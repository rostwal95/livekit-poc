"""Owned bootstrap fakes and real harmless child lifecycle controls; no database DDL."""

from __future__ import annotations

import asyncio
import base64
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from continuity_lab.api import BookingChange
from continuity_lab.case_control_api import CaseSnapshot
from continuity_lab.postgres_api import CaseProjection, ManagedReceipt
from services.channel_policy_demo.owner_config import read_owner_profile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "channel_policy_setup_tested", ROOT / "local-setup/scripts/channel_policy_setup.py"
)
assert SPEC is not None and SPEC.loader is not None
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)
PRIVATE = "PRIVATE_SETUP_SENTINEL"
RUNTIME = "runtime_synthetic_" + "r" * 32
OWNER = "owner_synthetic_" + "o" * 32


class Managed:
    def __init__(self, fixture):
        self.fixture = fixture
        self.pending_count = self.close_calls = 0
        self.closed = False

    async def submit(self, *, idempotency_key, request):
        self.fixture.events.append(("submit", idempotency_key, request))
        self.fixture.request = request
        return ManagedReceipt(
            True,
            self.fixture.task_id,
            self.fixture.case_id,
            CaseProjection.create(
                {
                    "task_id": self.fixture.task_id,
                    "case_id": self.fixture.case_id,
                    "case_revision": "0",
                }
            ),
        )

    async def close(self):
        self.close_calls += 1
        self.closed = True


class Controller(Managed):
    async def case(self, *, task_id):
        self.fixture.events.append(("case", task_id))
        return self.fixture.snapshot(0, self.fixture.request)

    async def revise(self, *, task_id, expected_revision, request):
        self.fixture.events.append(("revise", task_id, expected_revision, request))
        return self.fixture.snapshot(1, request)


class Node:
    def __init__(self, fixture):
        self.fixture = fixture
        self.calls = []
        self.error = None

    async def upgrade(self, **values):
        self.calls.append(values)
        self.fixture.events.append(("node", values["schema"]))
        if self.error is not None:
            raise self.error
        return self.fixture.receiver_id


class SetupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="channel-setup-test-")
        self.root = Path(self.temp.name).resolve()
        (self.root / ".local").mkdir(mode=0o700)
        (self.root / "services/channel-policy-gateway").mkdir(parents=True)
        self.directory = self.root / ".local/profile"
        self.node = Path(sys.executable).resolve()
        self.database = m.SetupDatabase(15432, RUNTIME, OWNER)
        self.events, self.tasks, self.releases = [], [], []
        self.task_id, self.case_id, self.receiver_id = (str(uuid4()) for _ in range(3))
        self.request = None
        self.managed, self.controller = Managed(self), Controller(self)
        self.migrations = Node(self)
        self.patches = [
            patch.object(
                m,
                "_fresh_namespaces",
                side_effect=lambda settings, schemas: self.events.append(
                    ("fresh", settings, schemas)
                ),
            ),
            patch.object(m, "_install_case", side_effect=self.install_case),
            patch.object(m, "_install_work", side_effect=self.install_work),
            patch(
                "continuity_lab.postgres_api.open_postgres_client", side_effect=self.open_managed
            ),
            patch(
                "continuity_lab.case_control_api.open_case_control_client",
                side_effect=self.open_controller,
            ),
            patch.object(m, "_load_database", side_effect=AssertionError("ambient settings read")),
        ]
        for item in self.patches:
            item.start()

    async def asyncTearDown(self):
        for release in self.releases:
            release.set()
        if self.tasks:
            async with asyncio.timeout(3):
                await asyncio.gather(*self.tasks, return_exceptions=True)
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    async def install_case(self, settings):
        self.events.append(("case_install", settings))

    async def install_work(self, settings):
        self.events.append(("work_install", settings))

    def open_managed(self, **values):
        self.events.append(("managed_open", values))
        return self.managed

    def open_controller(self, **values):
        self.events.append(("controller_open", values))
        return self.controller

    def snapshot(self, revision, request):
        return CaseSnapshot(
            self.task_id,
            "channel_policy_scope",
            "channel_policy_actor",
            revision,
            request,
            None,
            False,
            None,
            "2026-11-13T00:00:00+00:00",
            "2026-11-13T00:00:00+00:00",
            self.case_id,
        )

    def run_setup(self, **changes):
        return m.prepare(
            changes.get("directory", self.directory),
            self.node,
            database=self.database,
            repository=self.root,
            migrations=self.migrations,
        )

    def journals(self):
        return [
            json.loads(path.read_bytes()) for path in sorted(self.directory.glob("setup-*.json"))
        ]

    async def test_full_fake_public_flow_preserves_actual_case_receiver_owner_and_revision(self):
        profile = await self.run_setup()
        self.assertEqual(
            (profile.case.task_id, profile.case.authority_case_id), (self.task_id, self.case_id)
        )
        self.assertEqual(profile.route.receiver_id, self.receiver_id)
        self.assertEqual(profile.app_owner_id, self.journals()[0]["identity"]["app_owner_id"])
        self.assertEqual(self.journals()[-1]["stage"], "prepared")
        self.assertEqual(
            [e[0] for e in self.events],
            [
                "fresh",
                "case_install",
                "work_install",
                "managed_open",
                "controller_open",
                "submit",
                "case",
                "revise",
                "node",
            ],
        )
        submitted = next(e for e in self.events if e[0] == "submit")
        revised = next(e for e in self.events if e[0] == "revise")
        self.assertEqual(submitted[2], BookingChange("DEMO-BK-001", date(2030, 12, 10), True))
        self.assertEqual(revised[2:], (0, BookingChange("DEMO-BK-001", date(2030, 12, 11), True)))
        self.assertTrue(self.managed.closed and self.controller.closed)
        self.assertEqual(self.migrations.calls[0]["owner_password"], OWNER)
        owner_bytes = (self.directory / "owner-profile.json").read_bytes()
        self.assertIn(RUNTIME.encode(), owner_bytes)
        self.assertNotIn(OWNER.encode(), owner_bytes)
        self.assertEqual(read_owner_profile(self.directory / "owner-profile.json"), profile)
        self.assertTrue(profile.database.work_schema.startswith("p1_work_cp45_"))
        node_config = json.loads((self.directory / "node-config.json").read_bytes())
        self.assertEqual(node_config, profile.node_configuration())
        specialist_path = self.directory / "specialist-config.json"
        self.assertEqual(
            json.loads(specialist_path.read_bytes()), profile.specialist_configuration()
        )
        self.assertEqual(stat.S_IMODE(specialist_path.stat().st_mode), 0o600)
        self.assertNotIn(RUNTIME.encode(), specialist_path.read_bytes())
        self.assertNotIn(OWNER.encode(), specialist_path.read_bytes())
        self.assertEqual(len(json.loads(specialist_path.read_bytes())["evidence"]), 3)
        self.assertEqual([policy.template.request_revision for policy in profile.policies], [1, 2])
        self.assertEqual(
            [
                json.loads(policy.bodies[1])["observations"][0]["days_before_arrival"]
                for policy in profile.policies
            ],
            [10, 4],
        )

    async def test_explicit_falsey_injected_node_port_never_falls_back_to_actual_migrations(self):
        class Falsey(Node):
            def __bool__(self):
                return False

        self.migrations = Falsey(self)
        with patch.object(m, "NodeMigrations", side_effect=AssertionError("no implicit authority")):
            profile = await self.run_setup()
        self.assertEqual(
            (profile.route.receiver_id, len(self.migrations.calls)), (self.receiver_id, 1)
        )

    async def test_all_owned_final_files_are_private_single_link_with_no_pending_files(self):
        await self.run_setup()
        self.assertEqual(self.directory.stat().st_mode & 0o777, 0o700)
        for path in self.directory.iterdir():
            with self.subTest(name=path.name):
                self.assertEqual((path.stat().st_mode & 0o777, path.stat().st_nlink), (0o600, 1))
                self.assertFalse(path.name.startswith(".pending"))
                json.loads(path.read_bytes())

    async def test_existing_directory_never_loads_settings_or_repeats_owner_operations(self):
        self.directory.mkdir(mode=0o700)
        marker = self.directory / "preserve.txt"
        marker.write_bytes(b"original")
        with self.assertRaisesRegex(m.SetupError, "^already_exists$"):
            await self.run_setup()
        self.assertEqual((self.events, marker.read_bytes()), ([], b"original"))

    async def test_outside_ignored_root_missing_parent_and_symlink_targets_fail_before_owner_io(
        self,
    ):
        variants = [self.root / "outside", self.root / ".local/missing/profile"]
        link = self.root / ".local/link"
        link.symlink_to(self.root / ".local", target_is_directory=True)
        variants.append(link / "profile")
        for path in variants:
            with self.subTest(path=path.name), self.assertRaises(m.SetupError):
                await self.run_setup(directory=path)
        self.assertEqual(self.events, [])

    async def test_owner_failure_preserves_partial_journal_and_never_continues_or_drops(self):
        with (
            patch.object(m, "_install_case", side_effect=RuntimeError(PRIVATE)),
            self.assertRaisesRegex(m.SetupError, "^unavailable$"),
        ):
            await self.run_setup()
        self.assertEqual([e[0] for e in self.events], ["fresh"])
        self.assertEqual(self.journals()[-1]["stage"], "failed_partial")
        self.assertFalse((self.directory / "owner-profile.json").exists())
        self.assertEqual(len(self.migrations.calls), 0)

    async def test_cancelled_ddl_waiter_retains_actual_thread_before_exit(self):
        self.patches[1].stop()
        from continuity_lab import postgres_migrations as public

        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)
        calls = []

        def install(settings):
            calls.append("install")
            entered.set()
            self.assertTrue(release.wait(2))

        with patch.object(public, "install_schema", side_effect=install):
            task = asyncio.create_task(self.run_setup())
            self.tasks.append(task)
            async with asyncio.timeout(1):
                while not entered.is_set():
                    await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(calls, ["install"])
        self.assertEqual(self.journals()[-1]["stage"], "aborted_unknown")
        self.assertFalse(self.managed.closed)
        self.assertEqual(self.migrations.calls, [])

    async def test_pending_cancel_between_stages_denies_work_and_node_then_fresh_setup_progresses(
        self,
    ):
        self.patches[2].stop()
        from continuity_lab import work_admin as public

        calls = []
        patches = [
            patch.object(
                public,
                "install_work_schema",
                side_effect=lambda *args, **kwargs: calls.append("install"),
            )
        ]
        for item in patches:
            item.start()
        original_publish = m._publish
        try:
            for stage in ("work_install_started", "node_upgrade_started"):
                self.directory = self.root / ".local" / ("cancel-" + stage)
                self.managed, self.controller = Managed(self), Controller(self)
                before = len(calls)

                def publish(path, raw, *, selected=stage):
                    original_publish(path, raw)
                    if json.loads(raw).get("stage") == selected:
                        current = asyncio.current_task()
                        self.assertIsNotNone(current)
                        current.cancel()

                with patch.object(m, "_publish", side_effect=publish):
                    task = asyncio.create_task(self.run_setup())
                    self.tasks.append(task)
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                self.assertEqual(len(calls) - before, 0 if stage == "work_install_started" else 1)
                self.assertEqual(self.migrations.calls, [])
                self.assertEqual(self.journals()[-1]["stage"], "aborted_unknown")
                if stage == "node_upgrade_started":
                    self.assertTrue(self.managed.closed and self.controller.closed)
            self.managed, self.controller = Managed(self), Controller(self)
            fresh = asyncio.create_task(
                self.run_setup(directory=self.root / ".local/fresh-after-cancel")
            )
            self.tasks.append(fresh)
            profile = await fresh
            self.assertEqual(
                (profile.route.receiver_id, len(self.migrations.calls)), (self.receiver_id, 1)
            )
        finally:
            for item in reversed(patches):
                item.stop()

    async def test_cleanup_observer_allocation_failure_retains_both_close_tasks_and_primary_failure(
        self,
    ):
        release = asyncio.Event()
        self.releases.append(release)
        entered = [asyncio.Event(), asyncio.Event()]
        attempts = []

        async def failed_submit(**values):
            attempts.append("submit")
            failure = m.SetupError("invalid_setup")
            failure.args = ("PRIVATE_PRIMARY_BODY",)
            raise failure

        self.managed.submit = failed_submit
        for client, event in zip((self.managed, self.controller), entered, strict=True):

            async def held_close(current=client, ready=event):
                current.close_calls += 1
                current.pending_count = 1
                ready.set()
                try:
                    await release.wait()
                    current.closed = True
                finally:
                    current.pending_count = 0

            client.close = held_close
        original = asyncio.create_task
        failed = []

        def allocate(action):
            if action.cr_code.co_name == "observe" and not failed:
                failed.append(action)
                raise RuntimeError("PRIVATE_OBSERVER_ALLOCATION")
            task = original(action)
            if action.cr_code.co_name == "close":
                self.tasks.append(task)
            return task

        with patch.object(m.asyncio, "create_task", side_effect=allocate):
            opening = original(self.run_setup())
            self.tasks.append(opening)
            try:
                await asyncio.wait_for(asyncio.gather(*(event.wait() for event in entered)), 1)
                await asyncio.sleep(0)
                self.assertFalse(opening.done())
                self.assertEqual((self.managed.close_calls, self.controller.close_calls), (1, 1))
                self.assertFalse(self.managed.closed or self.controller.closed)
                self.assertIsNone(failed[0].cr_frame)
            finally:
                release.set()
            with self.assertRaisesRegex(m.SetupError, "^invalid_setup$"):
                await opening
        self.assertEqual(attempts, ["submit"])
        self.assertTrue(self.managed.closed and self.controller.closed)
        self.assertEqual((self.managed.close_calls, self.controller.close_calls), (1, 1))
        self.managed, self.controller = Managed(self), Controller(self)
        profile = await self.run_setup(directory=self.root / ".local/fresh-after-observer-failure")
        self.assertEqual(profile.route.receiver_id, self.receiver_id)

    async def test_cancelled_late_client_constructor_is_adopted_and_closed_before_propagation(self):
        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)

        def late(**values):
            entered.set()
            self.assertTrue(release.wait(2))
            return self.managed

        with patch("continuity_lab.postgres_api.open_postgres_client", side_effect=late):
            task = asyncio.create_task(self.run_setup())
            self.tasks.append(task)
            async with asyncio.timeout(1):
                while not entered.is_set():
                    await asyncio.sleep(0)
            task.cancel()
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual((self.managed.close_calls, self.controller.close_calls), (1, 0))
        self.assertFalse(any(e[0] == "submit" for e in self.events))
        self.assertEqual(self.migrations.calls, [])

    async def test_corrupt_case_revision_or_action_state_stops_before_node_and_preserves_ids(self):
        original = self.controller.revise

        async def corrupt(**values):
            return replace(await original(**values), revision=0)

        self.controller.revise = corrupt
        with self.assertRaisesRegex(m.SetupError, "^invalid_setup$"):
            await self.run_setup()
        self.assertTrue(self.managed.closed and self.controller.closed)
        self.assertEqual(self.migrations.calls, [])
        self.assertEqual(self.journals()[-1]["identity"]["task_id"], self.task_id)

    async def test_node_failure_retains_real_seed_identity_without_publishing_ready_profile(self):
        self.migrations.error = RuntimeError(PRIVATE)
        with self.assertRaisesRegex(m.SetupError, "^unavailable$"):
            await self.run_setup()
        last = self.journals()[-1]
        self.assertEqual(
            (last["stage"], last["identity"]["task_id"]), ("failed_partial", self.task_id)
        )
        self.assertFalse((self.directory / "owner-profile.json").exists())
        self.assertEqual(len(self.migrations.calls), 1)

    async def test_booking_setup_installs_one_baseline_under_the_owner(self):
        self.patches[1].stop()
        from continuity_lab import postgres_migrations as public

        owner = m._settings(self.database, "cp45_case_" + "c" * 32, owner=True)
        with patch.object(public, "install_schema") as install:
            await m._install_case(owner)
        install.assert_called_once_with(owner)

    async def test_work_installs_one_baseline_with_execution_limits(self):
        self.patches[2].stop()
        from continuity_lab import work_admin as public

        owner = m._settings(self.database, "p1_work_cp45_" + "a" * 32, owner=True)
        with patch.object(public, "install_work_schema") as install:
            await m._install_work(owner)
        install.assert_called_once_with(
            owner, public.WorkLimits(16, 16), execution_limits=public.ExecutionLimits(4, 2, 10_000)
        )

    async def test_case_clients_close_independently_and_retry_failed_observer_without_resubmit(
        self,
    ):
        original_close = self.managed.close
        first = True

        async def failed_close():
            nonlocal first
            if first:
                first = False
                raise RuntimeError(PRIVATE)
            await original_close()

        self.managed.close = failed_close
        await self.run_setup()
        self.assertTrue(self.managed.closed and self.controller.closed)
        self.assertEqual(sum(e[0] == "submit" for e in self.events), 1)
        self.assertIn("cleanup_incomplete", [j["stage"] for j in self.journals()])


class LocalContracts(unittest.TestCase):
    def test_database_credentials_bounds_privacy_and_utf16_limits_are_pure(self):
        database = m.SetupDatabase(15432, RUNTIME, OWNER)
        self.assertNotIn(RUNTIME, repr(database))
        self.assertNotIn(OWNER, repr(database))
        for value in (True, 0, 65536, 10**1000):
            with self.subTest(kind=type(value).__name__), self.assertRaises(m.SetupError):
                m.SetupDatabase(value, RUNTIME, OWNER)
        for value in ("a" * 31, "\ud800" * 40, "😀" * 65, "x" * 129, " " * 32):
            with self.subTest(length=len(value)), self.assertRaises(m.SetupError):
                m.SetupDatabase(15432, value, OWNER)
        self.assertEqual(m.SetupDatabase(15432, "µ" * 32, OWNER).port, 15432)

    def test_atomic_publish_is_complete_on_visibility_and_preserves_existing_final(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            path = directory / "final.json"
            original = os.link
            observed = []

            def link(source, destination, **values):
                self.assertEqual(Path(source).read_bytes(), b'{"complete":true}\n')
                self.assertFalse(Path(destination).exists())
                observed.append(True)
                return original(source, destination, **values)

            with patch.object(m.os, "link", side_effect=link):
                m._publish(path, b'{"complete":true}\n')
            self.assertEqual(observed, [True])
            with self.assertRaises(FileExistsError):
                m._publish(path, b'{"replacement":true}\n')
            self.assertEqual(path.read_bytes(), b'{"complete":true}\n')
            self.assertEqual((path.stat().st_mode & 0o777, path.stat().st_nlink), (0o600, 1))
            self.assertEqual(list(directory.iterdir()), [path])

    def test_pending_collision_never_removes_a_file_this_publication_did_not_create(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            selected = uuid4()
            pending = directory / (".pending-" + selected.hex)
            pending.write_bytes(b"preserve-owned-by-another-call")
            target = directory / "final.json"
            with (
                patch.object(m, "uuid4", return_value=selected),
                self.assertRaises(FileExistsError),
            ):
                m._publish(target, b"{}\n")
            self.assertEqual(pending.read_bytes(), b"preserve-owned-by-another-call")
            self.assertFalse(target.exists())

    def test_plan_parser_and_private_failures_never_open_settings_or_echo_arguments(self):
        with (
            patch.object(m, "_load_database", side_effect=AssertionError("settings")),
            patch.object(m.asyncio, "run", side_effect=AssertionError("event loop")),
            patch.object(os, "getenv", side_effect=AssertionError("environment")),
            patch.object(Path, "read_bytes", side_effect=AssertionError("file")),
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(m.main(["--plan"]), 0)
            value = json.loads(output.getvalue())
            self.assertEqual(value["schemas"], {"booking": 1, "work": 1, "channel": 1})
            self.assertFalse(value["provider_access"])
        for args in (
            [],
            [PRIVATE],
            ["prepare", "--directory", PRIVATE, "--node", "/tmp/" + PRIVATE],
            ["prepare", "--directory", "/tmp/a", "--directory", "/tmp/b"],
        ):
            output, errors = io.StringIO(), io.StringIO()
            with redirect_stdout(output), redirect_stderr(errors):
                self.assertEqual(m.main(args), 2)
            self.assertNotIn(PRIVATE, output.getvalue() + errors.getvalue())
            self.assertEqual(json.loads(output.getvalue())["code"], "invalid_arguments")

    def test_import_is_inert_without_runtime_sdk_or_private_settings(self):
        name = "channel_setup_inert_probe"
        spec = importlib.util.spec_from_file_location(name, m.__file__)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            with (
                patch.object(m.os, "open", side_effect=AssertionError("file")),
                patch.object(m.subprocess, "Popen", side_effect=AssertionError("process")),
                patch.object(m.threading.Thread, "start", side_effect=AssertionError("thread")),
                patch.object(m.Path, "resolve", side_effect=AssertionError("path")),
            ):
                spec.loader.exec_module(module)
        finally:
            sys.modules.pop(name, None)


class OwnedNodeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.processes = []
        self.receiver = str(uuid4())
        self.node = Path(sys.executable).resolve()
        self.original_popen = subprocess.Popen
        self.captured = []

    def child(self, program):
        def opened(arguments, **options):
            self.captured.append((arguments, options))
            process = self.original_popen([sys.executable, "-I", "-c", program], **options)
            self.processes.append(process)
            return process

        return patch.object(m.subprocess, "Popen", side_effect=opened)

    async def upgrade(self, *, started=None):
        return await m.NodeMigrations(started=started).upgrade(
            node=self.node,
            cwd=ROOT / "services/channel-policy-gateway",
            port=15432,
            schema="cp45_channel_" + "b" * 32,
            owner_password=OWNER,
        )

    async def asyncTearDown(self):
        for process in self.processes:
            self.assertIsNotNone(process.returncode)
            with self.assertRaises(ProcessLookupError):
                os.killpg(process.pid, 0)
            for stream in (process.stdin, process.stdout, process.stderr):
                self.assertTrue(stream.closed)

    async def test_actual_child_public_command_closed_owner_only_environment_and_real_return_identity(
        self,
    ):
        program = (
            'import sys,json; p=json.load(sys.stdin); print(json.dumps({"schema_version":1,"receiver_id":"'
            + self.receiver
            + '"},separators=(",",":")))'
        )
        observed = []
        with self.child(program):
            self.assertEqual(await self.upgrade(started=observed.append), self.receiver)
        self.assertEqual(observed, [self.processes[0].pid])
        arguments, options = self.captured[0]
        self.assertIn("@livekit-ecosystem/channel-continuity/migrations", arguments[-1])
        self.assertEqual(
            set(options["env"]),
            {"PATH", "LANG", "CI", "NO_COLOR", "CHANNEL_POLICY_SETUP_OWNER_PASSWORD"},
        )
        self.assertEqual(options["env"]["CHANNEL_POLICY_SETUP_OWNER_PASSWORD"], OWNER)
        self.assertNotIn(RUNTIME, options["env"].values())
        self.assertTrue(options["start_new_session"])

    async def test_real_node_production_environment_gate_and_success_parser_without_database(self):
        node = shutil.which("node")
        self.assertIsNotNone(node)
        self.node = Path(node).resolve()
        module = f"export async function installChannelSchema() {{ return {json.dumps(self.receiver)}; }}"
        # Replace only the imported producers: original environment validation,
        # staged calls, stdout bytes and Python success parsing all execute.
        program = m._NODE_PROGRAM.replace(
            "@livekit-ecosystem/channel-continuity/migrations",
            "data:text/javascript;base64," + base64.b64encode(module.encode()).decode(),
        )
        self.assertNotEqual(program, m._NODE_PROGRAM)

        def opened(arguments, **options):
            options["env"] = {**options["env"], **extra}
            self.captured.append((arguments, options))
            process = self.original_popen(arguments, **options)
            self.processes.append(process)
            return process

        with (
            patch.object(m, "_NODE_PROGRAM", program),
            patch.object(m.subprocess, "Popen", side_effect=opened),
        ):
            extra = {"__CF_USER_TEXT_ENCODING": "0x1F5:0x0:0x0"}
            self.assertEqual(await self.upgrade(), self.receiver)
            for key in ("NODE_OPTIONS", "PGPORT", "OPENAI_API_KEY"):
                with self.subTest(key=key):
                    extra = {key: "" if key == "NODE_OPTIONS" else PRIVATE}
                    with self.assertRaisesRegex(m.SetupError, "^unavailable$"):
                        await self.upgrade()
            # Failed role environments do not poison a fresh valid child.
            extra = {"__CF_USER_TEXT_ENCODING": "0x1F5:0x0:0x0"}
            self.assertEqual(await self.upgrade(), self.receiver)
        self.assertEqual(len(self.processes), 5)

    async def test_real_node_program_persists_dispatch_lease_beyond_joined_step_deadline(self):
        node = shutil.which("node")
        self.assertIsNotNone(node)
        self.node = Path(node).resolve()
        with tempfile.TemporaryDirectory() as name:
            capture = Path(name) / "limits.jsonl"
            module = (
                "import { appendFileSync } from 'node:fs';"
                "export async function installChannelSchema(_settings, limits) {"
                f"appendFileSync({json.dumps(str(capture))}, JSON.stringify(limits));"
                f"return {json.dumps(self.receiver)}; }}"
            )
            program = m._NODE_PROGRAM.replace(
                "@livekit-ecosystem/channel-continuity/migrations",
                "data:text/javascript;base64," + base64.b64encode(module.encode()).decode(),
            )

            def opened(arguments, **options):
                process = self.original_popen(arguments, **options)
                self.processes.append(process)
                return process

            with (
                patch.object(m, "_NODE_PROGRAM", program),
                patch.object(m.subprocess, "Popen", side_effect=opened),
            ):
                self.assertEqual(await self.upgrade(), self.receiver)
            observed = json.loads(capture.read_text())
        self.assertEqual(
            observed["dispatch"],
            {"maxActive": 2, "maxAttempts": 2, "leaseMs": 8000, "retryDelayMs": 100},
        )

    async def test_pending_cancel_direct_node_upgrade_starts_no_child_then_fresh_call_progresses(
        self,
    ):
        async def cancelled():
            current = asyncio.current_task()
            self.assertIsNotNone(current)
            current.cancel()
            return await self.upgrade()

        task = asyncio.create_task(cancelled())
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.processes, [])
        program = (
            'import sys,json;sys.stdin.read();print(json.dumps({"schema_version":1,"receiver_id":"'
            + self.receiver
            + '"},separators=(",",":")))'
        )
        with self.child(program):
            self.assertEqual(await self.upgrade(), self.receiver)

    async def test_task_setup_failure_is_finite_before_any_process_then_valid_child_progresses(
        self,
    ):
        import gc
        import warnings

        actions = []

        def fail(action):
            actions.append(action)
            raise RuntimeError(PRIVATE)

        with warnings.catch_warnings(record=True) as observed:
            warnings.simplefilter("always")
            with (
                patch.object(m.asyncio, "create_task", side_effect=fail),
                self.assertRaisesRegex(m.SetupError, "^unavailable$"),
            ):
                await self.upgrade()
            gc.collect()
        self.assertFalse(
            [warning for warning in observed if issubclass(warning.category, RuntimeWarning)]
        )
        self.assertEqual(self.processes, [])
        self.assertEqual(len(actions), 1)
        self.assertIsNone(actions[0].cr_frame)
        program = (
            'import sys,json;sys.stdin.read();print(json.dumps({"schema_version":1,"receiver_id":"'
            + self.receiver
            + '"},separators=(",",":")))'
        )
        with self.child(program):
            self.assertEqual(await self.upgrade(), self.receiver)

    async def test_capture_overflow_is_finite_and_actual_group_is_reaped(self):
        program = 'import sys;sys.stdin.read();sys.stdout.write("x"*40000);sys.stdout.flush()'
        with self.child(program), self.assertRaisesRegex(m.SetupError, "^unavailable$"):
            await self.upgrade()

    async def test_deadline_reaps_only_owned_sleeping_child_without_dependency_text(self):
        program = "import sys,time;sys.stdin.read();time.sleep(20)"
        with (
            self.child(program),
            patch.object(m, "_NODE_SECONDS", 0.03),
            patch.object(m, "_REAP_SECONDS", 0.1),
            self.assertRaisesRegex(m.SetupError, "^unavailable$"),
        ):
            await self.upgrade()

    async def test_cancellation_retains_actual_thread_and_reaps_child_before_propagating(self):
        program = "import sys,time;sys.stdin.read();time.sleep(20)"
        with self.child(program), patch.object(m, "_REAP_SECONDS", 0.1):
            task = asyncio.create_task(self.upgrade())
            async with asyncio.timeout(1):
                while not self.processes:
                    await asyncio.sleep(0)
            task.cancel()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertIsNotNone(self.processes[0].returncode)


ACCOUNT_TOKEN = "a" * 43
ASSOCIATION_REQUEST = {
    "schema_version": 1,
    "port": 15432,
    "schema": "cp45_channel_" + "c" * 32,
    "tenantId": "tenant_demo",
    "accountId": "account_demo",
    "caseId": "case_demo",
    "conversationId": "conversation_demo",
    "providerAccountId": "joined_sms",
    "senderId": "demo_sms_sender",
}
# Public-module stand-ins: the challenge secret must round-trip through a
# signed LINK body, and the inbox must be closed, or the stub exits non-zero.
_STUB_POSTGRES = """
let issued, closed = false;
export class SeededAccounts { constructor(seeds) { if (seeds.length !== 1 || seeds[0].caseId !== 'case_demo') throw Error(); } }
export class ChannelInbox {
  constructor(settings, integration, accounts, hooks, observer) {
    if (settings.user !== 'livekit_lab' || settings.schema !== 'cp45_channel_' + 'c'.repeat(32)) throw Error();
    if (typeof observer !== 'function') throw Error();
    process.on('exit', () => { if (!closed) process.exitCode = 9; });
  }
  async createChallenge(token, sender) {
    if (sender !== 'demo_sms_sender') throw Error();
    issued = { challengeId: '11111111-2222-4333-8444-555555555555', secret: 's'.repeat(43) };
    return { ...issued, expiresAt: new Date().toISOString() };
  }
  async completeAssociation(raw, headers) {
    const body = JSON.parse(raw).body;
    if (body !== 'LINK ' + issued.challengeId + ' ' + issued.secret || headers.signature !== 'f'.repeat(64)) throw Error();
    return { associationVersion: '7' };
  }
  async close() { closed = true; }
}
"""
_STUB_SECURITY = """
export function createFakeSmsIntegration(scope, key) {
  if (scope.provider !== 'fake_sms' || key.length !== 32 || key[0] !== 0x4f) throw Error();
  return { scope };
}
export function signFakeSms(message, key, timestamp, scope) {
  return { raw: Buffer.from(JSON.stringify(message)), headers: { timestamp: String(timestamp), signature: 'f'.repeat(64) } };
}
"""


def _data_module(source: str) -> str:
    return "data:text/javascript;base64," + base64.b64encode(source.encode()).decode()


class AssociationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        node = shutil.which("node")
        self.assertIsNotNone(node)
        self.node = Path(node).resolve()
        self.processes = []
        self.original_popen = subprocess.Popen

    async def asyncTearDown(self):
        for process in self.processes:
            self.assertIsNotNone(process.returncode)
            with self.assertRaises(ProcessLookupError):
                os.killpg(process.pid, 0)

    def associate(self):
        return m._run_association(
            self.node,
            ROOT / "services/channel-policy-gateway",
            ASSOCIATION_REQUEST,
            RUNTIME,
            ACCOUNT_TOKEN,
            threading.Event(),
        )

    def opened(self, extra):
        def opened(arguments, **options):
            options["env"] = {**options["env"], **extra}
            process = self.original_popen(arguments, **options)
            self.processes.append(process)
            return process

        return opened

    def test_cli_accepts_only_absolute_associate_sms_options(self):
        selected = m._arguments(["associate-sms", "--directory", "/tmp/a", "--node", "/tmp/n"])
        self.assertEqual(selected, ("associate-sms", Path("/tmp/a"), Path("/tmp/n")))
        for args in (
            ["associate-sms", "--directory", "relative", "--node", "/tmp/n"],
            ["associate-sms", "--directory", "/tmp/a", "--directory", "/tmp/b"],
            ["associate", "--directory", "/tmp/a", "--node", "/tmp/n"],
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(m.main(args), 2)
            self.assertEqual(json.loads(output.getvalue())["code"], "invalid_arguments")

    async def test_real_node_program_links_the_issued_challenge_through_public_ports(self):
        program = m._ASSOCIATE_PROGRAM.replace(
            "@livekit-ecosystem/channel-continuity/postgres", _data_module(_STUB_POSTGRES)
        ).replace("@livekit-ecosystem/channel-continuity/security", _data_module(_STUB_SECURITY))
        self.assertNotIn("@livekit-ecosystem", program)
        with (
            patch.object(m, "_ASSOCIATE_PROGRAM", program),
            patch.object(m.subprocess, "Popen", side_effect=self.opened({})),
        ):
            self.assertEqual(await asyncio.to_thread(self.associate), "7")
            for key in ("NODE_OPTIONS", "PGPORT", "OPENAI_API_KEY"):
                with (
                    self.subTest(key=key),
                    patch.object(m.subprocess, "Popen", side_effect=self.opened({key: PRIVATE})),
                    self.assertRaises(m.SetupError),
                ):
                    await asyncio.to_thread(self.associate)

    async def test_observer_lines_or_extra_fields_on_stdout_are_rejected(self):
        for output in (
            '{"component":"channel_inbox"}\n{"schema_version":1,"association_version":"1"}\n',
            '{"schema_version":1,"association_version":"1","token":"x"}\n',
            '{"schema_version":1,"association_version":"01"}\n',
        ):
            program = "process.stdout.write(" + json.dumps(output) + ")"
            with (
                self.subTest(output=output[:24]),
                patch.object(m, "_ASSOCIATE_PROGRAM", program),
                patch.object(m.subprocess, "Popen", side_effect=self.opened({})),
                self.assertRaises((m.SetupError, ValueError)),
            ):
                await asyncio.to_thread(self.associate)


if __name__ == "__main__":
    unittest.main()
