"""Finite loopback HTTP consumer; remote observations never grant durable authority."""

from __future__ import annotations

import asyncio
import logging
import re
import socket
import time
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, Self, cast

from .contracts import (
    MAX_RESULT_BYTES,
    ContractError,
    DelegationRequest,
    DelegationResult,
    Scope,
    decode,
    digest,
    encode_request,
    identifier,
    match_result,
    object_fields,
    parse_error,
    parse_request,
    parse_result,
)
from .document_contracts import (
    DocumentRequest,
    DocumentResult,
    encode_document_request,
    match_document_result,
    parse_document_request,
    parse_document_result,
)
from .fixed_policy_contracts import (
    FixedPolicyRequest,
    FixedPolicyResult,
    encode_fixed_policy_request,
    match_fixed_policy_result,
    parse_fixed_policy_request,
    parse_fixed_policy_result,
)
from .security import EvidenceRecord

if TYPE_CHECKING:
    from .fixed_policy import FixedPolicyResultObservation

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
HttpCode = Literal[
    "invalid_http",
    "body_limit",
    "body_timeout",
    "request_aborted",
    "deadline_exceeded",
    "closing",
    "internal_error",
    "cleanup_incomplete",
    "invalid_response",
    "connection_failed",
    "client_closed",
    "client_capacity",
]
_HTTP_CODES = frozenset(
    {
        "invalid_http",
        "body_limit",
        "body_timeout",
        "request_aborted",
        "deadline_exceeded",
        "closing",
        "internal_error",
        "cleanup_incomplete",
        "invalid_response",
        "connection_failed",
        "client_closed",
        "client_capacity",
    }
)
_AUTH = re.compile(r"Bearer [A-Za-z0-9_-]{43}\Z", re.ASCII)
_LENGTH = re.compile(rb"[1-9][0-9]{0,5}\Z", re.ASCII)
_HEADER_NAME = re.compile(rb"[!#$%&'*+.^_`|~0-9a-z-]+\Z", re.ASCII)
Operation = Literal["invoke", "status", "cancel"]


class SpecialistHttpError(RuntimeError):
    """A fixed safe transport code, without a dependency exception message."""

    def __init__(self, code: HttpCode) -> None:
        if type(code) is not str or code not in _HTTP_CODES:
            code = "internal_error"
        self.code: HttpCode = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class SpecialistEndpoint:
    """Only the explicit local scripted specialist is reachable."""

    port: int
    host: Literal["127.0.0.1"] = "127.0.0.1"

    def __post_init__(self) -> None:
        if type(self.host) is not str or self.host != "127.0.0.1" or type(self.port) is not int:
            raise SpecialistHttpError("invalid_http")
        if not 1 <= self.port <= 65535:
            raise SpecialistHttpError("invalid_http")


@dataclass(frozen=True, slots=True)
class SpecialistResultObservation:
    """Strict correlated bytes observed over HTTP, including historical expiry.

    This is neither durable acceptance nor current case/action authorization.
    """

    result: DelegationResult
    timeliness: Literal["candidate", "expired"]
    observed_at_ms: int


@dataclass(frozen=True, slots=True)
class AttemptObservation:
    """Current ephemeral remote registration; no completion or durable history."""

    scope: Scope
    delegation_id: str
    attempt_id: str
    input_fingerprint: str
    cancel_requested: bool
    deadline_exceeded: bool
    transport_disconnected: bool
    closing: bool
    state: Literal["running"] = "running"
    durable: Literal[False] = False


def parse_observation(payload: bytes) -> AttemptObservation:
    """Reject extra fields, coercions and non-running/non-ephemeral observations."""
    try:
        obj = object_fields(
            decode(payload, 1024),
            {
                "schema_version",
                "kind",
                "scope",
                "delegation_id",
                "attempt_id",
                "input_fingerprint",
                "state",
                "cancel_requested",
                "deadline_exceeded",
                "transport_disconnected",
                "closing",
                "durable",
            },
        )
        scope = object_fields(obj["scope"], {"tenant_id", "account_id"})
        flags = ("cancel_requested", "deadline_exceeded", "transport_disconnected", "closing")
        if (
            type(obj["schema_version"]) is not int
            or obj["schema_version"] != 1
            or obj["kind"] != "specialist.attempt_observation"
            or obj["state"] != "running"
            or obj["durable"] is not False
            or any(type(obj[key]) is not bool for key in flags)
        ):
            raise SpecialistHttpError("invalid_response")
        return AttemptObservation(
            Scope(identifier(scope["tenant_id"]), identifier(scope["account_id"])),
            identifier(obj["delegation_id"]),
            identifier(obj["attempt_id"]),
            digest(obj["input_fingerprint"]),
            cast(bool, obj["cancel_requested"]),
            cast(bool, obj["deadline_exceeded"]),
            cast(bool, obj["transport_disconnected"]),
            cast(bool, obj["closing"]),
        )
    except ContractError:
        raise SpecialistHttpError("invalid_response") from None


def _remote_failure(payload: bytes) -> ContractError | SpecialistHttpError:
    try:
        obj = object_fields(
            decode(payload, 512), {"schema_version", "kind", "code", "request_id", "retryable"}
        )
        if obj["kind"] == "delegation.error":
            return ContractError(parse_error(payload)[0])
        if (
            type(obj["schema_version"]) is not int
            or obj["schema_version"] != 1
            or obj["kind"] != "specialist.http_error"
            or obj["retryable"] is not False
            or type(obj["code"]) is not str
            or obj["code"] not in _HTTP_CODES
        ):
            raise SpecialistHttpError("invalid_response")
        identifier(obj["request_id"])
        return SpecialistHttpError(cast(HttpCode, obj["code"]))
    except (ContractError, SpecialistHttpError):
        return SpecialistHttpError("invalid_response")


@dataclass(eq=False, slots=True)
class _OwnedCall:
    operation: Operation
    deadline: float
    writer: asyncio.StreamWriter | None = field(default=None, repr=False)
    task: asyncio.Task[bytes] | None = field(default=None, repr=False)


class SpecialistClient:
    """One request per connection, no retry, proxy, redirect, queue or import-time I/O.

    A cancelled waiter requests transport cancellation. Its slot remains owned until
    the actual task and socket cleanup settle. Timeout never proves remote work stopped.
    The application owns logging handlers and their execution/flush budgets.
    """

    def __init__(
        self,
        endpoint: SpecialistEndpoint,
        authorization: str,
        *,
        timeout_ms: int = 5000,
        max_active: int = 4,
        cleanup_ms: int = 1000,
    ) -> None:
        if type(endpoint) is not SpecialistEndpoint:
            raise SpecialistHttpError("invalid_http")
        self._endpoint = SpecialistEndpoint(endpoint.port, endpoint.host)
        if type(authorization) is not str or _AUTH.fullmatch(authorization) is None:
            raise SpecialistHttpError("invalid_http")
        if (
            type(timeout_ms) is not int
            or not 20 <= timeout_ms <= 5000
            or type(max_active) is not int
            or not 1 <= max_active <= 16
            or type(cleanup_ms) is not int
            or not 20 <= cleanup_ms <= 1000
        ):
            raise SpecialistHttpError("invalid_http")
        self._authorization = authorization
        self._timeout, self._maximum, self._cleanup = (
            timeout_ms / 1000,
            max_active,
            cleanup_ms / 1000,
        )
        self._owned: set[_OwnedCall] = set()
        self._closed = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._counts = {
            "started": 0,
            "received": 0,
            "validated": 0,
            "validation_failed": 0,
            "failed": 0,
            "cancelled": 0,
            "capacity_rejected": 0,
            "cleanup_failed": 0,
            "telemetry_failed": 0,
        }

    @property
    def active(self) -> int:
        return len(self._owned)

    def metrics(self) -> MappingProxyType[str, int]:
        return MappingProxyType({**self._counts, "active": self.active})

    def _bind(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        if loop is not self._loop:
            raise SpecialistHttpError("invalid_http")
        return loop

    def _emit(self, operation: Operation, code: str, outcome: str) -> None:
        try:
            LOGGER.info(
                "specialist_http",
                extra={
                    "event": "specialist_http",
                    "operation": operation,
                    "code": code,
                    "outcome": outcome,
                },
            )
        except Exception:  # noqa: BLE001 - telemetry cannot replace the transport outcome
            self._counts["telemetry_failed"] += 1

    async def invoke(self, request: DelegationRequest) -> DelegationResult:
        """Return an in-window candidate, preserving the original strict API."""
        return (await self._invoke_result(request, include_expired=False)).result

    async def invoke_observed(self, request: DelegationRequest) -> SpecialistResultObservation:
        """Retain a strict late observation for a durable owner to classify.

        Framing, transport lifetime, identity and evidence-reference checks remain
        mandatory. Only business expiry may be returned as historical data.
        """
        return await self._invoke_result(request, include_expired=True)

    async def _invoke_result(
        self, request: DelegationRequest, *, include_expired: bool
    ) -> SpecialistResultObservation:
        snapshot = parse_request(encode_request(request))
        deadline = self._bind().time() + self._timeout
        payload = await self._call("invoke", snapshot, deadline)
        try:
            result = parse_result(payload)
            observed_at_ms = time.time_ns() // 1_000_000
            timeliness = match_result(snapshot, result, observed_at_ms=observed_at_ms)
            if timeliness == "expired" and not include_expired:
                raise SpecialistHttpError("deadline_exceeded")
            self._check(deadline)
        except ContractError:
            self._counts["validation_failed"] += 1
            self._emit("invoke", "invalid_response", "rejected")
            raise SpecialistHttpError("invalid_response") from None
        except SpecialistHttpError as error:
            self._counts["validation_failed"] += 1
            self._emit("invoke", error.code, "rejected")
            raise
        self._counts["validated"] += 1
        self._emit(
            "invoke", "ok" if timeliness == "candidate" else "deadline_exceeded", "validated"
        )
        return SpecialistResultObservation(result, timeliness, observed_at_ms)

    async def invoke_document(self, request: DocumentRequest) -> DocumentResult:
        """Read-only image capability; never a P1 policy execution result."""
        snapshot = parse_document_request(encode_document_request(request))
        deadline = self._bind().time() + self._timeout
        payload = await self._call("invoke", snapshot, deadline)
        try:
            result = parse_document_result(payload)
            if (
                match_document_result(snapshot, result, observed_at_ms=time.time_ns() // 1_000_000)
                != "candidate"
            ):
                raise SpecialistHttpError("deadline_exceeded")
            self._check(deadline)
        except ContractError:
            self._counts["validation_failed"] += 1
            self._emit("invoke", "invalid_response", "rejected")
            raise SpecialistHttpError("invalid_response") from None
        except SpecialistHttpError as error:
            self._counts["validation_failed"] += 1
            self._emit("invoke", error.code, "rejected")
            raise
        self._counts["validated"] += 1
        self._emit("invoke", "ok", "validated")
        return result

    async def invoke_fixed_policy(self, request: FixedPolicyRequest) -> FixedPolicyResult:
        """Observe correlated in-window bytes; factual verification stays explicit."""
        return (await self._fixed_policy_result(request, include_expired=False)).result

    async def invoke_fixed_policy_observed(
        self, request: FixedPolicyRequest, *, evidence: tuple[EvidenceRecord, ...]
    ) -> FixedPolicyResultObservation:
        """Fully verify supplied source facts before exposing historical data."""
        from .fixed_policy import _snapshot_fixed_policy_pair

        snapshot = parse_fixed_policy_request(encode_fixed_policy_request(request))
        records = _snapshot_fixed_policy_pair(evidence)
        for reference in snapshot.evidence:
            matching = [
                record
                for record in records
                if record.scope == snapshot.scope
                and record.reference.source_id == reference.source_id
            ]
            if len(matching) != 1 or matching[0].reference != reference:
                raise ContractError("evidence_mismatch")
            if reference.media_type != "application/json" or len(matching[0].body) > 4096:
                raise ContractError()
        return await self._fixed_policy_result(snapshot, include_expired=True, evidence=records)

    async def _fixed_policy_result(
        self,
        request: FixedPolicyRequest,
        *,
        include_expired: bool,
        evidence: tuple[EvidenceRecord, ...] | None = None,
    ) -> FixedPolicyResultObservation:
        # Fixed imports at call time avoid a module-initialization cycle; no I/O.
        from .fixed_policy import (
            FixedPolicyResultObservation,
            snapshot_fixed_policy_records,
            verify_fixed_policy_facts,
        )

        snapshot = parse_fixed_policy_request(encode_fixed_policy_request(request))
        records = None if evidence is None else snapshot_fixed_policy_records(evidence)
        deadline = self._bind().time() + self._timeout
        payload = await self._call("invoke", snapshot, deadline)
        try:
            result = parse_fixed_policy_result(payload)
            observed_at_ms = time.time_ns() // 1_000_000
            applicability = match_fixed_policy_result(
                snapshot, result, observed_at_ms=observed_at_ms
            )
            if records is not None:
                applicability = verify_fixed_policy_facts(
                    snapshot, result, records, observed_at_ms=observed_at_ms
                )
            if applicability == "expired" and not include_expired:
                raise SpecialistHttpError("deadline_exceeded")
            self._check(deadline)
        except ContractError:
            self._counts["validation_failed"] += 1
            self._emit("invoke", "invalid_response", "rejected")
            raise SpecialistHttpError("invalid_response") from None
        except SpecialistHttpError as error:
            self._counts["validation_failed"] += 1
            self._emit("invoke", error.code, "rejected")
            raise
        self._counts["validated"] += 1
        self._emit(
            "invoke", "deadline_exceeded" if applicability == "expired" else "ok", "validated"
        )
        return FixedPolicyResultObservation(result, applicability, observed_at_ms)

    async def status_fixed_policy(self, request: FixedPolicyRequest) -> AttemptObservation:
        return await self._observe("status", request)

    async def cancel_fixed_policy(self, request: FixedPolicyRequest) -> AttemptObservation:
        return await self._observe("cancel", request)

    async def status_document(self, request: DocumentRequest) -> AttemptObservation:
        return await self._observe("status", request)

    async def cancel_document(self, request: DocumentRequest) -> AttemptObservation:
        return await self._observe("cancel", request)

    async def status(self, request: DelegationRequest) -> AttemptObservation:
        return await self._observe("status", request)

    async def cancel(self, request: DelegationRequest) -> AttemptObservation:
        return await self._observe("cancel", request)

    async def _observe(
        self,
        operation: Literal["status", "cancel"],
        request: DelegationRequest | DocumentRequest | FixedPolicyRequest,
    ) -> AttemptObservation:
        snapshot = (
            parse_fixed_policy_request(encode_fixed_policy_request(request))
            if type(request) is FixedPolicyRequest
            else parse_document_request(encode_document_request(request))
            if type(request) is DocumentRequest
            else parse_request(encode_request(cast(DelegationRequest, request)))
        )
        deadline = self._bind().time() + self._timeout
        payload = await self._call(operation, snapshot, deadline)
        try:
            result = parse_observation(payload)
            if (
                (result.scope, result.delegation_id, result.attempt_id, result.input_fingerprint)
                != (
                    snapshot.scope,
                    snapshot.delegation_id,
                    snapshot.attempt.attempt_id,
                    snapshot.input_fingerprint,
                )
                or operation == "cancel"
                and not result.cancel_requested
            ):
                raise SpecialistHttpError("invalid_response")
            self._check(deadline)
        except SpecialistHttpError as error:
            self._counts["validation_failed"] += 1
            self._emit(operation, error.code, "rejected")
            raise
        self._counts["validated"] += 1
        self._emit(operation, "ok", "validated")
        return result

    async def _call(
        self,
        operation: Operation,
        request: DelegationRequest | DocumentRequest | FixedPolicyRequest,
        deadline: float,
    ) -> bytes:
        self._bind()
        if self._closed:
            raise SpecialistHttpError("client_closed")
        if len(self._owned) >= self._maximum:
            self._counts["capacity_rejected"] += 1
            raise SpecialistHttpError("client_capacity")
        body = (
            encode_fixed_policy_request(request)
            if type(request) is FixedPolicyRequest
            else encode_document_request(request)
            if type(request) is DocumentRequest
            else encode_request(cast(DelegationRequest, request))
        )
        self._check(deadline)
        owned = _OwnedCall(operation, deadline)
        self._owned.add(owned)
        self._counts["started"] += 1
        task = asyncio.create_task(self._exchange(owned, body))
        owned.task = task

        def settled(completed: asyncio.Task[bytes]) -> None:
            self._owned.discard(owned)
            if not completed.cancelled():
                completed.exception()  # Observe private failure without formatting its cause.

        task.add_done_callback(settled)
        try:
            async with asyncio.timeout_at(deadline + self._cleanup):
                return await asyncio.shield(task)
        except TimeoutError:
            # Caller observation is finite; actual cleanup still owns its slot.
            if not task.cancelling():
                task.cancel()
            raise SpecialistHttpError("cleanup_incomplete") from None
        except asyncio.CancelledError:
            if not task.cancelling():
                task.cancel()
            raise

    @staticmethod
    def _check(deadline: float) -> None:
        if asyncio.get_running_loop().time() >= deadline:
            raise SpecialistHttpError("deadline_exceeded")

    async def _exchange(self, owned: _OwnedCall, body: bytes) -> bytes:
        outcome, code = "failed", "connection_failed"
        try:
            async with asyncio.timeout_at(owned.deadline):
                reader, writer = await asyncio.open_connection(
                    self._endpoint.host, self._endpoint.port, family=socket.AF_INET, limit=8192
                )
                owned.writer = writer
                self._check(owned.deadline)
                headers = (
                    f"POST /v1/{owned.operation} HTTP/1.1\r\nHost: 127.0.0.1:{self._endpoint.port}\r\n"
                    f"Authorization: {self._authorization}\r\nContent-Type: application/json\r\n"
                    f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
                ).encode("ascii")
                writer.write(headers + body)
                await writer.drain()
                head = await reader.readuntil(b"\r\n\r\n")
                self._check(owned.deadline)
                status, length = self._headers(head, owned.operation)
                payload = await reader.readexactly(length)
                # EOF is required: one finite response, no surplus body/pipelined response.
                if await reader.read(1):
                    raise SpecialistHttpError("invalid_response")
                self._check(owned.deadline)
                if status >= 400:
                    raise _remote_failure(payload)
                outcome, code = "received", "ok"
                return payload
        except asyncio.CancelledError:
            outcome, code = "cancelled", "request_aborted"
            raise
        except TimeoutError:
            code = "deadline_exceeded"
            raise SpecialistHttpError("deadline_exceeded") from None
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            code = "invalid_response"
            raise SpecialistHttpError("invalid_response") from None
        except (OSError, ConnectionError):
            raise SpecialistHttpError("connection_failed") from None
        except (SpecialistHttpError, ContractError) as error:
            code = error.code
            raise
        except Exception:  # noqa: BLE001 - outer transport boundary contains dependency diagnostics
            code = "internal_error"
            raise SpecialistHttpError("internal_error") from None
        finally:
            try:
                await self._close_writer(owned)
            finally:
                self._counts[outcome] += 1
                self._emit(owned.operation, code, outcome)

    @staticmethod
    def _headers(head: bytes, operation: Operation) -> tuple[int, int]:
        if len(head) > 8192:
            raise SpecialistHttpError("invalid_response")
        lines = head[:-4].split(b"\r\n")
        status = re.fullmatch(rb"HTTP/1\.1 ([1-5][0-9]{2}) [\x20-\x7e]{0,128}", lines[0])
        if status is None or not 1 <= len(lines) - 1 <= 16:
            raise SpecialistHttpError("invalid_response")
        code = int(status[1])
        if code != (202 if operation == "cancel" else 200) and not 400 <= code <= 599:
            raise SpecialistHttpError("invalid_response")
        headers: dict[bytes, bytes] = {}
        for line in lines[1:]:
            name, separator, value = line.partition(b":")
            lowered = name.lower()
            if (
                not separator
                or _HEADER_NAME.fullmatch(lowered) is None
                or lowered in headers
                or any(byte < 32 and byte != 9 or byte == 127 for byte in value)
            ):
                raise SpecialistHttpError("invalid_response")
            headers[lowered] = value.strip(b" \t")
        length = headers.get(b"content-length", b"")
        maximum = 512 if code >= 400 else MAX_RESULT_BYTES if operation == "invoke" else 1024
        if (
            headers.get(b"content-type") != b"application/json"
            or b"transfer-encoding" in headers
            or b"content-encoding" in headers
            or headers.get(b"connection") != b"close"
            or _LENGTH.fullmatch(length) is None
            or int(length) > maximum
        ):
            raise SpecialistHttpError("invalid_response")
        return code, int(length)

    async def _close_writer(self, owned: _OwnedCall) -> None:
        writer = owned.writer
        if writer is None:
            return
        try:
            writer.close()
            waiter = asyncio.create_task(writer.wait_closed())
        except Exception:  # noqa: BLE001 - fixed cleanup boundary, no private diagnostics
            self._abort(writer)
            self._counts["cleanup_failed"] += 1
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                raise asyncio.CancelledError from None
            raise SpecialistHttpError("cleanup_incomplete") from None
        try:
            async with asyncio.timeout(self._cleanup):
                await asyncio.shield(waiter)
        except asyncio.CancelledError:
            # A close during normal response cleanup still owns the actual socket.
            self._abort(writer)
            await self._settle_cleanup(waiter)
            raise
        except TimeoutError:
            self._abort(writer)
            self._counts["cleanup_failed"] += 1
            # Retain the call permit until actual connection_lost, even if close()
            # reports its finite observation budget exhausted to another waiter.
            await self._settle_cleanup(waiter)
            raise SpecialistHttpError("cleanup_incomplete") from None
        except OSError:
            # A peer reset completed this closed socket; never serialize its cause.
            pass
        except Exception:  # noqa: BLE001 - cleanup cannot expose dependency exception text
            self._abort(writer)
            self._counts["cleanup_failed"] += 1
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                raise asyncio.CancelledError from None
            raise SpecialistHttpError("cleanup_incomplete") from None

    async def _settle_cleanup(self, waiter: asyncio.Task[None]) -> None:
        try:
            await asyncio.shield(waiter)
        except OSError:
            pass
        except Exception:  # noqa: BLE001 - cancellation/timeout cleanup is a safe boundary
            self._counts["cleanup_failed"] += 1

    def _abort(self, writer: asyncio.StreamWriter) -> None:
        try:
            writer.transport.abort()
        except Exception:  # noqa: BLE001 - preserve the fixed cleanup failure
            self._counts["cleanup_failed"] += 1

    async def close(self) -> None:
        loop = self._bind()
        self._closed = True
        deadline = loop.time() + self._cleanup
        tasks = tuple(item.task for item in self._owned if item.task is not None)
        for task in tasks:
            if not task.cancelling():
                task.cancel()
        if tasks:
            try:
                async with asyncio.timeout_at(deadline):
                    await asyncio.shield(asyncio.gather(*tasks, return_exceptions=True))
            except TimeoutError:
                self._counts["cleanup_failed"] += 1
                raise SpecialistHttpError("cleanup_incomplete") from None
        if self._owned or loop.time() > deadline:
            raise SpecialistHttpError("cleanup_incomplete")

    async def __aenter__(self) -> Self:
        self._bind()
        if self._closed:
            raise SpecialistHttpError("client_closed")
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()
