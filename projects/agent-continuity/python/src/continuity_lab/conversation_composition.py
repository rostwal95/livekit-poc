"""Trusted composition shared by HTTP and the session-bound native consumer."""

from pathlib import Path

from .authorization import AuthenticatedActor, BearerToken, TokenDirectory
from .case_projection import PostgresCaseProjection
from .case_service import ScopedCaseService
from .conversation_service import AsyncConversationService, ConversationService
from .managed_admission import PostgresManagedAdmission
from .postgres_case import PostgresCaseAuthority
from .postgres_effects import PostgresEffects
from .postgres_lifecycle import PostgresLifecycle
from .postgres_settings import PostgresSettings
from .postgres_store import PostgresExecutionStore
from .quote_producer import TrustedQuoteProducer
from .quote_reader import ReadOnlyQuoteSupplier


def build_conversation_service(
    *,
    actor: AuthenticatedActor,
    token: BearerToken,
    settings: PostgresSettings,
    quote_database: Path | None = None,
) -> AsyncConversationService:
    """Blocking startup; callers offload this factory before serving media."""
    executions = PostgresExecutionStore(settings)
    cases = PostgresCaseAuthority(executions)
    lifecycle = PostgresLifecycle(executions, cases=cases)
    effects = PostgresEffects(executions, cases=cases)
    directory = TokenDirectory({token: actor})
    case_service = ScopedCaseService(directory, cases, lifecycle, effects=effects)
    producer = (
        None
        if quote_database is None
        else TrustedQuoteProducer(cases, lifecycle, ReadOnlyQuoteSupplier(quote_database))
    )
    service = ConversationService(
        directory,
        PostgresManagedAdmission(executions, cases=cases, lifecycle=lifecycle),
        PostgresCaseProjection(executions, cases=cases, lifecycle=lifecycle, effects=effects),
        case_service,
        producer,
    )
    return AsyncConversationService(service, maximum=4, shutdown_timeout=5)
