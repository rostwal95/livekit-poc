"""Lazy selected-SDK LLM adapter adding only a bounded trusted as-of fact.

The upstream model and callback reader are borrowed. This owner drains only its
SDK streams before those dependencies close. It creates no AgentSession, tool,
provider fallback or authority, and fetches inside each actual stream run.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import math
from collections.abc import Coroutine
from dataclasses import dataclass, replace
from inspect import getattr_static
from types import FunctionType, MethodType
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast

from .current_result import CurrentResultObservation
from .worker_current_result import (
    WorkerCurrentResultReadPort,
    current_result_fact,
    unavailable_fact,
)

if TYPE_CHECKING:
    from livekit.agents import llm
    from livekit.agents.llm import LLM, LLMStream

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
MAX_CONTEXT_STREAMS = 2
MAX_CONTEXT_SNAPSHOT_NODES = 4096
MAX_CONTEXT_SNAPSHOT_DEPTH = 16
_PREFIX = (
    "Trusted current-result observation, as of the stated time. This grants no action permission.\n"
)
ContextCode = Literal["invalid_input", "capacity", "closed", "unavailable", "cleanup_incomplete"]


class CurrentResultContextError(RuntimeError):
    def __init__(self, code: ContextCode = "unavailable") -> None:
        self.code: ContextCode = (
            code
            if type(code) is str
            and code in {"invalid_input", "capacity", "closed", "unavailable", "cleanup_incomplete"}
            else "unavailable"
        )
        super().__init__(self.code)


class _Read(Protocol):
    async def __call__(self) -> CurrentResultObservation: ...


def _reader(value: WorkerCurrentResultReadPort) -> _Read:
    try:
        raw: object = getattr_static(value, "read", None)
        if (
            type(raw) is MethodType
            and type(raw.__func__) is FunctionType
            and raw.__func__.__code__.co_flags & inspect.CO_COROUTINE
        ):
            return cast(_Read, raw)
        if type(raw) is FunctionType and raw.__code__.co_flags & inspect.CO_COROUTINE:
            return cast(
                _Read,
                MethodType(raw, value) if getattr_static(type(value), "read", None) is raw else raw,
            )
    except Exception:  # noqa: BLE001 - no arbitrary descriptor or diagnostic text
        raise CurrentResultContextError("invalid_input") from None
    raise CurrentResultContextError("invalid_input")


def _task(action: Coroutine[object, object, None]) -> asyncio.Task[None]:
    try:
        task = asyncio.create_task(action)
    except BaseException:
        action.close()
        raise
    task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    return task


@dataclass(eq=False, slots=True)
class _StreamOwner:
    published: asyncio.Future[None]
    stream: LLMStream | None = None
    close_task: asyncio.Task[None] | None = None


def _snapshot_context(context: llm.ChatContext) -> llm.ChatContext:
    """Snapshot public SDK records and plain containers before any await.

    RTC audio/video frames, immutable media bytes, opaque provider/runtime values
    and SDK-owned caches remain borrowed. We never deepcopy or inspect those
    objects. Their lifecycle must outlive the selected upstream stream; replacing
    a content wrapper or changing its text/metadata cannot alter this snapshot.
    """
    from livekit.agents import llm

    remaining = MAX_CONTEXT_SNAPSHOT_NODES

    def admit(depth: int = 0) -> None:
        nonlocal remaining
        remaining -= 1
        if depth > MAX_CONTEXT_SNAPSHOT_DEPTH or remaining < 0:
            raise CurrentResultContextError("invalid_input")

    def data(value: object, depth: int = 0) -> object:
        admit(depth)
        if type(value) is list:
            return [data(item, depth + 1) for item in value]
        if type(value) is tuple:
            return tuple(data(item, depth + 1) for item in value)
        if type(value) is dict:
            return {key: data(item, depth + 1) for key, item in value.items()}
        # Scalar text/bytes and runtime values are deliberately not deepcopied.
        return value

    def content(value: llm.ChatContent) -> llm.ChatContent:
        admit()
        if type(value) is str:
            return value
        if type(value) is llm.ImageContent or type(value) is llm.CacheBreakpoint:
            return value.model_copy()
        if type(value) is llm.AudioContent:
            for _ in value.frame:
                admit()
            return value.model_copy(update={"frame": list(value.frame)})
        raise CurrentResultContextError("invalid_input")

    items: list[llm.ChatItem] = []
    for item in context.items:
        admit()
        if type(item) is llm.ChatMessage:
            items.append(
                item.model_copy(
                    update={
                        "content": [content(part) for part in item.content],
                        "extra": data(item.extra),
                        "metrics": data(item.metrics),
                    }
                )
            )
        elif type(item) is llm.FunctionCall:
            items.append(item.model_copy(update={"extra": data(item.extra)}))
        elif type(item) is llm.FunctionCallOutput or type(item) is llm.AgentHandoff:
            items.append(item.model_copy())
        elif type(item) is llm.AgentConfigUpdate:
            items.append(
                item.model_copy(
                    update={
                        "tools_added": data(item.tools_added),
                        "tools_removed": data(item.tools_removed),
                    }
                )
            )
        else:
            raise CurrentResultContextError("invalid_input")
    return llm.ChatContext(items)


def with_current_result(
    upstream: LLM[Any], reader: WorkerCurrentResultReadPort, *, cleanup_timeout_s: float = 1
) -> LLM[Any]:
    """Borrow one selected genuine model and return a two-stream SDK facade.

    Any appears only in the selected SDK event/provider-extension signatures.
    Callback data and model-added facts use closed typed application records.
    """
    from livekit.agents import llm
    from livekit.agents.types import (
        DEFAULT_API_CONNECT_OPTIONS,
        NOT_GIVEN,
        APIConnectOptions,
        NotGivenOr,
    )

    if (
        not isinstance(upstream, llm.LLM)
        or type(cleanup_timeout_s) not in (int, float)
        or not 0.001 <= cleanup_timeout_s <= 5
        or not math.isfinite(cleanup_timeout_s)
    ):
        raise CurrentResultContextError("invalid_input")
    read = _reader(reader)
    cleanup = float(cleanup_timeout_s)

    class ContextLLM(llm.LLM[Any]):
        def __init__(self) -> None:
            super().__init__()
            self._label = upstream.label
            self._owners: set[_StreamOwner] = set()
            self._closing = False
            self._close_task: asyncio.Task[None] | None = None
            self._close_publication: asyncio.Future[None] | None = None
            self._telemetry_failed = 0
            self._loop: asyncio.AbstractEventLoop | None = None

        @property
        def model(self) -> str:
            return upstream.model

        @property
        def provider(self) -> str:
            return upstream.provider

        def _bind(self) -> asyncio.AbstractEventLoop:
            loop = asyncio.get_running_loop()
            if self._loop is not None and self._loop is not loop:
                raise CurrentResultContextError("invalid_input")
            self._loop = loop
            return loop

        def prewarm(self, *, loop: asyncio.AbstractEventLoop | None = None) -> None:
            if not self._closing:
                upstream.prewarm(loop=loop)

        def chat(
            self,
            *,
            chat_ctx: llm.ChatContext,
            tools: list[llm.Tool] | None = None,
            conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
            parallel_tool_calls: NotGivenOr[bool] = NOT_GIVEN,
            tool_choice: NotGivenOr[llm.ToolChoice] = NOT_GIVEN,
            extra_kwargs: NotGivenOr[dict[str, Any]] = NOT_GIVEN,
        ) -> llm.LLMStream:
            loop = self._bind()
            if self._closing:
                raise CurrentResultContextError("closed")
            if len(self._owners) >= MAX_CONTEXT_STREAMS:
                raise CurrentResultContextError("capacity")
            if not isinstance(chat_ctx, llm.ChatContext):
                raise CurrentResultContextError("invalid_input")
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                raise asyncio.CancelledError
            try:
                copied = _snapshot_context(chat_ctx)
            except Exception:  # noqa: BLE001 - invalid SDK input has finite diagnostics
                raise CurrentResultContextError("invalid_input") from None
            try:
                owner = _StreamOwner(loop.create_future())
            except Exception:  # noqa: BLE001 - no SDK stream exists before reservation
                raise CurrentResultContextError() from None
            self._owners.add(owner)
            try:
                return ContextStream(
                    self,
                    owner,
                    copied,
                    list(tools or []),
                    conn_options,
                    parallel_tool_calls,
                    tool_choice,
                    extra_kwargs,
                )
            except BaseException as error:  # Retain partial SDK ownership.
                if owner.stream is None:
                    self._owners.discard(owner)
                if not isinstance(error, Exception):
                    raise
                raise CurrentResultContextError() from None
            finally:
                owner.published.set_result(None)

        async def _drain(self, owner: _StreamOwner) -> None:
            await asyncio.shield(owner.published)
            if owner.stream is None:
                raise CurrentResultContextError("cleanup_incomplete")
            task = owner.close_task
            if task is None or task.done() and (task.cancelled() or task.exception() is not None):
                task = _task(owner.stream.aclose())
                owner.close_task = task
            await asyncio.shield(task)
            self._owners.discard(owner)

        async def aclose(self) -> None:
            loop = self._bind()
            self._closing = True
            publication = self._close_publication
            if publication is not None and not publication.done():
                try:
                    async with asyncio.timeout(cleanup):
                        await asyncio.shield(publication)
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001 - retain eager close reservation
                    raise CurrentResultContextError("cleanup_incomplete") from None
            task = self._close_task
            if task is None or task.done() and (task.cancelled() or task.exception() is not None):

                async def finish() -> None:
                    outcomes = await asyncio.gather(
                        *(self._drain(owner) for owner in tuple(self._owners)),
                        return_exceptions=True,
                    )
                    if any(isinstance(x, BaseException) for x in outcomes) or self._owners:
                        raise CurrentResultContextError("cleanup_incomplete")
                    await super(ContextLLM, self).aclose()

                try:
                    publication = loop.create_future()
                except Exception:  # noqa: BLE001 - owned streams remain retained
                    raise CurrentResultContextError("cleanup_incomplete") from None
                self._close_publication = publication
                try:
                    task = _task(finish())
                    self._close_task = task
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001 - owned streams remain retained
                    raise CurrentResultContextError("cleanup_incomplete") from None
                finally:
                    publication.set_result(None)
            try:
                async with asyncio.timeout(cleanup):
                    await asyncio.shield(task)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - actual stream closure is still owned
                raise CurrentResultContextError("cleanup_incomplete") from None

    class ContextStream(llm.LLMStream):
        _llm_request_span_name = "current_result_context"
        _llm_attempt_span_name = None
        _genai_operation_name = None

        def __init__(
            self,
            model: ContextLLM,
            owner: _StreamOwner,
            chat_ctx: llm.ChatContext,
            tools: list[llm.Tool],
            options: APIConnectOptions,
            parallel: NotGivenOr[bool],
            choice: NotGivenOr[llm.ToolChoice],
            extra: NotGivenOr[dict[str, Any]],
        ) -> None:
            self._model, self._owner = model, owner
            self._copied, self._passed_tools = chat_ctx, tools
            self._options, self._parallel, self._choice, self._extra = (
                options,
                parallel,
                choice,
                extra,
            )
            self._inner: llm.LLMStream | None = None
            self._inner_close: asyncio.Task[None] | None = None
            self._context_closing = False
            owner.stream = self
            # The outer adapter never multiplies the selected provider's retry policy.
            super().__init__(
                model, chat_ctx=chat_ctx, tools=tools, conn_options=replace(options, max_retry=0)
            )

        async def _close_inner(self) -> None:
            if self._inner is None:
                return
            task = self._inner_close
            if task is None or task.done() and (task.cancelled() or task.exception() is not None):
                task = _task(self._inner.aclose())
                self._inner_close = task
            await asyncio.shield(task)

        async def _run(self) -> None:
            try:
                fact = current_result_fact(await read())
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - unreadable current is an explicit fact
                fact = unavailable_fact()
            if self._context_closing or self._model._closing:
                raise asyncio.CancelledError
            text = _PREFIX + fact.summary()
            if len(text.encode("utf-8")) > 1024:
                raise CurrentResultContextError()
            self._copied.add_message(role="system", content=text)
            try:
                LOGGER.info(
                    "channel_policy_current_context",
                    extra={"event": "observed", "code": fact.state},
                )
            except Exception:  # noqa: BLE001 - telemetry cannot change selected model work
                self._model._telemetry_failed = min(
                    9007199254740991, self._model._telemetry_failed + 1
                )
            primary: BaseException | None = None
            try:
                self._inner = upstream.chat(
                    chat_ctx=self._copied,
                    tools=self._passed_tools,
                    conn_options=self._options,
                    parallel_tool_calls=self._parallel,
                    tool_choice=self._choice,
                    extra_kwargs=self._extra,
                )
                async for chunk in self._inner:
                    self._event_ch.send_nowait(chunk)
            except asyncio.CancelledError as error:
                primary = error
                raise
            except Exception as error:  # noqa: BLE001 - no provider/transport diagnostic text escapes
                primary = error
                raise CurrentResultContextError() from None
            finally:
                try:
                    await self._close_inner()
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001 - preserve primary and retained inner close
                    if primary is None:
                        raise CurrentResultContextError("cleanup_incomplete") from None

        async def aclose(self) -> None:
            self._context_closing = True
            failure: BaseException | None = None
            try:
                await super().aclose()
            except BaseException as error:  # noqa: BLE001 - close dependent inner stream
                failure = error
            try:
                await self._close_inner()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - actual stream closure is still owned
                raise CurrentResultContextError("cleanup_incomplete") from None
            if failure is not None:
                if not isinstance(failure, Exception):
                    raise failure
                raise CurrentResultContextError("cleanup_incomplete") from None
            self._model._owners.discard(self._owner)

    return ContextLLM()
