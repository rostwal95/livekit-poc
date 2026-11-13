"""Offline public issued value and pre-await snapshot boundaries; no database."""

import asyncio
import dataclasses
import unittest
from uuid import uuid4

from continuity_lab.execution_api import (
    AttemptResult,
    ExecutionClient,
    ExecutionLimits,
    ExecutionObservation,
    Issuance,
    IssuedAttempt,
    WorkError,
)
from continuity_lab.work_api import WorkPayload, WorkRecord, WorkScope


class IssuedPublicValues(unittest.TestCase):
    def grant(self):
        record = WorkRecord(
            str(uuid4()),
            WorkScope("tenant", "account"),
            "logical",
            WorkPayload("booking.evaluate_policy", b"original", 2000000010000),
            2000000000000,
            False,
        )
        return IssuedAttempt(
            record, str(uuid4()), "issue-command", 1, str(uuid4()), 1, 2000000000001, 2000000005000
        )

    def test_grant_and_result_are_typed_immutable_bounded_and_safe(self):
        grant = self.grant()
        self.assertTrue(Issuance(grant, True).created)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            grant.epoch = 2
        result = AttemptResult(
            grant.record.work_id,
            grant.attempt_id,
            b"PRIVATE_RESULT_SENTINEL",
            2000000000002,
            "eligible_at_commit",
        )
        self.assertNotIn("PRIVATE_RESULT_SENTINEL", repr(result))
        self.assertEqual(len(result.sha256), 64)
        for body in (b"", b"x" * 8193, bytearray(b"value")):
            with self.assertRaises(WorkError):
                AttemptResult(
                    grant.record.work_id,
                    grant.attempt_id,
                    body,
                    2000000000002,
                    "eligible_at_commit",
                )
        self.assertEqual(
            len(
                AttemptResult(
                    grant.record.work_id, grant.attempt_id, b"x" * 8192, 2000000000002, "cancelled"
                ).body
            ),
            8192,
        )

    def test_limits_and_observations_reject_inconsistent_or_unbounded_input(self):
        for values in (
            (0, 1, 100),
            (5, 1, 100),
            (1, 4, 100),
            (1, 1, 99),
            (1, 1, 30001),
            (True, 1, 100),
        ):
            with self.assertRaises(WorkError):
                ExecutionLimits(*values)
        grant = self.grant()
        with self.assertRaises(WorkError):
            ExecutionObservation(grant.record, None, None, 1, "accepted")
        with self.assertRaises(WorkError):
            ExecutionObservation(grant.record, grant, None, 1, "result_recorded")
        self.assertEqual(
            ExecutionObservation(grant.record, grant, None, 1, "running").status, "running"
        )
        with self.assertRaises(WorkError):
            ExecutionObservation(grant.record, grant, None, 2, "running")
        with self.assertRaises(WorkError):
            ExecutionObservation(
                dataclasses.replace(grant.record, idempotency_key="different"),
                grant,
                None,
                1,
                "running",
            )
        with self.assertRaises(WorkError):
            ExecutionObservation(grant.record, object(), None, 1, "running")
        with self.assertRaises(WorkError):
            ExecutionObservation(grant.record, grant, object(), 1, "result_recorded")
        cancelled = ExecutionObservation(
            dataclasses.replace(grant.record, cancel_requested=True), grant, None, 1, "cancelled"
        )
        self.assertTrue(cancelled.record.cancel_requested)
        self.assertFalse(cancelled.current_attempt.record.cancel_requested)
        with self.assertRaises(WorkError):
            dataclasses.replace(grant, owner_id="invalid")
        with self.assertRaises(WorkError):
            dataclasses.replace(grant, lease_until_ms=grant.issued_at_ms)

    def test_complete_rebuilds_nested_grant_before_await_and_preserves_status_validation(self):
        async def run():
            original = self.grant()
            reached, release = asyncio.Event(), asyncio.Event()
            captured = []

            class FakeStore:
                def complete(self, scope, attempt, body):
                    captured.append(attempt)
                    return AttemptResult(
                        attempt.record.work_id,
                        attempt.attempt_id,
                        body,
                        2000000000002,
                        "eligible_at_commit",
                    )

            client = object.__new__(ExecutionClient)
            client._store = FakeStore()

            async def held(operation):
                reached.set()
                await release.wait()
                return operation(WorkScope("tenant", "account"))

            client._run = held
            pending = asyncio.create_task(client.complete(attempt=original, body=b"result"))
            await reached.wait()
            object.__setattr__(original.record.scope, "account_id", "changed")
            object.__setattr__(original.record.payload, "body", b"changed")
            release.set()
            await pending
            self.assertEqual(captured[0].record.scope.account_id, "account")
            self.assertEqual(captured[0].record.payload.body, b"original")
            invalid = self.grant()
            object.__setattr__(invalid.record, "status", "forged")
            with self.assertRaises(WorkError):
                await client.complete(attempt=invalid, body=b"result")
            invalid = self.grant()
            object.__setattr__(invalid.record, "payload", object())
            with self.assertRaises(WorkError):
                await client.complete(attempt=invalid, body=b"result")

        asyncio.run(run())
