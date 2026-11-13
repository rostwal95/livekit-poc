"""Public example orchestration checks; actual stores/processes have separate gates."""

import asyncio
import importlib.util
import sys
import unittest
from dataclasses import replace
from pathlib import Path

import test_completion as fixtures

from delegation_reliability import DelegationSubmission, DelegationView

SOURCE = Path(__file__).resolve().parents[1] / "examples/policy_completion.py"
SPEC = importlib.util.spec_from_file_location("p3_public_policy_example", SOURCE)
assert SPEC is not None and SPEC.loader is not None
EXAMPLE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = EXAMPLE
SPEC.loader.exec_module(EXAMPLE)


class Coordinator:
    def __init__(self, view):
        self.view = view
        self.submitted = 0
        self.changed = False
        self.entered = asyncio.Event()
        self.release = None

    async def submit(self, request):
        self.submitted += 1
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        view = (
            replace(
                self.view,
                record=replace(self.view.record, work_id="00000000-0000-4000-8000-000000000001"),
            )
            if self.changed and self.submitted == 2
            else self.view
        )
        return DelegationSubmission(view, self.submitted == 1)

    async def get(self, work_id):
        return self.view


class PublicExampleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture = fixtures.CompletionTests(
            "test_normal_delivery_and_original_replay_use_one_remote_accept"
        )
        await self.fixture.asyncSetUp()
        self.coordinator = Coordinator(
            DelegationView(self.fixture.view.execution.record, self.fixture.request)
        )
        self.delivery = self.fixture.delivery()
        self.authorizer = self.fixture.authorizer()

    async def asyncTearDown(self):
        await self.fixture.asyncTearDown()

    async def run_example(self, confirmation=None):
        return await EXAMPLE.run_completion(
            self.fixture.request,
            coordinators=(self.coordinator, self.coordinator),
            runner=self.fixture.runner,
            delivery=self.delivery,
            authorizer=self.authorizer,
            confirmation=self.fixture.confirmation if confirmation is None else confirmation,
            execution_command_id="issue",
            confirmation_command_id="explicit_confirmation",
        )

    async def test_concurrent_logical_replay_and_explicit_completion_keep_states_separate(self):
        observed = await self.run_example()
        self.assertEqual(self.coordinator.submitted, 2)
        self.assertEqual(observed.created_acceptances, 1)
        self.assertEqual(observed.delivery_state, "accepted")
        self.assertEqual(observed.human_acknowledgement, "unobserved")
        self.assertFalse(observed.invoked)
        self.assertEqual(self.fixture.receiver.accepted, 1)
        self.assertEqual(self.fixture.actions.calls, 1)
        self.assertEqual(self.fixture.runner.pending_count, 0)

    async def test_read_only_inspection_cannot_deliver_or_authorize(self):
        observed = await EXAMPLE.inspect_accepted(
            self.fixture.work_id,
            coordinator=self.coordinator,
            runner=self.fixture.runner,
            delivery=self.delivery,
            authorizer=self.authorizer,
        )
        self.assertEqual(observed.execution.applicability, "candidate")
        self.assertEqual(observed.delivery.state, "missing")
        self.assertIsNone(observed.action)
        self.assertEqual(self.fixture.receiver.accepted, 0)
        self.assertEqual(self.fixture.actions.calls, 0)

    async def test_divergent_acceptance_identity_stops_before_delivery_or_action(self):
        self.coordinator.changed = True
        with self.assertRaisesRegex(EXAMPLE.ExampleInvariantError, "^example_identity_mismatch$"):
            await self.run_example()
        self.assertEqual(self.fixture.receiver.accepted, 0)
        self.assertEqual(self.fixture.actions.calls, 0)

    async def test_result_never_supplies_missing_explicit_confirmation(self):
        from continuity_lab.postgres_api import InvalidConfirmation

        forged = replace(self.fixture.confirmation)
        object.__setattr__(forged, "explicit", False)
        with self.assertRaises(InvalidConfirmation):
            await self.run_example(forged)
        self.assertEqual(self.fixture.actions.calls, 0)

    async def test_confirmation_is_copied_before_concurrent_submission_await(self):
        self.coordinator.release = asyncio.Event()
        original_amount = self.fixture.confirmation.quote.amount_minor
        pending = asyncio.create_task(self.run_example())
        try:
            await self.coordinator.entered.wait()
            object.__setattr__(
                self.fixture.confirmation.quote, "amount_minor", original_amount + 100
            )
        finally:
            self.coordinator.release.set()
        await pending
        receipt = self.fixture.actions.rows["explicit_confirmation"]
        self.assertEqual(receipt.confirmation.quote.amount_minor, original_amount)
        self.assertEqual(receipt.intent.quote.amount_minor, original_amount)
