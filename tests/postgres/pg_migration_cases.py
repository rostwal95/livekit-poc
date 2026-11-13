"""Real PostgreSQL owner/permissions/staging tests; unavailable setup never skips.

Run explicitly with P1_RUN_POSTGRES_TESTS=1 and restricted local role credentials.
Every case uses a disposable schema owned by the one-shot migration principal.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from dataclasses import replace
from datetime import date
from uuid import uuid4

import psycopg
from psycopg import sql

from continuity_lab.execution_models import ExecutionStatus, InquiryResult
from continuity_lab.migrations import MigrationError, SchemaVersionError
from continuity_lab.models import BookingChange
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
from continuity_lab.postgres_settings import PostgresSettings
from continuity_lab.postgres_store import PostgresExecutionStore
from continuity_lab.transfer import TransferSnapshot, make_snapshot


class PostgresMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if os.environ.get("P1_RUN_POSTGRES_TESTS") != "1":
            raise RuntimeError(
                "Real PostgreSQL migration lane requires explicit setup and credentials"
            )
        cls.runtime_base = PostgresSettings.from_env()
        cls.migration_base = PostgresSettings.from_env("P1_MIGRATION_")

    def setUp(self) -> None:
        self.schema = "p1_migration_" + uuid4().hex
        self.runtime = replace(self.runtime_base, schema=self.schema)
        self.migration = replace(self.migration_base, schema=self.schema)
        self.addCleanup(self.drop_schema)
        self.snapshot = self.fixture_snapshot()

    def drop_schema(self) -> None:
        if not self.schema.startswith("p1_migration_") or len(self.schema) != 45:
            raise AssertionError("Only an isolated owned test schema may be removed")
        with self.migration.connect(application_name="continuity-test") as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(self.schema))
            )

    @staticmethod
    def fixture_snapshot() -> TransferSnapshot:
        created = "2030-12-01T11:00:00.000123+00:00"
        started = "2030-12-01T11:01:00.000456+00:00"
        finished = "2030-12-01T11:02:00.000789+00:00"
        request = BookingChange("DEMO-BK-001", date(2030, 12, 10), confirmed=True)
        payload = json.dumps(request.payload(), sort_keys=True, separators=(",", ":"))
        result = json.dumps(
            InquiryResult("DEMO-BK-001", date(2030, 12, 10), True).payload(),
            sort_keys=True,
            separators=(",", ":"),
        )
        tasks = [
            {
                "task_id": name,
                "scope_id": "account-a",
                "idempotency_key": name,
                "payload": payload,
                "status": "queued",
                "created_at": created,
            }
            for name in ("accepted", "running", "succeeded", "failed", "legacy-only")
        ]
        executions = []
        attempts = []
        for status, version in (("accepted", 0), ("running", 1), ("succeeded", 3), ("failed", 2)):
            executions.append(
                {
                    "task_id": status,
                    "operation": "booking.inquire",
                    "status": status,
                    "effect_id": str(uuid4()),
                    "version": version,
                    "created_at": created,
                    "updated_at": created
                    if version == 0
                    else started
                    if status == "running"
                    else finished,
                    "result_json": result if status == "succeeded" else None,
                    "error_code": "inquiry_rejected" if status == "failed" else None,
                }
            )
            if status == "accepted":
                continue
            for attempt_no in range(1, 3 if status == "succeeded" else 2):
                attempt_status = (
                    "interrupted"
                    if status == "succeeded" and attempt_no == 1
                    else "started"
                    if status == "running"
                    else status
                )
                attempts.append(
                    {
                        "attempt_id": str(uuid4()),
                        "task_id": status,
                        "attempt_no": attempt_no,
                        "status": attempt_status,
                        "started_at": started,
                        "finished_at": None if attempt_status == "started" else finished,
                        "error_code": "inquiry_rejected" if attempt_status == "failed" else None,
                    }
                )
        return make_snapshot(tasks, executions, attempts, migration_id=str(uuid4()))

    def business_rows(self) -> tuple[list[dict], list[dict], list[dict]]:
        with self.migration.connect(application_name="continuity-test") as connection:
            return tuple(
                connection.execute(
                    sql.SQL("SELECT * FROM {}.{} ORDER BY {}").format(
                        sql.Identifier(self.schema),
                        sql.Identifier(table),
                        sql.SQL('task_id COLLATE "C",attempt_no,attempt_id COLLATE "C"')
                        if table == "execution_attempts"
                        else sql.SQL('task_id COLLATE "C"'),
                    )
                ).fetchall()
                for table in ("tasks", "executions", "execution_attempts")
            )

    def test_batched_catalog_reads_preserve_all_versions_and_observe_later_drift(self) -> None:
        empty = make_snapshot([], [], [], migration_id=str(uuid4()))
        stage_import(self.migration, empty)
        activate_import(self.migration, empty.migration_id, empty.source_digest)

        class CatalogReadRecorder:
            def __init__(self, connection):
                self.connection = connection
                self.calls = []

            @property
            def info(self):
                return self.connection.info

            def execute(self, query, parameters=None):
                self.calls.append((query, parameters))
                return self.connection.execute(query, parameters)

        for version, upgrade in ((1, None), (2, upgrade_v2), (3, upgrade_v3), (4, upgrade_v4)):
            if upgrade is not None:
                upgrade(self.migration)
            with self.subTest(version=version), self.runtime.connect() as connection:
                observed = CatalogReadRecorder(connection)
                validate_schema(observed, self.schema, minimum_version=version)
                column_queries = [
                    (query, parameters)
                    for query, parameters in observed.calls
                    if isinstance(query, str) and "FROM pg_attribute a JOIN pg_class t" in query
                ]
                self.assertEqual(1, len(column_queries))
                self.assertEqual({1: 4, 2: 13, 3: 19, 4: 21}[version], len(column_queries[0][1][1]))
                self.assertEqual(
                    3,
                    sum(
                        isinstance(query, str) and "FROM pg_roles r WHERE r.rolname=%s" in query
                        for query, _ in observed.calls
                    ),
                )

        store = PostgresExecutionStore(self.runtime)
        self.assertEqual((), store.list(scope_id="account-a"))
        with self.migration.connect() as owner:
            owner.execute(
                sql.SQL(
                    "ALTER TABLE {}.execution_limits ALTER COLUMN lease_seconds SET DEFAULT 30"
                ).format(sql.Identifier(self.schema))
            )
        with self.assertRaises(SchemaVersionError):
            store.list(scope_id="account-a")
        # An explicit owner repair is still required; serving validation does not repair drift.
        with self.migration.connect() as owner:
            owner.execute(
                sql.SQL(
                    "ALTER TABLE {}.execution_limits ALTER COLUMN lease_seconds DROP DEFAULT"
                ).format(sql.Identifier(self.schema))
            )
        self.assertEqual((), store.list(scope_id="account-a"))

    def test_install_is_owner_only_idempotent_and_staging_gate_is_closed(self) -> None:
        install_schema(self.migration)
        install_schema(self.migration)
        metadata = read_import_state(self.runtime)
        self.assertEqual(
            (metadata.version, metadata.state, metadata.migration_id, metadata.source_digest),
            (1, "staging", None, None),
        )
        with (
            self.runtime.connect(application_name="continuity-test") as connection,
            self.assertRaises(SchemaVersionError),
        ):
            validate_schema(connection, self.schema)
        with self.assertRaises(MigrationError):
            install_schema(self.runtime)
        self.assertEqual(self.business_rows(), ([], [], []))

    def test_full_snapshot_is_exact_and_replayed_then_activated(self) -> None:
        report = stage_import(self.migration, self.snapshot)
        self.assertEqual(
            (report.changed, report.tasks, report.executions, report.attempts, report.state),
            (True, 5, 4, 4, "staging"),
        )
        verify_import(self.migration, self.snapshot)
        replay = stage_import(self.migration, self.snapshot)
        self.assertFalse(replay.changed)
        expected = tuple(
            sorted(
                (dict(row) for row in values),
                key=lambda row: (
                    row["task_id"],
                    row.get("attempt_no", 0),
                    row.get("attempt_id", ""),
                ),
            )
            for values in (self.snapshot.tasks, self.snapshot.executions, self.snapshot.attempts)
        )
        self.assertEqual(self.business_rows(), expected)
        activate_import(self.migration, self.snapshot.migration_id, self.snapshot.source_digest)
        activate_import(self.migration, self.snapshot.migration_id, self.snapshot.source_digest)
        self.assertEqual(read_import_state(self.runtime).state, "active")
        store = PostgresExecutionStore(self.runtime)
        succeeded = store.get(scope_id="account-a", task_id="succeeded")
        self.assertEqual((succeeded.status, succeeded.version), (ExecutionStatus.SUCCEEDED, 3))
        self.assertEqual(len(store.attempts(scope_id="account-a", task_id="succeeded")), 2)
        # The M1-only intake remains byte-identical and has no invented execution.
        self.assertEqual(len(store.list(scope_id="account-a")), 4)

    def test_each_precommit_interruption_rolls_back_rows_and_receipt(self) -> None:
        for fail_at in ("postgres.after_stage_rows", "postgres.before_stage_commit"):
            with self.subTest(fail_at=fail_at):

                def fail(name: str, fail_at: str = fail_at) -> None:
                    if name == fail_at:
                        raise RuntimeError("Controlled interruption")

                with self.assertRaises(RuntimeError):
                    stage_import(self.migration, self.snapshot, failpoint=fail)
                self.assertEqual(self.business_rows(), ([], [], []))
                self.assertIsNone(read_import_state(self.migration).migration_id)
        self.assertTrue(stage_import(self.migration, self.snapshot).changed)

    def test_lost_ack_retries_same_committed_receipt_without_overwrite(self) -> None:
        def fail(name: str) -> None:
            if name == "postgres.after_stage_commit":
                raise RuntimeError("Controlled lost acknowledgement")

        with self.assertRaises(RuntimeError):
            stage_import(self.migration, self.snapshot, failpoint=fail)
        before = self.business_rows()
        self.assertEqual(
            read_import_state(self.migration).source_digest, self.snapshot.source_digest
        )
        self.assertFalse(stage_import(self.migration, self.snapshot).changed)
        self.assertEqual(self.business_rows(), before)

    def test_abrupt_process_exit_before_commit_leaves_no_partial_import(self) -> None:
        # os._exit bypasses Python cleanup: PostgreSQL must roll back disconnected work.
        environment = os.environ.copy()
        environment["P1_MIGRATION_SCHEMA"] = self.schema
        code = """import os
from continuity_lab.postgres_settings import PostgresSettings
from continuity_lab.postgres_migrations import stage_import
from pg_migration_cases import PostgresMigrationTests
def stop(name):
    if name=='postgres.before_stage_commit': os._exit(73)
stage_import(PostgresSettings.from_env('P1_MIGRATION_'),PostgresMigrationTests.fixture_snapshot(),failpoint=stop)
"""
        existing = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = os.pathsep.join(
            filter(None, (os.path.dirname(__file__), existing))
        )
        outcome = subprocess.run(
            [sys.executable, "-c", code],
            env=environment,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(outcome.returncode, 73, "Child did not reach the controlled interruption")
        self.assertEqual(self.business_rows(), ([], [], []))
        self.assertIsNone(read_import_state(self.migration).migration_id)
        self.assertTrue(stage_import(self.migration, self.snapshot).changed)

    def test_changed_snapshot_or_receipt_never_overwrites_accepted_import(self) -> None:
        stage_import(self.migration, self.snapshot)
        original = self.business_rows()
        changed_tasks = [dict(row) for row in self.snapshot.tasks]
        changed_tasks[0]["scope_id"] = "another-account"
        changed = make_snapshot(
            changed_tasks,
            self.snapshot.executions,
            self.snapshot.attempts,
            migration_id=self.snapshot.migration_id,
        )
        different_id = replace(self.snapshot, migration_id=str(uuid4()))
        for snapshot in (changed, different_id, replace(self.snapshot, source_digest="0" * 64)):
            with self.subTest(identity=snapshot.migration_id):
                with self.assertRaises(MigrationError):
                    stage_import(self.migration, snapshot)
                self.assertEqual(self.business_rows(), original)
        with self.assertRaises(MigrationError):
            activate_import(self.migration, str(uuid4()), self.snapshot.source_digest)
        self.assertEqual(read_import_state(self.runtime).state, "staging")

    def test_activation_rechecks_staged_digest_and_leaves_corruption_inactive(self) -> None:
        stage_import(self.migration, self.snapshot)
        verify_import(self.migration, self.snapshot)
        with self.runtime.connect(application_name="continuity-test") as connection:
            connection.execute(
                sql.SQL(
                    "UPDATE {}.tasks SET scope_id='changed-after-verify' WHERE task_id='accepted'"
                ).format(sql.Identifier(self.schema))
            )
        changed = self.business_rows()
        with self.assertRaises(MigrationError):
            activate_import(self.migration, self.snapshot.migration_id, self.snapshot.source_digest)
        self.assertEqual(read_import_state(self.runtime).state, "staging")
        self.assertEqual(self.business_rows(), changed)
        # Explicit fixture repair restores exact original bytes; activation itself never repairs.
        with self.migration.connect(application_name="continuity-test") as connection:
            connection.execute(
                sql.SQL("UPDATE {}.tasks SET scope_id='account-a' WHERE task_id='accepted'").format(
                    sql.Identifier(self.schema)
                )
            )
        activate_import(self.migration, self.snapshot.migration_id, self.snapshot.source_digest)
        self.assertEqual(read_import_state(self.runtime).state, "active")

    def test_activation_table_locks_bound_concurrent_raw_dml(self) -> None:
        stage_import(self.migration, self.snapshot)
        with (
            self.runtime.connect(application_name="continuity-test") as connection,
            connection.transaction(),
        ):
            connection.execute(
                sql.SQL(
                    "UPDATE {}.tasks SET scope_id='uncommitted-writer' WHERE task_id='accepted'"
                ).format(sql.Identifier(self.schema))
            )
            # An already admitted raw writer holds ROW EXCLUSIVE until commit.
            # Activation must time out safely rather than verify/flip around it.
            with self.assertRaises(MigrationError):
                activate_import(
                    self.migration, self.snapshot.migration_id, self.snapshot.source_digest
                )
            self.assertEqual(read_import_state(self.runtime).state, "staging")
        with self.assertRaises(MigrationError):
            activate_import(self.migration, self.snapshot.migration_id, self.snapshot.source_digest)
        self.assertEqual(read_import_state(self.runtime).state, "staging")

    def test_target_alteration_is_detected_without_repair(self) -> None:
        stage_import(self.migration, self.snapshot)
        with self.migration.connect(application_name="continuity-test") as connection:
            connection.execute(
                sql.SQL("UPDATE {}.tasks SET scope_id='changed' WHERE task_id='accepted'").format(
                    sql.Identifier(self.schema)
                )
            )
        before = self.business_rows()
        for action in (
            lambda: verify_import(self.migration, self.snapshot),
            lambda: stage_import(self.migration, self.snapshot),
        ):
            with self.assertRaises(MigrationError):
                action()
            self.assertEqual(self.business_rows(), before)

    def test_nonempty_target_without_matching_receipt_is_never_cleared(self) -> None:
        install_schema(self.migration)
        task = dict(self.snapshot.tasks[0])
        with self.migration.connect(application_name="continuity-test") as connection:
            connection.execute(
                sql.SQL("INSERT INTO {}.tasks VALUES (%s,%s,%s,%s,%s,%s)").format(
                    sql.Identifier(self.schema)
                ),
                tuple(
                    task[name]
                    for name in (
                        "task_id",
                        "scope_id",
                        "idempotency_key",
                        "payload",
                        "status",
                        "created_at",
                    )
                ),
            )
        before = self.business_rows()
        with self.assertRaises(MigrationError):
            stage_import(self.migration, self.snapshot)
        self.assertEqual(self.business_rows(), before)
        self.assertIsNone(read_import_state(self.runtime).migration_id)

    def test_active_target_rejects_old_source_comparison_after_runtime_progress(self) -> None:
        stage_import(self.migration, self.snapshot)
        activate_import(self.migration, self.snapshot.migration_id, self.snapshot.source_digest)
        store = PostgresExecutionStore(self.runtime)
        store.start_attempt(scope_id="account-a", task_id="accepted", expected_version=0)
        before = self.business_rows()
        for action in (
            lambda: stage_import(self.migration, self.snapshot),
            lambda: verify_import(self.migration, self.snapshot),
        ):
            with self.assertRaises(MigrationError):
                action()
        self.assertEqual(self.business_rows(), before)
        self.assertEqual(read_import_state(self.runtime).migration_id, self.snapshot.migration_id)

    def test_runtime_cannot_change_schema_receipt_or_delete_accepted_rows(self) -> None:
        stage_import(self.migration, self.snapshot)
        forbidden = (
            sql.SQL("UPDATE {}.schema_metadata SET state='active'").format(
                sql.Identifier(self.schema)
            ),
            sql.SQL("DELETE FROM {}.tasks").format(sql.Identifier(self.schema)),
            sql.SQL("TRUNCATE {}.tasks CASCADE").format(sql.Identifier(self.schema)),
            sql.SQL("CREATE TABLE {}.forbidden (id TEXT)").format(sql.Identifier(self.schema)),
            sql.SQL("ALTER TABLE {}.tasks ADD COLUMN forbidden TEXT").format(
                sql.Identifier(self.schema)
            ),
            sql.SQL("DROP TABLE {}.execution_attempts").format(sql.Identifier(self.schema)),
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema + "_x")),
            sql.SQL("CREATE TEMP TABLE forbidden (id TEXT)"),
        )
        before = self.business_rows()
        with self.runtime.connect(application_name="continuity-test") as connection:
            for query in forbidden:
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    connection.execute(query)
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                connection.execute("SELECT rolpassword FROM pg_authid")
        self.assertEqual(self.business_rows(), before)
        self.assertEqual(read_import_state(self.runtime).state, "staging")

    def test_future_table_defaults_are_select_only(self) -> None:
        install_schema(self.migration)
        with self.migration.connect(application_name="continuity-test") as owner:
            owner.execute(
                sql.SQL("CREATE TABLE {}.future_table (id TEXT)").format(
                    sql.Identifier(self.schema)
                )
            )
            owner.execute(
                sql.SQL("INSERT INTO {}.future_table VALUES ('synthetic')").format(
                    sql.Identifier(self.schema)
                )
            )
        with self.runtime.connect(application_name="continuity-test") as runtime:
            self.assertEqual(
                runtime.execute(
                    sql.SQL("SELECT id FROM {}.future_table").format(sql.Identifier(self.schema))
                ).fetchone(),
                {"id": "synthetic"},
            )
            for query in (
                "INSERT INTO {}.future_table VALUES ('forbidden')",
                "UPDATE {}.future_table SET id='forbidden'",
                "DELETE FROM {}.future_table",
            ):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    runtime.execute(sql.SQL(query).format(sql.Identifier(self.schema)))
        with self.migration.connect(application_name="continuity-test") as owner:
            owner.execute(sql.SQL("DROP TABLE {}.future_table").format(sql.Identifier(self.schema)))
            validate_schema(owner, self.schema, require_active=False)

    def test_replaced_check_constraint_fails_closed_without_schema_repair(self) -> None:
        install_schema(self.migration)
        with self.migration.connect(application_name="continuity-test") as connection:
            connection.execute(
                sql.SQL(
                    "ALTER TABLE {}.tasks DROP CONSTRAINT tasks_status, ADD CONSTRAINT tasks_status CHECK (status IN ('queued','unsafe'))"
                ).format(sql.Identifier(self.schema))
            )
        for action in (
            lambda: read_import_state(self.runtime),
            lambda: install_schema(self.migration),
            lambda: stage_import(self.migration, self.snapshot),
        ):
            with self.assertRaises(SchemaVersionError):
                action()

    def test_added_runtime_metadata_authority_fails_schema_verification(self) -> None:
        install_schema(self.migration)
        with self.migration.connect(application_name="continuity-test") as connection:
            connection.execute(
                sql.SQL("GRANT UPDATE ON {}.schema_metadata TO livekit_lab").format(
                    sql.Identifier(self.schema)
                )
            )
        with self.assertRaises(SchemaVersionError):
            read_import_state(self.runtime)
        # Re-running installation detects privilege drift; it is not a repair command.
        with self.assertRaises(SchemaVersionError):
            install_schema(self.migration)

    def test_moved_check_name_does_not_hide_missing_task_constraint(self) -> None:
        install_schema(self.migration)
        with self.migration.connect(application_name="continuity-test") as connection:
            connection.execute(
                sql.SQL("ALTER TABLE {}.tasks DROP CONSTRAINT tasks_status").format(
                    sql.Identifier(self.schema)
                )
            )
            connection.execute(
                sql.SQL(
                    "ALTER TABLE {}.executions ADD CONSTRAINT tasks_status CHECK (status='queued')"
                ).format(sql.Identifier(self.schema))
            )
        with self.assertRaises(SchemaVersionError):
            read_import_state(self.runtime)

    def test_unlogged_table_defaults_and_duplicate_checks_are_rejected(self) -> None:
        changes = (
            "ALTER TABLE {}.schema_metadata SET UNLOGGED",
            "ALTER TABLE {}.tasks ALTER COLUMN status SET DEFAULT 'queued'",
            "ALTER TABLE {}.executions ADD CONSTRAINT tasks_status CHECK (status='queued')",
        )
        for change in changes:
            with self.subTest(change=change):
                self.drop_schema()
                install_schema(self.migration)
                with self.migration.connect(application_name="continuity-test") as connection:
                    connection.execute(sql.SQL(change).format(sql.Identifier(self.schema)))
                with self.assertRaises(SchemaVersionError):
                    read_import_state(self.runtime)

    def test_column_level_metadata_grants_are_rejected(self) -> None:
        install_schema(self.migration)
        with self.migration.connect(application_name="continuity-test") as connection:
            connection.execute(
                sql.SQL("GRANT UPDATE (state) ON {}.schema_metadata TO livekit_lab").format(
                    sql.Identifier(self.schema)
                )
            )
        with self.assertRaises(SchemaVersionError):
            read_import_state(self.runtime)

    def test_forged_digest_and_invalid_attempt_timestamp_fail_before_target_install(self) -> None:
        malformed_attempts = [dict(row) for row in self.snapshot.attempts]
        malformed_attempts[0]["started_at"] = "2030-12-01T11:01:00"
        malformed = make_snapshot(
            self.snapshot.tasks,
            self.snapshot.executions,
            malformed_attempts,
            migration_id=self.snapshot.migration_id,
        )
        for snapshot in (replace(self.snapshot, source_digest="0" * 64), malformed):
            with self.assertRaises(MigrationError):
                stage_import(self.migration, snapshot)
        with self.migration.connect(application_name="continuity-test") as connection:
            self.assertIsNone(
                connection.execute(
                    "SELECT 1 FROM pg_namespace WHERE nspname=%s", (self.schema,)
                ).fetchone()
            )


if __name__ == "__main__":
    unittest.main()
