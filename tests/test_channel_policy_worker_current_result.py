"""Fixed Worker callback and private transport controls; no PG/provider/RTC."""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import json
import socket
import struct
import subprocess
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

from delegation_reliability import (
    channel_policy_key,
    encode_channel_policy_result,
    produce_channel_policy_request,
    produce_channel_policy_result,
)
from delegation_reliability.contracts import canonical
from delegation_reliability.fixed_policy_contracts import (
    parse_fixed_policy_result,
    produce_fixed_policy_request,
)
from services.channel_policy_demo import worker_current_result as m
from services.channel_policy_demo._loopback_json import LoopbackJSONError, LoopbackJSONTransport
from services.channel_policy_demo.current_result import (
    CurrentResultCase,
    CurrentResultIntent,
    CurrentResultObservation,
    CurrentResultObserved,
    CurrentResultProjection,
    CurrentResultReceipt,
    encode_current_result_observation,
)
from services.channel_policy_demo.discovery import DiscoveryScope
from services.channel_policy_demo.worker_client import WorkerBinding

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "w" * 43
PRIVATE = "PRIVATE_WORKER_CURRENT_SENTINEL"


def fixture():
    data = json.loads((ROOT / "contracts/delegation/fixed-policy-v2.json").read_bytes())
    operation, attempt = str(uuid4()), str(uuid4())
    raw = copy.deepcopy(data["producer_input"])
    raw.update(
        delegation_id=channel_policy_key(operation),
        attempt={"attempt_id": "attempt_" + UUID(attempt).hex, "number": 1},
    )
    request = produce_channel_policy_request(
        {
            "schema_version": 1,
            "kind": "delegation.request",
            "capability": "booking.evaluate_policy",
            "input_schema_version": 3,
            "origin": {
                "kind": "p2.prepared_dispatch.v1",
                "profile_id": str(uuid4()),
                "operation_key": operation,
                "input_receipt_id": str(uuid4()),
                "payload_sha256": hashlib.sha256(b"original").hexdigest(),
                "payload_byte_length": 8,
            },
            "request": produce_fixed_policy_request(raw).to_wire(),
        }
    )
    result = parse_fixed_policy_result(canonical(data["result"]))
    result = replace(
        result,
        delegation_id=request.delegation_id,
        attempt_id=request.attempt.attempt_id,
        input_fingerprint=request.request.input_fingerprint,
    )
    body = encode_channel_policy_result(produce_channel_policy_result(request, result))
    sha = hashlib.sha256(body).hexdigest()
    scope = DiscoveryScope(request.scope.tenant_id, request.scope.account_id)
    binding = WorkerBinding(
        request.origin.profile_id, scope, request.case_id, request.conversation_id
    )
    intent = CurrentResultIntent(
        str(uuid4()),
        scope,
        str(uuid4()),
        attempt,
        sha,
        str(uuid4()),
        "recipient_demo",
        base64.b64encode(body).decode(),
        1900000000003,
    )
    receipt = CurrentResultReceipt(
        intent.delivery_id,
        str(uuid4()),
        intent.receiver_id,
        intent.recipient_id,
        sha,
        1900000000004,
    )
    projection = CurrentResultProjection(
        request.origin.input_receipt_id,
        operation,
        intent,
        receipt,
        CurrentResultCase("p1_public_v4", "1"),
        CurrentResultObserved(
            "2026-11-13T00:00:00.001Z", "2026-11-13T00:00:00.002Z", "2026-11-13T00:00:00.003Z"
        ),
    )
    return binding, CurrentResultObservation(
        binding.profile_id,
        scope,
        binding.case_id,
        binding.conversation_id,
        "2026-11-13T00:00:00.004Z",
        "current",
        projection,
    )


def changed_body(observation, inner_change):
    from delegation_reliability import parse_channel_policy_result

    original = parse_channel_policy_result(base64.b64decode(observation.result.intent.body))
    changed = replace(original, result=replace(original.result, **inner_change))
    body = encode_channel_policy_result(changed)
    sha = hashlib.sha256(body).hexdigest()
    projection = replace(
        observation.result,
        intent=replace(
            observation.result.intent, body=base64.b64encode(body).decode(), result_sha256=sha
        ),
        receipt=replace(observation.result.receipt, result_sha256=sha),
    )
    return replace(observation, result=projection)


class HTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.binding, self.value = fixture()
        self.status = 200
        self.raw = encode_current_result_observation(self.value)
        self.requests = []
        self.tasks = set()
        self.release = None
        self.reset = False
        self.clients = []
        self.connections = 0
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        self.client = self.opened()

    def opened(self, **kwargs):
        client = m.WorkerCurrentResultClient(
            m.WorkerCurrentEndpoint(port=self.port),
            self.binding,
            m.CurrentResultCredential(TOKEN),
            **kwargs,
        )
        self.clients.append(client)
        return client

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        self.connections += 1
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            fields = {}
            for line in head[:-4].split(b"\r\n")[1:]:
                key, value = line.split(b": ", 1)
                fields[key.decode().lower()] = value.decode()
            body = await reader.readexactly(int(fields["content-length"]))
            self.requests.append((head, fields, body))
            if self.release is not None:
                await self.release.wait()
            if self.reset:
                writer.get_extra_info("socket").setsockopt(
                    socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
                )
                writer.transport.abort()
                return
            out = (
                f"HTTP/1.1 {self.status} Response\r\nContent-Type: application/json\r\nContent-Length: {len(self.raw)}\r\nConnection: close\r\nCache-Control: no-store\r\n\r\n".encode()
                + self.raw
            )
            writer.write(out)
            await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
            self.tasks.discard(task)

    async def asyncTearDown(self):
        if self.release is not None:
            self.release.set()
        for client in self.clients:
            await client.close()
        self.server.close()
        await self.server.wait_closed()
        async with asyncio.timeout(2):
            while self.tasks:
                await asyncio.sleep(0)

    async def code(self, expected):
        with self.assertRaises(m.WorkerCurrentResultError) as caught:
            await self.client.read()
        self.assertEqual((caught.exception.code, caught.exception.args), (expected, (expected,)))
        self.assertNotIn(PRIVATE, str(caught.exception))

    async def test_exact_scope_free_request_and_fresh_callback_capability(self):
        value = await self.client.read()
        self.assertEqual(value, self.value)
        head, fields, body = self.requests[0]
        self.assertTrue(head.startswith(b"POST /v1/channel-policy/current-result HTTP/1.1\r\n"))
        self.assertEqual(body, b'{"schemaVersion":1}')
        self.assertEqual(
            fields,
            {
                "host": f"127.0.0.1:{self.port}",
                "authorization": "Bearer " + TOKEN,
                "content-type": "application/json",
                "content-length": "19",
                "connection": "close",
            },
        )
        for selector in [
            "scope",
            "nodeEpoch",
            "generation",
            "workId",
            "deliveryId",
            "publisherToken",
        ]:
            self.assertNotIn(selector, body.decode())

    async def test_fixed_profile_scope_case_conversation_denials(self):
        for field, value in [
            ("profile_id", str(uuid4())),
            ("scope", DiscoveryScope("foreign_tenant", "foreign_account")),
            ("case_id", "foreign_case"),
            ("conversation_id", "foreign_conversation"),
        ]:
            self.raw = encode_current_result_observation(
                replace(self.value, **{field: value}, result=None, state="no_delivery")
            )
            await self.code("unauthorized")
        self.raw = encode_current_result_observation(self.value)
        self.assertEqual(await self.client.read(), self.value)

    async def test_complete_noncurrent_observations_are_distinct_and_have_no_body(self):
        for state in ["no_delivery", "not_applicable"]:
            value = replace(self.value, state=state, result=None)
            self.raw = encode_current_result_observation(value)
            self.assertEqual(await self.client.read(), value)
        for raw in [b"null", b"{}", b'{"schemaVersion":true}', b"NaN"]:
            self.raw = raw
            await self.code("invalid_state")

    async def test_coordinated_body_sha_forgeries_cannot_change_case_revision_operation_or_attempt(
        self,
    ):
        for changes in [
            {"case_id": "foreign_case"},
            {"request_revision": 2},
            {"delegation_id": channel_policy_key(str(uuid4()))},
            {"attempt_id": "attempt_" + uuid4().hex},
        ]:
            self.raw = encode_current_result_observation(changed_body(self.value, changes))
            await self.code("invalid_state")
        self.raw = encode_current_result_observation(self.value)
        self.assertEqual(await self.client.read(), self.value)

    async def test_parent_operational_error_is_never_no_delivery(self):
        for status, code in [
            (400, "invalid_input"),
            (401, "unauthorized"),
            (429, "capacity"),
            (503, "closed"),
            (503, "unavailable"),
            (503, "cleanup_incomplete"),
        ]:
            self.status = status
            self.raw = json.dumps(
                {"schemaVersion": 1, "status": "unavailable", "code": code}
            ).encode()
            await self.code(code)
        self.status = 503
        self.raw = json.dumps(
            {"schemaVersion": 1, "status": "unavailable", "code": PRIVATE}
        ).encode()
        await self.code("unavailable")
        self.raw = b"null"
        await self.code("unavailable")

    async def test_immutable_binding_is_copied_before_waiting_for_parent(self):
        object.__setattr__(self.binding.scope, "tenant_id", "changed_tenant")
        self.assertEqual(await self.client.read(), self.value)

    async def test_shared_owner_retains_timed_out_sockets_and_releases_peer_reset_closures(self):
        self.release = asyncio.Event()
        client = self.opened(timeout_s=0.01, cleanup_timeout_s=0.01)
        for _ in range(2):
            with self.assertRaisesRegex(m.WorkerCurrentResultError, "deadline_exceeded"):
                await client.read()
        self.assertEqual(client.pending_count, 2)
        with self.assertRaisesRegex(m.WorkerCurrentResultError, "capacity"):
            await client.read()
        with self.assertRaisesRegex(m.WorkerCurrentResultError, "cleanup_incomplete"):
            await client.close()
        self.release.set()
        async with asyncio.timeout(2):
            while client.pending_count:
                await asyncio.sleep(0)
        await client.close()
        self.assertEqual(len(self.requests), 2)
        self.release, self.reset = None, True
        client = self.opened()
        for _ in range(2):
            with self.assertRaisesRegex(m.WorkerCurrentResultError, "^unavailable$"):
                await client.read()
        self.assertEqual(client.pending_count, 0)
        self.reset = False
        self.assertEqual(await client.read(), self.value)
        await client.close()
        self.assertEqual((client.pending_count, len(self.requests)), (0, 5))

    async def test_raw_control_transport_keeps_status_bytes_and_closed_purpose_paths(self):
        self.status = 503
        self.raw = b"opaque diagnostic-free bytes"
        paths = {
            "room_open": "open",
            "room_observe": "observe",
            "room_close": "close",
            "room_recover": "recover-revoke",
            "room_attach": "attach-agent",
        }
        for purpose, suffix in paths.items():
            client = LoopbackJSONTransport(port=self.port, bearer="p" * 43, purpose=purpose)
            try:
                self.assertEqual(await client.exchange(b'{"schemaVersion":1}'), (503, self.raw))
            finally:
                await client.close()
            self.assertTrue(
                self.requests[-1][0].startswith(
                    ("POST /v1/channel-policy/rooms/" + suffix + " HTTP/1.1").encode()
                )
            )
        before = self.connections
        with self.assertRaisesRegex(LoopbackJSONError, "invalid_input"):
            LoopbackJSONTransport(port=self.port, bearer=TOKEN, purpose="https://foreign.invalid")
        self.assertEqual(self.connections, before)

    async def test_valid_complete_ack_survives_actual_writer_close_failure(self):
        receipt = str(uuid4())
        self.raw = json.dumps({"schemaVersion": 1, "receiptId": receipt}).encode()
        events = []
        transport = LoopbackJSONTransport(port=self.port, bearer=TOKEN, purpose="room_open")
        original = asyncio.StreamWriter.wait_closed

        async def fail_client(writer):
            await original(writer)
            peer = writer.get_extra_info("peername")
            if peer is not None and peer[1] == self.port:
                events.append("close_failed")
                raise RuntimeError(PRIVATE)

        def decode(status, raw):
            value = json.loads(raw)
            if status != 200 or value != {"schemaVersion": 1, "receiptId": receipt}:
                raise LoopbackJSONError("invalid_state")
            events.append("decoded")
            return value["receiptId"]

        try:
            with patch.object(asyncio.StreamWriter, "wait_closed", fail_client):
                self.assertEqual(
                    await transport.exchange_decoded(b'{"schemaVersion":1}', decoder=decode),
                    receipt,
                )
            self.assertEqual(events, ["decoded", "close_failed"])
            self.assertEqual(
                (
                    transport.pending_count,
                    transport.metrics()["succeeded"],
                    transport.metrics()["failed"],
                ),
                (1, 1, 0),
            )
            await transport.close()
            self.assertEqual((transport.pending_count, len(self.requests)), (0, 1))
        finally:
            await transport.close()

    async def test_invalid_ack_primary_survives_actual_writer_close_failure(self):
        self.raw = b'{"schemaVersion":1,"receiptId":"wrong"}'
        events = []
        transport = LoopbackJSONTransport(port=self.port, bearer=TOKEN, purpose="room_open")
        original = asyncio.StreamWriter.wait_closed

        async def fail_client(writer):
            await original(writer)
            peer = writer.get_extra_info("peername")
            if peer is not None and peer[1] == self.port:
                events.append("close_failed")
                raise RuntimeError(PRIVATE)

        def decode(status, raw):
            events.append("invalid_ack")
            raise LoopbackJSONError("invalid_state")

        try:
            with (
                patch.object(asyncio.StreamWriter, "wait_closed", fail_client),
                self.assertRaisesRegex(LoopbackJSONError, "^invalid_state$"),
            ):
                await transport.exchange_decoded(b'{"schemaVersion":1}', decoder=decode)
            self.assertEqual(events, ["invalid_ack", "close_failed"])
            self.assertEqual(
                (
                    transport.pending_count,
                    transport.metrics()["succeeded"],
                    transport.metrics()["failed"],
                ),
                (1, 0, 1),
            )
            await transport.close()
            self.assertEqual((transport.pending_count, len(self.requests)), (0, 1))
        finally:
            await transport.close()

    async def test_late_decoder_failure_is_semantic_failure_not_raw_success(self):
        self.release = asyncio.Event()
        transport = LoopbackJSONTransport(
            port=self.port,
            bearer=TOKEN,
            purpose="worker_current_result",
            timeout_s=0.01,
            cleanup_timeout_s=0.01,
        )

        def decode(status, raw):
            raise LoopbackJSONError("invalid_state")

        try:
            with self.assertRaisesRegex(LoopbackJSONError, "deadline_exceeded"):
                await transport.exchange_decoded(b'{"schemaVersion":1}', decoder=decode)
            self.assertEqual(transport.pending_count, 1)
            self.release.set()
            async with asyncio.timeout(2):
                while transport.pending_count:
                    await asyncio.sleep(0)
            self.assertEqual(
                (transport.metrics()["succeeded"], transport.metrics()["failed"]), (0, 1)
            )
        finally:
            await transport.close()


class Facts(unittest.TestCase):
    def test_only_five_bounded_facts_reach_model_summary(self):
        binding, value = fixture()
        fact = m.current_result_fact(value)
        summary = fact.summary()
        self.assertEqual(
            json.loads(summary),
            {
                "state": "current",
                "eligible": True,
                "uncertainty": "none",
                "revision": "1",
                "asOf": value.read_completed_at,
            },
        )
        self.assertLessEqual(len(summary.encode()), 1024)
        for secret in [
            binding.profile_id,
            binding.scope.tenant_id,
            binding.case_id,
            value.result.intent.body,
            value.result.operation_key,
            value.result.intent.work_id,
            TOKEN,
        ]:
            self.assertNotIn(secret, summary)

    def test_absence_stale_and_unavailable_have_no_result_claim(self):
        _, value = fixture()
        for state in ["no_delivery", "not_applicable"]:
            fact = m.current_result_fact(replace(value, state=state, result=None))
            self.assertEqual(
                (fact.state, fact.eligible, fact.uncertainty, fact.revision),
                (state, None, None, None),
            )
        self.assertEqual(
            json.loads(m.unavailable_fact().summary()),
            {
                "state": "unavailable",
                "eligible": None,
                "uncertainty": None,
                "revision": None,
                "asOf": None,
            },
        )

    def test_fact_constructor_rejects_invented_flags_revision_and_asof(self):
        for values in [
            ("unavailable", True, None, None, None),
            ("current", 1, "none", "1", "2026-11-13T00:00:00.000Z"),
            ("current", True, "none", "01", "2026-11-13T00:00:00.000Z"),
            ("current", True, "none", "1", "2026-99-99T00:00:00.000Z"),
        ]:
            with self.assertRaisesRegex(m.WorkerCurrentResultError, "invalid_state"):
                m.CurrentResultFact(*values)

    def test_credential_endpoint_bounds_and_cold_import(self):
        self.assertEqual(m.WorkerCurrentEndpoint().port, 11031)
        self.assertNotIn(TOKEN, repr(m.CurrentResultCredential(TOKEN)))
        for value in ["x" * 42, TOKEN + "\n", PRIVATE]:
            with self.assertRaisesRegex(m.WorkerCurrentResultError, "invalid_input"):
                m.CurrentResultCredential(value)
        for value in [True, 0, 65536]:
            with self.assertRaisesRegex(m.WorkerCurrentResultError, "invalid_input"):
                m.WorkerCurrentEndpoint(port=value)
        code = "import sys;from unittest.mock import patch;\nwith patch('socket.socket',side_effect=AssertionError('socket')),patch('subprocess.Popen',side_effect=AssertionError('process')):import services.channel_policy_demo.worker_current_result,services.channel_policy_demo.current_result_context\nassert 'livekit.agents' not in sys.modules"
        result = subprocess.run(
            [sys.executable, "-B", "-c", code],
            cwd=ROOT,
            capture_output=True,
            timeout=5,
            check=False,
        )
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))
