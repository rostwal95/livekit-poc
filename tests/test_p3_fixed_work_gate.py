"""Independent pure host boundaries; no database, compiler, service or provider."""

from __future__ import annotations

import contextlib
import copy
import importlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "local-setup/scripts"))
gate = importlib.import_module("p3_durable_fixed_policy_check")


def encoded(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), allow_nan=True).encode()


def report(installed: bool = False):
    return {
        "schema_version": 1,
        "status": "passed",
        "mode": "local_fixed_work_installed" if installed else "local_fixed_work_source",
        "tests": 12,
        "passed": 12,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "duration_seconds": 1.0,
        "child_commands": 29 if installed else 8,
        "package_assertions": 8 if installed else 0,
        "cleanup_complete": True,
        "code": "ok",
        "stage": "complete",
        "retained_index_sha256": "a" * 64,
        "case_results": [{"name": name, "status": "passed"} for name in gate.CASES],
    }


class DurableFixedWorkGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def environment(self, mode: str):
        value = {
            "PATH": "/usr/bin",
            "LANG": "C",
            "CI": "1",
            "NO_COLOR": "1",
            "P3_FIXED_WORK_DIRECTORY": str(self.root),
        }
        if mode == "serve":
            value.update(
                P3_FIXED_WORK_INPUT_FILE=str(self.root / "fixed-work-input.json"),
                P3_FIXED_WORK_ENDPOINT_FILE=str(self.root / "fixed-work-endpoint.json"),
                P3_FIXED_WORK_STOP_FILE=str(self.root / "fixed-work.stop"),
                P3_FIXED_WORK_TOKEN="A" * 43,
            )
        else:
            value.update(
                P3_FIXED_WORK_WORK_SCHEMA="p1_work_fixedv2_" + "a" * 32,
                P3_FIXED_WORK_CASE_SCHEMA="p3_completion_" + "a" * 32,
                P3_FIXED_WORK_PG_PORT="5432",
            )
            if mode in {"install", "cleanup"}:
                value["P3_FIXED_WORK_OWNER_PASSWORD"] = "PRIVATE_ENV_SENTINEL"
            else:
                value["P3_FIXED_WORK_RUNTIME_PASSWORD"] = "PRIVATE_ENV_SENTINEL"
                value["P3_FIXED_WORK_TOKEN"] = "A" * 43
        return value

    def test_plan_is_pure_before_any_setup_or_run_construction(self) -> None:
        for installed in (False, True):
            stdout = io.StringIO()
            with (
                patch.object(gate, "DurableWorkRun", side_effect=AssertionError("started")),
                patch.object(gate, "private_directory", side_effect=AssertionError("created")),
                contextlib.redirect_stdout(stdout),
            ):
                self.assertEqual(
                    gate.main(
                        ["--plan", *(["--installed"] if installed else [])],
                        root=self.root / "missing",
                    ),
                    0,
                )
            value = json.loads(stdout.getvalue())
            self.assertEqual(value["status"], "planned")
            self.assertEqual(
                (value["tests"], value["children"], value["package_assertions"]),
                (12, 29 if installed else 8, 8 if installed else 0),
            )
            self.assertEqual(tuple(value["cases"]), gate.CASES)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_unknown_argument_output_does_not_echo_private_values(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as exit_code:
            gate.main(["--unknown", "PRIVATE_ARG_SENTINEL"], root=self.root)
        self.assertEqual(exit_code.exception.code, 2)
        self.assertNotIn("PRIVATE_ARG_SENTINEL", stderr.getvalue())
        self.assertEqual(json.loads(stderr.getvalue())["code"], "invalid_input")

    def test_source_installed_and_failed_reports_are_distinct(self) -> None:
        for installed in (False, True):
            value = report(installed)
            self.assertEqual(gate.validated_report(encoded(value)), value)
        failed = report()
        failed.update(
            status="failed",
            passed=0,
            failures=1,
            code="component_failed",
            stage="exercise",
            cleanup_complete=False,
            child_commands=0,
            retained_index_sha256=None,
            case_results=[],
        )
        self.assertEqual(gate.validated_report(encoded(failed))["status"], "failed")

    def test_forged_success_and_changed_closed_report_fields_fail(self) -> None:
        changes = (
            ("schema_version", True),
            ("status", "planned"),
            ("mode", "local_fixed_work_other"),
            ("tests", 0),
            ("passed", 11),
            ("failures", 1),
            ("errors", 1),
            ("skipped", 1),
            ("duration_seconds", True),
            ("duration_seconds", float("nan")),
            ("duration_seconds", float("inf")),
            ("duration_seconds", 181),
            ("child_commands", 7),
            ("package_assertions", 8),
            ("cleanup_complete", False),
            ("cleanup_complete", 1),
            ("code", "component_failed"),
            ("stage", "exercise"),
            ("retained_index_sha256", None),
            ("case_results", []),
            ("unknown", "PRIVATE_SENTINEL"),
        )
        for key, value in changes:
            with self.subTest(key=key, value=value):
                changed = report()
                changed[key] = value
                with self.assertRaises(gate.GateError):
                    gate.validated_report(encoded(changed))
        for key, value in (
            ("child_commands", 28),
            ("package_assertions", 0),
            ("duration_seconds", 361),
        ):
            changed = report(True)
            changed[key] = value
            with self.subTest(installed=key), self.assertRaises(gate.GateError):
                gate.validated_report(encoded(changed))

    def test_only_original_closed_success_modes_are_accepted(self) -> None:
        for mode in gate.PYTHON_MODES:
            value = {
                "schema_version": 1,
                "status": "passed",
                "mode": mode,
                "cleanup_complete": True,
            }
            gate.validate_reply(encoded(value), mode)
            for key, replacement in (
                ("cleanup_complete", 1),
                ("mode", "foreign_mode"),
                ("extra", "PRIVATE_SENTINEL"),
            ):
                changed = copy.deepcopy(value)
                changed[key] = replacement
                with self.subTest(mode=mode, key=key), self.assertRaises(gate.GateError):
                    gate.validate_reply(encoded(changed), mode)
        with self.assertRaises(gate.GateError):
            gate.validate_reply(
                encoded(
                    {
                        "schema_version": 1,
                        "status": "passed",
                        "mode": "foreign_mode",
                        "cleanup_complete": True,
                    }
                ),
                "foreign_mode",
            )

    def test_environment_roles_exclude_each_other_and_ambient_selectors(self) -> None:
        for mode in (*sorted(gate.PYTHON_MODES), "serve"):
            value = self.environment(mode)
            gate.validate_environment(value, mode)
            for key in (
                "PGPASSWORD",
                "PYTHONPATH",
                "NODE_OPTIONS",
                "HTTP_PROXY",
                "OPENAI_API_KEY",
                "DEEPGRAM_API_KEY",
                "ELEVENLABS_API_KEY",
            ):
                with self.subTest(mode=mode, extra=key), self.assertRaises(gate.GateError):
                    gate.validate_environment({**value, key: "PRIVATE_SENTINEL"}, mode)
            wrong_role = (
                "P3_FIXED_WORK_RUNTIME_PASSWORD"
                if mode in {"install", "cleanup"}
                else "P3_FIXED_WORK_OWNER_PASSWORD"
            )
            with self.subTest(mode=mode, credential=wrong_role), self.assertRaises(gate.GateError):
                gate.validate_environment({**value, wrong_role: "PRIVATE_SENTINEL"}, mode)
        with self.assertRaises(gate.GateError):
            gate.validate_environment(self.environment("exercise"), "foreign_role")

    def test_environment_scope_schema_port_and_token_shape(self) -> None:
        value = self.environment("exercise")
        for key, replacement in (
            ("P3_FIXED_WORK_WORK_SCHEMA", "p1_work_foreign"),
            ("P3_FIXED_WORK_CASE_SCHEMA", "public"),
            ("P3_FIXED_WORK_PG_PORT", "0"),
            ("P3_FIXED_WORK_PG_PORT", "65536"),
            ("P3_FIXED_WORK_PG_PORT", "05432"),
            ("P3_FIXED_WORK_TOKEN", "bad"),
            ("P3_FIXED_WORK_DIRECTORY", str(self.root / ".." / self.root.name)),
        ):
            with self.subTest(key=key, replacement=replacement), self.assertRaises(gate.GateError):
                gate.validate_environment({**value, key: replacement}, "exercise")
        serve = self.environment("serve")
        with self.assertRaises(gate.GateError):
            gate.validate_environment(
                {**serve, "P3_FIXED_WORK_STOP_FILE": str(self.root / "foreign.stop")}, "serve"
            )

    def test_expiry_wait_requires_both_real_database_observation_and_receiver_time(self) -> None:
        owner = Mock()
        owner.db_now.side_effect = [99, 100, 100]
        with (
            patch.object(gate.time, "time_ns", side_effect=[99_000_000, 100_000_000]) as host,
            patch.object(gate.time, "monotonic", side_effect=[0, 0.01, 0.02]),
            patch.object(gate.time, "sleep") as pause,
        ):
            self.assertEqual(gate.DurableWorkRun.after_db(owner, 100, 1, require_host=True), 100)
        self.assertEqual((owner.db_now.call_count, host.call_count, pause.call_count), (3, 2, 2))
        owner = Mock()
        owner.db_now.return_value = 99
        with (
            patch.object(gate.time, "time_ns", return_value=1_000_000_000) as host,
            patch.object(gate.time, "monotonic", return_value=0),
            self.assertRaises(gate.GateError) as failure,
        ):
            gate.DurableWorkRun.after_db(owner, 100, 0, require_host=True)
        self.assertEqual(failure.exception.code, "deadline_exceeded")
        host.assert_not_called()
        owner.db_now.return_value = 100
        with patch.object(gate.time, "time_ns", side_effect=AssertionError("host clock used")):
            self.assertEqual(gate.DurableWorkRun.after_db(owner, 100, 1), 100)

    def test_report_and_artifact_namespaces_cannot_reuse_or_alias(self) -> None:
        requested = Path(".local/validation/p3-fixed-work/check.json")
        target = gate.target_path(self.root, requested)
        self.assertEqual(target, self.root / requested)
        for bad in (
            target,
            Path("foreign/check.json"),
            Path(".local/validation/p3-fixed-work/../check.json"),
            Path(".local/validation/p3-fixed-work/nested/check.json"),
        ):
            with self.subTest(path=bad), self.assertRaises(gate.GateError):
                gate.target_path(self.root, bad)
        target.parent.mkdir(parents=True)
        artifact = target.with_name(target.stem + "-artifacts")
        artifact.symlink_to(self.root / "missing-artifacts", target_is_directory=True)
        with self.assertRaises(gate.GateError):
            gate.target_path(self.root, requested)
        artifact.unlink()
        target.write_bytes(b"original")
        with self.assertRaises(gate.GateError):
            gate.target_path(self.root, requested)
        self.assertEqual(target.read_bytes(), b"original")


if __name__ == "__main__":
    unittest.main()
