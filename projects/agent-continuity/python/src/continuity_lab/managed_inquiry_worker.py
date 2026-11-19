"""One bounded, lookup-first inquiry attempt; no polling/sleeping timer loop."""

import logging
from collections.abc import Callable
from datetime import datetime

from .execution_models import UnsupportedOperation
from .lifecycle_models import LifecycleSnapshot
from .postgres_lifecycle import PostgresLifecycle
from .retry_policy import FailureClass, instant
from .supplier import InquirySupplierPort, SupplierRejected, SupplierUnavailable

LOGGER = logging.getLogger("continuity_lab.managed_inquiry_worker")
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
        "inquiry_rejected",
        "inquiry_conflict",
        "dependency_unavailable",
        "schema_version_unsupported",
        "invalid_input",
    }
)


class InquiryNotDispatched(SupplierUnavailable):
    """Trusted provider assertion that this invocation accepted no inquiry.

    This must never be inferred from exception wording or a client timeout. It
    exists for an adapter with positive pre-dispatch evidence, including the
    deterministic scripted fixture used to test transient retries.
    """


def _event(event: str, code: str = "ok") -> None:
    try:
        LOGGER.log(
            logging.ERROR if event == "managed_worker_failed" else logging.INFO,
            event,
            extra={"event": event, "code": code},
        )
    except Exception:  # noqa: BLE001 - telemetry cannot alter inquiry truth or failures
        return


def _code(error: Exception) -> str:
    try:
        candidate = getattr(error, "code", "unexpected_error")
        return candidate if type(candidate) is str and candidate in _CODES else "unexpected_error"
    except Exception:  # noqa: BLE001 - diagnostic metadata cannot replace an original failure
        return "unexpected_error"


class ManagedInquiryWorker:
    """Run at most one eligible attempt while holding the existing worker slot.

    A retry/recovery preserves the original effect and always looks it up first.
    Ambiguous dispatch is explicit uncertainty. Unexpected defects leave the
    started attempt recoverable and propagate to the sanitized entry boundary.
    """

    def __init__(
        self,
        lifecycle: PostgresLifecycle,
        supplier: InquirySupplierPort,
        *,
        failpoint: Callable[[str], None] | None = None,
    ) -> None:
        capabilities = supplier.capabilities
        if not capabilities.idempotent or not capabilities.lookup or not capabilities.read_only:
            raise UnsupportedOperation(
                "Managed inquiries require the cooperating read-only supplier contract"
            )
        self.lifecycle, self.supplier, self.failpoint = lifecycle, supplier, failpoint

    def run_one(self, *, scope_id: str, task_id: str) -> LifecycleSnapshot:
        try:
            with self.lifecycle.worker_slot():
                claim = self.lifecycle.claim_due(scope_id=scope_id, task_id=task_id)
                if claim is None:
                    return self.lifecycle.get(scope_id=scope_id, task_id=task_id)
                try:
                    observation = self.supplier.lookup(
                        scope_id=scope_id,
                        effect_id=claim.execution.effect_id,
                        request=claim.execution.request,
                    )
                except SupplierRejected:
                    return self.lifecycle.finish_failure(claim, FailureClass.PERMANENT)
                except SupplierUnavailable:
                    # A first lookup on a fresh untouched execution proves this
                    # worker has not dispatched. A recovering/older execution
                    # may already have an effect; failed lookup cannot erase it.
                    failure = (
                        FailureClass.TRANSIENT
                        if not claim.recovered and claim.attempt.attempt_no == 1
                        else FailureClass.AMBIGUOUS
                    )
                    return self.lifecycle.finish_failure(claim, failure)
                if observation is None:
                    current = self.lifecycle.get(scope_id=scope_id, task_id=task_id)
                    if instant(self.lifecycle.clock()) >= datetime.fromisoformat(current.deadline):
                        # A slow lookup cannot extend the original dispatch
                        # deadline. Recovery keeps old uncertainty explicit.
                        failure = (
                            FailureClass.AMBIGUOUS if claim.recovered else FailureClass.TRANSIENT
                        )
                        return self.lifecycle.finish_failure(claim, failure)
                    self.lifecycle.assert_claim_current(claim)
                    _event("managed_inquiry_dispatched")
                    try:
                        observation = self.supplier.inquire(
                            scope_id=scope_id,
                            effect_id=claim.execution.effect_id,
                            request=claim.execution.request,
                        )
                    except InquiryNotDispatched:
                        return self.lifecycle.finish_failure(claim, FailureClass.TRANSIENT)
                    except SupplierRejected:
                        return self.lifecycle.finish_failure(claim, FailureClass.PERMANENT)
                    except SupplierUnavailable:
                        return self.lifecycle.finish_failure(claim, FailureClass.AMBIGUOUS)
                else:
                    _event("managed_inquiry_reconciled")
                if self.failpoint is not None:
                    self.failpoint("managed_worker.after_supplier_success")
                value = self.lifecycle.finish_success(claim, observation.result)
                _event("managed_worker_completed")
                return value
        except Exception as error:
            _event("managed_worker_failed", _code(error))
            raise
