"""Scoped package ownership/budget probes, reviewed 12 November 2026.

Actual small local Python children test lifetime boundaries. The synthetic report
case checks metadata only; it is not a package build, provider or PG qualification.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "local-setup/scripts"))
import p3_document_package as scoped
from p3_document_evidence import digest, json_bytes, write_private

from harness.process_control import FileBarrier


class ScopedPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            prefix="scoped-document-package-unit-", dir="/private/tmp"
        )
        self.root = Path(self.temp.name)
        self.outer = {"children": 0, "capture": 0, "reserved": 0}
        self.options = {
            "outer_children": lambda: self.outer["children"],
            "outer_capture": lambda: self.outer["capture"],
            "outer_reservations": lambda: self.outer["reserved"],
            "deadline": time.monotonic() + 45,
            "final_deadline": time.monotonic() + 60,
        }
        with patch.object(scoped.packages.shutil, "which", return_value=sys.executable):
            self.run = scoped.ScopedPackageRun(self.root, self.root / "nested.json", **self.options)

    def tearDown(self):
        for child in self.run.children:
            if hasattr(child, "close"):
                child.close()
        if self.run.work.exists():
            try:
                self.run.cleanup_resources()
            except scoped.packages.GateError:
                if self.run.work.exists() and self.run.children_settled():
                    shutil.rmtree(self.run.work)
        self.temp.cleanup()

    def held_child(self):
        barrier = FileBarrier(self.run.work, "direct_held")
        code = (
            "import os,time;"
            f"p={str(self.run.work / 'direct_held.reached')!r};"
            "fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);"
            'os.write(fd,(str(os.getpid())+"\\n").encode());os.close(fd);time.sleep(30)'
        )
        child = self.run.start([sys.executable, "-I", "-c", code], stage="imports")
        child.wait_for_barrier(barrier, timeout=5)
        return child

    def test_one_live_direct_child_survives_false_close_but_keeps_reservation_and_work(self):
        child = self.held_child()
        reserved = self.run.reservations[child.pid]
        with (
            patch.object(child, "close", return_value=None),
            self.assertRaises(scoped.packages.GateError),
        ):
            self.run.cleanup_resources()
        self.assertIsNone(child.returncode)
        self.assertIn(child, self.run.children)
        self.assertEqual(self.run.reservations[child.pid], reserved)
        self.assertTrue(self.run.work.exists())
        self.assertTrue((self.run.retained / "unresolved-work.json").is_file())
        self.assertFalse(self.run.children_settled())
        child.close()
        self.assertIsInstance(child.returncode, int)
        self.run.cleanup_resources()
        self.assertTrue(self.run.children_settled())
        self.assertFalse(self.run.work.exists())

    def compiler_like_child(self, *, leave_parent=False):
        barrier = FileBarrier(self.run.work, "compiler_held")
        grandchild_pid = self.run.work / "compiler-grandchild.pid"
        code = (
            "import os,subprocess,sys,time;"
            "child=subprocess.Popen([sys.executable,'-I','-c','import time;time.sleep(30)'],"
            "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);"
            f"fd=os.open({str(grandchild_pid)!r},os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);"
            "os.write(fd,(str(child.pid)+'\\n').encode());os.close(fd);"
        )
        if not leave_parent:
            code += (
                f"fd=os.open({str(self.run.work / 'compiler_held.reached')!r},"
                "os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);"
                "os.write(fd,(str(os.getpid())+'\\n').encode());os.close(fd);time.sleep(30)"
            )
        child = self.run.start([sys.executable, "-I", "-c", code], stage="node_types")
        if not leave_parent:
            child.wait_for_barrier(barrier, timeout=5)
        return child, grandchild_pid

    def assert_pid_gone(self, pid):
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_complete_marker_two_link_publication_window_is_awaited_not_accepted(self):
        child = self.held_child()
        marker = child.output_directory / "process-group.pid"
        pending = marker.with_name(marker.name + ".pending")
        os.link(marker, pending)

        def finish_publication():
            time.sleep(0.03)
            pending.unlink()

        writer = threading.Thread(target=finish_publication)
        writer.start()
        try:
            child.close()
            self.assertFalse(pending.exists())
            self.assertTrue(child.group_settled)
            self.assertEqual(marker.stat().st_nlink, 1)
        finally:
            writer.join(timeout=2)
            self.assertFalse(writer.is_alive())

    def test_group_confirmation_failure_cannot_hide_a_spawned_unregistered_owner(self):
        with patch.object(
            scoped.GroupedOwnedProcess,
            "_confirm_group",
            side_effect=scoped.ProcessControlError("unconfirmed_group"),
        ) as confirm:
            child = self.held_child()
            confirm.assert_not_called()  # Constructor is spawn-only, not observation.
            self.assertIn(child, self.run.children)
            self.assertIsNone(child.returncode)
            reservation = self.run.reservations[child.pid]
            with self.assertRaises(scoped.ProcessControlError):
                self.run.cleanup_resources()
        self.assertIn(child, self.run.children)
        self.assertTrue(child.cleanup_failed)
        self.assertEqual(self.run.reservations[child.pid], reservation)
        self.assertTrue(self.run.work.exists())
        child.close()
        self.assertTrue(child.group_settled)
        self.run.cleanup_resources()
        self.assertFalse(self.run.work.exists())

    def test_actual_compiler_parent_and_grandchild_are_closed_and_group_is_absent(self):
        child, pid_file = self.compiler_like_child()
        grandchild = int(pid_file.read_text())
        self.assertEqual(os.getpgid(grandchild), child.pid)
        self.assertNotEqual(child.pid, os.getpgrp())
        child.close()
        self.assertIsInstance(child.returncode, int)
        self.assertTrue(child.group_settled)
        self.assertFalse(child.cleanup_failed)
        self.assert_pid_gone(grandchild)
        with self.assertRaises(ProcessLookupError):
            os.killpg(child.pid, 0)
        self.run.capture(child)
        self.assertNotIn(child.pid, self.run.reservations)

    def test_verified_leader_sigkill_also_settles_its_compiler_group(self):
        child, pid_file = self.compiler_like_child()
        terminated = child.kill(timeout=3)
        self.assertEqual(terminated.pid, child.pid)
        self.assertTrue(terminated.killed)
        self.assertEqual(terminated.returncode, -9)
        self.assertTrue(child.group_settled)
        self.assert_pid_gone(int(pid_file.read_text()))
        child.close()
        self.assertFalse(child.cleanup_failed)

    def test_false_close_after_leader_exit_cannot_hide_retained_descendant(self):
        child, pid_file = self.compiler_like_child(leave_parent=True)
        deadline = time.monotonic() + 3
        while child.returncode is None and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertEqual(child.returncode, 0)
        self.assertTrue(child.cleanup_failed)
        self.assertFalse(child.group_settled)
        grandchild = int(pid_file.read_text())
        reservation = self.run.reservations[child.pid]
        with (
            patch.object(child, "close", return_value=None),
            self.assertRaises(scoped.packages.GateError),
        ):
            self.run.cleanup_resources()
        self.assertTrue(self.run.work.exists())
        self.assertEqual(self.run.reservations[child.pid], reservation)
        os.kill(grandchild, 0)  # This owner remains real and must be retried.
        child.close()
        self.assert_pid_gone(grandchild)
        self.run.cleanup_resources()
        self.assertFalse(self.run.work.exists())

    def test_successful_parent_exit_still_drains_its_live_compiler_helper(self):
        child, pid_file = self.compiler_like_child(leave_parent=True)
        self.assertEqual(child.wait(timeout=5).returncode, 0)
        self.assertTrue(child.group_settled)
        self.assert_pid_gone(int(pid_file.read_text()))
        child.close()
        self.assertFalse(child.cleanup_failed)

    def test_wait_timeout_cannot_leave_a_compiler_grandchild_running(self):
        child, pid_file = self.compiler_like_child()
        with self.assertRaises(scoped.ProcessTimeout):
            child.wait(timeout=0.02)
        child.close()
        self.assertTrue(child.group_settled)
        self.assert_pid_gone(int(pid_file.read_text()))

    def test_unsettled_group_keeps_failure_reservation_and_work_until_actual_retry(self):
        child = self.held_child()
        reservation = self.run.reservations[child.pid]
        with (
            patch.object(child, "_group_exists", return_value=True),
            patch.object(scoped, "GROUP_CLOSE_SECONDS", 0.03),
            self.assertRaises(scoped.ProcessTimeout),
        ):
            self.run.cleanup_resources()
        self.assertIsInstance(child.returncode, int)
        self.assertTrue(child.cleanup_failed)
        self.assertFalse(self.run.children_settled())
        self.assertEqual(self.run.reservations[child.pid], reservation)
        self.assertTrue(self.run.work.exists())
        child.close()
        self.assertFalse(child.cleanup_failed)
        self.run.cleanup_resources()
        self.assertFalse(self.run.work.exists())

    def test_expired_final_budget_still_signals_but_never_restarts_parent_reap_wait(self):
        child = self.held_child()
        child._group_final_deadline = time.monotonic() - 0.01
        began = time.monotonic()
        with patch.object(child._process, "wait", wraps=child._process.wait) as blocking_wait:
            try:
                child.close()
            except scoped.ProcessTimeout:
                pass  # A still-pending reap is retained, never called successful.
        self.assertLess(time.monotonic() - began, 0.25)
        blocking_wait.assert_not_called()
        deadline = time.monotonic() + 2
        while not child.group_settled and time.monotonic() < deadline:
            try:
                child.close()
            except scoped.ProcessTimeout:
                time.sleep(0.005)
        self.assertTrue(child.group_settled)
        self.assertIsInstance(child.returncode, int)
        self.assertFalse(child.cleanup_failed)

    def test_permission_error_is_retained_as_unsettled_never_group_absence(self):
        child = self.held_child()
        reservation = self.run.reservations[child.pid]
        with (
            patch.object(scoped.os, "killpg", side_effect=PermissionError("unresolved")),
            patch.object(scoped, "GROUP_CLOSE_SECONDS", 0.03),
            self.assertRaises(scoped.ProcessTimeout),
        ):
            self.run.cleanup_resources()
        self.assertTrue(child.cleanup_failed)
        self.assertFalse(child.group_settled)
        self.assertEqual(self.run.reservations[child.pid], reservation)
        self.assertTrue(self.run.work.exists())
        child.close()
        self.assertTrue(child.group_settled)
        self.run.cleanup_resources()
        self.assertFalse(self.run.work.exists())

    def test_group_signal_refuses_the_current_parent_group(self):
        child = self.held_child()
        with (
            patch.object(scoped.os, "getpgrp", return_value=child.pid),
            patch.object(scoped.os, "killpg") as group_signal,
            self.assertRaises(scoped.ProcessControlError),
        ):
            child.close()
        group_signal.assert_not_called()
        self.assertTrue(child.cleanup_failed)
        child.close()
        self.assertTrue(child.group_settled)
        self.assertFalse(child.cleanup_failed)

    def test_shared_child_limit_is_checked_before_spawn_not_after_seventeen_commands(self):
        self.outer["children"] = 32
        with (
            patch.object(scoped, "GroupedOwnedProcess") as spawn,
            self.assertRaises(scoped.packages.GateError),
        ):
            self.run.start([sys.executable, "-I", "-c", "pass"], stage="imports")
        spawn.assert_not_called()
        self.assertEqual(self.run.commands, 0)
        self.outer["children"] = 31
        child = self.run.start([sys.executable, "-I", "-c", "pass"], stage="imports")
        with (
            patch.object(scoped, "GroupedOwnedProcess") as spawn,
            self.assertRaises(scoped.packages.GateError),
        ):
            self.run.start([sys.executable, "-I", "-c", "pass"], stage="imports")
        spawn.assert_not_called()
        child.close()

    def test_outer_capture_and_both_live_reservations_prevent_overcommit_then_allow_progress(self):
        self.outer.update(capture=scoped.MAX_CAPTURE - 2 * scoped.MAX_STREAM - 4, reserved=4)
        child = self.held_child()
        self.assertEqual(self.run.reservations[child.pid], 2 * scoped.MAX_STREAM)
        with (
            patch.object(scoped, "GroupedOwnedProcess") as spawn,
            self.assertRaises(scoped.packages.GateError),
        ):
            self.run.start([sys.executable, "-I", "-c", "pass"], stage="imports")
        spawn.assert_not_called()
        child.close()
        self.run.capture(child)
        self.assertNotIn(child.pid, self.run.reservations)
        self.assertEqual(
            self.run.command([sys.executable, "-I", "-c", 'print("x")'], stage="imports"),
            (b"x\n", b""),
        )
        self.assertEqual(self.run.captured, 2)

    def test_small_remaining_capture_is_reserved_as_two_bounded_streams(self):
        self.outer["capture"] = scoped.MAX_CAPTURE - 2
        child = self.run.start([sys.executable, "-I", "-c", "pass"], stage="imports")
        self.assertEqual(self.run.reservations[child.pid], 2)
        child.wait(timeout=5)
        child.close()
        self.run.capture(child)
        self.assertEqual(self.run.captured, 0)

    def test_wait_exception_still_closes_and_reaps_actual_direct_child(self):
        child = self.held_child()
        primary = scoped.packages.GateError("deadline_exceeded")
        with (
            patch.object(self.run, "start", return_value=child),
            patch.object(child, "wait", side_effect=primary),
            self.assertRaises(scoped.packages.GateError) as caught,
        ):
            self.run.command([sys.executable, "-I", "-c", "pass"], stage="imports")
        self.assertIs(caught.exception, primary)
        self.assertIsInstance(child.returncode, int)
        self.assertFalse(child.cleanup_failed)
        self.assertNotIn(child.pid, self.run.reservations)

    def test_offline_delegates_unchanged_and_primary_error_survives_secondary_cleanup(self):
        primary = scoped.packages.GateError("invalid_artifact")
        secondary = scoped.packages.GateError("cleanup_incomplete")
        with (
            patch.object(scoped.packages.PackageRun, "offline", side_effect=primary),
            self.assertRaises(scoped.packages.GateError) as caught,
        ):
            self.run.offline()
        self.assertIs(caught.exception, primary)
        with (
            patch.object(scoped.packages.PackageRun, "cleanup_resources", side_effect=secondary),
            self.assertRaises(scoped.packages.GateError) as caught,
        ):
            self.run.cleanup_resources()
        self.assertIs(caught.exception, primary)
        self.assertIs(self.run.cleanup_failure, secondary)
        self.assertIs(self.run.primary_failure, primary)

    def test_cancellation_is_preserved_and_cannot_be_relabelled_as_cleanup_error(self):
        primary = KeyboardInterrupt()
        with (
            patch.object(scoped.packages.PackageRun, "offline", side_effect=primary),
            self.assertRaises(KeyboardInterrupt),
        ):
            self.run.offline()
        with (
            patch.object(
                scoped.packages.PackageRun,
                "cleanup_resources",
                side_effect=scoped.packages.GateError("cleanup_incomplete"),
            ),
            self.assertRaises(KeyboardInterrupt) as caught,
        ):
            self.run.cleanup_resources()
        self.assertIs(caught.exception, primary)

    def test_deadlines_are_clamped_and_invalid_callbacks_fail_before_allocation(self):
        self.assertLessEqual(self.run.deadline, self.options["deadline"])
        self.assertLessEqual(self.run.final_deadline, self.options["final_deadline"])
        self.outer["children"] = True
        with (
            patch.object(scoped.packages.PackageRun, "__init__") as init,
            self.assertRaises(scoped.packages.GateError),
        ):
            scoped.ScopedPackageRun(self.root, self.root / "bad.json", **self.options)
        init.assert_not_called()
        self.assertFalse((self.root / "bad-artifacts").exists())
        self.outer["children"] = 0

    def test_offline_profile_rejects_lab_and_ambient_authority_before_any_child(self):
        with (
            patch.object(scoped.packages.PackageRun, "lab") as lab,
            self.assertRaises(scoped.packages.GateError),
        ):
            self.run.lab()
        lab.assert_not_called()
        with patch.object(scoped, "GroupedOwnedProcess") as spawn:
            with self.assertRaises(scoped.packages.GateError):
                self.run.start([sys.executable], stage="lab_install")
            with self.assertRaises(scoped.packages.GateError):
                self.run.start(
                    [sys.executable],
                    stage="imports",
                    environment={**self.run.base, "PGPASSWORD": "synthetic"},
                )
        spawn.assert_not_called()

    def test_success_requires_actual_cleanup_not_passed_count_alone(self):
        child = self.held_child()
        self.run.passed.update(scoped.packages.OFFLINE_CASES)
        self.run.commands = 17
        with self.assertRaises(scoped.packages.GateError):
            self.run.successful_report()
        self.assertIsNone(child.returncode)
        self.assertFalse(self.run.report.exists())
        self.run.commands = 1
        child.close()

    def test_synthetic_complete_report_is_validated_indexed_and_detached(self):
        # Explicit metadata-only fixture, not real build/17process qualification.
        snapshot = {"synthetic-public-source.py": digest(b"synthetic source")}
        write_private(self.run.retained / "source-index.json", json_bytes(snapshot))
        self.run.passed.update(scoped.packages.OFFLINE_CASES)
        self.run.commands = 17
        self.run.children = [
            SimpleNamespace(pid=10000 + n, returncode=0, cleanup_failed=False) for n in range(17)
        ]
        for name, path in scoped.packages.ARTIFACT_PATHS.items():
            body = b"synthetic archive metadata fixture"
            write_private(self.run.retained / path, body)
            self.run.artifacts[name] = {"path": path, "bytes": len(body), "sha256": digest(body)}
        shutil.rmtree(self.run.work)
        with patch.object(self.run, "source_index", return_value=snapshot):
            report = self.run.successful_report()
        scoped.packages.validated_report(self.run.report.read_bytes())
        self.assertEqual(report["child_commands"], 17)
        self.assertEqual(report["tests"], 8)
        self.assertEqual(report["proofs"], {})
        self.assertEqual(
            len(json.loads((self.run.retained / "retained-index.json").read_bytes())["files"]), 6
        )
        report["artifacts"]["p1-wheel"]["sha256"] = "mutated returned object"
        again = self.run.successful_report()
        self.assertNotEqual(again["artifacts"]["p1-wheel"]["sha256"], "mutated returned object")
        self.assertEqual(self.run.report.read_bytes(), json_bytes(again))


if __name__ == "__main__":
    unittest.main()
