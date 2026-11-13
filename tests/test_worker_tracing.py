"""Opt-in durable child traces preserve worker authority, output and failure semantics."""

import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.trace import StatusCode

from continuity_lab import worker_cli, worker_runtime
from continuity_lab.lease_models import LeaseGrant, WorkClaim, WorkKind
from continuity_lab.tracing import TraceRuntime, TraceSettings
from continuity_lab.worker_cli import WorkerSettings
from continuity_lab.worker_runtime import encode_work_claim

PRIVATE = "SECRET_SENTINEL"
ENDPOINT = "http://localhost:4318/v1/traces"


def claim(kind=WorkKind.INQUIRY):
    return WorkClaim(
        LeaseGrant("account-a", str(uuid4()), str(uuid4()), 2, "2030-12-01T00:00:30+00:00"),
        kind,
        "owner-a" if kind == WorkKind.WAIT else None,
    )


class MemoryExporter(SpanExporter):
    def __init__(self, fail=False):
        self.spans = []
        self.closed = False
        self.fail = fail

    def export(self, spans):
        if self.fail:
            raise PrivateError(PRIVATE)
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self):
        self.closed = True


class PrivateError(RuntimeError):
    def __str__(self):
        raise AssertionError("Private exception text must never be rendered")


class WorkerTraceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.settings = WorkerSettings.from_env(
            {
                "P1_WORKER_SCOPE": "account-a",
                "P1_WORKER_SUPPLIER_DB": str(self.folder / "supplier.sqlite3"),
                "P1_WORKER_SINK_DB": str(self.folder / "sink.sqlite3"),
                "P1_WORKER_STATE_FILE": str(self.folder / "health.json"),
            }
        )

    def test_child_environment_adds_only_verified_trace_endpoint_and_launcher_preserves_scrub(self):
        environment = {
            "P1_POSTGRES_PASSWORD": "synthetic-runtime",
            "P1_TRACE_ENDPOINT": ENDPOINT,
            "LOCAL_ACCESS_TOKEN": PRIVATE,
            "OTEL_EXPORTER_OTLP_HEADERS": "secret=" + PRIVATE,
            "HTTP_PROXY": "http://untrusted.invalid:8080",
        }
        with patch.dict(os.environ, environment, clear=True):
            child = worker_cli._child_environment(self.settings)
        self.assertEqual(child["P1_TRACE_ENDPOINT"], ENDPOINT)
        self.assertNotIn(PRIVATE, json.dumps(child))
        self.assertNotIn("HTTP_PROXY", child)
        self.assertFalse(any(key.startswith("OTEL_") for key in child))
        launcher = worker_runtime.ProcessStepLauncher(
            (sys.executable, "-m", "continuity_lab.worker_cli", "step"),
            environment=child,
            cwd=self.folder,
        )
        value = claim()
        with patch.object(worker_runtime, "ProcessStepChild") as process:
            launcher.start(value, maximum_output_bytes=4096)
        actual = process.call_args.kwargs["environment"]
        self.assertEqual(actual["P1_TRACE_ENDPOINT"], ENDPOINT)
        self.assertEqual(actual["P1_WORKER_CLAIM"], encode_work_claim(value))
        self.assertEqual(set(actual) - set(child), {"P1_WORKER_CLAIM"})

    def test_provider_trace_mode_survives_only_as_a_fixed_enum_without_forwarding_provider_keys(
        self,
    ):
        for mode in ("scripted", "local_real", "provider_real"):
            with (
                self.subTest(mode=mode),
                patch.dict(
                    os.environ,
                    {
                        "P1_POSTGRES_PASSWORD": "synthetic-runtime",
                        "P1_TRACE_ENDPOINT": ENDPOINT,
                        "P1_TRACE_MODE": mode,
                        "DEEPGRAM_API_KEY": PRIVATE,
                        "OPENAI_API_KEY": PRIVATE,
                        "ELEVEN_API_KEY": PRIVATE,
                        "ELEVENLABS_API_KEY": PRIVATE,
                    },
                    clear=True,
                ),
            ):
                child = worker_cli._child_environment(self.settings)
                self.assertEqual(mode, child["P1_TRACE_MODE"])
                self.assertNotIn(PRIVATE, json.dumps(child))
        for mode in ("provider_real ", "PROVIDER_REAL", "cloud", PRIVATE):
            with (
                self.subTest(mode_type=type(mode).__name__),
                patch.dict(
                    os.environ,
                    {
                        "P1_POSTGRES_PASSWORD": "synthetic-runtime",
                        "P1_TRACE_ENDPOINT": ENDPOINT,
                        "P1_TRACE_MODE": mode,
                    },
                    clear=True,
                ),
                self.assertRaises(ValueError),
            ):
                worker_cli._child_environment(self.settings)

    def test_invalid_external_endpoint_is_rejected_before_child_launch_or_work(self):
        with (
            patch.dict(
                os.environ,
                {"P1_TRACE_ENDPOINT": "http://external.invalid:4318/v1/traces"},
                clear=True,
            ),
            self.assertRaises(ValueError),
        ):
            worker_cli._child_environment(self.settings)
        with (
            patch.dict(
                os.environ,
                {
                    "P1_TRACE_ENDPOINT": "http://external.invalid:4318/v1/traces",
                    "P1_WORKER_CLAIM": encode_work_claim(claim()),
                },
                clear=True,
            ),
            patch.object(worker_cli, "_execute_step") as execute,
            self.assertRaises(ValueError),
        ):
            worker_cli._step(self.settings)
        execute.assert_not_called()

    def test_real_private_provider_records_each_selected_work_kind_task_epoch_and_duration(self):
        for kind in WorkKind:
            with self.subTest(kind=kind):
                value = claim(kind)
                exporter = MemoryExporter()
                runtimes = []

                def create(settings, fixture_exporter=exporter, owned_runtimes=runtimes):
                    runtime = TraceRuntime(settings, exporter=fixture_exporter)
                    owned_runtimes.append(runtime)
                    return runtime

                def work(_settings, _claim):
                    time.sleep(0.005)
                    print('{"status":"step_completed"}')

                with (
                    patch.dict(
                        os.environ,
                        {
                            "P1_TRACE_ENDPOINT": ENDPOINT,
                            "P1_WORKER_CLAIM": encode_work_claim(value),
                        },
                        clear=True,
                    ),
                    patch("continuity_lab.tracing.TraceRuntime", side_effect=create),
                    patch.object(worker_cli, "_execute_step", side_effect=work) as execute,
                    redirect_stdout(io.StringIO()) as output,
                ):
                    worker_cli._step(self.settings)
                execute.assert_called_once_with(self.settings, value)
                self.assertEqual(json.loads(output.getvalue()), {"status": "step_completed"})
                self.assertEqual(len(exporter.spans), 1)
                span = exporter.spans[0]
                self.assertEqual(span.name, "continuity." + kind.value)
                self.assertEqual(span.attributes["continuity.operation"], kind.value)
                self.assertEqual(span.attributes["continuity.task_id"], value.grant.task_id)
                self.assertEqual(span.attributes["continuity.epoch"], value.grant.epoch)
                self.assertEqual(span.attributes["continuity.outcome"], "success")
                self.assertGreaterEqual(span.attributes["continuity.duration_seconds"], 0.005)
                self.assertTrue(exporter.closed)
                self.assertTrue(runtimes[0].processor.closed)

    def test_operation_exception_is_identical_and_has_only_safe_error_trace(self):
        value = claim(WorkKind.MUTATION)
        exporter = MemoryExporter()
        original = PrivateError(PRIVATE)

        def create(settings):
            return TraceRuntime(settings, exporter=exporter)

        with (
            patch.dict(
                os.environ,
                {"P1_TRACE_ENDPOINT": ENDPOINT, "P1_WORKER_CLAIM": encode_work_claim(value)},
                clear=True,
            ),
            patch("continuity_lab.tracing.TraceRuntime", side_effect=create),
            patch.object(worker_cli, "_execute_step", side_effect=original),
            self.assertRaises(PrivateError) as observed,
        ):
            worker_cli._step(self.settings)
        self.assertIs(observed.exception, original)
        self.assertEqual(exporter.spans[0].status.status_code, StatusCode.ERROR)
        self.assertEqual(exporter.spans[0].attributes["continuity.outcome"], "failed")
        self.assertEqual(exporter.spans[0].events, ())
        self.assertIsNone(exporter.spans[0].status.description)
        self.assertNotIn(PRIVATE, json.dumps(dict(exporter.spans[0].attributes)))
        self.assertTrue(exporter.closed)

    def test_failed_export_does_not_change_successful_operation_or_stdout(self):
        exporter = MemoryExporter(fail=True)
        runtimes = []

        def create(settings):
            runtime = TraceRuntime(settings, exporter=exporter)
            runtimes.append(runtime)
            return runtime

        with (
            patch.dict(
                os.environ,
                {"P1_TRACE_ENDPOINT": ENDPOINT, "P1_WORKER_CLAIM": encode_work_claim(claim())},
                clear=True,
            ),
            patch("continuity_lab.tracing.TraceRuntime", side_effect=create),
            patch.object(worker_cli, "_execute_step") as execute,
            redirect_stdout(io.StringIO()) as output,
        ):
            worker_cli._step(self.settings)
        execute.assert_called_once()
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(runtimes[0].processor.failed, 1)
        self.assertTrue(exporter.closed)

    def test_cleanup_errors_cannot_mask_business_failure_and_flush_budget_is_explicit(self):
        exporter = MemoryExporter()
        tracing = TraceRuntime(TraceSettings("durable-worker"), exporter=exporter)
        original = PrivateError(PRIVATE)
        with (
            patch.dict(
                os.environ,
                {"P1_TRACE_ENDPOINT": ENDPOINT, "P1_WORKER_CLAIM": encode_work_claim(claim())},
                clear=True,
            ),
            patch("continuity_lab.tracing.TraceRuntime", return_value=tracing),
            patch.object(
                tracing.provider, "force_flush", side_effect=PrivateError(PRIVATE)
            ) as flush,
            patch.object(tracing, "close", side_effect=PrivateError(PRIVATE)) as close,
            patch.object(worker_cli, "_execute_step", side_effect=original),
            patch.object(worker_cli, "_event") as event,
            self.assertRaises(PrivateError) as observed,
        ):
            worker_cli._step(self.settings)
        self.assertIs(observed.exception, original)
        flush.assert_called_once_with(timeout_millis=300)
        close.assert_called_once()
        self.assertEqual(event.call_count, 2)
        self.assertTrue(tracing.close())

    def test_no_endpoint_fresh_interpreter_completes_without_importing_optional_otel(self):
        code = textwrap.dedent("""
            import builtins, os
            original = builtins.__import__
            def guarded(name, *args, **kwargs):
                if name.startswith('opentelemetry') or name == 'httpx':
                    raise AssertionError('Base step imported optional tracing dependency')
                return original(name, *args, **kwargs)
            builtins.__import__ = guarded
            from continuity_lab import worker_cli
            from continuity_lab.lease_models import LeaseGrant, WorkClaim, WorkKind
            from continuity_lab.worker_runtime import encode_work_claim
            settings = worker_cli.WorkerSettings.from_env({'P1_WORKER_SCOPE':'account-a'})
            claim = WorkClaim(LeaseGrant('account-a','task-a','00000000-0000-4000-8000-000000000001',1,'2030-12-01T00:00:30+00:00'),WorkKind.INQUIRY)
            os.environ.clear()
            os.environ['P1_WORKER_CLAIM'] = encode_work_claim(claim)
            calls=[]
            worker_cli._execute_step = lambda settings, value: calls.append(value)
            worker_cli._step(settings)
            assert calls == [claim]
        """)
        result = subprocess.run(
            [sys.executable, "-c", code],
            env=os.environ.copy(),
            capture_output=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode())
