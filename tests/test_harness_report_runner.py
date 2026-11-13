"""Report protocol rejects false success and retains only safe owned evidence."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from harness import HarnessError, execute, load_catalog
from harness.process_control import ProcessTimeout
from harness.report_runner import ReportRunnerError, execute_report, read_report, wait_owned


def envelope(**changes):
    return {
        "schemaVersion": 1,
        "caseId": "P1-06",
        "mode": "lab",
        "status": "passed",
        "testCount": 2,
        "skippedCount": 0,
        "failureCount": 0,
        "errorCount": 0,
        "durationSeconds": 0.1,
        "code": "passed",
        **changes,
    }


class ReportProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "result.json"

    def read(self, value):
        self.path.write_text(json.dumps(value))
        return read_report(self.path, "P1-06", "lab")

    def test_positive_closed_protocol_and_explicit_incomplete_are_distinct(self):
        self.assertEqual(self.read(envelope()), envelope())
        self.assertEqual(
            self.read(envelope(status="incomplete", code="setup_required", testCount=0))["status"],
            "incomplete",
        )

    def test_unknown_missing_duplicate_and_mismatched_fields_fail_closed(self):
        values = [
            envelope(private="private-report-sentinel"),
            envelope(caseId="P1-07"),
            envelope(schemaVersion=True),
            envelope(mode="unknown"),
            envelope(code="private-report-sentinel"),
        ]
        missing = envelope()
        del missing["errorCount"]
        values.append(missing)
        for value in values:
            with self.subTest(value=value), self.assertRaises(ReportRunnerError):
                self.read(value)
        self.path.write_text('{"schemaVersion":1,"schemaVersion":1}')
        with self.assertRaises(ReportRunnerError):
            read_report(self.path, "P1-06", "lab")

    def test_zero_skips_errors_failures_and_contradictory_status_cannot_pass(self):
        for changes in [
            {"testCount": 0},
            {"skippedCount": 1},
            {"errorCount": 1},
            {"failureCount": 1},
            {"code": "test_error"},
            {"status": "failed"},
        ]:
            with self.subTest(changes=changes), self.assertRaises(ReportRunnerError):
                self.read(envelope(**changes))

    def test_numeric_booleans_huge_nonfinite_negative_and_unbounded_values_reject(self):
        for field in [
            "testCount",
            "skippedCount",
            "errorCount",
            "failureCount",
            "durationSeconds",
        ]:
            for value in [True, -1, 100001, float("nan"), float("inf"), 10**350]:
                with (
                    self.subTest(field=field, value=value),
                    self.assertRaises(ReportRunnerError),
                ):
                    self.read(envelope(**{field: value}))

    def test_nonregular_symlink_hardlink_oversize_and_invalid_encoding_never_read_as_report(
        self,
    ):
        self.path.write_text(json.dumps(envelope()))
        link = self.root / "link.json"
        link.symlink_to(self.path)
        with self.assertRaises(ReportRunnerError):
            read_report(link, "P1-06", "lab")
        hard = self.root / "hard.json"
        os.link(self.path, hard)
        with self.assertRaises(ReportRunnerError):
            read_report(hard, "P1-06", "lab")
        hard.unlink()
        self.path.write_bytes(b"x" * 65537)
        with self.assertRaises(ReportRunnerError):
            read_report(self.path, "P1-06", "lab")
        self.path.write_bytes(b"\xff")
        with self.assertRaises(ReportRunnerError):
            read_report(self.path, "P1-06", "lab")
        self.path.unlink()
        os.mkfifo(self.path)
        with self.assertRaises(ReportRunnerError):
            read_report(self.path, "P1-06", "lab")


class ActualReportCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "output"
        self.output.mkdir()
        self.script = self.root / "runner.py"

    def run_script(self, body, *, timeout=3):
        self.script.write_text(
            'import argparse,json,sys,time\nfrom pathlib import Path\np=argparse.ArgumentParser();p.add_argument("--case");p.add_argument("--report");a=p.parse_args()\n'
            + body
            + "\n"
        )
        return execute_report(
            self.root, self.output, self.script, "P1-06", timeout, expected_mode="lab"
        )

    def report_body(self, value=None):
        return "Path(a.report).write_text(" + repr(json.dumps(value or envelope())) + ")"

    def assert_private_removed(self, outcome):
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertNotIn("private-runner-sentinel", str(outcome))

    def test_real_positive_script_runs_with_explicit_argv_and_removes_private_output(
        self,
    ):
        result = self.run_script(
            self.report_body()
            + '\nprint("private-runner-sentinel")\nprint("private-runner-sentinel",file=sys.stderr)'
        )
        self.assertEqual((result.status, result.exit_code, result.test_count), ("passed", 0, 2))
        self.assert_private_removed(result)
        self.assertEqual(result.command[2:4], ["--case", "P1-06"])

    def test_actual_infrastructure_report_keeps_private_stderr_and_explicit_long_duration_bound(
        self,
    ):
        self.script.write_text(
            'import sys,json\nfrom pathlib import Path\na=sys.argv\nPath(a[a.index("--report")+1]).write_text('
            + repr(json.dumps(envelope(durationSeconds=301)))
            + ')\nprint("private-runner-sentinel",file=sys.stderr)\n'
        )
        outcome = execute_report(
            self.root,
            self.output,
            self.script,
            "P1-06",
            840,
            expected_mode="lab",
            infrastructure=True,
        )
        self.assertEqual("passed", outcome.status)
        self.assert_private_removed(outcome)

    def test_infrastructure_live_success_and_wrong_bound_report_mode_are_distinct(self):
        for expected, reported, status in [
            ("live", "live", "passed"),
            ("live", "lab", "runner_error"),
            ("lab", "live", "runner_error"),
        ]:
            with self.subTest(expected=expected, reported=reported):
                self.script.write_text(
                    'import sys,json\nfrom pathlib import Path\na=sys.argv\nPath(a[a.index("--report")+1]).write_text('
                    + repr(json.dumps(envelope(mode=reported, durationSeconds=301)))
                    + ')\nprint("private-runner-sentinel",file=sys.stderr)\n'
                )
                result = execute_report(
                    self.root,
                    self.output,
                    self.script,
                    "P1-06",
                    840,
                    expected_mode=expected,
                    infrastructure=True,
                )
                self.assertEqual(status, result.status)
                self.assert_private_removed(result)

    def test_declared_lab_case_cannot_pass_an_offline_or_live_report(self):
        for mode in ("offline", "live"):
            with self.subTest(mode=mode):
                result = self.run_script(self.report_body(envelope(mode=mode)))
                self.assertEqual(
                    (result.status, result.diagnostic_code),
                    ("runner_error", "runner_report_invalid"),
                )
                self.assert_private_removed(result)
        ordinary = self.run_script(self.report_body())
        self.assertEqual(ordinary.status, "passed")

    def test_nonzero_exit_cannot_promote_previously_written_success(self):
        result = self.run_script(self.report_body() + "\nraise SystemExit(7)")
        self.assertEqual(
            (result.status, result.exit_code, result.runner_exit_code), ("failed", 1, 7)
        )
        self.assert_private_removed(result)

    def test_missing_invalid_and_secret_extra_report_data_never_persist(self):
        for body in [
            'print("private-runner-sentinel")',
            self.report_body(envelope(private="private-runner-sentinel")),
        ]:
            with self.subTest(body=body):
                result = self.run_script(body)
                self.assertEqual(
                    (result.status, result.diagnostic_code),
                    ("runner_error", "runner_report_invalid"),
                )
                self.assert_private_removed(result)

    def test_required_setup_incomplete_and_skip_are_nonpassing(self):
        result = self.run_script(
            self.report_body(envelope(status="incomplete", code="setup_required", testCount=0))
            + "\nraise SystemExit(2)"
        )
        self.assertEqual((result.status, result.exit_code), ("incomplete", 2))
        self.assert_private_removed(result)

    def test_actual_timeout_reaps_owned_child_and_deletes_partial_private_capture(self):
        result = self.run_script(
            'print("private-runner-sentinel",flush=True)\ntime.sleep(30)', timeout=1
        )
        self.assertEqual(
            (result.status, result.exit_code, result.diagnostic_code),
            ("timed_out", 124, "runner_timeout"),
        )
        self.assert_private_removed(result)

    def test_actual_output_flood_is_bounded_and_nonpassing(self):
        result = self.run_script(
            'print("private-runner-sentinel"*10000,flush=True)\ntime.sleep(30)'
        )
        self.assertEqual(
            (result.status, result.diagnostic_code),
            ("runner_error", "runner_output_limit"),
        )
        self.assert_private_removed(result)


class CatalogReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "harness").mkdir()
        (self.root / "runner.py").write_text("pass\n")
        self.catalog = {
            "schemaVersion": 1,
            "requiredDocuments": [],
            "projects": {},
            "runners": {
                "P1-01": {
                    "project": "p1",
                    "title": "fixture",
                    "kind": "python_json_report",
                    "script": "runner.py",
                    "timeoutSeconds": 3,
                    "assertionFiles": ["runner.py"],
                    "mode": "lab",
                }
            },
        }
        for number in range(1, 4):
            source = f"scope{number}.md"
            (self.root / source).write_text(f"| P{number}-01 | fixture | assertion |\n")
            self.catalog["projects"][f"p{number}"] = {"scope": source}

    def save(self):
        (self.root / "harness/catalog.json").write_text(json.dumps(self.catalog))

    def test_valid_catalog_accepts_only_closed_regular_python_report_target(self):
        self.save()
        case = next(c for c in load_catalog(self.root) if c["caseId"] == "P1-01")
        self.assertEqual(case["status"], "registered")
        for key, value in [
            ("script", "../outside.py"),
            ("script", "/tmp/outside.py"),
            ("script", "missing.py"),
            ("script", "runner.sh"),
            ("timeoutSeconds", True),
            ("extra", "private-runner-sentinel"),
        ]:
            with self.subTest(key=key, value=value):
                old = dict(self.catalog["runners"]["P1-01"])
                self.catalog["runners"]["P1-01"][key] = value
                self.save()
                with self.assertRaises(HarnessError):
                    load_catalog(self.root)
                self.catalog["runners"]["P1-01"] = old

    def test_assertion_inventory_supports_esm_but_rejects_noncode_and_missing_files(self):
        runner = self.catalog["runners"]["P1-01"]
        for name in ("assertions.py", "assertions.ts", "assertions.mjs"):
            (self.root / name).write_text("// synthetic assertion source\n")
            runner["assertionFiles"] = [name]
            self.save()
            self.assertEqual(load_catalog(self.root)[0]["caseId"], "P1-01")
        for name in ("missing.mjs", "assertions.json", "assertions.sh"):
            if not name.startswith("missing"):
                (self.root / name).write_text("synthetic non-code\n")
            runner["assertionFiles"] = [name]
            self.save()
            with self.subTest(name=name), self.assertRaises(HarnessError):
                load_catalog(self.root)

    def test_inside_root_symlink_script_is_refused(self):
        (self.root / "alias.py").symlink_to(self.root / "runner.py")
        self.catalog["runners"]["P1-01"]["script"] = "alias.py"
        self.save()
        with self.assertRaises(HarnessError):
            load_catalog(self.root)

    def test_execute_persists_only_validated_report_and_safe_fixed_diagnostic(self):
        value = envelope(caseId="P1-01")
        self.script = self.root / "runner.py"
        self.script.write_text(
            'import sys,json\nfrom pathlib import Path\na=sys.argv\nPath(a[a.index("--report")+1]).write_text('
            + repr(json.dumps(value))
            + ')\nprint("private-runner-sentinel",file=sys.stderr)\n'
        )
        self.save()
        case = next(c for c in load_catalog(self.root) if c["caseId"] == "P1-01")
        result = execute(self.root, case)
        self.assertEqual((result["status"], result["testCount"]), ("passed", 2))
        for path in (self.root / ".local/harness").rglob("*"):
            if path.is_file():
                self.assertNotIn("private-runner-sentinel", path.read_text())
        self.assertEqual(result["runnerReport"], value)


class InfrastructureProtocolTests(ReportProtocolTests):
    def test_ordinary_duration_remains300_while_explicit_infrastructure_bound_is_finite(self):
        self.path.write_text(json.dumps(envelope(durationSeconds=301)))
        with self.assertRaises(ReportRunnerError):
            read_report(self.path, "P1-06", "lab")
        self.assertEqual(
            301, read_report(self.path, "P1-06", "lab", max_duration=840)["durationSeconds"]
        )
        for value in (True, 0, -1, 901, 10**350, float("nan"), None):
            with self.subTest(value=value), self.assertRaises(ReportRunnerError):
                read_report(self.path, "P1-06", "lab", max_duration=value)
        self.path.write_text(json.dumps(envelope(durationSeconds=841)))
        with self.assertRaises(ReportRunnerError):
            read_report(self.path, "P1-06", "lab", max_duration=840)

    def test_owned_observation_chunks_share_one_original_deadline_without_closing_child(self):
        child = Mock()
        child.wait.side_effect = [
            ProcessTimeout("first"),
            ProcessTimeout("second"),
            SimpleNamespace(returncode=0, pid=1),
        ]
        clock = Mock(side_effect=[10, 10, 310, 310, 610, 610])
        self.assertEqual(0, wait_owned(child, 840, clock=clock).returncode)
        self.assertEqual(
            [300.0, 300.0, 240], [call.kwargs["timeout"] for call in child.wait.call_args_list]
        )
        child.close.assert_not_called()
        child = Mock()
        child.wait.side_effect = ProcessTimeout("private-runner-sentinel")
        clock = Mock(side_effect=[10, 10, 310, 310, 610, 610, 850])
        with self.assertRaises(ProcessTimeout):
            wait_owned(child, 840, clock=clock)
        self.assertEqual(3, child.wait.call_count)

    def test_execution_rejects_wrong_mode_invalid_flag_or_unbounded_duration_before_launch(self):
        script = self.root / "never.py"
        script.write_text("raise AssertionError('must not run')")
        for timeout, infrastructure, mode in [
            (301, False, "lab"),
            (901, True, "lab"),
            (840, True, "offline"),
            (840, True, "unknown"),
            (True, True, "lab"),
            (840, 1, "lab"),
        ]:
            with self.subTest(timeout=timeout, infrastructure=infrastructure, mode=mode):
                result = execute_report(
                    self.root,
                    self.root,
                    script,
                    "P1-06",
                    timeout,
                    expected_mode=mode,
                    infrastructure=infrastructure,
                )
                self.assertEqual("runner_error", result.status)
                self.assertIsNone(result.runner_exit_code)
                self.assertEqual([], result.command)


class InfrastructureCatalogTests(CatalogReportTests):
    def test_distinct_kind_has900_cap_lab_live_and_ts_assertions_do_not_allow_ts_entrypoint(self):
        target = self.catalog["runners"]["P1-01"]
        target.update(kind="python_infrastructure_report", timeoutSeconds=840)
        (self.root / "browser.ts").write_text("// actual browser assertion fixture\n")
        target["assertionFiles"] = ["browser.ts"]
        self.save()
        self.assertEqual("registered", load_catalog(self.root)[0]["status"])
        target["mode"] = "live"
        self.save()
        self.assertEqual("live", load_catalog(self.root)[0]["mode"])
        target["mode"] = "lab"
        for field, value in [
            ("timeoutSeconds", 901),
            ("mode", "unknown"),
            ("mode", "offline"),
            ("script", "browser.ts"),
        ]:
            original = dict(target)
            target[field] = value
            self.save()
            with self.subTest(field=field, value=value), self.assertRaises(HarnessError):
                load_catalog(self.root)
            target.clear()
            target.update(original)
        target.update(kind="python_json_report", timeoutSeconds=301)
        self.save()
        with self.assertRaises(HarnessError):
            load_catalog(self.root)
        target.update(
            kind="python_infrastructure_report", timeoutSeconds=840, assertionFiles=["unknown.txt"]
        )
        (self.root / "unknown.txt").write_text("unsafe assertion fixture")
        self.save()
        with self.assertRaises(HarnessError):
            load_catalog(self.root)


if __name__ == "__main__":
    unittest.main()
