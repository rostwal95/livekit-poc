"""Genuine SDK extensions, imported only by the explicit scripted loader.

This module constructs no room or AgentSession. SDK streams remain registered
until their actual SDK close settles, including abandoned/cancelled observers.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from typing import Any, Never, Protocol
from uuid import UUID, uuid4

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

from channel_continuity.native_models import CommittedTranscript

from .native_models import (
    MAX_SESSION_SAMPLES,
    MAX_TURN_SAMPLES,
    SAMPLE_RATE,
    NativeModelError,
    ScriptedAudio,
    ScriptedModelBundle,
    ScriptedModelProfile,
    _asset,
    _task,
)


class _Stream(Protocol):
    async def _finish_close(self) -> None: ...


class _Streams:
    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self.stopped = False
        self.handles: dict[_Stream, asyncio.Task[None] | None] = {}

    def add(self, stream: _Stream) -> None:
        if self.stopped:
            raise NativeModelError("closed")
        if len(self.handles) >= self.capacity:
            raise NativeModelError("capacity_exhausted")
        self.handles[stream] = None  # reserve before eager SDK task construction

    async def close_stream(self, stream: _Stream) -> None:
        if stream not in self.handles:
            return
        task = self.handles[stream]
        if task is None or (task.done() and (task.cancelled() or task.exception() is not None)):
            task = _task(self._close_one(stream), cleanup=True)
            self.handles[stream] = task
        await asyncio.shield(task)

    async def _close_one(self, stream: _Stream) -> None:
        try:
            await stream._finish_close()
        except Exception:  # noqa: BLE001 - finite SDK close boundary
            raise NativeModelError("cleanup_incomplete") from None
        self.handles.pop(stream, None)

    async def close(self) -> None:
        self.stopped = True
        results = await asyncio.gather(
            *(self.close_stream(item) for item in tuple(self.handles)), return_exceptions=True
        )
        if any(isinstance(item, BaseException) for item in results) or self.handles:
            raise NativeModelError("cleanup_incomplete")


async def _partial_tasks(stream: object) -> None:
    # SDK constructors allocate their own tasks. Retain even a partially
    # constructed stream in its registry if a constructor raises.
    values = vars(stream)
    tasks = [
        value
        for key in ("_task", "_synthesize_task", "_metrics_task")
        if isinstance((value := values.get(key)), asyncio.Task)
    ]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    for key in ("_input_ch", "_event_ch"):
        channel = values.get(key)
        if channel is not None:
            channel.close()
    for key in ("_tee", "_tee_aiter"):
        tee = values.get(key)
        if tee is not None:
            await tee.aclose()


def _uuid(value: str) -> None:
    try:
        if type(value) is not str or str(parsed := UUID(value)) != value or parsed.version != 4:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise NativeModelError("invalid_input") from None


class _Recognizer(stt.STT[Never]):
    def __init__(self, profile: ScriptedModelProfile) -> None:
        super().__init__(
            capabilities=stt.STTCapabilities(
                streaming=True, interim_results=False, offline_recognize=False, manual_flush=True
            )
        )
        self.profile = profile
        self.streams = _Streams(1)
        self.current: str | None = None
        self.seen: set[str] = set()
        self.open: set[str] = set()
        self.pending: set[str] = set()
        self.finals: dict[str, CommittedTranscript] = {}
        self.turn_text: dict[str, str] = {}
        self.samples = 0
        self.frames = 0
        self.final_count = 0

    @property
    def model(self) -> str:
        return "channel-scripted-declared-pcm-v1"

    @property
    def provider(self) -> str:
        return "local-scripted"

    def pending_work(self) -> int:
        return len(self.pending)

    def begin_turn(self, input_id: str) -> None:
        _uuid(input_id)
        if self.streams.stopped:
            raise NativeModelError("closed")
        if (
            self.current is not None
            or self.pending
            or input_id in self.seen
            or len(self.seen) >= len(self.profile.input_fixtures)
        ):
            raise NativeModelError("capacity_exhausted")
        fixture = self.profile.input_fixtures[len(self.seen)]
        self.seen.add(input_id)
        self.open.add(input_id)
        self.turn_text[input_id] = _asset(fixture).text
        self.current = input_id

    def final_snapshot(self, input_id: str) -> CommittedTranscript | None:
        _uuid(input_id)
        return self.finals.get(input_id)

    def end_turn(self, input_id: str) -> None:
        _uuid(input_id)
        self.open.discard(input_id)
        if self.current == input_id:
            self.current = None

    async def _recognize_impl(
        self,
        buffer: AudioBuffer,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions,
    ) -> stt.SpeechEvent:
        raise NativeModelError("invalid_input")

    def stream(
        self,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> stt.RecognizeStream:
        if language not in (NOT_GIVEN, "en"):
            raise NativeModelError("invalid_input")
        try:
            return _Recognition(self, conn_options)
        except NativeModelError:
            raise
        except Exception:  # noqa: BLE001 - retain partial SDK constructor in registry
            raise NativeModelError("unavailable") from None

    async def aclose(self) -> None:
        self.current = None
        self.open.clear()
        await self.streams.close()


class _Recognition(stt.RecognizeStream):
    def __init__(self, owner: _Recognizer, options: APIConnectOptions) -> None:
        self.owner = owner
        self.captured: str | None = None
        self.turn_samples = 0
        self.turn_frames = 0
        self.non_silent_samples = 0
        self.flushed = False
        self.closing = False
        self.ready = False
        owner.streams.add(self)
        # Do not ask the SDK to resample unsupported formats into valid fixtures.
        super().__init__(stt=owner, conn_options=options)
        self.ready = True

    def push_frame(self, frame: rtc.AudioFrame) -> None:
        if (
            self.closing
            or self.owner.streams.stopped
            or self._input_ch.closed
            or self._event_ch.closed
        ):
            raise NativeModelError("closed")
        if (
            type(frame) is not rtc.AudioFrame
            or frame.sample_rate != SAMPLE_RATE
            or frame.num_channels != 1
            or not 0 < frame.samples_per_channel <= SAMPLE_RATE
            or len(frame.data) != frame.samples_per_channel
        ):
            raise NativeModelError("invalid_audio")
        if self.flushed:
            raise NativeModelError("capacity_exhausted")
        original = self.captured if self.captured is not None else self.owner.current
        if original is None or original not in self.owner.open:
            raise NativeModelError("invalid_input")
        if (
            self.turn_samples + frame.samples_per_channel > MAX_TURN_SAMPLES
            or self.owner.samples + frame.samples_per_channel > MAX_SESSION_SAMPLES
            or self.turn_frames >= 1024
        ):
            raise NativeModelError("capacity_exhausted")
        # Snapshot caller-owned PCM and original turn synchronously, before the
        # SDK queue/recognizer coroutine can await or a different turn can start.
        copied = rtc.AudioFrame(bytes(frame.data), SAMPLE_RATE, 1, frame.samples_per_channel)
        super().push_frame(copied)
        self.captured = original
        self.owner.pending.add(original)
        self.turn_samples += frame.samples_per_channel
        self.turn_frames += 1
        self.owner.samples += frame.samples_per_channel
        self.owner.frames += 1

    def flush(self) -> None:
        if (
            self.closing
            or self.owner.streams.stopped
            or self._input_ch.closed
            or self._event_ch.closed
        ):
            raise NativeModelError("closed")
        if self.flushed:
            return  # SDK may flush then end_input; keep at most one queued marker.
        self.flushed = True
        super().flush()

    async def _run(self) -> None:
        try:
            async for item in self._input_ch:
                if isinstance(item, rtc.AudioFrame):
                    samples = item.data.cast("h") if item.data.format != "h" else item.data
                    if math.sqrt(sum(int(value) ** 2 for value in samples) / len(samples)) >= 50:
                        self.non_silent_samples += item.samples_per_channel
                    continue
                original = self.captured
                duration = self.turn_samples / SAMPLE_RATE
                request_id = "scripted-stt-" + uuid4().hex
                text = ""
                if (
                    original is not None
                    and original in self.owner.open
                    and self.non_silent_samples >= SAMPLE_RATE // 10
                ):
                    text = self.owner.turn_text[original]
                    final = CommittedTranscript(original, text, request_id)
                    if original in self.owner.finals:
                        raise NativeModelError("invalid_input")
                    self.owner.finals[original] = final
                    self.owner.final_count += 1
                    self._event_ch.send_nowait(
                        stt.SpeechEvent(type=stt.SpeechEventType.START_OF_SPEECH)
                    )
                self._event_ch.send_nowait(
                    stt.SpeechEvent(
                        type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                        request_id=request_id,
                        alternatives=[
                            stt.SpeechData(
                                language=LanguageCode("en"),
                                text=text,
                                start_time=0,
                                end_time=duration,
                            )
                        ],
                    )
                )
                self._event_ch.send_nowait(
                    stt.SpeechEvent(
                        type=stt.SpeechEventType.RECOGNITION_USAGE,
                        request_id=request_id,
                        recognition_usage=stt.RecognitionUsage(audio_duration=duration),
                    )
                )
                self._event_ch.send_nowait(stt.SpeechEvent(type=stt.SpeechEventType.END_OF_SPEECH))
                self._reset()
        finally:
            self._reset()

    def _reset(self) -> None:
        if self.captured is not None:
            self.owner.pending.discard(self.captured)
        self.captured = None
        self.turn_samples = self.turn_frames = self.non_silent_samples = 0
        self.flushed = False

    async def aclose(self) -> None:
        self.closing = True
        await self.owner.streams.close_stream(self)

    async def _finish_close(self) -> None:
        self.closing = True
        if self.ready:
            await super().aclose()
        else:
            await _partial_tasks(self)
        self._reset()


class _LanguageModel(llm.LLM[Never]):
    def __init__(self, reply: str) -> None:
        super().__init__()
        self.reply = reply
        self.streams = _Streams(2)
        self.calls = 0

    @property
    def model(self) -> str:
        return "channel-scripted-declared-response-v1"

    @property
    def provider(self) -> str:
        return "local-scripted"

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
        if tools or self.calls >= 64:
            raise NativeModelError("invalid_input" if tools else "capacity_exhausted")
        # A declared reply contains no model-selected authority or tool call.
        try:
            stream = _Reply(self, chat_ctx, conn_options)
        except NativeModelError:
            raise
        except Exception:  # noqa: BLE001 - retain partial SDK constructor in registry
            raise NativeModelError("unavailable") from None
        self.calls += 1
        return stream

    async def aclose(self) -> None:
        await self.streams.close()


class _Reply(llm.LLMStream):
    def __init__(
        self, owner: _LanguageModel, context: llm.ChatContext, options: APIConnectOptions
    ) -> None:
        self.owner, self.ready = owner, False
        owner.streams.add(self)
        super().__init__(owner, chat_ctx=context.copy(), tools=[], conn_options=options)
        self.ready = True

    async def _run(self) -> None:
        self._event_ch.send_nowait(
            llm.ChatChunk(
                id="scripted-llm-" + uuid4().hex,
                delta=llm.ChoiceDelta(role="assistant", content=self.owner.reply),
            )
        )
        # Synthetic response is not provider token usage; do not fabricate tokens.

    async def aclose(self) -> None:
        await self.owner.streams.close_stream(self)

    async def _finish_close(self) -> None:
        if self.ready:
            await super().aclose()
        else:
            await _partial_tasks(self)


class _Voice(tts.TTS[Never]):
    def __init__(self, assets: tuple[ScriptedAudio, ...]) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=SAMPLE_RATE,
            num_channels=1,
        )
        self.assets = assets
        self.streams = _Streams(2)
        self.calls = 0
        self.frames = 0

    @property
    def model(self) -> str:
        return "channel-scripted-declared-pcm-voice-v1"

    @property
    def provider(self) -> str:
        return "local-scripted"

    def synthesize(
        self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> tts.ChunkedStream:
        if type(text) is not str:
            raise NativeModelError("invalid_input")
        try:
            if len(text.encode("utf-8")) > 2048:
                raise NativeModelError("invalid_input")
        except UnicodeError:
            raise NativeModelError("invalid_input") from None
        pcm = next(
            (
                item.pcm
                for item in self.assets
                if not item.fixture.startswith("input-")
                and _asset(item.fixture).text == text.strip()
            ),
            None,
        )
        if pcm is None:
            raise NativeModelError("invalid_input")
        if self.calls >= 64:
            raise NativeModelError("capacity_exhausted")
        try:
            result = _Speech(self, text, pcm, conn_options)
        except NativeModelError:
            raise
        except Exception:  # noqa: BLE001 - retain partial SDK constructor in registry
            raise NativeModelError("unavailable") from None
        self.calls += 1
        return result

    async def aclose(self) -> None:
        await self.streams.close()


class _Speech(tts.ChunkedStream):
    def __init__(self, owner: _Voice, text: str, pcm: bytes, options: APIConnectOptions) -> None:
        self.owner, self.pcm, self.ready = owner, pcm, False
        owner.streams.add(self)
        super().__init__(tts=owner, input_text=text, conn_options=options)
        self.ready = True

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        output_emitter.initialize(
            request_id="scripted-tts-" + uuid4().hex,
            sample_rate=SAMPLE_RATE,
            num_channels=1,
            mime_type="audio/pcm",
            frame_size_ms=20,
        )
        for offset in range(0, len(self.pcm), 640):
            output_emitter.push(self.pcm[offset : offset + 640])
            self.owner.frames += 1
            # Yield between bounded chunks; RTC output owns actual playout pace.
            await asyncio.sleep(0)
        # ChunkedStream ends input and joins the emitter after _run returns.
        # An extra flush here creates the SDK's synthetic final silence marker.

    async def aclose(self) -> None:
        await self.owner.streams.close_stream(self)

    async def _finish_close(self) -> None:
        if self.ready:
            await super().aclose()
        else:
            await _partial_tasks(self)


class _Bundle:
    def __init__(
        self, recognizer: _Recognizer, model: _LanguageModel, voice: _Voice, timeout: float
    ) -> None:
        self.recognizer, self.model, self.voice = recognizer, model, voice
        self.timeout = timeout
        self.task: asyncio.Task[None] | None = None
        self.closed = False

    @property
    def pending_count(self) -> int:
        return sum(
            len(item.handles)
            for item in (self.recognizer.streams, self.model.streams, self.voice.streams)
        )

    def metrics(self) -> dict[str, int]:
        return {
            "stt_streams": len(self.recognizer.streams.handles),
            "llm_streams": len(self.model.streams.handles),
            "tts_streams": len(self.voice.streams.handles),
            "pending_turns": self.recognizer.pending_work(),
            "audio_samples": self.recognizer.samples,
            "audio_frames": self.recognizer.frames,
            "transcripts": self.recognizer.final_count,
            "model_calls": self.model.calls,
            "speech_calls": self.voice.calls,
            "speech_frames": self.voice.frames,
            "closed": int(self.closed),
        }

    async def aclose(self) -> None:
        for item in (self.recognizer.streams, self.model.streams, self.voice.streams):
            item.stopped = True
        if self.closed:
            return
        if self.task is None or (
            self.task.done() and (self.task.cancelled() or self.task.exception() is not None)
        ):
            self.task = _task(self._close(), cleanup=True)
        try:
            async with asyncio.timeout(self.timeout):
                await asyncio.shield(self.task)
        except TimeoutError:
            raise NativeModelError("cleanup_incomplete") from None

    async def _close(self) -> None:
        closes: tuple[Callable[[], Awaitable[None]], ...] = (
            self.recognizer.aclose,
            self.model.aclose,
            self.voice.aclose,
        )
        results = await asyncio.gather(*(close() for close in closes), return_exceptions=True)
        if any(isinstance(result, BaseException) for result in results) or self.pending_count:
            raise NativeModelError("cleanup_incomplete")
        self.closed = True


def build_models(
    profile: ScriptedModelProfile, assets: tuple[ScriptedAudio, ...]
) -> ScriptedModelBundle:
    recognizer = _Recognizer(profile)
    model = _LanguageModel(_asset(profile.reply_fixture).text)
    voice = _Voice(assets)
    owner = _Bundle(recognizer, model, voice, profile.cleanup_timeout_s)
    return ScriptedModelBundle(
        stt=recognizer,
        llm=model,
        tts=voice,
        recognizer=recognizer,
        owner=owner,
        assets=assets,
        profile=profile,
    )
