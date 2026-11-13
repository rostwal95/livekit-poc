"""Inert public configuration and two owned, offloaded client startup lifetimes.

Only unreceived startup resources belong to this facade. Successful return
transfers ownership to the job/router; facade close never closes those clients.
"""

from __future__ import annotations

import asyncio
import math
import re
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from inspect import CO_COROUTINE, getattr_static
from types import FunctionType, MappingProxyType, MethodType
from typing import Literal, Protocol, TypeVar, cast

from continuity_lab.authorization import BearerToken
from continuity_lab.delivery_api import DeliveryPort, open_delivery_client
from continuity_lab.execution_api import ExecutionPort, open_execution_client
from continuity_lab.postgres_settings import PostgresSettings
from continuity_lab.work_api import (
    TaskExecutionPort,
    WorkDirectory,
    WorkPrincipal,
    WorkScope,
    open_work_client,
)
from delegation_reliability import ChannelPolicyCoordinator, CoordinatorError
from delegation_reliability.contracts import Scope, identifier
from delegation_reliability.coordinator import CaseAuthorityPort
from delegation_reliability.delivery_contract import ResultReceiverPort
from delegation_reliability.fixed_policy import (
    FixedPolicySpecialistClient,
    snapshot_fixed_policy_records,
)
from delegation_reliability.fixed_policy_execution import FixedPolicyInvocationPort
from delegation_reliability.http_client import SpecialistEndpoint
from delegation_reliability.security import EvidenceRecord

from .jobs import JobError

T = TypeVar("T")
Kind = Literal["execution", "delivery", "coordinator", "specialist", "receiver"]
MAX_STARTUPS = 2


def _require(condition: bool) -> None:
    if not condition:
        raise JobError("invalid_input")


def _scope(value: Scope) -> Scope:
    _require(type(value) is Scope)
    return Scope(identifier(value.tenant_id), identifier(value.account_id))


@dataclass(frozen=True, slots=True)
class PublicWorkConfig:
    settings: PostgresSettings
    directory: WorkDirectory = field(repr=False)
    token: BearerToken = field(repr=False)
    scope: Scope

    def __post_init__(self) -> None:
        try:
            _require(
                type(self.settings) is PostgresSettings and type(self.directory) is WorkDirectory
            )
            _require(type(self.token) is BearerToken)
            settings = self.settings
            object.__setattr__(
                self,
                "settings",
                PostgresSettings(
                    settings.host,
                    settings.port,
                    settings.dbname,
                    settings.user,
                    settings.password,
                    settings.schema,
                ),
            )
            scope = _scope(self.scope)
            token = BearerToken(self.token.value)
            principal = self.directory.authenticate(token)
            if principal.scope != WorkScope(scope.tenant_id, scope.account_id):
                raise JobError("unauthorized")
            principal = WorkPrincipal(
                principal.actor_id, WorkScope(principal.scope.tenant_id, principal.scope.account_id)
            )
            object.__setattr__(self, "scope", scope)
            object.__setattr__(self, "token", token)
            object.__setattr__(self, "directory", WorkDirectory({token: principal}))
        except JobError:
            raise
        except Exception:  # noqa: BLE001 - configured principals and passwords never reflect errors
            raise JobError("invalid_input") from None


@dataclass(frozen=True, slots=True)
class PublicSpecialistConfig:
    endpoint: SpecialistEndpoint
    authorization: str = field(repr=False)

    def __post_init__(self) -> None:
        try:
            _require(type(self.endpoint) is SpecialistEndpoint)
            _require(
                type(self.authorization) is str
                and re.fullmatch(r"Bearer [A-Za-z0-9_-]{43}", self.authorization) is not None
            )
            object.__setattr__(
                self, "endpoint", SpecialistEndpoint(self.endpoint.port, self.endpoint.host)
            )
        except JobError:
            raise
        except Exception:  # noqa: BLE001 - finite configuration boundary
            raise JobError("invalid_input") from None


@dataclass(frozen=True, slots=True)
class PublicReceiverConfig:
    port: int
    publisher_token: str = field(repr=False)
    receiver_id: str
    scope: WorkScope
    recipient_id: str

    def __post_init__(self) -> None:
        try:
            from .wire import uuid_value

            _require(type(self.port) is int and 1 <= self.port <= 65535)
            _require(
                type(self.publisher_token) is str
                and re.fullmatch(r"[A-Za-z0-9_-]{43}", self.publisher_token) is not None
            )
            _require(type(self.scope) is WorkScope)
            object.__setattr__(
                self, "scope", WorkScope(self.scope.tenant_id, self.scope.account_id)
            )
            object.__setattr__(self, "receiver_id", uuid_value(self.receiver_id))
            identifier(self.recipient_id)
        except JobError:
            raise
        except Exception:  # noqa: BLE001 - credentials never enter diagnostic values
            raise JobError("invalid_input") from None


class _Close(Protocol):
    async def __call__(self) -> None: ...


def _close_callback(value: object) -> _Close:
    """Public clients expose ordinary async methods; reject dependency getters."""
    try:
        raw: object = getattr_static(value, "close", None)
        if type(raw) is MethodType:
            function = raw.__func__
            if type(function) is FunctionType and function.__code__.co_flags & CO_COROUTINE:
                return cast(_Close, raw)
        if type(raw) is FunctionType and raw.__code__.co_flags & CO_COROUTINE:
            return cast(
                _Close,
                MethodType(raw, value)
                if getattr_static(type(value), "close", None) is raw
                else raw,
            )
    except Exception:  # noqa: BLE001 - no dynamic descriptors are evaluated
        raise JobError("cleanup_incomplete") from None
    raise JobError("cleanup_incomplete")


def _task(action: Coroutine[object, object, T]) -> asyncio.Task[T]:
    try:
        task = asyncio.create_task(action)
    except BaseException:
        action.close()
        raise
    task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    return task


@dataclass(eq=False, slots=True)
class _Startup:
    kind: Kind
    producer: asyncio.Task[object] | None = field(default=None, repr=False)
    resource: object | None = field(default=None, repr=False)
    cleanup: asyncio.Task[None] | None = field(default=None, repr=False)
    settled: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    abandoned: bool = False
    transferred: bool = False


class PublicClientFactory:
    """Two actual startups shared by origin and jobs; no hidden cancellation gap.

    A cancelled open waits for its actual thread and unreceived resource to settle
    before propagating cancellation. A failed close retains the startup and its
    waiting open until an explicit close retry repairs it. This facade may close
    alongside router/job stop and drain, since transferred clients are never ours.
    Shared case readers close only after both those owners and this facade drain.
    """

    def __init__(
        self,
        *,
        work: PublicWorkConfig,
        specialist: PublicSpecialistConfig,
        receiver: PublicReceiverConfig,
        case_authority: CaseAuthorityPort,
        cleanup_timeout_s: float = 1,
    ) -> None:
        try:
            _require(
                type(work) is PublicWorkConfig
                and type(specialist) is PublicSpecialistConfig
                and type(receiver) is PublicReceiverConfig
            )
            self._work = PublicWorkConfig(work.settings, work.directory, work.token, work.scope)
            self._specialist = PublicSpecialistConfig(specialist.endpoint, specialist.authorization)
            self._receiver = PublicReceiverConfig(
                receiver.port,
                receiver.publisher_token,
                receiver.receiver_id,
                receiver.scope,
                receiver.recipient_id,
            )
            _require(receiver.scope == WorkScope(work.scope.tenant_id, work.scope.account_id))
            _require(
                type(cleanup_timeout_s) in (int, float)
                and 0.001 <= cleanup_timeout_s <= 5
                and math.isfinite(cleanup_timeout_s)
            )
        except JobError:
            raise
        except Exception:  # noqa: BLE001 - reject malformed nested configuration without private args
            raise JobError("invalid_input") from None
        self._cases = case_authority
        self._cleanup = float(cleanup_timeout_s)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._startups: set[_Startup] = set()
        self._closing = False
        self._close_task: asyncio.Task[None] | None = None
        self._transferred = 0
        self._cleanup_setup_failed = 0

    def _bind(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        if self._loop is not loop:
            raise JobError("invalid_input")
        return loop

    @property
    def pending_count(self) -> int:
        return len(self._startups)

    def metrics(self) -> MappingProxyType[str, int]:
        return MappingProxyType(
            {
                "active_startups": self.pending_count,
                "transferred": self._transferred,
                "closing": int(self._closing),
                "cleanup_setup_failed": self._cleanup_setup_failed,
            }
        )

    def _release(self, startup: _Startup, *, transferred: bool = False) -> None:
        startup.resource = None
        startup.transferred = transferred
        if transferred:
            self._transferred += 1
        self._startups.discard(startup)
        startup.settled.set()

    async def _produce(self, startup: _Startup) -> object:
        config = self._work
        if startup.kind in ("execution", "delivery", "coordinator"):
            producer: Callable[[], object]
            if startup.kind == "execution":
                producer = lambda: open_execution_client(
                    settings=config.settings, directory=config.directory, token=config.token
                )
            elif startup.kind == "delivery":
                producer = lambda: open_delivery_client(
                    settings=config.settings, directory=config.directory, token=config.token
                )
            else:
                producer = lambda: open_work_client(
                    settings=config.settings, directory=config.directory, token=config.token
                )
            value = await asyncio.to_thread(producer)
            # Adopt immediately after the actual worker returns, before validation/transfer.
            startup.resource = value
            if value is self._cases or value is self:
                startup.resource = None
                raise JobError("invalid_input")
            port = cast(TaskExecutionPort, value)
            if port.scope != WorkScope(config.scope.tenant_id, config.scope.account_id):
                raise JobError("unauthorized")
            if startup.kind == "coordinator":
                value = ChannelPolicyCoordinator(
                    executions=port, scope=config.scope, case_authority=self._cases, max_active=1
                )
                startup.resource = value
        elif startup.kind == "specialist":
            value = FixedPolicySpecialistClient(
                self._specialist.endpoint, self._specialist.authorization, max_active=1
            )
            startup.resource = value
        else:
            from .result_receiver import ChannelResultReceiver

            receiver = self._receiver
            value = ChannelResultReceiver(
                port=receiver.port,
                publisher_token=receiver.publisher_token,
                receiver_id=receiver.receiver_id,
                scope=receiver.scope,
                recipient_id=receiver.recipient_id,
            )
            startup.resource = value
        _close_callback(value)
        count: object = getattr(
            value, "active" if startup.kind == "specialist" else "pending_count", None
        )
        if type(count) is not int or count != 0:
            raise JobError("invalid_input")
        return value

    def _ensure_cleanup(self, startup: _Startup, *, retry: bool = False) -> None:
        if startup.settled.is_set():
            return
        task = startup.cleanup
        if (
            retry
            and task is not None
            and task.done()
            and (task.cancelled() or task.exception() is not None)
        ):
            startup.cleanup = None
        if startup.cleanup is None:

            async def finish() -> None:
                if startup.producer is not None:
                    await asyncio.gather(asyncio.shield(startup.producer), return_exceptions=True)
                if startup.resource is not None:
                    await _close_callback(startup.resource)()
                    count: object = getattr(
                        startup.resource,
                        "active" if startup.kind == "specialist" else "pending_count",
                        None,
                    )
                    if type(count) is not int or count != 0:
                        raise JobError("cleanup_incomplete")
                self._release(startup)

            startup.cleanup = _task(finish())

    async def _settle_abandoned(self, startup: _Startup) -> bool:
        """Retain actual startup through repeated waiter cancellation, without uncancel."""
        cancelled = False
        startup.abandoned = True
        try:
            self._ensure_cleanup(startup)
        except BaseException as error:
            self._cleanup_setup_failed += 1
            if isinstance(error, asyncio.CancelledError):
                cancelled = True
            elif not isinstance(error, Exception):
                raise
        while not startup.settled.is_set():
            try:
                await startup.settled.wait()
            except asyncio.CancelledError:
                cancelled = True
        return cancelled

    async def _open(self, kind: Kind) -> object:
        self._bind()
        if self._closing:
            raise JobError("closed")
        if self.pending_count >= MAX_STARTUPS:
            raise JobError("capacity")
        startup = _Startup(kind)
        self._startups.add(startup)
        try:
            startup.producer = _task(self._produce(startup))
        except BaseException as error:
            self._release(startup)
            if isinstance(error, Exception):
                raise JobError("unavailable") from None
            raise
        try:
            value = await asyncio.shield(startup.producer)
        except asyncio.CancelledError:
            await self._settle_abandoned(startup)
            raise
        except Exception as error:  # noqa: BLE001 - only fixed public startup failures escape
            cancelled = await self._settle_abandoned(startup)
            if cancelled:
                raise asyncio.CancelledError from None
            if type(error) is JobError:
                code: object = getattr_static(error, "code", None)
                if type(code) is str and code in {"invalid_input", "unauthorized"}:
                    raise JobError(cast(Literal["invalid_input", "unauthorized"], code)) from None
            raise JobError("unavailable") from None
        if self._closing or startup.abandoned:
            cancelled = await self._settle_abandoned(startup)
            if cancelled:
                raise asyncio.CancelledError from None
            raise JobError("closed")
        self._release(startup, transferred=True)
        return value

    async def open_execution(self) -> ExecutionPort:
        return cast(ExecutionPort, await self._open("execution"))

    async def open_delivery(self) -> DeliveryPort:
        return cast(DeliveryPort, await self._open("delivery"))

    async def open_specialist(
        self, *, evidence: tuple[EvidenceRecord, ...]
    ) -> FixedPolicyInvocationPort:
        try:
            _require(type(evidence) is tuple and len(evidence) == 2)
            copied = snapshot_fixed_policy_records(evidence)
            _require(all(record.scope == self._work.scope for record in copied))
        except Exception:  # noqa: BLE001 - immutable evidence remains caller-selected trusted data
            raise JobError("invalid_input") from None
        return cast(FixedPolicyInvocationPort, await self._open("specialist"))

    async def open_receiver(self) -> ResultReceiverPort:
        return cast(ResultReceiverPort, await self._open("receiver"))

    async def open(self) -> ChannelPolicyCoordinator:
        try:
            return cast(ChannelPolicyCoordinator, await self._open("coordinator"))
        except JobError as error:
            code: object = getattr_static(error, "code", None)
            codes = {
                "invalid_input": "invalid_input",
                "unauthorized": "unauthorized",
                "capacity": "capacity",
                "closed": "closed",
                "cleanup_incomplete": "cleanup_incomplete",
                "unavailable": "storage_unavailable",
            }
            safe = (
                codes.get(code, "storage_unavailable")
                if type(code) is str
                else "storage_unavailable"
            )
            from delegation_reliability.coordinator import CoordinatorCode

            raise CoordinatorError(cast(CoordinatorCode, safe)) from None

    async def close(self) -> None:
        loop = self._bind()
        self._closing = True
        for startup in self._startups:
            startup.abandoned = True

        async def finish() -> None:
            starts = tuple(self._startups)
            for startup in starts:
                self._ensure_cleanup(startup, retry=True)
            results = await asyncio.gather(
                *(startup.cleanup for startup in starts if startup.cleanup is not None),
                return_exceptions=True,
            )
            if any(isinstance(value, BaseException) for value in results) or self._startups:
                raise JobError("cleanup_incomplete")

        if (
            self._close_task is not None
            and self._close_task.done()
            and (self._close_task.cancelled() or self._close_task.exception() is not None)
        ):
            self._close_task = None
        if self._close_task is None:
            try:
                self._close_task = _task(finish())
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - retain ownership after cleanup allocation failure
                raise JobError("cleanup_incomplete") from None
        try:
            async with asyncio.timeout_at(loop.time() + self._cleanup):
                await asyncio.shield(self._close_task)
        except TimeoutError:
            raise JobError("cleanup_incomplete") from None
        except Exception:  # noqa: BLE001 - cleanup diagnostics never expose dependency args
            raise JobError("cleanup_incomplete") from None
