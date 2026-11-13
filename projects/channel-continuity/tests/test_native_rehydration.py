"""Read-only context codec/actual local HTTP and pinned SDK initialization assertions."""

import asyncio
import json
import unittest
from uuid import uuid4

from test_native_sdk import AudioSink, Intake, QueueInput, TextSink, binding, context, scripted

from channel_continuity.codec import TrustedPrincipal, produce_text_event
from channel_continuity.native import NativeRuntime
from channel_continuity.native_models import NativeCredential, NativeEndpoint, NativeError
from channel_continuity.native_rehydration import (
    NativeContextHttpClient,
    NativeRehydrationProfile,
    RehydrationQuery,
    context_from,
)

STAMP = "2026-11-11T10:20:30.123Z"


def payload(b, revision="1", history=True):
    receipt = str(uuid4())
    event = produce_text_event(
        {
            "eventId": str(uuid4()),
            "providerScope": {
                "tenantId": "tenant",
                "provider": "livekit",
                "providerAccountId": "local",
            },
            "accountScope": {"tenantId": "tenant", "accountId": "account"},
            "conversationId": "conversation",
            "caseId": "case",
            "receivedAt": STAMP,
            "channel": "web_chat",
            "messageId": str(uuid4()),
            "senderId": str(uuid4()),
            "body": "Old accepted user request — नमस्ते",
        },
        TrustedPrincipal(b.provider_scope, b.account_scope),
    )
    # Codec frozen event is copied through its exact original wire representation.
    original = json.loads(event.wire_json)
    value = {
        "schemaVersion": 1,
        "contextId": str(uuid4()),
        "access": {
            "kind": "native",
            "bindingId": b.binding_id,
            "roomId": b.room_id,
            "participantId": b.participant_id,
        },
        "case": {
            "schemaVersion": 1,
            "source": "standalone_reference_v1",
            "scope": {"tenantId": "tenant", "accountId": "account"},
            "caseId": "case",
            "conversationId": "conversation",
            "revision": revision,
            "request": {
                "schemaVersion": 1,
                "kind": "booking_investigation",
                "bookingReference": "BOOK-1",
                "newCheckIn": "2030-01-12",
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
        "history": {
            "messages": [
                {
                    "receipt": {
                        "receiptId": receipt,
                        "eventId": original["eventId"],
                        "messageId": original["messageId"],
                        "acceptanceSequence": "1",
                        "acceptedAt": STAMP,
                    },
                    "event": original,
                    "operationKey": str(uuid4()),
                    "processingState": "dispatched",
                    "associationVersion": "1",
                }
            ]
            if history
            else [],
            "nextCursor": None,
            "hasMore": False,
        },
        "work": {"items": [], "nextCursor": None, "hasMore": False},
        "responses": {"items": [], "nextCursor": None, "hasMore": False},
        "replies": {"items": [], "nextCursor": None, "hasMore": False},
        "observed": {
            "p2ObservedAt": STAMP,
            "caseObservedAt": STAMP,
            "disclosureAdmittedAt": STAMP,
            "atomic": False,
        },
    }
    return value


class ContextModelTests(unittest.TestCase):
    def test_exact_context_copies_data_and_returns_detached_payload(self):
        b = binding()
        raw = payload(b)
        v = context_from(raw, b)
        raw["case"]["revision"] = "2"
        self.assertEqual(v.case_revision, "1")
        copy_ = v.payload()
        copy_["history"]["messages"].clear()
        self.assertEqual(len(v.payload()["history"]["messages"]), 1)

    def test_current_authority_scope_and_new_room_are_required(self):
        b = binding()
        for section, key, value in (
            ("access", "bindingId", str(uuid4())),
            ("access", "roomId", "old-room"),
            ("case", "caseId", "other"),
            ("case", "conversationId", "other"),
        ):
            with self.subTest(key=key):
                raw = payload(b)
                raw[section][key] = value
                with self.assertRaises(NativeError):
                    context_from(raw, b)

    def test_quote_confirmation_and_unknown_case_fields_are_rejected(self):
        b = binding()
        for field in ("quote", "confirmation_payload", "confirmation", "tools", "cancelled"):
            raw = payload(b)
            raw["case"][field] = {"secret": "never forwarded"}
            with self.subTest(field=field), self.assertRaises(NativeError):
                context_from(raw, b)

    def test_source_separation_and_unsupported_inquiry_supplier_truth(self):
        b = binding()
        raw = payload(b)
        raw["case"]["supplierResult"] = {
            "supplierId": str(uuid4()),
            "revision": "2",
            "bookingReference": "BOOK-1",
            "newCheckIn": "2030-01-12",
        }
        with self.assertRaises(NativeError):
            context_from(raw, b)

    def test_int64_and_unicode_current_case_facts(self):
        b = binding()
        raw = payload(b, "9223372036854775807")
        raw["case"]["request"]["bookingReference"] = "BOOK नमस्ते"
        self.assertEqual(context_from(raw, b).case_revision, "9223372036854775807")
        raw["case"]["revision"] = "9223372036854775808"
        with self.assertRaises(NativeError):
            context_from(raw, b)

    def test_p1_task_identity_uses_128_codepoints_not_128_bytes(self):
        b = binding()
        raw = payload(b)
        raw["case"]["source"] = "p1_public_v4"
        raw["case"]["workflow"] = {"taskId": "界" * 128, "state": "completed", "version": "1"}
        self.assertEqual(context_from(raw, b).payload()["case"]["workflow"]["taskId"], "界" * 128)
        raw["case"]["workflow"]["taskId"] += "界"
        with self.assertRaises(NativeError):
            context_from(raw, b)

    def test_paging_cannot_cross_scope_or_truncate_whole_message(self):
        b = binding()
        raw = payload(b)
        raw["history"]["hasMore"] = True
        raw["history"]["nextCursor"] = {
            "kind": "history",
            "scopeDigest": "b" * 64,
            "beforeSequence": "1",
        }
        with self.assertRaises(NativeError):
            context_from(raw, b)

    def test_non_atomic_and_total_byte_contract(self):
        b = binding()
        raw = payload(b)
        raw["observed"]["atomic"] = True
        with self.assertRaises(NativeError):
            context_from(raw, b)
        raw = payload(b)
        raw["history"]["messages"] *= 9
        with self.assertRaises(NativeError):
            context_from(raw, b)

    def test_query_is_copied_closed_and_cannot_supply_scope(self):
        q = RehydrationQuery()
        raw = q.payload()
        raw["limits"]["history"] = 1
        self.assertEqual(q.payload()["limits"]["history"], 8)
        for change in (
            {"scope": {}},
            {"limits": {"history": 0, "work": 8, "responses": 4, "replies": 4}},
        ):
            raw = q.payload()
            raw.update(change)
            with self.assertRaises(NativeError):
                RehydrationQuery.from_payload(raw)

    def test_custom_equality_value_is_rejected_without_execution(self):
        called = []

        class Value:
            def __eq__(self, other):
                called.append(other)
                return True

        b = binding()
        raw = payload(b)
        raw["case"]["request"]["kind"] = Value()
        with self.assertRaises(NativeError):
            context_from(raw, b)
        self.assertEqual(called, [])

    def test_escaped_surrogate_cannot_escape_fixed_model_error(self):
        b = binding()
        raw = payload(b)
        raw["case"]["request"]["bookingReference"] = "\ud800"
        with self.assertRaises(NativeError):
            context_from(raw, b)


class ContextHttpTests(unittest.IsolatedAsyncioTestCase):
    async def endpoint(self, handler):
        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        self.addAsyncCleanup(server.wait_closed)
        self.addCleanup(server.close)
        return NativeEndpoint("127.0.0.1", server.sockets[0].getsockname()[1])

    async def test_real_http_read_carries_only_fixed_query_and_native_bearer(self):
        b = binding()
        seen = []

        async def handler(reader, writer):
            try:
                head = await reader.readuntil(b"\r\n\r\n")
                size = int(
                    next(
                        x
                        for x in head.decode().split("\r\n")
                        if x.lower().startswith("content-length:")
                    ).split(":")[1]
                )
                seen.append((head, await reader.readexactly(size)))
                raw = json.dumps(
                    {"schemaVersion": 1, "status": "known", "context": payload(b)},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode()
                writer.write(
                    f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {len(raw)}\r\nConnection: close\r\n\r\n".encode()
                    + raw
                )
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        client = NativeContextHttpClient(
            await self.endpoint(handler), NativeCredential("K" * 43), b
        )
        self.addAsyncCleanup(client.aclose)
        result = await client.load()
        self.assertEqual(result.case_revision, "1")
        self.assertIn(b"POST /v1/rehydration/native HTTP/1.1", seen[0][0])
        self.assertIn(b"Authorization: Bearer " + b"K" * 43, seen[0][0])
        self.assertEqual(set(json.loads(seen[0][1])), {"schemaVersion", "query"})
        self.assertEqual(client.metrics()["known"], 1)

    async def test_lost_or_foreign_read_is_unavailable_and_no_retry(self):
        b = binding()
        calls = []

        async def handler(reader, writer):
            calls.append(1)
            try:
                await reader.readuntil(b"\r\n\r\n")
                raw = json.dumps(
                    {"schemaVersion": 1, "status": "known", "context": payload(binding())},
                    separators=(",", ":"),
                ).encode()
                writer.write(
                    f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {len(raw)}\r\nConnection: close\r\n\r\n".encode()
                    + raw
                )
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        client = NativeContextHttpClient(
            await self.endpoint(handler), NativeCredential("K" * 43), b
        )
        self.addAsyncCleanup(client.aclose)
        with self.assertRaises(NativeError):
            await client.load()
        self.assertEqual(calls, [1])


class MemoryContext:
    def __init__(self, b, gate=None):
        self.b = b
        self.gate = gate
        self.entered = asyncio.Event()
        self.revision = "1"
        self.calls = 0

    async def load(self, query=None):
        self.calls += 1
        self.entered.set()
        if self.gate is not None:
            await self.gate.wait()
        return context_from(payload(self.b, self.revision), self.b)

    async def aclose(self):
        pass


class ContextSdkTests(unittest.IsolatedAsyncioTestCase):
    async def make(self, gate=None):
        b = binding()
        p = Intake()
        p.binding = b
        stt = scripted.ScriptedRecognizer()
        model = scripted.ScriptedModel()
        voice = scripted.ScriptedVoice(b"\x10\x27" * 1600, pace=False)
        port = MemoryContext(b, gate)
        r = NativeRuntime(
            b, p, stt=stt, llm=model, tts=voice, rehydration=NativeRehydrationProfile(port)
        )
        r.session.input.audio = QueueInput()
        r.session.output.audio = AudioSink()
        r.session.output.transcription = TextSink()
        self.addAsyncCleanup(voice.aclose)
        self.addAsyncCleanup(stt.aclose)
        self.addAsyncCleanup(model.aclose)
        self.addAsyncCleanup(r.aclose)
        return r, p, model, port

    async def activate(self, r):
        await r.refresh_context()
        await r.session.start(r.agent, record=False)
        r._ready = True
        r.session.input.set_audio_enabled(False)

    async def test_actual_sdk_context_load_and_idle_refresh_generate_nothing_then_new_input_progress(
        self,
    ):
        r, p, model, _port = await self.make()
        await self.activate(r)
        self.assertEqual(model.calls, 0)
        self.assertEqual(p.calls, [])
        users = [x for x in r.agent.chat_ctx.items if getattr(x, "role", None) == "user"]
        self.assertEqual(len(users), 1)
        self.assertTrue(users[0].id.startswith("p2.history."))
        await r.refresh_context()
        self.assertEqual(model.calls, 0)
        new = context(r.binding, str(uuid4()))
        self.assertEqual((await r.prepare(new))["source"], "scripted")
        self.assertEqual(model.calls, 1)
        self.assertEqual(p.calls, [])
        self.assertEqual(r.metrics()["defaultReplyInvocations"], 0)

    async def test_mismatched_current_revision_requires_explicit_idle_refresh(self):
        r, p, model, port = await self.make()
        await self.activate(r)
        new = context(r.binding, str(uuid4()))
        new["caseRevision"] = "2"
        with self.assertRaises(NativeError):
            await r.prepare(new)
        self.assertEqual(model.calls, 0)
        self.assertEqual(r.rehydration_metrics()["revisionMismatch"], 1)
        port.revision = "2"
        await r.refresh_context()
        await r.prepare(new)
        self.assertEqual(model.calls, 1)
        self.assertEqual(p.calls, [])

    async def test_held_context_is_owned_and_closed_runtime_never_updates_or_generates(self):
        gate = asyncio.Event()
        r, p, model, port = await self.make(gate)
        task = asyncio.create_task(r.refresh_context())
        await port.entered.wait()
        self.assertEqual(r.rehydration_metrics()["active"], 1)
        with self.assertRaises(NativeError):
            await r.refresh_context()
        closing = asyncio.create_task(r.aclose())
        await asyncio.sleep(0)
        self.assertFalse(closing.done())
        gate.set()
        with self.assertRaises(NativeError):
            await task
        await closing
        self.assertIsNone(r.loaded_context)
        self.assertEqual(model.calls, 0)
        self.assertEqual(p.calls, [])

    async def test_revision_zero_is_readable_but_native_dispatch_domain_remains_explicit(self):
        r, p, model, port = await self.make()
        port.revision = "0"
        await self.activate(r)
        self.assertEqual(r.loaded_context.case_revision, "0")
        from channel_continuity.native_models import NativeInput

        with self.assertRaises(NativeError):
            await r._accept(
                NativeInput(
                    str(uuid4()),
                    "web_chat",
                    "investigate",
                    r.binding.room_id,
                    r.binding.participant_id,
                )
            )
        zero = context(r.binding, str(uuid4()))
        zero["caseRevision"] = "0"
        with self.assertRaises(NativeError):
            await r.prepare(zero)
        self.assertEqual(p.calls, [])
        self.assertEqual(model.calls, 0)
        port.revision = "1"
        await r.refresh_context()
        await r.prepare(context(r.binding, str(uuid4())))
        self.assertEqual(model.calls, 1)
