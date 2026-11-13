"""Streaming capture bound to an immutable application token, never mutable SDK speech state."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar, cast
from uuid import uuid4

from livekit import rtc
from livekit.agents import llm
from livekit.agents.types import FlushSentinel
from livekit.agents.voice import SpeechHandle

from .native_communication import (
    BrowserObservation,
    NativeCommunicationPort,
    ObservationReceipt,
    ResponseAnchor,
    ResponseReceipt,
    ResponseView,
    SdkObservation,
)
from .native_models import NativeBinding, NativeError, text, uuid

LOGGER = logging.getLogger(__name__)
_T = TypeVar("_T")


def _payload_digest(value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
            "utf-8"
        )
    ).hexdigest()


@dataclass(slots=True, eq=False)
class CaptureTicket:
    owner: NativeCaptureManager
    context: dict[str, object]
    generation_id: str
    response_id: str = field(default_factory=lambda: str(uuid4()))
    handle: asyncio.Future[SpeechHandle] = field(
        default_factory=lambda: asyncio.get_running_loop().create_future()
    )
    anchor: asyncio.Future[ResponseAnchor] = field(
        default_factory=lambda: asyncio.get_running_loop().create_future()
    )
    nodes: set[asyncio.Task[Any]] = field(default_factory=set)
    streams: list[_StreamingNode] = field(default_factory=list)
    generated_complete: bool = False
    sdk_failure: bool = False
    tts_calls: int = 0
    retired: bool = False

    def __post_init__(self) -> None:
        def observed(future: asyncio.Future[Any]) -> None:
            if not future.cancelled():
                future.exception()

        self.handle.add_done_callback(observed)
        self.anchor.add_done_callback(observed)


_CURRENT: ContextVar[CaptureTicket | None] = ContextVar("p2_communication_capture", default=None)


class _StreamingNode(AsyncIterator[str | FlushSentinel]):
    def __init__(
        self,
        ticket: CaptureTicket,
        factory: Callable[[], AsyncIterable[llm.ChatChunk | str | FlushSentinel]],
    ) -> None:
        self.ticket, self.factory = ticket, factory
        self.queue: asyncio.Queue[str | FlushSentinel] = asyncio.Queue(maxsize=2)
        self.changed, self.space = asyncio.Event(), asyncio.Event()
        self.space.set()
        self.stopped = False
        self.cancel_requested = False
        self.source: AsyncIterator[llm.ChatChunk | str | FlushSentinel] | None = None
        task = asyncio.current_task()
        if task is None:
            raise NativeError()
        ticket.nodes.add(task)
        task.add_done_callback(ticket.nodes.discard)
        self.producer = asyncio.create_task(self._produce(), name="communication-llm-producer")

        def settled(done: asyncio.Task[None]) -> None:
            self.changed.set()
            self.space.set()
            if not done.cancelled():
                done.exception()

        self.producer.add_done_callback(settled)

    def __aiter__(self) -> _StreamingNode:
        return self

    async def __anext__(self) -> str | FlushSentinel:
        try:
            while True:
                if self.stopped:
                    raise StopAsyncIteration
                if not self.queue.empty():
                    value = self.queue.get_nowait()
                    self.space.set()
                    return value
                if self.producer.done():
                    if self.producer.cancelled():
                        raise NativeError("dependency_unavailable")
                    await asyncio.shield(self.producer)
                    raise StopAsyncIteration
                self.changed.clear()
                if not self.queue.empty() or self.producer.done():
                    continue
                await self.changed.wait()
        except asyncio.CancelledError:
            self.request_stop()
            raise

    def request_stop(self) -> None:
        self.stopped = True
        self.changed.set()
        self.space.set()
        if not self.cancel_requested and not self.producer.done():
            self.cancel_requested = True
            self.producer.cancel()

    async def aclose(self) -> None:
        self.request_stop()
        await asyncio.shield(asyncio.gather(self.producer, return_exceptions=True))

    async def _put(self, value: str | FlushSentinel) -> None:
        while self.queue.full():
            if self.stopped:
                raise NativeError("dependency_unavailable")
            self.space.clear()
            if not self.queue.full():
                continue
            await self.space.wait()
        if self.stopped:
            raise NativeError("dependency_unavailable")
        self.queue.put_nowait(value)
        self.changed.set()

    async def _produce(self) -> None:
        pieces: list[str] = []
        size = 0
        chunks = 0
        normal = False
        try:
            handle = await asyncio.shield(self.ticket.handle)
            await asyncio.shield(self.ticket.anchor)
            if self.ticket.retired or handle.interrupted or self.ticket.owner.closed:
                raise NativeError("closed")
            source = self.factory()
            if not isinstance(source, AsyncIterable):
                raise NativeError()
            self.source = source.__aiter__()
            try:
                while True:
                    while self.queue.full():
                        if self.stopped:
                            raise NativeError("dependency_unavailable")
                        self.space.clear()
                        if not self.queue.full():
                            continue
                        await self.space.wait()
                    if self.stopped:
                        raise NativeError("dependency_unavailable")
                    try:
                        chunk = await anext(self.source)
                    except StopAsyncIteration:
                        break
                    chunks += 1
                    if chunks > 256 or self.stopped:
                        raise NativeError("dependency_unavailable")
                    if isinstance(chunk, FlushSentinel):
                        await self._put(chunk)
                        continue
                    if isinstance(chunk, llm.ChatChunk):
                        if chunk.delta is None:
                            continue
                        if chunk.delta.tool_calls:
                            raise NativeError()
                        value = chunk.delta.content or ""
                    elif type(chunk) is str:
                        value = chunk
                    else:
                        raise NativeError()
                    if type(value) is not str:
                        raise NativeError()
                    try:
                        size += len(value.encode("utf-8"))
                    except UnicodeError:
                        raise NativeError() from None
                    if size > 4096:
                        raise NativeError()
                    if value:
                        pieces.append(value)
                        await self._put(value)
                normal = not self.stopped
            finally:
                close = getattr(self.source, "aclose", None)
                if close is not None:
                    result = close()
                    if inspect.isawaitable(result):
                        await result
            if not normal or self.stopped:
                raise NativeError("dependency_unavailable")
            generated = text("".join(pieces), 4096)
            await self.ticket.owner.generated(self.ticket, generated)
            self.ticket.generated_complete = True
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.ticket.sdk_failure = True
            if isinstance(error, NativeError):
                raise
            raise NativeError("dependency_unavailable") from None
        finally:
            self.changed.set()
            self.space.set()


class NativeCaptureManager:
    def __init__(
        self,
        binding: NativeBinding,
        port: NativeCommunicationPort,
        room: Callable[[], rtc.Room | None],
    ) -> None:
        self.binding, self.port, self.room = binding, port, room
        self.closed = False
        self.tickets: dict[str, CaptureTicket] = {}
        self.publications: set[asyncio.Task[Any]] = set()
        self.reports: set[asyncio.Task[ObservationReceipt]] = set()
        self.counts = {
            "anchorsKnown": 0,
            "generatedFactsKnown": 0,
            "sdkFactsKnown": 0,
            "browserReportsKnown": 0,
            "unknownAcknowledgements": 0,
            "rejectedReports": 0,
            "observerFailures": 0,
        }
        for method in (
            "begin_response",
            "observe_sdk",
            "observe_browser",
            "inspect_response",
            "aclose",
        ):
            try:
                if isinstance(inspect.getattr_static(port, method), property) or not callable(
                    getattr(port, method)
                ):
                    raise NativeError()
            except (AttributeError, TypeError):
                raise NativeError() from None

    def metrics(self) -> dict[str, int]:
        return {
            **self.counts,
            "activeNodes": sum(
                not t.done() for ticket in self.tickets.values() for t in ticket.nodes
            ),
            "activeProducers": sum(
                not stream.producer.done()
                for ticket in self.tickets.values()
                for stream in ticket.streams
            ),
            "activePublications": sum(not task.done() for task in self.publications),
            "activeReports": sum(not task.done() for task in self.reports),
        }

    def allocate(self, context: dict[str, object], generation_id: str) -> CaptureTicket:
        if self.closed:
            raise NativeError("closed")
        if len(self.tickets) >= 64 or any(not x.retired for x in self.tickets.values()):
            raise NativeError("capacity_exhausted")
        copied = dict(context)
        copied["message"] = dict(cast(dict[str, object], context["message"]))
        copied["scope"] = dict(cast(dict[str, object], context["scope"]))
        ticket = CaptureTicket(self, copied, generation_id)
        self.tickets[ticket.response_id] = ticket
        return ticket

    def invoke(self, ticket: CaptureTicket, generate: Callable[[], SpeechHandle]) -> SpeechHandle:
        if ticket.owner is not self or ticket.retired or ticket.handle.done():
            raise NativeError()
        token = _CURRENT.set(ticket)
        try:
            handle = generate()
        finally:
            _CURRENT.reset(token)
        if not isinstance(handle, SpeechHandle):
            raise NativeError()
        ticket.handle.set_result(handle)
        return handle

    def node(
        self, factory: Callable[[], AsyncIterable[llm.ChatChunk | str | FlushSentinel]]
    ) -> AsyncIterable[str | FlushSentinel]:
        ticket = _CURRENT.get()
        if (
            ticket is None
            or ticket.owner is not self
            or ticket.retired
            or self.closed
            or ticket.streams
        ):
            raise NativeError("forbidden")
        stream = _StreamingNode(ticket, factory)
        ticket.streams.append(stream)
        return stream

    def tts(
        self, factory: Callable[[], AsyncIterable[rtc.AudioFrame]]
    ) -> AsyncIterable[rtc.AudioFrame]:
        ticket = _CURRENT.get()
        if ticket is None or ticket.owner is not self or ticket.retired or self.closed:
            raise NativeError("forbidden")
        if ticket.tts_calls >= 16 or sum(not node.done() for node in ticket.nodes) >= 8:
            ticket.sdk_failure = True
            raise NativeError("capacity_exhausted")
        ticket.tts_calls += 1
        task = asyncio.current_task()
        if task is None:
            raise NativeError()
        ticket.nodes.add(task)
        task.add_done_callback(ticket.nodes.discard)

        async def captured() -> AsyncIterator[rtc.AudioFrame]:
            source = factory().__aiter__()
            try:
                async for frame in source:
                    yield frame
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - SDK source errors stay bound and fixed.
                ticket.sdk_failure = True
                raise NativeError("dependency_unavailable") from None
            finally:
                close = getattr(source, "aclose", None)
                if close is not None:
                    try:
                        result = close()
                        if inspect.isawaitable(result):
                            await result
                    except asyncio.CancelledError:
                        raise
                    except Exception:  # noqa: BLE001 - Keep actual failed-close truth.
                        ticket.sdk_failure = True
                        raise NativeError("dependency_unavailable") from None

        return captured()

    async def _publication(self, work: Callable[[], Awaitable[_T]]) -> _T:
        if len(self.publications) >= 8:
            raise NativeError("capacity_exhausted")

        async def run() -> _T:
            return await work()

        task = asyncio.create_task(run(), name="communication-publication")
        self.publications.add(task)

        def done(value: asyncio.Task[Any]) -> None:
            self.publications.discard(value)
            if not value.cancelled():
                value.exception()

        task.add_done_callback(done)
        try:
            return await asyncio.shield(task)
        except NativeError as error:
            if error.code in ("acknowledgement_unknown", "dependency_unavailable"):
                self.counts["unknownAcknowledgements"] += 1
            raise

    async def publish_anchor(self, ticket: CaptureTicket) -> None:
        handle = await asyncio.shield(ticket.handle)
        message = cast(dict[str, object], ticket.context["message"])
        anchor = ResponseAnchor(
            ticket.response_id,
            ticket.generation_id,
            handle.id,
            self.binding.binding_id,
            cast(str, message["eventId"]),
            cast(str, message["receiptId"]),
            cast(str, ticket.context["operationKey"]),
            cast(str, ticket.context["caseRevision"]),
        )
        try:
            receipt = await self._publication(lambda: self.port.begin_response(anchor))
            if type(receipt) is not ResponseReceipt or receipt.response_id != anchor.response_id:
                raise NativeError()
            self.counts["anchorsKnown"] += 1
            ticket.anchor.set_result(anchor)
            await self.mapping(ticket)
        except BaseException:
            if not ticket.anchor.done():
                ticket.anchor.set_exception(NativeError("acknowledgement_unknown"))
            handle.interrupt(force=True)
            raise

    async def generated(self, ticket: CaptureTicket, body: str) -> None:
        anchor = await asyncio.shield(ticket.anchor)
        value = SdkObservation(
            str(uuid4()),
            anchor.response_id,
            anchor.generation_id,
            anchor.sdk_speech_id,
            "generated_complete",
            text=body,
        )
        receipt = await self._publication(lambda: self.port.observe_sdk(value))
        if (
            type(receipt) is not ObservationReceipt
            or receipt.response_id != value.response_id
            or receipt.event_id != value.event_id
            or receipt.payload_digest != _payload_digest(value.payload())
        ):
            raise NativeError()
        self.counts["generatedFactsKnown"] += 1
        await self.mapping(ticket)

    async def mapping(self, ticket: CaptureTicket) -> None:
        room = self.room()
        if room is None:
            return
        try:
            view = await self._publication(lambda: self.port.inspect_response(ticket.response_id))
            if (
                type(view) is not ResponseView
                or view.binding != self.binding
                or view.anchor.response_id != ticket.response_id
            ):
                raise NativeError()
            a = view.anchor
            raw = json.dumps(
                {
                    "schemaVersion": 1,
                    "bindingId": a.binding_id,
                    "inputId": a.input_id,
                    "operationKey": a.operation_key,
                    "generationId": a.generation_id,
                    "responseId": a.response_id,
                    "sdkSpeechId": a.sdk_speech_id,
                    "observationCount": view.observation_count,
                },
                separators=(",", ":"),
            ).encode()
            if len(raw) > 2048:
                raise NativeError()
            async with asyncio.timeout(1):
                await room.local_participant.publish_data(
                    raw,
                    reliable=True,
                    destination_identities=[self.binding.participant_id],
                    topic="p2.response",
                )
        except Exception:  # noqa: BLE001 - Observation publication never changes durable work.
            self.counts["observerFailures"] += 1
            try:
                LOGGER.info(
                    "communication_state",
                    extra={"communication_event": "mapping", "communication_code": "unavailable"},
                )
            except Exception:  # noqa: BLE001 - Observation publication never changes durable work.
                self.counts["observerFailures"] += 1

    async def drain(self, ticket: CaptureTicket) -> None:
        producers = tuple(stream.producer for stream in ticket.streams)
        if producers:
            await asyncio.shield(asyncio.gather(*producers, return_exceptions=True))
        nodes = tuple(task for task in ticket.nodes if task is not asyncio.current_task())
        if nodes:
            await asyncio.shield(asyncio.gather(*nodes, return_exceptions=True))

    async def settled(self, ticket: CaptureTicket) -> bool:
        await self.drain(ticket)
        handle = await asyncio.shield(ticket.handle)
        anchor = await asyncio.shield(ticket.anchor)
        assistant = [
            item
            for item in tuple(handle.chat_items)
            if isinstance(item, llm.ChatMessage) and item.role == "assistant"
        ]
        if len(assistant) > 16:
            raise NativeError()
        body = "".join(item.text_content or "" for item in assistant)
        if body:
            text(body, 4096)
        failed = (
            handle.exception() is not None
            or ticket.sdk_failure
            or not ticket.generated_complete
            or (any(item.interrupted for item in assistant) and not handle.interrupted)
        )
        state = "interrupted" if handle.interrupted else "unknown" if failed else "completed"
        value = SdkObservation(
            str(uuid4()),
            anchor.response_id,
            anchor.generation_id,
            anchor.sdk_speech_id,
            "speech_settled",
            state=cast(Literal["completed", "interrupted", "unknown"], state),
            sdk_text=body or None,
        )
        receipt = await self._publication(lambda: self.port.observe_sdk(value))
        if (
            type(receipt) is not ObservationReceipt
            or receipt.response_id != value.response_id
            or receipt.event_id != value.event_id
            or receipt.payload_digest != _payload_digest(value.payload())
        ):
            raise NativeError()
        self.counts["sdkFactsKnown"] += 1
        await self.mapping(ticket)
        ticket.retired = True
        return (
            ticket.generated_complete
            and not failed
            and bool(ticket.streams)
            and all(
                stream.producer.done()
                and not stream.producer.cancelled()
                and stream.producer.exception() is None
                for stream in ticket.streams
            )
        )

    async def abort(self, ticket: CaptureTicket) -> None:
        if (
            ticket.handle.done()
            and not ticket.handle.cancelled()
            and ticket.handle.exception() is None
        ):
            ticket.handle.result().interrupt(force=True)
        else:
            if not ticket.handle.done():
                ticket.handle.set_exception(NativeError("closed"))
        if not ticket.anchor.done():
            ticket.anchor.set_exception(NativeError("acknowledgement_unknown"))
        for stream in ticket.streams:
            stream.request_stop()
        await self.drain(ticket)
        ticket.retired = True

    async def playback(self, value: BrowserObservation) -> ObservationReceipt:
        if type(value) is not BrowserObservation:
            raise NativeError()
        if self.closed:
            raise NativeError("closed")
        ticket = self.tickets.get(value.response_id)
        if (
            ticket is None
            or not ticket.anchor.done()
            or ticket.anchor.cancelled()
            or ticket.anchor.exception() is not None
        ):
            raise NativeError("forbidden")
        if len(self.reports) >= 2:
            raise NativeError("capacity_exhausted")

        async def actual() -> ObservationReceipt:
            receipt = await self._publication(lambda: self.port.observe_browser(value))
            if (
                type(receipt) is not ObservationReceipt
                or receipt.response_id != value.response_id
                or receipt.event_id != value.event_id
                or receipt.payload_digest != _payload_digest(value.payload())
            ):
                raise NativeError()
            self.counts["browserReportsKnown"] += 1
            await self.mapping(ticket)
            return receipt

        task = asyncio.create_task(actual(), name="communication-browser-report")
        self.reports.add(task)

        def done(value: asyncio.Task[ObservationReceipt]) -> None:
            self.reports.discard(value)
            if not value.cancelled():
                value.exception()

        task.add_done_callback(done)
        try:
            return await asyncio.shield(task)
        except NativeError as error:
            if error.code == "acknowledgement_unknown":
                self.counts["unknownAcknowledgements"] += 1
            else:
                self.counts["rejectedReports"] += 1
            raise

    def interrupt(self, response_id: str) -> None:
        ticket = self.tickets.get(uuid(response_id))
        if (
            ticket is None
            or not ticket.handle.done()
            or ticket.handle.cancelled()
            or ticket.handle.exception() is not None
        ):
            raise NativeError("forbidden")
        ticket.handle.result().interrupt()

    async def view(self, response_id: str) -> ResponseView:
        if uuid(response_id) not in self.tickets:
            raise NativeError("forbidden")
        return cast(
            ResponseView, await self._publication(lambda: self.port.inspect_response(response_id))
        )

    def stop(self) -> None:
        self.closed = True
        for ticket in self.tickets.values():
            for stream in ticket.streams:
                stream.request_stop()

    async def aclose(self) -> None:
        self.stop()
        for ticket in self.tickets.values():
            await self.drain(ticket)
        if self.reports:
            await asyncio.shield(asyncio.gather(*tuple(self.reports), return_exceptions=True))
        if self.publications:
            await asyncio.shield(asyncio.gather(*tuple(self.publications), return_exceptions=True))
