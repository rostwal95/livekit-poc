"""Independent immutable communication contracts and real loopback framing/lifetime."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import unittest
from dataclasses import FrozenInstanceError, replace
from uuid import uuid4

from channel_continuity.codec import AccountScope, ProviderScope
from channel_continuity.native_communication import (
    BrowserObservation,
    NativeCommunicationHttpClient,
    ObservationReceipt,
    ResponseAnchor,
    ResponseReceipt,
    ResponseView,
    SdkObservation,
    observation_receipt,
    response_receipt,
    response_view,
)
from channel_continuity.native_http import NativeCleanupIncomplete
from channel_continuity.native_models import (
    NativeBinding,
    NativeCredential,
    NativeEndpoint,
    NativeError,
)

STAMP = "2026-11-11T10:20:30.123Z"


def binding():
    return NativeBinding(
        str(uuid4()),
        ProviderScope("tenant", "livekit", "provider"),
        AccountScope("tenant", "account"),
        "case",
        "conversation",
        "room",
        "browser",
        "agent",
    )


def anchor(b):
    return ResponseAnchor(
        str(uuid4()),
        str(uuid4()),
        "speech_1",
        b.binding_id,
        str(uuid4()),
        str(uuid4()),
        str(uuid4()),
        "9223372036854775807",
    )


def payload_digest(value):
    return hashlib.sha256(
        json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def receipt(a, b):
    bound = {
        **a.payload(),
        "scope": {"tenantId": b.account_scope.tenant_id, "accountId": b.account_scope.account_id},
        "providerScope": {
            "tenantId": b.provider_scope.tenant_id,
            "provider": b.provider_scope.provider,
            "providerAccountId": b.provider_scope.provider_account_id,
        },
        "caseId": b.case_id,
        "conversationId": b.conversation_id,
        "roomId": b.room_id,
        "participantId": b.participant_id,
    }
    return ResponseReceipt(a.response_id, str(uuid4()), payload_digest(bound), "1", STAMP)


def sdk(a):
    return SdkObservation(
        str(uuid4()),
        a.response_id,
        a.generation_id,
        a.sdk_speech_id,
        "generated_complete",
        text="Actual full output — नमस्ते\n",
    )


def observation(o):
    return ObservationReceipt(
        o.response_id, o.event_id, str(uuid4()), payload_digest(o.payload()), "1", STAMP
    )


def view(a, b, r):
    return ResponseView(a, b, r, 0, None, "unknown", None, "unknown", False)


class CommunicationModelTests(unittest.TestCase):
    def setUp(self):
        self.b = binding()
        self.a = anchor(self.b)
        self.r = receipt(self.a, self.b)

    def test_frozen_values_roundtrip_and_payload_copy(self):
        values = (
            self.a,
            self.r,
            sdk(self.a),
            BrowserObservation(str(uuid4()), self.a.response_id, "partial", 125),
            observation(sdk(self.a)),
            view(self.a, self.b, self.r),
        )
        for value in values:
            with (
                self.subTest(value=type(value).__name__),
                self.assertRaises((FrozenInstanceError, AttributeError)),
            ):
                value.extra = "inert"
        raw = view(self.a, self.b, self.r).payload()
        self.assertEqual(response_view(raw, self.b), view(self.a, self.b, self.r))
        raw["anchor"]["scope"]["tenantId"] = "foreign"
        self.assertEqual(
            view(self.a, self.b, self.r).payload()["anchor"]["scope"]["tenantId"], "tenant"
        )
        self.assertEqual(response_receipt(self.r.payload()), self.r)
        o = observation(sdk(self.a))
        self.assertEqual(observation_receipt(o.payload()), o)

    def test_anchor_uuid_speech_and_revision_fail_closed(self):
        for changes in (
            {"response_id": "not_uuid"},
            {"sdk_speech_id": "bad\nheader"},
            {"case_revision": "0"},
            {"case_revision": "01"},
            {"case_revision": "9223372036854775808"},
            {"case_revision": 1},
        ):
            with self.subTest(changes=changes), self.assertRaises(NativeError):
                replace(self.a, **changes)

    def test_receipt_digest_timestamp_sequence_and_closed_fields(self):
        for changes in (
            {"anchor_digest": "A" * 64},
            {"response_sequence": "00"},
            {"response_sequence": True},
            {"accepted_at": "2026-02-30T10:20:30.123Z"},
            {"accepted_at": "2026-11-11T10:20:30Z"},
        ):
            with self.subTest(changes=changes), self.assertRaises(NativeError):
                replace(self.r, **changes)
        for raw in (
            {**self.r.payload(), "humanAcknowledged": True},
            {k: v for k, v in self.r.payload().items() if k != "anchorDigest"},
        ):
            with self.assertRaises(NativeError):
                response_receipt(raw)

    def test_sdk_fact_variants_and_utf8_caps(self):
        a = self.a
        generated = sdk(a)
        self.assertEqual(generated.payload()["fact"]["type"], "generated_complete")
        settled = SdkObservation(
            str(uuid4()),
            a.response_id,
            a.generation_id,
            a.sdk_speech_id,
            "speech_settled",
            state="interrupted",
            sdk_text="synchronized partial",
        )
        self.assertEqual(settled.payload()["fact"]["state"], "interrupted")
        for changes in (
            {"text": "é" * 2049},
            {"text": "\ud800"},
            {"state": "completed"},
            {"sdk_text": "not this variant"},
            {"kind": "model_claimed_playback"},
        ):
            with self.subTest(changes=changes), self.assertRaises(NativeError):
                replace(generated, **changes)
        with self.assertRaises(NativeError):
            replace(settled, text="fabricated full text")
        with self.assertRaises(NativeError):
            replace(settled, state="played")

    def test_browser_reports_are_bounded_source_facts(self):
        o = BrowserObservation(str(uuid4()), self.a.response_id, "completed", 180000)
        self.assertEqual(o.payload()["state"], "completed")
        self.assertNotIn("consent", o.payload())
        for changes in (
            {"state": "human_acknowledged"},
            {"observed_audio_ms": True},
            {"observed_audio_ms": -1},
            {"observed_audio_ms": 180001},
        ):
            with self.subTest(changes=changes), self.assertRaises(NativeError):
                replace(o, **changes)

    def test_view_rejects_foreign_bindings_receipt_and_summary_bounds(self):
        original = view(self.a, self.b, self.r)
        raw = original.payload()
        for path in (
            ("scope", "tenantId"),
            ("scope", "accountId"),
            ("providerScope", "providerAccountId"),
        ):
            changed = copy.deepcopy(raw)
            changed["anchor"][path[0]][path[1]] = "foreign"
            with self.subTest(path=path), self.assertRaises(NativeError) as caught:
                response_view(changed, self.b)
            self.assertEqual(caught.exception.code, "forbidden")
        for changes in (
            {"receipt": replace(self.r, response_id=str(uuid4()))},
            {"observation_count": True},
            {"observation_count": 65},
            {"sdk_state": "played"},
            {"browser_state": "consent"},
            {"conflicted": 1},
        ):
            with self.subTest(changes=changes), self.assertRaises(NativeError):
                replace(original, **changes)


class CommunicationHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.b = binding()
        self.a = anchor(self.b)
        self.r = receipt(self.a, self.b)
        self.tasks = set()
        self.writers = set()
        self.servers = []
        self.clients = []
        self.releases = []

    async def asyncTearDown(self):
        for release in self.releases:
            release.set()
        for server in self.servers:
            server.close()
        for writer in tuple(self.writers):
            writer.close()
        if self.tasks:
            await asyncio.gather(*tuple(self.tasks), return_exceptions=True)
        for server in self.servers:
            await server.wait_closed()
        for client in self.clients:
            await client.aclose()

    async def server(self, work, *, timeout=0.2, cleanup=0.2):
        async def handle(reader, writer):
            task = asyncio.current_task()
            self.tasks.add(task)
            self.writers.add(writer)
            try:
                head = await reader.readuntil(b"\r\n\r\n")
                lines = head.split(b"\r\n")
                headers = dict(line.split(b": ", 1) for line in lines[1:-2])
                body = await reader.readexactly(int(headers[b"Content-Length"]))
                await work(writer, lines[0], headers, body)
            finally:
                writer.close()
                await writer.wait_closed()
                self.writers.discard(writer)
                self.tasks.discard(task)

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        self.servers.append(server)
        client = NativeCommunicationHttpClient(
            NativeEndpoint("127.0.0.1", server.sockets[0].getsockname()[1]),
            *(NativeCredential(c * 43) for c in "psba"),
            self.b,
            timeout=timeout,
            cleanup=cleanup,
        )
        self.clients.append(client)
        return client

    async def write(
        self, writer, value, *, status=200, extra_head=b"", extra_body=b"", connection="close"
    ):
        raw = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()
        writer.write(
            f"HTTP/1.1 {status} Result\r\nContent-Type: application/json\r\nContent-Length: {len(raw)}\r\nConnection: {connection}\r\n".encode()
            + extra_head
            + b"\r\n"
            + raw
            + extra_body
        )
        await writer.drain()

    def known(self, result):
        return {"schemaVersion": 1, "status": "known", "result": result}

    async def test_four_routes_exact_source_credentials_and_wire(self):
        sdk_value = sdk(self.a)
        browser = BrowserObservation(str(uuid4()), self.a.response_id, "partial", 32)
        calls = []
        routes = {
            b"POST /v1/native/responses HTTP/1.1": (b"p", self.a.payload(), self.r.payload()),
            b"POST /v1/native/sdk-observations HTTP/1.1": (
                b"s",
                sdk_value.payload(),
                observation(sdk_value).payload(),
            ),
            b"POST /v1/native/browser-observations HTTP/1.1": (
                b"b",
                browser.payload(),
                observation(browser).payload(),
            ),
            b"POST /v1/native/response-inspect HTTP/1.1": (
                b"a",
                {"schemaVersion": 1, "responseId": self.a.response_id},
                view(self.a, self.b, self.r).payload(),
            ),
        }

        async def work(w, line, h, body):
            credential, expected, result = routes[line]
            self.assertEqual(h[b"Authorization"], b"Bearer " + credential * 43)
            self.assertEqual(json.loads(body), expected)
            self.assertEqual(
                body, json.dumps(expected, ensure_ascii=False, separators=(",", ":")).encode()
            )
            calls.append(line)
            await self.write(w, self.known(result))

        c = await self.server(work)
        self.assertEqual(await c.begin_response(self.a), self.r)
        self.assertEqual((await c.observe_sdk(sdk_value)).event_id, sdk_value.event_id)
        self.assertEqual((await c.observe_browser(browser)).event_id, browser.event_id)
        self.assertEqual((await c.inspect_response(self.a.response_id)).anchor, self.a)
        self.assertEqual(len(calls), 4)
        self.assertEqual(
            c.metrics(), {"started": 4, "known": 4, "rejected": 0, "unknown": 0, "active": 0}
        )

    async def test_validly_shaped_wrong_request_digest_never_adopts_receipt(self):
        sdk_value = sdk(self.a)
        browser = BrowserObservation(str(uuid4()), self.a.response_id, "partial", 1)
        for method, request, result in (
            ("begin_response", self.a, replace(self.r, anchor_digest="0" * 64).payload()),
            (
                "observe_sdk",
                sdk_value,
                replace(observation(sdk_value), payload_digest="0" * 64).payload(),
            ),
            (
                "observe_browser",
                browser,
                replace(observation(browser), payload_digest="0" * 64).payload(),
            ),
        ):

            async def work(w, line, h, body, result=result):
                await self.write(w, self.known(result))

            c = await self.server(work)
            with self.subTest(method=method), self.assertRaises(NativeError) as caught:
                await getattr(c, method)(request)
            self.assertEqual(caught.exception.code, "acknowledgement_unknown")
            self.assertEqual(c.metrics()["known"], 0)

    async def test_wrong_identity_never_adopts_success(self):
        async def work(w, line, h, b):
            await self.write(w, self.known(replace(self.r, response_id=str(uuid4())).payload()))

        c = await self.server(work)
        with self.assertRaises(NativeError) as caught:
            await c.begin_response(self.a)
        self.assertEqual(caught.exception.code, "acknowledgement_unknown")
        self.assertEqual(c.metrics()["known"], 0)

    async def test_valid_rejection_is_distinct_from_lost_write_and_read(self):
        requests = 0

        async def work(w, line, h, b):
            nonlocal requests
            requests += 1
            if requests == 1:
                await self.write(
                    w, {"schemaVersion": 1, "status": "rejected", "code": "forbidden"}, status=403
                )

        c = await self.server(work)
        for call, code in (
            (lambda: c.begin_response(self.a), "forbidden"),
            (lambda: c.begin_response(self.a), "acknowledgement_unknown"),
            (lambda: c.inspect_response(self.a.response_id), "dependency_unavailable"),
        ):
            with self.assertRaises(NativeError) as caught:
                await call()
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(c.metrics()["rejected"], 1)
        self.assertEqual(c.metrics()["unknown"], 2)

    async def test_duplicate_header_trailing_body_keepalive_and_bad_json_are_unknown(self):
        variants = [
            {"extra_head": b"Content-Length: 2\r\n"},
            {"extra_body": b"x"},
            {"connection": "keep-alive"},
        ]
        for variant in variants:

            async def work(w, line, h, b, selected=variant):
                await self.write(w, self.known(self.r.payload()), **selected)

            c = await self.server(work)
            with self.subTest(variant=variant), self.assertRaises(NativeError) as caught:
                await c.begin_response(self.a)
            self.assertEqual(caught.exception.code, "acknowledgement_unknown")

        async def malformed(w, line, h, b):
            raw = b'{"schemaVersion":1,"schemaVersion":1,"status":"known","result":{}}'
            w.write(
                f"HTTP/1.1 200 Result\r\nContent-Type: application/json\r\nContent-Length: {len(raw)}\r\nConnection: close\r\n\r\n".encode()
                + raw
            )
            await w.drain()

        c = await self.server(malformed)
        with self.assertRaises(NativeError) as caught:
            await c.begin_response(self.a)
        self.assertEqual(caught.exception.code, "acknowledgement_unknown")

    async def test_foreign_inspection_state_is_dependency_unavailable(self):
        raw = view(self.a, self.b, self.r).payload()
        raw["anchor"]["roomId"] = "foreign"

        async def work(w, line, h, b):
            await self.write(w, self.known(raw))

        c = await self.server(work)
        with self.assertRaises(NativeError) as caught:
            await c.inspect_response(self.a.response_id)
        self.assertEqual(caught.exception.code, "dependency_unavailable")

    async def test_inspection_wrong_bound_anchor_digest_is_unavailable_without_retry(self):
        raw = view(self.a, self.b, self.r).payload()
        raw["receipt"]["anchorDigest"] = "0" * 64
        calls = []

        async def work(w, line, h, body):
            calls.append(line)
            await self.write(w, self.known(raw))

        c = await self.server(work)
        with self.assertRaises(NativeError) as caught:
            await c.inspect_response(self.a.response_id)
        self.assertEqual(caught.exception.code, "dependency_unavailable")
        self.assertEqual(len(calls), 1)
        self.assertEqual(c.metrics()["known"], 0)

    async def test_waiter_cancel_retains_two_actual_calls_and_incomplete_close(self):
        entered = asyncio.Queue()
        release = asyncio.Event()
        self.releases.append(release)

        async def work(w, line, h, b):
            entered.put_nowait(True)
            await release.wait()
            await self.write(w, self.known(self.r.payload()))

        c = await self.server(work, timeout=0.5, cleanup=0.02)
        one = asyncio.create_task(c.begin_response(self.a))
        two = asyncio.create_task(c.begin_response(self.a))
        await entered.get()
        await entered.get()
        one.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await one
        self.assertEqual(c.metrics()["active"], 2)
        with self.assertRaises(NativeError) as caught:
            await c.begin_response(self.a)
        self.assertEqual(caught.exception.code, "capacity_exhausted")
        with self.assertRaises(NativeCleanupIncomplete):
            await c.aclose()
        self.assertEqual(c.metrics()["active"], 2)
        release.set()
        self.assertEqual(await two, self.r)
        await c.aclose()
        self.assertEqual(c.metrics()["active"], 0)
        with self.assertRaises(NativeError) as caught:
            await c.begin_response(self.a)
        self.assertEqual(caught.exception.code, "closed")

    async def test_anchor_is_snapshotted_before_network_wait(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        self.releases.append(release)
        original = self.a.response_id

        async def work(w, line, h, body):
            self.assertEqual(json.loads(body)["responseId"], original)
            entered.set()
            await release.wait()
            await self.write(w, self.known(self.r.payload()))

        c = await self.server(work)
        task = asyncio.create_task(c.begin_response(self.a))
        await entered.wait()
        object.__setattr__(self.a, "response_id", str(uuid4()))
        release.set()
        self.assertEqual((await task).response_id, original)

    async def test_sdk_and_browser_identity_are_snapshotted_before_network_wait(self):
        for value, method in (
            (sdk(self.a), "observe_sdk"),
            (BrowserObservation(str(uuid4()), self.a.response_id, "partial", 1), "observe_browser"),
        ):
            entered, release = asyncio.Event(), asyncio.Event()
            self.releases.append(release)
            original = value.event_id
            expected = observation(value)

            async def work(
                w,
                line,
                h,
                body,
                entered=entered,
                release=release,
                original=original,
                expected=expected,
            ):
                self.assertEqual(json.loads(body)["eventId"], original)
                entered.set()
                await release.wait()
                await self.write(w, self.known(expected.payload()))

            c = await self.server(work)
            task = asyncio.create_task(getattr(c, method)(value))
            await entered.wait()
            object.__setattr__(value, "event_id", str(uuid4()))
            release.set()
            with self.subTest(method=method):
                self.assertEqual((await task).event_id, original)


if __name__ == "__main__":
    unittest.main()
