"""One-call worker safety and useful progress against independent real stores."""

import importlib
import json
import logging
import os
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock, patch

from continuity_lab.execution import ExecutionStore
from continuity_lab.execution_models import (
    AttemptStatus,
    ExecutionError,
    ExecutionStatus,
    FailureCode,
    TransitionConflict,
)
from continuity_lab.inquiry_worker import InquiryWorker, WorkerBusy, WorkerLockUnavailable
from continuity_lab.managed_inquiry_worker import ManagedInquiryWorker
from continuity_lab.migrations import migrate
from continuity_lab.models import BookingChange
from continuity_lab.supplier import FakeSupplier, InquiryCapabilities, initialize_supplier

ROOT = Path(__file__).resolve().parents[1]


class Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


class InquiryWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name).resolve()
        self.database = self.path / "execution.sqlite3"
        self.supplier_database = self.path / "supplier.sqlite3"
        migrate(self.database, self.path / "before.sqlite3")
        initialize_supplier(self.supplier_database, scope_id="account-a")
        self.executions = ExecutionStore(self.database)
        self.supplier = FakeSupplier(self.supplier_database)
        self.request = BookingChange("DEMO-BK-001", date(2030, 12, 10), True)
        self.before = self.supplier.booking(scope_id="account-a", booking_reference="DEMO-BK-001")
        self.capture = Capture()
        self.logger = logging.getLogger("continuity_lab.inquiry_worker")
        level, propagate = self.logger.level, self.logger.propagate
        self.logger.addHandler(self.capture)
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        self.addCleanup(self.logger.removeHandler, self.capture)
        self.addCleanup(self.logger.setLevel, level)
        self.addCleanup(setattr, self.logger, "propagate", propagate)

    def submit(self, *, key: str = "request-1", request: BookingChange | None = None):
        return self.executions.submit(
            scope_id="account-a", idempotency_key=key, request=request or self.request
        ).execution

    def assert_booking_unchanged(self) -> None:
        self.assertEqual(
            self.supplier.booking(scope_id="account-a", booking_reference="DEMO-BK-001"),
            self.before,
        )

    def test_available_inquiry_finishes_once_and_terminal_replay_is_quiet(self) -> None:
        accepted = self.submit()
        worker = InquiryWorker(self.executions, self.supplier)
        completed = worker.run_one(scope_id="account-a", task_id=accepted.task_id)
        self.assertEqual(completed.status, ExecutionStatus.SUCCEEDED)
        self.assertTrue(completed.result.available)
        self.assertEqual(completed.effect_id, accepted.effect_id)
        self.assertEqual(
            len(self.executions.attempts(scope_id="account-a", task_id=accepted.task_id)), 1
        )
        self.assertEqual(self.supplier.count_inquiries(scope_id="account-a"), 1)
        count = len(self.capture.records)
        self.assertEqual(worker.run_one(scope_id="account-a", task_id=accepted.task_id), completed)
        self.assertEqual(len(self.capture.records), count)
        self.assertEqual(self.supplier.count_inquiries(scope_id="account-a"), 1)
        self.assert_booking_unchanged()

    def test_unavailable_date_is_a_successful_investigation_without_mutation(self) -> None:
        accepted = self.submit(request=BookingChange("DEMO-BK-001", date(2030, 12, 25), True))
        result = InquiryWorker(self.executions, self.supplier).run_one(
            scope_id="account-a", task_id=accepted.task_id
        )
        self.assertEqual(result.status, ExecutionStatus.SUCCEEDED)
        self.assertFalse(result.result.available)
        self.assertIsNone(result.error_code)
        self.assert_booking_unchanged()

    def test_definitive_rejection_finishes_failed_and_does_not_repeat(self) -> None:
        accepted = self.submit(request=BookingChange("UNKNOWN", date(2030, 12, 10), True))
        worker = InquiryWorker(self.executions, self.supplier)
        result = worker.run_one(scope_id="account-a", task_id=accepted.task_id)
        self.assertEqual(
            (result.status, result.error_code),
            (ExecutionStatus.FAILED, FailureCode.INQUIRY_REJECTED),
        )
        self.assertIsNone(result.result)
        self.assertEqual(worker.run_one(scope_id="account-a", task_id=accepted.task_id), result)
        self.assertEqual(self.supplier.count_inquiries(scope_id="account-a"), 0)
        self.assertEqual(
            self.executions.attempts(scope_id="account-a", task_id=accepted.task_id)[0].status,
            AttemptStatus.FAILED,
        )
        self.assert_booking_unchanged()

    def test_external_inquiry_can_write_another_execution_without_a_held_db_lock(self) -> None:
        accepted = self.submit()
        executions, request = self.executions, self.request
        observations = []

        class IndependentWriteSupplier(FakeSupplier):
            def inquire(self, **kwargs):
                observations.append(
                    executions.submit(
                        scope_id="account-a", idempotency_key="other", request=request
                    ).execution
                )
                return super().inquire(**kwargs)

        result = InquiryWorker(
            self.executions, IndependentWriteSupplier(self.supplier_database)
        ).run_one(scope_id="account-a", task_id=accepted.task_id)
        self.assertEqual(result.status, ExecutionStatus.SUCCEEDED)
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].status, ExecutionStatus.ACCEPTED)
        self.assert_booking_unchanged()

    def test_second_cooperating_worker_is_refused_until_slot_released(self) -> None:
        accepted = self.submit()
        entered, release = Event(), Event()

        class HeldSupplier(FakeSupplier):
            def inquire(self, **kwargs):
                entered.set()
                if not release.wait(3):
                    raise AssertionError("Test supplier release was not observed")
                return super().inquire(**kwargs)

        worker = InquiryWorker(self.executions, HeldSupplier(self.supplier_database))
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(worker.run_one, scope_id="account-a", task_id=accepted.task_id)
            try:
                self.assertTrue(entered.wait(3))
                with self.assertRaises(WorkerBusy) as failure:
                    InquiryWorker(self.executions, self.supplier).run_one(
                        scope_id="account-a", task_id=accepted.task_id
                    )
                self.assertEqual(failure.exception.code, "capacity_exhausted")
            finally:
                release.set()
            result = pending.result(timeout=3)
        self.assertEqual(result.status, ExecutionStatus.SUCCEEDED)
        self.assertEqual(
            len(self.executions.attempts(scope_id="account-a", task_id=accepted.task_id)), 1
        )

    def test_unexpected_supplier_error_is_preserved_then_manual_recovery_progresses(self) -> None:
        accepted = self.submit()

        class PrivateFailure(RuntimeError):
            def __str__(self):
                raise AssertionError("Exception text must never be read")

            def __repr__(self):
                raise AssertionError("Exception repr must never be read")

        original = PrivateFailure("PRIVATE_SENTINEL raw SQL and booking")

        class BrokenSupplier(FakeSupplier):
            def inquire(self, **kwargs):
                raise original

        with self.assertRaises(PrivateFailure) as caught:
            InquiryWorker(self.executions, BrokenSupplier(self.supplier_database)).run_one(
                scope_id="account-a", task_id=accepted.task_id
            )
        self.assertIs(caught.exception, original)
        unfinished = self.executions.get(scope_id="account-a", task_id=accepted.task_id)
        self.assertEqual(unfinished.status, ExecutionStatus.RUNNING)
        self.assertIsNone(unfinished.error_code)
        result = InquiryWorker(self.executions, self.supplier).run_one(
            scope_id="account-a", task_id=accepted.task_id
        )
        self.assertEqual(result.status, ExecutionStatus.SUCCEEDED)
        attempts = self.executions.attempts(scope_id="account-a", task_id=accepted.task_id)
        self.assertEqual(
            [attempt.status for attempt in attempts],
            [AttemptStatus.INTERRUPTED, AttemptStatus.SUCCEEDED],
        )
        self.assertTrue(
            all(
                not record.exc_info and "PRIVATE_SENTINEL" not in record.getMessage()
                for record in self.capture.records
            )
        )

    def test_persisted_supplier_success_is_reconciled_under_original_effect(self) -> None:
        accepted = self.submit()
        names = []

        def after_supplier(name):
            names.append(name)
            raise RuntimeError("Simulated loss before local outcome commitment")

        with self.assertRaises(RuntimeError):
            InquiryWorker(self.executions, self.supplier, failpoint=after_supplier).run_one(
                scope_id="account-a", task_id=accepted.task_id
            )
        self.assertEqual(names, ["worker.after_supplier_success"])
        self.assertEqual(self.supplier.count_inquiries(scope_id="account-a"), 1)
        self.assertEqual(
            self.executions.get(scope_id="account-a", task_id=accepted.task_id).status,
            ExecutionStatus.RUNNING,
        )
        result = InquiryWorker(self.executions, self.supplier).run_one(
            scope_id="account-a", task_id=accepted.task_id
        )
        self.assertEqual(result.effect_id, accepted.effect_id)
        self.assertEqual(result.status, ExecutionStatus.SUCCEEDED)
        self.assertEqual(self.supplier.count_inquiries(scope_id="account-a"), 1)
        self.assertIn("inquiry_reconciled", [record.event for record in self.capture.records])
        self.assert_booking_unchanged()

    def test_manual_recovery_limit_preserves_inspectable_unfinished_state(self) -> None:
        accepted = self.submit()

        def incomplete(_):
            raise RuntimeError("Controlled incomplete outcome acknowledgement")

        worker = InquiryWorker(self.executions, self.supplier, failpoint=incomplete)
        for _ in range(8):
            with self.assertRaises(RuntimeError):
                worker.run_one(scope_id="account-a", task_id=accepted.task_id)
        with self.assertRaises(TransitionConflict):
            InquiryWorker(self.executions, self.supplier).run_one(
                scope_id="account-a", task_id=accepted.task_id
            )
        attempts = self.executions.attempts(scope_id="account-a", task_id=accepted.task_id)
        self.assertEqual(len(attempts), 8)
        self.assertEqual(attempts[-1].status, AttemptStatus.STARTED)
        self.assertEqual(
            self.executions.get(scope_id="account-a", task_id=accepted.task_id).status,
            ExecutionStatus.RUNNING,
        )
        self.assertEqual(self.supplier.count_inquiries(scope_id="account-a"), 1)
        self.assert_booking_unchanged()

    def test_stale_attempt_cannot_finalize_after_manual_state_replacement(self) -> None:
        accepted = self.submit()
        executions = self.executions

        def replace_attempt(_):
            current = executions.get(scope_id="account-a", task_id=accepted.task_id)
            executions.recover_attempt(
                scope_id="account-a", task_id=accepted.task_id, expected_version=current.version
            )

        with self.assertRaises(TransitionConflict):
            InquiryWorker(self.executions, self.supplier, failpoint=replace_attempt).run_one(
                scope_id="account-a", task_id=accepted.task_id
            )
        unfinished = self.executions.get(scope_id="account-a", task_id=accepted.task_id)
        self.assertEqual(unfinished.status, ExecutionStatus.RUNNING)
        self.assertIsNone(unfinished.result)
        result = InquiryWorker(self.executions, self.supplier).run_one(
            scope_id="account-a", task_id=accepted.task_id
        )
        self.assertEqual(result.status, ExecutionStatus.SUCCEEDED)
        self.assertEqual(self.supplier.count_inquiries(scope_id="account-a"), 1)

    def test_unsafe_lock_is_refused_before_any_attempt_or_effect(self) -> None:
        accepted = self.submit()
        worker = InquiryWorker(self.executions, self.supplier)
        target = self.path / "private-target"
        target.write_text("keep unchanged")
        worker.lock_path.symlink_to(target)
        with self.assertRaises(WorkerLockUnavailable):
            worker.run_one(scope_id="account-a", task_id=accepted.task_id)
        self.assertEqual(target.read_text(), "keep unchanged")
        worker.lock_path.unlink()
        worker.lock_path.write_text("")
        worker.lock_path.chmod(0o644)
        with self.assertRaises(WorkerLockUnavailable):
            worker.run_one(scope_id="account-a", task_id=accepted.task_id)
        self.assertEqual(
            self.executions.get(scope_id="account-a", task_id=accepted.task_id).status,
            ExecutionStatus.ACCEPTED,
        )
        self.assertEqual(
            self.executions.attempts(scope_id="account-a", task_id=accepted.task_id), ()
        )
        self.assertEqual(self.supplier.count_inquiries(scope_id="account-a"), 0)

    def test_database_hard_link_cannot_bypass_the_cooperative_worker_slot(self) -> None:
        accepted = self.submit()
        alias = self.path / "execution-alias.sqlite3"
        os.link(self.database, alias)
        worker = InquiryWorker(ExecutionStore(alias), self.supplier)
        with self.assertRaises(WorkerLockUnavailable):
            worker.run_one(scope_id="account-a", task_id=accepted.task_id)
        self.assertEqual(
            self.executions.attempts(scope_id="account-a", task_id=accepted.task_id), ()
        )
        self.assertEqual(self.supplier.count_inquiries(scope_id="account-a"), 0)

    def test_fatal_supplier_exception_propagates_and_releases_worker_lock(self) -> None:
        accepted = self.submit()

        class FatalFixture(BaseException):
            pass

        original = FatalFixture("PRIVATE_SENTINEL")

        class FatalSupplier(FakeSupplier):
            def inquire(self, **kwargs):
                raise original

        with self.assertRaises(FatalFixture) as caught:
            InquiryWorker(self.executions, FatalSupplier(self.supplier_database)).run_one(
                scope_id="account-a", task_id=accepted.task_id
            )
        self.assertIs(caught.exception, original)
        self.assertFalse(any(record.event == "worker_failed" for record in self.capture.records))
        recovered = InquiryWorker(self.executions, self.supplier).run_one(
            scope_id="account-a", task_id=accepted.task_id
        )
        self.assertEqual(recovered.status, ExecutionStatus.SUCCEEDED)

    def test_worker_events_have_fixed_safe_payloads_without_request_or_exception_data(self) -> None:
        accepted = self.submit()
        InquiryWorker(self.executions, self.supplier).run_one(
            scope_id="account-a", task_id=accepted.task_id
        )
        self.assertEqual(
            [(record.event, record.code) for record in self.capture.records],
            [("inquiry_dispatched", "ok"), ("worker_completed", "succeeded")],
        )
        for record in self.capture.records:
            self.assertFalse(record.exc_info)
            self.assertNotIn(accepted.task_id, record.getMessage())
            self.assertNotIn("account-a", record.getMessage())
            self.assertNotIn("DEMO-BK", record.getMessage())

    def test_cli_runs_one_inquiry_and_invalid_arguments_are_sanitized(self) -> None:
        accepted = self.submit()
        command = [
            sys.executable,
            "-m",
            "continuity_lab.inquiry_worker",
            "--db",
            str(self.database),
            "--supplier-db",
            str(self.supplier_database),
            "--scope",
            "account-a",
            "--task-id",
            accepted.task_id,
        ]
        result = subprocess.run(
            command,
            cwd=ROOT,
            env={"PATH": os.defpath, "PYTHONPATH": str(ROOT)},
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "succeeded")
        records = [json.loads(line) for line in result.stderr.splitlines()]
        self.assertTrue(
            {"inquiry_dispatched", "worker_completed"} <= {record["event"] for record in records}
        )
        self.assertTrue(all(record["service"] == "continuity-execution" for record in records))
        invalid = subprocess.run(
            command + ["--PRIVATE_SENTINEL"],
            cwd=ROOT,
            env={"PATH": os.defpath, "PYTHONPATH": str(ROOT)},
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(invalid.returncode, 2)
        self.assertNotIn("PRIVATE_SENTINEL", invalid.stdout + invalid.stderr)
        self.assertEqual(json.loads(invalid.stderr)["code"], "invalid_command")

    def test_cli_dependency_failure_does_not_reflect_private_path(self) -> None:
        accepted = self.submit()
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "continuity_lab.inquiry_worker",
                "--db",
                str(self.database),
                "--supplier-db",
                str(self.path / "PRIVATE_SENTINEL.sqlite3"),
                "--scope",
                "account-a",
                "--task-id",
                accepted.task_id,
            ],
            cwd=ROOT,
            env={"PATH": os.defpath, "PYTHONPATH": str(ROOT)},
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("PRIVATE_SENTINEL", result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["code"], "dependency_unavailable")


class InquiryDiagnosticContainmentTests(unittest.TestCase):
    """Observation failures cannot replace business results or primary failures."""

    helpers = (
        ("execution", "log"),
        ("inquiry_worker", "log"),
        ("managed_inquiry_worker", "log"),
        ("postgres_case", "info"),
        ("postgres_lifecycle", "info"),
        ("postgres_store", "log"),
        ("supplier", "log"),
        ("postgres_migrations", "info"),
    )

    def test_existing_event_boundaries_contain_logger_failure_without_swallowing_fatal_exit(self):
        for name, method in self.helpers:
            module = importlib.import_module("continuity_lab." + name)
            with self.subTest(module=name):
                with patch.object(module.LOGGER, method, side_effect=OSError("private sink")):
                    self.assertIsNone(module._event("diagnostic_fixture"))
                fatal = KeyboardInterrupt()
                with patch.object(module.LOGGER, method, side_effect=fatal):
                    with self.assertRaises(KeyboardInterrupt) as caught:
                        module._event("diagnostic_fixture")
                    self.assertIs(caught.exception, fatal)

    def test_managed_worker_returns_committed_success_when_completion_log_fails(self):
        from contextlib import nullcontext

        lifecycle = Mock()
        lifecycle.worker_slot.return_value = nullcontext()
        claim = SimpleNamespace(execution=SimpleNamespace(effect_id="effect", request="request"))
        lifecycle.claim_due.return_value = claim
        committed = object()
        lifecycle.finish_success.return_value = committed
        supplier = Mock(capabilities=InquiryCapabilities())
        result = object()
        supplier.lookup.return_value = SimpleNamespace(result=result)
        worker = ManagedInquiryWorker(lifecycle, supplier)

        def observe(_level, event, **_kwargs):
            if event == "managed_worker_completed":
                raise OSError("private sink")

        with patch("continuity_lab.managed_inquiry_worker.LOGGER.log", side_effect=observe):
            self.assertIs(worker.run_one(scope_id="scope", task_id="task"), committed)
        lifecycle.finish_success.assert_called_once_with(claim, result)
        supplier.inquire.assert_not_called()

    def test_managed_worker_preserves_primary_failure_with_hostile_code_and_failed_logger(self):
        from contextlib import nullcontext

        class PrimaryFailure(RuntimeError):
            @property
            def code(self):
                raise LookupError("private metadata")

        original = PrimaryFailure("private primary")
        lifecycle = Mock()
        lifecycle.worker_slot.return_value = nullcontext()
        lifecycle.claim_due.side_effect = original
        supplier = Mock(capabilities=InquiryCapabilities())
        worker = ManagedInquiryWorker(lifecycle, supplier)
        with (
            patch(
                "continuity_lab.managed_inquiry_worker.LOGGER.log",
                side_effect=OSError("private sink"),
            ),
            self.assertRaises(PrimaryFailure) as caught,
        ):
            worker.run_one(scope_id="scope", task_id="task")
        self.assertIs(caught.exception, original)
        supplier.lookup.assert_not_called()
        lifecycle.finish_success.assert_not_called()

    def test_inquiry_worker_preserves_primary_domain_failure_with_hostile_code_and_failed_logger(
        self,
    ):
        from contextlib import nullcontext

        class PrimaryFailure(ExecutionError):
            @property
            def code(self):
                raise LookupError("private metadata")

        original = PrimaryFailure("private primary")
        executions = Mock()
        executions.worker_slot.return_value = nullcontext()
        executions.get.side_effect = original
        supplier = Mock()
        worker = InquiryWorker(executions, supplier)
        with (
            patch("continuity_lab.inquiry_worker.LOGGER.log", side_effect=OSError("private sink")),
            self.assertRaises(PrimaryFailure) as caught,
        ):
            worker.run_one(scope_id="scope", task_id="task")
        self.assertIs(caught.exception, original)
        executions.start_attempt.assert_not_called()
        supplier.lookup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
