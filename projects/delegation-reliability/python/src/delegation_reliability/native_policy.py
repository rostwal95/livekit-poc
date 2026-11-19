"""One opt-in SDK background call over public durable fixed-policy authority.

SDK waiting, local I/O ownership, immutable results and as-of applicability remain
separate. No queue, retry, business cancellation or mutation is introduced.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Literal, Protocol, cast
from uuid import UUID

from livekit.agents import Agent, RunContext, ToolError, function_tool, llm

from continuity_lab.execution_api import ExecutionObservation
from continuity_lab.work_api import WorkRecord, WorkScope

from .contracts import (
    CAPABILITY,
    MAX_TIMESTAMP_MS,
    Attempt,
    ContractError,
    canonical,
    decode,
    digest,
    identifier,
    integer,
    object_fields,
)
from .coordinator import CoordinatorError
from .fixed_policy import _snapshot_fixed_policy_pair, verify_fixed_policy_facts
from .fixed_policy_contracts import (
    FixedPolicyRequest,
    encode_fixed_policy_request,
    encode_fixed_policy_result,
    parse_fixed_policy_request,
)
from .fixed_policy_execution import (
    FixedPolicyExecutionView,
    FixedPolicyRun,
    FixedPolicySubmission,
    FixedPolicyView,
)
from .runner import DelegationRunError
from .security import EvidenceRecord

__all__ = [
    "NativePolicyAgent",
    "NativePolicyApplication",
    "NativePolicyError",
    "NativePolicyObservation",
    "encode_native_policy_observation",
    "parse_native_policy_observation",
]

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
MAX_OBSERVATION_BYTES = 4096
NativePolicyCode = Literal[
    "invalid_input",
    "capacity",
    "closed",
    "cleanup_incomplete",
    "acknowledgement_unknown",
    "unavailable",
    "invalid_observation",
]
NativePolicyState = Literal["no_work", "work", "result", "outdated", "unknown"]
_WAITER = {"idle", "waiting", "returned", "stopped_waiting"}
_APPLICABILITY = {
    "missing",
    "candidate",
    "clarification",
    "outdated",
    "case_cancelled",
    "expired",
    "execution_ineligible",
    "unavailable",
}
_ERROR = {
    "read_unavailable",
    "capacity",
    "acknowledgement_unknown",
    "closed",
    "invalid_observation",
}
_DISPOSITION = {"eligible_at_commit", "cancelled", "expired", "superseded", "lease_expired"}
_STATUS = {
    "accepted",
    "running",
    "retryable",
    "exhausted",
    "result_recorded",
    "cancelled",
    "expired",
}


class NativePolicyError(RuntimeError):
    """Finite safe code, never external exception text or tool instructions."""

    def __init__(self, code: NativePolicyCode) -> None:
        allowed = {
            "invalid_input",
            "capacity",
            "closed",
            "cleanup_incomplete",
            "acknowledgement_unknown",
            "unavailable",
            "invalid_observation",
        }
        self.code: NativePolicyCode = (
            code if type(code) is str and code in allowed else "invalid_input"
        )
        super().__init__(self.code)


def _enum(value: object, allowed: set[str]) -> str:
    if type(value) is not str or value not in allowed:
        raise ContractError()
    return value


def _uuid(value: object) -> str:
    if type(value) is not str:
        raise ContractError()
    try:
        parsed = UUID(value)
    except ValueError:
        raise ContractError() from None
    if parsed.version != 4 or str(parsed) != value:
        raise ContractError()
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise ContractError()
    return value


def _reference(value: object, *, role: str) -> dict[str, object]:
    ref = object_fields(value, {"role", "source_id", "version", "sha256", "byte_length"})
    if ref["role"] != role:
        raise ContractError()
    identifier(ref["source_id"])
    identifier(ref["version"])
    digest(ref["sha256"])
    integer(ref["byte_length"], 1, 4096)
    return ref


def _validated(payload: bytes) -> bytes:
    obj = object_fields(
        decode(payload, MAX_OBSERVATION_BYTES),
        {
            "schema_version",
            "kind",
            "binding",
            "state",
            "tool_waiter",
            "owned_run",
            "work",
            "attempt",
            "result",
            "applicability",
            "app_read_completed_at_ms",
            "error",
            "consistency",
        },
    )
    if (
        type(obj["schema_version"]) is not int
        or obj["schema_version"] != 1
        or (obj["kind"] != "native-policy.observation" or obj["consistency"] != "as_of_non_atomic")
    ):
        raise ContractError()
    binding = object_fields(
        obj["binding"],
        {
            "scope",
            "delegation_id",
            "case_id",
            "request_revision",
            "input_fingerprint",
            "sources",
        },
    )
    scope = object_fields(binding["scope"], {"tenant_id", "account_id"})
    identifier(scope["tenant_id"])
    identifier(scope["account_id"])
    identifier(binding["delegation_id"])
    identifier(binding["case_id"])
    integer(binding["request_revision"], 1, 1_000_000)
    digest(binding["input_fingerprint"])
    refs = binding["sources"]
    if type(refs) is not list or len(refs) != 2:
        raise ContractError()
    policy, facts = _reference(refs[0], role="policy"), _reference(refs[1], role="facts")
    if policy["source_id"] == facts["source_id"]:
        raise ContractError()
    state = _enum(obj["state"], {"no_work", "work", "result", "outdated", "unknown"})
    _enum(obj["tool_waiter"], _WAITER)
    _boolean(obj["owned_run"])
    integer(obj["app_read_completed_at_ms"], 0, MAX_TIMESTAMP_MS)
    if obj["error"] is not None:
        _enum(obj["error"], _ERROR)
    if state in {"no_work", "unknown"}:
        if any(obj[key] is not None for key in ("work", "attempt", "result", "applicability")):
            raise ContractError()
        if (state == "unknown") != (obj["error"] is not None):
            raise ContractError()
    else:
        if obj["error"] is not None:
            raise ContractError()
        work = object_fields(
            obj["work"],
            {
                "work_id",
                "request_sha256",
                "accepted_at_ms",
                "status",
                "cancel_requested",
            },
        )
        _uuid(work["work_id"])
        digest(work["request_sha256"])
        integer(work["accepted_at_ms"], 0, MAX_TIMESTAMP_MS)
        _enum(work["status"], _STATUS)
        _boolean(work["cancel_requested"])
        applicability = _enum(obj["applicability"], _APPLICABILITY)
        attempt = None
        if obj["attempt"] is not None:
            attempt = object_fields(obj["attempt"], {"attempt_id", "number"})
            _uuid(attempt["attempt_id"])
            integer(attempt["number"], 1, 3)
        if state == "work":
            if (
                obj["result"] is not None
                or applicability != "missing"
                or work["status"] == "result_recorded"
            ):
                raise ContractError()
        else:
            if (
                attempt is None
                or applicability == "missing"
                or ((state == "outdated") != (applicability == "outdated"))
            ):
                raise ContractError()
            result = object_fields(
                obj["result"],
                {
                    "attempt_id",
                    "wire_attempt_id",
                    "sha256",
                    "recorded_at_ms",
                    "disposition",
                    "eligible",
                    "uncertainty",
                    "rule_refs",
                    "fact_refs",
                },
            )
            if result["attempt_id"] != attempt["attempt_id"] or result["wire_attempt_id"] != (
                "attempt_" + _uuid(attempt["attempt_id"]).replace("-", "")
            ):
                raise ContractError()
            digest(result["sha256"])
            integer(result["recorded_at_ms"], 0, MAX_TIMESTAMP_MS)
            _enum(result["disposition"], _DISPOSITION)
            if (
                work["status"] == "result_recorded"
                and result["disposition"] != "eligible_at_commit"
            ):
                raise ContractError()
            if result["eligible"] is not None:
                _boolean(result["eligible"])
            uncertainty = _enum(result["uncertainty"], {"none", "missing", "conflicting"})
            rules, witnesses = result["rule_refs"], result["fact_refs"]
            if (
                type(rules) is not list
                or len(rules) != 1
                or type(witnesses) is not list
                or len(witnesses) > 2
            ):
                raise ContractError()
            rule = object_fields(
                rules[0], {"source_id", "version", "sha256", "rule_id", "minimum_notice_days"}
            )
            if any(rule[key] != policy[key] for key in ("source_id", "version", "sha256")) or (
                rule["rule_id"] != "notice_minimum_days"
                or type(rule["minimum_notice_days"]) is not int
                or rule["minimum_notice_days"] != 7
            ):
                raise ContractError()
            identities, values = set(), set()
            for witness in witnesses:
                fact = object_fields(
                    witness, {"source_id", "version", "sha256", "fact_id", "days_before_arrival"}
                )
                if any(fact[key] != facts[key] for key in ("source_id", "version", "sha256")):
                    raise ContractError()
                identities.add(identifier(fact["fact_id"]))
                values.add(integer(fact["days_before_arrival"], 0, 3650))
            if len(identities) != len(witnesses):
                raise ContractError()
            if uncertainty == "none":
                if (
                    not 1 <= len(witnesses) <= 2
                    or len(values) != 1
                    or result["eligible"] is not (next(iter(values)) >= 7)
                ):
                    raise ContractError()
            elif (
                result["eligible"] is not None
                or (uncertainty == "missing" and len(witnesses) != 0)
                or (uncertainty == "conflicting" and (len(witnesses) != 2 or len(values) != 2))
            ):
                raise ContractError()
    encoded = canonical(obj)
    if len(encoded) > MAX_OBSERVATION_BYTES:
        raise ContractError()
    return encoded


@dataclass(frozen=True, slots=True)
class NativePolicyObservation:
    """A copied closed read DTO; syntax does not grant factual or action authority."""

    payload: bytes = field(repr=False)

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "payload", _validated(self.payload))
        except (ContractError, AttributeError, TypeError, ValueError):
            raise NativePolicyError("invalid_observation") from None

    @property
    def state(self) -> NativePolicyState:
        return cast(NativePolicyState, self.to_wire()["state"])

    def to_wire(self) -> dict[str, object]:
        return cast(dict[str, object], decode(self.payload, MAX_OBSERVATION_BYTES))


def parse_native_policy_observation(payload: bytes) -> NativePolicyObservation:
    return NativePolicyObservation(payload)


def encode_native_policy_observation(value: NativePolicyObservation) -> bytes:
    if type(value) is not NativePolicyObservation:
        raise NativePolicyError("invalid_observation")
    return _validated(value.payload)


class _CoordinatorPort(Protocol):
    @property
    def pending_count(self) -> int: ...
    async def submit(self, request: FixedPolicyRequest) -> FixedPolicySubmission: ...
    async def find(self, delegation_id: str) -> FixedPolicyView | None: ...
    async def close(self) -> None: ...


class _RunnerPort(Protocol):
    @property
    def pending_count(self) -> int: ...
    async def run_once(self, work_id: str, command_id: str) -> FixedPolicyRun: ...
    async def inspect(self, work_id: str) -> FixedPolicyExecutionView: ...
    async def close(self) -> None: ...


class NativePolicyApplication:
    """One configured logical work, one shielded run and one reserved read lane.

    Supply an exclusively owned FixedPolicyRunner(max_active=2), a coordinator,
    and their immutable evidence. The application owns the two facades; the host
    owns its one SDK session, model, room and their shared case reader.
    """

    def __init__(
        self,
        *,
        coordinator: _CoordinatorPort,
        runner: _RunnerPort,
        request: FixedPolicyRequest,
        evidence: tuple[EvidenceRecord, ...],
        command_id: str,
        read_timeout_ms: int = 2000,
        cleanup_ms: int = 3000,
    ) -> None:
        try:
            value = parse_fixed_policy_request(encode_fixed_policy_request(request))
            records = _snapshot_fixed_policy_pair(evidence)
            identifier(command_id)
            integer(read_timeout_ms, 20, 5000)
            integer(cleanup_ms, 20, 5000)
            if any(
                not any(
                    record.scope == value.scope and record.reference == ref for record in records
                )
                for ref in value.evidence
            ):
                raise ContractError()
        except (ContractError, AttributeError, TypeError, ValueError):
            raise NativePolicyError("invalid_input") from None
        self._coordinator, self._runner = coordinator, runner
        self._request, self._records, self._command = value, records, command_id
        self._read_timeout, self._cleanup = read_timeout_ms / 1000, cleanup_ms / 1000
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closed = self._attempted = self._submitting = self._reserved = False
        self._read_busy = self._read_abandoned = False
        self._waiter = "idle"
        self._run_task: asyncio.Task[FixedPolicyRun] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._counts = {
            "tool_started": 0,
            "tool_returned": 0,
            "tool_waiters_stopped": 0,
            "observations": 0,
            "read_failures": 0,
            "capacity_rejected": 0,
            "telemetry_failures": 0,
        }

    def _bind(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        if self._loop is not loop:
            raise NativePolicyError("invalid_input")
        return loop

    def _pending(self) -> tuple[int, int]:
        values = self._coordinator.pending_count, self._runner.pending_count
        if any(type(value) is not int or not 0 <= value <= 4 for value in values):
            raise NativePolicyError("invalid_observation")
        return values

    def _refresh_ownership(self) -> None:
        coordinator, runner = self._pending()
        if not self._submitting and not coordinator and not runner:
            if self._run_task is None or self._run_task.done():
                self._reserved = False
            if self._read_abandoned:
                self._read_busy = self._read_abandoned = False

    @property
    def binding(self) -> dict[str, object]:
        """Copied trusted configuration for mint/read pinning; no acceptance claim."""
        request = self._request
        return {
            "scope": {"tenant_id": request.scope.tenant_id, "account_id": request.scope.account_id},
            "delegation_id": request.delegation_id,
            "case_id": request.case_id,
            "request_revision": request.request_revision,
            "input_fingerprint": request.input_fingerprint,
            "sources": [
                {
                    "role": role,
                    "source_id": ref.source_id,
                    "version": ref.version,
                    "sha256": ref.sha256,
                    "byte_length": ref.byte_length,
                }
                for role, ref in zip(("policy", "facts"), request.evidence, strict=True)
            ],
        }

    def stop(self) -> None:
        """Stop new admission without pretending any owner has closed."""
        self._closed = True

    def metrics(self) -> Mapping[str, int]:
        self._refresh_ownership()
        coordinator, runner = self._pending()
        return MappingProxyType(
            {
                **self._counts,
                "owned_run": int(self._reserved),
                "read_reserved": int(self._read_busy),
                "coordinator_pending": coordinator,
                "runner_pending": runner,
                "closing": int(self._closed),
            }
        )

    def _emit(self, event: str, code: str = "ok") -> None:
        try:
            LOGGER.info("native_policy", extra={"event": event, "code": code})
        except Exception:  # noqa: BLE001 - Diagnostics never change ownership or authority.
            self._counts["telemetry_failures"] += 1

    def _same_request(self, value: FixedPolicyRequest) -> FixedPolicyRequest:
        copied = parse_fixed_policy_request(encode_fixed_policy_request(value))
        if (
            copied.input_fingerprint != self._request.input_fingerprint
            or copied.scope != self._request.scope
        ):
            raise NativePolicyError("invalid_observation")
        return copied

    def _checked_record(self, request: FixedPolicyRequest, record: WorkRecord) -> None:
        copied = self._same_request(request)
        if (
            type(record) is not WorkRecord
            or record.scope != WorkScope(copied.scope.tenant_id, copied.scope.account_id)
            or (
                record.idempotency_key != copied.delegation_id
                or record.payload.operation != CAPABILITY
                or record.payload.body != encode_fixed_policy_request(copied)
                or record.payload.deadline_at_ms != copied.deadline_at_ms
            )
        ):
            raise NativePolicyError("invalid_observation")
        _uuid(record.work_id)

    async def evaluate(self, ctx: RunContext[None]) -> NativePolicyObservation:
        """One accepted background call; repeated calls inspect the original identity."""
        self._bind()
        self._refresh_ownership()
        if self._closed:
            raise NativePolicyError("closed")
        if self._reserved:
            self._counts["capacity_rejected"] += 1
            raise NativePolicyError("capacity")
        if self._attempted:
            return await self.inspect_observed()
        self._attempted = self._reserved = self._submitting = True
        self._waiter = "waiting"
        self._counts["tool_started"] += 1
        try:
            try:
                accepted = await self._coordinator.submit(self._request)
            except CoordinatorError as error:
                # Capacity rejects acceptance. Permit a later explicit call with
                # the same frozen identity; retain actual pending ownership.
                # Unknown acceptance and post-acceptance failures stay read-only.
                if error.code == "capacity":
                    self._attempted = False
                raise
            if (
                type(accepted) is not FixedPolicySubmission
                or type(accepted.view) is not FixedPolicyView
            ):
                raise NativePolicyError("invalid_observation")
            self._checked_record(accepted.view.request, accepted.view.record)
            self._request = self._same_request(accepted.view.request)
            if self._closed:
                raise NativePolicyError("closed")
            work_id = accepted.view.record.work_id
            self._run_task = asyncio.create_task(
                self._runner.run_once(work_id, self._command), name="native-policy-run"
            )

            def observed(task: asyncio.Task[FixedPolicyRun]) -> None:
                if not task.cancelled():
                    task.exception()  # Consume the actual outcome, never release admission here.

            self._run_task.add_done_callback(observed)
            self._submitting = False
            self._emit("accepted")
            await ctx.update(
                {"schema_version": 1, "status": "pending", "work_id": work_id}, silent=True
            )
            observed_run = await asyncio.shield(self._run_task)
            if type(observed_run) is not FixedPolicyRun:
                raise NativePolicyError("invalid_observation")
            self._waiter = "returned"
            self._counts["tool_returned"] += 1
            self._refresh_ownership()
            self._counts["observations"] += 1
            # run_once already returns its validated public read view. A concurrent
            # card read owns the read lane; do not issue a redundant read here.
            return self._view_observation(observed_run.view, work_id)
        except asyncio.CancelledError:
            self._waiter = "stopped_waiting"
            self._counts["tool_waiters_stopped"] += 1
            self._emit("stopped_waiting", "request_aborted")
            raise
        except (CoordinatorError, DelegationRunError) as error:
            self._waiter = "stopped_waiting"
            self._counts["tool_waiters_stopped"] += 1
            code: NativePolicyCode = (
                "acknowledgement_unknown"
                if error.code == "acknowledgement_unknown"
                else "unavailable"
            )
            self._emit("stopped_waiting", code)
            raise NativePolicyError(code) from None
        except NativePolicyError:
            self._waiter = "stopped_waiting"
            raise
        except (ContractError, AttributeError, TypeError, ValueError):
            self._waiter = "stopped_waiting"
            raise NativePolicyError("invalid_observation") from None
        except Exception:  # noqa: BLE001 - Sanitize the public SDK progress/port boundary.
            self._waiter = "stopped_waiting"
            raise NativePolicyError("unavailable") from None
        finally:
            self._submitting = False
            self._refresh_ownership()

    def _wire(
        self,
        *,
        view: FixedPolicyExecutionView | None,
        state: NativePolicyState,
        error: str | None = None,
    ) -> NativePolicyObservation:
        binding = self.binding
        work: dict[str, object] | None = None
        attempt: dict[str, object] | None = None
        result: dict[str, object] | None = None
        applicability: str | None = None
        if view is not None:
            record = view.execution.record
            work = {
                "work_id": record.work_id,
                "request_sha256": record.payload.sha256,
                "accepted_at_ms": record.accepted_at_ms,
                "status": view.execution.status,
                "cancel_requested": record.cancel_requested,
            }
            grant = view.execution.current_attempt
            if grant is not None:
                attempt = {"attempt_id": grant.attempt_id, "number": grant.number}
            persisted, body = view.execution.result, view.result
            if persisted is not None and body is not None:
                result = {
                    "attempt_id": persisted.attempt_id,
                    "wire_attempt_id": body.attempt_id,
                    "sha256": persisted.sha256,
                    "recorded_at_ms": persisted.recorded_at_ms,
                    "disposition": persisted.disposition,
                    "eligible": body.eligible,
                    "uncertainty": body.uncertainty,
                    "rule_refs": [ref.to_wire() for ref in body.rule_refs],
                    "fact_refs": [ref.to_wire() for ref in body.fact_refs],
                }
            applicability = view.applicability
        return NativePolicyObservation(
            canonical(
                {
                    "schema_version": 1,
                    "kind": "native-policy.observation",
                    "binding": binding,
                    "state": state,
                    "tool_waiter": self._waiter,
                    "owned_run": self._reserved,
                    "work": work,
                    "attempt": attempt,
                    "result": result,
                    "applicability": applicability,
                    "app_read_completed_at_ms": time.time_ns() // 1_000_000,
                    "error": error,
                    "consistency": "as_of_non_atomic",
                }
            )
        )

    def _view_observation(
        self, view: FixedPolicyExecutionView, work_id: str
    ) -> NativePolicyObservation:
        if type(view) is not FixedPolicyExecutionView:
            raise NativePolicyError("invalid_observation")
        self._checked_record(view.request, view.execution.record)
        if (
            type(view.execution) is not ExecutionObservation
            or view.execution.record.work_id != work_id
            or ((view.execution.result is None) != (view.result is None))
        ):
            raise NativePolicyError("invalid_observation")
        ExecutionObservation(
            view.execution.record,
            view.execution.current_attempt,
            view.execution.result,
            view.execution.attempts_issued,
            view.execution.status,
        )
        if view.result is not None:
            grant, stored = view.execution.current_attempt, view.execution.result
            if (
                grant is None
                or stored is None
                or encode_fixed_policy_result(view.result) != stored.body
            ):
                raise NativePolicyError("invalid_observation")
            transport = replace(
                view.request,
                attempt=Attempt("attempt_" + grant.attempt_id.replace("-", ""), grant.number),
            )
            verify_fixed_policy_facts(
                transport,
                view.result,
                self._records,
                observed_at_ms=time.time_ns() // 1_000_000,
            )
        state: NativePolicyState = (
            "work"
            if view.result is None
            else "outdated"
            if view.applicability == "outdated"
            else "result"
        )
        return self._wire(view=view, state=state)

    async def inspect_observed(self) -> NativePolicyObservation:
        """One exact-work read; unknown reads never manufacture fresh authority fields."""
        self._bind()
        self._refresh_ownership()
        if self._closed:
            raise NativePolicyError("closed")
        if self._read_busy:
            self._counts["capacity_rejected"] += 1
            raise NativePolicyError("capacity")
        self._read_busy = True
        settled = False
        try:
            async with asyncio.timeout(self._read_timeout):
                accepted = await self._coordinator.find(self._request.delegation_id)
                if accepted is None:
                    settled = True
                    if self._attempted and self._coordinator.pending_count:
                        return self._wire(
                            view=None, state="unknown", error="acknowledgement_unknown"
                        )
                    return self._wire(view=None, state="no_work")
                if type(accepted) is not FixedPolicyView:
                    raise NativePolicyError("invalid_observation")
                self._checked_record(accepted.request, accepted.record)
                view = await self._runner.inspect(accepted.record.work_id)
                observed = self._view_observation(view, accepted.record.work_id)
                settled = True
                self._counts["observations"] += 1
                return observed
        except asyncio.CancelledError:
            self._read_abandoned = True
            raise
        except (CoordinatorError, DelegationRunError, TimeoutError) as error:
            self._read_abandoned = True
            self._counts["read_failures"] += 1
            code = (
                "acknowledgement_unknown"
                if isinstance(error, (CoordinatorError, DelegationRunError))
                and error.code == "acknowledgement_unknown"
                else "read_unavailable"
            )
            self._emit("read_failed", code)
            return self._wire(view=None, state="unknown", error=code)
        except (ContractError, AttributeError, TypeError, ValueError):
            raise NativePolicyError("invalid_observation") from None
        finally:
            if settled:
                self._read_busy = False
            else:
                self._read_abandoned = True
            self._refresh_ownership()

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
                outcomes = await asyncio.gather(
                    self._coordinator.close(), self._runner.close(), return_exceptions=True
                )
                task = self._run_task
                if task is not None and not task.done():
                    # Ports have already been asked to close; never block those attempts on the run.
                    await asyncio.wait({task}, timeout=self._cleanup)
                self._refresh_ownership()
                if (
                    any(isinstance(outcome, BaseException) for outcome in outcomes)
                    or self._reserved
                    or self._read_busy
                    or any(self._pending())
                ):
                    raise NativePolicyError("cleanup_incomplete")

            self._close_task = asyncio.create_task(finish(), name="native-policy-close")
            self._close_task.add_done_callback(
                lambda task: None if task.cancelled() else task.exception()
            )
        try:
            async with asyncio.timeout_at(loop.time() + self._cleanup):
                await asyncio.shield(self._close_task)
        except (TimeoutError, CoordinatorError, DelegationRunError):
            raise NativePolicyError("cleanup_incomplete") from None


class NativePolicyAgent(Agent):
    """One read-only business tool; SDK lifecycle cancellation stops its waiter only."""

    def __init__(self, application: NativePolicyApplication) -> None:
        if type(application) is not NativePolicyApplication:
            raise NativePolicyError("invalid_input")
        super().__init__(
            instructions=(
                "Use evaluate_policy only for the already configured read-only policy request. "
                "Pending means accepted work, not a result. Tool cancellation only stops waiting. "
                "Results and applicability are observations and never authorize a booking change."
            )
        )
        self.application = application

    @function_tool(on_duplicate="reject", flags=llm.ToolFlag.CANCELLABLE)
    async def evaluate_policy(self, ctx: RunContext[None]) -> str:
        """Observe the configured policy without changing a booking or sending a message."""
        try:
            observed = await self.application.evaluate(ctx)
        except NativePolicyError as error:
            message = (
                "A policy review is still owned; inspect its original result."
                if error.code == "capacity"
                else "The policy review is unavailable; inspect the configured observation."
            )
            raise ToolError(message) from None
        return canonical(
            {
                "schema_version": 1,
                "status": "completed" if observed.state in {"result", "outdated"} else "observed",
                "observation": observed.to_wire(),
            }
        ).decode()
