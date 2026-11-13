"""Actual database-clock leases, independent invocations and retained epochs."""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from psycopg import sql

from continuity_lab.execution_cli import _SafeFormatter
from continuity_lab.execution_models import (
    ExecutionCapacityExceeded,
    ExecutionNotFound,
)
from continuity_lab.lease_models import (
    MAX_EPOCH,
    CoordinationPolicy,
    LeaseBusy,
    LeaseLost,
    LeaseRequired,
)
from continuity_lab.models import BookingChange
from continuity_lab.postgres_leases import PostgresLeases, require_worker_lease
from continuity_lab.postgres_migrations import (
    activate_import,
    install_schema,
    stage_import,
    upgrade_v2,
    upgrade_v3,
    upgrade_v4,
)
from continuity_lab.postgres_settings import PostgresSettings
from continuity_lab.postgres_store import PostgresExecutionStore
from continuity_lab.postgres_unit_of_work import protected_transaction
from continuity_lab.transfer import make_snapshot
from harness.process_control import FileBarrier, OwnedProcess

ROOT = Path(__file__).resolve().parents[2]
ACTOR_SCOPE = "scope-a"
CHILD = r"""
import json,sys
from pathlib import Path
from continuity_lab.lease_models import LeaseGrant,LeaseBusy,LeaseLost
from continuity_lab.postgres_leases import PostgresLeases,require_worker_lease
from continuity_lab.postgres_settings import PostgresSettings
from continuity_lab.postgres_store import PostgresExecutionStore
from continuity_lab.postgres_unit_of_work import protected_transaction
from harness.process_control import FileBarrier
mode,directory,payload=sys.argv[1:]
data=json.loads(payload)
store=PostgresExecutionStore(PostgresSettings.from_env())
leases=PostgresLeases(store)
FileBarrier(Path(directory),'lease_boundary').arrive_and_wait(timeout=20)
try:
 if mode=='acquire':
  grant=leases.acquire(**data)
  print(json.dumps({'state':'acquired','epoch':grant.epoch,'owner_id':grant.owner_id,'expires_at':grant.expires_at}),flush=True)
 else:
  grant=LeaseGrant(**data)
  with protected_transaction(store) as connection:
   require_worker_lease(connection,store,grant,scope_id=grant.scope_id,task_id=grant.task_id)
  print(json.dumps({'state':'guarded'}),flush=True)
except LeaseBusy:
 print(json.dumps({'state':'busy'}),flush=True)
except LeaseLost:
 print(json.dumps({'state':'lost'}),flush=True)
"""


class PostgresLeaseCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("P1_RUN_POSTGRES_TESTS") != "1":
            raise RuntimeError("Real lease tests require explicit local PostgreSQL setup")
        cls.runtime_base = PostgresSettings.from_env()
        cls.owner_base = PostgresSettings.from_env("P1_MIGRATION_")

    def setUp(self):
        self.schema = "p1_leases_" + uuid4().hex
        self.runtime = replace(self.runtime_base, schema=self.schema)
        self.owner = replace(self.owner_base, schema=self.schema)
        self.addCleanup(self.drop_schema)
        install_schema(self.owner)
        snapshot = make_snapshot([], [], [], migration_id=str(uuid4()))
        stage_import(self.owner, snapshot)
        activate_import(self.owner, snapshot.migration_id, snapshot.source_digest)
        upgrade_v2(self.owner)
        upgrade_v3(self.owner)
        upgrade_v4(self.owner, policy=CoordinationPolicy(10, 2, 100, 2))
        self.store = PostgresExecutionStore(self.runtime)
        self.leases = PostgresLeases(self.store)
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.directory = Path(self.folder.name).resolve()
        self.sequence = 0

    def drop_schema(self):
        if not self.schema.startswith("p1_leases_") or len(self.schema) != 42:
            raise AssertionError("Only this run's owned schema may be removed")
        with closing(self.owner.connect(application_name="continuity-test")) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(self.schema))
            )

    def submit(self, scope=ACTOR_SCOPE):
        self.sequence += 1
        return self.store.submit(
            scope_id=scope,
            idempotency_key="lease-" + str(self.sequence),
            request=BookingChange("DEMO-BK-001", date(2030, 12, 10), True),
        ).execution

    def acquire(self, record, owner=None):
        return self.leases.acquire(
            scope_id=record.scope_id,
            task_id=record.task_id,
            owner_id=str(uuid4()) if owner is None else owner,
        )

    def expire(self, grant):
        """Observe real server expiry, never infer arrival from an arbitrary sleep."""
        deadline = time.monotonic() + 5
        with closing(self.owner.connect(application_name="continuity-test")) as connection:
            while time.monotonic() < deadline:
                row = connection.execute(
                    "SELECT clock_timestamp()>=%s::timestamptz AS expired", (grant.expires_at,)
                ).fetchone()
                if row["expired"]:
                    return
                connection.execute("SELECT pg_sleep(0.025)")
        self.fail("Database lease did not expire within its explicit bound")

    def environment(self):
        env = {key: value for key, value in os.environ.items() if not key.startswith(("P1_", "PG"))}
        env.update(
            {
                "P1_POSTGRES_HOST": self.runtime.host,
                "P1_POSTGRES_PORT": str(self.runtime.port),
                "P1_POSTGRES_DB": self.runtime.dbname,
                "P1_POSTGRES_USER": self.runtime.user,
                "P1_POSTGRES_PASSWORD": self.runtime.password,
                "P1_POSTGRES_SCHEMA": self.schema,
                "PYTHONPATH": str(ROOT),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        return env

    def child(self, mode, label, payload):
        directory = self.directory / label
        directory.mkdir(mode=0o700)
        barrier = FileBarrier(directory, "lease_boundary")
        process = OwnedProcess(
            [sys.executable, "-c", CHILD, mode, str(directory), json.dumps(payload)],
            cwd=ROOT,
            env=self.environment(),
            output_directory=self.directory / (label + "-output"),
        )
        self.addCleanup(process.close)
        process.wait_for_barrier(barrier, timeout=10)
        return process, barrier

    def child_result(self, child):
        result = child.wait(timeout=15)
        self.assertEqual(
            result.returncode,
            0,
            child.output_tail("stderr", redact_values=(self.runtime.password,)),
        )
        return json.loads(child.output_tail("stdout", redact_values=(self.runtime.password,)))

    def test_acquire_replay_renew_and_release_retain_epoch(self):
        record = self.submit()
        grant = self.acquire(record)
        self.assertEqual(grant.epoch, 1)
        same = self.acquire(record, grant.owner_id)
        self.assertEqual(same, grant)
        renewed = self.leases.renew(grant)
        self.assertEqual((renewed.owner_id, renewed.epoch), (grant.owner_id, grant.epoch))
        self.assertGreaterEqual(
            datetime.fromisoformat(renewed.expires_at), datetime.fromisoformat(grant.expires_at)
        )
        # An observation's original expiry is not a separate fencing token.
        self.leases.release(grant)
        observed = self.leases.get(scope_id=record.scope_id, task_id=record.task_id)
        self.assertIsNone(observed.owner_id)
        self.assertIsNone(observed.expires_at)
        self.assertEqual(observed.epoch, 1)
        successor = self.acquire(record)
        self.assertEqual(successor.epoch, 2)
        with self.assertRaises(LeaseLost):
            self.leases.renew(grant)
        with self.assertRaises(LeaseLost):
            self.leases.release(grant)
        self.leases.release(successor)

    def test_actual_server_expiry_allows_takeover_and_rejects_old_writes(self):
        record = self.submit()
        grant = self.acquire(record)
        with self.assertRaises(LeaseBusy):
            self.acquire(record)
        self.expire(grant)
        # An invented future observation cannot revive expired stored authority.
        future = replace(grant, expires_at="2099-01-01T00:00:00+00:00")
        for value in (grant, future):
            with self.assertRaises(LeaseLost):
                self.leases.renew(value)
            with self.assertRaises(LeaseLost):
                self.leases.release(value)
        successor = self.acquire(record)
        self.assertEqual(successor.epoch, 2)
        with protected_transaction(self.store) as connection, self.assertRaises(LeaseLost):
            require_worker_lease(
                connection, self.store, grant, scope_id=record.scope_id, task_id=record.task_id
            )
        with protected_transaction(self.store) as connection:
            require_worker_lease(
                connection, self.store, successor, scope_id=record.scope_id, task_id=record.task_id
            )
        self.leases.release(successor)

    def test_worker_wall_clock_cannot_extend_or_shorten_server_lease(self):
        record = self.submit()
        for skew in (datetime(2000, 1, 1, tzinfo=UTC), datetime(2099, 1, 1, tzinfo=UTC)):
            leases = PostgresLeases(
                PostgresExecutionStore(self.runtime, clock=lambda skew=skew: skew)
            )
            with closing(self.owner.connect(application_name="continuity-test")) as connection:
                before = connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
            grant = leases.acquire(
                scope_id=record.scope_id, task_id=record.task_id, owner_id=str(uuid4())
            )
            with closing(self.owner.connect(application_name="continuity-test")) as connection:
                after = connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
            due = datetime.fromisoformat(grant.expires_at)
            self.assertGreaterEqual(due, before + timedelta(seconds=2))
            self.assertLessEqual(due, after + timedelta(seconds=2))
            leases.release(grant)

    def test_active_capacity_is_global_and_replay_reads_remain_available(self):
        first, second, third = self.submit(), self.submit(), self.submit("scope-b")
        a, b = self.acquire(first), self.acquire(second)
        with self.assertRaises(ExecutionCapacityExceeded):
            self.acquire(third)
        self.assertEqual(self.acquire(first, a.owner_id), a)
        self.assertEqual(self.store.get(scope_id=third.scope_id, task_id=third.task_id), third)
        self.leases.release(a)
        c = self.acquire(third)
        self.assertEqual(c.epoch, 1)
        self.leases.release(b)
        self.leases.release(c)

    def test_scoped_lookup_precedes_coordination_observation(self):
        record = self.submit()
        grant = self.acquire(record)
        for method in (self.leases.get, self.leases.acquire):
            args = {"scope_id": "foreign-scope", "task_id": record.task_id}
            if method == self.leases.acquire:
                args["owner_id"] = str(uuid4())
            with self.assertRaises(ExecutionNotFound):
                method(**args)
        with protected_transaction(self.store) as connection, self.assertRaises(ExecutionNotFound):
            require_worker_lease(
                connection, self.store, None, scope_id="foreign-scope", task_id=record.task_id
            )
        other = self.submit()
        with protected_transaction(self.store) as connection, self.assertRaises(LeaseLost):
            require_worker_lease(
                connection, self.store, grant, scope_id=other.scope_id, task_id=other.task_id
            )
        self.leases.release(grant)

    def test_missing_grant_is_rejected_but_authorized_reads_do_not_need_lease(self):
        record = self.submit()
        self.assertIsNone(self.leases.get(scope_id=record.scope_id, task_id=record.task_id))
        with protected_transaction(self.store) as connection, self.assertRaises(LeaseRequired):
            require_worker_lease(
                connection, self.store, None, scope_id=record.scope_id, task_id=record.task_id
            )
        self.assertEqual(self.store.get(scope_id=record.scope_id, task_id=record.task_id), record)
        grant = self.acquire(record)
        with protected_transaction(self.store) as connection:
            require_worker_lease(
                connection, self.store, grant, scope_id=record.scope_id, task_id=record.task_id
            )
        self.leases.release(grant)

    def test_two_independent_processes_cannot_acquire_same_unexpired_workflow(self):
        record = self.submit()
        args = {"scope_id": record.scope_id, "task_id": record.task_id}
        a, ab = self.child("acquire", "first", args | {"owner_id": str(uuid4())})
        b, bb = self.child("acquire", "second", args | {"owner_id": str(uuid4())})
        a.release_barrier(ab)
        b.release_barrier(bb)
        observed = [self.child_result(a), self.child_result(b)]
        self.assertEqual(sorted(row["state"] for row in observed), ["acquired", "busy"])
        self.assertEqual(self.leases.get(scope_id=record.scope_id, task_id=record.task_id).epoch, 1)

    def test_paused_independent_process_loses_local_write_authority_after_takeover(self):
        record = self.submit()
        old = self.acquire(record)
        from dataclasses import asdict

        child, barrier = self.child("guard", "old-worker", asdict(old))
        self.expire(old)
        current = self.acquire(record)
        self.assertEqual(current.epoch, 2)
        child.release_barrier(barrier)
        self.assertEqual(self.child_result(child), {"state": "lost"})
        with protected_transaction(self.store) as connection:
            require_worker_lease(
                connection, self.store, current, scope_id=record.scope_id, task_id=record.task_id
            )
        self.leases.release(current)

    def test_acquisition_rollback_and_lost_ack_preserve_one_original_epoch(self):
        record = self.submit()
        owner = str(uuid4())

        def fail(point):
            if point == "leases.before_acquire_commit":
                raise RuntimeError("injected")

        with self.assertRaises(RuntimeError):
            PostgresLeases(self.store, failpoint=fail).acquire(
                scope_id=record.scope_id, task_id=record.task_id, owner_id=owner
            )
        self.assertIsNone(self.leases.get(scope_id=record.scope_id, task_id=record.task_id))

        def lost(point):
            if point == "leases.after_acquire_commit":
                raise RuntimeError("injected")

        with self.assertRaises(RuntimeError):
            PostgresLeases(self.store, failpoint=lost).acquire(
                scope_id=record.scope_id, task_id=record.task_id, owner_id=owner
            )
        known = self.leases.get(scope_id=record.scope_id, task_id=record.task_id)
        recovered = self.acquire(record, owner)
        self.assertEqual(known.grant(), recovered)
        self.assertEqual(recovered.epoch, 1)
        self.leases.release(recovered)

    def test_renew_and_release_rollback_and_ack_loss_do_not_reset_epoch(self):
        record = self.submit()
        grant = self.acquire(record)
        for operation in ("renew", "release"):

            def fail(point, operation=operation):
                if point == "leases.before_" + operation + "_commit":
                    raise RuntimeError("injected")

            with self.assertRaises(RuntimeError):
                getattr(PostgresLeases(self.store, failpoint=fail), operation)(grant)
            self.assertEqual(
                self.leases.get(scope_id=record.scope_id, task_id=record.task_id).grant(), grant
            )

        def lost(point):
            if point == "leases.after_renew_commit":
                raise RuntimeError("injected")

        with self.assertRaises(RuntimeError):
            PostgresLeases(self.store, failpoint=lost).renew(grant)
        known = self.leases.get(scope_id=record.scope_id, task_id=record.task_id)
        self.assertGreaterEqual(
            datetime.fromisoformat(known.expires_at), datetime.fromisoformat(grant.expires_at)
        )

        def release_lost(point):
            if point == "leases.after_release_commit":
                raise RuntimeError("injected")

        with self.assertRaises(RuntimeError):
            PostgresLeases(self.store, failpoint=release_lost).release(grant)
        with self.assertRaises(LeaseLost):
            self.leases.release(grant)
        self.assertEqual(self.acquire(record).epoch, 2)

    def test_epoch_capacity_retains_read_and_same_owner_replay(self):
        record = self.submit()
        grant = self.acquire(record)
        with closing(self.owner.connect(application_name="continuity-test")) as connection:
            connection.execute(
                sql.SQL("UPDATE {} SET epoch=%s WHERE task_id=%s").format(
                    sql.Identifier(self.schema, "execution_leases")
                ),
                (MAX_EPOCH, record.task_id),
            )
        current = self.acquire(record, grant.owner_id)
        self.assertEqual(current.epoch, MAX_EPOCH)
        self.leases.release(current)
        with self.assertRaises(ExecutionCapacityExceeded):
            self.acquire(record)
        self.assertEqual(
            self.leases.get(scope_id=record.scope_id, task_id=record.task_id).epoch, MAX_EPOCH
        )
        self.assertEqual(self.store.get(scope_id=record.scope_id, task_id=record.task_id), record)

    def test_real_lease_logs_have_fixed_fields_and_logger_failure_cannot_change_authority(self):
        record = self.submit()
        with self.assertLogs("continuity_lab.postgres_leases", level="INFO") as logs:
            grant = self.acquire(record)
            renewed = self.leases.renew(grant)
            self.leases.release(renewed)
        self.assertEqual(
            [row.event for row in logs.records],
            ["execution_lease_acquired", "execution_lease_renewed", "execution_lease_released"],
        )
        rendered = "".join(_SafeFormatter().format(row) for row in logs.records)
        for private in (record.task_id, record.scope_id, grant.owner_id, self.runtime.password):
            self.assertNotIn(private, rendered)

        class Broken(logging.Handler):
            def emit(self, record):
                raise RuntimeError("SECRET_SENTINEL")

        logger = logging.getLogger("continuity_lab.postgres_leases")
        handler = Broken()
        logger.addHandler(handler)
        prior = logger.level
        logger.setLevel(logging.INFO)
        try:
            current = self.acquire(record)
            self.leases.release(current)
        finally:
            logger.removeHandler(handler)
            logger.setLevel(prior)
        self.assertIsNone(
            self.leases.get(scope_id=record.scope_id, task_id=record.task_id).owner_id
        )

    def test_guard_samples_database_time_after_waiting_for_admission_lock(self):
        from dataclasses import asdict

        from continuity_lab.postgres_settings import advisory_keys

        record = self.submit()
        grant = self.acquire(record)
        child, barrier = self.child("guard", "blocked-worker", asdict(grant))
        keys = advisory_keys(self.schema, "admission")
        with protected_transaction(self.store) as holding:
            # Keep the real lock wait below the unchanged one-second lock budget
            # while still crossing server expiry after the transaction starts.
            near_deadline = time.monotonic() + 4
            while time.monotonic() < near_deadline:
                near = holding.execute(
                    "SELECT clock_timestamp()>=(%s::timestamptz - INTERVAL '0.75 seconds') AS near",
                    (grant.expires_at,),
                ).fetchone()
                if near["near"]:
                    break
                holding.execute("SELECT pg_sleep(0.025)")
            else:
                self.fail("Server clock never reached the bounded expiry window")
            child.release_barrier(barrier)
            deadline = time.monotonic() + 3
            blocked = False
            while time.monotonic() < deadline:
                row = holding.execute(
                    "SELECT EXISTS(SELECT 1 FROM pg_locks WHERE locktype='advisory' AND classid=%s::oid AND objid=%s::oid AND objsubid=2 AND NOT granted) AS blocked",
                    (keys[0] & 0xFFFFFFFF, keys[1] & 0xFFFFFFFF),
                ).fetchone()
                if row["blocked"]:
                    blocked = True
                    break
                holding.execute("SELECT pg_sleep(0.025)")
            self.assertTrue(blocked, "Child never actually waited for this schema's admission lock")
            still_live = holding.execute(
                "SELECT clock_timestamp()<%s::timestamptz AS live", (grant.expires_at,)
            ).fetchone()
            self.assertTrue(
                still_live["live"], "Child did not start waiting before real server expiry"
            )
            # Observe expiry on the server while the old invocation's transaction
            # is already waiting. A transaction-start timestamp would be stale.
            self.expire(grant)
        self.assertEqual(self.child_result(child), {"state": "lost"})
        successor = self.acquire(record)
        self.assertEqual(successor.epoch, 2)
        self.leases.release(successor)

    def test_explicit_grant_cannot_silently_downgrade_to_legacy_v3(self):
        from continuity_lab.execution_models import UnsupportedOperation
        from continuity_lab.lease_models import LeaseGrant

        schema = "p1_lease_legacy_" + uuid4().hex
        owner = replace(self.owner, schema=schema)
        runtime = replace(self.runtime, schema=schema)
        try:
            install_schema(owner)
            snapshot = make_snapshot([], [], [], migration_id=str(uuid4()))
            stage_import(owner, snapshot)
            activate_import(owner, snapshot.migration_id, snapshot.source_digest)
            upgrade_v2(owner)
            upgrade_v3(owner)
            store = PostgresExecutionStore(runtime)
            record = store.submit(
                scope_id=ACTOR_SCOPE,
                idempotency_key="legacy",
                request=BookingChange("DEMO-BK-001", date(2030, 12, 10), True),
            ).execution
            with protected_transaction(store) as connection:
                require_worker_lease(
                    connection, store, None, scope_id=record.scope_id, task_id=record.task_id
                )
            grant = LeaseGrant(
                record.scope_id, record.task_id, str(uuid4()), 1, "2099-01-01T00:00:00+00:00"
            )
            with (
                protected_transaction(store) as connection,
                self.assertRaises(UnsupportedOperation),
            ):
                require_worker_lease(
                    connection, store, grant, scope_id=record.scope_id, task_id=record.task_id
                )
            with self.assertRaises(UnsupportedOperation):
                PostgresLeases(store).acquire(
                    scope_id=record.scope_id, task_id=record.task_id, owner_id=grant.owner_id
                )
            self.assertEqual(store.get(scope_id=record.scope_id, task_id=record.task_id), record)
        finally:
            if not schema.startswith("p1_lease_legacy_") or len(schema) != 48:
                raise AssertionError("Only this isolated legacy test schema may be removed")
            with closing(owner.connect(application_name="continuity-test")) as connection:
                connection.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
                )
