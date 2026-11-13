"""Bounded loopback publisher transport; the application owns its supplied service.

Imports start no listener. HTTP abandonment never cancels a started service
invocation. HTTP drain observes only transport and those service invocations; a
completed bounded service waiter can leave P1 I/O retained by its coordinator.
The application closes HTTP, then service/coordinator, then the shared case reader.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import math
import re
import socket
from dataclasses import dataclass, field
from functools import partial
from types import MappingProxyType
from typing import Literal, Protocol, cast

from delegation_reliability import CoordinatorError
from delegation_reliability.coordinator import CoordinatorCode

from .wire import (
    ChannelOperationLookup,
    OriginWireError,
    account_scope,
    parse_accept_frame,
    parse_lookup_frame,
    parse_profile_frame,
    uuid_value,
)

LOGGER = logging.getLogger("p3_channel_origin_http")
LOGGER.addHandler(logging.NullHandler())
_ROUTES = frozenset(
    {
        "/v1/investigations/inspect-profile",
        "/v1/investigations/lookup",
        "/v1/investigations/accept",
    }
)
_HEADERS = frozenset({"host", "authorization", "content-type", "content-length", "connection"})
HttpCode = Literal["invalid_configuration", "closed", "unavailable", "cleanup_incomplete"]


class OriginHttpError(RuntimeError):
    """Fixed operational code; received bytes and dependency text stay private."""

    def __init__(self, code: HttpCode) -> None:
        self.code = (
            code
            if type(code) is str
            and code in {"invalid_configuration", "closed", "unavailable", "cleanup_incomplete"}
            else "unavailable"
        )
        super().__init__(self.code)


class ChannelOriginPort(Protocol):
    """Transport-only port; no close ownership or hidden recovering work queue."""

    async def accept(self, raw: bytes) -> dict[str, object]: ...

    async def lookup(self, raw: bytes) -> dict[str, object] | None: ...

    async def inspect_profile(self, raw: bytes) -> None: ...


@dataclass(frozen=True, slots=True)
class OriginHttpEndpoint:
    host: Literal["127.0.0.1"]
    port: int

    @property
    def origin(self) -> str:
        return f"http://{self.host}:{self.port}"


@dataclass(eq=False, slots=True)
class _Connection:
    socket: socket.socket = field(repr=False)
    writer: asyncio.StreamWriter | None = field(default=None, repr=False)
    task: asyncio.Task[None] | None = field(default=None, repr=False)
    call: asyncio.Task[dict[str, object]] | None = field(default=None, repr=False)


def _seconds(value: object) -> float:
    if not isinstance(value, (int, float)) or type(value) not in (int, float):
        raise OriginHttpError("invalid_configuration")
    if not 0.02 <= value <= 5 or not math.isfinite(value):
        raise OriginHttpError("invalid_configuration")
    return float(value)


def _consume(task: asyncio.Task[object]) -> None:
    if not task.cancelled():
        task.exception()


def _receipt(value: object, expected: ChannelOperationLookup) -> dict[str, object]:
    if type(value) is not dict or set(value) != {
        "operationKey",
        "scope",
        "payloadDigest",
        "receiptId",
    }:
        raise CoordinatorError("invalid_stored_state")
    try:
        scope = account_scope(value["scope"])
        receipt_id = uuid_value(value["receiptId"])
    except OriginWireError:
        raise CoordinatorError("invalid_stored_state") from None
    if (
        value["operationKey"] != expected.operation_key
        or value["payloadDigest"] != expected.payload_sha256
        or scope != expected.scope
    ):
        raise CoordinatorError("invalid_stored_state")
    return {**expected.to_wire(), "receiptId": receipt_id}


def _encoded(value: dict[str, object]) -> bytes:
    try:
        raw = json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise CoordinatorError("invalid_stored_state") from None
    if not 0 < len(raw) <= 4096:
        raise CoordinatorError("invalid_stored_state")
    return raw


class ChannelOriginHttp:
    """Own one listener, at most eight sockets and four full handler lifetimes.

    Admission happens before socket accept, so saturated peers wait in the bounded
    kernel backlog rather than creating an unbounded application socket registry.
    A response timeout may finish HTTP observation while the handler/call remains
    retained. Successful HTTP drain covers only these service invocations and
    transport resources. A coordinator may still own P1 I/O after its service
    waiter settles: close HTTP, then service/coordinator, then the shared case
    reader. This host neither polls coordinator state nor closes application ports.
    """

    def __init__(
        self,
        service: ChannelOriginPort,
        *,
        operation_bearer: str,
        read_timeout_s: float = 2,
        call_timeout_s: float = 2,
        cleanup_timeout_s: float = 1,
    ) -> None:
        if (
            type(operation_bearer) is not str
            or re.fullmatch(r"[A-Za-z0-9_-]{43}", operation_bearer) is None
        ):
            raise OriginHttpError("invalid_configuration")
        self._read_timeout = _seconds(read_timeout_s)
        self._call_timeout = _seconds(call_timeout_s)
        self._cleanup_timeout = _seconds(cleanup_timeout_s)
        self._service = service
        self._authorization = ("Bearer " + operation_bearer).encode("ascii")
        self._loop: asyncio.AbstractEventLoop | None = None
        self._endpoint: OriginHttpEndpoint | None = None
        self._listener: socket.socket | None = None
        self._accept_task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._connections: set[_Connection] = set()
        self._handlers: set[_Connection] = set()
        self._calls: set[asyncio.Task[dict[str, object]]] = set()
        self._available = asyncio.Event()
        self._available.set()
        self._closing = False
        self._counts = {
            "started": 0,
            "known": 0,
            "rejected": 0,
            "timed_out": 0,
            "telemetry_failed": 0,
        }

    def _bind(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        if self._loop is not None and loop is not self._loop:
            raise OriginHttpError("invalid_configuration")
        self._loop = loop
        return loop

    def metrics(self) -> MappingProxyType[str, int | bool]:
        return MappingProxyType(
            {
                **self._counts,
                "active": len(self._calls),
                "handlers": len(self._handlers),
                "sockets": len(self._connections),
                "closing": self._closing,
            }
        )

    def _log(self, event: Literal["known", "rejected", "timed_out"], code: str) -> None:
        try:
            LOGGER.info("channel_origin_http", extra={"event": event, "code": code})
        except Exception:  # noqa: BLE001 - telemetry cannot replace a business observation
            self._counts["telemetry_failed"] += 1

    async def start(self, port: int = 0) -> OriginHttpEndpoint:
        loop = self._bind()
        if type(port) is not int or not 0 <= port <= 65535:
            raise OriginHttpError("invalid_configuration")
        if self._closing:
            raise OriginHttpError("closed")
        if self._endpoint is not None:
            if port not in (0, self._endpoint.port):
                raise OriginHttpError("invalid_configuration")
            return self._endpoint
        listener: socket.socket | None = None
        try:
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.setblocking(False)
            listener.bind(("127.0.0.1", port))
            listener.listen(8)
            endpoint = OriginHttpEndpoint("127.0.0.1", int(listener.getsockname()[1]))
        except OSError:
            if listener is not None:
                listener.close()
            raise OriginHttpError("unavailable") from None
        # No suspension precedes ownership registration or follows task creation.
        self._listener, self._endpoint = listener, endpoint
        accept = self._accept()
        try:
            self._accept_task = loop.create_task(accept, eager_start=False)
        except Exception:  # noqa: BLE001 - task setup cannot leak a listener
            accept.close()
            listener.close()
            self._listener, self._endpoint = None, None
            raise OriginHttpError("unavailable") from None
        self._accept_task.add_done_callback(_consume)
        return endpoint

    async def _accept(self) -> None:
        loop = self._bind()
        listener = self._listener
        assert listener is not None
        while not self._closing:
            if len(self._connections) >= 8:
                self._available.clear()
                await self._available.wait()
                continue
            try:
                accepted, address = await loop.sock_accept(listener)
            except OSError:
                if self._closing:
                    return
                self._closing = True
                return
            if self._closing or address[0] != "127.0.0.1":
                accepted.close()
                continue
            if len(self._handlers) >= 4:
                self._counts["rejected"] += 1
                self._log("rejected", "capacity")
                accepted.close()
                continue
            accepted.setblocking(False)
            connection = _Connection(accepted)
            self._connections.add(connection)
            self._handlers.add(connection)
            serve = self._serve(connection)
            try:
                connection.task = loop.create_task(serve, eager_start=False)
            except Exception:  # noqa: BLE001 - retain no socket without an owner task
                serve.close()
                accepted.close()
                self._connections.discard(connection)
                self._handlers.discard(connection)
                self._closing = True
                listener.close()
                self._counts["rejected"] += 1
                self._log("rejected", "unavailable")
                return
            connection.task.add_done_callback(partial(self._handler_settled, connection))

    async def _request(self, reader: asyncio.StreamReader) -> tuple[str, bytes]:
        async with asyncio.timeout(self._read_timeout):
            try:
                head = await reader.readuntil(b"\r\n\r\n")
            except (asyncio.IncompleteReadError, asyncio.LimitOverrunError):
                raise CoordinatorError("invalid_input") from None
            if len(head) > 4096:
                raise CoordinatorError("invalid_input")
            lines = head[:-4].split(b"\r\n")
            if not 1 <= len(lines) <= 33:
                raise CoordinatorError("invalid_input")
            first = lines[0].split(b" ")
            if len(first) != 3 or first[0] != b"POST" or first[2] != b"HTTP/1.1":
                raise CoordinatorError("invalid_input")
            try:
                route = first[1].decode("ascii")
            except UnicodeError:
                raise CoordinatorError("invalid_input") from None
            if route not in _ROUTES:
                raise CoordinatorError("invalid_input")
            headers: dict[str, bytes] = {}
            for line in lines[1:]:
                name, separator, value = line.partition(b":")
                if (
                    not separator
                    or re.fullmatch(rb"[A-Za-z-]+", name) is None
                    or any(byte < 32 or byte > 126 for byte in value)
                ):
                    raise CoordinatorError("invalid_input")
                key = name.decode("ascii").lower()
                if key in headers or key not in _HEADERS:
                    raise CoordinatorError("invalid_input")
                headers[key] = value.strip(b" ")
            if set(headers) != _HEADERS:
                raise CoordinatorError("invalid_input")
            endpoint = self._endpoint
            assert endpoint is not None
            if (
                headers["host"] != f"127.0.0.1:{endpoint.port}".encode()
                or headers["content-type"] != b"application/json"
                or headers["connection"].lower() != b"close"
                or re.fullmatch(rb"[1-9][0-9]{0,4}", headers["content-length"]) is None
            ):
                raise CoordinatorError("invalid_input")
            if not hmac.compare_digest(headers["authorization"], self._authorization):
                raise CoordinatorError("unauthorized")
            length = int(headers["content-length"])
            if length > 32768:
                raise CoordinatorError("invalid_input")
            try:
                body = await reader.readexactly(length)
            except asyncio.IncompleteReadError:
                raise CoordinatorError("invalid_input") from None
            return route, body

    async def _dispatch(self, route: str, raw: bytes) -> dict[str, object]:
        if route == "/v1/investigations/inspect-profile":
            profile_id = parse_profile_frame(raw)
            await self._service.inspect_profile(raw)
            return {"schemaVersion": 1, "status": "known", "profileId": profile_id, "ready": True}
        if route == "/v1/investigations/lookup":
            expected = parse_lookup_frame(raw)
            value = await self._service.lookup(raw)
            observation: dict[str, object] = (
                {"status": "absent"}
                if value is None
                else {"status": "accepted", "receipt": _receipt(value, expected)}
            )
            return {"schemaVersion": 1, "status": "known", "observation": observation}
        expected = parse_accept_frame(raw).lookup()
        receipt = _receipt(await self._service.accept(raw), expected)
        return {"schemaVersion": 1, "status": "known", "receipt": receipt}

    async def _response(self, writer: asyncio.StreamWriter, status: int, body: bytes) -> None:
        reason = {
            200: "OK",
            400: "Bad Request",
            403: "Forbidden",
            409: "Conflict",
            429: "Too Many Requests",
            503: "Service Unavailable",
        }[status]
        writer.write(
            (
                f"HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\nConnection: close\r\nCache-Control: no-store\r\n\r\n"
            ).encode("ascii")
            + body
        )
        async with asyncio.timeout(self._read_timeout):
            await writer.drain()

    async def _serve(self, connection: _Connection) -> None:
        call: asyncio.Task[dict[str, object]] | None = None
        writer: asyncio.StreamWriter | None = None
        try:
            reader, writer = await asyncio.open_connection(sock=connection.socket, limit=4096)
            connection.writer = writer
            self._counts["started"] += 1
            route, raw = await self._request(reader)
            if self._closing:
                raise CoordinatorError("closed")
            if len(self._calls) >= 4:
                raise CoordinatorError("capacity")
            operation = self._dispatch(route, raw)
            try:
                call = asyncio.create_task(operation, eager_start=False)
            except Exception:  # noqa: BLE001 - failed scheduling owns no live service coroutine
                operation.close()
                raise CoordinatorError("internal_error") from None
            connection.call = call
            self._calls.add(call)
            call.add_done_callback(partial(self._settled, connection))
            try:
                async with asyncio.timeout(self._call_timeout):
                    value = await asyncio.shield(call)
                body = _encoded(value)
            except TimeoutError:
                self._counts["timed_out"] += 1
                timeout_code: CoordinatorCode = (
                    "acknowledgement_unknown" if route.endswith("/accept") else "deadline_exceeded"
                )
                self._log("timed_out", timeout_code)
                raise CoordinatorError(timeout_code) from None
            self._counts["known"] += 1
            self._log("known", "ok")
            await self._response(writer, 200, body)
        except (OriginWireError, CoordinatorError) as error:
            code = (
                CoordinatorError(cast(CoordinatorCode, error.code)).code
                if isinstance(error, CoordinatorError)
                else "invalid_input"
            )
            if isinstance(error, OriginWireError):
                code = {
                    "InvalidCommand": "invalid_input",
                    "AccessDenied": "unauthorized",
                    "IdentityConflict": "identity_conflict",
                }[OriginWireError(error.code).code]
            status = (
                403
                if code == "unauthorized"
                else 409
                if code == "identity_conflict"
                else 429
                if code == "capacity"
                else 400
                if code == "invalid_input"
                else 503
            )
            self._counts["rejected"] += 1
            self._log("rejected", code)
            if writer is not None and not writer.is_closing():
                try:
                    await self._response(
                        writer,
                        status,
                        _encoded({"schemaVersion": 1, "status": "error", "code": code}),
                    )
                except (OSError, TimeoutError, RuntimeError):
                    pass
        except (OSError, TimeoutError):
            self._counts["rejected"] += 1
            self._log("rejected", "unavailable")
        except Exception:  # noqa: BLE001 - outer transport containment excludes dependency text
            self._counts["rejected"] += 1
            self._log("rejected", "internal_error")
            if writer is not None and not writer.is_closing():
                try:
                    await self._response(
                        writer,
                        503,
                        _encoded({"schemaVersion": 1, "status": "error", "code": "internal_error"}),
                    )
                except (OSError, TimeoutError, RuntimeError):
                    pass
        finally:
            if writer is not None:
                writer.close()
            else:
                connection.socket.close()
            if writer is not None:
                try:
                    await writer.wait_closed()
                except (OSError, RuntimeError):
                    pass
            self._connections.discard(connection)
            self._available.set()

    def _retire(self, connection: _Connection) -> None:
        task, call = connection.task, connection.call
        if task is not None and task.done() and (call is None or call.done()):
            self._handlers.discard(connection)

    def _handler_settled(self, connection: _Connection, task: asyncio.Task[None]) -> None:
        _consume(task)
        self._retire(connection)

    def _settled(self, connection: _Connection, call: asyncio.Task[dict[str, object]]) -> None:
        _consume(call)
        self._calls.discard(call)
        self._retire(connection)

    async def _finish_close(self) -> None:
        listener = self._listener
        if listener is not None:
            listener.close()
        accept = self._accept_task
        if accept is not None:
            if not accept.done():
                accept.cancel()
            await asyncio.gather(accept, return_exceptions=True)
        tasks = []
        for connection in tuple(self._connections):
            if connection.writer is not None:
                connection.writer.close()
            else:
                connection.socket.close()
            if connection.task is not None:
                tasks.append(connection.task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        calls = tuple(self._calls)
        if calls:
            await asyncio.gather(*calls, return_exceptions=True)

    async def close(self) -> None:
        """Drain transport/service invocations; the application closes Core next."""
        self._bind()
        self._closing = True
        self._available.set()
        if (
            self._close_task is not None
            and self._close_task.done()
            and (self._close_task.cancelled() or self._close_task.exception() is not None)
        ):
            self._close_task = None
        if self._close_task is None:
            finish = self._finish_close()
            try:
                self._close_task = asyncio.create_task(finish, eager_start=False)
            except Exception:  # noqa: BLE001 - unscheduled cleanup retains its application owners
                finish.close()
                raise OriginHttpError("cleanup_incomplete") from None
            self._close_task.add_done_callback(_consume)
        try:
            async with asyncio.timeout(self._cleanup_timeout):
                await asyncio.shield(self._close_task)
        except TimeoutError:
            raise OriginHttpError("cleanup_incomplete") from None
        except Exception:  # noqa: BLE001 - cleanup diagnostics never serialize dependency text
            raise OriginHttpError("cleanup_incomplete") from None
        if self._connections or self._calls or self._handlers:
            raise OriginHttpError("cleanup_incomplete")
