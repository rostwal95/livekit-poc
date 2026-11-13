"""Parent physical activation CAS and private original-room records.

No imports or constructors perform filesystem/SDK/network work. This state is a
bounded lifecycle/recovery guard; durable business history stays with P1/P2.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PosixPath
from typing import Literal, cast

from .native_worker_config import (
    LIVEKIT_URL,
    NativeWorkerConfig,
    NativeWorkerConfigError,
    encode_native_worker_config,
    validate_livekit_url,
)
from .room_control import RoomBinding, RoomOpen
from .wire import uuid_value

MAX_GENERATION = 1_000_000
COMMAND_BYTES = 1024
DESCRIPTOR_BYTES = 32768
RoomCode = Literal[
    "invalid_input",
    "conflict",
    "capacity",
    "closed",
    "unavailable",
    "outcome_unknown",
    "cleanup_incomplete",
    "recovery_required",
]
RoomStage = Literal[
    "idle", "preparing", "waiting_browser", "ready", "closing", "closed", "recovery_required"
]


class NativeRoomError(Exception):
    def __init__(self, code: RoomCode = "unavailable") -> None:
        self.code: RoomCode = (
            code
            if type(code) is str
            and code
            in {
                "invalid_input",
                "conflict",
                "capacity",
                "closed",
                "unavailable",
                "outcome_unknown",
                "cleanup_incomplete",
                "recovery_required",
            }
            else "unavailable"
        )
        super().__init__(self.code)


def _need(value: bool, code: RoomCode = "invalid_input") -> None:
    if not value:
        raise NativeRoomError(code)


def _uuid(value: object) -> str:
    try:
        return uuid_value(cast(str, value))
    except Exception:  # noqa: BLE001 - finite private-file boundary; never expose paths or replace foreign owners
        raise NativeRoomError("invalid_input") from None


def generation(value: object, *, zero: bool = True) -> str:
    _need(type(value) is str and re.fullmatch(r"0|[1-9][0-9]{0,6}", value, re.ASCII) is not None)
    copied = cast(str, value)
    _need((0 if zero else 1) <= int(copied) <= MAX_GENERATION)
    return copied


def _identifier(value: object) -> str:
    _need(
        type(value) is str
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value, re.ASCII) is not None
    )
    return cast(str, value)


def _token(value: object) -> str:
    _need(type(value) is str and re.fullmatch(r"[A-Za-z0-9_-]{43}", value, re.ASCII) is not None)
    return cast(str, value)


def _jwt(value: object) -> str:
    _need(
        type(value) is str
        and 0 < len(value) <= 8192
        and re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", value, re.ASCII)
        is not None
    )
    return cast(str, value)


def utc_time(value: object) -> str:
    _need(
        type(value) is str
        and re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z", value, re.ASCII
        )
        is not None
    )
    try:
        copied = cast(str, value)
        _need(
            datetime.fromisoformat(copied).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            == copied
        )
        return copied
    except (ValueError, OverflowError):
        raise NativeRoomError("invalid_input") from None


def now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class StartCommand:
    owner_epoch: str
    expected_generation: str
    command_id: str

    def __post_init__(self) -> None:
        _uuid(self.owner_epoch)
        generation(self.expected_generation)
        _uuid(self.command_id)


@dataclass(frozen=True, slots=True)
class EndCommand:
    owner_epoch: str
    generation: str
    original_start_command_id: str

    def __post_init__(self) -> None:
        _uuid(self.owner_epoch)
        generation(self.generation, zero=False)
        _uuid(self.original_start_command_id)


@dataclass(frozen=True, slots=True)
class NodeRoomCursor:
    """Observed Node cursor, never the Parent physical activation version."""

    node_epoch: str
    generation: str
    recovery_required: bool
    control_port: int = 11029

    def __post_init__(self) -> None:
        _uuid(self.node_epoch)
        generation(self.generation)
        _need(type(self.recovery_required) is bool)
        _need(type(self.control_port) is int and 1 <= self.control_port <= 65535)

    def payload(self) -> dict[str, object]:
        return {
            "nodeEpoch": self.node_epoch,
            "generation": self.generation,
            "recoveryRequired": self.recovery_required,
            "endpoint": {"host": "127.0.0.1", "port": self.control_port},
        }


@dataclass(frozen=True, slots=True)
class NativeRoomStatus:
    owner_epoch: str
    generation: str
    original_start_command_id: str | None
    stage: RoomStage
    as_of: str
    node_cursor: NodeRoomCursor
    sdk_ready: bool = False
    worker_running: bool = False
    expires_at: str | None = None

    def __post_init__(self) -> None:
        _uuid(self.owner_epoch)
        generation(self.generation)
        if self.original_start_command_id is not None:
            _uuid(self.original_start_command_id)
        _need((self.generation == "0") == (self.original_start_command_id is None))
        _need(
            type(self.stage) is str
            and self.stage
            in {
                "idle",
                "preparing",
                "waiting_browser",
                "ready",
                "closing",
                "closed",
                "recovery_required",
            }
        )
        utc_time(self.as_of)
        _need(type(self.node_cursor) is NodeRoomCursor)
        NodeRoomCursor(
            self.node_cursor.node_epoch,
            self.node_cursor.generation,
            self.node_cursor.recovery_required,
            self.node_cursor.control_port,
        )
        _need(type(self.sdk_ready) is bool and type(self.worker_running) is bool)
        _need(not self.sdk_ready or self.stage == "ready" and self.worker_running)
        if self.expires_at is not None:
            utc_time(self.expires_at)
        if self.stage in {"idle", "closed"}:
            _need(not self.worker_running and not self.sdk_ready)

    def payload(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "ownerEpoch": self.owner_epoch,
            "generation": self.generation,
            "originalStartCommandId": self.original_start_command_id,
            "stage": self.stage,
            "asOf": self.as_of,
            "nodeCursor": self.node_cursor.payload(),
            "sdkReady": self.sdk_ready,
            "workerRunning": self.worker_running,
            "expiresAt": self.expires_at,
        }


@dataclass(frozen=True, slots=True)
class BrowserRoomGrant:
    owner_epoch: str
    generation: str
    original_start_command_id: str
    token: str = field(repr=False)
    room_id: str
    participant_id: str
    agent_id: str
    binding_id: str
    expires_at: str
    url: str = LIVEKIT_URL
    mode: Literal["scripted", "provider_real"] = "scripted"

    def __post_init__(self) -> None:
        EndCommand(self.owner_epoch, self.generation, self.original_start_command_id)
        _jwt(self.token)
        for value in (self.room_id, self.participant_id, self.agent_id):
            _identifier(value)
        _need(self.participant_id != self.agent_id)
        _uuid(self.binding_id)
        utc_time(self.expires_at)
        try:
            validate_livekit_url(self.url)
        except NativeWorkerConfigError:
            raise NativeRoomError("invalid_input") from None
        _need(type(self.mode) is str and self.mode in ("scripted", "provider_real"))

    def payload(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "ownerEpoch": self.owner_epoch,
            "generation": self.generation,
            "originalStartCommandId": self.original_start_command_id,
            "mode": self.mode,
            "stage": "waiting_browser",
            "rtc": {
                "url": self.url,
                "token": self.token,
                "roomId": self.room_id,
                "participantId": self.participant_id,
                "agentId": self.agent_id,
                "bindingId": self.binding_id,
                "expiresAt": self.expires_at,
            },
        }


def room_metadata(start: StartCommand, binding_id: str) -> str:
    """Nonsecret ownership marker, combined with creation history/name and SID."""
    _need(type(start) is StartCommand)
    StartCommand(start.owner_epoch, start.expected_generation, start.command_id)
    _uuid(binding_id)
    return json.dumps(
        {
            "schemaVersion": 1,
            "kind": "channel_policy_native_room",
            "ownerEpoch": start.owner_epoch,
            "startCommandId": start.command_id,
            "bindingId": binding_id,
        },
        separators=(",", ":"),
        allow_nan=False,
    )


@dataclass(frozen=True, slots=True)
class RoomIdentity:
    name: str
    metadata: str
    sid: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.name)
        try:
            _need(type(self.metadata) is str)
            raw = self.metadata.encode("utf-8", "strict")
        except UnicodeError:
            raise NativeRoomError("invalid_input") from None
        _need(0 < len(raw) <= 1024)
        value = _decode(raw, 1024)
        _need(set(value) == {"schemaVersion", "kind", "ownerEpoch", "startCommandId", "bindingId"})
        _need(
            type(value["schemaVersion"]) is int
            and value["schemaVersion"] == 1
            and value["kind"] == "channel_policy_native_room"
        )
        for key in ("ownerEpoch", "startCommandId", "bindingId"):
            _uuid(value[key])
        _need(_encode(value) == raw)
        if self.sid is not None:
            _identifier(self.sid)


@dataclass(frozen=True, slots=True)
class RoomDescriptor:
    """Immutable original request+caps; a descriptor is not mutation authority."""

    start: StartCommand
    generation: str
    node_open: RoomOpen = field(repr=False)
    browser_token: str = field(repr=False)
    worker_config_sha256: str
    metadata: str
    mode: Literal["scripted", "provider_real"] = "scripted"

    def __post_init__(self) -> None:
        _need(type(self.start) is StartCommand and type(self.node_open) is RoomOpen)
        _need(type(self.mode) is str and self.mode in ("scripted", "provider_real"))
        StartCommand(self.start.owner_epoch, self.start.expected_generation, self.start.command_id)
        generation(self.generation, zero=False)
        _need(int(self.generation) == int(self.start.expected_generation) + 1)
        b = self.node_open.binding
        _need(type(b) is RoomBinding)
        copied = RoomOpen(
            self.node_open.node_epoch,
            self.node_open.expected_generation,
            self.node_open.open_id,
            RoomBinding(
                b.binding_id, b.native_bearer, b.room_id, b.participant_id, b.agent_id, b.expires_at
            ),
            self.node_open.room_view_bearer,
        )
        _need(copied == self.node_open)
        _jwt(self.browser_token)
        _need(
            type(self.worker_config_sha256) is str
            and re.fullmatch(r"[0-9a-f]{64}", self.worker_config_sha256, re.ASCII) is not None
        )
        _need(self.metadata == room_metadata(self.start, b.binding_id))
        RoomIdentity(b.room_id, self.metadata)


@dataclass(frozen=True, slots=True)
class RoomFiles:
    directory: Path = field(repr=False)
    descriptor_path: Path = field(repr=False)
    worker_config_path: Path = field(repr=False)
    descriptor_sha256: str
    config_sha256: str


@dataclass(frozen=True, slots=True)
class ClosedRoomReceipt:
    status: NativeRoomStatus
    room: RoomIdentity
    descriptor_sha256: str | None
    worker_exit_code: int | None
    room_disposition: Literal["never_created", "observed_absent"]
    worker_disposition: Literal["never_started", "reaped"]

    def __post_init__(self) -> None:
        _need(type(self.status) is NativeRoomStatus and self.status.stage == "closed")
        _need(type(self.room) is RoomIdentity)
        metadata = _decode(self.room.metadata.encode("utf-8", "strict"), 1024)
        _need(
            (metadata["ownerEpoch"], metadata["startCommandId"])
            == (self.status.owner_epoch, self.status.original_start_command_id)
        )
        _need(
            type(self.room_disposition) is str
            and self.room_disposition in {"never_created", "observed_absent"}
        )
        _need((self.room_disposition == "observed_absent") == (self.room.sid is not None))
        _need(
            type(self.worker_disposition) is str
            and self.worker_disposition in {"never_started", "reaped"}
        )
        if self.worker_disposition == "reaped":
            _need(type(self.worker_exit_code) is int and -255 <= self.worker_exit_code <= 255)
        else:
            _need(self.worker_exit_code is None)
        if self.descriptor_sha256 is not None:
            _need(
                type(self.descriptor_sha256) is str
                and re.fullmatch(r"[0-9a-f]{64}", self.descriptor_sha256, re.ASCII) is not None
            )


def _pairs(values: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in values:
        _need(name not in result)
        result[name] = value
    return result


def _constant(_: str) -> object:
    raise NativeRoomError("invalid_input")


def _decode(raw: bytes, maximum: int = COMMAND_BYTES) -> dict[str, object]:
    try:
        _need(type(raw) is bytes and 0 < len(raw) <= maximum)
        value: object = json.loads(
            raw.decode("utf-8", "strict"), object_pairs_hook=_pairs, parse_constant=_constant
        )
        _need(type(value) is dict)
        return cast(dict[str, object], value)
    except (ValueError, UnicodeError, RecursionError):
        raise NativeRoomError("invalid_input") from None


def _encode(value: dict[str, object]) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
            "utf-8", "strict"
        )
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise NativeRoomError("invalid_input") from None


def parse_start_command(raw: bytes) -> StartCommand:
    value = _decode(raw)
    _need(set(value) == {"schemaVersion", "ownerEpoch", "expectedGeneration", "commandId"})
    _need(type(value["schemaVersion"]) is int and value["schemaVersion"] == 1)
    return StartCommand(
        _uuid(value["ownerEpoch"]),
        generation(value["expectedGeneration"]),
        _uuid(value["commandId"]),
    )


def parse_end_command(raw: bytes) -> EndCommand:
    value = _decode(raw)
    _need(set(value) == {"schemaVersion", "ownerEpoch", "generation", "originalStartCommandId"})
    _need(type(value["schemaVersion"]) is int and value["schemaVersion"] == 1)
    return EndCommand(
        _uuid(value["ownerEpoch"]),
        generation(value["generation"], zero=False),
        _uuid(value["originalStartCommandId"]),
    )


def encode_descriptor(value: RoomDescriptor, config: NativeWorkerConfig) -> bytes:
    try:
        _need(type(value) is RoomDescriptor and type(config) is NativeWorkerConfig)
        copied = RoomDescriptor(
            value.start,
            value.generation,
            value.node_open,
            value.browser_token,
            value.worker_config_sha256,
            value.metadata,
            value.mode,
        )
        config_raw = encode_native_worker_config(config)
        _need(hashlib.sha256(config_raw).hexdigest() == copied.worker_config_sha256)
        _need(copied.mode == config.inference_mode)
        b = copied.node_open.binding
        c = config.binding
        _need(
            (b.binding_id, b.room_id, b.participant_id, b.agent_id)
            == (c.binding_id, c.room_id, c.participant_id, c.agent_id)
        )
        _need(config.native_credential.value == b.native_bearer)
        _need(
            len(
                {
                    b.native_bearer,
                    copied.node_open.room_view_bearer,
                    config.current_bearer,
                    config.prepare_bearer,
                }
            )
            == 4
        )
        raw = _encode(
            {
                "schemaVersion": 1,
                "mode": copied.mode,
                "ownerEpoch": copied.start.owner_epoch,
                "expectedGeneration": copied.start.expected_generation,
                "generation": copied.generation,
                "originalStartCommandId": copied.start.command_id,
                "nodeOpen": copied.node_open.to_wire(),
                "browserToken": copied.browser_token,
                "workerConfigSha256": copied.worker_config_sha256,
                "roomMetadata": copied.metadata,
            }
        )
        _need(len(raw) <= DESCRIPTOR_BYTES)
        return raw
    except Exception:  # noqa: BLE001 - finite private-file boundary; never expose paths or replace foreign owners
        raise NativeRoomError("invalid_input") from None


def encode_start_command(value: StartCommand) -> bytes:
    _need(type(value) is StartCommand)
    copied = StartCommand(value.owner_epoch, value.expected_generation, value.command_id)
    return _encode(
        {
            "schemaVersion": 1,
            "ownerEpoch": copied.owner_epoch,
            "expectedGeneration": copied.expected_generation,
            "commandId": copied.command_id,
        }
    )


def encode_end_command(value: EndCommand) -> bytes:
    _need(type(value) is EndCommand)
    copied = EndCommand(value.owner_epoch, value.generation, value.original_start_command_id)
    return _encode(
        {
            "schemaVersion": 1,
            "ownerEpoch": copied.owner_epoch,
            "generation": copied.generation,
            "originalStartCommandId": copied.original_start_command_id,
        }
    )


def encode_closed_receipt(value: ClosedRoomReceipt) -> bytes:
    _need(type(value) is ClosedRoomReceipt)
    copied = ClosedRoomReceipt(
        value.status,
        value.room,
        value.descriptor_sha256,
        value.worker_exit_code,
        value.room_disposition,
        value.worker_disposition,
    )
    # There are deliberately no tokens, capabilities, original control bodies,
    # transcripts, provider values or raw child stderr in the terminal receipt.
    return _encode(
        {
            "schemaVersion": 1,
            "status": copied.status.payload(),
            "room": {
                "name": copied.room.name,
                "metadata": copied.room.metadata,
                "sid": copied.room.sid,
                "disposition": copied.room_disposition,
            },
            "descriptorSha256": copied.descriptor_sha256,
            "worker": {
                "disposition": copied.worker_disposition,
                "exitCode": copied.worker_exit_code,
            },
        }
    )


def _fields(value: object, keys: set[str]) -> dict[str, object]:
    _need(type(value) is dict and set(value) == keys)
    return cast(dict[str, object], value)


def parse_closed_receipt(raw: bytes) -> ClosedRoomReceipt:
    value = _fields(
        _decode(raw, DESCRIPTOR_BYTES),
        {"schemaVersion", "status", "room", "descriptorSha256", "worker"},
    )
    _need(type(value["schemaVersion"]) is int and value["schemaVersion"] == 1)
    status = _fields(
        value["status"],
        {
            "schemaVersion",
            "ownerEpoch",
            "generation",
            "originalStartCommandId",
            "stage",
            "asOf",
            "nodeCursor",
            "sdkReady",
            "workerRunning",
            "expiresAt",
        },
    )
    _need(
        type(status["schemaVersion"]) is int
        and status["schemaVersion"] == 1
        and status["stage"] == "closed"
    )
    node = _fields(
        status["nodeCursor"], {"nodeEpoch", "generation", "recoveryRequired", "endpoint"}
    )
    endpoint = _fields(node["endpoint"], {"host", "port"})
    _need(type(endpoint["host"]) is str and endpoint["host"] == "127.0.0.1")
    copied_status = NativeRoomStatus(
        cast(str, status["ownerEpoch"]),
        cast(str, status["generation"]),
        cast(str | None, status["originalStartCommandId"]),
        "closed",
        cast(str, status["asOf"]),
        NodeRoomCursor(
            cast(str, node["nodeEpoch"]),
            cast(str, node["generation"]),
            cast(bool, node["recoveryRequired"]),
            cast(int, endpoint["port"]),
        ),
        cast(bool, status["sdkReady"]),
        cast(bool, status["workerRunning"]),
        cast(str | None, status["expiresAt"]),
    )
    room = _fields(value["room"], {"name", "metadata", "sid", "disposition"})
    worker = _fields(value["worker"], {"disposition", "exitCode"})
    result = ClosedRoomReceipt(
        copied_status,
        RoomIdentity(
            cast(str, room["name"]), cast(str, room["metadata"]), cast(str | None, room["sid"])
        ),
        cast(str | None, value["descriptorSha256"]),
        cast(int | None, worker["exitCode"]),
        cast(Literal["never_created", "observed_absent"], room["disposition"]),
        cast(Literal["never_started", "reaped"], worker["disposition"]),
    )
    _need(encode_closed_receipt(result) == raw)
    return result


def _private_info(path: Path, *, directory: bool) -> os.stat_result:
    info = path.lstat()
    expected = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    _need(
        expected
        and info.st_uid == os.getuid()
        and stat.S_IMODE(info.st_mode) == (0o700 if directory else 0o600),
        "recovery_required",
    )
    if not directory:
        _need(info.st_nlink == 1, "recovery_required")
    return info


def _identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _stable_file(info: os.stat_result) -> tuple[int, int, int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _read_private(path: Path, maximum: int) -> bytes:
    before = _private_info(path, directory=False)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        actual = os.fstat(fd)
        _need(
            stat.S_ISREG(actual.st_mode)
            and actual.st_uid == os.getuid()
            and stat.S_IMODE(actual.st_mode) == 0o600
            and actual.st_nlink == 1
            and _stable_file(actual) == _stable_file(before)
            and 0 < actual.st_size <= maximum,
            "recovery_required",
        )
        result = bytearray()
        while len(result) <= maximum:
            part = os.read(fd, min(4096, maximum + 1 - len(result)))
            if not part:
                break
            result.extend(part)
        after = os.fstat(fd)
        _need(
            0 < len(result) <= maximum
            and len(result) == before.st_size
            and _stable_file(after) == _stable_file(before),
            "recovery_required",
        )
        _need(
            _stable_file(_private_info(path, directory=False)) == _stable_file(before),
            "recovery_required",
        )
        return bytes(result)
    finally:
        os.close(fd)


class PrivateRoomState:
    """Synchronous private file owner, called only through retained offload tasks.

    One active immutable descriptor/config and one redacted last-closed receipt
    bound disk growth. Existing active/partial files belong to a previous owner
    and require explicit recovery; constructors and new starts never reset them.
    This object owns only exact inodes it successfully created in this process.
    """

    def __init__(self, directory: Path) -> None:
        _need(type(directory) is PosixPath and directory.is_absolute())
        self._directory = directory
        self._active = directory / "active"
        self._active_identity: tuple[int, int] | None = None
        self._owned: dict[Path, tuple[int, int]] = {}
        self._expected: dict[Path, str] = {}
        self._files: RoomFiles | None = None
        self._descriptor: RoomDescriptor | None = None
        self._receipt: bytes | None = None

    @property
    def files(self) -> RoomFiles | None:
        return self._files

    def _root(self) -> None:
        _need(
            self._directory.parent.resolve(strict=True) == self._directory.parent,
            "recovery_required",
        )
        try:
            self._directory.mkdir(mode=0o700)
        except FileExistsError:
            pass
        _private_info(self._directory, directory=True)
        _need(self._directory.resolve(strict=True) == self._directory, "recovery_required")
        _need(
            {entry.name for entry in self._directory.iterdir()} <= {"active", "lastclosed.json"},
            "recovery_required",
        )
        previous = self._directory / "lastclosed.json"
        if previous.exists():
            try:
                parse_closed_receipt(_read_private(previous, DESCRIPTOR_BYTES))
            except Exception:  # noqa: BLE001 - finite private-file boundary; never expose paths or replace foreign owners
                raise NativeRoomError("recovery_required") from None

    def _new(self, final: Path, raw: bytes) -> None:
        pending = final.with_name(final.name + ".pending")
        # A retry may remove only this object's unfinished file, never a file
        # from a prior process or a foreign inode at the same path.
        if pending in self._owned:
            self._unlink_owned(pending)
        fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        self._owned[pending] = _identity(os.fstat(fd))
        try:
            view = memoryview(raw)
            while view:
                written = os.write(fd, view)
                _need(written > 0, "unavailable")
                view = view[written:]
            os.fsync(fd)
            _need(stat.S_IMODE(os.fstat(fd).st_mode) == 0o600, "unavailable")
        finally:
            os.close(fd)
        # Complete bytes become visible atomically. link is exclusive; it never
        # replaces a descriptor/config already present under the original name.
        os.link(pending, final, follow_symlinks=False)
        self._owned[final] = self._owned[pending]
        self._expected[final] = hashlib.sha256(raw).hexdigest()
        self._unlink_owned(pending)
        _sync_directory(final.parent)

    def prepare(self, descriptor: RoomDescriptor, config: NativeWorkerConfig) -> RoomFiles:
        try:
            _need(self._active_identity is None and self._files is None, "conflict")
            descriptor_raw = encode_descriptor(descriptor, config)
            config_raw = encode_native_worker_config(config)
            self._descriptor = descriptor
            self._root()
            try:
                self._active.mkdir(mode=0o700)
            except FileExistsError:
                raise NativeRoomError("recovery_required") from None
            self._active_identity = _identity(_private_info(self._active, directory=True))
            self._new(self._active / "worker.json", config_raw)
            self._new(self._active / "descriptor.json", descriptor_raw)
            self._files = RoomFiles(
                self._active,
                self._active / "descriptor.json",
                self._active / "worker.json",
                hashlib.sha256(descriptor_raw).hexdigest(),
                hashlib.sha256(config_raw).hexdigest(),
            )
            _sync_directory(self._directory)
            return self._files
        except NativeRoomError:
            raise
        except Exception:  # noqa: BLE001 - finite private-file boundary; never expose paths or replace foreign owners
            raise NativeRoomError("unavailable") from None

    def _unlink_owned(self, path: Path) -> None:
        owned = self._owned.get(path)
        _need(owned is not None, "cleanup_incomplete")
        try:
            actual = path.lstat()
        except FileNotFoundError:
            self._owned.pop(path, None)
            self._expected.pop(path, None)
            return
        _need(
            stat.S_ISREG(actual.st_mode)
            and _identity(actual) == owned
            and actual.st_uid == os.getuid()
            and stat.S_IMODE(actual.st_mode) == 0o600,
            "cleanup_incomplete",
        )
        if path in self._expected:
            _need(
                hashlib.sha256(_read_private(path, DESCRIPTOR_BYTES)).hexdigest()
                == self._expected[path],
                "cleanup_incomplete",
            )
        path.unlink()
        self._owned.pop(path, None)
        self._expected.pop(path, None)

    def finish(self, receipt: ClosedRoomReceipt) -> None:
        """Publish one nonsecret receipt, then remove only owned active files.

        The controller calls this only after real effects/clients/child settle.
        A partial filesystem failure retains this object and must be reobserved;
        it cannot free the physical activation for a new room prematurely.
        """
        try:
            raw = encode_closed_receipt(receipt)
            _need(self._receipt is None or self._receipt == raw, "conflict")
            if self._active_identity is None:
                # No owned active directory means preparation never created any
                # private resources. Existing foreign/stale state is untouched.
                _need(not self._owned, "cleanup_incomplete")
                return
            descriptor = self._descriptor
            _need(descriptor is not None, "cleanup_incomplete")
            if descriptor is not None:
                _need(
                    (
                        receipt.status.owner_epoch,
                        receipt.status.generation,
                        receipt.status.original_start_command_id,
                        receipt.room.name,
                        receipt.room.metadata,
                    )
                    == (
                        descriptor.start.owner_epoch,
                        descriptor.generation,
                        descriptor.start.command_id,
                        descriptor.node_open.binding.room_id,
                        descriptor.metadata,
                    ),
                    "cleanup_incomplete",
                )
            _need(
                self._files is None
                and receipt.descriptor_sha256 is None
                or self._files is not None
                and receipt.descriptor_sha256 == self._files.descriptor_sha256,
                "cleanup_incomplete",
            )
            _need(
                _identity(_private_info(self._active, directory=True)) == self._active_identity,
                "cleanup_incomplete",
            )
            _need(
                set(self._active.iterdir())
                == {path for path in self._owned if path.parent == self._active},
                "cleanup_incomplete",
            )
            if self._receipt is None:
                pending = self._directory / "lastclosed.json.pending"
                if pending in self._owned:
                    self._unlink_owned(pending)
                fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                self._owned[pending] = _identity(os.fstat(fd))
                try:
                    view = memoryview(raw)
                    while view:
                        written = os.write(fd, view)
                        _need(written > 0, "cleanup_incomplete")
                        view = view[written:]
                    os.fsync(fd)
                finally:
                    os.close(fd)
                final = self._directory / "lastclosed.json"
                if final.exists():
                    parse_closed_receipt(_read_private(final, DESCRIPTOR_BYTES))
                os.replace(pending, final)
                self._owned.pop(pending)
                self._receipt = raw
                _sync_directory(self._directory)
            for path in tuple(self._owned):
                _need(path.parent == self._active, "cleanup_incomplete")
                self._unlink_owned(path)
            self._active.rmdir()
            self._active_identity = None
            _sync_directory(self._directory)
        except NativeRoomError:
            raise
        except Exception:  # noqa: BLE001 - finite private-file boundary; never expose paths or replace foreign owners
            raise NativeRoomError("cleanup_incomplete") from None
