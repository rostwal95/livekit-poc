"""Explicit compatibility exports for the canonical channel-policy application.

Serving implementation lives only in services.channel_policy_demo.result_receiver.
This adjacent path remains available to the existing qualification tools.
"""

from services.channel_policy_demo.result_receiver import (
    INTENT_BYTES,
    LOGGER,
    RESPONSE_BYTES,
    ChannelResultReceiver,
    MappedCode,
    aiohttp,
    asyncio,
    receipt_from,
)

__all__ = [
    "INTENT_BYTES",
    "LOGGER",
    "RESPONSE_BYTES",
    "ChannelResultReceiver",
    "MappedCode",
    "aiohttp",
    "asyncio",
    "receipt_from",
]
