"""P1 explicit acceptance selection/setup/report privacy without database access."""

import ast
import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "acceptance_under_test", ROOT / "local-setup/scripts/p1_acceptance.py"
)
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)
VALUES = {
    "POSTGRES_PORT": "5432",
    "POSTGRES_PASSWORD": "synthetic-runtime-sentinel",
    "POSTGRES_MIGRATION_PASSWORD": "synthetic-migration-sentinel",
}


class Samples:
    class Passing(unittest.TestCase):
        def runTest(self):
            self.assertTrue(True)

    class PrivateFailure(unittest.TestCase):
        def runTest(self):
            raise RuntimeError("private-test-trace-sentinel")

    class PrivateAssertion(unittest.TestCase):
        def runTest(self):
            self.fail("private-test-trace-sentinel")

    class PrivateSubtest(unittest.TestCase):
        def runTest(self):
            with self.subTest(private="private-test-trace-sentinel"):
                self.fail("private-test-trace-sentinel")

    class RequiredSkip(unittest.TestCase):
        def runTest(self):
            self.skipTest("private-test-trace-sentinel")


class P1AcceptanceTests(unittest.TestCase):
    def suite(self, case, first=Samples.Passing):
        count = len(acceptance.CASES[case])
        return unittest.TestSuite([first()] + [Samples.Passing() for _ in range(count - 1)])

    def run_case(self, first=Samples.Passing):
        return acceptance.run_case(
            "P1-06",
            root=ROOT,
            settings_loader=lambda _: VALUES,
            suite_loader=lambda case, _: self.suite(case, first),
        )

    def test_frozen_mappings_reference_existing_exact_public_test_methods(self):
        self.assertEqual(
            set(acceptance.CASES),
            {f"P1-{n:02}" for n in [6, 7, 8, 9, 10, 11, 12, 13, 15, 16, 17, 19]},
        )
        for case, identifiers in acceptance.CASES.items():
            self.assertGreater(len(identifiers), 1)
            self.assertEqual(len(identifiers), len(set(identifiers)))
            for identifier in identifiers:
                module, cls, method = identifier.split(".")
                path = (
                    ROOT
                    / "tests"
                    / ("postgres" if module.startswith("pg_") else "")
                    / (module + ".py")
                )
                tree = ast.parse(path.read_text())
                nodes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls]
                self.assertEqual(len(nodes), 1, (case, identifier))
                self.assertIn(
                    method,
                    {n.name for n in nodes[0].body if isinstance(n, ast.FunctionDef)},
                    (case, identifier),
                )

    def test_required_schedules_are_explicit_not_inferred_from_broad_test_counts(self):
        expected = {
            10: [
                "actual_process_retains_early_signal",
                "late_signal_concurrent",
                "actual_process_restart_preserves_deadline",
            ],
            15: [
                "two_independent_processes",
                "paused_independent_process",
                "paused_old_external_call",
                "without_cooperation",
                "known_supplier_success",
            ],
            16: [
                "completion_commit_process_loss_before_first_delivery",
                "after_receiver_commit",
            ],
            19: [
                "existing_m1_upgrades",
                "abrupt_process_exit",
                "backup_includes_committed_wal",
                "complete_cutover",
                "process_exit_at_each_checkpoint",
                "retained_backup_is_restorable",
                "populated_v3_upgrade",
            ],
        }
        for number, names in expected.items():
            values = " ".join(acceptance.CASES[f"P1-{number:02}"])
            for name in names:
                self.assertIn(name, values)

    def test_success_counts_every_selected_assertion_and_reports_only_closed_fields(
        self,
    ):
        report, code = self.run_case()
        self.assertEqual((code, report["status"], report["testCount"]), (0, "passed", 2))
        self.assertEqual(
            set(report),
            {
                "schemaVersion",
                "caseId",
                "mode",
                "status",
                "testCount",
                "skippedCount",
                "failureCount",
                "errorCount",
                "durationSeconds",
                "code",
            },
        )
        self.assertNotIn("sentinel", json.dumps(report))

    def test_private_errors_assertions_and_subtests_never_format_exception_content(
        self,
    ):
        for first in [
            Samples.PrivateFailure,
            Samples.PrivateAssertion,
            Samples.PrivateSubtest,
        ]:
            with self.subTest(first=first):
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    report, code = self.run_case(first)
                self.assertEqual(code, 1)
                self.assertEqual(report["status"], "failed")
                self.assertNotIn(
                    "private-test-trace-sentinel",
                    json.dumps(report) + out.getvalue() + err.getvalue(),
                )

    def test_expected_failure_and_unexpected_success_remain_nonpassing(self):
        class Expected(unittest.TestCase):
            @unittest.expectedFailure
            def runTest(self):
                self.fail("private-test-trace-sentinel")

        class Unexpected(unittest.TestCase):
            @unittest.expectedFailure
            def runTest(self):
                self.assertTrue(True)

        report, code = self.run_case(Expected)
        self.assertEqual((code, report["status"], report["skippedCount"]), (2, "incomplete", 1))
        report, code = self.run_case(Unexpected)
        self.assertEqual((code, report["status"], report["failureCount"]), (1, "failed", 1))
        self.assertNotIn("private-test-trace-sentinel", json.dumps(report))

    def test_skipped_required_assertion_is_explicitly_nonpassing(self):
        report, code = self.run_case(Samples.RequiredSkip)
        self.assertEqual((code, report["status"], report["skippedCount"]), (2, "incomplete", 1))

    def test_unknown_case_and_zero_or_missing_mapping_cannot_pass(self):
        with patch.object(acceptance, "load_settings", side_effect=AssertionError("must not load")):
            report, code = acceptance.run_case("P1-14")
            self.assertEqual((code, report["code"]), (1, "mapping_invalid"))
        report, code = acceptance.run_case(
            "P1-06",
            settings_loader=lambda _: VALUES,
            suite_loader=lambda *_: unittest.TestSuite(),
        )
        self.assertEqual((code, report["code"]), (1, "mapping_invalid"))

        def unavailable(*_):
            raise acceptance.MappingInvalid("private-test-trace-sentinel")

        report, code = acceptance.run_case(
            "P1-06", settings_loader=lambda _: VALUES, suite_loader=unavailable
        )
        self.assertEqual((code, report["code"]), (1, "mapping_invalid"))

    def test_missing_or_hostile_private_setup_fails_without_reflecting_values(self):
        for values in [
            {},
            {**VALUES, "POSTGRES_PORT": "private-test-trace-sentinel"},
            {**VALUES, "POSTGRES_PASSWORD": "bad\nprivate-test-trace-sentinel"},
        ]:
            with self.subTest(values=values):
                report, code = acceptance.run_case(
                    "P1-06",
                    settings_loader=lambda _, values=values: values,
                    suite_loader=lambda *_: self.fail("should not load"),
                )
                self.assertEqual(
                    (code, report["status"], report["code"]),
                    (2, "incomplete", "setup_required"),
                )
                self.assertNotIn("sentinel", json.dumps(report))

    def test_environment_is_derived_from_owned_setup_and_ambient_selectors_restored(
        self,
    ):
        ambient = {
            "PGHOST": "private-host-sentinel",
            "P1_POSTGRES_SCHEMA": "foreign-sentinel",
            "P1_MIGRATION_USER": "foreign-migrator",
            "P1_WORKER_SCHEMA": "foreign-worker",
        }
        with patch.dict(os.environ, ambient):
            with acceptance.configured_environment(VALUES):
                self.assertNotIn("PGHOST", os.environ)
                self.assertNotIn("P1_WORKER_SCHEMA", os.environ)
                self.assertEqual(os.environ["P1_POSTGRES_HOST"], "127.0.0.1")
                self.assertEqual(os.environ["P1_POSTGRES_USER"], "livekit_lab")
                self.assertEqual(os.environ["P1_MIGRATION_USER"], "continuity_migrator")
                self.assertEqual(os.environ["P1_RUN_POSTGRES_TESTS"], "1")
                self.assertEqual(os.environ["P1_POSTGRES_PASSWORD"], VALUES["POSTGRES_PASSWORD"])
            for key, value in ambient.items():
                self.assertEqual(os.environ[key], value)

    def test_environment_and_test_paths_restore_after_original_failure(self):
        import sys

        before = list(sys.path)
        with patch.dict(os.environ, {"P1_POSTGRES_SCHEMA": "ambient-original"}):
            with (
                self.assertRaisesRegex(RuntimeError, "original"),
                acceptance.configured_environment(VALUES),
                acceptance.test_imports(ROOT),
            ):
                raise RuntimeError("original")
            self.assertEqual(os.environ["P1_POSTGRES_SCHEMA"], "ambient-original")
        self.assertEqual(sys.path, before)

    def test_publisher_is_exclusive_private_and_refuses_symlink_overwrite(self):
        report, _ = self.run_case()
        with tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve()) as directory:
            path = Path(directory) / "report.json"
            acceptance.publish(path, report)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                acceptance.publish(path, report)
            alias = Path(directory) / "alias.json"
            alias.symlink_to(path)
            with self.assertRaises(OSError):
                acceptance.publish(alias, report)
            self.assertEqual(json.loads(path.read_text()), report)


if __name__ == "__main__":
    unittest.main()
