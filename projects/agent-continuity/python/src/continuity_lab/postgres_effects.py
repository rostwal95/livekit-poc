"""Single-worker mutation, cancellation and completion authority on PostgreSQL v3.

All state changes use the existing admission/case transaction. Generation is an
attempt-owner token, not a lease epoch or generic row revision. Supplier and sink
calls occur in their worker adapters after this transaction has closed.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import psycopg
from psycopg import sql

from .authorization import AuthenticatedActor
from .case_models import (
    ActionIntent,
    CaseSnapshot,
    canonical,
    identity,
    integer,
    require_mutation_quote,
    utc_instant,
    uuid_identity,
)
from .effect_models import (
    BusinessOutcome,
    CancellationDisposition,
    CancellationReceipt,
    CancelReason,
    CompletionEvent,
    DeliveryClaim,
    DeliveryPolicy,
    DeliverySnapshot,
    DeliveryState,
    EffectClaim,
    EffectFailure,
    EffectSnapshot,
    EffectState,
    MutationResult,
    parse_business_outcome,
    parse_completion_event,
    parse_delivery_policy,
    parse_mutation_result,
    require_result_binding,
)
from .execution_models import (
    ExecutionCapacityExceeded,
    ExecutionNotFound,
    InvalidStoredState,
    TransitionConflict,
    UnsupportedOperation,
)
from .lease_models import LeaseGrant
from .models import IdempotencyConflict
from .postgres_case import PostgresCaseAuthority
from .postgres_leases import require_worker_lease
from .postgres_store import PostgresExecutionStore
from .postgres_unit_of_work import protected_transaction

Connection = psycopg.Connection[dict[str, Any]]
LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
# Schema v5 paces known dependency outages: 1 s doubling to 30 s, never past the deadline.
RETRY_INITIAL_SECONDS, RETRY_MAX_SECONDS = 1, 30
_TERMINAL = frozenset(
    {
        EffectState.SUCCEEDED,
        EffectState.FAILED,
        EffectState.UNCERTAIN,
        EffectState.CANCELLED,
    }
)


def _event(event: str, code: str = "ok") -> None:
    try:
        LOGGER.info(event, extra={"event": event, "code": code})
    except Exception:  # noqa: BLE001 - explicit producer-only telemetry containment
        return


def _one(cursor: psycopg.Cursor[dict[str, Any]]) -> None:
    if cursor.rowcount != 1:
        raise TransitionConflict("Protected effect state changed before this operation")


class PostgresEffects:
    """Retain mutation/cancellation/outbox evidence under original task identity."""

    def __init__(
        self,
        executions: PostgresExecutionStore,
        *,
        cases: PostgresCaseAuthority | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        failpoint: Callable[[str], None] | None = None,
        maximum_attempts: int = 8,
        maximum_cancellations: int = 128,
        delivery_policy: DeliveryPolicy | None = None,
        worker_lease: LeaseGrant | None = None,
    ) -> None:
        if type(maximum_attempts) is not int or not 1 <= maximum_attempts <= 100:
            raise ValueError("Mutation attempt budget must be between 1 and 100")
        if type(maximum_cancellations) is not int or not 1 <= maximum_cancellations <= 10000:
            raise ValueError("Cancellation retention bound must be positive and finite")
        if delivery_policy is None:
            delivery_policy = DeliveryPolicy()
        if type(delivery_policy) is not DeliveryPolicy:
            raise ValueError("A typed delivery policy is required")
        if worker_lease is not None and type(worker_lease) is not LeaseGrant:
            raise ValueError("A typed explicit worker lease is required")
        self.worker_lease = worker_lease
        self.executions, self.clock, self.failpoint = executions, clock, failpoint
        self.cases = cases or PostgresCaseAuthority(executions, clock=clock)
        self.maximum_attempts, self.maximum_cancellations = (
            maximum_attempts,
            maximum_cancellations,
        )
        self.delivery_policy = delivery_policy

    def worker_slot(self) -> AbstractContextManager[None]:
        """Legacy session coordination; v4 authority is the explicit DB lease."""
        return self.executions.worker_slot() if self.worker_lease is None else nullcontext()

    def _guard(self, connection: Connection, scope_id: str, task_id: str) -> None:
        require_worker_lease(
            connection, self.executions, self.worker_lease, scope_id=scope_id, task_id=task_id
        )

    def _table(self, name: str) -> sql.Identifier:
        return sql.Identifier(self.executions.settings.schema, name)

    def _now(self) -> datetime:
        value = self.clock()
        if type(value) is not datetime or value.utcoffset() is None:
            raise ValueError("Effect clock must return an aware instant")
        return value.astimezone(UTC)

    def _hit(self, point: str) -> None:
        if self.failpoint is not None:
            self.failpoint(point)

    @contextmanager
    def _transaction(self) -> Iterator[Connection]:
        with protected_transaction(self.executions) as connection:
            row = connection.execute(
                sql.SQL("SELECT version FROM {} WHERE singleton").format(
                    self._table("schema_metadata")
                )
            ).fetchone()
            if row is None or row["version"] not in {3, 4, 5}:
                raise UnsupportedOperation("Mutation and completion require schema v3 or later")
            yield connection

    def _paced(self, connection: Connection) -> bool:
        """Schema v5 persists when a dependency-unavailable retry becomes due."""
        row = connection.execute(
            sql.SQL("SELECT version FROM {} WHERE singleton").format(self._table("schema_metadata"))
        ).fetchone()
        return row is not None and row["version"] >= 5

    def _worker_case(self, connection: Connection, scope_id: str, task_id: str) -> CaseSnapshot:
        self.executions._get(connection, identity(scope_id), identity(task_id))
        row = connection.execute(
            sql.SQL("SELECT actor_id FROM {} WHERE task_id=%s AND scope_id=%s").format(
                self._table("cases")
            ),
            (task_id, scope_id),
        ).fetchone()
        if row is None:
            raise ExecutionNotFound("Execution is unavailable")
        return self.cases.get_in_transaction(
            connection, AuthenticatedActor(row["actor_id"], scope_id), task_id
        )

    def _effect_row(self, connection: Connection, task_id: str) -> dict[str, Any] | None:
        return connection.execute(
            sql.SQL("SELECT * FROM {} WHERE task_id=%s FOR UPDATE").format(
                self._table("mutation_effects")
            ),
            (task_id,),
        ).fetchone()

    def _snapshot(self, row: dict[str, Any], case: CaseSnapshot) -> EffectSnapshot:
        try:
            intent = case.intent
            if (
                intent is None
                or row["intent_id"] != intent.intent_id
                or row["task_id"] != case.task_id
            ):
                raise ValueError("Mutation intent binding is invalid")
            state = EffectState(row["state"])
            generation, attempt_no, dispatch_count = (
                integer(row["generation"]),
                integer(row["attempt_no"], maximum=100),
                integer(row["dispatch_count"], maximum=100),
            )
            result = (
                None
                if row["result_json"] is None
                else parse_mutation_result(json.loads(row["result_json"]))
            )
            if result is not None:
                require_result_binding(result, intent)
                if canonical(result.payload()) != row["result_json"]:
                    raise ValueError("Mutation evidence is not canonical")
            error = None if row["error_code"] is None else EffectFailure(row["error_code"])
            if (state == EffectState.SUCCEEDED) != (result is not None):
                raise ValueError("Mutation result disposition is inconsistent")
            if state in {EffectState.FAILED, EffectState.UNCERTAIN} and error is None:
                raise ValueError("Failed mutation lacks a safe error")
            if (dispatch_count == 0) != (row["dispatched_at"] is None):
                raise ValueError("Mutation dispatch evidence is inconsistent")
            if row["dispatched_at"] is not None:
                utc_instant(row["dispatched_at"])
            if row["active_attempt_id"] is not None:
                uuid_identity(row["active_attempt_id"])
            if (attempt_no == 0) != (row["active_attempt_id"] is None):
                raise ValueError("Mutation attempt pointer is inconsistent")
            if dispatch_count > attempt_no or (
                state in {EffectState.CLAIMED, EffectState.DISPATCHED} and attempt_no == 0
            ):
                raise ValueError("Mutation attempt evidence is inconsistent")
            return EffectSnapshot(
                intent,
                state,
                generation,
                attempt_no,
                dispatch_count,
                result,
                error,
                utc_instant(row["updated_at"]).isoformat(),
            )
        except (
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            OverflowError,
        ) as error:
            raise InvalidStoredState("Mutation contains invalid stored evidence") from error

    def _completion(self, connection: Connection, case: CaseSnapshot) -> CompletionEvent | None:
        outcome_row = connection.execute(
            sql.SQL("SELECT * FROM {} WHERE task_id=%s").format(self._table("business_outcomes")),
            (case.task_id,),
        ).fetchone()
        rows = connection.execute(
            sql.SQL("SELECT * FROM {} WHERE task_id=%s LIMIT 2").format(
                self._table("completion_events")
            ),
            (case.task_id,),
        ).fetchall()
        if outcome_row is None:
            if rows:
                raise InvalidStoredState("Completion event lacks its business outcome")
            return None
        try:
            outcome = parse_business_outcome(json.loads(outcome_row["payload_json"]))
            if (
                canonical(outcome.payload()) != outcome_row["payload_json"]
                or outcome.created_at != outcome_row["created_at"]
                or (outcome.task_id, outcome.case_id, outcome.scope_id)
                != (case.task_id, case.case_id, case.scope_id)
            ):
                raise ValueError("Business outcome binding is invalid")
            if case.intent is None:
                if outcome.intent_id is not None:
                    raise ValueError("Uncommitted case has an effect outcome")
            elif (outcome.intent_id, outcome.effect_id) != (
                case.intent.intent_id,
                case.intent.effect_id,
            ):
                raise ValueError("Business outcome intent binding is invalid")
            if outcome.result is not None and case.intent is not None:
                require_result_binding(outcome.result, case.intent)
            if len(rows) != 1:
                raise ValueError("Business outcome must have one completion event")
            event = parse_completion_event(json.loads(rows[0]["payload_json"]))
            if (
                event.canonical() != rows[0]["payload_json"]
                or event.event_id != rows[0]["event_id"]
                or event.created_at != rows[0]["created_at"]
                or event.outcome != outcome
            ):
                raise ValueError("Completion event binding is invalid")
            effect_row = connection.execute(
                sql.SQL("SELECT * FROM {} WHERE task_id=%s").format(
                    self._table("mutation_effects")
                ),
                (case.task_id,),
            ).fetchone()
            if case.intent is not None:
                if effect_row is None:
                    raise ValueError("Committed outcome lacks its effect state")
                effect = self._snapshot(effect_row, case)
                if (effect.state, effect.result, effect.error_code) != (
                    outcome.state,
                    outcome.result,
                    outcome.error_code,
                ):
                    raise ValueError("Effect and immutable outcome disagree")
            elif effect_row is not None:
                raise ValueError("Uncommitted case has effect state")
            return event
        except (
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            OverflowError,
        ) as error:
            raise InvalidStoredState("Completion contains invalid stored evidence") from error

    def _insert_completion(
        self,
        connection: Connection,
        case: CaseSnapshot,
        state: EffectState,
        result: MutationResult | None,
        error: EffectFailure | None,
        cancellation: CancellationDisposition,
        stamp: str,
    ) -> CompletionEvent:
        previous = self._completion(connection, case)
        intent = case.intent
        outcome = BusinessOutcome(
            case.task_id,
            case.case_id,
            case.scope_id,
            None if intent is None else intent.intent_id,
            None if intent is None else intent.effect_id,
            state,
            result,
            error,
            cancellation,
            stamp,
        )
        if previous is not None:
            if previous.outcome != outcome:
                raise TransitionConflict("Business outcome is already final")
            return previous
        event = CompletionEvent(str(uuid4()), outcome, stamp)
        connection.execute(
            sql.SQL("INSERT INTO {} (task_id,payload_json,created_at) VALUES (%s,%s,%s)").format(
                self._table("business_outcomes")
            ),
            (case.task_id, canonical(outcome.payload()), stamp),
        )
        connection.execute(
            sql.SQL(
                "INSERT INTO {} (event_id,task_id,payload_json,created_at) VALUES (%s,%s,%s,%s)"
            ).format(self._table("completion_events")),
            (event.event_id, case.task_id, event.canonical(), stamp),
        )
        connection.execute(
            sql.SQL(
                "INSERT INTO {} (event_id,state,generation,attempts,policy_json,next_attempt_at,error_code,updated_at) VALUES (%s,'pending',0,0,%s,%s,NULL,%s)"
            ).format(self._table("completion_deliveries")),
            (event.event_id, canonical(self.delivery_policy.payload()), stamp, stamp),
        )
        control = connection.execute(
            sql.SQL("SELECT version FROM {} WHERE task_id=%s FOR UPDATE").format(
                self._table("execution_controls")
            ),
            (case.task_id,),
        ).fetchone()
        if control is not None:
            control_state = (
                "cancelled"
                if state == EffectState.CANCELLED
                else "completed"
                if state == EffectState.SUCCEEDED
                else "uncertain"
                if state == EffectState.UNCERTAIN
                else "failed"
            )
            control_error = (
                None
                if error is None
                else {
                    EffectFailure.SUPPLIER_REJECTED: "permanent_failure",
                    EffectFailure.ATTEMPTS_EXHAUSTED: "retry_exhausted",
                }.get(error, error.value)
            )
            _one(
                connection.execute(
                    sql.SQL(
                        "UPDATE {} SET state=%s,next_attempt_at=NULL,error_code=%s,version=version+1,updated_at=%s WHERE task_id=%s AND version=%s"
                    ).format(self._table("execution_controls")),
                    (
                        control_state,
                        control_error,
                        stamp,
                        case.task_id,
                        control["version"],
                    ),
                )
            )
        self._hit("effects.after_completion_rows")
        return event

    def _deadline(self, connection: Connection, case: CaseSnapshot) -> datetime:
        control = connection.execute(
            sql.SQL("SELECT * FROM {} WHERE task_id=%s FOR UPDATE").format(
                self._table("execution_controls")
            ),
            (case.task_id,),
        ).fetchone()
        if control is None:
            raise UnsupportedOperation("Committed mutation requires its original managed deadline")
        if control["state"] != "intent_committed":
            raise InvalidStoredState("Mutation continuation is not at its committed boundary")
        return utc_instant(control["deadline"])

    def _insert_effect(
        self, connection: Connection, case: CaseSnapshot, stamp: str
    ) -> dict[str, Any]:
        if case.intent is None:
            raise UnsupportedOperation("A committed mutation intent is required")
        connection.execute(
            sql.SQL(
                "INSERT INTO {} (intent_id,task_id,state,generation,attempt_no,dispatch_count,active_attempt_id,result_json,error_code,dispatched_at,updated_at) VALUES (%s,%s,'pending',0,0,0,NULL,NULL,NULL,NULL,%s)"
            ).format(self._table("mutation_effects")),
            (case.intent.intent_id, case.task_id, stamp),
        )
        row = self._effect_row(connection, case.task_id)
        assert row is not None
        return row

    def intent(self, *, scope_id: str, task_id: str) -> ActionIntent:
        """Read the immutable intended target before consuming a worker attempt."""
        with self._transaction() as connection:
            case = self._worker_case(connection, scope_id, task_id)
            if case.intent is None:
                raise UnsupportedOperation("A committed mutation intent is required")
            require_mutation_quote(case.intent)
            return case.intent

    def get(self, *, scope_id: str, task_id: str) -> EffectSnapshot | None:
        with self._transaction() as connection:
            case = self._worker_case(connection, scope_id, task_id)
            row = self._effect_row(connection, task_id)
            if row is None:
                return None
            value = self._snapshot(row, case)
            completion = self._completion(connection, case)
            if (value.state in _TERMINAL) != (completion is not None):
                raise InvalidStoredState("Mutation outcome and completion do not agree")
            return value

    def claim(self, *, scope_id: str, task_id: str) -> EffectClaim | None:
        with self._transaction() as connection:
            case = self._worker_case(connection, scope_id, task_id)
            self._guard(connection, scope_id, task_id)
            if self._completion(connection, case) is not None:
                return None
            intent = case.intent
            if intent is None:
                raise UnsupportedOperation("A committed exact mutation intent is required")
            quote = require_mutation_quote(intent)
            if quote.case_id != case.case_id:
                raise InvalidStoredState("Mutation proposal belongs to another case")
            deadline = self._deadline(connection, case)
            now = self._now()
            stamp = now.isoformat()
            row = self._effect_row(connection, task_id) or self._insert_effect(
                connection, case, stamp
            )
            value = self._snapshot(row, case)
            if value.state in _TERMINAL:
                raise InvalidStoredState("Terminal mutation lacks its completion event")
            possible = value.dispatch_count > 0
            if case.cancelled and not possible:
                self._finish_row(
                    connection,
                    case,
                    row,
                    EffectState.CANCELLED,
                    None,
                    None,
                    CancellationDisposition.BEFORE_DISPATCH,
                    stamp,
                )
                return None
            if now >= deadline and not possible:
                self._finish_row(
                    connection,
                    case,
                    row,
                    EffectState.FAILED,
                    None,
                    EffectFailure.DEADLINE_EXPIRED,
                    CancellationDisposition.NOT_REQUESTED,
                    stamp,
                )
                return None
            if value.attempt_no >= self.maximum_attempts:
                self._finish_row(
                    connection,
                    case,
                    row,
                    EffectState.UNCERTAIN if possible else EffectState.FAILED,
                    None,
                    EffectFailure.ATTEMPTS_EXHAUSTED,
                    CancellationDisposition.REQUESTED
                    if case.cancelled
                    else CancellationDisposition.NOT_REQUESTED,
                    stamp,
                )
                return None
            if (
                value.state == EffectState.PENDING
                and row.get("next_attempt_at") is not None
                and now < row["next_attempt_at"]
            ):
                return None
            recovered = value.state in {EffectState.CLAIMED, EffectState.DISPATCHED}
            if recovered:
                if row["active_attempt_id"] is None:
                    raise InvalidStoredState("Claimed mutation lacks a current attempt")
                _one(
                    connection.execute(
                        sql.SQL(
                            "UPDATE {} SET state='interrupted',finished_at=%s,error_code=NULL WHERE attempt_id=%s AND intent_id=%s AND attempt_no=%s AND state='started'"
                        ).format(self._table("mutation_attempts")),
                        (
                            stamp,
                            row["active_attempt_id"],
                            intent.intent_id,
                            value.attempt_no,
                        ),
                    )
                )
            attempt_id = str(uuid4())
            number = value.attempt_no + 1
            generation = value.generation + 1
            connection.execute(
                sql.SQL(
                    "INSERT INTO {} (attempt_id,intent_id,attempt_no,state,started_at,finished_at,error_code) VALUES (%s,%s,%s,'started',%s,NULL,NULL)"
                ).format(self._table("mutation_attempts")),
                (attempt_id, intent.intent_id, number, stamp),
            )
            _one(
                connection.execute(
                    sql.SQL(
                        "UPDATE {} SET state='claimed',generation=%s,attempt_no=%s,active_attempt_id=%s,error_code=NULL,updated_at=%s WHERE intent_id=%s AND generation=%s"
                    ).format(self._table("mutation_effects")),
                    (
                        generation,
                        number,
                        attempt_id,
                        stamp,
                        intent.intent_id,
                        value.generation,
                    ),
                )
            )
            claim = EffectClaim(intent, attempt_id, number, generation, recovered, possible)
            self._hit("effects.before_claim_commit")
        self._hit("effects.after_claim_commit")
        _event("mutation_claimed")
        return claim

    def _claimed(
        self, connection: Connection, claim: EffectClaim
    ) -> tuple[CaseSnapshot, dict[str, Any]]:
        if type(claim) is not EffectClaim:
            raise ValueError("A typed mutation claim is required")
        case = self._worker_case(connection, claim.intent.scope_id, claim.intent.task_id)
        row = self._effect_row(connection, case.task_id)
        self._guard(connection, case.scope_id, case.task_id)
        if row is None or case.intent != claim.intent:
            raise TransitionConflict("Mutation claim no longer owns its intent")
        value = self._snapshot(row, case)
        if (
            value.generation != claim.generation
            or row["active_attempt_id"] != claim.attempt_id
            or value.attempt_no != claim.attempt_no
            or value.state not in {EffectState.CLAIMED, EffectState.DISPATCHED}
        ):
            raise TransitionConflict("Mutation claim no longer owns this attempt")
        attempt = connection.execute(
            sql.SQL("SELECT * FROM {} WHERE attempt_id=%s AND intent_id=%s").format(
                self._table("mutation_attempts")
            ),
            (claim.attempt_id, claim.intent.intent_id),
        ).fetchone()
        if (
            attempt is None
            or attempt["state"] != "started"
            or attempt["attempt_no"] != claim.attempt_no
        ):
            raise TransitionConflict("Mutation attempt is no longer active")
        return case, row

    def prepare_dispatch(self, claim: EffectClaim, *, absence_confirmed: bool) -> bool:
        if type(absence_confirmed) is not bool:
            raise ValueError("Dispatch absence evidence must be explicit")
        with self._transaction() as connection:
            case, row = self._claimed(connection, claim)
            if row["state"] != EffectState.CLAIMED:
                raise TransitionConflict("This attempt already reserved dispatch")
            now = self._now()
            stamp = now.isoformat()
            # A prior reservation may still land after a lookup miss, so it cannot prove
            # prevention or a definite deadline failure.
            if not absence_confirmed or (
                row["dispatch_count"] > 0
                and (case.cancelled or now >= self._deadline(connection, case))
            ):
                self._finish_row(
                    connection,
                    case,
                    row,
                    EffectState.UNCERTAIN,
                    None,
                    EffectFailure.AMBIGUOUS_OUTCOME,
                    CancellationDisposition.REQUESTED
                    if case.cancelled
                    else CancellationDisposition.NOT_REQUESTED,
                    stamp,
                )
                return False
            if case.cancelled:
                self._finish_row(
                    connection,
                    case,
                    row,
                    EffectState.CANCELLED,
                    None,
                    None,
                    CancellationDisposition.BEFORE_DISPATCH,
                    stamp,
                )
                return False
            if now >= self._deadline(connection, case):
                self._finish_row(
                    connection,
                    case,
                    row,
                    EffectState.FAILED,
                    None,
                    EffectFailure.DEADLINE_EXPIRED,
                    CancellationDisposition.NOT_REQUESTED,
                    stamp,
                )
                return False
            _one(
                connection.execute(
                    sql.SQL(
                        "UPDATE {} SET state='dispatched',dispatch_count=dispatch_count+1,dispatched_at=COALESCE(dispatched_at,%s),updated_at=%s WHERE intent_id=%s AND state='claimed' AND generation=%s AND active_attempt_id=%s"
                    ).format(self._table("mutation_effects")),
                    (
                        stamp,
                        stamp,
                        claim.intent.intent_id,
                        claim.generation,
                        claim.attempt_id,
                    ),
                )
            )
            self._hit("effects.before_dispatch_commit")
        self._hit("effects.after_dispatch_commit")
        _event("mutation_dispatch_reserved")
        return True

    def _finish_row(
        self,
        connection: Connection,
        case: CaseSnapshot,
        row: dict[str, Any],
        state: EffectState,
        result: MutationResult | None,
        error: EffectFailure | None,
        cancellation: CancellationDisposition,
        stamp: str,
    ) -> EffectSnapshot:
        value = self._snapshot(row, case)
        if result is not None:
            require_result_binding(result, value.intent)
        if row["active_attempt_id"] is not None:
            active = connection.execute(
                sql.SQL("SELECT * FROM {} WHERE attempt_id=%s").format(
                    self._table("mutation_attempts")
                ),
                (row["active_attempt_id"],),
            ).fetchone()
            if active is None or (active["intent_id"], active["attempt_no"]) != (
                value.intent.intent_id,
                value.attempt_no,
            ):
                raise InvalidStoredState("Mutation attempt belongs to different evidence")
            if active["state"] == "started":
                _one(
                    connection.execute(
                        sql.SQL(
                            "UPDATE {} SET state=%s,finished_at=%s,error_code=%s WHERE attempt_id=%s AND intent_id=%s AND attempt_no=%s AND state='started'"
                        ).format(self._table("mutation_attempts")),
                        (
                            state.value,
                            stamp,
                            None if error is None else error.value,
                            row["active_attempt_id"],
                            value.intent.intent_id,
                            value.attempt_no,
                        ),
                    )
                )
        _one(
            connection.execute(
                sql.SQL(
                    "UPDATE {} SET state=%s,generation=generation+1,result_json=%s,error_code=%s,updated_at=%s WHERE intent_id=%s AND generation=%s"
                ).format(self._table("mutation_effects")),
                (
                    state.value,
                    None if result is None else canonical(result.payload()),
                    None if error is None else error.value,
                    stamp,
                    value.intent.intent_id,
                    value.generation,
                ),
            )
        )
        self._insert_completion(connection, case, state, result, error, cancellation, stamp)
        finished = self._effect_row(connection, case.task_id)
        assert finished is not None
        return self._snapshot(finished, case)

    def finish_success(self, claim: EffectClaim, result: MutationResult) -> EffectSnapshot:
        require_result_binding(result, claim.intent)
        with self._transaction() as connection:
            case, row = self._claimed(connection, claim)
            # A successful reliable lookup is truth even after cancellation/expiry.
            value = self._finish_row(
                connection,
                case,
                row,
                EffectState.SUCCEEDED,
                result,
                None,
                CancellationDisposition.REQUESTED
                if case.cancelled
                else CancellationDisposition.NOT_REQUESTED,
                self._now().isoformat(),
            )
            self._hit("effects.before_finish_commit")
        self._hit("effects.after_finish_commit")
        _event("mutation_finished", "succeeded")
        _event("completion_committed")
        return value

    def finish_failure(self, claim: EffectClaim, code: EffectFailure) -> EffectSnapshot:
        if type(code) is not EffectFailure:
            raise ValueError("A safe typed mutation failure is required")
        with self._transaction() as connection:
            case, row = self._claimed(connection, claim)
            now = self._now()
            stamp = now.isoformat()
            if (
                code == EffectFailure.DEPENDENCY_UNAVAILABLE
                and row["state"] == EffectState.CLAIMED
                and row["dispatch_count"] == 0
                and now < self._deadline(connection, case)
                and row["attempt_no"] < self.maximum_attempts
                and not case.cancelled
            ):
                _one(
                    connection.execute(
                        sql.SQL(
                            "UPDATE {} SET state='failed',finished_at=%s,error_code=%s WHERE attempt_id=%s AND state='started'"
                        ).format(self._table("mutation_attempts")),
                        (stamp, code.value, claim.attempt_id),
                    )
                )
                if self._paced(connection):
                    delay = min(
                        RETRY_INITIAL_SECONDS * 2 ** (row["attempt_no"] - 1), RETRY_MAX_SECONDS
                    )
                    due = min(now + timedelta(seconds=delay), self._deadline(connection, case))
                    _one(
                        connection.execute(
                            sql.SQL(
                                "UPDATE {} SET state='pending',generation=generation+1,error_code=%s,updated_at=%s,next_attempt_at=%s WHERE intent_id=%s AND generation=%s"
                            ).format(self._table("mutation_effects")),
                            (code.value, stamp, due, claim.intent.intent_id, claim.generation),
                        )
                    )
                else:
                    _one(
                        connection.execute(
                            sql.SQL(
                                "UPDATE {} SET state='pending',generation=generation+1,error_code=%s,updated_at=%s WHERE intent_id=%s AND generation=%s"
                            ).format(self._table("mutation_effects")),
                            (code.value, stamp, claim.intent.intent_id, claim.generation),
                        )
                    )
                fresh = self._effect_row(connection, case.task_id)
                assert fresh is not None
                value = self._snapshot(fresh, case)
            else:
                if code == EffectFailure.DEPENDENCY_UNAVAILABLE:
                    code = (
                        EffectFailure.AMBIGUOUS_OUTCOME
                        if row["dispatch_count"] > 0
                        else EffectFailure.DEADLINE_EXPIRED
                        if now >= self._deadline(connection, case)
                        else EffectFailure.ATTEMPTS_EXHAUSTED
                    )
                state = (
                    EffectState.UNCERTAIN
                    if code == EffectFailure.AMBIGUOUS_OUTCOME
                    else EffectState.FAILED
                )
                if case.cancelled and row["dispatch_count"] == 0:
                    state = EffectState.CANCELLED
                    code_value = None
                    cancellation = CancellationDisposition.BEFORE_DISPATCH
                else:
                    code_value = code
                    cancellation = (
                        CancellationDisposition.REQUESTED
                        if case.cancelled
                        else CancellationDisposition.NOT_REQUESTED
                    )
                value = self._finish_row(
                    connection, case, row, state, None, code_value, cancellation, stamp
                )
            self._hit("effects.before_finish_commit")
        self._hit("effects.after_finish_commit")
        _event("mutation_finished", code.value)
        return value

    def finish_uncertain(
        self, claim: EffectClaim, code: EffectFailure = EffectFailure.AMBIGUOUS_OUTCOME
    ) -> EffectSnapshot:
        if code not in {
            EffectFailure.AMBIGUOUS_OUTCOME,
            EffectFailure.ATTEMPTS_EXHAUSTED,
        }:
            raise ValueError("Uncertainty needs a safe ambiguous-outcome classification")
        with self._transaction() as connection:
            case, row = self._claimed(connection, claim)
            value = self._finish_row(
                connection,
                case,
                row,
                EffectState.UNCERTAIN,
                None,
                code,
                CancellationDisposition.REQUESTED
                if case.cancelled
                else CancellationDisposition.NOT_REQUESTED,
                self._now().isoformat(),
            )
            self._hit("effects.before_finish_commit")
        self._hit("effects.after_finish_commit")
        _event("mutation_finished", code.value)
        _event("completion_committed")
        return value

    def _cancel_receipt(
        self, row: dict[str, Any], case: CaseSnapshot, created: bool
    ) -> CancellationReceipt:
        try:
            payload = json.loads(row["payload_json"])
            expected = {
                "schema_version": 1,
                "task_id": case.task_id,
                "case_id": case.case_id,
                "scope_id": case.scope_id,
                "actor_id": case.actor_id,
                "reason": CancelReason.USER_REQUESTED.value,
            }
            if (
                payload != expected
                or canonical(payload) != row["payload_json"]
                or (row["task_id"], row["scope_id"], row["actor_id"])
                != (case.task_id, case.scope_id, case.actor_id)
            ):
                raise ValueError("Cancellation receipt binding is invalid")
            disposition = CancellationDisposition(row["disposition"])
            if disposition == CancellationDisposition.NOT_REQUESTED:
                raise ValueError("A cancellation command cannot be unrequested")
            return CancellationReceipt(
                uuid_identity(row["cancellation_id"]),
                case.task_id,
                case.case_id,
                identity(row["command_id"]),
                CancelReason.USER_REQUESTED,
                disposition,
                utc_instant(row["created_at"]).isoformat(),
                created,
            )
        except (
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            OverflowError,
        ) as error:
            raise InvalidStoredState("Cancellation contains invalid stored evidence") from error

    def cancel(
        self,
        *,
        actor: AuthenticatedActor,
        task_id: str,
        command_id: str,
        reason: CancelReason = CancelReason.USER_REQUESTED,
    ) -> CancellationReceipt:
        if type(reason) is not CancelReason:
            raise ValueError("A typed cancellation reason is required")
        command_id = identity(command_id)
        with self._transaction() as connection:
            case = self.cases.get_in_transaction(connection, actor, task_id)
            prior = connection.execute(
                sql.SQL("SELECT * FROM {} WHERE scope_id=%s AND command_id=%s").format(
                    self._table("cancellation_commands")
                ),
                (actor.scope_id, command_id),
            ).fetchone()
            if prior is not None:
                if (prior["task_id"], prior["actor_id"]) != (
                    case.task_id,
                    actor.actor_id,
                ):
                    raise IdempotencyConflict(
                        "Cancellation command already has different semantics"
                    )
                return self._cancel_receipt(prior, case, False)
            count = connection.execute(
                sql.SQL("SELECT COUNT(*) AS n FROM {} WHERE task_id=%s").format(
                    self._table("cancellation_commands")
                ),
                (task_id,),
            ).fetchone()
            if count is None or count["n"] >= self.maximum_cancellations:
                raise ExecutionCapacityExceeded(
                    "Cancellation receipt retention capacity is exhausted"
                )
            # Case lock precedes control/effect/waits, shared with confirmation.
            connection.execute(
                sql.SQL("SELECT version FROM {} WHERE task_id=%s FOR UPDATE").format(
                    self._table("execution_controls")
                ),
                (task_id,),
            ).fetchone()
            row = self._effect_row(connection, task_id)
            event = self._completion(connection, case)
            value = None if row is None else self._snapshot(row, case)
            if value is not None and value.state in _TERMINAL and event is None:
                raise InvalidStoredState("Terminal mutation lacks its completion")
            disposition = (
                CancellationDisposition.ALREADY_TERMINAL
                if event is not None
                else CancellationDisposition.BEFORE_COMMIT
                if case.intent is None
                else CancellationDisposition.BEFORE_DISPATCH
                if value is None or value.dispatch_count == 0
                else CancellationDisposition.REQUESTED
            )
            stamp = self._now().isoformat()
            cancel_id = str(uuid4())
            payload = {
                "schema_version": 1,
                "task_id": case.task_id,
                "case_id": case.case_id,
                "scope_id": case.scope_id,
                "actor_id": actor.actor_id,
                "reason": reason.value,
            }
            connection.execute(
                sql.SQL(
                    "INSERT INTO {} (cancellation_id,scope_id,task_id,actor_id,command_id,payload_json,disposition,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)"
                ).format(self._table("cancellation_commands")),
                (
                    cancel_id,
                    case.scope_id,
                    task_id,
                    actor.actor_id,
                    command_id,
                    canonical(payload),
                    disposition.value,
                    stamp,
                ),
            )
            _one(
                connection.execute(
                    sql.SQL(
                        "UPDATE {} SET cancelled=TRUE,updated_at=%s WHERE task_id=%s AND scope_id=%s AND actor_id=%s"
                    ).format(self._table("cases")),
                    (stamp, task_id, actor.scope_id, actor.actor_id),
                )
            )
            if disposition in {
                CancellationDisposition.BEFORE_COMMIT,
                CancellationDisposition.BEFORE_DISPATCH,
            }:
                connection.execute(
                    sql.SQL(
                        "UPDATE {} SET state='expired',finished_at=%s WHERE task_id=%s AND state='pending'"
                    ).format(self._table("execution_waits")),
                    (stamp, task_id),
                )
                if case.intent is not None:
                    row = row or self._insert_effect(connection, case, stamp)
                    self._finish_row(
                        connection,
                        case,
                        row,
                        EffectState.CANCELLED,
                        None,
                        None,
                        disposition,
                        stamp,
                    )
                else:
                    self._insert_completion(
                        connection,
                        case,
                        EffectState.CANCELLED,
                        None,
                        None,
                        disposition,
                        stamp,
                    )
            inserted = connection.execute(
                sql.SQL("SELECT * FROM {} WHERE cancellation_id=%s").format(
                    self._table("cancellation_commands")
                ),
                (cancel_id,),
            ).fetchone()
            assert inserted is not None
            receipt = self._cancel_receipt(inserted, case, True)
            self._hit("effects.before_cancel_commit")
        self._hit("effects.after_cancel_commit")
        _event("cancellation_recorded")
        if disposition in {
            CancellationDisposition.BEFORE_COMMIT,
            CancellationDisposition.BEFORE_DISPATCH,
        }:
            _event("completion_committed")
        return receipt

    def completion(self, *, actor: AuthenticatedActor, task_id: str) -> CompletionEvent | None:
        with self._transaction() as connection:
            case = self.cases.get_in_transaction(connection, actor, task_id)
            return self._completion(connection, case)

    def _delivery(self, connection: Connection, event: CompletionEvent) -> DeliverySnapshot:
        row = connection.execute(
            sql.SQL("SELECT * FROM {} WHERE event_id=%s FOR UPDATE").format(
                self._table("completion_deliveries")
            ),
            (event.event_id,),
        ).fetchone()
        if row is None:
            raise InvalidStoredState("Completion event lacks durable delivery state")
        try:
            state = DeliveryState(row["state"])
            generation = integer(row["generation"])
            attempts = integer(row["attempts"], maximum=100)
            policy = parse_delivery_policy(json.loads(row["policy_json"]))
            if (
                canonical(policy.payload()) != row["policy_json"]
                or attempts > policy.maximum_attempts
            ):
                raise ValueError("Delivery policy is invalid")
            due = (
                None
                if row["next_attempt_at"] is None
                else utc_instant(row["next_attempt_at"]).isoformat()
            )
            if (state == DeliveryState.PENDING) != (due is not None):
                raise ValueError("Delivery eligibility is invalid")
            code = row["error_code"]
            if code not in {None, "dependency_unavailable", "delivery_exhausted"}:
                raise ValueError("Delivery code is invalid")
            target_id = None if row["target_id"] is None else uuid_identity(row["target_id"])
            if attempts > 0 and target_id is None:
                raise ValueError("Delivery attempts lack a bound receiver")
            return DeliverySnapshot(
                event,
                target_id,
                state,
                generation,
                attempts,
                due,
                code,
                utc_instant(row["updated_at"]).isoformat(),
            )
        except (
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            OverflowError,
        ) as error:
            raise InvalidStoredState("Completion delivery contains invalid stored state") from error

    def delivery(self, *, actor: AuthenticatedActor, task_id: str) -> DeliverySnapshot | None:
        with self._transaction() as connection:
            case = self.cases.get_in_transaction(connection, actor, task_id)
            event = self._completion(connection, case)
            return None if event is None else self._delivery(connection, event)

    def delivery_for_scope(self, *, scope_id: str, task_id: str) -> DeliverySnapshot | None:
        """Trusted worker inspection; application callers use the actor boundary."""
        with self._transaction() as connection:
            case = self._worker_case(connection, scope_id, task_id)
            event = self._completion(connection, case)
            return None if event is None else self._delivery(connection, event)

    def claim_delivery(
        self, *, scope_id: str, task_id: str, target_id: str
    ) -> DeliveryClaim | None:
        target_id = uuid_identity(target_id)
        with self._transaction() as connection:
            case = self._worker_case(connection, scope_id, task_id)
            self._guard(connection, scope_id, task_id)
            event = self._completion(connection, case)
            if event is None:
                return None
            current = self._delivery(connection, event)
            if current.target_id is not None and current.target_id != target_id:
                raise TransitionConflict("Completion is bound to another delivery target")
            now = self._now()
            stamp = now.isoformat()
            if current.state in {DeliveryState.DELIVERED, DeliveryState.EXHAUSTED}:
                return None
            if (
                current.state == DeliveryState.PENDING
                and utc_instant(current.next_attempt_at) > now
            ):
                return None
            row = connection.execute(
                sql.SQL("SELECT policy_json FROM {} WHERE event_id=%s").format(
                    self._table("completion_deliveries")
                ),
                (event.event_id,),
            ).fetchone()
            assert row is not None
            policy = parse_delivery_policy(json.loads(row["policy_json"]))
            if current.attempts >= policy.maximum_attempts:
                _one(
                    connection.execute(
                        sql.SQL(
                            "UPDATE {} SET state='exhausted',generation=generation+1,next_attempt_at=NULL,error_code='delivery_exhausted',updated_at=%s WHERE event_id=%s AND generation=%s"
                        ).format(self._table("completion_deliveries")),
                        (stamp, event.event_id, current.generation),
                    )
                )
                return None
            _one(
                connection.execute(
                    sql.SQL(
                        "UPDATE {} SET state='delivering',target_id=%s,generation=generation+1,attempts=attempts+1,next_attempt_at=NULL,error_code=NULL,updated_at=%s WHERE event_id=%s AND generation=%s"
                    ).format(self._table("completion_deliveries")),
                    (target_id, stamp, event.event_id, current.generation),
                )
            )
            claim = DeliveryClaim(event, current.generation + 1, current.attempts + 1, target_id)
            self._hit("delivery.before_claim_commit")
        self._hit("delivery.after_claim_commit")
        _event("completion_delivery_started")
        return claim

    def _claimed_delivery(
        self, connection: Connection, claim: DeliveryClaim
    ) -> tuple[CaseSnapshot, DeliverySnapshot, DeliveryPolicy]:
        case = self._worker_case(
            connection, claim.event.outcome.scope_id, claim.event.outcome.task_id
        )
        event = self._completion(connection, case)
        if event != claim.event:
            raise TransitionConflict("Delivery event changed before acknowledgement")
        current = self._delivery(connection, event)
        self._guard(connection, case.scope_id, case.task_id)
        if (
            current.state != DeliveryState.DELIVERING
            or current.generation != claim.generation
            or current.attempts != claim.attempts
            or current.target_id != claim.target_id
        ):
            raise TransitionConflict("Delivery claim is no longer current")
        row = connection.execute(
            sql.SQL("SELECT policy_json FROM {} WHERE event_id=%s").format(
                self._table("completion_deliveries")
            ),
            (event.event_id,),
        ).fetchone()
        assert row is not None
        return case, current, parse_delivery_policy(json.loads(row["policy_json"]))

    def finish_delivery(self, claim: DeliveryClaim, *, delivered: bool) -> DeliverySnapshot:
        if type(delivered) is not bool:
            raise ValueError("Delivery acknowledgement must be explicit")
        with self._transaction() as connection:
            _, current, policy = self._claimed_delivery(connection, claim)
            now = self._now()
            stamp = now.isoformat()
            state = (
                DeliveryState.DELIVERED
                if delivered
                else DeliveryState.EXHAUSTED
                if current.attempts >= policy.maximum_attempts
                else DeliveryState.PENDING
            )
            due = None
            if state == DeliveryState.PENDING:
                delay = min(
                    policy.maximum_delay_seconds,
                    policy.initial_delay_seconds * (2 ** (current.attempts - 1)),
                )
                try:
                    due = (now + timedelta(seconds=delay)).isoformat()
                except OverflowError:
                    state = DeliveryState.EXHAUSTED
            code = (
                None
                if delivered
                else "delivery_exhausted"
                if state == DeliveryState.EXHAUSTED
                else "dependency_unavailable"
            )
            _one(
                connection.execute(
                    sql.SQL(
                        "UPDATE {} SET state=%s,generation=generation+1,next_attempt_at=%s,error_code=%s,updated_at=%s WHERE event_id=%s AND generation=%s AND state='delivering'"
                    ).format(self._table("completion_deliveries")),
                    (
                        state.value,
                        due,
                        code,
                        stamp,
                        claim.event.event_id,
                        claim.generation,
                    ),
                )
            )
            value = self._delivery(connection, claim.event)
            self._hit("delivery.before_finish_commit")
        self._hit("delivery.after_finish_commit")
        _event(
            "completion_delivered" if delivered else "completion_delivery_failed",
            "ok" if delivered else code or "dependency_unavailable",
        )
        return value
