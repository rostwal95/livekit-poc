"""Explicit result delivery over P1's immutable plan and a cooperating receiver.

This module starts no listener, worker or retry loop. A receiver receipt means
accepted bytes, never playback, human acknowledgement or booking authorization.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Generic, Literal, Protocol, TypeVar, cast, get_args
from uuid import UUID

from continuity_lab.delivery_api import (
    DeliveryIntent,
    DeliveryPort,
    DeliveryReceipt,
    DeliverySnapshot,
    DeliveryStart,
)
from continuity_lab.execution_api import AttemptResult, ExecutionObservation, IssuedAttempt
from continuity_lab.work_api import WorkError, WorkScope

from ._policy_codec import (
    CHANNEL_CODEC,
    FIXED_CODEC,
    V1_CODEC,
    PolicyFacts,
    RequestT,
    ResultT,
    _PolicyCodec,
)
from .channel_policy_execution import ChannelPolicyExecutionView
from .contracts import (
    Attempt,
    ContractError,
    DelegationRequest,
    DelegationResult,
    EvidenceRef,
    Scope,
    identifier,
)
from .delivery_contract import DelegationDelivery, DeliveryBinding, ResultReceiverPort
from .fixed_policy import _snapshot_fixed_policy_pair
from .fixed_policy_execution import FixedPolicyExecutionView
from .runner import (
    Applicability,
    DelegationExecutionView,
    DelegationRunError,
    _attempt_with_codec,
    _record_with_codec,
)
from .security import EvidenceRecord, EvidenceRegistry

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
T = TypeVar("T")
CompletionCode = Literal[
    "invalid_input",
    "unauthorized",
    "not_found",
    "identity_conflict",
    "capacity",
    "expired",
    "storage_unavailable",
    "acknowledgement_unknown",
    "schema_mismatch",
    "closed",
    "cleanup_incomplete",
    "invalid_stored_state",
    "invalid_result",
    "not_eligible",
    "case_changed",
    "case_cancelled",
    "invalid_confirmation",
    "request_aborted",
    "deadline_exceeded",
    "internal_error",
    "stale_revision",
    "quote_expired",
    "deadline_expired",
    "intent_committed",
]
_CODES = frozenset(get_args(CompletionCode))


class CompletionError(RuntimeError):
    """One fixed public code; raw dependency errors and payloads never escape."""

    def __init__(self, code: CompletionCode) -> None:
        self.code = code if type(code) is str and code in _CODES else "internal_error"
        super().__init__(self.code)


class DelegationResultReadPort(Protocol):
    """Application-owned, already bounded result inspection; no invocation permission."""

    async def inspect(self, work_id: str) -> DelegationExecutionView: ...


class FixedPolicyResultReadPort(Protocol):
    """Application-owned v2 inspection; no invocation or delivery permission."""

    async def inspect(self, work_id: str) -> FixedPolicyExecutionView: ...


class ChannelPolicyResultReadPort(Protocol):
    """Application-owned v3 inspection; origin data grants no delivery authority."""

    async def inspect(self, work_id: str) -> ChannelPolicyExecutionView: ...


class _Closable(Protocol):
    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class _Result:
    view: DelegationExecutionView
    request: DelegationRequest
    transport: DelegationRequest
    result: DelegationResult
    issued: IssuedAttempt
    recorded: AttemptResult


@dataclass(frozen=True, slots=True)
class _ValidatedResult(Generic[RequestT, ResultT]):
    execution: ExecutionObservation
    request: RequestT
    transport: RequestT
    result: ResultT
    issued: IssuedAttempt
    recorded: AttemptResult
    applicability: Applicability
    facts: PolicyFacts


@dataclass(frozen=True, slots=True)
class _DeliveryResult:
    work_id: str
    case_id: str
    conversation_id: str
    new_eligible: bool
    issued: IssuedAttempt
    recorded: AttemptResult


@dataclass(eq=False, slots=True)
class _Call:
    operation: str
    deadline: float
    abandoned: bool = False
    writing: bool = False
    external: bool = False
    task: asyncio.Task[object] | None = field(default=None, repr=False)


def _uuid(value: str) -> str:
    if type(value) is not str or len(value) != 36:
        raise CompletionError("invalid_input")
    try:
        parsed = UUID(value)
    except ValueError:
        raise CompletionError("invalid_input") from None
    if parsed.version != 4 or str(parsed) != value:
        raise CompletionError("invalid_input")
    return value


def _scope(value: Scope) -> Scope:
    if type(value) is not Scope:
        raise CompletionError("invalid_input")
    try:
        return Scope(identifier(value.tenant_id), identifier(value.account_id))
    except ContractError:
        raise CompletionError("invalid_input") from None


def _evidence(scope: Scope, values: tuple[EvidenceRecord, ...]) -> tuple[EvidenceRecord, ...]:
    try:
        if type(values) is not tuple or not 1 <= len(values) <= 4:
            raise CompletionError("invalid_input")
        EvidenceRegistry(values)
        if any(item.scope != scope for item in values):
            raise CompletionError("unauthorized")
        copied = tuple(
            EvidenceRecord(
                Scope(item.scope.tenant_id, item.scope.account_id),
                EvidenceRef(
                    item.reference.source_id,
                    item.reference.version,
                    item.reference.sha256,
                    item.reference.media_type,
                    item.reference.byte_length,
                    item.reference.width,
                    item.reference.height,
                ),
                bytes(item.body),
            )
            for item in values
        )
        if sum(len(item.body) for item in copied) > 16384:
            raise CompletionError("invalid_input")
        return copied
    except (ContractError, AttributeError, TypeError, ValueError):
        raise CompletionError("invalid_input") from None


def _validated_result(
    execution: ExecutionObservation,
    observed_request: RequestT,
    observed_result: ResultT | None,
    applicability: Applicability,
    scope: Scope,
    work_id: str,
    evidence: tuple[EvidenceRecord, ...],
    codec: _PolicyCodec[RequestT, ResultT],
) -> _ValidatedResult[RequestT, ResultT]:
    """Copy complete immutable history through one of the closed policy codecs."""
    try:
        if type(execution) is not ExecutionObservation:
            raise CompletionError("invalid_stored_state")
        record, request = _record_with_codec(execution.record, scope, work_id, codec)
        if execution.current_attempt is None or execution.result is None or observed_result is None:
            raise CompletionError("not_eligible")
        issued = _attempt_with_codec(execution.current_attempt, scope, record, codec)
        original = execution.result
        if type(original) is not AttemptResult:
            raise CompletionError("invalid_stored_state")
        recorded = AttemptResult(
            original.work_id,
            original.attempt_id,
            original.body,
            original.recorded_at_ms,
            original.disposition,
        )
        observed = ExecutionObservation(
            record, issued, recorded, execution.attempts_issued, execution.status
        )
        if (recorded.work_id, recorded.attempt_id) != (work_id, issued.attempt_id):
            raise CompletionError("invalid_stored_state")
        result = codec.parse_result(recorded.body)
        if (
            codec.encode_result(result) != recorded.body
            or codec.encode_result(observed_result) != recorded.body
        ):
            raise CompletionError("invalid_stored_state")
        if codec.encode_request(observed_request) != record.payload.body:
            raise CompletionError("invalid_stored_state")
        transport = codec.with_attempt(
            request, Attempt("attempt_" + UUID(issued.attempt_id).hex, issued.number)
        )
        transport = codec.parse_request(codec.encode_request(transport))
        facts = codec.verify(transport, result, evidence, recorded.recorded_at_ms)
        if type(applicability) is not str or applicability not in {
            "missing",
            "candidate",
            "clarification",
            "outdated",
            "case_cancelled",
            "expired",
            "execution_ineligible",
            "unavailable",
        }:
            raise CompletionError("invalid_stored_state")
        return _ValidatedResult(
            observed, request, transport, result, issued, recorded, applicability, facts
        )
    except (ContractError, DelegationRunError, WorkError, AttributeError, TypeError, ValueError):
        raise CompletionError("invalid_stored_state") from None


def _result(
    value: DelegationExecutionView, scope: Scope, work_id: str, evidence: tuple[EvidenceRecord, ...]
) -> _Result:
    """Preserve the strict v1 result contract shared by the action adapter."""
    if type(value) is not DelegationExecutionView:
        raise CompletionError("invalid_stored_state")
    checked = _validated_result(
        value.execution,
        value.request,
        value.result,
        value.applicability,
        scope,
        work_id,
        evidence,
        V1_CODEC,
    )
    view = DelegationExecutionView(
        checked.execution, checked.request, checked.result, checked.applicability
    )
    return _Result(
        view, checked.request, checked.transport, checked.result, checked.issued, checked.recorded
    )


class _CompletionOwner:
    """Finite owned port calls; cancellation of a waiter does not retire actual I/O."""

    def __init__(
        self,
        scope: Scope,
        clients: tuple[_Closable, ...],
        *,
        max_active: int,
        timeout_ms: int,
        cleanup_ms: int,
    ) -> None:
        self._scope = _scope(scope)
        if (
            type(max_active) is not int
            or not 1 <= max_active <= 4
            or type(timeout_ms) is not int
            or not 20 <= timeout_ms <= 10000
            or type(cleanup_ms) is not int
            or not 20 <= cleanup_ms <= 5000
        ):
            raise CompletionError("invalid_input")
        self._clients = clients
        self._maximum, self._timeout, self._cleanup = (
            max_active,
            timeout_ms / 1000,
            cleanup_ms / 1000,
        )
        self._calls: set[_Call] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None
        self._counts = {
            "started": 0,
            "succeeded": 0,
            "failed": 0,
            "capacity_rejected": 0,
            "timed_out_waiters": 0,
            "cancelled_waiters": 0,
            "telemetry_failed": 0,
            "receiver_invoked": 0,
            "reconciled": 0,
        }

    def _bind(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        if self._loop is not loop:
            raise CompletionError("invalid_input")
        return loop

    @property
    def pending_count(self) -> int:
        return len(self._calls)

    def metrics(self) -> MappingProxyType[str, int]:
        return MappingProxyType({**self._counts, "active": self.pending_count})

    @staticmethod
    def _check(call: _Call) -> None:
        if call.abandoned:
            raise CompletionError("request_aborted")
        if asyncio.get_running_loop().time() >= call.deadline:
            raise CompletionError("deadline_exceeded")

    def _require_scope(self, actual: WorkScope) -> None:
        try:
            if type(actual) is not WorkScope or WorkScope(
                actual.tenant_id, actual.account_id
            ) != WorkScope(self._scope.tenant_id, self._scope.account_id):
                raise CompletionError("unauthorized")
        except WorkError:
            raise CompletionError("unauthorized") from None

    async def _run(self, operation: str, action: Callable[[_Call], Awaitable[T]]) -> T:
        loop = self._bind()
        if self._closed:
            raise CompletionError("closed")
        if len(self._calls) >= self._maximum:
            self._counts["capacity_rejected"] += 1
            raise CompletionError("capacity")
        call = _Call(operation, loop.time() + self._timeout)
        self._calls.add(call)
        self._counts["started"] += 1

        async def owned() -> T:
            code, outcome = "ok", "succeeded"
            try:
                return await action(call)
            except CompletionError as error:
                code, outcome = error.code, "failed"
                raise
            except (WorkError, DelegationRunError) as error:
                code, outcome = error.code if error.code in _CODES else "internal_error", "failed"
                raise CompletionError(cast(CompletionCode, code)) from None
            except asyncio.CancelledError:
                code, outcome = "request_aborted", "failed"
                raise
            except Exception:  # noqa: BLE001 - one fixed public adapter boundary
                code, outcome = "internal_error", "failed"
                raise CompletionError("internal_error") from None
            finally:
                self._counts[outcome] += 1
                try:
                    LOGGER.info(
                        "delegation_completion",
                        extra={
                            "event": "delegation_completion",
                            "operation": operation,
                            "code": code,
                            "outcome": outcome,
                        },
                    )
                except Exception:  # noqa: BLE001 - telemetry cannot alter committed facts
                    self._counts["telemetry_failed"] += 1

        task = asyncio.create_task(owned())
        call.task = task

        def settled(completed: asyncio.Task[T]) -> None:
            self._calls.discard(call)
            if not completed.cancelled():
                completed.exception()

        task.add_done_callback(settled)
        try:
            async with asyncio.timeout_at(call.deadline):
                result = await asyncio.shield(task)
                if loop.time() >= call.deadline:
                    raise TimeoutError
                return result
        except TimeoutError:
            call.abandoned = True
            self._counts["timed_out_waiters"] += 1
            raise CompletionError(
                "acknowledgement_unknown" if call.writing else "deadline_exceeded"
            ) from None
        except asyncio.CancelledError:
            call.abandoned = True
            self._counts["cancelled_waiters"] += 1
            raise

    async def close(self) -> None:
        loop = self._bind()
        self._closed = True
        for call in self._calls:
            if not call.external:
                call.abandoned = True
        if (
            self._close_task is not None
            and self._close_task.done()
            and (self._close_task.cancelled() or self._close_task.exception() is not None)
        ):
            self._close_task = None
        if self._close_task is None:

            async def finish() -> None:
                tasks = tuple(call.task for call in self._calls if call.task is not None)
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                outcomes = await asyncio.gather(
                    *(client.close() for client in self._clients), return_exceptions=True
                )
                if any(isinstance(value, BaseException) for value in outcomes):
                    raise CompletionError("cleanup_incomplete")

            self._close_task = asyncio.create_task(finish())
            self._close_task.add_done_callback(
                lambda done: None if done.cancelled() else done.exception()
            )
        deadline = loop.time() + self._cleanup
        try:
            async with asyncio.timeout_at(deadline):
                await asyncio.shield(self._close_task)
        except TimeoutError:
            raise CompletionError("cleanup_incomplete") from None
        if self._calls or loop.time() >= deadline:
            raise CompletionError("cleanup_incomplete")


class _DeliveryCore(_CompletionOwner):
    """One delivery algorithm over validated immutable v1 or fixed-policy history."""

    def __init__(
        self,
        *,
        deliveries: DeliveryPort,
        receiver: ResultReceiverPort,
        scope: Scope,
        evidence: tuple[EvidenceRecord, ...],
        bindings: tuple[DeliveryBinding, ...],
        max_active: int = 2,
        timeout_ms: int = 5000,
        cleanup_ms: int = 1000,
    ) -> None:
        super().__init__(
            scope,
            (deliveries, receiver),
            max_active=max_active,
            timeout_ms=timeout_ms,
            cleanup_ms=cleanup_ms,
        )
        self._require_scope(deliveries.scope)
        self._receiver_id = _uuid(receiver.receiver_id)
        if type(bindings) is not tuple or not 1 <= len(bindings) <= 128:
            raise CompletionError("invalid_input")
        copied = []
        try:
            for binding in bindings:
                if type(binding) is not DeliveryBinding:
                    raise CompletionError("invalid_input")
                copied.append(
                    DeliveryBinding(binding.case_id, binding.conversation_id, binding.recipient_id)
                )
        except ContractError:
            raise CompletionError("invalid_input") from None
        if len({(b.case_id, b.conversation_id) for b in copied}) != len(copied):
            raise CompletionError("invalid_input")
        self._bindings = tuple(copied)
        self._deliveries, self._receiver = deliveries, receiver
        self._evidence = _evidence(self._scope, evidence)

    async def _read_result(self, work_id: str) -> _DeliveryResult:
        raise NotImplementedError

    @property
    def scope(self) -> WorkScope:
        self._require_scope(self._deliveries.scope)
        return WorkScope(self._scope.tenant_id, self._scope.account_id)

    @property
    def receiver_id(self) -> str:
        self._require_scope(self._deliveries.scope)
        self._require_receiver()
        return self._receiver_id

    @property
    def bindings(self) -> tuple[DeliveryBinding, ...]:
        self._require_scope(self._deliveries.scope)
        self._require_receiver()
        return tuple(
            DeliveryBinding(b.case_id, b.conversation_id, b.recipient_id) for b in self._bindings
        )

    def _require_receiver(self) -> None:
        try:
            if _uuid(self._receiver.receiver_id) != self._receiver_id:
                raise CompletionError("identity_conflict")
        except CompletionError:
            raise
        except Exception:  # noqa: BLE001 - a misbound receiver cannot reflect configuration
            raise CompletionError("identity_conflict") from None

    def _plan(self, value: DeliveryIntent, result: _DeliveryResult) -> DeliveryIntent:
        try:
            if type(value) is not DeliveryIntent:
                raise CompletionError("invalid_stored_state")
            copied = DeliveryIntent(
                value.delivery_id,
                WorkScope(value.scope.tenant_id, value.scope.account_id),
                value.work_id,
                value.attempt_id,
                value.result_sha256,
                value.receiver_id,
                value.recipient_id,
                value.body,
                value.prepared_at_ms,
            )
            binding = next(
                (
                    b
                    for b in self._bindings
                    if b.case_id == result.case_id and b.conversation_id == result.conversation_id
                ),
                None,
            )
            if binding is None:
                raise CompletionError("unauthorized")
            if (
                copied.scope != WorkScope(self._scope.tenant_id, self._scope.account_id)
                or copied.work_id != result.work_id
                or copied.attempt_id != result.issued.attempt_id
                or copied.result_sha256 != result.recorded.sha256
                or copied.body != result.recorded.body
            ):
                raise CompletionError("invalid_stored_state")
            if (
                copied.receiver_id != self._receiver_id
                or copied.recipient_id != binding.recipient_id
            ):
                raise CompletionError("identity_conflict")
            return copied
        except (WorkError, AttributeError, TypeError, ValueError):
            raise CompletionError("invalid_stored_state") from None

    @staticmethod
    def _receipt(value: DeliveryReceipt, intent: DeliveryIntent) -> DeliveryReceipt:
        try:
            if type(value) is not DeliveryReceipt:
                raise CompletionError("invalid_stored_state")
            copied = DeliveryReceipt(
                value.delivery_id,
                value.receipt_id,
                value.receiver_id,
                value.recipient_id,
                value.result_sha256,
                value.accepted_at_ms,
            )
            if (
                copied.delivery_id,
                copied.receiver_id,
                copied.recipient_id,
                copied.result_sha256,
            ) != (
                intent.delivery_id,
                intent.receiver_id,
                intent.recipient_id,
                intent.result_sha256,
            ):
                raise CompletionError("invalid_stored_state")
            return copied
        except (WorkError, AttributeError, TypeError, ValueError):
            raise CompletionError("invalid_stored_state") from None

    def _snapshot(self, value: DeliverySnapshot, result: _DeliveryResult) -> DeliverySnapshot:
        if type(value) is not DeliverySnapshot or type(value.possible) is not bool:
            raise CompletionError("invalid_stored_state")
        intent = None if value.intent is None else self._plan(value.intent, result)
        if value.receipt is not None and intent is None:
            raise CompletionError("invalid_stored_state")
        receipt = (
            None
            if value.receipt is None
            else self._receipt(value.receipt, cast(DeliveryIntent, intent))
        )
        try:
            return DeliverySnapshot(intent, value.possible, receipt)
        except WorkError:
            raise CompletionError("invalid_stored_state") from None

    async def _inspect(self, work_id: str) -> tuple[_DeliveryResult, DeliverySnapshot]:
        result = await self._read_result(work_id)
        self._require_scope(self._deliveries.scope)
        snapshot = self._snapshot(await self._deliveries.inspect(work_id=work_id), result)
        return result, snapshot

    @staticmethod
    def _view(snapshot: DeliverySnapshot, *, invoked: bool = False) -> DelegationDelivery:
        state: Literal["missing", "prepared", "unknown", "accepted"] = (
            "accepted"
            if snapshot.receipt is not None
            else "unknown"
            if snapshot.possible
            else "prepared"
            if snapshot.intent is not None
            else "missing"
        )
        return DelegationDelivery(snapshot, state, invoked)

    async def inspect(self, work_id: str) -> DelegationDelivery:
        work_id = _uuid(work_id)

        async def read(_: _Call) -> DelegationDelivery:
            _observed, snapshot = await self._inspect(work_id)
            return self._view(snapshot)

        return await self._run("delivery_inspect", read)

    async def deliver_once(self, work_id: str) -> DelegationDelivery:
        work_id = _uuid(work_id)
        return await self._run("deliver", lambda call: self._deliver(call, work_id))

    async def _deliver(self, call: _Call, work_id: str) -> DelegationDelivery:
        result, snapshot = await self._inspect(work_id)
        if snapshot.receipt is not None:
            return self._view(snapshot)
        intent = snapshot.intent
        if not snapshot.possible:
            if not result.new_eligible or result.recorded.disposition != "eligible_at_commit":
                raise CompletionError("not_eligible")
            binding = next(
                (
                    b
                    for b in self._bindings
                    if b.case_id == result.case_id and b.conversation_id == result.conversation_id
                ),
                None,
            )
            if binding is None:
                raise CompletionError("unauthorized")
            self._check(call)
            self._require_scope(self._deliveries.scope)
            call.writing = True
            if intent is None:
                try:
                    intent = self._plan(
                        await self._deliveries.prepare(
                            work_id=work_id,
                            attempt_id=result.issued.attempt_id,
                            result_sha256=result.recorded.sha256,
                            receiver_id=self._receiver_id,
                            recipient_id=binding.recipient_id,
                        ),
                        result,
                    )
                except WorkError as error:
                    if error.code != "acknowledgement_unknown":
                        raise
                    self._require_scope(self._deliveries.scope)
                    try:
                        observed = await self._deliveries.inspect(work_id=work_id)
                    except WorkError:
                        raise CompletionError("acknowledgement_unknown") from None
                    snapshot = self._snapshot(observed, result)
                    if snapshot.intent is None:
                        raise CompletionError("acknowledgement_unknown") from None
                    intent = snapshot.intent
            self._check(call)
            self._require_scope(self._deliveries.scope)
            try:
                started = await self._deliveries.begin(intent=intent)
                if type(started) is not DeliveryStart or type(started.created) is not bool:
                    raise CompletionError("invalid_stored_state")
                if self._plan(started.intent, result) != intent:
                    raise CompletionError("invalid_stored_state")
                created = started.created
            except WorkError as error:
                if error.code != "acknowledgement_unknown":
                    raise
                created = False
        else:
            created = False
        assert intent is not None
        if created:
            # The created begin persisted a possible-send marker that later calls
            # only look up, so this call must reach the receiver despite waiter loss.
            call.external = True
        else:
            self._check(call)
        self._require_receiver()
        # Find before accept also reconciles an already committed cooperating receiver.
        try:
            receipt = await self._receiver.find(intent)
        except WorkError as error:
            if error.code in {"storage_unavailable", "acknowledgement_unknown"}:
                raise CompletionError("acknowledgement_unknown") from None
            raise
        invoked = False
        if receipt is None:
            if not created:
                return self._view(DeliverySnapshot(intent, True, None))
            self._counts["receiver_invoked"] += 1
            invoked = True
            self._require_receiver()
            try:
                receipt = await self._receiver.accept(intent)
            except WorkError as error:
                if error.code != "acknowledgement_unknown":
                    raise
                self._require_receiver()
                try:
                    receipt = await self._receiver.find(intent)
                except WorkError:
                    raise CompletionError("acknowledgement_unknown") from None
                if receipt is None:
                    raise CompletionError("acknowledgement_unknown") from None
                self._counts["reconciled"] += 1
        receipt = self._receipt(receipt, intent)
        self._require_scope(self._deliveries.scope)
        call.writing = True
        try:
            stored = await self._deliveries.record_receipt(intent=intent, receipt=receipt)
        except WorkError as error:
            if error.code != "acknowledgement_unknown":
                raise
            self._require_scope(self._deliveries.scope)
            try:
                observed = await self._deliveries.inspect(work_id=work_id)
            except WorkError:
                raise CompletionError("acknowledgement_unknown") from None
            snapshot = self._snapshot(observed, result)
            if snapshot.receipt is None:
                raise CompletionError("acknowledgement_unknown") from None
            stored = snapshot.receipt
            self._counts["reconciled"] += 1
        if self._receipt(stored, intent) != receipt:
            raise CompletionError("invalid_stored_state")
        return self._view(DeliverySnapshot(intent, True, receipt), invoked=invoked)


class DelegationDeliveryClient(_DeliveryCore):
    """Explicit v1 delivery; the application owns its shared result inspector.

    This client owns and closes its P1 delivery and receiver clients. Only a new
    persisted begin may accept bytes remotely; an existing possible send performs
    lookup only, and reliable absence remains unknown for a paused prior caller.
    """

    def __init__(
        self,
        *,
        results: DelegationResultReadPort,
        deliveries: DeliveryPort,
        receiver: ResultReceiverPort,
        scope: Scope,
        evidence: tuple[EvidenceRecord, ...],
        bindings: tuple[DeliveryBinding, ...],
        max_active: int = 2,
        timeout_ms: int = 5000,
        cleanup_ms: int = 1000,
    ) -> None:
        super().__init__(
            deliveries=deliveries,
            receiver=receiver,
            scope=scope,
            evidence=evidence,
            bindings=bindings,
            max_active=max_active,
            timeout_ms=timeout_ms,
            cleanup_ms=cleanup_ms,
        )
        self._results = results

    async def _read_result(self, work_id: str) -> _DeliveryResult:
        checked = _result(
            await self._results.inspect(work_id), self._scope, work_id, self._evidence
        )
        return _DeliveryResult(
            work_id,
            checked.request.case_id,
            checked.request.conversation_id,
            checked.view.applicability in {"candidate", "clarification"},
            checked.issued,
            checked.recorded,
        )


class FixedPolicyDeliveryClient(_DeliveryCore):
    """Opt-in v2 delivery of a current, fully verified policy answer.

    New delivery requires candidate applicability and P1 begin eligibility. An
    original possible delivery performs lookup only, even after cancellation or
    expiry; its absence remains unknown. Receiver acceptance is distinct from
    carrier delivery, playback, human acknowledgement and action authority.

    Owns the supplied delivery and receiver ports; the application retains its
    shared result inspector. Actual calls remain owned after waiter cancellation
    or timeout, and incomplete close requires an explicit later observation.
    """

    def __init__(
        self,
        *,
        results: FixedPolicyResultReadPort,
        deliveries: DeliveryPort,
        receiver: ResultReceiverPort,
        scope: Scope,
        evidence: tuple[EvidenceRecord, ...],
        bindings: tuple[DeliveryBinding, ...],
        max_active: int = 2,
        timeout_ms: int = 5000,
        cleanup_ms: int = 1000,
    ) -> None:
        try:
            copied = _snapshot_fixed_policy_pair(evidence)
        except (ContractError, AttributeError, TypeError, ValueError):
            raise CompletionError("invalid_input") from None
        super().__init__(
            deliveries=deliveries,
            receiver=receiver,
            scope=scope,
            evidence=copied,
            bindings=bindings,
            max_active=max_active,
            timeout_ms=timeout_ms,
            cleanup_ms=cleanup_ms,
        )
        self._results = results

    async def _read_result(self, work_id: str) -> _DeliveryResult:
        value = await self._results.inspect(work_id)
        if type(value) is not FixedPolicyExecutionView:
            raise CompletionError("invalid_stored_state")
        checked = _validated_result(
            value.execution,
            value.request,
            value.result,
            value.applicability,
            self._scope,
            work_id,
            self._evidence,
            FIXED_CODEC,
        )
        return _DeliveryResult(
            work_id,
            checked.request.case_id,
            checked.request.conversation_id,
            checked.applicability == "candidate" and checked.facts == "candidate",
            checked.issued,
            checked.recorded,
        )


class ChannelPolicyDeliveryClient(_DeliveryCore):
    """Deliver the original verified v3 bytes through the existing P1/P2 seam.

    Only a current candidate may begin a new delivery. Existing possible and
    accepted original receipts retain the shared lookup-only reconciliation
    semantics; the application owns the supplied result inspector.
    """

    def __init__(
        self,
        *,
        results: ChannelPolicyResultReadPort,
        deliveries: DeliveryPort,
        receiver: ResultReceiverPort,
        scope: Scope,
        evidence: tuple[EvidenceRecord, ...],
        bindings: tuple[DeliveryBinding, ...],
        max_active: int = 2,
        timeout_ms: int = 5000,
        cleanup_ms: int = 1000,
    ) -> None:
        try:
            copied = _snapshot_fixed_policy_pair(evidence)
        except (ContractError, AttributeError, TypeError, ValueError):
            raise CompletionError("invalid_input") from None
        super().__init__(
            deliveries=deliveries,
            receiver=receiver,
            scope=scope,
            evidence=copied,
            bindings=bindings,
            max_active=max_active,
            timeout_ms=timeout_ms,
            cleanup_ms=cleanup_ms,
        )
        self._results = results

    async def _read_result(self, work_id: str) -> _DeliveryResult:
        value = await self._results.inspect(work_id)
        if type(value) is not ChannelPolicyExecutionView:
            raise CompletionError("invalid_stored_state")
        checked = _validated_result(
            value.execution,
            value.request,
            value.result,
            value.applicability,
            self._scope,
            work_id,
            self._evidence,
            CHANNEL_CODEC,
        )
        return _DeliveryResult(
            work_id,
            checked.request.case_id,
            checked.request.conversation_id,
            checked.applicability == "candidate" and checked.facts == "candidate",
            checked.issued,
            checked.recorded,
        )
