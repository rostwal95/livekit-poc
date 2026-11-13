"""Content-free local OTLP traces, bounded export ownership and outage behavior."""

import asyncio
import json
import logging
import math
import threading
import time
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from uuid import uuid4

from opentelemetry import trace
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import Event, ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.sdk.util.instrumentation import InstrumentationScope
from opentelemetry.trace import (
    Link,
    SpanContext,
    SpanKind,
    Status,
    StatusCode,
    TraceFlags,
    TraceState,
)

from continuity_lab.tracing import (
    ATTR_ENUMS,
    NUMERIC,
    BoundedTraceProcessor,
    LocalHTTPSpanExporter,
    TraceRuntime,
    TraceSettings,
    safe_attributes,
    sanitized_span,
)

PRIVATE = "SECRET_SENTINEL"


def private_span():
    context = SpanContext(123, 456, False, TraceFlags(1), TraceState([("private", PRIVATE)]))
    parent = SpanContext(123, 455, True, TraceFlags(1), TraceState([("tenant", PRIVATE)]))
    return ReadableSpan(
        name="raw-private-" + PRIVATE,
        context=context,
        parent=parent,
        resource=Resource({"service.name": PRIVATE, "authorization": PRIVATE}),
        attributes={
            "continuity.operation": "submit",
            "continuity.outcome": "success",
            "continuity.task_id": str(uuid4()),
            "gen_ai.usage.input_tokens": 2,
            "transcript": PRIVATE,
            "authorization": PRIVATE,
            "gen_ai.tool.name": PRIVATE,
        },
        events=(Event("exception", {"exception.message": PRIVATE}, 3),),
        links=(Link(context, {"secret": PRIVATE}),),
        kind=SpanKind.SERVER,
        status=Status(StatusCode.ERROR, PRIVATE),
        start_time=1,
        end_time=5,
        instrumentation_scope=InstrumentationScope(
            PRIVATE, PRIVATE, attributes={"private": PRIVATE}
        ),
    )


class MemoryExporter(SpanExporter):
    def __init__(self):
        self.spans = []
        self.shutdowns = 0

    def export(self, spans):
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self):
        self.shutdowns += 1


@contextmanager
def receiver(*, delay=0.0, status=200, response=b"", body_gate=None):
    state = {"bodies": [], "headers": [], "received": threading.Event()}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            state["bodies"].append(self.rfile.read(length))
            state["headers"].append(dict(self.headers))
            state["received"].set()
            if delay:
                time.sleep(delay)
            self.send_response(status)
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            if body_gate is not None:
                body_gate.wait(timeout=2)
            try:
                self.wfile.write(response)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.02), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1/traces", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


class AttributeTests(unittest.TestCase):
    def test_allowlist_accepts_only_enums_canonical_uuid_and_finite_nonnegative_numbers(self):
        values = {key: next(iter(allowed)) for key, allowed in ATTR_ENUMS.items()}
        task_id = str(uuid4())
        values.update({key: 2 for key in NUMERIC})
        values.update({"continuity.task_id": task_id, "unknown": PRIVATE})
        result = safe_attributes(values)
        self.assertNotIn("unknown", result)
        self.assertEqual(result["continuity.task_id"], task_id)
        for bad in (True, False, -1, float("inf"), float("-inf"), math.nan, 10**1000, "1", [1]):
            for key in NUMERIC:
                with self.subTest(kind=type(bad).__name__, key=key):
                    self.assertEqual(safe_attributes({key: bad}), {})
        self.assertEqual(safe_attributes({"continuity.task_id": task_id.upper()}), {})
        self.assertEqual(safe_attributes({"continuity.task_id": "{" + task_id + "}"}), {})
        self.assertEqual(safe_attributes({key: PRIVATE for key in ATTR_ENUMS}), {})
        self.assertEqual(safe_attributes(None), {})

    def test_sanitization_copies_span_and_preserves_original_diagnostic_without_exporting_it(self):
        source = private_span()
        clean = sanitized_span(source, "conversation-agent")
        self.assertIsNot(clean, source)
        self.assertEqual(clean.name, "continuity.sdk")
        self.assertEqual(clean.context.trace_id, source.context.trace_id)
        self.assertEqual(clean.context.span_id, source.context.span_id)
        self.assertEqual(clean.parent.span_id, source.parent.span_id)
        self.assertEqual(clean.context.trace_state.to_header(), "")
        self.assertEqual(clean.parent.trace_state.to_header(), "")
        self.assertEqual(clean.status.status_code, StatusCode.ERROR)
        self.assertIsNone(clean.status.description)
        self.assertEqual(clean.events, ())
        self.assertEqual(clean.links, ())
        self.assertEqual(clean.resource.attributes["service.name"], "conversation-agent")
        self.assertEqual(clean.instrumentation_scope.name, "continuity.safe")
        self.assertNotIn(PRIVATE, json.dumps(dict(clean.attributes)))
        self.assertEqual(source.context.trace_state["private"], PRIVATE)
        self.assertEqual(source.parent.trace_state["tenant"], PRIVATE)
        self.assertEqual(source.attributes["transcript"], PRIVATE)
        self.assertEqual(source.events[0].attributes["exception.message"], PRIVATE)
        self.assertEqual(source.links[0].attributes["secret"], PRIVATE)
        self.assertEqual(source.status.description, PRIVATE)
        self.assertEqual(source.resource.attributes["authorization"], PRIVATE)

    def test_real_profile_exports_only_fixed_mode_and_model_without_content(self):
        exporter = MemoryExporter()
        runtime = TraceRuntime(
            TraceSettings("conversation-agent", mode="local_real"), exporter=exporter
        )
        with runtime.span(
            "session", **{"gen_ai.request.model": "qwen3:4b-instruct", "prompt": PRIVATE}
        ):
            pass
        self.assertTrue(runtime.provider.force_flush(timeout_millis=500))
        self.assertTrue(runtime.close())
        self.assertEqual(len(exporter.spans), 1)
        span = exporter.spans[0]
        self.assertEqual(span.resource.attributes["continuity.mode"], "local_real")
        self.assertEqual(span.attributes["gen_ai.request.model"], "qwen3:4b-instruct")
        self.assertNotIn(PRIVATE, json.dumps(dict(span.attributes)))
        self.assertEqual(safe_attributes({"gen_ai.request.model": PRIVATE}), {})
        for mode in (PRIVATE, True, None):
            with self.subTest(mode_type=type(mode).__name__), self.assertRaises(ValueError):
                TraceSettings("conversation-agent", mode=mode)

    def test_provider_profile_uses_only_three_fixed_model_names_and_drops_credentials_content(self):
        exporter = MemoryExporter()
        runtime = TraceRuntime(
            TraceSettings("conversation-agent", mode="provider_real"), exporter=exporter
        )
        for model, provider in (
            ("nova-3", "deepgram"),
            ("gpt-5.4-mini", "openai"),
            ("eleven_v4_turbo", "elevenlabs"),
        ):
            with runtime.span(
                "session",
                **{
                    "gen_ai.request.model": model,
                    "gen_ai.provider.name": provider,
                    "authorization": PRIVATE,
                    "api_key": PRIVATE,
                    "transcript": PRIVATE,
                },
            ):
                pass
        self.assertTrue(runtime.provider.force_flush(timeout_millis=500))
        self.assertTrue(runtime.close())
        self.assertEqual(3, len(exporter.spans))
        self.assertEqual(
            {"nova-3", "gpt-5.4-mini", "eleven_v4_turbo"},
            {span.attributes["gen_ai.request.model"] for span in exporter.spans},
        )
        self.assertEqual(
            {"deepgram", "openai", "elevenlabs"},
            {span.attributes["gen_ai.provider.name"] for span in exporter.spans},
        )
        for span in exporter.spans:
            self.assertEqual("provider_real", span.resource.attributes["continuity.mode"])
            self.assertNotIn(PRIVATE, json.dumps(dict(span.attributes)))
        self.assertEqual(
            {},
            safe_attributes(
                {
                    "gen_ai.request.model": "arbitrary-" + PRIVATE,
                    "provider.name": PRIVATE,
                    "gen_ai.provider.name": PRIVATE,
                }
            ),
        )
        # The rejected initial candidate remains historical evidence, not a runtime fallback.
        self.assertEqual({}, safe_attributes({"gen_ai.request.model": "gpt-6-luna"}))
        for invalid in ("provider_real ", "PROVIDER_REAL", "cloud"):
            with self.subTest(mode=invalid), self.assertRaises(ValueError):
                TraceSettings("conversation-agent", mode=invalid)

    def test_exact_official_provider_aliases_normalize_only_sanitized_copies(self):
        for alias, canonical, model in (
            ("Deepgram", "deepgram", "nova-3"),
            ("ElevenLabs", "elevenlabs", "eleven_v4_turbo"),
        ):
            values = {
                "gen_ai.provider.name": alias,
                "gen_ai.request.model": model,
                "prompt": PRIVATE,
            }
            original = dict(values)
            source = ReadableSpan(
                name="stt_node",
                context=private_span().context,
                attributes=values,
                resource=Resource({"service.name": PRIVATE}),
                status=Status(StatusCode.OK),
                start_time=1,
                end_time=2,
            )
            clean = sanitized_span(source, "conversation-agent", mode="provider_real")
            self.assertEqual(canonical, clean.attributes["gen_ai.provider.name"])
            self.assertEqual(model, clean.attributes["gen_ai.request.model"])
            self.assertEqual(alias, source.attributes["gen_ai.provider.name"])
            self.assertEqual(PRIVATE, source.attributes["prompt"])
            self.assertEqual(original, values)
            self.assertNotIn(PRIVATE, json.dumps(dict(clean.attributes)))

    def test_provider_aliases_do_not_broaden_the_fixed_catalog_or_other_attribute_fields(self):
        for value in (
            "DeepGram",
            "DEEPGRAM",
            "Elevenlabs",
            "ELEVENLABS",
            "ElevenLabs ",
            "OpenAI",
            "local-whisper",
            PRIVATE,
            "Deepgram" + PRIVATE,
            True,
            None,
            [],
        ):
            with self.subTest(kind=type(value).__name__):
                self.assertEqual({}, safe_attributes({"gen_ai.provider.name": value}))
        self.assertEqual(
            {},
            safe_attributes(
                {
                    "gen_ai.request.model": "Deepgram",
                    "gen_ai.tool.name": "ElevenLabs",
                    "provider.name": "Deepgram",
                }
            ),
        )
        for provider in ("deepgram", "openai", "elevenlabs"):
            self.assertEqual(
                {"gen_ai.provider.name": provider},
                safe_attributes({"gen_ai.provider.name": provider}),
            )

    def test_settings_reject_external_credentialled_unbounded_or_nonfinite_configuration(self):
        for overrides in (
            {"service": PRIVATE},
            {"queue_size": True},
            {"queue_size": 0},
            {"queue_size": 1025},
            {"export_timeout": True},
            {"export_timeout": 0},
            {"export_timeout": math.inf},
            {"export_timeout": 10**1000},
            {"shutdown_timeout": 2.1},
            {"shutdown_timeout": 10**1000},
            {"endpoint": "https://127.0.0.1:4318/v1/traces"},
            {"endpoint": "http://external.invalid:4318/v1/traces"},
            {"endpoint": "http://secret@localhost:4318/v1/traces"},
            {"endpoint": "http://localhost:4318/v1/traces?secret=value"},
            {"endpoint": "http://localhost/v1/traces"},
            {"endpoint": "http://localhost:4318/private"},
        ):
            options = {"service": "business-api", **overrides}
            with self.subTest(fields=tuple(overrides)), self.assertRaises(ValueError):
                TraceSettings(**options)
        self.assertEqual(TraceSettings("business-api").queue_size, 128)


class ProcessorTests(unittest.TestCase):
    def test_finite_queue_drops_overflow_and_shutdown_preserves_an_inflight_export_bound(self):
        entered, release = threading.Event(), threading.Event()

        class BlockingExporter(MemoryExporter):
            def export(self, spans):
                entered.set()
                release.wait(timeout=2)
                return super().export(spans)

        exporter = BlockingExporter()
        processor = BoundedTraceProcessor(
            TraceSettings("business-api", queue_size=1, shutdown_timeout=0.05), exporter
        )
        try:
            processor.on_end(private_span())
            self.assertTrue(entered.wait(timeout=1))
            processor.on_end(private_span())
            processor.on_end(private_span())
            self.assertEqual(processor.dropped, 1)
            self.assertFalse(processor.force_flush(0))
            started = time.monotonic()
            processor.shutdown()
            self.assertLess(time.monotonic() - started, 0.3)
            self.assertFalse(processor.closed)
            self.assertEqual(processor.dropped, 2)
            self.assertTrue(processor.force_flush(0) is False)
            processor.on_end(private_span())
        finally:
            release.set()
            processor._thread.join(timeout=1)
        self.assertTrue(processor.closed)
        self.assertEqual(processor.exported, 1)
        self.assertEqual(exporter.shutdowns, 1)
        self.assertTrue(processor.force_flush(100))
        self.assertEqual(len(exporter.spans), 1)

    def test_shutdown_racing_a_sanitizer_cannot_enqueue_after_export_thread_has_exited(self):
        entered, release = threading.Event(), threading.Event()
        exporter = MemoryExporter()
        processor = BoundedTraceProcessor(TraceSettings("business-api"), exporter)
        original = sanitized_span

        def gated(span, service, mode="scripted"):
            entered.set()
            release.wait(timeout=1)
            return original(span, service, mode)

        with patch("continuity_lab.tracing.sanitized_span", side_effect=gated):
            producer = threading.Thread(target=lambda: processor.on_end(private_span()))
            producer.start()
            try:
                self.assertTrue(entered.wait(timeout=1))
                processor.shutdown()
                self.assertTrue(processor.closed)
            finally:
                release.set()
                producer.join(timeout=1)
        self.assertFalse(producer.is_alive())
        self.assertEqual(processor.exported, 0)
        self.assertTrue(processor.force_flush(100))
        self.assertTrue(processor._queue.empty())
        self.assertEqual(processor.dropped, 1)

    def test_shutdown_error_is_contained_and_repeated_close_preserves_failure(self):
        class PrivateError(RuntimeError):
            def __str__(self):
                raise AssertionError("Private shutdown exception text was read")

        runtime = TraceRuntime(TraceSettings("business-api"))
        with patch.object(runtime.provider, "shutdown", side_effect=PrivateError(PRIVATE)):
            self.assertFalse(runtime.close())
            self.assertFalse(runtime.close())

    def test_private_sdk_provider_bounds_raw_attributes_events_and_links(self):
        runtime = TraceRuntime(TraceSettings("business-api"))
        before = trace.get_tracer_provider()
        span = runtime.tracer.start_span("llm_node")
        for index in range(40):
            span.set_attribute(f"raw-{index}", PRIVATE * 100)
        for index in range(16):
            span.add_event(f"raw-event-{index}", {"raw": PRIVATE * 100})
        self.assertLessEqual(len(span.attributes), 32)
        self.assertTrue(all(len(value) <= 128 for value in span.attributes.values()))
        self.assertLessEqual(len(span.events), 8)
        self.assertEqual(len(span.links), 0)
        span.end()
        self.assertTrue(runtime.close())
        self.assertIs(trace.get_tracer_provider(), before)

    def test_exporter_failure_and_shutdown_failure_never_render_private_exception(self):
        class PrivateError(RuntimeError):
            def __str__(self):
                raise AssertionError("Private exporter error text was read")

        class FailedExporter(MemoryExporter):
            def export(self, spans):
                raise PrivateError(PRIVATE)

            def shutdown(self):
                self.shutdowns += 1
                raise PrivateError(PRIVATE)

        exporter = FailedExporter()
        processor = BoundedTraceProcessor(TraceSettings("business-api"), exporter)
        processor.on_end(private_span())
        self.assertTrue(processor.force_flush(1000))
        processor.shutdown()
        self.assertTrue(processor.closed)
        self.assertEqual(processor.failed, 2)
        self.assertEqual(exporter.shutdowns, 1)
        for invalid in (-1, 2001, True, 0.1):
            with self.subTest(kind=type(invalid).__name__), self.assertRaises(ValueError):
                processor.force_flush(invalid)

    def test_runtime_records_fixed_success_and_error_without_exception_event_or_global_provider(
        self,
    ):
        exporter = MemoryExporter()
        runtime = TraceRuntime(TraceSettings("durable-worker"), exporter=exporter)
        with runtime.span("inquiry", **{"continuity.attempt": 1}):
            pass
        with self.assertRaisesRegex(RuntimeError, PRIVATE), runtime.span("mutation"):
            raise RuntimeError(PRIVATE)
        with self.assertRaises(asyncio.CancelledError), runtime.span("wait"):
            raise asyncio.CancelledError()
        self.assertTrue(runtime.processor.force_flush(1000))
        self.assertEqual(len(exporter.spans), 3)
        self.assertEqual(
            [span.attributes["continuity.outcome"] for span in exporter.spans],
            ["success", "failed", "failed"],
        )
        self.assertTrue(all(not span.events and not span.links for span in exporter.spans))
        self.assertTrue(all(span.status.description is None for span in exporter.spans))
        self.assertEqual(exporter.spans[1].status.status_code, StatusCode.ERROR)
        self.assertTrue(runtime.close())
        self.assertTrue(runtime.close())
        self.assertEqual(exporter.shutdowns, 1)
        with self.assertRaises(ValueError), runtime.span(PRIVATE):
            pass

    def test_disabled_runtime_owns_no_export_thread(self):
        before = tuple(threading.enumerate())
        runtime = TraceRuntime(TraceSettings("business-api"))
        with runtime.span("get"):
            pass
        self.assertIsNone(runtime.processor)
        self.assertTrue(runtime.close())
        self.assertEqual(tuple(threading.enumerate()), before)


class HTTPExportTests(unittest.TestCase):
    def test_real_otlp_protobuf_contains_only_safe_fields_and_excludes_environment_headers(self):
        with (
            receiver() as (endpoint, state),
            patch.dict(
                "os.environ",
                {
                    "OTEL_EXPORTER_OTLP_HEADERS": "private=" + PRIVATE,
                    "OTEL_EXPORTER_OTLP_TRACES_HEADERS": "private=" + PRIVATE,
                },
            ),
        ):
            runtime = TraceRuntime(TraceSettings("conversation-agent", endpoint=endpoint))
            try:
                runtime.processor.on_end(private_span())
                self.assertTrue(runtime.processor.force_flush(1800))
                self.assertEqual(runtime.processor.exported, 1)
                self.assertEqual(len(state["bodies"]), 1)
                self.assertNotIn(PRIVATE.encode(), state["bodies"][0])
                self.assertNotIn(PRIVATE, json.dumps(state["headers"]))
                request = ExportTraceServiceRequest.FromString(state["bodies"][0])
                self.assertEqual(len(request.resource_spans), 1)
                resource = request.resource_spans[0]
                self.assertEqual(resource.scope_spans[0].scope.name, "continuity.safe")
                span = resource.scope_spans[0].spans[0]
                self.assertEqual(span.name, "continuity.sdk")
                self.assertEqual(span.trace_state, "")
                self.assertEqual(span.events, [])
                self.assertEqual(span.links, [])
                self.assertEqual(span.status.message, "")
                attributes = {item.key for item in span.attributes}
                self.assertEqual(
                    attributes,
                    {
                        "continuity.operation",
                        "continuity.outcome",
                        "continuity.task_id",
                        "gen_ai.usage.input_tokens",
                    },
                )
            finally:
                self.assertTrue(runtime.close())

    def test_exporter_refuses_oversize_protobuf_and_closed_export_without_any_http_request(self):
        with receiver() as (endpoint, state):
            exporter = LocalHTTPSpanExporter(TraceSettings("business-api", endpoint=endpoint))
            large = private_span()
            large._attributes = {"unsafe-large-fixture": "x" * 70000}
            self.assertEqual(exporter.export((large,)), SpanExportResult.FAILURE)
            self.assertEqual(
                exporter.export(tuple(private_span() for _ in range(33))), SpanExportResult.FAILURE
            )
            exporter.shutdown()
            exporter.shutdown()
            self.assertEqual(exporter.export((private_span(),)), SpanExportResult.FAILURE)
            self.assertEqual(state["bodies"], [])

    def test_success_status_does_not_wait_for_or_read_large_response_body(self):
        gate = threading.Event()
        with receiver(response=PRIVATE.encode() * 10000, body_gate=gate) as (endpoint, state):
            runtime = TraceRuntime(TraceSettings("business-api", endpoint=endpoint))
            try:
                started = time.monotonic()
                with runtime.span("get"):
                    pass
                self.assertTrue(runtime.processor.force_flush(500))
                self.assertLess(time.monotonic() - started, 0.5)
                self.assertEqual(runtime.processor.exported, 1)
                self.assertTrue(state["received"].is_set())
                self.assertFalse(gate.is_set())
            finally:
                gate.set()
                self.assertTrue(runtime.close())

    def test_real_http_timeout_does_not_block_business_or_bounded_shutdown(self):
        with receiver(delay=0.7) as (endpoint, state):
            runtime = TraceRuntime(TraceSettings("business-api", endpoint=endpoint))
            started = time.monotonic()
            with runtime.span("get"):
                business_result = "unchanged"
            self.assertLess(time.monotonic() - started, 0.1)
            self.assertEqual(business_result, "unchanged")
            self.assertTrue(state["received"].wait(timeout=1))
            self.assertTrue(runtime.processor.force_flush(1800))
            self.assertGreaterEqual(runtime.processor.failed, 1)
            started = time.monotonic()
            self.assertTrue(runtime.close())
            self.assertLess(time.monotonic() - started, 1.6)

    def test_real_http_outage_counts_failure_without_logging_response_or_exception_body(self):
        records = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(record)

        logger = logging.getLogger("opentelemetry.exporter")
        capture = Capture()
        logger.addHandler(capture)
        try:
            with receiver(status=503, response=PRIVATE.encode()) as (endpoint, state):
                runtime = TraceRuntime(TraceSettings("business-api", endpoint=endpoint))
                try:
                    with runtime.span("submit"):
                        pass
                    self.assertTrue(runtime.processor.force_flush(1800))
                    self.assertTrue(state["received"].is_set())
                    self.assertGreaterEqual(runtime.processor.failed, 1)
                finally:
                    self.assertTrue(runtime.close())
        finally:
            logger.removeHandler(capture)
        rendered = [logging.Formatter().format(record) for record in records]
        self.assertNotIn(PRIVATE, "\n".join(rendered))
