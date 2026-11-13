"""Configured read-only image journey; caller owns clients and immutable sources."""

from __future__ import annotations

import time
from typing import Protocol

from delegation_reliability.contracts import ContractError
from delegation_reliability.document_contracts import (
    DocumentRequest,
    DocumentResult,
    encode_document_request,
    encode_document_result,
    match_document_result,
    parse_document_request,
    parse_document_result,
)


class DocumentInvocationPort(Protocol):
    async def invoke(self, request: DocumentRequest) -> DocumentResult: ...


async def extract_document(
    *, client: DocumentInvocationPort, request: DocumentRequest
) -> DocumentResult:
    """Match a typed HTTP observation; factual fixture review remains separate."""
    snapshot = parse_document_request(encode_document_request(request))
    observed = await client.invoke(snapshot)
    result = parse_document_result(encode_document_result(observed))
    if (
        match_document_result(snapshot, result, observed_at_ms=time.time_ns() // 1_000_000)
        != "candidate"
    ):
        raise ContractError("expired")
    return result
