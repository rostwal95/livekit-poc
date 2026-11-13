"""Offline ownership tests for the separate installed-public-P1 fixture."""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "p2_starter_p1_under_test", ROOT / "local-setup/scripts/p2_starter_p1.py"
)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


class P1StarterFixtureTests(unittest.TestCase):
    def observer(self, directory, child=None, publish=None, signal_group=None):
        self.child = child or SimpleNamespace(
            pid=410041,
            returncode=0,
            stdout=io.BytesIO(),
            stderr=io.BytesIO(),
            poll=lambda: 0,
            wait=lambda timeout: 0,
        )

        def absent(pid, sig):
            raise ProcessLookupError

        return m.CapturedSteps(
            directory,
            "a" * 32,
            "exact-mutation",
            Path(sys.executable).resolve(),
            spawn=lambda *args, **kwargs: self.child,
            publish_record=publish or m.publish,
            signal_group=signal_group or absent,
        )

    def kwargs(self):
        env = {key: "synthetic-private" for key in m.STEP_CHILD_ENV}
        env.update(
            P1_POSTGRES_HOST="127.0.0.1",
            P1_POSTGRES_DB="livekit_lab",
            P1_POSTGRES_USER="livekit_lab",
            P1_WORKER_SUPPLIER_MODE="cooperating",
        )
        return {
            "env": env,
            "cwd": tempfile.gettempdir(),
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "start_new_session": True,
        }

    def test_plan_is_six_separate_and_no_P1_import_or_worker_call(self):
        output = io.StringIO()
        with (
            patch.object(m, "public_worker_once", side_effect=AssertionError("no worker")),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(m.main(["--plan"]), 0)
        value = json.loads(output.getvalue())
        self.assertEqual(len(value["groups"]), 6)
        self.assertEqual(value["standaloneGroups"], 0)
        self.assertFalse(value["measurementStarted"])
        self.assertEqual(
            value["revisionAcknowledgement"], "application_reply_hold_not_command_receipt"
        )

    def test_installed_venv_interpreter_path_is_preserved_not_resolved_to_base(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            executable = root / "python"
            executable.symlink_to(Path(sys.executable).resolve())
            observer = m.CapturedSteps(
                root, "a" * 32, "exact-mutation", executable, spawn=lambda *args, **kwargs: None
            )
            self.assertEqual(observer.argv[0], str(executable))
            self.assertNotEqual(observer.argv[0], str(executable.resolve()))

    def test_atomic_publication_is_complete_exclusive_private(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            target = root / "step.json"
            m.publish(target, b'{"schemaVersion":1}')
            self.assertEqual(target.read_bytes(), b'{"schemaVersion":1}')
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(target.stat().st_nlink, 1)
            self.assertEqual(list(root.glob("*.pending")), [])
            with self.assertRaises(OSError):
                m.publish(target, b"replacement")
            self.assertEqual(target.read_bytes(), b'{"schemaVersion":1}')

    def test_publication_rejects_linked_parent_and_existing_link(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            real = root / "real"
            real.mkdir(mode=0o700)
            link = root / "linked"
            link.symlink_to(real, target_is_directory=True)
            with self.assertRaises(m.FixtureError):
                m.publish(link / "x", b"x")
            target = real / "x"
            target.symlink_to(root / "foreign")
            with self.assertRaises(OSError):
                m.publish(target, b"x")
            self.assertFalse((root / "foreign").exists())

    def test_only_exact_public_worker_argv_and_child_environment_can_spawn(self):
        with tempfile.TemporaryDirectory() as directory:
            observer = self.observer(Path(directory).resolve())
            for wrong in (["/bin/sh"], [*observer.argv, "extra"]):
                with self.assertRaises(m.FixtureError):
                    observer.observed_spawn(wrong, **self.kwargs())
            args = self.kwargs()
            args["env"]["OPENAI_API_KEY"] = "not-allowed"
            with self.assertRaises(m.FixtureError):
                observer.observed_spawn(observer.argv, **args)
            args = self.kwargs()
            args["start_new_session"] = False
            with self.assertRaises(m.FixtureError):
                observer.observed_spawn(observer.argv, **args)
            self.assertEqual(observer.steps, [])

    def test_actual_handle_is_registered_before_fallible_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            seen = []

            def broken_publish(path, raw):
                seen.append(len(observer.steps))
                raise OSError("synthetic publication failure")

            observer = self.observer(Path(directory).resolve(), publish=broken_publish)
            with self.assertRaises(OSError):
                observer.observed_spawn(observer.argv, **self.kwargs())
            self.assertEqual(seen, [1])
            self.assertIs(observer.steps[0].handle, self.child)
            self.assertTrue(observer.close(time.monotonic() + 1))

    def test_second_child_is_rejected_without_clamping_or_replacing_first_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            observer = self.observer(Path(directory).resolve())
            observer.observed_spawn(observer.argv, **self.kwargs())
            with self.assertRaises(m.FixtureError):
                observer.observed_spawn(observer.argv, **self.kwargs())
            self.assertEqual(len(observer.steps), 1)
            self.assertTrue(observer.close(time.monotonic() + 1))

    def test_group_EPERM_is_never_absence_and_reaped_PID_is_not_signalled(self):
        with tempfile.TemporaryDirectory() as directory:
            signals = []

            def ambiguous(pid, sig):
                signals.append(sig)
                raise PermissionError

            observer = self.observer(Path(directory).resolve(), signal_group=ambiguous)
            observer.observed_spawn(observer.argv, **self.kwargs())
            self.assertFalse(observer.close(time.monotonic()))
            self.assertTrue(signals)
            self.assertEqual(set(signals), {0})
            self.assertFalse(observer.steps[0].group_absent)

    def test_live_captured_owner_is_signalled_reaped_and_group_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            signals = []
            child = SimpleNamespace(pid=410041, returncode=None, stdout=None, stderr=None)
            child.poll = lambda: child.returncode

            def wait(timeout):
                child.returncode = -15
                return -15

            child.wait = wait

            def signal_group(pid, sig):
                signals.append((pid, sig))
                if child.returncode is not None:
                    raise ProcessLookupError

            observer = self.observer(
                Path(directory).resolve(), child=child, signal_group=signal_group
            )
            observer.observed_spawn(observer.argv, **self.kwargs())
            self.assertTrue(observer.close(time.monotonic() + 1))
            self.assertIn((410041, 15), signals)
            self.assertTrue(observer.steps[0].group_absent)

    def test_worker_primary_survives_diagnostic_failure_and_patch_is_restored(self):
        with tempfile.TemporaryDirectory() as directory:
            original = subprocess.Popen

            def broken_publish(path, raw):
                raise OSError("secondary")

            observer = self.observer(Path(directory).resolve(), publish=broken_publish)
            primary = RuntimeError("private-primary")

            def invoke():
                raise primary

            with self.assertRaises(RuntimeError) as caught:
                m.public_worker_once(observer, invoke=invoke)
            self.assertIs(caught.exception, primary)
            self.assertIs(subprocess.Popen, original)

    def test_worker_result_requires_exact_one_settled_zero_exit_step(self):
        with tempfile.TemporaryDirectory() as directory:
            observer = self.observer(Path(directory).resolve())

            def invoke():
                observer.observed_spawn(observer.argv, **self.kwargs())
                return 0

            value = m.public_worker_once(observer, invoke=invoke)
            self.assertTrue(value["cleanupComplete"])
            self.assertEqual(len(value["steps"]), 1)
            self.assertEqual(value["steps"][0]["returnCode"], 0)
            self.assertNotIn("synthetic-private", json.dumps(value))

    def test_zero_step_worker_cannot_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            observer = self.observer(Path(directory).resolve())
            with self.assertRaises(m.FixtureError):
                m.public_worker_once(observer, invoke=lambda: 0)

    def test_installed_module_requires_physical_declared_venv_not_checkout_link(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            installed = root / "env"
            installed.mkdir()
            module = installed / "public.py"
            module.write_text("# public\n")
            m.installed_module(module, installed)
            outside = root / "checkout.py"
            outside.write_text("# checkout\n")
            link = installed / "linked.py"
            link.symlink_to(outside)
            for path in (outside, link):
                with self.assertRaises(m.FixtureError):
                    m.installed_module(path, installed)


class P1PublicFactoryLifetimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_factory_waiter_retains_late_owner_before_close(self):
        owners = m.PublicFactoryOwners()
        entered, release = threading.Event(), threading.Event()
        closed = []

        async def close():
            closed.append(True)

        client = SimpleNamespace(pending_count=0, close=close)

        def factory():
            entered.set()
            release.wait(2)
            return client

        caller = asyncio.create_task(owners.open(factory))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 1))
            caller.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await caller
            self.assertFalse(await owners.close(time.monotonic() + 0.01))
            self.assertEqual(closed, [])
            self.assertEqual(len(owners.pending), 1)
        finally:
            release.set()
            self.assertTrue(await owners.close(time.monotonic() + 1))
        self.assertEqual(closed, [True])
        self.assertTrue(await owners.close(time.monotonic() + 1))
        self.assertEqual(closed, [True])

    async def test_ignored_close_is_one_retained_future_and_later_progress(self):
        owners = m.PublicFactoryOwners()
        release = asyncio.Event()
        count = []

        async def close():
            count.append(True)
            await release.wait()

        client = SimpleNamespace(pending_count=0, close=close)
        owners.clients.append(client)
        try:
            for _ in range(3):
                self.assertFalse(await owners.close(time.monotonic() + 0.005))
            self.assertEqual(count, [True])
            self.assertEqual(len(owners.close_tasks), 1)
        finally:
            release.set()
            self.assertTrue(await owners.close(time.monotonic() + 1))
        self.assertEqual(count, [True])

    async def test_independent_close_attempts_preserve_failed_owner_for_retry(self):
        owners = m.PublicFactoryOwners()
        calls = []

        async def broken():
            calls.append("broken")
            raise RuntimeError("synthetic")

        async def good():
            calls.append("good")

        first, second = (
            SimpleNamespace(pending_count=1, close=broken),
            SimpleNamespace(pending_count=0, close=good),
        )
        owners.clients.extend([first, second])
        self.assertFalse(await owners.close(time.monotonic() + 1))
        self.assertCountEqual(calls, ["broken", "good"])

        async def settled():
            calls.append("settled")
            first.pending_count = 0

        first.close = settled
        self.assertTrue(await owners.close(time.monotonic() + 1))
        self.assertEqual(calls.count("good"), 1)

    async def test_public_factory_capacity_is_reserved_before_another_constructor(self):
        owners = m.PublicFactoryOwners()
        owners.admitted = 9
        calls = []
        with self.assertRaises(m.FixtureError):
            await owners.open(lambda: calls.append(True))
        self.assertEqual(calls, [])
        self.assertEqual(len(owners.pending), 0)

    async def test_independent_bridge_close_observers_retry_before_readers_are_released(self):
        calls = []

        async def first():
            calls.append("first")
            if calls.count("first") == 1:
                raise RuntimeError("known observer timeout")

        async def second():
            calls.append("second")

        self.assertTrue(
            await m.close_bridge_tier(
                [SimpleNamespace(close=first), SimpleNamespace(close=second)], time.monotonic() + 1
            )
        )
        self.assertEqual(calls.count("first"), 2)
        self.assertEqual(calls.count("second"), 1)

    async def test_actual_held_bridge_close_is_retained_not_cancelled_at_deadline(self):
        release = asyncio.Event()
        entered = asyncio.Event()
        cancelled = []

        async def held():
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.append(True)
                raise

        try:
            self.assertFalse(
                await m.close_bridge_tier([SimpleNamespace(close=held)], time.monotonic() + 0.01)
            )
            self.assertTrue(entered.is_set())
            self.assertEqual(cancelled, [])
        finally:
            release.set()
            await asyncio.sleep(0)
        self.assertEqual(cancelled, [])

    async def test_verify_requests_supported_full_public_page_limit_and_closes_all_clients(self):
        from continuity_lab import postgres_api

        queries = []
        closed = []
        published = []

        async def get(*, task_id, limit, cursor):
            self.assertEqual(limit, 50)
            self.assertIsNone(cursor)
            queries.append(task_id)
            return SimpleNamespace(payload=lambda: {"has_more": False, "history_truncated": False})

        async def close():
            closed.append(True)

        with tempfile.TemporaryDirectory() as directory:
            current = SimpleNamespace(
                directory=Path(directory),
                owner="a" * 32,
                credentials={
                    "p1Tokens": {slot: "A" * 43 for slot in ("revision", "stale", "exact")}
                },
                actor=lambda: "synthetic_actor",
                scope=lambda slot: "scope_" + slot,
                settings=lambda: None,
                supplier=lambda slot: Path(directory) / (slot + ".sqlite3"),
            )
            original = {
                "schemaVersion": 1,
                "owner": current.owner,
                "slots": {
                    slot: {"task_id": slot + "-task"} for slot in ("revision", "stale", "exact")
                },
            }

            def factory(**kwargs):
                return SimpleNamespace(get=get, close=close, pending_count=0)

            with (
                patch.object(m, "_public_modules"),
                patch.object(m, "read_data", return_value=original),
                patch.object(postgres_api, "open_postgres_client", side_effect=factory),
                patch.object(
                    m, "publish", side_effect=lambda path, raw: published.append((path, raw))
                ),
            ):
                result = await m.public_phase(current, "verify")
            self.assertEqual(result["status"], "passed")
            self.assertEqual(queries, ["revision-task", "stale-task", "exact-task"])
            self.assertEqual(len(closed), 3)
            self.assertEqual(len(published), 1)

    async def test_verify_rejects_more_or_truncated_or_missing_flags_without_publishing(self):
        from continuity_lab import postgres_api

        for payload in (
            {"has_more": True, "history_truncated": False},
            {"has_more": False, "history_truncated": True},
            {"has_more": False},
            {"has_more": 0, "history_truncated": False},
        ):
            closed = []

            async def get(*, task_id, limit, cursor, result=payload):
                self.assertEqual(limit, 50)
                return SimpleNamespace(payload=lambda: result)

            async def close(records=closed):
                records.append(True)

            with tempfile.TemporaryDirectory() as directory:
                current = SimpleNamespace(
                    directory=Path(directory),
                    owner="a" * 32,
                    credentials={
                        "p1Tokens": {slot: "A" * 43 for slot in ("revision", "stale", "exact")}
                    },
                    actor=lambda: "synthetic_actor",
                    scope=lambda slot: "scope_" + slot,
                    settings=lambda: None,
                    supplier=lambda slot: Path(directory) / (slot + ".sqlite3"),
                )
                original = {
                    "schemaVersion": 1,
                    "owner": current.owner,
                    "slots": {
                        slot: {"task_id": slot + "-task"} for slot in ("revision", "stale", "exact")
                    },
                }

                def factory(**kwargs):
                    return SimpleNamespace(get=get, close=close, pending_count=0)

                with (
                    patch.object(m, "_public_modules"),
                    patch.object(m, "read_data", return_value=original),
                    patch.object(postgres_api, "open_postgres_client", side_effect=factory),
                    patch.object(m, "publish") as published,
                    self.assertRaises(m.FixtureError),
                ):
                    await m.public_phase(current, "verify")
                self.assertEqual(closed, [True])
                published.assert_not_called()

    async def test_unknown_public_phase_rejects_before_any_P1_module_or_IO(self):
        with (
            patch.object(m, "_public_modules", side_effect=AssertionError("no imports")),
            self.assertRaises(m.FixtureError),
        ):
            await m.public_phase(None, "unknown")


if __name__ == "__main__":
    unittest.main()
