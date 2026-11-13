"""Real PostgreSQL and separate supplier state prove the mutation boundary.

Independent OS processes die after durable supplier success and before local
acknowledgment. Inspection-only supplier counters are evidence for tests, never
reconciliation authority for production workers.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from psycopg import sql

from continuity_lab.authorization import AuthenticatedActor
from continuity_lab.case_models import (
    Confirmation,
    InvalidConfirmation,
    QuoteExpired,
    QuoteSnapshot,
    StaleRevision,
)
from continuity_lab.effect_models import EffectFailure, EffectState
from continuity_lab.execution_models import (
    ExecutionCapacityExceeded,
    TransitionConflict,
    UnsupportedOperation,
)
from continuity_lab.lifecycle_models import LifecycleState
from continuity_lab.managed_inquiry_worker import ManagedInquiryWorker
from continuity_lab.models import BookingChange
from continuity_lab.mutation_supplier import (
    MutationSupplier,
    MutationUnavailable,
    NonCooperatingMutationSupplier,
    initialize_mutation_supplier,
)
from continuity_lab.mutation_worker import MutationWorker
from continuity_lab.postgres_case import PostgresCaseAuthority
from continuity_lab.postgres_effects import PostgresEffects
from continuity_lab.postgres_lifecycle import PostgresLifecycle
from continuity_lab.postgres_migrations import (
    activate_import,
    install_schema,
    stage_import,
    upgrade_v2,
    upgrade_v3,
)
from continuity_lab.postgres_settings import PostgresSettings
from continuity_lab.postgres_store import PostgresExecutionStore
from continuity_lab.postgres_unit_of_work import protected_transaction
from continuity_lab.retry_policy import RetryPolicy
from continuity_lab.transfer import make_snapshot
from harness.process_control import FileBarrier, OwnedProcess

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2030, 12, 1, tzinfo=UTC)
ACTOR = AuthenticatedActor("actor-a", "account-a")
BOOKING = "DEMO-BK-001"

CHILD = r"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from continuity_lab.mutation_supplier import MutationSupplier, NonCooperatingMutationSupplier
from continuity_lab.mutation_worker import MutationWorker
from continuity_lab.postgres_effects import PostgresEffects
from continuity_lab.postgres_settings import PostgresSettings
from continuity_lab.postgres_store import PostgresExecutionStore
from harness.process_control import FileBarrier

supplier_db, directory, mode, point, scope, task_id, now, cooperating = sys.argv[1:]
barrier = FileBarrier(Path(directory), "mutation_boundary")
def failpoint(name):
    if name == point:
        if mode == "exit":
            os._exit(71)
        if mode == "barrier":
            barrier.arrive_and_wait(timeout=20)

clock = lambda: datetime.fromisoformat(now)
executions = PostgresExecutionStore(PostgresSettings.from_env(), clock=clock)
effects = PostgresEffects(executions, clock=clock)
factory = MutationSupplier if cooperating == "1" else NonCooperatingMutationSupplier
supplier = factory(Path(supplier_db), clock=clock)
value = MutationWorker(effects, supplier, failpoint=failpoint).run_one(scope_id=scope, task_id=task_id)
print(json.dumps({"state": value.state.value, "intent_id": value.intent.intent_id,
                  "effect_id": value.intent.effect_id, "attempt_no": value.attempt_no,
                  "dispatch_count": value.dispatch_count,
                  "result": None if value.result is None else value.result.payload()}), flush=True)
"""


class Clock:
    def __init__(self):
        self.value = NOW

    def __call__(self):
        return self.value


class PostgresMutationCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("P1_RUN_POSTGRES_TESTS") != "1":
            raise RuntimeError("Real mutation gate requires explicit local PostgreSQL setup")
        cls.runtime_base = PostgresSettings.from_env()
        cls.owner_base = PostgresSettings.from_env("P1_MIGRATION_")

    def setUp(self):
        self.schema = "p1_mutation_" + uuid4().hex
        self.runtime = replace(self.runtime_base, schema=self.schema)
        self.owner = replace(self.owner_base, schema=self.schema)
        self.addCleanup(self.drop_schema)
        install_schema(self.owner)
        snapshot = make_snapshot([], [], [], migration_id=str(uuid4()))
        stage_import(self.owner, snapshot)
        activate_import(self.owner, snapshot.migration_id, snapshot.source_digest)
        upgrade_v2(self.owner)
        upgrade_v3(self.owner)
        self.clock = Clock()
        self.executions = PostgresExecutionStore(self.runtime, clock=self.clock)
        self.cases = PostgresCaseAuthority(self.executions, clock=self.clock)
        self.lifecycle = PostgresLifecycle(self.executions, cases=self.cases, clock=self.clock)
        self.effects = PostgresEffects(self.executions, cases=self.cases, clock=self.clock)
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.folder = Path(self.directory.name).resolve()
        self.database = self.folder / "supplier.sqlite3"
        initialize_mutation_supplier(self.database, scope_id=ACTOR.scope_id)
        self.supplier = MutationSupplier(self.database, clock=self.clock)
        self.sequence = 0

    def drop_schema(self):
        if not self.schema.startswith("p1_mutation_") or len(self.schema) != 44:
            raise AssertionError("Only this isolated mutation test schema may be removed")
        with closing(self.owner.connect(application_name="continuity-test")) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(self.schema))
            )

    def prepare(self, key="one", *, supplier=None, revision=None, deadline=None, commit=True):
        supplier = self.supplier if supplier is None else supplier
        request = BookingChange(BOOKING, date(2030, 12, 10), True)
        record = self.executions.submit(
            scope_id=ACTOR.scope_id, idempotency_key=key, request=request
        ).execution
        self.lifecycle.manage(
            scope_id=ACTOR.scope_id,
            task_id=record.task_id,
            policy=RetryPolicy(),
            deadline=self.clock() + timedelta(minutes=5) if deadline is None else deadline,
        )
        inquiry = ManagedInquiryWorker(self.lifecycle, supplier.inquiry_view()).run_one(
            scope_id=ACTOR.scope_id, task_id=record.task_id
        )
        self.assertEqual(inquiry.state, LifecycleState.INQUIRY_COMPLETE)
        case = self.cases.enroll(actor=ACTOR, task_id=record.task_id)
        booking = supplier.booking(scope_id=ACTOR.scope_id, booking_reference=BOOKING)
        quote = QuoteSnapshot(
            str(uuid4()),
            record.task_id,
            case.revision,
            BOOKING,
            request.new_check_in,
            12500,
            "USD",
            (self.clock() + timedelta(seconds=30)).isoformat(),
            case_id=case.case_id,
            expected_supplier_revision=booking.revision if revision is None else revision,
            supplier_id=supplier.provider_id,
        )
        self.cases.publish_quote(actor=ACTOR, quote=quote)
        if not commit:
            return record, quote
        intent = self.cases.commit_intent(
            actor=ACTOR, confirmation=Confirmation(quote, True), command_id="confirm-" + key
        )
        return record, intent

    def noncooperating(self):
        database = self.folder / "noncooperating.sqlite3"
        initialize_mutation_supplier(database, scope_id=ACTOR.scope_id, cooperating=False)
        return NonCooperatingMutationSupplier(database, clock=self.clock)

    def run_one(self, record, *, supplier=None, effects=None, failpoint=None):
        return MutationWorker(
            self.effects if effects is None else effects,
            self.supplier if supplier is None else supplier,
            failpoint=failpoint,
        ).run_one(scope_id=ACTOR.scope_id, task_id=record.task_id)

    def read(self, record):
        return self.effects.get(scope_id=ACTOR.scope_id, task_id=record.task_id)

    def rows(self, table, task_id):
        key = "intent_id" if table == "mutation_attempts" else "task_id"
        with closing(self.runtime.connect()) as connection:
            return connection.execute(
                sql.SQL("SELECT * FROM {} WHERE {}=%s ORDER BY 1").format(
                    sql.Identifier(self.schema, table), sql.Identifier(key)
                ),
                (task_id,),
            ).fetchall()

    def child(self, record, *, supplier=None, mode="normal", point="unused"):
        supplier = self.supplier if supplier is None else supplier
        self.sequence += 1
        state = self.folder / f"worker_{self.sequence}"
        state.mkdir(mode=0o700)
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(ROOT),
            "PYTHONDONTWRITEBYTECODE": "1",
            "P1_POSTGRES_HOST": self.runtime.host,
            "P1_POSTGRES_PORT": str(self.runtime.port),
            "P1_POSTGRES_DB": self.runtime.dbname,
            "P1_POSTGRES_USER": self.runtime.user,
            "P1_POSTGRES_PASSWORD": self.runtime.password,
            "P1_POSTGRES_SCHEMA": self.schema,
        }
        child = OwnedProcess(
            [
                sys.executable,
                "-c",
                CHILD,
                str(supplier.database),
                str(state),
                mode,
                point,
                ACTOR.scope_id,
                record.task_id,
                self.clock().isoformat(),
                "1" if supplier.capabilities.idempotent else "0",
            ],
            cwd=ROOT,
            env=environment,
            output_directory=self.folder / f"worker_{self.sequence}_output",
            max_output_bytes=16384,
        )
        self.addCleanup(child.close)
        return child, FileBarrier(state, "mutation_boundary")

    def finished(self, child):
        result = child.wait(timeout=10)
        self.assertEqual(result.returncode, 0, child.output_tail("stderr"))
        output = child.output_tail("stdout")
        self.assertEqual(len(output.splitlines()), 1)
        return json.loads(output)

    def assert_counts(self, supplier, *, applied, calls):
        self.assertEqual(supplier.count_mutations(scope_id=ACTOR.scope_id), applied)
        self.assertEqual(supplier.count_calls(scope_id=ACTOR.scope_id), calls)

    def assert_completion(self, record, intent):
        self.assertEqual(len(self.rows("business_outcomes", record.task_id)), 1)
        self.assertEqual(len(self.rows("completion_events", record.task_id)), 1)
        [event] = self.rows("completion_events", record.task_id)
        payload = json.loads(event["payload_json"])
        self.assertEqual(payload["outcome"]["effect_id"], intent.effect_id)

    def test_normal_inquiry_confirmation_and_separate_mutation_process_preserve_identity(self):
        record, intent = self.prepare()
        before = self.supplier.booking(scope_id=ACTOR.scope_id, booking_reference=BOOKING)
        child, _ = self.child(record)
        with child:
            response = self.finished(child)
        value = self.read(record)
        self.assertEqual(response["state"], "succeeded")
        self.assertEqual(
            (response["intent_id"], response["effect_id"]), (intent.intent_id, intent.effect_id)
        )
        self.assertEqual(
            (value.state, value.attempt_no, value.dispatch_count), (EffectState.SUCCEEDED, 1, 1)
        )
        result = value.result
        self.assertEqual((result.previous_revision, result.revision), (before.revision, 1))
        self.assertEqual((result.amount_minor, result.currency), (12500, "USD"))
        self.assertEqual(result.supplier_id, self.supplier.provider_id)
        self.assert_counts(self.supplier, applied=1, calls=1)
        self.assertEqual(self.supplier.count_inquiries(scope_id=ACTOR.scope_id), 1)
        self.assert_completion(record, intent)
        repeat, _ = self.child(record)
        with repeat:
            self.assertEqual(self.finished(repeat), response)
        self.assertEqual(self.read(record), value)
        self.assert_counts(self.supplier, applied=1, calls=1)

    def test_sigkill_after_supplier_commit_reconciles_original_effect_without_second_apply(self):
        record, intent = self.prepare()
        child, barrier = self.child(
            record, mode="barrier", point="mutation_worker.after_supplier_success"
        )
        with child:
            child.wait_for_barrier(barrier, timeout=10)
            self.assertEqual(self.read(record).state, EffectState.DISPATCHED)
            known = self.supplier.lookup(intent)
            self.assertIsNotNone(known)
            self.assert_counts(self.supplier, applied=1, calls=1)
            self.assertEqual(len(self.rows("completion_events", record.task_id)), 0)
            termination = child.kill(timeout=3)
            self.assertTrue(termination.killed)
            self.assertEqual(termination.returncode, -signal.SIGKILL)
            self.assertEqual(child.wait(timeout=3).returncode, -signal.SIGKILL)
            self.assertEqual(child.output_tail("stdout"), "")
        replacement, _ = self.child(record)
        with replacement:
            response = self.finished(replacement)
        value = self.read(record)
        self.assertEqual(value.state, EffectState.SUCCEEDED)
        self.assertEqual(value.result, known.result)
        self.assertEqual(response["effect_id"], intent.effect_id)
        self.assertEqual((value.attempt_no, value.dispatch_count), (2, 1))
        attempts = sorted(
            self.rows("mutation_attempts", intent.intent_id), key=lambda row: row["attempt_no"]
        )
        self.assertEqual([row["state"] for row in attempts], ["interrupted", "succeeded"])
        self.assertNotEqual(attempts[0]["attempt_id"], attempts[1]["attempt_id"])
        self.assert_counts(self.supplier, applied=1, calls=1)
        self.assert_completion(record, intent)

    def test_os_exit_after_supplier_commit_reopens_and_recovers_one_effect(self):
        record, intent = self.prepare()
        child, _ = self.child(record, mode="exit", point="mutation_worker.after_supplier_success")
        with child:
            self.assertEqual(child.wait(timeout=10).returncode, 71)
            self.assertEqual(child.output_tail("stdout"), "")
        self.assertEqual(self.read(record).state, EffectState.DISPATCHED)
        self.assertEqual(self.run_one(record).result, self.supplier.lookup(intent).result)
        self.assert_counts(self.supplier, applied=1, calls=1)
        self.assert_completion(record, intent)

    def test_noncooperating_ambiguous_success_is_uncertain_and_never_blindly_resent(self):
        supplier = self.noncooperating()
        record, intent = self.prepare(supplier=supplier)
        child, _ = self.child(
            record, supplier=supplier, mode="exit", point="mutation_worker.after_supplier_success"
        )
        with child:
            self.assertEqual(child.wait(timeout=10).returncode, 71)
        self.assert_counts(supplier, applied=1, calls=1)
        replacement, _ = self.child(record, supplier=supplier)
        with replacement:
            self.assertEqual(self.finished(replacement)["state"], "uncertain")
        value = self.read(record)
        self.assertEqual(
            (value.state, value.error_code, value.result),
            (EffectState.UNCERTAIN, EffectFailure.AMBIGUOUS_OUTCOME, None),
        )
        self.assertEqual(self.run_one(record, supplier=supplier), value)
        self.assert_counts(supplier, applied=1, calls=1)
        self.assert_completion(record, intent)

    def test_noncooperating_pre_reservation_crash_is_provably_unsent_and_can_progress(self):
        supplier = self.noncooperating()
        record, _ = self.prepare(supplier=supplier)
        child, _ = self.child(
            record, supplier=supplier, mode="exit", point="mutation_worker.after_claim"
        )
        with child:
            self.assertEqual(child.wait(timeout=10).returncode, 71)
        value = self.read(record)
        self.assertEqual((value.state, value.dispatch_count), (EffectState.CLAIMED, 0))
        self.assert_counts(supplier, applied=0, calls=0)
        replacement, _ = self.child(record, supplier=supplier)
        with replacement:
            self.assertEqual(self.finished(replacement)["state"], "succeeded")
        self.assertEqual((self.read(record).attempt_no, self.read(record).dispatch_count), (2, 1))
        self.assert_counts(supplier, applied=1, calls=1)

    def test_noncooperating_reserved_but_uncalled_crash_stays_uncertain_without_resend(self):
        supplier = self.noncooperating()
        record, _ = self.prepare(supplier=supplier)
        child, _ = self.child(
            record, supplier=supplier, mode="exit", point="mutation_worker.after_dispatch_reserved"
        )
        with child:
            self.assertEqual(child.wait(timeout=10).returncode, 71)
        self.assertEqual(self.read(record).dispatch_count, 1)
        self.assert_counts(supplier, applied=0, calls=0)
        self.assertEqual(self.run_one(record, supplier=supplier).state, EffectState.UNCERTAIN)
        self.assert_counts(supplier, applied=0, calls=0)

    def test_cooperating_reserved_but_uncalled_crash_uses_absence_then_same_effect_retry(self):
        record, intent = self.prepare()
        child, _ = self.child(record, mode="exit", point="mutation_worker.after_dispatch_reserved")
        with child:
            self.assertEqual(child.wait(timeout=10).returncode, 71)
        self.assertIsNone(self.supplier.lookup(intent))
        self.assert_counts(self.supplier, applied=0, calls=0)
        self.assertEqual(self.run_one(record).state, EffectState.SUCCEEDED)
        value = self.read(record)
        self.assertEqual((value.attempt_no, value.dispatch_count), (2, 2))
        self.assertEqual(value.result.effect_id, intent.effect_id)
        self.assert_counts(self.supplier, applied=1, calls=1)

    def test_wrong_configured_provider_consumes_no_attempt_and_valid_target_progresses(self):
        record, _ = self.prepare()
        other_db = self.folder / "other_supplier.sqlite3"
        initialize_mutation_supplier(other_db, scope_id=ACTOR.scope_id)
        other = MutationSupplier(other_db, clock=self.clock)
        with self.assertRaises(UnsupportedOperation):
            self.run_one(record, supplier=other)
        self.assertIsNone(self.read(record))
        self.assert_counts(other, applied=0, calls=0)
        self.assert_counts(self.supplier, applied=0, calls=0)
        self.assertEqual(self.run_one(record).state, EffectState.SUCCEEDED)

    def test_absent_altered_stale_and_expired_confirmation_make_zero_supplier_apply_calls(self):
        record, quote = self.prepare(commit=False)
        with self.assertRaises(InvalidConfirmation):
            self.cases.commit_intent(actor=ACTOR, confirmation=None, command_id="absent")
        for name, changes in (
            ("amount", {"amount_minor": quote.amount_minor + 1}),
            ("supplier", {"supplier_id": str(uuid4())}),
            ("supplier-revision", {"expected_supplier_revision": 1}),
            ("case", {"case_id": str(uuid4())}),
        ):
            with self.subTest(name=name), self.assertRaises(InvalidConfirmation):
                self.cases.commit_intent(
                    actor=ACTOR,
                    confirmation=Confirmation(replace(quote, **changes), True),
                    command_id="changed-" + name,
                )
        with self.assertRaises(UnsupportedOperation):
            self.run_one(record)
        self.cases.revise(
            actor=ACTOR,
            task_id=record.task_id,
            expected_revision=0,
            request=BookingChange(BOOKING, date(2030, 12, 11), True),
        )
        with self.assertRaises(StaleRevision):
            self.cases.commit_intent(
                actor=ACTOR, confirmation=Confirmation(quote, True), command_id="stale"
            )
        expired_record, expired_quote = self.prepare("expired", commit=False)
        self.clock.value = datetime.fromisoformat(expired_quote.expires_at)
        with self.assertRaises(QuoteExpired):
            self.cases.commit_intent(
                actor=ACTOR, confirmation=Confirmation(expired_quote, True), command_id="expired"
            )
        with self.assertRaises(UnsupportedOperation):
            self.run_one(expired_record)
        self.assert_counts(self.supplier, applied=0, calls=0)
        valid, _ = self.prepare("valid-after-invalid")
        self.assertEqual(self.run_one(valid).state, EffectState.SUCCEEDED)
        self.assert_counts(self.supplier, applied=1, calls=1)

    def test_same_revision_conflict_is_explicit_and_other_work_still_progresses(self):
        first, _ = self.prepare("one")
        stale, _ = self.prepare("two")
        self.assertEqual(self.run_one(first).state, EffectState.SUCCEEDED)
        rejected = self.run_one(stale)
        self.assertEqual(
            (rejected.state, rejected.error_code),
            (EffectState.FAILED, EffectFailure.SUPPLIER_REJECTED),
        )
        fresh, _ = self.prepare("three")
        self.assertEqual(self.run_one(fresh).state, EffectState.SUCCEEDED)
        self.assert_counts(self.supplier, applied=2, calls=3)

    def test_quote_expiry_after_commit_does_not_revoke_accepted_intent(self):
        record, intent = self.prepare()
        self.clock.value = datetime.fromisoformat(intent.quote.expires_at)
        self.assertEqual(self.run_one(record).state, EffectState.SUCCEEDED)
        self.assert_counts(self.supplier, applied=1, calls=1)

    def test_deadline_before_dispatch_prevents_supplier_call(self):
        deadline = NOW + timedelta(seconds=20)
        record, _ = self.prepare(deadline=deadline)
        self.clock.value = deadline
        value = self.run_one(record)
        self.assertEqual(
            (value.state, value.error_code, value.dispatch_count),
            (EffectState.FAILED, EffectFailure.DEADLINE_EXPIRED, 0),
        )
        self.assert_counts(self.supplier, applied=0, calls=0)

    def test_cancellation_before_dispatch_prevents_supplier_call(self):
        record, _ = self.prepare()
        self.effects.cancel(actor=ACTOR, task_id=record.task_id, command_id="cancel")
        self.assertEqual(self.run_one(record).state, EffectState.CANCELLED)
        self.assert_counts(self.supplier, applied=0, calls=0)

    def test_known_supplier_success_wins_late_cancel_and_deadline(self):
        record, intent = self.prepare()
        child, _ = self.child(record, mode="exit", point="mutation_worker.after_supplier_success")
        with child:
            self.assertEqual(child.wait(timeout=10).returncode, 71)
        known = self.supplier.lookup(intent).result
        self.clock.value += timedelta(hours=1)
        self.effects.cancel(actor=ACTOR, task_id=record.task_id, command_id="cancel-after")
        value = self.run_one(record)
        self.assertEqual((value.state, value.result), (EffectState.SUCCEEDED, known))
        self.assert_counts(self.supplier, applied=1, calls=1)
        self.assert_completion(record, intent)

    def test_fresh_inquiry_unavailability_is_retryable_without_dispatch(self):
        class Unavailable(MutationSupplier):
            def lookup(self, intent):
                raise MutationUnavailable("SECRET_SENTINEL")

        record, _ = self.prepare()
        supplier = Unavailable(self.database, clock=self.clock)
        value = self.run_one(record, supplier=supplier)
        self.assertEqual(
            (value.state, value.dispatch_count, value.error_code),
            (EffectState.PENDING, 0, EffectFailure.DEPENDENCY_UNAVAILABLE),
        )
        self.assert_counts(self.supplier, applied=0, calls=0)
        self.assertEqual(len(self.rows("completion_events", record.task_id)), 0)
        self.assertEqual(self.run_one(record).state, EffectState.SUCCEEDED)
        self.assertEqual(self.read(record).attempt_no, 2)

    def test_lost_apply_response_is_reconciled_in_same_invocation_without_resend(self):
        class LostResponse(MutationSupplier):
            def apply(self, intent):
                super().apply(intent)
                raise MutationUnavailable("SECRET_SENTINEL")

        record, _ = self.prepare()
        value = self.run_one(record, supplier=LostResponse(self.database, clock=self.clock))
        self.assertEqual(value.state, EffectState.SUCCEEDED)
        self.assert_counts(self.supplier, applied=1, calls=1)

    def test_apply_unavailable_is_not_positive_no_dispatch_evidence(self):
        class Unavailable(MutationSupplier):
            def apply(self, intent):
                raise MutationUnavailable("SECRET_SENTINEL")

        record, _ = self.prepare()
        with self.assertRaises(MutationUnavailable):
            self.run_one(record, supplier=Unavailable(self.database, clock=self.clock))
        self.assertEqual(
            (self.read(record).state, self.read(record).dispatch_count), (EffectState.DISPATCHED, 1)
        )
        self.assertEqual(len(self.rows("completion_events", record.task_id)), 0)
        self.assertEqual(self.run_one(record).state, EffectState.SUCCEEDED)
        self.assert_counts(self.supplier, applied=1, calls=1)

    def test_unexpected_defect_retains_reservation_then_reconciliation_progresses(self):
        class Crashed(MutationSupplier):
            def apply(self, intent):
                super().apply(intent)
                raise RuntimeError("SECRET_SENTINEL")

        record, _ = self.prepare()
        with (
            self.assertRaises(RuntimeError),
            self.assertLogs("continuity_lab.mutation_worker", level="INFO") as captured,
        ):
            self.run_one(record, supplier=Crashed(self.database, clock=self.clock))
        self.assertNotIn("SECRET_SENTINEL", "\n".join(captured.output))
        self.assertEqual(self.read(record).state, EffectState.DISPATCHED)
        self.assertEqual(self.run_one(record).state, EffectState.SUCCEEDED)
        self.assert_counts(self.supplier, applied=1, calls=1)

    def test_dispatch_reservation_checks_current_cancel_and_cannot_be_repeated(self):
        record, _ = self.prepare()
        claim = self.effects.claim(scope_id=ACTOR.scope_id, task_id=record.task_id)
        self.assertTrue(self.effects.prepare_dispatch(claim, absence_confirmed=True))
        with self.assertRaises(TransitionConflict):
            self.effects.prepare_dispatch(claim, absence_confirmed=True)
        self.assertEqual(self.read(record).dispatch_count, 1)
        second, _ = self.prepare("cancel-between")
        second_claim = self.effects.claim(scope_id=ACTOR.scope_id, task_id=second.task_id)
        self.effects.cancel(actor=ACTOR, task_id=second.task_id, command_id="cancel-claim")
        with self.assertRaises(TransitionConflict):
            self.effects.prepare_dispatch(second_claim, absence_confirmed=True)
        self.assertEqual(self.read(second).state, EffectState.CANCELLED)
        self.assert_counts(self.supplier, applied=0, calls=0)

    def test_supplier_calls_can_acquire_admission_because_worker_holds_no_transaction(self):
        executions = self.executions
        probes = []

        class Checked(MutationSupplier):
            def lookup(self, intent):
                with protected_transaction(executions) as connection:
                    connection.execute("SELECT 1")
                probes.append("lookup")
                return super().lookup(intent)

            def apply(self, intent):
                with protected_transaction(executions) as connection:
                    connection.execute("SELECT 1")
                probes.append("apply")
                return super().apply(intent)

        record, _ = self.prepare()
        self.assertEqual(
            self.run_one(record, supplier=Checked(self.database, clock=self.clock)).state,
            EffectState.SUCCEEDED,
        )
        self.assertEqual(probes, ["lookup", "apply"])
        self.assert_counts(self.supplier, applied=1, calls=1)

    def test_live_session_worker_slot_blocks_second_worker_without_stealing_claim(self):
        record, _ = self.prepare()
        child, barrier = self.child(record, mode="barrier", point="mutation_worker.after_claim")
        with child:
            child.wait_for_barrier(barrier, timeout=10)
            before = self.read(record)
            self.assertEqual((before.state, before.attempt_no), (EffectState.CLAIMED, 1))
            with self.assertRaises(ExecutionCapacityExceeded):
                self.run_one(record)
            self.assertEqual(self.read(record), before)
            self.assert_counts(self.supplier, applied=0, calls=0)
            child.release_barrier(barrier)
            self.assertEqual(self.finished(child)["state"], "succeeded")
        self.assert_counts(self.supplier, applied=1, calls=1)


if __name__ == "__main__":
    unittest.main()
