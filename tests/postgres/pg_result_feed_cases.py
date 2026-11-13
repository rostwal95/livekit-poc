"""Explicit actual PostgreSQL v4 result-feed tests; no source ACK or execution queue."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import threading
import time
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql

from continuity_lab.delivery_api import DeliveryReceipt, open_delivery_client
from continuity_lab.execution_api import ExecutionLimits, open_execution_client
from continuity_lab.result_feed_api import ResultFeedCursor, open_result_feed_client
from continuity_lab.work_admin import (
    install_work_schema,
    upgrade_work_schema_v2,
    upgrade_work_schema_v3,
    upgrade_work_schema_v4,
)
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
from harness.process_control import FileBarrier, OwnedProcess


class ResultFeedPostgresCases(unittest.IsolatedAsyncioTestCase):
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
        self.scope = WorkScope("tenant_feed", "account_feed")
        self.other = WorkScope("tenant_feed", "other_account")
        self.token = BearerToken("synthetic-feed-" + "x" * 40)
        self.clients = []
        self.addCleanup(self.drop)
        install_work_schema(self.owner, WorkLimits(10, 10))

    async def asyncTearDown(self):
        for client in self.clients:
            await client.close()
            self.assertEqual(client.pending_count, 0)

    def drop(self):
        with closing(self.owner.connect(application_name="continuity-test")) as connection:
            row = connection.execute(
                "SELECT pg_get_userbyid(nspowner) AS owner,obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=%s",
                [self.schema],
            ).fetchone()
            if row is not None:
                self.assertEqual(row["owner"], "continuity_migrator")
                self.assertIn(
                    row["marker"],
                    {
                        "continuity-readonly-work-v1",
                        "continuity-readonly-work-v2",
                        "continuity-readonly-work-v3",
                        "continuity-readonly-work-v4",
                    },
                )
                connection.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema))
                )

    def client(self, kind="work", *, scope=None, hook=None):
        scope = self.scope if scope is None else scope
        args = {
            "settings": self.runtime,
            "directory": WorkDirectory({self.token: WorkPrincipal("feed_actor", scope)}),
            "token": self.token,
        }
        factory = {
            "work": open_work_client,
            "execution": open_execution_client,
            "feed": open_result_feed_client,
            "delivery": open_delivery_client,
        }[kind]
        if kind in {"execution", "delivery"}:
            args["harness_failpoint"] = hook
        value = factory(**args)
        self.clients.append(value)
        return value

    def ready(self, *, feed=True, limits=None):
        upgrade_work_schema_v2(self.owner, ExecutionLimits() if limits is None else limits)
        upgrade_work_schema_v3(self.owner)
        if feed:
            upgrade_work_schema_v4(self.owner)

    async def accepted(self, key="one", scope=None):
        return (
            await self.client(scope=scope).submit(
                idempotency_key=key,
                payload=WorkPayload(
                    "booking.evaluate_policy",
                    b'{"opaque":"original"}',
                    time.time_ns() // 1000000 + 60000,
                ),
            )
        ).record

    async def grant(self, key="one", scope=None):
        record = await self.accepted(key, scope)
        attempt = (
            await self.client("execution", scope=scope).issue(
                work_id=record.work_id, owner_id=str(uuid4()), command_id="issue_" + key
            )
        ).attempt
        return record, attempt

    async def useful(self, key="one", scope=None):
        record, attempt = await self.grant(key, scope)
        result = await self.client("execution", scope=scope).complete(
            attempt=attempt, body=b'{"opaque":"result"}'
        )
        return record, attempt, result

    def query(self, statement, values=(), *, runtime=False):
        with closing(
            (self.runtime if runtime else self.owner).connect(application_name="continuity-test")
        ) as connection:
            cursor = connection.execute(
                sql.SQL(statement).format(sql.Identifier(self.schema)), values
            )
            return [] if cursor.description is None else cursor.fetchall()

    def old_bytes(self):
        return {
            name: self.query(
                "SELECT row_to_json(t)::text AS original FROM {}."
                + name
                + " t ORDER BY row_to_json(t)::text"
            )
            for name in (
                "accepted_work",
                "cancellation_commands",
                "issued_attempts",
                "attempt_results",
                "result_delivery_intents",
                "result_delivery_possible",
                "result_delivery_receipts",
                "result_actions",
            )
        }

    async def error(self, awaitable, code):
        with self.assertRaises(WorkError) as caught:
            await awaitable
        self.assertEqual(caught.exception.code, code)

    def wait_after(self, timestamp):
        until = time.monotonic() + 3
        with closing(self.owner.connect(application_name="continuity-test")) as connection:
            while True:
                if (
                    connection.execute(
                        "SELECT floor(extract(epoch FROM clock_timestamp())*1000)::bigint AS now"
                    ).fetchone()["now"]
                    >= timestamp
                ):
                    return
                self.assertLess(time.monotonic(), until)
                connection.execute("SELECT pg_sleep(0.005)")

    async def test_explicit_upgrade_preserves_bytes_and_replay_source_and_prior_apis(self):
        with self.assertRaises(WorkError):
            self.client("feed")
        with self.assertRaises(WorkError):
            upgrade_work_schema_v4(self.owner)
        self.ready(feed=False)
        record, attempt, result = await self.useful()
        delivery = self.client("delivery")
        intent = await delivery.prepare(
            work_id=record.work_id,
            attempt_id=attempt.attempt_id,
            result_sha256=result.sha256,
            receiver_id=str(uuid4()),
            recipient_id="original_receiver",
        )
        await delivery.begin(intent=intent)
        original_receipt = DeliveryReceipt(
            intent.delivery_id,
            str(uuid4()),
            intent.receiver_id,
            intent.recipient_id,
            intent.result_sha256,
            time.time_ns() // 1000000,
        )
        await delivery.record_receipt(intent=intent, receipt=original_receipt)
        cancellation = await self.client().cancel(
            work_id=record.work_id, command_id="cancel-after-result"
        )
        before = self.old_bytes()
        upgrade_work_schema_v4(self.owner)
        feed = self.client("feed")
        page = await feed.read(limit=1)
        self.assertEqual(len(page.events), 1)
        event = page.events[0]
        self.assertEqual(
            (
                event.work_id,
                event.attempt_id,
                event.issue_command_id,
                event.result_sha256,
                event.recorded_at_ms,
                event.disposition,
                event.origin,
            ),
            (
                record.work_id,
                attempt.attempt_id,
                attempt.command_id,
                result.sha256,
                result.recorded_at_ms,
                result.disposition,
                "adopted_history",
            ),
        )
        self.assertEqual(page.next_cursor.sequence, 1)
        self.assertFalse(page.has_more)
        upgrade_work_schema_v4(self.owner)
        upgrade_work_schema_v3(self.owner)
        upgrade_work_schema_v2(self.owner)
        install_work_schema(self.owner, WorkLimits(10, 10))
        reopened = self.client("feed")
        self.assertEqual(reopened.source_id, feed.source_id)
        self.assertEqual(await reopened.read(), page)
        self.assertEqual(self.old_bytes(), before)
        self.assertEqual(
            await self.client("delivery").record_receipt(intent=intent, receipt=original_receipt),
            original_receipt,
        )
        self.assertEqual(
            await self.client().cancel(work_id=record.work_id, command_id="cancel-after-result"),
            cancellation,
        )
        self.assertEqual(
            await self.client("execution").complete(attempt=attempt, body=result.body), result
        )
        self.assertEqual(await feed.read(), page)

    async def test_upgrade_rolls_back_before_commit_and_unknown_ack_retains_adoption(self):
        self.ready(feed=False)
        await self.useful()
        before = self.old_bytes()

        def fail_before(stage):
            if stage == "upgrade_v4.before_commit":
                raise OSError("PRIVATE_FEED_UPGRADE")

        with self.assertRaises(WorkError) as caught:
            upgrade_work_schema_v4(self.owner, harness_failpoint=fail_before)
        self.assertEqual(caught.exception.code, "storage_unavailable")
        self.assertEqual(self.query("SELECT version FROM {}.schema_metadata")[0]["version"], 3)
        self.assertEqual(self.old_bytes(), before)
        self.assertEqual(
            self.query(
                "SELECT count(*) AS n FROM pg_tables WHERE schemaname=%s AND tablename LIKE 'result_feed_%%'",
                (self.schema,),
            )[0]["n"],
            0,
        )

        def fail_after(stage):
            if stage == "upgrade_v4.after_commit":
                raise OSError("PRIVATE_FEED_ACK")

        with self.assertRaises(WorkError) as caught:
            upgrade_work_schema_v4(self.owner, harness_failpoint=fail_after)
        self.assertEqual(caught.exception.code, "acknowledgement_unknown")
        first = await self.client("feed").read()
        upgrade_work_schema_v4(self.owner)
        self.assertEqual(first, await self.client("feed").read())
        self.assertEqual(self.old_bytes(), before)

    async def test_backfill_retains_all_historical_attempts_with_honest_adoption_order(self):
        self.ready(feed=False, limits=ExecutionLimits(2, 3, 100))
        record, first = await self.grant()
        await asyncio.to_thread(self.wait_after, first.lease_until_ms)
        second = (
            await self.client("execution").issue(
                work_id=record.work_id, owner_id=str(uuid4()), command_id="issue_second"
            )
        ).attempt
        result2 = await self.client("execution").complete(attempt=second, body=b"second")
        result1 = await self.client("execution").complete(attempt=first, body=b"first-late")
        self.assertEqual(result1.disposition, "superseded")
        upgrade_work_schema_v4(self.owner)
        feed = self.client("feed")
        events = (await feed.read()).events
        expected = sorted(
            (result1, result2),
            key=lambda r: (
                r.recorded_at_ms,
                r.work_id,
                1 if r.attempt_id == first.attempt_id else 2,
                r.attempt_id,
            ),
        )
        self.assertEqual([e.attempt_id for e in events], [r.attempt_id for r in expected])
        for event in events:
            self.assertEqual(event.origin, "adopted_history")
            historical = await self.client("execution").find_issue(
                command_id=event.issue_command_id
            )
            self.assertEqual(historical.attempt_id, event.attempt_id)
            self.assertEqual(
                (
                    await self.client("execution").result(
                        work_id=event.work_id, attempt_id=event.attempt_id
                    )
                ).sha256,
                event.result_sha256,
            )

    async def test_live_completion_event_is_atomic_and_replay_emits_nothing(self):
        self.ready()
        feed = self.client("feed")
        initial = await feed.read()
        self.assertEqual(initial.high_watermark.sequence, 0)
        record, attempt = await self.grant()

        def fail(stage):
            if stage == "complete.before_commit":
                raise OSError("PRIVATE_COMPLETE_BEFORE")

        await self.error(
            self.client("execution", hook=fail).complete(attempt=attempt, body=b"known"),
            "storage_unavailable",
        )
        self.assertEqual((await feed.read()).events, ())
        self.assertIsNone(
            await self.client("execution").result(
                work_id=record.work_id, attempt_id=attempt.attempt_id
            )
        )
        result = await self.client("execution").complete(attempt=attempt, body=b"known")
        page = await feed.read()
        self.assertEqual(len(page.events), 1)
        self.assertEqual(page.events[0].origin, "live")
        self.assertEqual(page.events[0].result_sha256, result.sha256)
        self.assertEqual(
            await self.client("execution").complete(attempt=attempt, body=b"known"), result
        )
        await self.error(
            self.client("execution").complete(attempt=attempt, body=b"changed"), "identity_conflict"
        )
        self.assertEqual(await feed.read(), page)
        await self.client().cancel(work_id=record.work_id, command_id="later-cancel")
        self.assertTrue(
            (await self.client("execution").observe(work_id=record.work_id)).record.cancel_requested
        )
        self.assertEqual(await feed.read(), page)

    async def test_unknown_completion_ack_has_one_findable_event_and_result(self):
        self.ready()
        record, attempt = await self.grant()

        def fail(stage):
            if stage == "complete.after_commit":
                raise OSError("PRIVATE_ACK")

        await self.error(
            self.client("execution", hook=fail).complete(attempt=attempt, body=b"result"),
            "acknowledgement_unknown",
        )
        result = await self.client("execution").result(
            work_id=record.work_id, attempt_id=attempt.attempt_id
        )
        self.assertEqual(result.body, b"result")
        first = await self.client("feed").read()
        self.assertEqual(len(first.events), 1)
        await self.client("execution").complete(attempt=attempt, body=b"result")
        self.assertEqual(await self.client("feed").read(), first)

    async def test_scope_local_cursors_pages_empty_reads_and_foreign_identity(self):
        self.ready()
        await self.useful("one")
        await self.useful("foreign", self.other)
        await self.useful("two")
        feed = self.client("feed")
        page1 = await feed.read(limit=1)
        self.assertEqual(
            (page1.next_cursor.sequence, page1.high_watermark.sequence, page1.has_more),
            (1, 2, True),
        )
        page2 = await feed.read(after=page1.next_cursor, limit=1)
        self.assertEqual(
            (page2.next_cursor.sequence, page2.high_watermark.sequence, page2.has_more),
            (2, 2, False),
        )
        empty = await feed.read(after=page2.next_cursor)
        self.assertEqual(empty.events, ())
        self.assertEqual(empty.after, empty.next_cursor)
        other = self.client("feed", scope=self.other)
        self.assertEqual((await other.read()).high_watermark.sequence, 1)
        await self.error(other.read(after=page1.next_cursor), "identity_conflict")
        await self.error(
            feed.read(after=ResultFeedCursor(str(uuid4()), self.scope, 0)), "identity_conflict"
        )
        await self.error(
            feed.read(after=ResultFeedCursor(feed.source_id, self.scope, 3)), "invalid_input"
        )
        self.assertEqual((await feed.read(limit=100)).events, (page1.events[0], page2.events[0]))

    async def test_uncommitted_lower_event_cannot_be_skipped_by_later_completion(self):
        self.ready()
        one, first = await self.grant("first")
        two, second = await self.grant("second")
        entered, release = threading.Event(), threading.Event()

        def hold(stage):
            if stage == "complete.before_commit":
                entered.set()
                if not release.wait(4):
                    raise TimeoutError("held completion")

        first_task = asyncio.create_task(
            self.client("execution", hook=hold).complete(attempt=first, body=b"first")
        )
        self.assertTrue(await asyncio.to_thread(entered.wait, 3))
        second_task = asyncio.create_task(
            self.client("execution").complete(attempt=second, body=b"second")
        )
        try:

            def blocked():
                until = time.monotonic() + 2
                with closing(
                    self.runtime.connect(application_name="continuity-test")
                ) as connection:
                    while True:
                        row = connection.execute(
                            "SELECT count(*) AS n FROM pg_stat_activity WHERE pid<>pg_backend_pid() AND wait_event_type='Lock' AND cardinality(pg_blocking_pids(pid))>0 AND query LIKE %s",
                            ["%" + self.schema + "%admission%"],
                        ).fetchone()
                        if row["n"] >= 1:
                            return row["n"]
                        if time.monotonic() >= until:
                            return 0
                        connection.execute("SELECT pg_sleep(0.01)")

            self.assertGreaterEqual(await asyncio.to_thread(blocked), 1)
            self.assertFalse(second_task.done())
            feed = self.client("feed")
            self.assertEqual((await feed.read()).events, ())
        finally:
            release.set()
            await asyncio.gather(first_task, second_task)
        page = await self.client("feed").read()
        self.assertEqual(
            [(e.sequence, e.work_id) for e in page.events], [(1, one.work_id), (2, two.work_id)]
        )

    async def test_v4_delivery_reuses_exact_existing_result_and_receipt(self):
        self.ready()
        record, attempt, result = await self.useful()
        delivery = self.client("delivery")
        intent = await delivery.prepare(
            work_id=record.work_id,
            attempt_id=attempt.attempt_id,
            result_sha256=result.sha256,
            receiver_id=str(uuid4()),
            recipient_id="conversation_feed",
        )
        self.assertTrue((await delivery.begin(intent=intent)).created)
        receipt = DeliveryReceipt(
            intent.delivery_id,
            str(uuid4()),
            intent.receiver_id,
            intent.recipient_id,
            intent.result_sha256,
            time.time_ns() // 1000000,
        )
        accepted = await delivery.record_receipt(intent=intent, receipt=receipt)
        self.assertEqual(await delivery.record_receipt(intent=intent, receipt=receipt), accepted)
        self.assertEqual(len((await self.client("feed").read()).events), 1)

    async def test_runtime_grants_and_corrupt_head_fail_closed_without_repair(self):
        self.ready()
        await self.useful()
        for statement in (
            "UPDATE {}.result_feed_source SET source_id=gen_random_uuid()",
            "DELETE FROM {}.result_feed_events",
            "UPDATE {}.result_feed_events SET origin='adopted_history'",
            "UPDATE {}.result_feed_heads SET anchor_work_id=gen_random_uuid()",
        ):
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                self.query(statement, runtime=True)
        feed = self.client("feed")
        self.query("UPDATE {}.result_feed_heads SET last_sequence=0")
        await self.error(feed.read(), "schema_mismatch")
        with self.assertRaises(WorkError) as caught:
            upgrade_work_schema_v4(self.owner)
        self.assertEqual(caught.exception.code, "schema_mismatch")
        self.assertEqual(
            self.query("SELECT last_sequence FROM {}.result_feed_heads")[0]["last_sequence"], 0
        )

    async def test_existing_client_rejects_recreated_profile_source_identity(self):
        self.ready()
        original = self.client("feed")
        source = original.source_id
        self.drop()
        install_work_schema(self.owner, WorkLimits(10, 10))
        self.ready()
        self.assertNotEqual(self.client("feed").source_id, source)
        await self.error(original.read(), "identity_conflict")

    async def test_actual_owner_sigkill_before_adoption_commit_rolls_back(self):
        self.ready(feed=False)
        record, _, _ = await self.useful()
        original = self.old_bytes()
        code = r"""
import os,threading
from pathlib import Path
from continuity_lab.work_api import PostgresSettings
from continuity_lab.work_admin import upgrade_work_schema_v4
assert not any(key.startswith("P1_POSTGRES_") for key in os.environ)
def hold(stage):
 if stage=="upgrade_v4.before_commit":
  path=Path(os.environ["UPGRADE_MARKER"])
  with path.open("x") as output:output.write(str(os.getpid())+"\n")
  path.chmod(0o600)
  threading.Event().wait(20)
upgrade_work_schema_v4(PostgresSettings.from_env("P1_MIGRATION_"),harness_failpoint=hold)
"""
        with tempfile.TemporaryDirectory(prefix="p1-feed-upgrade-") as temporary:
            state = Path(temporary).resolve()
            barrier = FileBarrier(state, "upgrade")
            env = {
                key: os.environ[key]
                for key in ("PATH", "HOME", "TMPDIR", "LANG")
                if key in os.environ
            }
            env.update(
                {
                    "P1_MIGRATION_HOST": self.owner.host,
                    "P1_MIGRATION_PORT": str(self.owner.port),
                    "P1_MIGRATION_DB": self.owner.dbname,
                    "P1_MIGRATION_USER": self.owner.user,
                    "P1_MIGRATION_PASSWORD": self.owner.password,
                    "P1_MIGRATION_SCHEMA": self.schema,
                    "UPGRADE_MARKER": str(state / "upgrade.reached"),
                }
            )
            with OwnedProcess(
                [sys.executable, "-I", "-c", code],
                cwd=state,
                env=env,
                output_directory=state / "child",
                max_output_bytes=4096,
            ) as child:
                await asyncio.to_thread(child.wait_for_barrier, barrier, timeout=5)
                killed = await asyncio.to_thread(child.kill, timeout=3)
                self.assertTrue(killed.killed)
                self.assertEqual(killed.returncode, -9)
            self.assertFalse(child.cleanup_failed)
        self.assertEqual(self.query("SELECT version FROM {}.schema_metadata")[0]["version"], 3)
        self.assertEqual(self.old_bytes(), original)
        self.assertEqual(await self.client().get(work_id=record.work_id), record)
        self.assertEqual(
            self.query(
                "SELECT count(*) AS n FROM pg_tables WHERE schemaname=%s AND tablename LIKE 'result_feed_%%'",
                (self.schema,),
            )[0]["n"],
            0,
        )
        upgrade_work_schema_v4(self.owner)
        self.assertEqual(len((await self.client("feed").read()).events), 1)
