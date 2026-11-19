"""Single-worker PostgreSQL inquiry adapter; schema changes are explicit."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import psycopg
from psycopg import sql

from .execution_codec import decode_attempt, decode_execution
from .execution_models import (
    AttemptRecord,
    AttemptStart,
    ExecutionCapacityExceeded,
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
from .models import BookingChange, IdempotencyConflict, IntakeCapacityExceeded
from .postgres_migrations import validate_schema
from .postgres_settings import PostgresSettings, advisory_keys

LOGGER = logging.getLogger("continuity_lab.postgres_store")
LOGGER.addHandler(logging.NullHandler())


def _now() -> datetime:
    return datetime.now(UTC)


def _identity(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 128:
        raise ValueError("identity must contain 1 to 128 characters without surrounding whitespace")
    return value


def _version(value: int) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("expected version must be a nonnegative integer")
    return value


def _canonical(request: BookingChange) -> str:
    if type(request) is not BookingChange:
        raise ValueError("a validated booking investigation is required")
    return json.dumps(request.payload(), sort_keys=True, separators=(",", ":"))


def _event(event: str, code: str = "ok") -> None:
    try:
        LOGGER.log(
            logging.ERROR if event == "storage_failed" else logging.INFO,
            event,
            extra={"event": event, "code": code},
        )
    except Exception:  # noqa: BLE001 - telemetry cannot alter committed state or failures
        return


class PostgresExecutionStore:
    """Supported inquiry operations with scoped identity and short transactions.

    Admission uses one bounded transaction advisory lock so capacity/replay
    decisions serialize across cooperating callers. The worker's session lock
    is separate and holds no transaction over supplier calls. Neither is the
    lease/epoch protocol of the later multi-worker phase.
    """

    backend = "postgres"

    def __init__(
        self,
        settings: PostgresSettings,
        *,
        clock: Callable[[], datetime] = _now,
        failpoint: Callable[[str], None] | None = None,
        maximum_pending: int = 1000,
        maximum_records: int = 10000,
        maximum_attempts: int = 8,
    ) -> None:
        if type(maximum_pending) is not int or maximum_pending < 1:
            raise ValueError("maximum pending must be a positive integer")
        if type(maximum_records) is not int or maximum_records < maximum_pending:
            raise ValueError("maximum records must be an integer at least maximum pending")
        if type(maximum_attempts) is not int or not 1 <= maximum_attempts <= 100:
            raise ValueError("maximum attempts must be between 1 and 100")
        self.settings, self.clock, self.failpoint = settings, clock, failpoint
        self.maximum_pending, self.maximum_records = maximum_pending, maximum_records
        self.maximum_attempts = maximum_attempts
        self._select = sql.SQL(
            "SELECT e.*,t.scope_id,t.idempotency_key,t.payload FROM {} e JOIN {} t ON t.task_id=e.task_id"
        ).format(self._table("executions"), self._table("tasks"))
        with self._connection():
            pass

    def _table(self, name: str) -> sql.Identifier:
        return sql.Identifier(self.settings.schema, name)

    @contextmanager
    def _connection(self) -> Iterator[psycopg.Connection[dict[str, Any]]]:
        try:
            with closing(self.settings.connect()) as connection:
                self._require_runtime_role(connection)
                validate_schema(connection, self.settings.schema, require_active=True)
                yield connection
        except StorageUnavailable:
            _event("storage_failed", "storage_unavailable")
            raise
        except psycopg.Error as error:
            _event("storage_failed", "storage_unavailable")
            raise StorageUnavailable("Execution storage is unavailable") from error

    def _require_runtime_role(self, connection: psycopg.Connection[dict[str, Any]]) -> None:
        """Reject accidental migration/admin credentials before serving work."""
        role = connection.execute(
            """SELECT current_user AS name,r.rolsuper,r.rolcreatedb,r.rolcreaterole,
                      r.rolreplication,r.rolbypassrls,
                      EXISTS(SELECT 1 FROM pg_auth_members m WHERE m.member=r.oid) AS memberships,
                      has_database_privilege(current_user,current_database(),'CREATE') AS database_create,
                      has_database_privilege(current_user,current_database(),'TEMPORARY') AS database_temp,
                      has_schema_privilege(current_user,%s,'CREATE') AS schema_create,
                      EXISTS(SELECT 1 FROM pg_namespace n WHERE n.nspname=%s AND n.nspowner=r.oid) AS schema_owner
                 FROM pg_roles r WHERE r.rolname=current_user""",
            (self.settings.schema, self.settings.schema),
        ).fetchone()
        forbidden = (
            "rolsuper",
            "rolcreatedb",
            "rolcreaterole",
            "rolreplication",
            "rolbypassrls",
            "memberships",
            "database_create",
            "database_temp",
            "schema_create",
            "schema_owner",
        )
        if role is None or role["name"] != "livekit_lab" or any(role[name] for name in forbidden):
            raise StorageUnavailable("PostgreSQL execution requires the restricted runtime role")
        tables = connection.execute(
            """SELECT c.relname,
                      has_table_privilege(current_user,c.oid,'DELETE') AS deletes,
                      has_table_privilege(current_user,c.oid,'TRUNCATE') AS truncates,
                      has_table_privilege(current_user,c.oid,'TRIGGER') AS triggers,
                      has_table_privilege(current_user,c.oid,'INSERT') AS inserts,
                      has_table_privilege(current_user,c.oid,'UPDATE') AS updates
                 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname=%s AND c.relkind='r'""",
            (self.settings.schema,),
        ).fetchall()
        for table in tables:
            if (
                table["deletes"]
                or table["truncates"]
                or table["triggers"]
                or (
                    table["relname"] == "schema_metadata" and (table["inserts"] or table["updates"])
                )
            ):
                raise StorageUnavailable(
                    "PostgreSQL runtime privileges exceed the supported policy"
                )

    def _write_lock(self, connection: psycopg.Connection[dict[str, Any]]) -> None:
        try:
            connection.execute(
                "SELECT pg_advisory_xact_lock(%s,%s)",
                advisory_keys(self.settings.schema, "admission"),
            )
        except psycopg.errors.LockNotAvailable as error:
            raise ExecutionCapacityExceeded("Execution admission lock is busy") from error
        # A migration may have changed the gate while this transaction waited.
        validate_schema(connection, self.settings.schema, require_active=True)

    def _stamp(self) -> str:
        instant = self.clock()
        if not isinstance(instant, datetime) or instant.utcoffset() is None:
            raise ValueError("clock must return an aware datetime")
        return instant.astimezone(UTC).isoformat()

    def _hit(self, name: str) -> None:
        if self.failpoint is not None:
            self.failpoint(name)

    def _get(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        scope_id: str,
        task_id: str,
    ) -> ExecutionRecord:
        row = connection.execute(
            self._select + sql.SQL(" WHERE t.scope_id=%s AND e.task_id=%s"),
            (scope_id, task_id),
        ).fetchone()
        if row is None:
            raise ExecutionNotFound("Execution is unavailable in this scope")
        return decode_execution(row)

    def submit(
        self,
        *,
        scope_id: str,
        idempotency_key: str,
        request: BookingChange,
        operation: str = Operation.INQUIRE,
    ) -> ExecutionSubmission:
        # Keep legacy validation before connection acquisition.
        scope_id, idempotency_key = _identity(scope_id), _identity(idempotency_key)
        _canonical(request)
        if operation != Operation.INQUIRE:
            raise UnsupportedOperation("Only booking investigation is supported")
        with self._connection() as connection, connection.transaction():
            self._write_lock(connection)
            value = self.submit_in_transaction(
                connection,
                scope_id=scope_id,
                idempotency_key=idempotency_key,
                request=request,
                operation=operation,
            )
        self._hit("execution.after_accept_commit")
        _event("execution_accepted" if value.enrolled else "execution_replayed")
        return value

    def submit_in_transaction(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        scope_id: str,
        idempotency_key: str,
        request: BookingChange,
        operation: str = Operation.INQUIRE,
    ) -> ExecutionSubmission:
        """Use the caller's protected admission transaction; never perform I/O."""
        scope_id, idempotency_key = _identity(scope_id), _identity(idempotency_key)
        payload = _canonical(request)
        if operation != Operation.INQUIRE:
            raise UnsupportedOperation("Only booking investigation is supported")
        stamp, created, enrolled = self._stamp(), False, False
        prior = connection.execute(
            sql.SQL("SELECT * FROM {} WHERE scope_id=%s AND idempotency_key=%s").format(
                self._table("tasks")
            ),
            (scope_id, idempotency_key),
        ).fetchone()
        if prior is not None and prior["payload"] != payload:
            raise IdempotencyConflict("key already used for a different request")
        task_id = prior["task_id"] if prior is not None else str(uuid4())
        existing = connection.execute(
            sql.SQL("SELECT task_id FROM {} WHERE task_id=%s").format(self._table("executions")),
            (task_id,),
        ).fetchone()
        if existing is None:
            metadata = connection.execute(
                sql.SQL("SELECT version FROM {} WHERE singleton").format(
                    self._table("schema_metadata")
                )
            ).fetchone()
            if metadata is not None and metadata["version"] in (4, 5):
                from .postgres_leases import PostgresLeases

                limits = PostgresLeases(self).limits_in_transaction(connection)
                count = connection.execute(
                    sql.SQL("""
                    SELECT (SELECT COUNT(*) FROM {}) AS records, COUNT(*) FILTER (WHERE b.task_id IS NULL
                      AND (e.status IN ('accepted','running') OR
                           c.state NOT IN ('completed','cancelled','failed','uncertain'))) AS pending
                    FROM {} e LEFT JOIN {} c ON c.task_id=e.task_id
                    LEFT JOIN {} b ON b.task_id=e.task_id
                """).format(
                        self._table("tasks"),
                        self._table("executions"),
                        self._table("execution_controls"),
                        self._table("business_outcomes"),
                    )
                ).fetchone()
                pending_limit, record_limit = limits.maximum_pending, limits.maximum_records
            else:
                pending_limit, record_limit = self.maximum_pending, self.maximum_records
                count = connection.execute(
                    sql.SQL(
                        "SELECT COUNT(*) AS records,COUNT(*) FILTER (WHERE status IN ('accepted','running')) AS pending FROM {}"
                    ).format(self._table("executions"))
                ).fetchone()
            if count is None:
                raise InvalidStoredState("Execution count is unavailable")
            if count["pending"] >= pending_limit or (
                count["records"] >= record_limit
                and (metadata is None or metadata["version"] not in (4, 5) or prior is None)
            ):
                raise IntakeCapacityExceeded("Execution admission capacity exhausted")
            if prior is None:
                connection.execute(
                    sql.SQL(
                        "INSERT INTO {} (task_id,scope_id,idempotency_key,payload,status,created_at) VALUES (%s,%s,%s,%s,'queued',%s)"
                    ).format(self._table("tasks")),
                    (task_id, scope_id, idempotency_key, payload, stamp),
                )
                created = True
            original_stamp = prior["created_at"] if prior is not None else stamp
            connection.execute(
                sql.SQL(
                    "INSERT INTO {} (task_id,operation,status,effect_id,version,created_at,updated_at,result_json,error_code) VALUES (%s,%s,'accepted',%s,0,%s,%s,NULL,NULL)"
                ).format(self._table("executions")),
                (
                    task_id,
                    Operation.INQUIRE.value,
                    str(uuid4()),
                    original_stamp,
                    original_stamp,
                ),
            )
            enrolled = True
        execution = self._get(connection, scope_id, task_id)
        self._hit("execution.before_accept_commit")
        return ExecutionSubmission(execution, created, enrolled)

    def _check_pending_capacity(self, connection: psycopg.Connection[dict[str, Any]]) -> None:
        """Charge newly managed completed inquiry work without duplicating its ID."""
        metadata = connection.execute(
            sql.SQL("SELECT version FROM {} WHERE singleton").format(self._table("schema_metadata"))
        ).fetchone()
        if metadata is None or metadata["version"] not in (4, 5):
            return
        from .postgres_leases import PostgresLeases

        limits = PostgresLeases(self).limits_in_transaction(connection)
        row = connection.execute(
            sql.SQL("""
            SELECT COUNT(*) AS pending FROM {} e
            LEFT JOIN {} c ON c.task_id=e.task_id
            LEFT JOIN {} b ON b.task_id=e.task_id
            WHERE b.task_id IS NULL AND (e.status IN ('accepted','running') OR
              c.state NOT IN ('completed','cancelled','failed','uncertain'))
        """).format(
                self._table("executions"),
                self._table("execution_controls"),
                self._table("business_outcomes"),
            )
        ).fetchone()
        if row is None:
            raise InvalidStoredState("Outstanding work count is unavailable")
        if row["pending"] >= limits.maximum_pending:
            raise ExecutionCapacityExceeded("Outstanding execution capacity is exhausted")

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
                self._select
                + sql.SQL(
                    ' WHERE t.scope_id=%s ORDER BY e.created_at COLLATE "C",e.task_id COLLATE "C" LIMIT %s'
                ),
                (scope_id, limit),
            ).fetchall()
            return tuple(decode_execution(row) for row in rows)

    def attempts(self, *, scope_id: str, task_id: str) -> tuple[AttemptRecord, ...]:
        scope_id, task_id = _identity(scope_id), _identity(task_id)
        with self._connection() as connection:
            self._get(connection, scope_id, task_id)
            rows = connection.execute(
                sql.SQL("SELECT * FROM {} WHERE task_id=%s ORDER BY attempt_no").format(
                    self._table("execution_attempts")
                ),
                (task_id,),
            ).fetchall()
            return tuple(decode_attempt(row) for row in rows)

    def _require_unmanaged(
        self, connection: psycopg.Connection[dict[str, Any]], task_id: str
    ) -> None:
        """Advanced continuation owns its attempts; the legacy worker must stop."""
        metadata = connection.execute(
            sql.SQL("SELECT version FROM {} WHERE singleton").format(self._table("schema_metadata"))
        ).fetchone()
        if metadata is not None and metadata["version"] in (4, 5):
            raise UnsupportedOperation(
                "Schema v4 inquiry writes require an explicit execution lease"
            )
        if metadata is not None and metadata["version"] in {2, 3}:
            managed = connection.execute(
                sql.SQL("SELECT 1 FROM {} WHERE task_id=%s").format(
                    self._table("execution_controls")
                ),
                (task_id,),
            ).fetchone()
            if managed is not None:
                raise UnsupportedOperation("Managed inquiries require the lifecycle worker")

    def start_attempt(self, *, scope_id: str, task_id: str, expected_version: int) -> AttemptStart:
        scope_id, task_id, expected_version = (
            _identity(scope_id),
            _identity(task_id),
            _version(expected_version),
        )
        stamp = self._stamp()
        with self._connection() as connection, connection.transaction():
            self._write_lock(connection)
            execution = self._get(connection, scope_id, task_id)
            self._require_unmanaged(connection, task_id)
            if (
                execution.version != expected_version
                or execution.status != ExecutionStatus.ACCEPTED
            ):
                raise TransitionConflict("Execution cannot start this attempt")
            attempt_id = str(uuid4())
            row = connection.execute(
                sql.SQL(
                    "INSERT INTO {} (attempt_id,task_id,attempt_no,status,started_at,finished_at,error_code) VALUES (%s,%s,1,'started',%s,NULL,NULL) RETURNING *"
                ).format(self._table("execution_attempts")),
                (attempt_id, task_id, stamp),
            ).fetchone()
            changed = connection.execute(
                sql.SQL(
                    "UPDATE {} SET status='running',version=version+1,updated_at=%s WHERE task_id=%s AND version=%s AND status='accepted'"
                ).format(self._table("executions")),
                (stamp, task_id, expected_version),
            )
            if changed.rowcount != 1 or row is None:
                raise TransitionConflict("Execution transition lost its expected version")
            result = AttemptStart(self._get(connection, scope_id, task_id), decode_attempt(row))
        _event("attempt_started")
        return result

    def recover_attempt(
        self, *, scope_id: str, task_id: str, expected_version: int
    ) -> AttemptStart:
        scope_id, task_id, expected_version = (
            _identity(scope_id),
            _identity(task_id),
            _version(expected_version),
        )
        stamp = self._stamp()
        with self._connection() as connection, connection.transaction():
            self._write_lock(connection)
            execution = self._get(connection, scope_id, task_id)
            self._require_unmanaged(connection, task_id)
            if execution.version != expected_version or execution.status != ExecutionStatus.RUNNING:
                raise TransitionConflict("Execution cannot recover this attempt")
            active = connection.execute(
                sql.SQL("SELECT * FROM {} WHERE task_id=%s AND status='started' LIMIT 2").format(
                    self._table("execution_attempts")
                ),
                (task_id,),
            ).fetchall()
            maximum = connection.execute(
                sql.SQL("SELECT MAX(attempt_no) AS maximum FROM {} WHERE task_id=%s").format(
                    self._table("execution_attempts")
                ),
                (task_id,),
            ).fetchone()
            if len(active) != 1 or maximum is None or active[0]["attempt_no"] != maximum["maximum"]:
                raise InvalidStoredState("Execution has inconsistent current attempt state")
            if maximum["maximum"] >= self.maximum_attempts:
                raise TransitionConflict("Manual inquiry recovery attempt limit reached")
            changed = connection.execute(
                sql.SQL(
                    "UPDATE {} SET status='interrupted',finished_at=%s WHERE attempt_id=%s AND status='started'"
                ).format(self._table("execution_attempts")),
                (stamp, active[0]["attempt_id"]),
            )
            if changed.rowcount != 1:
                raise TransitionConflict("Prior attempt no longer owns unfinished state")
            row = connection.execute(
                sql.SQL(
                    "INSERT INTO {} (attempt_id,task_id,attempt_no,status,started_at,finished_at,error_code) VALUES (%s,%s,%s,'started',%s,NULL,NULL) RETURNING *"
                ).format(self._table("execution_attempts")),
                (str(uuid4()), task_id, maximum["maximum"] + 1, stamp),
            ).fetchone()
            changed = connection.execute(
                sql.SQL(
                    "UPDATE {} SET version=version+1,updated_at=%s WHERE task_id=%s AND version=%s AND status='running'"
                ).format(self._table("executions")),
                (stamp, task_id, expected_version),
            )
            if changed.rowcount != 1 or row is None:
                raise TransitionConflict("Recovery lost its expected version")
            result = AttemptStart(self._get(connection, scope_id, task_id), decode_attempt(row))
        _event("attempt_recovered")
        return result

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
        stamp = self._stamp()
        with self._connection() as connection, connection.transaction():
            self._write_lock(connection)
            execution = self._get(connection, scope_id, task_id)
            self._require_unmanaged(connection, task_id)
            if execution.version != expected_version or execution.status != ExecutionStatus.RUNNING:
                raise TransitionConflict("Execution cannot accept this attempt outcome")
            if result is not None and (result.booking_reference, result.new_check_in) != (
                execution.request.booking_reference,
                execution.request.new_check_in,
            ):
                raise ValueError("inquiry result must match the accepted request")
            state = ExecutionStatus.SUCCEEDED if result is not None else ExecutionStatus.FAILED
            code = error_code.value if error_code else None
            changed = connection.execute(
                sql.SQL(
                    "UPDATE {} SET status=%s,finished_at=%s,error_code=%s WHERE attempt_id=%s AND task_id=%s AND status='started'"
                ).format(self._table("execution_attempts")),
                (state.value, stamp, code, attempt_id, task_id),
            )
            if changed.rowcount != 1:
                raise TransitionConflict("Attempt is not the current unfinished attempt")
            changed = connection.execute(
                sql.SQL(
                    "UPDATE {} SET status=%s,version=version+1,updated_at=%s,result_json=%s,error_code=%s WHERE task_id=%s AND version=%s AND status='running'"
                ).format(self._table("executions")),
                (
                    state.value,
                    stamp,
                    json.dumps(result.payload(), sort_keys=True, separators=(",", ":"))
                    if result
                    else None,
                    code,
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
        raise UnsupportedOperation("Inquiry cancellation is not implemented")

    @contextmanager
    def worker_slot(self) -> Iterator[None]:
        """Hold one cooperating session slot, without an open transaction."""
        keys = advisory_keys(self.settings.schema, "worker")
        with self._connection() as connection:
            acquired = connection.execute(
                "SELECT pg_try_advisory_lock(%s,%s) AS acquired", keys
            ).fetchone()
            if acquired is None or not acquired["acquired"]:
                raise ExecutionCapacityExceeded("A cooperating inquiry worker is already active")
            # This connection is dedicated, never pooled. Closing its session
            # releases the lock without a second SQL operation that could mask
            # an already-active supplier or cancellation exception.
            yield
