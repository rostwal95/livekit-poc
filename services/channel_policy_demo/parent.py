"""Explicit Python Parent composition; no Node launch/config loading/DDL/provider ownership.

Sources start before the externally owned Node gateway. Its observed room cursor
then admits the executor and operator listener. Room End leaves this background
application and its independently authorized synthetic SMS channel running.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import math
from collections.abc import Callable, Coroutine, Mapping
from dataclasses import dataclass, field, fields
from pathlib import Path, PosixPath
from types import FunctionType, MappingProxyType, MethodType
from typing import Any, Literal, Protocol, TypeVar, cast

from channel_continuity.codec import AccountScope, ProviderScope
from channel_continuity.native_models import NativeEndpoint

from ._bounded_loopback_http import Endpoint, LoopbackEndpoint
from .application import ChannelPolicyApplication
from .native_room import CurrentResultAttachmentPort, NativeRoomOwner, NativeRoomRoute
from .native_room_admin import LiveKitAdminSettings
from .native_room_state import NodeRoomCursor
from .native_worker_config import InferenceMode
from .native_worker_process import _base
from .operator import (
    ApplicationObservationPort,
    ChannelPolicyOperator,
    RoomOperatorPort,
    SmsOperatorPort,
)
from .operator_http import ChannelPolicyOperatorHttp
from .operator_sms import ChannelPolicySmsClient, SmsRoute
from .owner_config import OwnerProfile, encode_owner_profile, parse_owner_profile
from .room_control import RoomPublisherCredential
from .wire import uuid_value

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
Code = Literal["invalid_input", "conflict", "closed", "unavailable", "cleanup_incomplete"]
Name = Literal["app", "rooms", "sms", "http"]
_CODES = frozenset({"invalid_input", "conflict", "closed", "unavailable", "cleanup_incomplete"})
_AUX = frozenset({11029, 11030, 11031, 11032, 11033})


class ParentError(RuntimeError):
    def __init__(self, code: Code = "unavailable") -> None:
        self.code: Code = code if type(code) is str and code in _CODES else "unavailable"
        super().__init__(self.code)


def _need(value: bool, code: Code = "invalid_input") -> None:
    if not value:
        raise ParentError(code)


def _failure(error: BaseException, fallback: Code = "unavailable") -> ParentError:
    try:
        value = inspect.getattr_static(error, "code", None)
        return ParentError(
            cast(Code, value) if type(value) is str and value in _CODES else fallback
        )
    except Exception:  # noqa: BLE001 - finite outer boundary; no dependency getters/messages
        return ParentError(fallback)


T = TypeVar("T")


def _task(action: Coroutine[Any, Any, T], *, cleanup: bool = False) -> asyncio.Task[T]:
    try:
        result = asyncio.create_task(action, eager_start=False)
    except BaseException as error:
        action.close()
        if isinstance(error, Exception):
            raise ParentError("cleanup_incomplete" if cleanup else "unavailable") from None
        raise
    result.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    return result


@dataclass(frozen=True, slots=True)
class ParentSettings:
    profile: OwnerProfile = field(repr=False)
    admin: LiveKitAdminSettings = field(repr=False)
    operator_bearer: str = field(repr=False)
    owner_epoch: str
    room_directory: Path = field(repr=False)
    python_executable: Path = field(repr=False)
    base_environment: Mapping[str, str] = field(repr=False)
    inference_mode: InferenceMode = "scripted"

    def __post_init__(self) -> None:
        try:
            _need(self.inference_mode == "scripted")
            profile = parse_owner_profile(encode_owner_profile(self.profile))
            _need(type(self.admin) is LiveKitAdminSettings)
            admin = LiveKitAdminSettings(self.admin.api_key, self.admin.api_secret, self.admin.url)
            RoomPublisherCredential(self.operator_bearer)
            credentials = {
                getattr(profile.credentials, item.name) for item in fields(profile.credentials)
            }
            _need(self.operator_bearer not in credentials | {admin.api_key, admin.api_secret})
            uuid_value(self.owner_epoch)
            for path in (self.room_directory, self.python_executable):
                _need(type(path) is PosixPath and path.is_absolute())
            _need(
                not _AUX.intersection(
                    getattr(profile.ports, item.name) for item in fields(profile.ports)
                )
            )
            object.__setattr__(self, "profile", profile)
            object.__setattr__(self, "admin", admin)
            object.__setattr__(
                self, "base_environment", MappingProxyType(_base(self.base_environment))
            )
        except Exception:  # noqa: BLE001 - private startup data has one finite diagnostic
            raise ParentError("invalid_input") from None


class AppPort(ApplicationObservationPort, CurrentResultAttachmentPort, Protocol):
    async def start_sources(self) -> None: ...
    async def start_executor(self) -> None: ...
    async def close(self) -> None: ...


class RoomsPort(RoomOperatorPort, Protocol):
    async def close(self) -> None: ...


class SmsPort(SmsOperatorPort, Protocol):
    async def close(self) -> None: ...


class HttpPort(Protocol):
    async def start(self, port: int = 0) -> Endpoint: ...
    async def close(self) -> None: ...


class _ClosePort(Protocol):
    async def close(self) -> None: ...


R = TypeVar("R", bound=_ClosePort)


def _app(profile: OwnerProfile) -> AppPort:
    return ChannelPolicyApplication(profile)


def _rooms(settings: ParentSettings, app: AppPort, cursor: NodeRoomCursor) -> RoomsPort:
    p, r = settings.profile, settings.profile.route
    route = NativeRoomRoute(
        r.profile_id,
        ProviderScope(r.scope.tenant_id, "livekit", p.native_provider_account_id),
        AccountScope(r.scope.tenant_id, r.scope.account_id),
        r.case_id,
        r.conversation_id,
        NativeEndpoint("127.0.0.1", p.ports.native),
        inference_mode=settings.inference_mode,
    )
    return NativeRoomOwner(
        route,
        owner_epoch=settings.owner_epoch,
        app=app,
        admin=settings.admin,
        publisher=RoomPublisherCredential(p.credentials.native_publisher_token),
        cursor=cursor,
        directory=settings.room_directory,
        python_executable=settings.python_executable,
        base_environment=settings.base_environment,
        # The room observes its retained worker-process drain before closing
        # gateway and LiveKit resources.
        cleanup_timeout_s=30,
    )


def _sms(route: SmsRoute) -> SmsPort:
    return ChannelPolicySmsClient(route)


def _http(operator: ChannelPolicyOperator, bearer: str) -> HttpPort:
    return ChannelPolicyOperatorHttp(operator, bearer=bearer)


@dataclass(frozen=True, slots=True)
class ParentFactories:
    app: Callable[[OwnerProfile], AppPort] = _app
    rooms: Callable[[ParentSettings, AppPort, NodeRoomCursor], RoomsPort] = _rooms
    sms: Callable[[SmsRoute], SmsPort] = _sms
    http: Callable[[ChannelPolicyOperator, str], HttpPort] = _http

    def __post_init__(self) -> None:
        for value in (self.app, self.rooms, self.sms, self.http):
            _need(
                type(value) in (FunctionType, MethodType)
                and not inspect.iscoroutinefunction(value)
                and not inspect.isasyncgenfunction(value)
                and not inspect.isgeneratorfunction(value)
            )


class ChannelPolicyParent:
    """Four fixed owners; actual stages and cleanup observers are retained.

    Successful start describes the operator listener, not an RTC room or model
    readiness. The external launcher keeps Node alive until close really drains.
    """

    def __init__(
        self,
        settings: ParentSettings,
        *,
        startup_timeout_s: float = 15,
        cleanup_timeout_s: float = 60,
        factories: ParentFactories | None = None,
    ) -> None:
        _need(type(settings) is ParentSettings)
        self._settings = ParentSettings(
            settings.profile,
            settings.admin,
            settings.operator_bearer,
            settings.owner_epoch,
            settings.room_directory,
            settings.python_executable,
            settings.base_environment,
            settings.inference_mode,
        )
        for value, maximum in ((startup_timeout_s, 15), (cleanup_timeout_s, 60)):
            _need(type(value) in (int, float) and 0.02 <= value <= maximum and math.isfinite(value))
        self._startup_budget, self._cleanup_budget = (
            float(startup_timeout_s),
            float(cleanup_timeout_s),
        )
        chosen = ParentFactories() if factories is None else factories
        _need(type(chosen) is ParentFactories)
        self._factories = ParentFactories(chosen.app, chosen.rooms, chosen.sms, chosen.http)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._app: AppPort | None = None
        self._owners: dict[Name, _ClosePort] = {}
        self._closed_owners: set[Name] = set()
        self._closers: dict[Name, asyncio.Task[None]] = {}
        self._sources: asyncio.Task[None] | None = None
        self._starting: asyncio.Task[LoopbackEndpoint] | None = None
        self._closing_task: asyncio.Task[None] | None = None
        self._front_task: asyncio.Task[None] | None = None
        self._front_closed = False
        self._source_deadline: float | None = None
        self._start_deadline: float | None = None
        self._cursor: NodeRoomCursor | None = None
        self._endpoint: LoopbackEndpoint | None = None
        self._sources_ready = self._executor_ready = self._closing = self._closed = False
        self._cleanup_allocation_failed = 0

    def _bind(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        _need(self._loop is None or self._loop is loop)
        self._loop = loop
        return loop

    def _check(self, deadline: float | None = None) -> None:
        _need(not self._closing, "closed")
        current = asyncio.current_task()
        if current is not None and current.cancelling():
            raise asyncio.CancelledError
        if deadline is not None:
            _need(self._bind().time() < deadline, "unavailable")

    def _adopt(self, name: Name, value: R) -> R:
        _need(all(value is not previous for previous in self._owners.values()), "unavailable")
        self._owners[name] = value
        return value

    @property
    def ready(self) -> bool:
        return self._endpoint is not None and not self._closing

    def metrics(self) -> MappingProxyType[str, int]:
        return MappingProxyType(
            {
                "sources_ready": int(self._sources_ready and not self._closing),
                "executor_ready": int(self._executor_ready and not self._closing),
                "operator_ready": int(self.ready),
                "closing": int(self._closing),
                "closed": int(self._closed),
                "front_closed": int(self._front_closed),
                "owned_resources": len(self._owners) - len(self._closed_owners),
                "cleanup_allocation_failed": self._cleanup_allocation_failed,
                "startup_active": sum(
                    task is not None and not task.done() for task in (self._sources, self._starting)
                ),
            }
        )

    async def _open_sources(self) -> None:
        self._check(self._source_deadline)
        self._app = self._adopt("app", self._factories.app(self._settings.profile))
        self._check(self._source_deadline)
        await self._app.start_sources()
        self._check(self._source_deadline)
        self._sources_ready = True

    async def start_sources(self) -> None:
        loop = self._bind()
        self._check()
        if self._sources_ready:
            return
        try:
            if self._sources is None:
                self._source_deadline = loop.time() + self._startup_budget
                self._sources = _task(self._open_sources())
            assert self._source_deadline is not None
            async with asyncio.timeout_at(self._source_deadline):
                await asyncio.shield(self._sources)
        except BaseException as error:
            # A launcher may already own a dispatching gateway. Keep App
            # origins alive until its explicit dispatch-quiesce phase.
            self._begin_prepare_shutdown()
            if isinstance(error, Exception):
                raise _failure(error) from None
            raise

    async def _open_operator(self) -> LoopbackEndpoint:
        self._check(self._start_deadline)
        assert self._app is not None and self._cursor is not None
        await self._app.start_executor()
        self._check(self._start_deadline)
        self._executor_ready = True
        rooms = self._adopt("rooms", self._factories.rooms(self._settings, self._app, self._cursor))
        self._check(self._start_deadline)
        p = self._settings.profile
        sms = self._adopt(
            "sms",
            self._factories.sms(
                SmsRoute(
                    p.route.scope.tenant_id,
                    p.sms_provider_account_id,
                    "demo_sms_sender",
                    p.ports.sms,
                )
            ),
        )
        self._check(self._start_deadline)
        operator = ChannelPolicyOperator(rooms, self._app, sms)
        host = self._adopt("http", self._factories.http(operator, self._settings.operator_bearer))
        self._check(self._start_deadline)
        endpoint = await host.start(11033)
        self._check(self._start_deadline)
        _need(
            type(endpoint) is LoopbackEndpoint
            and endpoint.host == "127.0.0.1"
            and endpoint.port == 11033,
            "unavailable",
        )
        self._endpoint = LoopbackEndpoint(endpoint.host, endpoint.port)
        return self._endpoint

    async def start(self, cursor: NodeRoomCursor) -> LoopbackEndpoint:
        loop = self._bind()
        self._check()
        _need(type(cursor) is NodeRoomCursor)
        try:
            selected = NodeRoomCursor(
                cursor.node_epoch, cursor.generation, cursor.recovery_required, cursor.control_port
            )
        except Exception:  # noqa: BLE001 - malformed observed cursor has no allocation or private text
            raise ParentError("invalid_input") from None
        occupied = {
            getattr(self._settings.profile.ports, item.name)
            for item in fields(self._settings.profile.ports)
        } | {11030, 11031, 11032, 11033}
        _need(selected.control_port not in occupied)
        _need(self._cursor is None or self._cursor == selected, "conflict")
        _need(self._sources_ready and self._app is not None, "unavailable")
        try:
            if self._starting is None:
                self._cursor = selected
                self._start_deadline = loop.time() + self._startup_budget
                self._starting = _task(self._open_operator())
            if self.ready:
                assert self._endpoint is not None
                return self._endpoint
            assert self._start_deadline is not None
            async with asyncio.timeout_at(self._start_deadline):
                return await asyncio.shield(self._starting)
        except BaseException as error:
            self._begin_prepare_shutdown()
            if isinstance(error, Exception):
                raise _failure(error) from None
            raise

    def _begin_close(self) -> None:
        self._begin_prepare_shutdown()
        if (
            self._closing_task is None
            or self._closing_task.done()
            and (self._closing_task.cancelled() or self._closing_task.exception() is not None)
        ):
            try:
                self._closing_task = _task(self._finish_close(), cleanup=True)
            except Exception:  # noqa: BLE001 - actual owners remain retained for explicit close
                self._cleanup_allocation_failed = min(
                    9007199254740991, self._cleanup_allocation_failed + 1
                )

    def _begin_prepare_shutdown(self) -> None:
        self._closing = True
        if (
            self._front_task is None
            or self._front_task.done()
            and (self._front_task.cancelled() or self._front_task.exception() is not None)
        ):
            try:
                self._front_task = _task(self._finish_prepare_shutdown(), cleanup=True)
            except Exception:  # noqa: BLE001 - all returned owners remain retained for explicit close
                self._cleanup_allocation_failed = min(
                    9007199254740991, self._cleanup_allocation_failed + 1
                )

    async def _close_one(self, name: Name) -> None:
        if name in self._closed_owners or name not in self._owners:
            return
        task = self._closers.get(name)
        if task is None or task.done() and (task.cancelled() or task.exception() is not None):
            task = _task(self._owners[name].close(), cleanup=True)
            self._closers[name] = task
        await asyncio.shield(task)
        self._closed_owners.add(name)

    async def _finish_prepare_shutdown(self) -> None:
        startup = tuple(task for task in (self._sources, self._starting) if task is not None)
        if startup:
            await asyncio.gather(
                *(asyncio.shield(task) for task in startup), return_exceptions=True
            )
        await self._close_one("http")
        observers = []
        failed = False
        for name in ("rooms", "sms"):
            try:
                observers.append(_task(self._close_one(name), cleanup=True))
            except Exception:  # noqa: BLE001 - attempt each independent tier owner
                failed = True
        if observers:
            values = await asyncio.gather(*observers, return_exceptions=True)
            failed = failed or any(isinstance(value, BaseException) for value in values)
        _need(not failed, "cleanup_incomplete")
        self._front_closed = True

    async def prepare_shutdown(self) -> None:
        """Drain room/operator owners while application origin listeners stay live.

        The launcher observes this before globally quiescing gateway dispatch.
        Timeout/cancellation abandons only this observer; the same front task and
        every returned resource stay owned for the next observation.
        """
        self._bind()
        self._begin_prepare_shutdown()
        try:
            _need(self._front_task is not None, "cleanup_incomplete")
            assert self._front_task is not None
            async with asyncio.timeout(min(45, self._cleanup_budget)):
                await asyncio.shield(self._front_task)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - private owner failures stay behind one finite code
            raise ParentError("cleanup_incomplete") from None

    async def _finish_close(self) -> None:
        _need(self._front_task is not None, "cleanup_incomplete")
        assert self._front_task is not None
        await asyncio.shield(self._front_task)
        await self._close_one("app")
        self._closed = True

    async def close(self) -> None:
        """Close owned resources after the caller's external dispatch barrier.

        A composition with a gateway must first await prepare_shutdown(), then
        quiesce that gateway's actual dispatch owners. Parent does not own or
        independently verify an externally supplied gateway's lifecycle.
        """
        self._bind()
        self._begin_close()
        try:
            _need(self._closing_task is not None, "cleanup_incomplete")
            assert self._closing_task is not None
            async with asyncio.timeout(self._cleanup_budget):
                await asyncio.shield(self._closing_task)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - no dependency/private values cross shutdown boundary
            raise ParentError("cleanup_incomplete") from None
