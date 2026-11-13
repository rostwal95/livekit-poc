"""Immutable values for the explicitly supported SQLite inquiry subset."""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Protocol

from .models import BookingChange


class Operation(StrEnum):
    INQUIRE = "booking.inquire"


class ExecutionStatus(StrEnum):
    ACCEPTED = "accepted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class AttemptStatus(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class FailureCode(StrEnum):
    INQUIRY_REJECTED = "inquiry_rejected"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"


class ExecutionError(RuntimeError):
    """Safe domain failure; callers must not serialize its dependency cause."""

    code = "execution_error"


class ExecutionNotFound(ExecutionError):
    code = "execution_not_found"


class TransitionConflict(ExecutionError):
    code = "transition_conflict"


class UnsupportedOperation(ExecutionError):
    code = "unsupported_operation"


class StorageUnavailable(ExecutionError):
    code = "storage_unavailable"


class InvalidStoredState(ExecutionError):
    code = "invalid_stored_state"


class ExecutionCapacityExceeded(ExecutionError):
    code = "capacity_exhausted"


class ExecutionPortClosed(ExecutionError):
    code = "execution_port_closed"


@dataclass(frozen=True, slots=True)
class InquiryResult:
    booking_reference: str
    new_check_in: date
    available: bool

    def __post_init__(self) -> None:
        # Reuse the existing canonical booking/date rules, without granting apply.
        canonical = BookingChange(self.booking_reference, self.new_check_in, confirmed=True)
        if type(self.available) is not bool:
            raise ValueError("availability must be a boolean")
        object.__setattr__(self, "booking_reference", canonical.booking_reference)

    def payload(self) -> dict[str, str | bool]:
        return {
            "booking_reference": self.booking_reference,
            "new_check_in": self.new_check_in.isoformat(),
            "available": self.available,
        }


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    task_id: str
    scope_id: str
    idempotency_key: str
    request: BookingChange
    operation: Operation
    status: ExecutionStatus
    effect_id: str
    version: int
    created_at: str
    updated_at: str
    result: InquiryResult | None
    error_code: FailureCode | None


@dataclass(frozen=True, slots=True)
class ExecutionSubmission:
    execution: ExecutionRecord
    created: bool
    enrolled: bool


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    attempt_id: str
    task_id: str
    attempt_no: int
    status: AttemptStatus
    started_at: str
    finished_at: str | None
    error_code: FailureCode | None


@dataclass(frozen=True, slots=True)
class AttemptStart:
    execution: ExecutionRecord
    attempt: AttemptRecord


class InquiryExecutionPort(Protocol):
    """Small allowlisted subset, not the future wait/cancel/lease interface."""

    def submit(
        self,
        *,
        scope_id: str,
        idempotency_key: str,
        request: BookingChange,
        operation: str = Operation.INQUIRE,
    ) -> ExecutionSubmission: ...

    def get(self, *, scope_id: str, task_id: str) -> ExecutionRecord: ...


class WorkerExecutionPort(InquiryExecutionPort, Protocol):
    """Current inquiry lifecycle shared by SQLite and PostgreSQL adapters."""

    backend: str

    def list(self, *, scope_id: str, limit: int = 100) -> tuple[ExecutionRecord, ...]: ...
    def attempts(self, *, scope_id: str, task_id: str) -> tuple[AttemptRecord, ...]: ...
    def start_attempt(
        self, *, scope_id: str, task_id: str, expected_version: int
    ) -> AttemptStart: ...
    def recover_attempt(
        self, *, scope_id: str, task_id: str, expected_version: int
    ) -> AttemptStart: ...
    def finish_attempt(
        self,
        *,
        scope_id: str,
        task_id: str,
        attempt_id: str,
        expected_version: int,
        result: InquiryResult | None = None,
        error_code: FailureCode | None = None,
    ) -> ExecutionRecord: ...
    def cancel(self, *, scope_id: str, task_id: str) -> None: ...
    def worker_slot(self) -> AbstractContextManager[None]: ...
