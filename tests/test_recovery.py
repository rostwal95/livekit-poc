"""Version-conditional recovery preserves effect and rejects stale outcomes."""

import sqlite3
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from continuity_lab.execution import ExecutionStore
from continuity_lab.execution_models import (
    AttemptStatus,
    ExecutionNotFound,
    ExecutionStatus,
    InquiryResult,
    InvalidStoredState,
    TransitionConflict,
)
from continuity_lab.migrations import migrate
from continuity_lab.models import BookingChange


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.database = root / "execution.sqlite3"
        migrate(self.database, root / "v0.sqlite3")
        self.store = ExecutionStore(self.database, maximum_attempts=2)
        self.request = BookingChange("DEMO-BK-001", date(2030, 12, 10), True)
        self.row = self.store.submit(
            scope_id="account-a", idempotency_key="one", request=self.request
        ).execution

    def start(self):
        return self.store.start_attempt(
            scope_id=self.row.scope_id, task_id=self.row.task_id, expected_version=0
        )

    def recover(self, version=1):
        return self.store.recover_attempt(
            scope_id=self.row.scope_id, task_id=self.row.task_id, expected_version=version
        )

    def test_recovery_preserves_effect_interrupts_old_attempt_and_current_progresses(self):
        first = self.start()
        second = self.recover()
        self.assertEqual(
            (second.execution.effect_id, second.execution.version), (self.row.effect_id, 2)
        )
        self.assertEqual(second.attempt.attempt_no, 2)
        self.assertNotEqual(second.attempt.attempt_id, first.attempt.attempt_id)
        [old, current] = self.store.attempts(scope_id=self.row.scope_id, task_id=self.row.task_id)
        self.assertEqual(
            (old.status, current.status), (AttemptStatus.INTERRUPTED, AttemptStatus.STARTED)
        )
        for version in (1, 2):
            with self.subTest(version=version), self.assertRaises(TransitionConflict):
                self.store.finish_attempt(
                    scope_id=self.row.scope_id,
                    task_id=self.row.task_id,
                    attempt_id=first.attempt.attempt_id,
                    expected_version=version,
                    result=InquiryResult("DEMO-BK-001", date(2030, 12, 10), True),
                )
        finished = self.store.finish_attempt(
            scope_id=self.row.scope_id,
            task_id=self.row.task_id,
            attempt_id=second.attempt.attempt_id,
            expected_version=2,
            result=InquiryResult("DEMO-BK-001", date(2030, 12, 10), True),
        )
        self.assertEqual(
            (finished.status, finished.effect_id, finished.version),
            (ExecutionStatus.SUCCEEDED, self.row.effect_id, 3),
        )
        with self.assertRaises(TransitionConflict):
            self.recover(version=3)

    def test_recovery_is_bounded_and_keeps_state_inspectable(self):
        self.start()
        second = self.recover()
        with self.assertRaises(TransitionConflict):
            self.recover(version=2)
        self.assertEqual(
            self.store.get(scope_id=self.row.scope_id, task_id=self.row.task_id), second.execution
        )
        self.assertEqual(
            len(self.store.attempts(scope_id=self.row.scope_id, task_id=self.row.task_id)), 2
        )

    def test_prestart_wrong_scope_and_stale_version_cannot_recover(self):
        with self.assertRaises(TransitionConflict):
            self.recover(version=0)
        self.start()
        with self.assertRaises(ExecutionNotFound):
            self.store.recover_attempt(
                scope_id="other", task_id=self.row.task_id, expected_version=1
            )
        with self.assertRaises(TransitionConflict):
            self.recover(version=0)
        self.assertEqual(self.recover().attempt.attempt_no, 2)

    def test_ambiguous_current_attempt_state_is_not_silently_repaired(self):
        self.start()
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute(
                "INSERT INTO execution_attempts VALUES (?,?,2,'started',?,NULL,NULL)",
                (str(uuid4()), self.row.task_id, self.row.created_at),
            )
        with self.assertRaises(InvalidStoredState):
            self.recover()
        self.assertEqual(
            self.store.get(scope_id=self.row.scope_id, task_id=self.row.task_id).version, 1
        )

    def test_attempt_limit_configuration_is_explicit(self):
        for value in (0, -1, True, 101, "2"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ExecutionStore(self.database, maximum_attempts=value)


if __name__ == "__main__":
    unittest.main()
