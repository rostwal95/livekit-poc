"""Shared bounded LLM behavior with actual cloud labels and a fixed TLS wire route."""

from __future__ import annotations

import asyncio
import importlib
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx2
from livekit.agents import llm
from openai import AsyncOpenAI

from .inference_llm import LocalLLM, PluginFactory
from .inference_settings import LLM_TIMEOUT_SECONDS, MAX_OUTPUT_TOKENS
from .provider_settings import OPENAI_BASE_URL, PROVIDER_LLM_MODEL, ProviderInferenceError


class BoundedLLM(LocalLLM):
    """Reuse the tested context/tool/output/deadline guards with explicit identities.

    LocalLLM retains its original factory and behavior. No model/provider label is
    inherited implicitly by this reusable facade.
    """

    def __init__(
        self, provider: llm.LLM[Any], client: AsyncOpenAI, *, model_name: str, provider_name: str
    ) -> None:
        if (model_name, provider_name) not in {
            (PROVIDER_LLM_MODEL, "openai"),
            ("qwen3:4b-instruct", "local-ollama"),
        }:
            raise ProviderInferenceError("invalid_configuration")
        self._model_name, self._provider_name = model_name, provider_name
        super().__init__(provider, client)

    @property
    def model(self) -> str:
        return self._model_name

    @property
    def provider(self) -> str:
        return self._provider_name


class _LeaseBody(httpx2.AsyncByteStream):
    def __init__(self, source: httpx2.AsyncByteStream, release: Callable[[], None]) -> None:
        self.source, self.release = source, release
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        size = 0
        try:
            async for part in self.source:
                size += len(part)
                if size > 65536:
                    raise ProviderInferenceError("response_limit")
                yield part
        finally:
            await self.aclose()

    async def aclose(self) -> None:
        if not self.closed:
            self.closed = True
            try:
                await self.source.aclose()
            finally:
                self.release()


class ProviderLLMTransport(httpx2.AsyncBaseTransport):
    """One active +one queued wire request; the response body retains its slot."""

    def __init__(self, api_key: str, source: httpx2.AsyncBaseTransport | None = None) -> None:
        self._api_key = api_key
        self.source = source or httpx2.AsyncHTTPTransport(
            retries=0,
            trust_env=False,
            verify=True,
            limits=httpx2.Limits(max_connections=1, max_keepalive_connections=1),
        )
        self._slot = asyncio.Semaphore(1)
        self._pending = 0
        self._closed = False
        self._bodies: set[_LeaseBody] = set()
        self._requests: set[asyncio.Task[Any]] = set()

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        if self._closed:
            raise ProviderInferenceError("closed")
        if request.method != "POST" or str(request.url) != OPENAI_BASE_URL + "/chat/completions":
            raise ProviderInferenceError("invalid_configuration")
        try:
            content = request.content
        except httpx2.RequestNotRead:
            raise ProviderInferenceError("input_limit") from None
        if len(content) > 131072:
            raise ProviderInferenceError("input_limit")
        try:
            body = json.loads(content)
        except (ValueError, RecursionError):
            raise ProviderInferenceError("input_limit") from None
        if (
            type(body) is not dict
            or body.get("model") != PROVIDER_LLM_MODEL
            or body.get("store") is not False
            or body.get("reasoning_effort") != "none"
            or type(body.get("max_completion_tokens")) is not int
            or body["max_completion_tokens"] != MAX_OUTPUT_TOKENS
        ):
            raise ProviderInferenceError("invalid_configuration")
        if self._pending >= 2:
            raise ProviderInferenceError("busy")
        self._pending += 1
        task = asyncio.current_task()
        if task is not None:
            self._requests.add(task)
        acquired = False
        transferred = False
        try:
            await self._slot.acquire()
            acquired = True
            if self._closed:
                raise ProviderInferenceError("closed")
            request.headers.clear()
            request.headers.update(
                {
                    "Host": "api.openai.com",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                    "Accept-Encoding": "identity",
                    "Content-Length": str(len(content)),
                    "Authorization": "Bearer " + self._api_key,
                }
            )
            response = await self.source.handle_async_request(request)
            try:
                length = response.headers.get("Content-Length")
                if response.status_code != 200:
                    raise ProviderInferenceError("dependency_unavailable")
                if response.headers.get("Content-Encoding", "identity") != "identity":
                    raise ProviderInferenceError("response_invalid")
                if length is not None and (
                    not length.isascii()
                    or not length.isdigit()
                    or len(length) > 8
                    or int(length) > 65536
                ):
                    raise ProviderInferenceError("response_limit")
                if response.is_closed:
                    try:
                        cached = response.content
                    except httpx2.ResponseNotRead:
                        raise ProviderInferenceError("response_invalid") from None
                    if len(cached) > 65536:
                        raise ProviderInferenceError("response_limit")
                    return response
                if not isinstance(response.stream, httpx2.AsyncByteStream):
                    raise ProviderInferenceError("response_invalid")

                def release() -> None:
                    self._bodies.discard(wrapped)
                    self._pending -= 1
                    self._slot.release()

                wrapped = _LeaseBody(response.stream, release)
                self._bodies.add(wrapped)
                response.stream = wrapped
                transferred = True
                return response
            except BaseException:
                await response.aclose()
                raise
        finally:
            if task is not None:
                self._requests.discard(task)
            if not transferred:
                self._pending -= 1
                if acquired:
                    self._slot.release()

    async def aclose(self) -> None:
        self._closed = True
        current = asyncio.current_task()
        tasks = [task for task in self._requests if task is not current]
        for task in tasks:
            task.cancel()
        failures = 0
        cancelled: asyncio.CancelledError | None = None
        for action in [
            *(body.aclose for body in tuple(self._bodies)),
            lambda: asyncio.gather(*tasks, return_exceptions=True),
            self.source.aclose,
        ]:
            try:
                async with asyncio.timeout(0.05):
                    await action()
            except asyncio.CancelledError as error:
                failures += 1
                cancelled = cancelled or error
            except Exception:  # noqa: BLE001 - independent fixed cleanup boundary
                failures += 1
        if cancelled is not None:
            raise cancelled
        if failures or self._pending:
            raise ProviderInferenceError("cleanup_incomplete")


async def create_provider_llm(
    api_key: str,
    *,
    plugin_factory: PluginFactory | None = None,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> BoundedLLM:
    if plugin_factory is None:
        try:
            plugin_factory = importlib.import_module("livekit.plugins.openai").LLM
        except Exception:  # noqa: BLE001 - optional plugin errors remain private
            raise ProviderInferenceError("dependency_unavailable") from None
    http = httpx2.AsyncClient(
        timeout=httpx2.Timeout(LLM_TIMEOUT_SECONDS, connect=5, pool=5),
        trust_env=False,
        follow_redirects=False,
        transport=ProviderLLMTransport(api_key, transport),
    )
    client: AsyncOpenAI | None = None
    try:
        client = AsyncOpenAI(
            api_key=api_key,
            admin_api_key="",
            organization="",
            project="",
            webhook_secret="",
            base_url=OPENAI_BASE_URL,
            timeout=LLM_TIMEOUT_SECONDS,
            max_retries=0,
            http_client=http,
        )
        provider = plugin_factory(
            model=PROVIDER_LLM_MODEL,
            client=client,
            reasoning_effort="none",
            parallel_tool_calls=False,
            tool_choice="auto",
            max_completion_tokens=MAX_OUTPUT_TOKENS,
            max_retries=0,
            store=False,
            # Pin the actual wire contract after SDK parameter filtering.
            extra_body={"store": False, "reasoning_effort": "none"},
        )
        if not isinstance(provider, llm.LLM):
            raise ProviderInferenceError("dependency_unavailable")
        return BoundedLLM(provider, client, model_name=PROVIDER_LLM_MODEL, provider_name="openai")
    except BaseException as error:
        try:
            async with asyncio.timeout(0.2):
                if client is not None:
                    await client.close()
                else:
                    await http.aclose()
        except Exception:  # noqa: BLE001,S110 - preserve construction/cancellation failure
            pass
        if not isinstance(error, Exception):
            raise
        raise ProviderInferenceError("dependency_unavailable") from None
