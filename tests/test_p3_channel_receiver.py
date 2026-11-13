"""Actual bounded loopback transport and public P1 producer; no PG/SFU/provider."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import importlib.util
import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp import web

from continuity_lab.delivery_api import DeliveryIntent, DeliveryReceipt
from continuity_lab.work_api import WorkError, WorkScope

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "channel_result_receiver_tested", ROOT / "local-setup/scripts/p3_channel_receiver.py"
)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)
FIXTURE = json.loads((ROOT / "contracts/delegation/result-receiver-v1.json").read_text())
TOKEN = "q" * 43


def intent():
    value = json.loads(FIXTURE["intent_canonical"])
    return DeliveryIntent(
        value["delivery_id"],
        WorkScope(**value["scope"]),
        value["work_id"],
        value["attempt_id"],
        value["result_sha256"],
        value["receiver_id"],
        value["recipient_id"],
        base64.b64decode(value["body"], validate=True),
        value["prepared_at_ms"],
    )


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


class ContractTests(unittest.TestCase):
    def client(self):
        original = intent()
        return m.ChannelResultReceiver(
            port=12345,
            publisher_token=TOKEN,
            receiver_id=original.receiver_id,
            scope=original.scope,
            recipient_id=original.recipient_id,
        )

    def test_shared_fixture_matches_actual_public_p1_producer_and_original_v2_body(self):
        original = intent()
        policy = json.loads((ROOT / "contracts/delegation/fixed-policy-v2.json").read_text())
        self.assertEqual(original.canonical().decode("ascii"), FIXTURE["intent_canonical"])
        self.assertEqual(original.body, policy["result_canonical"].encode())
        self.assertEqual(original.result_sha256, hashlib.sha256(original.body).hexdigest())
        self.assertEqual(
            m.receipt_from(FIXTURE["receipt"], original), DeliveryReceipt(**FIXTURE["receipt"])
        )
        notice_digest = hashlib.sha256(FIXTURE["notice"].encode()).hexdigest()
        self.assertNotEqual(original.result_sha256, notice_digest)
        self.assertEqual(len(FIXTURE["negative_intents"]), 9)
        maximum = replace(
            original, body=b"x" * 8192, result_sha256=hashlib.sha256(b"x" * 8192).hexdigest()
        )
        self.assertLessEqual(len(maximum.canonical()), m.INTENT_BYTES)
        with self.assertRaises(WorkError):
            replace(
                maximum, body=b"x" * 8193, result_sha256=hashlib.sha256(b"x" * 8193).hexdigest()
            )

    def test_constructor_is_inert_and_rejects_untrusted_configuration(self):
        original = intent()
        config = {
            "port": 12345,
            "publisher_token": TOKEN,
            "receiver_id": original.receiver_id,
            "scope": original.scope,
            "recipient_id": original.recipient_id,
        }
        with patch.object(m.aiohttp, "ClientSession", side_effect=AssertionError("I/O")):
            client = m.ChannelResultReceiver(**config)
            self.assertEqual(client.receiver_id, original.receiver_id)
            self.assertEqual(client.pending_count, 0)
            self.assertNotIn(TOKEN, repr(client))
            for change in (
                {"port": True},
                {"port": 0},
                {"port": 65536},
                {"publisher_token": "secret\nheader"},
                {"receiver_id": "not-uuid"},
                {"scope": {}},
                {"recipient_id": "outside route"},
                {"timeout_ms": True},
                {"timeout_ms": 5001},
                {"cleanup_ms": 2001},
            ):
                with self.subTest(change=list(change)), self.assertRaises(WorkError):
                    m.ChannelResultReceiver(**{**config, **change})

    def test_foreign_loop_call_and_close_reject_before_owner_mutation_without_network(self):
        client = self.client()
        receipt = DeliveryReceipt(**FIXTURE["receipt"])

        async def denied(awaitable):
            with self.assertRaises(WorkError) as caught:
                await awaitable
            self.assertEqual(caught.exception.code, "invalid_input")

        with (
            asyncio.Runner() as owner,
            asyncio.Runner() as foreign,
            patch.object(client, "_request", AsyncMock(return_value=receipt)) as request,
            patch.object(m.aiohttp, "ClientSession", side_effect=AssertionError("network")),
        ):
            self.assertEqual(owner.run(client.find(intent())), receipt)
            foreign.run(denied(client.find(intent())))
            foreign.run(denied(client.close()))
            self.assertEqual(request.await_count, 1)
            self.assertEqual(client.pending_count, 0)
            self.assertFalse(client._closing)
            self.assertIsNone(client._session)
            self.assertIsNone(client._close_task)
            owner.run(client.close())

    def test_session_factory_runtime_failure_is_safe_and_connector_stays_owned(self):
        async def check():
            client = self.client()
            try:
                with patch.object(
                    m.aiohttp, "ClientSession", side_effect=RuntimeError("PRIVATE_FACTORY_SENTINEL")
                ) as factory:
                    for operation, code in (
                        (client.accept, "acknowledgement_unknown"),
                        (client.find, "storage_unavailable"),
                    ):
                        with self.assertRaises(WorkError) as caught:
                            await operation(intent())
                        self.assertEqual(caught.exception.code, code)
                        self.assertNotIn("PRIVATE", str(caught.exception))
                    self.assertEqual(factory.call_count, 2)
                    self.assertIs(factory.call_args_list[0].kwargs["connector"], client._connector)
                    self.assertIs(factory.call_args_list[1].kwargs["connector"], client._connector)
                    self.assertIsNone(client._session)
                    self.assertIsNotNone(client._connector)
                    self.assertFalse(client._connector.closed)
                    self.assertEqual(client.pending_count, 0)
                with patch.object(
                    client._connector,
                    "close",
                    side_effect=RuntimeError("PRIVATE_CONNECTOR_SENTINEL"),
                ):
                    with self.assertRaises(WorkError) as caught:
                        await client.close()
                    self.assertEqual(caught.exception.code, "cleanup_incomplete")
                    self.assertNotIn("PRIVATE", str(caught.exception))
                    self.assertFalse(client._connector.closed)
            finally:
                await client.close()
            self.assertTrue(client._connector.closed)

        asyncio.run(check())

    def test_request_runtime_failure_is_safe_and_failed_close_retains_retry(self):
        async def check():
            client = self.client()
            try:
                with patch.object(
                    m.aiohttp.ClientSession,
                    "post",
                    side_effect=RuntimeError("PRIVATE_REQUEST_SENTINEL"),
                ) as request:
                    for operation, code in (
                        (client.accept, "acknowledgement_unknown"),
                        (client.find, "storage_unavailable"),
                    ):
                        with self.assertRaises(WorkError) as caught:
                            await operation(intent())
                        self.assertEqual(caught.exception.code, code)
                        self.assertNotIn("PRIVATE", str(caught.exception))
                    self.assertEqual(request.call_count, 2)
                self.assertIsNotNone(client._session)
                self.assertFalse(client._session.closed)
                self.assertEqual(client._session.timeout.total, 5)
                self.assertEqual(client._session.timeout.ceil_threshold, 6)
                with patch.object(
                    client._session, "close", side_effect=RuntimeError("PRIVATE_CLOSE_SENTINEL")
                ):
                    with self.assertRaises(WorkError) as caught:
                        await client.close()
                    self.assertEqual(caught.exception.code, "cleanup_incomplete")
                    self.assertNotIn("PRIVATE", str(caught.exception))
                    self.assertTrue(client._connector.closed)
                await client.close()
                self.assertTrue(client._session.closed)
                self.assertTrue(client._connector.closed)
                self.assertEqual(client.pending_count, 0)
            finally:
                await client.close()

        asyncio.run(check())


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.original = intent()
        self.receipt = FIXTURE["receipt"].copy()
        self.response = {"schemaVersion": 1, "status": "accepted", "receipt": self.receipt}
        self.raw = None
        self.status = 200
        self.headers = {"Content-Type": "application/json", "Cache-Control": "no-store"}
        self.requests = []
        self.entered = asyncio.Event()
        self.release = None
        self.redirect_seen = False
        self.runner = web.AppRunner(self.app(), access_log=None)
        await self.runner.setup()
        server = web.TCPSite(self.runner, "127.0.0.1", 0)
        await server.start()
        addresses = self.runner.addresses
        self.port = addresses[0][1]
        self.clients = []

    def app(self):
        app = web.Application()

        async def handler(request):
            self.assertEqual(request.headers.get("Authorization"), "Bearer " + TOKEN)
            self.assertEqual(request.headers.get("Content-Type"), "application/json")
            self.requests.append((request.path, await request.read()))
            self.entered.set()
            if self.release is not None:
                await self.release.wait()
            return web.Response(
                body=self.raw if self.raw is not None else wire(self.response),
                status=self.status,
                headers=self.headers,
            )

        async def redirected(_request):
            self.redirect_seen = True
            return web.Response(text="not allowed")

        app.router.add_post("/v1/p2-result-receiver/{operation}", handler)
        app.router.add_post("/redirect", redirected)
        return app

    def client(self, **changes):
        client = m.ChannelResultReceiver(
            **{
                "port": self.port,
                "publisher_token": TOKEN,
                "receiver_id": self.original.receiver_id,
                "scope": self.original.scope,
                "recipient_id": self.original.recipient_id,
                **changes,
            }
        )
        self.clients.append(client)
        return client

    async def asyncTearDown(self):
        if self.release is not None:
            self.release.set()
        for client in self.clients:
            await client.close()
            self.assertEqual(client.pending_count, 0)
        await self.runner.cleanup()

    async def error(self, awaitable, code):
        with self.assertRaises(WorkError) as caught:
            await awaitable
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn(TOKEN, str(caught.exception))

    async def test_actual_accept_and_lookup_keep_exact_original_bytes_and_receipt(self):
        client = self.client()
        expected = DeliveryReceipt(**self.receipt)
        self.assertEqual(await client.accept(self.original), expected)
        self.assertEqual(await client.find(self.original), expected)
        self.assertEqual(
            [p for p, _ in self.requests],
            ["/v1/p2-result-receiver/accept", "/v1/p2-result-receiver/find"],
        )
        self.assertTrue(all(body == self.original.canonical() for _, body in self.requests))
        self.assertEqual(client.metrics["accepted"], 1)
        self.assertEqual(client.metrics["found"], 1)
        with self.assertRaises(TypeError):
            client.metrics["accepted"] = 3

    async def test_missing_is_lookup_only_and_never_a_successful_acceptance(self):
        client = self.client()
        self.response = {"schemaVersion": 1, "status": "missing", "receipt": None}
        self.assertIsNone(await client.find(self.original))
        await self.error(client.accept(self.original), "acknowledgement_unknown")
        self.assertEqual(len(self.requests), 2)

    async def test_foreign_scope_receiver_or_recipient_denied_before_any_network_call(self):
        client = self.client()
        for changed, code in (
            (replace(self.original, scope=WorkScope("foreign", "account_demo")), "unauthorized"),
            (
                replace(self.original, receiver_id="66666666-6666-4666-8666-666666666666"),
                "identity_conflict",
            ),
            (replace(self.original, recipient_id="other_recipient"), "identity_conflict"),
        ):
            await self.error(client.accept(changed), code)
        self.assertEqual(self.requests, [])
        self.assertEqual(client.pending_count, 0)

    async def test_every_receipt_binding_and_exact_shape_are_revalidated(self):
        client = self.client()
        for key, value in (
            ("delivery_id", "66666666-6666-4666-8666-666666666666"),
            ("receiver_id", "66666666-6666-4666-8666-666666666666"),
            ("recipient_id", "other_recipient"),
            ("result_sha256", "0" * 64),
            ("accepted_at_ms", True),
            ("receipt_id", "secret-sentinel"),
            ("extra", "sentinel"),
        ):
            self.response = {
                "schemaVersion": 1,
                "status": "accepted",
                "receipt": {**self.receipt, key: value},
            }
            await self.error(client.accept(self.original), "acknowledgement_unknown")

    async def test_duplicate_keys_unknown_fields_boolean_versions_and_bad_json_reject(self):
        client = self.client()
        for raw in (
            b'{"schemaVersion":1,"schemaVersion":1,"status":"missing","receipt":null}',
            wire({**self.response, "extra": "secret-sentinel"}),
            wire({**self.response, "schemaVersion": True}),
            b"[]",
            b'{"schemaVersion":NaN}',
            b"\xff",
            b"{" * 2048,
        ):
            self.raw = raw
            await self.error(client.find(self.original), "storage_unavailable")

    async def test_response_size_content_type_encoding_cache_and_redirect_fail_closed(self):
        client = self.client()
        self.raw = b"x" * 2049
        await self.error(client.accept(self.original), "acknowledgement_unknown")
        self.raw = None
        for headers in (
            {"Content-Type": "text/plain", "Cache-Control": "no-store"},
            {"Content-Type": "application/json"},
            {
                "Content-Type": "application/json",
                "Cache-Control": "no-store",
                "Content-Encoding": "gzip",
            },
        ):
            self.headers = headers
            await self.error(client.find(self.original), "storage_unavailable")
        self.headers = {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
            "Location": f"http://127.0.0.1:{self.port}/redirect",
        }
        self.status = 307
        await self.error(client.accept(self.original), "acknowledgement_unknown")
        self.assertFalse(self.redirect_seen)

    async def test_finite_safe_remote_errors_and_arbitrary_error_text_never_escape(self):
        client = self.client()
        for code, translated in (
            ("AccessDenied", "unauthorized"),
            ("IdentityConflict", "identity_conflict"),
            ("Overloaded", "capacity"),
            ("UpgradeRequired", "schema_mismatch"),
        ):
            self.status = 403
            self.response = {"schemaVersion": 1, "status": "error", "error": code}
            await self.error(client.accept(self.original), translated)
        self.response["error"] = "secret-sentinel: provider error payload"
        await self.error(client.accept(self.original), "acknowledgement_unknown")
        self.assertEqual(client.metrics["rejected"], 5)

    async def test_timeout_retains_two_actual_calls_and_prevents_a_third_invocation(self):
        self.release = asyncio.Event()
        client = self.client(timeout_ms=20, cleanup_ms=20)
        await self.error(client.accept(self.original), "acknowledgement_unknown")
        await self.error(client.find(self.original), "storage_unavailable")
        self.assertEqual(client.pending_count, 2)
        await self.error(client.accept(self.original), "capacity")
        await self.error(client.close(), "cleanup_incomplete")
        self.assertEqual(client.pending_count, 2)
        self.assertEqual(len(self.requests), 2)
        await self.error(client.find(self.original), "closed")
        self.release.set()
        await asyncio.sleep(0.01)
        await client.close()
        self.assertEqual(client.pending_count, 0)
        self.assertEqual(client.metrics["cleanup_incomplete"], 1)

    async def test_caller_cancellation_propagates_and_keeps_original_io_until_settlement(self):
        self.release = asyncio.Event()
        client = self.client()
        caller = asyncio.create_task(client.accept(self.original))
        await asyncio.wait_for(self.entered.wait(), 1)
        caller.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await caller
        self.assertEqual(client.pending_count, 1)
        self.assertEqual(client.metrics["abandoned"], 1)
        self.release.set()
        await client.close()
        self.assertEqual(client.pending_count, 0)
        self.assertEqual(client.metrics["accepted"], 1)

    async def test_fresh_client_can_make_useful_progress_after_closed_original_client(self):
        first = self.client()
        await first.close()
        await self.error(first.accept(self.original), "closed")
        second = self.client()
        self.assertEqual(await second.find(self.original), DeliveryReceipt(**self.receipt))
        self.assertEqual(len(self.requests), 1)


if __name__ == "__main__":
    unittest.main()
