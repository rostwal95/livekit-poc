"""Actual private receiver storage and bounded owned I/O, with no remote services."""

import asyncio
import hashlib
import logging
import sqlite3
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from continuity_lab.delivery_api import (
    DeliveryIntent,
    DeliveryReceipt,
    DeliverySnapshot,
    DeliveryStart,
)
from continuity_lab.receiver_api import (
    ReceiverBinding,
    initialize_result_receiver,
    open_result_receiver,
)
from continuity_lab.work_api import WorkError, WorkScope


class ReceiverCases(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "receiver.sqlite3"
        self.scope = WorkScope("tenant", "account")
        self.receiver_id = str(uuid4())
        self.binding = ReceiverBinding(self.scope, "conversation")
        self.clients = []

    async def asyncTearDown(self):
        for client in self.clients:
            await client.close()
            self.assertEqual(client.pending_count, 0)

    def install(self, limit=1000):
        return initialize_result_receiver(
            self.path, receiver_id=self.receiver_id, maximum_records=limit
        )

    def receiver(self, **kwargs):
        value = open_result_receiver(
            self.path, receiver_id=self.receiver_id, bindings=(self.binding,), **kwargs
        )
        self.clients.append(value)
        return value

    def intent(self, body=b'{"eligible":true}'):
        return DeliveryIntent(
            str(uuid4()),
            self.scope,
            str(uuid4()),
            str(uuid4()),
            hashlib.sha256(body).hexdigest(),
            self.receiver_id,
            "conversation",
            body,
            2000000000000,
        )

    async def test_explicit_owner_init_private_schema_and_no_implicit_runtime_ddl(self):
        with self.assertRaises(WorkError):
            self.receiver()
        self.assertFalse(self.path.exists())
        self.assertEqual(self.install(), self.receiver_id)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.install(), self.receiver_id)
        with self.assertRaises(WorkError):
            initialize_result_receiver(self.path, receiver_id=str(uuid4()))
        self.path.chmod(0o644)
        with self.assertRaises(WorkError) as caught:
            self.receiver()
        self.assertEqual(caught.exception.code, "schema_mismatch")
        self.path.chmod(0o600)
        self.assertIsNone(await self.receiver().find(self.intent()))

    async def test_core_receipt_replay_scope_target_conflict_and_fresh_reopen(self):
        self.install()
        client = self.receiver()
        intent = self.intent()
        first = await client.accept(intent)
        self.assertEqual(first, await client.accept(intent))
        self.assertEqual(first, await client.find(intent))
        self.assertEqual(first, await self.receiver().find(intent))
        for changed in (
            replace(intent, scope=WorkScope("other", "account")),
            replace(intent, recipient_id="other"),
            replace(intent, receiver_id=str(uuid4())),
        ):
            with self.assertRaises(WorkError) as caught:
                await client.find(changed)
            self.assertEqual(caught.exception.code, "unauthorized")
        other = self.intent(b"changed")
        changed = replace(other, delivery_id=intent.delivery_id)
        with self.assertRaises(WorkError) as caught:
            await client.accept(changed)
        self.assertEqual(caught.exception.code, "identity_conflict")
        self.assertEqual(first, await client.find(intent))
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(
                connection.execute("SELECT count(*) FROM result_receipts").fetchone()[0], 1
            )

    async def test_capacity_preserves_core_replay_and_reads(self):
        self.install(1)
        client = self.receiver()
        intent = self.intent()
        receipt = await client.accept(intent)
        with self.assertRaises(WorkError) as caught:
            await client.accept(self.intent())
        self.assertEqual(caught.exception.code, "capacity")
        self.assertEqual(await client.accept(intent), receipt)
        self.assertEqual(await client.find(intent), receipt)

    async def test_before_commit_rolls_back_after_commit_unknown_reconciles_original(self):
        self.install()

        def before(stage):
            if stage == "receiver.before_commit":
                raise OSError("PRIVATE_BEFORE")

        original = self.intent()
        with self.assertRaises(WorkError) as caught:
            await self.receiver(harness_failpoint=before).accept(original)
        self.assertEqual(caught.exception.code, "storage_unavailable")
        self.assertIsNone(await self.receiver().find(original))

        def after(stage):
            if stage == "receiver.after_commit":
                raise OSError("PRIVATE_AFTER")

        with self.assertRaises(WorkError) as caught:
            await self.receiver(harness_failpoint=after).accept(original)
        self.assertEqual(caught.exception.code, "acknowledgement_unknown")
        self.assertNotIn("PRIVATE", str(caught.exception))
        found = await self.receiver().find(original)
        self.assertIsNotNone(found)
        self.assertEqual(found, await self.receiver().accept(original))

    async def test_cancelled_waiters_retain_four_actual_threads_and_nested_snapshot(self):
        self.install()
        reached = threading.Event()
        release = threading.Event()

        def held(stage):
            if stage == "receiver.before_commit":
                reached.set()
                if not release.wait(2):
                    raise AssertionError("Owned release missing")

        client = self.receiver(harness_failpoint=held)
        intent = self.intent()
        expected = replace(intent, scope=WorkScope("tenant", "account"))
        tasks = []
        try:
            tasks.append(asyncio.create_task(client.accept(intent)))
            self.assertTrue(await asyncio.to_thread(reached.wait, 1))
            object.__setattr__(intent.scope, "tenant_id", "changed")
            object.__setattr__(intent, "body", b"PRIVATE_CALLER_MUTATION")
            for _ in range(3):
                tasks.append(asyncio.create_task(client.accept(expected)))
            for _ in range(100):
                if client.pending_count == 4:
                    break
                await asyncio.sleep(0.001)
            self.assertEqual(client.pending_count, 4)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.assertEqual(client.pending_count, 4)
            with self.assertRaises(WorkError) as caught:
                await client.find(expected)
            self.assertEqual(caught.exception.code, "capacity")
            self.assertEqual(client.pending_count, 4)
        finally:
            release.set()
            await asyncio.gather(*tasks, return_exceptions=True)
            for _ in range(200):
                if client.pending_count == 0:
                    break
                await asyncio.sleep(0.005)
        self.assertEqual(client.pending_count, 0)
        # The application binding was copied independently of the caller's scope object.
        fresh = open_result_receiver(
            self.path,
            receiver_id=self.receiver_id,
            bindings=(ReceiverBinding(WorkScope("tenant", "account"), "conversation"),),
        )
        self.clients.append(fresh)
        self.assertIsNotNone(await fresh.find(expected))
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(
                connection.execute("SELECT count(*) FROM result_receipts").fetchone()[0], 1
            )

    async def test_telemetry_failure_cannot_change_committed_truth(self):
        self.install()
        client = self.receiver()
        intent = self.intent()

        class Throw(logging.Handler):
            def emit(self, record):
                raise RuntimeError("PRIVATE_LOGGER")

        logger = logging.getLogger("continuity_lab.receiver_api")
        handler = Throw()
        level = logger.level
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        try:
            first = await client.accept(intent)
            self.assertEqual(await client.find(intent), first)
            self.assertEqual(await client.accept(intent), first)
            self.assertGreaterEqual(client.metrics()["telemetry_failures"], 3)
        finally:
            logger.removeHandler(handler)
            logger.setLevel(level)

    async def test_drift_and_invalid_bounded_configuration_fail_closed(self):
        self.install()
        with sqlite3.connect(self.path) as connection:
            connection.execute("CREATE TABLE unexpected(value TEXT)")
        with self.assertRaises(WorkError) as caught:
            self.receiver()
        self.assertEqual(caught.exception.code, "schema_mismatch")
        with sqlite3.connect(self.path) as connection:
            connection.execute("DROP TABLE unexpected")
        for bindings in ((), tuple([self.binding] * 65), (self.binding, self.binding)):
            with self.assertRaises(WorkError):
                open_result_receiver(self.path, receiver_id=self.receiver_id, bindings=bindings)
        self.assertIsNone(await self.receiver().find(self.intent()))


class DeliveryValues(unittest.TestCase):
    def test_values_reject_bad_receipt_body_or_inconsistent_observation_and_remain_safe(self):
        scope = WorkScope("tenant", "account")
        body = b"PRIVATE_BODY"
        intent = DeliveryIntent(
            str(uuid4()),
            scope,
            str(uuid4()),
            str(uuid4()),
            hashlib.sha256(body).hexdigest(),
            str(uuid4()),
            "recipient",
            body,
            2000000000000,
        )
        self.assertNotIn("PRIVATE_BODY", repr(intent))
        for changes in (
            {"body": b""},
            {"body": b"x" * 8193},
            {"result_sha256": "0" * 64},
            {"prepared_at_ms": True},
        ):
            with self.assertRaises(WorkError):
                replace(intent, **changes)
        with self.assertRaises(WorkError):
            DeliveryStart(intent, 1)
        with self.assertRaises(WorkError):
            DeliverySnapshot(None, True, None)
        receipt = DeliveryReceipt(
            intent.delivery_id,
            str(uuid4()),
            intent.receiver_id,
            intent.recipient_id,
            intent.result_sha256,
            2000000000001,
        )
        self.assertEqual(DeliverySnapshot(intent, True, receipt).receipt, receipt)
        with self.assertRaises(WorkError):
            DeliverySnapshot(intent, False, receipt)
