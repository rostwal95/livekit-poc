"""Native tools and bounded room controls around one authenticated business port."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from livekit import rtc
from livekit.agents import (
    Agent,
    AgentSession,
    RunContext,
    SessionConnectOptions,
    ToolError,
    function_tool,
    room_io,
    tts,
)
from livekit.agents.types import APIConnectOptions

from .scripted import (
    DEMO,
    MAX_TEXT_BYTES,
    ScriptedLLM,
    ScriptedSTT,
    ScriptedTTS,
    SpeechBank,
)
from .telemetry import emit

MAX_TOOL_CALLS = 32
MAX_TEXT_TURNS = 32
MAX_RPC_COMMANDS = 64
MEDIA_READY_TIMEOUT_SECONDS = 10
SESSION_READY_ATTRIBUTE = "continuity.session_ready"
RPC_METHODS = ("business.start_turn", "business.commit_turn", "business.interrupt")
Receipt = dict[str, object]
ObservationHook = Callable[[Receipt], Awaitable[None]]


class BusinessPort(Protocol):
    """Trusted composition binds owner, request key and current task internally."""

    async def submit_investigation(self) -> Receipt: ...
    async def get_case(self) -> Receipt: ...
    async def cancel_case(self) -> Receipt: ...
    async def aclose(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ConversationBinding:
    expected_participant: str

    def __post_init__(self) -> None:
        value = self.expected_participant
        if (
            type(value) is not str
            or not value.startswith(("browser-", "smoke-"))
            or not 8 <= len(value) <= 128
            or value != value.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
        ):
            raise ValueError("A verified bounded browser participant binding is required")


class ManualTurnCounter(Protocol):
    turns: int


class DurableAgent(Agent):
    """Tools receive no scope, actor, task or confirmation arguments from a model."""

    def __init__(
        self,
        port: BusinessPort,
        *,
        on_observation: ObservationHook | None = None,
        inference_mode: Literal["scripted", "local_real", "provider_real"] = "scripted",
    ) -> None:
        if inference_mode not in {"scripted", "local_real", "provider_real"}:
            raise ValueError("Invalid conversation inference mode")
        if inference_mode == "provider_real":
            from .provider_settings import PROVIDER_INSTRUCTIONS

            instructions = PROVIDER_INSTRUCTIONS
        elif inference_mode == "local_real":
            from .inference_settings import LOCAL_INSTRUCTIONS

            instructions = LOCAL_INSTRUCTIONS
        else:
            instructions = "You are a scripted local workflow assistant. Use only the offered investigation, inspection and explicit cancellation tools. A model statement never confirms a booking change. Exact quote confirmation happens only in the authenticated workflow panel."
        super().__init__(instructions=instructions)
        self._business = port
        self._on_observation = on_observation
        self._tool_calls = 0

    async def _call(
        self, operation: Callable[[], Awaitable[Receipt]], ctx: RunContext[None]
    ) -> Receipt:
        if self._tool_calls >= MAX_TOOL_CALLS:
            raise ToolError("The local conversation operation limit was reached.")
        self._tool_calls += 1
        try:
            # This is an SDK-owned async tool, not a business acceptance. The
            # silent update releases the speech turn while the adapter retains
            # the actual operation/capacity until its real receipt is available.
            await ctx.update({"schema_version": 1, "status": "pending"}, silent=True)
            result = await operation()
            if (
                type(result) is not dict
                or len(json.dumps(result, allow_nan=False).encode("utf-8")) > 8192
            ):
                raise ValueError("Invalid business receipt")
        except Exception:  # noqa: BLE001 - sanitized SDK-facing privacy boundary
            raise ToolError(
                "The operation could not be completed; inspect the workflow panel."
            ) from None
        if self._on_observation is not None:
            try:
                async with asyncio.timeout(1):
                    await self._on_observation(result)
            except Exception:  # noqa: BLE001,S110 - optional hint cannot change business truth
                pass
        return result

    @function_tool(
        name="submit_investigation",
        description="Accept the already authorized investigation for this conversation; never changes a booking.",
    )
    async def submit_investigation(self, ctx: RunContext[None]) -> Receipt:
        return await self._call(self._business.submit_investigation, ctx)

    @function_tool(
        name="get_case", description="Inspect the current owned investigation from durable state."
    )
    async def get_case(self, ctx: RunContext[None]) -> Receipt:
        return await self._call(self._business.get_case, ctx)

    @function_tool(
        name="cancel_case",
        description="Record an explicit request to cancel the current owned investigation; cancellation may be best effort.",
    )
    async def cancel_case(self, ctx: RunContext[None]) -> Receipt:
        return await self._call(self._business.cancel_case, ctx)


class ConversationControls:
    """Manual turn control is bound to the participant minted by the server."""

    def __init__(
        self,
        session: AgentSession[None],
        binding: ConversationBinding,
        recognizer: ManualTurnCounter,
        *,
        transcript_timeout: float = 2.0,
        commit_timeout: float = 3.0,
    ) -> None:
        if (transcript_timeout, commit_timeout) not in {(2.0, 3.0), (10.0, 11.0)} or any(
            type(value) not in {int, float} for value in (transcript_timeout, commit_timeout)
        ):
            raise ValueError("Invalid conversation turn budgets")
        self.transcript_timeout, self.commit_timeout = transcript_timeout, commit_timeout
        self.session, self.binding, self.recognizer = session, binding, recognizer
        self.rpc_commands = 0
        self.text_turns = 0
        self.audio_active = False
        self._lock = asyncio.Lock()
        self._room: rtc.Room | None = None
        self._readers: set[asyncio.Task[None]] = set()
        self._registered_text = False
        self._closed = False
        self._ready = False

    def mark_ready(self) -> None:
        """Called only after the public SDK RoomIO readiness barrier succeeds."""
        if self._closed:
            raise RuntimeError("The local conversation has closed")
        self._ready = True

    def _authorize(self, caller: str, payload: str) -> None:
        if self._closed:
            raise rtc.RpcError(1410, "The local conversation has closed")
        if caller != self.binding.expected_participant:
            raise rtc.RpcError(1403, "This participant cannot control the conversation")
        if type(payload) is not str or len(payload.encode("utf-8")) > 128:
            raise rtc.RpcError(1400, "Invalid local conversation control")
        try:
            value = json.loads(payload)
        except (ValueError, TypeError):
            raise rtc.RpcError(1400, "Invalid local conversation control") from None
        if (
            type(value) is not dict
            or set(value) != {"schema_version"}
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 1
        ):
            raise rtc.RpcError(1400, "Invalid local conversation control")
        if not self._ready:
            raise rtc.RpcError(1411, "The local media session is not ready")
        if self.rpc_commands >= MAX_RPC_COMMANDS:
            raise rtc.RpcError(1429, "The local conversation control limit was reached")
        self.rpc_commands += 1

    async def start_turn(self, data: rtc.RpcInvocationData) -> str:
        self._authorize(data.caller_identity, data.payload)
        if self._lock.locked() or self.audio_active:
            raise rtc.RpcError(1409, "An audio turn is already active")
        async with self._lock:
            async with asyncio.timeout(3):
                await self.session.interrupt(force=True)
            self.session.clear_user_turn()
            self.session.input.set_audio_enabled(True)
            self.audio_active = True
        return json.dumps({"schema_version": 1, "status": "turn_started"})

    async def commit_turn(self, data: rtc.RpcInvocationData) -> str:
        self._authorize(data.caller_identity, data.payload)
        if self._lock.locked() or not self.audio_active:
            raise rtc.RpcError(1409, "No audio turn is active")
        async with self._lock:
            self.session.input.set_audio_enabled(False)
            self.audio_active = False
            previous = self.recognizer.turns
            async with asyncio.timeout(self.commit_timeout):
                await self.session.commit_user_turn(
                    transcript_timeout=self.transcript_timeout, stt_flush_duration=0.1
                )
            status = "turn_committed" if self.recognizer.turns > previous else "no_audio"
        return json.dumps({"schema_version": 1, "status": status})

    async def interrupt(self, data: rtc.RpcInvocationData) -> str:
        self._authorize(data.caller_identity, data.payload)
        async with asyncio.timeout(3):
            await self.session.interrupt(force=True)
        return json.dumps({"schema_version": 1, "status": "speech_interrupted"})

    async def text_input(self, session: AgentSession[None], event: room_io.TextInputEvent) -> None:
        if (
            self._closed
            or not self._ready
            or event.participant is None
            or event.participant.identity != self.binding.expected_participant
        ):
            return
        if (
            type(event.text) is not str
            or not event.text
            or len(event.text.encode("utf-8")) > MAX_TEXT_BYTES
            or self.text_turns >= MAX_TEXT_TURNS
        ):
            return
        self.text_turns += 1
        async with asyncio.timeout(3):
            await session.interrupt(force=True)
        session.generate_reply(user_input=event.text)

    def on_text(self, reader: rtc.TextStreamReader, identity: str) -> None:
        if (
            self._closed
            or not self._ready
            or identity != self.binding.expected_participant
            or len(self._readers) >= 2
            or self.text_turns >= MAX_TEXT_TURNS
        ):
            reader.close()
            return
        task = asyncio.create_task(
            self._read_text(reader, identity), name="conversation-text-reader"
        )
        self._readers.add(task)

        def completed(finished: asyncio.Task[None]) -> None:
            self._readers.discard(finished)
            if not finished.cancelled():
                finished.exception()

        task.add_done_callback(completed)

    async def _read_text(self, reader: rtc.TextStreamReader, identity: str) -> None:
        chunks: list[str] = []
        size = 0
        try:
            async with asyncio.timeout(3):
                async for chunk in reader:
                    if type(chunk) is not str:
                        raise ValueError("Invalid conversation text")
                    size += len(chunk.encode("utf-8"))
                    if size > MAX_TEXT_BYTES:
                        raise ValueError("Conversation text exceeds its bound")
                    chunks.append(chunk)
            if self._room is not None:
                await self.text_input(
                    self.session,
                    room_io.TextInputEvent(
                        text="".join(chunks),
                        participant=self._room.remote_participants.get(identity),
                    ),
                )
        except Exception:  # noqa: BLE001 - transport errors are fixed, payload-free observations
            emit("input_rejected", "invalid_input")
        finally:
            reader.close()

    async def aclose(self) -> None:
        self._closed = True
        self._ready = False
        pending = tuple(self._readers)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._readers.clear()

    def register(self, room: rtc.Room) -> None:
        self._room = room
        room.register_text_stream_handler("lk.chat", self.on_text)
        self._registered_text = True
        for name, handler in zip(
            RPC_METHODS, (self.start_turn, self.commit_turn, self.interrupt), strict=True
        ):
            room.local_participant.register_rpc_method(name, handler)

    def unregister(self, room: rtc.Room) -> None:
        if self._registered_text:
            room.unregister_text_stream_handler("lk.chat")
            self._registered_text = False
        for name in RPC_METHODS:
            room.local_participant.unregister_rpc_method(name)


@dataclass
class ConversationRuntime:
    session: AgentSession[None]
    agent: DurableAgent
    controls: ConversationControls
    recognizer: ManualTurnCounter
    speaker: tts.TTS[Any]
    greeting: str = DEMO
    inference_mode: Literal["scripted", "local_real", "provider_real"] = "scripted"
    _closed: bool = field(default=False, init=False)

    async def start(self, room: rtc.Room) -> None:
        self.controls.register(room)
        await self.session.start(
            self.agent,
            room=room,
            # Only the owned caller-bound RPC/text ports may drive this session.
            # The SDK RemoteSession host installs a separate unbound byte ingress.
            session_host=False,
            room_options=room_io.RoomOptions(
                participant_identity=self.controls.binding.expected_participant,
                audio_input=room_io.AudioInputOptions(
                    sample_rate=16000, num_channels=1, frame_size_ms=20, pre_connect_audio=False
                ),
                text_input=False,
                audio_output=room_io.AudioOutputOptions(sample_rate=16000, num_channels=1),
                close_on_disconnect=True,
                delete_room_on_close=False,
            ),
            record={
                "audio": False,
                "transcript": False,
                "logs": False,
                "traces": True,
                "redaction": True,
            },
        )
        # Session.start publishes its listening state before RoomIO finishes
        # participant/audio setup. Interrupting an output capture while it still
        # waits for subscription cancels a shared SDK future in the frozen SDK.
        # Use its public readiness barrier before exposing any interrupting input.
        async with asyncio.timeout(MEDIA_READY_TIMEOUT_SECONDS):
            await self.session.room_io.wait_for_ready()
            self.session.input.set_audio_enabled(False)
            self.controls.mark_ready()
            await room.local_participant.set_attributes(
                {SESSION_READY_ATTRIBUTE: "true", "continuity.inference_mode": self.inference_mode}
            )
        self.session.say(self.greeting)

    async def aclose(self) -> None:
        if self._closed:
            return
        await self.controls.aclose()
        await self.session.aclose()
        self._closed = True


def create_runtime(
    port: BusinessPort,
    binding: ConversationBinding,
    bank: SpeechBank,
    *,
    on_observation: ObservationHook | None = None,
    pace: bool = True,
) -> ConversationRuntime:
    recognizer, speaker = ScriptedSTT(), ScriptedTTS(bank, pace=pace)
    session: AgentSession[None] = AgentSession(
        stt=recognizer,
        llm=ScriptedLLM(),
        tts=speaker,
        vad=None,
        turn_handling={"turn_detection": "manual", "preemptive_generation": {"enabled": False}},
        max_tool_steps=2,
        user_away_timeout=None,
        conn_options=SessionConnectOptions(
            stt_conn_options=APIConnectOptions(max_retry=0, timeout=2),
            llm_conn_options=APIConnectOptions(max_retry=0, timeout=2),
            tts_conn_options=APIConnectOptions(max_retry=0, timeout=2),
        ),
    )
    agent = DurableAgent(port, on_observation=on_observation)
    return ConversationRuntime(
        session, agent, ConversationControls(session, binding, recognizer), recognizer, speaker
    )
