"""Immutable exact consent and case authority values for the PostgreSQL lifecycle.

Investigation, quote publication, explicit confirmation and intent commitment are
separate operations. These values never grant supplier mutation capability.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Protocol
from uuid import UUID

from .authorization import AuthenticatedActor
from .execution_models import ExecutionCapacityExceeded, ExecutionError, UnsupportedOperation
from .models import BookingChange

MAX_INTEGER = 9223372036854775807
MAX_AMOUNT_MINOR = 9007199254740991
SUPPORTED_CURRENCIES = frozenset({"USD", "EUR", "GBP", "INR"})


class StaleRevision(ExecutionError):
    code = "stale_revision"


class QuoteExpired(ExecutionError):
    code = "quote_expired"


class DeadlineExpired(ExecutionError):
    code = "deadline_expired"


class InvalidConfirmation(ExecutionError):
    code = "invalid_confirmation"


class CaseCancelled(ExecutionError):
    code = "case_cancelled"


class IntentAlreadyCommitted(ExecutionError):
    code = "intent_committed"


class CaseCapacityExceeded(ExecutionCapacityExceeded):
    pass


def identity(value: object) -> str:
    if (
        type(value) is not str
        or not 1 <= len(value) <= 128
        or value != value.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError("Case identity must be bounded nonempty text")
    value.encode("utf-8")
    return value


def integer(value: object, *, maximum: int = MAX_INTEGER) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError("Case integer is outside the supported range")
    return value


def uuid_identity(value: object) -> str:
    result = identity(value)
    if str(UUID(result)) != result:
        raise ValueError("Case UUID must use its canonical representation")
    return result


def utc_instant(value: object) -> datetime:
    if type(value) is not str or not 1 <= len(value) <= 64 or value != value.strip():
        raise ValueError("Case timestamp must be bounded UTC text")
    try:
        instant = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("Case timestamp must be a valid UTC instant") from error
    if instant.tzinfo is None or instant.utcoffset() != timedelta(0):
        raise ValueError("Case timestamp must be an absolute UTC instant")
    return instant.astimezone(UTC)


def canonical(value: Mapping[str, object]) -> str:
    return json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _fields(value: object, expected: set[str]) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ValueError("Case payload has unsupported or missing fields")
    return value


def _text(value: object) -> str:
    if type(value) is not str:
        raise ValueError("Case payload field must be text")
    return value


@dataclass(frozen=True, slots=True)
class QuoteSnapshot:
    quote_id: str
    task_id: str
    revision: int
    booking_reference: str
    new_check_in: date
    amount_minor: int
    currency: str
    expires_at: str
    case_id: str | None = None
    expected_supplier_revision: int | None = None
    supplier_id: str | None = None

    @property
    def schema_version(self) -> int:
        return 1 if self.case_id is None else 2

    def __post_init__(self) -> None:
        supplied = (
            self.case_id is not None,
            self.expected_supplier_revision is not None,
            self.supplier_id is not None,
        )
        if any(supplied) and not all(supplied):
            raise ValueError("Mutation proposal requires case, supplier identity and revision")
        if self.case_id is not None:
            uuid_identity(self.case_id)
            integer(self.expected_supplier_revision, maximum=MAX_INTEGER - 1)
            uuid_identity(self.supplier_id)
            if self.case_id == self.task_id:
                raise ValueError("Proposal case and workflow identities must remain distinct")
        uuid_identity(self.quote_id)
        identity(self.task_id)
        integer(self.revision)
        change = BookingChange(self.booking_reference, self.new_check_in, True)
        if change.booking_reference != self.booking_reference:
            raise ValueError("Quote booking reference must already be canonical")
        integer(self.amount_minor, maximum=MAX_AMOUNT_MINOR)
        if type(self.currency) is not str or self.currency not in SUPPORTED_CURRENCIES:
            raise ValueError("Quote currency is outside the supported synthetic set")
        object.__setattr__(self, "expires_at", utc_instant(self.expires_at).isoformat())

    def payload(self) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": self.schema_version,
            "quote_id": self.quote_id,
            "task_id": self.task_id,
            "revision": self.revision,
            "booking_reference": self.booking_reference,
            "new_check_in": self.new_check_in.isoformat(),
            "amount_minor": self.amount_minor,
            "currency": self.currency,
            "expires_at": self.expires_at,
        }
        if self.schema_version == 2:
            value.update(
                case_id=self.case_id,
                expected_supplier_revision=self.expected_supplier_revision,
                supplier_id=self.supplier_id,
            )
        return value


def parse_quote(value: object) -> QuoteSnapshot:
    if not isinstance(value, Mapping):
        raise ValueError("Quote payload must contain exact versioned fields")  # noqa: TRY004 - preserve public validation contract
    version = value.get("schema_version")
    if type(version) is not int or version not in {1, 2}:
        raise ValueError("Quote schema version is unsupported")
    expected = {
        "schema_version",
        "quote_id",
        "task_id",
        "revision",
        "booking_reference",
        "new_check_in",
        "amount_minor",
        "currency",
        "expires_at",
    }
    if version == 2:
        expected.update({"case_id", "expected_supplier_revision", "supplier_id"})
    fields = _fields(value, expected)
    return QuoteSnapshot(
        _text(fields["quote_id"]),
        _text(fields["task_id"]),
        integer(fields["revision"]),
        _text(fields["booking_reference"]),
        date.fromisoformat(_text(fields["new_check_in"])),
        integer(fields["amount_minor"], maximum=MAX_AMOUNT_MINOR),
        _text(fields["currency"]),
        _text(fields["expires_at"]),
        _text(fields["case_id"]) if version == 2 else None,
        integer(fields["expected_supplier_revision"], maximum=MAX_INTEGER - 1)
        if version == 2
        else None,
        _text(fields["supplier_id"]) if version == 2 else None,
    )


@dataclass(frozen=True, slots=True)
class Confirmation:
    quote: QuoteSnapshot
    explicit: bool

    def __post_init__(self) -> None:
        if type(self.quote) is not QuoteSnapshot or self.explicit is not True:
            raise InvalidConfirmation("An exact explicitly accepted quote is required")

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": self.quote.schema_version,
            "quote": self.quote.payload(),
            "explicit": True,
        }


def parse_confirmation(value: object) -> Confirmation:
    try:
        fields = _fields(value, {"schema_version", "quote", "explicit"})
        if type(fields["schema_version"]) is not int or fields["schema_version"] not in {1, 2}:
            raise ValueError("Confirmation schema version is unsupported")
        if fields["explicit"] is not True:
            raise ValueError("Explicit confirmation is required")
        quote = parse_quote(fields["quote"])
        if fields["schema_version"] != quote.schema_version:
            raise ValueError("Confirmation and proposal versions must agree")
        return Confirmation(quote, True)
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        raise InvalidConfirmation("An exact explicitly accepted quote is required") from error


@dataclass(frozen=True, slots=True)
class ActionIntent:
    intent_id: str
    task_id: str
    scope_id: str
    actor_id: str
    revision: int
    quote: QuoteSnapshot
    confirmation_id: str
    effect_id: str
    dispatch_event_id: str
    created_at: str

    def __post_init__(self) -> None:
        for value in (self.intent_id, self.confirmation_id, self.effect_id, self.dispatch_event_id):
            uuid_identity(value)
        for value in (self.task_id, self.scope_id, self.actor_id):
            identity(value)
        integer(self.revision)
        if type(self.quote) is not QuoteSnapshot or (self.quote.task_id, self.quote.revision) != (
            self.task_id,
            self.revision,
        ):
            raise ValueError("Action intent must preserve its exact quote identity")
        object.__setattr__(self, "created_at", utc_instant(self.created_at).isoformat())

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": self.quote.schema_version,
            "operation": "booking.apply",
            "intent_id": self.intent_id,
            "task_id": self.task_id,
            "scope_id": self.scope_id,
            "actor_id": self.actor_id,
            "revision": self.revision,
            "quote": self.quote.payload(),
            "confirmation_id": self.confirmation_id,
            "effect_id": self.effect_id,
            "dispatch_event_id": self.dispatch_event_id,
            "created_at": self.created_at,
        }


def parse_intent(value: object) -> ActionIntent:
    fields = _fields(
        value,
        {
            "schema_version",
            "operation",
            "intent_id",
            "task_id",
            "scope_id",
            "actor_id",
            "revision",
            "quote",
            "confirmation_id",
            "effect_id",
            "dispatch_event_id",
            "created_at",
        },
    )
    if (
        type(fields["schema_version"]) is not int
        or fields["schema_version"] not in {1, 2}
        or fields["operation"] != "booking.apply"
    ):
        raise ValueError("Action intent schema is unsupported")
    quote = parse_quote(fields["quote"])
    if fields["schema_version"] != quote.schema_version:
        raise ValueError("Action intent and proposal versions must agree")
    return ActionIntent(
        _text(fields["intent_id"]),
        _text(fields["task_id"]),
        _text(fields["scope_id"]),
        _text(fields["actor_id"]),
        integer(fields["revision"]),
        quote,
        _text(fields["confirmation_id"]),
        _text(fields["effect_id"]),
        _text(fields["dispatch_event_id"]),
        _text(fields["created_at"]),
    )


def require_mutation_quote(intent: ActionIntent) -> QuoteSnapshot:
    """Reject historical consent rather than inventing a supplier revision later."""
    if type(intent) is not ActionIntent or intent.quote.schema_version != 2:
        raise UnsupportedOperation("Mutation requires a committed version 2 supplier proposal")
    return intent.quote


@dataclass(frozen=True, slots=True)
class CaseSnapshot:
    task_id: str
    scope_id: str
    actor_id: str
    revision: int
    request: BookingChange
    quote: QuoteSnapshot | None
    cancelled: bool
    intent: ActionIntent | None
    created_at: str
    updated_at: str
    case_id: str

    def __post_init__(self) -> None:
        uuid_identity(self.case_id)
        if self.case_id == self.task_id:
            raise ValueError("Case and workflow identities must remain distinct")


@dataclass(frozen=True, slots=True)
class IntentDispatch:
    event_id: str
    intent: ActionIntent
    created_at: str

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "event_id": self.event_id,
            "type": "booking.apply_requested",
            "intent": self.intent.payload(),
            "created_at": self.created_at,
        }


class CaseAuthorityPort(Protocol):
    def enroll(self, *, actor: AuthenticatedActor, task_id: str) -> CaseSnapshot: ...
    def get(self, *, actor: AuthenticatedActor, task_id: str) -> CaseSnapshot: ...
    def revise(
        self,
        *,
        actor: AuthenticatedActor,
        task_id: str,
        expected_revision: int,
        request: BookingChange,
    ) -> CaseSnapshot: ...
    def commit_intent(
        self, *, actor: AuthenticatedActor, confirmation: Confirmation, command_id: str
    ) -> ActionIntent: ...
