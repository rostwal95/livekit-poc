"""SQLite is authoritative for accepted requests; no background work runs here."""

import json
import sqlite3
from contextlib import closing
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

from .models import (
    BookingChange,
    IdempotencyConflict,
    IntakeCapacityExceeded,
    Submission,
    Task,
)
from .sqlite_admission import ensure_write_open


class TaskStore:
    """File-backed, local task intake with scope-qualified idempotency keys.

    Each operation opens its own connection. SQLite serializes writers; the
    uniqueness constraint is the final guard against concurrent duplicate intake.
    A scope is supplied by the caller in this lab, not authenticated by this store.
    """

    def __init__(self, database: str | Path) -> None:
        self.database = str(database)
        if self.database == ":memory:":
            raise ValueError("use a file-backed database so requests survive a restart")
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    scope_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status = 'queued'),
                    created_at TEXT NOT NULL,
                    UNIQUE (scope_id, idempotency_key)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=5.0)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _identity(value: str, field: str) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > 128:
            raise ValueError(f"{field} must contain 1 to 128 characters")
        if value != value.strip():
            raise ValueError(f"{field} must not have leading or trailing whitespace")
        return value

    def submit(
        self,
        *,
        scope_id: str,
        idempotency_key: str,
        request: BookingChange,
        max_database_bytes: int | None = None,
    ) -> Submission:
        """Accept once per scope/key, returning the original task on a replay.

        Equal keys with different payloads are an error, including when the first
        caller never received the response. The entire check/insert is serialized
        in one write transaction; no network or model call happens inside it.
        """
        scope_id = self._identity(scope_id, "scope_id")
        idempotency_key = self._identity(idempotency_key, "idempotency_key")
        if max_database_bytes is not None and (
            type(max_database_bytes) is not int or max_database_bytes < 1
        ):
            raise ValueError("max_database_bytes must be a positive integer")
        payload = json.dumps(request.payload(), sort_keys=True, separators=(",", ":"))

        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM tasks WHERE scope_id = ? AND idempotency_key = ?",
                (scope_id, idempotency_key),
            ).fetchone()
            if existing is not None:
                if existing["payload"] != payload:
                    raise IdempotencyConflict("key already used for a different request")
                return Submission(task=self._task(existing), created=False)

            ensure_write_open(connection)
            if max_database_bytes is not None:
                self._check_capacity(connection, max_database_bytes, before_insert=True)

            task_id = str(uuid4())
            created_at = datetime.now(UTC).isoformat()
            connection.execute(
                "INSERT INTO tasks VALUES (?, ?, ?, ?, 'queued', ?)",
                (task_id, scope_id, idempotency_key, payload, created_at),
            )
            if max_database_bytes is not None:
                # Reject and roll back growth across the budget within this same
                # writer transaction; accepted replay/conflict decisions above
                # remain independent of the new-work admission threshold.
                self._check_capacity(connection, max_database_bytes, before_insert=False)
            task = Task(task_id, scope_id, idempotency_key, request, "queued", created_at)
            return Submission(task=task, created=True)

    @staticmethod
    def _check_capacity(
        connection: sqlite3.Connection, maximum: int, *, before_insert: bool
    ) -> None:
        page_count = connection.execute("PRAGMA page_count").fetchone()[0]
        page_size = connection.execute("PRAGMA page_size").fetchone()[0]
        allocated = page_count * page_size
        if allocated > maximum or (before_insert and allocated == maximum):
            raise IntakeCapacityExceeded("local intake allocation limit reached")

    def list_tasks(self, *, scope_id: str, limit: int | None = None) -> list[Task]:
        scope_id = self._identity(scope_id, "scope_id")
        if limit is not None and (type(limit) is not int or limit < 1):
            raise ValueError("limit must be a positive integer")
        query = "SELECT * FROM tasks WHERE scope_id = ? ORDER BY created_at, task_id"
        parameters: list[str | int] = [scope_id]
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)
        with closing(self._connect()) as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._task(row) for row in rows]

    @staticmethod
    def _task(row: sqlite3.Row) -> Task:
        payload = json.loads(row["payload"])
        request = BookingChange(
            booking_reference=payload["booking_reference"],
            new_check_in=date.fromisoformat(payload["new_check_in"]),
            confirmed=payload["confirmed"],
        )
        return Task(
            task_id=row["task_id"],
            scope_id=row["scope_id"],
            idempotency_key=row["idempotency_key"],
            request=request,
            status=row["status"],
            created_at=row["created_at"],
        )
