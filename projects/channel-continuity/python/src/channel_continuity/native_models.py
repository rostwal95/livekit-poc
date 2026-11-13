"""Immutable native binding/input values; SDK transport labels grant no account authority."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal, Protocol
from uuid import UUID

from .codec import AccountScope, ProviderScope

NativeCode = Literal[
    "invalid_input",
    "forbidden",
    "idempotency_conflict",
    "capacity_exhausted",
    "dependency_unavailable",
    "acknowledgement_unknown",
    "closed",
]
CODES = frozenset(
    (
        "invalid_input",
        "forbidden",
        "idempotency_conflict",
        "capacity_exhausted",
        "dependency_unavailable",
        "acknowledgement_unknown",
        "closed",
    )
)


class NativeError(ValueError):
    def __init__(self, code: NativeCode = "invalid_input") -> None:
        self.code = code
        super().__init__(code)


def identifier(value: object) -> str:
    import re

    if type(value) is not str or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value, flags=re.ASCII
    ):
        raise NativeError()
    return value


def uuid(value: object) -> str:
    if type(value) is not str:
        raise NativeError()
    try:
        parsed = UUID(value)
        if parsed.version != 4 or str(parsed) != value:
            raise ValueError()
    except ValueError:
        raise NativeError() from None
    return value


def text(value: object, maximum: int = 2048) -> str:
    if type(value) is not str or not value:
        raise NativeError()
    try:
        if len(value.encode("utf-8")) > maximum:
            raise NativeError()
    except UnicodeError:
        raise NativeError() from None
    return value


def fields(value: object, names: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != names:
        raise NativeError()
    return value.copy()


def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise NativeError()
        result[key] = value
    return result


def decode(raw: bytes, maximum: int) -> dict[str, object]:
    if type(raw) is not bytes or not 1 <= len(raw) <= maximum:
        raise NativeError()
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique,
            parse_constant=lambda _: (_ for _ in ()).throw(NativeError()),
        )
        if type(value) is not dict:
            raise NativeError()
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise NativeError() from None


@dataclass(frozen=True, slots=True)
class NativeBinding:
    binding_id: str
    provider_scope: ProviderScope
    account_scope: AccountScope
    case_id: str
    conversation_id: str
    room_id: str
    participant_id: str
    agent_id: str

    def __post_init__(self) -> None:
        uuid(self.binding_id)
        if (
            type(self.provider_scope) is not ProviderScope
            or type(self.account_scope) is not AccountScope
            or self.provider_scope.provider != "livekit"
            or self.provider_scope.tenant_id != self.account_scope.tenant_id
        ):
            raise NativeError("forbidden")
        for value in (
            self.case_id,
            self.conversation_id,
            self.room_id,
            self.participant_id,
            self.agent_id,
        ):
            identifier(value)


@dataclass(frozen=True, slots=True)
class NativeInput:
    input_id: str
    channel: Literal["web_chat", "voice_transcript"]
    body: str
    room_id: str
    participant_id: str

    def __post_init__(self) -> None:
        uuid(self.input_id)
        text(self.body)
        identifier(self.room_id)
        identifier(self.participant_id)
        if type(self.channel) is not str or self.channel not in ("web_chat", "voice_transcript"):
            raise NativeError()

    def payload(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "inputId": self.input_id,
            "channel": self.channel,
            "body": self.body,
            "roomId": self.room_id,
            "participantId": self.participant_id,
        }


@dataclass(frozen=True, slots=True)
class NativeAck:
    binding_id: str
    input_id: str
    channel: Literal["web_chat", "voice_transcript"]
    status: Literal["accepted", "replayed", "unknown", "rejected"]
    receipt_id: str | None = None
    operation_key: str | None = None
    acceptance_sequence: str | None = None
    code: NativeCode | None = None

    def __post_init__(self) -> None:
        uuid(self.binding_id)
        uuid(self.input_id)
        if type(self.channel) is not str or self.channel not in ("web_chat", "voice_transcript"):
            raise NativeError()
        if type(self.status) is not str or (self.code is not None and type(self.code) is not str):
            raise NativeError()
        if self.status in ("accepted", "replayed"):
            uuid(self.receipt_id)
            uuid(self.operation_key)
            if (
                type(self.acceptance_sequence) is not str
                or not 1 <= len(self.acceptance_sequence) <= 19
                or not self.acceptance_sequence.isascii()
                or not self.acceptance_sequence.isdecimal()
                or self.acceptance_sequence.startswith("0")
                or int(self.acceptance_sequence) > 9223372036854775807
                or self.code is not None
            ):
                raise NativeError()
        elif self.status in ("unknown", "rejected"):
            if (
                self.receipt_id is not None
                or self.operation_key is not None
                or self.acceptance_sequence is not None
                or self.code not in CODES
                or (self.status == "unknown") != (self.code == "acknowledgement_unknown")
            ):
                raise NativeError()
        else:
            raise NativeError()

    def payload(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "bindingId": self.binding_id,
            "inputId": self.input_id,
            "channel": self.channel,
            "status": self.status,
            "receiptId": self.receipt_id,
            "operationKey": self.operation_key,
            "acceptanceSequence": self.acceptance_sequence,
            "code": self.code,
        }


def ack_from(value: object, binding: NativeBinding, input: NativeInput) -> NativeAck:
    v = fields(
        value,
        {
            "schemaVersion",
            "bindingId",
            "inputId",
            "channel",
            "status",
            "receiptId",
            "operationKey",
            "acceptanceSequence",
            "code",
        },
    )
    if (
        type(v["schemaVersion"]) is not int
        or v["schemaVersion"] != 1
        or v["bindingId"] != binding.binding_id
        or v["inputId"] != input.input_id
        or v["channel"] != input.channel
    ):
        raise NativeError()
    from typing import cast

    return NativeAck(
        binding.binding_id,
        input.input_id,
        input.channel,
        cast(Literal["accepted", "replayed", "unknown", "rejected"], v["status"]),
        cast(str | None, v["receiptId"]),
        cast(str | None, v["operationKey"]),
        cast(str | None, v["acceptanceSequence"]),
        cast(NativeCode | None, v["code"]),
    )


class NativeIntakePort(Protocol):
    async def accept(self, input: NativeInput) -> NativeAck: ...
    async def aclose(self) -> None: ...


@dataclass(frozen=True, slots=True)
class CommittedTranscript:
    input_id: str
    body: str
    request_id: str

    def __post_init__(self) -> None:
        uuid(self.input_id)
        text(self.body)
        identifier(self.request_id)


class NativeRecognizer(Protocol):
    def pending_work(self) -> int: ...
    def begin_turn(self, input_id: str) -> None: ...
    def final_snapshot(self, input_id: str) -> CommittedTranscript | None: ...
    def end_turn(self, input_id: str) -> None: ...


@dataclass(frozen=True, slots=True)
class NativeEndpoint:
    host: Literal["127.0.0.1"]
    port: int

    def __post_init__(self) -> None:
        if (
            type(self.host) is not str
            or self.host != "127.0.0.1"
            or type(self.port) is not int
            or not 1 <= self.port <= 65535
        ):
            raise NativeError()


@dataclass(frozen=True, slots=True)
class NativeCredential:
    value: str = field(repr=False)

    def __post_init__(self) -> None:
        import re

        if type(self.value) is not str or not re.fullmatch(
            r"[A-Za-z0-9_-]{32,128}", self.value, flags=re.ASCII
        ):
            raise NativeError("forbidden")
