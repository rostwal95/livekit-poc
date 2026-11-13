"""P2 versioned channel data contracts; no durable runtime or authentication."""

from .codec import (
    MAX_TEXT_BYTES,
    MAX_WIRE_BYTES,
    AccountScope,
    ContractError,
    DecodedEvent,
    FrozenJson,
    JsonValue,
    ProviderScope,
    TrustedPrincipal,
    parse_event_json,
    produce_text_event,
)

__all__ = [
    "MAX_TEXT_BYTES",
    "MAX_WIRE_BYTES",
    "AccountScope",
    "ContractError",
    "DecodedEvent",
    "FrozenJson",
    "JsonValue",
    "ProviderScope",
    "TrustedPrincipal",
    "parse_event_json",
    "produce_text_event",
]
