"""Fresh-evidence wrapper contracts; all positive artifacts here are unit fixtures."""

import copy
import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "runtime_acceptance_under_test", ROOT / "local-setup/scripts/p1_runtime_acceptance.py"
)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def traces(real=False):
    result = {
        role: {
            "span_count": 1,
            "privacy_verified": True,
            "current_task_correlated": True,
            "query_api": "v3_raw_otlp",
        }
        for role in ("business-api", "conversation-agent", "durable-worker")
    }
    if real:
        result["conversation-agent"].update(
            models=["base.en", "qwen3:4b-instruct", "en_US-ljspeech-medium"],
            tools=["submit_investigation", "get_case"],
        )
    return result


def worker_quiescence_fixture():
    return {
        "schema_version": 1,
        "phase": "resumed",
        "quiescence_observed": True,
        "request_unresolved": False,
        "quiescence_checks": 1,
        "resume_checks": 1,
        "idle_snapshots": 1,
        "quiesce_signal_requests": 1,
        "resume_signal_requests": 1,
    }


def browser_fixture(real=False):
    tasks = 9 if real else 1
    value = {
        "status": "passed",
        "cleanup_verified": True,
        "run_id": "a" * 32,
        "mode": "local_real" if real else "local_synthetic_scripted",
        "module_hashes": {},
        "browser": {
            "required_cases": 2 if real else 6,
            "passed_cases": 2 if real else 6,
            "observations": {"actual_browser_assertions": True},
        },
        "traces": traces(real),
        "authority": {
            "revision": 1,
            "mutations": 1,
            "apply_calls": 1,
            "inquiries": tasks,
            "receiver_events": tasks,
        },
        "durable_counts": {"tasks": tasks, "intents": 1, "consumptions": 1},
    }
    if real:
        value.update(
            schema_version=1,
            model_manifest_sha256=runner.MODEL_MANIFEST,
            model_setup={
                "status": "verified",
                "profile": "p1-local-real-v1",
                "files": 10,
                "runtime_downloads": False,
            },
            cohort={
                "accepted": 8,
                "pending_before_end": 8,
                "pending_after_end": 8,
                "inquiry_succeeded_after_end": 8,
                "explicitly_cancelled_after_measurement": 8,
                "cleanup_deliveries": 8,
                "lost_accepted": 0,
                "pre_human_zero_apply_proven": True,
                "durable_identity_payload_matches": 9,
                "independent_inquiry_receipts_matched": 9,
                "independent_inquiry_receipts_matched_before_cleanup": 9,
                "worker_quiescence": worker_quiescence_fixture(),
            },
            engine_inference={
                role: {
                    "requests": 1,
                    "succeeded": 1,
                    "failed": 0,
                    "processed_input_bytes": 10,
                    "processed_output_bytes": 10,
                    "duration_seconds": 0.1,
                }
                for role in ("stt", "tts")
            },
            resources={
                role: {"before": {"counter": 1}, "after": {"counter": 2}}
                for role in ("native", "llm", "stt", "tts")
            },
        )
    else:
        value.update(
            slow_postgres={
                "native_wait_observed": True,
                "schema_advisory_wait_verified": True,
                "release_within_lock_timeout": True,
                "native_wait_seconds": 0.5,
            },
            held_supplier={
                "sqlite_exclusive_observed": True,
                "controls_completed_while_held": True,
                "release_within_provider_timeout": True,
                "quote_wait_seconds": 0.3,
            },
        )
    return value


class RuntimeEvidenceTests(unittest.TestCase):
    def test_provider_trust_requires_exact_metadata_actual_artifact_and_positive_bounded_bytes(
        self,
    ):
        trust = {
            "source": "explicit_ca_bundle",
            "bundle_sha256": "c" * 64,
            "bundle_bytes": 123,
            "native_only_mount_verified": True,
        }
        path = self.artifact / "provider-trust.json"
        runner.verify_provider_trust({"provider_trust": {"source": "image_os"}}, self.artifact)
        with self.assertRaises(runner.EvidenceError):
            runner.verify_provider_trust({"provider_trust": trust}, self.artifact)
        path.write_text(json.dumps(trust))
        runner.verify_provider_trust({"provider_trust": trust}, self.artifact)
        for change in (
            {"bundle_bytes": True},
            {"bundle_bytes": 0},
            {"bundle_bytes": 524289},
            {"bundle_sha256": "PRIVATE"},
            {"native_only_mount_verified": False},
            {"source": "ambient"},
            {"extra": "PRIVATE"},
        ):
            with self.subTest(change=change), self.assertRaises(runner.EvidenceError):
                runner.verify_provider_trust({"provider_trust": {**trust, **change}}, self.artifact)
        with self.assertRaises(runner.EvidenceError):
            runner.verify_provider_trust({"provider_trust": {"source": "image_os"}}, self.artifact)

    def test_explicit_ca_path_is_forwarded_only_for_provider_case_twenty_without_retaining_path(
        self,
    ):
        for case, mode, expected in (
            ("P1-20", "provider_real", True),
            ("P1-20", "local_real", False),
            ("P1-14", "provider_real", False),
        ):
            seen = []

            def command(_root, argv, _deadline, seen=seen):
                seen.append(argv)
                raise RuntimeError("stop-synthetic-before-runtime")

            with (
                patch.dict(os.environ, {"P1_PROVIDER_CA_BUNDLE": "/explicit/public-ca.pem"}),
                patch.object(
                    runner,
                    "load_tool",
                    return_value=SimpleNamespace(read_ca_bundle=lambda _p: b"synthetic public CA"),
                ),
                patch.object(runner, "command", side_effect=command),
            ):
                report, code = runner.run_case(case, root=self.root, real_profile=mode)
            self.assertEqual(1, code)
            self.assertEqual(expected, "--provider-ca-bundle" in seen[0])
            if expected:
                self.assertEqual(
                    "/explicit/public-ca.pem", seen[0][seen[0].index("--provider-ca-bundle") + 1]
                )
            self.assertNotIn("/explicit", json.dumps(report))

    @staticmethod
    def failure_output():
        return {
            "status": "failed",
            "code": "phase_g_demo_failed",
            "action": "inspect_retained_safe_evidence",
            "failure": {
                "schema_version": 1,
                "error_category": "FileNotFoundError",
                "source": "stack",
                "line": 404,
            },
        }

    def test_closed_preflight_failure_accepts_only_exact_builtin_sources_and_numeric_lines(self):
        valid = self.failure_output()
        helper = runner.load_tool(ROOT / "local-setup/scripts/phase_g_demo.py")
        self.assertEqual(
            runner.PREFLIGHT_ERROR_CATEGORIES,
            {name for _, name in helper.PREFLIGHT_ERROR_TYPES} | {"other"},
        )
        self.assertEqual(
            runner.PREFLIGHT_SOURCES, set(helper.PREFLIGHT_SOURCE_FILES) | {"unavailable"}
        )
        self.assertEqual(runner.child_failure_projection(json.dumps(valid)), valid["failure"])
        for category in runner.PREFLIGHT_ERROR_CATEGORIES:
            for source in runner.PREFLIGHT_SOURCES:
                value = copy.deepcopy(valid)
                value["failure"].update(
                    error_category=category, source=source, line=0 if source == "unavailable" else 1
                )
                self.assertEqual(
                    runner.child_failure_projection(json.dumps(value)), value["failure"]
                )

    def test_preflight_projection_rejects_hostile_unknown_duplicate_extra_and_nonfinite_data(self):
        valid = self.failure_output()
        for field, value in (
            ("schema_version", True),
            ("error_category", "PRIVATE"),
            ("error_category", {}),
            ("source", "/PRIVATE/stack.py"),
            ("source", "stack.py"),
            ("line", True),
            ("line", 1.0),
            ("line", float("nan")),
            ("line", -1),
            ("line", 100001),
            ("line", 0),
        ):
            changed = copy.deepcopy(valid)
            changed["failure"][field] = value
            with self.subTest(field=field, value=value):
                self.assertIsNone(runner.child_failure_projection(json.dumps(changed)))
        for level in ("outer", "inner"):
            changed = copy.deepcopy(valid)
            (changed if level == "outer" else changed["failure"])["private_body"] = "PRIVATE-KEY"
            self.assertIsNone(runner.child_failure_projection(json.dumps(changed)))
        for invalid in (
            "",
            "PRIVATE-STDOUT",
            "x" * 8193,
            '{"status":"failed","status":"passed"}',
            json.dumps({**valid, "status": "passed"}),
            json.dumps({**valid, "code": "PRIVATE"}),
        ):
            self.assertIsNone(runner.child_failure_projection(invalid))
        for field in valid["failure"]:
            changed = copy.deepcopy(valid)
            del changed["failure"][field]
            self.assertIsNone(runner.child_failure_projection(json.dumps(changed)))

    def test_failed_child_projection_survives_missing_artifacts_without_claiming_cleanup(self):
        with patch.object(runner, "command", return_value=(1, json.dumps(self.failure_output()))):
            report, code = runner.run_case("P1-20", root=self.root, real_profile="provider_real")
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["testCount"], 0)
        self.assertEqual(report["skippedCount"], 0)
        evidence = json.loads(
            next(
                (self.root / ".local/validation/p1-runtime-acceptance").glob("*/evidence.json")
            ).read_text()
        )
        self.assertEqual(evidence["child_failure"], self.failure_output()["failure"])
        self.assertFalse(evidence["cleanup_verified"])
        self.assertEqual(evidence["child_exit_code"], 1)
        self.assertEqual(evidence["artifacts"], [])
        self.assertNotIn("stdout", evidence)

    def test_nonzero_raw_child_output_is_discarded_and_never_becomes_a_pass(self):
        with patch.object(runner, "command", return_value=(1, "PRIVATE-TOKEN-RAW-STDOUT")):
            report, code = runner.run_case("P1-14", root=self.root)
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "failed")
        evidence = next(
            (self.root / ".local/validation/p1-runtime-acceptance").glob("*/evidence.json")
        ).read_text()
        self.assertNotIn("PRIVATE", evidence)
        self.assertNotIn("child_failure", json.loads(evidence))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / ".local/validation").mkdir(parents=True)
        (self.root / "local-setup/scripts").mkdir(parents=True)
        (self.root / "local-setup/scripts/phase_g_demo.py").write_text(
            "# controlled helper fixture"
        )
        self.artifact = self.root / ".local/validation/fresh"
        self.artifact.mkdir()
        (self.artifact / "playwright.json").write_text(json.dumps({"stats": {"skipped": 0}}))
        (self.artifact / "playwright-stats.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": "a" * 32,
                    "stats": {"expected": 2, "unexpected": 0, "skipped": 0, "flaky": 0},
                }
            )
        )
        for name in ("real-browser-observations.json", "business-browser-observations.json"):
            (self.artifact / name).write_text('{"actual":true}')

    def verify(self, value, real=False):
        def verify_browser(observations, report, **_kwargs):
            if observations != {"actual": True} or report != (
                {"stats": {"expected": 2, "unexpected": 0, "skipped": 0, "flaky": 0}}
                if real
                else {"stats": {"skipped": 0}}
            ):
                raise ValueError("private-sentinel")
            return value["browser"]

        verifier = SimpleNamespace(
            verify_browser=verify_browser,
            resource_window=lambda before, after, **_: {"before": before, "after": after},
        )
        with (
            patch.object(runner, "source_hashes", return_value={}),
            patch.object(runner, "load_tool", return_value=verifier),
        ):
            return runner.verify_browser(
                value, root=self.root, run_id="a" * 32, real=real, artifact=self.artifact
            )

    def test_scripted_and_real_full_unit_projections_require_actual_raw_runner_verification(self):
        self.assertEqual(6, self.verify(browser_fixture()))
        self.assertEqual(2, self.verify(browser_fixture(True), True))
        (self.artifact / "playwright.json").write_text('{"stats":{"skipped":1}}')
        with self.assertRaises(ValueError):
            self.verify(browser_fixture())

    def test_real_browser_requires_complete_bounded_quiescence_proof(self):
        original = browser_fixture(True)
        for checks in (1, 2001):
            value = copy.deepcopy(original)
            value["cohort"]["worker_quiescence"].update(
                quiescence_checks=checks, resume_checks=checks, idle_snapshots=checks
            )
            before = copy.deepcopy(value)
            self.assertEqual(self.verify(value, True), 2)
            self.assertEqual(value, before)
        self.assertEqual(self.verify(browser_fixture()), 6)

    def test_missing_or_partial_quiescence_proof_never_becomes_a_real_browser_pass(self):
        for proof in (None, {}, [], True, "PRIVATE"):
            value = browser_fixture(True)
            value["cohort"]["worker_quiescence"] = proof
            with (
                self.subTest(kind=type(proof).__name__),
                self.assertRaises(runner.EvidenceError) as caught,
            ):
                self.verify(value, True)
            self.assertNotIn("PRIVATE", str(caught.exception))
        value = browser_fixture(True)
        value["cohort"].pop("worker_quiescence")
        with self.assertRaises(runner.EvidenceError):
            self.verify(value, True)
        for field in worker_quiescence_fixture():
            proof = worker_quiescence_fixture()
            proof.pop(field)
            with self.subTest(missing=field), self.assertRaises(runner.EvidenceError):
                runner.verify_worker_quiescence(proof)

    def test_quiescence_counters_reject_bool_numeric_coercion_zero_overflow_and_repeat_signals(
        self,
    ):
        fields = (
            "quiescence_checks",
            "resume_checks",
            "idle_snapshots",
            "quiesce_signal_requests",
            "resume_signal_requests",
        )
        for field in fields:
            for invalid in (
                True,
                False,
                0,
                -1,
                1.0,
                "1",
                None,
                2002,
                10**1000,
                float("nan"),
                float("inf"),
            ):
                proof = {**worker_quiescence_fixture(), field: invalid}
                with (
                    self.subTest(field=field, kind=type(invalid).__name__),
                    self.assertRaises(runner.EvidenceError),
                ):
                    runner.verify_worker_quiescence(proof)
        for field in ("quiesce_signal_requests", "resume_signal_requests"):
            for repeated in (2, 2001):
                with (
                    self.subTest(field=field, repeated=repeated),
                    self.assertRaises(runner.EvidenceError),
                ):
                    runner.verify_worker_quiescence(
                        {**worker_quiescence_fixture(), field: repeated}
                    )

    def test_quiescence_schema_flags_and_final_phase_are_exact_and_closed(self):
        for changes in (
            {"schema_version": True},
            {"schema_version": 1.0},
            {"schema_version": 2},
            {"phase": "paused"},
            {"phase": "resuming"},
            {"phase": "PRIVATE"},
            {"phase": None},
            {"quiescence_observed": 1},
            {"quiescence_observed": False},
            {"request_unresolved": 0},
            {"request_unresolved": True},
            {"extra": "PRIVATE"},
        ):
            with (
                self.subTest(fields=tuple(changes)),
                self.assertRaises(runner.EvidenceError) as caught,
            ):
                runner.verify_worker_quiescence({**worker_quiescence_fixture(), **changes})
            self.assertNotIn("PRIVATE", str(caught.exception))

    def test_health_counts_cached_mode_missing_cleanup_or_missing_raw_assertions_cannot_pass(self):
        values = [{"status": "passed"}, browser_fixture()]
        values[1]["mode"] = "health"
        for change in (
            {"cleanup_verified": False},
            {"run_id": "old"},
            {"module_hashes": {"stale": "a"}},
            {"browser": {"required_cases": 6, "passed_cases": 5}},
            {"traces": {}},
            {"durable_counts": {"tasks": 0}},
        ):
            values.append({**browser_fixture(), **change})
        for value in values:
            with self.subTest(fields=tuple(value)), self.assertRaises(ValueError):
                self.verify(value)
        (self.artifact / "business-browser-observations.json").unlink()
        with self.assertRaises(ValueError):
            self.verify(browser_fixture())

    def test_real_requires_progress_after_end_positive_model_work_and_exact_confirmation_truth(
        self,
    ):
        for field, change in [
            ("cohort", {"lost_accepted": 1}),
            ("cohort", {"inquiry_succeeded_after_end": 0}),
            ("cohort", {"pre_human_zero_apply_proven": False}),
            ("model_setup", {"runtime_downloads": True}),
            ("authority", {"apply_calls": 2}),
        ]:
            value = browser_fixture(True)
            value[field].update(change)
            with self.subTest(field=field, change=change), self.assertRaises(ValueError):
                self.verify(value, True)
        for field, number in [
            ("succeeded", 0),
            ("failed", 1),
            ("duration_seconds", 0),
            ("processed_output_bytes", 0),
            ("requests", 2),
        ]:
            value = browser_fixture(True)
            value["engine_inference"]["stt"][field] = number
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.verify(value, True)

    def test_h2_selected_case_requires_new_driver_current_manifest_truth_and_role_shutdown(self):
        (self.root / "harness/workloads").mkdir(parents=True)
        declaration = {"base_manifest_sha256": "b" * 64}
        (self.root / "harness/workloads/p1-reliability-v1.json").write_text(json.dumps(declaration))
        digest = hashlib.sha256(
            json.dumps(declaration, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        item = {
            "case": "slow-shutdown-w2",
            "status": "passed",
            "cleanup_verified": True,
            "original_deadlines_preserved": True,
            "old_containers_observed_stopped": True,
            "new_process_lifetimes_observed": True,
            "provenance": {"module_hashes": {}},
            "outcomes": {
                "accepted": 8,
                "rejected": 24,
                "inquiry_succeeded": 8,
                "explicitly_cancelled_after_measurement": 8,
                "receiver_events": 8,
                "lost_accepted": 0,
                "apply_calls": 0,
                "mutations": 0,
            },
            "stopped_exit_codes": {"api": 143, "worker-1": 0, "worker-2": 0},
            "expected_stop_exit_codes": {"api": 143, "worker-1": 0, "worker-2": 0},
            "api_shutdown_observation": {
                "application_shutdown_complete_events": 1,
                "server_process_finished_events": 1,
            },
            "drain_observation": {
                "ready": False,
                "active_children": 1,
                "observed_to_release_seconds": 1.1,
            },
        }
        value = {
            "schema_version": 1,
            "status": "passed",
            "driver_sha256": "d" * 64,
            "coverage": "selected_case",
            "selected_case_names": ["slow-shutdown-w2"],
            "declared_case_count": 4,
            "manifest_sha256": digest,
            "base_manifest_sha256": "b" * 64,
            "cleanup_failures": [],
            "failure": None,
            "cases": [item],
        }
        with patch.object(runner, "source_hashes", return_value={}):
            self.assertEqual(1, runner.verify_h2(value, root=self.root, driver_sha256="d" * 64))
            for changes in (
                {"coverage": "complete_manifest"},
                {"driver_sha256": "e" * 64},
                {"cleanup_failures": ["failed"]},
                {"cases": []},
                {"selected_case_names": ["restart-w2"]},
                {"manifest_sha256": "old"},
            ):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    runner.verify_h2({**value, **changes}, root=self.root, driver_sha256="d" * 64)
            for field, change in [
                ("stopped_exit_codes", {"api": 0, "worker-1": 0, "worker-2": 0}),
                (
                    "api_shutdown_observation",
                    {
                        "application_shutdown_complete_events": 0,
                        "server_process_finished_events": 1,
                    },
                ),
                (
                    "drain_observation",
                    {"ready": False, "active_children": 1, "observed_to_release_seconds": 0.2},
                ),
            ]:
                invalid = copy.deepcopy(value)
                invalid["cases"][0][field] = change
                with self.subTest(field=field), self.assertRaises(ValueError):
                    runner.verify_h2(invalid, root=self.root, driver_sha256="d" * 64)

    def test_new_directory_nonzero_child_and_private_exception_never_reuse_old_browser_report(self):
        with patch.object(runner, "command", side_effect=RuntimeError("private-sentinel")):
            report, code = runner.run_case("P1-20", root=self.root)
        self.assertEqual(1, code)
        self.assertEqual("failed", report["status"])
        self.assertEqual("live", report["mode"])
        files = list(
            (self.root / ".local/validation/p1-runtime-acceptance").glob("*/evidence.json")
        )
        self.assertEqual(1, len(files))
        evidence = json.loads(files[0].read_text())
        self.assertFalse(evidence["cleanup_verified"])
        self.assertEqual("browser", evidence["failure_stage"])
        self.assertIn("p1-20-", evidence["child_artifact_directory"])
        self.assertNotIn("private-sentinel", json.dumps(report) + files[0].read_text())
        self.assertEqual([], list((self.root / ".local").glob("private-*")))

    def test_complete_scripted_wrapper_requires_all6_browser_and_all3_postcommit_assertions(self):
        value = browser_fixture()
        commands = []

        def command(_root, argv, _deadline):
            commands.append(argv)
            if "--pg-only" in argv:
                path = Path(argv[argv.index("--report") + 1])
                pg = {
                    "schemaVersion": 1,
                    "caseId": "P1-14",
                    "mode": "lab",
                    "status": "passed",
                    "testCount": 3,
                    "skippedCount": 0,
                    "failureCount": 0,
                    "errorCount": 0,
                    "durationSeconds": 0.1,
                    "code": "passed",
                }
                path.write_text(json.dumps(pg))
            else:
                path = Path(argv[argv.index("--artifact-root") + 1])
                path.mkdir()
                (path / "container-demo.json").write_text(json.dumps(value))
                (path / ("cleanup-" + value["run_id"] + ".json")).write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "run_id": value["run_id"],
                            "status": "passed",
                            "cleanup_verified": True,
                            "codes": [],
                        }
                    )
                )
                (path / "business-browser-observations.json").write_text('{"actual":true}')
                (path / "playwright.json").write_text('{"stats":{"skipped":0}}')
            return 0, "private-capture-sentinel"

        verifier = SimpleNamespace(verify_browser=lambda *_: value["browser"])
        with (
            patch.object(runner, "command", side_effect=command),
            patch.object(runner, "source_hashes", return_value={}),
            patch.object(runner, "load_tool", return_value=verifier),
        ):
            report, code = runner.run_case("P1-14", root=self.root)
        self.assertEqual((0, "passed", 9), (code, report["status"], report["testCount"]))
        self.assertEqual("lab", report["mode"])
        self.assertEqual(2, len(commands))
        self.assertEqual("scripted", commands[0][commands[0].index("--mode") + 1])
        self.assertEqual("600", commands[0][commands[0].index("--work-seconds") + 1])
        evidence = next(
            iter((self.root / ".local/validation/p1-runtime-acceptance").glob("*/evidence.json"))
        )
        self.assertTrue(json.loads(evidence.read_text())["cleanup_verified"])
        self.assertNotIn("private-capture-sentinel", evidence.read_text())
        self.assertEqual([], list((self.root / ".local").glob("private-*")))

    def test_existing_h2_uuid_cannot_be_adopted_even_if_its_stdout_says_passed(self):
        scripts = self.root / "local-setup/scripts"
        scripts.mkdir(parents=True, exist_ok=True)
        (scripts / "p1_reliability.py").write_text("# controlled driver fixture")
        stale = self.root / ".local/validation/p1-phase-h2" / ("b" * 32)
        stale.mkdir(parents=True)
        (stale / "summary.json").write_text('{"status":"passed"}')
        output = json.dumps({"status": "passed", "cases_passed": 1, "report": str(stale)})
        with patch.object(runner, "command", return_value=(0, output)):
            report, code = runner.run_case("P1-18", root=self.root)
        self.assertEqual(1, code)
        self.assertEqual(0, report["testCount"])
        self.assertEqual('{"status":"passed"}', (stale / "summary.json").read_text())
        evidence = next(
            iter((self.root / ".local/validation/p1-runtime-acceptance").glob("*/evidence.json"))
        )
        self.assertFalse(json.loads(evidence.read_text())["cleanup_verified"])

    def test_fixed_case_taxonomy_does_not_follow_ambient_model_flags(self):
        with (
            patch.dict(
                os.environ, {"P1_CONVERSATION_INFERENCE": "scripted", "P1_TRACE_MODE": "lab"}
            ),
            patch.object(runner, "command", side_effect=RuntimeError("private-sentinel")),
        ):
            real, _ = runner.run_case("P1-20", root=self.root)
            scripted, _ = runner.run_case("P1-14", root=self.root)
        self.assertEqual("live", real["mode"])
        self.assertEqual("lab", scripted["mode"])

    def test_actual_owned_command_discards_stderr_and_reaps_timeout_child(self):
        import sys
        import time

        code, output = runner.command(
            self.root,
            [
                sys.executable,
                "-c",
                "import sys;print('safe');print('private-command-sentinel',file=sys.stderr)",
            ],
            time.monotonic() + 3,
        )
        self.assertEqual((0, "safe\n"), (code, output))
        self.assertEqual([], list((self.root / ".local").glob("private-runtime-*")))
        with self.assertRaises(runner.ProcessTimeout):
            runner.command(
                self.root,
                [sys.executable, "-c", "import time;time.sleep(20)"],
                time.monotonic() + 0.03,
            )
        self.assertEqual([], list((self.root / ".local").glob("private-runtime-*")))

    def test_bounded_regular_artifact_reader_and_reference_reject_inert_malicious_shapes(self):
        for raw in [b'{"status":1,"status":2}', b'{"x":NaN}', b"\xff", b"x" * 2097153]:
            target = self.artifact / "data.json"
            target.write_bytes(raw)
            with self.assertRaises(ValueError):
                runner.read_json(target)
        target = self.artifact / "data.json"
        target.unlink()
        os.mkfifo(target)
        with self.assertRaises(ValueError):
            runner.read_json(target)
        target.unlink()
        target.write_text("{}")
        link = self.artifact / "link"
        link.symlink_to(target)
        with self.assertRaises(ValueError):
            runner.read_json(link)
        for value in ["relative", str(self.artifact), str(link)]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                runner.browser_path(value)


if __name__ == "__main__":
    unittest.main()
