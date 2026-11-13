"""Offline processing-gate safety checks; no PostgreSQL, provider or source writes."""

import importlib.util
import io
import json
import os
import stat
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "p3_processing_gate_fixture", ROOT / "local-setup/scripts/p3_processing_check.py"
)
assert SPEC is not None and SPEC.loader is not None
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def report():
    return {
        "schema_version": 1,
        "status": "passed",
        "mode": GATE.MODE,
        "tests": len(GATE.CASE_NAMES),
        "passed": len(GATE.CASE_NAMES),
        "errors": 0,
        "failures": 0,
        "skipped": 0,
        "duration_seconds": 2.5,
        "cleanup_complete": True,
        "child_terminations": 5,
        "blocking_graphs_observed": 1,
        "case_results": [
            {"name": name, "status": "passed", "code": "ok"} for name in GATE.CASE_NAMES
        ],
        "source_authority": "actual_p1_work_v4_existing_delivery_and_receiver",
        "processing_authority": "p3_projection_v2_terminal_ack_no_source_ack_or_action",
        "backup_restore": "validated_versioned_profile_rows_not_pg_dump",
        "provider_calls": False,
    }


def context():
    return {
        "P3_PROCESS_WORK_SCHEMA": "p1_work_processing_" + "a" * 32,
        "P3_PROCESS_CASE_SCHEMA": "p3_completion_" + "a" * 32,
        "P3_PROCESS_SCHEMA": "p3_projection_" + "a" * 32,
        "P3_PROCESS_DIRECTORY": "/synthetic/private",
        "P3_PROCESS_TOKEN": "A" * 43,
        "P3_PROCESS_BARRIER": "/synthetic/private/before_commit.reached",
    }


def values():
    return {
        "POSTGRES_PORT": "15432",
        "POSTGRES_PASSWORD": "runtime_fixture",
        "POSTGRES_MIGRATION_PASSWORD": "owner_fixture",
        "OPENAI_API_KEY": "PRIVATE_PROVIDER_SENTINEL",
    }


class ProcessingGateTests(unittest.TestCase):
    def test_complete_report_and_frozen_inventory_pass(self):
        self.assertEqual(GATE.validated_report(json.dumps(report()).encode()), report())
        self.assertEqual(len(GATE.CASE_NAMES), 16)

    def test_incomplete_unsafe_or_coerced_report_fails(self):
        for key, value in (
            ("schema_version", True),
            ("tests", 0),
            ("tests", True),
            ("passed", 15),
            ("errors", 1),
            ("failures", 1),
            ("skipped", 1),
            ("child_terminations", 4),
            ("child_terminations", True),
            ("blocking_graphs_observed", 0),
            ("blocking_graphs_observed", True),
            ("backup_restore", "pg_dump"),
            ("cleanup_complete", False),
            ("cleanup_complete", 1),
            ("duration_seconds", True),
            ("duration_seconds", 0),
            ("duration_seconds", 181),
            ("duration_seconds", float("nan")),
            ("duration_seconds", float("inf")),
            ("provider_calls", 0),
            ("provider_calls", True),
            ("source_authority", "synthetic_mock"),
            ("processing_authority", "current_action_permission"),
        ):
            value_report = report()
            value_report[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(GATE.GateError):
                GATE.validated_report(json.dumps(value_report).encode())

    def test_missing_duplicate_reordered_or_failed_case_cannot_pass(self):
        for kind in ("missing", "duplicate", "unknown", "failed", "order"):
            value = report()
            if kind == "missing":
                value["case_results"].pop()
            elif kind == "duplicate":
                value["case_results"][0] = value["case_results"][1]
            elif kind == "unknown":
                value["case_results"][0]["name"] = "invented_case"
            elif kind == "failed":
                value["case_results"][0]["status"] = "failed"
            else:
                value["case_results"].reverse()
            with self.assertRaises(GATE.GateError):
                GATE.validated_report(json.dumps(value).encode())

    def test_unknown_duplicate_truncated_or_oversized_json_fails(self):
        good = json.dumps(report()).encode()
        for raw in (
            good[:-1],
            b"[]",
            b"",
            b"x" * (GATE.MAX_REPORT_BYTES + 1),
            b'{"status":"passed","status":"passed"}',
        ):
            with self.assertRaises(GATE.GateError):
                GATE.validated_report(raw)
        changed = report()
        changed["private_body"] = "forbidden"
        with self.assertRaises(GATE.GateError):
            GATE.validated_report(json.dumps(changed).encode())

    def test_every_mode_excludes_other_role_and_ambient_injection(self):
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "PRIVATE_AMBIENT_SENTINEL",
                "PGSERVICE": "ambient",
                "PYTHONPATH": "ambient",
                "NODE_OPTIONS": "ambient",
            },
        ):
            for mode in GATE.MODE_KEYS:
                env = GATE.child_environment(values(), mode=mode, context=context())
                owner = mode in GATE.OWNER_MODES
                self.assertEqual("P3_PROCESS_OWNER_PASSWORD" in env, owner)
                self.assertEqual("P3_PROCESS_RUNTIME_PASSWORD" in env, not owner)
                for key in ("OPENAI_API_KEY", "PGSERVICE", "PYTHONPATH", "NODE_OPTIONS"):
                    self.assertNotIn(key, env)
                self.assertFalse(any("PRIVATE_" in value for value in env.values()))

    def test_mixed_missing_unknown_and_empty_child_environment_fails(self):
        good = GATE.child_environment(values(), mode="verify-gap", context=context())
        for key, value in (
            ("P3_PROCESS_OWNER_PASSWORD", "owner"),
            ("NODE_OPTIONS", "injected"),
            ("PGSERVICE", "injected"),
            ("P3_PROCESS_TOKEN", ""),
        ):
            with self.assertRaises(GATE.GateError):
                GATE.validate_child_environment({**good, key: value}, "verify-gap")
        missing = dict(good)
        missing.pop("P3_PROCESS_RUNTIME_PASSWORD")
        with self.assertRaises(GATE.GateError):
            GATE.validate_child_environment(missing, "verify-gap")
        with self.assertRaises(GATE.GateError):
            GATE.child_environment(values(), mode="unknown", context=context())
        with self.assertRaises(GATE.GateError):
            GATE.child_environment(values(), mode="verify-gap", context={})

    def test_report_is_private_exclusive_and_owned(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            target = Path(".local/validation/p3-processing/result.json")
            GATE.retain_report(root, target, report())
            self.assertEqual(json.loads((root / target).read_text()), report())
            self.assertEqual(stat.S_IMODE((root / target).stat().st_mode), 0o600)
            with self.assertRaises(GATE.GateError):
                GATE.retain_report(root, target, report())
            for bad in (
                Path("outside.json"),
                Path(".local/validation/p3-processing/../other.json"),
            ):
                with self.assertRaises(GATE.GateError):
                    GATE.report_target(root, bad)

    def test_symlink_report_parent_cannot_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / ".local/validation").mkdir(parents=True)
            actual = root / "actual"
            actual.mkdir()
            (root / ".local/validation/p3-processing").symlink_to(actual, target_is_directory=True)
            with self.assertRaises(GATE.GateError):
                GATE.report_target(root, Path(".local/validation/p3-processing/result.json"))

    def test_capture_budget_is_shared_finite_and_exhaustion_fails(self):
        budget = GATE.core.CaptureBudget()
        for _ in range(17):
            self.assertEqual(budget.reserve(4096), 2048)
        self.assertEqual(budget.available, 131072 - 17 * 4096)
        budget.reserve(131072)
        with self.assertRaises(GATE.GateError):
            budget.reserve()

    def test_missing_setup_stops_before_process_or_secret_read(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()) as output:
            with (
                patch.object(GATE.core, "load_setup", side_effect=GATE.GateError("missing_setup")),
                patch.object(GATE, "OwnedProcess") as process,
            ):
                result = GATE.main([], root=Path(temp).resolve())
            self.assertEqual(result, 1)
            process.assert_not_called()
            self.assertEqual(json.loads(output.getvalue())["code"], "missing_setup")

    def test_existing_evidence_stops_before_setup_and_preserves_bytes(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            root = Path(temp).resolve()
            target = Path(".local/validation/p3-processing/old.json")
            GATE.retain_report(root, target, report())
            original = (root / target).read_bytes()
            with patch.object(GATE.core, "load_setup") as setup:
                result = GATE.main(["--report", str(target)], root=root)
            self.assertEqual(result, 1)
            setup.assert_not_called()
            self.assertEqual((root / target).read_bytes(), original)

    def test_evidence_write_failure_cannot_exit_success(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()) as output:
            with (
                patch.object(GATE.core, "load_setup", side_effect=GATE.GateError("missing_setup")),
                patch.object(GATE, "retain_report", side_effect=OSError("PRIVATE_SENTINEL")),
            ):
                result = GATE.main([], root=Path(temp).resolve())
            self.assertEqual(result, 1)
            self.assertNotIn("PRIVATE_SENTINEL", output.getvalue())
            self.assertEqual(json.loads(output.getvalue())["status"], "failed")

    def test_cleanup_failure_preserves_first_failure_and_cannot_pass(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()) as output:
            root = Path(temp).resolve()
            for name in (
                "projects/delegation-reliability/tests/pg_processing_cases.py",
                ".venv/bin/python",
            ):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            setup = SimpleNamespace(load_settings=values, SetupError=ValueError)
            responses = [
                {"status": "passed", "work_version": 4, "case_version": 4, "projection_version": 1},
                GATE.GateError("seed_failed"),
                GATE.GateError("cleanup_failed"),
            ]
            with (
                patch.object(GATE.core, "load_setup", return_value=setup),
                patch.object(GATE, "run_child", side_effect=responses) as child,
            ):
                status = GATE.main([], root=root)
            self.assertEqual(status, 1)
            self.assertEqual(child.call_count, 3)
            result = json.loads(output.getvalue())
            self.assertEqual(result["code"], "seed_failed")
            self.assertIs(result["cleanup_complete"], False)

    def test_actual_offline_child_validates_framing_and_is_owned(self):
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp).resolve()
            environment = GATE.child_environment(values(), mode="verify", context=context())
            result = GATE.run_child(
                [sys.executable, "-I", "-c", 'print(\'{"status":"passed","cases":[]}\')', "verify"],
                cwd=work,
                environment=environment,
                output=work / "good",
                deadline=time.monotonic() + 5,
                budget=GATE.core.CaptureBudget(),
            )
            self.assertEqual(result, {"status": "passed", "cases": []})
            for name, script in (
                ("noise", 'print("PRIVATE_SENTINEL");print(\'{"status":"passed"}\')'),
                (
                    "stderr",
                    'import sys;print("PRIVATE_SENTINEL",file=sys.stderr);print(\'{"status":"passed"}\')',
                ),
                ("exit", "raise SystemExit(1)"),
            ):
                with self.assertRaises(GATE.GateError) as caught:
                    GATE.run_child(
                        [sys.executable, "-I", "-c", script, "verify"],
                        cwd=work,
                        environment=environment,
                        output=work / name,
                        deadline=time.monotonic() + 5,
                        budget=GATE.core.CaptureBudget(),
                    )
                self.assertNotIn("PRIVATE_SENTINEL", str(caught.exception))

    def test_unreaped_or_failed_child_can_never_return_known(self):
        for cleanup, returncode, stderr in (
            (True, 0, b""),
            (False, None, b""),
            (False, 1, b""),
            (False, 0, b"PRIVATE_SENTINEL"),
        ):
            child = SimpleNamespace(
                cleanup_failed=cleanup,
                returncode=returncode,
                wait=lambda observed=returncode, **kwargs: SimpleNamespace(returncode=observed),
            )
            budget = SimpleNamespace(
                read=lambda *args, observed=stderr: (b'{"status":"passed"}', observed)
            )
            with self.assertRaises(GATE.GateError):
                GATE.checked_child(
                    child,
                    output=Path("synthetic"),
                    limit=2048,
                    budget=budget,
                    deadline=time.monotonic() + 2,
                    mode="verify",
                )

    def qualification(self, root):
        for name in (
            "projects/delegation-reliability/tests/pg_processing_cases.py",
            ".venv/bin/python",
        ):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        setup = SimpleNamespace(load_settings=values, SetupError=ValueError)
        observations = {
            "install": {"work_version": 4, "case_version": 4, "projection_version": 1},
            "seed": {"source_results": 7, "projected_results": 7},
            "restore-upgrade": {
                "projection_version": 2,
                "backup_restore": True,
                "cases": [GATE.CASE_NAMES[0]],
            },
            "verify-gap": {"cases": [GATE.CASE_NAMES[n] for n in (1, 2, 3, 4, 6)]},
            "verify-ack-after": {"cases": [GATE.CASE_NAMES[7]]},
            "resume-receiver": {"cases": [GATE.CASE_NAMES[n] for n in (5, 9, 11, 12)]},
            "locks": {"blocked": True},
            "verify": {"cases": [GATE.CASE_NAMES[n] for n in (10, 13, 14)]},
            "owner-check": {"cases": [GATE.CASE_NAMES[15]]},
            "cleanup": {"schemas_removed": True},
        }

        class Child:
            def __init__(self, command, **kwargs):
                self.mode = command[-1]
                self.cleanup_failed = False
                self.returncode = 0

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def wait_for_barrier(self, *args, **kwargs):
                pass

            def release_barrier(self, *args, **kwargs):
                pass

            def kill(self, **kwargs):
                self.returncode = -9
                return SimpleNamespace(killed=True, returncode=-9)

            def wait(self, **kwargs):
                return SimpleNamespace(returncode=0)

        def child(command, **kwargs):
            return {"status": "passed", **observations[command[-1]]}

        def capture(output, limit):
            if output.name == "race-a":
                return b'{"status":"passed","cases":[]}', b""
            if output.name == "race-b":
                return json.dumps({"status": "passed", "cases": [GATE.CASE_NAMES[8]]}).encode(), b""
            return b"", b""

        return (
            patch.object(GATE.core, "load_setup", return_value=setup),
            patch.object(GATE, "run_child", side_effect=child),
            patch.object(GATE, "OwnedProcess", side_effect=Child),
            patch.object(GATE.core.CaptureBudget, "read", side_effect=capture),
        )

    def test_complete_protocol_reaches_exact_success_and_records_all_actual_counts(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()) as output:
            root = Path(temp).resolve()
            setup, child, process, capture = self.qualification(root)
            with setup, child, process, capture:
                result = GATE.main([], root=root)
            self.assertEqual(result, 0)
            record = json.loads(output.getvalue())
            self.assertEqual(GATE.validated_report(json.dumps(record).encode()), record)
            self.assertEqual(record["child_terminations"], 5)
            self.assertEqual(record["blocking_graphs_observed"], 1)
            self.assertEqual(len(record["case_results"]), 16)

    def test_failed_final_evidence_write_cannot_report_success_after_all_cases(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()) as output:
            root = Path(temp).resolve()
            setup, child, process, capture = self.qualification(root)
            with (
                setup,
                child,
                process,
                capture,
                patch.object(GATE, "retain_report", side_effect=OSError("PRIVATE_SENTINEL")),
            ):
                result = GATE.main([], root=root)
            self.assertEqual(result, 1)
            record = json.loads(output.getvalue())
            self.assertEqual(record["status"], "failed")
            self.assertNotIn("PRIVATE_SENTINEL", output.getvalue())

    def test_child_boolean_and_integer_substitution_cannot_pass(self):
        for value, expected in (
            ({"projection_version": True}, {"projection_version": 1}),
            ({"blocked": 1}, {"blocked": True}),
            ({"schemas_removed": 1}, {"schemas_removed": True}),
            ({"backup_restore": 1}, {"backup_restore": True}),
            ({"source_results": 7.0}, {"source_results": 7}),
        ):
            self.assertFalse(GATE.exact_child(value, expected))
        self.assertTrue(
            GATE.exact_child({"schema_version": 1, "cases": []}, {"cases": [], "schema_version": 1})
        )
