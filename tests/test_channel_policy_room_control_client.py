"""Real TCP control frames, uncertainty and retained cross-purpose ownership."""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import patch
from uuid import uuid4

from services.channel_policy_demo import room_control_client as m
from services.channel_policy_demo.room_control import (
    RoomAttach,
    RoomBinding,
    RoomCommand,
    RoomOpen,
    RoomPublisherCredential,
    RoomRecover,
)


def fixture():
    return RoomOpen(
        str(uuid4()),
        "0",
        str(uuid4()),
        RoomBinding(
            str(uuid4()), "n" * 43, "room_a", "caller_a", "agent_a", "2030-01-01T00:02:00.000Z"
        ),
        "v" * 43,
    )


class ControlTCP(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.gate = asyncio.Event()
        self.gate.set()
        self.accepted = asyncio.Event()
        self.closed = asyncio.Event()
        self.sockets = set()
        self.client = None
        self.opened = fixture()
        self.status = 200
        self.response = None
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def handle(self, reader, writer):
        self.sockets.add(writer)
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            rows = head[:-4].decode().split("\r\n")
            headers = dict(line.split(": ", 1) for line in rows[1:])
            raw = await reader.readexactly(int(headers["Content-Length"]))
            value = json.loads(raw)
            self.requests.append((rows[0], headers, value))
            self.accepted.set()
            await self.gate.wait()
            if self.response is not None:
                body = self.response
            elif self.status != 200:
                body = {
                    "schemaVersion": 1,
                    "status": "unavailable",
                    "code": "conflict" if self.status == 409 else "unauthorized",
                }
            elif rows[0].startswith("POST /v1/channel-policy/rooms/attach-agent "):
                body = {key: field for key, field in value.items() if key != "prepareBearer"}
                body["state"] = "attached"
            elif rows[0].startswith("POST /v1/channel-policy/rooms/recover-revoke "):
                body = {
                    "schemaVersion": 1,
                    "nodeEpoch": value["nodeEpoch"],
                    "generation": str(int(value["expectedGeneration"]) + 1),
                    "bindingId": value["bindingId"],
                    "state": "recovered",
                    "revocation": {
                        "bindingId": value["bindingId"],
                        "state": "absent",
                        "revokedAt": None,
                    },
                }
            else:
                generation = value.get(
                    "generation", str(int(value.get("expectedGeneration", "0")) + 1)
                )
                is_closed = rows[0].startswith("POST /v1/channel-policy/rooms/close ")
                body = {
                    "schemaVersion": 1,
                    "nodeEpoch": value["nodeEpoch"],
                    "generation": generation,
                    "openId": value["openId"],
                    "state": "closed" if is_closed else "ready",
                    "publication": {
                        "bindingId": self.opened.binding.binding_id,
                        "bindingDigest": "a" * 64,
                        "publishedAt": "2030-01-01T00:00:00.000Z",
                        "expiresAt": "2030-01-01T00:02:00.000Z",
                    },
                    "revocation": {
                        "bindingId": self.opened.binding.binding_id,
                        "state": "revoked",
                        "revokedAt": "2030-01-01T00:01:00.000Z",
                    }
                    if is_closed
                    else None,
                    "globalReaderDrained": False,
                }
            payload = (
                json.dumps(body, separators=(",", ":")).encode()
                if type(body) is not bytes
                else body
            )
            reason = (
                "OK" if self.status == 200 else "Conflict" if self.status == 409 else "Unauthorized"
            )
            writer.write(
                f"HTTP/1.1 {self.status} {reason}\r\nContent-Length: {len(payload)}\r\nContent-Type: application/json\r\nConnection: close\r\nCache-Control: no-store\r\n\r\n".encode()
                + payload
            )
            await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()
            self.sockets.discard(writer)
            self.closed.set()

    def make(self, **values):
        self.client = m.RoomControlHttpClient(
            RoomPublisherCredential("p" * 43), port=self.port, **values
        )
        return self.client

    async def asyncTearDown(self):
        self.gate.set()
        if self.client is not None:
            await self.client.close()
        self.server.close()
        await self.server.wait_closed()
        for writer in tuple(self.sockets):
            writer.close()
        for _ in range(100):
            if not self.sockets:
                break
            await asyncio.sleep(0.001)
        self.assertFalse(self.sockets)

    async def test_all_five_purposes_use_fixed_routes_one_role_and_exact_original_frames(self):
        client = self.make()
        opened = await client.open(self.opened)
        self.assertEqual(opened.state, "ready")
        command = self.opened.command()
        attached = await client.attach(
            RoomAttach(
                command.node_epoch,
                command.generation,
                command.open_id,
                self.opened.binding.binding_id,
                "w" * 43,
            )
        )
        self.assertEqual(attached.state, "attached")
        self.assertEqual(
            (await client.observe(command, binding=self.opened.binding)).open_id,
            self.opened.open_id,
        )
        self.assertEqual(
            (await client.close_room(command, binding=self.opened.binding)).state, "closed"
        )
        recovered = await client.recover(
            RoomRecover(self.opened.node_epoch, "1", self.opened.binding.binding_id)
        )
        self.assertEqual(recovered.generation, "2")
        self.assertEqual(recovered.revocation.state, "absent")
        self.assertEqual(
            [request[0] for request in self.requests],
            [
                f"POST /v1/channel-policy/rooms/{route} HTTP/1.1"
                for route in ("open", "attach-agent", "observe", "close", "recover-revoke")
            ],
        )
        for _, headers, _ in self.requests:
            self.assertEqual(headers["Authorization"], "Bearer " + "p" * 43)
            self.assertEqual(len(headers), 5)
        self.assertEqual(self.requests[0][2], self.opened.to_wire())
        self.assertNotIn("binding", self.requests[1][2])
        self.assertEqual(client.metrics()["known"], 5)

    async def test_attachment_rejects_publisher_alias_and_malformed_before_io(self):
        client = self.make()
        command = self.opened.command()
        for value in (
            object(),
            RoomAttach(
                command.node_epoch, "1", command.open_id, self.opened.binding.binding_id, "p" * 43
            ),
        ):
            with self.assertRaisesRegex(m.RoomControlError, "^invalid_input$"):
                await client.attach(value)
        self.assertEqual(self.requests, [])
        self.assertEqual(client.pending_count, 0)

    async def test_malformed_attachment_ack_stays_unknown_and_capacity_spans_controls(self):
        client = self.make(timeout_s=0.01, cleanup_timeout_s=0.01)
        command = self.opened.command()
        request = RoomAttach(
            command.node_epoch, "1", command.open_id, self.opened.binding.binding_id, "w" * 43
        )
        self.response = {"schemaVersion": 1, "state": "attached", "private": "PRIVATE_ACK"}
        with self.assertRaisesRegex(m.RoomControlError, "^outcome_unknown$"):
            await client.attach(request)
        self.response = None
        self.gate.clear()
        for call in (
            lambda: client.attach(request),
            lambda: client.observe(command, binding=self.opened.binding),
        ):
            with self.assertRaisesRegex(m.RoomControlError, "^outcome_unknown$"):
                await call()
        self.assertEqual(client.pending_count, 2)
        before = len(self.requests)
        with self.assertRaisesRegex(m.RoomControlError, "^capacity$"):
            await client.close_room(command, binding=self.opened.binding)
        self.assertEqual(len(self.requests), before)
        self.gate.set()
        await client.close()
        self.assertEqual(client.pending_count, 0)
        self.assertEqual(client.metrics()["known"], 2)

    async def test_definitive_errors_are_distinct_from_unknown_transport_or_malformed_ack(self):
        client = self.make()
        for status, expected in ((401, "unauthorized"), (409, "conflict")):
            self.status = status
            with (
                self.subTest(status=status),
                self.assertRaisesRegex(m.RoomControlError, "^" + expected + "$"),
            ):
                await client.open(self.opened)
        self.status = 200
        self.response = {"schemaVersion": 1, "private": "CONTROL_PRIVATE_SENTINEL"}
        with self.assertRaisesRegex(m.RoomControlError, "^outcome_unknown$"):
            await client.open(self.opened)
        self.assertEqual(client.metrics()["known"], 0)
        self.assertEqual(client.metrics()["rejected"], 2)

    async def test_two_actual_calls_span_different_purposes_after_waiter_loss(self):
        client = self.make(timeout_s=0.01, cleanup_timeout_s=0.01)
        self.gate.clear()
        first = asyncio.create_task(client.open(self.opened))
        await self.accepted.wait()
        second = asyncio.create_task(
            client.observe(self.opened.command(), binding=self.opened.binding)
        )
        outcomes = await asyncio.gather(first, second, return_exceptions=True)
        self.assertTrue(
            all(
                isinstance(error, m.RoomControlError) and error.code == "outcome_unknown"
                for error in outcomes
            )
        )
        self.assertEqual(client.pending_count, 2)
        with self.assertRaisesRegex(m.RoomControlError, "^capacity$"):
            await client.close_room(self.opened.command(), binding=self.opened.binding)
        with self.assertRaisesRegex(m.RoomControlError, "^cleanup_incomplete$"):
            await client.close()
        self.assertEqual(client.pending_count, 2)
        self.assertEqual(len(self.requests), 2)
        self.gate.set()
        await asyncio.wait_for(self.closed.wait(), 1)
        for _ in range(200):
            if client.pending_count == 0:
                break
            await asyncio.sleep(0.001)
        await client.close()
        self.assertEqual(client.pending_count, 0)
        self.assertEqual(client.metrics()["known"], 2)

    async def test_cancelled_waiter_does_not_cancel_actual_call_or_permit_follow_on_work(self):
        client = self.make()
        self.gate.clear()
        pending = asyncio.create_task(client.open(self.opened))
        await self.accepted.wait()
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending
        self.assertEqual(client.pending_count, 1)
        self.gate.set()
        await client.close()
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(client.metrics()["known"], 1)
        with self.assertRaisesRegex(m.RoomControlError, "^closed$"):
            await client.open(self.opened)

    async def test_request_and_expected_ack_are_snapshotted_before_network_wait(self):
        client = self.make()
        self.gate.clear()
        pending = asyncio.create_task(client.open(self.opened))
        await self.accepted.wait()
        original_binding = self.opened.binding.binding_id
        object.__setattr__(self.opened.binding, "binding_id", str(uuid4()))
        # The fake peer acknowledges the original immutable request too.
        self.opened = RoomOpen(
            self.opened.node_epoch,
            "0",
            self.opened.open_id,
            RoomBinding(
                original_binding,
                "n" * 43,
                "room_a",
                "caller_a",
                "agent_a",
                "2030-01-01T00:02:00.000Z",
            ),
            "v" * 43,
        )
        self.gate.set()
        result = await pending
        self.assertEqual(result.publication.binding_id, original_binding)

    async def test_queued_cancellation_and_allocation_failure_admit_no_http_then_fresh_progress(
        self,
    ):
        client = self.make()

        async def cancelled():
            asyncio.current_task().cancel()
            await client.open(self.opened)

        pending = asyncio.create_task(cancelled())
        with self.assertRaises(asyncio.CancelledError):
            await pending
        self.assertEqual(client.pending_count, 0)
        self.assertFalse(self.requests)
        original = m.asyncio.create_task

        def failed(action, *args, **values):
            raise RuntimeError("CONTROL_PRIVATE_SENTINEL")

        with (
            patch.object(m.asyncio, "create_task", side_effect=failed),
            self.assertRaisesRegex(m.RoomControlError, "^unavailable$"),
        ):
            await client.open(self.opened)
        self.assertIs(m.asyncio.create_task, original)
        self.assertEqual(client.pending_count, 0)
        self.assertEqual((await client.open(self.opened)).state, "ready")

    async def test_invalid_and_bypassed_inputs_are_finite_before_any_socket(self):
        client = self.make()
        for request in (None, {}, object.__new__(RoomOpen)):
            with (
                self.subTest(type=type(request).__name__),
                self.assertRaisesRegex(m.RoomControlError, "^invalid_input$"),
            ):
                await client.open(request)
        with self.assertRaisesRegex(m.RoomControlError, "^invalid_input$"):
            await client.observe(object.__new__(RoomCommand), binding=self.opened.binding)
        with self.assertRaisesRegex(m.RoomControlError, "^invalid_input$"):
            await client.recover(object.__new__(RoomRecover))
        self.assertFalse(self.requests)
        self.assertEqual(client.pending_count, 0)

    async def test_known_ack_survives_failed_cleanup_observation_but_slot_remains_owned(self):
        client = self.make()
        original = m.LoopbackJSONTransport.close
        fail_once = True

        async def close(transport):
            nonlocal fail_once
            if fail_once:
                fail_once = False
                raise RuntimeError("CONTROL_PRIVATE_SENTINEL")
            await original(transport)

        with patch.object(m.LoopbackJSONTransport, "close", new=close):
            result = await client.open(self.opened)
            self.assertEqual(result.state, "ready")
            self.assertEqual(client.pending_count, 1)
            self.assertEqual(client.metrics()["cleanup_owned"], 1)
            await client.close()
        self.assertEqual(client.pending_count, 0)
        self.assertEqual(len(self.requests), 1)

    async def test_remote_unknown_is_not_reported_as_rejected_or_known(self):
        client = self.make()
        self.status = 503
        self.response = {"schemaVersion": 1, "status": "unavailable", "code": "outcome_unknown"}
        with self.assertRaisesRegex(m.RoomControlError, "^outcome_unknown$"):
            await client.open(self.opened)
        self.assertEqual(client.metrics()["known"], 0)
        self.assertEqual(client.metrics()["rejected"], 0)
        self.assertEqual(client.metrics()["unknown"], 1)

    async def test_telemetry_failure_cannot_change_a_known_ack(self):
        client = self.make()
        with patch.object(m.LOGGER, "info", side_effect=RuntimeError("CONTROL_PRIVATE_SENTINEL")):
            result = await client.open(self.opened)
        self.assertEqual(result.state, "ready")
        self.assertGreater(client.metrics()["telemetry_failed"], 0)

    async def test_invalid_constructor_configuration_is_finite_without_io(self):
        for credential, port in (
            (None, self.port),
            (object.__new__(RoomPublisherCredential), self.port),
            (RoomPublisherCredential("p" * 43), True),
            (RoomPublisherCredential("p" * 43), 0),
        ):
            with (
                self.subTest(port=port),
                self.assertRaisesRegex(m.RoomControlError, "^invalid_input$"),
            ):
                m.RoomControlHttpClient(credential, port=port)
        for budget in (True, 10**1000, float("nan"), -1):
            with (
                self.subTest(budget=str(budget)[:10]),
                self.assertRaisesRegex(m.RoomControlError, "^invalid_input$"),
            ):
                m.RoomControlHttpClient(RoomPublisherCredential("p" * 43), timeout_s=budget)
        self.assertFalse(self.requests)

    async def test_cleanup_observer_allocation_failure_is_retryable(self):
        client = self.make()

        def failed(action, *args, **values):
            raise RuntimeError("CONTROL_PRIVATE_SENTINEL")

        with (
            patch.object(m.asyncio, "create_task", side_effect=failed),
            self.assertRaisesRegex(m.RoomControlError, "^cleanup_incomplete$"),
        ):
            await client.close()
        await client.close()
        self.assertEqual(client.pending_count, 0)


if __name__ == "__main__":
    unittest.main()
