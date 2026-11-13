"""Schema3 uses the existing owned delivery schedule and exact outer bytes."""

import asyncio
import unittest
from dataclasses import replace
from uuid import uuid4

from test_channel_policy_execution import setup
from test_completion import DeliveryStore
from test_fixed_policy_completion import ResultReads, StructuralReceiver
from test_fixed_policy_execution import Specialist
from test_runner import FakeCases, FakeExecution

from continuity_lab.delivery_api import DeliveryReceipt
from continuity_lab.work_api import WorkError
from delegation_reliability import (
    ChannelPolicyDeliveryClient,
    ChannelPolicyRunner,
    CompletionError,
    DeliveryBinding,
    FixedPolicyDeliveryClient,
    FixedPolicyExecutionView,
    encode_channel_policy_result,
)
from delegation_reliability.contracts import canonical
from delegation_reliability.fixed_policy_contracts import encode_fixed_policy_result


class ChannelCompletionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.runners, self.clients, self.tasks = [], [], []
        self.request, self.evidence, self.view = await self.valid_view()
        self.results = ResultReads(self.view)
        self.store = DeliveryStore(self.view)
        self.receiver = StructuralReceiver()
        self.binding = DeliveryBinding(
            self.request.case_id, self.request.conversation_id, "recipient_channel"
        )
        self.work_id = self.view.execution.record.work_id

    async def asyncTearDown(self):
        for event in (
            self.results.release,
            self.receiver.release,
            self.receiver.find_release,
            self.store.prepare_release,
        ):
            if event is not None:
                event.set()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        for owner in self.clients + self.runners:
            await owner.close()

    async def valid_view(self, values=(10,)):
        request, evidence = setup(values)
        execution = FakeExecution(request)
        runner = ChannelPolicyRunner(
            executions=execution,
            scope=request.scope,
            owner_id=str(uuid4()),
            specialist=Specialist(),
            case_authority=FakeCases(request),
            evidence=evidence,
        )
        self.runners.append(runner)
        result = await runner.run_once(execution.record.work_id, "run_for_delivery")
        return request, evidence, result.view

    def client(self, **options):
        owner = ChannelPolicyDeliveryClient(
            results=self.results,
            deliveries=self.store,
            receiver=self.receiver,
            scope=self.request.scope,
            evidence=self.evidence,
            bindings=(self.binding,),
            **options,
        )
        self.clients.append(owner)
        return owner

    def no_writes(self):
        self.assertEqual(
            (self.store.prepared, self.store.begun, self.store.recorded, self.receiver.accepted),
            (0, 0, 0, 0),
        )

    async def test_current_delivery_receipt_binds_outer3_not_inner2_and_replay_is_read_only(self):
        owner = self.client()
        first = await owner.deliver_once(self.work_id)
        intent = first.snapshot.intent
        self.assertEqual(first.state, "accepted")
        self.assertEqual(intent.body, encode_channel_policy_result(self.view.result))
        self.assertNotEqual(intent.body, encode_fixed_policy_result(self.view.result.result))
        self.assertEqual(intent.result_sha256, self.view.execution.result.sha256)
        self.assertEqual(first.snapshot.receipt.result_sha256, intent.result_sha256)
        self.assertEqual(intent.attempt_id, self.view.execution.current_attempt.attempt_id)
        self.assertEqual(intent.receiver_id, self.receiver.receiver_id)
        self.assertEqual(intent.recipient_id, "recipient_channel")
        again = await owner.deliver_once(self.work_id)
        self.assertEqual(again.snapshot, first.snapshot)
        self.assertFalse(again.receiver_invoked)
        self.assertEqual((self.receiver.accepted, self.store.begun, self.store.recorded), (1, 1, 1))

    async def test_stale_new_delivery_denied_and_same_current_result_progresses(self):
        owner = self.client()
        self.results.value = replace(self.view, applicability="outdated")
        with self.assertRaisesRegex(CompletionError, "^not_eligible$"):
            await owner.deliver_once(self.work_id)
        self.no_writes()
        self.results.value = self.view
        self.assertEqual((await owner.deliver_once(self.work_id)).state, "accepted")

    async def test_possible_original_uses_find_only_after_case_change_and_keeps_receipt(self):
        owner = self.client()
        self.receiver.failure = WorkError("acknowledgement_unknown")
        with self.assertRaisesRegex(CompletionError, "^acknowledgement_unknown$"):
            await owner.deliver_once(self.work_id)
        intent = self.store.snapshot.intent
        self.assertTrue(self.store.snapshot.possible)
        self.results.value = replace(self.view, applicability="outdated")
        self.receiver.failure = None
        unknown = await owner.deliver_once(self.work_id)
        self.assertEqual(unknown.state, "unknown")
        receipt = DeliveryReceipt(
            intent.delivery_id,
            str(uuid4()),
            intent.receiver_id,
            intent.recipient_id,
            intent.result_sha256,
            intent.prepared_at_ms + 1,
        )
        self.receiver.values[intent.delivery_id] = receipt
        accepted = await owner.deliver_once(self.work_id)
        self.assertEqual(accepted.snapshot.receipt, receipt)
        self.assertFalse(accepted.receiver_invoked)
        self.results.value = replace(self.view, applicability="case_cancelled")
        self.assertEqual((await owner.deliver_once(self.work_id)).snapshot, accepted.snapshot)
        self.assertEqual(self.receiver.accepted, 0)

    async def test_full_inner_fact_forgery_is_rejected_even_with_consistent_outer_result_body(self):
        forged = replace(self.view.result, result=replace(self.view.result.result, eligible=False))
        body = canonical(forged.to_wire())
        recorded = replace(self.view.execution.result, body=body)
        self.results.value = replace(
            self.view, execution=replace(self.view.execution, result=recorded), result=forged
        )
        owner = self.client()
        with self.assertRaisesRegex(CompletionError, "^invalid_stored_state$"):
            await owner.deliver_once(self.work_id)
        self.no_writes()
        self.results.value = self.view
        self.assertEqual((await owner.deliver_once(self.work_id)).state, "accepted")

    async def test_outer_fingerprint_and_accepted_source_bytes_are_independently_required(self):
        owner = self.client()
        forged = replace(self.view.result, input_fingerprint="e" * 64)
        recorded = replace(self.view.execution.result, body=canonical(forged.to_wire()))
        self.results.value = replace(
            self.view, execution=replace(self.view.execution, result=recorded), result=forged
        )
        with self.assertRaisesRegex(CompletionError, "^invalid_stored_state$"):
            await owner.deliver_once(self.work_id)
        self.no_writes()
        self.results.value = replace(
            self.view, request=replace(self.request, input_fingerprint="e" * 64)
        )
        with self.assertRaisesRegex(CompletionError, "^invalid_stored_state$"):
            await owner.deliver_once(self.work_id)
        self.no_writes()

    async def test_clarification_is_history_but_cannot_prepare_new_delivery(self):
        request, evidence, view = await self.valid_view((3, 10))
        self.request, self.evidence, self.view = request, evidence, view
        self.results.value = view
        self.store = DeliveryStore(view)
        self.work_id = view.execution.record.work_id
        self.assertEqual(view.applicability, "clarification")
        owner = self.client()
        with self.assertRaisesRegex(CompletionError, "^not_eligible$"):
            await owner.deliver_once(self.work_id)
        self.no_writes()

    async def test_v2_and_v3_facades_do_not_coerce_each_others_observed_views(self):
        old = FixedPolicyExecutionView(
            self.view.execution, self.request.request, self.view.result.result, "candidate"
        )
        owner = self.client()
        self.results.value = old
        with self.assertRaisesRegex(CompletionError, "^invalid_stored_state$"):
            await owner.deliver_once(self.work_id)
        self.results.value = self.view
        legacy = FixedPolicyDeliveryClient(
            results=self.results,
            deliveries=self.store,
            receiver=self.receiver,
            scope=self.request.scope,
            evidence=self.evidence,
            bindings=(self.binding,),
        )
        self.clients.append(legacy)
        with self.assertRaisesRegex(CompletionError, "^invalid_stored_state$"):
            await legacy.deliver_once(self.work_id)
        self.no_writes()

    async def test_cancelled_waiter_keeps_actual_outer_accept_owned_until_close_retry(self):
        self.receiver.release = asyncio.Event()
        owner = self.client(max_active=1, cleanup_ms=20)
        caller = asyncio.create_task(owner.deliver_once(self.work_id))
        self.tasks.append(caller)
        await asyncio.wait_for(self.receiver.entered.wait(), 1)
        caller.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await caller
        self.assertEqual(owner.pending_count, 1)
        with self.assertRaisesRegex(CompletionError, "^capacity$"):
            await owner.inspect(self.work_id)
        with self.assertRaisesRegex(CompletionError, "^cleanup_incomplete$"):
            await owner.close()
        self.assertEqual((self.store.closed, self.receiver.closed), (0, 0))
        self.receiver.release.set()
        await owner.close()
        self.assertEqual(owner.pending_count, 0)
        self.assertEqual(
            self.store.snapshot.intent.body, encode_channel_policy_result(self.view.result)
        )
        self.assertIsNotNone(self.store.snapshot.receipt)
