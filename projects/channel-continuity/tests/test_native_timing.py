"""Explicit native timing and scheduled-reply ownership on the pinned SDK; no remote service."""

import asyncio
import unittest
from uuid import uuid4

from livekit.agents.voice.io import AudioOutput
from test_native_sdk import AudioSink, Intake, QueueInput, TextSink, binding, context, scripted

from channel_continuity.native import (
    SCRIPTED_INSTRUCTIONS,
    NativeError,
    NativeInput,
    NativeRuntime,
    NativeTiming,
)


class HeldPlaybackSink(AudioSink):
    """Reports playback finished only when released, like a real client still playing."""

    def __init__(self) -> None:
        super().__init__()
        self.release = asyncio.Event()
        self.finishers: set[asyncio.Task[None]] = set()

    def flush(self) -> None:
        AudioOutput.flush(self)
        played, self.duration = self.duration, 0

        async def finish() -> None:
            await self.release.wait()
            self.on_playback_finished(playback_position=played, interrupted=False)

        task = asyncio.ensure_future(finish())
        self.finishers.add(task)
        task.add_done_callback(self.finishers.discard)


class NativeTimingContractTests(unittest.TestCase):
    def test_defaults_match_the_scripted_profile(self):
        timing = NativeTiming()
        self.assertEqual(
            (timing.model_seconds, timing.commit_seconds, timing.transcript_seconds),
            (2.0, 4.0, 2.0),
        )
        self.assertEqual((timing.reply, timing.reply_seconds, timing.replies), ("playout", 60, 4))

    def test_out_of_range_or_inconsistent_budgets_fail_closed(self):
        for fields in (
            {"model_seconds": 0.5},
            {"model_seconds": float("nan")},
            {"model_seconds": True},
            {"commit_seconds": 13},
            {"transcript_seconds": 4.0},
            {"transcript_seconds": 5.0, "commit_seconds": 4.0},
            {"reply": "eventually"},
            {"reply_seconds": 1},
            {"replies": 0},
            {"replies": 9},
        ):
            with self.subTest(fields=fields), self.assertRaises(NativeError):
                NativeTiming(**fields)


class ScheduledReplyTests(unittest.IsolatedAsyncioTestCase):
    async def make(self, timing, *, instructions=None, sink=None):
        b = binding()
        port = Intake()
        port.binding = b
        recognizer = scripted.ScriptedRecognizer()
        model = scripted.ScriptedModel()
        voice = scripted.ScriptedVoice(b"\x10\x27" * 1600, pace=False)
        events = []
        runtime = NativeRuntime(
            b,
            port,
            stt=recognizer,
            llm=model,
            tts=voice,
            observer=events.append,
            timing=timing,
            instructions=instructions,
        )
        audio = sink or HeldPlaybackSink()
        runtime.session.input.audio = QueueInput()
        runtime.session.output.audio = audio
        runtime.session.output.transcription = TextSink()
        await runtime.session.start(runtime.agent, record=False)
        runtime._ready = True
        runtime.session.input.set_audio_enabled(False)
        self.addAsyncCleanup(voice.aclose)
        self.addAsyncCleanup(recognizer.aclose)
        self.addAsyncCleanup(model.aclose)
        self.addAsyncCleanup(runtime.aclose)
        return runtime, model, audio, events

    async def accepted(self, runtime):
        i = str(uuid4())
        await runtime._accept(NativeInput(i, "web_chat", "investigate", "room", "browser"))
        return i

    def outcomes(self, events):
        return [e["code"] for e in events if e["event"] == "generation"]

    async def test_scheduled_prepare_returns_before_playout_then_reports_completion(self):
        r, model, audio, events = await self.make(NativeTiming(reply="scheduled"))
        i = await self.accepted(r)
        async with asyncio.timeout(2):
            decision = await r.prepare(context(r.binding, i))
        self.assertEqual(decision["kind"], "investigation")
        self.assertEqual(r.metrics()["activeReplyObservers"], 1)
        # Dispatch returned once the reply was scheduled; generation continues.
        async with asyncio.timeout(2):
            while model.calls < 1:
                await asyncio.sleep(0.01)
        self.assertEqual(r.metrics()["nativeGeneratedReplies"], 0)
        self.assertEqual(self.outcomes(events), ["started"])
        audio.release.set()
        async with asyncio.timeout(2):
            while r.metrics()["activeReplyObservers"]:
                await asyncio.sleep(0.01)
        self.assertEqual(self.outcomes(events), ["started", "completed"])
        self.assertEqual(r.metrics()["nativeGeneratedReplies"], 1)

    async def test_default_playout_mode_still_waits_for_playback_before_dispatch(self):
        r, _model, audio, _events = await self.make(None)
        i = await self.accepted(r)
        preparing = asyncio.create_task(r.prepare(context(r.binding, i)))
        await asyncio.sleep(0.3)
        self.assertFalse(preparing.done())
        audio.release.set()
        async with asyncio.timeout(3):
            decision = await preparing
        self.assertEqual(decision["caseRevision"], "1")
        self.assertEqual(r.metrics()["activeReplyObservers"], 0)

    async def test_reply_observer_cap_rejects_new_dispatch_until_playback_settles(self):
        r, _model, audio, _events = await self.make(NativeTiming(reply="scheduled", replies=1))
        first = await self.accepted(r)
        await r.prepare(context(r.binding, first))
        second = await self.accepted(r)
        with self.assertRaises(NativeError) as rejected:
            await r.prepare(context(r.binding, second))
        self.assertEqual(rejected.exception.code, "capacity_exhausted")
        audio.release.set()
        async with asyncio.timeout(2):
            while r.metrics()["activeReplyObservers"]:
                await asyncio.sleep(0.01)
        await r.prepare(context(r.binding, second))

    async def test_close_cancels_reply_observers_without_waiting_for_playback(self):
        r, _model, _audio, events = await self.make(NativeTiming(reply="scheduled"))
        i = await self.accepted(r)
        await r.prepare(context(r.binding, i))
        self.assertEqual(r.metrics()["activeReplyObservers"], 1)
        async with asyncio.timeout(4):
            await r.aclose()
        self.assertEqual(r.metrics()["activeReplyObservers"], 0)
        self.assertNotIn("completed", self.outcomes(events))

    async def test_instructions_are_explicit_and_bounded(self):
        r, *_ = await self.make(None)
        self.assertEqual(r.agent.instructions, SCRIPTED_INSTRUCTIONS)
        custom, *_ = await self.make(None, instructions="Reply in one short sentence.")
        self.assertEqual(custom.agent.instructions, "Reply in one short sentence.")
        for invalid in ("", "x" * 4097, 7):
            with (
                self.subTest(length=len(invalid) if isinstance(invalid, str) else None),
                self.assertRaises(NativeError),
            ):
                NativeRuntime(
                    binding(),
                    Intake(),
                    stt=scripted.ScriptedRecognizer(),
                    llm=scripted.ScriptedModel(),
                    tts=scripted.ScriptedVoice(b"\x10\x27" * 1600, pace=False),
                    instructions=invalid,
                )

    async def test_published_inference_mode_is_explicit_and_closed(self):
        def runtime(**kwargs):
            return NativeRuntime(
                binding(),
                Intake(),
                stt=scripted.ScriptedRecognizer(),
                llm=scripted.ScriptedModel(),
                tts=scripted.ScriptedVoice(b"\x10\x27" * 1600, pace=False),
                **kwargs,
            )

        self.assertEqual(runtime()._inference_mode, "scripted")
        self.assertEqual(runtime(inference_mode="provider_real")._inference_mode, "provider_real")
        for invalid in ("local_real", "", None):
            with self.subTest(mode=invalid), self.assertRaises(NativeError):
                runtime(inference_mode=invalid)

    async def test_scheduled_replies_are_refused_with_response_capture(self):
        with self.assertRaises(NativeError):
            NativeRuntime(
                binding(),
                Intake(),
                stt=scripted.ScriptedRecognizer(),
                llm=scripted.ScriptedModel(),
                tts=scripted.ScriptedVoice(b"\x10\x27" * 1600, pace=False),
                communication=object(),  # type: ignore[arg-type]
                timing=NativeTiming(reply="scheduled"),
            )


if __name__ == "__main__":
    unittest.main()
