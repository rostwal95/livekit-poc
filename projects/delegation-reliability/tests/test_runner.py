"""Typed fake execution/specialist ports; actual durability has a separate gate."""

import asyncio
import copy
import hashlib
import json
import logging
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import PropertyMock, patch
from uuid import UUID, uuid4

from continuity_lab.execution_api import (
    AttemptResult,
    ExecutionObservation,
    Issuance,
    IssuedAttempt,
)
from continuity_lab.work_api import WorkError, WorkPayload, WorkRecord, WorkScope
from delegation_reliability import (
    CaseSnapshot,
    DelegationRunError,
    DelegationRunner,
    SpecialistResultObservation,
)
from delegation_reliability.contracts import canonical, parse_result, produce_request
from delegation_reliability.security import EvidenceRecord

FIXTURE = json.loads(
    (Path(__file__).resolve().parents[3] / "contracts/delegation/v1.json").read_text()
)
POLICY = canonical({"minimum_notice_days": 7, "policy_version": "policy_v1"})


def request():
    value = copy.deepcopy(FIXTURE["producer_input"])
    value["deadline_at_ms"] = time.time_ns() // 1_000_000 + 30_000
    return produce_request(value)


def result_for(value):
    return replace(
        parse_result(canonical(FIXTURE["result"])),
        scope=value.scope,
        delegation_id=value.delegation_id,
        case_id=value.case_id,
        request_revision=value.request_revision,
        attempt_id=value.attempt.attempt_id,
        input_fingerprint=value.input_fingerprint,
        completed_at_ms=time.time_ns() // 1_000_000,
    )


class FakeCases:
    def __init__(self, value):
        self.current = CaseSnapshot(value.scope, value.case_id, 1, False)
        self.failure = None

    async def snapshot(self, *, case_id):
        if self.failure is not None:
            raise self.failure
        return self.current


class FakeExecution:
    def __init__(self, value):
        self.scope = WorkScope(value.scope.tenant_id, value.scope.account_id)
        self.record = WorkRecord(
            str(uuid4()),
            self.scope,
            value.delegation_id,
            WorkPayload(
                "booking.evaluate_policy", canonical(value.to_wire()), value.deadline_at_ms
            ),
            time.time_ns() // 1_000_000,
            False,
        )
        self.current = None
        self.issues = {}
        self.results = {}
        self.issue_count = 0
        self.complete_count = 0
        self.closed = 0
        self.ack_issue = False
        self.ack_complete = False
        self.lookup_failure = False
        self.issue_release = None
        self.issue_entered = asyncio.Event()
        self.complete_disposition = "eligible_at_commit"
        self.issue_error = None
        self.attempt_id = None
        self.after_issue = None

    async def observe(self, *, work_id):
        if work_id != self.record.work_id:
            raise WorkError("not_found")
        result = None if self.current is None else self.results.get(self.current.attempt_id)
        status = "accepted" if self.current is None else "running"
        if self.record.cancel_requested:
            status = "cancelled"
        if result is not None and result.disposition == "eligible_at_commit":
            status = "result_recorded"
        return ExecutionObservation(
            record=self.record,
            current_attempt=self.current,
            result=result,
            attempts_issued=len(self.issues),
            status=status,
        )

    async def issue(self, *, work_id, owner_id, command_id):
        self.issue_count += 1
        if self.issue_error is not None:
            raise self.issue_error
        if work_id != self.record.work_id:
            raise WorkError("not_found")
        old = self.issues.get(command_id)
        if old is not None:
            return Issuance(attempt=old, created=False)
        now = time.time_ns() // 1_000_000
        grant = IssuedAttempt(
            record=replace(self.record, cancel_requested=False),
            attempt_id=self.attempt_id or str(uuid4()),
            command_id=command_id,
            number=len(self.issues) + 1,
            owner_id=owner_id,
            epoch=len(self.issues) + 1,
            issued_at_ms=now,
            lease_until_ms=now + 10_000,
        )
        self.current = grant
        self.issues[command_id] = grant
        self.issue_entered.set()
        if self.issue_release is not None:
            await self.issue_release.wait()
        if self.after_issue is not None:
            self.after_issue(self)
        if self.ack_issue:
            raise WorkError("acknowledgement_unknown")
        return Issuance(attempt=grant, created=True)

    async def find_issue(self, *, command_id):
        if self.lookup_failure:
            raise WorkError("storage_unavailable")
        return self.issues.get(command_id)

    async def complete(self, *, attempt, body):
        self.complete_count += 1
        disposition = self.complete_disposition
        if self.record.cancel_requested:
            disposition = "cancelled"
        result = AttemptResult(
            work_id=self.record.work_id,
            attempt_id=attempt.attempt_id,
            body=body,
            recorded_at_ms=time.time_ns() // 1_000_000,
            disposition=disposition,
        )
        self.results[attempt.attempt_id] = result
        if self.ack_complete:
            raise WorkError("acknowledgement_unknown")
        return result

    async def result(self, *, work_id, attempt_id):
        if self.lookup_failure:
            raise WorkError("storage_unavailable")
        return self.results.get(attempt_id)

    async def close(self):
        self.closed += 1


class FakeSpecialist:
    def __init__(self):
        self.requests = []
        self.release = None
        self.entered = asyncio.Event()
        self.closed = 0
        self.alter = lambda result: result
        self.failure = None

    async def invoke_observed(self, value):
        self.requests.append(value)
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        if self.failure is not None:
            raise self.failure
        result = self.alter(result_for(value))
        now = time.time_ns() // 1_000_000
        return SpecialistResultObservation(
            result, "expired" if now >= value.deadline_at_ms else "candidate", now
        )

    async def close(self):
        self.closed += 1


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.value = request()
        self.execution = FakeExecution(self.value)
        self.specialist = FakeSpecialist()
        self.cases = FakeCases(self.value)
        self.runners = []

    async def asyncTearDown(self):
        if self.execution.issue_release is not None:
            self.execution.issue_release.set()
        if self.specialist.release is not None:
            self.specialist.release.set()
        for runner in self.runners:
            await runner.close()

    def runner(self, **options):
        result = DelegationRunner(
            executions=self.execution,
            scope=self.value.scope,
            owner_id=str(uuid4()),
            specialist=self.specialist,
            case_authority=self.cases,
            evidence=(EvidenceRecord(self.value.scope, self.value.evidence[0], POLICY),),
            **options,
        )
        self.runners.append(result)
        return result

    async def test_issued_transport_identity_original_input_and_useful_result(self):
        before = self.execution.record.payload.body
        runner = self.runner()
        run = await runner.run_once(self.execution.record.work_id, "command_first")
        self.assertTrue(run.invoked)
        self.assertEqual(run.view.applicability, "candidate")
        self.assertTrue(run.view.result.eligible)
        self.assertNotEqual(
            self.specialist.requests[0].attempt.attempt_id, self.value.attempt.attempt_id
        )
        self.assertEqual(
            self.specialist.requests[0].attempt.attempt_id,
            "attempt_" + self.execution.current.attempt_id.replace("-", ""),
        )
        self.assertEqual(
            self.specialist.requests[0].input_fingerprint, self.value.input_fingerprint
        )
        self.assertEqual(self.execution.record.payload.body, before)
        self.assertEqual(run.recorded.sha256, hashlib.sha256(run.recorded.body).hexdigest())
        self.assertEqual(
            (await runner.inspect(self.execution.record.work_id)).result, run.view.result
        )

    async def test_accepted_proposed_attempt_never_invokes_without_issuance(self):
        self.execution.issue_error = WorkError("expired")
        runner = self.runner()
        with self.assertRaisesRegex(DelegationRunError, "^expired$"):
            await runner.run_once(self.execution.record.work_id, "cancelled_before_start")
        self.assertEqual(self.specialist.requests, [])
        self.assertEqual(self.execution.complete_count, 0)
        self.execution.issue_error = None
        self.assertTrue(
            (await runner.run_once(self.execution.record.work_id, "valid_start")).invoked
        )

    async def test_replayed_issued_command_never_reinvokes(self):
        runner = self.runner()
        self.specialist.failure = OSError("PRIVATE_TRANSPORT_SENTINEL")
        with self.assertRaisesRegex(DelegationRunError, "^internal_error$"):
            await runner.run_once(self.execution.record.work_id, "command_unknown")
        self.specialist.failure = None
        replay = await runner.run_once(self.execution.record.work_id, "command_unknown")
        self.assertFalse(replay.invoked)
        self.assertEqual(replay.view.applicability, "missing")
        self.assertEqual(len(self.specialist.requests), 1)
        self.assertEqual(self.execution.complete_count, 0)

    async def test_digit_and_letter_uuids_have_stable_wire_identity(self):
        runner = self.runner()
        for prefix in ("1", "a"):
            self.execution.current = None
            self.execution.issues.clear()
            self.execution.results.clear()
            self.execution.attempt_id = str(UUID(prefix + "0000000000040008000000000000000"))
            result = await runner.run_once(self.execution.record.work_id, "command_" + prefix)
            self.assertEqual(
                result.view.result.attempt_id, "attempt_" + UUID(self.execution.attempt_id).hex
            )
            self.assertEqual(
                (await runner.inspect(self.execution.record.work_id)).result, result.view.result
            )

    async def test_fresh_current_observation_blocks_known_cancelled_issue(self):
        self.execution.after_issue = lambda port: setattr(
            port, "record", replace(port.record, cancel_requested=True)
        )
        runner = self.runner()
        with self.assertRaisesRegex(DelegationRunError, "^expired$"):
            await runner.run_once(self.execution.record.work_id, "command_delayed_cancel")
        self.assertEqual(self.specialist.requests, [])
        self.assertEqual(self.execution.complete_count, 0)

    async def test_declared_stored_digest_cannot_be_normalized_away(self):
        runner = self.runner()
        with (
            patch.object(WorkPayload, "sha256", new_callable=PropertyMock, return_value="0" * 64),
            self.assertRaisesRegex(DelegationRunError, "^invalid_stored_state$"),
        ):
            await runner.run_once(self.execution.record.work_id, "command_bad_digest")
        self.assertEqual(self.execution.issue_count, 0)
        self.assertTrue(
            (await runner.run_once(self.execution.record.work_id, "command_good_digest")).invoked
        )

    async def test_unknown_issue_ack_reconciles_without_new_issue_or_invoke(self):
        runner = self.runner()
        self.execution.ack_issue = True
        result = await runner.run_once(self.execution.record.work_id, "command_ack")
        self.assertFalse(result.invoked)
        self.assertEqual(self.execution.issue_count, 1)
        self.assertEqual(self.specialist.requests, [])

    async def test_failed_unknown_ack_lookup_stays_unknown(self):
        runner = self.runner()
        self.execution.ack_issue = True
        self.execution.lookup_failure = True
        with self.assertRaisesRegex(DelegationRunError, "^acknowledgement_unknown$"):
            await runner.run_once(self.execution.record.work_id, "command_ack")
        self.assertEqual(self.execution.issue_count, 1)
        self.assertEqual(self.specialist.requests, [])

    async def test_complete_ack_loss_reconciles_original_without_second_write(self):
        runner = self.runner()
        self.execution.ack_complete = True
        result = await runner.run_once(self.execution.record.work_id, "command_complete")
        self.assertEqual(result.view.applicability, "candidate")
        self.assertEqual(self.execution.complete_count, 1)
        again = await runner.run_once(self.execution.record.work_id, "another_command")
        self.assertFalse(again.invoked)
        self.assertEqual(self.execution.issue_count, 1)
        self.assertEqual(len(self.specialist.requests), 1)

    async def test_wrong_scope_composition_fails_before_any_write(self):
        self.execution.scope = WorkScope("foreign", "account")
        with self.assertRaisesRegex(DelegationRunError, "^unauthorized$"):
            self.runner()
        self.assertEqual(self.execution.issue_count, 0)

    async def test_scope_changed_after_constructor_is_rechecked(self):
        runner = self.runner()
        self.execution.scope = WorkScope("foreign", "account")
        with self.assertRaisesRegex(DelegationRunError, "^unauthorized$"):
            await runner.run_once(self.execution.record.work_id, "command_bad_scope")
        self.assertEqual(self.execution.issue_count, 0)

    async def test_bad_result_identity_or_facts_cannot_commit(self):
        runner = self.runner()
        for alter in (
            lambda r: replace(r, attempt_id="forged"),
            lambda r: replace(r, eligible=False),
        ):
            self.specialist.alter = alter
            with self.assertRaisesRegex(DelegationRunError, "^invalid_result$"):
                await runner.run_once(
                    self.execution.record.work_id, "command_" + str(len(self.execution.issues))
                )
        self.assertEqual(self.execution.complete_count, 0)
        self.specialist.alter = lambda r: r
        self.assertEqual(
            (
                await runner.run_once(self.execution.record.work_id, "command_valid")
            ).view.applicability,
            "candidate",
        )

    async def test_case_await_cannot_mutate_validated_execution_snapshot(self):
        runner = self.runner()
        first = await runner.run_once(self.execution.record.work_id, "command_snapshot")
        entered, released = asyncio.Event(), asyncio.Event()
        original = self.execution.record
        original_result = self.execution.results[self.execution.current.attempt_id]

        async def held_snapshot(*, case_id):
            entered.set()
            await released.wait()
            return self.cases.current

        self.cases.snapshot = held_snapshot
        task = asyncio.create_task(runner.inspect(original.work_id))
        await asyncio.wait_for(entered.wait(), 1)
        object.__setattr__(original, "cancel_requested", True)
        object.__setattr__(original_result, "disposition", "cancelled")
        released.set()
        result = await task
        self.assertFalse(result.execution.record.cancel_requested)
        self.assertEqual(result.execution.result.disposition, "eligible_at_commit")
        self.assertEqual(result.request, first.view.request)
        self.assertEqual(result.applicability, "candidate")

    async def test_case_changed_after_computation_is_outdated_not_authority(self):
        runner = self.runner()
        self.specialist.release = asyncio.Event()
        task = asyncio.create_task(
            runner.run_once(self.execution.record.work_id, "command_delayed")
        )
        await asyncio.wait_for(self.specialist.entered.wait(), 1)
        self.cases.current = replace(self.cases.current, request_revision=2)
        self.specialist.release.set()
        run = await task
        self.assertTrue(run.view.result.eligible)
        self.assertEqual(run.view.applicability, "outdated")
        self.assertEqual(run.recorded.disposition, "eligible_at_commit")

    async def test_case_read_failure_and_cancellation_do_not_invent_candidate(self):
        runner = self.runner()
        self.cases.failure = RuntimeError("PRIVATE_CASE_SENTINEL")
        self.assertEqual(
            (
                await runner.run_once(self.execution.record.work_id, "command_case")
            ).view.applicability,
            "unavailable",
        )
        self.cases.failure = None
        self.cases.current = replace(self.cases.current, cancelled=True)
        self.assertEqual(
            (await runner.inspect(self.execution.record.work_id)).applicability, "case_cancelled"
        )

    async def test_cancel_during_http_retains_known_historical_result(self):
        runner = self.runner()
        self.specialist.release = asyncio.Event()
        task = asyncio.create_task(runner.run_once(self.execution.record.work_id, "command_cancel"))
        await asyncio.wait_for(self.specialist.entered.wait(), 1)
        self.execution.record = replace(self.execution.record, cancel_requested=True)
        self.specialist.release.set()
        result = await task
        self.assertEqual(result.recorded.disposition, "cancelled")
        self.assertEqual(result.view.applicability, "execution_ineligible")
        self.assertTrue(result.view.result.eligible)

    async def test_stale_grant_cannot_become_current_candidate(self):
        runner = self.runner()
        self.execution.complete_disposition = "lease_expired"
        result = await runner.run_once(self.execution.record.work_id, "command_stale")
        self.assertEqual(result.recorded.disposition, "lease_expired")
        self.assertEqual(result.view.applicability, "execution_ineligible")

    async def test_cancelled_waiter_retains_slot_and_known_result_progresses(self):
        runner = self.runner(cleanup_ms=20)
        self.specialist.release = asyncio.Event()
        task = asyncio.create_task(runner.run_once(self.execution.record.work_id, "command_waiter"))
        await asyncio.wait_for(self.specialist.entered.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(runner.pending_count, 1)
        with self.assertRaisesRegex(DelegationRunError, "^capacity$"):
            await runner.inspect(self.execution.record.work_id)
        with self.assertRaisesRegex(DelegationRunError, "^cleanup_incomplete$"):
            await runner.close()
        self.specialist.release.set()
        for _ in range(100):
            if runner.pending_count == 0:
                break
            await asyncio.sleep(0.005)
        await runner.close()
        self.assertEqual(self.execution.complete_count, 1)
        self.assertEqual(runner.pending_count, 0)
        self.assertEqual((self.execution.closed, self.specialist.closed), (1, 1))

    async def test_abandoned_issuance_never_starts_late_http(self):
        runner = self.runner(timeout_ms=20)
        self.execution.issue_release = asyncio.Event()
        task = asyncio.create_task(
            runner.run_once(self.execution.record.work_id, "command_issue_wait")
        )
        await asyncio.wait_for(self.execution.issue_entered.wait(), 1)
        with self.assertRaisesRegex(DelegationRunError, "^acknowledgement_unknown$"):
            await task
        self.execution.issue_release.set()
        for _ in range(100):
            if runner.pending_count == 0:
                break
            await asyncio.sleep(0.005)
        self.assertEqual(self.specialist.requests, [])
        self.assertEqual(self.execution.complete_count, 0)
        self.assertEqual(len(self.execution.issues), 1)

    async def test_telemetry_failure_does_not_change_result_and_messages_stay_safe(self):
        class Throwing(logging.Handler):
            def emit(self, record):
                raise RuntimeError("PRIVATE_LOG_SENTINEL")

        logger = logging.getLogger("delegation_reliability.runner")
        handler = Throwing()
        before = logger.level
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        try:
            runner = self.runner()
            result = await runner.run_once(self.execution.record.work_id, "command_logging")
            self.assertEqual(result.view.applicability, "candidate")
            self.assertEqual(runner.metrics()["telemetry_failed"], 1)
            self.assertEqual(str(DelegationRunError([])), "internal_error")
        finally:
            logger.removeHandler(handler)
            logger.setLevel(before)

    async def test_invalid_config_and_stored_bytes_reject_before_invocation(self):
        with self.assertRaisesRegex(DelegationRunError, "^invalid_input$"):
            self.runner(max_active=True)
        runner = self.runner()
        self.execution.record = replace(
            self.execution.record,
            payload=WorkPayload("booking.evaluate_policy", b"{}", self.value.deadline_at_ms),
        )
        with self.assertRaisesRegex(DelegationRunError, "^invalid_stored_state$"):
            await runner.run_once(self.execution.record.work_id, "command_corrupt")
        self.assertEqual(self.execution.issue_count, 0)
        self.assertEqual(self.specialist.requests, [])
