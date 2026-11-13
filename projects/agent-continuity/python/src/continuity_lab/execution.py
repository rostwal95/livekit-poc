"""Explicitly migrated SQLite inquiry state; no supplier or scheduler runs here."""

import json
import logging
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .execution_codec import decode_attempt, decode_execution
from .execution_models import (
    AttemptRecord,
    AttemptStart,
    ExecutionNotFound,
    ExecutionRecord,
    ExecutionStatus,
    ExecutionSubmission,
    FailureCode,
    InquiryResult,
    InvalidStoredState,
    Operation,
    StorageUnavailable,
    TransitionConflict,
    UnsupportedOperation,
)
from .migrations import require_schema
from .models import BookingChange, IdempotencyConflict, IntakeCapacityExceeded
from .sqlite_admission import ensure_write_open
from .worker_lock import WORKER_LOCK_SUFFIX, WorkerLockUnavailable, sqlite_worker_lock

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
_SELECT = """SELECT e.*, t.scope_id, t.idempotency_key, t.payload
             FROM executions e JOIN tasks t ON t.task_id = e.task_id"""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _identity(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 128:
        raise ValueError("identity must contain 1 to 128 characters without surrounding whitespace")
    return value


def _canonical(request: BookingChange) -> str:
    if type(request) is not BookingChange:
        raise ValueError("a validated booking investigation is required")
    return json.dumps(request.payload(), sort_keys=True, separators=(",", ":"))


def _version(value: int) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("expected version must be a nonnegative integer")
    return value


def _event(event: str, code: str = "ok") -> None:
    # Fields are fixed producer literals, never exception/request values.
    level = logging.ERROR if event == "storage_failed" else logging.INFO
    LOGGER.log(level, event, extra={"event": event, "code": code})


class ExecutionStore:
    """Synchronous store for one inquiry lifecycle and its optimistic transitions.

    Scope is supplied by a trusted local caller, not authenticated by SQLite.
    `created` describes the logical M1 task; `enrolled` describes a newly added
    execution row. Legacy intake written after migration is enrolled only through
    explicit submit. Reads never repair state. No schema DDL occurs at runtime.
    """

    backend = "sqlite"

    def __init__(
        self,
        database: str | Path,
        *,
        clock: Callable[[], datetime] = _utc_now,
        failpoint: Callable[[str], None] | None = None,
        maximum_pending: int = 1000,
        maximum_records: int = 10000,
        maximum_attempts: int = 8,
    ) -> None:
        if str(database) == ":memory:":
            raise ValueError("a migrated file-backed database is required")
        if type(maximum_pending) is not int or maximum_pending < 1:
            raise ValueError("maximum pending must be a positive integer")
        if type(maximum_records) is not int or maximum_records < maximum_pending:
            raise ValueError("maximum records must be an integer at least maximum pending")
        if type(maximum_attempts) is not int or not 1 <= maximum_attempts <= 100:
            raise ValueError("maximum attempts must be between 1 and 100")
        self.maximum_attempts = maximum_attempts
        self.database = Path(database).resolve()
        self.clock, self.failpoint, self.maximum_pending = clock, failpoint, maximum_pending
        self.maximum_records = maximum_records
        with self._connection():
            pass

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        try:
            with closing(
                sqlite3.connect(
                    self.database.as_uri() + "?mode=rw",
                    uri=True,
                    timeout=5,
                )
            ) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA foreign_keys = ON")
                require_schema(connection)
                yield connection
        except sqlite3.Error as error:
            _event("storage_failed", "storage_unavailable")
            raise StorageUnavailable("Execution storage is unavailable") from error

    def _now(self) -> str:
        instant = self.clock()
        if not isinstance(instant, datetime) or instant.utcoffset() is None:
            raise ValueError("clock must return an aware datetime")
        return instant.astimezone(UTC).isoformat()

    def _hit(self, name: str) -> None:
        if self.failpoint is not None:
            self.failpoint(name)

    @staticmethod
    def _record(row: sqlite3.Row) -> ExecutionRecord:
        return decode_execution(dict(row))

    @staticmethod
    def _attempt(row: sqlite3.Row) -> AttemptRecord:
        return decode_attempt(dict(row))

    def worker_slot(self) -> AbstractContextManager[None]:
        if self.database.stat().st_nlink != 1:
            raise WorkerLockUnavailable("Execution database aliases are unsupported")
        return sqlite_worker_lock(self.database.with_name(self.database.name + WORKER_LOCK_SUFFIX))

    def _get(self, connection: sqlite3.Connection, scope_id: str, task_id: str) -> ExecutionRecord:
        row = connection.execute(
            _SELECT + " WHERE t.scope_id=? AND e.task_id=?", (scope_id, task_id)
        ).fetchone()
        if row is None:
            raise ExecutionNotFound("Execution is unavailable in this scope")
        return self._record(row)

    def submit(
        self,
        *,
        scope_id: str,
        idempotency_key: str,
        request: BookingChange,
        operation: str = Operation.INQUIRE,
    ) -> ExecutionSubmission:
        scope_id, idempotency_key = _identity(scope_id), _identity(idempotency_key)
        payload = _canonical(request)
        if operation != Operation.INQUIRE:
            raise UnsupportedOperation("Only booking investigation is supported")
        now, created, enrolled = self._now(), False, False
        with self._connection() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = connection.execute(
                "SELECT * FROM tasks WHERE scope_id=? AND idempotency_key=?",
                (scope_id, idempotency_key),
            ).fetchone()
            if prior is not None and prior["payload"] != payload:
                raise IdempotencyConflict("key already used for a different request")
            task_id = prior["task_id"] if prior is not None else str(uuid4())
            existing = connection.execute(
                "SELECT task_id FROM executions WHERE task_id=?", (task_id,)
            ).fetchone()
            if existing is None:
                ensure_write_open(connection)
                count, pending = connection.execute(
                    "SELECT COUNT(*),COALESCE(SUM(status IN ('accepted','running')),0) FROM executions"
                ).fetchone()
                if pending >= self.maximum_pending or count >= self.maximum_records:
                    raise IntakeCapacityExceeded("Execution admission capacity exhausted")
                if prior is None:
                    connection.execute(
                        "INSERT INTO tasks VALUES (?,?,?,?, 'queued',?)",
                        (task_id, scope_id, idempotency_key, payload, now),
                    )
                    created = True
                stamp = prior["created_at"] if prior is not None else now
                connection.execute(
                    """INSERT INTO executions
                       (task_id,operation,status,effect_id,version,created_at,updated_at,result_json,error_code)
                       VALUES (?,?,'accepted',?,0,?,?,NULL,NULL)""",
                    (task_id, Operation.INQUIRE, str(uuid4()), stamp, stamp),
                )
                enrolled = True
            execution = self._get(connection, scope_id, task_id)
            self._hit("execution.before_accept_commit")
        self._hit("execution.after_accept_commit")
        _event("execution_accepted" if enrolled else "execution_replayed")
        return ExecutionSubmission(execution, created, enrolled)

    def get(self, *, scope_id: str, task_id: str) -> ExecutionRecord:
        scope_id, task_id = _identity(scope_id), _identity(task_id)
        with self._connection() as connection:
            return self._get(connection, scope_id, task_id)

    def list(self, *, scope_id: str, limit: int = 100) -> tuple[ExecutionRecord, ...]:
        scope_id = _identity(scope_id)
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("list limit must be between 1 and 1000")
        with self._connection() as connection:
            rows = connection.execute(
                _SELECT + " WHERE t.scope_id=? ORDER BY e.created_at,e.task_id LIMIT ?",
                (scope_id, limit),
            ).fetchall()
            return tuple(self._record(row) for row in rows)

    def attempts(self, *, scope_id: str, task_id: str) -> tuple[AttemptRecord, ...]:
        scope_id, task_id = _identity(scope_id), _identity(task_id)
        with self._connection() as connection:
            self._get(connection, scope_id, task_id)
            rows = connection.execute(
                "SELECT * FROM execution_attempts WHERE task_id=? ORDER BY attempt_no", (task_id,)
            ).fetchall()
            return tuple(self._attempt(row) for row in rows)

    def start_attempt(self, *, scope_id: str, task_id: str, expected_version: int) -> AttemptStart:
        scope_id, task_id, expected_version = (
            _identity(scope_id),
            _identity(task_id),
            _version(expected_version),
        )
        now = self._now()
        with self._connection() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            execution = self._get(connection, scope_id, task_id)
            ensure_write_open(connection)
            if (
                execution.version != expected_version
                or execution.status != ExecutionStatus.ACCEPTED
            ):
                raise TransitionConflict("Execution cannot start this attempt")
            attempt_id = str(uuid4())
            connection.execute(
                "INSERT INTO execution_attempts VALUES (?,?,1,'started',?,NULL,NULL)",
                (attempt_id, task_id, now),
            )
            changed = connection.execute(
                "UPDATE executions SET status='running',version=version+1,updated_at=? WHERE task_id=? AND version=? AND status='accepted'",
                (now, task_id, expected_version),
            )
            if changed.rowcount != 1:
                raise TransitionConflict("Execution transition lost its expected version")
            attempt = connection.execute(
                "SELECT * FROM execution_attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            result = AttemptStart(self._get(connection, scope_id, task_id), self._attempt(attempt))
        _event("attempt_started")
        return result

    def recover_attempt(
        self,
        *,
        scope_id: str,
        task_id: str,
        expected_version: int,
    ) -> AttemptStart:
        """Replace a stopped inquiry attempt under the cooperative worker lock.

        The caller must own the single-worker application lock and establish that
        the earlier cooperating worker is stopped. This is state fencing, not a
        distributed lease or a guarantee that an external operation stopped.
        The inquiry's persisted effect identity is preserved for reconciliation.
        """
        scope_id, task_id = _identity(scope_id), _identity(task_id)
        expected_version = _version(expected_version)
        now = self._now()
        with self._connection() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            execution = self._get(connection, scope_id, task_id)
            ensure_write_open(connection)
            if execution.version != expected_version or execution.status != ExecutionStatus.RUNNING:
                raise TransitionConflict("Execution cannot recover this attempt")
            active = connection.execute(
                "SELECT * FROM execution_attempts WHERE task_id=? AND status='started' LIMIT 2",
                (task_id,),
            ).fetchall()
            maximum = connection.execute(
                "SELECT MAX(attempt_no) FROM execution_attempts WHERE task_id=?",
                (task_id,),
            ).fetchone()[0]
            if len(active) != 1 or active[0]["attempt_no"] != maximum:
                raise InvalidStoredState("Execution has inconsistent current attempt state")
            if maximum >= self.maximum_attempts:
                raise TransitionConflict("Manual inquiry recovery attempt limit reached")
            changed = connection.execute(
                "UPDATE execution_attempts SET status='interrupted',finished_at=? WHERE attempt_id=? AND status='started'",
                (now, active[0]["attempt_id"]),
            )
            if changed.rowcount != 1:
                raise TransitionConflict("Prior attempt no longer owns unfinished state")
            attempt_id = str(uuid4())
            connection.execute(
                "INSERT INTO execution_attempts VALUES (?,?,?,'started',?,NULL,NULL)",
                (attempt_id, task_id, maximum + 1, now),
            )
            changed = connection.execute(
                "UPDATE executions SET version=version+1,updated_at=? WHERE task_id=? AND version=? AND status='running'",
                (now, task_id, expected_version),
            )
            if changed.rowcount != 1:
                raise TransitionConflict("Recovery lost its expected version")
            attempt = connection.execute(
                "SELECT * FROM execution_attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            started = AttemptStart(self._get(connection, scope_id, task_id), self._attempt(attempt))
        _event("attempt_recovered")
        return started

    def finish_attempt(
        self,
        *,
        scope_id: str,
        task_id: str,
        attempt_id: str,
        expected_version: int,
        result: InquiryResult | None = None,
        error_code: FailureCode | None = None,
    ) -> ExecutionRecord:
        scope_id, task_id, attempt_id = (
            _identity(scope_id),
            _identity(task_id),
            _identity(attempt_id),
        )
        expected_version = _version(expected_version)
        if (result is None) == (error_code is None):
            raise ValueError("exactly one result or safe failure code is required")
        if result is not None and type(result) is not InquiryResult:
            raise ValueError("a validated inquiry result is required")
        if error_code is not None and type(error_code) is not FailureCode:
            raise ValueError("an allowlisted failure code is required")
        now = self._now()
        with self._connection() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            execution = self._get(connection, scope_id, task_id)
            ensure_write_open(connection)
            if execution.version != expected_version or execution.status != ExecutionStatus.RUNNING:
                raise TransitionConflict("Execution cannot accept this attempt outcome")
            if result is not None and (result.booking_reference, result.new_check_in) != (
                execution.request.booking_reference,
                execution.request.new_check_in,
            ):
                raise ValueError("inquiry result must match the accepted request")
            state = ExecutionStatus.SUCCEEDED if result is not None else ExecutionStatus.FAILED
            changed = connection.execute(
                "UPDATE execution_attempts SET status=?,finished_at=?,error_code=? WHERE attempt_id=? AND task_id=? AND status='started'",
                (state.value, now, error_code, attempt_id, task_id),
            )
            if changed.rowcount != 1:
                raise TransitionConflict("Attempt is not the current unfinished attempt")
            changed = connection.execute(
                "UPDATE executions SET status=?,version=version+1,updated_at=?,result_json=?,error_code=? WHERE task_id=? AND version=? AND status='running'",
                (
                    state.value,
                    now,
                    json.dumps(result.payload(), sort_keys=True, separators=(",", ":"))
                    if result
                    else None,
                    error_code,
                    task_id,
                    expected_version,
                ),
            )
            if changed.rowcount != 1:
                raise TransitionConflict("Execution transition lost its expected version")
            completed = self._get(connection, scope_id, task_id)
        _event("attempt_finished", state.value)
        return completed

    def cancel(self, *, scope_id: str, task_id: str) -> None:
        self.get(scope_id=scope_id, task_id=task_id)
        raise UnsupportedOperation("SQLite inquiry cancellation is not implemented")
