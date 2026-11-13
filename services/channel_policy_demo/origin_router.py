"""Two fixed publisher facets with retained, exclusively owned P1 call lifetimes.

Prepared/discovery ports and shared case readers are borrowed. Each successful
factory return transfers one fresh coordinator; a constructed canonical service
then owns that coordinator. The application closes this router exactly once,
then closes borrowed readers. No route cache, durable queue or authority is added.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
from collections.abc import Coroutine
from dataclasses import dataclass, field
from inspect import CO_COROUTINE, getattr_static
from types import FunctionType, MappingProxyType, MethodType
from typing import Literal, Protocol, TypeVar, cast, get_args

from continuity_lab.work_api import WorkError, WorkPayload, WorkRecord, WorkScope
from delegation_reliability import (
    ChannelPolicyCoordinator,
    ChannelPolicyView,
    CoordinatorError,
    channel_policy_key,
    encode_channel_policy_request,
    parse_channel_policy_request,
)
from delegation_reliability.contracts import ContractError, Scope, identifier
from delegation_reliability.coordinator import CoordinatorCode
from delegation_reliability.fixed_policy_contracts import (
    FixedPolicyRequest,
    encode_fixed_policy_request,
    parse_fixed_policy_request,
)

from .discovery import (
    DiscoveryError,
    DiscoveryPage,
    SourceBindingId,
    encode_discovery_page,
    parse_discovery_page,
)
from .executor import DiscoveryPort, PreparedReadPort
from .origin import ChannelOriginBinding, ChannelOriginService
from .wire import (
    ChannelAccountScope,
    ChannelOperationLookup,
    OriginWireError,
    PreparedChannelInput,
    parse_accept_frame,
    parse_lookup_frame,
    parse_profile_frame,
    require_p3_compatible,
    uuid_value,
)

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
MAX_CALLS = 2
MAX_TEMPLATES = 16
Event = Literal["accept", "lookup", "inspect_profile"]
Reply = dict[str, object] | None
Input = PreparedChannelInput | ChannelOperationLookup | str
_CODES = frozenset(get_args(CoordinatorCode))
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class OriginRouterBinding:
    profile_id: str
    scope: Scope
    case_id: str
    conversation_id: str


@dataclass(frozen=True, slots=True)
class RevisionTemplateCatalog:
    """Copied immutable server configuration, never selected from message facts."""

    templates: tuple[FixedPolicyRequest, ...]

    def __post_init__(self) -> None:
        try:
            if type(self.templates) is not tuple or not 1 <= len(self.templates) <= MAX_TEMPLATES:
                raise CoordinatorError("invalid_input")
            copies = []
            for value in self.templates:
                if type(value) is not FixedPolicyRequest:
                    raise CoordinatorError("invalid_input")
                copies.append(parse_fixed_policy_request(encode_fixed_policy_request(value)))
            if len({item.request_revision for item in copies}) != len(copies):
                raise CoordinatorError("invalid_input")
            object.__setattr__(self, "templates", tuple(copies))
        except (ContractError, AttributeError, TypeError, ValueError):
            raise CoordinatorError("invalid_input") from None

    def for_revision(self, revision: int) -> FixedPolicyRequest:
        if type(revision) is not int or not 1 <= revision <= 1000000:
            raise CoordinatorError("invalid_input")
        for item in self.templates:
            if item.request_revision == revision:
                return parse_fixed_policy_request(encode_fixed_policy_request(item))
        raise CoordinatorError("case_state_unavailable")


class CoordinatorFactory(Protocol):
    """Return a fresh idle real public coordinator owning its P1 work client.

    Shared case readers remain borrowed. Failed/cancelled partial construction
    remains factory-owned. A fresh returned resource is router-owned even if it
    fails validation; it is quarantined until actual close and zero pending work.
    Returning a borrowed/shared coordinator or another borrowed reader is invalid.
    """

    async def open(self) -> ChannelPolicyCoordinator: ...


@dataclass(eq=False, slots=True)
class _Call:
    source: SourceBindingId
    event: Event
    raw: bytes = field(repr=False)
    value: Input = field(repr=False)
    deadline: float
    reply: asyncio.Future[Reply] = field(repr=False)
    task: asyncio.Task[None] | None = field(default=None, repr=False)
    coordinator: ChannelPolicyCoordinator | None = field(default=None, repr=False)
    service: ChannelOriginService | None = field(default=None, repr=False)
    returned: bool = False
    closed: bool = False
    abandoned: bool = False
    accept_started: bool = False


def _static_code(error: Exception) -> object:
    try:
        return getattr_static(error, "code", None)
    except Exception:  # noqa: BLE001 - malformed descriptors have no diagnostic authority
        return None


def _safe(error: Exception) -> CoordinatorError:
    if isinstance(error, CoordinatorError):
        code = _static_code(error)
        return CoordinatorError(
            cast(CoordinatorCode, code)
            if type(code) is str and code in _CODES
            else "internal_error"
        )
    if isinstance(error, OriginWireError):
        code = _static_code(error)
        mapping: dict[str, CoordinatorCode] = {
            "InvalidCommand": "invalid_input",
            "AccessDenied": "unauthorized",
            "IdentityConflict": "identity_conflict",
        }
        return CoordinatorError(
            mapping.get(code, "invalid_input") if type(code) is str else "invalid_input"
        )
    if isinstance(error, (ContractError, DiscoveryError)):
        return CoordinatorError("invalid_input")
    return CoordinatorError("storage_unavailable")


def _binding(value: OriginRouterBinding) -> OriginRouterBinding:
    try:
        if type(value) is not OriginRouterBinding or type(value.scope) is not Scope:
            raise CoordinatorError("invalid_input")
        return OriginRouterBinding(
            uuid_value(value.profile_id),
            Scope(identifier(value.scope.tenant_id), identifier(value.scope.account_id)),
            identifier(value.case_id),
            identifier(value.conversation_id),
        )
    except (OriginWireError, ContractError, AttributeError, TypeError, ValueError):
        raise CoordinatorError("invalid_input") from None


def _seconds(value: float) -> float:
    if type(value) not in (int, float) or not 0.02 <= value <= 5 or not math.isfinite(value):
        raise CoordinatorError("invalid_input")
    return float(value)


class _DiscoveryRead(Protocol):
    async def __call__(self) -> DiscoveryPage: ...


class _PreparedRead(Protocol):
    async def __call__(
        self, *, source_binding_id: SourceBindingId, receipt_id: str
    ) -> bytes | None: ...


class _OpenCoordinator(Protocol):
    async def __call__(self) -> ChannelPolicyCoordinator: ...


def _method(value: object, name: str) -> object:
    """Bind declared Python async methods without owner attribute access.

    Ordinary functions, bound methods, static methods and class methods are
    supported. Other callable/descriptor forms, including AsyncMock, are rejected
    before invocation; serving adapters use declared asynchronous methods.
    """
    try:
        raw: object = getattr_static(value, name, None)
        if type(raw) is MethodType:
            bound: object = raw
        elif type(raw) is staticmethod:
            bound = staticmethod.__get__(raw, value, type(value))
        elif type(raw) is classmethod:
            target = cast(type[object], value) if issubclass(type(value), type) else type(value)
            bound = classmethod.__get__(raw, None, target)
        elif type(raw) is FunctionType:
            declared: object = getattr_static(type(value), name, None)
            bound = FunctionType.__get__(raw, value, type(value)) if declared is raw else raw
        else:
            raise CoordinatorError("invalid_input")
        function = bound.__func__ if type(bound) is MethodType else bound
        if type(function) is not FunctionType or not function.__code__.co_flags & CO_COROUTINE:
            raise CoordinatorError("invalid_input")
        return bound
    except Exception:  # noqa: BLE001 - rejected descriptors never supply public diagnostics
        raise CoordinatorError("invalid_input") from None


def _consume(completed: asyncio.Future[T]) -> None:
    if not completed.cancelled():
        completed.exception()


def _spawn(action: Coroutine[object, object, T]) -> asyncio.Task[T]:
    try:
        task = asyncio.create_task(action)
    except BaseException as error:
        action.close()
        if not isinstance(error, Exception):
            raise
        raise CoordinatorError("internal_error") from None
    task.add_done_callback(_consume)
    return task


@dataclass(frozen=True, slots=True)
class ChannelOriginFacet:
    """A fixed source principal; transport authentication belongs its HTTP host."""

    _router: ChannelOriginRouter = field(repr=False)
    source_binding_id: SourceBindingId

    def __post_init__(self) -> None:
        if type(self._router) is not ChannelOriginRouter or self.source_binding_id not in (
            "native",
            "sms",
        ):
            raise CoordinatorError("invalid_input")

    async def accept(self, raw: bytes) -> dict[str, object]:
        result = await self._router._observe(self.source_binding_id, "accept", raw)
        if type(result) is not dict:
            raise CoordinatorError("invalid_stored_state")
        return result

    async def lookup(self, raw: bytes) -> Reply:
        return await self._router._observe(self.source_binding_id, "lookup", raw)

    async def inspect_profile(self, raw: bytes) -> None:
        await self._router._observe(self.source_binding_id, "inspect_profile", raw)


class ChannelOriginRouter:
    """Globally two factory/call/close lifetimes, shared by two borrowed facets.

    Waiter budgets stop the next stage after abandonment; an already-started
    canonical accept retains its ambiguous outcome. Business receipts are returned
    independently of later cleanup. Failed cleanup retains the same owner/slot
    and public close may be retried. Borrowed discovery/prepared ports are never
    closed here, and their own actual I/O may outlive their bounded read waiter.
    """

    def __init__(
        self,
        *,
        binding: OriginRouterBinding,
        discovery: DiscoveryPort,
        prepared: PreparedReadPort,
        templates: RevisionTemplateCatalog,
        coordinators: CoordinatorFactory,
        deadline_window_ms: int = 30000,
        timeout_s: float = 5,
        cleanup_timeout_s: float = 1,
    ) -> None:
        copied = _binding(binding)
        try:
            if type(templates) is not RevisionTemplateCatalog:
                raise CoordinatorError("invalid_input")
            catalogue = RevisionTemplateCatalog(templates.templates)
            for item in catalogue.templates:
                if (
                    item.scope != copied.scope
                    or item.case_id != copied.case_id
                    or item.conversation_id != copied.conversation_id
                ):
                    raise CoordinatorError("unauthorized")
            self._discover = cast(_DiscoveryRead, _method(discovery, "read"))
            self._prepared_read = cast(_PreparedRead, _method(prepared, "read"))
            self._open = cast(_OpenCoordinator, _method(coordinators, "open"))
            if type(deadline_window_ms) is not int or not 20 <= deadline_window_ms <= 60000:
                raise CoordinatorError("invalid_input")
        except CoordinatorError as error:
            raise _safe(error) from None
        except Exception:  # noqa: BLE001 - trusted injection/configuration boundary
            raise CoordinatorError("invalid_input") from None
        self._timeout, self._cleanup = _seconds(timeout_s), _seconds(cleanup_timeout_s)
        self._binding, self._templates, self._window = copied, catalogue, deadline_window_ms
        self._borrowed: tuple[object, ...] = (discovery, prepared, coordinators)
        self._calls: set[_Call] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closing = False
        self._close_task: asyncio.Task[None] | None = None
        self._native, self._sms = (
            ChannelOriginFacet(self, "native"),
            ChannelOriginFacet(self, "sms"),
        )
        self._counts = {
            "started": 0,
            "succeeded": 0,
            "failed": 0,
            "timed_out_waiters": 0,
            "cancelled_waiters": 0,
            "factories_started": 0,
            "cleanup_incomplete": 0,
            "owners_settled": 0,
            "telemetry_failed": 0,
        }

    @property
    def native(self) -> ChannelOriginFacet:
        return self._native

    @property
    def sms(self) -> ChannelOriginFacet:
        return self._sms

    @property
    def pending_count(self) -> int:
        return len(self._calls)

    def metrics(self) -> MappingProxyType[str, int]:
        return MappingProxyType(
            {**self._counts, "active": len(self._calls), "closing": int(self._closing)}
        )

    def _bind(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif loop is not self._loop:
            raise CoordinatorError("invalid_input")
        return loop

    def _log(self, call: _Call, code: str) -> None:
        try:
            safe_code = (
                code if type(code) is str and (code in _CODES or code == "ok") else "internal_error"
            )
            LOGGER.info(
                "channel_origin_router",
                extra={"operation": call.event, "source": call.source, "code": safe_code},
            )
        except Exception:  # noqa: BLE001 - telemetry cannot alter accepted history or cleanup
            self._counts["telemetry_failed"] += 1

    def _route(self, value: PreparedChannelInput) -> None:
        require_p3_compatible(value)
        b = self._binding
        if (
            value.scope != ChannelAccountScope(b.scope.tenant_id, b.scope.account_id)
            or value.case_id != b.case_id
            or value.conversation_id != b.conversation_id
        ):
            raise CoordinatorError("unauthorized")

    def _input(self, event: Event, raw: bytes) -> Input:
        if event == "accept":
            value = parse_accept_frame(raw)
            self._route(value)
            return value
        if event == "lookup":
            query = parse_lookup_frame(raw)
            if query.scope != ChannelAccountScope(
                self._binding.scope.tenant_id, self._binding.scope.account_id
            ):
                raise CoordinatorError("unauthorized")
            return query
        profile = parse_profile_frame(raw)
        if profile != self._binding.profile_id:
            raise CoordinatorError("unauthorized")
        return profile

    def _check(self, call: _Call) -> None:
        if self._closing:
            raise CoordinatorError("closed")
        if call.abandoned:
            raise CoordinatorError("request_aborted")
        if self._bind().time() >= call.deadline:
            raise CoordinatorError("deadline_exceeded")

    def _prune(self) -> None:
        for call in tuple(self._calls):
            if call.closed and call.task is not None and call.task.done():
                self._calls.remove(call)
                self._counts["owners_settled"] += 1

    def _retry_closes(self) -> None:
        self._prune()
        for call in self._calls:
            if call.task is not None and call.task.done() and not call.closed:
                call.task = _spawn(self._close_owner(call))

    async def _attest(self, call: _Call, receipt_id: str) -> PreparedChannelInput:
        raw = await self._prepared_read(source_binding_id=call.source, receipt_id=receipt_id)
        self._check(call)
        if raw is None:
            raise CoordinatorError("not_found")
        try:
            prepared = parse_accept_frame(raw)
            self._route(prepared)
            if prepared.input_receipt_id != receipt_id:
                raise CoordinatorError("identity_conflict")
            return prepared
        except (OriginWireError, ContractError):
            raise CoordinatorError("invalid_stored_state") from None

    async def _coordinator(self, call: _Call) -> ChannelPolicyCoordinator:
        self._counts["factories_started"] += 1
        value = await self._open()
        if any(value is port for port in self._borrowed) or any(
            other is not call and other.coordinator is value for other in self._calls
        ):
            raise CoordinatorError("invalid_input")
        # Preserve fresh malformed returns for cleanup, not for business authority.
        call.returned, call.coordinator = True, value
        if type(value) is not ChannelPolicyCoordinator:
            raise CoordinatorError("invalid_input")
        if value.scope != self._binding.scope:
            raise CoordinatorError("unauthorized")
        if type(value.pending_count) is not int or value.pending_count != 0:
            raise CoordinatorError("invalid_input")
        self._check(call)
        return value

    def _known(self, view: ChannelPolicyView, prepared: PreparedChannelInput) -> FixedPolicyRequest:
        try:
            if (
                type(view) is not ChannelPolicyView
                or type(view.record) is not WorkRecord
                or type(view.record.payload) is not WorkPayload
                or type(view.record.scope) is not WorkScope
            ):
                raise CoordinatorError("invalid_stored_state")
            record = view.record
            payload = WorkPayload(
                record.payload.operation, record.payload.body, record.payload.deadline_at_ms
            )
            WorkRecord(
                record.work_id,
                WorkScope(record.scope.tenant_id, record.scope.account_id),
                record.idempotency_key,
                payload,
                record.accepted_at_ms,
                record.cancel_requested,
                record.status,
            )
            request = parse_channel_policy_request(payload.body)
            b, origin = self._binding, request.origin
            if (
                record.payload.sha256 != hashlib.sha256(payload.body).hexdigest()
                or encode_channel_policy_request(request) != payload.body
                or encode_channel_policy_request(view.request) != payload.body
                or payload.deadline_at_ms != request.deadline_at_ms
                or record.idempotency_key != channel_policy_key(prepared.operation_key)
                or record.scope != WorkScope(b.scope.tenant_id, b.scope.account_id)
                or request.scope != b.scope
                or request.case_id != b.case_id
                or request.conversation_id != b.conversation_id
            ):
                raise CoordinatorError("invalid_stored_state")
            if (
                origin.profile_id != b.profile_id
                or origin.operation_key != prepared.operation_key
                or origin.input_receipt_id != prepared.input_receipt_id
                or origin.payload_sha256 != prepared.payload_sha256
                or origin.payload_byte_length != prepared.payload_byte_length
                or request.request_revision != require_p3_compatible(prepared)
            ):
                raise CoordinatorError("identity_conflict")
            return request.request
        except (ContractError, WorkError, AttributeError, TypeError, ValueError):
            raise CoordinatorError("invalid_stored_state") from None

    def _service(
        self, call: _Call, prepared: PreparedChannelInput, template: FixedPolicyRequest
    ) -> ChannelOriginService:
        if call.coordinator is None:
            raise CoordinatorError("invalid_stored_state")
        service = ChannelOriginService(
            binding=ChannelOriginBinding(
                self._binding.profile_id,
                self._binding.scope,
                self._binding.case_id,
                self._binding.conversation_id,
                prepared.sender_id,
            ),
            template=template,
            coordinator=call.coordinator,
            deadline_window_ms=self._window,
        )
        # Only this service now closes the coordinator; never close both tiers.
        call.service = service
        return service

    async def _business(self, call: _Call) -> Reply:
        self._check(call)
        if call.event == "accept":
            expected = cast(PreparedChannelInput, call.value)
            actual = await self._attest(call, expected.input_receipt_id)
            if actual != expected:
                raise CoordinatorError("identity_conflict")
            coordinator = await self._coordinator(call)
            known = await coordinator.find(channel_policy_key(actual.operation_key))
            self._check(call)
            template = (
                self._templates.for_revision(require_p3_compatible(actual))
                if known is None
                else self._known(known, actual)
            )
            service = self._service(call, actual, template)
            call.accept_started = True
            return await service.accept(call.raw)
        if call.event == "lookup":
            query = cast(ChannelOperationLookup, call.value)
            coordinator = await self._coordinator(call)
            known = await coordinator.find(channel_policy_key(query.operation_key))
            self._check(call)
            if known is None:
                return None
            actual = await self._attest(call, known.request.origin.input_receipt_id)
            if (
                actual.operation_key != query.operation_key
                or actual.payload_sha256 != query.payload_sha256
            ):
                raise CoordinatorError("identity_conflict")
            self._known(known, actual)
            final = await coordinator.find(channel_policy_key(query.operation_key))
            self._check(call)
            if final is None:
                raise CoordinatorError("invalid_stored_state")
            self._known(final, actual)
            if (final.record.work_id, final.record.payload.body) != (
                known.record.work_id,
                known.record.payload.body,
            ):
                raise CoordinatorError("invalid_stored_state")
            return {
                "operationKey": actual.operation_key,
                "scope": {
                    "tenantId": self._binding.scope.tenant_id,
                    "accountId": self._binding.scope.account_id,
                },
                "payloadDigest": actual.payload_sha256,
                "receiptId": uuid_value(final.record.work_id),
            }
        page = parse_discovery_page(encode_discovery_page(await self._discover()))
        self._check(call)
        b = self._binding
        if (
            page.profile_id != b.profile_id
            or page.scope.tenant_id != b.scope.tenant_id
            or page.scope.account_id != b.scope.account_id
            or page.case_id != b.case_id
            or page.conversation_id != b.conversation_id
        ):
            raise CoordinatorError("unauthorized")
        if page.overflow or page.next_cursor is not None:
            raise CoordinatorError("capacity")
        coordinator = await self._coordinator(call)
        if await coordinator.find("p2_origin_preflight") is not None:
            raise CoordinatorError("invalid_stored_state")
        self._check(call)
        return None

    async def _close_owner(self, call: _Call) -> None:
        if not call.returned:
            call.closed = True
            return
        try:
            if call.coordinator is None:
                raise CoordinatorError("cleanup_incomplete")
            if call.service is not None:
                await call.service.close()
            else:
                await call.coordinator.close()
            pending = call.coordinator.pending_count
            if type(pending) is not int or pending != 0:
                raise CoordinatorError("cleanup_incomplete")
        except Exception:  # noqa: BLE001 - never discard a fresh returned partial owner
            self._counts["cleanup_incomplete"] += 1
            self._log(call, "cleanup_incomplete")
            return
        call.closed = True

    async def _lifetime(self, call: _Call) -> None:
        try:
            result = await self._business(call)
            self._counts["succeeded"] += 1
            self._log(call, "ok")
            call.reply.set_result(result)
        except asyncio.CancelledError:
            call.reply.cancel()
            raise
        except Exception as error:  # noqa: BLE001 - one finite outer operation boundary
            safe = _safe(error)
            self._counts["failed"] += 1
            self._log(call, safe.code)
            call.reply.set_exception(safe)
        finally:
            await self._close_owner(call)

    async def _observe(self, source: SourceBindingId, event: Event, raw: bytes) -> Reply:
        loop = self._bind()
        if self._closing:
            raise CoordinatorError("closed")
        try:
            value = self._input(event, raw)
        except Exception as error:  # noqa: BLE001 - closed wire diagnostics only
            raise _safe(error) from None
        self._retry_closes()
        if len(self._calls) >= MAX_CALLS:
            raise CoordinatorError("capacity")
        reply: asyncio.Future[Reply] = loop.create_future()
        reply.add_done_callback(_consume)
        call = _Call(source, event, raw, value, loop.time() + self._timeout, reply)
        self._calls.add(call)
        try:
            call.task = _spawn(self._lifetime(call))
        except BaseException:
            self._calls.remove(call)
            reply.cancel()
            raise
        self._counts["started"] += 1
        try:
            async with asyncio.timeout_at(call.deadline):
                return await asyncio.shield(reply)
        except TimeoutError:
            call.abandoned = True
            self._counts["timed_out_waiters"] += 1
            raise CoordinatorError(
                "acknowledgement_unknown" if call.accept_started else "deadline_exceeded"
            ) from None
        except asyncio.CancelledError:
            call.abandoned = True
            self._counts["cancelled_waiters"] += 1
            raise

    async def _finish_close(self) -> None:
        self._retry_closes()
        tasks = tuple(call.task for call in self._calls if call.task is not None)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._prune()
        if self._calls:
            raise CoordinatorError("cleanup_incomplete")

    async def close(self) -> None:
        loop = self._bind()
        self._closing = True
        deadline = loop.time() + self._cleanup
        # A new observer can inherit an older observer's finite failure. Permit
        # one fresh observation within this caller's same budget, never a rerun.
        for attempt in range(2):
            if (
                self._close_task is not None
                and self._close_task.done()
                and (self._close_task.cancelled() or self._close_task.exception() is not None)
            ):
                self._close_task = None
            if self._close_task is None:
                try:
                    self._close_task = _spawn(self._finish_close())
                except CoordinatorError:
                    raise CoordinatorError("cleanup_incomplete") from None
            try:
                async with asyncio.timeout_at(deadline):
                    await asyncio.shield(self._close_task)
                return
            except TimeoutError:
                self._counts["cleanup_incomplete"] += 1
                raise CoordinatorError("cleanup_incomplete") from None
            except CoordinatorError as error:
                if (
                    _safe(error).code != "cleanup_incomplete"
                    or attempt != 0
                    or loop.time() >= deadline
                    or not self._close_task.done()
                ):
                    raise _safe(error) from None
                self._close_task = None
        raise CoordinatorError("cleanup_incomplete")
