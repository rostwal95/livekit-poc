"""Pinned Deepgram wire decoding and actual manual flush; synthetic HTTPS only."""

import asyncio
import io
import json
import traceback
import unittest
import wave
from importlib.metadata import version
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from livekit import rtc
from livekit.agents import stt
from livekit.agents.language import LanguageCode
from livekit.plugins.deepgram import STT

from services.conversation_agent.provider_http import BoundedJSONResponse
from services.conversation_agent.provider_settings import DEEPGRAM_URL, ProviderInferenceError
from services.conversation_agent.provider_speech import OPTIONS, ProviderSTT

PRIVATE = "SYNTHETIC-DEEPGRAM-PRIVATE-SENTINEL"
KEY = "synthetic-test-key"
PCM = b"\x10\x27" * 960


def response_payload(text="Inspect my current case."):
    return json.dumps(
        {
            "metadata": {"request_id": "synthetic-deepgram-request"},
            "results": {
                "channels": [
                    {
                        "alternatives": [
                            {
                                "transcript": text,
                                "confidence": 0.99,
                                "words": [
                                    {
                                        "word": "inspect",
                                        "punctuated_word": "Inspect",
                                        "start": 0.0,
                                        "end": 0.06,
                                        "confidence": 0.99,
                                    }
                                ],
                            }
                        ]
                    }
                ]
            },
        }
    ).encode()


class SyntheticContent:
    def __init__(self, payload):
        self.payload = payload
        self.bytes_read = 0
        self.chunks_read = 0

    async def iter_chunked(self, size):
        for offset in range(0, len(self.payload), size):
            chunk = self.payload[offset : offset + size]
            self.bytes_read += len(chunk)
            self.chunks_read += 1
            yield chunk


class SyntheticResponse(BoundedJSONResponse):
    """Use the real owned bounded decoder, with no real socket or aiohttp session."""

    def __init__(self, status, payload, content_type="application/json"):
        self.status = status
        self.content = SyntheticContent(payload)
        self.media_type = content_type
        self.did_close = False
        self._bounded_cache = None

    @property
    def content_type(self):
        return self.media_type

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        self.close()

    def close(self):
        self.did_close = True


class SyntheticSession:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.closed = False

    def post(self, **arguments):
        self.calls.append(arguments)
        return self.response

    async def close(self):
        self.closed = True


def sdk(session):
    return STT(
        model="nova-3",
        language="en",
        sample_rate=16000,
        endpointing_ms=0,
        mip_opt_out=True,
        api_key=KEY,
        base_url=DEEPGRAM_URL,
        http_session=session,
    )


def frame():
    return rtc.AudioFrame(PCM, 16000, 1, len(PCM) // 2)


class DeepgramSDKCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # An accidental fallback can never turn this offline contract into a call.
        blocker = patch(
            "aiohttp.ClientSession._request", side_effect=AssertionError("Network forbidden")
        )
        blocker.start()
        self.addCleanup(blocker.stop)

    def assert_wire(self, session):
        self.assertEqual(len(session.calls), 1)
        request = session.calls[0]
        url = urlsplit(request["url"])
        self.assertEqual(
            (url.scheme, url.netloc, url.path), ("https", "api.deepgram.com", "/v1/listen")
        )
        self.assertIsNone(url.username)
        self.assertIsNone(url.password)
        query = parse_qs(url.query)
        self.assertEqual(query["model"], ["nova-3"])
        self.assertEqual(query["language"], ["en"])
        self.assertEqual(query["mip_opt_out"], ["true"])
        self.assertEqual(
            request["headers"],
            {
                "Authorization": "Token " + KEY,
                "Accept": "application/json",
                "Content-Type": "audio/wav",
            },
        )
        self.assertEqual(request["timeout"].sock_connect, OPTIONS.timeout)
        with wave.open(io.BytesIO(request["data"]), "rb") as audio:
            self.assertEqual(
                (
                    audio.getframerate(),
                    audio.getnchannels(),
                    audio.getsampwidth(),
                    audio.getcomptype(),
                ),
                (16000, 1, 2, "NONE"),
            )
            self.assertEqual(audio.getnframes(), 960)
            self.assertEqual(audio.readframes(audio.getnframes()), PCM)

    async def test_actual_pinned_sdk_decodes_wire_final_and_emits_real_numeric_usage(self):
        self.assertEqual(version("livekit-plugins-deepgram"), "1.8.11")
        response = SyntheticResponse(200, response_payload())
        session = SyntheticSession(response)
        recognizer = sdk(session)
        metrics = []
        recognizer.on("metrics_collected", metrics.append)
        try:
            event = await recognizer.recognize(
                frame(), language=LanguageCode("en"), conn_options=OPTIONS
            )
            self.assertEqual(event.type, stt.SpeechEventType.FINAL_TRANSCRIPT)
            self.assertEqual(event.request_id, "synthetic-deepgram-request")
            self.assertEqual(event.alternatives[0].text, "Inspect my current case.")
            self.assertEqual(event.alternatives[0].language, "en")
            self.assertEqual(event.alternatives[0].end_time, 0.06)
            self.assertEqual(len(metrics), 1)
            self.assertAlmostEqual(metrics[0].audio_duration, 0.06)
            self.assertGreater(metrics[0].duration, 0)
            self.assertFalse(metrics[0].streamed)
            self.assertEqual(metrics[0].metadata.model_name, "nova-3")
            self.assertEqual(metrics[0].metadata.model_provider, "Deepgram")
            self.assert_wire(session)
            self.assertTrue(response.did_close)
            self.assertEqual(response.content.bytes_read, len(response_payload()))
        finally:
            await recognizer.aclose()
            await session.close()
        self.assertTrue(session.closed)

    async def test_actual_sdk_manual_flush_retains_final_and_pcm_usage_without_interim_or_retry(
        self,
    ):
        response = SyntheticResponse(200, response_payload())
        session = SyntheticSession(response)
        adapter = ProviderSTT(sdk(session), session)
        metrics = []
        adapter.on("metrics_collected", metrics.append)
        stream = adapter.stream(conn_options=OPTIONS)
        try:
            stream.push_frame(frame())
            await asyncio.sleep(0)
            self.assertEqual(session.calls, [])
            stream.flush()
            stream.end_input()  # Its final empty flush must not submit a second ASR request.
            async with asyncio.timeout(2):
                events = [event async for event in stream]
            self.assertEqual(
                [event.type for event in events],
                [
                    stt.SpeechEventType.START_OF_SPEECH,
                    stt.SpeechEventType.FINAL_TRANSCRIPT,
                    stt.SpeechEventType.RECOGNITION_USAGE,
                    stt.SpeechEventType.END_OF_SPEECH,
                ],
            )
            self.assertEqual(events[1].alternatives[0].text, "Inspect my current case.")
            self.assertEqual(events[1].alternatives[0].end_time, 0.06)
            self.assertTrue(events[1].request_id.startswith("provider-stt-"))
            self.assertAlmostEqual(events[2].recognition_usage.audio_duration, 0.06)
            self.assertEqual(adapter.turns, 1)
            self.assertAlmostEqual(adapter.audio_seconds, 0.06)
            self.assertEqual(adapter.pool.pending, 0)
            self.assertEqual(len(metrics), 1)
            self.assertAlmostEqual(metrics[0].audio_duration, 0.06)
            self.assertTrue(metrics[0].streamed)
            self.assert_wire(session)
        finally:
            await stream.aclose()
            await adapter.aclose()
        self.assertFalse(adapter.streams)
        self.assertTrue(session.closed)

    async def test_actual_sdk_auth_failures_never_read_error_body_or_retry(self):
        for status in (401, 403, 429, 500):
            with self.subTest(status=status):
                response = SyntheticResponse(status, PRIVATE.encode())
                session = SyntheticSession(response)
                adapter = ProviderSTT(sdk(session), session)
                try:
                    with self.assertRaises(ProviderInferenceError) as caught:
                        await adapter.recognize(frame(), conn_options=OPTIONS)
                    self.assertEqual(caught.exception.code, "dependency_unavailable")
                    self.assertNotIn(PRIVATE, "".join(traceback.format_exception(caught.exception)))
                    self.assertEqual(response.content.bytes_read, 0)
                    self.assertTrue(response.did_close)
                    self.assertEqual(adapter.turns, 0)
                    self.assertEqual(adapter.pool.pending, 0)
                    self.assert_wire(session)
                finally:
                    await adapter.aclose()
                self.assertTrue(session.closed)

    async def test_actual_sdk_invalid_json_and_schema_are_bounded_content_free_failures(self):
        for payload, content_type in (
            (PRIVATE.encode(), "application/json"),
            (b"\xff", "application/json"),
            (b"{}", "application/json"),
            (response_payload(), "text/plain"),
        ):
            with self.subTest(content_type=content_type, bytes=len(payload)):
                response = SyntheticResponse(200, payload, content_type)
                session = SyntheticSession(response)
                adapter = ProviderSTT(sdk(session), session)
                try:
                    with self.assertRaises(ProviderInferenceError) as caught:
                        await adapter.recognize(frame(), conn_options=OPTIONS)
                    self.assertEqual(caught.exception.code, "dependency_unavailable")
                    self.assertNotIn(PRIVATE, "".join(traceback.format_exception(caught.exception)))
                    self.assertLessEqual(response.content.bytes_read, 16384)
                    if content_type != "application/json":
                        self.assertEqual(response.content.bytes_read, 0)
                    self.assertEqual(len(session.calls), 1)
                    self.assertEqual(adapter.turns, 0)
                finally:
                    await adapter.aclose()
                self.assertTrue(session.closed)

    async def test_actual_sdk_oversize_stops_at_one_excess_chunk_without_consuming_private_tail(
        self,
    ):
        payload = b" " * 16384 + b"x" * 4096 + PRIVATE.encode()
        response = SyntheticResponse(200, payload)
        session = SyntheticSession(response)
        adapter = ProviderSTT(sdk(session), session)
        try:
            with self.assertRaises(ProviderInferenceError) as caught:
                await adapter.recognize(frame(), conn_options=OPTIONS)
            self.assertEqual(caught.exception.code, "dependency_unavailable")
            self.assertNotIn(PRIVATE, "".join(traceback.format_exception(caught.exception)))
            self.assertEqual(response.content.bytes_read, 20480)
            self.assertLess(response.content.bytes_read, len(payload))
            self.assertTrue(response.did_close)
            self.assertEqual(len(session.calls), 1)
            self.assertEqual(adapter.turns, 0)
            self.assertEqual(adapter.pool.pending, 0)
        finally:
            await adapter.aclose()
        self.assertTrue(session.closed)

    async def test_actual_sdk_blank_recognition_does_not_invent_transcript_or_useful_turn(self):
        response = SyntheticResponse(200, response_payload(""))
        session = SyntheticSession(response)
        adapter = ProviderSTT(sdk(session), session)
        try:
            event = await adapter.recognize(frame(), conn_options=OPTIONS)
            self.assertEqual(event.type, stt.SpeechEventType.FINAL_TRANSCRIPT)
            self.assertEqual(event.alternatives, [])
            self.assertEqual(adapter.turns, 0)
            self.assertEqual(len(session.calls), 1)
        finally:
            await adapter.aclose()
        self.assertTrue(session.closed)
