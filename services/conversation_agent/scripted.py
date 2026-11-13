"""Bounded local SDK providers for explicitly labelled scripted-media tests.

The recognizer maps an observed, non-silent manual audio turn to a fixed fixture
script. It is not general speech recognition. The model uses a tiny exact command
allowlist; it cannot manufacture quote confirmation or business scope. Speech is
pre-generated local PCM, played through the normal SDK TTS pipeline.
"""

from __future__ import annotations

import asyncio
import json
import math
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Never
from uuid import uuid4

from livekit import rtc
from livekit.agents import llm, stt, tts
from livekit.agents.language import LanguageCode
from livekit.agents.types import (
    DEFAULT_API_CONNECT_OPTIONS,
    NOT_GIVEN,
    APIConnectOptions,
    NotGivenOr,
)
from livekit.agents.utils import AudioBuffer

SAMPLE_RATE = 16000
FRAME_SAMPLES = 320
MAX_TEXT_BYTES = 4096
MAX_AUDIO_SECONDS = 12
MAX_SESSION_AUDIO_SECONDS = 190
MAX_TURNS = 32

DEMO = "This is a scripted local voice demonstration."
ACCEPTED = "Your investigation was accepted and continues independently."
STATUS = "The workflow panel shows the latest durable state."
CANCELLED = "Your cancellation request was recorded for the current investigation."
GUARD = "Confirm the exact quote only in the workflow panel."
UNAVAILABLE = "The operation could not be completed; please inspect the workflow panel."
NO_CASE = "No investigation has been accepted for this conversation yet."
SPEECH_FILES = {
    DEMO: "demo.wav",
    ACCEPTED: "accepted.wav",
    STATUS: "status.wav",
    CANCELLED: "cancelled.wav",
    GUARD: "guard.wav",
    UNAVAILABLE: "unavailable.wav",
    NO_CASE: "no-case.wav",
}
COMMAND_TO_TOOL = {
    "investigate": "submit_investigation",
    "status": "get_case",
    "cancel this investigation": "cancel_case",
}
TOOL_TO_REPLY = {
    "submit_investigation": ACCEPTED,
    "get_case": STATUS,
    "cancel_case": CANCELLED,
}


@dataclass(frozen=True, slots=True)
class SpeechBank:
    """Validated small PCM assets loaded once at explicit process setup."""

    clips: tuple[tuple[str, bytes], ...]

    def __post_init__(self) -> None:
        if type(self.clips) is not tuple or not 1 <= len(self.clips) <= 16:
            raise ValueError("A finite speech fixture bank is required")
        names: set[str] = set()
        for text, pcm in self.clips:
            if text not in SPEECH_FILES or text in names:
                raise ValueError("Speech fixture text must be supported and unique")
            if (
                type(pcm) is not bytes
                or not 0 < len(pcm) <= SAMPLE_RATE * 2 * MAX_AUDIO_SECONDS
                or len(pcm) % 2
            ):
                raise ValueError("Speech PCM must be bounded mono PCM16")
            names.add(text)

    @classmethod
    def load(cls, directory: Path) -> SpeechBank:
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("A real speech fixture directory is required")
        clips = []
        for text, name in SPEECH_FILES.items():
            path = directory / name
            if (
                path.is_symlink()
                or not path.is_file()
                or path.stat().st_size > SAMPLE_RATE * 2 * MAX_AUDIO_SECONDS + 4096
            ):
                raise ValueError("A bounded speech fixture file is required")
            try:
                with wave.open(str(path), "rb") as source:
                    if (
                        source.getnchannels(),
                        source.getsampwidth(),
                        source.getframerate(),
                        source.getcomptype(),
                    ) != (1, 2, SAMPLE_RATE, "NONE"):
                        raise ValueError("Speech fixtures must use uncompressed 16 kHz mono PCM16")
                    frames = source.getnframes()
                    if not 0 < frames <= SAMPLE_RATE * MAX_AUDIO_SECONDS:
                        raise ValueError("Speech fixture duration exceeds its bound")
                    pcm = source.readframes(frames + 1)
                    if len(pcm) != frames * 2:
                        raise ValueError("Speech fixture is truncated")
            except (wave.Error, EOFError):
                raise ValueError("Speech fixture has an invalid WAV encoding") from None
            clips.append((text, pcm))
        return cls(tuple(clips))

    def pcm(self, text: str) -> bytes:
        for phrase, pcm in self.clips:
            if text.strip() == phrase:
                return pcm
        raise ValueError("The scripted speaker only supports declared fixture phrases")


class ScriptedLLM(llm.LLM[Never]):
    """Exercise native SDK tool execution without a network model/provider."""

    @property
    def model(self) -> str:
        return "scripted-business-v1"

    @property
    def provider(self) -> str:
        return "local-fixture"

    def chat(
        self,
        *,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool] | None = None,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
        parallel_tool_calls: NotGivenOr[bool] = NOT_GIVEN,
        tool_choice: NotGivenOr[llm.ToolChoice] = NOT_GIVEN,
        extra_kwargs: NotGivenOr[dict[str, Any]] = NOT_GIVEN,
    ) -> llm.LLMStream:
        # Any is the selected SDK's provider-extension argument; it grants no
        # application authority and is intentionally ignored by this fixture.
        return _ScriptedLLMStream(
            self,
            chat_ctx=chat_ctx,
            tools=tools or [],
            conn_options=conn_options,
            tool_choice=tool_choice,
        )


class _ScriptedLLMStream(llm.LLMStream):
    def __init__(
        self,
        provider: ScriptedLLM,
        *,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool],
        conn_options: APIConnectOptions,
        tool_choice: NotGivenOr[llm.ToolChoice],
    ) -> None:
        self.choice = tool_choice
        super().__init__(provider, chat_ctx=chat_ctx, tools=tools, conn_options=conn_options)

    async def _run(self) -> None:
        await asyncio.sleep(0)
        # SDK deferred replies append a system instruction after the verified
        # tool result. Ignore only trailing instruction messages; an assistant
        # message remains a boundary and cannot reissue an earlier user command.
        item = next(
            (
                entry
                for entry in reversed(self.chat_ctx.items)
                if not (
                    isinstance(entry, llm.ChatMessage) and entry.role in {"system", "developer"}
                )
            ),
            None,
        )
        if item is None:
            reply, tool = DEMO, None
        else:
            if isinstance(item, llm.FunctionCallOutput):
                reply = UNAVAILABLE if item.is_error else TOOL_TO_REPLY.get(item.name, GUARD)
                # A domain rejection returned as a safe receipt must not be
                # narrated as acceptance. No receipt text is treated as a tool.
                try:
                    value = json.loads(item.output)
                    if type(value) is dict and value.get("status") == "pending":
                        reply = DEMO  # A progress update never narrates business acceptance.
                    elif type(value) is dict and value.get("status") in {
                        "failed",
                        "rejected",
                        "not_accepted",
                    }:
                        reply = NO_CASE if value.get("status") == "not_accepted" else UNAVAILABLE
                except (ValueError, TypeError):
                    pass
                tool = None
            elif isinstance(item, llm.ChatMessage) and item.role == "user":
                text = item.text_content or ""
                if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
                    raise ValueError("Scripted model input exceeds its bound")
                tool = COMMAND_TO_TOOL.get(text.strip().lower()) if self.choice != "none" else None
                reply = GUARD
            else:
                reply, tool = GUARD, None
        available = {
            item.info.name
            for item in self.tools
            if isinstance(item, (llm.FunctionTool, llm.RawFunctionTool))
        }
        if tool not in available:
            tool = None
        request_id = "fixture-" + uuid4().hex
        if tool is not None:
            self._event_ch.send_nowait(
                llm.ChatChunk(
                    id=request_id,
                    delta=llm.ChoiceDelta(
                        role="assistant",
                        tool_calls=[
                            llm.FunctionToolCall(
                                name=tool, arguments="{}", call_id="fixture-call-" + uuid4().hex
                            )
                        ],
                    ),
                )
            )
        else:
            self._event_ch.send_nowait(
                llm.ChatChunk(id=request_id, delta=llm.ChoiceDelta(role="assistant", content=reply))
            )
        self._event_ch.send_nowait(
            llm.ChatChunk(
                id=request_id,
                usage=llm.CompletionUsage(completion_tokens=1, prompt_tokens=1, total_tokens=2),
            )
        )


class ScriptedSTT(stt.STT[Never]):
    """Manual, audio-qualified fixture transcript; never a human STT claim."""

    def __init__(self) -> None:
        super().__init__(
            capabilities=stt.STTCapabilities(
                streaming=True, interim_results=False, manual_flush=True
            )
        )
        self.audio_seconds = 0.0
        self.non_silent_seconds = 0.0
        self.turns = 0

    @property
    def model(self) -> str:
        return "scripted-audio-turn-v1"

    @property
    def provider(self) -> str:
        return "local-fixture"

    def _transcript(self, seconds: float, non_silent: float) -> stt.SpeechEvent:
        if non_silent < 0.1:
            return stt.SpeechEvent(type=stt.SpeechEventType.FINAL_TRANSCRIPT, alternatives=[])
        if self.turns >= MAX_TURNS:
            raise ValueError("Scripted transcript turn bound reached")
        text = "investigate" if self.turns == 0 else "status"
        self.turns += 1
        return stt.SpeechEvent(
            type=stt.SpeechEventType.FINAL_TRANSCRIPT,
            request_id="fixture-stt-" + uuid4().hex,
            alternatives=[
                stt.SpeechData(
                    language=LanguageCode("en"), text=text, start_time=0, end_time=seconds
                )
            ],
        )

    def _audio(self, frame: rtc.AudioFrame) -> tuple[float, float]:
        if (
            frame.num_channels != 1
            or frame.sample_rate != SAMPLE_RATE
            or frame.samples_per_channel > SAMPLE_RATE
        ):
            raise ValueError("Scripted audio frame format exceeds its bound")
        seconds = frame.samples_per_channel / SAMPLE_RATE
        self.audio_seconds += seconds
        if self.audio_seconds > MAX_SESSION_AUDIO_SECONDS:
            raise ValueError("Scripted session audio bound reached")
        samples = frame.data.cast("h") if frame.data.format != "h" else frame.data
        rms = math.sqrt(sum(int(sample) ** 2 for sample in samples) / max(1, len(samples)))
        non_silent = seconds if rms >= 50 else 0.0
        self.non_silent_seconds += non_silent
        return seconds, non_silent

    async def _recognize_impl(
        self,
        buffer: AudioBuffer,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions,
    ) -> stt.SpeechEvent:
        frames = [buffer] if isinstance(buffer, rtc.AudioFrame) else buffer
        seconds, non_silent = 0.0, 0.0
        for frame in frames:
            duration, speech = self._audio(frame)
            seconds += duration
            non_silent += speech
            if seconds > MAX_AUDIO_SECONDS:
                raise ValueError("Scripted turn audio bound reached")
        return self._transcript(seconds, non_silent)

    def stream(
        self,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> stt.RecognizeStream:
        return _ScriptedRecognizeStream(self, conn_options=conn_options)


class _ScriptedRecognizeStream(stt.RecognizeStream):
    def __init__(self, provider: ScriptedSTT, *, conn_options: APIConnectOptions) -> None:
        self.provider = provider
        super().__init__(stt=provider, conn_options=conn_options, sample_rate=SAMPLE_RATE)

    async def _run(self) -> None:
        seconds, non_silent = 0.0, 0.0
        async for item in self._input_ch:
            if isinstance(item, rtc.AudioFrame):
                duration, speech = self.provider._audio(item)
                seconds += duration
                non_silent += speech
                if seconds > MAX_AUDIO_SECONDS:
                    raise ValueError("Scripted turn audio bound reached")
            else:
                result = self.provider._transcript(seconds, non_silent)
                if result.alternatives:
                    self._event_ch.send_nowait(
                        stt.SpeechEvent(type=stt.SpeechEventType.START_OF_SPEECH)
                    )
                    self._event_ch.send_nowait(result)
                    self._event_ch.send_nowait(
                        stt.SpeechEvent(
                            type=stt.SpeechEventType.RECOGNITION_USAGE,
                            recognition_usage=stt.RecognitionUsage(audio_duration=seconds),
                        )
                    )
                    self._event_ch.send_nowait(
                        stt.SpeechEvent(type=stt.SpeechEventType.END_OF_SPEECH)
                    )
                seconds, non_silent = 0.0, 0.0


class ScriptedTTS(tts.TTS[Never]):
    def __init__(self, bank: SpeechBank, *, pace: bool = True) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=SAMPLE_RATE,
            num_channels=1,
        )
        self.bank, self.pace = bank, pace
        self.frames_emitted = 0

    @property
    def model(self) -> str:
        return "scripted-pcm-speech-v1"

    @property
    def provider(self) -> str:
        return "local-fixture"

    def synthesize(
        self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> tts.ChunkedStream:
        if type(text) is not str or len(text.encode("utf-8")) > MAX_TEXT_BYTES:
            raise ValueError("Scripted speech text exceeds its bound")
        pcm = self.bank.pcm(text)
        return _SpeechStream(self, text, pcm, conn_options=conn_options)


class _SpeechStream(tts.ChunkedStream):
    def __init__(
        self, provider: ScriptedTTS, text: str, pcm: bytes, *, conn_options: APIConnectOptions
    ) -> None:
        self.provider, self.pcm = provider, pcm
        super().__init__(tts=provider, input_text=text, conn_options=conn_options)

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        output_emitter.initialize(
            request_id="fixture-tts-" + uuid4().hex,
            sample_rate=SAMPLE_RATE,
            num_channels=1,
            mime_type="audio/pcm",
            frame_size_ms=20,
        )
        for offset in range(0, len(self.pcm), FRAME_SAMPLES * 2):
            output_emitter.push(self.pcm[offset : offset + FRAME_SAMPLES * 2])
            self.provider.frames_emitted += 1
            if self.provider.pace:
                await asyncio.sleep(FRAME_SAMPLES / SAMPLE_RATE)
            else:
                await asyncio.sleep(0)
        output_emitter.flush()
