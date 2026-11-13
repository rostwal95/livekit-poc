"""Read-only current disclosure joins; no result, delivery or grant is created.

The newest recorded result is a barrier: stale/expired or undelivered results
never fall back to an older card. Newer inputs without a result may coexist with
an older current delivery. Observations are non-atomic, not ongoing permission.
Borrowed source/native readers and the job factory outlive this owner's drain.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import math
import re
import time
from collections.abc import Coroutine
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from inspect import getattr_static
from types import FunctionType, MappingProxyType, MethodType
from typing import Literal, Protocol, TypeVar, cast
from uuid import UUID

from continuity_lab.delivery_api import DeliveryIntent, DeliveryReceipt, DeliverySnapshot
from continuity_lab.execution_api import AttemptResult, ExecutionObservation, IssuedAttempt
from continuity_lab.work_api import WorkPayload, WorkRecord, WorkScope
from delegation_reliability import (
    ChannelPolicyExecutionView,
    ChannelPolicyRequest,
    ChannelPolicyResult,
    ChannelPolicyView,
    channel_policy_key,
    encode_channel_policy_request,
    encode_channel_policy_result,
    match_channel_policy_result,
    parse_channel_policy_request,
    parse_channel_policy_result,
)
from delegation_reliability.contracts import Attempt, Scope, identifier
from delegation_reliability.delivery_contract import DelegationDelivery
from delegation_reliability.fixed_policy import verify_fixed_policy_facts
from delegation_reliability.runner import Applicability

from .current_result import (
    CURRENT_RESULT_BYTES,
    CurrentResultObservation,
    CurrentResultProjection,
    encode_current_result_observation,
    parse_current_result_observation,
)
from .discovery import (
    DiscoveryItem,
    DiscoveryPage,
    DiscoveryScope,
    encode_discovery_page,
    parse_discovery_page,
)
from .executor import DiscoveryPort, PreparedReadPort, StoredWorkPort
from .jobs import EvidenceCatalogue
from .wire import (
    PreparedChannelInput,
    decode_object,
    parse_accept_frame,
    require_p3_compatible,
    uuid_value,
)

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
ProducerCode = Literal[
    "invalid_input",
    "unauthorized",
    "identity_conflict",
    "invalid_stored_state",
    "unavailable",
    "overflow",
    "capacity",
    "closed",
    "deadline_exceeded",
    "request_aborted",
    "cleanup_incomplete",
]
_CODES = frozenset(
    {
        "invalid_input",
        "unauthorized",
        "identity_conflict",
        "invalid_stored_state",
        "unavailable",
        "overflow",
        "capacity",
        "closed",
        "deadline_exceeded",
        "request_aborted",
        "cleanup_incomplete",
    }
)
T = TypeVar("T")


class CurrentResultProducerError(RuntimeError):
    def __init__(self, code: ProducerCode = "unavailable") -> None:
        self.code: ProducerCode = code if type(code) is str and code in _CODES else "unavailable"
        super().__init__(self.code)


def _need(value: bool, code: ProducerCode = "invalid_stored_state") -> None:
    if not value:
        raise CurrentResultProducerError(code)


def _failure(error: Exception) -> CurrentResultProducerError:
    try:
        code: object = getattr_static(error, "code", None)
    except Exception:  # noqa: BLE001 - finite public boundary
        code = None
    # Snapshot data only; never call a dependency's getter or retain its args.
    if type(code) is str and code in _CODES:
        return CurrentResultProducerError(cast(ProducerCode, code))
    return CurrentResultProducerError()


def _budget(value: float) -> float:
    _need(
        type(value) in (int, float) and 0.001 <= value <= 5 and math.isfinite(value),
        "invalid_input",
    )
    return float(value)


def _spawn(action: Coroutine[object, object, T]) -> asyncio.Task[T]:
    try:
        task = asyncio.create_task(action)
    except BaseException:
        action.close()
        raise
    task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    return task


def _method(value: object, name: str) -> object:
    """Copy a genuine async function without calling owner/descriptor getters."""
    try:
        raw: object = getattr_static(value, name, None)
        if type(raw) is MethodType:
            function = raw.__func__
            if type(function) is FunctionType and function.__code__.co_flags & inspect.CO_COROUTINE:
                return raw
        elif type(raw) is FunctionType and raw.__code__.co_flags & inspect.CO_COROUTINE:
            return MethodType(raw, value) if getattr_static(type(value), name, None) is raw else raw
        elif isinstance(raw, (staticmethod, classmethod)) and type(raw) in (
            staticmethod,
            classmethod,
        ):
            function = raw.__func__
            if type(function) is FunctionType and function.__code__.co_flags & inspect.CO_COROUTINE:
                return function if type(raw) is staticmethod else MethodType(function, type(value))
    except Exception:  # noqa: BLE001 - finite public boundary  # noqa: BLE001 - reject descriptor failures without diagnostics
        raise CurrentResultProducerError("invalid_input") from None
    raise CurrentResultProducerError("invalid_input")


@dataclass(frozen=True, slots=True)
class ProducerBinding:
    profile_id: str
    scope: Scope
    case_id: str
    conversation_id: str
    owner_id: str
    receiver_id: str
    recipient_id: str

    def __post_init__(self) -> None:
        try:
            for value in (self.profile_id, self.owner_id, self.receiver_id):
                uuid_value(value)
            _need(type(self.scope) is Scope, "invalid_input")
            object.__setattr__(
                self,
                "scope",
                Scope(identifier(self.scope.tenant_id), identifier(self.scope.account_id)),
            )
            for value in (self.case_id, self.conversation_id, self.recipient_id):
                identifier(value)
        except Exception:  # noqa: BLE001 - finite public boundary
            raise CurrentResultProducerError("invalid_input") from None


class InspectionPort(Protocol):
    @property
    def pending_count(self) -> int: ...
    async def inspect_result(self) -> ChannelPolicyExecutionView: ...
    async def inspect_delivery(self) -> DelegationDelivery: ...
    async def close(self) -> None: ...


class InspectionFactoryPort(Protocol):
    """Same job tickets as execution; failed opens retain/close partial owners."""

    async def open_inspection(
        self, *, work_id: str, owner_id: str, request: ChannelPolicyRequest
    ) -> InspectionPort: ...


class NativeResultReadPort(Protocol):
    """One immutable current room. Null is absence; failures must raise.

    The configured transport authenticates its fixed room capability and epoch /
    generation; caller input cannot choose scope, native bearer or a new room.
    Deeper borrowed P2 SQL may remain app-owned after this call settles (mode G).
    """

    async def read(self, *, delivery_id: str) -> bytes | None: ...


class _DiscoveryRead(Protocol):
    async def __call__(self) -> DiscoveryPage: ...


class _PreparedRead(Protocol):
    async def __call__(
        self, *, source_binding_id: Literal["native", "sms"], receipt_id: str
    ) -> bytes | None: ...


class _StoredRead(Protocol):
    async def __call__(self, work_id: str) -> ChannelPolicyView: ...


class _Open(Protocol):
    async def __call__(
        self, *, work_id: str, owner_id: str, request: ChannelPolicyRequest
    ) -> InspectionPort: ...


class _InspectResult(Protocol):
    async def __call__(self) -> ChannelPolicyExecutionView: ...


class _InspectDelivery(Protocol):
    async def __call__(self) -> DelegationDelivery: ...


class _Close(Protocol):
    async def __call__(self) -> None: ...


def _fields(value: object, names: set[str]) -> dict[str, object]:
    _need(type(value) is dict and set(value) == names)
    return cast(dict[str, object], value)


def _revision(value: object) -> str:
    _need(type(value) is str and re.fullmatch(r"0|[1-9][0-9]{0,18}", value, re.ASCII) is not None)
    result = cast(str, value)
    _need(int(result) <= 9223372036854775807)
    return result


def _enum(value: object, allowed: set[str]) -> str:
    _need(type(value) is str and value in allowed)
    return cast(str, value)


def _date(value: object) -> None:
    _need(type(value) is str and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is not None)
    _need(date.fromisoformat(cast(str, value)).isoformat() == value)


def _booking(value: object) -> None:
    _need(type(value) is str)
    text = cast(str, value)
    _need(0 < len(text.encode("utf-8", "strict")) <= 64 and text.strip().upper() == text)
    _need(not any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in text))


def _case(value: object, binding: ProducerBinding) -> tuple[str, bool]:
    """Validate the complete public P2 CurrentCase shape before discarding fields."""
    c = _fields(
        value,
        {
            "schemaVersion",
            "source",
            "scope",
            "caseId",
            "conversationId",
            "revision",
            "request",
            "workflow",
            "intent",
            "mutation",
            "supplierResult",
            "sourceRevision",
        },
    )
    _need(
        type(c["schemaVersion"]) is int
        and c["schemaVersion"] == 1
        and c["source"] == "p1_public_v4"
    )
    scope = _fields(c["scope"], {"tenantId", "accountId"})
    _need(
        scope == {"tenantId": binding.scope.tenant_id, "accountId": binding.scope.account_id}
        and (c["caseId"], c["conversationId"]) == (binding.case_id, binding.conversation_id),
        "identity_conflict",
    )
    revision = _revision(c["revision"])
    _need(
        type(c["sourceRevision"]) is str
        and re.fullmatch(r"[0-9a-f]{64}", c["sourceRevision"]) is not None
    )
    request = _fields(
        c["request"],
        {"schemaVersion", "kind", "bookingReference", "newCheckIn", "investigationConsent"},
    )
    _need(
        type(request["schemaVersion"]) is int
        and request["schemaVersion"] == 1
        and request["kind"] == "booking_investigation"
        and request["investigationConsent"] is True
    )
    _booking(request["bookingReference"])
    _date(request["newCheckIn"])
    workflow = c["workflow"]
    cancelled = False
    if workflow is not None:
        w = _fields(workflow, {"taskId", "state", "version"})
        _need(type(w["taskId"]) is str)
        task = cast(str, w["taskId"])
        _need(
            0 < len(task) <= 128
            and len(task.encode("utf-8", "strict")) <= 512
            and task.strip() == task
            and not any(ord(char) < 32 or ord(char) == 127 for char in task)
        )
        _revision(w["version"])
        cancelled = w["state"] == "cancelled"
        _enum(
            w["state"],
            {
                "ready",
                "running",
                "retry_wait",
                "inquiry_complete",
                "waiting",
                "intent_committed",
                "failed",
                "uncertain",
                "completed",
                "cancelled",
            },
        )
    intent = _fields(c["intent"], {"state", "intentId"})
    state = _enum(intent["state"], {"not_committed", "committed"})
    _need((state == "committed") == (intent["intentId"] is not None))
    if intent["intentId"] is not None:
        _need(
            type(intent["intentId"]) is str and str(UUID(intent["intentId"])) == intent["intentId"]
        )
    mutation = _fields(
        c["mutation"], {"state", "outcome", "cancellation", "effectId", "outcomeEventId"}
    )
    _enum(
        mutation["state"],
        {
            "not_observed",
            "pending",
            "claimed",
            "dispatched",
            "succeeded",
            "failed",
            "uncertain",
            "cancelled",
        },
    )
    _enum(mutation["outcome"], {"not_observed", "succeeded", "failed", "uncertain", "cancelled"})
    _enum(
        mutation["cancellation"],
        {
            "not_observed",
            "not_requested",
            "cancelled_before_commit",
            "cancelled_before_dispatch",
            "requested_best_effort",
            "already_terminal",
        },
    )
    for key in ("effectId", "outcomeEventId"):
        item = mutation[key]
        if item is not None:
            _need(type(item) is str and str(UUID(item)) == item)
    if c["supplierResult"] is not None:
        supplier = _fields(
            c["supplierResult"], {"supplierId", "revision", "bookingReference", "newCheckIn"}
        )
        _need(
            type(supplier["supplierId"]) is str
            and str(UUID(supplier["supplierId"])) == supplier["supplierId"]
        )
        _revision(supplier["revision"])
        _booking(supplier["bookingReference"])
        _date(supplier["newCheckIn"])
    return revision, cancelled


def _record(value: WorkRecord) -> WorkRecord:
    _need(
        type(value) is WorkRecord
        and type(value.scope) is WorkScope
        and type(value.payload) is WorkPayload
    )
    return WorkRecord(
        value.work_id,
        WorkScope(value.scope.tenant_id, value.scope.account_id),
        value.idempotency_key,
        WorkPayload(value.payload.operation, value.payload.body, value.payload.deadline_at_ms),
        value.accepted_at_ms,
        value.cancel_requested,
        value.status,
    )


def _identity(record: WorkRecord) -> tuple[object, ...]:
    return (
        record.work_id,
        record.scope,
        record.idempotency_key,
        record.payload,
        record.accepted_at_ms,
    )


class CurrentResultProducer:
    """One actual scan and at most one owned inspection, including failed close.

    Concurrent readers of a published, unabandoned scan share its observation;
    only the last waiter's expiry/abort abandons it. Abandonment stops observation
    only. Check it after every await; admitted calls/factories/close remain
    retained, with no next business stage. close drains this transport/service-call
    ownership, not global borrowed SQL.
    """

    def __init__(
        self,
        *,
        binding: ProducerBinding,
        discovery: DiscoveryPort,
        prepared: PreparedReadPort,
        stored: StoredWorkPort,
        inspections: InspectionFactoryPort,
        native: NativeResultReadPort,
        evidence: EvidenceCatalogue,
        timeout_s: float = 5,
        cleanup_timeout_s: float = 1,
    ) -> None:
        _need(
            type(binding) is ProducerBinding and type(evidence) is EvidenceCatalogue,
            "invalid_input",
        )
        self._binding = ProducerBinding(
            binding.profile_id,
            binding.scope,
            binding.case_id,
            binding.conversation_id,
            binding.owner_id,
            binding.receiver_id,
            binding.recipient_id,
        )
        self._timeout, self._cleanup = _budget(timeout_s), _budget(cleanup_timeout_s)
        self._discovery = cast(_DiscoveryRead, _method(discovery, "read"))
        self._prepared = cast(_PreparedRead, _method(prepared, "read"))
        self._stored = cast(_StoredRead, _method(stored, "get"))
        self._open = cast(_Open, _method(inspections, "open_inspection"))
        self._native_read = cast(_NativeRead, _method(native, "read"))
        self._borrowed: tuple[object, ...] = (
            discovery,
            prepared,
            stored,
            inspections,
            native,
            evidence,
        )
        self._evidence = evidence
        self._scan: asyncio.Task[CurrentResultObservation] | None = None
        self._scan_publication: asyncio.Future[None] | None = None
        self._inspection: InspectionPort | None = None
        self._result_read: _InspectResult | None = None
        self._delivery_read: _InspectDelivery | None = None
        self._inspection_close: _Close | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closing = self._abandoned = False
        self._waiters = 0
        self._selected_deadline: int | None = None
        self._counts = {
            "scans_started": 0,
            "scans_joined": 0,
            "current": 0,
            "no_delivery": 0,
            "not_applicable": 0,
            "failed": 0,
        }

    def _bind(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        _need(self._loop is None or self._loop is loop, "invalid_input")
        self._loop = loop
        return loop

    def _check(self) -> None:
        _need(not self._abandoned and not self._closing, "request_aborted")

    def _scan_active(self) -> bool:
        return (self._scan_publication is not None and not self._scan_publication.done()) or (
            self._scan is not None and not self._scan.done()
        )

    def metrics(self) -> MappingProxyType[str, int]:
        return MappingProxyType(
            {
                **self._counts,
                "scan_active": int(self._scan_active()),
                "inspection_owned": int(self._inspection is not None),
                "close_active": int(self._close_task is not None and not self._close_task.done()),
            }
        )

    def _log(self, code: str) -> None:
        try:
            LOGGER.info("channel_policy_current_result", extra={"event": "observed", "code": code})
        except Exception:  # noqa: BLE001 - finite public boundary  # noqa: BLE001 - telemetry cannot change disclosure
            return

    def _observation(
        self,
        state: Literal["no_delivery", "not_applicable", "current"],
        result: CurrentResultProjection | None = None,
    ) -> CurrentResultObservation:
        b = self._binding
        value = CurrentResultObservation(
            b.profile_id,
            DiscoveryScope(b.scope.tenant_id, b.scope.account_id),
            b.case_id,
            b.conversation_id,
            datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            state,
            result,
        )
        return parse_current_result_observation(encode_current_result_observation(value))

    def _winner(
        self, value: ChannelPolicyView, frame: PreparedChannelInput, item: DiscoveryItem
    ) -> ChannelPolicyView:
        _need(type(value) is ChannelPolicyView)
        record = _record(value.record)
        _need(type(value.request) is ChannelPolicyRequest)
        request = parse_channel_policy_request(encode_channel_policy_request(value.request))
        body = encode_channel_policy_request(request)
        b = self._binding
        _need(
            (
                record.work_id,
                record.scope,
                record.idempotency_key,
                record.payload.operation,
                record.payload.body,
                record.payload.sha256,
                record.payload.deadline_at_ms,
            )
            == (
                item.external_receipt_id,
                WorkScope(b.scope.tenant_id, b.scope.account_id),
                channel_policy_key(item.operation_key),
                "booking.evaluate_policy",
                body,
                hashlib.sha256(body).hexdigest(),
                request.deadline_at_ms,
            )
        )
        o = request.origin
        _need(
            (
                o.kind,
                o.profile_id,
                o.operation_key,
                o.input_receipt_id,
                o.payload_sha256,
                o.payload_byte_length,
            )
            == (
                "p2.prepared_dispatch.v1",
                b.profile_id,
                item.operation_key,
                item.receipt_id,
                frame.payload_sha256,
                frame.payload_byte_length,
            ),
            "identity_conflict",
        )
        _need(
            (request.scope, request.case_id, request.conversation_id, request.request_revision)
            == (b.scope, b.case_id, b.conversation_id, int(frame.case_revision)),
            "identity_conflict",
        )
        self._evidence.select(request)
        return ChannelPolicyView(record, request)

    def _execution(
        self, view: ChannelPolicyExecutionView, winner: ChannelPolicyView
    ) -> ChannelPolicyExecutionView:
        _need(
            type(view) is ChannelPolicyExecutionView
            and type(view.execution) is ExecutionObservation
        )
        original = view.execution
        record = _record(original.record)
        _need(
            _identity(record) == _identity(winner.record)
            and encode_channel_policy_request(view.request)
            == encode_channel_policy_request(winner.request)
        )
        grant = original.current_attempt
        if grant is not None:
            _need(type(grant) is IssuedAttempt)
            grant = IssuedAttempt(
                _record(grant.record),
                grant.attempt_id,
                grant.command_id,
                grant.number,
                grant.owner_id,
                grant.epoch,
                grant.issued_at_ms,
                grant.lease_until_ms,
            )
        recorded = original.result
        if recorded is not None:
            _need(type(recorded) is AttemptResult)
            recorded = AttemptResult(
                recorded.work_id,
                recorded.attempt_id,
                recorded.body,
                recorded.recorded_at_ms,
                recorded.disposition,
            )
        copied = ExecutionObservation(
            record, grant, recorded, original.attempts_issued, original.status
        )
        applicability = _enum(
            view.applicability,
            {
                "missing",
                "candidate",
                "clarification",
                "outdated",
                "case_cancelled",
                "expired",
                "execution_ineligible",
                "unavailable",
            },
        )
        if recorded is None:
            _need(view.result is None and applicability == "missing")
            return ChannelPolicyExecutionView(copied, winner.request, None, "missing")
        _need(grant is not None and view.result is not None)
        grant = cast(IssuedAttempt, grant)
        result = parse_channel_policy_result(recorded.body)
        _need(
            encode_channel_policy_result(result) == recorded.body
            and encode_channel_policy_result(cast("ChannelPolicyResult", view.result))
            == recorded.body
        )
        transport = replace(
            winner.request,
            request=replace(
                winner.request.request,
                attempt=Attempt("attempt_" + UUID(grant.attempt_id).hex, grant.number),
            ),
        )
        match_channel_policy_result(transport, result, observed_at_ms=recorded.recorded_at_ms)
        verify_fixed_policy_facts(
            transport.request,
            result.result,
            self._evidence.select(winner.request),
            observed_at_ms=recorded.recorded_at_ms,
        )
        _need(applicability != "unavailable", "unavailable")
        now = time.time_ns() // 1_000_000
        facts = verify_fixed_policy_facts(
            transport.request,
            result.result,
            self._evidence.select(winner.request),
            observed_at_ms=now,
        )
        if (
            facts == "expired"
            or record.cancel_requested
            or recorded.disposition != "eligible_at_commit"
        ):
            return ChannelPolicyExecutionView(
                copied,
                winner.request,
                result,
                "expired" if facts == "expired" else "execution_ineligible",
            )
        return ChannelPolicyExecutionView(
            copied, winner.request, result, cast("Applicability", applicability)
        )

    def _delivery(
        self, value: DelegationDelivery, execution: ChannelPolicyExecutionView
    ) -> DeliverySnapshot:
        _need(
            type(value) is DelegationDelivery
            and value.receiver_invoked is False
            and type(value.snapshot) is DeliverySnapshot
        )
        snap = value.snapshot
        intent = snap.intent
        if intent is not None:
            _need(type(intent) is DeliveryIntent and type(intent.scope) is WorkScope)
            intent = DeliveryIntent(
                intent.delivery_id,
                WorkScope(intent.scope.tenant_id, intent.scope.account_id),
                intent.work_id,
                intent.attempt_id,
                intent.result_sha256,
                intent.receiver_id,
                intent.recipient_id,
                intent.body,
                intent.prepared_at_ms,
            )
            recorded = execution.execution.result
            _need(recorded is not None)
            recorded = cast(AttemptResult, recorded)
            b = self._binding
            _need(
                (
                    intent.scope,
                    intent.work_id,
                    intent.attempt_id,
                    intent.result_sha256,
                    intent.receiver_id,
                    intent.recipient_id,
                    intent.body,
                )
                == (
                    WorkScope(b.scope.tenant_id, b.scope.account_id),
                    execution.execution.record.work_id,
                    recorded.attempt_id,
                    recorded.sha256,
                    b.receiver_id,
                    b.recipient_id,
                    recorded.body,
                ),
                "identity_conflict",
            )
        receipt = snap.receipt
        if receipt is not None:
            _need(type(receipt) is DeliveryReceipt)
            receipt = DeliveryReceipt(
                receipt.delivery_id,
                receipt.receipt_id,
                receipt.receiver_id,
                receipt.recipient_id,
                receipt.result_sha256,
                receipt.accepted_at_ms,
            )
        copied = DeliverySnapshot(intent, snap.possible, receipt)
        state = (
            "accepted"
            if receipt is not None
            else "unknown"
            if copied.possible
            else "prepared"
            if intent is not None
            else "missing"
        )
        _need(type(value.state) is str and value.state == state)
        return copied

    async def _drain_inspection(self) -> None:
        owner = self._inspection
        if owner is None:
            return
        task = self._close_task
        if task is None or task.done() and (task.cancelled() or task.exception() is not None):
            _need(self._inspection_close is not None, "cleanup_incomplete")
            task = _spawn(cast(_Close, self._inspection_close)())
            self._close_task = task
        try:
            await asyncio.shield(task)
            count = owner.pending_count
            _need(type(count) is int and count == 0, "cleanup_incomplete")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - finite public boundary
            raise CurrentResultProducerError("cleanup_incomplete") from None
        self._inspection = self._result_read = self._delivery_read = self._inspection_close = None
        self._close_task = None

    async def _select(self) -> CurrentResultObservation:
        page = parse_discovery_page(encode_discovery_page(await self._discovery()))
        self._check()
        b = self._binding
        _need(
            (page.profile_id, page.scope, page.case_id, page.conversation_id)
            == (
                b.profile_id,
                DiscoveryScope(b.scope.tenant_id, b.scope.account_id),
                b.case_id,
                b.conversation_id,
            ),
            "unauthorized",
        )
        _need(not page.overflow, "overflow")
        for item in reversed(page.items):
            raw = await self._prepared(
                source_binding_id=item.source_binding_id, receipt_id=item.receipt_id
            )
            self._check()
            if raw is None:
                _need(item.state != "dispatched")
                continue
            frame = parse_accept_frame(raw)
            require_p3_compatible(frame)
            _need(
                (
                    frame.operation_key,
                    frame.input_receipt_id,
                    frame.scope.tenant_id,
                    frame.scope.account_id,
                    frame.case_id,
                    frame.conversation_id,
                )
                == (
                    item.operation_key,
                    item.receipt_id,
                    b.scope.tenant_id,
                    b.scope.account_id,
                    b.case_id,
                    b.conversation_id,
                ),
                "identity_conflict",
            )
            if item.state != "dispatched":
                continue
            work_id = cast(str, item.external_receipt_id)
            stored = await self._stored(work_id)
            self._check()
            winner = self._winner(stored, frame, item)
            owner = await self._open(work_id=work_id, owner_id=b.owner_id, request=winner.request)
            _need(all(owner is not borrowed for borrowed in self._borrowed), "invalid_stored_state")
            self._inspection = owner
            self._inspection_close = cast(_Close, _method(owner, "close"))
            self._result_read = cast(_InspectResult, _method(owner, "inspect_result"))
            self._delivery_read = cast(_InspectDelivery, _method(owner, "inspect_delivery"))
            self._check()
            execution = self._execution(await self._result_read(), winner)
            self._check()
            if execution.result is None:
                await self._drain_inspection()
                self._check()
                continue
            self._selected_deadline = winner.request.deadline_at_ms
            if execution.applicability not in {"candidate", "clarification"}:
                return self._observation("not_applicable")
            before = self._delivery(await self._delivery_read(), execution)
            self._check()
            if before.receipt is None or before.intent is None:
                return self._observation("no_delivery")
            native = await self._native_read(delivery_id=before.intent.delivery_id)
            self._check()
            # A body remains withheld until fresh public P3 and P1 observations
            # after the potentially delayed, generation-bound P2 read.
            after_execution = self._execution(await self._result_read(), winner)
            self._check()
            _need(after_execution.execution.result == execution.execution.result)
            after = self._delivery(await self._delivery_read(), after_execution)
            self._check()
            _need(after == before)
            if (
                after_execution.applicability not in {"candidate", "clarification"}
                or time.time_ns() // 1_000_000 >= winner.request.deadline_at_ms
            ):
                return self._observation("not_applicable")
            if native is None:
                return self._observation("no_delivery")
            obj = decode_object(native, CURRENT_RESULT_BYTES)
            n = _fields(obj, {"schemaVersion", "intent", "receipt", "case", "observed"})
            _need(type(n["schemaVersion"]) is int and n["schemaVersion"] == 1)
            revision, case_cancelled = _case(n["case"], b)
            shell = json.loads(encode_current_result_observation(self._observation("no_delivery")))
            shell.update(
                state="current",
                result={
                    "inputReceiptId": item.receipt_id,
                    "operationKey": item.operation_key,
                    "intent": n["intent"],
                    "receipt": n["receipt"],
                    "case": {"source": "p1_public_v4", "revision": revision},
                    "observed": n["observed"],
                },
            )
            projected = parse_current_result_observation(
                json.dumps(
                    shell, ensure_ascii=False, separators=(",", ":"), allow_nan=False
                ).encode("utf-8", "strict")
            )
            result = projected.result
            _need(result is not None)
            result = cast(CurrentResultProjection, result)
            _need(
                before.intent.canonical()
                == json.dumps(
                    n["intent"],
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                    allow_nan=False,
                ).encode("ascii")
                and (
                    result.receipt.delivery_id,
                    result.receipt.receipt_id,
                    result.receipt.receiver_id,
                    result.receipt.recipient_id,
                    result.receipt.result_sha256,
                    result.receipt.accepted_at_ms,
                )
                == (
                    before.receipt.delivery_id,
                    before.receipt.receipt_id,
                    before.receipt.receiver_id,
                    before.receipt.recipient_id,
                    before.receipt.result_sha256,
                    before.receipt.accepted_at_ms,
                ),
                "identity_conflict",
            )
            if case_cancelled or revision != str(winner.request.request_revision):
                return self._observation("not_applicable")
            return self._observation("current", result)
        return self._observation("no_delivery")

    async def _run(self) -> CurrentResultObservation:
        failure: BaseException | None = None
        result: CurrentResultObservation | None = None
        try:
            result = await self._select()
        except BaseException as error:  # noqa: BLE001 - drain owned inspection before control flow
            failure = error
        try:
            await self._drain_inspection()
        except Exception as error:  # noqa: BLE001 - preserve primary failure during cleanup
            if failure is None:
                failure = error
        if failure is not None:
            if not isinstance(failure, Exception):
                raise failure
            self._counts["failed"] += 1
            safe = _failure(failure)
            self._log(safe.code)
            raise safe from None
        self._check()
        _need(result is not None)
        result = cast(CurrentResultObservation, result)
        if (
            result.state == "current"
            and self._selected_deadline is not None
            and time.time_ns() // 1_000_000 >= self._selected_deadline
        ):
            result = self._observation("not_applicable")
        self._counts[result.state] += 1
        self._log(result.state)
        return result

    def _joinable(
        self, current: asyncio.Task[object] | None
    ) -> asyncio.Task[CurrentResultObservation] | None:
        scan = self._scan
        if (
            scan is None
            or scan.done()
            or scan is current
            or self._abandoned
            or self._scan_publication is None
            or not self._scan_publication.done()
        ):
            return None
        return scan

    async def _wait(
        self, loop: asyncio.AbstractEventLoop, scan: asyncio.Task[CurrentResultObservation]
    ) -> CurrentResultObservation:
        self._waiters += 1
        try:
            async with asyncio.timeout_at(loop.time() + self._timeout):
                return await asyncio.shield(scan)
        except TimeoutError:
            self._abandoned = self._abandoned or self._waiters == 1
            raise CurrentResultProducerError("deadline_exceeded") from None
        except asyncio.CancelledError:
            self._abandoned = self._abandoned or self._waiters == 1
            raise
        finally:
            self._waiters -= 1

    async def read(self) -> CurrentResultObservation:
        loop = self._bind()
        _need(not self._closing, "closed")
        current = asyncio.current_task()
        shared = self._joinable(current)
        if shared is not None:
            if current is not None and current.cancelling():
                raise asyncio.CancelledError
            self._counts["scans_joined"] += 1
            try:
                return await self._wait(loop, shared)
            except CurrentResultProducerError as error:
                raise CurrentResultProducerError(error.code) from None
        _need(not self._scan_active() and self._inspection is None, "capacity")
        if current is not None and current.cancelling():
            raise asyncio.CancelledError
        self._abandoned = False
        self._selected_deadline = None
        # Eager task factories may run/reenter before create_task returns. This
        # reservation is also a publication barrier: close cannot miss the
        # already-started scan while its Task reference is being transferred.
        try:
            publication: asyncio.Future[None] = loop.create_future()
        except Exception:  # noqa: BLE001 - no reservation/owner exists on allocation failure
            raise CurrentResultProducerError() from None
        self._scan_publication = publication
        try:
            scan = self._scan = _spawn(self._run())
        except Exception:  # noqa: BLE001 - finite public boundary
            raise CurrentResultProducerError() from None
        finally:
            # Covers ordinary setup failure and cancellation/control flow. The
            # unscheduled coroutine was closed by _spawn; no actual owner hides.
            publication.set_result(None)
        self._counts["scans_started"] += 1
        return await self._wait(loop, scan)

    async def close(self) -> None:
        loop = self._bind()
        self._closing = self._abandoned = True
        try:
            async with asyncio.timeout_at(loop.time() + self._cleanup):
                if self._scan_publication is not None:
                    await asyncio.shield(self._scan_publication)
                if self._scan is not None:
                    await asyncio.shield(asyncio.gather(self._scan, return_exceptions=True))
                await self._drain_inspection()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - finite public boundary
            raise CurrentResultProducerError("cleanup_incomplete") from None


class _NativeRead(Protocol):
    async def __call__(self, *, delivery_id: str) -> bytes | None: ...
