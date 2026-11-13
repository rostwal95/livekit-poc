"""Real independent workers prove the first read-only inquiry recovery boundary.

P1-04/P1-05 assertions inspect separate execution and supplier stores. These tests
make no claim about booking mutations, PostgreSQL leases or conversational media.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

from continuity_lab.execution import ExecutionStore
from continuity_lab.execution_models import AttemptStatus, ExecutionStatus, FailureCode
from continuity_lab.migrations import migrate
from continuity_lab.models import BookingChange
from continuity_lab.supplier import FakeSupplier, initialize_supplier
from harness.process_control import FileBarrier, OwnedProcess

ROOT = Path(__file__).resolve().parents[1]
SCOPE = "traveller-a"
BOOKING = "DEMO-BK-001"
REQUEST = BookingChange(BOOKING, date(2030, 12, 10), confirmed=True)
CHILD = r"""
import json
import sys
from dataclasses import asdict
from pathlib import Path

from continuity_lab.execution import ExecutionStore
from continuity_lab.inquiry_worker import InquiryWorker
from continuity_lab.supplier import FakeSupplier
from harness.process_control import FileBarrier

database, supplier_db, directory, mode, scope, task_id = sys.argv[1:]
barrier = FileBarrier(Path(directory), "after_supplier_success")

def failpoint(name):
    if mode == "after_supplier" and name == "worker.after_supplier_success":
        barrier.arrive_and_wait(timeout=20)

worker = InquiryWorker(
    ExecutionStore(Path(database)), FakeSupplier(Path(supplier_db)), failpoint=failpoint
)
record = worker.run_one(scope_id=scope, task_id=task_id)
print(json.dumps(asdict(record), default=str), flush=True)
"""


class InquiryAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.database = self.root / "executions.sqlite3"
        self.supplier_database = self.root / "supplier.sqlite3"
        migrate(self.database, self.root / "before-upgrade.sqlite3")
        initialize_supplier(self.supplier_database, scope_id=SCOPE)
        self.store = ExecutionStore(self.database)
        self.supplier = FakeSupplier(self.supplier_database)
        self.original_booking = self.supplier.booking(scope_id=SCOPE, booking_reference=BOOKING)
        self.sequence = 0

    def accept(self, *, request: BookingChange = REQUEST, key: str = "inquiry-001"):
        return self.store.submit(scope_id=SCOPE, idempotency_key=key, request=request).execution

    def child(self, task_id: str, *, mode: str = "normal") -> tuple[OwnedProcess, FileBarrier]:
        self.sequence += 1
        name = f"worker_{self.sequence}"
        state = self.root / name
        state.mkdir(mode=0o700)
        barrier = FileBarrier(state, "after_supplier_success")
        child = OwnedProcess(
            [
                sys.executable,
                "-c",
                CHILD,
                str(self.database),
                str(self.supplier_database),
                str(state),
                mode,
                SCOPE,
                task_id,
            ],
            cwd=ROOT,
            env={
                "PATH": os.environ.get("PATH", ""),
                "PYTHONPATH": str(ROOT),
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            output_directory=self.root / f"{name}_output",
            max_output_bytes=16_384,
        )
        self.addCleanup(child.close)
        return child, barrier

    def finished(self, child: OwnedProcess) -> dict:
        result = child.wait(timeout=10)
        self.assertEqual(result.returncode, 0, child.output_tail("stderr"))
        output = child.output_tail("stdout")
        self.assertEqual(len(output.splitlines()), 1, "One completed worker result is required")
        return json.loads(output)

    def assert_booking_unchanged(self) -> None:
        self.assertEqual(
            FakeSupplier(self.supplier_database).booking(scope_id=SCOPE, booking_reference=BOOKING),
            self.original_booking,
        )

    def test_p1_04_independent_worker_persists_inquiry_and_leaves_booking_unchanged(self) -> None:
        accepted = self.accept()
        child, _ = self.child(accepted.task_id)
        with child:
            returned = self.finished(child)
        persisted = ExecutionStore(self.database).get(scope_id=SCOPE, task_id=accepted.task_id)
        self.assertEqual(returned["task_id"], accepted.task_id)
        self.assertEqual(returned["effect_id"], accepted.effect_id)
        self.assertEqual(returned["status"], "succeeded")
        self.assertEqual(persisted.status, ExecutionStatus.SUCCEEDED)
        self.assertEqual(persisted.effect_id, accepted.effect_id)
        self.assertEqual(persisted.request, REQUEST)
        self.assertIsNotNone(persisted.result)
        self.assertTrue(persisted.result.available)
        self.assertEqual(persisted.result.booking_reference, BOOKING)
        self.assertEqual(persisted.result.new_check_in, REQUEST.new_check_in)
        observation = FakeSupplier(self.supplier_database).lookup(
            scope_id=SCOPE, effect_id=accepted.effect_id, request=REQUEST
        )
        self.assertIsNotNone(observation)
        self.assertEqual(observation.effect_id, accepted.effect_id)
        self.assertEqual(observation.result, persisted.result)
        self.assertEqual(self.supplier.count_inquiries(scope_id=SCOPE), 1)
        [attempt] = self.store.attempts(scope_id=SCOPE, task_id=accepted.task_id)
        self.assertEqual(attempt.status, AttemptStatus.SUCCEEDED)
        self.assertIsNotNone(attempt.finished_at)
        self.assert_booking_unchanged()

    def test_p1_05_new_process_recovers_original_supplier_effect_after_actual_kill(self) -> None:
        accepted = self.accept()
        child, barrier = self.child(accepted.task_id, mode="after_supplier")
        with child:
            child.wait_for_barrier(barrier, timeout=10)
            self.assertIsNone(child.returncode)
            interrupted = ExecutionStore(self.database).get(
                scope_id=SCOPE, task_id=accepted.task_id
            )
            self.assertEqual(interrupted.status, ExecutionStatus.RUNNING)
            self.assertIsNone(interrupted.result)
            self.assertEqual(interrupted.effect_id, accepted.effect_id)
            [first_attempt] = self.store.attempts(scope_id=SCOPE, task_id=accepted.task_id)
            self.assertEqual(first_attempt.status, AttemptStatus.STARTED)
            supplier_before = FakeSupplier(self.supplier_database).lookup(
                scope_id=SCOPE, effect_id=accepted.effect_id, request=REQUEST
            )
            self.assertIsNotNone(supplier_before, "Supplier evidence must exist before the crash")
            self.assertEqual(self.supplier.count_inquiries(scope_id=SCOPE), 1)
            self.assert_booking_unchanged()
            termination = child.kill(timeout=3)
            self.assertTrue(termination.killed)
            self.assertEqual(termination.returncode, -signal.SIGKILL)
            self.assertEqual(child.wait(timeout=3).returncode, -signal.SIGKILL)
            self.assertEqual(child.output_tail("stdout"), "", "No local completion was returned")
        # The original worker is reaped before a distinct process attempts takeover.
        replacement, _ = self.child(accepted.task_id)
        self.assertIsNot(replacement, child)
        self.assertEqual(child.returncode, -signal.SIGKILL)
        with replacement:
            returned = self.finished(replacement)
        recovered = ExecutionStore(self.database).get(scope_id=SCOPE, task_id=accepted.task_id)
        self.assertEqual(returned["task_id"], accepted.task_id)
        self.assertEqual(recovered.status, ExecutionStatus.SUCCEEDED)
        self.assertEqual(recovered.task_id, accepted.task_id)
        self.assertEqual(recovered.effect_id, accepted.effect_id)
        self.assertEqual(recovered.request, REQUEST)
        self.assertEqual(recovered.result, supplier_before.result)
        self.assertGreater(recovered.version, interrupted.version)
        self.assertEqual(FakeSupplier(self.supplier_database).count_inquiries(scope_id=SCOPE), 1)
        attempts = self.store.attempts(scope_id=SCOPE, task_id=accepted.task_id)
        self.assertEqual([attempt.attempt_no for attempt in attempts], [1, 2])
        self.assertEqual(
            [attempt.status for attempt in attempts],
            [AttemptStatus.INTERRUPTED, AttemptStatus.SUCCEEDED],
        )
        self.assertNotEqual(attempts[0].attempt_id, attempts[1].attempt_id)
        self.assertTrue(all(attempt.finished_at is not None for attempt in attempts))
        self.assert_booking_unchanged()
        repeated, _ = self.child(accepted.task_id)
        with repeated:
            self.finished(repeated)
        self.assertEqual(self.store.get(scope_id=SCOPE, task_id=accepted.task_id), recovered)
        self.assertEqual(self.store.attempts(scope_id=SCOPE, task_id=accepted.task_id), attempts)
        self.assertEqual(self.supplier.count_inquiries(scope_id=SCOPE), 1)
        self.assert_booking_unchanged()

    def test_unavailable_inquiry_is_a_successful_read_only_result(self) -> None:
        request = BookingChange(BOOKING, date(2030, 12, 25), confirmed=True)
        accepted = self.accept(request=request)
        child, _ = self.child(accepted.task_id)
        with child:
            self.finished(child)
        persisted = self.store.get(scope_id=SCOPE, task_id=accepted.task_id)
        self.assertEqual(persisted.status, ExecutionStatus.SUCCEEDED)
        self.assertIsNotNone(persisted.result)
        self.assertFalse(persisted.result.available)
        self.assertEqual(persisted.result.new_check_in, request.new_check_in)
        self.assertIsNone(persisted.error_code)
        self.assertEqual(self.supplier.count_inquiries(scope_id=SCOPE), 1)
        self.assert_booking_unchanged()

    def test_supplier_rejection_is_persisted_and_other_valid_work_still_progresses(self) -> None:
        rejected_request = BookingChange("UNKNOWN-BOOKING", date(2030, 12, 10), confirmed=True)
        rejected = self.accept(request=rejected_request)
        failed, _ = self.child(rejected.task_id)
        with failed:
            self.finished(failed)
        outcome = self.store.get(scope_id=SCOPE, task_id=rejected.task_id)
        self.assertEqual(outcome.status, ExecutionStatus.FAILED)
        self.assertEqual(outcome.error_code, FailureCode.INQUIRY_REJECTED)
        self.assertIsNone(outcome.result)
        self.assertEqual(self.supplier.count_inquiries(scope_id=SCOPE), 0)
        self.assert_booking_unchanged()
        accepted = self.accept(key="valid-after-rejection")
        succeeding, _ = self.child(accepted.task_id)
        with succeeding:
            self.finished(succeeding)
        self.assertEqual(
            self.store.get(scope_id=SCOPE, task_id=accepted.task_id).status,
            ExecutionStatus.SUCCEEDED,
        )
        self.assertEqual(self.supplier.count_inquiries(scope_id=SCOPE), 1)
        self.assert_booking_unchanged()


if __name__ == "__main__":
    unittest.main()
