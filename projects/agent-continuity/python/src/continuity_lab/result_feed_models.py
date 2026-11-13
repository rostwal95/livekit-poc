"""Immutable scoped source references; a feed event grants no action authority."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Protocol

from .issued_models import ResultDisposition
from .work_models import WorkError, WorkScope, work_identifier, work_milliseconds, work_uuid

MAX_FEED_SEQUENCE = 9_223_372_036_854_775_807
FeedOrigin = Literal["live", "adopted_history"]


def sequence(value: int) -> int:
    if type(value) is not int or not 0 <= value <= MAX_FEED_SEQUENCE:
        raise WorkError("invalid_input")
    return value


def copy_scope(value: WorkScope) -> WorkScope:
    if type(value) is not WorkScope:
        raise WorkError("invalid_input")
    return WorkScope(value.tenant_id, value.account_id)


@dataclass(frozen=True, slots=True)
class ResultFeedCursor:
    source_id: str
    scope: WorkScope
    sequence: int

    def __post_init__(self) -> None:
        work_uuid(self.source_id)
        copy_scope(self.scope)
        sequence(self.sequence)


def copy_cursor(value: ResultFeedCursor) -> ResultFeedCursor:
    if type(value) is not ResultFeedCursor:
        raise WorkError("invalid_input")
    return ResultFeedCursor(value.source_id, copy_scope(value.scope), value.sequence)


@dataclass(frozen=True, slots=True)
class ResultFeedEvent:
    event_id: str
    source_id: str
    scope: WorkScope
    sequence: int
    work_id: str
    attempt_id: str
    issue_command_id: str
    result_sha256: str
    recorded_at_ms: int
    disposition: ResultDisposition
    origin: FeedOrigin
    kind: Literal["result_recorded"] = "result_recorded"

    def __post_init__(self) -> None:
        for value in (self.event_id, self.source_id, self.work_id, self.attempt_id):
            work_uuid(value)
        copy_scope(self.scope)
        if sequence(self.sequence) == 0:
            raise WorkError("invalid_input")
        work_identifier(self.issue_command_id)
        work_milliseconds(self.recorded_at_ms)
        if (
            type(self.result_sha256) is not str
            or re.fullmatch(r"[0-9a-f]{64}", self.result_sha256) is None
            or type(self.disposition) is not str
            or self.disposition
            not in {"eligible_at_commit", "cancelled", "expired", "superseded", "lease_expired"}
            or type(self.origin) is not str
            or self.origin not in {"live", "adopted_history"}
            or type(self.kind) is not str
            or self.kind != "result_recorded"
        ):
            raise WorkError("invalid_input")


@dataclass(frozen=True, slots=True)
class ResultFeedPage:
    source_id: str
    scope: WorkScope
    after: ResultFeedCursor
    events: tuple[ResultFeedEvent, ...]
    next_cursor: ResultFeedCursor
    high_watermark: ResultFeedCursor
    has_more: bool

    def __post_init__(self) -> None:
        work_uuid(self.source_id)
        copy_scope(self.scope)
        cursors = (self.after, self.next_cursor, self.high_watermark)
        if any(
            type(c) is not ResultFeedCursor
            or c.source_id != self.source_id
            or c.scope != self.scope
            for c in cursors
        ):
            raise WorkError("invalid_input")
        if (
            type(self.events) is not tuple
            or len(self.events) > 100
            or type(self.has_more) is not bool
        ):
            raise WorkError("invalid_input")
        expected = self.after.sequence
        for event in self.events:
            expected += 1
            if (
                type(event) is not ResultFeedEvent
                or event.source_id != self.source_id
                or event.scope != self.scope
                or event.sequence != expected
            ):
                raise WorkError("invalid_input")
        if (
            self.next_cursor.sequence != expected
            or self.high_watermark.sequence < expected
            or self.has_more != (expected < self.high_watermark.sequence)
        ):
            raise WorkError("invalid_input")


class ResultFeedPort(Protocol):
    @property
    def scope(self) -> WorkScope: ...
    @property
    def source_id(self) -> str: ...
    @property
    def pending_count(self) -> int: ...
    async def read(
        self, *, after: ResultFeedCursor | None = None, limit: int = 25
    ) -> ResultFeedPage: ...
    async def close(self) -> None: ...
