"""Explicit synthetic action-race v4 fixtures/leased workers, never product composition.

This tooling alone imports P1 worker/migration internals. P3 product code consumes
public clients. No function loads credentials, resets application state or invokes
models; callers provision one marked UUID schema and private supplier fixture.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

from psycopg import Connection, sql

from continuity_lab.authorization import AuthenticatedActor
from continuity_lab.execution_models import TransitionConflict
from continuity_lab.lease_models import CoordinationPolicy
from continuity_lab.lifecycle_models import LifecycleState
from continuity_lab.managed_inquiry_worker import ManagedInquiryWorker
from continuity_lab.models import BookingChange
from continuity_lab.mutation_supplier import MutationSupplier, initialize_mutation_supplier
from continuity_lab.mutation_worker import MutationWorker
from continuity_lab.postgres_case import PostgresCaseAuthority
from continuity_lab.postgres_effects import PostgresEffects
from continuity_lab.postgres_leases import PostgresLeases
from continuity_lab.postgres_lifecycle import PostgresLifecycle
from continuity_lab.postgres_migrations import (
    activate_import,
    install_schema,
    stage_import,
    upgrade_v2,
    upgrade_v3,
    upgrade_v4,
)
from continuity_lab.postgres_settings import PostgresSettings, advisory_keys
from continuity_lab.postgres_store import PostgresExecutionStore
from continuity_lab.transfer import make_snapshot

ACTOR = AuthenticatedActor("p3_completion_user", "p3_completion_scope")
BOOKING = "DEMO-BK-001"
REQUEST = BookingChange(BOOKING, date(2030, 12, 10), True)
ALTERNATE = BookingChange(BOOKING, date(2030, 12, 11), True)
MARKER = "p3-action-race-case-fixture-v1"


def _owned(settings: PostgresSettings) -> None:
    if re.fullmatch(r"p3_completion_[0-9a-f]{32}", settings.schema) is None:
        raise ValueError("Only a new owned completion case schema is supported")


def install(settings: PostgresSettings, supplier: Path) -> dict[str, object]:
    """Owner only; empty validated booking schema and independent synthetic supplier."""
    _owned(settings)
    if settings.user != "continuity_migrator" or supplier.exists():
        raise ValueError("Explicit fresh owner preparation required")
    with closing(settings.connect(application_name="continuity-test")) as connection:
        if (
            connection.execute(
                "SELECT 1 FROM pg_namespace WHERE nspname=%s", [settings.schema]
            ).fetchone()
            is not None
        ):
            raise ValueError("Fixture schema must be new")
    install_schema(settings)
    # Mark the independently owned empty authority before later upgrades so a
    # failed later preparation still has an explicit safe cleanup identity.
    with closing(settings.connect(application_name="continuity-test")) as connection:
        connection.execute(
            sql.SQL("COMMENT ON SCHEMA {} IS {}").format(
                sql.Identifier(settings.schema), sql.Literal(MARKER)
            )
        )
    snapshot = make_snapshot([], [], [], migration_id=str(uuid4()))
    stage_import(settings, snapshot)
    activate_import(settings, snapshot.migration_id, snapshot.source_digest)
    upgrade_v2(settings)
    upgrade_v3(settings)
    upgrade_v4(settings, policy=CoordinationPolicy(20, 2, 100, 5))
    initialize_mutation_supplier(supplier, scope_id=ACTOR.scope_id)
    return {"status": "passed", "case_version": 4, "supplier": "synthetic_persistent"}


def inquire(settings: PostgresSettings, supplier: Path, task_id: str) -> dict[str, object]:
    """Runtime only; one actual v4-leased inquiry through existing worker authority."""
    _owned(settings)
    if settings.user != "livekit_lab":
        raise ValueError("Runtime fixture credentials required")
    executions = PostgresExecutionStore(settings)
    cases = PostgresCaseAuthority(executions)
    leases = PostgresLeases(executions)
    grant = leases.acquire(scope_id=ACTOR.scope_id, task_id=task_id, owner_id=str(uuid4()))
    try:
        lifecycle = PostgresLifecycle(executions, cases=cases, worker_lease=grant)
        value = ManagedInquiryWorker(lifecycle, MutationSupplier(supplier).inquiry_view()).run_one(
            scope_id=ACTOR.scope_id, task_id=task_id
        )
        if value.state != LifecycleState.INQUIRY_COMPLETE:
            raise AssertionError("Actual inquiry did not complete")
        return {"status": "passed", "state": value.state.value, "task_id": task_id}
    finally:
        leases.release(grant)


def mutate(
    settings: PostgresSettings,
    supplier: Path,
    task_id: str,
    *,
    failpoint: Callable[[str], None] | None = None,
) -> dict[str, object]:
    """Runtime only; execute an already committed exact P1 intent, never fabricate one."""
    _owned(settings)
    if settings.user != "livekit_lab":
        raise ValueError("Runtime fixture credentials required")
    executions = PostgresExecutionStore(settings)
    cases = PostgresCaseAuthority(executions)
    leases = PostgresLeases(executions)
    grant = leases.acquire(scope_id=ACTOR.scope_id, task_id=task_id, owner_id=str(uuid4()))
    try:
        effects = PostgresEffects(executions, cases=cases, worker_lease=grant)
        worker_code = "ok"
        try:
            value = MutationWorker(
                effects, MutationSupplier(supplier), failpoint=failpoint
            ).run_one(scope_id=ACTOR.scope_id, task_id=task_id)
        except TransitionConflict:
            worker_code = "transition_conflict"
            value = effects.get(scope_id=ACTOR.scope_id, task_id=task_id)
        if value is None:
            raise AssertionError("Actual mutation snapshot missing")
        return {
            "status": "passed",
            "effect_state": value.state.value,
            "worker_code": worker_code,
            "effect_id": value.intent.effect_id,
            "result": None if value.result is None else value.result.payload(),
        }
    finally:
        leases.release(grant)


def supplier_truth(supplier: Path) -> dict[str, object]:
    """Independent SQLite inspection; this is evidence, not supplier invocation authority."""
    with closing(sqlite3.connect(f"file:{supplier}?mode=ro", uri=True)) as connection:
        bookings = connection.execute(
            "SELECT scope_id,booking_reference,check_in,revision FROM bookings"
        ).fetchall()
        receipts = connection.execute(
            "SELECT scope_id,effect_id,result_json FROM mutation_receipts"
        ).fetchall()
        calls = connection.execute("SELECT count(*) FROM apply_calls").fetchone()[0]
        applied = connection.execute(
            "SELECT count(*) FROM apply_calls WHERE outcome='applied'"
        ).fetchone()[0]
    return {
        "status": "passed",
        "bookings": [list(row) for row in bookings],
        "mutation_receipts": [
            {"scope_id": row[0], "effect_id": row[1], "result": json.loads(row[2])}
            for row in receipts
        ],
        "applied_calls": applied,
        "all_apply_calls": calls,
    }


def cleanup(settings: PostgresSettings) -> dict[str, object]:
    """Owner only; remove this fixture after checking its marker and owner."""
    _owned(settings)
    if settings.user != "continuity_migrator":
        raise ValueError("Explicit owner cleanup required")
    with closing(settings.connect(application_name="continuity-test")) as connection:
        row = connection.execute(
            "SELECT pg_get_userbyid(nspowner) AS owner,obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=%s",
            [settings.schema],
        ).fetchone()
        if row is not None:
            if row != {"owner": "continuity_migrator", "marker": MARKER}:
                raise ValueError("Owned fixture marker mismatch")
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(settings.schema))
            )
    return {"status": "passed", "schema_removed": True}


def initialize_supplier(supplier: Path) -> None:
    """A distinct actual cooperating authority per schedule; no cross-quote drift."""
    if supplier.exists():
        raise ValueError("Supplier fixture must be fresh")
    initialize_mutation_supplier(supplier, scope_id=ACTOR.scope_id)


def marker(path: Path) -> None:
    """One complete exclusive PID marker, never an arbitrary process selector."""
    pending = path.with_name(path.name + "." + str(os.getpid()) + ".pending")
    fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(str(os.getpid()) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(pending, path, follow_symlinks=False)
    finally:
        pending.unlink(missing_ok=True)


class FixtureFailure(RuntimeError):
    """One fixed scheduling diagnostic, never a reflected database exception."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def lock_waiters(
    connection: Connection[dict[str, Any]], key1: int, key2: int
) -> list[dict[str, Any]]:
    # pg_locks is live; pg_stat_activity can retain an older transaction snapshot
    # taken before the prewarmed writer opens its command connection. Refresh only
    # statistics before each actual-key/role-filtered observation.
    connection.execute("SELECT pg_stat_clear_snapshot()")
    return connection.execute(
        "SELECT l.pid,pg_blocking_pids(l.pid) AS blockers "
        "FROM pg_locks l JOIN pg_stat_activity a USING(pid) "
        "WHERE l.locktype='advisory' AND l.classid=%s::oid AND l.objid=%s::oid "
        "AND l.objsubid=2 AND NOT l.granted AND a.usename='livekit_lab' ORDER BY l.pid",
        (key1 & 0xFFFFFFFF, key2 & 0xFFFFFFFF),
    ).fetchall()


def ordered_lock(settings: PostgresSettings, directory: Path, scenario: str) -> dict[str, object]:
    """Owner-only continuous observer: one waiter then real two-waiter soft chain.

    The parent prewarms both writers, releases them in the intended order and
    releases this lock only after the actual SQL graph marker. No interpreter is
    started during the unchanged 1000ms P1 lock timeout.
    """
    _owned(settings)
    if settings.user != "continuity_migrator" or scenario not in {"b_first", "a_first"}:
        raise ValueError("Explicit isolated owner lock required")
    key1, key2 = advisory_keys(settings.schema, "admission")
    name = "case_admission_" + scenario
    with (
        closing(settings.connect(application_name="continuity-test")) as connection,
        connection.transaction(),
    ):
        connection.execute("SELECT pg_advisory_xact_lock(%s,%s)", (key1, key2))
        owner = connection.info.backend_pid
        marker(directory / (name + ".reached"))
        first: int | None = None
        graph: list[dict[str, object]] = []
        deadline = time.monotonic() + 0.9
        while True:
            rows = lock_waiters(connection, key1, key2)
            if first is None and len(rows) == 1 and rows[0]["blockers"] == [owner]:
                first = int(rows[0]["pid"])
                marker(directory / ("first_wait_" + scenario + ".reached"))
            if first is not None and len(rows) == 2:
                second = next(row for row in rows if row["pid"] != first)
                first_row = next(row for row in rows if row["pid"] == first)
                if first_row["blockers"] == [owner] and set(second["blockers"]) == {
                    owner,
                    first,
                }:
                    graph = [
                        {"pid": int(row["pid"]), "blockers": list(row["blockers"])} for row in rows
                    ]
                    marker(directory / ("order_graph_" + scenario + ".reached"))
                    break
            if time.monotonic() >= deadline:
                raise FixtureFailure("lock_no_waiter" if first is None else "lock_chain_incomplete")
            time.sleep(0.001)
        release = directory / (name + ".released")
        while not release.exists():
            if time.monotonic() >= deadline:
                raise FixtureFailure("owner_lock_release_timeout")
            time.sleep(0.001)
        if release.read_text() != str(os.getpid()) + "\n":
            raise AssertionError("wrong_owner_lock_release")
    # Safe structural proof only; backend identities are bounded synthetic evidence.
    (directory / ("graph_" + scenario + ".json")).write_text(json.dumps(graph))
    return {
        "status": "passed",
        "order": "revision_first" if scenario == "b_first" else "intent_first",
        "waiters": 2,
        "blocking_graphs": 1,
    }


def expired(
    settings: PostgresSettings, task_id: str, work: PostgresSettings, work_id: str
) -> tuple[bool, bool]:
    """Actual database-clock evidence for this isolated case lease and work horizon."""
    _owned(settings)
    with closing(settings.connect(application_name="continuity-test")) as connection:
        row = connection.execute(
            sql.SQL(
                "SELECT (extract(epoch FROM clock_timestamp())*1000)::bigint >= w.deadline_at_ms AS work_expired, "
                "l.expires_at <= clock_timestamp() AS lease_expired FROM {}.accepted_work w "
                "CROSS JOIN {}.execution_leases l WHERE w.work_id=%s::uuid AND l.task_id=%s"
            ).format(sql.Identifier(work.schema), sql.Identifier(settings.schema)),
            (work_id, task_id),
        ).fetchone()
        if row is None:
            raise AssertionError("missing_expiry_authorities")
        return bool(row["work_expired"]), bool(row["lease_expired"])
