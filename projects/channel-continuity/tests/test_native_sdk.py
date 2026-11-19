"""Actual pinned SDK pipeline; synthetic providers never call a remote service."""

import asyncio
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from livekit import rtc
from livekit.agents import Agent, AgentSession
from livekit.agents.voice.io import AudioInput, AudioOutput, AudioOutputCapabilities, TextOutput

from channel_continuity.codec import AccountScope, ProviderScope
from channel_continuity.native import (
    NativeAck,
    NativeBinding,
    NativeError,
    NativeInput,
    NativeRuntime,
)

spec = importlib.util.spec_from_file_location(
    "p2_scripted_sdk_test", Path(__file__).parents[1] / "examples" / "native_scripted.py"
)
assert spec and spec.loader
scripted = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = scripted
spec.loader.exec_module(scripted)


def binding():
    return NativeBinding(
        str(uuid4()),
        ProviderScope("tenant", "livekit", "local"),
        AccountScope("tenant", "account"),
        "case",
        "conversation",
        "room",
        "browser",
        "agent",
    )


def rpc(value=None, caller="browser"):
    return rtc.RpcInvocationData(
        request_id="test",
        caller_identity=caller,
        payload=json.dumps({"schemaVersion": 1, **({"inputId": value} if value else {})}),
        response_timeout=5,
    )


def context(b, i, body="investigate"):
    return {
        "schemaVersion": 1,
        "kind": "investigation",
        "operationKey": str(uuid4()),
        "scope": {"tenantId": "tenant", "accountId": "account"},
        "caseId": "case",
        "caseRevision": "1",
        "conversationId": "conversation",
        "message": {
            "receiptId": str(uuid4()),
            "eventId": i,
            "messageId": i,
            "senderId": b.binding_id,
            "body": body,
        },
    }


class Intake:
    def __init__(self, gate=None):
        self.calls = []
        self.gate = gate
        self.entered = asyncio.Event()
        self.closed = False

    async def accept(self, v):
        self.calls.append(v)
        self.entered.set()
        if self.gate is not None:
            await self.gate.wait()
        return NativeAck(
            self.binding.binding_id,
            v.input_id,
            v.channel,
            "accepted",
            str(uuid4()),
            str(uuid4()),
            str(len(self.calls)),
        )

    async def aclose(self):
        self.closed = True


class QueueInput(AudioInput):
    def __init__(self):
        super().__init__(label="native-test-input")
        self.frames = asyncio.Queue(maxsize=32)

    async def __anext__(self):
        return await self.frames.get()


class AudioSink(AudioOutput):
    def __init__(self):
        super().__init__(
            label="native-test-output",
            capabilities=AudioOutputCapabilities(pause=False),
            sample_rate=16000,
        )
        self.frames = []
        self.duration = 0

    async def capture_frame(self, f):
        await super().capture_frame(f)
        self.frames.append(f)
        self.duration += f.duration

    def flush(self):
        super().flush()
        self.on_playback_finished(playback_position=self.duration, interrupted=False)
        self.duration = 0

    def clear_buffer(self):
        if self.duration:
            self.on_playback_finished(playback_position=self.duration, interrupted=True)
        self.duration = 0


class TextSink(TextOutput):
    def __init__(self):
        super().__init__(label="native-test-text", next_in_chain=None)
        self.parts = []

    async def capture_text(self, v):
        self.parts.append(v)

    def flush(self):
        pass


class NativeSdkTests(unittest.IsolatedAsyncioTestCase):
    async def make(self, *, gate=None, final_delay=0, interim_only=False, final_gate=None):
        b = binding()
        port = Intake(gate)
        port.binding = b
        recognizer = scripted.ScriptedRecognizer(
            final_delay=final_delay, interim_only=interim_only, final_gate=final_gate
        )
        model = scripted.ScriptedModel()
        voice = scripted.ScriptedVoice(b"\x10\x27" * 1600, pace=False)
        runtime = NativeRuntime(b, port, stt=recognizer, llm=model, tts=voice)
        source = QueueInput()
        audio = AudioSink()
        text = TextSink()
        runtime.session.input.audio = source
        runtime.session.output.audio = audio
        runtime.session.output.transcription = text
        await runtime.session.start(runtime.agent, record=False)
        runtime._ready = True
        runtime.session.input.set_audio_enabled(False)
        self.addAsyncCleanup(voice.aclose)
        self.addAsyncCleanup(recognizer.aclose)
        self.addAsyncCleanup(model.aclose)
        self.addAsyncCleanup(runtime.aclose)
        return runtime, port, recognizer, model, source, audio, text

    async def test_genuine_sdk_close_fences_runtime_input_and_prepare_before_cleanup(self):
        r, p, _stt, model, *_ = await self.make()
        seen = []
        r.session.on("close", lambda event: seen.append(event.reason.value))
        await r.session.aclose()
        self.assertEqual(seen, ["user_initiated"])
        self.assertTrue(r._closed)
        self.assertFalse(r._ready)
        self.assertEqual(r.metrics()["sdkSessionClosed"], 1)
        with self.assertRaises(rtc.RpcError) as rejected:
            await r.start_turn(rpc(str(uuid4())))
        self.assertEqual(rejected.exception.code, 1411)
        with self.assertRaises(NativeError):
            await r.prepare(context(r.binding, str(uuid4())))
        self.assertEqual((len(p.calls), model.calls), (0, 0))
        self.assertIsNotNone(r._close_task)
        await r.aclose()
        self.assertTrue(r._sdk_closed)

    async def test_sdk_close_retains_held_owned_context_after_cancelled_close_waiter(self):
        r, *_ = await self.make()
        entered, release = asyncio.Event(), asyncio.Event()

        async def held():
            entered.set()
            await release.wait()

        actual = asyncio.create_task(held())
        r._context_tasks.add(actual)
        actual.add_done_callback(r._context_tasks.discard)
        await entered.wait()
        try:
            await r.session.aclose()
            self.assertFalse(r._ready)
            self.assertFalse(actual.done())
            observer = asyncio.create_task(r.aclose())
            await asyncio.sleep(0)
            observer.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await observer
            self.assertFalse(actual.done())
            self.assertIsNotNone(r._close_task)
            self.assertFalse(r._close_task.done())
        finally:
            release.set()
            await actual
            await r.aclose()
        self.assertEqual(r.rehydration_metrics()["active"], 0)

    async def test_synthetic_close_allocation_failure_fences_then_public_cleanup_progresses(self):
        from livekit.agents.voice import CloseEvent, CloseReason

        from channel_continuity import native as native_module

        r, *_ = await self.make()
        with patch.object(
            native_module.asyncio,
            "create_task",
            side_effect=RuntimeError("PRIVATE_CLOSE_ALLOCATION"),
        ):
            r._session_closed(CloseEvent(reason=CloseReason.PARTICIPANT_DISCONNECTED))
        self.assertFalse(r._ready)
        self.assertTrue(r._closed)
        self.assertIsNone(r._close_task)
        self.assertEqual(r.metrics()["sdkCloseAllocationFailed"], 1)
        await r.aclose()
        self.assertTrue(r._sdk_closed)

    async def test_legacy_v6_interrupt_wire_remains_available(self):
        runtime, *_ = await self.make()
        self.assertIsNone(runtime._communication)
        self.assertEqual(
            json.loads(await runtime.interrupt(rpc())),
            {"schemaVersion": 1, "status": "speech_interrupted", "inputId": None},
        )
        self.assertEqual(runtime.metrics()["defaultReplyInvocations"], 0)

    async def feed(self, source, recognizer):
        previous = recognizer.audio_seconds
        for _ in range(10):
            await source.frames.put(
                rtc.AudioFrame(
                    b"\x10\x27" * 320, sample_rate=16000, num_channels=1, samples_per_channel=320
                )
            )
        async with asyncio.timeout(3):
            while recognizer.audio_seconds < previous + 0.19:
                await asyncio.sleep(0.005)

    async def test_committed_voice_accepts_before_sole_dispatch_and_repeat_has_one_user_context(
        self,
    ):
        gate = asyncio.Event()
        r, p, stt, model, source, audio, text = await self.make(gate=gate)
        i = str(uuid4())
        await r.start_turn(rpc(i))
        await self.feed(source, stt)
        committing = asyncio.create_task(r.commit_turn(rpc(i)))
        await asyncio.wait_for(p.entered.wait(), 3)
        self.assertEqual(model.calls, 0)
        self.assertEqual(r.metrics()["defaultReplyInvocations"], 0)
        from livekit.agents import StopResponse
        from livekit.agents.llm import ChatContext, ChatMessage

        with self.assertRaises(StopResponse):
            await r.agent.on_user_turn_completed(
                ChatContext(), ChatMessage(role="user", content=["investigate"])
            )
        preparing = asyncio.create_task(r.prepare(context(r.binding, i)))
        await asyncio.sleep(0)
        self.assertEqual(model.calls, 0)
        gate.set()
        self.assertEqual(json.loads(await committing)["status"], "turn_committed")
        self.assertEqual((await preparing)["source"], "scripted")
        self.assertEqual(json.loads(await r.commit_turn(rpc(i)))["status"], "turn_committed")
        self.assertEqual(len(p.calls), 1)
        self.assertEqual(model.calls, 1)
        self.assertTrue(audio.frames)
        self.assertTrue(text.parts)
        users = [m for m in r.agent.chat_ctx.items if getattr(m, "role", None) == "user"]
        self.assertEqual(len(users), 1)
        self.assertEqual(users[0].text_content, "investigate")
        self.assertEqual(r.metrics()["nativeGenerationAttempts"], 1)
        self.assertEqual(r.metrics()["activeVoiceWork"], 0)

    async def test_interim_promoted_by_sdk_never_becomes_genuine_acceptance(self):
        r, p, stt, model, source, *_ = await self.make(interim_only=True)
        i = str(uuid4())
        await r.start_turn(rpc(i))
        await self.feed(source, stt)
        self.assertEqual(json.loads(await r.commit_turn(rpc(i)))["status"], "no_audio")
        self.assertEqual(p.calls, [])
        self.assertEqual(model.calls, 0)
        self.assertEqual(r.metrics()["genuineFinalSnapshots"], 0)

    async def test_delayed_genuine_final_keeps_original_turn_and_never_generates_automatically(
        self,
    ):
        final = asyncio.Event()
        r, p, stt, model, source, *_ = await self.make(final_gate=final)
        i = str(uuid4())
        await r.start_turn(rpc(i))
        await self.feed(source, stt)
        committing = asyncio.create_task(r.commit_turn(rpc(i)))
        async with asyncio.timeout(3):
            while not stt._pending:
                await asyncio.sleep(0.005)
        with self.assertRaises(rtc.RpcError):
            await r.start_turn(rpc(str(uuid4())))
        self.assertEqual(p.calls, [])
        self.assertEqual(model.calls, 0)
        final.set()
        self.assertEqual(json.loads(await committing)["status"], "turn_committed")
        self.assertEqual(p.calls[0].input_id, i)
        self.assertEqual(model.calls, 0)

    async def test_wrong_rpc_caller_and_changed_context_cannot_generate(self):
        r, p, _stt, model, *_ = await self.make()
        i = str(uuid4())
        with self.assertRaises(rtc.RpcError):
            await r.start_turn(rpc(i, "wrong"))
        changed = context(r.binding, i)
        changed["caseId"] = "other"
        with self.assertRaises(NativeError):
            await r.prepare(changed)
        self.assertEqual(p.calls, [])
        self.assertEqual(model.calls, 0)

    async def test_explicit_text_intake_is_durable_only_until_public_dispatch(self):
        r, _p, _stt, model, *_ = await self.make()
        i = str(uuid4())
        value = NativeInput(i, "web_chat", "investigate", "room", "browser")
        ack = await r._accept(value)
        self.assertEqual(ack.status, "accepted")
        self.assertEqual(model.calls, 0)
        await r.prepare(context(r.binding, i))
        self.assertEqual(model.calls, 1)
        self.assertEqual(r.metrics()["defaultReplyInvocations"], 0)

    async def test_late_closed_source_final_cannot_be_relabelled_into_next_turn(self):
        stt = scripted.ScriptedRecognizer(final_gate=asyncio.Event())
        i = str(uuid4())
        stt.begin_turn(i)
        stream = stt.stream()
        try:
            stream.push_frame(
                rtc.AudioFrame(
                    b"\x10\x27" * 3200, sample_rate=16000, num_channels=1, samples_per_channel=3200
                )
            )
            stream.flush()
            async with asyncio.timeout(2):
                while i not in stt._pending:
                    await asyncio.sleep(0.005)
            stt.end_turn(i)
            with self.assertRaises(NativeError):
                stt.begin_turn(str(uuid4()))
            stt.final_gate.set()
            async with asyncio.timeout(2):
                while stt._pending:
                    await asyncio.sleep(0.005)
            self.assertIsNone(stt.final_snapshot(i))
            other = str(uuid4())
            stt.begin_turn(other)
            self.assertIsNone(stt.final_snapshot(other))
            stt.end_turn(other)
        finally:
            await stream.aclose()
            await stt.aclose()

    async def test_context_cap_and_typed_identity_preflight_do_not_invoke_sdk(self):
        r, _p, _stt, model, *_ = await self.make()
        r._generation_count = 64
        with self.assertRaises(NativeError):
            await r.prepare(context(r.binding, str(uuid4())))
        self.assertEqual(model.calls, 0)

    async def test_positive_control_plain_sdk_hook_would_automatically_generate_without_intake(
        self,
    ):
        recognizer = scripted.ScriptedRecognizer()
        model = scripted.ScriptedModel()
        voice = scripted.ScriptedVoice(b"\x10\x27" * 1600, pace=False)
        session = AgentSession(
            stt=recognizer,
            llm=model,
            tts=voice,
            vad=None,
            turn_handling={"turn_detection": "manual", "preemptive_generation": {"enabled": False}},
        )
        source = QueueInput()
        session.input.audio = source
        session.output.audio = AudioSink()
        session.output.transcription = TextSink()
        try:
            await session.start(Agent(instructions="Fixed local test"), record=False)
            recognizer.begin_turn(str(uuid4()))
            await self.feed(source, recognizer)
            await session.commit_user_turn(transcript_timeout=2, stt_flush_duration=0.1)
            async with asyncio.timeout(3):
                while model.calls != 1:
                    await asyncio.sleep(0.005)
            self.assertEqual(model.calls, 1)
        finally:
            await session.aclose()
            await recognizer.aclose()
            await model.aclose()
            await voice.aclose()

    async def test_native_text_reader_caller_and_attribute_limits_are_enforced_before_intake(self):
        r, p, _stt, model, *_ = await self.make()

        class Reader:
            def __init__(self, attributes):
                self.info = SimpleNamespace(topic="lk.chat", attributes=attributes)
                self.closed = False

            def close(self):
                self.closed = True

            def __aiter__(self):
                return self.iterate()

            async def iterate(self):
                yield "investigate"

        wrong = Reader({"p2.input_id": str(uuid4())})
        r._on_text(wrong, "other")
        self.assertTrue(wrong.closed)
        self.assertEqual(p.calls, [])
        bad = Reader({"p2.input_id": str(uuid4()), "accountId": "other"})
        r._on_text(bad, "browser")
        if r._readers:
            await asyncio.gather(*tuple(r._readers))
        self.assertTrue(bad.closed)
        self.assertEqual(p.calls, [])
        self.assertEqual(model.calls, 0)

    async def test_observer_outages_and_eight_pending_cap_are_real_fixed_counters(self):
        from unittest.mock import patch

        from channel_continuity import native

        r, *_ = await self.make()

        def fail(_):
            raise RuntimeError("SECRET_SENTINEL")

        r._observer = fail
        r._emit("input", "rejected")
        self.assertEqual(r.metrics()["observerFailures"], 1)

        async def async_fail(_):
            raise RuntimeError("SECRET_SENTINEL")

        r._observer = async_fail
        r._emit("input", "rejected")
        if r._notices:
            await asyncio.gather(*tuple(r._notices), return_exceptions=True)
        self.assertEqual(r.metrics()["observerFailures"], 2)
        r._observer = None
        with patch.object(native.LOGGER, "info", side_effect=RuntimeError("SECRET_SENTINEL")):
            r._emit("input", "rejected")
        self.assertEqual(r.metrics()["observerFailures"], 3)
        gate = asyncio.Event()

        async def held(_):
            await gate.wait()

        r._observer = held
        for _ in range(9):
            r._emit("input", "accepted")
        self.assertEqual(r.metrics()["observerPending"], 8)
        self.assertEqual(r.metrics()["observerDropped"], 1)
        gate.set()
        await asyncio.gather(*tuple(r._notices))
        self.assertEqual(r.metrics()["observerPending"], 0)

    async def test_close_during_held_started_observation_cannot_start_sdk_generation(self):
        from unittest.mock import patch

        r, _p, _stt, model, *_ = await self.make()
        entered = asyncio.Event()
        release = asyncio.Event()

        async def held(*_):
            entered.set()
            await release.wait()

        with patch.object(r, "_generation", held):
            preparing = asyncio.create_task(r.prepare(context(r.binding, str(uuid4()))))
            await entered.wait()
            closing = asyncio.create_task(r.aclose())
            await asyncio.sleep(0)
            self.assertTrue(r._closed)
            self.assertEqual(model.calls, 0)
            self.assertEqual(r.metrics()["activePrepare"], 1)
            release.set()
            with self.assertRaises(NativeError):
                await preparing
            await closing
        self.assertEqual(model.calls, 0)
        self.assertEqual(r.metrics()["activePrepare"], 0)

    async def test_monotonic_expiry_during_started_observation_cannot_start_sdk_generation(self):
        from unittest.mock import patch

        from channel_continuity import native

        r, _p, _stt, model, *_ = await self.make()
        real = asyncio.get_running_loop()
        offset = 0

        class Clock:
            def time(self):
                return real.time() + offset

            def __getattr__(self, name):
                return getattr(real, name)

        async def held(*_):
            nonlocal offset
            offset = 5

        with (
            patch.object(r, "_generation", held),
            patch.object(native.asyncio, "get_running_loop", return_value=Clock()),
            self.assertRaises(NativeError),
        ):
            await r.prepare(context(r.binding, str(uuid4())))
        self.assertEqual(model.calls, 0)
        await r.prepare(context(r.binding, str(uuid4())))
        self.assertEqual(model.calls, 1)

    async def test_sdk_close_failure_still_drains_independent_intake_and_observer(self):
        from unittest.mock import AsyncMock, patch

        from channel_continuity.native import NativeCleanupIncomplete

        gate = asyncio.Event()
        r, p, _stt, _model, *_ = await self.make(gate=gate)
        notice = asyncio.Event()

        async def held(_):
            await notice.wait()

        r._observer = held
        r._emit("input", "accepted")
        accepting = asyncio.create_task(
            r._accept(NativeInput(str(uuid4()), "web_chat", "investigate", "room", "browser"))
        )
        await p.entered.wait()
        with patch.object(
            r.session, "aclose", new=AsyncMock(side_effect=RuntimeError("SECRET_SENTINEL"))
        ):
            closing = asyncio.create_task(r.aclose())
            await asyncio.sleep(0)
            self.assertEqual(r.metrics()["activeIntakes"], 1)
            gate.set()
            notice.set()
            await accepting
            with self.assertRaises(NativeCleanupIncomplete) as raised:
                await closing
            self.assertNotIn("SECRET_SENTINEL", str(raised.exception))
            self.assertFalse(r.sdk_closed)
        self.assertEqual(r.metrics()["activeIntakes"], 0)
        self.assertEqual(r.metrics()["observerPending"], 0)
        failed_close = r._close_task
        sdk_close = r.session.aclose
        retry_entered, retry_release = asyncio.Event(), asyncio.Event()
        retry_calls = 0

        async def recovered_close():
            nonlocal retry_calls
            retry_calls += 1
            retry_entered.set()
            await retry_release.wait()
            await sdk_close()

        with patch.object(r.session, "aclose", new=recovered_close):
            first_retry = asyncio.create_task(r.aclose())
            try:
                async with asyncio.timeout(1):
                    await retry_entered.wait()
                second_retry = asyncio.create_task(r.aclose())
                await asyncio.sleep(0)
                self.assertIsNot(r._close_task, failed_close)
                self.assertEqual(retry_calls, 1)
                self.assertFalse(r._close_task.done())
                self.assertTrue(r._closed)
                self.assertFalse(r._ready)
                with self.assertRaises(rtc.RpcError):
                    await r.start_turn(rpc(str(uuid4())))
                with self.assertRaises(NativeError):
                    await r.prepare(context(r.binding, str(uuid4())))
                first_retry.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await first_retry
                self.assertFalse(r._close_task.done())
                self.assertFalse(second_retry.done())
            finally:
                retry_release.set()
                await asyncio.gather(first_retry, return_exceptions=True)
            await second_retry
            await r.aclose()
        self.assertEqual(retry_calls, 1)
        self.assertTrue(r.sdk_closed)

    async def test_two_actual_reader_slots_hold_until_settlement_and_reject_third(self):
        r, p, _stt, model, *_ = await self.make()
        release = asyncio.Event()
        entered = asyncio.Queue()

        class Reader:
            def __init__(self):
                self.info = SimpleNamespace(
                    topic="lk.chat", attributes={"p2.input_id": str(uuid4())}
                )
                self.closed = False

            def close(self):
                self.closed = True

            def __aiter__(self):
                return self.iterate()

            async def iterate(self):
                entered.put_nowait(True)
                await release.wait()
                yield "investigate"

        one, two, three = Reader(), Reader(), Reader()
        r._on_text(one, "browser")
        r._on_text(two, "browser")
        await entered.get()
        await entered.get()
        r._on_text(three, "browser")
        self.assertTrue(three.closed)
        self.assertEqual(r.metrics()["activeReaders"], 2)
        self.assertEqual(p.calls, [])
        self.assertEqual(model.calls, 0)
        release.set()
        await asyncio.gather(*tuple(r._readers))
        self.assertEqual(r.metrics()["activeReaders"], 0)
        self.assertEqual(len(p.calls), 2)
        self.assertEqual(model.calls, 0)


if __name__ == "__main__":
    unittest.main()
