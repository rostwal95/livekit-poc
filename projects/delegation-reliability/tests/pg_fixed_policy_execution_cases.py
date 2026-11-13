"""Actual public P1/P3 durable-v2 consumer; owner setup is isolated test tooling.

No scheduler, supplier worker, action or projection is constructed. Owner-only
bootstrap is imported lazily. Runtime modes use declared public ports only.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import re
import stat
import time
from contextlib import closing
from dataclasses import asdict, replace
from pathlib import Path
from types import ModuleType
from typing import Any, NoReturn, cast
from uuid import UUID

from psycopg import sql

from continuity_lab.case_control_api import BookingChange, open_case_control_client
from continuity_lab.execution_api import ExecutionLimits, IssuedAttempt, open_execution_client
from continuity_lab.postgres_api import AuthenticatedActor, open_postgres_client
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
    WorkError,
    WorkLimits,
    WorkPrincipal,
    WorkScope,
    open_work_client,
)
from delegation_reliability import (
    CaseBinding,
    CoordinatorError,
    DelegationCoordinator,
    DelegationRunError,
    FixedPolicyCoordinator,
    FixedPolicyRunner,
    ManagedCaseAuthority,
    SpecialistEndpoint,
    SpecialistHttpError,
)
from delegation_reliability.contracts import (
    Attempt,
    ContractError,
    EvidenceRef,
    Scope,
    parse_request,
)
from delegation_reliability.fixed_policy import FixedPolicySpecialistClient
from delegation_reliability.fixed_policy_contracts import (
    FixedPolicyRequest,
    encode_fixed_policy_request,
    produce_fixed_policy_request,
)
from delegation_reliability.security import EvidenceRecord

LABELS = (
    "known",
    "missing",
    "conflicting",
    "wrong_rule",
    "wrong_decision",
    "wrong_witness",
    "foreign_scope",
    "expired_wrong_facts",
    "expired_valid",
    "cancelled",
    "abandoned",
    "postcommit",
    "useful",
)
NEGATIVE = frozenset(LABELS[3:8])
MODES = ("install", "exercise", "commit-kill", "reopen", "cleanup")
CASES = (
    "v1_defaults_and_version_separation",
    "v2_acceptance_original_bytes_scope_and_deadline",
    "full_input_replay_and_changed_identity_conflict",
    "unbound_foreign_zero_cancelled_and_stale_case_denied",
    "new_issuance_only_and_exact_owner_command_replay",
    "known_missing_and_conflicting_truth_preserved",
    "forged_and_expired_bad_facts_zero_result_commit",
    "historical_expired_body_and_authority_time",
    "business_cancel_and_known_fact_separation",
    "abandoned_waiter_retains_capacity_and_retry_close",
    "owned_postcommit_kill_and_fresh_original_lookup",
    "independent_inventory_and_useful_current_progress",
)
BASE = frozenset({"PATH", "LANG", "CI", "NO_COLOR", "__CF_USER_TEXT_ENCODING"})
COMMON = frozenset(
    {
        "P3_FIXED_WORK_DIRECTORY",
        "P3_FIXED_WORK_WORK_SCHEMA",
        "P3_FIXED_WORK_CASE_SCHEMA",
        "P3_FIXED_WORK_PG_PORT",
    }
)
ACTOR = AuthenticatedActor("p3_completion_user", "p3_completion_scope")
MODE, STAGE = "", "setup"


def folder() -> Path:
    p = Path(os.environ["P3_FIXED_WORK_DIRECTORY"])
    info = p.lstat()
    assert p.is_absolute() and p.resolve() == p and stat.S_ISDIR(info.st_mode)
    assert info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700
    return p


def environment(mode: str) -> None:
    assert mode in MODES
    role = (
        {"P3_FIXED_WORK_OWNER_PASSWORD"}
        if mode in {"install", "cleanup"}
        else {"P3_FIXED_WORK_RUNTIME_PASSWORD", "P3_FIXED_WORK_TOKEN"}
    )
    assert COMMON | role <= os.environ.keys() and not set(os.environ) - (COMMON | role | BASE)
    assert re.fullmatch(r"p1_work_fixedv2_[0-9a-f]{32}", os.environ["P3_FIXED_WORK_WORK_SCHEMA"])
    assert re.fullmatch(r"p3_completion_[0-9a-f]{32}", os.environ["P3_FIXED_WORK_CASE_SCHEMA"])
    assert 1 <= int(os.environ["P3_FIXED_WORK_PG_PORT"]) <= 65535
    folder()


def settings(kind: str = "work") -> PostgresSettings:
    assert kind in {"work", "case"}
    owner = MODE in {"install", "cleanup"}
    return PostgresSettings(
        port=int(os.environ["P3_FIXED_WORK_PG_PORT"]),
        schema=os.environ["P3_FIXED_WORK_" + kind.upper() + "_SCHEMA"],
        user="continuity_migrator" if owner else "livekit_lab",
        password=os.environ[
            "P3_FIXED_WORK_OWNER_PASSWORD" if owner else "P3_FIXED_WORK_RUNTIME_PASSWORD"
        ],
    )


def read_private(path: Path, maximum: int = 32768) -> bytes:
    info = path.lstat()
    assert (
        stat.S_ISREG(info.st_mode)
        and info.st_uid == os.geteuid()
        and stat.S_IMODE(info.st_mode) == 0o600
        and info.st_nlink == 1
        and 0 < info.st_size <= maximum
    )
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        held = os.fstat(stream.fileno())
        assert (held.st_dev, held.st_ino) == (info.st_dev, info.st_ino)
        raw = stream.read(maximum + 1)
    assert 0 < len(raw) <= maximum
    return raw


def file_json(value: object) -> bytes:
    """Bounded setup/proof JSON, distinct from the16KiB public wire codec."""
    count = 0

    def visit(item: object, depth: int) -> None:
        nonlocal count
        count += 1
        assert count <= 4096 and depth <= 12
        if type(item) is dict:
            assert all(type(key) is str for key in item)
            for child in item.values():
                visit(child, depth + 1)
        elif type(item) is list:
            assert len(item) <= 128
            for child in item:
                visit(child, depth + 1)
        else:
            assert item is None or type(item) in {str, int, bool}
            if type(item) is int:
                assert abs(item) <= 9007199254740991

    visit(value, 0)
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    assert len(raw) <= 32768
    return raw


def load(name: str) -> dict[str, Any]:
    assert re.fullmatch(r"[a-z][a-z0-9_-]*[.]json", name)
    raw = read_private(folder() / name)
    value = json.loads(raw)
    assert type(value) is dict and raw in {file_json(value), file_json(value) + b"\n"}
    return cast(dict[str, Any], value)


def publish(path: Path, raw: bytes) -> None:
    assert path.parent == folder() and 0 < len(raw) <= 32768
    pending = path.with_name(path.name + "." + str(os.getpid()) + ".pending")
    fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(pending, path, follow_symlinks=False)
    finally:
        pending.unlink(missing_ok=True)


def save(name: str, value: object) -> None:
    assert re.fullmatch(r"[a-z][a-z0-9_-]*[.]json", name)
    publish(folder() / name, file_json(value) + b"\n")


def marker(name: str) -> None:
    assert re.fullmatch(r"fixed_work_[a-z_]{1,48}", name)
    publish(folder() / (name + ".reached"), (str(os.getpid()) + "\n").encode("ascii"))


def marker_pid(path: Path, expected: int) -> int:
    end = time.monotonic() + 1
    while True:
        info = path.lstat()
        if info.st_nlink == 2:
            pending = path.with_name(path.name + "." + str(expected) + ".pending")
            try:
                other = pending.lstat()
            except FileNotFoundError:
                other = None
            if other is not None:
                assert (
                    stat.S_ISREG(other.st_mode)
                    and (other.st_dev, other.st_ino) == (info.st_dev, info.st_ino)
                    and other.st_nlink in {1, 2}
                )
                assert time.monotonic() < end
                time.sleep(0.002)
                continue
            # unlink may race the two lstat calls; only the same final inode may settle.
            final = path.lstat()
            assert (final.st_dev, final.st_ino) == (
                info.st_dev,
                info.st_ino,
            ) and final.st_nlink == 1
        assert read_private(path, 32) == (str(expected) + "\n").encode("ascii")
        return expected


async def wait_marker(name: str, expected: int, seconds: float = 15) -> None:
    path = folder() / (name + ".reached")
    end = time.monotonic() + seconds
    while not path.exists():
        assert time.monotonic() < end, "marker_timeout"
        await asyncio.sleep(0.002)
    await asyncio.to_thread(marker_pid, path, expected)


def barrier(name: str, seconds: float = 20) -> None:
    marker(name)
    path = folder() / (name + ".released")
    end = time.monotonic() + seconds
    while not path.exists():
        assert time.monotonic() < end, "release_timeout"
        time.sleep(0.002)
    marker_pid(path, os.getpid())


async def wait_entry(pending: asyncio.Task[Any], name: str, expected: int) -> None:
    arrival = asyncio.create_task(wait_marker(name, expected))
    try:
        completed, _ = await asyncio.wait((pending, arrival), return_when=asyncio.FIRST_COMPLETED)
        if pending in completed:
            await pending
            raise AssertionError("operation_finished_before_entry")
        await arrival
    finally:
        if not arrival.done():
            arrival.cancel()
        await asyncio.gather(arrival, return_exceptions=True)


def module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def helper() -> ModuleType:
    assert MODE in {"install", "cleanup"}
    return module(
        Path(__file__).resolve().parents[3] / "local-setup/scripts/p3_case_fixture.py",
        "fixed_work_owner_case_fixture",
    )


def context() -> dict[str, Any]:
    value = load("fixed-work-context.json")
    assert (
        set(value) == {"schema_version", "scope", "owners", "commands"}
        and value["schema_version"] == 1
    )
    assert set(value["scope"]) == {"tenant_id", "account_id"}
    for name in ("owners", "commands"):
        assert set(value[name]) == set(LABELS) and len(set(value[name].values())) == 13
    for owner in value["owners"].values():
        assert str(UUID(owner)) == owner and UUID(owner).version == 4
    return value


def scope() -> Scope:
    return Scope(**context()["scope"])


def directory() -> tuple[WorkDirectory, BearerToken]:
    token = BearerToken(os.environ["P3_FIXED_WORK_TOKEN"])
    current = scope()
    return WorkDirectory(
        {token: WorkPrincipal("fixed_work_actor", WorkScope(current.tenant_id, current.account_id))}
    ), token


def evidence(label: str) -> tuple[EvidenceRecord, ...]:
    enrolled = load("fixed-work-input.json")
    case = next(c for c in enrolled["cases"] if c["label"] == label)
    refs = case["evidence"]
    return tuple(
        EvidenceRecord(
            Scope(**row["scope"]), EvidenceRef(**row["reference"]), row["body_utf8"].encode("utf-8")
        )
        for ref in refs
        for row in enrolled["records"]
        if row["reference"] == ref and row["scope"] == enrolled["scope"]
    )


def request(label: str) -> FixedPolicyRequest:
    value = load("fixed-work-input.json")
    case = next(c for c in value["cases"] if c["label"] == label)
    return produce_fixed_policy_request(
        {
            "schema_version": 1,
            "kind": "delegation.request",
            "capability": "booking.evaluate_policy",
            "input_schema_version": 2,
            "scope": value["scope"],
            "delegation_id": case["delegation_id"],
            "case_id": case["case_id"],
            "request_revision": case["request_revision"],
            "context_snapshot": case["context_snapshot"],
            "evidence": case["evidence"],
            "deadline_at_ms": time.time_ns() // 1_000_000
            + (1000 if label in {"expired_valid", "expired_wrong_facts"} else 60000),
            "result_route": {"conversation_id": case["conversation_id"]},
            "attempt": {"attempt_id": "proposal_" + label, "number": 1},
        }
    )


def accepted(label: str) -> dict[str, Any]:
    return load("accepted-" + label + ".json")


async def close_tier(*owners: Any) -> None:
    outcomes = await asyncio.gather(*(owner.close() for owner in owners), return_exceptions=True)
    failed = next((x for x in outcomes if isinstance(x, BaseException)), None)
    if failed is not None:
        raise failed


class RecordingSpecialist:
    def __init__(self, label: str, execution: Any) -> None:
        self.label, self.execution = label, execution
        endpoints = load("fixed-work-endpoint.json")
        enrolled = load("fixed-work-input.json")
        role = next(c["peer"] for c in enrolled["cases"] if c["label"] == label)
        self.actual = FixedPolicySpecialistClient(
            SpecialistEndpoint(endpoints[role]["port"]),
            "Bearer " + os.environ["P3_FIXED_WORK_TOKEN"],
            timeout_ms=5000,
            cleanup_ms=100,
        )
        self.started = 0

    async def invoke_observed(
        self, value: FixedPolicyRequest, *, evidence: tuple[EvidenceRecord, ...]
    ) -> Any:
        self.started += 1
        grant = await self.execution.find_issue(command_id=context()["commands"][self.label])
        assert (
            type(grant) is IssuedAttempt
            and value.attempt.attempt_id == "attempt_" + UUID(grant.attempt_id).hex
        )
        save(
            "grant-" + self.label + ".json",
            {
                "work_id": grant.record.work_id,
                "attempt_id": grant.attempt_id,
                "command_id": grant.command_id,
                "number": grant.number,
                "owner_id": grant.owner_id,
                "epoch": grant.epoch,
                "issued_at_ms": grant.issued_at_ms,
                "lease_until_ms": grant.lease_until_ms,
            },
        )
        try:
            result = await self.actual.invoke_observed(value, evidence=evidence)
        except SpecialistHttpError as error:
            assert error.code == "invalid_response" and self.label in NEGATIVE
            save(
                "observed-" + self.label + ".json",
                {
                    "label": self.label,
                    "outcome": "invalid_response",
                    "applicability": None,
                    "observed_at_ms": time.time_ns() // 1_000_000,
                },
            )
            raise
        save(
            "observed-" + self.label + ".json",
            {
                "label": self.label,
                "outcome": "stored",
                "applicability": result.applicability,
                "observed_at_ms": result.observed_at_ms,
            },
        )
        return result

    async def close(self) -> None:
        await self.actual.close()


class Bundle:
    def __init__(self, label: str, *, hook: Any = None) -> None:
        self.label = label
        directory_, token = directory()
        self.client = open_postgres_client(
            actor=ACTOR,
            token=token,
            settings=settings("case"),
            quote_database=folder() / "supplier.sqlite3",
        )
        state = load("fixed-work-cases.json")
        self.cases = ManagedCaseAuthority(
            self.client,
            scope=scope(),
            bindings=tuple(CaseBinding(k, v["task_id"], v["case_id"]) for k, v in state.items()),
        )
        self.work = open_work_client(settings=settings(), directory=directory_, token=token)
        self.execution = open_execution_client(
            settings=settings(), directory=directory_, token=token, harness_failpoint=hook
        )
        self.remote = RecordingSpecialist(label, self.execution)
        self.coordinator = FixedPolicyCoordinator(
            executions=self.work, scope=scope(), case_authority=self.cases
        )
        self.runner = FixedPolicyRunner(
            executions=self.execution,
            scope=scope(),
            owner_id=context()["owners"][label],
            specialist=self.remote,
            case_authority=self.cases,
            evidence=evidence(label),
            timeout_ms=10000,
            cleanup_ms=100,
        )

    async def close(self) -> None:
        await close_tier(self.runner, self.coordinator)
        await self.client.close()

    async def accept(self) -> str:
        value = request(self.label)
        submitted = await self.coordinator.submit(value)
        assert submitted.created and submitted.view.request == value
        save(
            "accepted-" + self.label + ".json",
            {
                "work_id": submitted.view.record.work_id,
                "request_utf8": encode_fixed_policy_request(value).decode("utf-8"),
            },
        )
        return submitted.view.record.work_id


async def case_setup() -> None:
    global STAGE
    from datetime import date

    STAGE = "case_setup"
    _, token = directory()
    client = open_postgres_client(
        actor=ACTOR,
        token=token,
        settings=settings("case"),
        quote_database=folder() / "supplier.sqlite3",
    )
    control = open_case_control_client(
        actor=ACTOR,
        token=token,
        settings=settings("case"),
        quote_database=folder() / "supplier.sqlite3",
    )
    cases = {}
    try:
        for name in ("case_fixed", "case_cancelled"):
            receipt = await client.submit(
                idempotency_key=name, request=BookingChange("DEMO-BK-001", date(2030, 12, 10), True)
            )
            cases[name] = {"task_id": receipt.task_id, "case_id": receipt.case_id}
            authority = ManagedCaseAuthority(
                client,
                scope=scope(),
                bindings=(CaseBinding(name, receipt.task_id, receipt.case_id),),
            )
            workdir, worktoken = directory()
            work = open_work_client(settings=settings(), directory=workdir, token=worktoken)
            coordinator = FixedPolicyCoordinator(
                executions=work, scope=scope(), case_authority=authority
            )
            try:
                data = json.loads(encode_fixed_policy_request(request("known")))
                data.pop("input_fingerprint")
                data["case_id"] = name
                value = produce_fixed_policy_request(data)
                try:
                    await coordinator.submit(value)
                except CoordinatorError as error:
                    assert error.code == "invalid_stored_state"
                else:
                    raise AssertionError("zero_revision_admitted")
                assert await coordinator.find(value.delegation_id) is None
            finally:
                await coordinator.close()
            revised = await control.revise(
                task_id=receipt.task_id,
                expected_revision=0,
                request=BookingChange("DEMO-BK-001", date(2030, 12, 11), True),
            )
            assert revised.revision == 1
        await client.cancel(
            task_id=cases["case_cancelled"]["task_id"], command_id="case_cancel_fixed"
        )
        save("fixed-work-cases.json", cases)
    finally:
        await close_tier(client, control)


async def preflight(b: Bundle) -> None:
    global STAGE
    STAGE = "preflight"
    value = request("known")
    workdir, token = directory()
    legacy = DelegationCoordinator(
        executions=open_work_client(settings=settings(), directory=workdir, token=token),
        scope=scope(),
        case_authority=b.cases,
    )
    # Deliberately pass a hostile v2 DTO to the v1 runtime-rejection boundary.
    legacy_input: Any = value
    try:
        try:
            await legacy.submit(legacy_input)
        except CoordinatorError as error:
            assert error.code == "invalid_input"
        else:
            raise AssertionError("legacy_accepted_v2")
        try:
            parse_request(encode_fixed_policy_request(value))
        except ContractError:
            pass
        else:
            raise AssertionError("legacy_codec_accepted_v2")
        for changes, expected in (
            ({"case_id": "unbound"}, "not_found"),
            ({"case_id": "case_cancelled"}, "case_cancelled"),
            ({"request_revision": 2}, "case_changed"),
            (
                {"scope": {"tenant_id": scope().tenant_id, "account_id": "foreign_account"}},
                "unauthorized",
            ),
        ):
            data = json.loads(encode_fixed_policy_request(value))
            data.pop("input_fingerprint")
            data.update(changes)
            try:
                await b.coordinator.submit(produce_fixed_policy_request(data))
            except CoordinatorError as error:
                assert error.code == expected
            else:
                raise AssertionError("guard_admitted")
    finally:
        await legacy.close()


async def cancel(b: Bundle, label: str) -> None:
    value = await b.coordinator.cancel(accepted(label)["work_id"], "cancel_" + label)
    save("cancel-" + label + ".json", asdict(value))


async def run_label(label: str) -> None:
    global STAGE
    STAGE = "accept"
    b = Bundle(label)
    primary = None
    try:
        work = await b.accept()
        if label == "known":
            original = await b.coordinator.get(work)
            replay = await b.coordinator.submit(
                replace(original.request, attempt=Attempt("fresh_proposal", 2))
            )
            assert not replay.created and replay.view == original
            changed = json.loads(encode_fixed_policy_request(original.request))
            changed.pop("input_fingerprint")
            changed["result_route"]["conversation_id"] = "changed_conversation"
            try:
                await b.coordinator.submit(produce_fixed_policy_request(changed))
            except CoordinatorError as error:
                assert error.code == "identity_conflict"
            else:
                raise AssertionError("changed_input_replayed")
        STAGE = "invoke"
        pending = asyncio.create_task(b.runner.run_once(work, context()["commands"][label]))
        # Observe immediately, including the interval before any entry marker.
        pending.add_done_callback(lambda task: None if task.cancelled() else task.exception())
        node = load("fixed-work-endpoint.json")["pid"]
        if label in {"cancelled", "abandoned"}:
            await wait_entry(pending, "fixed_work_" + label + "_held", node)
            if label == "cancelled":
                STAGE = "cancel"
                await cancel(b, label)
                marker("fixed_work_cancel_verified")
            else:
                STAGE = "abandon"
                pending.cancel()
                try:
                    await pending
                except asyncio.CancelledError:
                    pass
                assert b.runner.pending_count == 1 and b.remote.actual.active == 1
                try:
                    await b.runner.run_once(work, context()["commands"][label])
                except DelegationRunError as error:
                    assert error.code == "capacity"
                else:
                    raise AssertionError("abandoned_slot_released")
                try:
                    await b.runner.close()
                except DelegationRunError as error:
                    assert error.code == "cleanup_incomplete"
                else:
                    raise AssertionError("held_close_claimed")
                save(
                    "fixed-work-waiter.json", {"active_after_abandon": 1, "close_incomplete": True}
                )
                marker("fixed_work_abandon_verified")
                end = time.monotonic() + 15
                while b.runner.pending_count:
                    assert time.monotonic() < end
                    await asyncio.sleep(0.002)
                await b.runner.close()
                assert b.remote.actual.active == 0
                return
        if label in NEGATIVE:
            try:
                await pending
            except DelegationRunError as error:
                assert error.code == "transport_unknown"
            else:
                raise AssertionError("bad_result_committed")
            grant = await b.execution.find_issue(command_id=context()["commands"][label])
            assert (
                grant is not None
                and await b.execution.result(work_id=work, attempt_id=grant.attempt_id) is None
            )
        else:
            done = await pending
            assert done.invoked and done.recorded is not None
            expected = (
                "cancelled"
                if label == "cancelled"
                else "expired"
                if label == "expired_valid"
                else "eligible_at_commit"
            )
            assert done.recorded.disposition == expected
            if label == "known":
                run_replay = await b.runner.run_once(work, context()["commands"][label])
                assert (
                    not run_replay.invoked
                    and run_replay.recorded is None
                    and run_replay.view.result == done.view.result
                )
                await cancel(b, label)
                after = await b.runner.inspect(work)
                assert (
                    after.execution.result == done.view.execution.result
                    and after.applicability == "execution_ineligible"
                )
        # Exact issue replay is read/replay only; a new owner never acquires it.
        grant = await b.execution.find_issue(command_id=context()["commands"][label])
        assert grant is not None
        same = await b.execution.issue(
            work_id=work, owner_id=grant.owner_id, command_id=grant.command_id
        )
        assert not same.created and same.attempt == grant
        try:
            await b.execution.issue(
                work_id=work,
                owner_id="00000000-0000-4000-8000-000000000099",
                command_id=grant.command_id,
            )
        except WorkError as error:
            assert error.code == "identity_conflict"
        else:
            raise AssertionError("new_owner_reused_command")
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            await b.close()
        except BaseException:
            if primary is None:
                raise


async def exercise() -> None:
    await case_setup()
    # Explicit public guard tests precede any accepted work or invocation.
    b = Bundle("known")
    try:
        await preflight(b)
    finally:
        await b.close()
    for label in LABELS[:7]:
        await run_label(label)
    # Four unsupported results retain four original P1 leases; never fake slot
    # release or mint another command to make the fixture proceed.
    workdir, token = directory()
    execution = open_execution_client(settings=settings(), directory=workdir, token=token)
    try:
        end = time.monotonic() + 12
        labels = ("wrong_rule", "wrong_decision", "wrong_witness", "foreign_scope")
        observed = []
        for label in labels:
            value = await execution.observe(work_id=accepted(label)["work_id"])
            while value.status == "running":
                assert time.monotonic() < end
                await asyncio.sleep(0.01)
                value = await execution.observe(work_id=accepted(label)["work_id"])
            assert (
                value.status == "retryable"
                and value.result is None
                and value.current_attempt is not None
            )
            observed.append(
                {
                    "label": label,
                    "work_id": value.record.work_id,
                    "attempt_id": value.current_attempt.attempt_id,
                    "lease_until_ms": value.current_attempt.lease_until_ms,
                    "status": value.status,
                }
            )
        save("fixed-work-rejected-lease-wait.json", {"schema_version": 1, "records": observed})
    finally:
        await execution.close()
    for label in LABELS[7:11]:
        await run_label(label)


async def commit_kill() -> None:
    def hook(stage: str) -> None:
        if stage == "complete.after_commit":
            barrier("fixed_work_result_committed")

    b = Bundle("postcommit", hook=hook)
    try:
        work = await b.accept()
        await b.runner.run_once(work, context()["commands"]["postcommit"])
        raise AssertionError("postcommit_not_killed")
    finally:
        await b.close()


async def reopen() -> None:
    global STAGE
    STAGE = "replay"
    # A fresh process uses the configured public example for useful current work.
    b = Bundle("useful")
    try:
        work = await b.accept()
        example = module(
            Path(__file__).resolve().parents[1] / "examples/durable_fixed_policy.py",
            "fixed_work_public_example",
        )
        submitted, result = await example.run_durable_fixed_policy(
            coordinator=b.coordinator,
            runner=b.runner,
            request=(await b.coordinator.get(work)).request,
            command_id=context()["commands"]["useful"],
        )
        assert not submitted.created and result.invoked and result.recorded is not None
    finally:
        await b.close()
    await asyncio.to_thread(barrier, "fixed_work_useful_committed")
    rows = []
    for label in LABELS:
        STAGE = "replay"
        b = Bundle(label)
        try:
            original = accepted(label)
            view = await b.runner.inspect(original["work_id"])
            grant = await b.execution.find_issue(command_id=context()["commands"][label])
            assert grant is not None
            assert not (
                await b.execution.issue(
                    work_id=original["work_id"],
                    owner_id=grant.owner_id,
                    command_id=grant.command_id,
                )
            ).created
            if label not in NEGATIVE:
                assert view.result is not None and view.execution.result is not None
                known = view.execution.result
                if known.disposition == "eligible_at_commit":
                    replay = await b.runner.run_once(
                        original["work_id"], context()["commands"][label]
                    )
                    assert (
                        not replay.invoked
                        and replay.recorded is None
                        and replay.view.execution.result == known
                    )
                assert (
                    await b.execution.result(work_id=known.work_id, attempt_id=known.attempt_id)
                    == known
                )
            else:
                assert view.result is None and view.execution.result is None
            assert b.remote.started == 0
            observed = load("observed-" + label + ".json")
            rows.append({k: observed[k] for k in ("label", "outcome", "applicability")})
        finally:
            await b.close()
    STAGE = "feed"
    workdir, token = directory()
    feed = open_result_feed_client(settings=settings(), directory=workdir, token=token)
    try:
        first = await feed.read(limit=16)
        second = await feed.read(limit=16)
        assert first == second and len(first.events) == 8 and not first.has_more
        save(
            "fixed-work-public-feed.json",
            {"source_id": first.source_id, "events": [asdict(e) for e in first.events]},
        )
    finally:
        await feed.close()
    marker_waiter = load("fixed-work-waiter.json")
    marker_waiter["active_after_release"] = 0
    STAGE = "proof"
    save(
        "fixed-work-client.json",
        {
            "schema_version": 1,
            "kind": "fixed-policy.execution-client",
            "cases": list(CASES),
            "records": rows,
            "replay": {
                "new_issue_writes": 0,
                "new_complete_writes": 0,
                "new_invocations": 0,
                "original_identity": True,
            },
            "waiter": marker_waiter,
            "default_v1_preserved": True,
            "zero_revision_accepts": 0,
            "zero_revision_invocations": 0,
        },
    )
    await asyncio.to_thread(barrier, "fixed_work_reads_verified")


def install() -> None:
    global STAGE
    STAGE = "install"
    save(
        "fixed-work-owned.json",
        {
            "schema_version": 1,
            "work_schema": settings().schema,
            "case_schema": settings("case").schema,
        },
    )
    install_work_schema(settings(), limits=WorkLimits(16, 16))
    upgrade_work_schema_v2(settings(), limits=ExecutionLimits(4, 3, 10000))
    upgrade_work_schema_v3(settings())
    upgrade_work_schema_v4(settings())
    helper().install(settings("case"), folder() / "supplier.sqlite3")


def cleanup() -> None:
    global STAGE
    STAGE = "cleanup"
    owned = load("fixed-work-owned.json")
    assert (
        owned["work_schema"] == settings().schema
        and owned["case_schema"] == settings("case").schema
    )
    first = None
    try:
        helper().cleanup(settings("case"))
    except Exception as error:  # noqa: BLE001 - attempt every independent owned profile and preserve the primary.
        first = error
    try:
        with closing(settings().connect(application_name="continuity-test")) as connection:
            row = connection.execute(
                "SELECT pg_get_userbyid(nspowner) AS owner,obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=%s",
                (settings().schema,),
            ).fetchone()
            if row is not None:
                assert row["owner"] == "continuity_migrator" and row["marker"] in {
                    "continuity-readonly-work-v1",
                    "continuity-readonly-work-v2",
                    "continuity-readonly-work-v3",
                    "continuity-readonly-work-v4",
                }
                connection.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(settings().schema))
                )
    except Exception as error:  # noqa: BLE001 - cleanup errors never skip the independent owned profile.
        if first is None:
            first = error
    if first is not None:
        raise first


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.exit(2, '{"schema_version":1,"status":"failed","code":"invalid_input"}\n')


def main() -> int:
    global MODE
    parser = SafeParser(description=__doc__)
    parser.add_argument("mode", choices=MODES)
    args = parser.parse_args()
    MODE = args.mode
    cleanup_complete = False
    try:
        environment(MODE)
        if MODE in {"install", "cleanup"}:
            globals()[MODE]()
        else:
            asyncio.run(
                {"exercise": exercise, "commit-kill": commit_kill, "reopen": reopen}[MODE]()
            )
        cleanup_complete = True
    except Exception:  # noqa: BLE001 - finite fixture boundary; no exception properties/messages are inspected.
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "failed",
                    "mode": MODE,
                    "stage": STAGE,
                    "code": "fixture_failed",
                    "cleanup_complete": cleanup_complete,
                },
                sort_keys=True,
            )
        )
        return 1
    print(
        json.dumps(
            {"schema_version": 1, "status": "passed", "mode": MODE, "cleanup_complete": True},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
