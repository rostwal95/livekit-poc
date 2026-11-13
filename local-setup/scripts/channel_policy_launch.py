"""Explicit joined scripted demo launcher; imports and --plan perform no I/O.

Uses an existing prepared profile. Schema/SMS preparation is a separate owner
operation. Incomplete stop retains the original owners and private active marker;
a repeated signal retries that same cleanup, never replaces the activation.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import inspect
import json
import os
import signal
import stat
import sys
from collections.abc import Callable, Coroutine, Mapping, Sequence
from dataclasses import dataclass, field, fields
from pathlib import Path, PosixPath
from types import MappingProxyType, ModuleType
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypeVar, cast
from uuid import uuid4

if TYPE_CHECKING:
    from services.channel_policy_demo._bounded_loopback_http import Endpoint
    from services.channel_policy_demo.native_room_admin import LiveKitAdminSettings
    from services.channel_policy_demo.native_room_state import NodeRoomCursor
    from services.channel_policy_demo.owner_config import OwnerProfile
    from services.channel_policy_demo.parent import ParentSettings

Code = Literal[
    "invalid_arguments",
    "invalid_configuration",
    "already_active",
    "unavailable",
    "closed",
    "cleanup_incomplete",
]
_CODES = frozenset(
    {
        "invalid_arguments",
        "invalid_configuration",
        "already_active",
        "unavailable",
        "closed",
        "cleanup_incomplete",
    }
)
BASE = frozenset({"PATH", "LANG", "CI", "NO_COLOR", "__CF_USER_TEXT_ENCODING"})
T = TypeVar("T")
STARTUP_SECONDS, SHUTDOWN_SECONDS = 60.0, 60.0
PRIVATE_BYTES = 32768


class LaunchError(RuntimeError):
    def __init__(self, code: Code = "unavailable") -> None:
        self.code: Code = code if type(code) is str and code in _CODES else "unavailable"
        super().__init__(self.code)


def need(value: bool, code: Code = "invalid_configuration") -> None:
    if not value:
        raise LaunchError(code)


def finite(error: BaseException, fallback: Code = "unavailable") -> LaunchError:
    try:
        value = inspect.getattr_static(error, "code", None)
        return LaunchError(
            cast(Code, value) if type(value) is str and value in _CODES else fallback
        )
    except Exception:  # noqa: BLE001 - no dependency getters/arguments in diagnostics
        return LaunchError(fallback)


def task(action: Coroutine[Any, Any, T], *, cleanup: bool = False) -> asyncio.Task[T]:
    try:
        result = asyncio.create_task(action, eager_start=False)
    except BaseException as error:
        action.close()
        if isinstance(error, Exception):
            raise LaunchError("cleanup_incomplete" if cleanup else "unavailable") from None
        raise
    result.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    return result


def encode(value: object) -> bytes:
    try:
        raw = (
            json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
        ).encode("utf-8", "strict")
        need(0 < len(raw) <= PRIVATE_BYTES)
        return raw
    except Exception:  # noqa: BLE001 - no private file bytes in errors
        raise LaunchError("invalid_configuration") from None


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        need(key not in result)
        result[key] = value
    return result


def _constant(_: str) -> object:
    raise LaunchError("invalid_configuration")


def decode(raw: bytes) -> object:
    try:
        return json.loads(
            raw.decode("utf-8", "strict"), object_pairs_hook=_pairs, parse_constant=_constant
        )
    except Exception:  # noqa: BLE001 - no malformed private bytes in diagnostics
        raise LaunchError("invalid_configuration") from None


def _signature(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def private_directory(path: Path, *, create: bool = False) -> None:
    if create:
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
    value = path.lstat()
    need(
        stat.S_ISDIR(value.st_mode)
        and stat.S_IMODE(value.st_mode) == 0o700
        and value.st_uid == os.getuid()
        and path.resolve(strict=True) == path
    )


def read_private(path: Path, *, limit: int = PRIVATE_BYTES) -> tuple[bytes, tuple[int, ...]]:
    need(type(limit) is int and 1 <= limit <= 262144)
    private_directory(path.parent)
    before = path.lstat()
    need(
        stat.S_ISREG(before.st_mode)
        and stat.S_IMODE(before.st_mode) == 0o600
        and before.st_uid == os.getuid()
        and before.st_nlink == 1
        and 0 < before.st_size <= limit
    )
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        opened = os.fstat(descriptor)
        need(_signature(before) == _signature(opened))
        raw = os.read(descriptor, limit + 1)
        need(not os.read(descriptor, 1) and len(raw) == before.st_size)
        need(_signature(before) == _signature(os.fstat(descriptor)) == _signature(path.lstat()))
        return raw, _signature(before)
    finally:
        os.close(descriptor)


def publish(path: Path, raw: bytes) -> tuple[int, ...]:
    """Write/fsync before exclusive final visibility; remove only owned pending."""
    need(0 < len(raw) <= PRIVATE_BYTES)
    private_directory(path.parent)
    pending = path.with_name(".pending-" + uuid4().hex)
    descriptor: int | None = None
    created = False
    try:
        descriptor = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        created = True
        remaining = memoryview(raw)
        while remaining:
            size = os.write(descriptor, remaining)
            need(size > 0)
            remaining = remaining[size:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.link(pending, path, follow_symlinks=False)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if created:
            pending.unlink()
    saved, signature = read_private(path)
    need(saved == raw)
    return signature


def immutable(path: Path, value: object) -> tuple[int, ...]:
    raw = encode(value)
    if path.exists() or path.is_symlink():
        saved, signature = read_private(path)
        need(decode(saved) == value)
        return signature
    return publish(path, raw)


@dataclass(frozen=True, slots=True)
class LaunchRequest:
    repository: Path
    profile_path: Path = field(repr=False)
    node: Path
    base_environment: Mapping[str, str] = field(repr=False)
    no_ui: bool = False
    inference_mode: Literal["scripted", "provider_real"] = "scripted"

    def __post_init__(self) -> None:
        need(
            type(self.inference_mode) is str
            and self.inference_mode in ("scripted", "provider_real")
        )
        for path in (self.repository, self.profile_path, self.node):
            need(type(path) is PosixPath and path.is_absolute())
        need(type(self.no_ui) is bool and isinstance(self.base_environment, Mapping))
        need(
            not set(self.base_environment) - BASE and {"PATH", "LANG"} <= set(self.base_environment)
        )
        copied: dict[str, str] = {}
        for key, value in self.base_environment.items():
            need(
                type(key) is str
                and type(value) is str
                and 0 < len(value.encode("utf-8", "strict")) <= 4096
                and "\0" not in value
            )
            copied[key] = value
        object.__setattr__(self, "base_environment", MappingProxyType(copied))


@dataclass(frozen=True, slots=True)
class PreparedLaunch:
    profile: OwnerProfile = field(repr=False)
    admin: LiveKitAdminSettings = field(repr=False)
    operator_bearer: str = field(repr=False)
    launch_id: str
    runtime: Path
    sources: Mapping[str, str]
    active_bytes: bytes = field(repr=False)
    active_signature: tuple[int, ...] = field(repr=False)
    provider_environment: Mapping[str, str] | None = field(default=None, repr=False)

    @property
    def operator_file(self) -> Path:
        return self.runtime / "operator.json"

    def finish(self) -> None:
        saved, signature = read_private(self.runtime / "active.json")
        need(
            saved == self.active_bytes and signature == self.active_signature, "cleanup_incomplete"
        )
        (self.runtime / "active.json").unlink()


class ParentPort(Protocol):
    async def start_sources(self) -> None: ...
    async def start(self, cursor: NodeRoomCursor) -> Endpoint: ...
    async def close(self) -> None: ...


class ChildPort(Protocol):
    async def start(self) -> None: ...
    async def wait_ready(self, deadline: float) -> dict[str, object]: ...
    async def wait_terminal(self) -> None: ...
    async def close(self) -> None: ...
    def facts(self) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class LaunchFactories:
    prepare: Callable[[LaunchRequest], PreparedLaunch]
    parent: Callable[[ParentSettings], ParentPort]
    child: Callable[[object], ChildPort]


def helper() -> ModuleType:
    """Fixed adjacent module only; no checkout/CWD/PYTHONPATH fallback."""
    path = Path(__file__).with_name("channel_policy_launch_child.py")
    name = "_channel_policy_launch_child"
    prior = sys.modules.get(name)
    if prior is not None:
        need(getattr(prior, "__file__", None) == str(path))
        return prior
    spec = importlib.util.spec_from_file_location(name, path)
    need(spec is not None and spec.loader is not None)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        if sys.modules.get(name) is module:
            del sys.modules[name]
        raise
    return module


def stack_settings(repository: Path) -> dict[str, str]:
    """Only maintained three-file loader; serving never imports owner DDL tools."""
    path = repository / "local-setup/stack.py"
    spec = importlib.util.spec_from_file_location("_channel_policy_launch_stack", path)
    need(spec is not None and spec.loader is not None)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        result = module.load_settings(repository / "local-setup")
        need(type(result) is dict)
        return cast(dict[str, str], result)
    finally:
        if sys.modules.get(spec.name) is module:
            del sys.modules[spec.name]


def provider_credentials(repository: Path) -> dict[str, str]:
    """Explicit provider_real only: the strict owner-only loader, values never echoed."""
    path = repository / "local-setup/provider_config.py"
    spec = importlib.util.spec_from_file_location("_channel_policy_launch_provider", path)
    need(spec is not None and spec.loader is not None)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        loaded = module.read_credentials(repository / "local-setup/.env.providers")
        result = loaded.environment()
        need(type(result) is dict and len(result) == 3)
        return cast(dict[str, str], result)
    finally:
        if sys.modules.get(spec.name) is module:
            del sys.modules[spec.name]


def source_bindings(request: LaunchRequest) -> dict[str, str]:
    paths = [
        "services/channel-policy-gateway/dist/specialist-serve.js",
        "services/channel-policy-gateway/dist/serve.js",
        "services/channel_policy_demo/parent.py",
        "local-setup/scripts/channel_policy_launch.py",
        "local-setup/scripts/channel_policy_launch_child.py",
    ]
    if not request.no_ui:
        paths += [
            "apps/local-console/vite.channel-policy.config.ts",
            "apps/local-console/dist-channel-policy/channel-policy.html",
        ]
    result: dict[str, str] = {}
    for relative in paths:
        path = request.repository / relative
        before = path.lstat()
        need(
            stat.S_ISREG(before.st_mode)
            and 0 < before.st_size <= 1048576
            and path.resolve(strict=True) == path
        )
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            need(_signature(before) == _signature(os.fstat(descriptor)))
            raw = bytearray()
            while piece := os.read(descriptor, 65536):
                raw.extend(piece)
                need(len(raw) <= 1048576)
            need(
                len(raw) == before.st_size
                and _signature(before)
                == _signature(os.fstat(descriptor))
                == _signature(path.lstat())
            )
        finally:
            os.close(descriptor)
        result[relative] = hashlib.sha256(raw).hexdigest()
    return result


def prepare(request: LaunchRequest) -> PreparedLaunch:
    """Off conversational loop. Publishes active marker only after all validation."""
    import secrets

    from services.channel_policy_demo.native_room_admin import LiveKitAdminSettings
    from services.channel_policy_demo.owner_config import read_owner_profile
    from services.channel_policy_demo.room_control import RoomPublisherCredential

    try:
        need(request.repository.resolve(strict=True) == request.repository)
        info = request.node.stat()
        need(stat.S_ISREG(info.st_mode) and bool(info.st_mode & 0o111))
        python = request.repository / ".venv/bin/python"
        need(python.is_file() and os.access(python, os.X_OK))
        profile = read_owner_profile(request.profile_path)
        settings = stack_settings(request.repository)
        port = settings["LIVEKIT_HTTP_PORT"]
        need(
            type(port) is str
            and port.isascii()
            and port.isdecimal()
            and str(int(port)) == port
            and 1 <= int(port) <= 65535
        )
        admin = LiveKitAdminSettings(
            settings["LIVEKIT_API_KEY"], settings["LIVEKIT_API_SECRET"], "http://127.0.0.1:" + port
        )
        private_directory(request.profile_path.parent)
        runtime = request.profile_path.parent / ".runtime"
        private_directory(runtime, create=True)
        need(
            not (runtime / "active.json").exists() and not (runtime / "active.json").is_symlink(),
            "already_active",
        )
        for filename, expected in (
            ("node-config.json", profile.node_configuration()),
            ("specialist-config.json", profile.specialist_configuration()),
        ):
            raw, _ = read_private(
                request.profile_path.with_name(filename),
                limit=262144 if filename == "specialist-config.json" else PRIVATE_BYTES,
            )
            need(decode(raw) == expected)
        bindings = source_bindings(request)
        key_path = runtime / "operator.json"
        if key_path.exists() or key_path.is_symlink():
            raw, _ = read_private(key_path)
            value = decode(raw)
            need(type(value) is dict and set(value) == {"schemaVersion", "profileId", "bearer"})
            data = cast(dict[str, object], value)
            need(
                type(data["schemaVersion"]) is int
                and data["schemaVersion"] == 1
                and data["profileId"] == profile.route.profile_id
            )
            bearer = cast(str, data["bearer"])
            RoomPublisherCredential(bearer)
        else:
            bearer = secrets.token_urlsafe(32)
            publish(
                key_path,
                encode(
                    {"schemaVersion": 1, "profileId": profile.route.profile_id, "bearer": bearer}
                ),
            )
        credentials = {
            getattr(profile.credentials, item.name) for item in fields(profile.credentials)
        }
        need(bearer not in credentials | {admin.api_key, admin.api_secret})
        immutable(
            runtime / "room-control.json",
            {"schemaVersion": 1, "port": 11029, "recoverBindingId": None},
        )
        immutable(
            runtime / "native-bridge.json",
            {
                "schemaVersion": 1,
                "prepareEndpoint": {"host": "127.0.0.1", "port": 11030},
                "rehydrationPort": 11032,
            },
        )
        keys = (
            provider_credentials(request.repository)
            if request.inference_mode == "provider_real"
            else None
        )
        launch_id = str(uuid4())
        active = encode(
            {
                "schemaVersion": 1,
                "profileId": profile.route.profile_id,
                "launchId": launch_id,
                "pid": os.getpid(),
                "sourceBindings": bindings,
            }
        )
        signature = publish(runtime / "active.json", active)
        return PreparedLaunch(
            profile,
            admin,
            bearer,
            launch_id,
            runtime,
            MappingProxyType(bindings),
            active,
            signature,
            None if keys is None else MappingProxyType(keys),
        )
    except LaunchError:
        raise
    except Exception:  # noqa: BLE001 - stack/private values never leave startup boundary
        raise LaunchError("invalid_configuration") from None


def default_factories() -> LaunchFactories:
    from services.channel_policy_demo.parent import ChannelPolicyParent

    child = helper()
    return LaunchFactories(
        prepare, ChannelPolicyParent, cast(Callable[[object], ChildPort], child.RoleChild)
    )


class JoinedLauncher:
    """At most three role children and one Parent; original startup/drain retained."""

    def __init__(self, request: LaunchRequest, *, factories: LaunchFactories | None = None) -> None:
        need(type(request) is LaunchRequest)
        need(factories is None or type(factories) is LaunchFactories)
        self.request = request
        self._factories = factories
        self._prepared: PreparedLaunch | None = None
        self._parent: ParentPort | None = None
        self._children: dict[str, ChildPort] = {}
        self._operations: set[asyncio.Task[Any]] = set()
        self._startup: asyncio.Task[None] | None = None
        self._cleanup: asyncio.Task[None] | None = None
        self._parent_cleanup: asyncio.Task[None] | None = None
        self._ui_cleanup: asyncio.Task[None] | None = None
        self._deadline: float | None = None
        self._closing = self._closed = self._ready = False
        self._watches: dict[str, asyncio.Task[None]] = {}

    def _check(self, deadline: float) -> None:
        current = asyncio.current_task()
        if current is not None and current.cancelling():
            raise asyncio.CancelledError
        need(not self._closing, "closed")
        need(not any(watch.done() for watch in self._watches.values()), "unavailable")
        need(asyncio.get_running_loop().time() < deadline, "unavailable")

    async def _stage(self, action: Coroutine[Any, Any, T], deadline: float) -> T:
        try:
            self._check(deadline)
        except BaseException:
            action.close()
            raise
        actual = task(action)
        self._operations.add(actual)
        actual.add_done_callback(self._operations.discard)
        async with asyncio.timeout_at(deadline):
            return await asyncio.shield(actual)

    async def _prepare(self) -> PreparedLaunch:
        assert self._factories is not None
        result = await asyncio.to_thread(self._factories.prepare, self.request)
        need(type(result) is PreparedLaunch)
        self._prepared = result
        return result

    async def _role(self, role: str, deadline: float) -> dict[str, object]:
        assert self._prepared is not None and self._factories is not None
        p, runtime = self._prepared.profile, self._prepared.runtime
        environment = dict(self.request.base_environment)
        if role == "gateway":
            environment.update(p.credentials.node_environment())
        if role == "specialist":
            environment["P3_DEMO_SPECIALIST_BEARER"] = p.credentials.specialist_bearer
        self._check(deadline)
        module = helper()
        spec = module.ChildSpec(
            role,
            self.request.repository,
            self.request.node,
            p.route.profile_id,
            {
                key: getattr(p.ports, key)
                for key in ("native", "sms", "read", "receiver", "specialist")
            },
            environment,
            self.request.profile_path.with_name(
                "node-config.json" if role == "gateway" else "specialist-config.json"
            )
            if role != "ui"
            else None,
            runtime / "room-control.json" if role == "gateway" else None,
            runtime / "native-bridge.json" if role == "gateway" else None,
        )
        owner = self._factories.child(spec)
        need(
            all(owner is not old for old in self._children.values())
            and cast(object, owner) is not self._parent
        )
        self._children[role] = owner
        self._check(deadline)
        role_deadline = min(deadline, asyncio.get_running_loop().time() + 15)
        await self._stage(owner.start(), role_deadline)
        value = await self._stage(owner.wait_ready(role_deadline), role_deadline)
        self._check(deadline)
        self._watches[role] = task(owner.wait_terminal())
        return value

    async def _open(self, deadline: float) -> None:
        from services.channel_policy_demo.native_room_state import NodeRoomCursor
        from services.channel_policy_demo.parent import ParentSettings

        self._check(deadline)
        if self._factories is None:
            self._factories = default_factories()
        prepared = await self._stage(self._prepare(), deadline)
        self._check(deadline)
        settings = ParentSettings(
            prepared.profile,
            prepared.admin,
            prepared.operator_bearer,
            prepared.launch_id,
            prepared.runtime / "rooms",
            self.request.repository / ".venv/bin/python",
            self.request.base_environment,
            self.request.inference_mode,
            prepared.provider_environment,
        )
        self._parent = self._factories.parent(settings)
        self._check(deadline)
        await self._stage(self._parent.start_sources(), deadline)
        self._check(deadline)
        await self._role("specialist", deadline)
        frame = await self._role("gateway", deadline)
        cursor = cast(dict[str, object], frame["roomControl"])
        observed = NodeRoomCursor(
            cast(str, cursor["nodeEpoch"]),
            cast(str, cursor["generation"]),
            cast(bool, cursor["recoveryRequired"]),
            11029,
        )
        endpoint = await self._stage(self._parent.start(observed), deadline)
        need(endpoint.host == "127.0.0.1" and endpoint.port == 11033, "unavailable")
        self._check(deadline)
        if not self.request.no_ui:
            await self._role("ui", deadline)
        self._check(deadline)
        need(not any(watch.done() for watch in self._watches.values()), "unavailable")
        self._ready = True

    async def start(self) -> None:
        current = asyncio.current_task()
        if current is not None and current.cancelling():
            raise asyncio.CancelledError
        need(not self._closing, "closed")
        if self._startup is None:
            deadline = asyncio.get_running_loop().time() + STARTUP_SECONDS
            self._startup = task(self._open(deadline))
        try:
            await asyncio.shield(self._startup)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - finite serving startup
            raise finite(error) from None

    async def wait_terminal(self) -> None:
        need(self._ready and bool(self._watches), "unavailable")
        await asyncio.wait(self._watches.values(), return_when=asyncio.FIRST_COMPLETED)

    def status(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "status": "closed"
            if self._closed
            else "closing"
            if self._closing
            else "ready"
            if self._ready
            else "starting",
            "mode": self.request.inference_mode,
            "uiUrl": None if self.request.no_ui else "http://127.0.0.1:5179/channel-policy.html",
            "operatorKeyFile": str(self._prepared.operator_file)
            if self._prepared is not None
            else None,
            "children": [owner.facts() for owner in self._children.values()],
        }

    def _front_cleanup(self) -> None:
        # Start both admission fences without awaiting either slow owner. Keep
        # independent observers so a failed allocation cannot discard the other.
        allocation_failed = False
        for name, owner in (
            ("_ui_cleanup", self._children.get("ui")),
            ("_parent_cleanup", self._parent),
        ):
            if owner is None:
                continue
            prior = cast(asyncio.Task[None] | None, getattr(self, name))
            if (
                prior is None
                or prior.done()
                and (prior.cancelled() or prior.exception() is not None)
            ):
                try:
                    setattr(self, name, task(owner.close(), cleanup=True))
                except Exception:  # noqa: BLE001 - independently retain both front owners
                    allocation_failed = True
        need(not allocation_failed, "cleanup_incomplete")

    async def _drain(self) -> None:
        self._front_cleanup()
        if self._startup is not None:
            await asyncio.gather(asyncio.shield(self._startup), return_exceptions=True)
        if self._operations:
            await asyncio.gather(
                *(asyncio.shield(value) for value in tuple(self._operations)),
                return_exceptions=True,
            )
        # A public factory can reenter close before its returned UI/Parent is
        # adopted. Startup is now settled, so catch every such late owner.
        self._front_cleanup()
        front = tuple(
            value for value in (self._ui_cleanup, self._parent_cleanup) if value is not None
        )
        if front:
            await asyncio.gather(
                *(asyncio.shield(value) for value in front), return_exceptions=True
            )
            need(
                all(not value.cancelled() and value.exception() is None for value in front),
                "cleanup_incomplete",
            )
        for role in ("gateway", "specialist"):
            if role in self._children:
                await self._children[role].close()
        if self._watches:
            await asyncio.gather(*self._watches.values(), return_exceptions=True)
        if self._prepared is not None:
            await asyncio.to_thread(self._prepared.finish)
        self._closed = True

    async def close(self) -> None:
        self._closing, self._ready = True, False
        if self._closed:
            return
        if self._deadline is None:
            self._deadline = asyncio.get_running_loop().time() + SHUTDOWN_SECONDS
        if (
            self._cleanup is None
            or self._cleanup.done()
            and (self._cleanup.cancelled() or self._cleanup.exception() is not None)
        ):
            self._cleanup = task(self._drain(), cleanup=True)
        try:
            if self._cleanup.done():
                await asyncio.shield(self._cleanup)
            else:
                async with asyncio.timeout_at(self._deadline):
                    await asyncio.shield(self._cleanup)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - original owners remain reachable
            raise LaunchError("cleanup_incomplete") from None


def plan() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "status": "planned",
        "mode": "scripted",
        "optionalModes": ["provider_real"],
        "preparedProfileRequired": True,
        "servingDDL": False,
        "providerFiles": False,
        "providerCalls": False,
        "providerReal": "explicit --provider; keys from local-setup/.env.providers reach only "
        "the native worker",
        "childrenMaximum": 3,
        "startupSeconds": 60,
        "roleReadySeconds": 15,
        "shutdownSeconds": 60,
        "stdoutBytesPerRole": 262144,
        "stderrBytesPerRole": 1048576,
        "ui": "prebuilt_preview",
        "uiPort": 5179,
        "operatorPort": 11033,
        "shutdownOrder": ["ui", "parent", "gateway", "specialist"],
    }


def emit(value: object) -> None:
    try:
        sys.stdout.write(json.dumps(value, separators=(",", ":"), allow_nan=False) + "\n")
        sys.stdout.flush()
    except Exception:  # noqa: BLE001, S110 - output failure cannot erase owned resources
        pass


async def serve(request: LaunchRequest) -> int:
    launcher = JoinedLauncher(request)
    loop = asyncio.get_running_loop()
    stopped = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stopped.set)
    startup = task(launcher.start())
    stopping = task(stopped.wait())
    terminal: asyncio.Task[None] | None = None
    failed = False
    try:
        await asyncio.wait((startup, stopping), return_when=asyncio.FIRST_COMPLETED)
        if not stopped.is_set():
            await startup
            emit(launcher.status())
            terminal = task(launcher.wait_terminal())
            await asyncio.wait((terminal, stopping), return_when=asyncio.FIRST_COMPLETED)
            if not stopped.is_set():
                failed = True
    except asyncio.CancelledError:
        failed = True
    except Exception:  # noqa: BLE001 - all configuration/child failures are finite
        failed = True
        emit({"schemaVersion": 1, "status": "unavailable", "code": "unavailable"})
    finally:
        # Repeated SIGTERM/INT retries this same retained cleanup. Once an actual
        # cleanup settles successfully after the observer, observe it and exit.
        while True:
            stopped.clear()
            try:
                await launcher.close()
                break
            except asyncio.CancelledError:
                continue
            except Exception:  # noqa: BLE001 - no forced exit over incomplete owners
                emit({"schemaVersion": 1, "status": "closing", "code": "cleanup_incomplete"})
                retry = task(stopped.wait())
                actual = launcher._cleanup
                waiters = (retry,) if actual is None or actual.done() else (retry, actual)
                await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
                retry.cancel()
                await asyncio.gather(retry, return_exceptions=True)
        for observer in (stopping, terminal):
            if observer is not None:
                observer.cancel()
        await asyncio.gather(
            *(value for value in (stopping, terminal, startup) if value is not None),
            return_exceptions=True,
        )
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(sig)
    final_state = launcher.status()
    emit(final_state)
    children = cast(list[dict[str, object]], final_state["children"])
    graceful = all(child.get("gracefulClosed") is True for child in children)
    return 1 if failed or not graceful else 0


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--plan"]:
        emit(plan())
        return 0
    try:
        flags = args[5:]
        need(
            len(args) >= 5
            and args[0] == "serve"
            and args[1] == "--profile"
            and args[3] == "--node"
            and len(set(flags)) == len(flags)
            and set(flags) <= {"--no-ui", "--provider"},
            "invalid_arguments",
        )
        repository = Path(__file__).resolve(strict=True).parents[2]
        environment = {key: value for key, value in os.environ.items() if key in BASE}
        request = LaunchRequest(
            repository,
            Path(args[2]),
            Path(args[4]),
            environment,
            "--no-ui" in flags,
            "provider_real" if "--provider" in flags else "scripted",
        )
        return asyncio.run(serve(request))
    except KeyboardInterrupt:
        return 1
    except Exception as error:  # noqa: BLE001 - no raw argv, credentials or dependency diagnostics
        emit(
            {
                "schemaVersion": 1,
                "status": "unavailable",
                "code": finite(error, "invalid_arguments").code,
            }
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
