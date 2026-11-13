"""Actual bounded local HTTP with synthetic receipt peers; no PG/RTC/providers."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import unittest
from unittest.mock import patch
from uuid import uuid4

from services.channel_policy_demo import operator_sms as m
from services.channel_policy_demo.operator_contract import OperatorError, SmsCommand, encode

NOW = "2026-11-13T09:00:00.000Z"


class SmsSigningTests(unittest.TestCase):
    def test_mac_binds_exact_original_utf8_scope_and_fresh_header_time(self):
        c = SmsCommand(str(uuid4()), NOW, "Investigate 🧭 e\u0301")
        route = m.SmsRoute("tenant_demo", "carrier_demo")
        raw, headers = m.signed_sms(c, route, 1794550800)
        message = json.loads(raw)
        self.assertEqual(
            message,
            {
                "schemaVersion": 1,
                "eventId": c.event_id,
                "messageId": c.event_id,
                "senderId": "demo_sms_sender",
                "body": c.body,
                "occurredAt": NOW,
            },
        )
        expected = hmac.new(
            b"O" * 32,
            b"p2.fake_sms.v1\ntenant_demo\nfake_sms\ncarrier_demo\n1794550800\n" + raw,
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(headers["X-P2-Signature"], expected)
        retry_raw, retry_headers = m.signed_sms(c, route, 1794550900)
        self.assertEqual(raw, retry_raw)
        self.assertNotEqual(headers["X-P2-Signature"], retry_headers["X-P2-Signature"])

    def test_huge_and_nonfinite_budgets_are_finite_validation_errors(self):
        route = m.SmsRoute("tenant_demo", "carrier_demo")
        for name in ("observer_timeout_s", "cleanup_timeout_s"):
            for value in (10**1000, -(10**1000), float("inf"), float("nan"), True):
                with (
                    self.subTest(name=name, value=str(value)[:20]),
                    self.assertRaises(OperatorError) as caught,
                ):
                    m.ChannelPolicySmsClient(route, **{name: value})
                self.assertEqual(str(caught.exception), "invalid_input")

    def test_route_rejects_nonlocal_destinations_and_wide_scope(self):
        for changes in (
            {"port": True},
            {"port": 0},
            {"tenant_id": "tenant\nforeign"},
            {"provider_account_id": "http://remote"},
            {"sender_id": "../sender"},
        ):
            with self.subTest(changes=changes), self.assertRaises(OperatorError):
                m.SmsRoute(
                    **(
                        {"tenant_id": "tenant_demo", "provider_account_id": "carrier_demo"}
                        | changes
                    )
                )


class SmsClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.command = SmsCommand(str(uuid4()), NOW, "Investigate this request")
        self.release = asyncio.Event()
        self.release.set()
        self.entered = asyncio.Event()
        self.requests = []
        self.handlers = set()
        self.status = 200
        self.override = None
        self.extra_headers = b""
        self.server = await asyncio.start_server(self.connected, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        self.client = m.ChannelPolicySmsClient(
            m.SmsRoute("tenant_demo", "carrier_demo", port=self.port),
            observer_timeout_s=1,
            cleanup_timeout_s=1,
        )

    def connected(self, reader, writer):
        task = asyncio.create_task(self.handle(reader, writer))
        self.handlers.add(task)
        task.add_done_callback(self.handlers.discard)

    async def handle(self, reader, writer):
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            headers = dict(line.split(b": ", 1) for line in head.split(b"\r\n")[1:-2])
            raw = await reader.readexactly(int(headers[b"Content-Length"]))
            self.requests.append((head, raw))
            self.entered.set()
            await self.release.wait()
            c = self.command
            raw = (
                self.override
                if self.override is not None
                else encode(
                    {
                        "schemaVersion": 1,
                        "kind": "channel.receipt",
                        "replayed": False,
                        "receipt": {
                            "receiptId": str(uuid4()),
                            "eventId": c.event_id,
                            "messageId": c.event_id,
                            "acceptanceSequence": "1",
                            "acceptedAt": NOW,
                        },
                    }
                )
            )
            writer.write(
                f"HTTP/1.1 {self.status} Response\r\nContent-Type: application/json\r\nContent-Length: {len(raw)}\r\nConnection: close\r\n".encode()
                + self.extra_headers
                + b"\r\n"
                + raw
            )
            await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    async def asyncTearDown(self):
        self.release.set()
        await asyncio.wait_for(self.client.close(), 4)
        self.server.close()
        await self.server.wait_closed()
        await asyncio.gather(*tuple(self.handlers))

    async def test_session_factory_failure_is_finite_and_registered_connector_closes(self):
        import aiohttp

        connectors = []

        def fail_session(**kwargs):
            connectors.append(kwargs["connector"])
            raise RuntimeError("PRIVATE_BACKEND_SENTINEL")

        with (
            patch.object(aiohttp, "ClientSession", side_effect=fail_session),
            self.assertRaises(OperatorError) as caught,
        ):
            await self.client.send(self.command)
        self.assertEqual(str(caught.exception), "unavailable")
        self.assertEqual(self.requests, [])
        self.assertEqual(len(connectors), 1)
        await self.client.close()
        self.assertTrue(connectors[0].closed)

    async def test_signing_failure_before_send_preserves_session_and_useful_retry(self):
        with (
            patch.object(m, "signed_sms", side_effect=RuntimeError("PRIVATE_BACKEND_SENTINEL")),
            self.assertRaises(OperatorError) as caught,
        ):
            await self.client.send(self.command)
        self.assertEqual(str(caught.exception), "unavailable")
        self.assertEqual(self.requests, [])
        self.assertEqual((await self.client.send(self.command)).command_id, self.command.command_id)

    async def test_session_close_failure_still_closes_connector_and_can_be_reobserved(self):
        import aiohttp

        connectors = []

        class Session:
            calls = 0

            def post(inner, *args, **kwargs):
                raise RuntimeError("PRIVATE_BACKEND_SENTINEL")

            async def close(inner):
                inner.calls += 1
                if inner.calls == 1:
                    raise RuntimeError("PRIVATE_BACKEND_SENTINEL")

        def session(**kwargs):
            connectors.append(kwargs["connector"])
            return Session()

        with (
            patch.object(aiohttp, "ClientSession", side_effect=session),
            self.assertRaises(OperatorError),
        ):
            await self.client.send(self.command)
        with self.assertRaises(OperatorError) as caught:
            await self.client.close()
        self.assertEqual(str(caught.exception), "cleanup_incomplete")
        self.assertTrue(connectors[0].closed)
        await self.client.close()
        self.assertEqual(len(connectors), 1)

    async def test_actual_http_acceptance_uses_fixed_path_and_original_body(self):
        observed = await self.client.send(self.command)
        self.assertEqual(observed.command_id, self.command.command_id)
        self.assertEqual(observed.event_id, self.command.event_id)
        head, raw = self.requests[0]
        self.assertTrue(head.startswith(b"POST /webhooks/fake-sms HTTP/1.1\r\n"))
        self.assertEqual(json.loads(raw)["body"], self.command.body)
        self.assertNotIn(b"Authorization", head)
        self.assertEqual(self.client.pending_count, 0)

    async def test_unknown_waiter_retains_call_and_blocks_new_actual_send(self):
        self.client = m.ChannelPolicySmsClient(
            m.SmsRoute("tenant_demo", "carrier_demo", port=self.port), observer_timeout_s=0.02
        )
        self.release.clear()
        with self.assertRaises(OperatorError) as caught:
            await self.client.send(self.command)
        self.assertEqual(caught.exception.code, "outcome_unknown")
        self.assertEqual(self.client.pending_count, 1)
        with self.assertRaises(OperatorError) as second:
            await self.client.send(self.command)
        self.assertEqual(second.exception.code, "capacity")
        self.assertEqual(len(self.requests), 1)
        self.release.set()
        await self.client.close()
        self.assertEqual(self.client.pending_count, 0)

    async def test_cancelled_waiter_does_not_cancel_actual_acceptance(self):
        self.release.clear()
        waiter = asyncio.create_task(self.client.send(self.command))
        await self.entered.wait()
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiter
        self.assertEqual(self.client.pending_count, 1)
        self.release.set()
        await self.client.close()
        self.assertEqual(len(self.requests), 1)

    async def test_incomplete_close_retains_original_owner_until_actual_drain(self):
        self.client = m.ChannelPolicySmsClient(
            m.SmsRoute("tenant_demo", "carrier_demo", port=self.port), cleanup_timeout_s=0.02
        )
        self.release.clear()
        waiter = asyncio.create_task(self.client.send(self.command))
        await self.entered.wait()
        with self.assertRaises(OperatorError) as caught:
            await self.client.close()
        self.assertEqual(caught.exception.code, "cleanup_incomplete")
        with self.assertRaises(OperatorError) as closed:
            await self.client.send(self.command)
        self.assertEqual(closed.exception.code, "closed")
        self.release.set()
        await waiter
        await self.client.close()
        self.assertEqual(self.client.pending_count, 0)

    async def test_malformed_or_foreign_success_is_unknown_not_new_authority(self):
        for raw in (b"{}", b'{"private":"PRIVATE_BACKEND_SENTINEL"}', b"[1]"):
            self.override = raw
            with self.subTest(raw=raw), self.assertRaises(OperatorError) as caught:
                await self.client.send(self.command)
            self.assertEqual(caught.exception.code, "outcome_unknown")
            self.assertNotIn("PRIVATE", str(caught.exception))

    async def test_rejected_errors_are_finite_and_remote_503_is_unknown(self):
        for status, code in (
            (400, "invalid_input"),
            (403, "unauthorized"),
            (409, "conflict"),
            (429, "capacity"),
            (503, "outcome_unknown"),
        ):
            self.status = status
            self.override = b"PRIVATE_BACKEND_SENTINEL"
            with self.subTest(status=status), self.assertRaises(OperatorError) as caught:
                await self.client.send(self.command)
            self.assertEqual(caught.exception.code, code)

    async def test_redirect_is_never_followed(self):
        self.status = 302
        self.extra_headers = b"Location: http://127.0.0.1:1/private\r\n"
        with self.assertRaises(OperatorError) as caught:
            await self.client.send(self.command)
        self.assertEqual(caught.exception.code, "outcome_unknown")
        self.assertEqual(len(self.requests), 1)

    async def test_task_allocation_failure_admits_no_http_request(self):
        with patch.object(
            asyncio, "create_task", side_effect=RuntimeError("PRIVATE_BACKEND_SENTINEL")
        ):
            with self.assertRaises(OperatorError) as caught:
                await self.client.send(self.command)
            self.assertEqual(str(caught.exception), "unavailable")
        self.assertEqual(self.client.pending_count, 0)
        self.assertEqual(self.requests, [])
        self.assertEqual((await self.client.send(self.command)).command_id, self.command.command_id)


if __name__ == "__main__":
    unittest.main()
