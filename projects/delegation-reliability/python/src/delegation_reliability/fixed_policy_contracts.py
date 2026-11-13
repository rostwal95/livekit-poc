"""Explicit policy-v2 wire values; legacy policy codecs and authority stay separate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .contracts import (
    CAPABILITY,
    MAX_REQUEST_BYTES,
    MAX_RESULT_BYTES,
    MAX_TIMESTAMP_MS,
    Attempt,
    ContractError,
    EvidenceRef,
    Producer,
    Scope,
    canonical,
    decode,
    digest,
    identifier,
    integer,
    logical_fingerprint,
    object_fields,
    text,
)

FIXED_POLICY_VERSION = "notice_v1"
FIXED_POLICY_RULE = "notice_minimum_days"
FIXED_POLICY_MINIMUM_DAYS = 7
FixedPolicyUncertainty = Literal["none", "missing", "conflicting"]
FixedPolicyApplicability = Literal["candidate", "clarification", "expired"]


@dataclass(frozen=True, slots=True)
class FixedPolicyContext:
    policy_version: str
    policy_source_id: str
    facts_source_id: str


@dataclass(frozen=True, slots=True)
class FixedPolicyRequest:
    scope: Scope
    delegation_id: str
    case_id: str
    request_revision: int
    context_snapshot: FixedPolicyContext
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
            "input_schema_version": 2,
            "scope": {"tenant_id": self.scope.tenant_id, "account_id": self.scope.account_id},
            "delegation_id": self.delegation_id,
            "case_id": self.case_id,
            "request_revision": self.request_revision,
            "context_snapshot": {
                "policy_version": self.context_snapshot.policy_version,
                "policy_source_id": self.context_snapshot.policy_source_id,
                "facts_source_id": self.context_snapshot.facts_source_id,
            },
            "evidence": [
                {
                    "source_id": ref.source_id,
                    "version": ref.version,
                    "sha256": ref.sha256,
                    "media_type": ref.media_type,
                    "byte_length": ref.byte_length,
                    "width": ref.width,
                    "height": ref.height,
                }
                for ref in self.evidence
            ],
            "deadline_at_ms": self.deadline_at_ms,
            "result_route": {"conversation_id": self.conversation_id},
            "attempt": {"attempt_id": self.attempt.attempt_id, "number": self.attempt.number},
            "input_fingerprint": self.input_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class FixedPolicyRuleEvidence:
    source_id: str
    version: str
    sha256: str
    rule_id: str
    minimum_notice_days: int

    def to_wire(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "version": self.version,
            "sha256": self.sha256,
            "rule_id": self.rule_id,
            "minimum_notice_days": self.minimum_notice_days,
        }


@dataclass(frozen=True, slots=True)
class FixedPolicyFactEvidence:
    source_id: str
    version: str
    sha256: str
    fact_id: str
    days_before_arrival: int

    def to_wire(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "version": self.version,
            "sha256": self.sha256,
            "fact_id": self.fact_id,
            "days_before_arrival": self.days_before_arrival,
        }


@dataclass(frozen=True, slots=True)
class FixedPolicyResult:
    scope: Scope
    delegation_id: str
    case_id: str
    request_revision: int
    attempt_id: str
    input_fingerprint: str
    eligible: bool | None
    uncertainty: FixedPolicyUncertainty
    rule_refs: tuple[FixedPolicyRuleEvidence, ...]
    fact_refs: tuple[FixedPolicyFactEvidence, ...]
    producer: Producer
    completed_at_ms: int

    def to_wire(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": "delegation.result",
            "capability": CAPABILITY,
            "result_schema_version": 2,
            "scope": {"tenant_id": self.scope.tenant_id, "account_id": self.scope.account_id},
            "delegation_id": self.delegation_id,
            "case_id": self.case_id,
            "request_revision": self.request_revision,
            "attempt_id": self.attempt_id,
            "input_fingerprint": self.input_fingerprint,
            "eligible": self.eligible,
            "uncertainty": self.uncertainty,
            "rule_refs": [ref.to_wire() for ref in self.rule_refs],
            "fact_refs": [ref.to_wire() for ref in self.fact_refs],
            "producer": {
                "producer_id": self.producer.producer_id,
                "model_id": self.producer.model_id,
                "model_version": self.producer.model_version,
                "config_fingerprint": self.producer.config_fingerprint,
            },
            "completed_at_ms": self.completed_at_ms,
        }


REQUEST_FIELDS = {
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
}
RESULT_FIELDS = {
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
    "rule_refs",
    "fact_refs",
    "producer",
    "completed_at_ms",
}


def _header(value: dict[str, object], kind: str, version_field: str) -> None:
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or (type(value[version_field]) is not int or value[version_field] != 2)
    ):
        raise ContractError("unsupported_version")
    if value["kind"] != kind:
        raise ContractError()
    if value["capability"] != CAPABILITY:
        raise ContractError("unknown_capability")


def _scope(value: object) -> Scope:
    obj = object_fields(value, {"tenant_id", "account_id"})
    return Scope(identifier(obj["tenant_id"]), identifier(obj["account_id"]))


def _reference(value: object) -> EvidenceRef:
    obj = object_fields(
        value,
        {
            "source_id",
            "version",
            "sha256",
            "media_type",
            "byte_length",
            "width",
            "height",
        },
    )
    if (
        obj["media_type"] != "application/json"
        or obj["width"] is not None
        or obj["height"] is not None
    ):
        raise ContractError()
    return EvidenceRef(
        identifier(obj["source_id"]),
        identifier(obj["version"]),
        digest(obj["sha256"]),
        "application/json",
        integer(obj["byte_length"], 1, 4096),
        None,
        None,
    )


def parse_fixed_policy_request(payload: bytes) -> FixedPolicyRequest:
    obj = object_fields(decode(payload, MAX_REQUEST_BYTES), REQUEST_FIELDS)
    _header(obj, "delegation.request", "input_schema_version")
    context = object_fields(
        obj["context_snapshot"],
        {
            "policy_version",
            "policy_source_id",
            "facts_source_id",
        },
    )
    ctx = FixedPolicyContext(
        identifier(context["policy_version"]),
        identifier(context["policy_source_id"]),
        identifier(context["facts_source_id"]),
    )
    if type(obj["evidence"]) is not list or len(obj["evidence"]) != 2:
        raise ContractError()
    refs = tuple(_reference(ref) for ref in obj["evidence"])
    if ctx.policy_source_id == ctx.facts_source_id or (
        refs[0].source_id != ctx.policy_source_id or refs[1].source_id != ctx.facts_source_id
    ):
        raise ContractError("evidence_mismatch")
    fingerprint = digest(obj["input_fingerprint"])
    if fingerprint != logical_fingerprint(obj):
        raise ContractError("identity_conflict")
    route = object_fields(obj["result_route"], {"conversation_id"})
    attempt = object_fields(obj["attempt"], {"attempt_id", "number"})
    return FixedPolicyRequest(
        _scope(obj["scope"]),
        identifier(obj["delegation_id"]),
        identifier(obj["case_id"]),
        integer(obj["request_revision"], 1, 1000000),
        ctx,
        refs,
        integer(obj["deadline_at_ms"], 0, MAX_TIMESTAMP_MS),
        identifier(route["conversation_id"]),
        Attempt(identifier(attempt["attempt_id"]), integer(attempt["number"], 1, 16)),
        fingerprint,
    )


def produce_fixed_policy_request(value: dict[str, object]) -> FixedPolicyRequest:
    copied = object_fields(
        decode(canonical(value), MAX_REQUEST_BYTES), REQUEST_FIELDS - {"input_fingerprint"}
    )
    copied["input_fingerprint"] = logical_fingerprint(copied)
    return parse_fixed_policy_request(canonical(copied))


def encode_fixed_policy_request(value: FixedPolicyRequest) -> bytes:
    if (
        type(value) is not FixedPolicyRequest
        or type(value.scope) is not Scope
        or (
            type(value.context_snapshot) is not FixedPolicyContext
            or type(value.attempt) is not Attempt
            or type(value.evidence) is not tuple
            or any(type(ref) is not EvidenceRef for ref in value.evidence)
        )
    ):
        raise ContractError()
    raw = canonical(value.to_wire())
    parse_fixed_policy_request(raw)
    return raw


def _producer(value: object) -> Producer:
    obj = object_fields(value, {"producer_id", "model_id", "model_version", "config_fingerprint"})
    model = None if obj["model_id"] is None else text(obj["model_id"], 64)
    version = None if obj["model_version"] is None else text(obj["model_version"], 64)
    if (model is None) != (version is None) or model == "" or version == "":
        raise ContractError()
    return Producer(
        identifier(obj["producer_id"]), model, version, digest(obj["config_fingerprint"])
    )


def parse_fixed_policy_result(payload: bytes) -> FixedPolicyResult:
    obj = object_fields(decode(payload, MAX_RESULT_BYTES), RESULT_FIELDS)
    _header(obj, "delegation.result", "result_schema_version")
    if (
        type(obj["rule_refs"]) is not list
        or len(obj["rule_refs"]) != 1
        or (type(obj["fact_refs"]) is not list or len(obj["fact_refs"]) > 2)
    ):
        raise ContractError()
    rule = object_fields(
        obj["rule_refs"][0], {"source_id", "version", "sha256", "rule_id", "minimum_notice_days"}
    )
    rule_refs = (
        FixedPolicyRuleEvidence(
            identifier(rule["source_id"]),
            identifier(rule["version"]),
            digest(rule["sha256"]),
            identifier(rule["rule_id"]),
            integer(rule["minimum_notice_days"], 0, 3650),
        ),
    )
    facts = []
    for value in obj["fact_refs"]:
        ref = object_fields(
            value, {"source_id", "version", "sha256", "fact_id", "days_before_arrival"}
        )
        facts.append(
            FixedPolicyFactEvidence(
                identifier(ref["source_id"]),
                identifier(ref["version"]),
                digest(ref["sha256"]),
                identifier(ref["fact_id"]),
                integer(ref["days_before_arrival"], 0, 3650),
            )
        )
    if len({ref.fact_id for ref in facts}) != len(facts):
        raise ContractError()
    eligible, uncertainty = obj["eligible"], obj["uncertainty"]
    if uncertainty == "none":
        if (
            type(eligible) is not bool
            or not facts
            or len({ref.days_before_arrival for ref in facts}) != 1
        ):
            raise ContractError()
    elif uncertainty == "missing":
        if eligible is not None or facts:
            raise ContractError()
    elif uncertainty == "conflicting":
        if (
            eligible is not None
            or len(facts) != 2
            or facts[0].days_before_arrival == facts[1].days_before_arrival
        ):
            raise ContractError()
    else:
        raise ContractError()
    return FixedPolicyResult(
        _scope(obj["scope"]),
        identifier(obj["delegation_id"]),
        identifier(obj["case_id"]),
        integer(obj["request_revision"], 1, 1000000),
        identifier(obj["attempt_id"]),
        digest(obj["input_fingerprint"]),
        eligible,
        uncertainty,
        rule_refs,
        tuple(facts),
        _producer(obj["producer"]),
        integer(obj["completed_at_ms"], 0, MAX_TIMESTAMP_MS),
    )


def encode_fixed_policy_result(value: FixedPolicyResult) -> bytes:
    if (
        type(value) is not FixedPolicyResult
        or type(value.scope) is not Scope
        or (
            type(value.producer) is not Producer
            or type(value.rule_refs) is not tuple
            or type(value.fact_refs) is not tuple
            or any(type(ref) is not FixedPolicyRuleEvidence for ref in value.rule_refs)
            or any(type(ref) is not FixedPolicyFactEvidence for ref in value.fact_refs)
        )
    ):
        raise ContractError()
    raw = canonical(value.to_wire())
    parse_fixed_policy_result(raw)
    return raw


def match_fixed_policy_result(
    request: FixedPolicyRequest,
    result: FixedPolicyResult,
    *,
    observed_at_ms: int,
) -> FixedPolicyApplicability:
    request = parse_fixed_policy_request(encode_fixed_policy_request(request))
    result = parse_fixed_policy_result(encode_fixed_policy_result(result))
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

    def same_source(
        ref: FixedPolicyRuleEvidence | FixedPolicyFactEvidence, source: EvidenceRef
    ) -> None:
        if (ref.source_id, ref.version, ref.sha256) != (
            source.source_id,
            source.version,
            source.sha256,
        ):
            raise ContractError("evidence_mismatch")

    for rule in result.rule_refs:
        same_source(rule, request.evidence[0])
    for fact in result.fact_refs:
        same_source(fact, request.evidence[1])
    if observed_at_ms >= request.deadline_at_ms:
        return "expired"
    return "candidate" if result.uncertainty == "none" else "clarification"
