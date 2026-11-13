"""Authenticated synthetic application boundary for exact consent and signals.

Quote issuance and retry/attempt policy belong to trusted producer/worker code.
Caller bodies never supply an actor or scope; no model summary can substitute for
an exact explicit confirmation command. Production IAM/HTTP/UI adapters follow.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, TypeVar

from .authorization import AuthenticatedActor, BearerToken, TokenDirectory
from .bounded_io import BoundedAsyncIO
from .case_models import ActionIntent, CaseAuthorityPort, CaseSnapshot, Confirmation, QuoteSnapshot
from .case_telemetry import CaseTelemetry
from .effect_models import (
    CancellationReceipt,
    CancelReason,
    CompletionEvent,
    DeliverySnapshot,
    EffectSnapshot,
    EffectViewPort,
)
from .execution_models import UnsupportedOperation
from .lifecycle_models import LifecycleSnapshot, SignalReceipt, WaitAdvance, WaitSnapshot
from .models import BookingChange

T = TypeVar("T")


class LifecyclePort(Protocol):
    def get(self, *, scope_id: str, task_id: str) -> LifecycleSnapshot: ...
    def arm_wait(
        self,
        *,
        actor: AuthenticatedActor,
        task_id: str,
        wait_id: str,
        quote: QuoteSnapshot,
        deadline: datetime,
    ) -> WaitSnapshot: ...
    def signal(
        self, *, actor: AuthenticatedActor, event_id: str, confirmation: Confirmation
    ) -> SignalReceipt: ...
    def advance(self, *, actor: AuthenticatedActor, task_id: str) -> WaitAdvance: ...
    def waits(self, *, actor: AuthenticatedActor, task_id: str) -> tuple[WaitSnapshot, ...]: ...


@dataclass(frozen=True, slots=True)
class ScopedCaseService:
    directory: TokenDirectory = field(repr=False)
    cases: CaseAuthorityPort = field(repr=False)
    lifecycle: LifecyclePort = field(repr=False)
    telemetry: CaseTelemetry = field(default_factory=CaseTelemetry, repr=False)
    effects: EffectViewPort | None = field(default=None, repr=False)

    def enroll(self, *, token: BearerToken, task_id: str) -> CaseSnapshot:
        return self.telemetry.call(
            "enroll",
            lambda: self.cases.enroll(actor=self.directory.authenticate(token), task_id=task_id),
        )

    def get(self, *, token: BearerToken, task_id: str) -> CaseSnapshot:
        return self.telemetry.call(
            "get", lambda: self.cases.get(actor=self.directory.authenticate(token), task_id=task_id)
        )

    def revise(
        self, *, token: BearerToken, task_id: str, expected_revision: int, request: BookingChange
    ) -> CaseSnapshot:
        return self.telemetry.call(
            "revise",
            lambda: self.cases.revise(
                actor=self.directory.authenticate(token),
                task_id=task_id,
                expected_revision=expected_revision,
                request=request,
            ),
        )

    def confirm(
        self, *, token: BearerToken, confirmation: Confirmation, command_id: str
    ) -> ActionIntent:
        return self.telemetry.call(
            "confirm",
            lambda: self.cases.commit_intent(
                actor=self.directory.authenticate(token),
                confirmation=confirmation,
                command_id=command_id,
            ),
        )

    def arm_wait(
        self,
        *,
        token: BearerToken,
        task_id: str,
        wait_id: str,
        quote: QuoteSnapshot,
        deadline: datetime,
    ) -> WaitSnapshot:
        return self.telemetry.call(
            "arm_wait",
            lambda: self.lifecycle.arm_wait(
                actor=self.directory.authenticate(token),
                task_id=task_id,
                wait_id=wait_id,
                quote=quote,
                deadline=deadline,
            ),
        )

    def signal(
        self, *, token: BearerToken, event_id: str, confirmation: Confirmation
    ) -> SignalReceipt:
        return self.telemetry.call(
            "signal",
            lambda: self.lifecycle.signal(
                actor=self.directory.authenticate(token),
                event_id=event_id,
                confirmation=confirmation,
            ),
        )

    def advance(self, *, token: BearerToken, task_id: str) -> WaitAdvance:
        return self.telemetry.call(
            "advance",
            lambda: self.lifecycle.advance(
                actor=self.directory.authenticate(token), task_id=task_id
            ),
        )

    def waits(self, *, token: BearerToken, task_id: str) -> tuple[WaitSnapshot, ...]:
        return self.telemetry.call(
            "waits",
            lambda: self.lifecycle.waits(actor=self.directory.authenticate(token), task_id=task_id),
        )

    def get_lifecycle(self, *, token: BearerToken, task_id: str) -> LifecycleSnapshot:
        def inspect() -> LifecycleSnapshot:
            actor = self.directory.authenticate(token)
            self.cases.get(actor=actor, task_id=task_id)
            return self.lifecycle.get(scope_id=actor.scope_id, task_id=task_id)

        return self.telemetry.call("lifecycle", inspect)

    def _effects(self) -> EffectViewPort:
        if self.effects is None:
            raise UnsupportedOperation("Supplier effects require the configured v3 boundary")
        return self.effects

    def cancel(
        self,
        *,
        token: BearerToken,
        task_id: str,
        command_id: str,
        reason: CancelReason = CancelReason.USER_REQUESTED,
    ) -> CancellationReceipt:
        def command() -> CancellationReceipt:
            actor = self.directory.authenticate(token)
            return self._effects().cancel(
                actor=actor, task_id=task_id, command_id=command_id, reason=reason
            )

        return self.telemetry.call("cancel", command)

    def get_effect(self, *, token: BearerToken, task_id: str) -> EffectSnapshot | None:
        def inspect() -> EffectSnapshot | None:
            actor = self.directory.authenticate(token)
            self.cases.get(actor=actor, task_id=task_id)
            return self._effects().get(scope_id=actor.scope_id, task_id=task_id)

        return self.telemetry.call("effect", inspect)

    def get_completion(self, *, token: BearerToken, task_id: str) -> CompletionEvent | None:
        def inspect() -> CompletionEvent | None:
            actor = self.directory.authenticate(token)
            return self._effects().completion(actor=actor, task_id=task_id)

        return self.telemetry.call("completion", inspect)

    def get_delivery(self, *, token: BearerToken, task_id: str) -> DeliverySnapshot | None:
        def inspect() -> DeliverySnapshot | None:
            actor = self.directory.authenticate(token)
            return self._effects().delivery(actor=actor, task_id=task_id)

        return self.telemetry.call("delivery", inspect)


class AsyncCaseService(BoundedAsyncIO):
    """Offload the same authenticated boundary under finite owned I/O capacity."""

    def __init__(
        self,
        service: ScopedCaseService,
        *,
        maximum: int = 4,
        admission_timeout: float = 0.05,
        shutdown_timeout: float = 10,
    ) -> None:
        super().__init__(
            maximum=maximum, admission_timeout=admission_timeout, shutdown_timeout=shutdown_timeout
        )
        self.service = service

    async def run(self, action: Callable[[ScopedCaseService], T]) -> T:
        """Trusted adapter supplies an operation; untrusted bodies cannot supply code."""
        return await self._run(lambda: action(self.service))
