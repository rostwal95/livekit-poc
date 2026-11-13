"""Explicit durable policy-v2 facades over P1; no projection or action extension."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from continuity_lab.execution_api import AttemptResult, ExecutionObservation, ExecutionPort
from continuity_lab.work_api import TaskExecutionPort, WorkRecord

from ._policy_codec import FIXED_CODEC, _FixedInvocation
from .contracts import ContractError, Scope
from .coordinator import CaseAuthorityPort, _CoordinatorCore
from .fixed_policy import FixedPolicyResultObservation, _snapshot_fixed_policy_pair
from .fixed_policy_contracts import FixedPolicyRequest, FixedPolicyResult
from .runner import Applicability, DelegationRunError, _RunnerCore
from .security import EvidenceRecord

__all__ = [
    "FixedPolicyCoordinator",
    "FixedPolicyExecutionView",
    "FixedPolicyInvocationPort",
    "FixedPolicyResultObservation",
    "FixedPolicyRun",
    "FixedPolicyRunner",
    "FixedPolicySubmission",
    "FixedPolicyView",
]


class FixedPolicyInvocationPort(Protocol):
    """Verified historical observation; P1 remains the sole execution authority."""

    async def invoke_observed(
        self, request: FixedPolicyRequest, *, evidence: tuple[EvidenceRecord, ...]
    ) -> FixedPolicyResultObservation: ...
    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class FixedPolicyView:
    record: WorkRecord
    request: FixedPolicyRequest = field(repr=False)


@dataclass(frozen=True, slots=True)
class FixedPolicySubmission:
    view: FixedPolicyView
    created: bool


@dataclass(frozen=True, slots=True)
class FixedPolicyExecutionView:
    execution: ExecutionObservation
    request: FixedPolicyRequest = field(repr=False)
    result: FixedPolicyResult | None = field(repr=False)
    applicability: Applicability


@dataclass(frozen=True, slots=True)
class FixedPolicyRun:
    view: FixedPolicyExecutionView
    invoked: bool
    recorded: AttemptResult | None = field(default=None, repr=False)


class FixedPolicyCoordinator(_CoordinatorCore[FixedPolicyRequest, FixedPolicyResult]):
    """Opt in to strict v2 acceptance with the original P1 identity and limits."""

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
            codec=FIXED_CODEC,
            scope=scope,
            case_authority=case_authority,
            max_active=max_active,
            timeout_ms=timeout_ms,
            cleanup_ms=cleanup_ms,
        )

    async def submit(self, request: FixedPolicyRequest) -> FixedPolicySubmission:
        value = await self._submit_request(request)
        return FixedPolicySubmission(
            FixedPolicyView(value.view.record, value.view.request), value.created
        )

    async def find(self, delegation_id: str) -> FixedPolicyView | None:
        value = await self._find_request(delegation_id)
        return None if value is None else FixedPolicyView(value.record, value.request)

    async def get(self, work_id: str) -> FixedPolicyView:
        value = await self._get_request(work_id)
        return FixedPolicyView(value.record, value.request)


class FixedPolicyRunner(_RunnerCore[FixedPolicyRequest, FixedPolicyResult]):
    """Opt in to verified v2 execution; issue/commit/replay ownership is shared."""

    def __init__(
        self,
        *,
        executions: ExecutionPort,
        scope: Scope,
        owner_id: str,
        specialist: FixedPolicyInvocationPort,
        case_authority: CaseAuthorityPort,
        evidence: tuple[EvidenceRecord, ...],
        max_active: int = 1,
        timeout_ms: int = 5000,
        cleanup_ms: int = 1000,
    ) -> None:
        try:
            if type(evidence) is not tuple or len(evidence) != 2:
                raise ContractError()
            copied = _snapshot_fixed_policy_pair(evidence)
            if any(
                item.reference.media_type != "application/json" or len(item.body) > 4096
                for item in copied
            ):
                raise ContractError()
        except (ContractError, AttributeError, TypeError, ValueError):
            raise DelegationRunError("invalid_input") from None
        super().__init__(
            executions=executions,
            codec=FIXED_CODEC,
            scope=scope,
            owner_id=owner_id,
            specialist=_FixedInvocation(specialist, copied),
            case_authority=case_authority,
            evidence=copied,
            max_active=max_active,
            timeout_ms=timeout_ms,
            cleanup_ms=cleanup_ms,
        )

    async def run_once(self, work_id: str, command_id: str) -> FixedPolicyRun:
        value = await self._run_once_request(work_id, command_id)
        view = value.view
        return FixedPolicyRun(
            FixedPolicyExecutionView(view.execution, view.request, view.result, view.applicability),
            value.invoked,
            value.recorded,
        )

    async def inspect(self, work_id: str) -> FixedPolicyExecutionView:
        value = await self._inspect_request(work_id)
        return FixedPolicyExecutionView(
            value.execution, value.request, value.result, value.applicability
        )
