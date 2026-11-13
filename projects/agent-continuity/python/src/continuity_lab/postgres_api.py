"""Supported authenticated managed-case client; requires the postgres extra.

The synchronous factory is trusted startup composition. It validates an existing
ACTIVE v4 authority and performs no DDL. Offload startup before entering a media
turn. The client exposes typed commands, never a callable execution endpoint.
"""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
from types import TracebackType
from typing import Self

from .authorization import AuthenticatedActor, AuthenticationFailed, BearerToken
from .case_models import (
    CaseCancelled,
    Confirmation,
    DeadlineExpired,
    IntentAlreadyCommitted,
    InvalidConfirmation,
    QuoteExpired,
    QuoteSnapshot,
    StaleRevision,
)
from .case_projection import CaseProjection, parse_confirmation_payload
from .conversation_composition import build_conversation_service
from .conversation_service import AsyncConversationService, ManagedReceipt
from .effect_models import CancellationDisposition, CancellationReceipt
from .lifecycle_models import SignalReceipt
from .models import BookingChange
from .postgres_migrations import validate_schema as _validate_schema
from .postgres_settings import PostgresSettings
from .quote_producer import QuoteReceipt

__all__ = [
    "AuthenticatedActor",
    "AuthenticationFailed",
    "BearerToken",
    "CancellationDisposition",
    "CancellationReceipt",
    "CaseCancelled",
    "CaseProjection",
    "Confirmation",
    "DeadlineExpired",
    "IntentAlreadyCommitted",
    "InvalidConfirmation",
    "ManagedCaseClient",
    "ManagedReceipt",
    "PostgresSettings",
    "QuoteExpired",
    "QuoteReceipt",
    "QuoteSnapshot",
    "SignalReceipt",
    "StaleRevision",
    "open_postgres_client",
    "parse_confirmation_payload",
]


class ManagedCaseClient:
    """One credential-bound client with finite I/O and an explicit close barrier.

    The boundary and token are trusted composition values. Every operation still
    authenticates through the underlying service; methods have no scope/actor
    override. Cancelling a waiter cannot stop already-started synchronous work or
    cancel the business task. Only cancel() records a business cancellation.
    """

    def __init__(self, boundary: AsyncConversationService, token: BearerToken) -> None:
        if not isinstance(boundary, AsyncConversationService) or type(token) is not BearerToken:
            raise ValueError(
                "A bounded conversation boundary and validated credential are required"
            )
        self._boundary, self._token = boundary, token

    @property
    def pending_count(self) -> int:
        """Actual synchronous operations still owning finite I/O capacity."""
        return self._boundary.pending_count

    async def submit(self, *, idempotency_key: str, request: BookingChange) -> ManagedReceipt:
        return await self._boundary.run(
            lambda service: service.submit(
                token=self._token, idempotency_key=idempotency_key, request=request
            )
        )

    async def get(
        self, *, task_id: str, cursor: str | None = None, limit: int = 10
    ) -> CaseProjection:
        return await self._boundary.run(
            lambda service: service.get(
                token=self._token, task_id=task_id, cursor=cursor, limit=limit
            )
        )

    async def cancel(self, *, task_id: str, command_id: str) -> CancellationReceipt:
        return await self._boundary.run(
            lambda service: service.cancel(
                token=self._token, task_id=task_id, command_id=command_id
            )
        )

    async def prepare_quote(
        self, *, task_id: str, expected_revision: int, command_id: str
    ) -> QuoteReceipt:
        """Trusted controller action; a native model tool must not expose it."""
        return await self._boundary.run(
            lambda service: service.prepare_quote(
                token=self._token,
                task_id=task_id,
                expected_revision=expected_revision,
                command_id=command_id,
            )
        )

    async def signal(
        self, *, task_id: str, confirmation: Confirmation, command_id: str
    ) -> SignalReceipt:
        """Record separate exact controller confirmation, never a model assertion."""
        return await self._boundary.run(
            lambda service: service.signal(
                token=self._token,
                task_id=task_id,
                confirmation=confirmation,
                command_id=command_id,
            )
        )

    async def close(self) -> None:
        """Reject new work and await actual pending I/O within its shutdown bound.

        Timeout or cancellation preserves pending ownership. Call close again to
        observe later completion; it never claims that a write was rolled back.
        """
        await self._boundary.close()

    async def __aenter__(self) -> Self:
        await self._boundary.__aenter__()
        return self

    async def __aexit__(
        self,
        error_type: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._boundary.__aexit__(error_type, error, traceback)


def open_postgres_client(
    *,
    actor: AuthenticatedActor,
    token: BearerToken,
    settings: PostgresSettings,
    quote_database: Path | None = None,
) -> ManagedCaseClient:
    """Build one existing-authority client at trusted synchronous startup.

    Four I/O slots, 50 ms admission timeout and five-second shutdown observation
    retain the existing composition bounds. No deployment or inference service
    is required by this library; the application owns its database and workers.
    """
    if (
        type(actor) is not AuthenticatedActor
        or type(token) is not BearerToken
        or type(settings) is not PostgresSettings
    ):
        raise ValueError("Validated trusted actor, credential and PostgreSQL settings are required")
    with closing(settings.connect()) as connection:
        _validate_schema(connection, settings.schema, require_active=True, minimum_version=4)
    return ManagedCaseClient(
        build_conversation_service(
            actor=actor, token=token, settings=settings, quote_database=quote_database
        ),
        token,
    )
