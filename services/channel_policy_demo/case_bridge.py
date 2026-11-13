"""Explicit read-only loopback P2 composition over one public P1 projection read.

Trusted startup fixes the logical reference, P1 identity/task and credential. No
schema, settings, listener or business operation is created at import. Returned
case facts are observations; this bridge grants no quote, confirmation or tool
capability. The application owns and separately closes the supplied readers.
"""

from __future__ import annotations

import asyncio as asyncio  # noqa: PLC0414 - explicit typed compatibility export
import hashlib
import hmac
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from types import MappingProxyType
from typing import Literal, Protocol
from uuid import UUID

import h11

from continuity_lab.api import BookingChange, ExecutionCapacityExceeded, ExecutionNotFound
from continuity_lab.case_control_api import CaseControlClient, CaseControlIdentity
from continuity_lab.conversation_service import AsyncConversationService
from continuity_lab.postgres_api import (
    AuthenticatedActor,
    AuthenticationFailed,
    BearerToken,
    CaseProjection,
    ManagedCaseClient,
)

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
MAX_REVISION = 9_223_372_036_854_775_807
MAX_COUNTER = 9_007_199_254_740_991
HEADER_BYTES = BODY_BYTES = CASE_BYTES = 4096
RESPONSE_BYTES = 8192
SOCKETS, REQUESTS = 16, 2
Code = Literal[
    "AccessDenied", "InvalidCommand", "Overloaded", "Unavailable", "CleanupIncomplete", "Closed"
]


class BridgeError(RuntimeError):
    """Finite safe adapter code, without raw dependency diagnostics."""

    def __init__(self, code: Code) -> None:
        self.code = code
        super().__init__(code)


class CurrentCaseReader(Protocol):
    @property
    def identity(self) -> CaseControlIdentity: ...
    async def get(
        self, *, task_id: str, cursor: str | None = None, limit: int = 1
    ) -> CaseProjection: ...
    async def close(self) -> None: ...


class PublicCurrentCaseReader:
    """One public boundary/token shared by managed reads and public identity checks."""

    def __init__(self, boundary: AsyncConversationService, token: BearerToken, schema: str) -> None:
        self._managed = ManagedCaseClient(boundary, token)
        self._controller = CaseControlClient(boundary, token, schema)

    @property
    def identity(self) -> CaseControlIdentity:
        return self._controller.identity

    async def get(
        self, *, task_id: str, cursor: str | None = None, limit: int = 1
    ) -> CaseProjection:
        return await self._managed.get(task_id=task_id, cursor=cursor, limit=limit)

    async def close(self) -> None:
        await self._managed.close()


@dataclass(frozen=True, slots=True)
class CurrentCaseBinding:
    tenant_id: str
    account_id: str
    case_id: str
    conversation_id: str
    task_id: str
    authority_case_id: str
    token: str = field(repr=False)
    reader: CurrentCaseReader = field(repr=False)


@dataclass(frozen=True, slots=True)
class _Binding:
    tenant_id: str
    account_id: str
    case_id: str
    conversation_id: str
    task_id: str
    authority_case_id: str
    token_digest: bytes = field(repr=False)
    identity: CaseControlIdentity
    reader: CurrentCaseReader = field(repr=False)


@dataclass(eq=False, slots=True)
class _Call:
    deadline: float
    operation_started: bool = False
    abandoned: bool = False
    task: asyncio.Task[dict[str, object]] | None = field(default=None, repr=False)


def _id(value: object) -> str:
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value) is None:
        raise BridgeError("InvalidCommand")
    return value


def _trusted_id(value: object) -> str:
    if (
        type(value) is not str
        or not 1 <= len(value) <= 128
        or value != value.strip()
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise BridgeError("Unavailable")
    value.encode("utf-8")
    return value


def _uuid(value: object) -> str:
    if type(value) is not str or len(value) != 36:
        raise BridgeError("Unavailable")
    try:
        if str(UUID(value)) != value:
            raise ValueError
    except ValueError:
        raise BridgeError("Unavailable") from None
    return value


def _fields(value: object, names: set[str], code: Code = "Unavailable") -> dict[str, object]:
    if type(value) is not dict or set(value) != names:
        raise BridgeError(code)
    return value


def _revision(value: object) -> str:
    if (
        type(value) is not str
        or re.fullmatch(r"0|[1-9][0-9]{0,18}", value) is None
        or int(value) > MAX_REVISION
    ):
        raise BridgeError("Unavailable")
    return value


def _sha(value: object) -> str:
    if type(value) is not str or re.fullmatch(r"[a-f0-9]{64}", value) is None:
        raise BridgeError("Unavailable")
    return value


def _enum(value: object, values: set[str]) -> str:
    if type(value) is not str or value not in values:
        raise BridgeError("Unavailable")
    return value


def _identity(reader: CurrentCaseReader) -> CaseControlIdentity:
    value = reader.identity
    if type(value) is not CaseControlIdentity:
        raise BridgeError("AccessDenied")
    actor = AuthenticatedActor(value.actor_id, value.scope_id)
    if type(value.schema) is not str or re.fullmatch(r"[a-z][a-z0-9_]{0,62}", value.schema) is None:
        raise BridgeError("AccessDenied")
    return CaseControlIdentity(actor.actor_id, actor.scope_id, value.schema)


def _bindings(values: tuple[CurrentCaseBinding, ...]) -> tuple[_Binding, ...]:
    if type(values) is not tuple or not 1 <= len(values) <= 64:
        raise BridgeError("InvalidCommand")
    copied = []
    authorities: dict[tuple[str, str, str], tuple[str, str, str]] = {}
    for value in values:
        if type(value) is not CurrentCaseBinding:
            raise BridgeError("InvalidCommand")
        try:
            identity = _identity(value.reader)
            item = _Binding(
                _id(value.tenant_id),
                _id(value.account_id),
                _id(value.case_id),
                _id(value.conversation_id),
                _trusted_id(value.task_id),
                _uuid(value.authority_case_id),
                hashlib.sha256(BearerToken(value.token).value.encode("ascii")).digest(),
                identity,
                value.reader,
            )
            authority = (identity.schema, identity.scope_id, item.task_id)
            logical = (item.tenant_id, item.account_id, item.case_id)
            if authority in authorities and authorities[authority] != logical:
                raise BridgeError("InvalidCommand")
            authorities[authority] = logical
            copied.append(item)
        except (ValueError, AuthenticationFailed, AttributeError, UnicodeError):
            raise BridgeError("InvalidCommand") from None
    if len({(b.tenant_id, b.account_id, b.case_id, b.conversation_id) for b in copied}) != len(
        copied
    ):
        raise BridgeError("InvalidCommand")
    return tuple(copied)


def _request(value: object) -> dict[str, object]:
    body = _fields(value, {"booking_reference", "new_check_in", "confirmed"})
    reference, stamp = body["booking_reference"], body["new_check_in"]
    if (
        type(reference) is not str
        or not 1 <= len(reference.encode("utf-8")) <= 64
        or any(ord(c) < 32 or ord(c) == 127 for c in reference)
        or type(stamp) is not str
        or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", stamp) is None
        or body["confirmed"] is not True
    ):
        raise BridgeError("Unavailable")
    parsed = date.fromisoformat(stamp)
    if BookingChange(reference, parsed, True).payload() != body:
        raise BridgeError("Unavailable")
    return {
        "schemaVersion": 1,
        "kind": "booking_investigation",
        "bookingReference": reference,
        "newCheckIn": stamp,
        "investigationConsent": True,
    }


def _mutation_result(
    value: object, binding: _Binding, intent_id: str | None, effect_id: str | None
) -> dict[str, object]:
    body = _fields(
        value,
        {
            "schema_version",
            "effect_id",
            "intent_id",
            "task_id",
            "case_id",
            "supplier_id",
            "scope_id",
            "booking_reference",
            "previous_check_in",
            "new_check_in",
            "previous_revision",
            "revision",
            "amount_minor",
            "currency",
            "created_at",
        },
    )
    if (
        type(body["schema_version"]) is not int
        or body["schema_version"] != 1
        or (
            body["task_id"],
            body["case_id"],
            body["scope_id"],
            body["intent_id"],
            body["effect_id"],
        )
        != (
            binding.task_id,
            binding.authority_case_id,
            binding.identity.scope_id,
            intent_id,
            effect_id,
        )
        or intent_id is None
        or effect_id is None
    ):
        raise BridgeError("Unavailable")
    revision = _revision(body["revision"])
    previous = _revision(body["previous_revision"])
    if int(revision) != int(previous) + 1:
        raise BridgeError("Unavailable")
    request = _request(
        {
            "booking_reference": body["booking_reference"],
            "new_check_in": body["new_check_in"],
            "confirmed": True,
        }
    )
    return {
        "supplierId": _uuid(body["supplier_id"]),
        "revision": revision,
        "bookingReference": request["bookingReference"],
        "newCheckIn": request["newCheckIn"],
    }


def _snapshot(value: CaseProjection, binding: _Binding) -> dict[str, object]:
    if type(value) is not CaseProjection:
        raise BridgeError("Unavailable")
    body = value.payload()
    if (
        type(body.get("schema_version")) is not int
        or body["schema_version"] != 1
        or (body.get("task_id"), body.get("case_id"))
        != (binding.task_id, binding.authority_case_id)
    ):
        raise BridgeError("Unavailable")
    workflow = body["lifecycle"]
    if type(workflow) is not dict:
        raise BridgeError("Unavailable")
    state = _enum(
        workflow.get("state"),
        {
            "ready",
            "running",
            "retry_wait",
            "inquiry_complete",
            "waiting",
            "intent_committed",
            "failed",
            "uncertain",
            "completed",
            "cancelled",
        },
    )
    confirmation = _fields(
        body["confirmation"], {"state", "intent_id", "confirmation_id", "committed_at"}
    )
    confirmation_state = _enum(
        confirmation["state"], {"cancelled", "committed", "required", "not_requested"}
    )
    intent_id = None if confirmation["intent_id"] is None else _uuid(confirmation["intent_id"])
    if (confirmation_state == "committed") != (intent_id is not None):
        raise BridgeError("Unavailable")
    effect = body["effect"]
    outcome = body["outcome"]
    effect_state = "not_observed"
    effect_result = None
    if effect is not None:
        effect_body = _fields(
            effect,
            {
                "state",
                "generation",
                "attempt_no",
                "dispatch_count",
                "result",
                "error_code",
                "updated_at",
            },
        )
        effect_state = _enum(
            effect_body["state"],
            {"pending", "claimed", "dispatched", "succeeded", "failed", "uncertain", "cancelled"},
        )
        effect_result = effect_body["result"]
        if intent_id is None or ((effect_state == "succeeded") != (effect_result is not None)):
            raise BridgeError("Unavailable")
    outcome_state, cancellation = "not_observed", "not_observed"
    effect_id, event_id, outcome_result = None, None, None
    if outcome is not None:
        completed = _fields(
            outcome,
            {
                "state",
                "result",
                "error_code",
                "cancellation",
                "created_at",
                "intent_id",
                "effect_id",
                "event_id",
            },
        )
        outcome_state = _enum(completed["state"], {"succeeded", "failed", "uncertain", "cancelled"})
        cancellation = _enum(
            completed["cancellation"],
            {
                "not_requested",
                "cancelled_before_commit",
                "cancelled_before_dispatch",
                "requested_best_effort",
                "already_terminal",
            },
        )
        if completed["intent_id"] != intent_id or (
            (completed["intent_id"] is None) != (completed["effect_id"] is None)
        ):
            raise BridgeError("Unavailable")
        effect_id = None if completed["effect_id"] is None else _uuid(completed["effect_id"])
        event_id = _uuid(completed["event_id"])
        outcome_result = completed["result"]
        if (
            (outcome_state == "succeeded") != (outcome_result is not None)
            or (effect is not None and effect_state != outcome_state)
            or (effect is None and outcome_state != "cancelled")
        ):
            raise BridgeError("Unavailable")
        if outcome_state == "cancelled" and cancellation not in {
            "cancelled_before_commit",
            "cancelled_before_dispatch",
        }:
            raise BridgeError("Unavailable")
    if effect_result is not None and outcome_result is not None and effect_result != outcome_result:
        raise BridgeError("Unavailable")
    result = outcome_result if outcome_result is not None else effect_result
    if result is not None:
        if effect_id is None and type(result) is dict:
            effect_id = _uuid(result.get("effect_id"))
        supplier = _mutation_result(result, binding, intent_id, effect_id)
    else:
        supplier = None
    value_out = {
        "schemaVersion": 1,
        "source": "p1_public_v4",
        "scope": {"tenantId": binding.tenant_id, "accountId": binding.account_id},
        "caseId": binding.case_id,
        "conversationId": binding.conversation_id,
        "revision": _revision(body["case_revision"]),
        "request": _request(body["request"]),
        "workflow": {
            "taskId": binding.task_id,
            "state": state,
            "version": _revision(workflow.get("version")),
        },
        "intent": {
            "state": "committed" if intent_id is not None else "not_committed",
            "intentId": intent_id,
        },
        "mutation": {
            "state": effect_state,
            "outcome": outcome_state,
            "cancellation": cancellation,
            "effectId": effect_id,
            "outcomeEventId": event_id,
        },
        "supplierResult": supplier,
        "sourceRevision": _sha(body["projection_revision"]),
    }
    if (
        len(
            json.dumps(
                value_out, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
        )
        > CASE_BYTES
    ):
        raise BridgeError("Unavailable")
    return value_out


def _pairs(values: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in values:
        if key in result:
            raise BridgeError("InvalidCommand")
        result[key] = value
    return result


def _constant(_: str) -> None:
    raise BridgeError("InvalidCommand")


def _failure(code: Code) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "status": "unavailable",
        "code": code if code in {"AccessDenied", "InvalidCommand", "Overloaded"} else "Unavailable",
    }


class CurrentCaseBridge:
    """Own finite sockets/get tasks; the application separately closes readers."""

    def __init__(
        self,
        bindings: tuple[CurrentCaseBinding, ...],
        *,
        request_timeout_ms: int = 1000,
        close_timeout_ms: int = 2000,
    ) -> None:
        if (
            type(request_timeout_ms) is not int
            or not 20 <= request_timeout_ms <= 2000
            or type(close_timeout_ms) is not int
            or not 20 <= close_timeout_ms <= 2000
        ):
            raise BridgeError("InvalidCommand")
        self._bindings = _bindings(bindings)
        self._timeout, self._close_timeout = request_timeout_ms / 1000, close_timeout_ms / 1000
        self._server: asyncio.Server | None = None
        self._starting: asyncio.Task[asyncio.Server] | None = None
        self._port = 0
        self._closed = False
        self._calls: set[_Call] = set()
        self._connections: set[asyncio.StreamWriter] = set()
        self._closing: dict[asyncio.StreamWriter, asyncio.Task[None]] = {}
        self._handlers: set[asyncio.Task[None]] = set()
        self._close_task: asyncio.Task[None] | None = None
        self._counts = {"known": 0, "unavailable": 0, "telemetry_failed": 0}

    @property
    def port(self) -> int:
        return self._port

    @property
    def pending_count(self) -> int:
        return len(self._calls)

    def metrics(self) -> MappingProxyType[str, int]:
        return MappingProxyType(
            {**self._counts, "active_requests": len(self._calls), "sockets": len(self._connections)}
        )

    def _emit(self, code: str, outcome: str) -> None:
        self._counts[outcome] = min(MAX_COUNTER, self._counts[outcome] + 1)
        try:
            LOGGER.info(
                "p2_current_case_bridge",
                extra={"event": "p2_current_case_bridge", "code": code, "outcome": outcome},
            )
        except Exception:  # noqa: BLE001 - telemetry cannot change case commitment truth
            self._counts["telemetry_failed"] = min(
                MAX_COUNTER, self._counts["telemetry_failed"] + 1
            )

    async def start(self, *, port: int = 0) -> None:
        if self._closed:
            raise BridgeError("Closed")
        if (
            self._starting is not None
            or self._server is not None
            or type(port) is not int
            or not 0 <= port <= 65535
        ):
            raise BridgeError("InvalidCommand")
        self._starting = asyncio.create_task(
            asyncio.start_server(
                self._connected,
                "127.0.0.1",
                port,
                limit=HEADER_BYTES + 1,
                backlog=16,
            )
        )

        def bound(done: asyncio.Task[asyncio.Server]) -> None:
            if not done.cancelled():
                error = done.exception()
                if error is None and self._closed:
                    done.result().close()

        self._starting.add_done_callback(bound)
        self._server = await asyncio.shield(self._starting)
        assert self._server.sockets is not None
        self._port = self._server.sockets[0].getsockname()[1]

    def _connected(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if self._closed or len(self._connections) >= SOCKETS:
            writer.transport.abort()
            return
        self._connections.add(writer)
        task = asyncio.create_task(self._handle(reader, writer))
        self._handlers.add(task)
        task.add_done_callback(self._handler_done)

    def _handler_done(self, task: asyncio.Task[None]) -> None:
        self._handlers.discard(task)
        if not task.cancelled():
            task.exception()

    def _close_writer(self, writer: asyncio.StreamWriter) -> asyncio.Task[None]:
        existing = self._closing.get(writer)
        if existing is not None and (
            not existing.done() or (not existing.cancelled() and existing.exception() is None)
        ):
            return existing
        writer.close()

        async def observe() -> None:
            try:
                await writer.wait_closed()
            except ConnectionError:
                # StreamWriter's closed future settled with connection_lost.
                # This is observed transport closure, not a timer conclusion.
                self._emit("Unavailable", "unavailable")

        task = asyncio.create_task(observe())
        self._closing[writer] = task

        def settled(done: asyncio.Task[None]) -> None:
            if not done.cancelled() and done.exception() is None:
                self._connections.discard(writer)
                if self._closing.get(writer) is done:
                    self._closing.pop(writer, None)

        task.add_done_callback(settled)
        return task

    @staticmethod
    def _check(call: _Call) -> None:
        if call.abandoned or asyncio.get_running_loop().time() >= call.deadline:
            raise BridgeError("Unavailable")

    async def _read(self, reader: asyncio.StreamReader) -> tuple[str, str, dict[str, object]]:
        head = await reader.readuntil(b"\r\n\r\n")
        if len(head) > HEADER_BYTES:
            raise BridgeError("InvalidCommand")
        connection = h11.Connection(h11.SERVER, max_incomplete_event_size=HEADER_BYTES)
        connection.receive_data(head)
        event = connection.next_event()
        if (
            not isinstance(event, h11.Request)
            or event.http_version != b"1.1"
            or event.method != b"POST"
        ):
            raise BridgeError("InvalidCommand")
        lines = head.split(b"\r\n")[1:-2]
        if len(lines) > 16 or any(not line or line[:1] in b" \t" for line in lines):
            raise BridgeError("InvalidCommand")
        names = [line.split(b":", 1)[0].lower() for line in lines]
        if len(set(names)) != len(names):
            raise BridgeError("InvalidCommand")
        headers = dict(event.headers)
        if (
            set(headers)
            != {b"host", b"authorization", b"content-type", b"content-length", b"connection"}
            or headers.get(b"connection") != b"close"
            or headers.get(b"content-type") != b"application/json"
            or headers.get(b"host") != f"127.0.0.1:{self._port}".encode("ascii")
        ):
            raise BridgeError("InvalidCommand")
        length = headers.get(b"content-length", b"")
        if re.fullmatch(rb"0|[1-9][0-9]{0,4}", length) is None or int(length) > BODY_BYTES:
            raise BridgeError("InvalidCommand")
        body = await reader.readexactly(int(length))
        connection.receive_data(body)
        data = bytearray()
        while True:
            part = connection.next_event()
            if isinstance(part, h11.EndOfMessage):
                break
            if not isinstance(part, h11.Data):
                raise BridgeError("InvalidCommand")
            data.extend(part.data)
        target = event.target.decode("ascii")
        if target not in {"/v1/current-case/inspect"}:
            raise BridgeError("InvalidCommand")
        raw_auth = headers.get(b"authorization", b"").decode("ascii")
        if not raw_auth.startswith("Bearer "):
            raise BridgeError("AccessDenied")
        decoded = json.loads(
            bytes(data).decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant
        )
        if type(decoded) is not dict:
            raise BridgeError("InvalidCommand")
        return target, raw_auth[7:], decoded

    def _binding(self, body: dict[str, object], token: str) -> _Binding:
        _fields(body, {"schemaVersion", "scope", "caseId", "conversationId"}, "InvalidCommand")
        if type(body["schemaVersion"]) is not int or body["schemaVersion"] != 1:
            raise BridgeError("InvalidCommand")
        scope = _fields(body["scope"], {"tenantId", "accountId"}, "InvalidCommand")
        reference = (
            _id(scope["tenantId"]),
            _id(scope["accountId"]),
            _id(body["caseId"]),
            _id(body["conversationId"]),
        )
        try:
            digest = hashlib.sha256(BearerToken(token).value.encode("ascii")).digest()
        except AuthenticationFailed:
            raise BridgeError("AccessDenied") from None
        found = None
        for binding in self._bindings:
            matches = hmac.compare_digest(digest, binding.token_digest)
            if matches and reference == (
                binding.tenant_id,
                binding.account_id,
                binding.case_id,
                binding.conversation_id,
            ):
                found = binding
        if found is None or _identity(found.reader) != found.identity:
            raise BridgeError("AccessDenied")
        return found

    async def _operate(self, call: _Call, reader: asyncio.StreamReader) -> dict[str, object]:
        _path, token, body = await self._read(reader)
        binding = self._binding(body, token)
        self._check(call)
        if _identity(binding.reader) != binding.identity:
            raise BridgeError("AccessDenied")
        call.operation_started = True
        value = await binding.reader.get(task_id=binding.task_id, cursor=None, limit=1)
        snapshot = _snapshot(value, binding)
        if _identity(binding.reader) != binding.identity:
            raise BridgeError("AccessDenied")
        self._check(call)
        return {"schemaVersion": 1, "status": "known", "case": snapshot}

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        call: _Call | None = None
        try:
            if len(self._calls) >= REQUESTS:
                response = _failure("Overloaded")
            else:
                call = _Call(asyncio.get_running_loop().time() + self._timeout)
                self._calls.add(call)
                task = asyncio.create_task(self._operate(call, reader))
                call.task = task

                def settled(done: asyncio.Task[dict[str, object]]) -> None:
                    self._calls.discard(call)
                    if not done.cancelled():
                        done.exception()

                task.add_done_callback(settled)
                try:
                    async with asyncio.timeout_at(call.deadline):
                        response = await asyncio.shield(task)
                    self._check(call)
                except (AuthenticationFailed, ExecutionNotFound):
                    response = _failure("AccessDenied")
                except ExecutionCapacityExceeded:
                    response = _failure("Overloaded")
                except BridgeError as error:
                    response = _failure(error.code)
                except TimeoutError:
                    call.abandoned = True
                    response = _failure("Unavailable")
                except asyncio.CancelledError:
                    call.abandoned = True
                    raise
                except Exception:  # noqa: BLE001 - fixed safe outer read boundary
                    response = _failure(
                        "Unavailable" if call.operation_started else "InvalidCommand"
                    )
            outcome = "known" if response["status"] == "known" else "unavailable"
            self._emit(str(response.get("code", "ok")), outcome)
            raw = json.dumps(
                response, ensure_ascii=True, separators=(",", ":"), allow_nan=False
            ).encode("ascii")
            if len(raw) > RESPONSE_BYTES:
                raw = json.dumps(_failure("Unavailable"), separators=(",", ":")).encode("ascii")
            writer.write(
                f"HTTP/1.1 200 Result\r\nContent-Type: application/json\r\nContent-Length: {len(raw)}\r\nConnection: close\r\n\r\n".encode(
                    "ascii"
                )
                + raw
            )
            async with asyncio.timeout(0.1):
                await writer.drain()
        except (ConnectionError, TimeoutError, BridgeError):
            pass
        finally:
            closing = self._close_writer(writer)
            try:
                async with asyncio.timeout(0.1):
                    await asyncio.shield(closing)
            except TimeoutError:
                self._emit("Unavailable", "unavailable")

    async def close(self) -> None:
        self._closed = True
        for call in self._calls:
            call.abandoned = True
        if self._server is not None:
            self._server.close()
        for writer in tuple(self._connections):
            self._close_writer(writer)
        if (
            self._close_task is not None
            and self._close_task.done()
            and (self._close_task.cancelled() or self._close_task.exception() is not None)
        ):
            self._close_task = None
        if self._close_task is None:

            async def finish() -> None:
                failed = False
                if self._starting is not None:
                    try:
                        server = await asyncio.shield(self._starting)
                    except Exception:  # noqa: BLE001 - failed bind owns no listener
                        self._emit("Unavailable", "unavailable")
                    else:
                        server.close()
                        try:
                            await server.wait_closed()
                        except Exception:  # noqa: BLE001 - attempt other cleanup owners
                            failed = True
                handlers = await asyncio.gather(*tuple(self._handlers), return_exceptions=True)
                closed = await asyncio.gather(
                    *tuple(self._closing.values()), return_exceptions=True
                )
                tasks = tuple(call.task for call in self._calls if call.task is not None)
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                if (
                    failed
                    or any(isinstance(value, BaseException) for value in (*handlers, *closed))
                    or self._connections
                ):
                    raise BridgeError("CleanupIncomplete")

            self._close_task = asyncio.create_task(finish())
            self._close_task.add_done_callback(
                lambda done: None if done.cancelled() else done.exception()
            )
        try:
            async with asyncio.timeout(self._close_timeout):
                await asyncio.shield(self._close_task)
        except TimeoutError:
            raise BridgeError("CleanupIncomplete") from None
        if self._calls:
            raise BridgeError("CleanupIncomplete")


async def start_current_case_bridge(
    bindings: tuple[CurrentCaseBinding, ...],
    *,
    port: int = 0,
    request_timeout_ms: int = 1000,
    close_timeout_ms: int = 2000,
) -> CurrentCaseBridge:
    bridge = CurrentCaseBridge(
        bindings, request_timeout_ms=request_timeout_ms, close_timeout_ms=close_timeout_ms
    )
    try:
        await bridge.start(port=port)
    except BaseException:
        try:
            await bridge.close()
        except BridgeError:
            pass
        raise
    return bridge
