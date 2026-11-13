"""Four explicit public P1/SDK consumers; parent owns SQL, peers and RTC rooms.

The roomless cases use the actual pinned SDK with a deterministic local model.
Only native_stale connects RTC. Fixed copied host support is fixture tooling,
never a checkout product fallback, a second worker queue or mutation authority.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import logging
import os
import re
import stat
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, replace
from pathlib import Path
from types import ModuleType
from typing import Any, TypeVar
from urllib.parse import urlsplit
from uuid import UUID

from livekit import rtc
from livekit.agents import AgentSession, RunContext, RunResult, function_tool, llm
from livekit.agents.voice.events import (
    ConversationItemAddedEvent,
    ToolCallEnded,
    ToolCallStarted,
    ToolCallUpdated,
    ToolExecutionUpdatedEvent,
)

import continuity_lab
import delegation_reliability
from continuity_lab.execution_api import (
    AttemptResult,
    ExecutionClient,
    ExecutionObservation,
    Issuance,
    IssuedAttempt,
    open_execution_client,
)
from continuity_lab.postgres_api import CaseProjection, ManagedCaseClient, open_postgres_client
from continuity_lab.work_api import (
    WorkCancellation,
    WorkClient,
    WorkPayload,
    WorkRecord,
    WorkScope,
    WorkSubmission,
    open_work_client,
)
from delegation_reliability import (
    CaseBinding,
    FixedPolicyCoordinator,
    FixedPolicyRun,
    FixedPolicyRunner,
    ManagedCaseAuthority,
    NativePolicyAgent,
    NativePolicyApplication,
    NativePolicyError,
    NativePolicyObservation,
    SpecialistEndpoint,
    encode_native_policy_observation,
    parse_native_policy_observation,
)
from delegation_reliability.contracts import Scope
from delegation_reliability.fixed_policy import (
    FixedPolicyResultObservation,
    FixedPolicySpecialistClient,
)
from delegation_reliability.fixed_policy_contracts import (
    FixedPolicyRequest,
    encode_fixed_policy_request,
    parse_fixed_policy_result,
    produce_fixed_policy_request,
)
from delegation_reliability.scripted import (
    COMPLETED_REPLY,
    EVALUATE_COMMAND,
    QUESTION_COMMAND,
    USEFUL_REPLY,
    FixtureLLM,
)
from delegation_reliability.security import EvidenceRecord

sys.dont_write_bytecode = True

LABELS = ("native_known", "native_retained", "native_stale", "native_useful")
BASE = {"PATH", "LANG", "CI", "NO_COLOR", "__CF_USER_TEXT_ENCODING"}
ENVIRONMENT = {
    "P3_FIXED_WORK_DIRECTORY",
    "P3_FIXED_WORK_WORK_SCHEMA",
    "P3_FIXED_WORK_CASE_SCHEMA",
    "P3_FIXED_WORK_PG_PORT",
    "P3_FIXED_WORK_RUNTIME_PASSWORD",
    "P3_FIXED_WORK_TOKEN",
}
STAGE, CASE = "setup", None
T = TypeVar("T")


def support(path: Path, name: str) -> ModuleType:
    """Load one declared copied fixture dependency, with dataclass registration."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
LEGACY = support(HERE.with_name("pg_fixed_policy_execution_cases.py"), "native_case_support")
LEGACY.__dict__["MODE"] = "exercise"
CONTROL = support(ROOT / "harness/process_control.py", "native_process_control")
EXAMPLE = support(HERE.parents[1] / "examples/native_fixed_policy.py", "native_public_example")
HTTP = support(ROOT / "local-setup/scripts/p3_native_policy_http.py", "native_http_support")


def canonical(value: object, maximum: int = 65536) -> bytes:
    raw = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    assert 0 < len(raw) <= maximum
    return raw


def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        assert key not in result
        result[key] = value
    return result


def private_directory(path: Path) -> None:
    info = path.lstat()
    assert path.is_absolute() and path.resolve() == path and stat.S_ISDIR(info.st_mode)
    assert info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700


def read(path: Path, maximum: int = 65536) -> bytes:
    private_directory(path.parent)
    before = path.lstat()
    assert (
        stat.S_ISREG(before.st_mode)
        and before.st_uid == os.geteuid()
        and stat.S_IMODE(before.st_mode) == 0o600
        and before.st_nlink == 1
        and 0 < before.st_size <= maximum
    )
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    current = path.lstat()

    def identity(s: os.stat_result) -> tuple[int, int, int, int, int]:
        return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns

    assert identity(before) == identity(opened) == identity(after) == identity(current)
    assert current.st_nlink == 1 and len(raw) == before.st_size <= maximum
    return raw


def load(path: Path, maximum: int = 65536) -> dict[str, Any]:
    # Any is bounded, schema-checked fixture JSON, never an unchecked product port.
    def nonfinite(_value: str) -> object:
        raise AssertionError

    value = json.loads(
        read(path, maximum).decode("utf-8", "strict"),
        object_pairs_hook=object_pairs,
        parse_constant=nonfinite,
    )
    assert type(value) is dict
    return value


def publish(path: Path, value: object, maximum: int = 65536) -> bytes:
    private_directory(path.parent)
    raw = canonical(value, maximum) + b"\n"
    assert len(raw) <= maximum
    pending = path.with_name(path.name + "." + str(os.getpid()) + ".pending")
    owned = False
    try:
        fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        owned = True
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(pending, path, follow_symlinks=False)
    finally:
        if owned:
            pending.unlink(missing_ok=True)
    return raw


async def until(predicate: Callable[[], bool], seconds: float = 5) -> None:
    end = asyncio.get_running_loop().time() + seconds
    while not predicate():
        assert asyncio.get_running_loop().time() < end
        await asyncio.sleep(0.002)


async def barrier(directory: Path, name: str) -> None:
    await asyncio.to_thread(CONTROL.FileBarrier(directory, name).arrive_and_wait, timeout=30)


def config() -> dict[str, Any]:
    LEGACY.environment("exercise")
    assert ENVIRONMENT <= os.environ.keys() and not set(os.environ) - ENVIRONMENT - BASE
    value = load(LEGACY.folder() / "native-policy-runtime.json", 32768)
    assert set(value) == {
        "schema_version",
        "installed",
        "cases",
        "node_token",
        "operator_token",
        "rtc",
        "assets",
    }
    assert type(value["schema_version"]) is int and value["schema_version"] == 1
    assert type(value["installed"]) is bool and set(value["cases"]) == set(LABELS)
    for row in value["cases"].values():
        assert type(row) is dict and set(row) == {"owner_id", "command_id"}
        assert type(row["owner_id"]) is str and str(UUID(row["owner_id"])) == row["owner_id"]
        assert UUID(row["owner_id"]).version == 4
        assert type(row["command_id"]) is str and re.fullmatch(
            r"[A-Za-z0-9_.:-]{1,64}", row["command_id"]
        )
    assert len({r["owner_id"] for r in value["cases"].values()}) == 4
    assert len({r["command_id"] for r in value["cases"].values()}) == 4
    for name in ("node_token", "operator_token"):
        assert type(value[name]) is str and re.fullmatch(r"[A-Za-z0-9_-]{43}", value[name])
    assert set(value["rtc"]) == {
        "schema_version",
        "kind",
        "session_id",
        "server_url",
        "room_name",
        "participant_identity",
        "agent_identity",
        "rtc_token",
        "profile",
        "inference_mode",
        "expires_at_ms",
        "agent_token",
    }
    assert value["rtc"]["schema_version"] == 1 and value["rtc"]["kind"] == "native-policy.session"
    assert (
        value["rtc"]["profile"] == "p3_native_policy_text_v1"
        and value["rtc"]["inference_mode"] == "scripted"
    )
    rtc_config = value["rtc"]
    for name in ("room_name", "participant_identity", "agent_identity"):
        assert type(rtc_config[name]) is str and re.fullmatch(
            r"[A-Za-z0-9_.:-]{1,64}", rtc_config[name]
        )
    assert (
        type(rtc_config["session_id"]) is str
        and str(UUID(rtc_config["session_id"])) == rtc_config["session_id"]
    )
    assert UUID(rtc_config["session_id"]).version == 4
    for name in ("rtc_token", "agent_token"):
        assert type(rtc_config[name]) is str and 1 <= len(rtc_config[name].encode("utf-8")) <= 4096
    url = urlsplit(rtc_config["server_url"])
    assert url.scheme == "ws" and url.hostname in {"127.0.0.1", "localhost"}
    assert url.port is not None and 1 <= url.port <= 65535
    assert (
        url.path in {"", "/"}
        and not url.query
        and not url.fragment
        and url.username is None
        and url.password is None
    )
    assert (
        type(rtc_config["expires_at_ms"]) is int
        and time.time_ns() // 1_000_000 < rtc_config["expires_at_ms"] <= 4102444800000
    )
    assert type(value["assets"]) is str
    private_directory(Path(value["assets"]))
    if value["installed"]:
        for package in (continuity_lab, delegation_reliability):
            assert package.__file__ is not None
            assert Path(package.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
    return value


class SafeLogs(logging.Handler):
    """Do not format SDK record arguments, exception text, prompts or tokens."""

    def __init__(self) -> None:
        super().__init__()
        self.counts = {"debug": 0, "info": 0, "warning": 0, "error": 0}

    def emit(self, record: logging.LogRecord) -> None:
        name = (
            "error"
            if record.levelno >= 40
            else "warning"
            if record.levelno >= 30
            else "info"
            if record.levelno >= 20
            else "debug"
        )
        self.counts[name] += 1


class CountingWork:
    def __init__(self, actual: WorkClient) -> None:
        self.actual = actual
        self.counts = {name: 0 for name in ("submit", "find", "get", "cancel", "close")}

    @property
    def scope(self) -> WorkScope:
        return self.actual.scope

    @property
    def pending_count(self) -> int:
        return self.actual.pending_count

    async def submit(self, *, idempotency_key: str, payload: WorkPayload) -> WorkSubmission:
        self.counts["submit"] += 1
        return await self.actual.submit(idempotency_key=idempotency_key, payload=payload)

    async def find(self, *, idempotency_key: str) -> WorkRecord | None:
        self.counts["find"] += 1
        return await self.actual.find(idempotency_key=idempotency_key)

    async def get(self, *, work_id: str) -> WorkRecord:
        self.counts["get"] += 1
        return await self.actual.get(work_id=work_id)

    async def cancel(self, *, work_id: str, command_id: str) -> WorkCancellation:
        self.counts["cancel"] += 1
        return await self.actual.cancel(work_id=work_id, command_id=command_id)

    async def close(self) -> None:
        self.counts["close"] += 1
        await self.actual.close()


class CountingExecution:
    def __init__(self, actual: ExecutionClient) -> None:
        self.actual = actual
        self.counts = {
            name: 0 for name in ("issue", "find_issue", "complete", "result", "observe", "close")
        }
        self.issued: IssuedAttempt | None = None

    @property
    def scope(self) -> WorkScope:
        return self.actual.scope

    @property
    def pending_count(self) -> int:
        return self.actual.pending_count

    async def issue(self, *, work_id: str, owner_id: str, command_id: str) -> Issuance:
        self.counts["issue"] += 1
        value = await self.actual.issue(work_id=work_id, owner_id=owner_id, command_id=command_id)
        self.issued = value.attempt
        return value

    async def find_issue(self, *, command_id: str) -> IssuedAttempt | None:
        self.counts["find_issue"] += 1
        return await self.actual.find_issue(command_id=command_id)

    async def complete(self, *, attempt: IssuedAttempt, body: bytes) -> AttemptResult:
        self.counts["complete"] += 1
        return await self.actual.complete(attempt=attempt, body=body)

    async def result(self, *, work_id: str, attempt_id: str) -> AttemptResult | None:
        self.counts["result"] += 1
        return await self.actual.result(work_id=work_id, attempt_id=attempt_id)

    async def observe(self, *, work_id: str) -> ExecutionObservation:
        self.counts["observe"] += 1
        return await self.actual.observe(work_id=work_id)

    async def close(self) -> None:
        self.counts["close"] += 1
        await self.actual.close()


class CountingSpecialist:
    def __init__(self, actual: FixedPolicySpecialistClient) -> None:
        self.actual, self.invocations = actual, 0
        self.request: FixedPolicyRequest | None = None

    async def invoke_observed(
        self, request: FixedPolicyRequest, *, evidence: tuple[EvidenceRecord, ...]
    ) -> FixedPolicyResultObservation:
        self.invocations += 1
        self.request = request
        return await self.actual.invoke_observed(request, evidence=evidence)

    async def close(self) -> None:
        await self.actual.close()


class ObservedRunner(FixedPolicyRunner):
    """Record only the actual public run_once wrapper Task, never private owners."""

    wrapper_task: asyncio.Task[Any] | None = None

    async def run_once(self, work_id: str, command_id: str) -> FixedPolicyRun:
        self.wrapper_task = asyncio.current_task()
        return await super().run_once(work_id, command_id)


class CapturingAgent(NativePolicyAgent):
    context: RunContext[None] | None = None

    @function_tool(on_duplicate="reject", flags=llm.ToolFlag.CANCELLABLE)
    async def evaluate_policy(self, ctx: RunContext[None]) -> str:
        """Delegate the unchanged public tool and retain its actual SDK context."""
        self.context = ctx
        return await NativePolicyAgent.evaluate_policy(self, ctx)


class SDKFacts:
    def __init__(self, session: AgentSession[None]) -> None:
        self.events: list[dict[str, object]] = []
        self.useful = self.completed = 0
        session.on("tool_execution_updated", self.tool)
        session.on("conversation_item_added", self.conversation)

    def tool(self, event: ToolExecutionUpdatedEvent) -> None:
        update = event.update
        if isinstance(update, ToolCallStarted):
            row: dict[str, object] = {
                "type": "started",
                "call_id": update.function_call.call_id,
                "name": update.function_call.name,
            }
        elif isinstance(update, ToolCallUpdated):
            assert len(update.message.encode()) <= 512
            row = {
                "type": "updated",
                "call_id": update.call_id,
                "message": update.message,
                "silent": update.silent,
            }
        elif isinstance(update, ToolCallEnded):
            row = {"type": "ended", "call_id": update.call_id, "status": update.status}
        else:
            return
        assert len(self.events) < 24
        self.events.append(row)

    def conversation(self, event: ConversationItemAddedEvent) -> None:
        item = event.item
        if isinstance(item, llm.ChatMessage) and item.role == "assistant":
            self.useful += int(item.text_content == USEFUL_REPLY)
            self.completed += int(item.text_content == COMPLETED_REPLY)

    def payload(self) -> dict[str, object]:
        return {
            "events": list(self.events),
            "useful_replies": self.useful,
            "completed_replies": self.completed,
        }


def work_wire(record: WorkRecord) -> dict[str, Any]:
    value = asdict(record)
    value["payload"]["body"] = record.payload.body.decode("utf-8")
    value["payload"]["sha256"] = record.payload.sha256
    return value


def issued_wire(attempt: IssuedAttempt) -> dict[str, Any]:
    value = asdict(attempt)
    value["record"] = work_wire(attempt.record)
    return value


def result_wire(result: AttemptResult) -> dict[str, Any]:
    value = asdict(result)
    value["body"] = parse_fixed_policy_result(result.body).to_wire()
    value["sha256"] = result.sha256
    return value


class CaseRun:
    def __init__(
        self,
        label: str,
        configured: dict[str, Any],
        request: FixedPolicyRequest,
        records: tuple[EvidenceRecord, ...],
        case_client: ManagedCaseClient,
        case_state: dict[str, Any],
        endpoint: dict[str, Any],
        work: WorkClient,
        execution: ExecutionClient,
    ) -> None:
        self.label, self.configured, self.request, self.records = (
            label,
            configured,
            request,
            records,
        )
        self.directory = LEGACY.folder() / "cases" / label
        self.case_client, self.case_state = case_client, case_state
        self.work = CountingWork(work)
        self.execution = CountingExecution(execution)
        self.specialist = CountingSpecialist(
            FixedPolicySpecialistClient(
                SpecialistEndpoint(endpoint["endpoint"]["port"]),
                "Bearer " + configured["node_token"],
                timeout_ms=5000,
                cleanup_ms=100,
            )
        )
        self.authority = ManagedCaseAuthority(
            case_client,
            scope=LEGACY.scope(),
            bindings=tuple(
                CaseBinding(k, v["task_id"], v["case_id"]) for k, v in case_state.items()
            ),
        )
        self.coordinator = FixedPolicyCoordinator(
            executions=self.work,
            scope=LEGACY.scope(),
            case_authority=self.authority,
            cleanup_ms=100,
        )
        self.runner = ObservedRunner(
            executions=self.execution,
            scope=LEGACY.scope(),
            owner_id=configured["cases"][label]["owner_id"],
            specialist=self.specialist,
            case_authority=self.authority,
            evidence=records,
            max_active=2,
            timeout_ms=1000 if label == "native_retained" else 5000,
            cleanup_ms=100,
        )
        self.app = NativePolicyApplication(
            coordinator=self.coordinator,
            runner=self.runner,
            request=request,
            evidence=records,
            command_id=configured["cases"][label]["command_id"],
            cleanup_ms=100,
        )
        self.model: FixtureLLM | None = None
        self.session: AgentSession[None] | None = None
        self.facts: SDKFacts | None = None
        self.agent: CapturingAgent | None = None
        self.session_close: asyncio.Task[None] | None = None
        self.session_closed = self.model_closed = self.app_closed = False
        self.shared_case_closed = False
        self.stored: AttemptResult | None = None
        self.ownership: dict[str, object] = {}
        self.host: Any = None  # Declared copied host-only fixture module, not a product port.
        self.room: rtc.Room | None = None

    def initialize_sdk(self) -> None:
        assert self.session is None
        self.model = FixtureLLM()
        self.session = AgentSession(llm=self.model, max_tool_steps=3, user_away_timeout=None)
        self.facts = SDKFacts(self.session)
        self.agent = CapturingAgent(self.app)

    @classmethod
    async def create(
        cls,
        label: str,
        configured: dict[str, Any],
        request: FixedPolicyRequest,
        records: tuple[EvidenceRecord, ...],
        case_client: ManagedCaseClient,
        case_state: dict[str, Any],
        endpoint: dict[str, Any],
    ) -> CaseRun:
        # Public DB factories validate an existing profile synchronously. Only
        # those factories leave the loop; AgentSession must bind the actual loop.
        directory, token = LEGACY.directory()
        work = await asyncio.to_thread(
            open_work_client, settings=LEGACY.settings(), directory=directory, token=token
        )
        try:
            execution = await asyncio.to_thread(
                open_execution_client, settings=LEGACY.settings(), directory=directory, token=token
            )
        except BaseException:
            await work.close()
            raise
        try:
            return cls(
                label,
                configured,
                request,
                records,
                case_client,
                case_state,
                endpoint,
                work,
                execution,
            )
        except BaseException:
            await asyncio.gather(work.close(), execution.close(), return_exceptions=True)
            raise

    def writes(self) -> dict[str, int]:
        return {
            "submit": self.work.counts["submit"],
            "cancel": self.work.counts["cancel"],
            "issue": self.execution.counts["issue"],
            "complete": self.execution.counts["complete"],
            "invoke": self.specialist.invocations,
        }

    async def close_session(self) -> None:
        if self.session is None:
            return
        if self.session_close is None:
            self.session_close = asyncio.create_task(self.session.aclose(), name="native-sdk-close")
            self.session_close.add_done_callback(lambda t: None if t.cancelled() else t.exception())
        async with asyncio.timeout(2):
            await asyncio.shield(self.session_close)
        self.session_closed = True

    async def close(self) -> None:
        self.app.stop()
        if self.host is not None:
            self.host.stop()
        # Independent SDK/HTTP/facade close attempts always run, even on a sibling failure.
        outcomes = await asyncio.gather(
            self.close_session(),
            self.app.close(),
            *([self.host.close()] if self.host is not None else []),
            return_exceptions=True,
        )
        self.app_closed = not isinstance(outcomes[1], BaseException)
        dependent = any(isinstance(x, BaseException) for x in outcomes)
        if self.session_closed and self.model is not None:
            independent = await asyncio.gather(
                self.model.aclose(),
                *([self.room.disconnect()] if self.room is not None else []),
                return_exceptions=True,
            )
            self.model_closed = not isinstance(independent[0], BaseException)
            dependent = dependent or any(isinstance(x, BaseException) for x in independent)
        if dependent:
            raise NativePolicyError("cleanup_incomplete")
        assert self.runner.pending_count == self.coordinator.pending_count == 0

    async def observed(self) -> NativePolicyObservation:
        return await self.app.inspect_observed()

    async def hold_seen(self) -> None:
        path = self.directory / "native_policy_held.reached"
        await until(lambda: path.exists() and path.lstat().st_nlink == 1)
        # The parent independently joins this marker PID to its exact Node handle.
        raw = read(path, 32)
        assert re.fullmatch(rb"[1-9][0-9]{0,19}\n", raw)
        assert self.specialist.invocations == 1 and self.execution.issued is not None
        assert self.execution.counts["complete"] == 0

    def pre_entry_denials(self, no_work: NativePolicyObservation) -> None:
        """Installed public contract rejection, before any execution or transport.

        This does not claim cross-scope PG authorization. The real positive
        case binding is checked separately by public case_setup and authority.
        """
        before = self.writes()
        assert before == {"submit": 0, "cancel": 0, "issue": 0, "complete": 0, "invoke": 0}
        zero_revision = replace(self.request, request_revision=0)
        logical = zero_revision.to_wire()
        zero_revision = replace(
            zero_revision,
            input_fingerprint=hashlib.sha256(
                canonical(
                    {k: v for k, v in logical.items() if k not in {"attempt", "input_fingerprint"}}
                )
            ).hexdigest(),
        )
        foreign = replace(
            self.records[0], scope=Scope(self.request.scope.tenant_id, "foreign_native_account")
        )
        probes = (
            ("zero_revision_request", zero_revision, self.records),
            ("foreign_evidence_scope", self.request, (foreign, self.records[1])),
        )
        outcomes: list[dict[str, str]] = []
        for name, candidate, evidence in probes:
            try:
                NativePolicyApplication(
                    coordinator=self.coordinator,
                    runner=self.runner,
                    request=candidate,
                    evidence=evidence,
                    command_id=self.configured["cases"][self.label]["command_id"],
                )
            except NativePolicyError as error:
                assert error.code == "invalid_input"
                outcomes.append({"name": name, "code": error.code})
            else:
                raise AssertionError
        malformed = no_work.to_wire()
        malformed["owned_run"] = "true"
        try:
            parse_native_policy_observation(canonical(malformed, 4096))
        except NativePolicyError as error:
            assert error.code == "invalid_observation"
            outcomes.append({"name": "malformed_observation", "code": error.code})
        else:
            raise AssertionError
        assert self.writes() == before
        self.ownership["pre_entry_denials"] = {
            "cases": outcomes,
            "before": before,
            "after": self.writes(),
        }

    async def roomless(self) -> tuple[NativePolicyObservation, dict[str, object]]:
        global STAGE
        STAGE = "sdk_start"
        self.initialize_sdk()
        assert self.session is not None and self.facts is not None and self.agent is not None
        facts = self.facts
        await self.session.start(self.agent, record=False)
        no_work = await self.observed()
        assert no_work.state == "no_work" and self.work.counts["find"] == 1
        if self.label == "native_known":
            self.pre_entry_denials(no_work)
        STAGE = "held_followup"
        await self.session.run(user_input=EVALUATE_COMMAND)
        await self.hold_seen()
        reply: RunResult[None] = await self.session.run(user_input=QUESTION_COMMAND)
        assert any(
            x.type == "message" and x.item.text_content == USEFUL_REPLY for x in reply.events
        )
        assert self.facts.useful == 1 and self.facts.completed == 0
        assert (await self.observed()).state == "work" and self.runner.pending_count == 1
        self.ownership["no_work"] = no_work.to_wire()
        if self.label == "native_retained":
            return await self.retained()
        await barrier(self.directory, "native_followup")
        STAGE = "result"
        await until(lambda: facts.completed == 1 and self.runner.pending_count == 0)
        observed = await self.observed()
        assert observed.state == "result" and observed.to_wire()["applicability"] == "candidate"
        before = self.writes()
        await self.session.run(user_input=EVALUATE_COMMAND)
        await until(lambda: facts.completed == 2)
        replay = await self.observed()
        assert self.writes() == before
        assert replay.to_wire()["result"] == observed.to_wire()["result"]
        return observed, {"before": before, "after": self.writes(), "observation": replay.to_wire()}

    async def retained(self) -> tuple[NativePolicyObservation, dict[str, object]]:
        global STAGE
        STAGE = "retained_waiter"
        assert self.agent is not None and self.facts is not None
        await self.close_session()
        assert any(x.get("status") == "cancelled" for x in self.facts.events)
        await until(
            lambda: self.runner.wrapper_task is not None and self.runner.wrapper_task.done()
        )
        assert self.runner.pending_count == 1 and self.app.metrics()["owned_run"] == 1
        assert self.agent.context is not None
        before = self.writes()
        try:
            await self.app.evaluate(self.agent.context)
        except NativePolicyError as error:
            assert error.code == "capacity"
        else:
            raise AssertionError
        assert self.writes() == before
        read_while_held = await self.observed()
        assert (
            read_while_held.state == "work"
            and read_while_held.to_wire()["tool_waiter"] == "stopped_waiting"
        )
        STAGE = "retained_close"
        try:
            await self.app.close()
        except NativePolicyError as close_error:
            assert close_error.code == "cleanup_incomplete"
        else:
            raise AssertionError
        # Shared case reader remains open until the dependent facades actually settle.
        still_open = await self.case_client.get(
            task_id=self.case_state["case_fixed"]["task_id"], limit=1
        )
        wrapper = self.runner.wrapper_task
        assert wrapper is not None
        self.ownership.update(
            {
                "wrapper_done_while_pending": wrapper.done(),
                "runner_pending_held": self.runner.pending_count,
                "new_call_code": "capacity",
                "read_while_held": read_while_held.to_wire(),
                "close_code": "cleanup_incomplete",
                "shared_reader_open": type(still_open) is CaseProjection,
            }
        )
        await barrier(self.directory, "native_retained_ready")
        STAGE = "retained_result"
        await until(lambda: self.runner.pending_count == 0)
        await self.app.close()
        self.app_closed = True
        # A fresh public inspector reads the original; no evaluate/issue/HTTP reinvocation.
        endpoint = load(self.directory / "native-policy-endpoint.json")
        fresh = await CaseRun.create(
            self.label,
            self.configured,
            self.request,
            self.records,
            self.case_client,
            self.case_state,
            endpoint,
        )
        replay_before = self.writes()
        try:
            observed = await fresh.observed()
            assert observed.state == "result"
            assert fresh.writes() == {
                "submit": 0,
                "cancel": 0,
                "issue": 0,
                "complete": 0,
                "invoke": 0,
            }
            self.ownership["fresh_inspector_writes"] = fresh.writes()
            assert fresh.session is None
            self.ownership["fresh_inspector_sdk_sessions"] = 0
            self.ownership["late_original"] = observed.to_wire()
            attempt = self.execution.issued
            assert attempt is not None
            self.stored = await fresh.execution.result(
                work_id=attempt.record.work_id, attempt_id=attempt.attempt_id
            )
            assert self.stored is not None
        finally:
            await fresh.close()
        assert self.writes() == replay_before
        return observed, {
            "before": replay_before,
            "after": self.writes(),
            "observation": observed.to_wire(),
        }

    async def browser(self) -> tuple[NativePolicyObservation, dict[str, object]]:
        global STAGE
        STAGE = "rtc_start"
        self.initialize_sdk()
        assert self.session is not None and self.facts is not None
        configuration = self.configured["rtc"]
        self.room = rtc.Room()
        await self.room.connect(configuration["server_url"], configuration["agent_token"])
        session_json = {key: value for key, value in configuration.items() if key != "agent_token"}
        session_json["binding"] = self.app.binding

        async def observe() -> bytes:
            return encode_native_policy_observation(await self.observed())

        self.host = HTTP.NativePolicyHttp(
            canonical(session_json, 8192),
            observe,
            operator_token=self.configured["operator_token"],
            assets=Path(self.configured["assets"]),
        )
        endpoint = await self.host.start()
        publish(
            self.directory / "native-policy-ui-endpoint.json",
            {
                "schema_version": 1,
                "origin": endpoint.origin,
                "session_id": configuration["session_id"],
            },
        )
        # Starting the configured example can await the exact browser; HTTP must be live first.
        start = asyncio.create_task(
            EXAMPLE.start_native_fixed_policy(
                session=self.session,
                application=self.app,
                room=self.room,
                participant_identity=configuration["participant_identity"],
            ),
            name="native-room-start",
        )
        start.add_done_callback(lambda t: None if t.cancelled() else t.exception())
        try:
            await barrier(self.directory, "native_ui_ready")
            async with asyncio.timeout(15):
                await asyncio.shield(start)
                assert self.session.room_io is not None
                await self.session.room_io.wait_for_ready()
            linked = self.session.room_io.linked_participant
            assert linked is not None and linked.identity == configuration["participant_identity"]
            assert (
                self.session.room_io.audio_input is None
                and self.session.room_io.audio_output is None
            )
            assert self.session.room_io.transcription_output is not None
            assert self.session.agent_state in {"idle", "listening", "thinking", "speaking"}
            await self.room.local_participant.set_attributes(
                {
                    "p3.native_policy.ready": "true",
                    "p3.native_policy.profile": "p3_native_policy_text_v1",
                    "p3.native_policy.session_id": configuration["session_id"],
                    "p3.inference_mode": "scripted",
                }
            )
            self.ownership["room_io"] = {
                "participant_identity": linked.identity,
                "audio_input": False,
                "audio_output": False,
                "text_output": True,
                "session_host": False,
            }
            STAGE = "browser"
            await barrier(self.directory, "native_browser_finished")
            observed = await self.observed()
            assert (
                observed.state == "outdated" and observed.to_wire()["applicability"] == "outdated"
            )
            assert self.specialist.invocations == 1 and self.facts.useful >= 1
            before = self.writes()
            replay = await self.observed()
            assert self.writes() == before
            return observed, {
                "before": before,
                "after": self.writes(),
                "observation": replay.to_wire(),
            }
        finally:
            await self.room.local_participant.set_attributes({"p3.native_policy.ready": "false"})
            if not start.done():
                # SDK close is attempted by the case owner before this observer is joined.
                await self.close_session()
            await asyncio.gather(start, return_exceptions=True)

    async def proof(
        self,
        before: dict[str, object],
        observation: NativePolicyObservation,
        replay: dict[str, object],
    ) -> dict[str, object]:
        attempt = self.execution.issued
        assert self.facts is not None
        assert attempt is not None and self.specialist.request is not None
        stored = self.stored
        if stored is None:
            stored = await self.execution.result(
                work_id=attempt.record.work_id, attempt_id=attempt.attempt_id
            )
        assert stored is not None and stored.work_id == attempt.record.work_id
        assert stored.attempt_id == attempt.attempt_id and self.specialist.invocations == 1
        assert (
            self.work.counts["submit"]
            == self.execution.counts["issue"]
            == self.execution.counts["complete"]
            == 1
        )
        assert self.work.counts["cancel"] == 0
        after = (
            await self.case_client.get(task_id=self.case_state["case_fixed"]["task_id"], limit=10)
        ).payload()
        return {
            "schema_version": 1,
            "kind": "native-policy.case",
            "name": self.label,
            "scope": asdict(self.request.scope),
            "request": self.request.to_wire(),
            "case_before": before,
            "case_after": after,
            "observation": observation.to_wire(),
            "accepted": work_wire(attempt.record),
            "issued": issued_wire(attempt),
            "stored_result": result_wire(stored),
            "sdk": self.facts.payload(),
            "counters": {
                "work": dict(self.work.counts),
                "execution": dict(self.execution.counts),
                "specialist": {
                    "invocations": self.specialist.invocations,
                    "metrics": dict(self.specialist.actual.metrics()),
                },
                "app": dict(self.app.metrics()),
            },
            "replay": replay,
            "ownership": dict(self.ownership),
            "cleanup_complete": False,
        }


def request(label: str) -> FixedPolicyRequest:
    value = LEGACY.request("known").to_wire()
    value.pop("input_fingerprint")
    value["delegation_id"] = label
    value["case_id"] = "case_fixed"
    value["request_revision"] = 2 if label == "native_useful" else 1
    value["result_route"] = {"conversation_id": "conversation_" + label}
    value["attempt"] = {"attempt_id": "proposal_" + label, "number": 1}
    return produce_fixed_policy_request(value)


async def run(configured: dict[str, Any]) -> dict[str, object]:
    global STAGE, CASE
    STAGE = "case_setup"
    await LEGACY.case_setup()
    case_state = LEGACY.load("fixed-work-cases.json")
    _, token = LEGACY.directory()
    descriptors: list[dict[str, object]] = []
    for label in LABELS:
        CASE, STAGE = label, "enroll"
        directory = LEGACY.folder() / "cases" / label
        private_directory(directory)
        value, records = request(label), LEGACY.evidence("known")
        publish(
            directory / "native-policy-input.json",
            {
                "schema_version": 1,
                "owner_id": configured["cases"][label]["owner_id"],
                "request_utf8": encode_fixed_policy_request(value).decode(),
                "evidence": [
                    {
                        "scope": asdict(row.scope),
                        "reference": asdict(row.reference),
                        "body_utf8": row.body.decode(),
                    }
                    for row in records
                ],
            },
            131072,
        )
        await barrier(directory, "native_node_ready")
        endpoint = load(directory / "native-policy-endpoint.json")
        assert set(endpoint) == {
            "schema_version",
            "kind",
            "endpoint",
            "owner_id",
            "input_sha256",
            "template_sha256",
        }
        assert type(endpoint["schema_version"]) is int and endpoint["schema_version"] == 1
        assert (
            endpoint["kind"] == "native-policy.endpoint"
            and endpoint["owner_id"] == configured["cases"][label]["owner_id"]
        )
        assert type(endpoint["endpoint"]) is dict and set(endpoint["endpoint"]) == {"host", "port"}
        assert endpoint["endpoint"]["host"] == "127.0.0.1"
        assert (
            type(endpoint["endpoint"]["port"]) is int and 1 <= endpoint["endpoint"]["port"] <= 65535
        )
        assert (
            endpoint["input_sha256"]
            == hashlib.sha256(read(directory / "native-policy-input.json", 131072)).hexdigest()
        )
        assert (
            endpoint["template_sha256"]
            == hashlib.sha256(encode_fixed_policy_request(value)).hexdigest()
        )
        case_client = await asyncio.to_thread(
            open_postgres_client,
            actor=LEGACY.ACTOR,
            token=token,
            settings=LEGACY.settings("case"),
            quote_database=LEGACY.folder() / "supplier.sqlite3",
        )
        actor = await CaseRun.create(
            label, configured, value, records, case_client, case_state, endpoint
        )
        failure: BaseException | None = None
        failed_stage = STAGE
        try:
            before = (
                await case_client.get(task_id=case_state["case_fixed"]["task_id"], limit=10)
            ).payload()
            observed, replay = await (
                actor.browser() if label == "native_stale" else actor.roomless()
            )
            proof = await actor.proof(before, observed, replay)
        except BaseException as error:  # noqa: BLE001 - Preserve the primary across independent owner close attempts.
            failure, failed_stage = error, STAGE
        try:
            STAGE = "close"
            await actor.close()
            await case_client.close()
            actor.shared_case_closed = True
        except BaseException:
            if failure is None:
                raise
        if failure is not None:
            STAGE = failed_stage
            raise failure
        proof["cleanup_complete"] = True
        assert actor.facts is not None
        proof["sdk"] = actor.facts.payload()
        proof["ownership"] = {
            **actor.ownership,
            "session_closed": actor.session_closed,
            "app_closed": actor.app_closed,
            "model_closed": actor.model_closed,
            "shared_case_closed": actor.shared_case_closed,
            "coordinator_pending": actor.coordinator.pending_count,
            "runner_pending": actor.runner.pending_count,
            "room_disconnected": actor.room is None or not actor.room.isconnected(),
            "session_close_done": actor.session_close is not None and actor.session_close.done(),
        }
        raw = publish(directory / "case-proof.json", proof)
        descriptors.append(
            {
                "name": label,
                "path": "cases/" + label + "/case-proof.json",
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
        STAGE = "case_done"
        await barrier(directory, "native_case_done")
    STAGE = "complete"
    reply = {
        "schema_version": 1,
        "kind": "native-policy.consumer",
        "status": "passed",
        "cases": descriptors,
        "installed_prefix_verified": configured["installed"],
        "shared_case_closed": True,
        "cleanup_complete": True,
    }
    publish(LEGACY.folder() / "native-policy-consumer-proof.json", reply)
    return reply


def main() -> int:
    os.umask(0o077)
    logs = SafeLogs()
    logging.getLogger().handlers[:] = [logs]
    logging.getLogger().setLevel(logging.INFO)
    try:
        assert sys.argv[1:] == ["run"]
        result = asyncio.run(run(config()))
    except Exception:  # noqa: BLE001 - Fixed finite diagnostics never reflect exceptions or credentials.
        result = {
            "schema_version": 1,
            "kind": "native-policy.consumer",
            "status": "failed",
            "case": CASE,
            "stage": STAGE,
            "code": "fixture_failed",
            "cleanup_complete": False,
        }
        try:
            publish(LEGACY.folder() / "native-policy-consumer-failure.json", result, 4096)
        except Exception:  # noqa: BLE001 - Retention failure cannot replace the primary safe frame.
            logging.getLogger(__name__).error("native_fixture_retention_failed")
        print(canonical(result).decode(), flush=True)
        return 1
    print(canonical(result).decode(), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
