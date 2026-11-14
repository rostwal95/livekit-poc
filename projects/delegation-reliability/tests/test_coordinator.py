"""Typed fake-port coordinator tests; these do not prove PostgreSQL persistence."""

import asyncio
import copy
import hashlib
import json
import logging
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from continuity_lab.postgres_api import CaseProjection
from continuity_lab.work_api import (
    WorkCancellation,
    WorkError,
    WorkPayload,
    WorkRecord,
    WorkScope,
    WorkSubmission,
)
from delegation_reliability.case_adapter import CaseBinding, ManagedCaseAuthority
from delegation_reliability.contracts import canonical, parse_request, produce_request
from delegation_reliability.coordinator import (
    CaseSnapshot,
    CoordinatorError,
    DelegationCoordinator,
    DelegationSubmission,
)

FIXTURE = json.loads(
    (Path(__file__).resolve().parents[3] / "contracts/delegation/v1.json").read_text()
)


def request(**changes):
    value = copy.deepcopy(FIXTURE["producer_input"])
    value["deadline_at_ms"] = time.time_ns() // 1_000_000 + 30_000
    value.update(changes)
    return produce_request(value)


class FakeCases:
    def __init__(self, value):
        self.current = CaseSnapshot(value.scope, value.case_id, value.request_revision, False)
        self.calls = 0
        self.entered = asyncio.Event()
        self.release = None

    async def snapshot(self, *, case_id):
        self.calls += 1
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        return self.current


class FakeExecutions:
    """One scoped fake authority; deliberately no filesystem/database behavior."""

    def __init__(self, value):
        self.scope = WorkScope(value.scope.tenant_id, value.scope.account_id)
        self.records = {}
        self.commands = {}
        self.calls = 0
        self.closed = 0
        self.ack_loss = False
        self.lock = asyncio.Lock()
        self.entered = asyncio.Event()
        self.release = None
        self.failure = None

    @property
    def pending_count(self):
        return 0

    async def submit(self, *, idempotency_key, payload):
        self.calls += 1
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        if self.failure is not None:
            raise self.failure
        async with self.lock:
            existing = self.records.get(idempotency_key)
            if existing is not None:
                if existing.payload != payload:
                    raise WorkError("identity_conflict")
                return WorkSubmission(existing, False)
            record = WorkRecord(
                str(uuid4()),
                self.scope,
                idempotency_key,
                payload,
                time.time_ns() // 1_000_000,
                False,
            )
            self.records[idempotency_key] = record
            if self.ack_loss:
                raise WorkError("acknowledgement_unknown")
            return WorkSubmission(record, True)

    async def find(self, *, idempotency_key):
        return self.records.get(idempotency_key)

    async def get(self, *, work_id):
        for record in self.records.values():
            if record.work_id == work_id:
                return record
        raise WorkError("not_found")

    async def cancel(self, *, work_id, command_id):
        key = command_id
        previous = self.commands.get(key)
        if previous is not None:
            if previous.work_id != work_id:
                raise WorkError("identity_conflict")
            return previous
        record = await self.get(work_id=work_id)
        self.records[record.idempotency_key] = replace(record, cancel_requested=True)
        cancellation = WorkCancellation(
            str(uuid4()), work_id, command_id, time.time_ns() // 1_000_000
        )
        self.commands[key] = cancellation
        return cancellation

    async def close(self):
        self.closed += 1


class CoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.value = request()
        self.port = FakeExecutions(self.value)
        self.cases = FakeCases(self.value)
        self.coordinators = []

    async def asyncTearDown(self):
        if self.port.release is not None:
            self.port.release.set()
        if self.cases.release is not None:
            self.cases.release.set()
        for coordinator in self.coordinators:
            await coordinator.close()

    def coordinator(self, **options):
        result = DelegationCoordinator(
            executions=self.port, scope=self.value.scope, case_authority=self.cases, **options
        )
        self.coordinators.append(result)
        return result

    async def test_accepts_original_canonical_snapshot_and_get_find(self):
        coordinator = self.coordinator()
        submitted = await coordinator.submit(self.value)
        self.assertTrue(submitted.created)
        self.assertEqual(submitted.view.request, self.value)
        self.assertEqual(
            submitted.view.record.payload.sha256,
            hashlib.sha256(submitted.view.record.payload.body).hexdigest(),
        )
        self.assertEqual(submitted.view.record.status, "accepted")
        self.assertFalse(submitted.view.record.cancel_requested)
        self.assertEqual(await coordinator.get(submitted.view.record.work_id), submitted.view)
        self.assertEqual(await coordinator.find(self.value.delegation_id), submitted.view)
        self.assertIsNone(await coordinator.find("missing"))
        self.assertEqual(self.cases.calls, 1)

    async def test_caller_mutation_after_preflight_cannot_change_accepted_input(self):
        coordinator = self.coordinator()
        self.cases.release = asyncio.Event()
        original_note = self.value.context_snapshot.note
        pending = asyncio.create_task(coordinator.submit(self.value))
        await self.cases.entered.wait()
        object.__setattr__(self.value.context_snapshot, "note", "SECRET_SENTINEL changed")
        self.cases.release.set()
        accepted = await pending
        self.assertEqual(accepted.view.request.context_snapshot.note, original_note)
        self.assertNotIn(b"SECRET_SENTINEL", accepted.view.record.payload.body)
        self.assertNotIn(original_note, repr(accepted.view))

    async def test_exact_replay_and_transport_attempt_retry_return_original_bytes(self):
        coordinator = self.coordinator()
        first = await coordinator.submit(self.value)
        retry_wire = self.value.to_wire()
        retry_wire["attempt"] = {"attempt_id": "attempt_retry", "number": 2}
        retry = parse_request(canonical(retry_wire))
        self.cases.current = replace(self.cases.current, request_revision=2, cancelled=True)
        second = await coordinator.submit(retry)
        self.assertFalse(second.created)
        self.assertEqual(second.view, first.view)
        self.assertEqual(second.view.request.attempt, self.value.attempt)
        self.assertEqual(self.cases.calls, 1)
        self.assertEqual(self.port.calls, 1)

    async def test_changed_same_id_scope_and_bad_input_fail_without_replacement(self):
        coordinator = self.coordinator()
        first = await coordinator.submit(self.value)
        wire = self.value.to_wire()
        wire.pop("input_fingerprint")
        wire["result_route"] = {"conversation_id": "other_route"}
        changed = produce_request(wire)
        with self.assertRaisesRegex(CoordinatorError, "^identity_conflict$"):
            await coordinator.submit(changed)
        wire["scope"] = {"tenant_id": "other", "account_id": "other"}
        with self.assertRaisesRegex(CoordinatorError, "^unauthorized$"):
            await coordinator.submit(produce_request(wire))
        with self.assertRaisesRegex(CoordinatorError, "^invalid_input$"):
            await coordinator.submit({"note": "SECRET_SENTINEL"})
        self.assertEqual(await coordinator.find(self.value.delegation_id), first.view)

    async def test_concurrent_different_attempt_bytes_reconcile_one_logical_acceptance(self):
        coordinator = self.coordinator()
        self.port.release = asyncio.Event()
        retry_wire = self.value.to_wire()
        retry_wire["attempt"] = {"attempt_id": "attempt_retry", "number": 2}
        retry = parse_request(canonical(retry_wire))
        first = asyncio.create_task(coordinator.submit(self.value))
        second = asyncio.create_task(coordinator.submit(retry))
        await self.port.entered.wait()
        await asyncio.sleep(0)
        self.port.release.set()
        values = await asyncio.gather(first, second)
        self.assertEqual(sum(value.created for value in values), 1)
        self.assertEqual(values[0].view, values[1].view)
        self.assertEqual(len(self.port.records), 1)

    async def test_concurrent_changed_input_conflicts_and_preserves_first_snapshot(self):
        coordinator = self.coordinator()
        self.port.release = asyncio.Event()
        changed = self.value.to_wire()
        changed.pop("input_fingerprint")
        changed["context_snapshot"]["note"] = "changed inert context"
        changed = produce_request(changed)
        original = asyncio.create_task(coordinator.submit(self.value))
        await self.port.entered.wait()
        contender = asyncio.create_task(coordinator.submit(changed))
        await asyncio.sleep(0)
        self.port.release.set()
        outcomes = await asyncio.gather(original, contender, return_exceptions=True)
        accepted = [item for item in outcomes if isinstance(item, DelegationSubmission)]
        conflicts = [item for item in outcomes if isinstance(item, CoordinatorError)]
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].code, "identity_conflict")
        self.assertEqual(await coordinator.find(self.value.delegation_id), accepted[0].view)
        self.assertEqual(len(self.port.records), 1)

    async def test_changed_context_with_claimed_old_fingerprint_is_invalid_before_ports(self):
        coordinator = self.coordinator()
        forged = replace(
            self.value,
            context_snapshot=replace(self.value.context_snapshot, note="SECRET_SENTINEL"),
        )
        with self.assertRaisesRegex(CoordinatorError, "^invalid_input$"):
            await coordinator.submit(forged)
        self.assertEqual(self.cases.calls, 0)
        self.assertEqual(self.port.calls, 0)

    async def test_committed_ack_loss_is_reconciled_without_second_submit(self):
        coordinator = self.coordinator()
        self.port.ack_loss = True
        accepted = await coordinator.submit(self.value)
        self.assertFalse(accepted.created)
        self.assertEqual(self.port.calls, 1)
        self.assertEqual(await coordinator.get(accepted.view.record.work_id), accepted.view)

    async def test_unreconciled_failure_cannot_acknowledge_acceptance(self):
        coordinator = self.coordinator()
        self.port.failure = WorkError("acknowledgement_unknown")
        with self.assertRaisesRegex(CoordinatorError, "^acknowledgement_unknown$"):
            await coordinator.submit(self.value)
        self.assertEqual(len(self.port.records), 0)
        self.port.failure = WorkError("storage_unavailable")
        with self.assertRaisesRegex(CoordinatorError, "^storage_unavailable$"):
            await coordinator.submit(self.value)
        self.port.failure = None
        self.assertTrue((await coordinator.submit(self.value)).created)

    async def test_current_revision_cancelled_case_and_expired_new_work_rejected(self):
        coordinator = self.coordinator()
        self.cases.current = replace(self.cases.current, request_revision=2)
        with self.assertRaisesRegex(CoordinatorError, "^case_changed$"):
            await coordinator.submit(self.value)
        self.cases.current = replace(self.cases.current, request_revision=1, cancelled=True)
        with self.assertRaisesRegex(CoordinatorError, "^case_cancelled$"):
            await coordinator.submit(self.value)
        self.cases.current = replace(self.cases.current, cancelled=False)
        expired = request(deadline_at_ms=time.time_ns() // 1_000_000 - 1)
        with self.assertRaisesRegex(CoordinatorError, "^expired$"):
            await coordinator.submit(expired)
        self.assertEqual(self.port.calls, 0)
        self.assertTrue((await coordinator.submit(self.value)).created)

    async def test_get_replay_cancel_remain_available_after_deadline_or_case_change(self):
        coordinator = self.coordinator()
        accepted = await coordinator.submit(self.value)
        self.cases.current = replace(self.cases.current, request_revision=2, cancelled=True)
        work_id = accepted.view.record.work_id
        with patch(
            "delegation_reliability.coordinator.time.time_ns",
            return_value=(self.value.deadline_at_ms + 1) * 1_000_000,
        ):
            self.assertEqual((await coordinator.submit(self.value)).view, accepted.view)
            cancel = await coordinator.cancel(work_id, "cancel_one")
            self.assertEqual(cancel, await coordinator.cancel(work_id, "cancel_one"))
            observed = await coordinator.get(work_id)
            self.assertTrue(observed.record.cancel_requested)
            self.assertEqual(observed.record.status, "accepted")
            self.assertEqual(cancel.disposition, "requested")

    async def test_cancelled_case_read_does_not_later_start_acceptance(self):
        coordinator = self.coordinator(max_active=1)
        self.cases.release = asyncio.Event()
        pending = asyncio.create_task(coordinator.submit(self.value))
        await self.cases.entered.wait()
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending
        self.assertEqual(coordinator.pending_count, 1)
        with self.assertRaisesRegex(CoordinatorError, "^capacity$"):
            await coordinator.find(self.value.delegation_id)
        self.cases.release.set()
        await coordinator.close()
        self.assertEqual(self.port.calls, 0)
        self.assertEqual(coordinator.pending_count, 0)

    async def test_timed_out_write_retains_capacity_and_reconciles_same_key(self):
        coordinator = self.coordinator(max_active=1, timeout_ms=20)
        self.port.release = asyncio.Event()
        with self.assertRaisesRegex(CoordinatorError, "^acknowledgement_unknown$"):
            await coordinator.submit(self.value)
        self.assertEqual(coordinator.pending_count, 1)
        with self.assertRaisesRegex(CoordinatorError, "^capacity$"):
            await coordinator.find(self.value.delegation_id)
        self.port.release.set()
        for _ in range(10):
            if coordinator.pending_count == 0:
                break
            await asyncio.sleep(0)
        self.assertIsNotNone(await coordinator.find(self.value.delegation_id))
        self.assertEqual(self.port.calls, 1)

    async def test_close_during_case_read_never_starts_acceptance(self):
        coordinator = self.coordinator()
        self.cases.release = asyncio.Event()
        pending = asyncio.create_task(coordinator.submit(self.value))
        await self.cases.entered.wait()
        closing = asyncio.create_task(coordinator.close())
        await asyncio.sleep(0)
        self.cases.release.set()
        await closing
        with self.assertRaisesRegex(CoordinatorError, "^request_aborted$"):
            await pending
        self.assertEqual((self.port.calls, coordinator.pending_count), (0, 0))

    async def test_bounded_close_does_not_cancel_live_write_and_is_idempotent(self):
        coordinator = self.coordinator(cleanup_ms=20)
        self.port.release = asyncio.Event()
        pending = asyncio.create_task(coordinator.submit(self.value))
        await self.port.entered.wait()
        for _ in range(2):
            with self.assertRaisesRegex(CoordinatorError, "^cleanup_incomplete$"):
                await coordinator.close()
            self.assertEqual(coordinator.pending_count, 1)
            self.assertFalse(pending.done())
        self.port.release.set()
        self.assertTrue((await pending).created)
        await coordinator.close()
        await coordinator.close()
        self.assertEqual(self.port.closed, 1)
        with self.assertRaisesRegex(CoordinatorError, "^closed$"):
            await coordinator.find(self.value.delegation_id)

    async def test_corrupt_stored_hash_scope_or_noncanonical_body_never_acknowledged(self):
        coordinator = self.coordinator()
        accepted = await coordinator.submit(self.value)
        pristine = accepted.view.record
        for change in ("hash", "scope", "body"):
            record = replace(
                pristine,
                payload=WorkPayload(
                    pristine.payload.operation,
                    pristine.payload.body,
                    pristine.payload.deadline_at_ms,
                ),
            )
            if change == "hash":
                object.__setattr__(record.payload, "sha256", "0" * 64)
            elif change == "scope":
                object.__setattr__(record, "scope", WorkScope("other", "other"))
            else:
                object.__setattr__(
                    record,
                    "payload",
                    WorkPayload(
                        pristine.payload.operation,
                        b" " + pristine.payload.body,
                        pristine.payload.deadline_at_ms,
                    ),
                )
            self.port.records[self.value.delegation_id] = record
            with self.assertRaisesRegex(CoordinatorError, "^invalid_stored_state$"):
                await coordinator.find(self.value.delegation_id)
        self.port.records[self.value.delegation_id] = pristine
        self.assertIsNotNone(await coordinator.find(self.value.delegation_id))

    async def test_safe_port_exception_and_logger_failure_never_reflect_private_text(self):
        coordinator = self.coordinator()
        self.port.failure = OSError("SECRET_SENTINEL")
        with self.assertRaisesRegex(CoordinatorError, "^internal_error$"):
            await coordinator.submit(self.value)
        self.port.failure = None

        class Handler(logging.Handler):
            def emit(self, record):
                self.seen = record
                raise ValueError("SECRET_SENTINEL")

        logger = logging.getLogger("delegation_reliability.coordinator")
        handler, original = Handler(), logger.level
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        try:
            accepted = await coordinator.submit(self.value)
        finally:
            logger.removeHandler(handler)
            logger.setLevel(original)
        self.assertTrue(accepted.created)
        self.assertEqual(coordinator.metrics()["telemetry_failed"], 1)
        self.assertNotIn("SECRET_SENTINEL", str(handler.seen.__dict__))
        self.assertNotIn(self.value.context_snapshot.note, str(handler.seen.__dict__))

    async def test_unauthorized_case_observation_and_unknown_work_are_fixed(self):
        coordinator = self.coordinator()
        self.cases.current = replace(self.cases.current, case_id="other_case")
        with self.assertRaisesRegex(CoordinatorError, "^unauthorized$"):
            await coordinator.submit(self.value)
        with self.assertRaisesRegex(CoordinatorError, "^not_found$"):
            await coordinator.get(str(uuid4()))
        with self.assertRaisesRegex(CoordinatorError, "^invalid_input$"):
            await coordinator.cancel("SECRET_SENTINEL", "cancel")

    async def test_misbound_public_execution_scope_rejected_before_any_port_call(self):
        self.port.scope = WorkScope("other", "other")
        with self.assertRaisesRegex(CoordinatorError, "^unauthorized$"):
            self.coordinator()
        self.assertEqual(self.port.calls, 0)
        self.assertEqual(self.cases.calls, 0)
        self.assertEqual(len(self.port.records), 0)
        self.port.scope = WorkScope(self.value.scope.tenant_id, self.value.scope.account_id)
        coordinator = self.coordinator()
        self.port.scope = WorkScope("other", "other")
        with self.assertRaisesRegex(CoordinatorError, "^unauthorized$"):
            await coordinator.submit(self.value)
        self.assertEqual(self.port.calls, 0)
        self.port.scope = WorkScope(self.value.scope.tenant_id, self.value.scope.account_id)
        self.assertTrue((await coordinator.submit(self.value)).created)

    async def test_public_case_adapter_uses_trusted_bindings_and_strict_p1_projection(self):
        task_id, case_id = str(uuid4()), str(uuid4())

        class ReadClient:
            def __init__(self):
                self.requested = []
                self.revision = "1"
                self.confirmation_state = "not_requested"

            async def get(self, *, task_id, cursor=None, limit=10):
                self.requested.append((task_id, limit))
                return CaseProjection.create(
                    {
                        "schema_version": 1,
                        "task_id": task_id,
                        "case_id": case_id,
                        "case_revision": self.revision,
                        "confirmation": {"state": self.confirmation_state},
                    }
                )

        reader = ReadClient()
        adapter = ManagedCaseAuthority(
            reader,
            scope=self.value.scope,
            bindings=(CaseBinding(self.value.case_id, task_id, case_id),),
        )
        snapshot = await adapter.snapshot(case_id=self.value.case_id)
        self.assertEqual(snapshot, self.cases.current)
        self.assertEqual(reader.requested, [(task_id, 1)])
        with self.assertRaisesRegex(CoordinatorError, "^not_found$"):
            await adapter.snapshot(case_id="not_configured")
        # Both un-cancelled and subsequently cancelled committed cases have this
        # same current public projection. Neither may manufacture a false value.
        for _label in ("committed_uncancelled", "committed_after_cancel"):
            reader.confirmation_state = "committed"
            with self.assertRaisesRegex(CoordinatorError, "^case_state_unavailable$"):
                await adapter.snapshot(case_id=self.value.case_id)
        reader.confirmation_state = "required"
        self.assertFalse((await adapter.snapshot(case_id=self.value.case_id)).cancelled)
        reader.confirmation_state = "cancelled"
        self.assertTrue((await adapter.snapshot(case_id=self.value.case_id)).cancelled)
        reader.revision = "01"
        with self.assertRaisesRegex(CoordinatorError, "^invalid_stored_state$"):
            await adapter.snapshot(case_id=self.value.case_id)
