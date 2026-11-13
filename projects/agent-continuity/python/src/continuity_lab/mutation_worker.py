"""One cooperative mutation attempt with explicit external uncertainty.

The case authority commits consent. The effect store reserves dispatch before
this worker calls the independent supplier outside every database transaction.
A process restart reconciles only through declared supplier capabilities.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Protocol

from .case_models import ActionIntent, require_mutation_quote
from .effect_models import (
    EffectClaim,
    EffectFailure,
    EffectSnapshot,
    EffectState,
    MutationResult,
    require_result_binding,
)
from .execution_models import UnsupportedOperation
from .mutation_supplier import (
    MutationCapabilities,
    MutationConflict,
    MutationObservation,
    MutationRejected,
    MutationUnavailable,
)

LOGGER = logging.getLogger("continuity_lab.mutation_worker")
LOGGER.addHandler(logging.NullHandler())
_CODES = frozenset(
    {
        "execution_error",
        "execution_not_found",
        "transition_conflict",
        "unsupported_operation",
        "storage_unavailable",
        "invalid_stored_state",
        "capacity_exhausted",
        "mutation_rejected",
        "mutation_conflict",
        "dependency_unavailable",
        "schema_version_unsupported",
        "invalid_input",
        "supplier_rejected",
        "deadline_expired",
        "ambiguous_outcome",
        "attempts_exhausted",
    }
)


class WorkerSlotPort(Protocol):
    def worker_slot(self) -> AbstractContextManager[None]: ...


class MutationExecutionPort(Protocol):
    @property
    def executions(self) -> WorkerSlotPort: ...
    def worker_slot(self) -> AbstractContextManager[None]: ...
    def intent(self, *, scope_id: str, task_id: str) -> ActionIntent: ...
    def claim(self, *, scope_id: str, task_id: str) -> EffectClaim | None: ...
    def prepare_dispatch(self, claim: EffectClaim, *, absence_confirmed: bool) -> bool: ...
    def finish_success(self, claim: EffectClaim, result: MutationResult) -> EffectSnapshot: ...
    def finish_failure(self, claim: EffectClaim, code: EffectFailure) -> EffectSnapshot: ...
    def finish_uncertain(
        self, claim: EffectClaim, code: EffectFailure = EffectFailure.AMBIGUOUS_OUTCOME
    ) -> EffectSnapshot: ...
    def get(self, *, scope_id: str, task_id: str) -> EffectSnapshot | None: ...


class MutationSupplierPort(Protocol):
    @property
    def capabilities(self) -> MutationCapabilities: ...
    @property
    def provider_id(self) -> str: ...
    def lookup(self, intent: ActionIntent) -> MutationObservation | None: ...
    def apply(self, intent: ActionIntent) -> MutationObservation: ...


def _event(event: str, code: str = "ok") -> None:
    try:
        LOGGER.log(
            logging.ERROR if event == "mutation_worker_failed" else logging.INFO,
            event,
            extra={"event": event, "code": code},
        )
    except Exception:  # noqa: BLE001 - telemetry cannot alter external-effect truth
        return


def _code(error: Exception) -> str:
    try:
        candidate = getattr(error, "code", "unexpected_error")
        return candidate if type(candidate) is str and candidate in _CODES else "unexpected_error"
    except Exception:  # noqa: BLE001 - diagnostic metadata cannot replace an original failure
        return "unexpected_error"


class MutationWorker:
    """Run at most one newly reserved apply, or reconcile an existing effect.

    A stopped claim before reservation is positively undispatched. A reserved
    dispatch may have executed even if the old process returned no response.
    Noncooperating ambiguity becomes a durable uncertain result with no resend.
    """

    def __init__(
        self,
        effects: MutationExecutionPort,
        supplier: MutationSupplierPort,
        *,
        failpoint: Callable[[str], None] | None = None,
    ) -> None:
        if type(supplier.capabilities) is not MutationCapabilities:
            raise ValueError("A validated mutation supplier contract is required")
        self.effects, self.supplier, self.failpoint = effects, supplier, failpoint
        self.capabilities = supplier.capabilities

    def _hit(self, name: str) -> None:
        if self.failpoint is not None:
            self.failpoint(name)

    def run_one(self, *, scope_id: str, task_id: str) -> EffectSnapshot | None:
        try:
            existing = self.effects.get(scope_id=scope_id, task_id=task_id)
            if existing is not None and existing.state in {
                EffectState.SUCCEEDED,
                EffectState.FAILED,
                EffectState.UNCERTAIN,
                EffectState.CANCELLED,
            }:
                return existing
            committed = self.effects.intent(scope_id=scope_id, task_id=task_id)
            quote = require_mutation_quote(committed)
            if quote.supplier_id != self.supplier.provider_id:
                raise UnsupportedOperation(
                    "Configured supplier differs from the committed authority"
                )
            with self.effects.worker_slot():
                claim = self.effects.claim(scope_id=scope_id, task_id=task_id)
                if claim is None:
                    return self.effects.get(scope_id=scope_id, task_id=task_id)
                quote = require_mutation_quote(claim.intent)
                if quote.supplier_id != self.supplier.provider_id:
                    raise UnsupportedOperation(
                        "Configured supplier differs from the committed authority"
                    )
                self._hit("mutation_worker.after_claim")
                observation: MutationObservation | None = None
                if claim.may_have_dispatched and not (
                    self.capabilities.lookup and self.capabilities.idempotent
                ):
                    # Fixture inspection or a revision mismatch is not reliable
                    # evidence of this particular prior external outcome.
                    return self.effects.finish_uncertain(claim)
                if self.capabilities.lookup:
                    try:
                        observation = self.supplier.lookup(claim.intent)
                    except MutationUnavailable:
                        if claim.may_have_dispatched:
                            # Keep a cooperating reservation recoverable, with
                            # its existing finite manual attempt budget.
                            raise
                        return self.effects.finish_failure(
                            claim, EffectFailure.DEPENDENCY_UNAVAILABLE
                        )
                if observation is not None:
                    require_result_binding(observation.result, claim.intent)
                    _event("mutation_reconciled")
                    self._hit("mutation_worker.after_supplier_success")
                    value = self.effects.finish_success(claim, observation.result)
                    _event("mutation_worker_completed")
                    return value
                # A fresh/unreserved claim has not called apply. Reliable lookup
                # plus deduplication permits a prior reservation's same-key retry.
                absence_confirmed = not claim.may_have_dispatched or (
                    self.capabilities.lookup and self.capabilities.idempotent
                )
                if not self.effects.prepare_dispatch(claim, absence_confirmed=absence_confirmed):
                    return self.effects.get(scope_id=scope_id, task_id=task_id)
                self._hit("mutation_worker.after_dispatch_reserved")
                _event("mutation_dispatched")
                try:
                    observation = self.supplier.apply(claim.intent)
                except (MutationRejected, MutationConflict):
                    return self.effects.finish_failure(claim, EffectFailure.SUPPLIER_REJECTED)
                except MutationUnavailable:
                    if not (self.capabilities.lookup and self.capabilities.idempotent):
                        return self.effects.finish_uncertain(claim)
                    # One bounded reconciliation lookup can recover a lost
                    # response. Never issue a second apply in this invocation.
                    observation = self.supplier.lookup(claim.intent)
                    if observation is None:
                        raise
                    require_result_binding(observation.result, claim.intent)
                    _event("mutation_reconciled")
                require_result_binding(observation.result, claim.intent)
                self._hit("mutation_worker.after_supplier_success")
                value = self.effects.finish_success(claim, observation.result)
                _event("mutation_worker_completed")
                return value
        except Exception as error:
            _event("mutation_worker_failed", _code(error))
            raise
