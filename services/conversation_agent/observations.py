"""Numeric SDK usage/report observations, with finite local retention and no content."""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import time
from pathlib import Path
from uuid import uuid4

from livekit.agents import AgentSession, JobContext
from livekit.agents.metrics.usage import LLMModelUsage, STTModelUsage, TTSModelUsage
from livekit.agents.telemetry import set_tracer_provider
from livekit.agents.voice.events import SessionUsageUpdatedEvent

from continuity_lab.tracing import TraceRuntime

from .telemetry import emit

DIRECTORY = Path("/tmp/conversation-observations")
FIELDS = (
    "llm_input_tokens",
    "llm_output_tokens",
    "stt_audio_seconds",
    "tts_audio_seconds",
    "tts_characters",
    "usage_updates",
    "report_events",
    "report_duration_seconds",
    "trace_exported",
    "trace_dropped",
    "trace_failed",
)


def finite(value: object) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    if not 0 <= value <= 9223372036854775807:
        return 0
    return value if type(value) is int or math.isfinite(value) else 0


class SessionObserver:
    def __init__(self, session: AgentSession[None], tracing: TraceRuntime) -> None:
        self.tracing = tracing
        self.mode = tracing.mode
        self.values: dict[str, float | int] = dict.fromkeys(FIELDS, 0)
        self._closed = False
        self._report_observed = False
        self._started = time.monotonic()
        self._span = tracing.tracer.start_span(
            "continuity.session", attributes={"continuity.mode": self.mode}
        )
        set_tracer_provider(tracing.provider, allow_pii=False)
        session.on("session_usage_updated", self._usage)

    def _usage(self, event: SessionUsageUpdatedEvent) -> None:
        self.values["usage_updates"] = min(self.values["usage_updates"] + 1, 10000)
        totals = dict.fromkeys(FIELDS[:5], 0.0)
        for usage in event.usage.model_usage[:16]:
            # Never serialize provider/model labels or the SDK object itself.
            if type(usage) is LLMModelUsage:
                totals["llm_input_tokens"] += finite(usage.input_tokens)
                totals["llm_output_tokens"] += finite(usage.output_tokens)
            elif type(usage) is STTModelUsage:
                totals["stt_audio_seconds"] += finite(usage.audio_duration)
            elif type(usage) is TTSModelUsage:
                totals["tts_audio_seconds"] += finite(usage.audio_duration)
                totals["tts_characters"] += finite(usage.characters_count)
        self.values.update({key: finite(value) for key, value in totals.items()})

    def _finish(self) -> None:
        self._span.end()
        flushed = self.tracing.provider.force_flush(timeout_millis=300)
        closed = self.tracing.close()
        processor = self.tracing.processor
        if processor is not None:
            for name in ("exported", "dropped", "failed"):
                self.values["trace_" + name] = finite(getattr(processor, name))
        if not flushed or not closed:
            emit("cleanup_failed", "shutdown_incomplete")
        DIRECTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
        # This directory is dedicated to generated numeric observations. No
        # names from metadata, room IDs, request bodies or tokens are accepted.
        if DIRECTORY.is_symlink() or DIRECTORY.stat().st_uid != os.getuid():
            raise ValueError("Observation directory is not privately owned")
        os.chmod(DIRECTORY, 0o700)
        prior = sorted(
            (
                p
                for p in DIRECTORY.iterdir()
                if re.fullmatch(r"[0-9a-f-]{36}\.json", p.name)
                and p.is_file()
                and not p.is_symlink()
            ),
            key=lambda p: p.stat().st_mtime,
        )
        for path in prior[:-31]:
            path.unlink()
        payload = {
            "schema_version": 1,
            "mode": self.mode,
            "sdk_report_observed": self._report_observed,
            "values": self.values,
        }
        data = json.dumps(payload, allow_nan=False, separators=(",", ":")).encode()
        if len(data) > 4096:
            raise ValueError("Numeric observation exceeds its byte budget")
        path = DIRECTORY / (str(uuid4()) + ".json")
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)

    async def aclose(self, session: AgentSession[None], ctx: JobContext) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            report = ctx.make_session_report(session)
            self._report_observed = True
            self.values["report_events"] = min(len(report.events), 10000)
            self.values["report_duration_seconds"] = finite(report.duration)
            self._usage(SessionUsageUpdatedEvent(usage=session.usage))
        finally:
            session.off("session_usage_updated", self._usage)
            await asyncio.to_thread(self._finish)
