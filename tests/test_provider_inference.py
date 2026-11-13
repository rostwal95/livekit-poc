"""Provider profile bounds and wire contracts; no model APIs or real keys."""

import asyncio
import json
import logging
import traceback
import unittest
from types import SimpleNamespace
from typing import Never
from unittest.mock import AsyncMock, Mock, patch

import h11
import httpx2
from livekit import rtc
from livekit.agents import Agent, AgentSession, llm, stt, tts
from livekit.agents.language import LanguageCode
from livekit.agents.voice.io import AudioInput, AudioOutput, AudioOutputCapabilities
from yarl import URL

from services.conversation_agent.inference_settings import LocalInferenceError, selected_profile
from services.conversation_agent.provider_http import BoundedJSONResponse, provider_http_session
from services.conversation_agent.provider_inference import ProviderPlugins, create_provider_runtime
from services.conversation_agent.provider_llm import ProviderLLMTransport, create_provider_llm
from services.conversation_agent.provider_settings import (
    PROVIDER_LLM_MODEL,
    ProviderCredentials,
    ProviderInferenceError,
)
from services.conversation_agent.provider_speech import OperationPool, ProviderSTT, ProviderTTS
from services.conversation_agent.session import ConversationBinding, DurableAgent
from services.conversation_agent.telemetry import _SafeFormatter

SENTINEL = "SECRET_PROVIDER_SENTINEL"
KEY = "test-" + SENTINEL
ENV = {
    "P1_CONVERSATION_INFERENCE": "provider_real",
    "OPENAI_API_KEY": KEY,
    "DEEPGRAM_API_KEY": KEY,
    "ELEVEN_API_KEY": KEY,
}


def http_session():
    value = SimpleNamespace(closed=False)

    async def close():
        value.closed = True

    value.close = AsyncMock(side_effect=close)
    return value


def frame(samples=320, silent=False, rate=16000):
    return rtc.AudioFrame(bytes(samples * 2) if silent else b"\x10\x27" * samples, rate, 1, samples)


class Recognizer(stt.STT[Never]):
    def __init__(self):
        super().__init__(capabilities=stt.STTCapabilities(streaming=False, interim_results=False))
        self.calls = 0
        self.closed = False
        self.failure = None
        self.blocked = None
        self.entered = asyncio.Event()
        self.answer = "Inspect my current case."

    async def _recognize_impl(self, buffer, *, language, conn_options):
        self.calls += 1
        self.entered.set()
        if self.blocked is not None:
            await self.blocked.wait()
        if self.failure is not None:
            raise self.failure
        return stt.SpeechEvent(
            type=stt.SpeechEventType.FINAL_TRANSCRIPT,
            alternatives=[stt.SpeechData(language=LanguageCode("en"), text=self.answer)],
        )

    async def aclose(self):
        self.closed = True


class Speaker(tts.TTS[Never]):
    def __init__(self):
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False), sample_rate=24000, num_channels=1
        )
        self.closed = False
        self.samples = 2400
        self.blocked = None
        self.entered = asyncio.Event()

    def synthesize(self, text, *, conn_options):
        return Speech(self, text, conn_options)

    async def aclose(self):
        self.closed = True


class Speech(tts.ChunkedStream):
    def __init__(self, owner, text, options):
        self.owner = owner
        super().__init__(tts=owner, input_text=text, conn_options=options)

    async def _run(self, output_emitter):
        self.owner.entered.set()
        if self.owner.blocked is not None:
            await self.owner.blocked.wait()
        output_emitter.initialize(
            request_id="synthetic-provider-test",
            sample_rate=24000,
            num_channels=1,
            mime_type="audio/pcm",
            frame_size_ms=20,
        )
        output_emitter.push(b"\x01\x10" * self.owner.samples)
        output_emitter.flush()


def request():
    return httpx2.Request(
        "POST",
        "https://api.openai.com/v1/chat/completions",
        json={
            "model": PROVIDER_LLM_MODEL,
            "store": False,
            "reasoning_effort": "none",
            "max_completion_tokens": 128,
        },
    )


class ProviderBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_guards_reject_wrong_origins_redirects_and_proxy_inheritance(self):
        for role, valid in (
            ("stt", "https://api.deepgram.com/v1/listen?model=nova-3"),
            ("tts", "https://api.elevenlabs.io/v1/text-to-dialogue/stream?output_format=pcm_24000"),
        ):
            session = provider_http_session(role)
            try:
                self.assertFalse(session.trust_env)
                self.assertFalse(session.auto_decompress)
                self.assertEqual(session.connector.limit, 1)
                self.assertEqual(session.connector.limit_per_host, 1)
                start = session.trace_configs[0].on_request_start[0]
                await start(session, None, SimpleNamespace(method="POST", url=URL(valid)))
                for method, url in (
                    ("GET", valid),
                    ("POST", valid.replace("https:", "http:")),
                    ("POST", "https://private.invalid/v1/listen"),
                    ("POST", valid + "#private"),
                    ("POST", valid.replace("https://", "https://user:pass@")),
                ):
                    with self.assertRaises(ProviderInferenceError):
                        await start(session, None, SimpleNamespace(method=method, url=URL(url)))
                with self.assertRaises(ProviderInferenceError):
                    await session.trace_configs[0].on_request_redirect[0](session, None, None)
            finally:
                await session.close()
        with self.assertRaises(ProviderInferenceError):
            provider_http_session("ambient")

    async def test_bounded_asr_json_rejects_error_body_oversize_and_private_decode_failure(self):
        class Content:
            def __init__(self, payload):
                self.payload, self.reads = payload, 0

            async def iter_chunked(self, size):
                self.reads += 1
                for index in range(0, len(self.payload), size):
                    yield self.payload[index : index + size]

        class Response(BoundedJSONResponse):
            def __init__(self, status, payload):
                self.status, self.content = status, Content(payload)
                self.did_close = False

            @property
            def content_type(self):
                return "application/json"

            def close(self):
                self.did_close = True

        response = Response(200, b'{"ok":true}')
        self.assertEqual(await response.json(), {"ok": True})
        self.assertEqual(await response.read(), b'{"ok":true}')
        self.assertEqual(response.content.reads, 1)
        for status in (401, 403, 429, 500):
            response = Response(status, SENTINEL.encode())
            with self.assertRaises(ProviderInferenceError) as caught:
                await response.json()
            self.assertEqual(response.content.reads, 0)
            self.assertTrue(response.did_close)
            self.assertNotIn(SENTINEL, str(caught.exception))
        for payload in (b"x" * 16385, SENTINEL.encode(), b"\xff"):
            response = Response(200, payload)
            with self.assertRaises(ProviderInferenceError) as caught:
                await response.json()
            self.assertNotIn(SENTINEL, "".join(traceback.format_exception(caught.exception)))

    async def test_tts_audio_limit_admission_and_cancelled_cleanup_remain_finite(self):
        source, session = Speaker(), http_session()
        source.samples = 24000 * 21
        model = ProviderTTS(source, session)
        try:
            with self.assertRaises(ProviderInferenceError) as caught:
                async with model.synthesize("Synthetic overlong response.") as stream:
                    async for _ in stream:
                        pass
            self.assertEqual(caught.exception.code, "response_limit")
        finally:
            await model.aclose()
        source, session = Speaker(), http_session()
        source.blocked = asyncio.Event()
        model = ProviderTTS(source, session)
        first = model.synthesize("Synthetic first response.")
        await source.entered.wait()
        second = model.synthesize("Synthetic queued response.")
        with self.assertRaises(ProviderInferenceError):
            model.synthesize("Rejected third response.")
        await model.aclose()
        self.assertEqual(model.pool.pending, 0)
        self.assertFalse(model.streams)
        self.assertTrue(source.closed)
        self.assertTrue(session.closed)
        await first.aclose()
        await second.aclose()

    async def test_cleanup_failure_still_closes_http_and_never_formats_provider_exception(self):
        source, session = Recognizer(), http_session()
        source.aclose = AsyncMock(side_effect=RuntimeError(SENTINEL))
        model = ProviderSTT(source, session)
        with self.assertRaises(ProviderInferenceError) as caught:
            await model.aclose()
        self.assertTrue(session.closed)
        self.assertEqual(caught.exception.code, "cleanup_incomplete")
        self.assertNotIn(SENTINEL, "".join(traceback.format_exception(caught.exception)))
        with self.assertRaises(ProviderInferenceError):
            await model.aclose()

    async def test_provider_log_boundary_discards_messages_exception_chains_and_private_extras(
        self,
    ):
        formatter = _SafeFormatter()
        for namespace in (
            "livekit.plugins.deepgram",
            "livekit.plugins.elevenlabs",
            "openai",
            "aiohttp",
            "websockets",
        ):
            record = logging.LogRecord(namespace, logging.ERROR, __file__, 1, SENTINEL, (), None)
            record.private = SENTINEL
            record.exc_info = (RuntimeError, RuntimeError(SENTINEL), None)
            output = formatter.format(record)
            self.assertNotIn(SENTINEL, output)
            self.assertEqual(
                set(json.loads(output)), {"service", "timestamp", "severity", "event", "code"}
            )

    async def test_actual_sdk_clear_user_turn_preserves_replacement_stream_and_real_flush(self):
        class QueueInput(AudioInput):
            def __init__(self):
                super().__init__(label="provider-reset-fixture")
                self.frames = asyncio.Queue(maxsize=32)

            async def __anext__(self):
                return await self.frames.get()

        source, client = Recognizer(), http_session()
        model = ProviderSTT(source, client)
        audio = QueueInput()
        session = AgentSession(
            stt=model,
            vad=None,
            turn_handling={"turn_detection": "manual", "preemptive_generation": {"enabled": False}},
        )
        session.input.audio = audio
        await session.start(
            Agent(instructions="Offline manual ASR fixture."), record=False, session_host=False
        )
        session.input.set_audio_enabled(False)
        try:
            async with asyncio.timeout(2):
                while not model.streams:
                    await asyncio.sleep(0.001)
            for turn in range(1, 4):
                previous = model.audio_seconds
                session.clear_user_turn()
                session.input.set_audio_enabled(True)
                for _ in range(10):
                    await audio.frames.put(frame())
                async with asyncio.timeout(2):
                    while model.audio_seconds < previous + 0.19:
                        await asyncio.sleep(0.001)
                session.input.set_audio_enabled(False)
                await session.commit_user_turn(
                    transcript_timeout=1, stt_flush_duration=0.1, skip_reply=True
                )
                self.assertEqual(model.turns, turn)
                self.assertEqual(source.calls, turn)
                self.assertEqual(model.pool.pending, 0)
                self.assertEqual(len(model.streams), 1)
        finally:
            await session.aclose()
            await model.aclose()
        self.assertFalse(model.streams)
        self.assertTrue(source.closed)
        self.assertTrue(client.closed)

    async def test_actual_sdk_manual_turn_reaches_provider_wire_with_its_cache_marker(self):
        class QueueInput(AudioInput):
            def __init__(self):
                super().__init__(label="provider-llm-session-fixture")
                self.frames = asyncio.Queue(maxsize=32)

            async def __anext__(self):
                return await self.frames.get()

        class AudioSink(AudioOutput):
            def __init__(self):
                super().__init__(
                    label="provider-llm-session-sink",
                    capabilities=AudioOutputCapabilities(pause=False),
                    sample_rate=24000,
                )
                self.frames = 0
                self.seconds = 0.0
                self.finished = asyncio.Event()

            async def capture_frame(self, frame):
                await super().capture_frame(frame)
                self.frames += 1
                self.seconds += frame.duration

            def flush(self):
                super().flush()
                self.on_playback_finished(playback_position=self.seconds, interrupted=False)
                self.seconds = 0.0
                self.finished.set()

            def clear_buffer(self):
                if self.seconds:
                    self.on_playback_finished(playback_position=self.seconds, interrupted=True)
                self.seconds = 0.0

        for legacy_guard in (True, False):
            with self.subTest(legacy_guard=legacy_guard):
                wire_requests, guard_codes, markers, usage = [], [], [], []
                called = asyncio.Event()

                def wire(req, wire_requests=wire_requests):
                    body = json.loads(req.content)
                    self.assertEqual(body["model"], PROVIDER_LLM_MODEL)
                    self.assertIs(body["store"], False)
                    self.assertEqual(body["reasoning_effort"], "none")
                    self.assertEqual(
                        {tool["function"]["name"] for tool in body["tools"]},
                        {"submit_investigation", "get_case", "cancel_case"},
                    )
                    # SDK cache controls must not create new fields on this GPT-5.4 wire.
                    self.assertNotIn("cache_breakpoint", json.dumps(body))
                    wire_requests.append(req)
                    payload = {
                        "id": "provider-session-fixture",
                        "model": PROVIDER_LLM_MODEL,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"role": "assistant", "content": "Synthetic reply."},
                                "finish_reason": None,
                            }
                        ],
                    }
                    tokens = {
                        "id": "provider-session-fixture",
                        "model": PROVIDER_LLM_MODEL,
                        "choices": [],
                        "usage": {"prompt_tokens": 5, "completion_tokens": 4, "total_tokens": 9},
                    }
                    return httpx2.Response(
                        200,
                        headers={"content-type": "text/event-stream"},
                        content=(
                            "data: "
                            + json.dumps(payload)
                            + "\n\ndata: "
                            + json.dumps(tokens)
                            + "\n\ndata: [DONE]\n\n"
                        ).encode(),
                    )

                model = await create_provider_llm(KEY, transport=httpx2.MockTransport(wire))
                original = model.chat

                def observed_chat(
                    _original=original,
                    _legacy_guard=legacy_guard,
                    _markers=markers,
                    _guard_codes=guard_codes,
                    _called=called,
                    **kwargs,
                ):
                    parts = [
                        part
                        for item in kwargs["chat_ctx"].items
                        if isinstance(item, llm.ChatMessage)
                        for part in item.content
                    ]
                    _markers.extend(part for part in parts if type(part) is llm.CacheBreakpoint)
                    try:
                        # Positive control for the exact old production failure, before any wire I/O.
                        if _legacy_guard and any(type(part) is not str for part in parts):
                            raise LocalInferenceError("input_limit")
                        return _original(**kwargs)
                    except LocalInferenceError as error:
                        _guard_codes.append(error.code)
                        raise
                    finally:
                        _called.set()

                model.chat = observed_chat
                model.on("metrics_collected", usage.append)
                source, speaker = Recognizer(), Speaker()
                recognizer = ProviderSTT(source, http_session())
                synthesizer = ProviderTTS(speaker, http_session())
                audio, sink = QueueInput(), AudioSink()
                port = SimpleNamespace(
                    submit_investigation=AsyncMock(), get_case=AsyncMock(), cancel_case=AsyncMock()
                )
                session = AgentSession(
                    stt=recognizer,
                    llm=model,
                    tts=synthesizer,
                    vad=None,
                    turn_handling={
                        "turn_detection": "manual",
                        "preemptive_generation": {"enabled": False},
                    },
                )
                session.input.audio, session.output.audio = audio, sink
                try:
                    await session.start(
                        DurableAgent(port, inference_mode="provider_real"),
                        record=False,
                        session_host=False,
                    )
                    session.input.set_audio_enabled(False)
                    async with asyncio.timeout(2):
                        while not recognizer.streams:
                            await asyncio.sleep(0.001)
                    session.clear_user_turn()
                    session.input.set_audio_enabled(True)
                    for _ in range(10):
                        await audio.frames.put(frame())
                    async with asyncio.timeout(2):
                        while recognizer.audio_seconds < 0.19:
                            await asyncio.sleep(0.001)
                    session.input.set_audio_enabled(False)
                    await session.commit_user_turn(transcript_timeout=1, stt_flush_duration=0.1)
                    async with asyncio.timeout(3):
                        await called.wait()
                        if not legacy_guard:
                            await sink.finished.wait()
                    self.assertEqual(recognizer.turns, 1)
                    self.assertEqual(source.calls, 1)
                    self.assertEqual(len(markers), 1)
                finally:
                    await session.aclose()
                    await recognizer.aclose()
                    await model.aclose()
                    await synthesizer.aclose()
                self.assertFalse(recognizer.streams)
                self.assertEqual(recognizer.pool.pending, 0)
                self.assertTrue(source.closed)
                self.assertTrue(speaker.closed)
                for method in (port.submit_investigation, port.get_case, port.cancel_case):
                    method.assert_not_awaited()
                if legacy_guard:
                    self.assertEqual(guard_codes, ["input_limit"])
                    self.assertFalse(wire_requests)
                    self.assertEqual(sink.frames, 0)
                else:
                    self.assertFalse(guard_codes)
                    self.assertEqual(len(wire_requests), 1)
                    self.assertGreater(sink.frames, 0)
                    self.assertTrue(
                        any(
                            item.prompt_tokens == 5 and item.completion_tokens == 4
                            for item in usage
                        )
                    )

    async def test_two_stt_handles_are_bounded_and_both_close_cancels_actual_recognition(self):
        source, client = Recognizer(), http_session()
        source.blocked = asyncio.Event()
        model = ProviderSTT(source, client)
        first, second = model.stream(), model.stream()
        with self.assertRaises(ProviderInferenceError) as caught:
            model.stream()
        self.assertEqual(caught.exception.code, "busy")
        first.push_frame(frame())
        first.flush()
        await source.entered.wait()
        self.assertEqual(model.pool.pending, 1)
        await model.aclose()
        self.assertEqual(model.pool.pending, 0)
        self.assertFalse(model.streams)
        self.assertTrue(source.closed)
        self.assertTrue(client.closed)
        await first.aclose()
        await second.aclose()

    async def test_stt_run_completion_retains_handle_until_sdk_close_is_observed(self):
        model = ProviderSTT(Recognizer(), http_session())
        first = model.stream()
        first.end_input()
        self.assertEqual([event async for event in first], [])
        self.assertIn(first, model.streams)
        second = model.stream()
        with self.assertRaises(ProviderInferenceError):
            model.stream()
        await first.aclose()
        self.assertNotIn(first, model.streams)
        replacement = model.stream()
        self.assertEqual(len(model.streams), 2)
        await model.aclose()
        self.assertFalse(model.streams)
        await second.aclose()
        await replacement.aclose()

    async def test_cancelled_sdk_stream_close_does_not_drop_owned_handle(self):
        model = ProviderSTT(Recognizer(), http_session())
        stream = model.stream()
        entered, release = asyncio.Event(), asyncio.Event()

        async def held_close(_stream):
            entered.set()
            await release.wait()

        try:
            with patch.object(stt.RecognizeStream, "aclose", held_close):
                closing = asyncio.create_task(stream.aclose())
                await entered.wait()
                closing.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await closing
            self.assertIn(stream, model.streams)
            await stream.aclose()
            self.assertNotIn(stream, model.streams)
        finally:
            await model.aclose()

    async def test_explicit_profile_and_credentials_validation_never_formats_values(self):
        self.assertEqual(selected_profile({}), "scripted")
        self.assertEqual(
            selected_profile({"P1_CONVERSATION_INFERENCE": "local_real"}), "local_real"
        )
        self.assertEqual(selected_profile(ENV), "provider_real")
        with patch("os.environ", ENV):
            credentials = ProviderCredentials.from_environment()
            self.assertNotIn(SENTINEL, repr(credentials))
        for invalid in (None, "", "short", "x" * 513, "bad key with spaces"):
            with (
                patch("os.environ", {**ENV, "OPENAI_API_KEY": invalid}),
                self.assertRaises(ProviderInferenceError),
            ):
                ProviderCredentials.from_environment()
        with (
            patch("os.environ", {"P1_CONVERSATION_INFERENCE": "scripted"}),
            patch.object(
                ProviderCredentials,
                "from_environment",
                side_effect=AssertionError("No credential access"),
            ),
            self.assertRaises(ProviderInferenceError),
        ):
            await create_provider_runtime(Mock(), ConversationBinding("browser-provider-test"))

    async def test_official_openai_plugin_uses_fixed_model_reasoning_tls_host_and_authorization(
        self,
    ):
        captured = []

        def handle(req):
            captured.append(req)
            codec = h11.Connection(h11.CLIENT)
            codec.send(
                h11.Request(
                    method=req.method, target=req.url.raw_path, headers=list(req.headers.raw)
                )
            )
            payload = {
                "id": "provider-wire-test",
                "model": PROVIDER_LLM_MODEL,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": "Synthetic test output."},
                        "finish_reason": None,
                    }
                ],
            }
            usage = {
                "id": "provider-wire-test",
                "model": PROVIDER_LLM_MODEL,
                "choices": [],
                "usage": {"prompt_tokens": 5, "completion_tokens": 4, "total_tokens": 9},
            }
            return httpx2.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=(
                    "data: "
                    + json.dumps(payload)
                    + "\n\ndata: "
                    + json.dumps(usage)
                    + "\n\ndata: [DONE]\n\n"
                ).encode(),
            )

        with patch(
            "os.environ",
            {
                **ENV,
                "OPENAI_CUSTOM_HEADERS": json.dumps(
                    {"x-private": SENTINEL, "Authorization": SENTINEL}
                ),
                "HTTPS_PROXY": "http://private.invalid",
            },
        ):
            model = await create_provider_llm(KEY, transport=httpx2.MockTransport(handle))
            try:
                context = llm.ChatContext.empty()
                context.add_message(role="user", content="status")
                tools = DurableAgent(Mock(), inference_mode="provider_real").tools
                async with model.chat(chat_ctx=context, tools=tools) as stream:
                    chunks = [chunk async for chunk in stream]
                self.assertEqual(model.model, PROVIDER_LLM_MODEL)
                self.assertEqual(model.provider, "openai")
                self.assertTrue(any(chunk.delta and chunk.delta.content for chunk in chunks))
                self.assertEqual(len(captured), 1)
                req = captured[0]
                body = json.loads(req.content)
                self.assertEqual(str(req.url), "https://api.openai.com/v1/chat/completions")
                self.assertEqual(req.headers["host"], "api.openai.com")
                self.assertEqual(req.headers["authorization"], "Bearer " + KEY)
                self.assertNotIn("x-private", req.headers)
                functions = [tool["function"] for tool in body["tools"]]
                self.assertEqual(
                    {tool["name"] for tool in functions},
                    {"submit_investigation", "get_case", "cancel_case"},
                )
                self.assertTrue(
                    all(tool["parameters"].get("properties", {}) == {} for tool in functions)
                )
                self.assertTrue(
                    all(tool["parameters"].get("required", []) == [] for tool in functions)
                )
                self.assertEqual(
                    (
                        body["model"],
                        body["reasoning_effort"],
                        body["max_completion_tokens"],
                        body["store"],
                    ),
                    (PROVIDER_LLM_MODEL, "none", 128, False),
                )
            finally:
                await model.aclose()

    async def test_provider_wire_rejects_redirect_auth_quota_and_body_limits_without_reading_errors(
        self,
    ):
        class PrivateBody(httpx2.AsyncByteStream):
            async def __aiter__(self):
                raise AssertionError("Provider error bodies must not be consumed")
                yield b""

            async def aclose(self):
                pass

        for status in (302, 401, 403, 429, 500):
            transport = ProviderLLMTransport(
                KEY,
                httpx2.MockTransport(
                    lambda req, status=status: httpx2.Response(status, stream=PrivateBody())
                ),
            )
            with self.subTest(status=status), self.assertRaises(ProviderInferenceError) as caught:
                await transport.handle_async_request(request())
            self.assertNotIn(SENTINEL, str(caught.exception))
            self.assertEqual(transport._pending, 0)
            await transport.aclose()
        transport = ProviderLLMTransport(
            KEY, httpx2.MockTransport(lambda req: httpx2.Response(200, content=b"x" * 65537))
        )
        with self.assertRaises(ProviderInferenceError):
            await transport.handle_async_request(request())
        self.assertEqual(transport._pending, 0)
        await transport.aclose()

    async def test_llm_body_retains_one_active_one_waiting_and_cancelled_waiter_releases_admission(
        self,
    ):
        class OpenBody(httpx2.AsyncByteStream):
            async def __aiter__(self):
                yield b"ok"

            async def aclose(self):
                pass

        transport = ProviderLLMTransport(
            KEY, httpx2.MockTransport(lambda req: httpx2.Response(200, stream=OpenBody()))
        )
        first = await transport.handle_async_request(request())
        second = asyncio.create_task(transport.handle_async_request(request()))
        await asyncio.sleep(0)
        with self.assertRaises(ProviderInferenceError) as caught:
            await transport.handle_async_request(request())
        self.assertEqual(caught.exception.code, "busy")
        second.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await second
        self.assertEqual(transport._pending, 1)
        await first.aclose()
        self.assertEqual(transport._pending, 0)
        await transport.aclose()

    async def test_pool_keeps_actual_work_owned_and_close_cancels_both_slots(self):
        pool = OperationPool()
        entered = asyncio.Event()
        release = asyncio.Event()

        async def held():
            entered.set()
            await release.wait()
            return "ok"

        first = asyncio.create_task(pool.run(held))
        await entered.wait()
        second = asyncio.create_task(pool.run(held))
        await asyncio.sleep(0)
        with self.assertRaises(ProviderInferenceError):
            await pool.run(held)
        await pool.aclose()
        self.assertTrue(first.cancelled())
        self.assertTrue(second.cancelled())
        self.assertEqual(pool.pending, 0)
        with self.assertRaises(ProviderInferenceError):
            await pool.run(held)

    async def test_batch_manual_flush_emits_actual_final_and_received_audio_usage(self):
        source = Recognizer()
        session = http_session()
        model = ProviderSTT(source, session)
        try:
            self.assertTrue(model.capabilities.manual_flush)
            self.assertFalse(model.capabilities.interim_results)
            async with model.stream() as stream:
                for _ in range(10):
                    stream.push_frame(frame())
                self.assertEqual(model.turns, 0)
                self.assertEqual(source.calls, 0)
                stream.flush()
                events = []
                async for event in stream:
                    events.append(event)
                    if event.type is stt.SpeechEventType.END_OF_SPEECH:
                        break
            self.assertEqual(model.turns, 1)
            self.assertEqual(source.calls, 1)
            self.assertEqual(
                next(
                    event for event in events if event.type is stt.SpeechEventType.FINAL_TRANSCRIPT
                )
                .alternatives[0]
                .text,
                source.answer,
            )
            self.assertAlmostEqual(
                next(
                    event for event in events if event.type is stt.SpeechEventType.RECOGNITION_USAGE
                ).recognition_usage.audio_duration,
                0.2,
            )
            self.assertEqual((model.model, model.provider), ("nova-3", "deepgram"))
        finally:
            await model.aclose()
        self.assertTrue(source.closed)
        self.assertTrue(session.closed)

    async def test_silence_oversize_and_provider_failure_cannot_be_recognized_turns(self):
        source = Recognizer()
        model = ProviderSTT(source, http_session())
        try:
            silent = await model.recognize(frame(silent=True))
            self.assertEqual(silent.alternatives, [])
            self.assertEqual(source.calls, 0)
            with self.assertRaises(LocalInferenceError):
                await model._transcribe(b"\x01\x10" * (16000 * 12 + 1))
            source.failure = RuntimeError(SENTINEL)
            with self.assertRaises(ProviderInferenceError) as caught:
                await model.recognize(frame())
            self.assertNotIn(SENTINEL, "".join(traceback.format_exception(caught.exception)))
            self.assertEqual(model.turns, 0)
        finally:
            await model.aclose()

    async def test_stt_shutdown_owns_and_cancels_accepted_recognition(self):
        source = Recognizer()
        source.blocked = asyncio.Event()
        session = http_session()
        model = ProviderSTT(source, session)
        caller = asyncio.create_task(model.recognize(frame()))
        await source.entered.wait()
        await model.aclose()
        with self.assertRaises(asyncio.CancelledError):
            await caller
        self.assertTrue(source.closed)
        self.assertTrue(session.closed)
        self.assertEqual(model.pool.pending, 0)

    async def test_tts_forwards_generated_pcm_and_truthful_labels_without_alignment_claim(self):
        source = Speaker()
        session = http_session()
        model = ProviderTTS(source, session)
        try:
            self.assertFalse(model.capabilities.aligned_transcript)
            async with model.synthesize("Synthetic test output.") as stream:
                frames = [event.frame async for event in stream]
            self.assertTrue(frames)
            self.assertTrue(any(byte for item in frames for byte in item.data.cast("B")))
            self.assertTrue(
                all(item.sample_rate == 24000 and item.num_channels == 1 for item in frames)
            )
            self.assertEqual((model.model, model.provider), ("eleven_v4_turbo", "elevenlabs"))
            with self.assertRaises(ProviderInferenceError):
                model.synthesize("x" * 1025)
        finally:
            await model.aclose()
        self.assertTrue(source.closed)
        self.assertTrue(session.closed)

    async def test_factory_passes_fixed_provider_options_and_closes_all_resources(self):
        from livekit.plugins import openai

        source_stt, source_tts = Recognizer(), Speaker()
        sessions = []
        stt_factory, tts_factory = Mock(return_value=source_stt), Mock(return_value=source_tts)

        def session_factory(_role):
            value = http_session()
            sessions.append(value)
            return value

        with patch("os.environ", ENV):
            runtime = await create_provider_runtime(
                Mock(),
                ConversationBinding("browser-provider-test"),
                plugins=ProviderPlugins(stt_factory, tts_factory, openai.LLM),
                session_factory=session_factory,
                llm_transport=httpx2.MockTransport(
                    lambda req: (_ for _ in ()).throw(AssertionError("No startup inference"))
                ),
            )
        self.assertEqual(runtime.inference_mode, "provider_real")
        self.assertEqual(
            {tool.info.name for tool in runtime.agent.tools},
            {"submit_investigation", "get_case", "cancel_case"},
        )
        self.assertEqual(stt_factory.call_args.kwargs["model"], "nova-3")
        self.assertTrue(stt_factory.call_args.kwargs["mip_opt_out"])
        self.assertEqual(tts_factory.call_args.kwargs["model"], "eleven_v4_turbo")
        self.assertEqual(tts_factory.call_args.kwargs["voice_id"], "JBFqnCBsd6RMkjVDRZzb")
        self.assertNotIn("enable_logging", tts_factory.call_args.kwargs)
        await runtime.aclose()
        self.assertTrue(source_stt.closed)
        self.assertTrue(source_tts.closed)
        self.assertTrue(all(session.closed for session in sessions))

    async def test_runtime_cancellation_still_closes_all_model_and_http_owners(self):
        from livekit.plugins import openai

        source_stt, source_tts = Recognizer(), Speaker()
        sessions = []

        def session_factory(_role):
            value = http_session()
            sessions.append(value)
            return value

        with patch("os.environ", ENV):
            runtime = await create_provider_runtime(
                Mock(),
                ConversationBinding("browser-provider-test"),
                plugins=ProviderPlugins(
                    Mock(return_value=source_stt), Mock(return_value=source_tts), openai.LLM
                ),
                session_factory=session_factory,
            )
        runtime.controls.aclose = AsyncMock(side_effect=asyncio.CancelledError())
        with self.assertRaises(asyncio.CancelledError):
            await runtime.aclose()
        self.assertTrue(source_stt.closed)
        self.assertTrue(source_tts.closed)
        self.assertTrue(all(item.closed for item in sessions))
        self.assertTrue(runtime.models[-1]._client.is_closed())
        with self.assertRaises(LocalInferenceError):
            await runtime.aclose()

    async def test_partial_factory_failure_or_cancellation_closes_created_models_and_sessions(self):
        from livekit.plugins import openai

        for error in (RuntimeError(SENTINEL), asyncio.CancelledError(SENTINEL)):
            source_stt = Recognizer()
            sessions = []

            def session_factory(_role, sessions=sessions):
                value = http_session()
                sessions.append(value)
                return value

            with (
                patch("os.environ", ENV),
                self.assertRaises(
                    asyncio.CancelledError
                    if isinstance(error, asyncio.CancelledError)
                    else ProviderInferenceError
                ) as caught,
            ):
                await create_provider_runtime(
                    Mock(),
                    ConversationBinding("browser-provider-test"),
                    plugins=ProviderPlugins(
                        Mock(return_value=source_stt), Mock(side_effect=error), openai.LLM
                    ),
                    session_factory=session_factory,
                )
            self.assertTrue(source_stt.closed)
            self.assertTrue(all(session.closed for session in sessions))
            if not isinstance(error, asyncio.CancelledError):
                self.assertNotIn(SENTINEL, "".join(traceback.format_exception(caught.exception)))


if __name__ == "__main__":
    unittest.main()
