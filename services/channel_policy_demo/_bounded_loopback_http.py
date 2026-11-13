"""Private closed-purpose loopback HTTP transport for borrowed application ports.

Imports bind nothing. Each application owns its borrowed dependency's separate drain. This transport
stops admission and retains actual calls/sockets through observer cancellation,
but never closes borrowed application ports or manufactures input authority.
"""

from __future__ import annotations

import asyncio
import hmac
import inspect
import json
import math
import re
import socket
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from functools import partial
from types import FunctionType, MappingProxyType, MethodType
from typing import Any, Literal, Protocol, TypeVar, cast

_HEADERS = frozenset({"host", "authorization", "content-type", "content-length", "connection"})
HostCode = Literal["invalid_configuration", "unavailable", "closed", "cleanup_incomplete"]
Purpose = Literal["native_prepare", "worker_current_result", "operator"]
HttpCode = Literal[
    "invalid_input",
    "unauthorized",
    "forbidden",
    "idempotency_conflict",
    "capacity",
    "closed",
    "unavailable",
    "cleanup_incomplete",
    "conflict",
    "outcome_unknown",
    "recovery_required",
]
Event = Literal["prepared", "read", "rejected", "timed_out"]
Observer = Callable[[Event, str], None]
_CODES: dict[str, HttpCode] = {
    "invalid_request": "invalid_input",
    "invalid_input": "invalid_input",
    "unauthorized": "unauthorized",
    "forbidden": "forbidden",
    "idempotency_conflict": "idempotency_conflict",
    "capacity_exhausted": "capacity",
    "capacity": "capacity",
    "closed": "closed",
    "dependency_unavailable": "unavailable",
    "acknowledgement_unknown": "unavailable",
    "unavailable": "unavailable",
    "cleanup_incomplete": "cleanup_incomplete",
    "conflict": "conflict",
    "outcome_unknown": "outcome_unknown",
    "recovery_required": "recovery_required",
}


@dataclass(frozen=True, slots=True)
class _Profile:
    route: bytes
    request_bytes: int
    response_bytes: int
    success: Literal["prepared", "read"]
    maximum_timeout: float


_PROFILES = MappingProxyType(
    {
        "native_prepare": _Profile(b"/v1/native/prepare", 32768, 2048, "prepared", 4),
        "worker_current_result": _Profile(
            b"/v1/channel-policy/current-result", 1024, 32768, "read", 1
        ),
        "operator": _Profile(b"/v1/channel-policy-demo/", 32768, 16384, "read", 15),
    }
)


class BoundedHttpError(Exception):
    """Finite process-boundary diagnostic, without dependency text or received data."""

    def __init__(self, code: HostCode = "unavailable") -> None:
        self.code = (
            code
            if type(code) is str
            and code in {"invalid_configuration", "unavailable", "closed", "cleanup_incomplete"}
            else "unavailable"
        )
        super().__init__(self.code)


def host_error_code(error: BaseException) -> HostCode:
    try:
        value = inspect.getattr_static(error, "code", None)
    except Exception:  # noqa: BLE001 - finite boundary without dependency getters
        return "unavailable"
    return (
        cast(HostCode, value)
        if type(value) is str
        and value in {"invalid_configuration", "unavailable", "closed", "cleanup_incomplete"}
        else "unavailable"
    )


class HttpRejection(Exception):
    def __init__(self, code: HttpCode = "invalid_input") -> None:
        self.code = code
        super().__init__(code)


class ExchangePort(Protocol):
    """Application owns its DTO/authority; transport owns only exchange calls."""

    async def exchange(self, raw: bytes) -> bytes: ...


class Endpoint(Protocol):
    @property
    def host(self) -> Literal["127.0.0.1"]: ...
    @property
    def port(self) -> int: ...


@dataclass(frozen=True, slots=True)
class LoopbackEndpoint:
    host: Literal["127.0.0.1"]
    port: int

    def __post_init__(self) -> None:
        if (
            type(self.host) is not str
            or self.host != "127.0.0.1"
            or type(self.port) is not int
            or not 1 <= self.port <= 65535
        ):
            raise BoundedHttpError("invalid_configuration")


@dataclass(eq=False, slots=True)
class _Connection:
    socket: socket.socket = field(repr=False)
    task: asyncio.Task[None] | None = field(default=None, repr=False)
    call: asyncio.Task[bytes] | None = field(default=None, repr=False)


def _seconds(value: object, maximum: float) -> float:
    if (
        type(value) not in (int, float)
        or not 0.02 <= cast(float, value) <= maximum
        or not math.isfinite(cast(float, value))
    ):
        raise BoundedHttpError("invalid_configuration")
    return float(cast(float, value))


def _code(error: BaseException) -> HttpCode:
    try:
        value = inspect.getattr_static(error, "code", None)
    except Exception:  # noqa: BLE001 - static finite dependency error boundary
        return "unavailable"
    return _CODES.get(value, "unavailable") if type(value) is str else "unavailable"


def _encode(value: dict[str, object], maximum: int = 2048) -> bytes:
    try:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
            "utf-8", "strict"
        )
        if not 0 < len(raw) <= maximum:
            raise ValueError
        return raw
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise HttpRejection("unavailable") from None


_T = TypeVar("_T")


def _task(
    loop: asyncio.AbstractEventLoop, operation: Coroutine[Any, Any, _T], *, cleanup: bool = False
) -> asyncio.Task[_T]:
    try:
        return loop.create_task(operation, eager_start=False)
    except BaseException as error:
        operation.close()
        if isinstance(error, Exception):
            raise BoundedHttpError("cleanup_incomplete" if cleanup else "unavailable") from None
        raise


def _consume(task: asyncio.Task[object]) -> None:
    if not task.cancelled():
        task.exception()


class BoundedLoopbackHttp:
    """One closed-purpose listener, four full call owners, eight actual sockets.

    Socket admission uses a synchronous readiness callback, so no accepted socket
    can return after an abandoned accept await. Calls are reserved before their
    task can run. Timeouts/disconnects preserve started calls and handler capacity
    until actual settlement. This transport owns no borrowed application close capability.
    """

    def __init__(
        self,
        application: ExchangePort,
        *,
        purpose: Purpose,
        bearer: str,
        call_timeout_s: float,
        cleanup_timeout_s: float,
        observer: Observer,
    ) -> None:
        if (
            type(purpose) is not str
            or purpose not in _PROFILES
            or type(bearer) is not str
            or re.fullmatch(r"[A-Za-z0-9_-]{43}", bearer) is None
        ):
            raise BoundedHttpError("invalid_configuration")
        self._profile: _Profile = _PROFILES[purpose]
        self._purpose: Purpose = purpose
        self._call_timeout: float = _seconds(call_timeout_s, self._profile.maximum_timeout)
        self._cleanup_timeout: float = _seconds(cleanup_timeout_s, 5)
        descriptor = inspect.getattr_static(type(application), "exchange", None)
        if (
            type(descriptor) is not FunctionType
            or not inspect.iscoroutinefunction(descriptor)
            or inspect.getattr_static(application, "exchange", None) is not descriptor
        ):
            raise BoundedHttpError("invalid_configuration")
        try:
            inspect.signature(descriptor).bind(application, b"")
        except (TypeError, ValueError):
            raise BoundedHttpError("invalid_configuration") from None
        self._exchange: Callable[[bytes], Coroutine[Any, Any, bytes]] = cast(
            Callable[[bytes], Coroutine[Any, Any, bytes]], MethodType(descriptor, application)
        )
        self._observer: Observer = observer
        self._authorization: bytes = ("Bearer " + bearer).encode("ascii")
        self._loop: asyncio.AbstractEventLoop | None = None
        self._listener: socket.socket | None = None
        self._endpoint: LoopbackEndpoint | None = None
        self._watching: bool = False
        self._closing: bool = False
        self._records: set[_Connection] = set()
        self._sockets: set[_Connection] = set()
        self._handlers: set[_Connection] = set()
        self._calls: set[asyncio.Task[bytes]] = set()
        self._close_task: asyncio.Task[None] | None = None
        self._counts: dict[str, int] = {
            key: 0
            for key in (
                "accepted",
                self._profile.success,
                "rejected",
                "timed_out",
                "telemetry_failed",
            )
        }

    def _bind(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        if self._loop is not None and self._loop is not loop:
            raise BoundedHttpError("invalid_configuration")
        self._loop = loop
        return loop

    @property
    def pending_count(self) -> int:
        return len(self._records | self._sockets)

    def metrics(self) -> MappingProxyType[str, int]:
        return MappingProxyType(
            {
                **self._counts,
                "sockets": len(self._sockets),
                "handlers": len(self._handlers),
                "active_calls": len(self._calls),
                "closing": int(self._closing),
            }
        )

    def _log(self, event: Event, code: HttpCode | Literal["ok"]) -> None:
        try:
            self._observer(event, "ok" if code == "ok" else self._wire_code(code))
        except Exception:  # noqa: BLE001 - diagnostics cannot change authority or cleanup
            self._counts["telemetry_failed"] += 1

    def _wire_code(self, code: HttpCode) -> str:
        if self._purpose == "native_prepare":
            return {"invalid_input": "invalid_request", "capacity": "capacity_exhausted"}.get(
                code, code
            )
        return code

    def _watch(self) -> None:
        listener = self._listener
        if (
            not self._closing
            and not self._watching
            and listener is not None
            and listener.fileno() >= 0
            and len(self._sockets) < 8
        ):
            self._bind().add_reader(listener.fileno(), self._accept_ready)
            self._watching = True

    def _unwatch(self) -> None:
        listener = self._listener
        if self._watching and listener is not None:
            self._bind().remove_reader(listener.fileno())
        self._watching = False

    async def start(self, port: int = 0) -> Endpoint:
        loop = self._bind()
        if type(port) is not int or not 0 <= port <= 65535:
            raise BoundedHttpError("invalid_configuration")
        if self._closing:
            raise BoundedHttpError("closed")
        current = asyncio.current_task()
        if current is not None and current.cancelling():
            raise asyncio.CancelledError
        if self._endpoint is not None:
            if port not in (0, self._endpoint.port):
                raise BoundedHttpError("invalid_configuration")
            return self._endpoint
        listener: socket.socket | None = None
        try:
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.setblocking(False)
            listener.bind(("127.0.0.1", port))
            listener.listen(8)
            endpoint = LoopbackEndpoint("127.0.0.1", int(listener.getsockname()[1]))
            self._listener, self._endpoint = listener, endpoint
            loop.add_reader(listener.fileno(), self._accept_ready)
            self._watching = True
        except BaseException as error:
            if listener is not None:
                listener.close()
            self._listener, self._endpoint = None, None
            if isinstance(error, Exception):
                raise BoundedHttpError("unavailable") from None
            raise
        return endpoint

    def _accept_ready(self) -> None:
        listener = self._listener
        if self._closing or listener is None:
            return
        loop = self._bind()
        # At most eight accepts per readiness callback; no await can lose a socket.
        for _ in range(8):
            if len(self._sockets) >= 8:
                self._unwatch()
                return
            try:
                accepted, address = listener.accept()
            except BlockingIOError:
                return
            except OSError:
                self._closing = True
                self._unwatch()
                self._counts["rejected"] += 1
                self._log("rejected", "unavailable")
                return
            connection = _Connection(accepted)
            self._records.add(connection)
            self._sockets.add(connection)
            if address[0] != "127.0.0.1":
                self._close_socket(connection)
                continue
            try:
                accepted.setblocking(False)
                admitted = len(self._handlers) < 4
                if admitted:
                    self._handlers.add(connection)
                operation = self._serve(connection) if admitted else self._reject(connection)
                connection.task = _task(loop, operation)
            except BaseException as error:
                self._close_socket(connection)
                self._closing = True
                self._unwatch()
                self._counts["rejected"] += 1
                self._log("rejected", "unavailable")
                if not isinstance(error, Exception):
                    raise
                return
            connection.task.add_done_callback(partial(self._handler_settled, connection))
        if len(self._sockets) >= 8:
            self._unwatch()

    def _close_socket(self, connection: _Connection) -> None:
        try:
            connection.socket.close()
        except OSError:
            if connection.socket.fileno() >= 0:
                return
        if connection.socket.fileno() < 0:
            self._sockets.discard(connection)
            self._retire(connection)
            try:
                self._watch()
            except Exception:  # noqa: BLE001 - stop admission, retain existing owners
                self._closing = True
                self._counts["rejected"] += 1
                self._log("rejected", "unavailable")

    async def _request(self, connection: _Connection) -> bytes:
        loop = self._bind()
        received = bytearray()
        async with asyncio.timeout(1):
            while b"\r\n\r\n" not in received:
                if len(received) >= 4096:
                    raise HttpRejection()
                chunk = await loop.sock_recv(connection.socket, 4096 - len(received))
                if not chunk:
                    raise HttpRejection()
                received.extend(chunk)
        offset = received.index(b"\r\n\r\n") + 4
        lines = bytes(received[: offset - 4]).split(b"\r\n")
        if not 1 <= len(lines) <= 33:
            raise HttpRejection()
        operation: bytes | None = None
        if self._purpose == "operator":
            prefix = b"POST " + self._profile.route
            suffix = b" HTTP/1.1"
            if not lines[0].startswith(prefix) or not lines[0].endswith(suffix):
                raise HttpRejection()
            operation = lines[0][len(prefix) : -len(suffix)]
            if operation not in {
                b"status",
                b"start",
                b"end",
                b"current",
                b"case",
                b"progress",
                b"sms",
            }:
                raise HttpRejection()
        elif lines[0] != b"POST " + self._profile.route + b" HTTP/1.1":
            raise HttpRejection()
        headers: dict[str, bytes] = {}
        for line in lines[1:]:
            name, separator, value = line.partition(b":")
            if (
                not separator
                or re.fullmatch(rb"[A-Za-z-]+", name) is None
                or any(byte < 32 or byte > 126 for byte in value)
            ):
                raise HttpRejection()
            key = name.decode("ascii").lower()
            if key in headers or self._purpose != "operator" and key not in _HEADERS:
                raise HttpRejection()
            headers[key] = value.strip(b" ")
        endpoint = self._endpoint
        assert endpoint is not None
        if (
            (
                not _HEADERS <= set(headers)
                if self._purpose == "operator"
                else set(headers) != _HEADERS
            )
            or "transfer-encoding" in headers
            or self._purpose == "operator"
            and headers.get("origin", b"http://127.0.0.1:5179") != b"http://127.0.0.1:5179"
            or headers["host"] != f"127.0.0.1:{endpoint.port}".encode()
            or headers["content-type"] != b"application/json"
            or headers["connection"].lower() != b"close"
            or re.fullmatch(rb"[1-9][0-9]{0,4}", headers["content-length"]) is None
        ):
            raise HttpRejection()
        if not hmac.compare_digest(headers["authorization"], self._authorization):
            raise HttpRejection("unauthorized")
        length = int(headers["content-length"])
        if length > self._profile.request_bytes:
            raise HttpRejection()
        body = bytearray(received[offset:])
        if len(body) > length:
            raise HttpRejection()
        async with asyncio.timeout(1):
            while len(body) < length:
                chunk = await loop.sock_recv(connection.socket, length - len(body))
                if not chunk:
                    raise HttpRejection()
                body.extend(chunk)
        if operation is not None:
            # Preserve all nested bytes/duplicate evidence for the application
            # decoder. Only a closed route selected by this listener is wrapped.
            return b'{"operation":"' + operation + b'","request":' + bytes(body) + b"}"
        return bytes(body)

    async def _invoke(self, raw: bytes) -> bytes:
        value = await self._exchange(raw)
        if type(value) is not bytes or not 0 < len(value) <= self._profile.response_bytes:
            raise HttpRejection("unavailable")
        return value

    async def _response(self, connection: _Connection, status: int, body: bytes) -> None:
        reason = {
            200: "OK",
            400: "Bad Request",
            401: "Unauthorized",
            403: "Forbidden",
            409: "Conflict",
            429: "Too Many Requests",
            503: "Service Unavailable",
        }[status]
        cache = (
            "Cache-Control: no-store\r\n"
            if self._purpose in {"worker_current_result", "operator"}
            else ""
        )
        wire = (
            f"HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n{cache}\r\n".encode(
                "ascii"
            )
            + body
        )
        async with asyncio.timeout(1):
            await self._bind().sock_sendall(connection.socket, wire)

    async def _reject(self, connection: _Connection) -> None:
        self._counts["rejected"] += 1
        self._log("rejected", "capacity")
        try:
            # Drain one bounded request before closing: unread TCP input can
            # otherwise reset a valid peer before its overload response arrives.
            await self._request(connection)
            await self._response(
                connection,
                429,
                _encode(
                    {
                        "schemaVersion": 1,
                        "status": "unavailable",
                        "code": self._wire_code("capacity"),
                    }
                ),
            )
        except (OSError, TimeoutError, HttpRejection):
            pass
        finally:
            self._close_socket(connection)

    async def _serve(self, connection: _Connection) -> None:
        self._counts["accepted"] += 1
        try:
            raw = await self._request(connection)
            if self._closing:
                raise HttpRejection("closed")
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                raise asyncio.CancelledError
            if len(self._calls) >= 4:
                raise HttpRejection("capacity")
            call = _task(self._bind(), self._invoke(raw))
            connection.call = call
            self._calls.add(call)
            call.add_done_callback(partial(self._call_settled, connection))
            try:
                async with asyncio.timeout(self._call_timeout):
                    value = await asyncio.shield(call)
            except TimeoutError:
                self._counts["timed_out"] += 1
                self._log("timed_out", "unavailable")
                raise HttpRejection(
                    "outcome_unknown" if self._purpose == "operator" else "unavailable"
                ) from None
            await self._response(connection, 200, value)
            self._counts[self._profile.success] += 1
            self._log(self._profile.success, "ok")
        except Exception as error:  # noqa: BLE001 - outer HTTP containment, static finite codes only
            code = _code(error)
            status = {
                "invalid_input": 400,
                "unauthorized": 401,
                "forbidden": 403,
                "idempotency_conflict": 409,
                "capacity": 429,
            }.get(code, 503)
            if self._purpose == "operator":
                status = {
                    "unauthorized": 403,
                    "conflict": 409,
                    "closed": 409,
                    "recovery_required": 409,
                }.get(code, status)
            self._counts["rejected"] += 1
            self._log("rejected", code)
            if connection.socket.fileno() >= 0:
                try:
                    await self._response(
                        connection,
                        status,
                        _encode(
                            {
                                "schemaVersion": 1,
                                "status": "unavailable",
                                "code": self._wire_code(code),
                            }
                        ),
                    )
                except (OSError, TimeoutError):
                    pass
        finally:
            self._close_socket(connection)

    def _retire(self, connection: _Connection) -> None:
        if (
            connection not in self._sockets
            and (connection.task is None or connection.task.done())
            and (connection.call is None or connection.call.done())
        ):
            self._records.discard(connection)
            self._handlers.discard(connection)

    def _handler_settled(self, connection: _Connection, task: asyncio.Task[None]) -> None:
        _consume(task)
        self._retire(connection)

    def _call_settled(self, connection: _Connection, task: asyncio.Task[bytes]) -> None:
        _consume(task)
        self._calls.discard(task)
        self._retire(connection)

    async def _finish_close(self) -> None:
        listener = self._listener
        listener_failed = False
        if listener is not None:
            try:
                listener.close()
            except OSError:
                listener_failed = listener.fileno() >= 0
        for connection in tuple(self._sockets):
            self._close_socket(connection)
        tasks = tuple(
            connection.task for connection in self._records if connection.task is not None
        )
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        calls = tuple(self._calls)
        if calls:
            await asyncio.gather(*calls, return_exceptions=True)
        # Python can complete gather synchronously when every call is already
        # done. Its registered settlement callbacks may still be queued; retire
        # only these observed done calls without depending on callback order.
        for call in calls:
            if call.done():
                self._calls.discard(call)
        for connection in tuple(self._records):
            self._retire(connection)
        if listener_failed or self._records or self._sockets or self._handlers or self._calls:
            raise BoundedHttpError("cleanup_incomplete")

    async def close(self) -> None:
        loop = self._bind()
        self._closing = True
        try:
            self._unwatch()
        except Exception:  # noqa: BLE001 - retain listener on selector cleanup failure
            raise BoundedHttpError("cleanup_incomplete") from None
        if self._close_task is None or (
            self._close_task.done()
            and (self._close_task.cancelled() or self._close_task.exception() is not None)
        ):
            self._close_task = _task(loop, self._finish_close(), cleanup=True)
            self._close_task.add_done_callback(_consume)
        try:
            async with asyncio.timeout(self._cleanup_timeout):
                await asyncio.shield(self._close_task)
        except TimeoutError:
            raise BoundedHttpError("cleanup_incomplete") from None
        except Exception:  # noqa: BLE001 - safe cleanup boundary, retain actual owners
            raise BoundedHttpError("cleanup_incomplete") from None
