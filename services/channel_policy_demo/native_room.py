"""One Parent-owned physical native room; business execution remains independent.

The browser controls only the Parent CAS tuple. Parent selects every route,
identity and capability before publication. A genuine worker owns the sole
NativeRuntime/AgentSession; this module never constructs either SDK object.
Construction/import is inert. All original external mutation requests are sent
at most once, and an unresolved actual owner blocks the next physical room.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import math
import secrets
from collections.abc import Callable, Coroutine, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path, PosixPath
from types import FunctionType, MappingProxyType, MethodType
from typing import Any, Literal, Protocol, TypeVar, cast
from uuid import uuid4

from channel_continuity.codec import AccountScope, ProviderScope
from channel_continuity.native_models import NativeBinding, NativeCredential, NativeEndpoint

from .application import CurrentResultReadPort
from .current_result import (
    CurrentResultObservation,
    encode_current_result_observation,
    parse_current_result_observation,
)
from .current_result_http import CurrentResultEndpoint, RoomCurrentResultHttp
from .current_result_producer import NativeResultReadPort
from .native_models import ScriptedModelProfile
from .native_room_admin import LiveKitAdminSettings, LiveKitRoomAdmin, RoomPresence
from .native_room_state import (
    MAX_GENERATION,
    BrowserRoomGrant,
    ClosedRoomReceipt,
    EndCommand,
    NativeRoomError,
    NativeRoomStatus,
    NodeRoomCursor,
    PrivateRoomState,
    RoomCode,
    RoomDescriptor,
    RoomFiles,
    RoomIdentity,
    RoomStage,
    StartCommand,
    _need,
    _uuid,
    now_utc,
    room_metadata,
)
from .native_worker_config import NativeWorkerConfig, encode_native_worker_config
from .native_worker_process import NativeWorkerProcess, WorkerProcessStatus, _base
from .room_control import (
    RoomAttach,
    RoomAttachmentObservation,
    RoomBinding,
    RoomCommand,
    RoomObservation,
    RoomOpen,
    RoomPublication,
    RoomPublisherCredential,
    RoomRevocation,
)
from .room_control_client import RoomControlHttpClient
from .room_result_client import (
    RoomResultBinding,
    RoomResultEndpoint,
    RoomResultHttpClient,
    RoomViewCredential,
)

_T = TypeVar("_T")
_MAX_COUNTER = 9007199254740991
_ROOM_CODES = frozenset(
    {
        "invalid_input",
        "conflict",
        "capacity",
        "closed",
        "unavailable",
        "outcome_unknown",
        "cleanup_incomplete",
        "recovery_required",
    }
)


def _finite(error: BaseException, fallback: RoomCode = "unavailable") -> NativeRoomError:
    """Copy one static own finite code; never forward dependency messages/getters."""
    try:
        value = inspect.getattr_static(error, "code", None)
        code = cast(RoomCode, value) if type(value) is str and value in _ROOM_CODES else fallback
    except Exception:  # noqa: BLE001 - finite application boundary; preserve actual owners and private errors
        code = fallback
    return NativeRoomError(code)


def _task(operation: Coroutine[Any, Any, _T], *, cleanup: bool = False) -> asyncio.Task[_T]:
    try:
        task = asyncio.create_task(operation, eager_start=False)
    except BaseException as error:
        operation.close()
        if isinstance(error, Exception):
            raise NativeRoomError("cleanup_incomplete" if cleanup else "unavailable") from None
        raise
    task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    return task


def _method(value: object, name: str, *, asynchronous: bool) -> Callable[..., Any]:
    """Capture a real function/method without invoking arbitrary descriptors."""
    try:
        raw = inspect.getattr_static(value, name)
        if type(raw) is FunctionType:
            result = raw.__get__(value, type(value))
        elif type(raw) is MethodType:
            result = raw
        else:
            raise ValueError
        _need(inspect.iscoroutinefunction(result) is asynchronous)
        _need(not inspect.isasyncgenfunction(result) and not inspect.isgeneratorfunction(result))
        return cast(Callable[..., Any], result)
    except Exception:  # noqa: BLE001 - finite application boundary; preserve actual owners and private errors
        raise NativeRoomError("invalid_input") from None


@dataclass(frozen=True, slots=True)
class NativeRoomRoute:
    """Trusted immutable route; browser/model input never supplies these fields."""

    profile_id: str
    provider_scope: ProviderScope
    account_scope: AccountScope
    case_id: str
    conversation_id: str
    native_endpoint: NativeEndpoint = field(
        default_factory=lambda: NativeEndpoint("127.0.0.1", 11024)
    )
    prepare_port: int = 11030
    rehydration_endpoint: NativeEndpoint = field(
        default_factory=lambda: NativeEndpoint("127.0.0.1", 11032)
    )
    current_port: int = 11031
    model_profile: ScriptedModelProfile = field(default_factory=ScriptedModelProfile)

    def __post_init__(self) -> None:
        try:
            _uuid(self.profile_id)
            _need(
                type(self.provider_scope) is ProviderScope
                and type(self.account_scope) is AccountScope
            )
            provider = ProviderScope(
                self.provider_scope.tenant_id,
                self.provider_scope.provider,
                self.provider_scope.provider_account_id,
            )
            account = AccountScope(self.account_scope.tenant_id, self.account_scope.account_id)
            _need(provider.provider == "livekit" and provider.tenant_id == account.tenant_id)
            _need(
                type(self.native_endpoint) is NativeEndpoint
                and type(self.rehydration_endpoint) is NativeEndpoint
            )
            _need(type(self.model_profile) is ScriptedModelProfile)
            binding = NativeBinding(
                "00000000-0000-4000-8000-000000000001",
                provider,
                account,
                self.case_id,
                self.conversation_id,
                "room",
                "participant",
                "agent",
            )
            # Validate the exact public worker route/profile without touching a
            # file, asset, SDK session, environment variable or network socket.
            copied = NativeWorkerConfig(
                self.profile_id,
                binding,
                "YQ.Yg.Yw",
                NativeCredential("a" * 43),
                "b" * 43,
                "c" * 43,
                self.model_profile,
                self.native_endpoint,
                self.prepare_port,
                self.rehydration_endpoint,
                self.current_port,
            )
            object.__setattr__(self, "provider_scope", copied.binding.provider_scope)
            object.__setattr__(self, "account_scope", copied.binding.account_scope)
            object.__setattr__(self, "native_endpoint", copied.native_endpoint)
            object.__setattr__(self, "rehydration_endpoint", copied.rehydration_endpoint)
            object.__setattr__(self, "model_profile", copied.model_profile)
        except Exception:  # noqa: BLE001 - finite application boundary; preserve actual owners and private errors
            raise NativeRoomError("invalid_input") from None


class CurrentResultAttachmentPort(Protocol):
    def attach_current_result(self, native: NativeResultReadPort) -> CurrentResultReadPort: ...
    async def close_current_result(self) -> None: ...


class RoomAdminPort(Protocol):
    @property
    def pending_count(self) -> int: ...
    def mint(
        self, *, room: str, identity: str, role: Literal["browser", "agent"], expires_at: str
    ) -> str: ...
    async def inspect(self, identity: RoomIdentity) -> RoomPresence: ...
    async def create(self, identity: RoomIdentity) -> RoomIdentity: ...
    async def delete(self, identity: RoomIdentity) -> None: ...
    async def settle(self) -> None: ...
    async def close(self) -> None: ...


class RoomControlPort(Protocol):
    @property
    def pending_count(self) -> int: ...
    async def open(self, request: RoomOpen) -> RoomObservation: ...
    async def attach(self, request: RoomAttach) -> RoomAttachmentObservation: ...
    async def observe(self, command: RoomCommand, *, binding: RoomBinding) -> RoomObservation: ...
    async def close_room(
        self, command: RoomCommand, *, binding: RoomBinding
    ) -> RoomObservation: ...
    async def close(self) -> None: ...


class RoomViewPort(NativeResultReadPort, Protocol):
    @property
    def pending_count(self) -> int: ...
    async def close(self) -> None: ...


class CurrentHostPort(Protocol):
    @property
    def pending_count(self) -> int: ...
    async def start(self, port: int = 11031) -> CurrentResultEndpoint: ...
    async def close(self) -> None: ...


class WorkerPort(Protocol):
    @property
    def pending_count(self) -> int: ...
    def status(self) -> WorkerProcessStatus: ...
    async def start(self) -> None: ...
    async def wait_prepare(self) -> None: ...
    async def wait_terminal(self) -> None: ...
    async def wait_exit(self) -> int: ...
    async def stop(self) -> None: ...


def _admin(settings: LiveKitAdminSettings) -> RoomAdminPort:
    return LiveKitRoomAdmin(settings)


def _control(publisher: RoomPublisherCredential, port: int) -> RoomControlPort:
    return RoomControlHttpClient(publisher, port=port)


def _view(cursor: NodeRoomCursor, command: RoomCommand, token: str) -> RoomViewPort:
    return RoomResultHttpClient(
        RoomResultEndpoint("127.0.0.1", cursor.control_port),
        RoomResultBinding(command.node_epoch, command.generation),
        RoomViewCredential(token),
    )


def _host(
    reader: CurrentResultReadPort, predicate: Callable[[], bool], token: str
) -> CurrentHostPort:
    return RoomCurrentResultHttp(reader, is_current=predicate, current_bearer=token)


def _worker(python: Path, config: Path, environment: Mapping[str, str]) -> WorkerPort:
    return NativeWorkerProcess(python, config, environment)


@dataclass(frozen=True, slots=True)
class NativeRoomPorts:
    """Explicit owned factories; defaults construct genuine serving adapters."""

    admin: Callable[[LiveKitAdminSettings], RoomAdminPort] = _admin
    control: Callable[[RoomPublisherCredential, int], RoomControlPort] = _control
    view: Callable[[NodeRoomCursor, RoomCommand, str], RoomViewPort] = _view
    host: Callable[[CurrentResultReadPort, Callable[[], bool], str], CurrentHostPort] = _host
    worker: Callable[[Path, Path, Mapping[str, str]], WorkerPort] = _worker

    def __post_init__(self) -> None:
        for function in (self.admin, self.control, self.view, self.host, self.worker):
            _need(
                type(function) in (FunctionType, MethodType)
                and not inspect.iscoroutinefunction(function)
                and not inspect.isasyncgenfunction(function)
                and not inspect.isgeneratorfunction(function)
            )


@dataclass(slots=True)
class _Activation:
    start: StartCommand
    generation: str
    node_open: RoomOpen = field(repr=False)
    identity: RoomIdentity
    native_binding: NativeBinding
    current_bearer: str = field(repr=False)
    prepare_bearer: str = field(repr=False)
    startup_deadline: float
    expires_monotonic: float
    state: PrivateRoomState = field(repr=False)
    startup: asyncio.Task[BrowserRoomGrant] | None = None
    ending: asyncio.Task[None] | None = None
    monitor: asyncio.Task[None] | None = None
    timer: asyncio.TimerHandle | None = None
    admin: RoomAdminPort | None = field(default=None, repr=False)
    control: RoomControlPort | None = field(default=None, repr=False)
    view: RoomViewPort | None = field(default=None, repr=False)
    reader: CurrentResultReadPort | None = field(default=None, repr=False)
    host: CurrentHostPort | None = field(default=None, repr=False)
    worker: WorkerPort | None = field(default=None, repr=False)
    descriptor: RoomDescriptor | None = field(default=None, repr=False)
    files: RoomFiles | None = field(default=None, repr=False)
    grant: BrowserRoomGrant | None = field(default=None, repr=False)
    terminal: NativeRoomStatus | None = None
    receipt: ClosedRoomReceipt | None = None
    front: dict[str, asyncio.Task[None]] = field(default_factory=dict, repr=False)
    front_done: set[str] = field(default_factory=set)
    closing: bool = False
    attached: bool = False
    create_attempted: bool = False
    open_attempted: bool = False
    close_attempted: bool = False
    delete_attempted: bool = False
    g_closed: bool = False
    sfu_absent: bool = False
    admin_closed: bool = False
    control_closed: bool = False
    view_closed: bool = False


@dataclass(frozen=True, slots=True)
class _ClosedActivation:
    start: StartCommand
    status: NativeRoomStatus


class NativeRoomOwner:
    """Serial physical room owner with immutable Parent/Node versions kept apart.

    A process restart with an unresolved active descriptor fails closed. This is
    not an automatic crash-recovery manager. End proves as-of SFU absence and
    closes native/current capabilities; existing RTC JWTs retain their original
    expiration and are not represented as permanently revoked credentials.
    """

    def __init__(
        self,
        route: NativeRoomRoute,
        *,
        owner_epoch: str,
        app: CurrentResultAttachmentPort,
        admin: LiveKitAdminSettings,
        publisher: RoomPublisherCredential,
        cursor: NodeRoomCursor,
        directory: Path,
        python_executable: Path,
        base_environment: Mapping[str, str],
        startup_timeout_s: float = 15,
        cleanup_timeout_s: float = 2,
        ports: NativeRoomPorts | None = None,
    ) -> None:
        try:
            _need(
                type(route) is NativeRoomRoute
                and type(admin) is LiveKitAdminSettings
                and type(publisher) is RoomPublisherCredential
                and type(cursor) is NodeRoomCursor
            )
            self._route = NativeRoomRoute(
                route.profile_id,
                route.provider_scope,
                route.account_scope,
                route.case_id,
                route.conversation_id,
                route.native_endpoint,
                route.prepare_port,
                route.rehydration_endpoint,
                route.current_port,
                route.model_profile,
            )
            self._epoch = _uuid(owner_epoch)
            self._admin = LiveKitAdminSettings(admin.api_key, admin.api_secret, admin.url)
            self._publisher = RoomPublisherCredential(publisher.value)
            self._cursor = NodeRoomCursor(
                cursor.node_epoch, cursor.generation, cursor.recovery_required, cursor.control_port
            )
            _need(
                cursor.control_port
                not in {
                    route.native_endpoint.port,
                    route.prepare_port,
                    route.rehydration_endpoint.port,
                    route.current_port,
                }
            )
            _need(
                type(directory) is PosixPath
                and directory.is_absolute()
                and type(python_executable) is PosixPath
                and python_executable.is_absolute()
            )
            self._directory, self._python = directory, python_executable
            self._environment = _base(base_environment)
            for value, maximum in ((startup_timeout_s, 15), (cleanup_timeout_s, 15)):
                _need(
                    type(value) in (int, float)
                    and 0.02 <= value <= maximum
                    and math.isfinite(value)
                )
            self._startup_budget, self._cleanup_budget = (
                float(startup_timeout_s),
                float(cleanup_timeout_s),
            )
            self._attach = cast(
                Callable[[NativeResultReadPort], CurrentResultReadPort],
                _method(app, "attach_current_result", asynchronous=False),
            )
            self._detach = cast(
                Callable[[], Coroutine[Any, Any, None]],
                _method(app, "close_current_result", asynchronous=True),
            )
            selected = NativeRoomPorts() if ports is None else ports
            _need(type(selected) is NativeRoomPorts)
            self._ports = NativeRoomPorts(
                selected.admin, selected.control, selected.view, selected.host, selected.worker
            )
        except Exception:  # noqa: BLE001 - finite application boundary; preserve actual owners and private errors
            raise NativeRoomError("invalid_input") from None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._generation = 0
        self._current: _Activation | None = None
        self._last: _ClosedActivation | None = None
        self._closing = False
        self._recovery_required = cursor.recovery_required
        self._counts = {
            "starts": 0,
            "closed": 0,
            "conflicts": 0,
            "unknown": 0,
            "cleanupIncomplete": 0,
        }

    def _bind(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        _need(self._loop is None or self._loop is loop)
        self._loop = loop
        return loop

    def _count(self, name: str) -> None:
        self._counts[name] = min(_MAX_COUNTER, self._counts[name] + 1)

    @property
    def pending_count(self) -> int:
        # This is a union physical owner metric, not a sum of SDK/HTTP tasks.
        return int(self._current is not None)

    def metrics(self) -> MappingProxyType[str, int]:
        return MappingProxyType(
            {
                **self._counts,
                "physicalOwners": self.pending_count,
                "recoveryRequired": int(self._recovery_required),
            }
        )

    def _status(self, record: _Activation) -> NativeRoomStatus:
        if record.terminal is not None:
            return record.terminal
        worker = record.worker.status() if record.worker is not None else None
        terminal_worker = worker is not None and self._worker_terminal(worker)
        ready = (
            worker is not None and worker.sdk_ready and not record.closing and not terminal_worker
        )
        stage = (
            "recovery_required"
            if self._recovery_required
            else "closing"
            if record.closing or terminal_worker
            else "ready"
            if ready
            else "waiting_browser"
            if record.grant is not None
            else "preparing"
        )
        return NativeRoomStatus(
            self._epoch,
            record.generation,
            record.start.command_id,
            cast(RoomStage, stage),
            now_utc(),
            self._cursor,
            ready,
            worker.running if worker is not None else False,
            record.node_open.binding.expires_at,
        )

    def status(self) -> NativeRoomStatus:
        if self._current is not None:
            return self._status(self._current)
        if self._last is not None:
            if self._recovery_required:
                previous = self._last.status
                return NativeRoomStatus(
                    self._epoch,
                    previous.generation,
                    previous.original_start_command_id,
                    "recovery_required",
                    now_utc(),
                    self._cursor,
                )
            return self._last.status
        return NativeRoomStatus(
            self._epoch,
            "0",
            None,
            "recovery_required" if self._recovery_required else "idle",
            now_utc(),
            self._cursor,
        )

    def _current_room(self, record: _Activation) -> bool:
        worker = record.worker.status() if record.worker is not None else None
        return (
            self._current is record
            and not record.closing
            and not self._closing
            and (worker is None or not self._worker_terminal(worker))
            and self._loop is not None
            and self._loop.time() < record.expires_monotonic
        )

    @staticmethod
    def _worker_terminal(worker: WorkerProcessStatus) -> bool:
        return (
            worker.protocol_failed
            or worker.stage in {"session_closed", "closed", "failed"}
            or worker.spawned
            and not worker.running
        )

    def _admit(self, record: _Activation) -> None:
        loop = self._bind()
        current = asyncio.current_task()
        if current is not None and current.cancelling():
            raise asyncio.CancelledError
        _need(self._current_room(record) and loop.time() < record.startup_deadline, "closed")

    def _reserve(self, start: StartCommand) -> _Activation:
        loop = self._bind()
        stamp = uuid4().hex
        expiry = datetime.now(UTC) + timedelta(seconds=180)
        expires_at = expiry.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        native, view, current, prepare = (secrets.token_urlsafe(32) for _ in range(4))
        _need(len({native, view, current, prepare, self._publisher.value}) == 5, "unavailable")
        binding_id = str(uuid4())
        b = RoomBinding(
            binding_id,
            native,
            "cp_room_" + stamp,
            "cp_browser_" + stamp,
            "cp_agent_" + stamp,
            expires_at,
        )
        opening = RoomOpen(self._cursor.node_epoch, self._cursor.generation, str(uuid4()), b, view)
        route = self._route
        binding = NativeBinding(
            binding_id,
            route.provider_scope,
            route.account_scope,
            route.case_id,
            route.conversation_id,
            b.room_id,
            b.participant_id,
            b.agent_id,
        )
        record = _Activation(
            start,
            str(int(start.expected_generation) + 1),
            opening,
            RoomIdentity(b.room_id, room_metadata(start, binding_id)),
            binding,
            current,
            prepare,
            loop.time() + self._startup_budget,
            loop.time() + 180,
            PrivateRoomState(self._directory),
        )
        self._generation += 1
        self._current = record
        self._count("starts")
        try:
            record.timer = loop.call_at(record.expires_monotonic, self._begin_end, record)
        except BaseException as error:
            self._begin_end(record)
            if isinstance(error, Exception):
                raise NativeRoomError("unavailable") from None
            raise
        return record

    async def start(self, command: StartCommand) -> BrowserRoomGrant:
        loop = self._bind()
        _need(type(command) is StartCommand)
        original = StartCommand(
            command.owner_epoch, command.expected_generation, command.command_id
        )
        current_task = asyncio.current_task()
        if current_task is not None and current_task.cancelling():
            raise asyncio.CancelledError
        _need(original.owner_epoch == self._epoch, "conflict")
        if self._last is not None and original.command_id == self._last.start.command_id:
            _need(original == self._last.start, "conflict")
            raise NativeRoomError("closed")
        record = self._current
        if record is not None:
            _need(record.start == original, "conflict")
            _need(not record.closing, "closed")
        else:
            _need(not self._closing, "closed")
            _need(not self._recovery_required, "recovery_required")
            _need(int(original.expected_generation) == self._generation, "conflict")
            _need(
                self._generation < MAX_GENERATION and int(self._cursor.generation) < MAX_GENERATION,
                "capacity",
            )
            try:
                record = self._reserve(original)
            except Exception as error:  # noqa: BLE001 - finite application boundary; preserve actual owners and private errors
                raise _finite(error) from None
        if record.grant is not None:
            _need(self._current_room(record), "closed")
            return record.grant
        try:
            if record.startup is None:
                record.startup = _task(self._start_actual(record))
            remaining = record.startup_deadline - loop.time()
            _need(remaining > 0, "closed")
            async with asyncio.timeout(remaining):
                grant = await asyncio.shield(record.startup)
            _need(self._current_room(record), "closed")
            return grant
        except BaseException as error:
            self._begin_end(record)
            if isinstance(error, asyncio.CancelledError):
                raise
            if isinstance(error, Exception):
                raise _finite(error) from None
            raise

    async def _start_actual(self, record: _Activation) -> BrowserRoomGrant:
        try:
            self._admit(record)
            record.admin = self._ports.admin(self._admin)
            record.control = self._ports.control(self._publisher, self._cursor.control_port)
            b = record.node_open.binding
            browser = record.admin.mint(
                room=b.room_id, identity=b.participant_id, role="browser", expires_at=b.expires_at
            )
            agent = record.admin.mint(
                room=b.room_id, identity=b.agent_id, role="agent", expires_at=b.expires_at
            )
            route = self._route
            config = NativeWorkerConfig(
                route.profile_id,
                record.native_binding,
                agent,
                NativeCredential(b.native_bearer),
                record.prepare_bearer,
                record.current_bearer,
                route.model_profile,
                route.native_endpoint,
                route.prepare_port,
                route.rehydration_endpoint,
                route.current_port,
                self._admin.rtc_url,
            )
            record.descriptor = RoomDescriptor(
                record.start,
                record.generation,
                record.node_open,
                browser,
                hashlib.sha256(encode_native_worker_config(config)).hexdigest(),
                record.identity.metadata,
            )
            record.files = await asyncio.to_thread(record.state.prepare, record.descriptor, config)
            self._admit(record)
            before = await record.admin.inspect(record.identity)
            self._admit(record)
            _need(before.state == "absent", "conflict")
            record.create_attempted = True
            identity = await record.admin.create(record.identity)
            _need(
                type(identity) is RoomIdentity
                and identity.name == b.room_id
                and identity.metadata == record.descriptor.metadata
                and identity.sid is not None,
                "outcome_unknown",
            )
            record.identity = RoomIdentity(identity.name, identity.metadata, identity.sid)
            self._admit(record)
            record.open_attempted = True
            observation = await record.control.open(record.node_open)
            self._accept_node(record, observation, ready=True)
            self._admit(record)
            record.view = self._ports.view(
                self._cursor, record.node_open.command(), record.node_open.room_view_bearer
            )
            reader = self._attach(record.view)
            record.reader = reader
            record.attached = True
            self._admit(record)
            record.host = self._ports.host(
                reader, lambda: self._current_room(record), record.current_bearer
            )
            endpoint = await record.host.start(route.current_port)
            _need(
                endpoint.host == "127.0.0.1" and endpoint.port == route.current_port, "unavailable"
            )
            self._admit(record)
            record.worker = self._ports.worker(
                self._python, record.files.worker_config_path, self._environment
            )
            await record.worker.start()
            self._admit(record)
            record.monitor = _task(self._monitor(record))
            await record.worker.wait_prepare()
            self._admit(record)
            command = record.node_open.command()
            attached = await record.control.attach(
                RoomAttach(
                    command.node_epoch,
                    command.generation,
                    command.open_id,
                    b.binding_id,
                    record.prepare_bearer,
                )
            )
            _need(
                type(attached) is RoomAttachmentObservation
                and (
                    attached.node_epoch,
                    attached.generation,
                    attached.open_id,
                    attached.binding_id,
                    attached.state,
                )
                == (
                    command.node_epoch,
                    command.generation,
                    command.open_id,
                    b.binding_id,
                    "attached",
                ),
                "outcome_unknown",
            )
            self._admit(record)
            grant = BrowserRoomGrant(
                self._epoch,
                record.generation,
                record.start.command_id,
                browser,
                b.room_id,
                b.participant_id,
                b.agent_id,
                b.binding_id,
                b.expires_at,
                url=self._admin.rtc_url,
            )
            record.grant = grant
            return grant
        except BaseException as error:
            if isinstance(error, Exception) and _finite(error).code == "recovery_required":
                self._recovery_required = True
            self._begin_end(record)
            if isinstance(error, Exception):
                raise _finite(error) from None
            raise

    def _accept_node(
        self, record: _Activation, value: RoomObservation, *, ready: bool = False
    ) -> None:
        command = record.node_open.command()
        _need(
            type(value) is RoomObservation
            and (value.node_epoch, value.generation, value.open_id)
            == (command.node_epoch, command.generation, command.open_id),
            "outcome_unknown",
        )
        if value.publication is not None:
            p = value.publication
            _need(type(p) is RoomPublication, "outcome_unknown")
            RoomPublication(p.binding_id, p.binding_digest, p.published_at, p.expires_at)
            _need(
                (p.binding_id, p.expires_at)
                == (record.node_open.binding.binding_id, record.node_open.binding.expires_at),
                "outcome_unknown",
            )
        if value.revocation is not None:
            r = value.revocation
            _need(type(r) is RoomRevocation, "outcome_unknown")
            RoomRevocation(r.binding_id, r.state, r.revoked_at)
        RoomObservation(
            value.node_epoch,
            value.generation,
            value.open_id,
            value.state,
            value.publication,
            value.revocation,
            value.global_reader_drained,
        )
        if ready:
            _need(
                value.state == "ready"
                and value.publication is not None
                and value.publication.binding_id == record.node_open.binding.binding_id,
                "outcome_unknown",
            )
        if value.state == "closed":
            _need(
                value.revocation is not None
                and value.revocation.binding_id == record.node_open.binding.binding_id,
                "outcome_unknown",
            )
        self._cursor = NodeRoomCursor(
            value.node_epoch, value.generation, False, self._cursor.control_port
        )

    async def _monitor(self, record: _Activation) -> None:
        assert record.worker is not None
        try:
            await record.worker.wait_terminal()
        finally:
            if not record.closing:
                self._begin_end(record)

    def _begin_end(self, record: _Activation) -> None:
        # Called synchronously by End, timeout, stop, worker exit and grant timer.
        # The captured HTTP predicate becomes false before any draining await.
        record.closing = True
        if record.timer is not None:
            record.timer.cancel()
            record.timer = None
        if (
            record.ending is None
            or record.ending.done()
            and (record.ending.cancelled() or record.ending.exception() is not None)
        ):
            try:
                record.ending = _task(self._finish_end(record), cleanup=True)
            except Exception:  # noqa: BLE001 - finite application boundary; preserve actual owners and private errors
                # Actual resources remain on record; explicit close/End retries
                # task allocation without dropping an owner or emitting secrets.
                self._count("cleanupIncomplete")

    async def _front_owner(
        self, record: _Activation, name: str, action: Callable[[], Coroutine[Any, Any, None]]
    ) -> None:
        if name in record.front_done:
            return
        previous = record.front.get(name)
        if (
            previous is None
            or previous.done()
            and (previous.cancelled() or previous.exception() is not None)
        ):
            previous = _task(action(), cleanup=True)
            record.front[name] = previous
        await asyncio.shield(previous)
        record.front_done.add(name)

    async def _independent_closes(
        self,
        record: _Activation,
        actions: list[tuple[str, Callable[[], Coroutine[Any, Any, None]]]],
    ) -> None:
        observers: list[asyncio.Task[None]] = []
        try:
            for name, action in actions:
                observers.append(_task(self._front_owner(record, name, action), cleanup=True))
        except BaseException:
            if observers:
                await asyncio.gather(*observers, return_exceptions=True)
            raise
        if observers:
            values = await asyncio.gather(*observers, return_exceptions=True)
            _need(
                all(not isinstance(value, BaseException) for value in values), "cleanup_incomplete"
            )

    async def _front_drain(self, record: _Activation) -> None:
        actions: list[tuple[str, Callable[[], Coroutine[Any, Any, None]]]] = []
        if record.worker is not None:
            actions.append(("worker", record.worker.stop))
        if record.host is not None:
            actions.append(("host", record.host.close))
        if record.attached:
            actions.append(("producer", self._detach))
        await self._independent_closes(record, actions)
        if record.monitor is not None:
            await asyncio.gather(asyncio.shield(record.monitor), return_exceptions=True)
        if record.worker is not None:
            status = record.worker.status()
            _need(
                (not status.spawned or status.reaped and status.returncode is not None)
                and not status.running
                and record.worker.pending_count == 0,
                "cleanup_incomplete",
            )
        if record.host is not None:
            _need(record.host.pending_count == 0, "cleanup_incomplete")

    async def _close_g(self, record: _Activation) -> None:
        if record.g_closed or not record.open_attempted:
            record.g_closed = True
            return
        assert record.control is not None
        command = record.node_open.command()
        if not record.close_attempted:
            # Observe the original identity first, especially after an unknown
            # open acknowledgement. A conflicting/absent original stays unknown;
            # it never causes a fresh open or unrelated version to be adopted.
            value = await record.control.observe(command, binding=record.node_open.binding)
            self._accept_node(record, value)
            if value.state != "closed":
                record.close_attempted = True
                value = await record.control.close_room(command, binding=record.node_open.binding)
        else:
            value = await record.control.observe(command, binding=record.node_open.binding)
        self._accept_node(record, value)
        _need(value.state == "closed", "cleanup_incomplete")
        record.g_closed = True

    async def _close_sfu(self, record: _Activation) -> None:
        if record.sfu_absent or not record.create_attempted:
            return
        assert record.admin is not None
        # A timed-out public call still owns actual transport work. Observe its
        # completion before deciding whether a same-name room may still appear.
        await record.admin.settle()
        found = await record.admin.inspect(record.identity)
        if found.state == "absent":
            _need(record.identity.sid is not None, "outcome_unknown")
            record.sfu_absent = True
            return
        _need(found.state == "owned" and found.room is not None, "outcome_unknown")
        assert found.room is not None
        _need(
            found.room.name == record.identity.name
            and found.room.metadata == record.identity.metadata
            and found.room.sid is not None,
            "outcome_unknown",
        )
        if record.identity.sid is None:
            # Only our one attempted create, original metadata and original name
            # permit adoption after its unknown acknowledgement.
            record.identity = found.room
        _need(found.room == record.identity, "outcome_unknown")
        if not record.delete_attempted:
            record.delete_attempted = True
            await record.admin.delete(record.identity)
        await record.admin.settle()
        after = await record.admin.inspect(record.identity)
        _need(after.state == "absent", "cleanup_incomplete")
        record.sfu_absent = True

    async def _finish_end(self, record: _Activation) -> None:
        try:
            if record.startup is not None:
                await asyncio.gather(asyncio.shield(record.startup), return_exceptions=True)
            await self._front_drain(record)
            if record.view is not None and not record.view_closed:
                await record.view.close()
                _need(record.view.pending_count == 0, "cleanup_incomplete")
                record.view_closed = True
            await self._close_g(record)
            await self._close_sfu(record)
            final: list[tuple[str, Callable[[], Coroutine[Any, Any, None]]]] = []
            if record.control is not None and not record.control_closed:
                final.append(("control_adapter", record.control.close))
            if record.admin is not None and not record.admin_closed:
                final.append(("admin_adapter", record.admin.close))
            await self._independent_closes(record, final)
            if record.control is not None:
                _need(record.control.pending_count == 0, "cleanup_incomplete")
                record.control_closed = True
            if record.admin is not None:
                _need(record.admin.pending_count == 0, "cleanup_incomplete")
                record.admin_closed = True
            _need(not self._recovery_required, "recovery_required")
            if record.receipt is None:
                closed = NativeRoomStatus(
                    self._epoch,
                    record.generation,
                    record.start.command_id,
                    "closed",
                    now_utc(),
                    self._cursor,
                    False,
                    False,
                    record.node_open.binding.expires_at,
                )
                child = record.worker.status() if record.worker is not None else None
                descriptor_sha = (
                    record.files.descriptor_sha256 if record.files is not None else None
                )
                record.receipt = ClosedRoomReceipt(
                    closed,
                    record.identity,
                    descriptor_sha,
                    child.returncode if child is not None and child.spawned else None,
                    "observed_absent" if record.create_attempted else "never_created",
                    "reaped" if child is not None and child.spawned else "never_started",
                )
            await asyncio.to_thread(record.state.finish, record.receipt)
            record.terminal = record.receipt.status
            if self._current is record:
                self._current = None
                self._last = _ClosedActivation(record.start, record.terminal)
                self._count("closed")
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - finite application boundary; preserve actual owners and private errors
            self._count("cleanupIncomplete")
            if _finite(error).code == "outcome_unknown":
                self._count("unknown")
            raise _finite(error, "cleanup_incomplete") from None

    async def _observe_end(self, record: _Activation) -> NativeRoomStatus:
        self._begin_end(record)
        try:
            _need(record.ending is not None, "cleanup_incomplete")
            assert record.ending is not None
            async with asyncio.timeout(self._cleanup_budget):
                await asyncio.shield(record.ending)
            _need(record.terminal is not None, "cleanup_incomplete")
            assert record.terminal is not None
            return record.terminal
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - finite application boundary; preserve actual owners and private errors
            raise _finite(error, "cleanup_incomplete") from None

    async def end(self, command: EndCommand) -> NativeRoomStatus:
        self._bind()
        _need(type(command) is EndCommand)
        original = EndCommand(
            command.owner_epoch, command.generation, command.original_start_command_id
        )
        _need(original.owner_epoch == self._epoch, "conflict")
        if self._last is not None and original == EndCommand(
            self._epoch, self._last.status.generation, self._last.start.command_id
        ):
            return self._last.status
        record = self._current
        _need(
            record is not None
            and original == EndCommand(self._epoch, record.generation, record.start.command_id),
            "conflict",
        )
        return await self._observe_end(cast(_Activation, record))

    def is_current(self, command: EndCommand) -> bool:
        _need(type(command) is EndCommand)
        original = EndCommand(
            command.owner_epoch, command.generation, command.original_start_command_id
        )
        record = self._current
        return (
            record is not None
            and original == EndCommand(self._epoch, record.generation, record.start.command_id)
            and self._current_room(record)
        )

    async def read_current(self, command: EndCommand) -> CurrentResultObservation:
        self._bind()
        current = asyncio.current_task()
        if current is not None and current.cancelling():
            raise asyncio.CancelledError
        _need(type(command) is EndCommand)
        original = EndCommand(
            command.owner_epoch, command.generation, command.original_start_command_id
        )
        record = self._current
        _need(
            record is not None
            and original == EndCommand(self._epoch, record.generation, record.start.command_id),
            "conflict",
        )
        assert record is not None
        reader = record.reader
        _need(reader is not None and self._current_room(record), "closed")
        assert reader is not None
        try:
            observed = await reader.read()
            copied = parse_current_result_observation(encode_current_result_observation(observed))
            route = self._route
            _need(
                (
                    copied.profile_id,
                    copied.scope.tenant_id,
                    copied.scope.account_id,
                    copied.case_id,
                    copied.conversation_id,
                )
                == (
                    route.profile_id,
                    route.account_scope.tenant_id,
                    route.account_scope.account_id,
                    route.case_id,
                    route.conversation_id,
                ),
                "unavailable",
            )
            _need(self._current_room(record), "closed")
            return copied
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - finite application boundary; preserve actual owners and private errors
            raise _finite(error) from None

    async def close(self) -> None:
        self._bind()
        self._closing = True
        record = self._current
        if record is not None:
            await self._observe_end(record)
        _need(not self._recovery_required, "recovery_required")
