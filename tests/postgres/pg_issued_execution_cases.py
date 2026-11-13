"""Explicit actual PostgreSQL issued read-only work; excluded from offline discovery."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
import unittest
from contextlib import closing
from dataclasses import replace
from uuid import uuid4

import psycopg
from psycopg import sql

from continuity_lab.execution_api import ExecutionLimits, open_execution_client
from continuity_lab.work_admin import install_work_schema, upgrade_work_schema_v2
from continuity_lab.work_api import (
    BearerToken,
    PostgresSettings,
    WorkDirectory,
    WorkError,
    WorkPayload,
    WorkPrincipal,
    WorkScope,
    open_work_client,
)


class IssuedExecutionPostgresCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("P1_RUN_POSTGRES_TESTS") != "1":
            raise RuntimeError("Explicit local PostgreSQL setup required")
        cls.runtime_base = PostgresSettings.from_env()
        cls.owner_base = PostgresSettings.from_env("P1_MIGRATION_")

    def setUp(self):
        self.schema = "p1_work_" + uuid4().hex
        self.runtime = replace(self.runtime_base, schema=self.schema)
        self.owner = replace(self.owner_base, schema=self.schema)
        self.token = BearerToken("synthetic-issued-" + "x" * 40)
        self.scope = WorkScope("tenant_issued", "account_issued")
        self.directory = WorkDirectory({self.token: WorkPrincipal("issued_actor", self.scope)})
        self.owner_id = str(uuid4())
        self.addCleanup(self.cleanup)
        install_work_schema(self.owner)

    def cleanup(self):
        self.assertTrue(self.schema.startswith("p1_work_") and len(self.schema) == 40)
        with closing(self.owner.connect(application_name="continuity-test")) as connection:
            row = connection.execute(
                "SELECT obj_description(oid,'pg_namespace') AS marker,pg_get_userbyid(nspowner) AS owner FROM pg_namespace WHERE nspname=%s",
                [self.schema],
            ).fetchone()
            if row is not None:
                self.assertEqual(row["owner"], "continuity_migrator")
                self.assertIn(
                    row["marker"], {"continuity-readonly-work-v1", "continuity-readonly-work-v2"}
                )
                connection.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema))
                )

    def work(self, *, scope=None):
        directory = (
            self.directory
            if scope is None
            else WorkDirectory({self.token: WorkPrincipal("other_actor", scope)})
        )
        return open_work_client(settings=self.runtime, directory=directory, token=self.token)

    def execution(self, *, scope=None, hook=None):
        directory = (
            self.directory
            if scope is None
            else WorkDirectory({self.token: WorkPrincipal("other_actor", scope)})
        )
        return open_execution_client(
            settings=self.runtime, directory=directory, token=self.token, harness_failpoint=hook
        )

    def upgrade(self, limits=None, hook=None):
        upgrade_work_schema_v2(
            self.owner, ExecutionLimits() if limits is None else limits, harness_failpoint=hook
        )

    async def accepted(self, client, key="logical", deadline=None):
        return (
            await client.submit(
                idempotency_key=key,
                payload=WorkPayload(
                    "booking.evaluate_policy",
                    b'{"synthetic":"original"}',
                    time.time_ns() // 1000000 + 30000 if deadline is None else deadline,
                ),
            )
        ).record

    def sql(self, query, *values):
        with closing(self.owner.connect(application_name="continuity-test")) as connection:
            cursor = connection.execute(sql.SQL(query).format(sql.Identifier(self.schema)), values)
            return [] if cursor.description is None else cursor.fetchall()

    def wait_after(self, timestamp):
        deadline = time.monotonic() + 3
        with closing(self.owner.connect(application_name="continuity-test")) as connection:
            while True:
                now = connection.execute(
                    "SELECT floor(extract(epoch FROM clock_timestamp())*1000)::bigint AS now"
                ).fetchone()["now"]
                if now >= timestamp:
                    return
                self.assertLess(time.monotonic(), deadline)
                connection.execute("SELECT pg_sleep(0.01)")

    async def error(self, awaitable, code):
        with self.assertRaises(WorkError) as caught:
            await awaitable
        self.assertEqual(caught.exception.code, code)

    def test_explicit_upgrade_preserves_original_acceptance_cancel_and_v1_apis(self):
        async def run():
            work = self.work()
            try:
                original = await self.accepted(work)
                cancellation = await work.cancel(
                    work_id=original.work_id, command_id="cancel-original"
                )
                with self.assertRaises(WorkError) as caught:
                    self.execution()
                self.assertEqual(caught.exception.code, "schema_mismatch")
                self.upgrade()
                install_work_schema(self.owner)
                self.upgrade()
                self.assertEqual(
                    (await work.get(work_id=original.work_id)).payload, original.payload
                )
                self.assertFalse(
                    (await work.submit(idempotency_key="logical", payload=original.payload)).created
                )
                self.assertEqual(
                    await work.cancel(work_id=original.work_id, command_id="cancel-original"),
                    cancellation,
                )
                execution = self.execution()
                try:
                    self.assertEqual(
                        (await execution.observe(work_id=original.work_id)).status, "cancelled"
                    )
                    await self.error(
                        execution.issue(
                            work_id=original.work_id,
                            owner_id=self.owner_id,
                            command_id="blocked-cancel",
                        ),
                        "expired",
                    )
                finally:
                    await execution.close()
                self.assertEqual(
                    self.sql("SELECT version FROM {}.schema_metadata")[0]["version"], 2
                )
            finally:
                await work.close()

        asyncio.run(run())

    def test_upgrade_before_commit_rolls_back_and_after_commit_is_reconciled(self):
        def fail(stage):
            if stage == "upgrade.before_commit":
                raise RuntimeError("PRIVATE_UPGRADE_SENTINEL")

        with self.assertRaises(WorkError) as caught:
            self.upgrade(hook=fail)
        self.assertEqual(caught.exception.code, "storage_unavailable")
        self.assertEqual(self.sql("SELECT version FROM {}.schema_metadata")[0]["version"], 1)
        with closing(self.owner.connect()) as connection:
            self.assertIsNone(
                connection.execute(
                    "SELECT to_regclass(%s) AS table", [self.schema + ".issued_attempts"]
                ).fetchone()["table"]
            )
        install_work_schema(self.owner)

        def after(stage):
            if stage == "upgrade.after_commit":
                raise RuntimeError("PRIVATE_ACK_SENTINEL")

        with self.assertRaises(WorkError) as caught:
            self.upgrade(hook=after)
        self.assertEqual(caught.exception.code, "acknowledgement_unknown")
        self.upgrade()
        install_work_schema(self.owner)
        with self.assertRaises(WorkError):
            self.upgrade(ExecutionLimits(max_active=1))
        self.assertEqual(self.sql("SELECT version FROM {}.schema_metadata")[0]["version"], 2)

    def test_upgrade_rejects_drift_without_adopting_or_creating_execution_tables(self):
        self.sql("ALTER TABLE {}.accepted_work ADD COLUMN drift text")
        with self.assertRaises(WorkError) as caught:
            self.upgrade()
        self.assertEqual(caught.exception.code, "schema_mismatch")
        self.assertEqual(self.sql("SELECT version FROM {}.schema_metadata")[0]["version"], 1)
        with closing(self.owner.connect()) as connection:
            self.assertIsNone(
                connection.execute(
                    "SELECT to_regclass(%s) AS table", [self.schema + ".issued_attempts"]
                ).fetchone()["table"]
            )

    def test_normal_issue_result_replay_and_later_cancel_preserve_known_truth(self):
        self.upgrade()

        async def run():
            work, execution = self.work(), self.execution()
            try:
                original = await self.accepted(work)
                issuance = await execution.issue(
                    work_id=original.work_id, owner_id=self.owner_id, command_id="start"
                )
                self.assertTrue(issuance.created)
                grant = issuance.attempt
                self.assertEqual(grant.record, original)
                self.assertEqual(
                    (await execution.observe(work_id=original.work_id)).status, "running"
                )
                replay = await execution.issue(
                    work_id=original.work_id, owner_id=self.owner_id, command_id="start"
                )
                self.assertFalse(replay.created)
                self.assertEqual(replay.attempt, grant)
                result = await execution.complete(attempt=grant, body=b'{"candidate":true}')
                self.assertEqual(result.disposition, "eligible_at_commit")
                self.assertEqual(await execution.complete(attempt=grant, body=result.body), result)
                self.assertEqual(
                    await execution.result(work_id=original.work_id, attempt_id=grant.attempt_id),
                    result,
                )
                await work.cancel(work_id=original.work_id, command_id="cancel-after-known")
                observation = await execution.observe(work_id=original.work_id)
                self.assertEqual(observation.status, "result_recorded")
                self.assertTrue(observation.record.cancel_requested)
                self.assertFalse(observation.current_attempt.record.cancel_requested)
                self.assertEqual(observation.result, result)
                self.assertEqual(await execution.find_issue(command_id="start"), grant)
                await self.error(
                    execution.issue(
                        work_id=original.work_id,
                        owner_id=self.owner_id,
                        command_id="new-after-result",
                    ),
                    "identity_conflict",
                )
            finally:
                await execution.close()
                await work.close()

        asyncio.run(run())

    def test_concurrent_same_command_returns_one_exact_grant(self):
        self.upgrade()

        async def run():
            work = self.work()
            clients = [self.execution() for _ in range(6)]
            try:
                original = await self.accepted(work)
                values = await asyncio.gather(
                    *(
                        client.issue(
                            work_id=original.work_id,
                            owner_id=self.owner_id,
                            command_id="shared-start",
                        )
                        for client in clients
                    )
                )
                self.assertEqual(sum(value.created for value in values), 1)
                self.assertEqual(len({value.attempt.attempt_id for value in values}), 1)
                self.assertTrue(all(value.attempt == values[0].attempt for value in values))
                self.assertEqual(len(self.sql("SELECT attempt_id FROM {}.issued_attempts")), 1)
            finally:
                for client in clients:
                    await client.close()
                await work.close()

        asyncio.run(run())

    def test_global_active_cap_across_scopes_keeps_replay_and_reads_available(self):
        self.upgrade(ExecutionLimits(max_active=1))

        async def run():
            other = WorkScope("tenant_issued", "account_other")
            work, remote, execution, foreign = (
                self.work(),
                self.work(scope=other),
                self.execution(),
                self.execution(scope=other),
            )
            try:
                first, second = await self.accepted(work), await self.accepted(remote)
                issue = await execution.issue(
                    work_id=first.work_id, owner_id=self.owner_id, command_id="first"
                )
                await self.error(
                    foreign.issue(
                        work_id=second.work_id, owner_id=str(uuid4()), command_id="second"
                    ),
                    "capacity",
                )
                self.assertEqual(await execution.find_issue(command_id="first"), issue.attempt)
                self.assertEqual((await foreign.observe(work_id=second.work_id)).status, "accepted")
                await execution.complete(attempt=issue.attempt, body=b"known")
                self.assertTrue(
                    (
                        await foreign.issue(
                            work_id=second.work_id, owner_id=str(uuid4()), command_id="second"
                        )
                    ).created
                )
            finally:
                for client in (execution, foreign, work, remote):
                    await client.close()

        asyncio.run(run())

    def test_scoped_command_and_exact_grant_result_identity_conflicts(self):
        self.upgrade()

        async def run():
            work, execution, foreign = (
                self.work(),
                self.execution(),
                self.execution(scope=WorkScope("tenant_issued", "foreign")),
            )
            try:
                first, second = await self.accepted(work), await self.accepted(work, "second")
                grant = (
                    await execution.issue(
                        work_id=first.work_id, owner_id=self.owner_id, command_id="start"
                    )
                ).attempt
                await self.error(
                    execution.issue(
                        work_id=second.work_id, owner_id=self.owner_id, command_id="start"
                    ),
                    "identity_conflict",
                )
                await self.error(
                    execution.issue(
                        work_id=first.work_id, owner_id=str(uuid4()), command_id="start"
                    ),
                    "identity_conflict",
                )
                self.assertIsNone(await foreign.find_issue(command_id="start"))
                await self.error(foreign.observe(work_id=first.work_id), "not_found")
                await self.error(foreign.complete(attempt=grant, body=b"secret"), "invalid_input")
                await self.error(
                    execution.complete(
                        attempt=replace(grant, owner_id=str(uuid4())), body=b"forged"
                    ),
                    "identity_conflict",
                )
                self.assertIsNone(
                    await execution.result(work_id=first.work_id, attempt_id=grant.attempt_id)
                )
                first_result = await execution.complete(attempt=grant, body=b"original")
                await self.error(
                    execution.complete(attempt=grant, body=b"changed"), "identity_conflict"
                )
                self.assertEqual(
                    await execution.result(work_id=first.work_id, attempt_id=grant.attempt_id),
                    first_result,
                )
            finally:
                for client in (execution, foreign, work):
                    await client.close()

        asyncio.run(run())

    def test_attempt_cap_and_superseded_results_are_retained_without_current_promotion(self):
        self.upgrade(ExecutionLimits(lease_ms=100))

        async def run():
            work, execution = self.work(), self.execution()
            try:
                original = await self.accepted(work)
                grants = []
                for number in range(1, 4):
                    grant = (
                        await execution.issue(
                            work_id=original.work_id,
                            owner_id=self.owner_id,
                            command_id="start-" + str(number),
                        )
                    ).attempt
                    self.assertEqual((grant.number, grant.epoch), (number, number))
                    grants.append(grant)
                    await asyncio.to_thread(self.wait_after, grant.lease_until_ms)
                await self.error(
                    execution.issue(
                        work_id=original.work_id, owner_id=self.owner_id, command_id="over-cap"
                    ),
                    "capacity",
                )
                old = await execution.complete(attempt=grants[0], body=b"historical")
                self.assertEqual(old.disposition, "superseded")
                late = await execution.complete(attempt=grants[-1], body=b"late")
                self.assertEqual(late.disposition, "lease_expired")
                observation = await execution.observe(work_id=original.work_id)
                self.assertEqual(observation.status, "exhausted")
                self.assertEqual(observation.result, late)
                self.assertEqual(
                    await execution.result(
                        work_id=original.work_id, attempt_id=grants[0].attempt_id
                    ),
                    old,
                )
                self.assertFalse(
                    (
                        await execution.issue(
                            work_id=original.work_id, owner_id=self.owner_id, command_id="start-1"
                        )
                    ).created
                )
            finally:
                await execution.close()
                await work.close()

        asyncio.run(run())

    def test_cancel_during_issued_work_retains_late_bytes_without_eligibility(self):
        self.upgrade()

        async def run():
            work, execution = self.work(), self.execution()
            try:
                original = await self.accepted(work)
                grant = (
                    await execution.issue(
                        work_id=original.work_id, owner_id=self.owner_id, command_id="start"
                    )
                ).attempt
                await work.cancel(work_id=original.work_id, command_id="cancel-held")
                self.assertEqual(await execution.find_issue(command_id="start"), grant)
                result = await execution.complete(attempt=grant, body=b"known-after-cancel")
                self.assertEqual(result.disposition, "cancelled")
                observation = await execution.observe(work_id=original.work_id)
                self.assertEqual(observation.status, "cancelled")
                self.assertEqual(observation.result, result)
                self.assertTrue(observation.record.cancel_requested)
                await self.error(
                    execution.issue(
                        work_id=original.work_id, owner_id=self.owner_id, command_id="new-start"
                    ),
                    "expired",
                )
            finally:
                await execution.close()
                await work.close()

        asyncio.run(run())

    def test_deadline_blocks_new_issuance_and_known_result_stays_historical(self):
        self.upgrade()

        async def run():
            work, execution = self.work(), self.execution()
            try:
                original = await self.accepted(work, deadline=time.time_ns() // 1000000 + 500)
                grant = (
                    await execution.issue(
                        work_id=original.work_id, owner_id=self.owner_id, command_id="start"
                    )
                ).attempt
                await asyncio.to_thread(self.wait_after, original.payload.deadline_at_ms)
                result = await execution.complete(attempt=grant, body=b"known-after-deadline")
                self.assertEqual(result.disposition, "expired")
                self.assertEqual(
                    (await execution.observe(work_id=original.work_id)).status, "expired"
                )
                await self.error(
                    execution.issue(
                        work_id=original.work_id, owner_id=self.owner_id, command_id="new-start"
                    ),
                    "expired",
                )
                self.assertEqual(await execution.find_issue(command_id="start"), grant)
            finally:
                await execution.close()
                await work.close()

        asyncio.run(run())

    def test_before_after_commit_acknowledgement_boundaries_reconcile_original_rows(self):
        self.upgrade()

        async def run():
            work = self.work()
            stage = ["issue.before_commit"]

            def failpoint(value):
                if value == stage[0]:
                    raise RuntimeError("PRIVATE_ACK_SENTINEL")

            execution = self.execution(hook=failpoint)
            try:
                original = await self.accepted(work)
                await self.error(
                    execution.issue(
                        work_id=original.work_id, owner_id=self.owner_id, command_id="start"
                    ),
                    "storage_unavailable",
                )
                self.assertIsNone(await execution.find_issue(command_id="start"))
                stage[0] = "issue.after_commit"
                await self.error(
                    execution.issue(
                        work_id=original.work_id, owner_id=self.owner_id, command_id="start"
                    ),
                    "acknowledgement_unknown",
                )
                grant = await execution.find_issue(command_id="start")
                self.assertIsNotNone(grant)
                stage[0] = "complete.before_commit"
                await self.error(
                    execution.complete(attempt=grant, body=b"known"), "storage_unavailable"
                )
                self.assertIsNone(
                    await execution.result(work_id=original.work_id, attempt_id=grant.attempt_id)
                )
                stage[0] = "complete.after_commit"
                await self.error(
                    execution.complete(attempt=grant, body=b"known"), "acknowledgement_unknown"
                )
                result = await execution.result(
                    work_id=original.work_id, attempt_id=grant.attempt_id
                )
                self.assertEqual(result.body, b"known")
                stage[0] = "none"
                self.assertEqual(await execution.complete(attempt=grant, body=b"known"), result)
            finally:
                await execution.close()
                await work.close()

        asyncio.run(run())

    def test_cancelled_waiter_keeps_real_io_and_nested_original_grant_snapshot(self):
        self.upgrade()
        reached, release = threading.Event(), threading.Event()

        def hook(stage):
            if stage == "complete.before_commit":
                reached.set()
                if not release.wait(3):
                    raise AssertionError("completion_release_timeout")

        async def run():
            work, execution = self.work(), self.execution(hook=hook)
            try:
                original = await self.accepted(work)
                grant = (
                    await execution.issue(
                        work_id=original.work_id, owner_id=self.owner_id, command_id="start"
                    )
                ).attempt
                pending = asyncio.create_task(execution.complete(attempt=grant, body=b"known"))
                self.assertTrue(await asyncio.to_thread(reached.wait, 2))
                object.__setattr__(grant.record.payload, "body", b"MUTATED_PRIVATE_SENTINEL")
                object.__setattr__(grant.record.scope, "account_id", "mutated")
                pending.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await pending
                self.assertEqual(execution.pending_count, 1)
                release.set()
                await execution.close()
                self.assertEqual(execution.pending_count, 0)
                fresh = self.execution()
                try:
                    result = await fresh.result(
                        work_id=original.work_id, attempt_id=grant.attempt_id
                    )
                    self.assertEqual(result.body, b"known")
                    stored = await fresh.find_issue(command_id="start")
                    self.assertEqual(stored.record.scope, self.scope)
                    self.assertEqual(stored.record.payload.body, b'{"synthetic":"original"}')
                finally:
                    await fresh.close()
            finally:
                release.set()
                await execution.close()
                await work.close()

        asyncio.run(run())

    def test_runtime_cannot_rewrite_grants_results_limits_or_catalog_and_logging_failure_progresses(
        self,
    ):
        self.upgrade()

        class Failing(logging.Handler):
            def emit(self, record):
                raise RuntimeError("PRIVATE_LOG_SENTINEL")

        logger = logging.getLogger("continuity_lab.readonly_work")
        handler, level = Failing(), logger.level
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        async def run():
            work, execution = self.work(), self.execution()
            try:
                original = await self.accepted(work)
                grant = (
                    await execution.issue(
                        work_id=original.work_id, owner_id=self.owner_id, command_id="start"
                    )
                ).attempt
                result = await execution.complete(attempt=grant, body=b"known")
                self.assertEqual((await execution.observe(work_id=original.work_id)).result, result)
                self.assertEqual(await execution.find_issue(command_id="start"), grant)
                self.assertGreaterEqual(execution.metrics()["telemetry_failures"], 4)
                for statement in (
                    "UPDATE {}.issued_attempts SET epoch=epoch",
                    "DELETE FROM {}.attempt_results",
                    "UPDATE {}.execution_limits SET max_active=2",
                    "CREATE TABLE {}.forbidden(value int)",
                ):
                    with (
                        closing(self.runtime.connect()) as connection,
                        self.assertRaises(psycopg.errors.InsufficientPrivilege),
                    ):
                        connection.execute(sql.SQL(statement).format(sql.Identifier(self.schema)))
                self.assertEqual(
                    await execution.result(work_id=original.work_id, attempt_id=grant.attempt_id),
                    result,
                )
            finally:
                await execution.close()
                await work.close()

        try:
            asyncio.run(run())
        finally:
            logger.removeHandler(handler)
            logger.setLevel(level)

    def test_deadline_is_sampled_after_actual_admission_lock_wait(self):
        self.upgrade()

        async def run():
            work, execution = self.work(), self.execution()
            try:
                original = await self.accepted(work, deadline=time.time_ns() // 1000000 + 450)
                with (
                    closing(self.owner.connect(application_name="continuity-test")) as owner,
                    owner.transaction(),
                ):
                    owner.execute(
                        sql.SQL("SELECT singleton FROM {}.admission FOR UPDATE").format(
                            sql.Identifier(self.schema)
                        )
                    )
                    pending = asyncio.create_task(
                        execution.issue(
                            work_id=original.work_id, owner_id=self.owner_id, command_id="waited"
                        )
                    )
                    await asyncio.sleep(0.05)
                    self.assertEqual(execution.pending_count, 1)
                    await asyncio.to_thread(self.wait_after, original.payload.deadline_at_ms)
                await self.error(pending, "expired")
                self.assertIsNone(await execution.find_issue(command_id="waited"))
                useful = await self.accepted(work, "useful-after-lock")
                self.assertTrue(
                    (
                        await execution.issue(
                            work_id=useful.work_id, owner_id=self.owner_id, command_id="useful"
                        )
                    ).created
                )
            finally:
                await execution.close()
                await work.close()

        asyncio.run(run())
