"""Typed fake ports prove orchestration; real SQL/process evidence has a separate gate."""

import asyncio
import logging
import time
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import uuid4

import test_runner as prior

from continuity_lab.action_api import ActionError, ActionIntent, ActionReceipt
from continuity_lab.case_control_api import CaseControlIdentity
from continuity_lab.case_control_api import CaseSnapshot as AuthorityCase
from continuity_lab.delivery_api import (
    DeliveryIntent,
    DeliveryReceipt,
    DeliverySnapshot,
    DeliveryStart,
)
from continuity_lab.postgres_api import Confirmation, QuoteSnapshot
from continuity_lab.work_api import WorkError, WorkScope
from delegation_reliability import (
    ActionBinding,
    CompletionError,
    DelegationAuthorizer,
    DelegationDeliveryClient,
    DeliveryBinding,
    ExactManagedCaseAuthority,
)
from delegation_reliability.contracts import canonical
from delegation_reliability.runner import DelegationRunner
from delegation_reliability.security import EvidenceRecord


class Results:
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
        assert work_id == self.value.execution.record.work_id
        return self.value


class DeliveryStore:
    def __init__(self, value):
        self.scope = value.execution.record.scope
        self.value = value
        self.snapshot = DeliverySnapshot(None, False, None)
        self.prepared = self.begun = self.recorded = self.closed = 0
        self.ack_prepare = self.ack_begin = self.ack_record = False
        self.inspect_failure = False
        self.lookup_after_ack = False
        self.prepare_release = None
        self.prepare_entered = asyncio.Event()
        self.begin_release = None

    async def prepare(self, *, work_id, attempt_id, result_sha256, receiver_id, recipient_id):
        self.prepared += 1
        old = self.snapshot.intent
        if old is not None:
            if (
                old.work_id,
                old.attempt_id,
                old.result_sha256,
                old.receiver_id,
                old.recipient_id,
            ) != (work_id, attempt_id, result_sha256, receiver_id, recipient_id):
                raise WorkError("identity_conflict")
            return old
        plan = DeliveryIntent(
            str(uuid4()),
            self.scope,
            work_id,
            attempt_id,
            result_sha256,
            receiver_id,
            recipient_id,
            self.value.execution.result.body,
            time.time_ns() // 1_000_000,
        )
        self.snapshot = DeliverySnapshot(plan, False, None)
        self.prepare_entered.set()
        if self.prepare_release is not None:
            await self.prepare_release.wait()
        if self.ack_prepare:
            raise WorkError("acknowledgement_unknown")
        return plan

    async def begin(self, *, intent):
        self.begun += 1
        assert self.snapshot.intent == intent
        created = not self.snapshot.possible
        self.snapshot = DeliverySnapshot(intent, True, self.snapshot.receipt)
        if self.begin_release is not None:
            await self.begin_release.wait()
        if self.ack_begin:
            raise WorkError("acknowledgement_unknown")
        return DeliveryStart(intent, created)

    async def record_receipt(self, *, intent, receipt):
        self.recorded += 1
        assert intent == self.snapshot.intent
        self.snapshot = DeliverySnapshot(intent, True, receipt)
        if self.ack_record:
            if self.lookup_after_ack:
                self.inspect_failure = True
            raise WorkError("acknowledgement_unknown")
        return receipt

    async def inspect(self, *, work_id):
        if self.inspect_failure:
            raise WorkError("storage_unavailable")
        assert work_id == self.value.execution.record.work_id
        return self.snapshot

    async def close(self):
        self.closed += 1


class Receiver:
    def __init__(self):
        self.receiver_id = str(uuid4())
        self.values = {}
        self.accepted = self.found = self.closed = 0
        self.entered = asyncio.Event()
        self.release = None
        self.ack = False
        self.failure = None
        self.after_find = None

    async def find(self, intent):
        self.found += 1
        if self.failure is not None:
            raise self.failure
        if self.after_find is not None:
            self.after_find()
        return self.values.get(intent.delivery_id)

    async def accept(self, intent):
        self.accepted += 1
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        if self.failure is not None:
            raise self.failure
        result = self.values.setdefault(
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
        return result

    async def close(self):
        self.closed += 1


class Actions:
    def __init__(self, value, binding):
        self.scope = value.execution.record.scope
        self.case_actor_id = binding.authority_actor_id
        self.case_scope_id = binding.authority_scope_id
        self.case_schema = binding.case_schema
        self.binding = binding
        self.rows = {}
        self.calls = self.closed = 0
        self.ack = self.lookup_failure = False
        self.lookup_after_ack = False
        self.work_eligible = True
        self.current_revision = value.request.request_revision
        self.entered = asyncio.Event()
        self.release = None

    async def find_action(self, *, command_id):
        if self.lookup_failure:
            raise ActionError("storage_unavailable")
        return self.rows.get(command_id)

    async def action(self, *, work_id):
        return next((v for v in self.rows.values() if v.work_id == work_id), None)

    async def authorize(
        self, *, work_id, attempt_id, result_sha256, expected_revision, confirmation, command_id
    ):
        self.calls += 1
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        if not self.work_eligible:
            raise ActionError("expired")
        if expected_revision != self.current_revision:
            raise ActionError("stale_revision")
        old = self.rows.get(command_id)
        if old is not None:
            return old
        quote = confirmation.quote
        intent = ActionIntent(
            str(uuid4()),
            self.binding.task_id,
            self.case_scope_id,
            self.case_actor_id,
            expected_revision,
            quote,
            str(uuid4()),
            str(uuid4()),
            str(uuid4()),
            datetime.now(UTC).isoformat(),
        )
        result = ActionReceipt(
            str(uuid4()),
            self.scope,
            work_id,
            attempt_id,
            result_sha256,
            self.case_schema,
            self.case_scope_id,
            self.case_actor_id,
            self.binding.task_id,
            self.binding.authority_case_id,
            expected_revision,
            command_id,
            confirmation,
            intent,
            time.time_ns() // 1_000_000,
        )
        self.rows[command_id] = result
        if self.ack:
            if self.lookup_after_ack:
                self.lookup_failure = True
            raise ActionError("acknowledgement_unknown")
        return result

    async def close(self):
        self.closed += 1


class CompletionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.request = prior.request()
        execution = prior.FakeExecution(self.request)
        self.runner = DelegationRunner(
            executions=execution,
            scope=self.request.scope,
            owner_id=str(uuid4()),
            specialist=prior.FakeSpecialist(),
            case_authority=prior.FakeCases(self.request),
            evidence=(EvidenceRecord(self.request.scope, self.request.evidence[0], prior.POLICY),),
        )
        run = await self.runner.run_once(execution.record.work_id, "issue")
        self.view = run.view
        self.results = Results(self.view)
        self.work_id = self.view.execution.record.work_id
        self.store = DeliveryStore(self.view)
        self.receiver = Receiver()
        self.bind = DeliveryBinding(
            self.request.case_id, self.request.conversation_id, "recipient_demo"
        )
        self.action_bind = ActionBinding(
            self.request.case_id,
            str(uuid4()),
            str(uuid4()),
            "case_actor",
            "case_scope",
            "case_schema",
        )
        self.actions = Actions(self.view, self.action_bind)
        self.confirmation = Confirmation(
            QuoteSnapshot(
                str(uuid4()),
                self.action_bind.task_id,
                self.request.request_revision,
                "DEMO-BK-001",
                date(2030, 12, 10),
                500,
                "USD",
                datetime.fromtimestamp(
                    (time.time_ns() // 1_000_000 + 30000) / 1000, UTC
                ).isoformat(),
                self.action_bind.authority_case_id,
                0,
                str(uuid4()),
            ),
            True,
        )
        self.clients = []

    async def asyncTearDown(self):
        for event in (
            self.results.release,
            self.store.prepare_release,
            self.receiver.release,
            self.actions.release,
        ):
            if event is not None:
                event.set()
        for client in self.clients:
            await client.close()
        await self.runner.close()

    def delivery(self, **options):
        result = DelegationDeliveryClient(
            results=self.results,
            deliveries=self.store,
            receiver=self.receiver,
            scope=self.request.scope,
            evidence=(EvidenceRecord(self.request.scope, self.request.evidence[0], prior.POLICY),),
            bindings=(self.bind,),
            **options,
        )
        self.clients.append(result)
        return result

    def authorizer(self, **options):
        result = DelegationAuthorizer(
            results=self.results,
            actions=self.actions,
            scope=self.request.scope,
            evidence=(EvidenceRecord(self.request.scope, self.request.evidence[0], prior.POLICY),),
            bindings=(self.action_bind,),
            **options,
        )
        self.clients.append(result)
        return result

    async def test_normal_delivery_and_original_replay_use_one_remote_accept(self):
        client = self.delivery()
        first = await client.deliver_once(self.work_id)
        self.assertEqual(first.state, "accepted")
        self.assertTrue(first.receiver_invoked)
        replay = await client.deliver_once(self.work_id)
        self.assertEqual(replay.snapshot, first.snapshot)
        self.assertFalse(replay.receiver_invoked)
        self.assertEqual(self.receiver.accepted, 1)
        self.assertEqual(self.store.recorded, 1)
        self.assertEqual(first.snapshot.intent.body, self.view.execution.result.body)
        self.assertEqual((await client.inspect(self.work_id)).snapshot, first.snapshot)

    async def test_existing_possible_absence_stays_unknown_without_another_accept(self):
        client = self.delivery()
        self.store.ack_begin = True
        outcome = await client.deliver_once(self.work_id)
        self.assertEqual(outcome.state, "unknown")
        self.assertEqual(self.receiver.accepted, 0)
        again = await client.deliver_once(self.work_id)
        self.assertEqual(again.state, "unknown")
        self.assertEqual(self.receiver.accepted, 0)

    async def test_receiver_ack_loss_reconciles_same_receipt(self):
        self.receiver.ack = True
        result = await self.delivery().deliver_once(self.work_id)
        self.assertEqual(result.state, "accepted")
        self.assertEqual(self.receiver.accepted, 1)
        self.assertEqual(self.store.snapshot.receipt, result.snapshot.receipt)

    async def test_sender_prepare_and_receipt_ack_loss_inspect_original(self):
        self.store.ack_prepare = self.store.ack_record = True
        result = await self.delivery().deliver_once(self.work_id)
        self.assertEqual(result.state, "accepted")
        self.assertEqual(
            (self.store.prepared, self.store.recorded, self.receiver.accepted), (1, 1, 1)
        )

    async def test_changed_route_or_receiver_never_retargets_an_original_plan(self):
        client = self.delivery()
        await client.deliver_once(self.work_id)
        self.clients.remove(client)
        # A new service must explicitly restore the old binding to reconcile it.
        altered = DelegationDeliveryClient(
            results=self.results,
            deliveries=self.store,
            receiver=self.receiver,
            scope=self.request.scope,
            evidence=(EvidenceRecord(self.request.scope, self.request.evidence[0], prior.POLICY),),
            bindings=(replace(self.bind, recipient_id="recipient_other"),),
        )
        self.clients.extend((client, altered))
        with self.assertRaises(CompletionError) as caught:
            await altered.deliver_once(self.work_id)
        self.assertEqual(caught.exception.code, "identity_conflict")
        self.assertEqual(self.receiver.accepted, 1)

    async def test_known_receipt_remains_fact_after_current_case_invalidation(self):
        client = self.delivery()
        first = await client.deliver_once(self.work_id)
        self.results.value = replace(self.view, applicability="outdated")
        replay = await client.deliver_once(self.work_id)
        self.assertEqual(replay.snapshot, first.snapshot)
        self.assertEqual(self.receiver.accepted, 1)

    async def test_outdated_or_misbound_scope_cannot_prepare_or_send(self):
        client = self.delivery()
        self.results.value = replace(self.view, applicability="outdated")
        with self.assertRaises(CompletionError):
            await client.deliver_once(self.work_id)
        self.assertEqual((self.store.prepared, self.receiver.accepted), (0, 0))
        self.results.value = self.view
        self.store.scope = WorkScope("other", "other")
        with self.assertRaises(CompletionError):
            await client.deliver_once(self.work_id)
        self.assertEqual((self.store.prepared, self.receiver.accepted), (0, 0))

    async def test_wrong_receiver_receipt_cannot_be_recorded(self):
        client = self.delivery()
        self.store.ack_begin = True
        missing = await client.deliver_once(self.work_id)
        intent = missing.snapshot.intent
        self.receiver.values[intent.delivery_id] = DeliveryReceipt(
            intent.delivery_id,
            str(uuid4()),
            self.receiver.receiver_id,
            "wrong",
            intent.result_sha256,
            time.time_ns() // 1_000_000,
        )
        with self.assertRaises(CompletionError) as caught:
            await client.deliver_once(self.work_id)
        self.assertEqual(caught.exception.code, "invalid_stored_state")
        self.assertEqual(self.store.recorded, 0)

    async def test_cancelled_waiter_keeps_slot_and_known_acceptance_is_stored(self):
        self.receiver.release = asyncio.Event()
        client = self.delivery(max_active=1)
        caller = asyncio.create_task(client.deliver_once(self.work_id))
        await asyncio.wait_for(self.receiver.entered.wait(), 1)
        caller.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await caller
        self.assertEqual(client.pending_count, 1)
        with self.assertRaises(CompletionError) as caught:
            await client.inspect(self.work_id)
        self.assertEqual(caught.exception.code, "capacity")
        self.receiver.release.set()
        await client.close()
        self.assertIsNotNone(self.store.snapshot.receipt)
        self.assertEqual(client.pending_count, 0)

    async def test_abandoned_prepare_cannot_begin_external_delivery_and_close_retains_io(self):
        self.store.prepare_release = asyncio.Event()
        client = self.delivery(timeout_ms=20, cleanup_ms=20)
        with self.assertRaises(CompletionError) as caught:
            await client.deliver_once(self.work_id)
        self.assertEqual(caught.exception.code, "acknowledgement_unknown")
        with self.assertRaises(CompletionError) as caught:
            await client.close()
        self.assertEqual(caught.exception.code, "cleanup_incomplete")
        self.assertEqual(client.pending_count, 1)
        self.store.prepare_release.set()
        await client.close()
        self.assertEqual((self.store.begun, self.receiver.accepted), (0, 0))

    async def test_created_begin_still_reaches_the_receiver_after_waiter_timeout(self):
        self.store.begin_release = asyncio.Event()
        client = self.delivery(timeout_ms=20, cleanup_ms=20)
        with self.assertRaises(CompletionError) as caught:
            await client.deliver_once(self.work_id)
        self.assertEqual(caught.exception.code, "acknowledgement_unknown")
        self.assertEqual((self.store.begun, self.receiver.accepted), (1, 0))
        self.store.begin_release.set()
        while client.pending_count:
            await asyncio.sleep(0)
        self.assertEqual((self.receiver.accepted, self.store.recorded), (1, 1))
        replay = await client.deliver_once(self.work_id)
        self.assertEqual((replay.state, replay.receiver_invoked), ("accepted", False))
        self.assertEqual(self.receiver.accepted, 1)
        await client.close()

    async def test_close_during_a_created_begin_retains_the_call_through_receiver_accept(self):
        self.store.begin_release = asyncio.Event()
        client = self.delivery(timeout_ms=1000, cleanup_ms=20)
        delivering = asyncio.create_task(client.deliver_once(self.work_id))
        while self.store.begun == 0:
            await asyncio.sleep(0)
        with self.assertRaises(CompletionError) as caught:
            await client.close()
        self.assertEqual(caught.exception.code, "cleanup_incomplete")
        self.store.begin_release.set()
        self.assertEqual((await delivering).state, "accepted")
        await client.close()
        self.assertEqual((self.receiver.accepted, self.store.recorded), (1, 1))

    async def test_explicit_exact_confirmation_commits_then_replays_fact(self):
        client = self.authorizer()
        first = await client.authorize_once(
            self.work_id, confirmation=self.confirmation, command_id="confirm"
        )
        self.assertFalse(first.reconciled)
        self.assertEqual(first.receipt.intent.quote, self.confirmation.quote)
        self.results.value = replace(self.view, applicability="execution_ineligible")
        replay = await client.authorize_once(
            self.work_id, confirmation=self.confirmation, command_id="confirm"
        )
        self.assertTrue(replay.reconciled)
        self.assertEqual(replay.receipt, first.receipt)
        self.assertEqual(self.actions.calls, 1)
        self.assertEqual(await client.inspect(self.work_id), first.receipt)

    async def test_unknown_action_ack_reconciles_without_another_authorization(self):
        self.actions.ack = True
        client = self.authorizer()
        result = await client.authorize_once(
            self.work_id, confirmation=self.confirmation, command_id="confirm"
        )
        self.assertTrue(result.reconciled)
        self.assertEqual(self.actions.calls, 1)
        self.assertEqual(result.receipt, self.actions.rows["confirm"])

    async def test_stale_or_wrong_quote_and_missing_explicit_consent_cannot_authorize(self):
        client = self.authorizer()
        with self.assertRaises(CompletionError):
            await client.authorize_once(self.work_id, confirmation=object(), command_id="bad")
        wrong = Confirmation(replace(self.confirmation.quote, revision=2), True)
        with self.assertRaises(CompletionError):
            await client.authorize_once(self.work_id, confirmation=wrong, command_id="bad")
        self.results.value = replace(self.view, applicability="outdated")
        with self.assertRaises(CompletionError):
            await client.authorize_once(
                self.work_id, confirmation=self.confirmation, command_id="bad"
            )
        self.assertEqual(self.actions.calls, 0)

    async def test_authority_observes_cancel_after_application_preflight(self):
        self.actions.release = asyncio.Event()
        client = self.authorizer()
        pending = asyncio.create_task(
            client.authorize_once(self.work_id, confirmation=self.confirmation, command_id="race")
        )
        await asyncio.wait_for(self.actions.entered.wait(), 1)
        self.actions.work_eligible = False
        self.actions.release.set()
        with self.assertRaises(CompletionError) as caught:
            await pending
        self.assertEqual(caught.exception.code, "expired")
        self.assertEqual(self.actions.rows, {})

    async def test_changed_guard_identity_fails_before_authorization(self):
        client = self.authorizer()
        self.actions.case_actor_id = "changed"
        with self.assertRaises(CompletionError) as caught:
            await client.authorize_once(
                self.work_id, confirmation=self.confirmation, command_id="bad"
            )
        self.assertEqual(caught.exception.code, "unauthorized")
        self.assertEqual(self.actions.calls, 0)

    async def test_telemetry_failure_never_changes_known_delivery_or_action(self):
        class Broken(logging.Handler):
            def emit(self, record):
                raise RuntimeError("PRIVATE_COMPLETION_SENTINEL")

        logger = logging.getLogger("delegation_reliability.completion")
        handler = Broken()
        logger.addHandler(handler)
        old = logger.level
        logger.setLevel(logging.INFO)
        try:
            client = self.delivery()
            receipt = await client.deliver_once(self.work_id)
            self.assertEqual(receipt.state, "accepted")
            self.assertGreater(client.metrics()["telemetry_failed"], 0)
            authorizer = self.authorizer()
            result = await authorizer.authorize_once(
                self.work_id, confirmation=self.confirmation, command_id="confirm"
            )
            self.assertIsNotNone(result.receipt.intent)
        finally:
            logger.removeHandler(handler)
            logger.setLevel(old)

    async def test_exact_case_read_checks_current_identity_and_handles_committed_cancel(self):
        binding = self.action_bind

        class Read:
            identity = CaseControlIdentity(
                binding.authority_actor_id, binding.authority_scope_id, binding.case_schema
            )

            async def case(inner, *, task_id):
                return AuthorityCase(
                    task_id,
                    binding.authority_scope_id,
                    binding.authority_actor_id,
                    2,
                    None,
                    None,
                    True,
                    None,
                    datetime.now(UTC).isoformat(),
                    datetime.now(UTC).isoformat(),
                    binding.authority_case_id,
                )

        source = Read()
        adapter = ExactManagedCaseAuthority(source, scope=self.request.scope, bindings=(binding,))
        value = await adapter.snapshot(case_id=binding.case_id)
        self.assertTrue(value.cancelled)
        self.assertEqual(value.request_revision, 2)
        source.identity = replace(source.identity, scope_id="other")
        with self.assertRaises(CompletionError):
            await adapter.snapshot(case_id=binding.case_id)

    async def test_factual_tampering_and_snapshot_hash_corruption_never_prepare(self):
        client = self.delivery()
        corrupted = replace(self.view.result, eligible=False)
        recorded = replace(self.view.execution.result, body=canonical(corrupted.to_wire()))
        self.results.value = replace(
            self.view, execution=replace(self.view.execution, result=recorded), result=corrupted
        )
        with self.assertRaises(CompletionError):
            await client.deliver_once(self.work_id)
        self.assertEqual(self.store.prepared, 0)

    async def test_receiver_identity_changed_during_lookup_cannot_accept(self):
        client = self.delivery()
        self.receiver.after_find = lambda: setattr(self.receiver, "receiver_id", str(uuid4()))
        with self.assertRaises(CompletionError) as caught:
            await client.deliver_once(self.work_id)
        self.assertEqual(caught.exception.code, "identity_conflict")
        self.assertEqual(self.receiver.accepted, 0)
        self.assertTrue(self.store.snapshot.possible)

    async def test_postcommit_receipt_lookup_failure_preserves_unknown(self):
        client = self.delivery()
        self.store.ack_record = self.store.lookup_after_ack = True
        with self.assertRaises(CompletionError) as caught:
            await client.deliver_once(self.work_id)
        self.assertEqual(caught.exception.code, "acknowledgement_unknown")
        self.assertIsNotNone(self.store.snapshot.receipt)
        self.assertEqual(self.receiver.accepted, 1)
        self.store.inspect_failure = False
        actual = await client.deliver_once(self.work_id)
        self.assertEqual(actual.state, "accepted")
        self.assertEqual(self.receiver.accepted, 1)

    async def test_postcommit_action_lookup_failure_preserves_unknown(self):
        client = self.authorizer()
        self.actions.ack = self.actions.lookup_after_ack = True
        with self.assertRaises(CompletionError) as caught:
            await client.authorize_once(
                self.work_id, confirmation=self.confirmation, command_id="confirm"
            )
        self.assertEqual(caught.exception.code, "acknowledgement_unknown")
        self.assertEqual(len(self.actions.rows), 1)
        self.actions.lookup_failure = False
        actual = await client.authorize_once(
            self.work_id, confirmation=self.confirmation, command_id="confirm"
        )
        self.assertTrue(actual.reconciled)
        self.assertEqual(self.actions.calls, 1)

    async def test_nested_result_and_route_mutation_after_prepare_cannot_change_bytes(self):
        client = self.delivery()
        self.store.prepare_release = asyncio.Event()
        pending = asyncio.create_task(client.deliver_once(self.work_id))
        await asyncio.wait_for(self.store.prepare_entered.wait(), 1)
        original = self.view.execution.result.body
        object.__setattr__(self.view.result, "eligible", False)
        object.__setattr__(self.bind, "recipient_id", "changed")
        self.store.prepare_release.set()
        actual = await pending
        self.assertEqual(actual.state, "accepted")
        self.assertEqual(actual.snapshot.intent.body, original)
        self.assertEqual(actual.snapshot.intent.recipient_id, "recipient_demo")

    async def test_explicit_confirmation_is_snapshotted_before_first_await(self):
        client = self.authorizer()
        self.results.release = asyncio.Event()
        pending = asyncio.create_task(
            client.authorize_once(
                self.work_id, confirmation=self.confirmation, command_id="confirm"
            )
        )
        await asyncio.wait_for(self.results.entered.wait(), 1)
        original = self.confirmation.quote.amount_minor
        object.__setattr__(self.confirmation.quote, "amount_minor", 9999)
        self.results.release.set()
        result = await pending
        self.assertEqual(result.receipt.confirmation.quote.amount_minor, original)
        self.assertEqual(self.actions.calls, 1)
