"""Real PostgreSQL v1-to-v2 evolution; missing setup is failure, never a skip."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql

from continuity_lab.cutover import cutover
from continuity_lab.execution import ExecutionStore
from continuity_lab.execution_models import ExecutionStatus, InquiryResult
from continuity_lab.migrations import MigrationError, SchemaVersionError, migrate
from continuity_lab.models import BookingChange
from continuity_lab.postgres_migrations import (
    activate_import,
    install_schema,
    read_import_state,
    stage_import,
    upgrade_v2,
    validate_schema,
    verify_import,
)
from continuity_lab.postgres_schema_v2 import DEFINITIONS, GRANTS, OPERATING_INDEXES
from continuity_lab.postgres_settings import PostgresSettings, advisory_keys
from continuity_lab.postgres_store import PostgresExecutionStore
from continuity_lab.transfer import make_snapshot


class PostgresUpgradeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if os.environ.get("P1_RUN_POSTGRES_TESTS") != "1":
            raise RuntimeError(
                "Real PostgreSQL upgrade lane requires explicit setup and credentials"
            )
        cls.runtime_base = PostgresSettings.from_env()
        cls.migration_base = PostgresSettings.from_env("P1_MIGRATION_")

    def setUp(self) -> None:
        self.schema = "p1_upgrade_" + uuid4().hex
        self.runtime = replace(self.runtime_base, schema=self.schema)
        self.owner = replace(self.migration_base, schema=self.schema)
        self.addCleanup(self.drop_schema)
        self.request = BookingChange("DEMO-BK-001", date(2030, 12, 10), True)
        self.snapshot = make_snapshot([], [], [], migration_id=str(uuid4()))
        self.install_active()

    def install_active(self) -> None:
        install_schema(self.owner)
        stage_import(self.owner, self.snapshot)
        activate_import(self.owner, self.snapshot.migration_id, self.snapshot.source_digest)
        self.store = PostgresExecutionStore(self.runtime)
        self.record = self.store.submit(
            scope_id="account-a", idempotency_key="existing-v1", request=self.request
        ).execution

    def drop_schema(self) -> None:
        if not self.schema.startswith("p1_upgrade_") or len(self.schema) != 43:
            raise AssertionError("Only an owned isolated upgrade schema may be removed")
        with self.owner.connect(application_name="continuity-test") as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(self.schema))
            )

    def rows(self) -> tuple[list[dict], ...]:
        with self.owner.connect(application_name="continuity-test") as connection:
            return tuple(
                connection.execute(
                    sql.SQL("SELECT * FROM {}.{} ORDER BY {}").format(
                        sql.Identifier(self.schema),
                        sql.Identifier(table),
                        sql.SQL("task_id,attempt_no,attempt_id")
                        if table == "execution_attempts"
                        else sql.SQL("task_id"),
                    )
                ).fetchall()
                for table in ("tasks", "executions", "execution_attempts")
            )

    def names(self) -> set[str]:
        with self.owner.connect(application_name="continuity-test") as connection:
            return {
                row["tablename"]
                for row in connection.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname=%s", (self.schema,)
                ).fetchall()
            }

    def test_populated_v1_upgrade_preserves_original_rows_receipt_and_inquiry_progress(self):
        original = self.rows()
        old_receipt = read_import_state(self.owner)
        with self.runtime.connect() as connection, self.assertRaises(SchemaVersionError):
            validate_schema(connection, self.schema, minimum_version=2)
        report = upgrade_v2(self.owner)
        self.assertEqual(
            (report.previous_version, report.current_version, report.changed), (1, 2, True)
        )
        self.assertEqual(self.rows(), original)
        receipt = read_import_state(self.owner)
        self.assertEqual(receipt.version, 2)
        self.assertEqual(
            (receipt.state, receipt.migration_id, receipt.source_digest),
            (old_receipt.state, old_receipt.migration_id, old_receipt.source_digest),
        )
        store = PostgresExecutionStore(self.runtime)
        self.assertEqual(store.get(scope_id="account-a", task_id=self.record.task_id), self.record)
        started = store.start_attempt(
            scope_id="account-a", task_id=self.record.task_id, expected_version=0
        )
        finished = store.finish_attempt(
            scope_id="account-a",
            task_id=self.record.task_id,
            attempt_id=started.attempt.attempt_id,
            expected_version=started.execution.version,
            result=InquiryResult(self.request.booking_reference, self.request.new_check_in, True),
        )
        self.assertEqual(finished.status, ExecutionStatus.SUCCEEDED)
        self.assertEqual(finished.effect_id, self.record.effect_id)
        with self.runtime.connect() as connection:
            validate_schema(connection, self.schema, minimum_version=2)

    def test_upgrade_and_install_replay_do_not_change_data_or_reset_version(self):
        upgrade_v2(self.owner)
        old = self.rows()
        report = upgrade_v2(self.owner)
        self.assertEqual(
            (report.previous_version, report.current_version, report.changed), (2, 2, False)
        )
        install_schema(self.owner)
        self.assertEqual(read_import_state(self.owner).version, 2)
        self.assertEqual(self.rows(), old)
        self.assertEqual(
            self.names(),
            set(DEFINITIONS) | {"tasks", "executions", "execution_attempts", "schema_metadata"},
        )

    def test_runtime_role_cannot_upgrade(self):
        with self.assertRaises(MigrationError):
            upgrade_v2(self.runtime)
        self.assertEqual(read_import_state(self.owner).version, 1)
        self.assertNotIn("cases", self.names())
        self.assertEqual(
            self.store.get(scope_id="account-a", task_id=self.record.task_id), self.record
        )

    def test_staging_v1_cannot_upgrade_before_verified_cutover(self):
        self.drop_schema()
        install_schema(self.owner)
        with self.assertRaises(SchemaVersionError):
            upgrade_v2(self.owner)
        self.assertEqual(read_import_state(self.owner).state, "staging")
        self.assertEqual(read_import_state(self.owner).version, 1)
        self.assertNotIn("cases", self.names())

    def test_precommit_failures_restore_exact_v1_and_retry_progresses(self):
        for name in ("postgres.upgrade.after_ddl", "postgres.upgrade.before_commit"):
            with self.subTest(checkpoint=name):
                original = self.rows()

                def interrupt(point, barrier=name):
                    if point == barrier:
                        raise RuntimeError("Controlled upgrade interruption")

                with self.assertRaises(RuntimeError):
                    upgrade_v2(self.owner, failpoint=interrupt)
                self.assertEqual(read_import_state(self.owner).version, 1)
                self.assertEqual(self.rows(), original)
                self.assertNotIn("cases", self.names())
                with self.runtime.connect() as connection:
                    validate_schema(connection, self.schema)
        self.assertTrue(upgrade_v2(self.owner).changed)

    def test_committed_response_loss_replays_without_new_state(self):
        original = self.rows()

        def interrupt(point):
            if point == "postgres.upgrade.after_commit":
                raise RuntimeError("Controlled committed acknowledgement loss")

        with self.assertRaises(RuntimeError):
            upgrade_v2(self.owner, failpoint=interrupt)
        self.assertEqual(read_import_state(self.owner).version, 2)
        self.assertFalse(upgrade_v2(self.owner).changed)
        self.assertEqual(self.rows(), original)

    def test_actual_child_loss_at_each_checkpoint_preserves_atomic_version_and_data(self):
        module_root = (
            Path(importlib.import_module(upgrade_v2.__module__).__file__).resolve().parents[1]
        )
        code = """import os
from continuity_lab.postgres_migrations import upgrade_v2
from continuity_lab.postgres_settings import PostgresSettings
def interrupt(point):
    if point == os.environ['P1_UPGRADE_BARRIER']:
        os._exit(73)
upgrade_v2(PostgresSettings.from_env('P1_MIGRATION_'),failpoint=interrupt)
raise SystemExit(74)
"""
        for name in (
            "postgres.upgrade.after_ddl",
            "postgres.upgrade.before_commit",
            "postgres.upgrade.after_commit",
        ):
            with self.subTest(checkpoint=name):
                if read_import_state(self.owner).version == 2:
                    self.drop_schema()
                    self.install_active()
                original = self.rows()
                environment = {
                    key: value
                    for key, value in os.environ.items()
                    if not key.startswith(("P1_", "PG"))
                }
                environment.update(
                    {
                        "PYTHONPATH": str(module_root),
                        "P1_MIGRATION_HOST": self.owner.host,
                        "P1_MIGRATION_PORT": str(self.owner.port),
                        "P1_MIGRATION_DB": self.owner.dbname,
                        "P1_MIGRATION_USER": self.owner.user,
                        "P1_MIGRATION_PASSWORD": self.owner.password,
                        "P1_MIGRATION_SCHEMA": self.schema,
                        "P1_UPGRADE_BARRIER": name,
                    }
                )
                child = subprocess.run(
                    [sys.executable, "-c", code],
                    cwd=module_root,
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                )
                self.assertEqual(
                    child.returncode, 73, "Owned upgrade child must stop at its checkpoint"
                )
                self.assertEqual(child.stdout, "")
                self.assertEqual(child.stderr, "")
                expected = 2 if name.endswith("after_commit") else 1
                self.assertEqual(read_import_state(self.owner).version, expected)
                self.assertEqual(self.rows(), original)
                self.assertEqual(upgrade_v2(self.owner).changed, expected == 1)
                with self.runtime.connect() as connection:
                    validate_schema(connection, self.schema, minimum_version=2)

    def test_runtime_immutable_grants_and_metadata_are_enforced_by_postgres(self):
        upgrade_v2(self.owner)
        with self.runtime.connect() as connection:
            for table, grants in GRANTS.items():
                allowed = connection.execute(
                    "SELECT has_table_privilege(current_user,%s,'SELECT') AS reads,has_table_privilege(current_user,%s,'INSERT') AS inserts,has_table_privilege(current_user,%s,'UPDATE') AS updates",
                    (f"{self.schema}.{table}",) * 3,
                ).fetchone()
                self.assertEqual(
                    allowed, {"reads": True, "inserts": True, "updates": "UPDATE" in grants}
                )
                if "UPDATE" not in grants:
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                        connection.execute(
                            sql.SQL(
                                "UPDATE {}.{} SET payload_json=payload_json WHERE FALSE"
                            ).format(sql.Identifier(self.schema), sql.Identifier(table))
                            if table != "execution_signal_consumptions"
                            else sql.SQL(
                                "UPDATE {}.{} SET created_at=created_at WHERE FALSE"
                            ).format(sql.Identifier(self.schema), sql.Identifier(table))
                        )
                for verb in ("DELETE FROM", "TRUNCATE"):
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                        connection.execute(
                            sql.SQL("{} {}.{}").format(
                                sql.SQL(verb), sql.Identifier(self.schema), sql.Identifier(table)
                            )
                        )
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                connection.execute(
                    sql.SQL("UPDATE {}.schema_metadata SET version=1").format(
                        sql.Identifier(self.schema)
                    )
                )
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                connection.execute(
                    sql.SQL("CREATE TABLE {}.forbidden(id INTEGER)").format(
                        sql.Identifier(self.schema)
                    )
                )

    def test_grant_and_constraint_drift_fail_closed_and_replay_does_not_repair(self):
        upgrade_v2(self.owner)
        with self.owner.connect() as connection:
            connection.execute(
                sql.SQL("GRANT UPDATE ON {}.quotes TO livekit_lab").format(
                    sql.Identifier(self.schema)
                )
            )
        for operation in (
            lambda: PostgresExecutionStore(self.runtime),
            lambda: upgrade_v2(self.owner),
            lambda: install_schema(self.owner),
        ):
            with self.assertRaises(SchemaVersionError):
                operation()
        with self.owner.connect() as connection:
            allowed = connection.execute(
                "SELECT has_table_privilege('livekit_lab',%s,'UPDATE') AS allowed",
                (f"{self.schema}.quotes",),
            ).fetchone()
            self.assertTrue(allowed["allowed"])
            connection.execute(
                sql.SQL("REVOKE UPDATE ON {}.quotes FROM livekit_lab").format(
                    sql.Identifier(self.schema)
                )
            )
            connection.execute(
                sql.SQL("ALTER TABLE {}.cases DROP CONSTRAINT cases_scope").format(
                    sql.Identifier(self.schema)
                )
            )
        with self.assertRaises(SchemaVersionError):
            PostgresExecutionStore(self.runtime)

    def test_v2_cannot_be_staging_and_import_cannot_overwrite_active_lifecycle(self):
        upgrade_v2(self.owner)
        with self.owner.connect() as connection, self.assertRaises(psycopg.errors.CheckViolation):
            connection.execute(
                sql.SQL("UPDATE {}.schema_metadata SET state='staging'").format(
                    sql.Identifier(self.schema)
                )
            )
        for operation in (
            lambda: stage_import(self.owner, self.snapshot),
            lambda: verify_import(self.owner, self.snapshot),
        ):
            with self.assertRaises(MigrationError):
                operation()
        self.assertEqual(read_import_state(self.owner).version, 2)
        self.assertEqual(
            self.store.get(scope_id="account-a", task_id=self.record.task_id), self.record
        )

    def test_completed_sqlite_cutover_receipt_survives_upgrade_and_target_progress(self):
        self.drop_schema()
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            database = folder / "source.sqlite3"
            backup = folder / "source-backup.sqlite3"
            migrate(database, folder / "v0-backup.sqlite3")
            accepted = (
                ExecutionStore(database)
                .submit(scope_id="account-a", idempotency_key="cutover", request=self.request)
                .execution
            )
            first = cutover(database, backup, self.owner)
            upgrade_v2(self.owner)
            store = PostgresExecutionStore(self.runtime)
            started = store.start_attempt(
                scope_id="account-a", task_id=accepted.task_id, expected_version=0
            )
            finished = store.finish_attempt(
                scope_id="account-a",
                task_id=accepted.task_id,
                attempt_id=started.attempt.attempt_id,
                expected_version=started.execution.version,
                result=InquiryResult(
                    self.request.booking_reference, self.request.new_check_in, True
                ),
            )
            repeated = cutover(database, backup, self.owner)
            self.assertEqual(
                (repeated.migration_id, repeated.source_digest),
                (first.migration_id, first.source_digest),
            )
            self.assertEqual(store.get(scope_id="account-a", task_id=accepted.task_id), finished)
            self.assertEqual(read_import_state(self.owner).version, 2)
            self.assertEqual(
                ExecutionStore(database).get(scope_id="account-a", task_id=accepted.task_id),
                accepted,
            )

    def test_admission_contention_is_bounded_and_does_not_partially_upgrade(self):
        with self.owner.connect() as connection, connection.transaction():
            connection.execute(
                "SELECT pg_advisory_xact_lock(%s,%s)", advisory_keys(self.schema, "admission")
            )
            with self.assertRaises(MigrationError):
                upgrade_v2(self.owner)
        self.assertEqual(read_import_state(self.owner).version, 1)
        self.assertNotIn("cases", self.names())
        self.assertTrue(upgrade_v2(self.owner).changed)

    def test_profile_selection_rejects_metadata_view_before_executing_it(self):
        with self.owner.connect() as connection:
            connection.execute(
                sql.SQL("DROP TABLE {}.schema_metadata").format(sql.Identifier(self.schema))
            )
            connection.execute(
                sql.SQL("CREATE TABLE {}.metadata_probe_calls(id BIGINT)").format(
                    sql.Identifier(self.schema)
                )
            )
            connection.execute(
                sql.SQL(
                    "CREATE FUNCTION {}.metadata_probe() RETURNS INTEGER LANGUAGE plpgsql SECURITY DEFINER AS $probe$ BEGIN INSERT INTO {}.metadata_probe_calls VALUES(1); RETURN 1; END $probe$"
                ).format(sql.Identifier(self.schema), sql.Identifier(self.schema))
            )
            connection.execute(
                sql.SQL(
                    "CREATE VIEW {}.schema_metadata AS SELECT TRUE AS singleton,{}.metadata_probe() AS version,'active'::TEXT AS state,NULL::TEXT AS migration_id,NULL::TEXT AS source_digest"
                ).format(sql.Identifier(self.schema), sql.Identifier(self.schema))
            )
            connection.execute(
                sql.SQL("GRANT SELECT ON {}.schema_metadata TO livekit_lab").format(
                    sql.Identifier(self.schema)
                )
            )
        with self.runtime.connect() as connection, self.assertRaises(SchemaVersionError):
            validate_schema(connection, self.schema)
        with self.owner.connect() as connection:
            count = connection.execute(
                sql.SQL("SELECT count(*) AS count FROM {}.metadata_probe_calls").format(
                    sql.Identifier(self.schema)
                )
            ).fetchone()
            self.assertEqual(count["count"], 0)

    def test_operating_indexes_are_plain_nonunique_btrees_with_declared_order(self):
        upgrade_v2(self.owner)
        with self.owner.connect() as connection:
            rows = connection.execute(
                "SELECT c.relname,t.relname AS table_name,i.indisunique,i.indisprimary,am.amname,ARRAY(SELECT a.attname FROM unnest(i.indkey) WITH ORDINALITY k(num,ord) JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.num ORDER BY k.ord) AS columns FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_class t ON t.oid=i.indrelid JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_am am ON am.oid=c.relam WHERE n.nspname=%s",
                (self.schema,),
            ).fetchall()
        actual = {
            row["relname"]: (row["table_name"], tuple(row["columns"]))
            for row in rows
            if row["relname"] in OPERATING_INDEXES
        }
        self.assertEqual(actual, OPERATING_INDEXES)
        for row in rows:
            if row["relname"] in OPERATING_INDEXES:
                self.assertFalse(row["indisunique"])
                self.assertFalse(row["indisprimary"])
                self.assertEqual(row["amname"], "btree")

    def test_operating_index_drop_and_wrong_column_order_fail_closed(self):
        upgrade_v2(self.owner)
        with self.owner.connect() as connection:
            connection.execute(
                sql.SQL("DROP INDEX {}.signals_task_created_idx").format(
                    sql.Identifier(self.schema)
                )
            )
        with self.assertRaises(SchemaVersionError):
            PostgresExecutionStore(self.runtime)
        with self.owner.connect() as connection:
            connection.execute(
                sql.SQL(
                    "CREATE INDEX signals_task_created_idx ON {}.execution_signals(signal_id,created_at,task_id)"
                ).format(sql.Identifier(self.schema))
            )
        with self.assertRaises(SchemaVersionError):
            PostgresExecutionStore(self.runtime)
        with self.owner.connect() as connection:
            connection.execute(
                sql.SQL("DROP INDEX {}.signals_task_created_idx").format(
                    sql.Identifier(self.schema)
                )
            )
            connection.execute(
                sql.SQL(
                    "CREATE INDEX signals_task_created_idx ON {}.execution_signals(task_id,created_at,signal_id)"
                ).format(sql.Identifier(self.schema))
            )
        self.assertEqual(
            PostgresExecutionStore(self.runtime).get(
                scope_id="account-a", task_id=self.record.task_id
            ),
            self.record,
        )

    def test_operating_index_cannot_be_replaced_by_stricter_unique_index(self):
        upgrade_v2(self.owner)
        with self.owner.connect() as connection:
            connection.execute(
                sql.SQL("DROP INDEX {}.quotes_task_idx").format(sql.Identifier(self.schema))
            )
            connection.execute(
                sql.SQL("CREATE UNIQUE INDEX quotes_task_idx ON {}.quotes(task_id)").format(
                    sql.Identifier(self.schema)
                )
            )
        with self.assertRaises(SchemaVersionError):
            PostgresExecutionStore(self.runtime)

    def test_case_identity_is_separate_nonnull_unique_text_after_task_binding(self):
        upgrade_v2(self.owner)
        with self.owner.connect() as connection:
            columns = connection.execute(
                "SELECT a.attname,a.attnotnull,format_type(a.atttypid,a.atttypmod) AS kind,c.collname FROM pg_attribute a JOIN pg_class t ON t.oid=a.attrelid JOIN pg_namespace n ON n.oid=t.relnamespace LEFT JOIN pg_collation c ON c.oid=a.attcollation WHERE n.nspname=%s AND t.relname='cases' AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum",
                (self.schema,),
            ).fetchall()
        self.assertEqual([row["attname"] for row in columns[:2]], ["task_id", "case_id"])
        self.assertEqual(
            columns[1], {"attname": "case_id", "attnotnull": True, "kind": "text", "collname": "C"}
        )
        second = self.store.submit(
            scope_id="account-a", idempotency_key="other-case", request=self.request
        ).execution
        case_id = str(uuid4())
        payload = json.dumps(self.request.payload(), sort_keys=True, separators=(",", ":"))
        query = sql.SQL(
            "INSERT INTO {}.cases (task_id,case_id,scope_id,actor_id,revision,request_json,current_quote_id,cancelled,created_at,updated_at) VALUES (%s,%s,%s,%s,0,%s,NULL,FALSE,%s,%s)"
        ).format(sql.Identifier(self.schema))

        def values(task_id, identity):
            return (
                task_id,
                identity,
                "account-a",
                "actor-a",
                payload,
                self.record.created_at,
                self.record.created_at,
            )

        with self.runtime.connect() as connection:
            connection.execute(query, values(self.record.task_id, case_id))
            with self.assertRaises(psycopg.errors.UniqueViolation):
                connection.execute(query, values(second.task_id, case_id))
            with self.assertRaises(psycopg.errors.NotNullViolation):
                connection.execute(query, values(second.task_id, None))
            with self.assertRaises(psycopg.errors.CheckViolation):
                connection.execute(query, values(second.task_id, second.task_id))
            row = connection.execute(
                sql.SQL("SELECT case_id,task_id FROM {}.cases WHERE task_id=%s").format(
                    sql.Identifier(self.schema)
                ),
                (self.record.task_id,),
            ).fetchone()
            self.assertEqual(row, {"case_id": case_id, "task_id": self.record.task_id})
            validate_schema(connection, self.schema, minimum_version=2)
        self.assertNotEqual(case_id, self.record.task_id)
