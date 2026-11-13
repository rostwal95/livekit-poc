"""Configured bounded image HTTP consumer; no setup, authority or model calls."""

from __future__ import annotations

from types import MappingProxyType

from .document_contracts import DocumentRequest, DocumentResult
from .http_client import AttemptObservation, SpecialistClient, SpecialistEndpoint


class DocumentSpecialistClient:
    """Own one existing finite transport; image results cannot authorize actions."""

    def __init__(
        self,
        endpoint: SpecialistEndpoint,
        authorization: str,
        *,
        timeout_ms: int = 5000,
        max_active: int = 4,
        cleanup_ms: int = 1000,
    ) -> None:
        self._transport = SpecialistClient(
            endpoint,
            authorization,
            timeout_ms=timeout_ms,
            max_active=max_active,
            cleanup_ms=cleanup_ms,
        )

    @property
    def active(self) -> int:
        return self._transport.active

    def metrics(self) -> MappingProxyType[str, int]:
        return self._transport.metrics()

    async def invoke(self, request: DocumentRequest) -> DocumentResult:
        return await self._transport.invoke_document(request)

    async def status(self, request: DocumentRequest) -> AttemptObservation:
        return await self._transport.status_document(request)

    async def cancel(self, request: DocumentRequest) -> AttemptObservation:
        return await self._transport.cancel_document(request)

    async def close(self) -> None:
        await self._transport.close()


DocumentSpecialistHttpClient = DocumentSpecialistClient
