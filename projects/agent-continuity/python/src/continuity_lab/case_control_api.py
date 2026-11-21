"""Additive exact case reads/controller commands; no import-time I/O or schema changes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Self

from .authorization import AuthenticatedActor, BearerToken
from .case_models import ActionIntent, CaseSnapshot, Confirmation, identity, parse_confirmation
from .conversation_service import AsyncConversationService
from .models import BookingChange
from .postgres_api import open_postgres_client
from .postgres_settings import PostgresSettings, validate_identifier

__all__ = [
    "ActionIntent",
    "AuthenticatedActor",
    "BearerToken",
    "BookingChange",
    "CaseControlClient",
    "CaseControlIdentity",
    "CaseSnapshot",
    "Confirmation",
    "PostgresSettings",
    "open_case_control_client",
]


@dataclass(frozen=True, slots=True)
class CaseControlIdentity:
    actor_id: str
    scope_id: str
    schema: str


class CaseControlClient:
    """Credential-bound exact state. Controller confirmation is separate from model tools."""

    def __init__(self, boundary: AsyncConversationService, token: BearerToken, schema: str) -> None:
        if not isinstance(boundary, AsyncConversationService) or type(token) is not BearerToken:
            raise ValueError("Validated trusted boundary and credential are required")
        validate_identifier(schema)
        self._boundary, self._token, self._schema = boundary, token, schema
        _ = self.identity

    @property
    def identity(self) -> CaseControlIdentity:
        actor = self._boundary.service.directory.authenticate(self._token)
        return CaseControlIdentity(actor.actor_id, actor.scope_id, self._schema)

    @property
    def pending_count(self) -> int:
        return self._boundary.pending_count

    async def case(self, *, task_id: str) -> CaseSnapshot:
        task_id = identity(task_id)
        return await self._boundary.run(
            lambda service: service.case_service.get(token=self._token, task_id=task_id)
        )

    async def revise(
        self, *, task_id: str, expected_revision: int, request: BookingChange
    ) -> CaseSnapshot:
        if type(request) is not BookingChange:
            raise ValueError("A typed request is required")
        task_id = identity(task_id)
        snapshot = BookingChange(request.booking_reference, request.new_check_in, request.confirmed)
        return await self._boundary.run(
            lambda service: service.case_service.revise(
                token=self._token,
                task_id=task_id,
                expected_revision=expected_revision,
                request=snapshot,
            )
        )

    async def commit_confirmation(
        self, *, task_id: str, confirmation: Confirmation, command_id: str
    ) -> ActionIntent:
        """Independent exact controller operation; P3 uses action_api's additional work guard."""
        task_id, command_id = identity(task_id), identity(command_id)
        if type(confirmation) is not Confirmation:
            raise ValueError("An exact confirmation is required")
        snapshot = parse_confirmation(confirmation.payload())
        if snapshot.quote.task_id != task_id:
            raise ValueError("The confirmation task must match")
        return await self._boundary.run(
            lambda service: service.case_service.confirm(
                token=self._token, confirmation=snapshot, command_id=command_id
            )
        )

    async def close(self) -> None:
        await self._boundary.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()


def open_case_control_client(
    *,
    actor: AuthenticatedActor,
    token: BearerToken,
    settings: PostgresSettings,
    quote_database: Path | None = None,
) -> CaseControlClient:
    """Validate the initialized booking schema before conversation I/O."""
    # Use the supported factory's preflight without copying authority/migration policy.
    validated = open_postgres_client(
        actor=actor, token=token, settings=settings, quote_database=quote_database
    )
    return CaseControlClient(validated._boundary, token, settings.schema)
