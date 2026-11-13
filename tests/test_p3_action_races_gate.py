"""Offline protected-action race-gate safety checks; no PostgreSQL, provider or source writes."""

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
    "p3_action_race_gate_fixture", ROOT / "local-setup/scripts/p3_action_races_check.py"
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
        "child_terminations": 3,
        "blocking_graphs_observed": 2,
        "case_results": [
            {"name": name, "status": "passed", "code": "ok"} for name in GATE.CASE_NAMES
        ],
        "source_authority": "actual_public_p1_work_case_action_and_leased_effects",
        "supplier_authority": "independent_cooperating_sqlite_per_schedule",
        "runtime_change": "validation_only_existing_p3_p1_guards",
        "provider_calls": False,
    }


def context():
    return {
        "P3_RACE_WORK_SCHEMA": "p1_work_actionrace_" + "a" * 32,
        "P3_RACE_CASE_SCHEMA": "p3_completion_" + "a" * 32,
        "P3_RACE_DIRECTORY": "/synthetic/private",
        "P3_RACE_TOKEN": "A" * 43,
        "P3_RACE_BARRIER": "/synthetic/private/before_commit.reached",
    }


def values():
    return {
        "POSTGRES_PORT": "15432",
        "POSTGRES_PASSWORD": "runtime_fixture",
        "POSTGRES_MIGRATION_PASSWORD": "owner_fixture",
        "OPENAI_API_KEY": "PRIVATE_PROVIDER_SENTINEL",
    }


def proof_examples():
    graph = [{"pid": 10, "blockers": [30]}, {"pid": 20, "blockers": [10, 30]}]
    return {
        "graph_b_first.json": graph,
        "graph_a_first.json": graph,
        "owner_proof.json": {
            "status": "passed",
            "exact_reconciliation": True,
            "actions": 10,
            "applied": 6,
            "receipts": 2,
            "results": 12,
            "reconciliation_sha256": "a" * 64,
        },
    }


class ActionRaceGateTests(unittest.TestCase):
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
                self.assertEqual("P3_RACE_OWNER_PASSWORD" in env, owner)
                self.assertEqual("P3_RACE_RUNTIME_PASSWORD" in env, not owner)
                for key in ("OPENAI_API_KEY", "PGSERVICE", "PYTHONPATH", "NODE_OPTIONS"):
                    self.assertNotIn(key, env)
                self.assertFalse(any("PRIVATE_" in value for value in env.values()))

    def test_mixed_missing_unknown_and_empty_child_environment_fails(self):
        good = GATE.child_environment(values(), mode="owned-lifetime", context=context())
        for key, value in (
            ("P3_RACE_OWNER_PASSWORD", "owner"),
            ("NODE_OPTIONS", "injected"),
            ("PGSERVICE", "injected"),
            ("P3_RACE_TOKEN", ""),
        ):
            with self.assertRaises(GATE.GateError):
                GATE.validate_child_environment({**good, key: value}, "owned-lifetime")
        missing = dict(good)
        missing.pop("P3_RACE_RUNTIME_PASSWORD")
        with self.assertRaises(GATE.GateError):
            GATE.validate_child_environment(missing, "owned-lifetime")
        with self.assertRaises(GATE.GateError):
            GATE.child_environment(values(), mode="unknown", context=context())
        with self.assertRaises(GATE.GateError):
            GATE.child_environment(values(), mode="owned-lifetime", context={})

    def test_report_is_private_exclusive_and_owned(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            target = Path(".local/validation/p3-action-races/result.json")
            GATE.retain_report(root, target, report())
            self.assertEqual(json.loads((root / target).read_text()), report())
            self.assertEqual(stat.S_IMODE((root / target).stat().st_mode), 0o600)
            with self.assertRaises(GATE.GateError):
                GATE.retain_report(root, target, report())
            for bad in (
                Path("outside.json"),
                Path(".local/validation/p3-action-races/../other.json"),
            ):
                with self.assertRaises(GATE.GateError):
                    GATE.report_target(root, bad)

    def test_symlink_report_parent_cannot_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / ".local/validation").mkdir(parents=True)
            actual = root / "actual"
            actual.mkdir()
            (root / ".local/validation/p3-action-races").symlink_to(
                actual, target_is_directory=True
            )
            with self.assertRaises(GATE.GateError):
                GATE.report_target(root, Path(".local/validation/p3-action-races/result.json"))

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
            target = Path(".local/validation/p3-action-races/old.json")
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

    def test_actual_offline_child_validates_framing_and_is_owned(self):
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp).resolve()
            environment = GATE.child_environment(values(), mode="owned-lifetime", context=context())
            result = GATE.run_child(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    'print(\'{"status":"passed","cases":[]}\')',
                    "owned-lifetime",
                ],
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
                        [sys.executable, "-I", "-c", script, "owned-lifetime"],
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
                    mode="owned-lifetime",
                )

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
            (work / "prepare-b-first").mkdir(parents=True)
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
            (work / "prepare-b-first/stdout.bin").write_bytes(raw)
            (work / "prepare-b-first/stderr.bin").write_bytes(b"fixed_stage_failed")
            (work / "fixture.sqlite3").write_bytes(b"DO_NOT_COPY_FIXTURE_BODY")
            (work / "unknown").mkdir()
            (work / "unknown/stdout.bin").write_bytes(b"DO_NOT_COPY_UNKNOWN_MODE")
            target = Path(".local/validation/p3-action-races/diagnostic.json")
            relative = GATE.retain_diagnostics(root, target, work, (ordinary, escaped))
            destination = root / relative
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o700)
            self.assertEqual(
                {str(x.relative_to(destination)) for x in destination.rglob("*") if x.is_file()},
                {"prepare-b-first/stdout.txt", "prepare-b-first/stderr.txt", "manifest.json"},
            )
            retained = (destination / "prepare-b-first/stdout.txt").read_bytes()
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
                (work / "prepare-b-first").mkdir(parents=True)
                if kind == "symlink":
                    outside = root / "private-file"
                    outside.write_bytes(b"PRIVATE_UNRELATED")
                    (work / "prepare-b-first/stdout.bin").symlink_to(outside)
                else:
                    (work / "prepare-b-first/stdout.bin").write_bytes(b"x" * 2049)
                with self.assertRaises(GATE.GateError):
                    GATE.retain_diagnostics(
                        root,
                        Path(".local/validation/p3-action-races/diagnostic.json"),
                        work,
                        ("fixture_secret",),
                    )

    def test_redaction_remains_bounded_when_replacement_expands(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            work = root / "work"
            (work / "prepare-b-first").mkdir(parents=True)
            (work / "prepare-b-first/stdout.bin").write_bytes(b"xy" * 1024)
            relative = GATE.retain_diagnostics(
                root, Path(".local/validation/p3-action-races/expanded.json"), work, ("xy",)
            )
            retained = (root / relative / "prepare-b-first/stdout.txt").read_bytes()
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
            raise GATE.GateError("fixture_failed")
        self.assertEqual(caught.exception.code, "fixture_failed")
        self.assertIs(state["diagnostics_retained"], False)
        self.assertEqual(state["diagnostics_code"], "retention_failed")
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(state))

    def test_existing_diagnostic_evidence_stops_before_setup(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()) as output:
            root = Path(temp).resolve()
            target = Path(".local/validation/p3-action-races/held.json")
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

    def test_complete_report_and_exact_closed_inventory(self):
        self.assertEqual(GATE.validated_report(json.dumps(report()).encode()), report())
        self.assertEqual(len(GATE.CASE_NAMES), 16)
        self.assertEqual(len(GATE.MODE_KEYS), 31)
        self.assertEqual(
            GATE.OWNER_MODES, {"install", "lock-b-first", "lock-a-first", "owner-check", "cleanup"}
        )
        self.assertEqual(set(GATE.MODE_KEYS), set(GATE.RESPONSES))
        self.assertEqual(
            {mode for mode, keys in GATE.MODE_KEYS.items() if "P3_RACE_BARRIER" in keys},
            set(GATE.BARRIERS),
        )
        for mode in GATE.MODE_KEYS:
            env = GATE.child_environment(values(), mode=mode, context=context())
            self.assertEqual("P3_RACE_TOKEN" in env, mode not in GATE.OWNER_MODES)

    def test_incomplete_unsafe_or_coerced_report_fails(self):
        for key, value in (
            ("schema_version", True),
            ("tests", 0),
            ("tests", True),
            ("passed", 15),
            ("errors", 1),
            ("failures", 1),
            ("skipped", 1),
            ("child_terminations", 2),
            ("child_terminations", True),
            ("blocking_graphs_observed", 1),
            ("blocking_graphs_observed", True),
            ("cleanup_complete", 1),
            ("cleanup_complete", False),
            ("duration_seconds", True),
            ("duration_seconds", 0),
            ("duration_seconds", 181),
            ("duration_seconds", float("nan")),
            ("duration_seconds", float("inf")),
            ("provider_calls", 0),
            ("provider_calls", True),
            ("source_authority", "mock"),
            ("supplier_authority", "local_intent"),
            ("runtime_change", "new_guard"),
        ):
            changed = report()
            changed[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(GATE.GateError):
                GATE.validated_report(json.dumps(changed).encode())

    def qualification(self, root, *, changes=None, killed=True):
        for name in (
            "projects/delegation-reliability/tests/pg_action_race_cases.py",
            "local-setup/scripts/p3_action_case_fixture.py",
            ".venv/bin/python",
        ):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        setup = SimpleNamespace(load_settings=values, SetupError=ValueError)
        replies = json.loads(json.dumps(GATE.RESPONSES))
        replies.update(changes or {})
        events = []

        class Child:
            def __init__(self, command, **kwargs):
                self.mode = command[-1]
                self.cleanup_failed = False
                self.returncode = 0
                events.append(("spawn", self.mode))

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def wait_for_barrier(self, barrier, **kwargs):
                events.append(("wait", self.mode, barrier.name))

            def release_barrier(self, barrier, **kwargs):
                events.append(("release", self.mode, barrier.name))

            def kill(self, **kwargs):
                self.returncode = -9 if killed else 0
                return SimpleNamespace(killed=killed, returncode=self.returncode)

            def wait(self, **kwargs):
                return SimpleNamespace(returncode=0)

        def call(command, **kwargs):
            mode = command[-1]
            events.append(("call", mode))
            if mode == "owner-check":
                for name, value in proof_examples().items():
                    (kwargs["cwd"] / name).write_text(json.dumps(value))
            value = replies[mode]
            if isinstance(value, Exception):
                raise value
            return value

        def capture(output, limit):
            value = replies[output.name]
            return (b"" if value is None else json.dumps(value).encode()), b""

        return (
            patch.object(GATE.core, "load_setup", return_value=setup),
            patch.object(GATE, "run_child", side_effect=call),
            patch.object(GATE, "OwnedProcess", side_effect=Child),
            patch.object(GATE.core.CaptureBudget, "read", side_effect=capture),
        ), events

    def run_protocol(self, *, changes=None, killed=True, diagnostic=False, evidence_error=False):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()) as output:
            root = Path(temp).resolve()
            patches, events = self.qualification(root, changes=changes, killed=killed)
            with patches[0], patches[1], patches[2], patches[3]:
                if evidence_error:
                    with patch.object(
                        GATE, "retain_report", side_effect=OSError("PRIVATE_SENTINEL")
                    ):
                        code = GATE.main([], root=root)
                else:
                    code = GATE.main(["--diagnostic"] if diagnostic else [], root=root)
            text = output.getvalue()
            self.assertNotIn("PRIVATE_SENTINEL", text)
            return code, json.loads(text), events

    def test_complete_protocol_observes_three_kills_two_graphs_and_all_modes_once(self):
        code, value, events = self.run_protocol()
        self.assertEqual(code, 0)
        self.assertEqual(GATE.validated_report(json.dumps(value).encode()), value)
        invoked = [item[1] for item in events if item[0] in {"call", "spawn"}]
        self.assertEqual(len(invoked), 31)
        self.assertEqual(set(invoked), set(GATE.MODE_ORDER))
        self.assertEqual(invoked[-1], "cleanup")

    def test_both_lock_orders_use_prewarmed_same_owner_observer_and_exact_release_order(self):
        code, _, events = self.run_protocol()
        self.assertEqual(code, 0)
        for suffix, first, second in (
            ("b-first", "revise", "action"),
            ("a-first", "action", "revise"),
        ):
            label = suffix.replace("-", "_")
            owner = "lock-" + suffix
            start = events.index(("spawn", owner))
            end = events.index(("release", owner, "case_admission_" + label))
            critical = events[start + 1 : end + 1]
            self.assertFalse(any(event[0] in {"call", "spawn"} for event in critical))
            releases = [item[1] for item in critical if item[0] == "release"]
            self.assertEqual(releases, [first + "-" + suffix, second + "-" + suffix, owner])
            first_wait = events.index(("wait", owner, "first_wait_" + label))
            graph = events.index(("wait", owner, "order_graph_" + label))
            self.assertLess(first_wait, graph)
            self.assertLess(graph, end)

    def test_strict_child_primitives_authority_codes_and_case_names_cannot_be_substituted(self):
        for mode, changes in (
            ("install", {"work_version": True}),
            ("lock-b-first", {"waiters": True}),
            ("lock-a-first", {"blocking_graphs": 1.0}),
            ("action-a-first", {"action_committed": 1}),
            ("revise-a-first", {"revision_code": "stale_revision"}),
            ("worker-claim", {"worker_code": "ignored"}),
            ("cancel-reserved", {"disposition": "cancelled_before_dispatch"}),
            ("cancel-applied", {"work_expired": 1}),
            ("owner-check", {"exact_reconciliation": 1}),
            ("finish-b-first", {"cases": [0, 1]}),
        ):
            with self.subTest(mode=mode, changes=changes):
                reply = {**GATE.RESPONSES[mode], **changes}
                code, value, _ = self.run_protocol(changes={mode: reply})
                self.assertEqual(code, 1)
                self.assertEqual(value["code"], "invalid_report")
                self.assertIs(value["cleanup_complete"], True)

    def test_primary_failure_survives_cleanup_failure_and_cleanup_still_runs(self):
        code, value, events = self.run_protocol(
            changes={
                "prepare-b-first": GATE.GateError("primary_fixture_failed"),
                "cleanup": GATE.GateError("cleanup_failed"),
            }
        )
        self.assertEqual(code, 1)
        self.assertEqual(value["code"], "primary_fixture_failed")
        self.assertIs(value["cleanup_complete"], False)
        self.assertEqual(events[-1], ("call", "cleanup"))

    def test_coerced_cleanup_after_all_cases_cannot_pass(self):
        code, value, _ = self.run_protocol(
            changes={"cleanup": {"status": "passed", "cleanup_complete": 1}}
        )
        self.assertEqual(code, 1)
        self.assertEqual(value["code"], "cleanup_incomplete")
        self.assertIs(value["cleanup_complete"], False)

    def test_three_claimed_kills_without_verified_sigkill_cannot_pass(self):
        code, value, _ = self.run_protocol(killed=False)
        self.assertEqual(code, 1)
        self.assertEqual(value["code"], "crash_not_observed")
        self.assertIs(value["cleanup_complete"], True)

    def test_final_report_write_failure_cannot_exit_success(self):
        code, value, _ = self.run_protocol(evidence_error=True)
        self.assertEqual(code, 1)
        self.assertEqual(value["status"], "failed")

    def test_diagnostic_mode_never_qualifies_even_if_all_cases_pass(self):
        code, value, _ = self.run_protocol(diagnostic=True)
        self.assertEqual(code, 1)
        self.assertEqual(value["code"], "diagnostic_not_qualification")
        self.assertIs(value["diagnostic"], True)
        self.assertIs(value["cleanup_complete"], True)

    def test_success_proof_retains_only_three_closed_files_with_direct_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            work = root / "work"
            work.mkdir()
            for name, value in proof_examples().items():
                (work / name).write_text(json.dumps(value))
            (work / "original_confirmation.json").write_text("PRIVATE_BODY")
            relative = GATE.retain_proof(
                root, Path(".local/validation/p3-action-races/normal.json"), work
            )
            folder = root / relative
            self.assertEqual(stat.S_IMODE(folder.stat().st_mode), 0o700)
            self.assertEqual(
                {path.name for path in folder.iterdir()}, {*GATE.PROOF_FILES, "manifest.json"}
            )
            manifest = json.loads((folder / "manifest.json").read_text())
            self.assertFalse(manifest["raw_request_confirmation_credentials_retained"])
            for entry in manifest["files"]:
                raw = (folder / entry["path"]).read_bytes()
                self.assertEqual(entry["sha256"], hashlib.sha256(raw).hexdigest())
                self.assertEqual(entry["bytes"], len(raw))
                self.assertEqual(stat.S_IMODE((folder / entry["path"]).stat().st_mode), 0o600)
            with self.assertRaises(GATE.GateError):
                GATE.retain_proof(root, Path(".local/validation/p3-action-races/normal.json"), work)

    def test_proof_graph_requires_true_two_waiter_chain_and_exact_pid_primitives(self):
        for graph in (
            [{"pid": True, "blockers": [30]}, {"pid": 20, "blockers": [10, 30]}],
            [{"pid": 10, "blockers": [30]}, {"pid": 20, "blockers": [30]}],
            [{"pid": 10, "blockers": [30]}, {"pid": 20, "blockers": [40, 50]}],
            [{"pid": 10, "blockers": [30]}, {"pid": 10, "blockers": [10, 30]}],
            [{"pid": 10, "blockers": [30], "body": "PRIVATE"}, {"pid": 20, "blockers": [10, 30]}],
        ):
            with self.subTest(graph=graph), self.assertRaises(GATE.GateError):
                GATE.validate_proof("graph_b_first.json", json.dumps(graph).encode())

    def test_proof_owner_closed_fields_types_digest_and_duplicate_keys(self):
        for key, value in (
            ("exact_reconciliation", 1),
            ("actions", True),
            ("actions", 11),
            ("applied", 0),
            ("results", 33),
            ("reconciliation_sha256", "not_a_digest"),
            ("private_body", "PRIVATE"),
        ):
            changed = {**proof_examples()["owner_proof.json"], key: value}
            with self.subTest(key=key), self.assertRaises(GATE.GateError):
                GATE.validate_proof("owner_proof.json", json.dumps(changed).encode())
        with self.assertRaises(GATE.GateError):
            GATE.validate_proof(
                "graph_a_first.json",
                b'[{"pid":10,"pid":10,"blockers":[30]},{"pid":20,"blockers":[10,30]}]',
            )

    def test_proof_missing_symlink_hardlink_and_oversized_input_cannot_be_copied(self):
        for kind in ("missing", "symlink", "hardlink", "oversized"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                work = root / "work"
                work.mkdir()
                for name, value in proof_examples().items():
                    (work / name).write_text(json.dumps(value))
                selected = work / "graph_b_first.json"
                selected.unlink()
                if kind == "oversized":
                    selected.write_bytes(b"x" * 4097)
                elif kind in {"symlink", "hardlink"}:
                    outside = root / "outside"
                    outside.write_text(json.dumps(proof_examples()["graph_b_first.json"]))
                    if kind == "symlink":
                        selected.symlink_to(outside)
                    else:
                        os.link(outside, selected)
                with self.assertRaises((GATE.GateError, OSError)):
                    GATE.retain_proof(
                        root, Path(".local/validation/p3-action-races/normal.json"), work
                    )
                self.assertFalse(
                    (root / ".local/validation/p3-action-races/normal-artifacts").exists()
                )

    def test_existing_proof_stops_before_settings_and_retains_original(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()) as output:
            root = Path(temp).resolve()
            target = Path(".local/validation/p3-action-races/original.json")
            folder = GATE.proof_target(root, target)
            folder.mkdir(mode=0o700)
            (folder / "original").write_bytes(b"original")
            with patch.object(GATE.core, "load_setup") as setup:
                status = GATE.main(["--report", str(target)], root=root)
            self.assertEqual(status, 1)
            setup.assert_not_called()
            self.assertEqual(json.loads(output.getvalue())["code"], "existing_proof")
            self.assertEqual((folder / "original").read_bytes(), b"original")

    def test_proof_retention_failure_after_all_cases_still_cannot_qualify(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()) as output:
            root = Path(temp).resolve()
            patches, _ = self.qualification(root)
            with (
                patches[0],
                patches[1],
                patches[2],
                patches[3],
                patch.object(GATE, "retain_proof", side_effect=OSError("PRIVATE_SENTINEL")),
            ):
                status = GATE.main([], root=root)
            self.assertEqual(status, 1)
            record = json.loads(output.getvalue())
            self.assertEqual(record["status"], "failed")
            self.assertIs(record["cleanup_complete"], True)
            self.assertNotIn("PRIVATE_SENTINEL", output.getvalue())


if __name__ == "__main__":
    unittest.main()
