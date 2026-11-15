"""Real v4 worker fences, admission and stale external-call schedules."""

import json
import os
import sys
import time
import unittest
from contextlib import closing
from datetime import date, timedelta
from uuid import uuid4

import pg_mutation_cases as prior
from psycopg import sql

from continuity_lab.case_models import Confirmation, QuoteSnapshot
from continuity_lab.completion_sink import CompletionSink, initialize_completion_sink
from continuity_lab.effect_models import CancellationDisposition, EffectFailure, EffectState
from continuity_lab.execution_models import UnsupportedOperation
from continuity_lab.lease_models import (
    CoordinationPolicy,
    LeaseLost,
    LeaseRequired,
    WorkKind,
)
from continuity_lab.lifecycle_models import LifecycleState
from continuity_lab.managed_inquiry_worker import ManagedInquiryWorker
from continuity_lab.models import BookingChange, IntakeCapacityExceeded
from continuity_lab.mutation_worker import MutationWorker
from continuity_lab.postgres_effects import PostgresEffects
from continuity_lab.postgres_leases import PostgresLeases
from continuity_lab.postgres_lifecycle import PostgresLifecycle
from continuity_lab.postgres_migrations import upgrade_v4
from continuity_lab.postgres_work import PostgresWorkQueue
from continuity_lab.retry_policy import RetryPolicy
from harness.process_control import FileBarrier, OwnedProcess

ACTOR = prior.ACTOR
NOW = prior.NOW

CHILD = r"""
import json,sys
from dataclasses import asdict
from datetime import datetime
from continuity_lab.lease_models import LeaseGrant,LeaseLost
from continuity_lab.mutation_supplier import MutationSupplier,NonCooperatingMutationSupplier
from continuity_lab.mutation_worker import MutationWorker
from continuity_lab.postgres_effects import PostgresEffects
from continuity_lab.postgres_store import PostgresExecutionStore
from continuity_lab.postgres_settings import PostgresSettings
from harness.process_control import FileBarrier
path,folder,point,raw,cooperating,now=sys.argv[1:]
grant=LeaseGrant(**json.loads(raw))
clock=lambda:datetime.fromisoformat(now)
store=PostgresExecutionStore(PostgresSettings.from_env(),clock=clock)
effects=PostgresEffects(store,worker_lease=grant,clock=clock)
supplier=(MutationSupplier if cooperating=='1' else NonCooperatingMutationSupplier)(path,clock=clock)
def pause(hit):
    if hit==point:FileBarrier(folder,'supplier_boundary').arrive_and_wait(timeout=20)
try:
    MutationWorker(effects,supplier,failpoint=pause).run_one(scope_id=grant.scope_id,task_id=grant.task_id)
except LeaseLost:
    print(json.dumps({'code':'lease_lost'}),flush=True)
    sys.exit(10)
raise AssertionError('A stale worker must not acknowledge its result')
"""


class PostgresCoordinationCases(unittest.TestCase):
    setUpClass = classmethod(prior.PostgresMutationCases.setUpClass.__func__)
    drop_schema = prior.PostgresMutationCases.drop_schema
    noncooperating = prior.PostgresMutationCases.noncooperating

    def setUp(self):
        prior.PostgresMutationCases.setUp(self)
        if (
            self._testMethodName
            == "test_late_management_of_completed_inquiry_cannot_bypass_pending_cap"
        ):
            from continuity_lab.inquiry_worker import InquiryWorker

            self.legacy = self.submit("legacy-completed")
            InquiryWorker(self.executions, self.supplier.inquiry_view()).run_one(
                scope_id=ACTOR.scope_id, task_id=self.legacy.task_id
            )
        upgrade_v4(self.owner, policy=CoordinationPolicy(10, 2, 50, 3))
        self.leases = PostgresLeases(self.executions)
        self.queue = PostgresWorkQueue(self.executions, clock=self.clock)

    def submit(self, key):
        return self.executions.submit(
            scope_id=ACTOR.scope_id,
            idempotency_key=key,
            request=BookingChange(prior.BOOKING, date(2030, 12, 10), True),
        ).execution

    def grant(self, record):
        return self.leases.acquire(
            scope_id=ACTOR.scope_id, task_id=record.task_id, owner_id=str(uuid4())
        )

    def lifecycle_for(self, grant=None):
        return PostgresLifecycle(
            self.executions, cases=self.cases, clock=self.clock, worker_lease=grant
        )

    def effects_for(self, grant=None):
        return PostgresEffects(
            self.executions, cases=self.cases, clock=self.clock, worker_lease=grant
        )

    def prepare(self, key="one", supplier=None, commit=True):
        supplier = self.supplier if supplier is None else supplier
        record = self.submit(key)
        self.lifecycle.manage(
            scope_id=ACTOR.scope_id,
            task_id=record.task_id,
            policy=RetryPolicy(),
            deadline=self.clock() + timedelta(minutes=5),
        )
        grant = self.grant(record)
        try:
            ManagedInquiryWorker(self.lifecycle_for(grant), supplier.inquiry_view()).run_one(
                scope_id=ACTOR.scope_id, task_id=record.task_id
            )
        finally:
            self.leases.release(grant)
        case = self.cases.enroll(actor=ACTOR, task_id=record.task_id)
        quote = QuoteSnapshot(
            str(uuid4()),
            record.task_id,
            case.revision,
            prior.BOOKING,
            record.request.new_check_in,
            12500,
            "USD",
            (self.clock() + timedelta(minutes=2)).isoformat(),
            case.case_id,
            supplier.booking(scope_id=ACTOR.scope_id, booking_reference=prior.BOOKING).revision,
            supplier.provider_id,
        )
        self.cases.publish_quote(actor=ACTOR, quote=quote)
        if not commit:
            return record, quote
        intent = self.cases.commit_intent(
            actor=ACTOR, confirmation=Confirmation(quote, True), command_id="confirm-" + key
        )
        return record, intent

    def expire(self, grant):
        deadline = time.monotonic() + 6
        with closing(self.runtime.connect(application_name="continuity-test")) as connection:
            while time.monotonic() < deadline:
                if connection.execute(
                    "SELECT clock_timestamp()>=%s::timestamptz AS expired", (grant.expires_at,)
                ).fetchone()["expired"]:
                    return
                time.sleep(0.01)
        self.fail("Required actual database lease expiry was not observed")

    def child(self, record, grant, point, supplier):
        from dataclasses import asdict

        path = self.folder / ("child-" + uuid4().hex)
        path.mkdir(mode=0o700)
        barrier = FileBarrier(path, "supplier_boundary")
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("P1_MIGRATION_", "PG"))
        }
        env.update({"P1_POSTGRES_SCHEMA": self.schema, "PYTHONPATH": str(prior.ROOT)})
        child = OwnedProcess(
            [
                sys.executable,
                "-c",
                CHILD,
                str(supplier.database),
                str(path),
                point,
                json.dumps(asdict(grant)),
                "1" if supplier.capabilities.idempotent else "0",
                self.clock().isoformat(),
            ],
            cwd=prior.ROOT,
            env=env,
            output_directory=path / "output",
        )
        return child, barrier

    def stale_boundary(self, *, cooperating=True, after_success=False, during_pause=None):
        supplier = self.supplier if cooperating else self.noncooperating()
        record, intent = self.prepare(supplier=supplier)
        first = self.grant(record)
        point = (
            "mutation_worker.after_supplier_success"
            if after_success
            else "mutation_worker.after_dispatch_reserved"
        )
        child, barrier = self.child(record, first, point, supplier)
        with child:
            child.wait_for_barrier(barrier, timeout=10)
            # Public reads and protected authority transactions remain available.
            self.assertEqual(self.cases.get(actor=ACTOR, task_id=record.task_id).intent, intent)
            if during_pause == "cancel":
                receipt = self.effects.cancel(
                    actor=ACTOR, task_id=record.task_id, command_id="cancel"
                )
                self.assertEqual(receipt.disposition, CancellationDisposition.REQUESTED)
            elif during_pause == "deadline":
                self.clock.value += timedelta(minutes=6)
            self.expire(first)
            second = self.grant(record)
            self.assertGreater(second.epoch, first.epoch)
            value = MutationWorker(self.effects_for(second), supplier).run_one(
                scope_id=ACTOR.scope_id, task_id=record.task_id
            )
            self.assertEqual(
                value.state,
                EffectState.SUCCEEDED
                if cooperating and during_pause is None
                else EffectState.UNCERTAIN,
            )
            before = self.effects_for().completion(actor=ACTOR, task_id=record.task_id)
            if not cooperating or during_pause is not None:
                self.assertEqual(supplier.count_calls(scope_id=ACTOR.scope_id), 0)
            self.leases.release(second)
            child.release_barrier(barrier)
            self.assertEqual(child.wait(timeout=10).returncode, 10)
            self.assertEqual(json.loads(child.output_tail("stdout"))["code"], "lease_lost")
        retained = self.effects_for().get(scope_id=ACTOR.scope_id, task_id=record.task_id)
        self.assertEqual(retained, value)
        self.assertEqual(self.effects_for().completion(actor=ACTOR, task_id=record.task_id), before)
        self.assertEqual(supplier.count_mutations(scope_id=ACTOR.scope_id), 1)
        self.assertEqual(
            supplier.count_calls(scope_id=ACTOR.scope_id),
            1 if after_success or not cooperating or during_pause is not None else 2,
        )
        self.assertEqual(
            MutationWorker(self.effects_for(), supplier).run_one(
                scope_id=ACTOR.scope_id, task_id=record.task_id
            ),
            value,
        )
        return before.outcome

    def test_paused_old_external_call_after_takeover_is_cooperatively_deduplicated(self):
        self.stale_boundary()

    def test_paused_old_call_without_cooperation_remains_uncertain(self):
        self.stale_boundary(cooperating=False)

    def test_known_supplier_success_reconciles_after_epoch_takeover_and_rejects_old_ack(self):
        self.stale_boundary(after_success=True)

    def test_cancel_during_paused_old_call_is_uncertain_not_prevented_after_takeover(self):
        outcome = self.stale_boundary(during_pause="cancel")
        self.assertEqual(
            (outcome.state, outcome.error_code, outcome.cancellation),
            (
                EffectState.UNCERTAIN,
                EffectFailure.AMBIGUOUS_OUTCOME,
                CancellationDisposition.REQUESTED,
            ),
        )

    def test_deadline_during_paused_old_call_is_uncertain_not_failed_after_takeover(self):
        outcome = self.stale_boundary(during_pause="deadline")
        self.assertEqual(
            (outcome.state, outcome.error_code, outcome.cancellation),
            (
                EffectState.UNCERTAIN,
                EffectFailure.AMBIGUOUS_OUTCOME,
                CancellationDisposition.NOT_REQUESTED,
            ),
        )

    def test_missing_lease_cannot_start_inquiry_mutation_or_delivery(self):
        record = self.submit("missing")
        self.lifecycle.manage(
            scope_id=ACTOR.scope_id,
            task_id=record.task_id,
            policy=RetryPolicy(),
            deadline=self.clock() + timedelta(minutes=5),
        )
        with self.assertRaises(LeaseRequired):
            self.lifecycle.claim_due(scope_id=ACTOR.scope_id, task_id=record.task_id)
        with self.assertRaises(UnsupportedOperation):
            self.executions.start_attempt(
                scope_id=ACTOR.scope_id, task_id=record.task_id, expected_version=0
            )
        prepared, _intent = self.prepare("valid")
        with self.assertRaises(LeaseRequired):
            self.effects.claim(scope_id=ACTOR.scope_id, task_id=prepared.task_id)
        grant = self.grant(prepared)
        value = MutationWorker(self.effects_for(grant), self.supplier).run_one(
            scope_id=ACTOR.scope_id, task_id=prepared.task_id
        )
        self.assertEqual(value.state, EffectState.SUCCEEDED)
        self.leases.release(grant)
        with self.assertRaises(LeaseRequired):
            self.effects.claim_delivery(
                scope_id=ACTOR.scope_id, task_id=prepared.task_id, target_id=str(uuid4())
            )

    def test_expired_inquiry_grant_cannot_ack_and_current_grant_recovers_known_result(self):
        record = self.submit("inquiry")
        self.lifecycle.manage(
            scope_id=ACTOR.scope_id,
            task_id=record.task_id,
            policy=RetryPolicy(),
            deadline=self.clock() + timedelta(minutes=5),
        )
        grant = self.grant(record)
        old = self.lifecycle_for(grant)
        claim = old.claim_due(scope_id=ACTOR.scope_id, task_id=record.task_id)
        observation = self.supplier.inquiry_view().inquire(
            scope_id=ACTOR.scope_id,
            effect_id=claim.execution.effect_id,
            request=claim.execution.request,
        )
        self.expire(grant)
        with self.assertRaises(LeaseLost):
            old.finish_success(claim, observation.result)
        fresh = self.grant(record)
        value = ManagedInquiryWorker(
            self.lifecycle_for(fresh), self.supplier.inquiry_view()
        ).run_one(scope_id=ACTOR.scope_id, task_id=record.task_id)
        self.assertEqual(value.state, LifecycleState.INQUIRY_COMPLETE)
        self.assertEqual(self.supplier.count_inquiries(scope_id=ACTOR.scope_id), 1)
        self.leases.release(fresh)

    def test_expired_delivery_ack_is_rejected_and_current_epoch_replays_original_receiver(self):
        record, _ = self.prepare()
        grant = self.grant(record)
        effects = self.effects_for(grant)
        MutationWorker(effects, self.supplier).run_one(
            scope_id=ACTOR.scope_id, task_id=record.task_id
        )
        path = self.folder / "sink.sqlite3"
        initialize_completion_sink(path)
        sink = CompletionSink(path, clock=self.clock)
        claim = effects.claim_delivery(
            scope_id=ACTOR.scope_id, task_id=record.task_id, target_id=sink.receiver_id
        )
        sink.accept(claim.event)
        self.expire(grant)
        with self.assertRaises(LeaseLost):
            effects.finish_delivery(claim, delivered=True)
        fresh = self.grant(record)
        from continuity_lab.outbox_delivery import CompletionDeliveryWorker

        value = CompletionDeliveryWorker(self.effects_for(fresh), sink).run_one(
            scope_id=ACTOR.scope_id, task_id=record.task_id
        )
        self.assertEqual(value.state.value, "delivered")
        self.assertEqual(sink.count(), 1)
        self.leases.release(fresh)

    def policy(self, *, pending=10, active=2, records=50):
        with closing(self.owner.connect(application_name="continuity-test")) as connection:
            connection.execute(
                sql.SQL(
                    "UPDATE {} SET maximum_pending=%s,maximum_active=%s,maximum_records=%s"
                ).format(sql.Identifier(self.schema, "execution_limits")),
                (pending, active, records),
            )

    def test_pending_capacity_includes_successful_inquiry_waits_and_committed_intents(self):
        self.policy(pending=2, active=1, records=3)
        first, quote = self.prepare("waiting", commit=False)
        self.lifecycle.arm_wait(
            actor=ACTOR,
            task_id=first.task_id,
            wait_id=str(uuid4()),
            quote=quote,
            deadline=self.clock() + timedelta(seconds=40),
        )
        second, _ = self.prepare("intent")
        with self.assertRaises(IntakeCapacityExceeded):
            self.submit("rejected")
        replay = self.submit("waiting")
        self.assertEqual(replay.task_id, first.task_id)
        self.assertEqual(len(self.executions.list(scope_id=ACTOR.scope_id)), 2)
        self.effects.cancel(actor=ACTOR, task_id=first.task_id, command_id="cancel")
        third = self.submit("accepted-after-cancel")
        self.assertNotEqual(third.task_id, first.task_id)
        self.effects.cancel(actor=ACTOR, task_id=second.task_id, command_id="cancel-second")
        with self.assertRaises(IntakeCapacityExceeded):
            self.submit("retention-reject")
        self.assertEqual(self.submit("intent").task_id, second.task_id)

    def test_due_selection_skips_unsignalled_wait_and_releases_capacity_for_fresh_progress(self):
        self.policy(active=1)
        record, quote = self.prepare(commit=False)
        self.lifecycle.arm_wait(
            actor=ACTOR,
            task_id=record.task_id,
            wait_id=str(uuid4()),
            quote=quote,
            deadline=self.clock() + timedelta(seconds=40),
        )
        self.assertIsNone(self.queue.claim_next(scope_id=ACTOR.scope_id, owner_id=str(uuid4())))
        other = self.submit("other")
        self.lifecycle.manage(
            scope_id=ACTOR.scope_id,
            task_id=other.task_id,
            policy=RetryPolicy(),
            deadline=self.clock() + timedelta(minutes=5),
        )
        claim = self.queue.claim_next(scope_id=ACTOR.scope_id, owner_id=str(uuid4()))
        self.assertEqual(claim.kind, WorkKind.INQUIRY)
        self.assertIsNone(self.queue.claim_next(scope_id=ACTOR.scope_id, owner_id=str(uuid4())))
        ManagedInquiryWorker(self.lifecycle_for(claim.grant), self.supplier.inquiry_view()).run_one(
            scope_id=ACTOR.scope_id, task_id=other.task_id
        )
        self.queue.release(claim.grant)
        self.lifecycle.signal(
            actor=ACTOR, event_id="valid-signal", confirmation=Confirmation(quote, True)
        )
        claim = self.queue.claim_next(scope_id=ACTOR.scope_id, owner_id=str(uuid4()))
        self.assertEqual((claim.kind, claim.actor_id), (WorkKind.WAIT, ACTOR.actor_id))
        self.assertIsNotNone(
            self.lifecycle_for(claim.grant).advance(actor=ACTOR, task_id=record.task_id).intent
        )
        self.queue.release(claim.grant)
        claim = self.queue.claim_next(scope_id=ACTOR.scope_id, owner_id=str(uuid4()))
        self.assertEqual(claim.kind, WorkKind.MUTATION)
        MutationWorker(self.effects_for(claim.grant), self.supplier).run_one(
            scope_id=ACTOR.scope_id, task_id=record.task_id
        )
        self.queue.release(claim.grant)
        claim = self.queue.claim_next(scope_id=ACTOR.scope_id, owner_id=str(uuid4()))
        self.assertEqual(claim.kind, WorkKind.DELIVERY)
        self.queue.release(claim.grant)

    def test_selector_does_not_enroll_unmanaged_or_repeat_completed_inquiry(self):
        self.submit("unmanaged")
        self.assertIsNone(self.queue.claim_next(scope_id=ACTOR.scope_id, owner_id=str(uuid4())))
        self.prepare("complete-inquiry", commit=False)
        self.assertIsNone(self.queue.claim_next(scope_id=ACTOR.scope_id, owner_id=str(uuid4())))
        self.assertIsNone(self.queue.claim_next(scope_id="other-scope", owner_id=str(uuid4())))

    def test_late_management_of_completed_inquiry_cannot_bypass_pending_cap(self):
        from continuity_lab.execution_models import ExecutionCapacityExceeded

        self.policy(pending=1, active=1)
        pending = self.submit("fills-pending")
        with self.assertRaises(ExecutionCapacityExceeded):
            self.lifecycle.manage(
                scope_id=ACTOR.scope_id,
                task_id=self.legacy.task_id,
                policy=RetryPolicy(),
                deadline=self.clock() + timedelta(minutes=5),
            )
        self.cases.enroll(actor=ACTOR, task_id=pending.task_id)
        self.effects.cancel(actor=ACTOR, task_id=pending.task_id, command_id="free-capacity")
        managed = self.lifecycle.manage(
            scope_id=ACTOR.scope_id,
            task_id=self.legacy.task_id,
            policy=RetryPolicy(),
            deadline=self.clock() + timedelta(minutes=5),
        )
        self.assertEqual(managed.state, LifecycleState.INQUIRY_COMPLETE)
        self.assertEqual(
            self.lifecycle.manage(
                scope_id=ACTOR.scope_id,
                task_id=self.legacy.task_id,
                policy=RetryPolicy(),
                deadline=self.clock() + timedelta(minutes=5),
            ),
            managed,
        )

    def test_retained_m1_identities_count_and_known_identity_can_enroll_at_retention_cap(self):
        self.policy(pending=2, active=1, records=2)
        self.prepare("one")
        task_id = str(uuid4())
        request = BookingChange(prior.BOOKING, date(2030, 12, 10), True)
        with closing(self.owner.connect(application_name="continuity-test")) as connection:
            connection.execute(
                sql.SQL("INSERT INTO {} VALUES (%s,%s,%s,%s,'queued',%s)").format(
                    sql.Identifier(self.schema, "tasks")
                ),
                (
                    task_id,
                    ACTOR.scope_id,
                    "legacy-m1",
                    json.dumps(request.payload(), sort_keys=True, separators=(",", ":")),
                    self.clock().isoformat(),
                ),
            )
        with self.assertRaises(IntakeCapacityExceeded):
            self.submit("new-id-rejected")
        enrolled = self.executions.submit(
            scope_id=ACTOR.scope_id, idempotency_key="legacy-m1", request=request
        )
        self.assertEqual(enrolled.execution.task_id, task_id)
        self.assertTrue(enrolled.enrolled)
        self.assertFalse(enrolled.created)
        self.assertEqual(self.submit("legacy-m1").task_id, task_id)
        self.assertEqual(len(self.executions.list(scope_id=ACTOR.scope_id)), 2)

    def test_exhausted_epoch_does_not_starve_other_eligible_work(self):
        first = self.submit("exhausted")
        second = self.submit("eligible")
        for record in (first, second):
            self.lifecycle.manage(
                scope_id=ACTOR.scope_id,
                task_id=record.task_id,
                policy=RetryPolicy(),
                deadline=self.clock() + timedelta(minutes=5),
            )
        grant = self.grant(first)
        self.leases.release(grant)
        with closing(self.owner.connect(application_name="continuity-test")) as connection:
            connection.execute(
                sql.SQL("UPDATE {} SET epoch=9223372036854775807 WHERE task_id=%s").format(
                    sql.Identifier(self.schema, "execution_leases")
                ),
                (first.task_id,),
            )
        claim = self.queue.claim_next(scope_id=ACTOR.scope_id, owner_id=str(uuid4()))
        self.assertEqual(claim.grant.task_id, second.task_id)
        ManagedInquiryWorker(self.lifecycle_for(claim.grant), self.supplier.inquiry_view()).run_one(
            scope_id=ACTOR.scope_id, task_id=second.task_id
        )
        self.queue.release(claim.grant)
        self.assertEqual(
            self.executions.get(scope_id=ACTOR.scope_id, task_id=first.task_id).task_id,
            first.task_id,
        )

    def test_queue_snapshot_qualifies_expired_ownership_and_terminal_delivery(self):
        from continuity_lab.outbox_delivery import CompletionDeliveryWorker

        record = self.submit("observed")
        self.cases.enroll(actor=ACTOR, task_id=record.task_id)
        self.assertEqual(self.queue.snapshot(scope_id=ACTOR.scope_id).outstanding, 1)
        grant = self.grant(record)
        self.assertEqual(self.queue.snapshot(scope_id=ACTOR.scope_id).active, 1)
        self.expire(grant)
        snapshot = self.queue.snapshot(scope_id=ACTOR.scope_id)
        self.assertEqual(snapshot.active, 0)
        self.assertGreaterEqual(snapshot.recovery_lag_seconds, 0)
        self.effects.cancel(actor=ACTOR, task_id=record.task_id, command_id="cancel")
        fresh = self.grant(record)
        path = self.folder / "snapshot-sink.sqlite3"
        initialize_completion_sink(path)
        sink = CompletionSink(path, clock=self.clock)
        CompletionDeliveryWorker(self.effects_for(fresh), sink).run_one(
            scope_id=ACTOR.scope_id, task_id=record.task_id
        )
        self.expire(fresh)
        snapshot = self.queue.snapshot(scope_id=ACTOR.scope_id)
        self.assertEqual(
            (snapshot.outstanding, snapshot.active, snapshot.recovery_lag_seconds), (0, 0, 0)
        )
        self.assertEqual(self.queue.snapshot(scope_id="foreign").outstanding, 0)

    def test_completed_inquiry_without_wait_expires_without_losing_known_result(self):
        self.policy(pending=1, active=1)
        record, _ = self.prepare(commit=False)
        known = self.executions.get(scope_id=ACTOR.scope_id, task_id=record.task_id)
        with self.assertRaises(IntakeCapacityExceeded):
            self.submit("blocked")
        self.clock.value += timedelta(minutes=6)
        claim = self.queue.claim_next(scope_id=ACTOR.scope_id, owner_id=str(uuid4()))
        self.assertEqual(claim.kind, WorkKind.INQUIRY)
        result = ManagedInquiryWorker(
            self.lifecycle_for(claim.grant), self.supplier.inquiry_view()
        ).run_one(scope_id=ACTOR.scope_id, task_id=record.task_id)
        self.assertEqual(result.state, LifecycleState.FAILED)
        self.assertEqual(result.error_code.value, "deadline_expired")
        self.queue.release(claim.grant)
        self.assertEqual(
            self.executions.get(scope_id=ACTOR.scope_id, task_id=record.task_id), known
        )
        self.assertEqual(self.supplier.count_inquiries(scope_id=ACTOR.scope_id), 1)
        self.assertIsNone(self.effects.completion(actor=ACTOR, task_id=record.task_id))
        self.assertNotEqual(self.submit("useful-new").task_id, record.task_id)
