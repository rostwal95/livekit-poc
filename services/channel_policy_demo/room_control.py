"""Closed parent-only native room control DTOs; no I/O or credentials on import.

Room/view/native and publisher capabilities are separate roles. An observation is
an as-of lifecycle receipt, never execution, current-result or playback authority.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, cast

from .wire import uuid_value

CONTROL_BYTES = 1024
OBSERVATION_BYTES = 4096
MAX_GENERATION = 1000000
ControlCode = Literal[
    "invalid_input",
    "invalid_state",
    "unauthorized",
    "conflict",
    "capacity",
    "unavailable",
    "outcome_unknown",
    "closed",
    "cleanup_incomplete",
    "recovery_required",
]
_CONTROL_CODES = frozenset(
    {
        "invalid_input",
        "invalid_state",
        "unauthorized",
        "conflict",
        "capacity",
        "unavailable",
        "outcome_unknown",
        "closed",
        "cleanup_incomplete",
        "recovery_required",
    }
)
RoomState = Literal["opening", "ready", "publication_unknown", "closing", "closed"]
RevocationState = Literal["revoked", "absent", "unpublished"]
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}", re.ASCII)
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", re.ASCII)
_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z", re.ASCII)


class RoomControlError(RuntimeError):
    def __init__(self, code: ControlCode = "unavailable") -> None:
        self.code: ControlCode = (
            code if type(code) is str and code in _CONTROL_CODES else "unavailable"
        )
        super().__init__(self.code)


def _need(value: bool, code: ControlCode = "invalid_input") -> None:
    if not value:
        raise RoomControlError(code)


def _text(value: object, pattern: re.Pattern[str]) -> str:
    _need(type(value) is str and pattern.fullmatch(value) is not None)
    return cast(str, value)


def _uuid(value: object) -> str:
    try:
        return uuid_value(cast(str, value))
    except Exception:  # noqa: BLE001 - original values stay private
        raise RoomControlError("invalid_input") from None


def _generation(value: object, *, zero: bool = True) -> str:
    result = _text(value, re.compile(r"0|[1-9][0-9]{0,6}", re.ASCII))
    _need((0 if zero else 1) <= int(result) <= MAX_GENERATION)
    return result


def _timestamp(value: object) -> str:
    result = _text(value, _TIME)
    try:
        _need(
            datetime.fromisoformat(result).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            == result
        )
    except (ValueError, OverflowError):
        raise RoomControlError("invalid_input") from None
    return result


def _fields(value: object, expected: set[str]) -> dict[str, object]:
    _need(type(value) is dict and set(value) == expected)
    return cast(dict[str, object], value)


@dataclass(frozen=True, slots=True)
class RoomPublisherCredential:
    value: str = field(repr=False)

    def __post_init__(self) -> None:
        _text(self.value, _TOKEN)


@dataclass(frozen=True, slots=True)
class RoomBinding:
    binding_id: str
    native_bearer: str = field(repr=False)
    room_id: str
    participant_id: str
    agent_id: str
    expires_at: str

    def __post_init__(self) -> None:
        _uuid(self.binding_id)
        _text(self.native_bearer, _TOKEN)
        for value in (self.room_id, self.participant_id, self.agent_id):
            _text(value, _ID)
        _need(self.participant_id != self.agent_id)
        _timestamp(self.expires_at)

    def to_wire(self) -> dict[str, object]:
        return {
            "bindingId": self.binding_id,
            "nativeBearer": self.native_bearer,
            "roomId": self.room_id,
            "participantId": self.participant_id,
            "agentId": self.agent_id,
            "expiresAt": self.expires_at,
        }


@dataclass(frozen=True, slots=True)
class RoomCommand:
    node_epoch: str
    generation: str
    open_id: str

    def __post_init__(self) -> None:
        _uuid(self.node_epoch)
        _generation(self.generation, zero=False)
        _uuid(self.open_id)

    def to_wire(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "nodeEpoch": self.node_epoch,
            "generation": self.generation,
            "openId": self.open_id,
        }


@dataclass(frozen=True, slots=True)
class RoomOpen:
    node_epoch: str
    expected_generation: str
    open_id: str
    binding: RoomBinding
    room_view_bearer: str = field(repr=False)

    def __post_init__(self) -> None:
        _uuid(self.node_epoch)
        _generation(self.expected_generation)
        _uuid(self.open_id)
        _need(type(self.binding) is RoomBinding)
        _text(self.room_view_bearer, _TOKEN)
        _need(self.room_view_bearer != self.binding.native_bearer)

    def to_wire(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "nodeEpoch": self.node_epoch,
            "expectedGeneration": self.expected_generation,
            "openId": self.open_id,
            "binding": self.binding.to_wire(),
            "roomViewBearer": self.room_view_bearer,
        }

    def command(self) -> RoomCommand:
        _need(int(self.expected_generation) < MAX_GENERATION, "capacity")
        return RoomCommand(self.node_epoch, str(int(self.expected_generation) + 1), self.open_id)


@dataclass(frozen=True, slots=True)
class RoomAttach:
    """Publisher-selected worker capability for exactly one published room."""

    node_epoch: str
    generation: str
    open_id: str
    binding_id: str
    prepare_bearer: str = field(repr=False)

    def __post_init__(self) -> None:
        RoomCommand(self.node_epoch, self.generation, self.open_id)
        _uuid(self.binding_id)
        _text(self.prepare_bearer, _TOKEN)

    def to_wire(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "nodeEpoch": self.node_epoch,
            "generation": self.generation,
            "openId": self.open_id,
            "bindingId": self.binding_id,
            "prepareBearer": self.prepare_bearer,
        }


@dataclass(frozen=True, slots=True)
class RoomAttachmentObservation:
    node_epoch: str
    generation: str
    open_id: str
    binding_id: str
    state: Literal["attached"] = "attached"

    def __post_init__(self) -> None:
        RoomCommand(self.node_epoch, self.generation, self.open_id)
        _uuid(self.binding_id)
        _need(type(self.state) is str and self.state == "attached")


def encode_room_attach(value: RoomAttach) -> bytes:
    try:
        _need(type(value) is RoomAttach)
        copied = RoomAttach(
            value.node_epoch,
            value.generation,
            value.open_id,
            value.binding_id,
            value.prepare_bearer,
        )
        raw = json.dumps(copied.to_wire(), separators=(",", ":"), allow_nan=False).encode()
        _need(len(raw) <= CONTROL_BYTES)
        return raw
    except Exception:  # noqa: BLE001 - bypassed/malformed DTO diagnostics stay private
        raise RoomControlError("invalid_input") from None


def parse_room_attachment(raw: bytes, *, request: RoomAttach) -> RoomAttachmentObservation:
    try:
        # Snapshot caller identity again; an ACK does not authorize retargeting.
        encode_room_attach(request)
        p = _fields(
            _decode(raw),
            {"schemaVersion", "nodeEpoch", "generation", "openId", "bindingId", "state"},
        )
        _need(type(p["schemaVersion"]) is int and p["schemaVersion"] == 1)
        result = RoomAttachmentObservation(
            _uuid(p["nodeEpoch"]),
            _generation(p["generation"], zero=False),
            _uuid(p["openId"]),
            _uuid(p["bindingId"]),
            cast(Literal["attached"], p["state"]),
        )
        _need(
            (result.node_epoch, result.generation, result.open_id, result.binding_id)
            == (request.node_epoch, request.generation, request.open_id, request.binding_id)
        )
        return result
    except Exception:  # noqa: BLE001 - reject private/contradictory/foreign ACKs without echo
        raise RoomControlError("invalid_state") from None


@dataclass(frozen=True, slots=True)
class RoomRecover:
    node_epoch: str
    expected_generation: str
    binding_id: str

    def __post_init__(self) -> None:
        _uuid(self.node_epoch)
        _generation(self.expected_generation)
        _uuid(self.binding_id)

    def to_wire(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "nodeEpoch": self.node_epoch,
            "expectedGeneration": self.expected_generation,
            "bindingId": self.binding_id,
        }


@dataclass(frozen=True, slots=True)
class RoomPublication:
    binding_id: str
    binding_digest: str
    published_at: str
    expires_at: str

    def __post_init__(self) -> None:
        _uuid(self.binding_id)
        _text(self.binding_digest, re.compile(r"[0-9a-f]{64}", re.ASCII))
        _timestamp(self.published_at)
        _timestamp(self.expires_at)
        _need(self.published_at <= self.expires_at)


@dataclass(frozen=True, slots=True)
class RoomRevocation:
    binding_id: str
    state: RevocationState
    revoked_at: str | None

    def __post_init__(self) -> None:
        _uuid(self.binding_id)
        _need(type(self.state) is str and self.state in {"revoked", "absent", "unpublished"})
        if self.state == "revoked":
            _timestamp(self.revoked_at)
        else:
            _need(self.revoked_at is None)


@dataclass(frozen=True, slots=True)
class RoomObservation:
    node_epoch: str
    generation: str
    open_id: str
    state: RoomState
    publication: RoomPublication | None
    revocation: RoomRevocation | None
    global_reader_drained: Literal[False] = False

    def __post_init__(self) -> None:
        RoomCommand(self.node_epoch, self.generation, self.open_id)
        _need(
            type(self.state) is str
            and self.state in {"opening", "ready", "publication_unknown", "closing", "closed"}
        )
        _need(self.publication is None or type(self.publication) is RoomPublication)
        _need(self.revocation is None or type(self.revocation) is RoomRevocation)
        _need(self.global_reader_drained is False)
        if self.state == "ready":
            _need(self.publication is not None and self.revocation is None)
        elif self.state in {"opening", "publication_unknown"}:
            _need(self.publication is None and self.revocation is None)
        elif self.state == "closed":
            _need(self.revocation is not None)
        if self.revocation is not None:
            _need(self.state in {"closing", "closed"})
            if self.revocation.state == "unpublished":
                _need(self.publication is None)
            if self.publication is not None:
                _need(self.revocation.binding_id == self.publication.binding_id)


@dataclass(frozen=True, slots=True)
class RoomRecoveryObservation:
    node_epoch: str
    generation: str
    binding_id: str
    revocation: RoomRevocation

    def __post_init__(self) -> None:
        _uuid(self.node_epoch)
        _generation(self.generation, zero=False)
        _uuid(self.binding_id)
        _need(
            type(self.revocation) is RoomRevocation
            and self.revocation.binding_id == self.binding_id
        )
        _need(self.revocation.state in {"revoked", "absent"})


def encode_room_control(value: RoomOpen | RoomCommand | RoomRecover) -> bytes:
    try:
        if type(value) is RoomOpen:
            b = value.binding
            _need(type(b) is RoomBinding)
            copied: RoomOpen | RoomCommand | RoomRecover = RoomOpen(
                value.node_epoch,
                value.expected_generation,
                value.open_id,
                RoomBinding(
                    b.binding_id,
                    b.native_bearer,
                    b.room_id,
                    b.participant_id,
                    b.agent_id,
                    b.expires_at,
                ),
                value.room_view_bearer,
            )
        elif type(value) is RoomCommand:
            copied = RoomCommand(value.node_epoch, value.generation, value.open_id)
        elif type(value) is RoomRecover:
            copied = RoomRecover(value.node_epoch, value.expected_generation, value.binding_id)
        else:
            raise RoomControlError("invalid_input")
        raw = json.dumps(
            copied.to_wire(), ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8", "strict")
        _need(len(raw) <= CONTROL_BYTES)
        return raw
    except Exception:  # noqa: BLE001 - incomplete or bypassed DTOs never reflect fields
        raise RoomControlError("invalid_input") from None


def _pairs(values: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in values:
        _need(key not in result)
        result[key] = value
    return result


def _constant(_: str) -> object:
    raise RoomControlError("invalid_state")


def _decode(raw: bytes) -> dict[str, object]:
    _need(type(raw) is bytes and 0 < len(raw) <= OBSERVATION_BYTES, "invalid_state")
    try:
        result: object = json.loads(
            raw.decode("utf-8", "strict"), object_pairs_hook=_pairs, parse_constant=_constant
        )
        _need(type(result) is dict, "invalid_state")
        return cast(dict[str, object], result)
    except (ValueError, UnicodeError, RecursionError):
        raise RoomControlError("invalid_state") from None


def _publication(value: object) -> RoomPublication | None:
    if value is None:
        return None
    p = _fields(value, {"bindingId", "bindingDigest", "publishedAt", "expiresAt"})
    return RoomPublication(
        _uuid(p["bindingId"]),
        cast(str, p["bindingDigest"]),
        _timestamp(p["publishedAt"]),
        _timestamp(p["expiresAt"]),
    )


def _revocation(value: object) -> RoomRevocation | None:
    if value is None:
        return None
    p = _fields(value, {"bindingId", "state", "revokedAt"})
    return RoomRevocation(
        _uuid(p["bindingId"]), cast(RevocationState, p["state"]), cast(str | None, p["revokedAt"])
    )


def parse_room_observation(
    raw: bytes, *, command: RoomCommand, binding: RoomBinding
) -> RoomObservation:
    try:
        _need(type(command) is RoomCommand and type(binding) is RoomBinding)
        p = _fields(
            _decode(raw),
            {
                "schemaVersion",
                "nodeEpoch",
                "generation",
                "openId",
                "state",
                "publication",
                "revocation",
                "globalReaderDrained",
            },
        )
        _need(type(p["schemaVersion"]) is int and p["schemaVersion"] == 1)
        result = RoomObservation(
            _uuid(p["nodeEpoch"]),
            _generation(p["generation"], zero=False),
            _uuid(p["openId"]),
            cast(RoomState, p["state"]),
            _publication(p["publication"]),
            _revocation(p["revocation"]),
            cast(Literal[False], p["globalReaderDrained"]),
        )
        _need(
            (result.node_epoch, result.generation, result.open_id)
            == (command.node_epoch, command.generation, command.open_id)
        )
        if result.publication is not None:
            _need(
                (result.publication.binding_id, result.publication.expires_at)
                == (binding.binding_id, binding.expires_at)
            )
        if result.revocation is not None:
            _need(result.revocation.binding_id == binding.binding_id)
        return result
    except Exception:  # noqa: BLE001 - dependency/data diagnostics never escape
        raise RoomControlError("invalid_state") from None


def parse_room_recovery(raw: bytes, *, request: RoomRecover) -> RoomRecoveryObservation:
    try:
        _need(type(request) is RoomRecover)
        p = _fields(
            _decode(raw),
            {"schemaVersion", "nodeEpoch", "generation", "bindingId", "state", "revocation"},
        )
        _need(
            type(p["schemaVersion"]) is int
            and p["schemaVersion"] == 1
            and p["state"] == "recovered"
        )
        revocation = _revocation(p["revocation"])
        _need(revocation is not None)
        result = RoomRecoveryObservation(
            _uuid(p["nodeEpoch"]),
            _generation(p["generation"], zero=False),
            _uuid(p["bindingId"]),
            cast(RoomRevocation, revocation),
        )
        _need(
            result.node_epoch == request.node_epoch
            and result.binding_id == request.binding_id
            and int(result.generation) == int(request.expected_generation) + 1
        )
        return result
    except Exception:  # noqa: BLE001 - same-request recovery remains explicit
        raise RoomControlError("invalid_state") from None


def parse_room_control_error(raw: bytes, status: int) -> RoomControlError:
    try:
        p = _fields(_decode(raw), {"schemaVersion", "status", "code"})
        _need(
            type(p["schemaVersion"]) is int
            and p["schemaVersion"] == 1
            and p["status"] == "unavailable"
        )
        allowed = {
            400: {"invalid_input"},
            401: {"unauthorized"},
            409: {"conflict", "recovery_required"},
            429: {"capacity"},
            503: {"closed", "unavailable", "outcome_unknown", "cleanup_incomplete"},
        }
        _need(type(p["code"]) is str and p["code"] in allowed[status])
        return RoomControlError(cast(ControlCode, p["code"]))
    except Exception:  # noqa: BLE001 - malformed operational response is not an ACK
        return RoomControlError("outcome_unknown")
