"""Quiescence keeps retained inquiry state and closes every public write path."""

import shutil
import sqlite3
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from continuity_lab.execution import ExecutionStore
from continuity_lab.execution_models import ExecutionStatus, InquiryResult
from continuity_lab.inquiry_worker import InquiryWorker, WorkerBusy
from continuity_lab.migrations import migrate, require_schema
from continuity_lab.models import BookingChange
from continuity_lab.source_transfer import (
    CutoverError,
    mark_source_cutover,
    prepare_source,
    read_source_state,
    source_snapshot,
)
from continuity_lab.sqlite_admission import SourceAdmissionClosed
from continuity_lab.store import TaskStore
from continuity_lab.supplier import FakeSupplier, initialize_supplier


class SourceTransferTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.database = self.path / "execution.sqlite3"
        self.backup = self.path / "quiescence-backup.sqlite3"
        migrate(self.database, self.path / "initial-backup.sqlite3")
        self.store = ExecutionStore(self.database)
        self.intake = TaskStore(self.database)
        self.request = BookingChange("DEMO-BK-001", date(2030, 12, 10), True)

    def submit(self, key="one"):
        return self.store.submit(
            scope_id="account-a", idempotency_key=key, request=self.request
        ).execution

    def intake_submit(self, key="m1"):
        return self.intake.submit(scope_id="account-a", idempotency_key=key, request=self.request)

    def version(self, database=None):
        with closing(sqlite3.connect(database or self.database)) as connection:
            return connection.execute("PRAGMA user_version").fetchone()[0]

    def rows(self, database=None):
        with closing(sqlite3.connect(database or self.database)) as connection:
            return tuple(
                tuple(connection.execute(f"SELECT * FROM {table} ORDER BY 1"))
                for table in ("tasks", "executions", "execution_attempts")
            )

    def test_private_v1_backup_restores_exact_original_rows_and_work_can_continue(self):
        accepted = self.submit("accepted")
        running = self.submit("running")
        self.store.start_attempt(scope_id="account-a", task_id=running.task_id, expected_version=0)
        legacy = self.intake_submit()
        before = self.rows()
        snapshot = prepare_source(self.database, self.backup)
        self.assertEqual(
            (len(snapshot.tasks), len(snapshot.executions), len(snapshot.attempts)), (3, 2, 1)
        )
        self.assertEqual((self.version(), self.version(self.backup)), (2, 1))
        self.assertEqual(self.rows(), before)
        self.assertEqual(self.rows(self.backup), before)
        self.assertEqual(self.backup.stat().st_mode & 0o777, 0o600)
        with closing(sqlite3.connect(self.backup)) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            require_schema(connection)
            self.assertIsNone(
                connection.execute(
                    "SELECT 1 FROM sqlite_schema WHERE name='source_cutover'"
                ).fetchone()
            )
        restored = self.path / "restored.sqlite3"
        shutil.copy2(self.backup, restored)
        restored_store = ExecutionStore(restored)
        self.assertEqual(
            restored_store.get(scope_id="account-a", task_id=accepted.task_id), accepted
        )
        enrolled = restored_store.submit(
            scope_id="account-a", idempotency_key="m1", request=self.request
        )
        self.assertEqual(enrolled.execution.task_id, legacy.task.task_id)
        self.assertTrue(enrolled.enrolled)
        self.assertTrue(
            restored_store.submit(
                scope_id="account-a",
                idempotency_key="new-after-explicit-restore",
                request=self.request,
            ).created
        )

    def test_quiescence_closes_m1_enrollment_start_recover_and_finish_but_keeps_replay(self):
        accepted = self.submit("accepted")
        running = self.submit("running")
        started = self.store.start_attempt(
            scope_id="account-a", task_id=running.task_id, expected_version=0
        )
        legacy = self.intake_submit()
        before = self.rows()
        prepare_source(self.database, self.backup)
        mutations = (
            lambda: self.submit("new"),
            lambda: self.intake_submit("new-m1"),
            lambda: self.store.submit(
                scope_id="account-a", idempotency_key="m1", request=self.request
            ),
            lambda: self.store.start_attempt(
                scope_id="account-a", task_id=accepted.task_id, expected_version=0
            ),
            lambda: self.store.recover_attempt(
                scope_id="account-a", task_id=running.task_id, expected_version=1
            ),
            lambda: self.store.finish_attempt(
                scope_id="account-a",
                task_id=running.task_id,
                attempt_id=started.attempt.attempt_id,
                expected_version=1,
                result=InquiryResult("DEMO-BK-001", date(2030, 12, 10), True),
            ),
        )
        for mutation in mutations:
            with self.assertRaises(SourceAdmissionClosed):
                mutation()
        self.assertEqual(self.submit("accepted"), accepted)
        self.assertEqual(self.intake_submit().task, legacy.task)
        self.assertEqual(len(self.store.list(scope_id="account-a")), 2)
        self.assertEqual(
            self.store.attempts(scope_id="account-a", task_id=running.task_id), (started.attempt,)
        )
        self.assertEqual(self.rows(), before)

    def test_committed_quiescence_failpoint_resumes_identity_and_cutover_checkpoint(self):
        accepted = self.submit()

        def stop(name):
            if name == "source.after_quiesce":
                raise RuntimeError("Controlled coordinator interruption")

        with self.assertRaises(RuntimeError):
            prepare_source(self.database, self.backup, failpoint=stop)
        state = read_source_state(self.database)
        self.assertEqual(state.state, "quiesced")
        snapshot = prepare_source(self.database, self.backup)
        self.assertEqual(snapshot.migration_id, state.migration_id)
        self.assertEqual(snapshot.source_digest, state.source_digest)
        self.assertEqual(source_snapshot(self.database), snapshot)
        mark_source_cutover(self.database, snapshot)
        mark_source_cutover(self.database, snapshot)
        self.assertEqual(read_source_state(self.database).state, "cutover")
        self.assertEqual(source_snapshot(self.database), snapshot)
        self.assertEqual(self.submit(), accepted)

    def test_matching_retained_v1_backup_can_resume_before_quiescence_commit(self):
        self.submit()
        before = self.rows()
        shutil.copy2(self.database, self.backup)
        self.backup.chmod(0o600)
        snapshot = prepare_source(self.database, self.backup)
        self.assertEqual(self.version(), 2)
        self.assertEqual(self.rows(self.backup), before)
        self.assertEqual(source_snapshot(self.database), snapshot)

    def test_unquiesced_export_and_changed_backup_destination_fail_closed(self):
        self.submit()
        with self.assertRaises(CutoverError):
            source_snapshot(self.database)
        self.assertIsNone(read_source_state(self.database))
        self.assertEqual(self.version(), 1)
        snapshot = prepare_source(self.database, self.backup)
        with self.assertRaises(CutoverError):
            prepare_source(self.database, self.path / "another-backup.sqlite3")
        self.assertEqual(source_snapshot(self.database), snapshot)
        self.assertFalse((self.path / "another-backup.sqlite3").exists())

    def test_changed_retained_backup_is_rejected_on_resume(self):
        self.submit()
        prepare_source(self.database, self.backup)
        with closing(sqlite3.connect(self.backup)) as connection, connection:
            connection.execute("UPDATE tasks SET created_at='2031-01-01T00:00:00+00:00'")
        with self.assertRaises(CutoverError):
            prepare_source(self.database, self.backup)
        self.assertEqual(read_source_state(self.database).state, "quiesced")

    def test_changed_source_content_cannot_export_or_resume(self):
        accepted = self.submit()
        prepare_source(self.database, self.backup)
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute(
                "UPDATE executions SET updated_at='2031-01-01T00:00:00+00:00' WHERE task_id=?",
                (accepted.task_id,),
            )
        for operation in (
            lambda: source_snapshot(self.database),
            lambda: prepare_source(self.database, self.backup),
        ):
            with self.assertRaises(CutoverError):
                operation()

    def test_active_worker_slot_refuses_quiescence_and_preserves_v1(self):
        accepted = self.submit()
        with self.store.worker_slot(), self.assertRaises(WorkerBusy):
            prepare_source(self.database, self.backup)
        self.assertEqual(self.version(), 1)
        self.assertFalse(self.backup.exists())
        self.assertEqual(self.submit(), accepted)
        self.assertIsNotNone(prepare_source(self.database, self.backup))

    def test_worker_after_quiescence_cannot_call_supplier_and_retains_accepted_state(self):
        supplier_database = self.path / "supplier.sqlite3"
        initialize_supplier(supplier_database, scope_id="account-a")

        class ForbiddenSupplier(FakeSupplier):
            def lookup(self, **kwargs):
                raise AssertionError("A quiesced source must not consult the supplier")

            def inquire(self, **kwargs):
                raise AssertionError("A quiesced source must not dispatch an inquiry")

        accepted = self.submit()
        prepare_source(self.database, self.backup)
        with self.assertRaises(SourceAdmissionClosed):
            InquiryWorker(self.store, ForbiddenSupplier(supplier_database)).run_one(
                scope_id="account-a", task_id=accepted.task_id
            )
        self.assertEqual(
            self.store.get(scope_id="account-a", task_id=accepted.task_id).status,
            ExecutionStatus.ACCEPTED,
        )
        self.assertEqual(FakeSupplier(supplier_database).count_inquiries(scope_id="account-a"), 0)

    def test_invalid_m1_only_timestamp_is_rejected_before_source_schema_changes(self):
        self.intake_submit()
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("UPDATE tasks SET created_at='not-a-time'")
        with self.assertRaises(CutoverError):
            prepare_source(self.database, self.backup)
        self.assertEqual(self.version(), 1)

    def test_retained_backup_with_public_permissions_is_rejected(self):
        self.submit()
        prepare_source(self.database, self.backup)
        self.backup.chmod(0o644)
        with self.assertRaises(CutoverError):
            prepare_source(self.database, self.backup)
        self.assertEqual(read_source_state(self.database).state, "quiesced")

    def test_retained_backup_with_hardlink_alias_is_rejected(self):
        import os

        self.submit()
        prepare_source(self.database, self.backup)
        os.link(self.backup, self.path / "backup-alias.sqlite3")
        with self.assertRaises(CutoverError):
            prepare_source(self.database, self.backup)

    def test_source_can_bind_only_one_destination_before_and_after_cutover(self):
        from continuity_lab.source_transfer import bind_source_target

        self.submit()
        snapshot = prepare_source(self.database, self.backup)
        bind_source_target(self.database, "a" * 64)
        bind_source_target(self.database, "a" * 64)
        with self.assertRaises(CutoverError):
            bind_source_target(self.database, "b" * 64)
        mark_source_cutover(self.database, snapshot)
        bind_source_target(self.database, "a" * 64)
        with self.assertRaises(CutoverError):
            bind_source_target(self.database, "b" * 64)
        self.assertEqual(read_source_state(self.database).target_identity, "a" * 64)

    def test_postgres_incompatible_source_identity_rejects_before_quiescence(self):
        self.intake.submit(scope_id="account\0a", idempotency_key="m1", request=self.request)
        with self.assertRaises(CutoverError):
            prepare_source(self.database, self.backup)
        self.assertEqual(self.version(), 1)
        self.assertIsNone(read_source_state(self.database))
