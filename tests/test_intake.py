import json
import sqlite3
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from continuity_lab.models import (
    BookingChange,
    IdempotencyConflict,
    IntakeCapacityExceeded,
)
from continuity_lab.store import TaskStore


class IntakeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = Path(self.directory.name) / "tasks.sqlite3"
        self.store = TaskStore(self.database)
        self.request = BookingChange("DEMO-BK-001", date(2030, 12, 10), confirmed=True)

    def submit(self, **overrides):
        arguments = {
            "scope_id": "traveller-a",
            "idempotency_key": "request-001",
            "request": self.request,
        }
        arguments.update(overrides)
        return self.store.submit(**arguments)

    def test_duplicate_returns_original_task_after_reopening_store(self) -> None:
        first = self.submit()
        self.store = TaskStore(self.database)
        replay = self.submit()
        self.assertTrue(first.created)
        self.assertFalse(replay.created)
        self.assertEqual(first.task, replay.task)
        self.assertEqual(1, len(self.store.list_tasks(scope_id="traveller-a")))

    def test_conflicting_key_does_not_modify_original(self) -> None:
        original = self.submit()
        other = BookingChange("DEMO-BK-001", date(2030, 12, 11), confirmed=True)
        with self.assertRaises(IdempotencyConflict):
            self.submit(request=other)
        self.assertEqual([original.task], self.store.list_tasks(scope_id="traveller-a"))

    def test_same_key_is_independent_in_different_scopes(self) -> None:
        first = self.submit()
        second = self.submit(scope_id="traveller-b")
        self.assertNotEqual(first.task.task_id, second.task.task_id)
        self.assertEqual([first.task], self.store.list_tasks(scope_id="traveller-a"))

    def test_concurrent_duplicate_submissions_create_one_task(self) -> None:
        def submit(_):
            return TaskStore(self.database).submit(
                scope_id="traveller-a",
                idempotency_key="request-001",
                request=self.request,
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(submit, range(16)))
        self.assertEqual(1, sum(result.created for result in results))
        self.assertEqual(1, len({result.task.task_id for result in results}))

    def test_concurrent_conflicting_requests_accept_only_one_payload(self) -> None:
        other = BookingChange("DEMO-BK-001", date(2030, 12, 11), confirmed=True)

        def submit(request):
            try:
                return self.submit(request=request)
            except IdempotencyConflict:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, [self.request, other]))
        self.assertEqual(1, sum(result is not None for result in results))
        self.assertEqual(1, len(self.store.list_tasks(scope_id="traveller-a")))

    def test_unconfirmed_request_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "confirmation"):
            BookingChange("DEMO-BK-001", date(2030, 12, 10), confirmed=False)
        self.assertEqual([], self.store.list_tasks(scope_id="traveller-a"))

    def test_booking_reference_normalization_is_canonical(self) -> None:
        first = self.submit()
        normalized = BookingChange(" demo-bk-001 ", date(2030, 12, 10), confirmed=True)
        self.assertEqual(first.task, self.submit(request=normalized).task)

    def test_invalid_identity_is_rejected(self) -> None:
        for value in ("", " ", " key", "x" * 129):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.submit(idempotency_key=value)

    def test_capacity_only_rejects_new_keys_without_blocking_replay_or_conflict(
        self,
    ) -> None:
        first = self.submit()
        replay = self.submit(max_database_bytes=1)
        self.assertEqual((replay.task, replay.created), (first.task, False))
        with self.assertRaises(IdempotencyConflict):
            self.submit(
                request=BookingChange("DEMO-BK-001", date(2030, 12, 11), confirmed=True),
                max_database_bytes=1,
            )
        with self.assertRaises(IntakeCapacityExceeded):
            self.submit(idempotency_key="new-key", max_database_bytes=1)
        self.assertEqual(self.store.list_tasks(scope_id="traveller-a", limit=1), [first.task])
        self.assertEqual(self.store.list_tasks(scope_id="traveller-a"), [first.task])

    def test_concurrent_capacity_checks_roll_back_growth_under_the_writer_transaction(
        self,
    ) -> None:
        def allocation():
            with closing(sqlite3.connect(self.database)) as connection:
                page_count = connection.execute("PRAGMA page_count").fetchone()[0]
                page_size = connection.execute("PRAGMA page_size").fetchone()[0]
            return page_count * page_size, page_size

        original_bytes, page_size = allocation()
        maximum = original_bytes + page_size

        def submit(index):
            try:
                return TaskStore(self.database).submit(
                    scope_id="traveller-a",
                    idempotency_key=f"capacity-{index}",
                    request=self.request,
                    max_database_bytes=maximum,
                )
            except IntakeCapacityExceeded:
                return None

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(submit, range(64)))
        accepted = [result for result in results if result is not None]
        self.assertGreater(len(accepted), 0)
        self.assertLess(len(accepted), len(results))
        self.assertLessEqual(allocation()[0], maximum)
        persisted = self.store.list_tasks(scope_id="traveller-a")
        self.assertEqual(
            {task.task_id for task in persisted},
            {result.task.task_id for result in accepted},
        )
        self.assertEqual(len(persisted), len(accepted))
        first = accepted[0]
        replay = self.submit(idempotency_key=first.task.idempotency_key, max_database_bytes=1)
        self.assertEqual(replay.task, first.task)
        self.assertFalse(replay.created)

    def test_list_limit_preserves_order_scope_and_unlimited_default(self) -> None:
        first = self.submit()
        second = self.submit(idempotency_key="request-002")
        self.submit(scope_id="traveller-b")
        self.assertEqual(self.store.list_tasks(scope_id="traveller-a", limit=1), [first.task])
        self.assertEqual(self.store.list_tasks(scope_id="traveller-a"), [first.task, second.task])
        for invalid in (0, -1, True, "1"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.store.list_tasks(scope_id="traveller-a", limit=invalid)

    def test_invalid_capacity_budget_is_rejected_without_accepting_work(self) -> None:
        for invalid in (0, -1, True, "1000"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.submit(max_database_bytes=invalid)
        self.assertEqual(self.store.list_tasks(scope_id="traveller-a"), [])

    def test_request_is_visible_to_a_fresh_python_process(self) -> None:
        first = self.submit()
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "continuity_lab",
                "--db",
                str(self.database),
                "list",
                "--scope",
                "traveller-a",
            ],
            check=True,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[1],
        )
        tasks = json.loads(result.stdout)
        self.assertEqual(first.task.task_id, tasks[0]["task_id"])
        self.assertEqual("queued", tasks[0]["status"])

    def test_cli_conflict_is_nonzero_and_preserves_request(self) -> None:
        first = self.submit()
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "continuity_lab",
                "--db",
                str(self.database),
                "submit",
                "--scope",
                "traveller-a",
                "--key",
                "request-001",
                "--booking",
                "DEMO-BK-001",
                "--check-in",
                "2030-12-11",
                "--confirm",
            ],
            capture_output=True,
            text=True,
            check=False,
            cwd=Path(__file__).resolve().parents[1],
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("different request", result.stderr)
        self.assertEqual([first.task], self.store.list_tasks(scope_id="traveller-a"))


if __name__ == "__main__":
    unittest.main()
