"""Evidence gates refuse missing assertions, skipped browser cases and unsafe reports."""

import copy
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

SPEC = importlib.util.spec_from_file_location(
    "phase_g_demo_verifier",
    Path(__file__).resolve().parents[1] / "local-setup/scripts/phase_g_demo.py",
)
demo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(demo)


class PhaseGDemoEvidenceTests(unittest.TestCase):
    def test_explicit_ca_snapshot_is_exact_exclusive_readonly_and_metadata_contains_no_content(
        self,
    ):
        raw = b"synthetic-public-cert-only-bytes"
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            module = SimpleNamespace(read_ca_bundle=lambda _path: raw)
            with (
                patch.object(demo.importlib.util, "module_from_spec", return_value=module),
                patch.object(
                    demo.importlib.util,
                    "spec_from_file_location",
                    return_value=SimpleNamespace(
                        name="synthetic_ca_module",
                        loader=SimpleNamespace(exec_module=lambda _m: None),
                    ),
                ),
            ):
                mount, evidence = demo.provider_ca_mount(folder, folder / "approved.pem", folder)
                with self.assertRaises(FileExistsError):
                    demo.provider_ca_mount(folder, folder / "approved.pem", folder)
            self.assertEqual(raw, (folder / "provider-ca.pem").read_bytes())
            self.assertEqual(0o644, (folder / "provider-ca.pem").stat().st_mode & 0o777)
            self.assertEqual(
                "type=bind,src="
                + str(folder / "provider-ca.pem")
                + ",dst=/etc/ssl/certs/ca-certificates.crt,readonly",
                mount,
            )
            self.assertEqual(
                {
                    "schema_version": 1,
                    "bundle_sha256": hashlib.sha256(raw).hexdigest(),
                    "bundle_bytes": len(raw),
                },
                evidence,
            )
            self.assertNotIn("synthetic-public", json.dumps(evidence))

    def setUp(self):
        self.observations = {
            **dict.fromkeys(demo.BROWSER_FLAGS, True),
            "schema_version": 1,
            "browser_version": "143.0.7499.40",
            "playwright_version": "1.65.0",
            "unexpected_network_requests": 0,
            "supplier_outcome": "succeeded",
        }
        self.report = {"stats": {"expected": 6, "unexpected": 0, "skipped": 0, "flaky": 0}}
        self.sdk = {
            "schema_version": 1,
            "mode": "scripted",
            "sdk_report_observed": True,
            "values": dict.fromkeys(demo.OBSERVATION_FIELDS, 1),
        }

    @staticmethod
    def trace_fixture(service="conversation-agent", task="11111111-1111-4111-8111-111111111111"):
        attributes = [
            {"key": key, "value": {"stringValue": value}}
            for key, value in (
                ("service.name", service),
                ("service.version", "0.1.0"),
                ("continuity.mode", "scripted"),
            )
        ]
        span = {
            "traceId": "1" * 32,
            "spanId": "2" * 16,
            "name": "function_tool",
            "kind": 1,
            "flags": 1,
            "startTimeUnixNano": "1800000000000000000",
            "endTimeUnixNano": "1800000000000000001",
            "attributes": [
                {"key": "continuity.task_id", "value": {"stringValue": task}},
                {"key": "gen_ai.usage.input_tokens", "value": {"intValue": "1"}},
                {"key": "continuity.duration_seconds", "value": {"doubleValue": 0.1}},
            ],
            "status": {"code": 2},
        }
        return {
            "result": {
                "resourceSpans": [
                    {
                        "resource": {"attributes": attributes},
                        "scopeSpans": [
                            {
                                "scope": {"name": "continuity.safe", "version": "1"},
                                "spans": [span],
                            }
                        ],
                    }
                ]
            }
        }

    @staticmethod
    def api_record():
        return {
            "severity": "error",
            "timestamp": "2026-11-10T07:00:00+00:00",
            "event": "http_request_error",
            "operation": "business_session",
            "method": "POST",
            "status": 503,
            "duration_seconds": 4.012345,
            "request_id": "a" * 32,
            "code": "dispatch_unavailable",
        }

    def test_api_failure_log_summary_retains_fixed_counts_and_durations_without_identifiers(self):
        record = self.api_record()
        complete = {key: value for key, value in record.items() if key != "code"}
        complete.update(
            severity="info",
            event="http_request_completed",
            operation="business_get",
            method="GET",
            status=200,
            duration_seconds=0.125,
        )
        value = demo.safe_api_log_summary(
            "\n".join(map(json.dumps, (record, record, complete))) + "\nPRIVATE-RAW-LOG"
        )
        self.assertEqual(value["accepted_lines"], 3)
        self.assertEqual(value["discarded_lines"], 1)
        failed = next(row for row in value["records"] if row["status"] == 503)
        self.assertEqual(
            failed,
            {
                "operation": "business_session",
                "method": "POST",
                "status": 503,
                "code": "dispatch_unavailable",
                "severity": "error",
                "count": 2,
                "duration_seconds_total": 8.02469,
                "duration_seconds_max": 4.012345,
            },
        )
        safe = json.dumps(value)
        for private in (
            "PRIVATE",
            record["request_id"],
            record["timestamp"],
            "request_id",
            "timestamp",
            "detail",
        ):
            self.assertNotIn(private, safe)
        from services.control_api.telemetry import ERRORS, METHODS, OPERATIONS

        self.assertEqual(demo.API_ERROR_CODES, frozenset(ERRORS))
        self.assertEqual(demo.API_METHODS, METHODS | {"OTHER"})
        self.assertEqual(
            demo.API_OPERATIONS,
            set(OPERATIONS.values())
            | {
                "business_submit",
                "business_session",
                "business_get",
                "business_quote",
                "business_signal",
                "business_cancel",
                "unknown",
            },
        )

    def test_api_failure_log_summary_rejects_raw_unknown_extra_duplicate_and_nonfinite_fields(self):
        invalid = []
        record = self.api_record()
        for field, value in (
            ("code", "PRIVATE-ERROR-TEXT"),
            ("code", {}),
            ("operation", "/PRIVATE/room"),
            ("method", "PRIVATE"),
            ("status", True),
            ("status", 600),
            ("status", 503.0),
            ("duration_seconds", True),
            ("duration_seconds", float("nan")),
            ("duration_seconds", float("inf")),
            ("duration_seconds", -1),
            ("duration_seconds", 3601),
            ("request_id", "PRIVATE-ID"),
            ("timestamp", "PRIVATE-TIME"),
            ("severity", "info"),
            ("event", "http_request_completed"),
        ):
            invalid.append(json.dumps({**record, field: value}))
        for field in record:
            changed = dict(record)
            del changed[field]
            invalid.append(json.dumps(changed))
        for field in ("detail", "body", "token", "exception", "path", "job_id"):
            invalid.append(json.dumps({**record, field: "PRIVATE"}))
        invalid.append('{"severity":"error","severity":"info"}')
        value = demo.safe_api_log_summary("\n".join(invalid))
        self.assertEqual(value["accepted_lines"], 0)
        self.assertEqual(value["discarded_lines"], len(invalid))
        self.assertEqual(value["status"], "unavailable")
        self.assertEqual(value["records"], [])
        self.assertNotIn("PRIVATE", json.dumps(value))
        for raw in ("x" * 262145, "x\n" * 501):
            with self.assertRaises(ValueError):
                demo.safe_api_log_summary(raw)

    def test_top_level_failure_uses_exact_builtin_and_last_owned_source_only(self):
        source = str(demo.ROOT / "local-setup/stack.py")
        namespace = {}
        exec(  # noqa: S102 - trusted literal fixtures require controlled traceback filenames
            compile(
                "def owned():\n    raise FileNotFoundError('PRIVATE-KEY-AND-PATH')\n",
                source,
                "exec",
            ),
            namespace,
        )
        try:
            namespace["owned"]()
        except FileNotFoundError as error:
            result = demo.safe_top_level_failure(error)
        self.assertEqual(
            result["failure"],
            {
                "schema_version": 1,
                "error_category": "FileNotFoundError",
                "source": "stack",
                "line": 2,
            },
        )
        retained = json.dumps(result)
        self.assertNotIn("PRIVATE", retained)
        self.assertNotIn(source, retained)

    def test_top_level_failure_never_formats_hostile_subclass_or_its_chain(self):
        class Hostile(RuntimeError):
            def __str__(self):
                raise AssertionError("Private exception must not be formatted")

            def __repr__(self):
                raise AssertionError("Private exception must not be represented")

            def __getattribute__(self, name):
                if name in {"args", "__traceback__", "__cause__", "__context__"}:
                    raise AssertionError("Private fields must not use custom access")
                return super().__getattribute__(name)

        error = Hostile("PRIVATE-PROVIDER-TOKEN")
        error.__cause__ = ValueError("PRIVATE-CAUSE")
        try:
            raise error
        except Hostile as observed:
            result = demo.safe_top_level_failure(observed)
        self.assertEqual(
            result["failure"],
            {"schema_version": 1, "error_category": "other", "source": "unavailable", "line": 0},
        )
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertEqual(
            demo.safe_top_level_failure(RuntimeError("PRIVATE"))["failure"]["error_category"],
            "RuntimeError",
        )

    def test_top_level_failure_prefers_innermost_allowlisted_frame_and_ignores_foreign_paths(self):
        namespace = {}
        for name, code in (
            ("stack", "def inner():\n    raise ValueError('PRIVATE')\n"),
            ("p1_real_media", "def middle():\n    inner()\n"),
            ("phase_g_demo", "def outer():\n    middle()\n"),
        ):
            exec(  # noqa: S102 - trusted literal fixtures require controlled traceback filenames
                compile(code, str(demo.ROOT / demo.PREFLIGHT_SOURCE_FILES[name]), "exec"), namespace
            )
        try:
            namespace["outer"]()
        except ValueError as error:
            self.assertEqual(demo.safe_top_level_failure(error)["failure"]["source"], "stack")
        foreign = {}
        exec(  # noqa: S102 - trusted literal fixtures require controlled traceback filenames
            compile("def bad():\n    raise ValueError('PRIVATE')\n", "/PRIVATE/stack.py", "exec"),
            foreign,
        )
        try:
            foreign["bad"]()
        except ValueError as error:
            result = demo.safe_top_level_failure(error)
        self.assertEqual(result["failure"]["source"], "unavailable")
        self.assertEqual(result["failure"]["line"], 0)
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_cli_failure_emits_only_closed_projection_without_running_setup(self):
        output = io.StringIO()
        with (
            patch.object(demo, "main", side_effect=ValueError("PRIVATE-RAW-DETAIL")),
            redirect_stdout(output),
        ):
            self.assertEqual(demo.cli(["--mode", "scripted"]), 1)
        result = json.loads(output.getvalue())
        self.assertEqual(set(result), {"status", "code", "action", "failure"})
        self.assertEqual(result["failure"]["error_category"], "ValueError")
        self.assertNotIn("PRIVATE", output.getvalue())
        with patch.object(demo, "main", return_value=0), redirect_stdout(output := io.StringIO()):
            self.assertEqual(demo.cli([]), 0)
        self.assertEqual(output.getvalue(), "")

    def test_v3_query_uses_raw_otlp_endpoint_and_explicit_fixed_time_bounds(self):
        query = demo.jaeger_v3_query("conversation-agent", 1000000, 2000000)
        parsed = urlsplit(query)
        self.assertEqual(parsed.path, "/api/v3/traces")
        fields = parse_qs(parsed.query)
        self.assertEqual(fields["query.raw_traces"], ["true"])
        self.assertEqual(fields["query.search_depth"], ["100"])
        self.assertEqual(fields["query.start_time_min"], ["1970-01-01T00:00:01Z"])
        self.assertEqual(fields["query.start_time_max"], ["1970-01-01T00:00:02Z"])
        for arguments in (
            ("unknown", 1, 2),
            ("conversation-agent", True, 2),
            ("business-api", 3, 2),
        ):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                demo.jaeger_v3_query(*arguments)

    def test_v3_otlp_preserves_error_status_and_correlates_only_requested_resource_service(self):
        task = "11111111-1111-4111-8111-111111111111"
        fixture = self.trace_fixture()
        raw = json.dumps(fixture).encode()
        result = demo.parse_jaeger_v3(raw, service="conversation-agent", task_id=task)
        self.assertEqual(result["query_api"], "v3_raw_otlp")
        self.assertEqual(result["trace_count"], 1)
        self.assertEqual(result["span_count"], 1)
        self.assertTrue(result["current_task_correlated"])
        self.assertEqual(result["status_counts"], {"unset": 0, "ok": 0, "error": 1})
        self.assertEqual(result["kind_counts"]["internal"], 1)
        self.assertEqual(result["operations"], ["function_tool"])
        self.assertNotIn(task, json.dumps(result))
        mixed = raw + b"\n" + json.dumps(self.trace_fixture("business-api")).encode()
        result = demo.parse_jaeger_v3(mixed, service="conversation-agent", task_id=task)
        self.assertEqual(result["span_count"], 1)
        other = demo.parse_jaeger_v3(raw, service="durable-worker", task_id=task)
        self.assertEqual(other["span_count"], 0)
        self.assertFalse(other["current_task_correlated"])
        server = copy.deepcopy(fixture)
        server["result"]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["kind"] = 2
        result = demo.parse_jaeger_v3(
            json.dumps(server).encode(), service="conversation-agent", task_id=task
        )
        self.assertEqual(result["kind_counts"]["server"], 1)
        empty = demo.parse_jaeger_v3(b'{"result":{}}', service="conversation-agent", task_id=task)
        self.assertEqual(empty["span_count"], 0)
        for invalid in (
            b'{"result":{},"result":{}}',
            b'{"error":{"message":"private"}}',
            b'{"result":{}}\n{"error":{"message":"private"}}',
            b'{"data":[]}',
            b" ",
            b"x" * (demo.MAX_TRACE_BYTES + 1),
            b'{"result":{}}\n' * 257,
        ):
            with self.subTest(length=len(invalid)), self.assertRaises(ValueError):
                demo.parse_jaeger_v3(invalid, service="conversation-agent", task_id=task)

    def test_v3_otlp_rejects_unknown_content_scope_and_malformed_identity_numeric_status_fields(
        self,
    ):
        task = "11111111-1111-4111-8111-111111111111"
        fixture = self.trace_fixture()
        source = fixture["result"]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        for change in (
            {"events": [{"name": "private"}]},
            {"links": [{"traceId": "private"}]},
            {"traceState": "private=value"},
            {"traceId": "0" * 32},
            {"parentSpanId": "private"},
            {"name": "private-span-name"},
            {"kind": True},
            {"kind": 0},
            {"kind": 6},
            {"flags": True},
            {"startTimeUnixNano": 1},
            {"endTimeUnixNano": "01"},
            {"status": {"code": True}},
            {"status": {"code": 3}},
            {"status": {"code": 2, "message": "private"}},
            {"droppedEventsCount": True},
            {"attributes": [{"key": "@jaeger@warnings", "value": {"stringValue": "private"}}]},
            {"attributes": source["attributes"] * 2},
            {"attributes": [{"key": "gen_ai.usage.input_tokens", "value": {"intValue": "01"}}]},
            {
                "attributes": [
                    {
                        "key": "gen_ai.usage.input_tokens",
                        "value": {"intValue": "9223372036854775808"},
                    }
                ]
            },
            {"attributes": [{"key": "gen_ai.usage.input_tokens", "value": {"doubleValue": True}}]},
            {
                "attributes": [
                    {"key": "gen_ai.usage.input_tokens", "value": {"doubleValue": float("nan")}}
                ]
            },
            {"attributes": [{"key": "continuity.task_id", "value": {"stringValue": "private"}}]},
        ):
            modified = copy.deepcopy(fixture)
            modified["result"]["resourceSpans"][0]["scopeSpans"][0]["spans"][0].update(change)
            with self.subTest(fields=list(change)), self.assertRaises(ValueError):
                demo.parse_jaeger_v3(
                    json.dumps(modified).encode(), service="conversation-agent", task_id=task
                )
        modified = copy.deepcopy(fixture)
        modified["result"]["resourceSpans"][0]["scopeSpans"][0]["scope"]["name"] = "private"
        with self.assertRaises(ValueError):
            demo.parse_jaeger_v3(
                json.dumps(modified).encode(), service="conversation-agent", task_id=task
            )

    def test_positive_browser_gate_requires_all_six_actual_cases_and_versions(self):
        result = demo.verify_browser(self.observations, self.report)
        self.assertEqual(result["passed_cases"], 6)
        self.assertEqual(result["observations"], self.observations)

    def test_verified_browser_stage_retains_only_safe_actual_stats_without_claiming_phase_success(
        self,
    ):
        report = {**self.report, "private-error": "private-token"}
        stage = demo.browser_stage_evidence(self.observations, report, ("private-token",))
        self.assertEqual(stage["stage"], "browser")
        self.assertEqual(stage["status"], "passed")
        self.assertEqual(stage["phase_status"], "not_established")
        self.assertEqual(stage["runner_stats"], self.report["stats"])
        self.assertNotIn("private-token", json.dumps(stage))
        for changes in (
            {"transcript": "private"},
            {"last_status": "private-token"},
            {"native_agent": False},
        ):
            with self.subTest(fields=list(changes)), self.assertRaises(ValueError):
                demo.browser_stage_evidence(
                    {**self.observations, **changes}, report, ("private-token",)
                )

    @staticmethod
    def authority_fixture(**changes):
        return {
            "provider_id": "11111111-1111-4111-8111-111111111111",
            "revision": 1,
            "mutations": 1,
            "apply_calls": 1,
            "inquiries": 1,
            "receiver_events": 1,
            **changes,
        }

    def test_authority_wait_allows_only_eventual_delivery_and_records_before_every_decision(self):
        provider = self.authority_fixture()["provider_id"]
        now, reads, records, pauses = [0.0], [], [], []

        def read(budget):
            reads.append(budget)
            return self.authority_fixture(receiver_events=0 if len(reads) == 1 else 1)

        def pause(seconds):
            pauses.append(seconds)
            now[0] += seconds

        result = demo.wait_for_authority(
            read, records.append, provider, timeout_seconds=1, clock=lambda: now[0], pause=pause
        )
        self.assertEqual(result["mutations"], 1)
        self.assertEqual([record["receiver_events"] for record in records], [0, 1])
        self.assertEqual(reads, [1, 0.5])
        self.assertEqual(pauses, [0.5])
        self.assertTrue(all(record["provider_matches"] for record in records))
        self.assertNotIn(provider, json.dumps(records))

    def test_missing_delivery_times_out_without_counting_zero_progress_or_duplicates_as_success(
        self,
    ):
        provider = self.authority_fixture()["provider_id"]
        for changes in (
            {"mutations": 2},
            {"revision": 2},
            {"inquiries": 2},
            {"apply_calls": 0},
            {"revision": 0, "mutations": 0, "inquiries": 0, "apply_calls": 0},
            {"provider_id": "22222222-2222-4222-8222-222222222222"},
        ):
            reads, records, pauses = [], [], []

            def read(budget, values=changes, observed_reads=reads):
                observed_reads.append(budget)
                return self.authority_fixture(receiver_events=0, **values)

            with self.subTest(changes=changes), self.assertRaises(ValueError):
                demo.wait_for_authority(
                    read, records.append, provider, clock=lambda: 0, pause=pauses.append
                )
            self.assertEqual(len(reads), 1)
            self.assertEqual(len(records), 1)
            self.assertEqual(pauses, [])
        now, reads, records = [0.0], [], []

        def pending(budget):
            reads.append(budget)
            return self.authority_fixture(receiver_events=0)

        def pause(seconds):
            now[0] += seconds

        with self.assertRaises(TimeoutError):
            demo.wait_for_authority(
                pending,
                records.append,
                provider,
                timeout_seconds=1,
                clock=lambda: now[0],
                pause=pause,
            )
        self.assertEqual(reads, [1, 0.5])
        self.assertEqual(len(records), 2)
        self.assertTrue(all(record["receiver_events"] == 0 for record in records))

    def test_authority_read_deadline_and_observation_cap_cannot_be_extended_by_reads_or_sleep(self):
        provider = self.authority_fixture()["provider_id"]
        now, records, budgets = [0.0], [], []

        def overrun(budget):
            budgets.append(budget)
            now[0] += budget + 0.1
            return self.authority_fixture()

        with self.assertRaises(TimeoutError):
            demo.wait_for_authority(
                overrun,
                records.append,
                provider,
                timeout_seconds=1,
                clock=lambda: now[0],
                pause=lambda _seconds: None,
            )
        self.assertEqual(budgets, [1])
        self.assertEqual(len(records), 1)
        records.clear()
        with self.assertRaises(TimeoutError):
            demo.wait_for_authority(
                lambda _budget: self.authority_fixture(receiver_events=0),
                records.append,
                provider,
                clock=lambda: 0,
                pause=lambda _seconds: None,
            )
        self.assertEqual(len(records), 31)
        for changes in (
            {"revision": True},
            {"inquiries": -1},
            {"receiver_events": 9223372036854775808},
            {"apply_calls": "1"},
            {"private": "secret"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                demo.safe_authority_counts(self.authority_fixture(**changes), provider)

    def test_each_missing_or_false_behavior_cannot_count_as_passing(self):
        for flag in demo.BROWSER_FLAGS:
            for value in (None, False, "true", 1):
                with self.subTest(flag=flag, value=value), self.assertRaises(ValueError):
                    demo.verify_browser({**self.observations, flag: value}, self.report)

    def test_skipped_failed_flaky_or_wrong_runner_cases_never_count_as_passing(self):
        for changes in ({"expected": 4}, {"skipped": 1}, {"unexpected": 1}, {"flaky": 1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                demo.verify_browser(
                    self.observations, {"stats": {**self.report["stats"], **changes}}
                )
        for changes in (
            {"playwright_version": "1.64.0"},
            {"browser_version": ""},
            {"unexpected_network_requests": 1},
            {"supplier_outcome": "pending"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                demo.verify_browser({**self.observations, **changes}, self.report)

    def test_numeric_sdk_reports_require_real_usage_and_actual_report_observation(self):
        result = demo.verify_sdk([self.sdk] * 3)
        self.assertEqual(result["reports"], 3)
        self.assertEqual(result["totals"]["trace_exported"], 3)
        for records in (
            [],
            [self.sdk] * 2,
            [self.sdk] * 33,
            [{**self.sdk, "sdk_report_observed": False}] * 3,
            [{**self.sdk, "values": dict.fromkeys(demo.OBSERVATION_FIELDS, 0)}] * 3,
        ):
            with self.subTest(count=len(records)), self.assertRaises(ValueError):
                demo.verify_sdk(records)

    def test_sdk_reports_reject_content_fields_and_nonfinite_or_boolean_counts(self):
        for value in (float("nan"), float("inf"), True, -1, 9223372036854775808, "1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                demo.verify_sdk(
                    [{**self.sdk, "values": {**self.sdk["values"], "tts_audio_seconds": value}}] * 3
                )
        for value in (
            {**self.sdk, "transcript": "private-content"},
            {**self.sdk, "values": {**self.sdk["values"], "request": "private-content"}},
        ):
            with self.assertRaises(ValueError):
                demo.verify_sdk([value] * 3)

    def test_failure_sdk_reports_retain_zero_and_unobserved_values_without_passing_the_gate(self):
        unobserved = {
            **self.sdk,
            "sdk_report_observed": False,
            "values": dict.fromkeys(demo.OBSERVATION_FIELDS, 0),
        }
        result = demo.safe_sdk_failure([unobserved])
        self.assertEqual(result["status"], "observed")
        self.assertEqual(result["reports"], 1)
        self.assertEqual(result["records"], [unobserved])
        self.assertEqual(result["totals"], dict.fromkeys(demo.OBSERVATION_FIELDS, 0))
        self.assertEqual(demo.safe_sdk_failure([])["reports"], 0)
        self.assertEqual(demo.safe_sdk_failure([self.sdk] * 32)["reports"], 32)
        self.assertNotIn("private", json.dumps(result))
        with self.assertRaises(ValueError):
            demo.verify_sdk([unobserved] * 3)
        for invalid in (
            None,
            {},
            [self.sdk] * 33,
            ["private text"],
            [{**self.sdk, "schema_version": True}],
            [{**self.sdk, "sdk_report_observed": 1}],
            [{**self.sdk, "sdk_report_observed": "true"}],
            [{**self.sdk, "transcript": "private text"}],
            [{**self.sdk, "values": {**self.sdk["values"], "private": 1}}],
        ):
            with self.subTest(value_type=type(invalid)), self.assertRaises(ValueError):
                demo.safe_sdk_failure(invalid)
        for invalid in (True, -1, float("inf"), float("nan"), 9223372036854775808, "1"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                demo.safe_sdk_failure(
                    [{**self.sdk, "values": {**self.sdk["values"], "tts_audio_seconds": invalid}}]
                )
        compile(demo.READ_REPORTS_SCRIPT, "read-numeric-reports", "exec")

    def test_failure_observations_remain_diagnostic_without_becoming_passing_evidence(self):
        incomplete = {
            **self.observations,
            "native_agent": False,
            "last_phase": "join",
            "last_status": "The agent is absent.",
        }
        self.assertEqual(demo.safe_browser_failure(incomplete, ("private-token",)), incomplete)
        with self.assertRaises(ValueError):
            demo.verify_browser(incomplete, self.report)
        for extra in (
            {"transcript": "private text"},
            {"metadata": "private"},
            {"last_status": "private-token"},
            {"last_phase": "arbitrary-private-phase"},
            {"audio_current_time": float("nan")},
            {"native_agent": "true"},
        ):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                demo.safe_browser_failure({**incomplete, **extra}, ("private-token",))

    def test_failure_voice_pipeline_diagnostics_are_exact_bounded_optional_observations(self):
        diagnostic = {
            **self.observations,
            **dict.fromkeys(demo.BROWSER_DIAGNOSTIC_FLAGS, False),
            **dict.fromkeys(demo.BROWSER_DIAGNOSTIC_COUNTERS, 0),
            "voice_displayed_transcripts": 0,
            "native_submit_acknowledged": False,
        }
        self.assertEqual(demo.safe_browser_failure(diagnostic, ("private-token",)), diagnostic)
        with self.assertRaises(ValueError):
            demo.verify_browser(diagnostic, self.report)
        for field in demo.BROWSER_DIAGNOSTIC_COUNTERS | {"voice_displayed_transcripts"}:
            maximum = 40 if field == "voice_displayed_transcripts" else 1000000000
            self.assertEqual(
                demo.safe_browser_failure({**diagnostic, field: maximum}, ("private-token",))[
                    field
                ],
                maximum,
            )
            for invalid in (True, False, -1, maximum + 1, 0.5, "0", None, float("nan"), {}):
                with self.subTest(field=field, invalid=invalid), self.assertRaises(ValueError):
                    demo.safe_browser_failure({**diagnostic, field: invalid}, ("private-token",))
        for field in demo.BROWSER_DIAGNOSTIC_FLAGS:
            for invalid in (0, 1, "false", None, {}):
                with self.subTest(field=field, invalid=invalid), self.assertRaises(ValueError):
                    demo.safe_browser_failure({**diagnostic, field: invalid}, ("private-token",))
        for field in ("voice_text_transcript", "voice_room", "voice_text_unrecognized"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                demo.safe_browser_failure(
                    {**diagnostic, field: "private-token"}, ("private-token",)
                )

    def test_embedded_supplier_holder_and_markers_are_valid_python_without_shell_expansion(self):
        compile(demo.HeldSupplierProbe.HOLD_SCRIPT, "supplier-holder", "exec")
        probe = demo.HeldSupplierProbe(
            "owned-worker", Path("/tmp/markers"), Path("/tmp/output"), {}
        )
        with patch.object(
            demo.subprocess, "run", return_value=SimpleNamespace(returncode=0)
        ) as run:
            self.assertTrue(probe._marker())
            self.assertTrue(probe._marker(release=True))
        for call in run.call_args_list:
            argv = call.args[0]
            self.assertEqual(argv[:3], ["docker", "exec", "owned-worker"])
            self.assertEqual(argv[3:5], ["python", "-c"])
            compile(argv[5], "supplier-marker", "exec")
            self.assertFalse(call.kwargs.get("shell", False))
            self.assertEqual(call.kwargs["timeout"], 3)

    def test_browser_sample_provenance_rejects_html_fallback_wrong_samples_and_oversized_bytes(
        self,
    ):
        payload = b"RIFF" + bytes(40)
        digest = hashlib.sha256(payload).hexdigest()
        result = demo.browser_sample_provenance(payload, digest)
        self.assertEqual(result["sha256"], digest)
        self.assertEqual(result["source"], "packaged_wav_webaudio")
        self.assertFalse(result["physical_microphone_capture_verified"])
        for raw, expected in (
            (b"<html>not the sample</html>", digest),
            (b"other" * 10, digest),
            (payload, "wrong-hash"),
            (bytes(524289), digest),
        ):
            with self.subTest(length=len(raw)), self.assertRaises(ValueError):
                demo.browser_sample_provenance(raw, expected)

    def test_served_console_provenance_checks_index_before_all_compiled_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "assets").mkdir()
            expected = {
                "/index.html": b'<script src="/assets/index-abc.js"></script>',
                "/assets/index-abc.js": b"compiled-current-code",
                "/assets/index-def.css": b"compiled-current-styles",
            }
            for relative, content in expected.items():
                (directory / relative.removeprefix("/")).write_bytes(content)
            calls = []

            def fetch(relative, maximum):
                calls.append(relative)
                self.assertLessEqual(len(expected[relative]), maximum)
                return expected[relative]

            result = demo.console_provenance(directory, fetch)
            self.assertEqual(calls, list(expected))
            self.assertEqual(result["count"], 3)
            self.assertEqual(
                result["files"]["assets/index-abc.js"],
                hashlib.sha256(expected["/assets/index-abc.js"]).hexdigest(),
            )
            calls.clear()

            def stale_index(relative, maximum):
                calls.append(relative)
                return b"stale index"

            with self.assertRaises(ValueError):
                demo.console_provenance(directory, stale_index)
            self.assertEqual(calls, ["/index.html"])
            with self.assertRaises(ValueError):
                demo.console_provenance(
                    directory,
                    lambda relative, maximum: (
                        b"stale bundle" if relative.endswith(".js") else expected[relative]
                    ),
                )

    def test_console_preflight_rejects_unsafe_missing_or_unbounded_local_and_served_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            assets = directory / "assets"
            assets.mkdir()
            index = directory / "index.html"
            index.write_bytes(b"index")
            javascript = assets / "index-abc.js"
            javascript.write_bytes(b"code")
            for invalid in (b"", bytes(65537), "index", None):
                with self.subTest(served=type(invalid)), self.assertRaises(ValueError):
                    demo.console_provenance(
                        directory, lambda relative, maximum, value=invalid: value
                    )
            javascript.unlink()
            with self.assertRaises(ValueError):
                demo.console_provenance(directory, lambda relative, maximum: b"index")
            javascript.symlink_to(index)
            with self.assertRaises(ValueError):
                demo.console_provenance(directory, lambda relative, maximum: b"index")
            javascript.unlink()
            with javascript.open("wb") as stream:
                stream.truncate(2097153)
            with self.assertRaises(ValueError):
                demo.console_provenance(directory, lambda relative, maximum: b"index")
            javascript.unlink()
            (assets / "unexpected.map").write_bytes(b"code")
            with self.assertRaises(ValueError):
                demo.console_provenance(directory, lambda relative, maximum: b"index")
            with self.assertRaises(ValueError):
                demo.console_provenance(directory / "missing", lambda relative, maximum: b"index")

    def test_source_provenance_inventory_requires_actual_core_service_modules_and_nine_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for package in (
                "projects/agent-continuity/python/src/continuity_lab",
                "services/control_api",
                "services/conversation_agent",
            ):
                directory = root / package
                directory.mkdir(parents=True)
                (directory / "__init__.py").write_text("module = 1\n")
            core = root / "projects/agent-continuity/python/src/continuity_lab"
            for name in ("api", "postgres_api", "testing"):
                (core / f"{name}.py").write_text(f"public_module = {name!r}\n")
            # A stale root shadow cannot supply the canonical package inventory.
            shadow = root / "continuity_lab"
            shadow.mkdir()
            (shadow / "__init__.py").write_text("shadow = True\n")
            assets = root / "services/conversation_agent/assets"
            assets.mkdir()
            for number in range(9):
                (assets / f"sample-{number}.wav").write_bytes(b"RIFF" + bytes(40))
            (assets / "manifest.json").write_text("{}\n")
            modules, installed_assets = demo.installed_source_inventory(root)
            self.assertEqual(len(modules), 6)
            self.assertEqual(len(installed_assets), 10)
            self.assertEqual(
                modules["continuity_lab/__init__.py"], hashlib.sha256(b"module = 1\n").hexdigest()
            )
            for name in ("api", "postgres_api", "testing"):
                self.assertIn(f"continuity_lab/{name}.py", modules)
            self.assertFalse(any(name.startswith("projects/") for name in modules))
            (core / "__init__.py").unlink()
            with self.assertRaises(ValueError):
                demo.installed_source_inventory(root)
            (core / "__init__.py").write_text("module = 1\n")
            (assets / "sample-0.wav").unlink()
            (assets / "unexpected.json").write_text("{}\n")
            with self.assertRaises(ValueError):
                demo.installed_source_inventory(root)
        compile(demo.INSTALLED_MODULE_SCRIPT, "installed-module-provenance", "exec")

    def test_dispatch_diagnostics_only_return_counts_and_finite_statuses(self):
        from livekit.protocol.agent import JobStatus

        empty = SimpleNamespace(state=SimpleNamespace(jobs=[]))
        assigned = SimpleNamespace(
            state=SimpleNamespace(
                jobs=[
                    SimpleNamespace(
                        state=SimpleNamespace(
                            status=JobStatus.JS_RUNNING,
                            worker_id="private-worker-id",
                            error="private-error",
                        )
                    )
                ]
            )
        )
        result = demo.dispatch_counts([empty, assigned])
        self.assertEqual(result["dispatches"], 2)
        self.assertEqual(result["zero_job_dispatches"], 1)
        self.assertEqual(result["assigned_jobs"], 1)
        self.assertEqual(result["jobs"]["running"], 1)
        self.assertNotIn("private", json.dumps(result))
        with self.assertRaises(ValueError):
            demo.dispatch_counts([empty] * 33)
        self.assertEqual(
            demo.native_worker_counts({"active_jobs": 1, "worker_load": 1.0, "room": "private"}),
            {"active_jobs": 1, "worker_load": 1.0},
        )
        for value in ({"active_jobs": True}, {"worker_load": float("nan")}, {"worker_load": -1}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                demo.native_worker_counts(value)

    def test_pg_fault_timing_includes_server_wait_age_and_safe_wall_clock_milestones(self):
        started = datetime(2030, 12, 1, tzinfo=UTC)
        observed = started + timedelta(milliseconds=25)
        base = int(started.timestamp() * 1000)
        result = demo.pg_wait_result(
            started,
            observed,
            observed_unix_ms=base + 30,
            released_unix_ms=base + 530,
            observed_hold_seconds=0.5,
        )
        self.assertAlmostEqual(result["actual_wait_age_at_observation_seconds"], 0.025)
        self.assertAlmostEqual(result["actual_wait_seconds_estimate"], 0.525)
        self.assertTrue(result["schema_advisory_wait_verified"])
        self.assertTrue(result["release_within_lock_timeout"])
        self.assertEqual(result["wait_started_unix_ms"], base)
        self.assertEqual(result["released_unix_ms"], base + 530)
        late = demo.pg_wait_result(
            started,
            observed,
            observed_unix_ms=base + 30,
            released_unix_ms=base + 1000,
            observed_hold_seconds=0.95,
        )
        self.assertFalse(late["release_within_lock_timeout"])
        for changes in (
            {"observed_hold_seconds": float("nan")},
            {"observed_hold_seconds": True},
            {"released_unix_ms": base - 1},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                demo.pg_wait_result(
                    started,
                    observed,
                    **{
                        "observed_unix_ms": base + 30,
                        "released_unix_ms": base + 530,
                        "observed_hold_seconds": 0.5,
                        **changes,
                    },
                )
        with self.assertRaises(ValueError):
            demo.pg_wait_result(
                observed,
                started,
                observed_unix_ms=base,
                released_unix_ms=base + 10,
                observed_hold_seconds=0.5,
            )

    def test_native_log_gate_rejects_sdk_job_extras_freeform_bodies_and_unknown_vocabulary(self):
        record = {
            "service": "conversation-agent",
            "timestamp": "2030-12-01T00:00:00+00:00",
            "severity": "warning",
            "event": "sdk_warning",
            "code": "sdk_warning",
        }
        self.assertEqual(demo.verify_native_record(record), "sdk_warning")
        for extra in (
            {"message": "private SDK body"},
            {"room": "private-room"},
            {"job_id": "private-job"},
            {"code.file.path": "private-path"},
            {"event": "private event"},
            {"code": "private code"},
            {"service": "other-service"},
            {"severity": "arbitrary"},
        ):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                demo.verify_native_record({**record, **extra})

    def test_browser_override_requires_explicit_absolute_regular_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "browser with spaces"
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(0o700)
            self.assertEqual(demo.browser_executable(str(executable)), str(executable))
            link = Path(directory) / "alias"
            link.symlink_to(executable)
            for value in (
                "relative/browser",
                str(link),
                str(Path(directory)),
                str(executable.parent / "missing"),
                str(executable.parent / ".." / executable.name),
                "bad\0path",
            ):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    demo.browser_executable(value)
            executable.chmod(0o600)
            with self.assertRaises(ValueError):
                demo.browser_executable(str(executable))

    def test_json_reader_rejects_symlinks_large_nonfinite_and_duplicate_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good = root / "good.json"
            good.write_text(json.dumps(self.report))
            self.assertEqual(demo.bounded_json(good), self.report)
            link = root / "alias.json"
            link.symlink_to(good)
            with self.assertRaises(ValueError):
                demo.bounded_json(link)
            for raw in (
                '{"expected":1,"expected":5}',
                '{"count":NaN}',
                '"' + "x" * demo.MAX_JSON_BYTES + '"',
            ):
                good.write_text(raw)
                with self.subTest(size=len(raw)), self.assertRaises(ValueError):
                    demo.bounded_json(good)


class PhaseGDispatchObservationTests(unittest.IsolatedAsyncioTestCase):
    async def test_control_plane_diagnostics_only_count_verified_current_run_bindings(self):
        from datetime import date

        from livekit.protocol.models import ParticipantInfo

        from continuity_lab.authorization import AuthenticatedActor
        from continuity_lab.models import BookingChange
        from continuity_lab.session_grants import sign_grant

        secret = "s" * 40
        current = "11111111-1111-4111-8111-111111111111"
        other = "22222222-2222-4222-8222-222222222222"

        def record(room, task):
            grant = sign_grant(
                secret=secret,
                actor=AuthenticatedActor("local-operator", "demo-traveller"),
                room=room,
                participant="browser-unit",
                request=BookingChange("DEMO-BK-001", date(2030, 12, 10), True),
                request_key="private-original-key",
                task_id=task,
            )
            return SimpleNamespace(
                agent_name="local-business-agent",
                metadata=grant,
                state=SimpleNamespace(deleted_at=0, jobs=[]),
            )

        client = SimpleNamespace(
            room=SimpleNamespace(
                list_rooms=AsyncMock(
                    return_value=SimpleNamespace(
                        rooms=[
                            SimpleNamespace(name="business-owned"),
                            SimpleNamespace(name="business-other"),
                        ]
                    )
                ),
                list_participants=AsyncMock(
                    return_value=SimpleNamespace(
                        participants=[
                            SimpleNamespace(kind=ParticipantInfo.AGENT),
                            SimpleNamespace(kind=ParticipantInfo.STANDARD),
                        ]
                    )
                ),
            ),
            agent_dispatch=SimpleNamespace(
                list_dispatch=AsyncMock(
                    side_effect=[
                        [record("business-owned", current)],
                        [record("business-other", other)],
                    ]
                )
            ),
        )
        context = AsyncMock()
        context.__aenter__.return_value = client
        with patch("livekit.api.LiveKitAPI", return_value=context):
            result = await demo.conversation_dispatch_observations(
                "ws://127.0.0.1:17880", "synthetic", secret, {current}
            )
        self.assertEqual(result["rooms"], 1)
        self.assertEqual(result["zero_job_dispatches"], 1)
        self.assertEqual(result["agent_participants"], 1)
        self.assertEqual(result["non_agent_participants"], 1)
        client.room.list_participants.assert_awaited_once()
        raw = json.dumps(result)
        for private in (
            secret,
            current,
            other,
            "business-owned",
            "business-other",
            "private-original-key",
            "browser-unit",
        ):
            self.assertNotIn(private, raw)

    async def test_room_inventory_cap_refuses_unbounded_diagnostic_traversal(self):
        client = SimpleNamespace(
            room=SimpleNamespace(
                list_rooms=AsyncMock(
                    return_value=SimpleNamespace(rooms=[SimpleNamespace(name="business-room")] * 65)
                )
            )
        )
        context = AsyncMock()
        context.__aenter__.return_value = client
        with patch("livekit.api.LiveKitAPI", return_value=context), self.assertRaises(ValueError):
            await demo.conversation_dispatch_observations(
                "ws://127.0.0.1:17880", "synthetic", "s" * 40, set()
            )
