"""Offline controls for the separate installed P1 adapter host; no qualification."""

from __future__ import annotations

import asyncio
import contextlib
import copy
import importlib.util
import io
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "p2_p1_host_under_test", ROOT / "local-setup/scripts/p2_starter_p1_check.py"
)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def report():
    return {
        "schema_version": 1,
        "status": "passed",
        "mode": m.MODE,
        "tests": 6,
        "passed": 6,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "duration_seconds": 1.25,
        "direct_commands": 26,
        "nested_commands": 3,
        "child_commands": 29,
        "direct_capture_bytes": 10,
        "nested_capture_bound_bytes": 49152,
        "cleanup_complete": True,
        "process_inventory_complete": True,
        "code": "ok",
        "stage": "complete",
        "retained_index_sha256": "a" * 64,
        "case_results": [{"name": n, "status": "passed"} for n in m.CASE_NAMES],
    }


class BoundaryTests(unittest.TestCase):
    def test_plan_is_pure_and_reserves_nested_processes(self):
        output = io.StringIO()
        with (
            patch.object(m, "ContractRun", side_effect=AssertionError("no construction")),
            patch.object(m.shared, "target_path", side_effect=AssertionError("no files")),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(m.main(["--plan"], root=Path("/missing")), 0)
        value = m.shared.decode(output.getvalue().encode())
        self.assertEqual((len(value["cases"]), value["total_commands"]), (6, 29))
        self.assertFalse(value["measurement_started"])
        self.assertEqual(len(set(value["direct_roles"])), 26)
        self.assertEqual(value["bounds"]["max_direct_children"] + 3, 32)
        self.assertEqual(value["bounds"]["max_owned_process_groups"], 32)

    def test_closed_report_rejects_aliases_counts_partial_and_missing_ownership(self):
        self.assertEqual(m.validated_report(m.shared.json_bytes(report())), report())
        mutations = [
            ("schema_version", True),
            ("tests", True),
            ("passed", 5),
            ("nested_commands", 4),
            ("direct_commands", 30),
            ("child_commands", 28),
            ("cleanup_complete", False),
            ("process_inventory_complete", False),
            ("retained_index_sha256", None),
            ("mode", "other"),
            ("code", "raw_error"),
            ("duration_seconds", float("inf")),
            ("duration_seconds", -1),
        ]
        for key, value in mutations:
            with self.subTest(key=key, value=value), self.assertRaises(m.GateError):
                changed = report()
                changed[key] = value
                m.validated_report(m.shared.json_bytes(changed))
        changed = report()
        changed["case_results"][-1]["name"] = "not_an_assertion"
        with self.assertRaises(m.GateError):
            m.validated_report(m.shared.json_bytes(changed))

    def test_failed_report_cannot_claim_partial_qualification(self):
        value = report()
        value.update(
            status="failed",
            passed=0,
            failures=1,
            cleanup_complete=False,
            process_inventory_complete=False,
            code="cleanup_incomplete",
            stage="proof",
            case_results=[],
        )
        m.validated_report(m.shared.json_bytes(value))
        value["passed"] = 1
        value["case_results"] = [{"name": m.CASE_NAMES[0], "status": "passed"}]
        with self.assertRaises(m.GateError):
            m.validated_report(m.shared.json_bytes(value))

    def test_nested_record_requires_original_worker_argv_exit_and_group(self):
        executable = Path("/private/tmp/installed/bin/python")
        owner, outer, nested = "a" * 32, 198765, 198766
        step = {
            "role": "exact-mutation",
            "processId": nested,
            "groupId": nested,
            "argvSha256": m.digest(
                m.shared.json_bytes(
                    [
                        str(executable),
                        "-m",
                        "continuity_lab.worker_cli",
                        "step",
                    ]
                )
            ),
            "returnCode": 0,
            "groupAbsent": True,
        }
        value = {
            "schemaVersion": 1,
            "owner": owner,
            "workerProcessId": outer,
            "steps": [step],
            "cleanupComplete": True,
        }
        kwargs = {
            "role": "exact-mutation",
            "owner": owner,
            "worker_pid": outer,
            "executable": executable,
        }
        self.assertEqual(m.validate_step(m.shared.json_bytes(value), **kwargs), value)
        for key, bad in [
            ("processId", outer),
            ("groupId", 123),
            ("argvSha256", "0" * 64),
            ("returnCode", True),
            ("returnCode", 1),
            ("groupAbsent", False),
            ("role", "stale-inquiry"),
        ]:
            with self.subTest(key=key), self.assertRaises(m.GateError):
                changed = copy.deepcopy(value)
                changed["steps"][0][key] = bad
                m.validate_step(m.shared.json_bytes(changed), **kwargs)
        for key, bad in [("owner", "b" * 32), ("workerProcessId", nested), ("steps", [])]:
            with self.subTest(key=key), self.assertRaises(m.GateError):
                m.validate_step(m.shared.json_bytes({**value, key: bad}), **kwargs)

    def test_group_probe_never_signals_and_permission_error_is_unknown(self):
        for error, expected in [(ProcessLookupError(), True), (PermissionError(), False)]:
            with patch.object(m.os, "killpg", side_effect=error) as call:
                self.assertEqual(m.group_absent(198766), expected)
                call.assert_called_once_with(198766, 0)

    def test_marker_diagnostics_retain_only_fixed_names_and_private_decimal_pid_states(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
            work = Path(directory).resolve()
            sentinel = b"SYNTHETIC_SECRET_MARKER_BYTES"
            m.shared.write_private(work / "p1_zero_read_done.reached", b"12345\n")
            m.shared.write_private(work / "p1_zero_read_done.released", sentinel)
            m.shared.write_private(work / "p1_ready.reached", b"00123\n")
            m.shared.write_private(work / "unlisted.reached", sentinel)
            value = m.diagnostic_marker_inventory(work, "a" * 32)
            self.assertEqual(set(value["markers"]), set(m.MARKERS))
            self.assertEqual(
                value["markers"]["p1_zero_read_done"]["reached"],
                {"state": "observed", "pid": 12345},
            )
            self.assertEqual(
                value["markers"]["p1_zero_read_done"]["released"], {"state": "unavailable"}
            )
            self.assertEqual(value["markers"]["p1_ready"]["reached"], {"state": "unavailable"})
            self.assertEqual(value["markers"]["p1_stop"]["released"], {"state": "absent"})
            self.assertNotIn(sentinel, m.shared.json_bytes(value))
            self.assertNotIn("unlisted", value["markers"])

    def test_owner_snapshot_rejects_scope_before_connection_and_never_prunes(self):
        with self.assertRaises(m.GateError):
            m.owner_snapshot(lambda: self.fail("must not connect"), "public")

        class Cursor:
            def __init__(self, rows):
                self.rows = rows

            def fetchall(self):
                return self.rows

        class Connection:
            def __init__(self, count):
                self.count = count
                self.closed = False

            def execute(self, query, params=None):
                text = query if type(query) is str else query.as_string()
                if "pg_get_userbyid" in text:
                    return Cursor([{"owner": "continuity_migrator"}])
                if "pg_tables" in text:
                    return Cursor([{"tablename": "accepted_tasks"}])
                self_outer.assertTrue(text.endswith("LIMIT 129"))
                return Cursor([{"body": '{"original":"retained"}'} for _ in range(self.count)])

            def close(self):
                self.closed = True

        self_outer = self
        good = Connection(128)
        self.assertEqual(
            len(m.owner_snapshot(lambda: good, "p1_starter_" + "a" * 32)["accepted_tasks"]), 128
        )
        self.assertTrue(good.closed)
        bad = Connection(129)
        with self.assertRaises(m.GateError):
            m.owner_snapshot(lambda: bad, "p1_starter_" + "a" * 32)
        self.assertTrue(bad.closed)


class CleanupTests(unittest.IsolatedAsyncioTestCase):
    def make_run(self, path):
        calls = []

        class Actual:
            closing = False

            async def drain(self, deadline):
                calls.append("drain")
                return True

            async def cleanup_call(self, function):
                calls.append("schema")
                return function()

            async def close(self, deadline):
                calls.append("actual-close")
                return True

        class Children:
            def __init__(self):
                self.children = []
                self.start_failed = False

            def close(self):
                calls.append("children-close")

            def all_settled(self):
                return True

            def capture(self, child, **kwargs):
                raise AssertionError("not needed")

        run = m.ContractRun.__new__(m.ContractRun)
        run.actual, run.children = Actual(), Children()
        run.final = time.monotonic() + 20
        run.work, run.secrets = path, ()
        run.artifacts = path
        run.marker = {
            "schema_version": 1,
            "owner": "a" * 32,
            "schema": "p1_starter_" + "a" * 32,
            "path": str(path),
        }
        m.shared.write_private(path / "owned-work.json", m.shared.json_bytes(run.marker))
        run.steps, run.worker_pids, run.zero_step_roles = {}, {}, set()
        run.proofs = {}
        run.lab_started, run.lab_cleaned = True, False

        def cleanup_schema():
            run.lab_cleaned = True

        run.cleanup_schema = cleanup_schema
        run.python, run.owner = path / "installed/bin/python", "a" * 32
        return run, calls

    async def test_drain_and_child_closure_precede_schema_and_private_removal(self):
        path = Path(tempfile.mkdtemp(prefix="p1-adapter-cleanup-", dir="/private/tmp"))
        run, calls = self.make_run(path)
        try:
            self.assertTrue(await run.cleanup())
            self.assertEqual(calls, ["drain", "children-close", "schema", "actual-close"])
            self.assertFalse(path.exists())
        finally:
            if path.exists():
                m.shutil.rmtree(path)

    async def test_unknown_nested_owner_still_closes_children_and_withholds_ddl(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
            path = Path(directory)
            run, calls = self.make_run(path)
            run.worker_pids["exact-mutation"] = 198765
            self.assertFalse(await run.cleanup())
            self.assertEqual(calls, ["drain", "children-close"])
            self.assertTrue(path.exists())
            self.assertFalse(run.lab_cleaned)

    async def test_foreign_owned_marker_closes_children_but_never_removes_schema(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
            path = Path(directory)
            run, calls = self.make_run(path)
            marker = path / "owned-work.json"
            marker.unlink()
            m.shared.write_private(marker, m.shared.json_bytes({**run.marker, "owner": "b" * 32}))
            with self.assertRaises(m.GateError):
                await run.cleanup()
            self.assertEqual(calls, ["drain", "children-close"])
            self.assertTrue(path.exists())
            self.assertFalse(run.lab_cleaned)

    async def test_unsettled_actual_work_withholds_schema_and_files(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
            run, calls = self.make_run(Path(directory))

            async def pending(deadline):
                calls.append("drain")
                return False

            run.actual.drain = pending
            self.assertFalse(await run.cleanup())
            self.assertEqual(calls, ["drain", "children-close"])
            self.assertTrue(Path(directory).exists())
            self.assertFalse(run.lab_cleaned)


class FailureRetentionTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def failure():
        return {
            "schemaVersion": 1,
            "status": "failed",
            "mode": "p1-contract",
            "stage": "configuration",
            "errorType": "StarterError",
            "code": "Unavailable",
            "cleanupComplete": False,
        }

    async def test_actual_exited_child_drains_buffered_output_before_close_and_retains_safe_phase(
        self,
    ):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
            base = Path(directory).resolve()
            run = m.ContractRun(ROOT, base / "report.json")
            run.deadline, run.final = time.monotonic() + 5, time.monotonic() + 10
            run.children.deadline, run.children.final_deadline = run.deadline, run.final
            raw = m.shared.json_bytes(self.failure())
            held_wait = None
            admitted = []

            async def journey():
                nonlocal held_wait
                source = "import os,sys; p=sys.argv[1]; f=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600); os.write(f,sys.argv[2].encode()); os.close(f); sys.stdout.write('finite failed stdout\\n'); sys.stderr.write('finite failed stderr\\n'); sys.exit(1)"
                failed = run.start(
                    "p1-revision-consumer",
                    [
                        sys.executable,
                        "-I",
                        "-c",
                        source,
                        str(run.work / "phase-revision.json"),
                        raw.decode(),
                    ],
                    m.runtime_base(),
                )
                held_source = "import pathlib,sys,time; pathlib.Path(sys.argv[1]).write_text('ready'); time.sleep(30)"
                held = run.start(
                    "p1-bridges",
                    [sys.executable, "-I", "-c", held_source, str(run.work / "unit-held-ready")],
                    m.runtime_base(),
                )
                admitted.extend([failed, held])
                until = time.monotonic() + 3
                while failed.returncode is None or not (run.work / "unit-held-ready").exists():
                    self.assertLess(time.monotonic(), until)
                    await asyncio.sleep(0.005)
                self.assertEqual((failed.output_directory / "stdout.bin").read_bytes(), b"")
                held_wait = patch.object(
                    held, "wait", side_effect=AssertionError("live held owner must not be joined")
                )
                held_wait.start()
                raise m.GateError("invalid_proof")

            run.journey = journey
            try:
                with patch.object(m, "ContractRun", return_value=run):
                    result = await m.execute(ROOT, base / "report.json")
                self.assertEqual(result["code"], "invalid_proof")
                self.assertTrue(result["cleanup_complete"])
                self.assertEqual((run.artifacts / "phase-revision.json").read_bytes(), raw)
                self.assertEqual(
                    (admitted[0].output_directory / "stdout.bin").read_bytes(),
                    b"finite failed stdout\n",
                )
                self.assertEqual(
                    (admitted[0].output_directory / "stderr.bin").read_bytes(),
                    b"finite failed stderr\n",
                )
                self.assertFalse(run.work.exists())
                self.assertTrue(run.children.all_settled())
                self.assertTrue(all(m.group_absent(c.pid) for c in admitted))
                self.assertEqual(result["direct_commands"], 2)
            finally:
                if held_wait is not None:
                    held_wait.stop()
                run.children.close()
                if run.work.exists():
                    m.shutil.rmtree(run.work)

    async def test_phase_failure_requires_fixed_finite_shape_size_and_secret_scan(self):
        original = self.failure()
        candidates = [
            (m.shared.json_bytes({**original, "extra": "not allowed"}), ()),
            (m.shared.json_bytes({**original, "schemaVersion": True}), ()),
            (m.shared.json_bytes({**original, "status": "passed"}), ()),
            (m.shared.json_bytes(original) + b" " * 2048, ()),
            (
                m.shared.json_bytes({**original, "code": "DispatchUnavailable"}),
                (b"DispatchUnavailable",),
            ),
        ]
        for raw, secrets in candidates:
            with (
                self.subTest(raw_bytes=len(raw), secret=bool(secrets)),
                tempfile.TemporaryDirectory(dir="/private/tmp") as directory,
            ):
                run = m.ContractRun(ROOT, Path(directory).resolve() / "report.json")
                run.secrets = secrets
                try:
                    m.shared.write_private(run.work / "phase-revision.json", raw)
                    with self.assertRaises(m.GateError):
                        run.retain_phase_failures()
                    self.assertFalse((run.artifacts / "phase-revision.json").exists())
                    self.assertTrue(run.work.exists())
                finally:
                    run.children.close()
                    m.shutil.rmtree(run.work)

    async def test_successful_phase_artifact_and_unlisted_work_file_remain_unmodified(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
            run = m.ContractRun(ROOT, Path(directory).resolve() / "report.json")
            try:
                original = b'{"already":"retained success"}'
                run.proofs["revision"] = {"already": "retained success"}
                m.shared.write_private(run.artifacts / "phase-revision.json", original)
                m.shared.write_private(run.work / "phase-revision.json", b" " * 3000)
                m.shared.write_private(
                    run.work / "phase-unlisted.json", b"UNREVIEWED_PRIVATE_BYTES"
                )
                run.retain_phase_failures()
                self.assertEqual((run.artifacts / "phase-revision.json").read_bytes(), original)
                self.assertFalse((run.artifacts / "phase-unlisted.json").exists())
            finally:
                run.children.close()
                m.shutil.rmtree(run.work)


if __name__ == "__main__":
    unittest.main()
