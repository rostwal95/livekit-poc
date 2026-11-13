"""Offline acceptance selector ownership and fail-closed protocol tests."""

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
    "p3_acceptance_fixture", ROOT / "local-setup/scripts/p3_acceptance.py"
)
assert SPEC is not None and SPEC.loader is not None
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)
import p3_completion_check as COMPLETION


def component():
    return {
        "schema_version": 1,
        "status": "passed",
        "mode": COMPLETION.MODE,
        "tests": 13,
        "passed": 13,
        "errors": 0,
        "failures": 0,
        "skipped": 0,
        "duration_seconds": 1.25,
        "cleanup_complete": True,
        "child_terminations": 1,
        "case_results": [
            {"name": name, "status": "passed", "code": "ok"} for name in COMPLETION.CASE_NAMES
        ],
        "node_version": "24.22.2",
        "case_authority": "actual_p1_v4_exact_confirmation_and_guarded_intent",
        "invocation_authority": "runner_requires_p1_issued_attempt_http_service_separately_authenticated",
    }


class P3AcceptanceTests(unittest.TestCase):
    def test_complete_selected_component_and_numeric_envelope(self):
        self.assertEqual(
            GATE.validate_component(json.dumps(component()).encode(), "P3-01"), component()
        )
        result = GATE.envelope("P3-01", "passed", 13, 1.0)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["mode"], "lab")
        self.assertEqual(
            set(result),
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

    def test_partial_skipped_unclean_wrong_inventory_or_wrong_mode_cannot_pass(self):
        for field, bad in (
            ("tests", 0),
            ("tests", True),
            ("cleanup_complete", False),
            ("skipped", 1),
            ("mode", "offline"),
            ("case_results", []),
            ("passed", 12),
        ):
            value = component()
            value[field] = bad
            with self.subTest(field=field), self.assertRaises(GATE.AcceptanceError):
                GATE.validate_component(json.dumps(value).encode(), "P3-01")

    def test_duplicate_truncated_oversized_or_nonselected_component_rejected(self):
        for raw, case in (
            (b"{}", "P3-02"),
            (b"", "P3-01"),
            (b"x" * 32769, "P3-01"),
            (b'{"tests":13,"tests":13}', "P3-01"),
            (b"[]", "P3-01"),
        ):
            with self.subTest(case=case), self.assertRaises(GATE.AcceptanceError):
                GATE.validate_component(raw, case)

    def test_contract_selectors_bind_full_inventory_and_exact_case_identity(self):
        import p3_contract_acceptance_check as contract

        for case_id in ("P3-03", "P3-11"):
            names = contract.CASES[case_id]
            value = {
                "schema_version": 1,
                "status": "passed",
                "case_id": case_id,
                "mode": contract.MODE,
                "tests": len(names),
                "passed": len(names),
                "errors": 0,
                "failures": 0,
                "skipped": 0,
                "duration_seconds": 1.0,
                "cleanup_complete": True,
                "child_terminations": 0,
                "case_results": [
                    {"name": name, "status": "passed", "code": "ok"} for name in names
                ],
                "node_version": "24.22.2",
            }
            self.assertEqual(GATE.validate_component(json.dumps(value).encode(), case_id), value)
            value["case_id"] = "P3-01"
            with self.assertRaises(GATE.AcceptanceError):
                GATE.validate_component(json.dumps(value).encode(), case_id)

    def test_environment_forwards_no_provider_pg_proxy_or_interpreter_selectors(self):
        with patch.dict(
            os.environ,
            {
                "PATH": "/usr/bin",
                "OPENAI_API_KEY": "PRIVATE_SENTINEL",
                "P3_COMPLETE_OWNER_PASSWORD": "OWNER_SENTINEL",
                "PGSERVICE": "PRIVATE_SENTINEL",
                "PYTHONPATH": "PRIVATE_SENTINEL",
                "NODE_OPTIONS": "PRIVATE_SENTINEL",
                "HTTPS_PROXY": "PRIVATE_SENTINEL",
            },
            clear=True,
        ):
            actual = GATE.child_environment()
        self.assertEqual(actual, {"PATH": "/usr/bin", "CI": "1", "NO_COLOR": "1"})

    def test_report_is_fresh_owned_private_and_inside_allowed_roots(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            target = root / ".local/harness/run/private-report/result.json"
            GATE.retain(root, target, {"status": "synthetic"})
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(GATE.AcceptanceError):
                GATE.retain(root, target, {"status": "changed"})
            self.assertEqual(json.loads(target.read_text()), {"status": "synthetic"})
            for bad in (root / "outside.json", root / ".local/validation/../outside.json"):
                with self.assertRaises(GATE.AcceptanceError):
                    GATE.report_target(root, bad)
            link = root / ".local/validation/link"
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(root, target_is_directory=True)
            with self.assertRaises(GATE.AcceptanceError):
                GATE.report_target(root, link / "result.json")

    def test_component_reader_rejects_symlink_hardlink_directory_and_oversize(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            value = root / "value"
            value.write_bytes(b"{}")
            link = root / "link"
            link.symlink_to(value)
            with self.assertRaises(OSError):
                GATE.read_component(link)
            os.link(value, root / "hard")
            with self.assertRaises(GATE.AcceptanceError):
                GATE.read_component(value)
            with self.assertRaises(GATE.AcceptanceError):
                GATE.read_component(root)
            huge = root / "huge"
            huge.write_bytes(b"x" * 32769)
            with self.assertRaises(GATE.AcceptanceError):
                GATE.read_component(huge)

    def call(self, root, side_effect=None, value=None):
        target = Path(".local/validation/result.json")
        output = io.StringIO()
        with (
            patch.object(
                GATE, "run_component", side_effect=side_effect, return_value=value
            ) as child,
            redirect_stdout(output),
        ):
            code = GATE.main(["--case", "P3-01", "--report", str(target)], root=root)
        return code, json.loads(output.getvalue()), child

    def test_missing_setup_cannot_pass_or_invoke_provider(self):
        with tempfile.TemporaryDirectory() as temp:
            code, result, _ = self.call(
                Path(temp).resolve(), GATE.AcceptanceError("setup_required")
            )
        self.assertEqual((code, result["status"], result["testCount"]), (2, "incomplete", 0))

    def test_unexpected_private_error_is_fixed_and_reported_not_reflected(self):
        with tempfile.TemporaryDirectory() as temp:
            code, result, _ = self.call(Path(temp).resolve(), RuntimeError("PRIVATE_SENTINEL"))
        self.assertEqual((code, result["status"], result["code"]), (1, "failed", "test_error"))
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(result))

    def test_fresh_success_retains_exact_protocol_and_evidence_without_duplicate_run(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            code, result, child = self.call(root, value=component())
            self.assertEqual((code, result["testCount"]), (0, 13))
            child.assert_called_once()
            self.assertEqual(
                json.loads((root / ".local/validation/result.json").read_text()), result
            )
            code, rejected, second = self.call(root, value=component())
            self.assertEqual((code, rejected["code"]), (1, "mapping_invalid"))
            second.assert_not_called()

    def test_report_write_failure_cannot_print_success(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.object(GATE, "retain", side_effect=OSError("PRIVATE_SENTINEL")),
        ):
            code, result, _ = self.call(Path(temp).resolve(), value=component())
        self.assertEqual((code, result["status"], result["code"]), (1, "failed", "mapping_invalid"))
