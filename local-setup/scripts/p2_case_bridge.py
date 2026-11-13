"""Explicit loopback P2 application adapter over public P1 case CAS commands.

No import-time listener, schema, credential loading or durable command receipt.
A lost revision acknowledgement stays unknown. Current state cannot identify which
command won. This adapter does not atomically couple P2 association revocation to
P1 commitment. Exact confirmation is a separate opt-in controller capability;
quote issuance, supplier and model operations remain outside this adapter.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from types import MappingProxyType
from typing import Literal, Protocol, cast
from uuid import UUID

import h11

from continuity_lab.api import (
    ExecutionCapacityExceeded,
    ExecutionNotFound,
    IdempotencyConflict,
    TransitionConflict,
    UnsupportedOperation,
)
from continuity_lab.case_control_api import (
    ActionIntent,
    BookingChange,
    CaseControlIdentity,
    CaseSnapshot,
)
from continuity_lab.postgres_api import (
    AuthenticatedActor,
    AuthenticationFailed,
    BearerToken,
    CaseCancelled,
    Confirmation,
    DeadlineExpired,
    IntentAlreadyCommitted,
    InvalidConfirmation,
    QuoteExpired,
    StaleRevision,
    parse_confirmation_payload,
)

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
MAX_REVISION = 9_223_372_036_854_775_807
MAX_COUNTER = 9_007_199_254_740_991
HEADER_BYTES = 4096
BODY_BYTES = 8192
SOCKETS = 16
REQUESTS = 4
Code = Literal[
    "AccessDenied",
    "InvalidCommand",
    "RevisionConflict",
    "IdentityConflict",
    "Overloaded",
    "Unavailable",
    "OutcomeUnknown",
    "CleanupIncomplete",
    "Closed",
]


class BridgeError(RuntimeError):
    """Fixed application code; raw dependency errors never cross the adapter."""

    def __init__(self, code: Code) -> None:
        self.code = code
        super().__init__(code)


class DropAcknowledgement(RuntimeError):
    """Trusted test hook only: drop the socket after a successful controller write."""


class CaseClient(Protocol):
    @property
    def identity(self) -> CaseControlIdentity: ...
    async def case(self, *, task_id: str) -> CaseSnapshot: ...
    async def revise(
        self, *, task_id: str, expected_revision: int, request: BookingChange
    ) -> CaseSnapshot: ...
    async def close(self) -> None: ...


class ConfirmationClient(CaseClient, Protocol):
    async def commit_confirmation(
        self, *, task_id: str, confirmation: Confirmation, command_id: str
    ) -> ActionIntent: ...


@dataclass(frozen=True, slots=True)
class CaseBinding:
    tenant_id: str
    account_id: str
    case_id: str
    task_id: str
    authority_case_id: str
    token: str = field(repr=False)
    client: CaseClient = field(repr=False)
    allow_confirmation: bool = False


@dataclass(frozen=True, slots=True)
class _Binding:
    tenant_id: str
    account_id: str
    case_id: str
    task_id: str
    authority_case_id: str
    token_digest: bytes = field(repr=False)
    identity: CaseControlIdentity
    client: CaseClient = field(repr=False)
    confirmer: ConfirmationClient | None = field(repr=False)


@dataclass(eq=False, slots=True)
class _Call:
    deadline: float
    possible_write: bool = False
    operation_started: bool = False
    abandoned: bool = False
    task: asyncio.Task[dict[str, object]] | None = field(default=None, repr=False)


def _id(value: object) -> str:
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value) is None:
        raise BridgeError("InvalidCommand")
    return value


def _uuid(value: object) -> str:
    if type(value) is not str or len(value) != 36:
        raise BridgeError("InvalidCommand")
    try:
        parsed = UUID(value)
    except ValueError:
        raise BridgeError("InvalidCommand") from None
    if parsed.version != 4 or str(parsed) != value:
        raise BridgeError("InvalidCommand")
    return value


def _quote_uuid(value: object) -> str:
    # The public P1 producer derives canonical UUID5 proposal identities.
    # Match its canonical UUID contract without changing operation UUID4 IDs.
    if type(value) is not str or len(value) != 36:
        raise BridgeError("InvalidCommand")
    try:
        if str(UUID(value)) != value:
            raise ValueError
    except ValueError:
        raise BridgeError("InvalidCommand") from None
    return value


def _fields(value: object, names: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != names:
        raise BridgeError("InvalidCommand")
    return value


def _version(value: object) -> None:
    if type(value) is not int or value != 1:
        raise BridgeError("InvalidCommand")


def _revision(value: object) -> int:
    if type(value) is not str or re.fullmatch(r"0|[1-9][0-9]{0,18}", value) is None:
        raise BridgeError("InvalidCommand")
    number = int(value)
    if number > MAX_REVISION:
        raise BridgeError("InvalidCommand")
    return number


def _request(value: object) -> BookingChange:
    body = _fields(
        value, {"schemaVersion", "kind", "bookingReference", "newCheckIn", "investigationConsent"}
    )
    _version(body["schemaVersion"])
    reference, raw_date = body["bookingReference"], body["newCheckIn"]
    if (
        body["kind"] != "booking_investigation"
        or body["investigationConsent"] is not True
        or type(reference) is not str
        or re.fullmatch(r"[A-Z0-9][A-Z0-9._:-]{0,63}", reference) is None
        or type(raw_date) is not str
        or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", raw_date) is None
    ):
        raise BridgeError("InvalidCommand")
    try:
        parsed = date.fromisoformat(raw_date)
    except ValueError:
        raise BridgeError("InvalidCommand") from None
    if parsed.isoformat() != raw_date:
        raise BridgeError("InvalidCommand")
    return BookingChange(reference, parsed, True)


def _request_body(value: BookingChange) -> dict[str, object]:
    if type(value) is not BookingChange:
        raise BridgeError("Unavailable")
    result: dict[str, object] = {
        "schemaVersion": 1,
        "kind": "booking_investigation",
        "bookingReference": value.booking_reference,
        "newCheckIn": value.new_check_in.isoformat(),
        "investigationConsent": value.confirmed,
    }
    _request(result)
    return result


def _identity(client: CaseClient) -> CaseControlIdentity:
    value = client.identity
    if type(value) is not CaseControlIdentity:
        raise BridgeError("AccessDenied")
    actor = AuthenticatedActor(value.actor_id, value.scope_id)
    if type(value.schema) is not str or re.fullmatch(r"[a-z][a-z0-9_]{0,62}", value.schema) is None:
        raise BridgeError("AccessDenied")
    return CaseControlIdentity(actor.actor_id, actor.scope_id, value.schema)


def _bindings(values: tuple[CaseBinding, ...]) -> tuple[_Binding, ...]:
    if type(values) is not tuple or not 1 <= len(values) <= 64:
        raise BridgeError("InvalidCommand")
    copied = []
    for value in values:
        if type(value) is not CaseBinding or type(value.allow_confirmation) is not bool:
            raise BridgeError("InvalidCommand")
        try:
            token = BearerToken(value.token)
            confirmer = None
            if value.allow_confirmation:
                if not callable(getattr(value.client, "commit_confirmation", None)):
                    raise BridgeError("InvalidCommand")
                confirmer = cast(ConfirmationClient, value.client)
            copied.append(
                _Binding(
                    _id(value.tenant_id),
                    _id(value.account_id),
                    _id(value.case_id),
                    _uuid(value.task_id),
                    _uuid(value.authority_case_id),
                    hashlib.sha256(token.value.encode("ascii")).digest(),
                    _identity(value.client),
                    value.client,
                    confirmer,
                )
            )
        except (ValueError, AuthenticationFailed, AttributeError):
            raise BridgeError("InvalidCommand") from None
    if len({(b.tenant_id, b.account_id, b.case_id) for b in copied}) != len(copied):
        raise BridgeError("InvalidCommand")
    if len({(b.identity.schema, b.identity.scope_id, b.task_id) for b in copied}) != len(copied):
        raise BridgeError("InvalidCommand")
    return tuple(copied)


def _snapshot(value: CaseSnapshot, binding: _Binding) -> dict[str, object]:
    if type(value) is not CaseSnapshot or (
        value.task_id,
        value.case_id,
        value.actor_id,
        value.scope_id,
    ) != (
        binding.task_id,
        binding.authority_case_id,
        binding.identity.actor_id,
        binding.identity.scope_id,
    ):
        raise BridgeError("Unavailable")
    if type(value.revision) is not int or not 0 <= value.revision <= MAX_REVISION:
        raise BridgeError("Unavailable")
    if type(value.cancelled) is not bool or (
        value.intent is not None and type(value.intent) is not ActionIntent
    ):
        raise BridgeError("Unavailable")
    try:
        request = _request_body(value.request)
    except (BridgeError, AttributeError, TypeError, ValueError):
        raise BridgeError("Unavailable") from None
    return {
        "scope": {"tenantId": binding.tenant_id, "accountId": binding.account_id},
        "caseId": binding.case_id,
        "revision": str(value.revision),
        "request": request,
        "cancelled": value.cancelled,
        "committed": value.intent is not None,
    }


def _confirmation(body: dict[str, object], binding: _Binding) -> tuple[Confirmation, str, str]:
    if body["explicit"] is not True:
        raise BridgeError("InvalidCommand")
    command_id, quote_id = _uuid(body["commandId"]), _quote_uuid(body["quoteId"])
    revision = _revision(body["expectedRevision"])
    raw, digest = body["quoteJson"], body["quoteDigest"]
    if (
        type(raw) is not str
        or type(digest) is not str
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
    ):
        raise BridgeError("InvalidCommand")
    try:
        encoded = raw.encode("utf-8")
        if not 1 <= len(encoded) <= 4096 or hashlib.sha256(encoded).hexdigest() != digest:
            raise BridgeError("InvalidCommand")
        # Reject duplicate members before the public parser, without normalizing bytes.
        json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
        confirmation = parse_confirmation_payload(raw, explicit=body["explicit"])
        quote = confirmation.quote
        canonical = json.dumps(
            quote.payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        if (
            canonical != raw
            or quote.schema_version != 2
            or quote.quote_id != quote_id
            or quote.revision != revision
            or quote.task_id != binding.task_id
            or quote.case_id != binding.authority_case_id
        ):
            raise BridgeError("InvalidCommand")
    except (ValueError, TypeError, AttributeError, UnicodeError):
        raise BridgeError("InvalidCommand") from None
    return confirmation, command_id, digest


def _confirmation_receipt(
    value: ActionIntent, binding: _Binding, confirmation: Confirmation, command_id: str, digest: str
) -> dict[str, object]:
    if (
        type(value) is not ActionIntent
        or value.quote != confirmation.quote
        or (value.task_id, value.actor_id, value.scope_id, value.revision)
        != (
            binding.task_id,
            binding.identity.actor_id,
            binding.identity.scope_id,
            confirmation.quote.revision,
        )
    ):
        raise BridgeError("OutcomeUnknown")
    return {
        "scope": {"tenantId": binding.tenant_id, "accountId": binding.account_id},
        "caseId": binding.case_id,
        "commandId": command_id,
        "revision": str(value.revision),
        "quoteId": confirmation.quote.quote_id,
        "quoteDigest": digest,
        "intentId": _uuid(value.intent_id),
        "effectId": _uuid(value.effect_id),
    }


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
        "status": "unknown" if code == "OutcomeUnknown" else "rejected",
        "code": code,
    }


class CaseBridge:
    """Owned finite loopback sockets/calls. Supplied case clients close with it."""

    def __init__(
        self,
        bindings: tuple[CaseBinding, ...],
        *,
        request_timeout_ms: int = 1000,
        close_timeout_ms: int = 2000,
        harness_after_revision: Callable[[], Awaitable[None]] | None = None,
        harness_after_confirmation: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        if (
            type(request_timeout_ms) is not int
            or not 20 <= request_timeout_ms <= 5000
            or type(close_timeout_ms) is not int
            or not 20 <= close_timeout_ms <= 5000
            or (harness_after_revision is not None and not callable(harness_after_revision))
            or (harness_after_confirmation is not None and not callable(harness_after_confirmation))
        ):
            raise BridgeError("InvalidCommand")
        self._bindings = _bindings(bindings)
        self._timeout, self._close_timeout = request_timeout_ms / 1000, close_timeout_ms / 1000
        self._hook = harness_after_revision
        self._confirm_hook = harness_after_confirmation
        self._server: asyncio.Server | None = None
        self._starting: asyncio.Task[asyncio.Server] | None = None
        self._port = 0
        self._closed = False
        self._calls: set[_Call] = set()
        self._connections: set[asyncio.StreamWriter] = set()
        self._closing: dict[asyncio.StreamWriter, asyncio.Task[None]] = {}
        self._handlers: set[asyncio.Task[None]] = set()
        self._close_task: asyncio.Task[None] | None = None
        self._counts = {"known": 0, "rejected": 0, "unknown": 0, "telemetry_failed": 0}

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
                "p2_case_bridge",
                extra={"event": "p2_case_bridge", "code": code, "outcome": outcome},
            )
        except Exception:  # noqa: BLE001 - telemetry cannot change case commitment truth
            self._counts["telemetry_failed"] = min(
                MAX_COUNTER, self._counts["telemetry_failed"] + 1
            )

    async def start(self, *, port: int = 0) -> None:
        if self._closed:
            raise BridgeError("Closed")
        if self._starting is not None or type(port) is not int or not 0 <= port <= 65535:
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
                self._emit("Unavailable", "rejected")

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
            b"transfer-encoding" in headers
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
        if target not in {"/v1/case/inspect", "/v1/case/revise", "/v1/case/confirm"}:
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
        _version(body["schemaVersion"])
        scope = _fields(body["scope"], {"tenantId", "accountId"})
        tenant, account, case = _id(scope["tenantId"]), _id(scope["accountId"]), _id(body["caseId"])
        try:
            digest = hashlib.sha256(BearerToken(token).value.encode("ascii")).digest()
        except AuthenticationFailed:
            raise BridgeError("AccessDenied") from None
        found = None
        for binding in self._bindings:
            matches = hmac.compare_digest(digest, binding.token_digest)
            if matches and (tenant, account, case) == (
                binding.tenant_id,
                binding.account_id,
                binding.case_id,
            ):
                found = binding
        if found is None or _identity(found.client) != found.identity:
            raise BridgeError("AccessDenied")
        return found

    async def _operate(self, call: _Call, reader: asyncio.StreamReader) -> dict[str, object]:
        path, token, body = await self._read(reader)
        revising = path == "/v1/case/revise"
        confirming = path == "/v1/case/confirm"
        required = {"schemaVersion", "scope", "caseId"}
        if revising:
            required |= {"expectedRevision", "request"}
        elif confirming:
            required |= {
                "commandId",
                "expectedRevision",
                "quoteId",
                "quoteDigest",
                "quoteJson",
                "explicit",
            }
        _fields(body, required)
        binding = self._binding(body, token)
        if confirming:
            if binding.confirmer is None:
                raise BridgeError("AccessDenied")
            confirmation, command_id, digest = _confirmation(body, binding)
            self._check(call)
            if _identity(binding.client) != binding.identity:
                raise BridgeError("AccessDenied")
            call.operation_started = call.possible_write = True
            intent = await binding.confirmer.commit_confirmation(
                task_id=binding.task_id,
                confirmation=confirmation,
                command_id=command_id,
            )
            receipt = _confirmation_receipt(intent, binding, confirmation, command_id, digest)
            if self._confirm_hook is not None:
                await self._confirm_hook()
            return {"schemaVersion": 1, "status": "known", "confirmation": receipt}
        expected = _revision(body["expectedRevision"]) if revising else None
        request = _request(body["request"]) if revising else None
        expected_request = _request_body(request) if request is not None else None
        self._check(call)
        if _identity(binding.client) != binding.identity:
            raise BridgeError("AccessDenied")
        call.operation_started = True
        if revising:
            assert expected is not None and request is not None
            call.possible_write = True
            value = await binding.client.revise(
                task_id=binding.task_id, expected_revision=expected, request=request
            )
        else:
            value = await binding.client.case(task_id=binding.task_id)
        snapshot = _snapshot(value, binding)
        if revising:
            assert expected is not None and request is not None
            if (
                snapshot["revision"] not in {str(expected), str(expected + 1)}
                or snapshot["request"] != expected_request
                or snapshot["cancelled"] is not False
                or snapshot["committed"] is not False
            ):
                raise BridgeError("OutcomeUnknown")
            if self._hook is not None:
                await self._hook()
        return {"schemaVersion": 1, "status": "known", "case": snapshot}

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        call: _Call | None = None
        response: dict[str, object] | None = None
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
                except DropAcknowledgement:
                    self._emit("OutcomeUnknown", "unknown")
                    return
                except (
                    StaleRevision,
                    CaseCancelled,
                    IntentAlreadyCommitted,
                    TransitionConflict,
                    QuoteExpired,
                    DeadlineExpired,
                    InvalidConfirmation,
                    UnsupportedOperation,
                ):
                    response = _failure("RevisionConflict")
                except IdempotencyConflict:
                    response = _failure("IdentityConflict")
                except (AuthenticationFailed, ExecutionNotFound):
                    response = _failure("AccessDenied")
                except ExecutionCapacityExceeded:
                    response = _failure("Overloaded")
                except BridgeError as error:
                    response = _failure(
                        "OutcomeUnknown"
                        if call.possible_write
                        and error.code
                        not in {
                            "AccessDenied",
                            "RevisionConflict",
                            "IdentityConflict",
                            "Overloaded",
                        }
                        else error.code
                    )
                except TimeoutError:
                    call.abandoned = True
                    response = _failure("OutcomeUnknown" if call.possible_write else "Unavailable")
                except asyncio.CancelledError:
                    call.abandoned = True
                    raise
                except Exception:  # noqa: BLE001 - fixed safe boundary; possible commits stay unknown
                    response = _failure(
                        "OutcomeUnknown"
                        if call.possible_write
                        else "Unavailable"
                        if call.operation_started
                        else "InvalidCommand"
                    )
            assert response is not None
            outcome = (
                "known"
                if response["status"] == "known"
                else "unknown"
                if response["status"] == "unknown"
                else "rejected"
            )
            self._emit(str(response.get("code", "ok")), outcome)
            raw = json.dumps(
                response, ensure_ascii=True, separators=(",", ":"), allow_nan=False
            ).encode("ascii")
            if len(raw) > BODY_BYTES:
                raise BridgeError(
                    "OutcomeUnknown" if call is not None and call.possible_write else "Unavailable"
                )
            status = 200
            writer.write(
                f"HTTP/1.1 {status} Result\r\nContent-Type: application/json\r\nContent-Length: {len(raw)}\r\nConnection: close\r\n\r\n".encode(
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
                # The observer still owns this socket until actual settlement.
                self._emit("Unavailable", "rejected")

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
                if self._starting is not None:
                    try:
                        server = await asyncio.shield(self._starting)
                    except Exception:  # noqa: BLE001 - failed bind owns no listener
                        self._emit("Unavailable", "rejected")
                    else:
                        server.close()
                        await server.wait_closed()
                await asyncio.gather(*tuple(self._handlers), return_exceptions=True)
                closed = await asyncio.gather(
                    *tuple(self._closing.values()), return_exceptions=True
                )
                if any(isinstance(value, BaseException) for value in closed):
                    raise BridgeError("CleanupIncomplete")
                tasks = tuple(call.task for call in self._calls if call.task is not None)
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                unique = {id(binding.client): binding.client for binding in self._bindings}
                outcomes = await asyncio.gather(
                    *(client.close() for client in unique.values()), return_exceptions=True
                )
                if any(isinstance(value, BaseException) for value in outcomes) or self._connections:
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


async def start_case_bridge(
    bindings: tuple[CaseBinding, ...],
    *,
    port: int = 0,
    request_timeout_ms: int = 1000,
    close_timeout_ms: int = 2000,
    harness_after_revision: Callable[[], Awaitable[None]] | None = None,
    harness_after_confirmation: Callable[[], Awaitable[None]] | None = None,
) -> CaseBridge:
    bridge = CaseBridge(
        bindings,
        request_timeout_ms=request_timeout_ms,
        close_timeout_ms=close_timeout_ms,
        harness_after_revision=harness_after_revision,
        harness_after_confirmation=harness_after_confirmation,
    )
    try:
        await bridge.start(port=port)
    except BaseException as error:
        try:
            await bridge.close()
        except BridgeError:
            error.add_note("Bridge startup cleanup is still owned; no new start is authorized.")
        raise
    return bridge
