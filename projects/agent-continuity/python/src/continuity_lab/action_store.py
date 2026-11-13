"""P1 result eligibility and exact case intent share one protected transaction."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import psycopg
from psycopg import sql

from .action_models import ActionError, ActionReceipt, result_digest
from .authorization import AuthenticatedActor
from .case_models import Confirmation, canonical, parse_confirmation, parse_intent
from .execution_models import ExecutionError
from .execution_store import ExecutionStore
from .models import IdempotencyConflict
from .postgres_case import PostgresCaseAuthority
from .postgres_migrations import validate_schema
from .postgres_settings import PostgresSettings
from .postgres_store import PostgresExecutionStore
from .postgres_unit_of_work import protected_transaction
from .work_models import WorkError, WorkLimits, WorkScope, work_identifier, work_uuid
from .work_schema import Connection, validate_work_schema, work_schema_version
from .work_store import WorkStore

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())


def translated(error: Exception) -> ActionError:
    if isinstance(error, ActionError):
        return ActionError(error.code)
    if isinstance(error, WorkError):
        return ActionError(error.code)
    if isinstance(error, IdempotencyConflict):
        return ActionError("identity_conflict")
    if isinstance(error, ExecutionError):
        code = getattr(error, "code", "storage_unavailable")
        mapping = {
            "authentication_required": "unauthorized",
            "capacity_exhausted": "capacity",
            "invalid_stored_state": "schema_mismatch",
            "execution_not_found": "not_found",
            "not_found": "not_found",
            "idempotency_conflict": "identity_conflict",
            "transition_conflict": "identity_conflict",
            "case_cancelled": "case_cancelled",
            "stale_revision": "stale_revision",
            "invalid_confirmation": "invalid_confirmation",
            "quote_expired": "quote_expired",
            "deadline_expired": "deadline_expired",
            "intent_committed": "intent_committed",
            "capacity_exceeded": "capacity",
            "execution_capacity_exceeded": "capacity",
        }
        return ActionError(
            mapping.get(code, "storage_unavailable") if type(code) is str else "storage_unavailable"
        )
    return ActionError("storage_unavailable")


class ActionStore:
    """Fixed booking-admission→work-admission→case/control lock order, no external I/O."""

    def __init__(
        self,
        work: WorkStore,
        case_settings: PostgresSettings,
        failpoint: Callable[[str], None] | None = None,
    ) -> None:
        self.work, self.case_settings, self.failpoint = work, case_settings, failpoint
        self.executions = ExecutionStore(work)
        self.cases = PostgresExecutionStore(case_settings)
        self._telemetry_failures = 0
        self._telemetry_lock = threading.Lock()
        with closing(work.settings.connect()) as connection:
            self._validate_work(connection)
        with closing(case_settings.connect()) as connection:
            validate_schema(
                connection, case_settings.schema, require_active=True, minimum_version=4
            )

    @property
    def telemetry_failures(self) -> int:
        with self._telemetry_lock:
            return self._telemetry_failures

    def _emit(self, operation: str, code: str) -> None:
        try:
            LOGGER.info(
                "guarded_action",
                extra={"event": "guarded_action", "operation": operation, "code": code},
            )
        except Exception:  # noqa: BLE001 - a log sink cannot change committed truth
            with self._telemetry_lock:
                self._telemetry_failures += 1

    def _hit(self, stage: str) -> None:
        if self.failpoint is not None:
            self.failpoint(stage)

    def _validate_work(self, connection: Connection) -> WorkLimits:
        bounds = validate_work_schema(connection, self.work.settings)
        if work_schema_version(connection, self.work.settings.schema) not in (3, 4):
            raise ActionError("schema_mismatch")
        return bounds

    def _table(self) -> sql.Identifier:
        return sql.Identifier(self.work.settings.schema, "result_actions")

    def _select(self) -> sql.Composed:
        return sql.SQL(
            "SELECT action_id::text,tenant_id,account_id,work_id::text,attempt_id::text,result_sha256,case_schema,case_scope_id,case_actor_id,case_task_id::text,case_id::text,expected_revision,command_id,confirmation_json,intent_id::text,intent_json,committed_at_ms FROM {} WHERE tenant_id=%s AND account_id=%s"
        ).format(self._table())

    @staticmethod
    def _decode(row: dict[str, Any]) -> ActionReceipt:
        try:
            confirmation = parse_confirmation(json.loads(row["confirmation_json"]))
            intent = parse_intent(json.loads(row["intent_json"]))
            if (
                canonical(confirmation.payload()) != row["confirmation_json"]
                or canonical(intent.payload()) != row["intent_json"]
                or intent.intent_id != row["intent_id"]
            ):
                raise ActionError("schema_mismatch")
            return ActionReceipt(
                row["action_id"],
                WorkScope(row["tenant_id"], row["account_id"]),
                row["work_id"],
                row["attempt_id"],
                row["result_sha256"],
                row["case_schema"],
                row["case_scope_id"],
                row["case_actor_id"],
                row["case_task_id"],
                row["case_id"],
                row["expected_revision"],
                row["command_id"],
                confirmation,
                intent,
                row["committed_at_ms"],
            )
        except (ActionError, WorkError, ValueError, TypeError, KeyError, AttributeError):
            raise ActionError("schema_mismatch") from None

    def _find(
        self,
        connection: Connection,
        scope: WorkScope,
        *,
        command_id: str | None = None,
        work_id: str | None = None,
    ) -> ActionReceipt | None:
        clause, value = (
            ("command_id=%s", command_id)
            if command_id is not None
            else ("work_id=%s::uuid", work_id)
        )
        row = connection.execute(
            self._select() + sql.SQL(" AND " + clause), [scope.tenant_id, scope.account_id, value]
        ).fetchone()
        return None if row is None else self._decode(row)

    def read(
        self,
        scope: WorkScope,
        actor: AuthenticatedActor,
        *,
        command_id: str | None = None,
        work_id: str | None = None,
    ) -> ActionReceipt | None:
        if command_id is not None:
            work_identifier(command_id)
        elif work_id is not None:
            work_uuid(work_id)
        else:
            raise ActionError("invalid_input")
        try:
            with closing(self.work.settings.connect()) as connection, connection.transaction():
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                self._validate_work(connection)
                result = self._find(connection, scope, command_id=command_id, work_id=work_id)
            if result is not None and (
                result.case_schema,
                result.case_scope_id,
                result.case_actor_id,
            ) != (self.case_settings.schema, actor.scope_id, actor.actor_id):
                result = None
            self._emit("inspect", "ok")
            return result
        except Exception as error:  # noqa: BLE001 - one safe dependency boundary
            checked = translated(error)
            self._emit("inspect", checked.code)
            raise checked from None

    def authorize(
        self,
        scope: WorkScope,
        actor: AuthenticatedActor,
        *,
        work_id: str,
        attempt_id: str,
        result_sha256: str,
        expected_revision: int,
        confirmation: Confirmation,
        command_id: str,
    ) -> ActionReceipt:
        work_uuid(work_id)
        work_uuid(attempt_id)
        result_digest(result_sha256)
        work_identifier(command_id)
        committing = False
        try:
            self._hit("authorize.before_locks")
            with protected_transaction(self.cases) as connection:
                # Both profiles are known before any metadata/payload use. All case writes
                # share the booking lock; work-only writes never acquire it in reverse.
                validate_schema(
                    connection, self.case_settings.schema, require_active=True, minimum_version=4
                )
                self._validate_work(connection)
                guard = connection.execute(
                    sql.SQL(
                        "SELECT record_count,cancel_count FROM {}.admission WHERE singleton FOR UPDATE"
                    ).format(sql.Identifier(self.work.settings.schema))
                ).fetchone()
                bounds = self._validate_work(connection)
                counts = connection.execute(
                    sql.SQL(
                        "SELECT (SELECT count(*) FROM {}.accepted_work) AS record_count,(SELECT count(*) FROM {}.cancellation_commands) AS cancel_count"
                    ).format(*([sql.Identifier(self.work.settings.schema)] * 2))
                ).fetchone()
                if (
                    guard is None
                    or guard != counts
                    or guard["record_count"] > bounds.max_records
                    or guard["cancel_count"] > bounds.max_cancel_commands
                ):
                    raise ActionError("schema_mismatch")
                self._hit("authorize.after_locks")
                prior = self._find(connection, scope, command_id=command_id)
                if prior is not None:
                    if (
                        prior.work_id,
                        prior.attempt_id,
                        prior.result_sha256,
                        prior.case_schema,
                        prior.case_scope_id,
                        prior.case_actor_id,
                        prior.expected_revision,
                        prior.confirmation,
                    ) != (
                        work_id,
                        attempt_id,
                        result_sha256,
                        self.case_settings.schema,
                        actor.scope_id,
                        actor.actor_id,
                        expected_revision,
                        confirmation,
                    ):
                        raise ActionError("identity_conflict")
                    value = prior
                else:
                    if self._find(connection, scope, work_id=work_id) is not None:
                        raise ActionError("identity_conflict")
                    record = self.work._get(connection, scope, work_id)
                    latest = self.executions._latest(connection, scope, work_id)
                    known = self.executions._result(connection, scope, work_id, attempt_id)
                    if (
                        latest is None
                        or latest.attempt_id != attempt_id
                        or known is None
                        or known.sha256 != result_sha256
                        or known.disposition != "eligible_at_commit"
                    ):
                        raise ActionError("invalid_result")
                    stamp = connection.execute(
                        "SELECT floor(extract(epoch FROM clock_timestamp())*1000)::bigint AS now"
                    ).fetchone()
                    if stamp is None:
                        raise ActionError("storage_unavailable")
                    now = stamp["now"]
                    if record.cancel_requested or record.payload.deadline_at_ms <= now:
                        raise ActionError("expired")
                    if (
                        confirmation.quote.schema_version != 2
                        or confirmation.quote.revision != expected_revision
                    ):
                        raise ActionError("invalid_confirmation")

                    guard_time = [now]

                    def guarded_clock() -> datetime:
                        # CaseAuthority asks for time after its case/control locks. The
                        # work lock is still held; check the original deadline again.
                        live = connection.execute(
                            "SELECT floor(extract(epoch FROM clock_timestamp())*1000)::bigint AS now"
                        ).fetchone()
                        if live is None:
                            raise ActionError("storage_unavailable")
                        if record.payload.deadline_at_ms <= live["now"]:
                            raise ActionError("expired")
                        guard_time[0] = live["now"]
                        return datetime.fromtimestamp(live["now"] / 1000, UTC)

                    authority = PostgresCaseAuthority(self.cases, clock=guarded_clock)
                    existing_case = authority.get_in_transaction(
                        connection, actor, confirmation.quote.task_id
                    )
                    if existing_case.intent is not None:
                        raise ActionError("intent_committed")
                    intent = authority.commit_intent_in_transaction(
                        connection, actor, confirmation, command_id
                    )
                    now = guard_time[0]
                    value = ActionReceipt(
                        str(uuid4()),
                        scope,
                        work_id,
                        attempt_id,
                        result_sha256,
                        self.case_settings.schema,
                        actor.scope_id,
                        actor.actor_id,
                        confirmation.quote.task_id,
                        confirmation.quote.case_id or "",
                        expected_revision,
                        command_id,
                        confirmation,
                        intent,
                        now,
                    )
                    connection.execute(
                        sql.SQL(
                            "INSERT INTO {} VALUES(%s::uuid,%s,%s,%s::uuid,%s::uuid,%s,%s,%s,%s,%s::uuid,%s::uuid,%s,%s,%s,%s::uuid,%s,%s)"
                        ).format(self._table()),
                        [
                            value.action_id,
                            scope.tenant_id,
                            scope.account_id,
                            work_id,
                            attempt_id,
                            result_sha256,
                            self.case_settings.schema,
                            actor.scope_id,
                            actor.actor_id,
                            value.case_task_id,
                            value.case_id,
                            expected_revision,
                            command_id,
                            canonical(confirmation.payload()),
                            intent.intent_id,
                            canonical(intent.payload()),
                            now,
                        ],
                    )
                self._hit("authorize.before_commit")
                committing = True
            self._hit("authorize.after_commit")
            self._emit("authorize", "ok")
            return value
        except psycopg.errors.LockNotAvailable:
            checked = ActionError("acknowledgement_unknown" if committing else "capacity")
            self._emit("authorize", checked.code)
            raise checked from None
        except Exception as error:  # noqa: BLE001 - never expose SQL, payloads or dependency diagnostics
            checked = ActionError("acknowledgement_unknown") if committing else translated(error)
            self._emit("authorize", checked.code)
            raise checked from None
