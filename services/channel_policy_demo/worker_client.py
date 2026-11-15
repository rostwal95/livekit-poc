"""Bounded read-only client for the configured Node source boundary.

Read observations are not business acknowledgements or execution authority.
The client owns real connection/read/close lifetimes; adapters only borrow it.
Imports perform no I/O and credentials never enter diagnostics or URLs.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import math
import re
from collections.abc import Coroutine
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, TypeVar, cast

from delegation_reliability import CoordinatorError
from delegation_reliability.contracts import ContractError, identifier
from delegation_reliability.coordinator import CoordinatorCode

from ._loopback_json import close_writer
from .discovery import (
    PAGE_BYTES,
    PREPARED_FRAME_BYTES,
    DiscoveryError,
    DiscoveryPage,
    DiscoveryScope,
    SourceBindingId,
    parse_discovery_page,
)
from .wire import OriginWireError, parse_accept_frame, require_p3_compatible, uuid_value

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
ReadCode = Literal[
    "invalid_input",
    "unauthorized",
    "not_found",
    "invalid_state",
    "capacity",
    "unavailable",
    "closed",
    "cleanup_incomplete",
]
_CODES = frozenset(
    {
        "invalid_input",
        "unauthorized",
        "not_found",
        "invalid_state",
        "capacity",
        "unavailable",
        "closed",
        "cleanup_incomplete",
    }
)
_HEADERS = frozenset({"content-type", "content-length", "connection", "cache-control", "date"})
T = TypeVar("T")


class WorkerReadError(RuntimeError):
    """Finite diagnostics exclude tokens, original input and dependency text."""

    def __init__(self, code: ReadCode = "unavailable") -> None:
        self.code: ReadCode = code if type(code) is str and code in _CODES else "unavailable"
        super().__init__(self.code)


def _failure(error: BaseException) -> WorkerReadError:
    try:
        code = (
            inspect.getattr_static(error, "code", None) if type(error) is WorkerReadError else None
        )
        if type(code) is str and code in _CODES:
            return WorkerReadError(cast(ReadCode, code))
    except Exception:  # noqa: BLE001 - a dependency accessor cannot supply a diagnostic
        return WorkerReadError()
    return WorkerReadError()


def _need(condition: bool, code: ReadCode = "invalid_state") -> None:
    if not condition:
        raise WorkerReadError(code)


@dataclass(frozen=True, slots=True)
class WorkerEndpoint:
    host: Literal["127.0.0.1"]
    port: int

    def __post_init__(self) -> None:
        _need(type(self.host) is str and self.host == "127.0.0.1", "invalid_input")
        _need(type(self.port) is int and 1 <= self.port <= 65535, "invalid_input")


@dataclass(frozen=True, slots=True)
class WorkerCredential:
    value: str = field(repr=False)

    def __post_init__(self) -> None:
        _need(
            type(self.value) is str and re.fullmatch(r"[A-Za-z0-9_-]{43}", self.value) is not None,
            "invalid_input",
        )


@dataclass(frozen=True, slots=True)
class WorkerBinding:
    profile_id: str
    scope: DiscoveryScope
    case_id: str
    conversation_id: str

    def __post_init__(self) -> None:
        try:
            uuid_value(self.profile_id)
            _need(type(self.scope) is DiscoveryScope, "invalid_input")
            object.__setattr__(
                self, "scope", DiscoveryScope(self.scope.tenant_id, self.scope.account_id)
            )
            identifier(self.case_id)
            identifier(self.conversation_id)
        except (
            OriginWireError,
            DiscoveryError,
            ContractError,
            AttributeError,
            TypeError,
            ValueError,
        ):
            raise WorkerReadError("invalid_input") from None


def _budget(value: float) -> float:
    _need(
        type(value) in (int, float) and 0.02 <= value <= 5 and math.isfinite(value), "invalid_input"
    )
    return float(value)


def _task(action: Coroutine[object, object, T]) -> asyncio.Task[T]:
    try:
        task = asyncio.create_task(action)
    except BaseException:
        action.close()
        raise
    task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    return task


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        _need(key not in result)
        result[key] = value
    return result


def _constant(_: str) -> object:
    raise WorkerReadError("invalid_state")


def _error_response(raw: bytes, status: int) -> WorkerReadError:
    try:
        value: object = json.loads(
            raw.decode("utf-8", "strict"), object_pairs_hook=_pairs, parse_constant=_constant
        )
        _need(type(value) is dict)
        fields = cast(dict[str, object], value)
        _need(set(fields) == {"schemaVersion", "status", "code"})
        _need(type(fields["schemaVersion"]) is int and fields["schemaVersion"] == 1)
        _need(fields["status"] == "unavailable")
        code = fields["code"]
        _need(type(code) is str and code in _CODES)
        expected = {
            "invalid_input": 400,
            "unauthorized": 403,
            "not_found": 404,
            "invalid_state": 503,
            "capacity": 429,
            "unavailable": 503,
            "closed": 503,
            "cleanup_incomplete": 503,
        }
        _need(expected[cast(str, code)] == status)
        return WorkerReadError(cast(ReadCode, code))
    except (ValueError, UnicodeError, RecursionError, WorkerReadError):
        return WorkerReadError("invalid_state")


@dataclass(eq=False, slots=True)
class _Call:
    task: asyncio.Task[object] | None = None
    writer: asyncio.StreamWriter | None = field(default=None, repr=False)
    published: asyncio.Event = field(default_factory=asyncio.Event)


class ChannelPolicyWorkerClient:
    """Two actual socket/codec lifetimes; no implicit retries or ownership transfer.

    Waiter cancellation/timeout leaves the actual operation retained. Its fixed
    I/O deadline closes transport, while late connection/close work stays owned.
    close stops admission and observes those same operations without disowning them.
    """

    def __init__(
        self,
        endpoint: WorkerEndpoint,
        credential: WorkerCredential,
        binding: WorkerBinding,
        *,
        timeout_s: float = 2,
        cleanup_timeout_s: float = 1,
    ) -> None:
        try:
            _need(
                type(endpoint) is WorkerEndpoint
                and type(credential) is WorkerCredential
                and type(binding) is WorkerBinding,
                "invalid_input",
            )
            self._endpoint = WorkerEndpoint(endpoint.host, endpoint.port)
            copied_credential = WorkerCredential(credential.value)
            self._binding = WorkerBinding(
                binding.profile_id, binding.scope, binding.case_id, binding.conversation_id
            )
        except (AttributeError, TypeError, ValueError):
            raise WorkerReadError("invalid_input") from None
        self._authorization = "Bearer " + copied_credential.value
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
        if self._loop is None:
            self._loop = loop
        elif loop is not self._loop:
            raise WorkerReadError("invalid_input")
        return loop

    @property
    def pending_count(self) -> int:
        return len(self._calls)

    def metrics(self) -> MappingProxyType[str, int]:
        return MappingProxyType(
            {**self._counts, "active": len(self._calls), "closing": int(self._closing)}
        )

    def _log(self, operation: Literal["discovery", "prepared"], code: str) -> None:
        safe = code if type(code) is str and code in _CODES | {"ok"} else "unavailable"
        try:
            LOGGER.info("channel_policy_worker_read", extra={"operation": operation, "code": safe})
        except Exception:  # noqa: BLE001 - telemetry cannot alter read or cleanup outcome
            self._counts["telemetry_failed"] += 1

    @staticmethod
    def _check(deadline: float) -> None:
        if asyncio.get_running_loop().time() >= deadline:
            raise WorkerReadError("unavailable")

    async def _exchange(
        self, call: _Call, path: str, body: bytes, maximum: int, deadline: float
    ) -> tuple[int, bytes]:
        writer: asyncio.StreamWriter | None = None
        primary: BaseException | None = None
        try:
            async with asyncio.timeout_at(deadline):
                reader, writer = await asyncio.open_connection(
                    self._endpoint.host, self._endpoint.port, limit=4096
                )
                call.writer = writer
                self._check(deadline)
                headers = (
                    f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1:{self._endpoint.port}\r\n"
                    f"Authorization: {self._authorization}\r\nContent-Type: application/json\r\n"
                    f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
                ).encode("ascii")
                writer.write(headers + body)
                await writer.drain()
                self._check(deadline)
                head = await reader.readuntil(b"\r\n\r\n")
                _need(len(head) <= 4096)
                lines = head[:-4].split(b"\r\n")
                match = re.fullmatch(rb"HTTP/1\.1 ([0-9]{3}) [\x20-\x7e]{1,64}", lines[0])
                _need(match is not None and len(lines) <= 9)
                assert match is not None
                status = int(match[1])
                fields: dict[str, str] = {}
                for line in lines[1:]:
                    name, separator, value = line.partition(b": ")
                    _need(separator == b": ")
                    key = name.decode("ascii", "strict").lower()
                    _need(key in _HEADERS and key not in fields)
                    fields[key] = value.decode("ascii", "strict")
                length = fields.get("content-length", "")
                _need(re.fullmatch(r"0|[1-9][0-9]{0,4}", length) is not None)
                limit = maximum if status == 200 else 4096 if status != 204 else 0
                _need(
                    int(length) <= limit
                    and fields.get("content-type") == "application/json"
                    and fields.get("connection") == "close"
                )
                _need(status in {200, 204, 400, 403, 404, 429, 503})
                payload = await reader.readexactly(int(length))
                self._check(deadline)
                # Require the server's promised terminal close; reject trailing bytes.
                _need(await reader.read(1) == b"")
                self._check(deadline)
                return status, payload
        except BaseException as error:
            primary = error
            raise
        finally:
            if writer is not None:
                try:
                    await self._close_writer(call)
                except Exception:  # noqa: BLE001 - preserve the first read failure
                    if primary is None:
                        raise WorkerReadError("cleanup_incomplete") from None

    async def _close_writer(self, call: _Call) -> None:
        writer = call.writer
        if writer is not None:
            await close_writer(writer)
            call.writer = None

    def _route(self, page: DiscoveryPage) -> None:
        b = self._binding
        _need(
            (page.profile_id, page.scope, page.case_id, page.conversation_id)
            == (b.profile_id, b.scope, b.case_id, b.conversation_id),
            "unauthorized",
        )

    async def _perform(
        self,
        call: _Call,
        kind: Literal["discovery", "prepared"],
        receipt_id: str | None,
        source: SourceBindingId | None,
        deadline: float,
    ) -> object:
        try:
            if kind == "discovery":
                status, raw = await self._exchange(
                    call, "/v1/policy/discovery", b'{"schemaVersion":1}', PAGE_BYTES, deadline
                )
                if status != 200:
                    if status == 204:
                        raise WorkerReadError("invalid_state")
                    raise _error_response(raw, status)
                page = parse_discovery_page(raw)
                self._route(page)
                result: object = page
            else:
                body = json.dumps(
                    {"schemaVersion": 1, "receiptId": receipt_id, "sourceBindingId": source},
                    separators=(",", ":"),
                ).encode("ascii")
                status, raw = await self._exchange(
                    call, "/v1/policy/prepared", body, PREPARED_FRAME_BYTES, deadline
                )
                if status == 204:
                    _need(raw == b"")
                    result = None
                elif status == 200:
                    prepared = parse_accept_frame(raw)
                    require_p3_compatible(prepared)
                    b = self._binding
                    _need(
                        (
                            prepared.scope.tenant_id,
                            prepared.scope.account_id,
                            prepared.case_id,
                            prepared.conversation_id,
                            prepared.input_receipt_id,
                        )
                        == (
                            b.scope.tenant_id,
                            b.scope.account_id,
                            b.case_id,
                            b.conversation_id,
                            receipt_id,
                        ),
                        "unauthorized",
                    )
                    result = raw
                else:
                    raise _error_response(raw, status)
        except asyncio.CancelledError:
            raise
        except WorkerReadError as error:
            safe = _failure(error)
            self._counts["failed"] += 1
            self._log(kind, safe.code)
            raise safe from None
        except (OriginWireError, DiscoveryError, ContractError):
            self._counts["failed"] += 1
            self._log(kind, "invalid_state")
            raise WorkerReadError("invalid_state") from None
        except Exception:  # noqa: BLE001 - outer transport containment excludes private text
            self._counts["failed"] += 1
            self._log(kind, "unavailable")
            raise WorkerReadError() from None
        self._counts["succeeded"] += 1
        self._log(kind, "ok")
        return result

    async def _read(
        self,
        kind: Literal["discovery", "prepared"],
        receipt_id: str | None = None,
        source: SourceBindingId | None = None,
    ) -> object:
        loop = self._bind()
        if self._closing:
            raise WorkerReadError("closed")
        if len(self._calls) >= 2:
            raise WorkerReadError("capacity")
        deadline = loop.time() + self._timeout
        call = _Call()
        self._calls.add(call)
        action = self._perform(call, kind, receipt_id, source, deadline)
        try:
            task = _task(action)
            call.task = task
        except BaseException as error:
            self._calls.discard(call)
            if isinstance(error, Exception):
                raise WorkerReadError() from None
            raise
        finally:
            call.published.set()

        def settled(_: asyncio.Task[object]) -> None:
            if call.writer is None:
                self._calls.discard(call)

        task.add_done_callback(settled)
        self._counts["started"] += 1
        try:
            async with asyncio.timeout_at(deadline):
                return await asyncio.shield(task)
        except TimeoutError:
            self._counts["timed_out_waiters"] += 1
            raise WorkerReadError() from None
        except asyncio.CancelledError:
            self._counts["cancelled_waiters"] += 1
            raise

    async def discovery(self) -> DiscoveryPage:
        value = await self._read("discovery")
        if type(value) is not DiscoveryPage:
            raise WorkerReadError("invalid_state")
        return value

    async def prepared(
        self, *, source_binding_id: SourceBindingId, receipt_id: str
    ) -> bytes | None:
        try:
            receipt = uuid_value(receipt_id)
            _need(
                type(source_binding_id) is str and source_binding_id in {"native", "sms"},
                "invalid_input",
            )
        except (OriginWireError, TypeError, ValueError):
            raise WorkerReadError("invalid_input") from None
        value = await self._read("prepared", receipt, source_binding_id)
        if value is not None and type(value) is not bytes:
            raise WorkerReadError("invalid_state")
        return value

    async def _drain_call(self, call: _Call) -> None:
        await call.published.wait()
        if call.task is not None:
            await asyncio.gather(asyncio.shield(call.task), return_exceptions=True)
        if call.writer is not None:
            await self._close_writer(call)
        self._calls.discard(call)

    async def _finish_close(self) -> None:
        results = await asyncio.gather(
            *(self._drain_call(call) for call in tuple(self._calls)), return_exceptions=True
        )
        if any(isinstance(value, BaseException) for value in results):
            raise WorkerReadError("cleanup_incomplete")

    async def close(self) -> None:
        loop = self._bind()
        self._closing = True
        if (
            self._close_task is not None
            and self._close_task.done()
            and (self._close_task.cancelled() or self._close_task.exception() is not None)
        ):
            self._close_task = None
        if self._close_task is None:
            try:
                self._close_task = _task(self._finish_close())
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - cleanup task allocation has a finite boundary
                raise WorkerReadError("cleanup_incomplete") from None
        try:
            async with asyncio.timeout_at(loop.time() + self._cleanup):
                await asyncio.shield(self._close_task)
        except TimeoutError:
            raise WorkerReadError("cleanup_incomplete") from None
        _need(not self._calls, "cleanup_incomplete")


@dataclass(frozen=True, slots=True)
class WorkerDiscoveryReader:
    """Borrow a client; the application closes it after all dependants drain."""

    client: ChannelPolicyWorkerClient = field(repr=False)

    async def read(self) -> DiscoveryPage:
        return await self.client.discovery()


@dataclass(frozen=True, slots=True)
class WorkerPreparedReader:
    client: ChannelPolicyWorkerClient = field(repr=False)

    async def read(self, *, source_binding_id: SourceBindingId, receipt_id: str) -> bytes | None:
        return await self.client.prepared(
            source_binding_id=source_binding_id, receipt_id=receipt_id
        )


_COORDINATOR_CODES: dict[ReadCode, CoordinatorCode] = {
    "invalid_input": "invalid_input",
    "unauthorized": "unauthorized",
    "not_found": "not_found",
    "invalid_state": "invalid_stored_state",
    "capacity": "capacity",
    "unavailable": "storage_unavailable",
    "closed": "closed",
    "cleanup_incomplete": "cleanup_incomplete",
}


@dataclass(frozen=True, slots=True)
class CoordinatorWorkerDiscoveryReader:
    """Borrow a client and translate its closed errors for the origin publisher port.

    Readers sharing a lane wait for each other, so background scans hold at most
    one of the client's two slots and origin dispatch keeps the other.
    """

    client: ChannelPolicyWorkerClient = field(repr=False)
    lane: asyncio.Semaphore | None = field(default=None, repr=False)

    async def read(self) -> DiscoveryPage:
        try:
            if self.lane is None:
                return await self.client.discovery()
            async with self.lane:
                return await self.client.discovery()
        except WorkerReadError as error:
            raise CoordinatorError(_COORDINATOR_CODES[_failure(error).code]) from None


@dataclass(frozen=True, slots=True)
class CoordinatorWorkerPreparedReader:
    client: ChannelPolicyWorkerClient = field(repr=False)
    lane: asyncio.Semaphore | None = field(default=None, repr=False)

    async def read(self, *, source_binding_id: SourceBindingId, receipt_id: str) -> bytes | None:
        try:
            if self.lane is None:
                return await self.client.prepared(
                    source_binding_id=source_binding_id, receipt_id=receipt_id
                )
            async with self.lane:
                return await self.client.prepared(
                    source_binding_id=source_binding_id, receipt_id=receipt_id
                )
        except WorkerReadError as error:
            raise CoordinatorError(_COORDINATOR_CODES[_failure(error).code]) from None
