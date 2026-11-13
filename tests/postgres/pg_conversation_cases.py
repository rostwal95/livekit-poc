"""Real PostgreSQL atomic acceptance, exact proposal and bounded projection tests."""

import json
import os
import sys
import unittest
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import pg_mutation_cases as prior
from psycopg import sql

from continuity_lab.authorization import AuthenticatedActor
from continuity_lab.case_models import Confirmation, QuoteSnapshot, canonical
from continuity_lab.case_projection import PostgresCaseProjection, parse_confirmation_payload
from continuity_lab.completion_sink import CompletionSink, initialize_completion_sink
from continuity_lab.execution_models import ExecutionNotFound, UnsupportedOperation
from continuity_lab.lease_models import CoordinationPolicy
from continuity_lab.lifecycle_models import LifecycleState
from continuity_lab.managed_admission import PostgresManagedAdmission
from continuity_lab.managed_inquiry_worker import ManagedInquiryWorker
from continuity_lab.models import BookingChange, IdempotencyConflict, IntakeCapacityExceeded
from continuity_lab.mutation_worker import MutationWorker
from continuity_lab.outbox_delivery import CompletionDeliveryWorker
from continuity_lab.postgres_case import PostgresCaseAuthority
from continuity_lab.postgres_effects import PostgresEffects
from continuity_lab.postgres_leases import PostgresLeases
from continuity_lab.postgres_lifecycle import PostgresLifecycle
from continuity_lab.postgres_migrations import upgrade_v4
from continuity_lab.postgres_unit_of_work import protected_transaction
from continuity_lab.quote_producer import TrustedQuoteProducer
from harness.process_control import OwnedProcess

ACTOR = prior.ACTOR
REQUEST = BookingChange(prior.BOOKING, date(2030, 12, 10), True)
CHILD = r"""
import os,json,sys
from datetime import datetime,date
from continuity_lab.authorization import AuthenticatedActor
from continuity_lab.models import BookingChange
from continuity_lab.managed_admission import PostgresManagedAdmission
from continuity_lab.postgres_store import PostgresExecutionStore
from continuity_lab.postgres_settings import PostgresSettings
actor,scope,key,now,crash=sys.argv[1:]
clock=lambda:datetime.fromisoformat(now)
store=PostgresExecutionStore(PostgresSettings.from_env(),clock=clock)
def failpoint(point):
 if crash=='1' and point=='managed_admission.after_commit':os._exit(71)
result=PostgresManagedAdmission(store,clock=clock,failpoint=failpoint).accept(actor=AuthenticatedActor(actor,scope),idempotency_key=key,request=BookingChange('DEMO-BK-001',date(2030,12,10),True))
print(json.dumps({'created':result.created,'task_id':result.case.task_id,'case_id':result.case.case_id,'deadline':result.lifecycle.deadline}),flush=True)
"""


class PostgresConversationCases(unittest.TestCase):
    setUpClass = classmethod(prior.PostgresMutationCases.setUpClass.__func__)
    drop_schema = prior.PostgresMutationCases.drop_schema

    def setUp(self):
        prior.PostgresMutationCases.setUp(self)
        upgrade_v4(self.owner, policy=CoordinationPolicy(10, 2, 50, 30))
        self.admission = PostgresManagedAdmission(
            self.executions, cases=self.cases, lifecycle=self.lifecycle, clock=self.clock
        )
        self.projection = PostgresCaseProjection(
            self.executions, cases=self.cases, lifecycle=self.lifecycle, effects=self.effects
        )
        self.producer = TrustedQuoteProducer(
            self.cases, self.lifecycle, self.supplier, clock=self.clock
        )
        self.leases = PostgresLeases(self.executions)

    def accept(self, key="one", *, actor=ACTOR):
        return self.admission.accept(actor=actor, idempotency_key=key, request=REQUEST)

    def count(self, table):
        with closing(self.runtime.connect(application_name="continuity-test")) as connection:
            return connection.execute(
                sql.SQL("SELECT COUNT(*) AS n FROM {}").format(sql.Identifier(self.schema, table))
            ).fetchone()["n"]

    def policy(self, pending=10, records=50):
        with closing(self.owner.connect(application_name="continuity-test")) as connection:
            connection.execute(
                sql.SQL(
                    "UPDATE {} SET maximum_pending=%s,maximum_active=1,maximum_records=%s"
                ).format(sql.Identifier(self.schema, "execution_limits")),
                (pending, records),
            )

    def investigate(self, acceptance):
        grant = self.leases.acquire(
            scope_id=ACTOR.scope_id, task_id=acceptance.case.task_id, owner_id=str(uuid4())
        )
        try:
            lifecycle = PostgresLifecycle(
                self.executions, cases=self.cases, clock=self.clock, worker_lease=grant
            )
            result = ManagedInquiryWorker(lifecycle, self.supplier.inquiry_view()).run_one(
                scope_id=ACTOR.scope_id, task_id=acceptance.case.task_id
            )
            self.assertEqual(result.state, LifecycleState.INQUIRY_COMPLETE)
        finally:
            self.leases.release(grant)

    def prepare(self, key="one"):
        accepted = self.accept(key)
        self.investigate(accepted)
        receipt = self.producer.prepare(
            actor=ACTOR,
            task_id=accepted.case.task_id,
            expected_revision=accepted.case.revision,
            command_id="proposal-" + key,
        )
        return accepted, receipt

    def child(self, key, crash=False):
        folder = self.folder / ("accept-" + uuid4().hex)
        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(prior.ROOT),
            "PYTHONDONTWRITEBYTECODE": "1",
            "P1_POSTGRES_HOST": self.runtime.host,
            "P1_POSTGRES_PORT": str(self.runtime.port),
            "P1_POSTGRES_DB": self.runtime.dbname,
            "P1_POSTGRES_USER": self.runtime.user,
            "P1_POSTGRES_PASSWORD": self.runtime.password,
            "P1_POSTGRES_SCHEMA": self.schema,
        }
        return OwnedProcess(
            [
                sys.executable,
                "-c",
                CHILD,
                ACTOR.actor_id,
                ACTOR.scope_id,
                key,
                self.clock().isoformat(),
                "1" if crash else "0",
            ],
            cwd=prior.ROOT,
            env=env,
            output_directory=folder,
        )

    def test_acceptance_rolls_back_every_partial_boundary_then_valid_work_progresses(self):
        for point in (
            "managed_admission.after_inquiry",
            "managed_admission.after_case",
            "managed_admission.after_control",
            "managed_admission.before_commit",
        ):
            with self.subTest(point=point):

                def fail(hit, expected=point):
                    if hit == expected:
                        raise RuntimeError("SECRET_SENTINEL")

                port = PostgresManagedAdmission(
                    self.executions,
                    cases=self.cases,
                    lifecycle=self.lifecycle,
                    clock=self.clock,
                    failpoint=fail,
                )
                with self.assertRaises(RuntimeError):
                    port.accept(actor=ACTOR, idempotency_key="atomic", request=REQUEST)
                for table in ("tasks", "executions", "cases", "execution_controls"):
                    self.assertEqual(self.count(table), 0)
        accepted = self.accept("atomic")
        self.assertTrue(accepted.created)
        self.assertNotEqual(accepted.case.case_id, accepted.execution.task_id)
        for table in ("tasks", "executions", "cases", "execution_controls"):
            self.assertEqual(self.count(table), 1)
        self.investigate(accepted)

    def test_lost_ack_replay_preserves_ids_original_deadline_after_expiry_and_capacity(self):
        def lost(point):
            if point == "managed_admission.after_commit":
                raise RuntimeError("lost acknowledgement")

        port = PostgresManagedAdmission(
            self.executions,
            cases=self.cases,
            lifecycle=self.lifecycle,
            clock=self.clock,
            failpoint=lost,
        )
        with self.assertRaises(RuntimeError):
            port.accept(actor=ACTOR, idempotency_key="same", request=REQUEST)
        row = self.executions.list(scope_id=ACTOR.scope_id)[0]
        original = self.lifecycle.get(scope_id=ACTOR.scope_id, task_id=row.task_id)
        self.policy(pending=1, records=1)
        self.clock.value += timedelta(minutes=20)
        replay = self.accept("same")
        self.assertFalse(replay.created)
        self.assertEqual(replay.case.task_id, row.task_id)
        self.assertEqual(replay.lifecycle.deadline, original.deadline)
        with self.assertRaises(IntakeCapacityExceeded):
            self.accept("new")
        self.assertEqual(self.count("tasks"), 1)

    def test_real_process_loss_after_atomic_commit_retains_all_three_owners(self):
        with self.child("crashed", True) as child:
            self.assertEqual(child.wait(timeout=10).returncode, 71)
        for table in ("tasks", "executions", "cases", "execution_controls"):
            self.assertEqual(self.count(table), 1)
        with self.child("crashed") as child:
            self.assertEqual(child.wait(timeout=10).returncode, 0)
            record = json.loads(child.output_tail("stdout"))
        self.assertFalse(record["created"])
        replay = self.accept("crashed")
        self.assertEqual(
            (record["task_id"], record["case_id"], record["deadline"]),
            (replay.case.task_id, replay.case.case_id, replay.lifecycle.deadline),
        )

    def test_two_independent_acceptors_return_one_original_identity(self):
        with self.child("concurrent") as first, self.child("concurrent") as second:
            self.assertEqual(first.wait(timeout=10).returncode, 0)
            self.assertEqual(second.wait(timeout=10).returncode, 0)
            values = [json.loads(child.output_tail("stdout")) for child in (first, second)]
        self.assertEqual(sum(item["created"] for item in values), 1)
        self.assertEqual(values[0]["task_id"], values[1]["task_id"])
        self.assertEqual(values[0]["case_id"], values[1]["case_id"])
        self.assertEqual(self.count("tasks"), 1)

    def test_request_conflict_and_owner_isolation_precede_capacity(self):
        accepted = self.accept()
        self.policy(pending=1, records=1)
        with self.assertRaises(IdempotencyConflict):
            self.admission.accept(
                actor=ACTOR,
                idempotency_key="one",
                request=BookingChange(prior.BOOKING, date(2030, 12, 11), True),
            )
        with self.assertRaises(ExecutionNotFound):
            self.accept(actor=AuthenticatedActor("peer", ACTOR.scope_id))
        with self.assertRaises(ExecutionNotFound):
            self.projection.get(
                actor=AuthenticatedActor(ACTOR.actor_id, "foreign"),
                task_id=accepted.case.task_id,
                cursor="malformed",
            )
        self.assertFalse(self.accept().created)

    def test_legacy_or_partial_inquiry_is_not_adopted_into_a_new_owner_or_deadline(self):
        original = self.executions.submit(
            scope_id=ACTOR.scope_id, idempotency_key="legacy", request=REQUEST
        ).execution
        with self.assertRaises(UnsupportedOperation):
            self.accept("legacy")
        self.assertEqual(self.count("cases"), 0)
        self.assertEqual(self.count("execution_controls"), 0)
        self.cases.enroll(actor=ACTOR, task_id=original.task_id)
        with self.assertRaises(UnsupportedOperation):
            self.accept("legacy")
        self.assertEqual(self.count("execution_controls"), 0)

    def test_case_capacity_rejects_without_stranding_new_execution(self):
        first = self.accept()
        cases = PostgresCaseAuthority(self.executions, clock=self.clock, maximum_cases=1)
        lifecycle = PostgresLifecycle(self.executions, cases=cases, clock=self.clock)
        limited = PostgresManagedAdmission(
            self.executions, cases=cases, lifecycle=lifecycle, clock=self.clock
        )
        from continuity_lab.case_models import CaseCapacityExceeded

        with self.assertRaises(CaseCapacityExceeded):
            limited.accept(actor=ACTOR, idempotency_key="second", request=REQUEST)
        self.assertEqual(self.count("tasks"), 1)
        self.assertEqual(self.count("executions"), 1)
        self.assertFalse(
            limited.accept(actor=ACTOR, idempotency_key="one", request=REQUEST).created
        )
        self.assertNotEqual(self.accept("second").case.task_id, first.case.task_id)

    def test_quote_and_wait_are_atomic_and_independent_booking_read_holds_no_sql_lock(self):
        accepted = self.accept()
        self.investigate(accepted)
        parent = self

        class CheckingSupplier:
            provider_id = parent.supplier.provider_id

            def booking(self, **kwargs):
                with protected_transaction(parent.executions):
                    pass
                return parent.supplier.booking(**kwargs)

        def fail(point):
            if point == "quote_producer.after_quote":
                raise RuntimeError("stop before wait")

        producer = TrustedQuoteProducer(
            self.cases, self.lifecycle, CheckingSupplier(), clock=self.clock, failpoint=fail
        )
        with self.assertRaises(RuntimeError):
            producer.prepare(
                actor=ACTOR,
                task_id=accepted.case.task_id,
                expected_revision=0,
                command_id="atomic-quote",
            )
        self.assertEqual(self.count("quotes"), 0)
        self.assertEqual(self.count("execution_waits"), 0)
        self.assertEqual(
            self.lifecycle.get(scope_id=ACTOR.scope_id, task_id=accepted.case.task_id).state,
            LifecycleState.INQUIRY_COMPLETE,
        )
        receipt = self.producer.prepare(
            actor=ACTOR,
            task_id=accepted.case.task_id,
            expected_revision=0,
            command_id="atomic-quote",
        )
        self.assertTrue(receipt.created)
        self.assertEqual(receipt.quote.expected_supplier_revision, 0)
        self.assertEqual(receipt.quote.supplier_id, self.supplier.provider_id)
        self.assertEqual(self.count("quotes"), 1)
        self.assertEqual(self.count("execution_waits"), 1)

    def test_quote_lost_ack_replays_before_expiry_or_unavailable_supplier(self):
        accepted = self.accept()
        self.investigate(accepted)

        def lost(point):
            if point == "quote_producer.after_commit":
                raise RuntimeError("lost")

        producer = TrustedQuoteProducer(
            self.cases, self.lifecycle, self.supplier, clock=self.clock, failpoint=lost
        )
        with self.assertRaises(RuntimeError):
            producer.prepare(
                actor=ACTOR, task_id=accepted.case.task_id, expected_revision=0, command_id="replay"
            )
        self.clock.value += timedelta(minutes=10)

        class Unavailable:
            @property
            def provider_id(self):
                raise AssertionError("Known receipt must not read provider")

            def booking(self, **kwargs):
                raise AssertionError("Known receipt must not call provider")

        producer = TrustedQuoteProducer(self.cases, self.lifecycle, Unavailable(), clock=self.clock)
        receipt = producer.prepare(
            actor=ACTOR, task_id=accepted.case.task_id, expected_revision=0, command_id="replay"
        )
        self.assertFalse(receipt.created)
        with self.assertRaises(IdempotencyConflict):
            producer.prepare(
                actor=ACTOR, task_id=accepted.case.task_id, expected_revision=1, command_id="replay"
            )
        self.assertEqual(self.count("quotes"), 1)
        self.assertEqual(self.count("execution_waits"), 1)

    def test_quote_rechecks_revision_after_supplier_read_and_preserves_business_deadline(self):
        accepted = self.accept()
        self.investigate(accepted)
        original = accepted.lifecycle.deadline
        parent = self

        class Revising:
            provider_id = parent.supplier.provider_id

            def booking(self, **kwargs):
                value = parent.supplier.booking(**kwargs)
                parent.cases.revise(
                    actor=ACTOR,
                    task_id=accepted.case.task_id,
                    expected_revision=0,
                    request=BookingChange(prior.BOOKING, date(2030, 12, 11), True),
                )
                return value

        from continuity_lab.case_models import StaleRevision

        with self.assertRaises(StaleRevision):
            TrustedQuoteProducer(self.cases, self.lifecycle, Revising(), clock=self.clock).prepare(
                actor=ACTOR, task_id=accepted.case.task_id, expected_revision=0, command_id="race"
            )
        self.assertEqual(self.count("quotes"), 0)
        self.assertEqual(self.count("execution_waits"), 0)
        self.assertEqual(
            self.lifecycle.get(scope_id=ACTOR.scope_id, task_id=accepted.case.task_id).deadline,
            original,
        )
        from continuity_lab.execution_models import TransitionConflict

        with self.assertRaises(TransitionConflict):
            self.producer.prepare(
                actor=ACTOR, task_id=accepted.case.task_id, expected_revision=1, command_id="fresh"
            )
        new_request = BookingChange(prior.BOOKING, date(2030, 12, 11), True)
        fresh = self.admission.accept(
            actor=ACTOR, idempotency_key="fresh-investigation", request=new_request
        )
        self.investigate(fresh)
        receipt = self.producer.prepare(
            actor=ACTOR, task_id=fresh.case.task_id, expected_revision=0, command_id="fresh"
        )
        self.assertEqual(receipt.quote.new_check_in, new_request.new_check_in)
        self.assertLessEqual(receipt.quote.expires_at, fresh.lifecycle.deadline)

    def test_unavailable_inquiry_cannot_produce_quote_and_other_work_progresses(self):
        from continuity_lab.execution_models import InquiryResult, TransitionConflict
        from continuity_lab.supplier import InquiryCapabilities, InquiryObservation

        accepted = self.accept()

        class Unavailable:
            capabilities = InquiryCapabilities()

            def lookup(self, **_kwargs):
                return None

            def inquire(self, *, scope_id, effect_id, request):
                return InquiryObservation(
                    InquiryResult(request.booking_reference, request.new_check_in, False),
                    effect_id,
                    True,
                )

        grant = self.leases.acquire(
            scope_id=ACTOR.scope_id, task_id=accepted.case.task_id, owner_id=str(uuid4())
        )
        try:
            lifecycle = PostgresLifecycle(
                self.executions, cases=self.cases, clock=self.clock, worker_lease=grant
            )
            self.assertEqual(
                ManagedInquiryWorker(lifecycle, Unavailable())
                .run_one(scope_id=ACTOR.scope_id, task_id=accepted.case.task_id)
                .state,
                LifecycleState.INQUIRY_COMPLETE,
            )
        finally:
            self.leases.release(grant)
        with self.assertRaises(TransitionConflict):
            self.producer.prepare(
                actor=ACTOR,
                task_id=accepted.case.task_id,
                expected_revision=0,
                command_id="unavailable",
            )
        self.assertEqual(self.count("quotes"), 0)
        self.assertEqual(self.count("execution_waits"), 0)
        other = self.accept("available")
        self.investigate(other)
        self.assertTrue(
            self.producer.prepare(
                actor=ACTOR, task_id=other.case.task_id, expected_revision=0, command_id="available"
            ).created
        )

    def test_projection_current_state_pagination_and_changed_snapshot_reset(self):
        accepted, receipt = self.prepare()
        first = self.projection.get(actor=ACTOR, task_id=accepted.case.task_id, limit=1).payload()
        self.assertEqual(first["case_revision"], "0")
        self.assertEqual(first["request_key"], "one")
        self.assertEqual(first["confirmation"]["state"], "required")
        self.assertIsNone(first["outcome"])
        self.assertIsNone(first["delivery"])
        self.assertEqual(first["inquiry"]["request"], REQUEST.payload())
        self.assertTrue(first["has_more"])
        second = self.projection.get(
            actor=ACTOR, task_id=accepted.case.task_id, cursor=first["next_cursor"], limit=1
        ).payload()
        self.assertFalse(second["cursor_reset"])
        self.assertEqual(first["projection_revision"], second["projection_revision"])
        self.assertNotEqual(first["events"][0]["event_id"], second["events"][0]["event_id"])
        self.lifecycle.signal(
            actor=ACTOR, event_id="exact-signal", confirmation=Confirmation(receipt.quote, True)
        )
        self.lifecycle.advance(actor=ACTOR, task_id=accepted.case.task_id)
        changed = self.projection.get(
            actor=ACTOR, task_id=accepted.case.task_id, cursor=first["next_cursor"], limit=1
        ).payload()
        self.assertTrue(changed["cursor_reset"])
        self.assertNotEqual(changed["projection_revision"], first["projection_revision"])
        self.assertEqual(changed["confirmation"]["state"], "committed")
        self.assertIsNone(changed["outcome"])
        self.assertEqual(
            changed["quote"]["confirmation_payload"], canonical(receipt.quote.payload())
        )

    def test_business_outcome_delivery_and_later_cancel_remain_separate(self):
        accepted, receipt = self.prepare()
        self.lifecycle.signal(
            actor=ACTOR, event_id="signal", confirmation=Confirmation(receipt.quote, True)
        )
        self.lifecycle.advance(actor=ACTOR, task_id=accepted.case.task_id)
        grant = self.leases.acquire(
            scope_id=ACTOR.scope_id, task_id=accepted.case.task_id, owner_id=str(uuid4())
        )
        effects = PostgresEffects(
            self.executions, cases=self.cases, clock=self.clock, worker_lease=grant
        )
        MutationWorker(effects, self.supplier).run_one(
            scope_id=ACTOR.scope_id, task_id=accepted.case.task_id
        )
        before = self.projection.get(actor=ACTOR, task_id=accepted.case.task_id).payload()
        self.assertEqual(before["outcome"]["state"], "succeeded")
        self.assertEqual(before["delivery"]["state"], "pending")
        path = self.folder / "receiver.sqlite3"
        initialize_completion_sink(path)
        CompletionDeliveryWorker(effects, CompletionSink(path, clock=self.clock)).run_one(
            scope_id=ACTOR.scope_id, task_id=accepted.case.task_id
        )
        self.effects.cancel(actor=ACTOR, task_id=accepted.case.task_id, command_id="too-late")
        after = self.projection.get(actor=ACTOR, task_id=accepted.case.task_id).payload()
        self.assertEqual(after["confirmation"]["state"], "committed")
        self.assertEqual(after["outcome"], before["outcome"])
        self.assertEqual(after["delivery"]["state"], "delivered")
        self.assertEqual(after["effect"]["result"]["revision"], "1")
        self.assertEqual(after["outcome"]["result"]["previous_revision"], "0")
        self.assertEqual(after["lifecycle"]["lease"]["epoch"], str(grant.epoch))
        self.leases.release(grant)

    def test_projection_preserves_bigint_confirmation_values_without_js_roundtrip(self):
        accepted = self.accept()
        self.investigate(accepted)
        huge = 9007199254740993
        with closing(self.owner.connect(application_name="continuity-test")) as connection:
            connection.execute(
                sql.SQL("UPDATE {} SET revision=%s WHERE task_id=%s").format(
                    sql.Identifier(self.schema, "cases")
                ),
                (huge, accepted.case.task_id),
            )
        receipt = self.producer.prepare(
            actor=ACTOR, task_id=accepted.case.task_id, expected_revision=huge, command_id="bigint"
        )
        body = self.projection.get(actor=ACTOR, task_id=accepted.case.task_id).payload()
        self.assertEqual(body["case_revision"], str(huge))
        self.assertEqual(body["quote"]["revision"], str(huge))
        self.assertEqual(
            parse_confirmation_payload(body["quote"]["confirmation_payload"], explicit=True).quote,
            receipt.quote,
        )

    def test_history_window_is_explicitly_truncated_and_response_remains_bounded(self):
        accepted = self.accept()
        self.investigate(accepted)
        with closing(self.owner.connect(application_name="continuity-test")) as connection:
            for index in range(110):
                quote = QuoteSnapshot(
                    str(uuid4()),
                    accepted.case.task_id,
                    0,
                    prior.BOOKING,
                    REQUEST.new_check_in,
                    2500,
                    "USD",
                    (self.clock() + timedelta(minutes=1)).isoformat(),
                    accepted.case.case_id,
                    0,
                    self.supplier.provider_id,
                )
                stamp = (self.clock() - timedelta(seconds=index)).isoformat()
                connection.execute(
                    sql.SQL("INSERT INTO {} VALUES (%s,%s,%s,%s,%s)").format(
                        sql.Identifier(self.schema, "quotes")
                    ),
                    (quote.quote_id, quote.task_id, 0, canonical(quote.payload()), stamp),
                )
        body = self.projection.get(actor=ACTOR, task_id=accepted.case.task_id, limit=50).payload()
        self.assertTrue(body["history_truncated"])
        self.assertEqual(body["events_total"], 112)
        self.assertEqual(len(body["events"]), 50)
        self.assertTrue(body["has_more"])
        self.assertLessEqual(len(json.dumps(body).encode()), 65536)
        ids = set()
        cursor = None
        for _ in range(5):
            page = self.projection.get(
                actor=ACTOR, task_id=accepted.case.task_id, cursor=cursor, limit=50
            ).payload()
            for event in page["events"]:
                self.assertNotIn(event["event_id"], ids)
                ids.add(event["event_id"])
            cursor = page["next_cursor"]
            if not page["has_more"]:
                break
        self.assertEqual(len(ids), 102)

    def test_projection_owner_check_precedes_malformed_cursor_and_history_reads(self):
        accepted = self.accept()
        for actor in (
            AuthenticatedActor("peer", ACTOR.scope_id),
            AuthenticatedActor(ACTOR.actor_id, "foreign"),
        ):
            with self.subTest(actor=actor), self.assertRaises(ExecutionNotFound):
                self.projection.get(
                    actor=actor, task_id=accepted.case.task_id, cursor="SECRET_SENTINEL"
                )
        with self.assertRaises(ValueError):
            self.projection.get(actor=ACTOR, task_id=accepted.case.task_id, cursor="malformed")
        self.assertEqual(self.count("cases"), 1)

    def test_fixture_matches_actual_projection_keys_and_exact_quote_serializer(self):
        accepted, receipt = self.prepare()
        fixture_path = (
            Path(__file__).resolve().parents[2] / "contracts/business/case-projection.json"
        )
        fixture = json.loads(fixture_path.read_text())
        body = self.projection.get(actor=ACTOR, task_id=accepted.case.task_id).payload()
        self.assertEqual(set(body), set(fixture))
        for key in ("inquiry", "lifecycle", "confirmation"):
            self.assertEqual(set(body[key]), set(fixture[key]))
        from continuity_lab.case_projection import quote_payload

        exact = parse_confirmation_payload(
            fixture["quote"]["confirmation_payload"], explicit=True
        ).quote
        self.assertEqual(quote_payload(exact), fixture["quote"])
        self.assertEqual(body["quote"]["confirmation_payload"], canonical(receipt.quote.payload()))

    def test_peer_owner_cannot_distinguish_changed_payload_from_known_replay(self):
        accepted = self.accept()
        peer = AuthenticatedActor("peer", ACTOR.scope_id)
        for request in (REQUEST, BookingChange(prior.BOOKING, date(2030, 12, 11), True)):
            with self.subTest(request=request), self.assertRaises(ExecutionNotFound):
                self.admission.accept(actor=peer, idempotency_key="one", request=request)
        self.assertEqual(self.count("tasks"), 1)
        self.assertEqual(self.accept().case.task_id, accepted.case.task_id)
