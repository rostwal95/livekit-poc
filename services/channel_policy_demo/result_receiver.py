"""Explicit local P3-to-P2 result-receiver composition; imports start no I/O.

The application supplies one fixed loopback endpoint and publisher capability.
The remote receipt accepts original result bytes, never a carrier send or hearing.
"""

from __future__ import annotations

import asyncio as asyncio  # noqa: PLC0414 - explicit typed compatibility export
import json
import logging
import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal, cast
from uuid import UUID

import aiohttp as aiohttp  # noqa: PLC0414 - explicit typed compatibility export

from continuity_lab.delivery_api import DeliveryIntent, DeliveryReceipt
from continuity_lab.work_api import WorkError, WorkScope

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
RESPONSE_BYTES = 2048
INTENT_BYTES = 16384
MappedCode = Literal[
    "unauthorized",
    "invalid_input",
    "identity_conflict",
    "capacity",
    "closed",
    "schema_mismatch",
    "acknowledgement_unknown",
    "storage_unavailable",
]
_ERRORS: dict[str, MappedCode] = {
    "AccessDenied": "unauthorized",
    "InvalidCommand": "invalid_input",
    "IdentityConflict": "identity_conflict",
    "Overloaded": "capacity",
    "Closed": "closed",
    "UpgradeRequired": "schema_mismatch",
    "AcknowledgementUnknown": "acknowledgement_unknown",
    "Unavailable": "storage_unavailable",
}


def _uuid(value: str) -> str:
    try:
        parsed = UUID(value)
        if type(value) is not str or str(parsed) != value or parsed.version != 4:
            raise ValueError
    except (ValueError, AttributeError, TypeError):
        raise WorkError("invalid_input") from None
    return value


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise WorkError("invalid_input")
        result[key] = value
    return result


def _invalid_constant(_: str) -> object:
    raise WorkError("invalid_input")


def _decode(raw: bytes) -> dict[str, object]:
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= RESPONSE_BYTES:
            raise ValueError
        value: object = json.loads(
            raw.decode("utf-8", "strict"),
            object_pairs_hook=_pairs,
            parse_constant=_invalid_constant,
        )
        if type(value) is not dict:
            raise ValueError
        return cast(dict[str, object], value)
    except (ValueError, UnicodeError, RecursionError, WorkError):
        raise WorkError("storage_unavailable") from None


def receipt_from(value: object, intent: DeliveryIntent) -> DeliveryReceipt:
    """Revalidate the exact P1 receipt, including its original result digest."""
    try:
        if type(value) is not dict or set(value) != {
            "delivery_id",
            "receipt_id",
            "receiver_id",
            "recipient_id",
            "result_sha256",
            "accepted_at_ms",
        }:
            raise ValueError
        receipt = DeliveryReceipt(**value)
        if (
            receipt.delivery_id,
            receipt.receiver_id,
            receipt.recipient_id,
            receipt.result_sha256,
        ) != (intent.delivery_id, intent.receiver_id, intent.recipient_id, intent.result_sha256):
            raise ValueError
        return receipt
    except (TypeError, ValueError, WorkError):
        raise WorkError("storage_unavailable") from None


class ChannelResultReceiver:
    """Two retained actual calls; closing a waiter never releases a remote call.

    This adapter owns its HTTP session only. The application separately owns P1,
    P2, the server process and any current-channel read adapter.
    """

    def __init__(
        self,
        *,
        port: int,
        publisher_token: str,
        receiver_id: str,
        scope: WorkScope,
        recipient_id: str,
        timeout_ms: int = 2000,
        cleanup_ms: int = 1000,
    ) -> None:
        if (
            type(port) is not int
            or not 1 <= port <= 65535
            or type(publisher_token) is not str
            or re.fullmatch(r"[A-Za-z0-9_-]{32,128}", publisher_token) is None
            or type(scope) is not WorkScope
            or type(recipient_id) is not str
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", recipient_id) is None
            or type(timeout_ms) is not int
            or not 20 <= timeout_ms <= 5000
            or type(cleanup_ms) is not int
            or not 20 <= cleanup_ms <= 2000
        ):
            raise WorkError("invalid_input")
        self._receiver_id = _uuid(receiver_id)
        self._scope = WorkScope(scope.tenant_id, scope.account_id)
        self._recipient_id = recipient_id
        self._port = port
        self._token = publisher_token
        self._timeout = timeout_ms / 1000
        self._cleanup = cleanup_ms / 1000
        self._calls: set[asyncio.Task[DeliveryReceipt | None]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._connector: aiohttp.TCPConnector | None = None
        self._session: aiohttp.ClientSession | None = None
        self._closing = False
        self._close_task: asyncio.Task[None] | None = None
        self._counts = {
            key: 0
            for key in (
                "accepted",
                "found",
                "missing",
                "rejected",
                "abandoned",
                "cleanup_incomplete",
            )
        }

    @property
    def receiver_id(self) -> str:
        return self._receiver_id

    @property
    def pending_count(self) -> int:
        return len(self._calls)

    @property
    def metrics(self) -> Mapping[str, int]:
        return MappingProxyType({**self._counts, "active": self.pending_count})

    def _bind(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        if self._loop is not loop:
            raise WorkError("invalid_input")

    def _intent(self, value: DeliveryIntent) -> DeliveryIntent:
        if type(value) is not DeliveryIntent or type(value.scope) is not WorkScope:
            raise WorkError("invalid_input")
        snapshot = DeliveryIntent(
            value.delivery_id,
            WorkScope(value.scope.tenant_id, value.scope.account_id),
            value.work_id,
            value.attempt_id,
            value.result_sha256,
            value.receiver_id,
            value.recipient_id,
            value.body,
            value.prepared_at_ms,
        )
        if snapshot.scope != self._scope:
            raise WorkError("unauthorized")
        if (snapshot.receiver_id, snapshot.recipient_id) != (self._receiver_id, self._recipient_id):
            raise WorkError("identity_conflict")
        if len(snapshot.canonical()) > INTENT_BYTES:
            raise WorkError("invalid_input")
        return snapshot

    async def accept(self, intent: DeliveryIntent) -> DeliveryReceipt:
        receipt = await self._call("accept", intent)
        if receipt is None:
            raise WorkError("acknowledgement_unknown")
        return receipt

    async def find(self, intent: DeliveryIntent) -> DeliveryReceipt | None:
        return await self._call("find", intent)

    async def _call(
        self, operation: Literal["accept", "find"], intent: DeliveryIntent
    ) -> DeliveryReceipt | None:
        self._bind()
        intent = self._intent(intent)
        if self._closing:
            raise WorkError("closed")
        if len(self._calls) >= 2:
            raise WorkError("capacity")
        task = asyncio.create_task(self._request(operation, intent), name="p3-p2-result-receiver")
        self._calls.add(task)

        def settled(done: asyncio.Task[DeliveryReceipt | None]) -> None:
            self._calls.discard(done)
            if not done.cancelled():
                done.exception()

        task.add_done_callback(settled)
        try:
            async with asyncio.timeout(self._timeout):
                return await asyncio.shield(task)
        except TimeoutError:
            self._counts["abandoned"] += 1
            raise WorkError(
                "acknowledgement_unknown" if operation == "accept" else "storage_unavailable"
            ) from None
        except asyncio.CancelledError:
            self._counts["abandoned"] += 1
            raise

    async def _request(
        self, operation: Literal["accept", "find"], intent: DeliveryIntent
    ) -> DeliveryReceipt | None:
        try:
            if self._session is None:
                if self._connector is None:
                    self._connector = aiohttp.TCPConnector(limit=2, limit_per_host=2)
                self._session = aiohttp.ClientSession(
                    connector=self._connector,
                    timeout=aiohttp.ClientTimeout(total=5, ceil_threshold=6),
                    trust_env=False,
                    auto_decompress=False,
                    skip_auto_headers={"User-Agent", "Accept-Encoding"},
                    cookie_jar=aiohttp.DummyCookieJar(),
                )
            async with self._session.post(
                f"http://127.0.0.1:{self._port}/v1/p2-result-receiver/{operation}",
                data=intent.canonical(),
                headers={
                    "Authorization": "Bearer " + self._token,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                skip_auto_headers={"User-Agent", "Accept-Encoding"},
                allow_redirects=False,
                max_line_size=2048,
                max_field_size=2048,
                max_headers=32,
                read_bufsize=2048,
            ) as response:
                lengths = response.headers.getall("Content-Length", [])
                if (
                    len(lengths) != 1
                    or re.fullmatch(r"[1-9][0-9]{0,3}", lengths[0]) is None
                    or int(lengths[0]) > RESPONSE_BYTES
                    or response.headers.getall("Content-Type", []) != ["application/json"]
                    or response.headers.getall("Cache-Control", []) != ["no-store"]
                    or "Content-Encoding" in response.headers
                    or "Transfer-Encoding" in response.headers
                ):
                    raise WorkError("storage_unavailable")
                raw = await response.content.readexactly(int(lengths[0]))
                value = _decode(raw)
                if value.get("schemaVersion") != 1 or type(value.get("schemaVersion")) is not int:
                    raise WorkError("storage_unavailable")
                if response.status != 200:
                    if (
                        response.status not in {400, 403, 409, 429, 503}
                        or set(value) != {"schemaVersion", "status", "error"}
                        or value["status"] != "error"
                        or type(value["error"]) is not str
                        or value["error"] not in _ERRORS
                    ):
                        raise WorkError("storage_unavailable")
                    # WorkError validates the finite translation again.
                    raise WorkError(_ERRORS[value["error"]])
                if set(value) != {"schemaVersion", "status", "receipt"}:
                    raise WorkError("storage_unavailable")
                if (
                    value["status"] == "missing"
                    and value["receipt"] is None
                    and operation == "find"
                ):
                    self._counts["missing"] += 1
                    return None
                if value["status"] != "accepted":
                    raise WorkError("storage_unavailable")
                receipt = receipt_from(value["receipt"], intent)
                self._counts["accepted" if operation == "accept" else "found"] += 1
                return receipt
        except asyncio.CancelledError:
            raise
        except WorkError as error:
            self._counts["rejected"] += 1
            if operation == "accept" and error.code == "storage_unavailable":
                raise WorkError("acknowledgement_unknown") from None
            raise
        except (
            aiohttp.ClientError,
            OSError,
            TimeoutError,
            asyncio.IncompleteReadError,
            RuntimeError,
        ):
            # aiohttp uses RuntimeError for session/factory lifetime failures.
            # This outer HTTP boundary must never reflect dependency text.
            self._counts["rejected"] += 1
            raise WorkError(
                "acknowledgement_unknown" if operation == "accept" else "storage_unavailable"
            ) from None

    async def close(self) -> None:
        self._bind()
        self._closing = True
        if self._close_task is None or (
            self._close_task.done()
            and (self._close_task.cancelled() or self._close_task.exception() is not None)
        ):
            self._close_task = asyncio.create_task(self._drain(), name="p3-p2-receiver-close")
            self._close_task.add_done_callback(
                lambda done: None if done.cancelled() else done.exception()
            )
        try:
            async with asyncio.timeout(self._cleanup):
                await asyncio.shield(self._close_task)
        except TimeoutError:
            self._counts["cleanup_incomplete"] += 1
            raise WorkError("cleanup_incomplete") from None

    async def _drain(self) -> None:
        if self._calls:
            await asyncio.gather(*tuple(self._calls), return_exceptions=True)
        failed = False
        if self._session is not None:
            try:
                await self._session.close()
            except Exception:  # noqa: BLE001 - outer explicit resource-close boundary
                failed = True
        # Requests settled first. Attempt this retained owner after the session,
        # including when its factory or close failed; retry still observes both.
        if self._connector is not None:
            try:
                await self._connector.close()
            except Exception:  # noqa: BLE001 - outer explicit resource-close boundary
                failed = True
        if failed:
            raise WorkError("cleanup_incomplete") from None
