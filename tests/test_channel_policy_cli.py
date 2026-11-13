"""Inert CLI and real-loop fake-application ownership; no SQL, sockets or providers."""

from __future__ import annotations

import asyncio
import gc
import io
import json
import os
import signal
import subprocess
import sys
import unittest
import warnings
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from services.channel_policy_demo import __main__ as m
from services.channel_policy_demo.owner_config import ProfileError

PRIVATE = "PRIVATE_ARG_PATH_DEPENDENCY_SENTINEL"


class Unavailable(RuntimeError):
    code = "unavailable"


class FakeApp:
    def __init__(self):
        self.events = []
        self.source_entered, self.executor_entered, self.close_entered = (
            asyncio.Event(),
            asyncio.Event(),
            asyncio.Event(),
        )
        self.source_release, self.executor_release, self.close_release = (
            asyncio.Event(),
            asyncio.Event(),
            asyncio.Event(),
        )
        for event in (self.source_release, self.executor_release, self.close_release):
            event.set()
        self.source_calls = self.executor_calls = self.close_calls = 0
        self.stage_cancelled = self.close_cancelled = 0
        self.source_active = self.executor_active = False
        self.closing = self.closed = False
        self.source_error = None
        self.executor_errors, self.close_errors = [], []

    async def start_sources(self):
        self.source_calls += 1
        self.events.append("sources")
        self.source_active = True
        self.source_entered.set()
        try:
            await self.source_release.wait()
            if self.source_error is not None:
                raise self.source_error
            if self.closing:
                raise RuntimeError(PRIVATE)
        except asyncio.CancelledError:
            self.stage_cancelled += 1
            raise
        finally:
            self.source_active = False

    async def start_executor(self):
        self.executor_calls += 1
        self.events.append("executor")
        self.executor_active = True
        self.executor_entered.set()
        try:
            await self.executor_release.wait()
            if self.executor_errors:
                raise self.executor_errors.pop(0)
            if self.closing:
                raise RuntimeError(PRIVATE)
        except asyncio.CancelledError:
            self.stage_cancelled += 1
            raise
        finally:
            self.executor_active = False

    async def close(self):
        self.close_calls += 1
        self.events.append("close")
        self.closing = True
        self.close_entered.set()
        try:
            if self.close_errors:
                raise self.close_errors.pop(0)
            if self.source_active:
                await self.source_release.wait()
            if self.executor_active:
                await self.executor_release.wait()
            await self.close_release.wait()
            self.closed = True
        except asyncio.CancelledError:
            self.close_cancelled += 1
            raise


class CliArguments(unittest.TestCase):
    def capture(self, args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            result = m.main(args)
        self.assertEqual(err.getvalue(), "")
        self.assertNotIn(PRIVATE, out.getvalue())
        return result, [json.loads(line) for line in out.getvalue().splitlines()]

    def test_plan_has_fixed_limits_and_no_environment_file_loop_or_owner_access(self):
        with (
            patch.object(m, "_load_application", side_effect=AssertionError("owner")),
            patch.object(m.asyncio, "run", side_effect=AssertionError("loop")),
            patch.object(Path, "read_bytes", side_effect=AssertionError("file")),
            patch.object(os, "open", side_effect=AssertionError("open")),
            patch.object(os, "getenv", side_effect=AssertionError("environment")),
        ):
            code, events = self.capture(["--plan"])
        self.assertEqual((code, len(events)), (0, 1))
        self.assertEqual(events[0]["event"], "plan")
        self.assertEqual(
            events[0]["limits"],
            {"node_readiness_ms": 15000, "readiness_poll_ms": 100, "close_observer_ms": 5000},
        )
        self.assertFalse(events[0]["provider_access"])
        self.assertFalse(events[0]["serving_ddl"])

    def test_closed_parser_defaults_and_explicit_order_do_not_access_files(self):
        path = Path("/private/tmp/synthetic-owner.json")
        self.assertEqual(m._arguments(["serve", "--profile", str(path)]), (path, "running"))
        self.assertEqual(
            m._arguments(["serve", "--executor", "paused", "--profile", str(path)]),
            (path, "paused"),
        )
        self.assertEqual(
            m._arguments(["serve", "--profile", str(path), "--executor", "running"]),
            (path, "running"),
        )

    def test_invalid_arguments_are_finite_and_never_echo_values_or_paths(self):
        variants = (
            [],
            [PRIVATE],
            ["--plan", PRIVATE],
            ["serve"],
            ["serve", "--profile"],
            ["serve", "--profile", PRIVATE],
            ["serve", "--profile", "/private/tmp/" + PRIVATE + ".env"],
            ["serve", "--profile", "/private/tmp/" + PRIVATE + ".json", "--token", PRIVATE],
            ["serve", "--profile", "/private/tmp/owner.json", "--executor", PRIVATE],
            ["serve", "--profile", "/private/tmp/owner.json", "--profile", PRIVATE],
            ["serve", "--profile", "/private/tmp/\ud800.json"],
            ["serve", "--profile", "/private/tmp/owner\n.json"],
            ["serve", "--profile", "/" + "x" * 4096 + ".json"],
        )
        with patch.object(m, "_load_application", side_effect=AssertionError("owner")):
            for index, args in enumerate(variants):
                with self.subTest(index=index):
                    code, events = self.capture(args)
                    self.assertEqual(code, 2)
                    self.assertEqual(
                        events,
                        [
                            {
                                "schema_version": 1,
                                "event": "error",
                                "code": "invalid_arguments",
                                "executor": "running",
                            }
                        ],
                    )

    def test_private_profile_failure_has_finite_status_and_no_application_owner(self):
        with patch.object(m, "_load_application", side_effect=ProfileError()):
            code, events = self.capture(["serve", "--profile", "/private/tmp/" + PRIVATE + ".json"])
        self.assertEqual((code, events[0]["code"]), (2, "invalid_profile"))

    def test_private_loader_exception_is_finite(self):
        with patch.object(m, "_load_application", side_effect=RuntimeError(PRIVATE)):
            code, events = self.capture(["serve", "--profile", "/private/tmp/" + PRIVATE + ".json"])
        self.assertEqual((code, events[0]["code"]), (1, "unavailable"))

    def test_import_is_inert_and_does_not_import_configuration_or_application(self):
        script = """
import asyncio, importlib, logging, os, socket, threading
from pathlib import Path
from unittest.mock import patch
with (
 patch.object(socket, 'socket', side_effect=AssertionError('socket')),
 patch.object(threading.Thread, 'start', side_effect=AssertionError('thread')),
 patch.object(asyncio, 'create_task', side_effect=AssertionError('task')),
 patch.object(Path, 'read_bytes', side_effect=AssertionError('file')),
 patch.object(os, 'getenv', side_effect=AssertionError('env')),
 patch.object(logging, 'basicConfig', side_effect=AssertionError('logging')),
):
 import services.channel_policy_demo.__main__
import sys
assert 'services.channel_policy_demo.application' not in sys.modules
assert 'services.channel_policy_demo.owner_config' not in sys.modules
print('inert')
"""
        completed = subprocess.run(
            [sys.executable, "-I", "-B", "-c", script],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual((completed.returncode, completed.stdout), (0, "inert\n"), completed.stderr)


class CliLifecycle(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.apps, self.stops, self.tasks = [], [], []
        self.emitted = []
        self.poll_patch = patch.object(m, "_POLL_SECONDS", 0.005)
        self.close_patch = patch.object(m, "_CLOSE_OBSERVER_SECONDS", 0.02)
        self.poll_patch.start()
        self.close_patch.start()

    async def asyncTearDown(self):
        for app in self.apps:
            for event in (app.source_release, app.executor_release, app.close_release):
                event.set()
            app.close_errors.clear()
        for stop in self.stops:
            stop.set()
        if self.tasks:
            async with asyncio.timeout(2):
                await asyncio.gather(*self.tasks, return_exceptions=True)
        self.poll_patch.stop()
        self.close_patch.stop()

    def app(self):
        app = FakeApp()
        self.apps.append(app)
        return app

    def sink(self, event, code, executor):
        self.emitted.append({"event": event, "code": code, "executor": executor})
        self.assertNotIn(PRIVATE, json.dumps(self.emitted))

    def started(self, app, executor="running", emit=None):
        stop = asyncio.Event()
        self.stops.append(stop)
        task = asyncio.create_task(
            m.run_application(app, executor=executor, stop=stop, emit=emit or self.sink)
        )
        self.tasks.append(task)
        return task, stop

    async def until(self, predicate):
        async with asyncio.timeout(1):
            while not predicate():
                await asyncio.sleep(0)

    async def test_sources_precede_executor_and_only_successful_readiness_publishes_app_ready(self):
        app = self.app()
        task, stop = self.started(app)
        await self.until(lambda: any(event["event"] == "app_ready" for event in self.emitted))
        self.assertEqual(app.events, ["sources", "executor"])
        self.assertEqual([event["event"] for event in self.emitted], ["sources_ready", "app_ready"])
        self.assertFalse(task.done())
        stop.set()
        self.assertEqual(await task, 0)
        self.assertTrue(app.closed)
        self.assertEqual(
            [event["event"] for event in self.emitted], ["sources_ready", "app_ready", "closed"]
        )

    async def test_paused_executor_publishes_ready_without_any_node_readiness_call(self):
        app = self.app()
        task, stop = self.started(app, executor="paused")
        await self.until(lambda: len(self.emitted) == 2)
        self.assertEqual((app.source_calls, app.executor_calls), (1, 0))
        self.assertEqual(
            self.emitted[1], {"event": "app_ready", "code": "ok", "executor": "paused"}
        )
        stop.set()
        self.assertEqual(await task, 0)
        self.assertTrue(app.closed)

    async def test_stop_during_held_source_begins_close_without_cancelling_startup(self):
        app = self.app()
        app.source_release.clear()
        task, stop = self.started(app)
        await app.source_entered.wait()
        stop.set()
        await asyncio.wait_for(app.close_entered.wait(), 1)
        self.assertEqual((app.executor_calls, app.stage_cancelled, app.closed), (0, 0, False))
        self.assertFalse(task.done())
        app.source_release.set()
        self.assertEqual(await task, 0)
        self.assertEqual([event["event"] for event in self.emitted], ["closed"])

    async def test_stop_during_held_node_readiness_begins_close_and_keeps_actual_read(self):
        app = self.app()
        app.executor_release.clear()
        task, stop = self.started(app)
        await app.executor_entered.wait()
        stop.set()
        await asyncio.wait_for(app.close_entered.wait(), 1)
        self.assertEqual((app.executor_calls, app.stage_cancelled), (1, 0))
        self.assertFalse(task.done())
        self.assertEqual([event["event"] for event in self.emitted], ["sources_ready"])
        app.executor_release.set()
        self.assertEqual(await task, 0)
        self.assertEqual(self.emitted[-1]["event"], "closed")

    async def test_readonly_readiness_retry_keeps_one_original_deadline_and_then_progresses(self):
        app = self.app()
        app.executor_errors = [Unavailable(PRIVATE), Unavailable(PRIVATE)]
        task, stop = self.started(app)
        await self.until(lambda: any(event["event"] == "app_ready" for event in self.emitted))
        self.assertEqual((app.source_calls, app.executor_calls), (1, 3))
        stop.set()
        self.assertEqual(await task, 0)
        self.assertEqual(
            [event["event"] for event in self.emitted], ["sources_ready", "app_ready", "closed"]
        )

    async def test_readiness_expiry_closes_without_resetting_deadline_or_emitting_ready(self):
        app = self.app()
        app.executor_errors = [Unavailable(PRIVATE) for _ in range(100)]
        with patch.object(m, "_READINESS_SECONDS", 0.035):
            task, _ = self.started(app)
            self.assertEqual(await asyncio.wait_for(asyncio.shield(task), 1), 1)
        self.assertLess(app.executor_calls, 100)
        self.assertTrue(app.closed)
        self.assertEqual(
            [event["event"] for event in self.emitted], ["sources_ready", "error", "closed"]
        )

    async def test_held_readiness_past_deadline_is_retained_while_close_starts_promptly(self):
        app = self.app()
        app.executor_release.clear()
        with patch.object(m, "_READINESS_SECONDS", 0.015):
            task, _ = self.started(app)
            await asyncio.wait_for(app.close_entered.wait(), 1)
            self.assertEqual((app.executor_calls, app.stage_cancelled), (1, 0))
            self.assertFalse(task.done())
            app.executor_release.set()
            self.assertEqual(await task, 1)
        self.assertNotIn("app_ready", [event["event"] for event in self.emitted])

    async def test_failed_close_retries_explicitly_emits_incomplete_once_and_drains(self):
        app = self.app()
        app.close_errors = [RuntimeError(PRIVATE), RuntimeError(PRIVATE)]
        task, stop = self.started(app)
        await app.executor_entered.wait()
        stop.set()
        self.assertEqual(await task, 0)
        self.assertEqual((app.close_calls, app.close_cancelled, app.closed), (3, 0, True))
        self.assertEqual(sum(event["event"] == "cleanup_incomplete" for event in self.emitted), 1)
        self.assertEqual(sum(event["event"] == "closed" for event in self.emitted), 1)

    async def test_timed_out_close_observer_retains_same_actual_close_and_does_not_spam(self):
        app = self.app()
        app.close_release.clear()
        task, stop = self.started(app)
        await app.executor_entered.wait()
        stop.set()
        await app.close_entered.wait()
        await asyncio.sleep(0.065)
        self.assertEqual((app.close_calls, app.close_cancelled), (1, 0))
        self.assertFalse(task.done())
        self.assertEqual(sum(event["event"] == "cleanup_incomplete" for event in self.emitted), 1)
        self.assertNotIn("closed", [event["event"] for event in self.emitted])
        app.close_release.set()
        self.assertEqual(await task, 0)
        self.assertTrue(app.closed)

    async def test_outer_repeated_cancellation_propagates_only_after_actual_drain(self):
        app = self.app()
        app.source_release.clear()
        app.close_release.clear()
        task, _ = self.started(app)
        await app.source_entered.wait()
        task.cancel()
        await app.close_entered.wait()
        task.cancel()
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        self.assertEqual((app.stage_cancelled, app.close_cancelled), (0, 0))
        app.source_release.set()
        app.close_release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(app.closed)
        self.assertEqual(self.emitted[-1]["event"], "closed")

    async def test_dependency_failure_is_finite_and_still_closes(self):
        app = self.app()
        app.source_error = RuntimeError(PRIVATE)
        task, _ = self.started(app)
        self.assertEqual(await task, 1)
        self.assertTrue(app.closed)
        self.assertEqual(
            self.emitted,
            [
                {"event": "error", "code": "unavailable", "executor": "running"},
                {"event": "closed", "code": "ok", "executor": "running"},
            ],
        )

    async def test_hostile_readiness_code_getter_never_runs_and_is_not_retried(self):
        hits = []

        class Getter(RuntimeError):
            @property
            def code(self):
                hits.append(True)
                raise RuntimeError(PRIVATE)

        app = self.app()
        app.executor_errors = [Getter(PRIVATE)]
        task, _ = self.started(app)
        self.assertEqual(await task, 1)
        self.assertEqual((hits, app.executor_calls, app.closed), ([], 1, True))
        self.assertNotIn("app_ready", [event["event"] for event in self.emitted])

    async def test_event_sink_failure_cannot_prevent_actual_stop_and_drain(self):
        app = self.app()

        def failed(*_):
            raise RuntimeError(PRIVATE)

        task, stop = self.started(app, emit=failed)
        await app.executor_entered.wait()
        stop.set()
        self.assertEqual(await task, 0)
        self.assertTrue(app.closed)

    async def test_source_task_allocation_failure_closes_unscheduled_coroutine_and_app(self):
        app = self.app()
        stop = asyncio.Event()
        self.stops.append(stop)
        original = asyncio.create_task
        actions = []

        def allocate(action):
            if action.cr_code.co_name == "start_sources":
                actions.append(action)
                raise RuntimeError(PRIVATE)
            return original(action)

        with warnings.catch_warnings(record=True) as seen:
            warnings.simplefilter("always")
            with patch.object(m.asyncio, "create_task", side_effect=allocate):
                self.assertEqual(
                    await m.run_application(app, executor="running", stop=stop, emit=self.sink), 1
                )
            gc.collect()
        self.assertFalse(
            [warning for warning in seen if issubclass(warning.category, RuntimeWarning)]
        )
        self.assertTrue(app.closed)
        self.assertEqual((len(actions), app.source_calls), (1, 0))
        self.assertIsNone(actions[0].cr_frame)

    async def test_close_allocation_failure_retains_app_and_retries_without_new_business(self):
        app = self.app()
        task, stop = self.started(app)
        await app.executor_entered.wait()
        original = asyncio.create_task
        failed = []

        def allocate(action):
            if action.cr_code.co_name == "close_and_settle" and not failed:
                failed.append(action)
                raise RuntimeError(PRIVATE)
            return original(action)

        with patch.object(m.asyncio, "create_task", side_effect=allocate):
            stop.set()
            self.assertEqual(await task, 0)
        self.assertEqual((app.source_calls, app.executor_calls, app.close_calls), (1, 1, 1))
        self.assertIsNone(failed[0].cr_frame)
        self.assertTrue(app.closed)
        self.assertEqual(sum(event["event"] == "cleanup_incomplete" for event in self.emitted), 1)

    async def test_signal_handlers_install_before_owner_start_and_remove_after_actual_drain(self):
        app = self.app()
        loop = asyncio.get_running_loop()
        handlers, removed = {}, []

        def emit(event, code, executor):
            self.sink(event, code, executor)
            if event == "app_ready":
                handlers[signal.SIGTERM]()

        with (
            patch.object(
                loop,
                "add_signal_handler",
                side_effect=lambda selected, callback: handlers.__setitem__(selected, callback),
            ),
            patch.object(
                loop, "remove_signal_handler", side_effect=lambda selected: removed.append(selected)
            ),
            patch.object(m, "_load_application", return_value=app) as loader,
            patch.object(m, "_event", side_effect=emit),
        ):
            self.assertEqual(await m._serve(Path("/private/tmp/owner.json"), "running"), 0)
        self.assertEqual(set(handlers), {signal.SIGTERM, signal.SIGINT})
        self.assertEqual(set(removed), set(handlers))
        self.assertEqual(loader.call_count, 1)
        self.assertTrue(app.closed)
        self.assertEqual(self.emitted[-1]["event"], "closed")


if __name__ == "__main__":
    unittest.main()
