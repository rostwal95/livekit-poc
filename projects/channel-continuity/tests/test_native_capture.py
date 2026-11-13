"""Actual pinned SDK capture/lifetime tests; local synthetic providers only."""

import asyncio
import contextvars
import gc
import hashlib
import json
import unittest
from uuid import uuid4

from livekit import rtc
from livekit.agents import llm, tts
from livekit.agents.voice import SpeechHandle
from livekit.agents.voice.agent import ModelSettings
from test_native_sdk import AudioSink, Intake, QueueInput, TextSink, binding, context, scripted

from channel_continuity.native import NativeError, NativeRuntime
from channel_continuity.native_capture import NativeCaptureManager
from channel_continuity.native_communication import (
    ObservationReceipt,
    ResponseReceipt,
    ResponseView,
)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


class MemoryCommunication:
    def __init__(self, b, gate=None):
        self.binding = b
        self.gate = gate
        self.entered = asyncio.Event()
        self.anchors = {}
        self.receipts = {}
        self.sdk = []
        self.browser = []
        self.closed = False

    async def begin_response(self, a):
        self.entered.set()
        if self.gate is not None:
            await self.gate.wait()
        b = self.binding
        canonical = {
            **a.payload(),
            "scope": {
                "tenantId": b.account_scope.tenant_id,
                "accountId": b.account_scope.account_id,
            },
            "providerScope": {
                "tenantId": b.provider_scope.tenant_id,
                "provider": b.provider_scope.provider,
                "providerAccountId": b.provider_scope.provider_account_id,
            },
            "caseId": b.case_id,
            "conversationId": b.conversation_id,
            "roomId": b.room_id,
            "participantId": b.participant_id,
        }
        self.anchors[a.response_id] = a
        r = ResponseReceipt(
            a.response_id,
            str(uuid4()),
            digest(canonical),
            str(len(self.anchors)),
            "2030-01-01T00:00:00.000Z",
        )
        self.receipts[a.response_id] = r
        return r

    async def observe_sdk(self, v):
        self.sdk.append(v)
        return self.receipt(v)

    async def observe_browser(self, v):
        self.browser.append(v)
        return self.receipt(v)

    def receipt(self, v):
        return ObservationReceipt(
            v.response_id,
            v.event_id,
            str(uuid4()),
            digest(v.payload()),
            str(len(self.sdk) + len(self.browser)),
            "2030-01-01T00:00:00.000Z",
        )

    async def inspect_response(self, response_id):
        generated = [
            x.text
            for x in self.sdk
            if x.response_id == response_id and x.kind == "generated_complete"
        ]
        settled = [
            x for x in self.sdk if x.response_id == response_id and x.kind == "speech_settled"
        ]
        browser = [x for x in self.browser if x.response_id == response_id]
        state = settled[-1].state if settled else "unknown"
        sdk_text = settled[-1].sdk_text if settled else None
        browser_state = (
            "completed_reported"
            if any(x.state == "completed" for x in browser)
            else "partial"
            if any(x.state == "partial" for x in browser)
            else "started"
            if browser
            else "unknown"
        )
        count = sum(x.response_id == response_id for x in self.sdk + self.browser)
        return ResponseView(
            self.anchors[response_id],
            self.binding,
            self.receipts[response_id],
            count,
            generated[-1] if generated else None,
            state,
            sdk_text,
            browser_state,
            False,
        )

    async def aclose(self):
        self.closed = True


class HeldAudio(AudioSink):
    def __init__(self):
        super().__init__()
        self.flushed = asyncio.Event()
        self.hold = True

    def flush(self):
        super(AudioSink, self).flush()
        self.flushed.set()
        if not self.hold:
            self.on_playback_finished(playback_position=self.duration, interrupted=False)
            self.duration = 0


class ControlledModel(scripted.ScriptedModel):
    def __init__(self, *, body=None, gate=None, ignore_cancel=False, fail=False):
        super().__init__()
        self.body = scripted.REPLY if body is None else body
        self.gate = gate
        self.ignore_cancel = ignore_cancel
        self.fail = fail
        self.emitted = asyncio.Event()
        self.cancelled = asyncio.Event()

    def chat(self, *, chat_ctx, tools=None, conn_options, **kwargs):
        return ControlledStream(self, chat_ctx, tools or [], conn_options)


class ControlledStream(scripted._ModelStream):
    async def _run(self):
        self.owner.calls += 1
        self._event_ch.send_nowait(
            llm.ChatChunk(
                id="capture-fixture",
                delta=llm.ChoiceDelta(role="assistant", content=self.owner.body),
            )
        )
        self.owner.emitted.set()
        if self.owner.gate is not None:
            while not self.owner.gate.is_set():
                try:
                    await self.owner.gate.wait()
                except asyncio.CancelledError:
                    self.owner.cancelled.set()
                    if not self.owner.ignore_cancel:
                        raise
        if self.owner.fail:
            raise RuntimeError("SYNTHETIC_MODEL_FAILURE")


class FlexibleVoice(scripted.ScriptedVoice):
    def synthesize(self, text, *, conn_options):
        return scripted._VoiceStream(self, text, conn_options)


class ImmediateStreamingVoice(tts.TTS):
    def __init__(self):
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=True), sample_rate=16000, num_channels=1
        )

    def synthesize(self, text, *, conn_options):
        raise NativeError()

    def stream(self, *, conn_options):
        return ImmediateStreamingVoiceStream(tts=self, conn_options=conn_options)


class ImmediateStreamingVoiceStream(tts.SynthesizeStream):
    async def _run(self, output_emitter):
        output_emitter.initialize(
            request_id="streaming-fixture",
            sample_rate=16000,
            num_channels=1,
            mime_type="audio/pcm",
            stream=True,
            frame_size_ms=20,
        )
        output_emitter.start_segment(segment_id="segment-fixture")
        async for value in self._input_ch:
            if isinstance(value, str):
                output_emitter.push(b"\x10\x27" * 1600)
            else:
                output_emitter.flush()
        output_emitter.end_segment()


class FailingVoice(scripted.ScriptedVoice):
    def synthesize(self, text, *, conn_options):
        raise RuntimeError("SYNTHETIC_TTS_FAILURE")


class IgnoringVoice(scripted.ScriptedVoice):
    def __init__(self, gate):
        super().__init__(b"\x10\x27" * 1600, pace=False)
        self.gate = gate
        self.entered = asyncio.Event()
        self.cancelled = asyncio.Event()

    def synthesize(self, text, *, conn_options):
        return IgnoringVoiceStream(self, text, conn_options)


class IgnoringVoiceStream(scripted._VoiceStream):
    async def _run(self, output_emitter):
        self.owner.entered.set()
        while not self.owner.gate.is_set():
            try:
                await self.owner.gate.wait()
            except asyncio.CancelledError:
                self.owner.cancelled.set()
        await super()._run(output_emitter)


class NativeCaptureTests(unittest.IsolatedAsyncioTestCase):
    async def make(self, *, model=None, audio=None, anchor_gate=None, voice=None):
        b = binding()
        input_port = Intake()
        input_port.binding = b
        communication = MemoryCommunication(b, anchor_gate)
        recognizer = scripted.ScriptedRecognizer()
        model = model or ControlledModel()
        voice = voice or scripted.ScriptedVoice(b"\x10\x27" * 1600, pace=False)
        runtime = NativeRuntime(
            b, input_port, stt=recognizer, llm=model, tts=voice, communication=communication
        )
        source = QueueInput()
        audio = audio or AudioSink()
        transcript = TextSink()
        runtime.session.input.audio = source
        runtime.session.output.audio = audio
        runtime.session.output.transcription = transcript
        await runtime.session.start(runtime.agent, record=False)
        runtime._ready = True
        runtime.session.input.set_audio_enabled(False)
        self.addAsyncCleanup(communication.aclose)
        self.addAsyncCleanup(voice.aclose)
        self.addAsyncCleanup(recognizer.aclose)
        self.addAsyncCleanup(model.aclose)
        self.addAsyncCleanup(runtime.aclose)
        return runtime, communication, model, audio, transcript

    async def test_actual_sdk_waits_for_durable_anchor_and_records_actual_full_stream(self):
        gate = asyncio.Event()
        r, p, model, audio, _ = await self.make(anchor_gate=gate)
        work = asyncio.create_task(r.prepare(context(r.binding, str(uuid4()))))
        await asyncio.wait_for(p.entered.wait(), 2)
        self.assertEqual(model.calls, 0)
        self.assertEqual(audio.frames, [])
        gate.set()
        self.assertEqual((await work)["source"], "scripted")
        generated = [x for x in p.sdk if x.kind == "generated_complete"]
        self.assertEqual(len(generated), 1)
        self.assertEqual(generated[0].text, scripted.REPLY)
        ticket = next(iter(r._communication.tickets.values()))
        self.assertTrue(ticket.retired)
        self.assertEqual(generated[0].sdk_speech_id, ticket.handle.result().id)
        self.assertEqual(r.communication_metrics()["activeNodes"], 0)
        self.assertEqual(r.metrics()["defaultReplyInvocations"], 0)

    async def test_actual_settled_interrupt_preserves_known_readonly_decision(self):
        audio = HeldAudio()
        r, p, _, _, _ = await self.make(audio=audio)
        work = asyncio.create_task(r.prepare(context(r.binding, str(uuid4()))))
        await asyncio.wait_for(audio.flushed.wait(), 2)
        ticket = next(iter(r._communication.tickets.values()))
        data = rtc.RpcInvocationData(
            request_id="interrupt",
            caller_identity="browser",
            payload=json.dumps({"schemaVersion": 1, "responseId": ticket.response_id}),
            response_timeout=5,
        )
        reply = json.loads(await r.interrupt_response(data))
        self.assertEqual(reply["status"], "interruption_requested")
        self.assertEqual((await work)["kind"], "investigation")
        self.assertEqual(r.metrics()["nativeGeneratedReplies"], 0)
        self.assertTrue(any(x.kind == "speech_settled" and x.state == "interrupted" for x in p.sdk))
        audio.hold = False
        self.assertEqual((await r.prepare(context(r.binding, str(uuid4()))))["source"], "scripted")
        self.assertEqual(r.metrics()["nativeGeneratedReplies"], 1)

    async def test_opt_in_legacy_interrupt_cannot_retarget_active_sdk_speech(self):
        audio = HeldAudio()
        r, _, _, _, _ = await self.make(audio=audio)
        work = asyncio.create_task(r.prepare(context(r.binding, str(uuid4()))))
        try:
            await asyncio.wait_for(audio.flushed.wait(), 2)
            ticket = next(iter(r._communication.tickets.values()))
            with self.assertRaises(rtc.RpcError) as denied:
                await r.interrupt(
                    rtc.RpcInvocationData(
                        request_id="legacy",
                        caller_identity="browser",
                        payload='{"schemaVersion":1}',
                        response_timeout=5,
                    )
                )
            self.assertEqual(denied.exception.code, 1403)
            self.assertFalse(ticket.handle.result().interrupted)
            self.assertFalse(work.done())
            await r.interrupt_response(
                rtc.RpcInvocationData(
                    request_id="scoped",
                    caller_identity="browser",
                    payload=json.dumps({"schemaVersion": 1, "responseId": ticket.response_id}),
                    response_timeout=5,
                )
            )
            self.assertEqual((await work)["kind"], "investigation")
        finally:
            audio.clear_buffer()
            await asyncio.gather(work, return_exceptions=True)
        audio.hold = False
        self.assertEqual((await r.prepare(context(r.binding, str(uuid4()))))["source"], "scripted")

    async def test_old_response_interrupt_never_retargets_new_handle(self):
        audio = HeldAudio()
        audio.hold = False
        r, _, _, _, _ = await self.make(audio=audio)
        await r.prepare(context(r.binding, str(uuid4())))
        old = next(iter(r._communication.tickets.values()))
        audio.hold = True
        audio.flushed.clear()
        new_work = asyncio.create_task(r.prepare(context(r.binding, str(uuid4()))))
        await asyncio.wait_for(audio.flushed.wait(), 2)
        new = list(r._communication.tickets.values())[-1]
        r._communication.interrupt(old.response_id)
        self.assertFalse(new.handle.result().interrupted)
        r._communication.interrupt(new.response_id)
        await new_work

    async def test_missing_capture_context_fails_at_node_call_without_model_invocation(self):
        r, _, model, _, _ = await self.make()
        with self.assertRaises(NativeError):
            r.agent.llm_node(llm.ChatContext(), [], ModelSettings())
        self.assertEqual(model.calls, 0)
        self.assertEqual(r.communication_metrics()["activeNodes"], 0)

    async def test_prefix_error_never_becomes_generated_complete_or_known_preparation(self):
        r, p, _, _, _ = await self.make(model=ControlledModel(fail=True))
        with self.assertRaises(NativeError):
            await r.prepare(context(r.binding, str(uuid4())))
        self.assertFalse(any(x.kind == "generated_complete" for x in p.sdk))
        self.assertEqual(r.metrics()["activePrepare"], 0)

    async def test_oversized_actual_stream_never_becomes_generated_complete(self):
        r, p, _, _, _ = await self.make(model=ControlledModel(body="x" * 4097))
        with self.assertRaises(NativeError):
            await r.prepare(context(r.binding, str(uuid4())))
        self.assertFalse(any(x.kind == "generated_complete" for x in p.sdk))

    async def test_browser_report_matches_original_response_and_is_not_acknowledgement(self):
        r, p, _, _, _ = await self.make()
        await r.prepare(context(r.binding, str(uuid4())))
        ticket = next(iter(r._communication.tickets.values()))
        event_id = str(uuid4())
        payload = {
            "schemaVersion": 1,
            "eventId": event_id,
            "responseId": ticket.response_id,
            "state": "partial",
            "observedAudioMs": 50,
        }
        reply = json.loads(
            await r.playback(
                rtc.RpcInvocationData(
                    request_id="report",
                    caller_identity="browser",
                    payload=json.dumps(payload),
                    response_timeout=5,
                )
            )
        )
        self.assertEqual(reply["status"], "known")
        self.assertEqual(reply["result"]["eventId"], event_id)
        self.assertEqual(len(p.browser), 1)
        denied = json.loads(
            await r.playback(
                rtc.RpcInvocationData(
                    request_id="wrong",
                    caller_identity="other",
                    payload=json.dumps(payload),
                    response_timeout=5,
                )
            )
        )
        self.assertEqual(denied["status"], "rejected")
        self.assertEqual(len(p.browser), 1)

    async def test_cancel_ignoring_source_outlives_watchdog_without_freeing_generation(self):
        release = asyncio.Event()
        model = ControlledModel(gate=release, ignore_cancel=True)
        r, p, _, _, _ = await self.make(model=model)
        work = asyncio.create_task(r.prepare(context(r.binding, str(uuid4()))))
        await asyncio.wait_for(model.emitted.wait(), 2)
        self.addCleanup(release.set)
        ticket = next(iter(r._communication.tickets.values()))
        ticket.handle.result().interrupt()
        await asyncio.wait_for(model.cancelled.wait(), 2)
        async with asyncio.timeout(7):
            while not ticket.handle.result().done():
                await asyncio.sleep(0.01)
        self.assertGreater(r.communication_metrics()["activeProducers"], 0)
        self.assertEqual(r.metrics()["activePrepare"], 1)
        with self.assertRaises(NativeError) as raised:
            await r.prepare(context(r.binding, str(uuid4())))
        self.assertEqual(raised.exception.code, "capacity_exhausted")
        self.assertFalse(any(x.kind == "generated_complete" for x in p.sdk))
        release.set()
        with self.assertRaises(NativeError):
            await work
        async with asyncio.timeout(3):
            while r.metrics()["activePrepare"]:
                await asyncio.sleep(0.01)
        self.assertEqual(r.communication_metrics()["activeProducers"], 0)
        model.gate = None
        model.ignore_cancel = False
        self.assertEqual((await r.prepare(context(r.binding, str(uuid4()))))["source"], "scripted")

    async def test_public_sdk_queued_unbound_call_cannot_borrow_current_response(self):
        audio = HeldAudio()
        r, p, model, _, _ = await self.make(audio=audio)
        preparing = asyncio.create_task(r.prepare(context(r.binding, str(uuid4()))))
        await asyncio.wait_for(audio.flushed.wait(), 2)
        original = next(iter(r._communication.tickets.values()))
        denied = asyncio.Event()
        node = r.agent.llm_node

        def observed_node(*args, **kwargs):
            try:
                return node(*args, **kwargs)
            except NativeError:
                denied.set()
                raise

        r.agent.llm_node = observed_node
        rogue = r.session.generate_reply(user_input="rogue queued input", tool_choice="none")
        await asyncio.wait_for(denied.wait(), 2)
        self.assertFalse(original.handle.result().done())
        self.assertEqual(model.calls, 1)
        self.assertEqual(len(p.anchors), 1)
        self.assertEqual(p.sdk[0].sdk_speech_id, original.handle.result().id)
        r._communication.interrupt(original.response_id)
        self.assertEqual((await preparing)["kind"], "investigation")
        await asyncio.wait_for(rogue.wait_for_playout(), 2)
        self.assertIsNotNone(rogue.exception())

    async def test_retired_captured_context_is_denied_before_new_source(self):
        r, _, model, _, _ = await self.make()
        snapshots = []
        original = r.session.generate_reply

        def capture(**kwargs):
            snapshots.append(contextvars.copy_context())
            return original(**kwargs)

        r.session.generate_reply = capture
        await r.prepare(context(r.binding, str(uuid4())))
        with self.assertRaises(NativeError):
            snapshots[0].run(r.agent.llm_node, llm.ChatContext(), [], ModelSettings())
        self.assertEqual(model.calls, 1)
        self.assertEqual(r.communication_metrics()["activeProducers"], 0)

    async def test_generate_raises_observes_futures_and_allows_later_progress(self):
        r, _, model, _, _ = await self.make()
        events = []
        loop = asyncio.get_running_loop()
        prior = loop.get_exception_handler()
        loop.set_exception_handler(lambda _, ctx: events.append(ctx))
        self.addCleanup(loop.set_exception_handler, prior)
        original = r.session.generate_reply

        def fail(**kwargs):
            raise RuntimeError("SDK_PRIVATE_SENTINEL")

        r.session.generate_reply = fail
        with self.assertRaises(NativeError) as raised:
            await r.prepare(context(r.binding, str(uuid4())))
        self.assertEqual(raised.exception.code, "dependency_unavailable")
        self.assertEqual(model.calls, 0)
        self.assertTrue(all(t.retired for t in r._communication.tickets.values()))
        r._communication.tickets.clear()
        gc.collect()
        await asyncio.sleep(0)
        self.assertFalse(events)
        r.session.generate_reply = original
        self.assertEqual((await r.prepare(context(r.binding, str(uuid4()))))["source"], "scripted")

    async def test_anchor_failure_has_no_model_output_and_observes_futures(self):
        r, p, model, audio, _ = await self.make()
        original = p.begin_response
        events = []
        loop = asyncio.get_running_loop()
        prior = loop.get_exception_handler()
        loop.set_exception_handler(lambda _, ctx: events.append(ctx))
        self.addCleanup(loop.set_exception_handler, prior)

        async def fail(anchor):
            raise NativeError("acknowledgement_unknown")

        p.begin_response = fail
        with self.assertRaises(NativeError):
            await r.prepare(context(r.binding, str(uuid4())))
        self.assertEqual(model.calls, 0)
        self.assertEqual(audio.frames, [])
        self.assertEqual(r.communication_metrics()["activeProducers"], 0)
        r._communication.tickets.clear()
        gc.collect()
        await asyncio.sleep(0)
        self.assertFalse(events)
        p.begin_response = original
        self.assertEqual(
            (await r.prepare(context(r.binding, str(uuid4()))))["kind"], "investigation"
        )

    async def test_actual_sdk_first_audio_precedes_model_eof_and_generated_fact(self):
        gate = asyncio.Event()
        model = ControlledModel(body=scripted.REPLY + " More", gate=gate)
        voice = ImmediateStreamingVoice()
        r, p, _, audio, _ = await self.make(model=model, voice=voice)
        self.addCleanup(gate.set)
        preparing = asyncio.create_task(r.prepare(context(r.binding, str(uuid4()))))

        async def settle():
            gate.set()
            await asyncio.gather(preparing, return_exceptions=True)

        self.addAsyncCleanup(settle)
        await asyncio.wait_for(model.emitted.wait(), 2)
        async with asyncio.timeout(2):
            while not audio.frames:
                await asyncio.sleep(0.001)
        self.assertFalse(any(x.kind == "generated_complete" for x in p.sdk))
        self.assertFalse(gate.is_set())
        gate.set()
        self.assertEqual((await preparing)["kind"], "investigation")
        self.assertEqual(
            next(x.text for x in p.sdk if x.kind == "generated_complete"), scripted.REPLY + " More"
        )

    async def test_actual_tts_failure_retains_generation_but_not_completed_preparation(self):
        voice = FailingVoice(b"\x10\x27" * 1600, pace=False)
        r, p, _, _, _ = await self.make(voice=voice)
        with self.assertRaises(NativeError):
            await r.prepare(context(r.binding, str(uuid4())))
        self.assertTrue(any(x.kind == "generated_complete" for x in p.sdk))
        self.assertTrue(any(x.kind == "speech_settled" and x.state == "unknown" for x in p.sdk))
        self.assertEqual(r.metrics()["nativeGeneratedReplies"], 0)
        self.assertEqual(r.communication_metrics()["activeNodes"], 0)

    async def test_cancel_ignoring_tts_retains_real_node_past_handle_watchdog(self):
        gate = asyncio.Event()
        voice = IgnoringVoice(gate)
        r, p, _, _, _ = await self.make(voice=voice)
        self.addCleanup(gate.set)
        work = asyncio.create_task(r.prepare(context(r.binding, str(uuid4()))))
        await asyncio.wait_for(voice.entered.wait(), 2)
        ticket = next(iter(r._communication.tickets.values()))
        ticket.handle.result().interrupt()
        await asyncio.wait_for(voice.cancelled.wait(), 2)
        async with asyncio.timeout(7):
            while not ticket.handle.result().done():
                await asyncio.sleep(0.01)
        self.assertGreater(r.communication_metrics()["activeNodes"], 0)
        self.assertEqual(r.metrics()["activePrepare"], 1)
        with self.assertRaises(NativeError):
            await r.prepare(context(r.binding, str(uuid4())))
        gate.set()
        with self.assertRaises(NativeError):
            await work
        async with asyncio.timeout(3):
            while r.metrics()["activePrepare"]:
                await asyncio.sleep(0.01)
        self.assertEqual(r.communication_metrics()["activeNodes"], 0)
        self.assertTrue(any(x.kind == "generated_complete" for x in p.sdk))
        self.assertEqual(
            (await r.prepare(context(r.binding, str(uuid4()))))["kind"], "investigation"
        )


class StreamingChannelTests(unittest.IsolatedAsyncioTestCase):
    async def make_node(self, source):
        b = binding()
        port = MemoryCommunication(b)
        manager = NativeCaptureManager(b, port, lambda: None)
        ticket = manager.allocate(context(b, str(uuid4())), str(uuid4()))
        streams = []

        def generate():
            streams.append(manager.node(source))
            return SpeechHandle.create()

        manager.invoke(ticket, generate)
        await manager.publish_anchor(ticket)
        self.addAsyncCleanup(manager.aclose)
        return manager, ticket, streams[0], port

    async def test_queue_two_blocks_source_read_and_streams_before_eof(self):
        reads = []
        gate = asyncio.Event()

        async def source():
            for value in ("a", "b", "c"):
                reads.append(value)
                yield value
            await gate.wait()

        manager, ticket, node, port = await self.make_node(source)
        async with asyncio.timeout(2):
            while len(reads) < 2:
                await asyncio.sleep(0)
        self.assertEqual(reads, ["a", "b"])
        self.assertEqual(ticket.streams[0].queue.qsize(), 2)
        self.assertEqual(await anext(node), "a")
        async with asyncio.timeout(2):
            while len(reads) < 3:
                await asyncio.sleep(0)
        self.assertFalse(ticket.generated_complete)
        self.assertEqual(await anext(node), "b")
        self.assertEqual(await anext(node), "c")
        gate.set()
        with self.assertRaises(StopAsyncIteration):
            await anext(node)
        self.assertTrue(ticket.generated_complete)
        self.assertEqual(port.sdk[0].text, "abc")
        self.assertEqual(manager.metrics()["activeProducers"], 0)

    async def test_chunk_count_bound_stops_empty_source_without_full_text(self):
        async def source():
            for _ in range(257):
                yield ""

        _, ticket, node, port = await self.make_node(source)
        with self.assertRaises(NativeError):
            await anext(node)
        self.assertFalse(ticket.generated_complete)
        self.assertEqual(port.sdk, [])

    async def test_multi_segment_chunks_preserve_exact_generated_text(self):
        from livekit.agents.types import FlushSentinel

        async def source():
            yield llm.ChatChunk(id="a", delta=llm.ChoiceDelta(role="assistant", content="first "))
            yield FlushSentinel()
            yield "second"

        _, ticket, node, port = await self.make_node(source)
        values = [value async for value in node]
        self.assertEqual(values[0], "first ")
        self.assertIsInstance(values[1], FlushSentinel)
        self.assertEqual(values[2], "second")
        self.assertTrue(ticket.generated_complete)
        self.assertEqual(port.sdk[0].text, "first second")

    async def test_tts_call_cap_fails_before_unbounded_source_creation(self):
        b = binding()
        port = MemoryCommunication(b)
        manager = NativeCaptureManager(b, port, lambda: None)
        ticket = manager.allocate(context(b, str(uuid4())), str(uuid4()))
        calls = []

        async def source():
            calls.append(1)
            if False:
                yield None

        def generate():
            for _ in range(16):
                manager.tts(source)
            with self.assertRaises(NativeError) as raised:
                manager.tts(source)
            self.assertEqual(raised.exception.code, "capacity_exhausted")
            return SpeechHandle.create()

        manager.invoke(ticket, generate)
        self.assertEqual(calls, [])
        self.assertTrue(ticket.sdk_failure)
        await manager.aclose()
