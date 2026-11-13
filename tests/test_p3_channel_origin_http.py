"""Ephemeral real socket controls; supplied service is explicit and non-durable."""

from __future__ import annotations

import asyncio
import gc
import json
import logging
import socket
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

from delegation_reliability import CoordinatorError
from services.channel_policy_demo import origin_http as m

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "q" * 43
FIXTURE = json.loads((ROOT / "contracts/delegation/channel-policy-v3.json").read_bytes())
CASE = FIXTURE["p2_cases"][0]
PROFILE = FIXTURE["profile_id"]
RECEIPT = {
    "operationKey": CASE["submission"]["operationKey"],
    "scope": CASE["submission"]["scope"],
    "payloadDigest": CASE["payload_sha256"],
    "receiptId": "22222222-2222-4222-8222-222222222222",
}


def encode(value):
    return json.dumps(value, separators=(",", ":")).encode()


def payload(route):
    if route == "accept":
        return CASE["accept_frame_canonical"].encode()
    if route == "lookup":
        return encode({key: RECEIPT[key] for key in ("operationKey", "scope", "payloadDigest")})
    return encode({"schemaVersion": 1, "profileId": PROFILE})


class Service:
    def __init__(self):
        self.calls = []
        self.entered = asyncio.Event()
        self.release = None
        self.failure = None
        self.result = RECEIPT
        self.absent = False
        self.cancelled = 0
        self.closed = 0

    async def _call(self, route, raw):
        self.calls.append((route, raw))
        self.entered.set()
        try:
            if self.release is not None:
                await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        if self.failure is not None:
            raise self.failure
        return self.result

    async def accept(self, raw):
        return await self._call("accept", raw)

    async def lookup(self, raw):
        value = await self._call("lookup", raw)
        return None if self.absent else value

    async def inspect_profile(self, raw):
        await self._call("inspect-profile", raw)

    async def close(self):
        self.closed += 1


class ConfigurationTests(unittest.TestCase):
    def test_constructor_is_inert_and_validates_closed_configuration(self):
        with patch.object(socket, "socket", side_effect=AssertionError("no listener")):
            m.ChannelOriginHttp(Service(), operation_bearer=TOKEN)
            self.assertEqual(
                m.ChannelOriginHttp.__module__, "services.channel_policy_demo.origin_http"
            )
            for changes in (
                {"operation_bearer": "x" * 42},
                {"operation_bearer": "x" * 44},
                {"operation_bearer": "-" * 42 + "!"},
                {"operation_bearer": object()},
                {"read_timeout_s": True},
                {"call_timeout_s": float("inf")},
                {"cleanup_timeout_s": 0},
                {"cleanup_timeout_s": 5.001},
                {"read_timeout_s": 10**1000},
                {"call_timeout_s": 10**1000},
                {"cleanup_timeout_s": 10**1000},
            ):
                with self.subTest(fields=list(changes)), self.assertRaises(m.OriginHttpError):
                    m.ChannelOriginHttp(Service(), **{"operation_bearer": TOKEN, **changes})

    def test_cross_loop_close_fails_before_closing_or_mutating(self):
        owner = m.ChannelOriginHttp(Service(), operation_bearer=TOKEN)

        async def first():
            owner._bind()

        asyncio.run(first())
        with self.assertRaisesRegex(m.OriginHttpError, "^invalid_configuration$"):
            asyncio.run(owner.close())
        self.assertFalse(owner.metrics()["closing"])
        self.assertIsNone(owner._close_task)


class HttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.service = Service()
        self.host = m.ChannelOriginHttp(
            self.service,
            operation_bearer=TOKEN,
            read_timeout_s=0.2,
            call_timeout_s=0.2,
            cleanup_timeout_s=0.05,
        )
        self.endpoint = await self.host.start()
        self.clients = []

    async def asyncTearDown(self):
        if self.service.release is not None:
            self.service.release.set()
        for reader, writer in self.clients:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionResetError:
                self.assertTrue(writer.is_closing())
        await self.host.close()
        self.assertEqual(self.service.closed, 0)
        self.assertEqual(self.host.metrics()["active"], 0)
        self.assertEqual(self.host.metrics()["sockets"], 0)

    def request(self, route="accept", raw=None, headers=None, first=None):
        raw = payload(route) if raw is None else raw
        frame = {
            "Host": "127.0.0.1:" + str(self.endpoint.port),
            "Authorization": "Bearer " + TOKEN,
            "Content-Type": "application/json",
            "Content-Length": str(len(raw)),
            "Connection": "close",
        }
        if headers:
            frame.update(headers)
        head = first or f"POST /v1/investigations/{route} HTTP/1.1"
        return (
            head + "\r\n" + "\r\n".join(k + ": " + v for k, v in frame.items()) + "\r\n\r\n"
        ).encode() + raw

    async def connect(self):
        reader, writer = await asyncio.open_connection(self.endpoint.host, self.endpoint.port)
        self.clients.append((reader, writer))
        return reader, writer

    async def exchange(self, frame):
        reader, writer = await self.connect()
        writer.write(frame)
        await writer.drain()
        try:
            async with asyncio.timeout(1):
                raw = await reader.read()
        except ConnectionResetError:
            return None, None, b""
        if not raw:
            return None, None, raw
        head, body = raw.split(b"\r\n\r\n", 1)
        status = int(head.split(b" ")[1])
        lines = {
            k.lower(): v.strip()
            for k, v in (line.split(b":", 1) for line in head.split(b"\r\n")[1:])
        }
        self.assertEqual(lines[b"content-type"], b"application/json")
        self.assertEqual(lines[b"connection"], b"close")
        self.assertEqual(lines[b"cache-control"], b"no-store")
        self.assertEqual(int(lines[b"content-length"]), len(body))
        self.assertLessEqual(len(body), 4096)
        self.assertNotIn(b"transfer-encoding", lines)
        return status, json.loads(body), raw

    async def settled(self, predicate):
        async with asyncio.timeout(1):
            while not predicate():
                await asyncio.sleep(0.001)

    async def test_exact_existing_client_envelopes_and_original_raw_bytes(self):
        status, reply, _ = await self.exchange(self.request("inspect-profile"))
        self.assertEqual(status, 200)
        self.assertEqual(
            reply, {"schemaVersion": 1, "status": "known", "profileId": PROFILE, "ready": True}
        )
        status, reply, _ = await self.exchange(self.request())
        self.assertEqual(status, 200)
        self.assertEqual(reply, {"schemaVersion": 1, "status": "known", "receipt": RECEIPT})
        status, reply, _ = await self.exchange(self.request("lookup"))
        self.assertEqual(status, 200)
        self.assertEqual(reply["observation"], {"status": "accepted", "receipt": RECEIPT})
        self.service.absent = True
        status, reply, _ = await self.exchange(self.request("lookup"))
        self.assertEqual(status, 200)
        self.assertEqual(reply["observation"], {"status": "absent"})
        self.assertEqual(
            self.service.calls,
            [
                (route, payload(route))
                for route in ("inspect-profile", "accept", "lookup", "lookup")
            ],
        )
        self.assertEqual(self.host.metrics()["known"], 4)

    async def test_authentication_and_route_framing_reject_before_service(self):
        original = self.request()
        cases = [
            (self.request(headers={"Authorization": "Bearer " + "r" * 43}), 403),
            (self.request(headers={"Host": "example.com"}), 400),
            (self.request(headers={"Connection": "keep-alive"}), 400),
            (self.request(headers={"Content-Type": "text/plain"}), 400),
            (self.request(headers={"Transfer-Encoding": "chunked"}), 400),
            (self.request(headers={"Content-Encoding": "gzip"}), 400),
            (self.request(headers={"Forwarded": "for=127.0.0.1"}), 400),
            (self.request(headers={"Proxy-Authorization": "Bearer secret"}), 400),
            (self.request(first="GET /v1/investigations/accept HTTP/1.1"), 400),
            (self.request(first="POST http://127.0.0.1/evil HTTP/1.1"), 400),
            (self.request(first="POST /v1/investigations/accept?x=y HTTP/1.1"), 400),
            (self.request(first="POST /v1/investigations/accept HTTP/1.0"), 400),
            (original.replace(b"Content-Length:", b"Content-Length: 1\r\nContent-Length:", 1), 400),
            (
                original.replace(
                    b"Authorization:", b"authorization: Bearer bad\r\nAuthorization:", 1
                ),
                400,
            ),
            (original.replace(b"Content-Length: ", b"Content-Length: 0", 1), 400),
            (
                original.replace(b"Connection: close\r\n", b"Connection: close\r\n folded\r\n", 1),
                400,
            ),
        ]
        for frame, expected in cases:
            with self.subTest(case=cases.index((frame, expected))):
                status, _, _ = await self.exchange(frame)
                self.assertEqual(status, expected)
        self.assertEqual(self.service.calls, [])

    async def test_size_duplicate_json_and_original_digest_fail_before_service(self):
        frames = [
            self.request(raw=b"x" * 32769),
            self.request(headers={"X-Long": "q" * 4096}),
            self.request(headers={"Content-Length": "99999"}),
            self.request(raw=b'{"schemaVersion":1,"schemaVersion":1}'),
            self.request(
                raw=CASE["accept_frame_canonical"]
                .replace(CASE["payload_sha256"], "f" * 64)
                .encode()
            ),
        ]
        for index, frame in enumerate(frames):
            with self.subTest(index=index):
                status, _reply, _ = await self.exchange(frame)
                self.assertEqual(status, 409 if index == 4 else 400)
        self.assertEqual(self.service.calls, [])

    async def test_finite_errors_and_malformed_receipts_contain_dependency_sentinels(self):
        for failure, expected in (
            (CoordinatorError("identity_conflict"), 409),
            (CoordinatorError("unauthorized"), 403),
            (CoordinatorError("capacity"), 429),
            (RuntimeError("SECRET_SENTINEL"), 503),
        ):
            self.service.failure = failure
            with self.subTest(error=type(failure).__name__):
                status, _, raw = await self.exchange(self.request())
                self.assertEqual(status, expected)
                self.assertNotIn(b"SECRET_SENTINEL", raw)
        self.service.failure = None
        for result in (
            {**RECEIPT, "debug": "SECRET_SENTINEL"},
            {**RECEIPT, "receiptId": "SECRET_SENTINEL"},
            {**RECEIPT, "payloadDigest": "f" * 64},
            {**RECEIPT, "scope": {"tenantId": "foreign", "accountId": "other"}},
        ):
            self.service.result = result
            status, reply, raw = await self.exchange(self.request())
            self.assertEqual(status, 503)
            self.assertEqual(reply["code"], "invalid_stored_state")
            self.assertNotIn(b"SECRET_SENTINEL", raw)

    async def test_exporter_failure_cannot_replace_a_successful_receipt(self):
        class Broken(logging.Handler):
            def emit(self, record):
                raise RuntimeError("SECRET_SENTINEL")

        before = m.LOGGER.level
        handler = Broken()
        m.LOGGER.addHandler(handler)
        m.LOGGER.setLevel(logging.INFO)
        try:
            status, reply, raw = await self.exchange(self.request())
        finally:
            m.LOGGER.removeHandler(handler)
            m.LOGGER.setLevel(before)
        self.assertEqual(status, 200)
        self.assertEqual(reply["receipt"], RECEIPT)
        self.assertNotIn(b"SECRET_SENTINEL", raw)
        self.assertEqual(self.host.metrics()["telemetry_failed"], 1)

    async def test_caller_abort_retains_actual_slots_and_incomplete_close_until_settlement(self):
        self.service.release = asyncio.Event()
        _reader, writer = await self.connect()
        writer.write(self.request())
        await writer.drain()
        await self.service.entered.wait()
        writer.close()
        await writer.wait_closed()
        self.assertEqual(self.host.metrics()["active"], 1)
        self.assertEqual(self.host.metrics()["handlers"], 1)
        with self.assertRaisesRegex(m.OriginHttpError, "^cleanup_incomplete$"):
            await self.host.close()
        self.assertEqual(self.host.metrics()["active"], 1)
        self.assertEqual(self.service.cancelled, 0)
        self.service.release.set()
        await self.host.close()
        self.assertEqual(self.host.metrics()["active"], 0)
        self.assertEqual(self.service.closed, 0)

    async def test_response_timeout_retains_four_actual_calls_and_later_useful_progress(self):
        self.service.release = asyncio.Event()
        requests = [asyncio.create_task(self.exchange(self.request())) for _ in range(4)]
        await self.settled(lambda: len(self.service.calls) == 4)
        self.assertEqual(self.host.metrics()["active"], 4)
        status, reply, _ = await self.exchange(self.request())
        self.assertIsNone(status)
        self.assertIsNone(reply)
        self.assertEqual(len(self.service.calls), 4)
        self.assertEqual(self.host.metrics()["handlers"], 4)
        replies = await asyncio.gather(*requests)
        self.assertEqual([value[0] for value in replies], [503] * 4)
        self.assertEqual([value[1]["code"] for value in replies], ["acknowledgement_unknown"] * 4)
        self.assertEqual(self.host.metrics()["active"], 4)
        self.assertEqual(self.host.metrics()["timed_out"], 4)
        self.assertEqual(self.service.cancelled, 0)
        self.service.release.set()
        await self.settled(lambda: self.host.metrics()["active"] == 0)
        status, reply, _ = await self.exchange(self.request("lookup"))
        self.assertEqual(status, 200)
        self.assertEqual(reply["observation"]["receipt"], RECEIPT)

    async def test_four_handler_cap_includes_slow_headers_and_rejects_excess_before_parse(self):
        peers = [await self.connect() for _ in range(4)]
        await self.settled(lambda: self.host.metrics()["handlers"] == 4)
        self.assertEqual(self.host.metrics()["sockets"], 4)
        reader, _writer = await self.connect()
        async with asyncio.timeout(1):
            self.assertEqual(await reader.read(), b"")
        self.assertEqual(self.host.metrics()["handlers"], 4)
        self.assertLessEqual(self.host.metrics()["sockets"], 8)
        self.assertEqual(self.service.calls, [])
        for _reader, peer in peers:
            peer.close()
            await peer.wait_closed()
        await self.settled(lambda: self.host.metrics()["handlers"] == 0)
        status, _, _ = await self.exchange(self.request("lookup"))
        self.assertEqual(status, 200)
        self.assertEqual(len(self.service.calls), 1)

    async def test_close_waiter_cancellation_keeps_actual_close_and_service_ownership(self):
        self.service.release = asyncio.Event()
        request = asyncio.create_task(self.exchange(self.request()))
        await self.service.entered.wait()
        observer = asyncio.create_task(self.host.close())
        await asyncio.sleep(0)
        observer.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await observer
        self.assertFalse(self.host._close_task.cancelled())
        self.assertEqual(self.host.metrics()["active"], 1)
        self.service.release.set()
        await self.host.close()
        await request
        self.assertEqual(self.service.cancelled, 0)

    async def test_header_count_control_bytes_and_truncated_body_release_handlers(self):
        original = self.request()
        frames = [
            original.replace(b"Connection: close", b"Connection: close\x00"),
            original.replace(b"Connection: close", b"Connection: close\r\n" + b"a: b\r\n" * 33),
            original.replace(b"Content-Type: application/json\r\n", b""),
        ]
        for frame in frames:
            status, reply, _ = await self.exchange(frame)
            self.assertEqual((status, reply["code"]), (400, "invalid_input"))
        reader, writer = await self.connect()
        writer.write(original[:-1])
        await writer.drain()
        writer.write_eof()
        async with asyncio.timeout(1):
            raw = await reader.read()
        self.assertTrue(raw.startswith(b"HTTP/1.1 400"))
        await self.settled(lambda: self.host.metrics()["handlers"] == 0)
        self.assertEqual(self.service.calls, [])

    async def test_wrong_loop_start_cannot_replace_live_listener_or_close(self):
        result = []

        def other_loop():
            try:
                asyncio.run(self.host.start())
            except m.OriginHttpError as error:
                result.append(error.code)

        await asyncio.to_thread(other_loop)
        self.assertEqual(result, ["invalid_configuration"])
        self.assertFalse(self.host.metrics()["closing"])
        status, _, _ = await self.exchange(self.request("lookup"))
        self.assertEqual(status, 200)

    async def test_mutated_dependency_error_code_cannot_escape_safe_diagnostics(self):
        failure = CoordinatorError("invalid_input")
        failure.code = "SECRET_SENTINEL"
        self.service.failure = failure
        records = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(record.__dict__.copy())

        before = m.LOGGER.level
        handler = Capture()
        m.LOGGER.addHandler(handler)
        m.LOGGER.setLevel(logging.INFO)
        try:
            status, reply, raw = await self.exchange(self.request())
        finally:
            m.LOGGER.removeHandler(handler)
            m.LOGGER.setLevel(before)
        self.assertEqual((status, reply["code"]), (503, "internal_error"))
        self.assertNotIn(b"SECRET_SENTINEL", raw)
        self.assertEqual(records[0]["code"], "internal_error")
        self.assertNotIn("SECRET_SENTINEL", repr(records))

    async def test_service_cancelled_call_releases_after_actual_settlement(self):
        self.service.failure = asyncio.CancelledError()
        status, _, _ = await self.exchange(self.request())
        self.assertIsNone(status)
        await self.settled(lambda: self.host.metrics()["handlers"] == 0)
        self.assertEqual(self.host.metrics()["active"], 0)
        self.service.failure = None
        status, _, _ = await self.exchange(self.request("lookup"))
        self.assertEqual(status, 200)

    async def test_socket_constructor_failure_is_safe_inert_and_allows_fresh_retry(self):
        await self.host.close()
        self.host = m.ChannelOriginHttp(self.service, operation_bearer=TOKEN)
        with (
            patch.object(m.socket, "socket", side_effect=OSError("PRIVATE_STARTUP_SENTINEL")),
            self.assertRaises(m.OriginHttpError) as caught,
        ):
            await self.host.start()
        self.assertEqual(caught.exception.code, "unavailable")
        self.assertEqual(str(caught.exception), "unavailable")
        self.assertNotIn("PRIVATE_STARTUP_SENTINEL", repr(caught.exception))
        self.assertIsNone(self.host._listener)
        self.assertIsNone(self.host._endpoint)
        self.assertIsNone(self.host._accept_task)
        self.assertEqual(self.host.metrics()["sockets"], 0)
        self.assertEqual(self.host.metrics()["handlers"], 0)
        self.assertFalse(self.host.metrics()["closing"])
        self.assertEqual(self.service.calls, [])
        self.endpoint = await self.host.start()
        status, reply, _ = await self.exchange(self.request("lookup"))
        self.assertEqual(status, 200)
        self.assertEqual(reply["observation"]["receipt"], RECEIPT)

    async def test_partial_socket_setup_failure_closes_socket_before_retry(self):
        await self.host.close()
        self.host = m.ChannelOriginHttp(self.service, operation_bearer=TOKEN)
        created = []

        class BindFailure(socket.socket):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                created.append(self)

            def bind(self, address):
                raise OSError("PRIVATE_STARTUP_SENTINEL")

        with (
            patch.object(m.socket, "socket", BindFailure),
            self.assertRaisesRegex(m.OriginHttpError, "^unavailable$"),
        ):
            await self.host.start()
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].fileno(), -1)
        self.assertIsNone(self.host._listener)
        self.assertIsNone(self.host._endpoint)
        self.assertIsNone(self.host._accept_task)
        self.endpoint = await self.host.start()
        status, reply, _ = await self.exchange(self.request("lookup"))
        self.assertEqual(status, 200)
        self.assertEqual(reply["observation"]["receipt"], RECEIPT)

    async def test_close_task_setup_failure_retains_owners_without_coroutine_warning(self):
        self.service.release = asyncio.Event()
        request = asyncio.create_task(self.exchange(self.request()))
        await self.service.entered.wait()
        listener = self.host._listener
        with warnings.catch_warnings(record=True) as caught_warnings:
            warnings.simplefilter("always", RuntimeWarning)
            with (
                patch.object(
                    m.asyncio, "create_task", side_effect=RuntimeError("PRIVATE_CLOSE_SENTINEL")
                ),
                self.assertRaises(m.OriginHttpError) as caught,
            ):
                await self.host.close()
            gc.collect()
        self.assertEqual(caught.exception.code, "cleanup_incomplete")
        self.assertEqual(str(caught.exception), "cleanup_incomplete")
        self.assertNotIn("PRIVATE_CLOSE_SENTINEL", repr(caught.exception))
        self.assertFalse(any(issubclass(item.category, RuntimeWarning) for item in caught_warnings))
        self.assertTrue(self.host.metrics()["closing"])
        self.assertEqual(self.host.metrics()["active"], 1)
        self.assertEqual(self.host.metrics()["handlers"], 1)
        self.assertIsNone(self.host._close_task)
        self.assertIs(self.host._listener, listener)
        self.assertGreaterEqual(listener.fileno(), 0)
        self.assertEqual(self.service.cancelled, 0)
        with self.assertRaisesRegex(m.OriginHttpError, "^cleanup_incomplete$"):
            await self.host.close()
        self.assertIsNotNone(self.host._close_task)
        self.service.release.set()
        await self.host.close()
        await request
        self.assertEqual(listener.fileno(), -1)
        self.assertEqual(self.host.metrics()["active"], 0)
        self.assertEqual(self.host.metrics()["handlers"], 0)
        self.assertEqual(self.service.closed, 0)

    async def test_start_is_idempotent_and_closed_host_denies_restart(self):
        self.assertEqual(await self.host.start(), self.endpoint)
        self.assertEqual(await self.host.start(self.endpoint.port), self.endpoint)
        with self.assertRaises(m.OriginHttpError):
            await self.host.start(True)
        await self.host.close()
        with self.assertRaisesRegex(m.OriginHttpError, "^closed$"):
            await self.host.start()
