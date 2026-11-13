"""Two retained application job tickets over public execution and guarded delivery.

No queue, retry loop, source template, database, provider or environment is owned
here. A returned idle job consumes a factory ticket until verified actual close.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
import math
from collections.abc import Coroutine
from dataclasses import dataclass, field, replace
from inspect import getattr_static
from types import FunctionType, MappingProxyType, MethodType
from typing import Literal, Protocol, TypeVar, cast
from uuid import UUID

from continuity_lab.delivery_api import (
    DeliveryIntent,
    DeliveryPort,
    DeliveryReceipt,
    DeliverySnapshot,
)
from continuity_lab.execution_api import ExecutionObservation, ExecutionPort
from continuity_lab.work_api import WorkPayload, WorkRecord, WorkScope
from delegation_reliability import (
    ChannelPolicyDeliveryClient,
    ChannelPolicyExecutionView,
    ChannelPolicyRequest,
    ChannelPolicyRun,
    ChannelPolicyRunner,
    CompletionError,
    DelegationRunError,
    channel_policy_key,
    encode_channel_policy_request,
    parse_channel_policy_request,
)
from delegation_reliability.contracts import ContractError, Scope, decode, identifier
from delegation_reliability.coordinator import CaseAuthorityPort
from delegation_reliability.delivery_contract import (
    DelegationDelivery,
    DeliveryBinding,
    ResultReceiverPort,
)
from delegation_reliability.fixed_policy import snapshot_fixed_policy_records
from delegation_reliability.fixed_policy_execution import FixedPolicyInvocationPort
from delegation_reliability.security import EvidenceRecord

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
MAX_JOB_TICKETS = 2
JobCode = Literal[
    "invalid_input",
    "identity_conflict",
    "unauthorized",
    "invalid_stored_state",
    "capacity",
    "closed",
    "deadline_exceeded",
    "request_aborted",
    "cleanup_incomplete",
    "not_eligible",
    "case_changed",
    "case_cancelled",
    "expired",
    "acknowledgement_unknown",
    "unavailable",
]
_CODES = frozenset(
    {
        "invalid_input",
        "identity_conflict",
        "unauthorized",
        "invalid_stored_state",
        "capacity",
        "closed",
        "deadline_exceeded",
        "request_aborted",
        "cleanup_incomplete",
        "not_eligible",
        "case_changed",
        "case_cancelled",
        "expired",
        "acknowledgement_unknown",
        "unavailable",
    }
)
T = TypeVar("T")


class JobError(RuntimeError):
    """Static finite codes only; dependency descriptors and args never escape."""

    def __init__(self, code: JobCode = "unavailable") -> None:
        self.code: JobCode = code if type(code) is str and code in _CODES else "unavailable"
        super().__init__(self.code)


def _code(error: BaseException) -> JobCode:
    if isinstance(error, (JobError, DelegationRunError, CompletionError)):
        try:
            code: object = getattr_static(error, "code", None)
        except Exception:  # noqa: BLE001 - diagnostics must not invoke dependency code
            return "unavailable"
        if type(code) is str and code in _CODES:
            return cast(JobCode, code)
    return "unavailable"


def _uuid(value: str) -> str:
    if type(value) is not str:
        raise JobError("invalid_input")
    try:
        parsed = UUID(value)
    except ValueError:
        raise JobError("invalid_input") from None
    if parsed.version != 4 or str(parsed) != value:
        raise JobError("invalid_input")
    return value


def _budget(value: float, maximum: float) -> float:
    if type(value) not in (float, int) or not 0.001 <= value <= maximum or not math.isfinite(value):
        raise JobError("invalid_input")
    return float(value)


def _spawn(action: Coroutine[object, object, T]) -> asyncio.Task[T]:
    try:
        task = asyncio.create_task(action)
    except BaseException as error:
        action.close()
        if not isinstance(error, Exception):
            raise
        raise JobError("unavailable") from None

    def observed(done: asyncio.Task[T]) -> None:
        if not done.cancelled():
            done.exception()

    task.add_done_callback(observed)
    return task


def _static_async(value: object, name: str) -> object:
    """Snapshot genuine async callbacks without executing arbitrary descriptors."""
    try:
        raw: object = getattr_static(value, name, None)
        if type(raw) is MethodType:
            function = raw.__func__
            if type(function) is FunctionType and function.__code__.co_flags & inspect.CO_COROUTINE:
                return raw
        elif type(raw) is FunctionType:
            if raw.__code__.co_flags & inspect.CO_COROUTINE:
                return (
                    MethodType(raw, value)
                    if getattr_static(type(value), name, None) is raw
                    else raw
                )
        elif isinstance(raw, (staticmethod, classmethod)) and type(raw) in (
            staticmethod,
            classmethod,
        ):
            function = raw.__func__
            if type(function) is FunctionType and function.__code__.co_flags & inspect.CO_COROUTINE:
                return function if type(raw) is staticmethod else MethodType(function, type(value))
    except Exception:  # noqa: BLE001 - static inspection never reflects dependency diagnostics
        raise JobError("invalid_input") from None
    raise JobError("invalid_input")


class _OpenExecution(Protocol):
    async def __call__(self) -> ExecutionPort: ...


class _OpenSpecialist(Protocol):
    async def __call__(
        self, *, evidence: tuple[EvidenceRecord, ...]
    ) -> FixedPolicyInvocationPort: ...


class _OpenDelivery(Protocol):
    async def __call__(self) -> DeliveryPort: ...


class _OpenReceiver(Protocol):
    async def __call__(self) -> ResultReceiverPort: ...


class _Close(Protocol):
    async def __call__(self) -> None: ...


def _scope(value: Scope) -> Scope:
    try:
        if type(value) is not Scope:
            raise JobError("invalid_input")
        return Scope(identifier(value.tenant_id), identifier(value.account_id))
    except (ContractError, AttributeError, TypeError, ValueError):
        raise JobError("invalid_input") from None


def _request(value: ChannelPolicyRequest) -> ChannelPolicyRequest:
    try:
        if type(value) is not ChannelPolicyRequest:
            raise JobError("invalid_input")
        return parse_channel_policy_request(encode_channel_policy_request(value))
    except Exception:  # noqa: BLE001 - malformed nested DTOs cannot reflect private errors
        raise JobError("invalid_input") from None


class EvidenceCatalogue:
    """At most sixteen trusted pairs, selected by both winning immutable refs.

    Source record versions and byte hashes remain independent of policy version.
    Construction/selection is pure; no file/template/current proposal is read.
    """

    def __init__(self, pairs: tuple[tuple[EvidenceRecord, ...], ...]) -> None:
        try:
            if type(pairs) is not tuple or not 1 <= len(pairs) <= 16:
                raise JobError("invalid_input")
            copied: list[tuple[EvidenceRecord, ...]] = []
            for pair in pairs:
                if type(pair) is not tuple or len(pair) != 2:
                    raise JobError("invalid_input")
                records = snapshot_fixed_policy_records(pair)
                if records[0].scope != records[1].scope:
                    raise JobError("invalid_input")
                if any(
                    record.reference.media_type != "application/json"
                    or not 1 <= len(record.body) <= 4096
                    or type(decode(record.body, 4096)) is not dict
                    for record in records
                ):
                    raise JobError("invalid_input")
                key = (records[0].scope, tuple(record.reference for record in records))
                if any(
                    key == (existing[0].scope, tuple(record.reference for record in existing))
                    for existing in copied
                ):
                    raise JobError("identity_conflict")
                copied.append(records)
            self._pairs = tuple(copied)
        except (ContractError, AttributeError, TypeError, ValueError):
            raise JobError("invalid_input") from None

    def select(self, request: ChannelPolicyRequest) -> tuple[EvidenceRecord, ...]:
        request = _request(request)
        key = (request.scope, request.request.evidence)
        for records in self._pairs:
            if (records[0].scope, tuple(record.reference for record in records)) == key:
                return snapshot_fixed_policy_records(records)
        raise JobError("identity_conflict")


class JobClientFactory(Protocol):
    """Return fresh owned ports or settle internal unreturned setup before raising.

    Open must not hide a still-running constructor/thread when it raises. The
    job factory shields each actual open. A port returned after waiter
    abandonment is still adopted and closed before the global ticket is released.
    Shared case readers and other jobs' ports must never be returned here.
    """

    async def open_execution(self) -> ExecutionPort: ...

    async def open_specialist(
        self, *, evidence: tuple[EvidenceRecord, ...]
    ) -> FixedPolicyInvocationPort: ...

    async def open_delivery(self) -> DeliveryPort: ...

    async def open_receiver(self) -> ResultReceiverPort: ...


class ExecutionRunnerPort(Protocol):
    @property
    def pending_count(self) -> int: ...

    async def inspect(self, work_id: str) -> ChannelPolicyExecutionView: ...

    async def run_once(self, work_id: str, command_id: str) -> ChannelPolicyRun: ...

    async def close(self) -> None: ...


class GuardedDeliveryPort(Protocol):
    @property
    def pending_count(self) -> int: ...

    async def deliver_once(self, work_id: str) -> DelegationDelivery: ...

    async def inspect(self, work_id: str) -> DelegationDelivery: ...

    async def close(self) -> None: ...


class _Closable(Protocol):
    async def close(self) -> None: ...


class _OwnedFacade(_Closable, Protocol):
    @property
    def pending_count(self) -> int: ...


@dataclass(frozen=True, slots=True)
class DeliveryObservation:
    """Guarded delivery observation; accepted never means human acknowledgement."""

    state: Literal["not_started", "missing", "prepared", "unknown", "accepted", "denied", "failed"]
    value: DelegationDelivery | None = field(default=None, repr=False)
    code: JobCode | None = None


@dataclass(frozen=True, slots=True)
class JobObservation:
    execution: ChannelPolicyRun | None = field(repr=False)
    execution_code: JobCode | None
    delivery: DeliveryObservation


@dataclass(eq=False, slots=True)
class _Resource:
    value: _Closable = field(repr=False)
    tier: int
    close_task: asyncio.Task[None] | None = field(default=None, repr=False)
    close_action: _Close | None = field(default=None, repr=False)


@dataclass(eq=False, slots=True)
class _Ticket:
    resources: list[_Resource] = field(default_factory=list, repr=False)
    identities: set[int] = field(default_factory=set, repr=False)
    construction: asyncio.Task[_OwnedFacade] | None = field(default=None, repr=False)
    partial_close: asyncio.Task[None] | None = field(default=None, repr=False)
    job: _OwnedFacade | None = field(default=None, repr=False)
    cleanup_observer: asyncio.Task[None] | None = field(default=None, repr=False)
    abandoned: bool = False
    released: bool = False


async def _drain(ticket: _Ticket) -> None:
    """One close observation per resource, dependent delivery tier before runner.

    Failed or pending observers remain owned. A later explicit close may observe
    successful drainage or retry a failed public close; business calls never retry.
    """
    for tier in (0, 1):
        resources = tuple(item for item in ticket.resources if item.tier == tier)
        for resource in resources:
            task = resource.close_task
            if (
                task is not None
                and task.done()
                and (task.cancelled() or task.exception() is not None)
            ):
                resource.close_task = None
            if resource.close_task is None:
                if resource.close_action is None:
                    resource.close_action = cast(_Close, _static_async(resource.value, "close"))
                resource.close_task = _spawn(resource.close_action())
        tasks = tuple(resource.close_task for resource in resources)
        await asyncio.gather(*(task for task in tasks if task is not None), return_exceptions=True)
        failed = False
        for resource in resources:
            task = resource.close_task
            if task is None or task.cancelled() or task.exception() is not None:
                failed = True
            else:
                ticket.resources.remove(resource)
        if failed:
            raise JobError("cleanup_incomplete")


def _pending(port: ExecutionRunnerPort | GuardedDeliveryPort) -> int:
    try:
        count = port.pending_count
    except Exception:  # noqa: BLE001 - a failed owner observation cannot free its slot
        raise JobError("cleanup_incomplete") from None
    if type(count) is not int or not 0 <= count <= 1:
        raise JobError("cleanup_incomplete")
    return count


def _validate_winning_view(
    view: ChannelPolicyExecutionView,
    *,
    work_id: str,
    expected: ChannelPolicyRequest,
    expected_body: bytes,
) -> None:
    """Join immutable public P1 work/key/payload and the whole winning request.

    The public authority preserves accepted payload/key. This pre-read and
    post-run check is not an atomic fingerprint issue fence against corrupt
    or contradictory later authority reads.
    """
    try:
        if (
            type(view) is not ChannelPolicyExecutionView
            or type(view.execution) is not ExecutionObservation
        ):
            raise JobError("invalid_stored_state")
        record = view.execution.record
        if (
            type(record) is not WorkRecord
            or type(record.payload) is not WorkPayload
            or type(record.scope) is not WorkScope
        ):
            raise JobError("invalid_stored_state")
        payload = WorkPayload(
            record.payload.operation, record.payload.body, record.payload.deadline_at_ms
        )
        copied = WorkRecord(
            record.work_id,
            WorkScope(record.scope.tenant_id, record.scope.account_id),
            record.idempotency_key,
            payload,
            record.accepted_at_ms,
            record.cancel_requested,
            record.status,
        )
        if (
            copied.work_id != work_id
            or copied.scope != WorkScope(expected.scope.tenant_id, expected.scope.account_id)
            or copied.idempotency_key != channel_policy_key(expected.origin.operation_key)
            or payload.operation != "booking.evaluate_policy"
            or payload.body != expected_body
            or payload.sha256 != hashlib.sha256(expected_body).hexdigest()
            or payload.deadline_at_ms != expected.deadline_at_ms
            or encode_channel_policy_request(_request(view.request)) != expected_body
        ):
            raise JobError("invalid_stored_state")
    except Exception:  # noqa: BLE001 - malformed public observations stay finite before delivery
        raise JobError("invalid_stored_state") from None


class ActualJob:
    """One execution then guarded delivery, retained through all actual close.

    A cancelled/timed-out waiter abandons observation only. Already started I/O
    settles; no later delivery is admitted after that abandonment or close. The
    execution observation survives every delivery denial or operational failure.
    """

    def __init__(
        self,
        *,
        factory: ChannelPolicyJobFactory,
        ticket: _Ticket,
        work_id: str,
        request: ChannelPolicyRequest,
        runner: ExecutionRunnerPort,
        delivery: GuardedDeliveryPort,
    ) -> None:
        self._factory, self._ticket, self._work_id = factory, ticket, work_id
        self._runner, self._delivery = runner, delivery
        self._expected_request = _request(request)
        self._expected_body = encode_channel_policy_request(self._expected_request)
        self._run_task: asyncio.Task[ChannelPolicyRun] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._closing = self._abandoned = self._waiting = False
        self._observation = JobObservation(None, None, DeliveryObservation("not_started"))

    @property
    def observation(self) -> JobObservation:
        return self._observation

    @property
    def pending_count(self) -> int:
        return int(
            (self._run_task is not None and not self._run_task.done())
            or (self._close_task is not None and not self._close_task.done())
            or _pending(self._runner) > 0
            or _pending(self._delivery) > 0
        )

    def metrics(self) -> MappingProxyType[str, int]:
        return MappingProxyType(
            {
                "active": self.pending_count,
                "runner_pending": _pending(self._runner),
                "delivery_pending": _pending(self._delivery),
                "stage_pending": int(self._run_task is not None and not self._run_task.done()),
                "close_pending": int(self._close_task is not None and not self._close_task.done()),
            }
        )

    def _validate_view(self, view: ChannelPolicyExecutionView) -> None:
        _validate_winning_view(
            view,
            work_id=self._work_id,
            expected=self._expected_request,
            expected_body=self._expected_body,
        )

    async def _run(self, command_id: str) -> ChannelPolicyRun:
        try:
            self._validate_view(await self._runner.inspect(self._work_id))
            if self._abandoned or self._closing:
                raise JobError("request_aborted")
            execution = await self._runner.run_once(self._work_id, command_id)
            if type(execution) is not ChannelPolicyRun:
                raise JobError("invalid_stored_state")
            self._validate_view(execution.view)
        except asyncio.CancelledError:
            self._observation = JobObservation(None, "request_aborted", self._observation.delivery)
            raise
        except Exception as error:  # noqa: BLE001 - never expose dependency args/getters
            code = _code(error)
            self._observation = JobObservation(None, code, self._observation.delivery)
            raise JobError(code) from None
        self._observation = JobObservation(execution, None, self._observation.delivery)
        if self._abandoned or self._closing:
            self._observation = JobObservation(
                execution, None, DeliveryObservation("not_started", code="request_aborted")
            )
            return execution
        try:
            delivery = await self._delivery.deliver_once(self._work_id)
            if type(delivery) is not DelegationDelivery or delivery.state not in {
                "missing",
                "prepared",
                "unknown",
                "accepted",
            }:
                raise JobError("invalid_stored_state")
            observation = DeliveryObservation(delivery.state, delivery)
        except asyncio.CancelledError:
            self._observation = JobObservation(
                execution, None, DeliveryObservation("unknown", code="request_aborted")
            )
            raise
        except Exception as error:  # noqa: BLE001 - execution remains a known separate fact
            code = _code(error)
            state: Literal["unknown", "denied", "failed"] = (
                "unknown"
                if code == "acknowledgement_unknown"
                else "denied"
                if code in {"not_eligible", "case_changed", "case_cancelled", "expired"}
                else "failed"
            )
            observation = DeliveryObservation(state, code=code)
        self._observation = JobObservation(execution, None, observation)
        self._factory._log("delivery", observation.code or "ok")
        return execution

    async def run_once(self, work_id: str, command_id: str) -> ChannelPolicyRun:
        loop = self._factory._bind()
        if _uuid(work_id) != self._work_id or command_id != "cp45_" + UUID(work_id).hex:
            raise JobError("identity_conflict")
        if self._closing:
            raise JobError("closed")
        if self._waiting:
            raise JobError("capacity")
        if self._run_task is None:
            self._run_task = _spawn(self._run(command_id))
        self._waiting = True
        try:
            async with asyncio.timeout_at(loop.time() + self._factory._timeout):
                return await asyncio.shield(self._run_task)
        except TimeoutError:
            self._abandoned = True
            raise JobError("deadline_exceeded") from None
        except asyncio.CancelledError:
            self._abandoned = True
            raise
        finally:
            self._waiting = False

    async def close(self) -> None:
        loop = self._factory._bind()
        self._closing = True
        if self._ticket.released:
            return
        if (
            self._close_task is not None
            and self._close_task.done()
            and (self._close_task.cancelled() or self._close_task.exception() is not None)
        ):
            self._close_task = None
        if self._close_task is None:

            async def finish() -> None:
                if self._run_task is not None:
                    await asyncio.gather(self._run_task, return_exceptions=True)
                await _drain(self._ticket)
                if _pending(self._runner) or _pending(self._delivery):
                    raise JobError("cleanup_incomplete")
                self._factory._release(self._ticket)

            self._close_task = _spawn(finish())
        try:
            async with asyncio.timeout_at(loop.time() + self._factory._cleanup):
                await asyncio.shield(self._close_task)
        except TimeoutError:
            raise JobError("cleanup_incomplete") from None
        except Exception:  # noqa: BLE001 - failed close retains the same job/ticket
            raise JobError("cleanup_incomplete") from None


class ReadOnlyInspection:
    """One read at a time on a retained job ticket; no execution/delivery actions.

    Caller loss abandons observation, not the actual read or its owned clients.
    Closing stops new reads and waits for actual settlement before tiered drain.
    The accepted public P1 request/key are immutable, as for execution jobs.
    """

    def __init__(
        self,
        *,
        factory: ChannelPolicyJobFactory,
        ticket: _Ticket,
        work_id: str,
        request: ChannelPolicyRequest,
        runner: ExecutionRunnerPort,
        delivery: GuardedDeliveryPort,
        receiver_id: str,
    ) -> None:
        self._factory, self._ticket, self._work_id = factory, ticket, work_id
        self._runner, self._delivery = runner, delivery
        self._receiver_id = _uuid(receiver_id)
        self._expected_request = _request(request)
        self._expected_body = encode_channel_policy_request(self._expected_request)
        self._stage: asyncio.Task[ChannelPolicyExecutionView | DelegationDelivery] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._waiting = self._closing = self._abandoned = False

    @property
    def pending_count(self) -> int:
        return int(
            (self._stage is not None and not self._stage.done())
            or (self._close_task is not None and not self._close_task.done())
            or _pending(self._runner) > 0
            or _pending(self._delivery) > 0
        )

    def metrics(self) -> MappingProxyType[str, int]:
        return MappingProxyType(
            {
                "active": self.pending_count,
                "runner_pending": _pending(self._runner),
                "delivery_pending": _pending(self._delivery),
                "stage_pending": int(self._stage is not None and not self._stage.done()),
                "close_pending": int(self._close_task is not None and not self._close_task.done()),
            }
        )

    def _delivery_view(self, value: DelegationDelivery) -> DelegationDelivery:
        try:
            if (
                type(value) is not DelegationDelivery
                or type(value.snapshot) is not DeliverySnapshot
                or value.receiver_invoked is not False
            ):
                raise JobError("invalid_stored_state")
            original = value.snapshot
            if original.intent is not None and (
                type(original.intent) is not DeliveryIntent
                or type(original.intent.scope) is not WorkScope
            ):
                raise JobError("invalid_stored_state")
            if original.receipt is not None and type(original.receipt) is not DeliveryReceipt:
                raise JobError("invalid_stored_state")
            snapshot = DeliverySnapshot(
                replace(
                    original.intent,
                    scope=WorkScope(
                        original.intent.scope.tenant_id, original.intent.scope.account_id
                    ),
                )
                if original.intent is not None
                else None,
                original.possible,
                replace(original.receipt) if original.receipt is not None else None,
            )
            intent = snapshot.intent
            if intent is not None and (
                intent.work_id != self._work_id
                or intent.scope
                != WorkScope(
                    self._expected_request.scope.tenant_id,
                    self._expected_request.scope.account_id,
                )
                or intent.receiver_id != self._receiver_id
                or intent.recipient_id != self._factory._binding.recipient_id
            ):
                raise JobError("invalid_stored_state")
            state: Literal["missing", "prepared", "unknown", "accepted"] = (
                "accepted"
                if snapshot.receipt is not None
                else "unknown"
                if snapshot.possible
                else "prepared"
                if snapshot.intent is not None
                else "missing"
            )
            if value.state != state:
                raise JobError("invalid_stored_state")
            return DelegationDelivery(snapshot, state)
        except Exception:  # noqa: BLE001 - malformed stored DTOs never reflect their contents
            raise JobError("invalid_stored_state") from None

    async def _inspect(
        self, kind: Literal["result", "delivery"]
    ) -> ChannelPolicyExecutionView | DelegationDelivery:
        try:
            view = await self._runner.inspect(self._work_id)
            _validate_winning_view(
                view,
                work_id=self._work_id,
                expected=self._expected_request,
                expected_body=self._expected_body,
            )
            if kind == "result":
                return view
            if self._closing or self._abandoned or self._factory._closing or self._ticket.abandoned:
                raise JobError("request_aborted")
            return self._delivery_view(await self._delivery.inspect(self._work_id))
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - only static finite dependency codes escape
            raise JobError(_code(error)) from None

    async def _read(
        self, kind: Literal["result", "delivery"]
    ) -> ChannelPolicyExecutionView | DelegationDelivery:
        loop = self._factory._bind()
        current = asyncio.current_task()
        if current is not None and current.cancelling():
            raise asyncio.CancelledError
        if (
            self._closing
            or self._factory._closing
            or self._ticket.abandoned
            or self._ticket.released
        ):
            raise JobError("closed")
        if self._waiting or self.pending_count:
            raise JobError("capacity")
        # Reserve before create_task, including eager task factories and reentry.
        self._waiting, self._abandoned = True, False
        try:
            self._stage = _spawn(self._inspect(kind))
            try:
                async with asyncio.timeout_at(loop.time() + self._factory._timeout):
                    return await asyncio.shield(self._stage)
            except TimeoutError:
                self._abandoned = True
                raise JobError("deadline_exceeded") from None
            except asyncio.CancelledError:
                self._abandoned = True
                raise
        finally:
            self._waiting = False

    async def inspect_result(self) -> ChannelPolicyExecutionView:
        return cast(ChannelPolicyExecutionView, await self._read("result"))

    async def inspect_delivery(self) -> DelegationDelivery:
        return cast(DelegationDelivery, await self._read("delivery"))

    async def close(self) -> None:
        loop = self._factory._bind()
        self._closing = True
        if self._ticket.released:
            return
        if (
            self._close_task is not None
            and self._close_task.done()
            and (self._close_task.cancelled() or self._close_task.exception() is not None)
        ):
            self._close_task = None
        if self._close_task is None:

            async def finish() -> None:
                if self._stage is not None:
                    await asyncio.gather(self._stage, return_exceptions=True)
                await _drain(self._ticket)
                if _pending(self._runner) or _pending(self._delivery):
                    raise JobError("cleanup_incomplete")
                self._factory._release(self._ticket)

            try:
                self._close_task = _spawn(finish())
            except Exception:  # noqa: BLE001 - owned facades remain retained on allocation failure
                raise JobError("cleanup_incomplete") from None
        try:
            async with asyncio.timeout_at(loop.time() + self._factory._cleanup):
                await asyncio.shield(self._close_task)
        except TimeoutError:
            raise JobError("cleanup_incomplete") from None
        except Exception:  # noqa: BLE001 - every unresolved read/close remains owned
            raise JobError("cleanup_incomplete") from None


class ChannelPolicyJobFactory:
    """Factory-global two-ticket bound spans partial setup, jobs and close.

    This factory owns returned client ports and facades. Shared case authority and
    the injected client-construction facade are borrowed and never closed here.
    The outer application closes those only after this factory actually drains.
    """

    def __init__(
        self,
        *,
        scope: Scope,
        case_authority: CaseAuthorityPort,
        bindings: tuple[DeliveryBinding, ...],
        catalogue: EvidenceCatalogue,
        clients: JobClientFactory,
        timeout_s: float = 10,
        cleanup_timeout_s: float = 1,
    ) -> None:
        self._scope = _scope(scope)
        try:
            if type(bindings) is not tuple or len(bindings) != 1:
                raise JobError("invalid_input")
            binding = bindings[0]
            if type(binding) is not DeliveryBinding or type(catalogue) is not EvidenceCatalogue:
                raise JobError("invalid_input")
            self._binding = DeliveryBinding(
                binding.case_id, binding.conversation_id, binding.recipient_id
            )
            _static_async(case_authority, "snapshot")
            self._open_execution = cast(_OpenExecution, _static_async(clients, "open_execution"))
            self._open_specialist = cast(_OpenSpecialist, _static_async(clients, "open_specialist"))
            self._open_delivery = cast(_OpenDelivery, _static_async(clients, "open_delivery"))
            self._open_receiver = cast(_OpenReceiver, _static_async(clients, "open_receiver"))
        except Exception:  # noqa: BLE001 - constructor descriptors cannot expose diagnostics
            raise JobError("invalid_input") from None
        self._catalogue, self._clients, self._cases = catalogue, clients, case_authority
        self._timeout = _budget(timeout_s, 10)
        self._cleanup = _budget(cleanup_timeout_s, 5)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tickets: set[_Ticket] = set()
        self._identities: set[int] = set()
        self._closing = False
        self._close_task: asyncio.Task[None] | None = None
        self._telemetry_failed = 0

    def _bind(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        if loop is not self._loop:
            raise JobError("invalid_input")
        return loop

    @property
    def active_count(self) -> int:
        return len(self._tickets)

    def metrics(self) -> MappingProxyType[str, int]:
        return MappingProxyType(
            {
                "active_tickets": self.active_count,
                "constructing": sum(
                    ticket.construction is not None and not ticket.construction.done()
                    for ticket in self._tickets
                ),
                "returned_jobs": sum(ticket.job is not None for ticket in self._tickets),
                "partial_owners": sum(
                    ticket.job is None and bool(ticket.resources) for ticket in self._tickets
                ),
                "telemetry_failed": self._telemetry_failed,
            }
        )

    def _log(self, operation: Literal["delivery", "close"], code: JobCode | Literal["ok"]) -> None:
        try:
            LOGGER.info("channel_policy_job", extra={"operation": operation, "code": code})
        except Exception:  # noqa: BLE001 - diagnostics cannot erase accepted observations
            self._telemetry_failed += 1

    def _claim(self, ticket: _Ticket, value: _Closable, tier: int) -> None:
        if (
            any(value is borrowed for borrowed in (cast(object, self), self._clients, self._cases))
            or id(value) in self._identities
            or any(value is item.job for item in self._tickets)
        ):
            raise JobError("invalid_input")
        # Adopt before validating close shape; malformed owned returns cannot free capacity.
        ticket.identities.add(id(value))
        self._identities.add(id(value))
        resource = _Resource(value, tier)
        ticket.resources.append(resource)
        try:
            resource.close_action = cast(_Close, _static_async(value, "close"))
        except Exception:  # noqa: BLE001 - no dependency descriptor diagnostics escape
            raise JobError("invalid_input") from None

    def _transfer(
        self, ticket: _Ticket, owner: _Closable, children: tuple[_Closable, ...], tier: int
    ) -> None:
        self._claim(ticket, owner, tier)
        for child in children:
            ticket.resources[:] = [
                resource for resource in ticket.resources if resource.value is not child
            ]

    def _release(self, ticket: _Ticket) -> None:
        if ticket.resources:
            raise JobError("cleanup_incomplete")
        self._identities.difference_update(ticket.identities)
        self._tickets.discard(ticket)
        ticket.released = True

    def _admit_stage(self, ticket: _Ticket) -> None:
        if ticket.abandoned or self._closing:
            raise JobError("request_aborted")

    async def _close_partial(self, ticket: _Ticket) -> None:
        if ticket.released:
            return
        if (
            ticket.partial_close is not None
            and ticket.partial_close.done()
            and (ticket.partial_close.cancelled() or ticket.partial_close.exception() is not None)
        ):
            ticket.partial_close = None
        if ticket.partial_close is None:

            async def finish() -> None:
                await _drain(ticket)
                self._release(ticket)

            ticket.partial_close = _spawn(finish())
        await asyncio.shield(ticket.partial_close)

    async def _construct(
        self,
        ticket: _Ticket,
        work_id: str,
        owner_id: str,
        request: ChannelPolicyRequest,
        evidence: tuple[EvidenceRecord, ...],
        *,
        inspection: bool = False,
    ) -> _OwnedFacade:
        try:
            executions = await self._open_execution()
            self._claim(ticket, executions, 1)
            self._admit_stage(ticket)
            specialist = await self._open_specialist(evidence=evidence)
            self._claim(ticket, specialist, 1)
            self._admit_stage(ticket)
            runner = ChannelPolicyRunner(
                executions=executions,
                scope=self._scope,
                owner_id=owner_id,
                specialist=specialist,
                case_authority=self._cases,
                evidence=evidence,
                max_active=1,
            )
            self._transfer(ticket, runner, (executions, specialist), 1)
            deliveries = await self._open_delivery()
            self._claim(ticket, deliveries, 0)
            self._admit_stage(ticket)
            receiver = await self._open_receiver()
            self._claim(ticket, receiver, 0)
            self._admit_stage(ticket)
            delivery = ChannelPolicyDeliveryClient(
                results=runner,
                deliveries=deliveries,
                receiver=receiver,
                scope=self._scope,
                evidence=evidence,
                bindings=(self._binding,),
                max_active=1,
            )
            self._transfer(ticket, delivery, (deliveries, receiver), 0)
            job: _OwnedFacade
            if inspection:
                job = ReadOnlyInspection(
                    factory=self,
                    ticket=ticket,
                    work_id=work_id,
                    request=request,
                    runner=runner,
                    delivery=delivery,
                    receiver_id=receiver.receiver_id,
                )
            else:
                job = ActualJob(
                    factory=self,
                    ticket=ticket,
                    work_id=work_id,
                    request=request,
                    runner=runner,
                    delivery=delivery,
                )
            ticket.job = job
            return job
        except BaseException as error:
            # The task itself may fail with cancellation while earlier ports remain ours.
            # A separate retained observer survives that control flow and owns their close.
            try:
                await self._close_partial(ticket)
            except BaseException as cleanup_error:
                self._log("close", "cleanup_incomplete")
                if not isinstance(cleanup_error, Exception) and isinstance(error, Exception):
                    raise
            if not isinstance(error, Exception):
                raise
            raise JobError(_code(error)) from None

    def _abandon_open(self, ticket: _Ticket) -> None:
        ticket.abandoned = True
        # Construction may have completed in the same loop turn as waiter loss.
        # Its idle returned owner is still ours even though no caller received it.
        if ticket.job is not None and not ticket.released and ticket.cleanup_observer is None:
            try:
                ticket.cleanup_observer = _spawn(ticket.job.close())
            except Exception:  # noqa: BLE001 - preserve the primary waiter failure and owner
                self._log("close", "cleanup_incomplete")

    async def open(
        self, *, work_id: str, owner_id: str, request: ChannelPolicyRequest
    ) -> ActualJob:
        return cast(
            ActualJob,
            await self._open(work_id=work_id, owner_id=owner_id, request=request, inspection=False),
        )

    async def open_inspection(
        self, *, work_id: str, owner_id: str, request: ChannelPolicyRequest
    ) -> ReadOnlyInspection:
        return cast(
            ReadOnlyInspection,
            await self._open(work_id=work_id, owner_id=owner_id, request=request, inspection=True),
        )

    async def _open(
        self,
        *,
        work_id: str,
        owner_id: str,
        request: ChannelPolicyRequest,
        inspection: bool,
    ) -> _OwnedFacade:
        loop = self._bind()
        work_id, owner_id, request = _uuid(work_id), _uuid(owner_id), _request(request)
        if request.scope != self._scope or (
            request.case_id,
            request.conversation_id,
        ) != (self._binding.case_id, self._binding.conversation_id):
            raise JobError("unauthorized")
        evidence = self._catalogue.select(request)
        if self._closing:
            raise JobError("closed")
        if self.active_count >= MAX_JOB_TICKETS:
            raise JobError("capacity")
        ticket = _Ticket()
        self._tickets.add(ticket)
        try:
            ticket.construction = _spawn(
                self._construct(ticket, work_id, owner_id, request, evidence, inspection=inspection)
            )
        except BaseException:
            self._release(ticket)
            raise
        try:
            async with asyncio.timeout_at(loop.time() + self._timeout):
                return await asyncio.shield(ticket.construction)
        except TimeoutError:
            self._abandon_open(ticket)
            raise JobError("deadline_exceeded") from None
        except asyncio.CancelledError:
            self._abandon_open(ticket)
            raise

    async def close(self) -> None:
        loop = self._bind()
        self._closing = True
        for ticket in self._tickets:
            ticket.abandoned = True

        async def close_ticket(ticket: _Ticket) -> None:
            if ticket.construction is not None:
                # An outer cleanup deadline must never cancel partial startup.
                await asyncio.shield(asyncio.gather(ticket.construction, return_exceptions=True))
            if ticket.job is not None:
                await ticket.job.close()
            else:
                await self._close_partial(ticket)

        async def finish() -> None:
            tickets = tuple(self._tickets)
            for ticket in tickets:
                task = ticket.cleanup_observer
                if (
                    task is not None
                    and task.done()
                    and (task.cancelled() or task.exception() is not None)
                ):
                    ticket.cleanup_observer = None
                if ticket.cleanup_observer is None:
                    ticket.cleanup_observer = _spawn(close_ticket(ticket))
            outcomes = await asyncio.gather(
                *(
                    ticket.cleanup_observer
                    for ticket in tickets
                    if ticket.cleanup_observer is not None
                ),
                return_exceptions=True,
            )
            if any(isinstance(value, BaseException) for value in outcomes) or self._tickets:
                raise JobError("cleanup_incomplete")

        if (
            self._close_task is not None
            and self._close_task.done()
            and (self._close_task.cancelled() or self._close_task.exception() is not None)
        ):
            self._close_task = None
        if self._close_task is None:
            self._close_task = _spawn(finish())
        try:
            async with asyncio.timeout_at(loop.time() + self._cleanup):
                await asyncio.shield(self._close_task)
        except TimeoutError:
            raise JobError("cleanup_incomplete") from None
        except Exception:  # noqa: BLE001 - every unresolved owner stays in the factory
            raise JobError("cleanup_incomplete") from None
