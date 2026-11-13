"""Explicit synthetic v4 fixture/leased workers for P3 gates, never product composition.

This tooling alone imports P1 worker/migration internals. P3 product code consumes
public clients. No function loads credentials, resets application state or invokes
models; callers provision one marked UUID schema and private supplier fixture.
"""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path
from uuid import uuid4

from psycopg import sql

from continuity_lab.authorization import AuthenticatedActor
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
from continuity_lab.postgres_settings import PostgresSettings
from continuity_lab.postgres_store import PostgresExecutionStore
from continuity_lab.transfer import make_snapshot

ACTOR = AuthenticatedActor("p3_completion_user", "p3_completion_scope")
BOOKING = "DEMO-BK-001"
REQUEST = BookingChange(BOOKING, date(2030, 12, 10), True)
ALTERNATE = BookingChange(BOOKING, date(2030, 12, 11), True)
MARKER = "p3-completion-case-fixture-v1"


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
    upgrade_v4(settings, policy=CoordinationPolicy(20, 2, 100, 30))
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


def mutate(settings: PostgresSettings, supplier: Path, task_id: str) -> dict[str, object]:
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
        value = MutationWorker(effects, MutationSupplier(supplier)).run_one(
            scope_id=ACTOR.scope_id, task_id=task_id
        )
        if value is None or value.result is None:
            raise AssertionError("Actual mutation result missing")
        return {
            "status": "passed",
            "effect_state": value.state.value,
            "effect_id": value.intent.effect_id,
            "result": value.result.payload(),
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
