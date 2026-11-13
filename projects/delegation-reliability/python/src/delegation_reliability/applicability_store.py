"""Private refresh/display metadata CAS; no external I/O occurs in transactions."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from contextlib import closing
from typing import Any

from psycopg import sql
from psycopg.errors import SerializationFailure, UniqueViolation

from continuity_lab.work_api import PostgresSettings

from .applicability_models import (
    ApplicabilityRefresh,
    ApplicabilityView,
    DisplayTombstone,
    RefreshPolicy,
    _RefreshDraft,
    parse_refresh,
    parse_refresh_policy,
    parse_tombstone,
    refreshed,
)
from .applicability_schema import MARKER_V3
from .projection_models import (
    ProjectedResult,
    ProjectionBinding,
    ProjectionError,
    event_digest,
    integer,
)
from .projection_store import ConnectionType, ProjectionStore, settings, validate


class ApplicabilityStore:
    def __init__(
        self,
        value: PostgresSettings,
        binding: ProjectionBinding,
        policy: RefreshPolicy,
        failpoint: Callable[[str], None] | None = None,
    ) -> None:
        self.settings = settings(value)
        self.binding = binding
        self.policy = parse_refresh_policy(policy.canonical())
        self.failpoint = failpoint
        self._projection = ProjectionStore(value, binding)
        self._validate_startup()

    def _table(self, name: str) -> sql.Identifier:
        return sql.Identifier(self.settings.schema, name)

    def _state(self, c: ConnectionType) -> int:
        validate(c, self.settings, binding=self.binding)
        marker = c.execute(
            "SELECT obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=%s",
            [self.settings.schema],
        ).fetchone()
        if marker != {"marker": MARKER_V3}:
            raise ProjectionError("schema_mismatch")
        rows = c.execute(
            sql.SQL("SELECT * FROM {}").format(self._table("refresh_control"))
        ).fetchall()
        if len(rows) != 1:
            raise ProjectionError("schema_mismatch")
        row = rows[0]
        raw = row["policy_json"].encode()
        if (
            hashlib.sha256(raw).hexdigest() != row["policy_sha256"]
            or parse_refresh_policy(raw).sha256 != self.policy.sha256
        ):
            raise ProjectionError("identity_conflict")
        count = c.execute(
            sql.SQL("SELECT count(*) AS count FROM {}").format(
                self._table("applicability_refreshes")
            )
        ).fetchone()
        if (
            count is None
            or count["count"] != row["command_count"]
            or not 0 <= row["command_count"] <= self.policy.max_commands
        ):
            raise ProjectionError("schema_mismatch")
        return integer(row["command_count"], self.policy.max_commands)

    def _validate_startup(self) -> None:
        try:
            with closing(self.settings.connect()) as c, c.transaction():
                c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                self._state(c)
        except ProjectionError:
            raise
        except Exception:  # noqa: BLE001 - fixed storage boundary
            raise ProjectionError("storage_unavailable") from None

    def _row(self, c: ConnectionType, work_id: str, attempt_id: str) -> ProjectedResult:
        row = c.execute(
            sql.SQL("SELECT * FROM {} WHERE work_id=%s::uuid AND attempt_id=%s::uuid").format(
                self._table("projected_results")
            ),
            [work_id, attempt_id],
        ).fetchone()
        if row is None:
            raise ProjectionError("not_found")
        return self._projection._decode(row)

    def _identity(
        self, row: ProjectedResult, receipt: ApplicabilityRefresh | DisplayTombstone
    ) -> None:
        if (
            event_digest(receipt.event) != event_digest(row.event)
            or receipt.projected_sha256 != hashlib.sha256(row.canonical()).hexdigest()
            or receipt.request_sha256 != row.request_sha256
            or receipt.policy_sha256 != self.policy.sha256
            or (
                isinstance(receipt, ApplicabilityRefresh)
                and receipt.request_revision != row.request_revision
            )
        ):
            raise ProjectionError("schema_mismatch")

    def _decode(self, c: ConnectionType, value: dict[str, Any]) -> ApplicabilityRefresh:
        try:
            raw = value["body_json"].encode()
            receipt = parse_refresh(raw)
            if (
                hashlib.sha256(raw).hexdigest() != value["body_sha256"]
                or receipt.command_id != str(value["command_id"])
                or receipt.event.sequence != value["event_sequence"]
                or receipt.revision != value["revision"]
                or receipt.event.source_id != self.binding.source_id
                or receipt.event.scope != self.binding.scope
            ):
                raise ProjectionError("schema_mismatch")
            row = self._row(c, receipt.event.work_id, receipt.event.attempt_id)
            self._identity(row, receipt)
            return receipt
        except Exception:  # noqa: BLE001 - corrupted/foreign metadata never escapes
            raise ProjectionError("schema_mismatch") from None

    def _command(self, c: ConnectionType, command_id: str) -> ApplicabilityRefresh | None:
        value = c.execute(
            sql.SQL("SELECT * FROM {} WHERE command_id=%s::uuid").format(
                self._table("applicability_refreshes")
            ),
            [command_id],
        ).fetchone()
        return None if value is None else self._decode(c, value)

    def _view(self, c: ConnectionType, row: ProjectedResult) -> ApplicabilityView:
        head = c.execute(
            sql.SQL("SELECT * FROM {} WHERE event_sequence=%s").format(
                self._table("applicability_heads")
            ),
            [row.event.sequence],
        ).fetchone()
        if head is None:
            return ApplicabilityView(row, 0, None, None)
        revision = head["revision"]
        latest = (
            None
            if head["latest_command_id"] is None
            else self._command(c, str(head["latest_command_id"]))
        )
        count = c.execute(
            sql.SQL("SELECT count(*) AS count FROM {} WHERE event_sequence=%s").format(
                self._table("applicability_refreshes")
            ),
            [row.event.sequence],
        ).fetchone()
        if count is None or count["count"] != revision or revision > self.policy.max_per_result:
            raise ProjectionError("schema_mismatch")
        tombstone = None
        if head["tombstone_json"] is not None:
            raw = head["tombstone_json"].encode()
            tombstone = parse_tombstone(raw)
            if hashlib.sha256(raw).hexdigest() != head["tombstone_sha256"]:
                raise ProjectionError("schema_mismatch")
            self._identity(row, tombstone)
        if latest is not None:
            self._identity(row, latest)
        try:
            return ApplicabilityView(row, revision, latest, tombstone)
        except ProjectionError:
            raise ProjectionError("schema_mismatch") from None

    def command(self, command_id: str) -> ApplicabilityRefresh | None:
        try:
            with closing(self.settings.connect()) as c, c.transaction():
                c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                self._state(c)
                return self._command(c, command_id)
        except ProjectionError:
            raise
        except Exception:  # noqa: BLE001 - fixed safe storage boundary
            raise ProjectionError("storage_unavailable") from None

    def inspect(self, work_id: str, attempt_id: str) -> ApplicabilityView:
        try:
            with closing(self.settings.connect()) as c, c.transaction():
                c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                self._state(c)
                return self._view(c, self._row(c, work_id, attempt_id))
        except ProjectionError:
            raise
        except Exception:  # noqa: BLE001 - fixed safe storage boundary
            raise ProjectionError("storage_unavailable") from None

    @staticmethod
    def semantic_match(
        value: ApplicabilityRefresh, work_id: str, attempt_id: str, expected_revision: int
    ) -> None:
        if (value.event.work_id, value.event.attempt_id, value.expected_revision) != (
            work_id,
            attempt_id,
            expected_revision,
        ):
            raise ProjectionError("identity_conflict")

    def commit(
        self, command_id: str, expected_revision: int, draft: _RefreshDraft
    ) -> ApplicabilityRefresh:
        committing = False
        try:
            with closing(self.settings.connect()) as c:
                with c.transaction():
                    c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                    c.execute(
                        sql.SQL("SELECT singleton FROM {} WHERE singleton FOR UPDATE").format(
                            self._table("refresh_control")
                        )
                    )
                    count = self._state(c)
                    original = self._command(c, command_id)
                    event = draft.projection.event
                    if original is not None:
                        self.semantic_match(
                            original, event.work_id, event.attempt_id, expected_revision
                        )
                        return original
                    row = self._row(c, event.work_id, event.attempt_id)
                    if row.canonical() != draft.projection.canonical():
                        raise ProjectionError("identity_conflict")
                    view = self._view(c, row)
                    if view.revision != expected_revision:
                        raise ProjectionError("checkpoint_conflict")
                    if (
                        count >= self.policy.max_commands
                        or view.revision >= self.policy.max_per_result
                    ):
                        raise ProjectionError("capacity")
                    receipt = refreshed(
                        command_id=command_id,
                        expected_revision=expected_revision,
                        policy=self.policy,
                        draft=draft,
                        previous=view.latest,
                        observed_at_ms=time.time_ns() // 1_000_000,
                    )
                    raw = receipt.canonical()
                    c.execute(
                        sql.SQL("INSERT INTO {} VALUES(%s::uuid,%s,%s,%s,%s)").format(
                            self._table("applicability_refreshes")
                        ),
                        [
                            command_id,
                            event.sequence,
                            receipt.revision,
                            raw.decode(),
                            hashlib.sha256(raw).hexdigest(),
                        ],
                    )
                    changed = c.execute(
                        sql.SQL(
                            "INSERT INTO {}(event_sequence,revision,latest_command_id) VALUES(%s,%s,%s::uuid) ON CONFLICT(event_sequence) DO UPDATE SET revision=EXCLUDED.revision,latest_command_id=EXCLUDED.latest_command_id WHERE {}.revision=%s"
                        ).format(
                            self._table("applicability_heads"),
                            sql.Identifier("applicability_heads"),
                        ),
                        [event.sequence, receipt.revision, command_id, expected_revision],
                    )
                    if changed.rowcount != 1:
                        raise ProjectionError("checkpoint_conflict")
                    c.execute(
                        sql.SQL(
                            "UPDATE {} SET command_count=command_count+1 WHERE singleton"
                        ).format(self._table("refresh_control"))
                    )
                    if self.failpoint is not None:
                        self.failpoint("applicability.refresh.before_commit")
                    committing = True
                if self.failpoint is not None:
                    self.failpoint("applicability.refresh.after_commit")
                return receipt
        except SerializationFailure:
            raise ProjectionError("checkpoint_conflict") from None
        except UniqueViolation:
            raise ProjectionError("identity_conflict") from None
        except ProjectionError:
            if committing:
                raise ProjectionError("acknowledgement_unknown") from None
            raise
        except Exception:  # noqa: BLE001 - preserve ambiguous commit, never retry
            raise ProjectionError(
                "acknowledgement_unknown" if committing else "storage_unavailable"
            ) from None

    def hide(self, work_id: str, attempt_id: str) -> DisplayTombstone:
        committing = False
        try:
            with closing(self.settings.connect()) as c:
                with c.transaction():
                    c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                    c.execute(
                        sql.SQL("SELECT singleton FROM {} WHERE singleton FOR UPDATE").format(
                            self._table("refresh_control")
                        )
                    )
                    self._state(c)
                    row = self._row(c, work_id, attempt_id)
                    view = self._view(c, row)
                    if view.tombstone is not None:
                        return view.tombstone
                    tombstone = DisplayTombstone(
                        row.event,
                        hashlib.sha256(row.canonical()).hexdigest(),
                        row.request_sha256,
                        self.policy.sha256,
                        time.time_ns() // 1_000_000,
                    )
                    raw = tombstone.canonical()
                    c.execute(
                        sql.SQL(
                            "INSERT INTO {}(event_sequence,revision,latest_command_id,tombstone_json,tombstone_sha256) VALUES(%s,0,NULL,%s,%s) ON CONFLICT(event_sequence) DO UPDATE SET tombstone_json=EXCLUDED.tombstone_json,tombstone_sha256=EXCLUDED.tombstone_sha256 WHERE {}.tombstone_json IS NULL"
                        ).format(
                            self._table("applicability_heads"),
                            sql.Identifier("applicability_heads"),
                        ),
                        [row.event.sequence, raw.decode(), hashlib.sha256(raw).hexdigest()],
                    )
                    if self.failpoint is not None:
                        self.failpoint("applicability.hide.before_commit")
                    committing = True
                if self.failpoint is not None:
                    self.failpoint("applicability.hide.after_commit")
                return tombstone
        except SerializationFailure:
            raise ProjectionError("checkpoint_conflict") from None
        except ProjectionError:
            if committing:
                raise ProjectionError("acknowledgement_unknown") from None
            raise
        except Exception:  # noqa: BLE001 - preserve uncertain metadata write
            raise ProjectionError(
                "acknowledgement_unknown" if committing else "storage_unavailable"
            ) from None
