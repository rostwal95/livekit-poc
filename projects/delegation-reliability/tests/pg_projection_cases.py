"""Owned PostgreSQL projection fixtures; product imports only public P1 interfaces."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import re
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from uuid import UUID, uuid4

from psycopg import sql

from continuity_lab.case_control_api import CaseControlClient, open_case_control_client
from continuity_lab.execution_api import ExecutionLimits, open_execution_client
from continuity_lab.postgres_api import open_postgres_client
from continuity_lab.result_feed_api import open_result_feed_client
from continuity_lab.work_admin import (
    install_work_schema,
    upgrade_work_schema_v2,
    upgrade_work_schema_v3,
    upgrade_work_schema_v4,
)
from continuity_lab.work_api import (
    BearerToken,
    PostgresSettings,
    WorkDirectory,
    WorkPayload,
    WorkPrincipal,
    WorkScope,
    open_work_client,
)
from delegation_reliability import ActionBinding, ExactManagedCaseAuthority, ProjectionProjector
from delegation_reliability.contracts import (
    Attempt,
    DelegationRequest,
    Scope,
    canonical,
    encode_request,
    encode_result,
    parse_result,
    produce_request,
)
from delegation_reliability.projection_admin import install_projection_schema
from delegation_reliability.projection_api import open_projection_client
from delegation_reliability.projection_models import (
    ProjectionBinding,
    ProjectionError,
    ProjectionLimits,
    parse_projected,
)
from delegation_reliability.security import EvidenceRecord

CASES = (
    "v3_history_adopted_stable_source",
    "invalid_result_quarantined",
    "valid_result_after_quarantine",
    "precommit_kill_fresh_resume",
    "concurrent_batch_original_replay",
    "case_only_change_preserves_asof",
    "postcommit_kill_fresh_original",
    "retention_capacity_no_advance",
    "foreign_scope_zero_disclosure",
    "source_uuid_mismatch_rejected",
    "independent_source_projection_zero_intents",
    "cleanup_ownership",
)
OWNER_MODES = {"install", "upgrade", "locks", "owner-check", "cleanup"}
COMMON = {
    "P3_PROJECT_WORK_SCHEMA",
    "P3_PROJECT_CASE_SCHEMA",
    "P3_PROJECT_SCHEMA",
    "P3_PROJECT_DIRECTORY",
}
MODES = {
    "install",
    "seed",
    "upgrade",
    "crash-before",
    "resume",
    "race-a",
    "race-b",
    "locks",
    "crash-after",
    "verify",
    "owner-check",
    "cleanup",
}
BASE = {
    "PATH",
    "HOME",
    "TMPDIR",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "SYSTEMROOT",
    "__CF_USER_TEXT_ENCODING",
    "NO_COLOR",
    "CI",
}
SCOPE = Scope("tenant_p3", "account_p3")
POLICY = canonical({"minimum_notice_days": 7, "policy_version": "policy_v1"})
MODE = ""
STAGE = "fixture"


def helper() -> ModuleType:
    path = Path(__file__).resolve().parents[3] / "local-setup/scripts/p3_case_fixture.py"
    spec = importlib.util.spec_from_file_location("p3_projection_case_helper", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HELPER = helper()


def folder() -> Path:
    value = Path(os.environ["P3_PROJECT_DIRECTORY"])
    assert value.is_absolute() and value.is_dir() and not value.is_symlink()
    return value


def save(name: str, value: object) -> None:
    raw = (json.dumps(value, sort_keys=True) + "\n").encode()
    assert len(raw) < 32768
    fd = os.open(folder() / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)


def load(name: str) -> dict[str, object]:
    value = json.loads((folder() / name).read_text())
    assert type(value) is dict
    return value


def settings(kind: str = "work", *, owner: bool = False, cap: bool = False) -> PostgresSettings:
    assert owner == (MODE in OWNER_MODES)
    schema = os.environ[
        {
            "work": "P3_PROJECT_WORK_SCHEMA",
            "case": "P3_PROJECT_CASE_SCHEMA",
            "projection": "P3_PROJECT_SCHEMA",
        }[kind]
    ]
    pattern = {
        "work": r"p1_work_projection_[0-9a-f]{32}",
        "case": r"p3_completion_[0-9a-f]{32}",
        "projection": r"p3_projection_[0-9a-f]{32}",
    }[kind]
    assert re.fullmatch(pattern, schema)
    if cap:
        assert kind == "projection"
        schema += "_cap"
    return PostgresSettings(
        port=int(os.environ["P3_PROJECT_PG_PORT"]),
        schema=schema,
        user="continuity_migrator" if owner else "livekit_lab",
        password=os.environ[
            "P3_PROJECT_OWNER_PASSWORD" if owner else "P3_PROJECT_RUNTIME_PASSWORD"
        ],
    )


def directory(*, foreign: bool = False) -> tuple[WorkDirectory, BearerToken]:
    token = BearerToken(os.environ["P3_PROJECT_TOKEN"])
    scope = (
        WorkScope("foreign", "private") if foreign else WorkScope(SCOPE.tenant_id, SCOPE.account_id)
    )
    return WorkDirectory({token: WorkPrincipal("projection_actor", scope)}), token


def control() -> CaseControlClient:
    return open_case_control_client(
        actor=HELPER.ACTOR,
        token=BearerToken(os.environ["P3_PROJECT_TOKEN"]),
        settings=settings("case"),
        quote_database=folder() / "supplier.sqlite3",
    )


def cases(client: CaseControlClient) -> ExactManagedCaseAuthority:
    value = load("case.json")
    return ExactManagedCaseAuthority(
        client,
        scope=SCOPE,
        bindings=(
            ActionBinding(
                "case_projection",
                str(value["task_id"]),
                str(value["case_id"]),
                HELPER.ACTOR.actor_id,
                HELPER.ACTOR.scope_id,
                settings("case").schema,
            ),
        ),
    )


def request(number: int) -> DelegationRequest:
    return produce_request(
        {
            "schema_version": 1,
            "kind": "delegation.request",
            "capability": "booking.evaluate_policy",
            "input_schema_version": 1,
            "scope": {"tenant_id": SCOPE.tenant_id, "account_id": SCOPE.account_id},
            "delegation_id": "projection_" + str(number),
            "case_id": "case_projection",
            "request_revision": 2,
            "context_snapshot": {
                "policy_version": "policy_v1",
                "policy_source_id": "policy_demo",
                "days_before_arrival": 14,
                "note": "Explicit synthetic projection fixture.",
            },
            "evidence": [
                {
                    "source_id": "policy_demo",
                    "version": "source_v1",
                    "sha256": hashlib.sha256(POLICY).hexdigest(),
                    "media_type": "application/json",
                    "byte_length": len(POLICY),
                    "width": None,
                    "height": None,
                }
            ],
            "deadline_at_ms": time.time_ns() // 1_000_000 + 60000,
            "result_route": {"conversation_id": "conversation_projection"},
            "attempt": {"attempt_id": "attempt_proposed", "number": 1},
        }
    )


def policy_result(value: DelegationRequest) -> bytes:
    data = json.loads(
        (Path(__file__).resolve().parents[3] / "contracts/delegation/v1.json").read_text()
    )
    result = parse_result(canonical(data["result"]))
    return encode_result(
        replace(
            result,
            scope=value.scope,
            delegation_id=value.delegation_id,
            case_id=value.case_id,
            request_revision=value.request_revision,
            input_fingerprint=value.input_fingerprint,
            attempt_id=value.attempt.attempt_id,
            completed_at_ms=time.time_ns() // 1_000_000,
        )
    )


async def seed() -> dict[str, object]:
    client = open_postgres_client(
        actor=HELPER.ACTOR,
        token=BearerToken(os.environ["P3_PROJECT_TOKEN"]),
        settings=settings("case"),
        quote_database=folder() / "supplier.sqlite3",
    )
    ctl = control()
    registrations, token = directory()
    work = open_work_client(settings=settings(), directory=registrations, token=token)
    execution = open_execution_client(settings=settings(), directory=registrations, token=token)
    try:
        case = await client.submit(idempotency_key="projection_case", request=HELPER.REQUEST)
        save("case.json", {"task_id": case.task_id, "case_id": case.case_id})
        await asyncio.to_thread(
            HELPER.inquire, settings("case"), folder() / "supplier.sqlite3", case.task_id
        )
        await ctl.revise(task_id=case.task_id, expected_revision=0, request=HELPER.ALTERNATE)
        await ctl.revise(task_id=case.task_id, expected_revision=1, request=HELPER.REQUEST)
        originals = []
        for number in range(4):
            value = request(number)
            accepted = await work.submit(
                idempotency_key=value.delegation_id,
                payload=WorkPayload(
                    "booking.evaluate_policy", encode_request(value), value.deadline_at_ms
                ),
            )
            grant = (
                await execution.issue(
                    work_id=accepted.record.work_id,
                    owner_id=str(uuid4()),
                    command_id="projection_issue_" + str(number),
                )
            ).attempt
            transport = replace(
                value, attempt=Attempt("attempt_" + UUID(grant.attempt_id).hex, grant.number)
            )
            body = b"{}" if number == 0 else policy_result(transport)
            result = await execution.complete(attempt=grant, body=body)
            assert result.disposition == "eligible_at_commit"
            originals.append(
                {
                    "work_id": accepted.record.work_id,
                    "attempt_id": grant.attempt_id,
                    "issue_command_id": grant.command_id,
                    "tenant_id": SCOPE.tenant_id,
                    "account_id": SCOPE.account_id,
                    "result_sha256": result.sha256,
                    "request_sha256": accepted.record.payload.sha256,
                    "delegation_id": value.delegation_id,
                }
            )
            await asyncio.sleep(0.005)
        save("originals.json", {"results": originals})
    finally:
        await asyncio.gather(client.close(), ctl.close(), work.close(), execution.close())
    return {"status": "passed", "results": 4}


def upgrade() -> dict[str, object]:
    upgrade_work_schema_v4(settings(owner=True))
    with closing(settings(owner=True).connect(application_name="continuity-test")) as connection:
        row = connection.execute(
            sql.SQL("SELECT source_id::text FROM {}.result_feed_source").format(
                sql.Identifier(settings(owner=True).schema)
            )
        ).fetchone()
        assert row is not None
        source = str(row["source_id"])
        events = connection.execute(
            sql.SQL("SELECT sequence,origin FROM {}.result_feed_events ORDER BY sequence").format(
                sql.Identifier(settings(owner=True).schema)
            )
        ).fetchall()
        assert (
            len(events) == 4
            and [r["sequence"] for r in events] == [1, 2, 3, 4]
            and all(r["origin"] == "adopted_history" for r in events)
        )
    binding = ProjectionBinding(source, WorkScope(SCOPE.tenant_id, SCOPE.account_id))
    install_projection_schema(
        settings("projection", owner=True), binding=binding, limits=ProjectionLimits(8)
    )
    install_projection_schema(
        settings("projection", owner=True, cap=True), binding=binding, limits=ProjectionLimits(1)
    )
    upgrade_work_schema_v4(settings(owner=True))
    install_projection_schema(
        settings("projection", owner=True), binding=binding, limits=ProjectionLimits(8)
    )
    save("source.json", {"source_id": source})
    return {"status": "passed", "work_version": 4, "projection_version": 1, "cases": [CASES[0]]}


def source() -> str:
    return str(load("source.json")["source_id"])


def projector(
    ctl: CaseControlClient, *, cap: bool = False, hook: Callable[[str], None] | None = None
) -> ProjectionProjector:
    registrations, token = directory()
    value = request(0)
    return ProjectionProjector(
        events=open_result_feed_client(settings=settings(), directory=registrations, token=token),
        executions=open_execution_client(settings=settings(), directory=registrations, token=token),
        projections=open_projection_client(
            settings=settings("projection", cap=cap),
            directory=registrations,
            token=token,
            source_id=source(),
            harness_failpoint=hook,
        ),
        scope=SCOPE,
        evidence=(EvidenceRecord(SCOPE, value.evidence[0], POLICY),),
        case_authority=cases(ctl),
        timeout_ms=10000,
    )


def hold(point: str) -> None:
    expected = {
        "crash-before": "projection.before_commit",
        "race-a": "projection.before_commit",
        "crash-after": "projection.after_commit",
    }[MODE]
    if point != expected:
        return
    name = {
        "crash-before": "before_commit",
        "race-a": "race_commit",
        "crash-after": "after_commit",
    }[MODE]
    reached = Path(os.environ["P3_PROJECT_BARRIER"])
    assert reached == folder() / (name + ".reached")
    fd = os.open(reached, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(str(os.getpid()) + "\n")
    deadline = time.monotonic() + 8
    released = folder() / (name + ".released")
    while not released.exists():
        assert time.monotonic() < deadline, "barrier_timeout"
        time.sleep(0.005)
    assert released.read_text() == str(os.getpid()) + "\n"


async def run_projection_mode() -> dict[str, object]:
    ctl = control()
    client = projector(
        ctl, hook=hold if MODE in {"crash-before", "race-a", "crash-after"} else None
    )
    try:
        if MODE in {"crash-before", "crash-after"}:
            await client.project_once(limit=1)
            raise AssertionError("crash_not_observed")
        if MODE == "resume":
            point = await client._projections.checkpoint()
            assert point.sequence == 0
            first = await client.project_once(limit=1)
            assert first.rows[0].validation == "rejected" and first.after.sequence == 1
            second = await client.project_once(limit=1)
            row = second.rows[0]
            assert row.validation == "validated" and row.observation is not None
            assert (
                row.observation.applicability == "candidate" and row.observation.case_revision == 2
            )
            save("row2.json", row.payload())
            case = load("case.json")
            await ctl.revise(
                task_id=str(case["task_id"]), expected_revision=2, request=HELPER.ALTERNATE
            )
            await ctl.revise(
                task_id=str(case["task_id"]), expected_revision=3, request=HELPER.REQUEST
            )
            same = await client._projections.get(
                work_id=row.event.work_id, attempt_id=row.event.attempt_id
            )
            assert same is not None and same.canonical() == row.canonical()
            save("resume.json", {"checkpoint": 2, "case_revision": 4})
            return {"status": "passed", "cases": [CASES[1], CASES[2], CASES[3], CASES[5]]}
        batch = await client.project_once(limit=1)
        assert (
            batch.rows[0].observation is not None and batch.rows[0].observation.case_revision == 4
        )
        assert batch.rows[0].observation.applicability == "outdated"
        if MODE == "race-a":
            assert not batch.reconciled and (batch.before.sequence, batch.after.sequence) == (2, 3)
            save("race-a.json", batch.rows[0].payload())
            return {"status": "passed", "cases": []}
        assert (
            MODE == "race-b"
            and batch.reconciled
            and (batch.before.sequence, batch.after.sequence) == (3, 3)
        )
        deadline = time.monotonic() + 1
        while not (folder() / "race-a.json").exists():
            assert time.monotonic() < deadline
            await asyncio.sleep(0.005)
        assert batch.rows[0].payload() == load("race-a.json")
        save("race-b.json", batch.rows[0].payload())
        return {"status": "passed", "cases": [CASES[4]]}
    finally:
        await asyncio.gather(client.close(), ctl.close())


def locks() -> dict[str, object]:
    value = settings("projection", owner=True)
    with closing(value.connect(application_name="continuity-test")) as connection:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            rows = connection.execute(
                """SELECT a.pid,pg_blocking_pids(a.pid) AS blockers FROM pg_stat_activity a
                WHERE a.datname=current_database() AND a.usename='livekit_lab'
                AND EXISTS(SELECT 1 FROM pg_locks l JOIN pg_class c ON c.oid=l.relation JOIN pg_namespace n ON n.oid=c.relnamespace
                           WHERE l.pid=a.pid AND n.nspname=%s AND c.relname='projection_checkpoint')""",
                [value.schema],
            ).fetchall()
            pids = {r["pid"] for r in rows}
            if any(any(pid in pids for pid in r["blockers"]) for r in rows):
                return {"status": "passed", "blocked": True}
            time.sleep(0.005)
    raise AssertionError("sql_contention_not_observed")


async def verify() -> dict[str, object]:
    ctl = control()
    client = projector(ctl)
    cap = projector(ctl, cap=True)
    try:
        assert (await client._projections.checkpoint()).sequence == 4
        originals = load("originals.json")["results"]
        assert type(originals) is list
        last = originals[3]
        assert type(last) is dict
        row = await client._projections.get(work_id=last["work_id"], attempt_id=last["attempt_id"])
        assert (
            row is not None
            and row.validation == "validated"
            and row.event.result_sha256 == last["result_sha256"]
        )
        assert row.observation is not None and row.observation.case_revision == 4
        assert (await client.project_once()).rows == ()
        save("row4.json", row.payload())
        assert (await cap.project_once(limit=1)).after.sequence == 1
        try:
            await cap.project_once(limit=1)
            raise AssertionError("capacity_accepted")
        except ProjectionError as error:
            assert error.code == "capacity"
        assert (await cap._projections.checkpoint()).sequence == 1
        registrations, token = directory(foreign=True)
        for foreign_source in (False, True):
            try:
                open_projection_client(
                    settings=settings("projection"),
                    directory=registrations if not foreign_source else directory()[0],
                    token=token,
                    source_id=str(uuid4()) if foreign_source else source(),
                )
                raise AssertionError("wrong_binding_accepted")
            except ProjectionError as error:
                assert error.code == ("source_mismatch" if foreign_source else "unauthorized")
        return {"status": "passed", "cases": [CASES[6], CASES[7], CASES[8], CASES[9]]}
    finally:
        await asyncio.gather(client.close(), cap.close(), ctl.close())


def owner_check() -> dict[str, object]:
    with closing(settings(owner=True).connect(application_name="continuity-test")) as connection:
        ws = sql.Identifier(settings(owner=True).schema)
        ps = sql.Identifier(settings("projection", owner=True).schema)
        rows = connection.execute(
            sql.SQL("""SELECT p.*,e.event_id::text AS source_event_id,s.source_id::text AS source_uuid,
            e.sequence AS source_sequence,e.work_id::text AS source_work_id,e.attempt_id::text AS source_attempt_id,
            e.tenant_id AS source_tenant,e.account_id AS source_account,i.command_id AS source_command,
            a.sha256 AS source_sha,a.body,a.sha256,w.body AS request_body,w.sha256 AS request_sha,w.idempotency_key,
            w.tenant_id AS accepted_tenant,w.account_id AS accepted_account
            FROM {}.projected_results p JOIN {}.result_feed_events e ON e.sequence=p.event_sequence
            JOIN {}.attempt_results a ON a.attempt_id=p.attempt_id AND a.work_id=e.work_id AND a.attempt_id=e.attempt_id
            AND a.tenant_id=e.tenant_id AND a.account_id=e.account_id
            JOIN {}.accepted_work w ON w.work_id=p.work_id AND w.work_id=e.work_id
            JOIN {}.issued_attempts i ON i.attempt_id=a.attempt_id AND i.work_id=w.work_id
            AND i.tenant_id=w.tenant_id AND i.account_id=w.account_id CROSS JOIN {}.result_feed_source s
            ORDER BY p.event_sequence""").format(ps, ws, ws, ws, ws, ws)
        ).fetchall()
        assert len(rows) == 4
        originals = load("originals.json")["results"]
        assert type(originals) is list and len(originals) == 4
        for index, value in enumerate(rows):
            before = originals[index]
            assert type(before) is dict
            projected = parse_projected(value["body_json"].encode())
            assert (
                projected.event.event_id == value["source_event_id"]
                and projected.event.source_id == value["source_uuid"] == source()
            )
            assert projected.event.sequence == value["source_sequence"]
            assert projected.event.work_id == value["source_work_id"] == before["work_id"]
            assert projected.event.attempt_id == value["source_attempt_id"] == before["attempt_id"]
            assert (
                projected.event.issue_command_id
                == value["source_command"]
                == before["issue_command_id"]
            )
            assert projected.request_sha256 == before["request_sha256"]
            assert projected.event.result_sha256 == before["result_sha256"]
            assert value["idempotency_key"] == before["delegation_id"]
            assert (
                value["source_tenant"]
                == value["accepted_tenant"]
                == before["tenant_id"]
                == SCOPE.tenant_id
            )
            assert (
                value["source_account"]
                == value["accepted_account"]
                == before["account_id"]
                == SCOPE.account_id
            )

            assert (
                projected.event.result_sha256
                == value["source_sha"]
                == value["sha256"]
                == hashlib.sha256(bytes(value["body"])).hexdigest()
            )
            assert (
                projected.request_sha256
                == value["request_sha"]
                == hashlib.sha256(bytes(value["request_body"])).hexdigest()
            )
            assert projected.event.scope == WorkScope(SCOPE.tenant_id, SCOPE.account_id)
            assert projected.validation == (
                "rejected" if projected.event.sequence == 1 else "validated"
            )
            assert value["body_sha256"] == hashlib.sha256(value["body_json"].encode()).hexdigest()
        assert json.loads(rows[1]["body_json"]) == load("row2.json")
        assert json.loads(rows[2]["body_json"]) == load("race-a.json") == load("race-b.json")
        assert json.loads(rows[3]["body_json"]) == load("row4.json")
        for table in ("result_actions", "result_delivery_intents", "result_delivery_receipts"):
            row = connection.execute(
                sql.SQL("SELECT count(*) AS count FROM {}.{}").format(ws, sql.Identifier(table))
            ).fetchone()
            assert row is not None and row["count"] == 0
    with closing(
        settings("case", owner=True).connect(application_name="continuity-test")
    ) as connection:
        for table in ("action_intents", "mutation_effects"):
            row = connection.execute(
                sql.SQL("SELECT count(*) AS count FROM {}.{}").format(
                    sql.Identifier(settings("case", owner=True).schema), sql.Identifier(table)
                )
            ).fetchone()
            assert row is not None and row["count"] == 0
    assert HELPER.supplier_truth(folder() / "supplier.sqlite3")["applied_calls"] == 0
    return {"status": "passed", "cases": [CASES[10]]}


def cleanup() -> dict[str, object]:
    for kind, cap, markers in (
        ("projection", False, {"delegation-result-projection-v1"}),
        ("projection", True, {"delegation-result-projection-v1"}),
        (
            "work",
            False,
            {
                "continuity-readonly-work-v1",
                "continuity-readonly-work-v2",
                "continuity-readonly-work-v3",
                "continuity-readonly-work-v4",
            },
        ),
    ):
        value = settings(kind, owner=True, cap=cap)
        with closing(value.connect(application_name="continuity-test")) as connection:
            row = connection.execute(
                "SELECT pg_get_userbyid(nspowner) AS owner,obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=%s",
                [value.schema],
            ).fetchone()
            if row is not None:
                assert row["owner"] == "continuity_migrator" and row["marker"] in markers
                connection.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(value.schema))
                )
            assert (
                connection.execute(
                    "SELECT 1 FROM pg_namespace WHERE nspname=%s", [value.schema]
                ).fetchone()
                is None
            )
    HELPER.cleanup(settings("case", owner=True))
    return {"status": "passed", "schemas_removed": True}


def main() -> int:
    global MODE, STAGE
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=sorted(MODES))
    MODE = parser.parse_args().mode
    try:
        owner = MODE in OWNER_MODES
        required = COMMON | {
            "P3_PROJECT_PG_PORT",
            "P3_PROJECT_OWNER_PASSWORD" if owner else "P3_PROJECT_RUNTIME_PASSWORD",
        }
        if not owner:
            required.add("P3_PROJECT_TOKEN")
        if MODE in {"crash-before", "race-a", "crash-after"}:
            required.add("P3_PROJECT_BARRIER")
        assert required <= set(os.environ) and not (set(os.environ) - required - BASE)
        STAGE = MODE
        if MODE == "install":
            install_work_schema(settings(owner=True))
            upgrade_work_schema_v2(
                settings(owner=True), limits=ExecutionLimits(max_active=2, lease_ms=10000)
            )
            upgrade_work_schema_v3(settings(owner=True))
            HELPER.install(settings("case", owner=True), folder() / "supplier.sqlite3")
            report = {"status": "passed", "work_version": 3, "case_version": 4}
        elif MODE == "upgrade":
            report = upgrade()
        elif MODE == "locks":
            report = locks()
        elif MODE == "owner-check":
            report = owner_check()
        elif MODE == "cleanup":
            report = cleanup()
        elif MODE == "seed":
            report = asyncio.run(seed())
        elif MODE == "verify":
            report = asyncio.run(verify())
        else:
            report = asyncio.run(run_projection_mode())
        print(json.dumps(report))
        return 0
    except Exception:  # noqa: BLE001 - fixed fixture stage, no credential or dependency text
        print(json.dumps({"status": "failed", "code": STAGE}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
