"""Real PostgreSQL cancellation, exact-effect authority and durable completion."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from psycopg import sql

from continuity_lab.authorization import AuthenticatedActor
from continuity_lab.case_models import CaseCancelled, Confirmation, QuoteSnapshot
from continuity_lab.completion_sink import (
    CompletionSink,
    CompletionSinkUnavailable,
    initialize_completion_sink,
)
from continuity_lab.effect_models import (
    CancellationDisposition,
    DeliveryPolicy,
    DeliveryState,
    EffectFailure,
    EffectState,
    MutationResult,
)
from continuity_lab.execution_models import (
    ExecutionCapacityExceeded,
    ExecutionNotFound,
    InquiryResult,
    InvalidStoredState,
    TransitionConflict,
)
from continuity_lab.lifecycle_models import LifecycleState
from continuity_lab.models import BookingChange, IdempotencyConflict
from continuity_lab.outbox_delivery import CompletionDeliveryWorker
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
from continuity_lab.retry_policy import RetryPolicy
from continuity_lab.transfer import make_snapshot

NOW = datetime(2030, 12, 1, tzinfo=UTC)
ACTOR = AuthenticatedActor("actor-a", "account-a")
REQUEST = BookingChange("DEMO-BK-001", date(2030, 12, 10), True)


class PostgresEffectCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("P1_RUN_POSTGRES_TESTS") != "1":
            raise RuntimeError("Real effect lane requires explicit local PostgreSQL setup")
        cls.runtime_base = PostgresSettings.from_env()
        cls.owner_base = PostgresSettings.from_env("P1_MIGRATION_")

    def setUp(self):
        self.schema = "p1_effect_" + uuid4().hex
        self.runtime = replace(self.runtime_base, schema=self.schema)
        self.owner = replace(self.owner_base, schema=self.schema)
        self.addCleanup(self.drop_schema)
        snapshot = make_snapshot([], [], [], migration_id=str(uuid4()))
        install_schema(self.owner)
        stage_import(self.owner, snapshot)
        activate_import(self.owner, snapshot.migration_id, snapshot.source_digest)
        upgrade_v2(self.owner)
        upgrade_v3(self.owner)
        self.clock = [NOW]
        self.store = PostgresExecutionStore(self.runtime, clock=lambda: self.clock[0])
        self.cases = PostgresCaseAuthority(self.store, clock=lambda: self.clock[0])
        self.lifecycle = PostgresLifecycle(
            self.store, cases=self.cases, clock=lambda: self.clock[0]
        )
        self.effects = self.authority()
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.sink_path = Path(self.directory.name) / "sink.sqlite3"
        initialize_completion_sink(self.sink_path)
        self.sink = CompletionSink(self.sink_path, clock=lambda: self.clock[0])

    def drop_schema(self):
        if not self.schema.startswith("p1_effect_") or len(self.schema) != 42:
            raise AssertionError("Only the owned isolated effect schema may be removed")
        with self.owner.connect(application_name="continuity-test") as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(self.schema))
            )

    def authority(self, **kwargs):
        return PostgresEffects(self.store, cases=self.cases, clock=lambda: self.clock[0], **kwargs)

    def prepare(self, key="one", *, commit=True):
        record = self.store.submit(
            scope_id=ACTOR.scope_id, idempotency_key=key, request=REQUEST
        ).execution
        self.lifecycle.manage(
            scope_id=ACTOR.scope_id,
            task_id=record.task_id,
            policy=RetryPolicy(),
            deadline=self.clock[0] + timedelta(minutes=2),
        )
        with self.store.worker_slot():
            claim = self.lifecycle.claim_due(scope_id=ACTOR.scope_id, task_id=record.task_id)
            self.lifecycle.finish_success(
                claim,
                InquiryResult(REQUEST.booking_reference, REQUEST.new_check_in, True),
            )
        case = self.cases.enroll(actor=ACTOR, task_id=record.task_id)
        quote = QuoteSnapshot(
            str(uuid4()),
            record.task_id,
            case.revision,
            REQUEST.booking_reference,
            REQUEST.new_check_in,
            1250,
            "USD",
            (self.clock[0] + timedelta(seconds=30)).isoformat(),
            case.case_id,
            0,
            str(uuid4()),
        )
        self.cases.publish_quote(actor=ACTOR, quote=quote)
        intent = (
            self.cases.commit_intent(
                actor=ACTOR,
                confirmation=Confirmation(quote, True),
                command_id=key + "-confirm",
            )
            if commit
            else None
        )
        return record, quote, intent

    def claim(self, record, authority=None):
        return (authority or self.effects).claim(scope_id=ACTOR.scope_id, task_id=record.task_id)

    def result(self, intent, **changes):
        result = MutationResult(
            intent.effect_id,
            intent.intent_id,
            intent.task_id,
            intent.quote.case_id,
            intent.quote.supplier_id,
            intent.scope_id,
            intent.quote.booking_reference,
            date(2030, 12, 5),
            intent.quote.new_check_in,
            0,
            1,
            intent.quote.amount_minor,
            intent.quote.currency,
            self.clock[0].isoformat(),
        )
        return replace(result, **changes)

    def complete(self):
        record, _, intent = self.prepare()
        claim = self.claim(record)
        self.assertTrue(self.effects.prepare_dispatch(claim, absence_confirmed=True))
        value = self.effects.finish_success(claim, self.result(intent))
        return record, value

    def counts(self):
        with self.runtime.connect() as connection:
            return tuple(
                connection.execute(
                    sql.SQL("SELECT count(*) AS n FROM {}").format(
                        sql.Identifier(self.schema, table)
                    )
                ).fetchone()["n"]
                for table in (
                    "action_intents",
                    "mutation_effects",
                    "mutation_attempts",
                    "cancellation_commands",
                    "business_outcomes",
                    "completion_events",
                    "completion_deliveries",
                )
            )

    def test_success_keeps_original_workflow_distinct_ids_and_one_atomic_completion(
        self,
    ):
        record, value = self.complete()
        self.assertEqual(value.state, EffectState.SUCCEEDED)
        event = self.effects.completion(actor=ACTOR, task_id=record.task_id)
        self.assertEqual(event.outcome.result, value.result)
        self.assertNotEqual(value.intent.effect_id, record.effect_id)
        self.assertNotEqual(event.outcome.case_id, record.task_id)
        self.assertNotEqual(event.event_id, value.intent.dispatch_event_id)
        self.assertIsNone(self.claim(record))
        self.assertEqual(self.counts(), (1, 1, 1, 0, 1, 1, 1))
        self.assertEqual(
            self.lifecycle.get(scope_id=ACTOR.scope_id, task_id=record.task_id).state,
            LifecycleState.COMPLETED,
        )
        self.assertEqual(
            self.store.get(scope_id=ACTOR.scope_id, task_id=record.task_id).effect_id,
            record.effect_id,
        )

    def test_cancel_before_commit_is_idempotent_and_prevents_confirmation(self):
        record, quote, _ = self.prepare(commit=False)
        first = self.effects.cancel(actor=ACTOR, task_id=record.task_id, command_id="cancel")
        self.assertEqual(first.disposition, CancellationDisposition.BEFORE_COMMIT)
        replay = self.effects.cancel(actor=ACTOR, task_id=record.task_id, command_id="cancel")
        self.assertFalse(replay.created)
        self.assertEqual(replay.cancellation_id, first.cancellation_id)
        with self.assertRaises((CaseCancelled, TransitionConflict)):
            self.cases.commit_intent(
                actor=ACTOR,
                confirmation=Confirmation(quote, True),
                command_id="confirm",
            )
        event = self.effects.completion(actor=ACTOR, task_id=record.task_id)
        self.assertIsNone(event.outcome.intent_id)
        self.assertEqual(self.counts(), (0, 0, 0, 1, 1, 1, 1))
        self.assertEqual(
            self.lifecycle.get(scope_id=ACTOR.scope_id, task_id=record.task_id).state,
            LifecycleState.CANCELLED,
        )

    def test_cancel_before_dispatch_retains_committed_intent_and_prevents_claim(
        self,
    ):
        record, _, intent = self.prepare()
        receipt = self.effects.cancel(actor=ACTOR, task_id=record.task_id, command_id="cancel")
        self.assertEqual(receipt.disposition, CancellationDisposition.BEFORE_DISPATCH)
        self.assertIsNone(self.claim(record))
        value = self.effects.get(scope_id=ACTOR.scope_id, task_id=record.task_id)
        self.assertEqual(
            (value.state, value.dispatch_count, value.attempt_no),
            (EffectState.CANCELLED, 0, 0),
        )
        self.assertEqual(self.cases.get(actor=ACTOR, task_id=record.task_id).intent, intent)
        self.assertEqual(self.counts(), (1, 1, 0, 1, 1, 1, 1))

    def test_confirmation_and_cancel_transaction_winner_has_one_truthful_completion(
        self,
    ):
        record, quote, _ = self.prepare(commit=False)
        start = threading.Barrier(2)

        def confirm():
            start.wait()
            try:
                return self.cases.commit_intent(
                    actor=ACTOR,
                    confirmation=Confirmation(quote, True),
                    command_id="race-confirm",
                )
            except (CaseCancelled, TransitionConflict):
                return None

        def cancel():
            start.wait()
            return self.effects.cancel(
                actor=ACTOR, task_id=record.task_id, command_id="race-cancel"
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(confirm), pool.submit(cancel)
            intent, receipt = a.result(), b.result()
        self.assertEqual(
            receipt.disposition,
            CancellationDisposition.BEFORE_COMMIT
            if intent is None
            else CancellationDisposition.BEFORE_DISPATCH,
        )
        self.assertEqual(self.counts()[4:], (1, 1, 1))
        self.assertEqual(
            self.effects.completion(actor=ACTOR, task_id=record.task_id).outcome.state,
            EffectState.CANCELLED,
        )

    def test_dispatch_reservation_wins_cancel_then_known_success_wins_deadline(self):
        record, _, intent = self.prepare()
        claim = self.claim(record)
        self.assertTrue(self.effects.prepare_dispatch(claim, absence_confirmed=True))
        receipt = self.effects.cancel(actor=ACTOR, task_id=record.task_id, command_id="cancel")
        self.assertEqual(receipt.disposition, CancellationDisposition.REQUESTED)
        self.assertIsNone(self.effects.completion(actor=ACTOR, task_id=record.task_id))
        self.assertEqual(
            self.lifecycle.get(scope_id=ACTOR.scope_id, task_id=record.task_id).state,
            LifecycleState.INTENT_COMMITTED,
        )
        self.clock[0] += timedelta(days=1)
        value = self.effects.finish_success(claim, self.result(intent))
        self.assertEqual(value.state, EffectState.SUCCEEDED)
        event = self.effects.completion(actor=ACTOR, task_id=record.task_id)
        self.assertEqual(event.outcome.cancellation, CancellationDisposition.REQUESTED)
        later = self.effects.cancel(actor=ACTOR, task_id=record.task_id, command_id="cancel-later")
        self.assertEqual(later.disposition, CancellationDisposition.ALREADY_TERMINAL)
        self.assertEqual(self.effects.completion(actor=ACTOR, task_id=record.task_id), event)

    def test_recovered_claim_keeps_possible_dispatch_evidence_for_cancel(self):
        record, _, _ = self.prepare()
        original = self.claim(record)
        self.effects.prepare_dispatch(original, absence_confirmed=True)
        recovered = self.claim(record)
        self.assertTrue(recovered.recovered)
        self.assertTrue(recovered.may_have_dispatched)
        self.assertGreater(recovered.generation, original.generation)
        receipt = self.effects.cancel(actor=ACTOR, task_id=record.task_id, command_id="cancel")
        self.assertEqual(receipt.disposition, CancellationDisposition.REQUESTED)
        self.assertIsNone(self.effects.completion(actor=ACTOR, task_id=record.task_id))
        value = self.effects.finish_uncertain(recovered)
        self.assertEqual(value.state, EffectState.UNCERTAIN)

    def test_claim_without_reservation_remains_provably_not_dispatched_on_recovery(
        self,
    ):
        record, _, _ = self.prepare()
        first = self.claim(record)
        second = self.claim(record)
        self.assertTrue(second.recovered)
        self.assertFalse(second.may_have_dispatched)
        self.assertEqual(
            self.effects.get(scope_id=ACTOR.scope_id, task_id=record.task_id).dispatch_count,
            0,
        )
        with self.assertRaises(TransitionConflict):
            self.effects.prepare_dispatch(first, absence_confirmed=True)
        self.assertTrue(self.effects.prepare_dispatch(second, absence_confirmed=True))
        with self.assertRaises(TransitionConflict):
            self.effects.prepare_dispatch(second, absence_confirmed=True)

    def test_attempt_cap_without_dispatch_fails_but_possible_dispatch_stays_uncertain(
        self,
    ):
        for key, dispatch in (("never-sent", False), ("possibly-sent", True)):
            with self.subTest(dispatch=dispatch):
                record, _, _ = self.prepare(key)
                effects = self.authority(maximum_attempts=1)
                claim = self.claim(record, effects)
                if dispatch:
                    effects.prepare_dispatch(claim, absence_confirmed=True)
                self.assertIsNone(self.claim(record, effects))
                value = effects.get(scope_id=ACTOR.scope_id, task_id=record.task_id)
                self.assertEqual(
                    value.state,
                    EffectState.UNCERTAIN if dispatch else EffectState.FAILED,
                )
                self.assertEqual(value.error_code, EffectFailure.ATTEMPTS_EXHAUSTED)

    def test_fresh_deadline_prevents_dispatch_but_known_external_truth_survives_expiry(
        self,
    ):
        record, _, _ = self.prepare()
        self.clock[0] += timedelta(minutes=2)
        self.assertIsNone(self.claim(record))
        value = self.effects.get(scope_id=ACTOR.scope_id, task_id=record.task_id)
        self.assertEqual(
            (value.state, value.dispatch_count, value.error_code),
            (EffectState.FAILED, 0, EffectFailure.DEADLINE_EXPIRED),
        )

    def test_predispatch_unavailability_retains_bounded_manual_retry_and_attempt_receipts(
        self,
    ):
        record, _, _ = self.prepare()
        effects = self.authority(maximum_attempts=2)
        first = self.claim(record, effects)
        value = effects.finish_failure(first, EffectFailure.DEPENDENCY_UNAVAILABLE)
        self.assertEqual(value.state, EffectState.PENDING)
        self.assertIsNone(effects.completion(actor=ACTOR, task_id=record.task_id))
        second = self.claim(record, effects)
        value = effects.finish_failure(second, EffectFailure.DEPENDENCY_UNAVAILABLE)
        self.assertEqual(
            (value.state, value.error_code),
            (EffectState.FAILED, EffectFailure.ATTEMPTS_EXHAUSTED),
        )
        self.assertEqual(self.counts()[2], 2)

    def test_changed_result_binding_and_stale_generation_cannot_finalize(self):
        record, _, intent = self.prepare()
        first = self.claim(record)
        second = self.claim(record)
        with self.assertRaises(TransitionConflict):
            self.effects.finish_success(first, self.result(intent))
        with self.assertRaises(InvalidStoredState):
            self.effects.finish_success(second, self.result(intent, supplier_id=str(uuid4())))
        self.assertIsNone(self.effects.completion(actor=ACTOR, task_id=record.task_id))
        self.assertEqual(
            self.effects.finish_success(second, self.result(intent)).state,
            EffectState.SUCCEEDED,
        )

    def test_completion_and_effect_rollback_together_then_retry_same_claim(self):
        record, _, intent = self.prepare()
        claim = self.claim(record)

        def fail(name):
            if name == "effects.after_completion_rows":
                raise RuntimeError("isolated crash before atomic commit")

        effects = self.authority(failpoint=fail)
        with self.assertRaises(RuntimeError):
            effects.finish_success(claim, self.result(intent))
        self.assertEqual(self.counts()[4:], (0, 0, 0))
        self.assertEqual(
            self.effects.get(scope_id=ACTOR.scope_id, task_id=record.task_id).state,
            EffectState.CLAIMED,
        )
        self.effects.finish_success(claim, self.result(intent))
        self.assertEqual(self.counts()[4:], (1, 1, 1))

    def test_cancel_scope_owner_conflicts_and_capacity_replay_are_explicit(self):
        first, _, _ = self.prepare("first")
        second, _, _ = self.prepare("second")
        effects = self.authority(maximum_cancellations=1)
        effects.cancel(actor=ACTOR, task_id=first.task_id, command_id="same")
        self.assertFalse(
            effects.cancel(actor=ACTOR, task_id=first.task_id, command_id="same").created
        )
        with self.assertRaises(ExecutionCapacityExceeded):
            effects.cancel(actor=ACTOR, task_id=first.task_id, command_id="new")
        with self.assertRaises(IdempotencyConflict):
            effects.cancel(actor=ACTOR, task_id=second.task_id, command_id="same")
        for actor in (
            AuthenticatedActor("other-actor", ACTOR.scope_id),
            AuthenticatedActor(ACTOR.actor_id, "account-b"),
        ):
            with self.subTest(actor=actor), self.assertRaises(ExecutionNotFound):
                effects.cancel(actor=actor, task_id=first.task_id, command_id="private")
            with self.assertRaises(ExecutionNotFound):
                effects.completion(actor=actor, task_id=first.task_id)

    def test_cancel_closes_pending_wait_and_preserves_typed_final_observation(self):
        record, quote, _ = self.prepare(commit=False)
        wait = self.lifecycle.arm_wait(
            actor=ACTOR,
            task_id=record.task_id,
            wait_id=str(uuid4()),
            quote=quote,
            deadline=self.clock[0] + timedelta(seconds=20),
        )
        self.effects.cancel(actor=ACTOR, task_id=record.task_id, command_id="cancel")
        with self.runtime.connect() as connection:
            row = connection.execute(
                sql.SQL("SELECT state,finished_at FROM {} WHERE wait_id=%s").format(
                    sql.Identifier(self.schema, "execution_waits")
                ),
                (wait.wait_id,),
            ).fetchone()
        self.assertEqual(row["state"], "expired")
        self.assertIsNotNone(row["finished_at"])

    def test_delivery_backoff_is_bounded_and_does_not_change_business_truth(self):
        record, _ = self.complete()
        # Policy is captured at completion; create a second task under a bounded policy.
        record2, _, intent = self.prepare("bounded")
        effects = self.authority(delivery_policy=DeliveryPolicy(2, 2, 2))
        claim = self.claim(record2, effects)
        effects.finish_success(claim, self.result(intent))
        event = effects.completion(actor=ACTOR, task_id=record2.task_id)

        class Unavailable:
            receiver_id = str(uuid4())

            def accept(self, event):
                raise CompletionSinkUnavailable("SECRET_SENTINEL")

        worker = CompletionDeliveryWorker(effects, Unavailable())
        first = worker.run_one(scope_id=ACTOR.scope_id, task_id=record2.task_id)
        self.assertEqual(
            (first.state, first.attempts, first.next_attempt_at),
            (
                DeliveryState.PENDING,
                1,
                (self.clock[0] + timedelta(seconds=2)).isoformat(),
            ),
        )
        early = worker.run_one(scope_id=ACTOR.scope_id, task_id=record2.task_id)
        self.assertEqual(early, first)
        self.clock[0] += timedelta(seconds=2)
        last = worker.run_one(scope_id=ACTOR.scope_id, task_id=record2.task_id)
        self.assertEqual(
            (last.state, last.attempts, last.error_code),
            (DeliveryState.EXHAUSTED, 2, "delivery_exhausted"),
        )
        self.assertEqual(worker.run_one(scope_id=ACTOR.scope_id, task_id=record2.task_id), last)
        self.assertEqual(effects.completion(actor=ACTOR, task_id=record2.task_id), event)
        self.assertEqual(
            self.lifecycle.get(scope_id=ACTOR.scope_id, task_id=record2.task_id).state,
            LifecycleState.COMPLETED,
        )
        self.assertEqual(self.effects.delivery(actor=ACTOR, task_id=record.task_id).attempts, 0)

    def test_delivery_receiver_binding_and_generation_reject_swaps_before_budget_changes(
        self,
    ):
        record, _ = self.complete()
        target = self.sink.receiver_id
        first = self.effects.claim_delivery(
            scope_id=ACTOR.scope_id, task_id=record.task_id, target_id=target
        )
        before = self.effects.delivery(actor=ACTOR, task_id=record.task_id)
        with self.assertRaises(TransitionConflict):
            self.effects.claim_delivery(
                scope_id=ACTOR.scope_id, task_id=record.task_id, target_id=str(uuid4())
            )
        self.assertEqual(self.effects.delivery(actor=ACTOR, task_id=record.task_id), before)
        second = self.effects.claim_delivery(
            scope_id=ACTOR.scope_id, task_id=record.task_id, target_id=target
        )
        with self.assertRaises(TransitionConflict):
            self.effects.finish_delivery(first, delivered=True)
        delivered = self.effects.finish_delivery(second, delivered=True)
        self.assertEqual(delivered.state, DeliveryState.DELIVERED)
        with self.assertRaises(TransitionConflict):
            self.effects.claim_delivery(
                scope_id=ACTOR.scope_id, task_id=record.task_id, target_id=str(uuid4())
            )

    def test_actual_process_loss_after_receiver_commit_replays_one_stable_event(self):
        record, _ = self.complete()
        event = self.effects.completion(actor=ACTOR, task_id=record.task_id)
        code = """import os,sys
from datetime import datetime
from continuity_lab.completion_sink import CompletionSink
from continuity_lab.outbox_delivery import CompletionDeliveryWorker
from continuity_lab.postgres_effects import PostgresEffects
from continuity_lab.postgres_settings import PostgresSettings
from continuity_lab.postgres_store import PostgresExecutionStore
settings=PostgresSettings.from_env()
now=datetime.fromisoformat(sys.argv[3])
effects=PostgresEffects(PostgresExecutionStore(settings),clock=lambda:now)
sink=CompletionSink(sys.argv[2],clock=lambda:now)
def crash(name):
 if name=="outbox.after_sink_success":os._exit(74)
CompletionDeliveryWorker(effects,sink,failpoint=crash).run_one(scope_id="account-a",task_id=sys.argv[1])
"""
        environment = dict(os.environ, P1_POSTGRES_SCHEMA=self.schema)
        child = subprocess.run(
            [
                sys.executable,
                "-c",
                code,
                record.task_id,
                str(self.sink_path),
                self.clock[0].isoformat(),
            ],
            env=environment,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(child.returncode, 74, child.stderr)
        self.assertEqual(self.sink.count(), 1)
        self.assertEqual(
            self.effects.delivery(actor=ACTOR, task_id=record.task_id).state,
            DeliveryState.DELIVERING,
        )
        self.sink.prune_diagnostics(keep=0)
        fresh = self.authority()
        result = CompletionDeliveryWorker(fresh, CompletionSink(self.sink_path)).run_one(
            scope_id=ACTOR.scope_id, task_id=record.task_id
        )
        self.assertEqual(
            (result.state, result.attempts, result.event),
            (DeliveryState.DELIVERED, 2, event),
        )
        self.assertEqual((self.sink.count(), self.sink.diagnostic_count()), (1, 1))
        self.assertEqual(fresh.completion(actor=ACTOR, task_id=record.task_id), event)

    def test_delivery_ack_local_rollback_leaves_stable_sink_receipt_and_retryable_event(
        self,
    ):
        record, _ = self.complete()

        def fail(name):
            if name == "delivery.before_finish_commit":
                raise RuntimeError("local acknowledgement lost")

        worker = CompletionDeliveryWorker(self.authority(failpoint=fail), self.sink)
        with self.assertRaises(RuntimeError):
            worker.run_one(scope_id=ACTOR.scope_id, task_id=record.task_id)
        self.assertEqual(self.sink.count(), 1)
        self.assertEqual(
            self.effects.delivery(actor=ACTOR, task_id=record.task_id).state,
            DeliveryState.DELIVERING,
        )
        result = CompletionDeliveryWorker(self.effects, self.sink).run_one(
            scope_id=ACTOR.scope_id, task_id=record.task_id
        )
        self.assertEqual(
            (result.state, result.attempts, self.sink.count()),
            (DeliveryState.DELIVERED, 2, 1),
        )

    def test_quote_expiry_does_not_revoke_already_committed_authority_before_deadline(
        self,
    ):
        record, _, intent = self.prepare()
        self.clock[0] += timedelta(seconds=31)
        claim = self.claim(record)
        self.assertTrue(self.effects.prepare_dispatch(claim, absence_confirmed=True))
        self.assertEqual(
            self.effects.finish_success(claim, self.result(intent)).state,
            EffectState.SUCCEEDED,
        )

    def test_cancellation_transaction_rollback_leaves_no_false_cancel_or_completion(
        self,
    ):
        record, _, _ = self.prepare()

        def fail(name):
            if name == "effects.before_cancel_commit":
                raise RuntimeError("cancel transaction aborted")

        with self.assertRaises(RuntimeError):
            self.authority(failpoint=fail).cancel(
                actor=ACTOR, task_id=record.task_id, command_id="cancel"
            )
        self.assertFalse(self.cases.get(actor=ACTOR, task_id=record.task_id).cancelled)
        self.assertEqual(self.counts(), (1, 0, 0, 0, 0, 0, 0))
        receipt = self.effects.cancel(actor=ACTOR, task_id=record.task_id, command_id="cancel")
        self.assertTrue(receipt.created)
        self.assertEqual(receipt.disposition, CancellationDisposition.BEFORE_DISPATCH)

    def test_committed_success_with_lost_return_replays_completion_without_new_attempt(
        self,
    ):
        record, _, intent = self.prepare()
        claim = self.claim(record)

        def fail(name):
            if name == "effects.after_finish_commit":
                raise RuntimeError("committed return lost")

        with self.assertRaises(RuntimeError):
            self.authority(failpoint=fail).finish_success(claim, self.result(intent))
        event = self.effects.completion(actor=ACTOR, task_id=record.task_id)
        self.assertEqual(event.outcome.state, EffectState.SUCCEEDED)
        self.assertIsNone(self.claim(record))
        self.assertEqual(self.counts(), (1, 1, 1, 0, 1, 1, 1))

    def test_delivery_crash_recovery_attempt_cap_exhausts_without_changing_outcome(
        self,
    ):
        record, _, intent = self.prepare()
        effects = self.authority(delivery_policy=DeliveryPolicy(2, 1, 2))
        claim = self.claim(record, effects)
        effects.finish_success(claim, self.result(intent))
        original = effects.completion(actor=ACTOR, task_id=record.task_id)
        target = self.sink.receiver_id
        effects.claim_delivery(scope_id=ACTOR.scope_id, task_id=record.task_id, target_id=target)
        effects.claim_delivery(scope_id=ACTOR.scope_id, task_id=record.task_id, target_id=target)
        self.assertIsNone(
            effects.claim_delivery(
                scope_id=ACTOR.scope_id, task_id=record.task_id, target_id=target
            )
        )
        final = effects.delivery(actor=ACTOR, task_id=record.task_id)
        self.assertEqual((final.state, final.attempts), (DeliveryState.EXHAUSTED, 2))
        self.assertEqual(effects.completion(actor=ACTOR, task_id=record.task_id), original)
        self.assertEqual(self.sink.count(), 0)

    def test_cross_effect_attempt_pointer_cannot_cancel_or_close_unrelated_attempt(
        self,
    ):
        first, _, _ = self.prepare("first")
        second, _, _ = self.prepare("second")
        a, b = self.claim(first), self.claim(second)
        with self.owner.connect(application_name="continuity-test") as connection:
            connection.execute(
                sql.SQL("UPDATE {} SET active_attempt_id=%s WHERE task_id=%s").format(
                    sql.Identifier(self.schema, "mutation_effects")
                ),
                (b.attempt_id, first.task_id),
            )
        with self.assertRaises(InvalidStoredState):
            self.effects.cancel(actor=ACTOR, task_id=first.task_id, command_id="cancel")
        self.assertFalse(self.cases.get(actor=ACTOR, task_id=first.task_id).cancelled)
        with self.runtime.connect() as connection:
            rows = connection.execute(
                sql.SQL("SELECT attempt_id,state FROM {} ORDER BY attempt_id").format(
                    sql.Identifier(self.schema, "mutation_attempts")
                )
            ).fetchall()
        self.assertEqual(
            {row["attempt_id"]: row["state"] for row in rows},
            {a.attempt_id: "started", b.attempt_id: "started"},
        )
        self.assertEqual(self.counts()[3:], (0, 0, 0, 0))

    def test_missing_attempt_pointer_evidence_cannot_be_finalized_by_deadline(self):
        record, _, _ = self.prepare()
        self.claim(record)
        with self.owner.connect(application_name="continuity-test") as connection:
            connection.execute(
                sql.SQL("UPDATE {} SET active_attempt_id=%s WHERE task_id=%s").format(
                    sql.Identifier(self.schema, "mutation_effects")
                ),
                (str(uuid4()), record.task_id),
            )
        self.clock[0] += timedelta(minutes=2)
        with self.assertRaises(InvalidStoredState):
            self.claim(record)
        self.assertEqual(self.counts()[4:], (0, 0, 0))
