"""Offline real-profile contracts; actual local models remain a separate mandatory lane."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import traceback
import unittest
from array import array
from dataclasses import FrozenInstanceError
from typing import Never
from unittest.mock import AsyncMock, patch

import h11
import httpx
import httpx2
from livekit import rtc
from livekit.agents import llm, stt
from livekit.agents.types import APIConnectOptions

from services.conversation_agent.inference_http import LocalModelHTTP, strict_transcript
from services.conversation_agent.inference_llm import (
    LocalLLMTransport,
    bounded_chunk,
    create_local_llm,
)
from services.conversation_agent.inference_settings import (
    LOCAL_GREETING,
    LOCAL_INSTRUCTIONS,
    LOCAL_LLM_MODEL,
    MAX_MODEL_CONTEXT_BYTES,
    MAX_MODEL_OUTPUT_BYTES,
    MAX_OUTPUT_TOKENS,
    SAMPLE_RATE,
    TTS_SAMPLE_RATE,
    LocalInferenceError,
    LocalInferenceSettings,
    selected_profile,
)
from services.conversation_agent.inference_speech import (
    LocalSTT,
    LocalTTS,
    decoded_speech,
    wav_bytes,
)
from services.conversation_agent.local_inference import create_local_runtime
from services.conversation_agent.session import ConversationBinding, ConversationControls
from services.conversation_agent.telemetry import configure_logging

SENTINEL = "private-provider-prompt-credential-sentinel"
OPTIONS = APIConnectOptions(max_retry=0, timeout=1)


class Bytes(httpx.AsyncByteStream):
    def __init__(self, parts):
        self.parts, self.reads, self.closes = parts, 0, 0

    async def __aiter__(self):
        for part in self.parts:
            self.reads += 1
            yield part

    async def aclose(self):
        self.closes += 1


class Bytes2(httpx2.AsyncByteStream):
    def __init__(self, parts):
        self.parts, self.reads, self.closes = parts, 0, 0

    async def __aiter__(self):
        for part in self.parts:
            self.reads += 1
            yield part

    async def aclose(self):
        self.closes += 1


def response(body, status=200, headers=None):
    return httpx.Response(status, headers=headers, stream=Bytes([body]))


def frame(samples=320, *, sample_rate=SAMPLE_RATE, channels=1, level=1000):
    return rtc.AudioFrame(
        data=array("h", [level] * samples * channels).tobytes(),
        sample_rate=sample_rate,
        num_channels=channels,
        samples_per_channel=samples,
    )


def chunk(text="A generated answer.", calls=None):
    return llm.ChatChunk(
        id="local-test-id",
        delta=llm.ChoiceDelta(role="assistant", content=text, tool_calls=calls or []),
    )


class NativeLLM(llm.LLM[Never]):
    def __init__(self, chunks=None, failure=None, blocked=None):
        super().__init__()
        self.chunks = chunks if chunks is not None else [chunk()]
        self.failure, self.blocked = failure, blocked
        self.calls, self.closes, self.stream_closes = [], 0, 0

    def chat(self, *, chat_ctx, tools=None, conn_options=OPTIONS, **kwargs):
        self.calls.append(kwargs)
        return NativeStream(self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options)

    async def aclose(self):
        self.closes += 1


class NativeStream(llm.LLMStream):
    def __init__(self, provider, **kwargs):
        self.provider = provider
        super().__init__(provider, **kwargs)

    async def _run(self):
        try:
            if self.provider.blocked:
                await self.provider.blocked.wait()
            if self.provider.failure:
                raise self.provider.failure
            for item in self.provider.chunks:
                self._event_ch.send_nowait(item)
                await asyncio.sleep(0)
        finally:
            self.provider.stream_closes += 1


class Port:
    async def submit_investigation(self):
        return {"status": "accepted"}

    async def get_case(self):
        return {"status": "observed"}

    async def cancel_case(self):
        return {"status": "requested"}

    async def aclose(self):
        return None


class SettingsTests(unittest.TestCase):
    def test_opt_in_identities_are_fixed_and_immutable_with_no_remote_or_model_override(self):
        settings = LocalInferenceSettings()
        self.assertEqual(settings.llm_base_url, "http://p1-llm:11434/v1")
        self.assertEqual(settings.stt_base_url, "http://p1-stt:8080")
        self.assertEqual(settings.tts_base_url, "http://p1-tts:5000")
        self.assertEqual(LocalInferenceSettings("host").stt_base_url, "http://127.0.0.1:18441")
        self.assertEqual(selected_profile({}), "scripted")
        self.assertEqual(
            selected_profile({"P1_CONVERSATION_INFERENCE": "local_real"}), "local_real"
        )
        with self.assertRaises(FrozenInstanceError):
            settings.network = "host"
        for value in [None, True, "remote", "https://private", "LOCAL_REAL"]:
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(LocalInferenceError):
                    LocalInferenceSettings(value)
                with self.assertRaises(LocalInferenceError):
                    selected_profile({"P1_CONVERSATION_INFERENCE": value})

    def test_strict_transcript_rejects_shapes_duplicates_depth_invalid_unicode_and_oversize(self):
        self.assertEqual(
            strict_transcript(b'{"text":"A different real phrase."}', 100),
            "A different real phrase.",
        )
        for raw in [
            b"[]",
            b"null",
            b'{"text":12}',
            b'{"text":"a","extra":"b"}',
            b'{"text":"a","text":"b"}',
            b"\xff",
            b'{"text":"\\ud800"}',
            b'{"text":"\\u0000"}',
            b'{"text":"too long"}',
        ]:
            with self.subTest(raw=raw[:20]):
                with self.assertRaises(LocalInferenceError) as caught:
                    strict_transcript(raw, 4)
                if raw.decode(errors="ignore"):
                    self.assertNotIn(raw.decode(errors="ignore"), str(caught.exception))

    def test_tts_wav_requires_the_selected_pcm_format_useful_samples_and_complete_payload(self):
        pcm = array("h", [1000] * 441).tobytes()
        self.assertEqual(decoded_speech(wav_bytes(pcm, TTS_SAMPLE_RATE)), pcm)
        for raw in [
            b"bad-wave",
            wav_bytes(pcm, 16000),
            wav_bytes(b"\0" * 20, TTS_SAMPLE_RATE),
            wav_bytes(b"", TTS_SAMPLE_RATE),
            wav_bytes(pcm, TTS_SAMPLE_RATE)[:-1],
        ]:
            with self.subTest(size=len(raw)), self.assertRaises(LocalInferenceError):
                decoded_speech(raw)


class HTTPTests(unittest.IsolatedAsyncioTestCase):
    async def http(self, handler, *, timeout=1, limit=20):
        client = LocalModelHTTP(
            "http://p1-stt:8080",
            timeout_seconds=timeout,
            maximum_response_bytes=limit,
            transport=httpx.MockTransport(handler),
        )
        self.addAsyncCleanup(client.aclose)
        return client

    async def test_error_redirect_compression_and_oversize_headers_never_consume_private_body(self):
        for status, headers in [
            (503, {}),
            (302, {"Location": "https://external.invalid"}),
            (200, {"Content-Encoding": "gzip"}),
            (200, {"Content-Length": "99999999"}),
            (200, {"Content-Length": "1,2"}),
        ]:
            with self.subTest(status=status, headers=list(headers)):
                spy = Bytes([SENTINEL.encode()])
                client = await self.http(
                    lambda req, status=status, headers=headers, spy=spy: httpx.Response(
                        status, headers=headers, stream=spy
                    )
                )
                with self.assertRaises(LocalInferenceError) as caught:
                    await client.post("/inference")
                self.assertEqual(spy.reads, 0)
                self.assertEqual(spy.closes, 1)
                self.assertNotIn(SENTINEL, "".join(traceback.format_exception(caught.exception)))
                self.assertFalse(client.client.trust_env)
                self.assertFalse(client.client.follow_redirects)

    async def test_stream_limit_and_closed_or_wrong_route_fail_without_unbounded_reads(self):
        spy = Bytes([b"1" * 10, b"2" * 11, b"must-not-read"])
        client = await self.http(lambda req: httpx.Response(200, stream=spy))
        with self.assertRaises(LocalInferenceError) as caught:
            await client.post("/inference")
        self.assertEqual(caught.exception.code, "response_limit")
        self.assertLessEqual(spy.reads, 3)
        with self.assertRaises(LocalInferenceError):
            await client.post("/synthesize")
        await client.aclose()
        with self.assertRaises(LocalInferenceError) as caught:
            await client.post("/inference")
        self.assertEqual(caught.exception.code, "closed")

    async def test_waiter_cancellation_and_capacity_rejection_leave_useful_slot_progress(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def handle(request):
            entered.set()
            await release.wait()
            return response(b"ok")

        client = await self.http(handle)
        first = asyncio.create_task(client.post("/inference"))
        await entered.wait()
        waiter = asyncio.create_task(client.post("/inference"))
        await asyncio.sleep(0)
        with self.assertRaises(LocalInferenceError) as caught:
            await client.post("/inference")
        self.assertEqual(caught.exception.code, "busy")
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiter
        release.set()
        self.assertEqual(await first, b"ok")
        self.assertEqual(await client.post("/inference"), b"ok")
        self.assertEqual(client._pending, 0)

    async def test_timeout_retrieves_original_call_and_permits_a_later_request(self):
        calls = 0

        async def handle(request):
            nonlocal calls
            calls += 1
            if calls == 1:
                await asyncio.Event().wait()
            return response(b"ok")

        client = await self.http(handle, timeout=0.03)
        with self.assertRaises(LocalInferenceError) as caught:
            await client.post("/inference")
        self.assertEqual(caught.exception.code, "deadline_exceeded")
        self.assertEqual(await client.post("/inference"), b"ok")
        self.assertEqual(calls, 2)

    async def test_close_cancels_and_retrieves_both_owned_request_and_queued_waiter(self):
        entered = asyncio.Event()

        async def handle(request):
            entered.set()
            await asyncio.Event().wait()

        client = await self.http(handle)
        active = asyncio.create_task(client.post("/inference"))
        await entered.wait()
        waiting = asyncio.create_task(client.post("/inference"))
        await asyncio.sleep(0)
        self.assertEqual(len(client._tasks), 2)
        await client.aclose()
        results = await asyncio.gather(active, waiting, return_exceptions=True)
        self.assertTrue(all(isinstance(result, asyncio.CancelledError) for result in results))
        self.assertFalse(client._tasks)
        self.assertEqual(client._pending, 0)
        self.assertTrue(client.client.is_closed)


class SpeechTests(unittest.IsolatedAsyncioTestCase):
    async def test_manual_stt_flush_uses_actual_pcm_and_each_returned_transcript_without_mapping(
        self,
    ):
        phrases = [
            "Please investigate the authorized change.",
            "Do not cancel it; tell me its status.",
        ]
        requests = []

        def handle(request):
            requests.append(request)
            return response(json.dumps({"text": phrases[len(requests) - 1]}).encode())

        model = LocalSTT(LocalInferenceSettings(), transport=httpx.MockTransport(handle))
        self.addAsyncCleanup(model.aclose)
        for expected in phrases:
            async with model.stream(conn_options=OPTIONS) as stream:
                stream.push_frame(frame())
                stream.flush()
                stream.end_input()
                events = [event async for event in stream]
            transcript = next(
                event for event in events if event.type == stt.SpeechEventType.FINAL_TRANSCRIPT
            )
            self.assertEqual(transcript.alternatives[0].text, expected)
        self.assertEqual(model.turns, 2)
        self.assertTrue(model.capabilities.manual_flush)
        self.assertIn(b"RIFF", requests[0].content)
        self.assertIn(b"turn.wav", requests[0].content)
        self.assertNotIn(phrases[0].encode(), requests[0].content)

    async def test_stt_silence_and_audio_bounds_do_not_call_inference_or_fabricate_transcripts(
        self,
    ):
        calls = []
        model = LocalSTT(
            LocalInferenceSettings(), transport=httpx.MockTransport(lambda req: calls.append(req))
        )
        self.addAsyncCleanup(model.aclose)
        event = await model.recognize(frame(level=0), conn_options=OPTIONS)
        self.assertEqual(event.alternatives, [])
        self.assertEqual(calls, [])
        self.assertEqual(model.turns, 0)
        for item in [frame(sample_rate=8000), frame(channels=2), frame(samples=16001)]:
            with self.assertRaises(LocalInferenceError):
                await model.recognize(item, conn_options=OPTIONS)
        with self.assertRaises(LocalInferenceError):
            await model.recognize([frame(samples=16000) for _ in range(13)], conn_options=OPTIONS)
        self.assertEqual(calls, [])

    async def test_generated_tts_uses_arbitrary_bounded_text_and_real_sdk_audio_frames(self):
        texts, pcm = [], array("h", [3000] * 882).tobytes()

        def handle(request):
            texts.append(json.loads(request.content))
            return response(wav_bytes(pcm, TTS_SAMPLE_RATE))

        model = LocalTTS(LocalInferenceSettings(), transport=httpx.MockTransport(handle))
        self.addAsyncCleanup(model.aclose)
        text = "This phrase is absent from every prerecorded speech-bank clip."
        async with model.synthesize(text, conn_options=OPTIONS) as stream:
            frames = [event.frame async for event in stream]
        self.assertEqual(texts, [{"text": text}])
        rendered = b"".join(item.data.tobytes() for item in frames)
        self.assertEqual(rendered[: len(pcm)], pcm)
        self.assertFalse(any(rendered[len(pcm) :]))
        self.assertLessEqual(len(rendered) - len(pcm), TTS_SAMPLE_RATE // 5)
        self.assertTrue(all(item.sample_rate == TTS_SAMPLE_RATE for item in frames))
        self.assertGreater(model.frames_emitted, 0)
        for bad in ["", "x" * 1025, "\ud800"]:
            with self.assertRaises(LocalInferenceError):
                model.synthesize(bad, conn_options=OPTIONS)


class LLMTests(unittest.IsolatedAsyncioTestCase):
    async def model(self, provider=None, **kwargs):
        provider = provider or NativeLLM()
        self.created_kwargs = None

        def factory(**arguments):
            self.created_kwargs = arguments
            return provider

        model = await create_local_llm(LocalInferenceSettings(), plugin_factory=factory, **kwargs)
        self.addAsyncCleanup(model.aclose)
        return model, provider

    async def test_real_provider_text_and_native_no_argument_tool_call_are_preserved(self):
        call = llm.FunctionToolCall(
            name="get_case", arguments="{}", call_id="call-1", extra={"private": SENTINEL}
        )
        source = NativeLLM([chunk("Generated text."), chunk(None, [call])])
        model, _ = await self.model(source)
        async with model.chat(chat_ctx=llm.ChatContext.empty(), conn_options=OPTIONS) as stream:
            chunks = [item async for item in stream]
        self.assertEqual(chunks[0].delta.content, "Generated text.")
        self.assertEqual(chunks[1].delta.tool_calls[0].name, "get_case")
        self.assertIsNone(chunks[1].delta.tool_calls[0].extra)
        self.assertNotIn(SENTINEL, "".join(item.model_dump_json() for item in chunks))
        self.assertEqual(source.calls[0]["parallel_tool_calls"], False)
        self.assertEqual(self.created_kwargs["max_completion_tokens"], MAX_OUTPUT_TOKENS)
        self.assertEqual(self.created_kwargs["extra_body"]["think"], False)
        self.assertEqual(self.created_kwargs["client"].max_retries, 0)

    async def test_tool_authority_payload_injection_and_unknown_tools_are_rejected(self):
        for name, arguments in [
            ("confirm_quote", "{}"),
            ("get_case", '{"scope":"other"}'),
            ("submit_investigation", "[]"),
            ("cancel_case", "{bad"),
            ("get_case", '"' + SENTINEL + '"'),
        ]:
            with self.subTest(name=name), self.assertRaises(LocalInferenceError):
                bounded_chunk(
                    chunk(
                        None,
                        [llm.FunctionToolCall(name=name, arguments=arguments, call_id="call-1")],
                    )
                )
        with self.assertRaises(LocalInferenceError):
            bounded_chunk(
                llm.ChatChunk(
                    id="id",
                    usage=llm.CompletionUsage(
                        completion_tokens=129, prompt_tokens=1, total_tokens=130
                    ),
                )
            )

    async def test_exact_sdk_cache_marker_reaches_provider_without_mutating_the_context(self):
        model, source = await self.model()
        marker = llm.CacheBreakpoint()
        context = llm.ChatContext.empty()
        context.add_message(role="system", content=["Fixed instructions.", marker])
        original = context.to_dict(exclude_metrics=True)
        async with model.chat(chat_ctx=context, conn_options=OPTIONS) as stream:
            chunks = [item async for item in stream]
        self.assertTrue(chunks)
        self.assertEqual(len(source.calls), 1)
        self.assertEqual(context.to_dict(exclude_metrics=True), original)
        self.assertIs(context.items[0].content[1], marker)

    async def test_cache_marker_support_does_not_admit_media_controls_subclasses_or_malformed_markers(
        self,
    ):
        class TextSubclass(str):
            pass

        class MarkerSubclass(llm.CacheBreakpoint):
            pass

        extra = llm.CacheBreakpoint()
        extra.__dict__["private"] = SENTINEL
        cases = (
            llm.ImageContent(image="https://invalid.example/synthetic.png"),
            llm.AudioContent(frame=[frame()]),
            {"type": "cache_breakpoint"},
            object(),
            TextSubclass(SENTINEL),
            MarkerSubclass(),
            llm.CacheBreakpoint.model_construct(type=SENTINEL),
            extra,
        )
        model, source = await self.model()
        for part in cases:
            # Exercise the runtime boundary even if an upstream caller bypasses validation.
            message = llm.ChatMessage.model_construct(role="system", content=[part])
            with (
                self.subTest(kind=type(part).__name__),
                self.assertRaises(LocalInferenceError) as caught,
            ):
                model.chat(chat_ctx=llm.ChatContext([message]))
            self.assertEqual(caught.exception.code, "input_limit")
            self.assertNotIn(SENTINEL, str(caught.exception))
        self.assertEqual(source.calls, [])

    async def test_cache_markers_preserve_context_byte_and_item_limits(self):
        model, source = await self.model()
        for context in (
            llm.ChatContext(
                [
                    llm.ChatMessage(role="system", content=["x", llm.CacheBreakpoint()])
                    for _ in range(65)
                ]
            ),
            llm.ChatContext(
                [
                    llm.ChatMessage(
                        role="system",
                        content=["x" * MAX_MODEL_CONTEXT_BYTES, llm.CacheBreakpoint()],
                    )
                ]
            ),
        ):
            with self.assertRaises(LocalInferenceError) as caught:
                model.chat(chat_ctx=context)
            self.assertEqual(caught.exception.code, "input_limit")
        self.assertEqual(source.calls, [])

    async def test_context_and_output_bounds_prevent_unbounded_generation_and_extra_overrides(self):
        model, source = await self.model(NativeLLM([chunk("x" * (MAX_MODEL_OUTPUT_BYTES + 1))]))
        context = llm.ChatContext.empty()
        context.add_message(role="user", content="x" * (MAX_MODEL_CONTEXT_BYTES + 1))
        with self.assertRaises(LocalInferenceError):
            model.chat(chat_ctx=context)
        with self.assertRaises(LocalInferenceError):
            model.chat(
                chat_ctx=llm.ChatContext.empty(),
                extra_kwargs={"base_url": "https://external.invalid"},
            )
        self.assertEqual(source.calls, [])
        with self.assertRaises(LocalInferenceError):
            async with model.chat(chat_ctx=llm.ChatContext.empty(), conn_options=OPTIONS) as stream:
                _ = [item async for item in stream]

    async def test_total_timeout_cancels_and_retrieves_the_actual_native_provider_stream(self):
        source = NativeLLM(blocked=asyncio.Event())
        model, _ = await self.model(source)
        with (
            patch("services.conversation_agent.inference_llm.LLM_TIMEOUT_SECONDS", 0.03),
            self.assertRaises(LocalInferenceError) as caught,
        ):
            async with model.chat(chat_ctx=llm.ChatContext.empty(), conn_options=OPTIONS) as stream:
                _ = [item async for item in stream]
        self.assertEqual(caught.exception.code, "deadline_exceeded")
        self.assertEqual(source.stream_closes, 1)

    async def test_unknown_provider_exception_is_sanitized_without_its_chain_or_prompt(self):
        model, _ = await self.model(NativeLLM(failure=RuntimeError(SENTINEL)))
        with self.assertRaises(LocalInferenceError) as caught:
            async with model.chat(chat_ctx=llm.ChatContext.empty(), conn_options=OPTIONS) as stream:
                _ = [item async for item in stream]
        self.assertNotIn(SENTINEL, "".join(traceback.format_exception(caught.exception)))

    async def test_actual_sdk_wire_discards_ambient_headers_credentials_and_proxy_settings(self):
        seen = []
        body = b'data: {"id":"id","object":"chat.completion.chunk","created":0,"model":"local","choices":[{"index":0,"delta":{"content":"ok"},"finish_reason":null}]}\n\ndata: [DONE]\n\n'

        def handle(request):
            # Exercise the actual HTTP/1.1 codec requirement that a MockTransport
            # alone omits: removing Host makes the request invalid before I/O.
            h11.Request(
                method=request.method, target=request.url.raw_path, headers=request.headers.raw
            )
            seen.append(request)
            return httpx2.Response(
                200, headers={"Content-Type": "text/event-stream"}, stream=Bytes2([body])
            )

        env = {
            "OPENAI_API_KEY": SENTINEL,
            "OPENAI_ADMIN_KEY": SENTINEL,
            "OPENAI_ORG_ID": SENTINEL,
            "OPENAI_PROJECT_ID": SENTINEL,
            "OPENAI_BASE_URL": "https://external.invalid",
            "OPENAI_CUSTOM_HEADERS": "X-Private: "
            + SENTINEL
            + "\nAuthorization: Bearer "
            + SENTINEL,
            "HTTP_PROXY": "http://external.invalid:1",
            "HTTPS_PROXY": "http://external.invalid:1",
        }
        with patch.dict(os.environ, env):
            model, _ = await self.model(transport=httpx2.MockTransport(handle))
            client = self.created_kwargs["client"]
            stream = await client.chat.completions.create(
                model=LOCAL_LLM_MODEL, messages=[{"role": "user", "content": "test"}], stream=True
            )
            async with stream:
                result = [item async for item in stream]
        self.assertEqual(result[0].choices[0].delta.content, "ok")
        self.assertEqual(str(seen[0].url), "http://p1-llm:11434/v1/chat/completions")
        self.assertEqual(seen[0].headers["Host"], "p1-llm:11434")
        self.assertEqual(seen[0].headers["Authorization"], "Bearer local-only")
        self.assertNotIn(SENTINEL, str(dict(seen[0].headers)))
        await model.aclose()
        self.assertTrue(client.is_closed())

    async def test_llm_wire_rejects_redirect_status_compression_and_large_stream_before_parsing(
        self,
    ):
        for status, headers in [
            (302, {"Location": "https://external.invalid"}),
            (500, {}),
            (200, {"Content-Encoding": "gzip"}),
            (200, {"Content-Length": "65537"}),
        ]:
            with self.subTest(status=status, headers=list(headers)):
                spy = Bytes2([SENTINEL.encode()])
                transport = LocalLLMTransport(
                    "http://p1-llm:11434/v1",
                    httpx2.MockTransport(
                        lambda req, status=status, headers=headers, spy=spy: httpx2.Response(
                            status, headers=headers, stream=spy
                        )
                    ),
                )
                self.addAsyncCleanup(transport.aclose)
                with self.assertRaises(LocalInferenceError):
                    await transport.handle_async_request(
                        httpx2.Request(
                            "POST", "http://p1-llm:11434/v1/chat/completions", content=b"{}"
                        )
                    )
                self.assertEqual(spy.reads, 0)
                self.assertEqual(spy.closes, 1)
        spy = Bytes2([b"x" * 65537])
        transport = LocalLLMTransport(
            "http://p1-llm:11434/v1",
            httpx2.MockTransport(lambda req: httpx2.Response(200, stream=spy)),
        )
        self.addAsyncCleanup(transport.aclose)
        result = await transport.handle_async_request(
            httpx2.Request("POST", "http://p1-llm:11434/v1/chat/completions", content=b"{}")
        )
        with self.assertRaises(LocalInferenceError):
            await result.aread()
        await result.aclose()


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_runtime_keeps_native_tools_scope_readiness_manual_turns_and_owns_models(
        self,
    ):
        source = NativeLLM()
        runtime = await create_local_runtime(
            Port(),
            ConversationBinding("browser-local-test"),
            LocalInferenceSettings(),
            plugin_factory=lambda **kw: source,
        )
        self.assertEqual(runtime.controls.transcript_timeout, 10)
        self.assertEqual(runtime.controls.commit_timeout, 11)
        self.assertEqual(runtime.greeting, LOCAL_GREETING)
        self.assertEqual(runtime.inference_mode, "local_real")
        self.assertEqual(runtime.agent.instructions, LOCAL_INSTRUCTIONS)
        self.assertIsNone(runtime.session.vad)
        self.assertEqual(
            {tool.info.name for tool in runtime.agent.tools},
            {"submit_investigation", "get_case", "cancel_case"},
        )
        self.assertFalse(runtime.controls._ready)
        await runtime.aclose()
        self.assertEqual(source.closes, 1)
        self.assertTrue(runtime.models[0].http.client.is_closed)
        self.assertTrue(runtime.models[1].http.client.is_closed)
        await runtime.aclose()
        self.assertEqual(source.closes, 1)

    async def test_default_control_budgets_and_unavailable_plugin_are_explicit(self):
        class Counter:
            turns = 0

        controls = ConversationControls(
            object(), ConversationBinding("browser-local-test"), Counter()
        )
        self.assertEqual((controls.transcript_timeout, controls.commit_timeout), (2, 3))
        for pair in [(0, 0), (2, 11), (100, 101), (True, 3)]:
            with self.assertRaises(ValueError):
                ConversationControls(
                    object(),
                    ConversationBinding("browser-local-test"),
                    Counter(),
                    transcript_timeout=pair[0],
                    commit_timeout=pair[1],
                )
        with (
            patch(
                "services.conversation_agent.inference_llm.importlib.import_module",
                side_effect=RuntimeError(SENTINEL),
            ),
            self.assertRaises(LocalInferenceError) as caught,
        ):
            await create_local_llm(LocalInferenceSettings())
        self.assertNotIn(SENTINEL, "".join(traceback.format_exception(caught.exception)))

    async def test_model_constructor_failure_closes_client_and_never_reflects_dependency_text(self):
        captured = []

        def failed(**kwargs):
            captured.append(kwargs["client"])
            raise RuntimeError(SENTINEL)

        with self.assertRaises(LocalInferenceError) as caught:
            await create_local_llm(LocalInferenceSettings(), plugin_factory=failed)
        self.assertTrue(captured[0].is_closed())
        self.assertNotIn(SENTINEL, "".join(traceback.format_exception(caught.exception)))

    async def test_runtime_construction_failure_closes_already_created_model(self):
        source = NativeLLM()
        with (
            patch(
                "services.conversation_agent.local_inference.LocalSTT",
                side_effect=RuntimeError(SENTINEL),
            ),
            self.assertRaises(LocalInferenceError) as caught,
        ):
            await create_local_runtime(
                Port(),
                ConversationBinding("browser-local-test"),
                LocalInferenceSettings(),
                plugin_factory=lambda source=source, **kw: source,
            )
        self.assertEqual(source.closes, 1)
        self.assertNotIn(SENTINEL, "".join(traceback.format_exception(caught.exception)))

    async def test_runtime_cleanup_failure_and_cancellation_still_close_all_models(self):
        for error in [RuntimeError(SENTINEL), asyncio.CancelledError(SENTINEL)]:
            with self.subTest(kind=type(error).__name__):
                source = NativeLLM()
                runtime = await create_local_runtime(
                    Port(),
                    ConversationBinding("browser-local-test"),
                    LocalInferenceSettings(),
                    plugin_factory=lambda source=source, **kw: source,
                )
                expected = (
                    asyncio.CancelledError
                    if isinstance(error, asyncio.CancelledError)
                    else LocalInferenceError
                )
                with (
                    patch.object(runtime.session, "aclose", new=AsyncMock(side_effect=error)),
                    self.assertRaises(expected),
                ):
                    await runtime.aclose()
                self.assertTrue(runtime.models[0].http.client.is_closed)
                self.assertTrue(runtime.models[1].http.client.is_closed)
                self.assertEqual(source.closes, 1)
                with self.assertRaises(LocalInferenceError):
                    await runtime.aclose()

    async def test_real_prewarm_selects_only_mode_without_loading_any_fixture_or_model(self):
        from types import SimpleNamespace

        from services.conversation_agent import worker

        process = SimpleNamespace(userdata={})
        with (
            patch.dict(os.environ, {"P1_CONVERSATION_INFERENCE": "local_real"}),
            patch.object(worker.SpeechBank, "load", side_effect=AssertionError("No fixture load")),
        ):
            worker.prewarm(process)
        self.assertEqual(process.userdata, {"inference_mode": "local_real"})

    async def test_provider_sdk_log_namespaces_cannot_render_raw_fields_messages_or_chains(self):
        configure_logging()
        streams = []
        for name in ["openai", "httpx", "httpx2", "httpcore", "httpcore2"]:
            logger = logging.getLogger(name)
            output = io.StringIO()
            previous = logger.handlers[0].stream
            logger.handlers[0].setStream(output)
            try:
                logger.error(
                    SENTINEL,
                    exc_info=(RuntimeError, RuntimeError(SENTINEL), None),
                    extra={"body": SENTINEL},
                )
            finally:
                logger.handlers[0].setStream(previous)
            streams.append(output.getvalue())
        for output in streams:
            self.assertNotIn(SENTINEL, output)
            self.assertEqual(
                set(json.loads(output)), {"service", "timestamp", "severity", "event", "code"}
            )


if __name__ == "__main__":
    unittest.main()
