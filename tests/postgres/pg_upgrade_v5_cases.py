"""Explicit PostgreSQL v5 retry-pacing gate; missing setup is a failure, never a skip."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4

from psycopg import sql

from continuity_lab.authorization import AuthenticatedActor
from continuity_lab.case_models import Confirmation, QuoteSnapshot
from continuity_lab.effect_models import EffectFailure, EffectState
from continuity_lab.lease_models import WorkKind
from continuity_lab.managed_inquiry_worker import ManagedInquiryWorker
from continuity_lab.migrations import MigrationError, SchemaVersionError
from continuity_lab.models import BookingChange
from continuity_lab.mutation_supplier import (
    MutationSupplier,
    MutationUnavailable,
    initialize_mutation_supplier,
)
from continuity_lab.mutation_worker import MutationWorker
from continuity_lab.postgres_case import PostgresCaseAuthority
from continuity_lab.postgres_effects import PostgresEffects
from continuity_lab.postgres_lifecycle import PostgresLifecycle
from continuity_lab.postgres_migrations import (
    UpgradeReport,
    activate_import,
    install_schema,
    read_import_state,
    stage_import,
    upgrade_v2,
    upgrade_v3,
    upgrade_v4,
    upgrade_v5,
    validate_schema,
)
from continuity_lab.postgres_schema_v2 import COLUMNS as V2_COLUMNS
from continuity_lab.postgres_schema_v3 import COLUMNS as V3_COLUMNS
from continuity_lab.postgres_schema_v4 import COLUMNS as V4_COLUMNS
from continuity_lab.postgres_settings import PostgresSettings
from continuity_lab.postgres_store import PostgresExecutionStore
from continuity_lab.postgres_work import PostgresWorkQueue
from continuity_lab.retry_policy import RetryPolicy
from continuity_lab.transfer import make_snapshot

ROOT = Path(__file__).resolve().parents[2]
LEGACY = AuthenticatedActor("legacy-owner", "account-a")
PACED = AuthenticatedActor("paced-owner", "account-paced")
TABLES = ("tasks", "executions", "execution_attempts", *V2_COLUMNS, *V3_COLUMNS, *V4_COLUMNS)


class Unavailable(MutationSupplier):
    def lookup(self, intent):
        raise MutationUnavailable("SECRET_SENTINEL")


class PostgresUpgradeV5Cases(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if os.environ.get("P1_RUN_POSTGRES_TESTS") != "1":
            raise RuntimeError("Real PostgreSQL v5 upgrade tests require explicit local setup")
        cls.runtime_base = PostgresSettings.from_env()
        cls.owner_base = PostgresSettings.from_env("P1_MIGRATION_")

    def setUp(self) -> None:
        self.schema = "p1_upgrade_v5_" + uuid4().hex
        self.runtime = replace(self.runtime_base, schema=self.schema)
        self.owner = replace(self.owner_base, schema=self.schema)
        self.addCleanup(self.drop_schema)
        self.now = [datetime(2030, 12, 1, tzinfo=UTC)]
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        database = Path(folder.name).resolve() / "supplier.sqlite3"
        initialize_mutation_supplier(database, scope_id=LEGACY.scope_id)
        initialize_mutation_supplier(database, scope_id=PACED.scope_id)
        self.supplier = MutationSupplier(database, clock=self.clock)
        self.unavailable = Unavailable(database, clock=self.clock)
        snapshot = make_snapshot([], [], [], migration_id=str(uuid4()))
        install_schema(self.owner)
        stage_import(self.owner, snapshot)
        activate_import(self.owner, snapshot.migration_id, snapshot.source_digest)
        upgrade_v2(self.owner)
        upgrade_v3(self.owner)
        self.store = PostgresExecutionStore(self.runtime)
        self.cases = PostgresCaseAuthority(self.store, clock=self.clock)
        self.lifecycle = PostgresLifecycle(self.store, cases=self.cases, clock=self.clock)
        # A v3 dependency outage leaves a pending effect that v5 must keep due at once.
        legacy = self.prepare("legacy-unavailable", 10, LEGACY)
        effects = PostgresEffects(self.store, cases=self.cases, clock=self.clock)
        value = MutationWorker(effects, self.unavailable).run_one(
            scope_id=LEGACY.scope_id, task_id=legacy.task_id
        )
        self.assertEqual(value.state, EffectState.PENDING)
        # Leased v4+ workers own every later step; this intent waits for its first effect.
        self.paced = self.prepare("paced", 12, PACED)

    def clock(self) -> datetime:
        return self.now[0]

    def drop_schema(self) -> None:
        if not self.schema.startswith("p1_upgrade_v5_") or len(self.schema) != 46:
            raise AssertionError("Only this owned isolated schema may be removed")
        with closing(self.owner.connect(application_name="continuity-test")) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(self.schema))
            )

    def prepare(self, key: str, day: int, actor: AuthenticatedActor) -> Any:
        request = BookingChange("DEMO-BK-001", date(2030, 12, day), True)
        record = self.store.submit(
            scope_id=actor.scope_id, idempotency_key=key, request=request
        ).execution
        self.lifecycle.manage(
            scope_id=actor.scope_id,
            task_id=record.task_id,
            policy=RetryPolicy(),
            deadline=self.now[0] + timedelta(hours=1),
        )
        ManagedInquiryWorker(self.lifecycle, self.supplier.inquiry_view()).run_one(
            scope_id=actor.scope_id, task_id=record.task_id
        )
        case = self.cases.enroll(actor=actor, task_id=record.task_id)
        booking = self.supplier.booking(
            scope_id=actor.scope_id, booking_reference=request.booking_reference
        )
        quote = QuoteSnapshot(
            str(uuid4()),
            record.task_id,
            case.revision,
            request.booking_reference,
            request.new_check_in,
            2500,
            "USD",
            (self.now[0] + timedelta(minutes=10)).isoformat(),
            case_id=case.case_id,
            expected_supplier_revision=booking.revision,
            supplier_id=self.supplier.provider_id,
        )
        self.cases.publish_quote(actor=actor, quote=quote)
        self.cases.commit_intent(
            actor=actor, confirmation=Confirmation(quote, True), command_id="confirm-" + key
        )
        return record

    def preserved_rows(self) -> dict[str, list[dict[str, Any]]]:
        with closing(self.owner.connect(application_name="continuity-test")) as connection:
            return {
                name: sorted(
                    connection.execute(
                        sql.SQL("SELECT * FROM {}.{}").format(
                            sql.Identifier(self.schema), sql.Identifier(name)
                        )
                    ).fetchall(),
                    key=lambda row: json.dumps(row, sort_keys=True, default=str),
                )
                for name in TABLES
            }

    def effect_row(self, task_id: str) -> dict[str, Any]:
        with closing(self.runtime.connect()) as connection:
            row = connection.execute(
                sql.SQL("SELECT * FROM {} WHERE task_id=%s").format(
                    sql.Identifier(self.schema, "mutation_effects")
                ),
                (task_id,),
            ).fetchone()
        assert row is not None
        return row

    def validate(self, minimum: int) -> None:
        with closing(self.runtime.connect()) as connection:
            validate_schema(connection, self.schema, require_active=True, minimum_version=minimum)

    def run_claimed(self, queue: PostgresWorkQueue, supplier: MutationSupplier, task_id: str):
        claim = queue.claim_next(scope_id=PACED.scope_id, owner_id=str(uuid4()))
        assert claim is not None
        self.assertEqual((claim.kind, claim.grant.task_id), (WorkKind.MUTATION, task_id))
        try:
            effects = PostgresEffects(
                self.store, cases=self.cases, clock=self.clock, worker_lease=claim.grant
            )
            return MutationWorker(effects, supplier).run_one(
                scope_id=PACED.scope_id, task_id=task_id
            )
        finally:
            queue.release(claim.grant)

    def test_v3_cannot_skip_the_explicit_v4_upgrade(self):
        with self.assertRaises(SchemaVersionError):
            upgrade_v5(self.owner)
        self.assertEqual(read_import_state(self.owner).version, 3)

    def test_populated_v4_upgrade_preserves_rows_and_leaves_existing_effects_due(self):
        upgrade_v4(self.owner)
        before = self.preserved_rows()
        self.assertTrue(before["mutation_effects"])
        receipt = read_import_state(self.owner)
        self.assertEqual(upgrade_v5(self.owner), UpgradeReport(4, 5, True))
        after = self.preserved_rows()
        for row in after["mutation_effects"]:
            self.assertIsNone(row.pop("next_attempt_at"))
        self.assertEqual(after, before)
        state = read_import_state(self.owner)
        self.assertEqual(
            (state.version, state.migration_id, state.source_digest),
            (5, receipt.migration_id, receipt.source_digest),
        )
        self.validate(5)

    def test_replay_and_older_upgrades_never_downgrade_or_rewrite(self):
        upgrade_v4(self.owner)
        upgrade_v5(self.owner)
        before = self.preserved_rows()
        for upgrade in (upgrade_v5, upgrade_v4, upgrade_v3, upgrade_v2):
            self.assertEqual(upgrade(self.owner), UpgradeReport(5, 5, False))
        self.assertEqual(self.preserved_rows(), before)

    def test_runtime_cannot_run_schema_upgrade(self):
        upgrade_v4(self.owner)
        before = self.preserved_rows()
        with self.assertRaises(MigrationError):
            upgrade_v5(self.runtime)
        self.assertEqual(read_import_state(self.owner).version, 4)
        self.assertEqual(self.preserved_rows(), before)

    def test_precommit_failures_leave_exact_v4_then_retry_progresses(self):
        upgrade_v4(self.owner)
        before = self.preserved_rows()
        for point in ("postgres.upgrade_v5.after_ddl", "postgres.upgrade_v5.before_commit"):

            def fail(name: str, point: str = point) -> None:
                if name == point:
                    raise RuntimeError("stopped before commit")

            with self.assertRaises(RuntimeError):
                upgrade_v5(self.owner, failpoint=fail)
            self.assertEqual(read_import_state(self.owner).version, 4)
            self.assertEqual(self.preserved_rows(), before)
            self.validate(4)
        self.assertEqual(upgrade_v5(self.owner), UpgradeReport(4, 5, True))

    def test_pre_upgrade_backup_restores_an_exact_v4_that_upgrades_again(self):
        upgrade_v4(self.owner)
        before = self.preserved_rows()
        docker = shutil.which("docker")
        if docker is None:
            raise AssertionError("The backup round trip requires the local Docker CLI")
        spec = importlib.util.spec_from_file_location("stack", ROOT / "local-setup/stack.py")
        assert spec is not None and spec.loader is not None
        stack = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(stack)
        container = subprocess.run(
            [
                docker,
                "ps",
                "--filter",
                "label=com.docker.compose.project=" + stack.PROJECT,
                "--filter",
                "label=com.docker.compose.service=postgres",
                "--format",
                "{{.ID}}",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()
        self.assertRegex(container, r"^[0-9a-f]{12,64}$")
        backup = "/tmp/p1-upgrade-v5-" + uuid4().hex
        environment = {"PATH": os.environ.get("PATH", ""), "PGPASSWORD": self.owner.password}

        def inside(*command: str) -> None:
            subprocess.run(
                [docker, "exec", "-e", "PGPASSWORD", container, *command],
                check=True,
                capture_output=True,
                env=environment,
                timeout=120,
            )

        connection_flags = (
            "--host=127.0.0.1",
            "--username=" + self.owner.user,
            "--dbname=" + self.owner.dbname,
        )
        inside("mkdir", "-m", "700", backup)
        self.addCleanup(inside, "rm", "-rf", backup)
        inside(
            "pg_dump",
            *connection_flags,
            "--schema=" + self.schema,
            "--inserts",
            "--no-owner",
            "--file=" + backup + "/schema.sql",
        )
        self.assertEqual(upgrade_v5(self.owner), UpgradeReport(4, 5, True))
        with closing(self.owner.connect(application_name="continuity-test")) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema))
            )
        inside(
            "psql",
            "-X",
            *connection_flags,
            "--set=ON_ERROR_STOP=1",
            "--single-transaction",
            "--file=" + backup + "/schema.sql",
        )
        self.assertEqual(read_import_state(self.owner).version, 4)
        self.assertEqual(self.preserved_rows(), before)
        self.validate(4)
        self.assertEqual(upgrade_v5(self.owner), UpgradeReport(4, 5, True))
        self.validate(5)

    def test_v4_dependency_retry_stays_due_at_once(self):
        upgrade_v4(self.owner)
        record = self.paced
        queue = PostgresWorkQueue(self.store, clock=self.clock)
        value = self.run_claimed(queue, self.unavailable, record.task_id)
        self.assertEqual(value.state, EffectState.PENDING)
        self.assertNotIn("next_attempt_at", self.effect_row(record.task_id))
        claim = queue.claim_next(scope_id=PACED.scope_id, owner_id=str(uuid4()))
        assert claim is not None
        queue.release(claim.grant)
        self.assertEqual(claim.grant.task_id, record.task_id)

    def test_paced_dependency_retry_waits_for_its_persisted_due_time(self):
        upgrade_v4(self.owner)
        upgrade_v5(self.owner)
        record = self.paced
        queue = PostgresWorkQueue(self.store, clock=self.clock)
        value = self.run_claimed(queue, self.unavailable, record.task_id)
        self.assertEqual(
            (value.state, value.dispatch_count, value.error_code),
            (EffectState.PENDING, 0, EffectFailure.DEPENDENCY_UNAVAILABLE),
        )
        due = self.effect_row(record.task_id)["next_attempt_at"]
        self.assertEqual(due, self.now[0] + timedelta(seconds=1))
        self.assertIsNone(queue.claim_next(scope_id=PACED.scope_id, owner_id=str(uuid4())))
        self.now[0] = due
        value = self.run_claimed(queue, self.supplier, record.task_id)
        self.assertEqual((value.state, value.attempt_no), (EffectState.SUCCEEDED, 2))
        self.assertEqual(self.supplier.count_mutations(scope_id=PACED.scope_id), 1)

    def test_cancellation_is_not_held_behind_a_paced_retry(self):
        upgrade_v4(self.owner)
        upgrade_v5(self.owner)
        record = self.paced
        queue = PostgresWorkQueue(self.store, clock=self.clock)
        self.run_claimed(queue, self.unavailable, record.task_id)
        self.assertIsNone(queue.claim_next(scope_id=PACED.scope_id, owner_id=str(uuid4())))
        effects = PostgresEffects(self.store, cases=self.cases, clock=self.clock)
        effects.cancel(actor=PACED, task_id=record.task_id, command_id="cancel-paced")
        value = effects.get(scope_id=PACED.scope_id, task_id=record.task_id)
        assert value is not None
        self.assertEqual(value.state, EffectState.CANCELLED)
        claim = queue.claim_next(scope_id=PACED.scope_id, owner_id=str(uuid4()))
        assert claim is not None
        queue.release(claim.grant)
        self.assertEqual((claim.kind, claim.grant.task_id), (WorkKind.DELIVERY, record.task_id))
        self.assertEqual(self.supplier.count_calls(scope_id=PACED.scope_id), 0)

    def test_legacy_pending_effect_remains_due_after_upgrade(self):
        upgrade_v4(self.owner)
        upgrade_v5(self.owner)
        queue = PostgresWorkQueue(self.store, clock=self.clock)
        claim = queue.claim_next(scope_id=LEGACY.scope_id, owner_id=str(uuid4()))
        assert claim is not None
        queue.release(claim.grant)
        self.assertEqual(claim.kind, WorkKind.MUTATION)
        self.assertTrue(re.fullmatch(r"[0-9a-f-]{36}", claim.grant.task_id))


if __name__ == "__main__":
    unittest.main()
