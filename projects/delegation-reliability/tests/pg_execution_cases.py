"""Actual opt-in P1 v2/HTTP cases; typed case reads grant no action authority."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import threading
import time
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from psycopg import sql

from continuity_lab.execution_api import ExecutionClient, ExecutionLimits, open_execution_client
from continuity_lab.work_admin import install_work_schema, upgrade_work_schema_v2
from continuity_lab.work_api import (
    BearerToken,
    PostgresSettings,
    WorkClient,
    WorkDirectory,
    WorkError,
    WorkPayload,
    WorkPrincipal,
    WorkScope,
    open_work_client,
)
from delegation_reliability import (
    CaseSnapshot,
    DelegationCoordinator,
    DelegationRun,
    DelegationRunError,
    DelegationRunner,
    SpecialistClient,
    SpecialistEndpoint,
)
from delegation_reliability.contracts import (
    CAPABILITY,
    DelegationRequest,
    Scope,
    canonical,
    encode_request,
    parse_request,
    produce_request,
)
from delegation_reliability.security import EvidenceRecord

SCOPE = Scope("tenant_p3", "account_p3")
POLICY = canonical({"minimum_notice_days": 7, "policy_version": "policy_v1"})
OWNER_MODES = frozenset({"install", "upgrade", "owner-check", "cleanup"})
MODE_KEYS = {
    "install": {"P3_EXEC_SCHEMA"},
    "upgrade": {"P3_EXEC_SCHEMA"},
    "seed": {"P3_EXEC_SCHEMA", "P3_EXEC_TOKEN"},
    "exercise": {"P3_EXEC_SCHEMA", "P3_EXEC_TOKEN", "P3_EXEC_SPECIALIST_PORT", "P3_EXEC_BARRIERS"},
    "verify": {"P3_EXEC_SCHEMA", "P3_EXEC_TOKEN", "P3_EXEC_SPECIALIST_PORT", "P3_EXEC_PRIMARY_SHA"},
    "crash": {
        "P3_EXEC_SCHEMA",
        "P3_EXEC_TOKEN",
        "P3_EXEC_SPECIALIST_PORT",
        "P3_EXEC_CRASH_DEADLINE",
        "P3_EXEC_COMMIT_MARKER",
    },
    "verify-crash": {
        "P3_EXEC_SCHEMA",
        "P3_EXEC_TOKEN",
        "P3_EXEC_SPECIALIST_PORT",
        "P3_EXEC_CRASH_DEADLINE",
    },
    "owner-check": {"P3_EXEC_SCHEMA"},
    "cleanup": {"P3_EXEC_SCHEMA", "P3_EXEC_PROFILE_INSTALLED"},
}
BASE_KEYS = {
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
_ACTIVE_MODE: str | None = None
_DIAGNOSTIC_STAGE = "fixture"


def validate_environment(mode: str) -> None:
    password = "P3_EXEC_MIGRATION_PASSWORD" if mode in OWNER_MODES else "P3_EXEC_RUNTIME_PASSWORD"
    required = {"P3_EXEC_PG_PORT", password, *MODE_KEYS[mode]}
    if not required <= set(os.environ) or set(os.environ) - required - BASE_KEYS:
        raise AssertionError("unsafe_child_environment")


def settings(*, owner: bool = False) -> PostgresSettings:
    if _ACTIVE_MODE is None or owner != (_ACTIVE_MODE in OWNER_MODES):
        raise AssertionError("wrong_credential_role")
    schema = os.environ["P3_EXEC_SCHEMA"]
    if re.fullmatch(r"p1_work_p3exec_[0-9a-f]{32}", schema) is None:
        raise AssertionError("unsafe_schema")
    return PostgresSettings(
        port=int(os.environ["P3_EXEC_PG_PORT"]),
        schema=schema,
        user="continuity_migrator" if owner else "livekit_lab",
        password=os.environ["P3_EXEC_MIGRATION_PASSWORD" if owner else "P3_EXEC_RUNTIME_PASSWORD"],
    )


class Cases:
    def __init__(self, revision: int = 1) -> None:
        self.revision = revision

    async def snapshot(self, *, case_id: str) -> CaseSnapshot:
        return CaseSnapshot(SCOPE, case_id, self.revision, False)


def request(key: str, revision: int = 1, deadline: int | None = None) -> DelegationRequest:
    return produce_request(
        {
            "schema_version": 1,
            "kind": "delegation.request",
            "capability": CAPABILITY,
            "input_schema_version": 1,
            "scope": {"tenant_id": SCOPE.tenant_id, "account_id": SCOPE.account_id},
            "delegation_id": key,
            "case_id": "case_p3",
            "request_revision": revision,
            "context_snapshot": {
                "policy_version": "policy_v1",
                "policy_source_id": "policy_demo",
                "days_before_arrival": 14,
                "note": "Immutable issued synthetic policy input.",
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
            "deadline_at_ms": deadline
            if deadline is not None
            else time.time_ns() // 1_000_000 + 30000,
            "result_route": {"conversation_id": "conversation_p3"},
            "attempt": {"attempt_id": "proposed_" + key, "number": 1},
        }
    )


def directory(scope: WorkScope | None = None) -> tuple[WorkDirectory, BearerToken]:
    token = BearerToken(os.environ["P3_EXEC_TOKEN"])
    return WorkDirectory(
        {
            token: WorkPrincipal(
                "p3_execution_check", scope or WorkScope(SCOPE.tenant_id, SCOPE.account_id)
            )
        }
    ), token


def work_client() -> WorkClient:
    registrations, token = directory()
    return open_work_client(settings=settings(), directory=registrations, token=token)


def execution_client(hook: Callable[[str], None] | None = None) -> ExecutionClient:
    registrations, token = directory()
    return open_execution_client(
        settings=settings(), directory=registrations, token=token, harness_failpoint=hook
    )


def runner(
    cases: Cases, value: DelegationRequest, hook: Callable[[str], None] | None = None
) -> DelegationRunner:
    return DelegationRunner(
        executions=execution_client(hook),
        scope=SCOPE,
        owner_id=str(uuid4()),
        specialist=SpecialistClient(
            SpecialistEndpoint(int(os.environ["P3_EXEC_SPECIALIST_PORT"])),
            "Bearer " + os.environ["P3_EXEC_TOKEN"],
        ),
        case_authority=cases,
        evidence=(EvidenceRecord(SCOPE, value.evidence[0], POLICY),),
    )


async def barrier(name: str) -> None:
    path = Path(os.environ["P3_EXEC_BARRIERS"]) / (name + ".held")
    deadline = asyncio.get_running_loop().time() + 3
    while not path.exists():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("barrier_timeout")
        await asyncio.sleep(0.01)


def release(name: str) -> None:
    (Path(os.environ["P3_EXEC_BARRIERS"]) / (name + ".release")).touch(mode=0o600, exist_ok=True)


async def seed() -> dict[str, object]:
    work = work_client()
    try:
        value = request("delegation_primary")
        accepted = await work.submit(
            idempotency_key=value.delegation_id,
            payload=WorkPayload(CAPABILITY, encode_request(value), value.deadline_at_ms),
        )
        assert accepted.created
        return {"status": "passed", "payload_sha256": accepted.record.payload.sha256}
    finally:
        await work.close()
        assert work.pending_count == 0


async def exercise() -> dict[str, object]:
    cases = Cases()
    work = work_client()
    coordinator = DelegationCoordinator(executions=work, scope=SCOPE, case_authority=cases)
    owned: list[DelegationRunner] = []
    active_tasks: list[asyncio.Task[DelegationRun]] = []
    observed = []
    try:
        original = await coordinator.find("delegation_primary")
        assert original is not None
        main = runner(cases, original.request)
        owned.append(main)
        result = await main.run_once(original.record.work_id, "command_primary")
        assert (
            result.invoked
            and result.view.result is not None
            and result.view.result.eligible is True
        )
        assert result.view.applicability == "candidate" and result.recorded is not None
        assert result.view.execution.record.payload.body == encode_request(original.request)
        grant = result.view.execution.current_attempt
        assert grant is not None
        assert result.view.result.attempt_id == "attempt_" + grant.attempt_id.replace("-", "")
        assert original.request.attempt.attempt_id != result.view.result.attempt_id
        assert grant.record.payload.body == original.record.payload.body
        observed.extend(["v1_input_preserved_v2_issued_identity", "actual_grounded_policy_result"])
        again = await main.run_once(original.record.work_id, "command_primary")
        assert not again.invoked and again.view.result == result.view.result
        assert again.view.execution.attempts_issued == 1
        observed.append("duplicate_command_no_reinvocation")

        registrations, token = directory(WorkScope(SCOPE.tenant_id, "foreign"))
        foreign = open_execution_client(settings=settings(), directory=registrations, token=token)
        unused_http = SpecialistClient(
            SpecialistEndpoint(int(os.environ["P3_EXEC_SPECIALIST_PORT"])),
            "Bearer " + os.environ["P3_EXEC_TOKEN"],
        )
        try:
            try:
                DelegationRunner(
                    executions=foreign,
                    scope=SCOPE,
                    owner_id=str(uuid4()),
                    specialist=unused_http,
                    case_authority=cases,
                    evidence=(EvidenceRecord(SCOPE, original.request.evidence[0], POLICY),),
                )
            except DelegationRunError as error:
                assert error.code == "unauthorized"
            else:
                raise AssertionError("misbound_scope_accepted")
            try:
                await foreign.observe(work_id=original.record.work_id)
            except WorkError as error:
                assert error.code == "not_found"
            else:
                raise AssertionError("foreign_result_disclosed")
        finally:
            await unused_http.close()
            await foreign.close()
        observed.append("scope_forgery_zero_invocation")

        before = await coordinator.submit(request("delegation_cancel_before"))
        await coordinator.cancel(before.view.record.work_id, "cancel_before")
        try:
            await main.run_once(before.view.record.work_id, "command_cancel_before")
        except DelegationRunError as cancelled_error:
            assert cancelled_error.code == "expired"
        else:
            raise AssertionError("cancelled_work_invoked")
        assert (await main.inspect(before.view.record.work_id)).execution.attempts_issued == 0
        observed.append("cancel_before_issue_zero_attempts")

        cancelled = await coordinator.submit(request("delegation_cancel_during"))
        pending = asyncio.create_task(
            main.run_once(cancelled.view.record.work_id, "command_cancel_during")
        )
        active_tasks.append(pending)
        await barrier("cancel")
        receipt = await coordinator.cancel(cancelled.view.record.work_id, "cancel_during")
        assert receipt.disposition == "requested"
        release("cancel")
        historical = await pending
        assert historical.recorded is not None and historical.recorded.disposition == "cancelled"
        assert historical.view.result is not None and historical.view.result.eligible is True
        assert historical.view.applicability == "execution_ineligible"
        observed.append("cancel_during_http_known_result_historical")

        stale = await coordinator.submit(request("delegation_stale"))
        pending = asyncio.create_task(main.run_once(stale.view.record.work_id, "command_stale_a"))
        active_tasks.append(pending)
        await barrier("stale")
        probe = execution_client()
        try:
            deadline = asyncio.get_running_loop().time() + 3
            while (await probe.observe(work_id=stale.view.record.work_id)).status != "retryable":
                if asyncio.get_running_loop().time() >= deadline:
                    raise AssertionError("database_lease_not_expired")
                await asyncio.sleep(0.025)
        finally:
            await probe.close()
        replacement = runner(cases, stale.view.request)
        owned.append(replacement)
        current = await replacement.run_once(stale.view.record.work_id, "command_stale_b")
        assert current.recorded is not None and current.recorded.disposition == "eligible_at_commit"
        release("stale")
        older = await pending
        assert older.recorded is not None and older.recorded.disposition == "superseded"
        assert older.view.result == current.view.result
        assert older.view.applicability == "candidate"
        observed.append("expired_epoch_historical_cannot_replace_current")

        cases.revision = 2
        assert (await main.inspect(original.record.work_id)).applicability == "outdated"
        revised = await coordinator.submit(request("delegation_revision_b", 2))
        newer = await main.run_once(revised.view.record.work_id, "command_revision_b")
        assert newer.view.applicability == "candidate" and newer.view.result is not None
        assert newer.view.result.request_revision == 2
        observed.append("revision_a_outdated_b_useful_readonly")
        return {
            "status": "passed",
            "cases": observed,
            "primary_sha256": result.recorded.sha256,
            "primary_payload_sha256": original.record.payload.sha256,
        }
    finally:
        for name in ("cancel", "stale"):
            release(name)
        if active_tasks:
            await asyncio.gather(*active_tasks, return_exceptions=True)
        for item in owned:
            await item.close()
            assert item.pending_count == 0
        await coordinator.close()
        assert work.pending_count == 0


async def verify(*, crash: bool) -> dict[str, object]:
    cases = Cases(2)
    work = work_client()
    try:
        key = "delegation_crash" if crash else "delegation_primary"
        accepted = await work.find(idempotency_key=key)
        assert accepted is not None
        value = parse_request(accepted.payload.body)
        owned = runner(cases, value)
        try:
            view = await owned.inspect(accepted.work_id)
            assert view.result is not None and view.result.eligible is True
            assert view.execution.result is not None
            if crash:
                assert value.deadline_at_ms == int(os.environ["P3_EXEC_CRASH_DEADLINE"])
                assert view.applicability == "candidate"
            else:
                assert view.execution.result.sha256 == os.environ["P3_EXEC_PRIMARY_SHA"]
                assert view.applicability == "outdated"
            replay = await owned.run_once(
                accepted.work_id, "command_crash" if crash else "command_primary"
            )
            assert not replay.invoked and replay.view.result == view.result
            return {
                "status": "passed",
                "cases": [
                    "postcommit_sigkill_result_reconciliation"
                    if crash
                    else "fresh_process_original_result_read"
                ],
            }
        finally:
            await owned.close()
    finally:
        await work.close()


async def crash() -> None:
    cases = Cases(2)
    work = work_client()
    coordinator = DelegationCoordinator(executions=work, scope=SCOPE, case_authority=cases)
    value = request("delegation_crash", 2, int(os.environ["P3_EXEC_CRASH_DEADLINE"]))
    accepted = await coordinator.submit(value)

    def hold(stage: str) -> None:
        if stage == "complete.after_commit":
            with os.fdopen(
                os.open(
                    os.environ["P3_EXEC_COMMIT_MARKER"],
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                ),
                "w",
            ) as stream:
                stream.write(f"{os.getpid()}\n")
            if not threading.Event().wait(30):
                raise AssertionError("parent_did_not_kill")

    owned = runner(cases, value, hold)
    try:
        await owned.run_once(accepted.view.record.work_id, "command_crash")
    finally:
        await owned.close()
        await coordinator.close()


def owner_probe(*, cleanup: bool) -> dict[str, object]:
    global _DIAGNOSTIC_STAGE
    selected = settings(owner=True)
    with closing(selected.connect(application_name="continuity-test")) as connection:
        row = connection.execute(
            "SELECT pg_get_userbyid(nspowner) AS owner,obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=%s",
            [selected.schema],
        ).fetchone()
        if row is None:
            if cleanup and os.environ["P3_EXEC_PROFILE_INSTALLED"] == "0":
                return {"status": "passed", "schema_removed": True}
            raise AssertionError("missing_owned_profile")
        assert row["owner"] == "continuity_migrator"
        assert row["marker"] in (
            {"continuity-readonly-work-v1", "continuity-readonly-work-v2"}
            if cleanup
            else {"continuity-readonly-work-v2"}
        )
        if cleanup:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(selected.schema))
            )
            assert (
                connection.execute(
                    "SELECT 1 FROM pg_namespace WHERE nspname=%s", [selected.schema]
                ).fetchone()
                is None
            )
            return {"status": "passed", "schema_removed": True}
        counts: dict[str, int] = {}
        for table in (
            "accepted_work",
            "cancellation_commands",
            "issued_attempts",
            "attempt_results",
        ):
            counted = connection.execute(
                sql.SQL("SELECT count(*) AS count FROM {}.{}").format(
                    sql.Identifier(selected.schema), sql.Identifier(table)
                )
            ).fetchone()
            assert counted is not None and type(counted["count"]) is int
            counts[table] = counted["count"]
        _DIAGNOSTIC_STAGE = "owner_counts"
        assert counts == {
            "accepted_work": 6,
            "cancellation_commands": 2,
            "issued_attempts": 6,
            "attempt_results": 6,
        }
        _DIAGNOSTIC_STAGE = "owner_scope"
        foreign_row = connection.execute(
            sql.SQL(
                "SELECT count(*) AS count FROM {}.accepted_work WHERE tenant_id<>'tenant_p3' OR account_id<>'account_p3'"
            ).format(sql.Identifier(selected.schema))
        ).fetchone()
        assert foreign_row is not None and foreign_row["count"] == 0
        _DIAGNOSTIC_STAGE = "owner_result_identity"
        rows = connection.execute(
            sql.SQL(
                "SELECT r.body,r.sha256,r.disposition,a.attempt_id::text,w.body AS original FROM {}.attempt_results r JOIN {}.issued_attempts a USING(attempt_id) JOIN {}.accepted_work w ON w.work_id=a.work_id"
            ).format(*[sql.Identifier(selected.schema)] * 3)
        ).fetchall()
        dispositions: dict[str, int] = {}
        for item in rows:
            raw = bytes(item["body"])
            assert hashlib.sha256(raw).hexdigest() == item["sha256"]
            original = parse_request(bytes(item["original"]))
            decoded = json.loads(raw)
            assert decoded["attempt_id"] == "attempt_" + item["attempt_id"].replace("-", "")
            assert decoded["input_fingerprint"] == original.input_fingerprint
            assert decoded["scope"] == {
                "tenant_id": SCOPE.tenant_id,
                "account_id": SCOPE.account_id,
            }
            dispositions[item["disposition"]] = dispositions.get(item["disposition"], 0) + 1
        _DIAGNOSTIC_STAGE = "owner_dispositions"
        assert dispositions == {"eligible_at_commit": 4, "cancelled": 1, "superseded": 1}
        return {
            "status": "passed",
            "counts": counts,
            "foreign_records": 0,
            "dispositions": dispositions,
        }


def main() -> int:
    global _ACTIVE_MODE
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=tuple(MODE_KEYS))
    args = parser.parse_args()
    _ACTIVE_MODE = args.mode
    try:
        validate_environment(args.mode)
        if args.mode == "install":
            install_work_schema(settings(owner=True))
            value = {"status": "passed", "profile_version": 1}
        elif args.mode == "upgrade":
            upgrade_work_schema_v2(settings(owner=True), ExecutionLimits(lease_ms=1500))
            value = {"status": "passed", "profile_version": 2}
        elif args.mode == "seed":
            value = asyncio.run(seed())
        elif args.mode == "exercise":
            value = asyncio.run(exercise())
        elif args.mode == "verify":
            value = asyncio.run(verify(crash=False))
        elif args.mode == "verify-crash":
            value = asyncio.run(verify(crash=True))
        elif args.mode == "crash":
            asyncio.run(crash())
            raise AssertionError("crash_hook_not_reached")
        else:
            value = owner_probe(cleanup=args.mode == "cleanup")
        print(json.dumps(value, sort_keys=True))
        return 0
    except Exception:  # noqa: BLE001 - explicit fixture boundary has fixed diagnostics only
        print(json.dumps({"status": "failed", "code": _DIAGNOSTIC_STAGE}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
