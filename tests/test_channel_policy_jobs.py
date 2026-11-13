"""Offline composition and actual-owner controls; no PostgreSQL/provider calls."""

from __future__ import annotations

import asyncio
import copy
import gc
import hashlib
import inspect
import json
import subprocess
import sys
import time
import unittest
import warnings
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from continuity_lab.delivery_api import DeliverySnapshot
from continuity_lab.execution_api import ExecutionObservation
from continuity_lab.work_api import WorkPayload, WorkRecord, WorkScope
from delegation_reliability import (
    ChannelPolicyExecutionView,
    ChannelPolicyRun,
    CompletionError,
    DelegationRunError,
    channel_policy_key,
    encode_channel_policy_request,
    produce_channel_policy_request,
)
from delegation_reliability.contracts import Scope, canonical
from delegation_reliability.coordinator import CaseSnapshot
from delegation_reliability.delivery_contract import DelegationDelivery, DeliveryBinding
from delegation_reliability.fixed_policy_contracts import produce_fixed_policy_request
from delegation_reliability.security import EvidenceRecord
from services.channel_policy_demo import jobs as m

ROOT = Path(__file__).resolve().parents[1]


def fixture(label="a"):
    data = json.loads((ROOT / "contracts/delegation/fixed-policy-v2.json").read_bytes())
    raw = copy.deepcopy(data["producer_input"])
    raw["deadline_at_ms"] = time.time_ns() // 1_000_000 + 30000
    operation = str(uuid4())
    raw["delegation_id"] = channel_policy_key(operation)
    facts = json.loads(data["facts_body_utf8"])
    facts["observations"] = [
        {"fact_id": "notice_0", "days_before_arrival": 10 if label == "a" else 14}
    ]
    bodies = (data["policy_body_utf8"].encode(), canonical(facts))
    for ref, body in zip(raw["evidence"], bodies, strict=True):
        ref.update(
            version="distinct_" + label,
            sha256=hashlib.sha256(body).hexdigest(),
            byte_length=len(body),
        )
    inner = produce_fixed_policy_request(raw)
    request = produce_channel_policy_request(
        {
            "schema_version": 1,
            "kind": "delegation.request",
            "capability": "booking.evaluate_policy",
            "input_schema_version": 3,
            "origin": {
                "kind": "p2.prepared_dispatch.v1",
                "profile_id": str(uuid4()),
                "operation_key": operation,
                "input_receipt_id": str(uuid4()),
                "payload_sha256": hashlib.sha256(b"original").hexdigest(),
                "payload_byte_length": 8,
            },
            "request": inner.to_wire(),
        }
    )
    records = tuple(
        EvidenceRecord(request.scope, replace(ref), body)
        for ref, body in zip(request.request.evidence, bodies, strict=True)
    )
    return request, records


def changed_original(request):
    operation = str(uuid4())
    inner = request.request.to_wire()
    inner.pop("input_fingerprint")
    inner["delegation_id"] = channel_policy_key(operation)
    outer = request.to_wire()
    outer.pop("input_fingerprint")
    outer["origin"]["operation_key"] = operation
    outer["origin"]["input_receipt_id"] = str(uuid4())
    outer["request"] = produce_fixed_policy_request(inner).to_wire()
    return produce_channel_policy_request(outer)


def result_for(request, work_id):
    record = WorkRecord(
        work_id,
        WorkScope(request.scope.tenant_id, request.scope.account_id),
        channel_policy_key(request.origin.operation_key),
        WorkPayload(
            "booking.evaluate_policy",
            encode_channel_policy_request(request),
            request.deadline_at_ms,
        ),
        time.time_ns() // 1_000_000,
        False,
    )
    return ChannelPolicyRun(
        ChannelPolicyExecutionView(
            ExecutionObservation(record, None, None, 0, "accepted"), request, None, "missing"
        ),
        False,
    )


class Port:
    def __init__(self, role, clients):
        self.role, self.clients = role, clients
        self.scope = WorkScope(clients.request.scope.tenant_id, clients.request.scope.account_id)
        self.receiver_id = str(uuid4())
        self.pending_count = 0
        self.close_calls = 0
        self.close_entered, self.closed = asyncio.Event(), asyncio.Event()
        self.close_release = None
        self.close_error = None

    async def close(self):
        self.close_calls += 1
        self.close_entered.set()
        if self.close_release is not None:
            await self.close_release.wait()
        if self.close_error is not None:
            raise self.close_error
        self.clients.events.append("close:" + self.role)
        self.closed.set()


class Cases:
    def __init__(self, request):
        self.request, self.closed = request, 0

    async def snapshot(self, *, case_id):
        return CaseSnapshot(self.request.scope, case_id, self.request.request_revision, False)

    async def close(self):
        self.closed += 1


class Clients:
    def __init__(self, request):
        self.request = request
        self.events, self.ports, self.selected = [], [], []
        self.entered = {
            role: asyncio.Event() for role in ("execution", "specialist", "delivery", "receiver")
        }
        self.release, self.errors, self.aliases = {}, {}, {}
        self.closed = 0

    async def opened(self, role):
        self.events.append("open:" + role)
        self.entered[role].set()
        if role in self.release:
            await self.release[role].wait()
        if role in self.errors:
            raise self.errors[role]
        value = self.aliases.get(role)
        if value is None:
            value = Port(role, self)
            self.ports.append(value)
        return value

    async def open_execution(self):
        return await self.opened("execution")

    async def open_specialist(self, *, evidence):
        self.selected.append(evidence)
        return await self.opened("specialist")

    async def open_delivery(self):
        return await self.opened("delivery")

    async def open_receiver(self):
        return await self.opened("receiver")

    async def close(self):
        self.closed += 1


class Runner:
    def __init__(self, *, executions, specialist, evidence, owner_id, **_):
        self.executions, self.specialist = executions, specialist
        self.evidence, self.owner_id = evidence, owner_id
        self.pending_count = self.calls = self.close_calls = 0
        self.run_entered, self.run_finished, self.close_entered = (
            asyncio.Event(),
            asyncio.Event(),
            asyncio.Event(),
        )
        self.run_release = self.close_release = None
        self.error = None
        self.bad_result = False
        self.late_pending = False
        self.close_error = None
        self.value = None

    async def inspect(self, work_id):
        return result_for(self.executions.clients.request, work_id).view

    async def run_once(self, work_id, command_id):
        self.calls += 1
        self.command_id = command_id
        self.run_entered.set()
        self.pending_count = 1
        try:
            if self.run_release is not None:
                await self.run_release.wait()
            if self.error is not None:
                raise self.error
            self.value = result_for(self.executions.clients.request, work_id)
            return object() if self.bad_result else self.value
        finally:
            self.pending_count = int(self.late_pending)
            self.run_finished.set()

    async def close(self):
        self.close_calls += 1
        self.close_entered.set()
        if self.close_release is not None:
            await self.close_release.wait()
        if self.close_error is not None:
            raise self.close_error
        await self.executions.close()
        await self.specialist.close()
        if self.pending_count:
            raise DelegationRunError("cleanup_incomplete")


class Delivery:
    def __init__(self, *, deliveries, receiver, results, **_):
        self.deliveries, self.receiver, self.results = deliveries, receiver, results
        self.pending_count = self.calls = self.close_calls = 0
        self.entered, self.finished, self.close_entered = (
            asyncio.Event(),
            asyncio.Event(),
            asyncio.Event(),
        )
        self.release = self.close_release = None
        self.error = None
        self.close_error = None
        self.state = "missing"

    async def deliver_once(self, work_id):
        self.calls += 1
        self.entered.set()
        self.pending_count = 1
        try:
            if self.release is not None:
                await self.release.wait()
            if self.error is not None:
                raise self.error
            return DelegationDelivery(DeliverySnapshot(None, False, None), self.state)
        finally:
            self.pending_count = 0
            self.finished.set()

    async def close(self):
        self.close_calls += 1
        self.close_entered.set()
        if self.close_release is not None:
            await self.close_release.wait()
        if self.close_error is not None:
            raise self.close_error
        await self.deliveries.close()
        await self.receiver.close()


class CatalogueTests(unittest.TestCase):
    def test_exact_winning_pair_ignores_newer_catalogue_order_and_ref_mixes(self):
        a, records_a = fixture("a")
        b, records_b = fixture("b")
        catalogue = m.EvidenceCatalogue((records_b, records_a))
        self.assertEqual(catalogue.select(a), records_a)
        self.assertEqual(catalogue.select(b), records_b)
        raw = a.request.to_wire()
        raw.pop("input_fingerprint")
        raw["evidence"][1] = b.request.to_wire()["evidence"][1]
        inner = produce_fixed_policy_request(raw)
        changed = replace(a, request=inner)
        # Reproduce a valid public outer fingerprint for the changed winning refs.
        wire = changed.to_wire()
        wire.pop("input_fingerprint")
        changed = produce_channel_policy_request(wire)
        with self.assertRaisesRegex(m.JobError, "^identity_conflict$"):
            catalogue.select(changed)

    def test_catalogue_snapshots_original_refs_scope_and_bodies(self):
        request, records = fixture()
        catalogue = m.EvidenceCatalogue((records,))
        object.__setattr__(records[0].reference, "version", "changed")
        selected = catalogue.select(request)
        self.assertEqual(selected[0].reference.version, "distinct_a")
        self.assertIsNot(selected[0], records[0])
        with self.assertRaises(FrozenInstanceError):
            selected[0].body = b"changed"

    def test_rejects_invalid_pair_shape_hash_media_scope_and_duplicate(self):
        _, records = fixture()
        invalid = [
            (),
            (records[0],),
            (records[0], records[0]),
            (replace(records[0], body=b"private"), records[1]),
            (records[0], replace(records[1], scope=Scope("foreign", "account"))),
        ]
        for pair in invalid:
            with self.subTest(pair_length=len(pair)), self.assertRaises(m.JobError):
                m.EvidenceCatalogue((pair,))
        with self.assertRaisesRegex(m.JobError, "^identity_conflict$"):
            m.EvidenceCatalogue((records, records))
        with self.assertRaisesRegex(m.JobError, "^invalid_input$"):
            m.EvidenceCatalogue(tuple(records for _ in range(17)))

    def test_import_is_inert_after_public_sdk_import(self):
        script = """
import delegation_reliability, asyncio, socket, threading
from pathlib import Path
from unittest.mock import patch
with patch.object(socket, 'create_connection', side_effect=AssertionError('network')), patch.object(threading.Thread, 'start', side_effect=AssertionError('thread')), patch.object(asyncio, 'create_task', side_effect=AssertionError('task')), patch.object(Path, 'read_bytes', side_effect=AssertionError('file')), patch.object(Path, 'read_text', side_effect=AssertionError('file')):
 import services.channel_policy_demo.jobs
print('inert')
"""
        completed = subprocess.run(
            [sys.executable, "-I", "-B", "-c", script],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(
            (completed.returncode, completed.stdout.strip()), (0, "inert"), completed.stderr
        )


class JobTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.request, self.records = fixture()
        self.work, self.owner = str(uuid4()), str(uuid4())
        self.clients, self.cases = Clients(self.request), Cases(self.request)
        self.runners, self.deliveries, self.factories, self.tasks, self.events = [], [], [], [], []

        def runner(**values):
            value = Runner(**values)
            self.runners.append(value)
            return value

        def delivery(**values):
            value = Delivery(**values)
            self.deliveries.append(value)
            return value

        self.runner_patch = patch.object(m, "ChannelPolicyRunner", side_effect=runner)
        self.delivery_patch = patch.object(m, "ChannelPolicyDeliveryClient", side_effect=delivery)
        self.runner_patch.start()
        self.delivery_patch.start()

    async def asyncTearDown(self):
        for event in self.events:
            event.set()
        for clients in {self.clients, *(port.clients for port in self.clients.ports)}:
            clients.errors.clear()
            for event in clients.release.values():
                event.set()
            for port in clients.ports:
                port.close_error = None
                if port.close_release is not None:
                    port.close_release.set()
        for owner in self.runners + self.deliveries:
            owner.close_error = None
            owner.pending_count = 0
            for name in ("release", "run_release", "close_release"):
                event = getattr(owner, name, None)
                if event is not None:
                    event.set()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        for factory in self.factories:
            for _ in range(3):
                try:
                    await factory.close()
                    break
                except m.JobError:
                    continue
            self.assertEqual(factory.active_count, 0)
        self.runner_patch.stop()
        self.delivery_patch.stop()

    def factory(self, **changes):
        options = {
            "scope": self.request.scope,
            "case_authority": self.cases,
            "bindings": (
                DeliveryBinding(
                    self.request.case_id, self.request.conversation_id, "recipient_demo"
                ),
            ),
            "catalogue": m.EvidenceCatalogue((self.records,)),
            "clients": self.clients,
            "timeout_s": 0.1,
            "cleanup_timeout_s": 0.03,
        }
        options.update(changes)
        factory = m.ChannelPolicyJobFactory(**options)
        self.factories.append(factory)
        return factory

    async def opened(self, factory=None, work=None):
        factory = factory or self.factory()
        job = await factory.open(
            work_id=work or self.work, owner_id=self.owner, request=self.request
        )
        return factory, job

    def command(self, work=None):
        return "cp45_" + (work or self.work).replace("-", "")

    async def until(self, event):
        await asyncio.wait_for(event.wait(), 1)

    def started(self, action):
        task = asyncio.create_task(action)
        self.tasks.append(task)
        return task

    async def test_execution_then_delivery_exact_owner_command_and_no_reinvocation(self):
        factory, job = await self.opened()
        self.assertEqual((job.pending_count, factory.active_count), (0, 1))
        value = await job.run_once(self.work, self.command())
        self.assertIs(value, job.observation.execution)
        self.assertEqual(job.observation.delivery.state, "missing")
        self.assertEqual(
            (self.runners[0].owner_id, self.runners[0].command_id), (self.owner, self.command())
        )
        self.assertEqual(self.clients.selected, [self.records])
        self.assertIs(await job.run_once(self.work, self.command()), value)
        self.assertEqual((self.runners[0].calls, self.deliveries[0].calls), (1, 1))
        await job.close()
        self.assertEqual(factory.active_count, 0)
        self.assertEqual(
            self.clients.events[-4:],
            ["close:delivery", "close:receiver", "close:execution", "close:specialist"],
        )
        self.assertEqual((self.clients.closed, self.cases.closed), (0, 0))
        self.assertTrue(all(port.close_calls == 1 for port in self.clients.ports))

    async def test_stale_delivery_denial_preserves_execution_and_separate_observation(self):
        _, job = await self.opened()
        self.deliveries[0].error = CompletionError("not_eligible")
        value = await job.run_once(self.work, self.command())
        self.assertIs(value, job.observation.execution)
        self.assertEqual(
            (
                job.observation.execution_code,
                job.observation.delivery.state,
                job.observation.delivery.code,
            ),
            (None, "denied", "not_eligible"),
        )
        self.assertNotIn("Original", repr(job.observation))

    async def test_ambiguous_delivery_is_unknown_never_empty_or_retried(self):
        _, job = await self.opened()
        self.deliveries[0].error = CompletionError("acknowledgement_unknown")
        first = await job.run_once(self.work, self.command())
        self.assertEqual(
            (job.observation.delivery.state, job.observation.delivery.code),
            ("unknown", "acknowledgement_unknown"),
        )
        self.assertIs(await job.run_once(self.work, self.command()), first)
        self.assertEqual(self.deliveries[0].calls, 1)

    async def test_raw_delivery_exception_never_erases_execution_or_leaks_text(self):
        _, job = await self.opened()
        self.deliveries[0].error = RuntimeError("PRIVATE_DEPENDENCY_SENTINEL")
        value = await job.run_once(self.work, self.command())
        self.assertIs(value, job.observation.execution)
        self.assertEqual(
            (job.observation.delivery.state, job.observation.delivery.code),
            ("failed", "unavailable"),
        )
        self.assertNotIn("PRIVATE", repr(job.observation))

    async def test_execution_failure_has_no_delivery_and_finite_error(self):
        _, job = await self.opened()
        self.runners[0].error = RuntimeError("PRIVATE_EXECUTION_SENTINEL")
        with self.assertRaisesRegex(m.JobError, "^unavailable$") as caught:
            await job.run_once(self.work, self.command())
        self.assertIsNone(caught.exception.__cause__)
        self.assertEqual(
            (job.observation.execution, job.observation.execution_code, self.deliveries[0].calls),
            (None, "unavailable", 0),
        )

    async def test_cancelled_runner_waiter_retains_actual_job_and_skips_later_delivery(self):
        factory, job = await self.opened()
        runner = self.runners[0]
        runner.run_release = asyncio.Event()
        task = self.started(job.run_once(self.work, self.command()))
        await self.until(runner.run_entered)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual((factory.active_count, job.pending_count), (1, 1))
        with self.assertRaisesRegex(m.JobError, "^cleanup_incomplete$"):
            await job.close()
        runner.run_release.set()
        await self.until(runner.run_finished)
        await job.close()
        self.assertIsNotNone(job.observation.execution)
        self.assertEqual((self.deliveries[0].calls, factory.active_count), (0, 0))

    async def test_timed_out_waiter_does_not_cancel_or_start_new_delivery(self):
        factory, job = await self.opened(self.factory(timeout_s=0.015))
        runner = self.runners[0]
        runner.run_release = asyncio.Event()
        with self.assertRaisesRegex(m.JobError, "^deadline_exceeded$"):
            await job.run_once(self.work, self.command())
        self.assertEqual(job.pending_count, 1)
        runner.run_release.set()
        await self.until(runner.run_finished)
        await job.close()
        self.assertEqual((self.deliveries[0].calls, factory.active_count), (0, 0))

    async def test_held_delivery_is_one_union_slot_and_other_job_makes_progress(self):
        factory, job = await self.opened()
        delivery = self.deliveries[0]
        delivery.release = asyncio.Event()
        task = self.started(job.run_once(self.work, self.command()))
        await self.until(delivery.entered)
        self.assertEqual(
            dict(job.metrics()),
            {
                "active": 1,
                "runner_pending": 0,
                "delivery_pending": 1,
                "stage_pending": 1,
                "close_pending": 0,
            },
        )
        other_work = str(uuid4())
        _, other = await self.opened(factory, other_work)
        await other.run_once(other_work, self.command(other_work))
        await other.close()
        self.assertEqual(factory.active_count, 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        with self.assertRaisesRegex(m.JobError, "^cleanup_incomplete$"):
            await job.close()
        delivery.release.set()
        await self.until(delivery.finished)
        await job.close()
        self.assertIsNotNone(job.observation.execution)

    async def test_two_idle_returned_jobs_still_reserve_global_factory_tickets(self):
        factory, first = await self.opened()
        _, second = await self.opened(factory, str(uuid4()))
        self.assertEqual(
            (first.pending_count, second.pending_count, factory.active_count), (0, 0, 2)
        )
        with self.assertRaisesRegex(m.JobError, "^capacity$"):
            await factory.open(work_id=str(uuid4()), owner_id=self.owner, request=self.request)
        await first.close()
        third_work = str(uuid4())
        _, third = await self.opened(factory, third_work)
        await third.run_once(third_work, self.command(third_work))
        self.assertEqual(factory.active_count, 2)

    async def test_close_retains_delivery_before_runner_and_reuses_actual_observer(self):
        factory, job = await self.opened()
        delivery, runner = self.deliveries[0], self.runners[0]
        delivery.close_release = asyncio.Event()
        with self.assertRaisesRegex(m.JobError, "^cleanup_incomplete$"):
            await job.close()
        self.assertEqual((delivery.close_calls, runner.close_calls, job.pending_count), (1, 0, 1))
        with self.assertRaisesRegex(m.JobError, "^cleanup_incomplete$"):
            await job.close()
        self.assertEqual(delivery.close_calls, 1)
        delivery.close_release.set()
        await job.close()
        self.assertEqual(
            (delivery.close_calls, runner.close_calls, factory.active_count), (1, 1, 0)
        )

    async def test_failed_delivery_close_does_not_close_runner_until_explicit_retry(self):
        factory, job = await self.opened()
        delivery, runner = self.deliveries[0], self.runners[0]
        delivery.close_error = RuntimeError("PRIVATE_CLOSE")
        with self.assertRaisesRegex(m.JobError, "^cleanup_incomplete$"):
            await job.close()
        self.assertEqual((runner.close_calls, factory.active_count), (0, 1))
        delivery.close_error = None
        await job.close()
        self.assertEqual(
            (delivery.close_calls, runner.close_calls, factory.active_count), (2, 1, 0)
        )

    async def test_cancelled_partial_factory_still_counts_globally_until_actual_close(self):
        self.clients.release["specialist"] = asyncio.Event()
        factory = self.factory()
        opening = self.started(
            factory.open(work_id=self.work, owner_id=self.owner, request=self.request)
        )
        await self.until(self.clients.entered["specialist"])
        execution = self.clients.ports[0]
        execution.close_release = asyncio.Event()
        self.clients.errors["specialist"] = asyncio.CancelledError()
        self.clients.release["specialist"].set()
        await self.until(execution.close_entered)
        opening.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await opening
        # Core may free its empty owner, but this independent ticket is still actual.
        self.assertEqual((factory.active_count, factory.metrics()["partial_owners"]), (1, 1))
        self.clients.errors.clear()
        self.clients.release.clear()
        _, second = await self.opened(factory, str(uuid4()))
        with self.assertRaisesRegex(m.JobError, "^capacity$"):
            await factory.open(work_id=str(uuid4()), owner_id=self.owner, request=self.request)
        ticket = next(ticket for ticket in factory._tickets if ticket.job is None)
        execution.close_release.set()
        await asyncio.gather(ticket.construction, return_exceptions=True)
        third_work = str(uuid4())
        _, third = await self.opened(factory, third_work)
        await third.run_once(third_work, self.command(third_work))
        await third.close()
        await second.close()
        self.assertEqual(factory.active_count, 0)

    async def test_late_first_port_after_cancel_is_adopted_closed_and_no_next_stage(self):
        self.clients.release["execution"] = asyncio.Event()
        factory = self.factory()
        task = self.started(
            factory.open(work_id=self.work, owner_id=self.owner, request=self.request)
        )
        await self.until(self.clients.entered["execution"])
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        with self.assertRaisesRegex(m.JobError, "^cleanup_incomplete$"):
            await factory.close()
        self.assertEqual(factory.active_count, 1)
        self.clients.release["execution"].set()
        await factory.close()
        self.assertEqual((factory.active_count, self.clients.ports[0].close_calls), (0, 1))
        self.assertNotIn("open:specialist", self.clients.events)

    async def test_failed_delivery_constructor_closes_highest_runner_once(self):
        with patch.object(
            m, "ChannelPolicyDeliveryClient", side_effect=RuntimeError("PRIVATE_CONSTRUCTOR")
        ):
            factory = self.factory()
            with self.assertRaisesRegex(m.JobError, "^unavailable$"):
                await factory.open(work_id=self.work, owner_id=self.owner, request=self.request)
        self.assertEqual(factory.active_count, 0)
        self.assertTrue(all(port.close_calls == 1 for port in self.clients.ports))
        self.assertEqual(self.runners[0].close_calls, 1)
        self.assertEqual(
            self.clients.events[-4:],
            ["close:delivery", "close:receiver", "close:execution", "close:specialist"],
        )

    async def test_same_job_alias_rejected_without_double_closing_execution(self):
        self.clients.release["specialist"] = asyncio.Event()
        factory = self.factory()
        opening = self.started(
            factory.open(work_id=self.work, owner_id=self.owner, request=self.request)
        )
        await self.until(self.clients.entered["specialist"])
        self.clients.aliases["specialist"] = self.clients.ports[0]
        self.clients.release["specialist"].set()
        with self.assertRaisesRegex(m.JobError, "^invalid_input$"):
            await opening
        self.assertEqual((factory.active_count, self.clients.ports[0].close_calls), (0, 1))

    async def test_other_job_alias_is_borrowed_and_never_closed_by_failed_job(self):
        factory, first = await self.opened()
        execution = self.clients.ports[0]
        self.clients.aliases["execution"] = execution
        with self.assertRaisesRegex(m.JobError, "^invalid_input$"):
            await factory.open(work_id=str(uuid4()), owner_id=self.owner, request=self.request)
        self.assertEqual((factory.active_count, execution.close_calls), (1, 0))
        self.clients.aliases.clear()
        await first.run_once(self.work, self.command())
        await first.close()
        self.assertEqual(execution.close_calls, 1)

    async def test_shared_case_alias_is_never_closed(self):
        self.clients.aliases["execution"] = self.cases
        factory = self.factory()
        with self.assertRaisesRegex(m.JobError, "^invalid_input$"):
            await factory.open(work_id=self.work, owner_id=self.owner, request=self.request)
        self.assertEqual((factory.active_count, self.cases.closed), (0, 0))

    async def test_invalid_scope_route_identity_command_and_budget_start_nothing(self):
        factory = self.factory()
        foreign = replace(self.request.request, scope=Scope("other", "account"))
        # Public producer re-fingerprints the changed inner and outer values.
        raw = foreign.to_wire()
        raw.pop("input_fingerprint")
        outer = self.request.to_wire()
        outer.pop("input_fingerprint")
        outer["request"] = produce_fixed_policy_request(raw).to_wire()
        changed = produce_channel_policy_request(outer)
        with self.assertRaisesRegex(m.JobError, "^unauthorized$"):
            await factory.open(work_id=self.work, owner_id=self.owner, request=changed)
        self.assertEqual(self.clients.events, [])
        _, job = await self.opened(factory)
        for work, command in [(str(uuid4()), self.command()), (self.work, "changed")]:
            with self.assertRaisesRegex(m.JobError, "^identity_conflict$"):
                await job.run_once(work, command)
        self.assertEqual(self.runners[0].calls, 0)
        for budget in [True, float("inf"), 0, 11]:
            with self.assertRaisesRegex(m.JobError, "^invalid_input$"):
                self.factory(timeout_s=budget)

    async def test_execution_late_pending_is_not_hidden_by_completed_stage(self):
        factory, job = await self.opened()
        runner = self.runners[0]
        runner.error, runner.late_pending = DelegationRunError("deadline_exceeded"), True
        with self.assertRaisesRegex(m.JobError, "^deadline_exceeded$"):
            await job.run_once(self.work, self.command())
        self.assertEqual((job.pending_count, job.metrics()["runner_pending"]), (1, 1))
        with self.assertRaisesRegex(m.JobError, "^cleanup_incomplete$"):
            await job.close()
        self.assertEqual(factory.active_count, 1)
        runner.pending_count = 0
        await job.close()
        self.assertEqual(factory.active_count, 0)

    async def test_create_task_failure_closes_unstarted_coroutine_and_preserves_ticket_state(self):
        factory = self.factory()
        captured = []

        def failed(action):
            captured.append(action)
            raise asyncio.CancelledError()

        with (
            patch.object(m.asyncio, "create_task", side_effect=failed),
            self.assertRaises(asyncio.CancelledError),
        ):
            await factory.open(work_id=self.work, owner_id=self.owner, request=self.request)
        self.assertEqual(factory.active_count, 0)
        self.assertTrue(
            all(inspect.getcoroutinestate(action) == inspect.CORO_CLOSED for action in captured)
        )
        _, job = await self.opened(factory)
        with (
            patch.object(m.asyncio, "create_task", side_effect=failed),
            self.assertRaises(asyncio.CancelledError),
        ):
            await job.run_once(self.work, self.command())
        self.assertEqual((job.pending_count, factory.active_count), (0, 1))
        await job.run_once(self.work, self.command())
        with (
            patch.object(m.asyncio, "create_task", side_effect=failed),
            self.assertRaises(asyncio.CancelledError),
        ):
            await job.close()
        await job.close()
        with warnings.catch_warnings(record=True) as seen:
            warnings.simplefilter("always")
            gc.collect()
        self.assertFalse([x for x in seen if issubclass(x.category, RuntimeWarning)])
        self.assertTrue(
            all(inspect.getcoroutinestate(action) == inspect.CORO_CLOSED for action in captured)
        )

    async def test_finite_error_codes_ignore_private_getters_args_and_unhashable_code(self):
        _, job = await self.opened()

        class Hostile(CompletionError):
            @property
            def code(self):
                raise AssertionError("PRIVATE_GETTER")

            @code.setter
            def code(self, value):
                pass

        error = Hostile.__new__(Hostile)
        RuntimeError.__init__(error, "PRIVATE_ARGUMENTS")
        self.deliveries[0].error = error
        await job.run_once(self.work, self.command())
        self.assertEqual(job.observation.delivery.code, "unavailable")
        for invalid in [[], {"private": "value"}, "PRIVATE_CODE"]:
            mutated = CompletionError("not_eligible")
            mutated.code = invalid
            self.assertEqual(m._code(mutated), "unavailable")
        self.assertNotIn("PRIVATE", repr(job.observation))

    async def test_factory_close_cancellation_retains_same_observer_and_both_jobs_drain(self):
        factory, first = await self.opened()
        _, second = await self.opened(factory, str(uuid4()))
        for owner in self.deliveries:
            owner.close_release = asyncio.Event()
        closing = self.started(factory.close())
        await self.until(self.deliveries[0].close_entered)
        await self.until(self.deliveries[1].close_entered)
        closing.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await closing
        self.assertEqual(
            (factory.active_count, first.pending_count, second.pending_count), (2, 1, 1)
        )
        for owner in self.deliveries:
            owner.close_release.set()
        await factory.close()
        self.assertEqual(factory.active_count, 0)
        self.assertTrue(all(owner.close_calls == 1 for owner in self.deliveries))

    async def test_telemetry_failure_does_not_replace_execution_or_delivery_observation(self):
        factory, job = await self.opened()
        self.deliveries[0].error = CompletionError("not_eligible")
        with patch.object(m.LOGGER, "info", side_effect=RuntimeError("PRIVATE_EXPORTER")):
            value = await job.run_once(self.work, self.command())
        self.assertIs(job.observation.execution, value)
        self.assertEqual(
            (job.observation.delivery.code, factory.metrics()["telemetry_failed"]),
            ("not_eligible", 1),
        )

    async def test_close_resource_task_allocation_failure_retains_owner_and_retry_progresses(self):
        factory, job = await self.opened()
        original = asyncio.create_task
        actions = []

        def allocate(action):
            actions.append(action)
            if len(actions) == 3:
                raise RuntimeError("PRIVATE_TASK_ALLOCATION")
            return original(action)

        with (
            patch.object(m.asyncio, "create_task", side_effect=allocate),
            self.assertRaisesRegex(m.JobError, "^cleanup_incomplete$"),
        ):
            await job.close()
        self.assertEqual(factory.active_count, 1)
        self.assertEqual(self.deliveries[0].close_calls, 1)
        self.assertEqual(self.runners[0].close_calls, 0)
        self.assertEqual(inspect.getcoroutinestate(actions[2]), inspect.CORO_CLOSED)
        await job.close()
        self.assertEqual(
            (factory.active_count, self.deliveries[0].close_calls, self.runners[0].close_calls),
            (0, 1, 1),
        )

    async def test_factory_close_observer_allocation_failure_retains_jobs_and_retry_progresses(
        self,
    ):
        factory, job = await self.opened()
        original = asyncio.create_task
        actions = []

        def allocate(action):
            actions.append(action)
            if len(actions) == 2:
                raise asyncio.CancelledError()
            return original(action)

        with (
            patch.object(m.asyncio, "create_task", side_effect=allocate),
            self.assertRaises(asyncio.CancelledError),
        ):
            await factory.close()
        self.assertEqual((factory.active_count, job.pending_count), (1, 0))
        self.assertEqual(inspect.getcoroutinestate(actions[1]), inspect.CORO_CLOSED)
        await factory.close()
        self.assertEqual(factory.active_count, 0)

    async def test_cancelled_delivery_preserves_execution_and_propagates_control_flow(self):
        _, job = await self.opened()
        self.deliveries[0].error = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await job.run_once(self.work, self.command())
        self.assertIsNotNone(job.observation.execution)
        self.assertEqual(
            (job.observation.delivery.state, job.observation.delivery.code),
            ("unknown", "request_aborted"),
        )

    async def test_factory_timeout_retains_late_setup_until_port_is_adopted_and_closed(self):
        self.clients.release["execution"] = asyncio.Event()
        factory = self.factory(timeout_s=0.015)
        with self.assertRaisesRegex(m.JobError, "^deadline_exceeded$"):
            await factory.open(work_id=self.work, owner_id=self.owner, request=self.request)
        self.assertEqual(factory.active_count, 1)
        self.clients.release["execution"].set()
        await factory.close()
        self.assertEqual(factory.active_count, 0)
        self.assertEqual(self.clients.events, ["open:execution", "close:execution"])

    async def test_nonfinite_pending_observation_retains_ticket_instead_of_claiming_closed(self):
        factory, job = await self.opened()
        self.runners[0].pending_count = True
        with self.assertRaisesRegex(m.JobError, "^cleanup_incomplete$"):
            _ = job.pending_count
        with self.assertRaisesRegex(m.JobError, "^cleanup_incomplete$"):
            await job.close()
        self.assertEqual(factory.active_count, 1)
        self.runners[0].pending_count = 0
        await job.close()
        self.assertEqual(factory.active_count, 0)

    async def test_completed_factory_and_cancelled_open_race_closes_unreceived_job(self):
        factory = self.factory()
        original = m._spawn
        opening = None

        def spawn(action):
            task = original(action)
            if action.cr_code.co_name == "_construct":
                task.add_done_callback(lambda _: opening.cancel())
            return task

        with patch.object(m, "_spawn", side_effect=spawn):
            opening = self.started(
                factory.open(work_id=self.work, owner_id=self.owner, request=self.request)
            )
            with self.assertRaises(asyncio.CancelledError):
                await opening
        ticket = next(iter(factory._tickets), None)
        if ticket is not None:
            self.assertIsNotNone(ticket.cleanup_observer)
            await asyncio.wait_for(asyncio.shield(ticket.cleanup_observer), 1)
        self.assertEqual(
            (factory.active_count, self.runners[0].calls, self.deliveries[0].calls), (0, 0, 0)
        )
        self.assertTrue(all(port.close_calls == 1 for port in self.clients.ports))
        other_work = str(uuid4())
        _, other = await self.opened(factory, other_work)
        await other.run_once(other_work, self.command(other_work))
        await other.close()

    async def test_malformed_nested_dto_error_is_finite_before_any_client_open(self):
        factory = self.factory()

        class Broken:
            def to_wire(self):
                raise RuntimeError("PRIVATE_NESTED_DTO")

        broken = replace(self.request)
        object.__setattr__(broken, "request", Broken())
        with self.assertRaisesRegex(m.JobError, "^invalid_input$"):
            await factory.open(work_id=self.work, owner_id=self.owner, request=broken)
        self.assertEqual((factory.active_count, self.clients.events), (0, []))

    async def test_large_integer_budgets_fail_before_clients_open_and_valid_work_progresses(self):
        for field in ("timeout_s", "cleanup_timeout_s"):
            with self.subTest(field=field), self.assertRaisesRegex(m.JobError, "^invalid_input$"):
                self.factory(**{field: 10**1000})
        self.assertEqual((self.clients.events, len(self.factories)), ([], 0))
        factory, job = await self.opened()
        self.assertEqual((factory.active_count, job.pending_count), (1, 0))
        value = await job.run_once(self.work, self.command())
        self.assertIs(job.observation.execution, value)
        self.assertEqual((self.runners[0].calls, self.deliveries[0].calls), (1, 1))
        await job.close()
        self.assertEqual(factory.active_count, 0)

    async def test_sync_factory_is_rejected_before_creating_any_unadopted_resource(self):
        class Sync(Clients):
            def open_execution(self):
                port = Port("execution", self)
                self.ports.append(port)
                return port

        clients = Sync(self.request)
        with self.assertRaisesRegex(m.JobError, "^invalid_input$"):
            self.factory(clients=clients)
        self.assertEqual((clients.events, clients.ports), ([], []))
        factory, job = await self.opened()
        await job.run_once(self.work, self.command())
        await job.close()
        self.assertEqual(factory.active_count, 0)

    async def test_factory_method_getters_and_marked_sync_functions_never_run(self):
        seen = []

        class Getter(Clients):
            @property
            def open_execution(self):
                seen.append("getter")
                raise RuntimeError("PRIVATE_GETTER")

        with self.assertRaisesRegex(m.JobError, "^invalid_input$"):
            self.factory(clients=Getter(self.request))
        clients = Clients(self.request)

        @inspect.markcoroutinefunction
        def marked():
            seen.append("sync-body")
            return Port("execution", clients)

        clients.open_execution = marked
        with self.assertRaisesRegex(m.JobError, "^invalid_input$"):
            self.factory(clients=clients)
        self.assertEqual(seen, [])

    async def test_constructor_snapshots_async_factory_callbacks_against_later_replacement(self):
        factory = self.factory()

        def replaced():
            raise AssertionError("PRIVATE_REPLACED_METHOD")

        self.clients.open_execution = replaced
        _, job = await self.opened(factory)
        await job.run_once(self.work, self.command())
        await job.close()
        self.assertEqual((factory.active_count, len(self.clients.ports)), (0, 4))

    async def test_changed_winning_original_is_rejected_before_runner_issue_or_delivery(self):
        factory, job = await self.opened()
        self.clients.request = changed_original(self.request)
        with self.assertRaisesRegex(m.JobError, "^invalid_stored_state$"):
            await job.run_once(self.work, self.command())
        self.assertEqual((self.runners[0].calls, self.deliveries[0].calls), (0, 0))
        self.assertIsNone(job.observation.execution)
        await job.close()
        self.clients.request = self.request
        other_work = str(uuid4())
        _, other = await self.opened(factory, other_work)
        await other.run_once(other_work, self.command(other_work))
        await other.close()
        self.assertEqual(factory.active_count, 0)

    async def test_changed_post_run_original_never_reaches_guarded_delivery(self):
        factory, job = await self.opened()
        self.runners[0].run_release = asyncio.Event()
        running = self.started(job.run_once(self.work, self.command()))
        await self.until(self.runners[0].run_entered)
        self.clients.request = changed_original(self.request)
        self.runners[0].run_release.set()
        with self.assertRaisesRegex(m.JobError, "^invalid_stored_state$"):
            await running
        self.assertEqual((self.runners[0].calls, self.deliveries[0].calls), (1, 0))
        self.assertIsNone(job.observation.execution)
        await job.close()
        self.clients.request = self.request
        other_work = str(uuid4())
        _, other = await self.opened(factory, other_work)
        await other.run_once(other_work, self.command(other_work))
        await other.close()
        self.assertEqual(factory.active_count, 0)

    async def test_public_preinspection_requires_full_work_payload_key_and_scope_join(self):
        factory = self.factory()
        for field in ("work", "scope", "key", "payload"):
            work = str(uuid4())
            _, job = await self.opened(factory, work)
            original = result_for(self.request, work).view
            record = original.execution.record
            if field == "work":
                record = replace(record, work_id=str(uuid4()))
            elif field == "scope":
                record = replace(record, scope=WorkScope("other", "account"))
            elif field == "key":
                record = replace(record, idempotency_key="different_key")
            else:
                changed = changed_original(self.request)
                record = replace(
                    record,
                    payload=WorkPayload(
                        "booking.evaluate_policy",
                        encode_channel_policy_request(changed),
                        changed.deadline_at_ms,
                    ),
                )
            altered = replace(
                original, execution=ExecutionObservation(record, None, None, 0, "accepted")
            )

            async def inspect_wrong(_, value=altered):
                return value

            self.runners[-1].inspect = inspect_wrong
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(m.JobError, "^invalid_stored_state$"),
            ):
                await job.run_once(work, self.command(work))
            self.assertEqual((self.runners[-1].calls, self.deliveries[-1].calls), (0, 0))
            await job.close()
        self.assertEqual(factory.active_count, 0)

    async def test_cancelled_preinspection_retains_actual_read_without_later_issue_or_delivery(
        self,
    ):
        factory, job = await self.opened()
        entered, release = asyncio.Event(), asyncio.Event()
        self.events.append(release)
        runner = self.runners[0]

        async def held_inspect(work):
            runner.pending_count = 1
            entered.set()
            try:
                await release.wait()
                return result_for(self.request, work).view
            finally:
                runner.pending_count = 0

        runner.inspect = held_inspect
        task = self.started(job.run_once(self.work, self.command()))
        await self.until(entered)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(
            (factory.active_count, job.pending_count, job.metrics()["runner_pending"]), (1, 1, 1)
        )
        with self.assertRaisesRegex(m.JobError, "^cleanup_incomplete$"):
            await job.close()
        release.set()
        await job.close()
        self.assertEqual((factory.active_count, runner.calls, self.deliveries[0].calls), (0, 0, 0))

    async def test_real_public_facades_construct_and_close_using_injected_owned_ports(self):
        self.runner_patch.stop()
        self.delivery_patch.stop()
        factory, job = await self.opened()
        self.assertIsInstance(job._runner, m.ChannelPolicyRunner)
        self.assertIsInstance(job._delivery, m.ChannelPolicyDeliveryClient)
        self.assertEqual(
            (job.pending_count, job.metrics()["runner_pending"], job.metrics()["delivery_pending"]),
            (0, 0, 0),
        )
        await job.close()
        self.assertTrue(all(port.close_calls == 1 for port in self.clients.ports))
        self.assertEqual((factory.active_count, self.cases.closed, self.clients.closed), (0, 0, 0))

    async def inspection_opened(self, factory=None, work=None):
        factory = self.factory() if factory is None else factory
        owner = await factory.open_inspection(
            work_id=self.work if work is None else work,
            owner_id=self.owner,
            request=self.request,
        )
        delivery = self.deliveries[-1]
        delivery.read_calls = 0
        delivery.read_value = DelegationDelivery(DeliverySnapshot(None, False, None), "missing")

        async def read(work_id):
            self.assertEqual(work_id, self.work if work is None else work)
            delivery.read_calls += 1
            delivery.pending_count = 1
            delivery.entered.set()
            try:
                if delivery.release is not None:
                    await delivery.release.wait()
                if delivery.error is not None:
                    raise delivery.error
                return delivery.read_value
            finally:
                delivery.pending_count = 0
                delivery.finished.set()

        delivery.inspect = read
        return factory, owner

    async def test_read_only_inspection_uses_same_owned_clients_without_action_methods(self):
        factory, owner = await self.inspection_opened()
        self.assertIsInstance(owner, m.ReadOnlyInspection)
        self.assertFalse(hasattr(owner, "run_once") or hasattr(owner, "deliver_once"))
        self.assertEqual((owner.pending_count, factory.active_count), (0, 1))
        self.assertEqual(len(self.clients.ports), 4)
        self.assertEqual(self.runners[0].owner_id, self.owner)
        self.assertEqual(self.clients.selected, [self.records])
        result = await owner.inspect_result()
        delivered = await owner.inspect_delivery()
        self.assertEqual(result.request, self.request)
        self.assertEqual(delivered.state, "missing")
        self.assertFalse(delivered.receiver_invoked)
        self.assertEqual((self.runners[0].calls, self.deliveries[0].calls), (0, 0))
        self.assertEqual(self.deliveries[0].read_calls, 1)
        await owner.close()
        self.assertEqual(factory.active_count, 0)
        self.assertTrue(all(port.close_calls == 1 for port in self.clients.ports))
        self.assertLess(
            self.clients.events.index("close:receiver"),
            self.clients.events.index("close:execution"),
        )
        self.assertEqual((self.cases.closed, self.clients.closed), (0, 0))
        for action in (owner.inspect_result, owner.inspect_delivery):
            with self.assertRaisesRegex(m.JobError, "^closed$"):
                await action()

    async def test_read_only_and_execution_share_two_actual_factory_tickets(self):
        factory, owner = await self.inspection_opened()
        _, job = await self.opened(factory, work=str(uuid4()))
        count = len(self.clients.ports)
        with self.assertRaisesRegex(m.JobError, "^capacity$"):
            await factory.open_inspection(
                work_id=str(uuid4()), owner_id=self.owner, request=self.request
            )
        self.assertEqual(len(self.clients.ports), count)
        await owner.close()
        _, fresh = await self.inspection_opened(factory, work=str(uuid4()))
        self.assertEqual(factory.active_count, 2)
        await fresh.close()
        await job.close()
        self.assertEqual((factory.active_count, sum(r.calls for r in self.runners)), (0, 0))

    async def test_execution_jobs_never_take_the_reserved_inspection_ticket(self):
        factory, first = await self.opened()
        _, second = await self.opened(factory, str(uuid4()))
        with self.assertRaisesRegex(m.JobError, "^capacity$"):
            await factory.open(work_id=str(uuid4()), owner_id=self.owner, request=self.request)
        _, owner = await self.inspection_opened(factory, work=str(uuid4()))
        self.assertEqual(factory.active_count, 3)
        with self.assertRaisesRegex(m.JobError, "^capacity$"):
            await factory.open_inspection(
                work_id=str(uuid4()), owner_id=self.owner, request=self.request
            )
        for job in (owner, first, second):
            await job.close()
        self.assertEqual(factory.active_count, 0)

    async def test_read_only_full_winning_request_checked_before_result_or_delivery(self):
        _, owner = await self.inspection_opened()
        runner, delivery = self.runners[0], self.deliveries[0]
        original = runner.inspect

        async def changed(work_id):
            return result_for(changed_original(self.request), work_id).view

        runner.inspect = changed
        for action in (owner.inspect_result, owner.inspect_delivery):
            with self.assertRaisesRegex(m.JobError, "^invalid_stored_state$"):
                await action()
        self.assertEqual((delivery.read_calls, runner.calls, delivery.calls), (0, 0, 0))
        runner.inspect = original
        self.assertEqual((await owner.inspect_result()).request, self.request)
        self.assertEqual((await owner.inspect_delivery()).state, "missing")
        await owner.close()

    async def test_read_only_timeout_retains_actual_read_and_close_until_settlement(self):
        factory = self.factory(timeout_s=0.02, cleanup_timeout_s=0.01)
        _, owner = await self.inspection_opened(factory)
        runner, delivery = self.runners[0], self.deliveries[0]
        release, finished = asyncio.Event(), asyncio.Event()
        self.events.append(release)
        original = runner.inspect
        calls = []

        async def held(work_id):
            calls.append(work_id)
            runner.pending_count = 1
            try:
                await release.wait()
                return await original(work_id)
            finally:
                runner.pending_count = 0
                finished.set()

        runner.inspect = held
        with self.assertRaisesRegex(m.JobError, "^deadline_exceeded$"):
            await owner.inspect_result()
        self.assertEqual((owner.pending_count, factory.active_count), (1, 1))
        for action in (owner.inspect_result, owner.inspect_delivery):
            with self.assertRaisesRegex(m.JobError, "^capacity$"):
                await action()
        with self.assertRaisesRegex(m.JobError, "^cleanup_incomplete$"):
            await owner.close()
        self.assertEqual((runner.close_calls, delivery.close_calls), (0, 0))
        release.set()
        await self.until(finished)
        await self.until(runner.executions.closed)
        await owner.close()
        self.assertEqual((len(calls), owner.pending_count, factory.active_count), (1, 0, 0))

    async def test_read_only_cancelled_delivery_waiter_retains_ticket_and_actual_read(self):
        factory, owner = await self.inspection_opened()
        delivery = self.deliveries[0]
        release = asyncio.Event()
        self.events.append(release)
        delivery.release = release
        task = self.started(owner.inspect_delivery())
        await self.until(delivery.entered)
        task.cancel()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual((owner.pending_count, factory.active_count), (1, 1))
        with self.assertRaisesRegex(m.JobError, "^capacity$"):
            await owner.inspect_result()
        with self.assertRaisesRegex(m.JobError, "^cleanup_incomplete$"):
            await owner.close()
        release.set()
        await self.until(delivery.finished)
        await owner.close()
        self.assertEqual((delivery.read_calls, delivery.calls, factory.active_count), (1, 0, 0))

    async def test_read_only_abandoned_pre_read_never_starts_delivery_inspection(self):
        _, owner = await self.inspection_opened()
        runner, delivery = self.runners[0], self.deliveries[0]
        entered, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
        self.events.append(release)
        original = runner.inspect

        async def held(work_id):
            entered.set()
            try:
                await release.wait()
                return await original(work_id)
            finally:
                finished.set()

        runner.inspect = held
        task = self.started(owner.inspect_delivery())
        await self.until(entered)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        release.set()
        await self.until(finished)
        await owner.close()
        self.assertEqual((delivery.read_calls, delivery.calls, runner.calls), (0, 0, 0))

    async def test_read_only_known_receipt_survives_failed_close_with_same_owned_ticket(self):
        from continuity_lab.delivery_api import DeliveryIntent, DeliveryReceipt

        factory, owner = await self.inspection_opened()
        delivery, runner = self.deliveries[0], self.runners[0]
        body = b'{"synthetic":"stored-observation"}'
        intent = DeliveryIntent(
            str(uuid4()),
            WorkScope(self.request.scope.tenant_id, self.request.scope.account_id),
            self.work,
            str(uuid4()),
            hashlib.sha256(body).hexdigest(),
            delivery.receiver.receiver_id,
            "recipient_demo",
            body,
            time.time_ns() // 1_000_000,
        )
        receipt = DeliveryReceipt(
            intent.delivery_id,
            str(uuid4()),
            intent.receiver_id,
            intent.recipient_id,
            intent.result_sha256,
            intent.prepared_at_ms,
        )
        delivery.read_value = DelegationDelivery(
            DeliverySnapshot(intent, True, receipt), "accepted"
        )
        observed = await owner.inspect_delivery()
        delivery.close_error = RuntimeError("PRIVATE_READ_CLOSE")
        with self.assertRaisesRegex(m.JobError, "^cleanup_incomplete$"):
            await owner.close()
        self.assertEqual((factory.active_count, runner.close_calls), (1, 0))
        self.assertEqual(observed.snapshot.receipt, receipt)
        self.assertEqual(observed.snapshot.intent.body, body)
        delivery.close_error = None
        await owner.close()
        self.assertEqual(factory.active_count, 0)
        self.assertEqual(observed.snapshot.receipt, receipt)
        self.assertEqual((runner.calls, delivery.calls), (0, 0))

    async def test_read_only_eager_reentry_reserves_actual_read_before_task_creation(self):
        _, owner = await self.inspection_opened()
        runner = self.runners[0]
        original = runner.inspect
        entered = []

        async def reentrant(work_id):
            with self.assertRaisesRegex(m.JobError, "^capacity$"):
                await owner.inspect_result()
            entered.append(work_id)
            return await original(work_id)

        runner.inspect = reentrant
        loop = asyncio.get_running_loop()
        previous = loop.get_task_factory()
        try:
            loop.set_task_factory(asyncio.eager_task_factory)
            self.assertEqual((await owner.inspect_result()).request, self.request)
        finally:
            loop.set_task_factory(previous)
        self.assertEqual(entered, [self.work])
        await owner.close()

    async def test_read_only_dependency_errors_are_finite_and_fresh_progress_remains(self):
        _, owner = await self.inspection_opened()
        runner = self.runners[0]
        original = runner.inspect

        class PrivateFailure(RuntimeError):
            @property
            def code(self):
                raise AssertionError("PRIVATE_CODE_GETTER")

        known = CompletionError("case_changed")
        known.args = ("PRIVATE_DEPENDENCY_BODY",)
        for failure, code in ((known, "case_changed"), (PrivateFailure("PRIVATE"), "unavailable")):

            async def failed(work_id, error=failure):
                raise error

            runner.inspect = failed
            with self.assertRaisesRegex(m.JobError, "^" + code + "$") as observed:
                await owner.inspect_result()
            self.assertIsNot(observed.exception, failure)
        runner.inspect = original
        self.assertEqual((await owner.inspect_result()).request, self.request)
        await owner.close()

    async def test_read_only_task_allocation_failure_closes_coroutine_without_losing_owner(self):
        factory, owner = await self.inspection_opened()
        for failure in (RuntimeError("PRIVATE_ALLOCATION"), asyncio.CancelledError()):
            actions = []

            def allocation(action, *, captured=actions, error=failure):
                captured.append(action)
                raise error

            with patch.object(m.asyncio, "create_task", side_effect=allocation):
                if isinstance(failure, asyncio.CancelledError):
                    with self.assertRaises(asyncio.CancelledError):
                        await owner.inspect_result()
                else:
                    with self.assertRaisesRegex(m.JobError, "^unavailable$"):
                        await owner.inspect_result()
            self.assertIsNone(actions[0].cr_frame)
            self.assertEqual((owner.pending_count, factory.active_count), (0, 1))
            self.assertEqual((await owner.inspect_result()).request, self.request)
        await owner.close()

    async def test_read_only_close_allocation_failure_keeps_resources_and_explicit_retry(self):
        factory, owner = await self.inspection_opened()
        actions = []

        def allocation(action):
            actions.append(action)
            raise RuntimeError("PRIVATE_CLOSE_ALLOCATION")

        with (
            patch.object(m.asyncio, "create_task", side_effect=allocation),
            self.assertRaisesRegex(m.JobError, "^cleanup_incomplete$"),
        ):
            await owner.close()
        self.assertIsNone(actions[0].cr_frame)
        self.assertEqual(factory.active_count, 1)
        self.assertTrue(all(port.close_calls == 0 for port in self.clients.ports))
        await owner.close()
        self.assertEqual(factory.active_count, 0)

    async def test_read_only_late_factory_return_after_cancel_is_adopted_and_closed(self):
        factory = self.factory(cleanup_timeout_s=0.01)
        release = asyncio.Event()
        self.events.append(release)
        self.clients.release["receiver"] = release
        task = self.started(
            factory.open_inspection(work_id=self.work, owner_id=self.owner, request=self.request)
        )
        await self.until(self.clients.entered["receiver"])
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(factory.active_count, 1)
        with self.assertRaisesRegex(m.JobError, "^cleanup_incomplete$"):
            await factory.close()
        release.set()
        await self.until(self.runners[0].executions.closed)
        await factory.close()
        self.assertEqual(factory.active_count, 0)
        self.assertTrue(all(port.close_calls == 1 for port in self.clients.ports))
        self.assertEqual(
            (self.runners[0].calls, self.deliveries[0].calls if self.deliveries else 0), (0, 0)
        )

    async def test_real_public_read_only_facades_construct_and_drain_without_issuing(self):
        self.runner_patch.stop()
        self.delivery_patch.stop()
        factory = self.factory()
        owner = await factory.open_inspection(
            work_id=self.work, owner_id=self.owner, request=self.request
        )
        self.assertIsInstance(owner._runner, m.ChannelPolicyRunner)
        self.assertIsInstance(owner._delivery, m.ChannelPolicyDeliveryClient)
        self.assertFalse(hasattr(owner, "run_once") or hasattr(owner, "deliver_once"))
        self.assertEqual(owner.pending_count, 0)
        await owner.close()
        self.assertEqual(factory.active_count, 0)
        self.assertTrue(all(port.close_calls == 1 for port in self.clients.ports))

    async def test_read_only_invalid_identity_is_rejected_before_any_client_open(self):
        factory = self.factory()
        for work, owner in (("invalid", self.owner), (self.work, "invalid")):
            with self.assertRaisesRegex(m.JobError, "^invalid_input$"):
                await factory.open_inspection(work_id=work, owner_id=owner, request=self.request)
        self.assertEqual((factory.active_count, self.clients.ports), (0, []))
        _, valid = await self.inspection_opened(factory)
        self.assertEqual((await valid.inspect_result()).request, self.request)
        await valid.close()

    async def test_read_only_delivery_metadata_scope_route_state_and_owned_copy_are_strict(self):
        from continuity_lab.delivery_api import DeliveryIntent

        _, owner = await self.inspection_opened()
        delivery = self.deliveries[0]
        body = b"stored synthetic observation"
        intent = DeliveryIntent(
            str(uuid4()),
            WorkScope(self.request.scope.tenant_id, self.request.scope.account_id),
            self.work,
            str(uuid4()),
            hashlib.sha256(body).hexdigest(),
            delivery.receiver.receiver_id,
            "recipient_demo",
            body,
            time.time_ns() // 1_000_000,
        )
        valid = DelegationDelivery(DeliverySnapshot(intent, False, None), "prepared")
        invalid = [replace(valid, receiver_invoked=True), replace(valid, state="accepted")]
        for changed in (
            replace(intent, work_id=str(uuid4())),
            replace(intent, scope=WorkScope("foreign", "account")),
            replace(intent, receiver_id=str(uuid4())),
            replace(intent, recipient_id="foreign"),
        ):
            invalid.append(DelegationDelivery(DeliverySnapshot(changed, False, None), "prepared"))
        bad_snapshot = DeliverySnapshot(intent, False, None)
        object.__setattr__(bad_snapshot, "possible", 1)
        invalid.append(DelegationDelivery(bad_snapshot, "unknown"))
        for value in invalid:
            with self.subTest(control=value.state):
                delivery.read_value = value
                with self.assertRaisesRegex(m.JobError, "^invalid_stored_state$"):
                    await owner.inspect_delivery()
        delivery.read_value = valid
        observed = await owner.inspect_delivery()
        self.assertEqual(observed, valid)
        self.assertIsNot(observed.snapshot, valid.snapshot)
        self.assertIsNot(observed.snapshot.intent, intent)
        self.assertIsNot(observed.snapshot.intent.scope, intent.scope)
        object.__setattr__(intent.scope, "tenant_id", "mutated_original")
        self.assertEqual(observed.snapshot.intent.scope.tenant_id, self.request.scope.tenant_id)
        self.assertEqual((self.runners[0].calls, delivery.calls), (0, 0))
        await owner.close()

    async def test_read_only_factory_stop_blocks_follow_on_and_new_read_before_child_close(self):
        factory, owner = await self.inspection_opened()
        runner, delivery = self.runners[0], self.deliveries[0]
        entered, release = asyncio.Event(), asyncio.Event()
        self.events.append(release)
        original = runner.inspect

        async def held(work_id):
            entered.set()
            await release.wait()
            return await original(work_id)

        runner.inspect = held
        reading = self.started(owner.inspect_delivery())
        await self.until(entered)

        def allocation(action):
            raise RuntimeError("PRIVATE_FACTORY_CLOSE_ALLOCATION")

        with (
            patch.object(m.asyncio, "create_task", side_effect=allocation),
            self.assertRaisesRegex(m.JobError, "^unavailable$"),
        ):
            await factory.close()
        self.assertFalse(owner._closing)
        with self.assertRaisesRegex(m.JobError, "^closed$"):
            await owner.inspect_result()
        release.set()
        with self.assertRaisesRegex(m.JobError, "^request_aborted$"):
            await reading
        self.assertEqual((delivery.read_calls, delivery.calls, runner.calls), (0, 0, 0))
        await factory.close()
        self.assertEqual(factory.active_count, 0)

    async def test_read_only_queued_cancellation_admits_no_read_then_fresh_read_progresses(self):
        factory, owner = await self.inspection_opened()
        runner = self.runners[0]
        original = runner.inspect
        calls = []

        async def observed(work_id):
            calls.append(work_id)
            return await original(work_id)

        runner.inspect = observed

        async def cancelled():
            current = asyncio.current_task()
            self.assertIsNotNone(current)
            current.cancel()
            await owner.inspect_result()

        task = self.started(cancelled())
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual((calls, owner.pending_count, factory.active_count), ([], 0, 1))
        self.assertEqual(owner.metrics()["stage_pending"], 0)
        self.assertEqual((await owner.inspect_result()).request, self.request)
        self.assertEqual(calls, [self.work])
        await owner.close()
        self.assertEqual(factory.active_count, 0)


if __name__ == "__main__":
    unittest.main()
