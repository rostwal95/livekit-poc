"""Actual P1 acceptance races and complete bounded P3 negative inventory.

Tooling owns isolated marked state and SQL inspection. Product composition imports
only public P1/P3 modules; this is neither a scheduler nor booking authority.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import TypeVar
from uuid import uuid4

from psycopg import sql

from continuity_lab.execution_api import ExecutionLimits, open_execution_client
from continuity_lab.work_admin import install_work_schema, upgrade_work_schema_v2
from continuity_lab.work_api import (
    BearerToken,
    PostgresSettings,
    WorkClient,
    WorkDirectory,
    WorkPrincipal,
    WorkScope,
    open_work_client,
)
from delegation_reliability import (
    CaseSnapshot,
    CoordinatorError,
    DelegationCoordinator,
    DelegationRunError,
    DelegationRunner,
    SpecialistClient,
    SpecialistEndpoint,
)
from delegation_reliability.contracts import (
    ContractError,
    DelegationRequest,
    EvidenceRef,
    Scope,
    canonical,
    encode_request,
    match_result,
    parse_request,
    parse_result,
    produce_request,
)
from delegation_reliability.security import EvidenceRecord, EvidenceRegistry, verify_policy_facts

SCOPE = Scope("tenant_p3", "account_p3")
POLICY = canonical({"minimum_notice_days": 7, "policy_version": "policy_v1"})
OWNER_MODES = frozenset({"install", "locks", "owner-check", "cleanup"})
MODES = (
    "install",
    "locks",
    "original",
    "equal",
    "changed",
    "verify",
    "negative",
    "owner-check",
    "cleanup",
)
COMMON = {"P3_ACCEPT_CASE_ID", "P3_ACCEPT_SCHEMA", "P3_ACCEPT_DIRECTORY", "P3_ACCEPT_PG_PORT"}
CONTEXT = {
    "install": set(),
    "locks": set(),
    "owner-check": set(),
    "cleanup": set(),
    "original": {"P3_ACCEPT_TOKEN"},
    "equal": {"P3_ACCEPT_TOKEN"},
    "changed": {"P3_ACCEPT_TOKEN"},
    "verify": {"P3_ACCEPT_TOKEN", "P3_ACCEPT_SPECIALIST_PORT"},
    "negative": {
        "P3_ACCEPT_TOKEN",
        "P3_ACCEPT_SPECIALIST_PORT",
        "P3_ACCEPT_BAD_PORT",
        "P3_ACCEPT_FIXTURE",
    },
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
_ACTIVE_MODE: str | None = None
_STAGE = "fixture"
T = TypeVar("T")


def environment(mode: str) -> None:
    password = "P3_ACCEPT_OWNER_PASSWORD" if mode in OWNER_MODES else "P3_ACCEPT_RUNTIME_PASSWORD"
    required = COMMON | CONTEXT[mode] | {password}
    if not required <= set(os.environ) or set(os.environ) - required - BASE:
        raise AssertionError("unsafe_environment")
    if os.environ["P3_ACCEPT_CASE_ID"] not in {"P3-03", "P3-11"}:
        raise AssertionError("invalid_case")


def folder() -> Path:
    value = Path(os.environ["P3_ACCEPT_DIRECTORY"])
    if not value.is_absolute() or value.resolve() != value or not value.is_dir():
        raise AssertionError("unsafe_directory")
    return value


def settings(*, owner: bool = False) -> PostgresSettings:
    if _ACTIVE_MODE is None or owner != (_ACTIVE_MODE in OWNER_MODES):
        raise AssertionError("credential_role")
    schema = os.environ["P3_ACCEPT_SCHEMA"]
    if re.fullmatch(r"p1_work_acceptance_[0-9a-f]{32}", schema) is None:
        raise AssertionError("unsafe_schema")
    return PostgresSettings(
        host="127.0.0.1",
        port=int(os.environ["P3_ACCEPT_PG_PORT"]),
        dbname="livekit_lab",
        schema=schema,
        user="continuity_migrator" if owner else "livekit_lab",
        password=os.environ["P3_ACCEPT_OWNER_PASSWORD" if owner else "P3_ACCEPT_RUNTIME_PASSWORD"],
    )


def make_request(key: str, deadline: int) -> DelegationRequest:
    return produce_request(
        {
            "schema_version": 1,
            "kind": "delegation.request",
            "capability": "booking.evaluate_policy",
            "input_schema_version": 1,
            "scope": {"tenant_id": SCOPE.tenant_id, "account_id": SCOPE.account_id},
            "delegation_id": key,
            "case_id": "case_acceptance",
            "request_revision": 1,
            "context_snapshot": {
                "policy_version": "policy_v1",
                "policy_source_id": "policy_demo",
                "days_before_arrival": 14,
                "note": "Original immutable acceptance.",
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
            "deadline_at_ms": deadline,
            "result_route": {"conversation_id": "conversation_acceptance"},
            "attempt": {"attempt_id": "attempt_original", "number": 1},
        }
    )


def original() -> DelegationRequest:
    return parse_request((folder() / "request.json").read_bytes())


def directory(scope: Scope = SCOPE) -> tuple[WorkDirectory, BearerToken]:
    token = BearerToken(os.environ["P3_ACCEPT_TOKEN"])
    return WorkDirectory(
        {token: WorkPrincipal("acceptance_actor", WorkScope(scope.tenant_id, scope.account_id))}
    ), token


async def client(scope: Scope = SCOPE, hook: Callable[[str], None] | None = None) -> WorkClient:
    registered, token = directory(scope)
    return await asyncio.to_thread(
        open_work_client,
        settings=settings(),
        directory=registered,
        token=token,
        harness_failpoint=hook,
    )


def mark(name: str) -> None:
    target = folder() / (name + ".reached")
    pending = target.with_name(target.name + ".pending")
    descriptor = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write((str(os.getpid()) + "\n").encode("ascii"))
            stream.flush()
            os.fsync(stream.fileno())
        os.link(pending, target, follow_symlinks=False)
    finally:
        pending.unlink(missing_ok=True)


async def wait(name: str, seconds: float = 8) -> None:
    deadline = time.monotonic() + seconds
    while not (folder() / name).exists():
        if time.monotonic() >= deadline:
            raise AssertionError("barrier_timeout")
        await asyncio.sleep(0.01)


class Cases:
    def __init__(self, mode: str | None = None, mutable: DelegationRequest | None = None) -> None:
        self.mode, self.mutable = mode, mutable

    async def snapshot(self, *, case_id: str) -> CaseSnapshot:
        if self.mode is not None:
            mark(self.mode + "_preflight")
            await wait(self.mode + ".release")
            if self.mode == "original" and self.mutable is not None:
                object.__setattr__(
                    self.mutable.context_snapshot, "note", "MUTATED_PRIVATE_SENTINEL"
                )
        return CaseSnapshot(SCOPE, case_id, 1, False)


async def runner(value: DelegationRequest, port: int) -> DelegationRunner:
    registered, token = directory()
    executions = await asyncio.to_thread(
        open_execution_client, settings=settings(), directory=registered, token=token
    )
    return DelegationRunner(
        executions=executions,
        scope=SCOPE,
        owner_id=str(uuid4()),
        specialist=SpecialistClient(
            SpecialistEndpoint(port), "Bearer " + os.environ["P3_ACCEPT_TOKEN"]
        ),
        case_authority=Cases(),
        evidence=(EvidenceRecord(SCOPE, value.evidence[0], POLICY),),
    )


async def admit(mode: str) -> dict[str, object]:
    value = original()
    if mode == "equal":
        value = replace(value, attempt=replace(value.attempt, attempt_id="attempt_equal"))
    if mode == "changed":
        wire = value.to_wire()
        wire.pop("input_fingerprint")
        wire["context_snapshot"] = {
            "policy_version": "policy_v1",
            "policy_source_id": "policy_demo",
            "days_before_arrival": 14,
            "note": "Changed payload.",
        }
        value = produce_request(wire)

    def hold(stage: str) -> None:
        if mode == "original" and stage == "submit.before_commit":
            mark("original_commit")
            deadline = time.monotonic() + 8
            while not (folder() / "commit.release").exists():
                if time.monotonic() >= deadline:
                    raise AssertionError("commit_release_timeout")
                time.sleep(0.005)

    work = await client(hook=hold)
    coordinator = DelegationCoordinator(
        executions=work, scope=SCOPE, case_authority=Cases(mode, value), timeout_ms=5000
    )
    try:
        try:
            accepted = await coordinator.submit(value)
        except CoordinatorError as error:
            assert mode == "changed" and error.code == "identity_conflict"
            result = {"status": "passed", "mode": mode, "code": error.code, "created": False}
        else:
            assert mode != "changed" and accepted.created == (mode == "original")
            assert accepted.view.record.payload.body == (folder() / "request.json").read_bytes()
            assert b"MUTATED_PRIVATE_SENTINEL" not in accepted.view.record.payload.body
            result = {
                "status": "passed",
                "mode": mode,
                "work_id": accepted.view.record.work_id,
                "sha256": accepted.view.record.payload.sha256,
                "created": accepted.created,
                "deadline_at_ms": accepted.view.request.deadline_at_ms,
            }
            (folder() / (mode + ".json")).write_text(json.dumps(result))
        return result
    finally:
        await coordinator.close()
        assert coordinator.pending_count == 0


def locks() -> dict[str, object]:
    mark("owner_ready")
    deadline = time.monotonic() + 8
    with closing(settings(owner=True).connect(application_name="continuity-test")) as connection:
        while time.monotonic() < deadline:
            rows = connection.execute(
                "SELECT DISTINCT pid,pg_blocking_pids(pid) AS blockers FROM pg_locks WHERE locktype='relation' AND relation=(SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relname='admission') AND mode='RowShareLock' AND granted",
                [settings(owner=True).schema],
            ).fetchall()
            entries = {row["pid"]: set(row["blockers"]) for row in rows}
            roots = {pid for pid, blockers in entries.items() if not blockers}
            waiting = {pid for pid, blockers in entries.items() if blockers}
            if len(entries) == 3 and len(roots) == 1 and len(waiting) == 2:
                root = next(iter(roots))
                for pid in waiting:
                    seen: set[int] = set()
                    pending = [pid]
                    while pending:
                        current = pending.pop()
                        if current in seen:
                            continue
                        seen.add(current)
                        pending.extend(entries.get(current, set()))
                    assert root in seen and seen <= set(entries)
                mark("sql_contention")
                return {
                    "status": "passed",
                    "holders": 1,
                    "waiters": 2,
                    "actual_admission_lock_contention": True,
                }
            time.sleep(0.005)
    raise AssertionError("sql_contention_not_observed")


async def verify() -> dict[str, object]:
    work = await client()
    coordinator = DelegationCoordinator(executions=work, scope=SCOPE, case_authority=Cases())
    run: DelegationRunner | None = None
    try:
        request = original()
        found = await coordinator.find(request.delegation_id)
        assert (
            found is not None
            and found.record.payload.body == (folder() / "request.json").read_bytes()
        )
        assert await coordinator.get(found.record.work_id) == found
        replay = await coordinator.submit(request)
        assert not replay.created and replay.view == found
        for foreign_scope in (
            Scope("tenant_other", SCOPE.account_id),
            Scope(SCOPE.tenant_id, "account_other"),
            Scope("tenant_other", "account_other"),
        ):
            foreign_work = await client(foreign_scope)
            foreign = DelegationCoordinator(
                executions=foreign_work, scope=foreign_scope, case_authority=Cases()
            )
            try:
                assert await foreign.find(request.delegation_id) is None
                for operation in (
                    foreign.get(found.record.work_id),
                    foreign.cancel(found.record.work_id, "foreign_cancel"),
                ):
                    try:
                        await operation
                    except CoordinatorError as error:
                        assert error.code == "not_found"
                    else:
                        raise AssertionError("foreign_disclosure")
            finally:
                await foreign.close()
        run = await runner(request, int(os.environ["P3_ACCEPT_SPECIALIST_PORT"]))
        result = await run.run_once(found.record.work_id, "acceptance_positive")
        assert (
            result.invoked
            and result.recorded is not None
            and result.recorded.disposition == "eligible_at_commit"
        )
        assert (
            result.view.applicability == "candidate"
            and result.view.result is not None
            and result.view.result.eligible is True
        )
        viewed = await run.inspect(found.record.work_id)
        assert viewed.result == result.view.result
        assert not (await run.run_once(found.record.work_id, "acceptance_positive")).invoked
        return {
            "status": "passed",
            "work_id": found.record.work_id,
            "sha256": found.record.payload.sha256,
            "result_sha256": result.recorded.sha256,
            "cross_scope_disclosures": 0,
            "selected_invocations": 1,
        }
    finally:
        if run is not None:
            await run.close()
        await coordinator.close()


def expect(run: Callable[[], T], code: str) -> None:
    try:
        run()
    except ContractError as error:
        assert error.code == code and str(error) == code
    else:
        raise AssertionError("missing_rejection")


def codec_checks() -> list[str]:
    fixture = json.loads(Path(os.environ["P3_ACCEPT_FIXTURE"]).read_text())
    request = parse_request(fixture["request_canonical"].encode())
    result = parse_result(fixture["result_canonical"].encode())
    expect(lambda: parse_result(b'{"SECRET_SENTINEL":'), "invalid_json")
    expect(
        lambda: match_result(
            request, replace(result, request_revision=2), observed_at_ms=fixture["observed_at_ms"]
        ),
        "result_mismatch",
    )
    expect(
        lambda: parse_result(canonical({**result.to_wire(), "result_schema_version": 2})),
        "unsupported_version",
    )
    expect(
        lambda: produce_request({**fixture["producer_input"], "input_schema_version": 2}),
        "unsupported_version",
    )
    expect(
        lambda: match_result(
            request,
            replace(result, scope=Scope("tenant_other", request.scope.account_id)),
            observed_at_ms=fixture["observed_at_ms"],
        ),
        "result_mismatch",
    )
    expect(lambda: parse_result(b" " * 8193), "invalid_json")
    expect(
        lambda: produce_request(
            {
                **fixture["producer_input"],
                "context_snapshot": {
                    **fixture["producer_input"]["context_snapshot"],
                    "note": "x" * 1025,
                },
            }
        ),
        "invalid_contract",
    )
    expect(lambda: parse_request(b" " * 16385), "invalid_json")
    image = {
        "source_id": "image_demo",
        "version": "source_v1",
        "sha256": "a" * 64,
        "media_type": "image/png",
        "byte_length": 2097153,
        "width": 1,
        "height": 1,
    }
    expect(
        lambda: produce_request({**fixture["producer_input"], "evidence": [image]}),
        "invalid_contract",
    )
    expect(
        lambda: produce_request(
            {**fixture["producer_input"], "evidence": [{**image, "byte_length": 1, "width": 2049}]}
        ),
        "invalid_contract",
    )
    ref = EvidenceRef("image_demo", "source_v1", "a" * 64, "image/png", 2097153, 1, 1)
    expect(
        lambda: EvidenceRegistry((EvidenceRecord(request.scope, ref, b"x" * 2097153),)),
        "invalid_contract",
    )
    records = (EvidenceRecord(request.scope, request.evidence[0], fixture["policy_body"].encode()),)
    expect(
        lambda: verify_policy_facts(
            request,
            replace(result, eligible=False),
            records,
            observed_at_ms=fixture["observed_at_ms"],
        ),
        "unsupported_facts",
    )
    forged = replace(result, evidence_refs=(replace(result.evidence_refs[0], sha256="a" * 64),))
    expect(
        lambda: verify_policy_facts(
            request, forged, records, observed_at_ms=fixture["observed_at_ms"]
        ),
        "evidence_mismatch",
    )
    assert (
        verify_policy_facts(request, result, records, observed_at_ms=fixture["observed_at_ms"])
        == "candidate"
    )
    return [
        "malformed_output",
        "wrong_revision",
        "unsupported_schema",
        "mismatched_tenant",
        "oversized_result",
        "oversized_context",
        "oversized_request",
        "oversized_image",
        "evidence_facts",
    ]


async def negative() -> dict[str, object]:
    codec = codec_checks()
    work = await client()
    coordinator = DelegationCoordinator(executions=work, scope=SCOPE, case_authority=Cases())
    records = []
    try:
        for index, name in enumerate(codec[:5]):
            value = make_request("delegation_negative_" + str(index), original().deadline_at_ms)
            accepted = await coordinator.submit(value)
            current = await runner(value, int(os.environ["P3_ACCEPT_BAD_PORT"]))
            try:
                try:
                    await current.run_once(accepted.view.record.work_id, "invalid_" + str(index))
                except DelegationRunError as error:
                    assert error.code == "transport_unknown" and str(error) == "transport_unknown"
                    observed_code = error.code
                else:
                    raise AssertionError("invalid_output_accepted")
                assert (await current.inspect(accepted.view.record.work_id)).result is None
                # The diagnostic is fixed; raw malformed bytes never become an explanation.
                records.append({"name": name, "code": observed_code, "result_committed": False})
                deadline = time.monotonic() + 3
                while (
                    await current.inspect(accepted.view.record.work_id)
                ).execution.status == "running":
                    if time.monotonic() >= deadline:
                        raise AssertionError("lease_not_expired")
                    await asyncio.sleep(0.01)
            finally:
                await current.close()
        value = make_request("delegation_after_rejection", original().deadline_at_ms)
        accepted = await coordinator.submit(value)
        current = await runner(value, int(os.environ["P3_ACCEPT_SPECIALIST_PORT"]))
        try:
            useful = await current.run_once(
                accepted.view.record.work_id, "positive_after_rejection"
            )
            assert (
                useful.recorded is not None
                and useful.recorded.disposition == "eligible_at_commit"
                and useful.view.applicability == "candidate"
            )
            assert useful.view.result is not None and useful.view.result.eligible is True
        finally:
            await current.close()
        return {
            "status": "passed",
            "python_codec_cases": codec,
            "invalid_observations": records,
            "invalid_results_committed": 0,
            "positive_results_committed": 1,
        }
    finally:
        await coordinator.close()


def owner_check() -> dict[str, object]:
    selected = settings(owner=True)
    expected = 1 if os.environ["P3_ACCEPT_CASE_ID"] == "P3-03" else 6
    with closing(selected.connect(application_name="continuity-test")) as connection:
        counts: dict[str, int] = {}
        for name in (
            "accepted_work",
            "issued_attempts",
            "attempt_results",
            "cancellation_commands",
        ):
            row = connection.execute(
                sql.SQL("SELECT count(*) AS count FROM {}.{}").format(
                    sql.Identifier(selected.schema), sql.Identifier(name)
                )
            ).fetchone()
            assert row is not None and type(row["count"]) is int
            counts[name] = row["count"]
        assert counts == {
            "accepted_work": expected,
            "issued_attempts": expected,
            "attempt_results": 1,
            "cancellation_commands": 0,
        }
        rows = connection.execute(
            sql.SQL(
                "SELECT w.work_id::text,w.body,w.sha256,w.tenant_id,w.account_id,i.attempt_id::text,r.body AS result,r.sha256 AS result_sha,r.disposition FROM {}.accepted_work w JOIN {}.issued_attempts i USING(work_id) LEFT JOIN {}.attempt_results r USING(attempt_id)"
            ).format(*[sql.Identifier(selected.schema)] * 3)
        ).fetchall()
        assert len(rows) == expected
        for row in rows:
            assert (row["tenant_id"], row["account_id"]) == (SCOPE.tenant_id, SCOPE.account_id)
            assert hashlib.sha256(bytes(row["body"])).hexdigest() == row["sha256"]
            request = parse_request(bytes(row["body"]))
            assert b"MUTATED_PRIVATE_SENTINEL" not in bytes(row["body"])
            if expected == 1:
                assert bytes(row["body"]) == (folder() / "request.json").read_bytes()
            if row["result"] is not None:
                body = bytes(row["result"])
                assert hashlib.sha256(body).hexdigest() == row["result_sha"]
                result = parse_result(body)
                assert result.attempt_id == "attempt_" + row["attempt_id"].replace("-", "")
                transport = replace(
                    request, attempt=replace(request.attempt, attempt_id=result.attempt_id)
                )
                assert (
                    verify_policy_facts(
                        transport,
                        result,
                        (EvidenceRecord(SCOPE, request.evidence[0], POLICY),),
                        observed_at_ms=result.completed_at_ms,
                    )
                    == "candidate"
                )
                assert row["disposition"] == "eligible_at_commit"
                if expected == 6:
                    assert request.delegation_id == "delegation_after_rejection"
            elif expected == 6:
                assert request.delegation_id.startswith("delegation_negative_")
        return {
            "status": "passed",
            "counts": counts,
            "foreign_records": 0,
            "invalid_result_commits": 0,
        }


def cleanup() -> dict[str, object]:
    selected = settings(owner=True)
    with closing(selected.connect(application_name="continuity-test")) as connection:
        row = connection.execute(
            "SELECT pg_get_userbyid(nspowner) AS owner,obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=%s",
            [selected.schema],
        ).fetchone()
        if row is not None:
            assert row["owner"] == "continuity_migrator" and row["marker"] in {
                "continuity-readonly-work-v1",
                "continuity-readonly-work-v2",
            }
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(selected.schema))
            )
        absent = connection.execute(
            "SELECT count(*) AS count FROM pg_namespace WHERE nspname=%s", [selected.schema]
        ).fetchone()
        assert absent is not None and absent["count"] == 0
    return {"status": "passed", "schema_removed": True}


def main() -> int:
    global _ACTIVE_MODE, _STAGE
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=MODES)
    args = parser.parse_args()
    try:
        environment(args.mode)
        _ACTIVE_MODE = args.mode
        _STAGE = args.mode
        if args.mode == "install":
            install_work_schema(settings(owner=True))
            upgrade_work_schema_v2(
                settings(owner=True),
                ExecutionLimits(
                    max_active=2,
                    lease_ms=1000 if os.environ["P3_ACCEPT_CASE_ID"] == "P3-11" else 10000,
                ),
            )
            (folder() / "request.json").write_bytes(
                encode_request(
                    make_request("delegation_concurrent", time.time_ns() // 1000000 + 55000)
                )
            )
            report = {"status": "passed", "version": 2}
        elif args.mode == "locks":
            report = locks()
        elif args.mode == "owner-check":
            report = owner_check()
        elif args.mode == "cleanup":
            report = cleanup()
        elif args.mode == "verify":
            report = asyncio.run(verify())
        elif args.mode == "negative":
            report = asyncio.run(negative())
        else:
            report = asyncio.run(admit(args.mode))
        print(json.dumps(report))
        return 0
    except Exception as error:  # noqa: BLE001 - fixed stage/own-source line only, never dependency details
        trace = error.__traceback__
        line = 0
        while trace is not None:
            if Path(trace.tb_frame.f_code.co_filename).resolve() == Path(__file__).resolve():
                line = trace.tb_lineno
            trace = trace.tb_next
        print(json.dumps({"status": "failed", "code": _STAGE, "line": line}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
