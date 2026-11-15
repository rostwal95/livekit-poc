"""Genuine SDK extension/PCM controls; no room, providers, database or media server."""

from __future__ import annotations

import asyncio
import gc
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import warnings
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from livekit import rtc
from livekit.agents import Agent, AgentSession, llm, stt, tts
from livekit.agents.voice.io import AudioInput

from channel_continuity.native_models import CommittedTranscript, NativeRecognizer
from services.channel_policy_demo import native_models as m

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = "PRIVATE_NATIVE_MODEL_SENTINEL"


def frame(pcm, *, rate=16000, channels=1, samples=None):
    return rtc.AudioFrame(
        pcm, rate, channels, len(pcm) // 2 // channels if samples is None else samples
    )


def feed(stream, pcm):
    for offset in range(0, len(pcm), 640):
        stream.push_frame(frame(pcm[offset : offset + 640]))


async def through_end(stream):
    events = []
    async with asyncio.timeout(2):
        async for event in stream:
            events.append(event)
            if event.type is stt.SpeechEventType.END_OF_SPEECH:
                return events
    raise AssertionError("expected finite final event")


class ConfigurationTests(unittest.TestCase):
    def test_closed_finite_fixture_configuration_and_positive(self):
        bad = [
            {"input_fixtures": ()},
            {"input_fixtures": ["input-investigate.wav"]},
            {"input_fixtures": ("../private.wav",)},
            {"input_fixtures": ("demo.wav",)},
            {"input_fixtures": ("input-investigate.wav",) * 33},
            {"reply_fixture": "input-investigate.wav"},
            {"reply_fixture": PRIVATE},
            {"cleanup_timeout_s": True},
            {"cleanup_timeout_s": 0},
            {"cleanup_timeout_s": -1},
            {"cleanup_timeout_s": float("nan")},
            {"cleanup_timeout_s": float("inf")},
            {"cleanup_timeout_s": 10**1000},
        ]
        for parameters in bad:
            with (
                self.subTest(fields=tuple(parameters)),
                self.assertRaises(m.NativeModelError) as error,
            ):
                m.ScriptedModelProfile(**parameters)
            self.assertEqual(error.exception.code, "invalid_configuration")
            self.assertNotIn(PRIVATE, str(error.exception))
        value = m.ScriptedModelProfile(("input-status.wav",), "status.wav", 1)
        self.assertEqual(value.input_fixtures, ("input-status.wav",))
        with self.assertRaises(FrozenInstanceError):
            value.reply_fixture = "demo.wav"

    def test_public_import_is_cold_and_does_not_import_other_service(self):
        code = r"""import asyncio, builtins, importlib.abc, json, pathlib, socket, sys, threading
class Deny(importlib.abc.MetaPathFinder):
 def find_spec(self, fullname, path=None, target=None):
  if fullname.startswith(('livekit', 'channel_continuity', 'services.conversation_agent')):
   raise AssertionError('SDK or service import before explicit loader')
sys.meta_path.insert(0,Deny())
def denied(*args,**kwargs): raise AssertionError('import-time side effect')
builtins.open=denied
pathlib.Path.read_bytes=denied
asyncio.create_task=denied
threading.Thread.start=denied
socket.socket=denied
from services.channel_policy_demo import native_models
assert native_models.ScriptedModelProfile().reply_fixture=='checking.wav'
assert not any(x.startswith(('livekit','channel_continuity','services.conversation_agent')) for x in sys.modules)
print(json.dumps({'cold':True}))
"""
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", code],
            cwd="/private/tmp",
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"cold": True})

    def test_pinned_asset_loader_and_provenance(self):
        assets = m._load_assets()
        self.assertEqual(len(assets), 10)
        self.assertEqual(len({item.fixture for item in assets}), 10)
        original = ROOT / "services/conversation_agent/assets/manifest.json"
        self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), m.MANIFEST_SHA256)
        provenance = json.loads(original.read_bytes())
        self.assertEqual(provenance["kind"], "synthetic-spoken-fixtures")
        self.assertIn("do not demonstrate speech recognition", provenance["purpose"])
        for item in assets:
            self.assertEqual((item.sample_rate, item.channels, item.sample_width), (16000, 1, 2))
            self.assertLessEqual(len(item.pcm), 384000)

    def test_changed_or_oversize_assets_are_finite_and_no_decoder_leak(self):
        for returned in (b"{}", b"x" * 16385):
            with (
                self.subTest(length=len(returned)),
                patch.object(m, "_read", return_value=returned),
                self.assertRaises(m.NativeModelError) as error,
            ):
                m._load_assets()
            self.assertEqual(str(error.exception), "invalid_configuration")
        with (
            patch.object(m, "_read", side_effect=OSError(PRIVATE)),
            self.assertRaises(m.NativeModelError) as error,
        ):
            m._load_assets()
        self.assertNotIn(PRIVATE, str(error.exception))
        self.assertEqual(len(m._load_assets()), 10)

    def test_default_reply_fits_the_native_prepare_budget_with_headroom(self):
        # P2 prepare generates and plays the dispatched reply within 4 seconds;
        # a reply near that length made durable dispatch nondeterministic.
        default = m.ScriptedModelProfile().reply_fixture
        self.assertEqual(default, m.DEFAULT_REPLY_FIXTURE)
        audio = next(item for item in m._load_assets() if item.fixture == default)
        self.assertLessEqual(len(audio.pcm) // 2, m.MAX_DEFAULT_REPLY_SAMPLES)
        self.assertLessEqual(m.MAX_DEFAULT_REPLY_SAMPLES / m.SAMPLE_RATE, 4 / 2)

    def test_audio_values_reject_mutable_and_forged_metadata(self):
        audio = m._load_assets()[0]
        for fields in (
            {"pcm": bytearray(audio.pcm)},
            {"pcm": b""},
            {"wav_sha256": "0" * 64},
            {"sample_rate": 8000},
            {"channels": True},
            {"fixture": PRIVATE},
        ):
            with self.subTest(fields=tuple(fields)), self.assertRaises(m.NativeModelError):
                replace(audio, **fields)
        self.assertEqual(type(audio.pcm), bytes)

    def test_asset_reader_denies_oversize_and_symlinks_then_allows_installed_hardlink(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "declared"
            alias = Path(directory) / "alias"
            file.write_bytes(b"bounded")
            alias.symlink_to(file)
            for path, bound in ((file, 2), (alias, 64)):
                with self.subTest(path=path.name), self.assertRaises(m.NativeModelError):
                    m._read(path, bound)
            self.assertEqual(m._read(file, 7), b"bounded")
            installed = Path(directory) / "installed"
            os.link(file, installed)
            self.assertEqual(m._read(installed, 7), b"bounded")


class NativeModelsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bundle = await m.load_scripted_models()
        self.addAsyncCleanup(self.bundle.aclose)

    async def test_bundle_uses_genuine_sdk_classes_and_public_recognizer_protocol(self):
        self.assertIsInstance(self.bundle.stt, stt.STT)
        self.assertIsInstance(self.bundle.llm, llm.LLM)
        self.assertIsInstance(self.bundle.tts, tts.TTS)
        recognizer: NativeRecognizer = self.bundle.recognizer
        self.assertIs(recognizer, self.bundle.stt)
        self.assertEqual(self.bundle.inference_mode, "scripted")
        self.assertEqual(self.bundle.pending_count, 0)
        self.assertFalse(self.bundle.stt.capabilities.offline_recognize)
        self.assertEqual(self.bundle.stt.provider, "local-scripted")
        self.assertEqual(self.bundle.tts.sample_rate, 16000)
        self.assertEqual(self.bundle.tts.num_channels, 1)

    async def test_declared_wav_pcm_creates_exact_final_snapshot(self):
        input_id = str(uuid4())
        self.bundle.recognizer.begin_turn(input_id)
        stream = self.bundle.stt.stream()
        self.addAsyncCleanup(stream.aclose)
        pcm = self.bundle.input_audio("input-investigate.wav").pcm
        feed(stream, pcm)
        self.assertEqual(self.bundle.recognizer.pending_work(), 1)
        stream.end_input()
        events = [event async for event in stream]
        final = next(
            event for event in events if event.type is stt.SpeechEventType.FINAL_TRANSCRIPT
        )
        snapshot = self.bundle.recognizer.final_snapshot(input_id)
        self.assertIs(type(snapshot), CommittedTranscript)
        self.assertEqual(snapshot, CommittedTranscript(input_id, "investigate", final.request_id))
        self.assertEqual(final.alternatives[0].text, snapshot.body)
        self.assertEqual(self.bundle.recognizer.pending_work(), 0)
        self.bundle.recognizer.end_turn(input_id)
        await stream.aclose()
        self.assertEqual(self.bundle.pending_count, 0)
        self.assertEqual(self.bundle.metrics()["audio_samples"], len(pcm) // 2)

    async def test_one_stream_supports_declared_followup_turn_and_no_reassociation(self):
        stream = self.bundle.stt.stream()
        self.addAsyncCleanup(stream.aclose)
        first, second = str(uuid4()), str(uuid4())
        self.bundle.recognizer.begin_turn(first)
        feed(stream, self.bundle.input_audio("input-investigate.wav").pcm)
        self.bundle.recognizer.end_turn(first)  # before the queued recognition coroutine runs
        with self.assertRaises(m.NativeModelError) as error:
            self.bundle.recognizer.begin_turn(second)
        self.assertEqual(error.exception.code, "capacity_exhausted")
        stream.flush()
        old = await through_end(stream)
        self.assertEqual(
            next(e for e in old if e.type is stt.SpeechEventType.FINAL_TRANSCRIPT)
            .alternatives[0]
            .text,
            "",
        )
        self.assertIsNone(self.bundle.recognizer.final_snapshot(first))
        self.bundle.recognizer.begin_turn(second)
        feed(stream, self.bundle.input_audio("input-status.wav").pcm)
        stream.flush()
        new = await through_end(stream)
        final = next(e for e in new if e.type is stt.SpeechEventType.FINAL_TRANSCRIPT)
        self.assertEqual(
            self.bundle.recognizer.final_snapshot(second),
            CommittedTranscript(second, "status", final.request_id),
        )
        self.assertIsNone(self.bundle.recognizer.final_snapshot(first))
        self.bundle.recognizer.end_turn(second)

    async def test_silence_has_no_committed_transcript_and_next_turn_progresses(self):
        stream = self.bundle.stt.stream()
        self.addAsyncCleanup(stream.aclose)
        first = str(uuid4())
        self.bundle.recognizer.begin_turn(first)
        stream.push_frame(frame(bytes(3200)))
        stream.flush()
        events = await through_end(stream)
        final = next(e for e in events if e.type is stt.SpeechEventType.FINAL_TRANSCRIPT)
        self.assertEqual(final.alternatives[0].text, "")
        self.assertIsNone(self.bundle.recognizer.final_snapshot(first))
        self.bundle.recognizer.end_turn(first)
        second = str(uuid4())
        self.bundle.recognizer.begin_turn(second)
        feed(stream, self.bundle.input_audio("input-status.wav").pcm)
        stream.flush()
        await through_end(stream)
        self.assertEqual(self.bundle.recognizer.final_snapshot(second).body, "status")
        self.bundle.recognizer.end_turn(second)

    async def test_wrong_audio_formats_reject_before_queue_and_valid_pcm_progresses(self):
        stream = self.bundle.stt.stream()
        self.addAsyncCleanup(stream.aclose)
        input_id = str(uuid4())
        self.bundle.recognizer.begin_turn(input_id)
        invalid = [
            frame(bytes(640), rate=8000),
            frame(bytes(1280), channels=2),
            frame(b""),
            frame(bytes(32002)),
            frame(bytes(642), samples=320),
        ]
        for item in invalid:
            with (
                self.subTest(rate=item.sample_rate, channels=item.num_channels),
                self.assertRaises(m.NativeModelError) as error,
            ):
                stream.push_frame(item)
            self.assertEqual(error.exception.code, "invalid_audio")
            self.assertEqual(self.bundle.recognizer.pending_work(), 0)
        feed(stream, self.bundle.input_audio("input-investigate.wav").pcm)
        stream.flush()
        await through_end(stream)
        self.assertEqual(self.bundle.recognizer.final_snapshot(input_id).body, "investigate")

    async def test_audio_turn_byte_and_frame_queue_caps_retain_actual_owner(self):
        input_id = str(uuid4())
        self.bundle.recognizer.begin_turn(input_id)
        stream = self.bundle.stt.stream()
        self.addAsyncCleanup(stream.aclose)
        sample = b"\x01\x01" * 16000
        for _ in range(12):
            stream.push_frame(frame(sample))
        with self.assertRaises(m.NativeModelError) as error:
            stream.push_frame(frame(sample))
        self.assertEqual(error.exception.code, "capacity_exhausted")
        self.assertEqual(self.bundle.metrics()["audio_samples"], 192000)
        self.assertEqual(self.bundle.pending_count, 1)
        await stream.aclose()
        self.assertEqual(self.bundle.recognizer.pending_work(), 0)
        self.assertEqual(self.bundle.pending_count, 0)

    async def test_tiny_frame_count_bounds_sdk_queue(self):
        self.bundle.recognizer.begin_turn(str(uuid4()))
        stream = self.bundle.stt.stream()
        self.addAsyncCleanup(stream.aclose)
        for _ in range(1024):
            stream.push_frame(frame(b"\x64\x00"))
        with self.assertRaises(m.NativeModelError):
            stream.push_frame(frame(b"\x64\x00"))
        self.assertEqual(self.bundle.metrics()["audio_frames"], 1024)
        self.assertEqual(self.bundle.pending_count, 1)
        await stream.aclose()
        self.assertEqual(self.bundle.pending_count, 0)

    async def test_replayed_turn_unknown_fixture_and_no_current_turn_are_denied(self):
        stream = self.bundle.stt.stream()
        self.addAsyncCleanup(stream.aclose)
        with self.assertRaises(m.NativeModelError):
            stream.push_frame(frame(bytes(640)))
        for bad in (PRIVATE, str(uuid4()).upper(), True):
            with self.subTest(kind=type(bad).__name__), self.assertRaises(m.NativeModelError):
                self.bundle.recognizer.begin_turn(bad)
        input_id = str(uuid4())
        self.bundle.recognizer.begin_turn(input_id)
        self.bundle.recognizer.end_turn(input_id)
        with self.assertRaises(m.NativeModelError):
            self.bundle.recognizer.begin_turn(input_id)
        with self.assertRaises(m.NativeModelError):
            self.bundle.input_audio("undeclared.wav")
        next_id = str(uuid4())
        self.bundle.recognizer.begin_turn(next_id)
        feed(stream, self.bundle.input_audio("input-status.wav").pcm)
        stream.flush()
        await through_end(stream)
        self.assertEqual(self.bundle.recognizer.final_snapshot(next_id).body, "status")

    async def test_pcm_is_copied_before_caller_mutation(self):
        input_id = str(uuid4())
        self.bundle.recognizer.begin_turn(input_id)
        stream = self.bundle.stt.stream()
        self.addAsyncCleanup(stream.aclose)
        caller = bytearray(b"\x00\x04" * 3200)
        stream.push_frame(frame(caller))
        caller[:] = bytes(len(caller))
        stream.flush()
        await through_end(stream)
        self.assertEqual(self.bundle.recognizer.final_snapshot(input_id).body, "investigate")

    async def test_scripted_model_emits_declared_text_without_tools_or_fabricated_usage(self):
        context = llm.ChatContext()
        context.add_message(role="user", content="Investigate this booking")
        stream = self.bundle.llm.chat(chat_ctx=context, tool_choice="none")
        self.addAsyncCleanup(stream.aclose)
        chunks = [chunk async for chunk in stream]
        self.assertEqual(
            "".join(chunk.delta.content or "" for chunk in chunks if chunk.delta),
            "Checking the policy.",
        )
        self.assertTrue(
            all(
                chunk.usage is None and not (chunk.delta and chunk.delta.tool_calls)
                for chunk in chunks
            )
        )
        await stream.aclose()
        self.assertEqual(self.bundle.pending_count, 0)

    async def test_llm_capacity_includes_finished_unclosed_streams(self):
        context = llm.ChatContext()
        first = self.bundle.llm.chat(chat_ctx=context)
        second = self.bundle.llm.chat(chat_ctx=context)
        self.addAsyncCleanup(first.aclose)
        self.addAsyncCleanup(second.aclose)
        await asyncio.gather(consume(first), consume(second))
        with self.assertRaises(m.NativeModelError) as error:
            self.bundle.llm.chat(chat_ctx=context)
        self.assertEqual(error.exception.code, "capacity_exhausted")
        self.assertEqual(self.bundle.pending_count, 2)
        await first.aclose()
        third = self.bundle.llm.chat(chat_ctx=context)
        self.addAsyncCleanup(third.aclose)
        await consume(third)
        await third.aclose()
        await second.aclose()
        self.assertEqual(self.bundle.pending_count, 0)

    async def test_tts_outputs_genuine_pcm_matching_declared_asset(self):
        text = "This is a scripted local voice demonstration."
        stream = self.bundle.tts.synthesize(text)
        self.addAsyncCleanup(stream.aclose)
        audio = [item async for item in stream]
        self.assertGreater(len(audio), 0)
        self.assertTrue(all(type(item.frame) is rtc.AudioFrame for item in audio))
        self.assertTrue(
            all(item.frame.sample_rate == 16000 and item.frame.num_channels == 1 for item in audio)
        )
        expected = next(item.pcm for item in m._load_assets() if item.fixture == "demo.wav")
        self.assertEqual(b"".join(bytes(item.frame.data) for item in audio), expected)
        await stream.aclose()
        self.assertEqual(self.bundle.pending_count, 0)
        self.assertGreater(self.bundle.metrics()["speech_frames"], 0)

    async def test_undeclared_tts_text_is_finite_and_does_not_consume_slot(self):
        for text in (PRIVATE, "x" * 2049, b"unknown", "\ud800"):
            with (
                self.subTest(kind=type(text).__name__),
                self.assertRaises(m.NativeModelError) as error,
            ):
                self.bundle.tts.synthesize(text)
            self.assertNotIn(PRIVATE, str(error.exception))
        self.assertEqual(self.bundle.pending_count, 0)
        valid = self.bundle.tts.synthesize("The workflow panel shows the latest durable state.")
        self.addAsyncCleanup(valid.aclose)
        await consume(valid)
        await valid.aclose()
        self.assertEqual(self.bundle.pending_count, 0)

    async def test_finished_audio_input_rejects_new_frames_with_finite_closed_code(self):
        stream = self.bundle.stt.stream()
        self.bundle.recognizer.begin_turn(str(uuid4()))
        feed(stream, self.bundle.input_audio("input-investigate.wav").pcm)
        stream.end_input()
        await consume(stream)
        for action in (lambda: stream.push_frame(frame(bytes(640))), stream.flush):
            with self.assertRaises(m.NativeModelError) as error:
                action()
            self.assertEqual(str(error.exception), "closed")
        await stream.aclose()
        self.assertEqual(self.bundle.pending_count, 0)

    async def test_sdk_clear_user_turn_replacement_commits_first_voice_turn(self):
        class QueueInput(AudioInput):
            def __init__(self):
                super().__init__(label="scripted-reset-fixture")
                self.frames: asyncio.Queue[rtc.AudioFrame] = asyncio.Queue()

            async def __anext__(self):
                return await self.frames.get()

        turns: tuple[tuple[m.InputFixture, str], ...] = (
            ("input-investigate.wav", "investigate"),
            ("input-status.wav", "status"),
        )
        audio = QueueInput()
        session: AgentSession[None] = AgentSession(
            stt=self.bundle.stt,
            vad=None,
            turn_handling={"turn_detection": "manual", "preemptive_generation": {"enabled": False}},
        )
        session.input.audio = audio
        await session.start(
            Agent(instructions="Offline scripted manual turn fixture."),
            record=False,
            session_host=False,
        )
        session.input.set_audio_enabled(False)
        try:
            async with asyncio.timeout(2):
                while not self.bundle.metrics()["stt_streams"]:
                    await asyncio.sleep(0.001)
            for fixture, expected in turns:
                input_id = str(uuid4())
                self.bundle.recognizer.begin_turn(input_id)
                session.clear_user_turn()
                session.input.set_audio_enabled(True)
                pcm = self.bundle.input_audio(fixture).pcm
                for offset in range(0, len(pcm), 640):
                    audio.frames.put_nowait(frame(pcm[offset : offset + 640]))
                async with asyncio.timeout(2):
                    while not audio.frames.empty():
                        await asyncio.sleep(0.001)
                session.input.set_audio_enabled(False)
                transcript = await session.commit_user_turn(
                    transcript_timeout=1, stt_flush_duration=0.1, skip_reply=True
                )
                self.assertEqual(transcript, expected)
                snapshot = self.bundle.recognizer.final_snapshot(input_id)
                assert snapshot is not None
                self.assertEqual((snapshot.input_id, snapshot.body), (input_id, expected))
                self.assertEqual(self.bundle.metrics()["stt_streams"], 1)
                self.bundle.recognizer.end_turn(input_id)
        finally:
            await session.aclose()
        self.assertEqual(self.bundle.pending_count, 0)
        first, second = self.bundle.stt.stream(), self.bundle.stt.stream()
        self.addAsyncCleanup(first.aclose)
        self.addAsyncCleanup(second.aclose)
        with self.assertRaises(m.NativeModelError) as error:
            self.bundle.stt.stream()
        self.assertEqual(error.exception.code, "capacity_exhausted")
        await first.aclose()
        third = self.bundle.stt.stream()
        self.addAsyncCleanup(third.aclose)
        self.assertEqual(self.bundle.pending_count, 2)
        await second.aclose()
        await third.aclose()
        self.assertEqual(self.bundle.pending_count, 0)

    async def test_close_timeout_retains_actual_stream_and_closes_independent_models(self):
        bundle = await m.load_scripted_models(m.ScriptedModelProfile(cleanup_timeout_s=0.02))
        self.addAsyncCleanup(bundle.aclose)
        recognition = bundle.stt.stream()
        reply = bundle.llm.chat(chat_ctx=llm.ChatContext())
        speech = bundle.tts.synthesize("This is a scripted local voice demonstration.")
        entered, release = asyncio.Event(), asyncio.Event()
        original = stt.RecognizeStream.aclose

        async def held_close(stream):
            if stream is recognition:
                entered.set()
                await release.wait()
            await original(stream)

        with patch.object(stt.RecognizeStream, "aclose", held_close):
            try:
                with self.assertRaises(m.NativeModelError) as error:
                    await bundle.aclose()
                self.assertEqual(error.exception.code, "cleanup_incomplete")
                self.assertTrue(entered.is_set())
                self.assertEqual(bundle.pending_count, 1)
                self.assertEqual(bundle.metrics()["llm_streams"], 0)
                self.assertEqual(bundle.metrics()["tts_streams"], 0)
                with self.assertRaises(m.NativeModelError) as closed:
                    bundle.stt.stream()
                self.assertEqual(closed.exception.code, "closed")
            finally:
                release.set()
            await bundle.aclose()
        self.assertEqual(bundle.pending_count, 0)
        self.assertEqual(bundle.metrics()["closed"], 1)
        await reply.aclose()
        await speech.aclose()

    async def test_cancelled_close_waiter_does_not_cancel_actual_stream_cleanup(self):
        recognition = self.bundle.stt.stream()
        entered, release = asyncio.Event(), asyncio.Event()
        original = stt.RecognizeStream.aclose

        async def held_close(stream):
            entered.set()
            await release.wait()
            await original(stream)

        with patch.object(stt.RecognizeStream, "aclose", held_close):
            waiter = asyncio.create_task(self.bundle.aclose())
            await entered.wait()
            waiter.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await waiter
            self.assertEqual(self.bundle.pending_count, 1)
            self.assertFalse(release.is_set())
            release.set()
            await self.bundle.aclose()
        await recognition.aclose()
        self.assertEqual(self.bundle.pending_count, 0)

    async def test_failed_close_copies_finite_error_and_retries_actual_owner(self):
        recognition = self.bundle.stt.stream()
        original = stt.RecognizeStream.aclose
        calls = 0

        async def failed_once(stream):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError(PRIVATE)
            await original(stream)

        with patch.object(stt.RecognizeStream, "aclose", failed_once):
            with self.assertRaises(m.NativeModelError) as error:
                await self.bundle.aclose()
            self.assertEqual(str(error.exception), "cleanup_incomplete")
            self.assertEqual(self.bundle.pending_count, 1)
            await self.bundle.aclose()
        self.assertEqual(calls, 2)
        self.assertEqual(self.bundle.pending_count, 0)
        await recognition.aclose()

    async def test_partial_sdk_constructor_retains_created_task_until_bundle_close(self):
        entered, release, settled = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def actual_owner():
            entered.set()
            try:
                await release.wait()
            finally:
                settled.set()

        def partial(stream, **kwargs):
            stream._task = asyncio.create_task(actual_owner())
            raise RuntimeError(PRIVATE)

        with (
            patch.object(stt.RecognizeStream, "__init__", partial),
            self.assertRaises(m.NativeModelError) as error,
        ):
            self.bundle.stt.stream()
        self.assertEqual(str(error.exception), "unavailable")
        await entered.wait()
        self.assertEqual(self.bundle.pending_count, 1)
        replacement = self.bundle.stt.stream()
        self.addAsyncCleanup(replacement.aclose)
        with self.assertRaises(m.NativeModelError) as capacity:
            self.bundle.stt.stream()
        self.assertEqual(capacity.exception.code, "capacity_exhausted")
        await self.bundle.aclose()
        self.assertTrue(settled.is_set())
        self.assertEqual(self.bundle.pending_count, 0)
        fresh = await m.load_scripted_models()
        fresh_stream = fresh.stt.stream()
        await fresh_stream.aclose()
        await fresh.aclose()

    async def test_model_rejects_tools_before_any_stream_and_can_still_reply(self):
        @llm.function_tool
        async def forbidden() -> str:
            raise AssertionError("scripted model cannot invoke an action")

        with self.assertRaises(m.NativeModelError) as error:
            self.bundle.llm.chat(chat_ctx=llm.ChatContext(), tools=[forbidden])
        self.assertEqual(error.exception.code, "invalid_input")
        self.assertEqual(self.bundle.pending_count, 0)
        stream = self.bundle.llm.chat(chat_ctx=llm.ChatContext(), tool_choice="none")
        await consume(stream)
        await stream.aclose()
        self.assertEqual(self.bundle.pending_count, 0)

    async def test_close_task_allocation_failure_closes_coroutine_and_retains_owner(self):
        recognition = self.bundle.stt.stream()
        with warnings.catch_warnings(record=True) as observed:
            warnings.simplefilter("always", RuntimeWarning)
            with (
                patch.object(asyncio, "create_task", side_effect=RuntimeError(PRIVATE)),
                self.assertRaises(m.NativeModelError) as error,
            ):
                await self.bundle.aclose()
            self.assertEqual(str(error.exception), "cleanup_incomplete")
            self.assertEqual(self.bundle.pending_count, 1)
            gc.collect()
            self.assertFalse(any("was never awaited" in str(item.message) for item in observed))
        await self.bundle.aclose()
        await recognition.aclose()
        self.assertEqual(self.bundle.pending_count, 0)

    async def test_closed_bundle_rejects_new_models_and_turns(self):
        await self.bundle.aclose()
        for action in (
            lambda: self.bundle.stt.stream(),
            lambda: self.bundle.llm.chat(chat_ctx=llm.ChatContext()),
            lambda: self.bundle.tts.synthesize("This is a scripted local voice demonstration."),
            lambda: self.bundle.recognizer.begin_turn(str(uuid4())),
        ):
            with self.assertRaises(m.NativeModelError) as error:
                action()
            self.assertEqual(error.exception.code, "closed")
        self.assertEqual(self.bundle.pending_count, 0)
        self.assertTrue(
            all(type(value) is int and value >= 0 for value in self.bundle.metrics().values())
        )


async def consume(stream):
    return [item async for item in stream]


class LoaderOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_fifo_replacement_cannot_block_cancelled_loader_thread(self):
        code = r"""import asyncio,json,os,pathlib,subprocess,sys,tempfile,threading
from unittest.mock import patch
from services.channel_policy_demo import native_models as m
async def main():
 with tempfile.TemporaryDirectory() as directory:
  target=pathlib.Path(directory)/'declared'
  target.write_bytes(b'bounded')
  actual_lstat=pathlib.Path.lstat
  actual_open=os.open
  replaced=False
  entered=threading.Event(); allowed=threading.Event(); read_done=threading.Event()
  fallback=threading.Event(); writer_done=threading.Event()
  flags=[]; reader_codes=[]
  def lstat(path,*args,**kwargs):
   nonlocal replaced
   before=actual_lstat(path,*args,**kwargs)
   if path==target and not replaced:
    replaced=True; target.unlink(); os.mkfifo(target,0o600)
   return before
  def opening(path,bits,*args,**kwargs):
   if pathlib.Path(path)==target:
    flags.append(bits); entered.set()
    if not allowed.wait(2): raise AssertionError('owned open gate timed out')
   return actual_open(path,bits,*args,**kwargs)
  def load():
   try: return m._read(target,64)
   except m.NativeModelError as error:
    reader_codes.append(error.code); raise
   finally: read_done.set()
  def release_old_blocking_reader():
   try:
    if not read_done.wait(1):
     fallback.set()
     descriptor=actual_open(target,os.O_WRONLY|os.O_NONBLOCK)
     os.close(descriptor)
   finally: writer_done.set()
  writer=threading.Thread(target=release_old_blocking_reader)
  with patch.object(pathlib.Path,'lstat',lstat),patch.object(os,'open',opening),patch.object(m,'_load_assets',load):
   task=asyncio.create_task(m.load_scripted_models())
   assert await asyncio.to_thread(entered.wait,1)
   task.cancel()
   await asyncio.sleep(0)
   retained_before_release=not task.done()
   writer.start()
   allowed.set()
   try:
    await task
    raise AssertionError('expected cancellation')
   except asyncio.CancelledError: pass
   finally:
    allowed.set()
    await asyncio.to_thread(writer.join,2)
  assert not writer.is_alive() and writer_done.is_set()
  assert not any(name.startswith('livekit') for name in sys.modules)
  print(json.dumps({'nonblocking':bool(flags[0]&os.O_NONBLOCK),'retained_before_release':retained_before_release,'actual_thread_settled':read_done.is_set(),'fallback_writer_used':fallback.is_set(),'writer_reaped':not writer.is_alive(),'reader_codes':reader_codes}))
asyncio.run(main())
"""
        result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-I", "-B", "-c", code],
            cwd="/private/tmp",
            capture_output=True,
            text=True,
            check=False,
            timeout=6,
            env={"PATH": os.defpath, "LANG": "C.UTF-8", "NO_COLOR": "1"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "nonblocking": True,
                "retained_before_release": True,
                "actual_thread_settled": True,
                "fallback_writer_used": False,
                "writer_reaped": True,
                "reader_codes": ["invalid_configuration"],
            },
        )

    async def test_cancelled_loader_retains_actual_thread_without_model_construction(self):
        entered, release = threading.Event(), threading.Event()
        actual = m._load_assets

        def held_assets():
            entered.set()
            release.wait(2)
            return actual()

        with (
            patch.object(m, "_load_assets", held_assets),
            patch("services.channel_policy_demo._native_models_sdk.build_models") as construct,
        ):
            task = asyncio.create_task(m.load_scripted_models())
            await asyncio.to_thread(entered.wait, 1)
            self.assertTrue(entered.is_set())
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
            construct.assert_not_called()
        value = await m.load_scripted_models()
        await value.aclose()

    async def test_pending_cancellation_starts_no_loader_thread_and_fresh_load_progresses(self):
        async def cancelled():
            asyncio.current_task().cancel()
            await m.load_scripted_models()

        with patch.object(m, "_load_assets") as load:
            task = asyncio.create_task(cancelled())
            with self.assertRaises(asyncio.CancelledError):
                await task
            load.assert_not_called()
        bundle = await m.load_scripted_models()
        await bundle.aclose()

    async def test_unexpected_loader_failure_is_finite_and_starts_no_models(self):
        with (
            patch.object(m, "_load_assets", side_effect=RuntimeError(PRIVATE)),
            patch("services.channel_policy_demo._native_models_sdk.build_models") as construct,
            self.assertRaises(m.NativeModelError) as error,
        ):
            await m.load_scripted_models()
        self.assertEqual(str(error.exception), "unavailable")
        construct.assert_not_called()
        bundle = await m.load_scripted_models()
        await bundle.aclose()

    async def test_loader_task_allocation_failure_is_finite_no_unawaited_coroutine(self):
        with warnings.catch_warnings(record=True) as observed:
            warnings.simplefilter("always", RuntimeWarning)
            with (
                patch.object(asyncio, "create_task", side_effect=RuntimeError(PRIVATE)),
                self.assertRaises(m.NativeModelError) as error,
            ):
                await m.load_scripted_models()
            self.assertEqual(str(error.exception), "unavailable")
            gc.collect()
            self.assertFalse(any("was never awaited" in str(item.message) for item in observed))
        bundle = await m.load_scripted_models()
        await bundle.aclose()


if __name__ == "__main__":
    unittest.main()
