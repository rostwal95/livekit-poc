import asyncio
import io
import json
import logging
import subprocess
import sys
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from services.rtc_agent import telemetry


class WorkerTelemetryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stream = io.StringIO()
        self.logger_name = f"worker-telemetry-test.{self.id()}"
        self.logger = logging.getLogger(self.logger_name)
        self.previous_logger_state = (self.logger.level, self.logger.propagate)
        self.patch_logger = patch.object(telemetry, "_logger", None)
        self.patch_name = patch.object(telemetry, "LOGGER_NAME", self.logger_name)
        self.patch_logger.start()
        self.patch_name.start()
        self.addCleanup(self.patch_logger.stop)
        self.addCleanup(self.patch_name.stop)
        self.addCleanup(self.close_handlers)
        telemetry.configure_logging(stream=self.stream)

    def close_handlers(self):
        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)
            handler.close()
        self.logger.setLevel(self.previous_logger_state[0])
        self.logger.propagate = self.previous_logger_state[1]

    def records(self):
        return [json.loads(line) for line in self.stream.getvalue().splitlines()]

    def test_schema_is_small_json_with_utc_timestamp_and_fixed_severity(self):
        telemetry.emit_event(
            "session_started", code="accepted", active_tasks=0, active_audio_tracks=0
        )
        [record] = self.records()
        self.assertEqual(
            set(record),
            {
                "service",
                "severity",
                "timestamp",
                "event",
                "code",
                "active_tasks",
                "active_audio_tracks",
            },
        )
        self.assertEqual(record["severity"], "info")
        self.assertEqual(record["service"], "rtc-agent")
        self.assertEqual(record["event"], "session_started")
        self.assertEqual(record["code"], "accepted")
        self.assertEqual(record["active_tasks"], 0)
        self.assertEqual(
            datetime.fromisoformat(record["timestamp"]).utcoffset(), UTC.utcoffset(None)
        )

    async def test_actual_future_success_failure_and_cancel_have_distinct_levels(self):
        loop = asyncio.get_running_loop()
        succeeded = loop.create_future()
        succeeded.set_result(None)
        failed = loop.create_future()
        failed.set_exception(RuntimeError("SECRET_SENTINEL task failure"))
        cancelled = loop.create_future()
        cancelled.cancel()
        for future in (succeeded, failed, cancelled):
            telemetry.log_task_completion(future, active_tasks=0)
        self.assertEqual(
            [(record["event"], record["code"], record["severity"]) for record in self.records()],
            [
                ("task_completed", "completed", "info"),
                ("task_failed", "unexpected_error", "error"),
                ("task_cancelled", "cancelled", "info"),
            ],
        )
        self.assertNotIn("SECRET_SENTINEL", self.stream.getvalue())

    def test_error_classification_never_reads_exception_text_or_cause(self):
        class PrivateFailure(RuntimeError):
            def __str__(self):
                raise AssertionError("Exception text must never be inspected")

            def __repr__(self):
                raise AssertionError("Exception repr must never be inspected")

        secret = PrivateFailure("SECRET_SENTINEL")
        secret.__cause__ = ValueError("SECRET_SENTINEL cause")
        self.assertEqual(telemetry.classify_error(secret), "unexpected_error")
        for error, expected in (
            (TimeoutError("SECRET_SENTINEL"), "timeout"),
            (ValueError("SECRET_SENTINEL"), "invalid_input"),
            (OSError("SECRET_SENTINEL"), "transport_error"),
            (asyncio.CancelledError("SECRET_SENTINEL"), "cancelled"),
        ):
            self.assertEqual(telemetry.classify_error(error), expected)
        telemetry.emit_event("task_failed", code=telemetry.classify_error(secret))
        self.assertNotIn("SECRET_SENTINEL", self.stream.getvalue())
        self.assertNotIn("Traceback", self.stream.getvalue())

    def test_idempotent_configuration_keeps_one_owned_handler_and_first_stream(self):
        other = io.StringIO()
        telemetry.configure_logging(stream=other)
        telemetry.configure_logging(stream=other)
        self.assertEqual(len(self.logger.handlers), 1)
        telemetry.emit_event("job_rejected", code="job_capacity")
        self.assertEqual(len(self.records()), 1)
        self.assertEqual(other.getvalue(), "")
        self.assertFalse(self.logger.propagate)

    def test_logger_context_isolation_and_no_stale_fields(self):
        telemetry.emit_event("session_started", code="accepted", active_tasks=3)
        telemetry.emit_event("session_finished", code="disconnected")
        self.assertNotIn("active_tasks", self.records()[1])
        other_name = self.logger_name + ".other"
        other_logger = logging.getLogger(other_name)
        other_stream = io.StringIO()
        with patch.object(telemetry, "LOGGER_NAME", other_name):
            telemetry.configure_logging(stream=other_stream)
            telemetry.emit_event("session_started", code="accepted")
        self.assertEqual(len(self.records()), 2)
        self.assertEqual(len(other_stream.getvalue().splitlines()), 1)
        for handler in other_logger.handlers[:]:
            other_logger.removeHandler(handler)
            handler.close()

    def test_fixed_rejection_and_expected_failure_severity(self):
        telemetry.emit_event("stream_rejected", code="invalid_source")
        telemetry.emit_event("task_failed", code="invalid_input")
        telemetry.emit_event("task_failed", code="timeout")
        telemetry.emit_event("task_failed", code="transport_error")
        self.assertEqual(
            [record["severity"] for record in self.records()], ["warning"] * 3 + ["error"]
        )

    def test_unknown_events_codes_and_unbounded_counts_are_rejected_without_logging(self):
        before = self.stream.getvalue()
        for event, code in (
            ("SECRET_SENTINEL", "accepted"),
            ("session_started", "SECRET_SENTINEL"),
        ):
            with self.assertRaisesRegex(ValueError, "Unknown worker application"):
                telemetry.emit_event(event, code=code)
        for value in (-1, 1025, True, "SECRET_SENTINEL"):
            with self.assertRaisesRegex(ValueError, "Invalid worker application count"):
                telemetry.emit_event("session_started", code="accepted", active_tasks=value)
        self.assertEqual(self.stream.getvalue(), before)

    def test_unconfigured_module_never_falls_back_to_root_logging(self):
        with patch.object(telemetry, "_logger", None):
            telemetry.emit_event("session_started", code="accepted")
        self.assertEqual(self.stream.getvalue(), "")

    async def test_real_bounded_task_failure_is_logged_and_still_raises_to_awaiter(self):
        from services.rtc_agent.transport import BoundedTasks

        failure = RuntimeError("SECRET_SENTINEL original task failure")

        async def fail():
            raise failure

        tasks = BoundedTasks()
        task = tasks.spawn(fail)
        self.assertIsNotNone(task)
        with self.assertRaises(RuntimeError) as captured:
            await task
        self.assertIs(captured.exception, failure)
        await asyncio.sleep(0)  # Drain the scheduled done callback, not a timing race.
        self.assertEqual(tasks.tasks, set())
        [record] = self.records()
        self.assertEqual((record["event"], record["code"]), ("task_failed", "unexpected_error"))
        self.assertNotIn("SECRET_SENTINEL", self.stream.getvalue())

    async def test_real_bounded_task_shutdown_logs_cancellation_without_error(self):
        from services.rtc_agent.transport import BoundedTasks

        started, released = asyncio.Event(), asyncio.Event()

        async def held():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                released.set()

        tasks = BoundedTasks()
        task = tasks.spawn(held)
        await started.wait()
        await tasks.close()
        self.assertTrue(released.is_set())
        self.assertTrue(task.cancelled())
        self.assertEqual(tasks.tasks, set())
        [record] = self.records()
        self.assertEqual((record["event"], record["severity"]), ("task_cancelled", "info"))

    async def test_actual_admission_callbacks_configure_and_log_fixed_rejections(self):
        from services.rtc_agent import worker

        for room, active_jobs, code, kwargs in (
            ("SECRET_SENTINEL_invalid_room", [], "invalid_room", {}),
            ("lab-test", [object()], "job_capacity", {"terminate": False}),
        ):
            request = SimpleNamespace(
                room=SimpleNamespace(name=room), reject=AsyncMock(), accept=AsyncMock()
            )
            with (
                patch.object(worker, "server", SimpleNamespace(active_jobs=active_jobs)),
                patch.object(
                    worker, "configure_logging", wraps=telemetry.configure_logging
                ) as setup,
            ):
                await worker.accept_local_job(request)
            setup.assert_called_once_with()
            request.reject.assert_awaited_once_with(**kwargs)
            request.accept.assert_not_awaited()
            self.assertEqual(self.records()[-1]["code"], code)
        self.assertNotIn("SECRET_SENTINEL", self.stream.getvalue())

    async def test_actual_session_entry_preserves_connect_failure_and_cancellation(self):
        from services.rtc_agent import worker

        class FakeRoom:
            def register_text_stream_handler(self, *_):
                return None

            def on(self, _):
                return lambda callback: callback

        for error, expected in (
            (OSError("SECRET_SENTINEL connect failure"), "failed"),
            (asyncio.CancelledError("SECRET_SENTINEL cancellation"), "cancelled"),
        ):
            self.stream.seek(0)
            self.stream.truncate()
            diagnostics = SimpleNamespace(
                on_text=Mock(), on_audio=Mock(), remove_audio=Mock(), close=AsyncMock()
            )
            context = SimpleNamespace(
                room=FakeRoom(),
                add_shutdown_callback=Mock(),
                connect=AsyncMock(side_effect=error),
                shutdown=Mock(),
            )
            with (
                patch.object(worker, "TransportDiagnostics", return_value=diagnostics),
                patch.object(
                    worker, "configure_logging", wraps=telemetry.configure_logging
                ) as setup,
                self.assertRaises(type(error)) as captured,
            ):
                await worker.transport_session(context)
            self.assertIs(captured.exception, error)
            setup.assert_called_once_with()
            diagnostics.close.assert_awaited_once_with()
            context.add_shutdown_callback.assert_called_once_with(diagnostics.close)
            records = self.records()
            self.assertEqual(records[0]["event"], "session_started")
            self.assertEqual(
                (records[-1]["event"], records[-1]["code"]), ("session_finished", expected)
            )
            if expected == "failed":
                self.assertEqual(records[1]["event"], "session_failed")
                self.assertEqual(records[1]["code"], "transport_error")
                self.assertEqual(records[1]["severity"], "error")
            else:
                self.assertTrue(all(record["severity"] == "info" for record in records))
            self.assertNotIn("SECRET_SENTINEL", self.stream.getvalue())

    async def test_actual_session_disconnect_logs_observed_end_and_cleans_up(self):
        from services.rtc_agent import worker

        class FakeRoom:
            def __init__(self):
                self.callbacks = {}

            def register_text_stream_handler(self, *_):
                return None

            def on(self, event):
                def register(callback):
                    self.callbacks[event] = callback
                    return callback

                return register

        room = FakeRoom()
        diagnostics = SimpleNamespace(
            on_text=Mock(), on_audio=Mock(), remove_audio=Mock(), close=AsyncMock()
        )
        context = SimpleNamespace(
            room=room,
            add_shutdown_callback=Mock(),
            connect=AsyncMock(side_effect=lambda: room.callbacks["disconnected"]()),
            shutdown=Mock(),
        )
        with patch.object(worker, "TransportDiagnostics", return_value=diagnostics):
            await worker.transport_session(context)
        diagnostics.close.assert_awaited_once_with()
        context.shutdown.assert_not_called()
        self.assertEqual(
            [(record["event"], record["code"]) for record in self.records()],
            [("session_started", "accepted"), ("session_finished", "disconnected")],
        )

    async def test_actual_session_does_not_catch_fatal_base_exception(self):
        from services.rtc_agent import worker

        class FakeRoom:
            def register_text_stream_handler(self, *_):
                return None

            def on(self, _):
                return lambda callback: callback

        fatal = SystemExit(42)
        diagnostics = SimpleNamespace(
            on_text=Mock(), on_audio=Mock(), remove_audio=Mock(), close=AsyncMock()
        )
        context = SimpleNamespace(
            room=FakeRoom(),
            add_shutdown_callback=Mock(),
            connect=AsyncMock(side_effect=fatal),
            shutdown=Mock(),
        )
        with (
            patch.object(worker, "TransportDiagnostics", return_value=diagnostics),
            self.assertRaises(SystemExit) as captured,
        ):
            await worker.transport_session(context)
        self.assertIs(captured.exception, fatal)
        diagnostics.close.assert_awaited_once_with()
        self.assertEqual(
            [(record["event"], record["code"]) for record in self.records()],
            [("session_started", "accepted"), ("session_finished", "failed")],
        )

    def test_import_does_not_attach_handlers_or_modify_root_logger(self):
        script = """
import io
import logging
root = logging.getLogger()
before = (root.level, tuple(root.handlers))
native = logging.getLogger("livekit.agents")
native_before = (native.level, tuple(native.handlers), native.propagate)
from services.rtc_agent import telemetry
assert telemetry._logger is None
assert (root.level, tuple(root.handlers)) == before
assert not logging.getLogger(telemetry.LOGGER_NAME).handlers
telemetry.configure_logging(stream=io.StringIO())
assert (root.level, tuple(root.handlers)) == before
assert (native.level, tuple(native.handlers), native.propagate) == native_before
"""
        result = subprocess.run(
            [sys.executable, "-c", script], check=False, text=True, capture_output=True, timeout=5
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
