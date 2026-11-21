"""Bounded PostgreSQL continuation state, attached to original inquiry identities.

The original execution and attempts remain their sole owners. This module adds
policy, waits and immutable signal receipts, not a competing durable job queue.
Every method owns one short protected transaction; suppliers run elsewhere.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager, nullcontext
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg import sql

from .authorization import AuthenticatedActor
from .case_models import (
    Confirmation,
    InvalidConfirmation,
    QuoteSnapshot,
    parse_confirmation,
    parse_quote,
)
from .execution_codec import decode_attempt
from .execution_models import (
    ExecutionCapacityExceeded,
    ExecutionRecord,
    ExecutionStatus,
    FailureCode,
    InquiryResult,
    InvalidStoredState,
    TransitionConflict,
    UnsupportedOperation,
)
from .lease_models import LeaseGrant
from .lifecycle_models import (
    LifecycleSnapshot,
    LifecycleState,
    ManagedClaim,
    SignalReceipt,
    WaitAdvance,
    WaitSnapshot,
    WaitState,
)
from .models import IdempotencyConflict
from .postgres_case import PostgresCaseAuthority
from .postgres_leases import require_worker_lease
from .postgres_store import PostgresExecutionStore
from .postgres_unit_of_work import protected_transaction
from .retry_policy import FailureClass, RetryError, RetryPolicy, decide_retry, instant, parse_policy

LOGGER = logging.getLogger("continuity_lab.postgres_lifecycle")
LOGGER.addHandler(logging.NullHandler())
Connection = psycopg.Connection[dict[str, Any]]


def _now() -> datetime:
    return datetime.now(UTC)


def _identity(value: str) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > 128
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise ValueError("A bounded nonempty identity is required")
    return value


def _uuid(value: str) -> str:
    if type(value) is not str or str(UUID(value)) != value:
        raise ValueError("A canonical UUID is required")
    return value


def _canonical(value: Mapping[str, object]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _time(value: object) -> str:
    if type(value) is not str or not 1 <= len(value) <= 64 or value != value.strip():
        raise ValueError("Stored business time is invalid")
    parsed = instant(datetime.fromisoformat(value))
    if parsed.isoformat() != value:
        raise ValueError("Stored business time must be canonical UTC")
    return value


def _event(event: str, code: str = "ok") -> None:
    try:
        LOGGER.info(event, extra={"event": event, "code": code})
    except Exception:  # noqa: BLE001 - telemetry cannot alter committed state or failures
        return


def _expect_one(cursor: psycopg.Cursor[dict[str, Any]]) -> psycopg.Cursor[dict[str, Any]]:
    if cursor.rowcount != 1:
        raise TransitionConflict("Protected continuation write lost its expected state")
    return cursor


def _control(row: dict[str, Any]) -> LifecycleSnapshot:
    try:
        state = LifecycleState(row["state"])
        version = row["version"]
        if type(version) is not int or not 0 <= version <= 9223372036854775807:
            raise ValueError("Invalid control version")
        due = None if row["next_attempt_at"] is None else _time(row["next_attempt_at"])
        if (state == LifecycleState.RETRY_WAIT) != (due is not None):
            raise ValueError("Invalid control eligibility")
        return LifecycleSnapshot(
            _identity(row["task_id"]),
            state,
            parse_policy(row["policy_json"]),
            _time(row["deadline"]),
            due,
            version,
            None if row["last_failure"] is None else FailureClass(row["last_failure"]),
            None if row["error_code"] is None else RetryError(row["error_code"]),
            _time(row["updated_at"]),
        )
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as error:
        raise InvalidStoredState("Execution continuation contains invalid stored state") from error


def _wait(row: dict[str, Any]) -> WaitSnapshot:
    try:
        quote = parse_quote(json.loads(row["quote_json"]))
        if quote.task_id != row["task_id"] or _canonical(quote.payload()) != row["quote_json"]:
            raise ValueError("Invalid stored quote")
        state = WaitState(row["state"])
        finished = None if row["finished_at"] is None else _time(row["finished_at"])
        if (state == WaitState.PENDING) != (finished is None):
            raise ValueError("Invalid wait disposition")
        return WaitSnapshot(
            _uuid(row["wait_id"]),
            _identity(row["task_id"]),
            quote,
            _time(row["deadline"]),
            state,
            _time(row["created_at"]),
            finished,
        )
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as error:
        raise InvalidStoredState("Execution wait contains invalid stored state") from error


class PostgresLifecycle:
    """One original execution with bounded policy, dormant waits and typed inbox.

    Trusted worker methods take explicit scope. Public caller adapters must bind
    actor/scope from authentication before calling the actor-bound wait methods.
    Retained identities are never deleted; finite capacity rejects new records.
    """

    def __init__(
        self,
        executions: PostgresExecutionStore,
        *,
        cases: PostgresCaseAuthority | None = None,
        clock: Callable[[], datetime] = _now,
        failpoint: Callable[[str], None] | None = None,
        maximum_controls: int = 10000,
        maximum_signals: int = 100,
        maximum_waits: int = 8,
        worker_lease: LeaseGrant | None = None,
    ) -> None:
        for value, maximum in (
            (maximum_controls, 100000),
            (maximum_signals, 1000),
            (maximum_waits, 100),
        ):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError("Continuation capacity must be a bounded positive integer")
        if worker_lease is not None and type(worker_lease) is not LeaseGrant:
            raise ValueError("A typed explicit worker lease is required")
        self.worker_lease = worker_lease
        self.executions, self.clock, self.failpoint = executions, clock, failpoint
        self.cases = cases if cases is not None else PostgresCaseAuthority(executions, clock=clock)
        self.maximum_controls, self.maximum_signals, self.maximum_waits = (
            maximum_controls,
            maximum_signals,
            maximum_waits,
        )

    def worker_slot(self) -> AbstractContextManager[None]:
        """A cooperating session slot is independent of each explicit execution lease."""
        return self.executions.worker_slot() if self.worker_lease is None else nullcontext()

    def _guard(self, connection: Connection, scope_id: str, task_id: str) -> None:
        require_worker_lease(
            connection, self.executions, self.worker_lease, scope_id=scope_id, task_id=task_id
        )

    def _table(self, name: str) -> sql.Identifier:
        return sql.Identifier(self.executions.settings.schema, name)

    def _hit(self, name: str) -> None:
        if self.failpoint is not None:
            self.failpoint(name)

    def _current(
        self, connection: Connection, scope_id: str, task_id: str
    ) -> tuple[ExecutionRecord, LifecycleSnapshot]:
        execution = self.executions._get(connection, _identity(scope_id), _identity(task_id))
        row = connection.execute(
            sql.SQL("SELECT * FROM {} WHERE task_id=%s FOR UPDATE").format(
                self._table("execution_controls")
            ),
            (task_id,),
        ).fetchone()
        if row is None:
            raise UnsupportedOperation("Execution continuation is not enabled")
        return execution, _control(row)

    def _set(
        self,
        connection: Connection,
        current: LifecycleSnapshot,
        state: LifecycleState,
        *,
        now: datetime,
        due: datetime | None = None,
        failure: FailureClass | None = None,
        error: RetryError | None = None,
    ) -> LifecycleSnapshot:
        changed = _expect_one(
            connection.execute(
                sql.SQL(
                    "UPDATE {} SET state=%s,next_attempt_at=%s,version=version+1,last_failure=%s,error_code=%s,updated_at=%s WHERE task_id=%s AND version=%s RETURNING *"
                ).format(self._table("execution_controls")),
                (
                    state.value,
                    None if due is None else instant(due).isoformat(),
                    None if failure is None else failure.value,
                    None if error is None else error.value,
                    instant(now).isoformat(),
                    current.task_id,
                    current.version,
                ),
            )
        ).fetchone()
        if changed is None:
            raise TransitionConflict("Execution continuation changed before this command")
        return _control(changed)

    def get(self, *, scope_id: str, task_id: str) -> LifecycleSnapshot:
        with protected_transaction(self.executions) as connection:
            return self._current(connection, scope_id, task_id)[1]

    def manage(
        self, *, scope_id: str, task_id: str, policy: RetryPolicy, deadline: datetime
    ) -> LifecycleSnapshot:
        if type(policy) is not RetryPolicy:
            raise ValueError("A typed bounded retry policy is required")
        if policy.max_attempts > self.executions.maximum_attempts:
            raise ValueError("Managed retry policy exceeds the configured worker attempt budget")
        deadline = instant(deadline)
        with protected_transaction(self.executions) as connection:
            value, created = self.manage_in_transaction(
                connection, scope_id=scope_id, task_id=task_id, policy=policy, deadline=deadline
            )
        if created:
            self._hit("lifecycle.after_manage_commit")
            _event("continuation_enabled")
        return value

    def manage_in_transaction(
        self,
        connection: Connection,
        *,
        scope_id: str,
        task_id: str,
        policy: RetryPolicy,
        deadline: datetime,
    ) -> tuple[LifecycleSnapshot, bool]:
        """Create continuation atomically with accepted work in the caller transaction."""
        if type(policy) is not RetryPolicy:
            raise ValueError("A typed bounded retry policy is required")
        if policy.max_attempts > self.executions.maximum_attempts:
            raise ValueError("Managed retry policy exceeds the configured worker attempt budget")
        deadline = instant(deadline)
        execution = self.executions._get(connection, _identity(scope_id), _identity(task_id))
        row = connection.execute(
            sql.SQL("SELECT * FROM {} WHERE task_id=%s").format(self._table("execution_controls")),
            (task_id,),
        ).fetchone()
        if row is not None:
            value = _control(row)
            if value.policy != policy or value.deadline != deadline.isoformat():
                raise IdempotencyConflict("Execution continuation already has another policy")
            return value, False
        if execution.status not in {ExecutionStatus.ACCEPTED, ExecutionStatus.SUCCEEDED}:
            raise UnsupportedOperation(
                "Only unstarted or completed inquiries can enter continuation"
            )
        if execution.status == ExecutionStatus.SUCCEEDED:
            self.executions._check_pending_capacity(connection)
        if deadline <= instant(self.clock()):
            raise ValueError("A continuation deadline must be in the future")
        count = connection.execute(
            sql.SQL("SELECT COUNT(*) AS count FROM {}").format(self._table("execution_controls"))
        ).fetchone()
        assert count is not None
        if count["count"] >= self.maximum_controls:
            raise ExecutionCapacityExceeded("Retained execution continuation capacity is exhausted")
        # Basic workers also hold this separate nonblocking session slot.
        # Global admission lock is already owned; failure simply rolls back.
        with self.executions.worker_slot():
            row = connection.execute(
                sql.SQL(
                    "INSERT INTO {} (task_id,state,policy_json,deadline,next_attempt_at,version,last_failure,error_code,updated_at) VALUES (%s,%s,%s,%s,NULL,0,NULL,NULL,%s) RETURNING *"
                ).format(self._table("execution_controls")),
                (
                    task_id,
                    LifecycleState.READY.value
                    if execution.status == ExecutionStatus.ACCEPTED
                    else LifecycleState.INQUIRY_COMPLETE.value,
                    policy.canonical(),
                    deadline.isoformat(),
                    instant(self.clock()).isoformat(),
                ),
            ).fetchone()
        assert row is not None
        self._hit("lifecycle.before_manage_commit")
        value = _control(row)
        return value, True

    def _end_without_dispatch(
        self,
        connection: Connection,
        execution: ExecutionRecord,
        current: LifecycleSnapshot,
        *,
        ambiguous: bool,
        now: datetime,
        error: RetryError,
    ) -> LifecycleSnapshot:
        stamp = instant(now).isoformat()
        connection.execute(
            sql.SQL(
                "UPDATE {} SET status='interrupted',finished_at=%s WHERE task_id=%s AND status='started'"
            ).format(self._table("execution_attempts")),
            (stamp, execution.task_id),
        )
        _expect_one(
            connection.execute(
                sql.SQL(
                    "UPDATE {} SET status=%s,version=version+1,updated_at=%s,error_code=%s WHERE task_id=%s AND version=%s"
                ).format(self._table("executions")),
                (
                    ExecutionStatus.RUNNING.value if ambiguous else ExecutionStatus.FAILED.value,
                    stamp,
                    None if ambiguous else FailureCode.DEPENDENCY_UNAVAILABLE.value,
                    execution.task_id,
                    execution.version,
                ),
            )
        )
        return self._set(
            connection,
            current,
            LifecycleState.UNCERTAIN if ambiguous else LifecycleState.FAILED,
            now=now,
            failure=FailureClass.AMBIGUOUS if ambiguous else FailureClass.TRANSIENT,
            error=error,
        )

    def claim_due(self, *, scope_id: str, task_id: str) -> ManagedClaim | None:
        """Called only while the cooperating worker session slot is held."""
        with protected_transaction(self.executions) as connection:
            execution, current = self._current(connection, scope_id, task_id)
            self._guard(connection, scope_id, task_id)
            if current.state == LifecycleState.INQUIRY_COMPLETE and instant(
                self.clock()
            ) >= datetime.fromisoformat(current.deadline):
                self._set(
                    connection,
                    current,
                    LifecycleState.FAILED,
                    now=instant(self.clock()),
                    error=RetryError.DEADLINE_EXPIRED,
                )
                return None
            if current.state not in {
                LifecycleState.READY,
                LifecycleState.RUNNING,
                LifecycleState.RETRY_WAIT,
            }:
                return None
            now = instant(self.clock())
            if current.state == LifecycleState.RETRY_WAIT and now < datetime.fromisoformat(
                current.next_attempt_at or ""
            ):
                return None
            rows = connection.execute(
                sql.SQL("SELECT * FROM {} WHERE task_id=%s ORDER BY attempt_no").format(
                    self._table("execution_attempts")
                ),
                (task_id,),
            ).fetchall()
            attempts = tuple(decode_attempt(row) for row in rows)
            active = tuple(row for row in attempts if row.status.value == "started")
            if [row.attempt_no for row in attempts] != list(range(1, len(attempts) + 1)) or (
                active and active[0].attempt_no != len(attempts)
            ):
                raise InvalidStoredState("Managed attempt history is not contiguous/current")
            recovered = current.state == LifecycleState.RUNNING
            if (
                (recovered and (execution.status != ExecutionStatus.RUNNING or len(active) != 1))
                or (not recovered and active)
                or (
                    current.state == LifecycleState.READY
                    and execution.status != ExecutionStatus.ACCEPTED
                )
                or (
                    current.state == LifecycleState.RETRY_WAIT
                    and execution.status != ExecutionStatus.RUNNING
                )
            ):
                raise InvalidStoredState("Execution continuation and attempt state disagree")
            if (
                now >= datetime.fromisoformat(current.deadline)
                or len(attempts) >= current.policy.max_attempts
            ):
                self._end_without_dispatch(
                    connection,
                    execution,
                    current,
                    ambiguous=recovered,
                    now=now,
                    error=RetryError.AMBIGUOUS_OUTCOME
                    if recovered
                    else RetryError.DEADLINE_EXPIRED
                    if now >= datetime.fromisoformat(current.deadline)
                    else RetryError.RETRY_EXHAUSTED,
                )
                return None
            if recovered:
                _expect_one(
                    connection.execute(
                        sql.SQL(
                            "UPDATE {} SET status='interrupted',finished_at=%s WHERE attempt_id=%s AND status='started'"
                        ).format(self._table("execution_attempts")),
                        (now.isoformat(), active[0].attempt_id),
                    )
                )
            attempt = connection.execute(
                sql.SQL(
                    "INSERT INTO {} (attempt_id,task_id,attempt_no,status,started_at,finished_at,error_code) VALUES (%s,%s,%s,'started',%s,NULL,NULL) RETURNING *"
                ).format(self._table("execution_attempts")),
                (str(uuid4()), task_id, len(attempts) + 1, now.isoformat()),
            ).fetchone()
            changed = _expect_one(
                connection.execute(
                    sql.SQL(
                        "UPDATE {} SET status='running',version=version+1,updated_at=%s WHERE task_id=%s AND version=%s"
                    ).format(self._table("executions")),
                    (now.isoformat(), task_id, execution.version),
                )
            )
            if changed.rowcount != 1 or attempt is None:
                raise TransitionConflict("Execution changed before claim")
            control = self._set(connection, current, LifecycleState.RUNNING, now=now)
            value = ManagedClaim(
                self.executions._get(connection, scope_id, task_id),
                decode_attempt(attempt),
                control.version,
                recovered,
            )
            self._hit("lifecycle.before_claim_commit")
        self._hit("lifecycle.after_claim_commit")
        _event("managed_attempt_started")
        return value

    def _claimed(
        self, connection: Connection, claim: ManagedClaim
    ) -> tuple[ExecutionRecord, LifecycleSnapshot]:
        if type(claim) is not ManagedClaim:
            raise ValueError("A typed managed claim is required")
        execution, current = self._current(
            connection, claim.execution.scope_id, claim.execution.task_id
        )
        self._guard(connection, execution.scope_id, execution.task_id)
        cancelled = current.state == LifecycleState.CANCELLED
        if cancelled:
            row = connection.execute(
                sql.SQL("SELECT cancelled FROM {} WHERE task_id=%s").format(self._table("cases")),
                (execution.task_id,),
            ).fetchone()
            if row is None or row["cancelled"] is not True:
                raise TransitionConflict("Managed cancellation evidence is unavailable")
        if (
            (
                not cancelled
                and (
                    current.state != LifecycleState.RUNNING
                    or current.version != claim.control_version
                )
            )
            or execution.version != claim.execution.version
            or execution.status != ExecutionStatus.RUNNING
        ):
            raise TransitionConflict("Managed attempt no longer owns execution state")
        row = connection.execute(
            sql.SQL(
                "SELECT * FROM {} WHERE attempt_id=%s AND task_id=%s AND status='started'"
            ).format(self._table("execution_attempts")),
            (claim.attempt.attempt_id, execution.task_id),
        ).fetchone()
        if row is None or decode_attempt(row) != claim.attempt:
            raise TransitionConflict("Managed attempt is no longer current")
        return execution, current

    def assert_claim_current(self, claim: ManagedClaim) -> None:
        """Recheck current local authority immediately before readonly provider I/O."""
        with protected_transaction(self.executions) as connection:
            self._claimed(connection, claim)

    def finish_success(self, claim: ManagedClaim, result: InquiryResult) -> LifecycleSnapshot:
        if type(result) is not InquiryResult:
            raise ValueError("A typed inquiry result is required")
        with protected_transaction(self.executions) as connection:
            execution, current = self._claimed(connection, claim)
            if (result.booking_reference, result.new_check_in) != (
                execution.request.booking_reference,
                execution.request.new_check_in,
            ):
                raise ValueError("Inquiry result does not match the accepted request")
            now = instant(self.clock())
            _expect_one(
                connection.execute(
                    sql.SQL(
                        "UPDATE {} SET status='succeeded',finished_at=%s WHERE attempt_id=%s AND status='started'"
                    ).format(self._table("execution_attempts")),
                    (now.isoformat(), claim.attempt.attempt_id),
                )
            )
            _expect_one(
                connection.execute(
                    sql.SQL(
                        "UPDATE {} SET status='succeeded',version=version+1,updated_at=%s,result_json=%s,error_code=NULL WHERE task_id=%s AND version=%s"
                    ).format(self._table("executions")),
                    (
                        now.isoformat(),
                        _canonical(result.payload()),
                        execution.task_id,
                        execution.version,
                    ),
                )
            )
            value = (
                current
                if current.state == LifecycleState.CANCELLED
                else self._set(connection, current, LifecycleState.INQUIRY_COMPLETE, now=now)
            )
            self._hit("lifecycle.before_outcome_commit")
        self._hit("lifecycle.after_outcome_commit")
        _event("managed_attempt_completed", "succeeded")
        return value

    def finish_failure(self, claim: ManagedClaim, failure: FailureClass) -> LifecycleSnapshot:
        if type(failure) is not FailureClass:
            raise ValueError("A typed failure classification is required")
        with protected_transaction(self.executions) as connection:
            execution, current = self._claimed(connection, claim)
            now = instant(self.clock())
            decision = decide_retry(
                failure,
                attempt_no=claim.attempt.attempt_no,
                policy=current.policy,
                now=now,
                deadline=datetime.fromisoformat(current.deadline),
            )
            _expect_one(
                connection.execute(
                    sql.SQL(
                        "UPDATE {} SET status='failed',finished_at=%s,error_code=%s WHERE attempt_id=%s AND status='started'"
                    ).format(self._table("execution_attempts")),
                    (
                        now.isoformat(),
                        FailureCode.DEPENDENCY_UNAVAILABLE.value,
                        claim.attempt.attempt_id,
                    ),
                )
            )
            terminal = (
                current.state == LifecycleState.CANCELLED or decision.disposition.value == "failed"
            )
            _expect_one(
                connection.execute(
                    sql.SQL(
                        "UPDATE {} SET status=%s,version=version+1,updated_at=%s,error_code=%s WHERE task_id=%s AND version=%s"
                    ).format(self._table("executions")),
                    (
                        ExecutionStatus.FAILED.value if terminal else ExecutionStatus.RUNNING.value,
                        now.isoformat(),
                        FailureCode.DEPENDENCY_UNAVAILABLE.value if terminal else None,
                        execution.task_id,
                        execution.version,
                    ),
                )
            )
            value = (
                current
                if current.state == LifecycleState.CANCELLED
                else self._set(
                    connection,
                    current,
                    LifecycleState(decision.disposition.value),
                    now=now,
                    due=decision.next_attempt_at,
                    failure=failure,
                    error=decision.error_code,
                )
            )
            self._hit("lifecycle.before_outcome_commit")
        self._hit("lifecycle.after_outcome_commit")
        _event("managed_attempt_completed", decision.error_code.value)
        return value

    def arm_wait(
        self,
        *,
        actor: AuthenticatedActor,
        task_id: str,
        wait_id: str,
        quote: QuoteSnapshot,
        deadline: datetime,
    ) -> WaitSnapshot:
        wait_id, deadline = _uuid(wait_id), instant(deadline)
        if type(quote) is not QuoteSnapshot or quote.task_id != task_id:
            raise ValueError("Wait quote must belong to this execution")
        with protected_transaction(self.executions) as connection:
            value, created = self.arm_wait_in_transaction(
                connection,
                actor=actor,
                task_id=task_id,
                wait_id=wait_id,
                quote=quote,
                deadline=deadline,
            )
        if created:
            self._hit("lifecycle.after_wait_commit")
            _event("confirmation_wait_armed")
        return value

    def arm_wait_in_transaction(
        self,
        connection: Connection,
        *,
        actor: AuthenticatedActor,
        task_id: str,
        wait_id: str,
        quote: QuoteSnapshot,
        deadline: datetime,
    ) -> tuple[WaitSnapshot, bool]:
        """Arm an exact published quote inside the caller's protected transaction."""
        wait_id, deadline = _uuid(wait_id), instant(deadline)
        if type(quote) is not QuoteSnapshot or quote.task_id != task_id:
            raise ValueError("Wait quote must belong to this execution")
        self.cases.get_in_transaction(connection, actor, task_id)
        execution, current = self._current(connection, actor.scope_id, task_id)
        prior = connection.execute(
            sql.SQL("SELECT * FROM {} WHERE wait_id=%s").format(self._table("execution_waits")),
            (wait_id,),
        ).fetchone()
        if prior is not None:
            value = _wait(prior)
            if (
                value.task_id != task_id
                or value.quote != quote
                or value.deadline != deadline.isoformat()
            ):
                raise IdempotencyConflict("Wait identity already has another expectation")
            return value, False
        self.cases.validate_quote_in_transaction(connection, actor, quote)
        now = instant(self.clock())
        if (
            execution.status != ExecutionStatus.SUCCEEDED
            or current.state != LifecycleState.INQUIRY_COMPLETE
        ):
            raise TransitionConflict("Only a completed inquiry can wait for confirmation")
        if (
            not now
            < deadline
            <= min(
                datetime.fromisoformat(current.deadline),
                datetime.fromisoformat(quote.expires_at),
            )
        ):
            raise ValueError("Wait deadline must fit the original business and quote deadlines")
        rows = connection.execute(
            sql.SQL("SELECT * FROM {} WHERE task_id=%s").format(self._table("execution_waits")),
            (task_id,),
        ).fetchall()
        if len(rows) >= self.maximum_waits:
            raise ExecutionCapacityExceeded("Retained wait capacity is exhausted")
        if any(_wait(row).state == WaitState.PENDING for row in rows):
            raise TransitionConflict("Execution already has a pending wait")
        value_row = connection.execute(
            sql.SQL(
                "INSERT INTO {} (wait_id,task_id,quote_json,deadline,state,created_at,finished_at) VALUES (%s,%s,%s,%s,'pending',%s,NULL) RETURNING *"
            ).format(self._table("execution_waits")),
            (
                wait_id,
                task_id,
                _canonical(quote.payload()),
                deadline.isoformat(),
                now.isoformat(),
            ),
        ).fetchone()
        self._set(connection, current, LifecycleState.WAITING, now=now)
        self._hit("lifecycle.before_wait_commit")
        assert value_row is not None
        value = _wait(value_row)
        return value, True

    def signal(
        self, *, actor: AuthenticatedActor, event_id: str, confirmation: Confirmation
    ) -> SignalReceipt:
        event_id = _identity(event_id)
        if type(confirmation) is not Confirmation:
            raise ValueError("A typed exact confirmation is required")
        task_id = confirmation.quote.task_id
        payload = _canonical(confirmation.payload())
        with protected_transaction(self.executions) as connection:
            self.cases.get_in_transaction(connection, actor, task_id)
            self._current(connection, actor.scope_id, task_id)
            prior = connection.execute(
                sql.SQL("SELECT * FROM {} WHERE scope_id=%s AND event_id=%s").format(
                    self._table("execution_signals")
                ),
                (actor.scope_id, event_id),
            ).fetchone()
            created = prior is None
            if prior is not None:
                if (prior["task_id"], prior["actor_id"], prior["payload_json"]) != (
                    task_id,
                    actor.actor_id,
                    payload,
                ):
                    raise IdempotencyConflict(
                        "Signal identity already has another canonical payload"
                    )
                row = prior
            else:
                count = connection.execute(
                    sql.SQL("SELECT COUNT(*) AS count FROM {} WHERE task_id=%s").format(
                        self._table("execution_signals")
                    ),
                    (task_id,),
                ).fetchone()
                assert count is not None
                if count["count"] >= self.maximum_signals:
                    raise ExecutionCapacityExceeded("Retained signal capacity is exhausted")
                inserted = connection.execute(
                    sql.SQL(
                        "INSERT INTO {} (signal_id,scope_id,task_id,actor_id,event_id,payload_json,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *"
                    ).format(self._table("execution_signals")),
                    (
                        str(uuid4()),
                        actor.scope_id,
                        task_id,
                        actor.actor_id,
                        event_id,
                        payload,
                        instant(self.clock()).isoformat(),
                    ),
                ).fetchone()
                assert inserted is not None
                row = inserted
            consumed = connection.execute(
                sql.SQL("SELECT wait_id FROM {} WHERE signal_id=%s").format(
                    self._table("execution_signal_consumptions")
                ),
                (row["signal_id"],),
            ).fetchone()
            value = SignalReceipt(
                _uuid(row["signal_id"]),
                task_id,
                event_id,
                created,
                None if consumed is None else _uuid(consumed["wait_id"]),
            )
            self._hit("lifecycle.before_signal_commit")
        self._hit("lifecycle.after_signal_commit")
        _event("confirmation_signal_accepted" if created else "confirmation_signal_replayed")
        return value

    def waits(self, *, actor: AuthenticatedActor, task_id: str) -> tuple[WaitSnapshot, ...]:
        with protected_transaction(self.executions) as connection:
            self.cases.get_in_transaction(connection, actor, task_id)
            self._current(connection, actor.scope_id, task_id)
            return tuple(
                _wait(row)
                for row in connection.execute(
                    sql.SQL("SELECT * FROM {} WHERE task_id=%s ORDER BY created_at,wait_id").format(
                        self._table("execution_waits")
                    ),
                    (task_id,),
                ).fetchall()
            )

    def advance(self, *, actor: AuthenticatedActor, task_id: str) -> WaitAdvance:
        with protected_transaction(self.executions) as connection:
            case = self.cases.get_in_transaction(connection, actor, task_id)
            _, current = self._current(connection, actor.scope_id, task_id)
            if self.worker_lease is not None:
                self._guard(connection, actor.scope_id, task_id)
            if case.intent is not None:
                if current.state in {
                    LifecycleState.COMPLETED,
                    LifecycleState.CANCELLED,
                    LifecycleState.FAILED,
                    LifecycleState.UNCERTAIN,
                }:
                    return WaitAdvance(current, case.intent)
                if current.state != LifecycleState.INTENT_COMMITTED:
                    now = instant(self.clock())
                    pending = connection.execute(
                        sql.SQL("SELECT * FROM {} WHERE task_id=%s AND state='pending'").format(
                            self._table("execution_waits")
                        ),
                        (task_id,),
                    ).fetchall()
                    for row in pending:
                        waiting = _wait(row)
                        state = (
                            WaitState.CONSUMED
                            if waiting.quote == case.intent.quote
                            else WaitState.EXPIRED
                        )
                        _expect_one(
                            connection.execute(
                                sql.SQL(
                                    "UPDATE {} SET state=%s,finished_at=%s WHERE wait_id=%s AND state='pending'"
                                ).format(self._table("execution_waits")),
                                (state.value, now.isoformat(), waiting.wait_id),
                            )
                        )
                    current = self._set(
                        connection, current, LifecycleState.INTENT_COMMITTED, now=now
                    )
                return WaitAdvance(current, case.intent)
            if current.state != LifecycleState.WAITING:
                return WaitAdvance(current, None)
            rows = connection.execute(
                sql.SQL(
                    "SELECT * FROM {} WHERE task_id=%s AND state='pending' LIMIT 2 FOR UPDATE"
                ).format(self._table("execution_waits")),
                (task_id,),
            ).fetchall()
            if len(rows) != 1:
                raise InvalidStoredState("Waiting execution lacks one pending wait")
            wait = _wait(rows[0])
            now = instant(self.clock())
            if now >= min(
                datetime.fromisoformat(wait.deadline),
                datetime.fromisoformat(current.deadline),
                datetime.fromisoformat(wait.quote.expires_at),
            ):
                _expect_one(
                    connection.execute(
                        sql.SQL(
                            "UPDATE {} SET state='expired',finished_at=%s WHERE wait_id=%s AND state='pending'"
                        ).format(self._table("execution_waits")),
                        (now.isoformat(), wait.wait_id),
                    )
                )
                value = WaitAdvance(
                    self._set(
                        connection,
                        current,
                        LifecycleState.FAILED,
                        now=now,
                        error=RetryError.DEADLINE_EXPIRED,
                    ),
                    None,
                )
            else:
                signals = connection.execute(
                    sql.SQL(
                        "SELECT s.* FROM {} s LEFT JOIN {} c ON c.signal_id=s.signal_id WHERE s.task_id=%s AND s.scope_id=%s AND s.actor_id=%s AND c.signal_id IS NULL ORDER BY s.created_at,s.signal_id"
                    ).format(
                        self._table("execution_signals"),
                        self._table("execution_signal_consumptions"),
                    ),
                    (task_id, actor.scope_id, actor.actor_id),
                ).fetchall()
                selected = None
                for row in signals:
                    try:
                        candidate = parse_confirmation(json.loads(row["payload_json"]))
                        if (
                            candidate.quote.task_id != task_id
                            or _canonical(candidate.payload()) != row["payload_json"]
                        ):
                            raise ValueError("Invalid signal payload")
                    except (
                        ValueError,
                        TypeError,
                        KeyError,
                        AttributeError,
                        InvalidConfirmation,
                    ) as error:
                        raise InvalidStoredState(
                            "Execution signal contains invalid stored state"
                        ) from error
                    if candidate.quote == wait.quote:
                        selected = row, candidate
                        break
                if selected is None:
                    return WaitAdvance(current, None)
                row, confirmation = selected
                intent = self.cases.commit_intent_in_transaction(
                    connection, actor, confirmation, "signal:" + _uuid(row["signal_id"])
                )
                connection.execute(
                    sql.SQL(
                        "INSERT INTO {} (signal_id,wait_id,task_id,created_at) VALUES (%s,%s,%s,%s)"
                    ).format(self._table("execution_signal_consumptions")),
                    (row["signal_id"], wait.wait_id, task_id, now.isoformat()),
                )
                # Case authority atomically closes the matching wait and updates
                # continuation state in the same transaction as intent creation.
                # Refresh its version; never overwrite it using our old snapshot.
                value = WaitAdvance(self._current(connection, actor.scope_id, task_id)[1], intent)
            self._hit("lifecycle.before_advance_commit")
        self._hit("lifecycle.after_advance_commit")
        if value.intent is not None:
            _event("intent_committed")
        _event("confirmation_wait_advanced", "deadline_expired" if value.intent is None else "ok")
        return value
