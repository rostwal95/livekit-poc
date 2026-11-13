"""Configured public delivery-only processing; importing performs no setup or I/O.

The application owns the processor lifecycle and its shared result/case readers.
The processor owns its processing/feed/delivery clients. Discovery position never
acknowledges unknown delivery, and no result supplies action or human consent.
"""

from delegation_reliability import (
    CompletionProcessor,
    ProcessingAcknowledgement,
    ProcessingClient,
    ProcessingStep,
)


async def process_results(processor: CompletionProcessor, *, limit: int = 4) -> ProcessingStep:
    return await processor.process_once(limit=limit)


async def inspect_ack(
    client: ProcessingClient, *, event_id: str
) -> ProcessingAcknowledgement | None:
    return await client.acknowledgement(event_id=event_id)
