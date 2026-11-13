"""Closed origin-bound policy envelopes; the nested specialist contract stays v2."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from .contracts import (
    CAPABILITY,
    MAX_REQUEST_BYTES,
    MAX_RESULT_BYTES,
    Attempt,
    ContractError,
    Scope,
    canonical,
    decode,
    digest,
    integer,
    object_fields,
)
from .fixed_policy_contracts import (
    FixedPolicyApplicability,
    FixedPolicyRequest,
    FixedPolicyResult,
    encode_fixed_policy_request,
    encode_fixed_policy_result,
    match_fixed_policy_result,
    parse_fixed_policy_request,
    parse_fixed_policy_result,
)

CHANNEL_POLICY_ORIGIN_KIND: Literal["p2.prepared_dispatch.v1"] = "p2.prepared_dispatch.v1"
_ORIGIN_FIELDS = {
    "kind",
    "profile_id",
    "operation_key",
    "input_receipt_id",
    "payload_sha256",
    "payload_byte_length",
}
_REQUEST_FIELDS = {
    "schema_version",
    "kind",
    "capability",
    "input_schema_version",
    "origin",
    "request",
    "input_fingerprint",
}
_RESULT_FIELDS = {
    "schema_version",
    "kind",
    "capability",
    "result_schema_version",
    "input_fingerprint",
    "result",
}


def _uuid(value: object) -> str:
    if type(value) is not str:
        raise ContractError()
    try:
        parsed = UUID(value)
    except ValueError:
        raise ContractError() from None
    if parsed.version != 4 or str(parsed) != value:
        raise ContractError()
    return value


def channel_policy_key(operation_key: str) -> str:
    """One original operation selects one key inside P1's configured scope."""
    return "p2_" + UUID(_uuid(operation_key)).hex


@dataclass(frozen=True, slots=True)
class ChannelPolicyOrigin:
    kind: Literal["p2.prepared_dispatch.v1"]
    profile_id: str
    operation_key: str
    input_receipt_id: str
    payload_sha256: str
    payload_byte_length: int

    def to_wire(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "profile_id": self.profile_id,
            "operation_key": self.operation_key,
            "input_receipt_id": self.input_receipt_id,
            "payload_sha256": self.payload_sha256,
            "payload_byte_length": self.payload_byte_length,
        }


@dataclass(frozen=True, slots=True)
class ChannelPolicyRequest:
    origin: ChannelPolicyOrigin
    request: FixedPolicyRequest
    input_fingerprint: str

    @property
    def scope(self) -> Scope:
        return self.request.scope

    @property
    def delegation_id(self) -> str:
        return self.request.delegation_id

    @property
    def case_id(self) -> str:
        return self.request.case_id

    @property
    def request_revision(self) -> int:
        return self.request.request_revision

    @property
    def deadline_at_ms(self) -> int:
        return self.request.deadline_at_ms

    @property
    def conversation_id(self) -> str:
        return self.request.conversation_id

    @property
    def attempt(self) -> Attempt:
        return self.request.attempt

    def to_wire(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": "delegation.request",
            "capability": CAPABILITY,
            "input_schema_version": 3,
            "origin": self.origin.to_wire(),
            "request": self.request.to_wire(),
            "input_fingerprint": self.input_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class ChannelPolicyResult:
    result: FixedPolicyResult
    input_fingerprint: str

    def to_wire(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": "delegation.result",
            "capability": CAPABILITY,
            "result_schema_version": 3,
            "input_fingerprint": self.input_fingerprint,
            "result": self.result.to_wire(),
        }


def _header(value: dict[str, object], kind: str, version_field: str) -> None:
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or type(value[version_field]) is not int
        or value[version_field] != 3
    ):
        raise ContractError("unsupported_version")
    if value["kind"] != kind:
        raise ContractError()
    if value["capability"] != CAPABILITY:
        raise ContractError("unknown_capability")


def _origin(value: object) -> ChannelPolicyOrigin:
    obj = object_fields(value, _ORIGIN_FIELDS)
    if obj["kind"] != CHANNEL_POLICY_ORIGIN_KIND:
        raise ContractError()
    return ChannelPolicyOrigin(
        CHANNEL_POLICY_ORIGIN_KIND,
        _uuid(obj["profile_id"]),
        _uuid(obj["operation_key"]),
        _uuid(obj["input_receipt_id"]),
        digest(obj["payload_sha256"]),
        integer(obj["payload_byte_length"], 1, 32768),
    )


def _fingerprint(origin: ChannelPolicyOrigin, request: FixedPolicyRequest) -> str:
    nested = request.to_wire()
    nested.pop("attempt")
    nested.pop("input_fingerprint")
    logical = {
        "schema_version": 1,
        "kind": "delegation.request",
        "capability": CAPABILITY,
        "input_schema_version": 3,
        "origin": origin.to_wire(),
        "request": nested,
    }
    return hashlib.sha256(canonical(logical)).hexdigest()


def parse_channel_policy_request(payload: bytes) -> ChannelPolicyRequest:
    obj = object_fields(decode(payload, MAX_REQUEST_BYTES), _REQUEST_FIELDS)
    _header(obj, "delegation.request", "input_schema_version")
    origin = _origin(obj["origin"])
    request = parse_fixed_policy_request(canonical(obj["request"]))
    if request.delegation_id != channel_policy_key(origin.operation_key):
        raise ContractError("identity_conflict")
    fingerprint = digest(obj["input_fingerprint"])
    if fingerprint != _fingerprint(origin, request):
        raise ContractError("identity_conflict")
    return ChannelPolicyRequest(origin, request, fingerprint)


def produce_channel_policy_request(value: dict[str, object]) -> ChannelPolicyRequest:
    obj = object_fields(
        decode(canonical(value), MAX_REQUEST_BYTES), _REQUEST_FIELDS - {"input_fingerprint"}
    )
    _header(obj, "delegation.request", "input_schema_version")
    origin = _origin(obj["origin"])
    request = parse_fixed_policy_request(canonical(obj["request"]))
    obj["input_fingerprint"] = _fingerprint(origin, request)
    return parse_channel_policy_request(canonical(obj))


def encode_channel_policy_request(value: ChannelPolicyRequest) -> bytes:
    if (
        type(value) is not ChannelPolicyRequest
        or type(value.origin) is not ChannelPolicyOrigin
        or type(value.request) is not FixedPolicyRequest
    ):
        raise ContractError()
    # Validate the typed nested object too; a frozen dataclass alone is not a boundary.
    encode_fixed_policy_request(value.request)
    raw = canonical(value.to_wire())
    parse_channel_policy_request(raw)
    return raw


def parse_channel_policy_result(payload: bytes) -> ChannelPolicyResult:
    obj = object_fields(decode(payload, MAX_RESULT_BYTES), _RESULT_FIELDS)
    _header(obj, "delegation.result", "result_schema_version")
    return ChannelPolicyResult(
        parse_fixed_policy_result(canonical(obj["result"])), digest(obj["input_fingerprint"])
    )


def encode_channel_policy_result(value: ChannelPolicyResult) -> bytes:
    if type(value) is not ChannelPolicyResult or type(value.result) is not FixedPolicyResult:
        raise ContractError()
    encode_fixed_policy_result(value.result)
    raw = canonical(value.to_wire())
    parse_channel_policy_result(raw)
    return raw


def match_channel_policy_result(
    request: ChannelPolicyRequest,
    result: ChannelPolicyResult,
    *,
    observed_at_ms: int,
) -> FixedPolicyApplicability:
    request = parse_channel_policy_request(encode_channel_policy_request(request))
    result = parse_channel_policy_result(encode_channel_policy_result(result))
    if request.input_fingerprint != result.input_fingerprint:
        raise ContractError("result_mismatch")
    return match_fixed_policy_result(request.request, result.result, observed_at_ms=observed_at_ms)


def produce_channel_policy_result(
    request: ChannelPolicyRequest, result: FixedPolicyResult
) -> ChannelPolicyResult:
    """Wrap matched specialist metadata; factual verification remains separate."""
    request = parse_channel_policy_request(encode_channel_policy_request(request))
    result = parse_fixed_policy_result(encode_fixed_policy_result(result))
    wrapped = ChannelPolicyResult(result, request.input_fingerprint)
    match_channel_policy_result(request, wrapped, observed_at_ms=0)
    return wrapped
