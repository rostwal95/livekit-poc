"""Explicitly loaded provider_real models for the joined showcase's native runtime.

Reuses the qualified P1 provider adapters: Deepgram nova-3 batch recognition after
an explicit manual flush, OpenAI gpt-5.4-mini and ElevenLabs eleven_v4_turbo. The
three keys reach only the native worker process environment and are read inside
the explicit loader. Importing this module loads no SDK, reads no environment and
starts no task. Models never select durable work: P2's deterministic dispatch
decision still queues the investigation; models produce transcripts and replies.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Any, Final, Literal

from .native_models import NativeModelError

if TYPE_CHECKING:
    from livekit.agents import llm as sdk_llm
    from livekit.agents import stt as sdk_stt
    from livekit.agents import tts as sdk_tts

    from channel_continuity.native import NativeTiming

PROVIDER_MODE: Final = "provider_real"
PROVIDER_LABELS: Final = ("deepgram/nova-3", "openai/gpt-5.4-mini", "elevenlabs/eleven_v4_turbo")
PROVIDER_ENVIRONMENT_KEYS: Final = frozenset(
    {"DEEPGRAM_API_KEY", "OPENAI_API_KEY", "ELEVEN_API_KEY"}
)


def provider_environment(values: Mapping[str, str]) -> dict[str, str]:
    """Copy exactly the three provider keys; values are never reflected in errors."""
    try:
        if not isinstance(values, Mapping) or set(values) != PROVIDER_ENVIRONMENT_KEYS:
            raise ValueError
        copied: dict[str, str] = {}
        for name, value in values.items():
            if (
                type(value) is not str
                or not 16 <= len(value) <= 512
                or any(not 33 <= ord(character) <= 126 for character in value)
            ):
                raise ValueError
            copied[name] = value
        return copied
    except Exception:  # noqa: BLE001 - one finite category; key material is never copied
        raise NativeModelError("invalid_configuration") from None


PROVIDER_INSTRUCTIONS: Final = (
    "You are the voice and chat assistant for a synthetic travel-support case. Every user "
    "message has already been durably recorded and a background policy check runs for the "
    "current case. Reply in one or two short spoken sentences, under 25 words. Only when the "
    "trusted current-result observation has state current, say whether the request is "
    "eligible under the policy as of the latest check, or that more information is needed if "
    "its eligibility is null. States no_delivery, not_applicable and unavailable all mean the "
    "policy check is still running; say exactly that. Never mention "
    "permissions, uncertainty, revisions, timestamps or identifiers. Never claim that a booking "
    "was changed, approved, cancelled or paid, and never request or accept confirmation; "
    "exact approvals happen outside this conversation. No tools are available."
)


def provider_timing() -> NativeTiming:
    """Real models need P1's real-speech commit budget and playout-independent dispatch."""
    from channel_continuity.native import NativeTiming

    return NativeTiming(
        model_seconds=15,
        commit_seconds=11,
        transcript_seconds=10,
        reply="scheduled",
        reply_seconds=60,
        replies=4,
    )


def _recognizer_type() -> type[Any]:
    """Define the turn-binding recognizer only after the explicit SDK/provider load."""
    from livekit import rtc
    from livekit.agents import stt
    from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions

    from channel_continuity.native_models import CommittedTranscript
    from channel_continuity.native_models import uuid as native_uuid
    from services.conversation_agent.inference_settings import (
        MAX_TURN_AUDIO_SECONDS,
        SAMPLE_RATE,
    )
    from services.conversation_agent.provider_settings import ProviderInferenceError
    from services.conversation_agent.provider_speech import (
        ProviderSTT,
        _ProviderRecognizeStream,
    )

    class _TurnStream(_ProviderRecognizeStream):
        """Binds each flushed batch transcript to the turn that captured its audio."""

        captured: str | None = None

        def __init__(self, provider: ProviderRecognizer, *, conn_options: APIConnectOptions):
            self.recognizer = provider
            super().__init__(provider, conn_options=conn_options)

        def push_frame(self, frame: rtc.AudioFrame) -> None:
            original = self.captured if self.captured is not None else self.recognizer.current
            if original is None or original not in self.recognizer.open:
                # Audio outside an explicit turn is never attributed to any input.
                self.recognizer.dropped_frames += 1
                return
            self.captured = original
            self.recognizer.pending.add(original)
            super().push_frame(frame)

        async def _run(self) -> None:
            pcm = bytearray()
            async for item in self._input_ch:
                if isinstance(item, rtc.AudioFrame):
                    part = self.provider._accept_frame(item)
                    if len(pcm) + len(part) > SAMPLE_RATE * 2 * MAX_TURN_AUDIO_SECONDS:
                        raise ProviderInferenceError("input_limit")
                    pcm.extend(part)
                    continue
                original, self.captured = self.captured, None
                try:
                    result = await self.provider._transcribe(bytes(pcm))
                    if result.alternatives:
                        if original is not None and original in self.recognizer.open:
                            self.recognizer.finals[original] = CommittedTranscript(
                                original, result.alternatives[0].text, result.request_id
                            )
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
                finally:
                    if original is not None:
                        self.recognizer.pending.discard(original)
                    pcm.clear()

    class ProviderRecognizer(ProviderSTT):
        """P1's Deepgram adapter plus P2's NativeRecognizer turn identity."""

        def __init__(self, upstream: stt.STT[Any], http_session: Any) -> None:
            super().__init__(upstream, http_session)
            self.current: str | None = None
            self.open: set[str] = set()
            self.pending: set[str] = set()
            self.finals: dict[str, CommittedTranscript] = {}
            self.dropped_frames = 0

        def pending_work(self) -> int:
            return len(self.pending)

        def begin_turn(self, input_id: str) -> None:
            native_uuid(input_id)
            if input_id in self.finals or input_id in self.open or len(self.finals) >= 32:
                raise NativeModelError("capacity_exhausted")
            self.open.add(input_id)
            self.current = input_id

        def final_snapshot(self, input_id: str) -> CommittedTranscript | None:
            native_uuid(input_id)
            return self.finals.get(input_id)

        def end_turn(self, input_id: str) -> None:
            native_uuid(input_id)
            self.open.discard(input_id)
            if self.current == input_id:
                self.current = None

        def stream(
            self,
            *,
            language: Any = None,
            conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
        ) -> stt.RecognizeStream:
            if self._closed:
                raise ProviderInferenceError("closed")
            if len(self.streams) >= 2:
                raise ProviderInferenceError("busy")
            stream = _TurnStream(self, conn_options=conn_options)
            self.streams.add(stream)
            return stream

    return ProviderRecognizer


def toolless_llm_factory() -> Callable[..., Any]:
    """Build P1's OpenAI plugin for a runtime that offers the model no tools.

    OpenAI rejects tool_choice or parallel_tool_calls sent without tools, while P1's
    bounded LLM always requests parallel_tool_calls=False for its tool-using session.
    """
    from livekit.agents import llm
    from livekit.agents.types import (
        DEFAULT_API_CONNECT_OPTIONS,
        NOT_GIVEN,
        APIConnectOptions,
        NotGivenOr,
    )
    from livekit.plugins import openai as openai_plugin

    from services.conversation_agent.provider_settings import ProviderInferenceError

    class ToollessOpenAI(openai_plugin.LLM):
        def chat(
            self,
            *,
            chat_ctx: llm.ChatContext,
            tools: list[llm.Tool] | None = None,
            conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
            parallel_tool_calls: NotGivenOr[bool] = NOT_GIVEN,
            tool_choice: NotGivenOr[llm.ToolChoice] = NOT_GIVEN,
            response_format: Any = NOT_GIVEN,
            extra_kwargs: NotGivenOr[dict[str, Any]] = NOT_GIVEN,
        ) -> Any:
            if tools:
                raise ProviderInferenceError("invalid_configuration")
            return super().chat(
                chat_ctx=chat_ctx,
                conn_options=conn_options,
                response_format=response_format,
                extra_kwargs=extra_kwargs,
            )

    def build(**options: Any) -> Any:
        options.pop("parallel_tool_calls", None)
        options.pop("tool_choice", None)
        return ToollessOpenAI(**options)

    return build


class ProviderModelBundle:
    """Models only; the caller owns the sole NativeRuntime/session and closes it first."""

    def __init__(
        self,
        *,
        stt: sdk_stt.STT[Any],
        llm: sdk_llm.LLM[Any],
        tts: sdk_tts.TTS[Any],
    ) -> None:
        self._stt, self._llm, self._tts = stt, llm, tts
        self._closed = False

    @property
    def stt(self) -> sdk_stt.STT[Any]:
        return self._stt

    @property
    def llm(self) -> sdk_llm.LLM[Any]:
        return self._llm

    @property
    def tts(self) -> sdk_tts.TTS[Any]:
        return self._tts

    @property
    def inference_mode(self) -> Literal["provider_real"]:
        return PROVIDER_MODE

    async def aclose(self) -> None:
        await _close_all([self._tts.aclose, self._llm.aclose, self._stt.aclose])
        self._closed = True


async def _close_all(actions: list[Callable[[], Awaitable[Any]]]) -> None:
    failed = False
    for action in actions:
        try:
            async with asyncio.timeout(2):
                await action()
        except Exception:  # noqa: BLE001 - close independent owners, then report once
            failed = True
    if failed:
        raise NativeModelError("cleanup_incomplete")


async def load_provider_models() -> ProviderModelBundle:
    """Construct the three provider models from this process's environment keys."""
    from services.conversation_agent.provider_http import provider_http_session
    from services.conversation_agent.provider_inference import _plugins
    from services.conversation_agent.provider_llm import create_provider_llm
    from services.conversation_agent.provider_settings import (
        DEEPGRAM_URL,
        ELEVEN_BASE_URL,
        PROVIDER_SAMPLE_RATE,
        PROVIDER_STT_MODEL,
        PROVIDER_TTS_MODEL,
        PROVIDER_VOICE,
        ProviderCredentials,
    )
    from services.conversation_agent.provider_speech import ProviderTTS

    owned: list[Callable[[], Awaitable[Any]]] = []
    try:
        credentials = ProviderCredentials.from_environment()
        plugins = _plugins()
        recognizer_type = _recognizer_type()
        model = await create_provider_llm(credentials.openai, plugin_factory=toolless_llm_factory())
        owned.append(model.aclose)
        deep_session = provider_http_session("stt")
        owned.append(deep_session.close)
        upstream_stt = plugins.stt(
            model=PROVIDER_STT_MODEL,
            language="en",
            sample_rate=16000,
            endpointing_ms=0,
            mip_opt_out=True,
            api_key=credentials.deepgram,
            base_url=DEEPGRAM_URL,
            http_session=deep_session,
        )
        recognizer = recognizer_type(upstream_stt, deep_session)
        owned.remove(deep_session.close)
        owned.append(recognizer.aclose)
        eleven_session = provider_http_session("tts")
        owned.append(eleven_session.close)
        upstream_tts = plugins.tts(
            model=PROVIDER_TTS_MODEL,
            voice_id=PROVIDER_VOICE,
            encoding="pcm_24000",
            api_key=credentials.eleven,
            base_url=ELEVEN_BASE_URL,
            http_session=eleven_session,
            sync_alignment=True,
        )
        if upstream_tts.sample_rate != PROVIDER_SAMPLE_RATE:
            raise NativeModelError("unavailable")
        speaker = ProviderTTS(upstream_tts, eleven_session)
        owned.remove(eleven_session.close)
        owned.append(speaker.aclose)
        return ProviderModelBundle(stt=recognizer, llm=model, tts=speaker)
    except BaseException as error:
        try:
            await _close_all(list(reversed(owned)))
        except NativeModelError:
            pass  # The primary construction failure is reported below.
        if not isinstance(error, Exception):
            raise
        if isinstance(error, NativeModelError):
            raise
        raise NativeModelError("unavailable") from None
