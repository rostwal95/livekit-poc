"""Explicit three-key provider profile; no model download or local fallback."""

from __future__ import annotations

import asyncio
import importlib
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import aiohttp
import httpx2
from livekit.agents import AgentSession, SessionConnectOptions, stt, tts
from livekit.agents.types import APIConnectOptions

from .inference_llm import PluginFactory
from .inference_settings import COMMIT_RPC_SECONDS, COMMIT_TRANSCRIPT_SECONDS, selected_profile
from .local_inference import LocalConversationRuntime, OwnedModel
from .provider_http import provider_http_session
from .provider_llm import create_provider_llm
from .provider_settings import (
    DEEPGRAM_URL,
    ELEVEN_BASE_URL,
    PROVIDER_GREETING,
    PROVIDER_MODE,
    PROVIDER_SAMPLE_RATE,
    PROVIDER_STT_MODEL,
    PROVIDER_TTS_MODEL,
    PROVIDER_VOICE,
    ProviderCredentials,
    ProviderInferenceError,
)
from .provider_speech import ProviderSTT, ProviderTTS
from .session import (
    BusinessPort,
    ConversationBinding,
    ConversationControls,
    DurableAgent,
    ObservationHook,
)
from .telemetry import emit


@dataclass(frozen=True)
class ProviderPlugins:
    stt: Callable[..., stt.STT[Any]]
    tts: Callable[..., tts.TTS[Any]]
    llm: PluginFactory | None = None


class ProviderConversationRuntime(LocalConversationRuntime):
    """Reuse independently bounded native/session/model cleanup ownership."""


def _plugins() -> ProviderPlugins:
    try:
        return ProviderPlugins(
            stt=importlib.import_module("livekit.plugins.deepgram").STT,
            tts=importlib.import_module("livekit.plugins.elevenlabs").TTS,
        )
    except Exception:  # noqa: BLE001 - optional plugin import is a private dependency boundary
        raise ProviderInferenceError("dependency_unavailable") from None


async def create_provider_runtime(
    port: BusinessPort,
    binding: ConversationBinding,
    *,
    on_observation: ObservationHook | None = None,
    plugins: ProviderPlugins | None = None,
    session_factory: Callable[[str], aiohttp.ClientSession] = provider_http_session,
    llm_transport: httpx2.AsyncBaseTransport | None = None,
) -> ProviderConversationRuntime:
    if selected_profile(os.environ) != PROVIDER_MODE:
        raise ProviderInferenceError("invalid_configuration")
    credentials = ProviderCredentials.from_environment()
    selected = plugins or _plugins()
    resources: list[OwnedModel] = []
    sessions: list[aiohttp.ClientSession] = []
    try:
        model = await create_provider_llm(
            credentials.openai, plugin_factory=selected.llm, transport=llm_transport
        )
        resources.append(model)
        deep_session = session_factory("stt")
        sessions.append(deep_session)
        upstream_stt = selected.stt(
            model=PROVIDER_STT_MODEL,
            language="en",
            sample_rate=16000,
            endpointing_ms=0,
            mip_opt_out=True,
            api_key=credentials.deepgram,
            base_url=DEEPGRAM_URL,
            http_session=deep_session,
        )
        if not isinstance(upstream_stt, stt.STT):
            raise ProviderInferenceError("dependency_unavailable")
        resources.append(upstream_stt)
        recognizer = ProviderSTT(upstream_stt, deep_session)
        resources.remove(upstream_stt)
        resources.append(recognizer)
        sessions.remove(deep_session)
        eleven_session = session_factory("tts")
        sessions.append(eleven_session)
        upstream_tts = selected.tts(
            model=PROVIDER_TTS_MODEL,
            voice_id=PROVIDER_VOICE,
            encoding="pcm_24000",
            api_key=credentials.eleven,
            base_url=ELEVEN_BASE_URL,
            http_session=eleven_session,
            sync_alignment=True,
        )
        if not isinstance(upstream_tts, tts.TTS):
            raise ProviderInferenceError("dependency_unavailable")
        resources.append(upstream_tts)
        if upstream_tts.sample_rate != PROVIDER_SAMPLE_RATE:
            raise ProviderInferenceError("dependency_unavailable")
        speaker = ProviderTTS(upstream_tts, eleven_session)
        resources.remove(upstream_tts)
        resources.append(speaker)
        sessions.remove(eleven_session)
        session: AgentSession[None] = AgentSession(
            stt=recognizer,
            llm=model,
            tts=speaker,
            vad=None,
            turn_handling={"turn_detection": "manual", "preemptive_generation": {"enabled": False}},
            max_tool_steps=2,
            user_away_timeout=None,
            conn_options=SessionConnectOptions(
                stt_conn_options=APIConnectOptions(max_retry=0, timeout=10),
                llm_conn_options=APIConnectOptions(max_retry=0, timeout=30),
                tts_conn_options=APIConnectOptions(max_retry=0, timeout=10),
            ),
        )
        resources.append(session)
        controls = ConversationControls(
            session,
            binding,
            recognizer,
            transcript_timeout=COMMIT_TRANSCRIPT_SECONDS,
            commit_timeout=COMMIT_RPC_SECONDS,
        )
        agent = DurableAgent(port, on_observation=on_observation, inference_mode=PROVIDER_MODE)
        return ProviderConversationRuntime(
            session,
            agent,
            controls,
            recognizer,
            speaker,
            greeting=PROVIDER_GREETING,
            inference_mode=PROVIDER_MODE,
            models=(recognizer, speaker, model),
        )
    except BaseException as error:
        cleanup_failed = False
        for resource in reversed(resources):
            try:
                async with asyncio.timeout(0.5):
                    await resource.aclose()
            except BaseException:  # noqa: BLE001 - independently close remaining resources
                cleanup_failed = True
        for http_session in sessions:
            try:
                async with asyncio.timeout(0.1):
                    await http_session.close()
            except BaseException:  # noqa: BLE001 - preserve original construction outcome
                cleanup_failed = True
        if cleanup_failed:
            emit("cleanup_failed", "shutdown_incomplete")
        if not isinstance(error, Exception):
            raise
        if isinstance(error, ProviderInferenceError):
            raise error from None
        raise ProviderInferenceError("dependency_unavailable") from None
