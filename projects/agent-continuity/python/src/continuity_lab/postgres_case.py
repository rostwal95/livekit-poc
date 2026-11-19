"""Scoped case revision and atomic exact-confirmation authority on PostgreSQL v2.

Quote publication is trusted synthetic producer work. The public authenticated
service deliberately does not expose it as a caller or model tool. No supplier
operation is performed in this module or inside its protected transactions.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

import psycopg
from psycopg import sql

from .authorization import AuthenticatedActor
from .case_models import (
    ActionIntent,
    CaseCancelled,
    CaseCapacityExceeded,
    CaseSnapshot,
    Confirmation,
    DeadlineExpired,
    IntentAlreadyCommitted,
    IntentDispatch,
    InvalidConfirmation,
    QuoteExpired,
    QuoteSnapshot,
    StaleRevision,
    canonical,
    identity,
    integer,
    parse_intent,
    parse_quote,
    utc_instant,
    uuid_identity,
)
from .execution_models import (
    ExecutionNotFound,
    InvalidStoredState,
    TransitionConflict,
    UnsupportedOperation,
)
from .models import BookingChange, IdempotencyConflict
from .postgres_store import PostgresExecutionStore
from .postgres_unit_of_work import protected_transaction

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
Connection = psycopg.Connection[dict[str, Any]]


def _event(event: str) -> None:
    try:
        LOGGER.info(event, extra={"event": event, "code": "ok"})
    except Exception:  # noqa: BLE001 - telemetry cannot alter committed state or failures
        return


def _actor(actor: AuthenticatedActor) -> AuthenticatedActor:
    if type(actor) is not AuthenticatedActor:
        raise ValueError("A trusted authenticated actor is required")
    return actor


def _request(value: object) -> BookingChange:
    if not isinstance(value, dict) or set(value) != {
        "booking_reference",
        "new_check_in",
        "confirmed",
    }:
        raise ValueError("Case request has unsupported fields")
    return BookingChange(
        value["booking_reference"], date.fromisoformat(value["new_check_in"]), value["confirmed"]
    )


class PostgresCaseAuthority:
    """Single owner of current case facts and immutable commitment receipts.

    Admission -> case row is the lock order shared with waits/signals. All
    replay-protection rows are retained; finite caps reject only new records.
    Revision uses explicit compare-and-set; after lost acknowledgement inspect
    the current revision before issuing another revision command.
    """

    def __init__(
        self,
        executions: PostgresExecutionStore,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        failpoint: Callable[[str], None] | None = None,
        maximum_cases: int = 10000,
        maximum_quotes_per_case: int = 32,
        maximum_confirmations_per_case: int = 128,
    ) -> None:
        for value in (maximum_cases, maximum_quotes_per_case, maximum_confirmations_per_case):
            if type(value) is not int or not 1 <= value <= 1000000:
                raise ValueError("Case capacity must be a bounded positive integer")
        self.executions = executions
        self.clock, self.failpoint = clock, failpoint
        self.maximum_cases = maximum_cases
        self.maximum_quotes_per_case = maximum_quotes_per_case
        self.maximum_confirmations_per_case = maximum_confirmations_per_case

    def _table(self, name: str) -> sql.Identifier:
        return sql.Identifier(self.executions.settings.schema, name)

    def _now(self) -> datetime:
        value = self.clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Case clock must return an aware absolute instant")
        return value.astimezone(UTC)

    def _fail(self, name: str) -> None:
        if self.failpoint:
            self.failpoint(name)

    def _quote(self, connection: Connection, quote_id: str) -> QuoteSnapshot:
        row = connection.execute(
            sql.SQL("SELECT * FROM {} WHERE quote_id=%s").format(self._table("quotes")), (quote_id,)
        ).fetchone()
        if row is None:
            raise InvalidStoredState("Case quote is unavailable")
        try:
            quote = parse_quote(json.loads(row["payload_json"]))
            if canonical(quote.payload()) != row["payload_json"] or (
                quote.quote_id,
                quote.task_id,
                quote.revision,
            ) != (row["quote_id"], row["task_id"], row["revision"]):
                raise ValueError("Case quote columns do not match its payload")
            utc_instant(row["created_at"])
            return quote
        except (ValueError, TypeError, KeyError, OverflowError) as error:
            raise InvalidStoredState("Case quote contains invalid stored state") from error

    def _intent(self, row: dict[str, Any]) -> ActionIntent:
        try:
            intent = parse_intent(json.loads(row["payload_json"]))
            expected = (
                intent.intent_id,
                intent.task_id,
                intent.scope_id,
                intent.actor_id,
                intent.revision,
                intent.quote.quote_id,
                intent.confirmation_id,
                intent.effect_id,
                intent.created_at,
            )
            actual = tuple(
                row[name]
                for name in (
                    "intent_id",
                    "task_id",
                    "scope_id",
                    "actor_id",
                    "revision",
                    "quote_id",
                    "confirmation_id",
                    "effect_id",
                    "created_at",
                )
            )
            if expected != actual or canonical(intent.payload()) != row["payload_json"]:
                raise ValueError("Action intent columns do not match its payload")
            return intent
        except (ValueError, TypeError, KeyError, OverflowError) as error:
            raise InvalidStoredState("Action intent contains invalid stored state") from error

    def _validate_intent_evidence(self, connection: Connection, intent: ActionIntent) -> None:
        """A readable commitment requires its original exact consent and event."""
        confirmation = connection.execute(
            sql.SQL("SELECT * FROM {} WHERE confirmation_id=%s").format(
                self._table("confirmations")
            ),
            (intent.confirmation_id,),
        ).fetchone()
        dispatch = connection.execute(
            sql.SQL("SELECT * FROM {} WHERE intent_id=%s").format(self._table("intent_dispatch")),
            (intent.intent_id,),
        ).fetchone()
        if confirmation is None or dispatch is None:
            raise InvalidStoredState("Intent has incomplete commitment evidence")
        try:
            identity(confirmation["command_id"])
            expected_confirmation = (
                intent.confirmation_id,
                intent.task_id,
                intent.scope_id,
                intent.actor_id,
                canonical(Confirmation(intent.quote, True).payload()),
                intent.created_at,
            )
            actual_confirmation = tuple(
                confirmation[name]
                for name in (
                    "confirmation_id",
                    "task_id",
                    "scope_id",
                    "actor_id",
                    "payload_json",
                    "created_at",
                )
            )
            event = IntentDispatch(intent.dispatch_event_id, intent, intent.created_at)
            expected_dispatch = (
                event.event_id,
                intent.intent_id,
                canonical(event.payload()),
                event.created_at,
            )
            actual_dispatch = tuple(
                dispatch[name] for name in ("event_id", "intent_id", "payload_json", "created_at")
            )
            if expected_confirmation != actual_confirmation or expected_dispatch != actual_dispatch:
                raise ValueError("Intent evidence does not match its immutable snapshot")
        except (ValueError, TypeError, KeyError, OverflowError) as error:
            raise InvalidStoredState("Intent has invalid commitment evidence") from error

    def get_in_transaction(
        self,
        connection: Connection,
        actor: AuthenticatedActor,
        task_id: str,
        *,
        for_update: bool = True,
    ) -> CaseSnapshot:
        actor, task_id = _actor(actor), identity(task_id)
        query = sql.SQL("SELECT * FROM {} WHERE task_id=%s AND scope_id=%s AND actor_id=%s").format(
            self._table("cases")
        )
        if for_update:
            query += sql.SQL(" FOR UPDATE")
        row = connection.execute(query, (task_id, actor.scope_id, actor.actor_id)).fetchone()
        if row is None:
            raise ExecutionNotFound("Execution is unavailable in this scope")
        try:
            for name in ("task_id", "scope_id", "actor_id"):
                identity(row[name])
            uuid_identity(row["case_id"])
            if row["case_id"] == task_id:
                raise ValueError("Case and workflow identities must remain distinct")
            integer(row["revision"])
            if type(row["cancelled"]) is not bool:
                raise ValueError("Invalid case cancellation evidence")
            request = _request(json.loads(row["request_json"]))
            if canonical(request.payload()) != row["request_json"]:
                raise ValueError("Case request is not canonical")
            for name in ("created_at", "updated_at"):
                utc_instant(row[name])
            quote = (
                self._quote(connection, row["current_quote_id"])
                if row["current_quote_id"] is not None
                else None
            )
            if quote is not None and (
                quote.task_id,
                quote.revision,
                quote.booking_reference,
                quote.new_check_in,
            ) != (task_id, row["revision"], request.booking_reference, request.new_check_in):
                raise ValueError("Current quote is not bound to the current case")
            if quote is not None and quote.schema_version == 2 and quote.case_id != row["case_id"]:
                raise ValueError("Current proposal is not bound to the immutable case identity")
            rows = connection.execute(
                sql.SQL("SELECT * FROM {} WHERE task_id=%s ORDER BY revision DESC LIMIT 2").format(
                    self._table("action_intents")
                ),
                (task_id,),
            ).fetchall()
            if len(rows) > 1:
                raise ValueError("Case has multiple committed revisions")
            intent = self._intent(rows[0]) if rows else None
            if intent is not None and (
                intent.scope_id,
                intent.actor_id,
                intent.revision,
                intent.quote,
            ) != (actor.scope_id, actor.actor_id, row["revision"], quote):
                raise ValueError("Committed intent is not bound to the current case")
            if intent is not None:
                self._validate_intent_evidence(connection, intent)
            return CaseSnapshot(
                task_id,
                actor.scope_id,
                actor.actor_id,
                row["revision"],
                request,
                quote,
                row["cancelled"],
                intent,
                row["created_at"],
                row["updated_at"],
                row["case_id"],
            )
        except (ValueError, TypeError, KeyError, OverflowError) as error:
            raise InvalidStoredState("Case contains invalid stored state") from error

    def get(self, *, actor: AuthenticatedActor, task_id: str) -> CaseSnapshot:
        with protected_transaction(self.executions) as connection:
            return self.get_in_transaction(connection, actor, task_id)

    def enroll(self, *, actor: AuthenticatedActor, task_id: str) -> CaseSnapshot:
        actor, task_id = _actor(actor), identity(task_id)
        with protected_transaction(self.executions) as connection:
            snapshot, created = self.enroll_in_transaction(connection, actor=actor, task_id=task_id)
        self._fail("case.after_enroll_commit")
        _event("case_enrolled" if created else "case_replayed")
        return snapshot

    def enroll_in_transaction(
        self,
        connection: Connection,
        *,
        actor: AuthenticatedActor,
        task_id: str,
    ) -> tuple[CaseSnapshot, bool]:
        """Enroll inside the caller's protected transaction without a second commit."""
        actor, task_id = _actor(actor), identity(task_id)
        created = False
        execution = self.executions._get(connection, actor.scope_id, task_id)
        prior = connection.execute(
            sql.SQL("SELECT actor_id FROM {} WHERE task_id=%s").format(self._table("cases")),
            (task_id,),
        ).fetchone()
        if prior is None:
            count = connection.execute(
                sql.SQL("SELECT COUNT(*) AS n FROM {}").format(self._table("cases"))
            ).fetchone()
            if count is None or count["n"] >= self.maximum_cases:
                raise CaseCapacityExceeded("Case retention capacity is exhausted")
            stamp = self._now().isoformat()
            case_id = str(uuid4())
            if case_id == task_id:
                raise InvalidStoredState("Case identity collided with its workflow identity")
            connection.execute(
                sql.SQL(
                    "INSERT INTO {} (task_id,case_id,scope_id,actor_id,revision,request_json,current_quote_id,cancelled,created_at,updated_at) VALUES (%s,%s,%s,%s,0,%s,NULL,FALSE,%s,%s)"
                ).format(self._table("cases")),
                (
                    task_id,
                    case_id,
                    actor.scope_id,
                    actor.actor_id,
                    canonical(execution.request.payload()),
                    stamp,
                    stamp,
                ),
            )
            created = True
        snapshot = self.get_in_transaction(connection, actor, task_id)
        self._fail("case.before_enroll_commit")
        return snapshot, created

    def revise(
        self,
        *,
        actor: AuthenticatedActor,
        task_id: str,
        expected_revision: int,
        request: BookingChange,
    ) -> CaseSnapshot:
        expected_revision = integer(expected_revision)
        if type(request) is not BookingChange:
            raise ValueError("A validated case request is required")
        with protected_transaction(self.executions) as connection:
            current = self.get_in_transaction(connection, actor, task_id)
            if current.revision != expected_revision:
                raise StaleRevision("Case revision is no longer current")
            if current.intent is not None:
                raise IntentAlreadyCommitted("Committed case requires a new request")
            if current.cancelled:
                raise CaseCancelled("Case was cancelled before commitment")
            if current.request == request:
                return current
            if current.revision == 9223372036854775807:
                raise CaseCapacityExceeded("Case revision capacity is exhausted")
            control = connection.execute(
                sql.SQL("SELECT * FROM {} WHERE task_id=%s FOR UPDATE").format(
                    self._table("execution_controls")
                ),
                (task_id,),
            ).fetchone()
            waits = connection.execute(
                sql.SQL("SELECT * FROM {} WHERE task_id=%s AND state='pending' FOR UPDATE").format(
                    self._table("execution_waits")
                ),
                (task_id,),
            ).fetchall()
            now = self._now()
            stamp = now.isoformat()
            changed = connection.execute(
                sql.SQL(
                    "UPDATE {} SET revision=revision+1,request_json=%s,current_quote_id=NULL,updated_at=%s WHERE task_id=%s AND revision=%s"
                ).format(self._table("cases")),
                (canonical(request.payload()), stamp, task_id, expected_revision),
            )
            if changed.rowcount != 1:
                raise TransitionConflict("Case revision changed before this command")
            for wait in waits:
                changed = connection.execute(
                    sql.SQL(
                        "UPDATE {} SET state='expired',finished_at=%s WHERE wait_id=%s AND state='pending'"
                    ).format(self._table("execution_waits")),
                    (stamp, wait["wait_id"]),
                )
                if changed.rowcount != 1:
                    raise TransitionConflict("Case wait changed before revision")
            if control is not None and control["state"] == "waiting":
                expired = now >= utc_instant(control["deadline"])
                changed = connection.execute(
                    sql.SQL(
                        "UPDATE {} SET state=%s,next_attempt_at=NULL,version=version+1,last_failure=NULL,error_code=%s,updated_at=%s WHERE task_id=%s AND version=%s"
                    ).format(self._table("execution_controls")),
                    (
                        "failed" if expired else "inquiry_complete",
                        "deadline_expired" if expired else None,
                        stamp,
                        task_id,
                        control["version"],
                    ),
                )
                if changed.rowcount != 1:
                    raise TransitionConflict("Case continuation changed before revision")
            snapshot = self.get_in_transaction(connection, actor, task_id)
            self._fail("case.before_revision_commit")
        self._fail("case.after_revision_commit")
        _event("case_revised")
        return snapshot

    def _require_proposal_version(self, connection: Connection, quote: QuoteSnapshot) -> None:
        metadata = connection.execute(
            sql.SQL("SELECT version FROM {} WHERE singleton").format(self._table("schema_metadata"))
        ).fetchone()
        if metadata is None or (metadata["version"] >= 3 and quote.schema_version != 2):
            raise UnsupportedOperation(
                "New mutation consent requires a supplier-bound version 2 proposal"
            )

    def _withdraw_pending_waits(self, connection: Connection, task_id: str) -> datetime:
        control = connection.execute(
            sql.SQL("SELECT * FROM {} WHERE task_id=%s FOR UPDATE").format(
                self._table("execution_controls")
            ),
            (task_id,),
        ).fetchone()
        waits = connection.execute(
            sql.SQL(
                "SELECT wait_id FROM {} WHERE task_id=%s AND state='pending' FOR UPDATE"
            ).format(self._table("execution_waits")),
            (task_id,),
        ).fetchall()
        now = self._now()
        for wait in waits:
            changed = connection.execute(
                sql.SQL(
                    "UPDATE {} SET state='expired',finished_at=%s WHERE wait_id=%s AND state='pending'"
                ).format(self._table("execution_waits")),
                (now.isoformat(), wait["wait_id"]),
            )
            if changed.rowcount != 1:
                raise TransitionConflict("Case wait changed before new proposal")
        if control is not None and control["state"] == "waiting":
            expired = now >= utc_instant(control["deadline"])
            changed = connection.execute(
                sql.SQL(
                    "UPDATE {} SET state=%s,next_attempt_at=NULL,version=version+1,last_failure=NULL,error_code=%s,updated_at=%s WHERE task_id=%s AND version=%s"
                ).format(self._table("execution_controls")),
                (
                    "failed" if expired else "inquiry_complete",
                    "deadline_expired" if expired else None,
                    now.isoformat(),
                    task_id,
                    control["version"],
                ),
            )
            if changed.rowcount != 1:
                raise TransitionConflict("Case continuation changed before new proposal")
        return now

    def _validate_quote(self, current: CaseSnapshot, quote: QuoteSnapshot, now: datetime) -> None:
        if quote.schema_version == 2 and quote.case_id != current.case_id:
            raise InvalidConfirmation("Proposal does not match the immutable case identity")
        if current.cancelled:
            raise CaseCancelled("Case was cancelled before commitment")
        if current.revision != quote.revision:
            raise StaleRevision("Case revision is no longer current")
        if current.quote != quote:
            raise InvalidConfirmation("Confirmation does not match the current published quote")
        if now >= utc_instant(quote.expires_at):
            raise QuoteExpired("Quote has expired")

    def validate_quote_in_transaction(
        self, connection: Connection, actor: AuthenticatedActor, quote: QuoteSnapshot
    ) -> None:
        if type(quote) is not QuoteSnapshot:
            raise InvalidConfirmation("An exact published quote is required")
        current = self.get_in_transaction(connection, actor, quote.task_id)
        self._validate_quote(current, quote, self._now())

    def publish_quote(self, *, actor: AuthenticatedActor, quote: QuoteSnapshot) -> QuoteSnapshot:
        if type(quote) is not QuoteSnapshot:
            raise ValueError("A validated quote snapshot is required")
        with protected_transaction(self.executions) as connection:
            value, replayed = self.publish_quote_in_transaction(
                connection, actor=actor, quote=quote
            )
        self._fail("case.after_quote_commit")
        _event("quote_replayed" if replayed else "quote_published")
        return value

    def publish_quote_in_transaction(
        self,
        connection: Connection,
        *,
        actor: AuthenticatedActor,
        quote: QuoteSnapshot,
    ) -> tuple[QuoteSnapshot, bool]:
        """Publish within an existing protected authority transaction."""
        if type(quote) is not QuoteSnapshot:
            raise ValueError("A validated quote snapshot is required")
        replayed = False
        current = self.get_in_transaction(connection, actor, quote.task_id)
        prior = connection.execute(
            sql.SQL("SELECT task_id,payload_json FROM {} WHERE quote_id=%s").format(
                self._table("quotes")
            ),
            (quote.quote_id,),
        ).fetchone()
        if prior is not None:
            if prior["task_id"] != quote.task_id or prior["payload_json"] != canonical(
                quote.payload()
            ):
                raise IdempotencyConflict("Quote identity already has different semantics")
            self._quote(connection, quote.quote_id)
            replayed = True
        else:
            self._require_proposal_version(connection, quote)
            if quote.schema_version == 2 and quote.case_id != current.case_id:
                raise InvalidConfirmation("Proposal does not match the immutable case identity")
            if current.quote is not None:
                now = self._withdraw_pending_waits(connection, current.task_id)
                if now >= utc_instant(quote.expires_at):
                    raise QuoteExpired("Quote has expired")
            if current.intent is not None:
                raise IntentAlreadyCommitted("Committed case requires a new request")
            if current.cancelled:
                raise CaseCancelled("Case was cancelled before commitment")
            if current.revision != quote.revision:
                raise StaleRevision("Case revision is no longer current")
            if (current.request.booking_reference, current.request.new_check_in) != (
                quote.booking_reference,
                quote.new_check_in,
            ):
                raise InvalidConfirmation("Quote does not match the current case request")
            count = connection.execute(
                sql.SQL("SELECT COUNT(*) AS n FROM {} WHERE task_id=%s").format(
                    self._table("quotes")
                ),
                (quote.task_id,),
            ).fetchone()
            if count is None or count["n"] >= self.maximum_quotes_per_case:
                raise CaseCapacityExceeded("Quote retention capacity is exhausted")
            now = self._now()
            if now >= utc_instant(quote.expires_at):
                raise QuoteExpired("Quote has expired")
            stamp = now.isoformat()
            connection.execute(
                sql.SQL(
                    "INSERT INTO {} (quote_id,task_id,revision,payload_json,created_at) VALUES (%s,%s,%s,%s,%s)"
                ).format(self._table("quotes")),
                (
                    quote.quote_id,
                    quote.task_id,
                    quote.revision,
                    canonical(quote.payload()),
                    stamp,
                ),
            )
            connection.execute(
                sql.SQL("UPDATE {} SET current_quote_id=%s,updated_at=%s WHERE task_id=%s").format(
                    self._table("cases")
                ),
                (quote.quote_id, stamp, quote.task_id),
            )
        self._fail("case.before_quote_commit")
        return quote, replayed

    def _commit_in_transaction(
        self,
        connection: Connection,
        actor: AuthenticatedActor,
        confirmation: Confirmation,
        command_id: str,
    ) -> tuple[ActionIntent, bool]:
        if type(confirmation) is not Confirmation:
            raise InvalidConfirmation("An exact explicit confirmation is required")
        command_id = identity(command_id)
        current = self.get_in_transaction(connection, actor, confirmation.quote.task_id)
        payload = canonical(confirmation.payload())
        prior = connection.execute(
            sql.SQL("SELECT * FROM {} WHERE scope_id=%s AND command_id=%s").format(
                self._table("confirmations")
            ),
            (actor.scope_id, command_id),
        ).fetchone()
        if prior is not None:
            if (prior["task_id"], prior["actor_id"], prior["payload_json"]) != (
                current.task_id,
                actor.actor_id,
                payload,
            ):
                raise IdempotencyConflict("Confirmation command already has different semantics")
            if current.intent is None or current.intent.quote != confirmation.quote:
                raise InvalidStoredState("Confirmation receipt has no matching committed intent")
            return current.intent, False
        self._require_proposal_version(connection, confirmation.quote)
        control = connection.execute(
            sql.SQL("SELECT * FROM {} WHERE task_id=%s FOR UPDATE").format(
                self._table("execution_controls")
            ),
            (current.task_id,),
        ).fetchone()
        waits = connection.execute(
            sql.SQL("SELECT * FROM {} WHERE task_id=%s AND state='pending' FOR UPDATE").format(
                self._table("execution_waits")
            ),
            (current.task_id,),
        ).fetchall()
        # All business timers use one instant sampled after every required lock.
        now = self._now()
        if confirmation.quote.schema_version == 2 and control is None:
            raise UnsupportedOperation(
                "Mutation consent requires an existing managed business deadline"
            )
        if control is not None:
            integer(control["version"])
            if now >= utc_instant(control["deadline"]):
                raise DeadlineExpired("Business deadline has expired")
            allowed = (
                {"inquiry_complete", "waiting"} if current.intent is None else {"intent_committed"}
            )
            if control["state"] not in allowed:
                raise TransitionConflict(
                    "Managed execution cannot accept confirmation in its current state"
                )
        for wait in waits:
            if wait["quote_json"] == canonical(confirmation.quote.payload()) and now >= utc_instant(
                wait["deadline"]
            ):
                raise DeadlineExpired("Confirmation wait deadline has expired")
        self._validate_quote(current, confirmation.quote, now)
        count = connection.execute(
            sql.SQL("SELECT COUNT(*) AS n FROM {} WHERE task_id=%s").format(
                self._table("confirmations")
            ),
            (current.task_id,),
        ).fetchone()
        if count is None or count["n"] >= self.maximum_confirmations_per_case:
            raise CaseCapacityExceeded("Confirmation retention capacity is exhausted")
        confirmation_id, stamp = str(uuid4()), now.isoformat()
        connection.execute(
            sql.SQL(
                "INSERT INTO {} (confirmation_id,task_id,scope_id,actor_id,command_id,payload_json,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)"
            ).format(self._table("confirmations")),
            (
                confirmation_id,
                current.task_id,
                actor.scope_id,
                actor.actor_id,
                command_id,
                payload,
                stamp,
            ),
        )
        created = current.intent is None
        if current.intent is not None:
            if current.intent.quote != confirmation.quote:
                raise IntentAlreadyCommitted("Case already has a different committed intent")
            intent = current.intent
        else:
            intent = ActionIntent(
                str(uuid4()),
                current.task_id,
                actor.scope_id,
                actor.actor_id,
                current.revision,
                confirmation.quote,
                confirmation_id,
                str(uuid4()),
                str(uuid4()),
                stamp,
            )
            connection.execute(
                sql.SQL(
                    "INSERT INTO {} (intent_id,task_id,scope_id,actor_id,revision,quote_id,confirmation_id,effect_id,payload_json,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
                ).format(self._table("action_intents")),
                (
                    intent.intent_id,
                    intent.task_id,
                    intent.scope_id,
                    intent.actor_id,
                    intent.revision,
                    intent.quote.quote_id,
                    intent.confirmation_id,
                    intent.effect_id,
                    canonical(intent.payload()),
                    stamp,
                ),
            )
            dispatch = IntentDispatch(intent.dispatch_event_id, intent, stamp)
            connection.execute(
                sql.SQL(
                    "INSERT INTO {} (event_id,intent_id,payload_json,created_at) VALUES (%s,%s,%s,%s)"
                ).format(self._table("intent_dispatch")),
                (dispatch.event_id, intent.intent_id, canonical(dispatch.payload()), stamp),
            )
            connection.execute(
                sql.SQL("UPDATE {} SET updated_at=%s WHERE task_id=%s").format(
                    self._table("cases")
                ),
                (stamp, current.task_id),
            )
        if created:
            if control is not None:
                changed = connection.execute(
                    sql.SQL(
                        "UPDATE {} SET state='intent_committed',next_attempt_at=NULL,version=version+1,updated_at=%s WHERE task_id=%s AND version=%s"
                    ).format(self._table("execution_controls")),
                    (stamp, current.task_id, control["version"]),
                )
                if changed.rowcount != 1:
                    raise TransitionConflict("Case continuation changed before commitment")
            for wait in waits:
                state = (
                    "consumed"
                    if wait["quote_json"] == canonical(confirmation.quote.payload())
                    else "expired"
                )
                changed = connection.execute(
                    sql.SQL(
                        "UPDATE {} SET state=%s,finished_at=%s WHERE wait_id=%s AND state='pending'"
                    ).format(self._table("execution_waits")),
                    (state, stamp, wait["wait_id"]),
                )
                if changed.rowcount != 1:
                    raise TransitionConflict("Case wait changed before commitment")
        self._fail("case.after_intent_rows")
        return intent, created

    def commit_intent_in_transaction(
        self,
        connection: Connection,
        actor: AuthenticatedActor,
        confirmation: Confirmation,
        command_id: str,
    ) -> ActionIntent:
        """Caller owns the shared transaction; no connection, await or commit here."""
        return self._commit_in_transaction(connection, actor, confirmation, command_id)[0]

    def commit_intent(
        self, *, actor: AuthenticatedActor, confirmation: Confirmation, command_id: str
    ) -> ActionIntent:
        with protected_transaction(self.executions) as connection:
            intent, created = self._commit_in_transaction(
                connection, actor, confirmation, command_id
            )
            self._fail("case.before_intent_commit")
        self._fail("case.after_intent_commit")
        _event("intent_committed" if created else "intent_replayed")
        return intent

    def dispatches(self, *, actor: AuthenticatedActor, task_id: str) -> tuple[IntentDispatch, ...]:
        with protected_transaction(self.executions) as connection:
            current = self.get_in_transaction(connection, actor, task_id)
            if current.intent is None:
                return ()
            rows = connection.execute(
                sql.SQL("SELECT * FROM {} WHERE intent_id=%s").format(
                    self._table("intent_dispatch")
                ),
                (current.intent.intent_id,),
            ).fetchall()
            if len(rows) != 1:
                raise InvalidStoredState("Intent has invalid dispatch evidence")
            dispatch = IntentDispatch(
                current.intent.dispatch_event_id, current.intent, current.intent.created_at
            )
            row = rows[0]
            if (row["event_id"], row["intent_id"], row["payload_json"], row["created_at"]) != (
                dispatch.event_id,
                current.intent.intent_id,
                canonical(dispatch.payload()),
                dispatch.created_at,
            ):
                raise InvalidStoredState("Intent has invalid dispatch evidence")
            return (dispatch,)
