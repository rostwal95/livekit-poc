"""Gap-aware delivery processing with public typed fake ports; no durability claim."""

import asyncio
import hashlib
import time
import unittest
from dataclasses import replace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import test_projection as projection_fixtures
import test_runner as runner_fixtures

from continuity_lab.delivery_api import DeliveryIntent, DeliveryReceipt, DeliverySnapshot
from continuity_lab.work_api import WorkError, WorkScope
from delegation_reliability import CompletionPolicy, CompletionProcessor
from delegation_reliability.completion import CompletionError
from delegation_reliability.delivery_contract import DelegationDelivery, DeliveryBinding
from delegation_reliability.processing_models import (
    ProcessingAcknowledgement,
    ProcessingCheckpoint,
    ProcessingPage,
    parse_ack,
    parse_policy,
)
from delegation_reliability.projection_models import ProjectionBinding, ProjectionError
from delegation_reliability.runner import DelegationRunError
from delegation_reliability.security import EvidenceRecord


class Metadata:
    def __init__(self, rows, policy):
        self.rows, self.policy = rows, policy
        self.scope = rows[0].event.scope
        self.source_id = rows[0].event.source_id
        self.point = ProcessingCheckpoint(
            ProjectionBinding(self.source_id, self.scope), policy.sha256, 0, 0, 0, 0, len(rows)
        )
        self.acks = {}
        self.commits = self.lookups = self.closed = 0
        self.unknown = False
        self.failure_code = "acknowledgement_unknown"
        self.persist = True
        self.lookup_failure = False
        self.alter = lambda page: page

    async def _page(self, limit):
        pending = [r for r in self.rows if r.event.sequence not in self.acks]
        after = [r for r in pending if r.event.sequence > self.point.scan_after][:limit]
        if len(after) < limit:
            after += [r for r in pending if r.event.sequence <= self.point.scan_after][
                : limit - len(after)
            ]
        return self.alter(ProcessingPage(self.point, tuple(after)))

    async def _commit(self, point, row, ack):
        self.commits += 1
        if row.event.sequence in self.acks:
            return self.point, self.acks[row.event.sequence]
        if self.persist:
            if ack is not None:
                self.acks[row.event.sequence] = ack
            watermark = 0
            while watermark + 1 in self.acks:
                watermark += 1
            self.point = replace(
                self.point,
                revision=self.point.revision + 1,
                terminal_watermark=watermark,
                scan_after=max(watermark, row.event.sequence),
                terminal_count=len(self.acks),
            )
        if self.unknown:
            raise ProjectionError(self.failure_code)
        return self.point, ack

    async def _reconcile(self, row):
        self.lookups += 1
        if self.lookup_failure:
            raise RuntimeError("PRIVATE_LOOKUP")
        return (
            (self.point, self.acks[row.event.sequence]) if row.event.sequence in self.acks else None
        )

    async def close(self):
        self.closed += 1


class Delivery:
    def __init__(self, rows, views, policy):
        self.scope = rows[0].event.scope
        self.receiver_id, self.bindings = policy.receiver_id, policy.bindings
        self.rows = {r.event.work_id: r for r in rows}
        self.views = views
        self.snapshots = {}
        self.accepts = self.delivers = self.closed = 0
        self.alter = lambda value: value
        self.release = None
        self.entered = asyncio.Event()

    def intent(self, row):
        return DeliveryIntent(
            str(uuid4()),
            self.scope,
            row.event.work_id,
            row.event.attempt_id,
            row.event.result_sha256,
            self.receiver_id,
            self.bindings[0].recipient_id,
            self.views[row.event.work_id].execution.result.body,
            time.time_ns() // 1_000_000,
        )

    def possible(self, row):
        self.snapshots[row.event.work_id] = DeliverySnapshot(self.intent(row), True, None)

    def late_receipt(self, row):
        intent = self.snapshots[row.event.work_id].intent
        receipt = DeliveryReceipt(
            intent.delivery_id,
            str(uuid4()),
            self.receiver_id,
            intent.recipient_id,
            intent.result_sha256,
            time.time_ns() // 1_000_000,
        )
        self.snapshots[row.event.work_id] = DeliverySnapshot(intent, True, receipt)

    async def inspect(self, work_id):
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        s = self.snapshots.get(work_id, DeliverySnapshot(None, False, None))
        return self.alter(
            DelegationDelivery(
                s, "accepted" if s.receipt else "unknown" if s.possible else "missing"
            )
        )

    async def deliver_once(self, work_id):
        self.delivers += 1
        s = self.snapshots.get(work_id)
        if s is None:
            self.accepts += 1
            self.possible(self.rows[work_id])
            self.late_receipt(self.rows[work_id])
        return await self.inspect(work_id)

    async def close(self):
        self.closed += 1


class Results:
    def __init__(self, views):
        self.views = views

    async def inspect(self, work_id):
        return self.views[work_id]


class ProcessingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.owners = []
        self.processors = []
        self.rows = []
        self.views = {}
        source = str(uuid4())
        for number in range(2):
            owner = projection_fixtures.ProjectorTests(
                "test_useful_result_projects_refs_and_asof_only_then_empty"
            )
            await owner.asyncSetUp()
            self.owners.append(owner)
            row = (await owner.client().project_once()).rows[0]
            row = replace(row, event=replace(row.event, source_id=source, sequence=number + 1))
            self.rows.append(row)
            runner = runner_fixtures.DelegationRunner(
                executions=owner.execution,
                scope=owner.value.scope,
                owner_id=str(uuid4()),
                specialist=runner_fixtures.FakeSpecialist(),
                case_authority=owner.cases,
                evidence=(
                    EvidenceRecord(
                        owner.value.scope, owner.value.evidence[0], runner_fixtures.POLICY
                    ),
                ),
            )
            self.views[row.event.work_id] = await runner.inspect(row.event.work_id)
            await runner.close()
        value = self.owners[0].value
        self.policy = CompletionPolicy(
            str(uuid4()), (DeliveryBinding(value.case_id, value.conversation_id, "recipient"),)
        )
        self.metadata = Metadata(self.rows, self.policy)
        self.feed = projection_fixtures.Feed(self.rows[0].event.scope, [r.event for r in self.rows])
        self.feed.source_id = source
        self.feed.events = [r.event for r in self.rows]
        self.delivery = Delivery(self.rows, self.views, self.policy)
        self.results = Results(self.views)

    def processor(self, **kw):
        value = self.owners[0].value
        p = CompletionProcessor(
            processing=self.metadata,
            source=self.feed,
            delivery=self.delivery,
            results=self.results,
            scope=value.scope,
            evidence=(EvidenceRecord(value.scope, value.evidence[0], runner_fixtures.POLICY),),
            **kw,
        )
        self.processors.append(p)
        return p

    async def asyncTearDown(self):
        if self.delivery.release:
            self.delivery.release.set()
        if self.feed.release:
            self.feed.release.set()
        for p in self.processors:
            await p.close()
        for owner in self.owners:
            await owner.asyncTearDown()

    async def test_useful_receipts_ack_exact_events_and_empty_replay(self):
        p = self.processor()
        step = await p.process_once()
        self.assertEqual((step.after.terminal_watermark, step.after.terminal_count), (2, 2))
        self.assertEqual(self.delivery.accepts, 2)
        for row in self.rows:
            ack = self.metadata.acks[row.event.sequence]
            self.assertEqual(ack.event, row.event)
            self.assertEqual(ack.projected_sha256, hashlib.sha256(row.canonical()).hexdigest())
            self.assertEqual(parse_ack(ack.canonical()), ack)
        self.assertEqual((await p.process_once()).outcomes, ())
        self.assertEqual(self.delivery.accepts, 2)

    async def test_unknown_a_stays_unacked_while_b_progresses(self):
        self.delivery.possible(self.rows[0])
        step = await self.processor().process_once()
        self.assertEqual([x.state for x in step.outcomes], ["unknown", "acknowledged"])
        self.assertEqual(
            (step.after.terminal_watermark, step.after.scan_after, step.after.terminal_count),
            (0, 2, 1),
        )
        self.assertNotIn(1, self.metadata.acks)
        self.assertEqual(self.delivery.accepts, 1)

    async def test_possible_a_after_cancel_expiry_or_case_change_never_terminal_skip(self):
        self.delivery.possible(self.rows[0])
        p = self.processor()
        for applicability in (
            "execution_ineligible",
            "expired",
            "outdated",
            "case_cancelled",
            "unavailable",
        ):
            self.views[self.rows[0].event.work_id] = replace(
                self.views[self.rows[0].event.work_id], applicability=applicability
            )
            step = await p.process_once()
            self.assertNotIn(1, self.metadata.acks)
            self.assertEqual(step.after.terminal_watermark, 0)
        self.assertEqual(self.delivery.accepts, 1)

    async def test_later_exact_receipt_closes_gap_without_another_accept(self):
        self.delivery.possible(self.rows[0])
        p = self.processor()
        await p.process_once()
        self.views[self.rows[0].event.work_id] = replace(
            self.views[self.rows[0].event.work_id], applicability="unavailable"
        )
        self.delivery.late_receipt(self.rows[0])
        step = await p.process_once()
        self.assertEqual(step.after.terminal_watermark, 2)
        self.assertEqual(self.metadata.acks[1].decision, "receiver_accepted")
        self.assertEqual(self.delivery.accepts, 1)

    async def test_new_outdated_result_is_not_required_asof_without_send(self):
        self.views[self.rows[0].event.work_id] = replace(
            self.views[self.rows[0].event.work_id], applicability="outdated"
        )
        await self.processor().process_once()
        self.assertEqual(self.metadata.acks[1].reason, "outdated")
        self.assertEqual(self.delivery.accepts, 1)

    async def test_case_unavailable_does_not_ack_and_later_other_work_progresses(self):
        self.views[self.rows[0].event.work_id] = replace(
            self.views[self.rows[0].event.work_id], applicability="unavailable"
        )
        step = await self.processor().process_once()
        self.assertEqual([x.state for x in step.outcomes], ["unavailable", "acknowledged"])
        self.assertNotIn(1, self.metadata.acks)

    async def test_wrong_attempt_or_digest_receipt_cannot_ack(self):
        self.delivery.possible(self.rows[1])
        self.delivery.late_receipt(self.rows[1])
        wrong = self.delivery.snapshots[self.rows[1].event.work_id]
        self.delivery.alter = lambda value: DelegationDelivery(wrong, "accepted")
        with self.assertRaisesRegex(ProjectionError, "^identity_conflict$"):
            await self.processor().process_once()
        self.assertEqual(self.metadata.acks, {})

    async def test_same_case_other_conversation_recipient_cannot_ack(self):
        other = DeliveryBinding(
            self.policy.bindings[0].case_id, "other_conversation", "other_recipient"
        )
        policy = replace(self.policy, bindings=self.policy.bindings + (other,))
        self.metadata.policy = policy
        self.metadata.point = replace(self.metadata.point, policy_sha256=policy.sha256)
        self.delivery.bindings = policy.bindings
        self.delivery.possible(self.rows[0])
        first = self.delivery.snapshots[self.rows[0].event.work_id]
        wrong = replace(first.intent, recipient_id="other_recipient")
        receipt = DeliveryReceipt(
            wrong.delivery_id,
            str(uuid4()),
            wrong.receiver_id,
            wrong.recipient_id,
            wrong.result_sha256,
            time.time_ns() // 1_000_000,
        )
        self.delivery.snapshots[self.rows[0].event.work_id] = DeliverySnapshot(wrong, True, receipt)
        with self.assertRaisesRegex(ProjectionError, "^identity_conflict$"):
            await self.processor().process_once(limit=1)
        self.assertEqual(self.metadata.acks, {})

    async def test_unroutable_results_stay_unacked_without_stalling_the_scan(self):
        unbound = DeliveryBinding("unbound_case", "unbound_conversation", "unbound_recipient")
        policy = replace(self.policy, bindings=(unbound,))
        self.metadata.policy = policy
        self.metadata.point = replace(self.metadata.point, policy_sha256=policy.sha256)
        self.delivery.bindings = policy.bindings
        p = self.processor()
        step = await p.process_once()
        self.assertEqual([x.state for x in step.outcomes], ["unavailable", "unavailable"])
        self.assertEqual((step.after.terminal_watermark, step.after.scan_after), (0, 2))
        again = await p.process_once()
        self.assertEqual([x.state for x in again.outcomes], ["unavailable", "unavailable"])
        self.assertEqual((self.metadata.acks, self.delivery.delivers), ({}, 0))
        self.assertEqual(p.metrics()["unroutable"], 4)

    async def first_call_unavailable(self, port, name, error):
        original, failures = getattr(port, name), iter((error,))

        async def busy(*args, **kwargs):
            failure = next(failures, None)
            if failure is not None:
                raise failure
            return await original(*args, **kwargs)

        setattr(port, name, busy)
        p = self.processor()
        step = await p.process_once()
        self.assertEqual([x.state for x in step.outcomes], ["unavailable", "acknowledged"])
        self.assertEqual((sorted(self.metadata.acks), step.after.scan_after), ([2], 2))
        self.assertEqual(p.metrics()["unavailable"], 1)
        again = await p.process_once()
        self.assertEqual([x.state for x in again.outcomes], ["acknowledged"])
        self.assertEqual(again.after.terminal_watermark, 2)

    async def test_feed_capacity_is_unacked_unavailable_while_later_work_progresses(self):
        await self.first_call_unavailable(self.feed, "read", WorkError("capacity"))

    async def test_delivery_capacity_is_unacked_unavailable_while_later_work_progresses(self):
        await self.first_call_unavailable(
            self.delivery, "deliver_once", CompletionError("capacity")
        )
        self.assertEqual(self.delivery.accepts, 2)

    async def test_result_read_capacity_is_unacked_unavailable_while_later_work_progresses(self):
        await self.first_call_unavailable(self.results, "inspect", DelegationRunError("capacity"))

    async def test_definite_dependency_failures_still_fail_the_step_closed(self):
        p = self.processor()
        for port, name, error, code in (
            (self.feed, "read", WorkError("unauthorized"), "unauthorized"),
            (
                self.results,
                "inspect",
                DelegationRunError("invalid_stored_state"),
                "invalid_source_state",
            ),
        ):
            with (
                self.subTest(code=code),
                patch.object(port, name, AsyncMock(side_effect=error)),
                self.assertRaisesRegex(ProjectionError, f"^{code}$"),
            ):
                await p.process_once()
        self.assertEqual((self.metadata.commits, self.delivery.delivers), (0, 0))

    async def test_public_models_reject_duplicate_outcomes_and_inconsistent_reason(self):
        from delegation_reliability.processing_models import ProcessingOutcome, ProcessingStep

        with self.assertRaises(ProjectionError):
            ProcessingPage(self.metadata.point, (self.rows[0], self.rows[0]))
        with self.assertRaises(ProjectionError):
            ProcessingOutcome(1, "acknowledged", None)
        outcome = ProcessingOutcome(1, "unknown", None)
        with self.assertRaises(ProjectionError):
            ProcessingStep(self.metadata.point, self.metadata.point, (outcome, outcome))
        with self.assertRaises(ProjectionError):
            ProcessingAcknowledgement(
                self.rows[0].event,
                "a" * 64,
                self.rows[0].request_sha256,
                self.policy.sha256,
                "rejected_content",
                "expired",
                time.time_ns() // 1_000_000,
                None,
            )

    async def test_source_failure_or_profile_mismatch_stops_before_any_ack_or_send(self):
        self.feed.failure = WorkError("not_found")
        with self.assertRaisesRegex(ProjectionError, "^invalid_source_state$"):
            await self.processor().process_once()
        self.assertEqual((self.metadata.commits, self.delivery.accepts), (0, 0))

    async def test_source_scope_changed_after_construction_fails_before_page(self):
        p = self.processor()
        self.feed.scope = WorkScope("foreign", "account")
        with self.assertRaisesRegex(ProjectionError, "^unauthorized$"):
            await p.process_once()
        self.assertEqual(self.metadata.commits, 0)

    async def test_policy_retarget_fails_before_any_receiver_call(self):
        p = self.processor()
        self.delivery.receiver_id = str(uuid4())
        with self.assertRaisesRegex(ProjectionError, "^identity_conflict$"):
            await p.process_once()
        self.assertEqual(self.delivery.delivers, 0)

    async def test_bound_total_limit_includes_wrap_and_rejects_invalid_limits(self):
        p = self.processor()
        self.delivery.possible(self.rows[0])
        await p.process_once(limit=1)
        self.assertEqual(len((await p.process_once(limit=1)).outcomes), 1)
        self.assertEqual(len((await p.process_once(limit=1)).outcomes), 1)
        for value in (0, 9, True):
            with self.assertRaisesRegex(ProjectionError, "^invalid_input$"):
                await p.process_once(limit=value)

    async def test_oversized_or_duplicate_page_rejected_before_send(self):
        def corrupt(page):
            object.__setattr__(page, "rows", (page.rows[0], page.rows[0]))
            return page

        self.metadata.alter = corrupt
        with self.assertRaisesRegex(ProjectionError, "^invalid_source_state$"):
            await self.processor().process_once(limit=2)
        self.assertEqual(self.delivery.accepts, 0)

    async def test_ack_commit_unknown_looks_up_once_without_resubmit(self):
        self.metadata.unknown = True
        await self.processor().process_once(limit=1)
        self.assertEqual(
            (self.metadata.commits, self.metadata.lookups, self.delivery.accepts), (1, 1, 1)
        )

    async def test_absent_or_failed_unknown_ack_lookup_stays_unknown(self):
        self.metadata.unknown = True
        self.metadata.persist = False
        with self.assertRaisesRegex(ProjectionError, "^acknowledgement_unknown$"):
            await self.processor().process_once(limit=1)
        self.assertEqual((self.metadata.commits, self.metadata.lookups), (1, 1))

    async def test_definite_conflict_returns_exact_winning_ack_without_second_write(self):
        self.metadata.unknown = True
        self.metadata.failure_code = "checkpoint_conflict"
        result = await self.processor().process_once(limit=1)
        self.assertEqual(result.outcomes[0].state, "acknowledged")
        self.assertEqual(
            (self.metadata.commits, self.metadata.lookups, self.delivery.accepts), (1, 1, 1)
        )

    async def test_definite_conflict_absence_stays_conflict(self):
        self.metadata.unknown = True
        self.metadata.failure_code = "checkpoint_conflict"
        self.metadata.persist = False
        with self.assertRaisesRegex(ProjectionError, "^checkpoint_conflict$"):
            await self.processor().process_once(limit=1)
        self.assertEqual((self.metadata.commits, self.metadata.lookups), (1, 1))

    async def test_definite_conflict_failed_lookup_stays_conflict(self):
        self.metadata.unknown = True
        self.metadata.failure_code = "checkpoint_conflict"
        self.metadata.lookup_failure = True
        with self.assertRaisesRegex(ProjectionError, "^checkpoint_conflict$"):
            await self.processor().process_once(limit=1)
        self.assertEqual((self.metadata.commits, self.metadata.lookups), (1, 1))

    async def test_unknown_ack_failed_lookup_stays_unknown(self):
        self.metadata.unknown = True
        self.metadata.lookup_failure = True
        with self.assertRaisesRegex(ProjectionError, "^acknowledgement_unknown$"):
            await self.processor().process_once(limit=1)
        self.assertEqual((self.metadata.commits, self.metadata.lookups), (1, 1))

    async def test_returned_ack_is_copied_before_next_port_await(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.feed.read

        async def held(*, after=None, limit=25):
            if after is not None and after.sequence == 1:
                entered.set()
                await release.wait()
            return await original(after=after, limit=limit)

        self.feed.read = held
        task = asyncio.create_task(self.processor().process_once(limit=2))
        await asyncio.wait_for(entered.wait(), 1)
        object.__setattr__(self.metadata.acks[1].event.scope, "tenant_id", "changed_original")
        release.set()
        result = await task
        self.assertEqual(
            result.outcomes[0].acknowledgement.event.scope.tenant_id,
            self.owners[0].value.scope.tenant_id,
        )

    async def test_waiter_timeout_retains_capacity_and_never_late_acknowledges(self):
        self.delivery.release = asyncio.Event()
        p = self.processor(max_active=1, timeout_ms=20, cleanup_ms=20)
        task = asyncio.create_task(p.process_once())
        await asyncio.wait_for(self.delivery.entered.wait(), 1)
        with self.assertRaisesRegex(ProjectionError, "^deadline_exceeded$"):
            await task
        self.assertEqual(p.pending_count, 1)
        with self.assertRaisesRegex(ProjectionError, "^capacity$"):
            await p.process_once()
        with self.assertRaisesRegex(ProjectionError, "^cleanup_incomplete$"):
            await p.close()
        self.delivery.release.set()
        await asyncio.sleep(0.01)
        await p.close()
        self.assertEqual((self.metadata.commits, self.delivery.accepts), (0, 0))

    async def test_caller_cancel_retains_owned_task_until_settlement(self):
        self.delivery.release = asyncio.Event()
        p = self.processor()
        task = asyncio.create_task(p.process_once())
        await asyncio.wait_for(self.delivery.entered.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(p.pending_count, 1)
        self.delivery.release.set()
        await asyncio.sleep(0.01)
        self.assertEqual(self.metadata.commits, 0)

    async def close_while_held(self, port, name, hold):
        entered, release = asyncio.Event(), asyncio.Event()
        original = getattr(port, name)

        async def held(*args, **kwargs):
            if hold(*args, **kwargs):
                entered.set()
                await release.wait()
            return await original(*args, **kwargs)

        setattr(port, name, held)
        p = self.processor()
        task = asyncio.create_task(p.process_once(limit=2))
        await asyncio.wait_for(entered.wait(), 1)
        closing = asyncio.create_task(p.close())
        await asyncio.sleep(0)
        release.set()
        with self.assertRaisesRegex(ProjectionError, "^request_aborted$"):
            await task
        await closing
        self.assertEqual(p.pending_count, 0)
        self.assertEqual(
            (sorted(self.metadata.acks), self.metadata.commits, self.delivery.delivers),
            ([1], 1, 1),
        )

    async def test_close_while_later_row_reads_starts_no_delivery_or_ack(self):
        await self.close_while_held(
            self.feed, "read", lambda *, after=None, limit=25: after.sequence == 1
        )

    async def test_close_during_ack_write_retains_it_and_starts_no_later_row(self):
        await self.close_while_held(
            self.metadata, "_commit", lambda point, row, ack: row.event.sequence == 1
        )

    async def test_telemetry_failure_does_not_change_ack_fact(self):
        p = self.processor()
        with patch(
            "delegation_reliability.projection_api.LOGGER.info",
            side_effect=RuntimeError("PRIVATE_LOG"),
        ):
            await p.process_once(limit=1)
        self.assertEqual(p.metrics()["telemetry_failed"], 1)
        self.assertEqual(len(self.metadata.acks), 1)

    def test_policy_strict_roundtrip_and_retarget_identity(self):
        self.assertEqual(parse_policy(self.policy.canonical()), self.policy)
        for raw in (b"{}", b"[]", b'{"schema_version":1,"schema_version":1}'):
            with self.assertRaises(ProjectionError):
                parse_policy(raw)
        self.assertNotEqual(
            self.policy.sha256, replace(self.policy, receiver_id=str(uuid4())).sha256
        )


class ProcessingWriteLifetimeTests(unittest.IsolatedAsyncioTestCase):
    async def held_write(self, *, cancel: bool) -> None:
        import threading

        from continuity_lab.work_api import BearerToken, WorkDirectory, WorkPrincipal
        from delegation_reliability.processing_api import ProcessingClient
        from delegation_reliability.projection_models import parse_projected

        owner = projection_fixtures.ProjectorTests(
            "test_useful_result_projects_refs_and_asof_only_then_empty"
        )
        await owner.asyncSetUp()
        row = (await owner.client().project_once()).rows[0]
        row = parse_projected(row.canonical())
        scope = WorkScope(row.event.scope.tenant_id, row.event.scope.account_id)
        policy = CompletionPolicy(
            str(uuid4()), (DeliveryBinding(row.case_id, owner.value.conversation_id, "recipient"),)
        )
        point = ProcessingCheckpoint(
            ProjectionBinding(row.event.source_id, WorkScope(scope.tenant_id, scope.account_id)),
            policy.sha256,
            0,
            0,
            0,
            0,
            1,
        )
        receipt = DeliveryReceipt(
            str(uuid4()),
            str(uuid4()),
            policy.receiver_id,
            "recipient",
            row.event.result_sha256,
            time.time_ns() // 1_000_000,
        )
        acknowledgement = ProcessingAcknowledgement(
            row.event,
            hashlib.sha256(row.canonical()).hexdigest(),
            row.request_sha256,
            policy.sha256,
            "receiver_accepted",
            "known_receipt",
            time.time_ns() // 1_000_000,
            receipt,
        )

        class Store:
            binding = ProjectionBinding(row.event.source_id, scope)

            def __init__(self):
                self.policy = policy
                self.entered = threading.Event()
                self.release = threading.Event()
                self.captured = None

            def commit(self, expected, draft, ack):
                self.captured = (expected, draft, ack)
                self.entered.set()
                assert self.release.wait(2)
                raise RuntimeError("PRIVATE_WRITE_SETTLED")

        store = Store()
        token = BearerToken("synthetic-processing-" + "x" * 40)
        directory = WorkDirectory(
            {token: WorkPrincipal("actor", WorkScope(scope.tenant_id, scope.account_id))}
        )
        client = ProcessingClient(
            store, directory, token, max_active=1, timeout_ms=20, cleanup_ms=20
        )
        observed = []
        loop = asyncio.get_running_loop()
        previous = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: observed.append(context))
        task = asyncio.create_task(client._commit(point, row, acknowledgement))
        try:
            self.assertTrue(await asyncio.to_thread(store.entered.wait, 1))
            if cancel:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            else:
                with self.assertRaisesRegex(ProjectionError, "^acknowledgement_unknown$"):
                    await task
            object.__setattr__(point.binding.scope, "tenant_id", "changed_original")
            object.__setattr__(row.event.scope, "account_id", "changed_original")
            object.__setattr__(receipt, "recipient_id", "changed_original")
            expected, draft, copied_ack = store.captured
            self.assertEqual(expected.binding.scope.tenant_id, scope.tenant_id)
            self.assertEqual(draft.event.scope.account_id, scope.account_id)
            self.assertEqual(copied_ack.receipt.recipient_id, "recipient")
            self.assertEqual(client.pending_count, 1)
            with self.assertRaisesRegex(ProjectionError, "^capacity$"):
                await client._page(1)
            with self.assertRaisesRegex(ProjectionError, "^cleanup_incomplete$"):
                await client.close()
        finally:
            store.release.set()
            await asyncio.sleep(0.02)
            await client.close()
            loop.set_exception_handler(previous)
            await owner.asyncTearDown()
        self.assertEqual(client.pending_count, 0)
        self.assertEqual(observed, [])

    async def test_commit_timeout_retains_real_thread_and_snapshots_inputs(self):
        await self.held_write(cancel=False)

    async def test_commit_cancellation_retains_real_thread_and_snapshots_inputs(self):
        await self.held_write(cancel=True)


class ProcessingSerializationTests(unittest.IsolatedAsyncioTestCase):
    """Actual SQLSTATE mapping at the private connection boundary."""

    async def asyncSetUp(self):
        await ProcessingTests.asyncSetUp(self)

    async def asyncTearDown(self):
        await ProcessingTests.asyncTearDown(self)

    async def test_store_serialization_before_or_during_commit_is_definite_conflict(self):
        from types import SimpleNamespace

        from psycopg.errors import SerializationFailure

        from delegation_reliability.processing_store import ProcessingStore

        row = self.rows[0]
        point = replace(self.metadata.point, projected_through=1)
        receipt = DeliveryReceipt(
            str(uuid4()),
            str(uuid4()),
            self.policy.receiver_id,
            "recipient",
            row.event.result_sha256,
            time.time_ns() // 1_000_000,
        )
        observed = ProcessingAcknowledgement(
            row.event,
            hashlib.sha256(row.canonical()).hexdigest(),
            row.request_sha256,
            self.policy.sha256,
            "receiver_accepted",
            "known_receipt",
            time.time_ns() // 1_000_000,
            receipt,
        )
        for failure in ("before", "commit"):

            class Transaction:
                def __init__(self, mode):
                    self.failure = mode

                def __enter__(self):
                    return self

                def __exit__(self, kind, error, trace):
                    if kind is None and self.failure == "commit":
                        raise SerializationFailure("PRIVATE_SERIALIZATION")

            class Connection:
                calls = 0

                def __init__(self, mode):
                    self.failure = mode

                def transaction(self):
                    return Transaction(self.failure)

                def execute(self, *args):
                    self.calls += 1
                    if self.failure == "before" and self.calls == 1:
                        raise SerializationFailure("PRIVATE_SERIALIZATION")
                    return SimpleNamespace(rowcount=1, fetchone=lambda: None)

                def close(self):
                    pass

            connection = Connection(failure)
            store = object.__new__(ProcessingStore)
            store.settings = SimpleNamespace(
                schema="p3_projection_test", connect=lambda connection=connection: connection
            )
            store.binding = point.binding
            store.policy = self.policy
            store.failpoint = None
            store._state = lambda c: point
            store._row = lambda c, s: row
            store._ack = lambda c, r: None
            with self.assertRaisesRegex(ProjectionError, "^checkpoint_conflict$"):
                store.commit(point, row, observed)
