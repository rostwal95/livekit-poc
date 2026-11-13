"""P1 acceptance uses real accepting processes and inspected persistent identities.

These tests cover the SQLite inquiry subset only. They do not establish supplier
execution, worker recovery, authenticated actor derivation or PostgreSQL leases.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import tempfile
import unittest
from contextlib import ExitStack
from datetime import date
from pathlib import Path

from continuity_lab.execution import ExecutionStore
from continuity_lab.migrations import migrate
from continuity_lab.models import BookingChange
from harness.process_control import FileBarrier, OwnedProcess

ROOT = Path(__file__).resolve().parents[1]
REQUEST = BookingChange("DEMO-BK-001", date(2030, 12, 10), confirmed=True)
CHILD = r"""
import json
import sys
from datetime import date
from pathlib import Path

from continuity_lab.execution import ExecutionStore
from continuity_lab.models import BookingChange, IdempotencyConflict
from harness.process_control import FileBarrier

database, directory, barrier_name, mode, scope, key, check_in = sys.argv[1:]
barrier = FileBarrier(Path(directory), barrier_name)
if mode == "before_submit":
    barrier.arrive_and_wait(timeout=20)

def failpoint(name):
    if mode == "before_commit" and name == "execution.before_accept_commit":
        barrier.arrive_and_wait(timeout=20)
    if mode == "after_commit" and name == "execution.after_accept_commit":
        barrier.arrive_and_wait(timeout=20)

store = ExecutionStore(Path(database), failpoint=failpoint)
try:
    result = store.submit(
        scope_id=scope,
        idempotency_key=key,
        request=BookingChange("DEMO-BK-001", date.fromisoformat(check_in), confirmed=True),
    )
except IdempotencyConflict:
    print(json.dumps({"code": "idempotency_conflict"}), flush=True)
    raise SystemExit(2)

record = result.execution
print(json.dumps({
    "task_id": record.task_id,
    "effect_id": record.effect_id,
    "scope_id": record.scope_id,
    "request": record.request.payload(),
    "created": result.created,
    "enrolled": result.enrolled,
}), flush=True)
if mode == "after_ack":
    barrier.arrive_and_wait(timeout=20)
"""


class ExecutionAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        # macOS may expose /var through a symlink; helper state uses its physical path.
        self.root = Path(self.directory.name).resolve()
        self.database = self.root / "executions.sqlite3"
        migrate(self.database, self.root / "before-upgrade.sqlite3")
        self.store = ExecutionStore(self.database)
        self.sequence = 0

    def child(
        self,
        *,
        mode: str = "normal",
        scope: str = "traveller-a",
        key: str = "acceptance-001",
        check_in: str = "2030-12-10",
    ) -> tuple[OwnedProcess, FileBarrier]:
        self.sequence += 1
        name = f"child_{self.sequence}"
        state = self.root / name
        state.mkdir(mode=0o700)
        barrier = FileBarrier(state, "acceptance")
        child = OwnedProcess(
            [
                sys.executable,
                "-c",
                CHILD,
                str(self.database),
                str(state),
                "acceptance",
                mode,
                scope,
                key,
                check_in,
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

    def acknowledgement(self, child: OwnedProcess, *, exit_code: int = 0) -> dict:
        result = child.wait(timeout=10)
        self.assertEqual(result.returncode, exit_code, child.output_tail("stderr"))
        output = child.output_tail("stdout")
        self.assertEqual(len(output.splitlines()), 1, "Exactly one acknowledgement is required")
        return json.loads(output)

    def assert_killed(self, child: OwnedProcess) -> None:
        termination = child.kill(timeout=3)
        self.assertTrue(termination.killed)
        self.assertEqual(termination.returncode, -signal.SIGKILL)
        self.assertEqual(child.wait(timeout=3).returncode, -signal.SIGKILL)

    def test_p1_01_acknowledged_request_survives_actual_intake_process_kill(self) -> None:
        child, barrier = self.child(mode="after_ack")
        with child:
            child.wait_for_barrier(barrier, timeout=10)
            self.assertIsNone(child.returncode)
            self.assert_killed(child)
            acknowledgement = json.loads(child.output_tail("stdout"))
        self.assertTrue(acknowledgement["created"])
        self.assertTrue(acknowledgement["enrolled"])
        recovered = ExecutionStore(self.database).get(
            scope_id="traveller-a", task_id=acknowledgement["task_id"]
        )
        self.assertEqual(recovered.task_id, acknowledgement["task_id"])
        self.assertEqual(recovered.effect_id, acknowledgement["effect_id"])
        self.assertEqual(recovered.request, REQUEST)
        self.assertEqual(recovered.request.payload(), acknowledgement["request"])
        self.assertEqual(recovered.version, 0)
        self.assertEqual(
            len(self.store.attempts(scope_id="traveller-a", task_id=recovered.task_id)), 0
        )

    def test_p1_02_concurrent_processes_acknowledge_one_logical_workflow(self) -> None:
        children = [self.child(mode="before_submit") for _ in range(6)]
        with ExitStack() as cleanup:
            for child, barrier in children:
                cleanup.enter_context(child)
                child.wait_for_barrier(barrier, timeout=10)
            # Every accepting process has reached the same pre-submit boundary.
            for child, barrier in children:
                child.release_barrier(barrier)
            results = [self.acknowledgement(child) for child, _ in children]
        self.assertEqual(sum(result["created"] for result in results), 1)
        self.assertEqual(sum(result["enrolled"] for result in results), 1)
        self.assertEqual(len({result["task_id"] for result in results}), 1)
        self.assertEqual(len({result["effect_id"] for result in results}), 1)
        self.assertTrue(all(result["request"] == REQUEST.payload() for result in results))
        persisted = self.store.list(scope_id="traveller-a", limit=100)
        self.assertEqual(len(persisted), 1)
        self.assertEqual(persisted[0].task_id, results[0]["task_id"])

    def test_p1_02_postcommit_preack_kill_replays_original_identity(self) -> None:
        child, barrier = self.child(mode="after_commit")
        with child:
            child.wait_for_barrier(barrier, timeout=10)
            committed = self.store.list(scope_id="traveller-a", limit=100)
            self.assertEqual(len(committed), 1)
            original = committed[0]
            self.assert_killed(child)
            self.assertEqual(child.output_tail("stdout"), "", "No acknowledgement was delivered")
        replay = ExecutionStore(self.database).submit(
            scope_id="traveller-a", idempotency_key="acceptance-001", request=REQUEST
        )
        self.assertFalse(replay.created)
        self.assertFalse(replay.enrolled)
        self.assertEqual(replay.execution.task_id, original.task_id)
        self.assertEqual(replay.execution.effect_id, original.effect_id)
        self.assertEqual(replay.execution.request, original.request)
        self.assertEqual(len(self.store.list(scope_id="traveller-a", limit=100)), 1)

    def test_precommit_kill_acknowledges_nothing_and_rolls_back_the_request(self) -> None:
        child, barrier = self.child(mode="before_commit")
        with child:
            child.wait_for_barrier(barrier, timeout=10)
            self.assert_killed(child)
            self.assertEqual(child.output_tail("stdout"), "")
        self.assertEqual(len(self.store.list(scope_id="traveller-a", limit=100)), 0)
        admitted = self.store.submit(
            scope_id="traveller-a", idempotency_key="acceptance-001", request=REQUEST
        )
        self.assertTrue(admitted.created, "A legitimate retry must still make useful progress")
        self.assertTrue(admitted.enrolled)
        self.assertEqual(admitted.execution.request, REQUEST)

    def test_p1_03_altered_replay_conflicts_and_another_scope_stays_independent(self) -> None:
        child, _ = self.child()
        with child:
            original = self.acknowledgement(child)
        changed, _ = self.child(check_in="2030-12-11")
        with changed:
            conflict = self.acknowledgement(changed, exit_code=2)
        self.assertEqual(conflict, {"code": "idempotency_conflict"})
        other, _ = self.child(scope="traveller-b")
        with other:
            independent = self.acknowledgement(other)
        self.assertNotEqual(independent["task_id"], original["task_id"])
        self.assertNotEqual(independent["effect_id"], original["effect_id"])
        self.assertEqual(independent["scope_id"], "traveller-b")
        self.assertTrue(independent["created"])
        self.assertTrue(independent["enrolled"])
        preserved = self.store.get(scope_id="traveller-a", task_id=original["task_id"])
        self.assertEqual(preserved.request, REQUEST)
        self.assertEqual(preserved.effect_id, original["effect_id"])
        self.assertEqual(len(self.store.list(scope_id="traveller-a", limit=100)), 1)
        self.assertEqual(len(self.store.list(scope_id="traveller-b", limit=100)), 1)


if __name__ == "__main__":
    unittest.main()
