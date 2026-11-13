"""Application-owned local fixtures. Fixed audio mapping is not general speech recognition."""

from __future__ import annotations

import asyncio
import math
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

from channel_continuity.native import CommittedTranscript, NativeError

REPLY = "The workflow panel shows the latest durable state."
RATE = 16000


class ScriptedModel(llm.LLM[Never]):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    @property
    def model(self) -> str:
        return "native-scripted-v1"

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
        return _ModelStream(self, chat_ctx, tools or [], conn_options)


class _ModelStream(llm.LLMStream):
    def __init__(
        self,
        owner: ScriptedModel,
        ctx: llm.ChatContext,
        tools: list[llm.Tool],
        options: APIConnectOptions,
    ) -> None:
        self.owner = owner
        super().__init__(owner, chat_ctx=ctx, tools=tools, conn_options=options)

    async def _run(self) -> None:
        self.owner.calls += 1
        self._event_ch.send_nowait(
            llm.ChatChunk(
                id="native-" + uuid4().hex,
                delta=llm.ChoiceDelta(role="assistant", content=REPLY),
                usage=llm.CompletionUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            )
        )


class ScriptedRecognizer(stt.STT[Never]):
    def __init__(
        self,
        *,
        final_delay: float = 0,
        interim_only: bool = False,
        final_gate: asyncio.Event | None = None,
    ) -> None:
        super().__init__(
            capabilities=stt.STTCapabilities(
                streaming=True, interim_results=True, manual_flush=True
            )
        )
        if (
            type(final_delay) not in (int, float)
            or not 0 <= final_delay <= 3
            or type(interim_only) is not bool
        ):
            raise NativeError()
        self.final_delay, self.interim_only, self.final_gate = final_delay, interim_only, final_gate
        self.current_turn: str | None = None
        self._open: set[str] = set()
        self._pending: set[str] = set()
        self._final: dict[str, CommittedTranscript] = {}
        self._seen: set[str] = set()
        self.audio_seconds = 0.0
        self.frames = 0

    @property
    def model(self) -> str:
        return "native-scripted-flush-v1"

    @property
    def provider(self) -> str:
        return "local-fixture"

    def begin_turn(self, input_id: str) -> None:
        if (
            self._pending
            or self.current_turn is not None
            or input_id in self._seen
            or len(self._seen) >= 32
        ):
            raise NativeError("capacity_exhausted")
        self._seen.add(input_id)
        self.current_turn = input_id
        self._open.add(input_id)

    def pending_work(self) -> int:
        return len(self._pending)

    def final_snapshot(self, input_id: str) -> CommittedTranscript | None:
        return self._final.get(input_id)

    def end_turn(self, input_id: str) -> None:
        self._open.discard(input_id)
        if self.current_turn == input_id:
            self.current_turn = None

    async def _recognize_impl(
        self,
        buffer: AudioBuffer,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions,
    ) -> stt.SpeechEvent:
        raise NativeError("invalid_input")

    def stream(
        self,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> stt.RecognizeStream:
        return _RecognizerStream(self, conn_options)


class _RecognizerStream(stt.RecognizeStream):
    def __init__(self, owner: ScriptedRecognizer, options: APIConnectOptions) -> None:
        self.owner = owner
        super().__init__(stt=owner, conn_options=options, sample_rate=RATE)

    async def _run(self) -> None:
        captured: str | None = None
        seconds = 0.0
        non_silent = 0.0
        try:
            async for item in self._input_ch:
                if isinstance(item, rtc.AudioFrame):
                    if (
                        item.sample_rate != RATE
                        or item.num_channels != 1
                        or item.samples_per_channel > RATE
                    ):
                        raise NativeError()
                    if captured is None:
                        captured = self.owner.current_turn
                        if captured is not None:
                            self.owner._pending.add(captured)
                    duration = item.samples_per_channel / RATE
                    seconds += duration
                    self.owner.audio_seconds += duration
                    self.owner.frames += 1
                    if seconds > 12 or self.owner.audio_seconds > 190:
                        raise NativeError("capacity_exhausted")
                    samples = item.data.cast("h") if item.data.format != "h" else item.data
                    if math.sqrt(sum(int(v) ** 2 for v in samples) / max(1, len(samples))) >= 50:
                        non_silent += duration
                else:
                    original = captured  # Captured before delay/await; never read a mutable current-turn ID later.
                    request_id = "native-stt-" + uuid4().hex
                    try:
                        if original is not None and non_silent >= 0.1:
                            data = stt.SpeechData(
                                language=LanguageCode("en"),
                                text="investigate",
                                start_time=0,
                                end_time=seconds,
                            )
                            self._event_ch.send_nowait(
                                stt.SpeechEvent(type=stt.SpeechEventType.START_OF_SPEECH)
                            )
                            self._event_ch.send_nowait(
                                stt.SpeechEvent(
                                    type=stt.SpeechEventType.INTERIM_TRANSCRIPT,
                                    request_id=request_id,
                                    alternatives=[data],
                                )
                            )
                            if self.owner.final_gate is not None:
                                await self.owner.final_gate.wait()
                            if self.owner.final_delay:
                                await asyncio.sleep(self.owner.final_delay)
                            if not self.owner.interim_only:
                                final = CommittedTranscript(original, "investigate", request_id)
                                previous = self.owner._final.get(original)
                                if previous is not None and previous != final:
                                    raise NativeError("idempotency_conflict")
                                if original in self.owner._open:
                                    self.owner._final[original] = final
                                self._event_ch.send_nowait(
                                    stt.SpeechEvent(
                                        type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                                        request_id=request_id,
                                        alternatives=[data],
                                    )
                                )
                            self._event_ch.send_nowait(
                                stt.SpeechEvent(type=stt.SpeechEventType.END_OF_SPEECH)
                            )
                        else:
                            self._event_ch.send_nowait(
                                stt.SpeechEvent(
                                    type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                                    request_id=request_id,
                                    alternatives=[
                                        stt.SpeechData(language=LanguageCode("en"), text="")
                                    ],
                                )
                            )
                    finally:
                        if original is not None:
                            self.owner._pending.discard(original)
                        captured = None
                        seconds = 0.0
                        non_silent = 0.0
        finally:
            if captured is not None:
                self.owner._pending.discard(captured)


class ScriptedVoice(tts.TTS[Never]):
    def __init__(self, pcm: bytes, *, pace: bool = True) -> None:
        if type(pcm) is not bytes or not pcm or len(pcm) > RATE * 2 * 4 or len(pcm) % 2:
            raise NativeError()
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False), sample_rate=RATE, num_channels=1
        )
        self.pcm, self.pace = pcm, pace
        self.frames_emitted = 0

    @property
    def model(self) -> str:
        return "native-prerecorded-speech-v1"

    @property
    def provider(self) -> str:
        return "local-fixture"

    def synthesize(
        self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> tts.ChunkedStream:
        if text != REPLY:
            raise NativeError()
        return _VoiceStream(self, text, conn_options)


class _VoiceStream(tts.ChunkedStream):
    def __init__(self, owner: ScriptedVoice, text: str, options: APIConnectOptions) -> None:
        self.owner = owner
        super().__init__(tts=owner, input_text=text, conn_options=options)

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        output_emitter.initialize(
            request_id="native-tts-" + uuid4().hex,
            sample_rate=RATE,
            num_channels=1,
            mime_type="audio/pcm",
            frame_size_ms=20,
        )
        for offset in range(0, len(self.owner.pcm), 640):
            output_emitter.push(self.owner.pcm[offset : offset + 640])
            self.owner.frames_emitted += 1
            await asyncio.sleep(0.02 if self.owner.pace else 0)
        output_emitter.flush()
