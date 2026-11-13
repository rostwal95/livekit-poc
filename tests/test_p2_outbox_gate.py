"""Offline assertion/environment/report ownership negatives for P2 outbox qualification."""

from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "p2_outbox_gate_tested", ROOT / "local-setup/scripts/p2_outbox_check.py"
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
        "duration_seconds": 2.5,
        "cleanup_complete": True,
        "case_results": [{"name": n, "status": "passed", "code": "ok"} for n in GATE.CASE_NAMES],
        "node_version": "24.22.2",
        "blocking_graphs": {"upgrade": 1, "route": 2},
        "child_terminations": 1,
        "schema_version_observed": 3,
        "authority": "P2_reservation_permission_not_external_send_fence",
    }


class OutboxGateTests(unittest.TestCase):
    def invalid(self, value: dict[str, object]) -> None:
        with self.assertRaises(GATE.core.GateError):
            GATE.validated_report(json.dumps(value).encode())

    def test_exact_named_progress_report_passes(self) -> None:
        self.assertEqual(GATE.validated_report(json.dumps(passing()).encode()), passing())

    def test_missing_or_changed_named_assertion_fails(self) -> None:
        for value in ([], [{"name": "fake_pass", "status": "passed", "code": "ok"}]):
            report = passing()
            report["case_results"] = value
            self.invalid(report)

    def test_skip_failure_error_is_not_a_pass(self) -> None:
        for key in ("failures", "errors", "skipped"):
            report = passing()
            report[key] = 1
            self.invalid(report)

    def test_booleans_are_not_case_kill_schema_or_graph_counts(self) -> None:
        for key in (
            "schema_version",
            "tests",
            "passed",
            "child_terminations",
            "schema_version_observed",
        ):
            report = passing()
            report[key] = True
            self.invalid(report)
        report = passing()
        report["blocking_graphs"] = {"upgrade": True, "route": 2}
        self.invalid(report)

    def test_observed_lock_graph_not_elapsed_delay(self) -> None:
        report = passing()
        report["blocking_graphs"] = {"upgrade": 0, "route": 2}
        self.invalid(report)

    def test_cleanup_timeout_missing_runtime_cannot_pass(self) -> None:
        for key, value in (
            ("cleanup_complete", False),
            ("duration_seconds", 181),
            ("duration_seconds", float("nan")),
            ("duration_seconds", 0),
            ("node_version", "22.0.0"),
        ):
            report = passing()
            report[key] = value
            self.invalid(report)

    def test_unknown_extra_fields_and_wrong_authority_fail(self) -> None:
        report = passing()
        report["secret"] = "PRIVATE"
        self.invalid(report)
        report = passing()
        report["authority"] = "exactly_once_sms"
        self.invalid(report)

    def test_duplicate_json_evidence_is_rejected(self) -> None:
        with self.assertRaises(GATE.core.GateError):
            GATE.decode(b'{"status":"passed","status":"failed"}')

    def test_owner_and_runtime_closed_environments_are_separate(self) -> None:
        values = {
            "POSTGRES_PORT": "15432",
            "POSTGRES_PASSWORD": "runtime_sentinel",
            "POSTGRES_MIGRATION_PASSWORD": "owner_sentinel",
        }
        context = {
            "P2_OUTBOX_SCHEMA": "p2_outbox_test",
            "P2_OUTBOX_DIRECTORY": "/private/tmp",
            "P2_OUTBOX_CARRIER_PORT": "12345",
            "P2_OUTBOX_CARRIER_TOKEN": "fake_token",
        }
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "PRIVATE",
                "PGPASSWORD": "PRIVATE",
                "NODE_OPTIONS": "PRIVATE",
                "HTTP_PROXY": "PRIVATE",
            },
        ):
            owner = GATE.child_environment(values, context, owner=True)
            runtime = GATE.child_environment(values, context, owner=False)
        self.assertNotIn("P2_OUTBOX_RUNTIME_PASSWORD", owner)
        self.assertNotIn("P2_OUTBOX_OWNER_PASSWORD", runtime)
        self.assertNotIn("P2_OUTBOX_CARRIER_TOKEN", owner)
        self.assertEqual(runtime["P2_OUTBOX_RUNTIME_PASSWORD"], "runtime_sentinel")
        for env in (owner, runtime):
            for key in ("OPENAI_API_KEY", "PGPASSWORD", "NODE_OPTIONS", "HTTP_PROXY"):
                self.assertNotIn(key, env)
        with self.assertRaises(GATE.core.GateError):
            GATE.child_environment(
                values, {**context, "P2_OUTBOX_OWNER_PASSWORD": "PRIVATE"}, owner=False
            )

    def test_child_stage_requires_exact_mode_keys_and_true_boolean(self) -> None:
        value = {
            "status": "passed",
            "mode": "seed",
            "cleanup_complete": True,
            "node_version": "24.22.2",
        }
        self.assertEqual(GATE.validated_stage(json.dumps(value).encode(), "seed"), value)
        for changed in ({"mode": "other"}, {"cleanup_complete": 1}, {"extra": "sentinel"}):
            with self.assertRaises(GATE.core.GateError):
                GATE.validated_stage(json.dumps({**value, **changed}).encode(), "seed")

    def test_cleanup_preserves_primary_and_attempts_remaining_owners(self) -> None:
        visited: list[str] = []
        state = {"cleanup_complete": False}

        async def fail() -> None:
            visited.append("socket")
            raise OSError("PRIVATE_SECONDARY")

        async def backup() -> None:
            visited.append("backup")

        async def schema() -> None:
            visited.append("schema")

        async def run() -> None:
            try:
                raise GATE.core.GateError("original_stage_failure")
            finally:
                await GATE.cleanup_actions((fail, backup, schema), state, sys.exception())

        with self.assertRaises(GATE.core.GateError) as caught:
            asyncio.run(run())
        self.assertEqual(caught.exception.code, "original_stage_failure")
        self.assertFalse(state["cleanup_complete"])
        self.assertEqual(visited, ["socket", "backup", "schema"])

    def test_cleanup_failure_without_primary_cannot_pass(self) -> None:
        async def fail() -> None:
            raise OSError("PRIVATE")

        with self.assertRaises(GATE.core.GateError) as caught:
            asyncio.run(GATE.cleanup_actions((fail,), {"cleanup_complete": False}, None))
        self.assertEqual(caught.exception.code, "cleanup_incomplete")

    def test_cleanup_budget_is_reserved_inside_final_deadline(self) -> None:
        work, final = GATE.deadlines(100.0)
        self.assertEqual(work, 265.0)
        self.assertEqual(final, 280.0)
        self.assertEqual(final - work, GATE.CLEANUP_SECONDS)

    def test_report_retention_never_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "proof.json"
            GATE.retain(path, passing())
            with self.assertRaises(GATE.core.GateError):
                GATE.retain(path, passing())

    def test_failed_report_write_is_nonpassing(self) -> None:
        async def run(*_args: object) -> dict[str, object]:
            return deepcopy(passing())

        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve()
            root.chmod(0o700)
            path = root / ".local/validation/p2-outbox/new.json"
            with (
                patch.object(GATE, "run", run),
                patch.object(
                    GATE, "retain", side_effect=GATE.core.GateError("report_retention_failed")
                ),
                redirect_stdout(io.StringIO()) as out,
            ):
                self.assertEqual(GATE.main(["--report", str(path)], root=root), 1)
            self.assertEqual(json.loads(out.getvalue())["code"], "report_retention_failed")

    def test_unsafe_target_is_rejected_before_run(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve()
            root.chmod(0o700)
            with self.assertRaises(GATE.core.GateError):
                GATE.target_path(root, Path("../unsafe.json"))


if __name__ == "__main__":
    unittest.main()
