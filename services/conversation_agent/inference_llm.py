"""Bounded native SDK stream around the official local OpenAI-compatible plugin."""

from __future__ import annotations

import asyncio
import importlib
import json
from collections.abc import AsyncIterator
from typing import Any, Protocol

import httpx2
from livekit.agents import llm
from livekit.agents.types import (
    DEFAULT_API_CONNECT_OPTIONS,
    NOT_GIVEN,
    APIConnectOptions,
    NotGivenOr,
)
from openai import AsyncOpenAI

from .inference_settings import (
    LLM_TIMEOUT_SECONDS,
    LOCAL_LLM_MODEL,
    MAX_MODEL_CHUNKS,
    MAX_MODEL_CONTEXT_BYTES,
    MAX_MODEL_OUTPUT_BYTES,
    MAX_OUTPUT_TOKENS,
    LocalInferenceError,
    LocalInferenceSettings,
)

TOOL_NAMES = frozenset({"submit_investigation", "get_case", "cancel_case"})


class _LimitedBody(httpx2.AsyncByteStream):
    def __init__(self, source: httpx2.AsyncByteStream) -> None:
        self.source = source
        self._closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        size = 0
        try:
            async for part in self.source:
                size += len(part)
                if size > 65536:
                    raise LocalInferenceError("response_limit")
                yield part
        finally:
            await self.aclose()

    async def aclose(self) -> None:
        if not self._closed:
            self._closed = True
            await self.source.aclose()


class LocalLLMTransport(httpx2.AsyncBaseTransport):
    """Fixed ChatCompletions route and wire headers; ambient SDK options cannot escape."""

    def __init__(self, base_url: str, source: httpx2.AsyncBaseTransport | None = None) -> None:
        if base_url not in {"http://p1-llm:11434/v1", "http://127.0.0.1:18440/v1"}:
            raise LocalInferenceError("invalid_configuration")
        self.url = base_url + "/chat/completions"
        self.host = "p1-llm:11434" if base_url == "http://p1-llm:11434/v1" else "127.0.0.1:18440"
        self.source = source or httpx2.AsyncHTTPTransport(
            retries=0,
            trust_env=False,
            limits=httpx2.Limits(max_connections=1, max_keepalive_connections=1),
        )

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        if request.method != "POST" or str(request.url) != self.url:
            raise LocalInferenceError("invalid_configuration")
        try:
            content_length = len(request.content)
        except httpx2.RequestNotRead:
            raise LocalInferenceError("input_limit") from None
        if content_length > 131072:
            raise LocalInferenceError("input_limit")
        # OpenAI's SDK can read OPENAI_CUSTOM_HEADERS. Reset the public request
        # headers at the actual transport boundary, after SDK construction/hooks.
        request.headers.clear()
        request.headers.update(
            {
                "Host": self.host,
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "Accept-Encoding": "identity",
                "Content-Length": str(content_length),
                "Authorization": "Bearer local-only",
            }
        )
        response = await self.source.handle_async_request(request)
        try:
            if response.status_code != 200:
                raise LocalInferenceError("dependency_unavailable")
            if response.headers.get("Content-Encoding", "identity") != "identity":
                raise LocalInferenceError("response_invalid")
            length = response.headers.get("Content-Length")
            if length is not None and (
                not length.isascii()
                or not length.isdigit()
                or len(length) > 8
                or int(length) > 65536
            ):
                raise LocalInferenceError("response_limit")
            if not isinstance(response.stream, httpx2.AsyncByteStream):
                raise LocalInferenceError("response_invalid")
            response.stream = _LimitedBody(response.stream)
            return response
        except BaseException:
            await response.aclose()
            raise

    async def aclose(self) -> None:
        await self.source.aclose()


class PluginFactory(Protocol):
    # Any is limited to the selected plugin's public constructor arguments.
    def __call__(self, **kwargs: Any) -> llm.LLM[Any]: ...


def bounded_chunk(chunk: llm.ChatChunk) -> tuple[llm.ChatChunk, int]:
    """Keep content/tool calls native; discard arbitrary provider extras and bound bytes."""
    if not isinstance(chunk, llm.ChatChunk) or len(chunk.id.encode("utf-8")) > 128:
        raise LocalInferenceError("response_invalid")
    delta = chunk.delta
    size = 0
    safe_delta = None
    if delta is not None:
        if delta.role not in {None, "assistant"} or len(delta.tool_calls) > 3:
            raise LocalInferenceError("response_invalid")
        text = delta.content
        if text is not None:
            size += len(text.encode("utf-8"))
        safe_calls = []
        for call in delta.tool_calls:
            if (
                call.name not in TOOL_NAMES
                or len(call.arguments.encode("utf-8")) > 128
                or not 1 <= len(call.call_id.encode("utf-8")) <= 128
            ):
                raise LocalInferenceError("response_invalid")
            try:
                arguments = json.loads(call.arguments or "{}")
            except (ValueError, RecursionError):
                raise LocalInferenceError("response_invalid") from None
            if type(arguments) is not dict or arguments:
                raise LocalInferenceError("response_invalid")
            size += len(call.arguments.encode("utf-8")) + len(call.name) + len(call.call_id)
            safe_calls.append(
                llm.FunctionToolCall(name=call.name, arguments=call.arguments, call_id=call.call_id)
            )
        safe_delta = llm.ChoiceDelta(role=delta.role, content=text, tool_calls=safe_calls)
    usage = chunk.usage
    if usage is not None:
        counts = (
            usage.completion_tokens,
            usage.prompt_tokens,
            usage.total_tokens,
            usage.prompt_cached_tokens,
            usage.reasoning_tokens,
        )
        if any(type(value) is not int or not 0 <= value <= 1000000 for value in counts):
            raise LocalInferenceError("response_invalid")
        if usage.completion_tokens > MAX_OUTPUT_TOKENS:
            raise LocalInferenceError("response_limit")
        # This finite provider is local; service-tier/provider metadata is not evidence.
        usage = llm.CompletionUsage(
            completion_tokens=usage.completion_tokens,
            prompt_tokens=usage.prompt_tokens,
            total_tokens=usage.total_tokens,
            prompt_cached_tokens=usage.prompt_cached_tokens,
            reasoning_tokens=usage.reasoning_tokens,
        )
    return llm.ChatChunk(id=chunk.id, delta=safe_delta, usage=usage), size


def _supported_text_content(part: object) -> bool:
    if type(part) is str:
        return True
    if type(part) is not llm.CacheBreakpoint:
        return False
    # The SDK appends this non-text control to each turn's instructions copy.
    # Exact class/fields admit that marker without enabling media or other controls.
    fields = vars(part)
    return (
        len(fields) == 1
        and type(fields.get("type")) is str
        and fields["type"] == "cache_breakpoint"
        and part.__pydantic_extra__ is None
    )


class LocalLLM(llm.LLM[Any]):
    """The actual plugin produces text/tool calls; this wrapper adds finite ownership."""

    def __init__(self, provider: llm.LLM[Any], client: AsyncOpenAI) -> None:
        super().__init__()
        self._provider, self._client = provider, client
        self._closed = False
        self._cleanup_failed = False

    @property
    def model(self) -> str:
        return LOCAL_LLM_MODEL

    @property
    def provider(self) -> str:
        return "local-ollama"

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
        if self._closed:
            raise LocalInferenceError("closed")
        if any(
            isinstance(item, llm.ChatMessage)
            and any(not _supported_text_content(part) for part in item.content)
            for item in chat_ctx.items
        ):
            raise LocalInferenceError("input_limit")
        # SDK context is bounded again at the provider boundary, before conversion/network I/O.
        try:
            context_bytes = json.dumps(
                chat_ctx.to_dict(exclude_metrics=True), ensure_ascii=False, allow_nan=False
            ).encode("utf-8")
        except (ValueError, TypeError, RecursionError):
            raise LocalInferenceError("input_limit") from None
        if len(context_bytes) > MAX_MODEL_CONTEXT_BYTES or len(chat_ctx.items) > 64:
            raise LocalInferenceError("input_limit")
        if extra_kwargs is not NOT_GIVEN and extra_kwargs:
            raise LocalInferenceError("invalid_configuration")
        return _LocalLLMStream(
            self,
            chat_ctx=chat_ctx,
            tools=tools or [],
            conn_options=conn_options,
            tool_choice=tool_choice,
        )

    async def aclose(self) -> None:
        if self._closed:
            if self._cleanup_failed:
                raise LocalInferenceError("cleanup_incomplete")
            return
        self._closed = True
        original: BaseException | None = None
        try:
            async with asyncio.timeout(0.2):
                await self._provider.aclose()
        except BaseException as error:  # noqa: BLE001 - close both resources before propagating
            # Preserve cancellation after independently closing the explicitly owned client.
            original = error
        try:
            async with asyncio.timeout(0.2):
                await self._client.close()
        except BaseException as error:  # noqa: BLE001 - preserve the original cleanup disposition
            if original is None:
                original = error
        if original is not None:
            self._cleanup_failed = True
            if not isinstance(original, Exception):
                raise original
            raise LocalInferenceError("cleanup_incomplete") from None


class _LocalLLMStream(llm.LLMStream):
    def __init__(
        self,
        provider: LocalLLM,
        *,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool],
        conn_options: APIConnectOptions,
        tool_choice: NotGivenOr[llm.ToolChoice],
    ) -> None:
        self.provider, self.choice = provider, tool_choice
        super().__init__(provider, chat_ctx=chat_ctx, tools=tools, conn_options=conn_options)

    async def _run(self) -> None:
        count, size = 0, 0
        try:
            async with asyncio.timeout(LLM_TIMEOUT_SECONDS):
                async with self.provider._provider.chat(
                    chat_ctx=self.chat_ctx,
                    tools=self.tools,
                    conn_options=APIConnectOptions(max_retry=0, timeout=LLM_TIMEOUT_SECONDS),
                    parallel_tool_calls=False,
                    tool_choice=self.choice,
                ) as stream:
                    async for chunk in stream:
                        count += 1
                        safe, added = bounded_chunk(chunk)
                        size += added
                        if count > MAX_MODEL_CHUNKS or size > MAX_MODEL_OUTPUT_BYTES:
                            raise LocalInferenceError("response_limit")
                        self._event_ch.send_nowait(safe)
        except TimeoutError:
            raise LocalInferenceError("deadline_exceeded") from None
        except LocalInferenceError:
            raise
        except Exception:  # noqa: BLE001 - model/provider exceptions may contain private inputs
            raise LocalInferenceError("dependency_unavailable") from None


async def create_local_llm(
    settings: LocalInferenceSettings,
    *,
    plugin_factory: PluginFactory | None = None,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> LocalLLM:
    if plugin_factory is None:
        try:
            plugin = importlib.import_module("livekit.plugins.openai")
            plugin_factory = plugin.LLM
        except Exception:  # noqa: BLE001 - optional plugin initialization stays payload-free
            raise LocalInferenceError("dependency_unavailable") from None
    http = httpx2.AsyncClient(
        timeout=httpx2.Timeout(LLM_TIMEOUT_SECONDS, connect=2, pool=2),
        limits=httpx2.Limits(max_connections=1, max_keepalive_connections=1),
        trust_env=False,
        follow_redirects=False,
        transport=LocalLLMTransport(settings.llm_base_url, transport),
    )
    try:
        client = AsyncOpenAI(
            api_key="local-only",
            admin_api_key="",
            organization="",
            project="",
            webhook_secret="",
            base_url=settings.llm_base_url,
            timeout=LLM_TIMEOUT_SECONDS,
            max_retries=0,
            http_client=http,
        )
    except BaseException as error:
        async with asyncio.timeout(0.2):
            await http.aclose()
        if not isinstance(error, Exception):
            raise
        raise LocalInferenceError("dependency_unavailable") from None
    try:
        provider = plugin_factory(
            model=LOCAL_LLM_MODEL,
            client=client,
            temperature=0.0,
            parallel_tool_calls=False,
            tool_choice="auto",
            max_completion_tokens=MAX_OUTPUT_TOKENS,
            max_retries=0,
            store=False,
            extra_body={
                "think": False,
                "options": {"num_ctx": 2048, "num_predict": MAX_OUTPUT_TOKENS, "num_thread": 4},
            },
        )
        if not isinstance(provider, llm.LLM):
            raise LocalInferenceError("dependency_unavailable")
        return LocalLLM(provider, client)
    except BaseException as error:
        try:
            async with asyncio.timeout(0.2):
                await client.close()
        except Exception:  # noqa: BLE001,S110 - original creation failure remains authoritative
            pass
        if not isinstance(error, Exception):
            raise
        raise LocalInferenceError("dependency_unavailable") from None
