"""Additive read-only document wire contract; no policy or execution authority."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Literal, cast

from .contracts import (
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

DOCUMENT_CAPABILITY = "booking.extract_document"
DOCUMENT_FIELDS = ("booking_reference", "property_name", "check_in", "check_out")
DocumentFieldName = Literal["booking_reference", "property_name", "check_in", "check_out"]
DocumentState = Literal["known", "missing", "ambiguous"]
DocumentOutcome = Literal["extracted", "clarification_required"]


@dataclass(frozen=True, slots=True)
class DocumentContext:
    document_source_id: str
    note: str = ""


@dataclass(frozen=True, slots=True)
class DocumentRequest:
    scope: Scope
    delegation_id: str
    case_id: str
    request_revision: int
    context_snapshot: DocumentContext
    evidence: tuple[EvidenceRef, ...]
    deadline_at_ms: int
    conversation_id: str
    attempt: Attempt
    input_fingerprint: str

    def to_wire(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": "delegation.request",
            "capability": DOCUMENT_CAPABILITY,
            "input_schema_version": 1,
            "scope": {"tenant_id": self.scope.tenant_id, "account_id": self.scope.account_id},
            "delegation_id": self.delegation_id,
            "case_id": self.case_id,
            "request_revision": self.request_revision,
            "context_snapshot": {
                "document_kind": "booking_confirmation_v1",
                "document_source_id": self.context_snapshot.document_source_id,
                "requested_fields": list(DOCUMENT_FIELDS),
                "note": self.context_snapshot.note,
            },
            "evidence": [
                {
                    "source_id": x.source_id,
                    "version": x.version,
                    "sha256": x.sha256,
                    "media_type": x.media_type,
                    "byte_length": x.byte_length,
                    "width": x.width,
                    "height": x.height,
                }
                for x in self.evidence
            ],
            "deadline_at_ms": self.deadline_at_ms,
            "result_route": {"conversation_id": self.conversation_id},
            "attempt": {"attempt_id": self.attempt.attempt_id, "number": self.attempt.number},
            "input_fingerprint": self.input_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class DocumentRegion:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class DocumentEvidence:
    source_id: str
    version: str
    sha256: str
    region: DocumentRegion

    def to_wire(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "version": self.version,
            "sha256": self.sha256,
            "region": {
                "x": self.region.x,
                "y": self.region.y,
                "width": self.region.width,
                "height": self.region.height,
            },
        }


@dataclass(frozen=True, slots=True)
class DocumentField:
    state: DocumentState
    value: str | None
    evidence_refs: tuple[DocumentEvidence, ...]

    def to_wire(self) -> dict[str, object]:
        return {
            "state": self.state,
            "value": self.value,
            "evidence_refs": [x.to_wire() for x in self.evidence_refs],
        }


@dataclass(frozen=True, slots=True)
class DocumentFields:
    booking_reference: DocumentField
    property_name: DocumentField
    check_in: DocumentField
    check_out: DocumentField

    def to_wire(self) -> dict[str, object]:
        return {name: getattr(self, name).to_wire() for name in DOCUMENT_FIELDS}


@dataclass(frozen=True, slots=True)
class DocumentResult:
    scope: Scope
    delegation_id: str
    case_id: str
    request_revision: int
    attempt_id: str
    input_fingerprint: str
    outcome: DocumentOutcome
    fields: DocumentFields
    producer: Producer
    completed_at_ms: int

    def to_wire(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": "delegation.result",
            "capability": DOCUMENT_CAPABILITY,
            "result_schema_version": 1,
            "scope": {"tenant_id": self.scope.tenant_id, "account_id": self.scope.account_id},
            "delegation_id": self.delegation_id,
            "case_id": self.case_id,
            "request_revision": self.request_revision,
            "attempt_id": self.attempt_id,
            "input_fingerprint": self.input_fingerprint,
            "outcome": self.outcome,
            "fields": self.fields.to_wire(),
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
    "outcome",
    "fields",
    "producer",
    "completed_at_ms",
}


def _header(value: dict[str, object], kind: str, version_field: str) -> None:
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or (type(value[version_field]) is not int or value[version_field] != 1)
    ):
        raise ContractError("unsupported_version")
    if value["kind"] != kind:
        raise ContractError()
    if value["capability"] != DOCUMENT_CAPABILITY:
        raise ContractError("unknown_capability")


def _scope(value: object) -> Scope:
    obj = object_fields(value, {"tenant_id", "account_id"})
    return Scope(identifier(obj["tenant_id"]), identifier(obj["account_id"]))


def logical_document_fingerprint(wire: dict[str, object]) -> str:
    return logical_fingerprint(wire)


def parse_document_request(payload: bytes) -> DocumentRequest:
    obj = object_fields(decode(payload, MAX_REQUEST_BYTES), REQUEST_FIELDS)
    _header(obj, "delegation.request", "input_schema_version")
    context = object_fields(
        obj["context_snapshot"], {"document_kind", "document_source_id", "requested_fields", "note"}
    )
    if context["document_kind"] != "booking_confirmation_v1" or (
        type(context["requested_fields"]) is not list
        or context["requested_fields"] != list(DOCUMENT_FIELDS)
    ):
        raise ContractError()
    refs = obj["evidence"]
    if type(refs) is not list or len(refs) != 1:
        raise ContractError()
    ref = object_fields(
        refs[0], {"source_id", "version", "sha256", "media_type", "byte_length", "width", "height"}
    )
    if ref["media_type"] != "image/png":
        raise ContractError()
    source_id = identifier(context["document_source_id"])
    evidence = EvidenceRef(
        identifier(ref["source_id"]),
        identifier(ref["version"]),
        digest(ref["sha256"]),
        "image/png",
        integer(ref["byte_length"], 1, 2097152),
        integer(ref["width"], 1, 2048),
        integer(ref["height"], 1, 2048),
    )
    if evidence.source_id != source_id:
        raise ContractError("evidence_mismatch")
    fingerprint = digest(obj["input_fingerprint"])
    if fingerprint != logical_document_fingerprint(obj):
        raise ContractError("identity_conflict")
    route = object_fields(obj["result_route"], {"conversation_id"})
    attempt = object_fields(obj["attempt"], {"attempt_id", "number"})
    return DocumentRequest(
        _scope(obj["scope"]),
        identifier(obj["delegation_id"]),
        identifier(obj["case_id"]),
        integer(obj["request_revision"], 1, 1000000),
        DocumentContext(source_id, text(context["note"])),
        (evidence,),
        integer(obj["deadline_at_ms"], 0, MAX_TIMESTAMP_MS),
        identifier(route["conversation_id"]),
        Attempt(identifier(attempt["attempt_id"]), integer(attempt["number"], 1, 1000)),
        fingerprint,
    )


def produce_document_request(value: dict[str, object]) -> DocumentRequest:
    copied = object_fields(
        decode(canonical(value), MAX_REQUEST_BYTES), REQUEST_FIELDS - {"input_fingerprint"}
    )
    copied["input_fingerprint"] = logical_document_fingerprint(copied)
    return parse_document_request(canonical(copied))


def encode_document_request(value: DocumentRequest) -> bytes:
    if (
        type(value) is not DocumentRequest
        or type(value.scope) is not Scope
        or (
            type(value.attempt) is not Attempt
            or type(value.context_snapshot) is not DocumentContext
            or type(value.evidence) is not tuple
            or any(type(x) is not EvidenceRef for x in value.evidence)
        )
    ):
        raise ContractError()
    raw = canonical(value.to_wire())
    parse_document_request(raw)
    return raw


def _evidence(value: object) -> DocumentEvidence:
    obj = object_fields(value, {"source_id", "version", "sha256", "region"})
    region = object_fields(obj["region"], {"x", "y", "width", "height"})
    x, y = integer(region["x"], 0, 2047), integer(region["y"], 0, 2047)
    width, height = integer(region["width"], 1, 2048), integer(region["height"], 1, 2048)
    if x + width > 2048 or y + height > 2048:
        raise ContractError()
    return DocumentEvidence(
        identifier(obj["source_id"]),
        identifier(obj["version"]),
        digest(obj["sha256"]),
        DocumentRegion(x, y, width, height),
    )


def _date(value: str) -> str:
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value, re.ASCII) is None:
        raise ContractError()
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ContractError() from None
    if not 1970 <= parsed.year <= 2100:
        raise ContractError()
    return value


def _field(value: object, name: str) -> DocumentField:
    obj = object_fields(value, {"state", "value", "evidence_refs"})
    state, val, refs = obj["state"], obj["value"], obj["evidence_refs"]
    if (
        type(state) is not str
        or state not in {"known", "missing", "ambiguous"}
        or type(refs) is not list
    ):
        raise ContractError()
    if state == "known":
        val = text(val, 128)
        if not val.strip() or not 1 <= len(refs) <= 2:
            raise ContractError()
        if name in {"check_in", "check_out"}:
            val = _date(val)
    elif val is not None or len(refs) != (0 if state == "missing" else 2):
        raise ContractError()
    witnesses = tuple(_evidence(x) for x in refs)
    if len({canonical(x.to_wire()) for x in witnesses}) != len(witnesses):
        raise ContractError()
    return DocumentField(cast(DocumentState, state), val, witnesses)


def parse_document_result(payload: bytes) -> DocumentResult:
    obj = object_fields(decode(payload, MAX_RESULT_BYTES), RESULT_FIELDS)
    _header(obj, "delegation.result", "result_schema_version")
    fields = object_fields(obj["fields"], set(DOCUMENT_FIELDS))
    parsed = [_field(fields[name], name) for name in DOCUMENT_FIELDS]
    outcome = obj["outcome"]
    expected = "extracted" if all(x.state == "known" for x in parsed) else "clarification_required"
    if type(outcome) is not str or outcome != expected:
        raise ContractError()
    arrival, departure = parsed[2].value, parsed[3].value
    if arrival is not None and departure is not None and departure <= arrival:
        raise ContractError()
    producer = object_fields(
        obj["producer"], {"producer_id", "model_id", "model_version", "config_fingerprint"}
    )
    model_id = None if producer["model_id"] is None else text(producer["model_id"], 64)
    model_version = (
        None if producer["model_version"] is None else text(producer["model_version"], 64)
    )
    if (model_id is None) != (model_version is None) or model_id == "" or model_version == "":
        raise ContractError()
    return DocumentResult(
        _scope(obj["scope"]),
        identifier(obj["delegation_id"]),
        identifier(obj["case_id"]),
        integer(obj["request_revision"], 1, 1000000),
        identifier(obj["attempt_id"]),
        digest(obj["input_fingerprint"]),
        cast(DocumentOutcome, outcome),
        DocumentFields(*parsed),
        Producer(
            identifier(producer["producer_id"]),
            model_id,
            model_version,
            digest(producer["config_fingerprint"]),
        ),
        integer(obj["completed_at_ms"], 0, MAX_TIMESTAMP_MS),
    )


def encode_document_result(value: DocumentResult) -> bytes:
    if (
        type(value) is not DocumentResult
        or type(value.scope) is not Scope
        or (type(value.fields) is not DocumentFields or type(value.producer) is not Producer)
    ):
        raise ContractError()
    for name in DOCUMENT_FIELDS:
        field = getattr(value.fields, name)
        if (
            type(field) is not DocumentField
            or type(field.evidence_refs) is not tuple
            or any(
                type(x) is not DocumentEvidence or type(x.region) is not DocumentRegion
                for x in field.evidence_refs
            )
        ):
            raise ContractError()
    raw = canonical(value.to_wire())
    parse_document_result(raw)
    return raw


def match_document_result(
    request: DocumentRequest, result: DocumentResult, *, observed_at_ms: int
) -> Literal["candidate", "expired"]:
    request = parse_document_request(encode_document_request(request))
    result = parse_document_result(encode_document_result(result))
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
    source = request.evidence[0]
    assert source.width is not None and source.height is not None
    for name in DOCUMENT_FIELDS:
        for ref in getattr(result.fields, name).evidence_refs:
            if (ref.source_id, ref.version, ref.sha256) != (
                source.source_id,
                source.version,
                source.sha256,
            ):
                raise ContractError("evidence_mismatch")
            if (
                ref.region.x + ref.region.width > source.width
                or ref.region.y + ref.region.height > source.height
            ):
                raise ContractError("evidence_mismatch")
    return "expired" if observed_at_ms >= request.deadline_at_ms else "candidate"
