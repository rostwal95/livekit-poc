"""Actual public-facade ownership with in-memory authority; no PG/RTC claim."""

import asyncio
import copy
import json
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from test_fixed_policy_execution import Specialist, setup
from test_runner import FakeCases, FakeExecution

from continuity_lab.work_api import WorkError, WorkSubmission
from delegation_reliability import (
    FixedPolicyCoordinator,
    FixedPolicyRunner,
    NativePolicyApplication,
    NativePolicyError,
    NativePolicyObservation,
    encode_native_policy_observation,
    parse_native_policy_observation,
)
from delegation_reliability.contracts import Scope, canonical


class Authority(FakeExecution):
    """Same original state serves public acceptance and execution ports in tests."""

    def __init__(self, request):
        super().__init__(request)
        self.accepted = False
        self.submit_calls = 0
        self.observe_entered = asyncio.Event()
        self.observe_release = None
        self.find_release = None
        self.find_entered = asyncio.Event()
        self.submit_release = None
        self.submit_entered = asyncio.Event()

    async def find(self, *, idempotency_key):
        self.find_entered.set()
        if self.find_release is not None:
            await self.find_release.wait()
        return (
            self.record
            if self.accepted and idempotency_key == self.record.idempotency_key
            else None
        )

    async def submit(self, *, idempotency_key, payload):
        self.submit_calls += 1
        self.submit_entered.set()
        if self.submit_release is not None:
            await self.submit_release.wait()
        if idempotency_key != self.record.idempotency_key or payload != self.record.payload:
            raise WorkError("identity_conflict")
        created = not self.accepted
        self.accepted = True
        return WorkSubmission(self.record, created)

    async def observe(self, *, work_id):
        self.observe_entered.set()
        if self.observe_release is not None:
            await self.observe_release.wait()
        return await super().observe(work_id=work_id)


class Context:
    def __init__(self, authority):
        self.authority = authority
        self.updates = []

    async def update(self, message, *, silent):
        if not self.authority.accepted:
            raise AssertionError("pending preceded durable acknowledgement")
        self.updates.append((copy.deepcopy(message), silent))


async def until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0)


async def close_until_settled(app):
    async with asyncio.timeout(2):
        while True:
            try:
                await app.close()
                return
            except NativePolicyError as error:
                if error.code != "cleanup_incomplete":
                    raise
                await asyncio.sleep(0)


def owners(values=(10,), *, runner_timeout=5000, read_timeout=1000, cleanup=50):
    request, records = setup(values)
    authority = Authority(request)
    cases = FakeCases(request)
    specialist = Specialist()
    coordinator = FixedPolicyCoordinator(
        executions=authority, scope=request.scope, case_authority=cases, cleanup_ms=20
    )
    runner = FixedPolicyRunner(
        executions=authority,
        scope=request.scope,
        owner_id=str(uuid4()),
        specialist=specialist,
        case_authority=cases,
        evidence=records,
        max_active=2,
        timeout_ms=runner_timeout,
        cleanup_ms=20,
    )
    application = NativePolicyApplication(
        coordinator=coordinator,
        runner=runner,
        request=request,
        evidence=records,
        command_id="native_original",
        read_timeout_ms=read_timeout,
        cleanup_ms=cleanup,
    )
    return application, authority, cases, specialist, coordinator, runner


class NativePolicyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.owned = []
        self.tasks = []

    async def asyncTearDown(self):
        for app, authority, _, specialist, _, _ in self.owned:
            if authority.submit_release is not None:
                authority.submit_release.set()
            if authority.find_release is not None:
                authority.find_release.set()
            if authority.observe_release is not None:
                authority.observe_release.set()
            if specialist.release is not None:
                specialist.release.set()
        for task in self.tasks:
            if not task.done():
                task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        for app, *_ in self.owned:
            await until(
                lambda app=app: (
                    not app.metrics()["runner_pending"] and not app.metrics()["coordinator_pending"]
                )
            )
            await close_until_settled(app)

    def make(self, *args, **kwargs):
        value = owners(*args, **kwargs)
        self.owned.append(value)
        return value

    def evaluate(self, app, authority):
        task = asyncio.create_task(app.evaluate(Context(authority)))
        task.add_done_callback(lambda value: None if value.cancelled() else value.exception())
        self.tasks.append(task)
        return task

    async def test_actual_public_producer_matches_shared_deterministic_contract(self):
        fixture = json.loads(
            (
                Path(__file__).resolve().parents[3]
                / "contracts/delegation/native-policy-view-v1.json"
            ).read_bytes()
        )
        for name, values in [
            ("candidate", (10,)),
            ("missing", ()),
            ("conflicting", (3, 10)),
            ("no_work", (10,)),
        ]:
            with (
                self.subTest(name=name),
                patch("time.time_ns", return_value=1794480000000 * 1_000_000),
            ):
                app, authority, *_ = self.make(values)
                authority.record = replace(
                    authority.record, work_id="11111111-1111-4111-8111-111111111111"
                )
                authority.attempt_id = "22222222-2222-4222-8222-222222222222"
                seen = (
                    await app.inspect_observed()
                    if name == "no_work"
                    else await app.evaluate(Context(authority))
                )
                self.assertEqual(seen.to_wire(), fixture["observations"][name])
                self.assertEqual(authority.issue_count, 0 if name == "no_work" else 1)
                self.assertEqual(authority.complete_count, 0 if name == "no_work" else 1)

    async def test_cancel_before_ack_keeps_acceptance_owner_and_never_starts_run(self):
        app, authority, _, specialist, coordinator, runner = self.make()
        authority.submit_release = asyncio.Event()
        task = self.evaluate(app, authority)
        async with asyncio.timeout(2):
            await authority.submit_entered.wait()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(coordinator.pending_count, 1)
        self.assertEqual(app.metrics()["owned_run"], 1)
        self.assertEqual((await app.inspect_observed()).state, "unknown")
        with self.assertRaisesRegex(NativePolicyError, "^capacity$"):
            await app.evaluate(Context(authority))
        authority.submit_release.set()
        await until(lambda: coordinator.pending_count == 0)
        self.assertEqual((await app.evaluate(Context(authority))).state, "work")
        self.assertEqual(authority.submit_calls, 1)
        self.assertEqual(authority.issue_count, 0)
        self.assertEqual(specialist.requests, [])
        self.assertEqual(runner.pending_count, 0)

    async def test_progress_failure_is_sanitized_and_keeps_the_accepted_run_owner(self):
        app, authority, _, specialist, _, runner = self.make()
        specialist.release = asyncio.Event()

        class BrokenContext(Context):
            async def update(self, message, *, silent):
                await super().update(message, silent=silent)
                raise OSError("SECRET_SENTINEL")

        with self.assertRaisesRegex(NativePolicyError, "^unavailable$") as caught:
            await app.evaluate(BrokenContext(authority))
        self.assertNotIn("SECRET_SENTINEL", str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)
        async with asyncio.timeout(2):
            await specialist.entered.wait()
        self.assertEqual(app.metrics()["owned_run"], 1)
        self.assertEqual(runner.pending_count, 1)
        with self.assertRaisesRegex(NativePolicyError, "^capacity$"):
            await app.evaluate(Context(authority))
        specialist.release.set()
        await until(lambda: runner.pending_count == 0)
        self.assertEqual((await app.inspect_observed()).state, "result")
        self.assertEqual(authority.issue_count, 1)

    async def test_no_work_is_a_definite_original_read_and_immutable_copy(self):
        app, authority, *_ = self.make()
        seen = await app.inspect_observed()
        self.assertEqual(seen.state, "no_work")
        self.assertIsNone(seen.to_wire()["work"])
        document = seen.to_wire()
        document["state"] = "unknown"
        self.assertEqual(seen.state, "no_work")
        self.assertEqual(authority.submit_calls, 0)
        self.assertEqual(authority.issue_count, 0)
        self.assertEqual(parse_native_policy_observation(seen.payload), seen)

    async def test_pre_admission_capacity_allows_explicit_same_request_retry(self):
        app, authority, _, specialist, coordinator, _ = self.make()
        original_binding = app.binding
        original_payload = authority.record.payload
        authority.find_release = asyncio.Event()
        pressure = [
            asyncio.create_task(coordinator.find(authority.record.idempotency_key))
            for _ in range(4)
        ]
        self.tasks.extend(pressure)
        await until(lambda: coordinator.pending_count == 4)
        with self.assertRaisesRegex(NativePolicyError, "^unavailable$"):
            await app.evaluate(Context(authority))
        self.assertEqual(coordinator.metrics()["capacity_rejected"], 1)
        self.assertEqual(authority.submit_calls, 0)
        self.assertFalse(authority.accepted)
        self.assertEqual(authority.issue_count, 0)
        self.assertEqual(specialist.requests, [])

        authority.find_release.set()
        await asyncio.gather(*pressure)
        await until(lambda: coordinator.pending_count == 0)
        # A distinct explicit call retries the same frozen request, not a new key.
        result = await app.evaluate(Context(authority))
        self.assertEqual(result.state, "result")
        self.assertEqual(app.binding, original_binding)
        self.assertEqual(authority.record.payload, original_payload)
        self.assertEqual(authority.submit_calls, 1)
        self.assertEqual(authority.issue_count, 1)
        self.assertEqual(set(authority.issues), {"native_original"})
        self.assertEqual(authority.complete_count, 1)
        self.assertEqual(len(specialist.requests), 1)

    async def test_unknown_submit_ack_never_retries_acceptance_or_issues(self):
        app, authority, _, specialist, coordinator, _ = self.make()
        original_submit = authority.submit

        async def lose_ack(*, idempotency_key, payload):
            await original_submit(idempotency_key=idempotency_key, payload=payload)
            raise WorkError("acknowledgement_unknown")

        with (
            patch.object(authority, "submit", side_effect=lose_ack),
            patch.object(
                authority,
                "find",
                side_effect=[None, WorkError("storage_unavailable")],
            ),
            self.assertRaisesRegex(NativePolicyError, "^acknowledgement_unknown$"),
        ):
            await app.evaluate(Context(authority))
        await until(lambda: coordinator.pending_count == 0)
        self.assertTrue(authority.accepted)
        for _ in range(2):
            self.assertEqual((await app.evaluate(Context(authority))).state, "work")
        self.assertEqual(authority.submit_calls, 1)
        self.assertEqual(authority.issue_count, 0)
        self.assertEqual(authority.complete_count, 0)
        self.assertEqual(specialist.requests, [])

    async def test_runner_capacity_after_acceptance_keeps_calls_lookup_only(self):
        app, authority, _, specialist, _, runner = self.make()
        authority.issue_error = WorkError("capacity")
        with self.assertRaisesRegex(NativePolicyError, "^unavailable$"):
            await app.evaluate(Context(authority))
        await until(lambda: runner.pending_count == 0)
        self.assertTrue(authority.accepted)
        self.assertEqual(authority.submit_calls, 1)
        self.assertEqual(authority.issue_count, 1)
        # Removing pressure must not turn a known acceptance into another run.
        authority.issue_error = None
        self.assertEqual((await app.evaluate(Context(authority))).state, "work")
        self.assertEqual(authority.submit_calls, 1)
        self.assertEqual(authority.issue_count, 1)
        self.assertEqual(authority.complete_count, 0)
        self.assertEqual(specialist.requests, [])

    async def test_ack_before_pending_and_reserved_read_progress_while_held(self):
        app, authority, _, specialist, _, runner = self.make()
        specialist.release = asyncio.Event()
        ctx = Context(authority)
        task = asyncio.create_task(app.evaluate(ctx))
        self.tasks.append(task)
        async with asyncio.timeout(2):
            await specialist.entered.wait()
        self.assertEqual(
            ctx.updates,
            [
                (
                    {"schema_version": 1, "status": "pending", "work_id": authority.record.work_id},
                    True,
                )
            ],
        )
        held = (await app.inspect_observed()).to_wire()
        self.assertEqual(held["state"], "work")
        self.assertIsNone(held["result"])
        self.assertTrue(held["owned_run"])
        self.assertEqual(runner.pending_count, 1)
        specialist.release.set()
        result = await task
        self.assertEqual(result.state, "result")
        self.assertEqual(result.to_wire()["applicability"], "candidate")
        self.assertEqual(authority.complete_count, 1)
        self.assertEqual(
            result.to_wire()["result"]["sha256"], next(iter(authority.results.values())).sha256
        )
        self.assertLessEqual(len(encode_native_policy_observation(result)), 4096)

    async def test_cancelled_sdk_waiter_does_not_free_actual_run_or_read_slot(self):
        app, authority, _, specialist, _, runner = self.make()
        specialist.release = asyncio.Event()
        task = self.evaluate(app, authority)
        async with asyncio.timeout(2):
            await specialist.entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(app.metrics()["owned_run"], 1)
        self.assertEqual(runner.pending_count, 1)
        with self.assertRaisesRegex(NativePolicyError, "^capacity$"):
            await app.evaluate(Context(authority))
        held = (await app.inspect_observed()).to_wire()
        self.assertEqual(held["tool_waiter"], "stopped_waiting")
        self.assertEqual(held["state"], "work")
        self.assertFalse(authority.record.cancel_requested)
        self.assertEqual(authority.issue_count, 1)
        self.assertEqual(len(specialist.requests), 1)
        specialist.release.set()
        await until(lambda: runner.pending_count == 0)
        self.assertEqual((await app.inspect_observed()).state, "result")
        self.assertEqual((await app.evaluate(Context(authority))).state, "result")
        self.assertEqual(authority.issue_count, 1)

    async def test_completed_run_does_not_compete_with_an_existing_card_read(self):
        app, authority, _, specialist, *_ = self.make()
        specialist.release = asyncio.Event()
        tool = self.evaluate(app, authority)
        async with asyncio.timeout(2):
            await specialist.entered.wait()
        authority.find_release = asyncio.Event()
        authority.find_entered.clear()
        read = asyncio.create_task(app.inspect_observed())
        read.add_done_callback(lambda task: None if task.cancelled() else task.exception())
        self.tasks.append(read)
        async with asyncio.timeout(2):
            await authority.find_entered.wait()
        specialist.release.set()
        try:
            result = await tool
            self.assertEqual(result.state, "result")
            self.assertFalse(read.done())
            self.assertEqual(authority.issue_count, 1)
        finally:
            authority.find_release.set()
        self.assertEqual((await read).state, "result")

    async def test_internal_runner_timeout_done_wrapper_does_not_free_run(self):
        app, authority, _, specialist, _, runner = self.make(runner_timeout=40)
        specialist.release = asyncio.Event()
        task = self.evaluate(app, authority)
        async with asyncio.timeout(2):
            await specialist.entered.wait()
        with self.assertRaisesRegex(NativePolicyError, "^acknowledgement_unknown$"):
            await task
        self.assertEqual(runner.pending_count, 1)
        self.assertEqual(app.metrics()["owned_run"], 1)
        with self.assertRaisesRegex(NativePolicyError, "^capacity$"):
            await app.evaluate(Context(authority))
        self.assertEqual((await app.inspect_observed()).state, "work")
        self.assertEqual(authority.issue_count, 1)
        specialist.release.set()
        await until(lambda: runner.pending_count == 0)
        self.assertEqual((await app.inspect_observed()).state, "result")
        self.assertFalse(authority.record.cancel_requested)

    async def test_original_result_remains_while_case_is_outdated(self):
        app, authority, cases, specialist, *_ = self.make()
        specialist.release = asyncio.Event()
        task = self.evaluate(app, authority)
        async with asyncio.timeout(2):
            await specialist.entered.wait()
        cases.current = replace(cases.current, request_revision=cases.current.request_revision + 1)
        specialist.release.set()
        seen = (await task).to_wire()
        self.assertEqual(seen["state"], "outdated")
        self.assertEqual(seen["applicability"], "outdated")
        self.assertEqual(seen["result"]["disposition"], "eligible_at_commit")
        self.assertEqual(seen["binding"]["request_revision"], cases.current.request_revision - 1)
        self.assertNotIn("currentCaseRevision", json.dumps(seen))
        self.assertNotIn("caseObservedAt", json.dumps(seen))

    async def test_missing_and_conflicting_are_null_clarifications(self):
        for values, expected in [((), "missing"), ((3, 10), "conflicting"), ((8, 8), "none")]:
            app, authority, *_ = self.make(values)
            seen = (await app.evaluate(Context(authority))).to_wire()
            self.assertEqual(seen["result"]["uncertainty"], expected)
            self.assertIs(seen["result"]["eligible"], True if expected == "none" else None)
            self.assertEqual(len(seen["result"]["fact_refs"]), len(values))

    async def test_abandoned_read_keeps_its_reservation_and_no_writes(self):
        app, authority, _, specialist, _, runner = self.make(read_timeout=20)
        specialist.release = asyncio.Event()
        task = self.evaluate(app, authority)
        async with asyncio.timeout(2):
            await specialist.entered.wait()
        authority.observe_release = asyncio.Event()
        seen = await app.inspect_observed()
        self.assertEqual(seen.state, "unknown")
        self.assertEqual(runner.pending_count, 2)
        self.assertEqual(app.metrics()["read_reserved"], 1)
        with self.assertRaisesRegex(NativePolicyError, "^capacity$"):
            await app.inspect_observed()
        self.assertEqual(authority.complete_count, 0)
        authority.observe_release.set()
        specialist.release.set()
        await task
        await until(lambda: runner.pending_count == 0)
        self.assertEqual((await app.inspect_observed()).state, "result")

    async def test_close_attempts_independent_owners_and_retries_actual_settlement(self):
        app, authority, _, specialist, coordinator, runner = self.make()
        specialist.release = asyncio.Event()
        task = self.evaluate(app, authority)
        async with asyncio.timeout(2):
            await specialist.entered.wait()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        with self.assertRaisesRegex(NativePolicyError, "^cleanup_incomplete$"):
            await app.close()
        self.assertGreaterEqual(authority.closed, 1)
        self.assertEqual(coordinator.pending_count, 0)
        self.assertEqual(runner.pending_count, 1)
        self.assertEqual(app.metrics()["owned_run"], 1)
        specialist.release.set()
        await until(lambda: runner.pending_count == 0)
        await close_until_settled(app)
        self.assertEqual(app.metrics()["owned_run"], 0)
        self.assertEqual(app.metrics()["read_reserved"], 0)
        with self.assertRaisesRegex(NativePolicyError, "^closed$"):
            await app.evaluate(Context(authority))

    async def test_wrong_result_never_commits_and_logging_failure_is_contained(self):
        app, authority, _, specialist, *_ = self.make()
        specialist.alter = lambda value: replace(value, eligible=False)
        with self.assertRaisesRegex(NativePolicyError, "^unavailable$"):
            await app.evaluate(Context(authority))
        self.assertEqual(authority.complete_count, 0)
        later, fresh, *_ = self.make()
        with patch(
            "delegation_reliability.native_policy.LOGGER.info",
            side_effect=OSError("SECRET_SENTINEL"),
        ):
            self.assertEqual((await later.evaluate(Context(fresh))).state, "result")
        self.assertGreater(later.metrics()["telemetry_failures"], 0)

    async def test_zero_foreign_missing_extra_sources_fail_before_acceptance(self):
        _app, authority, _, _, coordinator, runner = self.make()
        request, records = setup()
        for value, evidence in [
            (replace(request, request_revision=0), records),
            (request, (records[0],)),
            (request, records + (records[0],)),
            (
                request,
                (replace(records[0], scope=Scope("foreign", request.scope.account_id)), records[1]),
            ),
        ]:
            with self.assertRaisesRegex(NativePolicyError, "^invalid_input$"):
                NativePolicyApplication(
                    coordinator=coordinator,
                    runner=runner,
                    request=value,
                    evidence=evidence,
                    command_id="native_original",
                )
        self.assertEqual(authority.submit_calls, 0)
        self.assertEqual(authority.issue_count, 0)

    async def test_closed_codec_rejects_forged_fields_types_witnesses_and_overflow(self):
        app, authority, *_ = self.make()
        good = (await app.evaluate(Context(authority))).to_wire()
        reversed_json = json.dumps(dict(reversed(list(good.items()))), indent=2).encode()
        self.assertEqual(parse_native_policy_observation(reversed_json).to_wire(), good)
        changes = [
            lambda v: v.update(extra="SECRET_SENTINEL"),
            lambda v: v.update(app_read_completed_at_ms=True),
            lambda v: v["binding"].update(request_revision=0),
            lambda v: v["result"].update(eligible=None),
            lambda v: v["result"]["fact_refs"][0].update(source_id="foreign"),
            lambda v: v["result"].update(attempt_id=str(uuid4())),
            lambda v: v.update(state="unknown"),
            lambda v: v["work"].update(cancel_requested="false"),
            lambda v: v["result"]["rule_refs"][0].update(minimum_notice_days=8),
        ]
        for change in changes:
            value = copy.deepcopy(good)
            change(value)
            with self.assertRaisesRegex(NativePolicyError, "^invalid_observation$"):
                parse_native_policy_observation(canonical(value))
        for payload in [b" " * 4097, b"\xff", b'{"state":"x","state":"x"}', b'{"a":NaN}']:
            with self.assertRaisesRegex(NativePolicyError, "^invalid_observation$"):
                NativePolicyObservation(payload)
