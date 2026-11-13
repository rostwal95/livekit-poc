"""Bounded data codec; parsing neither authenticates nor durably accepts an event."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import TypeAlias, cast

JsonValue: TypeAlias = bool | int | str | list["JsonValue"] | dict[str, "JsonValue"] | None
FrozenJson: TypeAlias = (
    bool | int | str | tuple["FrozenJson", ...] | Mapping[str, "FrozenJson"] | None
)

MAX_WIRE_BYTES = 32768
MAX_TEXT_BYTES = 4096
MAX_SAFE_INTEGER = 9007199254740991
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z", re.ASCII)
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z\Z", re.ASCII)
_COMMON = {"schemaVersion", "eventId", "providerScope", "conversationId", "receivedAt", "type"}
_OPTIONAL = {"accountScope", "caseId", "occurredAt", "causationId", "retryCount", "signature"}
_SPECS: dict[str, tuple[dict[str, str | tuple[str, ...]], dict[str, str | tuple[str, ...]]]] = {
    "text.received": (
        {
            "channel": ("web_chat", "sms", "voice_transcript"),
            "messageId": "id",
            "senderId": "id",
            "body": "text",
        },
        {"expectedCaseRevision": "revision", "replyToResponseId": "id"},
    ),
    "response.generated": ({"responseId": "id", "body": "text"}, {}),
    "playback.reported": (
        {
            "responseId": "id",
            "source": ("agent_sdk", "browser_client"),
            "state": ("started", "partial", "completed", "interrupted"),
        },
        {"playedText": "text"},
    ),
    "delivery.reported": (
        {
            "messageId": "id",
            "state": ("accepted_by_provider", "delivered", "failed", "unknown", "read_reported"),
        },
        {},
    ),
    "user.acknowledged": ({"responseId": "id", "messageId": "id"}, {}),
}


class ContractError(ValueError):
    """A fixed payload-free error code, with no raw dependency diagnostics."""

    def __init__(self, code: str = "InvalidEvent") -> None:
        self.code = code
        super().__init__(code)


def _text(value: object, maximum: int, *, empty: bool = False) -> str:
    if type(value) is not str or (not value and not empty) or len(value) > maximum:
        raise ContractError()
    text = value
    try:
        size = len(text.encode("utf-8", errors="strict"))
    except UnicodeError:
        raise ContractError() from None
    if size > maximum:
        raise ContractError()
    return text


def _identifier(value: object) -> str:
    text = _text(value, 128)
    if not _IDENTIFIER.fullmatch(text):
        raise ContractError()
    return text


def _timestamp(value: object) -> None:
    text = _text(value, 24)
    if not _TIMESTAMP.fullmatch(text):
        raise ContractError()
    try:
        datetime.fromisoformat(text)
    except ValueError:
        raise ContractError() from None


@dataclass(frozen=True, slots=True)
class ProviderScope:
    tenant_id: str
    provider: str
    provider_account_id: str

    def __post_init__(self) -> None:
        for value in (self.tenant_id, self.provider, self.provider_account_id):
            _identifier(value)

    def as_json(self) -> dict[str, JsonValue]:
        return {
            "tenantId": self.tenant_id,
            "provider": self.provider,
            "providerAccountId": self.provider_account_id,
        }


@dataclass(frozen=True, slots=True)
class AccountScope:
    tenant_id: str
    account_id: str

    def __post_init__(self) -> None:
        _identifier(self.tenant_id)
        _identifier(self.account_id)

    def as_json(self) -> dict[str, JsonValue]:
        return {"tenantId": self.tenant_id, "accountId": self.account_id}


@dataclass(frozen=True, slots=True)
class TrustedPrincipal:
    """Configuration from an authenticated adapter, never parsed from event JSON."""

    provider_scope: ProviderScope
    account_scope: AccountScope | None = None

    def __post_init__(self) -> None:
        if type(self.provider_scope) is not ProviderScope or (
            self.account_scope is not None and type(self.account_scope) is not AccountScope
        ):
            raise ContractError("AccessDenied")
        if (
            self.account_scope is not None
            and self.account_scope.tenant_id != self.provider_scope.tenant_id
        ):
            raise ContractError("AccessDenied")


def _freeze(value: JsonValue) -> FrozenJson:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class DecodedEvent:
    event: Mapping[str, FrozenJson]
    canonical: str
    identity: str
    wire_json: str


def _integer(text: str) -> int:
    if text == "-0" or len(text) > 16:
        raise ContractError()
    value = int(text)
    if not 0 <= value <= MAX_SAFE_INTEGER:
        raise ContractError()
    return value


def _noninteger(_: str) -> JsonValue:
    raise ContractError()


def _pairs(items: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in items:
        if key in result:
            raise ContractError()
        result[key] = value
    return result


def _tree(value: object, depth: int = 0, budget: list[int] | None = None) -> None:
    # Shared descendants are charged each time; a compact DAG cannot amplify work.
    if budget is None:
        budget = [256, MAX_WIRE_BYTES]
    budget[0] -= 1
    if depth > 8 or budget[0] < 0:
        raise ContractError()
    if type(value) is dict:
        if len(value) > 64:
            raise ContractError()
        for key, item in value.items():
            key_text = _text(key, 128)
            budget[1] -= len(key_text.encode("utf-8"))
            if budget[1] < 0:
                raise ContractError()
            _tree(item, depth + 1, budget)
    elif type(value) is list:
        raise ContractError()
    elif type(value) is str:
        text = _text(value, MAX_WIRE_BYTES, empty=True)
        budget[1] -= len(text.encode("utf-8"))
        if budget[1] < 0:
            raise ContractError()
    elif value is None or type(value) is bool:
        return
    elif type(value) is int:
        if not 0 <= value <= MAX_SAFE_INTEGER:
            raise ContractError()
    else:
        raise ContractError()


def _canonical(value: JsonValue) -> str:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def parse_event_json(raw: str, principal: TrustedPrincipal) -> DecodedEvent:
    """Validate data against separately trusted scope; no authentication/acceptance."""
    _text(raw, MAX_WIRE_BYTES)
    if type(principal) is not TrustedPrincipal:
        raise ContractError("AccessDenied")
    try:
        value = cast(
            JsonValue,
            json.loads(
                raw,
                object_pairs_hook=_pairs,
                parse_int=_integer,
                parse_float=_noninteger,
                parse_constant=_noninteger,
            ),
        )
    except (ValueError, RecursionError):
        raise ContractError() from None
    _tree(value)
    if not isinstance(value, dict):
        raise ContractError()
    if type(value.get("schemaVersion")) is not int:
        raise ContractError()
    if value["schemaVersion"] != 1:
        raise ContractError("UnsupportedEventVersion")
    variant = value.get("type")
    if not isinstance(variant, str) or variant not in _SPECS:
        raise ContractError()
    required, optional = _SPECS[variant]
    if not _COMMON.union(required).issubset(value) or set(value) - _COMMON - _OPTIONAL - set(
        required
    ) - set(optional):
        raise ContractError()
    for key in ("eventId", "conversationId", "caseId", "causationId"):
        if key in value:
            _identifier(value[key])
    _timestamp(value["receivedAt"])
    if "occurredAt" in value:
        _timestamp(value["occurredAt"])
    if "signature" in value:
        _text(value["signature"], 256)
    if "retryCount" in value and (
        type(value["retryCount"]) is not int or not 0 <= value["retryCount"] <= 1000000
    ):
        raise ContractError()
    provider = value["providerScope"]
    if not isinstance(provider, dict) or set(provider) != {
        "tenantId",
        "provider",
        "providerAccountId",
    }:
        raise ContractError()
    for item in provider.values():
        _identifier(item)
    if provider != principal.provider_scope.as_json():
        raise ContractError("AccessDenied")
    account = value.get("accountScope")
    if account is not None:
        if not isinstance(account, dict) or set(account) != {"tenantId", "accountId"}:
            raise ContractError()
        for item in account.values():
            _identifier(item)
        if principal.account_scope is None or account != principal.account_scope.as_json():
            raise ContractError("AccessDenied")
    elif "accountScope" in value:
        raise ContractError()
    if principal.account_scope is not None and account is None:
        raise ContractError("AssociationRequired")
    if "caseId" in value and account is None:
        raise ContractError("AssociationRequired")
    for key, specification in (required | optional).items():
        if key not in value:
            continue
        item = value[key]
        if specification == "id":
            _identifier(item)
        elif specification == "text":
            _text(item, MAX_TEXT_BYTES, empty=True)
        elif specification == "revision":
            if type(item) is not int or not 0 <= item <= MAX_SAFE_INTEGER:
                raise ContractError()
        elif not isinstance(item, str) or item not in specification:
            raise ContractError()
    semantic = {
        key: item
        for key, item in value.items()
        if key not in {"receivedAt", "retryCount", "signature"}
    }
    identity: JsonValue = [
        provider["tenantId"],
        provider["provider"],
        provider["providerAccountId"],
        value["eventId"],
    ]
    frozen = cast(Mapping[str, FrozenJson], _freeze(value))
    return DecodedEvent(frozen, _canonical(semantic), _canonical(identity), _canonical(value))


def produce_text_event(
    fields: Mapping[str, JsonValue], principal: TrustedPrincipal
) -> DecodedEvent:
    """Create a validated text event without acknowledging durable acceptance."""
    if type(fields) is not dict:
        raise ContractError()
    _tree(fields)
    if "type" in fields or "schemaVersion" in fields:
        raise ContractError()
    wire: dict[str, JsonValue] = dict(fields)
    wire.update({"schemaVersion": 1, "type": "text.received"})
    try:
        serialized = _canonical(wire)
    except (TypeError, ValueError, RecursionError, OverflowError):
        raise ContractError() from None
    return parse_event_json(serialized, principal)
