"""Actual loopback worker wire/lifecycle tests; no PG, RTC or model providers."""

from __future__ import annotations

import asyncio
import gc
import hashlib
import json
import logging
import socket
import struct
import unittest
import warnings
from dataclasses import FrozenInstanceError
from unittest.mock import patch
from uuid import uuid4

from services.channel_policy_demo import worker_client as m
from services.channel_policy_demo.discovery import (
    DiscoveryPage,
    DiscoveryScope,
    encode_discovery_page,
)


def packed(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def fixture():
    binding = m.WorkerBinding(
        str(uuid4()), DiscoveryScope("demo", "traveller"), "case", "conversation"
    )
    receipt = str(uuid4())
    submission = {
        "schemaVersion": 1,
        "kind": "investigation",
        "operationKey": str(uuid4()),
        "scope": {"tenantId": "demo", "accountId": "traveller"},
        "caseId": "case",
        "caseRevision": "1",
        "conversationId": "conversation",
        "message": {
            "receiptId": receipt,
            "eventId": "event",
            "messageId": "message",
            "senderId": "sender",
            "body": "Review café 🧭.\u0000",
        },
    }
    canonical = packed(submission)
    frame = packed(
        {
            "schemaVersion": 1,
            "canonicalPayload": canonical.decode(),
            "payloadDigest": hashlib.sha256(canonical).hexdigest(),
        }
    )
    page = DiscoveryPage(
        binding.profile_id,
        binding.scope,
        binding.case_id,
        binding.conversation_id,
        "2026-11-13T00:00:00.000Z",
        (),
        False,
        None,
    )
    return binding, receipt, frame, page


def response(status, body, *, headers=None, trailing=b""):
    reason = {
        200: "OK",
        204: "No Content",
        400: "Bad Request",
        403: "Forbidden",
        404: "Not Found",
        429: "Too Many Requests",
        503: "Service Unavailable",
    }[status]
    values = (
        headers
        if headers is not None
        else [
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body))),
            ("Connection", "close"),
            ("Cache-Control", "no-store"),
            ("Date", "Fri, 13 Nov 2026 00:00:00 GMT"),
        ]
    )
    return (
        (
            f"HTTP/1.1 {status} {reason}\r\n" + "".join(f"{k}: {v}\r\n" for k, v in values) + "\r\n"
        ).encode()
        + body
        + trailing
    )


class WorkerValues(unittest.TestCase):
    def test_config_is_strict_frozen_and_credential_repr_is_safe(self):
        b, _, _, _ = fixture()
        for host, port in (
            ("localhost", 1),
            ("127.0.0.1", True),
            ("127.0.0.1", 0),
            ("127.0.0.1", 65536),
        ):
            with self.subTest(host=host, port=port), self.assertRaises(m.WorkerReadError):
                m.WorkerEndpoint(host, port)
        for key in ("x" * 42, "x" * 44, "x" * 43 + "\n", False):
            with self.subTest(kind=type(key).__name__), self.assertRaises(m.WorkerReadError):
                m.WorkerCredential(key)
        self.assertNotIn("x" * 43, repr(m.WorkerCredential("x" * 43)))
        with self.assertRaises(FrozenInstanceError):
            b.case_id = "other"
        for budget in (True, 0, float("nan"), 6, 10**1000, -(10**1000)):
            with self.subTest(budget=budget), self.assertRaises(m.WorkerReadError):
                m.ChannelPolicyWorkerClient(
                    m.WorkerEndpoint("127.0.0.1", 1),
                    m.WorkerCredential("x" * 43),
                    b,
                    timeout_s=budget,
                )

        for field in ("timeout_s", "cleanup_timeout_s"):
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(m.WorkerReadError, "^invalid_input$"),
            ):
                m.ChannelPolicyWorkerClient(
                    m.WorkerEndpoint("127.0.0.1", 1),
                    m.WorkerCredential("x" * 43),
                    b,
                    **{field: 10**1000},
                )


class WorkerHttp(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.binding, self.receipt, self.frame, self.page = fixture()
        self.page_raw = encode_discovery_page(self.page)
        self.reply = response(200, self.page_raw)
        self.release = asyncio.Event()
        self.release.set()
        self.reset = False
        self.received = asyncio.Queue(maxsize=16)
        self.connections = 0
        self.handler_errors = []
        self.requests = []
        self.tasks = set()
        self.writers = set()
        self.clients = []

        def accepted(reader, writer):
            task = asyncio.create_task(self.handle(reader, writer))
            self.tasks.add(task)

            def settled(done):
                self.tasks.discard(done)
                if not done.cancelled():
                    error = done.exception()
                    if error is not None:
                        self.handler_errors.append(type(error).__name__)

            task.add_done_callback(settled)

        self.server = await asyncio.start_server(accepted, "127.0.0.1", 0, limit=4096, backlog=4)
        self.port = self.server.sockets[0].getsockname()[1]

    async def handle(self, reader, writer):
        self.connections += 1
        self.writers.add(writer)
        try:
            async with asyncio.timeout(1):
                head = await reader.readuntil(b"\r\n\r\n")
                length = int(
                    next(
                        row.split(b": ", 1)[1]
                        for row in head.split(b"\r\n")
                        if row.startswith(b"Content-Length: ")
                    )
                )
                body = await reader.readexactly(length)
                self.requests.append((head, body))
                self.received.put_nowait((head, body))
                await self.release.wait()
                if self.reset:
                    writer.get_extra_info("socket").setsockopt(
                        socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
                    )
                    writer.transport.abort()
                    return
                writer.write(self.reply)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, TimeoutError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
            self.writers.discard(writer)

    def client(self, *, timeout=0.5, cleanup=0.05):
        client = m.ChannelPolicyWorkerClient(
            m.WorkerEndpoint("127.0.0.1", self.port),
            m.WorkerCredential("x" * 43),
            self.binding,
            timeout_s=timeout,
            cleanup_timeout_s=cleanup,
        )
        self.clients.append(client)
        return client

    async def seen(self, count=1):
        async with asyncio.timeout(1):
            for _ in range(count):
                await self.received.get()

    async def idle(self, client):
        async with asyncio.timeout(1):
            while client.pending_count:
                await asyncio.sleep(0)

    async def asyncTearDown(self):
        self.release.set()
        for writer in tuple(self.writers):
            writer.close()
        for client in self.clients:
            await client.close()
        self.server.close()
        await self.server.wait_closed()
        async with asyncio.timeout(2):
            await asyncio.gather(*tuple(self.tasks), return_exceptions=True)
        self.assertEqual(self.handler_errors, [])

    async def test_exact_request_and_scoped_discovery_use_borrowed_adapter(self):
        client = self.client()
        view = await m.WorkerDiscoveryReader(client).read()
        self.assertEqual(view, self.page)
        head, body = self.requests[0]
        self.assertTrue(head.startswith(b"POST /v1/policy/discovery HTTP/1.1\r\n"))
        self.assertEqual(body, b'{"schemaVersion":1}')
        self.assertEqual(client.metrics()["succeeded"], 1)
        with self.assertRaises(TypeError):
            client.metrics()["active"] = 3

    async def test_original_utf8_prepared_frame_and_explicit_no_plan_are_distinct(self):
        client = self.client()
        self.reply = response(200, self.frame)
        port = m.WorkerPreparedReader(client)
        self.assertEqual(
            await port.read(receipt_id=self.receipt, source_binding_id="native"), self.frame
        )
        self.assertEqual(
            self.requests[-1][1],
            packed({"schemaVersion": 1, "receiptId": self.receipt, "sourceBindingId": "native"}),
        )
        self.reply = response(204, b"")
        self.assertIsNone(await port.read(receipt_id=self.receipt, source_binding_id="sms"))

    async def test_rejects_invalid_receipt_and_source_before_socket_allocation(self):
        client = self.client()
        for receipt, source in (("bad", "native"), (self.receipt, "other"), (self.receipt, True)):
            with (
                self.subTest(source=source),
                self.assertRaisesRegex(m.WorkerReadError, "^invalid_input$"),
            ):
                await client.prepared(receipt_id=receipt, source_binding_id=source)
        self.assertEqual(self.connections, 0)
        self.assertEqual(client.pending_count, 0)

    async def test_configured_route_snapshot_and_scope_rejection(self):
        client = self.client()
        object.__setattr__(self.binding, "case_id", "changed_after_construction")
        self.assertEqual(await client.discovery(), self.page)
        value = json.loads(self.page_raw)
        value["scope"]["accountId"] = "other"
        self.reply = response(200, packed(value))
        with self.assertRaisesRegex(m.WorkerReadError, "^unauthorized$"):
            await client.discovery()
        self.reply = response(200, self.page_raw)
        self.assertEqual(await client.discovery(), self.page)

    async def test_rejects_changed_or_foreign_original_prepared_bytes(self):
        client = self.client()
        for changed in ("digest", "receipt", "scope", "revision"):
            value = json.loads(self.frame)
            submission = json.loads(value["canonicalPayload"])
            if changed == "digest":
                value["payloadDigest"] = "0" * 64
            else:
                if changed == "receipt":
                    submission["message"]["receiptId"] = str(uuid4())
                if changed == "scope":
                    submission["scope"]["accountId"] = "other"
                if changed == "revision":
                    submission["caseRevision"] = "0"
                value["canonicalPayload"] = packed(submission).decode()
                value["payloadDigest"] = hashlib.sha256(
                    value["canonicalPayload"].encode()
                ).hexdigest()
            self.reply = response(200, packed(value))
            with self.subTest(changed=changed), self.assertRaises(m.WorkerReadError):
                await client.prepared(receipt_id=self.receipt, source_binding_id="native")

    async def test_finite_remote_failures_never_become_successful_absence(self):
        client = self.client()
        for status, code in (
            (400, "invalid_input"),
            (403, "unauthorized"),
            (404, "not_found"),
            (429, "capacity"),
            (503, "unavailable"),
            (503, "closed"),
        ):
            self.reply = response(
                status, packed({"schemaVersion": 1, "status": "unavailable", "code": code})
            )
            with (
                self.subTest(code=code),
                self.assertRaisesRegex(m.WorkerReadError, "^" + code + "$"),
            ):
                await client.discovery()
        self.assertEqual(len(self.requests), 6)

    async def test_rejects_duplicate_and_private_remote_error_fields(self):
        client = self.client()
        for body in (
            b'{"schemaVersion":1,"schemaVersion":1,"status":"unavailable","code":"unavailable"}',
            packed({"schemaVersion": 1, "status": "unavailable", "code": "SECRET"}),
            packed({"schemaVersion": 1, "status": "unavailable", "code": "capacity"}),
            packed({"schemaVersion": True, "status": "unavailable", "code": "unavailable"}),
        ):
            self.reply = response(503, body)
            with self.assertRaisesRegex(m.WorkerReadError, "^invalid_state$"):
                await client.discovery()

    async def test_closed_http_lengths_headers_utf8_and_trailing_bytes(self):
        client = self.client()
        examples = [
            response(200, self.page_raw, trailing=b"x"),
            response(204, b""),
            response(
                200,
                self.page_raw,
                headers=[
                    ("Content-Type", "application/json"),
                    ("Content-Length", str(len(self.page_raw))),
                    ("Content-Length", "0"),
                    ("Connection", "close"),
                ],
            ),
            response(
                200,
                b"",
                headers=[
                    ("Content-Type", "application/json"),
                    ("Content-Length", "8193"),
                    ("Connection", "close"),
                ],
            ),
            response(
                200,
                self.page_raw,
                headers=[
                    ("Content-Type", "application/json"),
                    ("Content-Length", str(len(self.page_raw))),
                    ("Connection", "close"),
                    ("Transfer-Encoding", "chunked"),
                ],
            ),
            response(200, b"\xff"),
            response(200, b'{"schemaVersion":1,"schemaVersion":1}'),
        ]
        for raw in examples:
            self.reply = raw
            with self.subTest(size=len(raw)), self.assertRaises(m.WorkerReadError):
                await client.discovery()
        self.reply = response(200, self.page_raw)
        self.assertEqual(await client.discovery(), self.page)

    async def test_abandoned_waiters_retain_both_actual_reads_and_useful_progress(self):
        client = self.client()
        self.release.clear()
        tasks = [asyncio.create_task(client.discovery()) for _ in range(2)]
        await self.seen(2)
        for task in tasks:
            task.cancel()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        self.assertTrue(all(isinstance(value, asyncio.CancelledError) for value in results))
        self.assertEqual(client.pending_count, 2)
        with self.assertRaisesRegex(m.WorkerReadError, "^capacity$"):
            await client.discovery()
        self.release.set()
        await self.idle(client)
        self.assertEqual(await client.discovery(), self.page)
        self.assertEqual(client.metrics()["cancelled_waiters"], 2)

    async def test_close_timeout_retains_actual_read_and_retries_same_observer(self):
        client = self.client()
        self.release.clear()
        task = asyncio.create_task(client.discovery())
        await self.seen()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        with self.assertRaisesRegex(m.WorkerReadError, "^cleanup_incomplete$"):
            await client.close()
        self.assertEqual(client.pending_count, 1)
        with self.assertRaisesRegex(m.WorkerReadError, "^closed$"):
            await client.discovery()
        self.release.set()
        await client.close()
        self.assertEqual(client.pending_count, 0)

    async def test_held_actual_writer_close_retains_slots_after_read_waiter_deadline(self):
        client = self.client(timeout=0.04, cleanup=0.02)
        entered = asyncio.Event()
        release = asyncio.Event()
        original = asyncio.StreamWriter.wait_closed

        async def held(writer):
            peer = writer.get_extra_info("peername")
            if peer is not None and peer[1] == self.port:
                entered.set()
                await release.wait()
            await original(writer)

        with patch.object(asyncio.StreamWriter, "wait_closed", held):
            try:
                with self.assertRaisesRegex(m.WorkerReadError, "^unavailable$"):
                    await client.discovery()
                await asyncio.wait_for(entered.wait(), 1)
                self.assertEqual(client.pending_count, 1)
                with self.assertRaisesRegex(m.WorkerReadError, "^cleanup_incomplete$"):
                    await client.close()
                release.set()
                await client.close()
            finally:
                release.set()
        self.assertEqual(client.pending_count, 0)

    async def test_failed_close_observation_keeps_owner_but_peer_reset_closure_releases_it(self):
        client = self.client()
        original = asyncio.StreamWriter.wait_closed
        failed = False

        async def broken(writer):
            nonlocal failed
            peer = writer.get_extra_info("peername")
            if peer is not None and peer[1] == self.port and not failed:
                failed = True
                raise RuntimeError("PRIVATE_CLOSE")
            await original(writer)

        with (
            patch.object(asyncio.StreamWriter, "wait_closed", broken),
            self.assertRaisesRegex(m.WorkerReadError, "^cleanup_incomplete$"),
        ):
            await client.discovery()
        self.assertEqual(client.pending_count, 1)
        await client.close()
        self.assertEqual(client.pending_count, 0)
        self.reset = True
        client = self.client()
        for _ in range(2):
            with self.assertRaisesRegex(m.WorkerReadError, "^unavailable$"):
                await client.discovery()
        self.assertEqual(client.pending_count, 0)
        self.reset = False
        self.assertEqual(await client.discovery(), self.page)
        await client.close()
        self.assertEqual((client.pending_count, len(self.requests)), (0, 4))

    async def test_late_connector_returns_after_deadline_without_sending_a_request(self):
        client = self.client(timeout=0.02, cleanup=0.02)
        release = asyncio.Event()
        original = asyncio.open_connection

        async def late(*args, **kwargs):
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            return await original(*args, **kwargs)

        with patch.object(asyncio, "open_connection", late):
            try:
                with self.assertRaisesRegex(m.WorkerReadError, "^unavailable$"):
                    await client.discovery()
                self.assertEqual(client.pending_count, 1)
                with self.assertRaisesRegex(m.WorkerReadError, "^cleanup_incomplete$"):
                    await client.close()
                release.set()
                await client.close()
            finally:
                release.set()
        self.assertEqual(len(self.requests), 0)
        self.assertEqual(client.pending_count, 0)
        self.assertEqual(await self.client().discovery(), self.page)

    async def test_allocation_control_flow_closes_coroutine_and_releases_reserved_slot(self):
        client = self.client()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with (
                patch.object(asyncio, "create_task", side_effect=asyncio.CancelledError),
                self.assertRaises(asyncio.CancelledError),
            ):
                await client.discovery()
            gc.collect()
        self.assertFalse(any("was never awaited" in str(value.message) for value in caught))
        self.assertEqual(client.pending_count, 0)
        self.assertEqual(await client.discovery(), self.page)

    async def test_eager_allocation_reserves_capacity_before_connecting(self):
        client = self.client()
        original = asyncio.open_connection
        observed = []

        async def inspected(*args, **kwargs):
            observed.append(client.pending_count)
            return await original(*args, **kwargs)

        loop = asyncio.get_running_loop()
        factory = loop.get_task_factory()
        loop.set_task_factory(asyncio.eager_task_factory)
        try:
            with patch.object(asyncio, "open_connection", inspected):
                self.assertEqual(await client.discovery(), self.page)
        finally:
            loop.set_task_factory(factory)
        self.assertEqual(observed, [1])

    async def test_dependency_code_and_args_are_copied_without_private_accessors(self):
        client = self.client()

        class Hostile(m.WorkerReadError):
            def __init__(self):
                RuntimeError.__init__(self, "PRIVATE_SENTINEL")

            @property
            def code(self):
                raise RuntimeError("PRIVATE_GETTER")

        error = m.WorkerReadError("capacity")
        error.args = ("PRIVATE_ARGS",)
        for value, expected in ((error, "capacity"), (Hostile(), "unavailable")):
            with (
                patch.object(asyncio, "open_connection", side_effect=value),
                self.assertRaisesRegex(m.WorkerReadError, "^" + expected + "$"),
            ):
                await client.discovery()
        self.assertEqual(await client.discovery(), self.page)

    async def test_publisher_adapters_translate_only_the_closed_transport_error_contract(self):
        client = self.client()
        for status, code, expected in (
            (403, "unauthorized", "unauthorized"),
            (404, "not_found", "not_found"),
            (429, "capacity", "capacity"),
            (503, "invalid_state", "invalid_stored_state"),
        ):
            self.reply = response(
                status, packed({"schemaVersion": 1, "status": "unavailable", "code": code})
            )
            for port in (
                m.CoordinatorWorkerDiscoveryReader(client),
                m.CoordinatorWorkerPreparedReader(client),
            ):
                with (
                    self.subTest(code=code, port=type(port).__name__),
                    self.assertRaises(m.CoordinatorError) as caught,
                ):
                    if isinstance(port, m.CoordinatorWorkerDiscoveryReader):
                        await port.read()
                    else:
                        await port.read(source_binding_id="native", receipt_id=self.receipt)
                self.assertEqual(caught.exception.code, expected)
        self.reply = response(200, self.page_raw)
        self.assertEqual(await m.CoordinatorWorkerDiscoveryReader(client).read(), self.page)

    async def test_background_lane_serializes_readers_but_never_delays_dispatch_reads(self):
        class Held:
            def __init__(self):
                self.active = self.peak = 0
                self.release = asyncio.Event()

            async def discovery(self):
                self.active += 1
                self.peak = max(self.peak, self.active)
                try:
                    await self.release.wait()
                    return "page"
                finally:
                    self.active -= 1

            async def prepared(self, **kwargs):
                return await self.discovery()

        held = Held()
        lane = asyncio.Semaphore(1)
        scan = asyncio.create_task(m.CoordinatorWorkerDiscoveryReader(held, lane).read())
        result = asyncio.create_task(
            m.CoordinatorWorkerPreparedReader(held, lane).read(
                source_binding_id="native", receipt_id=self.receipt
            )
        )
        for _ in range(5):
            await asyncio.sleep(0)
        self.assertEqual(held.active, 1)
        dispatch = asyncio.create_task(
            m.CoordinatorWorkerPreparedReader(held).read(
                source_binding_id="native", receipt_id=self.receipt
            )
        )
        for _ in range(5):
            await asyncio.sleep(0)
        self.assertEqual(held.active, 2)
        held.release.set()
        self.assertEqual(await asyncio.gather(scan, result, dispatch), ["page"] * 3)
        self.assertEqual((held.peak, held.active, lane.locked()), (2, 0, False))

    async def test_telemetry_failure_does_not_block_real_read_or_safe_counters(self):
        client = self.client()

        class Broken(logging.Handler):
            def emit(self, record):
                raise RuntimeError("PRIVATE_LOGGER")

        handler = Broken()
        level = m.LOGGER.level
        m.LOGGER.setLevel(logging.INFO)
        m.LOGGER.addHandler(handler)
        try:
            self.assertEqual(await client.discovery(), self.page)
        finally:
            m.LOGGER.removeHandler(handler)
            m.LOGGER.setLevel(level)
        self.assertEqual(client.metrics()["telemetry_failed"], 1)


if __name__ == "__main__":
    unittest.main()
