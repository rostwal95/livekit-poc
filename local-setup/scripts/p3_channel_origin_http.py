"""Typed compatibility imports for the canonical channel-policy application.

Serving logic lives only in services.channel_policy_demo.origin_http.
This local path remains available to fixed adjacent qualification tooling.
"""

from services.channel_policy_demo.origin_http import (
    LOGGER,
    ChannelOriginHttp,
    ChannelOriginPort,
    HttpCode,
    OriginHttpEndpoint,
    OriginHttpError,
)

__all__ = [
    "LOGGER",
    "ChannelOriginHttp",
    "ChannelOriginPort",
    "HttpCode",
    "OriginHttpEndpoint",
    "OriginHttpError",
]
