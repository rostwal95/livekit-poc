"""Report and actual process/cleanup regressions for the image qualification gate."""

from __future__ import annotations

import copy
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "p3_document_gate_under_test", ROOT / "local-setup/scripts/p3_document_check.py"
)
assert SPEC is not None and SPEC.loader is not None
GATE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = GATE
SPEC.loader.exec_module(GATE)


class DocumentReportTests(unittest.TestCase):
    def valid(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "status": "passed",
            "mode": GATE.MODE,
            "tests": 20,
            "passed": 20,
            "errors": 0,
            "failures": 0,
            "skipped": 0,
            "cleanup_complete": True,
            "provider_calls": 8,
            "vision_inference_claimed": False,
            "P1_image_execution_claimed": False,
            "child_commands": 5,
            "direct_child_commands": 5,
            "nested_package_children": 0,
            "worker_records": 9,
            "canonical_http_results": 5,
            "duration_seconds": 1.25,
            "case_results": GATE.cases(GATE.CASE_NAMES),
            "retained_index_sha256": "a" * 64,
            "package_assertions": 0,
            "code": "ok",
            "stage": "complete",
        }

    def test_source_and_installed_exact_success_inventory(self) -> None:
        value = self.valid()
        GATE.validated_report(json.dumps(value).encode())
        value.update(
            mode=GATE.MODE + "_installed",
            direct_child_commands=9,
            nested_package_children=17,
            child_commands=26,
            package_assertions=8,
        )
        GATE.validated_report(json.dumps(value).encode())

    def test_required_skips_cleanup_inference_authority_and_wrong_counts_never_pass(self) -> None:
        for field, wrong in (
            ("skipped", 1),
            ("cleanup_complete", 1),
            ("cleanup_complete", False),
            ("vision_inference_claimed", True),
            ("P1_image_execution_claimed", True),
            ("provider_calls", 9),
            ("child_commands", 0),
            ("worker_records", 8),
            ("tests", True),
            ("nested_package_children", 17),
            ("duration_seconds", -1),
            ("mode", []),
            ("mode", {}),
            ("mode", None),
        ):
            with self.subTest(field=field, wrong=wrong):
                value = self.valid()
                value[field] = wrong
                with self.assertRaises(GATE.GateError):
                    GATE.validated_report(json.dumps(value).encode())

    def test_missing_extra_duplicate_and_reordered_case_results_fail(self) -> None:
        value = self.valid()
        for rows in (
            GATE.cases(GATE.CASE_NAMES[:-1]),
            list(reversed(GATE.cases(GATE.CASE_NAMES))),
            GATE.cases(GATE.CASE_NAMES[:-1] + (GATE.CASE_NAMES[0],)),
        ):
            value["case_results"] = rows
            with self.assertRaises(GATE.GateError):
                GATE.validated_report(json.dumps(value).encode())
        value = self.valid()
        value["future_field"] = "unexpected"
        with self.assertRaises(GATE.GateError):
            GATE.validated_report(json.dumps(value).encode())

    def test_additive_package_inventory_rejects_equal_count_substitutions(self) -> None:
        package = GATE.packages
        payload = {name: b"fixture" for name in package.P3_RUNTIME_FILES}
        modules, examples = set(package.SPECIALIST_MODULES), set(package.SPECIALIST_EXAMPLES)
        package.validate_current_payload_inventory(payload, modules, examples)
        wrong = dict(payload)
        wrong.pop("delegation_reliability/document.py")
        wrong["delegation_reliability/hidden_executor.py"] = b"unexpected"
        with self.assertRaises(package.GateError):
            package.validate_current_payload_inventory(wrong, modules, examples)
        with self.assertRaises(package.GateError):
            package.validate_current_payload_inventory(
                payload, modules - {"document"} | {"hidden-executor"}, examples
            )
        with self.assertRaises(package.GateError):
            package.validate_current_payload_inventory(
                payload, modules, examples - {"document-http.mjs"} | {"hidden-executor.mjs"}
            )

    def test_enrollment_is_exact_and_rejects_malformed_or_reordered_setup(self) -> None:
        value = {
            "schema_version": 1,
            "kind": "document.image-references",
            "records": [
                {
                    "name": n,
                    "reference": {
                        "source_id": "document_" + n,
                        "version": "document_v1",
                        "sha256": "a" * 64,
                        "media_type": "image/png",
                        "byte_length": 64,
                        "width": 640,
                        "height": 360,
                    },
                }
                for n in GATE.ENROLLMENT_NAMES
            ],
        }
        GATE.validate_enrollment(json.dumps(value).encode())
        for wrong in (None, True, [], {}, {"source_id": "URL"}):
            invalid = copy.deepcopy(value)
            invalid["records"][0]["reference"] = wrong
            with self.assertRaises(GATE.GateError):
                GATE.validate_enrollment(json.dumps(invalid).encode())
        for field, wrong in (
            ("width", True),
            ("height", 2049),
            ("byte_length", 2097153),
            ("version", "source_v1"),
            ("sha256", "A" * 64),
        ):
            invalid = copy.deepcopy(value)
            invalid["records"][0]["reference"][field] = wrong
            with self.assertRaises(GATE.GateError):
                GATE.validate_enrollment(json.dumps(invalid).encode())
        value["records"].reverse()
        with self.assertRaises(GATE.GateError):
            GATE.validate_enrollment(json.dumps(value).encode())

    def test_failure_sidecar_accepts_only_finite_diagnostics(self) -> None:
        value = {
            "schema_version": 1,
            "status": "failed",
            "mode": "node-server",
            "stage": "serve",
            "code": "fixture_failed",
            "cleanup_complete": False,
        }
        GATE.validate_failure_sidecar(json.dumps(value).encode(), node=True)
        for field, wrong in (
            ("code", "secret error body"),
            ("code", "ok"),
            ("stage", "http://private"),
            ("mode", []),
            ("cleanup_complete", 1),
        ):
            invalid = {**value, field: wrong}
            with self.assertRaises(GATE.GateError):
                GATE.validate_failure_sidecar(json.dumps(invalid).encode(), node=True)
        with self.assertRaises(GATE.GateError):
            GATE.validate_failure_sidecar(
                json.dumps({**value, "message": "unsafe"}).encode(), node=True
            )

    def test_plan_starts_no_runtime_or_private_settings(self) -> None:
        for options in (["--plan"], ["--plan", "--installed"]):
            output = io.StringIO()
            with (
                patch.object(GATE, "DocumentRun", side_effect=AssertionError("runtime_started")),
                redirect_stdout(output),
            ):
                self.assertEqual(GATE.main(options), 0)
            value = json.loads(output.getvalue())
            self.assertEqual(value["status"], "not_started")
            self.assertEqual(len(value["cases"]), 20)
            self.assertIs(value["provider_calls"], False)


class DocumentOwnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory(prefix="p3-document-owner-test-")
        self.root = Path(self.directory.name).resolve()
        self.report = self.root / "test.json"
        with patch.object(GATE.packages.shutil, "which", return_value=sys.executable):
            self.run = GATE.DocumentRun(self.root, self.report, installed=False)

    def tearDown(self) -> None:
        for child in self.run.children:
            child.close()
        if self.run.work.exists():
            self.run.nested_cleanup_known = True
            try:
                self.run.cleanup_resources()
            except (GATE.GateError, GATE.packages.GateError):
                if self.run.work.exists():
                    shutil.rmtree(self.run.work)
        self.directory.cleanup()

    def test_actual_live_child_blocks_dependent_work_deletion_after_false_close_request(
        self,
    ) -> None:
        child = self.run.start(
            [sys.executable, "-I", "-c", "import time;time.sleep(30)"],
            stage="node-server",
            environment=self.run.fixture_environment("node-server"),
        )
        with (
            patch.object(child, "close", return_value=None),
            self.assertRaises((GATE.GateError, GATE.packages.GateError)),
        ):
            self.run.cleanup_resources()
        self.assertIsNone(child.returncode)
        self.assertTrue(self.run.work.exists())
        self.assertTrue((self.run.retained / "unresolved-work.json").is_file())
        child.close()
        self.assertIsInstance(child.returncode, int)
        self.run.cleanup_resources()
        self.assertFalse(self.run.work.exists())

    def test_nested_builder_unknown_cleanup_retains_owned_work_until_observed(self) -> None:
        self.run.nested_cleanup_known = False
        with self.assertRaises(GATE.GateError):
            self.run.cleanup_resources()
        self.assertTrue(self.run.work.exists())
        self.run.nested_cleanup_known = True
        self.run.cleanup_resources()
        self.assertFalse(self.run.work.exists())

    def test_capture_redacts_generated_credentials_and_cannot_qualify(self) -> None:
        token = self.run.tokens[0]
        child = self.run.start(
            [sys.executable, "-I", "-c", "print(" + repr(token) + ")"],
            stage="node-server",
            environment=self.run.fixture_environment("node-server"),
        )
        with self.assertRaises(GATE.GateError) as caught:
            self.run.finish(child)
        self.assertEqual(caught.exception.code, "unsafe_capture")
        captured = [p.read_bytes() for p in self.run.retained.rglob("*.bin")]
        self.assertTrue(any(b"[redacted]" in raw for raw in captured))
        self.assertTrue(all(token.encode() not in raw for raw in captured))
        self.assertIsInstance(child.returncode, int)

    def test_reserved_capture_budget_and_nested_children_are_charged_before_spawn(self) -> None:
        self.run.nested_commands = GATE.MAX_CHILDREN
        with self.assertRaises(GATE.GateError):
            self.run.start([sys.executable, "-I", "-c", "pass"], stage="compile")
        self.assertEqual(self.run.commands, 0)
        self.run.nested_commands = 0
        self.run.nested_capture_bytes = GATE.MAX_CAPTURE
        with self.assertRaises(GATE.GateError):
            self.run.start([sys.executable, "-I", "-c", "pass"], stage="compile")
        self.assertEqual(self.run.commands, 0)

    def test_live_child_capture_keeps_reservation_until_actual_group_settlement(self) -> None:
        child = self.run.start(
            [sys.executable, "-I", "-c", "import time;time.sleep(30)"], stage="compile"
        )
        reservation = self.run.reservations[child.pid]
        self.run.capture(child)
        self.assertEqual(self.run.reservations[child.pid], reservation)
        self.assertEqual(self.run.captured, 0)
        child.close()
        self.run.capture(child)
        self.assertNotIn(child.pid, self.run.reservations)
        self.assertTrue(child.group_settled)

    def test_completed_nested_owner_is_rechecked_without_double_deleting_work(self) -> None:
        nested = SimpleNamespace(
            commands=17,
            captured=0,
            reservations={},
            work=self.root / "already-removed-work",
            children=[],
            children_settled=lambda: True,
            cleanup_resources=lambda: self.fail("closed work removed twice"),
        )
        self.run.nested_builder = nested
        self.run.nested_cleanup_known = True
        self.run.cleanup_resources()
        self.assertFalse(self.run.work.exists())
        self.run.nested_builder = None

    def test_source_index_failure_remains_primary_after_cleanup_failure(self) -> None:
        class Capture:
            def __init__(self) -> None:
                self.buffer = io.BytesIO()

        capture = Capture()
        instances: list[object] = []

        def fail_prepare(run: object) -> None:
            instances.append(run)
            raise GATE.GateError("invalid_artifact")

        with (
            patch.object(GATE.packages.shutil, "which", return_value=sys.executable),
            patch.object(GATE.DocumentRun, "prepare", fail_prepare),
            patch.object(
                GATE.DocumentRun,
                "cleanup_resources",
                side_effect=GATE.GateError("cleanup_incomplete"),
            ),
            patch.object(GATE.sys, "stdout", capture),
        ):
            code = GATE.main(
                ["--report", ".local/validation/p3-document/failure.json"], root=self.root
            )
        self.assertEqual(code, 1)
        report = json.loads(capture.buffer.getvalue())
        self.assertEqual(report["code"], "invalid_artifact")
        self.assertIs(report["cleanup_complete"], False)
        for run in instances:
            run.cleanup_resources()


if __name__ == "__main__":
    unittest.main()
