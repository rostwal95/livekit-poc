"""Immutable issued read-only attempt values; no booking or current-case authority."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from typing import Literal, Protocol

from .work_models import (
    WorkError,
    WorkRecord,
    WorkScope,
    work_identifier,
    work_milliseconds,
    work_uuid,
)

ResultDisposition = Literal[
    "eligible_at_commit", "cancelled", "expired", "superseded", "lease_expired"
]
ExecutionStatus = Literal[
    "accepted", "running", "retryable", "exhausted", "result_recorded", "cancelled", "expired"
]
_DISPOSITIONS = frozenset(
    {"eligible_at_commit", "cancelled", "expired", "superseded", "lease_expired"}
)
_STATUSES = frozenset(
    {"accepted", "running", "retryable", "exhausted", "result_recorded", "cancelled", "expired"}
)


@dataclass(frozen=True, slots=True)
class ExecutionLimits:
    """Logical active leases, attempts per work and lease milliseconds; not physical CPU caps."""

    max_active: int = 2
    max_attempts: int = 3
    lease_ms: int = 10000

    def __post_init__(self) -> None:
        for value, maximum in ((self.max_active, 4), (self.max_attempts, 3)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise WorkError("invalid_input")
        if type(self.lease_ms) is not int or not 100 <= self.lease_ms <= 30000:
            raise WorkError("invalid_input")


@dataclass(frozen=True, slots=True)
class IssuedAttempt:
    """Exact persisted grant; original accepted input remains separate from wire correlation."""

    record: WorkRecord
    attempt_id: str
    command_id: str
    number: int
    owner_id: str
    epoch: int
    issued_at_ms: int
    lease_until_ms: int

    def __post_init__(self) -> None:
        if type(self.record) is not WorkRecord or self.record.cancel_requested:
            raise WorkError("invalid_input")
        work_uuid(self.attempt_id)
        work_uuid(self.owner_id)
        work_identifier(self.command_id)
        for value in (self.number, self.epoch):
            if type(value) is not int or not 1 <= value <= 3:
                raise WorkError("invalid_input")
        work_milliseconds(self.issued_at_ms)
        work_milliseconds(self.lease_until_ms)
        if not self.issued_at_ms < self.lease_until_ms <= self.record.payload.deadline_at_ms:
            raise WorkError("invalid_input")


@dataclass(frozen=True, slots=True)
class Issuance:
    attempt: IssuedAttempt
    created: bool

    def __post_init__(self) -> None:
        if type(self.attempt) is not IssuedAttempt or type(self.created) is not bool:
            raise WorkError("invalid_input")


@dataclass(frozen=True, slots=True)
class AttemptResult:
    """Immutable opaque result; eligible_at_commit is only P1 time/lease/cancel eligibility."""

    work_id: str
    attempt_id: str
    body: bytes = field(repr=False)
    recorded_at_ms: int
    disposition: ResultDisposition

    def __post_init__(self) -> None:
        work_uuid(self.work_id)
        work_uuid(self.attempt_id)
        if type(self.body) is not bytes or not 1 <= len(self.body) <= 8192:
            raise WorkError("invalid_input")
        work_milliseconds(self.recorded_at_ms)
        if type(self.disposition) is not str or self.disposition not in _DISPOSITIONS:
            raise WorkError("invalid_input")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()


@dataclass(frozen=True, slots=True)
class ExecutionObservation:
    """Current persisted observations; result truth and current cancellation remain separate."""

    record: WorkRecord
    current_attempt: IssuedAttempt | None
    result: AttemptResult | None
    attempts_issued: int
    status: ExecutionStatus

    def __post_init__(self) -> None:
        if (
            type(self.record) is not WorkRecord
            or type(self.attempts_issued) is not int
            or not 0 <= self.attempts_issued <= 3
        ):
            raise WorkError("invalid_input")
        if type(self.status) is not str or self.status not in _STATUSES:
            raise WorkError("invalid_input")
        if self.current_attempt is not None and type(self.current_attempt) is not IssuedAttempt:
            raise WorkError("invalid_input")
        if self.result is not None and type(self.result) is not AttemptResult:
            raise WorkError("invalid_input")
        if (self.current_attempt is None) != (self.attempts_issued == 0):
            raise WorkError("invalid_input")
        if self.current_attempt is not None and (
            self.current_attempt.number != self.attempts_issued
            or self.current_attempt.record != replace(self.record, cancel_requested=False)
        ):
            raise WorkError("invalid_input")
        if self.status == "result_recorded" and (
            self.result is None or self.result.disposition != "eligible_at_commit"
        ):
            raise WorkError("invalid_input")
        if self.result is not None and (
            self.current_attempt is None
            or self.result.work_id != self.record.work_id
            or self.result.attempt_id != self.current_attempt.attempt_id
        ):
            raise WorkError("invalid_input")


class ExecutionPort(Protocol):
    @property
    def scope(self) -> WorkScope: ...
    @property
    def pending_count(self) -> int: ...
    async def issue(self, *, work_id: str, owner_id: str, command_id: str) -> Issuance: ...
    async def find_issue(self, *, command_id: str) -> IssuedAttempt | None: ...
    async def complete(self, *, attempt: IssuedAttempt, body: bytes) -> AttemptResult: ...
    async def result(self, *, work_id: str, attempt_id: str) -> AttemptResult | None: ...
    async def observe(self, *, work_id: str) -> ExecutionObservation: ...
    async def close(self) -> None: ...
