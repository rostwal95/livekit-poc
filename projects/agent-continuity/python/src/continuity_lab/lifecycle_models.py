"""Immutable continuation observations attached to one original execution."""

from dataclasses import dataclass
from enum import StrEnum

from .case_models import ActionIntent, QuoteSnapshot
from .execution_models import AttemptRecord, ExecutionRecord
from .retry_policy import FailureClass, RetryError, RetryPolicy


class LifecycleState(StrEnum):
    READY = "ready"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    INQUIRY_COMPLETE = "inquiry_complete"
    WAITING = "waiting"
    INTENT_COMMITTED = "intent_committed"
    FAILED = "failed"
    UNCERTAIN = "uncertain"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class WaitState(StrEnum):
    PENDING = "pending"
    CONSUMED = "consumed"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class LifecycleSnapshot:
    task_id: str
    state: LifecycleState
    policy: RetryPolicy
    deadline: str
    next_attempt_at: str | None
    version: int
    last_failure: FailureClass | None
    error_code: RetryError | None
    updated_at: str


@dataclass(frozen=True, slots=True)
class ManagedClaim:
    execution: ExecutionRecord
    attempt: AttemptRecord
    control_version: int
    recovered: bool


@dataclass(frozen=True, slots=True)
class WaitSnapshot:
    wait_id: str
    task_id: str
    quote: QuoteSnapshot
    deadline: str
    state: WaitState
    created_at: str
    finished_at: str | None


@dataclass(frozen=True, slots=True)
class SignalReceipt:
    signal_id: str
    task_id: str
    event_id: str
    created: bool
    consumed_wait_id: str | None


@dataclass(frozen=True, slots=True)
class WaitAdvance:
    lifecycle: LifecycleSnapshot
    intent: ActionIntent | None
