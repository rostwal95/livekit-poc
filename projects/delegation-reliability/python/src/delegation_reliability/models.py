"""Bounded immutable inputs and safe observations for the scripted P3-A experiment."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Literal

BaselineMode = Literal["single_tool", "native_task_group"]
MAX_INPUT_BYTES = 2048
MAX_NOTE_BYTES = 512
POLICY_VERSION = "synthetic-notice-v1"


class BaselineError(RuntimeError):
    """Safe finite diagnostic code; never contains supplied input or SDK exceptions."""

    code = "baseline_failed"

    def __init__(self) -> None:
        super().__init__(self.code)


class BaselineInputError(BaselineError):
    code = "invalid_input"


class BaselineTimeout(BaselineError):
    code = "baseline_timeout"


class BaselineCleanupError(BaselineError):
    code = "baseline_cleanup_failed"


class BaselineInvariantError(BaselineError):
    code = "baseline_invariant"


@dataclass(frozen=True, slots=True)
class PolicyInput:
    """Synthetic read-only policy facts, not verified customer or case authority."""

    case_revision: int = 1
    days_before_arrival: int = 14
    policy_version: str = POLICY_VERSION
    note: str = "synthetic fixture"

    def __post_init__(self) -> None:
        if (
            type(self.case_revision) is not int
            or not 1 <= self.case_revision <= 1_000_000
            or type(self.days_before_arrival) is not int
            or not 0 <= self.days_before_arrival <= 3650
            or type(self.policy_version) is not str
            or self.policy_version != POLICY_VERSION
            or type(self.note) is not str
        ):
            raise BaselineInputError()
        try:
            if len(self.note.encode("utf-8")) > MAX_NOTE_BYTES:
                raise BaselineInputError()
        except UnicodeEncodeError:
            raise BaselineInputError() from None

    @classmethod
    def from_json(cls, payload: bytes) -> PolicyInput:
        if type(payload) is not bytes or not 0 < len(payload) <= MAX_INPUT_BYTES:
            raise BaselineInputError()
        try:
            value = json.loads(payload, object_pairs_hook=_unique_object)
        except (ValueError, UnicodeError, RecursionError):
            raise BaselineInputError() from None
        if type(value) is not dict or set(value) != {
            "case_revision",
            "days_before_arrival",
            "policy_version",
            "note",
        }:
            raise BaselineInputError()
        return cls(**value)

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise BaselineInputError()
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class PolicyResult:
    case_revision: int
    input_fingerprint: str
    policy_version: str
    outcome: Literal["eligible", "clarification_required"]
    evidence_rule: str

    def as_tool_output(self) -> str:
        return json.dumps({"status": "completed", **asdict(self)}, sort_keys=True)


def evaluate_policy(value: PolicyInput) -> PolicyResult:
    """Evaluate one fixed synthetic rule; a result grants no mutation permission."""
    return PolicyResult(
        case_revision=value.case_revision,
        input_fingerprint=value.fingerprint,
        policy_version=value.policy_version,
        outcome="eligible" if value.days_before_arrival >= 7 else "clarification_required",
        evidence_rule="notice.minimum-seven-days",
    )


@dataclass(frozen=True, slots=True)
class BaselineObservation:
    mode: BaselineMode
    result: PolicyResult
    input_fingerprint: str
    held_response_code: str
    held_response_seconds: float
    completion_seconds: float
    result_absent_while_held: bool
    result_observed_in_sdk: bool
    native_task_count: int
    native_group_completed: bool
    sdk_tool_calls: int
    sdk_handoffs: int
    fixture_model_calls: int
    evaluations_completed: int
    active_after_cleanup: int
    cleanup_complete: bool
