"""Pure bounded retry eligibility; ambiguity never grants automatic resend."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum


class FailureClass(StrEnum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    AMBIGUOUS = "ambiguous"


class RetryDisposition(StrEnum):
    RETRY_WAIT = "retry_wait"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


class RetryError(StrEnum):
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    PERMANENT_FAILURE = "permanent_failure"
    RETRY_EXHAUSTED = "retry_exhausted"
    DEADLINE_EXPIRED = "deadline_expired"
    AMBIGUOUS_OUTCOME = "ambiguous_outcome"


def instant(value: datetime) -> datetime:
    if type(value) is not datetime or value.utcoffset() is None:
        raise ValueError("Business time must be an aware datetime")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    initial_delay_seconds: int = 1
    max_delay_seconds: int = 30

    def __post_init__(self) -> None:
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 100:
            raise ValueError("Retry attempts must be between 1 and 100")
        if (
            type(self.initial_delay_seconds) is not int
            or type(self.max_delay_seconds) is not int
            or not 1 <= self.initial_delay_seconds <= self.max_delay_seconds <= 3600
        ):
            raise ValueError("Retry delays must be bounded positive integer seconds")

    def payload(self) -> dict[str, int]:
        return {
            "max_attempts": self.max_attempts,
            "initial_delay_seconds": self.initial_delay_seconds,
            "max_delay_seconds": self.max_delay_seconds,
        }

    def canonical(self) -> str:
        return json.dumps(self.payload(), sort_keys=True, separators=(",", ":"))


def parse_policy(value: str) -> RetryPolicy:
    if type(value) is not str or len(value) > 256:
        raise ValueError("Stored retry policy is invalid")
    body = json.loads(value)
    if type(body) is not dict or set(body) != {
        "max_attempts",
        "initial_delay_seconds",
        "max_delay_seconds",
    }:
        raise ValueError("Stored retry policy is invalid")
    policy = RetryPolicy(**body)
    if policy.canonical() != value:
        raise ValueError("Stored retry policy must remain canonical")
    return policy


@dataclass(frozen=True, slots=True)
class RetryDecision:
    disposition: RetryDisposition
    next_attempt_at: datetime | None
    error_code: RetryError


def decide_retry(
    failure: FailureClass,
    *,
    attempt_no: int,
    policy: RetryPolicy,
    now: datetime,
    deadline: datetime,
) -> RetryDecision:
    """Evaluate after a completed attempt, without sleeping or mutating state.

    Unknown external outcomes remain uncertain even after a deadline. Known
    transient failures may retry only strictly before the original deadline.
    The first failed attempt waits initial_delay, then doubles with a finite cap.
    """
    if type(failure) is not FailureClass or type(policy) is not RetryPolicy:
        raise ValueError("A typed failure classification and retry policy are required")
    if type(attempt_no) is not int or not 1 <= attempt_no <= 100:
        raise ValueError("Attempt number is outside the bounded policy")
    now, deadline = instant(now), instant(deadline)
    if failure == FailureClass.AMBIGUOUS:
        return RetryDecision(RetryDisposition.UNCERTAIN, None, RetryError.AMBIGUOUS_OUTCOME)
    if failure == FailureClass.PERMANENT:
        return RetryDecision(RetryDisposition.FAILED, None, RetryError.PERMANENT_FAILURE)
    if now >= deadline:
        return RetryDecision(RetryDisposition.FAILED, None, RetryError.DEADLINE_EXPIRED)
    if attempt_no >= policy.max_attempts:
        return RetryDecision(RetryDisposition.FAILED, None, RetryError.RETRY_EXHAUSTED)
    delay = min(policy.initial_delay_seconds * 2 ** (attempt_no - 1), policy.max_delay_seconds)
    if deadline - now <= timedelta(seconds=delay):
        return RetryDecision(RetryDisposition.FAILED, None, RetryError.DEADLINE_EXPIRED)
    eligible = now + timedelta(seconds=delay)
    return RetryDecision(RetryDisposition.RETRY_WAIT, eligible, RetryError.DEPENDENCY_UNAVAILABLE)
