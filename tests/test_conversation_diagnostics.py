"""Finite native failure stages preserve privacy, cleanup and original exceptions."""

import asyncio
import json
import logging
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from services.conversation_agent import telemetry, worker
from services.conversation_agent.scripted import SPEECH_FILES, SpeechBank
from services.conversation_agent.session import ConversationBinding


class FailurePrivacyTests(unittest.TestCase):
    def test_failure_codes_are_error_severity_and_acceptance_stays_info(self):
        with patch.object(telemetry.LOGGER, "log") as logged:
            telemetry.emit("session_failed", "session_media_ready_timeout")
            self.assertEqual(logged.call_args.args[0], logging.ERROR)
            telemetry.emit("cleanup_failed", "session_cleanup_observer_timeout")
            self.assertEqual(logged.call_args.args[0], logging.ERROR)
            telemetry.emit("session_started", "accepted")
            self.assertEqual(logged.call_args.args[0], logging.INFO)

    def test_only_exact_builtin_types_and_fixed_phases_enter_five_field_logs(self):
        class PrivateError(RuntimeError):
            def __str__(self):
                raise AssertionError("Exception text must remain private")

            def __repr__(self):
                raise AssertionError("Exception repr must remain private")

        formatter = telemetry._SafeFormatter()
        for error, expected in (
            (TimeoutError("PRIVATE"), "timeout"),
            (ValueError("PRIVATE"), "configuration"),
            (TypeError("PRIVATE"), "configuration"),
            (AttributeError("PRIVATE"), "configuration"),
            (AssertionError("PRIVATE"), "configuration"),
            (asyncio.CancelledError("PRIVATE"), "cancelled"),
            (PrivateError(), "dependency"),
        ):
            error.__cause__ = PrivateError()
            error.__context__ = PrivateError()
            for phase in telemetry.SESSION_FAILURE_PHASES:
                with self.subTest(phase=phase, category=expected):
                    code = telemetry.session_failure_code(phase, error)
                    self.assertEqual(code, "session_" + phase + "_" + expected)
                    self.assertIn(code, telemetry.CODES)
                    record = logging.LogRecord(
                        "services.conversation_agent",
                        logging.ERROR,
                        "private",
                        1,
                        PrivateError(),
                        (),
                        None,
                    )
                    record.event, record.code = "session_failed", code
                    raw = formatter.format(record)
                    value = json.loads(raw)
                    self.assertEqual(
                        set(value), {"service", "timestamp", "severity", "event", "code"}
                    )
                    self.assertEqual(value["code"], code)
                    self.assertNotIn("PRIVATE", raw)
                    self.assertNotIn("Traceback", raw)
        for phase in ("PRIVATE", "", [], None):
            with self.subTest(phase=phase), self.assertRaises(ValueError):
                telemetry.session_failure_code(phase, PrivateError())


class StartupWarningPrivacyTests(unittest.TestCase):
    def record(self, module, function, *, level=logging.WARNING, args=(), info=None):
        class PrivateError(TimeoutError):
            def __str__(self):
                raise AssertionError("Message and exception content must not be read")

            def __repr__(self):
                raise AssertionError("Exception repr must not be read")

        private = PrivateError()
        private.__cause__ = PrivateError()
        private.__context__ = PrivateError()
        record = logging.LogRecord("livekit.agents", level, "PRIVATE-PATH", 1, private, (), None)
        record.module, record.funcName = module, function
        record.args, record.exc_info = args, info
        record.stack_info = private
        record.private_metadata = private
        record.getMessage = Mock(side_effect=AssertionError("Message formatter must not run"))
        value = json.loads(telemetry._SafeFormatter().format(record))
        record.getMessage.assert_not_called()
        self.assertEqual(set(value), {"service", "timestamp", "severity", "event", "code"})
        self.assertNotIn("PRIVATE", json.dumps(value))
        return value

    def test_verified_sdk_startup_origins_have_finite_codes_without_body_access(self):
        fixtures = (
            ("proc_pool", "start", "process_idle_initialize"),
            ("proc_pool", "_acquire_proc", "process_acquire"),
            ("proc_pool", "launch_job", "process_launch"),
            ("supervised_proc", "_memory_monitor_task", "process_memory"),
            ("supervised_proc", "_read_ipc_task", "process_responsiveness"),
            ("supervised_proc", "_supervise_task", "process_exit"),
            ("worker", "_connection_task", "worker_connection"),
            ("worker", "_on_accept", "assignment"),
            ("worker", "_job_request_task", "assignment_answer"),
            ("worker", "_handle_assignment", "assignment_lookup"),
            ("job_proc_lazy_main", "_warn_not_connected_task", "job_entry_connection"),
            ("job_proc_lazy_main", "_on_entry_done", "job_entry"),
            ("job_proc_lazy_main", "_shutdown_job", "job_shutdown"),
        )
        for module, function, expected in fixtures:
            with self.subTest(module=module, function=function):
                value = self.record(module, function)
                self.assertEqual((value["event"], value["severity"]), ("sdk_warning", "warning"))
                self.assertEqual(value["code"], "sdk_" + expected + "_none")
                self.assertIn(value["code"], telemetry.CODES)

    def test_exact_builtin_types_only_and_transcription_classification_stays_supported(self):
        class PrivateTimeout(TimeoutError):
            def __str__(self):
                raise AssertionError("Subclass messages must not be read")

        for error, expected in (
            (TimeoutError("PRIVATE"), "timeout"),
            (RuntimeError("PRIVATE"), "runtime"),
            (PrivateTimeout(), "other"),
        ):
            with self.subTest(category=expected):
                value = self.record("worker", "_on_accept", info=(type(error), error, None))
                self.assertEqual(value["code"], "sdk_assignment_" + expected)
                value = self.record(
                    "_output",
                    "_publish_transcription",
                    args=(error,),
                    info=(ValueError, ValueError("PRIVATE-UNRELATED"), None),
                )
                self.assertEqual(value["code"], "sdk_transcription_publish_" + expected)

    def test_memory_warning_is_not_relabelled_as_memory_limit_failure(self):
        warning = self.record("supervised_proc", "_memory_monitor_task")
        failure = self.record("supervised_proc", "_memory_monitor_task", level=logging.ERROR)
        self.assertEqual(warning["code"], "sdk_process_memory_none")
        self.assertEqual(failure["code"], "sdk_process_memory_none")
        self.assertEqual((warning["event"], warning["severity"]), ("sdk_warning", "warning"))
        self.assertEqual((failure["event"], failure["severity"]), ("sdk_error", "error"))

    def test_unknown_or_hostile_origins_keep_generic_code_without_metadata_conversion(self):
        class PrivateOrigin:
            def __str__(self):
                raise AssertionError("Origin string conversion must not run")

            def __hash__(self):
                raise AssertionError("Unknown origin hashing must not run")

        for module, function in (
            ("PRIVATE", "_acquire_proc"),
            ("proc_pool", "PRIVATE"),
            (PrivateOrigin(), "start"),
            ("worker", PrivateOrigin()),
            (None, []),
        ):
            with self.subTest(index=type(module).__name__):
                value = self.record(module, function)
                self.assertEqual(value["code"], "sdk_warning")
        value = self.record(
            "proc_pool", "_acquire_proc", args=PrivateOrigin(), info=PrivateOrigin()
        )
        self.assertEqual(value["code"], "sdk_process_acquire_none")


class StartupProgressPrivacyTests(unittest.TestCase):
    def test_fixed_startup_progress_uses_the_same_five_field_info_schema(self):
        expected = {
            "startup_entry",
            "startup_port_ready",
            "startup_runtime_constructing",
            "startup_runtime_ready",
            "startup_rtc_connecting",
            "startup_rtc_connected",
        }
        self.assertEqual(telemetry.STARTUP_PROGRESS_CODES, expected)
        for code in expected:
            with self.subTest(code=code):
                record = logging.LogRecord(
                    "services.conversation_agent", logging.INFO, "PRIVATE", 1, "PRIVATE", (), None
                )
                record.event, record.code = "startup_progress", code
                record.private_payload = "PRIVATE"
                record.exc_info = (RuntimeError, RuntimeError("PRIVATE"), None)
                raw = telemetry._SafeFormatter().format(record)
                value = json.loads(raw)
                self.assertEqual(set(value), {"service", "timestamp", "severity", "event", "code"})
                self.assertEqual(
                    (value["event"], value["code"], value["severity"]),
                    ("startup_progress", code, "info"),
                )
                self.assertNotIn("PRIVATE", raw)
                with patch.object(telemetry.LOGGER, "log") as logged:
                    telemetry.emit("startup_progress", code)
                    self.assertEqual(logged.call_args.args[0], logging.INFO)
        record.code = "PRIVATE-UNKNOWN-STAGE"
        self.assertEqual(
            json.loads(telemetry._SafeFormatter().format(record))["code"], "unexpected_error"
        )


class EntrypointFailureTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, phase, *, observer_fails=False):
        events = []
        port = SimpleNamespace(aclose=AsyncMock(side_effect=lambda: events.append("port")))
        observer = SimpleNamespace(
            aclose=AsyncMock(side_effect=lambda *_: events.append("observer"))
        )
        if observer_fails:
            observer.aclose.side_effect = TimeoutError("PRIVATE-OBSERVER")
        runtime = SimpleNamespace(
            inference_mode="scripted",
            session=SimpleNamespace(on=Mock()),
            controls=SimpleNamespace(
                unregister=Mock(side_effect=lambda *_: events.append("controls"))
            ),
            start=AsyncMock(),
            aclose=AsyncMock(side_effect=lambda: events.append("runtime")),
        )
        original = (
            TimeoutError("PRIVATE-BODY")
            if phase in {"rtc_connect", "media_ready", "port"}
            else ValueError("PRIVATE-SETUP")
        )
        composition = ModuleType("services.conversation_agent.composition")
        composition.SessionBusinessPort = type("UnboundSessionBusinessPort", (), {})
        composition.create_port = AsyncMock(
            return_value=(port, ConversationBinding("browser-test"))
        )
        composition.observe_session = Mock(return_value=observer)
        ctx = SimpleNamespace(
            job=SimpleNamespace(metadata="PRIVATE-GRANT"),
            room=SimpleNamespace(name="business-test", on=Mock()),
            proc=SimpleNamespace(
                userdata={
                    "speech_bank": SpeechBank(
                        tuple((text, b"\x01\x00" * 160) for text in SPEECH_FILES)
                    )
                }
            ),
            connect=AsyncMock(),
            add_shutdown_callback=Mock(),
            shutdown=Mock(),
        )
        factory = Mock(return_value=runtime)
        if phase == "port":
            composition.create_port.side_effect = original
        elif phase == "setup":
            factory.side_effect = original
        elif phase == "rtc_connect":
            ctx.connect.side_effect = original
        else:
            runtime.start.side_effect = original
        with (
            patch.dict(sys.modules, {"services.conversation_agent.composition": composition}),
            patch.object(worker, "configure_logging"),
            patch.object(worker, "create_runtime", factory),
            patch.object(worker, "emit") as emitted,
            self.assertRaises(type(original)) as caught,
        ):
            await worker.conversation_session(ctx)
        self.assertIs(caught.exception, original)
        code = (
            "session_setup_timeout"
            if phase == "port"
            else "session_setup_configuration"
            if phase == "setup"
            else "session_" + phase + "_timeout"
        )
        self.assertIn(("session_failed", code), [call.args for call in emitted.call_args_list])
        if phase == "port":
            port.aclose.assert_not_awaited()
            ctx.shutdown.assert_not_called()
        else:
            port.aclose.assert_awaited_once()
            ctx.shutdown.assert_called_once()
            if phase != "setup":
                runtime.aclose.assert_awaited_once()
                runtime.controls.unregister.assert_called_once()
                observer.aclose.assert_awaited_once()
        if observer_fails:
            self.assertIn(
                ("cleanup_failed", "session_cleanup_observer_timeout"),
                [call.args for call in emitted.call_args_list],
            )
            self.assertEqual(events[-1], "port")
        return [call.args for call in emitted.call_args_list]

    async def test_startup_progress_stops_at_the_actual_failed_boundary(self):
        stages = [
            "startup_entry",
            "startup_port_ready",
            "startup_runtime_constructing",
            "startup_runtime_ready",
            "startup_rtc_connecting",
            "startup_rtc_connected",
        ]
        for failure, count in (("port", 1), ("setup", 3), ("rtc_connect", 5), ("media_ready", 6)):
            with self.subTest(failure=failure):
                calls = await self.exercise(failure)
                observed = [code for event, code in calls if event == "startup_progress"]
                self.assertEqual(observed, stages[:count])
                self.assertNotIn(("session_started", "accepted"), calls)

    async def test_port_setup_failure_has_a_finite_stage(self):
        await self.exercise("port")

    async def test_runtime_setup_failure_preserves_port_cleanup(self):
        await self.exercise("setup")

    async def test_rtc_connect_failure_keeps_independent_cleanup(self):
        await self.exercise("rtc_connect")

    async def test_media_ready_timeout_has_its_own_stage(self):
        await self.exercise("media_ready")

    async def test_observer_cleanup_failure_is_visible_without_hiding_original_error(self):
        await self.exercise("media_ready", observer_fails=True)


if __name__ == "__main__":
    unittest.main()
