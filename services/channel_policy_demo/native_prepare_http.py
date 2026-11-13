"""Native prepare DTO adapter over the shared bounded loopback server.

Borrow NativeRuntime only. End concurrently closes this host and runtime, then
observes both before model/intake/room dependencies. No imports start I/O/SDK.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import re
import socket as socket  # noqa: PLC0414 - preserve typed compatibility for ownership tests
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from types import FunctionType, MethodType
from typing import Any, Literal, Protocol, cast

from ._bounded_loopback_http import (
    BoundedHttpError,
    BoundedLoopbackHttp,
    Event,
    HttpRejection,
    host_error_code,
)

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
ROUTE = b"/v1/native/prepare"
HostCode = Literal["invalid_configuration", "unavailable", "closed", "cleanup_incomplete"]


class NativePrepareHttpError(Exception):
    """Finite process-boundary diagnostic, without dependency text or received data."""

    def __init__(self, code: HostCode = "unavailable") -> None:
        self.code = (
            code
            if type(code) is str
            and code in {"invalid_configuration", "unavailable", "closed", "cleanup_incomplete"}
            else "unavailable"
        )
        super().__init__(self.code)


class NativePreparePort(Protocol):
    """Borrowed immutable binding; NativeRuntime validates context/authority/readiness."""

    async def prepare(self, context: object) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class NativePrepareEndpoint:
    host: Literal["127.0.0.1"]
    port: int

    def __post_init__(self) -> None:
        if (
            type(self.host) is not str
            or self.host != "127.0.0.1"
            or type(self.port) is not int
            or not 1 <= self.port <= 65535
        ):
            raise NativePrepareHttpError("invalid_configuration")


def _pairs(values: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in values:
        if key in result:
            raise HttpRejection()
        result[key] = value
    return result


def _constant(_: str) -> object:
    raise HttpRejection()


def _decode(raw: bytes) -> dict[str, object]:
    try:
        value: object = json.loads(
            raw.decode("utf-8", "strict"), object_pairs_hook=_pairs, parse_constant=_constant
        )
        if (
            type(value) is not dict
            or set(value) != {"schemaVersion", "kind", "context"}
            or type(value["schemaVersion"]) is not int
            or value["schemaVersion"] != 1
            or value["kind"] != "agent.prepare"
            or type(value["context"]) is not dict
        ):
            raise HttpRejection()
        return cast(dict[str, object], value["context"])
    except (ValueError, UnicodeError, RecursionError):
        raise HttpRejection() from None


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


class _PrepareExchange:
    def __init__(self, runtime: NativePreparePort) -> None:
        descriptor = inspect.getattr_static(type(runtime), "prepare", None)
        if (
            type(descriptor) is not FunctionType
            or not inspect.iscoroutinefunction(descriptor)
            or inspect.getattr_static(runtime, "prepare", None) is not descriptor
        ):
            raise NativePrepareHttpError("invalid_configuration")
        try:
            inspect.signature(descriptor).bind(runtime, object())
        except (TypeError, ValueError):
            raise NativePrepareHttpError("invalid_configuration") from None
        self._prepare = cast(
            Callable[[object], Coroutine[Any, Any, dict[str, object]]],
            MethodType(descriptor, runtime),
        )

    async def exchange(self, raw: bytes) -> bytes:
        context = _decode(raw)
        expected_revision = context.get("caseRevision")
        value = await self._prepare(context)
        if (
            type(value) is not dict
            or set(value) != {"kind", "source", "caseRevision"}
            or value["kind"] != "investigation"
            or value["source"] != "scripted"
        ):
            raise HttpRejection("unavailable")
        revision = value["caseRevision"]
        if (
            type(revision) is not str
            or re.fullmatch(r"[1-9][0-9]{0,18}", revision) is None
            or int(revision) > 9223372036854775807
            or revision != expected_revision
        ):
            raise HttpRejection("unavailable")
        return _encode(
            {
                "schemaVersion": 1,
                "kind": "agent.prepared",
                "inputDigest": hashlib.sha256(raw).hexdigest(),
                "decision": {
                    "kind": "investigation",
                    "source": "scripted",
                    "caseRevision": revision,
                },
            }
        )


def _observe(event: Event, code: str) -> None:
    LOGGER.info("native_prepare_http", extra={"event": event, "code": code})


class NativePrepareHttp(BoundedLoopbackHttp):
    """One borrowed binding; unchanged public prepare API and four/eight limits."""

    def __init__(
        self,
        runtime: NativePreparePort,
        *,
        prepare_bearer: str,
        call_timeout_s: float = 4,
        cleanup_timeout_s: float = 1,
    ) -> None:
        try:
            super().__init__(
                _PrepareExchange(runtime),
                purpose="native_prepare",
                bearer=prepare_bearer,
                call_timeout_s=call_timeout_s,
                cleanup_timeout_s=cleanup_timeout_s,
                observer=_observe,
            )
        except BoundedHttpError as error:
            raise NativePrepareHttpError(host_error_code(error)) from None

    async def start(self, port: int = 11030) -> NativePrepareEndpoint:
        try:
            endpoint = await super().start(port)
            return NativePrepareEndpoint(endpoint.host, endpoint.port)
        except BoundedHttpError as error:
            raise NativePrepareHttpError(host_error_code(error)) from None

    async def close(self) -> None:
        try:
            await super().close()
        except BoundedHttpError as error:
            raise NativePrepareHttpError(host_error_code(error)) from None
