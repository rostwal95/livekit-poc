"""Process evidence requires real owned children and explicit persisted barriers."""

import json
import os
import signal
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from harness.process_control import (
    FileBarrier,
    ManualClock,
    OwnedProcess,
    ProcessControlError,
    ProcessExited,
    ProcessOutputLimit,
    ProcessTimeout,
    UnsafeHarnessPath,
)

ROOT = Path(__file__).resolve().parents[1]


class ProcessControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve()
        self.counter = 0
        self.environment = {"PATH": os.defpath, "PYTHONPATH": str(ROOT)}

    def child(self, script: str, *, limit: int = 65_536) -> OwnedProcess:
        self.counter += 1
        return OwnedProcess(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=self.environment,
            output_directory=self.directory / f"child-{self.counter}",
            max_output_bytes=limit,
        )

    def barrier_script(self, name: str = "committed", *, before: str = "") -> str:
        return (
            "from pathlib import Path\nfrom harness.process_control import FileBarrier\n"
            + before
            + f"FileBarrier(Path({json.dumps(str(self.directory))}), {name!r}).arrive_and_wait(timeout=10)\n"
            + "print('released', flush=True)\n"
        )

    def test_normal_child_capture_and_reap(self) -> None:
        with self.child(
            "import os; os.write(1, b'safe stdout'); os.write(2, b'safe stderr')"
        ) as child:
            result = child.wait(timeout=3)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.pid, child.pid)
            self.assertEqual(child.output_tail("stdout"), "safe stdout")
            self.assertEqual(child.output_tail("stderr"), "safe stderr")
        self.assertEqual(child.returncode, 0)
        self.assertFalse(child.cleanup_failed)

    def test_barrier_normal_release_makes_progress(self) -> None:
        barrier = FileBarrier(self.directory, "committed")
        with self.child(self.barrier_script()) as child:
            child.wait_for_barrier(barrier, timeout=3)
            self.assertIsNone(child.returncode)
            child.release_barrier(barrier)
            self.assertEqual(child.wait(timeout=3).returncode, 0)
            self.assertEqual(child.output_tail("stdout"), "released\n")

    def test_barrier_observation_then_actual_sigkill_and_reap(self) -> None:
        barrier = FileBarrier(self.directory, "committed")
        with self.child(self.barrier_script(before="print('before kill', flush=True)\n")) as child:
            child.wait_for_barrier(barrier, timeout=3)
            result = child.kill(timeout=3)
            self.assertTrue(result.killed)
            self.assertEqual(result.pid, child.pid)
            self.assertEqual(result.returncode, -signal.SIGKILL)
            self.assertEqual(child.returncode, -signal.SIGKILL)
            self.assertEqual(child.output_tail("stdout"), "before kill\n")
            with self.assertRaises(ProcessExited):
                child.kill()
        self.assertFalse(child.cleanup_failed)

    def test_marker_from_an_exited_child_cannot_pass_live_barrier(self) -> None:
        barrier = FileBarrier(self.directory, "committed")
        script = (
            "import os\nfrom pathlib import Path\n"
            + f"Path({str(self.directory / 'committed.reached')!r}).write_text(str(os.getpid()) + '\\n')\n"
        )
        with self.child(script) as child:
            self.assertEqual(child.wait(timeout=3).returncode, 0)
            with self.assertRaises(ProcessExited):
                child.wait_for_barrier(barrier, timeout=1)

    def test_missing_barrier_timeout_is_not_success_and_context_reaps(self) -> None:
        barrier = FileBarrier(self.directory, "never_reached")
        child = self.child("import time; time.sleep(10)")
        with self.assertRaises(ProcessTimeout), child:
            child.wait_for_barrier(barrier, timeout=0.05)
        self.assertEqual(child.returncode, -signal.SIGKILL)
        self.assertTrue(child.termination.killed)

    def test_child_wait_timeout_reaps_without_hiding_original_failure(self) -> None:
        child = self.child("import time; time.sleep(10)")
        with self.assertRaises(ProcessTimeout), child:
            child.wait(timeout=0.05)
        self.assertEqual(child.returncode, -signal.SIGKILL)

    def test_child_exit_failure_is_preserved_and_cannot_claim_kill(self) -> None:
        with self.child("raise SystemExit(7)") as child:
            self.assertEqual(child.wait(timeout=3).returncode, 7)
            with self.assertRaises(ProcessExited):
                child.kill()
        self.assertIsNone(child.termination)

    def test_context_cleanup_reaps_child_when_caller_raises(self) -> None:
        child = self.child("import time; time.sleep(10)")
        original = RuntimeError("original fixture failure")
        with self.assertRaises(RuntimeError) as caught, child:
            raise original
        self.assertIs(caught.exception, original)
        self.assertEqual(child.returncode, -signal.SIGKILL)
        child.close()

    def test_cleanup_failure_is_reported_without_replacing_fixture_failure(self) -> None:
        child = self.child("print('done')")
        child.wait(timeout=3)
        original = RuntimeError("original fixture failure")
        with (
            patch.object(child, "close", side_effect=OSError("synthetic cleanup failure")),
            self.assertRaises(RuntimeError) as caught,
            child,
        ):
            raise original
        self.assertIs(caught.exception, original)
        self.assertTrue(child.cleanup_failed)
        self.assertIn("Owned process cleanup did not complete", original.__notes__)
        child.close()

    def test_output_capture_is_byte_capped_and_overflow_cannot_pass(self) -> None:
        child = self.child("import os; os.write(1, b'x' * 200000)", limit=1024)
        with self.assertRaises(ProcessOutputLimit), child:
            child.wait(timeout=3)
        self.assertLessEqual((child.output_directory / "stdout.bin").stat().st_size, 1024)
        self.assertIsNotNone(child.returncode)
        self.assertFalse(child.cleanup_failed)

    def test_both_streams_drain_without_pipe_deadlock(self) -> None:
        script = "import os\nfor _ in range(100):\n os.write(1,b'o'*512)\n os.write(2,b'e'*512)\n"
        with self.child(script) as child:
            self.assertEqual(child.wait(timeout=3).returncode, 0)
            for stream, expected in (("stdout", "o"), ("stderr", "e")):
                tail = child.output_tail(stream, maximum_bytes=1024)
                self.assertEqual(tail, expected * 1024)

    def test_tail_redacts_secret_crossing_the_requested_boundary(self) -> None:
        secret = "SYNTHETIC_SECRET_SENTINEL"
        script = f"import os; os.write(1, b'x'*100 + {secret.encode()!r} + b'y'*100)"
        with self.child(script) as child:
            self.assertEqual(child.wait(timeout=3).returncode, 0)
            tail = child.output_tail("stdout", maximum_bytes=110, redact_values=[secret])
            self.assertNotIn(secret, tail)
            self.assertNotIn("SENTINEL", tail)
            self.assertIn("[redacted]", tail)
            self.assertLessEqual(len(tail.encode()), 110)
            self.assertEqual((child.output_directory / "stdout.bin").stat().st_mode & 0o777, 0o600)

    def test_marker_pid_must_match_owned_child(self) -> None:
        barrier = FileBarrier(self.directory, "committed")
        (self.directory / "committed.reached").write_text("999999999\n")
        with self.child("import time; time.sleep(10)") as child:
            with self.assertRaises(ProcessControlError):
                child.wait_for_barrier(barrier, timeout=1)
            with self.assertRaises(ProcessControlError):
                child.release_barrier(barrier)

    def test_unsafe_names_symlink_directory_and_stale_marker_fail(self) -> None:
        for name in ("../escape", "", "point/name", "Upper", "x" * 65):
            with self.subTest(name=name), self.assertRaises(ValueError):
                FileBarrier(self.directory, name)
        link = self.directory / "link"
        link.symlink_to(self.directory, target_is_directory=True)
        with self.assertRaises(UnsafeHarnessPath):
            FileBarrier(link, "safe")
        (self.directory / "stale.reached").write_text("1\n")
        with self.assertRaises(UnsafeHarnessPath):
            FileBarrier(self.directory, "stale")

    def test_symlink_marker_and_symlink_output_reads_are_rejected(self) -> None:
        barrier = FileBarrier(self.directory, "committed")
        target = self.directory / "other"
        target.write_text("1\n")
        (self.directory / "committed.reached").symlink_to(target)
        with (
            self.child("import time; time.sleep(10)") as child,
            self.assertRaises(UnsafeHarnessPath),
        ):
            child.wait_for_barrier(barrier, timeout=1)
        with self.child("print('done')") as child:
            child.wait(timeout=3)
            path = child.output_directory / "stdout.bin"
            path.unlink()
            path.symlink_to(target)
            with self.assertRaises(UnsafeHarnessPath):
                child.output_tail("stdout")

    def test_invalid_duration_output_and_environment_do_not_start_a_child(self) -> None:
        with self.child("print('ok')") as child:
            for duration in (0, -1, True, float("nan"), float("inf"), 301):
                with self.subTest(duration=duration), self.assertRaises(ValueError):
                    child.wait(timeout=duration)
            self.assertEqual(child.wait(timeout=3).returncode, 0)
            for size in (0, True, 8193):
                with self.subTest(size=size), self.assertRaises(ValueError):
                    child.output_tail("stdout", maximum_bytes=size)
        with self.assertRaises(ValueError):
            OwnedProcess(
                [sys.executable],
                cwd=ROOT,
                env={"BAD=KEY": "x"},
                output_directory=self.directory / "invalid",
            )
        self.assertFalse((self.directory / "invalid").exists())


class ManualClockTests(unittest.TestCase):
    def test_utc_and_monotonic_advance_without_sleeping(self) -> None:
        start = datetime(2030, 1, 1, tzinfo=UTC)
        clock = ManualClock(start, monotonic_seconds=1_000_000)
        clock.advance(86_400.25)
        self.assertEqual(clock.now(), start + timedelta(seconds=86_400.25))
        self.assertEqual(clock.monotonic(), 1_086_400.25)
        clock.advance(0)
        self.assertEqual(clock.monotonic(), 1_086_400.25)

    def test_invalid_clock_values_and_overflow_preserve_original_state(self) -> None:
        for value in (
            datetime(2030, 1, 1),
            datetime(2030, 1, 1, tzinfo=timezone(timedelta(hours=1))),
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ManualClock(value)
        start = datetime(2030, 1, 1, tzinfo=UTC)
        clock = ManualClock(start)
        for seconds in (-1, True, float("nan"), float("inf"), 1e300):
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                clock.advance(seconds)
            self.assertEqual(clock.now(), start)
            self.assertEqual(clock.monotonic(), 0)


if __name__ == "__main__":
    unittest.main()
