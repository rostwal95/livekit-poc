"""Typed v2 facade/owner tests; actual PostgreSQL has its separate twelve-case gate."""

import asyncio
import copy
import hashlib
import json
import time
import unittest
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from test_coordinator import FakeCases as AcceptanceCases
from test_coordinator import FakeExecutions
from test_runner import FakeCases, FakeExecution

from delegation_reliability import (
    CaseSnapshot,
    CoordinatorError,
    DelegationCoordinator,
    DelegationRunError,
    DelegationRunner,
    FixedPolicyCoordinator,
    FixedPolicyResultObservation,
    FixedPolicyRunner,
)
from delegation_reliability.contracts import Attempt, ContractError, canonical
from delegation_reliability.fixed_policy import verify_fixed_policy_facts
from delegation_reliability.fixed_policy_contracts import (
    FixedPolicyFactEvidence,
    encode_fixed_policy_request,
    parse_fixed_policy_result,
    produce_fixed_policy_request,
)
from delegation_reliability.security import EvidenceRecord

FIXTURE = json.loads(
    (Path(__file__).resolve().parents[3] / "contracts/delegation/fixed-policy-v2.json").read_bytes()
)


def setup(values=(10,)):
    source = copy.deepcopy(FIXTURE["producer_input"])
    source["deadline_at_ms"] = time.time_ns() // 1_000_000 + 30_000
    facts = json.loads(FIXTURE["facts_body_utf8"])
    facts["observations"] = [
        {"fact_id": f"notice_{i}", "days_before_arrival": v} for i, v in enumerate(values)
    ]
    body = canonical(facts)
    source["evidence"][1].update(sha256=hashlib.sha256(body).hexdigest(), byte_length=len(body))
    value = produce_fixed_policy_request(source)
    records = (
        EvidenceRecord(value.scope, value.evidence[0], FIXTURE["policy_body_utf8"].encode()),
        EvidenceRecord(value.scope, value.evidence[1], body),
    )
    return value, records


def result_for(value, records):
    result = replace(
        parse_fixed_policy_result(canonical(FIXTURE["result"])),
        scope=value.scope,
        delegation_id=value.delegation_id,
        case_id=value.case_id,
        request_revision=value.request_revision,
        attempt_id=value.attempt.attempt_id,
        input_fingerprint=value.input_fingerprint,
        completed_at_ms=time.time_ns() // 1_000_000,
    )
    observations = json.loads(records[1].body)["observations"]
    facts = tuple(
        FixedPolicyFactEvidence(
            records[1].reference.source_id,
            records[1].reference.version,
            records[1].reference.sha256,
            x["fact_id"],
            x["days_before_arrival"],
        )
        for x in observations
    )
    values = {x.days_before_arrival for x in facts}
    uncertainty = "missing" if not values else "none" if len(values) == 1 else "conflicting"
    return replace(
        result,
        fact_refs=facts,
        eligible=(next(iter(values)) >= 7 if uncertainty == "none" else None),
        uncertainty=uncertainty,
    )


class Specialist:
    def __init__(self):
        self.requests = []
        self.entered = asyncio.Event()
        self.release = None
        self.alter = lambda value: value
        self.closed = 0

    async def invoke_observed(self, request, *, evidence):
        self.requests.append(request)
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        result = self.alter(result_for(request, evidence))
        now = time.time_ns() // 1_000_000
        # The runner independently verifies even a supplied port's typed observation.
        applicability = (
            "expired"
            if now >= request.deadline_at_ms
            else "candidate"
            if result.uncertainty == "none"
            else "clarification"
        )
        return FixedPolicyResultObservation(result, applicability, now)

    async def close(self):
        self.closed += 1


class FixedExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.value, self.records = setup()
        self.port = FakeExecution(self.value)
        self.cases = FakeCases(self.value)
        self.specialist = Specialist()
        self.owners = []

    async def asyncTearDown(self):
        if self.specialist.release is not None:
            self.specialist.release.set()
        for owner in self.owners:
            await owner.close()

    def runner(self, **options):
        value = FixedPolicyRunner(
            executions=self.port,
            scope=self.value.scope,
            owner_id=str(uuid4()),
            specialist=self.specialist,
            case_authority=self.cases,
            evidence=self.records,
            **options,
        )
        self.owners.append(value)
        return value

    async def test_original_v2_acceptance_and_attempt_replay(self):
        port = FakeExecutions(self.value)
        coord = FixedPolicyCoordinator(
            executions=port, scope=self.value.scope, case_authority=AcceptanceCases(self.value)
        )
        self.owners.append(coord)
        first = await coord.submit(self.value)
        second = await coord.submit(replace(self.value, attempt=Attempt("fresh_proposal", 2)))
        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(second.view, first.view)
        self.assertEqual(port.calls, 1)
        self.assertEqual(first.view.record.payload.body, encode_fixed_policy_request(self.value))
        changed, _ = setup((3,))
        with self.assertRaises(CoordinatorError) as caught:
            await coord.submit(changed)
        self.assertEqual(caught.exception.code, "identity_conflict")
        self.assertEqual(port.calls, 1)

    async def test_v1_facade_rejects_v2_and_zero_revision_never_submits(self):
        port = FakeExecutions(self.value)
        cases = AcceptanceCases(self.value)
        legacy = DelegationCoordinator(
            executions=port, scope=self.value.scope, case_authority=cases
        )
        self.owners.append(legacy)
        with self.assertRaises(CoordinatorError) as caught:
            await legacy.submit(self.value)
        self.assertEqual(caught.exception.code, "invalid_input")
        coord = FixedPolicyCoordinator(
            executions=port, scope=self.value.scope, case_authority=cases
        )
        self.owners.append(coord)
        cases.current = CaseSnapshot(self.value.scope, self.value.case_id, 0, False)
        with self.assertRaises(CoordinatorError):
            await coord.submit(self.value)
        self.assertEqual(port.calls, 0)

    async def test_malformed_observation_classification_never_completes_then_progress(self):
        class InvalidObservation(Specialist):
            async def invoke_observed(port, request, *, evidence):
                value = await super().invoke_observed(request, evidence=evidence)
                return replace(value, applicability=port.classification)

        for classification in (None, "unsupported", True):
            with self.subTest(classification=classification):
                self.port = FakeExecution(self.value)
                self.specialist = InvalidObservation()
                self.specialist.classification = classification
                with self.assertRaises(DelegationRunError) as caught:
                    await self.runner().run_once(self.port.record.work_id, "malformed")
                self.assertEqual(caught.exception.code, "invalid_result")
                self.assertEqual((self.port.complete_count, len(self.specialist.requests)), (0, 1))
        self.port, self.specialist = FakeExecution(self.value), Specialist()
        result = await self.runner().run_once(self.port.record.work_id, "later_valid")
        self.assertEqual(result.view.applicability, "candidate")
        self.assertEqual(self.port.complete_count, 1)

    async def test_default_v1_runner_rejects_v2_before_issue_or_completion(self):
        runner = DelegationRunner(
            executions=self.port,
            scope=self.value.scope,
            owner_id=str(uuid4()),
            specialist=self.specialist,
            case_authority=self.cases,
            evidence=self.records,
        )
        self.owners.append(runner)
        for action in (
            lambda: runner.inspect(self.port.record.work_id),
            lambda: runner.run_once(self.port.record.work_id, "v1_must_reject"),
        ):
            with self.assertRaises(DelegationRunError) as caught:
                await action()
            self.assertEqual(caught.exception.code, "invalid_stored_state")
        self.assertEqual(
            (self.port.issue_count, self.port.complete_count, len(self.specialist.requests)),
            (0, 0, 0),
        )

    async def test_new_v2_result_and_known_replay_no_second_issue(self):
        runner = self.runner()
        first = await runner.run_once(self.port.record.work_id, "original")
        self.assertTrue(first.invoked)
        self.assertEqual(first.view.applicability, "candidate")
        self.assertEqual(first.recorded.disposition, "eligible_at_commit")
        self.assertEqual(first.view.request, self.value)
        self.assertNotEqual(self.specialist.requests[0].attempt, self.value.attempt)
        again = await runner.run_once(self.port.record.work_id, "original")
        self.assertFalse(again.invoked)
        self.assertEqual(
            (self.port.issue_count, self.port.complete_count, len(self.specialist.requests)),
            (1, 1, 1),
        )
        self.assertEqual(again.view.result, first.view.result)

    async def test_missing_and_conflicting_results_remain_clarification(self):
        for values in [(), (10, 3)]:
            self.value, self.records = setup(values)
            self.port, self.cases, self.specialist = (
                FakeExecution(self.value),
                FakeCases(self.value),
                Specialist(),
            )
            run = await self.runner().run_once(self.port.record.work_id, "clarify")
            self.assertEqual(run.view.applicability, "clarification")
            self.assertIsNone(run.view.result.eligible)
            self.assertEqual(self.port.complete_count, 1)

    async def test_schema_valid_wrong_facts_never_complete_even_when_expired(self):
        runner = self.runner()
        self.specialist.alter = lambda value: replace(value, eligible=False)
        with self.assertRaises(DelegationRunError) as caught:
            await runner.run_once(self.port.record.work_id, "forged")
        self.assertEqual(caught.exception.code, "invalid_result")
        self.assertEqual(self.port.complete_count, 0)
        now = time.time_ns() // 1_000_000
        with self.assertRaises(ContractError):
            verify_fixed_policy_facts(
                self.value,
                self.specialist.alter(result_for(self.value, self.records)),
                self.records,
                observed_at_ms=max(now, self.value.deadline_at_ms + 1),
            )

    async def test_cancelled_late_fact_retained_without_current_applicability(self):
        self.port.complete_disposition = "cancelled"
        runner = self.runner()
        run = await runner.run_once(self.port.record.work_id, "cancelled")
        self.assertEqual(run.recorded.disposition, "cancelled")
        self.assertEqual(run.view.applicability, "execution_ineligible")
        self.assertTrue(run.view.result.eligible)

    async def test_known_eligible_fact_survives_later_cancel_and_old_lease(self):
        runner = self.runner()
        run = await runner.run_once(self.port.record.work_id, "known")
        self.port.record = replace(self.port.record, cancel_requested=True)
        self.port.current = replace(
            self.port.current, lease_until_ms=self.port.current.issued_at_ms + 1
        )
        view = await runner.inspect(self.port.record.work_id)
        self.assertEqual(view.execution.result, run.recorded)
        self.assertEqual(view.applicability, "execution_ineligible")
        self.assertEqual(self.port.complete_count, 1)

    async def test_abandoned_held_invocation_retains_owner_until_release(self):
        self.specialist.release = asyncio.Event()
        runner = self.runner(cleanup_ms=20)
        pending = asyncio.create_task(runner.run_once(self.port.record.work_id, "held"))
        entered = asyncio.create_task(self.specialist.entered.wait())
        try:
            done, _ = await asyncio.wait(
                {pending, entered}, timeout=1, return_when=asyncio.FIRST_COMPLETED
            )
            self.assertIn(entered, done)
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            self.assertEqual(runner.pending_count, 1)
            with self.assertRaises(DelegationRunError) as caught:
                await runner.close()
            self.assertEqual(caught.exception.code, "cleanup_incomplete")
            self.assertEqual(self.port.closed, 0)
            self.specialist.release.set()
            await runner.close()
            self.assertEqual(runner.pending_count, 0)
            self.assertEqual(self.port.complete_count, 1)
        finally:
            self.specialist.release.set()
            entered.cancel()
            await asyncio.gather(pending, entered, return_exceptions=True)
