"""Offline closed-protocol negatives for actual P3 contract acceptance tooling."""

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
    "p3_contract_gate_fixture", ROOT / "local-setup/scripts/p3_contract_acceptance_check.py"
)
assert SPEC is not None and SPEC.loader is not None
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def report(case_id="P3-03"):
    return {
        "schema_version": 1,
        "status": "passed",
        "case_id": case_id,
        "mode": GATE.MODE,
        "tests": len(GATE.CASES[case_id]),
        "passed": len(GATE.CASES[case_id]),
        "errors": 0,
        "failures": 0,
        "skipped": 0,
        "duration_seconds": 1.5,
        "cleanup_complete": True,
        "child_terminations": 0,
        "case_results": [
            {"name": name, "status": "passed", "code": "ok"} for name in GATE.CASES[case_id]
        ],
        "node_version": "24.22.2",
    }


def context():
    return {
        "P3_ACCEPT_CASE_ID": "P3-03",
        "P3_ACCEPT_SCHEMA": "p1_work_acceptance_" + "a" * 32,
        "P3_ACCEPT_DIRECTORY": "/synthetic/work",
        "P3_ACCEPT_TOKEN": "a" * 43,
        "P3_ACCEPT_SPECIALIST_PORT": "12345",
        "P3_ACCEPT_BAD_PORT": "12346",
        "P3_ACCEPT_FIXTURE": "/synthetic/fixture.json",
    }


def server(case_id="P3-03"):
    return {
        "status": "passed",
        "cleanup_complete": True,
        "evaluations": 1,
        "invalid_responses": 5 if case_id == "P3-11" else 0,
        "invalid_cases": GATE.CODEC_CASES[:5] if case_id == "P3-11" else [],
        "raw_requests": 5 if case_id == "P3-11" else 0,
        "codec_cases": GATE.CODEC_CASES if case_id == "P3-11" else [],
        "active": 0,
        "requests": 0,
        "sockets": 0,
        "node_version": "24.22.2",
    }


class ContractGateTests(unittest.TestCase):
    def test_exact_reports_require_all_eight_or_twelve_names(self):
        for case_id, count in (("P3-03", 8), ("P3-11", 12)):
            value = report(case_id)
            self.assertEqual(GATE.validated_report(json.dumps(value).encode(), case_id), value)
            self.assertEqual(value["tests"], count)

    def test_counts_types_modes_cleanup_timing_and_case_identity_fail_closed(self):
        for key, bad in (
            ("tests", True),
            ("passed", 0),
            ("errors", 1),
            ("skipped", 1),
            ("failures", 1),
            ("duration_seconds", True),
            ("duration_seconds", 181),
            ("duration_seconds", float("nan")),
            ("cleanup_complete", 1),
            ("cleanup_complete", False),
            ("child_terminations", 1),
            ("mode", "offline"),
            ("case_id", "P3-11"),
            ("node_version", "20.1.0"),
        ):
            with self.subTest(key=key, bad=bad), self.assertRaises(GATE.GateError):
                value = report()
                value[key] = bad
                GATE.validated_report(json.dumps(value).encode(), "P3-03")

    def test_missing_duplicate_reordered_unknown_and_failed_inventory_reject(self):
        for kind in ("missing", "duplicate", "reorder", "unknown", "failed"):
            value = report("P3-11")
            if kind == "missing":
                value["case_results"].pop()
            elif kind == "duplicate":
                value["case_results"][0] = value["case_results"][1]
            elif kind == "reorder":
                value["case_results"].reverse()
            elif kind == "unknown":
                value["case_results"][0]["name"] = "invented"
            else:
                value["case_results"][0]["status"] = "failed"
            with self.assertRaises(GATE.GateError):
                GATE.validated_report(json.dumps(value).encode(), "P3-11")

    def test_duplicate_json_oversize_unknown_fields_and_truncation_reject(self):
        for raw in (
            b"",
            b"[]",
            b'{"status":"passed","status":"passed"}',
            b"x" * 65537,
            json.dumps(report()).encode()[:-1],
        ):
            with self.assertRaises(GATE.GateError):
                GATE.validated_report(raw, "P3-03")
        value = report()
        value["private"] = "forbidden"
        with self.assertRaises(GATE.GateError):
            GATE.validated_report(json.dumps(value).encode(), "P3-03")
        with self.assertRaises(GATE.GateError):
            GATE.validated_report(json.dumps(report()).encode(), "P3-99")

    def test_fixed_environment_separates_roles_and_excludes_ambient_secrets(self):
        values = {
            "POSTGRES_PORT": "15432",
            "POSTGRES_PASSWORD": "runtime",
            "POSTGRES_MIGRATION_PASSWORD": "owner",
            "OPENAI_API_KEY": "SECRET_SENTINEL",
        }
        with patch.dict(
            os.environ,
            {
                "PGSERVICE": "ambient",
                "NODE_OPTIONS": "ambient",
                "OPENAI_API_KEY": "SECRET_SENTINEL",
            },
        ):
            for mode in GATE.MODE_KEYS:
                value = GATE.child_environment(values, mode=mode, context=context())
                owner = mode in GATE.OWNER_MODES
                self.assertEqual("P3_ACCEPT_OWNER_PASSWORD" in value, owner)
                self.assertEqual("P3_ACCEPT_RUNTIME_PASSWORD" in value, not owner)
                self.assertFalse({"PGSERVICE", "NODE_OPTIONS", "OPENAI_API_KEY"} & set(value))
                self.assertNotIn("SECRET_SENTINEL", value.values())

    def test_missing_mixed_or_extra_environment_rejects(self):
        values = {
            "POSTGRES_PORT": "15432",
            "POSTGRES_PASSWORD": "runtime",
            "POSTGRES_MIGRATION_PASSWORD": "owner",
        }
        good = GATE.child_environment(values, mode="verify", context=context())
        for key in ("P3_ACCEPT_OWNER_PASSWORD", "PGSERVICE", "NODE_OPTIONS"):
            with self.assertRaises(GATE.GateError):
                GATE.validate_child_environment({**good, key: "forbidden"}, "verify")
        broken = dict(good)
        broken.pop("P3_ACCEPT_RUNTIME_PASSWORD")
        with self.assertRaises(GATE.GateError):
            GATE.validate_child_environment(broken, "verify")

    def test_server_requires_independent_variants_and_later_positive_progress(self):
        for case_id in GATE.CASES:
            value = server(case_id)
            self.assertTrue(GATE.validate_server(json.dumps(value).encode(), case_id, "24.22.2"))
        for key, bad in (
            ("evaluations", 0),
            ("evaluations", True),
            ("invalid_responses", 4),
            ("invalid_cases", list(reversed(GATE.CODEC_CASES[:5]))),
            ("codec_cases", []),
            ("raw_requests", 6),
            ("sockets", 1),
        ):
            value = server("P3-11")
            value[key] = bad
            self.assertFalse(GATE.validate_server(json.dumps(value).encode(), "P3-11", "24.22.2"))

    def test_clean_resources_do_not_qualify_missing_functional_progress(self):
        value = server()
        value["evaluations"] = 0
        raw = json.dumps(value).encode()
        self.assertTrue(GATE.validate_server_cleanup(raw, "24.22.2"))
        self.assertFalse(GATE.validate_server(raw, "P3-03", "24.22.2"))

    def test_report_is_fresh_exclusive_private_and_under_owned_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            target = Path(".local/validation/p3-contract-acceptance/result.json")
            GATE.retain_report(root, target, report())
            self.assertEqual((root / target).stat().st_mode & 0o777, 0o600)
            with self.assertRaises(GATE.GateError):
                GATE.retain_report(root, target, report())
            for bad in (
                Path("outside.json"),
                Path(".local/validation/p3-contract-acceptance/../other.json"),
            ):
                with self.assertRaises(GATE.GateError):
                    GATE.report_target(root, bad)

    def test_symlink_parent_rejects_before_write(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / ".local/validation").mkdir(parents=True)
            (root / "actual").mkdir()
            (root / ".local/validation/p3-contract-acceptance").symlink_to(
                root / "actual", target_is_directory=True
            )
            with self.assertRaises(GATE.GateError):
                GATE.report_target(root, Path(".local/validation/p3-contract-acceptance/a.json"))

    def test_missing_setup_never_launches_child(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()) as output:
            root = Path(temp).resolve()
            with (
                patch.object(GATE.core, "load_setup", side_effect=GATE.GateError("missing_setup")),
                patch.object(GATE, "OwnedProcess") as process,
            ):
                self.assertEqual(GATE.main(["--case", "P3-03"], root=root), 1)
            process.assert_not_called()
            self.assertEqual(json.loads(output.getvalue())["code"], "missing_setup")

    def test_existing_evidence_rejects_before_local_configuration(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            root = Path(temp).resolve()
            target = Path(".local/validation/p3-contract-acceptance/saved.json")
            GATE.retain_report(root, target, report())
            with patch.object(GATE.core, "load_setup") as setup:
                self.assertEqual(
                    GATE.main(["--case", "P3-03", "--report", str(target)], root=root), 1
                )
            setup.assert_not_called()
            self.assertEqual(json.loads((root / target).read_text()), report())
