"""Private metadata CAS; external result/receiver I/O never occurs in this transaction."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from contextlib import closing

from psycopg import sql
from psycopg.errors import SerializationFailure

from continuity_lab.work_api import PostgresSettings

from .applicability_schema import MARKER_V3
from .processing_models import (
    CompletionPolicy,
    ProcessingAcknowledgement,
    ProcessingCheckpoint,
    ProcessingPage,
    parse_ack,
    parse_policy,
    snapshot_policy,
)
from .processing_schema import MARKER_V2
from .projection_models import ProjectedResult, ProjectionBinding, ProjectionError, event_digest
from .projection_store import ConnectionType, ProjectionStore, settings, validate


class ProcessingStore:
    def __init__(
        self,
        value: PostgresSettings,
        binding: ProjectionBinding,
        policy: CompletionPolicy,
        failpoint: Callable[[str], None] | None = None,
    ) -> None:
        self.settings = settings(value)
        self.binding = binding
        self.policy = snapshot_policy(policy)
        self.failpoint = failpoint
        self._projection = ProjectionStore(value, binding)
        self.checkpoint()

    def _table(self, name: str) -> sql.Identifier:
        return sql.Identifier(self.settings.schema, name)

    def _state(self, c: ConnectionType) -> ProcessingCheckpoint:
        point, _limits = validate(c, self.settings, binding=self.binding)
        marker = c.execute(
            "SELECT obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=%s",
            [self.settings.schema],
        ).fetchone()
        if marker not in ({"marker": MARKER_V2}, {"marker": MARKER_V3}):
            raise ProjectionError("schema_mismatch")
        rows = c.execute(
            sql.SQL("SELECT * FROM {}").format(self._table("processing_control"))
        ).fetchall()
        if len(rows) != 1:
            raise ProjectionError("schema_mismatch")
        row = rows[0]
        raw = row["policy_json"].encode()
        if (
            hashlib.sha256(raw).hexdigest() != row["policy_sha256"]
            or parse_policy(raw).sha256 != self.policy.sha256
        ):
            raise ProjectionError("identity_conflict")
        counts = c.execute(
            sql.SQL("SELECT count(*) AS count FROM {}").format(self._table("processing_acks"))
        ).fetchone()
        gap = c.execute(
            sql.SQL(
                "SELECT p.event_sequence FROM {} p WHERE NOT EXISTS(SELECT 1 FROM {} a WHERE a.event_sequence=p.event_sequence) ORDER BY p.event_sequence LIMIT 1"
            ).format(self._table("projected_results"), self._table("processing_acks"))
        ).fetchone()
        watermark = point.sequence if gap is None else gap["event_sequence"] - 1
        if (
            counts is None
            or counts["count"] != row["terminal_count"]
            or watermark != row["terminal_watermark"]
        ):
            raise ProjectionError("schema_mismatch")
        return ProcessingCheckpoint(
            self.binding,
            self.policy.sha256,
            row["revision"],
            row["terminal_watermark"],
            row["scan_after"],
            row["terminal_count"],
            point.sequence,
        )

    def _row(self, c: ConnectionType, sequence: int) -> ProjectedResult:
        row = c.execute(
            sql.SQL("SELECT * FROM {} WHERE event_sequence=%s").format(
                self._table("projected_results")
            ),
            [sequence],
        ).fetchone()
        if row is None:
            raise ProjectionError("not_found")
        return self._projection._decode(row)

    def _ack(self, c: ConnectionType, row: ProjectedResult) -> ProcessingAcknowledgement | None:
        value = c.execute(
            sql.SQL("SELECT * FROM {} WHERE event_sequence=%s").format(
                self._table("processing_acks")
            ),
            [row.event.sequence],
        ).fetchone()
        if value is None:
            return None
        try:
            raw = value["body_json"].encode()
            ack = parse_ack(raw)
            if (
                hashlib.sha256(raw).hexdigest() != value["body_sha256"]
                or value["event_id"].__str__() != ack.event.event_id
                or value["projected_sha256"] != ack.projected_sha256
            ):
                raise ProjectionError("schema_mismatch")
            self._identity(row, ack)
            return ack
        except (ValueError, TypeError, KeyError, AttributeError, ProjectionError):
            raise ProjectionError("schema_mismatch") from None

    def _identity(self, row: ProjectedResult, ack: ProcessingAcknowledgement) -> None:
        if (
            event_digest(ack.event) != event_digest(row.event)
            or ack.request_sha256 != row.request_sha256
            or ack.projected_sha256 != hashlib.sha256(row.canonical()).hexdigest()
            or ack.policy_sha256 != self.policy.sha256
        ):
            raise ProjectionError("identity_conflict")
        if (ack.decision == "rejected_content") != (row.validation == "rejected"):
            raise ProjectionError("identity_conflict")
        if ack.decision == "receiver_accepted" and row.event.disposition != "eligible_at_commit":
            raise ProjectionError("identity_conflict")
        if ack.receipt is not None and (
            ack.receipt.receiver_id != self.policy.receiver_id
            or not any(
                b.case_id == row.case_id and b.recipient_id == ack.receipt.recipient_id
                for b in self.policy.bindings
            )
        ):
            raise ProjectionError("identity_conflict")

    def checkpoint(self) -> ProcessingCheckpoint:
        try:
            with closing(self.settings.connect()) as c, c.transaction():
                c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                return self._state(c)
        except ProjectionError:
            raise
        except Exception:  # noqa: BLE001 - fixed private SQL boundary
            raise ProjectionError("storage_unavailable") from None

    def acknowledgement(self, event_id: str) -> ProcessingAcknowledgement | None:
        try:
            with closing(self.settings.connect()) as c, c.transaction():
                c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                self._state(c)
                row = c.execute(
                    sql.SQL("SELECT event_sequence FROM {} WHERE event_id=%s::uuid").format(
                        self._table("projected_results")
                    ),
                    [event_id],
                ).fetchone()
                return None if row is None else self._ack(c, self._row(c, row["event_sequence"]))
        except ProjectionError:
            raise
        except Exception:  # noqa: BLE001 - fixed private SQL boundary
            raise ProjectionError("storage_unavailable") from None

    def page(self, limit: int) -> ProcessingPage:
        try:
            with closing(self.settings.connect()) as c, c.transaction():
                c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                point = self._state(c)
                query = sql.SQL(
                    "SELECT p.* FROM {} p WHERE p.event_sequence>%s AND p.event_sequence<=%s AND NOT EXISTS(SELECT 1 FROM {} a WHERE a.event_sequence=p.event_sequence) ORDER BY p.event_sequence LIMIT %s"
                ).format(self._table("projected_results"), self._table("processing_acks"))
                rows = c.execute(
                    query, [point.scan_after, point.projected_through, limit]
                ).fetchall()
                if len(rows) < limit and point.scan_after > point.terminal_watermark:
                    rows += c.execute(
                        query, [point.terminal_watermark, point.scan_after, limit - len(rows)]
                    ).fetchall()
                return ProcessingPage(point, tuple(self._projection._decode(row) for row in rows))
        except ProjectionError:
            raise
        except Exception:  # noqa: BLE001 - fixed private SQL boundary
            raise ProjectionError("storage_unavailable") from None

    def commit(
        self,
        expected: ProcessingCheckpoint,
        draft: ProjectedResult,
        ack: ProcessingAcknowledgement | None,
    ) -> tuple[ProcessingCheckpoint, ProcessingAcknowledgement | None]:
        committing = False
        try:
            with closing(self.settings.connect()) as c:
                with c.transaction():
                    c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                    c.execute(
                        sql.SQL("SELECT singleton FROM {} WHERE singleton FOR UPDATE").format(
                            self._table("processing_control")
                        )
                    )
                    if self.failpoint is not None:
                        self.failpoint("processing.snapshot.established")
                    point = self._state(c)
                    row = self._row(c, draft.event.sequence)
                    if row.canonical() != draft.canonical():
                        raise ProjectionError("identity_conflict")
                    original = self._ack(c, row)
                    if original is not None:
                        return point, original
                    if (
                        point.revision != expected.revision
                        or point.binding != expected.binding
                        or point.policy_sha256 != expected.policy_sha256
                    ):
                        raise ProjectionError("checkpoint_conflict")
                    if point.revision >= 9223372036854775807:
                        raise ProjectionError("capacity")
                    count = point.terminal_count
                    if ack is not None:
                        self._identity(row, ack)
                        raw = ack.canonical()
                        c.execute(
                            sql.SQL("INSERT INTO {} VALUES(%s,%s::uuid,%s,%s,%s)").format(
                                self._table("processing_acks")
                            ),
                            [
                                row.event.sequence,
                                row.event.event_id,
                                ack.projected_sha256,
                                raw.decode(),
                                hashlib.sha256(raw).hexdigest(),
                            ],
                        )
                        count += 1
                    gap = c.execute(
                        sql.SQL(
                            "SELECT p.event_sequence FROM {} p WHERE NOT EXISTS(SELECT 1 FROM {} a WHERE a.event_sequence=p.event_sequence) ORDER BY p.event_sequence LIMIT 1"
                        ).format(self._table("projected_results"), self._table("processing_acks"))
                    ).fetchone()
                    watermark = (
                        point.projected_through if gap is None else gap["event_sequence"] - 1
                    )
                    scan = max(watermark, row.event.sequence)
                    changed = c.execute(
                        sql.SQL(
                            "UPDATE {} SET revision=%s,terminal_watermark=%s,scan_after=%s,terminal_count=%s WHERE singleton AND revision=%s"
                        ).format(self._table("processing_control")),
                        [point.revision + 1, watermark, scan, count, point.revision],
                    )
                    if changed.rowcount != 1:
                        raise ProjectionError("checkpoint_conflict")
                    after = ProcessingCheckpoint(
                        self.binding,
                        self.policy.sha256,
                        point.revision + 1,
                        watermark,
                        scan,
                        count,
                        point.projected_through,
                    )
                    stage = "processing.ack" if ack is not None else "processing.scan"
                    if self.failpoint is not None:
                        self.failpoint(stage + ".before_commit")
                    committing = True
                if self.failpoint is not None:
                    self.failpoint(stage + ".after_commit")
            return after, ack
        except SerializationFailure:
            raise ProjectionError("checkpoint_conflict") from None
        except ProjectionError:
            if committing:
                raise ProjectionError("acknowledgement_unknown") from None
            raise
        except Exception:  # noqa: BLE001 - never relabel uncertain commit as definite failure
            raise ProjectionError(
                "acknowledgement_unknown" if committing else "storage_unavailable"
            ) from None

    def reconcile(
        self, draft: ProjectedResult
    ) -> tuple[ProcessingCheckpoint, ProcessingAcknowledgement] | None:
        try:
            with closing(self.settings.connect()) as c, c.transaction():
                c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                point = self._state(c)
                row = self._row(c, draft.event.sequence)
                if row.canonical() != draft.canonical():
                    raise ProjectionError("identity_conflict")
                ack = self._ack(c, row)
                return None if ack is None else (point, ack)
        except ProjectionError:
            raise
        except Exception:  # noqa: BLE001 - safe exact lookup boundary
            raise ProjectionError("storage_unavailable") from None
