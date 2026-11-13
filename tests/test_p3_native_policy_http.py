"""Pure and ephemeral-loopback controls; no PG, SFU, product clients or browser."""

from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
import logging
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import aiohttp
from aiohttp import web

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "native_policy_http_tested", ROOT / "local-setup/scripts/p3_native_policy_http.py"
)
assert spec and spec.loader
import sys

m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
TOKEN = "q" * 43
ORIGIN = "http://127.0.0.1:5173"


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def binding():
    return {
        "scope": {"tenant_id": "tenant_demo", "account_id": "account_demo"},
        "case_id": "case_demo",
        "delegation_id": "delegation_demo",
        "request_revision": 1,
        "input_fingerprint": "3" * 64,
        "sources": [
            {
                "role": role,
                "source_id": role + "_source",
                "version": "source_v1",
                "sha256": digit * 64,
                "byte_length": 128,
            }
            for role, digit in (("policy", "1"), ("facts", "2"))
        ],
    }


def session():
    return {
        "schema_version": 1,
        "kind": "native-policy.session",
        "session_id": "33333333-3333-4333-8333-333333333333",
        "binding": binding(),
        "server_url": "ws://127.0.0.1:17880",
        "room_name": "p3_native_demo",
        "participant_identity": "p3_viewer_demo",
        "agent_identity": "p3_agent_demo",
        "rtc_token": "a" * 64 + "." + "b" * 64 + "." + "c" * 43,
        "profile": "p3_native_policy_text_v1",
        "inference_mode": "scripted",
        "expires_at_ms": 1794480060000,
    }


def observation():
    return {
        "schema_version": 1,
        "kind": "native-policy.observation",
        "binding": binding(),
        "state": "no_work",
        "tool_waiter": "idle",
        "owned_run": False,
        "work": None,
        "attempt": None,
        "result": None,
        "applicability": None,
        "app_read_completed_at_ms": 1794480000101,
        "error": None,
        "consistency": "as_of_non_atomic",
    }


class ConfigurationTests(unittest.TestCase):
    def test_constructor_is_inert_and_rejects_unsafe_frame_token_origin_or_bounds(self):
        async def observe():
            raise AssertionError("must not be called")

        with patch.object(web, "AppRunner", side_effect=AssertionError("must not start")):
            m.NativePolicyHttp(encode(session()), observe, operator_token=TOKEN, ui_origin=ORIGIN)
            for kwargs in (
                {"operator_token": session()["rtc_token"]},
                {"ui_origin": "http://example.com:80"},
                {"ui_origin": "http://127.0.0.1:0"},
                {"ui_origin": {}},
                {"assets": "arbitrary-selector"},
                {"read_timeout_s": True},
                {"cleanup_timeout_s": float("inf")},
            ):
                with self.subTest(kwargs=list(kwargs)), self.assertRaises(m.NativePolicyHttpError):
                    m.NativePolicyHttp(
                        encode(session()),
                        observe,
                        **{"operator_token": TOKEN, "ui_origin": ORIGIN, **kwargs},
                    )
            for raw in (
                b"[]",
                b'{"schema_version":1,"schema_version":1}',
                encode({**session(), "schema_version": True}),
                b" " * 8193,
                encode({**session(), "kind": "wrong"}),
            ):
                with self.subTest(bytes=len(raw)), self.assertRaises(m.NativePolicyHttpError):
                    m.NativePolicyHttp(raw, observe, operator_token=TOKEN, ui_origin=ORIGIN)


class HttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hosts = []
        self.releases = []
        self.client = aiohttp.ClientSession(trust_env=False, timeout=aiohttp.ClientTimeout(total=3))

    async def asyncTearDown(self):
        for release in self.releases:
            release.set()
        await self.client.close()
        for host in self.hosts:
            await host.close()
            self.assertEqual(host.metrics()["active_reads"], 0)
            self.assertEqual(host.metrics()["active_handlers"], 0)
            self.assertEqual(host.metrics()["connections"], 0)
            self.assertEqual(host.metrics()["closed"], 1)

    async def host(self, observe=None, **kwargs):
        if observe is None:

            async def observe():
                return encode(observation())

        value = m.NativePolicyHttp(
            encode(session()),
            observe,
            operator_token=TOKEN,
            ui_origin=kwargs.pop("ui_origin", ORIGIN),
            **kwargs,
        )
        self.hosts.append(value)
        endpoint = await value.start()
        return value, f"http://{endpoint.host}:{endpoint.port}"

    async def request(self, base, method, path, *, auth=True, **kwargs):
        headers = kwargs.pop("headers", {})
        if auth:
            headers = {"Authorization": "Bearer " + TOKEN, **headers}
        async with self.client.request(method, base + path, headers=headers, **kwargs) as response:
            raw = await response.read()
            self.assertEqual(response.headers.get("Cache-Control"), "no-store")
            self.assertNotIn("Set-Cookie", response.headers)
            return response.status, raw, response.headers

    async def wait(self, predicate):
        async with asyncio.timeout(2):
            while not predicate():
                await asyncio.sleep(0.005)

    async def test_original_session_replay_and_valid_observation_are_exact_and_no_work_is_created(
        self,
    ):
        calls = 0

        async def observe():
            nonlocal calls
            calls += 1
            return encode(observation())

        host, base = await self.host(observe)
        for _ in range(2):
            status, raw, _ = await self.request(base, "POST", m.SESSION)
            self.assertEqual((status, raw), (200, encode(session())))
        self.assertEqual(calls, 0)
        status, raw, headers = await self.request(
            base, "GET", m.OBSERVATION, headers={"Origin": ORIGIN}
        )
        self.assertEqual((status, raw), (200, encode(observation())))
        self.assertEqual(headers["Access-Control-Allow-Origin"], ORIGIN)
        self.assertEqual(calls, 1)
        self.assertEqual(host.metrics()["reads_started"], 1)

    async def test_start_pins_actual_origin_and_fixed_vite_proxy_host_is_supported(self):
        async def observe():
            return encode(observation())

        host = m.NativePolicyHttp(encode(session()), observe, operator_token=TOKEN)
        self.hosts.append(host)
        endpoint = await host.start()
        status, _, headers = await self.request(
            endpoint.origin, "POST", m.SESSION, headers={"Origin": endpoint.origin}
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers["Access-Control-Allow-Origin"], endpoint.origin)
        self.assertEqual(
            (await self.request(endpoint.origin, "GET", m.OBSERVATION, headers={"Origin": ORIGIN}))[
                0
            ],
            403,
        )
        _, base = await self.host()
        status, _, _ = await self.request(
            base, "GET", m.OBSERVATION, headers={"Host": "127.0.0.1:5173", "Origin": ORIGIN}
        )
        self.assertEqual(status, 200)

    async def test_auth_origin_host_method_path_query_and_body_fail_with_fixed_small_errors(self):
        host, base = await self.host()
        cases = [
            ("GET", m.OBSERVATION, {"auth": False}, 401),
            (
                "GET",
                m.OBSERVATION,
                {"headers": {"Authorization": "Bearer " + session()["rtc_token"]}},
                401,
            ),
            ("GET", m.OBSERVATION, {"headers": {"Origin": "http://localhost:9999"}}, 403),
            ("GET", m.OBSERVATION, {"headers": {"Host": "foreign.example"}}, 403),
            ("POST", m.OBSERVATION, {}, 405),
            ("GET", m.SESSION, {}, 405),
            ("GET", "/missing", {}, 404),
            ("GET", m.OBSERVATION + "?work_id=foreign", {}, 400),
            ("POST", m.SESSION, {"data": b"{}"}, 400),
            ("GET", m.OBSERVATION, {"data": b"x"}, 400),
        ]
        for method, path, kwargs, expected in cases:
            with self.subTest(method=method, path=path, status=expected):
                status, raw, _ = await self.request(base, method, path, **kwargs)
                self.assertEqual(status, expected)
                self.assertLessEqual(len(raw), 256)
                self.assertEqual(set(json.loads(raw)), {"schema_version", "kind", "code"})
                self.assertNotIn(TOKEN.encode(), raw)
        self.assertEqual(host.metrics()["reads_started"], 0)
        host.stop()
        status, raw, _ = await self.request(base, "POST", m.SESSION)
        self.assertEqual((status, json.loads(raw)["code"]), (503, "closed"))

    async def test_preflight_is_only_exact_origin_route_method_and_header_subset(self):
        _, base = await self.host()
        for path, method in ((m.SESSION, "POST"), (m.OBSERVATION, "GET")):
            headers = {
                "Origin": ORIGIN,
                "Access-Control-Request-Method": method,
                "Access-Control-Request-Headers": "Authorization, Content-Type",
            }
            status, raw, response = await self.request(
                base, "OPTIONS", path, auth=False, headers=headers
            )
            self.assertEqual((status, raw), (204, b""))
            self.assertEqual(response["Access-Control-Allow-Methods"], method)
            self.assertNotIn("Access-Control-Allow-Credentials", response)
            for wrong in (
                {"Origin": "http://localhost:3333"},
                {"Access-Control-Request-Method": "DELETE"},
                {"Access-Control-Request-Headers": "Cookie"},
            ):
                status, _, _ = await self.request(
                    base, "OPTIONS", path, auth=False, headers={**headers, **wrong}
                )
                self.assertEqual(status, 403)

    async def test_timeout_retains_one_actual_read_and_release_restores_useful_progress(self):
        entered, release = asyncio.Event(), asyncio.Event()
        self.releases.append(release)
        calls = 0

        async def observe():
            nonlocal calls
            calls += 1
            entered.set()
            await release.wait()
            return encode(observation())

        host, base = await self.host(observe, read_timeout_s=0.03)
        first = asyncio.create_task(self.request(base, "GET", m.OBSERVATION))
        await entered.wait()
        self.assertEqual((await first)[0], 503)
        self.assertEqual(host.metrics()["active_reads"], 1)
        self.assertEqual((await self.request(base, "GET", m.OBSERVATION))[0], 503)
        self.assertEqual(calls, 1)
        release.set()
        await self.wait(lambda: host.metrics()["active_reads"] == 0)
        self.assertEqual((await self.request(base, "GET", m.OBSERVATION))[0], 200)
        self.assertEqual(calls, 2)

    async def test_cancel_and_incomplete_close_preserve_callback_owner_until_actual_release(self):
        entered, release = asyncio.Event(), asyncio.Event()
        self.releases.append(release)
        cancelled = False

        async def observe():
            nonlocal cancelled
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled = True
                raise
            return encode(observation())

        host, base = await self.host(observe, read_timeout_s=1, cleanup_timeout_s=0.03)
        request = asyncio.create_task(self.request(base, "GET", m.OBSERVATION))
        await entered.wait()
        request.cancel()
        await asyncio.gather(request, return_exceptions=True)
        with self.assertRaises(m.NativePolicyHttpError) as caught:
            await host.close()
        self.assertEqual(caught.exception.code, "cleanup_incomplete")
        self.assertEqual(host.metrics()["active_reads"], 1)
        self.assertEqual(host.metrics()["closed"], 0)
        self.assertFalse(cancelled)
        release.set()
        await self.wait(lambda: host.metrics()["active_reads"] == 0)
        await host.close()
        self.assertEqual(host.metrics()["closed"], 1)

    async def test_bad_callback_binding_shape_size_and_exceptions_never_escape(self):
        candidate = encode(observation())

        async def observe():
            if isinstance(candidate, BaseException):
                raise candidate
            return candidate

        host, base = await self.host(observe)
        other = copy.deepcopy(observation())
        other["binding"]["scope"]["account_id"] = "foreign"
        for candidate in (
            encode(other),
            encode({**observation(), "secret": "PRIVATE_SENTINEL"}),
            b"x" * 4097,
            b'{"kind":"x","kind":"y"}',
            RuntimeError("PRIVATE_SENTINEL"),
        ):
            status, raw, _ = await self.request(base, "GET", m.OBSERVATION)
            self.assertEqual(status, 503)
            self.assertNotIn(b"PRIVATE_SENTINEL", raw)
            self.assertLessEqual(len(raw), 256)
        candidate = encode(observation())
        self.assertEqual((await self.request(base, "GET", m.OBSERVATION))[0], 200)
        self.assertEqual(host.metrics()["active_reads"], 0)

    async def test_browser_sized_header_set_fits_while_count_overflow_stays_rejected(self):
        host, base = await self.host()
        port = int(base.rsplit(":", 1)[1])
        headers = [
            ("Host", f"127.0.0.1:{port}"),
            ("Authorization", "Bearer " + TOKEN),
            ("Accept", "application/json"),
            ("Origin", ORIGIN),
            ("Connection", "close"),
            ("Content-Length", "0"),
            ("Sec-CH-UA", '"Chromium";v="131"'),
            ("Sec-CH-UA-Mobile", "?0"),
            ("Sec-CH-UA-Platform", '"macOS"'),
            ("User-Agent", "Synthetic Chromium regression"),
            ("Sec-Fetch-Site", "same-origin"),
            ("Sec-Fetch-Mode", "cors"),
            ("Sec-Fetch-Dest", "empty"),
            ("Accept-Encoding", "gzip, deflate"),
            ("Accept-Language", "en-US"),
            ("Cache-Control", "no-cache"),
            ("Pragma", "no-cache"),
            ("DNT", "1"),
        ]
        self.assertEqual(len(headers), 18)
        for count, expected_status in ((18, b"200"), (33, b"400")):
            expanded = headers + [("X-Fixture-" + str(i), "1") for i in range(count - 18)]
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            try:
                request = (
                    "POST /v1/p3-native/session HTTP/1.1\r\n"
                    + "".join(name + ": " + value + "\r\n" for name, value in expanded)
                    + "\r\n"
                )
                writer.write(request.encode("ascii"))
                await writer.drain()
                response = await asyncio.wait_for(reader.read(16384), 1)
                self.assertEqual(response.split(None, 2)[1], expected_status)
                if count == 18:
                    head = response.partition(b"\r\n\r\n")[0].lower()
                    self.assertIn(b"content-type: application/json", head)
                    self.assertIn(b"cache-control: no-store", head)
            finally:
                writer.close()
                await writer.wait_closed()
        self.assertEqual(host.metrics()["reads_started"], 0)

    async def test_parser_and_callback_failures_do_not_emit_private_raw_logs(self):
        async def observe():
            raise RuntimeError("CALLBACK_PRIVATE_SENTINEL")

        _, base = await self.host(observe)
        records = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        capture = Capture()
        logger = logging.getLogger()
        logger.addHandler(capture)
        try:
            port = int(base.rsplit(":", 1)[1])
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            try:
                raw = (
                    b"GET /v1/p3-native/observation HTTP/1.1\r\nHost: 127.0.0.1:"
                    + str(port).encode()
                    + b"\r\nX-Private: PARSER_PRIVATE_SENTINEL"
                    + b"x" * 2200
                    + b"\r\n\r\n"
                )
                writer.write(raw)
                await writer.drain()
                response = await asyncio.wait_for(reader.read(8192), 1)
                self.assertEqual(response.split(None, 2)[1], b"400")
            finally:
                writer.close()
                await writer.wait_closed()
            status, raw, _ = await self.request(base, "GET", m.OBSERVATION)
            self.assertEqual(status, 503)
            self.assertNotIn(b"CALLBACK_PRIVATE_SENTINEL", raw)
            self.assertFalse(any("PRIVATE_SENTINEL" in value for value in records))
        finally:
            logger.removeHandler(capture)

    async def test_partial_start_and_cleanup_failure_retain_same_public_owners_for_retry(self):
        async def observe():
            return encode(observation())

        host = m.NativePolicyHttp(
            encode(session()),
            observe,
            operator_token=TOKEN,
            ui_origin=ORIGIN,
            read_timeout_s=0.03,
            cleanup_timeout_s=0.03,
        )
        self.hosts.append(host)
        entered, release = asyncio.Event(), asyncio.Event()
        self.releases.append(release)
        original = web.TCPSite.start

        async def held(site):
            entered.set()
            await release.wait()
            await original(site)

        with patch.object(web.TCPSite, "start", held):
            starting = asyncio.create_task(host.start())
            await entered.wait()
            starting.cancel()
            await asyncio.gather(starting, return_exceptions=True)
            with self.assertRaises(m.NativePolicyHttpError):
                await host.close()
            release.set()
            await self.wait(lambda: host.metrics()["closed"] == 1)
        await host.close()
        second, _ = await self.host()
        with patch.object(web.AppRunner, "cleanup", side_effect=RuntimeError("CLEANUP_SECRET")):
            with self.assertRaises(m.NativePolicyHttpError) as caught:
                await second.close()
            self.assertEqual(str(caught.exception), "cleanup_incomplete")
            self.assertEqual(second.metrics()["closed"], 0)
        await second.close()
        self.assertEqual(second.metrics()["closed"], 1)

    async def test_direct_built_page_serves_exact_declared_logo_and_fonts_only(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
            root = Path(directory).resolve()
            (root / "vendor/livekit").mkdir(parents=True)
            page = b'<img src="/vendor/livekit/lk-logo-dark.svg" alt="LiveKit">'
            vendor = ROOT / "apps/local-console/public/vendor/livekit"
            expected = {
                "lk-logo-dark.svg": (
                    vendor.joinpath("lk-logo-dark.svg").read_bytes(),
                    "image/svg+xml",
                ),
                "PublicSans-Regular.woff2": (
                    vendor.joinpath("PublicSans-Regular.woff2").read_bytes(),
                    "font/woff2",
                ),
                "PublicSans-SemiBold.woff2": (
                    vendor.joinpath("PublicSans-SemiBold.woff2").read_bytes(),
                    "font/woff2",
                ),
                "commit-mono-400-regular.woff": (
                    vendor.joinpath("commit-mono-400-regular.woff").read_bytes(),
                    "font/woff",
                ),
            }
            (root / "p3-background.html").write_bytes(page)
            for name, (raw, _) in expected.items():
                (root / "vendor/livekit" / name).write_bytes(raw)
            (root / "vendor/livekit/other.svg").write_bytes(b"UNDECLARED_VENDOR_FILE")
            _, base = await self.host(assets=root, ui_origin=None)
            self.assertEqual(
                (await self.request(base, "GET", "/p3-background.html", auth=False))[:2],
                (200, page),
            )
            for name, (expected_raw, mime) in expected.items():
                status, raw, headers = await self.request(
                    base, "GET", "/vendor/livekit/" + name, auth=False
                )
                self.assertEqual((status, raw), (200, expected_raw))
                self.assertEqual(headers["Content-Type"], mime)
            self.assertEqual(
                (await self.request(base, "GET", "/vendor/livekit/other.svg", auth=False))[0],
                404,
            )
            (root / "vendor/livekit/lk-logo-dark.svg").unlink()
            (root / "vendor/livekit/lk-logo-dark.svg").symlink_to(root / "p3-background.html")
            with self.assertRaises(m.NativePolicyHttpError):
                m.NativePolicyHttp(
                    encode(session()), lambda: None, operator_token=TOKEN, assets=root
                )

    async def test_optional_fixed_assets_are_snapshotted_and_never_expose_other_paths(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
            root = Path(directory).resolve()
            (root / "assets").mkdir()
            (root / "p3-background.html").write_bytes(b"<h1>Policy</h1>")
            (root / "assets/card.js").write_bytes(b"export const ready=true;")
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            _, base = await self.host(assets=root, ui_origin=f"http://127.0.0.1:{port}")
            (root / "p3-background.html").write_bytes(b"CHANGED_AFTER_START")
            self.assertEqual(
                (await self.request(base, "GET", "/p3-background.html", auth=False))[:2],
                (200, b"<h1>Policy</h1>"),
            )
            self.assertEqual(
                (await self.request(base, "GET", "/assets/card.js", auth=False))[0], 200
            )
            self.assertEqual(
                (await self.request(base, "GET", "/owned-work.json", auth=False))[0], 404
            )
            (root / "assets/alias.js").symlink_to(root / "p3-background.html")

            async def observe():
                return encode(observation())

            with self.assertRaises(m.NativePolicyHttpError):
                m.NativePolicyHttp(
                    encode(session()), observe, operator_token=TOKEN, ui_origin=ORIGIN, assets=root
                )


if __name__ == "__main__":
    unittest.main()
