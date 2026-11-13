"""Offline validator/setup negatives only; no database, provider or Node launch."""

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "p3_gate_fixture", ROOT / "local-setup/scripts/p3_coordinator_check.py"
)
assert SPEC is not None and SPEC.loader is not None
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def context():
    return {
        "P3_CHECK_SCHEMA": "p1_work_p3_" + "a" * 32,
        "P3_CHECK_TOKEN": "A" * 43,
        "P3_CHECK_SPECIALIST_PORT": "12345",
        "P3_CHECK_RELEASE": "/synthetic/release",
        "P3_CHECK_PRIMARY_SHA256": "a" * 64,
        "P3_CHECK_CRASH_DEADLINE": "1800000000000",
        "P3_CHECK_COMMIT_MARKER": "/synthetic/committed.reached",
        "P3_CHECK_PROFILE_INSTALLED": "1",
    }


def selected_settings():
    return {
        "POSTGRES_PORT": "15432",
        "POSTGRES_PASSWORD": "runtime_fixture",
        "POSTGRES_MIGRATION_PASSWORD": "owner_fixture",
        "UNUSED_SECRET": "PRIVATE_SENTINEL",
    }


def report():
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
        "child_terminations": 1,
        "case_results": [
            {"name": name, "status": "passed", "code": "ok"} for name in GATE.CASE_NAMES
        ],
        "node_version": "24.22.2",
        "case_authority": "synthetic_typed_read_preflight",
        "invocation_authority": "independent_transport_probe_no_issued_attempt",
    }


class P3GateReportTests(unittest.TestCase):
    def test_complete_exact_nonzero_report_accepted(self):
        self.assertEqual(GATE.validated_report(json.dumps(report()).encode()), report())
        for version in ("24.22.2", "24.23.0", "26.13.0", "26.14.1"):
            self.assertTrue(GATE.supported_node(version))
        for version in (True, None, "24.22.1", "26.12.9", "27.0.0", "26.013.0"):
            self.assertFalse(GATE.supported_node(version))

    def test_missing_duplicate_unknown_failed_or_out_of_order_cases_fail_closed(self):
        for mutation in ("missing", "duplicate", "unknown", "failed", "order"):
            value = report()
            if mutation == "missing":
                value["case_results"].pop()
            elif mutation == "duplicate":
                value["case_results"][1] = value["case_results"][0]
            elif mutation == "unknown":
                value["case_results"][0]["name"] = "unregistered"
            elif mutation == "failed":
                value["case_results"][0].update(status="failed", code="assertion_failed")
            else:
                value["case_results"].reverse()
            with self.assertRaises(GATE.GateError):
                GATE.validated_report(json.dumps(value).encode())

    def test_boolean_zero_skip_cleanup_and_deadline_contradictions_cannot_pass(self):
        for key, bad in (
            ("tests", 0),
            ("tests", True),
            ("passed", 0),
            ("skipped", 1),
            ("cleanup_complete", False),
            ("cleanup_complete", 1),
            ("child_terminations", 0),
            ("child_terminations", True),
            ("duration_seconds", True),
            ("duration_seconds", 181),
            ("duration_seconds", float("nan")),
            ("schema_version", True),
            ("case_authority", "managed_case_qualified"),
            ("invocation_authority", "p1_issued_execution"),
        ):
            value = report()
            value[key] = bad
            with self.assertRaises(GATE.GateError):
                GATE.validated_report(json.dumps(value).encode())

    def test_duplicate_json_truncated_and_oversized_reports_fail_closed(self):
        raw = json.dumps(report()).encode()
        for bad in (
            b"",
            raw[:-1],
            b'{"status":"passed","status":"passed"}',
            b" " * (GATE.MAX_REPORT_BYTES + 1),
            b"[]",
        ):
            with self.assertRaises(GATE.GateError):
                GATE.validated_report(bad)

    def test_actual_server_cleanup_counts_are_strict_not_boolean_coercions(self):
        value = {
            "status": "passed",
            "cleanup_complete": True,
            "active": 0,
            "requests": 0,
            "sockets": 0,
            "node_version": "24.22.2",
        }
        self.assertTrue(GATE.validated_server(json.dumps(value).encode(), "24.22.2"))
        for key, bad in (
            ("active", False),
            ("sockets", 1),
            ("cleanup_complete", 1),
            ("node_version", "26.13.0"),
        ):
            changed = {**value, key: bad}
            self.assertFalse(GATE.validated_server(json.dumps(changed).encode(), "24.22.2"))

    def test_capture_reservations_cannot_exceed_whole_gate_limit(self):
        budget = GATE.CaptureBudget()
        reserved = [budget.reserve() * 2 for _ in range(9)]
        self.assertLessEqual(sum(reserved), GATE.MAX_CAPTURE_BYTES)
        while budget.available:
            reserved.append(budget.reserve() * 2)
        self.assertEqual(sum(reserved), GATE.MAX_CAPTURE_BYTES)
        with self.assertRaises(GATE.GateError):
            budget.reserve()


class P3GateSetupTests(unittest.TestCase):
    def test_no_ambient_provider_postgres_or_node_options_reach_children(self):
        hostile = {
            "PATH": "/synthetic/path",
            "HOME": "/synthetic/home",
            "__CF_USER_TEXT_ENCODING": "synthetic_encoding",
            "PGHOSTADDR": "external.invalid",
            "PGPASSWORD": "PRIVATE_SENTINEL",
            "NODE_OPTIONS": "--import=external.invalid",
            "P3_CHECK_TOKEN": "PRIVATE_SENTINEL",
            "P3_POSTGRES_PORT": "1",
            "OPENAI_API_KEY": "PRIVATE_SENTINEL",
            "DEEPGRAM_API_KEY": "PRIVATE_SENTINEL",
            "ELEVEN_API_KEY": "PRIVATE_SENTINEL",
            "OTEL_EXPORTER_OTLP_HEADERS": "PRIVATE_SENTINEL",
        }
        with patch.dict(os.environ, hostile, clear=True):
            for mode in GATE.MODE_CONTEXT_KEYS:
                environment = GATE.child_environment(
                    selected_settings(), mode=mode, context=context()
                )
                owner = mode in GATE.OWNER_MODES
                password = "P3_MIGRATION_PASSWORD" if owner else "P3_RUNTIME_PASSWORD"
                self.assertEqual(
                    set(environment),
                    {
                        "PATH",
                        "HOME",
                        "__CF_USER_TEXT_ENCODING",
                        "CI",
                        "NO_COLOR",
                        "P3_POSTGRES_PORT",
                        password,
                        *GATE.MODE_CONTEXT_KEYS[mode],
                    },
                )
                self.assertNotIn("PRIVATE_SENTINEL", json.dumps(environment))
                self.assertEqual(environment["P3_POSTGRES_PORT"], "15432")
                self.assertNotIn(
                    "P3_RUNTIME_PASSWORD" if owner else "P3_MIGRATION_PASSWORD", environment
                )
                if owner:
                    self.assertNotIn("P3_CHECK_TOKEN", environment)
                for forbidden in (
                    "P3_RUNTIME_PASSWORD" if owner else "P3_MIGRATION_PASSWORD",
                    "NODE_OPTIONS",
                    "OPENAI_API_KEY",
                    "PGHOSTADDR",
                ):
                    with self.assertRaises(GATE.GateError):
                        GATE.validate_child_environment(
                            {**environment, forbidden: "PRIVATE_SENTINEL"}, mode
                        )

    def test_fixture_runtime_modes_cannot_construct_owner_settings_or_accept_owner_environment(
        self,
    ):
        spec = importlib.util.spec_from_file_location(
            "p3_case_role_fixture",
            ROOT / "projects/delegation-reliability/tests/pg_coordinator_cases.py",
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        for mode in GATE.MODE_CONTEXT_KEYS:
            fixture._ACTIVE_MODE = mode
            owner = mode in GATE.OWNER_MODES
            environment = GATE.child_environment(selected_settings(), mode=mode, context=context())
            with patch.dict(os.environ, environment, clear=True):
                fixture.validate_environment(mode)
                with patch.object(fixture, "PostgresSettings") as settings:
                    with self.assertRaisesRegex(
                        AssertionError, "^credential_role_not_allowed_for_mode$"
                    ):
                        fixture.settings(owner=not owner)
                    settings.assert_not_called()
                wrong = "P3_RUNTIME_PASSWORD" if owner else "P3_MIGRATION_PASSWORD"
                with (
                    patch.dict(os.environ, {wrong: "PRIVATE_SENTINEL"}),
                    self.assertRaisesRegex(AssertionError, "^unsafe_child_environment$"),
                ):
                    fixture.validate_environment(mode)

    def test_setup_import_does_not_read_or_create_private_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "local-setup").mkdir()
            (root / "local-setup/stack.py").write_text(
                "def load_settings():\n    return {'synthetic': True}\n"
            )
            before = set(sys.modules)
            module = GATE.load_setup(root)
            self.assertEqual(module.load_settings(), {"synthetic": True})
            self.assertFalse(
                any(name.startswith("p3_coordinator_setup_") for name in set(sys.modules) - before)
            )
            self.assertFalse((root / "local-setup/.secrets.env").exists())

    def test_missing_setup_is_safe_and_launches_no_child(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(GATE, "OwnedProcess") as child,
        ):
            root = Path(temporary).resolve()
            (root / "local-setup").mkdir()
            (root / "local-setup/stack.py").write_text(
                "class SetupError(Exception): pass\ndef load_settings():\n    raise SetupError('PRIVATE_SENTINEL')\n"
            )
            output = io.StringIO()
            with patch("sys.stdout", output):
                self.assertEqual(GATE.main([], root=root), 1)
            self.assertEqual(json.loads(output.getvalue())["code"], "missing_setup")
            self.assertNotIn("PRIVATE_SENTINEL", output.getvalue())
            child.assert_not_called()

    def test_child_failure_stderr_truncation_timeout_and_cleanup_never_pass(self):
        variants = (
            (1, b'{"status":"passed"}', b"", False, None),
            (0, b'{"status":"passed"}', b"PRIVATE_SENTINEL", False, None),
            (0, b'{"status":"pass', b"", False, None),
            (0, b'{"status":"passed"}', b"", True, None),
            (0, b'{"status":"passed"}', b"", False, GATE.ProcessControlError("PRIVATE_SENTINEL")),
        )
        for code, raw, stderr, cleanup_failed, failure in variants:
            with tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary).resolve() / "capture"
                output.mkdir()
                (output / "stdout.bin").write_bytes(raw)
                (output / "stderr.bin").write_bytes(stderr)
                owned = SimpleNamespace(
                    cleanup_failed=cleanup_failed,
                    returncode=code,
                    wait=lambda code=code, **_kwargs: SimpleNamespace(returncode=code),
                )
                if failure is not None:

                    def fail(failure=failure, **_kwargs):
                        raise failure

                    owned.wait = fail
                with patch.object(GATE, "OwnedProcess") as constructor:
                    constructor.return_value.__enter__.return_value = owned
                    with self.assertRaises((GATE.GateError, GATE.ProcessControlError)) as caught:
                        GATE.run_child(
                            ["synthetic", "verify"],
                            cwd=output,
                            environment=GATE.child_environment(
                                selected_settings(), mode="verify", context=context()
                            ),
                            output=output,
                            deadline=GATE.time.monotonic() + 1,
                            budget=GATE.CaptureBudget(),
                        )
                # Public gate errors are fixed; raw process errors are contained by main.
                if isinstance(caught.exception, GATE.GateError):
                    self.assertNotIn("PRIVATE_SENTINEL", str(caught.exception))

    def test_missing_ready_barrier_cannot_produce_passing_gate_or_skip_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            for relative in (
                "projects/delegation-reliability/specialist-ts/tests/fixtures/python-client-server.mjs",
                "projects/delegation-reliability/specialist-ts/node_modules/typescript/bin/tsc",
                "projects/delegation-reliability/tests/pg_coordinator_cases.py",
                ".venv/bin/python",
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()

            barriers = []

            class Process:
                cleanup_failed = False
                returncode = 0

                def __init__(self, _command, **kwargs):
                    folder = kwargs["output_directory"]
                    folder.mkdir()
                    payload = (
                        b""
                        if folder.name == "compile"
                        else json.dumps(
                            {
                                "status": "passed",
                                "cleanup_complete": True,
                                "active": 0,
                                "requests": 0,
                                "sockets": 0,
                                "node_version": "24.22.2",
                            }
                        ).encode()
                    )
                    (folder / "stdout.bin").write_bytes(payload)
                    (folder / "stderr.bin").write_bytes(b"")

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    pass

                def wait(self, **_kwargs):
                    return SimpleNamespace(returncode=0)

                def wait_for_barrier(self, *_args, **_kwargs):
                    barriers.append(True)
                    raise GATE.ProcessControlError("PRIVATE_BARRIER_SENTINEL")

            setup = SimpleNamespace(
                load_settings=lambda: {
                    "POSTGRES_PORT": "15432",
                    "POSTGRES_PASSWORD": "runtime",
                    "POSTGRES_MIGRATION_PASSWORD": "owner",
                }
            )
            output = io.StringIO()
            with (
                patch.object(GATE, "load_setup", return_value=setup),
                patch.object(GATE, "OwnedProcess", Process),
                patch.object(GATE.shutil, "which", return_value="/synthetic/node"),
                patch.object(
                    GATE,
                    "run_child",
                    side_effect=[
                        {"status": "passed", "foreign_records": 0, "total_records": 0},
                        {"status": "passed", "schema_removed": True},
                    ],
                ) as child,
                patch("sys.stdout", output),
            ):
                self.assertEqual(GATE.main([], root=root), 1)
            value = json.loads(output.getvalue())
            self.assertEqual(value["status"], "failed")
            self.assertFalse(value["cleanup_complete"])
            self.assertNotIn("PRIVATE_BARRIER_SENTINEL", output.getvalue())
            self.assertEqual(barriers, [True])
            self.assertEqual(child.call_count, 2)
            self.assertEqual(child.call_args_list[-1].args[0][-1], "cleanup")

    def test_report_is_private_exclusive_scoped_and_refused_before_work(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            relative = Path(".local/validation/p3-coordinator/report.json")
            GATE.retain_report(root, relative, report())
            self.assertEqual((root / relative).stat().st_mode & 0o777, 0o600)
            with self.assertRaises(GATE.GateError):
                GATE.retain_report(root, relative, report())
            with self.assertRaises(GATE.GateError):
                GATE.retain_report(root, Path("outside.json"), report())
            with patch.object(GATE, "load_setup") as load, patch("sys.stdout", io.StringIO()):
                self.assertEqual(GATE.main(["--report", str(relative)], root=root), 1)
                load.assert_not_called()
