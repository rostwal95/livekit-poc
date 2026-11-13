"""One owned bounded loopback connection per native intake; no retry or environment loading."""

from __future__ import annotations

import asyncio
import json
import time
from typing import cast

from .native_models import (
    CODES,
    NativeAck,
    NativeBinding,
    NativeCode,
    NativeCredential,
    NativeEndpoint,
    NativeError,
    NativeInput,
    ack_from,
    decode,
    fields,
)


class NativeCleanupIncomplete(RuntimeError):
    def __init__(self) -> None:
        super().__init__("cleanup_incomplete")


class NativeHttpIntake:
    def __init__(
        self,
        endpoint: NativeEndpoint,
        credential: NativeCredential,
        binding: NativeBinding,
        *,
        timeout: float = 3.0,
        cleanup: float = 5.0,
    ) -> None:
        if (
            type(endpoint) is not NativeEndpoint
            or type(credential) is not NativeCredential
            or type(binding) is not NativeBinding
            or type(timeout) not in (int, float)
            or not 0.02 <= timeout <= 5
            or type(cleanup) not in (int, float)
            or not 0.02 <= cleanup <= 5
        ):
            raise NativeError()
        self._endpoint, self._credential, self._binding = endpoint, credential, binding
        self._timeout, self._cleanup = float(timeout), float(cleanup)
        self._tasks: set[asyncio.Task[NativeAck]] = set()
        self._closing = False
        self._counts = {"started": 0, "accepted": 0, "replayed": 0, "rejected": 0, "unknown": 0}

    def metrics(self) -> dict[str, int]:
        return {**self._counts, "active": len(self._tasks)}

    async def accept(self, input: NativeInput) -> NativeAck:
        if (
            type(input) is not NativeInput
            or input.room_id != self._binding.room_id
            or input.participant_id != self._binding.participant_id
        ):
            raise NativeError("forbidden")
        if self._closing:
            raise NativeError("closed")
        if len(self._tasks) >= 2:
            raise NativeError("capacity_exhausted")
        task = asyncio.create_task(self._exchange(input), name="native-intake-http")
        self._tasks.add(task)
        self._counts["started"] += 1

        def settled(done: asyncio.Task[NativeAck]) -> None:
            self._tasks.discard(done)
            if not done.cancelled():
                done.exception()

        task.add_done_callback(settled)
        return await asyncio.shield(task)

    async def _exchange(self, input: NativeInput) -> NativeAck:
        deadline = time.monotonic() + self._timeout
        writer: asyncio.StreamWriter | None = None
        unknown = NativeAck(
            self._binding.binding_id,
            input.input_id,
            input.channel,
            "unknown",
            code="acknowledgement_unknown",
        )
        try:
            async with asyncio.timeout(self._timeout):
                reader, writer = await asyncio.open_connection(
                    self._endpoint.host, self._endpoint.port, limit=4096
                )
                raw = json.dumps(
                    input.payload(), ensure_ascii=False, separators=(",", ":"), allow_nan=False
                ).encode("utf-8")
                if len(raw) > 16384:
                    raise NativeError()
                head = (
                    f"POST /v1/native/accept HTTP/1.1\r\nHost: 127.0.0.1:{self._endpoint.port}\r\nAuthorization: Bearer {self._credential.value}\r\nContent-Type: application/json\r\nContent-Length: {len(raw)}\r\nConnection: close\r\n\r\n"
                ).encode("ascii")
                writer.write(head + raw)
                await writer.drain()
                rawhead = await reader.readuntil(b"\r\n\r\n")
                if len(rawhead) > 4096:
                    raise NativeError()
                lines = rawhead.decode("ascii").split("\r\n")
                parts = lines[0].split(" ")
                if (
                    len(parts) < 3
                    or parts[0] != "HTTP/1.1"
                    or parts[1] not in ("200", "400", "401", "403", "409", "413", "429", "503")
                ):
                    raise NativeError()
                headers: dict[str, str] = {}
                for line in lines[1:-2]:
                    name, value = line.split(":", 1)
                    name = name.lower()
                    if name in headers or name not in (
                        "content-type",
                        "content-length",
                        "connection",
                        "date",
                        "server",
                        "cache-control",
                    ):
                        raise NativeError()
                    headers[name] = value.strip()
                size = headers.get("content-length", "")
                if (
                    headers.get("connection") != "close"
                    or headers.get("content-type") != "application/json"
                    or not size.isascii()
                    or not size.isdecimal()
                    or size.startswith("0")
                    or not 1 <= int(size) <= 2048
                ):
                    raise NativeError()
                body = await reader.readexactly(int(size))
                response = decode(body, 2048)
                if await reader.read(1) != b"":
                    raise NativeError()
                if time.monotonic() >= deadline:
                    raise NativeError()
                if parts[1] == "200":
                    result = ack_from(response, self._binding, input)
                    if result.status not in ("accepted", "replayed"):
                        raise NativeError()
                else:
                    error = fields(response, {"schemaVersion", "status", "code"})
                    if (
                        type(error["schemaVersion"]) is not int
                        or error["schemaVersion"] != 1
                        or error["code"] not in CODES
                    ):
                        raise NativeError()
                    code = cast(NativeCode, error["code"])
                    if error["status"] == "unknown" and code == "acknowledgement_unknown":
                        result = unknown
                    elif error["status"] == "rejected" and code != "acknowledgement_unknown":
                        result = NativeAck(
                            self._binding.binding_id,
                            input.input_id,
                            input.channel,
                            "rejected",
                            code=code,
                        )
                    else:
                        raise NativeError()
                self._counts[result.status] += 1
                return result
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - Unvalidated/lost external ACK remains uncertainty.
            self._counts["unknown"] += 1
            return unknown
        finally:
            if writer is not None:
                writer.close()
                # Closing remains owned even if the waiter stopped waiting.
                try:
                    await writer.wait_closed()
                except OSError:
                    pass  # Actual close settled with a fixed local socket error.

    async def aclose(self) -> None:
        self._closing = True
        pending = tuple(self._tasks)
        try:
            async with asyncio.timeout(self._cleanup):
                if pending:
                    await asyncio.shield(asyncio.gather(*pending, return_exceptions=True))
        except TimeoutError:
            raise NativeCleanupIncomplete() from None
        if self._tasks:
            raise NativeCleanupIncomplete()
