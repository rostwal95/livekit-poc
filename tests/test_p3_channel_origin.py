"""Application origin binding through real public P3 facades and fake P1 ports.

These offline tests do not qualify PostgreSQL, HTTP, RTC or provider inference.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import subprocess
import sys
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from continuity_lab.work_api import (
    WorkError,
    WorkRecord,
    WorkScope,
    WorkSubmission,
)
from delegation_reliability import (
    ChannelPolicyCoordinator,
    CoordinatorError,
    encode_channel_policy_request,
    parse_channel_policy_request,
)
from delegation_reliability.contracts import Scope
from delegation_reliability.coordinator import CaseSnapshot
from delegation_reliability.fixed_policy_contracts import produce_fixed_policy_request
from services.channel_policy_demo import origin as m
from services.channel_policy_demo import wire

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / "contracts/delegation/channel-policy-v3.json").read_bytes())


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def frame(submission):
    payload = encoded(submission)
    return encoded(
        {
            "schemaVersion": 1,
            "canonicalPayload": payload.decode(),
            "payloadDigest": hashlib.sha256(payload).hexdigest(),
        }
    )


class Ledger:
    def __init__(self):
        self.records = {}
        self.lock = asyncio.Lock()
        self.race = False
        self.misses = 0
        self.both_missed = asyncio.Event()


class WorkPort:
    """Credential-scoped fake public port; held I/O settles only on explicit release."""

    def __init__(self, scope, ledger=None):
        self.scope = WorkScope(scope.tenant_id, scope.account_id)
        self.ledger = Ledger() if ledger is None else ledger
        self.finds = 0
        self.submits = 0
        self.closed = 0
        self.entered = asyncio.Event()
        self.settled = asyncio.Event()
        self.release = None
        self.ack_loss = False
        self.submit_error = None
        self.reconcile_error = None
        self.pending_count = 0

    async def find(self, *, idempotency_key):
        self.finds += 1
        if self.finds > 1 and self.reconcile_error is not None:
            raise self.reconcile_error
        value = self.ledger.records.get(idempotency_key)
        if value is None and self.ledger.race:
            self.ledger.misses += 1
            if self.ledger.misses == 2:
                self.ledger.both_missed.set()
            await self.ledger.both_missed.wait()
        return value

    async def submit(self, *, idempotency_key, payload):
        self.submits += 1
        self.pending_count += 1
        self.entered.set()
        try:
            if self.release is not None:
                await self.release.wait()
            if self.submit_error is not None:
                raise self.submit_error
            async with self.ledger.lock:
                old = self.ledger.records.get(idempotency_key)
                if old is not None:
                    if old.payload != payload:
                        raise WorkError("identity_conflict")
                    return WorkSubmission(old, False)
                value = WorkRecord(
                    str(uuid4()),
                    self.scope,
                    idempotency_key,
                    payload,
                    time.time_ns() // 1000000,
                    False,
                )
                self.ledger.records[idempotency_key] = value
                if self.ack_loss:
                    raise WorkError("acknowledgement_unknown")
                return WorkSubmission(value, True)
        finally:
            self.pending_count -= 1
            self.settled.set()

    async def get(self, *, work_id):
        raise AssertionError("application never gets by a caller-selected UUID")

    async def cancel(self, *, work_id, command_id):
        raise AssertionError("application has no business-cancel authority")

    async def close(self):
        self.closed += 1


class Cases:
    def __init__(self, scope, case_id, revision):
        self.current = CaseSnapshot(
            Scope(scope.tenant_id, scope.account_id), case_id, revision, False
        )
        self.calls = 0

    async def snapshot(self, *, case_id):
        self.calls += 1
        return self.current


class ChannelOriginTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.owners = []
        self.ports = []
        self.cases = []

    async def asyncTearDown(self):
        for port in self.ports:
            if port.release is not None:
                port.release.set()
        for owner in self.owners:
            await owner.close()

    def build(self, index=0, *, ledger=None, profile=None, version=None, **options):
        case = FIXTURE["channel_cases"][index]
        policy = copy.deepcopy(case["producer_input"]["request"])
        policy.pop("input_fingerprint")
        if version is not None:
            policy["evidence"][0]["version"] = version
        template = produce_fixed_policy_request(policy)
        source = FIXTURE["p2_cases"][index]
        submission = source["submission"]
        binding = m.ChannelOriginBinding(
            FIXTURE["profile_id"] if profile is None else profile,
            template.scope,
            template.case_id,
            template.conversation_id,
            submission["message"]["senderId"],
        )
        port = WorkPort(template.scope, ledger)
        cases = Cases(template.scope, template.case_id, int(submission["caseRevision"]))
        coordinator = ChannelPolicyCoordinator(
            executions=port,
            scope=template.scope,
            case_authority=cases,
            timeout_ms=options.pop("timeout_ms", 5000),
            cleanup_ms=options.pop("cleanup_ms", 1000),
            max_active=options.pop("max_active", 4),
        )
        service = m.ChannelOriginService(
            binding=binding, template=template, coordinator=coordinator, **options
        )
        self.ports.append(port)
        self.cases.append(cases)
        self.owners.append(service)
        return service, port, cases, binding, template, coordinator

    async def test_actual_producer_inputs_retain_full_origin_and_actual_work_uuid_not_body(self):
        for index, fixture in enumerate(FIXTURE["p2_cases"]):
            service, port, cases, binding, _, _ = self.build(index)
            receipt = await service.accept(fixture["accept_frame_canonical"].encode())
            record = next(iter(port.ledger.records.values()))
            request = parse_channel_policy_request(record.payload.body)
            self.assertEqual(
                receipt,
                {
                    "operationKey": fixture["submission"]["operationKey"],
                    "scope": fixture["submission"]["scope"],
                    "payloadDigest": fixture["payload_sha256"],
                    "receiptId": record.work_id,
                },
            )
            self.assertNotEqual(receipt["receiptId"], request.origin.input_receipt_id)
            self.assertEqual(request.origin.profile_id, binding.profile_id)
            self.assertEqual(request.origin.payload_byte_length, fixture["payload_byte_length"])
            self.assertEqual(
                request.origin.input_receipt_id, fixture["submission"]["message"]["receiptId"]
            )
            self.assertEqual(record.payload.body, encode_channel_policy_request(request))
            self.assertLessEqual(len(record.payload.body), 16384)
            self.assertNotIn(fixture["payload_canonical"].encode(), record.payload.body)
            self.assertEqual((port.finds, port.submits, cases.calls), (1, 1, 1))
            self.assertEqual(service.metrics()["accepted_observed"], 1)

    async def test_known_replay_uses_original_context_after_expiry_case_and_config_changes(self):
        ledger = Ledger()
        first, port, cases, _, _, _ = self.build(ledger=ledger, deadline_window_ms=1000)
        raw = FIXTURE["p2_cases"][0]["accept_frame_canonical"].encode()
        receipt = await first.accept(raw)
        stored = next(iter(ledger.records.values())).payload.body
        original = parse_channel_policy_request(stored)
        cases.current = replace(cases.current, request_revision=2, cancelled=True)
        second, port2, cases2, _, _, _ = self.build(
            ledger=ledger, version="changed_v2", deadline_window_ms=50000
        )
        cases2.current = replace(cases2.current, request_revision=2, cancelled=True)
        with patch.object(
            m.time, "time_ns", return_value=(original.deadline_at_ms + 1000) * 1000000
        ):
            self.assertEqual(await second.accept(raw), receipt)
        self.assertEqual(next(iter(ledger.records.values())).payload.body, stored)
        self.assertEqual((port.submits, port2.submits, cases.calls, cases2.calls), (1, 0, 1, 0))
        self.assertEqual(second.metrics()["replayed_observed"], 1)

    async def test_concurrent_origin_proposals_keep_one_complete_first_context(self):
        ledger = Ledger()
        ledger.race = True
        first, port1, _, _, _, _ = self.build(
            ledger=ledger, version="proposal_a", deadline_window_ms=30000
        )
        second, port2, _, _, _, _ = self.build(
            ledger=ledger, version="proposal_b", deadline_window_ms=40000
        )
        raw = FIXTURE["p2_cases"][0]["accept_frame_canonical"].encode()
        async with asyncio.timeout(2):
            a, b = await asyncio.gather(first.accept(raw), second.accept(raw))
        self.assertEqual(a, b)
        self.assertEqual(len(ledger.records), 1)
        self.assertEqual(port1.submits + port2.submits, 2)
        self.assertEqual(port1.finds + port2.finds, 3)
        stored = parse_channel_policy_request(next(iter(ledger.records.values())).payload.body)
        self.assertIn(stored.request.evidence[0].version, ("proposal_a", "proposal_b"))
        self.assertEqual(
            first.metrics()["accepted_observed"] + second.metrics()["accepted_observed"], 1
        )

    async def test_changed_digest_receipt_or_profile_conflicts_on_same_original_key(self):
        service, port, _, _, _, _ = self.build()
        case = FIXTURE["p2_cases"][0]
        raw = case["accept_frame_canonical"].encode()
        receipt = await service.accept(raw)
        for path in ("body", "receiptId"):
            changed = copy.deepcopy(case["submission"])
            changed["message"][path] = "changed" if path == "body" else str(uuid4())
            with (
                self.subTest(path=path),
                self.assertRaisesRegex(CoordinatorError, "^identity_conflict$"),
            ):
                await service.accept(frame(changed))
        other, _, _, _, _, _ = self.build(ledger=port.ledger, profile=str(uuid4()))
        with self.assertRaisesRegex(CoordinatorError, "^identity_conflict$"):
            await other.accept(raw)
        self.assertEqual(len(port.ledger.records), 1)
        self.assertEqual(port.submits, 1)
        query = wire.parse_accept_frame(raw).lookup().to_wire()
        self.assertEqual(await service.lookup(encoded(query)), receipt)

    async def test_all_shared_negative_frames_fail_exact_stage_code_before_work_io(self):
        service, port, cases, _, _, _ = self.build()
        for value in FIXTURE["negative_accept_frames"]:
            code = (
                "unauthorized"
                if value["stage"] == "route"
                else {"InvalidCommand": "invalid_input", "IdentityConflict": "identity_conflict"}[
                    value["code"]
                ]
            )
            with (
                self.subTest(name=value["name"]),
                self.assertRaisesRegex(CoordinatorError, "^" + code + "$"),
            ):
                await service.accept(value["frame"].encode("utf-8"))
        self.assertEqual((port.finds, port.submits, cases.calls), (0, 0, 0))

    async def test_foreign_scope_sender_and_unsupported_mapped_ids_reject_before_io(self):
        service, port, cases, _, _, _ = self.build()
        original = FIXTURE["p2_cases"][0]["submission"]
        variants = []
        for key, changed in (
            ("caseId", "foreign_case"),
            ("conversationId", "foreign_conversation"),
            ("caseId", "X" * 65),
        ):
            value = copy.deepcopy(original)
            value[key] = changed
            variants.append((value, "invalid_input" if len(changed) > 64 else "unauthorized"))
        value = copy.deepcopy(original)
        value["scope"]["tenantId"] = "foreign_tenant"
        variants.append((value, "unauthorized"))
        value = copy.deepcopy(original)
        value["message"]["senderId"] = "foreign_sender"
        variants.append((value, "unauthorized"))
        for value, code in variants:
            with (
                self.subTest(code=code),
                self.assertRaisesRegex(CoordinatorError, "^" + code + "$"),
            ):
                await service.accept(frame(value))
        self.assertEqual((port.finds, port.submits, cases.calls), (0, 0, 0))

    async def test_new_stale_revision_is_rejected_but_current_original_operation_progresses(self):
        service, port, cases, _, _, _ = self.build()
        original = copy.deepcopy(FIXTURE["p2_cases"][0]["submission"])
        cases.current = replace(cases.current, request_revision=2)
        with self.assertRaisesRegex(CoordinatorError, "^case_changed$"):
            await service.accept(frame(original))
        self.assertEqual(port.submits, 0)
        original["caseRevision"] = "2"
        accepted = await service.accept(frame(original))
        self.assertEqual(accepted["operationKey"], original["operationKey"])
        self.assertEqual(port.submits, 1)

    async def test_lookup_has_no_case_read_and_missing_lookup_never_accepts(self):
        service, port, cases, _, _, _ = self.build()
        source = wire.parse_accept_frame(FIXTURE["p2_cases"][0]["accept_frame_canonical"].encode())
        query = encoded(source.lookup().to_wire())
        self.assertIsNone(await service.lookup(query))
        self.assertEqual((port.submits, cases.calls), (0, 0))
        receipt = await service.accept(FIXTURE["p2_cases"][0]["accept_frame_canonical"].encode())
        cases.current = replace(cases.current, request_revision=2, cancelled=True)
        self.assertEqual(await service.lookup(query), receipt)
        self.assertEqual(cases.calls, 1)
        bad = source.lookup().to_wire()
        bad["payloadDigest"] = "0" * 64
        with self.assertRaisesRegex(CoordinatorError, "^identity_conflict$"):
            await service.lookup(encoded(bad))
        bad = source.lookup().to_wire()
        bad["scope"] = {"tenantId": "foreign", "accountId": "foreign"}
        before = port.finds
        with self.assertRaisesRegex(CoordinatorError, "^unauthorized$"):
            await service.lookup(encoded(bad))
        self.assertEqual(port.finds, before)
        self.assertEqual(port.submits, 1)

    async def test_commit_unknown_has_one_core_reconciliation_read_and_no_adapter_retry(self):
        service, port, _, _, _, _ = self.build()
        port.ack_loss = True
        receipt = await service.accept(FIXTURE["p2_cases"][0]["accept_frame_canonical"].encode())
        self.assertEqual((port.finds, port.submits), (2, 1))
        self.assertEqual(receipt["receiptId"], next(iter(port.ledger.records.values())).work_id)
        self.assertEqual(service.metrics()["replayed_observed"], 1)
        self.assertEqual(service.metrics()["accepted_observed"], 0)

    async def test_unknown_missing_or_failed_reconciliation_never_resubmits(self):
        for failure in (None, WorkError("storage_unavailable")):
            service, port, _, _, _, _ = self.build()
            port.submit_error = WorkError("acknowledgement_unknown")
            port.reconcile_error = failure
            with (
                self.subTest(failure=failure),
                self.assertRaisesRegex(CoordinatorError, "^acknowledgement_unknown$"),
            ):
                await service.accept(FIXTURE["p2_cases"][0]["accept_frame_canonical"].encode())
            self.assertEqual((port.finds, port.submits, len(port.ledger.records)), (2, 1, 0))

    async def test_storage_failure_and_unexpected_dependency_text_are_safely_bounded(self):
        service, port, _, _, _, _ = self.build()
        port.submit_error = WorkError("storage_unavailable")
        with self.assertRaisesRegex(CoordinatorError, "^storage_unavailable$"):
            await service.accept(FIXTURE["p2_cases"][0]["accept_frame_canonical"].encode())
        self.assertEqual((port.finds, port.submits), (1, 1))
        port.submit_error = RuntimeError("SECRET_SENTINEL provider detail")
        with self.assertRaises(CoordinatorError) as caught:
            await service.accept(FIXTURE["p2_cases"][0]["accept_frame_canonical"].encode())
        self.assertEqual(str(caught.exception), "internal_error")
        self.assertNotIn("SECRET_SENTINEL", str(caught.exception))

    async def test_caller_abort_retains_actual_submit_and_later_lookup_recovers(self):
        service, port, _, _, _, _ = self.build(max_active=1)
        port.release = asyncio.Event()
        raw = FIXTURE["p2_cases"][0]["accept_frame_canonical"].encode()
        waiter = asyncio.create_task(service.accept(raw))
        await asyncio.wait_for(port.entered.wait(), 1)
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiter
        self.assertEqual((service.metrics()["active"], port.pending_count), (1, 1))
        query = encoded(wire.parse_accept_frame(raw).lookup().to_wire())
        with self.assertRaisesRegex(CoordinatorError, "^capacity$"):
            await service.lookup(query)
        port.release.set()
        await asyncio.wait_for(port.settled.wait(), 1)
        for _ in range(10):
            if service.metrics()["active"] == 0:
                break
            await asyncio.sleep(0)
        receipt = await service.lookup(query)
        self.assertEqual(receipt["receiptId"], next(iter(port.ledger.records.values())).work_id)
        self.assertEqual((port.submits, service.metrics()["cancelled_waiters"]), (1, 1))

    async def test_incomplete_close_retains_dependency_until_actual_settlement_then_retries(self):
        service, port, _, _, _, _ = self.build(cleanup_ms=20)
        port.release = asyncio.Event()
        task = asyncio.create_task(
            service.accept(FIXTURE["p2_cases"][0]["accept_frame_canonical"].encode())
        )
        await asyncio.wait_for(port.entered.wait(), 1)
        with self.assertRaisesRegex(CoordinatorError, "^cleanup_incomplete$"):
            await service.close()
        self.assertEqual((port.pending_count, port.closed, service.metrics()["active"]), (1, 0, 1))
        with self.assertRaisesRegex(CoordinatorError, "^closed$"):
            await service.accept(b"invalid")
        port.release.set()
        await task
        await service.close()
        self.assertEqual((port.pending_count, port.closed, service.metrics()["active"]), (0, 1, 0))

    async def test_profile_read_is_public_read_only_and_wrong_profile_does_no_io(self):
        service, port, cases, binding, _, _ = self.build()
        with self.assertRaisesRegex(CoordinatorError, "^unauthorized$"):
            await service.inspect_profile(encoded({"schemaVersion": 1, "profileId": str(uuid4())}))
        self.assertEqual(port.finds, 0)
        await service.inspect_profile(
            encoded({"schemaVersion": 1, "profileId": binding.profile_id})
        )
        self.assertEqual((port.finds, port.submits, cases.calls), (1, 0, 0))
        self.assertEqual(service.metrics()["profile_reads"], 1)

    async def test_configuration_is_copied_before_ownership_and_invalid_routes_leave_owner_open(
        self,
    ):
        service, port, _, binding, template, coordinator = self.build()
        for change, code in (
            ({"profile_id": "bad"}, "invalid_input"),
            ({"case_id": "other"}, "unauthorized"),
        ):
            with (
                self.subTest(change=change),
                self.assertRaisesRegex(CoordinatorError, "^" + code + "$"),
            ):
                m.ChannelOriginService(
                    binding=replace(binding, **change), template=template, coordinator=coordinator
                )
        for window in (True, 19, 60001):
            with (
                self.subTest(window=window),
                self.assertRaisesRegex(CoordinatorError, "^invalid_input$"),
            ):
                m.ChannelOriginService(
                    binding=binding,
                    template=template,
                    coordinator=coordinator,
                    deadline_window_ms=window,
                )
        self.assertEqual((port.finds, port.submits, port.closed), (0, 0, 0))
        object.__setattr__(binding, "profile_id", str(uuid4()))
        object.__setattr__(template.context_snapshot, "policy_source_id", "changed")
        object.__setattr__(template.scope, "tenant_id", "changed")
        await service.accept(FIXTURE["p2_cases"][0]["accept_frame_canonical"].encode())
        stored = parse_channel_policy_request(next(iter(port.ledger.records.values())).payload.body)
        self.assertEqual(stored.origin.profile_id, FIXTURE["profile_id"])
        self.assertEqual(stored.request.context_snapshot.policy_source_id, "policy_notice")
        self.assertEqual(stored.scope.tenant_id, "tenant_fixed")

    async def test_exporter_failure_cannot_change_accepted_receipt_and_logs_contain_no_payload(
        self,
    ):
        service, port, _, _, _, _ = self.build()
        original = copy.deepcopy(FIXTURE["p2_cases"][0]["submission"])
        original["message"]["body"] = "SECRET_SENTINEL original message"
        records = []

        class Broken(logging.Handler):
            def emit(self, record):
                records.append(record)
                raise RuntimeError("SECRET_SENTINEL exporter")

        handler = Broken()
        old_level = m.LOGGER.level
        m.LOGGER.addHandler(handler)
        m.LOGGER.setLevel(logging.INFO)
        try:
            receipt = await service.accept(frame(original))
            self.assertEqual(receipt["receiptId"], next(iter(port.ledger.records.values())).work_id)
            self.assertEqual(service.metrics()["telemetry_failed"], 1)
            self.assertEqual(len(records), 1)
            self.assertEqual(
                (records[0].getMessage(), records[0].operation, records[0].code),
                ("channel_origin", "accept", "known"),
            )
            self.assertNotIn("SECRET_SENTINEL", repr(records[0].__dict__))
        finally:
            m.LOGGER.removeHandler(handler)
            m.LOGGER.setLevel(old_level)
        snapshot = service.metrics()
        with self.assertRaises(TypeError):
            snapshot["started"] = 100

    async def test_wrong_event_loop_cannot_close_or_change_metrics(self):
        service, port, _, binding, _, _ = self.build()
        await service.inspect_profile(
            encoded({"schemaVersion": 1, "profileId": binding.profile_id})
        )
        before = dict(service.metrics())

        def other_loop():
            with self.assertRaisesRegex(CoordinatorError, "^invalid_input$"):
                asyncio.run(service.close())

        await asyncio.to_thread(other_loop)
        self.assertEqual(dict(service.metrics()), before)
        self.assertEqual(port.closed, 0)

    def test_import_starts_no_socket_or_process(self):
        code = """import asyncio,json,socket
from unittest.mock import patch
with patch.object(socket.socket,"connect",side_effect=AssertionError("network")),patch.object(socket.socket,"bind",side_effect=AssertionError("listener")),patch("subprocess.Popen",side_effect=AssertionError("process")),patch.object(asyncio,"create_task",side_effect=AssertionError("background task")):
    from services.channel_policy_demo import origin
assert origin.ChannelOriginService.__module__=="services.channel_policy_demo.origin"
print(json.dumps({"inert":True}))
"""
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", code],
            cwd="/private/tmp",
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"inert": True})


if __name__ == "__main__":
    unittest.main()
