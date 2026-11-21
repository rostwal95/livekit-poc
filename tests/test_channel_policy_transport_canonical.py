"""Canonical compatibility identities, inert imports and real fixed receiver headers."""

from __future__ import annotations

import asyncio
import base64
import json
import subprocess
import sys
import unittest
from pathlib import Path

from continuity_lab.delivery_api import DeliveryIntent, DeliveryReceipt
from continuity_lab.work_api import WorkScope
from services.channel_policy_demo import result_receiver

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "q" * 43


class CanonicalTransportTests(unittest.TestCase):
    def inert(self, canonical):
        code = """
import asyncio, importlib, logging, os, socket, subprocess, sys
from unittest.mock import patch
import aiohttp, h11
from continuity_lab.api import BookingChange, ExecutionCapacityExceeded, ExecutionNotFound
from continuity_lab.case_control_api import CaseControlClient, CaseControlIdentity
from continuity_lab.conversation_service import AsyncConversationService
from continuity_lab.postgres_api import AuthenticatedActor, AuthenticationFailed, BearerToken, CaseProjection, ManagedCaseClient
from continuity_lab.delivery_api import DeliveryIntent, DeliveryReceipt
from continuity_lab.work_api import WorkError, WorkScope
with (
    patch.object(socket, "socket", side_effect=AssertionError("socket")),
    patch.object(asyncio, "start_server", side_effect=AssertionError("server")),
    patch.object(asyncio, "open_connection", side_effect=AssertionError("client")),
    patch.object(asyncio, "create_task", side_effect=AssertionError("task")),
    patch.object(subprocess, "Popen", side_effect=AssertionError("process")),
    patch.object(os, "getenv", side_effect=AssertionError("environment")),
    patch.object(logging, "basicConfig", side_effect=AssertionError("logging")),
):
    importlib.import_module(sys.argv[1])
print("inert")
"""
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                code,
                canonical,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual((completed.returncode, completed.stdout), (0, "inert\n"), completed.stderr)

    def test_case_bridge_import_is_inert_in_a_cold_interpreter(self):
        self.inert("services.channel_policy_demo.case_bridge")

    def test_result_receiver_import_is_inert_in_a_cold_interpreter(self):
        self.inert("services.channel_policy_demo.result_receiver")


class ReceiverWireTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_accept_and_find_send_only_the_five_fixed_node_receiver_headers(self):
        fixture = json.loads((ROOT / "contracts/delegation/result-receiver-v1.json").read_bytes())
        raw = json.loads(fixture["intent_canonical"])
        original = DeliveryIntent(
            raw["delivery_id"],
            WorkScope(**raw["scope"]),
            raw["work_id"],
            raw["attempt_id"],
            raw["result_sha256"],
            raw["receiver_id"],
            raw["recipient_id"],
            base64.b64decode(raw["body"], validate=True),
            raw["prepared_at_ms"],
        )
        observed = []
        tasks = set()
        failure = asyncio.get_running_loop().create_future()
        response = json.dumps(
            {"schemaVersion": 1, "status": "accepted", "receipt": fixture["receipt"]},
            separators=(",", ":"),
        ).encode()

        async def exchange(reader, writer):
            try:
                async with asyncio.timeout(2):
                    header = await reader.readuntil(b"\r\n\r\n")
                    self.assertLessEqual(len(header), 8192)
                    lines = header[:-4].decode("ascii").split("\r\n")
                    pairs = [line.split(": ", 1) for line in lines[1:]]
                    self.assertEqual(len(pairs), 5)
                    headers = {name.lower(): value for name, value in pairs}
                    self.assertEqual(
                        set(headers),
                        {"host", "authorization", "content-type", "accept", "content-length"},
                    )
                    self.assertEqual(headers["authorization"], "Bearer " + TOKEN)
                    self.assertEqual(headers["content-type"], "application/json")
                    self.assertEqual(headers["accept"], "application/json")
                    body = await reader.readexactly(int(headers["content-length"]))
                    self.assertEqual(body, original.canonical())
                    observed.append((lines[0], headers["host"]))
                    writer.write(
                        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nCache-Control: no-store\r\nContent-Length: "
                        + str(len(response)).encode()
                        + b"\r\nConnection: close\r\n\r\n"
                        + response
                    )
                    await writer.drain()
            except Exception as error:  # noqa: BLE001 - retain server-side test assertion for caller
                if not failure.done():
                    failure.set_result(error)
            finally:
                writer.close()
                await writer.wait_closed()

        def connected(reader, writer):
            task = asyncio.create_task(exchange(reader, writer))
            tasks.add(task)
            task.add_done_callback(tasks.discard)

        server = await asyncio.start_server(connected, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        client = result_receiver.ChannelResultReceiver(
            port=port,
            publisher_token=TOKEN,
            receiver_id=original.receiver_id,
            scope=original.scope,
            recipient_id=original.recipient_id,
        )
        try:
            expected = DeliveryReceipt(**fixture["receipt"])
            self.assertEqual(await client.accept(original), expected)
            self.assertEqual(await client.find(original), expected)
            self.assertFalse(failure.done(), repr(failure.result()) if failure.done() else "")
            self.assertEqual(
                observed,
                [
                    ("POST /v1/p2-result-receiver/accept HTTP/1.1", f"127.0.0.1:{port}"),
                    ("POST /v1/p2-result-receiver/find HTTP/1.1", f"127.0.0.1:{port}"),
                ],
            )
            self.assertEqual(client.pending_count, 0)
        finally:
            await client.close()
            server.close()
            await server.wait_closed()
            if tasks:
                await asyncio.wait_for(asyncio.gather(*tuple(tasks)), 3)
            failure.cancel()
        self.assertTrue(client._session.closed)
        self.assertTrue(client._connector.closed)
        self.assertEqual((client.pending_count, len(tasks)), (0, 0))


if __name__ == "__main__":
    unittest.main()
