"""Bounded result-projection metadata; every applicability value is an as-of read.

No model here represents execution ownership, delivery, action permission or a
queue. Source/result identity is immutable; replay retains the original observation.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal, cast, get_args
from uuid import UUID

from continuity_lab.result_feed_api import ResultFeedEvent
from continuity_lab.work_api import WorkError, WorkScope

from .contracts import ERROR_CODES, canonical, decode

ProjectionCode = Literal[
    "invalid_input",
    "unauthorized",
    "source_mismatch",
    "checkpoint_conflict",
    "identity_conflict",
    "capacity",
    "storage_unavailable",
    "acknowledgement_unknown",
    "schema_mismatch",
    "closed",
    "cleanup_incomplete",
    "invalid_source_state",
    "deadline_exceeded",
    "request_aborted",
    "not_found",
]
_CODES = frozenset(get_args(ProjectionCode))
MAX_SEQUENCE = 9223372036854775807
MAX_RECORDS = 30000


class ProjectionError(RuntimeError):
    """Fixed public code; submitted data and dependency messages never escape."""

    def __init__(self, code: ProjectionCode) -> None:
        self.code: ProjectionCode = (
            code if type(code) is str and code in _CODES else "invalid_input"
        )
        super().__init__(self.code)


def uuid(value: str) -> str:
    if type(value) is not str or len(value) != 36:
        raise ProjectionError("invalid_input")
    try:
        parsed = UUID(value)
    except ValueError:
        raise ProjectionError("invalid_input") from None
    if parsed.version != 4 or str(parsed) != value:
        raise ProjectionError("invalid_input")
    return value


def integer(value: int, maximum: int = MAX_SEQUENCE) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ProjectionError("invalid_input")
    return value


def digest(value: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ProjectionError("invalid_input")
    return value


def timestamp(value: int) -> int:
    return integer(value, 4102444800000)


def fields(value: object, names: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != names:
        raise ProjectionError("invalid_input")
    return cast(
        dict[str, Any], value
    )  # Exact plain dictionary checked; models validate decoded fields.


@dataclass(frozen=True, slots=True)
class ProjectionBinding:
    source_id: str
    scope: WorkScope

    def __post_init__(self) -> None:
        uuid(self.source_id)
        if type(self.scope) is not WorkScope:
            raise ProjectionError("invalid_input")
        WorkScope(self.scope.tenant_id, self.scope.account_id)


@dataclass(frozen=True, slots=True)
class ProjectionLimits:
    max_records: int = 3000

    def __post_init__(self) -> None:
        if integer(self.max_records, MAX_RECORDS) == 0:
            raise ProjectionError("invalid_input")


@dataclass(frozen=True, slots=True)
class ProjectionCheckpoint:
    binding: ProjectionBinding
    sequence: int
    record_count: int

    def __post_init__(self) -> None:
        if type(self.binding) is not ProjectionBinding:
            raise ProjectionError("invalid_input")
        integer(self.sequence)
        integer(self.record_count, MAX_RECORDS)
        if self.sequence != self.record_count:
            raise ProjectionError("invalid_input")


Appraisal = Literal[
    "candidate",
    "clarification",
    "outdated",
    "case_cancelled",
    "expired",
    "execution_ineligible",
    "unavailable",
]
_CASE_STATES = frozenset({"observed", "unavailable", "not_read"})
_EXECUTION_STATES = frozenset(
    {"accepted", "running", "retryable", "exhausted", "result_recorded", "cancelled", "expired"}
)


@dataclass(frozen=True, slots=True)
class ApplicabilityObservation:
    """Separate non-atomic execution/case observations, never action permission."""

    applicability: Appraisal
    execution_status: str
    cancel_requested: bool
    current_attempt_id: str | None
    execution_observed_at_ms: int
    case_status: Literal["observed", "unavailable", "not_read"]
    case_revision: int | None
    case_cancelled: bool | None
    case_observed_at_ms: int | None
    evaluated_at_ms: int
    kind: Literal["as_of_non_atomic"] = "as_of_non_atomic"

    def __post_init__(self) -> None:
        if (
            type(self.applicability) is not str
            or self.applicability not in get_args(Appraisal)
            or type(self.execution_status) is not str
            or self.execution_status not in _EXECUTION_STATES
            or type(self.cancel_requested) is not bool
            or type(self.case_status) is not str
            or self.case_status not in _CASE_STATES
            or type(self.kind) is not str
            or self.kind != "as_of_non_atomic"
        ):
            raise ProjectionError("invalid_input")
        if self.current_attempt_id is not None:
            uuid(self.current_attempt_id)
        timestamp(self.execution_observed_at_ms)
        timestamp(self.evaluated_at_ms)
        if self.case_observed_at_ms is not None:
            timestamp(self.case_observed_at_ms)
        if self.case_status == "observed":
            if (
                self.case_revision is None
                or type(self.case_cancelled) is not bool
                or self.case_observed_at_ms is None
            ):
                raise ProjectionError("invalid_input")
            integer(self.case_revision, 9007199254740991)
        elif (
            self.case_revision is not None
            or self.case_cancelled is not None
            or (self.case_status == "not_read" and self.case_observed_at_ms is not None)
        ):
            raise ProjectionError("invalid_input")
        if self.case_status == "unavailable" and (
            self.case_observed_at_ms is None or self.applicability != "unavailable"
        ):
            raise ProjectionError("invalid_input")


def event_payload(event: ResultFeedEvent) -> dict[str, object]:
    if type(event) is not ResultFeedEvent or type(event.scope) is not WorkScope:
        raise ProjectionError("invalid_input")
    uuid(event.event_id)
    uuid(event.source_id)
    uuid(event.work_id)
    uuid(event.attempt_id)
    if integer(event.sequence) == 0:
        raise ProjectionError("invalid_input")
    digest(event.result_sha256)
    timestamp(event.recorded_at_ms)
    if (
        type(event.issue_command_id) is not str
        or not 1 <= len(event.issue_command_id) <= 128
        or event.origin not in {"live", "adopted_history"}
        or event.kind != "result_recorded"
        or event.disposition
        not in {"eligible_at_commit", "cancelled", "expired", "superseded", "lease_expired"}
    ):
        raise ProjectionError("invalid_input")
    return {
        "event_id": event.event_id,
        "source_id": event.source_id,
        "scope": {"tenant_id": event.scope.tenant_id, "account_id": event.scope.account_id},
        "sequence": event.sequence,
        "kind": event.kind,
        "work_id": event.work_id,
        "attempt_id": event.attempt_id,
        "issue_command_id": event.issue_command_id,
        "result_sha256": event.result_sha256,
        "recorded_at_ms": event.recorded_at_ms,
        "disposition": event.disposition,
        "origin": event.origin,
    }


def event_digest(event: ResultFeedEvent) -> str:
    return hashlib.sha256(canonical(event_payload(event))).hexdigest()


@dataclass(frozen=True, slots=True)
class ProjectedResult:
    event: ResultFeedEvent
    request_sha256: str
    delegation_id: str | None
    case_id: str | None
    request_revision: int | None
    input_fingerprint: str | None
    validation: Literal["validated", "rejected"]
    rejection_code: str | None
    observation: ApplicabilityObservation | None
    projected_at_ms: int
    schema_version: Literal[1] = 1
    kind: Literal["result_projection"] = "result_projection"

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not int
            or self.schema_version != 1
            or type(self.kind) is not str
            or self.kind != "result_projection"
        ):
            raise ProjectionError("invalid_input")
        event_payload(self.event)
        digest(self.request_sha256)
        timestamp(self.projected_at_ms)
        values = (self.delegation_id, self.case_id, self.request_revision, self.input_fingerprint)
        if any(v is None for v in values) and any(v is not None for v in values):
            raise ProjectionError("invalid_input")
        if self.delegation_id is not None:
            from .contracts import identifier

            assert (
                self.case_id is not None
                and self.request_revision is not None
                and self.input_fingerprint is not None
            )
            identifier(self.delegation_id)
            identifier(self.case_id)
            integer(self.request_revision, 9007199254740991)
            digest(self.input_fingerprint)
        if self.validation == "validated":
            if (
                self.rejection_code is not None
                or type(self.observation) is not ApplicabilityObservation
                or self.delegation_id is None
            ):
                raise ProjectionError("invalid_input")
        elif self.validation == "rejected":
            if (
                type(self.rejection_code) is not str
                or self.rejection_code not in ERROR_CODES
                or self.observation is not None
            ):
                raise ProjectionError("invalid_input")
        else:
            raise ProjectionError("invalid_input")

    def payload(self) -> dict[str, object]:
        from dataclasses import asdict

        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "event": event_payload(self.event),
            "request_sha256": self.request_sha256,
            "delegation_id": self.delegation_id,
            "case_id": self.case_id,
            "request_revision": self.request_revision,
            "input_fingerprint": self.input_fingerprint,
            "validation": self.validation,
            "rejection_code": self.rejection_code,
            "observation": None if self.observation is None else asdict(self.observation),
            "projected_at_ms": self.projected_at_ms,
        }

    def canonical(self) -> bytes:
        raw = canonical(self.payload())
        if not 1 <= len(raw) <= 8192:
            raise ProjectionError("invalid_input")
        return raw


def parse_projected(raw: bytes) -> ProjectedResult:
    """Strict database-value reconstruction; unknown fields and aliases reject."""
    try:
        body = fields(
            decode(raw, 8192),
            {
                "schema_version",
                "kind",
                "event",
                "request_sha256",
                "delegation_id",
                "case_id",
                "request_revision",
                "input_fingerprint",
                "validation",
                "rejection_code",
                "observation",
                "projected_at_ms",
            },
        )
        e = fields(
            body["event"],
            {
                "event_id",
                "source_id",
                "scope",
                "sequence",
                "kind",
                "work_id",
                "attempt_id",
                "issue_command_id",
                "result_sha256",
                "recorded_at_ms",
                "disposition",
                "origin",
            },
        )
        scope = fields(e.pop("scope"), {"tenant_id", "account_id"})
        event = ResultFeedEvent(scope=WorkScope(**scope), **e)
        observed = body.pop("observation")
        observation = (
            None
            if observed is None
            else ApplicabilityObservation(
                **fields(
                    observed,
                    {
                        "applicability",
                        "execution_status",
                        "cancel_requested",
                        "current_attempt_id",
                        "execution_observed_at_ms",
                        "case_status",
                        "case_revision",
                        "case_cancelled",
                        "case_observed_at_ms",
                        "evaluated_at_ms",
                        "kind",
                    },
                )
            )
        )
        body.pop("event")
        result = ProjectedResult(event=event, observation=observation, **body)
        if result.canonical() != raw:
            raise ProjectionError("invalid_input")
        return result
    except (ValueError, TypeError, KeyError, AttributeError, ProjectionError, WorkError):
        raise ProjectionError("invalid_input") from None


@dataclass(frozen=True, slots=True)
class ProjectionBatch:
    before: ProjectionCheckpoint
    after: ProjectionCheckpoint
    rows: tuple[ProjectedResult, ...]
    reconciled: bool

    def __post_init__(self) -> None:
        if (
            type(self.before) is not ProjectionCheckpoint
            or type(self.after) is not ProjectionCheckpoint
            or self.before.binding != self.after.binding
            or self.after.sequence < self.before.sequence
            or type(self.rows) is not tuple
            or len(self.rows) > 8
            or any(type(v) is not ProjectedResult for v in self.rows)
            or type(self.reconciled) is not bool
        ):
            raise ProjectionError("invalid_input")
