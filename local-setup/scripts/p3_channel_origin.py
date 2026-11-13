"""Typed compatibility imports for the canonical channel-policy application.

Serving logic lives only in services.channel_policy_demo.origin.
This local path remains available to fixed adjacent qualification tooling.
"""

from services.channel_policy_demo.origin import (
    LOGGER,
    ChannelOriginBinding,
    ChannelOriginService,
    Event,
)

__all__ = ["LOGGER", "ChannelOriginBinding", "ChannelOriginService", "Event"]
