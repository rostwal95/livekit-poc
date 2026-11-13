"""Closed current-result observations; parsing grants no applicability or authority.

The producer authenticates the current native grant and validates public P3
applicability, stored origin and delivery joins before choosing ``current``.
This codec only validates/copies the supplied observation. Empty states contain
no result bytes; operational failures use a separate finite HTTP error boundary.
P1's exact canonical base64 body stays opaque, including non-UTF-8 bytes.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, cast
from uuid import UUID

from .discovery import DiscoveryScope

CURRENT_RESULT_REQUEST_BYTES = 1024
CURRENT_RESULT_BYTES = 32768
RESULT_INTENT_BYTES = 16384
RESULT_BODY_BYTES = 8192
RESULT_BODY_BASE64_CHARACTERS = 10924
CurrentResultState = Literal["no_delivery", "not_applicable", "current"]
_ID = re.compile(r"[a-z][a-z0-9_-]{0,63}", re.ASCII)
_REVISION = re.compile(r"(?:0|[1-9][0-9]{0,18})", re.ASCII)
_SHA = re.compile(r"[0-9a-f]{64}", re.ASCII)
_UTC_MS = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z", re.ASCII)
_INTENT_FIELDS = {
    "delivery_id",
    "scope",
    "work_id",
    "attempt_id",
    "result_sha256",
    "receiver_id",
    "recipient_id",
    "body",
    "prepared_at_ms",
}
_RECEIPT_FIELDS = {
    "delivery_id",
    "receipt_id",
    "receiver_id",
    "recipient_id",
    "result_sha256",
    "accepted_at_ms",
}
_OBSERVATION_FIELDS = {
    "schemaVersion",
    "kind",
    "profileId",
    "scope",
    "caseId",
    "conversationId",
    "readCompletedAt",
    "state",
    "result",
}


class CurrentResultError(ValueError):
    """Finite diagnostics exclude result bytes, tokens and dependency messages."""

    def __init__(self) -> None:
        self.code: Literal["invalid_input"] = "invalid_input"
        super().__init__(self.code)


def _need(condition: bool) -> None:
    if not condition:
        raise CurrentResultError()


def _fields(value: object, names: set[str]) -> dict[str, object]:
    _need(type(value) is dict)
    result = cast(dict[object, object], value)
    _need(all(type(key) is str for key in result) and set(result) == names)
    return cast(dict[str, object], result)


def _version(value: object) -> None:
    _need(type(value) is int and value == 1)


def _identifier(value: object) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise CurrentResultError()
    return value


def _uuid(value: object) -> str:
    if type(value) is not str or len(value) != 36:
        raise CurrentResultError()
    try:
        parsed = UUID(value)
    except ValueError:
        raise CurrentResultError() from None
    _need(parsed.version == 4 and str(parsed) == value)
    return value


def _digest(value: object) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        raise CurrentResultError()
    return value


def _milliseconds(value: object) -> int:
    if type(value) is not int or not 0 <= value <= 4102444800000:
        raise CurrentResultError()
    return value


def _revision(value: object) -> str:
    if (
        type(value) is not str
        or _REVISION.fullmatch(value) is None
        or int(value) > 9223372036854775807
    ):
        raise CurrentResultError()
    return value


def _timestamp(value: object) -> str:
    if type(value) is not str or _UTC_MS.fullmatch(value) is None:
        raise CurrentResultError()
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise CurrentResultError() from None
    _need(parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z") == value)
    return value


def _scope(value: object) -> DiscoveryScope:
    if type(value) is not DiscoveryScope:
        raise CurrentResultError()
    try:
        return DiscoveryScope(_identifier(value.tenant_id), _identifier(value.account_id))
    except AttributeError:
        raise CurrentResultError() from None


def _body(value: object, expected_sha: str) -> str:
    if type(value) is not str or not 1 <= len(value) <= RESULT_BODY_BASE64_CHARACTERS:
        raise CurrentResultError()
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise CurrentResultError() from None
    _need(1 <= len(decoded) <= RESULT_BODY_BYTES)
    _need(base64.b64encode(decoded).decode("ascii") == value)
    _need(hashlib.sha256(decoded).hexdigest() == _digest(expected_sha))
    return value


@dataclass(frozen=True, slots=True)
class CurrentResultRequest:
    schema_version: Literal[1] = 1

    def __post_init__(self) -> None:
        _version(self.schema_version)


@dataclass(frozen=True, slots=True)
class CurrentResultIntent:
    delivery_id: str
    scope: DiscoveryScope
    work_id: str
    attempt_id: str
    result_sha256: str
    receiver_id: str
    recipient_id: str
    body: str = field(repr=False)
    prepared_at_ms: int

    def __post_init__(self) -> None:
        for value in (self.delivery_id, self.work_id, self.attempt_id, self.receiver_id):
            _uuid(value)
        _identifier(self.recipient_id)
        _digest(self.result_sha256)
        _body(self.body, self.result_sha256)
        _milliseconds(self.prepared_at_ms)
        object.__setattr__(self, "scope", _scope(self.scope))
        _need(len(_json(_intent_wire(self))) <= RESULT_INTENT_BYTES)


@dataclass(frozen=True, slots=True)
class CurrentResultReceipt:
    delivery_id: str
    receipt_id: str
    receiver_id: str
    recipient_id: str
    result_sha256: str
    accepted_at_ms: int

    def __post_init__(self) -> None:
        for value in (self.delivery_id, self.receipt_id, self.receiver_id):
            _uuid(value)
        _identifier(self.recipient_id)
        _digest(self.result_sha256)
        _milliseconds(self.accepted_at_ms)


@dataclass(frozen=True, slots=True)
class CurrentResultCase:
    source: Literal["p1_public_v4"]
    revision: str

    def __post_init__(self) -> None:
        _need(type(self.source) is str and self.source == "p1_public_v4")
        _revision(self.revision)


@dataclass(frozen=True, slots=True)
class CurrentResultObserved:
    p2_observed_at: str
    case_observed_at: str
    disclosure_admitted_at: str
    atomic: Literal[False] = False

    def __post_init__(self) -> None:
        _timestamp(self.p2_observed_at)
        _timestamp(self.case_observed_at)
        _timestamp(self.disclosure_admitted_at)
        _need(type(self.atomic) is bool and self.atomic is False)


def _intent(value: object) -> CurrentResultIntent:
    if type(value) is not CurrentResultIntent:
        raise CurrentResultError()
    try:
        return CurrentResultIntent(
            value.delivery_id,
            value.scope,
            value.work_id,
            value.attempt_id,
            value.result_sha256,
            value.receiver_id,
            value.recipient_id,
            value.body,
            value.prepared_at_ms,
        )
    except AttributeError:
        raise CurrentResultError() from None


def _receipt(value: object) -> CurrentResultReceipt:
    if type(value) is not CurrentResultReceipt:
        raise CurrentResultError()
    try:
        return CurrentResultReceipt(
            value.delivery_id,
            value.receipt_id,
            value.receiver_id,
            value.recipient_id,
            value.result_sha256,
            value.accepted_at_ms,
        )
    except AttributeError:
        raise CurrentResultError() from None


def _case(value: object) -> CurrentResultCase:
    if type(value) is not CurrentResultCase:
        raise CurrentResultError()
    try:
        return CurrentResultCase(value.source, value.revision)
    except AttributeError:
        raise CurrentResultError() from None


def _observed(value: object) -> CurrentResultObserved:
    if type(value) is not CurrentResultObserved:
        raise CurrentResultError()
    try:
        return CurrentResultObserved(
            value.p2_observed_at, value.case_observed_at, value.disclosure_admitted_at, value.atomic
        )
    except AttributeError:
        raise CurrentResultError() from None


@dataclass(frozen=True, slots=True)
class CurrentResultProjection:
    input_receipt_id: str
    operation_key: str
    intent: CurrentResultIntent
    receipt: CurrentResultReceipt
    case: CurrentResultCase
    observed: CurrentResultObserved

    def __post_init__(self) -> None:
        _uuid(self.input_receipt_id)
        _uuid(self.operation_key)
        object.__setattr__(self, "intent", _intent(self.intent))
        object.__setattr__(self, "receipt", _receipt(self.receipt))
        object.__setattr__(self, "case", _case(self.case))
        object.__setattr__(self, "observed", _observed(self.observed))
        _need(
            (
                self.intent.delivery_id,
                self.intent.receiver_id,
                self.intent.recipient_id,
                self.intent.result_sha256,
            )
            == (
                self.receipt.delivery_id,
                self.receipt.receiver_id,
                self.receipt.recipient_id,
                self.receipt.result_sha256,
            )
        )


def _projection(value: object) -> CurrentResultProjection:
    if type(value) is not CurrentResultProjection:
        raise CurrentResultError()
    try:
        return CurrentResultProjection(
            value.input_receipt_id,
            value.operation_key,
            value.intent,
            value.receipt,
            value.case,
            value.observed,
        )
    except AttributeError:
        raise CurrentResultError() from None


@dataclass(frozen=True, slots=True)
class CurrentResultObservation:
    profile_id: str
    scope: DiscoveryScope
    case_id: str
    conversation_id: str
    read_completed_at: str
    state: CurrentResultState
    result: CurrentResultProjection | None
    schema_version: Literal[1] = 1
    kind: Literal["channel.policy_current_result"] = "channel.policy_current_result"

    def __post_init__(self) -> None:
        _version(self.schema_version)
        _need(type(self.kind) is str and self.kind == "channel.policy_current_result")
        _uuid(self.profile_id)
        _identifier(self.case_id)
        _identifier(self.conversation_id)
        _timestamp(self.read_completed_at)
        _need(
            type(self.state) is str and self.state in {"no_delivery", "not_applicable", "current"}
        )
        object.__setattr__(self, "scope", _scope(self.scope))
        if self.state == "current":
            result = _projection(self.result)
            _need(result.intent.scope == self.scope)
            object.__setattr__(self, "result", result)
        else:
            _need(self.result is None)


def _pairs(values: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in values:
        _need(key not in result)
        result[key] = value
    return result


def _nonfinite(_: str) -> object:
    raise CurrentResultError()


def _decode(raw: bytes, maximum: int) -> object:
    if type(raw) is not bytes or not 0 < len(raw) <= maximum:
        raise CurrentResultError()
    try:
        return json.loads(
            raw.decode("utf-8", "strict"), object_pairs_hook=_pairs, parse_constant=_nonfinite
        )
    except (ValueError, UnicodeError, RecursionError):
        raise CurrentResultError() from None


def _json(value: object) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8", "strict")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise CurrentResultError() from None


def _intent_wire(value: CurrentResultIntent) -> dict[str, object]:
    return {
        "delivery_id": value.delivery_id,
        "scope": {"tenant_id": value.scope.tenant_id, "account_id": value.scope.account_id},
        "work_id": value.work_id,
        "attempt_id": value.attempt_id,
        "result_sha256": value.result_sha256,
        "receiver_id": value.receiver_id,
        "recipient_id": value.recipient_id,
        "body": value.body,
        "prepared_at_ms": value.prepared_at_ms,
    }


def _receipt_wire(value: CurrentResultReceipt) -> dict[str, object]:
    return {
        "delivery_id": value.delivery_id,
        "receipt_id": value.receipt_id,
        "receiver_id": value.receiver_id,
        "recipient_id": value.recipient_id,
        "result_sha256": value.result_sha256,
        "accepted_at_ms": value.accepted_at_ms,
    }


def _projection_wire(value: CurrentResultProjection) -> dict[str, object]:
    return {
        "inputReceiptId": value.input_receipt_id,
        "operationKey": value.operation_key,
        "intent": _intent_wire(value.intent),
        "receipt": _receipt_wire(value.receipt),
        "case": {"source": value.case.source, "revision": value.case.revision},
        "observed": {
            "p2ObservedAt": value.observed.p2_observed_at,
            "caseObservedAt": value.observed.case_observed_at,
            "disclosureAdmittedAt": value.observed.disclosure_admitted_at,
            "atomic": value.observed.atomic,
        },
    }


def _parse_projection(value: object) -> CurrentResultProjection:
    result = _fields(
        value, {"inputReceiptId", "operationKey", "intent", "receipt", "case", "observed"}
    )
    intent = _fields(result["intent"], _INTENT_FIELDS)
    scope = _fields(intent["scope"], {"tenant_id", "account_id"})
    receipt = _fields(result["receipt"], _RECEIPT_FIELDS)
    case = _fields(result["case"], {"source", "revision"})
    observed = _fields(
        result["observed"], {"p2ObservedAt", "caseObservedAt", "disclosureAdmittedAt", "atomic"}
    )
    # Every external field is validated before entering a typed record; casts do
    # not select authority, coerce numbers or inspect caller-selected objects.
    return CurrentResultProjection(
        _uuid(result["inputReceiptId"]),
        _uuid(result["operationKey"]),
        CurrentResultIntent(
            _uuid(intent["delivery_id"]),
            DiscoveryScope(_identifier(scope["tenant_id"]), _identifier(scope["account_id"])),
            _uuid(intent["work_id"]),
            _uuid(intent["attempt_id"]),
            _digest(intent["result_sha256"]),
            _uuid(intent["receiver_id"]),
            _identifier(intent["recipient_id"]),
            _body(intent["body"], _digest(intent["result_sha256"])),
            _milliseconds(intent["prepared_at_ms"]),
        ),
        CurrentResultReceipt(
            _uuid(receipt["delivery_id"]),
            _uuid(receipt["receipt_id"]),
            _uuid(receipt["receiver_id"]),
            _identifier(receipt["recipient_id"]),
            _digest(receipt["result_sha256"]),
            _milliseconds(receipt["accepted_at_ms"]),
        ),
        CurrentResultCase(
            cast(Literal["p1_public_v4"], case["source"]), _revision(case["revision"])
        ),
        CurrentResultObserved(
            _timestamp(observed["p2ObservedAt"]),
            _timestamp(observed["caseObservedAt"]),
            _timestamp(observed["disclosureAdmittedAt"]),
            cast(Literal[False], observed["atomic"]),
        ),
    )


def parse_current_result_request(raw: bytes) -> CurrentResultRequest:
    value = _fields(_decode(raw, CURRENT_RESULT_REQUEST_BYTES), {"schemaVersion"})
    _version(value["schemaVersion"])
    return CurrentResultRequest()


def encode_current_result_request(value: CurrentResultRequest) -> bytes:
    if type(value) is not CurrentResultRequest:
        raise CurrentResultError()
    try:
        _version(value.schema_version)
        return _json({"schemaVersion": 1})
    except AttributeError:
        raise CurrentResultError() from None


def parse_current_result_observation(raw: bytes) -> CurrentResultObservation:
    value = _fields(_decode(raw, CURRENT_RESULT_BYTES), _OBSERVATION_FIELDS)
    _version(value["schemaVersion"])
    scope = _fields(value["scope"], {"tenantId", "accountId"})
    return CurrentResultObservation(
        _uuid(value["profileId"]),
        DiscoveryScope(_identifier(scope["tenantId"]), _identifier(scope["accountId"])),
        _identifier(value["caseId"]),
        _identifier(value["conversationId"]),
        _timestamp(value["readCompletedAt"]),
        cast(CurrentResultState, value["state"]),
        None if value["result"] is None else _parse_projection(value["result"]),
        cast(Literal[1], value["schemaVersion"]),
        cast(Literal["channel.policy_current_result"], value["kind"]),
    )


def encode_current_result_observation(value: CurrentResultObservation) -> bytes:
    if type(value) is not CurrentResultObservation:
        raise CurrentResultError()
    try:
        copied = CurrentResultObservation(
            value.profile_id,
            value.scope,
            value.case_id,
            value.conversation_id,
            value.read_completed_at,
            value.state,
            value.result,
            value.schema_version,
            value.kind,
        )
        raw = _json(
            {
                "schemaVersion": copied.schema_version,
                "kind": copied.kind,
                "profileId": copied.profile_id,
                "scope": {"tenantId": copied.scope.tenant_id, "accountId": copied.scope.account_id},
                "caseId": copied.case_id,
                "conversationId": copied.conversation_id,
                "readCompletedAt": copied.read_completed_at,
                "state": copied.state,
                "result": None if copied.result is None else _projection_wire(copied.result),
            }
        )
        _need(len(raw) <= CURRENT_RESULT_BYTES)
        return raw
    except AttributeError:
        raise CurrentResultError() from None
