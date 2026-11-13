"""Finite P2 failure diagnostics never reflect bodies, paths, credentials or errors."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "p2_diagnostic_test", ROOT / "local-setup/scripts/p2_communication_diagnostics.py"
)
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def sample():
    return {
        "schemaVersion": 1,
        "stage": "exercise",
        "errorType": "ChannelError",
        "code": "SchemaMismatch",
        "frames": [{"file": "pg_communication_cases.js", "line": 123}],
    }


def encoded(value):
    return json.dumps(value).encode()


class DiagnosticTests(unittest.TestCase):
    def test_only_known_public_source_codes_and_own_frame_are_retained(self):
        item = sample()
        self.assertEqual(GATE.validated_failure(encoded(item), "exercise"), item)
        for changes in [
            {"schemaVersion": True},
            {"stage": "secret_sentinel"},
            {"stage": []},
            {"errorType": []},
            {"errorType": "SecretError"},
            {"code": "secret_sentinel"},
            {"message": "secret_sentinel"},
            {"frames": [{"file": "/private/secret", "line": 123}]},
            {"frames": [{"file": "pg_communication_cases.js", "line": True}]},
        ]:
            with self.subTest(keys=tuple(changes)), self.assertRaises(GATE.native.GateError):
                GATE.validated_failure(encoded({**item, **changes}), "exercise")

    def test_unknown_error_cannot_claim_a_known_code_and_gateway_is_separate(self):
        for kind in ["Error", "AssertionError", "DependencyError"]:
            value = {**sample(), "errorType": kind}
            with self.assertRaises(GATE.native.GateError):
                GATE.validated_failure(encoded(value), "exercise")
            value["code"] = None
            GATE.validated_failure(encoded(value), "exercise")
        value = {**sample(), "errorType": "GatewayError", "code": "invalid_http"}
        GATE.validated_failure(encoded(value), "exercise")
        with self.assertRaises(GATE.native.GateError):
            GATE.validated_failure(encoded({**value, "code": "SchemaMismatch"}), "exercise")

    def test_duplicate_json_deep_values_extra_frames_oversize_and_foreign_mode_fail(self):
        raw = encoded(sample())
        for value in [
            raw[:-1],
            b"\xff",
            b"x" * 2049,
            raw.replace(b'"schemaVersion": 1', b'"schemaVersion": 1,"\\u0073chemaVersion": 1'),
            encoded({**sample(), "frames": [{"file": "pg_communication_cases.js", "line": 1}] * 5}),
        ]:
            with self.assertRaises(GATE.native.GateError):
                GATE.validated_failure(value, "exercise")
        with self.assertRaises(GATE.native.GateError):
            GATE.validated_failure(raw, "foreign")

    def test_private_owned_file_rules_reject_links_modes_and_oversize(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "failure.json"
            path.write_bytes(encoded(sample()))
            path.chmod(0o600)
            self.assertEqual(GATE.private_failure(path, "exercise"), sample())
            alias = path.with_name("link")
            alias.symlink_to(path)
            with self.assertRaises(GATE.native.GateError):
                GATE.private_failure(alias, "exercise")
            alias.unlink()
            alias.hardlink_to(path)
            with self.assertRaises(GATE.native.GateError):
                GATE.private_failure(path, "exercise")
            alias.unlink()
            path.chmod(0o644)
            with self.assertRaises(GATE.native.GateError):
                GATE.private_failure(path, "exercise")
            path.chmod(0o600)
            path.write_bytes(b"x" * 2049)
            with self.assertRaises(GATE.native.GateError):
                GATE.private_failure(path, "exercise")

    def test_safe_retention_records_no_exception_message_or_unsafe_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            work = root / "work"
            artifacts = root / "artifacts"
            work.mkdir(mode=0o700)
            artifacts.mkdir(mode=0o700)
            path = work / "communication-failure-exercise.json"
            path.write_bytes(encoded(sample()))
            path.chmod(0o600)
            GATE.retain_safely(
                work, artifacts, [], RuntimeError("credential_sentinel"), ("credential_sentinel",)
            )
            saved = json.loads((artifacts / path.name).read_text())
            self.assertEqual(saved, sample())
            context = json.loads((artifacts / "fixture-failure-context.json").read_text())
            self.assertEqual(context["primaryType"], "DependencyError")
            self.assertEqual(context["retainedFixtureModes"], ["exercise"])
            self.assertNotIn(
                "credential_sentinel", "".join(p.read_text() for p in artifacts.iterdir())
            )
            self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in artifacts.iterdir()))

    def test_diagnostic_sink_failure_and_invalid_source_never_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            work = root / "work"
            artifacts = root / "artifacts"
            work.mkdir(mode=0o700)
            artifacts.mkdir(mode=0o700)
            path = work / "communication-failure-exercise.json"
            path.write_bytes(encoded({**sample(), "code": "secret_sentinel"}))
            path.chmod(0o600)
            GATE.retain_safely(
                work, artifacts, [], RuntimeError("secret_sentinel"), ("secret_sentinel",)
            )
            self.assertFalse((artifacts / path.name).exists())
            self.assertEqual(
                json.loads((artifacts / "fixture-failure-context.json").read_text())[
                    "diagnosticFilesRejected"
                ],
                1,
            )
            with patch.object(
                GATE.native, "write_json", side_effect=RuntimeError("secret_sentinel")
            ):
                GATE.retain_safely(work, artifacts, [], RuntimeError("primary"), ())
