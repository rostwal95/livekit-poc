"""Offline public-port ownership tests; no PostgreSQL, provider or SDK runtime."""

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
from collections.abc import Awaitable, Callable
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import cast
from unittest.mock import patch
from uuid import uuid4

from continuity_lab.execution_api import ExecutionObservation
from continuity_lab.work_api import WorkPayload, WorkRecord, WorkScope
from delegation_reliability import (
    ChannelPolicyExecutionView,
    ChannelPolicyRequest,
    ChannelPolicyRun,
    ChannelPolicyView,
    DelegationRunError,
    channel_policy_key,
    encode_channel_policy_request,
    produce_channel_policy_request,
)
from delegation_reliability.contracts import Scope
from delegation_reliability.fixed_policy_contracts import produce_fixed_policy_request
from services.channel_policy_demo import executor as m
from services.channel_policy_demo.discovery import (
    DiscoveryItem,
    DiscoveryPage,
    DiscoveryScope,
    SourceBindingId,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / "contracts/delegation/fixed-policy-v2.json").read_bytes())


def encoded(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def make_frame(value: dict[str, object]) -> bytes:
    raw = encoded(value)
    return encoded(
        {
            "schemaVersion": 1,
            "canonicalPayload": raw.decode(),
            "payloadDigest": hashlib.sha256(raw).hexdigest(),
        }
    )


def data(
    count: int = 3, *, gap: bool = False
) -> tuple[m.ExecutorBinding, DiscoveryPage, dict[str, bytes | None], dict[str, ChannelPolicyView]]:
    binding = m.ExecutorBinding(
        str(uuid4()),
        Scope("tenant_demo", "account_demo"),
        "case_demo",
        "conversation_demo",
        str(uuid4()),
    )
    items = []
    frames = {}
    records = {}
    for index in range(count):
        receipt, operation, work = str(uuid4()), str(uuid4()), str(uuid4())
        source: SourceBindingId = "native" if index % 2 == 0 else "sms"
        submission = {
            "schemaVersion": 1,
            "kind": "investigation",
            "operationKey": operation,
            "scope": {"tenantId": binding.scope.tenant_id, "accountId": binding.scope.account_id},
            "caseId": binding.case_id,
            "caseRevision": "1",
            "conversationId": binding.conversation_id,
            "message": {
                "receiptId": receipt,
                "eventId": "event_" + str(index),
                "messageId": "message_" + str(index),
                "senderId": "sender_" + source,
                "body": "Original café 🧭 " + str(index),
            },
        }
        frame = make_frame(submission)
        pending = gap and index == 0
        items.append(
            DiscoveryItem(
                receipt,
                operation,
                str(index + 1),
                source,
                "pending" if pending else "dispatched",
                not pending,
                None if pending else work,
            )
        )
        frames[receipt] = None if pending else frame
        if pending:
            continue
        policy = copy.deepcopy(FIXTURE["producer_input"])
        policy["delegation_id"] = channel_policy_key(operation)
        policy["deadline_at_ms"] = time.time_ns() // 1000000 + 30000
        inner = produce_fixed_policy_request(policy)
        payload = encoded(submission)
        request = produce_channel_policy_request(
            {
                "schema_version": 1,
                "kind": "delegation.request",
                "capability": "booking.evaluate_policy",
                "input_schema_version": 3,
                "origin": {
                    "kind": "p2.prepared_dispatch.v1",
                    "profile_id": binding.profile_id,
                    "operation_key": operation,
                    "input_receipt_id": receipt,
                    "payload_sha256": hashlib.sha256(payload).hexdigest(),
                    "payload_byte_length": len(payload),
                },
                "request": inner.to_wire(),
            }
        )
        record = WorkRecord(
            work,
            WorkScope(binding.scope.tenant_id, binding.scope.account_id),
            channel_policy_key(operation),
            WorkPayload(
                "booking.evaluate_policy",
                encode_channel_policy_request(request),
                request.deadline_at_ms,
            ),
            time.time_ns() // 1000000,
            False,
        )
        records[work] = ChannelPolicyView(record, request)
    page = DiscoveryPage(
        binding.profile_id,
        DiscoveryScope(binding.scope.tenant_id, binding.scope.account_id),
        binding.case_id,
        binding.conversation_id,
        "2026-11-13T00:00:00.000Z",
        tuple(items),
        False,
        None,
    )
    return binding, page, frames, records


class Discovery:
    def __init__(self, page: DiscoveryPage) -> None:
        self.page, self.calls = page, 0
        self.release: asyncio.Event | None = None
        self.entered = asyncio.Event()
        self.error: Exception | None = None

    async def read(self) -> DiscoveryPage:
        self.calls += 1
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        if self.error is not None:
            raise self.error
        return self.page


class Prepared:
    def __init__(self, frames: dict[str, bytes | None]) -> None:
        self.frames = frames
        self.calls: list[tuple[SourceBindingId, str]] = []
        self.hold_receipt: str | None = None
        self.release: asyncio.Event | None = None
        self.entered = asyncio.Event()

    async def read(self, *, source_binding_id: SourceBindingId, receipt_id: str) -> bytes | None:
        self.calls.append((source_binding_id, receipt_id))
        if receipt_id == self.hold_receipt:
            self.entered.set()
            assert self.release is not None
            await self.release.wait()
        return self.frames[receipt_id]


class Stored:
    def __init__(self, records: dict[str, ChannelPolicyView]) -> None:
        self.records, self.calls = records, []

    async def get(self, work_id: str) -> ChannelPolicyView:
        self.calls.append(work_id)
        return self.records[work_id]


class Runner:
    def __init__(self, view: ChannelPolicyView) -> None:
        self.view = view
        self.calls: list[tuple[str, str]] = []
        self.closed = self.close_calls = self.pending_count = 0
        self.run_entered, self.close_entered = asyncio.Event(), asyncio.Event()
        self.run_release: asyncio.Event | None = None
        self.close_release: asyncio.Event | None = None
        self.run_error: Exception | None = None
        self.fail_closes = 0
        self.late_io: asyncio.Event | None = None
        self.actual_task: asyncio.Task[None] | None = None
        self.alter_result = False

    async def run_once(self, work_id: str, command_id: str) -> ChannelPolicyRun:
        self.calls.append((work_id, command_id))
        self.run_entered.set()
        if self.late_io is not None:
            self.pending_count = 1

            async def actual() -> None:
                assert self.late_io is not None
                try:
                    await self.late_io.wait()
                finally:
                    self.pending_count = 0

            self.actual_task = asyncio.create_task(actual())
            raise DelegationRunError("deadline_exceeded")
        self.pending_count += 1
        try:
            if self.run_release is not None:
                await self.run_release.wait()
            if self.run_error is not None:
                raise self.run_error
            observation = ExecutionObservation(self.view.record, None, None, 0, "accepted")
            value = ChannelPolicyExecutionView(observation, self.view.request, None, "missing")
            result = ChannelPolicyRun(value, False)
            return cast(ChannelPolicyRun, object()) if self.alter_result else result
        finally:
            self.pending_count -= 1

    async def close(self) -> None:
        self.close_calls += 1
        self.close_entered.set()
        if self.close_release is not None:
            await self.close_release.wait()
        if self.pending_count or self.fail_closes:
            self.fail_closes = max(0, self.fail_closes - 1)
            raise DelegationRunError("cleanup_incomplete")
        self.closed += 1


class RecoverableReturn:
    """Malformed fresh public-port return whose resource remains observable."""

    def __init__(self, view: ChannelPolicyView, failure: str) -> None:
        self.inner = Runner(view)
        self.failure = failure

    @property
    def pending_count(self) -> int:
        if self.failure == "pending":
            raise RuntimeError("PRIVATE_PENDING_SENTINEL")
        return self.inner.pending_count

    @property
    def close(self) -> Callable[[], Awaitable[None]]:
        if self.failure == "close":
            raise AttributeError("PRIVATE_CLOSE_SENTINEL")
        return self.inner.close

    async def run_once(self, work_id: str, command_id: str) -> ChannelPolicyRun:
        return await self.inner.run_once(work_id, command_id)


class Factory:
    def __init__(self, records: dict[str, ChannelPolicyView]) -> None:
        self.runners = {key: Runner(value) for key, value in records.items()}
        self.calls: list[tuple[str, str, ChannelPolicyRequest]] = []
        self.release: asyncio.Event | None = None
        self.error: Exception | None = None
        self.entered = asyncio.Event()
        self.returned: m.JobRunnerPort | None = None
        self.cancel_open = False

    async def open(
        self, *, work_id: str, owner_id: str, request: ChannelPolicyRequest
    ) -> m.JobRunnerPort:
        self.calls.append((work_id, owner_id, request))
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        if self.error is not None:
            raise self.error
        if self.cancel_open:
            raise asyncio.CancelledError("PRIVATE_FACTORY_CANCELLED")
        if self.returned is not None:
            return self.returned
        if self.runners[work_id].closed:
            self.runners[work_id] = Runner(self.runners[work_id].view)
        return self.runners[work_id]


async def until(predicate: object) -> None:
    assert callable(predicate)
    async with asyncio.timeout(1):
        while not predicate():
            await asyncio.sleep(0)


class ExecutorTests(unittest.IsolatedAsyncioTestCase):
    def configure(
        self, count: int = 3, *, gap: bool = False, **options: float
    ) -> m.ChannelPolicyExecutor:
        self.binding, self.page, self.frames, self.records = data(count, gap=gap)
        self.discovery, self.prepared, self.stored, self.factory = (
            Discovery(self.page),
            Prepared(self.frames),
            Stored(self.records),
            Factory(self.records),
        )
        discovery: m.DiscoveryPort = self.discovery
        prepared: m.PreparedReadPort = self.prepared
        stored: m.StoredWorkPort = self.stored
        factory: m.RunnerFactory = self.factory
        options.setdefault("rerun_delay_s", 0)
        core = m.ChannelPolicyExecutor(
            binding=self.binding,
            discovery=discovery,
            prepared=prepared,
            stored=stored,
            runners=factory,
            **options,
        )
        self.core = core
        return core

    async def asyncTearDown(self) -> None:
        if hasattr(self, "core"):
            for event in (self.discovery.release, self.prepared.release, self.factory.release):
                if event is not None:
                    event.set()
            for runner in self.factory.runners.values():
                runner.fail_closes = 0
                for event in (runner.run_release, runner.close_release, runner.late_io):
                    if event is not None:
                        event.set()
                if runner.actual_task is not None:
                    await runner.actual_task
            for _ in range(3):
                try:
                    await self.core.close()
                    break
                except m.ExecutorError:
                    await asyncio.sleep(0)
            self.assertEqual(self.core.pending_count, 0)

    async def test_pending_gap_still_examines_later_work_and_uses_configured_source_ports(
        self,
    ) -> None:
        core = self.configure(gap=True)
        observed = await core.scan_once()
        self.assertEqual(
            (observed.discovered, observed.unprepared, observed.eligible, observed.started),
            (3, 1, 2, 2),
        )
        await core.close()
        self.assertEqual(
            self.prepared.calls,
            [(item.source_binding_id, item.receipt_id) for item in self.page.items],
        )
        self.assertEqual(len(self.factory.calls), 2)
        for work_id, owner_id, request in self.factory.calls:
            self.assertEqual(owner_id, self.binding.owner_id)
            self.assertEqual(request, self.records[work_id].request)
            self.assertEqual(
                self.factory.runners[work_id].calls, [(work_id, "cp45_" + work_id.replace("-", ""))]
            )
            self.assertEqual(self.factory.runners[work_id].closed, 1)
        with self.assertRaises(FrozenInstanceError):
            observed.started = 99
        with self.assertRaises(TypeError):
            core.metrics()["active_jobs"] = 99

    async def test_two_actual_factories_reserve_capacity_and_third_has_later_progress(self) -> None:
        core = self.configure()
        self.factory.release = asyncio.Event()
        first = await core.scan_once()
        await until(lambda: len(self.factory.calls) == 2)
        self.assertEqual((first.started, core.metrics()["active_jobs"]), (2, 2))
        self.assertEqual((await core.scan_once()).started, 0)
        self.assertEqual(len(self.factory.calls), 2)
        self.factory.release.set()
        await until(
            lambda: all(runner.closed for runner in list(self.factory.runners.values())[:2])
        )
        third_work = self.page.items[2].external_receipt_id
        before = len(self.prepared.calls)
        self.assertEqual((await core.scan_once()).started, 2)
        await core.close()
        self.assertEqual(len(self.factory.calls), 4)
        self.assertEqual(self.factory.calls[2][0], third_work)
        self.assertEqual(
            {receipt for _, receipt in self.prepared.calls[before:]},
            {item.receipt_id for item in self.page.items},
        )
        self.assertTrue(
            all(
                call[0] == item.source_binding_id
                for call, item in zip(self.prepared.calls[:3], self.page.items, strict=True)
            )
        )

    async def test_full_sixteen_input_rescans_make_round_robin_progress_without_acknowledging_gaps(
        self,
    ) -> None:
        core = self.configure(16)
        for turn in range(8):
            before = len(self.prepared.calls)
            observed = await core.scan_once()
            self.assertEqual(
                (observed.discovered, observed.eligible, observed.started), (16, 16, 2)
            )
            reads = self.prepared.calls[before:]
            self.assertEqual(
                (len(reads), {receipt for _, receipt in reads}),
                (16, {item.receipt_id for item in self.page.items}),
            )
            expected = [
                item.external_receipt_id for item in self.page.items[turn * 2 : turn * 2 + 2]
            ]
            await until(lambda turn=turn: len(self.factory.calls) == (turn + 1) * 2)
            self.assertEqual([call[0] for call in self.factory.calls[-2:]], expected)
            await until(
                lambda expected=expected: all(
                    self.factory.runners[work].closed == 1 for work in expected
                )
            )
        self.assertEqual(len({call[0] for call in self.factory.calls}), 16)
        self.assertEqual((await core.scan_once()).started, 2)
        await core.close()
        self.assertEqual(
            [call[0] for call in self.factory.calls[-2:]],
            [item.external_receipt_id for item in self.page.items[:2]],
        )
        self.assertEqual(len(self.prepared.calls), 16 * 9)

    async def test_both_lifetime_slots_remain_held_in_factory_run_and_close_stages(self) -> None:
        for stage in ("factory", "run", "close"):
            with self.subTest(stage=stage):
                core = self.configure()
                gate = asyncio.Event()
                first_two = list(self.factory.runners.values())[:2]
                if stage == "factory":
                    self.factory.release = gate
                else:
                    for runner in first_two:
                        if stage == "run":
                            runner.run_release = gate
                        else:
                            runner.close_release = gate
                self.assertEqual((await core.scan_once()).started, 2)
                if stage == "factory":
                    await until(lambda: len(self.factory.calls) == 2)
                else:
                    await asyncio.gather(
                        *(
                            runner.run_entered.wait()
                            if stage == "run"
                            else runner.close_entered.wait()
                            for runner in first_two
                        )
                    )
                self.assertEqual((await core.scan_once()).started, 0)
                self.assertEqual((len(self.factory.calls), core.metrics()["active_jobs"]), (2, 2))
                gate.set()
                await core.close()
                self.assertEqual((core.pending_count, len(self.factory.calls)), (0, 2))

    async def test_factory_cannot_transfer_the_same_runner_to_two_live_jobs(self) -> None:
        core = self.configure(2)
        first, second = list(self.factory.runners)
        shared = self.factory.runners[first]
        shared.run_release = asyncio.Event()
        self.factory.runners[second] = shared
        await core.scan_once()
        await shared.run_entered.wait()
        await until(lambda: core.metrics()["jobs_failed"] == 1)
        self.assertEqual((len(shared.calls), shared.close_calls), (1, 0))
        shared.run_release.set()
        await core.close()
        self.assertEqual((shared.closed, core.pending_count), (1, 0))

    async def test_repeated_scan_reuses_owner_command_without_terminal_memory_ledger(self) -> None:
        core = self.configure(1)
        await core.scan_once()
        work = next(iter(self.records))
        first = self.factory.runners[work]
        await until(lambda: first.closed == 1)
        self.factory.runners[work] = Runner(self.records[work])
        await core.scan_once()
        await core.close()
        self.assertEqual(len(self.factory.calls), 2)
        self.assertEqual(
            first.calls + self.factory.runners[work].calls,
            [(work, "cp45_" + work.replace("-", ""))] * 2,
        )
        self.assertEqual({call[1] for call in self.factory.calls}, {self.binding.owner_id})

    async def test_rerun_of_the_same_work_is_paced_while_every_scan_still_rereads(self) -> None:
        core = self.configure(1, rerun_delay_s=0.2, rerun_cap_s=0.4)
        work = next(iter(self.records))
        self.assertEqual((await core.scan_once()).started, 1)
        await until(lambda: self.factory.runners[work].closed == 1)
        reads = len(self.stored.calls)
        paced = await core.scan_once()
        self.assertEqual((paced.eligible, paced.started, paced.active), (1, 0, 0))
        self.assertEqual(len(self.stored.calls), reads + 1)
        self.assertEqual(core.metrics()["jobs_paced"], 1)
        await asyncio.sleep(0.35)
        self.assertEqual((await core.scan_once()).started, 1)
        await until(lambda: self.factory.runners[work].closed == 1)
        self.assertEqual((await core.scan_once()).started, 0)
        await asyncio.sleep(0.2)
        self.assertEqual((await core.scan_once()).started, 0)
        await asyncio.sleep(0.35)
        self.assertEqual((await core.scan_once()).started, 1)
        command = "cp45_" + work.replace("-", "")
        self.assertEqual({call[0] for call in self.factory.calls}, {work})
        self.assertEqual(len(self.factory.calls), 3)
        await until(lambda: self.factory.runners[work].closed == 1)
        self.assertEqual(self.factory.runners[work].calls, [(work, command)])

    async def test_pacing_never_delays_work_this_process_has_not_started(self) -> None:
        core = self.configure(3, rerun_delay_s=30)

        def settled() -> bool:
            return all(self.factory.runners[work].closed for work, *_ in self.factory.calls)

        first = await core.scan_once()
        self.assertEqual((first.eligible, first.started), (3, 2))
        await until(settled)
        second = await core.scan_once()
        self.assertEqual((second.eligible, second.started), (3, 1))
        self.assertEqual(len({call[0] for call in self.factory.calls}), 3)
        await until(settled)
        self.assertEqual((await core.scan_once()).started, 0)
        self.assertEqual(core.metrics()["jobs_paced"], 2 + 3)

    async def test_aborted_scan_retains_two_late_factories_and_does_not_admit_later_item(
        self,
    ) -> None:
        core = self.configure(cleanup_timeout_s=0.01)
        self.factory.release, self.prepared.release = asyncio.Event(), asyncio.Event()
        self.prepared.hold_receipt = self.page.items[2].receipt_id
        waiter = asyncio.create_task(core.scan_once())
        await self.prepared.entered.wait()
        await until(lambda: len(self.factory.calls) == 2)
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiter
        with self.assertRaisesRegex(m.ExecutorError, "^cleanup_incomplete$"):
            await core.close()
        self.assertEqual((core.metrics()["active_jobs"], len(self.factory.calls)), (2, 2))
        self.prepared.release.set()
        self.factory.release.set()
        await core.close()
        self.assertEqual(len(self.factory.calls), 2)
        self.assertEqual(sum(len(runner.calls) for runner in self.factory.runners.values()), 2)

    async def test_scan_timeout_retains_actual_read_and_useful_retry_after_settlement(self) -> None:
        core = self.configure(1, timeout_s=0.01)
        self.discovery.release = asyncio.Event()
        with self.assertRaisesRegex(m.ExecutorError, "^deadline_exceeded$"):
            await core.scan_once()
        self.assertEqual(core.metrics()["active_scans"], 1)
        with self.assertRaisesRegex(m.ExecutorError, "^capacity$"):
            await core.scan_once()
        self.discovery.release.set()
        await until(lambda: core.metrics()["active_scans"] == 0)
        self.assertEqual(len(self.factory.calls), 0)
        self.assertEqual((await core.scan_once()).started, 1)
        await core.close()

    async def test_close_retains_actual_run_and_bounded_observer_then_retries(self) -> None:
        core = self.configure(1, cleanup_timeout_s=0.01)
        runner = next(iter(self.factory.runners.values()))
        runner.run_release = asyncio.Event()
        await core.scan_once()
        await runner.run_entered.wait()
        with self.assertRaisesRegex(m.ExecutorError, "^cleanup_incomplete$"):
            await core.close()
        self.assertEqual(
            (core.metrics()["active_jobs"], runner.pending_count, runner.close_calls), (1, 1, 0)
        )
        with self.assertRaisesRegex(m.ExecutorError, "^closed$"):
            await core.scan_once()
        runner.run_release.set()
        await core.close()
        self.assertEqual((runner.closed, len(runner.calls)), (1, 1))

    async def test_runner_waiter_timeout_keeps_late_actual_io_and_close_failure_slot(self) -> None:
        core = self.configure(1)
        runner = next(iter(self.factory.runners.values()))
        runner.late_io = asyncio.Event()
        await core.scan_once()
        await runner.close_entered.wait()
        self.assertEqual((runner.pending_count, core.metrics()["active_jobs"]), (1, 1))
        self.assertEqual((await core.scan_once()).started, 0)
        with self.assertRaisesRegex(m.ExecutorError, "^cleanup_incomplete$"):
            await core.close()
        self.assertEqual(len(runner.calls), 1)
        runner.late_io.set()
        assert runner.actual_task is not None
        await runner.actual_task
        await core.close()
        self.assertEqual((core.pending_count, runner.closed), (0, 1))

    async def test_abandoned_close_observer_keeps_actual_close_and_single_call(self) -> None:
        core = self.configure(1)
        runner = next(iter(self.factory.runners.values()))
        runner.close_release = asyncio.Event()
        await core.scan_once()
        await runner.close_entered.wait()
        waiter = asyncio.create_task(core.close())
        await asyncio.sleep(0)
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiter
        self.assertEqual((core.metrics()["active_jobs"], runner.close_calls), (1, 1))
        runner.close_release.set()
        await core.close()
        self.assertEqual((runner.close_calls, runner.closed), (1, 1))

    async def test_failed_close_is_retained_and_retry_closes_without_resubmit(self) -> None:
        core = self.configure(1)
        runner = next(iter(self.factory.runners.values()))
        runner.fail_closes = 2
        await core.scan_once()
        await runner.close_entered.wait()
        with self.assertRaisesRegex(m.ExecutorError, "^cleanup_incomplete$"):
            await core.close()
        self.assertEqual(core.metrics()["active_jobs"], 1)
        await core.close()
        self.assertEqual((runner.close_calls, len(runner.calls)), (3, 1))

    async def test_factory_failures_never_close_borrowed_readers_and_fresh_retry_is_useful(
        self,
    ) -> None:
        core = self.configure(1)
        self.factory.error = RuntimeError("PRIVATE_FACTORY_SENTINEL")
        await core.scan_once()
        await until(lambda: core.metrics()["jobs_failed"] == 1)
        self.assertEqual(sum(runner.close_calls for runner in self.factory.runners.values()), 0)
        self.factory.error = None
        await core.scan_once()
        await core.close()
        self.assertEqual(core.metrics()["jobs_succeeded"], 1)
        self.assertFalse(
            any(hasattr(port, "close") for port in (self.discovery, self.prepared, self.stored))
        )

    async def test_borrowed_reader_or_factory_return_is_rejected_without_closing_that_owner(
        self,
    ) -> None:
        for name in ("discovery", "prepared", "stored", "factory"):
            with self.subTest(name=name):
                core = self.configure(1)
                self.factory.returned = cast(m.JobRunnerPort, getattr(self, name))
                await core.scan_once()
                await until(lambda core=core: core.metrics()["jobs_failed"] == 1)
                await core.close()
                self.assertEqual((core.pending_count, len(self.factory.calls)), (0, 1))
                self.assertEqual(
                    sum(runner.close_calls for runner in self.factory.runners.values()), 0
                )

    async def test_fresh_factory_return_with_actual_io_is_quarantined_until_real_drain(
        self,
    ) -> None:
        core = self.configure(1)
        runner = next(iter(self.factory.runners.values()))
        release = asyncio.Event()
        runner.pending_count = 1

        async def actual() -> None:
            try:
                await release.wait()
            finally:
                runner.pending_count = 0

        runner.actual_task = asyncio.create_task(actual())
        await core.scan_once()
        await runner.close_entered.wait()
        self.assertEqual(
            (core.metrics()["active_jobs"], runner.pending_count, runner.calls), (1, 1, [])
        )
        self.assertEqual((await core.scan_once()).started, 0)
        with self.assertRaisesRegex(m.ExecutorError, "^cleanup_incomplete$"):
            await core.close()
        self.assertEqual((len(self.factory.calls), core.metrics()["active_jobs"]), (1, 1))
        release.set()
        await runner.actual_task
        await core.close()
        self.assertEqual((runner.closed, runner.calls, core.pending_count), (1, [], 0))

    async def test_fresh_malformed_close_or_pending_observation_retains_slot_and_useful_retry(
        self,
    ) -> None:
        for failure in ("close", "pending"):
            with self.subTest(failure=failure):
                core = self.configure(1)
                returned = RecoverableReturn(next(iter(self.records.values())), failure)
                self.factory.returned = cast(m.JobRunnerPort, returned)
                await core.scan_once()
                await until(lambda core=core: core.metrics()["cleanup_incomplete"] >= 1)
                with self.assertRaisesRegex(m.ExecutorError, "^cleanup_incomplete$"):
                    await core.close()
                self.assertEqual(
                    (len(self.factory.calls), returned.inner.calls, core.metrics()["active_jobs"]),
                    (1, [], 1),
                )
                returned.failure = "repaired"
                await core.close()
                self.assertGreaterEqual(returned.inner.closed, 1)
                self.assertEqual(
                    (core.pending_count, len(self.factory.calls), returned.inner.calls), (0, 1, [])
                )

    async def test_telemetry_exception_cannot_change_scan_run_or_cleanup(self) -> None:
        core = self.configure(1)
        with patch.object(m.LOGGER, "info", side_effect=RuntimeError("PRIVATE_LOG_SENTINEL")):
            self.assertEqual((await core.scan_once()).started, 1)
            await core.close()
        self.assertEqual(core.metrics()["jobs_succeeded"], 1)
        self.assertGreaterEqual(core.metrics()["telemetry_failed"], 2)

    async def test_safe_dependency_error_and_single_fixed_event(self) -> None:
        core = self.configure(1)
        self.discovery.error = RuntimeError("PRIVATE_DEPENDENCY_SENTINEL")
        with (
            self.assertLogs(m.LOGGER, level="INFO") as logs,
            self.assertRaisesRegex(m.ExecutorError, "^unavailable$") as raised,
        ):
            await core.scan_once()
        self.assertNotIn("PRIVATE", repr(raised.exception))
        self.assertEqual(len(logs.records), 1)
        self.assertEqual(
            (logs.records[0].msg, logs.records[0].operation, logs.records[0].code),
            ("channel_policy_executor", "scan", "unavailable"),
        )
        self.discovery.error = None
        await core.scan_once()
        await core.close()

    async def test_wrong_loop_fails_before_closing_state_and_original_loop_stays_useful(
        self,
    ) -> None:
        core = self.configure(1)
        self.discovery.page = replace(self.page, items=())
        await core.scan_once()

        def foreign() -> str:
            try:
                asyncio.run(core.close())
            except m.ExecutorError as error:
                return error.code
            return "unexpected"

        self.assertEqual(await asyncio.to_thread(foreign), "invalid_input")
        self.assertEqual(core.metrics()["closing"], 0)
        self.discovery.page = self.page
        await core.scan_once()
        await core.close()

    async def test_task_allocation_failures_are_safe_close_coroutines_and_allow_retry(self) -> None:
        core = self.configure(1)
        with warnings.catch_warnings(record=True) as observed:
            warnings.simplefilter("always", RuntimeWarning)
            with (
                patch.object(
                    asyncio, "create_task", side_effect=RuntimeError("PRIVATE_TASK_SENTINEL")
                ),
                self.assertRaisesRegex(m.ExecutorError, "^unavailable$"),
            ):
                await core.scan_once()
            self.assertEqual(core.pending_count, 0)
            await core.scan_once()
            await until(lambda: next(iter(self.factory.runners.values())).closed == 1)
            with (
                patch.object(
                    asyncio, "create_task", side_effect=RuntimeError("PRIVATE_TASK_SENTINEL")
                ),
                self.assertRaisesRegex(m.ExecutorError, "^cleanup_incomplete$"),
            ):
                await core.close()
            await core.close()
            gc.collect()
        self.assertFalse(
            [warning for warning in observed if issubclass(warning.category, RuntimeWarning)]
        )

    async def test_job_task_allocation_failure_rolls_back_only_unstarted_slot_then_recovers(
        self,
    ) -> None:
        core = self.configure(1)
        real_create = asyncio.create_task
        allocations = 0

        def allocate(action):
            nonlocal allocations
            allocations += 1
            if allocations == 2:
                raise RuntimeError("PRIVATE_JOB_ALLOCATION")
            return real_create(action)

        with warnings.catch_warnings(record=True) as observed:
            warnings.simplefilter("always", RuntimeWarning)
            with (
                patch.object(asyncio, "create_task", side_effect=allocate),
                self.assertRaisesRegex(m.ExecutorError, "^unavailable$"),
            ):
                await core.scan_once()
            self.assertEqual((core.pending_count, self.factory.calls), (0, []))
            self.assertEqual((await core.scan_once()).started, 1)
            await core.close()
            gc.collect()
        self.assertFalse(
            [warning for warning in observed if issubclass(warning.category, RuntimeWarning)]
        )

    async def test_task_creation_cancellation_closes_scan_job_and_close_coroutines_and_recovers(
        self,
    ) -> None:
        for stage in ("scan", "job", "close"):
            with self.subTest(stage=stage):
                core = self.configure(1)
                if stage == "close":
                    await core.scan_once()
                    await until(lambda: next(iter(self.factory.runners.values())).closed == 1)
                real_create = asyncio.create_task
                allocations = 0

                def allocate(action, stage=stage, real_create=real_create):
                    nonlocal allocations
                    allocations += 1
                    if stage != "job" or allocations == 2:
                        raise asyncio.CancelledError("PRIVATE_ALLOCATION_CANCELLED")
                    return real_create(action)

                with warnings.catch_warnings(record=True) as observed:
                    warnings.simplefilter("always", RuntimeWarning)
                    with (
                        patch.object(asyncio, "create_task", side_effect=allocate),
                        self.assertRaises(asyncio.CancelledError),
                    ):
                        if stage == "close":
                            await core.close()
                        else:
                            await core.scan_once()
                    if stage != "close":
                        self.assertEqual((core.pending_count, self.factory.calls), (0, []))
                        self.assertEqual((await core.scan_once()).started, 1)
                    await core.close()
                    gc.collect()
                self.assertFalse(
                    [
                        warning
                        for warning in observed
                        if issubclass(warning.category, RuntimeWarning)
                    ]
                )
                self.assertEqual(core.pending_count, 0)
                self.assertEqual(
                    sum(len(runner.calls) for runner in self.factory.runners.values()), 1
                )

    async def test_other_task_allocation_control_flow_propagates_with_closed_coroutine(
        self,
    ) -> None:
        async def action() -> None:
            raise AssertionError("unstarted action")

        for failure in (KeyboardInterrupt(), SystemExit(), BaseException()):
            pending = action()
            with (
                patch.object(asyncio, "create_task", side_effect=failure),
                self.assertRaises(type(failure)) as raised,
            ):
                m._spawn(pending)
            self.assertIs(raised.exception, failure)
            self.assertEqual(inspect.getcoroutinestate(pending), inspect.CORO_CLOSED)
        core = self.configure(1)
        await core.scan_once()
        await core.close()

    async def test_cancelled_factory_releases_only_empty_owner_and_next_scan_is_useful(
        self,
    ) -> None:
        core = self.configure(1)
        self.factory.cancel_open = True
        self.assertEqual((await core.scan_once()).started, 1)
        await self.factory.entered.wait()
        self.assertEqual(sum(len(runner.calls) for runner in self.factory.runners.values()), 0)
        self.assertEqual(sum(runner.close_calls for runner in self.factory.runners.values()), 0)
        self.factory.cancel_open = False
        self.assertEqual((await core.scan_once()).started, 1)
        await core.close()
        self.assertEqual((core.pending_count, len(self.factory.calls)), (0, 2))
        self.assertEqual(core.metrics()["jobs_succeeded"], 1)
        self.assertEqual(sum(len(runner.calls) for runner in self.factory.runners.values()), 1)

    async def test_domain_failure_copies_static_finite_code_without_dependency_getters_or_args(
        self,
    ) -> None:
        getter_hits = 0

        class HostileCode(m.ExecutorError):
            def __init__(self) -> None:
                RuntimeError.__init__(self, "PRIVATE_DEPENDENCY_ARGS")

            @property
            def code(self) -> m.ExecutorCode:
                nonlocal getter_hits
                getter_hits += 1
                raise RuntimeError("PRIVATE_CODE_GETTER")

        errors: list[tuple[m.ExecutorError, str]] = []
        for value in ("capacity", "PRIVATE_CODE", None, True, [], {"private": "PRIVATE_VALUE"}):
            error = m.ExecutorError("capacity")
            object.__setattr__(error, "code", value)
            error.args = ("PRIVATE_DEPENDENCY_ARGS",)
            errors.append((error, "capacity" if value == "capacity" else "unavailable"))
        errors.append((HostileCode(), "unavailable"))
        for error, expected in errors:
            with self.subTest(expected=expected):
                core = self.configure(1)
                self.discovery.error = error
                with (
                    self.assertLogs(m.LOGGER, level="INFO") as logs,
                    self.assertRaises(m.ExecutorError) as raised,
                ):
                    await core.scan_once()
                self.assertIsNot(raised.exception, error)
                self.assertIs(type(raised.exception), m.ExecutorError)
                self.assertEqual(
                    (raised.exception.code, raised.exception.args), (expected, (expected,))
                )
                events = [(record.msg, record.operation, record.code) for record in logs.records]
                self.assertEqual(events, [("channel_policy_executor", "scan", expected)])
                self.assertNotIn("PRIVATE", repr((events, raised.exception.args)))
                self.discovery.error = None
                self.assertEqual((await core.scan_once()).started, 1)
                await core.close()
                self.assertEqual((core.pending_count, core.metrics()["jobs_succeeded"]), (0, 1))
        self.assertEqual(getter_hits, 0)

    async def test_overflow_and_foreign_route_fail_before_prepared_reads_or_factories(self) -> None:
        core = self.configure(16)
        self.discovery.page = replace(self.page, overflow=True, next_cursor="16")
        with self.assertRaisesRegex(m.ExecutorError, "^overflow$"):
            await core.scan_once()
        for field, value in (
            ("profile_id", str(uuid4())),
            ("case_id", "foreign_case"),
            ("conversation_id", "foreign_conversation"),
            ("scope", DiscoveryScope("foreign_tenant", "foreign_account")),
        ):
            self.discovery.page = replace(self.page, **{field: value})
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(m.ExecutorError, "^unauthorized$"),
            ):
                await core.scan_once()
        self.assertEqual((self.prepared.calls, self.factory.calls), ([], []))
        self.discovery.page = replace(self.page, items=())
        await core.scan_once()
        await core.close()

    async def test_missing_dispatched_plan_and_prepared_identity_conflict_fail_closed(self) -> None:
        core = self.configure(1)
        receipt = self.page.items[0].receipt_id
        original = self.frames[receipt]
        self.frames[receipt] = None
        with self.assertRaisesRegex(m.ExecutorError, "^invalid_stored_state$"):
            await core.scan_once()
        assert original is not None
        payload = json.loads(json.loads(original)["canonicalPayload"])
        payload["operationKey"] = str(uuid4())
        self.frames[receipt] = make_frame(payload)
        with self.assertRaisesRegex(m.ExecutorError, "^identity_conflict$"):
            await core.scan_once()
        self.assertEqual(self.factory.calls, [])
        self.frames[receipt] = original
        await core.scan_once()
        await core.close()

    async def test_full_origin_fields_and_case_revision_are_bound_to_original_prepared_frame(
        self,
    ) -> None:
        core = self.configure(1)
        key, view = next(iter(self.records.items()))
        for name, altered in (
            ("profile_id", str(uuid4())),
            ("operation_key", str(uuid4())),
            ("input_receipt_id", str(uuid4())),
            ("payload_sha256", "0" * 64),
            ("payload_byte_length", view.request.origin.payload_byte_length + 1),
        ):
            request = replace(view.request, origin=replace(view.request.origin, **{name: altered}))
            source = request.to_wire()
            source.pop("input_fingerprint")
            if name == "operation_key":
                inner = request.request.to_wire()
                inner.pop("input_fingerprint")
                inner["delegation_id"] = channel_policy_key(altered)
                source["request"] = produce_fixed_policy_request(inner).to_wire()
            forged = produce_channel_policy_request(source)
            record = replace(
                view.record,
                payload=WorkPayload(
                    "booking.evaluate_policy",
                    encode_channel_policy_request(forged),
                    forged.deadline_at_ms,
                ),
            )
            self.records[key] = ChannelPolicyView(record, forged)
            with self.subTest(name=name), self.assertRaises(m.ExecutorError):
                await core.scan_once()
        self.records[key] = view
        receipt = self.page.items[0].receipt_id
        original = self.frames[receipt]
        assert original is not None
        payload = json.loads(json.loads(original)["canonicalPayload"])
        payload["caseRevision"] = "2"
        changed = make_frame(payload)
        raw = encoded(payload)
        request = replace(
            view.request,
            origin=replace(
                view.request.origin,
                payload_sha256=hashlib.sha256(raw).hexdigest(),
                payload_byte_length=len(raw),
            ),
        )
        source = request.to_wire()
        source.pop("input_fingerprint")
        forged = produce_channel_policy_request(source)
        self.frames[receipt] = changed
        self.records[key] = ChannelPolicyView(
            replace(
                view.record,
                payload=WorkPayload(
                    "booking.evaluate_policy",
                    encode_channel_policy_request(forged),
                    forged.deadline_at_ms,
                ),
            ),
            forged,
        )
        with self.assertRaisesRegex(m.ExecutorError, "^identity_conflict$"):
            await core.scan_once()
        self.assertEqual(self.factory.calls, [])
        self.records[key], self.frames[receipt] = view, original
        await core.scan_once()
        await core.close()

    async def test_full_public_stored_work_bytes_scope_identity_sha_and_deadline_are_revalidated(
        self,
    ) -> None:
        core = self.configure(1)
        key, view = next(iter(self.records.items()))
        corrupt = [
            replace(view.record, work_id=str(uuid4())),
            replace(view.record, scope=WorkScope("foreign", "account_demo")),
            replace(view.record, idempotency_key="p2_wrong"),
            replace(
                view.record,
                payload=WorkPayload(
                    "booking.evaluate_policy",
                    view.record.payload.body,
                    view.record.payload.deadline_at_ms + 1,
                ),
            ),
            replace(
                view.record,
                payload=WorkPayload(
                    "booking.evaluate_policy",
                    json.dumps(json.loads(view.record.payload.body), indent=2).encode(),
                    view.request.deadline_at_ms,
                ),
            ),
        ]
        bad_sha = WorkPayload(
            "booking.evaluate_policy", view.record.payload.body, view.request.deadline_at_ms
        )
        object.__setattr__(bad_sha, "sha256", "0" * 64)
        corrupt.append(replace(view.record, payload=bad_sha))
        for record in corrupt:
            self.records[key] = ChannelPolicyView(record, view.request)
            with (
                self.subTest(record=record.work_id),
                self.assertRaisesRegex(m.ExecutorError, "^invalid_stored_state$"),
            ):
                await core.scan_once()
        self.assertEqual(self.factory.calls, [])
        self.records[key] = view
        await core.scan_once()
        await core.close()

    async def test_runner_errors_and_invalid_public_return_are_finite_without_business_retry(
        self,
    ) -> None:
        core = self.configure(1)
        runner = next(iter(self.factory.runners.values()))
        runner.run_error = RuntimeError("PRIVATE_RUN_SENTINEL")
        await core.scan_once()
        await until(lambda: runner.closed == 1)
        self.assertEqual((core.metrics()["jobs_failed"], len(runner.calls)), (1, 1))
        key = next(iter(self.records))
        second = Runner(self.records[key])
        second.alter_result = True
        self.factory.runners[key] = second
        await core.scan_once()
        await until(lambda: second.closed == 1)
        self.assertEqual(
            (core.metrics()["jobs_failed"], len(runner.calls) + len(second.calls)), (2, 2)
        )
        self.factory.runners[key] = Runner(self.records[key])
        await core.scan_once()
        await core.close()
        self.assertEqual(core.metrics()["jobs_succeeded"], 1)

    async def test_config_is_copied_and_invalid_ports_budgets_and_identity_fail_before_ownership(
        self,
    ) -> None:
        core = self.configure(1)
        object.__setattr__(self.binding, "owner_id", str(uuid4()))
        await core.scan_once()
        await core.close()
        self.assertNotEqual(self.factory.calls[0][1], self.binding.owner_id)
        for value in (True, False, float("nan"), float("inf"), 0, 0.0001, 5.1, -1, 10**1000):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(m.ExecutorError, "^invalid_input$"),
            ):
                m.ChannelPolicyExecutor(
                    binding=self.binding,
                    discovery=self.discovery,
                    prepared=self.prepared,
                    stored=self.stored,
                    runners=self.factory,
                    timeout_s=value,
                )
        with self.assertRaisesRegex(m.ExecutorError, "^invalid_input$"):
            m.ChannelPolicyExecutor(
                binding=self.binding,
                discovery=self.discovery,
                prepared=self.prepared,
                stored=self.stored,
                runners=self.factory,
                cleanup_timeout_s=10**1000,
            )
        for pacing in (
            {"rerun_delay_s": -1},
            {"rerun_delay_s": float("nan")},
            {"rerun_delay_s": True},
            {"rerun_cap_s": 61},
            {"rerun_delay_s": 2, "rerun_cap_s": 1},
        ):
            with (
                self.subTest(pacing=pacing),
                self.assertRaisesRegex(m.ExecutorError, "^invalid_input$"),
            ):
                m.ChannelPolicyExecutor(
                    binding=self.binding,
                    discovery=self.discovery,
                    prepared=self.prepared,
                    stored=self.stored,
                    runners=self.factory,
                    **pacing,
                )
        with self.assertRaisesRegex(m.ExecutorError, "^invalid_input$"):
            m.ChannelPolicyExecutor(
                binding=replace(self.binding, owner_id="bad"),
                discovery=self.discovery,
                prepared=self.prepared,
                stored=self.stored,
                runners=self.factory,
            )

        class PrivateGetter:
            @property
            def read(self) -> object:
                raise RuntimeError("PRIVATE_GETTER_SENTINEL")

        with self.assertRaisesRegex(m.ExecutorError, "^invalid_input$"):
            m.ChannelPolicyExecutor(
                binding=self.binding,
                discovery=cast(m.DiscoveryPort, PrivateGetter()),
                prepared=self.prepared,
                stored=self.stored,
                runners=self.factory,
            )
        self.assertEqual(len(self.factory.calls), 1)


class InertImport(unittest.TestCase):
    def test_import_has_no_socket_process_or_task_start(self) -> None:
        script = """import asyncio,socket,subprocess,sys
from unittest.mock import patch
sys.path.insert(0,sys.argv[1])
def denied(*args,**kwargs): raise RuntimeError('IMPORT_IO')
with patch.object(socket.socket,'connect',denied),patch.object(socket.socket,'bind',denied),patch.object(subprocess,'Popen',denied),patch.object(asyncio,'create_task',denied):
 import services.channel_policy_demo.executor
print('inert')
"""
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", script, str(ROOT)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual((result.returncode, result.stdout), (0, "inert\n"), result.stderr)
