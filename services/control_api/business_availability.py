"""Bounded observation of the fixed local native worker before dispatch.

Readiness is an observation, not an assignment fence. SDK admission still owns
one-job capacity; business acceptance and replay remain separate authority.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
from collections.abc import Callable
from typing import Protocol
from urllib.parse import urlsplit

import httpx

MAX_RESPONSE_BYTES = 8192
STABLE_IDLE_SECONDS = 1.6
WORKER_FIELDS = frozenset(
    {"worker_type", "agent_name", "active_jobs", "sdk_version", "worker_load", "protocol_version"}
)


class NativeWorkerAvailabilityPort(Protocol):
    async def available(self) -> bool: ...


def validate_worker_url(value: str) -> str:
    """Only the composed worker or one explicitly isolated helper worker is valid."""
    if type(value) is not str or not 1 <= len(value) <= 128:
        raise ValueError("A fixed local conversational worker URL is required")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if (
            parsed.scheme != "http"
            or re.fullmatch(r"(?:conversation-agent|p1-g-[a-f0-9]{32}-native)", host) is None
            or parsed.port != 8082
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
            or value != "http://" + host + ":8082"
        ):
            raise ValueError("Invalid worker URL")
    except (ValueError, TypeError, AttributeError):
        raise ValueError("A fixed local conversational worker URL is required") from None
    return value


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate worker observation field")
        result[key] = value
    return result


def _nonfinite(_value: str) -> None:
    raise ValueError("Nonfinite worker observation")


def _idle(body: bytes) -> bool:
    value = json.loads(body, object_pairs_hook=_unique, parse_constant=_nonfinite)
    if (
        type(value) is not dict
        or not {"worker_type", "agent_name", "sdk_version", "protocol_version"} <= set(value)
        or set(value) - WORKER_FIELDS
        or value["worker_type"] != "JT_ROOM"
        or value["agent_name"] != "local-business-agent"
        or value["sdk_version"] != "1.8.11"
        or type(value["protocol_version"]) is not int
        or value["protocol_version"] != 1
    ):
        return False
    # Protobuf JSON omits default zeros. WorkerInfo uses FLOAT for both fields,
    # so accept finite JSON integer/float zeros while excluding bool/string.
    jobs, load = value.get("active_jobs", 0), value.get("worker_load", 0)
    return (
        type(jobs) in (int, float)
        and jobs == 0
        and type(load) in (int, float)
        and 0 <= load < 1
        and math.isfinite(load)
    )


class NativeWorkerAvailability:
    """Consume one readiness observation after a fresh stable-idle window.

    SDK load/status advertisements may lag its process list. Repeated healthy
    idle observations span the frozen SDK's 1.5-second status interval; every
    true result consumes that window so a later admission must observe anew.
    """

    def __init__(self, url: str, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._url = validate_worker_url(url)
        self._clock = clock
        self._idle_since: float | None = None

    async def available(self) -> bool:
        try:
            if not await self._probe():
                self._idle_since = None
                return False
            raw = self._clock()
            if type(raw) not in (int, float):
                raise ValueError("A finite monotonic clock is required")
            stamp = float(raw)
            if not math.isfinite(stamp) or stamp < 0:
                raise ValueError("A finite monotonic clock is required")
            if self._idle_since is None or stamp < self._idle_since:
                self._idle_since = stamp
                return False
            if stamp - self._idle_since < STABLE_IDLE_SECONDS:
                return False
            self._idle_since = None
            return True
        except asyncio.CancelledError:
            self._idle_since = None
            raise
        except Exception:  # noqa: BLE001 - an invalid observation cannot authorize dispatch
            self._idle_since = None
            return False

    async def _probe(self) -> bool:
        try:
            async with (
                asyncio.timeout(0.6),
                httpx.AsyncClient(
                    trust_env=False,
                    timeout=0.25,
                    follow_redirects=False,
                    limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
                ) as client,
            ):
                # Health rejects an unregistered worker or a stale disconnected
                # worker. Never read a diagnostic health error/response body.
                async with client.stream("GET", self._url + "/") as health:
                    if health.status_code != 200:
                        return False
                async with client.stream("GET", self._url + "/worker") as response:
                    if (
                        response.status_code != 200
                        or response.headers.get("Content-Encoding", "identity") != "identity"
                    ):
                        return False
                    declared = response.headers.get("Content-Length")
                    if declared is not None and (
                        re.fullmatch(r"[0-9]{1,5}", declared) is None
                        or int(declared) > MAX_RESPONSE_BYTES
                    ):
                        return False
                    body = bytearray()
                    async for chunk in response.aiter_raw():
                        if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                            return False
                        body.extend(chunk)
                    return _idle(bytes(body))
        except Exception:  # noqa: BLE001 - fixed false observation, no dependency/body text
            return False
