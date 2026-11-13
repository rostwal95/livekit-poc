"""Actual loopback framing, scope/CAS and retained-resource bridge tests; no SQL."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import logging
import sys
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid4, uuid5

from continuity_lab.api import IdempotencyConflict
from continuity_lab.case_control_api import (
    ActionIntent,
    BookingChange,
    CaseControlIdentity,
    CaseSnapshot,
)
from continuity_lab.postgres_api import QuoteExpired, QuoteSnapshot, StaleRevision

SPEC = importlib.util.spec_from_file_location(
    "p2_case_bridge_test_module",
    Path(__file__).resolve().parents[1] / "local-setup/scripts/p2_case_bridge.py",
)
assert SPEC is not None and SPEC.loader is not None
bridge_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bridge_module
SPEC.loader.exec_module(bridge_module)
TOKEN = "a" * 43
SENTINEL = "SENTINEL_PRIVATE_BODY_TOKEN"


def request(day="2030-12-11"):
    return {
        "schemaVersion": 1,
        "kind": "booking_investigation",
        "bookingReference": "DEMO-BK-001",
        "newCheckIn": day,
        "investigationConsent": True,
    }


def body(*, revising=False):
    result = {
        "schemaVersion": 1,
        "scope": {"tenantId": "tenant_demo", "accountId": "account_demo"},
        "caseId": "case_demo",
    }
    if revising:
        result.update(expectedRevision="0", request=request())
    return result


class FakeClient:
    def __init__(self):
        self.identity = CaseControlIdentity("actor_demo", "scope_demo", "case_demo")
        self.value = CaseSnapshot(
            str(uuid4()),
            "scope_demo",
            "actor_demo",
            0,
            BookingChange("DEMO-BK-001", date(2030, 12, 10), True),
            None,
            False,
            None,
            "2030-01-01T00:00:00+00:00",
            "2030-01-01T00:00:00+00:00",
            str(uuid4()),
        )
        self.reads = self.calls = self.changes = self.closed = 0
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.target = 1
        self.failure = None
        self.invalid_return = False
        self.mutate_input = False
        self.closed_event = asyncio.Event()
        self.lock = asyncio.Lock()

    async def case(self, *, task_id):
        assert not self.closed
        self.reads += 1
        assert task_id == self.value.task_id
        if self.failure:
            raise self.failure
        return replace(self.value, actor_id="foreign") if self.invalid_return else self.value

    async def revise(self, *, task_id, expected_revision, request):
        assert not self.closed
        self.calls += 1
        if self.calls >= self.target:
            self.entered.set()
        await self.release.wait()
        async with self.lock:
            assert task_id == self.value.task_id
            if self.failure:
                raise self.failure
            if expected_revision != self.value.revision:
                raise StaleRevision("private dependency text " + SENTINEL)
            if self.mutate_input:
                object.__setattr__(request, "booking_reference", "OTHER")
            if self.value.request != request:
                self.value = replace(self.value, revision=self.value.revision + 1, request=request)
                self.changes += 1
            return replace(self.value, actor_id="foreign") if self.invalid_return else self.value

    async def close(self):
        self.closed += 1
        self.closed_event.set()


def binding(client):
    return bridge_module.CaseBinding(
        "tenant_demo",
        "account_demo",
        "case_demo",
        client.value.task_id,
        client.value.case_id,
        TOKEN,
        client,
    )


async def exchange(port, data, *, revising=False, confirming=False, token=TOKEN, raw=None):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        if raw is None:
            payload = json.dumps(data, separators=(",", ":")).encode()
            path = (
                "/v1/case/confirm"
                if confirming
                else "/v1/case/revise"
                if revising
                else "/v1/case/inspect"
            )
            raw = (
                f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
                f"Authorization: Bearer {token}\r\nContent-Type: application/json\r\n"
                f"Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n"
            ).encode() + payload
        writer.write(raw)
        await writer.drain()
        raw_result = await asyncio.wait_for(reader.read(12289), 1)
        if not raw_result:
            return None
        head, payload = raw_result.split(b"\r\n\r\n", 1)
        assert head.startswith(b"HTTP/1.1 200 ")
        assert len(head) <= 4096 and len(payload) <= 8192
        assert b"Content-Type: application/json" in head and b"Connection: close" in head
        length = next(line for line in head.split(b"\r\n") if line.startswith(b"Content-Length: "))
        assert int(length.split(b": ")[1]) == len(payload)
        assert not payload.endswith(b"\n")
        return json.loads(payload)
    finally:
        writer.close()
        await writer.wait_closed()


class CaseBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = FakeClient()
        self.bridge = await bridge_module.start_case_bridge((binding(self.client),))

    async def asyncTearDown(self):
        self.client.release.set()
        await self.bridge.close()
        self.assertEqual(self.bridge.pending_count, 0)
        self.assertEqual(self.bridge.metrics()["sockets"], 0)

    async def test_actual_socket_read_and_one_winning_expected_revision(self):
        observed = await exchange(self.bridge.port, body())
        self.assertEqual(observed["case"]["revision"], "0")
        first, second = await asyncio.gather(
            *(exchange(self.bridge.port, body(revising=True), revising=True) for _ in range(2))
        )
        self.assertEqual(sorted(item["status"] for item in (first, second)), ["known", "rejected"])
        self.assertEqual(
            next(item for item in (first, second) if item["status"] == "rejected")["code"],
            "RevisionConflict",
        )
        self.assertEqual(self.client.changes, 1)
        fresh = await exchange(self.bridge.port, body())
        self.assertEqual(fresh["case"]["revision"], "1")
        self.assertEqual(fresh["case"]["request"], request())
        self.assertFalse(fresh["case"]["committed"])

    async def test_same_current_request_is_known_unchanged_and_int64_revision_supported(self):
        self.client.value = replace(self.client.value, revision=bridge_module.MAX_REVISION)
        data = body(revising=True)
        data.update(expectedRevision=str(bridge_module.MAX_REVISION), request=request("2030-12-10"))
        result = await exchange(self.bridge.port, data, revising=True)
        self.assertEqual(result["status"], "known")
        self.assertEqual(result["case"]["revision"], str(bridge_module.MAX_REVISION))
        self.assertEqual(self.client.changes, 0)

    async def test_scope_token_target_and_changed_binding_rejected_before_call(self):
        variants = [body(revising=True) for _ in range(3)]
        variants[0]["scope"]["tenantId"] = "foreign"
        variants[1]["scope"]["accountId"] = "foreign"
        variants[2]["caseId"] = "foreign"
        for data in variants:
            self.assertEqual(
                (await exchange(self.bridge.port, data, revising=True))["code"], "AccessDenied"
            )
        self.assertEqual(
            (await exchange(self.bridge.port, body(revising=True), revising=True, token="b" * 43))[
                "code"
            ],
            "AccessDenied",
        )
        self.client.identity = replace(self.client.identity, actor_id="changed")
        self.assertEqual(
            (await exchange(self.bridge.port, body(revising=True), revising=True))["code"],
            "AccessDenied",
        )
        self.assertEqual(self.client.calls, 0)

    async def test_strict_command_date_identifier_number_and_extra_fields(self):
        variants = []
        for revision in (True, 0, "00", "-1", str(bridge_module.MAX_REVISION + 1)):
            data = body(revising=True)
            data["expectedRevision"] = revision
            variants.append(data)
        for key, value in (
            ("newCheckIn", "2030-02-30"),
            ("newCheckIn", "0000-01-01"),
            ("bookingReference", "lower"),
            ("investigationConsent", False),
        ):
            data = body(revising=True)
            data["request"][key] = value
            variants.append(data)
        extra = body(revising=True)
        extra["actor"] = SENTINEL
        variants.append(extra)
        for data in variants:
            result = await exchange(self.bridge.port, data, revising=True)
            self.assertEqual(result["code"], "InvalidCommand")
            self.assertNotIn(SENTINEL, json.dumps(result))
        self.assertEqual(self.client.calls, 0)

    async def test_duplicate_json_headers_transfer_encoding_and_size_fail_before_call(self):
        payload = json.dumps(body()).encode()
        base = (
            f"POST /v1/case/inspect HTTP/1.1\r\nHost: 127.0.0.1:{self.bridge.port}\r\n"
            f"Authorization: Bearer {TOKEN}\r\nContent-Type: application/json\r\n"
        )
        raw_cases = [
            base.encode()
            + f"Content-Length: {len(payload)}\r\nContent-Length: {len(payload)}\r\n\r\n".encode()
            + payload,
            base.encode() + b"Transfer-Encoding: chunked\r\n\r\n0\r\n\r\n",
            base.encode() + b"Content-Length: 8193\r\n\r\n",
            base.encode() + b"X-Large: " + b"x" * 4096 + b"\r\nContent-Length: 0\r\n\r\n",
        ]
        duplicated = b'{"schemaVersion":1,"schemaVersion":1,"scope":{},"caseId":"case_demo"}'
        raw_cases.append(
            base.encode() + f"Content-Length: {len(duplicated)}\r\n\r\n".encode() + duplicated
        )
        for raw in raw_cases:
            result = await exchange(self.bridge.port, None, raw=raw)
            self.assertEqual(result["code"], "InvalidCommand")
        self.assertEqual(self.client.reads + self.client.calls, 0)

    async def test_postcommit_ack_loss_never_implies_original_command_won_on_retry(self):
        async def drop():
            raise bridge_module.DropAcknowledgement()

        await self.bridge.close()
        self.client = FakeClient()
        self.bridge = await bridge_module.start_case_bridge(
            (binding(self.client),), harness_after_revision=drop
        )
        self.assertIsNone(await exchange(self.bridge.port, body(revising=True), revising=True))
        self.assertEqual(self.client.changes, 1)
        retry = await exchange(self.bridge.port, body(revising=True), revising=True)
        self.assertEqual(retry["code"], "RevisionConflict")
        current = await exchange(self.bridge.port, body())
        self.assertEqual(current["case"]["revision"], "1")
        self.assertEqual(self.client.changes, 1)
        self.assertEqual(self.bridge.metrics()["unknown"], 1)

    async def test_possible_write_malformed_result_and_dependency_error_stay_unknown(self):
        self.client.invalid_return = True
        response = await exchange(self.bridge.port, body(revising=True), revising=True)
        self.assertEqual(response["status"], "unknown")
        self.assertEqual(self.client.changes, 1)
        self.client.invalid_return = False
        self.client.failure = RuntimeError(SENTINEL)
        data = body(revising=True)
        data["expectedRevision"] = "1"
        response = await exchange(self.bridge.port, data, revising=True)
        self.assertEqual(response["code"], "OutcomeUnknown")
        self.assertNotIn(SENTINEL, json.dumps(response))
        response = await exchange(self.bridge.port, body())
        self.assertEqual(response["code"], "Unavailable")

    async def test_timeout_retains_four_actual_operations_and_close_ownership(self):
        await self.bridge.close()
        self.client = FakeClient()
        self.bridge = await bridge_module.start_case_bridge(
            (binding(self.client),), request_timeout_ms=80, close_timeout_ms=20
        )
        self.client.target = 4
        self.client.release.clear()
        requests = [
            asyncio.create_task(exchange(self.bridge.port, body(revising=True), revising=True))
            for _ in range(4)
        ]
        await asyncio.wait_for(self.client.entered.wait(), 1)
        results = await asyncio.gather(*requests)
        self.assertTrue(all(item["code"] == "OutcomeUnknown" for item in results))
        self.assertEqual(self.bridge.pending_count, 4)
        rejected = await exchange(self.bridge.port, body(revising=True), revising=True)
        self.assertEqual(rejected["code"], "Overloaded")
        self.assertEqual(self.client.calls, 4)
        with self.assertRaisesRegex(bridge_module.BridgeError, "^CleanupIncomplete$"):
            await self.bridge.close()
        self.assertEqual(self.bridge.pending_count, 4)
        self.client.release.set()
        await self.bridge.close()
        self.assertEqual(self.bridge.pending_count, 0)
        self.assertEqual(self.client.changes, 1)

    async def test_disconnect_and_throwing_logger_preserve_committed_truth(self):
        entered = asyncio.Event()
        release = asyncio.Event()

        async def hold():
            entered.set()
            await release.wait()

        await self.bridge.close()
        self.client = FakeClient()
        self.bridge = await bridge_module.start_case_bridge(
            (binding(self.client),), harness_after_revision=hold
        )
        call = asyncio.create_task(exchange(self.bridge.port, body(revising=True), revising=True))
        await asyncio.wait_for(entered.wait(), 1)
        call.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await call
        self.assertEqual(self.client.changes, 1)
        with patch.object(bridge_module.LOGGER, "info", side_effect=RuntimeError(SENTINEL)):
            release.set()
            fresh = await exchange(self.bridge.port, body())
            self.assertEqual(fresh["case"]["revision"], "1")
        self.assertGreaterEqual(self.bridge.metrics()["telemetry_failed"], 1)
        self.assertEqual(self.client.changes, 1)

    async def test_binding_and_expected_request_are_snapshotted_before_await(self):
        await self.bridge.close()
        self.client = FakeClient()
        original = binding(self.client)
        self.bridge = await bridge_module.start_case_bridge((original,))
        object.__setattr__(original, "tenant_id", "foreign")
        observed = await exchange(self.bridge.port, body())
        self.assertEqual(observed["case"]["scope"]["tenantId"], "tenant_demo")
        self.client.mutate_input = True
        changed = await exchange(self.bridge.port, body(revising=True), revising=True)
        self.assertEqual(changed["code"], "OutcomeUnknown")
        self.assertEqual(self.client.changes, 1)

    async def test_cancelled_start_retains_and_closes_late_listener(self):
        entered, release = asyncio.Event(), asyncio.Event()
        client = FakeClient()
        start_server = asyncio.start_server
        ports = []

        async def delayed(*args, **kwargs):
            entered.set()
            await release.wait()
            server = await start_server(*args, **kwargs)
            ports.append(server.sockets[0].getsockname()[1])
            return server

        with patch.object(bridge_module.asyncio, "start_server", side_effect=delayed):
            task = asyncio.create_task(
                bridge_module.start_case_bridge((binding(client),), close_timeout_ms=20)
            )
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(client.closed, 0)
            release.set()
            await asyncio.wait_for(client.closed_event.wait(), 1)
        self.assertEqual(client.closed, 1)
        with self.assertRaises(OSError):
            await asyncio.open_connection("127.0.0.1", ports[0])

    async def test_socket_pressure_stays_finite_and_recovers(self):
        outcomes = await asyncio.gather(
            *(asyncio.open_connection("127.0.0.1", self.bridge.port) for _ in range(24)),
            return_exceptions=True,
        )
        connections = [value for value in outcomes if not isinstance(value, BaseException)]
        self.assertTrue(connections)
        try:
            self.assertLessEqual(self.bridge.metrics()["sockets"], 16)
            self.assertLessEqual(self.bridge.pending_count, 4)
        finally:
            for _, writer in connections:
                writer.close()
            await asyncio.gather(
                *(writer.wait_closed() for _, writer in connections), return_exceptions=True
            )
        await self.bridge.close()
        self.client = FakeClient()
        self.bridge = await bridge_module.start_case_bridge((binding(self.client),))
        result = await exchange(self.bridge.port, body())
        self.assertEqual(result["status"], "known")

    async def test_late_actual_socket_close_remains_owned_until_observed(self):
        await self.bridge.close()
        self.client = FakeClient()
        entered, release = asyncio.Event(), asyncio.Event()

        class LateWriter:
            def __init__(inner, writer):
                inner.writer = writer
                inner.transport = writer.transport

            def write(inner, data):
                return inner.writer.write(data)

            async def drain(inner):
                await inner.writer.drain()

            def close(inner):
                entered.set()

            async def wait_closed(inner):
                await release.wait()
                inner.writer.close()
                await inner.writer.wait_closed()

        class LateBridge(bridge_module.CaseBridge):
            def _connected(inner, reader, writer):
                super()._connected(reader, LateWriter(writer))

        self.bridge = LateBridge((binding(self.client),), close_timeout_ms=20)
        await self.bridge.start()
        reader, writer = await asyncio.open_connection("127.0.0.1", self.bridge.port)
        try:
            payload = json.dumps(body()).encode()
            writer.write(
                (
                    f"POST /v1/case/inspect HTTP/1.1\r\nHost: 127.0.0.1:{self.bridge.port}\r\nAuthorization: Bearer {TOKEN}\r\nContent-Type: application/json\r\nContent-Length: {len(payload)}\r\n\r\n"
                ).encode()
                + payload
            )
            await writer.drain()
            head = await reader.readuntil(b"\r\n\r\n")
            length = int(
                next(
                    line.split(b": ")[1]
                    for line in head.split(b"\r\n")
                    if line.startswith(b"Content-Length:")
                )
            )
            self.assertEqual(json.loads(await reader.readexactly(length))["status"], "known")
            await asyncio.wait_for(entered.wait(), 1)
            with self.assertRaisesRegex(bridge_module.BridgeError, "^CleanupIncomplete$"):
                await self.bridge.close()
            self.assertEqual(self.bridge.metrics()["sockets"], 1)
            self.assertEqual(self.client.closed, 0)
            release.set()
            await self.bridge.close()
            self.assertEqual(await asyncio.wait_for(reader.read(), 1), b"")
            self.assertEqual(self.bridge.metrics()["sockets"], 0)
            self.assertEqual(self.client.closed, 1)
        finally:
            release.set()
            writer.close()
            await writer.wait_closed()

    async def test_import_configuration_and_literal_loopback_boundaries(self):
        self.assertEqual(self.bridge._server.sockets[0].getsockname()[0], "127.0.0.1")
        with self.assertRaises(bridge_module.BridgeError):
            bridge_module.CaseBridge(())
        with self.assertRaises(bridge_module.BridgeError):
            bridge_module.CaseBridge((binding(self.client), binding(self.client)))
        with self.assertRaises(bridge_module.BridgeError):
            bridge_module.CaseBridge((binding(self.client),), request_timeout_ms=5001)
        self.assertNotIn(TOKEN, repr(binding(self.client)))
        self.assertEqual(len(logging.getLogger(bridge_module.__name__).handlers), 1)


class ConfirmingClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.confirmations = {}
        self.confirm_calls = 0
        self.confirm_entered = asyncio.Event()
        self.confirm_release = asyncio.Event()
        self.confirm_release.set()
        self.quote = QuoteSnapshot(
            str(uuid5(NAMESPACE_URL, "synthetic-public-quote:" + self.value.task_id)),
            self.value.task_id,
            9_007_199_254_740_993,
            "DEMO-BK-001",
            date(2030, 12, 10),
            2500,
            "USD",
            "2030-01-01T00:00:00+00:00",
            self.value.case_id,
            9_007_199_254_740_994,
            str(uuid4()),
        )
        self.seen_quote = None

    async def commit_confirmation(self, *, task_id, confirmation, command_id):
        assert not self.closed and task_id == self.value.task_id
        self.confirm_calls += 1
        self.confirm_entered.set()
        await self.confirm_release.wait()
        self.seen_quote = confirmation.quote
        old = self.confirmations.get(command_id)
        if old is not None:
            if old.quote != confirmation.quote:
                raise IdempotencyConflict("private conflict " + SENTINEL)
            return old
        if self.failure:
            raise self.failure
        value = ActionIntent(
            str(uuid4()),
            task_id,
            self.identity.scope_id,
            self.identity.actor_id,
            confirmation.quote.revision,
            confirmation.quote,
            str(uuid4()),
            str(uuid4()),
            str(uuid4()),
            "2030-01-01T00:00:00+00:00",
        )
        self.confirmations[command_id] = value
        return replace(value, actor_id="foreign") if self.invalid_return else value


def confirmation_body(client):
    raw = json.dumps(
        client.quote.payload(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return dict(
        body(),
        commandId=str(uuid4()),
        expectedRevision=str(client.quote.revision),
        quoteId=client.quote.quote_id,
        quoteDigest=hashlib.sha256(raw.encode()).hexdigest(),
        quoteJson=raw,
        explicit=True,
    )


class CaseConfirmationBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = ConfirmingClient()
        self.bridge = await bridge_module.start_case_bridge(
            (replace(binding(self.client), allow_confirmation=True),)
        )

    async def asyncTearDown(self):
        self.client.confirm_release.set()
        await self.bridge.close()
        self.assertEqual(self.bridge.pending_count, 0)
        self.assertEqual(self.bridge.metrics()["sockets"], 0)

    async def test_exact_public_confirmation_preserves_bigints_and_original_command_replay(self):
        data = confirmation_body(self.client)
        first = await exchange(self.bridge.port, data, confirming=True)
        self.assertEqual(first["status"], "known")
        self.assertEqual(first["confirmation"]["revision"], "9007199254740993")
        self.assertEqual(self.client.seen_quote.expected_supplier_revision, 9_007_199_254_740_994)
        self.assertEqual(first, await exchange(self.bridge.port, data, confirming=True))
        self.assertEqual(len(self.client.confirmations), 1)
        self.assertEqual(self.client.reads, 0)
        self.assertEqual(self.client.calls, 0)

    async def test_confirmation_is_explicit_opt_in_capability(self):
        await self.bridge.close()
        self.client = ConfirmingClient()
        self.bridge = await bridge_module.start_case_bridge((binding(self.client),))
        result = await exchange(self.bridge.port, confirmation_body(self.client), confirming=True)
        self.assertEqual(result["code"], "AccessDenied")
        self.assertEqual(self.client.confirm_calls, 0)

    async def test_strict_canonical_quote_and_metadata_reject_before_public_call(self):
        for key, value in (
            ("explicit", False),
            ("explicit", 1),
            ("quoteDigest", "0" * 64),
            ("expectedRevision", "9007199254740994"),
            ("quoteId", str(uuid4())),
            ("commandId", "operation-not-uuid"),
            ("extra", True),
        ):
            data = confirmation_body(self.client)
            data[key] = value
            self.assertEqual(
                (await exchange(self.bridge.port, data, confirming=True))["code"], "InvalidCommand"
            )
        for change in ("whitespace", "duplicate", "foreign_task", "legacy"):
            data = confirmation_body(self.client)
            if change == "whitespace":
                data["quoteJson"] += " "
            elif change == "duplicate":
                data["quoteJson"] = data["quoteJson"][:-1] + ',"revision":9007199254740993}'
            else:
                quote = self.client.quote
                if change == "foreign_task":
                    quote = replace(quote, task_id=str(uuid4()))
                else:
                    quote = replace(
                        quote, case_id=None, supplier_id=None, expected_supplier_revision=None
                    )
                data["quoteJson"] = json.dumps(
                    quote.payload(), sort_keys=True, separators=(",", ":")
                )
            data["quoteDigest"] = hashlib.sha256(data["quoteJson"].encode()).hexdigest()
            self.assertEqual(
                (await exchange(self.bridge.port, data, confirming=True))["code"], "InvalidCommand"
            )
        self.assertEqual(self.client.confirm_calls, 0)

    async def test_public_conflict_expiry_and_failure_mapping_are_fixed(self):
        for failure, code in (
            (IdempotencyConflict(SENTINEL), "IdentityConflict"),
            (QuoteExpired(SENTINEL), "RevisionConflict"),
            (StaleRevision(SENTINEL), "RevisionConflict"),
            (RuntimeError(SENTINEL), "OutcomeUnknown"),
        ):
            self.client.failure = failure
            result = await exchange(
                self.bridge.port, confirmation_body(self.client), confirming=True
            )
            self.assertEqual(result["code"], code)
            self.assertNotIn(SENTINEL, json.dumps(result))

    async def test_post_commit_lost_ack_replays_known_receipt_without_new_intent(self):
        await self.bridge.close()
        self.client = ConfirmingClient()

        async def drop():
            raise bridge_module.DropAcknowledgement()

        self.bridge = await bridge_module.start_case_bridge(
            (replace(binding(self.client), allow_confirmation=True),),
            harness_after_confirmation=drop,
        )
        data = confirmation_body(self.client)
        self.assertIsNone(await exchange(self.bridge.port, data, confirming=True))
        original = self.client.confirmations[data["commandId"]]
        # Reopen application composition with the same retained dependency state.
        await self.bridge.close()
        self.client.closed = 0
        self.bridge = await bridge_module.start_case_bridge(
            (replace(binding(self.client), allow_confirmation=True),)
        )
        known = await exchange(self.bridge.port, data, confirming=True)
        self.assertEqual(known["confirmation"]["intentId"], original.intent_id)
        self.assertEqual(len(self.client.confirmations), 1)

    async def test_mismatched_public_result_remains_unknown_after_possible_commit(self):
        self.client.invalid_return = True
        result = await exchange(self.bridge.port, confirmation_body(self.client), confirming=True)
        self.assertEqual(
            result, {"schemaVersion": 1, "status": "unknown", "code": "OutcomeUnknown"}
        )
        self.assertEqual(len(self.client.confirmations), 1)

    async def test_confirmation_capacity_and_close_retain_actual_calls_after_timeout(self):
        await self.bridge.close()
        self.client = ConfirmingClient()
        self.client.confirm_release.clear()
        self.bridge = await bridge_module.start_case_bridge(
            (replace(binding(self.client), allow_confirmation=True),),
            request_timeout_ms=50,
            close_timeout_ms=50,
        )
        calls = [
            asyncio.create_task(
                exchange(self.bridge.port, confirmation_body(self.client), confirming=True)
            )
            for _ in range(4)
        ]
        await self.client.confirm_entered.wait()
        for _ in range(100):
            if self.client.confirm_calls == 4:
                break
            await asyncio.sleep(0.001)
        self.assertEqual(self.client.confirm_calls, 4)
        self.assertEqual(
            (await exchange(self.bridge.port, confirmation_body(self.client), confirming=True))[
                "code"
            ],
            "Overloaded",
        )
        await asyncio.gather(*calls)
        with self.assertRaises(bridge_module.BridgeError) as caught:
            await self.bridge.close()
        self.assertEqual(caught.exception.code, "CleanupIncomplete")
        self.assertEqual(self.bridge.pending_count, 4)
        self.assertEqual(self.client.closed, 0)
        self.client.confirm_release.set()
        await self.bridge.close()
        self.assertEqual(self.bridge.pending_count, 0)
