"""Explicit PostgreSQL delivery-profile tests; no offline skip or second executor."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql

from continuity_lab.delivery_api import DeliveryReceipt, open_delivery_client
from continuity_lab.execution_api import open_execution_client
from continuity_lab.work_admin import (
    install_work_schema,
    upgrade_work_schema_v2,
    upgrade_work_schema_v3,
)
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
from harness.process_control import FileBarrier, OwnedProcess


class ResultDeliveryPostgresCases(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("P1_RUN_POSTGRES_TESTS") != "1":
            raise RuntimeError("Explicit PostgreSQL setup required")
        cls.runtime_base = PostgresSettings.from_env()
        cls.owner_base = PostgresSettings.from_env("P1_MIGRATION_")

    def setUp(self):
        self.schema = "p1_work_" + uuid4().hex
        self.runtime = replace(self.runtime_base, schema=self.schema)
        self.owner = replace(self.owner_base, schema=self.schema)
        self.scope = WorkScope("tenant_delivery", "account_delivery")
        self.token = BearerToken("synthetic-delivery-" + "x" * 40)
        self.directory = WorkDirectory({self.token: WorkPrincipal("actor_delivery", self.scope)})
        self.receiver_id = str(uuid4())
        self.clients = []
        self.addCleanup(self.drop)
        install_work_schema(self.owner)

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
                    },
                )
                connection.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema))
                )

    def work(self, scope=None):
        directory = (
            self.directory
            if scope is None
            else WorkDirectory({self.token: WorkPrincipal("other_actor", scope)})
        )
        value = open_work_client(settings=self.runtime, directory=directory, token=self.token)
        self.clients.append(value)
        return value

    def execution(self):
        value = open_execution_client(
            settings=self.runtime, directory=self.directory, token=self.token
        )
        self.clients.append(value)
        return value

    def delivery(self, scope=None, hook=None):
        directory = (
            self.directory
            if scope is None
            else WorkDirectory({self.token: WorkPrincipal("other_actor", scope)})
        )
        value = open_delivery_client(
            settings=self.runtime, directory=directory, token=self.token, harness_failpoint=hook
        )
        self.clients.append(value)
        return value

    def ready(self):
        upgrade_work_schema_v2(self.owner)
        upgrade_work_schema_v3(self.owner)

    async def accepted(self, key="one", deadline=None):
        return (
            await self.work().submit(
                idempotency_key=key,
                payload=WorkPayload(
                    "booking.evaluate_policy",
                    b'{"input":"original"}',
                    deadline or time.time_ns() // 1000000 + 60000,
                ),
            )
        ).record

    async def useful(self, key="one", deadline=None):
        record = await self.accepted(key, deadline)
        grant = (
            await self.execution().issue(
                work_id=record.work_id, owner_id=str(uuid4()), command_id="issue_" + key
            )
        ).attempt
        result = await self.execution().complete(attempt=grant, body=b'{"eligible":true}')
        return record, grant, result

    async def prepared(self, key="one"):
        record, grant, result = await self.useful(key)
        intent = await self.delivery().prepare(
            work_id=record.work_id,
            attempt_id=grant.attempt_id,
            result_sha256=result.sha256,
            receiver_id=self.receiver_id,
            recipient_id="conversation_delivery",
        )
        return record, grant, result, intent

    def receipt(self, intent):
        return DeliveryReceipt(
            intent.delivery_id,
            str(uuid4()),
            intent.receiver_id,
            intent.recipient_id,
            intent.result_sha256,
            time.time_ns() // 1000000,
        )

    def count(self, table):
        with closing(self.owner.connect(application_name="continuity-test")) as connection:
            return connection.execute(
                sql.SQL("SELECT count(*) AS count FROM {}").format(
                    sql.Identifier(self.schema, table)
                )
            ).fetchone()["count"]

    async def test_explicit_upgrade_preserves_original_data_and_old_apis(self):
        record = await self.accepted()
        with self.assertRaises(WorkError):
            upgrade_work_schema_v3(self.owner)
        with self.assertRaises(WorkError):
            self.delivery()
        upgrade_work_schema_v2(self.owner)
        with self.assertRaises(WorkError):
            self.delivery()

        def before(stage):
            if stage == "upgrade_v3.before_commit":
                raise OSError("PRIVATE_UPGRADE")

        with self.assertRaises(WorkError):
            upgrade_work_schema_v3(self.owner, harness_failpoint=before)
        with closing(self.owner.connect(application_name="continuity-test")) as connection:
            self.assertEqual(
                connection.execute(
                    sql.SQL("SELECT version FROM {}.schema_metadata").format(
                        sql.Identifier(self.schema)
                    )
                ).fetchone()["version"],
                2,
            )

        def after(stage):
            if stage == "upgrade_v3.after_commit":
                raise OSError("PRIVATE_ACK")

        with self.assertRaises(WorkError) as caught:
            upgrade_work_schema_v3(self.owner, harness_failpoint=after)
        self.assertEqual(caught.exception.code, "acknowledgement_unknown")
        upgrade_work_schema_v3(self.owner)
        upgrade_work_schema_v2(self.owner)
        install_work_schema(self.owner)
        self.assertEqual(await self.work().get(work_id=record.work_id), record)
        self.assertFalse(
            (await self.work().submit(idempotency_key="one", payload=record.payload)).created
        )
        with closing(self.owner.connect(application_name="continuity-test")) as connection:
            self.assertEqual(
                connection.execute(
                    sql.SQL("SELECT version FROM {}.schema_metadata").format(
                        sql.Identifier(self.schema)
                    )
                ).fetchone()["version"],
                3,
            )
        self.assertEqual(
            (await self.execution().observe(work_id=record.work_id)).status, "accepted"
        )

    async def test_actual_owner_process_kill_before_upgrade_commit_rolls_back(self):
        record = await self.accepted()
        upgrade_work_schema_v2(self.owner)
        code = r"""
import os,threading
from pathlib import Path
from continuity_lab.work_api import PostgresSettings
from continuity_lab.work_admin import upgrade_work_schema_v3
assert not any(key.startswith("P1_POSTGRES_") for key in os.environ)
def hold(stage):
 if stage=="upgrade_v3.before_commit":
  path=Path(os.environ["UPGRADE_MARKER"])
  with path.open("x") as output:output.write(str(os.getpid())+"\n")
  path.chmod(0o600)
  threading.Event().wait(20)
upgrade_work_schema_v3(PostgresSettings.from_env("P1_MIGRATION_"),harness_failpoint=hold)
"""
        with tempfile.TemporaryDirectory(prefix="p1-delivery-upgrade-") as temporary:
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
                child.wait_for_barrier(barrier, timeout=5)
                killed = child.kill(timeout=3)
                self.assertTrue(killed.killed)
                self.assertEqual(killed.returncode, -9)
            self.assertFalse(child.cleanup_failed)
        self.assertEqual(await self.work().get(work_id=record.work_id), record)
        with closing(self.owner.connect(application_name="continuity-test")) as connection:
            self.assertEqual(
                connection.execute(
                    sql.SQL("SELECT version FROM {}.schema_metadata").format(
                        sql.Identifier(self.schema)
                    )
                ).fetchone()["version"],
                2,
            )
            self.assertIsNone(
                connection.execute(
                    "SELECT 1 FROM pg_tables WHERE schemaname=%s AND tablename='result_actions'",
                    [self.schema],
                ).fetchone()
            )
        upgrade_work_schema_v3(self.owner)
        self.assertIsNone((await self.delivery().inspect(work_id=record.work_id)).intent)

    async def test_normal_scoped_prepare_start_receipt_and_original_replay(self):
        self.ready()
        record, _grant, result, intent = await self.prepared()
        client = self.delivery()
        self.assertEqual((await client.inspect(work_id=record.work_id)).intent, intent)
        self.assertFalse((await client.inspect(work_id=record.work_id)).possible)
        self.assertTrue((await client.begin(intent=intent)).created)
        self.assertFalse((await client.begin(intent=intent)).created)
        receipt = self.receipt(intent)
        self.assertEqual(await client.record_receipt(intent=intent, receipt=receipt), receipt)
        self.assertEqual(
            await self.delivery().record_receipt(intent=intent, receipt=receipt), receipt
        )
        self.assertEqual((await client.inspect(work_id=record.work_id)).receipt, receipt)
        self.assertEqual(self.count("result_delivery_intents"), 1)
        self.assertEqual(self.count("result_delivery_possible"), 1)
        self.assertEqual(self.count("result_delivery_receipts"), 1)
        self.assertEqual(intent.body, result.body)
        self.assertEqual(intent.result_sha256, result.sha256)
        self.assertEqual((await self.work().get(work_id=record.work_id)).payload, record.payload)

    async def test_immutable_receiver_recipient_and_result_conflicts_do_not_retarget(self):
        self.ready()
        record, grant, result, intent = await self.prepared()
        client = self.delivery()
        for changes in (
            {"receiver_id": str(uuid4())},
            {"recipient_id": "another"},
            {"result_sha256": "0" * 64},
            {"attempt_id": str(uuid4())},
        ):
            kwargs = {
                "work_id": record.work_id,
                "attempt_id": grant.attempt_id,
                "result_sha256": result.sha256,
                "receiver_id": self.receiver_id,
                "recipient_id": "conversation_delivery",
            }
            kwargs.update(changes)
            with self.assertRaises(WorkError) as caught:
                await client.prepare(**kwargs)
            self.assertEqual(caught.exception.code, "identity_conflict")
        with self.assertRaises(WorkError):
            await client.begin(intent=replace(intent, receiver_id=str(uuid4())))
        self.assertFalse((await client.inspect(work_id=record.work_id)).possible)
        self.assertEqual((await client.inspect(work_id=record.work_id)).intent, intent)

    async def test_scope_lookups_and_forged_receipts_cannot_disclose_or_commit(self):
        self.ready()
        record, _grant, _result, intent = await self.prepared()
        foreign = self.delivery(WorkScope("tenant_delivery", "other"))
        with self.assertRaises(WorkError) as caught:
            await foreign.inspect(work_id=record.work_id)
        self.assertEqual(caught.exception.code, "not_found")
        with self.assertRaises(WorkError):
            await foreign.begin(intent=intent)
        client = self.delivery()
        with self.assertRaises(WorkError):
            await client.record_receipt(intent=intent, receipt=self.receipt(intent))
        await client.begin(intent=intent)
        with self.assertRaises(WorkError):
            await client.record_receipt(
                intent=intent, receipt=replace(self.receipt(intent), recipient_id="other")
            )
        self.assertIsNone((await client.inspect(work_id=record.work_id)).receipt)
        self.assertIsNotNone(
            await client.record_receipt(intent=intent, receipt=self.receipt(intent))
        )

    async def test_cancel_before_prepare_and_after_prepare_prevents_new_external_start(self):
        self.ready()
        record, grant, result = await self.useful("before")
        await self.work().cancel(work_id=record.work_id, command_id="cancel_before")
        with self.assertRaises(WorkError) as caught:
            await self.delivery().prepare(
                work_id=record.work_id,
                attempt_id=grant.attempt_id,
                result_sha256=result.sha256,
                receiver_id=self.receiver_id,
                recipient_id="conversation_delivery",
            )
        self.assertEqual(caught.exception.code, "expired")
        second, _, _, intent = await self.prepared("after")
        await self.work().cancel(work_id=second.work_id, command_id="cancel_after")
        with self.assertRaises(WorkError) as caught:
            await self.delivery().begin(intent=intent)
        self.assertEqual(caught.exception.code, "expired")
        self.assertFalse((await self.delivery().inspect(work_id=second.work_id)).possible)

    async def test_known_late_receipt_and_original_prepare_replay_survive_cancellation(self):
        self.ready()
        record, grant, result, intent = await self.prepared()
        client = self.delivery()
        await client.begin(intent=intent)
        await self.work().cancel(work_id=record.work_id, command_id="cancel_late")
        self.assertFalse((await client.begin(intent=intent)).created)
        self.assertEqual(
            await client.prepare(
                work_id=record.work_id,
                attempt_id=grant.attempt_id,
                result_sha256=result.sha256,
                receiver_id=self.receiver_id,
                recipient_id="conversation_delivery",
            ),
            intent,
        )
        receipt = self.receipt(intent)
        self.assertEqual(await client.record_receipt(intent=intent, receipt=receipt), receipt)
        self.assertEqual((await client.inspect(work_id=record.work_id)).receipt, receipt)
        with self.assertRaises(WorkError):
            await client.record_receipt(
                intent=intent, receipt=replace(receipt, receipt_id=str(uuid4()))
            )

    async def test_concurrent_clients_keep_one_binding_one_possible_marker_one_receipt(self):
        self.ready()
        record, grant, result = await self.useful()

        def prepare(_):
            async def call():
                client = open_delivery_client(
                    settings=self.runtime, directory=self.directory, token=self.token
                )
                try:
                    return await client.prepare(
                        work_id=record.work_id,
                        attempt_id=grant.attempt_id,
                        result_sha256=result.sha256,
                        receiver_id=self.receiver_id,
                        recipient_id="conversation_delivery",
                    )
                finally:
                    await client.close()

            return asyncio.run(call())

        with ThreadPoolExecutor(max_workers=6) as pool:
            intents = list(pool.map(prepare, range(6)))
        self.assertEqual(len(set(intents)), 1)
        intent = intents[0]
        starts = await asyncio.gather(*(self.delivery().begin(intent=intent) for _ in range(6)))
        self.assertEqual(sum(value.created for value in starts), 1)
        receipt = self.receipt(intent)
        values = await asyncio.gather(
            *(self.delivery().record_receipt(intent=intent, receipt=receipt) for _ in range(6))
        )
        self.assertTrue(all(value == receipt for value in values))
        self.assertEqual(self.count("result_delivery_receipts"), 1)

    async def test_prepare_begin_and_receipt_commit_uncertainty_reconcile_original(self):
        self.ready()
        record, grant, result = await self.useful()
        for stage in (
            "delivery_prepare.after_commit",
            "delivery_begin.after_commit",
            "delivery_receipt.after_commit",
        ):

            def failpoint(point, expected_stage=stage):
                if point == expected_stage:
                    raise OSError("PRIVATE_ACK")

            client = self.delivery(hook=failpoint)
            with self.assertRaises(WorkError) as caught:
                if stage.startswith("delivery_prepare"):
                    await client.prepare(
                        work_id=record.work_id,
                        attempt_id=grant.attempt_id,
                        result_sha256=result.sha256,
                        receiver_id=self.receiver_id,
                        recipient_id="conversation_delivery",
                    )
                elif stage.startswith("delivery_begin"):
                    await client.begin(
                        intent=(await self.delivery().inspect(work_id=record.work_id)).intent
                    )
                else:
                    intent = (await self.delivery().inspect(work_id=record.work_id)).intent
                    await client.record_receipt(intent=intent, receipt=self.receipt(intent))
            self.assertEqual(caught.exception.code, "acknowledgement_unknown")
            self.assertNotIn("PRIVATE", str(caught.exception))
        snapshot = await self.delivery().inspect(work_id=record.work_id)
        self.assertTrue(snapshot.possible)
        self.assertIsNotNone(snapshot.receipt)

    async def test_runtime_privileges_schema_drift_and_logger_failure_useful_progress(self):
        self.ready()
        record, _, _, intent = await self.prepared()
        client = self.delivery()
        with closing(self.runtime.connect()) as connection:
            for statement in (
                "UPDATE {}.result_delivery_intents SET recipient_id='retarget'",
                "DELETE FROM {}.result_delivery_intents",
                "CREATE TABLE {}.bad(value integer)",
            ):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    connection.execute(sql.SQL(statement).format(sql.Identifier(self.schema)))
        with closing(self.owner.connect(application_name="continuity-test")) as connection:
            connection.execute(
                sql.SQL(
                    "CREATE INDEX extra_delivery ON {}.result_delivery_intents(recipient_id)"
                ).format(sql.Identifier(self.schema))
            )
        with self.assertRaises(WorkError) as caught:
            self.delivery()
        self.assertEqual(caught.exception.code, "schema_mismatch")
        with closing(self.owner.connect(application_name="continuity-test")) as connection:
            connection.execute(
                sql.SQL("DROP INDEX {}.extra_delivery").format(sql.Identifier(self.schema))
            )

        class Throw(logging.Handler):
            def emit(self, record):
                raise RuntimeError("PRIVATE_TELEMETRY")

        logger = logging.getLogger("continuity_lab.readonly_work")
        handler = Throw()
        previous = logger.level
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        try:
            await client.begin(intent=intent)
            receipt = self.receipt(intent)
            self.assertEqual(await client.record_receipt(intent=intent, receipt=receipt), receipt)
            self.assertEqual((await client.inspect(work_id=record.work_id)).receipt, receipt)
            self.assertGreaterEqual(client.metrics()["telemetry_failures"], 3)
        finally:
            logger.removeHandler(handler)
            logger.setLevel(previous)

    async def test_database_clock_after_waited_lock_prevents_expired_new_delivery_start(self):
        self.ready()
        record, grant, result = await self.useful(deadline=time.time_ns() // 1000000 + 900)
        client = self.delivery()
        intent = await client.prepare(
            work_id=record.work_id,
            attempt_id=grant.attempt_id,
            result_sha256=result.sha256,
            receiver_id=self.receiver_id,
            recipient_id="conversation_delivery",
        )
        with (
            closing(self.owner.connect(application_name="continuity-test")) as blocker,
            blocker.transaction(),
        ):
            blocker.execute(
                sql.SQL("SELECT * FROM {}.admission FOR UPDATE").format(sql.Identifier(self.schema))
            )
            pending = asyncio.create_task(client.begin(intent=intent))
            await asyncio.sleep(0.05)
            while time.time_ns() // 1000000 <= record.payload.deadline_at_ms:
                await asyncio.sleep(0.02)
        with self.assertRaises(WorkError) as caught:
            await pending
        self.assertEqual(caught.exception.code, "expired")
        with self.assertRaises(WorkError) as caught:
            await client.begin(intent=intent)
        self.assertEqual(caught.exception.code, "expired")
        self.assertFalse((await client.inspect(work_id=record.work_id)).possible)
