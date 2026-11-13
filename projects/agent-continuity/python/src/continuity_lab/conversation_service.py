"""Authenticated durable conversation operations, without model consent tools.

The native adapter exposes only submit/get/cancel. Quote preparation and exact
confirmation are separate trusted controller operations at the HTTP/UI boundary.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, TypeVar

from .authorization import AuthenticatedActor, BearerToken, TokenDirectory
from .bounded_io import BoundedAsyncIO
from .case_models import Confirmation, identity
from .case_projection import CaseProjection
from .case_service import ScopedCaseService
from .case_telemetry import CaseTelemetry
from .effect_models import CancellationReceipt
from .execution_models import UnsupportedOperation
from .lifecycle_models import SignalReceipt
from .managed_admission import ManagedAcceptance
from .models import BookingChange
from .quote_producer import QuoteReceipt

T = TypeVar("T")


class ManagedAdmissionPort(Protocol):
    def accept(
        self, *, actor: AuthenticatedActor, idempotency_key: str, request: BookingChange
    ) -> ManagedAcceptance: ...


class CaseProjectionPort(Protocol):
    def get(
        self, *, actor: AuthenticatedActor, task_id: str, cursor: str | None = None, limit: int = 10
    ) -> CaseProjection: ...


class TrustedQuotePort(Protocol):
    def prepare(
        self, *, actor: AuthenticatedActor, task_id: str, expected_revision: int, command_id: str
    ) -> QuoteReceipt: ...


@dataclass(frozen=True, slots=True)
class ManagedReceipt:
    created: bool
    task_id: str
    case_id: str
    projection: CaseProjection

    def payload(self) -> dict[str, object]:
        return {
            "created": self.created,
            "task_id": self.task_id,
            "case_id": self.case_id,
            "projection": self.projection.payload(),
        }


@dataclass(frozen=True, slots=True)
class ConversationService:
    directory: TokenDirectory = field(repr=False)
    admission: ManagedAdmissionPort = field(repr=False)
    projection: CaseProjectionPort = field(repr=False)
    case_service: ScopedCaseService = field(repr=False)
    quote_producer: TrustedQuotePort | None = field(default=None, repr=False)
    telemetry: CaseTelemetry = field(default_factory=CaseTelemetry, repr=False)

    def __post_init__(self) -> None:
        if self.case_service.directory is not self.directory:
            raise ValueError("Conversation and controller operations require one trusted directory")

    def submit(
        self, *, token: BearerToken, idempotency_key: str, request: BookingChange
    ) -> ManagedReceipt:
        def accept() -> ManagedReceipt:
            actor = self.directory.authenticate(token)
            accepted = self.admission.accept(
                actor=actor, idempotency_key=idempotency_key, request=request
            )
            projection = self.projection.get(actor=actor, task_id=accepted.case.task_id)
            return ManagedReceipt(
                accepted.created, accepted.case.task_id, accepted.case.case_id, projection
            )

        return self.telemetry.call("managed_submit", accept)

    def get(
        self, *, token: BearerToken, task_id: str, cursor: str | None = None, limit: int = 10
    ) -> CaseProjection:
        return self.telemetry.call(
            "projection",
            lambda: self.projection.get(
                actor=self.directory.authenticate(token),
                task_id=task_id,
                cursor=cursor,
                limit=limit,
            ),
        )

    def prepare_quote(
        self, *, token: BearerToken, task_id: str, expected_revision: int, command_id: str
    ) -> QuoteReceipt:
        def prepare() -> QuoteReceipt:
            actor = self.directory.authenticate(token)
            if self.quote_producer is None:
                raise UnsupportedOperation("Trusted proposal production is not configured")
            return self.quote_producer.prepare(
                actor=actor,
                task_id=task_id,
                expected_revision=expected_revision,
                command_id=command_id,
            )

        return self.telemetry.call("prepare_quote", prepare)

    def signal(
        self, *, token: BearerToken, task_id: str, confirmation: Confirmation, command_id: str
    ) -> SignalReceipt:
        def signal() -> SignalReceipt:
            self.directory.authenticate(token)
            task = identity(task_id)
            if type(confirmation) is not Confirmation or confirmation.quote.task_id != task:
                raise ValueError("Exact confirmation belongs to another route task")
            return self.case_service.signal(
                token=token, event_id=command_id, confirmation=confirmation
            )

        return self.telemetry.call("signal", signal)

    def cancel(self, *, token: BearerToken, task_id: str, command_id: str) -> CancellationReceipt:
        def cancel() -> CancellationReceipt:
            self.directory.authenticate(token)
            return self.case_service.cancel(token=token, task_id=task_id, command_id=command_id)

        return self.telemetry.call("cancel", cancel)


class AsyncConversationService(BoundedAsyncIO):
    """Offload finite synchronous operations without tying work to a media turn."""

    def __init__(
        self,
        service: ConversationService,
        *,
        maximum: int = 4,
        admission_timeout: float = 0.05,
        shutdown_timeout: float = 10,
    ) -> None:
        super().__init__(
            maximum=maximum, admission_timeout=admission_timeout, shutdown_timeout=shutdown_timeout
        )
        self.service = service

    async def run(self, action: Callable[[ConversationService], T]) -> T:
        """Only a trusted adapter supplies code; request bodies never provide it."""
        return await self._run(lambda: action(self.service))
