"""Explicit source-gate consumer of origin-bound work and public P1/P2 ports.

Imports start no I/O. The supplied specialist is scripted; source/runtime SQL,
receiver acceptance, native reads and human acknowledgement remain distinct facts.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import math
import os
import re
import stat
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal, Protocol, TypeVar, cast
from uuid import UUID, uuid4

from continuity_lab.case_control_api import BookingChange, open_case_control_client
from continuity_lab.delivery_api import open_delivery_client
from continuity_lab.execution_api import open_execution_client
from continuity_lab.postgres_api import AuthenticatedActor, open_postgres_client
from continuity_lab.work_api import (
    BearerToken,
    PostgresSettings,
    WorkCancellation,
    WorkDirectory,
    WorkError,
    WorkPayload,
    WorkPrincipal,
    WorkRecord,
    WorkScope,
    WorkSubmission,
    open_work_client,
)
from delegation_reliability import (
    CaseBinding,
    ChannelPolicyCoordinator,
    ChannelPolicyDeliveryClient,
    ChannelPolicyRequest,
    ChannelPolicyRun,
    ChannelPolicyRunner,
    ChannelPolicyView,
    CompletionError,
    CoordinatorError,
    DeliveryBinding,
    FixedPolicyResultObservation,
    ManagedCaseAuthority,
    ResultReceiverPort,
    encode_channel_policy_request,
    encode_channel_policy_result,
    parse_channel_policy_request,
    produce_channel_policy_request,
)
from delegation_reliability.contracts import EvidenceRef, Scope, canonical, identifier
from delegation_reliability.coordinator import CaseSnapshot
from delegation_reliability.fixed_policy import (
    snapshot_fixed_policy_records,
    verify_fixed_policy_facts,
)
from delegation_reliability.fixed_policy_contracts import (
    FixedPolicyRequest,
    parse_fixed_policy_result,
    produce_fixed_policy_request,
)
from delegation_reliability.security import EvidenceRecord

ROOT = Path(__file__).resolve().parents[2]
BASE = frozenset({"PATH", "LANG", "CI", "NO_COLOR"})
OPTIONAL_BASE = frozenset({"__CF_USER_TEXT_ENCODING"})
ENVIRONMENT = frozenset(
    {
        "P3_ORIGIN_DIRECTORY",
        "P3_ORIGIN_PG_PORT",
        "P3_ORIGIN_RUNTIME_PASSWORD",
        "P3_ORIGIN_WORK_TOKEN",
        "P3_ORIGIN_CASE_TOKEN",
        "P3_ORIGIN_PUBLISHER_TOKEN",
    }
)
_LABELS = frozenset({"a", "b"})
_SHA = re.compile(r"[0-9a-f]{64}", re.ASCII)


class ConsumerError(RuntimeError):
    """One finite fixture error, with no private dependency text or getters."""

    def __init__(self) -> None:
        super().__init__("origin_consumer_failed")


def require(value: object) -> None:
    if value is not True:
        raise ConsumerError()


def uuid_value(value: object) -> str:
    require(type(value) is str and len(value) == 36)
    assert isinstance(value, str)
    try:
        parsed = UUID(value)
    except ValueError:
        raise ConsumerError() from None
    require(parsed.version == 4 and str(parsed) == value)
    return value


def closed(value: object, keys: set[str]) -> dict[str, Any]:
    require(type(value) is dict and set(value) == keys)
    return cast(dict[str, Any], value)


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        require(key not in result)
        result[key] = value
    return result


def _invalid_number(_: str) -> object:
    raise ConsumerError()


def read_private(path: Path, maximum: int = 16384) -> dict[str, Any]:
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600)
    require(info.st_uid == os.geteuid() and info.st_nlink == 1 and 0 < info.st_size <= maximum)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        raw = stream.read(maximum + 1)
        opened = os.fstat(stream.fileno())
    require((opened.st_dev, opened.st_ino, opened.st_size) == (info.st_dev, info.st_ino, len(raw)))
    value = json.loads(
        raw.decode("utf-8", "strict"), object_pairs_hook=_pairs, parse_constant=_invalid_number
    )
    require(type(value) is dict)
    return cast(dict[str, Any], value)


def publish(path: Path, value: object) -> None:
    require(path.parent.is_absolute() and path.parent.resolve() == path.parent)
    info = path.parent.lstat()
    require(
        stat.S_ISDIR(info.st_mode)
        and stat.S_IMODE(info.st_mode) == 0o700
        and info.st_uid == os.geteuid()
    )
    raw = (
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        + "\n"
    ).encode()
    require(0 < len(raw) <= 65536)
    pending = path.parent / (".origin-publish-" + uuid4().hex + ".pending")
    descriptor = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    primary: BaseException | None = None
    identity: tuple[int, int] | None = None
    try:
        with os.fdopen(descriptor, "wb") as stream:
            opened = os.fstat(stream.fileno())
            identity = (opened.st_dev, opened.st_ino)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        # Link is exclusive: existing final evidence is never replaced and final
        # visibility starts only after the complete pending bytes are durable.
        os.link(pending, path, follow_symlinks=False)
    except BaseException as error:  # noqa: BLE001 - clean only our exclusive pending before propagating
        primary = error
    finally:
        try:
            owned = pending.lstat()
            require(
                stat.S_ISREG(owned.st_mode)
                and owned.st_uid == os.geteuid()
                and stat.S_IMODE(owned.st_mode) == 0o600
            )
            require(identity is None or identity == (owned.st_dev, owned.st_ino))
            pending.unlink()
        except Exception:  # noqa: BLE001 - preserve primary publication errors without private diagnostics
            if primary is None:
                raise ConsumerError() from None
    if primary is not None:
        raise primary


@dataclass(frozen=True, slots=True)
class ConsumerEnvironment:
    directory: Path
    pg_port: int
    runtime_password: str = field(repr=False)
    work_token: str = field(repr=False)
    case_token: str = field(repr=False)
    publisher_token: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ConsumerConfig:
    scope: Scope
    case_id: str
    conversation_id: str
    recipient_id: str
    profile_id: str
    case_schema: str
    work_schema: str
    task_id: str
    authority_case_id: str
    supplier_path: Path
    receiver_port: int
    original_work_id: str
    ack_work_id: str
    original_owner: str
    current_owner: str
    parent_deadline_monotonic: float

    @property
    def business_deadline_monotonic(self) -> float:
        """Derived admission fence; the final twenty seconds retain cleanup owners."""
        return self.parent_deadline_monotonic - 20

    def progress(self) -> None:
        require(time.monotonic() < self.business_deadline_monotonic)


def configuration(
    directory: Path, environment: Mapping[str, str] | None = None
) -> tuple[ConsumerConfig, ConsumerEnvironment]:
    env = dict(os.environ if environment is None else environment)
    require(
        BASE | ENVIRONMENT <= env.keys() and not env.keys() - BASE - ENVIRONMENT - OPTIONAL_BASE
    )
    require(all(type(v) is str and bool(v) for v in env.values()))
    require(
        directory.is_absolute() and directory.resolve() == directory and not directory.is_symlink()
    )
    require(env["P3_ORIGIN_DIRECTORY"] == str(directory))
    info = directory.lstat()
    require(
        stat.S_ISDIR(info.st_mode)
        and stat.S_IMODE(info.st_mode) == 0o700
        and info.st_uid == os.geteuid()
    )
    for key in ("P3_ORIGIN_WORK_TOKEN", "P3_ORIGIN_CASE_TOKEN", "P3_ORIGIN_PUBLISHER_TOKEN"):
        require(re.fullmatch(r"[A-Za-z0-9_-]{43}", env[key], re.ASCII) is not None)
    password = env["P3_ORIGIN_RUNTIME_PASSWORD"]
    # Match public PostgresSettings; the database password is not a bearer token.
    require(1 <= len(password) <= 128 and not any(character in password for character in "\0\r\n"))
    require(re.fullmatch(r"[1-9][0-9]{0,4}", env["P3_ORIGIN_PG_PORT"], re.ASCII) is not None)
    port = int(env["P3_ORIGIN_PG_PORT"])
    require(1 <= port <= 65535)
    value = closed(
        read_private(directory / "origin-consumer-config.json"),
        {
            "schema_version",
            "scope",
            "case_id",
            "conversation_id",
            "recipient_id",
            "profile_id",
            "case_schema",
            "work_schema",
            "task_id",
            "authority_case_id",
            "supplier_path",
            "receiver_endpoint",
            "original_work_id",
            "ack_work_id",
            "owners",
            "parent_deadline_monotonic",
        },
    )
    require(type(value["schema_version"]) is int and value["schema_version"] == 1)
    scope = closed(value["scope"], {"tenant_id", "account_id"})
    copied_scope = Scope(identifier(scope["tenant_id"]), identifier(scope["account_id"]))
    case_id, conversation_id, recipient_id = (
        identifier(value[key]) for key in ("case_id", "conversation_id", "recipient_id")
    )
    for key, prefix in (("case_schema", "p3_completion_"), ("work_schema", "p1_work_origin_")):
        require(
            type(value[key]) is str
            and re.fullmatch(prefix + r"[0-9a-f]{32}", value[key], re.ASCII) is not None
        )
    endpoint = closed(value["receiver_endpoint"], {"host", "port"})
    require(
        endpoint["host"] == "127.0.0.1"
        and type(endpoint["port"]) is int
        and 1 <= endpoint["port"] <= 65535
    )
    owners = closed(value["owners"], {"original", "current"})
    original_owner, current_owner = uuid_value(owners["original"]), uuid_value(owners["current"])
    require(original_owner != current_owner)
    require(type(value["supplier_path"]) is str)
    supplier = Path(value["supplier_path"])
    require(
        supplier.parent == directory
        and supplier.resolve() == supplier
        and not supplier.is_symlink()
    )
    supplied = supplier.lstat()
    require(
        stat.S_ISREG(supplied.st_mode)
        and stat.S_IMODE(supplied.st_mode) == 0o600
        and supplied.st_uid == os.geteuid()
        and supplied.st_nlink == 1
    )
    deadline = value["parent_deadline_monotonic"]
    require(
        type(deadline) in (int, float)
        and math.isfinite(deadline)
        and 20 < deadline - time.monotonic() <= 180
    )
    original_work, ack_work = (
        uuid_value(value["original_work_id"]),
        uuid_value(value["ack_work_id"]),
    )
    require(original_work != ack_work)
    config = ConsumerConfig(
        copied_scope,
        case_id,
        conversation_id,
        recipient_id,
        uuid_value(value["profile_id"]),
        value["case_schema"],
        value["work_schema"],
        uuid_value(value["task_id"]),
        uuid_value(value["authority_case_id"]),
        supplier,
        endpoint["port"],
        original_work,
        ack_work,
        original_owner,
        current_owner,
        float(deadline),
    )
    require(config.task_id != config.authority_case_id)
    return config, ConsumerEnvironment(
        directory,
        port,
        env["P3_ORIGIN_RUNTIME_PASSWORD"],
        env["P3_ORIGIN_WORK_TOKEN"],
        env["P3_ORIGIN_CASE_TOKEN"],
        env["P3_ORIGIN_PUBLISHER_TOKEN"],
    )


def make_template(
    label: Literal["a", "b"], scope: Scope, case_id: str, conversation_id: str
) -> tuple[FixedPolicyRequest, tuple[EvidenceRecord, ...]]:
    """Build either trusted immutable source pair; only this call reads the fixture.

    Scope binds EvidenceRecord/request. The specialist's closed JSON body shapes
    contain no scope field and are deliberately kept compatible with policy v2.
    """
    require(type(label) is str and label in _LABELS and type(scope) is Scope)
    copied = Scope(identifier(scope.tenant_id), identifier(scope.account_id))
    case_id, conversation_id = identifier(case_id), identifier(conversation_id)
    source = json.loads((ROOT / "contracts/delegation/fixed-policy-v2.json").read_bytes())
    policy, facts = json.loads(source["policy_body_utf8"]), json.loads(source["facts_body_utf8"])
    facts["observations"][0]["days_before_arrival"] = 10 if label == "a" else 14
    bodies = (canonical(policy), canonical(facts))
    records = tuple(
        EvidenceRecord(
            copied,
            EvidenceRef(
                source_id,
                "distinct_" + label,
                hashlib.sha256(body).hexdigest(),
                "application/json",
                len(body),
                None,
                None,
            ),
            body,
        )
        for source_id, body in zip(("policy_notice", "facts_notice"), bodies, strict=True)
    )
    raw = source["producer_input"]
    raw.update(
        scope={"tenant_id": copied.tenant_id, "account_id": copied.account_id},
        delegation_id="origin_template_" + label,
        case_id=case_id,
        request_revision=1,
        evidence=[asdict(record.reference) for record in records],
        deadline_at_ms=time.time_ns() // 1000000 + 60000,
        result_route={"conversation_id": conversation_id},
        attempt={"attempt_id": "origin_proposal", "number": 1},
    )
    template = produce_fixed_policy_request(raw)
    return template, snapshot_fixed_policy_records(records)


@dataclass(frozen=True, slots=True)
class CatalogueEntry:
    label: Literal["a", "b"]
    template: FixedPolicyRequest
    evidence: tuple[EvidenceRecord, ...]


def select_evidence(
    request: ChannelPolicyRequest, catalogue: tuple[CatalogueEntry, ...]
) -> CatalogueEntry:
    request = parse_channel_policy_request(encode_channel_policy_request(request))
    require(
        type(catalogue) is tuple
        and len(catalogue) == 2
        and {entry.label for entry in catalogue} == {"a", "b"}
    )
    matches = [
        entry
        for entry in catalogue
        if entry.template.scope == request.scope
        and entry.template.case_id == request.case_id
        and entry.template.conversation_id == request.conversation_id
        and entry.template.context_snapshot == request.request.context_snapshot
        and entry.template.evidence == request.request.evidence
    ]
    require(len(matches) == 1)
    return matches[0]


class ScriptedPolicy:
    """Literal seven-day policy port; the P3 runner independently verifies its facts."""

    def __init__(self, entry: CatalogueEntry) -> None:
        self.evidence = snapshot_fixed_policy_records(entry.evidence)
        self.invocations, self.closed = 0, False

    async def invoke_observed(
        self, request: FixedPolicyRequest, *, evidence: tuple[EvidenceRecord, ...]
    ) -> FixedPolicyResultObservation:
        require(not self.closed and evidence == self.evidence)
        policy, facts = self.evidence
        observations = json.loads(facts.body)["observations"]
        days = observations[0]["days_before_arrival"]
        require(
            type(days) is int
            and days in {10, 14}
            and request.evidence == tuple(record.reference for record in self.evidence)
        )
        self.invocations += 1
        now = time.time_ns() // 1000000
        result = parse_fixed_policy_result(
            canonical(
                {
                    "schema_version": 1,
                    "kind": "delegation.result",
                    "capability": "booking.evaluate_policy",
                    "result_schema_version": 2,
                    "scope": {
                        "tenant_id": request.scope.tenant_id,
                        "account_id": request.scope.account_id,
                    },
                    "delegation_id": request.delegation_id,
                    "case_id": request.case_id,
                    "request_revision": request.request_revision,
                    "attempt_id": request.attempt.attempt_id,
                    "input_fingerprint": request.input_fingerprint,
                    "eligible": True,
                    "uncertainty": "none",
                    "rule_refs": [
                        {
                            "source_id": policy.reference.source_id,
                            "version": policy.reference.version,
                            "sha256": policy.reference.sha256,
                            "rule_id": "notice_minimum_days",
                            "minimum_notice_days": 7,
                        }
                    ],
                    "fact_refs": [
                        {
                            "source_id": facts.reference.source_id,
                            "version": facts.reference.version,
                            "sha256": facts.reference.sha256,
                            "fact_id": "notice_primary",
                            "days_before_arrival": days,
                        }
                    ],
                    "producer": {
                        "producer_id": "deterministic_notice_v1",
                        "model_id": None,
                        "model_version": None,
                        "config_fingerprint": hashlib.sha256(
                            b"origin_supplied_scripted_v1"
                        ).hexdigest(),
                    },
                    "completed_at_ms": now,
                }
            )
        )
        disposition = verify_fixed_policy_facts(request, result, self.evidence, observed_at_ms=now)
        return FixedPolicyResultObservation(result, disposition, now)

    async def close(self) -> None:
        self.closed = True


class Closeable(Protocol):
    async def close(self) -> None: ...


OwnerT = TypeVar("OwnerT", bound=Closeable)


class OwnedResources:
    """Retain actual startup/close tasks and close application case clients last."""

    def __init__(self) -> None:
        self.tiers: list[list[Closeable]] = [[], [], []]
        self.startups: set[asyncio.Task[object]] = set()
        self.observers: dict[int, asyncio.Task[None]] = {}
        self.cleanup_complete = False

    def add(self, owner: OwnerT, tier: int) -> OwnerT:
        self.tiers[tier].append(owner)
        return owner

    async def startup(self, factory: Callable[[], OwnerT], tier: int) -> OwnerT:
        async def actual() -> OwnerT:
            owner = await asyncio.to_thread(factory)
            return self.add(owner, tier)

        operation = actual()
        try:
            task = asyncio.create_task(operation, name="origin-consumer-public-startup")
        except BaseException:
            operation.close()
            raise
        self.startups.add(cast(asyncio.Task[object], task))
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        return await asyncio.shield(task)

    def transfer(self, owner: OwnerT, children: tuple[Closeable, ...], tier: int) -> OwnerT:
        require(all(any(child is retained for retained in self.tiers[tier]) for child in children))
        self.tiers[tier].append(owner)
        self.tiers[tier][:] = [
            retained
            for retained in self.tiers[tier]
            if all(retained is not child for child in children)
        ]
        return owner

    async def close(self, deadline: float) -> bool:
        self.cleanup_complete = False
        if not math.isfinite(deadline) or time.monotonic() >= deadline:
            return False
        try:
            async with asyncio.timeout_at(deadline):
                if self.startups:
                    await asyncio.gather(
                        *(asyncio.shield(task) for task in self.startups), return_exceptions=True
                    )
                for tier in self.tiers:
                    owners = tuple(tier)
                    pending: list[tuple[Closeable, asyncio.Task[None]]] = []
                    complete = True
                    for owner in owners:
                        task = self.observers.get(id(owner))
                        if task is None or (
                            task.done() and (task.cancelled() or task.exception() is not None)
                        ):
                            operation = owner.close()
                            try:
                                task = asyncio.create_task(
                                    operation, name="origin-consumer-owned-close"
                                )
                            except BaseException as error:
                                operation.close()
                                if not isinstance(error, Exception):
                                    raise
                                complete = False
                                continue
                            self.observers[id(owner)] = task
                            task.add_done_callback(
                                lambda done: None if done.cancelled() else done.exception()
                            )
                        pending.append((owner, task))
                    outcomes = await asyncio.gather(
                        *(asyncio.shield(task) for _owner, task in pending), return_exceptions=True
                    )
                    for (owner, _task), outcome in zip(pending, outcomes, strict=True):
                        if isinstance(outcome, BaseException):
                            complete = False
                        else:
                            tier[:] = [retained for retained in tier if retained is not owner]
                    if not complete:
                        return False
        except TimeoutError:
            return False
        self.cleanup_complete = (
            time.monotonic() < deadline
            and not any(self.tiers)
            and all(task.done() for task in self.startups)
        )
        return self.cleanup_complete

    def observation(self) -> dict[str, object]:
        return {
            "startup_tasks": len(self.startups),
            "startup_pending": sum(not task.done() for task in self.startups),
            "retained_tiers": [len(tier) for tier in self.tiers],
            "close_observers_pending": sum(not task.done() for task in self.observers.values()),
            "cleanup_complete": self.cleanup_complete,
        }


def receiver_factory() -> Callable[..., ResultReceiverPort]:
    """Load only the maintained adjacent inert adapter when the actual CLI composes it."""
    name = "origin_consumer_receiver_helper"
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(
            name, Path(__file__).with_name("p3_channel_receiver.py")
        )
        require(spec is not None and spec.loader is not None)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return cast(Callable[..., ResultReceiverPort], module.ChannelResultReceiver)


class SimulatedWork:
    """Injected public-port uncertainty only; this object never connects to PostgreSQL."""

    def __init__(self, scope: Scope, unavailable: bool) -> None:
        self.scope = WorkScope(scope.tenant_id, scope.account_id)
        self.unavailable, self.pending_count, self.closed = unavailable, 0, False
        self.calls: list[tuple[str, str]] = []

    async def find(self, *, idempotency_key: str) -> WorkRecord | None:
        self.calls.append(("find", idempotency_key))
        if len(self.calls) == 3 and self.unavailable:
            raise WorkError("storage_unavailable")
        return None

    async def submit(self, *, idempotency_key: str, payload: WorkPayload) -> WorkSubmission:
        self.calls.append(("submit", idempotency_key))
        raise WorkError("acknowledgement_unknown")

    async def get(self, *, work_id: str) -> WorkRecord:
        raise WorkError("not_found")

    async def cancel(self, *, work_id: str, command_id: str) -> WorkCancellation:
        raise WorkError("not_found")

    async def close(self) -> None:
        self.closed = True


class SimulatedCases:
    def __init__(self, request: ChannelPolicyRequest) -> None:
        self.request = request

    async def snapshot(self, *, case_id: str) -> CaseSnapshot:
        require(case_id == self.request.case_id)
        return CaseSnapshot(self.request.scope, case_id, self.request.request_revision, False)


async def simulate_uncertainty(request: ChannelPolicyRequest) -> list[dict[str, object]]:
    source = request.to_wire()
    source.pop("input_fingerprint")
    inner = request.request.to_wire()
    inner.pop("input_fingerprint")
    inner["deadline_at_ms"] = time.time_ns() // 1000000 + 60000
    source["request"] = produce_fixed_policy_request(inner).to_wire()
    candidate = produce_channel_policy_request(source)
    proofs: list[dict[str, object]] = []
    for unavailable in (False, True):
        port = SimulatedWork(candidate.scope, unavailable)
        coordinator = ChannelPolicyCoordinator(
            executions=port, scope=candidate.scope, case_authority=SimulatedCases(candidate)
        )
        try:
            try:
                await coordinator.accept(candidate)
            except CoordinatorError as error:
                require(type(error) is CoordinatorError and error.code == "acknowledgement_unknown")
            else:
                raise ConsumerError()
            require(
                port.calls
                == [
                    ("find", candidate.delegation_id),
                    ("submit", candidate.delegation_id),
                    ("find", candidate.delegation_id),
                ]
            )
        finally:
            await coordinator.close()
        require(port.closed)
        proofs.append(
            {
                "kind": "simulated_public_task_port",
                "reconciliation": "unavailable" if unavailable else "missing",
                "error": "acknowledgement_unknown",
                "finds": 2,
                "submits": 1,
                "keys": [key for _operation, key in port.calls],
                "actual_database_fault": False,
                "closed": True,
            }
        )
    return proofs


def validate_view(
    view: ChannelPolicyView, config: ConsumerConfig, revision: int
) -> ChannelPolicyRequest:
    request = parse_channel_policy_request(encode_channel_policy_request(view.request))
    require(
        request.scope == config.scope
        and request.case_id == config.case_id
        and request.conversation_id == config.conversation_id
    )
    require(request.origin.profile_id == config.profile_id and request.request_revision == revision)
    require(
        view.record.scope == WorkScope(config.scope.tenant_id, config.scope.account_id)
        and view.record.idempotency_key == request.delegation_id
        and view.record.payload.operation == "booking.evaluate_policy"
        and view.record.payload.deadline_at_ms == request.deadline_at_ms
        and view.record.payload.body == encode_channel_policy_request(request)
        and view.record.payload.sha256 == hashlib.sha256(view.record.payload.body).hexdigest()
    )
    uuid_value(view.record.work_id)
    return request


def parse_current_marker(value: object, config: ConsumerConfig) -> dict[str, Any]:
    marker = closed(value, {"schema_version", "receipt", "input_receipt_id"})
    require(type(marker["schema_version"]) is int and marker["schema_version"] == 1)
    receipt = closed(marker["receipt"], {"operationKey", "scope", "payloadDigest", "receiptId"})
    scope = closed(receipt["scope"], {"tenantId", "accountId"})
    require(scope == {"tenantId": config.scope.tenant_id, "accountId": config.scope.account_id})
    uuid_value(receipt["receiptId"])
    uuid_value(receipt["operationKey"])
    uuid_value(marker["input_receipt_id"])
    require(
        type(receipt["payloadDigest"]) is str
        and _SHA.fullmatch(receipt["payloadDigest"]) is not None
    )
    return marker


def validate_current_marker(value: object, view: ChannelPolicyView, config: ConsumerConfig) -> None:
    marker = parse_current_marker(value, config)
    receipt = marker["receipt"]
    scope = receipt["scope"]
    request = validate_view(view, config, 2)
    require(scope == {"tenantId": config.scope.tenant_id, "accountId": config.scope.account_id})
    require(uuid_value(receipt["receiptId"]) == view.record.work_id)
    require(uuid_value(receipt["operationKey"]) == request.origin.operation_key)
    require(
        type(receipt["payloadDigest"]) is str
        and _SHA.fullmatch(receipt["payloadDigest"]) is not None
        and receipt["payloadDigest"] == request.origin.payload_sha256
    )
    require(uuid_value(marker["input_receipt_id"]) == request.origin.input_receipt_id)


async def wait_marker(directory: Path, config: ConsumerConfig) -> dict[str, Any]:
    path = directory / "origin-current-accepted.json"
    while True:
        config.progress()
        try:
            info = path.lstat()
            require(
                stat.S_ISREG(info.st_mode)
                and stat.S_IMODE(info.st_mode) == 0o600
                and info.st_uid == os.geteuid()
                and path.resolve() == path
                and 0 < info.st_size <= 16384
            )
            if info.st_nlink == 2:
                # An exclusive atomic publisher briefly links complete pending
                # bytes before unlinking its own pending name. Never read NL2.
                await asyncio.sleep(0.02)
                continue
            return parse_current_marker(read_private(path), config)
        except FileNotFoundError:
            await asyncio.sleep(0.02)


def work_proof(view: ChannelPolicyView) -> dict[str, object]:
    raw = encode_channel_policy_request(view.request)
    return {
        "work_id": view.record.work_id,
        "request_canonical": raw.decode(),
        "request_sha256": hashlib.sha256(raw).hexdigest(),
        "input_fingerprint": view.request.input_fingerprint,
        "inner_input_fingerprint": view.request.request.input_fingerprint,
        "deadline_at_ms": view.request.deadline_at_ms,
        "origin": view.request.origin.to_wire(),
    }


def execution_proof(run: ChannelPolicyRun) -> dict[str, object]:
    executed, recorded = run.view.execution, run.recorded
    require(
        run.invoked
        and recorded is not None
        and run.view.result is not None
        and executed.current_attempt is not None
    )
    assert (
        recorded is not None
        and run.view.result is not None
        and executed.current_attempt is not None
    )
    raw = encode_channel_policy_result(run.view.result)
    require(
        raw == recorded.body
        and recorded.sha256 == hashlib.sha256(raw).hexdigest()
        and recorded.disposition == "eligible_at_commit"
        and run.view.applicability == "candidate"
    )
    issued = executed.current_attempt
    return {
        "work_id": executed.record.work_id,
        "result_canonical": raw.decode(),
        "result_sha256": recorded.sha256,
        "recorded_at_ms": recorded.recorded_at_ms,
        "disposition": recorded.disposition,
        "applicability": run.view.applicability,
        "issued": {
            "attempt_id": issued.attempt_id,
            "command_id": issued.command_id,
            "number": issued.number,
            "owner_id": issued.owner_id,
            "epoch": issued.epoch,
            "issued_at_ms": issued.issued_at_ms,
            "lease_until_ms": issued.lease_until_ms,
        },
    }


async def exercise(config: ConsumerConfig, environment: ConsumerEnvironment) -> dict[str, object]:
    resources = OwnedResources()
    proof: dict[str, Any] = {}
    specialists: list[ScriptedPolicy] = []
    primary: BaseException | None = None
    cleanup_control_flow: BaseException | None = None
    stage = "ports"
    cleanup_complete = False
    try:
        async with asyncio.timeout_at(config.business_deadline_monotonic):
            config.progress()
            catalogue = tuple(
                CatalogueEntry(
                    label,
                    *make_template(label, config.scope, config.case_id, config.conversation_id),
                )
                for label in ("a", "b")
            )
            work_scope = WorkScope(config.scope.tenant_id, config.scope.account_id)
            work_token, case_token = (
                BearerToken(environment.work_token),
                BearerToken(environment.case_token),
            )
            registrations = WorkDirectory(
                {work_token: WorkPrincipal("origin_fixture_actor", work_scope)}
            )
            case_settings = PostgresSettings(
                host="127.0.0.1",
                port=environment.pg_port,
                password=environment.runtime_password,
                schema=config.case_schema,
            )
            work_settings = PostgresSettings(
                host="127.0.0.1",
                port=environment.pg_port,
                password=environment.runtime_password,
                schema=config.work_schema,
            )
            actor = AuthenticatedActor("p3_completion_user", "p3_completion_scope")
            config.progress()
            reader = await resources.startup(
                lambda: open_postgres_client(
                    actor=actor,
                    token=case_token,
                    settings=case_settings,
                    quote_database=config.supplier_path,
                ),
                2,
            )
            config.progress()
            controller = await resources.startup(
                lambda: open_case_control_client(
                    actor=actor,
                    token=case_token,
                    settings=case_settings,
                    quote_database=config.supplier_path,
                ),
                2,
            )
            authority = ManagedCaseAuthority(
                reader,
                scope=config.scope,
                bindings=(CaseBinding(config.case_id, config.task_id, config.authority_case_id),),
            )

            async def new_coordinator() -> ChannelPolicyCoordinator:
                config.progress()
                port = await resources.startup(
                    lambda: open_work_client(
                        settings=work_settings, directory=registrations, token=work_token
                    ),
                    1,
                )
                return resources.transfer(
                    ChannelPolicyCoordinator(
                        executions=port, scope=config.scope, case_authority=authority
                    ),
                    (port,),
                    1,
                )

            async def new_runner(entry: CatalogueEntry, owner_id: str) -> ChannelPolicyRunner:
                config.progress()
                port = await resources.startup(
                    lambda: open_execution_client(
                        settings=work_settings, directory=registrations, token=work_token
                    ),
                    1,
                )
                specialist = resources.add(ScriptedPolicy(entry), 1)
                specialists.append(specialist)
                return resources.transfer(
                    ChannelPolicyRunner(
                        executions=port,
                        scope=config.scope,
                        owner_id=owner_id,
                        specialist=specialist,
                        case_authority=authority,
                        evidence=entry.evidence,
                    ),
                    (port, specialist),
                    1,
                )

            async def new_delivery(
                runner: ChannelPolicyRunner, entry: CatalogueEntry
            ) -> ChannelPolicyDeliveryClient:
                config.progress()
                port = await resources.startup(
                    lambda: open_delivery_client(
                        settings=work_settings, directory=registrations, token=work_token
                    ),
                    0,
                )
                receiver = resources.add(
                    receiver_factory()(
                        port=config.receiver_port,
                        publisher_token=environment.publisher_token,
                        receiver_id=config.profile_id,
                        scope=work_scope,
                        recipient_id=config.recipient_id,
                    ),
                    0,
                )
                return resources.transfer(
                    ChannelPolicyDeliveryClient(
                        results=runner,
                        deliveries=port,
                        receiver=receiver,
                        scope=config.scope,
                        evidence=entry.evidence,
                        bindings=(
                            DeliveryBinding(
                                config.case_id, config.conversation_id, config.recipient_id
                            ),
                        ),
                    ),
                    (port, receiver),
                    0,
                )

            config.progress()
            current_case = await controller.case(task_id=config.task_id)
            require(
                current_case.revision == 1
                and current_case.task_id == config.task_id
                and current_case.case_id == config.authority_case_id
                and not current_case.cancelled
            )
            coordinator = await new_coordinator()
            stage = "original_read"
            config.progress()
            original = await coordinator.get(config.original_work_id)
            original_request = validate_view(original, config, 1)
            original_entry = select_evidence(original_request, catalogue)
            proof["original"] = {**work_proof(original), "catalogue_label": original_entry.label}
            stage = "ack_read_only"
            config.progress()
            ack = await coordinator.get(config.ack_work_id)
            validate_view(ack, config, 1)
            proof["ack"] = {**work_proof(ack), "execution_requested": False, "read_only": True}
            stage = "original_run"
            original_runner = await new_runner(original_entry, config.original_owner)
            config.progress()
            original_run = await original_runner.run_once(
                config.original_work_id, "origin_original_" + UUID(config.original_owner).hex
            )
            proof["original"]["execution"] = execution_proof(original_run)
            original_delivery = await new_delivery(original_runner, original_entry)

            stage = "real_read_only_controls"
            controls = await new_coordinator()
            changed = original_request.to_wire()
            changed.pop("input_fingerprint")
            changed["origin"] = {**original_request.origin.to_wire(), "profile_id": str(uuid4())}
            try:
                config.progress()
                await controls.accept(produce_channel_policy_request(changed))
            except CoordinatorError as error:
                require(type(error) is CoordinatorError and error.code == "identity_conflict")
            else:
                raise ConsumerError()
            alternative = next(entry for entry in catalogue if entry.label != original_entry.label)
            changed = original_request.to_wire()
            changed.pop("input_fingerprint")
            nested = original_request.request.to_wire()
            nested.pop("input_fingerprint")
            nested["evidence"] = [asdict(record.reference) for record in alternative.evidence]
            changed["request"] = produce_fixed_policy_request(nested).to_wire()
            try:
                config.progress()
                await controls.submit(produce_channel_policy_request(changed))
            except CoordinatorError as error:
                require(type(error) is CoordinatorError and error.code == "identity_conflict")
            else:
                raise ConsumerError()
            proof["real_read_only_controls"] = {
                "changed_profile_accept": "identity_conflict",
                "changed_context_exact_submit": "identity_conflict",
                "key": original_request.delegation_id,
                "separate_work_client": True,
                "specialist_invoked": False,
            }
            stage = "simulated_uncertainty"
            config.progress()
            proof["simulations"] = await simulate_uncertainty(original_request)
            stage = "case_revision"
            config.progress()
            revised = await controller.revise(
                task_id=config.task_id,
                expected_revision=1,
                request=BookingChange("DEMO-BK-001", date(2030, 12, 12), True),
            )
            require(
                revised.revision == 2
                and revised.task_id == config.task_id
                and revised.case_id == config.authority_case_id
                and revised.intent is None
            )
            config.progress()
            publish(
                environment.directory / "origin-case-advanced.json",
                {"schema_version": 1, "revision": 2},
            )
            proof["case_revision"] = 2
            stage = "stale_new_delivery"
            try:
                config.progress()
                await original_delivery.deliver_once(config.original_work_id)
            except CompletionError as error:
                require(type(error) is CompletionError and error.code == "not_eligible")
            else:
                raise ConsumerError()
            config.progress()
            denied = await original_delivery.inspect(config.original_work_id)
            require(
                denied.state == "missing"
                and denied.snapshot.intent is None
                and denied.snapshot.receipt is None
            )
            config.progress()
            historical = await original_runner.inspect(config.original_work_id)
            require(
                historical.execution.result is not None
                and original_run.recorded is not None
                and historical.execution.result.body == original_run.recorded.body
                and historical.result == original_run.view.result
            )
            proof["original"]["stale_delivery"] = {
                "error": "not_eligible",
                "intent": None,
                "historical_result_sha256": historical.execution.result.sha256
                if historical.execution.result is not None
                else None,
                "historical_applicability": historical.applicability,
            }
            stage = "current_wait"
            marker = await wait_marker(environment.directory, config)
            receipt = closed(
                marker.get("receipt"), {"operationKey", "scope", "payloadDigest", "receiptId"}
            )
            current_work_id = uuid_value(receipt["receiptId"])
            require(current_work_id not in {config.original_work_id, config.ack_work_id})
            stage = "current_read"
            config.progress()
            current = await coordinator.get(current_work_id)
            validate_current_marker(marker, current, config)
            entry = select_evidence(current.request, catalogue)
            proof["current"] = {
                **work_proof(current),
                "catalogue_label": entry.label,
                "input_receipt_id": current.request.origin.input_receipt_id,
            }
            stage = "current_run"
            current_runner = await new_runner(entry, config.current_owner)
            config.progress()
            current_run = await current_runner.run_once(
                current_work_id, "origin_current_" + UUID(config.current_owner).hex
            )
            proof["current"]["execution"] = execution_proof(current_run)
            stage = "current_delivery"
            current_delivery = await new_delivery(current_runner, entry)
            config.progress()
            delivered = await current_delivery.deliver_once(current_work_id)
            require(
                delivered.state == "accepted"
                and delivered.receiver_invoked
                and delivered.snapshot.intent is not None
                and delivered.snapshot.receipt is not None
            )
            assert delivered.snapshot.intent is not None and delivered.snapshot.receipt is not None
            require(
                delivered.snapshot.receipt.result_sha256
                == proof["current"]["execution"]["result_sha256"]
            )
            receipt_wire = asdict(delivered.snapshot.receipt)
            config.progress()
            publish(
                environment.directory / "origin-current-delivered.json",
                {
                    "schema_version": 1,
                    "work_id": current_work_id,
                    "delivery_id": delivered.snapshot.intent.delivery_id,
                    "receipt": receipt_wire,
                },
            )
            proof["current"]["delivery"] = {
                "state": "accepted",
                "receiver_invoked": True,
                "intent": json.loads(delivered.snapshot.intent.canonical()),
                "receipt": receipt_wire,
                "human_acknowledgement": False,
            }
            require(sum(specialist.invocations for specialist in specialists) == 2)
    except BaseException as error:  # noqa: BLE001 - retain the primary while closing every actual owner
        primary = error
    finally:
        cleanup_operation = resources.close(config.parent_deadline_monotonic)
        try:
            cleanup_task = asyncio.create_task(
                cleanup_operation, name="origin-consumer-final-close"
            )
        except BaseException as error:  # noqa: BLE001 - retain owners and emit failed proof on setup failure
            cleanup_operation.close()
            cleanup_complete = False
            if not isinstance(error, Exception):
                cleanup_control_flow = error
            if primary is None:
                primary = error
        else:
            cleanup_task.add_done_callback(
                lambda done: None if done.cancelled() else done.exception()
            )
            try:
                cleanup_complete = await asyncio.shield(cleanup_task)
            except BaseException as error:  # noqa: BLE001 - cleanup never replaces primary diagnostics
                cleanup_complete = False
                if not isinstance(error, Exception):
                    cleanup_control_flow = error
                if primary is None:
                    primary = error
    value: dict[str, object] = {
        "schema_version": 1,
        "status": "passed" if primary is None and cleanup_complete else "failed",
        "code": "ok" if primary is None and cleanup_complete else "origin_consumer_failed",
        "stage": "complete" if primary is None else stage,
        "cleanup_complete": cleanup_complete,
        "specialist": "supplied_scripted_fixed_policy_v2",
        "actual_invoke_count": sum(s.invocations for s in specialists),
        "source_actual_assertions": 0,
        "provider_calls": False,
        "carrier_sends": 0,
        "supplier_mutations": 0,
        "proof": proof,
        "ownership": resources.observation(),
    }
    publish(environment.directory / "origin-p3-consumer.json", value)
    if cleanup_control_flow is not None:
        raise cleanup_control_flow
    if primary is not None and not isinstance(primary, Exception):
        raise primary
    return value


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        require(not args)
        config, environment = configuration(Path(os.environ.get("P3_ORIGIN_DIRECTORY", "")))
        value = asyncio.run(exercise(config, environment))
        summary = {
            key: value[key] for key in ("schema_version", "status", "code", "cleanup_complete")
        }
        print(json.dumps(summary, separators=(",", ":")))
        return 0 if value["status"] == "passed" else 1
    except Exception:  # noqa: BLE001 - fixed boundary; never inspect dependency code/getters/args
        print('{"schema_version":1,"status":"failed","code":"origin_consumer_failed"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
