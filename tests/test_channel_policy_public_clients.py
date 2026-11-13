"""Actual owned worker threads with fake public P1 functions; no DB/providers."""

from __future__ import annotations

import asyncio
import gc
import subprocess
import sys
import threading
import unittest
import warnings
from dataclasses import FrozenInstanceError
from unittest.mock import patch
from uuid import uuid4

from continuity_lab.authorization import BearerToken
from continuity_lab.postgres_settings import PostgresSettings
from continuity_lab.work_api import WorkDirectory, WorkPrincipal, WorkScope
from delegation_reliability import ChannelPolicyCoordinator, CoordinatorError
from delegation_reliability.contracts import Scope
from delegation_reliability.coordinator import CaseSnapshot
from delegation_reliability.fixed_policy import FixedPolicySpecialistClient
from delegation_reliability.http_client import SpecialistEndpoint
from services.channel_policy_demo import public_clients as m


def configs():
    token = BearerToken("k" * 43)
    scope = WorkScope("tenant_demo", "account_demo")
    directory = WorkDirectory({token: WorkPrincipal("runtime_actor", scope)})
    work = m.PublicWorkConfig(
        PostgresSettings(password="synthetic-password"),
        directory,
        token,
        Scope(scope.tenant_id, scope.account_id),
    )
    specialist = m.PublicSpecialistConfig(SpecialistEndpoint(19999), "Bearer " + "s" * 43)
    receiver = m.PublicReceiverConfig(19998, "p" * 43, str(uuid4()), scope, "recipient_demo")
    return work, specialist, receiver


class Cases:
    def __init__(self, scope):
        self.scope, self.closed = scope, 0

    async def snapshot(self, *, case_id):
        return CaseSnapshot(self.scope, case_id, 1, False)

    async def close(self):
        self.closed += 1


class Port:
    def __init__(self, scope):
        self.scope = scope
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
        self.closed.set()


class ConfigTests(unittest.TestCase):
    def test_inert_config_copies_and_hides_all_credentials(self):
        with patch.object(PostgresSettings, "connect", side_effect=AssertionError("I/O")):
            work, specialist, receiver = configs()
            self.assertNotIn("synthetic-password", repr(work))
            self.assertNotIn("k" * 43, repr(work))
            self.assertNotIn("s" * 43, repr(specialist))
            self.assertNotIn("p" * 43, repr(receiver))
            with self.assertRaises(FrozenInstanceError):
                receiver.port = 1
            copied = m.PublicWorkConfig(work.settings, work.directory, work.token, work.scope)
            object.__setattr__(work.scope, "tenant_id", "mutated")
            self.assertEqual(copied.scope.tenant_id, "tenant_demo")
            self.assertEqual(
                copied.directory.authenticate(copied.token).scope.tenant_id, "tenant_demo"
            )

    def test_scope_mismatch_invalid_tokens_and_huge_budgets_fail_without_io(self):
        work, specialist, receiver = configs()
        with patch.object(PostgresSettings, "connect", side_effect=AssertionError("I/O")):
            with self.assertRaisesRegex(m.JobError, "^unauthorized$"):
                m.PublicWorkConfig(
                    work.settings, work.directory, work.token, Scope("foreign", "account")
                )
            with self.assertRaises(m.JobError):
                m.PublicSpecialistConfig(specialist.endpoint, "Bearer " + "s" * 42)
            with self.assertRaises(m.JobError):
                m.PublicReceiverConfig(
                    receiver.port,
                    "p" * 44,
                    receiver.receiver_id,
                    receiver.scope,
                    receiver.recipient_id,
                )
            for value in (True, 0, 6, float("nan"), 10**1000):
                with (
                    self.subTest(value=value),
                    self.assertRaisesRegex(m.JobError, "^invalid_input$"),
                ):
                    m.PublicClientFactory(
                        work=work,
                        specialist=specialist,
                        receiver=receiver,
                        case_authority=Cases(work.scope),
                        cleanup_timeout_s=value,
                    )

    def test_import_does_not_open_files_threads_sockets_or_public_factories(self):
        script = """
import continuity_lab.execution_api, continuity_lab.delivery_api, continuity_lab.work_api
import delegation_reliability, socket, asyncio, threading
from unittest.mock import patch
from pathlib import Path
with patch.object(socket, 'create_connection', side_effect=AssertionError('socket')), patch.object(threading.Thread, 'start', side_effect=AssertionError('thread')), patch.object(asyncio, 'create_task', side_effect=AssertionError('task')), patch.object(Path, 'read_text', side_effect=AssertionError('file')), patch.object(Path, 'read_bytes', side_effect=AssertionError('file')):
 import services.channel_policy_demo.public_clients
print('inert')
"""
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", script],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "inert"), result.stderr)


class FactoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.work, self.specialist, self.receiver = configs()
        self.cases = Cases(self.work.scope)
        self.factories, self.ports, self.tasks = [], [], []
        self.thread_release = threading.Event()
        self.thread_release.set()
        self.entered = asyncio.Queue(maxsize=16)
        self.loop = asyncio.get_running_loop()
        self.thread_ids = []
        self.open_error = None
        self.port_scope = self.receiver.scope
        self.port_close_release = None
        self.port_close_error = None

        def opened(**values):
            self.thread_ids.append(threading.get_ident())
            self.loop.call_soon_threadsafe(self.entered.put_nowait, values)
            if not self.thread_release.wait(3):
                raise AssertionError("test release deadline")
            if self.open_error is not None:
                raise self.open_error
            port = Port(self.port_scope)
            port.close_release = self.port_close_release
            port.close_error = self.port_close_error
            self.ports.append(port)
            return port

        self.patches = [
            patch.object(m, name, side_effect=opened)
            for name in ("open_execution_client", "open_delivery_client", "open_work_client")
        ]
        for patcher in self.patches:
            patcher.start()

    async def asyncTearDown(self):
        self.thread_release.set()
        self.open_error = None
        if self.port_close_release is not None:
            self.port_close_release.set()
        for port in self.ports:
            port.close_error = None
            if port.close_release is not None:
                port.close_release.set()
        for factory in self.factories:
            for _ in range(3):
                try:
                    await factory.close()
                    break
                except m.JobError:
                    continue
            self.assertEqual(factory.pending_count, 0)
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        for port in self.ports:
            port.close_error = None
            if not port.closed.is_set():
                await port.close()
        for patcher in self.patches:
            patcher.stop()

    def factory(self, **changes):
        values = {
            "work": self.work,
            "specialist": self.specialist,
            "receiver": self.receiver,
            "case_authority": self.cases,
            "cleanup_timeout_s": 0.03,
        }
        values.update(changes)
        factory = m.PublicClientFactory(**values)
        self.factories.append(factory)
        return factory

    def start(self, action):
        task = asyncio.create_task(action)
        self.tasks.append(task)
        return task

    async def seen(self):
        return await asyncio.wait_for(self.entered.get(), 1)

    async def test_real_offload_transfers_fresh_execution_delivery_and_does_not_close_them(self):
        factory = self.factory()
        loop_thread = threading.get_ident()
        execution = await factory.open_execution()
        delivery = await factory.open_delivery()
        self.assertIsNot(execution, delivery)
        self.assertTrue(all(value != loop_thread for value in self.thread_ids))
        self.assertEqual((factory.pending_count, factory.metrics()["transferred"]), (0, 2))
        await factory.close()
        self.assertEqual(
            (execution.close_calls, delivery.close_calls, self.cases.closed), (0, 0, 0)
        )
        await execution.close()
        await delivery.close()

    async def test_actual_public_coordinator_owns_work_and_borrows_shared_cases(self):
        factory = self.factory()
        coordinator = await factory.open()
        self.assertIsInstance(coordinator, ChannelPolicyCoordinator)
        self.assertEqual(coordinator.scope, self.work.scope)
        await factory.close()
        self.assertEqual(self.ports[0].close_calls, 0)
        await coordinator.close()
        self.assertEqual((self.ports[0].close_calls, self.cases.closed), (1, 0))

    async def test_two_actual_worker_startups_reserve_capacity_before_new_io(self):
        factory = self.factory()
        self.thread_release.clear()
        first = self.start(factory.open_execution())
        second = self.start(factory.open_delivery())
        await self.seen()
        await self.seen()
        with self.assertRaisesRegex(m.JobError, "^capacity$"):
            await factory.open_execution()
        self.assertEqual((factory.pending_count, len(self.thread_ids)), (2, 2))
        first.cancel()
        second.cancel()
        self.assertFalse(first.done())
        self.thread_release.set()
        results = await asyncio.gather(first, second, return_exceptions=True)
        self.assertTrue(all(isinstance(value, asyncio.CancelledError) for value in results))
        self.assertEqual(factory.pending_count, 0)
        self.assertTrue(all(port.close_calls == 1 for port in self.ports))
        fresh = await factory.open_execution()
        await fresh.close()
        self.assertEqual(factory.metrics()["transferred"], 1)

    async def test_repeated_cancellation_retains_thread_and_held_late_close_until_settlement(self):
        factory = self.factory()
        self.thread_release.clear()
        self.port_close_release = asyncio.Event()
        opening = self.start(factory.open_execution())
        await self.seen()
        opening.cancel()
        # A second cancellation is latched without cancelling the actual thread.
        opening.cancel()
        self.assertFalse(opening.done())
        self.thread_release.set()
        async with asyncio.timeout(1):
            while not self.ports:
                await asyncio.sleep(0)
        await asyncio.wait_for(self.ports[0].close_entered.wait(), 1)
        opening.cancel()
        with self.assertRaisesRegex(m.JobError, "^cleanup_incomplete$"):
            await factory.close()
        self.assertEqual(
            (factory.pending_count, opening.done(), self.ports[0].close_calls), (1, False, 1)
        )
        self.port_close_release.set()
        await factory.close()
        with self.assertRaises(asyncio.CancelledError):
            await opening
        self.assertEqual(factory.pending_count, 0)

    async def test_failed_late_close_retains_startup_and_cancelled_open_until_explicit_repair(self):
        factory = self.factory()
        self.thread_release.clear()
        self.port_close_error = RuntimeError("PRIVATE_CLOSE")
        opening = self.start(factory.open_execution())
        await self.seen()
        opening.cancel()
        self.thread_release.set()
        async with asyncio.timeout(1):
            while not self.ports:
                await asyncio.sleep(0)
        await asyncio.wait_for(self.ports[0].close_entered.wait(), 1)
        self.assertEqual((factory.pending_count, opening.done()), (1, False))
        self.ports[0].close_error = None
        await factory.close()
        with self.assertRaises(asyncio.CancelledError):
            await opening
        self.assertEqual((factory.pending_count, self.ports[0].close_calls), (0, 2))

    async def test_constructor_failure_is_finite_no_owner_leaks_and_next_work_progresses(self):
        factory = self.factory()
        self.open_error = RuntimeError("PRIVATE_CONSTRUCTOR")
        with self.assertRaisesRegex(m.JobError, "^unavailable$"):
            await factory.open_execution()
        self.assertEqual((factory.pending_count, len(self.ports)), (0, 0))
        self.open_error = None
        value = await factory.open_execution()
        await value.close()
        self.assertEqual(factory.pending_count, 0)

    async def test_wrong_scope_return_is_adopted_and_closed_before_failure_escapes(self):
        factory = self.factory()
        self.port_scope = WorkScope("foreign", "account")
        with self.assertRaisesRegex(m.JobError, "^unauthorized$"):
            await factory.open_execution()
        self.assertEqual((factory.pending_count, self.ports[0].close_calls), (0, 1))
        self.port_scope = self.receiver.scope
        value = await factory.open_delivery()
        await value.close()

    async def test_public_coordinator_constructor_failure_closes_only_owned_work_port(self):
        factory = self.factory()
        with (
            patch.object(
                m, "ChannelPolicyCoordinator", side_effect=RuntimeError("PRIVATE_COORDINATOR")
            ),
            self.assertRaisesRegex(CoordinatorError, "^storage_unavailable$"),
        ):
            await factory.open()
        self.assertEqual(
            (factory.pending_count, self.ports[0].close_calls, self.cases.closed), (0, 1, 0)
        )
        coordinator = await factory.open()
        await coordinator.close()

    async def test_close_waiter_cancellation_keeps_same_actual_observer_and_all_workers(self):
        factory = self.factory()
        self.thread_release.clear()
        first = self.start(factory.open_execution())
        second = self.start(factory.open_delivery())
        await self.seen()
        await self.seen()
        closing = self.start(factory.close())
        await asyncio.sleep(0)
        closing.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await closing
        self.assertEqual(factory.pending_count, 2)
        self.thread_release.set()
        await factory.close()
        values = await asyncio.gather(first, second, return_exceptions=True)
        self.assertTrue(
            all(isinstance(value, m.JobError) and value.code == "closed" for value in values)
        )
        self.assertEqual(factory.pending_count, 0)
        self.assertTrue(all(port.close_calls == 1 for port in self.ports))

    async def test_task_allocation_control_flow_closes_coroutine_and_rolls_back_empty_startup(self):
        factory = self.factory()
        with warnings.catch_warnings(record=True) as observed:
            warnings.simplefilter("always")
            with (
                patch.object(m.asyncio, "create_task", side_effect=asyncio.CancelledError),
                self.assertRaises(asyncio.CancelledError),
            ):
                await factory.open_execution()
            gc.collect()
        self.assertFalse(
            [warning for warning in observed if issubclass(warning.category, RuntimeWarning)]
        )
        self.assertEqual((factory.pending_count, self.thread_ids), (0, []))
        port = await factory.open_execution()
        await port.close()

    async def test_config_snapshot_is_stable_after_caller_values_are_changed(self):
        factory = self.factory()
        object.__setattr__(self.work.settings, "schema", "changed")
        object.__setattr__(self.work.scope, "tenant_id", "changed")
        object.__setattr__(self.work.token, "value", "z" * 43)
        port = await factory.open_execution()
        passed = await self.seen()
        self.assertEqual(
            (
                passed["settings"].schema,
                passed["token"].value,
                passed["directory"].authenticate(passed["token"]).scope,
            ),
            ("continuity", "k" * 43, self.receiver.scope),
        )
        await port.close()

    async def test_real_specialist_constructor_is_inert_fresh_and_uses_public_interface(self):
        factory = self.factory()
        # Evidence is independently verified/passed by the runner, never selected here.
        from test_channel_policy_jobs import fixture

        _, evidence = fixture()
        one = await factory.open_specialist(evidence=evidence)
        two = await factory.open_specialist(evidence=evidence)
        self.assertIsInstance(one, FixedPolicySpecialistClient)
        self.assertIsNot(one, two)
        self.assertEqual((one.active, two.active, factory.pending_count), (0, 0, 0))
        await factory.close()
        await one.close()
        await two.close()

    async def test_wrong_scope_and_held_close_cannot_release_open_before_actual_cleanup(self):
        factory = self.factory()
        self.port_scope = WorkScope("foreign", "account")
        self.port_close_release = asyncio.Event()
        opening = self.start(factory.open_execution())
        await self.seen()
        async with asyncio.timeout(1):
            while not self.ports:
                await asyncio.sleep(0)
        await asyncio.wait_for(self.ports[0].close_entered.wait(), 1)
        self.assertEqual((factory.pending_count, opening.done()), (1, False))
        self.port_close_release.set()
        with self.assertRaisesRegex(m.JobError, "^unauthorized$"):
            await opening
        self.assertEqual(factory.pending_count, 0)
        self.port_scope = self.receiver.scope
        fresh = await factory.open_delivery()
        await fresh.close()

    async def test_cleanup_allocation_cancellation_retains_actual_unreceived_port_until_repair(
        self,
    ):
        factory = self.factory()
        self.port_scope = WorkScope("foreign", "account")
        original = asyncio.create_task
        failed = asyncio.Event()
        fail_once = True

        def allocate(action):
            nonlocal fail_once
            if action.cr_code.co_name == "finish" and fail_once:
                fail_once = False
                failed.set()
                raise asyncio.CancelledError()
            return original(action)

        with patch.object(m.asyncio, "create_task", side_effect=allocate):
            opening = self.start(factory.open_execution())
            await asyncio.wait_for(failed.wait(), 1)
        self.assertEqual(
            (factory.pending_count, opening.done(), self.ports[0].close_calls), (1, False, 0)
        )
        await factory.close()
        with self.assertRaises(asyncio.CancelledError):
            await opening
        self.assertEqual((factory.pending_count, self.ports[0].close_calls), (0, 1))

    async def test_cancelled_synchronous_constructor_has_settled_before_next_admission(self):
        factory = self.factory()
        self.open_error = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await factory.open_execution()
        self.assertEqual((factory.pending_count, self.ports), (0, []))
        self.open_error = None
        value = await factory.open_execution()
        await value.close()
        self.assertEqual(factory.pending_count, 0)

    async def test_coordinator_capacity_and_closed_errors_match_public_origin_contract(self):
        factory = self.factory()
        self.thread_release.clear()
        first = self.start(factory.open_execution())
        second = self.start(factory.open_delivery())
        await self.seen()
        await self.seen()
        with self.assertRaisesRegex(CoordinatorError, "^capacity$"):
            await factory.open()
        self.assertEqual(len(self.thread_ids), 2)
        self.thread_release.set()
        first_port, second_port = await asyncio.gather(first, second)
        await factory.close()
        with self.assertRaisesRegex(CoordinatorError, "^closed$"):
            await factory.open()
        await first_port.close()
        await second_port.close()

    async def test_actual_canonical_receiver_constructor_close_and_ownership_are_inert(self):
        from services.channel_policy_demo.result_receiver import ChannelResultReceiver

        factory = self.factory()
        with patch.object(asyncio, "open_connection", side_effect=AssertionError("network")):
            receiver = await factory.open_receiver()
            self.assertIsInstance(receiver, ChannelResultReceiver)
            self.assertEqual(
                (receiver.receiver_id, receiver.pending_count, factory.pending_count),
                (self.receiver.receiver_id, 0, 0),
            )
            await factory.close()
            self.assertFalse(receiver._closing)
            await receiver.close()
            self.assertTrue(receiver._closing)
        self.assertEqual(self.cases.closed, 0)

    async def test_invalid_evidence_rejected_before_specialist_creation_and_can_progress(self):
        factory = self.factory()
        with (
            patch.object(
                m, "FixedPolicySpecialistClient", side_effect=AssertionError("constructor")
            ),
            self.assertRaisesRegex(m.JobError, "^invalid_input$"),
        ):
            await factory.open_specialist(evidence=())
        self.assertEqual(factory.pending_count, 0)
        value = await factory.open_execution()
        await value.close()


if __name__ == "__main__":
    unittest.main()
