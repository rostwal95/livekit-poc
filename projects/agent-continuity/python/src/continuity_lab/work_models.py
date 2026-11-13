"""Immutable values for the explicit P1 read-only accepted-work profile.

The bytes are opaque to P1. Applications validate their own versioned schema;
acceptance grants no booking action, issued attempt, execution or completion.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol
from uuid import UUID

from .authorization import BearerToken

MAX_WORK_BYTES = 16384
MAX_WORK_TIMESTAMP_MS = 4102444800000
WORK_OPERATION = "booking.evaluate_policy"
WorkCode = Literal[
    "invalid_input",
    "unauthorized",
    "not_found",
    "identity_conflict",
    "capacity",
    "expired",
    "storage_unavailable",
    "acknowledgement_unknown",
    "schema_mismatch",
    "closed",
    "cleanup_incomplete",
]
_CODES = frozenset(
    {
        "invalid_input",
        "unauthorized",
        "not_found",
        "identity_conflict",
        "capacity",
        "expired",
        "storage_unavailable",
        "acknowledgement_unknown",
        "schema_mismatch",
        "closed",
        "cleanup_incomplete",
    }
)


class WorkError(RuntimeError):
    """Fixed safe code; no payload, credential or dependency detail in args."""

    def __init__(self, code: WorkCode) -> None:
        self.code: WorkCode = code if type(code) is str and code in _CODES else "invalid_input"
        super().__init__(self.code)


def work_identifier(value: str) -> str:
    if (
        type(value) is not str
        or len(value) > 128
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value) is None
    ):
        raise WorkError("invalid_input")
    return value


def work_uuid(value: str) -> str:
    if type(value) is not str or len(value) != 36:
        raise WorkError("invalid_input")
    try:
        parsed = UUID(value)
        if parsed.version != 4 or str(parsed) != value:
            raise ValueError
    except (ValueError, AttributeError):
        raise WorkError("invalid_input") from None
    return value


def work_milliseconds(value: int) -> int:
    if type(value) is not int or not 0 <= value <= MAX_WORK_TIMESTAMP_MS:
        raise WorkError("invalid_input")
    return value


@dataclass(frozen=True, slots=True)
class WorkScope:
    tenant_id: str
    account_id: str

    def __post_init__(self) -> None:
        work_identifier(self.tenant_id)
        work_identifier(self.account_id)


@dataclass(frozen=True, slots=True)
class WorkPayload:
    operation: str
    body: bytes = field(repr=False)
    deadline_at_ms: int
    sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            type(self.operation) is not str
            or self.operation != WORK_OPERATION
            or type(self.body) is not bytes
            or not 1 <= len(self.body) <= MAX_WORK_BYTES
        ):
            raise WorkError("invalid_input")
        work_milliseconds(self.deadline_at_ms)
        object.__setattr__(self, "sha256", hashlib.sha256(self.body).hexdigest())


@dataclass(frozen=True, slots=True)
class WorkLimits:
    max_records: int = 1000
    max_cancel_commands: int = 1000

    def __post_init__(self) -> None:
        for value in (self.max_records, self.max_cancel_commands):
            if type(value) is not int or not 1 <= value <= 10000:
                raise WorkError("invalid_input")


@dataclass(frozen=True, slots=True)
class WorkPrincipal:
    actor_id: str
    scope: WorkScope

    def __post_init__(self) -> None:
        work_identifier(self.actor_id)
        if type(self.scope) is not WorkScope:
            raise WorkError("invalid_input")


@dataclass(frozen=True, slots=True, init=False)
class WorkDirectory:
    """Trusted finite credential inventory. No plaintext tokens are retained."""

    _entries: tuple[tuple[bytes, WorkPrincipal], ...] = field(repr=False)

    def __init__(self, registrations: Mapping[BearerToken, WorkPrincipal]) -> None:
        if not isinstance(registrations, Mapping) or not 1 <= len(registrations) <= 64:
            raise WorkError("invalid_input")
        entries: list[tuple[bytes, WorkPrincipal]] = []
        seen: set[bytes] = set()
        for token, principal in registrations.items():
            if len(entries) >= 64:
                raise WorkError("invalid_input")
            if type(token) is not BearerToken or type(principal) is not WorkPrincipal:
                raise WorkError("invalid_input")
            digest = hashlib.sha256(token.value.encode("ascii")).digest()
            if digest in seen:
                raise WorkError("invalid_input")
            seen.add(digest)
            entries.append((digest, principal))
        if not entries:
            raise WorkError("invalid_input")
        object.__setattr__(self, "_entries", tuple(entries))

    def authenticate(self, token: BearerToken) -> WorkPrincipal:
        match = None
        if type(token) is BearerToken:
            actual = hashlib.sha256(token.value.encode("ascii")).digest()
            for expected, principal in self._entries:
                if hmac.compare_digest(actual, expected):
                    match = principal
        if match is None:
            raise WorkError("unauthorized")
        return match


@dataclass(frozen=True, slots=True)
class WorkRecord:
    work_id: str
    scope: WorkScope
    idempotency_key: str
    payload: WorkPayload
    accepted_at_ms: int
    cancel_requested: bool
    status: Literal["accepted"] = "accepted"

    def __post_init__(self) -> None:
        work_uuid(self.work_id)
        work_identifier(self.idempotency_key)
        work_milliseconds(self.accepted_at_ms)
        if (
            type(self.scope) is not WorkScope
            or type(self.payload) is not WorkPayload
            or type(self.cancel_requested) is not bool
            or type(self.status) is not str
            or self.status != "accepted"
        ):
            raise WorkError("invalid_input")


@dataclass(frozen=True, slots=True)
class WorkSubmission:
    record: WorkRecord
    created: bool

    def __post_init__(self) -> None:
        if type(self.record) is not WorkRecord or type(self.created) is not bool:
            raise WorkError("invalid_input")


@dataclass(frozen=True, slots=True)
class WorkCancellation:
    cancellation_id: str
    work_id: str
    command_id: str
    requested_at_ms: int
    disposition: Literal["requested"] = "requested"

    def __post_init__(self) -> None:
        work_uuid(self.cancellation_id)
        work_uuid(self.work_id)
        work_identifier(self.command_id)
        work_milliseconds(self.requested_at_ms)
        if type(self.disposition) is not str or self.disposition != "requested":
            raise WorkError("invalid_input")


class TaskExecutionPort(Protocol):
    @property
    def scope(self) -> WorkScope: ...
    @property
    def pending_count(self) -> int: ...
    async def submit(self, *, idempotency_key: str, payload: WorkPayload) -> WorkSubmission: ...
    async def find(self, *, idempotency_key: str) -> WorkRecord | None: ...
    async def get(self, *, work_id: str) -> WorkRecord: ...
    async def cancel(self, *, work_id: str, command_id: str) -> WorkCancellation: ...
    async def close(self) -> None: ...
