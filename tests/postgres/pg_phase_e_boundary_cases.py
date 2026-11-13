"""Real PostgreSQL root authority boundaries for supplier consent and cancellation."""

from __future__ import annotations

import os
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from psycopg import sql

from continuity_lab.authorization import AuthenticatedActor
from continuity_lab.case_models import Confirmation, InvalidConfirmation, QuoteSnapshot
from continuity_lab.effect_models import CancellationDisposition, EffectFailure, MutationResult
from continuity_lab.execution_models import (
    AttemptStatus,
    ExecutionStatus,
    InquiryResult,
    TransitionConflict,
    UnsupportedOperation,
)
from continuity_lab.lifecycle_models import LifecycleState, WaitState
from continuity_lab.models import BookingChange, IdempotencyConflict
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
from continuity_lab.retry_policy import FailureClass, RetryPolicy
from continuity_lab.transfer import make_snapshot

ACTOR = AuthenticatedActor("traveller-a", "account-a")
REQUEST = BookingChange("DEMO-BK-001", date(2030, 12, 10), True)
NOW = datetime(2030, 12, 1, tzinfo=UTC)
SUPPLIER_ID = "30000000-0000-0000-0000-000000000003"


class PhaseEBoundaryCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("P1_RUN_POSTGRES_TESTS") != "1":
            raise RuntimeError(
                "Phase E root boundary tests require explicit local PostgreSQL setup"
            )
        cls.runtime_base = PostgresSettings.from_env()
        cls.owner_base = PostgresSettings.from_env("P1_MIGRATION_")

    def setUp(self):
        self.schema = "p1_e_boundary_" + uuid4().hex
        self.runtime = replace(self.runtime_base, schema=self.schema)
        self.owner = replace(self.owner_base, schema=self.schema)
        self.addCleanup(self.drop_schema)
        snapshot = make_snapshot([], [], [], migration_id=str(uuid4()))
        install_schema(self.owner)
        stage_import(self.owner, snapshot)
        activate_import(self.owner, snapshot.migration_id, snapshot.source_digest)
        upgrade_v2(self.owner)
        self.now = NOW
        self.store = PostgresExecutionStore(self.runtime, clock=lambda: self.now)
        self.cases = PostgresCaseAuthority(self.store, clock=lambda: self.now)
        self.lifecycle = PostgresLifecycle(self.store, cases=self.cases, clock=lambda: self.now)
        self.effects = PostgresEffects(self.store, cases=self.cases, clock=lambda: self.now)

    def drop_schema(self):
        if not self.schema.startswith("p1_e_boundary_") or len(self.schema) != 46:
            raise AssertionError("Only this owned isolated Phase E schema may be removed")
        with self.owner.connect(application_name="continuity-test") as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(self.schema))
            )

    def accept(self, key="one", *, managed=True, complete=True):
        execution = self.store.submit(
            scope_id=ACTOR.scope_id, idempotency_key=key, request=REQUEST
        ).execution
        self.cases.enroll(actor=ACTOR, task_id=execution.task_id)
        if managed:
            self.lifecycle.manage(
                scope_id=ACTOR.scope_id,
                task_id=execution.task_id,
                policy=RetryPolicy(),
                deadline=self.now + timedelta(minutes=2),
            )
            if complete:
                claim = self.lifecycle.claim_due(scope_id=ACTOR.scope_id, task_id=execution.task_id)
                self.assertIsNotNone(claim)
                self.lifecycle.finish_success(claim, self.inquiry())
        return execution

    def inquiry(self):
        return InquiryResult(REQUEST.booking_reference, REQUEST.new_check_in, True)

    def quote(self, execution, *, version=2, **changes):
        case = self.cases.get(actor=ACTOR, task_id=execution.task_id)
        values = {
            "quote_id": str(uuid4()),
            "task_id": execution.task_id,
            "revision": case.revision,
            "booking_reference": REQUEST.booking_reference,
            "new_check_in": REQUEST.new_check_in,
            "amount_minor": 1250,
            "currency": "USD",
            "expires_at": (self.now + timedelta(seconds=90)).isoformat(),
        }
        if version == 2:
            values.update(
                case_id=case.case_id, supplier_id=SUPPLIER_ID, expected_supplier_revision=4
            )
        return QuoteSnapshot(**(values | changes))

    def commit(self, quote, command="confirm"):
        return self.cases.commit_intent(
            actor=ACTOR, confirmation=Confirmation(quote, True), command_id=command
        )

    def arm(self, execution, quote):
        return self.lifecycle.arm_wait(
            actor=ACTOR,
            task_id=execution.task_id,
            wait_id=str(uuid4()),
            quote=quote,
            deadline=self.now + timedelta(seconds=60),
        )

    def receipt_rows(self):
        names = ("quotes", "confirmations", "action_intents", "intent_dispatch")
        with self.owner.connect(application_name="continuity-test") as connection:
            return {
                name: sorted(
                    (
                        tuple(row.values())
                        for row in connection.execute(
                            sql.SQL("SELECT * FROM {}.{}").format(
                                sql.Identifier(self.schema), sql.Identifier(name)
                            )
                        ).fetchall()
                    ),
                    key=repr,
                )
                for name in names
            }

    def test_v3_reads_and_replays_exact_legacy_receipts_without_backfill_or_new_authority(self):
        committed = self.accept("committed", managed=False)
        old_quote = self.quote(committed, version=1)
        self.cases.publish_quote(actor=ACTOR, quote=old_quote)
        old_intent = self.commit(old_quote)
        pending = self.accept("pending", managed=False)
        pending_quote = self.quote(pending, version=1)
        self.cases.publish_quote(actor=ACTOR, quote=pending_quote)
        before = self.receipt_rows()
        upgrade_v3(self.owner)
        self.assertEqual(self.cases.get(actor=ACTOR, task_id=committed.task_id).intent, old_intent)
        self.assertEqual(self.commit(old_quote), old_intent)
        self.assertEqual(self.cases.publish_quote(actor=ACTOR, quote=old_quote), old_quote)
        self.assertEqual(self.cases.publish_quote(actor=ACTOR, quote=pending_quote), pending_quote)
        for quote in (old_quote, pending_quote):
            with self.assertRaises(UnsupportedOperation):
                self.commit(quote, "new-" + quote.quote_id)
            with self.assertRaises(UnsupportedOperation):
                self.cases.publish_quote(actor=ACTOR, quote=replace(quote, quote_id=str(uuid4())))
        with self.assertRaises(UnsupportedOperation):
            self.effects.claim(scope_id=ACTOR.scope_id, task_id=committed.task_id)
        self.assertEqual(self.receipt_rows(), before)
        self.assertIsNone(self.cases.get(actor=ACTOR, task_id=pending.task_id).intent)
        self.assertEqual(
            (old_quote.case_id, old_quote.supplier_id, old_quote.expected_supplier_revision),
            (None, None, None),
        )
        self.assertEqual(len(self.cases.dispatches(actor=ACTOR, task_id=committed.task_id)), 1)

    def test_v2_exact_consent_without_managed_business_deadline_cannot_commit(self):
        upgrade_v3(self.owner)
        execution = self.accept(managed=False)
        quote = self.quote(execution)
        self.cases.publish_quote(actor=ACTOR, quote=quote)
        before = self.receipt_rows()
        with self.assertRaises(UnsupportedOperation):
            self.commit(quote)
        self.assertEqual(self.receipt_rows(), before)
        self.assertIsNone(self.cases.get(actor=ACTOR, task_id=execution.task_id).intent)
        # Establishing an actual managed inquiry and deadline restores useful progress.
        self.lifecycle.manage(
            scope_id=ACTOR.scope_id,
            task_id=execution.task_id,
            policy=RetryPolicy(),
            deadline=self.now + timedelta(minutes=2),
        )
        claim = self.lifecycle.claim_due(scope_id=ACTOR.scope_id, task_id=execution.task_id)
        self.lifecycle.finish_success(claim, self.inquiry())
        self.assertEqual(self.commit(quote).quote, quote)

    def test_supplier_case_and_revision_alterations_cannot_replace_exact_published_consent(self):
        upgrade_v3(self.owner)
        execution = self.accept()
        quote = self.quote(execution)
        self.cases.publish_quote(actor=ACTOR, quote=quote)
        before = self.receipt_rows()
        for fields in (
            {"case_id": str(uuid4())},
            {"supplier_id": str(uuid4())},
            {"expected_supplier_revision": 5},
        ):
            with self.subTest(field=next(iter(fields))), self.assertRaises(InvalidConfirmation):
                self.commit(replace(quote, **fields), "changed-" + next(iter(fields)))
        self.assertEqual(self.receipt_rows(), before)
        intent = self.commit(quote)
        self.assertEqual(intent.quote, quote)
        self.assertEqual(
            self.lifecycle.get(scope_id=ACTOR.scope_id, task_id=execution.task_id).state,
            LifecycleState.INTENT_COMMITTED,
        )

    def test_wrong_case_publication_does_not_withdraw_current_wait_and_replacement_makes_progress(
        self,
    ):
        upgrade_v3(self.owner)
        execution = self.accept()
        original = self.quote(execution)
        self.cases.publish_quote(actor=ACTOR, quote=original)
        first_wait = self.arm(execution, original)
        original_control = self.lifecycle.get(scope_id=ACTOR.scope_id, task_id=execution.task_id)
        self.lifecycle.signal(
            actor=ACTOR, event_id="old", confirmation=Confirmation(original, True)
        )
        self.now += timedelta(seconds=10)
        replacement = self.quote(execution, amount_minor=1350)
        before = self.receipt_rows()
        with self.assertRaises(InvalidConfirmation):
            self.cases.publish_quote(actor=ACTOR, quote=replace(replacement, case_id=str(uuid4())))
        self.assertEqual(self.receipt_rows(), before)
        self.assertEqual(
            self.lifecycle.waits(actor=ACTOR, task_id=execution.task_id)[0].state, WaitState.PENDING
        )
        self.assertEqual(
            self.lifecycle.get(scope_id=ACTOR.scope_id, task_id=execution.task_id), original_control
        )
        self.cases.publish_quote(actor=ACTOR, quote=replacement)
        withdrawn = self.lifecycle.get(scope_id=ACTOR.scope_id, task_id=execution.task_id)
        self.assertEqual(withdrawn.state, LifecycleState.INQUIRY_COMPLETE)
        self.assertEqual(withdrawn.deadline, original_control.deadline)
        waits = self.lifecycle.waits(actor=ACTOR, task_id=execution.task_id)
        self.assertEqual(
            (waits[0].wait_id, waits[0].state), (first_wait.wait_id, WaitState.EXPIRED)
        )
        self.assertIsNone(self.lifecycle.advance(actor=ACTOR, task_id=execution.task_id).intent)
        second_wait = self.arm(execution, replacement)
        self.assertEqual(
            self.lifecycle.advance(actor=ACTOR, task_id=execution.task_id).lifecycle.state,
            LifecycleState.WAITING,
        )
        self.lifecycle.signal(
            actor=ACTOR, event_id="fresh", confirmation=Confirmation(replacement, True)
        )
        outcome = self.lifecycle.advance(actor=ACTOR, task_id=execution.task_id)
        self.assertEqual(outcome.intent.quote, replacement)
        self.assertEqual(outcome.lifecycle.deadline, original_control.deadline)
        self.assertEqual(outcome.lifecycle.state, LifecycleState.INTENT_COMMITTED)
        states = {
            wait.wait_id: wait.state
            for wait in self.lifecycle.waits(actor=ACTOR, task_id=execution.task_id)
        }
        self.assertEqual(
            states, {first_wait.wait_id: WaitState.EXPIRED, second_wait.wait_id: WaitState.CONSUMED}
        )
        replay = self.lifecycle.signal(
            actor=ACTOR, event_id="old", confirmation=Confirmation(original, True)
        )
        self.assertIsNone(replay.consumed_wait_id)
        self.assertEqual(self.cases.publish_quote(actor=ACTOR, quote=original), original)
        self.assertEqual(self.cases.get(actor=ACTOR, task_id=execution.task_id).quote, replacement)

    def test_reused_quote_identity_cannot_change_supplier_binding(self):
        upgrade_v3(self.owner)
        execution = self.accept()
        quote = self.quote(execution)
        self.cases.publish_quote(actor=ACTOR, quote=quote)
        for fields in (
            {"case_id": str(uuid4())},
            {"supplier_id": str(uuid4())},
            {"expected_supplier_revision": 5},
        ):
            with self.subTest(field=next(iter(fields))), self.assertRaises(IdempotencyConflict):
                self.cases.publish_quote(actor=ACTOR, quote=replace(quote, **fields))
        self.assertEqual(self.commit(quote).quote, quote)

    def test_cancellation_keeps_known_readonly_success_and_cannot_restart_continuation(self):
        upgrade_v3(self.owner)
        execution = self.accept(complete=False)
        claim = self.lifecycle.claim_due(scope_id=ACTOR.scope_id, task_id=execution.task_id)
        receipt = self.effects.cancel(actor=ACTOR, task_id=execution.task_id, command_id="stop")
        self.assertEqual(receipt.disposition, CancellationDisposition.BEFORE_COMMIT)
        cancelled = self.lifecycle.get(scope_id=ACTOR.scope_id, task_id=execution.task_id)
        self.assertEqual(cancelled.state, LifecycleState.CANCELLED)
        completion = self.effects.completion(actor=ACTOR, task_id=execution.task_id)
        self.assertIsNotNone(completion)
        final = self.lifecycle.finish_success(claim, self.inquiry())
        self.assertEqual(final, cancelled)
        inquiry = self.store.get(scope_id=ACTOR.scope_id, task_id=execution.task_id)
        self.assertEqual(
            (inquiry.status, inquiry.result), (ExecutionStatus.SUCCEEDED, self.inquiry())
        )
        attempts = self.store.attempts(scope_id=ACTOR.scope_id, task_id=execution.task_id)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0].status, AttemptStatus.SUCCEEDED)
        self.assertEqual(attempts[0].attempt_id, claim.attempt.attempt_id)
        self.assertIsNone(
            self.lifecycle.claim_due(scope_id=ACTOR.scope_id, task_id=execution.task_id)
        )
        self.assertEqual(
            self.lifecycle.advance(actor=ACTOR, task_id=execution.task_id).lifecycle, cancelled
        )
        self.assertEqual(
            self.effects.completion(actor=ACTOR, task_id=execution.task_id), completion
        )
        self.assertTrue(self.cases.get(actor=ACTOR, task_id=execution.task_id).cancelled)
        self.assertEqual(self.cases.dispatches(actor=ACTOR, task_id=execution.task_id), ())

    def test_cancellation_closes_failed_readonly_attempt_without_any_retry(self):
        upgrade_v3(self.owner)
        for failure in FailureClass:
            with self.subTest(failure=failure):
                execution = self.accept(failure.value, complete=False)
                claim = self.lifecycle.claim_due(scope_id=ACTOR.scope_id, task_id=execution.task_id)
                self.effects.cancel(
                    actor=ACTOR, task_id=execution.task_id, command_id="stop-" + failure.value
                )
                cancelled = self.lifecycle.get(scope_id=ACTOR.scope_id, task_id=execution.task_id)
                self.assertEqual(self.lifecycle.finish_failure(claim, failure), cancelled)
                self.assertEqual(cancelled.state, LifecycleState.CANCELLED)
                self.assertIsNone(cancelled.next_attempt_at)
                inquiry = self.store.get(scope_id=ACTOR.scope_id, task_id=execution.task_id)
                self.assertEqual(inquiry.status, ExecutionStatus.FAILED)
                self.assertIsNone(inquiry.result)
                attempts = self.store.attempts(scope_id=ACTOR.scope_id, task_id=execution.task_id)
                self.assertEqual(len(attempts), 1)
                self.assertEqual(attempts[0].status, AttemptStatus.FAILED)
                self.assertIsNotNone(attempts[0].finished_at)
                self.assertIsNone(
                    self.lifecycle.claim_due(scope_id=ACTOR.scope_id, task_id=execution.task_id)
                )
                self.assertIsNotNone(
                    self.effects.completion(actor=ACTOR, task_id=execution.task_id)
                )

    def test_cancelled_claim_requires_case_cancellation_and_original_attempt_and_execution_version(
        self,
    ):
        upgrade_v3(self.owner)
        execution = self.accept(complete=False)
        claim = self.lifecycle.claim_due(scope_id=ACTOR.scope_id, task_id=execution.task_id)
        self.effects.cancel(actor=ACTOR, task_id=execution.task_id, command_id="stop")
        for forged in (
            replace(claim, execution=replace(claim.execution, version=claim.execution.version + 1)),
            replace(claim, attempt=replace(claim.attempt, attempt_id=str(uuid4()))),
        ):
            with self.assertRaises(TransitionConflict):
                self.lifecycle.finish_success(forged, self.inquiry())
        with self.owner.connect(application_name="continuity-test") as connection:
            connection.execute(
                sql.SQL("UPDATE {} SET cancelled=FALSE WHERE task_id=%s").format(
                    sql.Identifier(self.schema, "cases")
                ),
                (execution.task_id,),
            )
        with self.assertRaises(TransitionConflict):
            self.lifecycle.finish_success(claim, self.inquiry())
        with self.owner.connect(application_name="continuity-test") as connection:
            connection.execute(
                sql.SQL("UPDATE {} SET cancelled=TRUE WHERE task_id=%s").format(
                    sql.Identifier(self.schema, "cases")
                ),
                (execution.task_id,),
            )
        self.assertEqual(
            self.lifecycle.finish_success(claim, self.inquiry()).state, LifecycleState.CANCELLED
        )
        with self.assertRaises(TransitionConflict):
            self.lifecycle.finish_success(claim, self.inquiry())

    def test_committed_intent_advance_never_revives_terminal_business_outcomes(self):
        upgrade_v3(self.owner)
        for state in (
            LifecycleState.COMPLETED,
            LifecycleState.CANCELLED,
            LifecycleState.FAILED,
            LifecycleState.UNCERTAIN,
        ):
            with self.subTest(state=state):
                execution = self.accept(state.value)
                quote = self.quote(execution)
                self.cases.publish_quote(actor=ACTOR, quote=quote)
                intent = self.commit(quote, "confirm-" + state.value)
                if state == LifecycleState.CANCELLED:
                    self.effects.cancel(
                        actor=ACTOR, task_id=execution.task_id, command_id="stop-" + state.value
                    )
                else:
                    claim = self.effects.claim(scope_id=ACTOR.scope_id, task_id=execution.task_id)
                    self.assertIsNotNone(claim)
                    if state == LifecycleState.FAILED:
                        self.effects.finish_failure(claim, EffectFailure.SUPPLIER_REJECTED)
                    else:
                        self.assertTrue(
                            self.effects.prepare_dispatch(claim, absence_confirmed=True)
                        )
                        if state == LifecycleState.UNCERTAIN:
                            self.effects.finish_uncertain(claim)
                        else:
                            result = MutationResult(
                                intent.effect_id,
                                intent.intent_id,
                                intent.task_id,
                                quote.case_id,
                                quote.supplier_id,
                                ACTOR.scope_id,
                                quote.booking_reference,
                                date(2030, 12, 5),
                                quote.new_check_in,
                                quote.expected_supplier_revision,
                                quote.expected_supplier_revision + 1,
                                quote.amount_minor,
                                quote.currency,
                                self.now.isoformat(),
                            )
                            self.effects.finish_success(claim, result)
                terminal = self.lifecycle.get(scope_id=ACTOR.scope_id, task_id=execution.task_id)
                self.assertEqual(terminal.state, state)
                completion = self.effects.completion(actor=ACTOR, task_id=execution.task_id)
                before = self.receipt_rows()
                for _ in range(2):
                    advanced = self.lifecycle.advance(actor=ACTOR, task_id=execution.task_id)
                    self.assertEqual((advanced.lifecycle, advanced.intent), (terminal, intent))
                self.assertEqual(
                    self.effects.completion(actor=ACTOR, task_id=execution.task_id), completion
                )
                self.assertEqual(self.receipt_rows(), before)
                self.assertIsNone(
                    self.effects.claim(scope_id=ACTOR.scope_id, task_id=execution.task_id)
                )
