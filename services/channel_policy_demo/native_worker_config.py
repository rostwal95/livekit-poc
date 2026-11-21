"""Closed native worker startup data; no SDK, assets or environment I/O.

Only load_native_worker_config reads the explicitly selected private JSON file.
The worker receives its own RTC token and three narrow service capabilities,
never database, case, publisher, discovery, provider or Node room-view secrets.
The private configuration selects scripted models. JWT syntax does not
validate signature, claims or mutation authority.
"""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from channel_continuity.codec import AccountScope, ProviderScope
from channel_continuity.native_models import NativeBinding, NativeCredential, NativeEndpoint

from .discovery import DiscoveryScope
from .native_models import InputFixture, ReplyFixture, ScriptedModelProfile
from .wire import uuid_value

if TYPE_CHECKING:
    from .worker_client import WorkerBinding
    from .worker_current_result import CurrentResultCredential, WorkerCurrentEndpoint

CONFIG_BYTES = 32768
LIVEKIT_URL = "ws://127.0.0.1:17880"
_APPLICATION_ID = re.compile(r"[a-z][a-z0-9_-]{0,63}", re.ASCII)
_CAPABILITY = re.compile(r"[A-Za-z0-9_-]{43}", re.ASCII)
_JWT = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", re.ASCII)
InferenceMode = Literal["scripted"]
_FIELDS = {
    "schemaVersion",
    "profileId",
    "scope",
    "providerAccountId",
    "caseId",
    "conversationId",
    "bindingId",
    "roomId",
    "participantId",
    "agentId",
    "livekit",
    "native",
    "prepare",
    "rehydration",
    "currentResult",
    "scripted",
}


class NativeWorkerConfigError(ValueError):
    """One fixed diagnostic; configuration values and paths are never reflected."""

    def __init__(self) -> None:
        self.code: Literal["invalid_configuration"] = "invalid_configuration"
        super().__init__(self.code)


def _need(condition: bool) -> None:
    if not condition:
        raise NativeWorkerConfigError()


def _object(value: object, names: set[str]) -> dict[str, object]:
    _need(type(value) is dict and set(value) == names)
    return cast(dict[str, object], value)


def _port(value: object) -> int:
    _need(type(value) is int and 1 <= value <= 65535)
    return cast(int, value)


def validate_livekit_url(value: object, *, scheme: Literal["http", "ws"] = "ws") -> str:
    """One canonical explicit-port loopback URL; no hostname/path/ambient lookup."""
    _need(type(scheme) is str and scheme in {"http", "ws"} and type(value) is str)
    copied = cast(str, value)
    matched = re.fullmatch(rf"{scheme}://127[.]0[.]0[.]1:([1-9][0-9]{{0,4}})", copied, re.ASCII)
    _need(matched is not None)
    assert matched is not None
    _need(1 <= int(matched.group(1)) <= 65535)
    return copied


def _capability(value: object) -> str:
    _need(type(value) is str and _CAPABILITY.fullmatch(value) is not None)
    return cast(str, value)


def _token(value: object) -> str:
    _need(type(value) is str and 0 < len(value) <= 8192 and _JWT.fullmatch(value) is not None)
    return cast(str, value)


def _binding(value: NativeBinding) -> NativeBinding:
    _need(
        type(value) is NativeBinding
        and type(value.provider_scope) is ProviderScope
        and type(value.account_scope) is AccountScope
    )
    return NativeBinding(
        value.binding_id,
        ProviderScope(
            value.provider_scope.tenant_id,
            value.provider_scope.provider,
            value.provider_scope.provider_account_id,
        ),
        AccountScope(value.account_scope.tenant_id, value.account_scope.account_id),
        value.case_id,
        value.conversation_id,
        value.room_id,
        value.participant_id,
        value.agent_id,
    )


@dataclass(frozen=True, slots=True)
class NativeWorkerConfig:
    """Immutable copied startup values; secret fields are excluded from repr.

    All wire fields are required. Constructor defaults select the four existing
    local service ports; schema1 supports scripted fixtures only. Public P2/P3
    binding constructors and compatible lowercase application identifiers enforce
    the narrow route. Pure codecs do not import heavy clients. The three typed
    client properties lazily load their genuine public implementations on access.
    """

    profile_id: str
    binding: NativeBinding
    livekit_token: str = field(repr=False)
    native_credential: NativeCredential = field(repr=False)
    prepare_bearer: str = field(repr=False)
    current_bearer: str = field(repr=False)
    model_profile: ScriptedModelProfile = field(default_factory=ScriptedModelProfile)
    native_endpoint: NativeEndpoint = field(
        default_factory=lambda: NativeEndpoint("127.0.0.1", 11024)
    )
    prepare_port: int = 11030
    rehydration_endpoint: NativeEndpoint = field(
        default_factory=lambda: NativeEndpoint("127.0.0.1", 11032)
    )
    current_port: int = 11031
    livekit_url: str = LIVEKIT_URL
    inference_mode: InferenceMode = "scripted"

    def __post_init__(self) -> None:
        try:
            _need(self.inference_mode == "scripted")
            profile = uuid_value(self.profile_id)
            binding = _binding(self.binding)
            livekit_url = validate_livekit_url(self.livekit_url)
            token = _token(self.livekit_token)
            _need(type(self.native_credential) is NativeCredential)
            native_cap = _capability(self.native_credential.value)
            prepare_cap = _capability(self.prepare_bearer)
            current_cap = _capability(self.current_bearer)
            caps = {native_cap, prepare_cap, current_cap}
            _need(len(caps) == 3 and not caps.intersection(token.split(".")))
            _need(
                type(self.native_endpoint) is NativeEndpoint
                and type(self.rehydration_endpoint) is NativeEndpoint
            )
            native_endpoint = NativeEndpoint(self.native_endpoint.host, self.native_endpoint.port)
            prepare_port = _port(self.prepare_port)
            rehydration_endpoint = NativeEndpoint(
                self.rehydration_endpoint.host, self.rehydration_endpoint.port
            )
            current_port = _port(self.current_port)
            _need(
                len(
                    {
                        native_endpoint.port,
                        prepare_port,
                        rehydration_endpoint.port,
                        current_port,
                    }
                )
                == 4
            )
            _need(
                type(self.model_profile) is ScriptedModelProfile
                and type(self.model_profile.input_fixtures) is tuple
                and type(self.model_profile.cleanup_timeout_s) in (int, float)
                and self.model_profile.cleanup_timeout_s == 1
            )
            models = ScriptedModelProfile(
                tuple(self.model_profile.input_fixtures), self.model_profile.reply_fixture
            )
            DiscoveryScope(binding.account_scope.tenant_id, binding.account_scope.account_id)
            for identifier in (binding.case_id, binding.conversation_id):
                _need(_APPLICATION_ID.fullmatch(identifier) is not None)
            for name, copied in (
                ("profile_id", profile),
                ("binding", binding),
                ("livekit_token", token),
                ("livekit_url", livekit_url),
                ("native_credential", NativeCredential(native_cap)),
                ("prepare_bearer", prepare_cap),
                ("current_bearer", current_cap),
                ("model_profile", models),
                ("native_endpoint", native_endpoint),
                ("prepare_port", prepare_port),
                ("rehydration_endpoint", rehydration_endpoint),
                ("current_port", current_port),
            ):
                object.__setattr__(self, name, copied)
        except Exception:  # noqa: BLE001 - closed startup boundary never reveals values
            raise NativeWorkerConfigError() from None

    @property
    def current_endpoint(self) -> WorkerCurrentEndpoint:
        from .worker_current_result import WorkerCurrentEndpoint

        return WorkerCurrentEndpoint(port=self.current_port)

    @property
    def current_credential(self) -> CurrentResultCredential:
        from .worker_current_result import CurrentResultCredential

        return CurrentResultCredential(self.current_bearer)

    @property
    def worker_binding(self) -> WorkerBinding:
        from .worker_client import WorkerBinding

        binding = self.binding
        return WorkerBinding(
            self.profile_id,
            DiscoveryScope(binding.account_scope.tenant_id, binding.account_scope.account_id),
            binding.case_id,
            binding.conversation_id,
        )


def _copy(value: NativeWorkerConfig) -> NativeWorkerConfig:
    _need(type(value) is NativeWorkerConfig)
    return NativeWorkerConfig(
        value.profile_id,
        value.binding,
        value.livekit_token,
        value.native_credential,
        value.prepare_bearer,
        value.current_bearer,
        value.model_profile,
        value.native_endpoint,
        value.prepare_port,
        value.rehydration_endpoint,
        value.current_port,
        value.livekit_url,
        value.inference_mode,
    )


def encode_native_worker_config(config: NativeWorkerConfig) -> bytes:
    """Revalidate bypassed DTOs and emit one deterministic compact JSON record."""
    try:
        value = _copy(config)
        binding = value.binding
        payload = {
            "schemaVersion": 1,
            "profileId": value.profile_id,
            "scope": {
                "tenantId": binding.account_scope.tenant_id,
                "accountId": binding.account_scope.account_id,
            },
            "providerAccountId": binding.provider_scope.provider_account_id,
            "caseId": binding.case_id,
            "conversationId": binding.conversation_id,
            "bindingId": binding.binding_id,
            "roomId": binding.room_id,
            "participantId": binding.participant_id,
            "agentId": binding.agent_id,
            "livekit": {"url": value.livekit_url, "token": value.livekit_token},
            "native": {"port": value.native_endpoint.port, "bearer": value.native_credential.value},
            "prepare": {"port": value.prepare_port, "bearer": value.prepare_bearer},
            "rehydration": {"port": value.rehydration_endpoint.port},
            "currentResult": {
                "port": value.current_port,
                "bearer": value.current_bearer,
            },
            "scripted": {
                "inputFixtures": list(value.model_profile.input_fixtures),
                "replyFixture": value.model_profile.reply_fixture,
            },
        }
        raw = (
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n"
        ).encode("utf-8", "strict")
        _need(0 < len(raw) <= CONFIG_BYTES)
        return raw
    except Exception:  # noqa: BLE001 - no DTO/dependency/private text in config errors
        raise NativeWorkerConfigError() from None


def _pairs(values: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in values:
        _need(key not in result)
        result[key] = value
    return result


def _constant(_: str) -> object:
    raise NativeWorkerConfigError()


def parse_native_worker_config(raw: bytes) -> NativeWorkerConfig:
    """Parse the closed scripted worker configuration without I/O."""
    try:
        _need(type(raw) is bytes and 0 < len(raw) <= CONFIG_BYTES)
        payload: object = json.loads(
            raw.decode("utf-8", "strict"), object_pairs_hook=_pairs, parse_constant=_constant
        )
        _need(type(payload) is dict)
        version = cast(dict[str, object], payload).get("schemaVersion")
        _need(type(version) is int and version == 1)
        value = _object(payload, _FIELDS)
        scope = _object(value["scope"], {"tenantId", "accountId"})
        livekit = _object(value["livekit"], {"url", "token"})
        native = _object(value["native"], {"port", "bearer"})
        prepare = _object(value["prepare"], {"port", "bearer"})
        rehydration = _object(value["rehydration"], {"port"})
        current = _object(value["currentResult"], {"port", "bearer"})
        scripted = _object(value["scripted"], {"inputFixtures", "replyFixture"})
        inputs = scripted["inputFixtures"]
        _need(type(inputs) is list and 1 <= len(inputs) <= 32)
        return NativeWorkerConfig(
            cast(str, value["profileId"]),
            NativeBinding(
                cast(str, value["bindingId"]),
                ProviderScope(
                    cast(str, scope["tenantId"]), "livekit", cast(str, value["providerAccountId"])
                ),
                AccountScope(cast(str, scope["tenantId"]), cast(str, scope["accountId"])),
                cast(str, value["caseId"]),
                cast(str, value["conversationId"]),
                cast(str, value["roomId"]),
                cast(str, value["participantId"]),
                cast(str, value["agentId"]),
            ),
            cast(str, livekit["token"]),
            NativeCredential(_capability(native["bearer"])),
            _capability(prepare["bearer"]),
            _capability(current["bearer"]),
            ScriptedModelProfile(
                tuple(cast(list[InputFixture], inputs)),
                cast(ReplyFixture, scripted["replyFixture"]),
            ),
            NativeEndpoint("127.0.0.1", _port(native["port"])),
            _port(prepare["port"]),
            NativeEndpoint("127.0.0.1", _port(rehydration["port"])),
            _port(current["port"]),
            cast(str, livekit["url"]),
        )
    except Exception:  # noqa: BLE001 - invalid JSON/public DTOs have one safe code
        raise NativeWorkerConfigError() from None


def _metadata(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _private_directory(value: os.stat_result) -> None:
    _need(
        stat.S_ISDIR(value.st_mode)
        and stat.S_IMODE(value.st_mode) == 0o700
        and value.st_uid == os.getuid()
    )


def _private_file(value: os.stat_result) -> None:
    _need(
        stat.S_ISREG(value.st_mode)
        and stat.S_IMODE(value.st_mode) == 0o600
        and value.st_uid == os.getuid()
        and value.st_nlink == 1
        and 0 < value.st_size <= CONFIG_BYTES
    )


def load_native_worker_config(path: Path) -> NativeWorkerConfig:
    """Read one private canonical JSON path through an anchored, checked parent.

    O_NONBLOCK makes a regular-file-to-FIFO swap finite. File and directory
    metadata/path identities must remain unchanged across the bounded read;
    successful parsing grants no additional service or JWT authority.
    """
    try:
        _need(isinstance(path, Path) and path.is_absolute() and path.suffix == ".json")
        _need(path.resolve(strict=True) == path)
        parent_before = path.parent.lstat()
        _private_directory(parent_before)
        directory = os.open(
            path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK
        )
        try:
            _need(_metadata(os.fstat(directory)) == _metadata(parent_before))
            entry_before = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
            _private_file(entry_before)
            descriptor = os.open(
                path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
            )
            try:
                before = os.fstat(descriptor)
                _private_file(before)
                _need(_metadata(before) == _metadata(entry_before))
                raw = os.read(descriptor, CONFIG_BYTES + 1)
                _need(not os.read(descriptor, 1))
                after = os.fstat(descriptor)
                _need(_metadata(before) == _metadata(after) and len(raw) == before.st_size)
                _need(
                    _metadata(os.stat(path.name, dir_fd=directory, follow_symlinks=False))
                    == _metadata(before)
                )
                _need(_metadata(path.lstat()) == _metadata(before))
                _need(_metadata(os.fstat(directory)) == _metadata(parent_before))
                _need(_metadata(path.parent.lstat()) == _metadata(parent_before))
            finally:
                os.close(descriptor)
        finally:
            os.close(directory)
        return parse_native_worker_config(raw)
    except Exception:  # noqa: BLE001 - private file errors never reveal path or values
        raise NativeWorkerConfigError() from None
