"""Joined composition: fake public storage/runner ports, real local source sockets."""

from __future__ import annotations

import asyncio
import copy
import json
import socket
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from delegation_reliability.coordinator import CaseSnapshot
from delegation_reliability.fixed_policy_contracts import produce_fixed_policy_request
from services.channel_policy_demo import application as m
from services.channel_policy_demo import owner_config as c
from services.channel_policy_demo.current_result import CurrentResultObservation
from services.channel_policy_demo.discovery import DiscoveryPage, DiscoveryScope
from services.channel_policy_demo.executor import ScanObservation

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = "PRIVATE_DEPENDENCY_TEXT_NEVER_DIAGNOSE"


def profile():
    data = json.loads((ROOT / "contracts/delegation/fixed-policy-v2.json").read_bytes())
    template = produce_fixed_policy_request(copy.deepcopy(data["producer_input"]))
    sockets = [socket.socket() for _ in range(8)]
    try:
        for item in sockets:
            item.bind(("127.0.0.1", 0))
        ports = c.ProfilePorts(*(item.getsockname()[1] for item in sockets))
    finally:
        for item in sockets:
            item.close()
    return c.OwnerProfile(
        c.ProfileRoute(
            str(uuid4()),
            str(uuid4()),
            template.scope,
            template.case_id,
            template.conversation_id,
            "recipient_demo",
        ),
        ports,
        c.ProfileDatabase(15432, "p1_app_case", "p1_work_app", "p2_app_channel"),
        c.ProfileCase("actor_demo", "scope_demo", str(uuid4()), str(uuid4())),
        c.ProfileCredentials(
            "synthetic_password_only" * 2, *(character * 43 for character in "abcdefghij")
        ),
        str(uuid4()),
        "joined_rtc",
        "joined_sms",
        (
            c.ProfilePolicy(
                template, (data["policy_body_utf8"].encode(), data["facts_body_utf8"].encode())
            ),
        ),
    )


class Composition(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.profile = profile()
        self.trace = []
        self.fail = set()
        self.holds = {}
        self.apps = []
        self.producers = []
        self.jobs = []
        outer = self

        class Owner:
            def __init__(self, label):
                self.label = label
                self.closed = False
                outer.trace.append("new:" + label)

            async def close(self):
                outer.trace.append("close:" + self.label)
                if event := outer.holds.get(self.label):
                    await event.wait()
                if self.label in outer.fail:
                    raise RuntimeError(PRIVATE)
                self.closed = True
                outer.trace.append("closed:" + self.label)

        class Managed(Owner):
            async def get(self, **kwargs):
                raise AssertionError("no case HTTP business read in this composition test")

        class Cases:
            def __init__(self, client, *, scope, bindings):
                self.scope = scope

            async def snapshot(self, *, case_id):
                outer.trace.append("snapshot")
                if event := outer.holds.get("case-observe"):
                    await event.wait()
                if "case-observe" in outer.fail:
                    raise RuntimeError(PRIVATE)
                return CaseSnapshot(self.scope, case_id, 1, False)

        class Stored(Owner):
            async def get(self, work_id):
                raise AssertionError("executor storage is a separate fake in this suite")

        class Clients(Owner):
            def __init__(self, **kwargs):
                super().__init__("clients")

            async def open(self):
                if "open" in outer.fail:
                    raise RuntimeError(PRIVATE)
                return Stored("stored")

            async def open_execution(self):
                raise AssertionError("unexpected execution")

            async def open_specialist(self, *, evidence):
                raise AssertionError("unexpected specialist")

            async def open_delivery(self):
                raise AssertionError("unexpected delivery")

            async def open_receiver(self):
                raise AssertionError("unexpected receiver")

        class Worker(Owner):
            def __init__(self, *args, **kwargs):
                super().__init__("worker")
                self.reads = 0

            async def discovery(self):
                self.reads += 1
                outer.trace.append("ready-read")
                if event := outer.holds.get("progress-observe"):
                    await event.wait()
                if "ready" in outer.fail:
                    raise RuntimeError(PRIVATE)
                r = outer.profile.route
                return DiscoveryPage(
                    r.profile_id,
                    DiscoveryScope(r.scope.tenant_id, r.scope.account_id),
                    r.case_id,
                    r.conversation_id,
                    "2030-01-01T00:00:00.000Z",
                    (),
                    False,
                    None,
                )

            async def prepared(self, **kwargs):
                raise AssertionError("unexpected prepared read")

        class Jobs(Owner):
            def __init__(self, **kwargs):
                super().__init__("jobs")
                outer.jobs.append(self)

            async def open_inspection(self, **kwargs):
                raise AssertionError("unexpected inspection for empty history")

            async def open(self, **kwargs):
                raise AssertionError("unexpected job")

        class Executor(Owner):
            def __init__(self, **kwargs):
                super().__init__("executor")
                outer.executor_arguments = kwargs

            async def scan_once(self):
                outer.trace.append("scan")
                if event := outer.holds.get("scan"):
                    await event.wait()
                if "scan" in outer.fail:
                    raise RuntimeError(PRIVATE)

        class Producer(Owner):
            def __init__(self, **kwargs):
                super().__init__("producer" + str(len(outer.producers) + 1))
                self.arguments = kwargs
                self.reads = 0
                outer.producers.append(self)

            async def read(self):
                self.reads += 1
                outer.trace.append("read:" + self.label)
                if event := outer.holds.get("read:" + self.label):
                    await event.wait()
                binding = self.arguments["binding"]
                return CurrentResultObservation(
                    binding.profile_id,
                    DiscoveryScope(binding.scope.tenant_id, binding.scope.account_id),
                    binding.case_id,
                    binding.conversation_id,
                    "2030-01-01T00:00:00.000Z",
                    "no_delivery",
                    None,
                )

        class Native:
            def __init__(self):
                self.reads = self.closes = 0

            async def read(self, *, delivery_id):
                self.reads += 1
                raise AssertionError("empty history must not select a delivery")

            async def close(self):
                self.closes += 1

        self.Producer, self.Native = Producer, Native
        self.Managed = Managed
        self.factory = lambda **kwargs: Managed("case")
        patches = [
            patch.object(
                m, "open_postgres_client", side_effect=lambda **kwargs: self.factory(**kwargs)
            ),
            patch.object(m, "ManagedCaseAuthority", Cases),
            patch.object(m, "PublicClientFactory", Clients),
            patch.object(m, "ChannelPolicyWorkerClient", Worker),
            patch.object(m, "ChannelPolicyJobFactory", Jobs),
            patch.object(m, "ChannelPolicyExecutor", Executor),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    async def asyncTearDown(self):
        self.fail.clear()
        for event in self.holds.values():
            event.set()
        for app in self.apps:
            await app.close()

    def app(self, **kwargs):
        result = m.ChannelPolicyApplication(self.profile, **kwargs)
        self.apps.append(result)
        return result

    def assert_port_closed(self, port):
        with socket.socket() as check:
            check.settimeout(0.2)
            self.assertNotEqual(check.connect_ex(("127.0.0.1", port)), 0)

    async def test_operator_observations_share_existing_clients_and_leave_jobs_untouched(self):
        app = self.app()
        await app.start_sources()
        before = app.metrics()["owned_resources"]
        case = await app.observe_case()
        progress = await app.observe_progress()
        self.assertEqual(case.revision, "1")
        self.assertRegex(case.observed_at, r"Z$")
        self.assertEqual(progress.payload()["counts"]["workKnown"], 0)
        self.assertEqual(app.metrics()["owned_resources"], before)
        self.assertEqual(len(self.jobs), 1)
        self.assertNotIn("new:producer1", self.trace)

    async def test_operator_observations_require_ready_sources(self):
        app = self.app()
        for read in (app.observe_case, app.observe_progress):
            with self.assertRaisesRegex(m.ApplicationError, "^unavailable$"):
                await read()
        await app.start_sources()
        await app.close()
        for read in (app.observe_case, app.observe_progress):
            with self.assertRaisesRegex(m.ApplicationError, "^closed$"):
                await read()

    async def test_failed_operator_reads_do_not_fabricate_success(self):
        app = self.app()
        await app.start_sources()
        self.fail.update(("case-observe", "ready"))
        for read in (app.observe_case, app.observe_progress):
            with self.assertRaisesRegex(m.ApplicationError, "^unavailable$") as caught:
                await read()
            self.assertNotIn(PRIVATE, repr(caught.exception))
        self.fail.clear()
        self.assertEqual((await app.observe_case()).revision, "1")
        self.assertEqual((await app.observe_progress()).native, 0)

    async def test_late_case_read_is_fenced_after_application_close(self):
        app = self.app()
        await app.start_sources()
        hold = self.holds["case-observe"] = asyncio.Event()
        waiter = asyncio.create_task(app.observe_case())
        while self.trace.count("snapshot") < 2:
            await asyncio.sleep(0)
        await app.close()
        hold.set()
        with self.assertRaisesRegex(m.ApplicationError, "^closed$"):
            await waiter

    async def test_late_progress_read_is_fenced_after_application_close(self):
        app = self.app()
        await app.start_sources()
        hold = self.holds["progress-observe"] = asyncio.Event()
        waiter = asyncio.create_task(app.observe_progress())
        while "ready-read" not in self.trace:
            await asyncio.sleep(0)
        await app.close()
        hold.set()
        with self.assertRaisesRegex(m.ApplicationError, "^closed$"):
            await waiter

    async def test_constructor_and_close_before_start_are_inert(self):
        app = self.app()
        self.assertEqual(self.trace, [])
        await app.close()
        self.assertEqual(app.metrics()["closed"], 1)
        self.assertEqual(app.metrics()["owned_resources"], 0)
        with self.assertRaisesRegex(m.ApplicationError, "^closed$"):
            await app.start_sources()

    async def test_real_three_source_listeners_bind_once_with_dispatch_budget_and_drain(self):
        app = self.app()
        await asyncio.gather(app.start_sources(), app.start_sources())
        self.assertEqual(app.metrics()["sources_ready"], 1)
        self.assertEqual(app.metrics()["owned_resources"], 10)
        self.assertEqual(self.trace.count("new:case"), 1)
        origins = [owner.value for owner in app._owners if type(owner.value) is m.ChannelOriginHttp]
        self.assertEqual([origin._call_timeout for origin in origins], [5.0, 5.0])
        await app.start_sources()
        self.assertEqual(self.trace.count("new:case"), 1)
        await app.close()
        for port in (
            self.profile.ports.case,
            self.profile.ports.native_origin,
            self.profile.ports.sms_origin,
        ):
            self.assert_port_closed(port)
        self.assertLess(self.trace.index("closed:executor"), self.trace.index("close:jobs"))
        self.assertLess(self.trace.index("closed:jobs"), self.trace.index("close:stored"))
        self.assertLess(self.trace.index("closed:stored"), self.trace.index("close:case"))
        self.assertEqual(app.metrics()["owned_resources"], 0)

    async def test_start_executor_requires_sources_then_node_readiness(self):
        app = self.app()
        with self.assertRaises(m.ApplicationError):
            await app.start_executor()
        await app.start_sources()
        self.fail.add("ready")
        with self.assertRaisesRegex(m.ApplicationError, "^unavailable$"):
            await app.start_executor()
        self.assertNotIn("scan", self.trace)
        self.fail.clear()
        await asyncio.gather(app.start_executor(), app.start_executor())
        await asyncio.sleep(0)
        self.assertEqual(app.metrics()["executor_running"], 1)
        self.assertLess(self.trace.index("ready-read"), self.trace.index("scan"))
        await app.close()
        self.assertEqual(app.metrics()["executor_running"], 0)

    async def test_partial_factory_failure_closes_every_returned_owner(self):
        app = self.app()
        self.fail.add("open")
        with self.assertRaisesRegex(m.ApplicationError, "^unavailable$") as error:
            await app.start_sources()
        self.assertNotIn(PRIVATE, str(error.exception))
        await app.close()
        self.assertEqual(app.metrics()["owned_resources"], 0)
        self.assertIn("closed:clients", self.trace)
        self.assertIn("closed:case", self.trace)
        self.assertNotIn("new:jobs", self.trace)

    async def test_occupied_port_has_no_fallback_and_partial_bind_is_drained(self):
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", self.profile.ports.native_origin))
            occupied.listen(1)
            app = self.app()
            with self.assertRaisesRegex(m.ApplicationError, "^unavailable$"):
                await app.start_sources()
            await app.close()
            self.assert_port_closed(self.profile.ports.case)
            self.assertEqual(occupied.getsockname()[1], self.profile.ports.native_origin)

    async def test_cancelled_start_retains_actual_thread_and_never_binds_after_close(self):
        entered, release = threading.Event(), threading.Event()

        def held(**kwargs):
            entered.set()
            if not release.wait(3):
                raise AssertionError("test startup barrier not released")
            return self.Managed("case")

        self.factory = held
        app = self.app(cleanup_timeout_s=0.02)
        opening = asyncio.create_task(app.start_sources())
        while not entered.is_set():
            await asyncio.sleep(0.001)
        opening.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await opening
        with self.assertRaisesRegex(m.ApplicationError, "^cleanup_incomplete$"):
            await app.close()
        self.assertEqual(app.metrics()["starting"], 1)
        release.set()
        await asyncio.sleep(0.01)
        await app.close()
        self.assertEqual(self.trace, ["new:case", "close:case", "closed:case"])
        self.assert_port_closed(self.profile.ports.case)

    async def test_timeout_uses_original_deadline_and_denies_late_binding(self):
        entered, release = threading.Event(), threading.Event()

        def held(**kwargs):
            entered.set()
            if not release.wait(3):
                raise AssertionError("test startup barrier not released")
            return self.Managed("case")

        self.factory = held
        app = self.app(startup_timeout_s=0.02)
        with self.assertRaisesRegex(m.ApplicationError, "^unavailable$"):
            await app.start_sources()
        release.set()
        await asyncio.sleep(0.01)
        with self.assertRaisesRegex(m.ApplicationError, "^unavailable$"):
            await app.start_sources()
        await app.close()
        self.assertNotIn("new:clients", self.trace)
        self.assertEqual(self.trace[-1], "closed:case")

    async def test_independent_active_close_attempts_withhold_readers_until_retry(self):
        app = self.app()
        await app.start_sources()
        self.fail.add("executor")
        with self.assertRaisesRegex(m.ApplicationError, "^cleanup_incomplete$"):
            await app.close()
        self.assertIn("closed:clients", self.trace)
        self.assertNotIn("close:jobs", self.trace)
        self.assertNotIn("close:stored", self.trace)
        self.assertNotIn("close:case", self.trace)
        self.fail.clear()
        await app.close()
        self.assertEqual(app.metrics()["owned_resources"], 0)

    async def test_close_waiter_cancellation_retains_actual_held_close(self):
        app = self.app()
        await app.start_sources()
        self.holds["executor"] = asyncio.Event()
        closing = asyncio.create_task(app.close())
        while "close:executor" not in self.trace:
            await asyncio.sleep(0)
        closing.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await closing
        self.assertNotIn("close:case", self.trace)
        self.holds["executor"].set()
        await app.close()
        self.assertEqual(self.trace.count("close:executor"), 1)
        self.assertEqual(app.metrics()["closed"], 1)

    async def test_scan_failure_and_telemetry_outage_do_not_erase_work_or_block_close(self):
        app = self.app()
        await app.start_sources()
        self.fail.add("scan")
        with patch.object(m.LOGGER, "info", side_effect=RuntimeError(PRIVATE)):
            await app.start_executor()
            while not app.metrics()["scans_failed"]:
                await asyncio.sleep(0)
            self.assertGreater(app.metrics()["telemetry_failed"], 0)
            await app.close()
        self.assertEqual(app.metrics()["closed"], 1)

    async def test_start_task_allocation_failure_creates_no_resources_and_next_start_works(self):
        app = self.app()
        with (
            patch.object(m.asyncio, "create_task", side_effect=asyncio.CancelledError),
            self.assertRaises(asyncio.CancelledError),
        ):
            await app.start_sources()
        self.assertEqual(app.metrics()["owned_resources"], 0)
        await app.start_sources()
        self.assertEqual(app.metrics()["sources_ready"], 1)

    async def test_source_allocation_error_is_finite_and_next_start_works(self):
        app = self.app()
        with (
            patch.object(m.asyncio, "create_task", side_effect=RuntimeError(PRIVATE)),
            self.assertRaisesRegex(m.ApplicationError, "^unavailable$") as error,
        ):
            await app.start_sources()
        self.assertNotIn(PRIVATE, str(error.exception))
        self.assertEqual(app.metrics()["owned_resources"], 0)
        await app.start_sources()
        self.assertEqual(app.metrics()["sources_ready"], 1)

    async def test_scanner_allocation_error_is_finite_and_next_admission_progresses(self):
        app = self.app()
        await app.start_sources()
        with (
            patch.object(m.asyncio, "create_task", side_effect=RuntimeError(PRIVATE)),
            self.assertRaisesRegex(m.ApplicationError, "^unavailable$") as error,
        ):
            await app.start_executor()
        self.assertNotIn(PRIVATE, str(error.exception))
        self.assertEqual(app.metrics()["executor_running"], 0)
        self.assertNotIn("scan", self.trace)
        await app.start_executor()
        await asyncio.sleep(0)
        self.assertIn("scan", self.trace)
        await app.close()

    async def test_close_allocation_error_retains_owners_and_retry_drains_them(self):
        app = self.app()
        await app.start_sources()
        with (
            patch.object(m.asyncio, "create_task", side_effect=RuntimeError(PRIVATE)),
            self.assertRaisesRegex(m.ApplicationError, "^cleanup_incomplete$") as error,
        ):
            await app.close()
        self.assertNotIn(PRIVATE, str(error.exception))
        self.assertEqual(app.metrics()["owned_resources"], 10)
        self.assertNotIn("close:case", self.trace)
        await app.close()
        self.assertEqual(app.metrics()["owned_resources"], 0)
        self.assertEqual(app.metrics()["closed"], 1)

    async def test_background_readers_share_one_lane_and_progress_waits_for_it(self):
        app = self.app()
        await app.start_sources()
        lane = self.executor_arguments["discovery"].lane
        self.assertIsInstance(lane, asyncio.Semaphore)
        self.assertIs(self.executor_arguments["prepared"].lane, lane)
        with patch.object(m, "CurrentResultProducer", self.Producer):
            app.attach_current_result(self.Native())
        for port in ("discovery", "prepared"):
            self.assertIs(self.producers[-1].arguments[port].lane, lane)
        await lane.acquire()
        progress = asyncio.create_task(app.observe_progress())
        for _ in range(5):
            await asyncio.sleep(0)
        self.assertFalse(progress.done())
        lane.release()
        self.assertEqual((await progress).native, 0)
        await app.close_current_result()

    async def test_current_read_retries_only_transient_capacity_within_its_bound(self):
        from services.channel_policy_demo.current_result_producer import (
            CurrentResultProducerError,
        )

        outcomes = []

        class Flaky(self.Producer):
            async def read(inner):
                code = outcomes.pop(0) if outcomes else None
                if code is not None:
                    raise CurrentResultProducerError(code)
                return await super().read()

        app = self.app()
        await app.start_sources()
        with (
            patch.object(m, "CURRENT_READ_RETRY_DELAYS_S", (0, 0)),
            patch.object(m, "CurrentResultProducer", Flaky),
        ):
            reader = app.attach_current_result(self.Native())
            outcomes[:] = ["capacity", "capacity"]
            self.assertEqual((await reader.read()).state, "no_delivery")
            outcomes[:] = ["capacity", "capacity", "capacity"]
            with self.assertRaisesRegex(CurrentResultProducerError, "^capacity$"):
                await reader.read()
            outcomes[:] = ["unavailable"]
            with self.assertRaisesRegex(CurrentResultProducerError, "^unavailable$"):
                await reader.read()
            self.assertEqual(outcomes, [])
            outcomes[:] = ["capacity"]
            await app.close_current_result()
            with self.assertRaisesRegex(m.ApplicationError, "^closed$"):
                await reader.read()
            self.assertEqual(outcomes, ["capacity"])

    async def test_actual_producer_uses_shared_public_ports_for_empty_history(self):
        app = self.app()
        await app.start_sources()
        native = self.Native()
        reader = app.attach_current_result(native)
        result = await reader.read()
        self.assertEqual(result.state, "no_delivery")
        self.assertEqual(result.profile_id, self.profile.route.profile_id)
        self.assertIsNone(result.result)
        self.assertEqual((native.reads, native.closes), (0, 0))
        self.assertEqual(self.trace.count("new:jobs"), 1)
        self.assertEqual(app.metrics()["owned_resources"], 11)
        self.assertFalse(hasattr(reader, "close"))
        await app.close_current_result()
        self.assertEqual(app.metrics()["owned_resources"], 10)
        with self.assertRaisesRegex(m.ApplicationError, "^closed$"):
            await reader.read()
        await app.start_executor()
        await app.close()
        self.assertEqual(native.closes, 0)

    async def test_current_attachment_requires_ready_sources_and_valid_native_port(self):
        app = self.app()
        with self.assertRaisesRegex(m.ApplicationError, "^unavailable$"):
            app.attach_current_result(self.Native())
        await app.close_current_result()
        await app.start_sources()
        with self.assertRaisesRegex(m.ApplicationError, "^invalid_input$"):
            app.attach_current_result(object())
        self.assertEqual(app.metrics()["owned_resources"], 10)
        reader = app.attach_current_result(self.Native())
        self.assertEqual((await reader.read()).state, "no_delivery")
        await app.close()
        with self.assertRaisesRegex(m.ApplicationError, "^closed$"):
            app.attach_current_result(self.Native())

    async def test_repeated_rooms_reuse_factory_and_keep_owner_bookkeeping_bounded(self):
        app = self.app()
        await app.start_sources()
        native = self.Native()
        with patch.object(m, "CurrentResultProducer", self.Producer):
            for _ in range(20):
                reader = app.attach_current_result(native)
                arguments = self.producers[-1].arguments
                binding = arguments["binding"]
                self.assertIs(arguments["inspections"], self.jobs[0])
                self.assertEqual(binding.owner_id, self.profile.app_owner_id)
                self.assertEqual(binding.receiver_id, self.profile.route.receiver_id)
                self.assertEqual(binding.recipient_id, self.profile.route.recipient_id)
                with self.assertRaisesRegex(m.ApplicationError, "^capacity$"):
                    app.attach_current_result(self.Native())
                self.assertEqual((await reader.read()).state, "no_delivery")
                await app.close_current_result()
                self.assertEqual(len(app._owners), 10)
                with self.assertRaisesRegex(m.ApplicationError, "^closed$"):
                    await reader.read()
        self.assertEqual(self.trace.count("new:jobs"), 1)
        self.assertEqual(self.trace.count("new:stored"), 1)
        self.assertEqual(native.closes, 0)
        await app.close_current_result()

    async def test_held_current_close_keeps_slot_and_all_shared_readers_alive(self):
        app = self.app(cleanup_timeout_s=0.02)
        await app.start_sources()
        with patch.object(m, "CurrentResultProducer", self.Producer):
            reader = app.attach_current_result(self.Native())
            self.holds["producer1"] = asyncio.Event()
            with self.assertRaisesRegex(m.ApplicationError, "^cleanup_incomplete$"):
                await app.close_current_result()
            with self.assertRaisesRegex(m.ApplicationError, "^capacity$"):
                app.attach_current_result(self.Native())
            with self.assertRaisesRegex(m.ApplicationError, "^closed$"):
                await reader.read()
            self.assertEqual(app.metrics()["current_result_closing"], 1)
            self.assertNotIn("close:jobs", self.trace)
            self.assertNotIn("close:worker", self.trace)
            self.holds["producer1"].set()
            await app.close_current_result()
            self.assertEqual(self.trace.count("close:producer1"), 1)
            self.assertEqual(app.metrics()["current_result_attached"], 0)
            self.assertEqual(
                (await app.attach_current_result(self.Native()).read()).state, "no_delivery"
            )

    async def test_cancelled_current_close_retains_same_actual_close(self):
        app = self.app()
        await app.start_sources()
        with patch.object(m, "CurrentResultProducer", self.Producer):
            app.attach_current_result(self.Native())
            self.holds["producer1"] = asyncio.Event()
            closing = asyncio.create_task(app.close_current_result())
            while "close:producer1" not in self.trace:
                await asyncio.sleep(0)
            closing.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await closing
            with self.assertRaisesRegex(m.ApplicationError, "^capacity$"):
                app.attach_current_result(self.Native())
            self.holds["producer1"].set()
            await app.close_current_result()
        self.assertEqual(self.trace.count("close:producer1"), 1)

    async def test_failed_current_close_blocks_new_room_until_successful_retry(self):
        app = self.app()
        await app.start_sources()
        with patch.object(m, "CurrentResultProducer", self.Producer):
            app.attach_current_result(self.Native())
            self.fail.add("producer1")
            with self.assertRaisesRegex(m.ApplicationError, "^cleanup_incomplete$"):
                await app.close_current_result()
            self.assertEqual(app.metrics()["owned_resources"], 11)
            with self.assertRaisesRegex(m.ApplicationError, "^capacity$"):
                app.attach_current_result(self.Native())
            self.fail.clear()
            await app.close_current_result()
            self.assertEqual(self.trace.count("close:producer1"), 2)
            self.assertEqual(
                (await app.attach_current_result(self.Native()).read()).state, "no_delivery"
            )

    async def test_late_old_room_read_is_fenced_after_new_room_attaches(self):
        app = self.app()
        await app.start_sources()
        with patch.object(m, "CurrentResultProducer", self.Producer):
            old = app.attach_current_result(self.Native())
            self.holds["read:producer1"] = asyncio.Event()
            reading = asyncio.create_task(old.read())
            while "read:producer1" not in self.trace:
                await asyncio.sleep(0)
            await app.close_current_result()
            current = app.attach_current_result(self.Native())
            self.holds["read:producer1"].set()
            with self.assertRaisesRegex(m.ApplicationError, "^closed$"):
                await reading
            self.assertEqual((await current.read()).state, "no_delivery")
            self.assertEqual(self.producers[1].reads, 1)
            self.assertEqual(self.producers[0].reads, 1)

    async def test_application_close_drains_current_before_jobs_and_shared_sources(self):
        app = self.app(cleanup_timeout_s=0.02)
        await app.start_sources()
        native = self.Native()
        with patch.object(m, "CurrentResultProducer", self.Producer):
            reader = app.attach_current_result(native)
            self.holds["producer1"] = asyncio.Event()
            with self.assertRaisesRegex(m.ApplicationError, "^cleanup_incomplete$"):
                await app.close()
            self.assertNotIn("close:jobs", self.trace)
            self.assertNotIn("close:case", self.trace)
            with self.assertRaisesRegex(m.ApplicationError, "^closed$"):
                await reader.read()
            self.holds["producer1"].set()
            # The negative observer intentionally has only 20 ms. Observe the
            # SAME retained close through its public retry API; CPU scheduling
            # is not a promise that all dependent listeners drain in 20 ms.
            async with asyncio.timeout(1):
                while True:
                    try:
                        await app.close()
                        break
                    except m.ApplicationError as error:
                        if error.code != "cleanup_incomplete":
                            raise
        self.assertLess(self.trace.index("closed:producer1"), self.trace.index("close:jobs"))
        self.assertEqual(app.metrics()["owned_resources"], 0)
        self.assertEqual(native.closes, 0)

    async def test_current_close_allocation_failure_preserves_owner_for_retry(self):
        app = self.app()
        await app.start_sources()
        with patch.object(m, "CurrentResultProducer", self.Producer):
            app.attach_current_result(self.Native())
            with (
                patch.object(m.asyncio, "create_task", side_effect=RuntimeError(PRIVATE)),
                self.assertRaisesRegex(m.ApplicationError, "^cleanup_incomplete$"),
            ):
                await app.close_current_result()
            self.assertEqual(app.metrics()["owned_resources"], 11)
            with self.assertRaisesRegex(m.ApplicationError, "^capacity$"):
                app.attach_current_result(self.Native())
            await app.close_current_result()
        self.assertEqual(app.metrics()["owned_resources"], 10)
        self.assertEqual(self.trace.count("close:producer1"), 1)

    async def test_eager_reentrant_close_observes_one_published_owner(self):
        app = self.app()
        await app.start_sources()
        reentered = []
        outer = self

        class Reentrant(self.Producer):
            async def close(self):
                reentered.append(asyncio.create_task(app.close_current_result()))
                await super().close()

        loop = asyncio.get_running_loop()
        previous = loop.get_task_factory()
        with patch.object(m, "CurrentResultProducer", Reentrant):
            app.attach_current_result(self.Native())
            loop.set_task_factory(asyncio.eager_task_factory)
            try:
                await app.close_current_result()
                await asyncio.gather(*reentered)
            finally:
                loop.set_task_factory(previous)
        outer.assertEqual(self.trace.count("close:producer1"), 1)
        self.assertEqual(app.metrics()["owned_resources"], 10)

    async def test_invalid_configuration_and_huge_numeric_budgets_are_finite(self):
        for field in ("startup_timeout_s", "cleanup_timeout_s"):
            for value in (True, 0, 10**1000, -(10**1000), float("nan"), float("inf")):
                with (
                    self.subTest(field=field),
                    self.assertRaisesRegex(m.ApplicationError, "^invalid_input$"),
                ):
                    m.ChannelPolicyApplication(self.profile, **{field: value})
        with self.assertRaisesRegex(m.ApplicationError, "^invalid_input$"):
            m.ChannelPolicyApplication(None)
        self.assertEqual(self.trace, [])


class ScanCadenceTests(unittest.TestCase):
    def test_idle_scans_back_off_to_one_second_and_any_work_restores_the_fast_rescan(self):
        idle = ScanObservation(16, 0, 16, 0, 0)
        interval = m.SCAN_INTERVAL_S
        seen = []
        for _ in range(4):
            interval = m.next_scan_interval(interval, idle)
            seen.append(interval)
        self.assertEqual(seen, [0.5, 1.0, 1.0, 1.0])
        for busy in (
            ScanObservation(16, 1, 15, 0, 0),
            ScanObservation(16, 0, 16, 1, 1),
            ScanObservation(16, 0, 16, 0, 1),
        ):
            self.assertEqual(m.next_scan_interval(1.0, busy), m.SCAN_INTERVAL_S)
        for unknown in (None, object(), "idle"):
            self.assertEqual(m.next_scan_interval(1.0, unknown), m.SCAN_INTERVAL_S)


if __name__ == "__main__":
    unittest.main()
