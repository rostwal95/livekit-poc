"""Actual media gates reject stale, partial, reset and foreign evidence/resources."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
import threading
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

SCRIPTS = Path(__file__).resolve().parents[1] / "local-setup/scripts"
sys.path.insert(0, str(SCRIPTS))
import p1_demo_ownership as ownership
import p1_real_media as media

SPEC = importlib.util.spec_from_file_location("p1_real_demo_test", SCRIPTS / "phase_g_demo.py")
assert SPEC is not None and SPEC.loader is not None
demo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(demo)
RUN = "1" * 32
TASK = "11111111-1111-4111-8111-111111111111"


class RealEvidenceTests(unittest.TestCase):
    def test_native_failure_aggregation_discards_unvalidated_raw_content(self):
        record = {
            "service": "conversation-agent",
            "timestamp": "PRIVATE-TIMESTAMP",
            "severity": "error",
            "event": "session_failed",
            "code": "session_media_ready_timeout",
        }
        raw = "\n".join(
            [
                json.dumps(record),
                json.dumps(record),
                "PRIVATE prompt body",
                json.dumps({**record, "request": "PRIVATE"}),
                json.dumps({**record, "code": "PRIVATE"}),
                '{"event":"PRIVATE","event":"session_failed"}',
            ]
        )
        value = demo.safe_native_log_summary(raw)
        self.assertEqual(value["accepted_lines"], 2)
        self.assertEqual(value["discarded_lines"], 4)
        self.assertEqual(
            value["records"],
            [
                {
                    "event": "session_failed",
                    "code": "session_media_ready_timeout",
                    "severity": "error",
                    "count": 2,
                }
            ],
        )
        self.assertNotIn("PRIVATE", json.dumps(value))
        for invalid in ("x" * 262145, "x\n" * 501):
            with self.assertRaises(ValueError):
                demo.safe_native_log_summary(invalid)

    def test_browser_failure_location_retains_no_messages_stacks_titles_or_unknown_paths(self):
        class Private:
            def __str__(self):
                raise AssertionError("Private browser text must not be read")

            def __repr__(self):
                raise AssertionError("Private browser repr must not be read")

        root = Path("/owned")
        result = {
            "status": "failed",
            "error": {
                "message": Private(),
                "stack": Private(),
                "location": {
                    "file": "/owned/apps/local-console/e2e/local-real.media.ts",
                    "line": 42,
                    "column": 30,
                },
            },
        }
        report = {
            "suites": [
                {
                    "specs": [
                        {
                            "title": "runs actual fixture inference, ends with eight accepted inquiries, and resumes the same case",
                            "tests": [{"results": [result]}],
                        }
                    ]
                }
            ]
        }
        value = media.safe_playwright_failure(report, source_root=root, source_lines=150)
        self.assertEqual(
            value["failures"],
            [
                {
                    "case": 1,
                    "code": "browser_case_failed",
                    "source_location_observed": True,
                    "source_line": 42,
                    "source_column": 30,
                }
            ],
        )
        self.assertNotIn("PRIVATE", json.dumps(value))
        self.assertNotIn("stack", json.dumps(value))
        result["error"]["location"]["file"] = "/PRIVATE/local-real.media.ts"
        value = media.safe_playwright_failure(report, source_root=root, source_lines=150)
        self.assertFalse(value["failures"][0]["source_location_observed"])
        self.assertNotIn("PRIVATE", json.dumps(value))
        result["error"]["location"].update(file="local-real.media.ts", line=151)
        self.assertFalse(
            media.safe_playwright_failure(report, source_root=root, source_lines=150)["failures"][
                0
            ]["source_location_observed"]
        )
        report["suites"][0]["specs"][0]["tests"][0]["results"].append(result)
        with self.assertRaises(ValueError):
            media.safe_playwright_failure(report, source_root=root, source_lines=150)

    def cohort(self, path):
        return media.PendingCohort(
            worker="owned",
            label="owned",
            directory=path,
            token="PRIVATE",
            control=Mock(),
            runtime=Mock(),
        )

    def test_cohort_never_started_owns_no_worker_cleanup_but_cannot_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            cohort = self.cohort(Path(folder))
            cohort.close()
            cohort.control.assert_not_called()
            self.assertIsNone(cohort.error)
            self.assertEqual(cohort.observation()["status"], "stopped")
            with self.assertRaises(RuntimeError):
                cohort.require_complete()

    def test_cohort_cancel_before_arm_exits_its_thread_without_false_cleanup_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            cohort = self.cohort(Path(folder))
            cohort.thread.start()
            original = RuntimeError("original browser failure")
            with self.assertRaises(RuntimeError) as caught:
                try:
                    raise original
                finally:
                    cohort.close()
            self.assertIs(caught.exception, original)
            self.assertFalse(cohort.thread.is_alive())
            self.assertFalse(cohort.paused)
            self.assertIsNone(cohort.error)
            self.assertIsNone(cohort.cleanup_error)
            self.assertEqual(cohort.accepted, [])
            cohort.control.assert_not_called()
            with self.assertRaises(RuntimeError):
                cohort.require_complete()

    def test_cohort_operation_failure_remains_nonpassing_without_claiming_resource_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            cohort = self.cohort(Path(folder))
            cohort.error = ValueError("PRIVATE")
            cohort.close()
            self.assertTrue(cohort.observation()["operation_error_observed"])
            self.assertFalse(cohort.observation()["cleanup_error_observed"])
            self.assertNotIn("PRIVATE", json.dumps(cohort.observation()))
            with self.assertRaises(RuntimeError):
                cohort.require_complete()

    def test_cohort_unresolved_worker_ownership_or_resume_error_still_fails_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            cohort = self.cohort(Path(folder))
            cohort.thread = threading.Thread(target=lambda: None)
            cohort.thread.start()
            cohort.thread.join()
            cohort.paused = True
            with self.assertRaises(RuntimeError):
                cohort.close()
            cohort.paused = False
            cohort.cleanup_error = ValueError("PRIVATE")
            with self.assertRaises(RuntimeError):
                cohort.close()
            with self.assertRaises(RuntimeError):
                cohort.require_complete()

    def test_container_platform_manifest_must_match_the_built_platform_not_the_index(self):
        descriptor = {
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "digest": "sha256:" + "1" * 64,
            "size": 1813,
            "platform": {"architecture": "arm64", "os": "linux"},
        }
        self.assertEqual(
            descriptor["digest"], media.platform_manifest(descriptor, copy.deepcopy(descriptor))
        )
        for changed in (
            None,
            {**descriptor, "digest": "sha256:" + "2" * 64},
            {**descriptor, "mediaType": "application/vnd.oci.image.index.v1+json"},
            {**descriptor, "platform": {"architecture": "amd64", "os": "linux"}},
            {**descriptor, "size": True},
        ):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                media.platform_manifest(descriptor, changed)

    def test_real_model_manifest_uses_the_preparation_canonical_digest(self):
        root = SCRIPTS.parents[1]
        self.assertEqual(media.MODEL_MANIFEST_SHA256, media.model_manifest(root))
        raw = (root / "local-setup/models/local-model-manifest.json").read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            candidate = Path(folder)
            path = candidate / "local-setup/models/local-model-manifest.json"
            path.parent.mkdir(parents=True)
            value = json.loads(raw)
            path.write_text(json.dumps(dict(reversed(list(value.items()))), indent=1) + "\n")
            self.assertEqual(media.MODEL_MANIFEST_SHA256, media.model_manifest(candidate))
            value["engines"]["llm"]["version"] = "changed"
            path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):
                media.model_manifest(candidate)
            path.write_bytes(
                raw.replace(b'"schema_version": 1', b'"schema_version":1,"schema_version":1', 1)
            )
            with self.assertRaises(ValueError):
                media.model_manifest(candidate)

    def test_work_timeout_and_shutdown_reserve_cleanup_without_stealing_an_alarm(self):
        now = [100.0]
        deadline = media.WorkDeadline(clock=lambda: now[0])
        with (
            patch.object(media.signal, "getitimer", return_value=(0.0, 0.0)),
            patch.object(media.signal, "getsignal", return_value=media.signal.SIG_DFL),
            patch.object(media.signal, "signal"),
            patch.object(media.signal, "setitimer") as timer,
        ):
            deadline.start()
            self.assertEqual(deadline.timeout(300), 300)
            now[0] = 700
            with self.assertRaises(media.MediaDeadline):
                deadline.timeout(1)
            with self.assertRaises(media.MediaDeadline):
                deadline._terminated(media.signal.SIGTERM, None)
            deadline.begin_cleanup()
            self.assertEqual(deadline.timeout(180), 180)
            deadline._terminated(media.signal.SIGTERM, None)
            now[0] = 881
            with self.assertRaises(media.MediaDeadline):
                deadline.timeout(1)
            deadline.finish()
            self.assertIn(
                ((media.signal.ITIMER_REAL, 600),), [(call.args,) for call in timer.call_args_list]
            )
            self.assertIn(
                ((media.signal.ITIMER_REAL, 180),), [(call.args,) for call in timer.call_args_list]
            )
        with (
            patch.object(media.signal, "getitimer", return_value=(1.0, 0.0)),
            self.assertRaises(ValueError),
        ):
            media.WorkDeadline().start()

    def test_explicit_artifacts_require_a_fresh_owned_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            parent = root / ".local/validation"
            parent.mkdir(parents=True)
            fresh = parent / "fresh"
            self.assertEqual(media.artifact_root(root, fresh), fresh)
            fresh.mkdir()
            for path in (fresh, root / "outside", parent / "fresh/../other", Path("relative")):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    media.artifact_root(root, path)
            (parent / "link").symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError):
                media.artifact_root(root, parent / "link/new")

    def test_all_nine_durable_payloads_and_independent_receipts_must_reconcile(self):
        from uuid import UUID

        request = {
            "booking_reference": "DEMO-BK-001",
            "new_check_in": "2030-12-10",
            "confirmed": True,
        }
        items = [
            {
                "task_id": str(UUID(int=index)),
                "case_id": str(UUID(int=index + 20)),
                "effect_id": str(UUID(int=index + 40)),
                "key": str(UUID(int=index + 60)),
                "request": request,
            }
            for index in range(1, 10)
        ]
        rows = [
            {
                "task_id": item["task_id"],
                "key": item["key"],
                "effect_id": item["effect_id"],
                "payload": media.canonical(request).decode(),
            }
            for item in items
        ]
        import hashlib

        receipts = [
            {
                "effect_id": item["effect_id"],
                "request_sha256": hashlib.sha256(media.canonical(request)).hexdigest(),
                "result_sha256": hashlib.sha256(
                    media.canonical(
                        {
                            "booking_reference": "DEMO-BK-001",
                            "new_check_in": "2030-12-10",
                            "available": True,
                        }
                    )
                ).hexdigest(),
            }
            for item in items
        ]
        connection = Mock()
        connection.execute.return_value.fetchall.return_value = rows
        runtime = SimpleNamespace(
            schema="p1_conversation_demo_" + RUN, connect=Mock(return_value=connection)
        )
        cohort = media.PendingCohort(
            worker="owned",
            label="owner",
            directory=Path("/private/tmp"),
            token="private",
            control=Mock(),
            runtime=runtime,
        )
        cohort.accepted = items[:8]
        first = items[8]
        cohort.foreground = {
            "task_id": first["task_id"],
            "request_key": first["key"],
            "inquiry": {"effect_id": first["effect_id"], "request": request},
        }
        cohort.result = {"accepted": 8}
        self.assertEqual(cohort.reconcile(receipts)["independent_inquiry_receipts_matched"], 9)
        for invalid in (
            receipts[:-1],
            [*receipts[:-1], receipts[0]],
            [*receipts[:-1], {**receipts[-1], "result_sha256": "0" * 64}],
        ):
            with self.subTest(receipts=invalid), self.assertRaises(ValueError):
                cohort.reconcile(invalid)
        connection.execute.return_value.fetchall.return_value = [
            {**rows[0], "payload": "changed"},
            *rows[1:],
        ]
        with self.assertRaises(ValueError):
            cohort.reconcile(receipts)

    @staticmethod
    def mint_attempt(status=200, code="none"):
        return {
            "http_status": status,
            "error_code": code,
            **dict.fromkeys(media.MINT_BINDING_FLAGS, True),
        }

    def mint_join(self, statuses=(200,)):
        return {
            "attempts": [
                self.mint_attempt(
                    status,
                    "none"
                    if status == 200
                    else "transport_error"
                    if status == 0
                    else "unclassified",
                )
                for status in statuses
            ],
            "overflowed": False,
            "completed": True,
        }

    def browser(self):
        return {
            **dict.fromkeys(media.REAL_FLAGS, True),
            "schema_version": 1,
            "mode": "local_real",
            "run_id": RUN,
            "foreground_task_id": TASK,
            "browser_version": "143.0.7499.40",
            "playwright_version": "1.65.0",
            "last_phase": "confirm",
            "supplier_outcome": "succeeded",
            "delivery_state": "delivered",
            "session_mint_http_status": 200,
            "session_mint_error_code": "none",
            "session_mint_joins": [self.mint_join() for _ in range(4)],
            "audio_current_time": 1.2,
            "active_interrupt_seconds": 0.1,
            "pg_interrupt_seconds": 0.1,
            "supplier_interrupt_seconds": 0.1,
            "unexpected_network_requests": 0,
            "native_sessions": 4,
            "background_accepted": 8,
            "background_pending_at_end": 8,
            "background_completed_after_end": 8,
        }

    def test_browser_requires_current_invocation_and_every_finite_requirement(self):
        report = {"stats": {"expected": 2, "unexpected": 0, "skipped": 0, "flaky": 0}}
        self.assertEqual(
            media.verify_browser(self.browser(), report, run_id=RUN)["passed_cases"], 2
        )
        for field, number in (
            ("mode", "scripted"),
            ("run_id", "2" * 32),
            ("background_accepted", 7),
            ("native_sessions", 8),
            ("pg_interrupt_seconds", 1.51),
            ("supplier_interrupt_seconds", float("nan")),
            ("active_interrupt_seconds", True),
            ("generated_audio_played", False),
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                media.verify_browser({**self.browser(), field: number}, report, run_id=RUN)
        for field in media.REAL_FLAGS:
            value = self.browser()
            del value[field]
            with self.subTest(missing=field), self.assertRaises(ValueError):
                media.safe_browser(value, run_id=RUN, passing=False)
        for extra in ("last_status", "transcript", "prompt", "model_output"):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                media.safe_browser({**self.browser(), extra: "PRIVATE"}, run_id=RUN, passing=False)
        for field in ("skipped", "unexpected", "flaky"):
            wrong = copy.deepcopy(report)
            wrong["stats"][field] = 1
            with self.subTest(field=field), self.assertRaises(ValueError):
                media.verify_browser(self.browser(), wrong, run_id=RUN)

    def test_mint_retry_contract_accepts_only_supported_bounded_logical_progress(self):
        for statuses in ((200,), (503, 200), (504, 200), (503, 504, 200), (0, 503, 200)):
            joined = self.mint_join(statuses)
            with self.subTest(statuses=statuses):
                observed = media.safe_mint_joins([joined], native_sessions=1, passing=True)
                self.assertEqual(observed, [joined])
                self.assertEqual(len(observed), 1)
        value = self.browser()
        value["session_mint_joins"][0] = self.mint_join((503, 200))
        self.assertEqual(
            media.verify_browser(
                value,
                {"stats": {"expected": 2, "unexpected": 0, "skipped": 0, "flaky": 0}},
                run_id=RUN,
            )["passed_cases"],
            2,
        )

    def test_mint_retry_contract_rejects_changed_binding_unbounded_hidden_failures_and_missing_success(
        self,
    ):
        for flag in media.MINT_BINDING_FLAGS:
            joined = self.mint_join((503, 200))
            joined["attempts"][1][flag] = False
            with self.subTest(changed=flag), self.assertRaises(ValueError):
                media.safe_mint_joins([joined], native_sessions=1, passing=True)
        for statuses in (
            (401, 200),
            (403, 200),
            (409, 200),
            (422, 200),
            (500, 200),
            (200, 200),
            (503,),
            (),
            (503, 503, 503, 200),
        ):
            with self.subTest(statuses=statuses), self.assertRaises(ValueError):
                media.safe_mint_joins([self.mint_join(statuses)], native_sessions=1, passing=True)
        for field, changed in (("overflowed", True), ("completed", False)):
            joined = self.mint_join()
            joined[field] = changed
            with self.subTest(field=field), self.assertRaises(ValueError):
                media.safe_mint_joins([joined], native_sessions=1, passing=True)
        for sessions in (3, 5):
            value = self.browser()
            value["native_sessions"] = sessions
            value["session_mint_joins"] = [self.mint_join() for _ in range(sessions)]
            with self.subTest(logical_sessions=sessions), self.assertRaises(ValueError):
                media.safe_browser(value, run_id=RUN, passing=True)
        for sessions in (0, 2, True, 1.0):
            with self.subTest(sessions=sessions), self.assertRaises(ValueError):
                media.safe_mint_joins([self.mint_join()], native_sessions=sessions, passing=True)

    def test_failed_mint_joins_keep_safe_partial_diagnostics_without_counting_as_native_success(
        self,
    ):
        joined = self.mint_join((503,))
        joined["completed"] = False
        self.assertEqual(
            media.safe_mint_joins([joined], native_sessions=0, passing=False), [joined]
        )
        joined["attempts"][0]["same_invocation"] = False
        self.assertEqual(
            media.safe_mint_joins([joined], native_sessions=0, passing=False), [joined]
        )
        with self.assertRaises(ValueError):
            media.safe_mint_joins([joined], native_sessions=0, passing=True)
        for extra in ("room", "identity", "task_id", "invocation_id", "token", "body", "error"):
            invalid = self.mint_join()
            invalid["attempts"][0][extra] = "PRIVATE"
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                media.safe_mint_joins([invalid], native_sessions=1, passing=False)
        for field, changed in (
            ("http_status", True),
            ("http_status", float("nan")),
            ("error_code", "PRIVATE"),
            ("same_room", "true"),
        ):
            invalid = self.mint_join()
            invalid["attempts"][0][field] = changed
            with self.subTest(field=field), self.assertRaises(ValueError):
                media.safe_mint_joins([invalid], native_sessions=1, passing=False)

    def test_session_mint_failure_diagnostics_retain_only_fixed_status_and_category(self):
        for mode in ("local_real", "provider_real"):
            for status, code in (
                (0, "not_observed"),
                (200, "none"),
                (503, "dispatch_unavailable"),
                (409, "session_in_use"),
                (401, "authentication_required"),
                (503, "unclassified"),
            ):
                value = {
                    **self.browser(),
                    "mode": mode,
                    "session_mint_http_status": status,
                    "session_mint_error_code": code,
                }
                with self.subTest(mode=mode, status=status, code=code):
                    observed = media.safe_browser(value, run_id=RUN, passing=False, mode=mode)
                    self.assertEqual(observed["session_mint_http_status"], status)
                    self.assertEqual(observed["session_mint_error_code"], code)
                    if status != 200:
                        with self.assertRaises(ValueError):
                            media.safe_browser(value, run_id=RUN, passing=True, mode=mode)
        # Categories are the API's fixed vocabulary, independent of private detail.
        from services.control_api.telemetry import ERRORS

        self.assertEqual(media.SESSION_MINT_ERROR_CODES, frozenset(ERRORS))

    def test_session_mint_diagnostics_reject_raw_content_and_contradictory_states(self):
        for status, code in (
            (True, "none"),
            (200.0, "none"),
            (float("nan"), "none"),
            (-1, "unclassified"),
            (600, "unclassified"),
            (0, "dispatch_unavailable"),
            (200, "unclassified"),
            (503, "none"),
            (503, "not_observed"),
            (503, "PRIVATE-TOKEN-OR-MESSAGE"),
            (503, {"detail": "PRIVATE"}),
        ):
            value = {
                **self.browser(),
                "session_mint_http_status": status,
                "session_mint_error_code": code,
            }
            with self.subTest(status=status, code=code), self.assertRaises(ValueError):
                media.safe_browser(value, run_id=RUN, passing=False)
        for field in ("session_mint_http_status", "session_mint_error_code"):
            value = self.browser()
            del value[field]
            with self.subTest(missing=field), self.assertRaises(ValueError):
                media.safe_browser(value, run_id=RUN, passing=False)
        for field in ("session_mint_body", "session_mint_error", "session_mint_token"):
            with self.subTest(extra=field), self.assertRaises(ValueError):
                media.safe_browser({**self.browser(), field: "PRIVATE"}, run_id=RUN, passing=False)

    def test_failed_browser_keeps_unobserved_finite_values_without_becoming_a_pass(
        self,
    ):
        value = self.browser()
        value["generated_audio_played"] = False
        value["active_interrupt_seconds"] = 0
        self.assertFalse(
            media.safe_browser(value, run_id=RUN, passing=False)["generated_audio_played"]
        )
        with self.assertRaises(ValueError):
            media.safe_browser(value, run_id=RUN, passing=True)

    @staticmethod
    def metrics(engine, count):
        return {
            "schema_version": 1,
            "engine": engine,
            "requests": count,
            "succeeded": count,
            "failed": 0,
            "active": 0,
            "max_active": 1 if count else 0,
            "processed_input_bytes": count * 1000,
            "processed_output_bytes": count * 3000,
            "duration_seconds": count * 0.5,
        }

    def test_health_or_other_engine_or_reset_or_failure_cannot_count_as_real_inference(
        self,
    ):
        before, after = self.metrics("stt", 4), self.metrics("stt", 6)
        self.assertEqual(media.engine_delta(before, after, engine="stt")["succeeded"], 2)
        for invalid in (
            {"status": "ready"},
            self.metrics("tts", 6),
            self.metrics("stt", 3),
            {**after, "active": 2},
            {**after, "max_active": 2},
            {**after, "processed_output_bytes": 0},
            {**after, "duration_seconds": float("inf")},
            {**after, "requests": 7, "failed": 1},
            {**after, "succeeded": True},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                media.engine_delta(before, invalid, engine="stt")

    def test_resources_require_two_current_cpu_samples_and_exact_caps_not_rss_claim(
        self,
    ):
        memory, cpus, pids = media.RESOURCE_LIMITS["llm"]
        before = {
            "cpu_usage_usec": 100,
            "cpu_quota_usec": cpus * 100000,
            "cpu_period_usec": 100000,
            "memory_current_bytes": 1000,
            "memory_peak_bytes": 2000,
            "memory_limit_bytes": memory,
            "pids_current": 3,
            "pids_limit": pids,
            "oom_kills": 0,
        }
        result = media.resource_window(before, {**before, "cpu_usage_usec": 110}, role="llm")
        self.assertEqual(result["samples"], 2)
        self.assertEqual(result["memory_kind"], "cgroup_accounted")
        for changed in (
            {},
            {"cpu_usage_usec": 100},
            {"cpu_usage_usec": 99},
            {"oom_kills": 1},
            {"memory_limit_bytes": memory - 1},
            {"memory_peak_bytes": memory + 1},
            {"pids_current": pids + 1},
            {"cpu_quota_usec": 0},
        ):
            invalid = {} if not changed else {**before, "cpu_usage_usec": 110, **changed}
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                media.resource_window(before, invalid, role="llm")

    def test_real_sdk_rejects_scripted_and_requires_positive_generated_output(self):
        record = {
            "schema_version": 1,
            "mode": "local_real",
            "sdk_report_observed": True,
            "values": dict.fromkeys(demo.OBSERVATION_FIELDS, 1),
        }
        self.assertTrue(
            demo.verify_sdk([record, record], mode="local_real")["real_inference_usage_only"]
        )
        with self.assertRaises(ValueError):
            demo.verify_sdk([record] * 3)
        with self.assertRaises(ValueError):
            demo.verify_sdk([{**record, "mode": "scripted"}] * 2, mode="local_real")
        with self.assertRaises(ValueError):
            demo.verify_sdk(
                [{**record, "values": {**record["values"], "llm_output_tokens": 0}}] * 2,
                mode="local_real",
            )
        unobserved = {**record, "sdk_report_observed": False}
        self.assertEqual(demo.safe_sdk_failure([unobserved], mode="local_real")["reports"], 1)
        with self.assertRaises(ValueError):
            demo.verify_sdk([unobserved] * 2, mode="local_real")

    def test_otlp_model_identity_is_profile_specific_and_raw_content_is_rejected(self):
        def fixture(mode):
            return {
                "result": {
                    "resourceSpans": [
                        {
                            "resource": {
                                "attributes": [
                                    {"key": key, "value": {"stringValue": value}}
                                    for key, value in (
                                        ("service.name", "conversation-agent"),
                                        ("service.version", "0.1.0"),
                                        ("continuity.mode", mode),
                                    )
                                ]
                            },
                            "scopeSpans": [
                                {
                                    "scope": {
                                        "name": "continuity.safe",
                                        "version": "1",
                                    },
                                    "spans": [
                                        {
                                            "traceId": "1" * 32,
                                            "spanId": "2" * 16,
                                            "name": "function_tool",
                                            "kind": 1,
                                            "startTimeUnixNano": "1",
                                            "endTimeUnixNano": "2",
                                            "attributes": [
                                                {
                                                    "key": "continuity.task_id",
                                                    "value": {"stringValue": TASK},
                                                },
                                                {
                                                    "key": "gen_ai.request.model",
                                                    "value": {"stringValue": "qwen3:4b-instruct"},
                                                },
                                                {
                                                    "key": "gen_ai.tool.name",
                                                    "value": {"stringValue": "get_case"},
                                                },
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                }
            }

        value = fixture("local_real")
        result = demo.parse_jaeger_v3(
            json.dumps(value).encode(),
            service="conversation-agent",
            task_id=TASK,
            mode="local_real",
        )
        self.assertEqual(result["models"], ["qwen3:4b-instruct"])
        self.assertEqual(result["tools"], ["get_case"])
        with self.assertRaises(ValueError):
            demo.parse_jaeger_v3(
                json.dumps(value).encode(), service="conversation-agent", task_id=TASK
            )
        value["result"]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"].append(
            {"key": "prompt", "value": {"stringValue": "PRIVATE"}}
        )
        with self.assertRaises(ValueError):
            demo.parse_jaeger_v3(
                json.dumps(value).encode(),
                service="conversation-agent",
                task_id=TASK,
                mode="local_real",
            )

    def test_declaration_rejects_changed_model_count_and_capture_policy(self):
        root = Path(__file__).resolve().parents[1]
        original, digest = media.declaration(root)
        self.assertEqual(len(digest), 64)
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / "local-setup/workloads"
            directory.mkdir(parents=True)
            path = directory / "p1-local-real-v1.json"
            for change in (
                {"models": {**media.MODELS, "llm": "other"}},
                {"background_inquiries": 7},
                {"native_concurrency": True},
                {"fixture": {**original["fixture"], "capture_seconds": 0.8}},
            ):
                path.write_text(json.dumps({**original, **change}))
                with self.subTest(change=change), self.assertRaises(ValueError):
                    media.declaration(Path(folder))


class OwnershipTests(unittest.TestCase):
    def settings(self, *responses):
        connection = Mock()
        connection.transaction.return_value = nullcontext()
        connection.execute.side_effect = [
            SimpleNamespace(fetchone=lambda row=row: row) for row in responses
        ]
        return SimpleNamespace(
            schema="p1_conversation_demo_" + RUN, connect=Mock(return_value=connection)
        ), connection

    @staticmethod
    def dropped(connection):
        return any("DROP SCHEMA" in str(call.args[0]) for call in connection.execute.call_args_list)

    def test_existing_namespace_is_never_installed_marked_or_dropped(self):
        settings, connection = self.settings({"oid": 4, "owner": "someone", "marker": "foreign"})
        guard = ownership.SchemaOwnership(settings)
        install = Mock()
        with self.assertRaises(ValueError):
            guard.prepare(install)
        guard.cleanup()
        install.assert_not_called()
        self.assertFalse(self.dropped(connection))

    def test_unknown_marker_or_replaced_oid_fails_closed_without_drop(self):
        metadata = {
            "version": 1,
            "state": "staging",
            "migration_id": None,
            "source_digest": None,
            "tasks": 0,
        }
        for wrong in ("marker", "owner", "oid"):
            settings, connection = self.settings(
                None,
                {"oid": 4, "owner": "continuity_migrator", "marker": None},
                metadata,
                None,
            )
            guard = ownership.SchemaOwnership(settings)
            guard.prepare(Mock())
            row = {"oid": 4, "owner": "continuity_migrator", "marker": guard.marker}
            row[wrong] = {"marker": "foreign", "owner": "someone", "oid": 5}[wrong]
            connection.execute.side_effect = [SimpleNamespace(fetchone=lambda row=row: row)]
            with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                guard.cleanup()
            self.assertFalse(self.dropped(connection))

    def test_only_marked_original_namespace_is_removed_and_absence_verified(self):
        metadata = {
            "version": 1,
            "state": "staging",
            "migration_id": None,
            "source_digest": None,
            "tasks": 0,
        }
        settings, connection = self.settings(
            None,
            {"oid": 4, "owner": "continuity_migrator", "marker": None},
            metadata,
            None,
        )
        guard = ownership.SchemaOwnership(settings)
        guard.prepare(Mock())
        connection.execute.side_effect = [
            SimpleNamespace(
                fetchone=lambda: {
                    "oid": 4,
                    "owner": "continuity_migrator",
                    "marker": guard.marker,
                }
            ),
            SimpleNamespace(fetchone=lambda: None),
            SimpleNamespace(fetchone=lambda: None),
        ]
        guard.cleanup()
        self.assertTrue(self.dropped(connection))

    def test_preexisting_volume_is_not_claimed_and_lost_ack_candidate_remains_tracked(
        self,
    ):
        name = "p1-g-" + RUN + "-fixtures"
        candidates = []
        command = Mock(return_value=name)
        with self.assertRaises(ValueError):
            ownership.volume_prepare(
                name,
                label_key="io.livekit-ecosystem.demo",
                run_id=RUN,
                candidates=candidates,
                command=command,
            )
        self.assertEqual(candidates, [])
        self.assertEqual(command.call_count, 1)

        def lost_ack(argv):
            if "create" in argv:
                raise RuntimeError("lost ack")
            return ""

        with self.assertRaises(RuntimeError):
            ownership.volume_prepare(
                name,
                label_key="io.livekit-ecosystem.demo",
                run_id=RUN,
                candidates=candidates,
                command=lost_ack,
            )
        self.assertEqual(candidates, [name])
        ownership.volume_verify(
            name,
            label_key="io.livekit-ecosystem.demo",
            run_id=RUN,
            command=Mock(return_value=RUN),
        )
        with self.assertRaises(ValueError):
            ownership.volume_verify(
                name,
                label_key="io.livekit-ecosystem.demo",
                run_id=RUN,
                command=Mock(return_value="foreign"),
            )


class _CohortConnection:
    def __init__(self, fixture):
        self.fixture = fixture
        self.rows = None

    def execute(self, _query, parameters=None):
        if parameters is None:
            self.rows = {"intents": 0, "consumptions": 0}
        else:
            self.rows = [
                {
                    "task_id": item["task_id"],
                    "key": item["key"],
                    "payload": media.canonical(self.fixture.request).decode(),
                    "effect_id": item["effect_id"],
                }
                for item in self.fixture.items
            ]
        return self

    def fetchone(self):
        return self.rows

    def fetchall(self):
        return self.rows

    def close(self):
        pass


class _CohortControllerFixture:
    """Synthetic public responses around the actual controller and reconciliation."""

    def __init__(self, directory, *, corrupt_receipt=False, malformed=None, expire=False):
        from uuid import UUID

        self.request = {
            "booking_reference": "DEMO-BK-001",
            "new_check_in": "2030-12-10",
            "confirmed": True,
        }
        self.result = {
            "booking_reference": "DEMO-BK-001",
            "new_check_in": "2030-12-10",
            "available": True,
        }

        self.directory = directory
        self.identity = lambda number: str(UUID(int=number))
        self.items = [self.item(100, self.identity(500))]
        self.foreground = self.items[0]["task_id"]
        self.paused = False
        self.quiescent = False
        self.health_quiescent = None
        self.health_ready = None
        self.worker_running = True
        self.signal_calls = []
        self.corrupt_receipt, self.malformed, self.expire = corrupt_receipt, malformed, expire
        self.clock = 0.0
        self.cancellations = []
        self.pending_reads = []
        self.cancel_reads = {}
        self.receipt_reads = 0
        self.replays = 0
        self.progressed = set()
        for marker in ("real-cohort-arm", "real-voice-ended", "real-before-human"):
            (directory / marker).write_text("1\n")
        (directory / "real-foreground-task").write_text(self.foreground + "\n")
        runtime = SimpleNamespace(
            schema="p1_owned_controller_fixture",
            connect=lambda **_kwargs: _CohortConnection(self),
        )
        self.cohort = media.PendingCohort(
            worker="owned-worker",
            label="owned-label",
            directory=directory,
            token="synthetic-controller-token",
            control=self.control,
            runtime=runtime,
        )
        self.cohort._request = self.response

    def item(self, number, key):
        return {
            "task_id": self.identity(number),
            "case_id": self.identity(number + 1000),
            "effect_id": self.identity(number + 2000),
            "key": key,
            "request": self.request,
        }

    def projection(self, item):
        task = item["task_id"]
        state = "succeeded" if task == self.foreground or not self.paused else "accepted"
        outcome = delivery = None
        if state == "succeeded" and task != self.foreground:
            self.progressed.add(task)
            if self.expire and len(self.progressed) == 8:
                self.clock = 44.0
        if task in self.cancellations:
            reads = self.cancel_reads.get(task, 0) + 1
            self.cancel_reads[task] = reads
            self.pending_reads.append((self.directory / "real-cohort-complete").exists())
            if reads >= 2:
                outcome = {"state": "cancelled"}
            if reads >= 3:
                delivery = {"state": "delivered"}
            if self.malformed is not None:
                outcome, delivery = self.malformed
            if self.expire:
                self.clock = 46.0
        return {
            "task_id": task,
            "case_id": item["case_id"],
            "request_key": item["key"],
            "request": self.request,
            "inquiry": {
                "effect_id": item["effect_id"],
                "request": self.request,
                "state": state,
                "result": self.result if state == "succeeded" else None,
            },
            "outcome": outcome,
            "delivery": delivery,
        }

    def response(self, path, body=None):
        if path == "/api/business/investigations":
            if set(body) != {*self.request, "idempotency_key"} or any(
                body[key] != value for key, value in self.request.items()
            ):
                raise AssertionError("Only the frozen investigation request is allowed")
            key = body["idempotency_key"]
            original = next((item for item in self.items if item["key"] == key), None)
            if original is not None:
                self.replays += 1
                return 200, {"created": False, "task_id": original["task_id"]}
            item = self.item(200 + len(self.items), key)
            self.items.append(item)
            return 200, {"created": True, "task_id": item["task_id"]}
        task = path.split("/")[4].split("?")[0]
        item = next(item for item in self.items if item["task_id"] == task)
        if path.endswith("/cancel"):
            if (self.directory / "real-cohort-complete").exists():
                raise AssertionError("Completion cannot precede explicit cancellation")
            self.cancellations.append(task)
            return 200, {
                "receipt": {
                    "command_id": body["command_id"],
                    "disposition": "cancelled_before_commit",
                }
            }
        return 200, self.projection(item)

    def control(self, arguments, **_kwargs):
        import hashlib

        if arguments[1] == "kill":
            signal_name = arguments[-2]
            self.signal_calls.append(signal_name)
            if signal_name == "SIGUSR1":
                self.quiescent = True
            elif signal_name == "SIGUSR2":
                self.quiescent = False
            else:
                raise AssertionError("Only bounded cooperative signals are allowed")
            return ""
        if arguments[1] == "pause":
            self.paused = True
            return ""
        if arguments[1] == "unpause":
            self.paused = False
            return ""
        if arguments[1] == "inspect":
            if arguments[-2] == "{{.State.Running}}":
                return "true" if self.worker_running else "false"
            return "true" if self.paused else "false"
        if arguments[1] == "ps":
            return "synthetic-owned-worker"
        if arguments[1] == "exec" and arguments[-1] == media.COHORT_QUIESCENT_SCRIPT:
            observed = self.quiescent if self.health_quiescent is None else self.health_quiescent()
            return "true" if observed else "false"
        if arguments[1] == "exec" and arguments[-1] == media.COHORT_READY_SCRIPT:
            observed = not self.quiescent if self.health_ready is None else self.health_ready()
            return "true" if observed else "false"
        if arguments[1] == "exec" and arguments[-1] == media.RECEIPT_SCRIPT:
            self.receipt_reads += 1
            rows = [
                {
                    "effect_id": item["effect_id"],
                    "request_sha256": hashlib.sha256(media.canonical(self.request)).hexdigest(),
                    "result_sha256": hashlib.sha256(media.canonical(self.result)).hexdigest(),
                }
                for item in self.items
            ]
            if self.corrupt_receipt:
                rows[0]["result_sha256"] = "0" * 64
            return json.dumps(rows)
        if arguments[1] == "exec":
            return json.dumps(
                {"inquiries": 9, "apply_calls": 0, "mutations": 0, "receiver_events": 8}
            )
        raise AssertionError("Unexpected fixture control operation")

    def run(self, *, snapshot=None):
        observed_snapshot = snapshot or (lambda **_kwargs: SimpleNamespace(active=0))
        with (
            patch("continuity_lab.postgres_store.PostgresExecutionStore"),
            patch(
                "continuity_lab.postgres_work.PostgresWorkQueue",
                return_value=SimpleNamespace(snapshot=observed_snapshot),
            ),
            patch.object(media.time, "monotonic", side_effect=lambda: self.clock),
        ):
            self.cohort._run()


class PendingCohortControllerTests(unittest.TestCase):
    def test_full_controller_waits_through_nullable_cancellation_and_delivery(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = _CohortControllerFixture(Path(folder))
            fixture.run()
            cohort = fixture.cohort
            self.assertIsNone(cohort.error)
            self.assertIsNone(cohort.cleanup_error)
            self.assertFalse(cohort.paused)
            self.assertEqual(len(cohort.accepted), 8)
            self.assertEqual(len(fixture.cancellations), 8)
            self.assertEqual(len(set(fixture.cancellations)), 8)
            self.assertEqual(fixture.receipt_reads, 1)
            self.assertEqual(fixture.replays, 8)
            self.assertEqual(len(fixture.pending_reads), 24)
            self.assertFalse(any(fixture.pending_reads))
            self.assertTrue((Path(folder) / "real-cohort-survived-end").is_file())
            self.assertTrue((Path(folder) / "real-cohort-complete").is_file())
            self.assertTrue((Path(folder) / "real-zero-apply-observed").is_file())
            self.assertEqual(cohort.result["inquiry_succeeded_after_end"], 8)
            self.assertEqual(cohort.result["explicitly_cancelled_after_measurement"], 8)
            self.assertEqual(cohort.result["cleanup_deliveries"], 8)
            self.assertEqual(
                cohort.result["independent_inquiry_receipts_matched_before_cleanup"], 9
            )
            self.assertTrue(cohort.result["pre_human_zero_apply_proven"])
            cohort.require_complete()

    def test_ui_prefixed_foreground_key_survives_the_complete_controller_unchanged(self):
        for legacy_uuid_guard in (True, False):
            with (
                self.subTest(legacy_uuid_guard=legacy_uuid_guard),
                tempfile.TemporaryDirectory() as folder,
            ):
                fixture = _CohortControllerFixture(Path(folder))
                original_key = "ui-" + fixture.identity(500)
                fixture.items[0]["key"] = original_key
                # Reproduce the prior replay-key UUID assumption inside the same controller.
                guard = (
                    patch("continuity_lab.case_models.identity", side_effect=media.uuid_value)
                    if legacy_uuid_guard
                    else nullcontext()
                )
                with guard:
                    fixture.run()
                self.assertEqual(fixture.items[0]["key"], original_key)
                self.assertEqual(len(fixture.cohort.accepted), 8)
                self.assertTrue((Path(folder) / "real-cohort-survived-end").is_file())
                self.assertFalse(fixture.cohort.paused)
                self.assertEqual(fixture.receipt_reads, 1)
                if legacy_uuid_guard:
                    self.assertIsInstance(fixture.cohort.error, ValueError)
                    self.assertFalse(fixture.cancellations)
                    self.assertFalse((Path(folder) / "real-cohort-complete").exists())
                    with self.assertRaises(RuntimeError):
                        fixture.cohort.require_complete()
                else:
                    self.assertIsNone(fixture.cohort.error)
                    self.assertEqual(len(set(fixture.cancellations)), 8)
                    self.assertEqual(len(fixture.pending_reads), 24)
                    self.assertFalse(any(fixture.pending_reads))
                    self.assertEqual(
                        fixture.cohort.result[
                            "independent_inquiry_receipts_matched_before_cleanup"
                        ],
                        9,
                    )
                    self.assertEqual(fixture.cohort.result["cleanup_deliveries"], 8)
                    self.assertTrue(fixture.cohort.result["pre_human_zero_apply_proven"])
                    fixture.cohort.require_complete()

    def test_valid_opaque_foreground_keys_keep_domain_semantics_and_exact_bytes(self):
        for key in ("path/request-identity", "café_旅行-request"):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as folder:
                fixture = _CohortControllerFixture(Path(folder))
                fixture.items[0]["key"] = key
                fixture.run()
                self.assertIsNone(fixture.cohort.error)
                self.assertEqual(fixture.items[0]["key"], key)
                self.assertEqual(
                    fixture.cohort.result["independent_inquiry_receipts_matched_before_cleanup"], 9
                )
                fixture.cohort.require_complete()

    def test_invalid_opaque_foreground_keys_fail_safely_before_cancellation(self):
        for key in (
            None,
            True,
            "",
            " leading",
            "trailing ",
            "PRIVATE\x00",
            "PRIVATE\x7f",
            "PRIVATE\ud800",
            "x" * 129,
        ):
            with self.subTest(kind=type(key).__name__), tempfile.TemporaryDirectory() as folder:
                fixture = _CohortControllerFixture(Path(folder))
                fixture.items[0]["key"] = key
                fixture.run()
                self.assertIsInstance(fixture.cohort.error, ValueError)
                self.assertFalse(fixture.cancellations)
                self.assertFalse((Path(folder) / "real-cohort-complete").exists())
                self.assertFalse(fixture.cohort.paused)
                self.assertNotIn("PRIVATE", json.dumps(fixture.cohort.observation()))
                with self.assertRaises(RuntimeError):
                    fixture.cohort.require_complete()

    def test_opaque_replay_keys_do_not_make_task_or_effect_identities_opaque(self):
        for field in ("task_id", "effect_id"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as folder:
                fixture = _CohortControllerFixture(Path(folder))
                fixture.items[0]["key"] = "ui-" + fixture.identity(500)
                fixture.items[0][field] = "ui-" + fixture.items[0][field]
                if field == "task_id":
                    fixture.foreground = fixture.items[0][field]
                    (Path(folder) / "real-foreground-task").write_text(fixture.foreground + "\n")
                fixture.run()
                self.assertIsInstance(fixture.cohort.error, ValueError)
                self.assertFalse(fixture.cancellations)
                self.assertFalse((Path(folder) / "real-cohort-complete").exists())
                with self.assertRaises(RuntimeError):
                    fixture.cohort.require_complete()

    def test_bad_independent_receipt_cannot_reach_cancellation_or_complete(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = _CohortControllerFixture(Path(folder), corrupt_receipt=True)
            fixture.run()
            self.assertIsInstance(fixture.cohort.error, ValueError)
            self.assertEqual(fixture.cancellations, [])
            self.assertFalse((Path(folder) / "real-cohort-complete").exists())
            self.assertFalse(fixture.cohort.paused)
            with self.assertRaises(RuntimeError):
                fixture.cohort.require_complete()

    def test_nonnullable_nonobjects_are_not_reinterpreted_as_pending(self):
        for value in (("PRIVATE", None), ({"state": "cancelled"}, ["PRIVATE"]), (False, {})):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as folder:
                fixture = _CohortControllerFixture(Path(folder), malformed=value)
                fixture.run()
                self.assertIsInstance(fixture.cohort.error, ValueError)
                self.assertNotIn("PRIVATE", str(fixture.cohort.error))
                self.assertFalse((Path(folder) / "real-cohort-complete").exists())
                self.assertFalse(fixture.cohort.paused)

    def test_cancellation_delivery_keeps_original_progress_deadline(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = _CohortControllerFixture(Path(folder), expire=True)
            fixture.run()
            self.assertIsInstance(fixture.cohort.error, RuntimeError)
            self.assertEqual(fixture.clock, 46.0)
            self.assertEqual(len(fixture.cancellations), 8)
            self.assertEqual(len(fixture.pending_reads), 1)
            self.assertFalse((Path(folder) / "real-cohort-complete").exists())
            self.assertFalse(fixture.cohort.paused)
            with self.assertRaises(RuntimeError):
                fixture.cohort.require_complete()


class PendingCohortQuiescenceTests(unittest.TestCase):
    def test_health_checkpoint_waits_for_post_sql_even_when_active_lease_is_zero(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = _CohortControllerFixture(Path(folder))
            post_sql_started, allow_checkpoint = threading.Event(), threading.Event()
            snapshots = []

            def healthy():
                post_sql_started.set()
                return allow_checkpoint.is_set()

            def snapshot(**_kwargs):
                snapshots.append(0)
                self.assertTrue(allow_checkpoint.is_set())
                return SimpleNamespace(active=0)

            fixture.health_quiescent = healthy
            original = fixture.cohort.control
            fixture.cohort.control = Mock(side_effect=original)
            thread = threading.Thread(target=lambda: fixture.run(snapshot=snapshot))
            fixture.cohort.thread = thread
            thread.start()
            try:
                self.assertTrue(post_sql_started.wait(timeout=1))
                self.assertFalse(fixture.paused)
                self.assertEqual(snapshots, [])
                self.assertFalse((Path(folder) / "real-cohort-pending").exists())
                self.assertEqual(fixture.signal_calls, ["SIGUSR1"])
                allow_checkpoint.set()
                thread.join(timeout=3)
                self.assertFalse(thread.is_alive())
                self.assertEqual(snapshots, [0])
                self.assertEqual(fixture.signal_calls, ["SIGUSR1", "SIGUSR2"])
                fixture.cohort.require_complete()
                self.assertFalse(fixture.cohort.quiesce_requested)
                self.assertEqual(fixture.cohort.observation()["quiescence"]["phase"], "resumed")
            finally:
                fixture.cohort.close()

    def test_idle_snapshot_is_still_required_after_cooperative_checkpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = _CohortControllerFixture(Path(folder))
            seen = []

            def snapshot(**_kwargs):
                seen.append(1 if not seen else 0)
                return SimpleNamespace(active=seen[-1])

            original = fixture.cohort.control

            def control(arguments, **kwargs):
                if arguments[1] == "pause":
                    self.assertEqual(seen, [1, 0])
                    self.assertTrue(fixture.cohort._quiescence_observed)
                return original(arguments, **kwargs)

            fixture.cohort.control = control
            fixture.run(snapshot=snapshot)
            fixture.cohort.require_complete()
            self.assertEqual(fixture.cohort.observation()["quiescence"]["idle_snapshots"], 2)

    def test_arm_wait_and_health_ack_share_the_original100_second_setup_deadline(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = _CohortControllerFixture(Path(folder))
            marker = Path(folder) / "real-cohort-arm"
            marker.unlink()

            def wait(_seconds):
                fixture.clock = 99.0
                marker.write_text("1\n")
                return False

            def health():
                fixture.clock = 100.0
                return True

            fixture.health_quiescent = health
            with patch.object(fixture.cohort.stop, "wait", side_effect=wait):
                fixture.run()
            self.assertIsInstance(fixture.cohort.error, RuntimeError)
            self.assertFalse(fixture.paused)
            self.assertFalse(fixture.quiescent)
            self.assertFalse(fixture.cohort._quiescence_observed)
            self.assertFalse((Path(folder) / "real-cohort-pending").exists())
            self.assertEqual(fixture.signal_calls, ["SIGUSR1", "SIGUSR2"])
            with self.assertRaises(RuntimeError):
                fixture.cohort.require_complete()

    def test_idle_snapshot_after_deadline_does_not_qualify_os_pause(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = _CohortControllerFixture(Path(folder))

            def snapshot(**_kwargs):
                fixture.clock = 100.0
                return SimpleNamespace(active=0)

            fixture.run(snapshot=snapshot)
            self.assertIsInstance(fixture.cohort.error, RuntimeError)
            self.assertFalse(fixture.paused)
            self.assertFalse(fixture.cohort.paused)
            self.assertFalse(fixture.cohort.quiesce_requested)
            self.assertFalse((Path(folder) / "real-cohort-pending").exists())

    def test_stop_waiting_for_checkpoint_resumes_without_pausing_or_accepting(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = _CohortControllerFixture(Path(folder))
            health_seen = threading.Event()

            def health():
                health_seen.set()
                return False

            fixture.health_quiescent = health
            thread = threading.Thread(target=fixture.run)
            fixture.cohort.thread = thread
            thread.start()
            self.assertTrue(health_seen.wait(timeout=1))
            fixture.cohort.close()
            self.assertFalse(thread.is_alive())
            self.assertIsNone(fixture.cohort.error)
            self.assertFalse(fixture.paused)
            self.assertFalse(fixture.quiescent)
            self.assertFalse(fixture.cohort.quiesce_requested)
            self.assertEqual(fixture.signal_calls, ["SIGUSR1", "SIGUSR2"])
            self.assertFalse(fixture.cohort.accepted)
            with self.assertRaises(RuntimeError):
                fixture.cohort.require_complete()

    def test_stop_during_ownership_inspection_never_requests_quiescence(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = _CohortControllerFixture(Path(folder))
            original = fixture.cohort.control
            operations = []

            def control(arguments, **kwargs):
                operations.append(arguments[1])
                result = original(arguments, **kwargs)
                if arguments[1] == "ps":
                    fixture.cohort.stop.set()
                return result

            fixture.cohort.control = control
            fixture.run()
            self.assertEqual(operations, ["ps"])
            self.assertIsNone(fixture.cohort.error)
            self.assertFalse(fixture.cohort.quiesce_requested)
            self.assertFalse(fixture.cohort.accepted)

    def test_ownership_inspection_cannot_extend_original_setup_deadline(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = _CohortControllerFixture(Path(folder))
            original = fixture.cohort.control
            operations = []

            def control(arguments, **kwargs):
                operations.append(arguments[1])
                result = original(arguments, **kwargs)
                if arguments[1] == "ps":
                    fixture.clock = 100.0
                return result

            fixture.cohort.control = control
            fixture.run()
            self.assertEqual(operations, ["ps"])
            self.assertIsInstance(fixture.cohort.error, RuntimeError)
            self.assertFalse(fixture.cohort.quiesce_requested)
            self.assertFalse(fixture.cohort.accepted)

    def test_stopped_or_unverified_running_worker_never_receives_signal(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = _CohortControllerFixture(Path(folder))
            fixture.worker_running = False
            fixture.run()
            self.assertIsInstance(fixture.cohort.error, ValueError)
            self.assertFalse(fixture.signal_calls)
            self.assertFalse(fixture.cohort.quiesce_requested)

    def test_lost_quiesce_signal_ack_is_owned_before_request_and_resumed_in_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = _CohortControllerFixture(Path(folder))
            original = fixture.cohort.control

            def control(arguments, **kwargs):
                if arguments[1:4] == ["kill", "--signal", "SIGUSR1"]:
                    self.assertTrue(fixture.cohort.quiesce_requested)
                    original(arguments, **kwargs)
                    raise TimeoutError("PRIVATE")
                return original(arguments, **kwargs)

            fixture.cohort.control = control
            fixture.run()
            self.assertIsInstance(fixture.cohort.error, TimeoutError)
            self.assertIsNone(fixture.cohort.cleanup_error)
            self.assertFalse(fixture.quiescent)
            self.assertFalse(fixture.cohort.quiesce_requested)
            self.assertEqual(fixture.signal_calls, ["SIGUSR1", "SIGUSR2"])
            self.assertNotIn("PRIVATE", json.dumps(fixture.cohort.observation()))
            with self.assertRaises(RuntimeError):
                fixture.cohort.require_complete()

    def test_lost_pause_ack_still_unpauses_and_resumes_the_exact_owned_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = _CohortControllerFixture(Path(folder))
            original = fixture.cohort.control

            def control(arguments, **kwargs):
                result = original(arguments, **kwargs)
                if arguments[1] == "pause":
                    raise TimeoutError("PRIVATE")
                return result

            fixture.cohort.control = control
            fixture.run()
            self.assertIsInstance(fixture.cohort.error, TimeoutError)
            self.assertIsNone(fixture.cohort.cleanup_error)
            self.assertFalse(fixture.paused)
            self.assertFalse(fixture.quiescent)
            self.assertFalse(fixture.cohort.paused)
            self.assertFalse(fixture.cohort.quiesce_requested)

    def test_lost_unpause_and_resume_acks_require_observed_unpaused_and_ready_state(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = _CohortControllerFixture(Path(folder))
            original = fixture.cohort.control

            def control(arguments, **kwargs):
                result = original(arguments, **kwargs)
                if arguments[1] == "unpause" or arguments[1:4] == ["kill", "--signal", "SIGUSR2"]:
                    raise TimeoutError("PRIVATE")
                return result

            fixture.cohort.control = control
            fixture.run()
            fixture.cohort.require_complete()
            self.assertFalse(fixture.paused)
            self.assertFalse(fixture.quiescent)
            self.assertFalse(fixture.cohort.quiesce_requested)
            self.assertEqual(fixture.cohort.observation()["quiescence"]["resume_checks"], 1)

    def test_uncertain_resume_health_cannot_pass_or_reset_its12_second_deadline(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = _CohortControllerFixture(Path(folder))

            def health():
                fixture.clock += 12.0
                return True

            fixture.health_ready = health
            fixture.run()
            self.assertIsInstance(fixture.cohort.error, RuntimeError)
            self.assertIsInstance(fixture.cohort.cleanup_error, RuntimeError)
            self.assertTrue(fixture.cohort.quiesce_requested)
            self.assertEqual(fixture.signal_calls, ["SIGUSR1", "SIGUSR2"])
            self.assertEqual(fixture.cohort.observation()["status"], "cleanup_incomplete")
            with self.assertRaises(RuntimeError):
                fixture.cohort.require_complete()

    def test_ready_on_resume_may_already_have_an_active_child(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = _CohortControllerFixture(Path(folder))
            fixture.health_ready = lambda: True
            seen = []
            original = fixture.cohort.control

            def control(arguments, **kwargs):
                if arguments[-1] == media.COHORT_READY_SCRIPT:
                    seen.append("ready permits active child; no idle snapshot on resume")
                return original(arguments, **kwargs)

            fixture.cohort.control = control
            fixture.run()
            fixture.cohort.require_complete()
            self.assertEqual(len(seen), 1)
            self.assertEqual(fixture.cohort.observation()["quiescence"]["idle_snapshots"], 1)

    def test_resume_ack_consumes_the_original45_second_recovery_window(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = _CohortControllerFixture(Path(folder))
            fixture.health_ready = lambda: setattr(fixture, "clock", 5.0) is None
            fixture.run()
            fixture.cohort.require_complete()
            self.assertEqual(fixture.cohort._recovery_started, 0)
            self.assertEqual(fixture.cohort._recovery_marks["inquiry_completion_seconds"], 5)
            self.assertEqual(fixture.cohort._recovery_observation()["deadline_seconds"], 45)

    def test_expired_recovery_after_resume_never_observes_inquiries_as_success(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = _CohortControllerFixture(Path(folder))
            original = fixture.cohort._resume

            def resume():
                original()
                fixture.clock = 45.0

            fixture.cohort._resume = resume
            fixture.run()
            self.assertIsInstance(fixture.cohort.error, RuntimeError)
            self.assertEqual(fixture.cohort._recovery_started, 0)
            self.assertEqual(fixture.cohort._recovery_counts["inquiries_succeeded"], 0)
            self.assertFalse((Path(folder) / "real-cohort-complete").exists())

    def test_late_successful_inquiry_read_cannot_cross_recovery_deadline(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = _CohortControllerFixture(Path(folder))
            original = fixture.cohort._projection

            def projection(item):
                result = original(item)
                if fixture.cohort._recovery_started is not None:
                    fixture.clock = 45.0
                return result

            fixture.cohort._projection = projection
            fixture.run()
            self.assertIsInstance(fixture.cohort.error, RuntimeError)
            self.assertEqual(fixture.cohort._recovery_counts["inquiries_succeeded"], 0)
            self.assertFalse((Path(folder) / "real-cohort-complete").exists())

    def test_late_successful_delivery_read_does_not_publish_cohort_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = _CohortControllerFixture(Path(folder))
            original = fixture.cohort._projection

            def projection(item):
                result = original(item)
                if (
                    fixture.cohort._recovery_phase == "delivery_recovery"
                    and result.get("delivery") is not None
                ):
                    fixture.clock = 45.0
                return result

            fixture.cohort._projection = projection
            fixture.run()
            self.assertIsInstance(fixture.cohort.error, RuntimeError)
            self.assertEqual(fixture.cohort._recovery_counts["inquiries_succeeded"], 8)
            self.assertEqual(fixture.cohort._recovery_counts["deliveries_observed"], 0)
            self.assertFalse((Path(folder) / "real-cohort-complete").exists())

    def test_stop_during_true_checkpoint_reply_resumes_before_any_pause(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = _CohortControllerFixture(Path(folder))

            def health():
                fixture.cohort.stop.set()
                return True

            fixture.health_quiescent = health
            fixture.run()
            self.assertIsNone(fixture.cohort.error)
            self.assertIsNone(fixture.cohort.cleanup_error)
            self.assertFalse(fixture.cohort._quiescence_observed)
            self.assertFalse(fixture.cohort.quiesce_requested)
            self.assertFalse(fixture.paused)
            self.assertFalse(fixture.cohort.accepted)
            self.assertEqual(fixture.signal_calls, ["SIGUSR1", "SIGUSR2"])

    def test_health_scripts_delegate_to_exact_installed_public_api_without_printing_paths(self):
        from contextlib import redirect_stdout
        from io import StringIO

        state = object()
        settings = SimpleNamespace(from_env=Mock(return_value=SimpleNamespace(state_file=state)))
        health = Mock()
        health.return_value.is_quiescent.return_value = True
        health.return_value.ready.return_value = True
        stub = SimpleNamespace(WorkerSettings=settings, WorkerHealth=health)
        for script, name in (
            (media.COHORT_QUIESCENT_SCRIPT, "is_quiescent"),
            (media.COHORT_READY_SCRIPT, "ready"),
        ):
            output = StringIO()
            with (
                patch.dict(sys.modules, {"continuity_lab.worker_cli": stub}),
                redirect_stdout(output),
            ):
                exec(compile(script, "<fixed-worker-health-probe>", "exec"), {})  # noqa: S102 - fixed source-owned probe under a stubbed API
            self.assertEqual(output.getvalue(), "true\n")
            health.assert_called_with(state)
            getattr(health.return_value, name).assert_called_once_with(maximum_age_seconds=10)

    def test_quiescence_observation_counts_are_finite_and_unsafe_health_is_nonpassing(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = _CohortControllerFixture(Path(folder))
            original = fixture.cohort.control

            def control(arguments, **kwargs):
                if arguments[-1] == media.COHORT_QUIESCENT_SCRIPT:
                    return "PRIVATE"
                return original(arguments, **kwargs)

            fixture.cohort.control = control
            fixture.run()
            self.assertIsInstance(fixture.cohort.error, ValueError)
            observed = fixture.cohort.observation()
            self.assertNotIn("PRIVATE", json.dumps(observed))
            self.assertFalse(fixture.cohort.quiesce_requested)
            for key, value in observed["quiescence"].items():
                if key.endswith(("checks", "requests", "snapshots")):
                    self.assertIs(type(value), int)
                    self.assertLessEqual(value, media.MAX_COHORT_HEALTH_OBSERVATIONS)


class PendingCohortProgressTests(unittest.TestCase):
    def test_completed_controller_reports_only_bounded_observed_progress(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = _CohortControllerFixture(Path(folder))
            fixture.run()
            value = fixture.cohort.observation()["recovery"]
            self.assertEqual(value["phase"], "complete")
            self.assertEqual(value["deadline_seconds"], 45)
            for field in ("inquiries_succeeded", "cancellations_issued", "deliveries_observed"):
                self.assertEqual(value[field], 8)
            self.assertEqual(value["last_projection_tasks"], 9)
            self.assertEqual(value["last_projection_states"]["inquiry"]["succeeded"], 9)
            self.assertEqual(value["last_projection_states"]["delivery"]["delivered"], 8)
            self.assertEqual(value["last_projection_states"]["delivery"]["none"], 1)
            self.assertTrue(all(value[field] == 0 for field in fixture.cohort._recovery_marks))
            self.assertNotIn(fixture.foreground, json.dumps(value))
            self.assertNotIn("DEMO-BK", json.dumps(value))
            fixture.cohort.require_complete()

    def test_timeout_preserves_original_deadline_phase_and_partial_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = _CohortControllerFixture(Path(folder), expire=True)
            fixture.run()
            with patch.object(media.time, "monotonic", return_value=46.0):
                value = fixture.cohort.observation()["recovery"]
            self.assertEqual(value["phase"], "delivery_recovery")
            self.assertEqual(value["deadline_seconds"], 45)
            self.assertEqual(value["elapsed_seconds"], 46)
            self.assertEqual(value["inquiry_completion_seconds"], 44)
            self.assertEqual(value["receipt_reconciliation_seconds"], 44)
            self.assertEqual(value["cancellation_issuance_seconds"], 44)
            self.assertIsNone(value["delivery_completion_seconds"])
            self.assertEqual(value["inquiries_succeeded"], 8)
            self.assertEqual(value["cancellations_issued"], 8)
            self.assertEqual(value["deliveries_observed"], 0)
            self.assertEqual(value["last_projection_tasks"], 9)
            self.assertFalse((Path(folder) / "real-cohort-complete").exists())
            with self.assertRaises(RuntimeError):
                fixture.cohort.require_complete()

    def test_receipt_failure_retains_inquiry_progress_without_implying_cancellation(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = _CohortControllerFixture(Path(folder), corrupt_receipt=True)
            fixture.run()
            value = fixture.cohort.observation()["recovery"]
            self.assertEqual(value["phase"], "receipt_reconciliation")
            self.assertEqual(value["inquiries_succeeded"], 8)
            self.assertEqual(value["cancellations_issued"], 0)
            self.assertEqual(value["deliveries_observed"], 0)
            self.assertIsNone(value["receipt_reconciliation_seconds"])
            self.assertIsNone(value["cancellation_issuance_seconds"])
            self.assertIsNone(value["delivery_completion_seconds"])
            self.assertFalse(fixture.cancellations)
            self.assertFalse((Path(folder) / "real-cohort-complete").exists())

    def test_projection_counts_drop_unknown_text_ids_and_nonfinite_clock_without_requests(self):
        with tempfile.TemporaryDirectory() as folder:
            cohort = RealEvidenceTests().cohort(Path(folder))
            for index in range(10):
                task = "private-task-" + str(index)
                cohort._record_projection(
                    task,
                    {
                        "task_id": task,
                        "inquiry": {"state": "PRIVATE"},
                        "outcome": {"state": ["PRIVATE"]},
                        "delivery": None,
                    },
                )
            cohort._recovery_started = 0
            with patch.object(media.time, "monotonic", return_value=float("nan")):
                value = cohort.observation()["recovery"]
            self.assertEqual(value["last_projection_tasks"], 9)
            self.assertEqual(value["last_projection_states"]["inquiry"]["unknown"], 9)
            self.assertEqual(value["last_projection_states"]["outcome"]["unknown"], 9)
            self.assertIsNone(value["elapsed_seconds"])
            retained = json.dumps(value, allow_nan=False)
            self.assertNotIn("PRIVATE", retained)
            self.assertNotIn("private-task", retained)
            cohort.control.assert_not_called()


class PendingCohortFailureTests(unittest.TestCase):
    @staticmethod
    def cohort(path):
        return media.PendingCohort(
            worker="owned",
            label="owned",
            directory=path,
            token="synthetic",
            control=Mock(),
            runtime=Mock(),
        )

    def test_own_controller_error_has_fixed_category_and_line_without_success_marker(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = _CohortControllerFixture(Path(folder), corrupt_receipt=True)
            fixture.run()
            value = fixture.cohort.observation()
            failure = value["operation_failure"]
            self.assertEqual(value["status"], "failed")
            self.assertEqual(set(failure), {"schema_version", "error_category", "source_line"})
            self.assertEqual(failure["schema_version"], 1)
            self.assertEqual(failure["error_category"], "ValueError")
            self.assertGreater(failure["source_line"], 0)
            self.assertLessEqual(failure["source_line"], 100000)
            self.assertIsNone(value["cleanup_failure"])
            self.assertFalse((Path(folder) / "real-cohort-complete").exists())
            self.assertNotIn("/", json.dumps(failure))

    def test_hostile_unknown_exception_message_properties_and_chain_are_untouched(self):
        class PrivateError(RuntimeError):
            def __str__(self):
                raise AssertionError("Exception text must not be accessed")

            def __repr__(self):
                raise AssertionError("Exception repr must not be accessed")

            def __getattribute__(self, _name):
                raise AssertionError("Dependency properties must not be accessed")

        with tempfile.TemporaryDirectory() as folder:
            cohort = self.cohort(Path(folder))
            error = PrivateError("PRIVATE-BODY")
            error.__cause__ = ValueError("PRIVATE-CHAIN")
            cohort._wait = Mock(side_effect=error)
            cohort._run()
            self.assertIs(cohort.error, error)
            value = cohort.observation()
            self.assertEqual(value["operation_failure"]["error_category"], "other")
            self.assertGreater(value["operation_failure"]["source_line"], 0)
            self.assertNotIn("PRIVATE", json.dumps(value))
            self.assertEqual(value["status"], "failed")
            self.assertFalse((Path(folder) / "real-cohort-complete").exists())
            with self.assertRaises(RuntimeError):
                cohort.require_complete()

    def test_http_failure_retains_only_exact_type_and_bounded_numeric_status(self):
        import io
        import urllib.error

        class PrivateBody(io.BytesIO):
            def read(self, *_args, **_kwargs):
                raise AssertionError("The private HTTP error body must remain unread")

        class PrivateHTTPError(urllib.error.HTTPError):
            pass

        for kind, code, expected in (
            (urllib.error.HTTPError, 503, 503),
            (urllib.error.HTTPError, 100, 100),
            (urllib.error.HTTPError, 599, 599),
            (urllib.error.HTTPError, 99, None),
            (urllib.error.HTTPError, 600, None),
            (urllib.error.HTTPError, True, None),
            (urllib.error.HTTPError, "PRIVATE-STATUS", None),
            (PrivateHTTPError, 503, None),
        ):
            with self.subTest(kind=kind, code=code), tempfile.TemporaryDirectory() as folder:
                body = PrivateBody(b"PRIVATE-BODY")
                error = kind(
                    "https://PRIVATE.example", code, "PRIVATE-MESSAGE", {"PRIVATE": "HEADER"}, body
                )
                cohort = self.cohort(Path(folder))
                cohort._wait = Mock(side_effect=error)
                try:
                    cohort._run()
                    failure = cohort.observation()["operation_failure"]
                    self.assertEqual(
                        failure["error_category"],
                        "HTTPError" if kind is urllib.error.HTTPError else "other",
                    )
                    self.assertEqual(failure.get("http_status"), expected)
                    self.assertEqual("http_status" in failure, expected is not None)
                    self.assertNotIn("PRIVATE", json.dumps(failure))
                    self.assertEqual(body.tell(), 0)
                finally:
                    error.close()
                    body.close()

    def test_modified_http_error_dictionary_cannot_invoke_dependency_lookup(self):
        import io
        import urllib.error

        class PrivateAttributes(dict):
            def get(self, *_args, **_kwargs):
                raise AssertionError("Dependency dictionary hooks must not run")

        class PrivateBody(io.BytesIO):
            def read(self, *_args, **_kwargs):
                raise AssertionError("The private HTTP error body must remain unread")

        with tempfile.TemporaryDirectory() as folder:
            body = PrivateBody(b"PRIVATE-BODY")
            error = urllib.error.HTTPError(
                "https://PRIVATE.example", 503, "PRIVATE-MESSAGE", {}, body
            )
            error.__dict__ = PrivateAttributes(error.__dict__)
            cohort = self.cohort(Path(folder))
            cohort._wait = Mock(side_effect=error)
            try:
                cohort._run()
                value = cohort.observation()
                self.assertIs(cohort.error, error)
                self.assertEqual(value["status"], "failed")
                self.assertEqual(value["operation_failure"]["error_category"], "HTTPError")
                self.assertNotIn("http_status", value["operation_failure"])
                self.assertNotIn("PRIVATE", json.dumps(value))
                self.assertEqual(body.tell(), 0)
                self.assertFalse((Path(folder) / "real-cohort-complete").exists())
            finally:
                error.close()
                body.close()

    def test_source_uses_code_identity_and_a_maximum_of_64_traceback_frames(self):
        from types import TracebackType

        with tempfile.TemporaryDirectory() as folder:
            cohort = self.cohort(Path(folder))
            cohort._wait = Mock(side_effect=ValueError("PRIVATE"))
            cohort._run()
            error = cohort.error
            own_trace = error.__traceback__
            self.assertIs(own_trace.tb_frame.f_code, media.PendingCohort._run.__code__)

            def foreign():
                raise ValueError("PRIVATE")

            # An unrelated frame can claim the same path; it still has another code identity.
            foreign.__code__ = foreign.__code__.replace(co_filename=media.__file__)
            try:
                foreign()
            except ValueError as foreign_error:
                foreign_trace = foreign_error.__traceback__.tb_next
            spoof = TracebackType(
                None, foreign_trace.tb_frame, foreign_trace.tb_lasti, foreign_trace.tb_lineno
            )
            error.__traceback__ = spoof
            self.assertEqual(cohort.observation()["operation_failure"]["source_line"], 0)
            for count, expected_found in ((63, True), (64, False)):
                trace = own_trace
                for _index in range(count):
                    trace = TracebackType(trace, spoof.tb_frame, spoof.tb_lasti, spoof.tb_lineno)
                error.__traceback__ = trace
                line = cohort.observation()["operation_failure"]["source_line"]
                self.assertEqual(line > 0, expected_found)
            self.assertNotIn("PRIVATE", json.dumps(cohort.observation()))

    def test_no_error_has_no_projection_and_cleanup_failure_stays_separate(self):
        with tempfile.TemporaryDirectory() as folder:
            cohort = self.cohort(Path(folder))
            self.assertIsNone(cohort.observation()["operation_failure"])
            self.assertIsNone(cohort.observation()["cleanup_failure"])
            cohort.error = ValueError("PRIVATE-ORIGINAL")
            cohort.cleanup_error = RuntimeError("PRIVATE-CLEANUP")
            value = cohort.observation()
            self.assertEqual(value["status"], "cleanup_incomplete")
            self.assertEqual(value["operation_failure"]["error_category"], "ValueError")
            self.assertEqual(value["cleanup_failure"]["error_category"], "RuntimeError")
            self.assertEqual(value["operation_failure"]["source_line"], 0)
            self.assertNotIn("PRIVATE", json.dumps(value))
            with self.assertRaises(RuntimeError):
                cohort.require_complete()


if __name__ == "__main__":
    unittest.main()
