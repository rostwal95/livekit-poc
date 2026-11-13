"""Typed mutation evidence, cancellation and durable completion observations.

A committed intent grants only its exact revision-bound synthetic operation.
Business outcome, cancellation request and completion delivery remain separate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Protocol

from .authorization import AuthenticatedActor
from .case_models import (
    MAX_AMOUNT_MINOR,
    MAX_INTEGER,
    SUPPORTED_CURRENCIES,
    ActionIntent,
    canonical,
    identity,
    integer,
    utc_instant,
    uuid_identity,
)
from .execution_models import InvalidStoredState
from .models import BookingChange


class EffectState(StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    DISPATCHED = "dispatched"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNCERTAIN = "uncertain"
    CANCELLED = "cancelled"


class EffectFailure(StrEnum):
    SUPPLIER_REJECTED = "supplier_rejected"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    DEADLINE_EXPIRED = "deadline_expired"
    AMBIGUOUS_OUTCOME = "ambiguous_outcome"
    ATTEMPTS_EXHAUSTED = "attempts_exhausted"


class CancelReason(StrEnum):
    USER_REQUESTED = "user_requested"


class CancellationDisposition(StrEnum):
    NOT_REQUESTED = "not_requested"
    BEFORE_COMMIT = "cancelled_before_commit"
    BEFORE_DISPATCH = "cancelled_before_dispatch"
    REQUESTED = "requested_best_effort"
    ALREADY_TERMINAL = "already_terminal"


class DeliveryState(StrEnum):
    PENDING = "pending"
    DELIVERING = "delivering"
    DELIVERED = "delivered"
    EXHAUSTED = "exhausted"


@dataclass(frozen=True, slots=True)
class MutationResult:
    effect_id: str
    intent_id: str
    task_id: str
    case_id: str
    supplier_id: str
    scope_id: str
    booking_reference: str
    previous_check_in: date
    new_check_in: date
    previous_revision: int
    revision: int
    amount_minor: int
    currency: str
    created_at: str

    def __post_init__(self) -> None:
        for value in (self.effect_id, self.intent_id, self.case_id, self.supplier_id):
            uuid_identity(value)
        identity(self.task_id)
        identity(self.scope_id)
        if self.case_id == self.task_id:
            raise ValueError("Case identity must remain separate from the workflow")
        if type(self.previous_check_in) is not date:
            raise ValueError("Previous booking date must be a date")
        request = BookingChange(self.booking_reference, self.new_check_in, True)
        if request.booking_reference != self.booking_reference:
            raise ValueError("Booking reference must be canonical")
        integer(self.previous_revision, maximum=MAX_INTEGER - 1)
        integer(self.revision)
        if self.revision != self.previous_revision + 1:
            raise ValueError("Mutation result must advance exactly the confirmed booking revision")
        integer(self.amount_minor, maximum=MAX_AMOUNT_MINOR)
        if type(self.currency) is not str or self.currency not in SUPPORTED_CURRENCIES:
            raise ValueError("Mutation currency is unsupported")
        object.__setattr__(self, "created_at", utc_instant(self.created_at).isoformat())

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "effect_id": self.effect_id,
            "intent_id": self.intent_id,
            "task_id": self.task_id,
            "case_id": self.case_id,
            "supplier_id": self.supplier_id,
            "scope_id": self.scope_id,
            "booking_reference": self.booking_reference,
            "previous_check_in": self.previous_check_in.isoformat(),
            "new_check_in": self.new_check_in.isoformat(),
            "previous_revision": self.previous_revision,
            "revision": self.revision,
            "amount_minor": self.amount_minor,
            "currency": self.currency,
            "created_at": self.created_at,
        }


def _object(value: object, fields: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != fields:
        raise ValueError("Payload fields are unsupported")
    return value


def _text(value: object) -> str:
    if type(value) is not str:
        raise ValueError("Payload text is invalid")
    return value


def parse_mutation_result(value: object) -> MutationResult:
    body = _object(
        value,
        {
            "schema_version",
            "effect_id",
            "intent_id",
            "task_id",
            "case_id",
            "supplier_id",
            "scope_id",
            "booking_reference",
            "previous_check_in",
            "new_check_in",
            "previous_revision",
            "revision",
            "amount_minor",
            "currency",
            "created_at",
        },
    )
    if type(body["schema_version"]) is not int or body["schema_version"] != 1:
        raise ValueError("Mutation result version is unsupported")
    return MutationResult(
        _text(body["effect_id"]),
        _text(body["intent_id"]),
        _text(body["task_id"]),
        _text(body["case_id"]),
        _text(body["supplier_id"]),
        _text(body["scope_id"]),
        _text(body["booking_reference"]),
        date.fromisoformat(_text(body["previous_check_in"])),
        date.fromisoformat(_text(body["new_check_in"])),
        integer(body["previous_revision"]),
        integer(body["revision"]),
        integer(body["amount_minor"], maximum=MAX_AMOUNT_MINOR),
        _text(body["currency"]),
        _text(body["created_at"]),
    )


def require_result_binding(result: MutationResult, intent: ActionIntent) -> None:
    """Validate the exact committed proposal; never fill missing legacy values."""
    from .case_models import require_mutation_quote

    quote = require_mutation_quote(intent)
    if type(result) is not MutationResult or (
        result.effect_id,
        result.intent_id,
        result.task_id,
        result.case_id,
        result.supplier_id,
        result.scope_id,
        result.booking_reference,
        result.new_check_in,
        result.previous_revision,
        result.amount_minor,
        result.currency,
    ) != (
        intent.effect_id,
        intent.intent_id,
        intent.task_id,
        quote.case_id,
        quote.supplier_id,
        intent.scope_id,
        quote.booking_reference,
        quote.new_check_in,
        quote.expected_supplier_revision,
        quote.amount_minor,
        quote.currency,
    ):
        raise InvalidStoredState("Mutation evidence does not match the committed intent")


@dataclass(frozen=True, slots=True)
class EffectClaim:
    intent: ActionIntent
    attempt_id: str
    attempt_no: int
    generation: int
    recovered: bool
    may_have_dispatched: bool


@dataclass(frozen=True, slots=True)
class EffectSnapshot:
    intent: ActionIntent
    state: EffectState
    generation: int
    attempt_no: int
    dispatch_count: int
    result: MutationResult | None
    error_code: EffectFailure | None
    updated_at: str


@dataclass(frozen=True, slots=True)
class CancellationReceipt:
    cancellation_id: str
    task_id: str
    case_id: str
    command_id: str
    reason: CancelReason
    disposition: CancellationDisposition
    created_at: str
    created: bool


@dataclass(frozen=True, slots=True)
class BusinessOutcome:
    task_id: str
    case_id: str
    scope_id: str
    intent_id: str | None
    effect_id: str | None
    state: EffectState
    result: MutationResult | None
    error_code: EffectFailure | None
    cancellation: CancellationDisposition
    created_at: str

    def __post_init__(self) -> None:
        identity(self.task_id)
        identity(self.scope_id)
        uuid_identity(self.case_id)
        if (self.intent_id is None) != (self.effect_id is None):
            raise ValueError("Outcome intent and effect identities must be paired")
        if self.intent_id is not None:
            uuid_identity(self.intent_id)
            uuid_identity(self.effect_id)
        if type(self.state) is not EffectState or self.state not in {
            EffectState.SUCCEEDED,
            EffectState.FAILED,
            EffectState.UNCERTAIN,
            EffectState.CANCELLED,
        }:
            raise ValueError("Only a final observed business disposition may complete")
        if type(self.cancellation) is not CancellationDisposition or (
            self.error_code is not None and type(self.error_code) is not EffectFailure
        ):
            raise ValueError("Completion classifications must be typed")
        if (self.state == EffectState.SUCCEEDED) != (self.result is not None):
            raise ValueError("Successful business completion requires mutation evidence")
        if self.state in {EffectState.FAILED, EffectState.UNCERTAIN} and self.error_code is None:
            raise ValueError("Failed or uncertain completion requires a safe error code")
        if (
            self.state in {EffectState.SUCCEEDED, EffectState.CANCELLED}
            and self.error_code is not None
        ):
            raise ValueError("Successful or cancelled completion cannot carry a failure")
        if self.state == EffectState.CANCELLED and self.cancellation not in {
            CancellationDisposition.BEFORE_COMMIT,
            CancellationDisposition.BEFORE_DISPATCH,
        }:
            raise ValueError("Cancelled completion requires positive prevention evidence")
        if self.result is not None and (
            self.result.task_id,
            self.result.case_id,
            self.result.scope_id,
            self.result.intent_id,
            self.result.effect_id,
        ) != (
            self.task_id,
            self.case_id,
            self.scope_id,
            self.intent_id,
            self.effect_id,
        ):
            raise ValueError("Business outcome evidence has inconsistent identities")
        object.__setattr__(self, "created_at", utc_instant(self.created_at).isoformat())

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "task_id": self.task_id,
            "case_id": self.case_id,
            "scope_id": self.scope_id,
            "intent_id": self.intent_id,
            "effect_id": self.effect_id,
            "state": self.state.value,
            "result": None if self.result is None else self.result.payload(),
            "error_code": None if self.error_code is None else self.error_code.value,
            "cancellation": self.cancellation.value,
            "created_at": self.created_at,
        }


def parse_business_outcome(value: object) -> BusinessOutcome:
    body = _object(
        value,
        {
            "schema_version",
            "task_id",
            "case_id",
            "scope_id",
            "intent_id",
            "effect_id",
            "state",
            "result",
            "error_code",
            "cancellation",
            "created_at",
        },
    )
    if type(body["schema_version"]) is not int or body["schema_version"] != 1:
        raise ValueError("Business outcome version is unsupported")
    return BusinessOutcome(
        _text(body["task_id"]),
        _text(body["case_id"]),
        _text(body["scope_id"]),
        None if body["intent_id"] is None else _text(body["intent_id"]),
        None if body["effect_id"] is None else _text(body["effect_id"]),
        EffectState(_text(body["state"])),
        None if body["result"] is None else parse_mutation_result(body["result"]),
        None if body["error_code"] is None else EffectFailure(_text(body["error_code"])),
        CancellationDisposition(_text(body["cancellation"])),
        _text(body["created_at"]),
    )


@dataclass(frozen=True, slots=True)
class CompletionEvent:
    event_id: str
    outcome: BusinessOutcome
    created_at: str

    def __post_init__(self) -> None:
        uuid_identity(self.event_id)
        if type(self.outcome) is not BusinessOutcome:
            raise ValueError("Completion must contain a typed business outcome")
        if utc_instant(self.created_at).isoformat() != self.outcome.created_at:
            raise ValueError("Completion event must preserve its outcome timestamp")
        object.__setattr__(self, "created_at", self.outcome.created_at)

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": "workflow.completed",
            "event_id": self.event_id,
            "outcome": self.outcome.payload(),
            "created_at": self.created_at,
        }

    def canonical(self) -> str:
        return canonical(self.payload())


def parse_completion_event(value: object) -> CompletionEvent:
    body = _object(value, {"schema_version", "kind", "event_id", "outcome", "created_at"})
    if (
        type(body["schema_version"]) is not int
        or body["schema_version"] != 1
        or body["kind"] != "workflow.completed"
    ):
        raise ValueError("Completion event version is unsupported")
    return CompletionEvent(
        _text(body["event_id"]),
        parse_business_outcome(body["outcome"]),
        _text(body["created_at"]),
    )


@dataclass(frozen=True, slots=True)
class DeliveryPolicy:
    maximum_attempts: int = 8
    initial_delay_seconds: int = 1
    maximum_delay_seconds: int = 30

    def __post_init__(self) -> None:
        if type(self.maximum_attempts) is not int or not 1 <= self.maximum_attempts <= 100:
            raise ValueError("Delivery attempts must be bounded")
        if (
            type(self.initial_delay_seconds) is not int
            or type(self.maximum_delay_seconds) is not int
            or not 1 <= self.initial_delay_seconds <= self.maximum_delay_seconds <= 3600
        ):
            raise ValueError("Delivery retry delay must be bounded")

    def payload(self) -> dict[str, int]:
        return {
            "maximum_attempts": self.maximum_attempts,
            "initial_delay_seconds": self.initial_delay_seconds,
            "maximum_delay_seconds": self.maximum_delay_seconds,
        }


def parse_delivery_policy(value: object) -> DeliveryPolicy:
    body = _object(value, {"maximum_attempts", "initial_delay_seconds", "maximum_delay_seconds"})
    return DeliveryPolicy(
        integer(body["maximum_attempts"]),
        integer(body["initial_delay_seconds"]),
        integer(body["maximum_delay_seconds"]),
    )


@dataclass(frozen=True, slots=True)
class DeliverySnapshot:
    event: CompletionEvent
    target_id: str | None
    state: DeliveryState
    generation: int
    attempts: int
    next_attempt_at: str | None
    error_code: str | None
    updated_at: str


@dataclass(frozen=True, slots=True)
class DeliveryClaim:
    event: CompletionEvent
    generation: int
    attempts: int
    target_id: str


class EffectViewPort(Protocol):
    def get(self, *, scope_id: str, task_id: str) -> EffectSnapshot | None: ...
    def cancel(
        self,
        *,
        actor: AuthenticatedActor,
        task_id: str,
        command_id: str,
        reason: CancelReason = CancelReason.USER_REQUESTED,
    ) -> CancellationReceipt: ...
    def completion(self, *, actor: AuthenticatedActor, task_id: str) -> CompletionEvent | None: ...
    def delivery(self, *, actor: AuthenticatedActor, task_id: str) -> DeliverySnapshot | None: ...
