"""Supported dependency-free inquiry API and compatibility values.

Scope arguments belong to a trusted application caller. Use the authenticated
PostgreSQL facade for managed business work. SQLite supports the documented
inquiry subset only; importing this module starts no service or migration.
"""

from .async_execution import AsyncExecutionStore
from .execution import ExecutionStore
from .execution_models import (
    ExecutionCapacityExceeded,
    ExecutionError,
    ExecutionNotFound,
    ExecutionPortClosed,
    ExecutionRecord,
    ExecutionStatus,
    ExecutionSubmission,
    FailureCode,
    InquiryExecutionPort,
    InquiryResult,
    InvalidStoredState,
    Operation,
    StorageUnavailable,
    TransitionConflict,
    UnsupportedOperation,
)
from .migrations import MigrationError, MigrationReport, SchemaVersionError, migrate
from .models import BookingChange, IdempotencyConflict, IntakeCapacityExceeded, Submission, Task
from .store import TaskStore

__all__ = [
    "AsyncExecutionStore",
    "BookingChange",
    "ExecutionCapacityExceeded",
    "ExecutionError",
    "ExecutionNotFound",
    "ExecutionPortClosed",
    "ExecutionRecord",
    "ExecutionStatus",
    "ExecutionStore",
    "ExecutionSubmission",
    "FailureCode",
    "IdempotencyConflict",
    "InquiryExecutionPort",
    "InquiryResult",
    "IntakeCapacityExceeded",
    "InvalidStoredState",
    "MigrationError",
    "MigrationReport",
    "Operation",
    "SchemaVersionError",
    "StorageUnavailable",
    "Submission",
    "Task",
    "TaskStore",
    "TransitionConflict",
    "UnsupportedOperation",
    "migrate",
    "safe_error_code",
]

_SAFE_CODES = frozenset(
    {
        "execution_error",
        "execution_not_found",
        "transition_conflict",
        "unsupported_operation",
        "storage_unavailable",
        "invalid_stored_state",
        "capacity_exhausted",
        "execution_port_closed",
        "migration_failed",
        "schema_version_unsupported",
        "source_quiesced",
        "authentication_required",
        "stale_revision",
        "quote_expired",
        "invalid_confirmation",
        "case_cancelled",
        "intent_committed",
        "deadline_expired",
        "inquiry_rejected",
        "inquiry_conflict",
        "dependency_unavailable",
        "lease_busy",
        "lease_lost",
        "lease_required",
    }
)


def safe_error_code(error: BaseException) -> str:
    """Select a fixed diagnostic code without serializing an exception or cause.

    This helper observes failures; callers must still propagate cancellation and
    preserve unknown business outcomes. It does not turn failure into a retry or
    remove private values from an exception's traceback/args.
    """
    if isinstance(error, IdempotencyConflict):
        return "idempotency_conflict"
    if isinstance(error, IntakeCapacityExceeded):
        return "capacity_exhausted"
    if isinstance(error, (ExecutionError, MigrationError)):
        try:
            candidate = error.code
            if type(candidate) is str and candidate in _SAFE_CODES:
                return candidate
        except Exception:  # noqa: BLE001 - diagnostic metadata cannot replace the original error
            return "execution_error"
        return "execution_error"
    if isinstance(error, ValueError):
        return "invalid_input"
    return "unexpected_error"
