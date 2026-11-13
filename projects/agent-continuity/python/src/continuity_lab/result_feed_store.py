"""Generic immutable result references, serialized by the existing work admission guard."""

from __future__ import annotations

from contextlib import closing
from uuid import uuid4

from psycopg import sql

from .result_feed_models import ResultFeedCursor, ResultFeedEvent, ResultFeedPage
from .work_models import WorkError, WorkScope, work_uuid
from .work_schema import Connection, execution_limits, validate_work_schema, work_schema_version
from .work_store import WorkStore


def source_id(connection: Connection, schema: str) -> str:
    rows = connection.execute(
        sql.SQL("SELECT singleton,source_id::text,adopted_at_ms FROM {}.result_feed_source").format(
            sql.Identifier(schema)
        )
    ).fetchall()
    if (
        len(rows) != 1
        or rows[0]["singleton"] is not True
        or type(rows[0]["adopted_at_ms"]) is not int
        or not 0 <= rows[0]["adopted_at_ms"] <= 4102444800000
    ):
        raise WorkError("schema_mismatch")
    try:
        return work_uuid(rows[0]["source_id"])
    except WorkError:
        raise WorkError("schema_mismatch") from None


def validate_feed_state(connection: Connection, schema: str) -> None:
    """Validate one coherent snapshot; no pruning or source repair is performed."""
    source_id(connection, schema)
    row = connection.execute(
        sql.SQL("""
        SELECT (SELECT count(*) FROM {}.accepted_work) AS works,
        (SELECT count(*) FROM {}.attempt_results) AS results,
        (SELECT count(*) FROM {}.result_feed_events) AS events,
        (SELECT count(*) FROM {}.result_feed_heads) AS heads,
        EXISTS(SELECT 1 FROM {}.result_feed_heads h LEFT JOIN
          (SELECT tenant_id,account_id,count(*) AS n,max(sequence) AS last FROM {}.result_feed_events GROUP BY tenant_id,account_id) e
          USING(tenant_id,account_id) WHERE h.last_sequence<>coalesce(e.n,0) OR h.last_sequence<>coalesce(e.last,0)) AS invalid_head,
        (SELECT max_records FROM {}.schema_metadata WHERE singleton) AS maximum
    """).format(*([sql.Identifier(schema)] * 7))
    ).fetchone()
    if (
        row is None
        or row["results"] != row["events"]
        or row["heads"] > row["works"]
        or row["works"] > row["maximum"]
        or row["events"] > row["maximum"] * execution_limits(connection, schema).max_attempts
        or row["invalid_head"] is not False
    ):
        raise WorkError("schema_mismatch")


def append_result_event(
    connection: Connection, schema: str, scope: WorkScope, work_id: str, attempt_id: str
) -> None:
    """Call only after result INSERT under the existing admission lock, in that TX."""
    head = sql.Identifier(schema, "result_feed_heads")
    connection.execute(
        sql.SQL(
            "INSERT INTO {} VALUES(%s,%s,%s::uuid,0) ON CONFLICT(tenant_id,account_id) DO NOTHING"
        ).format(head),
        [scope.tenant_id, scope.account_id, work_id],
    )
    row = connection.execute(
        sql.SQL(
            "SELECT last_sequence FROM {} WHERE tenant_id=%s AND account_id=%s FOR UPDATE"
        ).format(head),
        [scope.tenant_id, scope.account_id],
    ).fetchone()
    if row is None or not 0 <= row["last_sequence"] < 30000:
        raise WorkError("schema_mismatch")
    number = row["last_sequence"] + 1
    changed = connection.execute(
        sql.SQL(
            "UPDATE {} SET last_sequence=%s WHERE tenant_id=%s AND account_id=%s AND last_sequence=%s"
        ).format(head),
        [number, scope.tenant_id, scope.account_id, number - 1],
    )
    if changed.rowcount != 1:
        raise WorkError("schema_mismatch")
    connection.execute(
        sql.SQL(
            "INSERT INTO {}.result_feed_events VALUES(%s::uuid,%s,%s,%s,%s::uuid,%s::uuid,'live')"
        ).format(sql.Identifier(schema)),
        [str(uuid4()), scope.tenant_id, scope.account_id, number, work_id, attempt_id],
    )
    validate_feed_state(connection, schema)


class ResultFeedStore:
    def __init__(self, work: WorkStore) -> None:
        if type(work) is not WorkStore:
            raise WorkError("invalid_input")
        self.work = work
        try:
            with closing(work.settings.connect()) as connection, connection.transaction():
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                validate_work_schema(connection, work.settings)
                if work_schema_version(connection, work.settings.schema) != 4:
                    raise WorkError("schema_mismatch")
                validate_feed_state(connection, work.settings.schema)
                self.source_id = source_id(connection, work.settings.schema)
        except WorkError:
            raise
        except Exception:  # noqa: BLE001 - public storage boundary never reflects SQL/config
            raise WorkError("storage_unavailable") from None

    def read(self, scope: WorkScope, after: ResultFeedCursor | None, limit: int) -> ResultFeedPage:
        schema = self.work.settings.schema
        try:
            with closing(self.work.settings.connect()) as connection, connection.transaction():
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                validate_work_schema(connection, self.work.settings)
                if work_schema_version(connection, schema) != 4:
                    raise WorkError("schema_mismatch")
                if source_id(connection, schema) != self.source_id:
                    raise WorkError("identity_conflict")
                validate_feed_state(connection, schema)
                cursor = after or ResultFeedCursor(self.source_id, scope, 0)
                if cursor.source_id != self.source_id or cursor.scope != scope:
                    raise WorkError("identity_conflict")
                row = connection.execute(
                    sql.SQL(
                        "SELECT last_sequence FROM {}.result_feed_heads WHERE tenant_id=%s AND account_id=%s"
                    ).format(sql.Identifier(schema)),
                    [scope.tenant_id, scope.account_id],
                ).fetchone()
                tail = 0 if row is None else row["last_sequence"]
                if cursor.sequence > tail:
                    raise WorkError("invalid_input")
                rows = connection.execute(
                    sql.SQL("""SELECT e.event_id::text,e.sequence,e.work_id::text,e.attempt_id::text,e.origin,a.command_id,r.sha256,r.recorded_at_ms,r.disposition
                    FROM {}.result_feed_events e JOIN {}.issued_attempts a USING(tenant_id,account_id,work_id,attempt_id)
                    JOIN {}.attempt_results r USING(tenant_id,account_id,work_id,attempt_id)
                    WHERE e.tenant_id=%s AND e.account_id=%s AND e.sequence>%s AND e.sequence<=%s ORDER BY e.sequence LIMIT %s""").format(
                        *([sql.Identifier(schema)] * 3)
                    ),
                    [scope.tenant_id, scope.account_id, cursor.sequence, tail, limit],
                ).fetchall()
                events = tuple(
                    ResultFeedEvent(
                        r["event_id"],
                        self.source_id,
                        WorkScope(scope.tenant_id, scope.account_id),
                        r["sequence"],
                        r["work_id"],
                        r["attempt_id"],
                        r["command_id"],
                        r["sha256"],
                        r["recorded_at_ms"],
                        r["disposition"],
                        r["origin"],
                    )
                    for r in rows
                )
                last = cursor.sequence if not events else events[-1].sequence
                result = ResultFeedPage(
                    self.source_id,
                    scope,
                    cursor,
                    events,
                    ResultFeedCursor(self.source_id, scope, last),
                    ResultFeedCursor(self.source_id, scope, tail),
                    last < tail,
                )
            self.work._emit("result_feed_read", "ok")
            return result
        except WorkError:
            raise
        except Exception:  # noqa: BLE001 - fixed private-safe SQL/cleanup boundary
            raise WorkError("storage_unavailable") from None
