"""Offline protocol and role-environment checks for the explicit confirmation gate."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "p2_confirmation_gate_tested", ROOT / "local-setup/scripts/p2_confirmation_check.py"
)
assert SPEC is not None and SPEC.loader is not None
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def passing() -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": "passed",
        "mode": GATE.MODE,
        "tests": len(GATE.CASE_NAMES),
        "passed": len(GATE.CASE_NAMES),
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "duration_seconds": 1.5,
        "cleanup_complete": True,
        "node_version": "24.22.2",
        "case_results": [
            {"name": name, "status": "passed", "code": "ok"} for name in GATE.CASE_NAMES
        ],
        "blocking_graph": 2,
        "prompt_registry_version": 1,
        "authority": "public_P1_atomic_exact_quote_command_no_revocation_fence",
    }


class ConfirmationGateTests(unittest.TestCase):
    def check_invalid(self, value: dict[str, object]) -> None:
        with self.assertRaises(GATE.core.GateError):
            GATE.validated_report(json.dumps(value).encode())

    def test_exact_useful_dual_authority_report(self) -> None:
        self.assertEqual(GATE.validated_report(json.dumps(passing()).encode()), passing())

    def test_missing_assertion_is_not_a_pass(self) -> None:
        value = passing()
        value["case_results"] = []
        self.check_invalid(value)

    def test_rejects_skipped_and_nonzero_failures(self) -> None:
        for name in ("skipped", "failures", "errors"):
            with self.subTest(name=name):
                value = passing()
                value[name] = 1
                self.check_invalid(value)

    def test_boolean_is_not_an_executed_integer(self) -> None:
        value = passing()
        value["schema_version"] = True
        self.check_invalid(value)

    def test_no_elapsed_time_substitute_for_actual_blocking_graph(self) -> None:
        value = passing()
        value["blocking_graph"] = 0
        self.check_invalid(value)

    def test_cleanup_and_timeout_cannot_pass(self) -> None:
        for key, new in (
            ("cleanup_complete", False),
            ("duration_seconds", 181),
            ("duration_seconds", float("nan")),
        ):
            value = passing()
            value[key] = new
            self.check_invalid(value)

    def test_unknown_node_or_undeclared_report_field_rejected(self) -> None:
        value = passing()
        value["node_version"] = "22.0.0"
        self.check_invalid(value)
        value = passing()
        value["private_context"] = "sentinel"
        self.check_invalid(value)

    def test_case_identity_and_status_are_exact(self) -> None:
        value = passing()
        cases = deepcopy(value["case_results"])
        assert isinstance(cases, list)
        cases[0]["name"] = "unrelated_green_test"
        value["case_results"] = cases
        self.check_invalid(value)

    def test_duplicate_json_fields_fail(self) -> None:
        with self.assertRaises(GATE.core.GateError):
            GATE.decode(b'{"status":"passed","status":"failed"}')

    def test_owner_and_runtime_credentials_are_separate(self) -> None:
        values = {
            "POSTGRES_PORT": "15432",
            "POSTGRES_PASSWORD": "runtime_sentinel",
            "POSTGRES_MIGRATION_PASSWORD": "owner_sentinel",
        }
        common = {
            "P2_CONFIRM_INBOX_SCHEMA": "p2_inbox_test",
            "P2_CONFIRM_PROMPT_SCHEMA": "p2_prompt_test",
            "P2_CONFIRM_DIRECTORY": "/private/tmp",
        }
        runtime_context = {
            **common,
            "P2_CONFIRM_QUOTES_FILE": "/private/tmp/quotes.json",
            "P2_CONFIRM_BRIDGE_PORT": "1234",
            "P2_CONFIRM_BRIDGE_TOKEN": "a" * 43,
            "P2_CONFIRM_PUBLISH_MAIN_TOKEN": "b" * 43,
            "P2_CONFIRM_PUBLISH_RACE_TOKEN": "c" * 43,
        }
        with patch.dict(
            os.environ,
            {"PGHOSTADDR": "private", "NODE_OPTIONS": "private", "OPENAI_API_KEY": "private"},
        ):
            owner = GATE.child_environment(values, common, owner=True)
            runtime = GATE.child_environment(values, runtime_context, owner=False)
        with self.assertRaises(GATE.core.GateError):
            GATE.child_environment(
                values, {**common, "P2_CONFIRM_OWNER_PASSWORD": "no"}, owner=False
            )
        self.assertNotIn("P2_CONFIRM_RUNTIME_PASSWORD", owner)
        self.assertNotIn("P2_CONFIRM_OWNER_PASSWORD", runtime)
        for environment in (owner, runtime):
            self.assertFalse({"PGHOSTADDR", "NODE_OPTIONS", "OPENAI_API_KEY"} & set(environment))

    def test_passing_report_write_failure_is_nonpassing(self) -> None:
        async def successful_run(*_args: object) -> dict[str, object]:
            return passing()

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            with (
                patch.object(GATE, "run", new=successful_run),
                patch.object(GATE, "retain", side_effect=OSError("private-sentinel")),
                redirect_stdout(io.StringIO()) as output,
            ):
                code = GATE.main([], root=root)
            self.assertEqual(code, 1)
            value = json.loads(output.getvalue())
            self.assertEqual(value["status"], "failed")
            self.assertEqual(value["code"], "report_write_failed")
            self.assertNotIn("private-sentinel", output.getvalue())

    def test_evidence_cannot_escape_or_replace_an_existing_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            with self.assertRaises(GATE.core.GateError):
                GATE.target_path(root, root / "elsewhere.json")
            target = GATE.target_path(root, Path(".local/validation/p2-confirmation/selected.json"))
            GATE.retain(target, {"status": "failed"})
            with self.assertRaises(GATE.core.GateError):
                GATE.target_path(root, target)


if __name__ == "__main__":
    unittest.main()
