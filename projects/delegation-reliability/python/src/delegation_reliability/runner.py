"""One explicitly requested, P1-issued read-only invocation; no queue or retry loop."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Generic, Literal, Protocol, Self, TypeVar, cast
from uuid import UUID

from continuity_lab.execution_api import (
    AttemptResult,
    ExecutionObservation,
    ExecutionPort,
    Issuance,
    IssuedAttempt,
)
from continuity_lab.work_api import WorkError, WorkPayload, WorkRecord, WorkScope

from ._policy_codec import (
    V1_CODEC,
    RequestT,
    ResultT,
    _Invocation,
    _ObservedResult,
    _PolicyCodec,
    _V1Invocation,
)
from .contracts import (
    CAPABILITY,
    MAX_TIMESTAMP_MS,
    Attempt,
    ContractError,
    DelegationRequest,
    DelegationResult,
    EvidenceRef,
    Scope,
    identifier,
    integer,
)
from .coordinator import CaseAuthorityPort, CaseSnapshot
from .http_client import SpecialistHttpError, SpecialistResultObservation
from .security import EvidenceRecord, EvidenceRegistry

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
T = TypeVar("T")
RunnerCode = Literal[
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
    "transport_unknown",
    "request_aborted",
    "deadline_exceeded",
    "internal_error",
]
_CODES = frozenset(
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
        "invalid_stored_state",
        "invalid_result",
        "transport_unknown",
        "request_aborted",
        "deadline_exceeded",
        "internal_error",
    }
)
Applicability = Literal[
    "missing",
    "candidate",
    "clarification",
    "outdated",
    "case_cancelled",
    "expired",
    "execution_ineligible",
    "unavailable",
]


class DelegationRunError(RuntimeError):
    """Fixed safe public codes; neither a retry instruction nor remote-stop proof."""

    def __init__(self, code: RunnerCode) -> None:
        self.code = code if type(code) is str and code in _CODES else "internal_error"
        super().__init__(self.code)


class SpecialistInvocationPort(Protocol):
    """Bounded observation only; the P1 permit owns durable execution identity."""

    async def invoke_observed(self, request: DelegationRequest) -> SpecialistResultObservation: ...
    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class DelegationExecutionView:
    execution: ExecutionObservation
    request: DelegationRequest = field(repr=False)
    result: DelegationResult | None = field(repr=False)
    applicability: Applicability


@dataclass(frozen=True, slots=True)
class DelegationRun:
    view: DelegationExecutionView
    invoked: bool
    recorded: AttemptResult | None = field(default=None, repr=False)


@dataclass(eq=False, slots=True)
class _Call:
    operation: Literal["run", "inspect"]
    deadline: float
    abandoned: bool = False
    writing: bool = False
    invoking: bool = False
    task: asyncio.Task[object] | None = field(default=None, repr=False)


def _uuid(value: str) -> str:
    if type(value) is not str or len(value) != 36:
        raise DelegationRunError("invalid_input")
    try:
        parsed = UUID(value)
    except ValueError:
        raise DelegationRunError("invalid_input") from None
    if parsed.version != 4 or str(parsed) != value:
        raise DelegationRunError("invalid_input")
    return value


def _wire_attempt_id(attempt_id: str) -> str:
    """P3 identifiers start with a letter; bind every UUID deterministically."""
    return "attempt_" + UUID(_uuid(attempt_id)).hex


def _record_with_codec(
    value: WorkRecord, scope: Scope, work_id: str, codec: _PolicyCodec[RequestT, ResultT]
) -> tuple[WorkRecord, RequestT]:
    try:
        if (
            type(value) is not WorkRecord
            or type(value.scope) is not WorkScope
            or type(value.payload) is not WorkPayload
        ):
            raise DelegationRunError("invalid_stored_state")
        record = WorkRecord(
            value.work_id,
            WorkScope(value.scope.tenant_id, value.scope.account_id),
            value.idempotency_key,
            WorkPayload(value.payload.operation, value.payload.body, value.payload.deadline_at_ms),
            value.accepted_at_ms,
            value.cancel_requested,
            value.status,
        )
        if (
            type(value.payload.sha256) is not str
            or value.payload.sha256 != hashlib.sha256(record.payload.body).hexdigest()
        ):
            raise DelegationRunError("invalid_stored_state")
        request = codec.parse_request(record.payload.body)
        if (
            record.work_id != work_id
            or record.scope != WorkScope(scope.tenant_id, scope.account_id)
            or request.scope != scope
            or record.idempotency_key != request.delegation_id
            or record.payload.operation != CAPABILITY
            or record.payload.deadline_at_ms != request.deadline_at_ms
            or codec.encode_request(request) != record.payload.body
        ):
            raise DelegationRunError("invalid_stored_state")
        return record, request
    except (ContractError, WorkError, AttributeError, TypeError, ValueError):
        raise DelegationRunError("invalid_stored_state") from None


def _attempt_with_codec(
    value: IssuedAttempt, scope: Scope, record: WorkRecord, codec: _PolicyCodec[RequestT, ResultT]
) -> IssuedAttempt:
    try:
        if type(value) is not IssuedAttempt:
            raise DelegationRunError("invalid_stored_state")
        copied, _ = _record_with_codec(value.record, scope, record.work_id, codec)
        if (
            copied.scope != record.scope
            or copied.idempotency_key != record.idempotency_key
            or copied.payload != record.payload
            or copied.accepted_at_ms != record.accepted_at_ms
        ):
            raise DelegationRunError("invalid_stored_state")
        _uuid(value.attempt_id)
        _uuid(value.owner_id)
        identifier(value.command_id)
        integer(value.number, 1, 3)
        integer(value.epoch, 1, 3)
        integer(value.issued_at_ms, 0, MAX_TIMESTAMP_MS)
        integer(value.lease_until_ms, value.issued_at_ms + 1, MAX_TIMESTAMP_MS)
        return replace(value, record=copied)
    except (ContractError, WorkError, AttributeError, TypeError, ValueError):
        raise DelegationRunError("invalid_stored_state") from None


def _record(value: WorkRecord, scope: Scope, work_id: str) -> tuple[WorkRecord, DelegationRequest]:
    """Retain the strict v1 validator shared by existing completion adapters."""
    return _record_with_codec(value, scope, work_id, V1_CODEC)


def _attempt(value: IssuedAttempt, scope: Scope, record: WorkRecord) -> IssuedAttempt:
    """V1 completion remains sealed to its original request/result contract."""
    return _attempt_with_codec(value, scope, record, V1_CODEC)


@dataclass(frozen=True, slots=True)
class _ExecutionView(Generic[RequestT, ResultT]):
    execution: ExecutionObservation
    request: RequestT = field(repr=False)
    result: ResultT | None = field(repr=False)
    applicability: Applicability


@dataclass(frozen=True, slots=True)
class _RunResult(Generic[RequestT, ResultT]):
    view: _ExecutionView[RequestT, ResultT]
    invoked: bool
    recorded: AttemptResult | None = field(default=None, repr=False)


class _RunnerCore(Generic[RequestT, ResultT]):
    """Own finite port tasks and one explicit invocation per newly issued command.

    Both execution and specialist clients are owned and closed here. Case reads
    and immutable evidence are application composition. Caller cancellation keeps
    actual I/O capacity until settlement; after a call starts, known strict results
    may still be persisted as history. Replayed/ambiguous issuance never invokes.
    """

    def __init__(
        self,
        *,
        executions: ExecutionPort,
        codec: _PolicyCodec[RequestT, ResultT],
        scope: Scope,
        owner_id: str,
        specialist: _Invocation[RequestT, ResultT],
        case_authority: CaseAuthorityPort,
        evidence: tuple[EvidenceRecord, ...],
        max_active: int = 1,
        timeout_ms: int = 5000,
        cleanup_ms: int = 1000,
    ) -> None:
        self._codec: _PolicyCodec[RequestT, ResultT] = codec
        try:
            if type(scope) is not Scope:
                raise DelegationRunError("invalid_input")
            self._scope = Scope(identifier(scope.tenant_id), identifier(scope.account_id))
            self._owner = _uuid(owner_id)
            if type(evidence) is not tuple or not 1 <= len(evidence) <= 4:
                raise DelegationRunError("invalid_input")
            EvidenceRegistry(evidence)
            if any(item.scope != self._scope for item in evidence):
                raise DelegationRunError("unauthorized")
            self._evidence = tuple(
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
                for item in evidence
            )
            if sum(len(item.body) for item in self._evidence) > 16384:
                raise DelegationRunError("invalid_input")
        except (ContractError, AttributeError, TypeError, ValueError):
            raise DelegationRunError("invalid_input") from None
        if (
            type(max_active) is not int
            or not 1 <= max_active <= 4
            or type(timeout_ms) is not int
            or not 20 <= timeout_ms <= 10000
            or type(cleanup_ms) is not int
            or not 20 <= cleanup_ms <= 5000
        ):
            raise DelegationRunError("invalid_input")
        self._executions, self._cases = executions, case_authority
        self._specialist: _Invocation[RequestT, ResultT] = specialist
        self._require_scope()
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
            "invoked": 0,
            "not_reinvoked": 0,
            "capacity_rejected": 0,
            "timed_out_waiters": 0,
            "cancelled_waiters": 0,
            "telemetry_failed": 0,
        }

    def _require_scope(self) -> None:
        try:
            actual = self._executions.scope
            if type(actual) is not WorkScope or actual != WorkScope(
                self._scope.tenant_id, self._scope.account_id
            ):
                raise DelegationRunError("unauthorized")
        except DelegationRunError:
            raise
        except Exception:  # noqa: BLE001 - trusted composition is a fixed public boundary
            raise DelegationRunError("unauthorized") from None

    def _bind(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        if self._loop is not loop:
            raise DelegationRunError("invalid_input")
        return loop

    @property
    def pending_count(self) -> int:
        return len(self._calls)

    def metrics(self) -> MappingProxyType[str, int]:
        return MappingProxyType({**self._counts, "active": self.pending_count})

    @staticmethod
    def _check(call: _Call) -> None:
        if call.abandoned:
            raise DelegationRunError("request_aborted")
        if asyncio.get_running_loop().time() >= call.deadline:
            raise DelegationRunError("deadline_exceeded")

    async def _run_once_request(
        self, work_id: str, command_id: str
    ) -> _RunResult[RequestT, ResultT]:
        work_id = _uuid(work_id)
        try:
            command = identifier(command_id)
        except ContractError:
            raise DelegationRunError("invalid_input") from None
        return await self._run("run", lambda call: self._invoke(call, work_id, command))

    async def _invoke(
        self, call: _Call, work_id: str, command: str
    ) -> _RunResult[RequestT, ResultT]:
        self._require_scope()
        initial = await self._executions.observe(work_id=work_id)
        view = await self._view(initial, work_id)
        initial = view.execution
        if initial.result is not None and initial.result.disposition == "eligible_at_commit":
            self._counts["not_reinvoked"] += 1
            return _RunResult[RequestT, ResultT](view, False)
        self._check(call)
        self._require_scope()
        call.writing = True
        try:
            issued = await self._executions.issue(
                work_id=work_id, owner_id=self._owner, command_id=command
            )
        except WorkError as error:
            if error.code != "acknowledgement_unknown":
                raise
            self._require_scope()
            try:
                reconciled = await self._executions.find_issue(command_id=command)
            except WorkError:
                raise DelegationRunError("acknowledgement_unknown") from None
            if reconciled is None:
                raise DelegationRunError("acknowledgement_unknown") from None
            grant = _attempt_with_codec(reconciled, self._scope, view.execution.record, self._codec)
            if grant.command_id != command or grant.owner_id != self._owner:
                raise DelegationRunError("invalid_stored_state")
            self._counts["not_reinvoked"] += 1
            return _RunResult[RequestT, ResultT](await self._read(work_id), False)
        if type(issued) is not Issuance or type(issued.created) is not bool:
            raise DelegationRunError("invalid_stored_state")
        grant = _attempt_with_codec(issued.attempt, self._scope, view.execution.record, self._codec)
        if grant.command_id != command or grant.owner_id != self._owner:
            raise DelegationRunError("invalid_stored_state")
        if not issued.created:
            self._counts["not_reinvoked"] += 1
            return _RunResult[RequestT, ResultT](await self._read(work_id), False)
        self._check(call)
        self._require_scope()
        fresh = await self._executions.observe(work_id=work_id)
        fresh_view = await self._view(fresh, work_id)
        fresh = fresh_view.execution
        self._check(call)
        current = fresh.current_attempt
        if (
            fresh.status != "running"
            or fresh.record.cancel_requested
            or current is None
            or current.attempt_id != grant.attempt_id
            or current.owner_id != grant.owner_id
            or current.epoch != grant.epoch
            or current != grant
            or time.time_ns() // 1_000_000 >= grant.lease_until_ms
        ):
            raise DelegationRunError("expired")
        if fresh_view.request != view.request:
            raise DelegationRunError("invalid_stored_state")
        transport = self._codec.with_attempt(
            view.request, Attempt(_wire_attempt_id(grant.attempt_id), grant.number)
        )
        transport = self._codec.parse_request(self._codec.encode_request(transport))
        if transport.input_fingerprint != view.request.input_fingerprint:
            raise DelegationRunError("invalid_stored_state")
        call.invoking = True
        self._counts["invoked"] += 1
        try:
            observed = await self._specialist.invoke_observed(transport)
        except ContractError:
            raise DelegationRunError("invalid_result") from None
        try:
            if type(observed) is not _ObservedResult:
                raise DelegationRunError("invalid_result")
            result = self._codec.parse_result(self._codec.encode_result(observed.result))
            integer(observed.observed_at_ms, 0, MAX_TIMESTAMP_MS)
            if observed.timeliness != self._codec.match(transport, result, observed.observed_at_ms):
                raise DelegationRunError("invalid_result")
            facts = self._codec.verify(transport, result, self._evidence, observed.observed_at_ms)
            if observed.facts is not None and observed.facts != facts:
                raise DelegationRunError("invalid_result")
            body = self._codec.encode_result(result)
        except (ContractError, TypeError, ValueError, AttributeError):
            raise DelegationRunError("invalid_result") from None
        self._require_scope()
        try:
            committed = await self._executions.complete(attempt=grant, body=body)
        except WorkError as error:
            if error.code != "acknowledgement_unknown":
                raise
            self._require_scope()
            try:
                found_result = await self._executions.result(
                    work_id=work_id, attempt_id=grant.attempt_id
                )
            except WorkError:
                raise DelegationRunError("acknowledgement_unknown") from None
            if found_result is None:
                raise DelegationRunError("acknowledgement_unknown") from None
            committed = found_result
        self._result(committed, grant, transport)
        if committed.body != body:
            raise DelegationRunError("invalid_stored_state")
        recorded = AttemptResult(
            committed.work_id,
            committed.attempt_id,
            committed.body,
            committed.recorded_at_ms,
            committed.disposition,
        )
        return _RunResult[RequestT, ResultT](await self._read(work_id), True, recorded)

    async def _inspect_request(self, work_id: str) -> _ExecutionView[RequestT, ResultT]:
        work_id = _uuid(work_id)
        return await self._run("inspect", lambda _call: self._read(work_id))

    async def _read(self, work_id: str) -> _ExecutionView[RequestT, ResultT]:
        self._require_scope()
        return await self._view(await self._executions.observe(work_id=work_id), work_id)

    def _result(self, value: AttemptResult, grant: IssuedAttempt, request: RequestT) -> ResultT:
        try:
            if type(value) is not AttemptResult or type(value.body) is not bytes:
                raise DelegationRunError("invalid_stored_state")
            if (value.work_id, value.attempt_id) != (grant.record.work_id, grant.attempt_id):
                raise DelegationRunError("invalid_stored_state")
            if value.sha256 != hashlib.sha256(value.body).hexdigest():
                raise DelegationRunError("invalid_stored_state")
            integer(value.recorded_at_ms, 0, MAX_TIMESTAMP_MS)
            if type(value.disposition) is not str or value.disposition not in {
                "eligible_at_commit",
                "cancelled",
                "expired",
                "superseded",
                "lease_expired",
            }:
                raise DelegationRunError("invalid_stored_state")
            result = self._codec.parse_result(value.body)
            if self._codec.encode_result(result) != value.body:
                raise DelegationRunError("invalid_stored_state")
            self._codec.verify(request, result, self._evidence, value.recorded_at_ms)
            return result
        except (ContractError, WorkError, AttributeError, TypeError, ValueError):
            raise DelegationRunError("invalid_stored_state") from None

    async def _view(
        self, value: ExecutionObservation, work_id: str
    ) -> _ExecutionView[RequestT, ResultT]:
        if type(value) is not ExecutionObservation:
            raise DelegationRunError("invalid_stored_state")
        record, request = _record_with_codec(value.record, self._scope, work_id, self._codec)
        try:
            integer(value.attempts_issued, 0, 3)
        except ContractError:
            raise DelegationRunError("invalid_stored_state") from None
        if type(value.status) is not str or value.status not in {
            "accepted",
            "running",
            "retryable",
            "exhausted",
            "result_recorded",
            "cancelled",
            "expired",
        }:
            raise DelegationRunError("invalid_stored_state")
        grant = (
            None
            if value.current_attempt is None
            else _attempt_with_codec(value.current_attempt, self._scope, record, self._codec)
        )
        try:
            copied_result = (
                None
                if value.result is None
                else AttemptResult(
                    value.result.work_id,
                    value.result.attempt_id,
                    value.result.body,
                    value.result.recorded_at_ms,
                    value.result.disposition,
                )
            )
            value = ExecutionObservation(
                record, grant, copied_result, value.attempts_issued, value.status
            )
        except (WorkError, AttributeError, TypeError, ValueError):
            raise DelegationRunError("invalid_stored_state") from None
        result = None
        applicability: Applicability = "missing"
        if value.result is not None:
            if grant is None:
                raise DelegationRunError("invalid_stored_state")
            transport = self._codec.with_attempt(
                request, Attempt(_wire_attempt_id(grant.attempt_id), grant.number)
            )
            result = self._result(value.result, grant, transport)
            now = time.time_ns() // 1_000_000
            facts = self._codec.verify(transport, result, self._evidence, now)
            if record.cancel_requested:
                applicability = "execution_ineligible"
            elif facts == "expired":
                applicability = "expired"
            elif value.result.disposition != "eligible_at_commit":
                applicability = "execution_ineligible"
            else:
                try:
                    case = await self._cases.snapshot(case_id=request.case_id)
                    if (
                        type(case) is not CaseSnapshot
                        or case.scope != self._scope
                        or case.case_id != request.case_id
                        or type(case.cancelled) is not bool
                        or type(case.request_revision) is not int
                        or case.request_revision < 1
                    ):
                        raise DelegationRunError("invalid_stored_state")
                    if case.cancelled:
                        applicability = "case_cancelled"
                    elif case.request_revision != request.request_revision:
                        applicability = "outdated"
                    else:
                        applicability = cast(Applicability, facts)
                except Exception:  # noqa: BLE001 - unavailable read cannot invent current authority
                    applicability = "unavailable"
        return _ExecutionView[RequestT, ResultT](value, request, result, applicability)

    async def _run(
        self, operation: Literal["run", "inspect"], invoke: Callable[[_Call], Awaitable[T]]
    ) -> T:
        loop = self._bind()
        if self._closed:
            raise DelegationRunError("closed")
        self._require_scope()
        if len(self._calls) >= self._maximum:
            self._counts["capacity_rejected"] += 1
            raise DelegationRunError("capacity")
        call = _Call(operation, loop.time() + self._timeout)
        self._calls.add(call)
        self._counts["started"] += 1

        async def owned() -> T:
            code, outcome = "ok", "succeeded"
            try:
                return await invoke(call)
            except DelegationRunError as error:
                code, outcome = error.code, "failed"
                raise
            except WorkError as error:
                code, outcome = error.code if error.code in _CODES else "internal_error", "failed"
                raise DelegationRunError(cast(RunnerCode, code)) from None
            except (SpecialistHttpError, ContractError):
                code, outcome = "transport_unknown", "failed"
                raise DelegationRunError("transport_unknown") from None
            except asyncio.CancelledError:
                code, outcome = "request_aborted", "failed"
                raise
            except Exception:  # noqa: BLE001 - one public containment boundary
                code, outcome = "internal_error", "failed"
                raise DelegationRunError("internal_error") from None
            finally:
                self._counts[outcome] += 1
                try:
                    LOGGER.info(
                        "delegation_run",
                        extra={
                            "event": "delegation_run",
                            "operation": operation,
                            "code": code,
                            "outcome": outcome,
                        },
                    )
                except Exception:  # noqa: BLE001 - telemetry cannot change persisted truth
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
            raise DelegationRunError(
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
            if not call.invoking:
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
                    self._specialist.close(), self._executions.close(), return_exceptions=True
                )
                if any(isinstance(outcome, BaseException) for outcome in outcomes):
                    raise DelegationRunError("cleanup_incomplete")

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
            raise DelegationRunError("cleanup_incomplete") from None
        if self._calls or loop.time() >= deadline:
            raise DelegationRunError("cleanup_incomplete")

    async def __aenter__(self) -> Self:
        self._bind()
        if self._closed:
            raise DelegationRunError("closed")
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()


class DelegationRunner(_RunnerCore[DelegationRequest, DelegationResult]):
    """Original v1-only runner; one unchanged bounded durable owner engine."""

    def __init__(
        self,
        *,
        executions: ExecutionPort,
        scope: Scope,
        owner_id: str,
        specialist: SpecialistInvocationPort,
        case_authority: CaseAuthorityPort,
        evidence: tuple[EvidenceRecord, ...],
        max_active: int = 1,
        timeout_ms: int = 5000,
        cleanup_ms: int = 1000,
    ) -> None:
        super().__init__(
            executions=executions,
            codec=V1_CODEC,
            scope=scope,
            owner_id=owner_id,
            specialist=_V1Invocation(specialist),
            case_authority=case_authority,
            evidence=evidence,
            max_active=max_active,
            timeout_ms=timeout_ms,
            cleanup_ms=cleanup_ms,
        )

    async def run_once(self, work_id: str, command_id: str) -> DelegationRun:
        value = await self._run_once_request(work_id, command_id)
        view = value.view
        return DelegationRun(
            DelegationExecutionView(view.execution, view.request, view.result, view.applicability),
            value.invoked,
            value.recorded,
        )

    async def inspect(self, work_id: str) -> DelegationExecutionView:
        value = await self._inspect_request(work_id)
        return DelegationExecutionView(
            value.execution, value.request, value.result, value.applicability
        )
