"""Real loopback transport plus public P3 facades; P1 I/O is an explicit fake.

Transport drain and authority drain are separate. These tests qualify their close
ordering, not real PostgreSQL, persisted P2 intake or provider inference.
"""

from __future__ import annotations

import asyncio
import copy
import json
import unittest

import test_p3_channel_origin as fixture

from delegation_reliability import ChannelPolicyCoordinator, CoordinatorError
from delegation_reliability.fixed_policy_contracts import produce_fixed_policy_request
from services.channel_policy_demo import origin_http as http


class _CompositionCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        raw = copy.deepcopy(fixture.FIXTURE["channel_cases"][0]["producer_input"]["request"])
        raw.pop("input_fingerprint")
        template = produce_fixed_policy_request(raw)
        self.binding = fixture.m.ChannelOriginBinding(
            fixture.FIXTURE["profile_id"],
            template.scope,
            template.case_id,
            template.conversation_id,
            fixture.FIXTURE["p2_cases"][0]["submission"]["message"]["senderId"],
        )
        self.port = fixture.WorkPort(template.scope)
        self.port.release = asyncio.Event()
        cases = fixture.Cases(template.scope, template.case_id, 1)
        self.coordinator = ChannelPolicyCoordinator(
            executions=self.port,
            scope=template.scope,
            case_authority=cases,
            timeout_ms=self.CORE_TIMEOUT_MS,
            cleanup_ms=20,
        )
        self.service = fixture.m.ChannelOriginService(
            binding=self.binding,
            template=template,
            coordinator=self.coordinator,
        )
        self.host = http.ChannelOriginHttp(
            self.service,
            operation_bearer="o" * 43,
            call_timeout_s=self.HTTP_TIMEOUT_S,
            cleanup_timeout_s=0.02,
        )
        self.endpoint = await self.host.start()
        self.writers = []

    async def asyncTearDown(self):
        self.port.release.set()
        for writer in self.writers:
            writer.close()
            await writer.wait_closed()
        await self.host.close()
        await self.service.close()

    CORE_TIMEOUT_MS = 50
    HTTP_TIMEOUT_S = 1

    async def response(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.endpoint.port)
        self.writers.append(writer)
        body = fixture.FIXTURE["p2_cases"][0]["accept_frame_canonical"].encode()
        writer.write(
            (
                "POST /v1/investigations/accept HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{self.endpoint.port}\r\n"
                f"Authorization: Bearer {'o' * 43}\r\n"
                "Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
            ).encode()
            + body
        )
        await writer.drain()
        async with asyncio.timeout(2):
            raw = await reader.read()
        head, _, payload = raw.partition(b"\r\n\r\n")
        self.assertTrue(head.startswith(b"HTTP/1.1 503 "))
        self.assertEqual(
            json.loads(payload),
            {
                "schemaVersion": 1,
                "status": "error",
                "code": "acknowledgement_unknown",
            },
        )


class CoreWaiterFirstTests(_CompositionCase):
    async def test_core_waiter_settles_before_actual_p1_io_and_application_retains_owner(self):
        await self.response()
        await self.host.close()
        self.assertEqual(self.host.metrics()["active"], 0)
        self.assertEqual(self.host.metrics()["handlers"], 0)
        self.assertEqual((self.service.metrics()["active"], self.port.pending_count), (1, 1))
        with self.assertRaisesRegex(CoordinatorError, "^cleanup_incomplete$"):
            await self.service.close()
        self.assertEqual(self.port.closed, 0)
        self.port.release.set()
        await asyncio.wait_for(self.port.settled.wait(), 1)
        await self.service.close()
        self.assertEqual(
            (self.port.submits, self.port.closed, len(self.port.ledger.records)), (1, 1, 1)
        )


class HttpObserverFirstTests(_CompositionCase):
    CORE_TIMEOUT_MS = 5000
    HTTP_TIMEOUT_S = 0.03

    async def test_http_observer_settles_first_and_host_retains_service_until_actual_settlement(
        self,
    ):
        await self.response()
        self.assertEqual((self.host.metrics()["active"], self.host.metrics()["handlers"]), (1, 1))
        self.assertEqual((self.service.metrics()["active"], self.port.pending_count), (1, 1))
        with self.assertRaisesRegex(http.OriginHttpError, "^cleanup_incomplete$"):
            await self.host.close()
        self.assertEqual(self.port.closed, 0)
        self.port.release.set()
        await asyncio.wait_for(self.port.settled.wait(), 1)
        await self.host.close()
        await self.service.close()
        self.assertEqual(
            (self.host.metrics()["active"], self.service.metrics()["active"], self.port.closed),
            (0, 0, 1),
        )
        self.assertEqual((self.port.submits, len(self.port.ledger.records)), (1, 1))
