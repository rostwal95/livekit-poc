"""Separate operator authorization for the compact optional browser application.

The browser receives no administrative/native/SMS signing capability. This host
owns only actual exchanges and sockets; Parent shutdown drains it before its
borrowed room, SMS and application ports. End leaves this host available.
"""

from __future__ import annotations

import logging

from ._bounded_loopback_http import BoundedLoopbackHttp, Event, HttpRejection, _Connection
from .operator import ChannelPolicyOperator
from .operator_contract import require

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())


def _observe(event: Event, code: str) -> None:
    LOGGER.info("channel_policy_operator_http", extra={"event": event, "code": code})


class ChannelPolicyOperatorHttp(BoundedLoopbackHttp):
    def __init__(
        self,
        operator: ChannelPolicyOperator,
        *,
        bearer: str,
        call_timeout_s: float = 15,
        cleanup_timeout_s: float = 1,
    ) -> None:
        require(type(operator) is ChannelPolicyOperator)
        self._operator = operator
        super().__init__(
            operator,
            purpose="operator",
            bearer=bearer,
            call_timeout_s=call_timeout_s,
            cleanup_timeout_s=cleanup_timeout_s,
            observer=_observe,
        )

    async def _response(self, connection: _Connection, status: int, body: bytes) -> None:
        # There is no await between this captured lifecycle check and initiating
        # the socket write. A completed read alone never authorizes late A.
        if status == 200 and not self._operator.response_is_current(body):
            raise HttpRejection("closed")
        await super()._response(connection, status, body)
