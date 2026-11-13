"""Actual bounded browser HTTP; public room/case/SMS ports are explicit fakes."""

from __future__ import annotations

import asyncio
import json
import unittest
from uuid import uuid4

from services.channel_policy_demo.current_result import CurrentResultObservation
from services.channel_policy_demo.discovery import DiscoveryScope
from services.channel_policy_demo.native_room_state import (
    BrowserRoomGrant,
    NativeRoomStatus,
    NodeRoomCursor,
)
from services.channel_policy_demo.operator import (
    ApplicationObservationPort,
    ChannelPolicyOperator,
    RoomOperatorPort,
    SmsOperatorPort,
)
from services.channel_policy_demo.operator_contract import (
    CaseObservation,
    ProgressObservation,
    SmsObservation,
    encode,
)
from services.channel_policy_demo.operator_http import ChannelPolicyOperatorHttp

NOW = "2026-11-13T09:00:00.000Z"
EXPIRY = "2030-01-01T00:00:00.000Z"
TOKEN = "o" * 43


class Rooms:
    def __init__(self):
        self.epoch = str(uuid4())
        self.cursor = NodeRoomCursor(str(uuid4()), "0", False)
        self.generation = "0"
        self.command = None
        self.stage = "idle"
        self.current_gate = None
        self.read_started = asyncio.Event()
        self.closed = 0
        self.started = 0

    def status(self):
        return NativeRoomStatus(
            self.epoch,
            self.generation,
            self.command,
            self.stage,
            NOW,
            self.cursor,
            False,
            self.stage == "waiting_browser",
            EXPIRY if self.command else None,
        )

    def is_current(self, command):
        return (command.owner_epoch, command.generation, command.original_start_command_id) == (
            self.epoch,
            self.generation,
            self.command,
        ) and self.stage == "waiting_browser"

    async def start(self, command):
        self.started += 1
        self.command = command.command_id
        self.generation = str(int(command.expected_generation) + 1)
        self.stage = "waiting_browser"
        return BrowserRoomGrant(
            self.epoch,
            self.generation,
            self.command,
            "YQ.Yg.Yw",
            "room_demo",
            "browser_demo",
            "agent_demo",
            str(uuid4()),
            EXPIRY,
        )

    async def end(self, command):
        self.stage = "closed"
        return self.status()

    async def read_current(self, command):
        self.read_started.set()
        if self.current_gate is not None:
            await self.current_gate.wait()
        return CurrentResultObservation(
            str(uuid4()),
            DiscoveryScope("tenant_demo", "account_demo"),
            "case_demo",
            "conversation_demo",
            NOW,
            "no_delivery",
            None,
        )


class Observations:
    def __init__(self):
        self.gate = None
        self.calls = 0
        self.entered = asyncio.Queue(8)
        self.closed = 0

    async def observe_case(self):
        self.calls += 1
        self.entered.put_nowait(True)
        if self.gate is not None:
            await self.gate.wait()
        return CaseObservation("1", NOW)

    async def observe_progress(self):
        return ProgressObservation(NOW, 0, 0, 0, 0, 0, 0, 0, 0, 0)


class Sms:
    def __init__(self):
        self.calls = []
        self.closed = 0

    async def send(self, command):
        self.calls.append(command)
        return SmsObservation(
            command.command_id, False, str(uuid4()), command.event_id, command.event_id, "1", NOW
        )


class OperatorHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.rooms = Rooms()
        self.app = Observations()
        self.sms = Sms()
        rooms: RoomOperatorPort = self.rooms
        app: ApplicationObservationPort = self.app
        sms: SmsOperatorPort = self.sms
        self.operator = ChannelPolicyOperator(rooms, app, sms)
        self.host = ChannelPolicyOperatorHttp(self.operator, bearer=TOKEN, cleanup_timeout_s=1)
        self.port = (await self.host.start()).port

    async def asyncTearDown(self):
        if self.app.gate is not None:
            self.app.gate.set()
        if self.rooms.current_gate is not None:
            self.rooms.current_gate.set()
        await self.host.close()

    async def exchange(
        self, operation, value=None, *, token=TOKEN, extra=b"", target=None, wire=None
    ):
        raw = encode({"schemaVersion": 1} if value is None else value)
        request = (
            (
                f"POST {target or '/v1/channel-policy-demo/' + operation} HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nAuthorization: Bearer {token}\r\nContent-Type: application/json\r\nContent-Length: {len(raw)}\r\nConnection: close\r\n".encode()
                + extra
                + b"\r\n"
                + raw
            )
            if wire is None
            else wire
        )
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        try:
            writer.write(request)
            await writer.drain()
            async with asyncio.timeout(3):
                head = await reader.readuntil(b"\r\n\r\n")
                lines = head[:-4].split(b"\r\n")
                status = int(lines[0].split()[1])
                headers = {
                    name.lower(): value.strip()
                    for line in lines[1:]
                    for name, _, value in (line.partition(b":"),)
                }
                size = int(headers[b"content-length"])
                self.assertLessEqual(size, 16384)
                body = await reader.readexactly(size)
                self.assertEqual(await reader.read(1), b"")
                return status, headers, json.loads(body)
        finally:
            writer.close()
            await writer.wait_closed()

    async def join(self):
        command = {
            "schemaVersion": 1,
            "ownerEpoch": self.rooms.epoch,
            "expectedGeneration": "0",
            "commandId": str(uuid4()),
        }
        status, _, grant = await self.exchange("start", command)
        self.assertEqual(status, 200)
        return {
            "schemaVersion": 1,
            "ownerEpoch": grant["ownerEpoch"],
            "generation": grant["generation"],
            "originalStartCommandId": grant["originalStartCommandId"],
        }, grant

    async def test_browser_headers_and_independent_status_case_progress_are_supported(self):
        for operation in ("status", "case", "progress"):
            with self.subTest(operation=operation):
                status, headers, body = await self.exchange(
                    operation,
                    extra=b"Accept: */*\r\nUser-Agent: Synthetic browser\r\nOrigin: http://127.0.0.1:5179\r\nSec-Fetch-Site: same-origin\r\n",
                )
                self.assertEqual(status, 200)
                self.assertEqual(headers[b"cache-control"], b"no-store")
                self.assertNotIn(TOKEN, json.dumps(body))
        self.assertEqual(self.rooms.started, 0)

    async def test_join_grant_contains_only_rtc_and_original_parent_identity(self):
        command, grant = await self.join()
        self.assertEqual(
            set(grant),
            {
                "schemaVersion",
                "ownerEpoch",
                "generation",
                "originalStartCommandId",
                "mode",
                "stage",
                "rtc",
            },
        )
        self.assertEqual(grant["mode"], "scripted")
        self.assertEqual(grant["generation"], command["generation"])
        self.assertNotIn(TOKEN, json.dumps(grant))
        self.assertNotIn("prepareBearer", json.dumps(grant))

    async def test_current_five_facts_are_separate_from_case_observation(self):
        command, _ = await self.join()
        status, _, body = await self.exchange("current", command)
        self.assertEqual(status, 200)
        self.assertEqual(
            body["fact"],
            {
                "state": "no_delivery",
                "eligible": None,
                "uncertainty": None,
                "revision": None,
                "asOf": NOW,
            },
        )
        self.assertNotIn("body", body)

    async def test_end_preserves_separate_operator_sms_and_case_authorization(self):
        command, _ = await self.join()
        self.assertEqual((await self.exchange("end", command))[2]["stage"], "closed")
        sms = {
            "schemaVersion": 1,
            "commandId": str(uuid4()),
            "occurredAt": NOW,
            "body": "Investigate during dormancy",
        }
        self.assertEqual((await self.exchange("sms", sms))[0], 200)
        self.assertEqual((await self.exchange("case"))[0], 200)
        self.assertEqual(len(self.sms.calls), 1)
        self.assertEqual((self.rooms.closed, self.app.closed, self.sms.closed), (0, 0, 0))

    async def test_foreign_origin_and_credentials_never_reach_application(self):
        for token, extra, expected in (
            ("x" * 43, b"", 403),
            (TOKEN, b"Origin: https://foreign.invalid\r\n", 400),
        ):
            with self.subTest(expected=expected):
                status, _, body = await self.exchange("case", token=token, extra=extra)
                self.assertEqual(status, expected)
                self.assertEqual(set(body), {"schemaVersion", "status", "code"})
        self.assertEqual(self.app.calls, 0)

    async def test_exact_routes_and_request_schemas_reject_authority_selectors(self):
        for target in (
            "/v1/channel-policy-demo/case?scope=foreign",
            "/v1/channel-policy-demo/unknown",
            "/v1/channel-policy-demo/case/",
            "/v1/native/prepare",
        ):
            with self.subTest(target=target):
                self.assertEqual((await self.exchange("case", target=target))[0], 400)
        self.assertEqual(
            (await self.exchange("case", {"schemaVersion": 1, "scope": "foreign"}))[0], 400
        )
        self.assertEqual(self.app.calls, 0)

    async def test_duplicate_auth_or_transfer_encoding_is_rejected(self):
        for extra in (
            f"Authorization: Bearer {TOKEN}\r\n".encode(),
            b"Transfer-Encoding: chunked\r\n",
        ):
            with self.subTest(extra=extra):
                self.assertEqual((await self.exchange("case", extra=extra))[0], 400)
        self.assertEqual(self.app.calls, 0)

    async def test_timed_out_actual_calls_retain_four_slots_until_drain(self):
        await self.host.close()
        self.host = ChannelPolicyOperatorHttp(
            self.operator, bearer=TOKEN, call_timeout_s=0.02, cleanup_timeout_s=1
        )
        self.port = (await self.host.start()).port
        self.app.gate = asyncio.Event()
        waiters = [asyncio.create_task(self.exchange("case")) for _ in range(4)]
        for _ in range(4):
            await self.app.entered.get()
        responses = await asyncio.gather(*waiters)
        self.assertTrue(
            all(
                status == 503 and body["code"] == "outcome_unknown" for status, _, body in responses
            )
        )
        self.assertEqual(self.host.metrics()["active_calls"], 4)
        self.assertEqual((await self.exchange("case"))[0], 429)
        self.assertEqual(self.app.calls, 4)
        self.app.gate.set()
        await self.host.close()
        self.assertEqual(self.host.pending_count, 0)

    async def test_end_during_current_read_fences_late_response(self):
        command, _ = await self.join()
        self.rooms.current_gate = asyncio.Event()
        reading = asyncio.create_task(self.exchange("current", command))
        await self.rooms.read_started.wait()
        self.rooms.stage = "closed"
        self.rooms.current_gate.set()
        status, _, body = await reading
        self.assertEqual((status, body["code"]), (409, "closed"))
        self.assertNotIn("fact", body)

    async def test_last_socket_write_rechecks_current_room(self):
        await self.host.close()
        gate = asyncio.Event()
        entered = asyncio.Event()

        class HeldHost(ChannelPolicyOperatorHttp):
            async def _response(inner, connection, status, body):
                if status == 200 and b'"fact"' in body:
                    entered.set()
                    await gate.wait()
                await super()._response(connection, status, body)

        self.host = HeldHost(self.operator, bearer=TOKEN)
        self.port = (await self.host.start()).port
        command, _ = await self.join()
        pending = asyncio.create_task(self.exchange("current", command))
        await entered.wait()
        self.rooms.stage = "closed"
        gate.set()
        status, _, body = await pending
        self.assertEqual((status, body["code"]), (409, "closed"))

    async def test_unknown_original_sms_retains_its_body_and_timestamp(self):
        command = {
            "schemaVersion": 1,
            "commandId": str(uuid4()),
            "occurredAt": NOW,
            "body": "Original synthetic SMS",
        }
        for _ in range(2):
            self.assertEqual((await self.exchange("sms", command))[0], 200)
        self.assertEqual(self.sms.calls[0], self.sms.calls[1])
        self.assertEqual(self.app.calls, 0)

    async def test_host_close_drains_without_closing_borrowed_dependencies(self):
        await self.host.close()
        self.assertEqual(self.host.pending_count, 0)
        self.assertEqual((self.rooms.closed, self.app.closed, self.sms.closed), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
