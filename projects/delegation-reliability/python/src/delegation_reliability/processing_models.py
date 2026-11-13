"""Versioned delivery-only processing metadata; scan progress is never an ACK."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

from continuity_lab.delivery_api import DeliveryReceipt
from continuity_lab.result_feed_api import ResultFeedEvent
from continuity_lab.work_api import WorkScope

from .contracts import canonical, identifier
from .delivery_contract import DeliveryBinding
from .projection_models import (
    ProjectedResult,
    ProjectionBinding,
    ProjectionError,
    digest,
    event_payload,
    integer,
    timestamp,
    uuid,
)


@dataclass(frozen=True, slots=True)
class CompletionPolicy:
    receiver_id: str
    bindings: tuple[DeliveryBinding, ...]
    schema_version: Literal[1] = 1

    def __post_init__(self) -> None:
        uuid(self.receiver_id)
        if (
            type(self.schema_version) is not int
            or self.schema_version != 1
            or type(self.bindings) is not tuple
            or not 1 <= len(self.bindings) <= 32
        ):
            raise ProjectionError("invalid_input")
        keys = []
        for b in self.bindings:
            if type(b) is not DeliveryBinding:
                raise ProjectionError("invalid_input")
            DeliveryBinding(
                identifier(b.case_id), identifier(b.conversation_id), identifier(b.recipient_id)
            )
            keys.append((b.case_id, b.conversation_id))
        if len(set(keys)) != len(keys):
            raise ProjectionError("invalid_input")

    def canonical(self) -> bytes:
        raw = canonical(
            {
                "schema_version": self.schema_version,
                "kind": "delivery_only_processing",
                "receiver_id": self.receiver_id,
                "bindings": [
                    {
                        "case_id": b.case_id,
                        "conversation_id": b.conversation_id,
                        "recipient_id": b.recipient_id,
                    }
                    for b in self.bindings
                ],
            }
        )
        if len(raw) > 16384:
            raise ProjectionError("invalid_input")
        return raw

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical()).hexdigest()


def snapshot_policy(value: CompletionPolicy) -> CompletionPolicy:
    if type(value) is not CompletionPolicy:
        raise ProjectionError("invalid_input")
    result = CompletionPolicy(
        value.receiver_id,
        tuple(
            DeliveryBinding(b.case_id, b.conversation_id, b.recipient_id) for b in value.bindings
        ),
        value.schema_version,
    )
    result.canonical()
    return result


@dataclass(frozen=True, slots=True)
class ProcessingCheckpoint:
    binding: ProjectionBinding
    policy_sha256: str
    revision: int
    terminal_watermark: int
    scan_after: int
    terminal_count: int
    projected_through: int

    def __post_init__(self) -> None:
        if type(self.binding) is not ProjectionBinding:
            raise ProjectionError("invalid_input")
        digest(self.policy_sha256)
        for n in (self.revision, self.terminal_watermark, self.scan_after, self.projected_through):
            integer(n)
        integer(self.terminal_count, 30000)
        if (
            not self.terminal_watermark <= self.scan_after <= self.projected_through
            or not self.terminal_watermark <= self.terminal_count <= self.projected_through
        ):
            raise ProjectionError("invalid_input")


@dataclass(frozen=True, slots=True)
class ProcessingAcknowledgement:
    event: ResultFeedEvent
    projected_sha256: str
    request_sha256: str
    policy_sha256: str
    decision: Literal["receiver_accepted", "rejected_content", "not_required_as_of"]
    reason: str
    observed_at_ms: int
    receipt: DeliveryReceipt | None
    schema_version: Literal[1] = 1

    def __post_init__(self) -> None:
        event_payload(self.event)
        for d in (self.projected_sha256, self.request_sha256, self.policy_sha256):
            digest(d)
        timestamp(self.observed_at_ms)
        if (
            type(self.schema_version) is not int
            or self.schema_version != 1
            or type(self.decision) is not str
            or self.decision not in {"receiver_accepted", "rejected_content", "not_required_as_of"}
        ):
            raise ProjectionError("invalid_input")
        if type(self.reason) is not str or self.reason not in {
            "known_receipt",
            "rejected_content",
            "cancelled",
            "expired",
            "superseded",
            "lease_expired",
            "outdated",
            "case_cancelled",
            "execution_ineligible",
        }:
            raise ProjectionError("invalid_input")
        if self.decision == "receiver_accepted":
            r = self.receipt
            if type(r) is not DeliveryReceipt or self.reason != "known_receipt":
                raise ProjectionError("invalid_input")
            DeliveryReceipt(
                r.delivery_id,
                r.receipt_id,
                r.receiver_id,
                r.recipient_id,
                r.result_sha256,
                r.accepted_at_ms,
            )
            if r.result_sha256 != self.event.result_sha256:
                raise ProjectionError("identity_conflict")
        elif self.receipt is not None or self.reason == "known_receipt":
            raise ProjectionError("invalid_input")
        if self.decision == "rejected_content" and self.reason != "rejected_content":
            raise ProjectionError("invalid_input")
        if self.decision == "not_required_as_of" and self.reason in {
            "known_receipt",
            "rejected_content",
        }:
            raise ProjectionError("invalid_input")

    def payload(self) -> dict[str, object]:
        from dataclasses import asdict

        return {
            "schema_version": self.schema_version,
            "kind": "delivery_processing_ack",
            "event": event_payload(self.event),
            "projected_sha256": self.projected_sha256,
            "request_sha256": self.request_sha256,
            "policy_sha256": self.policy_sha256,
            "decision": self.decision,
            "reason": self.reason,
            "observed_at_ms": self.observed_at_ms,
            "receipt": None if self.receipt is None else asdict(self.receipt),
        }

    def canonical(self) -> bytes:
        raw = canonical(self.payload())
        if len(raw) > 4096:
            raise ProjectionError("invalid_input")
        return raw


@dataclass(frozen=True, slots=True)
class ProcessingPage:
    checkpoint: ProcessingCheckpoint
    rows: tuple[ProjectedResult, ...]

    def __post_init__(self) -> None:
        if (
            type(self.checkpoint) is not ProcessingCheckpoint
            or type(self.rows) is not tuple
            or len(self.rows) > 8
        ):
            raise ProjectionError("invalid_input")
        p = self.checkpoint
        seen = set()
        for row in self.rows:
            if (
                type(row) is not ProjectedResult
                or row.event.source_id != p.binding.source_id
                or row.event.scope != p.binding.scope
                or not p.terminal_watermark < row.event.sequence <= p.projected_through
                or row.event.sequence in seen
            ):
                raise ProjectionError("invalid_input")
            seen.add(row.event.sequence)


@dataclass(frozen=True, slots=True)
class ProcessingOutcome:
    sequence: int
    state: Literal["acknowledged", "unknown", "unavailable"]
    acknowledgement: ProcessingAcknowledgement | None

    def __post_init__(self) -> None:
        if (
            integer(self.sequence) == 0
            or type(self.state) is not str
            or self.state not in {"acknowledged", "unknown", "unavailable"}
        ):
            raise ProjectionError("invalid_input")
        if (self.state == "acknowledged") != (self.acknowledgement is not None):
            raise ProjectionError("invalid_input")
        if self.acknowledgement is not None and (
            type(self.acknowledgement) is not ProcessingAcknowledgement
            or self.acknowledgement.event.sequence != self.sequence
        ):
            raise ProjectionError("invalid_input")


@dataclass(frozen=True, slots=True)
class ProcessingStep:
    before: ProcessingCheckpoint
    after: ProcessingCheckpoint
    outcomes: tuple[ProcessingOutcome, ...]

    def __post_init__(self) -> None:
        a, b = self.before, self.after
        if (
            type(a) is not ProcessingCheckpoint
            or type(b) is not ProcessingCheckpoint
            or a.binding != b.binding
            or a.policy_sha256 != b.policy_sha256
            or b.revision < a.revision
            or b.terminal_watermark < a.terminal_watermark
            or b.terminal_count < a.terminal_count
            or b.projected_through < a.projected_through
            or type(self.outcomes) is not tuple
            or len(self.outcomes) > 8
        ):
            raise ProjectionError("invalid_input")
        seen = set()
        for item in self.outcomes:
            if (
                type(item) is not ProcessingOutcome
                or item.sequence in seen
                or not a.terminal_watermark < item.sequence <= a.projected_through
            ):
                raise ProjectionError("invalid_input")
            ack = item.acknowledgement
            if ack is not None and (
                ack.event.scope != a.binding.scope
                or ack.event.source_id != a.binding.source_id
                or ack.policy_sha256 != a.policy_sha256
            ):
                raise ProjectionError("invalid_input")
            seen.add(item.sequence)


def parse_policy(raw: bytes) -> CompletionPolicy:
    from .contracts import decode
    from .projection_models import fields

    try:
        value = fields(decode(raw, 16384), {"schema_version", "kind", "receiver_id", "bindings"})
        if value["kind"] != "delivery_only_processing" or type(value["bindings"]) is not list:
            raise ProjectionError("invalid_input")
        result = CompletionPolicy(
            value["receiver_id"],
            tuple(
                DeliveryBinding(**fields(b, {"case_id", "conversation_id", "recipient_id"}))
                for b in value["bindings"]
            ),
            value["schema_version"],
        )
        if result.canonical() != raw:
            raise ProjectionError("invalid_input")
        return result
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ProjectionError("invalid_input") from None


def parse_ack(raw: bytes) -> ProcessingAcknowledgement:
    from continuity_lab.work_api import WorkError

    from .contracts import decode
    from .projection_models import fields

    try:
        value = fields(
            decode(raw, 4096),
            {
                "schema_version",
                "kind",
                "event",
                "projected_sha256",
                "request_sha256",
                "policy_sha256",
                "decision",
                "reason",
                "observed_at_ms",
                "receipt",
            },
        )
        if value.pop("kind") != "delivery_processing_ack":
            raise ProjectionError("invalid_input")
        event = fields(
            value.pop("event"),
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
        scope = WorkScope(**fields(event.pop("scope"), {"tenant_id", "account_id"}))
        receipt = value.pop("receipt")
        result = ProcessingAcknowledgement(
            event=ResultFeedEvent(scope=scope, **event),
            receipt=None
            if receipt is None
            else DeliveryReceipt(
                **fields(
                    receipt,
                    {
                        "delivery_id",
                        "receipt_id",
                        "receiver_id",
                        "recipient_id",
                        "result_sha256",
                        "accepted_at_ms",
                    },
                )
            ),
            **value,
        )
        if result.canonical() != raw:
            raise ProjectionError("invalid_input")
        return result
    except (ValueError, TypeError, KeyError, AttributeError, WorkError):
        raise ProjectionError("invalid_input") from None
