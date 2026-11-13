"""Immutable coordination policy and observed server-time lease authority.

Lease expiry limits local write authority. It cannot cancel or fence an already
sent supplier request; that still requires supplier cooperation or uncertainty.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from .execution_models import TransitionConflict, UnsupportedOperation

MAX_EPOCH = 9223372036854775807


class LeaseBusy(TransitionConflict):
    """Another unexpired invocation currently owns this workflow."""

    code = "lease_busy"


class LeaseLost(TransitionConflict):
    """The supplied invocation epoch is absent, expired or superseded."""

    code = "lease_lost"


class LeaseRequired(UnsupportedOperation):
    """A v4 worker operation omitted its explicit lease authority."""

    code = "lease_required"


def identity(value: object) -> str:
    if (
        type(value) is not str
        or not 1 <= len(value) <= 128
        or value != value.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError("A bounded canonical identity is required")
    return value


def owner_identity(value: object) -> str:
    text = identity(value)
    try:
        canonical = str(UUID(text))
    except ValueError as error:
        raise ValueError("A canonical invocation UUID is required") from error
    if canonical != text:
        raise ValueError("A canonical invocation UUID is required")
    return text


def epoch_number(value: object) -> int:
    if type(value) is not int or not 1 <= value <= MAX_EPOCH:
        raise ValueError("A positive bounded lease epoch is required")
    return value


def server_instant(value: object) -> str:
    if type(value) is not str or not 1 <= len(value) <= 64:
        raise ValueError("A canonical UTC server instant is required")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("A canonical UTC server instant is required") from error
    if parsed.utcoffset() != timedelta(0) or parsed.isoformat() != value:
        raise ValueError("A canonical UTC server instant is required")
    return value


@dataclass(frozen=True, slots=True)
class CoordinationPolicy:
    maximum_pending: int = 1000
    maximum_active: int = 4
    maximum_records: int = 10000
    lease_seconds: int = 30

    def __post_init__(self) -> None:
        if any(
            type(value) is not int
            for value in (
                self.maximum_pending,
                self.maximum_active,
                self.maximum_records,
                self.lease_seconds,
            )
        ):
            raise ValueError("Coordination limits must be exact integers")
        if (
            not 1 <= self.maximum_pending <= 100000
            or not 1 <= self.maximum_active <= min(64, self.maximum_pending)
            or not self.maximum_pending <= self.maximum_records <= 1000000
            or not 1 <= self.lease_seconds <= 300
        ):
            raise ValueError("Coordination limits must satisfy the supported finite bounds")

    def payload(self) -> dict[str, int]:
        return {
            "maximum_pending": self.maximum_pending,
            "maximum_active": self.maximum_active,
            "maximum_records": self.maximum_records,
            "lease_seconds": self.lease_seconds,
        }


@dataclass(frozen=True, slots=True)
class LeaseGrant:
    scope_id: str
    task_id: str
    owner_id: str
    epoch: int
    expires_at: str

    def __post_init__(self) -> None:
        identity(self.scope_id)
        identity(self.task_id)
        owner_identity(self.owner_id)
        epoch_number(self.epoch)
        server_instant(self.expires_at)


@dataclass(frozen=True, slots=True)
class LeaseSnapshot:
    scope_id: str
    task_id: str
    owner_id: str | None
    epoch: int
    expires_at: str | None
    claimed_at: str
    renewed_at: str

    def __post_init__(self) -> None:
        identity(self.scope_id)
        identity(self.task_id)
        epoch_number(self.epoch)
        server_instant(self.claimed_at)
        server_instant(self.renewed_at)
        if datetime.fromisoformat(self.renewed_at) < datetime.fromisoformat(self.claimed_at):
            raise ValueError("Lease renewal must not precede claim")
        if (self.owner_id is None) != (self.expires_at is None):
            raise ValueError("Lease owner and expiry must be present together")
        if self.owner_id is not None:
            owner_identity(self.owner_id)
            server_instant(self.expires_at)
            assert self.expires_at is not None
            if datetime.fromisoformat(self.expires_at) <= datetime.fromisoformat(self.renewed_at):
                raise ValueError("Owned lease expiry must follow its last renewal")

    def grant(self) -> LeaseGrant:
        if self.owner_id is None or self.expires_at is None:
            raise LeaseLost("Execution invocation has no current lease owner")
        return LeaseGrant(self.scope_id, self.task_id, self.owner_id, self.epoch, self.expires_at)


class WorkKind(StrEnum):
    INQUIRY = "inquiry"
    WAIT = "wait"
    MUTATION = "mutation"
    DELIVERY = "delivery"


@dataclass(frozen=True, slots=True)
class WorkClaim:
    grant: LeaseGrant
    kind: WorkKind
    actor_id: str | None = None

    def __post_init__(self) -> None:
        if type(self.grant) is not LeaseGrant or type(self.kind) is not WorkKind:
            raise ValueError("Work selection requires a typed lease and step")
        if self.kind == WorkKind.WAIT:
            identity(self.actor_id)
        elif self.actor_id is not None:
            raise ValueError("Only a wait step carries the authority-derived actor")
