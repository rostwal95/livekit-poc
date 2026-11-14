"""Atomic managed investigation acceptance without mutation consent.

One protected v4 transaction creates the original inquiry, case owner and absolute
continuation deadline. Public callers cannot override actor, scope or policy.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from psycopg import sql

from .authorization import AuthenticatedActor
from .case_models import CaseSnapshot, identity
from .execution_models import ExecutionRecord, InvalidStoredState, UnsupportedOperation
from .lifecycle_models import LifecycleSnapshot
from .models import BookingChange, IdempotencyConflict
from .postgres_case import PostgresCaseAuthority
from .postgres_lifecycle import PostgresLifecycle
from .postgres_store import PostgresExecutionStore, _canonical
from .postgres_unit_of_work import protected_transaction
from .retry_policy import RetryPolicy, instant


@dataclass(frozen=True, slots=True)
class ManagedAcceptance:
    created: bool
    execution: ExecutionRecord
    case: CaseSnapshot
    lifecycle: LifecycleSnapshot


class PostgresManagedAdmission:
    """Retain first owner/deadline on replay, before new-work capacity checks."""

    def __init__(
        self,
        executions: PostgresExecutionStore,
        *,
        cases: PostgresCaseAuthority | None = None,
        lifecycle: PostgresLifecycle | None = None,
        lifetime_seconds: int = 300,
        policy: RetryPolicy | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        failpoint: Callable[[str], None] | None = None,
    ) -> None:
        if type(lifetime_seconds) is not int or not 1 <= lifetime_seconds <= 3600:
            raise ValueError("Managed acceptance lifetime must be finite and bounded")
        if policy is not None and type(policy) is not RetryPolicy:
            raise ValueError("Managed acceptance requires a typed trusted retry policy")
        self.executions, self.clock, self.failpoint = executions, clock, failpoint
        self.cases = cases or PostgresCaseAuthority(executions, clock=clock)
        self.lifecycle = lifecycle or PostgresLifecycle(executions, cases=self.cases, clock=clock)
        if self.cases.executions is not executions or self.lifecycle.executions is not executions:
            raise ValueError("Managed acceptance requires one execution authority")
        self.policy = policy or RetryPolicy()
        self.lifetime_seconds = lifetime_seconds

    def _hit(self, point: str) -> None:
        if self.failpoint is not None:
            self.failpoint(point)

    def accept(
        self, *, actor: AuthenticatedActor, idempotency_key: str, request: BookingChange
    ) -> ManagedAcceptance:
        if type(actor) is not AuthenticatedActor:
            raise ValueError("A trusted authenticated actor is required")
        idempotency_key = identity(idempotency_key)
        canonical_request = _canonical(request)

        def table(name: str) -> sql.Identifier:
            return sql.Identifier(self.executions.settings.schema, name)

        with protected_transaction(self.executions) as connection:
            metadata = connection.execute(
                sql.SQL("SELECT version FROM {} WHERE singleton").format(table("schema_metadata"))
            ).fetchone()
            if metadata is None or metadata["version"] not in (4, 5):
                raise UnsupportedOperation("Managed conversational acceptance requires schema v4")
            prior = connection.execute(
                sql.SQL(
                    "SELECT task_id,payload FROM {} WHERE scope_id=%s AND idempotency_key=%s"
                ).format(table("tasks")),
                (actor.scope_id, idempotency_key),
            ).fetchone()
            if prior is not None:
                presence = connection.execute(
                    sql.SQL(
                        "SELECT EXISTS(SELECT 1 FROM {} WHERE task_id=%s) AS case_present, EXISTS(SELECT 1 FROM {} WHERE task_id=%s) AS control_present"
                    ).format(table("cases"), table("execution_controls")),
                    (prior["task_id"], prior["task_id"]),
                ).fetchone()
                if presence is not None and presence["case_present"]:
                    # Owner checks precede semantic replay/conflict observations.
                    self.cases.get_in_transaction(connection, actor, prior["task_id"])
                if (
                    presence is None
                    or not presence["case_present"]
                    or not presence["control_present"]
                ):
                    raise UnsupportedOperation(
                        "Legacy inquiry requires explicit operator enrollment"
                    )
                if prior["payload"] != canonical_request:
                    raise IdempotencyConflict("Managed command already has another request")
                case = self.cases.get_in_transaction(connection, actor, prior["task_id"])
                execution, control = self.lifecycle._current(
                    connection, actor.scope_id, case.task_id
                )
                value = ManagedAcceptance(False, execution, case, control)
            else:
                now = instant(self.clock())
                try:
                    deadline = now + timedelta(seconds=self.lifetime_seconds)
                except OverflowError as error:
                    raise ValueError(
                        "Managed deadline exceeds the supported clock range"
                    ) from error
                accepted = self.executions.submit_in_transaction(
                    connection,
                    scope_id=actor.scope_id,
                    idempotency_key=idempotency_key,
                    request=request,
                )
                if not accepted.created or not accepted.enrolled:
                    raise InvalidStoredState(
                        "New managed command did not create its original inquiry"
                    )
                self._hit("managed_admission.after_inquiry")
                case, created = self.cases.enroll_in_transaction(
                    connection, actor=actor, task_id=accepted.execution.task_id
                )
                if not created:
                    raise InvalidStoredState("New managed inquiry already has a case")
                self._hit("managed_admission.after_case")
                control, created = self.lifecycle.manage_in_transaction(
                    connection,
                    scope_id=actor.scope_id,
                    task_id=case.task_id,
                    policy=self.policy,
                    deadline=deadline,
                )
                if not created:
                    raise InvalidStoredState("New managed inquiry already has continuation")
                self._hit("managed_admission.after_control")
                value = ManagedAcceptance(True, accepted.execution, case, control)
            self._hit("managed_admission.before_commit")
        self._hit("managed_admission.after_commit")
        return value
