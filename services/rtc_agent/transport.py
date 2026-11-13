"""Bounded deterministic RTC diagnostics, deliberately independent of AI models."""

import asyncio
import inspect
import json
from collections.abc import Callable, Coroutine
from typing import Any

from .telemetry import emit_event, log_task_completion

MAX_TEXT_BYTES = 16_384
ECHO_PREFIX = "Echo: "
MAX_REPLY_BYTES = MAX_TEXT_BYTES + len(ECHO_PREFIX.encode("utf-8"))
MAX_TASKS = 8
MAX_AUDIO_TRACKS = 4


async def close_reader(reader):
    close = getattr(reader, "aclose", None) or getattr(reader, "close", None)
    if close is not None:
        value = close()
        if inspect.isawaitable(value):
            await value


async def read_text(reader, maximum: int = MAX_TEXT_BYTES) -> str:
    chunks, size = [], 0
    try:
        async with asyncio.timeout(10):
            async for chunk in reader:
                size += len(chunk.encode("utf-8"))
                if size > maximum:
                    raise ValueError("Text exceeds transport diagnostic limit")
                chunks.append(chunk)
        return "".join(chunks)
    finally:
        await close_reader(reader)


class BoundedTasks:
    def __init__(self, maximum: int = MAX_TASKS):
        self.maximum = maximum
        self.tasks: set[asyncio.Task] = set()

    def spawn(self, factory: Callable[[], Coroutine[Any, Any, Any]]) -> asyncio.Task | None:
        if len(self.tasks) >= self.maximum:
            return None
        task = asyncio.create_task(factory())
        self.tasks.add(task)

        def completed(finished):
            self.tasks.discard(finished)
            log_task_completion(finished, active_tasks=len(self.tasks))

        task.add_done_callback(completed)
        return task

    async def close(self):
        pending = list(self.tasks)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


class TransportDiagnostics:
    def __init__(self, room, *, audio_stream_factory=None):
        self.room = room
        self.tasks = BoundedTasks()
        self.audio_tasks: dict[str, asyncio.Task] = {}
        self.audio_stream_factory = audio_stream_factory

    async def echo(self, reader, identity: str) -> None:
        text = await read_text(reader)
        if text:
            async with asyncio.timeout(5):
                await self.room.local_participant.send_text(
                    f"{ECHO_PREFIX}{text}", topic="lk.agent.chat", destination_identities=[identity]
                )

    def on_text(self, reader, identity: str) -> None:
        if not identity.startswith(("browser-", "smoke-")):
            emit_event("stream_rejected", code="invalid_source")
            close = getattr(reader, "close", None)
            if close is not None:
                close()
            return
        task = self.tasks.spawn(lambda: self.echo(reader, identity))
        if task is None:
            emit_event("stream_rejected", code="task_capacity", active_tasks=len(self.tasks.tasks))
            # Reader.close is synchronous in the selected SDK and releases its
            # FFI subscription even when we reject the stream before consuming it.
            close = getattr(reader, "close", None)
            if close is not None:
                close()

    async def observe_audio(self, track, track_sid: str):
        if self.audio_stream_factory is None:
            from livekit import rtc

            factory = rtc.AudioStream
        else:
            factory = self.audio_stream_factory
        stream = factory(track, capacity=32, sample_rate=16000, num_channels=1, frame_size_ms=20)
        frames = 0
        try:
            async for _ in stream:
                frames += 1
                if frames % 10 == 0:
                    async with asyncio.timeout(3):
                        await self.room.local_participant.send_text(
                            json.dumps(
                                {"type": "audio.frames", "frames": frames, "track_sid": track_sid}
                            ),
                            topic="lk.agent.events",
                        )
        finally:
            await stream.aclose()
            self.audio_tasks.pop(track_sid, None)

    def on_audio(self, track, track_sid: str) -> None:
        if track_sid in self.audio_tasks:
            return
        if len(self.audio_tasks) >= MAX_AUDIO_TRACKS:
            emit_event(
                "stream_rejected", code="audio_capacity", active_audio_tracks=len(self.audio_tasks)
            )
            return
        task = self.tasks.spawn(lambda: self.observe_audio(track, track_sid))
        if task is not None:
            self.audio_tasks[track_sid] = task
        else:
            emit_event("stream_rejected", code="task_capacity", active_tasks=len(self.tasks.tasks))

    def remove_audio(self, track_sid: str):
        task = self.audio_tasks.pop(track_sid, None)
        if task is not None:
            task.cancel()

    async def close(self):
        await self.tasks.close()
        self.audio_tasks.clear()
