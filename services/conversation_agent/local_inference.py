"""Explicit local-real profile; the scripted creation path remains unchanged."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Protocol

import httpx
import httpx2
from livekit.agents import AgentSession, SessionConnectOptions
from livekit.agents.types import APIConnectOptions

from .inference_llm import PluginFactory, create_local_llm
from .inference_settings import (
    COMMIT_RPC_SECONDS,
    COMMIT_TRANSCRIPT_SECONDS,
    LLM_TIMEOUT_SECONDS,
    LOCAL_GREETING,
    LOCAL_MODE,
    STT_TIMEOUT_SECONDS,
    TTS_TIMEOUT_SECONDS,
    LocalInferenceError,
    LocalInferenceSettings,
)
from .inference_speech import LocalSTT, LocalTTS
from .session import (
    BusinessPort,
    ConversationBinding,
    ConversationControls,
    ConversationRuntime,
    DurableAgent,
    ObservationHook,
)


class OwnedModel(Protocol):
    async def aclose(self) -> None: ...


@dataclass
class LocalConversationRuntime(ConversationRuntime):
    models: tuple[OwnedModel, ...] = ()
    _local_closed: bool = field(default=False, init=False)
    _cleanup_failed: bool = field(default=False, init=False)

    async def aclose(self) -> None:
        if self._local_closed:
            if self._cleanup_failed:
                raise LocalInferenceError("cleanup_incomplete")
            return
        failures = 0
        cancelled: asyncio.CancelledError | None = None
        resources: tuple[tuple[OwnedModel, float], ...] = (
            (self.controls, 0.2),
            (self.session, 2.0),
            *((model, 0.5) for model in self.models),
        )
        for resource, seconds in resources:
            try:
                async with asyncio.timeout(seconds):
                    await resource.aclose()
            except asyncio.CancelledError as error:
                cancelled = cancelled or error
                failures += 1
            except Exception:  # noqa: BLE001 - each owned resource must still be closed
                failures += 1
        self._local_closed = True
        self._closed = True
        self._cleanup_failed = bool(failures)
        if cancelled is not None:
            raise cancelled
        if failures:
            raise LocalInferenceError("cleanup_incomplete")


async def create_local_runtime(
    port: BusinessPort,
    binding: ConversationBinding,
    settings: LocalInferenceSettings,
    *,
    on_observation: ObservationHook | None = None,
    plugin_factory: PluginFactory | None = None,
    speech_transport: httpx.AsyncBaseTransport | None = None,
    llm_transport: httpx2.AsyncBaseTransport | None = None,
) -> LocalConversationRuntime:
    """Construct only preconfigured local endpoints; startup never downloads a model."""
    model = await create_local_llm(settings, plugin_factory=plugin_factory, transport=llm_transport)
    recognizer: LocalSTT | None = None
    speaker: LocalTTS | None = None
    try:
        recognizer = LocalSTT(settings, transport=speech_transport)
        speaker = LocalTTS(settings, transport=speech_transport)
        session: AgentSession[None] = AgentSession(
            stt=recognizer,
            llm=model,
            tts=speaker,
            vad=None,
            turn_handling={"turn_detection": "manual", "preemptive_generation": {"enabled": False}},
            max_tool_steps=2,
            user_away_timeout=None,
            conn_options=SessionConnectOptions(
                stt_conn_options=APIConnectOptions(max_retry=0, timeout=STT_TIMEOUT_SECONDS),
                llm_conn_options=APIConnectOptions(max_retry=0, timeout=LLM_TIMEOUT_SECONDS),
                tts_conn_options=APIConnectOptions(max_retry=0, timeout=TTS_TIMEOUT_SECONDS),
            ),
        )
        controls = ConversationControls(
            session,
            binding,
            recognizer,
            transcript_timeout=COMMIT_TRANSCRIPT_SECONDS,
            commit_timeout=COMMIT_RPC_SECONDS,
        )
        agent = DurableAgent(port, on_observation=on_observation, inference_mode=LOCAL_MODE)
        return LocalConversationRuntime(
            session,
            agent,
            controls,
            recognizer,
            speaker,
            greeting=LOCAL_GREETING,
            inference_mode=LOCAL_MODE,
            models=(recognizer, speaker, model),
        )
    except BaseException as error:
        # Construction did not transfer ownership to a runtime. Each created
        # model receives an independent finite cleanup attempt before propagating.
        for resource in (recognizer, speaker, model):
            if resource is not None:
                try:
                    async with asyncio.timeout(0.5):
                        await resource.aclose()
                except Exception:  # noqa: BLE001,S110 - preserve the original construction failure
                    pass
        if not isinstance(error, Exception):
            raise
        if isinstance(error, LocalInferenceError):
            raise error from None
        raise LocalInferenceError("dependency_unavailable") from None
