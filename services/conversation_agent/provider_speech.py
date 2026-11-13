"""Real provider speech behind the existing explicit manual-turn interfaces.

ASR uses the official bounded batch recognize API on commit. TTS forwards actual
chunked v4 dialogue PCM; this HTTP path does not claim vendor word alignment.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from typing import Any, Never, TypeVar
from uuid import uuid4

import aiohttp
from livekit import rtc
from livekit.agents import stt, tts
from livekit.agents.language import LanguageCode
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions

from .inference_settings import (
    MAX_TRANSCRIPT_BYTES,
    MAX_TTS_SECONDS,
    MAX_TTS_TEXT_BYTES,
    MAX_TURN_AUDIO_SECONDS,
    MAX_TURNS,
    SAMPLE_RATE,
    LocalInferenceError,
)
from .inference_speech import LocalSTT, _LocalRecognizeStream
from .provider_settings import (
    PROVIDER_SAMPLE_RATE,
    PROVIDER_STT_MODEL,
    PROVIDER_TTS_MODEL,
    ProviderInferenceError,
)

T = TypeVar("T")
OPTIONS = APIConnectOptions(max_retry=0, timeout=5)


async def close_owned(actions: list[Callable[[], Awaitable[Any]]]) -> None:
    cancelled: asyncio.CancelledError | None = None
    failed = False
    for action in actions:
        try:
            async with asyncio.timeout(0.1):
                await action()
        except asyncio.CancelledError as error:
            cancelled = cancelled or error
            failed = True
        except Exception:  # noqa: BLE001 - no exception content crosses this boundary
            failed = True
    if cancelled is not None:
        raise cancelled
    if failed:
        raise ProviderInferenceError("cleanup_incomplete")


class OperationPool:
    """One active/one waiting operation; the whole deadline includes admission."""

    def __init__(self) -> None:
        self.pending = 0
        self.closed = False
        self.slot = asyncio.Semaphore(1)
        self.tasks: set[asyncio.Task[Any]] = set()

    async def run(self, action: Callable[[], Awaitable[T]]) -> T:
        if self.closed:
            raise ProviderInferenceError("closed")
        if self.pending >= 2:
            raise ProviderInferenceError("busy")
        self.pending += 1
        task = asyncio.current_task()
        if task is not None:
            self.tasks.add(task)
        try:
            async with asyncio.timeout(10):
                async with self.slot:
                    if self.closed:
                        raise ProviderInferenceError("closed")
                    return await action()
        except TimeoutError:
            raise ProviderInferenceError("deadline_exceeded") from None
        except LocalInferenceError:
            raise
        except Exception:  # noqa: BLE001 - provider failures can embed credentials/content
            raise ProviderInferenceError("dependency_unavailable") from None
        finally:
            self.pending -= 1
            if task is not None:
                self.tasks.discard(task)

    async def aclose(self) -> None:
        self.closed = True
        current = asyncio.current_task()
        tasks = [task for task in self.tasks if task is not current]
        for task in tasks:
            task.cancel()
        async with asyncio.timeout(0.05):
            await asyncio.gather(*tasks, return_exceptions=True)
        if any(not task.done() for task in tasks):
            raise ProviderInferenceError("cleanup_incomplete")


class ProviderSTT(LocalSTT):
    """The existing guarded PCM/manual-flush adapter, using real Nova-3 batch ASR."""

    def __init__(self, provider: stt.STT[Any], http_session: aiohttp.ClientSession) -> None:
        stt.STT.__init__(
            self,
            capabilities=stt.STTCapabilities(
                streaming=True, interim_results=False, manual_flush=True
            ),
        )
        self.upstream, self.http_session = provider, http_session
        self.pool = OperationPool()
        self.turns, self.audio_seconds = 0, 0.0
        self._closed = False
        self._cleanup_failed = False
        self.streams: set[_ProviderRecognizeStream] = set()

    @property
    def model(self) -> str:
        return PROVIDER_STT_MODEL

    @property
    def provider(self) -> str:
        return "deepgram"

    async def _transcribe(self, pcm: bytes) -> stt.SpeechEvent:
        seconds = len(pcm) / (SAMPLE_RATE * 2)
        if (
            self._closed
            or self.turns >= MAX_TURNS
            or len(pcm) % 2
            or not 0 <= seconds <= MAX_TURN_AUDIO_SECONDS
        ):
            raise ProviderInferenceError("input_limit")
        samples = memoryview(pcm).cast("h")
        rms = math.sqrt(sum(int(value) ** 2 for value in samples) / max(1, len(samples)))
        if not pcm or rms < 50:
            return stt.SpeechEvent(type=stt.SpeechEventType.FINAL_TRANSCRIPT)

        async def recognize() -> stt.SpeechEvent:
            frame = rtc.AudioFrame(pcm, SAMPLE_RATE, 1, len(pcm) // 2)
            return await self.upstream.recognize(
                frame, language=LanguageCode("en"), conn_options=OPTIONS
            )

        result = await self.pool.run(recognize)
        if (
            type(result) is not stt.SpeechEvent
            or result.type is not stt.SpeechEventType.FINAL_TRANSCRIPT
            or len(result.alternatives) > 3
        ):
            raise ProviderInferenceError("response_invalid")
        if not result.alternatives or not result.alternatives[0].text.strip():
            return stt.SpeechEvent(type=stt.SpeechEventType.FINAL_TRANSCRIPT)
        alternative = result.alternatives[0]
        if len(alternative.text.encode("utf-8")) > MAX_TRANSCRIPT_BYTES:
            raise ProviderInferenceError("response_limit")
        self.turns += 1
        return stt.SpeechEvent(
            type=stt.SpeechEventType.FINAL_TRANSCRIPT,
            request_id="provider-stt-" + uuid4().hex,
            alternatives=[
                stt.SpeechData(
                    language=LanguageCode("en"),
                    text=alternative.text,
                    start_time=0,
                    end_time=seconds,
                )
            ],
        )

    def stream(
        self, *, language: Any = None, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> stt.RecognizeStream:
        if self._closed:
            raise ProviderInferenceError("closed")
        # SDK clear_user_turn starts a replacement before asynchronously closing
        # its old stream. Bound those owned handles independently of the shared
        # one-active/one-waiting pool that admits actual ASR operations.
        if len(self.streams) >= 2:
            raise ProviderInferenceError("busy")
        stream = _ProviderRecognizeStream(self, conn_options=conn_options)
        self.streams.add(stream)
        return stream

    async def aclose(self) -> None:
        if self._closed:
            if self._cleanup_failed:
                raise ProviderInferenceError("cleanup_incomplete")
            return
        self._closed = True
        try:
            await close_owned(
                [
                    *(stream.aclose for stream in tuple(self.streams)),
                    self.pool.aclose,
                    self.upstream.aclose,
                    self.http_session.close,
                ]
            )
        except BaseException:
            self._cleanup_failed = True
            raise


class _ProviderRecognizeStream(_LocalRecognizeStream):
    def __init__(self, provider: ProviderSTT, *, conn_options: APIConnectOptions) -> None:
        self.owner = provider
        super().__init__(provider, conn_options=conn_options)

    async def aclose(self) -> None:
        # _run ending does not join the SDK metrics/tee resources. Keep ownership
        # through successful SDK close, including cancellation or failed close.
        await super().aclose()
        self.owner.streams.discard(self)


class ProviderTTS(tts.TTS[Never]):
    def __init__(self, provider: tts.TTS[Any], http_session: aiohttp.ClientSession) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False, aligned_transcript=False),
            sample_rate=PROVIDER_SAMPLE_RATE,
            num_channels=1,
        )
        self.upstream, self.http_session = provider, http_session
        self.pool = OperationPool()
        self._closed = False
        self._cleanup_failed = False
        self.streams: set[_ProviderTTSStream] = set()

    @property
    def model(self) -> str:
        return PROVIDER_TTS_MODEL

    @property
    def provider(self) -> str:
        return "elevenlabs"

    def synthesize(
        self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> tts.ChunkedStream:
        if self._closed:
            raise ProviderInferenceError("closed")
        if (
            type(text) is not str
            or not text.strip()
            or len(text.encode("utf-8")) > MAX_TTS_TEXT_BYTES
        ):
            raise ProviderInferenceError("input_limit")
        if len(self.streams) >= 2:
            raise ProviderInferenceError("busy")
        stream = _ProviderTTSStream(self, text=text, conn_options=conn_options)
        self.streams.add(stream)
        return stream

    async def aclose(self) -> None:
        if self._closed:
            if self._cleanup_failed:
                raise ProviderInferenceError("cleanup_incomplete")
            return
        self._closed = True
        try:
            await close_owned(
                [
                    *(stream.aclose for stream in tuple(self.streams)),
                    self.pool.aclose,
                    self.upstream.aclose,
                    self.http_session.close,
                ]
            )
        except BaseException:
            self._cleanup_failed = True
            raise


class _ProviderTTSStream(tts.ChunkedStream):
    def __init__(
        self, provider: ProviderTTS, *, text: str, conn_options: APIConnectOptions
    ) -> None:
        self.owner, self.text = provider, text
        super().__init__(tts=provider, input_text=text, conn_options=conn_options)

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        source: tts.ChunkedStream | None = None

        async def generate() -> None:
            nonlocal source
            source = self.owner.upstream.synthesize(self.text, conn_options=OPTIONS)
            output_emitter.initialize(
                request_id="provider-tts-" + uuid4().hex,
                sample_rate=PROVIDER_SAMPLE_RATE,
                num_channels=1,
                mime_type="audio/pcm",
                frame_size_ms=20,
            )
            samples = 0
            async for event in source:
                frame = event.frame
                if (
                    frame.sample_rate != PROVIDER_SAMPLE_RATE
                    or frame.num_channels != 1
                    or not 0 < frame.samples_per_channel <= PROVIDER_SAMPLE_RATE
                ):
                    raise ProviderInferenceError("response_invalid")
                samples += frame.samples_per_channel
                if samples > PROVIDER_SAMPLE_RATE * MAX_TTS_SECONDS:
                    raise ProviderInferenceError("response_limit")
                output_emitter.push(frame.data.tobytes())
            if samples == 0:
                raise ProviderInferenceError("response_invalid")
            output_emitter.flush()

        try:
            await self.owner.pool.run(generate)
        finally:
            try:
                if source is not None:
                    await close_owned([source.aclose])
            finally:
                self.owner.streams.discard(self)

    async def aclose(self) -> None:
        try:
            await super().aclose()
        finally:
            self.owner.streams.discard(self)
