"""Actual loopback framing, uncertainty and retained intake lifetime."""

import asyncio
import json
import unittest
from uuid import uuid4

from channel_continuity.codec import AccountScope, ProviderScope
from channel_continuity.native import (
    NativeAck,
    NativeBinding,
    NativeCredential,
    NativeEndpoint,
    NativeError,
    NativeHttpIntake,
    NativeInput,
)


class NativeHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.b = NativeBinding(
            str(uuid4()),
            ProviderScope("t", "livekit", "p"),
            AccountScope("t", "a"),
            "c",
            "x",
            "room",
            "browser",
            "agent",
        )
        self.input = NativeInput(str(uuid4()), "web_chat", "investigate", "room", "browser")
        self.tasks = set()
        self.writers = set()

    async def asyncTearDown(self):
        for w in self.writers:
            w.close()
        if self.tasks:
            await asyncio.gather(*tuple(self.tasks), return_exceptions=True)

    async def server(self, work):
        async def handle(reader, writer):
            task = asyncio.current_task()
            self.tasks.add(task)
            self.writers.add(writer)
            try:
                head = await reader.readuntil(b"\r\n\r\n")
                headers = dict(line.split(b": ", 1) for line in head.split(b"\r\n")[1:-2])
                body = await reader.readexactly(int(headers[b"Content-Length"]))
                await work(writer, headers, body)
            finally:
                writer.close()
                await writer.wait_closed()
                self.writers.discard(writer)
                self.tasks.discard(task)

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        self.addAsyncCleanup(server.wait_closed)
        self.addCleanup(server.close)
        client = NativeHttpIntake(
            NativeEndpoint("127.0.0.1", server.sockets[0].getsockname()[1]),
            NativeCredential("a" * 43),
            self.b,
            timeout=0.15,
            cleanup=0.5,
        )
        self.addAsyncCleanup(client.aclose)
        return client

    async def write(self, w, value, status=200, connection="close", extra=b""):
        raw = json.dumps(value, separators=(",", ":")).encode()
        w.write(
            f"HTTP/1.1 {status} Result\r\nContent-Type: application/json\r\nContent-Length: {len(raw)}\r\nConnection: {connection}\r\n\r\n".encode()
            + raw
            + extra
        )
        await w.drain()

    def ack(self, i=None):
        return NativeAck(
            self.b.binding_id,
            (i or self.input).input_id,
            "web_chat",
            "accepted",
            str(uuid4()),
            str(uuid4()),
            "1",
        ).payload()

    async def test_normal_exact_native_ack_and_control_character_wire_bound(self):
        value = NativeInput(self.input.input_id, "web_chat", "\x01" * 2048, "room", "browser")
        calls = []

        async def work(w, h, body):
            calls.append(json.loads(body))
            self.assertEqual(h[b"Authorization"], b"Bearer " + b"a" * 43)
            self.assertLessEqual(len(body), 16384)
            await self.write(w, self.ack(value))

        c = await self.server(work)
        ack = await c.accept(value)
        self.assertEqual(ack.status, "accepted")
        self.assertEqual(len(calls), 1)
        self.assertEqual(c.metrics()["accepted"], 1)
        self.assertEqual(c.metrics()["active"], 0)

    async def test_missing_or_keepalive_framing_remains_unknown(self):
        async def work(w, h, b):
            await self.write(w, self.ack(), connection="keep-alive")

        c = await self.server(work)
        self.assertEqual((await c.accept(self.input)).status, "unknown")
        self.assertEqual(c.metrics()["unknown"], 1)

    async def test_wrong_ack_identity_never_adopts_receipt(self):
        async def work(w, h, b):
            await self.write(
                w, self.ack(NativeInput(str(uuid4()), "web_chat", "investigate", "room", "browser"))
            )

        c = await self.server(work)
        ack = await c.accept(self.input)
        self.assertEqual(ack.status, "unknown")
        self.assertIsNone(ack.receipt_id)

    async def test_definitive_rejection_and_unknown_have_distinct_codes(self):
        async def work(w, h, b):
            await self.write(
                w, {"schemaVersion": 1, "status": "rejected", "code": "idempotency_conflict"}, 409
            )

        c = await self.server(work)
        ack = await c.accept(self.input)
        self.assertEqual(ack.status, "rejected")
        self.assertEqual(ack.code, "idempotency_conflict")

    async def test_lost_response_is_unknown_not_rejected(self):
        async def work(w, h, b):
            return

        c = await self.server(work)
        ack = await c.accept(self.input)
        self.assertEqual(ack.status, "unknown")
        self.assertEqual(c.metrics()["rejected"], 0)

    async def test_waiter_cancel_keeps_actual_capacity_then_later_progress(self):
        entered = asyncio.Queue()
        release = asyncio.Event()

        async def work(w, h, b):
            entered.put_nowait(True)
            await release.wait()
            await self.write(w, self.ack())

        c = await self.server(work)
        one = asyncio.create_task(c.accept(self.input))
        await entered.get()
        one.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await one
        two = asyncio.create_task(c.accept(self.input))
        await entered.get()
        self.assertEqual(c.metrics()["active"], 2)
        with self.assertRaises(NativeError) as e:
            await c.accept(self.input)
        self.assertEqual(e.exception.code, "capacity_exhausted")
        release.set()
        self.assertEqual((await two).status, "accepted")
        await c.aclose()
        self.assertEqual(c.metrics()["active"], 0)

    async def test_wrong_room_rejects_before_socket(self):
        async def work(w, h, b):
            self.fail("unexpected_http")

        c = await self.server(work)
        with self.assertRaises(NativeError):
            await c.accept(NativeInput(str(uuid4()), "web_chat", "x", "other", "browser"))
        self.assertEqual(c.metrics()["started"], 0)

    async def test_duplicate_or_extra_response_bytes_remain_unknown(self):
        async def work(w, h, b):
            await self.write(w, self.ack(), extra=b"x")

        c = await self.server(work)
        self.assertEqual((await c.accept(self.input)).status, "unknown")


if __name__ == "__main__":
    unittest.main()
