"""Offline applicability-gate safety checks; no PostgreSQL, provider or source writes."""

import hashlib
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
    "p3_applicability_gate_fixture", ROOT / "local-setup/scripts/p3_applicability_check.py"
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
        "source_authority": "actual_p1_work_v4_existing_delivery_action_and_receiver",
        "applicability_authority": "p3_projection_v3_non_atomic_refresh_and_display_metadata",
        "backup_restore": "validated_versioned_profile_rows_not_pg_dump",
        "provider_calls": False,
    }


def context():
    return {
        "P3_REFRESH_WORK_SCHEMA": "p1_work_applicability_" + "a" * 32,
        "P3_REFRESH_CASE_SCHEMA": "p3_completion_" + "a" * 32,
        "P3_REFRESH_SCHEMA": "p3_projection_" + "a" * 32,
        "P3_REFRESH_DIRECTORY": "/synthetic/private",
        "P3_REFRESH_TOKEN": "A" * 43,
        "P3_REFRESH_BARRIER": "/synthetic/private/before_commit.reached",
    }


def values():
    return {
        "POSTGRES_PORT": "15432",
        "POSTGRES_PASSWORD": "runtime_fixture",
        "POSTGRES_MIGRATION_PASSWORD": "owner_fixture",
        "OPENAI_API_KEY": "PRIVATE_PROVIDER_SENTINEL",
    }


class ApplicabilityGateTests(unittest.TestCase):
    def test_complete_report_and_frozen_inventory_pass(self):
        self.assertEqual(GATE.validated_report(json.dumps(report()).encode()), report())
        self.assertEqual(len(GATE.CASE_NAMES), 18)

    def test_incomplete_unsafe_or_coerced_report_fails(self):
        for key, value in (
            ("schema_version", True),
            ("tests", 0),
            ("tests", True),
            ("passed", 17),
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
            ("applicability_authority", "current_action_permission"),
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
                self.assertEqual("P3_REFRESH_OWNER_PASSWORD" in env, owner)
                self.assertEqual("P3_REFRESH_RUNTIME_PASSWORD" in env, not owner)
                for key in ("OPENAI_API_KEY", "PGSERVICE", "PYTHONPATH", "NODE_OPTIONS"):
                    self.assertNotIn(key, env)
                self.assertFalse(any("PRIVATE_" in value for value in env.values()))

    def test_mixed_missing_unknown_and_empty_child_environment_fails(self):
        good = GATE.child_environment(values(), mode="verify", context=context())
        for key, value in (
            ("P3_REFRESH_OWNER_PASSWORD", "owner"),
            ("NODE_OPTIONS", "injected"),
            ("PGSERVICE", "injected"),
            ("P3_REFRESH_TOKEN", ""),
        ):
            with self.assertRaises(GATE.GateError):
                GATE.validate_child_environment({**good, key: value}, "verify")
        missing = dict(good)
        missing.pop("P3_REFRESH_RUNTIME_PASSWORD")
        with self.assertRaises(GATE.GateError):
            GATE.validate_child_environment(missing, "verify")
        with self.assertRaises(GATE.GateError):
            GATE.child_environment(values(), mode="unknown", context=context())
        with self.assertRaises(GATE.GateError):
            GATE.child_environment(values(), mode="verify", context={})

    def test_report_is_private_exclusive_and_owned(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            target = Path(".local/validation/p3-applicability/result.json")
            GATE.retain_report(root, target, report())
            self.assertEqual(json.loads((root / target).read_text()), report())
            self.assertEqual(stat.S_IMODE((root / target).stat().st_mode), 0o600)
            with self.assertRaises(GATE.GateError):
                GATE.retain_report(root, target, report())
            for bad in (
                Path("outside.json"),
                Path(".local/validation/p3-applicability/../other.json"),
            ):
                with self.assertRaises(GATE.GateError):
                    GATE.report_target(root, bad)

    def test_symlink_report_parent_cannot_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / ".local/validation").mkdir(parents=True)
            actual = root / "actual"
            actual.mkdir()
            (root / ".local/validation/p3-applicability").symlink_to(
                actual, target_is_directory=True
            )
            with self.assertRaises(GATE.GateError):
                GATE.report_target(root, Path(".local/validation/p3-applicability/result.json"))

    def test_capture_budget_is_shared_finite_and_exhaustion_fails(self):
        budget = GATE.core.CaptureBudget()
        for _ in range(20):
            self.assertEqual(budget.reserve(4096), 2048)
        self.assertEqual(budget.available, 131072 - 20 * 4096)
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
            target = Path(".local/validation/p3-applicability/old.json")
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
                "projects/delegation-reliability/tests/pg_applicability_cases.py",
                ".venv/bin/python",
            ):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            setup = SimpleNamespace(load_settings=values, SetupError=ValueError)
            responses = [
                {"status": "passed", "projection_version": 2},
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

    def qualification(self, root, *, stage_changes=None):
        for name in (
            "projects/delegation-reliability/tests/pg_applicability_cases.py",
            ".venv/bin/python",
        ):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        setup = SimpleNamespace(load_settings=values, SetupError=ValueError)
        observations = {
            "install": {"projection_version": 2},
            "seed": {"source_results": 8, "projected_results": 8, "old_ack_count": 1},
            "upgrade": {
                "projection_version": 3,
                "cases": [
                    "projection_v3_nonempty_upgrade_preserves_v2",
                    "upgrade_precommit_kill_repeat",
                ],
            },
            "resume": {"cases": ["refresh_precommit_kill_resume"]},
            "replay": {"cases": ["refresh_postcommit_kill_original_replay"]},
            "race-a": {"revision": 3},
            "race-b": {"cases": ["concurrent_local_cas_no_regression"]},
            "locks": {"blocked": True, "blocking_graphs": 1},
            "classify": {
                "cases": [
                    "late_a_outdated_valid_b_guarded_effect",
                    "work_cancel_invalidates_preserves_receipt",
                    "case_cancel_monotonic_invalidation",
                    "local_deadline_asof_latch",
                    "historical_lease_expiry_not_postcommit_invalidation",
                    "historical_attempt_exact_identity",
                    "case_unavailable_then_recovery",
                ]
            },
            "hide-resume": {"cases": ["hidden_display_preserves_replay_truth"]},
            "progress": {"cases": ["hidden_unknown_later_result_progress"]},
            "restore": {
                "cases": ["populated_refresh_tombstone_backup_restore"],
                "populated_tables": 8,
                "profile_rows_restored": True,
            },
            "verify": {
                "cases": ["scope_source_binding_zero_refresh", "retained_capacity_original_replay"],
                "source_results": 9,
                "projected_results": 9,
            },
            "owner-check": {
                "cases": ["independent_identity_reconciliation_cleanup"],
                "exact_reconciliation": True,
            },
            "cleanup": {"cleanup_complete": True},
        }

        observations.update(stage_changes or {})

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
                return b'{"status":"passed","revision":3}', b""
            if output.name == "race-b":
                return json.dumps(
                    {"status": "passed", "cases": [GATE.CASE_NAMES[10]]}
                ).encode(), b""
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
            self.assertEqual(len(record["case_results"]), 18)

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
            ({"cleanup_complete": 1}, {"cleanup_complete": True}),
            ({"profile_rows_restored": 1}, {"profile_rows_restored": True}),
            ({"populated_tables": 8.0}, {"populated_tables": 8}),
            ({"backup_restore": 1}, {"backup_restore": True}),
            ({"source_results": 7.0}, {"source_results": 7}),
        ):
            self.assertFalse(GATE.exact_child(value, expected))
        self.assertTrue(
            GATE.exact_child({"schema_version": 1, "cases": []}, {"cases": [], "schema_version": 1})
        )

    def test_frozen_twenty_modes_keep_barrier_and_token_roles_exact(self):
        self.assertEqual(len(GATE.MODE_KEYS), 20)
        self.assertEqual(
            GATE.OWNER_MODES,
            {"install", "upgrade-crash", "upgrade", "locks", "restore", "owner-check", "cleanup"},
        )
        self.assertEqual(
            {mode for mode, keys in GATE.MODE_KEYS.items() if "P3_REFRESH_BARRIER" in keys},
            {
                "upgrade-crash",
                "refresh-before",
                "refresh-after",
                "hide-before",
                "hide-after",
                "race-a",
            },
        )
        for mode in GATE.MODE_KEYS:
            selected = GATE.child_environment(values(), mode=mode, context=context())
            self.assertEqual("P3_REFRESH_TOKEN" in selected, mode not in GATE.OWNER_MODES)

    def test_nonempty_restore_protocol_cannot_substitute_empty_or_coerced_evidence(self):
        for changed in (
            {"populated_tables": 0},
            {"populated_tables": 8.0},
            {"profile_rows_restored": 1},
            {"profile_rows_restored": False},
        ):
            with (
                self.subTest(changed=changed),
                tempfile.TemporaryDirectory() as temp,
                redirect_stdout(io.StringIO()) as output,
            ):
                root = Path(temp).resolve()
                reply = {
                    "cases": [GATE.CASE_NAMES[2]],
                    "populated_tables": 8,
                    "profile_rows_restored": True,
                    **changed,
                }
                setup, child, process, capture = self.qualification(
                    root, stage_changes={"restore": reply}
                )
                with setup, child, process, capture:
                    result = GATE.main([], root=root)
                observed = json.loads(output.getvalue())
                self.assertEqual(result, 1)
                self.assertEqual(observed["code"], "invalid_report")
                self.assertIs(observed["cleanup_complete"], True)

    def test_cleanup_protocol_coercion_after_all_cases_never_passes(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()) as output:
            root = Path(temp).resolve()
            setup, child, process, capture = self.qualification(
                root, stage_changes={"cleanup": {"cleanup_complete": 1}}
            )
            with setup, child, process, capture:
                result = GATE.main([], root=root)
            observed = json.loads(output.getvalue())
            self.assertEqual(result, 1)
            self.assertEqual(observed["code"], "cleanup_incomplete")
            self.assertIs(observed["cleanup_complete"], False)

    def test_real_pid_marker_ownership_and_sigkill_are_observed(self):
        script = "import os,pathlib,sys,time; p=pathlib.Path(sys.argv[1]); q=p.with_suffix('.pending'); fd=os.open(q,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600); os.write(fd,(str(os.getpid()+int(sys.argv[2]))+'\\n').encode()); os.fsync(fd); os.close(fd); os.link(q,p); q.unlink(); time.sleep(10)"
        for delta in (0, 1):
            with self.subTest(delta=delta), tempfile.TemporaryDirectory() as temp:
                folder = Path(temp).resolve()
                barrier = GATE.FileBarrier(folder, "owned_commit")
                marker = folder / "owned_commit.reached"
                with GATE.OwnedProcess(
                    [sys.executable, "-I", "-c", script, str(marker), str(delta)],
                    cwd=folder,
                    env=GATE.core.base_environment(),
                    output_directory=folder / "child",
                    max_output_bytes=2048,
                ) as child:
                    if delta:
                        with self.assertRaises(GATE.ProcessControlError):
                            child.wait_for_barrier(barrier, timeout=2)
                    else:
                        child.wait_for_barrier(barrier, timeout=2)
                        self.assertEqual(marker.read_bytes(), (str(child.pid) + "\n").encode())
                        self.assertEqual(stat.S_IMODE(marker.stat().st_mode), 0o600)
                        killed = child.kill(timeout=2)
                        self.assertTrue(killed.killed)
                        self.assertEqual(killed.returncode, -9)
                self.assertFalse(child.cleanup_failed)
                self.assertIsNotNone(child.returncode)

    def test_diagnostics_retain_only_private_redacted_allowlisted_streams(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            work = root / "work"
            (work / "seed").mkdir(parents=True)
            ordinary = "ordinary_pg_role_secret_abcdefghijklmnopqrstuvwxyz"
            escaped = 'quote"slash\\line\nprivate_setting_abcdefghijk'
            raw = (
                "seed_substage: original_work_accept\n"
                + ordinary
                + " "
                + json.dumps(escaped)[1:-1]
                + " sk-proj-"
                + "z" * 40
                + " AKIA"
                + "A" * 16
                + " Bearer synthetic_auth_value_abcdefghijk"
            ).encode()
            (work / "seed/stdout.bin").write_bytes(raw)
            (work / "seed/stderr.bin").write_bytes(b"fixed_stage_failed")
            (work / "fixture.sqlite3").write_bytes(b"DO_NOT_COPY_FIXTURE_BODY")
            (work / "unknown").mkdir()
            (work / "unknown/stdout.bin").write_bytes(b"DO_NOT_COPY_UNKNOWN_MODE")
            target = Path(".local/validation/p3-applicability/diagnostic.json")
            relative = GATE.retain_diagnostics(root, target, work, (ordinary, escaped))
            destination = root / relative
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o700)
            self.assertEqual(
                {str(x.relative_to(destination)) for x in destination.rglob("*") if x.is_file()},
                {"seed/stdout.txt", "seed/stderr.txt", "manifest.json"},
            )
            retained = (destination / "seed/stdout.txt").read_bytes()
            for private in (
                ordinary.encode(),
                json.dumps(escaped)[1:-1].encode(),
                b"sk-proj-",
                b"AKIA",
                b"synthetic_auth_value_",
            ):
                self.assertNotIn(private, retained)
            self.assertIn(b"seed_substage: original_work_accept", retained)
            manifest = json.loads((destination / "manifest.json").read_text())
            self.assertFalse(manifest["raw_originals_retained"])
            self.assertFalse(manifest["provider_files_or_values_read"])
            for entry in manifest["streams"]:
                path = destination / entry["path"]
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertLessEqual(path.stat().st_size, 2048)
                self.assertEqual(entry["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            with self.assertRaises(GATE.GateError):
                GATE.retain_diagnostics(root, target, work, (ordinary,))

    def test_diagnostics_reject_symlink_or_oversized_streams(self):
        for kind in ("symlink", "oversized"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                work = root / "work"
                (work / "seed").mkdir(parents=True)
                if kind == "symlink":
                    outside = root / "private-file"
                    outside.write_bytes(b"PRIVATE_UNRELATED")
                    (work / "seed/stdout.bin").symlink_to(outside)
                else:
                    (work / "seed/stdout.bin").write_bytes(b"x" * 2049)
                with self.assertRaises(GATE.GateError):
                    GATE.retain_diagnostics(
                        root,
                        Path(".local/validation/p3-applicability/diagnostic.json"),
                        work,
                        ("fixture_secret",),
                    )

    def test_redaction_remains_bounded_when_replacement_expands(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            work = root / "work"
            (work / "seed").mkdir(parents=True)
            (work / "seed/stdout.bin").write_bytes(b"xy" * 1024)
            relative = GATE.retain_diagnostics(
                root, Path(".local/validation/p3-applicability/expanded.json"), work, ("xy",)
            )
            retained = (root / relative / "seed/stdout.txt").read_bytes()
            self.assertLessEqual(len(retained), 2048)
            self.assertNotIn(b"xy", retained)

    def test_diagnostic_retention_failure_preserves_primary_error(self):
        state = {}
        with (
            patch.object(GATE, "retain_diagnostics", side_effect=OSError("PRIVATE_SENTINEL")),
            self.assertRaises(GATE.GateError) as caught,
            GATE.diagnostic_failure(
                Path("/synthetic"),
                Path("result.json"),
                Path("work"),
                ("private_setting",),
                state,
                enabled=True,
            ),
        ):
            raise GATE.GateError("seed_failed")
        self.assertEqual(caught.exception.code, "seed_failed")
        self.assertIs(state["diagnostics_retained"], False)
        self.assertEqual(state["diagnostics_code"], "retention_failed")
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(state))

    def test_diagnostic_mode_never_qualifies_even_if_all_cases_pass(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()) as output:
            root = Path(temp).resolve()
            setup, child, process, capture = self.qualification(root)
            with setup, child, process, capture:
                status = GATE.main(["--diagnostic"], root=root)
            observed = json.loads(output.getvalue())
            self.assertEqual(status, 1)
            self.assertEqual(observed["status"], "failed")
            self.assertEqual(observed["code"], "diagnostic_not_qualification")
            self.assertIs(observed["diagnostic"], True)
            self.assertIs(observed["cleanup_complete"], True)

    def test_existing_diagnostic_evidence_stops_before_setup(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()) as output:
            root = Path(temp).resolve()
            target = Path(".local/validation/p3-applicability/held.json")
            folder = root / target.parent / "held-captures"
            GATE.core.private_directory(folder.parent)
            folder.mkdir(mode=0o700)
            original = folder / "original.txt"
            original.write_bytes(b"original_evidence")
            with patch.object(GATE.core, "load_setup") as setup:
                status = GATE.main(["--diagnostic", "--report", str(target)], root=root)
            self.assertEqual(status, 1)
            setup.assert_not_called()
            self.assertEqual(json.loads(output.getvalue())["code"], "existing_diagnostics")
            self.assertEqual(original.read_bytes(), b"original_evidence")
