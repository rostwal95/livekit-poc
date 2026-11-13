"""Explicit real PostgreSQL dormant waits, finite retries and process recovery."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from psycopg import sql

from continuity_lab.authorization import AuthenticatedActor
from continuity_lab.case_models import Confirmation, QuoteSnapshot
from continuity_lab.execution_cli import _SafeFormatter
from continuity_lab.execution_models import ExecutionNotFound, ExecutionStatus, UnsupportedOperation
from continuity_lab.lifecycle_models import LifecycleState, WaitState
from continuity_lab.managed_inquiry_worker import InquiryNotDispatched, ManagedInquiryWorker
from continuity_lab.models import BookingChange, IdempotencyConflict
from continuity_lab.postgres_case import PostgresCaseAuthority
from continuity_lab.postgres_lifecycle import PostgresLifecycle
from continuity_lab.postgres_migrations import install_schema, upgrade_v2
from continuity_lab.postgres_settings import PostgresSettings
from continuity_lab.postgres_store import PostgresExecutionStore
from continuity_lab.retry_policy import RetryError, RetryPolicy
from continuity_lab.supplier import (
    FakeSupplier,
    SupplierRejected,
    SupplierUnavailable,
    initialize_supplier,
)

NOW = datetime(2030, 12, 1, tzinfo=UTC)
ACTOR = AuthenticatedActor("traveller-a", "account-a")
REQUEST = BookingChange("DEMO-BK-001", date(2030, 12, 10), True)


class Clock:
    def __init__(self, value=NOW):
        self.value = value

    def __call__(self):
        return self.value


class PostgresLifecycleCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("P1_RUN_POSTGRES_TESTS") != "1":
            raise RuntimeError("Real lifecycle lane requires explicit local PostgreSQL setup")
        cls.runtime_base = PostgresSettings.from_env()
        cls.migration_base = PostgresSettings.from_env("P1_MIGRATION_")

    def setUp(self):
        self.schema = "p1_lifecycle_" + uuid4().hex
        self.migration = replace(self.migration_base, schema=self.schema)
        self.runtime = replace(self.runtime_base, schema=self.schema)
        self.addCleanup(self.drop_schema)
        install_schema(self.migration)
        with closing(self.migration.connect(application_name="continuity-migrate")) as connection:
            connection.execute(
                sql.SQL(
                    "UPDATE {} SET state='active',migration_id=%s,source_digest=%s WHERE singleton"
                ).format(sql.Identifier(self.schema, "schema_metadata")),
                (str(uuid4()), "0" * 64),
            )
        upgrade_v2(self.migration)
        self.clock = Clock()
        self.executions = PostgresExecutionStore(self.runtime, clock=self.clock)
        self.cases = PostgresCaseAuthority(self.executions, clock=self.clock)
        self.lifecycle = PostgresLifecycle(self.executions, cases=self.cases, clock=self.clock)
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.supplier_database = Path(self.directory.name) / "supplier.sqlite3"
        initialize_supplier(self.supplier_database, scope_id=ACTOR.scope_id)
        self.supplier = FakeSupplier(self.supplier_database)
        self.before = self.supplier.booking(
            scope_id=ACTOR.scope_id, booking_reference=REQUEST.booking_reference
        )

    def drop_schema(self):
        if (
            not self.schema.startswith("p1_lifecycle_")
            or len(self.schema) != len("p1_lifecycle_") + 32
        ):
            raise AssertionError("Only the isolated owned lifecycle schema may be removed")
        with closing(self.migration.connect(application_name="continuity-migrate")) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(self.schema))
            )

    def accept(self, key="one", policy=None, deadline=None):
        value = self.executions.submit(
            scope_id=ACTOR.scope_id, idempotency_key=key, request=REQUEST
        ).execution
        self.lifecycle.manage(
            scope_id=ACTOR.scope_id,
            task_id=value.task_id,
            policy=RetryPolicy() if policy is None else policy,
            deadline=self.clock() + timedelta(minutes=2) if deadline is None else deadline,
        )
        return value

    def worker(self, supplier=None, failpoint=None):
        return ManagedInquiryWorker(
            self.lifecycle, self.supplier if supplier is None else supplier, failpoint=failpoint
        )

    def run_one(self, record, supplier=None):
        return self.worker(supplier).run_one(scope_id=ACTOR.scope_id, task_id=record.task_id)

    def prepare_quote(self):
        record = self.accept()
        self.assertEqual(self.run_one(record).state, LifecycleState.INQUIRY_COMPLETE)
        case = self.cases.enroll(actor=ACTOR, task_id=record.task_id)
        quote = QuoteSnapshot(
            str(uuid4()),
            record.task_id,
            case.revision,
            REQUEST.booking_reference,
            REQUEST.new_check_in,
            1250,
            "USD",
            (self.clock() + timedelta(seconds=60)).isoformat(),
        )
        self.cases.publish_quote(actor=ACTOR, quote=quote)
        return record, quote

    def arm(self, record, quote):
        return self.lifecycle.arm_wait(
            actor=ACTOR,
            task_id=record.task_id,
            wait_id=str(uuid4()),
            quote=quote,
            deadline=self.clock() + timedelta(seconds=50),
        )

    def assert_booking_unchanged(self):
        self.assertEqual(
            self.supplier.booking(
                scope_id=ACTOR.scope_id, booking_reference=REQUEST.booking_reference
            ),
            self.before,
        )

    def test_normal_managed_inquiry_and_terminal_replay_preserve_effect_and_booking(self):
        record = self.accept()
        first = self.run_one(record)
        self.assertEqual(first.state, LifecycleState.INQUIRY_COMPLETE)
        self.assertEqual(self.run_one(record), first)
        self.assertEqual(
            len(self.executions.attempts(scope_id=ACTOR.scope_id, task_id=record.task_id)), 1
        )
        self.assertEqual(self.supplier.count_inquiries(scope_id=ACTOR.scope_id), 1)
        self.assertEqual(
            self.executions.get(scope_id=ACTOR.scope_id, task_id=record.task_id).effect_id,
            record.effect_id,
        )
        self.assert_booking_unchanged()

    def test_transient_predispatch_retries_only_when_due_then_makes_useful_progress(self):
        class OnceNotDispatched(FakeSupplier):
            calls = 0

            def inquire(self, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    raise InquiryNotDispatched("SECRET_SENTINEL")
                return super().inquire(**kwargs)

        supplier = OnceNotDispatched(self.supplier_database)
        record = self.accept()
        first = self.run_one(record, supplier)
        self.assertEqual(
            (first.state, first.next_attempt_at),
            (LifecycleState.RETRY_WAIT, (NOW + timedelta(seconds=1)).isoformat()),
        )
        self.assertEqual(self.run_one(record, supplier), first)
        self.assertEqual(supplier.calls, 1)
        self.clock.value += timedelta(seconds=1)
        self.assertEqual(self.run_one(record, supplier).state, LifecycleState.INQUIRY_COMPLETE)
        attempts = self.executions.attempts(scope_id=ACTOR.scope_id, task_id=record.task_id)
        self.assertEqual([row.status.value for row in attempts], ["failed", "succeeded"])
        self.assertEqual(self.supplier.count_inquiries(scope_id=ACTOR.scope_id), 1)
        self.assert_booking_unchanged()

    def test_permanent_rejection_and_retry_exhaustion_stop_with_finite_attempts(self):
        class Rejected(FakeSupplier):
            def inquire(self, **kwargs):
                raise SupplierRejected("SECRET_SENTINEL")

        permanent = self.accept("permanent")
        result = self.run_one(permanent, Rejected(self.supplier_database))
        self.assertEqual(
            (result.state, result.error_code), (LifecycleState.FAILED, RetryError.PERMANENT_FAILURE)
        )
        self.assertEqual(self.run_one(permanent, Rejected(self.supplier_database)), result)

        class NotSent(FakeSupplier):
            def inquire(self, **kwargs):
                raise InquiryNotDispatched("SECRET_SENTINEL")

        exhausted = self.accept("exhausted", RetryPolicy(2, 1, 5))
        self.assertEqual(
            self.run_one(exhausted, NotSent(self.supplier_database)).state,
            LifecycleState.RETRY_WAIT,
        )
        self.clock.value += timedelta(seconds=1)
        result = self.run_one(exhausted, NotSent(self.supplier_database))
        self.assertEqual(
            (result.state, result.error_code), (LifecycleState.FAILED, RetryError.RETRY_EXHAUSTED)
        )
        self.assertEqual(
            len(self.executions.attempts(scope_id=ACTOR.scope_id, task_id=exhausted.task_id)), 2
        )
        self.assertEqual(self.supplier.count_inquiries(scope_id=ACTOR.scope_id), 0)

    def test_deadline_prevents_dispatch_without_inventing_an_attempt(self):
        record = self.accept(deadline=NOW + timedelta(seconds=1))
        self.clock.value += timedelta(seconds=1)
        value = self.run_one(record)
        self.assertEqual(
            (value.state, value.error_code), (LifecycleState.FAILED, RetryError.DEADLINE_EXPIRED)
        )
        self.assertEqual(
            self.executions.attempts(scope_id=ACTOR.scope_id, task_id=record.task_id), ()
        )
        self.assertEqual(self.supplier.count_inquiries(scope_id=ACTOR.scope_id), 0)

    def test_ambiguous_dispatch_remains_uncertain_and_never_resends(self):
        class Ambiguous(FakeSupplier):
            calls = 0

            def inquire(self, **kwargs):
                self.calls += 1
                super().inquire(**kwargs)
                raise SupplierUnavailable("SECRET_SENTINEL")

        supplier = Ambiguous(self.supplier_database)
        record = self.accept()
        value = self.run_one(record, supplier)
        self.assertEqual(
            (value.state, value.error_code),
            (LifecycleState.UNCERTAIN, RetryError.AMBIGUOUS_OUTCOME),
        )
        self.clock.value += timedelta(days=1)
        self.assertEqual(self.run_one(record, supplier), value)
        self.assertEqual(supplier.calls, 1)
        self.assertEqual(
            self.executions.get(scope_id=ACTOR.scope_id, task_id=record.task_id).status,
            ExecutionStatus.RUNNING,
        )
        self.assertEqual(self.supplier.count_inquiries(scope_id=ACTOR.scope_id), 1)
        self.assert_booking_unchanged()

    def test_unexpected_defect_leaves_attempt_recoverable_and_does_not_render_private_text(self):
        class PrivateFailure(RuntimeError):
            def __str__(self):
                raise AssertionError("Private exception text must not be read")

            def __repr__(self):
                raise AssertionError("Private exception representation must not be read")

        record = self.accept()

        def fail(_):
            raise PrivateFailure()

        with (
            self.assertLogs("continuity_lab.managed_inquiry_worker", level="ERROR") as logs,
            self.assertRaises(PrivateFailure),
        ):
            self.worker(failpoint=fail).run_one(scope_id=ACTOR.scope_id, task_id=record.task_id)
        rendered = "".join(_SafeFormatter().format(row) for row in logs.records)
        self.assertNotIn("SECRET_SENTINEL", rendered)
        self.assertEqual(
            self.lifecycle.get(scope_id=ACTOR.scope_id, task_id=record.task_id).state,
            LifecycleState.RUNNING,
        )
        self.assertEqual(self.run_one(record).state, LifecycleState.INQUIRY_COMPLETE)
        self.assertEqual(self.supplier.count_inquiries(scope_id=ACTOR.scope_id), 1)
        self.assert_booking_unchanged()

    def test_fresh_lookup_failure_can_retry_but_recovery_lookup_failure_is_uncertain(self):
        class NoLookup(FakeSupplier):
            def lookup(self, **kwargs):
                raise SupplierUnavailable("SECRET_SENTINEL")

        fresh = self.accept("fresh")
        self.assertEqual(
            self.run_one(fresh, NoLookup(self.supplier_database)).state, LifecycleState.RETRY_WAIT
        )
        recovering = self.accept("recovering")
        with self.executions.worker_slot():
            self.lifecycle.claim_due(scope_id=ACTOR.scope_id, task_id=recovering.task_id)
        self.assertEqual(
            self.run_one(recovering, NoLookup(self.supplier_database)).state,
            LifecycleState.UNCERTAIN,
        )
        self.assertEqual(self.supplier.count_inquiries(scope_id=ACTOR.scope_id), 0)

    def test_managed_policy_replay_does_not_extend_deadline_or_erase_retention(self):
        record = self.accept()
        first = self.lifecycle.get(scope_id=ACTOR.scope_id, task_id=record.task_id)
        self.assertEqual(
            self.lifecycle.manage(
                scope_id=ACTOR.scope_id,
                task_id=record.task_id,
                policy=first.policy,
                deadline=datetime.fromisoformat(first.deadline),
            ),
            first,
        )
        with self.assertRaises(IdempotencyConflict):
            self.lifecycle.manage(
                scope_id=ACTOR.scope_id,
                task_id=record.task_id,
                policy=first.policy,
                deadline=NOW + timedelta(days=1),
            )
        with self.assertRaises(UnsupportedOperation):
            self.executions.start_attempt(
                scope_id=ACTOR.scope_id, task_id=record.task_id, expected_version=record.version
            )
        self.assertEqual(self.run_one(record).state, LifecycleState.INQUIRY_COMPLETE)

    def test_early_signal_survives_new_owner_and_advances_once_after_wait(self):
        record, quote = self.prepare_quote()
        signal = self.lifecycle.signal(
            actor=ACTOR, event_id="early", confirmation=Confirmation(quote, True)
        )
        self.assertTrue(signal.created)
        self.assertEqual(
            self.lifecycle.advance(actor=ACTOR, task_id=record.task_id).lifecycle.state,
            LifecycleState.INQUIRY_COMPLETE,
        )
        wait = self.arm(record, quote)
        fresh = PostgresLifecycle(
            PostgresExecutionStore(self.runtime, clock=self.clock), clock=self.clock
        )
        result = fresh.advance(actor=ACTOR, task_id=record.task_id)
        self.assertEqual(result.lifecycle.state, LifecycleState.INTENT_COMMITTED)
        self.assertEqual(result.intent.quote, quote)
        self.assertEqual(fresh.advance(actor=ACTOR, task_id=record.task_id).intent, result.intent)
        replay = fresh.signal(actor=ACTOR, event_id="early", confirmation=Confirmation(quote, True))
        self.assertEqual(
            (replay.created, replay.signal_id, replay.consumed_wait_id),
            (False, signal.signal_id, wait.wait_id),
        )
        self.assertEqual(len(self.cases.dispatches(actor=ACTOR, task_id=record.task_id)), 1)
        self.assert_booking_unchanged()

    def test_late_signal_concurrent_consumers_commit_one_intent_and_dispatch(self):
        record, quote = self.prepare_quote()
        self.arm(record, quote)
        self.lifecycle.signal(actor=ACTOR, event_id="late", confirmation=Confirmation(quote, True))
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(
                pool.map(
                    lambda _: self.lifecycle.advance(actor=ACTOR, task_id=record.task_id), range(4)
                )
            )
        self.assertEqual(len({row.intent.intent_id for row in results}), 1)
        self.assertEqual(len(self.cases.dispatches(actor=ACTOR, task_id=record.task_id)), 1)
        self.assertEqual(
            self.lifecycle.waits(actor=ACTOR, task_id=record.task_id)[0].state, WaitState.CONSUMED
        )

    def test_signal_replay_conflict_and_unrelated_quote_cannot_advance(self):
        record, quote = self.prepare_quote()
        self.arm(record, quote)
        unrelated = replace(quote, quote_id=str(uuid4()), amount_minor=9999)
        first = self.lifecycle.signal(
            actor=ACTOR, event_id="wrong", confirmation=Confirmation(unrelated, True)
        )
        self.assertTrue(first.created)
        with self.assertRaises(IdempotencyConflict):
            self.lifecycle.signal(
                actor=ACTOR, event_id="wrong", confirmation=Confirmation(quote, True)
            )
        self.assertEqual(
            self.lifecycle.advance(actor=ACTOR, task_id=record.task_id).lifecycle.state,
            LifecycleState.WAITING,
        )
        self.assertEqual(self.cases.dispatches(actor=ACTOR, task_id=record.task_id), ())
        self.lifecycle.signal(actor=ACTOR, event_id="right", confirmation=Confirmation(quote, True))
        self.assertEqual(
            self.lifecycle.advance(actor=ACTOR, task_id=record.task_id).lifecycle.state,
            LifecycleState.INTENT_COMMITTED,
        )

    def test_stale_case_revision_cannot_consume_old_confirmation(self):
        record, quote = self.prepare_quote()
        self.arm(record, quote)
        self.lifecycle.signal(actor=ACTOR, event_id="old", confirmation=Confirmation(quote, True))
        self.cases.revise(
            actor=ACTOR,
            task_id=record.task_id,
            expected_revision=quote.revision,
            request=BookingChange(REQUEST.booking_reference, date(2030, 12, 11), True),
        )
        # Revision atomically withdraws the stale wait, leaving the fresh case
        # eligible for a new proposal without consuming the old signal.
        value = self.lifecycle.advance(actor=ACTOR, task_id=record.task_id)
        self.assertIsNone(value.intent)
        self.assertEqual(value.lifecycle.state, LifecycleState.INQUIRY_COMPLETE)
        self.assertEqual(self.cases.dispatches(actor=ACTOR, task_id=record.task_id), ())
        self.assertEqual(
            self.lifecycle.waits(actor=ACTOR, task_id=record.task_id)[0].state, WaitState.EXPIRED
        )
        receipt = self.lifecycle.signal(
            actor=ACTOR, event_id="old", confirmation=Confirmation(quote, True)
        )
        self.assertFalse(receipt.created)
        self.assertIsNone(receipt.consumed_wait_id)

    def test_wait_deadline_is_effective_after_restart_even_with_received_signal(self):
        record, quote = self.prepare_quote()
        self.arm(record, quote)
        self.lifecycle.signal(
            actor=ACTOR, event_id="before-expiry", confirmation=Confirmation(quote, True)
        )
        self.clock.value += timedelta(seconds=50)
        fresh = PostgresLifecycle(
            PostgresExecutionStore(self.runtime, clock=self.clock), clock=self.clock
        )
        value = fresh.advance(actor=ACTOR, task_id=record.task_id)
        self.assertEqual(
            (value.lifecycle.state, value.lifecycle.error_code),
            (LifecycleState.FAILED, RetryError.DEADLINE_EXPIRED),
        )
        self.assertIsNone(value.intent)
        self.assertEqual(
            fresh.waits(actor=ACTOR, task_id=record.task_id)[0].state, WaitState.EXPIRED
        )
        self.assertEqual(self.cases.dispatches(actor=ACTOR, task_id=record.task_id), ())

    def test_direct_commit_wins_over_later_wait_expiry_without_false_reversal(self):
        record, quote = self.prepare_quote()
        self.arm(record, quote)
        intent = self.cases.commit_intent(
            actor=ACTOR, confirmation=Confirmation(quote, True), command_id="direct"
        )
        self.clock.value += timedelta(minutes=5)
        value = self.lifecycle.advance(actor=ACTOR, task_id=record.task_id)
        self.assertEqual(value.lifecycle.state, LifecycleState.INTENT_COMMITTED)
        self.assertEqual(value.intent, intent)
        self.assertEqual(
            self.lifecycle.waits(actor=ACTOR, task_id=record.task_id)[0].state, WaitState.CONSUMED
        )

    def test_cross_scope_wait_signal_and_history_are_unavailable_without_mutation(self):
        record, quote = self.prepare_quote()
        other = AuthenticatedActor("traveller-b", "account-b")
        for operation in (
            lambda: self.lifecycle.waits(actor=other, task_id=record.task_id),
            lambda: self.lifecycle.signal(
                actor=other, event_id="forged", confirmation=Confirmation(quote, True)
            ),
            lambda: self.lifecycle.advance(actor=other, task_id=record.task_id),
            lambda: self.lifecycle.arm_wait(
                actor=other,
                task_id=record.task_id,
                wait_id=str(uuid4()),
                quote=quote,
                deadline=NOW + timedelta(seconds=30),
            ),
        ):
            with self.assertRaises(ExecutionNotFound):
                operation()
        self.assertEqual(
            self.lifecycle.get(scope_id=ACTOR.scope_id, task_id=record.task_id).state,
            LifecycleState.INQUIRY_COMPLETE,
        )
        self.assertEqual(self.cases.dispatches(actor=ACTOR, task_id=record.task_id), ())

    def test_lost_signal_and_advance_acknowledgement_replay_original_receipts(self):
        record, quote = self.prepare_quote()
        self.arm(record, quote)

        def stop(name):
            if name == "lifecycle.after_signal_commit":
                raise RuntimeError("controlled interruption")

        owner = PostgresLifecycle(
            self.executions, cases=self.cases, clock=self.clock, failpoint=stop
        )
        with self.assertRaises(RuntimeError):
            owner.signal(actor=ACTOR, event_id="lost-ack", confirmation=Confirmation(quote, True))
        replay = self.lifecycle.signal(
            actor=ACTOR, event_id="lost-ack", confirmation=Confirmation(quote, True)
        )
        self.assertFalse(replay.created)

        def stop_advance(name):
            if name == "lifecycle.after_advance_commit":
                raise RuntimeError("controlled interruption")

        owner = PostgresLifecycle(
            self.executions, cases=self.cases, clock=self.clock, failpoint=stop_advance
        )
        with self.assertRaises(RuntimeError):
            owner.advance(actor=ACTOR, task_id=record.task_id)
        value = self.lifecycle.advance(actor=ACTOR, task_id=record.task_id)
        self.assertEqual(value.lifecycle.state, LifecycleState.INTENT_COMMITTED)
        self.assertEqual(len(self.cases.dispatches(actor=ACTOR, task_id=record.task_id)), 1)

    def test_precommit_advance_failure_rolls_back_intent_consumption_and_wait_together(self):
        record, quote = self.prepare_quote()
        self.arm(record, quote)
        self.lifecycle.signal(
            actor=ACTOR, event_id="rollback", confirmation=Confirmation(quote, True)
        )

        def stop(name):
            if name == "lifecycle.before_advance_commit":
                raise RuntimeError("controlled interruption")

        owner = PostgresLifecycle(
            self.executions, cases=self.cases, clock=self.clock, failpoint=stop
        )
        with self.assertRaises(RuntimeError):
            owner.advance(actor=ACTOR, task_id=record.task_id)
        self.assertIsNone(self.cases.get(actor=ACTOR, task_id=record.task_id).intent)
        self.assertEqual(
            self.lifecycle.waits(actor=ACTOR, task_id=record.task_id)[0].state, WaitState.PENDING
        )
        self.assertEqual(
            self.lifecycle.advance(actor=ACTOR, task_id=record.task_id).lifecycle.state,
            LifecycleState.INTENT_COMMITTED,
        )

    def test_actual_worker_process_exit_after_supplier_success_recovers_same_effect(self):
        record = self.accept()
        child = r"""
import os
from continuity_lab.postgres_settings import PostgresSettings
from continuity_lab.postgres_store import PostgresExecutionStore
from continuity_lab.postgres_lifecycle import PostgresLifecycle
from continuity_lab.managed_inquiry_worker import ManagedInquiryWorker
from continuity_lab.supplier import FakeSupplier
from datetime import datetime
lifecycle=PostgresLifecycle(PostgresExecutionStore(PostgresSettings.from_env()),clock=lambda:datetime.fromisoformat(os.environ['FIXTURE_NOW']))
def stop(name):
 if name=='managed_worker.after_supplier_success':os._exit(71)
ManagedInquiryWorker(lifecycle,FakeSupplier(os.environ['SUPPLIER_DATABASE']),failpoint=stop).run_one(scope_id='account-a',task_id=os.environ['FIXTURE_TASK'])
"""
        environment = {
            key: value for key, value in os.environ.items() if not key.startswith("P1_MIGRATION_")
        }
        environment.update(
            {
                "P1_POSTGRES_SCHEMA": self.schema,
                "FIXTURE_TASK": record.task_id,
                "SUPPLIER_DATABASE": str(self.supplier_database),
                "FIXTURE_NOW": NOW.isoformat(),
            }
        )
        result = subprocess.run(
            [sys.executable, "-c", child],
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(result.returncode, 71, result.stderr)
        self.assertEqual(self.supplier.count_inquiries(scope_id=ACTOR.scope_id), 1)
        self.assertEqual(self.run_one(record).state, LifecycleState.INQUIRY_COMPLETE)
        self.assertEqual(self.supplier.count_inquiries(scope_id=ACTOR.scope_id), 1)
        self.assertEqual(
            self.executions.get(scope_id=ACTOR.scope_id, task_id=record.task_id).effect_id,
            record.effect_id,
        )
        self.assertEqual(
            [
                row.status.value
                for row in self.executions.attempts(scope_id=ACTOR.scope_id, task_id=record.task_id)
            ],
            ["interrupted", "succeeded"],
        )
        self.assert_booking_unchanged()

    def test_actual_process_retains_early_signal_and_wait_then_new_process_advances(self):
        record, quote = self.prepare_quote()
        child = r"""
import json,os
from datetime import datetime
from continuity_lab.authorization import AuthenticatedActor
from continuity_lab.case_models import Confirmation,parse_quote
from continuity_lab.postgres_settings import PostgresSettings
from continuity_lab.postgres_store import PostgresExecutionStore
from continuity_lab.postgres_lifecycle import PostgresLifecycle
lifecycle=PostgresLifecycle(PostgresExecutionStore(PostgresSettings.from_env()),clock=lambda:datetime.fromisoformat(os.environ['FIXTURE_NOW']))
actor=AuthenticatedActor('traveller-a','account-a')
quote=parse_quote(json.loads(os.environ['FIXTURE_QUOTE']))
if os.environ['FIXTURE_MODE']=='arm':
 lifecycle.signal(actor=actor,event_id='process-early',confirmation=Confirmation(quote,True))
 lifecycle.arm_wait(actor=actor,task_id=quote.task_id,wait_id=os.environ['FIXTURE_WAIT'],quote=quote,deadline=datetime.fromisoformat(os.environ['FIXTURE_DEADLINE']))
 os._exit(72)
result=lifecycle.advance(actor=actor,task_id=quote.task_id)
print(json.dumps({'state':result.lifecycle.state,'intent':None if result.intent is None else result.intent.intent_id}))
"""
        env = {
            key: value for key, value in os.environ.items() if not key.startswith("P1_MIGRATION_")
        }
        env.update(
            {
                "P1_POSTGRES_SCHEMA": self.schema,
                "FIXTURE_NOW": NOW.isoformat(),
                "FIXTURE_QUOTE": json.dumps(quote.payload()),
                "FIXTURE_WAIT": str(uuid4()),
                "FIXTURE_DEADLINE": (NOW + timedelta(seconds=50)).isoformat(),
                "FIXTURE_MODE": "arm",
            }
        )
        first = subprocess.run(
            [sys.executable, "-c", child],
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(first.returncode, 72, first.stderr)
        env["FIXTURE_MODE"] = "advance"
        second = subprocess.run(
            [sys.executable, "-c", child],
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(second.returncode, 0, second.stderr)
        value = json.loads(second.stdout)
        self.assertEqual(value["state"], LifecycleState.INTENT_COMMITTED)
        self.assertEqual(
            value["intent"], self.cases.get(actor=ACTOR, task_id=record.task_id).intent.intent_id
        )
        self.assertEqual(len(self.cases.dispatches(actor=ACTOR, task_id=record.task_id)), 1)

    def test_signal_capacity_rejects_new_receipts_but_preserves_replay_and_progress(self):
        from continuity_lab.execution_models import ExecutionCapacityExceeded

        record, quote = self.prepare_quote()
        self.arm(record, quote)
        owner = PostgresLifecycle(
            self.executions, cases=self.cases, clock=self.clock, maximum_signals=1
        )
        first = owner.signal(actor=ACTOR, event_id="kept", confirmation=Confirmation(quote, True))
        with self.assertRaises(ExecutionCapacityExceeded):
            owner.signal(actor=ACTOR, event_id="rejected", confirmation=Confirmation(quote, True))
        replay = owner.signal(actor=ACTOR, event_id="kept", confirmation=Confirmation(quote, True))
        self.assertEqual((replay.created, replay.signal_id), (False, first.signal_id))
        self.assertEqual(
            owner.advance(actor=ACTOR, task_id=record.task_id).lifecycle.state,
            LifecycleState.INTENT_COMMITTED,
        )

    def test_managed_policy_cannot_expand_the_configured_attempt_budget(self):
        record = self.executions.submit(
            scope_id=ACTOR.scope_id, idempotency_key="budget", request=REQUEST
        ).execution
        with self.assertRaises(ValueError):
            self.lifecycle.manage(
                scope_id=ACTOR.scope_id,
                task_id=record.task_id,
                policy=RetryPolicy(max_attempts=9),
                deadline=NOW + timedelta(minutes=1),
            )
        self.assertEqual(
            self.executions.get(scope_id=ACTOR.scope_id, task_id=record.task_id), record
        )

    def test_actual_process_restart_preserves_deadline_and_rejects_expired_wait_signal(self):
        record, quote = self.prepare_quote()
        child = r"""
import json,os
from datetime import datetime
from continuity_lab.authorization import AuthenticatedActor
from continuity_lab.case_models import Confirmation,parse_quote
from continuity_lab.postgres_settings import PostgresSettings
from continuity_lab.postgres_store import PostgresExecutionStore
from continuity_lab.postgres_lifecycle import PostgresLifecycle
lifecycle=PostgresLifecycle(PostgresExecutionStore(PostgresSettings.from_env()),clock=lambda:datetime.fromisoformat(os.environ['FIXTURE_NOW']))
actor=AuthenticatedActor('traveller-a','account-a')
quote=parse_quote(json.loads(os.environ['FIXTURE_QUOTE']))
if os.environ['FIXTURE_MODE']=='arm':
 lifecycle.signal(actor=actor,event_id='process-early',confirmation=Confirmation(quote,True))
 lifecycle.arm_wait(actor=actor,task_id=quote.task_id,wait_id=os.environ['FIXTURE_WAIT'],quote=quote,deadline=datetime.fromisoformat(os.environ['FIXTURE_DEADLINE']))
 os._exit(72)
result=lifecycle.advance(actor=actor,task_id=quote.task_id)
print(json.dumps({'state':result.lifecycle.state,'intent':None if result.intent is None else result.intent.intent_id}))
"""
        env = {
            key: value for key, value in os.environ.items() if not key.startswith("P1_MIGRATION_")
        }
        env.update(
            {
                "P1_POSTGRES_SCHEMA": self.schema,
                "FIXTURE_NOW": NOW.isoformat(),
                "FIXTURE_QUOTE": json.dumps(quote.payload()),
                "FIXTURE_WAIT": str(uuid4()),
                "FIXTURE_DEADLINE": (NOW + timedelta(seconds=50)).isoformat(),
                "FIXTURE_MODE": "arm",
            }
        )
        first = subprocess.run(
            [sys.executable, "-c", child],
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(first.returncode, 72, first.stderr)
        env["FIXTURE_MODE"] = "advance"
        env["FIXTURE_NOW"] = (NOW + timedelta(seconds=50)).isoformat()
        second = subprocess.run(
            [sys.executable, "-c", child],
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(second.returncode, 0, second.stderr)
        value = json.loads(second.stdout)
        self.assertEqual(value["state"], LifecycleState.FAILED)
        self.assertIsNone(value["intent"])
        self.assertIsNone(self.cases.get(actor=ACTOR, task_id=record.task_id).intent)
        self.assertEqual(self.cases.dispatches(actor=ACTOR, task_id=record.task_id), ())
        self.assertEqual(
            self.lifecycle.waits(actor=ACTOR, task_id=record.task_id)[0].state, WaitState.EXPIRED
        )

    def test_slow_lookup_cannot_dispatch_after_the_original_deadline(self):
        clock = self.clock

        class SlowLookup(FakeSupplier):
            dispatched = False

            def lookup(self, **kwargs):
                clock.value += timedelta(seconds=1)

            def inquire(self, **kwargs):
                self.dispatched = True
                raise AssertionError("Expired work must not dispatch")

        record = self.accept(deadline=NOW + timedelta(seconds=1))
        supplier = SlowLookup(self.supplier_database)
        value = self.run_one(record, supplier)
        self.assertEqual(
            (value.state, value.error_code), (LifecycleState.FAILED, RetryError.DEADLINE_EXPIRED)
        )
        self.assertFalse(supplier.dispatched)
        self.assertEqual(self.supplier.count_inquiries(scope_id=ACTOR.scope_id), 0)

    def test_corrupt_wait_payload_cannot_redirect_confirmation_to_another_execution(self):
        from continuity_lab.execution_models import InvalidStoredState

        record, quote = self.prepare_quote()
        wait = self.arm(record, quote)
        unrelated = replace(quote, task_id="different-execution")
        with closing(self.runtime.connect()) as connection:
            connection.execute(
                sql.SQL("UPDATE {} SET quote_json=%s WHERE wait_id=%s").format(
                    sql.Identifier(self.schema, "execution_waits")
                ),
                (
                    json.dumps(unrelated.payload(), sort_keys=True, separators=(",", ":")),
                    wait.wait_id,
                ),
            )
        with self.assertRaises(InvalidStoredState):
            self.lifecycle.waits(actor=ACTOR, task_id=record.task_id)
        with self.assertRaises(InvalidStoredState):
            self.lifecycle.advance(actor=ACTOR, task_id=record.task_id)
        self.assertEqual(self.cases.dispatches(actor=ACTOR, task_id=record.task_id), ())
