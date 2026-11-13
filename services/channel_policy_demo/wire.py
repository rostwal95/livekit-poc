"""Strict P2 prepared-input wire for the explicit local origin bridge.

This is application composition, not account authentication or a work ledger.
Imports are inert; original message bytes remain in P2 and never select authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Literal, cast
from uuid import UUID

FRAME_BYTES = 32768
LOOKUP_BYTES = 1024
BODY_BYTES = 4096
P3_REVISION_MAX = 1000000
WireCode = Literal["InvalidCommand", "AccessDenied", "IdentityConflict"]
_CODES = frozenset({"InvalidCommand", "AccessDenied", "IdentityConflict"})
_P2_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", re.ASCII)
_P3_ID = re.compile(r"[a-z][a-z0-9_-]{0,63}", re.ASCII)
_SHA = re.compile(r"[0-9a-f]{64}", re.ASCII)


class OriginWireError(ValueError):
    """Finite safe diagnostics; never include received values or exception text."""

    def __init__(self, code: WireCode = "InvalidCommand") -> None:
        self.code: WireCode = code if type(code) is str and code in _CODES else "InvalidCommand"
        super().__init__(self.code)


def _fields(value: object, names: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != names:
        raise OriginWireError()
    return cast(dict[str, object], value)


def channel_identifier(value: object) -> str:
    if type(value) is not str or _P2_ID.fullmatch(value) is None:
        raise OriginWireError()
    return value


def uuid_value(value: object) -> str:
    if type(value) is not str or len(value) != 36:
        raise OriginWireError()
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError):
        raise OriginWireError() from None
    if parsed.version != 4 or str(parsed) != value:
        raise OriginWireError()
    return value


def _sha(value: object) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        raise OriginWireError()
    return value


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise OriginWireError()
        result[key] = value
    return result


def _invalid_number(_: str) -> object:
    raise OriginWireError()


def decode_object(raw: bytes, maximum: int = FRAME_BYTES) -> dict[str, object]:
    if type(raw) is not bytes or not 0 < len(raw) <= maximum:
        raise OriginWireError()
    try:
        value: object = json.loads(
            raw.decode("utf-8", "strict"),
            object_pairs_hook=_pairs,
            parse_constant=_invalid_number,
        )
    except (ValueError, UnicodeError, RecursionError):
        raise OriginWireError() from None
    if type(value) is not dict:
        raise OriginWireError()
    return cast(dict[str, object], value)


def json_text(value: object) -> str:
    """Match JSON.stringify ordering/Unicode for the closed primitive P2 shape."""
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        raise OriginWireError() from None


@dataclass(frozen=True, slots=True)
class ChannelAccountScope:
    tenant_id: str
    account_id: str

    def to_wire(self) -> dict[str, str]:
        return {"tenantId": self.tenant_id, "accountId": self.account_id}


def account_scope(value: object) -> ChannelAccountScope:
    raw = _fields(value, {"tenantId", "accountId"})
    return ChannelAccountScope(
        channel_identifier(raw["tenantId"]), channel_identifier(raw["accountId"])
    )


@dataclass(frozen=True, slots=True)
class ChannelOperationLookup:
    operation_key: str
    scope: ChannelAccountScope
    payload_sha256: str

    def to_wire(self) -> dict[str, object]:
        return {
            "operationKey": self.operation_key,
            "scope": self.scope.to_wire(),
            "payloadDigest": self.payload_sha256,
        }


@dataclass(frozen=True, slots=True)
class PreparedChannelInput:
    operation_key: str
    scope: ChannelAccountScope
    case_id: str
    case_revision: str
    conversation_id: str
    input_receipt_id: str
    event_id: str
    message_id: str
    sender_id: str
    body: str = field(repr=False)
    canonical_payload: str = field(repr=False)
    payload_sha256: str
    payload_byte_length: int

    def to_submission_wire(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "kind": "investigation",
            "operationKey": self.operation_key,
            "scope": self.scope.to_wire(),
            "caseId": self.case_id,
            "caseRevision": self.case_revision,
            "conversationId": self.conversation_id,
            "message": {
                "receiptId": self.input_receipt_id,
                "eventId": self.event_id,
                "messageId": self.message_id,
                "senderId": self.sender_id,
                "body": self.body,
            },
        }

    def lookup(self) -> ChannelOperationLookup:
        return ChannelOperationLookup(self.operation_key, self.scope, self.payload_sha256)


def parse_prepared_payload(payload: object, digest: object) -> PreparedChannelInput:
    if type(payload) is not str:
        raise OriginWireError()
    expected_sha = _sha(digest)
    try:
        encoded = payload.encode("utf-8", "strict")
    except UnicodeError:
        raise OriginWireError() from None
    raw = _fields(
        decode_object(encoded),
        {
            "schemaVersion",
            "kind",
            "operationKey",
            "scope",
            "caseId",
            "caseRevision",
            "conversationId",
            "message",
        },
    )
    message = _fields(raw["message"], {"receiptId", "eventId", "messageId", "senderId", "body"})
    if (
        type(raw["schemaVersion"]) is not int
        or raw["schemaVersion"] != 1
        or raw["kind"] != "investigation"
    ):
        raise OriginWireError()
    revision = raw["caseRevision"]
    if (
        type(revision) is not str
        or re.fullmatch(r"[1-9][0-9]{0,18}", revision, re.ASCII) is None
        or int(revision) > 9223372036854775807
    ):
        raise OriginWireError()
    body = message["body"]
    if type(body) is not str or len(body) > BODY_BYTES:
        raise OriginWireError()
    try:
        if len(body.encode("utf-8", "strict")) > BODY_BYTES:
            raise OriginWireError()
    except UnicodeError:
        raise OriginWireError() from None
    value = PreparedChannelInput(
        uuid_value(raw["operationKey"]),
        account_scope(raw["scope"]),
        channel_identifier(raw["caseId"]),
        revision,
        channel_identifier(raw["conversationId"]),
        uuid_value(message["receiptId"]),
        channel_identifier(message["eventId"]),
        channel_identifier(message["messageId"]),
        channel_identifier(message["senderId"]),
        body,
        payload,
        expected_sha,
        len(encoded),
    )
    if (
        json_text(value.to_submission_wire()) != payload
        or hashlib.sha256(encoded).hexdigest() != expected_sha
    ):
        raise OriginWireError("IdentityConflict")
    return value


def parse_accept_frame(raw: bytes) -> PreparedChannelInput:
    frame = _fields(decode_object(raw), {"schemaVersion", "canonicalPayload", "payloadDigest"})
    if type(frame["schemaVersion"]) is not int or frame["schemaVersion"] != 1:
        raise OriginWireError()
    return parse_prepared_payload(frame["canonicalPayload"], frame["payloadDigest"])


def parse_lookup_frame(raw: bytes) -> ChannelOperationLookup:
    frame = _fields(decode_object(raw, LOOKUP_BYTES), {"operationKey", "scope", "payloadDigest"})
    return ChannelOperationLookup(
        uuid_value(frame["operationKey"]),
        account_scope(frame["scope"]),
        _sha(frame["payloadDigest"]),
    )


def parse_profile_frame(raw: bytes) -> str:
    frame = _fields(decode_object(raw, 128), {"schemaVersion", "profileId"})
    if type(frame["schemaVersion"]) is not int or frame["schemaVersion"] != 1:
        raise OriginWireError()
    return uuid_value(frame["profileId"])


def require_p3_compatible(value: PreparedChannelInput) -> int:
    """Validate only mapped fields; P2-only message identities are never narrowed."""
    if type(value) is not PreparedChannelInput or type(value.scope) is not ChannelAccountScope:
        raise OriginWireError()
    if any(
        type(item) is not str or _P3_ID.fullmatch(item) is None
        for item in (
            value.scope.tenant_id,
            value.scope.account_id,
            value.case_id,
            value.conversation_id,
        )
    ):
        raise OriginWireError()
    raw_revision = value.case_revision
    if (
        type(raw_revision) is not str
        or re.fullmatch(r"[1-9][0-9]{0,18}", raw_revision, re.ASCII) is None
    ):
        raise OriginWireError()
    revision = int(raw_revision)
    if not 1 <= revision <= P3_REVISION_MAX:
        raise OriginWireError()
    return revision
