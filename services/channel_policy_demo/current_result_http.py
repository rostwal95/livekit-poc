"""Parent-owned current-result callback for one captured room and read capability.

Only schemaVersion1 is accepted. The browser/model cannot choose work, scope,
delivery, grant or room. End marks the actual RoomOwner closed synchronously,
then concurrently stops this host and App.close_current_result. This host never
closes its borrowed App reader, shared jobs or room-view transport.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from types import FunctionType, MethodType
from typing import TYPE_CHECKING, Any, Literal, cast

from ._bounded_loopback_http import (
    BoundedHttpError,
    BoundedLoopbackHttp,
    Event,
    HttpRejection,
    _code,
    _Connection,
    host_error_code,
)
from .current_result import (
    CurrentResultError,
    CurrentResultObservation,
    encode_current_result_observation,
    parse_current_result_request,
)

if TYPE_CHECKING:
    from .application import CurrentResultReadPort

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
HostCode = Literal["invalid_configuration", "unavailable", "closed", "cleanup_incomplete"]


class CurrentResultHttpError(Exception):
    def __init__(self, code: HostCode = "unavailable") -> None:
        self.code = (
            code
            if type(code) is str
            and code in {"invalid_configuration", "unavailable", "closed", "cleanup_incomplete"}
            else "unavailable"
        )
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class CurrentResultEndpoint:
    host: Literal["127.0.0.1"]
    port: int

    def __post_init__(self) -> None:
        if (
            type(self.host) is not str
            or self.host != "127.0.0.1"
            or type(self.port) is not int
            or not 1 <= self.port <= 65535
        ):
            raise CurrentResultHttpError("invalid_configuration")


class _CurrentExchange:
    def __init__(
        self,
        reader: CurrentResultReadPort,
        is_current: Callable[[], bool],
        is_closing: Callable[[], bool],
    ) -> None:
        descriptor = inspect.getattr_static(type(reader), "read", None)
        if (
            type(descriptor) is not FunctionType
            or not inspect.iscoroutinefunction(descriptor)
            or inspect.getattr_static(reader, "read", None) is not descriptor
            or type(is_current) not in (FunctionType, MethodType)
            or inspect.iscoroutinefunction(is_current)
            or inspect.isasyncgenfunction(is_current)
            or inspect.isgeneratorfunction(is_current)
        ):
            raise CurrentResultHttpError("invalid_configuration")
        try:
            inspect.signature(descriptor).bind(reader)
            inspect.signature(is_current).bind()
        except (TypeError, ValueError):
            raise CurrentResultHttpError("invalid_configuration") from None
        self._read = cast(
            Callable[[], Coroutine[Any, Any, CurrentResultObservation]],
            MethodType(descriptor, reader),
        )
        self._is_current, self._is_closing = is_current, is_closing

    def _check(self) -> None:
        try:
            current = self._is_current()
        except Exception:  # noqa: BLE001 - trusted lifecycle callback failures stay finite
            raise HttpRejection("unavailable") from None
        if type(current) is not bool:
            raise HttpRejection("unavailable")
        if not current or self._is_closing():
            raise HttpRejection("closed")

    async def exchange(self, raw: bytes) -> bytes:
        try:
            parse_current_result_request(raw)
        except CurrentResultError:
            raise HttpRejection("invalid_input") from None
        self._check()
        try:
            value = await self._read()
        except Exception as error:  # noqa: BLE001 - static finite operational errors, never empty
            code = _code(error)
            raise HttpRejection(
                code if code in {"capacity", "closed", "cleanup_incomplete"} else "unavailable"
            ) from None
        self._check()
        try:
            output = encode_current_result_observation(value)
        except CurrentResultError:
            raise HttpRejection("unavailable") from None
        self._check()
        return output


def _observe(event: Event, code: str) -> None:
    LOGGER.info("room_current_result_http", extra={"event": event, "code": code})


class RoomCurrentResultHttp(BoundedLoopbackHttp):
    """Borrow one immutable App reader plus a captured actual-room predicate.

    Stop host admission and App's producer concurrently. Successful host drain
    covers these reader calls/sockets only; App separately owns producer drain.
    A timed-out/cancelled observer retains actual reads and the old room slot.
    """

    def __init__(
        self,
        reader: CurrentResultReadPort,
        *,
        is_current: Callable[[], bool],
        current_bearer: str,
        timeout_s: float = 1,
        cleanup_timeout_s: float = 1,
    ) -> None:
        application = _CurrentExchange(reader, is_current, lambda: self._closing)
        self._application = application
        try:
            super().__init__(
                application,
                purpose="worker_current_result",
                bearer=current_bearer,
                call_timeout_s=timeout_s,
                cleanup_timeout_s=cleanup_timeout_s,
                observer=_observe,
            )
        except BoundedHttpError as error:
            raise CurrentResultHttpError(host_error_code(error)) from None

    async def _response(self, connection: _Connection, status: int, body: bytes) -> None:
        if status == 200:
            # The exchange task may settle before this handler resumes. Fence
            # again at response admission, immediately before the first send.
            # Bytes already admitted to TCP are an earlier as-of observation.
            self._application._check()
        await super()._response(connection, status, body)

    async def start(self, port: int = 11031) -> CurrentResultEndpoint:
        try:
            endpoint = await super().start(port)
            return CurrentResultEndpoint(endpoint.host, endpoint.port)
        except BoundedHttpError as error:
            raise CurrentResultHttpError(host_error_code(error)) from None

    async def close(self) -> None:
        try:
            await super().close()
        except BoundedHttpError as error:
            raise CurrentResultHttpError(host_error_code(error)) from None
