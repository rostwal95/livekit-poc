"""Real local STT and TTS public SDK extensions with manual, bounded audio turns."""

from __future__ import annotations

import asyncio
import io
import math
import wave
from typing import Never
from uuid import uuid4

import httpx
from livekit import rtc
from livekit.agents import stt, tts
from livekit.agents.language import LanguageCode
from livekit.agents.types import (
    DEFAULT_API_CONNECT_OPTIONS,
    NOT_GIVEN,
    APIConnectOptions,
    NotGivenOr,
)
from livekit.agents.utils.audio import AudioBuffer

from .inference_http import LocalModelHTTP, strict_transcript
from .inference_settings import (
    LOCAL_STT_MODEL,
    LOCAL_TTS_MODEL,
    MAX_SESSION_AUDIO_SECONDS,
    MAX_STT_RESPONSE_BYTES,
    MAX_TRANSCRIPT_BYTES,
    MAX_TTS_RESPONSE_BYTES,
    MAX_TTS_SECONDS,
    MAX_TTS_TEXT_BYTES,
    MAX_TURN_AUDIO_SECONDS,
    MAX_TURNS,
    SAMPLE_RATE,
    STT_TIMEOUT_SECONDS,
    TTS_SAMPLE_RATE,
    TTS_TIMEOUT_SECONDS,
    LocalInferenceError,
    LocalInferenceSettings,
)


def wav_bytes(pcm: bytes, sample_rate: int) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(sample_rate)
        stream.writeframes(pcm)
    return output.getvalue()


def decoded_speech(raw: bytes) -> bytes:
    try:
        with wave.open(io.BytesIO(raw), "rb") as stream:
            frames = stream.getnframes()
            if (
                stream.getnchannels() != 1
                or stream.getsampwidth() != 2
                or stream.getframerate() != TTS_SAMPLE_RATE
                or stream.getcomptype() != "NONE"
                or not 0 < frames <= TTS_SAMPLE_RATE * MAX_TTS_SECONDS
            ):
                raise LocalInferenceError("response_invalid")
            pcm = stream.readframes(frames)
            if len(pcm) != frames * 2 or not any(pcm):
                raise LocalInferenceError("response_invalid")
            return pcm
    except (wave.Error, EOFError, ValueError):
        raise LocalInferenceError("response_invalid") from None


class LocalSTT(stt.STT[Never]):
    """Whisper inference on real PCM; manual flush does not invent transcript text."""

    def __init__(
        self,
        settings: LocalInferenceSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            capabilities=stt.STTCapabilities(
                streaming=True, interim_results=False, manual_flush=True
            )
        )
        self.http = LocalModelHTTP(
            settings.stt_base_url,
            timeout_seconds=STT_TIMEOUT_SECONDS,
            maximum_response_bytes=MAX_STT_RESPONSE_BYTES,
            transport=transport,
        )
        self.turns = 0
        self.audio_seconds = 0.0
        self._closed = False

    @property
    def model(self) -> str:
        return LOCAL_STT_MODEL

    @property
    def provider(self) -> str:
        return "local-whisper"

    def _accept_frame(self, frame: rtc.AudioFrame) -> bytes:
        if (
            frame.sample_rate != SAMPLE_RATE
            or frame.num_channels != 1
            or not 0 < frame.samples_per_channel <= SAMPLE_RATE
            or self._closed
        ):
            raise LocalInferenceError("input_limit")
        self.audio_seconds += frame.samples_per_channel / SAMPLE_RATE
        if self.audio_seconds > MAX_SESSION_AUDIO_SECONDS:
            raise LocalInferenceError("input_limit")
        return frame.data.tobytes()

    async def _transcribe(self, pcm: bytes) -> stt.SpeechEvent:
        seconds = len(pcm) / (SAMPLE_RATE * 2)
        if not 0 <= seconds <= MAX_TURN_AUDIO_SECONDS or len(pcm) % 2:
            raise LocalInferenceError("input_limit")
        if self.turns >= MAX_TURNS or self._closed:
            raise LocalInferenceError("input_limit")
        samples = memoryview(pcm).cast("h")
        rms = math.sqrt(sum(int(x) ** 2 for x in samples) / max(1, len(samples)))
        if not pcm or rms < 50:
            return stt.SpeechEvent(type=stt.SpeechEventType.FINAL_TRANSCRIPT, alternatives=[])
        raw = await self.http.post(
            "/inference",
            files={"file": ("turn.wav", wav_bytes(pcm, SAMPLE_RATE), "audio/wav")},
            data={
                "temperature": "0.0",
                "temperature_inc": "0.0",
                "response_format": "json",
                "language": "en",
            },
        )
        text = strict_transcript(raw, MAX_TRANSCRIPT_BYTES)
        if not text:
            return stt.SpeechEvent(type=stt.SpeechEventType.FINAL_TRANSCRIPT, alternatives=[])
        self.turns += 1
        return stt.SpeechEvent(
            type=stt.SpeechEventType.FINAL_TRANSCRIPT,
            request_id="local-stt-" + uuid4().hex,
            alternatives=[
                stt.SpeechData(
                    language=LanguageCode("en"), text=text, start_time=0, end_time=seconds
                )
            ],
        )

    async def _recognize_impl(
        self,
        buffer: AudioBuffer,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions,
    ) -> stt.SpeechEvent:
        frames = [buffer] if isinstance(buffer, rtc.AudioFrame) else buffer
        pcm = bytearray()
        for frame in frames:
            part = self._accept_frame(frame)
            if len(pcm) + len(part) > SAMPLE_RATE * 2 * MAX_TURN_AUDIO_SECONDS:
                raise LocalInferenceError("input_limit")
            pcm.extend(part)
        return await self._transcribe(bytes(pcm))

    def stream(
        self,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> stt.RecognizeStream:
        if self._closed:
            raise LocalInferenceError("closed")
        return _LocalRecognizeStream(self, conn_options=conn_options)

    async def aclose(self) -> None:
        self._closed = True
        await self.http.aclose()


class _LocalRecognizeStream(stt.RecognizeStream):
    def __init__(self, provider: LocalSTT, *, conn_options: APIConnectOptions) -> None:
        self.provider = provider
        super().__init__(stt=provider, conn_options=conn_options, sample_rate=SAMPLE_RATE)

    async def _run(self) -> None:
        pcm = bytearray()
        async for item in self._input_ch:
            if isinstance(item, rtc.AudioFrame):
                part = self.provider._accept_frame(item)
                if len(pcm) + len(part) > SAMPLE_RATE * 2 * MAX_TURN_AUDIO_SECONDS:
                    raise LocalInferenceError("input_limit")
                pcm.extend(part)
            else:
                result = await self.provider._transcribe(bytes(pcm))
                if result.alternatives:
                    self._event_ch.send_nowait(
                        stt.SpeechEvent(type=stt.SpeechEventType.START_OF_SPEECH)
                    )
                    self._event_ch.send_nowait(result)
                    self._event_ch.send_nowait(
                        stt.SpeechEvent(
                            type=stt.SpeechEventType.RECOGNITION_USAGE,
                            recognition_usage=stt.RecognitionUsage(
                                audio_duration=len(pcm) / (SAMPLE_RATE * 2)
                            ),
                        )
                    )
                    self._event_ch.send_nowait(
                        stt.SpeechEvent(type=stt.SpeechEventType.END_OF_SPEECH)
                    )
                pcm.clear()


class LocalTTS(tts.TTS[Never]):
    """Generated Piper PCM from bounded text; no prerecorded phrase lookup."""

    def __init__(
        self,
        settings: LocalInferenceSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=TTS_SAMPLE_RATE,
            num_channels=1,
        )
        self.http = LocalModelHTTP(
            settings.tts_base_url,
            timeout_seconds=TTS_TIMEOUT_SECONDS,
            maximum_response_bytes=MAX_TTS_RESPONSE_BYTES,
            transport=transport,
        )
        self.frames_emitted = 0
        self._closed = False

    @property
    def model(self) -> str:
        return LOCAL_TTS_MODEL

    @property
    def provider(self) -> str:
        return "local-piper"

    def synthesize(
        self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> tts.ChunkedStream:
        try:
            valid = type(text) is str and 0 < len(text.encode("utf-8")) <= MAX_TTS_TEXT_BYTES
        except UnicodeError:
            valid = False
        if not valid or self._closed:
            raise LocalInferenceError("input_limit")
        return _LocalSpeechStream(self, text, conn_options=conn_options)

    async def aclose(self) -> None:
        self._closed = True
        await self.http.aclose()


class _LocalSpeechStream(tts.ChunkedStream):
    def __init__(self, provider: LocalTTS, text: str, *, conn_options: APIConnectOptions) -> None:
        self.provider = provider
        self.text = text
        super().__init__(tts=provider, input_text=text, conn_options=conn_options)

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        raw = await self.provider.http.post("/synthesize", json_body={"text": self.text})
        pcm = decoded_speech(raw)
        output_emitter.initialize(
            request_id="local-tts-" + uuid4().hex,
            sample_rate=TTS_SAMPLE_RATE,
            num_channels=1,
            mime_type="audio/pcm",
            frame_size_ms=20,
        )
        for offset in range(0, len(pcm), TTS_SAMPLE_RATE // 50 * 2):
            output_emitter.push(pcm[offset : offset + TTS_SAMPLE_RATE // 50 * 2])
            self.provider.frames_emitted += 1
            await asyncio.sleep(0)
        output_emitter.flush()
