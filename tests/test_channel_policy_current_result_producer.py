"""Public DTO joins and retained read ownership; no database, HTTP or providers."""

from __future__ import annotations

import asyncio
import copy
import gc
import hashlib
import json
import subprocess
import sys
import unittest
import warnings
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

from continuity_lab.delivery_api import DeliveryIntent, DeliveryReceipt, DeliverySnapshot
from continuity_lab.execution_api import AttemptResult, ExecutionObservation, IssuedAttempt
from continuity_lab.work_api import WorkPayload, WorkRecord, WorkScope
from delegation_reliability import (
    ChannelPolicyExecutionView,
    ChannelPolicyView,
    channel_policy_key,
    encode_channel_policy_request,
    encode_channel_policy_result,
    produce_channel_policy_request,
    produce_channel_policy_result,
)
from delegation_reliability.contracts import Attempt, Scope, canonical
from delegation_reliability.delivery_contract import DelegationDelivery
from delegation_reliability.fixed_policy_contracts import (
    parse_fixed_policy_result,
    produce_fixed_policy_request,
)
from delegation_reliability.security import EvidenceRecord
from services.channel_policy_demo import current_result_producer as m
from services.channel_policy_demo.current_result import encode_current_result_observation
from services.channel_policy_demo.discovery import DiscoveryItem, DiscoveryPage, DiscoveryScope
from services.channel_policy_demo.jobs import EvidenceCatalogue

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / "contracts/delegation/fixed-policy-v2.json").read_bytes())
T = 1900000000000
PRIVATE = "PRIVATE_CURRENT_RESULT_SENTINEL"


def encoded(value, *, sorted_keys=False):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=sorted_keys, separators=(",", ":")
    ).encode()


class Scenario:
    def __init__(self, count=1):
        self.binding = m.ProducerBinding(
            str(uuid4()),
            Scope("tenant_demo", "account_demo"),
            "case_demo",
            "conversation_demo",
            str(uuid4()),
            str(uuid4()),
            "recipient_demo",
        )
        self.items, self.frames, self.winners, self.views, self.deliveries, self.native = (
            [],
            {},
            {},
            {},
            {},
            {},
        )
        self.records = None
        self.events = []
        self.holds, self.errors, self.entered = {}, {}, {}
        self.owners = []
        self.now = T + 10
        for index in range(count):
            op, receipt, work, attempt = (str(uuid4()) for _ in range(4))
            source = "native" if index % 2 == 0 else "sms"
            wire = {
                "schemaVersion": 1,
                "kind": "investigation",
                "operationKey": op,
                "scope": {"tenantId": "tenant_demo", "accountId": "account_demo"},
                "caseId": "case_demo",
                "caseRevision": "1",
                "conversationId": "conversation_demo",
                "message": {
                    "receiptId": receipt,
                    "eventId": "event_" + str(index),
                    "messageId": "message_" + str(index),
                    "senderId": "sender_" + source,
                    "body": "Original café 🧭 " + str(index),
                },
            }
            payload = encoded(wire)
            self.frames[receipt] = encoded(
                {
                    "schemaVersion": 1,
                    "canonicalPayload": payload.decode(),
                    "payloadDigest": hashlib.sha256(payload).hexdigest(),
                }
            )
            inner = copy.deepcopy(FIXTURE["producer_input"])
            inner.update(delegation_id=channel_policy_key(op), deadline_at_ms=T + 60000)
            request = produce_channel_policy_request(
                {
                    "schema_version": 1,
                    "kind": "delegation.request",
                    "capability": "booking.evaluate_policy",
                    "input_schema_version": 3,
                    "origin": {
                        "kind": "p2.prepared_dispatch.v1",
                        "profile_id": self.binding.profile_id,
                        "operation_key": op,
                        "input_receipt_id": receipt,
                        "payload_sha256": hashlib.sha256(payload).hexdigest(),
                        "payload_byte_length": len(payload),
                    },
                    "request": produce_fixed_policy_request(inner).to_wire(),
                }
            )
            self.records = tuple(
                EvidenceRecord(request.scope, ref, body.encode())
                for ref, body in zip(
                    request.request.evidence,
                    (FIXTURE["policy_body_utf8"], FIXTURE["facts_body_utf8"]),
                    strict=True,
                )
            )
            record = WorkRecord(
                work,
                WorkScope("tenant_demo", "account_demo"),
                channel_policy_key(op),
                WorkPayload(
                    "booking.evaluate_policy",
                    encode_channel_policy_request(request),
                    request.deadline_at_ms,
                ),
                T - 1,
                False,
            )
            self.winners[work] = ChannelPolicyView(record, request)
            grant = IssuedAttempt(
                record, attempt, "command_" + str(index), 1, self.binding.owner_id, 1, T, T + 10000
            )
            transport = replace(
                request,
                request=replace(
                    request.request, attempt=Attempt("attempt_" + UUID(attempt).hex, 1)
                ),
            )
            result = parse_fixed_policy_result(canonical(FIXTURE["result"]))
            result = replace(
                result,
                delegation_id=request.delegation_id,
                input_fingerprint=request.request.input_fingerprint,
                attempt_id=transport.attempt.attempt_id,
                completed_at_ms=T + 1,
            )
            outer = produce_channel_policy_result(transport, result)
            body = encode_channel_policy_result(outer)
            recorded = AttemptResult(work, attempt, body, T + 2, "eligible_at_commit")
            self.views[work] = ChannelPolicyExecutionView(
                ExecutionObservation(record, grant, recorded, 1, "result_recorded"),
                request,
                outer,
                "candidate",
            )
            intent = DeliveryIntent(
                str(uuid4()),
                record.scope,
                work,
                attempt,
                recorded.sha256,
                self.binding.receiver_id,
                self.binding.recipient_id,
                body,
                T + 3,
            )
            accepted = DeliveryReceipt(
                intent.delivery_id,
                str(uuid4()),
                intent.receiver_id,
                intent.recipient_id,
                intent.result_sha256,
                T + 4,
            )
            self.deliveries[work] = DelegationDelivery(
                DeliverySnapshot(intent, True, accepted), "accepted"
            )
            self.native[intent.delivery_id] = {
                "schemaVersion": 1,
                "intent": json.loads(intent.canonical()),
                "receipt": {
                    "delivery_id": accepted.delivery_id,
                    "receipt_id": accepted.receipt_id,
                    "receiver_id": accepted.receiver_id,
                    "recipient_id": accepted.recipient_id,
                    "result_sha256": accepted.result_sha256,
                    "accepted_at_ms": accepted.accepted_at_ms,
                },
                "case": self.case(),
                "observed": {
                    "p2ObservedAt": "2026-11-13T01:00:00.001Z",
                    "caseObservedAt": "2026-11-13T01:00:00.002Z",
                    "disclosureAdmittedAt": "2026-11-13T01:00:00.003Z",
                    "atomic": False,
                },
            }
            self.items.append(
                DiscoveryItem(receipt, op, str(index + 1), source, "dispatched", True, work)
            )
        self.page = DiscoveryPage(
            self.binding.profile_id,
            DiscoveryScope("tenant_demo", "account_demo"),
            "case_demo",
            "conversation_demo",
            "2026-11-13T00:00:00.000Z",
            tuple(self.items),
            False,
            None,
        )

    def case(self):
        return {
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
            "workflow": {"taskId": str(uuid4()), "state": "ready", "version": "0"},
            "intent": {"state": "not_committed", "intentId": None},
            "mutation": {
                "state": "not_observed",
                "outcome": "not_observed",
                "cancellation": "not_observed",
                "effectId": None,
                "outcomeEventId": None,
            },
            "supplierResult": None,
            "sourceRevision": "f" * 64,
        }

    async def stage(self, name):
        self.events.append(name)
        self.entered.setdefault(name, asyncio.Event()).set()
        if name in self.holds:
            await self.holds[name].wait()
        if name in self.errors:
            raise self.errors[name]

    def pending(self, index):
        work = self.items[index].external_receipt_id
        view = self.views[work]
        self.views[work] = replace(
            view,
            execution=ExecutionObservation(view.execution.record, None, None, 0, "accepted"),
            result=None,
            applicability="missing",
        )

    def producer(self, **kwargs):
        return m.CurrentResultProducer(
            binding=self.binding,
            discovery=Discovery(self),
            prepared=Prepared(self),
            stored=Stored(self),
            inspections=Factory(self),
            native=Native(self),
            evidence=EvidenceCatalogue((self.records,)),
            **kwargs,
        )


class Discovery:
    def __init__(self, s):
        self.s = s

    async def read(self):
        await self.s.stage("discovery")
        return self.s.page


class Prepared:
    def __init__(self, s):
        self.s = s

    async def read(self, *, source_binding_id, receipt_id):
        await self.s.stage("prepared:" + receipt_id)
        expected = next(
            item.source_binding_id for item in self.s.page.items if item.receipt_id == receipt_id
        )
        assert source_binding_id == expected
        return self.s.frames[receipt_id]


class Stored:
    def __init__(self, s):
        self.s = s

    async def get(self, work_id):
        await self.s.stage("stored:" + work_id)
        return self.s.winners[work_id]


class Factory:
    def __init__(self, s):
        self.s = s

    async def open_inspection(self, *, work_id, owner_id, request):
        await self.s.stage("factory:" + work_id)
        assert owner_id == self.s.binding.owner_id and request == self.s.winners[work_id].request
        owner = Inspection(self.s, work_id)
        self.s.owners.append(owner)
        return owner


class Inspection:
    def __init__(self, s, work):
        self.s, self.work = s, work
        self.pending_count = 0
        self.result_calls = self.close_calls = 0

    async def inspect_result(self):
        self.pending_count += 1
        try:
            self.result_calls += 1
            await self.s.stage("result:" + str(self.result_calls))
            values = self.s.views[self.work]
            return values[self.result_calls - 1] if isinstance(values, list) else values
        finally:
            self.pending_count -= 1

    async def inspect_delivery(self):
        self.pending_count += 1
        try:
            await self.s.stage("delivery")
            return self.s.deliveries[self.work]
        finally:
            self.pending_count -= 1

    async def close(self):
        self.close_calls += 1
        await self.s.stage("close")


class Native:
    def __init__(self, s):
        self.s = s

    async def read(self, *, delivery_id):
        await self.s.stage("native")
        value = self.s.native[delivery_id]
        return encoded(value, sorted_keys=True) if isinstance(value, dict) else value


class ProducerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.s = Scenario()
        self.clock = patch.object(m, "time", SimpleNamespace(time_ns=lambda: self.s.now * 1000000))
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.p = self.s.producer()
        self.addAsyncCleanup(self.p.close)

    async def assert_code(self, code, p=None):
        with self.assertRaises(m.CurrentResultProducerError) as caught:
            await (p or self.p).read()
        self.assertEqual((caught.exception.code, caught.exception.args), (code, (code,)))
        self.assertNotIn(PRIVATE, str(caught.exception))

    async def test_current_joins_original_source_fact_result_and_actual_receipts(self):
        value = await self.p.read()
        self.assertEqual(value.state, "current")
        work = self.s.items[0].external_receipt_id
        expected = self.s.deliveries[work].snapshot
        self.assertEqual(value.result.intent.body, json.loads(expected.intent.canonical())["body"])
        self.assertEqual(value.result.receipt.receipt_id, expected.receipt.receipt_id)
        self.assertEqual(value.result.input_receipt_id, self.s.items[0].receipt_id)
        self.assertEqual(self.s.events.count("native"), 1)
        self.assertEqual(self.s.owners[0].result_calls, 2)
        self.assertEqual(self.s.owners[0].close_calls, 1)
        self.assertEqual(self.p.metrics()["inspection_owned"], 0)

    async def test_newer_sms_pending_result_allows_original_native_current(self):
        self.s = Scenario(2)
        self.s.pending(1)
        self.p = self.s.producer()
        self.addAsyncCleanup(self.p.close)
        value = await self.p.read()
        self.assertEqual(value.state, "current")
        self.assertEqual(value.result.input_receipt_id, self.s.items[0].receipt_id)
        self.assertEqual(len(self.s.owners), 2)
        self.assertTrue(all(owner.close_calls == 1 for owner in self.s.owners))

    async def test_latest_sms_result_is_selected_instead_of_older_native(self):
        self.s = Scenario(2)
        self.p = self.s.producer()
        self.addAsyncCleanup(self.p.close)
        value = await self.p.read()
        self.assertEqual(value.result.input_receipt_id, self.s.items[1].receipt_id)
        self.assertEqual(len(self.s.owners), 1)

    async def test_latest_recorded_expired_never_falls_back_to_older(self):
        self.s = Scenario(2)
        work = self.s.items[1].external_receipt_id
        self.s.views[work] = replace(self.s.views[work], applicability="expired")
        self.p = self.s.producer()
        self.addAsyncCleanup(self.p.close)
        value = await self.p.read()
        self.assertEqual((value.state, value.result), ("not_applicable", None))
        self.assertEqual(len(self.s.owners), 1)
        self.assertNotIn("native", self.s.events)

    async def test_latest_recorded_undelivered_never_falls_back_to_older(self):
        self.s = Scenario(2)
        work = self.s.items[1].external_receipt_id
        self.s.deliveries[work] = DelegationDelivery(DeliverySnapshot(None, False, None), "missing")
        self.p = self.s.producer()
        self.addAsyncCleanup(self.p.close)
        value = await self.p.read()
        self.assertEqual((value.state, value.result), ("no_delivery", None))
        self.assertEqual(len(self.s.owners), 1)
        self.assertNotIn("native", self.s.events)

    async def test_unprepared_pending_gap_does_not_become_ack_or_hide_older(self):
        self.s = Scenario(2)
        item = self.s.items[1]
        self.s.page = replace(
            self.s.page,
            items=(
                self.s.items[0],
                replace(item, state="pending", possible_external=False, external_receipt_id=None),
            ),
        )
        self.s.frames[item.receipt_id] = None
        self.p = self.s.producer()
        self.addAsyncCleanup(self.p.close)
        self.assertEqual((await self.p.read()).state, "current")
        self.assertIn("prepared:" + item.receipt_id, self.s.events)

    async def test_discovery_scope_and_overflow_fail_before_any_owned_inspection(self):
        for page, code in [(replace(self.s.page, profile_id=str(uuid4())), "unauthorized")]:
            self.s.page = page
            await self.assert_code(code)
            self.assertEqual(self.s.owners, [])
        self.s = Scenario(16)
        self.s.page = replace(self.s.page, overflow=True, next_cursor="16")
        self.p = self.s.producer()
        self.addAsyncCleanup(self.p.close)
        await self.assert_code("overflow")
        self.assertEqual(self.s.owners, [])

    async def test_dispatched_absence_is_failure_then_honest_source_progresses(self):
        receipt = self.s.items[0].receipt_id
        raw = self.s.frames[receipt]
        self.s.frames[receipt] = None
        await self.assert_code("invalid_stored_state")
        self.s.frames[receipt] = raw
        self.assertEqual((await self.p.read()).state, "current")

    async def test_coordinated_origin_forgeries_still_fail_original_prepared_join(self):
        item = self.s.items[0]
        work = item.external_receipt_id
        original = self.s.winners[work]
        for field, value in [
            ("input_receipt_id", str(uuid4())),
            ("operation_key", str(uuid4())),
            ("payload_sha256", "0" * 64),
            ("payload_byte_length", 1),
            ("profile_id", str(uuid4())),
        ]:
            with self.subTest(field=field):
                request = replace(
                    original.request, origin=replace(original.request.origin, **{field: value})
                )
                wire = request.to_wire()
                wire.pop("input_fingerprint")
                if field == "operation_key":
                    inner = wire["request"]
                    inner.pop("input_fingerprint")
                    inner["delegation_id"] = channel_policy_key(value)
                    wire["request"] = produce_fixed_policy_request(inner).to_wire()
                request = produce_channel_policy_request(wire)
                record = replace(
                    original.record,
                    payload=WorkPayload(
                        "booking.evaluate_policy",
                        encode_channel_policy_request(request),
                        request.deadline_at_ms,
                    ),
                )
                self.s.winners[work] = ChannelPolicyView(record, request)
                await self.assert_code("identity_conflict")
        self.s.winners[work] = original
        self.assertEqual((await self.p.read()).state, "current")

    async def test_changed_stored_work_key_body_deadline_and_uuid_are_rejected(self):
        work = self.s.items[0].external_receipt_id
        original = self.s.winners[work]
        for record in [
            replace(original.record, work_id=str(uuid4())),
            replace(original.record, idempotency_key="other"),
            replace(
                original.record,
                payload=WorkPayload(
                    "booking.evaluate_policy",
                    original.record.payload.body,
                    original.request.deadline_at_ms + 1,
                ),
            ),
        ]:
            self.s.winners[work] = ChannelPolicyView(record, original.request)
            await self.assert_code("invalid_stored_state")
        self.s.winners[work] = original
        self.assertEqual((await self.p.read()).state, "current")

    async def test_coordinated_result_body_and_reported_result_cannot_forge_facts(self):
        work = self.s.items[0].external_receipt_id
        view = self.s.views[work]
        fact = replace(view.result.result.fact_refs[0], days_before_arrival=14)
        result = replace(view.result, result=replace(view.result.result, fact_refs=(fact,)))
        recorded = replace(view.execution.result, body=encode_channel_policy_result(result))
        self.s.views[work] = replace(
            view, result=result, execution=replace(view.execution, result=recorded)
        )
        await self.assert_code("unavailable")
        self.assertNotIn("delivery", self.s.events)
        self.s.views[work] = view
        self.assertEqual((await self.p.read()).state, "current")

    async def test_delivery_route_swap_fails_before_native_disclosure(self):
        work = self.s.items[0].external_receipt_id
        original = self.s.deliveries[work]
        for field, value in [
            ("receiver_id", str(uuid4())),
            ("recipient_id", "other_recipient"),
            ("attempt_id", str(uuid4())),
        ]:
            intent = replace(original.snapshot.intent, **{field: value})
            self.s.deliveries[work] = DelegationDelivery(
                DeliverySnapshot(intent, False, None), "prepared"
            )
            await self.assert_code("identity_conflict")
        self.assertNotIn("native", self.s.events)
        self.s.deliveries[work] = original
        self.assertEqual((await self.p.read()).state, "current")

    async def test_native_current_case_change_suppresses_body(self):
        native = next(iter(self.s.native.values()))
        native["case"]["revision"] = "2"
        value = await self.p.read()
        self.assertEqual((value.state, value.result), ("not_applicable", None))
        self.assertNotIn("body", encode_current_result_observation(value).decode())

    async def test_native_cancelled_case_suppresses_body_despite_historical_receipt(self):
        native = next(iter(self.s.native.values()))
        native["case"]["workflow"]["state"] = "cancelled"
        value = await self.p.read()
        self.assertEqual((value.state, value.result), ("not_applicable", None))

    async def test_wrong_loop_fails_before_read_or_owner_mutation(self):
        await self.p.read()
        before = dict(self.p.metrics())
        events = list(self.s.events)

        async def elsewhere():
            try:
                await self.p.read()
            except m.CurrentResultProducerError as error:
                return error.code
            return "unexpected"

        code = await asyncio.to_thread(lambda: asyncio.run(elsewhere()))
        self.assertEqual(code, "invalid_input")
        self.assertEqual(dict(self.p.metrics()), before)
        self.assertEqual(self.s.events, events)

    async def test_native_timeout_retains_call_and_never_starts_later_observation(self):
        self.p = self.s.producer(timeout_s=0.01, cleanup_timeout_s=0.01)
        self.addAsyncCleanup(self.p.close)
        release = asyncio.Event()
        self.s.holds["native"] = release
        await self.assert_code("deadline_exceeded")
        await self.assert_code("capacity")
        self.assertEqual(self.s.owners[0].result_calls, 1)
        release.set()
        while self.p.metrics()["scan_active"]:
            await asyncio.sleep(0)
        self.assertEqual((self.s.owners[0].result_calls, self.s.owners[0].close_calls), (1, 1))
        self.assertEqual(self.p.metrics()["inspection_owned"], 0)
        fresh = self.s.producer()
        self.addAsyncCleanup(fresh.close)
        self.assertEqual((await fresh.read()).state, "current")

    async def test_successful_close_with_pending_actual_owner_retains_slot_until_zero(self):
        original = Inspection.close

        async def pending_close(owner):
            await original(owner)
            owner.pending_count = 1

        with patch.object(Inspection, "close", pending_close):
            await self.assert_code("cleanup_incomplete")
        owner = self.s.owners[0]
        self.assertEqual((owner.close_calls, self.p.metrics()["inspection_owned"]), (1, 1))
        await self.assert_code("capacity")
        owner.pending_count = 0
        await self.p.close()
        self.assertEqual((owner.close_calls, self.p.metrics()["inspection_owned"]), (1, 0))

    async def test_full_native_case_shape_scope_and_intent_receipt_are_validated(self):
        delivery = next(iter(self.s.native))
        original = copy.deepcopy(self.s.native[delivery])
        mutations = [
            lambda n: n["case"]["scope"].update(accountId="foreign"),
            lambda n: n["case"].update(source="standalone_reference_v1"),
            lambda n: n["case"]["request"].update(investigationConsent=False),
            lambda n: n["case"]["mutation"].update(state="invented"),
            lambda n: n["receipt"].update(receipt_id=str(uuid4())),
            lambda n: n["intent"].update(work_id=str(uuid4())),
        ]
        for mutate in mutations:
            n = copy.deepcopy(original)
            mutate(n)
            self.s.native[delivery] = n
            with self.assertRaises(m.CurrentResultProducerError):
                await self.p.read()
        self.s.native[delivery] = original
        self.assertEqual((await self.p.read()).state, "current")

    async def test_unknown_native_wire_failure_never_becomes_absence(self):
        delivery = next(iter(self.s.native))
        original = self.s.native[delivery]
        for raw in [
            b"null",
            b'{"schemaVersion":1,"schemaVersion":1}',
            b"NaN",
            b"\xff",
            b"x" * 32769,
        ]:
            self.s.native[delivery] = raw
            with self.assertRaises(m.CurrentResultProducerError):
                await self.p.read()
        self.s.native[delivery] = None
        self.assertEqual((await self.p.read()).state, "no_delivery")
        self.s.native[delivery] = original
        self.assertEqual((await self.p.read()).state, "current")

    async def test_fresh_post_read_applicability_suppresses_stale_body(self):
        work = self.s.items[0].external_receipt_id
        view = self.s.views[work]
        for state in ["expired", "outdated", "case_cancelled", "execution_ineligible"]:
            self.s.views[work] = [view, replace(view, applicability=state)]
            value = await self.p.read()
            self.assertEqual((value.state, value.result), ("not_applicable", None))
        self.s.views[work] = view
        self.assertEqual((await self.p.read()).state, "current")

    async def test_post_read_result_or_delivery_identity_change_is_not_empty(self):
        work = self.s.items[0].external_receipt_id
        view = self.s.views[work]
        changed = replace(view.execution.result, recorded_at_ms=T + 8)
        self.s.views[work] = [
            view,
            replace(view, execution=replace(view.execution, result=changed)),
        ]
        await self.assert_code("invalid_stored_state")
        self.s.views[work] = view
        self.assertEqual((await self.p.read()).state, "current")

    async def test_unavailable_public_applicability_and_operational_failure_are_errors(self):
        work = self.s.items[0].external_receipt_id
        view = self.s.views[work]
        self.s.views[work] = replace(view, applicability="unavailable")
        await self.assert_code("unavailable")
        self.s.views[work] = view
        self.s.errors["native"] = RuntimeError(PRIVATE)
        await self.assert_code("unavailable")
        del self.s.errors["native"]
        self.assertEqual((await self.p.read()).state, "current")

    async def test_error_getter_and_private_args_never_escape_and_telemetry_is_optional(self):
        class Hostile(RuntimeError):
            @property
            def code(self):
                raise RuntimeError(PRIVATE)

        self.s.errors["discovery"] = Hostile(PRIVATE)
        await self.assert_code("unavailable")
        del self.s.errors["discovery"]
        with patch.object(m.LOGGER, "info", side_effect=RuntimeError(PRIVATE)):
            self.assertEqual((await self.p.read()).state, "current")

    async def test_cancelled_discovery_retains_capacity_and_starts_no_later_stage(self):
        release = asyncio.Event()
        self.s.holds["discovery"] = release
        task = asyncio.create_task(self.p.read())
        while "discovery" not in self.s.entered:
            await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await self.assert_code("capacity")
        release.set()
        while self.p.metrics()["scan_active"]:
            await asyncio.sleep(0)
        self.assertEqual(self.s.owners, [])
        self.assertEqual((await self.p.read()).state, "current")

    async def test_late_factory_return_after_timeout_is_adopted_closed_and_never_read(self):
        self.p = self.s.producer(timeout_s=0.01, cleanup_timeout_s=0.01)
        self.addAsyncCleanup(self.p.close)
        work = self.s.items[0].external_receipt_id
        release = asyncio.Event()
        self.s.holds["factory:" + work] = release
        await self.assert_code("deadline_exceeded")
        await self.assert_code("capacity")
        release.set()
        while self.p.metrics()["scan_active"]:
            await asyncio.sleep(0)
        self.assertEqual(
            (len(self.s.owners), self.s.owners[0].result_calls, self.s.owners[0].close_calls),
            (1, 0, 1),
        )
        self.assertEqual(self.p.metrics()["inspection_owned"], 0)
        fresh = self.s.producer()
        self.addAsyncCleanup(fresh.close)
        self.assertEqual((await fresh.read()).state, "current")

    async def test_held_result_keeps_owner_during_incomplete_close_until_actual_settlement(self):
        self.p = self.s.producer(timeout_s=0.01, cleanup_timeout_s=0.01)
        self.addAsyncCleanup(self.p.close)
        release = asyncio.Event()
        self.s.holds["result:1"] = release
        await self.assert_code("deadline_exceeded")
        with self.assertRaisesRegex(m.CurrentResultProducerError, "cleanup_incomplete"):
            await self.p.close()
        self.assertEqual(self.p.metrics()["inspection_owned"], 1)
        self.assertEqual(self.s.owners[0].pending_count, 1)
        release.set()
        while self.p.metrics()["scan_active"]:
            await asyncio.sleep(0)
        await self.p.close()
        self.assertEqual(self.p.metrics()["inspection_owned"], 0)
        fresh = self.s.producer()
        self.addAsyncCleanup(fresh.close)
        self.assertEqual((await fresh.read()).state, "current")

    async def test_failed_close_retains_slot_and_useful_explicit_retry_drains(self):
        self.s.errors["close"] = RuntimeError(PRIVATE)
        await self.assert_code("cleanup_incomplete")
        self.assertEqual(self.p.metrics()["inspection_owned"], 1)
        await self.assert_code("capacity")
        del self.s.errors["close"]
        await self.p.close()
        self.assertEqual(self.p.metrics()["inspection_owned"], 0)
        fresh = self.s.producer()
        self.addAsyncCleanup(fresh.close)
        self.assertEqual((await fresh.read()).state, "current")

    async def test_expiry_while_close_is_held_suppresses_prepared_current_output(self):
        release = asyncio.Event()
        self.s.holds["close"] = release
        task = asyncio.create_task(self.p.read())
        while "close" not in self.s.entered:
            await asyncio.sleep(0)
        self.s.now = T + 60000
        release.set()
        value = await task
        self.assertEqual((value.state, value.result), ("not_applicable", None))

    async def test_eager_reentrant_read_observes_one_reserved_actual_scan(self):
        scenario = self.s
        seen = []

        class Reentrant(Discovery):
            once = True

            async def read(reader):
                seen.append(dict(p.metrics()))
                if reader.once:
                    reader.once = False
                    try:
                        await p.read()
                    except m.CurrentResultProducerError as error:
                        seen.append(error.code)
                    else:
                        seen.append("incorrectly_admitted")
                return await super().read()

        p = m.CurrentResultProducer(
            binding=scenario.binding,
            discovery=Reentrant(scenario),
            prepared=Prepared(scenario),
            stored=Stored(scenario),
            inspections=Factory(scenario),
            native=Native(scenario),
            evidence=EvidenceCatalogue((scenario.records,)),
        )
        self.addAsyncCleanup(p.close)
        loop = asyncio.get_running_loop()
        prior = loop.get_task_factory()
        loop.set_task_factory(asyncio.eager_task_factory)
        try:
            value = await p.read()
        finally:
            loop.set_task_factory(prior)
        self.assertEqual(value.state, "current")
        self.assertEqual((seen[0]["scan_active"], seen[1]), (1, "capacity"))
        self.assertEqual((p.metrics()["scans_started"], len(scenario.owners)), (1, 1))
        self.assertEqual((await p.read()).state, "current")

    async def test_eager_reentrant_close_waits_for_task_publication_and_actual_scan(self):
        scenario = self.s
        entered, release = asyncio.Event(), asyncio.Event()
        close_tasks = []

        class Reentrant(Discovery):
            async def read(reader):
                close_tasks.append(asyncio.create_task(p.close()))
                entered.set()
                await release.wait()
                return scenario.page

        p = m.CurrentResultProducer(
            binding=scenario.binding,
            discovery=Reentrant(scenario),
            prepared=Prepared(scenario),
            stored=Stored(scenario),
            inspections=Factory(scenario),
            native=Native(scenario),
            evidence=EvidenceCatalogue((scenario.records,)),
            cleanup_timeout_s=0.1,
        )
        self.addAsyncCleanup(p.close)
        loop = asyncio.get_running_loop()
        prior = loop.get_task_factory()
        loop.set_task_factory(asyncio.eager_task_factory)
        read = None
        try:
            read = asyncio.create_task(p.read())
            await entered.wait()
            self.assertFalse(close_tasks[0].done())
            self.assertEqual(p.metrics()["scan_active"], 1)
            release.set()
            with self.assertRaisesRegex(m.CurrentResultProducerError, "request_aborted"):
                await read
            await close_tasks[0]
        finally:
            release.set()
            loop.set_task_factory(prior)
            if read is not None:
                await asyncio.gather(read, return_exceptions=True)
            await asyncio.gather(*close_tasks, return_exceptions=True)
        self.assertEqual((p.metrics()["scan_active"], len(scenario.owners)), (0, 0))

    async def test_publication_future_allocation_failure_is_finite_before_owner_admission(self):
        loop = asyncio.get_running_loop()
        with patch.object(loop, "create_future", side_effect=RuntimeError(PRIVATE)):
            await self.assert_code("unavailable")
        with (
            patch.object(loop, "create_future", side_effect=asyncio.CancelledError),
            self.assertRaises(asyncio.CancelledError),
        ):
            await self.p.read()
        self.assertEqual((self.p.metrics()["scan_active"], self.s.events), (0, []))
        self.assertEqual((await self.p.read()).state, "current")

    async def test_ordinary_scan_allocation_failure_rolls_back_publication_before_fresh_read(self):
        actions = []

        def denied(action):
            actions.append(action)
            raise RuntimeError(PRIVATE)

        with warnings.catch_warnings(record=True) as seen:
            warnings.simplefilter("always")
            with patch.object(m.asyncio, "create_task", side_effect=denied):
                await self.assert_code("unavailable")
            gc.collect()
        self.assertIsNone(actions[0].cr_frame)
        self.assertFalse([w for w in seen if issubclass(w.category, RuntimeWarning)])
        self.assertEqual(
            (self.p.metrics()["scan_active"], self.p.metrics()["scans_started"]), (0, 0)
        )
        self.assertEqual((await self.p.read()).state, "current")

    async def test_cancelled_task_allocation_closes_coroutine_before_fresh_progress(self):
        actions = []

        def denied(action):
            actions.append(action)
            raise asyncio.CancelledError

        with warnings.catch_warnings(record=True) as seen:
            warnings.simplefilter("always")
            with (
                patch.object(m.asyncio, "create_task", side_effect=denied),
                self.assertRaises(asyncio.CancelledError),
            ):
                await self.p.read()
            gc.collect()
        self.assertIsNone(actions[0].cr_frame)
        self.assertFalse([w for w in seen if issubclass(w.category, RuntimeWarning)])
        self.assertEqual(self.p.metrics()["scan_active"], 0)
        self.assertEqual((await self.p.read()).state, "current")

    async def test_method_getters_are_never_called_and_snapshots_ignore_replacement(self):
        calls = []

        class Hostile:
            @property
            def read(self):
                calls.append(1)
                raise RuntimeError(PRIVATE)

        with self.assertRaisesRegex(m.CurrentResultProducerError, "invalid_input"):
            m.CurrentResultProducer(
                binding=self.s.binding,
                discovery=Hostile(),
                prepared=Prepared(self.s),
                stored=Stored(self.s),
                inspections=Factory(self.s),
                native=Native(self.s),
                evidence=EvidenceCatalogue((self.s.records,)),
            )
        self.assertEqual(calls, [])
        discovery = Discovery(self.s)
        p = m.CurrentResultProducer(
            binding=self.s.binding,
            discovery=discovery,
            prepared=Prepared(self.s),
            stored=Stored(self.s),
            inspections=Factory(self.s),
            native=Native(self.s),
            evidence=EvidenceCatalogue((self.s.records,)),
        )
        self.addAsyncCleanup(p.close)
        discovery.read = lambda: (_ for _ in ()).throw(RuntimeError(PRIVATE))
        self.assertEqual((await p.read()).state, "current")

    async def test_fresh_malformed_factory_resource_is_closed_without_calling_getter(self):
        scenario = self.s
        calls = []

        class Broken:
            pending_count = 0
            close_calls = 0

            @property
            def inspect_result(self):
                calls.append("getter")
                raise RuntimeError(PRIVATE)

            async def inspect_delivery(self):
                raise AssertionError("not_admitted")

            async def close(self):
                self.close_calls += 1

        class Returning(Factory):
            async def open_inspection(self, **kwargs):
                if self.bad:
                    return self.bad
                return await super().open_inspection(**kwargs)

        factory = Returning(scenario)
        resource = factory.bad = Broken()
        p = m.CurrentResultProducer(
            binding=scenario.binding,
            discovery=Discovery(scenario),
            prepared=Prepared(scenario),
            stored=Stored(scenario),
            inspections=factory,
            native=Native(scenario),
            evidence=EvidenceCatalogue((scenario.records,)),
        )
        self.addAsyncCleanup(p.close)
        await self.assert_code("invalid_input", p)
        self.assertEqual((calls, resource.close_calls, p.metrics()["inspection_owned"]), ([], 1, 0))
        factory.bad = None
        self.assertEqual((await p.read()).state, "current")

    async def test_factory_cannot_transfer_a_borrowed_source_reader(self):
        scenario = self.s
        discovery = Discovery(scenario)

        class Returning(Factory):
            async def open_inspection(self, **kwargs):
                if self.alias is not None:
                    return self.alias
                return await super().open_inspection(**kwargs)

        factory = Returning(scenario)
        factory.alias = discovery
        p = m.CurrentResultProducer(
            binding=scenario.binding,
            discovery=discovery,
            prepared=Prepared(scenario),
            stored=Stored(scenario),
            inspections=factory,
            native=Native(scenario),
            evidence=EvidenceCatalogue((scenario.records,)),
        )
        self.addAsyncCleanup(p.close)
        await self.assert_code("invalid_stored_state", p)
        self.assertEqual(p.metrics()["inspection_owned"], 0)
        factory.alias = None
        self.assertEqual((await p.read()).state, "current")

    async def test_budgets_are_finite_before_io_and_binding_is_immutable(self):
        for value in [True, 10**1000, float("nan"), float("inf"), 0, 6]:
            for key in ["timeout_s", "cleanup_timeout_s"]:
                with self.assertRaisesRegex(m.CurrentResultProducerError, "invalid_input"):
                    self.s.producer(**{key: value})
        self.assertEqual(self.s.events, [])
        with self.assertRaisesRegex(m.CurrentResultProducerError, "invalid_input"):
            replace(self.s.binding, owner_id=str(uuid4()).upper())

    async def test_empty_complete_discovery_returns_no_delivery_without_allocating_owners(self):
        self.s.page = replace(self.s.page, items=())
        value = await self.p.read()
        self.assertEqual((value.state, value.result), ("no_delivery", None))
        self.assertEqual(self.s.owners, [])


class InertTests(unittest.TestCase):
    def test_import_has_no_io_or_native_sdk_import(self):
        code = "import sys;from unittest.mock import patch;\nwith patch('socket.socket',side_effect=AssertionError('socket')),patch('subprocess.Popen',side_effect=AssertionError('process')):import services.channel_policy_demo.current_result_producer\nassert 'livekit.agents' not in sys.modules"
        result = subprocess.run(
            [sys.executable, "-B", "-c", code],
            check=False,
            cwd=ROOT,
            capture_output=True,
            timeout=5,
        )
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))
