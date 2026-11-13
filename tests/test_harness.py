"""Harness tests protect honest reporting and controlled runner execution."""

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness import HarnessError, execute, load_catalog, main, parse_cases, safe_path


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "harness").mkdir()
        (self.root / "tests").mkdir()
        (self.root / "tests/test_intake.py").write_text("# fixture target\n")
        (self.root / "README.md").write_text("fixture\n")
        self.catalog = {
            "schemaVersion": 1,
            "requiredDocuments": ["README.md"],
            "projects": {},
            "runners": {
                "BASE-01": {
                    "project": "p1",
                    "title": "fixture baseline",
                    "kind": "unittest_discovery",
                    "startDirectory": "tests",
                    "pattern": "test_intake.py",
                    "timeoutSeconds": 10,
                }
            },
        }
        for number in range(1, 4):
            source = f"scope{number}.md"
            (self.root / source).write_text(f"| P{number}-01 | scenario | required assertion |\n")
            self.catalog["projects"][f"p{number}"] = {"scope": source}
        self.save_catalog()

    def save_catalog(self):
        (self.root / "harness/catalog.json").write_text(json.dumps(self.catalog))

    def cli(self, *args):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = main(list(args), root=self.root)
        return code, json.loads(stream.getvalue())

    def test_scope_parser_reads_backticks_and_two_column_rows(self):
        cases = parse_cases("| `P1-01` | scenario |\n", "p1", "scope.md")
        self.assertEqual(cases[0]["caseId"], "P1-01")
        self.assertEqual(cases[0]["status"], "planned")

    def test_duplicate_and_malformed_ids_are_rejected(self):
        for text in ("| P1-01 | a |\n| P1-01 | b |", "| P1-X | bad |", "| P2-01 | wrong project |"):
            with self.subTest(text=text), self.assertRaises(HarnessError):
                parse_cases(text, "p1", "scope.md")

    def test_unsafe_paths_and_symlink_escape_are_rejected(self):
        for path in ("../outside", "/tmp/outside", "tests/../outside", "tests\\outside"):
            with self.subTest(path=path), self.assertRaises(HarnessError):
                safe_path(self.root, path)
        (self.root / "escape").symlink_to(self.root.parent, target_is_directory=True)
        with self.assertRaises(HarnessError):
            safe_path(self.root, "escape/outside")

    def test_planned_case_cannot_pass_and_writes_report(self):
        with patch("harness.subprocess.run") as runner:
            code, summary = self.cli("run", "P1-01")
        runner.assert_not_called()
        self.assertEqual(code, 2)
        self.assertEqual(summary["status"], "incomplete")
        report = summary["runs"][0]
        self.assertEqual(report["status"], "not_implemented")
        saved = json.loads((self.root / report["artifacts"]["report"]).read_text())
        self.assertEqual(saved, report)

    def test_failed_runner_preserves_exit_and_diagnostics(self):
        result = subprocess.CompletedProcess([], 7, "fixture stdout", "fixture failure")
        with patch("harness.subprocess.run", return_value=result) as runner:
            code, summary = self.cli("run", "BASE-01")
        self.assertEqual(code, 7)
        report = summary["runs"][0]
        self.assertEqual(report["status"], "failed")
        self.assertEqual((self.root / report["artifacts"]["stderr"]).read_text(), "fixture failure")
        self.assertIsInstance(runner.call_args.args[0], list)
        self.assertNotIn("shell", runner.call_args.kwargs)
        self.assertEqual(runner.call_args.kwargs["timeout"], 10)

    def test_timeout_bytes_decode_once_with_replacement_without_repr_or_traceback(self):
        failure = subprocess.TimeoutExpired([], 10, output=b"partial\xff", stderr=b"diagnostic\xfe")
        with patch("harness.subprocess.run", side_effect=failure):
            code, summary = self.cli("run", "BASE-01")
        report = summary["runs"][0]
        self.assertEqual((124, "timed_out"), (code, report["status"]))
        stdout = (self.root / report["artifacts"]["stdout"]).read_text()
        stderr = (self.root / report["artifacts"]["stderr"]).read_text()
        self.assertEqual("partial\ufffd", stdout)
        self.assertEqual("diagnostic\ufffd", stderr)
        self.assertNotIn("Traceback", stdout + stderr)
        self.assertNotIn("b'", stdout + stderr)

    def test_passing_baseline_does_not_complete_project(self):
        success = subprocess.CompletedProcess([], 0, "", "Ran 1 test in 0.01s\n\nOK\n")
        with patch("harness.subprocess.run", return_value=success):
            code, summary = self.cli("run", "--project", "p1")
        self.assertEqual(code, 2)
        self.assertEqual(summary["status"], "incomplete")
        self.assertEqual({r["status"] for r in summary["runs"]}, {"passed", "not_implemented"})

    def test_zero_tests_or_missing_summary_cannot_pass(self):
        for diagnostic in ("Ran 0 tests in 0.01s\n\nOK\n", "no unittest summary"):
            with self.subTest(diagnostic=diagnostic):
                result = subprocess.CompletedProcess([], 0, "", diagnostic)
                with patch("harness.subprocess.run", return_value=result):
                    code, summary = self.cli("run", "BASE-01")
                report = summary["runs"][0]
                self.assertEqual(code, 1)
                self.assertEqual(summary["status"], "failed")
                self.assertEqual(report["status"], "no_tests")
                self.assertEqual(report["runnerExitCode"], 0)
                self.assertNotEqual(report["testCount"], 1)

    def test_skipped_check_cannot_complete_required_suite(self):
        result = subprocess.CompletedProcess([], 0, "", "Ran 1 test in 0.01s\n\nOK (skipped=1)\n")
        with patch("harness.subprocess.run", return_value=result):
            code, summary = self.cli("run", "BASE-01")
        self.assertEqual(code, 2)
        self.assertEqual(summary["status"], "incomplete")
        self.assertEqual(summary["runs"][0]["skippedCount"], 1)

    def test_duplicate_catalog_json_key_is_rejected(self):
        (self.root / "harness/catalog.json").write_text('{"schemaVersion": 1, "schemaVersion": 1}')
        with self.assertRaisesRegex(HarnessError, "duplicate JSON key"):
            load_catalog(self.root)

    def test_timeout_is_recorded_and_not_passed(self):
        case = next(c for c in load_catalog(self.root) if c["caseId"] == "BASE-01")
        with patch(
            "harness.subprocess.run", side_effect=subprocess.TimeoutExpired([], 10, b"partial")
        ):
            report = execute(self.root, case)
        self.assertEqual(report["status"], "timed_out")
        self.assertEqual(report["exitCode"], 124)
        self.assertEqual((self.root / report["artifacts"]["stdout"]).read_text(), "partial")

    def test_invalid_runner_and_missing_document_fail_validation(self):
        self.catalog["runners"]["BASE-01"]["kind"] = "shell"
        self.save_catalog()
        with self.assertRaises(HarnessError):
            load_catalog(self.root)
        self.catalog["runners"] = {}
        self.catalog["requiredDocuments"].append("missing.md")
        self.save_catalog()
        code, result = self.cli("validate")
        self.assertEqual(code, 2)
        self.assertEqual(result["status"], "invalid")
        self.assertIn("missing.md", result["error"])


if __name__ == "__main__":
    unittest.main()
