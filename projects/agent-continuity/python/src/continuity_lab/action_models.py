"""Generic persisted result guards and exact case-intent receipts, without P3 schemas."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol, cast

from .case_models import ActionIntent, Confirmation, identity, integer
from .postgres_settings import validate_identifier
from .work_models import WorkScope, work_identifier, work_milliseconds, work_uuid

ActionCode = Literal[
    "invalid_input",
    "unauthorized",
    "not_found",
    "identity_conflict",
    "capacity",
    "expired",
    "storage_unavailable",
    "acknowledgement_unknown",
    "schema_mismatch",
    "closed",
    "cleanup_incomplete",
    "stale_revision",
    "case_cancelled",
    "quote_expired",
    "deadline_expired",
    "invalid_confirmation",
    "intent_committed",
    "invalid_result",
]
_CODES = frozenset(
    {
        "invalid_input",
        "unauthorized",
        "not_found",
        "identity_conflict",
        "capacity",
        "expired",
        "storage_unavailable",
        "acknowledgement_unknown",
        "schema_mismatch",
        "closed",
        "cleanup_incomplete",
        "stale_revision",
        "case_cancelled",
        "quote_expired",
        "deadline_expired",
        "invalid_confirmation",
        "intent_committed",
        "invalid_result",
    }
)


class ActionError(RuntimeError):
    """One fixed safe code; neither a retry instruction nor proof an intent rolled back."""

    def __init__(self, code: str) -> None:
        self.code: ActionCode = cast(
            ActionCode, code if type(code) is str and code in _CODES else "invalid_input"
        )
        super().__init__(self.code)


def result_digest(value: str) -> str:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ActionError("invalid_input")
    return value


@dataclass(frozen=True, slots=True)
class ActionReceipt:
    """Original guarded commitment; later expiry/cancellation cannot erase this fact."""

    action_id: str
    scope: WorkScope
    work_id: str
    attempt_id: str
    result_sha256: str
    case_schema: str
    case_scope_id: str
    case_actor_id: str
    case_task_id: str
    case_id: str
    expected_revision: int
    command_id: str
    confirmation: Confirmation = field(repr=False)
    intent: ActionIntent = field(repr=False)
    committed_at_ms: int

    def __post_init__(self) -> None:
        try:
            if (
                type(self.scope) is not WorkScope
                or type(self.confirmation) is not Confirmation
                or type(self.intent) is not ActionIntent
            ):
                raise ValueError
            for value in (
                self.action_id,
                self.work_id,
                self.attempt_id,
                self.case_task_id,
                self.case_id,
            ):
                work_uuid(value)
            result_digest(self.result_sha256)
            validate_identifier(self.case_schema)
            identity(self.case_scope_id)
            identity(self.case_actor_id)
            work_identifier(self.command_id)
            integer(self.expected_revision)
            work_milliseconds(self.committed_at_ms)
            quote = self.confirmation.quote
            if (
                quote.schema_version != 2
                or quote.task_id != self.case_task_id
                or quote.case_id != self.case_id
                or quote.revision != self.expected_revision
                or self.intent.quote != quote
                or self.intent.task_id != self.case_task_id
                or self.intent.scope_id != self.case_scope_id
                or self.intent.actor_id != self.case_actor_id
            ):
                raise ValueError
        except (ValueError, TypeError, AttributeError, RuntimeError):
            raise ActionError("invalid_input") from None


class ActionPort(Protocol):
    @property
    def scope(self) -> WorkScope: ...
    @property
    def case_actor_id(self) -> str: ...
    @property
    def case_scope_id(self) -> str: ...
    @property
    def case_schema(self) -> str: ...
    @property
    def pending_count(self) -> int: ...
    def metrics(self) -> Mapping[str, int]: ...
    async def authorize(
        self,
        *,
        work_id: str,
        attempt_id: str,
        result_sha256: str,
        expected_revision: int,
        confirmation: Confirmation,
        command_id: str,
    ) -> ActionReceipt: ...
    async def find_action(self, *, command_id: str) -> ActionReceipt | None: ...
    async def action(self, *, work_id: str) -> ActionReceipt | None: ...
    async def close(self) -> None: ...
