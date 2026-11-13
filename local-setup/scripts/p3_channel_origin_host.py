"""Test-only real-public-P1 origin fixture; the parent owns schemas and processes.

Serving performs no DDL or inference. Fixed private hooks observe a real public
work call without granting input-selected authority. Startup and close observers
retain actual owners; HTTP drains before service/Core and the shared case reader.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import math
import os
import re
import signal
import stat
import sys
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, TypeVar, cast

from continuity_lab.postgres_api import AuthenticatedActor, ManagedCaseClient, open_postgres_client
from continuity_lab.work_api import (
    BearerToken,
    PostgresSettings,
    TaskExecutionPort,
    WorkCancellation,
    WorkClient,
    WorkDirectory,
    WorkError,
    WorkPayload,
    WorkPrincipal,
    WorkRecord,
    WorkScope,
    WorkSubmission,
    open_work_client,
)
from delegation_reliability import CaseBinding, ChannelPolicyCoordinator, ManagedCaseAuthority
from delegation_reliability.contracts import Scope, canonical, identifier
from delegation_reliability.fixed_policy_contracts import (
    FixedPolicyRequest,
    parse_fixed_policy_request,
)


def _application_helpers() -> None:
    """Load only fixed adjacent application modules under isolated Python too.

    This never adds a checkout package path: public P1/P3 products still resolve
    through the selected interpreter. Existing modules must be this exact source.
    """
    for name in ("p2_channel_origin_wire", "p3_channel_origin", "p3_channel_origin_http"):
        path = Path(__file__).resolve().with_name(name + ".py")
        existing = sys.modules.get(name)
        if existing is not None:
            if existing.__file__ is None or Path(existing.__file__).resolve() != path:
                raise RuntimeError("invalid_application_helper")
            continue
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError("invalid_application_helper")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:  # noqa: BLE001 - never expose an unexpected application import message
            sys.modules.pop(name, None)
            raise RuntimeError("invalid_application_helper") from None


_application_helpers()

from p2_channel_origin_wire import channel_identifier, uuid_value
from p3_channel_origin import ChannelOriginBinding, ChannelOriginService
from p3_channel_origin_http import ChannelOriginHttp

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
Role = Literal["origin-race-a", "origin-race-b", "origin-ack", "origin-recovered", "origin-current"]
ROLES: tuple[Role, ...] = (
    "origin-race-a",
    "origin-race-b",
    "origin-ack",
    "origin-recovered",
    "origin-current",
)
BASE = frozenset({"PATH", "LANG", "CI", "NO_COLOR", "__CF_USER_TEXT_ENCODING"})
ENVIRONMENT = frozenset(
    {
        "P3_ORIGIN_DIRECTORY",
        "P3_ORIGIN_PG_PORT",
        "P3_ORIGIN_RUNTIME_PASSWORD",
        "P3_ORIGIN_WORK_TOKEN",
        "P3_ORIGIN_CASE_TOKEN",
        "P3_ORIGIN_OPERATION_TOKEN",
    }
)
_CONFIG_FIELDS = {
    "schema_version",
    "profile_id",
    "scope",
    "case_id",
    "conversation_id",
    "sender_id",
    "task_id",
    "authority_case_id",
    "case_schema",
    "work_schema",
    "supplier_path",
    "template",
    "deadline_window_ms",
    "operation_key",
    "parent_deadline_monotonic",
}
HostCode = Literal[
    "invalid_configuration",
    "invalid_control",
    "startup_failed",
    "deadline_exceeded",
    "cleanup_incomplete",
    "closed",
    "internal_error",
]


class OriginHostError(RuntimeError):
    def __init__(self, code: HostCode) -> None:
        self.code = (
            code
            if type(code) is str
            and code
            in {
                "invalid_configuration",
                "invalid_control",
                "startup_failed",
                "deadline_exceeded",
                "cleanup_incomplete",
                "closed",
                "internal_error",
            }
            else "internal_error"
        )
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class RuntimeEnvironment:
    directory: Path
    pg_port: int
    runtime_password: str = field(repr=False)
    work_token: str = field(repr=False)
    case_token: str = field(repr=False)
    operation_token: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class OriginHostConfig:
    role: Role
    profile_id: str
    scope: Scope
    case_id: str
    conversation_id: str
    sender_id: str
    task_id: str
    authority_case_id: str
    case_schema: str
    work_schema: str
    supplier_path: Path
    template: FixedPolicyRequest = field(repr=False)
    deadline_window_ms: int
    operation_key: str | None
    parent_deadline_monotonic: float

    @property
    def business_deadline(self) -> float:
        """Preserve the final twenty seconds for retained-owner cleanup only."""
        return self.parent_deadline_monotonic - 20


def _fields(value: object, names: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != names:
        raise OriginHostError("invalid_configuration")
    return cast(dict[str, object], value)


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in items:
        if key in out:
            raise OriginHostError("invalid_configuration")
        out[key] = value
    return out


def _invalid_constant(_: str) -> object:
    raise OriginHostError("invalid_configuration")


def _read(path: Path, maximum: int = 32768) -> dict[str, object]:
    try:
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or path.is_symlink()
            or not 0 < info.st_size <= maximum
        ):
            raise OriginHostError("invalid_configuration")
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
            raw = stream.read(maximum + 1)
            after = os.fstat(stream.fileno())
        if (info.st_dev, info.st_ino, info.st_size) != (after.st_dev, after.st_ino, len(raw)):
            raise OriginHostError("invalid_configuration")
        value: object = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_invalid_constant
        )
        if type(value) is not dict:
            raise OriginHostError("invalid_configuration")
        return cast(dict[str, object], value)
    except (OSError, ValueError, UnicodeError, RecursionError):
        raise OriginHostError("invalid_configuration") from None


def _private_directory(path: Path) -> None:
    try:
        info = path.lstat()
        if (
            not path.is_absolute()
            or path.resolve() != path
            or path.is_symlink()
            or not stat.S_ISDIR(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o700
            or info.st_uid != os.getuid()
        ):
            raise OriginHostError("invalid_configuration")
    except OSError:
        raise OriginHostError("invalid_configuration") from None


def configuration(
    role: str, environment: Mapping[str, str] | None = None
) -> tuple[RuntimeEnvironment, OriginHostConfig]:
    """Validate/copy fixed private configuration before any public port factory."""
    try:
        supplied = os.environ if environment is None else environment
        required = (BASE - {"__CF_USER_TEXT_ENCODING"}) | ENVIRONMENT
        if role not in ROLES or not required <= set(supplied) <= BASE | ENVIRONMENT:
            raise OriginHostError("invalid_configuration")
        values = {key: supplied[key] for key in set(supplied)}
        if any(type(v) is not str or not v or "\0" in v for v in values.values()):
            raise OriginHostError("invalid_configuration")
        if values["CI"] != "1" or values["NO_COLOR"] != "1":
            raise OriginHostError("invalid_configuration")
        if (
            len(values["PATH"]) > 8192
            or len(values["LANG"]) > 64
            or len(values.get("__CF_USER_TEXT_ENCODING", "")) > 64
        ):
            raise OriginHostError("invalid_configuration")
        directory = Path(values["P3_ORIGIN_DIRECTORY"])
        _private_directory(directory)
        port = values["P3_ORIGIN_PG_PORT"]
        if re.fullmatch(r"[1-9][0-9]{0,4}", port) is None or int(port) > 65535:
            raise OriginHostError("invalid_configuration")
        tokens = tuple(
            values["P3_ORIGIN_" + key + "_TOKEN"] for key in ("WORK", "CASE", "OPERATION")
        )
        if len(set(tokens)) != 3 or any(
            re.fullmatch(r"[A-Za-z0-9_-]{43}", token) is None for token in tokens
        ):
            raise OriginHostError("invalid_configuration")
        password = values["P3_ORIGIN_RUNTIME_PASSWORD"]
        if len(password) > 128 or any(c in password for c in "\r\n"):
            raise OriginHostError("invalid_configuration")
        runtime = RuntimeEnvironment(directory, int(port), password, *tokens)
        value = _fields(_read(directory / (role + "-config.json")), _CONFIG_FIELDS)
        if type(value["schema_version"]) is not int or value["schema_version"] != 1:
            raise OriginHostError("invalid_configuration")
        scope = _fields(value["scope"], {"tenant_id", "account_id"})
        bound_scope = Scope(identifier(scope["tenant_id"]), identifier(scope["account_id"]))
        case_id, conversation_id = (
            identifier(value["case_id"]),
            identifier(value["conversation_id"]),
        )
        case_schema, work_schema = value["case_schema"], value["work_schema"]
        if (
            type(case_schema) is not str
            or re.fullmatch(r"p3_completion_[0-9a-f]{32}", case_schema) is None
            or type(work_schema) is not str
            or re.fullmatch(r"p1_work_origin_[0-9a-f]{32}", work_schema) is None
        ):
            raise OriginHostError("invalid_configuration")
        if type(value["supplier_path"]) is not str:
            raise OriginHostError("invalid_configuration")
        supplier = Path(value["supplier_path"])
        if supplier.parent != directory or supplier.resolve() != supplier:
            raise OriginHostError("invalid_configuration")
        supplier_info = supplier.lstat()
        if (
            not stat.S_ISREG(supplier_info.st_mode)
            or stat.S_IMODE(supplier_info.st_mode) != 0o600
            or supplier_info.st_uid != os.getuid()
            or supplier_info.st_nlink != 1
        ):
            raise OriginHostError("invalid_configuration")
        window = value["deadline_window_ms"]
        deadline = value["parent_deadline_monotonic"]
        if type(window) is not int or not 20 <= window <= 60000:
            raise OriginHostError("invalid_configuration")
        if (
            isinstance(deadline, bool)
            or not isinstance(deadline, (float, int))
            or not math.isfinite(deadline)
            or not 0 < deadline - time.monotonic() <= 180
        ):
            raise OriginHostError("invalid_configuration")
        operation = value["operation_key"]
        if role in {"origin-race-a", "origin-race-b", "origin-ack"}:
            operation = uuid_value(operation)
        elif operation is not None:
            raise OriginHostError("invalid_configuration")
        template = parse_fixed_policy_request(canonical(value["template"]))
        if (
            template.scope != bound_scope
            or template.case_id != case_id
            or template.conversation_id != conversation_id
        ):
            raise OriginHostError("invalid_configuration")
        config = OriginHostConfig(
            role,
            uuid_value(value["profile_id"]),
            bound_scope,
            case_id,
            conversation_id,
            channel_identifier(value["sender_id"]),
            uuid_value(value["task_id"]),
            uuid_value(value["authority_case_id"]),
            case_schema,
            work_schema,
            supplier,
            template,
            window,
            operation,
            float(deadline),
        )
        return runtime, config
    except OriginHostError:
        raise
    except Exception:  # noqa: BLE001 - configuration diagnostics contain no raw values
        raise OriginHostError("invalid_configuration") from None


def publish(directory: Path, filename: str, value: dict[str, object]) -> None:
    """Complete private bytes before exclusive visibility; never replace a final.

    The fixed private pending inode is the only path this publisher removes.
    Readers wait for the transient two-link publication state to settle to one.
    """
    _private_directory(directory)
    if type(filename) is not str or re.fullmatch(r"[a-z][a-z0-9-]{0,100}\.json", filename) is None:
        raise OriginHostError("invalid_control")
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise OriginHostError("invalid_control") from None
    if not 0 < len(raw) <= 8192:
        raise OriginHostError("invalid_control")
    descriptor: int | None = None
    pending: Path | None = None
    identity: tuple[int, int] | None = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix="." + filename + ".", suffix=".pending", dir=directory
        )
        pending = Path(name)
        opened = os.fstat(descriptor)
        identity = (opened.st_dev, opened.st_ino)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(pending, directory / filename, follow_symlinks=False)
    except OSError:
        raise OriginHostError("invalid_control") from None
    finally:
        try:
            if descriptor is not None:
                os.close(descriptor)
            if pending is not None:
                info = pending.lstat()
                if (
                    identity != (info.st_dev, info.st_ino)
                    or not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.getuid()
                ):
                    raise OriginHostError("invalid_control")
                pending.unlink()
        except OSError:
            raise OriginHostError("invalid_control") from None


def _control_value(path: Path) -> dict[str, object] | None:
    """Only a complete single-link parent publication is eligible for strict read."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        raise OriginHostError("invalid_control") from None
    if (
        info.st_nlink == 2
        and stat.S_ISREG(info.st_mode)
        and stat.S_IMODE(info.st_mode) == 0o600
        and info.st_uid == os.getuid()
    ):
        return None
    try:
        return _read(path, 1024)
    except OriginHostError:
        raise OriginHostError("invalid_control") from None


class FixtureControl:
    """Only fixed parent-authored files and the process signal request stop/release."""

    def __init__(self, runtime: RuntimeEnvironment, config: OriginHostConfig) -> None:
        self.directory, self.role = runtime.directory, config.role
        self.deadline = config.business_deadline
        self.stop = asyncio.Event()

    def stopped(self) -> bool:
        if self.stop.is_set():
            return True
        path = self.directory / (self.role + "-stop.json")
        value = _control_value(path)
        if value is not None:
            if (
                value != {"schema_version": 1, "stop": True}
                or value.get("stop") is not True
                or type(value["schema_version"]) is not int
            ):
                raise OriginHostError("invalid_control")
            self.stop.set()
        if time.monotonic() >= self.deadline:
            self.stop.set()
        return self.stop.is_set()

    async def wait_release(self, filename: str, *, committed: bool) -> None:
        while True:
            if self.stopped():
                if committed:
                    return
                raise WorkError("closed")
            path = self.directory / filename
            value = _control_value(path)
            if value is not None:
                if (
                    value != {"schema_version": 1, "release": True}
                    or value.get("release") is not True
                    or type(value["schema_version"]) is not int
                ):
                    raise OriginHostError("invalid_control")
                return
            await asyncio.sleep(min(0.01, max(0, self.deadline - time.monotonic())))


class _WorkPort(TaskExecutionPort, Protocol):
    @property
    def pending_count(self) -> int: ...


class HookedTaskExecutionPort:
    """Test-only barriers around one unchanged credential-bound public P1 port."""

    def __init__(self, inner: _WorkPort, config: OriginHostConfig, control: FixtureControl) -> None:
        self._inner, self._config, self._control = inner, config, control
        self._key = (
            None if config.operation_key is None else "p2_" + config.operation_key.replace("-", "")
        )
        self._ordinal = 0
        self._submits = 0
        self._submit_observed = False

    @property
    def scope(self) -> WorkScope:
        return self._inner.scope

    @property
    def pending_count(self) -> int:
        return self._inner.pending_count

    @property
    def matching_find_count(self) -> int:
        return self._ordinal

    @property
    def submit_count(self) -> int:
        return self._submits

    async def find(self, *, idempotency_key: str) -> WorkRecord | None:
        if idempotency_key == self._key:
            self._ordinal += 1
            ordinal = self._ordinal
        else:
            ordinal = 0
        found = await self._inner.find(idempotency_key=idempotency_key)
        wanted = (
            2
            if self._config.role == "origin-race-a"
            else 1
            if self._config.role == "origin-race-b"
            else 0
        )
        if ordinal and ordinal == wanted:
            if found is not None:
                raise WorkError("identity_conflict")
            publish(
                self._control.directory,
                self._config.role + "-read-miss.json",
                {
                    "schema_version": 1,
                    "pid": os.getpid(),
                    "key": idempotency_key,
                    "ordinal": ordinal,
                    "found": False,
                },
            )
            await self._control.wait_release("race-release.json", committed=False)
        return found

    async def submit(self, *, idempotency_key: str, payload: WorkPayload) -> WorkSubmission:
        self._submits += 1
        matching = idempotency_key == self._key
        if matching and not self._submit_observed:
            publish(
                self._control.directory,
                self._config.role + "-submit-entered.json",
                {
                    "schema_version": 1,
                    "pid": os.getpid(),
                    "key": idempotency_key,
                },
            )
            self._submit_observed = True
        result = await self._inner.submit(idempotency_key=idempotency_key, payload=payload)
        if matching and self._config.role == "origin-ack" and result.created is True:
            publish(
                self._control.directory,
                "origin-ack-committed.json",
                {
                    "schema_version": 1,
                    "pid": os.getpid(),
                    "work_id": result.record.work_id,
                    "key": idempotency_key,
                    "payload_sha256": result.record.payload.sha256,
                    "deadline_at_ms": result.record.payload.deadline_at_ms,
                },
            )
            await self._control.wait_release("origin-ack-release.json", committed=True)
        return result

    async def get(self, *, work_id: str) -> WorkRecord:
        return await self._inner.get(work_id=work_id)

    async def cancel(self, *, work_id: str, command_id: str) -> WorkCancellation:
        return await self._inner.cancel(work_id=work_id, command_id=command_id)

    async def close(self) -> None:
        await self._inner.close()


class _Closeable(Protocol):
    async def close(self) -> None: ...


OwnerT = TypeVar("OwnerT", bound=_Closeable)


def _consume(task: asyncio.Task[object]) -> None:
    if not task.cancelled():
        task.exception()


class OwnedResources:
    """Register actual startup/close tasks before awaiting; retain incomplete tiers."""

    def __init__(self) -> None:
        self.tiers: list[list[_Closeable]] = [[], [], []]
        self.startups: set[asyncio.Task[object]] = set()
        self.close_observers: dict[int, asyncio.Task[None]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def _bind(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is not None and self._loop is not loop:
            raise OriginHostError("invalid_configuration")
        self._loop = loop

    def add(self, owner: OwnerT, tier: int) -> OwnerT:
        self.tiers[tier].append(owner)
        return owner

    async def startup(
        self,
        factory: Callable[[], OwnerT],
        tier: int,
        *,
        deadline: float | None = None,
        abort: Callable[[], bool] | None = None,
    ) -> OwnerT:
        self._bind()

        async def actual() -> OwnerT:
            if deadline is not None and time.monotonic() >= deadline:
                raise OriginHostError("deadline_exceeded")
            if abort is not None and abort():
                raise OriginHostError("closed")
            owner = await asyncio.to_thread(factory)
            return self.add(owner, tier)

        operation = actual()
        try:
            task = asyncio.create_task(operation, eager_start=False)
        except Exception:  # noqa: BLE001 - dispose only the unscheduled coroutine
            operation.close()
            raise OriginHostError("startup_failed") from None
        self.startups.add(task)
        task.add_done_callback(_consume)
        while not task.done():
            if deadline is not None and time.monotonic() >= deadline:
                raise OriginHostError("deadline_exceeded")
            if abort is not None and abort():
                raise OriginHostError("closed")
            await asyncio.wait(
                (task,),
                timeout=0.05
                if deadline is None
                else min(0.05, max(0, deadline - time.monotonic())),
            )
        try:
            return task.result()
        except asyncio.CancelledError:
            raise
        except OriginHostError:
            raise
        except Exception:  # noqa: BLE001 - private startup factory messages stay private
            raise OriginHostError("startup_failed") from None

    def transfer(self, owner: OwnerT, children: tuple[_Closeable, ...], tier: int) -> OwnerT:
        if not all(any(child is value for value in self.tiers[tier]) for child in children):
            raise OriginHostError("internal_error")
        self.tiers[tier].append(owner)
        self.tiers[tier][:] = [
            value for value in self.tiers[tier] if all(value is not child for child in children)
        ]
        return owner

    @property
    def startup_pending(self) -> int:
        return sum(not task.done() for task in self.startups)

    async def close_once(self, deadline: float, observer_seconds: float = 0.05) -> bool:
        self._bind()
        remaining = min(observer_seconds, max(0, deadline - time.monotonic()))
        if remaining <= 0:
            return False
        pending = tuple(task for task in self.startups if not task.done())
        if pending:
            _, waiting = await asyncio.wait(pending, timeout=remaining)
            if waiting:
                return False
        for tier in self.tiers:
            for owner in tuple(tier):
                remaining = min(observer_seconds, max(0, deadline - time.monotonic()))
                if remaining <= 0:
                    return False
                task = self.close_observers.get(id(owner))
                if (
                    task is None
                    or task.done()
                    and (task.cancelled() or task.exception() is not None)
                ):
                    try:
                        operation = owner.close()
                    except Exception:  # noqa: BLE001 - retain the owner if close construction fails
                        return False
                    try:
                        task = asyncio.create_task(operation, eager_start=False)
                    except Exception:  # noqa: BLE001 - close registration failure retains the owner
                        operation.close()
                        return False
                    self.close_observers[id(owner)] = task
                    task.add_done_callback(_consume)
                _, waiting = await asyncio.wait((task,), timeout=remaining)
                if waiting or task.cancelled() or task.exception() is not None:
                    return False
                tier[:] = [value for value in tier if value is not owner]
        return not self.startup_pending and not any(self.tiers)


class OriginFixtureHost:
    """Explicit local composition; never upgrades, deletes or repairs a schema."""

    def __init__(self, runtime: RuntimeEnvironment, config: OriginHostConfig) -> None:
        self.runtime, self.config = runtime, config
        self.control = FixtureControl(runtime, config)
        self.resources = OwnedResources()
        self.case_client: ManagedCaseClient | None = None
        self.work_client: WorkClient | None = None
        self.coordinator: ChannelPolicyCoordinator | None = None
        self.service: ChannelOriginService | None = None
        self.http: ChannelOriginHttp | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closing = False
        self._incomplete_published = False
        self._started = False
        self._starting = False
        self._closed = False
        self._telemetry_failed = 0

    def _bind(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is not None and self._loop is not loop:
            raise OriginHostError("invalid_configuration")
        self._loop = loop

    def _log(self, event: Literal["ready", "cleanup_incomplete", "closed"]) -> None:
        try:
            LOGGER.info("origin_fixture_host", extra={"event": event, "role": self.config.role})
        except Exception:  # noqa: BLE001 - exporter failure never changes ownership
            self._telemetry_failed += 1

    def request_stop(self) -> None:
        self.control.stop.set()

    def _admit(self) -> None:
        if time.monotonic() >= self.config.business_deadline:
            raise OriginHostError("deadline_exceeded")
        if self._closing or self.control.stopped():
            raise OriginHostError("closed")

    async def start(self) -> None:
        self._bind()
        try:
            await self._start()
        except asyncio.CancelledError:
            raise
        except OriginHostError:
            raise
        except Exception:  # noqa: BLE001 - constructor failures retain owners with fixed diagnostics
            raise OriginHostError("startup_failed") from None

    async def _start(self) -> None:
        self._bind()
        self._admit()
        if self._starting or self._started:
            raise OriginHostError("closed")
        self._starting = True
        config, runtime = self.config, self.runtime
        case_settings = PostgresSettings(
            host="127.0.0.1",
            port=runtime.pg_port,
            password=runtime.runtime_password,
            schema=config.case_schema,
        )
        work_settings = PostgresSettings(
            host="127.0.0.1",
            port=runtime.pg_port,
            password=runtime.runtime_password,
            schema=config.work_schema,
        )
        actor = AuthenticatedActor("p3_completion_user", "p3_completion_scope")
        self.case_client = await self.resources.startup(
            lambda: open_postgres_client(
                actor=actor,
                token=BearerToken(runtime.case_token),
                settings=case_settings,
                quote_database=config.supplier_path,
            ),
            2,
            deadline=config.business_deadline,
            abort=self.control.stopped,
        )
        self._admit()
        authority = ManagedCaseAuthority(
            self.case_client,
            scope=config.scope,
            bindings=(CaseBinding(config.case_id, config.task_id, config.authority_case_id),),
        )
        registrations = WorkDirectory(
            {
                BearerToken(runtime.work_token): WorkPrincipal(
                    "origin_fixture_actor",
                    WorkScope(config.scope.tenant_id, config.scope.account_id),
                )
            }
        )
        self.work_client = await self.resources.startup(
            lambda: open_work_client(
                settings=work_settings,
                directory=registrations,
                token=BearerToken(runtime.work_token),
            ),
            1,
            deadline=config.business_deadline,
            abort=self.control.stopped,
        )
        self._admit()
        hooked = HookedTaskExecutionPort(self.work_client, config, self.control)
        self.resources.transfer(hooked, (self.work_client,), 1)
        coordinator = ChannelPolicyCoordinator(
            executions=hooked, scope=config.scope, case_authority=authority, cleanup_ms=20
        )
        self.coordinator = self.resources.transfer(coordinator, (hooked,), 1)
        service = ChannelOriginService(
            binding=ChannelOriginBinding(
                config.profile_id,
                config.scope,
                config.case_id,
                config.conversation_id,
                config.sender_id,
            ),
            template=config.template,
            coordinator=coordinator,
            deadline_window_ms=config.deadline_window_ms,
        )
        self.service = self.resources.transfer(service, (coordinator,), 1)
        self._admit()
        self.http = self.resources.add(
            ChannelOriginHttp(
                service, operation_bearer=runtime.operation_token, cleanup_timeout_s=0.02
            ),
            0,
        )
        endpoint = await self.http.start()
        self._admit()
        publish(
            runtime.directory,
            config.role + "-ready.json",
            {"schema_version": 1, "pid": os.getpid(), "host": endpoint.host, "port": endpoint.port},
        )

        self._starting, self._started = False, True
        self._log("ready")

    def observation(self, *, complete: bool) -> dict[str, object]:
        http = {} if self.http is None else dict(self.http.metrics())
        return {
            "schema_version": 1,
            "pid": os.getpid(),
            "cleanup_complete": complete,
            "http_handlers": int(http.get("handlers", 0)),
            "http_calls": int(http.get("active", 0)),
            "http_sockets": int(http.get("sockets", 0)),
            "service_pending": 0 if self.service is None else self.service.metrics()["active"],
            "coordinator_pending": 0
            if self.coordinator is None
            else self.coordinator.pending_count,
            "work_pending": 0 if self.work_client is None else self.work_client.pending_count,
            "case_pending": 0 if self.case_client is None else self.case_client.pending_count,
            "startup_pending": self.resources.startup_pending,
            "retained_owners": [len(tier) for tier in self.resources.tiers],
            "telemetry_failed": self._telemetry_failed,
        }

    async def close(self) -> bool:
        self._bind()
        try:
            return await self._close()
        except asyncio.CancelledError:
            raise
        except OriginHostError:
            raise
        except Exception:  # noqa: BLE001 - incomplete cleanup never serializes dependency messages
            raise OriginHostError("cleanup_incomplete") from None

    async def _close(self) -> bool:
        self._bind()
        if self._closed:
            return True
        self._closing = True
        self.request_stop()
        deadline = self.config.parent_deadline_monotonic
        while time.monotonic() < deadline:
            if await self.resources.close_once(deadline):
                observation = self.observation(complete=True)
                if any(
                    observation[key] != 0
                    for key in (
                        "http_handlers",
                        "http_calls",
                        "http_sockets",
                        "service_pending",
                        "coordinator_pending",
                        "work_pending",
                        "case_pending",
                        "startup_pending",
                    )
                ):
                    raise OriginHostError("cleanup_incomplete")
                publish(self.runtime.directory, self.config.role + "-closed.json", observation)
                self._closed = True
                self._log("closed")
                return True
            if not self._incomplete_published:
                publish(
                    self.runtime.directory,
                    self.config.role + "-cleanup-incomplete.json",
                    self.observation(complete=False),
                )
                self._incomplete_published = True
                self._log("cleanup_incomplete")
            await asyncio.sleep(min(0.01, max(0, deadline - time.monotonic())))
        if not self._incomplete_published:
            publish(
                self.runtime.directory,
                self.config.role + "-cleanup-incomplete.json",
                self.observation(complete=False),
            )
            self._incomplete_published = True
            self._log("cleanup_incomplete")
        return False

    async def wait_stop(self) -> None:
        self._bind()
        while not self.control.stopped():
            await asyncio.sleep(min(0.01, max(0, self.config.business_deadline - time.monotonic())))


async def serve(runtime: RuntimeEnvironment, config: OriginHostConfig) -> int:
    host = OriginFixtureHost(runtime, config)
    loop = asyncio.get_running_loop()
    installed_signal = False
    primary: HostCode | None = None
    complete = False
    try:
        loop.add_signal_handler(signal.SIGTERM, host.request_stop)
        installed_signal = True
        await host.start()
        await host.wait_stop()
        if time.monotonic() >= config.business_deadline:
            primary = "deadline_exceeded"
    except asyncio.CancelledError:
        primary = "closed"
        raise
    except OriginHostError as error:
        primary = cast(HostCode, error.code)
    except Exception:  # noqa: BLE001 - no dependency text leaves this fixture
        primary = "startup_failed"
    finally:
        try:
            complete = await host.close()
        except Exception:  # noqa: BLE001 - preserve the primary error through cleanup
            if primary is None:
                primary = "cleanup_incomplete"
        if installed_signal:
            loop.remove_signal_handler(signal.SIGTERM)
    passed = primary is None and complete
    print(
        json.dumps(
            {
                "schema_version": 1,
                "status": "closed" if passed else "failed",
                "code": "ok" if passed else primary or "cleanup_incomplete",
                "cleanup_complete": complete,
                "role": config.role,
            },
            separators=(",", ":"),
        )
    )
    return 0 if passed else 1


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 1 or arguments[0] not in ROLES:
        print('{"schema_version":1,"status":"failed","code":"invalid_configuration"}')
        return 1
    try:
        runtime, config = configuration(arguments[0])
        return asyncio.run(serve(runtime, config))
    except Exception:  # noqa: BLE001 - malformed config and dependency messages stay private
        print('{"schema_version":1,"status":"failed","code":"invalid_configuration"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
