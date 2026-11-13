"""Explicit signed synthetic SMS over one fixed local gateway connection.

Original command identity/body/time determine provider bytes. A fresh MAC header
does not change those bytes. No retry, sender association or case revision occurs
here; owner bootstrap must associate the configured synthetic sender first.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import math
import re
import time
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar, cast

from .operator_contract import (
    OperatorCode,
    OperatorError,
    SmsCommand,
    SmsObservation,
    decode,
    encode,
    fields,
    require,
    revision,
    schema,
    timestamp,
    uuid_value,
)

if TYPE_CHECKING:
    import aiohttp

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class SmsRoute:
    tenant_id: str
    provider_account_id: str
    sender_id: str = "demo_sms_sender"
    port: int = 11025

    def __post_init__(self) -> None:
        require(
            type(self.tenant_id) is str
            and re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", self.tenant_id, re.ASCII) is not None
        )
        for value in (self.provider_account_id, self.sender_id):
            require(
                type(value) is str
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value, re.ASCII) is not None
            )
        require(type(self.port) is int and 1 <= self.port <= 65535)


def signed_sms(
    command: SmsCommand, route: SmsRoute, signed_at_seconds: int
) -> tuple[bytes, dict[str, str]]:
    require(type(command) is SmsCommand and type(route) is SmsRoute)
    require(type(signed_at_seconds) is int and 1000000000 <= signed_at_seconds <= 9999999999)
    # Revalidate immutable public values at the trust boundary.
    original = SmsCommand(command.command_id, command.occurred_at, command.body)
    configured = SmsRoute(route.tenant_id, route.provider_account_id, route.sender_id, route.port)
    raw = encode(
        {
            "schemaVersion": 1,
            "eventId": original.event_id,
            "messageId": original.event_id,
            "senderId": configured.sender_id,
            "body": original.body,
            "occurredAt": original.occurred_at,
        },
        32768,
    )
    stamp = str(signed_at_seconds)
    prefix = f"p2.fake_sms.v1\n{configured.tenant_id}\nfake_sms\n{configured.provider_account_id}\n{stamp}\n".encode()
    # Exactly the gateway's declared PUBLIC synthetic_v1 material; never a
    # real carrier key or an environment/provider credential.
    signature = hmac.new(bytes([0x4F]) * 32, prefix + raw, hashlib.sha256).hexdigest()
    return raw, {
        "Content-Type": "application/json",
        "Connection": "close",
        "X-P2-Timestamp": stamp,
        "X-P2-Signature": signature,
    }


def accepted_sms(raw: bytes, command: SmsCommand) -> SmsObservation:
    value = fields(decode(raw, 4096), {"schemaVersion", "kind", "receipt", "replayed"})
    schema(value["schemaVersion"])
    require(value["kind"] == "channel.receipt")
    r = fields(
        value["receipt"], {"receiptId", "eventId", "messageId", "acceptanceSequence", "acceptedAt"}
    )
    return SmsObservation(
        command.command_id,
        cast(bool, value["replayed"]),
        uuid_value(r["receiptId"]),
        cast(str, r["eventId"]),
        cast(str, r["messageId"]),
        revision(r["acceptanceSequence"], zero=False),
        timestamp(r["acceptedAt"]),
    )


def _task(action: Coroutine[object, object, T], *, cleanup: bool = False) -> asyncio.Task[T]:
    try:
        result = asyncio.create_task(action, eager_start=False)
    except BaseException as error:
        action.close()
        if isinstance(error, Exception):
            raise OperatorError("cleanup_incomplete" if cleanup else "unavailable") from None
        raise
    result.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    return result


class ChannelPolicySmsClient:
    """One actual call; waiter loss retains it and its session through drain.

    The operator host drains before this client, which drains before Node. End
    does not close this separately authorized dormant channel owner.
    """

    def __init__(
        self, route: SmsRoute, *, observer_timeout_s: float = 3, cleanup_timeout_s: float = 1
    ) -> None:
        require(type(route) is SmsRoute)
        self._route = SmsRoute(
            route.tenant_id, route.provider_account_id, route.sender_id, route.port
        )
        for value in (observer_timeout_s, cleanup_timeout_s):
            require(type(value) in (int, float) and 0.02 <= value <= 5 and math.isfinite(value))
        self._timeout, self._cleanup = float(observer_timeout_s), float(cleanup_timeout_s)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._session: aiohttp.ClientSession | None = None
        self._connector: aiohttp.TCPConnector | None = None
        self._call: asyncio.Task[SmsObservation] | None = None
        self._closing: asyncio.Task[None] | None = None
        self._closed = False

    def _bind(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        require(self._loop is None or self._loop is loop)
        self._loop = loop
        return loop

    @property
    def pending_count(self) -> int:
        return int(self._call is not None and not self._call.done())

    async def _send_actual(self, command: SmsCommand) -> SmsObservation:
        attempted = False
        try:
            import aiohttp

            if self._connector is None:
                self._connector = aiohttp.TCPConnector(limit=1, limit_per_host=1)
            if self._session is None:
                # Register each returned owner before the next factory can
                # fail. A session-constructor failure still leaves a connector
                # that this client must close explicitly.
                self._session = aiohttp.ClientSession(
                    connector=self._connector,
                    timeout=aiohttp.ClientTimeout(total=3),
                    trust_env=False,
                )
            raw, headers = signed_sms(command, self._route, int(time.time()))
            attempted = True
            async with self._session.post(
                f"http://127.0.0.1:{self._route.port}/webhooks/fake-sms",
                data=raw,
                headers=headers,
                allow_redirects=False,
            ) as response:
                # Never follow a redirect or forward simulation headers beyond
                # the configured listener; uncertain acceptance is explicit.
                if response.status != 200:
                    code = {
                        400: "invalid_input",
                        401: "unauthorized",
                        403: "unauthorized",
                        409: "conflict",
                        429: "capacity",
                    }.get(response.status, "outcome_unknown")
                    raise OperatorError(cast(OperatorCode, code))
                if (
                    response.content_type != "application/json"
                    or response.content_length is None
                    or not 0 < response.content_length <= 4096
                ):
                    raise OperatorError("outcome_unknown")
                chunks = bytearray()
                while True:
                    chunk = await response.content.read(4097 - len(chunks))
                    if not chunk:
                        break
                    chunks.extend(chunk)
                    if len(chunks) > 4096:
                        raise OperatorError("outcome_unknown")
                if len(chunks) != response.content_length:
                    raise OperatorError("outcome_unknown")
                try:
                    return accepted_sms(bytes(chunks), command)
                except OperatorError:
                    raise OperatorError("outcome_unknown") from None
        except asyncio.CancelledError:
            raise
        except OperatorError:
            raise
        except Exception:  # noqa: BLE001 - startup and possible acceptance share one finite boundary
            raise OperatorError("outcome_unknown" if attempted else "unavailable") from None

    async def send(self, command: SmsCommand) -> SmsObservation:
        loop = self._bind()
        require(not self._closed, "closed")
        require(type(command) is SmsCommand)
        copied = SmsCommand(command.command_id, command.occurred_at, command.body)
        current = asyncio.current_task()
        if current is not None and current.cancelling():
            raise asyncio.CancelledError
        require(self._call is None or self._call.done(), "capacity")
        self._call = _task(self._send_actual(copied))
        try:
            async with asyncio.timeout_at(loop.time() + self._timeout):
                return await asyncio.shield(self._call)
        except TimeoutError:
            raise OperatorError("outcome_unknown") from None

    async def _finish_close(self) -> None:
        if self._call is not None:
            await asyncio.gather(asyncio.shield(self._call), return_exceptions=True)
        failed = False
        if self._session is not None:
            try:
                await self._session.close()
            except Exception:  # noqa: BLE001 - close independent registered owner before reporting failure
                failed = True
        if self._connector is not None:
            try:
                await self._connector.close()
            except Exception:  # noqa: BLE001 - finite cleanup; original resources remain available to retry
                failed = True
        if failed:
            raise OperatorError("cleanup_incomplete")

    async def close(self) -> None:
        loop = self._bind()
        self._closed = True
        if (
            self._closing is not None
            and self._closing.done()
            and (self._closing.cancelled() or self._closing.exception() is not None)
        ):
            self._closing = None
        if self._closing is None:
            self._closing = _task(self._finish_close(), cleanup=True)
        try:
            async with asyncio.timeout_at(loop.time() + self._cleanup):
                await asyncio.shield(self._closing)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - retained cleanup never leaks dependency text
            raise OperatorError("cleanup_incomplete") from None
