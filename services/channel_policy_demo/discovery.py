"""Pure bounded discovery observations for one application-configured route.

Discovery is an as-of observation, not an ACK, watermark, clock permission or
execution authority. The caller owns authentication, configured scope and I/O.
Prepared reads retain the existing raw accept frame; these constants add no body.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from typing import Literal, cast
from uuid import UUID

REQUEST_BYTES = 1024
PAGE_BYTES = 8192
PAGE_ITEMS = 16
PREPARED_FRAME_BYTES = 32768
PREPARED_FOUND_STATUS = 200
PREPARED_ABSENT_STATUS = 204

SourceBindingId = Literal["native", "sms"]
DispatchState = Literal["pending", "running", "dispatched", "blocked", "exhausted", "uncertain"]
DiscoveryCode = Literal["invalid_input"]
_ID = re.compile(r"[a-z][a-z0-9_-]{0,63}", re.ASCII)
_SEQUENCE = re.compile(r"[1-9][0-9]{0,18}", re.ASCII)
_UTC_MS = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z", re.ASCII)
_STATES = frozenset({"pending", "running", "dispatched", "blocked", "exhausted", "uncertain"})
_ITEM_FIELDS = {
    "receiptId",
    "operationKey",
    "acceptanceSequence",
    "sourceBindingId",
    "state",
    "possibleExternal",
    "externalReceiptId",
}
_PAGE_FIELDS = {
    "schemaVersion",
    "kind",
    "profileId",
    "scope",
    "caseId",
    "conversationId",
    "readCompletedAt",
    "items",
    "overflow",
    "nextCursor",
}


class DiscoveryError(ValueError):
    """Fixed diagnostics exclude received values and private dependency text."""

    def __init__(self) -> None:
        self.code: DiscoveryCode = "invalid_input"
        super().__init__(self.code)


def _require(condition: bool) -> None:
    if not condition:
        raise DiscoveryError()


def _fields(value: object, names: set[str]) -> dict[str, object]:
    if type(value) is not dict:
        raise DiscoveryError()
    result = cast(dict[object, object], value)
    if any(type(key) is not str for key in result) or set(result) != names:
        raise DiscoveryError()
    return cast(dict[str, object], value)


def _version(value: object) -> Literal[1]:
    if type(value) is not int or value != 1:
        raise DiscoveryError()
    return 1


def _identifier(value: object) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise DiscoveryError()
    return value


def _uuid(value: object) -> str:
    if type(value) is not str or len(value) != 36:
        raise DiscoveryError()
    try:
        parsed = UUID(value)
    except ValueError:
        raise DiscoveryError() from None
    _require(parsed.version == 4 and str(parsed) == value)
    return value


def _sequence(value: object) -> str:
    if (
        type(value) is not str
        or _SEQUENCE.fullmatch(value) is None
        or int(value) > 9223372036854775807
    ):
        raise DiscoveryError()
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise DiscoveryError()
    return value


def _source(value: object) -> SourceBindingId:
    if type(value) is not str or value not in {"native", "sms"}:
        raise DiscoveryError()
    return cast(SourceBindingId, value)


def _state(value: object) -> DispatchState:
    if type(value) is not str or value not in _STATES:
        raise DiscoveryError()
    return cast(DispatchState, value)


def _timestamp(value: object) -> str:
    if type(value) is not str or _UTC_MS.fullmatch(value) is None:
        raise DiscoveryError()
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise DiscoveryError() from None
    _require(parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z") == value)
    return value


def _kind(value: object) -> Literal["channel.policy_discovery"]:
    if type(value) is not str or value != "channel.policy_discovery":
        raise DiscoveryError()
    return "channel.policy_discovery"


def _optional_uuid(value: object) -> str | None:
    return None if value is None else _uuid(value)


def _optional_sequence(value: object) -> str | None:
    return None if value is None else _sequence(value)


def _pairs(values: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in values:
        if key in result:
            raise DiscoveryError()
        result[key] = value
    return result


def _nonfinite(_: str) -> object:
    raise DiscoveryError()


def _decode(raw: bytes, maximum: int) -> object:
    if type(raw) is not bytes or not 0 < len(raw) <= maximum:
        raise DiscoveryError()
    try:
        value: object = json.loads(
            raw.decode("utf-8", "strict"), object_pairs_hook=_pairs, parse_constant=_nonfinite
        )
    except (ValueError, UnicodeError, RecursionError):
        raise DiscoveryError() from None
    return value


def _encode(value: dict[str, object], maximum: int) -> bytes:
    try:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
            "utf-8", "strict"
        )
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise DiscoveryError() from None
    _require(0 < len(raw) <= maximum)
    return raw


@dataclass(frozen=True, slots=True)
class DiscoveryScope:
    tenant_id: str
    account_id: str

    def __post_init__(self) -> None:
        _identifier(self.tenant_id)
        _identifier(self.account_id)


@dataclass(frozen=True, slots=True)
class DiscoveryRequest:
    schema_version: Literal[1] = 1

    def __post_init__(self) -> None:
        _version(self.schema_version)


@dataclass(frozen=True, slots=True)
class DiscoveryItem:
    receipt_id: str
    operation_key: str
    acceptance_sequence: str
    source_binding_id: SourceBindingId
    state: DispatchState
    possible_external: bool
    external_receipt_id: str | None

    def __post_init__(self) -> None:
        _uuid(self.receipt_id)
        _uuid(self.operation_key)
        _sequence(self.acceptance_sequence)
        _source(self.source_binding_id)
        _state(self.state)
        _boolean(self.possible_external)
        _optional_uuid(self.external_receipt_id)
        if self.state == "dispatched":
            _require(self.possible_external is True and self.external_receipt_id is not None)
        else:
            _require(self.external_receipt_id is None)


def _copy_scope(value: object) -> DiscoveryScope:
    if type(value) is not DiscoveryScope:
        raise DiscoveryError()
    try:
        return DiscoveryScope(value.tenant_id, value.account_id)
    except AttributeError:
        raise DiscoveryError() from None


def _copy_item(value: object) -> DiscoveryItem:
    if type(value) is not DiscoveryItem:
        raise DiscoveryError()
    try:
        return DiscoveryItem(
            value.receipt_id,
            value.operation_key,
            value.acceptance_sequence,
            value.source_binding_id,
            value.state,
            value.possible_external,
            value.external_receipt_id,
        )
    except AttributeError:
        raise DiscoveryError() from None


def _copy_items(value: object) -> tuple[DiscoveryItem, ...]:
    if type(value) not in (tuple, list):
        raise DiscoveryError()
    values = cast(tuple[object, ...] | list[object], value)
    _require(len(values) <= PAGE_ITEMS)
    result = tuple(_copy_item(item) for item in values)
    _require(
        all(
            int(first.acceptance_sequence) < int(second.acceptance_sequence)
            for first, second in pairwise(result)
        )
    )
    _require(len({item.receipt_id for item in result}) == len(result))
    _require(len({item.operation_key for item in result}) == len(result))
    work_ids = [item.external_receipt_id for item in result if item.external_receipt_id is not None]
    _require(len(set(work_ids)) == len(work_ids))
    return result


@dataclass(frozen=True, slots=True)
class DiscoveryPage:
    profile_id: str
    scope: DiscoveryScope
    case_id: str
    conversation_id: str
    read_completed_at: str
    items: tuple[DiscoveryItem, ...]
    overflow: bool
    next_cursor: str | None
    schema_version: Literal[1] = 1
    kind: Literal["channel.policy_discovery"] = "channel.policy_discovery"

    def __post_init__(self) -> None:
        _version(self.schema_version)
        _kind(self.kind)
        _uuid(self.profile_id)
        _identifier(self.case_id)
        _identifier(self.conversation_id)
        _timestamp(self.read_completed_at)
        _boolean(self.overflow)
        _optional_sequence(self.next_cursor)
        object.__setattr__(self, "scope", _copy_scope(self.scope))
        object.__setattr__(self, "items", _copy_items(self.items))
        if self.overflow:
            _require(
                len(self.items) == PAGE_ITEMS
                and self.next_cursor == self.items[-1].acceptance_sequence
            )
        else:
            _require(self.next_cursor is None)


def _item_wire(item: DiscoveryItem) -> dict[str, object]:
    return {
        "receiptId": item.receipt_id,
        "operationKey": item.operation_key,
        "acceptanceSequence": item.acceptance_sequence,
        "sourceBindingId": item.source_binding_id,
        "state": item.state,
        "possibleExternal": item.possible_external,
        "externalReceiptId": item.external_receipt_id,
    }


def _parse_item(value: object) -> DiscoveryItem:
    raw = _fields(value, _ITEM_FIELDS)
    return DiscoveryItem(
        _uuid(raw["receiptId"]),
        _uuid(raw["operationKey"]),
        _sequence(raw["acceptanceSequence"]),
        _source(raw["sourceBindingId"]),
        _state(raw["state"]),
        _boolean(raw["possibleExternal"]),
        _optional_uuid(raw["externalReceiptId"]),
    )


def parse_discovery_request(raw: bytes) -> DiscoveryRequest:
    """Only schemaVersion is accepted; callers configure the route and scope."""
    value = _fields(_decode(raw, REQUEST_BYTES), {"schemaVersion"})
    return DiscoveryRequest(_version(value["schemaVersion"]))


def encode_discovery_request(value: DiscoveryRequest) -> bytes:
    if type(value) is not DiscoveryRequest:
        raise DiscoveryError()
    try:
        version = _version(value.schema_version)
    except AttributeError:
        raise DiscoveryError() from None
    return _encode({"schemaVersion": version}, REQUEST_BYTES)


def parse_discovery_page(raw: bytes) -> DiscoveryPage:
    value = _fields(_decode(raw, PAGE_BYTES), _PAGE_FIELDS)
    scope = _fields(value["scope"], {"tenantId", "accountId"})
    items = value["items"]
    if type(items) is not list or len(items) > PAGE_ITEMS:
        raise DiscoveryError()
    return DiscoveryPage(
        _uuid(value["profileId"]),
        DiscoveryScope(_identifier(scope["tenantId"]), _identifier(scope["accountId"])),
        _identifier(value["caseId"]),
        _identifier(value["conversationId"]),
        _timestamp(value["readCompletedAt"]),
        tuple(_parse_item(item) for item in items),
        _boolean(value["overflow"]),
        _optional_sequence(value["nextCursor"]),
        _version(value["schemaVersion"]),
        _kind(value["kind"]),
    )


def encode_discovery_page(value: DiscoveryPage) -> bytes:
    """Revalidate a fresh snapshot, including records bypass-mutated by a caller."""
    if type(value) is not DiscoveryPage:
        raise DiscoveryError()
    try:
        page = DiscoveryPage(
            value.profile_id,
            value.scope,
            value.case_id,
            value.conversation_id,
            value.read_completed_at,
            value.items,
            value.overflow,
            value.next_cursor,
            value.schema_version,
            value.kind,
        )
    except AttributeError:
        raise DiscoveryError() from None
    return _encode(
        {
            "schemaVersion": page.schema_version,
            "kind": page.kind,
            "profileId": page.profile_id,
            "scope": {"tenantId": page.scope.tenant_id, "accountId": page.scope.account_id},
            "caseId": page.case_id,
            "conversationId": page.conversation_id,
            "readCompletedAt": page.read_completed_at,
            "items": [_item_wire(item) for item in page.items],
            "overflow": page.overflow,
            "nextCursor": page.next_cursor,
        },
        PAGE_BYTES,
    )
