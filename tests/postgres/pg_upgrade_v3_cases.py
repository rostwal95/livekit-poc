"""Explicit PostgreSQL v3 migration gate; missing setup is a failure, never a skip."""

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
from continuity_lab.execution_models import InquiryResult
from continuity_lab.migrations import MigrationError, SchemaVersionError
from continuity_lab.models import BookingChange
from continuity_lab.postgres_case import PostgresCaseAuthority
from continuity_lab.postgres_migrations import (
    activate_import,
    install_schema,
    read_import_state,
    stage_import,
    upgrade_v2,
    upgrade_v3,
    validate_schema,
    verify_import,
)
from continuity_lab.postgres_schema_v2 import COLUMNS as V2_COLUMNS
from continuity_lab.postgres_schema_v3 import DEFINITIONS, GRANTS, OPERATING_INDEXES
from continuity_lab.postgres_settings import PostgresSettings
from continuity_lab.postgres_store import PostgresExecutionStore
from continuity_lab.transfer import make_snapshot


class PostgresUpgradeV3Cases(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if os.environ.get("P1_RUN_POSTGRES_TESTS") != "1":
            raise RuntimeError("Real PostgreSQL v3 upgrade tests require explicit local setup")
        cls.runtime_base = PostgresSettings.from_env()
        cls.owner_base = PostgresSettings.from_env("P1_MIGRATION_")

    def setUp(self) -> None:
        self.schema = "p1_upgrade_v3_" + uuid4().hex
        self.runtime = replace(self.runtime_base, schema=self.schema)
        self.owner = replace(self.owner_base, schema=self.schema)
        self.addCleanup(self.drop_schema)
        self.snapshot = make_snapshot([], [], [], migration_id=str(uuid4()))
        self.actor = AuthenticatedActor("legacy-owner", "account-a")
        self.clock = [datetime(2030, 12, 1, tzinfo=UTC)]
        self.request = BookingChange("DEMO-BK-001", date(2030, 12, 10), True)
        self.install_v2()

    def install_v2(self) -> None:
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

    def drop_schema(self) -> None:
        if not self.schema.startswith("p1_upgrade_v3_") or len(self.schema) != 46:
            raise AssertionError("Only this owned isolated schema may be removed")
        with self.owner.connect(application_name="continuity-test") as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(self.schema))
            )

    def preserved_rows(self) -> dict[str, list[dict]]:
        tables = ("tasks", "executions", "execution_attempts", *V2_COLUMNS)
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

    def test_populated_v2_upgrade_preserves_exact_legacy_data_and_historical_receipt(
        self,
    ):
        before, receipt = self.preserved_rows(), read_import_state(self.owner)
        with (
            self.runtime.connect() as connection,
            self.assertRaises(SchemaVersionError),
        ):
            validate_schema(connection, self.schema, minimum_version=3)
        report = upgrade_v3(self.owner)
        self.assertEqual(
            (report.previous_version, report.current_version, report.changed),
            (2, 3, True),
        )
        self.assertEqual(self.preserved_rows(), before)
        after = read_import_state(self.owner)
        self.assertEqual(
            (after.state, after.migration_id, after.source_digest),
            (receipt.state, receipt.migration_id, receipt.source_digest),
        )
        self.assertEqual(after.version, 3)
        self.assertTrue(set(DEFINITIONS) <= self.table_names())
        with self.runtime.connect() as connection:
            validate_schema(connection, self.schema, minimum_version=3)

    def test_running_original_inquiry_can_finish_after_additive_v3_upgrade(self):
        started = self.store.start_attempt(
            scope_id=self.actor.scope_id,
            task_id=self.record.task_id,
            expected_version=self.record.version,
        )
        before = self.preserved_rows()
        upgrade_v3(self.owner)
        self.assertEqual(self.preserved_rows(), before)
        fresh = PostgresExecutionStore(self.runtime)
        finished = fresh.finish_attempt(
            scope_id=self.actor.scope_id,
            task_id=self.record.task_id,
            attempt_id=started.attempt.attempt_id,
            expected_version=started.execution.version,
            result=InquiryResult(self.request.booking_reference, self.request.new_check_in, True),
        )
        self.assertEqual(finished.status, "succeeded")
        self.assertEqual(finished.effect_id, self.record.effect_id)
        self.assertEqual(finished.task_id, self.record.task_id)
        self.assertEqual(
            self.cases.get(actor=self.actor, task_id=self.record.task_id).intent,
            self.intent,
        )

    def test_legacy_quote_and_intent_replay_remain_readable_without_mutation_backfill(
        self,
    ):
        before = self.preserved_rows()
        upgrade_v3(self.owner)
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
        upgrade_v3(self.owner)
        before = self.preserved_rows()
        self.assertEqual(upgrade_v3(self.owner).current_version, 3)
        self.assertFalse(upgrade_v3(self.owner).changed)
        old = upgrade_v2(self.owner)
        self.assertEqual((old.previous_version, old.current_version, old.changed), (3, 3, False))
        install_schema(self.owner)
        self.assertEqual(read_import_state(self.owner).version, 3)
        self.assertEqual(self.preserved_rows(), before)

    def test_active_v1_and_staging_cannot_skip_the_explicit_v2_upgrade(self):
        self.drop_schema()
        install_schema(self.owner)
        with self.assertRaises(SchemaVersionError):
            upgrade_v3(self.owner)
        self.assertEqual(read_import_state(self.owner).state, "staging")
        stage_import(self.owner, self.snapshot)
        activate_import(self.owner, self.snapshot.migration_id, self.snapshot.source_digest)
        with self.assertRaises(SchemaVersionError):
            upgrade_v3(self.owner)
        self.assertEqual(read_import_state(self.owner).version, 1)
        self.assertFalse(set(DEFINITIONS) & self.table_names())
        upgrade_v2(self.owner)
        self.assertTrue(upgrade_v3(self.owner).changed)

    def test_runtime_cannot_run_schema_upgrade(self):
        before = self.preserved_rows()
        with self.assertRaises(MigrationError):
            upgrade_v3(self.runtime)
        self.assertEqual(read_import_state(self.owner).version, 2)
        self.assertEqual(self.preserved_rows(), before)
        self.assertFalse(set(DEFINITIONS) & self.table_names())

    def test_precommit_failures_leave_exact_v2_then_valid_retry_progresses(self):
        before = self.preserved_rows()
        for barrier in (
            "postgres.upgrade_v3.after_ddl",
            "postgres.upgrade_v3.before_commit",
        ):

            def interrupt(point: str, expected: str = barrier) -> None:
                if point == expected:
                    raise RuntimeError("Controlled v3 migration interruption")

            with self.subTest(barrier=barrier), self.assertRaises(RuntimeError):
                upgrade_v3(self.owner, failpoint=interrupt)
            self.assertEqual(read_import_state(self.owner).version, 2)
            self.assertEqual(self.preserved_rows(), before)
            self.assertFalse(set(DEFINITIONS) & self.table_names())
        self.assertTrue(upgrade_v3(self.owner).changed)

    def test_lost_commit_acknowledgement_replays_complete_v3(self):
        before = self.preserved_rows()

        def interrupt(point: str) -> None:
            if point == "postgres.upgrade_v3.after_commit":
                raise RuntimeError("Controlled lost v3 acknowledgement")

        with self.assertRaises(RuntimeError):
            upgrade_v3(self.owner, failpoint=interrupt)
        self.assertEqual(read_import_state(self.owner).version, 3)
        self.assertFalse(upgrade_v3(self.owner).changed)
        self.assertEqual(self.preserved_rows(), before)

    def test_actual_child_exit_at_all_three_upgrade_checkpoints_is_atomic(self):
        package_root = (
            Path(importlib.import_module(upgrade_v3.__module__).__file__).resolve().parents[1]
        )
        code = """import os
from continuity_lab.postgres_migrations import upgrade_v3
from continuity_lab.postgres_settings import PostgresSettings
def interrupt(point):
    if point == os.environ['P1_UPGRADE_V3_BARRIER']:
        os._exit(77)
upgrade_v3(PostgresSettings.from_env('P1_MIGRATION_'),failpoint=interrupt)
raise SystemExit(78)
"""
        for barrier in (
            "postgres.upgrade_v3.after_ddl",
            "postgres.upgrade_v3.before_commit",
            "postgres.upgrade_v3.after_commit",
        ):
            if read_import_state(self.owner).version == 3:
                self.drop_schema()
                self.install_v2()
            before = self.preserved_rows()
            environment = {
                key: value
                for key, value in os.environ.items()
                if not key.startswith("P1_POSTGRES_")
            }
            environment.update(
                {
                    "P1_MIGRATION_SCHEMA": self.schema,
                    "P1_UPGRADE_V3_BARRIER": barrier,
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
                3 if barrier.endswith("after_commit") else 2,
            )
            self.assertEqual(self.preserved_rows(), before)
            upgrade_v3(self.owner)
            self.assertEqual(read_import_state(self.owner).version, 3)

    def test_runtime_new_immutable_tables_are_append_only_and_all_new_tables_forbid_delete(
        self,
    ):
        upgrade_v3(self.owner)
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
                        sql.SQL("UPDATE {}.{} SET created_at=created_at").format(
                            sql.Identifier(self.schema), sql.Identifier(table)
                        )
                    )
        with (
            self.runtime.connect() as connection,
            self.assertRaises(psycopg.errors.InsufficientPrivilege),
        ):
            connection.execute(
                sql.SQL("UPDATE {}.schema_metadata SET version=3").format(
                    sql.Identifier(self.schema)
                )
            )

    def test_completed_historical_receipt_does_not_allow_reimport_over_v3(self):
        upgrade_v3(self.owner)
        before = self.preserved_rows()
        with self.assertRaises(MigrationError):
            stage_import(self.owner, self.snapshot)
        with self.assertRaises(MigrationError):
            verify_import(self.owner, self.snapshot)
        activate_import(self.owner, self.snapshot.migration_id, self.snapshot.source_digest)
        self.assertEqual(self.preserved_rows(), before)
        self.assertEqual(read_import_state(self.owner).version, 3)

    def test_grant_drift_fails_and_replay_does_not_silently_repair_it(self):
        upgrade_v3(self.owner)
        with self.owner.connect(application_name="continuity-test") as connection:
            connection.execute(
                sql.SQL("GRANT UPDATE ON {}.completion_events TO livekit_lab").format(
                    sql.Identifier(self.schema)
                )
            )
        with (
            self.runtime.connect() as connection,
            self.assertRaises(SchemaVersionError),
        ):
            validate_schema(connection, self.schema)
        with self.assertRaises(SchemaVersionError):
            upgrade_v3(self.owner)
        with self.owner.connect(application_name="continuity-test") as connection:
            self.assertTrue(
                connection.execute(
                    "SELECT has_table_privilege('livekit_lab',%s,'UPDATE') AS allowed",
                    (self.schema + ".completion_events",),
                ).fetchone()["allowed"]
            )
            connection.execute(
                sql.SQL("REVOKE UPDATE ON {}.completion_events FROM livekit_lab").format(
                    sql.Identifier(self.schema)
                )
            )
        self.assertFalse(upgrade_v3(self.owner).changed)

    def test_control_state_extension_does_not_remove_prior_states_or_enforcement(self):
        upgrade_v3(self.owner)
        with self.owner.connect(application_name="continuity-test") as connection:
            for state in ("completed", "cancelled"):
                connection.execute(
                    sql.SQL(
                        "INSERT INTO {}.execution_controls VALUES (%s,%s,%s,%s,NULL,0,NULL,NULL,%s)"
                    ).format(sql.Identifier(self.schema)),
                    (
                        self.record.task_id,
                        state,
                        '{"initial_delay_seconds":1,"max_attempts":3,"max_delay_seconds":30}',
                        (self.clock[0] + timedelta(hours=1)).isoformat(),
                        self.clock[0].isoformat(),
                    ),
                )
                connection.execute(
                    sql.SQL("DELETE FROM {}.execution_controls WHERE task_id=%s").format(
                        sql.Identifier(self.schema)
                    ),
                    (self.record.task_id,),
                )
            with self.assertRaises(psycopg.errors.CheckViolation):
                connection.execute(
                    sql.SQL(
                        "INSERT INTO {}.execution_controls VALUES (%s,'invented',%s,%s,NULL,0,NULL,NULL,%s)"
                    ).format(sql.Identifier(self.schema)),
                    (
                        self.record.task_id,
                        '{"initial_delay_seconds":1,"max_attempts":3,"max_delay_seconds":30}',
                        (self.clock[0] + timedelta(hours=1)).isoformat(),
                        self.clock[0].isoformat(),
                    ),
                )

    def test_operational_indexes_are_required_nonunique_and_order_sensitive(self):
        upgrade_v3(self.owner)
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
            validate_schema(connection, self.schema, minimum_version=3)

    def test_new_table_default_column_and_check_drift_fail_closed(self):
        upgrade_v3(self.owner)
        with self.owner.connect(application_name="continuity-test") as connection:
            connection.execute(
                sql.SQL(
                    "ALTER TABLE {}.completion_events ALTER COLUMN created_at SET DEFAULT 'untrusted'"
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
                    "ALTER TABLE {}.completion_events ALTER COLUMN created_at DROP DEFAULT"
                ).format(sql.Identifier(self.schema))
            )
            connection.execute(
                sql.SQL("ALTER TABLE {}.mutation_effects DROP CONSTRAINT effects_state").format(
                    sql.Identifier(self.schema)
                )
            )
        with (
            self.runtime.connect() as connection,
            self.assertRaises(SchemaVersionError),
        ):
            validate_schema(connection, self.schema)
        with self.assertRaises(SchemaVersionError):
            upgrade_v3(self.owner)

    def test_delivery_attempt_requires_an_explicit_stable_receiver_identity(self):
        upgrade_v3(self.owner)
        event_id, target_id = str(uuid4()), str(uuid4())
        stamp = self.clock[0].isoformat()
        with self.owner.connect(application_name="continuity-test") as connection:
            connection.execute(
                sql.SQL("INSERT INTO {}.business_outcomes VALUES (%s,'{{}}',%s)").format(
                    sql.Identifier(self.schema)
                ),
                (self.record.task_id, stamp),
            )
            connection.execute(
                sql.SQL("INSERT INTO {}.completion_events VALUES (%s,%s,'{{}}',%s)").format(
                    sql.Identifier(self.schema)
                ),
                (event_id, self.record.task_id, stamp),
            )
            with self.assertRaises(psycopg.errors.CheckViolation) as caught:
                connection.execute(
                    sql.SQL(
                        "INSERT INTO {}.completion_deliveries VALUES (%s,NULL,'pending',0,1,'{{}}',%s,NULL,%s)"
                    ).format(sql.Identifier(self.schema)),
                    (event_id, stamp, stamp),
                )
            self.assertEqual(caught.exception.diag.constraint_name, "delivery_target_bound")
            connection.execute(
                sql.SQL(
                    "INSERT INTO {}.completion_deliveries VALUES (%s,%s,'pending',0,1,'{{}}',%s,NULL,%s)"
                ).format(sql.Identifier(self.schema)),
                (event_id, target_id, stamp, stamp),
            )
        with self.runtime.connect() as connection:
            validate_schema(connection, self.schema, minimum_version=3)
            row = connection.execute(
                sql.SQL(
                    "SELECT target_id,attempts FROM {}.completion_deliveries WHERE event_id=%s"
                ).format(sql.Identifier(self.schema)),
                (event_id,),
            ).fetchone()
            self.assertEqual((row["target_id"], row["attempts"]), (target_id, 1))
