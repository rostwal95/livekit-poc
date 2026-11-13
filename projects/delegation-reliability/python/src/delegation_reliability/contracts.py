"""Strict immutable first-capability wire boundary; no execution or authority store."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Literal, cast

MAX_REQUEST_BYTES = 16_384
MAX_RESULT_BYTES = 8_192
MAX_NODES = 256
MAX_DEPTH = 12
MAX_TIMESTAMP_MS = 4_102_444_800_000
MAX_DEADLINE_WINDOW_MS = 60_000
MAX_EVIDENCE_BYTES = 2_097_152
MAX_IMAGE_DIMENSION = 2048
CAPABILITY = "booking.evaluate_policy"
ErrorCode = Literal[
    "invalid_json",
    "invalid_contract",
    "unsupported_version",
    "unknown_capability",
    "identity_conflict",
    "result_mismatch",
    "evidence_mismatch",
    "unsupported_facts",
    "unauthorized",
    "expired",
    "capacity",
    "unknown_attempt",
]
ERROR_CODES = frozenset(
    {
        "invalid_json",
        "invalid_contract",
        "unsupported_version",
        "unknown_capability",
        "identity_conflict",
        "result_mismatch",
        "evidence_mismatch",
        "unsupported_facts",
        "unauthorized",
        "expired",
        "capacity",
        "unknown_attempt",
    }
)
_ID = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z", re.ASCII)
_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)


class ContractError(ValueError):
    """Fixed safe code, never received field values or external error text."""

    def __init__(self, code: ErrorCode = "invalid_contract") -> None:
        self.code = code
        super().__init__(code)


def object_fields(value: object, fields: set[str]) -> dict[str, object]:
    if type(value) is not dict or len(value) != len(fields) or set(value) != fields:
        raise ContractError()
    return cast(dict[str, object], value)


def integer(value: object, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ContractError()
    return value


def identifier(value: object) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ContractError()
    return value


def digest(value: object) -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise ContractError()
    return value


def text(value: object, maximum: int = 1024) -> str:
    if type(value) is not str or len(value) > maximum:
        raise ContractError()
    try:
        if len(value.encode("utf-8")) > maximum:
            raise ContractError()
    except UnicodeError:
        raise ContractError() from None
    return value


def canonical(value: object) -> bytes:
    normalized = _copy_json(value, 0, [MAX_NODES, MAX_REQUEST_BYTES], set())
    return json.dumps(normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


def _copy_json(value: object, depth: int, budget: list[int], active: set[int]) -> object:
    budget[0] -= 1
    if depth > MAX_DEPTH or budget[0] < 0:
        raise ContractError("invalid_json")
    if value is None or type(value) is bool:
        return value
    if type(value) is int:
        return integer(value, -9_007_199_254_740_991, 9_007_199_254_740_991)
    if type(value) is str:
        text(value, MAX_REQUEST_BYTES)
        budget[1] -= len(value.encode("utf-8"))
        if budget[1] < 0:
            raise ContractError("invalid_json")
        return value
    if type(value) not in (dict, list, tuple) or id(value) in active:
        raise ContractError("invalid_json")
    if depth >= MAX_DEPTH:
        raise ContractError("invalid_json")
    active.add(id(value))
    try:
        if isinstance(value, (list, tuple)):
            if len(value) > MAX_NODES:
                raise ContractError("invalid_json")
            return [_copy_json(child, depth + 1, budget, active) for child in value]
        mapping = cast(dict[str, object], value)  # Exact dict type checked above.
        if len(mapping) > 64:
            raise ContractError("invalid_json")
        output = {}
        for key, child in mapping.items():
            text(key, 64)
            budget[1] -= len(key.encode("utf-8"))
            if budget[1] < 0:
                raise ContractError("invalid_json")
            output[key] = _copy_json(child, depth + 1, budget, active)
        return output
    finally:
        active.remove(id(value))


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    output: dict[str, object] = {}
    for key, value in pairs:
        if key in output:
            raise ContractError("invalid_json")
        output[key] = value
    return output


def _number(raw: str) -> int:
    if len(raw) > 16 or raw == "-0":
        raise ContractError("invalid_json")
    value = int(raw)
    if abs(value) > 9_007_199_254_740_991:
        raise ContractError("invalid_json")
    return value


def _no_float(_: str) -> object:
    raise ContractError("invalid_json")


def decode(payload: bytes, maximum: int) -> object:
    if type(payload) is not bytes or not 0 < len(payload) <= maximum:
        raise ContractError("invalid_json")
    # Scan nesting before either language's general JSON parser allocates a deep tree.
    depth, quoted, escaped = 0, False, False
    for character in payload:
        if quoted:
            if escaped:
                escaped = False
            elif character == 92:
                escaped = True
            elif character == 34:
                quoted = False
        elif character == 34:
            quoted = True
        elif character in (91, 123):
            depth += 1
            if depth > MAX_DEPTH:
                raise ContractError("invalid_json")
        elif character in (93, 125):
            depth -= 1
    try:
        value: object = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_unique,
            parse_int=_number,
            parse_float=_no_float,
            parse_constant=_no_float,
        )
        remaining = [MAX_NODES]
        _walk(value, remaining)
        return value
    except (UnicodeError, ValueError, RecursionError):
        raise ContractError("invalid_json") from None


def _walk(value: object, remaining: list[int]) -> None:
    remaining[0] -= 1
    if remaining[0] < 0:
        raise ContractError("invalid_json")
    if type(value) is str:
        text(value, MAX_REQUEST_BYTES)
    elif type(value) is dict:
        for key, child in value.items():
            text(key, 64)
            _walk(child, remaining)
    elif type(value) is list:
        for child in value:
            _walk(child, remaining)


@dataclass(frozen=True, slots=True)
class Scope:
    tenant_id: str
    account_id: str


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    source_id: str
    version: str
    sha256: str
    media_type: Literal["application/json", "image/png"]
    byte_length: int
    width: int | None
    height: int | None


@dataclass(frozen=True, slots=True)
class ContextSnapshot:
    policy_version: str
    policy_source_id: str
    days_before_arrival: int
    note: str


@dataclass(frozen=True, slots=True)
class Attempt:
    attempt_id: str
    number: int


@dataclass(frozen=True, slots=True)
class DelegationRequest:
    scope: Scope
    delegation_id: str
    case_id: str
    request_revision: int
    context_snapshot: ContextSnapshot
    evidence: tuple[EvidenceRef, ...]
    deadline_at_ms: int
    conversation_id: str
    attempt: Attempt
    input_fingerprint: str

    def to_wire(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": "delegation.request",
            "capability": CAPABILITY,
            "input_schema_version": 1,
            "scope": {"tenant_id": self.scope.tenant_id, "account_id": self.scope.account_id},
            "delegation_id": self.delegation_id,
            "case_id": self.case_id,
            "request_revision": self.request_revision,
            "context_snapshot": {
                "policy_version": self.context_snapshot.policy_version,
                "policy_source_id": self.context_snapshot.policy_source_id,
                "days_before_arrival": self.context_snapshot.days_before_arrival,
                "note": self.context_snapshot.note,
            },
            "evidence": [
                {
                    "source_id": item.source_id,
                    "version": item.version,
                    "sha256": item.sha256,
                    "media_type": item.media_type,
                    "byte_length": item.byte_length,
                    "width": item.width,
                    "height": item.height,
                }
                for item in self.evidence
            ],
            "deadline_at_ms": self.deadline_at_ms,
            "result_route": {"conversation_id": self.conversation_id},
            "attempt": {"attempt_id": self.attempt.attempt_id, "number": self.attempt.number},
            "input_fingerprint": self.input_fingerprint,
        }


def logical_fingerprint(wire: dict[str, object]) -> str:
    logical = {
        key: value for key, value in wire.items() if key not in {"attempt", "input_fingerprint"}
    }
    return hashlib.sha256(canonical(logical)).hexdigest()


def _scope(value: object) -> Scope:
    obj = object_fields(value, {"tenant_id", "account_id"})
    return Scope(identifier(obj["tenant_id"]), identifier(obj["account_id"]))


def _evidence(value: object) -> EvidenceRef:
    obj = object_fields(
        value, {"source_id", "version", "sha256", "media_type", "byte_length", "width", "height"}
    )
    media = obj["media_type"]
    length = integer(obj["byte_length"], 1, MAX_EVIDENCE_BYTES)
    width = height = None
    if media == "application/json":
        if length > 4096 or obj["width"] is not None or obj["height"] is not None:
            raise ContractError()
    elif media == "image/png":
        width = integer(obj["width"], 1, MAX_IMAGE_DIMENSION)
        height = integer(obj["height"], 1, MAX_IMAGE_DIMENSION)
    else:
        raise ContractError()
    return EvidenceRef(
        identifier(obj["source_id"]),
        identifier(obj["version"]),
        digest(obj["sha256"]),
        media,
        length,
        width,
        height,
    )


def _header(obj: dict[str, object], kind: str, version_field: str) -> None:
    if (
        type(obj["schema_version"]) is not int
        or obj["schema_version"] != 1
        or type(obj[version_field]) is not int
        or obj[version_field] != 1
    ):
        raise ContractError("unsupported_version")
    if obj["kind"] != kind:
        raise ContractError()
    if obj["capability"] != CAPABILITY:
        raise ContractError("unknown_capability")


def parse_request(payload: bytes) -> DelegationRequest:
    obj = object_fields(
        decode(payload, MAX_REQUEST_BYTES),
        {
            "schema_version",
            "kind",
            "capability",
            "input_schema_version",
            "scope",
            "delegation_id",
            "case_id",
            "request_revision",
            "context_snapshot",
            "evidence",
            "deadline_at_ms",
            "result_route",
            "attempt",
            "input_fingerprint",
        },
    )
    _header(obj, "delegation.request", "input_schema_version")
    context = object_fields(
        obj["context_snapshot"],
        {"policy_version", "policy_source_id", "days_before_arrival", "note"},
    )
    route = object_fields(obj["result_route"], {"conversation_id"})
    attempt = object_fields(obj["attempt"], {"attempt_id", "number"})
    items = obj["evidence"]
    if type(items) is not list or not 1 <= len(items) <= 4:
        raise ContractError()
    evidence = tuple(_evidence(value) for value in items)
    if len({value.source_id for value in evidence}) != len(evidence):
        raise ContractError()
    policy_id = identifier(context["policy_source_id"])
    if not any(
        item.source_id == policy_id and item.media_type == "application/json" for item in evidence
    ):
        raise ContractError("evidence_mismatch")
    fingerprint = digest(obj["input_fingerprint"])
    if fingerprint != logical_fingerprint(obj):
        raise ContractError("identity_conflict")
    return DelegationRequest(
        _scope(obj["scope"]),
        identifier(obj["delegation_id"]),
        identifier(obj["case_id"]),
        integer(obj["request_revision"], 1, 1_000_000),
        ContextSnapshot(
            identifier(context["policy_version"]),
            policy_id,
            integer(context["days_before_arrival"], 0, 3650),
            text(context["note"]),
        ),
        evidence,
        integer(obj["deadline_at_ms"], 0, MAX_TIMESTAMP_MS),
        identifier(route["conversation_id"]),
        Attempt(identifier(attempt["attempt_id"]), integer(attempt["number"], 1, 16)),
        fingerprint,
    )


def encode_request(value: DelegationRequest) -> bytes:
    if (
        type(value) is not DelegationRequest
        or type(value.scope) is not Scope
        or type(value.context_snapshot) is not ContextSnapshot
        or type(value.attempt) is not Attempt
        or type(value.evidence) is not tuple
        or not 1 <= len(value.evidence) <= 4
        or any(type(item) is not EvidenceRef for item in value.evidence)
    ):
        raise ContractError()
    payload = canonical(value.to_wire())
    parse_request(payload)
    return payload


def produce_request(value: object) -> DelegationRequest:
    fields = {
        "schema_version",
        "kind",
        "capability",
        "input_schema_version",
        "scope",
        "delegation_id",
        "case_id",
        "request_revision",
        "context_snapshot",
        "evidence",
        "deadline_at_ms",
        "result_route",
        "attempt",
    }
    obj = object_fields(value, fields)
    copied = object_fields(decode(canonical(obj), MAX_REQUEST_BYTES), fields)
    copied["input_fingerprint"] = logical_fingerprint(copied)
    return parse_request(canonical(copied))


def check_replay(
    original: DelegationRequest, candidate: DelegationRequest
) -> Literal["duplicate", "distinct"]:
    if (original.scope, original.delegation_id) != (candidate.scope, candidate.delegation_id):
        return "distinct"
    if original.input_fingerprint != candidate.input_fingerprint:
        raise ContractError("identity_conflict")
    return "duplicate"


@dataclass(frozen=True, slots=True)
class Producer:
    producer_id: str
    model_id: str | None
    model_version: str | None
    config_fingerprint: str


@dataclass(frozen=True, slots=True)
class ResultEvidence:
    source_id: str
    version: str
    sha256: str
    rule_id: str


@dataclass(frozen=True, slots=True)
class DelegationResult:
    scope: Scope
    delegation_id: str
    case_id: str
    request_revision: int
    attempt_id: str
    input_fingerprint: str
    eligible: bool | None
    uncertainty: Literal["none", "missing", "conflicting"]
    evidence_refs: tuple[ResultEvidence, ...]
    producer: Producer
    completed_at_ms: int

    def to_wire(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": "delegation.result",
            "capability": CAPABILITY,
            "result_schema_version": 1,
            "scope": {"tenant_id": self.scope.tenant_id, "account_id": self.scope.account_id},
            "delegation_id": self.delegation_id,
            "case_id": self.case_id,
            "request_revision": self.request_revision,
            "attempt_id": self.attempt_id,
            "input_fingerprint": self.input_fingerprint,
            "eligible": self.eligible,
            "uncertainty": self.uncertainty,
            "evidence_refs": [
                {
                    "source_id": item.source_id,
                    "version": item.version,
                    "sha256": item.sha256,
                    "rule_id": item.rule_id,
                }
                for item in self.evidence_refs
            ],
            "producer": {
                "producer_id": self.producer.producer_id,
                "model_id": self.producer.model_id,
                "model_version": self.producer.model_version,
                "config_fingerprint": self.producer.config_fingerprint,
            },
            "completed_at_ms": self.completed_at_ms,
        }


def parse_result(payload: bytes) -> DelegationResult:
    obj = object_fields(
        decode(payload, MAX_RESULT_BYTES),
        {
            "schema_version",
            "kind",
            "capability",
            "result_schema_version",
            "scope",
            "delegation_id",
            "case_id",
            "request_revision",
            "attempt_id",
            "input_fingerprint",
            "eligible",
            "uncertainty",
            "evidence_refs",
            "producer",
            "completed_at_ms",
        },
    )
    _header(obj, "delegation.result", "result_schema_version")
    uncertainty = obj["uncertainty"]
    if uncertainty not in ("none", "missing", "conflicting"):
        raise ContractError()
    eligible = obj["eligible"]
    if (uncertainty == "none" and type(eligible) is not bool) or (
        uncertainty != "none" and eligible is not None
    ):
        raise ContractError()
    refs = obj["evidence_refs"]
    if type(refs) is not list or not 1 <= len(refs) <= 4:
        raise ContractError()
    evidence = []
    for item in refs:
        ref = object_fields(item, {"source_id", "version", "sha256", "rule_id"})
        evidence.append(
            ResultEvidence(
                identifier(ref["source_id"]),
                identifier(ref["version"]),
                digest(ref["sha256"]),
                identifier(ref["rule_id"]),
            )
        )
    if len({item.source_id for item in evidence}) != len(evidence):
        raise ContractError()
    producer = object_fields(
        obj["producer"], {"producer_id", "model_id", "model_version", "config_fingerprint"}
    )
    return DelegationResult(
        _scope(obj["scope"]),
        identifier(obj["delegation_id"]),
        identifier(obj["case_id"]),
        integer(obj["request_revision"], 1, 1_000_000),
        identifier(obj["attempt_id"]),
        digest(obj["input_fingerprint"]),
        cast(bool | None, eligible),
        uncertainty,
        tuple(evidence),
        Producer(
            identifier(producer["producer_id"]),
            None if producer["model_id"] is None else identifier(producer["model_id"]),
            None if producer["model_version"] is None else identifier(producer["model_version"]),
            digest(producer["config_fingerprint"]),
        ),
        integer(obj["completed_at_ms"], 0, MAX_TIMESTAMP_MS),
    )


def encode_result(value: DelegationResult) -> bytes:
    if (
        type(value) is not DelegationResult
        or type(value.scope) is not Scope
        or type(value.producer) is not Producer
        or type(value.evidence_refs) is not tuple
        or not 1 <= len(value.evidence_refs) <= 4
        or any(type(item) is not ResultEvidence for item in value.evidence_refs)
    ):
        raise ContractError()
    payload = canonical(value.to_wire())
    parse_result(payload)
    return payload


def match_result(
    request: DelegationRequest, result: DelegationResult, *, observed_at_ms: int
) -> Literal["candidate", "expired"]:
    integer(observed_at_ms, 0, MAX_TIMESTAMP_MS)
    if (
        request.scope,
        request.delegation_id,
        request.case_id,
        request.request_revision,
        request.attempt.attempt_id,
        request.input_fingerprint,
    ) != (
        result.scope,
        result.delegation_id,
        result.case_id,
        result.request_revision,
        result.attempt_id,
        result.input_fingerprint,
    ):
        raise ContractError("result_mismatch")
    known = {item.source_id: item for item in request.evidence}
    for ref in result.evidence_refs:
        expected = known.get(ref.source_id)
        if expected is None or (ref.version, ref.sha256) != (expected.version, expected.sha256):
            raise ContractError("evidence_mismatch")
    return "expired" if observed_at_ms >= request.deadline_at_ms else "candidate"


def encode_error(code: ErrorCode, request_id: str) -> bytes:
    if type(code) is not str or code not in ERROR_CODES:
        raise ContractError()
    return canonical(
        {
            "schema_version": 1,
            "kind": "delegation.error",
            "code": code,
            "request_id": identifier(request_id),
            "retryable": False,
        }
    )


def parse_error(payload: bytes) -> tuple[ErrorCode, str]:
    obj = object_fields(
        decode(payload, 512), {"schema_version", "kind", "code", "request_id", "retryable"}
    )
    if type(obj["schema_version"]) is not int or obj["schema_version"] != 1:
        raise ContractError("unsupported_version")
    code = obj["code"]
    if (
        obj["kind"] != "delegation.error"
        or type(code) is not str
        or code not in ERROR_CODES
        or obj["retryable"] is not False
    ):
        raise ContractError()
    return cast(ErrorCode, code), identifier(obj["request_id"])
