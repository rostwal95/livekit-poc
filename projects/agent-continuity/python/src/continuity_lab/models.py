"""Small application types, independent of transport and model providers."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class BookingChange:
    """A confirmed request to investigate a booking change, not to purchase one.

    Confirmation is a precondition in this local lab. A future voice adapter must
    collect it; the worker must not infer permission from an LLM's free text.
    """

    booking_reference: str
    new_check_in: date
    confirmed: bool

    def __post_init__(self) -> None:
        if not isinstance(self.booking_reference, str):
            raise ValueError("booking_reference must be a string")  # noqa: TRY004 - public validation contract
        reference = self.booking_reference.strip().upper()
        if not reference or len(reference) > 64:
            raise ValueError("booking_reference must contain 1 to 64 characters")
        # datetime subclasses date; accepting it would change the canonical payload.
        if type(self.new_check_in) is not date:
            raise ValueError("new_check_in must be a date")
        if self.confirmed is not True:
            raise ValueError("explicit confirmation is required before submission")
        object.__setattr__(self, "booking_reference", reference)

    def payload(self) -> dict[str, str | bool]:
        return {
            "booking_reference": self.booking_reference,
            "new_check_in": self.new_check_in.isoformat(),
            "confirmed": self.confirmed,
        }


@dataclass(frozen=True, slots=True)
class Task:
    task_id: str
    scope_id: str
    idempotency_key: str
    request: BookingChange
    status: str
    created_at: str


@dataclass(frozen=True, slots=True)
class Submission:
    task: Task
    created: bool


class IdempotencyConflict(ValueError):
    """The key was already accepted with a different canonical request."""


class IntakeCapacityExceeded(RuntimeError):
    """New intake exceeded its configured SQLite allocation budget."""
