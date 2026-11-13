"""Bounded, content-free application/SDK traces for an optional local OTLP sink.

A private provider and owned worker keep exporting off application event loops.
Only explicitly allowlisted fields reach the exporter; original SDK spans are
never mutated. Failed telemetry is an observation, never business authority.
"""

from __future__ import annotations

import logging
import math
import queue
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.common._internal.trace_encoder import encode_spans
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanLimits, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.sdk.util.instrumentation import InstrumentationScope
from opentelemetry.trace import SpanContext, SpanKind, Status, StatusCode, TraceState

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
SERVICES = frozenset({"business-api", "conversation-agent", "durable-worker"})
OPERATIONS = frozenset(
    {
        "submit",
        "get",
        "quote",
        "signal",
        "cancel",
        "inquiry",
        "wait",
        "mutation",
        "delivery",
        "interrupt",
        "session",
        "shutdown",
    }
)
SPAN_NAMES = frozenset({"continuity." + value for value in OPERATIONS}) | frozenset(
    {
        "job_entrypoint",
        "agent_session",
        "start_agent_activity",
        "llm_node",
        "stt_node",
        "tts_node",
        "function_tool",
        "agent_turn",
        "user_turn",
        "speech_handle",
        "realtime_model",
    }
)
ATTR_ENUMS: dict[str, frozenset[str]] = {
    "continuity.operation": OPERATIONS,
    "continuity.outcome": frozenset(
        {"success", "rejected", "failed", "uncertain", "cancelled", "interrupted"}
    ),
    "continuity.mode": frozenset({"scripted", "local_real", "provider_real"}),
    "continuity.backend": frozenset({"postgres"}),
    "gen_ai.operation.name": frozenset(
        {"chat", "speech_to_text", "text_to_speech", "execute_tool"}
    ),
    "gen_ai.provider.name": frozenset({"deepgram", "openai", "elevenlabs"}),
    "gen_ai.request.model": frozenset(
        {
            "scripted-business-v1",
            "scripted-audio-turn-v1",
            "scripted-pcm-speech-v1",
            "qwen3:4b-instruct",
            "base.en",
            "en_US-ljspeech-medium",
            "nova-3",
            "gpt-5.4-mini",
            "eleven_v4_turbo",
        }
    ),
    "gen_ai.tool.name": frozenset({"submit_investigation", "get_case", "cancel_case"}),
}
NUMERIC = frozenset(
    {
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
        "continuity.attempt",
        "continuity.epoch",
        "continuity.audio_frames",
        "continuity.duration_seconds",
    }
)
UUID_ATTRS = frozenset({"continuity.task_id", "continuity.effect_id"})


def _event(event: str) -> None:
    try:
        LOGGER.info(event, extra={"event": event, "code": "ok"})
    except Exception:  # noqa: BLE001 - telemetry cannot change application results
        return


@dataclass(frozen=True, slots=True)
class TraceSettings:
    service: str
    endpoint: str | None = None
    queue_size: int = 128
    export_timeout: float = 0.5
    shutdown_timeout: float = 1.5
    mode: str = "scripted"

    def __post_init__(self) -> None:
        if type(self.mode) is not str or self.mode not in {
            "scripted",
            "local_real",
            "provider_real",
        }:
            raise ValueError("A fixed trace profile mode is required")
        if self.service not in SERVICES:
            raise ValueError("A fixed trace service is required")
        if type(self.queue_size) is not int or not 1 <= self.queue_size <= 1024:
            raise ValueError("Trace queue must have a finite capacity")
        for value, maximum in ((self.export_timeout, 1.0), (self.shutdown_timeout, 2.0)):
            if (
                type(value) not in (int, float)
                or not 0 < value <= maximum
                or not math.isfinite(value)
            ):
                raise ValueError("Trace deadlines must be finite and bounded")
        if self.endpoint is not None:
            parsed = urlsplit(self.endpoint)
            if (
                parsed.scheme != "http"
                or parsed.hostname not in {"127.0.0.1", "localhost", "jaeger"}
                or parsed.path != "/v1/traces"
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("Only a credential-free local OTLP trace endpoint is supported")
            if parsed.port is None or not 1 <= parsed.port <= 65535:
                raise ValueError("A finite local OTLP port is required")


PROVIDER_ALIASES = {"Deepgram": "deepgram", "ElevenLabs": "elevenlabs"}


def safe_attributes(values: Mapping[str, Any] | None) -> dict[str, str | int | float]:
    result: dict[str, str | int | float] = {}
    for key, value in (values or {}).items():
        if key == "gen_ai.provider.name" and type(value) is str:
            value = PROVIDER_ALIASES.get(value, value)
        if (
            key in ATTR_ENUMS
            and type(value) is str
            and value in ATTR_ENUMS[key]
            or key in NUMERIC
            and type(value) in (int, float)
            and 0 <= value <= 9223372036854775807
            and (type(value) is int or math.isfinite(value))
        ):
            result[key] = value
        elif key in UUID_ATTRS and type(value) is str:
            try:
                if str(UUID(value)) == value:
                    result[key] = value
            except ValueError:
                continue
    return result


def clean_context(value: SpanContext | None) -> SpanContext | None:
    if value is None:
        return None
    return SpanContext(
        value.trace_id, value.span_id, value.is_remote, value.trace_flags, TraceState()
    )


def sanitized_span(span: ReadableSpan, service: str, mode: str = "scripted") -> ReadableSpan:
    """Copy only non-content identity/clock/enum metadata into a fresh span."""
    if (
        service not in SERVICES
        or type(mode) is not str
        or mode not in {"scripted", "local_real", "provider_real"}
    ):
        raise ValueError("A fixed trace service and profile mode are required")
    return ReadableSpan(
        name=span.name if span.name in SPAN_NAMES else "continuity.sdk",
        context=clean_context(span.context),
        parent=clean_context(span.parent),
        resource=Resource(
            {"service.name": service, "service.version": "0.1.0", "continuity.mode": mode}
        ),
        attributes=safe_attributes(span.attributes),
        events=(),
        links=(),
        kind=span.kind if isinstance(span.kind, SpanKind) else SpanKind.INTERNAL,
        status=Status(span.status.status_code),
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=InstrumentationScope("continuity.safe", "1"),
    )


class LocalHTTPSpanExporter(SpanExporter):
    """Own the local HTTP boundary without environment credentials or retries.

    The official pinned OTLP encoder supplies the wire format. An explicit HTTP
    client ignores proxy/certificate/auth environment hooks. Responses are closed
    after status inspection without reading arbitrary response bodies.
    """

    MAX_REQUEST_BYTES = 65536

    def __init__(self, settings: TraceSettings) -> None:
        if settings.endpoint is None:
            raise ValueError("An explicit local OTLP endpoint is required")
        self._endpoint = settings.endpoint
        self._closed = False
        self._client = httpx.Client(
            trust_env=False,
            timeout=settings.export_timeout,
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
            follow_redirects=False,
        )

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        if self._closed or not 0 < len(spans) <= 32:
            return SpanExportResult.FAILURE
        try:
            request = encode_spans(spans)
            if request.ByteSize() > self.MAX_REQUEST_BYTES:
                return SpanExportResult.FAILURE
            with self._client.stream(
                "POST",
                self._endpoint,
                content=request.SerializeToString(),
                headers={"content-type": "application/x-protobuf"},
            ) as response:
                return (
                    SpanExportResult.SUCCESS
                    if response.status_code == 200
                    else SpanExportResult.FAILURE
                )
        except Exception:  # noqa: BLE001 - never format network exception or response content
            return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        if not self._closed:
            self._closed = True
            self._client.close()


class BoundedTraceProcessor(SpanProcessor):
    """One finite export queue with explicit, observable shutdown ownership."""

    def __init__(self, settings: TraceSettings, exporter: SpanExporter) -> None:
        self.settings, self.exporter = settings, exporter
        self._queue: queue.Queue[ReadableSpan] = queue.Queue(maxsize=settings.queue_size)
        self._closing = threading.Event()
        self._changed = threading.Condition()
        self._pending = 0
        self.dropped = self.exported = self.failed = 0
        self._thread = threading.Thread(
            target=self._run, name="continuity-trace-export", daemon=True
        )
        self._thread.start()

    def on_start(self, span: Span, parent_context: Any = None) -> None:
        return

    def on_end(self, span: ReadableSpan) -> None:
        if self._closing.is_set():
            return
        try:
            clean = sanitized_span(span, self.settings.service, self.settings.mode)
            with self._changed:
                if self._closing.is_set():
                    self.dropped += 1
                    return
                self._queue.put_nowait(clean)
                self._pending += 1
        except queue.Full:
            self.dropped += 1
        except Exception:  # noqa: BLE001 - untrusted SDK diagnostic fields fail closed
            self.failed += 1

    def _run(self) -> None:
        try:
            while not self._closing.is_set() or not self._queue.empty():
                try:
                    value = self._queue.get(timeout=0.05)
                except queue.Empty:
                    continue
                try:
                    result = self.exporter.export((value,))
                    if result == SpanExportResult.SUCCESS:
                        self.exported += 1
                    else:
                        self.failed += 1
                except Exception:  # noqa: BLE001 - never serialize exporter errors
                    self.failed += 1
                finally:
                    self._queue.task_done()
                    with self._changed:
                        self._pending -= 1
                        self._changed.notify_all()
        finally:
            try:
                self.exporter.shutdown()
            except Exception:  # noqa: BLE001 - exporter cleanup cannot escape the worker
                self.failed += 1

    def force_flush(self, timeout_millis: int = 1000) -> bool:
        if type(timeout_millis) is not int or not 0 <= timeout_millis <= 2000:
            raise ValueError("Trace flush deadline must be within two seconds")
        deadline = time.monotonic() + timeout_millis / 1000
        with self._changed:
            while self._pending:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._changed.wait(remaining)
        return True

    def shutdown(self) -> None:
        self._closing.set()
        # Drop queued observations at shutdown; only current finite HTTP export
        # may finish. Business work is never retained in this queue.
        with self._changed:
            while True:
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                    self._pending -= 1
                    self.dropped += 1
                except queue.Empty:
                    break
            self._changed.notify_all()
        self._thread.join(self.settings.shutdown_timeout)
        if self._thread.is_alive():
            _event("trace_shutdown_incomplete")

    @property
    def closed(self) -> bool:
        return not self._thread.is_alive()


class TraceRuntime:
    def __init__(self, settings: TraceSettings, *, exporter: SpanExporter | None = None) -> None:
        self.mode = settings.mode
        self.provider = TracerProvider(
            shutdown_on_exit=False,
            resource=Resource({"service.name": settings.service, "continuity.mode": settings.mode}),
            span_limits=SpanLimits(
                max_attributes=32,
                max_events=8,
                max_links=0,
                max_attribute_length=128,
                max_span_attribute_length=128,
            ),
        )
        self.processor: BoundedTraceProcessor | None = None
        if exporter is not None or settings.endpoint is not None:
            actual = exporter if exporter is not None else LocalHTTPSpanExporter(settings)
            self.processor = BoundedTraceProcessor(settings, actual)
            self.provider.add_span_processor(self.processor)
        self.tracer = self.provider.get_tracer("continuity", "1")
        self._closed = False
        self._close_ok = True

    @contextmanager
    def span(self, operation: str, **attributes: str | float) -> Iterator[trace.Span]:
        if operation not in OPERATIONS:
            raise ValueError("A fixed trace operation is required")
        values = {"continuity.operation": operation, **attributes}
        with self.tracer.start_as_current_span(
            "continuity." + operation,
            attributes=safe_attributes(values),
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                yield span
            except BaseException:
                # Preserve cancellation/fatal exceptions; no exception event/body.
                span.set_status(StatusCode.ERROR)
                span.set_attribute("continuity.outcome", "failed")
                raise
            else:
                span.set_attribute("continuity.outcome", "success")

    def close(self) -> bool:
        if not self._closed:
            self._closed = True
            try:
                self.provider.shutdown()
            except Exception:  # noqa: BLE001 - diagnostics cannot mask a business result
                _event("trace_shutdown_incomplete")
                self._close_ok = False
        self._close_ok = self._close_ok and (self.processor is None or self.processor.closed)
        return self._close_ok
