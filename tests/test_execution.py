"""Behavioral contracts for explicitly migrated inquiry state, without suppliers."""

import io
import json
import logging
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, redirect_stdout
from dataclasses import FrozenInstanceError
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from continuity_lab.execution import ExecutionStore
from continuity_lab.execution_cli import _SafeFormatter, main
from continuity_lab.execution_models import (
    AttemptStatus,
    ExecutionNotFound,
    ExecutionStatus,
    FailureCode,
    InquiryResult,
    InvalidStoredState,
    StorageUnavailable,
    TransitionConflict,
    UnsupportedOperation,
)
from continuity_lab.migrations import MigrationError, SchemaVersionError, migrate
from continuity_lab.models import BookingChange, IdempotencyConflict, IntakeCapacityExceeded
from continuity_lab.store import TaskStore


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.database = self.path / "inquiry.sqlite3"
        migrate(self.database, self.path / "before.sqlite3")
        self.store = ExecutionStore(self.database)
        self.request = BookingChange("DEMO-BK-001", date(2030, 12, 10), True)

    def submit(self, **overrides):
        arguments = {
            "scope_id": "account-a",
            "idempotency_key": "request-1",
            "request": self.request,
        }
        arguments.update(overrides)
        return self.store.submit(**arguments)

    def outcome(self, **overrides):
        values = {
            "booking_reference": "DEMO-BK-001",
            "new_check_in": date(2030, 12, 10),
            "available": True,
        }
        values.update(overrides)
        return InquiryResult(**values)

    def test_atomic_identity_effect_and_replay_survive_reopen(self):
        first = self.submit()
        self.assertEqual((first.created, first.enrolled), (True, True))
        self.assertEqual(first.execution.status, ExecutionStatus.ACCEPTED)
        self.assertEqual(first.execution.version, 0)
        self.assertIsNotNone(first.execution.effect_id)
        self.assertEqual(
            self.store.attempts(scope_id="account-a", task_id=first.execution.task_id), ()
        )
        self.store = ExecutionStore(self.database)
        replay = self.submit()
        self.assertEqual((replay.created, replay.enrolled), (False, False))
        self.assertEqual(replay.execution, first.execution)
        self.assertEqual(
            TaskStore(self.database).list_tasks(scope_id="account-a")[0].status, "queued"
        )

    def test_concurrent_identical_and_conflicting_submissions_keep_one_identity(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            records = list(pool.map(lambda _: self.submit(), range(16)))
        self.assertEqual(sum(row.created for row in records), 1)
        self.assertEqual(sum(row.enrolled for row in records), 1)
        self.assertEqual(len({row.execution.effect_id for row in records}), 1)
        original = records[0].execution
        with self.assertRaises(IdempotencyConflict):
            self.submit(request=BookingChange("DEMO-BK-001", date(2030, 12, 11), True))
        other = self.submit(scope_id="account-b")
        self.assertNotEqual(other.execution.task_id, original.task_id)
        self.assertEqual(self.store.get(scope_id="account-a", task_id=original.task_id), original)

    def test_later_m1_intake_is_only_enrolled_by_explicit_submit(self):
        legacy = TaskStore(self.database).submit(
            scope_id="account-a", idempotency_key="request-1", request=self.request
        )
        with self.assertRaises(ExecutionNotFound):
            self.store.get(scope_id="account-a", task_id=legacy.task.task_id)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM executions").fetchone()[0], 0)
        enrolled = self.submit()
        self.assertEqual((enrolled.created, enrolled.enrolled), (False, True))
        self.assertEqual(enrolled.execution.task_id, legacy.task.task_id)
        self.assertEqual(self.submit().execution, enrolled.execution)

    def test_before_commit_failure_rolls_back_and_retry_progresses(self):
        def fail(name):
            if name == "execution.before_accept_commit":
                raise RuntimeError("SECRET_SENTINEL before commit")

        store = ExecutionStore(self.database, failpoint=fail)
        with self.assertRaises(RuntimeError):
            store.submit(scope_id="account-a", idempotency_key="request-1", request=self.request)
        self.assertEqual(self.store.list(scope_id="account-a"), ())
        self.assertEqual(TaskStore(self.database).list_tasks(scope_id="account-a"), [])
        self.assertTrue(self.submit().created)

    def test_after_commit_failure_is_resolved_using_original_identity(self):
        def fail(name):
            if name == "execution.after_accept_commit":
                raise RuntimeError("SECRET_SENTINEL after commit")

        store = ExecutionStore(self.database, failpoint=fail)
        with self.assertRaises(RuntimeError):
            store.submit(scope_id="account-a", idempotency_key="request-1", request=self.request)
        [original] = self.store.list(scope_id="account-a")
        replay = self.submit()
        self.assertEqual(replay.execution, original)
        self.assertEqual((replay.created, replay.enrolled), (False, False))

    def test_wrong_scope_and_unknown_id_have_identical_disclosure(self):
        row = self.submit().execution
        failures = []
        for scope, task in (("account-b", row.task_id), ("account-a", "missing")):
            with self.assertRaises(ExecutionNotFound) as caught:
                self.store.get(scope_id=scope, task_id=task)
            failures.append((caught.exception.code, str(caught.exception)))
            with self.assertRaises(ExecutionNotFound):
                self.store.attempts(scope_id=scope, task_id=task)
        self.assertEqual(failures[0], failures[1])

    def test_no_mutation_or_unsupported_cancel_is_accepted(self):
        with self.assertRaises(UnsupportedOperation):
            self.submit(operation="booking.apply")
        self.assertEqual(self.store.list(scope_id="account-a"), ())
        row = self.submit().execution
        with self.assertRaises(UnsupportedOperation):
            self.store.cancel(scope_id="account-a", task_id=row.task_id)
        self.assertEqual(self.store.get(scope_id="account-a", task_id=row.task_id), row)

    def test_ordinary_attempt_completes_with_bound_result_and_retains_queued_m1(self):
        row = self.submit().execution
        started = self.store.start_attempt(
            scope_id=row.scope_id, task_id=row.task_id, expected_version=0
        )
        self.assertEqual(started.execution.effect_id, row.effect_id)
        self.assertEqual(started.execution.version, 1)
        self.assertEqual(started.attempt.status, AttemptStatus.STARTED)
        result = self.outcome()
        finished = self.store.finish_attempt(
            scope_id=row.scope_id,
            task_id=row.task_id,
            attempt_id=started.attempt.attempt_id,
            expected_version=1,
            result=result,
        )
        self.assertEqual(
            (finished.status, finished.result, finished.version),
            (ExecutionStatus.SUCCEEDED, result, 2),
        )
        [attempt] = self.store.attempts(scope_id=row.scope_id, task_id=row.task_id)
        self.assertEqual(attempt.status, AttemptStatus.SUCCEEDED)
        self.assertIsNotNone(attempt.finished_at)
        self.assertEqual(
            TaskStore(self.database).list_tasks(scope_id=row.scope_id)[0].status, "queued"
        )

    def test_stale_wrong_attempt_and_wrong_result_cannot_finalize(self):
        row = self.submit().execution
        started = self.store.start_attempt(
            scope_id=row.scope_id, task_id=row.task_id, expected_version=0
        )
        arguments = {
            "scope_id": row.scope_id,
            "task_id": row.task_id,
            "attempt_id": started.attempt.attempt_id,
            "expected_version": 1,
            "result": self.outcome(),
        }
        with self.assertRaises(TransitionConflict):
            self.store.start_attempt(scope_id=row.scope_id, task_id=row.task_id, expected_version=0)
        for overrides, error in (
            ({"expected_version": 0}, TransitionConflict),
            ({"attempt_id": "another"}, TransitionConflict),
            ({"result": self.outcome(new_check_in=date(2030, 12, 11))}, ValueError),
        ):
            with self.subTest(overrides=overrides), self.assertRaises(error):
                self.store.finish_attempt(**(arguments | overrides))
        self.assertEqual(
            self.store.get(scope_id=row.scope_id, task_id=row.task_id).status,
            ExecutionStatus.RUNNING,
        )
        self.assertEqual(self.store.finish_attempt(**arguments).status, ExecutionStatus.SUCCEEDED)
        with self.assertRaises(TransitionConflict):
            self.store.finish_attempt(**arguments)

    def test_failure_codes_are_allowlisted_and_do_not_accept_provider_text(self):
        row = self.submit().execution
        attempt = self.store.start_attempt(
            scope_id=row.scope_id, task_id=row.task_id, expected_version=0
        ).attempt
        arguments = {
            "scope_id": row.scope_id,
            "task_id": row.task_id,
            "attempt_id": attempt.attempt_id,
            "expected_version": 1,
        }
        for invalid in (None, "SECRET_SENTINEL", "inquiry_rejected"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.store.finish_attempt(**arguments, error_code=invalid)
        failed = self.store.finish_attempt(**arguments, error_code=FailureCode.INQUIRY_REJECTED)
        self.assertEqual(
            (failed.status, failed.error_code, failed.result),
            (ExecutionStatus.FAILED, FailureCode.INQUIRY_REJECTED, None),
        )

    def test_capacity_preserves_replay_conflict_and_reads_and_recovers_slot(self):
        self.store = ExecutionStore(self.database, maximum_pending=1, maximum_records=2)
        first = self.submit().execution
        self.assertFalse(self.submit().created)
        with self.assertRaises(IntakeCapacityExceeded):
            self.submit(idempotency_key="next")
        with self.assertRaises(IdempotencyConflict):
            self.submit(request=BookingChange("OTHER", date(2030, 12, 10), True))
        attempt = self.store.start_attempt(
            scope_id=first.scope_id, task_id=first.task_id, expected_version=0
        ).attempt
        self.store.finish_attempt(
            scope_id=first.scope_id,
            task_id=first.task_id,
            attempt_id=attempt.attempt_id,
            expected_version=1,
            result=self.outcome(),
        )
        self.assertTrue(self.submit(idempotency_key="next").created)
        self.assertEqual(len(self.store.list(scope_id=first.scope_id)), 2)

    def test_retained_record_limit_preserves_completed_replay_and_inspection(self):
        self.store = ExecutionStore(self.database, maximum_pending=1, maximum_records=1)
        first = self.submit().execution
        started = self.store.start_attempt(
            scope_id=first.scope_id, task_id=first.task_id, expected_version=0
        )
        completed = self.store.finish_attempt(
            scope_id=first.scope_id,
            task_id=first.task_id,
            attempt_id=started.attempt.attempt_id,
            expected_version=1,
            result=self.outcome(),
        )
        with self.assertRaises(IntakeCapacityExceeded):
            self.submit(idempotency_key="new-after-completion")
        self.assertEqual(self.submit().execution, completed)
        self.assertEqual(self.store.list(scope_id=first.scope_id), (completed,))
        self.assertEqual(len(TaskStore(self.database).list_tasks(scope_id=first.scope_id)), 1)

    def test_runtime_never_initializes_or_accepts_unknown_schema(self):
        missing = self.path / "missing.sqlite3"
        with self.assertRaises(StorageUnavailable):
            ExecutionStore(missing)
        self.assertFalse(missing.exists())
        legacy = self.path / "legacy.sqlite3"
        TaskStore(legacy)
        with self.assertRaises(MigrationError):
            ExecutionStore(legacy)
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("PRAGMA user_version=2")
        with self.assertRaises(SchemaVersionError):
            self.store.list(scope_id="account-a")

    def test_corrupt_same_version_schema_and_noncanonical_payload_fail_closed(self):
        row = self.submit().execution
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute(
                "UPDATE tasks SET payload=? WHERE task_id=?",
                (json.dumps(self.request.payload()), row.task_id),
            )
        with self.assertRaises(InvalidStoredState):
            self.store.get(scope_id=row.scope_id, task_id=row.task_id)
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("CREATE TABLE foreign_data (id TEXT)")
        with self.assertRaises(MigrationError):
            self.store.get(scope_id=row.scope_id, task_id=row.task_id)

    def test_input_types_limits_clock_and_immutability(self):
        for value in (0, -1, True, 1001, "1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.store.list(scope_id="account-a", limit=value)
        for value in ("", " account", "x" * 129):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.submit(scope_id=value)
        with self.assertRaises(ValueError):
            InquiryResult("DEMO-BK-001", date(2030, 12, 10), 1)
        with self.assertRaises(ValueError):
            ExecutionStore(self.database, clock=lambda: datetime(2026, 11, 9)).submit(
                scope_id="a", idempotency_key="b", request=self.request
            )
        row = self.submit().execution
        with self.assertRaises(FrozenInstanceError):
            row.version = 12

    def test_safe_producer_logs_and_dependency_exception_translation(self):
        with self.assertLogs("continuity_lab.execution", level="INFO") as logs:
            self.submit()
            self.submit()
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(_SafeFormatter())
        for record in logs.records:
            handler.handle(record)
        self.assertNotIn(self.request.booking_reference, stream.getvalue())
        self.assertEqual(
            [json.loads(line)["event"] for line in stream.getvalue().splitlines()],
            ["execution_accepted", "execution_replayed"],
        )
        with (
            patch(
                "continuity_lab.execution.sqlite3.connect",
                side_effect=sqlite3.OperationalError("SECRET_SENTINEL"),
            ),
            self.assertLogs("continuity_lab.execution", level="ERROR") as failures,
            self.assertRaises(StorageUnavailable) as caught,
        ):
            self.store.list(scope_id="account-a")
        self.assertNotIn("SECRET_SENTINEL", str(caught.exception))
        self.assertNotIn("SECRET_SENTINEL", " ".join(failures.output))

    def test_cli_success_conflict_and_safe_error_output(self):
        arguments = [
            "--db",
            str(self.database),
            "submit",
            "--scope",
            "a",
            "--key",
            "one",
            "--booking",
            "DEMO-BK-001",
            "--check-in",
            "2030-12-10",
            "--confirm",
        ]
        with (
            patch("continuity_lab.execution_cli.configure_logging"),
            redirect_stdout(io.StringIO()) as out,
        ):
            self.assertEqual(main(arguments), 0)
        first = json.loads(out.getvalue())
        self.assertTrue(first["created"])
        arguments[arguments.index("2030-12-10")] = "2030-12-11"
        with (
            patch("continuity_lab.execution_cli.configure_logging"),
            redirect_stdout(io.StringIO()) as out,
        ):
            self.assertEqual(main(arguments), 2)
        self.assertEqual(json.loads(out.getvalue())["code"], "idempotency_conflict")


if __name__ == "__main__":
    unittest.main()
