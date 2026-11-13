"""Origin-first acceptance and v3 execution through explicit fake public ports."""

import asyncio
import copy
import hashlib
import time
import unittest
from dataclasses import FrozenInstanceError, replace
from uuid import uuid4

from test_coordinator import FakeCases as AcceptanceCases
from test_coordinator import FakeExecutions
from test_coordinator import request as legacy_request
from test_fixed_policy_execution import Specialist
from test_fixed_policy_execution import setup as fixed_setup
from test_runner import FakeCases, FakeExecution

from continuity_lab.work_api import WorkError, WorkPayload, WorkSubmission
from delegation_reliability import (
    ChannelPolicyCoordinator,
    ChannelPolicyOrigin,
    ChannelPolicyRunner,
    CoordinatorError,
    DelegationCoordinator,
    DelegationRunError,
    FixedPolicyCoordinator,
    channel_policy_key,
    encode_channel_policy_request,
    encode_channel_policy_result,
    produce_channel_policy_request,
)
from delegation_reliability.contracts import Scope, canonical
from delegation_reliability.fixed_policy_contracts import (
    FixedPolicyRequest,
    encode_fixed_policy_result,
    produce_fixed_policy_request,
)


def setup(values=(10,)):
    inner, evidence = fixed_setup(values)
    origin = ChannelPolicyOrigin(
        "p2.prepared_dispatch.v1",
        str(uuid4()),
        str(uuid4()),
        str(uuid4()),
        hashlib.sha256(b"original P2 input").hexdigest(),
        len(b"original P2 input"),
    )
    raw = inner.to_wire()
    raw.pop("input_fingerprint")
    raw["delegation_id"] = channel_policy_key(origin.operation_key)
    inner = produce_fixed_policy_request(raw)
    return wrap(inner, origin), evidence


def wrap(inner, origin):
    return produce_channel_policy_request(
        {
            "schema_version": 1,
            "kind": "delegation.request",
            "capability": "booking.evaluate_policy",
            "input_schema_version": 3,
            "origin": origin.to_wire(),
            "request": inner.to_wire(),
        }
    )


def proposed(value, **changes):
    raw = value.request.to_wire()
    raw.pop("input_fingerprint")
    raw.update(changes)
    return wrap(produce_fixed_policy_request(raw), value.origin)


class CountedExecutions(FakeExecutions):
    def __init__(self, value):
        super().__init__(value)
        self.finds = 0

    async def find(self, *, idempotency_key):
        self.finds += 1
        return await super().find(idempotency_key=idempotency_key)


class ChannelAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.value, self.evidence = setup()
        self.port = CountedExecutions(self.value)
        self.cases = AcceptanceCases(self.value)
        self.owners = []

    async def asyncTearDown(self):
        if self.port.release is not None:
            self.port.release.set()
        for owner in self.owners:
            await owner.close()

    def coordinator(self, **options):
        owner = ChannelPolicyCoordinator(
            executions=self.port,
            scope=self.value.scope,
            case_authority=self.cases,
            **options,
        )
        self.owners.append(owner)
        return owner

    async def test_scope_is_copied_immutable_read_only_configuration_without_io(self):
        supplied = Scope(self.value.scope.tenant_id, self.value.scope.account_id)
        owner = ChannelPolicyCoordinator(
            executions=self.port, scope=supplied, case_authority=self.cases
        )
        self.owners.append(owner)
        self.assertEqual(owner.scope, supplied)
        self.assertIsNot(owner.scope, supplied)
        object.__setattr__(supplied, "account_id", "changed_caller_object")
        self.assertEqual(owner.scope, self.value.scope)
        with self.assertRaises(AttributeError):
            owner.scope = Scope("other", "other")
        with self.assertRaises(FrozenInstanceError):
            owner.scope.account_id = "other"
        self.assertEqual((self.port.finds, self.port.calls, self.cases.calls), (0, 0, 0))

    async def test_exact_submit_retries_attempt_but_generated_changes_require_origin_accept(self):
        owner = self.coordinator()
        first = await owner.submit(self.value)
        retry = proposed(self.value, attempt={"attempt_id": "attempt_retry", "number": 2})
        self.assertEqual((await owner.submit(retry)).view, first.view)
        wire = copy.deepcopy(self.value.request.to_wire())
        wire["evidence"][0]["sha256"] = "e" * 64
        changed = proposed(
            self.value,
            deadline_at_ms=time.time_ns() // 1_000_000 - 1,
            evidence=wire["evidence"],
        )
        self.cases.current = replace(self.cases.current, request_revision=2, cancelled=True)
        with self.assertRaisesRegex(CoordinatorError, "^identity_conflict$"):
            await owner.submit(changed)
        retained = await owner.accept(changed)
        self.assertFalse(retained.created)
        self.assertEqual(retained.view, first.view)
        self.assertEqual(
            retained.view.record.payload.body, encode_channel_policy_request(self.value)
        )
        self.assertEqual((self.port.calls, self.cases.calls), (1, 1))

    async def test_entire_origin_and_stable_route_fields_conflict_without_alternate_key(self):
        owner = self.coordinator()
        first = await owner.accept(self.value)
        for origin in (
            replace(self.value.origin, profile_id=str(uuid4())),
            replace(self.value.origin, input_receipt_id=str(uuid4())),
            replace(self.value.origin, payload_sha256="e" * 64),
            replace(
                self.value.origin, payload_byte_length=self.value.origin.payload_byte_length + 1
            ),
        ):
            with (
                self.subTest(origin=origin),
                self.assertRaisesRegex(CoordinatorError, "^identity_conflict$"),
            ):
                await owner.accept(wrap(self.value.request, origin))
        for changes in (
            {"case_id": "other_case"},
            {"request_revision": 2},
            {"result_route": {"conversation_id": "other_conversation"}},
        ):
            with (
                self.subTest(changes=changes),
                self.assertRaisesRegex(CoordinatorError, "^identity_conflict$"),
            ):
                await owner.accept(proposed(self.value, **changes))
        foreign = proposed(self.value, scope={"tenant_id": "other", "account_id": "other"})
        before = self.port.finds
        with self.assertRaisesRegex(CoordinatorError, "^unauthorized$"):
            await owner.accept(foreign)
        self.assertEqual(self.port.finds, before)
        self.assertEqual((self.port.calls, self.cases.calls, len(self.port.records)), (1, 1, 1))
        self.assertEqual((await owner.get(first.view.record.work_id)).request, self.value)

    async def test_two_actual_misses_keep_exact_created_winner_and_reconcile_loser_once(self):
        owner = self.coordinator()
        self.port.release = asyncio.Event()
        other = proposed(self.value, deadline_at_ms=self.value.deadline_at_ms + 1000)
        first = asyncio.create_task(owner.accept(self.value))
        await self.port.entered.wait()
        second = asyncio.create_task(owner.accept(other))
        async with asyncio.timeout(1):
            while self.cases.calls < 2:
                await asyncio.sleep(0)
        self.port.release.set()
        values = await asyncio.gather(first, second)
        winner = next(value for value in values if value.created)
        self.assertEqual(sum(value.created for value in values), 1)
        self.assertEqual(values[0].view, values[1].view)
        self.assertIn(winner.view.request, (self.value, other))
        self.assertEqual((self.port.calls, self.port.finds, len(self.port.records)), (2, 3, 1))

    async def test_ack_unknown_commit_has_one_submit_and_one_reconciliation_find(self):
        owner = self.coordinator()
        self.port.ack_loss = True
        result = await owner.accept(self.value)
        self.assertFalse(result.created)
        self.assertEqual(result.view.request, self.value)
        self.assertEqual((self.port.calls, self.port.finds), (1, 2))

    async def test_missing_or_failed_ambiguous_lookup_preserves_unknown_without_resubmit(self):
        for lookup_fails in (False, True):
            with self.subTest(lookup_fails=lookup_fails):

                class Missing(CountedExecutions):
                    def __init__(inner, value, fail):
                        super().__init__(value)
                        inner.fail = fail

                    async def find(inner, *, idempotency_key):
                        inner.finds += 1
                        if inner.fail and inner.calls:
                            raise WorkError("storage_unavailable")

                port = Missing(self.value, lookup_fails)
                port.failure = WorkError("acknowledgement_unknown")
                owner = ChannelPolicyCoordinator(
                    executions=port, scope=self.value.scope, case_authority=self.cases
                )
                try:
                    with self.assertRaisesRegex(CoordinatorError, "^acknowledgement_unknown$"):
                        await owner.accept(self.value)
                    self.assertEqual((port.calls, port.finds), (1, 2))
                finally:
                    await owner.close()

    async def test_created_true_full_canonical_guard_includes_attempt_for_all_versions(self):
        class Substituted(CountedExecutions):
            async def submit(inner, *, idempotency_key, payload):
                response = await super().submit(idempotency_key=idempotency_key, payload=payload)
                wire = copy.deepcopy(self_wire)
                target = wire.get("request", wire)
                target["attempt"] = {"attempt_id": "attempt_substituted", "number": 2}
                body = canonical(wire)
                altered = replace(
                    response.record,
                    payload=WorkPayload(payload.operation, body, payload.deadline_at_ms),
                )
                return WorkSubmission(altered, True)

        inner2, _ = fixed_setup()
        for request, facade in (
            (legacy_request(), DelegationCoordinator),
            (inner2, FixedPolicyCoordinator),
            (self.value, ChannelPolicyCoordinator),
        ):
            self_wire = request.to_wire()
            port = Substituted(request)
            owner = facade(
                executions=port, scope=request.scope, case_authority=AcceptanceCases(request)
            )
            try:
                with (
                    self.subTest(facade=facade),
                    self.assertRaisesRegex(CoordinatorError, "^invalid_stored_state$"),
                ):
                    await owner.submit(request)
                self.assertEqual(port.calls, 1)
            finally:
                await owner.close()

    async def test_timeout_retains_actual_write_capacity_then_close_retry(self):
        owner = self.coordinator(max_active=2, timeout_ms=20, cleanup_ms=20)
        self.port.release = asyncio.Event()
        with self.assertRaisesRegex(CoordinatorError, "^acknowledgement_unknown$"):
            await owner.accept(self.value)
        self.assertEqual(owner.pending_count, 1)
        self.assertIsNone(await owner.find("unrelated"))
        with self.assertRaisesRegex(CoordinatorError, "^cleanup_incomplete$"):
            await owner.close()
        self.assertEqual(owner.pending_count, 1)
        self.port.release.set()
        await owner.close()
        self.assertEqual(owner.pending_count, 0)
        self.assertEqual(self.port.calls, 1)

    async def test_origin_created_true_cannot_substitute_another_valid_generated_proposal(self):
        other = proposed(self.value, deadline_at_ms=self.value.deadline_at_ms + 1000)

        class Substituted(CountedExecutions):
            async def submit(inner, *, idempotency_key, payload):
                response = await super().submit(idempotency_key=idempotency_key, payload=payload)
                return WorkSubmission(
                    replace(
                        response.record,
                        payload=WorkPayload(
                            payload.operation,
                            encode_channel_policy_request(other),
                            other.deadline_at_ms,
                        ),
                    ),
                    True,
                )

        port = Substituted(self.value)
        owner = ChannelPolicyCoordinator(
            executions=port, scope=self.value.scope, case_authority=self.cases
        )
        try:
            with self.assertRaisesRegex(CoordinatorError, "^invalid_stored_state$"):
                await owner.accept(self.value)
            self.assertEqual(port.calls, 1)
            # The genuine stored candidate still resolves as a known original winner.
            self.assertEqual((await owner.accept(other)).view.request, self.value)
        finally:
            await owner.close()

    async def test_cancelled_preflight_stays_owned_and_never_writes_after_release(self):
        owner = self.coordinator(max_active=1, cleanup_ms=20)
        self.cases.release = asyncio.Event()
        pending = asyncio.create_task(owner.accept(self.value))
        await self.cases.entered.wait()
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending
        self.assertEqual(owner.pending_count, 1)
        with self.assertRaisesRegex(CoordinatorError, "^capacity$"):
            await owner.find(self.value.delegation_id)
        self.cases.release.set()
        await owner.close()
        self.assertEqual(self.port.calls, 0)


class ChannelRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.value, self.evidence = setup()
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
        owner = ChannelPolicyRunner(
            executions=self.port,
            scope=self.value.scope,
            owner_id=str(uuid4()),
            specialist=self.specialist,
            case_authority=self.cases,
            evidence=self.evidence,
            **options,
        )
        self.owners.append(owner)
        return owner

    async def test_full_original3_bytes_and_fingerprints_survive_inner2_issued_transport(self):
        owner = self.runner()
        run = await owner.run_once(self.port.record.work_id, "run_channel")
        sent = self.specialist.requests[0]
        self.assertIs(type(sent), FixedPolicyRequest)
        self.assertNotEqual(sent.attempt, self.value.attempt)
        self.assertEqual(sent.input_fingerprint, self.value.request.input_fingerprint)
        self.assertEqual(run.view.result.input_fingerprint, self.value.input_fingerprint)
        self.assertEqual(run.view.result.result.attempt_id, sent.attempt.attempt_id)
        self.assertEqual(self.port.record.payload.body, encode_channel_policy_request(self.value))
        self.assertEqual(run.recorded.body, encode_channel_policy_result(run.view.result))
        self.assertNotEqual(run.recorded.body, encode_fixed_policy_result(run.view.result.result))
        self.assertEqual(run.view.result.result.rule_refs[0].minimum_notice_days, 7)
        self.assertEqual(run.view.result.result.fact_refs[0].days_before_arrival, 10)
        self.assertEqual(run.view.applicability, "candidate")
        again = await owner.run_once(self.port.record.work_id, "run_channel")
        self.assertFalse(again.invoked)
        self.assertEqual((len(self.specialist.requests), self.port.complete_count), (1, 1))

    async def test_inner_fact_forgery_rejects_before_completing_outer_result(self):
        self.specialist.alter = lambda value: replace(value, eligible=False)
        owner = self.runner()
        with self.assertRaisesRegex(DelegationRunError, "^invalid_result$"):
            await owner.run_once(self.port.record.work_id, "forged")
        self.assertEqual((len(self.specialist.requests), self.port.complete_count), (1, 0))

    async def test_new_source_records_cannot_replace_original_winning_refs_or_invoke(self):
        _, newer = fixed_setup((3,))
        self.evidence = newer
        owner = self.runner()
        with self.assertRaisesRegex(DelegationRunError, "^invalid_result$"):
            await owner.run_once(self.port.record.work_id, "wrong_sources")
        self.assertEqual((len(self.specialist.requests), self.port.complete_count), (0, 0))

    async def test_held_inner_work_retains_runner_slot_and_close_until_actual_settlement(self):
        completed, execution_closed, specialist_closed = (asyncio.Event() for _ in range(3))

        class ObservedExecution(FakeExecution):
            async def complete(port, *, attempt, body):
                result = await super().complete(attempt=attempt, body=body)
                completed.set()
                return result

            async def close(port):
                await super().close()
                execution_closed.set()

        class ObservedSpecialist(Specialist):
            async def close(port):
                await super().close()
                specialist_closed.set()

        self.port = ObservedExecution(self.value)
        self.specialist = ObservedSpecialist()
        self.specialist.release = asyncio.Event()
        owner = self.runner(timeout_ms=20, cleanup_ms=20)
        with self.assertRaisesRegex(DelegationRunError, "^acknowledgement_unknown$"):
            await owner.run_once(self.port.record.work_id, "held")
        self.assertEqual(owner.pending_count, 1)
        with self.assertRaisesRegex(DelegationRunError, "^capacity$"):
            await owner.inspect(self.port.record.work_id)
        with self.assertRaisesRegex(DelegationRunError, "^cleanup_incomplete$"):
            await owner.close()
        self.assertFalse(completed.is_set())
        self.assertFalse(execution_closed.is_set())
        self.assertFalse(specialist_closed.is_set())
        self.assertEqual((self.port.closed, self.specialist.closed), (0, 0))
        self.specialist.release.set()
        # Observe actual result persistence and both owned ports closing before
        # asking the already retained close operation for its final observation.
        await asyncio.wait_for(
            asyncio.gather(completed.wait(), execution_closed.wait(), specialist_closed.wait()),
            timeout=1,
        )
        await owner.close()
        self.assertEqual(owner.pending_count, 0)
        self.assertEqual(self.port.complete_count, 1)
        self.assertEqual((self.port.closed, self.specialist.closed), (1, 1))
