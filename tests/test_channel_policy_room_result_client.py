"""Real owned loopback TCP plus cancellation/close controls; no PG/provider/RTC."""

from __future__ import annotations

import asyncio
import base64
import copy
import gc
import hashlib
import json
import subprocess
import sys
import unittest
import warnings
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from services.channel_policy_demo import room_result_client as m

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = "PRIVATE_ROOM_RESULT_SENTINEL"
TOKEN = "v" * 43


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def view(delivery):
    body = b'{"transport_fixture":true}'
    sha = hashlib.sha256(body).hexdigest()
    return {
        "schemaVersion": 1,
        "intent": {
            "delivery_id": delivery,
            "scope": {"tenant_id": "tenant_demo", "account_id": "account_demo"},
            "work_id": str(uuid4()),
            "attempt_id": str(uuid4()),
            "result_sha256": sha,
            "receiver_id": str(uuid4()),
            "recipient_id": "recipient_demo",
            "body": base64.b64encode(body).decode(),
            "prepared_at_ms": 1900000000000,
        },
        "receipt": {
            "delivery_id": delivery,
            "receipt_id": str(uuid4()),
            "receiver_id": "",
            "recipient_id": "recipient_demo",
            "result_sha256": sha,
            "accepted_at_ms": 1900000000001,
        },
        "case": {
            "schemaVersion": 1,
            "source": "p1_public_v4",
            "scope": {"tenantId": "tenant_demo", "accountId": "account_demo"},
            "caseId": "case_demo",
            "conversationId": "conversation_demo",
            "revision": "1",
            "request": {
                "schemaVersion": 1,
                "kind": "booking_investigation",
                "bookingReference": "ABC100",
                "newCheckIn": "2030-12-11",
                "investigationConsent": True,
            },
            "workflow": None,
            "intent": {"state": "not_committed", "intentId": None},
            "mutation": {
                "state": "not_observed",
                "outcome": "not_observed",
                "cancellation": "not_observed",
                "effectId": None,
                "outcomeEventId": None,
            },
            "supplierResult": None,
            "sourceRevision": "a" * 64,
        },
        "observed": {
            "p2ObservedAt": "2026-11-13T00:00:00.001Z",
            "caseObservedAt": "2026-11-13T00:00:00.002Z",
            "disclosureAdmittedAt": "2026-11-13T00:00:00.003Z",
            "atomic": False,
        },
    }


def response(raw, status=200, headers=None, extra=b""):
    values = [
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(raw))),
        ("Connection", "close"),
        ("Cache-Control", "no-store"),
    ]
    if headers is not None:
        values = headers
    return (
        (
            f"HTTP/1.1 {status} Response\r\n" + "".join(f"{k}: {v}\r\n" for k, v in values) + "\r\n"
        ).encode()
        + raw
        + extra
    )


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.delivery = str(uuid4())
        self.binding = m.RoomResultBinding(str(uuid4()), "1")
        self.wire = view(self.delivery)
        self.wire["receipt"]["receiver_id"] = self.wire["intent"]["receiver_id"]
        self.output = response(encoded(self.wire))
        self.release = None
        self.requests = []
        self.connections = 0
        self.handlers = set()
        self.writers = set()
        self.failures = []
        self.clients = []
        self.waiters = []
        self.releases = []
        self.server = await asyncio.start_server(self.accepted, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        self.client = self.opened()

    def opened(self, **kwargs):
        client = m.RoomResultHttpClient(
            m.RoomResultEndpoint(port=self.port),
            self.binding,
            m.RoomViewCredential(TOKEN),
            **kwargs,
        )
        self.clients.append(client)
        return client

    async def accepted(self, reader, writer):
        task = asyncio.current_task()
        self.handlers.add(task)
        self.writers.add(writer)
        self.connections += 1
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            fields = {}
            for line in head[:-4].split(b"\r\n")[1:]:
                key, value = line.split(b": ", 1)
                fields[key.decode().lower()] = value.decode()
            raw = await reader.readexactly(int(fields["content-length"]))
            self.requests.append((head, fields, raw))
            if self.release is not None:
                await self.release.wait()
            writer.write(self.output)
            await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        except Exception as error:  # noqa: BLE001 - finite test-server failure capture
            self.failures.append(type(error).__name__)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
            self.writers.discard(writer)
            self.handlers.discard(task)

    async def asyncTearDown(self):
        if self.release is not None:
            self.release.set()
        for event in self.releases:
            event.set()
        for writer in self.writers:
            writer.close()
        for task in self.waiters:
            if not task.done():
                task.cancel()
        if self.waiters:
            await asyncio.gather(*self.waiters, return_exceptions=True)
        for client in self.clients:
            for _ in range(3):
                try:
                    await client.close()
                    break
                except m.RoomResultError:
                    await asyncio.sleep(0)
            self.assertEqual(client.pending_count, 0)
        self.server.close()
        await self.server.wait_closed()
        async with asyncio.timeout(2):
            while self.handlers:
                await asyncio.sleep(0)
        self.assertEqual(self.failures, [])

    async def until(self, predicate):
        async with asyncio.timeout(2):
            while not predicate():
                await asyncio.sleep(0)

    async def assert_code(self, code, client=None):
        with self.assertRaises(m.RoomResultError) as caught:
            await (client or self.client).read(delivery_id=self.delivery)
        self.assertEqual((caught.exception.code, caught.exception.args), (code, (code,)))
        self.assertNotIn(PRIVATE, str(caught.exception))

    async def test_real_tcp_request_exact_fixed_room_body_and_five_headers(self):
        expected = encoded(
            {
                "schemaVersion": 1,
                "nodeEpoch": self.binding.node_epoch,
                "generation": "1",
                "deliveryId": self.delivery,
            }
        )
        value = await self.client.read(delivery_id=self.delivery)
        self.assertEqual(value, encoded(self.wire))
        head, fields, raw = self.requests[0]
        self.assertTrue(
            head.startswith(b"POST /v1/channel-policy/rooms/native-result HTTP/1.1\r\n")
        )
        self.assertEqual(
            fields,
            {
                "host": f"127.0.0.1:{self.port}",
                "authorization": "Bearer " + TOKEN,
                "content-type": "application/json",
                "content-length": str(len(expected)),
                "connection": "close",
            },
        )
        self.assertEqual(raw, expected)
        self.assertNotIn(b"nativeBearer", raw)
        self.assertNotIn(b"scope", raw)
        self.assertEqual(self.client.pending_count, 0)

    async def test_invalid_caller_delivery_rejects_before_any_connection(self):
        for value in (True, {}, PRIVATE, self.delivery.upper(), self.delivery + "\n"):
            with self.assertRaisesRegex(m.RoomResultError, "invalid_input"):
                await self.client.read(delivery_id=value)
        self.assertEqual((self.connections, self.client.pending_count), (0, 0))
        self.assertIsNotNone(await self.client.read(delivery_id=self.delivery))

    async def test_publication_allocation_failure_is_finite_before_socket_then_progresses(self):
        loop = asyncio.get_running_loop()
        with patch.object(loop, "create_future", side_effect=RuntimeError(PRIVATE)):
            await self.assert_code("unavailable")
        self.assertEqual((self.connections, self.client.pending_count), (0, 0))
        self.assertIsNotNone(await self.client.read(delivery_id=self.delivery))

    async def test_only_literal_null_is_absence_and_real_view_bytes_are_unadapted(self):
        self.output = response(b"null")
        self.assertIsNone(await self.client.read(delivery_id=self.delivery))
        for raw in [b" null", b"null\n", b"{}", b"[]", b"false"]:
            self.output = response(raw)
            await self.assert_code("invalid_state")
        raw = json.dumps(self.wire, sort_keys=True, separators=(",", ":")).encode()
        self.output = response(raw)
        self.assertEqual(await self.client.read(delivery_id=self.delivery), raw)

    async def test_valid_standard_node_date_is_allowed_without_clock_authority(self):
        raw = encoded(self.wire)
        headers = [
            ("Date", "Fri, 13 Nov 2026 00:00:00 GMT"),
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(raw))),
            ("Connection", "close"),
            ("Cache-Control", "no-store"),
        ]
        self.output = response(raw, headers=headers)
        self.assertEqual(await self.client.read(delivery_id=self.delivery), raw)

    async def test_foreign_delivery_and_receipt_route_swaps_are_denied(self):
        variants = []
        for part, field, value in [
            ("intent", "delivery_id", str(uuid4())),
            ("receipt", "delivery_id", str(uuid4())),
            ("receipt", "receiver_id", str(uuid4())),
            ("receipt", "recipient_id", "foreign_recipient"),
            ("receipt", "result_sha256", "0" * 64),
        ]:
            v = copy.deepcopy(self.wire)
            v[part][field] = value
            variants.append(v)
        v = copy.deepcopy(self.wire)
        v["case"]["scope"]["accountId"] = "foreign_account"
        variants.append(v)
        for v in variants:
            self.output = response(encoded(v))
            await self.assert_code("invalid_state")
        self.output = response(encoded(self.wire))
        self.assertEqual(await self.client.read(delivery_id=self.delivery), encoded(self.wire))

    async def test_closed_topview_typed_intent_receipt_and_observation_schema(self):
        mutations = [
            lambda v: v.update(extra=PRIVATE),
            lambda v: v.update(schemaVersion=True),
            lambda v: v["intent"].update(prepared_at_ms=True),
            lambda v: v["intent"].update(body="not-base64"),
            lambda v: v["receipt"].update(extra=PRIVATE),
            lambda v: v["case"].update(extra=PRIVATE),
            lambda v: v["case"].update(source="standalone_reference_v1"),
            lambda v: v["case"].update(revision="01"),
            lambda v: v["observed"].update(atomic=True),
        ]
        for mutate in mutations:
            value = copy.deepcopy(self.wire)
            mutate(value)
            self.output = response(encoded(value))
            await self.assert_code("invalid_state")

    async def test_utf8_duplicates_nonfinite_surrogates_and_oversized_payloads_fail(self):
        for raw in [
            b"\xff",
            b'{"schemaVersion":1,"schemaVersion":1}',
            b"NaN",
            b'{"x":"\\ud800"}',
            b"x" * 32769,
        ]:
            self.output = response(raw)
            await self.assert_code("invalid_state")

    async def test_finite_operational_errors_never_become_empty(self):
        for status, code, expected in [
            (400, "invalid_input", "invalid_input"),
            (401, "unauthorized", "unauthorized"),
            (429, "capacity", "capacity"),
            (503, "closed", "closed"),
            (503, "unavailable", "unavailable"),
            (409, "conflict", "unavailable"),
            (409, "recovery_required", "unavailable"),
            (503, "outcome_unknown", "unavailable"),
            (503, "cleanup_incomplete", "cleanup_incomplete"),
        ]:
            self.output = response(
                encoded({"schemaVersion": 1, "status": "unavailable", "code": code}), status
            )
            await self.assert_code(expected)
        self.output = response(b"null", 401)
        await self.assert_code("unavailable")
        self.assertEqual(len(self.requests), 10)

    async def test_private_or_malformed_error_fields_remain_finite(self):
        for value in [
            {"schemaVersion": 1, "status": "unavailable", "code": PRIVATE},
            {"schemaVersion": True, "status": "unavailable", "code": "unauthorized"},
            {"schemaVersion": 1, "status": "unavailable", "code": []},
            {
                "schemaVersion": 1,
                "status": "unavailable",
                "code": "unavailable",
                "private": PRIVATE,
            },
        ]:
            self.output = response(encoded(value), 503)
            await self.assert_code("unavailable")
        self.output = response(encoded(self.wire))
        self.assertIsNotNone(await self.client.read(delivery_id=self.delivery))

    async def test_response_framing_headers_and_status_bounds(self):
        raw = encoded(self.wire)
        normal = [
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(raw))),
            ("Connection", "close"),
            ("Cache-Control", "no-store"),
        ]
        variants = [
            response(raw, headers=normal + [("Content-Length", str(len(raw)))]),
            response(raw, headers=normal + [("Transfer-Encoding", "chunked")]),
            response(raw, headers=normal + [("Content-Encoding", "gzip")]),
            response(raw, headers=normal + [("Date", "private")]),
            response(raw, headers=normal + [("X-Private", PRIVATE)]),
            response(raw, headers=[x for x in normal if x[0] != "Content-Length"]),
            response(
                raw, headers=[(k, "0" + v if k == "Content-Length" else v) for k, v in normal]
            ),
            response(
                raw, headers=[(k, "keep-alive" if k == "Connection" else v) for k, v in normal]
            ),
            response(
                raw, headers=[(k, "public" if k == "Cache-Control" else v) for k, v in normal]
            ),
            response(raw, status=204),
            response(raw, extra=b"x"),
            response(raw).replace(b"HTTP/1.1", b"HTTP/1.0", 1),
            b"HTTP/1.1 200 Response\r\nX: " + b"x" * 4100 + b"\r\n\r\n",
        ]
        for output in variants:
            self.output = output
            with self.assertRaises(m.RoomResultError):
                await self.client.read(delivery_id=self.delivery)
        self.output = response(encoded(self.wire))
        self.assertIsNotNone(await self.client.read(delivery_id=self.delivery))

    async def test_two_actual_timed_out_calls_hold_capacity_and_incomplete_close(self):
        self.release = asyncio.Event()
        client = self.opened(timeout_s=0.01, cleanup_timeout_s=0.01)
        for _ in range(2):
            await self.assert_code("deadline_exceeded", client)
        self.assertEqual((len(self.requests), client.pending_count), (2, 2))
        await self.assert_code("capacity", client)
        with self.assertRaisesRegex(m.RoomResultError, "cleanup_incomplete"):
            await client.close()
        self.assertEqual(client.pending_count, 2)
        self.release.set()
        await self.until(lambda: client.pending_count == 0)
        await client.close()
        self.assertEqual(len(self.requests), 2)

    async def test_cancelled_waiter_keeps_real_response_socket_until_settled(self):
        self.release = asyncio.Event()
        task = asyncio.create_task(self.client.read(delivery_id=self.delivery))
        self.waiters.append(task)
        await self.until(lambda: len(self.requests) == 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.client.pending_count, 1)
        self.release.set()
        await self.until(lambda: self.client.pending_count == 0)
        self.assertEqual(self.client.metrics()["cancelled_waiters"], 1)
        self.assertIsNotNone(await self.client.read(delivery_id=self.delivery))
        self.assertEqual(len(self.requests), 2)

    async def test_late_real_connect_after_cancel_is_adopted_closed_without_sending(self):
        original = m.asyncio.open_connection
        entered, release = asyncio.Event(), asyncio.Event()
        self.releases.append(release)

        async def late(*args, **kwargs):
            value = await original(*args, **kwargs)
            entered.set()
            await release.wait()
            return value

        with patch.object(m.asyncio, "open_connection", late):
            task = asyncio.create_task(self.client.read(delivery_id=self.delivery))
            self.waiters.append(task)
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(self.client.pending_count, 1)
            release.set()
            await self.until(lambda: self.client.pending_count == 0)
        self.assertEqual((self.connections, len(self.requests)), (1, 0))
        self.assertIsNotNone(await self.client.read(delivery_id=self.delivery))

    async def test_close_during_late_connect_retains_owner_and_prevents_request(self):
        original = m.asyncio.open_connection
        entered, release = asyncio.Event(), asyncio.Event()
        self.releases.append(release)
        client = self.opened(cleanup_timeout_s=0.01)

        async def late(*args, **kwargs):
            value = await original(*args, **kwargs)
            entered.set()
            await release.wait()
            return value

        with patch.object(m.asyncio, "open_connection", late):
            task = asyncio.create_task(client.read(delivery_id=self.delivery))
            self.waiters.append(task)
            await entered.wait()
            with self.assertRaisesRegex(m.RoomResultError, "cleanup_incomplete"):
                await client.close()
            self.assertEqual(client.pending_count, 1)
            release.set()
            with self.assertRaisesRegex(m.RoomResultError, "closed"):
                await task
            await client.close()
        self.assertEqual((client.pending_count, len(self.requests)), (0, 0))

    async def test_fixed_network_deadline_closes_actual_transport_without_retry(self):
        self.assertEqual(m.NETWORK_SECONDS, 5)
        self.release = asyncio.Event()
        with patch.object(m, "NETWORK_SECONDS", 0.02):
            await self.assert_code("unavailable")
        self.assertEqual((self.client.pending_count, len(self.requests)), (0, 1))
        self.release.set()

    async def test_task_allocation_failures_close_coroutines_and_allow_fresh_read(self):
        for error, code in [
            (RuntimeError(PRIVATE), "unavailable"),
            (asyncio.CancelledError(), None),
        ]:
            actions = []

            def fail(action, actions=actions, error=error):
                actions.append(action)
                raise error

            with warnings.catch_warnings(record=True) as observed:
                warnings.simplefilter("always")
                with patch.object(m.asyncio, "create_task", side_effect=fail):
                    if code is None:
                        with self.assertRaises(asyncio.CancelledError):
                            await self.client.read(delivery_id=self.delivery)
                    else:
                        await self.assert_code(code)
                gc.collect()
            self.assertIsNone(actions[0].cr_frame)
            self.assertFalse([w for w in observed if issubclass(w.category, RuntimeWarning)])
            self.assertEqual(self.client.pending_count, 0)
        self.assertIsNotNone(await self.client.read(delivery_id=self.delivery))

    async def test_close_task_allocation_failure_preserves_actual_call_then_retry(self):
        self.release = asyncio.Event()
        client = self.opened(timeout_s=0.01)
        await self.assert_code("deadline_exceeded", client)

        def fail(action):
            raise RuntimeError(PRIVATE)

        with (
            patch.object(m.asyncio, "create_task", side_effect=fail),
            self.assertRaisesRegex(m.RoomResultError, "cleanup_incomplete"),
        ):
            await client.close()
        self.assertEqual(client.pending_count, 1)
        self.release.set()
        await self.until(lambda: client.pending_count == 0)
        await client.close()

    async def test_queued_cancel_denies_new_socket_and_cleanup_still_allowed(self):
        async def cancelled():
            asyncio.current_task().cancel()
            return await self.client.read(delivery_id=self.delivery)

        task = asyncio.create_task(cancelled())
        self.waiters.append(task)
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.connections, 0)
        self.assertIsNotNone(await self.client.read(delivery_id=self.delivery))

    async def test_wrong_loop_fails_before_socket_or_owner_mutation(self):
        await self.client.read(delivery_id=self.delivery)
        before = dict(self.client.metrics())

        async def wrong():
            try:
                await self.client.read(delivery_id=self.delivery)
            except m.RoomResultError as error:
                return error.code

        self.assertEqual(await asyncio.to_thread(lambda: asyncio.run(wrong())), "invalid_input")
        self.assertEqual(dict(self.client.metrics()), before)
        self.assertEqual(self.connections, 1)

    async def test_hostile_dependency_error_getter_and_telemetry_are_safe(self):
        calls = []

        class Hostile(m.RoomResultError):
            @property
            def code(self):
                calls.append(1)
                raise RuntimeError(PRIVATE)

        error = Hostile.__new__(Hostile)
        RuntimeError.__init__(error, PRIVATE)

        async def denied(*args, **kwargs):
            raise error

        with patch.object(m.asyncio, "open_connection", denied):
            await self.assert_code("unavailable")
        self.assertEqual(calls, [])
        with patch.object(m.LOGGER, "info", side_effect=RuntimeError(PRIVATE)):
            self.assertIsNotNone(await self.client.read(delivery_id=self.delivery))
        self.assertEqual(self.client.metrics()["telemetry_failed"], 1)

    async def test_eager_reentrant_reads_reserve_two_actual_owners_before_connect(self):
        original = m.asyncio.open_connection
        calls = []
        peak = []

        async def connect(*args, **kwargs):
            ordinal = len(calls)
            calls.append(ordinal)
            peak.append(self.client.pending_count)
            if ordinal == 0:
                self.assertIsNotNone(await self.client.read(delivery_id=self.delivery))
            else:
                with self.assertRaisesRegex(m.RoomResultError, "capacity"):
                    await self.client.read(delivery_id=self.delivery)
            return await original(*args, **kwargs)

        loop = asyncio.get_running_loop()
        prior = loop.get_task_factory()
        loop.set_task_factory(asyncio.eager_task_factory)
        try:
            with patch.object(m.asyncio, "open_connection", connect):
                self.assertIsNotNone(await self.client.read(delivery_id=self.delivery))
        finally:
            loop.set_task_factory(prior)
        self.assertEqual(
            (calls, max(peak), len(self.requests), self.client.pending_count), ([0, 1], 2, 2, 0)
        )

    async def test_eager_read_and_close_reentry_waits_call_publication(self):
        original = m.asyncio.open_connection
        entered, release = asyncio.Event(), asyncio.Event()
        self.releases.append(release)
        closes = []
        client = self.opened(cleanup_timeout_s=0.1)

        async def connect(*args, **kwargs):
            closes.append(asyncio.create_task(client.close()))
            entered.set()
            await release.wait()
            return await original(*args, **kwargs)

        loop = asyncio.get_running_loop()
        prior = loop.get_task_factory()
        loop.set_task_factory(asyncio.eager_task_factory)
        task = None
        try:
            with patch.object(m.asyncio, "open_connection", connect):
                task = asyncio.create_task(client.read(delivery_id=self.delivery))
                self.waiters.append(task)
                await entered.wait()
                self.assertFalse(closes[0].done())
                self.assertEqual(client.pending_count, 1)
                release.set()
                with self.assertRaisesRegex(m.RoomResultError, "closed"):
                    await task
                await closes[0]
        finally:
            release.set()
            loop.set_task_factory(prior)
            await asyncio.gather(*closes, return_exceptions=True)
        self.assertEqual((client.pending_count, len(self.requests)), (0, 0))


class Contracts(unittest.TestCase):
    def test_constructor_is_closed_typed_immutable_private_and_bounded(self):
        endpoint = m.RoomResultEndpoint()
        binding = m.RoomResultBinding(str(uuid4()), "1")
        credential = m.RoomViewCredential(TOKEN)
        self.assertEqual((endpoint.host, endpoint.port), ("127.0.0.1", 11029))
        self.assertNotIn(TOKEN, repr(credential))
        with self.assertRaises(FrozenInstanceError):
            binding.generation = "2"
        for values in [
            {"host": "localhost"},
            {"host": "0.0.0.0"},
            {"port": 0},
            {"port": True},
            {"port": 65536},
        ]:
            with self.assertRaisesRegex(m.RoomResultError, "invalid_input"):
                m.RoomResultEndpoint(**values)
        for generation in ["0", "01", "1e0", "1000001", True, "1\n"]:
            with self.assertRaisesRegex(m.RoomResultError, "invalid_input"):
                m.RoomResultBinding(binding.node_epoch, generation)
        for token in ["v" * 42, TOKEN + "\n", "+" * 43, PRIVATE]:
            with self.assertRaisesRegex(m.RoomResultError, "invalid_input"):
                m.RoomViewCredential(token)
        for value in [True, 10**1000, float("inf"), float("nan"), 0, 6]:
            for key in ["timeout_s", "cleanup_timeout_s"]:
                with self.assertRaisesRegex(m.RoomResultError, "invalid_input"):
                    m.RoomResultHttpClient(endpoint, binding, credential, **{key: value})
        with self.assertRaisesRegex(m.RoomResultError, "invalid_input"):
            m.RoomResultBinding(binding.node_epoch.upper(), "1")

    def test_import_is_inert_without_environment_or_provider_reads(self):
        code = "import sys;from unittest.mock import patch;\nwith patch('socket.socket',side_effect=AssertionError('socket')),patch('subprocess.Popen',side_effect=AssertionError('process')),patch('asyncio.create_task',side_effect=AssertionError('task')):import services.channel_policy_demo.room_result_client\nassert 'livekit.agents' not in sys.modules"
        result = subprocess.run(
            [sys.executable, "-B", "-c", code],
            cwd=ROOT,
            capture_output=True,
            timeout=5,
            check=False,
        )
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))
