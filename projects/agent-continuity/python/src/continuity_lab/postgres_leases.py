"""Retained PostgreSQL invocation leases under a trusted server clock.

All acquisition/renewal/release and worker guards share the short admission
transaction. External I/O never belongs in this module or its transaction. An
unexpired epoch grants local write authority, not supplier request authority.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg import sql

from .execution_models import ExecutionCapacityExceeded, InvalidStoredState, UnsupportedOperation
from .lease_models import (
    MAX_EPOCH,
    CoordinationPolicy,
    LeaseBusy,
    LeaseGrant,
    LeaseLost,
    LeaseRequired,
    LeaseSnapshot,
    identity,
    owner_identity,
)
from .postgres_store import PostgresExecutionStore
from .postgres_unit_of_work import protected_transaction

Connection = psycopg.Connection[dict[str, Any]]
LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())


def _event(event: str, code: str = "ok") -> None:
    try:
        LOGGER.info(event, extra={"event": event, "code": code})
    except Exception:  # noqa: BLE001 - coordination cannot depend on telemetry availability
        return


def _table(executions: PostgresExecutionStore, name: str) -> sql.Identifier:
    return sql.Identifier(executions.settings.schema, name)


def _version(connection: Connection, executions: PostgresExecutionStore) -> int:
    row = connection.execute(
        sql.SQL("SELECT version FROM {} WHERE singleton").format(
            _table(executions, "schema_metadata")
        )
    ).fetchone()
    if row is None or type(row["version"]) is not int or row["version"] not in {1, 2, 3, 4}:
        raise InvalidStoredState("Coordination schema version is unavailable")
    return row["version"]


def _clock(connection: Connection) -> datetime:
    # Sample after acquiring the admission and row locks. transaction_timestamp
    # could already be stale after waiting and must not authorize a late worker.
    row = connection.execute("SELECT clock_timestamp() AS now").fetchone()
    if row is None or type(row["now"]) is not datetime or row["now"].utcoffset() is None:
        raise InvalidStoredState("Database lease clock is unavailable")
    return row["now"].astimezone(UTC)


def _stamp(value: object) -> str:
    if type(value) is not datetime or value.utcoffset() is None:
        raise ValueError("Lease clock evidence must be a database instant")
    return value.astimezone(UTC).isoformat()


def _snapshot(row: dict[str, Any], scope_id: str, task_id: str) -> LeaseSnapshot:
    try:
        if (row["scope_id"], row["task_id"]) != (scope_id, task_id):
            raise ValueError("Lease row belongs to another execution")
        return LeaseSnapshot(
            scope_id,
            task_id,
            row["owner_id"],
            row["epoch"],
            None if row["expires_at"] is None else _stamp(row["expires_at"]),
            _stamp(row["claimed_at"]),
            _stamp(row["renewed_at"]),
        )
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as error:
        raise InvalidStoredState("Lease contains invalid stored authority") from error


def _row(
    connection: Connection, executions: PostgresExecutionStore, task_id: str
) -> dict[str, Any] | None:
    return connection.execute(
        sql.SQL("SELECT * FROM {} WHERE task_id=%s FOR UPDATE").format(
            _table(executions, "execution_leases")
        ),
        (task_id,),
    ).fetchone()


def require_worker_lease(
    connection: Connection,
    executions: PostgresExecutionStore,
    grant: LeaseGrant | None,
    *,
    scope_id: str,
    task_id: str,
) -> None:
    """Guard one worker write on the caller's existing protected transaction.

    Legacy schemas retain their original single-worker coordination. A v4 grant
    cannot silently downgrade. The admission lock serializes this short guarded
    transaction with takeover; no provider call is permitted while it is held.
    """
    scope_id, task_id = identity(scope_id), identity(task_id)
    # Original scoped lookup precedes lease inspection, including malformed or
    # missing grants, so no cross-scope coordination observation is disclosed.
    executions._get(connection, scope_id, task_id)
    version = _version(connection, executions)
    if version < 4:
        if grant is not None:
            raise UnsupportedOperation("Lease authority requires schema v4")
        return
    if grant is None:
        raise LeaseRequired("A current explicit execution lease is required")
    if type(grant) is not LeaseGrant:
        raise ValueError("A typed execution lease grant is required")
    if (grant.scope_id, grant.task_id) != (scope_id, task_id):
        raise LeaseLost("Execution lease does not own this workflow")
    row = _row(connection, executions, task_id)
    now = _clock(connection)
    if row is None:
        raise LeaseLost("Execution lease is no longer current")
    current = _snapshot(row, scope_id, task_id)
    if (
        current.owner_id != grant.owner_id
        or current.epoch != grant.epoch
        or current.expires_at is None
        or datetime.fromisoformat(current.expires_at) <= now
    ):
        raise LeaseLost("Execution lease is no longer current")


class PostgresLeases:
    """Acquire per-invocation epochs within persisted cluster-wide limits.

    owner_id is a fresh canonical UUID for one invocation, retained only to
    replay a lost acquisition acknowledgement. Renew explicitly. Reacquiring an
    unexpired same-owner grant never extends its original expiry.
    """

    def __init__(
        self,
        executions: PostgresExecutionStore,
        *,
        failpoint: Callable[[str], None] | None = None,
    ) -> None:
        self.executions, self.failpoint = executions, failpoint

    def _hit(self, name: str) -> None:
        if self.failpoint is not None:
            self.failpoint(name)

    def limits_in_transaction(self, connection: Connection) -> CoordinationPolicy:
        if _version(connection, self.executions) != 4:
            raise UnsupportedOperation("Execution leases require schema v4")
        row = connection.execute(
            sql.SQL("SELECT * FROM {} WHERE singleton").format(
                _table(self.executions, "execution_limits")
            )
        ).fetchone()
        try:
            if row is None or row["singleton"] is not True:
                raise ValueError("Persisted coordination policy is absent")
            return CoordinationPolicy(
                maximum_pending=row["maximum_pending"],
                maximum_active=row["maximum_active"],
                maximum_records=row["maximum_records"],
                lease_seconds=row["lease_seconds"],
            )
        except (ValueError, TypeError, KeyError) as error:
            raise InvalidStoredState("Persisted coordination policy is invalid") from error

    def limits(self) -> CoordinationPolicy:
        with protected_transaction(self.executions) as connection:
            return self.limits_in_transaction(connection)

    def get(self, *, scope_id: str, task_id: str) -> LeaseSnapshot | None:
        scope_id, task_id = identity(scope_id), identity(task_id)
        with protected_transaction(self.executions) as connection:
            self.executions._get(connection, scope_id, task_id)
            self.limits_in_transaction(connection)
            row = _row(connection, self.executions, task_id)
            return None if row is None else _snapshot(row, scope_id, task_id)

    def acquire_in_transaction(
        self,
        connection: Connection,
        *,
        scope_id: str,
        task_id: str,
        owner_id: str,
    ) -> LeaseGrant:
        scope_id, task_id, owner_id = (
            identity(scope_id),
            identity(task_id),
            owner_identity(owner_id),
        )
        self.executions._get(connection, scope_id, task_id)
        limits = self.limits_in_transaction(connection)
        row = _row(connection, self.executions, task_id)
        now = _clock(connection)
        current = None if row is None else _snapshot(row, scope_id, task_id)
        if (
            current is not None
            and current.expires_at is not None
            and datetime.fromisoformat(current.expires_at) > now
        ):
            if current.owner_id == owner_id:
                return current.grant()
            raise LeaseBusy("Another invocation owns this execution lease")
        if current is not None and current.epoch >= MAX_EPOCH:
            raise ExecutionCapacityExceeded("Execution lease epoch capacity is exhausted")
        active = connection.execute(
            sql.SQL("SELECT COUNT(*) AS count FROM {} WHERE expires_at>%s").format(
                _table(self.executions, "execution_leases")
            ),
            (now,),
        ).fetchone()
        if (
            active is None
            or type(active["count"]) is not int
            or active["count"] >= limits.maximum_active
        ):
            raise ExecutionCapacityExceeded("Current execution lease capacity is exhausted")
        due = now + timedelta(seconds=limits.lease_seconds)
        if current is None:
            changed = connection.execute(
                sql.SQL(
                    "INSERT INTO {} (task_id,scope_id,owner_id,epoch,expires_at,claimed_at,renewed_at) VALUES (%s,%s,%s,1,%s,%s,%s) RETURNING *"
                ).format(_table(self.executions, "execution_leases")),
                (task_id, scope_id, owner_id, due, now, now),
            ).fetchone()
        else:
            changed = connection.execute(
                sql.SQL(
                    "UPDATE {} SET owner_id=%s,epoch=epoch+1,expires_at=%s,claimed_at=%s,renewed_at=%s WHERE task_id=%s AND scope_id=%s AND epoch=%s AND (expires_at IS NULL OR expires_at<=%s) RETURNING *"
                ).format(_table(self.executions, "execution_leases")),
                (owner_id, due, now, now, task_id, scope_id, current.epoch, now),
            ).fetchone()
        if changed is None:
            raise LeaseLost("Execution lease changed before acquisition")
        grant = _snapshot(changed, scope_id, task_id).grant()
        self._hit("leases.before_acquire_commit")
        return grant

    def acquire(self, *, scope_id: str, task_id: str, owner_id: str) -> LeaseGrant:
        with protected_transaction(self.executions) as connection:
            value = self.acquire_in_transaction(
                connection, scope_id=scope_id, task_id=task_id, owner_id=owner_id
            )
        self._hit("leases.after_acquire_commit")
        _event("execution_lease_acquired")
        return value

    def renew(self, grant: LeaseGrant) -> LeaseGrant:
        if type(grant) is not LeaseGrant:
            raise ValueError("A typed execution lease grant is required")
        with protected_transaction(self.executions) as connection:
            limits = self.limits_in_transaction(connection)
            require_worker_lease(
                connection, self.executions, grant, scope_id=grant.scope_id, task_id=grant.task_id
            )
            now = _clock(connection)
            due = now + timedelta(seconds=limits.lease_seconds)
            changed = connection.execute(
                sql.SQL(
                    "UPDATE {} SET expires_at=%s,renewed_at=%s WHERE task_id=%s AND scope_id=%s AND owner_id=%s AND epoch=%s AND expires_at>%s RETURNING *"
                ).format(_table(self.executions, "execution_leases")),
                (due, now, grant.task_id, grant.scope_id, grant.owner_id, grant.epoch, now),
            ).fetchone()
            if changed is None:
                raise LeaseLost("Execution lease expired before renewal")
            value = _snapshot(changed, grant.scope_id, grant.task_id).grant()
            self._hit("leases.before_renew_commit")
        self._hit("leases.after_renew_commit")
        _event("execution_lease_renewed")
        return value

    def release(self, grant: LeaseGrant) -> None:
        if type(grant) is not LeaseGrant:
            raise ValueError("A typed execution lease grant is required")
        with protected_transaction(self.executions) as connection:
            self.limits_in_transaction(connection)
            require_worker_lease(
                connection, self.executions, grant, scope_id=grant.scope_id, task_id=grant.task_id
            )
            now = _clock(connection)
            changed = connection.execute(
                sql.SQL(
                    "UPDATE {} SET owner_id=NULL,expires_at=NULL WHERE task_id=%s AND scope_id=%s AND owner_id=%s AND epoch=%s AND expires_at>%s"
                ).format(_table(self.executions, "execution_leases")),
                (grant.task_id, grant.scope_id, grant.owner_id, grant.epoch, now),
            )
            if changed.rowcount != 1:
                raise LeaseLost("Execution lease expired before release")
            self._hit("leases.before_release_commit")
        self._hit("leases.after_release_commit")
        _event("execution_lease_released")
