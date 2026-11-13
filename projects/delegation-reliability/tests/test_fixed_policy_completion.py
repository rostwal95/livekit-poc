"""Typed v2 delivery ports; real persistence and HTTP have separate actual gates."""

import asyncio
import copy
import logging
import time
import unittest
from dataclasses import replace
from uuid import uuid4

import test_runner as legacy
from test_completion import DeliveryStore
from test_fixed_policy_execution import Specialist, setup
from test_runner import FakeCases, FakeExecution

from continuity_lab.delivery_api import DeliveryReceipt, DeliverySnapshot
from continuity_lab.work_api import WorkError, WorkScope
from delegation_reliability import (
    CompletionError,
    DelegationDeliveryClient,
    DelegationRunner,
    DeliveryBinding,
    FixedPolicyDeliveryClient,
    FixedPolicyResultReadPort,
    FixedPolicyRunner,
    ResultReceiverPort,
)
from delegation_reliability.contracts import Scope, canonical
from delegation_reliability.fixed_policy_contracts import encode_fixed_policy_result
from delegation_reliability.security import EvidenceRecord


class StructuralReceiver:
    """A minimal structural consumer, without the P1 filesystem receiver class."""

    def __init__(self):
        self._receiver_id = str(uuid4())
        self.values = {}
        self.intents = []
        self.accepted = self.found = self.closed = 0
        self.entered = asyncio.Event()
        self.release = None
        self.find_release = None
        self.find_entered = asyncio.Event()
        self.failure = None
        self.ack = False
        self.after_find = None

    @property
    def receiver_id(self):
        return self._receiver_id

    async def find(self, intent):
        self.found += 1
        self.find_entered.set()
        if self.find_release is not None:
            await self.find_release.wait()
        if self.failure is not None:
            raise self.failure
        if self.after_find is not None:
            self.after_find()
        return self.values.get(intent.delivery_id)

    async def accept(self, intent):
        self.accepted += 1
        self.intents.append(intent)
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        if self.failure is not None:
            raise self.failure
        receipt = self.values.setdefault(
            intent.delivery_id,
            DeliveryReceipt(
                intent.delivery_id,
                str(uuid4()),
                intent.receiver_id,
                intent.recipient_id,
                intent.result_sha256,
                time.time_ns() // 1_000_000,
            ),
        )
        if self.ack:
            raise WorkError("acknowledgement_unknown")
        return receipt

    async def close(self):
        self.closed += 1


class ResultReads:
    """The application owns this reader; the delivery facade must not close it."""

    def __init__(self, value):
        self.value = value
        self.count = 0
        self.entered = asyncio.Event()
        self.release = None

    async def inspect(self, work_id):
        self.count += 1
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        return self.value


class FixedPolicyCompletionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.runners = []
        self.clients = []
        self.releases = []
        self.tasks = []
        self.request, self.evidence, self.view = await self.valid_view()
        self.results = ResultReads(self.view)
        self.store = DeliveryStore(self.view)
        self.receiver = StructuralReceiver()
        self.binding = DeliveryBinding(
            self.request.case_id, self.request.conversation_id, "recipient_fixed"
        )
        self.work_id = self.view.execution.record.work_id

    async def asyncTearDown(self):
        for event in self.releases:
            event.set()
        for event in (
            self.results.release,
            self.store.prepare_release,
            self.receiver.release,
            self.receiver.find_release,
        ):
            if event is not None:
                event.set()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        for client in self.clients:
            await client.close()
        for runner in self.runners:
            await runner.close()

    async def valid_view(self, values=(10,)):
        request, evidence = setup(values)
        execution = FakeExecution(request)
        runner = FixedPolicyRunner(
            executions=execution,
            scope=request.scope,
            owner_id=str(uuid4()),
            specialist=Specialist(),
            case_authority=FakeCases(request),
            evidence=evidence,
        )
        self.runners.append(runner)
        run = await runner.run_once(execution.record.work_id, "issue_fixed_delivery")
        return request, evidence, run.view

    def client(self, **options):
        receiver: ResultReceiverPort = self.receiver
        results: FixedPolicyResultReadPort = self.results
        client = FixedPolicyDeliveryClient(
            results=results,
            deliveries=self.store,
            receiver=receiver,
            scope=self.request.scope,
            evidence=self.evidence,
            bindings=(self.binding,),
            **options,
        )
        self.clients.append(client)
        return client

    async def settled(self, client):
        async with asyncio.timeout(1):
            while client.pending_count:
                await asyncio.sleep(0)

    def spawned(self, awaitable):
        task = asyncio.create_task(awaitable)
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        self.tasks.append(task)
        return task

    def changed_result(self, **changes):
        result = replace(self.view.result, **changes)
        recorded = replace(self.view.execution.result, body=canonical(result.to_wire()))
        return replace(
            self.view, execution=replace(self.view.execution, result=recorded), result=result
        )

    def no_writes(self):
        self.assertEqual(
            (self.store.prepared, self.store.begun, self.store.recorded, self.receiver.accepted),
            (0, 0, 0, 0),
        )

    async def test_exact_v2_bytes_witnesses_and_structural_receiver_route(self):
        client = self.client()
        first = await client.deliver_once(self.work_id)
        intent = first.snapshot.intent
        self.assertEqual(first.state, "accepted")
        self.assertTrue(first.receiver_invoked)
        self.assertEqual(intent.body, encode_fixed_policy_result(self.view.result))
        self.assertEqual(intent.result_sha256, self.view.execution.result.sha256)
        self.assertEqual(intent.attempt_id, self.view.execution.current_attempt.attempt_id)
        self.assertEqual(intent.scope, self.view.execution.record.scope)
        self.assertEqual(
            (intent.receiver_id, intent.recipient_id),
            (self.receiver.receiver_id, "recipient_fixed"),
        )
        self.assertEqual(self.view.result.rule_refs[0].minimum_notice_days, 7)
        self.assertEqual(self.view.result.fact_refs[0].days_before_arrival, 10)
        self.assertEqual(self.receiver.intents, [intent])
        replay = await client.deliver_once(self.work_id)
        self.assertEqual(replay.snapshot, first.snapshot)
        self.assertFalse(replay.receiver_invoked)
        self.assertEqual((self.receiver.accepted, self.store.recorded), (1, 1))
        self.assertEqual((await client.inspect(self.work_id)).snapshot, first.snapshot)

    async def test_supported_false_policy_answer_is_a_deliverable_candidate(self):
        request, evidence, view = await self.valid_view((3,))
        self.request, self.evidence, self.view = request, evidence, view
        self.results.value, self.store.value = view, view
        self.work_id = view.execution.record.work_id
        self.assertIs(view.result.eligible, False)
        self.assertEqual(view.applicability, "candidate")
        result = await self.client().deliver_once(self.work_id)
        self.assertEqual(result.state, "accepted")
        self.assertEqual(result.snapshot.intent.body, encode_fixed_policy_result(view.result))
        self.assertEqual(self.receiver.accepted, 1)

    async def test_v1_and_v2_delivery_facades_reject_each_others_views(self):
        old_request = legacy.request()
        execution = FakeExecution(old_request)
        runner = DelegationRunner(
            executions=execution,
            scope=old_request.scope,
            owner_id=str(uuid4()),
            specialist=legacy.FakeSpecialist(),
            case_authority=FakeCases(old_request),
            evidence=(EvidenceRecord(old_request.scope, old_request.evidence[0], legacy.POLICY),),
        )
        self.runners.append(runner)
        old_view = (await runner.run_once(execution.record.work_id, "legacy_delivery")).view
        self.results.value = old_view
        with self.assertRaises(CompletionError) as caught:
            await self.client().deliver_once(old_view.execution.record.work_id)
        self.assertEqual(caught.exception.code, "invalid_stored_state")
        self.no_writes()

        self.results.value = self.view
        old_client = DelegationDeliveryClient(
            results=self.results,
            deliveries=self.store,
            receiver=self.receiver,
            scope=self.request.scope,
            evidence=self.evidence,
            bindings=(self.binding,),
        )
        self.clients.append(old_client)
        with self.assertRaises(CompletionError) as caught:
            await old_client.deliver_once(self.work_id)
        self.assertEqual(caught.exception.code, "invalid_stored_state")
        self.no_writes()

    async def test_malformed_request_issuance_result_and_facts_reject_then_useful_progress(self):
        variants = [("wrong_view", object())]
        changed = copy.deepcopy(self.view)
        object.__setattr__(changed.request, "conversation_id", "changed_conversation")
        variants.append(("changed_request", changed))
        changed = copy.deepcopy(self.view)
        object.__setattr__(changed.execution.record, "scope", WorkScope("foreign", "foreign"))
        variants.append(("foreign_record", changed))
        changed = copy.deepcopy(self.view)
        object.__setattr__(
            changed.execution.current_attempt,
            "record",
            replace(changed.execution.current_attempt.record, accepted_at_ms=0),
        )
        variants.append(("changed_issued_record", changed))
        changed = copy.deepcopy(self.view)
        object.__setattr__(changed.execution.current_attempt, "attempt_id", str(uuid4()))
        variants.append(("changed_issued_attempt", changed))
        changed = copy.deepcopy(self.view)
        object.__setattr__(changed.execution.result, "work_id", str(uuid4()))
        variants.append(("changed_result_work", changed))
        changed = copy.deepcopy(self.view)
        object.__setattr__(changed.execution.result, "body", changed.execution.result.body + b" ")
        variants.append(("noncanonical_stored_result", changed))
        variants.extend(
            [
                ("unsupported_eligibility", self.changed_result(eligible=False)),
                ("wrong_fingerprint", self.changed_result(input_fingerprint="0" * 64)),
                ("foreign_result_scope", self.changed_result(scope=Scope("foreign", "foreign"))),
                (
                    "unsupported_fact",
                    self.changed_result(
                        fact_refs=(replace(self.view.result.fact_refs[0], fact_id="unknown_fact"),)
                    ),
                ),
                (
                    "changed_rule",
                    self.changed_result(
                        rule_refs=(replace(self.view.result.rule_refs[0], minimum_notice_days=8),)
                    ),
                ),
                (
                    "changed_fact_reference",
                    self.changed_result(
                        fact_refs=(replace(self.view.result.fact_refs[0], sha256="0" * 64),)
                    ),
                ),
            ]
        )
        client = self.client()
        for name, value in variants:
            with self.subTest(name=name):
                self.results.value = value
                with self.assertRaises(CompletionError) as caught:
                    await client.deliver_once(self.work_id)
                self.assertEqual(caught.exception.code, "invalid_stored_state")
                self.no_writes()
        self.results.value = self.view
        self.assertEqual((await client.deliver_once(self.work_id)).state, "accepted")
        self.assertEqual(self.receiver.accepted, 1)

    async def test_missing_and_conflicting_facts_cannot_prepare_or_begin(self):
        client = self.client()
        for values, uncertainty in [((), "missing"), ((3, 10), "conflicting")]:
            request, evidence, view = await self.valid_view(values)
            results, store, receiver = ResultReads(view), DeliveryStore(view), StructuralReceiver()
            current = FixedPolicyDeliveryClient(
                results=results,
                deliveries=store,
                receiver=receiver,
                scope=request.scope,
                evidence=evidence,
                bindings=(
                    DeliveryBinding(request.case_id, request.conversation_id, "recipient_fixed"),
                ),
            )
            self.clients.append(current)
            with self.subTest(uncertainty=uncertainty):
                self.assertEqual(view.applicability, "clarification")
                self.assertIsNone(view.result.eligible)
                self.assertEqual(view.result.uncertainty, uncertainty)
                with self.assertRaises(CompletionError) as caught:
                    await current.deliver_once(view.execution.record.work_id)
                self.assertEqual(caught.exception.code, "not_eligible")
                self.assertEqual((store.prepared, store.begun, receiver.accepted), (0, 0, 0))
                # A supplied reader cannot upgrade factual clarification to a new delivery.
                results.value = replace(view, applicability="candidate")
                with self.assertRaises(CompletionError) as caught:
                    await current.deliver_once(view.execution.record.work_id)
                self.assertEqual(caught.exception.code, "not_eligible")
                self.assertEqual((store.prepared, store.begun, receiver.accepted), (0, 0, 0))
        self.assertEqual((await client.deliver_once(self.work_id)).state, "accepted")

    async def test_current_stale_cancelled_expired_or_unavailable_result_blocks_new_delivery(self):
        client = self.client()
        for applicability in (
            "outdated",
            "case_cancelled",
            "expired",
            "execution_ineligible",
            "unavailable",
        ):
            with self.subTest(applicability=applicability):
                self.results.value = replace(self.view, applicability=applicability)
                with self.assertRaises(CompletionError) as caught:
                    await client.deliver_once(self.work_id)
                self.assertEqual(caught.exception.code, "not_eligible")
                self.no_writes()
        self.results.value = replace(
            self.view,
            execution=replace(
                self.view.execution,
                result=replace(self.view.execution.result, disposition="cancelled"),
                status="cancelled",
            ),
        )
        with self.assertRaises(CompletionError) as caught:
            await client.deliver_once(self.work_id)
        self.assertEqual(caught.exception.code, "not_eligible")
        self.no_writes()

    async def test_existing_possible_absence_remains_unknown_after_stale_case(self):
        client = self.client()
        self.store.ack_begin = True
        first = await client.deliver_once(self.work_id)
        self.assertEqual(first.state, "unknown")
        before = (self.store.prepared, self.store.begun, self.receiver.accepted)
        self.results.value = replace(self.view, applicability="outdated")
        again = await client.deliver_once(self.work_id)
        self.assertEqual(again.snapshot, first.snapshot)
        self.assertEqual(again.state, "unknown")
        self.assertEqual((self.store.prepared, self.store.begun, self.receiver.accepted), before)
        self.assertEqual(self.receiver.found, 2)

    async def test_existing_possible_exact_receipt_reconciles_after_current_invalidation(self):
        client = self.client()
        self.store.ack_begin = True
        first = await client.deliver_once(self.work_id)
        intent = first.snapshot.intent
        receipt = DeliveryReceipt(
            intent.delivery_id,
            str(uuid4()),
            intent.receiver_id,
            intent.recipient_id,
            intent.result_sha256,
            time.time_ns() // 1_000_000,
        )
        self.receiver.values[intent.delivery_id] = receipt
        self.results.value = replace(self.view, applicability="case_cancelled")
        reconciled = await client.deliver_once(self.work_id)
        self.assertEqual(reconciled.state, "accepted")
        self.assertEqual(reconciled.snapshot.receipt, receipt)
        self.assertFalse(reconciled.receiver_invoked)
        self.assertEqual((self.receiver.accepted, self.store.begun, self.store.recorded), (0, 1, 1))
        self.results.value = replace(self.view, applicability="expired")
        self.assertEqual((await client.deliver_once(self.work_id)).snapshot, reconciled.snapshot)

    async def test_known_receipt_still_requires_valid_immutable_bytes_and_facts(self):
        client = self.client()
        first = await client.deliver_once(self.work_id)
        self.results.value = self.changed_result(eligible=False)
        with self.assertRaises(CompletionError) as caught:
            await client.deliver_once(self.work_id)
        self.assertEqual(caught.exception.code, "invalid_stored_state")
        self.assertEqual(self.store.snapshot, first.snapshot)
        self.assertEqual(self.receiver.accepted, 1)

    async def test_route_receiver_and_receipt_cannot_retarget_original_intent(self):
        client = self.client()
        self.store.ack_begin = True
        first = await client.deliver_once(self.work_id)
        original = first.snapshot.intent
        changed = replace(original, recipient_id="other_recipient")
        self.store.snapshot = DeliverySnapshot(changed, True, None)
        with self.assertRaises(CompletionError) as caught:
            await client.deliver_once(self.work_id)
        self.assertEqual(caught.exception.code, "identity_conflict")
        self.store.snapshot = first.snapshot
        self.receiver.values[original.delivery_id] = DeliveryReceipt(
            original.delivery_id,
            str(uuid4()),
            original.receiver_id,
            "other_recipient",
            original.result_sha256,
            time.time_ns() // 1_000_000,
        )
        with self.assertRaises(CompletionError) as caught:
            await client.deliver_once(self.work_id)
        self.assertEqual(caught.exception.code, "invalid_stored_state")
        self.assertEqual((self.receiver.accepted, self.store.recorded), (0, 0))

    async def test_changed_receiver_during_lookup_cannot_accept(self):
        self.receiver.after_find = lambda: setattr(self.receiver, "_receiver_id", str(uuid4()))
        with self.assertRaises(CompletionError) as caught:
            await self.client().deliver_once(self.work_id)
        self.assertEqual(caught.exception.code, "identity_conflict")
        self.assertEqual(self.receiver.accepted, 0)
        self.assertTrue(self.store.snapshot.possible)

    async def test_prepare_receiver_and_receipt_ack_loss_reconcile_original_receipt(self):
        self.store.ack_prepare = self.store.ack_record = self.receiver.ack = True
        result = await self.client().deliver_once(self.work_id)
        self.assertEqual(result.state, "accepted")
        self.assertEqual(result.snapshot.receipt, self.store.snapshot.receipt)
        self.assertEqual(
            (self.store.prepared, self.store.begun, self.store.recorded, self.receiver.accepted),
            (1, 1, 1, 1),
        )

    async def test_postcommit_failed_lookup_preserves_unknown_then_original_replay(self):
        self.store.ack_record = self.store.lookup_after_ack = True
        client = self.client()
        with self.assertRaises(CompletionError) as caught:
            await client.deliver_once(self.work_id)
        self.assertEqual(caught.exception.code, "acknowledgement_unknown")
        receipt = self.store.snapshot.receipt
        self.assertIsNotNone(receipt)
        self.store.inspect_failure = False
        self.results.value = replace(self.view, applicability="outdated")
        actual = await client.deliver_once(self.work_id)
        self.assertEqual(actual.snapshot.receipt, receipt)
        self.assertEqual(self.receiver.accepted, 1)

    async def test_cancelled_waiter_retains_capacity_and_records_known_acceptance(self):
        self.receiver.release = asyncio.Event()
        client = self.client(max_active=1, cleanup_ms=20)
        caller = self.spawned(client.deliver_once(self.work_id))
        await asyncio.wait_for(self.receiver.entered.wait(), 1)
        caller.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await caller
        self.assertEqual(client.pending_count, 1)
        with self.assertRaises(CompletionError) as caught:
            await client.inspect(self.work_id)
        self.assertEqual(caught.exception.code, "capacity")
        with self.assertRaises(CompletionError) as caught:
            await client.close()
        self.assertEqual(caught.exception.code, "cleanup_incomplete")
        self.assertEqual((self.store.closed, self.receiver.closed), (0, 0))
        self.receiver.release.set()
        await client.close()
        self.assertEqual(client.pending_count, 0)
        self.assertIsNotNone(self.store.snapshot.receipt)
        self.assertEqual(self.receiver.accepted, 1)

    async def test_timeout_retains_external_accept_and_later_inspection_makes_progress(self):
        self.receiver.release = asyncio.Event()
        client = self.client(max_active=1, timeout_ms=20, cleanup_ms=20)
        with self.assertRaises(CompletionError) as caught:
            await client.deliver_once(self.work_id)
        self.assertEqual(caught.exception.code, "acknowledgement_unknown")
        self.assertEqual(client.pending_count, 1)
        with self.assertRaises(CompletionError) as caught:
            await client.inspect(self.work_id)
        self.assertEqual(caught.exception.code, "capacity")
        self.receiver.release.set()
        await self.settled(client)
        self.assertEqual((await client.inspect(self.work_id)).state, "accepted")
        self.assertEqual(self.receiver.accepted, 1)

    async def test_abandoned_prepare_never_begins_or_accepts_and_close_retries(self):
        self.store.prepare_release = asyncio.Event()
        client = self.client(timeout_ms=20, cleanup_ms=20)
        with self.assertRaises(CompletionError) as caught:
            await client.deliver_once(self.work_id)
        self.assertEqual(caught.exception.code, "acknowledgement_unknown")
        self.assertTrue(self.store.prepare_entered.is_set())
        with self.assertRaises(CompletionError) as caught:
            await client.close()
        self.assertEqual(caught.exception.code, "cleanup_incomplete")
        self.assertEqual(client.pending_count, 1)
        self.assertEqual((self.store.closed, self.receiver.closed), (0, 0))
        self.store.prepare_release.set()
        await client.close()
        self.assertEqual(
            (self.store.begun, self.receiver.accepted, client.pending_count), (0, 0, 0)
        )

    async def test_abandoned_result_read_never_prepares_or_closes_shared_reader(self):
        self.results.release = asyncio.Event()
        client = self.client(timeout_ms=20, cleanup_ms=20)
        with self.assertRaises(CompletionError) as caught:
            await client.deliver_once(self.work_id)
        self.assertEqual(caught.exception.code, "deadline_exceeded")
        self.assertEqual(client.pending_count, 1)
        self.no_writes()
        self.results.release.set()
        await self.settled(client)
        self.no_writes()
        self.assertEqual((await client.deliver_once(self.work_id)).state, "accepted")

    async def test_nested_result_evidence_and_binding_are_snapshotted_before_await(self):
        client = self.client()
        self.store.prepare_release = asyncio.Event()
        pending = self.spawned(client.deliver_once(self.work_id))
        await asyncio.wait_for(self.store.prepare_entered.wait(), 1)
        original = self.view.execution.result.body
        object.__setattr__(self.view.result.fact_refs[0], "days_before_arrival", 3)
        object.__setattr__(self.evidence[1], "body", b"PRIVATE_MUTATION_SENTINEL")
        object.__setattr__(self.binding, "recipient_id", "changed_recipient")
        self.store.prepare_release.set()
        result = await pending
        self.assertEqual(result.state, "accepted")
        self.assertEqual(result.snapshot.intent.body, original)
        self.assertEqual(result.snapshot.intent.recipient_id, "recipient_fixed")

    async def test_foreign_evidence_or_changed_delivery_scope_fail_before_writes(self):
        with self.assertRaises(CompletionError):
            FixedPolicyDeliveryClient(
                results=self.results,
                deliveries=self.store,
                receiver=self.receiver,
                scope=self.request.scope,
                evidence=(
                    replace(self.evidence[0], scope=Scope("foreign", "foreign")),
                    self.evidence[1],
                ),
                bindings=(self.binding,),
            )
        client = self.client()
        self.store.scope = WorkScope("foreign", "foreign")
        with self.assertRaises(CompletionError) as caught:
            await client.deliver_once(self.work_id)
        self.assertEqual(caught.exception.code, "unauthorized")
        self.no_writes()

    async def test_dependency_exception_and_telemetry_are_body_free_and_do_not_change_facts(self):
        class Broken(logging.Handler):
            def emit(self, record):
                raise RuntimeError("PRIVATE_COMPLETION_SENTINEL")

        client = self.client()
        self.receiver.failure = RuntimeError("PRIVATE_COMPLETION_SENTINEL")
        with self.assertRaises(CompletionError) as caught:
            await client.deliver_once(self.work_id)
        self.assertEqual(str(caught.exception), "internal_error")
        self.assertNotIn("PRIVATE", str(caught.exception))
        self.assertEqual(self.receiver.accepted, 0)
        self.receiver.failure = None
        logger = logging.getLogger("delegation_reliability.completion")
        handler, level = Broken(), logger.level
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        try:
            # Original possible delivery remains lookup-only; a known receiver fact can reconcile.
            intent = self.store.snapshot.intent
            self.receiver.values[intent.delivery_id] = DeliveryReceipt(
                intent.delivery_id,
                str(uuid4()),
                intent.receiver_id,
                intent.recipient_id,
                intent.result_sha256,
                time.time_ns() // 1_000_000,
            )
            result = await client.deliver_once(self.work_id)
            self.assertEqual(result.state, "accepted")
            self.assertGreater(client.metrics()["telemetry_failed"], 0)
            self.assertEqual(self.receiver.accepted, 0)
        finally:
            logger.removeHandler(handler)
            logger.setLevel(level)
