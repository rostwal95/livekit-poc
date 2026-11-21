"""Bounded due selection over the existing PostgreSQL authority, without a queue.

Selection and lease acquisition share the admission transaction. Only explicitly
managed inquiry/wait/intent state or retained completion delivery is runnable.
Wall time qualifies business due dates; lease authority always uses database time.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from psycopg import sql

from .execution_models import ExecutionCapacityExceeded, InvalidStoredState
from .lease_models import (
    CoordinationPolicy,
    LeaseGrant,
    WorkClaim,
    WorkKind,
    identity,
    owner_identity,
)
from .postgres_leases import PostgresLeases
from .postgres_store import PostgresExecutionStore
from .postgres_unit_of_work import protected_transaction


@dataclass(frozen=True, slots=True)
class QueueSnapshot:
    """Scoped durable gauges; capacity maxima are shared across the schema."""

    outstanding: int
    active: int
    maximum_pending: int
    maximum_active: int
    oldest_outstanding_seconds: float
    recovery_lag_seconds: float

    def __post_init__(self) -> None:
        if any(
            type(value) is not int or value < 0
            for value in (self.outstanding, self.active, self.maximum_pending, self.maximum_active)
        ):
            raise ValueError("Durable queue counts must be nonnegative integers")
        if any(
            type(value) not in (int, float) or not math.isfinite(value) or value < 0
            for value in (self.oldest_outstanding_seconds, self.recovery_lag_seconds)
        ):
            raise ValueError("Durable queue ages must be finite nonnegative seconds")


class PostgresWorkQueue:
    """Inspect one eligible workflow then acquire its persisted bounded lease."""

    def __init__(
        self,
        executions: PostgresExecutionStore,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.executions, self.clock = executions, clock
        self.leases = PostgresLeases(executions)

    def policy(self) -> CoordinationPolicy:
        return self.leases.limits()

    def release(self, grant: LeaseGrant) -> None:
        self.leases.release(grant)

    def snapshot(self, *, scope_id: str) -> QueueSnapshot:
        scope_id = identity(scope_id)

        def table(name: str) -> sql.Identifier:
            return sql.Identifier(self.executions.settings.schema, name)

        with protected_transaction(self.executions) as connection:
            limits = self.leases.limits_in_transaction(connection)
            row = connection.execute(
                sql.SQL("""
              WITH outstanding AS (
                SELECT e.created_at::timestamptz AS created
                FROM {executions} e JOIN {tasks} t ON t.task_id=e.task_id
                LEFT JOIN {controls} c ON c.task_id=e.task_id
                LEFT JOIN {outcomes} b ON b.task_id=e.task_id
                WHERE t.scope_id=%s AND b.task_id IS NULL AND
                  (e.status IN ('accepted','running') OR c.state NOT IN ('completed','cancelled','failed','uncertain'))
              )
              SELECT (SELECT COUNT(*) FROM outstanding) AS outstanding,
                COALESCE((SELECT GREATEST(0,EXTRACT(EPOCH FROM clock_timestamp()-MIN(created))) FROM outstanding),0) AS age,
                COUNT(*) FILTER (WHERE l.expires_at>clock_timestamp()) AS active,
                COALESCE(MAX(GREATEST(0,EXTRACT(EPOCH FROM clock_timestamp()-l.expires_at))) FILTER (WHERE l.owner_id IS NOT NULL AND l.expires_at<=clock_timestamp() AND
                  ((b.task_id IS NULL AND (e.status IN ('accepted','running') OR c.state NOT IN ('completed','cancelled','failed','uncertain')))
                   OR d.state IN ('pending','delivering'))),0) AS recovery
              FROM {leases} l JOIN {executions} e ON e.task_id=l.task_id
              LEFT JOIN {controls} c ON c.task_id=l.task_id
              LEFT JOIN {outcomes} b ON b.task_id=l.task_id
              LEFT JOIN {events} v ON v.task_id=l.task_id
              LEFT JOIN {deliveries} d ON d.event_id=v.event_id
              WHERE l.scope_id=%s
            """).format(
                    executions=table("executions"),
                    tasks=table("tasks"),
                    controls=table("execution_controls"),
                    outcomes=table("business_outcomes"),
                    leases=table("execution_leases"),
                    events=table("completion_events"),
                    deliveries=table("completion_deliveries"),
                ),
                (scope_id, scope_id),
            ).fetchone()
            if row is None:
                raise InvalidStoredState("Durable queue counts are unavailable")
            return QueueSnapshot(
                row["outstanding"],
                row["active"],
                limits.maximum_pending,
                limits.maximum_active,
                float(row["age"]),
                float(row["recovery"]),
            )

    def claim_next(self, *, scope_id: str, owner_id: str) -> WorkClaim | None:
        scope_id, owner_id = identity(scope_id), owner_identity(owner_id)
        now = self.clock()
        if type(now) is not datetime or now.utcoffset() is None:
            raise ValueError("Business due clock must return an aware instant")

        def table(name: str) -> sql.Identifier:
            return sql.Identifier(self.executions.settings.schema, name)

        with protected_transaction(self.executions) as connection:
            self.leases.limits_in_transaction(connection)
            row = connection.execute(
                sql.SQL("""
                WITH eligible AS (
                  SELECT e.task_id,c.actor_id,l.renewed_at,e.created_at,
                    CASE
                      WHEN d.state='delivering' OR
                           (d.state='pending' AND d.next_attempt_at::timestamptz<=%(now)s)
                        THEN 'delivery'
                      WHEN x.state='intent_committed' AND a.intent_id IS NOT NULL
                           AND a.payload_json::jsonb->>'schema_version'='2'
                           AND (m.state IS DISTINCT FROM 'pending' OR m.next_attempt_at IS NULL
                             OR m.next_attempt_at<=%(now)s OR c.cancelled)
                        THEN 'mutation'
                      WHEN x.state='waiting' AND EXISTS (
                        SELECT 1 FROM {waits} w WHERE w.task_id=e.task_id AND w.state='pending'
                          AND w.quote_json::jsonb->>'quote_id'=c.current_quote_id
                          AND (w.deadline::timestamptz<=%(now)s OR x.deadline::timestamptz<=%(now)s
                            OR (w.quote_json::jsonb->>'expires_at')::timestamptz<=%(now)s
                            OR (w.quote_json::jsonb->>'schema_version'='2' AND EXISTS(SELECT 1 FROM {signals} s
                               LEFT JOIN {consumptions} z ON z.signal_id=s.signal_id
                               WHERE s.task_id=e.task_id AND s.scope_id=t.scope_id
                                 AND s.actor_id=c.actor_id AND z.signal_id IS NULL
                                 AND s.payload_json::jsonb->'quote'=w.quote_json::jsonb))))
                        THEN 'wait'
                      WHEN (x.state='inquiry_complete' AND x.deadline::timestamptz<=%(now)s)
                        OR x.state IN ('ready','running') OR (x.state='retry_wait' AND
                           (x.next_attempt_at::timestamptz<=%(now)s OR x.deadline::timestamptz<=%(now)s))
                        THEN 'inquiry'
                    END AS kind
                  FROM {executions} e JOIN {tasks} t ON t.task_id=e.task_id
                  LEFT JOIN {controls} x ON x.task_id=e.task_id
                  LEFT JOIN {cases} c ON c.task_id=e.task_id AND c.scope_id=t.scope_id
                  LEFT JOIN {intents} a ON a.task_id=e.task_id
                  LEFT JOIN {effects} m ON m.intent_id=a.intent_id
                  LEFT JOIN {events} v ON v.task_id=e.task_id
                  LEFT JOIN {deliveries} d ON d.event_id=v.event_id
                  LEFT JOIN {leases} l ON l.task_id=e.task_id
                  WHERE t.scope_id=%(scope)s
                    -- Necessary condition of every CASE branch; terminal rows skip it.
                    AND (x.state IN ('intent_committed','waiting','inquiry_complete',
                                     'ready','running','retry_wait')
                         OR d.state IN ('delivering','pending'))
                    AND (l.owner_id IS NULL OR l.expires_at<=clock_timestamp())
                    AND (l.epoch IS NULL OR l.epoch<9223372036854775807)
                )
                SELECT task_id,actor_id,kind FROM eligible WHERE kind IS NOT NULL
                  ORDER BY COALESCE(renewed_at,'-infinity'::timestamptz),created_at,task_id LIMIT 1
                """).format(
                    waits=table("execution_waits"),
                    signals=table("execution_signals"),
                    consumptions=table("execution_signal_consumptions"),
                    executions=table("executions"),
                    tasks=table("tasks"),
                    controls=table("execution_controls"),
                    cases=table("cases"),
                    intents=table("action_intents"),
                    events=table("completion_events"),
                    deliveries=table("completion_deliveries"),
                    leases=table("execution_leases"),
                    effects=table("mutation_effects"),
                ),
                {"scope": scope_id, "now": now.astimezone(UTC)},
            ).fetchone()
            if row is None:
                return None
            try:
                kind = WorkKind(row["kind"])
            except (ValueError, TypeError, KeyError) as error:
                raise InvalidStoredState("Due work has an unsupported kind") from error
            try:
                grant = self.leases.acquire_in_transaction(
                    connection, scope_id=scope_id, task_id=row["task_id"], owner_id=owner_id
                )
            except ExecutionCapacityExceeded:
                # Global active budget is normal backpressure. No task was acked.
                return None
            return WorkClaim(grant, kind, row["actor_id"] if kind == WorkKind.WAIT else None)
