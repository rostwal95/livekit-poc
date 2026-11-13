"""Actual loopback read-only bridge validation and retained I/O tests; no SQL."""

from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid4, uuid5

from continuity_lab.authorization import TokenDirectory
from continuity_lab.case_control_api import CaseControlIdentity
from continuity_lab.conversation_service import AsyncConversationService, ConversationService
from continuity_lab.postgres_api import AuthenticatedActor, BearerToken, CaseProjection

SPEC = importlib.util.spec_from_file_location(
    "p2_current_case_bridge_tests",
    Path(__file__).resolve().parents[1] / "local-setup/scripts/p2_current_case_bridge.py",
)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)
TOKEN = "a" * 43
PRIVATE = "DO_NOT_DISCLOSE_QUOTE_OR_PRIVATE_ERROR"
TASK, CASE, INTENT, EFFECT, EVENT = (
    "trusted-task:original",
    str(uuid4()),
    str(uuid4()),
    str(uuid4()),
    str(uuid4()),
)
SUPPLIER = str(uuid5(NAMESPACE_URL, "synthetic-supplier"))


def projection(*, succeeded=False):
    result = {
        "schema_version": 1,
        "effect_id": EFFECT,
        "intent_id": INTENT,
        "task_id": TASK,
        "case_id": CASE,
        "supplier_id": SUPPLIER,
        "scope_id": "p1_scope",
        "booking_reference": "DEMO-BK-001",
        "previous_check_in": "2030-12-09",
        "new_check_in": "2030-12-10",
        "previous_revision": "0",
        "revision": "1",
        "amount_minor": 1000,
        "currency": "USD",
        "created_at": "2030-01-01T00:00:00+00:00",
    }
    return {
        "schema_version": 1,
        "task_id": TASK,
        "case_id": CASE,
        "case_revision": "2",
        "request": {
            "booking_reference": "DEMO-BK-001",
            "new_check_in": "2030-12-10",
            "confirmed": True,
        },
        "lifecycle": {"state": "completed" if succeeded else "inquiry_complete", "version": "4"},
        "inquiry": {"effect_id": str(uuid4()), "result": {"available": True}},
        "quote": {"confirmation_payload": PRIVATE},
        "events": [{"details": PRIVATE}],
        "confirmation": {
            "state": "committed" if succeeded else "required",
            "intent_id": INTENT if succeeded else None,
            "confirmation_id": str(uuid4()) if succeeded else None,
            "committed_at": "2030-01-01T00:00:00+00:00" if succeeded else None,
        },
        "effect": {
            "state": "succeeded",
            "generation": "1",
            "attempt_no": 1,
            "dispatch_count": 1,
            "result": result,
            "error_code": None,
            "updated_at": "2030-01-01T00:00:00+00:00",
        }
        if succeeded
        else None,
        "outcome": {
            "state": "succeeded",
            "result": copy.deepcopy(result),
            "error_code": None,
            "cancellation": "not_requested",
            "created_at": "2030-01-01T00:00:00+00:00",
            "intent_id": INTENT,
            "effect_id": EFFECT,
            "event_id": EVENT,
        }
        if succeeded
        else None,
        "projection_revision": "b" * 64,
    }


class Reader:
    def __init__(self):
        self.identity = CaseControlIdentity("p1_actor", "p1_scope", "p1_fixture")
        self.value = projection()
        self.calls = self.closed = 0
        self.expected_task = TASK
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.failure = None

    async def get(self, *, task_id, cursor=None, limit=1):
        self.calls += 1
        assert (task_id, cursor, limit) == (self.expected_task, None, 1)
        self.entered.set()
        await self.release.wait()
        if self.failure:
            raise self.failure
        return CaseProjection.create(self.value)

    async def close(self):
        self.closed += 1


def binding(reader):
    return module.CurrentCaseBinding(
        "tenant_demo", "account_demo", "case_demo", "conversation_demo", TASK, CASE, TOKEN, reader
    )


def body():
    return {
        "schemaVersion": 1,
        "scope": {"tenantId": "tenant_demo", "accountId": "account_demo"},
        "caseId": "case_demo",
        "conversationId": "conversation_demo",
    }


async def exchange(port, data=None, *, token=TOKEN, raw=None):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        if raw is None:
            encoded = json.dumps(body() if data is None else data, separators=(",", ":")).encode()
            raw = (
                f"POST /v1/current-case/inspect HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nAuthorization: Bearer {token}\r\nContent-Type: application/json\r\nContent-Length: {len(encoded)}\r\nConnection: close\r\n\r\n"
            ).encode() + encoded
        writer.write(raw)
        await writer.drain()
        answer = await asyncio.wait_for(reader.read(12289), 1)
        if not answer:
            return None
        header, payload = answer.split(b"\r\n\r\n", 1)
        assert header.startswith(b"HTTP/1.1 200 ") and len(header) <= 4096 and len(payload) <= 8192
        assert b"Content-Type: application/json" in header and b"Connection: close" in header
        length = next(
            line for line in header.split(b"\r\n") if line.startswith(b"Content-Length: ")
        )
        assert int(length.split(b": ")[1]) == len(payload) and not payload.endswith(b"\n")
        return json.loads(payload)
    finally:
        writer.close()
        await writer.wait_closed()


class CurrentCaseBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.reader = Reader()
        self.bridge = await module.start_current_case_bridge((binding(self.reader),))

    async def asyncTearDown(self):
        self.reader.release.set()
        await self.bridge.close()
        self.assertEqual(self.bridge.pending_count, 0)
        self.assertEqual(self.bridge.metrics()["sockets"], 0)
        await self.reader.close()

    async def test_known_one_get_allowlist_excludes_all_quote_and_event_controls(self):
        response = await exchange(self.bridge.port)
        self.assertEqual(response["status"], "known")
        case = response["case"]
        self.assertEqual(
            set(case),
            {
                "schemaVersion",
                "source",
                "scope",
                "caseId",
                "conversationId",
                "revision",
                "request",
                "workflow",
                "intent",
                "mutation",
                "supplierResult",
                "sourceRevision",
            },
        )
        self.assertEqual(
            case["workflow"], {"taskId": TASK, "state": "inquiry_complete", "version": "4"}
        )
        self.assertEqual(
            case["mutation"],
            {
                "state": "not_observed",
                "outcome": "not_observed",
                "cancellation": "not_observed",
                "effectId": None,
                "outcomeEventId": None,
            },
        )
        self.assertIsNone(case["supplierResult"])
        self.assertNotIn(PRIVATE, json.dumps(response))
        self.assertEqual(self.reader.calls, 1)

    async def test_mutation_truth_and_general_canonical_UUID_are_preserved(self):
        self.reader.value = projection(succeeded=True)
        self.reader.value["case_revision"] = "9223372036854775807"
        result = (await exchange(self.bridge.port))["case"]
        self.assertEqual(result["revision"], "9223372036854775807")
        self.assertEqual(result["intent"], {"state": "committed", "intentId": INTENT})
        self.assertEqual(
            result["supplierResult"],
            {
                "supplierId": SUPPLIER,
                "revision": "1",
                "bookingReference": "DEMO-BK-001",
                "newCheckIn": "2030-12-10",
            },
        )
        self.assertEqual(result["mutation"]["effectId"], EFFECT)
        self.assertEqual(result["mutation"]["outcomeEventId"], EVENT)
        self.assertNotIn(PRIVATE, json.dumps(result))

    async def test_foreign_tuple_token_and_changed_identity_deny_before_get(self):
        for name in ("caseId", "conversationId"):
            changed = body()
            changed[name] = "foreign"
            self.assertEqual((await exchange(self.bridge.port, changed))["code"], "AccessDenied")
        for name in ("tenantId", "accountId"):
            changed = body()
            changed["scope"][name] = "foreign"
            self.assertEqual((await exchange(self.bridge.port, changed))["code"], "AccessDenied")
        self.assertEqual((await exchange(self.bridge.port, token="c" * 43))["code"], "AccessDenied")
        self.reader.identity = replace(self.reader.identity, actor_id="changed")
        self.assertEqual((await exchange(self.bridge.port))["code"], "AccessDenied")
        self.assertEqual(self.reader.calls, 0)

    async def test_malformed_current_projection_facts_fail_closed(self):
        originals = projection(succeeded=True)
        variants = []
        for key, value in (
            ("task_id", "foreign"),
            ("case_id", str(uuid4())),
            ("case_revision", True),
            ("projection_revision", "wrong"),
        ):
            changed = copy.deepcopy(originals)
            changed[key] = value
            variants.append(changed)
        changed = copy.deepcopy(originals)
        changed["effect"]["result"]["new_check_in"] = "2030-12-11"
        variants.append(changed)
        changed = copy.deepcopy(originals)
        changed["outcome"]["intent_id"] = str(uuid4())
        variants.append(changed)
        changed = copy.deepcopy(originals)
        changed["outcome"]["effect_id"] = None
        variants.append(changed)
        changed = copy.deepcopy(originals)
        changed["outcome"]["result"]["scope_id"] = "foreign"
        changed["effect"]["result"]["scope_id"] = "foreign"
        variants.append(changed)
        changed = copy.deepcopy(originals)
        changed["lifecycle"]["state"] = ["completed"]
        variants.append(changed)
        changed = copy.deepcopy(originals)
        changed["lifecycle"]["version"] = 1
        variants.append(changed)
        changed = copy.deepcopy(originals)
        changed["confirmation"]["intent_id"] = None
        variants.append(changed)
        for value in variants:
            with self.subTest(value=value):
                self.reader.value = value
                answer = await exchange(self.bridge.port)
                self.assertEqual(
                    answer, {"schemaVersion": 1, "status": "unavailable", "code": "Unavailable"}
                )
                self.assertNotIn(PRIVATE, json.dumps(answer))

    async def test_duplicate_JSON_and_nonobject_or_unknown_fields_never_read(self):
        payloads = [
            b'{"schemaVersion":1,"schemaVersion":1}',
            b"[]",
            b"null",
            b'{"schemaVersion":NaN}',
            json.dumps({**body(), "taskId": TASK}).encode(),
            json.dumps({**body(), "schemaVersion": True}).encode(),
        ]
        for payload in payloads:
            raw = (
                f"POST /v1/current-case/inspect HTTP/1.1\r\nHost: 127.0.0.1:{self.bridge.port}\r\nAuthorization: Bearer {TOKEN}\r\nContent-Type: application/json\r\nContent-Length: {len(payload)}\r\nConnection: close\r\n\r\n"
            ).encode() + payload
            self.assertEqual((await exchange(self.bridge.port, raw=raw))["code"], "InvalidCommand")
        self.assertEqual(self.reader.calls, 0)

    async def test_read_only_route_and_HTTP_framing_reject_before_get(self):
        payload = json.dumps(body()).encode()
        valid = (
            f"POST /v1/current-case/inspect HTTP/1.1\r\nHost: 127.0.0.1:{self.bridge.port}\r\nAuthorization: Bearer {TOKEN}\r\nContent-Type: application/json\r\nContent-Length: {len(payload)}\r\nConnection: close\r\n\r\n"
        ).encode() + payload
        variants = [
            valid.replace(b"/v1/current-case/inspect", b"/v1/case/confirm"),
            valid.replace(b"Connection: close", b"Connection: keep-alive"),
            valid.replace(b"Content-Type:", b"Other: x\r\nContent-Type:"),
            valid.replace(b"Content-Length:", b"Transfer-Encoding: chunked\r\nContent-Length:"),
            valid.replace(
                b"Content-Type: application/json",
                b"Content-Type: application/json\r\nContent-Type: application/json",
            ),
        ]
        for raw in variants:
            self.assertEqual((await exchange(self.bridge.port, raw=raw))["code"], "InvalidCommand")
        self.assertEqual(self.reader.calls, 0)

    async def test_identity_changed_during_get_is_not_disclosed(self):
        self.reader.release.clear()
        waiting = asyncio.create_task(exchange(self.bridge.port))
        await self.reader.entered.wait()
        self.reader.identity = replace(self.reader.identity, scope_id="different")
        self.reader.release.set()
        self.assertEqual((await waiting)["code"], "AccessDenied")
        self.assertEqual(self.reader.calls, 1)

    async def test_timeout_retains_two_actual_reads_and_close_does_not_close_shared_reader(self):
        await self.bridge.close()
        self.bridge = await module.start_current_case_bridge(
            (binding(self.reader),), request_timeout_ms=20, close_timeout_ms=20
        )
        self.reader.release.clear()
        results = await asyncio.gather(exchange(self.bridge.port), exchange(self.bridge.port))
        self.assertEqual([item["code"] for item in results], ["Unavailable", "Unavailable"])
        self.assertEqual(self.bridge.pending_count, 2)
        self.assertEqual((await exchange(self.bridge.port))["code"], "Overloaded")
        with self.assertRaises(module.BridgeError) as caught:
            await self.bridge.close()
        self.assertEqual(caught.exception.code, "CleanupIncomplete")
        self.assertEqual(self.reader.closed, 0)
        self.reader.release.set()
        await self.bridge.close()
        self.assertEqual(self.bridge.pending_count, 0)
        self.assertEqual(self.reader.closed, 0)

    async def test_caller_abandonment_retains_get_and_fresh_progress_after_settlement(self):
        self.reader.release.clear()
        waiting = asyncio.create_task(exchange(self.bridge.port))
        await self.reader.entered.wait()
        waiting.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiting
        self.assertEqual(self.bridge.pending_count, 1)
        self.reader.release.set()
        for _ in range(100):
            if self.bridge.pending_count == 0:
                break
            await asyncio.sleep(0.005)
        self.assertEqual((await exchange(self.bridge.port))["status"], "known")

    async def test_dependency_and_telemetry_errors_never_disclose_private_text(self):
        self.reader.failure = RuntimeError(PRIVATE)
        with patch.object(module.LOGGER, "info", side_effect=RuntimeError(PRIVATE)):
            answer = await exchange(self.bridge.port)
        self.assertEqual(answer["code"], "Unavailable")
        self.assertNotIn(PRIVATE, json.dumps(answer))
        self.assertEqual(self.bridge.metrics()["telemetry_failed"], 1)

    async def test_public_reader_uses_same_supported_boundary_without_private_extraction(self):
        actor, token = AuthenticatedActor("p1_actor", "p1_scope"), BearerToken(TOKEN)
        directory = TokenDirectory({token: actor})
        calls = []

        class Projection:
            def get(self, *, actor, task_id, cursor, limit):
                calls.append((actor, task_id, cursor, limit))
                return CaseProjection.create(projection())

        service = ConversationService(
            directory, SimpleNamespace(), Projection(), SimpleNamespace(directory=directory)
        )
        boundary = AsyncConversationService(service)
        reader = module.PublicCurrentCaseReader(boundary, token, "p1_fixture")
        try:
            self.assertEqual(
                reader.identity, CaseControlIdentity("p1_actor", "p1_scope", "p1_fixture")
            )
            returned = await reader.get(task_id=TASK, cursor=None, limit=1)
            self.assertEqual(returned.payload()["task_id"], TASK)
            self.assertEqual(calls, [(actor, TASK, None, 1)])
        finally:
            await reader.close()
        self.assertEqual(boundary.pending_count, 0)

    async def test_late_writer_close_stays_owned_until_actual_release(self):
        await self.bridge.close()
        entered, release = asyncio.Event(), asyncio.Event()

        class LateWriter:
            def __init__(inner, writer):
                inner.writer, inner.transport = writer, writer.transport

            def write(inner, raw):
                return inner.writer.write(raw)

            async def drain(inner):
                await inner.writer.drain()

            def close(inner):
                entered.set()

            async def wait_closed(inner):
                await release.wait()
                inner.writer.close()
                await inner.writer.wait_closed()

        class LateBridge(module.CurrentCaseBridge):
            def _connected(inner, reader, writer):
                super()._connected(reader, LateWriter(writer))

        self.bridge = LateBridge((binding(self.reader),), close_timeout_ms=20)
        await self.bridge.start()
        reader, writer = await asyncio.open_connection("127.0.0.1", self.bridge.port)
        try:
            payload = json.dumps(body()).encode()
            writer.write(
                (
                    f"POST /v1/current-case/inspect HTTP/1.1\r\nHost: 127.0.0.1:{self.bridge.port}\r\nAuthorization: Bearer {TOKEN}\r\nContent-Type: application/json\r\nContent-Length: {len(payload)}\r\nConnection: close\r\n\r\n"
                ).encode()
                + payload
            )
            await writer.drain()
            header = await reader.readuntil(b"\r\n\r\n")
            length = int(
                next(
                    line.split(b": ")[1]
                    for line in header.split(b"\r\n")
                    if line.startswith(b"Content-Length:")
                )
            )
            self.assertEqual(json.loads(await reader.readexactly(length))["status"], "known")
            await asyncio.wait_for(entered.wait(), 1)
            with self.assertRaisesRegex(module.BridgeError, "^CleanupIncomplete$"):
                await self.bridge.close()
            self.assertEqual(self.bridge.metrics()["sockets"], 1)
            self.assertEqual(self.reader.closed, 0)
            release.set()
            await self.bridge.close()
            self.assertEqual(await asyncio.wait_for(reader.read(), 1), b"")
            self.assertEqual(self.bridge.metrics()["sockets"], 0)
        finally:
            release.set()
            writer.close()
            await writer.wait_closed()

    async def test_cancelled_start_retains_late_listener_and_application_reader(self):
        await self.bridge.close()
        self.bridge = module.CurrentCaseBridge((binding(self.reader),), close_timeout_ms=20)
        entered, release = asyncio.Event(), asyncio.Event()
        start_server, ports = asyncio.start_server, []

        async def late(*args, **kwargs):
            entered.set()
            await release.wait()
            server = await start_server(*args, **kwargs)
            ports.append(server.sockets[0].getsockname()[1])
            return server

        with patch.object(module.asyncio, "start_server", side_effect=late):
            waiting = asyncio.create_task(self.bridge.start())
            await asyncio.wait_for(entered.wait(), 1)
            waiting.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await waiting
            with self.assertRaisesRegex(module.BridgeError, "^CleanupIncomplete$"):
                await self.bridge.close()
            release.set()
            await self.bridge.close()
        self.assertEqual(self.reader.closed, 0)
        with self.assertRaises(OSError):
            await asyncio.open_connection("127.0.0.1", ports[0])

    async def test_preintent_cancel_is_not_fabricated_as_supplier_mutation(self):
        self.reader.value["lifecycle"]["state"] = "cancelled"
        self.reader.value["confirmation"]["state"] = "cancelled"
        self.reader.value["outcome"] = {
            "state": "cancelled",
            "result": None,
            "error_code": None,
            "cancellation": "cancelled_before_commit",
            "created_at": "2030-01-01T00:00:00+00:00",
            "intent_id": None,
            "effect_id": None,
            "event_id": EVENT,
        }
        result = (await exchange(self.bridge.port))["case"]
        self.assertEqual(
            result["mutation"],
            {
                "state": "not_observed",
                "outcome": "cancelled",
                "cancellation": "cancelled_before_commit",
                "effectId": None,
                "outcomeEventId": EVENT,
            },
        )
        self.assertIsNone(result["supplierResult"])

    async def test_socket_pressure_is_bounded_and_config_is_literal_loopback(self):
        self.assertEqual(self.bridge._server.sockets[0].getsockname()[0], "127.0.0.1")
        connections = await asyncio.gather(
            *(asyncio.open_connection("127.0.0.1", self.bridge.port) for _ in range(24)),
            return_exceptions=True,
        )
        try:
            self.assertLessEqual(self.bridge.metrics()["sockets"], 16)
            self.assertLessEqual(self.bridge.pending_count, 2)
        finally:
            writers = [value[1] for value in connections if not isinstance(value, BaseException)]
            for writer in writers:
                writer.close()
            await asyncio.gather(
                *(writer.wait_closed() for writer in writers), return_exceptions=True
            )
        for values, options in [
            ((), {}),
            ((binding(self.reader), binding(self.reader)), {}),
            ((binding(self.reader),), {"request_timeout_ms": 2001}),
            ((binding(self.reader),), {"close_timeout_ms": True}),
        ]:
            with self.assertRaises(module.BridgeError):
                module.CurrentCaseBridge(values, **options)
        self.assertNotIn(TOKEN, repr(binding(self.reader)))

    async def test_listener_cleanup_failure_does_not_skip_owned_get_settlement(self):
        await self.bridge.close()
        self.bridge = await module.start_current_case_bridge(
            (binding(self.reader),), request_timeout_ms=20, close_timeout_ms=20
        )
        self.reader.release.clear()
        self.assertEqual((await exchange(self.bridge.port))["code"], "Unavailable")
        self.assertEqual(self.bridge.pending_count, 1)

        async def failed_listener_close():
            raise OSError(PRIVATE)

        with patch.object(self.bridge._server, "wait_closed", side_effect=failed_listener_close):
            with self.assertRaisesRegex(module.BridgeError, "^CleanupIncomplete$"):
                await self.bridge.close()
            self.assertFalse(self.bridge._close_task.done())
            self.reader.release.set()
            with self.assertRaisesRegex(module.BridgeError, "^CleanupIncomplete$"):
                await self.bridge.close()
            self.assertEqual(self.bridge.pending_count, 0)
            self.assertEqual(self.bridge.metrics()["sockets"], 0)
        await self.bridge.close()
        self.assertEqual(self.reader.closed, 0)

    async def test_public_unicode_task_identity_and_explicit_reference_byte_subset(self):
        await self.bridge.close()
        task = "trusted original Ω"
        self.reader.expected_task = task
        self.reader.value["task_id"] = task
        self.reader.value["request"]["booking_reference"] = "BÉK-001"
        self.bridge = await module.start_current_case_bridge(
            (replace(binding(self.reader), task_id=task),)
        )
        observed = (await exchange(self.bridge.port))["case"]
        self.assertEqual(observed["workflow"]["taskId"], task)
        self.assertEqual(observed["request"]["bookingReference"], "BÉK-001")
        self.reader.value["request"]["booking_reference"] = "É" * 40
        rejected = await exchange(self.bridge.port)
        self.assertEqual(
            rejected, {"schemaVersion": 1, "status": "unavailable", "code": "Unavailable"}
        )


if __name__ == "__main__":
    unittest.main()
