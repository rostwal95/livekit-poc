"""Offline negative fixtures for the explicit P2 PostgreSQL gate, never database tests."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "p2_postgres_gate_fixture", ROOT / "local-setup/scripts/p2_postgres_check.py"
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("P2 PostgreSQL gate source is missing")
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def valid_report(example=False):
    names = GATE.EXAMPLE_CASE_NAMES if example else GATE.CASE_NAMES
    report = {
        "schema_version": 1,
        "status": "passed",
        "mode": "local_synthetic_postgres_example" if example else "local_synthetic_postgres",
        "tests": len(names),
        "passed": len(names),
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "duration_seconds": 1.5,
        "cleanup_complete": True,
        "child_terminations": 0 if example else 4,
        "case_results": [{"name": name, "status": "passed", "code": "ok"} for name in names],
        "node_version": "24.22.2",
    }
    if example:
        report["demo_observations"] = [
            {
                "phase": phase,
                "receipt_id": "12345678-1234-4234-8234-123456789abc",
                "operation_key": "22345678-1234-4234-8234-123456789abc",
                "acceptance_sequence": "1",
                "replayed": position == 1,
                "processing_state": "pending",
                "execution": "not_executed",
            }
            for position, phase in enumerate(("accepted", "replayed"))
        ]
    return report


class P2PostgresReportTests(unittest.TestCase):
    def test_complete_nonzero_report_and_supported_runtime_are_accepted(self):
        report = valid_report()
        self.assertEqual(GATE.validated_report(json.dumps(report).encode()), report)
        for version in ("24.22.2", "24.23.0", "26.13.0", "26.14.1"):
            self.assertTrue(GATE.supported_node(version))
        for version in ("24.22.1", "24.0.0", "26.12.9", "27.0.0", "26.013.0", None, True):
            self.assertFalse(GATE.supported_node(version))

    def test_example_selection_requires_exact_real_observations_and_no_forced_kill(self):
        report = valid_report(example=True)
        self.assertEqual(GATE.validated_report(json.dumps(report).encode(), example=True), report)
        with self.assertRaises(GATE.GateError):
            GATE.validated_report(json.dumps(report).encode())
        with self.assertRaises(GATE.GateError):
            GATE.validated_report(json.dumps(valid_report()).encode(), example=True)
        changed = valid_report(example=True)
        changed["child_terminations"] = 1
        with self.assertRaises(GATE.GateError):
            GATE.validated_report(json.dumps(changed).encode(), example=True)

    def test_dispatch_selection_requires_real_cases_and_one_process_kill(self):
        report = valid_report()
        names = GATE.DISPATCH_CASE_NAMES
        report.update(
            mode="local_synthetic_postgres_dispatch",
            tests=len(names),
            passed=len(names),
            child_terminations=1,
            case_results=[{"name": name, "status": "passed", "code": "ok"} for name in names],
        )
        self.assertEqual(GATE.validated_report(json.dumps(report).encode(), dispatch=True), report)
        with self.assertRaises(GATE.GateError):
            GATE.validated_report(json.dumps(report).encode())
        for change in (
            {"child_terminations": 0},
            {"child_terminations": 2},
            {"mode": "local_synthetic_postgres"},
            {"case_results": []},
        ):
            with self.subTest(change=change), self.assertRaises(GATE.GateError):
                GATE.validated_report(json.dumps({**report, **change}).encode(), dispatch=True)
        with self.assertRaises(GATE.GateError):
            GATE.validated_report(json.dumps(report).encode(), example=True, dispatch=True)

    def test_gateway_selection_requires_exact_process_recovery_and_cleanup(self):
        report = valid_report()
        names = GATE.GATEWAY_CASE_NAMES
        report.update(
            mode="local_synthetic_postgres_gateway",
            tests=len(names),
            passed=len(names),
            child_terminations=1,
            case_results=[{"name": name, "status": "passed", "code": "ok"} for name in names],
        )
        self.assertEqual(GATE.validated_report(json.dumps(report).encode(), gateway=True), report)
        for change in (
            {"child_terminations": 0},
            {"child_terminations": 2},
            {"cleanup_complete": False},
            {"mode": "local_synthetic_postgres"},
            {"case_results": []},
        ):
            with self.subTest(change=change), self.assertRaises(GATE.GateError):
                GATE.validated_report(json.dumps({**report, **change}).encode(), gateway=True)
        with self.assertRaises(GATE.GateError):
            GATE.validated_report(json.dumps(report).encode(), gateway=True, dispatch=True)

    def test_agent_selection_requires_one_real_model_process_kill(self):
        report = valid_report()
        names = GATE.AGENT_CASE_NAMES
        report.update(
            mode="local_synthetic_postgres_agent",
            tests=len(names),
            passed=len(names),
            child_terminations=1,
            case_results=[{"name": name, "status": "passed", "code": "ok"} for name in names],
        )
        self.assertEqual(GATE.validated_report(json.dumps(report).encode(), agent=True), report)
        for change in (
            {"child_terminations": 0},
            {"cleanup_complete": False},
            {"case_results": []},
            {"mode": "local_synthetic_postgres"},
        ):
            with self.assertRaises(GATE.GateError):
                GATE.validated_report(json.dumps({**report, **change}).encode(), agent=True)
        with self.assertRaises(GATE.GateError):
            GATE.validated_report(json.dumps(report).encode(), agent=True, gateway=True)

    def test_malformed_or_contradictory_example_projection_cannot_pass(self):
        mutations = [
            ("receipt_id", "PRIVATE_VALUE"),
            ("operation_key", []),
            ("acceptance_sequence", "0"),
            ("replayed", 1),
            ("phase", "accepted"),
            ("processing_state", "completed"),
            ("execution", "executed"),
            ("receipt_id", "32345678-1234-4234-8234-123456789abc"),
        ]
        for key, value in mutations:
            report = valid_report(example=True)
            report["demo_observations"][1][key] = value
            with self.subTest(field=key), self.assertRaises(GATE.GateError):
                GATE.validated_report(json.dumps(report).encode(), example=True)
        for observations in (
            [],
            None,
            [valid_report(example=True)["demo_observations"][0]],
            [{"secret": "PRIVATE_VALUE"}],
        ):
            report = valid_report(example=True)
            report["demo_observations"] = observations
            with self.assertRaises(GATE.GateError):
                GATE.validated_report(json.dumps(report).encode(), example=True)
        extra = valid_report(example=True)
        extra["demo_observations"][0]["body"] = "PRIVATE_VALUE"
        with self.assertRaises(GATE.GateError):
            GATE.validated_report(json.dumps(extra).encode(), example=True)

    def test_missing_unknown_duplicate_fields_and_malformed_json_are_rejected(self):
        original = json.dumps(valid_report())
        bad = [b"", b"not-json", b"{}", b"x" * 16385]
        missing = valid_report()
        missing.pop("cleanup_complete")
        bad.append(json.dumps(missing).encode())
        unknown = {**valid_report(), "unexpected": True}
        bad.append(json.dumps(unknown).encode())
        bad.append(
            original.replace(
                '"status": "passed"', '"status": "failed", "status": "passed"', 1
            ).encode()
        )
        for raw in bad:
            with self.subTest(size=len(raw)), self.assertRaises(GATE.GateError):
                GATE.validated_report(raw)

    def test_boolean_counts_zero_skips_missing_process_and_cleanup_failures_cannot_pass(self):
        for key, value in (
            ("schema_version", True),
            ("tests", True),
            ("passed", 0),
            ("failures", 1),
            ("errors", 1),
            ("skipped", 1),
            ("child_terminations", 0),
            ("child_terminations", True),
            ("cleanup_complete", False),
            ("cleanup_complete", 1),
            ("duration_seconds", True),
            ("duration_seconds", 0),
            ("duration_seconds", float("nan")),
            ("duration_seconds", float("inf")),
            ("duration_seconds", 10**1000),
            ("node_version", "24.0.0"),
            ("status", []),
        ):
            report = {**valid_report(), key: value}
            with self.subTest(field=key), self.assertRaises(GATE.GateError):
                GATE.validated_report(json.dumps(report).encode())
        empty = valid_report()
        empty.update(tests=0, passed=0, case_results=[])
        with self.assertRaises(GATE.GateError):
            GATE.validated_report(json.dumps(empty).encode())

    def test_duplicate_missing_and_contradictory_case_results_cannot_pass(self):
        duplicate = valid_report()
        duplicate["case_results"][-1] = duplicate["case_results"][0]
        missing = valid_report()
        missing["case_results"].pop()
        unknown = valid_report()
        unknown["case_results"][0]["name"] = "not_a_registered_case"
        failed = valid_report()
        failed["case_results"][0].update(status="failed", code="assertion_failed")
        malformed = valid_report()
        malformed["case_results"][0]["code"] = []
        for report in (duplicate, missing, unknown, failed, malformed):
            with self.assertRaises(GATE.GateError):
                GATE.validated_report(json.dumps(report).encode())

    def test_incomplete_failed_execution_is_preserved_as_failure(self):
        report = valid_report()
        report.update(
            status="failed",
            tests=1,
            passed=0,
            failures=1,
            child_terminations=0,
            case_results=[
                {"name": GATE.CASE_NAMES[0], "status": "failed", "code": "assertion_failed"}
            ],
        )
        self.assertEqual(GATE.validated_report(json.dumps(report).encode())["status"], "failed")


class P2PostgresSetupTests(unittest.TestCase):
    def test_child_environment_drops_ambient_credentials_and_target_overrides(self):
        hostile = {
            "PATH": "/synthetic/path",
            "HOME": "/synthetic/home",
            "PGHOST": "external.invalid",
            "PGPASSWORD": "AMBIENT_PRIVATE_SENTINEL",
            "P1_POSTGRES_PASSWORD": "AMBIENT_PRIVATE_SENTINEL",
            "P2_POSTGRES_PORT": "1",
            "P2_MIGRATION_PASSWORD": "AMBIENT_PRIVATE_SENTINEL",
            "OPENAI_API_KEY": "AMBIENT_PRIVATE_SENTINEL",
            "DEEPGRAM_API_KEY": "AMBIENT_PRIVATE_SENTINEL",
            "ELEVEN_API_KEY": "AMBIENT_PRIVATE_SENTINEL",
            "NODE_OPTIONS": "--import=external.invalid",
            "OTEL_EXPORTER_OTLP_HEADERS": "AMBIENT_PRIVATE_SENTINEL",
        }
        selected = {
            "POSTGRES_PORT": "15432",
            "POSTGRES_PASSWORD": "runtime_fixture_" + "r" * 32,
            "POSTGRES_MIGRATION_PASSWORD": "migration_fixture_" + "m" * 32,
            "UNUSED_SECRET": "AMBIENT_PRIVATE_SENTINEL",
        }
        with patch.dict(os.environ, hostile, clear=True):
            child = GATE.child_environment(selected)
        self.assertEqual(
            set(child),
            {
                "PATH",
                "HOME",
                "CI",
                "NO_COLOR",
                "P2_POSTGRES_PORT",
                "P2_RUNTIME_PASSWORD",
                "P2_MIGRATION_PASSWORD",
            },
        )
        self.assertEqual(child["P2_POSTGRES_PORT"], "15432")
        self.assertEqual(child["P2_RUNTIME_PASSWORD"], selected["POSTGRES_PASSWORD"])
        self.assertEqual(child["P2_MIGRATION_PASSWORD"], selected["POSTGRES_MIGRATION_PASSWORD"])
        self.assertNotIn("AMBIENT_PRIVATE_SENTINEL", json.dumps(child))

    def test_setup_source_loads_without_implicit_private_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            setup = root / "local-setup"
            setup.mkdir()
            (setup / "stack.py").write_text(
                "def load_settings():\n    return {'fixture': 'synthetic'}\n"
            )
            previous = set(sys.modules)
            module = GATE.load_setup(root)
            self.assertEqual(module.load_settings(), {"fixture": "synthetic"})
            self.assertFalse(
                any(name.startswith("p2_postgres_setup_") for name in set(sys.modules) - previous)
            )
            self.assertFalse((setup / ".secrets.env").exists())

    def test_missing_setup_fails_without_launching_or_echoing_private_error(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(GATE, "OwnedProcess") as child,
        ):
            root = Path(directory).resolve()
            setup = root / "local-setup"
            setup.mkdir()
            (setup / "stack.py").write_text(
                "class SetupError(Exception): pass\ndef load_settings():\n    raise SetupError('PRIVATE_SETUP_SENTINEL')\n"
            )
            output = io.StringIO()
            with patch("sys.stdout", output):
                self.assertEqual(GATE.main([], root=root), 1)
            report = json.loads(output.getvalue())
            self.assertEqual(report["code"], "missing_setup")
            self.assertNotIn("PRIVATE_SETUP_SENTINEL", output.getvalue())
            child.assert_not_called()

    def test_report_retention_is_private_exclusive_and_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            relative = Path(".local/validation/p2-postgres/report.json")
            GATE.retain_report(root, relative, valid_report())
            target = root / relative
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                GATE.retain_report(root, relative, valid_report())
            with self.assertRaises(GATE.GateError):
                GATE.retain_report(root, Path("outside.json"), valid_report())


if __name__ == "__main__":
    unittest.main()
