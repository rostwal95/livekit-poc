"""Private launcher composition/filesystem controls; fake product ports only."""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import services

ROOT = Path(services.__file__).resolve().parents[1]
# Test helper supplies synthetic data only. Production launcher never imports it.
sys.path.insert(0, str(ROOT / "tests"))
from test_channel_policy_owner_config import fixture

from services.channel_policy_demo._bounded_loopback_http import LoopbackEndpoint

DRAFT = Path(__file__).resolve().parents[1]
SOURCE = DRAFT / "local-setup/scripts/channel_policy_launch.py"
SPEC = importlib.util.spec_from_file_location("_channel_policy_launch", SOURCE)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)
BASE = {"PATH": "/usr/bin:/bin", "LANG": "C"}
SETTINGS = {
    "LIVEKIT_HTTP_PORT": "17880",
    "LIVEKIT_API_KEY": "synthetic_admin",
    "LIVEKIT_API_SECRET": "synthetic_admin_secret_" + "z" * 43,
}


def private(path, raw):
    path.write_bytes(raw)
    path.chmod(0o600)


class PreparedState(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.profile = fixture()
        self.profile_dir = self.root / "profile"
        self.profile_dir.mkdir(mode=0o700)
        self.request = m.LaunchRequest(
            self.root, self.profile_dir / "owner-profile.json", Path("/opt/homebrew/bin/node"), BASE
        )
        from services.channel_policy_demo.owner_config import encode_owner_profile

        private(self.request.profile_path, encode_owner_profile(self.profile))
        private(self.profile_dir / "node-config.json", m.encode(self.profile.node_configuration()))
        private(
            self.profile_dir / "specialist-config.json",
            m.encode(self.profile.specialist_configuration()),
        )
        self.sources = [
            "services/channel-policy-gateway/dist/specialist-serve.js",
            "services/channel-policy-gateway/dist/serve.js",
            "services/channel_policy_demo/parent.py",
            "local-setup/scripts/channel_policy_launch.py",
            "local-setup/scripts/channel_policy_launch_child.py",
            "apps/local-console/vite.channel-policy.config.ts",
            "apps/local-console/dist-channel-policy/channel-policy.html",
        ]
        for relative in self.sources + [".venv/bin/python"]:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic:" + relative)
            if relative == ".venv/bin/python":
                path.chmod(0o700)

    def prepare(self):
        with patch.object(m, "stack_settings", return_value=SETTINGS):
            return m.prepare(self.request)

    def test_prepare_uses_existing_profile_and_publishes_private_closed_state(self):
        prepared = self.prepare()
        self.assertEqual(prepared.admin.url, "http://127.0.0.1:17880")
        self.assertEqual(prepared.profile, self.profile)
        self.assertEqual(prepared.runtime.stat().st_mode & 0o777, 0o700)
        for name in ("operator.json", "active.json", "room-control.json", "native-bridge.json"):
            value = (prepared.runtime / name).stat()
            self.assertEqual((value.st_mode & 0o777, value.st_nlink), (0o600, 1))
        active = json.loads((prepared.runtime / "active.json").read_bytes())
        self.assertEqual(
            set(active), {"schemaVersion", "profileId", "launchId", "pid", "sourceBindings"}
        )
        for relative in self.sources:
            self.assertEqual(
                active["sourceBindings"][relative],
                hashlib.sha256((self.root / relative).read_bytes()).hexdigest(),
            )
        self.assertNotIn(prepared.operator_bearer, json.dumps(active))
        prepared.finish()
        self.assertFalse((prepared.runtime / "active.json").exists())
        self.assertTrue(prepared.operator_file.exists())

    def test_normal_restart_preserves_operator_key_and_static_configs(self):
        first = self.prepare()
        saved = {
            name: (first.runtime / name).read_bytes()
            for name in ("operator.json", "room-control.json", "native-bridge.json")
        }
        first.finish()
        second = self.prepare()
        self.assertNotEqual(first.launch_id, second.launch_id)
        self.assertEqual(first.operator_bearer, second.operator_bearer)
        self.assertEqual(saved, {name: (second.runtime / name).read_bytes() for name in saved})
        second.finish()

    def test_foreign_active_file_is_never_replaced_or_deleted(self):
        first = self.prepare()
        saved = (first.runtime / "active.json").read_bytes()
        with self.assertRaises(m.LaunchError) as caught:
            self.prepare()
        self.assertEqual(caught.exception.code, "already_active")
        self.assertEqual((first.runtime / "active.json").read_bytes(), saved)
        first.finish()

    def test_changed_private_configuration_fails_without_rewrite(self):
        first = self.prepare()
        first.finish()
        path = first.runtime / "room-control.json"
        wrong = m.encode({"schemaVersion": 1, "port": 11029, "recoverBindingId": str(uuid4())})
        private(path, wrong)
        with self.assertRaises(m.LaunchError):
            self.prepare()
        self.assertEqual(path.read_bytes(), wrong)
        self.assertFalse((first.runtime / "active.json").exists())

    def test_broad_permissions_or_symlink_private_state_fails_closed(self):
        first = self.prepare()
        first.finish()
        first.operator_file.chmod(0o644)
        with self.assertRaises(m.LaunchError):
            self.prepare()
        self.assertEqual(first.operator_file.stat().st_mode & 0o777, 0o644)
        first.operator_file.chmod(0o600)
        other = first.runtime / "other.json"
        first.operator_file.rename(other)
        first.operator_file.symlink_to(other)
        with self.assertRaises(m.LaunchError):
            self.prepare()
        self.assertTrue(first.operator_file.is_symlink())

    def test_changed_profile_child_config_is_rejected_before_active(self):
        path = self.profile_dir / "node-config.json"
        wrong = self.profile.node_configuration() | {"private": "PRIVATE"}
        private(path, m.encode(wrong))
        with self.assertRaises(m.LaunchError):
            self.prepare()
        self.assertFalse((self.profile_dir / ".runtime/active.json").exists())

    def test_existing_active_identity_cannot_be_deleted_after_metadata_race(self):
        prepared = self.prepare()
        path = prepared.runtime / "active.json"
        path.chmod(0o644)
        with self.assertRaises(m.LaunchError):
            prepared.finish()
        self.assertTrue(path.exists())
        path.chmod(0o600)
        # Changed ctime cannot be silently accepted as the original descriptor.
        with self.assertRaises(m.LaunchError):
            prepared.finish()
        self.assertTrue(path.exists())

    def test_private_read_detects_same_size_mutation(self):
        prepared = self.prepare()
        path = prepared.operator_file
        original = os.read
        changed = False

        def read(fd, length):
            nonlocal changed
            result = original(fd, length)
            if not changed:
                changed = True
                raw = path.read_bytes()
                path.write_bytes(raw.replace(b'"schemaVersion":1', b'"schemaVersion":2'))
            return result

        with patch.object(m.os, "read", read), self.assertRaises(m.LaunchError):
            m.read_private(path)
        self.assertTrue(path.exists())
        prepared.finish()

    def test_publish_never_overwrites_and_leaves_no_owned_pending_file(self):
        directory = self.profile_dir
        path = directory / "immutable.json"
        private(path, b"original")
        with self.assertRaises(FileExistsError):
            m.publish(path, b"replacement")
        self.assertEqual(path.read_bytes(), b"original")
        self.assertEqual(list(directory.glob(".pending-*")), [])

    def test_source_identity_rejects_links_and_requires_prebuilt_ui(self):
        path = self.root / self.sources[-1]
        path.unlink()
        with self.assertRaises(m.LaunchError):
            self.prepare()
        request = dataclasses.replace(self.request, no_ui=True)
        with patch.object(m, "stack_settings", return_value=SETTINGS):
            prepared = m.prepare(request)
        self.assertNotIn(self.sources[-1], prepared.sources)
        prepared.finish()

    def test_main_plan_and_cold_import_never_load_services_or_configuration(self):
        script = """import importlib.util,sys,pathlib,os
spec=importlib.util.spec_from_file_location('inert_launch',sys.argv[1]);m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
def audit(event,args):
 if event in ('open','os.listdir','os.scandir','socket.__new__','subprocess.Popen','os.system'):raise RuntimeError('FORBIDDEN_IO')
sys.addaudithook(audit)
assert not any(name.startswith(('livekit','services','continuity_lab','channel_continuity','delegation_reliability')) for name in sys.modules)
raise SystemExit(m.main(['--plan']))
"""
        completed = subprocess.run(
            [str(ROOT / ".venv/bin/python"), "-I", "-B", "-c", script, str(SOURCE)],
            capture_output=True,
            timeout=5,
            env=BASE,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        value = json.loads(completed.stdout)
        self.assertEqual(
            (value["childrenMaximum"], value["startupSeconds"], value["shutdownSeconds"]),
            (3, 60, 60),
        )
        self.assertFalse(value["servingDDL"] or value["providerFiles"] or value["providerCalls"])

    def test_main_invalid_arguments_are_finite_without_environment_access(self):
        from io import StringIO

        for arguments in (
            [],
            ["serve"],
            ["serve", "--profile", "relative", "--node", "/node"],
            ["serve", "--node", "/node", "--profile", "/profile"],
        ):
            out = StringIO()
            with patch.object(m.sys, "stdout", out):
                result = m.main(arguments)
            self.assertEqual(result, 2)
            self.assertNotIn("Traceback", out.getvalue())
            self.assertEqual(json.loads(out.getvalue())["status"], "unavailable")


class Composition(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.state = PreparedState(
            methodName="test_prepare_uses_existing_profile_and_publishes_private_closed_state"
        )
        self.state.setUp()
        self.request = self.state.request
        self.log, self.children, self.launchers = [], {}, []
        self.holds, self.faults = {}, set()
        self.prepare_release, self.prepare_started = threading.Event(), threading.Event()
        self.cursor_epoch = str(uuid4())
        outer = self

        class Parent:
            async def start_sources(self):
                outer.log.append("sources")
                if "sources" in outer.holds:
                    await outer.holds["sources"].wait()

            async def start(self, cursor):
                outer.log.append("parent:start")
                outer.cursor = cursor
                return LoopbackEndpoint("127.0.0.1", 11033)

            async def close(self):
                outer.log.append("parent:close")
                if "parent:close" in outer.holds:
                    await outer.holds["parent:close"].wait()
                if "parent:close" in outer.faults:
                    raise RuntimeError("PRIVATE_PARENT")

        class Child:
            def __init__(self, spec):
                self.spec, self.closed = spec, asyncio.Event()
                outer.children[spec.role] = self
                outer.log.append(spec.role + ":new")

            async def start(self):
                outer.log.append(self.spec.role + ":start")

            async def wait_ready(self, deadline):
                outer.log.append(self.spec.role + ":ready")
                if self.spec.role + ":ready" in outer.holds:
                    await outer.holds[self.spec.role + ":ready"].wait()
                if self.spec.role + ":ready" in outer.faults:
                    raise RuntimeError("PRIVATE_CHILD")
                return (
                    {
                        "roomControl": {
                            "nodeEpoch": outer.cursor_epoch,
                            "generation": "7",
                            "recoveryRequired": False,
                        }
                    }
                    if self.spec.role == "gateway"
                    else {}
                )

            async def wait_terminal(self):
                await self.closed.wait()

            async def close(self):
                outer.log.append(self.spec.role + ":close")
                if self.spec.role + ":close" in outer.holds:
                    await outer.holds[self.spec.role + ":close"].wait()
                if self.spec.role + ":close" in outer.faults:
                    raise RuntimeError("PRIVATE_CHILD")
                self.closed.set()

            def facts(self):
                closed = self.closed.is_set()
                graceful = closed and self.spec.role + ":abnormal" not in outer.faults
                return {
                    "role": self.spec.role,
                    "reaped": closed,
                    "groupAbsent": closed,
                    "returncode": 0 if graceful else 143 if closed else None,
                    "closedFrameObserved": graceful,
                    "gracefulClosed": graceful,
                    "failed": closed and not graceful,
                }

        def prepare(request):
            self.prepare_started.set()
            if "prepare" in self.faults:
                self.prepare_release.wait(3)
            with patch.object(m, "stack_settings", return_value=SETTINGS):
                return m.prepare(request)

        def parent(settings):
            self.log.append("parent:new")
            self.assertEqual(settings.admin.rtc_url, "ws://127.0.0.1:17880")
            self.assertEqual(
                settings.python_executable, self.request.repository / ".venv/bin/python"
            )
            return Parent()

        self.factories = m.LaunchFactories(prepare, parent, Child)

    async def asyncTearDown(self):
        self.prepare_release.set()
        self.faults.clear()
        for value in self.holds.values():
            value.set()
        async with asyncio.timeout(4):
            for launcher in self.launchers:
                while launcher.status()["status"] != "closed":
                    try:
                        await launcher.close()
                    except m.LaunchError:
                        await asyncio.sleep(0)
        self.state.doCleanups()

    def launcher(self, **values):
        launcher = m.JoinedLauncher(
            dataclasses.replace(self.request, **values), factories=self.factories
        )
        self.launchers.append(launcher)
        return launcher

    async def until(self, predicate):
        async with asyncio.timeout(1):
            while not predicate():
                await asyncio.sleep(0)

    async def test_sources_specialist_gateway_observed_cursor_parent_then_preview(self):
        launcher = self.launcher()
        await launcher.start()
        self.assertEqual(
            self.log,
            [
                "parent:new",
                "sources",
                "specialist:new",
                "specialist:start",
                "specialist:ready",
                "gateway:new",
                "gateway:start",
                "gateway:ready",
                "parent:start",
                "ui:new",
                "ui:start",
                "ui:ready",
            ],
        )
        self.assertEqual((self.cursor.node_epoch, self.cursor.generation), (self.cursor_epoch, "7"))
        self.assertEqual(launcher.status()["status"], "ready")
        self.assertNotIn(launcher._prepared.operator_bearer, json.dumps(launcher.status()))
        await launcher.close()
        self.assertEqual(
            self.log[-4:], ["ui:close", "parent:close", "gateway:close", "specialist:close"]
        )
        self.assertFalse((launcher._prepared.runtime / "active.json").exists())

    async def test_no_ui_has_only_two_node_roles(self):
        launcher = self.launcher(no_ui=True)
        await launcher.start()
        self.assertEqual(set(self.children), {"specialist", "gateway"})
        self.assertIsNone(launcher.status()["uiUrl"])
        await launcher.close()

    async def test_cancelled_start_waiter_keeps_offloaded_preparation_owned(self):
        self.faults.add("prepare")
        launcher = self.launcher()
        waiter = asyncio.create_task(launcher.start())
        await self.until(self.prepare_started.is_set)
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiter
        closer = asyncio.create_task(launcher.close())
        await asyncio.sleep(0)
        self.assertFalse(closer.done())
        self.prepare_release.set()
        await closer
        self.assertNotIn("parent:new", self.log)
        self.assertIsNotNone(launcher._prepared)
        self.assertFalse((launcher._prepared.runtime / "active.json").exists())

    async def test_stop_fences_parent_while_actual_sources_are_held(self):
        self.holds["sources"] = asyncio.Event()
        launcher = self.launcher()
        opening = asyncio.create_task(launcher.start())
        await self.until(lambda: "sources" in self.log)
        closer = asyncio.create_task(launcher.close())
        await self.until(lambda: "parent:close" in self.log)
        self.assertFalse(closer.done())
        self.assertFalse(self.children)
        self.holds["sources"].set()
        await closer
        with self.assertRaises(m.LaunchError):
            await opening
        self.assertFalse(self.children)

    async def test_failed_parent_close_blocks_node_dependency_and_marker_removal(self):
        launcher = self.launcher()
        await launcher.start()
        self.faults.add("parent:close")
        with self.assertRaises(m.LaunchError) as caught:
            await launcher.close()
        self.assertEqual(caught.exception.code, "cleanup_incomplete")
        self.assertTrue((launcher._prepared.runtime / "active.json").exists())
        self.assertNotIn("gateway:close", self.log)
        self.faults.remove("parent:close")
        await launcher.close()
        self.assertEqual(launcher.status()["status"], "closed")
        self.assertFalse((launcher._prepared.runtime / "active.json").exists())

    async def test_startup_failure_retains_original_children_and_safe_diagnostics(self):
        launcher = self.launcher()
        self.faults.add("gateway:ready")
        with self.assertRaises(m.LaunchError) as caught:
            await launcher.start()
        self.assertEqual(str(caught.exception), "unavailable")
        self.assertNotIn("PRIVATE", str(caught.exception))
        self.assertNotIn("parent:start", self.log)
        await launcher.close()
        self.assertTrue(all(value.closed.is_set() for value in self.children.values()))

    async def test_child_terminal_observation_fences_new_start_and_reports_failure(self):
        launcher = self.launcher()
        await launcher.start()
        self.children["gateway"].closed.set()
        await launcher.wait_terminal()
        self.assertEqual(len(self.children), 3)
        await launcher.close()

    async def test_cleanup_allocation_failure_keeps_known_owners_and_allows_retry(self):
        launcher = self.launcher()
        await launcher.start()
        original = m.asyncio.create_task

        def fail(action, **kwargs):
            raise RuntimeError("PRIVATE_ALLOCATION")

        with (
            patch.object(m.asyncio, "create_task", fail),
            self.assertRaises(m.LaunchError) as caught,
        ):
            await launcher.close()
        self.assertEqual(caught.exception.code, "cleanup_incomplete")
        self.assertTrue((launcher._prepared.runtime / "active.json").exists())
        self.assertFalse(any(value.closed.is_set() for value in self.children.values()))
        self.assertIs(m.asyncio.create_task, original)
        await launcher.close()

    async def test_original_sixty_second_shutdown_observer_is_not_renewed_on_retry(self):
        launcher = self.launcher()
        await launcher.start()
        self.faults.add("parent:close")
        with self.assertRaises(m.LaunchError):
            await launcher.close()
        original = launcher._deadline
        with self.assertRaises(m.LaunchError):
            await launcher.close()
        self.assertEqual(launcher._deadline, original)
        self.faults.remove("parent:close")
        await launcher.close()

    async def test_held_ui_close_fences_parent_before_waiting_for_ui(self):
        launcher = self.launcher()
        await launcher.start()
        self.holds["ui:close"] = asyncio.Event()
        closing = asyncio.create_task(launcher.close())
        await self.until(lambda: "parent:close" in self.log)
        self.assertIn("ui:close", self.log)
        self.assertFalse(closing.done())
        self.assertNotIn("gateway:close", self.log)
        self.assertTrue((launcher._prepared.runtime / "active.json").exists())
        self.holds["ui:close"].set()
        await closing
        self.assertTrue(self.children["ui"].closed.is_set())

    async def test_reentrant_ui_factory_late_owner_is_closed_before_dependencies(self):
        original_factory = self.factories.child
        original_task = m.task
        launcher = self.launcher()
        close_observers = []

        def allocate(action, *, cleanup=False):
            if cleanup and action.cr_code.co_name == "_drain":
                actual = asyncio.create_task(action, eager_start=True)
                actual.add_done_callback(
                    lambda done: None if done.cancelled() else done.exception()
                )
                return actual
            return original_task(action, cleanup=cleanup)

        def child(spec):
            if spec.role == "ui":
                close_observers.append(asyncio.create_task(launcher.close(), eager_start=True))
            return original_factory(spec)

        launcher._factories = dataclasses.replace(self.factories, child=child)
        with patch.object(m, "task", allocate):
            with self.assertRaises(m.LaunchError):
                await launcher.start()
            async with asyncio.timeout(1):
                await close_observers[0]
        self.assertTrue(self.children["ui"].closed.is_set())
        self.assertNotIn("ui:start", self.log)
        self.assertLess(self.log.index("ui:close"), self.log.index("gateway:close"))
        self.assertFalse((launcher._prepared.runtime / "active.json").exists())
        # The same immutable state can make useful progress under a fresh owner.
        self.log.clear()
        fresh = self.launcher()
        await fresh.start()
        await fresh.close()
        self.assertEqual(fresh.status()["status"], "closed")

    async def test_cli_quality_failure_still_drains_every_physical_owner(self):
        from io import StringIO

        loop = asyncio.get_running_loop()
        for abnormal in (False, True):
            with self.subTest(abnormal=abnormal):
                if abnormal:
                    self.faults.add("ui:abnormal")
                launcher = self.launcher()
                callbacks = []
                output = StringIO()
                with (
                    patch.object(m, "JoinedLauncher", return_value=launcher),
                    patch.object(
                        loop,
                        "add_signal_handler",
                        side_effect=lambda _signal, callback, values=callbacks: values.append(
                            callback
                        ),
                    ),
                    patch.object(loop, "remove_signal_handler", return_value=True),
                    patch.object(m.sys, "stdout", output),
                ):
                    serving = asyncio.create_task(m.serve(self.request))
                    await self.until(
                        lambda owner=launcher, values=callbacks: (
                            owner.status()["status"] == "ready" and values
                        )
                    )
                    callbacks[0]()
                    code = await serving
                self.assertEqual(code, 1 if abnormal else 0)
                self.assertTrue(all(child.closed.is_set() for child in self.children.values()))
                self.assertIn("parent:close", self.log)
                self.assertIn("gateway:close", self.log)
                self.assertIn("specialist:close", self.log)
                self.assertFalse((launcher._prepared.runtime / "active.json").exists())
                final = json.loads(output.getvalue().splitlines()[-1])
                ui = next(row for row in final["children"] if row["role"] == "ui")
                self.assertEqual(ui["gracefulClosed"], not abnormal)
                self.assertEqual(final["status"], "closed")

    async def test_queued_cancellation_does_not_allocate_prepare_or_children(self):
        launcher = self.launcher()

        async def cancelled():
            asyncio.current_task().cancel()
            await launcher.start()

        with self.assertRaises(asyncio.CancelledError):
            await asyncio.create_task(cancelled())
        self.assertFalse(self.prepare_started.is_set())
        self.assertFalse(self.children)
        await launcher.close()
