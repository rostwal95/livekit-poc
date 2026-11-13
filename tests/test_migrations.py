"""Explicit schema upgrades preserve original M1 data and rollback boundaries."""

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from continuity_lab.migrations import (
    ATTEMPTS_DDL,
    EXECUTIONS_DDL,
    TASKS_DDL,
    MigrationError,
    SchemaVersionError,
    migrate,
    require_schema,
)
from continuity_lab.store import TaskStore


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.database = self.root / "intake.sqlite3"
        self.backup = self.root / "intake-v0.backup.sqlite3"
        with closing(sqlite3.connect(self.database)) as connection:
            connection.executescript(
                (Path(__file__).parent / "fixtures/m1-v0.sql").read_text(encoding="utf-8")
            )
        self.original = self.snapshot(self.database)

    @staticmethod
    def snapshot(path):
        with closing(sqlite3.connect(path)) as connection:
            return {
                "version": connection.execute("PRAGMA user_version").fetchone()[0],
                "tasks": connection.execute("SELECT * FROM tasks ORDER BY task_id").fetchall(),
                "tables": connection.execute(
                    "SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name"
                ).fetchall(),
            }

    def test_existing_m1_upgrades_with_stable_id_payload_and_effect(self):
        report = migrate(self.database, self.backup)
        self.assertEqual((report.previous_version, report.current_version), (0, 1))
        self.assertTrue(report.changed)
        self.assertTrue(report.backup_created)
        self.assertEqual(report.backfilled, 1)
        current = self.snapshot(self.database)
        self.assertEqual(current["tasks"], self.original["tasks"])
        self.assertEqual(self.snapshot(self.backup), self.original)
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            require_schema(connection)
            task_id, operation, status, effect, version, created, updated, result, error = (
                connection.execute("SELECT * FROM executions").fetchone()
            )
        self.assertEqual(task_id, self.original["tasks"][0][0])
        self.assertEqual(operation, "booking.inquire")
        self.assertEqual(status, "accepted")
        self.assertEqual(len(effect), 36)
        self.assertEqual(version, 0)
        self.assertEqual((created, updated), (self.original["tasks"][0][5],) * 2)
        self.assertIsNone(result)
        self.assertIsNone(error)
        self.assertEqual(
            TaskStore(self.database).list_tasks(scope_id="traveller-a")[0].task_id, task_id
        )

    def test_repeating_current_migration_does_not_regenerate_effect_or_backup(self):
        migrate(self.database, self.backup)
        with closing(sqlite3.connect(self.database)) as connection:
            before = connection.execute("SELECT * FROM executions").fetchall()
        backup_bytes = self.backup.read_bytes()
        report = migrate(self.database, self.backup)
        self.assertFalse(report.changed)
        self.assertFalse(report.backup_created)
        self.assertEqual(report.backfilled, 0)
        self.assertEqual(self.backup.read_bytes(), backup_bytes)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("SELECT * FROM executions").fetchall(), before)

    def test_fresh_database_is_created_only_by_explicit_migration(self):
        fresh, backup = self.root / "new.sqlite3", self.root / "new.backup.sqlite3"
        report = migrate(fresh, backup)
        self.assertEqual(report.backfilled, 0)
        self.assertTrue(report.changed)
        self.assertTrue(backup.is_file())
        self.assertEqual(fresh.stat().st_mode & 0o777, 0o600)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        with closing(sqlite3.connect(fresh)) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            require_schema(connection)
            self.assertEqual(connection.execute("SELECT count(*) FROM executions").fetchone()[0], 0)

    def test_interrupted_ddl_and_precommit_failures_roll_back_old_data(self):
        for index, barrier in enumerate(("migration.after_schema", "migration.before_commit")):
            with self.subTest(barrier=barrier):
                backup = self.root / f"interrupted-{index}.sqlite3"

                def failpoint(name, expected=barrier):
                    if name == expected:
                        raise RuntimeError("Synthetic controlled interruption")

                with self.assertRaisesRegex(RuntimeError, "controlled interruption"):
                    migrate(self.database, backup, failpoint=failpoint)
                self.assertEqual(self.snapshot(self.database), self.original)
                self.assertEqual(self.snapshot(backup), self.original)
        self.assertTrue(migrate(self.database, self.backup).changed)

    def test_abrupt_process_exit_before_commit_recovers_original_intake(self):
        script = """
import os, sys
from continuity_lab.migrations import migrate
def stop(name):
    if name == 'migration.before_commit':
        os._exit(73)
migrate(sys.argv[1], sys.argv[2], failpoint=stop)
"""
        result = subprocess.run(
            [sys.executable, "-c", script, str(self.database), str(self.backup)],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(result.returncode, 73, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")
        self.assertEqual(self.snapshot(self.database), self.original)
        self.assertEqual(self.snapshot(self.backup), self.original)
        self.assertTrue(migrate(self.database, self.root / "after-crash.sqlite3").changed)

    def test_backup_includes_committed_wal_and_can_be_restored_with_sqlite_api(self):
        with closing(sqlite3.connect(self.database)) as writer:
            self.assertEqual(writer.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
            writer.execute(
                "INSERT INTO tasks SELECT '22222222-2222-4222-8222-222222222222', "
                "'traveller-b', 'm1-existing-002', payload, status, created_at FROM tasks LIMIT 1"
            )
            writer.commit()
            expected = self.snapshot(self.database)
            self.assertTrue(Path(str(self.database) + "-wal").is_file())
            self.assertEqual(migrate(self.database, self.backup).backfilled, 2)
            self.assertEqual(self.snapshot(self.backup), expected)
        restored = self.root / "restored.sqlite3"
        with (
            closing(sqlite3.connect(self.backup)) as source,
            closing(sqlite3.connect(restored)) as destination,
        ):
            source.backup(destination)
        self.assertEqual(self.snapshot(restored), expected)
        self.assertEqual(len(TaskStore(restored).list_tasks(scope_id="traveller-b")), 1)

    def test_existing_backup_is_never_overwritten(self):
        self.backup.write_text("Do not replace this evidence", encoding="utf-8")
        with self.assertRaises(MigrationError):
            migrate(self.database, self.backup)
        self.assertEqual(self.backup.read_text(), "Do not replace this evidence")
        self.assertEqual(self.snapshot(self.database), self.original)

    def test_unknown_version_fails_without_writing_backup_or_old_data(self):
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("PRAGMA user_version=99")
        expected = self.snapshot(self.database)
        with self.assertRaises(SchemaVersionError):
            migrate(self.database, self.backup)
        self.assertFalse(self.backup.exists())
        self.assertEqual(self.snapshot(self.database), expected)

    def test_sqlite_looking_foreign_name_cannot_hide_an_unexpected_table(self):
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("CREATE TABLE sqliteXextra (data TEXT)")
        with self.assertRaises(SchemaVersionError):
            migrate(self.database, self.backup)
        self.assertFalse(self.backup.exists())

    def test_unknown_table_view_or_trigger_fails_closed(self):
        for kind, statement in (
            ("table", "CREATE TABLE extra (data TEXT)"),
            ("view", "CREATE VIEW extra AS SELECT * FROM tasks"),
            ("trigger", "CREATE TRIGGER extra AFTER INSERT ON tasks BEGIN SELECT 1; END"),
            ("index", "CREATE INDEX extra ON tasks(created_at)"),
        ):
            with self.subTest(kind=kind):
                with closing(sqlite3.connect(self.database)) as connection:
                    connection.execute(statement)
                with self.assertRaises(SchemaVersionError):
                    migrate(self.database, self.backup)
                self.assertFalse(self.backup.exists())
                self.assertEqual(self.snapshot(self.database)["tasks"], self.original["tasks"])
                with closing(sqlite3.connect(self.database)) as connection:
                    connection.execute(f"DROP {kind.upper()} extra")

    def test_malformed_or_noncanonical_legacy_rows_fail_without_migration(self):
        original_payload = self.original["tasks"][0][3]
        variants = (
            ("payload", "not-json SECRET_SENTINEL"),
            ("payload", json.dumps(json.loads(original_payload), indent=2)),
            ("payload", original_payload.replace('"confirmed":true', '"confirmed":false')),
            (
                "payload",
                original_payload.replace('"confirmed":true', '"confirmed":true,"confirmed":true'),
            ),
            ("payload", original_payload.replace('"confirmed":true', '"confirmed":true,"extra":1')),
            ("payload", original_payload.replace("2030-12-10", "2030-02-31")),
            ("scope_id", " "),
            ("idempotency_key", " leading-space"),
            ("created_at", "2026-11-09T10:00:00"),
            ("created_at", "2026-11-09T10:00:00+01:00"),
        )
        for column, value in variants:
            with self.subTest(column=column, value=value):
                with closing(sqlite3.connect(self.database)) as connection, connection:
                    connection.execute(f"UPDATE tasks SET {column}=?", (value,))
                expected = self.snapshot(self.database)
                with self.assertRaises(MigrationError) as raised:
                    migrate(self.database, self.backup)
                self.assertNotIn("SECRET_SENTINEL", str(raised.exception))
                self.assertEqual(self.snapshot(self.database), expected)
                self.assertFalse(self.backup.exists())
                with closing(sqlite3.connect(self.database)) as connection, connection:
                    connection.execute("DELETE FROM tasks")
                    connection.execute(
                        "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?)", self.original["tasks"][0]
                    )

    def test_forged_version_does_not_bypass_shape_or_constraint_checks(self):
        for index, ddl in enumerate(
            (
                EXECUTIONS_DDL.replace("'booking.inquire'", "'BOOKING.INQUIRE'"),
                EXECUTIONS_DDL.replace(" REFERENCES tasks(task_id)", ""),
            )
        ):
            with self.subTest(index=index):
                database = self.root / f"forged-{index}.sqlite3"
                with closing(sqlite3.connect(database)) as connection:
                    connection.execute(TASKS_DDL)
                    connection.execute(ddl)
                    connection.execute(ATTEMPTS_DDL)
                    connection.execute("PRAGMA user_version=1")
                    connection.execute("PRAGMA foreign_keys=ON")
                    with self.assertRaises(SchemaVersionError):
                        require_schema(connection)
                with self.assertRaises(SchemaVersionError):
                    migrate(database, self.root / f"forged-{index}.backup.sqlite3")

    def test_require_schema_is_read_only_and_rejects_legacy_or_disabled_foreign_keys(self):
        with (
            closing(sqlite3.connect(self.database)) as connection,
            self.assertRaises(SchemaVersionError),
        ):
            require_schema(connection)
        self.assertEqual(self.snapshot(self.database), self.original)
        migrate(self.database, self.backup)
        with closing(sqlite3.connect(self.database)) as connection:
            with self.assertRaisesRegex(SchemaVersionError, "foreign-key enforcement"):
                require_schema(connection)
            connection.execute("PRAGMA foreign_keys=ON")
            require_schema(connection)
            self.assertFalse(connection.in_transaction)

    def test_attempt_fk_uniqueness_and_result_state_constraints_are_enforced(self):
        migrate(self.database, self.backup)
        task_id = self.original["tasks"][0][0]
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            for query, params in (
                ("UPDATE executions SET status='failed' WHERE task_id=?", (task_id,)),
                ("UPDATE executions SET result_json='{}' WHERE task_id=?", (task_id,)),
                ("UPDATE executions SET status='mutating' WHERE task_id=?", (task_id,)),
                (
                    "INSERT INTO execution_attempts VALUES ('a', 'unknown', 1, 'started', 'now', NULL, NULL)",
                    (),
                ),
                (
                    "INSERT INTO execution_attempts VALUES ('a', ?, 1, 'failed', 'now', NULL, 'failure')",
                    (task_id,),
                ),
            ):
                with self.subTest(query=query), self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(query, params)
                connection.rollback()
            connection.execute(
                "INSERT INTO execution_attempts VALUES ('a', ?, 1, 'started', 'now', NULL, NULL)",
                (task_id,),
            )
            connection.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO execution_attempts VALUES ('b', ?, 1, 'started', 'now', NULL, NULL)",
                    (task_id,),
                )

    def test_same_path_and_symlink_paths_are_rejected_without_modification(self):
        with self.assertRaises(MigrationError):
            migrate(self.database, self.database)
        database_link = self.root / "database-link.sqlite3"
        database_link.symlink_to(self.database)
        with self.assertRaises(MigrationError):
            migrate(database_link, self.backup)
        backup_link = self.root / "backup-link.sqlite3"
        backup_link.symlink_to(self.database)
        with self.assertRaises(MigrationError):
            migrate(self.database, backup_link)
        self.assertEqual(self.snapshot(self.database), self.original)


if __name__ == "__main__":
    unittest.main()
