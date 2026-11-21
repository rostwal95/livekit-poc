"""Verify fresh Python storage schemas against the configured local PostgreSQL."""

from __future__ import annotations

import asyncio
import os
import unittest
from contextlib import AsyncExitStack, closing
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from time import monotonic, time_ns
from unittest.mock import patch
from uuid import uuid4

from psycopg import errors, sql

from continuity_lab import postgres_migrations as booking
from continuity_lab import work_admin as work
from continuity_lab.authorization import AuthenticatedActor
from continuity_lab.case_control_api import open_case_control_client
from continuity_lab.case_models import Confirmation, QuoteSnapshot, StaleRevision
from continuity_lab.execution_api import open_execution_client
from continuity_lab.execution_models import AttemptStatus, InquiryResult
from continuity_lab.lease_models import CoordinationPolicy, LeaseLost, LeaseRequired, WorkKind
from continuity_lab.models import BookingChange
from continuity_lab.postgres_api import open_postgres_client
from continuity_lab.postgres_case import PostgresCaseAuthority
from continuity_lab.postgres_lifecycle import PostgresLifecycle
from continuity_lab.postgres_settings import PostgresSettings
from continuity_lab.postgres_store import PostgresExecutionStore
from continuity_lab.postgres_work import PostgresWorkQueue
from continuity_lab.result_feed_api import open_result_feed_client
from continuity_lab.result_feed_store import source_id
from continuity_lab.work_api import (
    BearerToken,
    WorkDirectory,
    WorkPayload,
    WorkPrincipal,
    WorkScope,
    open_work_client,
)
from continuity_lab.work_schema import validate_work_schema


class InitialSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        runtime = PostgresSettings.from_env()
        owner = replace(
            runtime, user="continuity_migrator", password=os.environ["POSTGRES_MIGRATION_PASSWORD"]
        )
        suffix = uuid4().hex
        self.runtime_booking = replace(runtime, schema=f"proof_booking_{suffix}")
        self.runtime_work = replace(runtime, schema=f"p1_work_proof_{suffix}")
        self.booking = replace(owner, schema=self.runtime_booking.schema)
        self.work = replace(owner, schema=self.runtime_work.schema)
        self.assert_absent(self.booking)
        self.assert_absent(self.work)
        self.addCleanup(self.remove_schemas)

    def remove_schemas(self) -> None:
        with closing(self.booking.connect(application_name="continuity-test")) as connection:
            for settings in (self.booking, self.work):
                connection.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                        sql.Identifier(settings.schema)
                    )
                )

    def assert_absent(self, settings: PostgresSettings) -> None:
        with closing(settings.connect(application_name="continuity-test")) as connection:
            row = connection.execute(
                "SELECT 1 FROM pg_namespace WHERE nspname=%s", (settings.schema,)
            ).fetchone()
            self.assertIsNone(row)

    def test_rollback_is_atomic_and_a_fresh_attempt_works(self) -> None:
        self.assert_absent(self.booking)
        self.assert_absent(self.work)
        with (
            patch.object(
                booking, "validate_schema", side_effect=booking.SchemaVersionError("proof")
            ),
            self.assertRaises(booking.SchemaVersionError),
        ):
            booking.install_schema(self.booking)
        with (
            patch.object(
                work, "validate_work_schema", side_effect=work.WorkError("schema_mismatch")
            ),
            self.assertRaises(work.WorkError),
        ):
            work.install_work_schema(self.work)
        self.assert_absent(self.booking)
        self.assert_absent(self.work)
        booking.install_schema(self.booking)
        work.install_work_schema(self.work)

    def test_ready_replay_roles_limits_and_drift(self) -> None:
        case_limits = CoordinationPolicy(maximum_pending=16, maximum_active=2, maximum_records=16)
        work_limits = work.WorkLimits(16, 16)
        execution_limits = work.ExecutionLimits(4, 2, 10000)
        with self.assertRaises(booking.MigrationError):
            booking.install_schema(self.runtime_booking)
        with self.assertRaises(work.WorkError):
            work.install_work_schema(self.runtime_work)
        booking.install_schema(self.booking, policy=case_limits)
        work.install_work_schema(self.work, work_limits, execution_limits=execution_limits)
        with closing(self.runtime_work.connect()) as connection:
            original = source_id(connection, self.work.schema)
        booking.install_schema(self.booking, policy=case_limits)
        work.install_work_schema(self.work, work_limits, execution_limits=execution_limits)
        with closing(self.runtime_booking.connect()) as connection:
            booking.validate_schema(connection, self.booking.schema)
            with self.assertRaises(errors.InsufficientPrivilege):
                connection.execute(
                    sql.SQL("CREATE TABLE {}.forbidden(value integer)").format(
                        sql.Identifier(self.booking.schema)
                    )
                )
        with closing(self.runtime_work.connect()) as connection:
            self.assertEqual(validate_work_schema(connection, self.runtime_work), work_limits)
            self.assertEqual(source_id(connection, self.work.schema), original)
            with self.assertRaises(errors.InsufficientPrivilege):
                connection.execute(
                    sql.SQL("CREATE TABLE {}.forbidden(value integer)").format(
                        sql.Identifier(self.work.schema)
                    )
                )
        with self.assertRaises(booking.SchemaVersionError):
            booking.install_schema(self.booking)
        with self.assertRaises(work.WorkError):
            work.install_work_schema(self.work)
        with closing(self.booking.connect(application_name="continuity-test")) as connection:
            connection.execute(
                sql.SQL("CREATE TABLE {}.unexpected(value integer)").format(
                    sql.Identifier(self.booking.schema)
                )
            )
        with self.assertRaises(booking.SchemaVersionError):
            booking.install_schema(self.booking, policy=case_limits)
        with closing(self.work.connect(application_name="continuity-test")) as connection:
            connection.execute(
                sql.SQL("COMMENT ON SCHEMA {} IS 'unknown-layout'").format(
                    sql.Identifier(self.work.schema)
                )
            )
        with self.assertRaises(work.WorkError):
            work.install_work_schema(self.work, work_limits, execution_limits=execution_limits)

    def test_result_replay_preserves_one_live_feed_event(self) -> None:
        work.install_work_schema(self.work, execution_limits=work.ExecutionLimits(4, 2, 10000))

        async def exercise() -> None:
            token = BearerToken(uuid4().hex)
            directory = WorkDirectory(
                {token: WorkPrincipal("proof_actor", WorkScope("proof", "test"))}
            )
            async with AsyncExitStack() as owners:
                intake = open_work_client(
                    settings=self.runtime_work, directory=directory, token=token
                )
                owners.push_async_callback(intake.close)
                worker = open_execution_client(
                    settings=self.runtime_work, directory=directory, token=token
                )
                owners.push_async_callback(worker.close)
                feed = open_result_feed_client(
                    settings=self.runtime_work, directory=directory, token=token
                )
                owners.push_async_callback(feed.close)
                payload = WorkPayload(
                    "booking.evaluate_policy", b"synthetic work", time_ns() // 1000000 + 30000
                )
                submission = await intake.submit(idempotency_key="proof-input", payload=payload)
                self.assertTrue(submission.created)
                self.assertEqual((await feed.read()).events, ())
                issue = {
                    "work_id": submission.record.work_id,
                    "owner_id": str(uuid4()),
                    "command_id": "proof-attempt",
                }
                issued = await worker.issue(**issue)
                self.assertTrue(issued.created)
                repeated = await worker.issue(**issue)
                self.assertFalse(repeated.created)
                self.assertEqual(repeated.attempt, issued.attempt)
                result = await worker.complete(attempt=issued.attempt, body=b"synthetic result")
                self.assertEqual(result.disposition, "eligible_at_commit")
                self.assertEqual(
                    await worker.complete(attempt=issued.attempt, body=result.body), result
                )
                (event,) = (await feed.read()).events
                self.assertEqual(
                    (event.work_id, event.attempt_id, event.origin),
                    (result.work_id, result.attempt_id, "live"),
                )

        asyncio.run(exercise())

    def test_expired_worker_and_stale_quote_cannot_commit(self) -> None:
        booking.install_schema(self.booking, policy=CoordinationPolicy(16, 2, 16, 2))
        actor = AuthenticatedActor("proof_actor", "proof_scope")
        token = BearerToken(uuid4().hex)
        store = PostgresExecutionStore(self.runtime_booking)
        cases = PostgresCaseAuthority(store)
        queue = PostgresWorkQueue(store)
        request = BookingChange("DEMO-BK-001", date(2030, 12, 10), True)

        def counts() -> tuple[int, ...]:
            with closing(self.runtime_booking.connect()) as connection:
                rows = [
                    connection.execute(
                        sql.SQL("SELECT count(*) AS count FROM {}").format(
                            sql.Identifier(self.booking.schema, table)
                        )
                    ).fetchone()
                    for table in ("confirmations", "action_intents", "intent_dispatch")
                ]
                return tuple(int(row["count"]) for row in rows if row is not None)

        async def exercise() -> None:
            async with AsyncExitStack() as owners:
                intake = open_postgres_client(
                    actor=actor, token=token, settings=self.runtime_booking
                )
                owners.push_async_callback(intake.close)
                controller = open_case_control_client(
                    actor=actor, token=token, settings=self.runtime_booking
                )
                owners.push_async_callback(controller.close)
                accepted = await intake.submit(idempotency_key="proof-booking", request=request)
                task_id = accepted.task_id
                with self.assertRaises(LeaseRequired):
                    PostgresLifecycle(store).claim_due(scope_id=actor.scope_id, task_id=task_id)
                first = queue.claim_next(scope_id=actor.scope_id, owner_id=str(uuid4()))
                assert first is not None
                self.assertEqual((first.grant.task_id, first.kind), (task_id, WorkKind.INQUIRY))
                original = PostgresLifecycle(store, worker_lease=first.grant)
                original_claim = original.claim_due(scope_id=actor.scope_id, task_id=task_id)
                assert original_claim is not None
                deadline = monotonic() + 6
                successor_owner = str(uuid4())
                while (
                    successor := queue.claim_next(scope_id=actor.scope_id, owner_id=successor_owner)
                ) is None:
                    if monotonic() >= deadline:
                        self.fail("The database did not observe expiry and permit takeover")
                    await asyncio.sleep(0.02)
                self.assertEqual(successor.grant.task_id, task_id)
                self.assertEqual(successor.grant.epoch, first.grant.epoch + 1)
                result = InquiryResult(request.booking_reference, request.new_check_in, True)
                try:
                    with self.assertRaises(LeaseLost):
                        original.finish_success(original_claim, result)
                    lifecycle = PostgresLifecycle(store, worker_lease=successor.grant)
                    recovered = lifecycle.claim_due(scope_id=actor.scope_id, task_id=task_id)
                    assert recovered is not None
                    self.assertTrue(recovered.recovered)
                    self.assertEqual(
                        recovered.execution.effect_id, original_claim.execution.effect_id
                    )
                    lifecycle.finish_success(recovered, result)
                finally:
                    queue.release(successor.grant)
                self.assertEqual(
                    tuple(
                        attempt.status
                        for attempt in store.attempts(scope_id=actor.scope_id, task_id=task_id)
                    ),
                    (AttemptStatus.INTERRUPTED, AttemptStatus.SUCCEEDED),
                )
                quote = QuoteSnapshot(
                    str(uuid4()),
                    task_id,
                    0,
                    request.booking_reference,
                    request.new_check_in,
                    2500,
                    "USD",
                    (datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
                    accepted.case_id,
                    1,
                    str(uuid4()),
                )
                cases.publish_quote(actor=actor, quote=quote)
                change = replace(request, new_check_in=date(2030, 12, 11))
                revised = await controller.revise(
                    task_id=task_id, expected_revision=0, request=change
                )
                self.assertEqual(revised.revision, 1)
                with self.assertRaises(StaleRevision):
                    await controller.commit_confirmation(
                        task_id=task_id,
                        confirmation=Confirmation(quote, True),
                        command_id="stale",
                    )
                self.assertEqual(counts(), (0, 0, 0))
                fresh = replace(
                    quote,
                    quote_id=str(uuid4()),
                    revision=revised.revision,
                    new_check_in=change.new_check_in,
                )
                cases.publish_quote(actor=actor, quote=fresh)
                confirmation = Confirmation(fresh, True)
                intent = await controller.commit_confirmation(
                    task_id=task_id, confirmation=confirmation, command_id="current"
                )
                self.assertEqual(intent.quote, fresh)
                self.assertEqual(
                    await controller.commit_confirmation(
                        task_id=task_id, confirmation=confirmation, command_id="current"
                    ),
                    intent,
                )
                self.assertEqual(counts(), (1, 1, 1))

        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
