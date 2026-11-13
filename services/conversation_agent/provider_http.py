"""Owned provider HTTP sessions with fixed TLS routes and bounded JSON reads."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import aiohttp

from .provider_settings import DEEPGRAM_URL, ELEVEN_BASE_URL, ProviderInferenceError


class BoundedJSONResponse(aiohttp.ClientResponse):
    """Public response-class hook prevents unbounded provider error/ASR bodies."""

    _bounded_cache: bytes | None = None

    def raise_for_status(self) -> None:
        if not 200 <= self.status < 300:
            self.close()
            raise ProviderInferenceError("dependency_unavailable")

    async def read(self) -> bytes:
        self.raise_for_status()
        if self._bounded_cache is None:
            content = bytearray()
            async for part in self.content.iter_chunked(4096):
                if len(content) + len(part) > 16384:
                    self.close()
                    raise ProviderInferenceError("response_limit")
                content.extend(part)
            self._bounded_cache = bytes(content)
        return self._bounded_cache

    async def text(self, encoding: str | None = None, errors: str = "strict") -> str:
        try:
            return (await self.read()).decode(encoding or "utf-8", errors=errors)
        except UnicodeError:
            raise ProviderInferenceError("response_invalid") from None

    async def json(
        self,
        *,
        encoding: str | None = None,
        loads: Callable[[str], Any] = json.loads,
        content_type: str | None = "application/json",
    ) -> Any:
        if content_type is not None and self.content_type != content_type:
            raise ProviderInferenceError("response_invalid")
        try:
            return loads(await self.text(encoding))
        except (UnicodeError, ValueError, RecursionError):
            raise ProviderInferenceError("response_invalid") from None


def provider_http_session(role: str) -> aiohttp.ClientSession:
    if role not in {"stt", "tts"}:
        raise ProviderInferenceError("invalid_configuration")
    expected = DEEPGRAM_URL if role == "stt" else ELEVEN_BASE_URL + "/text-to-dialogue/stream"
    trace = aiohttp.TraceConfig()

    async def start(
        _session: aiohttp.ClientSession, _ctx: Any, params: aiohttp.TraceRequestStartParams
    ) -> None:
        url = params.url
        if (
            params.method != "POST"
            or url.scheme != "https"
            or url.user is not None
            or url.password is not None
            or url.fragment
            or str(url.with_query(None)) != expected
        ):
            raise ProviderInferenceError("invalid_configuration")

    async def redirect(
        _session: aiohttp.ClientSession, _ctx: Any, _params: aiohttp.TraceRequestRedirectParams
    ) -> None:
        raise ProviderInferenceError("response_invalid")

    trace.on_request_start.append(start)
    trace.on_request_redirect.append(redirect)
    return aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(limit=1, limit_per_host=1),
        timeout=aiohttp.ClientTimeout(total=10, connect=5, sock_connect=5, sock_read=10),
        trust_env=False,
        response_class=BoundedJSONResponse,
        trace_configs=[trace],
        headers={"Accept-Encoding": "identity"},
        auto_decompress=False,
        max_line_size=8192,
        max_field_size=8192,
    )
