"""Trusted synthetic proposal issuance, separate from model tool authority."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from psycopg import sql

from .authorization import AuthenticatedActor
from .case_models import QuoteSnapshot, StaleRevision, canonical, identity, integer, utc_instant
from .execution_models import InvalidStoredState, TransitionConflict, UnsupportedOperation
from .lifecycle_models import LifecycleState, WaitSnapshot
from .models import IdempotencyConflict
from .postgres_case import Connection, PostgresCaseAuthority
from .postgres_lifecycle import PostgresLifecycle, _wait
from .postgres_unit_of_work import protected_transaction
from .supplier import BookingSnapshot


class QuoteSupplierPort(Protocol):
    @property
    def provider_id(self) -> str: ...
    def booking(self, *, scope_id: str, booking_reference: str) -> BookingSnapshot: ...


@dataclass(frozen=True, slots=True)
class QuoteReceipt:
    quote: QuoteSnapshot
    created: bool
    wait_id: str


def quote_command_ids(actor: AuthenticatedActor, task_id: str, command_id: str) -> tuple[str, str]:
    identity(task_id)
    identity(command_id)
    binding = canonical(
        {
            "actor_id": actor.actor_id,
            "scope_id": actor.scope_id,
            "task_id": task_id,
            "command_id": command_id,
        }
    )
    return str(uuid5(NAMESPACE_URL, "continuity:quote:" + binding)), str(
        uuid5(NAMESPACE_URL, "continuity:wait:" + binding)
    )


class TrustedQuoteProducer:
    """Read independent booking facts outside SQL locks, then bind a current case.

    A command's retained quote/wait is replayed before supplier I/O or expiry.
    The caller supplies only expected case revision and command identity, never
    price, currency, provider identity or expected supplier revision.
    """

    def __init__(
        self,
        cases: PostgresCaseAuthority,
        lifecycle: PostgresLifecycle,
        supplier: QuoteSupplierPort,
        *,
        amount_minor: int = 2500,
        currency: str = "USD",
        lifetime_seconds: int = 120,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        failpoint: Callable[[str], None] | None = None,
    ) -> None:
        integer(amount_minor, maximum=9007199254740991)
        if currency not in {"USD", "EUR", "GBP", "INR"} or type(currency) is not str:
            raise ValueError("Trusted quote currency is unsupported")
        if type(lifetime_seconds) is not int or not 1 <= lifetime_seconds <= 600:
            raise ValueError("Trusted quote lifetime must be finite and bounded")
        if cases.executions is not lifecycle.executions:
            raise ValueError("Quote publication and waiting require one authority")
        self.cases, self.lifecycle, self.supplier = cases, lifecycle, supplier
        self.amount_minor, self.currency, self.lifetime_seconds = (
            amount_minor,
            currency,
            lifetime_seconds,
        )
        self.clock, self.failpoint = clock, failpoint

    def _hit(self, point: str) -> None:
        if self.failpoint is not None:
            self.failpoint(point)

    def _prior(
        self,
        connection: Connection,
        actor: AuthenticatedActor,
        task_id: str,
        expected_revision: int,
        quote_id: str,
        wait_id: str,
    ) -> QuoteReceipt | None:
        case = self.cases.get_in_transaction(connection, actor, task_id)
        metadata = connection.execute(
            sql.SQL("SELECT version FROM {} WHERE singleton").format(
                self.cases._table("schema_metadata")
            )
        ).fetchone()
        if metadata is None or metadata["version"] != 4:
            raise UnsupportedOperation("Trusted conversational quotes require schema v4")
        row = connection.execute(
            sql.SQL("SELECT task_id FROM {} WHERE quote_id=%s").format(self.cases._table("quotes")),
            (quote_id,),
        ).fetchone()
        wait_row = connection.execute(
            sql.SQL("SELECT * FROM {} WHERE wait_id=%s").format(
                self.cases._table("execution_waits")
            ),
            (wait_id,),
        ).fetchone()
        if row is None:
            if wait_row is not None:
                raise InvalidStoredState("Quote command wait lacks its quote")
            return None
        quote = self.cases._quote(connection, quote_id)
        if (
            row["task_id"] != task_id
            or quote.revision != expected_revision
            or quote.case_id != case.case_id
        ):
            raise IdempotencyConflict("Quote command already has different semantics")
        if wait_row is None:
            raise InvalidStoredState("Published command lacks its atomic wait")
        wait: WaitSnapshot = _wait(wait_row)
        if wait.task_id != task_id or wait.quote != quote or wait.deadline != quote.expires_at:
            raise InvalidStoredState("Quote command and wait evidence do not agree")
        return QuoteReceipt(quote, False, wait_id)

    def prepare(
        self,
        *,
        actor: AuthenticatedActor,
        task_id: str,
        expected_revision: int,
        command_id: str,
    ) -> QuoteReceipt:
        if type(actor) is not AuthenticatedActor:
            raise ValueError("A trusted authenticated actor is required")
        task_id, command_id = identity(task_id), identity(command_id)
        integer(expected_revision)
        quote_id, wait_id = quote_command_ids(actor, task_id, command_id)
        executions = self.cases.executions
        with protected_transaction(executions) as connection:
            prior = self._prior(connection, actor, task_id, expected_revision, quote_id, wait_id)
            if prior is not None:
                return prior
            case = self.cases.get_in_transaction(connection, actor, task_id)
            execution, control = self.lifecycle._current(connection, actor.scope_id, task_id)
            if case.revision != expected_revision:
                raise StaleRevision("Case revision is no longer current")
            if control.state != LifecycleState.INQUIRY_COMPLETE:
                raise TransitionConflict("Only completed investigation can receive a proposal")
            if (
                execution.result is None
                or execution.result.available is not True
                or (execution.result.booking_reference, execution.result.new_check_in)
                != (case.request.booking_reference, case.request.new_check_in)
            ):
                raise TransitionConflict(
                    "Current request lacks a matching available inquiry result"
                )
            request = case.request
        # No admission/case/lease transaction spans the independent supplier read.
        booking = self.supplier.booking(
            scope_id=actor.scope_id, booking_reference=request.booking_reference
        )
        if type(booking) is not BookingSnapshot or (
            booking.scope_id,
            booking.booking_reference,
        ) != (actor.scope_id, request.booking_reference):
            raise ValueError("Supplier booking facts do not match the scoped request")
        provider_id = self.supplier.provider_id
        self._hit("quote_producer.after_supplier_read")
        with protected_transaction(executions) as connection:
            prior = self._prior(connection, actor, task_id, expected_revision, quote_id, wait_id)
            if prior is not None:
                return prior
            case = self.cases.get_in_transaction(connection, actor, task_id)
            execution, control = self.lifecycle._current(connection, actor.scope_id, task_id)
            if case.revision != expected_revision or case.request != request:
                raise StaleRevision("Case changed while quote facts were being read")
            if control.state != LifecycleState.INQUIRY_COMPLETE:
                raise TransitionConflict("Investigation is no longer ready for a proposal")
            if (
                execution.result is None
                or execution.result.available is not True
                or (execution.result.booking_reference, execution.result.new_check_in)
                != (case.request.booking_reference, case.request.new_check_in)
            ):
                raise TransitionConflict(
                    "Current request lacks a matching available inquiry result"
                )
            now = utc_instant(self.clock().isoformat())
            deadline = utc_instant(control.deadline)
            try:
                expiry = min(now + timedelta(seconds=self.lifetime_seconds), deadline)
            except OverflowError:
                expiry = deadline
            if expiry <= now:
                raise TransitionConflict("Original business deadline has expired")
            quote = QuoteSnapshot(
                quote_id,
                task_id,
                case.revision,
                request.booking_reference,
                request.new_check_in,
                self.amount_minor,
                self.currency,
                expiry.isoformat(),
                case.case_id,
                booking.revision,
                provider_id,
            )
            self.cases.publish_quote_in_transaction(connection, actor=actor, quote=quote)
            self._hit("quote_producer.after_quote")
            self.lifecycle.arm_wait_in_transaction(
                connection,
                actor=actor,
                task_id=task_id,
                wait_id=wait_id,
                quote=quote,
                deadline=expiry,
            )
            self._hit("quote_producer.before_commit")
        self._hit("quote_producer.after_commit")
        return QuoteReceipt(quote, True, wait_id)
