"""P3 immutable acceptance over P1's public read-only work authority.

This slice submits and inspects acceptance. It issues no attempt, starts no worker,
invokes no specialist, accepts no delivery and commits no booking action.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Generic, Literal, Protocol, Self, TypeVar, cast
from uuid import UUID

from continuity_lab.work_api import (
    TaskExecutionPort,
    WorkCancellation,
    WorkError,
    WorkPayload,
    WorkRecord,
    WorkScope,
    WorkSubmission,
)

from ._policy_codec import V1_CODEC, RequestT, ResultT, _PolicyCodec
from .contracts import (
    CAPABILITY,
    MAX_DEADLINE_WINDOW_MS,
    ContractError,
    DelegationRequest,
    DelegationResult,
    Scope,
    identifier,
    integer,
)
from .delivery_contract import ResultDeliveryPort

__all__ = [
    "CaseAuthorityPort",
    "CaseSnapshot",
    "CoordinatorCode",
    "CoordinatorError",
    "DelegationCoordinator",
    "DelegationSubmission",
    "DelegationView",
    "DeliveryObservation",
    "ResultDeliveryPort",
]

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
CoordinatorCode = Literal[
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
    "case_changed",
    "case_cancelled",
    "case_state_unavailable",
    "deadline_exceeded",
    "request_aborted",
    "invalid_stored_state",
    "internal_error",
]
_WORK_CODES = frozenset(
    {
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
    }
)
T = TypeVar("T")


class CoordinatorError(RuntimeError):
    """Fixed safe boundary code; dependency messages never become diagnostics."""

    def __init__(self, code: CoordinatorCode) -> None:
        allowed = {
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
            "case_changed",
            "case_cancelled",
            "case_state_unavailable",
            "deadline_exceeded",
            "request_aborted",
            "invalid_stored_state",
            "internal_error",
        }
        self.code = code if type(code) is str and code in allowed else "internal_error"
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class CaseSnapshot:
    """A trusted read observation; it cannot authorize a later action commitment."""

    scope: Scope
    case_id: str
    request_revision: int
    cancelled: bool


class CaseAuthorityPort(Protocol):
    """Credential-bound case read. Atomic action authority belongs to P3-I07."""

    async def snapshot(self, *, case_id: str) -> CaseSnapshot: ...


@dataclass(frozen=True, slots=True)
class DeliveryObservation:
    scope: Scope
    delegation_id: str
    delivery_id: str
    state: Literal["accepted", "observed"]


@dataclass(frozen=True, slots=True)
class DelegationView:
    """Original immutable accepted input, separate from computation or delivery."""

    record: WorkRecord
    request: DelegationRequest = field(repr=False)


@dataclass(frozen=True, slots=True)
class DelegationSubmission:
    view: DelegationView
    created: bool


@dataclass(eq=False, slots=True)
class _Call:
    operation: Literal["submit", "find", "get", "cancel"]
    deadline: float
    abandoned: bool = False
    writing: bool = False
    task: asyncio.Task[object] | None = field(default=None, repr=False)


def _uuid(value: str) -> str:
    if type(value) is not str or len(value) != 36:
        raise CoordinatorError("invalid_input")
    try:
        parsed = UUID(value)
    except ValueError:
        raise CoordinatorError("invalid_input") from None
    if parsed.version != 4 or str(parsed) != value:
        raise CoordinatorError("invalid_input")
    return value


def _scope(value: Scope) -> Scope:
    if type(value) is not Scope:
        raise CoordinatorError("invalid_input")
    return Scope(identifier(value.tenant_id), identifier(value.account_id))


_IdentityMode = Literal["exact", "channel_origin"]


def _same_input(
    original: RequestT,
    candidate: RequestT,
    codec: _PolicyCodec[RequestT, ResultT],
    mode: _IdentityMode,
) -> None:
    # Both inputs were independently parsed and had their fingerprints recomputed.
    # Compare the complete semantic envelope, not a claimed digest alone.
    if mode == "exact":
        first, second = codec.replay_identity(original), codec.replay_identity(candidate)
    elif mode == "channel_origin":
        first, second = codec.origin_identity(original), codec.origin_identity(candidate)
    else:
        raise CoordinatorError("invalid_input")
    if first != second:
        raise CoordinatorError("identity_conflict")


@dataclass(frozen=True, slots=True)
class _AcceptedView(Generic[RequestT]):
    record: WorkRecord
    request: RequestT = field(repr=False)


@dataclass(frozen=True, slots=True)
class _Submission(Generic[RequestT]):
    view: _AcceptedView[RequestT]
    created: bool


class _CoordinatorCore(Generic[RequestT, ResultT]):
    """Finite orchestration of public ports, without a second durable state owner.

    The execution client is owned and closed by this coordinator. The application
    owns the case adapter's lifecycle. A cancelled/expired waiter does not cancel
    already-started P1 I/O. It cannot start a write after abandonment at a preflight
    boundary. An ambiguous acknowledgement is reconciled only by the original key.
    """

    def __init__(
        self,
        *,
        executions: TaskExecutionPort,
        codec: _PolicyCodec[RequestT, ResultT],
        scope: Scope,
        case_authority: CaseAuthorityPort,
        max_active: int = 4,
        timeout_ms: int = 5000,
        cleanup_ms: int = 1000,
    ) -> None:
        self._codec: _PolicyCodec[RequestT, ResultT] = codec
        try:
            self._scope = _scope(scope)
        except ContractError:
            raise CoordinatorError("invalid_input") from None
        if (
            type(max_active) is not int
            or not 1 <= max_active <= 16
            or type(timeout_ms) is not int
            or not 20 <= timeout_ms <= 5000
            or type(cleanup_ms) is not int
            or not 20 <= cleanup_ms <= 5000
        ):
            raise CoordinatorError("invalid_input")
        self._executions, self._cases = executions, case_authority
        self._require_execution_scope()
        self._maximum, self._timeout, self._cleanup = (
            max_active,
            timeout_ms / 1000,
            cleanup_ms / 1000,
        )
        self._calls: set[_Call] = set()
        self._closed = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._counts = {
            "started": 0,
            "succeeded": 0,
            "failed": 0,
            "cancelled_waiters": 0,
            "timed_out_waiters": 0,
            "capacity_rejected": 0,
            "telemetry_failed": 0,
        }

    def _require_execution_scope(self) -> None:
        try:
            actual = self._executions.scope
            if type(actual) is not WorkScope:
                raise CoordinatorError("unauthorized")
            copied = WorkScope(actual.tenant_id, actual.account_id)
        except CoordinatorError:
            raise
        except Exception:  # noqa: BLE001 - trusted composition failure has fixed diagnostics
            raise CoordinatorError("unauthorized") from None
        if copied != WorkScope(self._scope.tenant_id, self._scope.account_id):
            raise CoordinatorError("unauthorized")

    @property
    def pending_count(self) -> int:
        return len(self._calls)

    def metrics(self) -> MappingProxyType[str, int]:
        return MappingProxyType({**self._counts, "active": self.pending_count})

    def _bind(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        if self._loop is not loop:
            raise CoordinatorError("invalid_input")
        return loop

    @staticmethod
    def _check(call: _Call) -> None:
        if call.abandoned:
            raise CoordinatorError("request_aborted")
        if asyncio.get_running_loop().time() >= call.deadline:
            raise CoordinatorError("deadline_exceeded")

    def _view(self, value: WorkRecord) -> _AcceptedView[RequestT]:
        try:
            if (
                type(value) is not WorkRecord
                or type(value.scope) is not WorkScope
                or type(value.payload) is not WorkPayload
                or type(value.payload.body) is not bytes
            ):
                raise CoordinatorError("invalid_stored_state")
            payload = WorkPayload(
                value.payload.operation, value.payload.body, value.payload.deadline_at_ms
            )
            if (
                type(value.payload.sha256) is not str
                or value.payload.sha256 != hashlib.sha256(payload.body).hexdigest()
            ):
                raise CoordinatorError("invalid_stored_state")
            record = WorkRecord(
                value.work_id,
                WorkScope(value.scope.tenant_id, value.scope.account_id),
                value.idempotency_key,
                payload,
                value.accepted_at_ms,
                value.cancel_requested,
                value.status,
            )
            original = self._codec.parse_request(payload.body)
            if (
                record.scope != WorkScope(self._scope.tenant_id, self._scope.account_id)
                or original.scope != self._scope
                or record.idempotency_key != original.delegation_id
                or payload.operation != CAPABILITY
                or payload.deadline_at_ms != original.deadline_at_ms
                or self._codec.encode_request(original) != payload.body
            ):
                raise CoordinatorError("invalid_stored_state")
            return _AcceptedView[RequestT](record, original)
        except (ContractError, WorkError, ValueError, TypeError, AttributeError):
            raise CoordinatorError("invalid_stored_state") from None

    def _snapshot(self, request: RequestT) -> RequestT:
        try:
            snapshot = self._codec.parse_request(self._codec.encode_request(request))
        except ContractError:
            raise CoordinatorError("invalid_input") from None
        if snapshot.scope != self._scope:
            raise CoordinatorError("unauthorized")
        return snapshot

    async def _submit_request(
        self, request: RequestT, *, identity: _IdentityMode = "exact"
    ) -> _Submission[RequestT]:
        snapshot = self._snapshot(request)
        return await self._run("submit", lambda call: self._submit(call, snapshot, identity))

    async def _submit(
        self, call: _Call, snapshot: RequestT, identity: _IdentityMode
    ) -> _Submission[RequestT]:
        original = await self._executions.find(idempotency_key=snapshot.delegation_id)
        if original is not None:
            view = self._view(original)
            _same_input(view.request, snapshot, self._codec, identity)
            return _Submission[RequestT](view, False)
        self._check(call)
        observed = await self._cases.snapshot(case_id=snapshot.case_id)
        self._check(call)
        try:
            if type(observed) is not CaseSnapshot or type(observed.cancelled) is not bool:
                raise CoordinatorError("invalid_stored_state")
            actual_scope = _scope(observed.scope)
            case_id = identifier(observed.case_id)
            revision = integer(observed.request_revision, 1, 9_007_199_254_740_991)
        except ContractError:
            raise CoordinatorError("invalid_stored_state") from None
        if actual_scope != self._scope or case_id != snapshot.case_id:
            raise CoordinatorError("unauthorized")
        if observed.cancelled:
            raise CoordinatorError("case_cancelled")
        if revision != snapshot.request_revision:
            raise CoordinatorError("case_changed")
        now = time.time_ns() // 1_000_000
        if snapshot.deadline_at_ms <= now:
            raise CoordinatorError("expired")
        if snapshot.deadline_at_ms - now > MAX_DEADLINE_WINDOW_MS:
            raise CoordinatorError("invalid_input")
        self._check(call)
        call.writing = True
        try:
            accepted = await self._executions.submit(
                idempotency_key=snapshot.delegation_id,
                payload=WorkPayload(
                    CAPABILITY, self._codec.encode_request(snapshot), snapshot.deadline_at_ms
                ),
            )
        except WorkError as error:
            if error.code not in {"identity_conflict", "acknowledgement_unknown"}:
                raise
            # Never resubmit after an uncertain commit. Inspect the original key.
            try:
                reconciled = await self._executions.find(idempotency_key=snapshot.delegation_id)
            except WorkError:
                raise CoordinatorError("acknowledgement_unknown") from None
            if reconciled is None:
                raise CoordinatorError(error.code) from None
            view = self._view(reconciled)
            _same_input(view.request, snapshot, self._codec, identity)
            return _Submission[RequestT](view, False)
        if type(accepted) is not WorkSubmission or type(accepted.created) is not bool:
            raise CoordinatorError("invalid_stored_state")
        view = self._view(accepted.record)
        if accepted.created and self._codec.encode_request(
            view.request
        ) != self._codec.encode_request(snapshot):
            raise CoordinatorError("invalid_stored_state")
        _same_input(view.request, snapshot, self._codec, identity)
        return _Submission[RequestT](view, accepted.created)

    async def _find_request(self, delegation_id: str) -> _AcceptedView[RequestT] | None:
        try:
            key = identifier(delegation_id)
        except ContractError:
            raise CoordinatorError("invalid_input") from None

        async def read(_call: _Call) -> _AcceptedView[RequestT] | None:
            value = await self._executions.find(idempotency_key=key)
            if value is None:
                return None
            view = self._view(value)
            if view.record.idempotency_key != key:
                raise CoordinatorError("invalid_stored_state")
            return view

        return await self._run("find", read)

    async def _get_request(self, work_id: str) -> _AcceptedView[RequestT]:
        work_id = _uuid(work_id)

        async def read(_call: _Call) -> _AcceptedView[RequestT]:
            view = self._view(await self._executions.get(work_id=work_id))
            if view.record.work_id != work_id:
                raise CoordinatorError("invalid_stored_state")
            return view

        return await self._run("get", read)

    async def cancel(self, work_id: str, command_id: str) -> WorkCancellation:
        work_id = _uuid(work_id)
        try:
            command = identifier(command_id)
        except ContractError:
            raise CoordinatorError("invalid_input") from None

        async def write(call: _Call) -> WorkCancellation:
            view = self._view(await self._executions.get(work_id=work_id))
            if view.record.work_id != work_id:
                raise CoordinatorError("invalid_stored_state")
            self._check(call)
            call.writing = True
            value = await self._executions.cancel(work_id=work_id, command_id=command)
            if type(value) is not WorkCancellation:
                raise CoordinatorError("invalid_stored_state")
            try:
                copied = WorkCancellation(
                    value.cancellation_id,
                    value.work_id,
                    value.command_id,
                    value.requested_at_ms,
                    value.disposition,
                )
            except WorkError:
                raise CoordinatorError("invalid_stored_state") from None
            if copied.work_id != work_id or copied.command_id != command:
                raise CoordinatorError("invalid_stored_state")
            return copied

        return await self._run("cancel", write)

    async def _run(
        self,
        operation: Literal["submit", "find", "get", "cancel"],
        invoke: Callable[[_Call], Awaitable[T]],
    ) -> T:
        loop = self._bind()
        if self._closed:
            raise CoordinatorError("closed")
        self._require_execution_scope()
        if len(self._calls) >= self._maximum:
            self._counts["capacity_rejected"] += 1
            raise CoordinatorError("capacity")
        call = _Call(operation, loop.time() + self._timeout)
        self._calls.add(call)
        self._counts["started"] += 1

        async def owned() -> T:
            code, outcome = "ok", "succeeded"
            try:
                return await invoke(call)
            except CoordinatorError as error:
                code, outcome = error.code, "failed"
                raise
            except WorkError as error:
                code, outcome = (
                    error.code if error.code in _WORK_CODES else "internal_error",
                    "failed",
                )
                raise CoordinatorError(cast(CoordinatorCode, code)) from None
            except asyncio.CancelledError:
                code, outcome = "request_aborted", "failed"
                raise
            except Exception:  # noqa: BLE001 - one public port containment boundary
                code, outcome = "internal_error", "failed"
                raise CoordinatorError("internal_error") from None
            finally:
                self._counts[outcome] += 1
                try:
                    LOGGER.info(
                        "delegation_port",
                        extra={
                            "event": "delegation_port",
                            "operation": operation,
                            "outcome": outcome,
                            "code": code,
                        },
                    )
                except Exception:  # noqa: BLE001 - telemetry cannot change acceptance
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
            raise CoordinatorError(
                "acknowledgement_unknown" if call.writing else "deadline_exceeded"
            ) from None
        except asyncio.CancelledError:
            call.abandoned = True
            self._counts["cancelled_waiters"] += 1
            raise

    async def close(self) -> None:
        loop = self._bind()
        self._closed = True
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
                try:
                    await self._executions.close()
                except Exception:  # noqa: BLE001 - close never serializes private adapter failures
                    raise CoordinatorError("cleanup_incomplete") from None

            self._close_task = asyncio.create_task(finish())

            def closed(completed: asyncio.Task[None]) -> None:
                if not completed.cancelled():
                    completed.exception()

            self._close_task.add_done_callback(closed)
        deadline = loop.time() + self._cleanup
        try:
            async with asyncio.timeout_at(deadline):
                await asyncio.shield(self._close_task)
        except TimeoutError:
            raise CoordinatorError("cleanup_incomplete") from None
        if self._calls or loop.time() > deadline:
            raise CoordinatorError("cleanup_incomplete")

    async def __aenter__(self) -> Self:
        self._bind()
        if self._closed:
            raise CoordinatorError("closed")
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()


class DelegationCoordinator(_CoordinatorCore[DelegationRequest, DelegationResult]):
    """Original v1-only facade over the shared bounded acceptance owner."""

    def __init__(
        self,
        *,
        executions: TaskExecutionPort,
        scope: Scope,
        case_authority: CaseAuthorityPort,
        max_active: int = 4,
        timeout_ms: int = 5000,
        cleanup_ms: int = 1000,
    ) -> None:
        super().__init__(
            executions=executions,
            codec=V1_CODEC,
            scope=scope,
            case_authority=case_authority,
            max_active=max_active,
            timeout_ms=timeout_ms,
            cleanup_ms=cleanup_ms,
        )

    async def submit(self, request: DelegationRequest) -> DelegationSubmission:
        value = await self._submit_request(request)
        return DelegationSubmission(
            DelegationView(value.view.record, value.view.request), value.created
        )

    async def find(self, delegation_id: str) -> DelegationView | None:
        value = await self._find_request(delegation_id)
        return None if value is None else DelegationView(value.record, value.request)

    async def get(self, work_id: str) -> DelegationView:
        value = await self._get_request(work_id)
        return DelegationView(value.record, value.request)
