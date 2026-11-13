"""Actual P1 temporal authority with an explicitly noncooperating test-only peer.

Serving modules are unchanged. The reused explicit case fixture alone imports P1
worker/bootstrap internals. All deadline decisions below use public P1 ports;
owner SQL supplies independent bounded evidence, never application permission.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from typing import Any, cast, get_args
from uuid import UUID, uuid4

from psycopg import sql

from continuity_lab.action_api import ActionError, Confirmation, open_action_client
from continuity_lab.action_models import ActionCode
from continuity_lab.case_control_api import open_case_control_client
from continuity_lab.delivery_api import open_delivery_client
from continuity_lab.execution_api import (
    AttemptResult,
    ExecutionClient,
    ExecutionLimits,
    ExecutionObservation,
    Issuance,
    IssuedAttempt,
    open_execution_client,
)
from continuity_lab.postgres_api import open_postgres_client, parse_confirmation_payload
from continuity_lab.receiver_api import (
    ReceiverBinding,
    initialize_result_receiver,
    open_result_receiver,
)
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
from continuity_lab.work_models import WorkCode
from delegation_reliability import (
    ActionBinding,
    ApplicabilityRefresher,
    CompletionError,
    CompletionPolicy,
    DelegationAuthorizer,
    DelegationCoordinator,
    DelegationDeliveryClient,
    DelegationRunError,
    DelegationRunner,
    DeliveryBinding,
    ExactManagedCaseAuthority,
    ProjectionProjector,
    RefreshPolicy,
    SpecialistClient,
    SpecialistEndpoint,
    SpecialistHttpError,
    open_applicability_client,
)
from delegation_reliability.completion import CompletionCode
from delegation_reliability.contracts import (
    Attempt,
    ContractError,
    DelegationRequest,
    ErrorCode,
    Scope,
    canonical,
    encode_request,
    parse_request,
    parse_result,
    produce_request,
)
from delegation_reliability.http_client import HttpCode
from delegation_reliability.projection_admin import (
    install_projection_schema,
    upgrade_projection_schema_v2,
    upgrade_projection_schema_v3,
)
from delegation_reliability.projection_api import open_projection_client
from delegation_reliability.projection_models import (
    ProjectionBinding,
    ProjectionCode,
    ProjectionError,
    ProjectionLimits,
)
from delegation_reliability.runner import RunnerCode
from delegation_reliability.security import EvidenceRecord

CASES = (
    "deadline_before_issue_zero_attempt",
    "admission_wait_uses_authority_clock",
    "issued_deadline_before_http_zero_invoke",
    "issued_lease_before_http_zero_invoke",
    "cancel_before_issue_zero_attempt",
    "cancel_after_issue_before_http_zero_invoke",
    "deadline_during_http_late_result_retained",
    "producer_timestamp_never_restores_eligibility",
    "lease_during_http_result_ineligible",
    "cancel_ack_running_ignored_result_retained",
    "cancel_ack_loss_remains_unknown",
    "waiter_timeout_retains_io_without_business_cancel",
    "waiter_cancel_retains_io_without_business_cancel",
    "original_issue_result_replay_no_new_invoke",
    "eligible_result_not_retroactive_lease_expiry",
    "valid_current_b_confirmed_effect_progress",
    "post_late_commit_kill_fresh_lookup_only",
    "independent_scope_refresh_metrics_cleanup",
)
MODES = (
    "install",
    "seed",
    "before-issue",
    "clock-lock",
    "lock-issue",
    "before-http",
    "invoke-expiry",
    "wait-expiry",
    "invoke-lease",
    "wait-lease",
    "invoke-cancel",
    "cancel-ack",
    "invoke-cancel-lost",
    "cancel-lost",
    "caller-timeout",
    "caller-cancel",
    "known-replay",
    "crash-late",
    "verify-crash",
    "useful-current",
    "owner-check",
    "cleanup",
)
OWNER_MODES = {"install", "clock-lock", "owner-check", "cleanup"}
BARRIERS = {
    "clock-lock": "deadline_lock_ready",
    "lock-issue": "issue_before_sql",
    "caller-timeout": "caller_timeout_observed",
    "caller-cancel": "caller_cancel_observed",
    "crash-late": "late_result_commit",
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
ROOT = Path(__file__).resolve().parents[3]
MODE = ""
STAGE = "fixture"
SCOPE = Scope("tenant_deadline", "account_deadline")
POLICY = canonical({"minimum_notice_days": 7, "policy_version": "policy_v1"})
RECIPIENT = "recipient_deadline"
LABELS = (
    "expired_before",
    "lock_wait",
    "issued_deadline",
    "issued_lease",
    "cancel_before",
    "cancel_issued",
    "expiry",
    "lease",
    "cancel",
    "cancel_lost",
    "caller_timeout",
    "caller_cancel",
    "known",
    "crash",
    "useful",
)
RESULT_LABELS = (
    "expiry",
    "lease",
    "cancel",
    "cancel_lost",
    "caller_timeout",
    "caller_cancel",
    "known",
    "crash",
    "useful",
)


DIAGNOSTIC_STAGES = frozenset(
    {"fixture", *MODES, *("owner_" + label for label in LABELS)}
    | {
        "invoke_" + label + "_" + suffix
        for label in RESULT_LABELS
        for suffix in ("submit", "await_run", "capture_result", "view_assert")
    }
    | {"denied_" + label + "_" + suffix for label in LABELS for suffix in ("authorizer", "action")}
)
DIAGNOSTIC_ERRORS = (
    (ContractError, "contract", frozenset(get_args(ErrorCode))),
    (WorkError, "work", frozenset(get_args(WorkCode))),
    (ActionError, "action", frozenset(get_args(ActionCode))),
    (DelegationRunError, "run", frozenset(get_args(RunnerCode))),
    (CompletionError, "completion", frozenset(get_args(CompletionCode))),
    (ProjectionError, "projection", frozenset(get_args(ProjectionCode))),
    (SpecialistHttpError, "http", frozenset(get_args(HttpCode))),
)


def diagnostic_stage(value: str) -> None:
    global STAGE
    assert type(value) is str and value in DIAGNOSTIC_STAGES, "invalid_diagnostic_stage"
    STAGE = value


def diagnostic_failure(error: BaseException, *, mode: object, stage: object) -> dict[str, object]:
    """Reflect only exact vetted exception classes and their finite public codes."""
    kind, code = "unexpected", "fixture_failed"
    if type(error) is AssertionError:
        kind, code = "assertion", "assertion_failed"
    else:
        for known, label, allowed in DIAGNOSTIC_ERRORS:
            if type(error) is known:
                kind = label
                value = object.__getattribute__(error, "__dict__").get("code")
                if type(value) is str and value in allowed:
                    code = value
                break
    return {
        "status": "failed",
        "mode": mode if type(mode) is str and mode in MODES else "unknown",
        "stage": stage if type(stage) is str and stage in DIAGNOSTIC_STAGES else "unknown",
        "code": code,
        "type": kind,
    }


def module(path: Path, name: str) -> ModuleType:
    import sys

    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


HELPER = module(ROOT / "local-setup/scripts/p3_case_fixture.py", "deadline_case_helper")
EXAMPLE = module(
    ROOT / "projects/delegation-reliability/examples/policy_completion.py",
    "deadline_public_example",
)
CONTRACT = json.loads((ROOT / "contracts/delegation/v1.json").read_bytes())


def environment() -> None:
    common = {
        "P3_DEADLINE_WORK_SCHEMA",
        "P3_DEADLINE_CASE_SCHEMA",
        "P3_DEADLINE_SCHEMA",
        "P3_DEADLINE_DIRECTORY",
        "P3_DEADLINE_PG_PORT",
    }
    required = common | (
        {"P3_DEADLINE_OWNER_PASSWORD"}
        if MODE in OWNER_MODES
        else {"P3_DEADLINE_RUNTIME_PASSWORD", "P3_DEADLINE_TOKEN", "P3_DEADLINE_PORT"}
    )
    if MODE in BARRIERS:
        required.add("P3_DEADLINE_BARRIER")
    if MODE == "wait-expiry":
        required.add("P3_DEADLINE_TARGET")
    assert required <= os.environ.keys() and not (os.environ.keys() - required - BASE), (
        "unsafe_child_environment"
    )
    assert re.fullmatch(r"p1_work_deadline_[0-9a-f]{32}", os.environ["P3_DEADLINE_WORK_SCHEMA"])
    assert re.fullmatch(r"p3_completion_[0-9a-f]{32}", os.environ["P3_DEADLINE_CASE_SCHEMA"])
    assert re.fullmatch(r"p3_projection_deadline_[0-9a-f]{32}", os.environ["P3_DEADLINE_SCHEMA"])


def folder() -> Path:
    p = Path(os.environ["P3_DEADLINE_DIRECTORY"])
    assert p.is_dir() and not p.is_symlink()
    return p


def settings(kind: str = "work") -> PostgresSettings:
    assert kind in {"work", "case", "projection"}
    key = {"work": "WORK_SCHEMA", "case": "CASE_SCHEMA", "projection": "SCHEMA"}[kind]
    owner = MODE in OWNER_MODES
    return PostgresSettings(
        port=int(os.environ["P3_DEADLINE_PG_PORT"]),
        schema=os.environ["P3_DEADLINE_" + key],
        user="continuity_migrator" if owner else "livekit_lab",
        password=os.environ[
            "P3_DEADLINE_OWNER_PASSWORD" if owner else "P3_DEADLINE_RUNTIME_PASSWORD"
        ],
    )


def bounded_json(value: object, *, maximum: int = 32768) -> bytes:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()
    assert 1 <= len(raw) <= maximum, "fixture_json_bound"
    return raw


def save(name: str, value: object) -> None:
    assert re.fullmatch(r"[a-z][a-z0-9_-]*\.json", name)
    raw = bounded_json(value)
    fd = os.open(folder() / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)


def load(name: str) -> dict[str, Any]:
    p = folder() / name
    assert not p.is_symlink() and p.stat().st_size <= 32768
    value = json.loads(p.read_bytes())
    assert type(value) is dict
    return cast(dict[str, Any], value)


def marker(name: str) -> None:
    assert re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name)
    p = folder() / (name + ".reached")
    pending = p.with_name(p.name + "." + str(os.getpid()) + ".pending")
    fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write((str(os.getpid()) + "\n").encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.link(pending, p, follow_symlinks=False)
    finally:
        pending.unlink(missing_ok=True)


def barrier(name: str, seconds: float = 4.5) -> None:
    assert Path(os.environ["P3_DEADLINE_BARRIER"]) == folder() / (name + ".reached")
    marker(name)
    release = folder() / (name + ".released")
    end = time.monotonic() + seconds
    while not release.exists():
        assert time.monotonic() < end, "barrier_timeout"
        time.sleep(0.002)
    assert release.read_text() == str(os.getpid()) + "\n", "wrong_barrier_release"


async def file_wait(name: str, seconds: float = 4) -> None:
    end = time.monotonic() + seconds
    while not (folder() / name).is_file():
        assert time.monotonic() < end, "peer_barrier_timeout"
        await asyncio.sleep(0.002)


def now() -> int:
    with closing(settings().connect(application_name="continuity-test")) as c:
        row = c.execute(
            "SELECT floor(extract(epoch FROM clock_timestamp())*1000)::bigint AS now"
        ).fetchone()
        assert row is not None
        return int(row["now"])


async def after(stamp: int) -> int:
    end = time.monotonic() + 4
    while True:
        observed = await asyncio.to_thread(now)
        if observed >= stamp:
            return observed
        assert time.monotonic() < end, "authority_time_not_observed"
        await asyncio.sleep(0.005)


def registrations(foreign: bool = False) -> tuple[WorkDirectory, BearerToken]:
    token = BearerToken(os.environ["P3_DEADLINE_TOKEN"])
    return WorkDirectory(
        {
            token: WorkPrincipal(
                "deadline_actor",
                WorkScope(SCOPE.tenant_id, "foreign_account" if foreign else SCOPE.account_id),
            )
        }
    ), token


def supplier(case: str = "deadline") -> Path:
    assert case in {"deadline", "useful"}
    return folder() / ("supplier_" + case + ".sqlite3")


def state(case: str = "deadline") -> dict[str, Any]:
    return load("case_" + case + ".json")


def action_binding(case: str = "deadline") -> ActionBinding:
    v = state(case)
    return ActionBinding(
        "case_" + case,
        v["task_id"],
        v["case_id"],
        HELPER.ACTOR.actor_id,
        HELPER.ACTOR.scope_id,
        settings("case").schema,
    )


def bindings() -> tuple[ActionBinding, ...]:
    return tuple(
        action_binding(k)
        for k in ("deadline", "useful")
        if (folder() / ("case_" + k + ".json")).is_file()
    )


def request(label: str, horizon: int = 60000) -> DelegationRequest:
    assert label in LABELS
    raw = json.loads(canonical(CONTRACT["producer_input"]))
    raw.update(
        scope={"tenant_id": SCOPE.tenant_id, "account_id": SCOPE.account_id},
        delegation_id="delegation_" + label,
        case_id="case_useful" if label == "useful" else "case_deadline",
        request_revision=2,
        deadline_at_ms=now() + horizon,
    )
    raw["result_route"] = {"conversation_id": "conversation_deadline"}
    return produce_request(raw)


def evidence() -> tuple[EvidenceRecord, ...]:
    value = produce_request(CONTRACT["producer_input"])
    return (EvidenceRecord(SCOPE, value.evidence[0], POLICY),)


def remote() -> SpecialistClient:
    return SpecialistClient(
        SpecialistEndpoint(int(os.environ["P3_DEADLINE_PORT"])),
        "Bearer " + os.environ["P3_DEADLINE_TOKEN"],
        timeout_ms=5000,
        cleanup_ms=1000,
    )


def result(label: str) -> dict[str, Any]:
    return load("work_" + label + ".json")


def transport(label: str) -> DelegationRequest:
    row = result(label)
    v = parse_request(canonical(row["request"]))
    grant = load("grant_" + label + ".json")
    return replace(v, attempt=Attempt("attempt_" + UUID(grant["attempt_id"]).hex, grant["number"]))


class HeldExecution:
    """Test-only port forwarding; no permit/state ownership is introduced."""

    def __init__(self, actual: ExecutionClient, *, external: bool = False) -> None:
        self.actual = actual
        self.external = external
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    @property
    def scope(self) -> WorkScope:
        return self.actual.scope

    @property
    def pending_count(self) -> int:
        return self.actual.pending_count

    async def observe(self, *, work_id: str) -> ExecutionObservation:
        return await self.actual.observe(work_id=work_id)

    async def find_issue(self, *, command_id: str) -> IssuedAttempt | None:
        return await self.actual.find_issue(command_id=command_id)

    async def result(self, *, work_id: str, attempt_id: str) -> AttemptResult | None:
        return await self.actual.result(work_id=work_id, attempt_id=attempt_id)

    async def complete(self, *, attempt: IssuedAttempt, body: bytes) -> AttemptResult:
        return await self.actual.complete(attempt=attempt, body=body)

    async def issue(self, *, work_id: str, owner_id: str, command_id: str) -> Issuance:
        if self.external:
            await asyncio.to_thread(barrier, "issue_before_sql")
            return await self.actual.issue(
                work_id=work_id, owner_id=owner_id, command_id=command_id
            )
        issued = await self.actual.issue(work_id=work_id, owner_id=owner_id, command_id=command_id)
        self.entered.set()
        await self.release.wait()
        return issued

    async def close(self) -> None:
        await self.actual.close()


def grant_payload(v: IssuedAttempt) -> dict[str, object]:
    return {
        "work_id": v.record.work_id,
        "attempt_id": v.attempt_id,
        "command_id": v.command_id,
        "number": v.number,
        "owner_id": v.owner_id,
        "epoch": v.epoch,
        "issued_at_ms": v.issued_at_ms,
        "lease_until_ms": v.lease_until_ms,
    }


class Bundle:
    def __init__(
        self,
        *,
        hold: bool = False,
        external: bool = False,
        hook: Callable[[str], None] | None = None,
        timeout_ms: int = 10000,
        cleanup_ms: int = 1000,
    ) -> None:
        directory, token = registrations()
        self.control = open_case_control_client(
            actor=HELPER.ACTOR, token=token, settings=settings("case"), quote_database=supplier()
        )
        self.cases = ExactManagedCaseAuthority(self.control, scope=SCOPE, bindings=bindings())
        self.work = open_work_client(settings=settings(), directory=directory, token=token)
        self.execution = open_execution_client(
            settings=settings(), directory=directory, token=token, harness_failpoint=hook
        )
        self.proxy = HeldExecution(self.execution, external=external) if hold else None
        self.remote = remote()
        self.coordinator = DelegationCoordinator(
            executions=self.work, scope=SCOPE, case_authority=self.cases
        )
        self.runner = DelegationRunner(
            executions=self.proxy or self.execution,
            scope=SCOPE,
            owner_id=str(uuid4()),
            specialist=self.remote,
            case_authority=self.cases,
            evidence=evidence(),
            max_active=1,
            timeout_ms=timeout_ms,
            cleanup_ms=cleanup_ms,
        )
        self.actions = open_action_client(
            settings=settings(),
            directory=directory,
            token=token,
            case_settings=settings("case"),
            case_actor=HELPER.ACTOR,
            case_token=token,
        )
        self.authorizer = DelegationAuthorizer(
            results=self.runner,
            actions=self.actions,
            scope=SCOPE,
            evidence=evidence(),
            bindings=bindings(),
        )

    async def close(self) -> None:
        if self.proxy is not None:
            self.proxy.release.set()
        first: BaseException | None = None
        for owner in (self.authorizer, self.runner, self.coordinator, self.control):
            try:
                await owner.close()
            except BaseException as error:  # noqa: BLE001 - Preserve cancellation while attempting all independent closes.
                if first is None:
                    first = error
        if first is not None:
            raise first


async def accepted(b: Bundle, label: str, horizon: int = 60000) -> str:
    value = await asyncio.to_thread(request, label, horizon)
    a = await b.coordinator.submit(value)
    wid = a.view.record.work_id
    save(
        "work_" + label + ".json",
        {
            "work_id": wid,
            "request": json.loads(encode_request(value)),
            "request_sha256": a.view.record.payload.sha256,
            "deadline_at_ms": value.deadline_at_ms,
        },
    )
    return wid


async def capture_grant(b: Bundle, label: str) -> IssuedAttempt:
    observed = await b.execution.observe(work_id=result(label)["work_id"])
    assert observed.current_attempt is not None
    value = observed.current_attempt
    p = folder() / ("grant_" + label + ".json")
    if p.exists():
        assert load(p.name) == grant_payload(value)
    else:
        save(p.name, grant_payload(value))
    return value


async def capture_result(b: Bundle, label: str, disposition: str) -> AttemptResult:
    grant = await capture_grant(b, label)
    value = await b.execution.result(work_id=grant.record.work_id, attempt_id=grant.attempt_id)
    assert value is not None and value.disposition == disposition
    save(
        "result_" + label + ".json",
        {
            "work_id": value.work_id,
            "attempt_id": value.attempt_id,
            "sha256": value.sha256,
            "recorded_at_ms": value.recorded_at_ms,
            "disposition": value.disposition,
        },
    )
    return value


def exact(case: str = "deadline") -> Confirmation:
    return parse_confirmation_payload(
        canonical(load("quote_" + case + ".json")["quote"]).decode(), explicit=True
    )


async def denied(b: Bundle, label: str, *, eligible_cancelled: bool = False) -> None:
    wid = result(label)["work_id"]
    diagnostic_stage("denied_" + label + "_authorizer")
    try:
        await b.authorizer.authorize_once(wid, confirmation=exact(), command_id="denied_" + label)
    except CompletionError as e:
        assert e.code == "not_eligible", e.code
    else:
        raise AssertionError("ineligible_facade_authorized")
    diagnostic_stage("denied_" + label + "_action")
    observed = await b.execution.observe(work_id=wid)
    try:
        await b.actions.authorize(
            work_id=wid,
            attempt_id=observed.current_attempt.attempt_id
            if observed.current_attempt
            else str(uuid4()),
            result_sha256=observed.result.sha256 if observed.result else "0" * 64,
            expected_revision=2,
            confirmation=exact(),
            command_id="guard_denied_" + label,
        )
    except ActionError as e:
        assert e.code == ("expired" if eligible_cancelled else "invalid_result"), e.code
    else:
        raise AssertionError("ineligible_guard_authorized")
    assert await b.actions.action(work_id=wid) is None


async def seed_case(case: str) -> None:
    _, token = registrations()
    client = open_postgres_client(
        actor=HELPER.ACTOR, token=token, settings=settings("case"), quote_database=supplier(case)
    )
    control = open_case_control_client(
        actor=HELPER.ACTOR, token=token, settings=settings("case"), quote_database=supplier(case)
    )
    try:
        a = await client.submit(idempotency_key="case_" + case, request=HELPER.REQUEST)
        save("case_" + case + ".json", {"task_id": a.task_id, "case_id": a.case_id})
        await asyncio.to_thread(HELPER.inquire, settings("case"), supplier(case), a.task_id)
        await control.revise(task_id=a.task_id, expected_revision=0, request=HELPER.ALTERNATE)
        await control.revise(task_id=a.task_id, expected_revision=1, request=HELPER.REQUEST)
        q = await client.prepare_quote(
            task_id=a.task_id, expected_revision=2, command_id="quote_" + case
        )
        save("quote_" + case + ".json", {"quote": q.quote.payload()})
    finally:
        await client.close()
        await control.close()


def reply(*indexes: int, **fields: object) -> dict[str, object]:
    return {
        "status": "passed",
        **({"cases": [CASES[i] for i in indexes]} if indexes else {}),
        **fields,
    }


def install() -> dict[str, object]:
    save(
        "owned.json",
        {
            "work": settings().schema,
            "case": settings("case").schema,
            "projection": settings("projection").schema,
            "marker": "p3-deadline-fixture-v1",
        },
    )
    install_work_schema(settings(), limits=WorkLimits(64, 64))
    upgrade_work_schema_v2(settings(), limits=ExecutionLimits(4, 3, 2500))
    upgrade_work_schema_v3(settings())
    upgrade_work_schema_v4(settings())
    HELPER.install(settings("case"), supplier())
    HELPER.initialize_mutation_supplier(supplier("useful"), scope_id=HELPER.ACTOR.scope_id)
    receiver = initialize_result_receiver(folder() / "receiver.sqlite3")
    save("receiver.json", {"receiver_id": receiver})
    with closing(settings().connect(application_name="continuity-test")) as c:
        source = c.execute(
            sql.SQL("SELECT source_id::text FROM {}.result_feed_source WHERE singleton").format(
                sql.Identifier(settings().schema)
            )
        ).fetchone()
        assert source is not None
    save("source.json", source)
    install_projection_schema(
        settings("projection"),
        binding=ProjectionBinding(
            source["source_id"], WorkScope(SCOPE.tenant_id, SCOPE.account_id)
        ),
        limits=ProjectionLimits(32),
    )
    upgrade_projection_schema_v2(
        settings("projection"),
        policy=CompletionPolicy(
            receiver,
            (
                DeliveryBinding("case_deadline", "conversation_deadline", RECIPIENT),
                DeliveryBinding("case_useful", "conversation_deadline", RECIPIENT),
            ),
        ),
    )
    upgrade_projection_schema_v3(settings("projection"), policy=RefreshPolicy(32, 2))
    return reply(work_version=4, case_version=4, projection_version=3)


async def cancel_work(b: Bundle, label: str) -> None:
    wid = result(label)["work_id"]
    receipt = await b.coordinator.cancel(wid, "cancel_" + label)
    snapshot = {
        "cancellation_id": receipt.cancellation_id,
        "work_id": receipt.work_id,
        "command_id": receipt.command_id,
        "requested_at_ms": receipt.requested_at_ms,
        "disposition": receipt.disposition,
    }
    p = folder() / ("cancel_" + label + ".json")
    if p.exists():
        assert load(p.name) == snapshot
    else:
        save(p.name, snapshot)
    assert (await b.execution.observe(work_id=wid)).record.cancel_requested is True


async def before_issue() -> dict[str, object]:
    b = Bundle()
    try:
        wid = await accepted(b, "expired_before", 800)
        await after(result("expired_before")["deadline_at_ms"])
        for label in ("expired_before", "cancel_before"):
            if label == "cancel_before":
                wid = await accepted(b, label)
                await cancel_work(b, label)
                await cancel_work(b, label)
            try:
                await b.runner.run_once(wid, "run_" + label)
            except DelegationRunError as e:
                assert e.code == "expired", e.code
            else:
                raise AssertionError("ineligible_issue_started")
            assert (await b.execution.observe(work_id=wid)).current_attempt is None
            await denied(b, label)
        assert b.runner.metrics()["invoked"] == 0
        return reply(0, 4)
    finally:
        await b.close()


async def lock_issue() -> dict[str, object]:
    b = Bundle(hold=True, external=True)
    try:
        wid = await accepted(b, "lock_wait", 700)
        try:
            await b.runner.run_once(wid, "run_lock_wait")
        except DelegationRunError as e:
            assert e.code == "expired", e.code
        else:
            raise AssertionError("expired_wait_created_grant")
        observed = await b.execution.observe(work_id=wid)
        assert (
            observed.current_attempt is None
            and observed.attempts_issued == 0
            and b.runner.metrics()["invoked"] == 0
        )
        await denied(b, "lock_wait")
        return reply(1, code="expired")
    finally:
        await b.close()


def clock_lock() -> dict[str, object]:
    with closing(settings().connect(application_name="continuity-test")) as c:
        barrier("deadline_lock_ready")
        with c.transaction():
            c.execute(
                sql.SQL("SELECT * FROM {}.admission WHERE singleton FOR UPDATE").format(
                    sql.Identifier(settings().schema)
                )
            )
            owner = c.info.backend_pid
            marker("deadline_lock_acquired")
            target = result("lock_wait")
            end = time.monotonic() + 0.9
            waiter: dict[str, Any] | None = None
            while waiter is None:
                c.execute("SELECT pg_stat_clear_snapshot()")
                rows = c.execute(
                    "SELECT pid,pg_blocking_pids(pid) AS blockers FROM pg_stat_activity WHERE usename='livekit_lab' AND %s=ANY(pg_blocking_pids(pid))",
                    (owner,),
                ).fetchall()
                if len(rows) == 1:
                    waiter = rows[0]
                else:
                    assert time.monotonic() < end, "unobserved_issue_waiter"
                    time.sleep(0.001)
            marker("deadline_lock_observed")
            while True:
                row = c.execute(
                    "SELECT floor(extract(epoch FROM clock_timestamp())*1000)::bigint AS now"
                ).fetchone()
                assert row is not None
                if row["now"] >= target["deadline_at_ms"]:
                    break
                assert time.monotonic() < end, "deadline_lock_budget"
                time.sleep(0.001)
            save(
                "eligibility-lock-proof.json",
                {
                    "schema_version": 1,
                    "owner_backend_pid": owner,
                    "waiter_backend_pid": waiter["pid"],
                    "blockers": waiter["blockers"],
                    "work_id": target["work_id"],
                    "deadline_at_ms": target["deadline_at_ms"],
                    "observed_after_wait_at_ms": row["now"],
                    "expected_new_grants": 0,
                },
            )
    return reply(waiters=1, authority_deadline_crossed=True)


async def before_http() -> dict[str, object]:
    for label in ("issued_deadline", "issued_lease", "cancel_issued"):
        b = Bundle(hold=True)
        assert b.proxy is not None
        wid = await accepted(b, label, 800 if label == "issued_deadline" else 60000)
        pending = asyncio.create_task(b.runner.run_once(wid, "run_" + label))
        try:
            await asyncio.wait_for(b.proxy.entered.wait(), 3)
            grant = await capture_grant(b, label)
            if label == "cancel_issued":
                await cancel_work(b, label)
            else:
                await after(
                    result(label)["deadline_at_ms"]
                    if label == "issued_deadline"
                    else grant.lease_until_ms
                )
            b.proxy.release.set()
            try:
                await pending
            except DelegationRunError as e:
                assert e.code == "expired", e.code
            else:
                raise AssertionError("ineligible_http_started")
            assert b.runner.metrics()["invoked"] == 0
            assert await b.execution.result(work_id=wid, attempt_id=grant.attempt_id) is None
            await denied(b, label)
        finally:
            b.proxy.release.set()
            await asyncio.gather(pending, return_exceptions=True)
            await b.close()
    return reply(2, 3, 5)


async def invocation(label: str) -> dict[str, object]:
    diagnostic_stage("invoke_" + label + "_submit")

    def hit(stage: str) -> None:
        if label == "crash" and stage == "complete.after_commit":
            barrier("late_result_commit")

    b = Bundle(hook=hit if label == "crash" else None)
    try:
        wid = await accepted(b, label, 1800 if label in {"expiry", "crash"} else 60000)
        pending = asyncio.create_task(b.runner.run_once(wid, "run_" + label))
        await file_wait(
            {
                "expiry": "remote_expiry.reached",
                "lease": "remote_lease.reached",
                "cancel": "remote_cancel.reached",
                "cancel_lost": "remote_cancel_lost.reached",
                "crash": "remote_crash.reached",
            }[label]
        )
        await capture_grant(b, label)
        diagnostic_stage("invoke_" + label + "_await_run")
        outcome = await pending
        disposition = {
            "expiry": "expired",
            "lease": "lease_expired",
            "cancel": "cancelled",
            "cancel_lost": "cancelled",
            "crash": "expired",
        }[label]
        diagnostic_stage("invoke_" + label + "_capture_result")
        stored = await capture_result(b, label, disposition)
        diagnostic_stage("invoke_" + label + "_view_assert")
        assert (
            outcome.recorded == stored
            and outcome.invoked is True
            and outcome.view.applicability in {"expired", "execution_ineligible"}
        )
        if label == "expiry":
            value = parse_result(stored.body)
            assert value.completed_at_ms < result(label)["deadline_at_ms"] <= stored.recorded_at_ms
        await denied(b, label)
        return reply(
            *{"expiry": (6, 7), "lease": (8,), "cancel": (9,), "cancel_lost": (10,)}[label],
            disposition=disposition,
        )
    finally:
        await b.close()


async def wait_time(label: str, *, lease: bool = False) -> dict[str, object]:
    await file_wait("grant_" + label + ".json")
    deadline = (
        load("grant_" + label + ".json")["lease_until_ms"]
        if lease
        else result(label)["deadline_at_ms"]
    )
    observed = await after(deadline)
    save(
        "time_" + label + ".json",
        {
            "label": label,
            "authority_at_ms": observed,
            "bound_at_ms": deadline,
            "kind": "lease" if lease else "work_deadline",
        },
    )
    return (
        reply(authority_lease_expired=True)
        if lease
        else reply(authority_expired=True, target=label)
    )


async def cancellation(label: str) -> dict[str, object]:
    b = Bundle()
    observer = remote()
    try:
        await cancel_work(b, label)
        wire = transport(label)
        if label == "cancel_lost":
            try:
                await observer.cancel(wire)
            except SpecialistHttpError as lost_error:
                assert str(lost_error.code) == "invalid_response"
            else:
                raise AssertionError("lost_cancel_ack_invented")
            save(
                "remote_cancel_lost.json",
                {"requested": True, "remote_ack": "unknown", "code": "invalid_response"},
            )
            return reply(
                cancel_requested=True, remote_ack="unknown", remote_code="invalid_response"
            )
        ack = await observer.cancel(wire)
        status = await observer.status(wire)
        assert (
            ack.state == status.state == "running"
            and ack.cancel_requested is status.cancel_requested is True
            and ack.durable is status.durable is False
        )
        raw = json.loads(encode_request(wire))
        raw.pop("input_fingerprint")
        raw["scope"]["tenant_id"] = "foreign_tenant"
        foreign = produce_request(raw)
        try:
            await observer.status(foreign)
        except ContractError as scope_error:
            assert scope_error.code == "unauthorized", scope_error.code
        else:
            raise AssertionError("foreign_status_disclosed")
        raw = json.loads(encode_request(wire))
        raw.pop("input_fingerprint")
        raw["context_snapshot"]["note"] = "changed cancelling fingerprint"
        changed = produce_request(raw)
        try:
            await observer.cancel(changed)
        except ContractError as fingerprint_error:
            assert fingerprint_error.code == "identity_conflict", fingerprint_error.code
        else:
            raise AssertionError("changed_cancel_reached_attempt")
        save(
            "remote_cancel.json",
            {
                "requested": True,
                "remote_ack": "observed",
                "state": ack.state,
                "cancel_requested": ack.cancel_requested,
                "durable": ack.durable,
                "still_running": status.state == "running",
            },
        )
        return reply(
            cancel_requested=True,
            remote_ack="observed",
            remote_state="running",
            remote_durable=False,
        )
    finally:
        await observer.close()
        await b.close()


async def caller(label: str) -> dict[str, object]:
    b = Bundle(timeout_ms=500 if label == "caller_timeout" else 10000, cleanup_ms=20)
    pending: asyncio.Task[Any] | None = None
    try:
        wid = await accepted(b, label)
        pending = asyncio.create_task(b.runner.run_once(wid, "run_" + label))
        await file_wait(
            "remote_timeout.reached"
            if label == "caller_timeout"
            else "remote_waiter_cancel.reached"
        )
        await capture_grant(b, label)
        if label == "caller_cancel":
            pending.cancel()
            try:
                await pending
            except asyncio.CancelledError:
                pass
            else:
                raise AssertionError("caller_cancel_not_propagated")
        else:
            try:
                await pending
            except DelegationRunError as e:
                assert e.code == "acknowledgement_unknown", e.code
            else:
                raise AssertionError("waiter_timeout_not_observed")
        assert b.runner.pending_count == 1 and b.remote.metrics()["active"] == 1
        assert (await b.execution.observe(work_id=wid)).record.cancel_requested is False
        try:
            await b.runner.run_once(wid, "extra_" + label)
        except DelegationRunError as e:
            assert e.code == "capacity", e.code
        else:
            raise AssertionError("abandoned_io_freed_slot")
        try:
            await b.runner.close()
        except DelegationRunError as e:
            assert e.code == "cleanup_incomplete", e.code
        else:
            raise AssertionError("held_io_closed")
        save(
            "lifetime_" + label + ".json",
            {
                "business_cancel_requested": False,
                "runner_active_while_held": b.runner.pending_count,
                "http_active_while_held": b.remote.metrics()["active"],
                "runner_metrics": dict(b.runner.metrics()),
            },
        )
        await asyncio.to_thread(barrier, BARRIERS[MODE])
        end = time.monotonic() + 3
        while b.runner.pending_count:
            assert time.monotonic() < end, "retained_io_never_settled"
            await asyncio.sleep(0.005)
        await b.runner.close()
    finally:
        if pending is not None:
            await asyncio.gather(pending, return_exceptions=True)
        await b.close()
    fresh = Bundle()
    try:
        stored = await capture_result(fresh, label, "eligible_at_commit")
        assert (
            stored.body
            and (
                await fresh.execution.observe(work_id=result(label)["work_id"])
            ).record.cancel_requested
            is False
        )
        return reply(11 if label == "caller_timeout" else 12, disposition="eligible_at_commit")
    finally:
        await fresh.close()


async def known() -> dict[str, object]:
    b = Bundle()
    try:
        wid = await accepted(b, "known")
        outcome = await b.runner.run_once(wid, "run_known")
        stored = await capture_result(b, "known", "eligible_at_commit")
        grant = await capture_grant(b, "known")
        await after(grant.lease_until_ms)
        current = await b.runner.inspect(wid)
        assert current.execution.result == stored and current.applicability == "candidate"
        await cancel_work(b, "known")
        for _ in range(2):
            repeated = await b.runner.run_once(wid, "run_known")
            assert (
                repeated.invoked is False
                and repeated.view.execution.result == stored
                and repeated.view.applicability == "execution_ineligible"
            )
            issued = await b.execution.issue(
                work_id=wid, owner_id=grant.owner_id, command_id=grant.command_id
            )
            assert issued.created is False and issued.attempt == grant
        assert outcome.recorded == stored and b.runner.metrics()["invoked"] == 1
        await denied(b, "known", eligible_cancelled=True)
        return reply(13, 14)
    finally:
        await b.close()


async def verify_crash() -> dict[str, object]:
    b = Bundle()
    try:
        stored = await capture_result(b, "crash", "expired")
        grant = await capture_grant(b, "crash")
        replay = await b.runner.inspect(stored.work_id)
        assert replay.execution.result == stored and replay.applicability == "expired"
        assert await b.execution.find_issue(command_id=grant.command_id) == grant
        assert b.runner.metrics()["invoked"] == 0
        await denied(b, "crash")
        return reply(16, disposition="expired")
    finally:
        await b.close()


async def project_and_refresh(b: Bundle) -> None:
    directory, token = registrations()
    source = load("source.json")["source_id"]
    projector = ProjectionProjector(
        events=open_result_feed_client(settings=settings(), directory=directory, token=token),
        executions=open_execution_client(settings=settings(), directory=directory, token=token),
        projections=open_projection_client(
            settings=settings("projection"), directory=directory, token=token, source_id=source
        ),
        scope=SCOPE,
        evidence=evidence(),
        case_authority=b.cases,
    )
    try:
        await projector.project_once(limit=8)
        await projector.project_once(limit=8)
    finally:
        await projector.close()
    metadata = open_applicability_client(
        settings=settings("projection"),
        directory=directory,
        token=token,
        source_id=source,
        policy=RefreshPolicy(32, 2),
    )
    refresher = ApplicabilityRefresher(
        events=open_result_feed_client(settings=settings(), directory=directory, token=token),
        executions=open_execution_client(settings=settings(), directory=directory, token=token),
        applicability=metadata,
        scope=SCOPE,
        evidence=evidence(),
        case_authority=b.cases,
    )
    views = []
    try:
        for label in RESULT_LABELS:
            row = load("result_" + label + ".json")
            command = str(uuid4())
            refreshed = await refresher.refresh(
                work_id=row["work_id"],
                attempt_id=row["attempt_id"],
                command_id=command,
                expected_revision=0,
            )
            assert (
                await refresher.refresh(
                    work_id=row["work_id"],
                    attempt_id=row["attempt_id"],
                    command_id=command,
                    expected_revision=0,
                )
                == refreshed
            )
            if label in {"expiry", "lease", "cancel", "cancel_lost", "crash", "known"}:
                assert refreshed.classification != "current"
            views.append(
                {
                    "label": label,
                    "work_id": row["work_id"],
                    "attempt_id": row["attempt_id"],
                    "command_id": command,
                    "state": refreshed.classification,
                    "reason": refreshed.reason,
                    "revision": refreshed.revision,
                }
            )
        save("refreshes.json", {"records": views})
    finally:
        await refresher.close()


async def useful() -> dict[str, object]:
    await seed_case("useful")
    b = Bundle()
    delivery: DelegationDeliveryClient | None = None
    try:
        wid = await accepted(b, "useful")
        outcome = await b.runner.run_once(wid, "run_useful")
        stored = await capture_result(b, "useful", "eligible_at_commit")
        assert outcome.view.applicability == "candidate"
        foreign_directory, foreign_token = registrations(foreign=True)
        foreign = open_execution_client(
            settings=settings(), directory=foreign_directory, token=foreign_token
        )
        foreign_work = open_work_client(
            settings=settings(), directory=foreign_directory, token=foreign_token
        )
        try:
            assert await foreign_work.find(idempotency_key="delegation_useful") is None
            assert await foreign.find_issue(command_id="run_useful") is None
            try:
                await foreign.result(work_id=wid, attempt_id=stored.attempt_id)
            except WorkError as error:
                assert error.code == "not_found"
            else:
                raise AssertionError("foreign_result_disclosed")
        finally:
            await foreign.close()
            await foreign_work.close()
        await project_and_refresh(b)
        directory, token = registrations()
        delivery = DelegationDeliveryClient(
            results=b.runner,
            deliveries=open_delivery_client(settings=settings(), directory=directory, token=token),
            receiver=open_result_receiver(
                folder() / "receiver.sqlite3",
                receiver_id=load("receiver.json")["receiver_id"],
                bindings=(
                    ReceiverBinding(WorkScope(SCOPE.tenant_id, SCOPE.account_id), RECIPIENT),
                ),
            ),
            scope=SCOPE,
            evidence=evidence(),
            bindings=(DeliveryBinding("case_useful", "conversation_deadline", RECIPIENT),),
        )
        delivered = await delivery.deliver_once(wid)
        assert delivered.state == "accepted" and delivered.snapshot.receipt is not None
        authorized = await b.authorizer.authorize_once(
            wid, confirmation=exact("useful"), command_id="action_useful"
        )
        effect = await asyncio.to_thread(
            HELPER.mutate, settings("case"), supplier("useful"), state("useful")["task_id"]
        )
        assert effect["effect_state"] == "succeeded"
        inspected = await EXAMPLE.inspect_accepted(
            wid,
            coordinator=b.coordinator,
            runner=b.runner,
            delivery=delivery,
            authorizer=b.authorizer,
        )
        assert (
            inspected.action == authorized.receipt
            and inspected.delivery.snapshot == delivered.snapshot
            and inspected.execution.execution.result == stored
        )
        save(
            "useful.json",
            {
                "work_id": wid,
                "action_id": authorized.receipt.action_id,
                "intent": authorized.receipt.intent.payload(),
                "confirmation": authorized.receipt.confirmation.payload(),
                "receipt_id": delivered.snapshot.receipt.receipt_id,
                "delivery_id": delivered.snapshot.receipt.delivery_id,
            },
        )
        return reply(15, supplier_calls=1, supplier_applied=1)
    finally:
        if delivery is not None:
            await delivery.close()
        await b.close()


def owner_check() -> dict[str, object]:
    global STAGE
    peer = load("peer-observations.json")
    assert len(peer["records"]) == 9
    remote_rows = {r["label"]: r for r in peer["records"]}
    assert set(remote_rows) == set(RESULT_LABELS)
    proof = []
    cancellations = []
    with closing(settings().connect(application_name="continuity-test")) as c:
        for label in LABELS:
            STAGE = "owner_" + label
            original = result(label)
            row = c.execute(
                sql.SQL("SELECT * FROM {}.accepted_work WHERE work_id=%s::uuid").format(
                    sql.Identifier(settings().schema)
                ),
                (original["work_id"],),
            ).fetchone()
            assert row is not None
            body = bytes(row["body"])
            req = parse_request(body)
            assert hashlib.sha256(body).hexdigest() == row["sha256"] == original[
                "request_sha256"
            ] and body == canonical(original["request"])
            assert (
                req.scope == SCOPE
                and row["tenant_id"] == SCOPE.tenant_id
                and row["account_id"] == SCOPE.account_id
            )
            assert row["deadline_at_ms"] == original["deadline_at_ms"] == req.deadline_at_ms
            grant = c.execute(
                sql.SQL("SELECT * FROM {}.issued_attempts WHERE work_id=%s::uuid").format(
                    sql.Identifier(settings().schema)
                ),
                (row["work_id"],),
            ).fetchall()
            values = c.execute(
                sql.SQL("SELECT * FROM {}.attempt_results WHERE work_id=%s::uuid").format(
                    sql.Identifier(settings().schema)
                ),
                (row["work_id"],),
            ).fetchall()
            cancels = c.execute(
                sql.SQL("SELECT * FROM {}.cancellation_commands WHERE work_id=%s::uuid").format(
                    sql.Identifier(settings().schema)
                ),
                (row["work_id"],),
            ).fetchall()
            facts: dict[str, object] = {
                "label": label,
                "scope": {"tenant_id": SCOPE.tenant_id, "account_id": SCOPE.account_id},
                "work_id": str(row["work_id"]),
                "request_sha256": row["sha256"],
                "input_fingerprint": req.input_fingerprint,
                "deadline_at_ms": row["deadline_at_ms"],
                "attempt_id": None,
                "result_sha256": None,
                "disposition": None,
                "cancel_requested": bool(cancels),
            }
            assert len(grant) == (
                0 if label in {"expired_before", "lock_wait", "cancel_before"} else 1
            )
            assert len(values) == (1 if label in RESULT_LABELS else 0)
            for command in cancels:
                saved = load("cancel_" + label + ".json")
                assert (
                    str(command["cancellation_id"]) == saved["cancellation_id"]
                    and command["command_id"] == saved["command_id"]
                    and command["requested_at_ms"] == saved["requested_at_ms"]
                )
                assert (
                    command["tenant_id"] == SCOPE.tenant_id
                    and command["account_id"] == SCOPE.account_id
                )
                cancellations.append(
                    {
                        "work_id": str(row["work_id"]),
                        "command_id": command["command_id"],
                        "cancellation_id": str(command["cancellation_id"]),
                        "requested_at_ms": command["requested_at_ms"],
                    }
                )
            if grant:
                g = grant[0]
                assert g["number"] == g["epoch"] == 1 and str(g["work_id"]) == str(row["work_id"])
                assert g["tenant_id"] == SCOPE.tenant_id and g["account_id"] == SCOPE.account_id
                assert (
                    g["issued_at_ms"]
                    < g["lease_until_ms"]
                    <= min(g["issued_at_ms"] + 2500, row["deadline_at_ms"])
                )
                wire = replace(
                    req, attempt=Attempt("attempt_" + str(g["attempt_id"]).replace("-", ""), 1)
                )
                facts.update(
                    attempt_id=str(g["attempt_id"]),
                    issue_command_id=g["command_id"],
                    issued_at_ms=g["issued_at_ms"],
                    lease_until_ms=g["lease_until_ms"],
                    transport_sha256=hashlib.sha256(encode_request(wire)).hexdigest(),
                )
            if values:
                v = values[0]
                raw = bytes(v["body"])
                stored = parse_result(raw)
                assert hashlib.sha256(raw).hexdigest() == v["sha256"] and str(
                    v["attempt_id"]
                ) == str(grant[0]["attempt_id"])
                assert (
                    stored.input_fingerprint == req.input_fingerprint
                    and stored.scope == SCOPE
                    and stored.request_revision == 2
                    and stored.attempt_id == "attempt_" + str(v["attempt_id"]).replace("-", "")
                )
                expected = (
                    "expired"
                    if label in {"expiry", "crash"}
                    else "lease_expired"
                    if label == "lease"
                    else "cancelled"
                    if label in {"cancel", "cancel_lost"}
                    else "eligible_at_commit"
                )
                assert v["disposition"] == expected
                if expected == "expired":
                    assert stored.completed_at_ms < row["deadline_at_ms"] <= v["recorded_at_ms"]
                if expected == "lease_expired":
                    assert grant[0]["lease_until_ms"] <= v["recorded_at_ms"] < row["deadline_at_ms"]
                if expected == "eligible_at_commit":
                    assert (
                        v["recorded_at_ms"] < grant[0]["lease_until_ms"]
                        and v["recorded_at_ms"] < row["deadline_at_ms"]
                    )
                rr = remote_rows[label]
                assert (
                    rr["delegation_id"] == req.delegation_id
                    and rr["attempt_id"] == stored.attempt_id
                    and rr["input_fingerprint"] == req.input_fingerprint
                )
                assert (
                    rr["request_sha256"] == facts["transport_sha256"]
                    and rr["result_sha256"] == v["sha256"]
                )
                projected = c.execute(
                    sql.SQL("SELECT * FROM {}.projected_results WHERE attempt_id=%s::uuid").format(
                        sql.Identifier(settings("projection").schema)
                    ),
                    (v["attempt_id"],),
                ).fetchone()
                assert projected is not None
                assert (
                    projected["result_sha256"] == v["sha256"]
                    and hashlib.sha256(projected["body_json"].encode()).hexdigest()
                    == projected["body_sha256"]
                )
                event = c.execute(
                    sql.SQL("SELECT * FROM {}.result_feed_events WHERE attempt_id=%s::uuid").format(
                        sql.Identifier(settings().schema)
                    ),
                    (v["attempt_id"],),
                ).fetchone()
                assert event is not None
                assert (
                    event["event_id"] == projected["event_id"]
                    and event["sequence"] == projected["event_sequence"]
                )
                refreshed = c.execute(
                    sql.SQL(
                        "SELECT * FROM {}.applicability_refreshes WHERE event_sequence=%s"
                    ).format(sql.Identifier(settings("projection").schema)),
                    (event["sequence"],),
                ).fetchall()
                assert len(refreshed) == 1
                assert (
                    hashlib.sha256(refreshed[0]["body_json"].encode()).hexdigest()
                    == refreshed[0]["body_sha256"]
                )
                from delegation_reliability.applicability_models import parse_refresh
                from delegation_reliability.projection_models import parse_projected

                p = parse_projected(projected["body_json"].encode())
                r = parse_refresh(refreshed[0]["body_json"].encode())
                assert (
                    p.event.scope == r.event.scope == WorkScope(SCOPE.tenant_id, SCOPE.account_id)
                    and p.event.source_id == r.event.source_id == load("source.json")["source_id"]
                )
                assert (
                    p.event.work_id == r.event.work_id == str(row["work_id"])
                    and p.request_sha256 == r.request_sha256 == row["sha256"]
                    and r.projected_sha256 == projected["body_sha256"]
                )
                assert (
                    r.event.attempt_id == str(v["attempt_id"])
                    and r.event.result_sha256 == v["sha256"]
                    and r.event.disposition == v["disposition"]
                )
                if label in {"expiry", "lease", "cancel", "cancel_lost", "crash", "known"}:
                    assert r.classification != "current"
                facts.update(
                    result_sha256=v["sha256"],
                    recorded_at_ms=v["recorded_at_ms"],
                    reported_completed_at_ms=stored.completed_at_ms,
                    disposition=v["disposition"],
                    event_id=str(event["event_id"]),
                    event_sequence=event["sequence"],
                    projected_sha256=projected["body_sha256"],
                    refresh_sha256=refreshed[0]["body_sha256"],
                    refresh_classification=r.classification,
                    refresh_reason=r.reason,
                )
            action = c.execute(
                sql.SQL("SELECT * FROM {}.result_actions WHERE work_id=%s::uuid").format(
                    sql.Identifier(settings().schema)
                ),
                (row["work_id"],),
            ).fetchone()
            assert (action is not None) == (label == "useful")
            proof.append(facts)
        useful_fact = load("useful.json")
        actions = c.execute(
            sql.SQL("SELECT * FROM {}.result_actions").format(sql.Identifier(settings().schema))
        ).fetchall()
        assert len(actions) == 1
        a = actions[0]
        assert (
            str(a["action_id"]) == useful_fact["action_id"]
            and json.loads(a["intent_json"]) == useful_fact["intent"]
            and json.loads(a["confirmation_json"]) == useful_fact["confirmation"]
        )
        intent = c.execute(
            sql.SQL(
                "SELECT i.*,e.state AS effect_state,e.result_json,e.dispatch_count,o.payload_json AS outcome_json,ce.event_id,cd.state AS notification_state,cd.attempts FROM {}.action_intents i JOIN {}.mutation_effects e USING(intent_id,task_id) JOIN {}.business_outcomes o USING(task_id) JOIN {}.completion_events ce USING(task_id) JOIN {}.completion_deliveries cd USING(event_id) WHERE i.intent_id=%s"
            ).format(*([sql.Identifier(settings("case").schema)] * 5)),
            (str(a["intent_id"]),),
        ).fetchone()
        assert intent is not None
        assert (
            json.loads(intent["payload_json"]) == useful_fact["intent"]
            and intent["effect_state"] == "succeeded"
            and intent["dispatch_count"] == 1
            and intent["notification_state"] == "pending"
            and intent["attempts"] == 0
        )
        with closing(sqlite3.connect(supplier("useful"))) as db:
            calls = db.execute("SELECT count(*) FROM apply_calls").fetchone()[0]
            applied = db.execute(
                "SELECT count(*) FROM apply_calls WHERE outcome='applied'"
            ).fetchone()[0]
            receipts = db.execute("SELECT effect_id,result_json FROM mutation_receipts").fetchall()
            assert calls == applied == len(receipts) == 1
            assert (
                receipts[0][0] == useful_fact["intent"]["effect_id"]
                and json.loads(receipts[0][1])
                == json.loads(intent["result_json"])
                == json.loads(intent["outcome_json"])["result"]
            )
        with closing(sqlite3.connect(supplier())) as db:
            assert db.execute("SELECT count(*) FROM apply_calls").fetchone()[0] == 0
        receiver = c.execute(
            sql.SQL(
                "SELECT i.*,r.receipt_id,r.accepted_at_ms FROM {}.result_delivery_intents i JOIN {}.result_delivery_receipts r USING(delivery_id)"
            ).format(*([sql.Identifier(settings().schema)] * 2))
        ).fetchall()
        assert len(receiver) == 1
        assert (
            str(receiver[0]["delivery_id"]) == useful_fact["delivery_id"]
            and str(receiver[0]["receipt_id"]) == useful_fact["receipt_id"]
            and str(receiver[0]["work_id"]) == useful_fact["work_id"]
        )
        with closing(sqlite3.connect(folder() / "receiver.sqlite3")) as db:
            accepted_rows = db.execute(
                "SELECT delivery_id,intent_json,receipt_json FROM result_receipts"
            ).fetchall()
            assert len(accepted_rows) == 1
            local_id, intent_raw, receipt_raw = accepted_rows[0]
            local_intent, local_receipt = json.loads(intent_raw), json.loads(receipt_raw)
            stored_result = load("result_useful.json")
            pg_intent = receiver[0]
            assert (
                local_id
                == local_intent["delivery_id"]
                == local_receipt["delivery_id"]
                == str(pg_intent["delivery_id"])
            )
            assert local_intent["scope"] == {
                "tenant_id": SCOPE.tenant_id,
                "account_id": SCOPE.account_id,
            }
            for key in ("work_id", "attempt_id", "receiver_id"):
                assert local_intent[key] == str(pg_intent[key])
            assert (
                local_intent["result_sha256"]
                == local_receipt["result_sha256"]
                == stored_result["sha256"]
                == pg_intent["result_sha256"]
            )
            assert (
                local_intent["recipient_id"]
                == local_receipt["recipient_id"]
                == pg_intent["recipient_id"]
                == RECIPIENT
            )
            assert (
                local_receipt["receiver_id"]
                == str(pg_intent["receiver_id"])
                == load("receiver.json")["receiver_id"]
            )
            assert (
                local_receipt["receipt_id"]
                == str(pg_intent["receipt_id"])
                == useful_fact["receipt_id"]
            )
            assert local_receipt["accepted_at_ms"] == pg_intent["accepted_at_ms"]
            assert local_intent["prepared_at_ms"] == pg_intent["prepared_at_ms"]
            assert (
                hashlib.sha256(base64.b64decode(local_intent["body"], validate=True)).hexdigest()
                == stored_result["sha256"]
            )
        counts = c.execute(
            sql.SQL(
                "SELECT (SELECT count(*) FROM {}.accepted_work) AS work,(SELECT count(*) FROM {}.issued_attempts) AS grants,(SELECT count(*) FROM {}.attempt_results) AS results,(SELECT count(*) FROM {}.cancellation_commands) AS cancellations,(SELECT count(*) FROM {}.result_feed_events) AS events,(SELECT count(*) FROM {}.projected_results) AS projected,(SELECT count(*) FROM {}.applicability_refreshes) AS refreshes,(SELECT count(*) FROM {}.action_intents) AS intents,(SELECT count(*) FROM {}.mutation_effects) AS effects"
            ).format(
                *([sql.Identifier(settings().schema)] * 5),
                *([sql.Identifier(settings("projection").schema)] * 2),
                *([sql.Identifier(settings("case").schema)] * 2),
            )
        ).fetchone()
        assert counts == {
            "work": 15,
            "grants": 12,
            "results": 9,
            "cancellations": 5,
            "events": 9,
            "projected": 9,
            "refreshes": 9,
            "intents": 1,
            "effects": 1,
        }
        lock = load("eligibility-lock-proof.json")
        assert (
            lock["deadline_at_ms"] <= lock["observed_after_wait_at_ms"]
            and lock["expected_new_grants"] == 0
        )
    save(
        "authority-proof.json",
        {
            "schema_version": 1,
            "status": "passed",
            "source_id": load("source.json")["source_id"],
            "counts": counts,
            "records": proof,
            "cancellations": cancellations,
            "useful": {
                "action_id": useful_fact["action_id"],
                "intent_id": useful_fact["intent"]["intent_id"],
                "effect_id": useful_fact["intent"]["effect_id"],
                "supplier_all_calls": calls,
                "supplier_applied": applied,
                "receiver_receipt_id": useful_fact["receipt_id"],
                "business_notification_state": "pending",
                "business_notification_attempts": 0,
            },
            "clock_semantics": "P1_database_after_locks; host_and_peer_observations_non_atomic",
        },
    )
    return reply(17, exact_reconciliation=True)


def cleanup() -> dict[str, object]:
    first: Exception | None = None
    try:
        HELPER.cleanup(settings("case"))
    except Exception as error:  # noqa: BLE001 - Attempt remaining isolated owned profiles.
        first = error
    owned = load("owned.json")
    for kind in ("projection", "work"):
        try:
            s = settings(kind)
            assert owned[kind] == s.schema
            with closing(s.connect(application_name="continuity-test")) as c:
                row = c.execute(
                    "SELECT pg_get_userbyid(nspowner) AS owner,obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=%s",
                    (s.schema,),
                ).fetchone()
                if row is not None:
                    assert row["owner"] == "continuity_migrator"
                    assert row["marker"] in (
                        {
                            "delegation-result-projection-v1",
                            "delegation-result-projection-v2",
                            "delegation-result-projection-v3",
                        }
                        if kind == "projection"
                        else {
                            "continuity-readonly-work-v1",
                            "continuity-readonly-work-v2",
                            "continuity-readonly-work-v3",
                            "continuity-readonly-work-v4",
                        }
                    )
                    c.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(s.schema)))
        except Exception as error:  # noqa: BLE001 - Preserve the first failure after all owned attempts.
            if first is None:
                first = error
    if first is not None:
        raise first
    return reply(cleanup_complete=True)


async def run() -> dict[str, object]:
    global STAGE
    STAGE = MODE
    if MODE == "install":
        return install()
    if MODE == "seed":
        await seed_case("deadline")
        return reply(case_revision=2)
    if MODE == "before-issue":
        return await before_issue()
    if MODE == "clock-lock":
        return clock_lock()
    if MODE == "lock-issue":
        return await lock_issue()
    if MODE == "before-http":
        return await before_http()
    if MODE.startswith("invoke-"):
        return await invocation(MODE.removeprefix("invoke-").replace("-", "_"))
    if MODE == "wait-expiry":
        target = os.environ["P3_DEADLINE_TARGET"]
        assert target in {"expiry", "crash"}
        return await wait_time(target)
    if MODE == "wait-lease":
        return await wait_time("lease", lease=True)
    if MODE in {"cancel-ack", "cancel-lost"}:
        return await cancellation("cancel" if MODE == "cancel-ack" else "cancel_lost")
    if MODE.startswith("caller-"):
        return await caller(MODE.replace("-", "_"))
    if MODE == "known-replay":
        return await known()
    if MODE == "crash-late":
        return await invocation("crash")
    if MODE == "verify-crash":
        return await verify_crash()
    if MODE == "useful-current":
        return await useful()
    if MODE == "owner-check":
        return owner_check()
    assert MODE == "cleanup"
    return cleanup()


def main() -> int:
    global MODE
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=MODES)
    MODE = parser.parse_args().mode
    environment()
    try:
        value = asyncio.run(run())
    except Exception as e:  # noqa: BLE001 - Safe fixed tooling diagnostics, no exception reflection.
        print(json.dumps(diagnostic_failure(e, mode=MODE, stage=STAGE)))
        return 1
    print(json.dumps(value))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
