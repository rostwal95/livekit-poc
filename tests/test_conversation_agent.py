"""Scripted native providers, real SDK tool runs and caller-bound PTT controls."""

import asyncio
import io
import json
import logging
import math
import os
import pickle
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, PropertyMock, patch
from uuid import uuid4

from livekit import rtc
from livekit.agents import llm, room_io
from livekit.agents.types import APIConnectOptions
from livekit.agents.voice.io import AudioInput, AudioOutput, AudioOutputCapabilities, TextOutput
from livekit.agents.voice.room_io._output import _ParticipantAudioOutput
from livekit.agents.voice.transcription import TranscriptSynchronizer

from continuity_lab.bounded_io import BoundedAsyncIO
from continuity_lab.execution_models import ExecutionCapacityExceeded
from services.conversation_agent import scripted, telemetry, worker
from services.conversation_agent import session as conversation_session
from services.conversation_agent.scripted import (
    ACCEPTED,
    DEMO,
    GUARD,
    MAX_AUDIO_SECONDS,
    MAX_TEXT_BYTES,
    SAMPLE_RATE,
    SPEECH_FILES,
    STATUS,
    UNAVAILABLE,
    ScriptedLLM,
    ScriptedSTT,
    ScriptedTTS,
    SpeechBank,
)
from services.conversation_agent.session import (
    MAX_RPC_COMMANDS,
    MAX_TOOL_CALLS,
    SESSION_READY_ATTRIBUTE,
    ConversationBinding,
    ConversationControls,
    DurableAgent,
    create_runtime,
)


class Port:
    def __init__(self):
        self.calls = []
        self.closed = False

    async def submit_investigation(self):
        self.calls.append("submit")
        return {"schema_version": 1, "status": "accepted", "task_id": str(uuid4())}

    async def get_case(self):
        self.calls.append("get")
        return {"schema_version": 1, "status": "waiting"}

    async def cancel_case(self):
        self.calls.append("cancel")
        return {"schema_version": 1, "status": "cancelled"}

    async def aclose(self):
        self.closed = True


def bank():
    pcm = b"".join(
        int(3000 * math.sin(2 * math.pi * 440 * n / SAMPLE_RATE)).to_bytes(2, "little", signed=True)
        for n in range(1600)
    )
    return SpeechBank(tuple((text, pcm) for text in SPEECH_FILES))


def audio_frame(*, silent=False, samples=320, sample_rate=SAMPLE_RATE):
    pcm = bytes(samples * 2) if silent else b"\x10\x27" * samples
    return rtc.AudioFrame(pcm, sample_rate=sample_rate, num_channels=1, samples_per_channel=samples)


def invocation(caller="browser-test", payload='{"schema_version":1}'):
    return rtc.RpcInvocationData(
        request_id="local-control", caller_identity=caller, payload=payload, response_timeout=3
    )


class CapturingAudioOutput(AudioOutput):
    """Native SDK sink: real emitted PCM, immediate synthetic playout completion."""

    def __init__(self):
        super().__init__(
            label="scripted-test-sink",
            capabilities=AudioOutputCapabilities(pause=False),
            sample_rate=SAMPLE_RATE,
        )
        self.frames = []
        self.segment_seconds = 0.0

    async def capture_frame(self, frame):
        await super().capture_frame(frame)
        self.frames.append(frame)
        self.segment_seconds += frame.duration

    def flush(self):
        super().flush()
        self.on_playback_finished(playback_position=self.segment_seconds, interrupted=False)
        self.segment_seconds = 0.0

    def clear_buffer(self):
        if self.segment_seconds:
            self.on_playback_finished(playback_position=self.segment_seconds, interrupted=True)
        self.segment_seconds = 0.0


class CapturingTextOutput(TextOutput):
    def __init__(self):
        super().__init__(label="scripted-test-transcription", next_in_chain=None)
        self.parts = []

    async def capture_text(self, text):
        self.parts.append(text)

    def flush(self):
        pass


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    def test_speech_bank_loads_real_spoken_pcm_and_rejects_invalid_bounds(self):
        assets = Path(scripted.__file__).parent / "assets"
        speech = SpeechBank.load(assets)
        self.assertEqual(len(speech.clips), 7)
        self.assertTrue(
            all(0 < len(pcm) <= SAMPLE_RATE * 2 * MAX_AUDIO_SECONDS for _, pcm in speech.clips)
        )
        self.assertTrue(any(byte for byte in speech.pcm(DEMO)))
        for value in (
            (),
            ((DEMO, b"\x00"),),
            ((DEMO, b""),),
            ((DEMO, b"\x00\x00"), (DEMO, b"\x00\x00")),
        ):
            with self.subTest(value_length=len(value)), self.assertRaises(ValueError):
                SpeechBank(value)
        with self.assertRaises(ValueError):
            speech.pcm("Untrusted arbitrary speech")

    def test_speech_bank_rejects_symlink_and_truncated_fixture(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            (path / "demo.wav").write_bytes(b"not audio")
            with self.assertRaises(ValueError):
                SpeechBank.load(path)
            (path / "demo.wav").unlink()
            (path / "demo.wav").symlink_to(Path(scripted.__file__).parent / "assets/demo.wav")
            with self.assertRaises(ValueError):
                SpeechBank.load(path)

    async def test_tts_emits_real_nonzero_pcm_through_sdk_audio_emitter(self):
        speaker = ScriptedTTS(bank(), pace=False)
        metrics = []
        speaker.on("metrics_collected", metrics.append)
        async with speaker.synthesize(DEMO, conn_options=APIConnectOptions(max_retry=0)) as stream:
            frames = [event.frame async for event in stream]
        await asyncio.sleep(0)
        self.assertGreater(len(frames), 0)
        pcm = b"".join(frame.data.tobytes() for frame in frames)
        self.assertEqual(pcm[:3200], bank().pcm(DEMO))
        # Frozen SDK AudioEmitter appends a 10ms silent alignment marker.
        self.assertEqual(pcm[3200:], bytes(160 * 2))
        self.assertTrue(any(sample for frame in frames for sample in frame.data.cast("B")))
        self.assertGreater(speaker.frames_emitted, 0)
        self.assertEqual(len(metrics), 1)
        self.assertGreater(metrics[0].audio_duration, 0)
        await speaker.aclose()

    async def test_silent_audio_never_becomes_an_investigation_turn(self):
        recognizer = ScriptedSTT()
        result = await recognizer.recognize(
            [audio_frame(silent=True) for _ in range(10)],
            conn_options=APIConnectOptions(max_retry=0),
        )
        self.assertEqual(result.alternatives, [])
        self.assertEqual(recognizer.turns, 0)
        voiced = await recognizer.recognize(
            [audio_frame() for _ in range(10)], conn_options=APIConnectOptions(max_retry=0)
        )
        self.assertEqual(voiced.alternatives[0].text, "investigate")
        self.assertEqual(recognizer.turns, 1)
        self.assertGreater(recognizer.non_silent_seconds, 0.1)

    async def test_streamed_manual_flush_uses_received_audio_and_then_status_script(self):
        recognizer = ScriptedSTT()
        for expected in ("investigate", "status"):
            async with recognizer.stream(conn_options=APIConnectOptions(max_retry=0)) as stream:
                for _ in range(8):
                    stream.push_frame(audio_frame())
                stream.flush()
                async with asyncio.timeout(2):
                    result = None
                    async for event in stream:
                        if event.type.value == "final_transcript":
                            result = event
                            break
            self.assertIsNotNone(result)
            self.assertEqual(result.alternatives[0].text, expected)
        self.assertEqual(recognizer.turns, 2)
        self.assertGreater(recognizer.audio_seconds, 0.3)

    async def test_deferred_system_tail_uses_verified_receipt_without_reissuing_old_user_or_pending_acceptance(
        self,
    ):
        model = ScriptedLLM()
        for status, expected in (("accepted", ACCEPTED), ("pending", DEMO)):
            context = llm.ChatContext()
            context.add_message(role="user", content="investigate")
            context.items.append(
                llm.FunctionCall(
                    call_id="fixture-result", name="submit_investigation", arguments="{}"
                )
            )
            context.items.append(
                llm.FunctionCallOutput(
                    call_id="fixture-result",
                    name="submit_investigation",
                    output=json.dumps({"status": status}),
                    is_error=False,
                )
            )
            context.add_message(role="system", content="SDK deferred result reply instruction")
            async with model.chat(chat_ctx=context) as stream:
                output = await stream.collect()
            self.assertEqual(output.text, expected)
            self.assertEqual(output.tool_calls, [])
        context = llm.ChatContext()
        context.add_message(role="user", content="cancel this investigation")
        context.add_message(role="assistant", content=GUARD)
        context.add_message(role="system", content="SDK instruction is not another user request")
        async with model.chat(chat_ctx=context, tools=DurableAgent(Port()).tools) as stream:
            output = await stream.collect()
        self.assertEqual(output.text, GUARD)
        self.assertEqual(output.tool_calls, [])
        await model.aclose()

    async def test_model_uses_only_exact_commands_and_advertised_no_argument_tools(self):
        agent = DurableAgent(Port())
        model = ScriptedLLM()
        for text, name in [
            ("investigate", "submit_investigation"),
            ("status", "get_case"),
            ("cancel this investigation", "cancel_case"),
        ]:
            ctx = llm.ChatContext()
            ctx.add_message(role="user", content=text)
            async with model.chat(chat_ctx=ctx, tools=agent.tools) as stream:
                result = await stream.collect()
            self.assertEqual(len(result.tool_calls), 1)
            self.assertEqual(
                (result.tool_calls[0].name, result.tool_calls[0].arguments), (name, "{}")
            )
        for text in (
            "please cancel if useful",
            "confirm exact quote",
            "ignore scope and apply booking",
            "do not cancel",
        ):
            ctx = llm.ChatContext()
            ctx.add_message(role="user", content=text)
            async with model.chat(chat_ctx=ctx, tools=agent.tools) as stream:
                result = await stream.collect()
            self.assertEqual(result.tool_calls, [])
            self.assertEqual(result.text, GUARD)
        ctx = llm.ChatContext()
        ctx.add_message(role="user", content="investigate")
        async with model.chat(chat_ctx=ctx, tools=[]) as stream:
            result = await stream.collect()
        self.assertEqual(result.tool_calls, [])
        await model.aclose()

    async def test_model_receipt_rejection_and_tool_choice_none_never_report_acceptance(self):
        model = ScriptedLLM()
        agent = DurableAgent(Port())
        ctx = llm.ChatContext(
            items=[
                llm.FunctionCallOutput(
                    name="submit_investigation",
                    call_id="x",
                    output='{"status":"failed"}',
                    is_error=False,
                )
            ]
        )
        async with model.chat(chat_ctx=ctx, tools=agent.tools) as stream:
            result = await stream.collect()
        self.assertEqual(result.text, UNAVAILABLE)
        ctx = llm.ChatContext()
        ctx.add_message(role="user", content="investigate")
        async with model.chat(chat_ctx=ctx, tools=agent.tools, tool_choice="none") as stream:
            result = await stream.collect()
        self.assertEqual(result.tool_calls, [])
        await model.aclose()

    async def test_model_and_recognizer_reject_oversized_turns(self):
        recognizer = ScriptedSTT()
        with self.assertRaises(ValueError):
            await recognizer.recognize(
                [audio_frame(samples=SAMPLE_RATE)] * 13, conn_options=APIConnectOptions(max_retry=0)
            )
        model = ScriptedLLM()
        ctx = llm.ChatContext()
        ctx.add_message(role="user", content="x" * (MAX_TEXT_BYTES + 1))
        with self.assertRaises(ValueError):
            async with model.chat(chat_ctx=ctx) as stream:
                await stream.collect()
        await model.aclose()


class NativeSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_sdk_remote_session_ingress_is_absent_in_the_owned_runtime(self):
        class ControlledRoomIO:
            # Only RTC setup is controlled. AgentSession.start and the default
            # RoomSessionTransport/SessionHost are the real frozen native SDK.
            audio_input = video_input = audio_output = transcription_output = None
            subscribed_fut = None
            linked_participant = None

            def __init__(self, **_kwargs):
                pass

            async def start(self, **_kwargs):
                pass

            async def wait_for_ready(self):
                pass

            async def aclose(self):
                pass

        for production in (False, True):
            with self.subTest(production=production):
                byte_handlers, text_handlers, rpc_handlers = {}, {}, {}
                participant = SimpleNamespace(
                    identity="agent-hosting-probe",
                    register_rpc_method=rpc_handlers.__setitem__,
                    unregister_rpc_method=lambda name, handlers=rpc_handlers: handlers.pop(
                        name, None
                    ),
                    set_attributes=AsyncMock(),
                    send_bytes=AsyncMock(),
                )
                room = SimpleNamespace(
                    local_participant=participant,
                    register_byte_stream_handler=byte_handlers.__setitem__,
                    unregister_byte_stream_handler=lambda name, handlers=byte_handlers: (
                        handlers.pop(name, None)
                    ),
                    register_text_stream_handler=text_handlers.__setitem__,
                    unregister_text_stream_handler=lambda name, handlers=text_handlers: (
                        handlers.pop(name, None)
                    ),
                    isconnected=lambda: True,
                )
                port = Port()
                runtime = create_runtime(
                    port, ConversationBinding("browser-test"), bank(), pace=False
                )
                with patch("livekit.agents.voice.agent_session.room_io.RoomIO", ControlledRoomIO):
                    try:
                        if production:
                            await runtime.start(room)
                            self.assertEqual(byte_handlers, {})
                            self.assertEqual(set(text_handlers), {"lk.chat"})
                            self.assertEqual(
                                set(rpc_handlers), set(conversation_session.RPC_METHODS)
                            )
                            with self.assertRaises(rtc.RpcError) as caught:
                                await rpc_handlers["business.interrupt"](
                                    invocation("browser-other")
                                )
                            self.assertEqual(caught.exception.code, 1403)
                            rejected = SimpleNamespace(close=Mock())
                            text_handlers["lk.chat"](rejected, "browser-other")
                            rejected.close.assert_called_once()
                            self.assertEqual(port.calls, [])
                        else:
                            # A positive control proves this fixture observes
                            # the SDK's real default remote-session registration.
                            await runtime.session.start(
                                runtime.agent,
                                room=room,
                                room_options=room_io.RoomOptions(text_input=False),
                                record=False,
                            )
                            self.assertEqual(set(byte_handlers), {"lk.agent.session"})
                    finally:
                        await runtime.aclose()
                        if production:
                            runtime.controls.unregister(room)
                self.assertEqual(byte_handlers, {})

    async def test_public_roomio_barrier_rejects_premature_interruption_then_forwards_status_audio_and_text(
        self,
    ):
        gate, subscription_waiting = asyncio.Event(), asyncio.Event()
        attributes = []

        class Publication:
            sid = "TR_bounded_probe"

            async def wait_for_subscription(self):
                subscription_waiting.set()
                await gate.wait()

        class Participant:
            identity = "agent-bounded-probe"

            async def publish_track(self, *_args):
                return Publication()

            async def set_attributes(self, value):
                attributes.append(value)

            register_rpc_method = Mock()
            unregister_rpc_method = Mock()

        room = SimpleNamespace(
            local_participant=Participant(),
            register_text_stream_handler=Mock(),
            unregister_text_stream_handler=Mock(),
        )
        leaf = _ParticipantAudioOutput(
            room,
            sample_rate=SAMPLE_RATE,
            num_channels=1,
            track_publish_options=rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
        )
        text = CapturingTextOutput()
        synchronizer = TranscriptSynchronizer(next_in_chain_audio=leaf, next_in_chain_text=text)
        port = Port()
        speech = SpeechBank.load(Path(scripted.__file__).parent / "assets")
        runtime = create_runtime(port, ConversationBinding("browser-test"), speech, pace=False)
        runtime.session.output.audio = synchronizer.audio_output
        runtime.session.output.transcription = synchronizer.text_output
        # The SDK's real public RoomIO.wait_for_ready is exercised. Its native
        # publication is represented by the controlled public subscription port;
        # resolving its ready future models _init_task completing that port.
        sdk_roomio = room_io.RoomIO(runtime.session, room)
        ready = sdk_roomio._ready_fut
        playback_started = []
        leaf.on("playback_started", playback_started.append)
        original_start = runtime.session.start

        async def start_offline(agent, **_kwargs):
            await original_start(agent, record=False)

        async def finish_native_setup():
            await leaf.start()
            if not ready.done():
                ready.set_result(None)

        setup = asyncio.create_task(finish_native_setup())
        started = None
        try:
            with (
                patch.object(
                    type(runtime.session),
                    "room_io",
                    new_callable=PropertyMock,
                    return_value=sdk_roomio,
                ),
                patch.object(runtime.session, "start", side_effect=start_offline),
                patch.object(
                    runtime.session, "interrupt", wraps=runtime.session.interrupt
                ) as interrupt,
                patch.object(runtime.session, "say", wraps=runtime.session.say) as say,
            ):
                started = asyncio.create_task(runtime.start(room))
                async with asyncio.timeout(2):
                    await subscription_waiting.wait()
                    while runtime.session.agent_state != "listening":
                        await asyncio.sleep(0)
                self.assertFalse(started.done())
                self.assertEqual(attributes, [])
                for method in (
                    runtime.controls.start_turn,
                    runtime.controls.commit_turn,
                    runtime.controls.interrupt,
                ):
                    with self.assertRaises(rtc.RpcError) as caught:
                        await method(invocation())
                    self.assertEqual(caught.exception.code, 1411)
                await runtime.controls.text_input(
                    runtime.session,
                    SimpleNamespace(
                        text="status", participant=SimpleNamespace(identity="browser-test")
                    ),
                )
                interrupt.assert_not_called()
                say.assert_not_called()
                self.assertEqual(port.calls, [])
                self.assertFalse(leaf._subscribed_fut.cancelled())
                gate.set()
                async with asyncio.timeout(3):
                    await started
                self.assertEqual(
                    attributes,
                    [{SESSION_READY_ATTRIBUTE: "true", "continuity.inference_mode": "scripted"}],
                )
                say.assert_called_once_with(DEMO)
                # Interrupt the now-safe greeting immediately, then verify the
                # next real native tool response survives synchronized playback.
                await runtime.controls.text_input(
                    runtime.session,
                    SimpleNamespace(
                        text="status", participant=SimpleNamespace(identity="browser-test")
                    ),
                )
                async with asyncio.timeout(8):
                    while not (
                        STATUS in "".join(text.parts)
                        and any(
                            isinstance(item, llm.ChatMessage)
                            and item.role == "assistant"
                            and STATUS in (item.text_content or "")
                            for item in runtime.session.history.items
                        )
                    ):
                        await asyncio.sleep(0.01)
                self.assertEqual(port.calls, ["get"])
                self.assertGreater(len(playback_started), 0)
                self.assertFalse(leaf._subscribed_fut.cancelled())
        finally:
            gate.set()
            if started is not None and not started.done():
                started.cancel()
                await asyncio.gather(started, return_exceptions=True)
            async with asyncio.timeout(6):
                await runtime.aclose()
                await synchronizer.aclose()
                await leaf.aclose()
            await asyncio.gather(setup, return_exceptions=True)
            runtime.controls.unregister(room)

    async def test_media_readiness_timeout_or_cancellation_never_claims_ready_or_greets(self):
        for cancel in (False, True):
            with self.subTest(cancel=cancel):
                entered = asyncio.Event()

                async def wait_ready(event=entered):
                    event.set()
                    await asyncio.Event().wait()

                runtime = create_runtime(
                    Port(), ConversationBinding("browser-test"), bank(), pace=False
                )
                session = SimpleNamespace(
                    start=AsyncMock(),
                    room_io=SimpleNamespace(wait_for_ready=wait_ready),
                    input=SimpleNamespace(set_audio_enabled=Mock()),
                    say=Mock(),
                    aclose=AsyncMock(),
                )
                runtime.session = session
                room = SimpleNamespace(
                    local_participant=SimpleNamespace(
                        register_rpc_method=Mock(), set_attributes=AsyncMock()
                    ),
                    register_text_stream_handler=Mock(),
                )
                with patch.object(conversation_session, "MEDIA_READY_TIMEOUT_SECONDS", 0.02):
                    started = asyncio.create_task(runtime.start(room))
                    await entered.wait()
                    if cancel:
                        started.cancel()
                    with self.assertRaises(asyncio.CancelledError if cancel else TimeoutError):
                        await started
                self.assertFalse(runtime.controls._ready)
                session.say.assert_not_called()
                session.input.set_audio_enabled.assert_not_called()
                room.local_participant.set_attributes.assert_not_awaited()
                await runtime.aclose()
                session.aclose.assert_awaited_once()

    async def test_native_agent_session_executes_durable_tools_and_exposes_no_confirmation_tool(
        self,
    ):
        port = Port()
        runtime = create_runtime(port, ConversationBinding("browser-test"), bank(), pace=False)
        usage = []
        runtime.session.on("session_usage_updated", usage.append)
        await runtime.session.start(runtime.agent, record=False)
        runtime.controls.mark_ready()
        try:
            self.assertEqual(
                {tool.info.name for tool in runtime.agent.tools},
                {"submit_investigation", "get_case", "cancel_case"},
            )
            for command, expected in [
                ("investigate", ["submit"]),
                ("status", ["submit", "get"]),
                ("cancel this investigation", ["submit", "get", "cancel"]),
            ]:
                async with asyncio.timeout(10):
                    result = await runtime.session.run(user_input=command)
                self.assertEqual(port.calls, expected)
                self.assertGreaterEqual(len(result.events), 3)
            async with asyncio.timeout(10):
                await runtime.session.run(user_input="confirm the quote and apply it")
            self.assertEqual(port.calls, ["submit", "get", "cancel"])
            self.assertGreater(len(runtime.session.usage.model_usage), 0)
            self.assertGreater(len(usage), 0)
        finally:
            await runtime.aclose()

    async def test_real_native_manual_audio_routes_only_observed_voiced_turns_to_tools(self):
        class QueueInput(AudioInput):
            def __init__(self):
                super().__init__(label="bounded-scripted-test")
                self.frames = asyncio.Queue(maxsize=32)

            async def __anext__(self):
                return await self.frames.get()

        port = Port()
        runtime = create_runtime(port, ConversationBinding("browser-test"), bank(), pace=False)
        source = QueueInput()
        runtime.session.input.audio = source
        await runtime.session.start(runtime.agent, record=False)
        runtime.controls.mark_ready()
        runtime.session.input.set_audio_enabled(False)
        try:
            for silent, expected_calls, expected_status in (
                (True, [], "no_audio"),
                (False, ["submit"], "turn_committed"),
                (False, ["submit", "get"], "turn_committed"),
            ):
                await runtime.controls.start_turn(invocation())
                previous_audio = runtime.recognizer.audio_seconds
                for _ in range(10):
                    await source.frames.put(audio_frame(silent=silent))
                async with asyncio.timeout(3):
                    while runtime.recognizer.audio_seconds < previous_audio + 0.19:
                        await asyncio.sleep(0.01)
                reply = json.loads(await runtime.controls.commit_turn(invocation()))
                self.assertEqual(reply["status"], expected_status)
                async with asyncio.timeout(5):
                    while port.calls != expected_calls:
                        await asyncio.sleep(0.01)
                if silent:
                    self.assertEqual(runtime.recognizer.turns, 0)
            self.assertEqual(runtime.recognizer.turns, 2)
            self.assertGreater(runtime.recognizer.non_silent_seconds, 0.3)
            self.assertGreater(len(runtime.session.usage.model_usage), 0)
        finally:
            await runtime.aclose()

    async def test_fast_async_final_result_produces_accepted_assistant_transcription_and_spoken_pcm_for_text_and_manual_audio(
        self,
    ):
        class QueueInput(AudioInput):
            def __init__(self):
                super().__init__(label="bounded-positive-input")
                self.frames = asyncio.Queue(maxsize=32)

            async def __anext__(self):
                return await self.frames.get()

        speech = SpeechBank.load(Path(scripted.__file__).parent / "assets")
        for manual in (False, True):
            with self.subTest(manual=manual):
                port, audio, text = Port(), CapturingAudioOutput(), CapturingTextOutput()
                runtime = create_runtime(
                    port, ConversationBinding("browser-test"), speech, pace=False
                )
                runtime.session.output.audio = audio
                runtime.session.output.transcription = text
                source = QueueInput()
                runtime.session.input.audio = source
                await runtime.session.start(runtime.agent, record=False)
                runtime.controls.mark_ready()
                try:
                    if manual:
                        runtime.session.input.set_audio_enabled(False)
                        await runtime.controls.start_turn(invocation())
                        for _ in range(10):
                            await source.frames.put(audio_frame())
                        async with asyncio.timeout(2):
                            while runtime.recognizer.audio_seconds < 0.19:
                                await asyncio.sleep(0.01)
                        await runtime.controls.commit_turn(invocation())
                    else:
                        runtime.session.generate_reply(user_input="investigate")
                    async with asyncio.timeout(5):
                        while not (
                            ACCEPTED in "".join(text.parts)
                            and any(
                                isinstance(item, llm.ChatMessage)
                                and item.role == "assistant"
                                and ACCEPTED in (item.text_content or "")
                                for item in runtime.session.history.items
                            )
                        ):
                            await asyncio.sleep(0.01)
                    self.assertEqual(port.calls, ["submit"])
                    self.assertNotIn(GUARD, "".join(text.parts))
                    self.assertGreater(len(audio.frames), 0)
                    pcm = b"".join(frame.data.tobytes() for frame in audio.frames)
                    self.assertEqual(pcm[: len(speech.pcm(ACCEPTED))], speech.pcm(ACCEPTED))
                    self.assertTrue(any(pcm))
                    self.assertGreater(runtime.speaker.frames_emitted, 0)
                finally:
                    await runtime.aclose()

    async def test_session_interruption_and_close_do_not_invoke_business_cancellation(self):
        port = Port()
        runtime = create_runtime(port, ConversationBinding("browser-test"), bank(), pace=False)
        await runtime.session.start(runtime.agent, record=False)
        runtime.controls.mark_ready()
        async with asyncio.timeout(10):
            await runtime.session.run(user_input="investigate")
        await runtime.session.interrupt(force=True)
        await runtime.aclose()
        await runtime.aclose()
        self.assertEqual(port.calls, ["submit"])
        self.assertFalse(port.closed)  # Worker owns explicit port shutdown after report export.

    async def _native_tool(self, agent, command):
        runtime = create_runtime(
            agent._business, ConversationBinding("browser-test"), bank(), pace=False
        )
        ended = []
        completed = asyncio.Event()

        def observe(event):
            if event.update.type == "tool_call_ended":
                ended.append(event.update)
                completed.set()

        runtime.session.on("tool_execution_updated", observe)
        await runtime.session.start(agent, record=False)
        try:
            runtime.session.generate_reply(user_input=command)
            async with asyncio.timeout(5):
                await completed.wait()
            return ended[-1]
        finally:
            await runtime.aclose()

    async def test_private_port_error_is_sanitized_and_hint_failure_preserves_receipt(self):
        class PrivateError(RuntimeError):
            def __str__(self):
                raise AssertionError("Private exception text must not be read")

        port = Port()
        port.get_case = AsyncMock(side_effect=PrivateError("SECRET_SENTINEL"))
        ended = await self._native_tool(DurableAgent(port), "status")
        self.assertEqual(ended.status, "error")
        self.assertNotIn("SECRET_SENTINEL", ended.message)
        self.assertIn("inspect the workflow panel", ended.message)
        hint = AsyncMock(side_effect=PrivateError("SECRET_SENTINEL"))
        agent = DurableAgent(port, on_observation=hint)
        ended = await self._native_tool(agent, "investigate")
        self.assertEqual(ended.status, "done")
        self.assertEqual(port.calls, ["submit"])
        hint.assert_awaited_once()

    async def test_tools_propagate_cancellation_and_enforce_call_and_payload_bounds(self):
        port = Port()
        port.get_case = AsyncMock(side_effect=asyncio.CancelledError())
        ended = await self._native_tool(DurableAgent(port), "status")
        self.assertEqual(ended.status, "cancelled")
        agent = DurableAgent(port)
        agent._tool_calls = MAX_TOOL_CALLS
        ended = await self._native_tool(agent, "investigate")
        self.assertEqual(ended.status, "error")
        self.assertIn("operation limit", ended.message)
        port.get_case = AsyncMock(return_value={"value": "x" * 9000})
        ended = await self._native_tool(DurableAgent(port), "status")
        self.assertEqual(ended.status, "error")
        self.assertIn("inspect the workflow panel", ended.message)

    async def test_native_interrupt_finishes_before_held_thread_without_early_acceptance_or_lost_work(
        self,
    ):
        class HeldPort(Port):
            def __init__(self):
                super().__init__()
                self.io = BoundedAsyncIO(maximum=1, shutdown_timeout=2)
                self.entered, self.release, self.finished = (
                    threading.Event(),
                    threading.Event(),
                    threading.Event(),
                )
                self.receipt = None
                self.acceptances = 0
                self.replays = 0

            async def submit_investigation(self):
                def commit():
                    self.entered.set()
                    self.release.wait(5)
                    if self.receipt is None:
                        self.acceptances += 1
                        self.receipt = {
                            "schema_version": 1,
                            "task_id": str(uuid4()),
                            "status": "accepted",
                        }
                    else:
                        self.replays += 1
                    self.finished.set()
                    return dict(self.receipt)

                return await self.io._run(commit)

            async def aclose(self):
                await self.io.close()
                await super().aclose()

        port, receipts = HeldPort(), []

        async def observed(receipt):
            receipts.append(receipt)

        speech = SpeechBank.load(Path(scripted.__file__).parent / "assets")
        audio, text = CapturingAudioOutput(), CapturingTextOutput()
        runtime = create_runtime(
            port, ConversationBinding("browser-test"), speech, on_observation=observed, pace=False
        )
        runtime.session.output.audio = audio
        runtime.session.output.transcription = text
        terminal, updates = [], []
        runtime.session.on(
            "tool_execution_updated",
            lambda event: (
                terminal.append(event.update)
                if event.update.type == "tool_call_ended"
                else updates.append(event.update)
            ),
        )
        await runtime.session.start(runtime.agent, record=False)
        runtime.controls.mark_ready()
        try:
            self.assertEqual(
                {tool.info.name for tool in runtime.agent.tools},
                {"submit_investigation", "get_case", "cancel_case"},
            )
            self.assertTrue(
                all(tool.info.flags == llm.ToolFlag.NONE for tool in runtime.agent.tools)
            )
            runtime.session.generate_reply(user_input="investigate")
            async with asyncio.timeout(2):
                while not port.entered.is_set():
                    await asyncio.sleep(0.01)
            started = time.monotonic()
            async with asyncio.timeout(0.3):
                reply = json.loads(await runtime.controls.interrupt(invocation()))
            self.assertEqual(reply["status"], "speech_interrupted")
            self.assertLess(time.monotonic() - started, 0.3)
            self.assertFalse(port.release.is_set())
            self.assertFalse(port.finished.is_set())
            self.assertEqual(port.io.pending_count, 1)
            self.assertEqual(receipts, [])
            self.assertEqual(port.acceptances, 0)
            self.assertEqual(audio.frames, [])
            self.assertEqual(text.parts, [])
            self.assertTrue(
                any(update.type == "tool_call_updated" and update.silent for update in updates)
            )
            self.assertFalse(
                any(
                    isinstance(item, llm.ChatMessage)
                    and item.role == "assistant"
                    and ACCEPTED in (item.text_content or "")
                    for item in runtime.session.history.items
                )
            )
            with self.assertRaises(ExecutionCapacityExceeded):
                await port.io._run(lambda: "no second slot")
            self.assertEqual(port.calls, [])
            port.release.set()
            async with asyncio.timeout(5):
                while len(terminal) < 1 or not receipts:
                    await asyncio.sleep(0.01)
            self.assertEqual(terminal[-1].status, "done")
            self.assertEqual(port.acceptances, 1)
            self.assertTrue(port.finished.is_set())
            async with asyncio.timeout(5):
                while not (
                    ACCEPTED in "".join(text.parts)
                    and any(
                        isinstance(item, llm.ChatMessage)
                        and item.role == "assistant"
                        and ACCEPTED in (item.text_content or "")
                        for item in runtime.session.history.items
                    )
                ):
                    await asyncio.sleep(0.01)
            self.assertGreater(len(audio.frames), 0)
            pcm = b"".join(frame.data.tobytes() for frame in audio.frames)
            self.assertEqual(pcm[: len(speech.pcm(ACCEPTED))], speech.pcm(ACCEPTED))
            original_frames = len(audio.frames)
            runtime.session.generate_reply(user_input="investigate")
            async with asyncio.timeout(5):
                while len(terminal) < 2 or len(receipts) < 2:
                    await asyncio.sleep(0.01)
            self.assertEqual(receipts[0]["task_id"], receipts[1]["task_id"])
            self.assertEqual((port.acceptances, port.replays), (1, 1))
            self.assertEqual(port.calls, [])
            self.assertEqual(port.io.pending_count, 0)
            async with asyncio.timeout(5):
                while (
                    len(audio.frames) <= original_frames
                    or sum(
                        isinstance(item, llm.ChatMessage)
                        and item.role == "assistant"
                        and ACCEPTED in (item.text_content or "")
                        for item in runtime.session.history.items
                    )
                    < 2
                ):
                    await asyncio.sleep(0.01)
        finally:
            port.release.set()
            await runtime.aclose()
            await port.aclose()


class ControlsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session = SimpleNamespace(
            interrupt=AsyncMock(),
            clear_user_turn=Mock(),
            input=SimpleNamespace(set_audio_enabled=Mock()),
            commit_user_turn=Mock(),
            generate_reply=Mock(),
        )
        self.recognizer = ScriptedSTT()
        self.controls = ConversationControls(
            self.session, ConversationBinding("browser-test"), self.recognizer
        )
        self.controls.mark_ready()

    async def test_unready_controls_close_text_readers_and_reject_every_rpc_before_session_access(
        self,
    ):
        controls = ConversationControls(
            self.session, ConversationBinding("browser-test"), self.recognizer
        )
        reader = SimpleNamespace(close=Mock())
        controls.on_text(reader, "browser-test")
        reader.close.assert_called_once()
        for method in (controls.start_turn, controls.commit_turn, controls.interrupt):
            with self.assertRaises(rtc.RpcError) as caught:
                await method(invocation())
            self.assertEqual(caught.exception.code, 1411)
        await controls.text_input(
            self.session,
            SimpleNamespace(text="status", participant=SimpleNamespace(identity="browser-test")),
        )
        self.session.interrupt.assert_not_awaited()
        self.session.generate_reply.assert_not_called()
        self.session.input.set_audio_enabled.assert_not_called()
        await controls.aclose()
        with self.assertRaises(RuntimeError):
            controls.mark_ready()

    async def test_closed_controls_reject_late_rpc_without_touching_session(self):
        await self.controls.aclose()
        for method in (
            self.controls.start_turn,
            self.controls.commit_turn,
            self.controls.interrupt,
        ):
            with self.assertRaises(rtc.RpcError) as caught:
                await method(invocation())
            self.assertEqual(caught.exception.code, 1410)
        self.session.interrupt.assert_not_awaited()
        self.session.input.set_audio_enabled.assert_not_called()

    async def test_rpc_rejects_foreign_participant_malformed_version_and_oversize_before_session_access(
        self,
    ):
        for data in (
            invocation("browser-other"),
            invocation(payload="secret"),
            invocation(payload='{"schema_version":true}'),
            invocation(payload='{"schema_version":1,"scope_id":"forged"}'),
            invocation(payload="x" * 129),
        ):
            with self.subTest(payload_length=len(data.payload)), self.assertRaises(rtc.RpcError):
                await self.controls.start_turn(data)
        self.session.interrupt.assert_not_awaited()
        self.session.clear_user_turn.assert_not_called()

    async def test_manual_turn_start_commit_and_duplicate_start_are_explicit(self):
        result = json.loads(await self.controls.start_turn(invocation()))
        self.assertEqual(result["status"], "turn_started")
        with self.assertRaises(rtc.RpcError):
            await self.controls.start_turn(invocation())

        async def commit(**_kwargs):
            self.recognizer.turns += 1
            return "investigate"

        self.session.commit_user_turn = commit
        result = json.loads(await self.controls.commit_turn(invocation()))
        self.assertEqual(result["status"], "turn_committed")
        self.assertFalse(self.controls.audio_active)
        self.assertEqual(self.session.input.set_audio_enabled.call_args_list[-1].args, (False,))
        with self.assertRaises(rtc.RpcError):
            await self.controls.commit_turn(invocation())

    async def test_silence_and_output_interruption_have_no_business_cancel_authority(self):
        await self.controls.start_turn(invocation())
        future = asyncio.get_running_loop().create_future()
        future.set_result("")
        self.session.commit_user_turn.return_value = future
        self.assertEqual(
            json.loads(await self.controls.commit_turn(invocation()))["status"], "no_audio"
        )
        self.assertEqual(
            json.loads(await self.controls.interrupt(invocation()))["status"], "speech_interrupted"
        )
        self.assertFalse(hasattr(self.session, "cancel_case"))
        self.controls.rpc_commands = MAX_RPC_COMMANDS
        with self.assertRaises(rtc.RpcError):
            await self.controls.interrupt(invocation())

    async def test_text_input_is_bounded_and_participant_bound(self):
        for caller, text in [
            ("browser-other", "investigate"),
            ("browser-test", "x" * (MAX_TEXT_BYTES + 1)),
        ]:
            await self.controls.text_input(
                self.session,
                SimpleNamespace(text=text, participant=SimpleNamespace(identity=caller)),
            )
        self.session.generate_reply.assert_not_called()
        await self.controls.text_input(
            self.session,
            SimpleNamespace(text="status", participant=SimpleNamespace(identity="browser-test")),
        )
        self.session.generate_reply.assert_called_once_with(user_input="status")

    async def test_hint_is_small_owned_destination_and_never_authorizes_state(self):
        room = SimpleNamespace(local_participant=SimpleNamespace(publish_data=AsyncMock()))
        task = str(uuid4())
        await worker.publish_observation(
            room, {"task_id": task, "status": "accepted"}, "browser-test"
        )
        args = room.local_participant.publish_data.call_args
        self.assertEqual(json.loads(args.args[0]), {"schema_version": 1, "task_id": task})
        self.assertEqual(args.kwargs["topic"], "continuity.observed")
        self.assertEqual(args.kwargs["destination_identities"], ["browser-test"])
        for bad in (None, "not-an-id", 123):
            await worker.publish_observation(room, {"task_id": bad}, "browser-test")
        self.assertEqual(room.local_participant.publish_data.await_count, 1)

    async def test_stream_reader_enforces_byte_capacity_caller_and_closes_every_reader(self):
        class Reader:
            def __init__(self, chunks):
                self.chunks = chunks
                self.closed = False

            def __aiter__(self):
                return self.iterate()

            async def iterate(self):
                for chunk in self.chunks:
                    await asyncio.sleep(0)
                    yield chunk

            def close(self):
                self.closed = True

        room = SimpleNamespace(
            local_participant=SimpleNamespace(
                register_rpc_method=Mock(), unregister_rpc_method=Mock()
            ),
            register_text_stream_handler=Mock(),
            unregister_text_stream_handler=Mock(),
            remote_participants={"browser-test": SimpleNamespace(identity="browser-test")},
        )
        self.controls.register(room)
        valid = Reader(["sta", "tus"])
        foreign = Reader(["investigate"])
        large = Reader(["x" * 4097])
        self.controls.on_text(foreign, "browser-other")
        self.assertTrue(foreign.closed)
        self.controls.on_text(valid, "browser-test")
        self.controls.on_text(large, "browser-test")
        await asyncio.gather(*tuple(self.controls._readers))
        self.assertTrue(valid.closed)
        self.assertTrue(large.closed)
        self.session.generate_reply.assert_called_once_with(user_input="status")
        self.controls.unregister(room)
        room.unregister_text_stream_handler.assert_called_once_with("lk.chat")

    async def test_reader_capacity_and_close_cancel_owned_readers_without_tool_dispatch(self):
        class HeldReader:
            def __init__(self):
                self.closed = False

            def __aiter__(self):
                return self

            async def __anext__(self):
                await asyncio.Event().wait()

            def close(self):
                self.closed = True

        first, second, rejected = HeldReader(), HeldReader(), HeldReader()
        self.controls.on_text(first, "browser-test")
        self.controls.on_text(second, "browser-test")
        self.controls.on_text(rejected, "browser-test")
        self.assertTrue(rejected.closed)
        self.assertEqual(len(self.controls._readers), 2)
        await asyncio.sleep(0)
        await self.controls.aclose()
        self.assertTrue(first.closed and second.closed)
        self.assertEqual(self.controls._readers, set())
        self.session.generate_reply.assert_not_called()


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_assignment_is_counted_and_acceptance_is_serialized(self):
        active = []
        entered = asyncio.Event()
        release = asyncio.Event()

        async def accept(**_kwargs):
            entered.set()
            await release.wait()
            active.append(object())

        request = SimpleNamespace(
            room=SimpleNamespace(name="business-test"),
            accept=AsyncMock(side_effect=accept),
            reject=AsyncMock(),
        )
        other = SimpleNamespace(
            room=SimpleNamespace(name="business-other"), accept=AsyncMock(), reject=AsyncMock()
        )
        admission = worker.JobAdmission()
        with (
            patch.object(worker, "server", SimpleNamespace(active_jobs=active)),
            patch.object(worker, "admission", admission),
            patch.object(worker, "configure_logging"),
        ):
            first = asyncio.create_task(admission.accept(request))
            await entered.wait()
            second = asyncio.create_task(admission.accept(other))
            await asyncio.sleep(0)
            self.assertEqual(worker.calculate_load(SimpleNamespace(active_jobs=active)), 1)
            other.accept.assert_not_awaited()
            release.set()
            await asyncio.gather(first, second)
        request.accept.assert_awaited_once()
        other.reject.assert_awaited_once_with(terminate=False)
        self.assertEqual(admission.pending, 0)

    async def test_admission_failure_releases_pending_and_invalid_room_never_accepts(self):
        admission = worker.JobAdmission()
        request = SimpleNamespace(
            room=SimpleNamespace(name="lab-existing"), accept=AsyncMock(), reject=AsyncMock()
        )
        with patch.object(worker, "configure_logging"):
            await admission.accept(request)
        request.reject.assert_awaited_once()
        request.accept.assert_not_awaited()
        request.room.name = "business-test"
        request.accept = AsyncMock(side_effect=RuntimeError("private"))
        with (
            patch.object(worker, "server", SimpleNamespace(active_jobs=[])),
            patch.object(worker, "configure_logging"),
            self.assertRaises(RuntimeError),
        ):
            await admission.accept(request)
        self.assertEqual(admission.pending, 0)

    def test_prewarm_loads_bounded_spoken_bank_and_callbacks_are_importable(self):
        proc = SimpleNamespace(userdata={})
        with patch.object(worker, "configure_logging"):
            worker.prewarm(proc)
        self.assertIsInstance(proc.userdata["speech_bank"], SpeechBank)
        callbacks = (
            worker.conversation_session,
            worker.accept_business_job,
            worker.calculate_load,
            worker.prewarm,
        )
        self.assertEqual(tuple(pickle.loads(pickle.dumps(callbacks))), callbacks)
        self.assertTrue(
            all(fn.__module__ == "services.conversation_agent.worker" for fn in callbacks)
        )

    def test_worker_callbacks_deserialize_in_a_fresh_spawn_style_interpreter(self):
        callbacks = (
            worker.conversation_session,
            worker.accept_business_job,
            worker.calculate_load,
            worker.prewarm,
        )
        with tempfile.TemporaryDirectory() as temp:
            payload = Path(temp) / "callbacks.pickle"
            payload.write_bytes(pickle.dumps(callbacks))
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import pickle,sys; value=pickle.load(open(sys.argv[1], 'rb')); "
                        "assert len(value)==4; "
                        "assert all(v.__module__=='services.conversation_agent.worker' for v in value)"
                    ),
                    str(payload),
                ],
                env=os.environ.copy(),
                check=False,
                capture_output=True,
                timeout=20,
            )
        self.assertEqual(result.returncode, 0, result.stderr.decode())

    async def test_closed_session_ends_connected_sdk_job_after_independent_cleanup_exactly_once(
        self,
    ):
        events = []
        port = Port()
        port.aclose = AsyncMock(side_effect=lambda: events.append("port"))
        observer = SimpleNamespace(
            aclose=AsyncMock(side_effect=lambda *_: events.append("observer"))
        )
        room_callbacks = {}
        callbacks = []
        room = SimpleNamespace(
            name="business-test", on=lambda name, fn: room_callbacks.update({name: fn})
        )
        session_callbacks = {}
        native = SimpleNamespace(on=lambda name, fn: session_callbacks.update({name: fn}))
        controls = SimpleNamespace(
            unregister=Mock(side_effect=lambda *_: events.append("unregister"))
        )

        async def start(_room):
            events.append("start")
            # The primary session closes while its JobContext room still lives.
            # Only ctx.shutdown resolves the SDK job future in this situation.
            session_callbacks["close"](None)

        runtime = SimpleNamespace(
            inference_mode="scripted",
            session=native,
            controls=controls,
            start=start,
            aclose=AsyncMock(side_effect=lambda: events.append("native")),
        )
        composition = ModuleType("services.conversation_agent.composition")
        composition.SessionBusinessPort = type("UnboundSessionBusinessPort", (), {})
        composition.create_port = AsyncMock(
            return_value=(port, ConversationBinding("browser-test"))
        )
        composition.observe_session = Mock(return_value=observer)
        ctx = SimpleNamespace(
            job=SimpleNamespace(metadata="signed-wrapper"),
            room=room,
            proc=SimpleNamespace(userdata={"speech_bank": bank()}),
            connect=AsyncMock(),
            add_shutdown_callback=callbacks.append,
            shutdown=Mock(side_effect=lambda **_: events.append("shutdown")),
        )
        with (
            patch.dict(sys.modules, {"services.conversation_agent.composition": composition}),
            patch.object(worker, "configure_logging"),
            patch.object(worker, "create_runtime", return_value=runtime),
        ):
            await worker.conversation_session(ctx)
            await callbacks[0]()
        self.assertEqual(events, ["start", "native", "unregister", "observer", "port", "shutdown"])
        ctx.shutdown.assert_called_once_with(reason="Local scripted conversation ended")
        observer.aclose.assert_awaited_once_with(native, ctx)
        self.assertEqual(port.calls, [])

    async def test_cleanup_failure_is_visible_and_other_resources_are_still_closed(self):
        port = Port()
        observer = SimpleNamespace(aclose=AsyncMock(side_effect=RuntimeError("private")))
        callbacks = {}
        room = SimpleNamespace(
            name="business-test", on=lambda name, fn: callbacks.update({name: fn})
        )

        async def start(_room):
            callbacks["disconnected"]()

        runtime = SimpleNamespace(
            inference_mode="scripted",
            session=SimpleNamespace(on=Mock()),
            controls=SimpleNamespace(unregister=Mock()),
            start=start,
            aclose=AsyncMock(side_effect=RuntimeError("private")),
        )
        composition = ModuleType("services.conversation_agent.composition")
        composition.SessionBusinessPort = type("UnboundSessionBusinessPort", (), {})
        composition.create_port = AsyncMock(
            return_value=(port, ConversationBinding("browser-test"))
        )
        composition.observe_session = Mock(return_value=observer)
        ctx = SimpleNamespace(
            job=SimpleNamespace(metadata="signed-wrapper"),
            room=room,
            proc=SimpleNamespace(userdata={"speech_bank": bank()}),
            connect=AsyncMock(),
            add_shutdown_callback=Mock(),
            shutdown=Mock(),
        )
        with (
            patch.dict(sys.modules, {"services.conversation_agent.composition": composition}),
            patch.object(worker, "configure_logging"),
            patch.object(worker, "create_runtime", return_value=runtime),
            self.assertRaises(worker.ConversationCleanupIncomplete),
        ):
            await worker.conversation_session(ctx)
        self.assertTrue(port.closed)
        observer.aclose.assert_awaited_once()
        runtime.controls.unregister.assert_called_once()
        self.assertEqual(port.calls, [])

    async def _exercise_cancelled_cleanup(self, resource, body_error=None):
        events = []
        cancellation = asyncio.CancelledError("private-cleanup-cancellation")
        port = Port()
        port.aclose = AsyncMock(side_effect=lambda: events.append("port"))
        observer = SimpleNamespace(
            aclose=AsyncMock(side_effect=lambda *_: events.append("observer"))
        )
        room_callbacks = {}
        room = SimpleNamespace(
            name="business-test", on=lambda name, fn: room_callbacks.update({name: fn})
        )

        async def start(_room):
            if body_error is not None:
                raise body_error
            room_callbacks["disconnected"]()

        runtime = SimpleNamespace(
            inference_mode="scripted",
            session=SimpleNamespace(on=Mock()),
            controls=SimpleNamespace(
                unregister=Mock(side_effect=lambda *_: events.append("unregister"))
            ),
            start=start,
            aclose=AsyncMock(side_effect=lambda: events.append("native")),
        )
        if resource == "native":
            runtime.aclose.side_effect = cancellation
        else:
            observer.aclose.side_effect = cancellation
        composition = ModuleType("services.conversation_agent.composition")
        composition.SessionBusinessPort = type("UnboundSessionBusinessPort", (), {})
        composition.create_port = AsyncMock(
            return_value=(port, ConversationBinding("browser-test"))
        )
        composition.observe_session = Mock(return_value=observer)
        ctx = SimpleNamespace(
            job=SimpleNamespace(metadata="signed-wrapper"),
            room=room,
            proc=SimpleNamespace(userdata={"speech_bank": bank()}),
            connect=AsyncMock(),
            add_shutdown_callback=Mock(),
            shutdown=Mock(),
        )
        expected = body_error if body_error is not None else cancellation
        with (
            patch.dict(sys.modules, {"services.conversation_agent.composition": composition}),
            patch.object(worker, "configure_logging"),
            patch.object(worker, "create_runtime", return_value=runtime),
            self.assertRaises(type(expected)) as observed,
        ):
            await worker.conversation_session(ctx)
        self.assertIs(observed.exception, expected)
        runtime.controls.unregister.assert_called_once()
        observer.aclose.assert_awaited_once()
        port.aclose.assert_awaited_once()
        self.assertEqual(events[-1], "port")
        ctx.shutdown.assert_called_once_with(reason="Local scripted conversation ended")
        self.assertEqual(port.calls, [])

    async def test_cancelled_native_and_observer_cleanup_still_close_other_resources_then_propagate(
        self,
    ):
        for resource in ("native", "observer"):
            with self.subTest(resource=resource):
                await self._exercise_cancelled_cleanup(resource)

    async def test_cleanup_cancellation_preserves_an_original_body_failure_or_cancellation(self):
        for original in (
            RuntimeError("private-body-failure"),
            asyncio.CancelledError("private-body-cancellation"),
        ):
            with self.subTest(error_kind=type(original).__name__):
                await self._exercise_cancelled_cleanup("native", body_error=original)

    def test_logging_never_formats_private_messages_chains_or_untrusted_metadata(self):
        class Private:
            def __str__(self):
                raise AssertionError("Private text accessed")

        formatter = telemetry._SafeFormatter()
        for name, level, event in (
            ("livekit.agents", logging.ERROR, "sdk_error"),
            ("opentelemetry.attributes", logging.WARNING, "sdk_warning"),
        ):
            with self.subTest(namespace=name):
                record = logging.LogRecord(name, level, "unused", 1, Private(), (), None)
                record.api_secret = "SECRET_SENTINEL"
                record.job_id = "SECRET_SENTINEL"
                record.room_id = "SECRET_SENTINEL"
                record.room = "SECRET_SENTINEL"
                record.agent_name = "SECRET_SENTINEL"
                record.exc_info = (RuntimeError, RuntimeError("SECRET_SENTINEL"), None)
                result = formatter.format(record)
                self.assertEqual(json.loads(result)["event"], event)
                self.assertNotIn("SECRET_SENTINEL", result)
        record = logging.LogRecord(
            "services.conversation_agent", logging.INFO, "unused", 1, Private(), (), None
        )
        record.event = []
        record.code = "SECRET_SENTINEL"
        result = formatter.format(record)
        self.assertNotIn("SECRET_SENTINEL", result)
        self.assertEqual(json.loads(result)["code"], "unexpected_error")

    def test_otel_warning_uses_owned_json_handler_without_private_fields_or_root_propagation(self):
        class Private:
            def __str__(self):
                raise AssertionError("Private OTel warning text was accessed")

        names = ("services.conversation_agent", "livekit", "livekit.agents", "opentelemetry")
        prior = {
            name: (
                logging.getLogger(name).handlers[:],
                logging.getLogger(name).level,
                logging.getLogger(name).propagate,
            )
            for name in names
        }
        root = logging.getLogger()
        root_handler = logging.Handler()
        root_handler.emit = Mock()
        root.addHandler(root_handler)
        output = io.StringIO()
        child = logging.getLogger("opentelemetry.attributes")
        try:
            with (
                patch.object(child, "level", logging.NOTSET),
                patch.object(child, "propagate", True),
                patch.object(child, "handlers", []),
                redirect_stderr(output),
            ):
                telemetry.configure_logging()
                telemetry.configure_logging()
                child.warning(
                    "Private OTel warning: %s",
                    Private(),
                    exc_info=(RuntimeError, RuntimeError("SECRET_SENTINEL"), None),
                    extra={
                        "job_id": "SECRET_SENTINEL",
                        "room_id": "SECRET_SENTINEL",
                        "room": "SECRET_SENTINEL",
                        "agent_name": "SECRET_SENTINEL",
                    },
                )
                self.assertFalse(logging.getLogger("opentelemetry").propagate)
                self.assertEqual(len(logging.getLogger("opentelemetry").handlers), 1)
        finally:
            root.removeHandler(root_handler)
            for name, (handlers, level, propagate) in prior.items():
                logger = logging.getLogger(name)
                logger.handlers = handlers
                logger.setLevel(level)
                logger.propagate = propagate
        root_handler.emit.assert_not_called()
        value = json.loads(output.getvalue())
        self.assertEqual(set(value), {"service", "timestamp", "severity", "event", "code"})
        self.assertEqual(value["service"], "conversation-agent")
        self.assertEqual(value["severity"], "warning")
        self.assertEqual((value["event"], value["code"]), ("sdk_warning", "sdk_warning"))
        self.assertNotIn("SECRET_SENTINEL", output.getvalue())
        self.assertNotIn("Traceback", output.getvalue())

    def test_native_sdk_failure_catalog_preserves_location_and_builtin_type_without_content(self):
        class PrivateError(RuntimeError):
            def __str__(self):
                raise AssertionError("Private failure text must not be read")

        formatter = telemetry._SafeFormatter()
        for module, function, error_type, code in (
            ("worker", "_job_request_task", TimeoutError, "sdk_assignment_timeout"),
            ("proc_pool", "_proc_spawn_task", RuntimeError, "sdk_process_initialize_runtime"),
            ("job_proc_lazy_main", "_on_entry_done", ValueError, "sdk_job_entry_value"),
            ("job_proc_lazy_main", "_shutdown_job", AttributeError, "sdk_job_shutdown_attribute"),
            ("job_proc_lazy_main", "_shutdown_job", PrivateError, "sdk_job_shutdown_other"),
            ("supervised_proc", "_memory_monitor_task", None, "sdk_process_memory_none"),
            ("SECRET_SENTINEL", "SECRET_SENTINEL", PrivateError, "sdk_error"),
        ):
            with self.subTest(expected=code):
                record = logging.LogRecord(
                    "livekit.agents", logging.ERROR, "unused", 1, PrivateError(), (), None
                )
                record.module, record.funcName = module, function
                record.exc_info = None if error_type is None else (error_type, PrivateError(), None)
                record.job_request = "SECRET_SENTINEL"
                value = json.loads(formatter.format(record))
                self.assertEqual(value["event"], "sdk_error")
                self.assertEqual(value["code"], code)
                self.assertIn(value["code"], telemetry.CODES)
                self.assertEqual(set(value), {"service", "timestamp", "severity", "event", "code"})
                self.assertNotIn("SECRET_SENTINEL", json.dumps(value))

    def test_transcription_warning_catalog_reads_only_exact_builtin_argument_types(self):
        class PrivateError(RuntimeError):
            def __str__(self):
                raise AssertionError("Private warning text must not be read")

            def __repr__(self):
                raise AssertionError("Private warning repr must not be read")

        formatter = telemetry._SafeFormatter()
        cases = (
            (
                "_output",
                "capture_text",
                (AttributeError("SECRET_SENTINEL"),),
                "sdk_transcription_capture_attribute",
            ),
            (
                "_output",
                "_flush_task",
                (TypeError("SECRET_SENTINEL"),),
                "sdk_transcription_flush_type",
            ),
            (
                "_output",
                "_publish_transcription",
                (RuntimeError("SECRET_SENTINEL"),),
                "sdk_transcription_publish_runtime",
            ),
            ("_output", "capture_text", (PrivateError(),), "sdk_transcription_capture_other"),
            ("_output", "capture_text", (), "sdk_transcription_capture_none"),
            (
                "_output",
                "capture_text",
                {"private": PrivateError()},
                "sdk_transcription_capture_none",
            ),
            ("SECRET_SENTINEL", "SECRET_SENTINEL", (PrivateError(),), "sdk_warning"),
        )
        for module, function, arguments, code in cases:
            with self.subTest(expected=code):
                record = logging.LogRecord(
                    "livekit.agents", logging.WARNING, "unused", 1, PrivateError(), (), None
                )
                record.module, record.funcName, record.args = module, function, arguments
                record.exc_info = (RuntimeError, PrivateError(), None)
                record.job_id = record.room = record.api_secret = "SECRET_SENTINEL"
                encoded = formatter.format(record)
                value = json.loads(encoded)
                self.assertEqual(set(value), {"service", "timestamp", "severity", "event", "code"})
                self.assertEqual((value["event"], value["code"]), ("sdk_warning", code))
                self.assertIn(code, telemetry.CODES)
                self.assertNotIn("SECRET_SENTINEL", encoded)

    def test_logging_outage_cannot_change_business_lifecycle(self):
        with patch.object(telemetry.LOGGER, "log", side_effect=RuntimeError("private")):
            telemetry.emit("session_started", "accepted")
