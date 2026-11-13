"""Explicit actual P1 read-only work profile cases; no default offline discovery."""

from __future__ import annotations

import asyncio
import logging
import os
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from uuid import uuid4

import psycopg
from psycopg import sql

from continuity_lab.work_admin import install_work_schema
from continuity_lab.work_api import (
    BearerToken,
    PostgresSettings,
    WorkDirectory,
    WorkError,
    WorkLimits,
    WorkPayload,
    WorkPrincipal,
    WorkScope,
    open_work_client,
)


class ReadOnlyWorkPostgresCases(unittest.TestCase):
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
        self.token = BearerToken("synthetic-work-token-" + "x" * 32)
        self.scope = WorkScope("tenant-a", "account-a")
        self.directory = WorkDirectory({self.token: WorkPrincipal("actor-a", self.scope)})
        self.addCleanup(self.cleanup)
        install_work_schema(self.owner)

    def cleanup(self):
        self.assertTrue(self.schema.startswith("p1_work_") and len(self.schema) == 40)
        with closing(self.owner.connect(application_name="continuity-test")) as connection:
            marker = connection.execute(
                "SELECT obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=%s",
                [self.schema],
            ).fetchone()
            if marker:
                self.assertEqual(marker["marker"], "continuity-readonly-work-v1")
                connection.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema))
                )

    def client(self, *, scope=None, failpoint=None):
        directory = (
            self.directory
            if scope is None
            else WorkDirectory({self.token: WorkPrincipal("actor-other", scope)})
        )
        return open_work_client(
            settings=self.runtime,
            directory=directory,
            token=self.token,
            harness_failpoint=failpoint,
        )

    def payload(self, body=b'{"synthetic":true}', deadline=None):
        return WorkPayload(
            "booking.evaluate_policy",
            body,
            int(time.time() * 1000) + 30000 if deadline is None else deadline,
        )

    def owner_sql(self, query, *params):
        with closing(self.owner.connect(application_name="continuity-test")) as connection:
            cursor = connection.execute(sql.SQL(query).format(sql.Identifier(self.schema)), params)
            return [] if cursor.description is None else cursor.fetchall()

    def test_public_accept_replay_find_and_original_scope(self):
        async def run():
            client = self.client()
            other = self.client(scope=WorkScope("tenant-a", "account-b"))
            try:
                payload = self.payload()
                one = await client.submit(idempotency_key="logical", payload=payload)
                replay = await client.submit(idempotency_key="logical", payload=payload)
                self.assertTrue(one.created)
                self.assertFalse(replay.created)
                self.assertEqual(one.record, replay.record)
                self.assertEqual(
                    (await client.find(idempotency_key="logical")).payload.body, payload.body
                )
                self.assertIsNone(await other.find(idempotency_key="logical"))
                for call in (
                    other.get(work_id=one.record.work_id),
                    other.cancel(work_id=one.record.work_id, command_id="cancel"),
                ):
                    with self.assertRaises(WorkError) as caught:
                        await call
                    self.assertEqual(caught.exception.code, "not_found")
                distinct = await other.submit(idempotency_key="logical", payload=payload)
                self.assertNotEqual(one.record.work_id, distinct.record.work_id)
            finally:
                await client.close()
                await other.close()

        asyncio.run(run())

    def test_concurrent_acceptors_keep_one_immutable_record(self):
        payload = self.payload()

        def submit(_):
            async def run():
                client = self.client()
                try:
                    return await client.submit(idempotency_key="concurrent", payload=payload)
                finally:
                    await client.close()

            return asyncio.run(run())

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(submit, range(6)))
        self.assertEqual(sum(result.created for result in results), 1)
        self.assertEqual(len({result.record.work_id for result in results}), 1)
        self.assertEqual(self.owner_sql("SELECT count(*) AS n FROM {}.accepted_work")[0]["n"], 1)

    def test_before_commit_rolls_back_after_commit_unknown_reconciles(self):
        payload = self.payload()

        async def run():
            def before(stage):
                if stage == "submit.before_commit":
                    raise RuntimeError("PRIVATE_STORAGE_SENTINEL")

            def after(stage):
                if stage == "submit.after_commit":
                    raise RuntimeError("PRIVATE_STORAGE_SENTINEL")

            for hook, key, code in (
                (before, "before", "storage_unavailable"),
                (after, "after", "acknowledgement_unknown"),
            ):
                faulty = self.client(failpoint=hook)
                try:
                    with self.assertRaises(WorkError) as caught:
                        await faulty.submit(idempotency_key=key, payload=payload)
                    self.assertEqual(caught.exception.code, code)
                    self.assertNotIn("PRIVATE", str(caught.exception))
                finally:
                    await faulty.close()
            client = self.client()
            try:
                self.assertIsNone(await client.find(idempotency_key="before"))
                original = await client.find(idempotency_key="after")
                self.assertIsNotNone(original)
                replay = await client.submit(idempotency_key="after", payload=payload)
                self.assertFalse(replay.created)
                self.assertEqual(original, replay.record)
            finally:
                await client.close()

        asyncio.run(run())

    def test_changed_bytes_deadline_conflict_and_expired_new_input(self):
        async def run():
            client = self.client()
            try:
                payload = self.payload()
                one = await client.submit(idempotency_key="original", payload=payload)
                for changed in (
                    self.payload(b"different", payload.deadline_at_ms),
                    self.payload(payload.body, payload.deadline_at_ms + 1),
                ):
                    with self.assertRaises(WorkError) as caught:
                        await client.submit(idempotency_key="original", payload=changed)
                    self.assertEqual(caught.exception.code, "identity_conflict")
                with self.assertRaises(WorkError) as caught:
                    await client.submit(idempotency_key="expired", payload=self.payload(deadline=1))
                self.assertEqual(caught.exception.code, "expired")
                self.assertEqual((await client.get(work_id=one.record.work_id)).payload, payload)
            finally:
                await client.close()

        asyncio.run(run())

    def test_cancellation_is_scoped_idempotent_and_separate_from_stop(self):
        async def run():
            client = self.client()
            try:
                payload = self.payload()
                first = await client.submit(idempotency_key="one", payload=payload)
                second = await client.submit(idempotency_key="two", payload=payload)
                a = await client.cancel(work_id=first.record.work_id, command_id="command")
                b = await client.cancel(work_id=first.record.work_id, command_id="command")
                self.assertEqual(a, b)
                self.assertEqual(a.disposition, "requested")
                with self.assertRaises(WorkError) as caught:
                    await client.cancel(work_id=second.record.work_id, command_id="command")
                self.assertEqual(caught.exception.code, "identity_conflict")
                observed = await client.get(work_id=first.record.work_id)
                self.assertEqual(observed.status, "accepted")
                self.assertTrue(observed.cancel_requested)
                self.assertFalse((await client.get(work_id=second.record.work_id)).cancel_requested)
            finally:
                await client.close()

        asyncio.run(run())

    def test_retained_caps_preserve_replay_reads_and_original_cancel(self):
        self.cleanup()
        install_work_schema(self.owner, WorkLimits(1, 1))

        async def run():
            client = self.client()
            try:
                payload = self.payload()
                first = await client.submit(idempotency_key="one", payload=payload)
                with self.assertRaises(WorkError) as caught:
                    await client.submit(idempotency_key="two", payload=payload)
                self.assertEqual(caught.exception.code, "capacity")
                original = await client.cancel(work_id=first.record.work_id, command_id="first")
                with self.assertRaises(WorkError) as caught:
                    await client.cancel(work_id=first.record.work_id, command_id="second")
                self.assertEqual(caught.exception.code, "capacity")
                self.assertEqual(
                    original, await client.cancel(work_id=first.record.work_id, command_id="first")
                )
                self.assertFalse(
                    (await client.submit(idempotency_key="one", payload=payload)).created
                )
                self.assertTrue((await client.get(work_id=first.record.work_id)).cancel_requested)
            finally:
                await client.close()

        asyncio.run(run())

    def test_runtime_cannot_ddl_mutate_or_delete_identity_and_owner_repeat_is_validation(self):
        install_work_schema(self.owner)
        for query in (
            "CREATE TABLE {}.forbidden(x integer)",
            "UPDATE {}.accepted_work SET idempotency_key='changed'",
            "DELETE FROM {}.accepted_work",
            "TRUNCATE {}.accepted_work",
            "UPDATE {}.schema_metadata SET version=2",
        ):
            with (
                closing(self.runtime.connect()) as connection,
                self.assertRaises(psycopg.errors.InsufficientPrivilege),
            ):
                connection.execute(sql.SQL(query).format(sql.Identifier(self.schema)))
        with self.assertRaises(WorkError):
            install_work_schema(self.runtime)
        with self.assertRaises(WorkError) as caught:
            install_work_schema(self.owner, WorkLimits(1, 1))
        self.assertEqual(caught.exception.code, "schema_mismatch")

    def test_catalog_drift_rejects_runtime_and_owner_without_adopting(self):
        for change, undo in (
            (
                "ALTER TABLE {}.accepted_work ENABLE ROW LEVEL SECURITY",
                "ALTER TABLE {}.accepted_work DISABLE ROW LEVEL SECURITY",
            ),
            (
                "CREATE INDEX extra_index ON {}.accepted_work(operation)",
                "DROP INDEX {}.extra_index",
            ),
        ):
            self.owner_sql(change)
            with self.assertRaises(WorkError) as runtime:
                self.client()
            self.assertEqual(runtime.exception.code, "schema_mismatch")
            with self.assertRaises(WorkError):
                install_work_schema(self.owner)
            self.owner_sql(undo)
            asyncio.run(self._valid_after_repair())

    async def _valid_after_repair(self):
        client = self.client()
        try:
            self.assertIsNone(await client.find(idempotency_key="absent"))
        finally:
            await client.close()

    def test_metadata_view_is_rejected_before_nontransactional_side_effect(self):
        self.owner_sql("ALTER TABLE {}.schema_metadata RENAME TO metadata_original")
        self.owner_sql("CREATE SEQUENCE {}.must_not_execute")
        self.owner_sql(
            f"CREATE VIEW {{}}.schema_metadata AS SELECT true AS singleton,nextval('{self.schema}.must_not_execute')::smallint AS version"
        )
        with self.assertRaises(WorkError) as caught:
            self.client()
        self.assertEqual(caught.exception.code, "schema_mismatch")
        with self.assertRaises(WorkError):
            install_work_schema(self.owner)
        self.assertFalse(
            self.owner_sql("SELECT is_called FROM {}.must_not_execute")[0]["is_called"]
        )

    def test_actual_io_admission_and_cancelled_waiter_retain_database_work(self):
        async def exercise():
            client = self.client()
            payload = self.payload()
            tasks = []
            try:
                with closing(self.owner.connect(application_name="continuity-test")) as connection:
                    with connection.transaction():
                        connection.execute(
                            sql.SQL("SELECT singleton FROM {}.admission FOR UPDATE").format(
                                sql.Identifier(self.schema)
                            )
                        )
                        tasks = [
                            asyncio.create_task(
                                client.submit(idempotency_key=f"io-{i}", payload=payload)
                            )
                            for i in range(4)
                        ]
                        deadline = time.monotonic() + 0.75
                        while client.pending_count != 4:
                            if time.monotonic() >= deadline:
                                self.fail("Actual I/O admission did not fill")
                            await asyncio.sleep(0.005)
                        tasks[0].cancel()
                        with self.assertRaises(asyncio.CancelledError):
                            await tasks[0]
                        self.assertEqual(client.pending_count, 4)
                        with self.assertRaises(WorkError) as caught:
                            await client.submit(idempotency_key="excess", payload=payload)
                        self.assertEqual(caught.exception.code, "capacity")
                        self.assertEqual(client.pending_count, 4)
                    await asyncio.gather(*tasks[1:])
                deadline = time.monotonic() + 2
                while client.pending_count:
                    if time.monotonic() >= deadline:
                        self.fail("Owned database calls did not settle")
                    await asyncio.sleep(0.005)
                original = await client.find(idempotency_key="io-0")
                self.assertIsNotNone(original)
                self.assertTrue(
                    (await client.submit(idempotency_key="later", payload=payload)).created
                )
            finally:
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                await client.close()

        asyncio.run(exercise())

    def test_unrelated_runtime_create_grant_fails_closed_then_progresses(self):
        extra = self.schema + "_extra"
        with closing(self.owner.connect(application_name="continuity-test")) as connection:
            connection.execute(
                sql.SQL("CREATE SCHEMA {} AUTHORIZATION continuity_migrator").format(
                    sql.Identifier(extra)
                )
            )
            try:
                connection.execute(
                    sql.SQL("GRANT CREATE ON SCHEMA {} TO livekit_lab").format(
                        sql.Identifier(extra)
                    )
                )
                with self.assertRaises(WorkError) as caught:
                    self.client()
                self.assertEqual(caught.exception.code, "schema_mismatch")
                connection.execute(
                    sql.SQL("REVOKE CREATE ON SCHEMA {} FROM livekit_lab").format(
                        sql.Identifier(extra)
                    )
                )
                asyncio.run(self._valid_after_repair())
            finally:
                connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(extra)))

    def test_sql_lock_timeout_is_capacity_then_original_key_progresses(self):
        async def run():
            client = self.client()
            payload = self.payload()
            try:
                with (
                    closing(self.owner.connect(application_name="continuity-test")) as connection,
                    connection.transaction(),
                ):
                    connection.execute(
                        sql.SQL("SELECT singleton FROM {}.admission FOR UPDATE").format(
                            sql.Identifier(self.schema)
                        )
                    )
                    with self.assertRaises(WorkError) as caught:
                        await client.submit(idempotency_key="blocked", payload=payload)
                    self.assertEqual(caught.exception.code, "capacity")
                self.assertIsNone(await client.find(idempotency_key="blocked"))
                self.assertTrue(
                    (await client.submit(idempotency_key="blocked", payload=payload)).created
                )
            finally:
                await client.close()

        asyncio.run(run())

    def test_logging_failure_cannot_change_committed_accept_replay_read_or_cancel(self):
        class Failing(logging.Handler):
            def emit(self, record):
                raise RuntimeError("PRIVATE_TELEMETRY_SENTINEL")

        logger = logging.getLogger("continuity_lab.readonly_work")
        handler = Failing()
        logger.addHandler(handler)
        level = logger.level
        logger.setLevel(logging.INFO)

        async def run():
            client = self.client()
            try:
                payload = self.payload()
                first = await client.submit(idempotency_key="telemetry", payload=payload)
                self.assertFalse(
                    (await client.submit(idempotency_key="telemetry", payload=payload)).created
                )
                self.assertEqual(await client.find(idempotency_key="telemetry"), first.record)
                await client.cancel(work_id=first.record.work_id, command_id="cancel")
                self.assertTrue((await client.get(work_id=first.record.work_id)).cancel_requested)
                self.assertGreaterEqual(client.metrics()["telemetry_failures"], 5)
            finally:
                await client.close()

        try:
            asyncio.run(run())
        finally:
            logger.removeHandler(handler)
            logger.setLevel(level)
