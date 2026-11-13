"""Real managed public-factory schema boundary and authenticated useful progress."""

import asyncio
import json
import unittest
from contextlib import closing
from datetime import date
from uuid import uuid4

import pg_mutation_cases as prior
from psycopg import sql

from continuity_lab.api import BookingChange, ExecutionNotFound, SchemaVersionError
from continuity_lab.lease_models import CoordinationPolicy
from continuity_lab.lifecycle_models import LifecycleState
from continuity_lab.managed_inquiry_worker import ManagedInquiryWorker
from continuity_lab.postgres_api import AuthenticatedActor, BearerToken, open_postgres_client
from continuity_lab.postgres_case import PostgresCaseAuthority
from continuity_lab.postgres_leases import PostgresLeases
from continuity_lab.postgres_lifecycle import PostgresLifecycle
from continuity_lab.postgres_migrations import upgrade_v4
from continuity_lab.postgres_store import PostgresExecutionStore


class PostgresPackageCases(unittest.TestCase):
    setUpClass = classmethod(prior.PostgresMutationCases.setUpClass.__func__)
    setUp = prior.PostgresMutationCases.setUp
    drop_schema = prior.PostgresMutationCases.drop_schema

    def snapshot(self):
        with closing(self.owner.connect(application_name="continuity-test")) as connection:
            tables = connection.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname=%s ORDER BY tablename",
                (self.schema,),
            ).fetchall()
            return {
                row["tablename"]: sorted(
                    json.dumps(value, sort_keys=True, default=str)
                    for value in connection.execute(
                        sql.SQL("SELECT * FROM {}").format(
                            sql.Identifier(self.schema, row["tablename"])
                        )
                    ).fetchall()
                )
                for row in tables
            }

    def test_public_factory_rejects_active_v3_without_changing_schema_or_rows(self):
        before = self.snapshot()
        with self.assertRaises(SchemaVersionError):
            open_postgres_client(
                actor=prior.ACTOR,
                token=BearerToken("package-test-token-" + "x" * 32),
                settings=self.runtime,
            )
        self.assertEqual(self.snapshot(), before)

    def test_public_v4_client_preserves_identity_progress_and_authenticated_read(self):
        upgrade_v4(self.owner, policy=CoordinationPolicy(10, 2, 50, 30))
        client = open_postgres_client(
            actor=prior.ACTOR,
            token=BearerToken("package-test-token-" + "x" * 32),
            settings=self.runtime,
        )
        foreign = open_postgres_client(
            actor=AuthenticatedActor("foreign-operator", "foreign-traveller"),
            token=BearerToken("foreign-test-token-" + "y" * 32),
            settings=self.runtime,
        )
        request = BookingChange(prior.BOOKING, date(2030, 12, 10), True)

        def inquire(task_id):
            # The public factory uses current UTC, so this worker deliberately
            # uses current UTC too, rather than the historical fixture clock.
            store = PostgresExecutionStore(self.runtime)
            cases = PostgresCaseAuthority(store)
            leases = PostgresLeases(store)
            grant = leases.acquire(
                scope_id=prior.ACTOR.scope_id, task_id=task_id, owner_id=str(uuid4())
            )
            try:
                lifecycle = PostgresLifecycle(store, cases=cases, worker_lease=grant)
                result = ManagedInquiryWorker(lifecycle, self.supplier.inquiry_view()).run_one(
                    scope_id=prior.ACTOR.scope_id, task_id=task_id
                )
                self.assertEqual(result.state, LifecycleState.INQUIRY_COMPLETE)
            finally:
                leases.release(grant)

        async def exercise():
            async with client, foreign:
                accepted = await client.submit(idempotency_key="package-original", request=request)
                self.assertTrue(accepted.created)
                self.assertNotEqual(accepted.task_id, accepted.case_id)
                await asyncio.to_thread(inquire, accepted.task_id)
                observed = await client.get(task_id=accepted.task_id, limit=1)
                self.assertEqual(observed.payload()["inquiry"]["state"], "succeeded")
                replay = await client.submit(idempotency_key="package-original", request=request)
                self.assertFalse(replay.created)
                self.assertEqual(
                    (replay.task_id, replay.case_id), (accepted.task_id, accepted.case_id)
                )
                with self.assertRaises(ExecutionNotFound):
                    await foreign.get(task_id=accepted.task_id)
            self.assertEqual(client.pending_count, 0)
            self.assertEqual(foreign.pending_count, 0)

        asyncio.run(exercise())
        self.assertEqual(self.supplier.count_inquiries(scope_id=prior.ACTOR.scope_id), 1)
        self.assertEqual(self.supplier.count_calls(scope_id=prior.ACTOR.scope_id), 0)
        self.assertEqual(self.supplier.count_mutations(scope_id=prior.ACTOR.scope_id), 0)
