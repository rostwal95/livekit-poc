"""Thin configured loopback HTTP host; no workflow, client or session construction."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import math
import os
import re
import stat
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal
from urllib.parse import urlsplit

from aiohttp import web

SESSION = "/v1/p3-native/session"
OBSERVATION = "/v1/p3-native/observation"
OBSERVATION_KEYS = frozenset(
    [
        "schema_version",
        "kind",
        "binding",
        "state",
        "tool_waiter",
        "owned_run",
        "work",
        "attempt",
        "result",
        "applicability",
        "app_read_completed_at_ms",
        "error",
        "consistency",
    ]
)
_SESSION_KEYS = frozenset(
    [
        "schema_version",
        "kind",
        "session_id",
        "binding",
        "server_url",
        "room_name",
        "participant_identity",
        "agent_identity",
        "rtc_token",
        "profile",
        "inference_mode",
        "expires_at_ms",
    ]
)
_QUIET = logging.getLogger(__name__ + ".quiet")
_QUIET.disabled = True
_QUIET.propagate = False
Observe = Callable[[], Awaitable[bytes]]
Code = Literal["invalid_configuration", "closed", "unavailable", "cleanup_incomplete"]


class NativePolicyHttpError(RuntimeError):
    def __init__(self, code: Code) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class HttpEndpoint:
    host: Literal["127.0.0.1"]
    port: int

    @property
    def origin(self) -> str:
        return f"http://{self.host}:{self.port}"


def _object(raw: bytes, maximum: int) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    def invalid(_: str) -> Any:
        raise ValueError

    if type(raw) is not bytes or not 1 <= len(raw) <= maximum:
        raise ValueError
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid)
    count = 0

    def check(item: Any, depth: int) -> None:
        nonlocal count
        count += 1
        if depth > 8 or count > 256:
            raise ValueError
        if type(item) is str:
            item.encode("utf-8")
        elif type(item) is dict:
            for key, child in item.items():
                check(key, depth + 1)
                check(child, depth + 1)
        elif type(item) is list:
            for child in item:
                check(child, depth + 1)
        elif item is not None and type(item) not in (int, bool):
            raise ValueError

    check(value, 0)
    if type(value) is not dict:
        raise ValueError
    return value


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _assets(directory: Path | None) -> dict[str, tuple[bytes, str]]:
    if directory is None:
        return {}
    if not directory.is_absolute() or directory != directory.resolve():
        raise ValueError
    for path in (directory, *directory.parents):
        if path.is_symlink():
            raise ValueError
    if (
        not directory.is_dir()
        or directory.stat().st_uid != os.getuid()
        or directory.stat().st_mode & 0o022
    ):
        raise ValueError
    result: dict[str, tuple[bytes, str]] = {}
    total = 0
    for index, path in enumerate(directory.rglob("*")):
        if index >= 128:
            raise ValueError
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise ValueError
        if stat.S_ISDIR(info.st_mode):
            continue
        relative = path.relative_to(directory).as_posix()
        if not (
            relative
            in {
                "p3-background.html",
                "vendor/livekit/lk-logo-dark.svg",
                "vendor/livekit/PublicSans-Regular.woff2",
                "vendor/livekit/PublicSans-SemiBold.woff2",
                "vendor/livekit/commit-mono-400-regular.woff",
            }
            or re.fullmatch(r"assets/[A-Za-z0-9_.-]{1,128}\.(js|css|woff2|svg|png)", relative)
        ):
            continue
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or info.st_mode & 0o022
        ):
            raise ValueError
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            raw = stream.read(2 * 1024 * 1024 + 1)
            after = os.fstat(stream.fileno())
        if (info.st_dev, info.st_ino, info.st_size) != (after.st_dev, after.st_ino, len(raw)):
            raise ValueError
        total += len(raw)
        if len(raw) > 2 * 1024 * 1024 or total > 4 * 1024 * 1024 or len(result) >= 64:
            raise ValueError
        mime = {
            ".html": "text/html",
            ".js": "text/javascript",
            ".css": "text/css",
            ".woff2": "font/woff2",
            ".woff": "font/woff",
            ".svg": "image/svg+xml",
            ".png": "image/png",
        }[path.suffix]
        result["/" + relative] = (raw, mime)
    if "/p3-background.html" not in result:
        raise ValueError
    result["/"] = result["/p3-background.html"]
    return result


def _consume(task: asyncio.Task[Any]) -> None:
    if not task.cancelled():
        task.exception()


class NativePolicyHttp:
    """Own only HTTP and supplied observation calls; parent owns every product port.

    Four admitted handlers and one actual observation are bounded. aiohttp's
    public connection count is observational, not a global socket admission cap.
    Built assets are snapshotted once; their origin's fixed port is used by start.
    """

    def __init__(
        self,
        session_json: bytes,
        observe: Observe,
        *,
        operator_token: str,
        ui_origin: str | None = None,
        assets: Path | None = None,
        read_timeout_s: float = 2,
        cleanup_timeout_s: float = 1,
    ) -> None:
        try:
            if (
                ui_origin is not None
                and type(ui_origin) is not str
                or assets is not None
                and not isinstance(assets, Path)
            ):
                raise ValueError
            session = _object(session_json, 8192)
            if (
                set(session) != _SESSION_KEYS
                or type(session["schema_version"]) is not int
                or session["schema_version"] != 1
                or session["kind"] != "native-policy.session"
                or type(session["binding"]) is not dict
            ):
                raise ValueError
            origin = None if ui_origin is None else urlsplit(ui_origin)
            if origin is not None and (
                origin.scheme != "http"
                or origin.hostname not in {"127.0.0.1", "localhost"}
                or origin.port is None
                or not 1 <= origin.port <= 65535
                or origin.path
                or origin.query
                or origin.fragment
                or ui_origin != f"http://{origin.hostname}:{origin.port}"
            ):
                raise ValueError
            if (
                type(operator_token) is not str
                or re.fullmatch(r"[A-Za-z0-9_-]{43}", operator_token) is None
                or not callable(observe)
            ):
                raise ValueError
            if any(
                type(v) not in (int, float) or not math.isfinite(v) or not 0.01 <= v <= 3
                for v in (read_timeout_s, cleanup_timeout_s)
            ):
                raise ValueError
            self._assets = _assets(assets)
            self._binding = _canonical(session["binding"])
        except (ValueError, TypeError, OSError, UnicodeError, RecursionError):
            raise NativePolicyHttpError("invalid_configuration") from None
        self._session, self._observe = session_json, observe
        self._authorization = ("Bearer " + operator_token).encode("ascii")
        self._origin, self._origin_port = ui_origin, origin.port if origin is not None else None
        self._read_timeout, self._cleanup_timeout = read_timeout_s, cleanup_timeout_s
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._start_task: asyncio.Task[HttpEndpoint] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._read: asyncio.Task[bytes] | None = None
        self._handlers: set[asyncio.Task[Any]] = set()
        self._closing = self._closed = self._ready = False
        self._port = 0
        self._counts = {
            "handlers_started": 0,
            "reads_started": 0,
            "reads_finished": 0,
            "rejected": 0,
        }

    def metrics(self) -> Mapping[str, int]:
        server = self._runner.server if self._runner is not None else None
        return MappingProxyType(
            {
                **self._counts,
                "active_handlers": len(self._handlers),
                "active_reads": int(self._read is not None),
                "connections": len(server.connections) if server else 0,
                "closing": int(self._closing),
                "closed": int(self._closed),
            }
        )

    def stop(self) -> None:
        self._closing = True
        self._ready = False

    async def start(self) -> HttpEndpoint:
        if self._closing:
            raise NativePolicyHttpError("closed")
        if self._start_task is None:
            self._start_task = asyncio.create_task(self._start())
            self._start_task.add_done_callback(_consume)
        try:
            return await asyncio.wait_for(asyncio.shield(self._start_task), self._read_timeout)
        except Exception:  # noqa: BLE001 - Body-free public startup boundary.
            raise NativePolicyHttpError("closed" if self._closing else "unavailable") from None

    async def _start(self) -> HttpEndpoint:
        app = web.Application(client_max_size=1, logger=_QUIET)
        app.router.add_route("*", "/{path:.*}", self._handle)
        self._runner = web.AppRunner(
            app,
            access_log=None,
            logger=_QUIET,
            shutdown_timeout=self._cleanup_timeout,
            handler_cancellation=True,
            keepalive_timeout=1,
            lingering_time=0,
            max_line_size=2048,
            max_field_size=2048,
            max_headers=32,
        )
        await self._runner.setup()
        if self._closing:
            raise NativePolicyHttpError("closed")
        self._site = web.TCPSite(
            self._runner,
            "127.0.0.1",
            self._origin_port if self._assets and self._origin_port is not None else 0,
            backlog=8,
        )
        await self._site.start()
        addresses = self._runner.addresses
        if len(addresses) != 1:
            raise NativePolicyHttpError("unavailable")
        self._port = int(addresses[0][1])
        if self._closing:
            raise NativePolicyHttpError("closed")
        endpoint = HttpEndpoint("127.0.0.1", self._port)
        if self._origin is None:
            self._origin, self._origin_port = endpoint.origin, self._port
        self._ready = True
        return endpoint

    def _response(
        self, request: web.Request, status: int, raw: bytes, mime: str = "application/json"
    ) -> web.Response:
        headers = {"Cache-Control": "no-store"}
        if self._origin is not None and request.headers.get("Origin") == self._origin:
            headers.update({"Access-Control-Allow-Origin": self._origin, "Vary": "Origin"})
        response = web.Response(status=status, body=raw, content_type=mime, headers=headers)
        response.force_close()
        return response

    def _error(self, request: web.Request, status: int, code: str) -> web.Response:
        self._counts["rejected"] += 1
        return self._response(
            request,
            status,
            _canonical({"schema_version": 1, "kind": "native-policy.error", "code": code}),
        )

    async def _handle(self, request: web.Request) -> web.Response:
        if len(self._handlers) >= 4:
            return self._error(request, 503, "unavailable")
        task = asyncio.current_task()
        assert task is not None
        self._handlers.add(task)
        self._counts["handlers_started"] += 1
        try:
            return await self._dispatch(request)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - Never reflect callback/dependency errors.
            return self._error(request, 503, "unavailable")
        finally:
            self._handlers.discard(task)

    async def _dispatch(self, request: web.Request) -> web.Response:
        if not self._ready:
            return self._error(request, 503, "closed" if self._closing else "unavailable")
        origins = request.headers.getall("Origin", [])
        if len(origins) > 1 or origins and origins[0] != self._origin:
            return self._error(request, 403, "forbidden")
        allowed_hosts = {f"127.0.0.1:{self._port}", f"localhost:{self._port}"}
        if self._origin is not None:
            allowed_hosts.add(urlsplit(self._origin).netloc)
        hosts = request.headers.getall("Host", [])
        if len(hosts) != 1 or hosts[0] not in allowed_hosts:
            return self._error(request, 403, "forbidden")
        path = request.raw_path
        api = path in (SESSION, OBSERVATION)
        if request.method == "OPTIONS":
            method = "POST" if path == SESSION else "GET"
            headers = {
                v.strip().lower()
                for v in request.headers.get("Access-Control-Request-Headers", "").split(",")
                if v.strip()
            }
            if (
                not api
                or origins != [self._origin]
                or request.headers.get("Access-Control-Request-Method") != method
                or not headers <= {"authorization", "content-type"}
            ):
                return self._error(request, 403, "forbidden")
            response = self._response(request, 204, b"")
            response.headers.update(
                {
                    "Access-Control-Allow-Methods": method,
                    "Access-Control-Allow-Headers": "Authorization, Content-Type",
                }
            )
            return response
        if not api:
            if path.split("?", 1)[0] in (SESSION, OBSERVATION):
                return self._error(request, 400, "invalid_request")
            asset = self._assets.get(path)
            if asset is not None and request.method == "GET":
                return self._response(request, 200, *asset)
            return self._error(request, 404, "invalid_request")
        auth = request.headers.getall("Authorization", [])
        if len(auth) != 1 or not hmac.compare_digest(auth[0].encode("utf-8"), self._authorization):
            return self._error(request, 401, "unauthorized")
        if self._closing:
            return self._error(request, 503, "closed")
        if request.method != ("POST" if path == SESSION else "GET"):
            return self._error(request, 405, "invalid_request")
        if request.content_length not in (None, 0) or "Transfer-Encoding" in request.headers:
            return self._error(request, 400, "invalid_request")
        if path == SESSION:
            return self._response(request, 200, self._session)
        if self._read is not None:
            return self._error(request, 503, "unavailable")
        self._read = asyncio.create_task(self._read_observation())
        self._counts["reads_started"] += 1
        self._read.add_done_callback(self._read_done)
        try:
            raw = await asyncio.wait_for(asyncio.shield(self._read), self._read_timeout)
        except TimeoutError:
            return self._error(request, 503, "unavailable")
        if self._closing:
            return self._error(request, 503, "closed")
        return self._response(request, 200, raw)

    async def _read_observation(self) -> bytes:
        raw = await self._observe()
        value = _object(raw, 4096)
        if (
            set(value) != OBSERVATION_KEYS
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 1
            or value["kind"] != "native-policy.observation"
            or _canonical(value["binding"]) != self._binding
        ):
            raise ValueError
        return raw

    def _read_done(self, task: asyncio.Task[bytes]) -> None:
        self._counts["reads_finished"] += 1
        if not task.cancelled():
            task.exception()
        if self._read is task:
            self._read = None

    async def close(self) -> None:
        self.stop()
        if (
            self._close_task is None
            or self._close_task.done()
            and (self._close_task.cancelled() or self._close_task.exception() is not None)
        ):
            self._close_task = asyncio.create_task(self._close_owned())
            self._close_task.add_done_callback(_consume)
        try:
            await asyncio.wait_for(asyncio.shield(self._close_task), self._cleanup_timeout)
        except Exception:  # noqa: BLE001 - Retain actual owners and expose only a safe code.
            raise NativePolicyHttpError("cleanup_incomplete") from None

    async def _close_owned(self) -> None:
        if self._start_task is not None:
            await asyncio.gather(self._start_task, return_exceptions=True)
        if self._site is not None and self._runner is not None and self._site in self._runner.sites:
            await self._site.stop()
        if self._read is not None:
            await asyncio.gather(self._read, return_exceptions=True)
        if self._handlers:
            await asyncio.gather(*tuple(self._handlers), return_exceptions=True)
        if self._runner is not None:
            await self._runner.cleanup()
        self._closed = True
