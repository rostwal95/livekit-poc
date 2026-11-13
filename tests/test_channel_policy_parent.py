"""Four fake public owners exercise the actual Parent composition, not services."""

from __future__ import annotations

import asyncio
import dataclasses
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from test_channel_policy_owner_config import fixture

from services.channel_policy_demo import parent as m
from services.channel_policy_demo._bounded_loopback_http import LoopbackEndpoint
from services.channel_policy_demo.native_room_admin import LiveKitAdminSettings
from services.channel_policy_demo.native_room_state import NodeRoomCursor

PRIVATE = "PRIVATE_PARENT_DEPENDENCY"


class ParentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name).resolve()
        self.log, self.instances, self.parents = [], {}, []
        self.holds, self.faults = {}, set()
        self.settings = m.ParentSettings(
            fixture(),
            LiveKitAdminSettings("local_key", "synthetic_admin_secret_" + "x" * 43),
            "k" * 43,
            str(uuid4()),
            self.directory / "rooms",
            Path("/trusted/.venv/bin/python"),
            {"PATH": "/usr/bin:/bin", "LANG": "C"},
        )
        outer = self

        class Owner:
            def __init__(self, label):
                self.label = label
                self.close_calls = 0
                outer.log.append("new:" + label)
                outer.instances.setdefault(label, []).append(self)

            async def close(self):
                self.close_calls += 1
                outer.log.append("close:" + self.label)
                if hold := outer.holds.get("close:" + self.label):
                    await hold.wait()
                if "close:" + self.label in outer.faults:
                    raise RuntimeError(PRIVATE)
                outer.log.append("closed:" + self.label)

        class App(Owner):
            def __init__(self):
                super().__init__("app")

            async def start_sources(self):
                outer.log.append("sources")
                if hold := outer.holds.get("sources"):
                    await hold.wait()
                if "sources" in outer.faults:
                    raise RuntimeError(PRIVATE)

            async def start_executor(self):
                outer.log.append("executor")
                if hold := outer.holds.get("executor"):
                    await hold.wait()
                if "executor" in outer.faults:
                    raise RuntimeError(PRIVATE)

            async def observe_case(self):
                raise AssertionError("not selected")

            async def observe_progress(self):
                raise AssertionError("not selected")

            def attach_current_result(self, native):
                raise AssertionError("no room was started")

            async def close_current_result(self):
                raise AssertionError("no room was started")

        class Rooms(Owner):
            def __init__(self):
                super().__init__("rooms")

            def status(self):
                raise AssertionError("operator not called")

            def is_current(self, command):
                raise AssertionError("operator not called")

            async def start(self, command):
                raise AssertionError("no SFU call")

            async def end(self, command):
                raise AssertionError("no SFU call")

            async def read_current(self, command):
                raise AssertionError("no read selected")

        class Sms(Owner):
            def __init__(self):
                super().__init__("sms")

            async def send(self, command):
                raise AssertionError("no SMS call")

        class Http(Owner):
            def __init__(self):
                super().__init__("http")

            async def start(self, port=0):
                outer.log.append("http:start")
                if hold := outer.holds.get("http:start"):
                    await hold.wait()
                if "http:start" in outer.faults:
                    raise RuntimeError(PRIVATE)
                return LoopbackEndpoint("127.0.0.1", port)

        def app(profile):
            self.assertEqual(profile, self.settings.profile)
            return App()

        def rooms(settings, app, cursor):
            self.assertIs(app, self.instances["app"][0])
            self.assertEqual(cursor, self.cursor)
            return Rooms()

        def sms(route):
            self.assertEqual(route.sender_id, "demo_sms_sender")
            self.assertEqual(
                route.provider_account_id, self.settings.profile.sms_provider_account_id
            )
            if "alias:sms" in self.faults:
                return self.instances["app"][0]
            return Sms()

        def http(operator, bearer):
            self.assertEqual(bearer, self.settings.operator_bearer)
            if "factory:http" in self.faults:
                raise RuntimeError(PRIVATE)
            return Http()

        self.factories = m.ParentFactories(app, rooms, sms, http)
        self.cursor = NodeRoomCursor(str(uuid4()), "0", False)

    async def asyncTearDown(self):
        self.faults.clear()
        for event in self.holds.values():
            event.set()
        async with asyncio.timeout(2):
            for parent in self.parents:
                while not parent.metrics()["closed"]:
                    try:
                        await parent.close()
                    except m.ParentError as error:
                        self.assertEqual(error.code, "cleanup_incomplete")
        self.temporary.cleanup()

    def parent(self, **values):
        result = m.ChannelPolicyParent(self.settings, factories=self.factories, **values)
        self.parents.append(result)
        return result

    async def until(self, predicate):
        async with asyncio.timeout(1):
            while not predicate():
                await asyncio.sleep(0)

    async def ready(self, parent):
        await parent.start_sources()
        return await parent.start(self.cursor)

    async def test_constructor_and_unstarted_close_are_inert(self):
        parent = self.parent()
        self.assertEqual(self.log, [])
        self.assertFalse(parent.ready)
        await parent.close()
        self.assertEqual(self.log, [])
        self.assertEqual(parent.metrics()["owned_resources"], 0)

    async def test_stages_original_cursor_and_closed_dependency_order(self):
        parent = self.parent()
        await parent.start_sources()
        self.assertEqual(set(self.instances), {"app"})
        self.assertFalse(parent.ready)
        endpoint = await parent.start(self.cursor)
        self.assertEqual(endpoint, LoopbackEndpoint("127.0.0.1", 11033))
        self.assertTrue(parent.ready)
        self.assertIs(await parent.start(self.cursor), endpoint)
        self.assertEqual(self.log.count("executor"), 1)
        self.assertEqual(
            {label: len(items) for label, items in self.instances.items()},
            {"app": 1, "rooms": 1, "sms": 1, "http": 1},
        )
        with self.assertRaisesRegex(m.ParentError, "^conflict$"):
            await parent.start(NodeRoomCursor(self.cursor.node_epoch, "1", False))
        await parent.close()
        for label in ("rooms", "sms"):
            self.assertLess(self.log.index("closed:http"), self.log.index("close:" + label))
            self.assertLess(self.log.index("closed:" + label), self.log.index("close:app"))
        self.assertEqual(parent.metrics()["owned_resources"], 0)

    async def test_reentrant_source_factory_close_retains_owner_without_starting_sources(self):
        parent = None
        observers = []
        ordinary = self.factories.app

        def app(profile):
            returned = ordinary(profile)
            observers.append(asyncio.create_task(parent.close(), eager_start=True))
            return returned

        parent = m.ChannelPolicyParent(
            self.settings, factories=dataclasses.replace(self.factories, app=app)
        )
        self.parents.append(parent)
        with self.assertRaisesRegex(m.ParentError, "^closed$"):
            await parent.start_sources()
        await asyncio.gather(*observers)
        self.assertNotIn("sources", self.log)
        self.assertEqual(self.instances["app"][0].close_calls, 1)
        self.assertEqual(parent.metrics()["owned_resources"], 0)
        self.instances.clear()
        fresh = self.parent()
        await self.ready(fresh)
        self.assertTrue(fresh.ready)

    async def test_reentrant_room_factory_close_retains_room_without_sms_or_listener(self):
        parent = None
        observers = []
        ordinary = self.factories.rooms

        def rooms(settings, app, cursor):
            returned = ordinary(settings, app, cursor)
            observers.append(asyncio.create_task(parent.close(), eager_start=True))
            return returned

        parent = m.ChannelPolicyParent(
            self.settings, factories=dataclasses.replace(self.factories, rooms=rooms)
        )
        self.parents.append(parent)
        await parent.start_sources()
        with self.assertRaisesRegex(m.ParentError, "^closed$"):
            await parent.start(self.cursor)
        await asyncio.gather(*observers)
        self.assertNotIn("sms", self.instances)
        self.assertNotIn("http", self.instances)
        self.assertNotIn("http:start", self.log)
        self.assertEqual(self.instances["rooms"][0].close_calls, 1)
        self.assertEqual(self.instances["app"][0].close_calls, 1)
        self.assertEqual(parent.metrics()["owned_resources"], 0)
        # The same configured route remains usable after its actual old owners
        # closed; no old activation or backend resource is substituted.
        self.instances.clear()
        fresh = self.parent()
        await self.ready(fresh)
        self.assertTrue(fresh.ready)

    async def test_cached_sources_do_not_reapply_old_startup_deadline(self):
        parent = self.parent()
        await parent.start_sources()
        parent._source_deadline = asyncio.get_running_loop().time() - 1
        await parent.start_sources()
        self.assertEqual(self.log.count("sources"), 1)
        await parent.start(self.cursor)

    async def test_malformed_colliding_or_early_cursor_allocates_no_extra_owner(self):
        parent = self.parent()
        with self.assertRaisesRegex(m.ParentError, "^unavailable$"):
            await parent.start(self.cursor)
        self.assertEqual(self.log, [])
        await parent.start_sources()
        bad = dataclasses.replace(self.cursor, control_port=self.settings.profile.ports.case)
        for cursor in ({"nodeEpoch": self.cursor.node_epoch}, bad):
            with (
                self.subTest(cursor=type(cursor).__name__),
                self.assertRaisesRegex(m.ParentError, "^invalid_input$"),
            ):
                await parent.start(cursor)
        self.assertEqual(self.log, ["new:app", "sources"])
        await parent.start(self.cursor)

    async def test_observed_nondefault_control_port_is_preserved_without_extra_owner(self):
        parent = self.parent()
        self.cursor = dataclasses.replace(self.cursor, control_port=11129)
        await self.ready(parent)
        self.assertEqual(parent._cursor, self.cursor)
        self.assertTrue(parent.ready)
        self.assertEqual(len(self.instances["rooms"]), 1)

    async def test_cancelled_sources_waiter_keeps_actual_start_and_late_app_owned(self):
        parent = self.parent(cleanup_timeout_s=0.02)
        self.holds["sources"] = asyncio.Event()
        caller = asyncio.create_task(parent.start_sources())
        await self.until(lambda: "sources" in self.log)
        caller.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await caller
        with self.assertRaisesRegex(m.ParentError, "^cleanup_incomplete$"):
            await parent.close()
        self.assertNotIn("close:app", self.log)
        self.assertEqual(parent.metrics()["owned_resources"], 1)
        self.holds["sources"].set()
        await parent.close()
        self.assertEqual(self.instances["app"][0].close_calls, 1)

    async def test_late_http_start_after_cancellation_never_becomes_ready(self):
        parent = self.parent(cleanup_timeout_s=0.02)
        await parent.start_sources()
        self.holds["http:start"] = asyncio.Event()
        caller = asyncio.create_task(parent.start(self.cursor))
        await self.until(lambda: "http:start" in self.log)
        caller.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await caller
        self.assertFalse(parent.ready)
        with self.assertRaisesRegex(m.ParentError, "^cleanup_incomplete$"):
            await parent.close()
        self.assertNotIn("close:rooms", self.log)
        self.holds["http:start"].set()
        await parent.close()
        self.assertEqual(parent.metrics()["owned_resources"], 0)

    async def test_cancelled_close_observer_retains_actual_http_then_drains(self):
        parent = self.parent()
        await self.ready(parent)
        self.holds["close:http"] = asyncio.Event()
        observer = asyncio.create_task(parent.close())
        await self.until(lambda: "close:http" in self.log)
        observer.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await observer
        self.assertFalse(parent.ready)
        self.assertNotIn("close:rooms", self.log)
        self.holds["close:http"].set()
        await parent.close()
        self.assertEqual(self.instances["http"][0].close_calls, 1)

    async def test_failed_http_close_blocks_dependent_owners_until_same_close_retry(self):
        parent = self.parent()
        await self.ready(parent)
        self.faults.add("close:http")
        with self.assertRaisesRegex(m.ParentError, "^cleanup_incomplete$"):
            await parent.close()
        self.assertNotIn("close:rooms", self.log)
        self.assertNotIn("close:app", self.log)
        self.faults.clear()
        await parent.close()
        self.assertEqual(self.instances["http"][0].close_calls, 2)
        self.assertEqual(len(self.instances["http"]), 1)

    async def test_room_close_failure_still_closes_sms_and_retains_shared_app(self):
        parent = self.parent()
        await self.ready(parent)
        self.faults.add("close:rooms")
        with self.assertRaisesRegex(m.ParentError, "^cleanup_incomplete$"):
            await parent.close()
        self.assertIn("closed:sms", self.log)
        self.assertNotIn("close:app", self.log)
        self.faults.clear()
        await parent.close()
        self.assertEqual(self.instances["rooms"][0].close_calls, 2)
        self.assertEqual(self.instances["sms"][0].close_calls, 1)

    async def test_partial_factory_failure_drains_every_returned_owner_once(self):
        parent = self.parent()
        await parent.start_sources()
        self.faults.add("factory:http")
        with self.assertRaisesRegex(m.ParentError, "^unavailable$") as caught:
            await parent.start(self.cursor)
        self.assertNotIn(PRIVATE, str(caught.exception))
        await parent.close()
        self.assertEqual(set(self.instances), {"app", "rooms", "sms"})
        self.assertTrue(all(items[0].close_calls == 1 for items in self.instances.values()))

    async def test_alias_factory_cannot_close_shared_app_as_sms(self):
        parent = self.parent()
        await parent.start_sources()
        self.faults.add("alias:sms")
        with self.assertRaisesRegex(m.ParentError, "^unavailable$"):
            await parent.start(self.cursor)
        await parent.close()
        self.assertEqual(self.instances["app"][0].close_calls, 1)
        self.assertNotIn("sms", self.instances)

    async def test_start_task_allocation_failure_has_no_factory_and_close_can_retry(self):
        parent = self.parent()
        with (
            patch.object(m.asyncio, "create_task", side_effect=RuntimeError(PRIVATE)),
            self.assertRaisesRegex(m.ParentError, "^unavailable$"),
        ):
            await parent.start_sources()
        self.assertEqual(self.log, [])
        await parent.close()
        self.assertEqual(parent.metrics()["owned_resources"], 0)

    async def test_queued_cancel_admits_no_new_factory_and_fresh_call_progresses(self):
        parent = self.parent()

        async def cancelled():
            current = asyncio.current_task()
            current.cancel()
            await parent.start_sources()

        with self.assertRaises(asyncio.CancelledError):
            await asyncio.create_task(cancelled())
        self.assertEqual(self.log, [])
        await self.ready(parent)

    async def test_eager_observation_keeps_single_source_and_operator_owner(self):
        parent = self.parent()
        loop = asyncio.get_running_loop()
        previous = loop.get_task_factory()
        loop.set_task_factory(asyncio.eager_task_factory)
        try:
            await asyncio.gather(parent.start_sources(), parent.start_sources())
            await asyncio.gather(parent.start(self.cursor), parent.start(self.cursor))
            await asyncio.gather(parent.close(), parent.close())
        finally:
            loop.set_task_factory(previous)
        self.assertEqual(self.log.count("new:app"), 1)
        self.assertEqual(self.log.count("new:http"), 1)
        self.assertEqual(self.log.count("close:app"), 1)

    def test_settings_copy_base_and_reject_cross_role_secret_or_fixed_port_alias(self):
        base = {"PATH": "/usr/bin:/bin", "LANG": "C"}
        copied = dataclasses.replace(self.settings, base_environment=base)
        base["LANG"] = "changed"
        self.assertEqual(copied.base_environment["LANG"], "C")
        with self.assertRaises(TypeError):
            copied.base_environment["LANG"] = "changed"
        for value in (
            self.settings.profile.credentials.account_token,
            self.settings.admin.api_secret,
            "bad",
        ):
            with (
                self.subTest(value_length=len(value)),
                self.assertRaisesRegex(m.ParentError, "^invalid_input$"),
            ):
                dataclasses.replace(self.settings, operator_bearer=value)
        with self.assertRaisesRegex(m.ParentError, "^invalid_input$"):
            dataclasses.replace(
                self.settings, base_environment=base | {"OPENAI_API_KEY": "PRIVATE"}
            )
        for name in ("startup_timeout_s", "cleanup_timeout_s"):
            with self.subTest(name=name), self.assertRaisesRegex(m.ParentError, "^invalid_input$"):
                m.ChannelPolicyParent(self.settings, **{name: 10**1000})
        changed_profile = dataclasses.replace(
            self.settings.profile,
            ports=dataclasses.replace(self.settings.profile.ports, case=11033),
        )
        with self.assertRaisesRegex(m.ParentError, "^invalid_input$"):
            dataclasses.replace(self.settings, profile=changed_profile)
        self.assertEqual(self.log, [])

    def test_cold_parent_import_has_no_sdk_provider_or_external_io(self):
        script = "import sys; import services.channel_policy_demo.parent; assert 'livekit.agents' not in sys.modules; assert 'livekit.rtc' not in sys.modules; assert 'openai' not in sys.modules; print('cold_parent_composition_ok')"
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "cold_parent_composition_ok")


if __name__ == "__main__":
    unittest.main()
