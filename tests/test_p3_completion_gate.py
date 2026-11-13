"""Offline completion-gate negatives only: no PostgreSQL, Node or providers."""

import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "p3_completion_gate_fixture", ROOT / "local-setup/scripts/p3_completion_check.py"
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
        "child_terminations": 1,
        "case_results": [
            {"name": name, "status": "passed", "code": "ok"} for name in GATE.CASE_NAMES
        ],
        "node_version": "24.22.2",
        "case_authority": "actual_p1_v4_exact_confirmation_and_guarded_intent",
        "invocation_authority": "runner_requires_p1_issued_attempt_http_service_separately_authenticated",
    }


def context():
    return {
        "P3_COMPLETE_WORK_SCHEMA": "p1_work_completion_" + "a" * 32,
        "P3_COMPLETE_CASE_SCHEMA": "p3_completion_" + "b" * 32,
        "P3_COMPLETE_DIRECTORY": "/synthetic/completion",
        "P3_COMPLETE_RECEIVER_ID": "00000000-0000-4000-8000-000000000001",
        "P3_COMPLETE_TOKEN": "A" * 43,
        "P3_COMPLETE_SPECIALIST_PORT": "12345",
        "P3_COMPLETE_COMMIT_MARKER": "/synthetic/committed.reached",
    }


def values():
    return {
        "POSTGRES_PORT": "15432",
        "POSTGRES_PASSWORD": "runtime_fixture",
        "POSTGRES_MIGRATION_PASSWORD": "owner_fixture",
        "OPENAI_API_KEY": "PRIVATE_PROVIDER_SENTINEL",
    }


class CompletionGateTests(unittest.TestCase):
    def test_exact_complete_nonzero_report_passes(self):
        self.assertEqual(GATE.validated_report(json.dumps(report()).encode()), report())
        self.assertEqual(len(GATE.CASE_NAMES), 13)

    def test_boolean_skip_missing_wrong_authority_or_late_success_fails(self):
        for key, bad in (
            ("tests", 0),
            ("tests", True),
            ("passed", 0),
            ("skipped", 1),
            ("errors", 1),
            ("failures", 1),
            ("duration_seconds", True),
            ("duration_seconds", 181),
            ("duration_seconds", float("nan")),
            ("cleanup_complete", False),
            ("cleanup_complete", 1),
            ("child_terminations", 0),
            ("schema_version", True),
            ("case_authority", "atomic_action_authority"),
            ("invocation_authority", "unissued_probe"),
        ):
            raw = report()
            raw[key] = bad
            with self.subTest(key=key, bad=bad), self.assertRaises(GATE.GateError):
                GATE.validated_report(json.dumps(raw).encode())

    def test_missing_duplicate_changed_and_reordered_cases_cannot_pass(self):
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

    def test_oversized_duplicate_json_unknown_field_and_truncation_fail(self):
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
        value = report()
        value["private_field"] = "forbidden"
        with self.assertRaises(GATE.GateError):
            GATE.validated_report(json.dumps(value).encode())

    def test_owner_runtime_environment_roles_are_exclusive_and_finite(self):
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "PRIVATE_AMBIENT_SENTINEL",
                "PGSERVICE": "ambient",
                "NODE_OPTIONS": "ambient",
            },
        ):
            for mode in GATE.MODE_KEYS:
                env = GATE.child_environment(values(), mode=mode, context=context())
                owner = mode in GATE.OWNER_MODES
                self.assertEqual("P3_COMPLETE_OWNER_PASSWORD" in env, owner)
                self.assertEqual("P3_COMPLETE_RUNTIME_PASSWORD" in env, not owner)
                for key in ("OPENAI_API_KEY", "PGSERVICE", "NODE_OPTIONS"):
                    self.assertNotIn(key, env)
                self.assertFalse(any("PRIVATE_" in value for value in env.values()))

    def test_unexpected_missing_or_mixed_role_child_environment_fails(self):
        good = GATE.child_environment(values(), mode="exercise", context=context())
        for key, value in (
            ("P3_COMPLETE_OWNER_PASSWORD", "owner"),
            ("NODE_OPTIONS", "injected"),
            ("PGSERVICE", "injected"),
        ):
            with self.assertRaises(GATE.GateError):
                GATE.validate_child_environment({**good, key: value}, "exercise")
        bad = dict(good)
        bad.pop("P3_COMPLETE_RUNTIME_PASSWORD")
        with self.assertRaises(GATE.GateError):
            GATE.validate_child_environment(bad, "exercise")
        with self.assertRaises(GATE.GateError):
            GATE.child_environment(values(), mode="unknown", context=context())

    def test_report_is_exclusive_under_owned_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            target = Path(".local/validation/p3-completion/result.json")
            GATE.retain_report(root, target, report())
            self.assertEqual(json.loads((root / target).read_text())["tests"], 13)
            with self.assertRaises(GATE.GateError):
                GATE.retain_report(root, target, report())
            for bad in (
                Path("outside.json"),
                Path(".local/validation/p3-completion/../other.json"),
            ):
                with self.assertRaises(GATE.GateError):
                    GATE.report_target(root, bad)

    def test_symlink_report_parent_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / ".local/validation").mkdir(parents=True)
            actual = root / "actual"
            actual.mkdir()
            (root / ".local/validation/p3-completion").symlink_to(actual, target_is_directory=True)
            with self.assertRaises(GATE.GateError):
                GATE.report_target(root, Path(".local/validation/p3-completion/result.json"))

    def test_server_invocation_count_is_exact_and_not_coerced(self):
        value = {
            "status": "passed",
            "cleanup_complete": True,
            "active": 0,
            "requests": 0,
            "sockets": 0,
            "node_version": "24.22.2",
            "invocation_count": 4,
        }
        self.assertTrue(GATE.validated_server(json.dumps(value).encode(), "24.22.2"))
        partial = {**value, "invocation_count": 2}
        self.assertTrue(GATE.validated_server_cleanup(json.dumps(partial).encode(), "24.22.2"))
        self.assertFalse(GATE.validated_server(json.dumps(partial).encode(), "24.22.2"))
        for bad in (True, 5, 7):
            changed = dict(value)
            changed["invocation_count"] = bad
            self.assertFalse(GATE.validated_server(json.dumps(changed).encode(), "24.22.2"))

    def test_capture_budget_covers_all_children_and_rejects_exhaustion(self):
        budget = GATE.core.CaptureBudget()
        for _ in range(11):
            self.assertEqual(budget.reserve(10240), 5120)
        self.assertEqual(budget.available, 131072 - 11 * 10240)
        budget.reserve(131072)
        with self.assertRaises(GATE.GateError):
            budget.reserve()

    def test_missing_setup_fails_before_process_or_secret_read(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()) as output:
            root = Path(temp).resolve()
            with (
                patch.object(GATE.core, "load_setup", side_effect=GATE.GateError("missing_setup")),
                patch.object(GATE, "OwnedProcess") as process,
            ):
                status = GATE.main([], root=root)
            self.assertEqual(status, 1)
            process.assert_not_called()
            self.assertEqual(json.loads(output.getvalue())["code"], "missing_setup")

    def test_existing_report_refuses_before_setup(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            root = Path(temp).resolve()
            target = Path(".local/validation/p3-completion/old.json")
            GATE.retain_report(root, target, report())
            with patch.object(GATE.core, "load_setup") as setup:
                status = GATE.main(["--report", str(target)], root=root)
            self.assertEqual(status, 1)
            setup.assert_not_called()
            self.assertEqual(json.loads((root / target).read_text()), report())
