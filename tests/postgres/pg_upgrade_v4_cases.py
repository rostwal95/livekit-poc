"""Explicit PostgreSQL v4 migration gate; missing setup is a failure, never a skip."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql

from continuity_lab.authorization import AuthenticatedActor
from continuity_lab.case_models import Confirmation, QuoteSnapshot
from continuity_lab.execution_models import InquiryResult, UnsupportedOperation
from continuity_lab.lease_models import CoordinationPolicy
from continuity_lab.migrations import MigrationError, SchemaVersionError
from continuity_lab.models import BookingChange, IdempotencyConflict
from continuity_lab.postgres_case import PostgresCaseAuthority
from continuity_lab.postgres_migrations import (
    activate_import,
    install_schema,
    read_import_state,
    stage_import,
    upgrade_v2,
    upgrade_v3,
    upgrade_v4,
    validate_schema,
    verify_import,
)
from continuity_lab.postgres_schema_v2 import COLUMNS as V2_COLUMNS
from continuity_lab.postgres_schema_v3 import COLUMNS as V3_COLUMNS
from continuity_lab.postgres_schema_v4 import DEFINITIONS, GRANTS, OPERATING_INDEXES
from continuity_lab.postgres_settings import PostgresSettings
from continuity_lab.postgres_store import PostgresExecutionStore
from continuity_lab.transfer import make_snapshot


class PostgresUpgradeV4Cases(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if os.environ.get("P1_RUN_POSTGRES_TESTS") != "1":
            raise RuntimeError("Real PostgreSQL v4 upgrade tests require explicit local setup")
        cls.runtime_base = PostgresSettings.from_env()
        cls.owner_base = PostgresSettings.from_env("P1_MIGRATION_")

    def setUp(self) -> None:
        self.schema = "p1_upgrade_v4_" + uuid4().hex
        self.runtime = replace(self.runtime_base, schema=self.schema)
        self.owner = replace(self.owner_base, schema=self.schema)
        self.addCleanup(self.drop_schema)
        self.snapshot = make_snapshot([], [], [], migration_id=str(uuid4()))
        self.actor = AuthenticatedActor("legacy-owner", "account-a")
        self.clock = [datetime(2030, 12, 1, tzinfo=UTC)]
        self.request = BookingChange("DEMO-BK-001", date(2030, 12, 10), True)
        self.install_v3()

    def install_v3(self) -> None:
        install_schema(self.owner)
        stage_import(self.owner, self.snapshot)
        activate_import(self.owner, self.snapshot.migration_id, self.snapshot.source_digest)
        upgrade_v2(self.owner)
        self.store = PostgresExecutionStore(self.runtime)
        self.record = self.store.submit(
            scope_id=self.actor.scope_id,
            idempotency_key="legacy-inquiry",
            request=self.request,
        ).execution
        self.cases = PostgresCaseAuthority(self.store, clock=lambda: self.clock[0])
        self.case = self.cases.enroll(actor=self.actor, task_id=self.record.task_id)
        self.quote = QuoteSnapshot(
            str(uuid4()),
            self.record.task_id,
            0,
            self.request.booking_reference,
            self.request.new_check_in,
            12500,
            "USD",
            (self.clock[0] + timedelta(hours=1)).isoformat(),
        )
        self.cases.publish_quote(actor=self.actor, quote=self.quote)
        self.intent = self.cases.commit_intent(
            actor=self.actor,
            confirmation=Confirmation(self.quote, True),
            command_id="legacy-confirm",
        )
        upgrade_v3(self.owner)

    def drop_schema(self) -> None:
        if not self.schema.startswith("p1_upgrade_v4_") or len(self.schema) != 46:
            raise AssertionError("Only this owned isolated schema may be removed")
        with self.owner.connect(application_name="continuity-test") as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(self.schema))
            )

    def preserved_rows(self) -> dict[str, list[dict]]:
        tables = ("tasks", "executions", "execution_attempts", *V2_COLUMNS, *V3_COLUMNS)
        with self.owner.connect(application_name="continuity-test") as connection:
            return {
                name: sorted(
                    connection.execute(
                        sql.SQL("SELECT * FROM {}.{}").format(
                            sql.Identifier(self.schema), sql.Identifier(name)
                        )
                    ).fetchall(),
                    key=lambda row: json.dumps(row, sort_keys=True),
                )
                for name in tables
            }

    def table_names(self) -> set[str]:
        with self.owner.connect(application_name="continuity-test") as connection:
            return {
                row["tablename"]
                for row in connection.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname=%s",
                    (self.schema,),
                )
            }

    def test_populated_v3_upgrade_preserves_exact_prior_data_and_historical_receipt(
        self,
    ):
        before, receipt = self.preserved_rows(), read_import_state(self.owner)
        with (
            self.runtime.connect() as connection,
            self.assertRaises(SchemaVersionError),
        ):
            validate_schema(connection, self.schema, minimum_version=4)
        report = upgrade_v4(self.owner)
        self.assertEqual(
            (report.previous_version, report.current_version, report.changed),
            (3, 4, True),
        )
        self.assertEqual(self.preserved_rows(), before)
        after = read_import_state(self.owner)
        self.assertEqual(
            (after.state, after.migration_id, after.source_digest),
            (receipt.state, receipt.migration_id, receipt.source_digest),
        )
        self.assertEqual(after.version, 4)
        self.assertTrue(set(DEFINITIONS) <= self.table_names())
        with self.runtime.connect() as connection:
            validate_schema(connection, self.schema, minimum_version=4)

    def test_populated_effect_wait_cancellation_and_delivery_bytes_survive_upgrade(self):
        from tempfile import TemporaryDirectory

        from continuity_lab.completion_sink import CompletionSink, initialize_completion_sink
        from continuity_lab.effect_models import EffectState
        from continuity_lab.managed_inquiry_worker import ManagedInquiryWorker
        from continuity_lab.mutation_supplier import MutationSupplier, initialize_mutation_supplier
        from continuity_lab.mutation_worker import MutationWorker
        from continuity_lab.outbox_delivery import CompletionDeliveryWorker
        from continuity_lab.postgres_effects import PostgresEffects
        from continuity_lab.postgres_lifecycle import PostgresLifecycle
        from continuity_lab.retry_policy import RetryPolicy

        with TemporaryDirectory() as folder_name:
            folder = Path(folder_name).resolve()
            initialize_mutation_supplier(folder / "supplier.sqlite3", scope_id=self.actor.scope_id)
            initialize_completion_sink(folder / "sink.sqlite3")
            supplier = MutationSupplier(folder / "supplier.sqlite3", clock=lambda: self.clock[0])
            sink = CompletionSink(folder / "sink.sqlite3", clock=lambda: self.clock[0])
            lifecycle = PostgresLifecycle(self.store, cases=self.cases, clock=lambda: self.clock[0])
            effects = PostgresEffects(self.store, cases=self.cases, clock=lambda: self.clock[0])

            def prepare(key, day):
                request = BookingChange("DEMO-BK-001", date(2030, 12, day), True)
                record = self.store.submit(
                    scope_id=self.actor.scope_id, idempotency_key=key, request=request
                ).execution
                lifecycle.manage(
                    scope_id=self.actor.scope_id,
                    task_id=record.task_id,
                    policy=RetryPolicy(),
                    deadline=self.clock[0] + timedelta(hours=1),
                )
                ManagedInquiryWorker(lifecycle, supplier.inquiry_view()).run_one(
                    scope_id=self.actor.scope_id, task_id=record.task_id
                )
                case = self.cases.enroll(actor=self.actor, task_id=record.task_id)
                booking = supplier.booking(
                    scope_id=self.actor.scope_id, booking_reference=request.booking_reference
                )
                quote = QuoteSnapshot(
                    str(uuid4()),
                    record.task_id,
                    case.revision,
                    request.booking_reference,
                    request.new_check_in,
                    2500,
                    "USD",
                    (self.clock[0] + timedelta(minutes=10)).isoformat(),
                    case_id=case.case_id,
                    expected_supplier_revision=booking.revision,
                    supplier_id=supplier.provider_id,
                )
                self.cases.publish_quote(actor=self.actor, quote=quote)
                return record, quote

            completed, quote = prepare("complete-effect", 10)
            self.cases.commit_intent(
                actor=self.actor,
                confirmation=Confirmation(quote, True),
                command_id="complete-confirm",
            )
            result = MutationWorker(effects, supplier).run_one(
                scope_id=self.actor.scope_id, task_id=completed.task_id
            )
            self.assertEqual(result.state, EffectState.SUCCEEDED)
            CompletionDeliveryWorker(effects, sink).run_one(
                scope_id=self.actor.scope_id, task_id=completed.task_id
            )
            waiting, wait_quote = prepare("consume-wait", 11)
            lifecycle.arm_wait(
                actor=self.actor,
                task_id=waiting.task_id,
                wait_id=str(uuid4()),
                quote=wait_quote,
                deadline=self.clock[0] + timedelta(minutes=5),
            )
            lifecycle.signal(
                actor=self.actor, event_id=str(uuid4()), confirmation=Confirmation(wait_quote, True)
            )
            lifecycle.advance(actor=self.actor, task_id=waiting.task_id)
            cancelled, _ = prepare("cancel-case", 12)
            effects.cancel(
                actor=self.actor, task_id=cancelled.task_id, command_id="cancel-before-commit"
            )
            before = self.preserved_rows()
            self.assertTrue(all(before[name] for name in (*V2_COLUMNS, *V3_COLUMNS)))
            receipt = read_import_state(self.owner)
            upgrade_v4(self.owner)
            self.assertEqual(self.preserved_rows(), before)
            after = read_import_state(self.owner)
            self.assertEqual(
                (after.migration_id, after.source_digest, after.state),
                (receipt.migration_id, receipt.source_digest, receipt.state),
            )
            self.assertEqual(sink.count(), 1)
            self.assertEqual(supplier.count_mutations(scope_id=self.actor.scope_id), 1)

    def test_running_unmanaged_inquiry_refuses_upgrade_until_v3_reconciliation(self):
        started = self.store.start_attempt(
            scope_id=self.actor.scope_id,
            task_id=self.record.task_id,
            expected_version=self.record.version,
        )
        before = self.preserved_rows()
        with self.assertRaises(UnsupportedOperation):
            upgrade_v4(self.owner)
        self.assertEqual(read_import_state(self.owner).version, 3)
        self.assertEqual(self.preserved_rows(), before)
        self.assertFalse(set(DEFINITIONS) & self.table_names())
        finished = PostgresExecutionStore(self.runtime).finish_attempt(
            scope_id=self.actor.scope_id,
            task_id=self.record.task_id,
            attempt_id=started.attempt.attempt_id,
            expected_version=started.execution.version,
            result=InquiryResult(self.request.booking_reference, self.request.new_check_in, True),
        )
        settled = self.preserved_rows()
        self.assertTrue(upgrade_v4(self.owner).changed)
        self.assertEqual(self.preserved_rows(), settled)
        self.assertEqual(
            PostgresExecutionStore(self.runtime).get(
                scope_id=self.actor.scope_id, task_id=self.record.task_id
            ),
            finished,
        )

    def test_managed_running_inquiry_retains_recoverable_state_through_upgrade(self):
        from continuity_lab.postgres_lifecycle import PostgresLifecycle
        from continuity_lab.retry_policy import RetryPolicy

        record = self.store.submit(
            scope_id=self.actor.scope_id, idempotency_key="managed-running", request=self.request
        ).execution
        lifecycle = PostgresLifecycle(self.store, cases=self.cases, clock=lambda: self.clock[0])
        lifecycle.manage(
            scope_id=self.actor.scope_id,
            task_id=record.task_id,
            policy=RetryPolicy(),
            deadline=self.clock[0] + timedelta(hours=1),
        )
        with self.store.worker_slot():
            claim = lifecycle.claim_due(scope_id=self.actor.scope_id, task_id=record.task_id)
        self.assertIsNotNone(claim)
        before = self.preserved_rows()
        self.assertTrue(upgrade_v4(self.owner).changed)
        self.assertEqual(self.preserved_rows(), before)
        current = PostgresExecutionStore(self.runtime).get(
            scope_id=self.actor.scope_id, task_id=record.task_id
        )
        self.assertEqual(current.status, "running")
        self.assertEqual(current.effect_id, record.effect_id)

    def test_legacy_quote_and_intent_replay_remain_readable_without_mutation_backfill(
        self,
    ):
        before = self.preserved_rows()
        upgrade_v4(self.owner)
        self.clock[0] += timedelta(days=365)
        current = self.cases.get(actor=self.actor, task_id=self.record.task_id)
        self.assertEqual(current.case_id, self.case.case_id)
        self.assertEqual(current.quote.payload()["schema_version"], 1)
        self.assertEqual(current.intent, self.intent)
        self.assertEqual(
            self.cases.commit_intent(
                actor=self.actor,
                confirmation=Confirmation(self.quote, True),
                command_id="legacy-confirm",
            ),
            self.intent,
        )
        self.assertEqual(self.preserved_rows(), before)
        with self.owner.connect(application_name="continuity-test") as connection:
            self.assertEqual(
                connection.execute(
                    sql.SQL("SELECT COUNT(*) AS count FROM {}.mutation_effects").format(
                        sql.Identifier(self.schema)
                    )
                ).fetchone()["count"],
                0,
            )

    def test_upgrade_replay_install_and_older_upgrade_never_downgrade_or_rewrite(self):
        upgrade_v4(self.owner)
        before = self.preserved_rows()
        self.assertEqual(upgrade_v4(self.owner).current_version, 4)
        self.assertFalse(upgrade_v4(self.owner).changed)
        third = upgrade_v3(self.owner)
        self.assertEqual(
            (third.previous_version, third.current_version, third.changed), (4, 4, False)
        )
        old = upgrade_v2(self.owner)
        self.assertEqual((old.previous_version, old.current_version, old.changed), (4, 4, False))
        install_schema(self.owner)
        self.assertEqual(read_import_state(self.owner).version, 4)
        self.assertEqual(self.preserved_rows(), before)

    def test_staging_v1_and_v2_cannot_skip_the_explicit_v3_upgrade(self):
        self.drop_schema()
        install_schema(self.owner)
        with self.assertRaises(SchemaVersionError):
            upgrade_v4(self.owner)
        self.assertEqual(read_import_state(self.owner).state, "staging")
        stage_import(self.owner, self.snapshot)
        activate_import(self.owner, self.snapshot.migration_id, self.snapshot.source_digest)
        for version in (1, 2):
            with self.subTest(version=version), self.assertRaises(SchemaVersionError):
                upgrade_v4(self.owner)
            self.assertEqual(read_import_state(self.owner).version, version)
            self.assertFalse(set(DEFINITIONS) & self.table_names())
            if version == 1:
                upgrade_v2(self.owner)
        upgrade_v3(self.owner)
        self.assertTrue(upgrade_v4(self.owner).changed)

    def test_runtime_cannot_run_schema_upgrade(self):
        before = self.preserved_rows()
        with self.assertRaises(MigrationError):
            upgrade_v4(self.runtime)
        self.assertEqual(read_import_state(self.owner).version, 3)
        self.assertEqual(self.preserved_rows(), before)
        self.assertFalse(set(DEFINITIONS) & self.table_names())

    def test_precommit_failures_leave_exact_v3_then_valid_retry_progresses(self):
        before = self.preserved_rows()
        for barrier in (
            "postgres.upgrade_v4.after_ddl",
            "postgres.upgrade_v4.before_commit",
        ):

            def interrupt(point: str, expected: str = barrier) -> None:
                if point == expected:
                    raise RuntimeError("Controlled v4 migration interruption")

            with self.subTest(barrier=barrier), self.assertRaises(RuntimeError):
                upgrade_v4(self.owner, failpoint=interrupt)
            self.assertEqual(read_import_state(self.owner).version, 3)
            self.assertEqual(self.preserved_rows(), before)
            self.assertFalse(set(DEFINITIONS) & self.table_names())
        self.assertTrue(upgrade_v4(self.owner).changed)

    def test_lost_commit_acknowledgement_replays_complete_v4(self):
        before = self.preserved_rows()

        def interrupt(point: str) -> None:
            if point == "postgres.upgrade_v4.after_commit":
                raise RuntimeError("Controlled lost v4 acknowledgement")

        with self.assertRaises(RuntimeError):
            upgrade_v4(self.owner, failpoint=interrupt)
        self.assertEqual(read_import_state(self.owner).version, 4)
        self.assertFalse(upgrade_v4(self.owner).changed)
        self.assertEqual(self.preserved_rows(), before)

    def test_actual_child_exit_at_all_three_upgrade_checkpoints_is_atomic(self):
        package_root = (
            Path(importlib.import_module(upgrade_v4.__module__).__file__).resolve().parents[1]
        )
        code = """import os
from continuity_lab.postgres_migrations import upgrade_v4
from continuity_lab.postgres_settings import PostgresSettings
def interrupt(point):
    if point == os.environ['P1_UPGRADE_V4_BARRIER']:
        os._exit(77)
upgrade_v4(PostgresSettings.from_env('P1_MIGRATION_'),failpoint=interrupt)
raise SystemExit(78)
"""
        for barrier in (
            "postgres.upgrade_v4.after_ddl",
            "postgres.upgrade_v4.before_commit",
            "postgres.upgrade_v4.after_commit",
        ):
            if read_import_state(self.owner).version == 4:
                self.drop_schema()
                self.install_v3()
            before = self.preserved_rows()
            environment = {
                key: value
                for key, value in os.environ.items()
                if not key.startswith("P1_POSTGRES_")
            }
            environment.update(
                {
                    "P1_MIGRATION_SCHEMA": self.schema,
                    "P1_UPGRADE_V4_BARRIER": barrier,
                    "PYTHONPATH": str(package_root),
                }
            )
            result = subprocess.run(
                [sys.executable, "-c", code],
                env=environment,
                cwd="/private/tmp",
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            self.assertEqual(result.returncode, 77, result.stderr[-1200:])
            self.assertEqual(
                read_import_state(self.owner).version,
                4 if barrier.endswith("after_commit") else 3,
            )
            self.assertEqual(self.preserved_rows(), before)
            upgrade_v4(self.owner)
            self.assertEqual(read_import_state(self.owner).version, 4)

    def test_runtime_policy_is_readonly_and_all_new_tables_forbid_delete(
        self,
    ):
        upgrade_v4(self.owner)
        for table, grants in GRANTS.items():
            for privilege in ("DELETE", "TRUNCATE", "TRIGGER"):
                with self.runtime.connect() as connection:
                    row = connection.execute(
                        "SELECT has_table_privilege(current_user,%s,%s) AS allowed",
                        (self.schema + "." + table, privilege),
                    ).fetchone()
                    self.assertFalse(row["allowed"])
            if "UPDATE" not in grants:
                with (
                    self.runtime.connect() as connection,
                    self.assertRaises(psycopg.errors.InsufficientPrivilege),
                ):
                    connection.execute(
                        sql.SQL("UPDATE {}.{} SET singleton=singleton").format(
                            sql.Identifier(self.schema), sql.Identifier(table)
                        )
                    )
        with (
            self.runtime.connect() as connection,
            self.assertRaises(psycopg.errors.InsufficientPrivilege),
        ):
            connection.execute(
                sql.SQL("UPDATE {}.schema_metadata SET version=4").format(
                    sql.Identifier(self.schema)
                )
            )

    def test_completed_historical_receipt_does_not_allow_reimport_over_v4(self):
        upgrade_v4(self.owner)
        before = self.preserved_rows()
        with self.assertRaises(MigrationError):
            stage_import(self.owner, self.snapshot)
        with self.assertRaises(MigrationError):
            verify_import(self.owner, self.snapshot)
        activate_import(self.owner, self.snapshot.migration_id, self.snapshot.source_digest)
        self.assertEqual(self.preserved_rows(), before)
        self.assertEqual(read_import_state(self.owner).version, 4)

    def test_grant_drift_fails_and_replay_does_not_silently_repair_it(self):
        upgrade_v4(self.owner)
        with self.owner.connect(application_name="continuity-test") as connection:
            connection.execute(
                sql.SQL("GRANT UPDATE ON {}.execution_limits TO livekit_lab").format(
                    sql.Identifier(self.schema)
                )
            )
        with (
            self.runtime.connect() as connection,
            self.assertRaises(SchemaVersionError),
        ):
            validate_schema(connection, self.schema)
        with self.assertRaises(SchemaVersionError):
            upgrade_v4(self.owner)
        with self.owner.connect(application_name="continuity-test") as connection:
            self.assertTrue(
                connection.execute(
                    "SELECT has_table_privilege('livekit_lab',%s,'UPDATE') AS allowed",
                    (self.schema + ".execution_limits",),
                ).fetchone()["allowed"]
            )
            connection.execute(
                sql.SQL("REVOKE UPDATE ON {}.execution_limits FROM livekit_lab").format(
                    sql.Identifier(self.schema)
                )
            )
        self.assertFalse(upgrade_v4(self.owner).changed)

    def test_limits_are_persisted_private_and_explicit_replay_cannot_reconfigure(self):
        selected = CoordinationPolicy(
            maximum_pending=7, maximum_active=2, maximum_records=20, lease_seconds=3
        )
        upgrade_v4(self.owner, policy=selected)
        with self.runtime.connect() as connection:
            row = connection.execute(
                sql.SQL("SELECT * FROM {}.execution_limits").format(sql.Identifier(self.schema))
            ).fetchone()
            self.assertEqual(row, {"singleton": True, **selected.payload()})
        self.assertFalse(upgrade_v4(self.owner).changed)
        self.assertFalse(upgrade_v4(self.owner, policy=selected).changed)
        with self.assertRaises(IdempotencyConflict):
            upgrade_v4(self.owner, policy=CoordinationPolicy())
        with self.runtime.connect() as connection:
            self.assertEqual(
                connection.execute(
                    sql.SQL("SELECT * FROM {}.execution_limits").format(sql.Identifier(self.schema))
                ).fetchone(),
                row,
            )

    def test_missing_limit_row_fails_closed_without_automatic_repair(self):
        upgrade_v4(self.owner)
        with self.owner.connect(application_name="continuity-test") as connection:
            connection.execute(
                sql.SQL("DELETE FROM {}.execution_limits").format(sql.Identifier(self.schema))
            )
        with self.runtime.connect() as connection, self.assertRaises(SchemaVersionError):
            validate_schema(connection, self.schema)
        with self.assertRaises(SchemaVersionError):
            upgrade_v4(self.owner)
        with self.owner.connect(application_name="continuity-test") as connection:
            self.assertEqual(
                connection.execute(
                    sql.SQL("SELECT COUNT(*) AS n FROM {}.execution_limits").format(
                        sql.Identifier(self.schema)
                    )
                ).fetchone()["n"],
                0,
            )

    def test_policy_constraints_reject_invalid_values(self):
        upgrade_v4(self.owner)
        statements = (
            "maximum_pending=0",
            "maximum_pending=100001",
            "maximum_active=0",
            "maximum_active=65",
            "maximum_active=maximum_pending+1",
            "maximum_records=maximum_pending-1",
            "maximum_records=1000001",
            "lease_seconds=0",
            "lease_seconds=301",
        )
        for expression in statements:
            with (
                self.subTest(expression=expression),
                self.owner.connect(application_name="continuity-test") as connection,
                self.assertRaises(psycopg.errors.CheckViolation),
            ):
                connection.execute(
                    sql.SQL("UPDATE {}.execution_limits SET " + expression).format(
                        sql.Identifier(self.schema)
                    )
                )
        with (
            self.owner.connect(application_name="continuity-test") as connection,
            self.assertRaises(psycopg.errors.CheckViolation),
        ):
            connection.execute(
                sql.SQL("INSERT INTO {}.execution_limits VALUES(FALSE,1,1,1,1)").format(
                    sql.Identifier(self.schema)
                )
            )

    def test_leases_bind_scope_and_retain_finite_clock_epoch_evidence(self):
        upgrade_v4(self.owner)
        task = self.record.task_id
        now = datetime(2030, 12, 1, tzinfo=UTC)
        later = now + timedelta(seconds=30)
        base = (task, self.actor.scope_id, str(uuid4()), 1, later, now, now)
        invalid = (
            base[:1] + ("foreign-scope",) + base[2:],
            (*base[:3], 0, *base[4:]),
            (*base[:2], None, *base[3:]),
            (*base[:4], now, *base[5:]),
            (*base[:5], later, now),
            (*base[:5], "infinity", "infinity"),
        )
        for row in invalid:
            with (
                self.subTest(row_kind=tuple(type(x).__name__ for x in row)),
                self.runtime.connect() as connection,
                self.assertRaises(
                    (psycopg.errors.CheckViolation, psycopg.errors.ForeignKeyViolation)
                ),
            ):
                connection.execute(
                    sql.SQL("INSERT INTO {}.execution_leases VALUES(%s,%s,%s,%s,%s,%s,%s)").format(
                        sql.Identifier(self.schema)
                    ),
                    row,
                )
        with self.runtime.connect() as connection:
            connection.execute(
                sql.SQL("INSERT INTO {}.execution_leases VALUES(%s,%s,%s,%s,%s,%s,%s)").format(
                    sql.Identifier(self.schema)
                ),
                base,
            )
            connection.execute(
                sql.SQL(
                    "UPDATE {}.execution_leases SET owner_id=NULL,expires_at=NULL WHERE task_id=%s"
                ).format(sql.Identifier(self.schema)),
                (task,),
            )
            row = connection.execute(
                sql.SQL(
                    "SELECT epoch,owner_id,expires_at FROM {}.execution_leases WHERE task_id=%s"
                ).format(sql.Identifier(self.schema)),
                (task,),
            ).fetchone()
            self.assertEqual(row, {"epoch": 1, "owner_id": None, "expires_at": None})

    def test_operational_indexes_are_required_nonunique_and_order_sensitive(self):
        upgrade_v4(self.owner)
        for name, (table, columns) in OPERATING_INDEXES.items():
            with self.owner.connect(application_name="continuity-test") as connection:
                connection.execute(
                    sql.SQL("DROP INDEX {}.{}").format(
                        sql.Identifier(self.schema), sql.Identifier(name)
                    )
                )
            with (
                self.runtime.connect() as connection,
                self.assertRaises(SchemaVersionError),
            ):
                validate_schema(connection, self.schema)
            with self.owner.connect(application_name="continuity-test") as connection:
                connection.execute(
                    sql.SQL("CREATE UNIQUE INDEX {} ON {}.{} ({})").format(
                        sql.Identifier(name),
                        sql.Identifier(self.schema),
                        sql.Identifier(table),
                        sql.SQL(",").join(map(sql.Identifier, columns)),
                    )
                )
            with (
                self.runtime.connect() as connection,
                self.assertRaises(SchemaVersionError),
            ):
                validate_schema(connection, self.schema)
            with self.owner.connect(application_name="continuity-test") as connection:
                connection.execute(
                    sql.SQL("DROP INDEX {}.{}").format(
                        sql.Identifier(self.schema), sql.Identifier(name)
                    )
                )
                connection.execute(
                    sql.SQL("CREATE INDEX {} ON {}.{} ({})").format(
                        sql.Identifier(name),
                        sql.Identifier(self.schema),
                        sql.Identifier(table),
                        sql.SQL(",").join(map(sql.Identifier, columns)),
                    )
                )
        with self.runtime.connect() as connection:
            validate_schema(connection, self.schema, minimum_version=4)

    def test_new_table_default_column_and_check_drift_fail_closed(self):
        upgrade_v4(self.owner)
        with self.owner.connect(application_name="continuity-test") as connection:
            connection.execute(
                sql.SQL(
                    "ALTER TABLE {}.execution_limits ALTER COLUMN lease_seconds SET DEFAULT 30"
                ).format(sql.Identifier(self.schema))
            )
        with (
            self.runtime.connect() as connection,
            self.assertRaises(SchemaVersionError),
        ):
            validate_schema(connection, self.schema)
        with self.owner.connect(application_name="continuity-test") as connection:
            connection.execute(
                sql.SQL(
                    "ALTER TABLE {}.execution_limits ALTER COLUMN lease_seconds DROP DEFAULT"
                ).format(sql.Identifier(self.schema))
            )
            connection.execute(
                sql.SQL("ALTER TABLE {}.execution_leases DROP CONSTRAINT leases_owner_pair").format(
                    sql.Identifier(self.schema)
                )
            )
        with (
            self.runtime.connect() as connection,
            self.assertRaises(SchemaVersionError),
        ):
            validate_schema(connection, self.schema)
        with self.assertRaises(SchemaVersionError):
            upgrade_v4(self.owner)

    def test_lease_clock_type_drift_is_not_treated_as_server_time(self):
        upgrade_v4(self.owner)
        with self.owner.connect(application_name="continuity-test") as connection:
            connection.execute(
                sql.SQL(
                    "ALTER TABLE {}.execution_leases ALTER COLUMN expires_at TYPE TIMESTAMP WITHOUT TIME ZONE"
                ).format(sql.Identifier(self.schema))
            )
        with self.runtime.connect() as connection, self.assertRaises(SchemaVersionError):
            validate_schema(connection, self.schema)
        with self.assertRaises(SchemaVersionError):
            upgrade_v4(self.owner)

    def test_future_table_policy_drift_fails_without_repair(self):
        upgrade_v4(self.owner)
        with self.owner.connect(application_name="continuity-test") as connection:
            connection.execute(
                sql.SQL(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA {} GRANT INSERT ON TABLES TO livekit_lab"
                ).format(sql.Identifier(self.schema))
            )
        with self.runtime.connect() as connection, self.assertRaises(SchemaVersionError):
            validate_schema(connection, self.schema)
        with self.assertRaises(SchemaVersionError):
            upgrade_v4(self.owner)
        with self.owner.connect(application_name="continuity-test") as connection:
            connection.execute(
                sql.SQL(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA {} REVOKE INSERT ON TABLES FROM livekit_lab"
                ).format(sql.Identifier(self.schema))
            )
        with self.runtime.connect() as connection:
            validate_schema(connection, self.schema, minimum_version=4)

    def test_default_policy_is_visible_but_cannot_be_changed_by_runtime(self):
        upgrade_v4(self.owner)
        with self.runtime.connect() as connection:
            row = connection.execute(
                sql.SQL("SELECT * FROM {}.execution_limits").format(sql.Identifier(self.schema))
            ).fetchone()
            self.assertEqual(row, {"singleton": True, **CoordinationPolicy().payload()})
        for statement in (
            "UPDATE {}.execution_limits SET lease_seconds=2",
            "DELETE FROM {}.execution_limits",
            "TRUNCATE {}.execution_limits",
            "CREATE TABLE {}.runtime_unwanted(x INTEGER)",
        ):
            with (
                self.subTest(operation=statement.split()[0]),
                self.runtime.connect() as connection,
                self.assertRaises(psycopg.errors.InsufficientPrivilege),
            ):
                connection.execute(sql.SQL(statement).format(sql.Identifier(self.schema)))
