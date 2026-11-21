"""P1-owned issued attempts/results using the accepted-work transaction boundary."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import closing
from dataclasses import replace
from typing import Any, TypeVar
from uuid import uuid4

from psycopg import sql

from .issued_models import (
    AttemptResult,
    ExecutionObservation,
    ExecutionStatus,
    Issuance,
    IssuedAttempt,
    ResultDisposition,
)
from .result_feed_store import append_result_event
from .work_models import WorkError, WorkLimits, WorkScope, work_identifier, work_uuid
from .work_schema import Connection, execution_limits, validate_work_schema
from .work_store import WorkStore

T = TypeVar("T")


class ExecutionStore:
    """No network calls, scheduling or remote stop claims occur inside these transactions."""

    def __init__(self, work: WorkStore) -> None:
        self.work = work
        try:
            with closing(work.settings.connect()) as connection:
                self._validate(connection)
        except WorkError:
            raise
        except Exception:  # noqa: BLE001 - One fixed public storage error boundary.
            raise WorkError("storage_unavailable") from None

    def _validate(self, connection: Connection) -> None:
        validate_work_schema(connection, self.work.settings)

    def _table(self, name: str) -> sql.Identifier:
        return self.work._table(name)

    def _attempt(
        self, connection: Connection, scope: WorkScope, row: dict[str, Any]
    ) -> IssuedAttempt:
        try:
            record = replace(
                self.work._get(connection, scope, row["work_id"]), cancel_requested=False
            )
            return IssuedAttempt(
                record,
                row["attempt_id"],
                row["command_id"],
                row["number"],
                row["owner_id"],
                row["epoch"],
                row["issued_at_ms"],
                row["lease_until_ms"],
            )
        except (WorkError, KeyError, ValueError, TypeError):
            raise WorkError("schema_mismatch") from None

    def _selection(self) -> sql.Composed:
        return sql.SQL(
            "SELECT attempt_id::text,work_id::text,command_id,number,owner_id::text,epoch,issued_at_ms,lease_until_ms FROM {} WHERE tenant_id=%s AND account_id=%s"
        ).format(self._table("issued_attempts"))

    def _find_issue(
        self, connection: Connection, scope: WorkScope, command_id: str
    ) -> IssuedAttempt | None:
        row = connection.execute(
            self._selection() + sql.SQL(" AND command_id=%s"),
            [scope.tenant_id, scope.account_id, command_id],
        ).fetchone()
        return None if row is None else self._attempt(connection, scope, row)

    def _latest(
        self, connection: Connection, scope: WorkScope, work_id: str
    ) -> IssuedAttempt | None:
        row = connection.execute(
            self._selection() + sql.SQL(" AND work_id=%s::uuid ORDER BY number DESC LIMIT 1"),
            [scope.tenant_id, scope.account_id, work_id],
        ).fetchone()
        return None if row is None else self._attempt(connection, scope, row)

    def _result(
        self, connection: Connection, scope: WorkScope, work_id: str, attempt_id: str
    ) -> AttemptResult | None:
        row = connection.execute(
            sql.SQL(
                "SELECT attempt_id::text,work_id::text,body,sha256,recorded_at_ms,disposition FROM {} WHERE tenant_id=%s AND account_id=%s AND work_id=%s::uuid AND attempt_id=%s::uuid"
            ).format(self._table("attempt_results")),
            [scope.tenant_id, scope.account_id, work_id, attempt_id],
        ).fetchone()
        if row is None:
            return None
        try:
            result = AttemptResult(
                row["work_id"],
                row["attempt_id"],
                row["body"],
                row["recorded_at_ms"],
                row["disposition"],
            )
            if type(row["sha256"]) is not str or result.sha256 != row["sha256"]:
                raise WorkError("schema_mismatch")
            return result
        except (WorkError, KeyError, ValueError, TypeError):
            raise WorkError("schema_mismatch") from None

    def _write(self, operation: str, run: Callable[[Connection, int], T]) -> T:
        def protected(connection: Connection, _: WorkLimits, now: int) -> T:
            self._validate(connection)
            return run(connection, now)

        return self.work._write(operation, protected)

    def _read(self, operation: str, run: Callable[[Connection, int], T]) -> T:
        try:
            with closing(self.work.settings.connect()) as connection, connection.transaction():
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                self._validate(connection)
                stamp = connection.execute(
                    "SELECT floor(extract(epoch FROM clock_timestamp())*1000)::bigint AS now"
                ).fetchone()
                if stamp is None:
                    raise WorkError("storage_unavailable")
                value = run(connection, stamp["now"])
            self.work._emit(operation, "ok")
            return value
        except WorkError:
            raise
        except Exception:  # noqa: BLE001 - Dependency/cleanup details never become diagnostics.
            raise WorkError("storage_unavailable") from None

    def issue(self, scope: WorkScope, work_id: str, owner_id: str, command_id: str) -> Issuance:
        work_uuid(work_id)
        work_uuid(owner_id)
        work_identifier(command_id)

        def issue(connection: Connection, now: int) -> Issuance:
            previous = self._find_issue(connection, scope, command_id)
            if previous is not None:
                if previous.record.work_id != work_id or previous.owner_id != owner_id:
                    raise WorkError("identity_conflict")
                return Issuance(previous, False)
            record = self.work._get(connection, scope, work_id)
            bounds = execution_limits(connection, self.work.settings.schema)
            latest = self._latest(connection, scope, work_id)
            # A known eligible result remains truth after later cancellation/deadline.
            if latest is not None:
                result = self._result(connection, scope, work_id, latest.attempt_id)
                if result is not None and result.disposition == "eligible_at_commit":
                    raise WorkError("identity_conflict")
            if record.cancel_requested or record.payload.deadline_at_ms <= now:
                raise WorkError("expired")
            if latest is not None and latest.number >= bounds.max_attempts:
                raise WorkError("capacity")
            if latest is not None and latest.lease_until_ms > now:
                raise WorkError("capacity")
            active = connection.execute(
                sql.SQL(
                    "SELECT count(*) AS count FROM {} a WHERE a.lease_until_ms>%s AND NOT EXISTS(SELECT 1 FROM {} r WHERE r.attempt_id=a.attempt_id)"
                ).format(self._table("issued_attempts"), self._table("attempt_results")),
                [now],
            ).fetchone()
            if active is None or active["count"] >= bounds.max_active:
                raise WorkError("capacity")
            number = 1 if latest is None else latest.number + 1
            epoch = 1 if latest is None else latest.epoch + 1
            grant = IssuedAttempt(
                record,
                str(uuid4()),
                command_id,
                number,
                owner_id,
                epoch,
                now,
                min(now + bounds.lease_ms, record.payload.deadline_at_ms),
            )
            connection.execute(
                sql.SQL(
                    "INSERT INTO {} VALUES(%s::uuid,%s,%s,%s::uuid,%s,%s,%s::uuid,%s,%s,%s)"
                ).format(self._table("issued_attempts")),
                [
                    grant.attempt_id,
                    scope.tenant_id,
                    scope.account_id,
                    work_id,
                    command_id,
                    number,
                    owner_id,
                    epoch,
                    now,
                    grant.lease_until_ms,
                ],
            )
            return Issuance(grant, True)

        return self._write("issue", issue)

    def find_issue(self, scope: WorkScope, command_id: str) -> IssuedAttempt | None:
        work_identifier(command_id)
        return self._read(
            "find_issue", lambda connection, _: self._find_issue(connection, scope, command_id)
        )

    def complete(self, scope: WorkScope, attempt: IssuedAttempt, body: bytes) -> AttemptResult:
        if (
            type(attempt) is not IssuedAttempt
            or attempt.record.scope != scope
            or type(body) is not bytes
            or not 1 <= len(body) <= 8192
        ):
            raise WorkError("invalid_input")

        def complete(connection: Connection, now: int) -> AttemptResult:
            actual = self._find_issue(connection, scope, attempt.command_id)
            if actual is None:
                raise WorkError("not_found")
            if actual != attempt:
                raise WorkError("identity_conflict")
            old = self._result(connection, scope, attempt.record.work_id, attempt.attempt_id)
            if old is not None:
                if old.body != body:
                    raise WorkError("identity_conflict")
                return old
            latest = self._latest(connection, scope, attempt.record.work_id)
            record = self.work._get(connection, scope, attempt.record.work_id)
            disposition: ResultDisposition
            if latest is None or latest.attempt_id != attempt.attempt_id:
                disposition = "superseded"
            elif record.cancel_requested:
                disposition = "cancelled"
            elif record.payload.deadline_at_ms <= now:
                disposition = "expired"
            elif attempt.lease_until_ms <= now:
                disposition = "lease_expired"
            else:
                disposition = "eligible_at_commit"
            result = AttemptResult(
                attempt.record.work_id, attempt.attempt_id, body, now, disposition
            )
            connection.execute(
                sql.SQL("INSERT INTO {} VALUES(%s::uuid,%s,%s,%s::uuid,%s,%s,%s,%s)").format(
                    self._table("attempt_results")
                ),
                [
                    attempt.attempt_id,
                    scope.tenant_id,
                    scope.account_id,
                    attempt.record.work_id,
                    body,
                    result.sha256,
                    now,
                    disposition,
                ],
            )
            append_result_event(
                connection,
                self.work.settings.schema,
                scope,
                attempt.record.work_id,
                attempt.attempt_id,
            )
            return result

        return self._write("complete", complete)

    def result(self, scope: WorkScope, work_id: str, attempt_id: str) -> AttemptResult | None:
        work_uuid(work_id)
        work_uuid(attempt_id)

        def read(connection: Connection, _: int) -> AttemptResult | None:
            self.work._get(connection, scope, work_id)
            return self._result(connection, scope, work_id, attempt_id)

        return self._read("result", read)

    def observe(self, scope: WorkScope, work_id: str) -> ExecutionObservation:
        work_uuid(work_id)

        def read(connection: Connection, now: int) -> ExecutionObservation:
            record = self.work._get(connection, scope, work_id)
            latest = self._latest(connection, scope, work_id)
            result = (
                None
                if latest is None
                else self._result(connection, scope, work_id, latest.attempt_id)
            )
            status: ExecutionStatus
            if result is not None and result.disposition == "eligible_at_commit":
                status = "result_recorded"
            elif record.cancel_requested:
                status = "cancelled"
            elif record.payload.deadline_at_ms <= now:
                status = "expired"
            elif latest is None:
                status = "accepted"
            elif latest.lease_until_ms > now and result is None:
                status = "running"
            elif (
                latest.number
                >= execution_limits(connection, self.work.settings.schema).max_attempts
            ):
                status = "exhausted"
            else:
                status = "retryable"
            return ExecutionObservation(
                record, latest, result, 0 if latest is None else latest.number, status
            )

        return self._read("observe", read)
