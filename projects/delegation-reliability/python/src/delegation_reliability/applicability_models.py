"""Versioned as-of refresh receipts and profile-lifetime display retention.

Local revisions order metadata, never case/execution authority. Display hiding
retains every protected projection, command and processing identity.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Literal, cast, get_args

from continuity_lab.result_feed_api import ResultFeedEvent
from continuity_lab.work_api import WorkError, WorkScope

from .contracts import canonical, decode
from .projection_models import (
    ApplicabilityObservation,
    ProjectedResult,
    ProjectionError,
    digest,
    event_payload,
    fields,
    integer,
    parse_projected,
    timestamp,
    uuid,
)

Classification = Literal["current", "outdated", "invalidated", "unavailable", "rejected"]
RefreshReason = Literal[
    "candidate",
    "clarification",
    "revision_advanced",
    "work_cancelled",
    "case_cancelled",
    "deadline_expired_local_as_of",
    "historical_cancelled",
    "historical_expired",
    "historical_superseded",
    "historical_lease_expired",
    "attempt_advanced",
    "case_unavailable",
    "execution_unavailable",
    "case_revision_unavailable",
    "rejected_content",
]


@dataclass(frozen=True, slots=True)
class RefreshPolicy:
    max_commands: int = 3000
    max_per_result: int = 4
    schema_version: Literal[1] = 1
    replay_horizon: Literal["profile_lifetime"] = "profile_lifetime"
    display_policy: Literal["explicit_permanent_hide"] = "explicit_permanent_hide"

    def __post_init__(self) -> None:
        if integer(self.max_commands, 30000) == 0 or integer(self.max_per_result, 8) == 0:
            raise ProjectionError("invalid_input")
        if (
            type(self.schema_version) is not int
            or self.schema_version != 1
            or type(self.replay_horizon) is not str
            or self.replay_horizon != "profile_lifetime"
            or type(self.display_policy) is not str
            or self.display_policy != "explicit_permanent_hide"
        ):
            raise ProjectionError("invalid_input")

    def canonical(self) -> bytes:
        return canonical(asdict(self))

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical()).hexdigest()


def parse_refresh_policy(raw: bytes) -> RefreshPolicy:
    try:
        value = RefreshPolicy(
            **fields(
                decode(raw, 1024),
                {
                    "max_commands",
                    "max_per_result",
                    "schema_version",
                    "replay_horizon",
                    "display_policy",
                },
            )
        )
        if value.canonical() != raw:
            raise ProjectionError("invalid_input")
        return value
    except (ValueError, TypeError, KeyError, AttributeError, WorkError):
        raise ProjectionError("invalid_input") from None


@dataclass(frozen=True, slots=True)
class InvalidationEvidence:
    """Verified retained barriers; host deadline expiry is explicitly local/as-of."""

    highest_case_revision: int | None
    highest_attempt_number: int
    work_cancelled: bool
    case_cancelled: bool
    deadline_expired_local_as_of: bool
    attempt_changed_seen: bool = False

    def __post_init__(self) -> None:
        if self.highest_case_revision is not None:
            integer(self.highest_case_revision, 9007199254740991)
        integer(self.highest_attempt_number, 3)
        if any(
            type(v) is not bool
            for v in (
                self.work_cancelled,
                self.case_cancelled,
                self.deadline_expired_local_as_of,
                self.attempt_changed_seen,
            )
        ):
            raise ProjectionError("invalid_input")


@dataclass(frozen=True, slots=True)
class ApplicabilityRefresh:
    command_id: str
    event: ResultFeedEvent
    projected_sha256: str
    request_sha256: str
    policy_sha256: str
    expected_revision: int
    revision: int
    original_attempt_number: int
    current_attempt_number: int
    request_revision: int | None
    observation: ApplicabilityObservation | None
    retained: InvalidationEvidence
    classification: Classification
    reason: RefreshReason
    refreshed_at_ms: int
    schema_version: Literal[1] = 1
    kind: Literal["applicability_refresh_as_of_non_atomic"] = (
        "applicability_refresh_as_of_non_atomic"
    )

    def __post_init__(self) -> None:
        uuid(self.command_id)
        event_payload(self.event)
        for value in (self.projected_sha256, self.request_sha256, self.policy_sha256):
            digest(value)
        integer(self.expected_revision, 7)
        if integer(self.revision, 8) != self.expected_revision + 1:
            raise ProjectionError("invalid_input")
        if integer(self.original_attempt_number, 3) == 0:
            raise ProjectionError("invalid_input")
        integer(self.current_attempt_number, 3)
        if self.request_revision is not None:
            integer(self.request_revision, 9007199254740991)
        if (
            type(self.retained) is not InvalidationEvidence
            or self.retained.highest_attempt_number < self.current_attempt_number
            or type(self.classification) is not str
            or self.classification not in get_args(Classification)
            or type(self.reason) is not str
            or self.reason not in get_args(RefreshReason)
            or type(self.schema_version) is not int
            or self.schema_version != 1
            or type(self.kind) is not str
            or self.kind != "applicability_refresh_as_of_non_atomic"
        ):
            raise ProjectionError("invalid_input")
        timestamp(self.refreshed_at_ms)
        if self.classification == "rejected":
            if self.reason != "rejected_content" or self.observation is not None:
                raise ProjectionError("invalid_input")
        elif type(self.observation) is not ApplicabilityObservation:
            raise ProjectionError("invalid_input")
        expected = (
            "current"
            if self.reason in {"candidate", "clarification"}
            else "outdated"
            if self.reason == "revision_advanced"
            else "unavailable"
            if self.reason
            in {"case_unavailable", "case_revision_unavailable", "execution_unavailable"}
            else "rejected"
            if self.reason == "rejected_content"
            else "invalidated"
        )
        if self.classification != expected:
            raise ProjectionError("invalid_input")
        if self.classification == "current" and (
            self.event.disposition != "eligible_at_commit"
            or self.retained.work_cancelled
            or self.retained.case_cancelled
            or self.retained.deadline_expired_local_as_of
            or self.retained.attempt_changed_seen
            or self.retained.highest_attempt_number > self.original_attempt_number
            or self.observation is None
            or self.observation.case_status != "observed"
            or self.observation.applicability != self.reason
            or self.observation.execution_status != "result_recorded"
            or self.observation.cancel_requested
            or self.observation.current_attempt_id != self.event.attempt_id
            or self.current_attempt_number != self.original_attempt_number
            or self.observation.case_cancelled is not False
            or self.request_revision is None
            or self.observation.case_revision != self.request_revision
            or self.retained.highest_case_revision != self.request_revision
        ):
            raise ProjectionError("invalid_input")

        witnesses = {
            "work_cancelled": self.retained.work_cancelled,
            "case_cancelled": self.retained.case_cancelled,
            "deadline_expired_local_as_of": self.retained.deadline_expired_local_as_of,
            "attempt_advanced": self.retained.attempt_changed_seen
            or self.retained.highest_attempt_number > self.original_attempt_number,
            "revision_advanced": self.request_revision is not None
            and self.retained.highest_case_revision is not None
            and self.retained.highest_case_revision > self.request_revision,
            "historical_cancelled": self.event.disposition == "cancelled",
            "historical_expired": self.event.disposition == "expired",
            "historical_superseded": self.event.disposition == "superseded",
            "historical_lease_expired": self.event.disposition == "lease_expired",
        }
        if self.reason in witnesses and not witnesses[self.reason]:
            raise ProjectionError("invalid_input")

    def payload(self) -> dict[str, object]:
        value = asdict(self)
        value["event"] = event_payload(self.event)
        return value

    def canonical(self) -> bytes:
        raw = canonical(self.payload())
        if len(raw) > 4096:
            raise ProjectionError("invalid_input")
        return raw


def _event(value: object) -> ResultFeedEvent:
    body = fields(
        value,
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
    scope = fields(body.pop("scope"), {"tenant_id", "account_id"})
    return ResultFeedEvent(scope=WorkScope(**scope), **body)


def parse_refresh(raw: bytes) -> ApplicabilityRefresh:
    try:
        body = fields(
            decode(raw, 4096),
            {
                "command_id",
                "event",
                "projected_sha256",
                "request_sha256",
                "policy_sha256",
                "expected_revision",
                "revision",
                "original_attempt_number",
                "current_attempt_number",
                "request_revision",
                "observation",
                "retained",
                "classification",
                "reason",
                "refreshed_at_ms",
                "schema_version",
                "kind",
            },
        )
        event = _event(body.pop("event"))
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
        retained = InvalidationEvidence(
            **fields(
                body.pop("retained"),
                {
                    "highest_case_revision",
                    "highest_attempt_number",
                    "work_cancelled",
                    "case_cancelled",
                    "deadline_expired_local_as_of",
                    "attempt_changed_seen",
                },
            )
        )
        result = ApplicabilityRefresh(
            event=event, observation=observation, retained=retained, **body
        )
        if result.canonical() != raw:
            raise ProjectionError("invalid_input")
        return result
    except (ValueError, TypeError, KeyError, AttributeError, WorkError):
        raise ProjectionError("invalid_input") from None


@dataclass(frozen=True, slots=True)
class DisplayTombstone:
    event: ResultFeedEvent
    projected_sha256: str
    request_sha256: str
    policy_sha256: str
    hidden_at_ms: int
    schema_version: Literal[1] = 1
    kind: Literal["display_hidden_retained_identity"] = "display_hidden_retained_identity"
    replay_horizon: Literal["profile_lifetime"] = "profile_lifetime"

    def __post_init__(self) -> None:
        event_payload(self.event)
        for value in (self.projected_sha256, self.request_sha256, self.policy_sha256):
            digest(value)
        timestamp(self.hidden_at_ms)
        if (
            type(self.schema_version) is not int
            or self.schema_version != 1
            or type(self.kind) is not str
            or self.kind != "display_hidden_retained_identity"
            or type(self.replay_horizon) is not str
            or self.replay_horizon != "profile_lifetime"
        ):
            raise ProjectionError("invalid_input")

    def canonical(self) -> bytes:
        body = asdict(self)
        body["event"] = event_payload(self.event)
        raw = canonical(body)
        if len(raw) > 2048:
            raise ProjectionError("invalid_input")
        return raw


def parse_tombstone(raw: bytes) -> DisplayTombstone:
    try:
        body = fields(
            decode(raw, 2048),
            {
                "event",
                "projected_sha256",
                "request_sha256",
                "policy_sha256",
                "hidden_at_ms",
                "schema_version",
                "kind",
                "replay_horizon",
            },
        )
        result = DisplayTombstone(event=_event(body.pop("event")), **body)
        if result.canonical() != raw:
            raise ProjectionError("invalid_input")
        return result
    except (ValueError, TypeError, KeyError, AttributeError, WorkError):
        raise ProjectionError("invalid_input") from None


@dataclass(frozen=True, slots=True)
class ApplicabilityView:
    projection: ProjectedResult
    revision: int
    latest: ApplicabilityRefresh | None
    tombstone: DisplayTombstone | None

    def __post_init__(self) -> None:
        if type(self.projection) is not ProjectedResult:
            raise ProjectionError("invalid_input")
        integer(self.revision, 8)
        if (self.latest is not None and type(self.latest) is not ApplicabilityRefresh) or (
            self.tombstone is not None and type(self.tombstone) is not DisplayTombstone
        ):
            raise ProjectionError("invalid_input")
        if (self.latest is None) != (self.revision == 0):
            raise ProjectionError("invalid_input")
        projection_sha = hashlib.sha256(self.projection.canonical()).hexdigest()
        for value in (self.latest, self.tombstone):
            if value is not None and (
                value.event != self.projection.event
                or value.projected_sha256 != projection_sha
                or value.request_sha256 != self.projection.request_sha256
            ):
                raise ProjectionError("identity_conflict")
        if self.latest is not None and self.latest.revision != self.revision:
            raise ProjectionError("invalid_input")


def snapshot_view(value: ApplicabilityView) -> ApplicabilityView:
    if type(value) is not ApplicabilityView:
        raise ProjectionError("invalid_source_state")
    return ApplicabilityView(
        parse_projected(value.projection.canonical()),
        value.revision,
        None if value.latest is None else parse_refresh(value.latest.canonical()),
        None if value.tombstone is None else parse_tombstone(value.tombstone.canonical()),
    )


@dataclass(frozen=True, slots=True)
class _RefreshDraft:
    projection: ProjectedResult
    original_attempt_number: int
    current_attempt_number: int
    observation: ApplicabilityObservation | None


def refreshed(
    *,
    command_id: str,
    expected_revision: int,
    policy: RefreshPolicy,
    draft: _RefreshDraft,
    previous: ApplicabilityRefresh | None,
    observed_at_ms: int,
) -> ApplicabilityRefresh:
    """Merge verified evidence under the metadata CAS; never grant authority."""
    p, o = draft.projection, draft.observation
    baseline = p.observation
    old = (
        previous.retained
        if previous is not None
        else InvalidationEvidence(
            None if baseline is None else baseline.case_revision,
            draft.original_attempt_number,
            False
            if baseline is None
            else baseline.cancel_requested or baseline.execution_status == "cancelled",
            False if baseline is None else baseline.case_cancelled is True,
            False
            if baseline is None
            else baseline.applicability == "expired" or baseline.execution_status == "expired",
            baseline is not None
            and baseline.current_attempt_id is not None
            and baseline.current_attempt_id != p.event.attempt_id,
        )
    )
    revision = old.highest_case_revision
    if o is not None and o.case_revision is not None:
        revision = o.case_revision if revision is None else max(revision, o.case_revision)
    retained = InvalidationEvidence(
        revision,
        max(old.highest_attempt_number, draft.current_attempt_number),
        old.work_cancelled
        or (o is not None and (o.cancel_requested or o.execution_status == "cancelled")),
        old.case_cancelled or (o is not None and o.case_cancelled is True),
        old.deadline_expired_local_as_of
        or (o is not None and (o.applicability == "expired" or o.execution_status == "expired")),
        old.attempt_changed_seen
        or (
            o is not None
            and o.current_attempt_id is not None
            and o.current_attempt_id != p.event.attempt_id
        ),
    )
    reason: RefreshReason
    if p.validation == "rejected":
        reason = "rejected_content"
    elif p.event.disposition != "eligible_at_commit":
        reason = cast(RefreshReason, "historical_" + p.event.disposition)
    elif retained.work_cancelled:
        reason = "work_cancelled"
    elif retained.case_cancelled:
        reason = "case_cancelled"
    elif retained.deadline_expired_local_as_of:
        reason = "deadline_expired_local_as_of"
    elif (
        retained.attempt_changed_seen
        or retained.highest_attempt_number > draft.original_attempt_number
    ):
        reason = "attempt_advanced"
    elif p.request_revision is not None and revision is not None and revision > p.request_revision:
        reason = "revision_advanced"
    elif o is not None and (
        o.applicability == "execution_ineligible"
        or o.execution_status != "result_recorded"
        or o.current_attempt_id != p.event.attempt_id
        or draft.current_attempt_number != draft.original_attempt_number
    ):
        reason = "execution_unavailable"
    elif o is None or o.case_status != "observed":
        reason = "case_unavailable"
    elif o.case_revision != p.request_revision or o.applicability not in {
        "candidate",
        "clarification",
    }:
        reason = "case_revision_unavailable"
    else:
        reason = "clarification" if o.applicability == "clarification" else "candidate"
    classification: Classification = (
        "current"
        if reason in {"candidate", "clarification"}
        else "outdated"
        if reason == "revision_advanced"
        else "unavailable"
        if reason in {"case_unavailable", "case_revision_unavailable", "execution_unavailable"}
        else "rejected"
        if reason == "rejected_content"
        else "invalidated"
    )
    result = ApplicabilityRefresh(
        command_id,
        p.event,
        hashlib.sha256(p.canonical()).hexdigest(),
        p.request_sha256,
        policy.sha256,
        expected_revision,
        expected_revision + 1,
        draft.original_attempt_number,
        draft.current_attempt_number,
        p.request_revision,
        o,
        retained,
        classification,
        reason,
        observed_at_ms,
    )
    result.canonical()
    return result
