"""P1-owned immutable accepted work; no executor, retry scheduler or booking action."""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import closing
from threading import Lock
from typing import Any, TypeVar
from uuid import uuid4

import psycopg
from psycopg import sql

from .postgres_settings import PostgresSettings
from .work_models import (
    WorkCancellation,
    WorkCode,
    WorkError,
    WorkLimits,
    WorkPayload,
    WorkRecord,
    WorkScope,
    WorkSubmission,
    work_identifier,
    work_uuid,
)
from .work_schema import Connection, check_settings, validate_work_schema

LOGGER = logging.getLogger("continuity_lab.readonly_work")
LOGGER.addHandler(logging.NullHandler())
T = TypeVar("T")


def _event(operation: str, code: str) -> bool:
    try:
        LOGGER.log(
            logging.INFO if code == "ok" else logging.WARNING,
            "readonly_work_operation",
            extra={"event": "readonly_work_operation", "operation": operation, "code": code},
        )
        return True
    except Exception:  # noqa: BLE001 - Application log handlers cannot change work truth.
        return False


class WorkStore:
    """Short protected transactions and immutable scoped rows, no external I/O.

    Trusted failpoints are harness-only and cannot be selected by payload bytes.
    Local connection/SQL budgets come from PostgresSettings; async callers own a
    finite I/O slot until the actual synchronous operation finishes.
    """

    def __init__(
        self, settings: PostgresSettings, failpoint: Callable[[str], None] | None = None
    ) -> None:
        check_settings(settings)
        self.settings, self.failpoint = settings, failpoint
        self.telemetry_failures = 0
        self._telemetry_lock = Lock()
        try:
            with closing(settings.connect()) as connection:
                validate_work_schema(connection, settings)
        except WorkError:
            raise
        except Exception:  # noqa: BLE001 - Outer storage/failpoint/cleanup boundary.
            raise WorkError("storage_unavailable") from None

    def _emit(self, operation: str, code: str) -> None:
        if not _event(operation, code):
            with self._telemetry_lock:
                self.telemetry_failures += 1

    def _table(self, name: str) -> sql.Identifier:
        return sql.Identifier(self.settings.schema, name)

    def _hit(self, stage: str) -> None:
        if self.failpoint is not None:
            self.failpoint(stage)

    def _selection(self) -> sql.Composed:
        return sql.SQL(
            "SELECT w.work_id::text,w.tenant_id,w.account_id,w.idempotency_key,w.operation,w.body,w.sha256,w.deadline_at_ms,w.accepted_at_ms,EXISTS(SELECT 1 FROM {} c WHERE c.tenant_id=w.tenant_id AND c.account_id=w.account_id AND c.work_id=w.work_id) AS cancel_requested FROM {} w"
        ).format(self._table("cancellation_commands"), self._table("accepted_work"))

    def _decode(self, row: dict[str, Any]) -> WorkRecord:
        try:
            if type(row["body"]) is not bytes:
                raise WorkError("schema_mismatch")
            payload = WorkPayload(row["operation"], row["body"], row["deadline_at_ms"])
            if type(row["sha256"]) is not str or payload.sha256 != row["sha256"]:
                raise WorkError("schema_mismatch")
            return WorkRecord(
                row["work_id"],
                WorkScope(row["tenant_id"], row["account_id"]),
                row["idempotency_key"],
                payload,
                row["accepted_at_ms"],
                row["cancel_requested"],
            )
        except (WorkError, KeyError, TypeError, ValueError):
            raise WorkError("schema_mismatch") from None

    def _find(self, connection: Connection, scope: WorkScope, key: str) -> WorkRecord | None:
        row = connection.execute(
            self._selection()
            + sql.SQL(" WHERE w.tenant_id=%s AND w.account_id=%s AND w.idempotency_key=%s"),
            [scope.tenant_id, scope.account_id, key],
        ).fetchone()
        return None if row is None else self._decode(row)

    def _get(self, connection: Connection, scope: WorkScope, work_id: str) -> WorkRecord:
        row = connection.execute(
            self._selection()
            + sql.SQL(" WHERE w.tenant_id=%s AND w.account_id=%s AND w.work_id=%s::uuid"),
            [scope.tenant_id, scope.account_id, work_id],
        ).fetchone()
        if row is None:
            raise WorkError("not_found")
        return self._decode(row)

    def _write(self, operation: str, run: Callable[[Connection, WorkLimits, int], T]) -> T:
        committing = False
        code: WorkCode
        try:
            with closing(self.settings.connect()) as connection:
                bounds = validate_work_schema(connection, self.settings)
                with connection.transaction():
                    guard = connection.execute(
                        sql.SQL(
                            "SELECT record_count,cancel_count FROM {} WHERE singleton FOR UPDATE"
                        ).format(self._table("admission"))
                    ).fetchone()
                    if guard is None:
                        raise WorkError("schema_mismatch")
                    # Revalidate after waiting on the owner/admission boundary.
                    if validate_work_schema(connection, self.settings) != bounds:
                        raise WorkError("schema_mismatch")
                    counts = connection.execute(
                        sql.SQL(
                            "SELECT (SELECT count(*) FROM {}) AS records,(SELECT count(*) FROM {}) AS cancellations"
                        ).format(self._table("accepted_work"), self._table("cancellation_commands"))
                    ).fetchone()
                    if (
                        counts is None
                        or guard
                        != {
                            "record_count": counts["records"],
                            "cancel_count": counts["cancellations"],
                        }
                        or guard["record_count"] > bounds.max_records
                        or guard["cancel_count"] > bounds.max_cancel_commands
                    ):
                        raise WorkError("schema_mismatch")
                    stamp = connection.execute(
                        "SELECT floor(extract(epoch FROM clock_timestamp())*1000)::bigint AS now"
                    ).fetchone()
                    if stamp is None:
                        raise WorkError("storage_unavailable")
                    result = run(connection, bounds, stamp["now"])
                    self._hit(operation + ".before_commit")
                    committing = True
                self._hit(operation + ".after_commit")
            self._emit(operation, "ok")
            return result
        except psycopg.errors.LockNotAvailable:
            code = "acknowledgement_unknown" if committing else "capacity"
            self._emit(operation, code)
            raise WorkError(code) from None
        except WorkError as error:
            code = "acknowledgement_unknown" if committing else error.code
            self._emit(operation, code)
            raise WorkError(code) from None
        except Exception:  # noqa: BLE001 - Outer storage/failpoint/cleanup boundary.
            code = "acknowledgement_unknown" if committing else "storage_unavailable"
            self._emit(operation, code)
            raise WorkError(code) from None

    def submit(self, scope: WorkScope, key: str, payload: WorkPayload) -> WorkSubmission:
        work_identifier(key)
        if type(scope) is not WorkScope or type(payload) is not WorkPayload:
            raise WorkError("invalid_input")
        # Reconstruct so even trusted code cannot smuggle a modified digest.
        snapshot = WorkPayload(payload.operation, payload.body, payload.deadline_at_ms)

        def accept(connection: Connection, bounds: WorkLimits, now: int) -> WorkSubmission:
            existing = self._find(connection, scope, key)
            if existing is not None:
                if existing.payload != snapshot:
                    raise WorkError("identity_conflict")
                return WorkSubmission(existing, False)
            if snapshot.deadline_at_ms <= now or snapshot.deadline_at_ms - now > 60000:
                raise WorkError("expired")
            count = connection.execute(
                sql.SQL("SELECT record_count FROM {} WHERE singleton").format(
                    self._table("admission")
                )
            ).fetchone()
            if count is None or count["record_count"] >= bounds.max_records:
                raise WorkError("capacity")
            work_id = str(uuid4())
            connection.execute(
                sql.SQL("INSERT INTO {} VALUES(%s::uuid,%s,%s,%s,%s,%s,%s,%s,%s)").format(
                    self._table("accepted_work")
                ),
                [
                    work_id,
                    scope.tenant_id,
                    scope.account_id,
                    key,
                    snapshot.operation,
                    snapshot.body,
                    snapshot.sha256,
                    snapshot.deadline_at_ms,
                    now,
                ],
            )
            connection.execute(
                sql.SQL("UPDATE {} SET record_count=record_count+1 WHERE singleton").format(
                    self._table("admission")
                )
            )
            return WorkSubmission(self._get(connection, scope, work_id), True)

        return self._write("submit", accept)

    def find(self, scope: WorkScope, key: str) -> WorkRecord | None:
        work_identifier(key)
        try:
            with closing(self.settings.connect()) as connection:
                validate_work_schema(connection, self.settings)
                result = self._find(connection, scope, key)
            self._emit("find", "ok")
            return result
        except WorkError:
            raise
        except Exception:  # noqa: BLE001 - Outer storage/failpoint/cleanup boundary.
            raise WorkError("storage_unavailable") from None

    def get(self, scope: WorkScope, work_id: str) -> WorkRecord:
        work_uuid(work_id)
        try:
            with closing(self.settings.connect()) as connection:
                validate_work_schema(connection, self.settings)
                result = self._get(connection, scope, work_id)
            self._emit("get", "ok")
            return result
        except WorkError:
            raise
        except Exception:  # noqa: BLE001 - Outer storage/failpoint/cleanup boundary.
            raise WorkError("storage_unavailable") from None

    def cancel(self, scope: WorkScope, work_id: str, command_id: str) -> WorkCancellation:
        work_uuid(work_id)
        work_identifier(command_id)

        def request(connection: Connection, bounds: WorkLimits, now: int) -> WorkCancellation:
            self._get(connection, scope, work_id)
            existing = connection.execute(
                sql.SQL(
                    "SELECT cancellation_id::text,work_id::text,command_id,requested_at_ms FROM {} WHERE tenant_id=%s AND account_id=%s AND command_id=%s"
                ).format(self._table("cancellation_commands")),
                [scope.tenant_id, scope.account_id, command_id],
            ).fetchone()
            if existing is not None:
                if existing["work_id"] != work_id:
                    raise WorkError("identity_conflict")
                return WorkCancellation(**existing)
            count = connection.execute(
                sql.SQL("SELECT cancel_count FROM {} WHERE singleton").format(
                    self._table("admission")
                )
            ).fetchone()
            if count is None or count["cancel_count"] >= bounds.max_cancel_commands:
                raise WorkError("capacity")
            cancellation = WorkCancellation(str(uuid4()), work_id, command_id, now)
            connection.execute(
                sql.SQL("INSERT INTO {} VALUES(%s::uuid,%s,%s,%s::uuid,%s,%s)").format(
                    self._table("cancellation_commands")
                ),
                [
                    cancellation.cancellation_id,
                    scope.tenant_id,
                    scope.account_id,
                    work_id,
                    command_id,
                    now,
                ],
            )
            connection.execute(
                sql.SQL("UPDATE {} SET cancel_count=cancel_count+1 WHERE singleton").format(
                    self._table("admission")
                )
            )
            return cancellation

        return self._write("cancel", request)
