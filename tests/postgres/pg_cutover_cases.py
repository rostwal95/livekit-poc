"""Real SQLite/PostgreSQL cutover checkpoints, interruption, resume and recovery.

This explicit lane fails when local role credentials are absent. Each test owns
its source directory and disposable PostgreSQL schema; no provider calls occur.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from psycopg import sql

from continuity_lab.cutover import cutover
from continuity_lab.execution import ExecutionStore
from continuity_lab.execution_models import FailureCode, InquiryResult
from continuity_lab.migrations import MigrationError, SchemaVersionError, migrate, require_schema
from continuity_lab.models import BookingChange
from continuity_lab.postgres_migrations import (
    activate_import,
    install_schema,
    read_import_state,
    stage_import,
)
from continuity_lab.postgres_settings import PostgresSettings
from continuity_lab.postgres_store import PostgresExecutionStore
from continuity_lab.source_transfer import CutoverError, prepare_source, read_source_state
from continuity_lab.sqlite_admission import SourceAdmissionClosed
from continuity_lab.store import TaskStore
from continuity_lab.transfer import make_snapshot

CHECKPOINTS = (
    "source.before_quiesce_commit",
    "source.after_quiesce",
    "postgres.after_stage_rows",
    "postgres.before_stage_commit",
    "postgres.after_stage_commit",
    "cutover.after_target_verified",
    "cutover.after_source_cutover",
    "cutover.after_target_active",
)


class PostgresCutoverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if os.environ.get("P1_RUN_POSTGRES_TESTS") != "1":
            raise RuntimeError(
                "Real cutover lane requires explicit local PostgreSQL setup and credentials"
            )
        cls.runtime_base = PostgresSettings.from_env()
        cls.migration_base = PostgresSettings.from_env("P1_MIGRATION_")

    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.schema = "p1_cutover_" + uuid4().hex
        self.runtime = replace(self.runtime_base, schema=self.schema)
        self.migration = replace(self.migration_base, schema=self.schema)
        self.addCleanup(self.drop_schema)
        self.request = BookingChange("DEMO-BK-001", date(2030, 12, 10), True)
        self.prepare_fixture("default")

    def drop_schema(self) -> None:
        if not self.schema.startswith("p1_cutover_") or len(self.schema) != 43:
            raise AssertionError("Only the isolated owned cutover schema may be removed")
        with self.migration.connect(application_name="continuity-test") as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(self.schema))
            )

    def prepare_fixture(self, label: str) -> None:
        folder = Path(self.directory.name) / label
        folder.mkdir()
        self.database = folder / "source.sqlite3"
        self.backup = folder / "before-cutover.sqlite3"
        migrate(self.database, folder / "before-v1.sqlite3")
        self.store = ExecutionStore(self.database)
        self.executions = {}
        for status in ("accepted", "running", "succeeded", "failed"):
            record = self.store.submit(
                scope_id="account-a", idempotency_key=status, request=self.request
            ).execution
            self.executions[status] = record
            if status == "accepted":
                continue
            started = self.store.start_attempt(
                scope_id="account-a", task_id=record.task_id, expected_version=0
            )
            if status == "running":
                continue
            if status == "succeeded":
                started = self.store.recover_attempt(
                    scope_id="account-a", task_id=record.task_id, expected_version=1
                )
                self.store.finish_attempt(
                    scope_id="account-a",
                    task_id=record.task_id,
                    attempt_id=started.attempt.attempt_id,
                    expected_version=2,
                    result=InquiryResult("DEMO-BK-001", date(2030, 12, 10), True),
                )
            else:
                self.store.finish_attempt(
                    scope_id="account-a",
                    task_id=record.task_id,
                    attempt_id=started.attempt.attempt_id,
                    expected_version=1,
                    error_code=FailureCode.INQUIRY_REJECTED,
                )
        self.legacy = (
            TaskStore(self.database)
            .submit(scope_id="account-a", idempotency_key="legacy-only", request=self.request)
            .task
        )
        self.original = self.sqlite_rows(self.database)

    @staticmethod
    def sqlite_rows(path: Path) -> tuple[list[dict], ...]:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            require_schema(connection)
            return tuple(
                [
                    dict(row)
                    for row in connection.execute(
                        "SELECT * FROM "
                        + table
                        + " ORDER BY "
                        + (
                            "task_id,attempt_no,attempt_id"
                            if table == "execution_attempts"
                            else "task_id"
                        )
                    )
                ]
                for table in ("tasks", "executions", "execution_attempts")
            )

    def postgres_rows(self) -> tuple[list[dict], ...]:
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

    def assert_source_closed(self) -> None:
        with self.assertRaises(SourceAdmissionClosed):
            self.store.submit(
                scope_id="account-a", idempotency_key="new-execution", request=self.request
            )
        with self.assertRaises(SourceAdmissionClosed):
            TaskStore(self.database).submit(
                scope_id="account-a", idempotency_key="new-intake", request=self.request
            )
        with self.assertRaises(SourceAdmissionClosed):
            self.store.start_attempt(
                scope_id="account-a",
                task_id=self.executions["accepted"].task_id,
                expected_version=0,
            )
        # Exact committed replay remains a read; it neither enrolls nor mutates.
        replay = self.store.submit(
            scope_id="account-a", idempotency_key="accepted", request=self.request
        )
        self.assertEqual((replay.created, replay.enrolled), (False, False))
        self.assertEqual(self.sqlite_rows(self.database), self.original)

    def assert_completed(self, expected_identity: tuple[str, str] | None = None) -> None:
        report = cutover(self.database, self.backup, self.migration)
        if expected_identity is not None:
            self.assertEqual((report.migration_id, report.source_digest), expected_identity)
        self.assertEqual(
            (report.state, report.tasks, report.executions, report.attempts), ("active", 5, 4, 4)
        )
        source = read_source_state(self.database)
        target = read_import_state(self.runtime)
        self.assertEqual((source.state, target.state), ("cutover", "active"))
        self.assertEqual(
            (source.migration_id, source.source_digest), (target.migration_id, target.source_digest)
        )
        self.assertEqual(self.postgres_rows(), self.original)
        self.assertEqual(self.sqlite_rows(self.backup), self.original)
        self.assert_source_closed()

    def test_complete_cutover_preserves_all_state_and_retry_keeps_runtime_progress(self) -> None:
        self.assert_completed()
        target = PostgresExecutionStore(self.runtime)
        task_id = self.executions["accepted"].task_id
        started = target.start_attempt(scope_id="account-a", task_id=task_id, expected_version=0)
        target.finish_attempt(
            scope_id="account-a",
            task_id=task_id,
            attempt_id=started.attempt.attempt_id,
            expected_version=1,
            result=InquiryResult("DEMO-BK-001", date(2030, 12, 10), True),
        )
        enrolled = target.submit(
            scope_id="account-a", idempotency_key="legacy-only", request=self.request
        )
        self.assertEqual(enrolled.execution.task_id, self.legacy.task_id)
        self.assertEqual((enrolled.created, enrolled.enrolled), (False, True))
        target.submit(
            scope_id="account-a", idempotency_key="new-postgres-work", request=self.request
        )
        progressed = self.postgres_rows()
        receipt = read_import_state(self.runtime)
        retry = cutover(self.database, self.backup, self.migration)
        self.assertTrue(retry.resumed)
        self.assertEqual(
            (retry.migration_id, retry.source_digest), (receipt.migration_id, receipt.source_digest)
        )
        self.assertEqual(self.postgres_rows(), progressed)
        self.assertEqual(self.sqlite_rows(self.database), self.original)
        self.assertEqual(self.sqlite_rows(self.backup), self.original)

    def test_completed_source_rejects_a_second_target_and_preserves_first_progress(self) -> None:
        self.assert_completed()
        target = PostgresExecutionStore(self.runtime)
        started = target.start_attempt(
            scope_id="account-a",
            task_id=self.executions["accepted"].task_id,
            expected_version=0,
        )
        target.finish_attempt(
            scope_id="account-a",
            task_id=started.execution.task_id,
            attempt_id=started.attempt.attempt_id,
            expected_version=1,
            result=InquiryResult("DEMO-BK-001", date(2030, 12, 10), True),
        )
        target.submit(
            scope_id="account-a", idempotency_key="first-target-progress", request=self.request
        )
        first_rows = self.postgres_rows()
        first_receipt = read_import_state(self.runtime)
        source_receipt = read_source_state(self.database)
        second_schema = "p1_cutover_" + uuid4().hex
        second = replace(self.migration, schema=second_schema)
        second_runtime = replace(self.runtime, schema=second_schema)

        def drop_second() -> None:
            with second.connect(application_name="continuity-test") as connection:
                connection.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                        sql.Identifier(second_schema)
                    )
                )

        self.addCleanup(drop_second)
        install_schema(second)
        with self.assertRaises(CutoverError):
            cutover(self.database, self.backup, second)
        self.assertEqual(read_source_state(self.database), source_receipt)
        self.assertEqual(read_import_state(self.runtime), first_receipt)
        self.assertEqual(self.postgres_rows(), first_rows)
        self.assertEqual(self.sqlite_rows(self.database), self.original)
        self.assertEqual(self.sqlite_rows(self.backup), self.original)
        second_receipt = read_import_state(second_runtime)
        self.assertEqual(
            (second_receipt.state, second_receipt.migration_id, second_receipt.source_digest),
            ("staging", None, None),
        )
        with second.connect(application_name="continuity-test") as connection:
            for table in ("tasks", "executions", "execution_attempts"):
                row = connection.execute(
                    sql.SQL("SELECT count(*) AS count FROM {}.{}").format(
                        sql.Identifier(second_schema), sql.Identifier(table)
                    )
                ).fetchone()
                self.assertEqual(row, {"count": 0})
        self.assert_source_closed()
        retried = cutover(self.database, self.backup, self.migration)
        self.assertTrue(retried.resumed)
        self.assertEqual(self.postgres_rows(), first_rows)

    def test_every_checkpoint_interruption_resumes_with_original_identity(self) -> None:
        for index, checkpoint in enumerate(CHECKPOINTS):
            with self.subTest(checkpoint=checkpoint):
                self.drop_schema()
                self.prepare_fixture("callback-" + str(index))

                def fail(name: str, checkpoint: str = checkpoint) -> None:
                    if name == checkpoint:
                        raise RuntimeError("Controlled checkpoint interruption")

                with self.assertRaises(RuntimeError):
                    cutover(self.database, self.backup, self.migration, failpoint=fail)
                state = read_source_state(self.database)
                if state is None:
                    self.assertEqual(checkpoint, "source.before_quiesce_commit")
                else:
                    self.assert_source_closed()
                identity = None if state is None else (state.migration_id, state.source_digest)
                self.assert_completed(identity)

    def test_process_exit_at_each_checkpoint_recovers_without_python_cleanup(self) -> None:
        code = """import os
from continuity_lab.cutover import cutover
from continuity_lab.postgres_settings import PostgresSettings
def stop(name):
    if name==os.environ['P1_CUTOVER_FAILPOINT']: os._exit(74)
cutover(os.environ['P1_CUTOVER_DATABASE'],os.environ['P1_CUTOVER_BACKUP'],PostgresSettings.from_env('P1_MIGRATION_'),failpoint=stop)
"""
        for index, checkpoint in enumerate(CHECKPOINTS):
            with self.subTest(checkpoint=checkpoint):
                self.drop_schema()
                self.prepare_fixture("process-" + str(index))
                environment = os.environ.copy()
                environment.update(
                    {
                        "P1_MIGRATION_SCHEMA": self.schema,
                        "P1_CUTOVER_DATABASE": str(self.database),
                        "P1_CUTOVER_BACKUP": str(self.backup),
                        "P1_CUTOVER_FAILPOINT": checkpoint,
                    }
                )
                outcome = subprocess.run(
                    [sys.executable, "-c", code],
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=20,
                    check=False,
                )
                self.assertEqual(
                    outcome.returncode, 74, "Child did not reach controlled cutover interruption"
                )
                state = read_source_state(self.database)
                identity = None if state is None else (state.migration_id, state.source_digest)
                self.assert_completed(identity)

    def test_retained_backup_is_restorable_as_original_v1_without_touching_target(self) -> None:
        self.assert_completed()
        target = self.postgres_rows()
        restored = Path(self.directory.name) / "restored.sqlite3"
        shutil.copyfile(self.backup, restored)
        self.assertEqual(self.sqlite_rows(restored), self.original)
        self.assertIsNone(read_source_state(restored))
        reopened = ExecutionStore(restored)
        self.assertEqual(len(reopened.list(scope_id="account-a")), 4)
        reopened.submit(
            scope_id="account-a", idempotency_key="restoration-proof", request=self.request
        )
        self.assertEqual(len(reopened.list(scope_id="account-a")), 5)
        self.assertEqual(self.postgres_rows(), target)
        self.assert_source_closed()

    def test_tampered_backup_prevents_resume_and_preserves_staged_target(self) -> None:
        def stop(name: str) -> None:
            if name == "postgres.after_stage_commit":
                raise RuntimeError("Controlled interruption after staging")

        with self.assertRaises(RuntimeError):
            cutover(self.database, self.backup, self.migration, failpoint=stop)
        target = self.postgres_rows()
        with closing(sqlite3.connect(self.backup)) as connection, connection:
            connection.execute(
                "UPDATE tasks SET scope_id='tampered-backup' WHERE task_id=?",
                (self.executions["accepted"].task_id,),
            )
        retained = self.backup.read_bytes()
        with self.assertRaises(CutoverError):
            cutover(self.database, self.backup, self.migration)
        self.assertEqual(self.postgres_rows(), target)
        self.assertEqual(self.backup.read_bytes(), retained)
        self.assertEqual(read_import_state(self.runtime).state, "staging")
        self.assertEqual(read_source_state(self.database).state, "quiesced")

    def test_changed_quiesced_source_prevents_activation_without_overwriting_target(self) -> None:
        def stop(name: str) -> None:
            if name == "postgres.after_stage_commit":
                raise RuntimeError("Controlled interruption after staging")

        with self.assertRaises(RuntimeError):
            cutover(self.database, self.backup, self.migration, failpoint=stop)
        before = self.postgres_rows()
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute(
                "UPDATE tasks SET scope_id='tampered-source' WHERE task_id=?",
                (self.executions["accepted"].task_id,),
            )
        with self.assertRaises(CutoverError):
            cutover(self.database, self.backup, self.migration)
        self.assertEqual(self.postgres_rows(), before)
        self.assertEqual(read_import_state(self.runtime).state, "staging")

    def test_raw_dml_after_source_cutover_cannot_activate_changed_target(self) -> None:
        def corrupt(name: str) -> None:
            if name == "cutover.after_source_cutover":
                with self.runtime.connect(application_name="continuity-test") as connection:
                    connection.execute(
                        sql.SQL(
                            "UPDATE {}.tasks SET scope_id='changed-at-activation-boundary' WHERE task_id=%s"
                        ).format(sql.Identifier(self.schema)),
                        (self.executions["accepted"].task_id,),
                    )

        with self.assertRaises(MigrationError):
            cutover(self.database, self.backup, self.migration, failpoint=corrupt)
        self.assertEqual(read_source_state(self.database).state, "cutover")
        self.assertEqual(read_import_state(self.runtime).state, "staging")
        changed = self.postgres_rows()
        with self.assertRaises(MigrationError):
            cutover(self.database, self.backup, self.migration)
        self.assertEqual(self.postgres_rows(), changed)
        self.assert_source_closed()
        # The fixture owner repairs the exact known synthetic row explicitly.
        with self.migration.connect(application_name="continuity-test") as connection:
            connection.execute(
                sql.SQL("UPDATE {}.tasks SET scope_id='account-a' WHERE task_id=%s").format(
                    sql.Identifier(self.schema)
                ),
                (self.executions["accepted"].task_id,),
            )
        self.assert_completed()

    def test_active_target_with_only_quiesced_source_is_protocol_inconsistency(self) -> None:
        snapshot = prepare_source(self.database, self.backup)
        stage_import(self.migration, snapshot)
        # Deliberate owner-only protocol violation, never an approved coordinator path.
        activate_import(self.migration, snapshot.migration_id, snapshot.source_digest)
        before = self.postgres_rows()
        with self.assertRaises(CutoverError):
            cutover(self.database, self.backup, self.migration)
        self.assertEqual(read_source_state(self.database).state, "quiesced")
        self.assertEqual(self.postgres_rows(), before)

    def test_conflicting_target_receipt_keeps_both_original_datasets(self) -> None:
        unrelated = make_snapshot((), (), (), migration_id=str(uuid4()))
        stage_import(self.migration, unrelated)
        with self.assertRaises(MigrationError):
            cutover(self.database, self.backup, self.migration)
        self.assertEqual(read_import_state(self.runtime).migration_id, unrelated.migration_id)
        self.assertEqual(self.postgres_rows(), ([], [], []))
        self.assertEqual(self.sqlite_rows(self.database), self.original)
        self.assertEqual(read_source_state(self.database).state, "quiesced")
        with self.assertRaises(SchemaVersionError):
            PostgresExecutionStore(self.runtime)


if __name__ == "__main__":
    unittest.main()
