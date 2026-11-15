"""Private fixed-purpose loopback exchanges; no arbitrary URL, role or retry.

Raw control exchanges return status/body. Read facades may provide a trusted
synchronous decoder inside the SAME retained call to preserve semantic metrics.
No request body/model selects its path, credential, decoder or diagnostic label.
"""

from __future__ import annotations

import asyncio
import inspect
import math
import re
import socket
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from email.utils import format_datetime, parsedate_to_datetime
from inspect import getattr_static
from types import FunctionType, MappingProxyType
from typing import Literal, TypeVar, cast

Purpose = Literal[
    "native_result",
    "worker_current_result",
    "room_open",
    "room_observe",
    "room_close",
    "room_recover",
    "room_attach",
]
LoopbackCode = Literal[
    "invalid_input",
    "invalid_state",
    "unauthorized",
    "capacity",
    "closed",
    "unavailable",
    "deadline_exceeded",
    "cleanup_incomplete",
]
_CODES = frozenset(
    {
        "invalid_input",
        "invalid_state",
        "unauthorized",
        "capacity",
        "closed",
        "unavailable",
        "deadline_exceeded",
        "cleanup_incomplete",
    }
)
_PURPOSES = MappingProxyType(
    {
        "native_result": ("/v1/channel-policy/rooms/native-result", 32768),
        "worker_current_result": ("/v1/channel-policy/current-result", 32768),
        "room_open": ("/v1/channel-policy/rooms/open", 4096),
        "room_observe": ("/v1/channel-policy/rooms/observe", 4096),
        "room_close": ("/v1/channel-policy/rooms/close", 4096),
        "room_recover": ("/v1/channel-policy/rooms/recover-revoke", 4096),
        "room_attach": ("/v1/channel-policy/rooms/attach-agent", 4096),
    }
)
MAX_CALLS = 2
_MAX_COUNTER = 9007199254740991
T = TypeVar("T")


class LoopbackJSONError(RuntimeError):
    def __init__(self, code: LoopbackCode = "unavailable") -> None:
        self.code: LoopbackCode = code if type(code) is str and code in _CODES else "unavailable"
        super().__init__(self.code)


def finite_error(error: BaseException) -> LoopbackJSONError:
    try:
        code: object = getattr_static(error, "code", None)
    except Exception:  # noqa: BLE001 - no dependency getter/args
        code = None
    return LoopbackJSONError(
        cast(LoopbackCode, code) if type(code) is str and code in _CODES else "unavailable"
    )


def _need(value: bool, code: LoopbackCode = "invalid_state") -> None:
    if not value:
        raise LoopbackJSONError(code)


def _budget(value: float) -> float:
    _need(
        type(value) in (float, int) and 0.001 <= value <= 5 and math.isfinite(value),
        "invalid_input",
    )
    return float(value)


def _network_default() -> float:
    return 5.0


def _spawn(action: Coroutine[object, object, T]) -> asyncio.Task[T]:
    try:
        task = asyncio.create_task(action)
    except BaseException:
        action.close()
        raise
    task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    return task


def _raw(status: int, raw: bytes) -> tuple[int, bytes]:
    return status, raw


async def close_writer(writer: asyncio.StreamWriter) -> None:
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        # connection_lost stored the transport's error in the close waiter, which
        # re-raises it on every await; the socket is already closed by then.
        pass


@dataclass(eq=False, slots=True)
class _Call:
    published: asyncio.Future[None]
    task: asyncio.Task[object] | None = None
    writer: asyncio.StreamWriter | None = None
    abandoned: bool = False


class LoopbackJSONTransport:
    """Two actual call/socket/close owners; waiter loss cannot release a slot.

    Network work has a fixed five-second budget. Cleanup remains owned if an
    actual writer close has not settled. close stops admission, drains admitted
    requests and retries only unresolved socket closure; it never resends.
    """

    def __init__(
        self,
        *,
        port: int,
        bearer: str,
        purpose: Purpose,
        timeout_s: float = 1,
        cleanup_timeout_s: float = 1,
        observer: Callable[[str], None] | None = None,
        network_budget: Callable[[], float] | None = None,
    ) -> None:
        _need(type(port) is int and 1 <= port <= 65535, "invalid_input")
        _need(
            type(bearer) is str
            and re.fullmatch(r"[A-Za-z0-9_-]{43}", bearer, re.ASCII) is not None,
            "invalid_input",
        )
        _need(type(purpose) is str and purpose in _PURPOSES, "invalid_input")
        _need(
            observer is None
            or (
                type(observer) is FunctionType
                and not observer.__code__.co_flags
                & (inspect.CO_COROUTINE | inspect.CO_ASYNC_GENERATOR)
            ),
            "invalid_input",
        )
        _need(
            network_budget is None
            or (
                type(network_budget) is FunctionType
                and not network_budget.__code__.co_flags
                & (inspect.CO_COROUTINE | inspect.CO_ASYNC_GENERATOR)
            ),
            "invalid_input",
        )
        self._port, self._authorization = port, "Bearer " + bearer
        self._path, self._maximum = _PURPOSES[purpose]
        self._observer = observer
        self._network_budget = network_budget or _network_default
        self._timeout, self._cleanup = _budget(timeout_s), _budget(cleanup_timeout_s)
        self._calls: set[_Call] = set()
        self._close_task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closing = False
        self._counts = {
            "started": 0,
            "succeeded": 0,
            "failed": 0,
            "cancelled_waiters": 0,
            "timed_out_waiters": 0,
            "telemetry_failed": 0,
        }

    def _bind(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        _need(self._loop is None or self._loop is loop, "invalid_input")
        self._loop = loop
        return loop

    @property
    def pending_count(self) -> int:
        return len(self._calls)

    def metrics(self) -> MappingProxyType[str, int]:
        return MappingProxyType(
            {**self._counts, "active": len(self._calls), "closing": int(self._closing)}
        )

    def _count(self, key: str) -> None:
        self._counts[key] = min(_MAX_COUNTER, self._counts[key] + 1)

    def _log(self, code: str) -> None:
        try:
            if self._observer is not None:
                self._observer(code)
        except Exception:  # noqa: BLE001 - telemetry cannot change exchange/cleanup truth
            self._count("telemetry_failed")

    async def _close_writer(self, call: _Call) -> None:
        if call.writer is not None:
            await close_writer(call.writer)
            call.writer = None

    async def _exchange(self, call: _Call, body: bytes) -> tuple[int, bytes]:
        async with asyncio.timeout(_budget(self._network_budget())):
            reader, writer = await asyncio.open_connection(
                "127.0.0.1", self._port, family=socket.AF_INET, limit=4096
            )
            call.writer = writer
            _need(not self._closing and not call.abandoned, "closed")
            headers = (
                f"POST {self._path} HTTP/1.1\r\nHost: 127.0.0.1:{self._port}\r\nAuthorization: {self._authorization}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n"
            ).encode("ascii")
            writer.write(headers + body)
            await writer.drain()
            head = await reader.readuntil(b"\r\n\r\n")
            _need(len(head) <= 4096)
            lines = head[:-4].split(b"\r\n")
            match = re.fullmatch(rb"HTTP/1\.1 ([0-9]{3}) [\x20-\x7e]{1,64}", lines[0])
            _need(match is not None and len(lines) <= 6)
            assert match is not None
            status = int(match[1])
            _need(status in {200, 400, 401, 409, 429, 503})
            fields: dict[str, str] = {}
            for line in lines[1:]:
                name, sep, value = line.partition(b": ")
                key = name.decode("ascii", "strict").lower()
                _need(
                    sep == b": "
                    and key
                    in {"content-length", "content-type", "connection", "cache-control", "date"}
                    and key not in fields
                )
                fields[key] = value.decode("ascii", "strict")
            length = fields.get("content-length", "")
            _need(re.fullmatch(r"0|[1-9][0-9]{0,4}", length) is not None)
            _need(
                int(length) <= (self._maximum if status == 200 else 4096)
                and fields.get("content-type") == "application/json"
                and fields.get("connection") == "close"
                and fields.get("cache-control") == "no-store"
            )
            if "date" in fields:
                _need(
                    format_datetime(parsedate_to_datetime(fields["date"]), usegmt=True)
                    == fields["date"]
                )
            raw = await reader.readexactly(int(length))
            _need(await reader.read(1) == b"")
            return status, raw

    async def _perform(
        self, call: _Call, body: bytes, decoder: Callable[[int, bytes], object]
    ) -> object:
        try:
            status, raw = await self._exchange(call, body)
            result = decoder(status, raw)
        except asyncio.CancelledError:
            raise
        except LoopbackJSONError as error:
            safe = finite_error(error)
            self._count("failed")
            self._log(safe.code)
            raise safe from None
        except Exception:  # noqa: BLE001 - socket/decoder diagnostics never escape
            self._count("failed")
            self._log("unavailable")
            raise LoopbackJSONError() from None
        finally:
            # The complete framed response is decoded before cleanup. A failed
            # close keeps this writer/slot owned but cannot erase known bytes or
            # replace a primary validation/network error. Cleanup never resends.
            try:
                await self._close_writer(call)
            except Exception:  # noqa: BLE001 - preserve knowledge and retained writer
                self._log("cleanup_incomplete")
        self._count("succeeded")
        self._log("absent" if result is None else "ok")
        return result

    async def exchange(self, body: bytes) -> tuple[int, bytes]:
        """Raw transport status/body only; no absence, retry or domain mapping."""
        return await self.exchange_decoded(body, decoder=_raw)

    async def exchange_decoded(self, body: bytes, *, decoder: Callable[[int, bytes], T]) -> T:
        """Trusted pure synchronous decoder runs before the same owner settles."""
        loop = self._bind()
        _need(type(body) is bytes and 0 < len(body) <= 1024, "invalid_input")
        _need(
            type(decoder) is FunctionType
            and not decoder.__code__.co_flags & (inspect.CO_COROUTINE | inspect.CO_ASYNC_GENERATOR),
            "invalid_input",
        )
        _need(not self._closing, "closed")
        _need(len(self._calls) < MAX_CALLS, "capacity")
        current = asyncio.current_task()
        if current is not None and current.cancelling():
            raise asyncio.CancelledError
        try:
            publication: asyncio.Future[None] = loop.create_future()
        except Exception:  # noqa: BLE001 - before admitting actual I/O owner
            raise LoopbackJSONError() from None
        call = _Call(publication)
        self._calls.add(call)
        try:
            call.task = _spawn(self._perform(call, body, decoder))
        except BaseException as error:
            self._calls.discard(call)
            if isinstance(error, Exception):
                raise LoopbackJSONError() from None
            raise
        finally:
            publication.set_result(None)

        def settled(_: asyncio.Task[object]) -> None:
            if call.writer is None:
                self._calls.discard(call)

        call.task.add_done_callback(settled)
        self._count("started")
        try:
            async with asyncio.timeout(self._timeout):
                return cast(T, await asyncio.shield(call.task))
        except TimeoutError:
            call.abandoned = True
            self._count("timed_out_waiters")
            raise LoopbackJSONError("deadline_exceeded") from None
        except asyncio.CancelledError:
            call.abandoned = True
            self._count("cancelled_waiters")
            raise

    async def _drain(self, call: _Call) -> None:
        await asyncio.shield(call.published)
        if call.task is not None:
            await asyncio.gather(asyncio.shield(call.task), return_exceptions=True)
        if call.writer is not None:
            await self._close_writer(call)
        self._calls.discard(call)

    async def _finish_close(self) -> None:
        results = await asyncio.gather(
            *(self._drain(call) for call in tuple(self._calls)), return_exceptions=True
        )
        _need(
            not any(isinstance(value, BaseException) for value in results) and not self._calls,
            "cleanup_incomplete",
        )

    async def close(self) -> None:
        self._bind()
        self._closing = True
        if (
            self._close_task is not None
            and self._close_task.done()
            and (self._close_task.cancelled() or self._close_task.exception() is not None)
        ):
            self._close_task = None
        if self._close_task is None:
            try:
                self._close_task = _spawn(self._finish_close())
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - actual owners remain retained for retry
                raise LoopbackJSONError("cleanup_incomplete") from None
        try:
            async with asyncio.timeout(self._cleanup):
                await asyncio.shield(self._close_task)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - no failed close may free actual call ownership
            raise LoopbackJSONError("cleanup_incomplete") from None
        _need(not self._calls, "cleanup_incomplete")
