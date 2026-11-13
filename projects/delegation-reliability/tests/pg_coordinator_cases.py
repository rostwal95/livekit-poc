"""Explicit installed-consumer PostgreSQL/socket fixture, outside unittest discovery.

CaseAuthorityPort here is a typed synthetic read preflight, not a managed booking
case proof. HTTP probes are independent of the P1 accepted-work record: no issued
attempt, coordinator invocation, delivery, action or recovering scheduler is claimed.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import threading
import time
from collections.abc import Awaitable, Callable
from contextlib import closing
from pathlib import Path

from psycopg import sql

from continuity_lab.work_admin import WorkLimits, install_work_schema
from continuity_lab.work_api import (
    BearerToken,
    PostgresSettings,
    WorkDirectory,
    WorkError,
    WorkPrincipal,
    WorkScope,
    open_work_client,
)
from delegation_reliability import (
    CaseSnapshot,
    CoordinatorError,
    DelegationCoordinator,
    SpecialistClient,
    SpecialistEndpoint,
    SpecialistHttpError,
)
from delegation_reliability.contracts import (
    CAPABILITY,
    ContractError,
    DelegationRequest,
    Scope,
    canonical,
    encode_request,
    produce_request,
)
from delegation_reliability.security import EvidenceRecord, verify_policy_facts

SCOPE = Scope("tenant_p3", "account_p3")
POLICY = canonical({"minimum_notice_days": 7, "policy_version": "policy_v1"})


OWNER_MODES = frozenset({"install", "owner-check", "cleanup"})
MODE_CONTEXT_KEYS = {
    "install": {"P3_CHECK_SCHEMA"},
    "owner-check": {"P3_CHECK_SCHEMA"},
    "cleanup": {"P3_CHECK_SCHEMA", "P3_CHECK_PROFILE_INSTALLED"},
    "exercise": {
        "P3_CHECK_SCHEMA",
        "P3_CHECK_TOKEN",
        "P3_CHECK_SPECIALIST_PORT",
        "P3_CHECK_RELEASE",
    },
    "verify": {"P3_CHECK_SCHEMA", "P3_CHECK_TOKEN", "P3_CHECK_PRIMARY_SHA256"},
    "crash": {
        "P3_CHECK_SCHEMA",
        "P3_CHECK_TOKEN",
        "P3_CHECK_CRASH_DEADLINE",
        "P3_CHECK_COMMIT_MARKER",
    },
    "verify-crash": {"P3_CHECK_SCHEMA", "P3_CHECK_TOKEN", "P3_CHECK_CRASH_DEADLINE"},
}
_ACTIVE_MODE: str | None = None


def validate_environment(mode: str) -> None:
    base = {
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
    password = "P3_MIGRATION_PASSWORD" if mode in OWNER_MODES else "P3_RUNTIME_PASSWORD"
    required = {"P3_POSTGRES_PORT", password, *MODE_CONTEXT_KEYS[mode]}
    if not required <= set(os.environ) or set(os.environ) - required - base:
        raise AssertionError("unsafe_child_environment")


class SyntheticCasePreflight:
    """Fixed trusted read fixture; no claim of atomic or managed-case authority."""

    async def snapshot(self, *, case_id: str) -> CaseSnapshot:
        return CaseSnapshot(SCOPE, case_id, 1, False)


def settings(*, owner: bool = False) -> PostgresSettings:
    if _ACTIVE_MODE is None or owner != (_ACTIVE_MODE in OWNER_MODES):
        raise AssertionError("credential_role_not_allowed_for_mode")
    schema = os.environ["P3_CHECK_SCHEMA"]
    if re.fullmatch(r"p1_work_p3_[0-9a-f]{32}", schema) is None:
        raise AssertionError("unsafe_schema")
    return PostgresSettings(
        host="127.0.0.1",
        port=int(os.environ["P3_POSTGRES_PORT"]),
        dbname="livekit_lab",
        schema=schema,
        user="continuity_migrator" if owner else "livekit_lab",
        password=os.environ["P3_MIGRATION_PASSWORD" if owner else "P3_RUNTIME_PASSWORD"],
    )


def request(key: str, *, deadline: int | None = None) -> DelegationRequest:
    return produce_request(
        {
            "schema_version": 1,
            "kind": "delegation.request",
            "capability": CAPABILITY,
            "input_schema_version": 1,
            "scope": {"tenant_id": SCOPE.tenant_id, "account_id": SCOPE.account_id},
            "delegation_id": key,
            "case_id": "case_p3",
            "request_revision": 1,
            "context_snapshot": {
                "policy_version": "policy_v1",
                "policy_source_id": "policy_demo",
                "days_before_arrival": 14,
                "note": "Immutable synthetic acceptance.",
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
            "attempt": {"attempt_id": "attempt_" + key, "number": 1},
        }
    )


def directory(scope: Scope = SCOPE) -> tuple[WorkDirectory, BearerToken]:
    token = BearerToken(os.environ["P3_CHECK_TOKEN"])
    return WorkDirectory(
        {token: WorkPrincipal("p3_check_actor", WorkScope(scope.tenant_id, scope.account_id))}
    ), token


async def coordinator(
    *, scope: Scope = SCOPE, hook: Callable[[str], None] | None = None
) -> DelegationCoordinator:
    registrations, token = directory(scope)
    client = await asyncio.to_thread(
        open_work_client,
        settings=settings(),
        directory=registrations,
        token=token,
        harness_failpoint=hook,
    )
    return DelegationCoordinator(
        executions=client, scope=scope, case_authority=SyntheticCasePreflight()
    )


async def expect_error(awaitable: Awaitable[object], code: str) -> None:
    try:
        await awaitable
    except (CoordinatorError, WorkError, SpecialistHttpError) as error:
        assert error.code == code
    else:
        raise AssertionError("expected_safe_error")


async def exercise() -> dict[str, object]:
    cases = []
    reached, release = threading.Event(), threading.Event()

    def snapshot_hook(stage: str) -> None:
        if stage == "submit.before_commit":
            reached.set()
            if not release.wait(3):
                raise AssertionError("snapshot_release_timeout")

    client = await coordinator(hook=snapshot_hook)
    try:
        original = request("delegation_primary")
        pending = asyncio.create_task(client.submit(original))
        try:
            assert await asyncio.to_thread(reached.wait, 2)
            object.__setattr__(original.context_snapshot, "note", "MUTATED_PRIVATE_SENTINEL")
        finally:
            release.set()
        accepted = await pending
        assert accepted.created
        body = accepted.view.record.payload.body
        assert b"MUTATED_PRIVATE_SENTINEL" not in body
        assert encode_request(accepted.view.request) == body
        assert accepted.view.record.payload.sha256 == hashlib.sha256(body).hexdigest()
        cases.append("immutable_snapshot")
        first = accepted.view
        assert (await client.get(first.record.work_id)) == first
        assert (await client.find("delegation_primary")) == first
        assert not (await client.submit(first.request)).created
        changed = first.request.to_wire()
        changed.pop("input_fingerprint")
        context = changed["context_snapshot"]
        assert isinstance(context, dict)
        context["note"] = "Different synthetic input."
        await expect_error(client.submit(produce_request(changed)), "identity_conflict")
        foreign = await coordinator(scope=Scope("tenant_p3", "account_other"))
        try:
            assert await foreign.find("delegation_primary") is None
            await expect_error(foreign.get(first.record.work_id), "not_found")
            await expect_error(foreign.cancel(first.record.work_id, "foreign_cancel"), "not_found")
        finally:
            await foreign.close()
        assert (await client.find("delegation_primary")) == first
        cases.append("scoped_replay_conflict_read")
        cancellation = await client.cancel(first.record.work_id, "cancel_primary")
        assert cancellation.disposition == "requested"
        assert await client.cancel(first.record.work_id, "cancel_primary") == cancellation
        replayed = await client.submit(first.request)
        assert replayed.view.record.cancel_requested and replayed.view.record.status == "accepted"
        assert replayed.view.record.payload.body == body
        cases.append("requested_cancel_original_replay")

        def failpoint(stage: str) -> None:
            if stage == "submit.after_commit":
                raise OSError("ACK_PRIVATE_SENTINEL")

        uncertain = await coordinator(hook=failpoint)
        try:
            lost = await uncertain.submit(request("delegation_ackloss"))
            assert not lost.created
            assert await uncertain.find("delegation_ackloss") == lost.view
        finally:
            await uncertain.close()
        cases.append("postcommit_ack_reconciliation")
        registrations, token = directory(Scope("tenant_p3", "account_other"))

        misbound = await asyncio.to_thread(
            open_work_client, settings=settings(), directory=registrations, token=token
        )
        try:
            try:
                DelegationCoordinator(
                    executions=misbound, scope=SCOPE, case_authority=SyntheticCasePreflight()
                )
            except CoordinatorError as error:
                assert error.code == "unauthorized"
            else:
                raise AssertionError("expected_scope_rejection")
            assert await misbound.find(idempotency_key="delegation_misbound") is None
        finally:
            await misbound.close()
        cases.append("misbound_scope_zero_acceptance")
        await socket_cases(cases)
        return {
            "status": "passed",
            "cases": cases,
            "primary_sha256": hashlib.sha256(body).hexdigest(),
        }
    finally:
        await client.close()
        assert client.pending_count == 0


async def socket_cases(cases: list[str]) -> None:
    endpoint = SpecialistEndpoint(int(os.environ["P3_CHECK_SPECIALIST_PORT"]))
    value = request("delegation_transport")
    async with SpecialistClient(endpoint, "Bearer " + os.environ["P3_CHECK_TOKEN"]) as http:
        held = asyncio.create_task(http.invoke(value))
        try:
            for _ in range(100):
                try:
                    observation = await http.status(value)
                    break
                except ContractError as error:
                    if error.code != "unknown_attempt":
                        raise
                    await asyncio.sleep(0.01)
            else:
                raise AssertionError("live_attempt_not_observed")
            assert observation.state == "running" and not observation.durable
            assert (await http.cancel(value)).cancel_requested
            Path(os.environ["P3_CHECK_RELEASE"]).touch(mode=0o600, exist_ok=False)
            await expect_error(held, "request_aborted")
        finally:
            Path(os.environ["P3_CHECK_RELEASE"]).touch(mode=0o600, exist_ok=True)
            if not held.done():
                held.cancel()
            await asyncio.gather(held, return_exceptions=True)
        cases.append("live_status_cancel_progress")
        current = request("delegation_transport_current")
        result = await http.invoke(current)
        assert result.eligible is True
        assert (
            verify_policy_facts(
                current,
                result,
                (EvidenceRecord(SCOPE, current.evidence[0], POLICY),),
                observed_at_ms=time.time_ns() // 1_000_000,
            )
            == "candidate"
        )
        assert http.metrics()["validated"] >= 3
        cases.append("python_typescript_grounded_candidate")
    assert http.active == 0


async def verify(*, crash: bool) -> dict[str, object]:
    client = await coordinator()
    try:
        key = "delegation_crash" if crash else "delegation_primary"
        view = await client.find(key)
        assert view is not None
        assert view.record.payload.body == encode_request(view.request)
        if crash:
            assert view.request.deadline_at_ms == int(os.environ["P3_CHECK_CRASH_DEADLINE"])
        else:
            assert view.record.payload.sha256 == os.environ["P3_CHECK_PRIMARY_SHA256"]
            assert view.record.cancel_requested
            assert view.request.context_snapshot.note == "Immutable synthetic acceptance."
        replayed = await client.submit(view.request)
        assert not replayed.created and replayed.view == view
        return {
            "status": "passed",
            "cases": [
                "after_commit_sigkill_reconciliation" if crash else "fresh_process_original_lookup"
            ],
        }
    finally:
        await client.close()
        assert client.pending_count == 0


async def crash_accept() -> None:
    def hook(stage: str) -> None:
        if stage == "submit.after_commit":
            marker = Path(os.environ["P3_CHECK_COMMIT_MARKER"])
            descriptor = os.open(
                marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            with os.fdopen(descriptor, "w") as stream:
                stream.write(str(os.getpid()) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                time.sleep(0.01)
            raise WorkError("acknowledgement_unknown")

    client = await coordinator(hook=hook)
    try:
        await client.submit(
            request("delegation_crash", deadline=int(os.environ["P3_CHECK_CRASH_DEADLINE"]))
        )
        raise AssertionError("parent_must_kill_after_commit")
    finally:
        await client.close()


def owner_counts() -> dict[str, object]:
    selected = settings(owner=True)
    with closing(selected.connect(application_name="continuity-test")) as connection:
        row = connection.execute(
            sql.SQL(
                "SELECT count(*) AS total,count(*) FILTER(WHERE tenant_id=%s AND account_id=%s) AS foreign_records FROM {}.accepted_work"
            ).format(sql.Identifier(selected.schema)),
            ["tenant_p3", "account_other"],
        ).fetchone()
        assert row is not None and type(row["total"]) is int and type(row["foreign_records"]) is int
        assert row["foreign_records"] == 0
        return {
            "status": "passed",
            "foreign_records": row["foreign_records"],
            "total_records": row["total"],
        }


def cleanup() -> dict[str, object]:
    selected = settings(owner=True)
    with closing(selected.connect(application_name="continuity-test")) as connection:
        row = connection.execute(
            "SELECT pg_get_userbyid(nspowner) AS owner,obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=%s",
            [selected.schema],
        ).fetchone()
        if os.environ.get("P3_CHECK_PROFILE_INSTALLED") == "1":
            assert row is not None
        if row is not None:
            assert row == {"owner": "continuity_migrator", "marker": "continuity-readonly-work-v1"}
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


def main() -> int:
    global _ACTIVE_MODE
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        choices=(
            "install",
            "exercise",
            "verify",
            "crash",
            "verify-crash",
            "cleanup",
            "owner-check",
        ),
    )
    args = parser.parse_args()
    report: dict[str, object]
    try:
        validate_environment(args.mode)
        _ACTIVE_MODE = args.mode
        if args.mode == "install":
            install_work_schema(settings(owner=True), WorkLimits(100, 100))
            report = owner_counts()
        elif args.mode == "owner-check":
            report = owner_counts()
        elif args.mode == "cleanup":
            report = cleanup()
        else:

            async def run() -> dict[str, object]:
                async with asyncio.timeout(90):
                    if args.mode == "exercise":
                        return await exercise()
                    if args.mode == "crash":
                        await crash_accept()
                        raise AssertionError("unreachable")
                    return await verify(crash=args.mode == "verify-crash")

            report = asyncio.run(run())
        print(json.dumps(report, sort_keys=True))
        return 0
    except Exception:  # noqa: BLE001 - fixed safe process boundary; no dependency diagnostics
        print(json.dumps({"status": "failed", "code": "case_failed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
