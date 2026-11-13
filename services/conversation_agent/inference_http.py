"""Owned finite HTTP requests to explicitly selected private local model services."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import httpx

from .inference_settings import LocalInferenceError


class LocalModelHTTP:
    """One active/one waiting request; timeout includes queueing and response bytes."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float,
        maximum_response_bytes: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if base_url not in {
            "http://p1-stt:8080",
            "http://p1-tts:5000",
            "http://127.0.0.1:18441",
            "http://127.0.0.1:18442",
        }:
            raise LocalInferenceError("invalid_configuration")
        if type(timeout_seconds) not in {int, float} or not 0 < timeout_seconds <= 10:
            raise LocalInferenceError("invalid_configuration")
        if type(maximum_response_bytes) is not int or not 0 < maximum_response_bytes <= 1048576:
            raise LocalInferenceError("invalid_configuration")
        self.timeout_seconds = timeout_seconds
        self.maximum_response_bytes = maximum_response_bytes
        self.path = "/inference" if base_url.endswith((":8080", ":18441")) else "/synthesize"
        self.client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(timeout_seconds, connect=2, pool=timeout_seconds),
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
            follow_redirects=False,
            trust_env=False,
            headers={"Accept-Encoding": "identity"},
            transport=transport,
        )
        self._slot = asyncio.Semaphore(1)
        self._pending = 0
        self._closed = False
        self._tasks: set[asyncio.Task[bytes]] = set()

    async def post(
        self,
        path: str,
        *,
        json_body: Mapping[str, str] | None = None,
        data: Mapping[str, str] | None = None,
        files: Mapping[str, tuple[str, bytes, str]] | None = None,
    ) -> bytes:
        if path != self.path:
            raise LocalInferenceError("invalid_configuration")
        if self._closed:
            raise LocalInferenceError("closed")
        if self._pending >= 2:
            raise LocalInferenceError("busy")
        self._pending += 1
        task = asyncio.create_task(
            self._request(path, json_body=json_body, data=data, files=files),
            name="bounded-local-model-http",
        )
        self._tasks.add(task)
        try:
            return await task
        finally:
            self._tasks.discard(task)
            self._pending -= 1

    async def _request(
        self,
        path: str,
        *,
        json_body: Mapping[str, str] | None,
        data: Mapping[str, str] | None,
        files: Mapping[str, tuple[str, bytes, str]] | None,
    ) -> bytes:
        try:
            async with asyncio.timeout(self.timeout_seconds):
                async with self._slot:
                    if self._closed:
                        raise LocalInferenceError("closed")
                    async with self.client.stream(
                        "POST", path, json=json_body, data=data, files=files
                    ) as response:
                        if response.status_code != 200:
                            # Dependency error/redirect bodies are never read or reflected.
                            raise LocalInferenceError("dependency_unavailable")
                        if response.headers.get("Content-Encoding", "identity") != "identity":
                            raise LocalInferenceError("response_invalid")
                        length = response.headers.get("Content-Length")
                        if length is not None and (
                            not length.isascii()
                            or not length.isdigit()
                            or len(length) > 8
                            or int(length) > self.maximum_response_bytes
                        ):
                            raise LocalInferenceError("response_limit")
                        value = bytearray()
                        async for part in response.aiter_raw(chunk_size=16384):
                            if len(value) + len(part) > self.maximum_response_bytes:
                                raise LocalInferenceError("response_limit")
                            value.extend(part)
                        return bytes(value)
        except TimeoutError:
            raise LocalInferenceError("deadline_exceeded") from None
        except httpx.HTTPError:
            raise LocalInferenceError("dependency_unavailable") from None

    async def aclose(self) -> None:
        self._closed = True
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        original: BaseException | None = None
        try:
            async with asyncio.timeout(0.2):
                await asyncio.gather(*tasks, return_exceptions=True)
        except BaseException as error:  # noqa: BLE001 - independently close the owned HTTP pool
            original = error
        try:
            async with asyncio.timeout(0.2):
                await self.client.aclose()
        except BaseException as error:  # noqa: BLE001 - preserve cancellation after both attempts
            original = original or error
        if original is not None:
            if not isinstance(original, Exception):
                raise original
            raise LocalInferenceError("cleanup_incomplete") from None


def strict_transcript(raw: bytes, maximum_text_bytes: int) -> str:
    """Read Whisper's selected JSON response with duplicate/shape/Unicode bounds."""
    import json

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, value in items:
            if name in result:
                raise LocalInferenceError("response_invalid")
            result[name] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=pairs)
        if type(value) is not dict or set(value) != {"text"} or type(value["text"]) is not str:
            raise LocalInferenceError("response_invalid")
        text = value["text"].strip()
        encoded = text.encode("utf-8")
        if len(encoded) > maximum_text_bytes or any(ord(c) < 32 and c not in "\n\t" for c in text):
            raise LocalInferenceError("response_limit")
        return text
    except (ValueError, UnicodeError, RecursionError):
        raise LocalInferenceError("response_invalid") from None
