"""Typed compatibility imports for the canonical channel-policy application.

Serving logic lives only in services.channel_policy_demo.wire.
This local path remains available to fixed adjacent qualification tooling.
"""

from services.channel_policy_demo.wire import (
    BODY_BYTES,
    FRAME_BYTES,
    LOOKUP_BYTES,
    P3_REVISION_MAX,
    ChannelAccountScope,
    ChannelOperationLookup,
    OriginWireError,
    PreparedChannelInput,
    WireCode,
    account_scope,
    channel_identifier,
    decode_object,
    json_text,
    parse_accept_frame,
    parse_lookup_frame,
    parse_prepared_payload,
    parse_profile_frame,
    require_p3_compatible,
    uuid_value,
)

__all__ = [
    "BODY_BYTES",
    "FRAME_BYTES",
    "LOOKUP_BYTES",
    "P3_REVISION_MAX",
    "ChannelAccountScope",
    "ChannelOperationLookup",
    "OriginWireError",
    "PreparedChannelInput",
    "WireCode",
    "account_scope",
    "channel_identifier",
    "decode_object",
    "json_text",
    "parse_accept_frame",
    "parse_lookup_frame",
    "parse_prepared_payload",
    "parse_profile_frame",
    "require_p3_compatible",
    "uuid_value",
]
