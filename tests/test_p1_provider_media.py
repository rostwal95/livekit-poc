"""Provider evidence policy uses synthetic fixtures; no credentials or API calls."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "local-setup/scripts"
sys.path.insert(0, str(SCRIPTS))
import p1_real_media as media


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


demo = load("provider_demo_test", SCRIPTS / "phase_g_demo.py")
runner = load("provider_wrapper_test", SCRIPTS / "p1_runtime_acceptance.py")
base_media = load("provider_base_media_fixture", ROOT / "tests/test_p1_real_media.py")
base_runtime = load("provider_base_runtime_fixture", ROOT / "tests/test_p1_runtime_acceptance.py")
RUN = "a" * 32
TASK = "11111111-1111-4111-8111-111111111111"
PAIRS = dict(zip(media.PROVIDER_MODELS.values(), media.PROVIDER_NAMES.values(), strict=True))


def browser():
    return {**base_media.RealEvidenceTests().browser(), "mode": "provider_real", "run_id": RUN}


def records():
    values = dict.fromkeys(demo.OBSERVATION_FIELDS, 1.0)
    values.update(trace_dropped=0.0, trace_failed=0.0)
    return [
        {
            "schema_version": 1,
            "mode": "provider_real",
            "sdk_report_observed": True,
            "values": dict(values),
        }
        for _ in range(2)
    ]


def resource(role):
    before = {
        "cpu_usage_usec": 1,
        "cpu_quota_usec": 150000,
        "cpu_period_usec": 100000,
        "memory_current_bytes": 100,
        "memory_peak_bytes": 100,
        "memory_limit_bytes": 512 * 1024**2,
        "pids_current": 1,
        "pids_limit": 256,
        "oom_kills": 0,
    }
    return media.resource_window(
        before, {**before, "cpu_usage_usec": 2}, role=role, mode="provider_real"
    )


def trace(service="conversation-agent"):
    spans = []
    definitions = (
        [("continuity.sdk", model, provider, None) for model, provider in PAIRS.items()]
        if service == "conversation-agent"
        else [("continuity.sdk", None, None, None)]
    )
    if service == "conversation-agent":
        definitions += [
            ("function_tool", None, None, name) for name in ("submit_investigation", "get_case")
        ]
        definitions += [("continuity.session", None, None, None)]
    for index, (name, model, provider, tool) in enumerate(definitions, 1):
        attrs = {"continuity.task_id": TASK}
        if model:
            attrs.update({"gen_ai.request.model": model, "gen_ai.provider.name": provider})
        if tool:
            attrs["gen_ai.tool.name"] = tool
        spans.append(
            {
                "traceId": "1" * 32,
                "spanId": f"{index:016x}",
                "name": name,
                "kind": 1,
                "startTimeUnixNano": "1",
                "endTimeUnixNano": "2",
                "attributes": [
                    {"key": key, "value": {"stringValue": value}} for key, value in attrs.items()
                ],
            }
        )
    return {
        "result": {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {"key": key, "value": {"stringValue": value}}
                            for key, value in {
                                "service.name": service,
                                "service.version": "0.1.0",
                                "continuity.mode": "provider_real",
                            }.items()
                        ]
                    },
                    "scopeSpans": [
                        {"scope": {"name": "continuity.safe", "version": "1"}, "spans": spans}
                    ],
                }
            ]
        }
    }


class ProviderMediaTests(unittest.TestCase):
    def test_only_explicit_trusted_profile_selects_providers(self):
        self.assertEqual(runner.selected_real_profile({}), "local_real")
        self.assertEqual(
            runner.selected_real_profile({"P1_ACCEPTANCE_REAL_PROFILE": "provider_real"}),
            "provider_real",
        )
        self.assertEqual(
            runner.selected_real_profile({"P1_CONVERSATION_INFERENCE": "provider_real"}),
            "local_real",
        )
        for value in (None, True, "scripted", "remote", "provider_real "):
            with self.subTest(value=value), self.assertRaises(ValueError):
                runner.selected_real_profile({"P1_ACCEPTANCE_REAL_PROFILE": value})

    def test_provider_wrapper_launch_is_explicit_live_and_never_executes_from_fixture(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            source = root / "local-setup/scripts/phase_g_demo.py"
            source.parent.mkdir(parents=True)
            source.write_text("# synthetic command fixture")
            with patch.object(
                runner, "command", side_effect=RuntimeError("SYNTHETIC-PRIVATE")
            ) as command:
                report, code = runner.run_case("P1-20", root=root, real_profile="provider_real")
            self.assertEqual(code, 1)
            self.assertEqual(report["mode"], "live")
            arguments = command.call_args.args[1]
            self.assertEqual(arguments[arguments.index("--mode") + 1], "provider_real")
            evidence = next(
                (root / ".local/validation/p1-runtime-acceptance").glob("*/evidence.json")
            )
            self.assertEqual(json.loads(evidence.read_text())["real_profile"], "provider_real")
            self.assertNotIn("SYNTHETIC-PRIVATE", evidence.read_text())

    def test_new_provider_declaration_preserves_v1_and_changes_only_explicit_model_selection(self):
        old = json.loads((ROOT / "local-setup/workloads/p1-provider-real-v1.json").read_text())
        self.assertEqual(
            "22f46da1af438da2c644966a2a262da17bcf4552cffbddc353de3152521ba94a",
            hashlib.sha256(media.canonical(old)).hexdigest(),
        )
        self.assertEqual("p1-provider-real-v1", old["declaration_id"])
        self.assertEqual("gpt-6-luna", old["models"]["llm"])
        current, _ = media.declaration(ROOT, mode="provider_real")
        expected = copy.deepcopy(old)
        expected["declaration_id"] = "p1-provider-real-v2"
        expected["models"]["llm"] = "gpt-5.4-mini"
        self.assertEqual(expected, current)

    def test_complete_frozen_provider_declaration_refuses_any_policy_change(self):
        declared, digest = media.declaration(ROOT, mode="provider_real")
        self.assertEqual(declared["models"], media.PROVIDER_MODELS)
        self.assertEqual(len(digest), 64)
        self.assertNotIn("model_manifest", declared)
        for field, value in (
            ("profile", "local_real"),
            ("models", {}),
            ("background_inquiries", 7),
            ("external_provider_resources", "measured"),
            ("browser_run_seconds", 301),
            ("resource_limits", {}),
        ):
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder).resolve()
                path = root / "local-setup/workloads/p1-provider-real-v2.json"
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps({**declared, field: value}))
                with self.subTest(field=field), self.assertRaises(ValueError):
                    media.declaration(root, mode="provider_real")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            path = root / "local-setup/workloads/p1-provider-real-v2.json"
            path.parent.mkdir(parents=True)
            path.write_text('{"profile":"private","profile":"provider_real"}')
            with self.assertRaises(ValueError):
                media.declaration(root, mode="provider_real")

    def test_provider_join_retries_count_logical_sessions_and_preserve_every_binding(self):
        value = browser()
        value["session_mint_joins"][0] = base_media.RealEvidenceTests().mint_join((503, 200))
        observed = media.safe_browser(value, run_id=RUN, passing=True, mode="provider_real")
        self.assertEqual(observed["native_sessions"], 4)
        self.assertEqual(len(observed["session_mint_joins"]), 4)
        for field in media.MINT_BINDING_FLAGS:
            changed = copy.deepcopy(value)
            changed["session_mint_joins"][0]["attempts"][1][field] = False
            with self.subTest(field=field), self.assertRaises(ValueError):
                media.safe_browser(changed, run_id=RUN, passing=True, mode="provider_real")

    def test_provider_inventory_needs_no_local_model_or_engine_file(self):
        required = media.gate_inventory(ROOT, mode="provider_real")
        self.assertIn("local-setup/provider_config.py", required)
        self.assertNotIn("local-setup/scripts/local_models.py", required)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            for relative in required:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / relative).read_bytes())
            self.assertEqual(media.gate_inventory(root, mode="provider_real"), required)
            with self.assertRaises(ValueError):
                media.gate_inventory(root)

    def test_credentials_file_is_private_native_only_and_never_implicitly_created(self):
        keys = {name: "SYNTHETIC-ONLY-" + name for name in demo.PROVIDER_ENV_KEYS}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            path = demo.private_environment_file(
                root,
                "native",
                {"P1_CONVERSATION_INFERENCE": "provider_real", **keys},
                mode="provider_real",
            )
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(path.stat().st_nlink, 1)
            for name, mode, settings in (
                ("api", "provider_real", keys),
                ("worker", "provider_real", keys),
                ("native", "local_real", keys),
                ("native", "scripted", keys),
                ("native", "provider_real", {}),
                ("native", "provider_real", {**keys, "EXTRA": "bad\nline"}),
            ):
                with self.subTest(name=name, mode=mode), self.assertRaises(ValueError):
                    demo.private_environment_file(root, name, settings, mode=mode)
            with self.assertRaises(FileExistsError):
                demo.private_environment_file(root, "native", keys, mode="provider_real")
            self.assertEqual(sorted(p.name for p in root.iterdir()), ["native.env"])

    def test_provider_browser_requires_same_real_flags_boundaries_and_exact_profile(self):
        report = {"stats": {"expected": 2, "unexpected": 0, "skipped": 0, "flaky": 0}}
        self.assertEqual(
            media.verify_browser(browser(), report, run_id=RUN, mode="provider_real")[
                "passed_cases"
            ],
            2,
        )
        with self.assertRaises(ValueError):
            media.verify_browser(browser(), report, run_id=RUN)
        for field, value in (
            ("fixture_input_committed", False),
            ("background_pending_after_end", 0),
            ("active_interrupt_seconds", 1.501),
            ("exact_quote_confirmed", False),
            ("mode", "local_real"),
            ("no_mutation_before_human", False),
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                media.verify_browser(
                    {**browser(), field: value}, report, run_id=RUN, mode="provider_real"
                )
        for field in ("skipped", "flaky", "unexpected"):
            bad = copy.deepcopy(report)
            bad["stats"][field] = 1
            with self.assertRaises(ValueError):
                media.verify_browser(browser(), bad, run_id=RUN, mode="provider_real")

    def test_only_native_api_worker_resources_can_be_observed_for_provider_profile(self):
        for role in ("native", "api", "worker"):
            self.assertGreater(resource(role)["cpu_usage_delta_usec"], 0)
        for role in ("llm", "stt", "tts"):
            with self.subTest(role=role), self.assertRaises(ValueError):
                resource(role)
        before = resource("api")["before"]
        for changed in (
            {"cpu_usage_usec": 1},
            {"oom_kills": 1},
            {"memory_limit_bytes": 1},
            {"cpu_usage_usec": True},
        ):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                media.resource_window(
                    before,
                    {**before, "cpu_usage_usec": 2, **changed},
                    role="api",
                    mode="provider_real",
                )
        with self.assertRaises(ValueError):
            media.resource_window(before, {**before, "cpu_usage_usec": 2}, role="api")

    def test_provider_sdk_proof_requires_actual_output_and_export_without_content(self):
        original = records()
        self.assertTrue(
            demo.verify_sdk(original, mode="provider_real")["real_inference_usage_only"]
        )
        for field, number in (
            ("llm_output_tokens", 0),
            ("stt_audio_seconds", 0),
            ("tts_audio_seconds", 0),
            ("trace_failed", 1),
            ("trace_dropped", 1),
        ):
            bad = copy.deepcopy(original)
            for record in bad:
                record["values"][field] = number
            with self.subTest(field=field), self.assertRaises(ValueError):
                demo.verify_sdk(bad, mode="provider_real")
        bad = copy.deepcopy(original)
        bad[0]["mode"] = "local_real"
        with self.assertRaises(ValueError):
            demo.verify_sdk(bad, mode="provider_real")
        bad = copy.deepcopy(original)
        bad[0]["values"]["prompt"] = "SYNTHETIC-PRIVATE"
        with self.assertRaises(ValueError):
            demo.verify_sdk(bad, mode="provider_real")

    def test_provider_otlp_requires_exact_model_provider_pairs_and_safe_fields(self):
        value = trace()
        result = demo.parse_jaeger_v3(
            json.dumps(value).encode(),
            service="conversation-agent",
            task_id=TASK,
            mode="provider_real",
        )
        self.assertEqual(result["model_providers"], PAIRS)
        self.assertEqual(set(result["providers"]), set(PAIRS.values()))
        spans = value["result"]["resourceSpans"][0]["scopeSpans"][0]["spans"]
        for provider in ("openai", "SYNTHETIC-PRIVATE", ""):
            bad = copy.deepcopy(value)
            attrs = bad["result"]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"]
            attrs[-1]["value"]["stringValue"] = provider
            with self.subTest(provider=provider), self.assertRaises(ValueError):
                demo.parse_jaeger_v3(
                    json.dumps(bad).encode(),
                    service="conversation-agent",
                    task_id=TASK,
                    mode="provider_real",
                )
        spans[0]["attributes"].append(
            {"key": "prompt", "value": {"stringValue": "SYNTHETIC-PRIVATE"}}
        )
        with self.assertRaises(ValueError):
            demo.parse_jaeger_v3(
                json.dumps(value).encode(),
                service="conversation-agent",
                task_id=TASK,
                mode="provider_real",
            )

    def test_provider_versions_are_installed_and_exact_without_credential_probe(self):
        correct = {
            "livekit-plugins-" + name: "1.8.11" for name in ("deepgram", "openai", "elevenlabs")
        }
        demo.require_provider_versions(correct)
        self.assertNotIn("livekit-plugins-deepgram", demo.installed_module_script("scripted"))
        self.assertIn("livekit-plugins-deepgram", demo.installed_module_script("provider_real"))
        for invalid in ({}, {**correct, "livekit-plugins-elevenlabs": "1.8.10"}):
            with self.assertRaises(ValueError):
                demo.require_provider_versions(invalid)


class ProviderWrapperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.artifact = self.root / ".local/validation/fresh"
        self.artifact.mkdir(parents=True)
        self.value = base_runtime.browser_fixture(True)
        for key in ("model_manifest_sha256", "model_setup", "engine_inference"):
            self.value.pop(key)
        self.value.update(
            mode="provider_real",
            declaration_sha256="d" * 64,
            gate_source_hashes={"driver": "f" * 64},
            original_task_id=TASK,
            resources={role: resource(role) for role in ("native", "api", "worker")},
            runtime_versions={
                "livekit-plugins-" + name: "1.8.11" for name in ("deepgram", "openai", "elevenlabs")
            },
            provider_trust={"source": "image_os"},
            provider_inference={
                "profile": "provider_real",
                "models": media.PROVIDER_MODELS,
                "providers": media.PROVIDER_NAMES,
                "external_resources": "unobserved",
                "actual_sdk_usage": True,
            },
            sdk=demo.verify_sdk(records(), mode="provider_real"),
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
                "quote_wait_seconds": 0.5,
            },
        )
        self.value["browser"] = media.verify_browser(
            browser(),
            {"stats": {"expected": 2, "unexpected": 0, "skipped": 0, "flaky": 0}},
            run_id=RUN,
            mode="provider_real",
        )
        self.write("real-browser-observations.json", browser())
        self.write(
            "playwright-stats.json",
            {
                "schema_version": 1,
                "run_id": RUN,
                "stats": {"expected": 2, "unexpected": 0, "skipped": 0, "flaky": 0},
            },
        )
        self.write(
            "provider-sdk-records.json",
            {"schema_version": 1, "run_id": RUN, "mode": "provider_real", "records": records()},
        )
        self.value["traces"] = {}
        for service in ("business-api", "conversation-agent", "durable-worker"):
            raw = json.dumps(trace(service)).encode()
            (self.artifact / ("provider-trace-" + service + ".json")).write_bytes(raw)
            self.value["traces"][service] = demo.parse_jaeger_v3(
                raw, service=service, task_id=TASK, mode="provider_real"
            )
        self.verifier = SimpleNamespace(
            verify_browser=media.verify_browser,
            resource_window=media.resource_window,
            declaration=lambda *_a, **_k: ({}, "d" * 64),
            gate_inventory=lambda *_a, **_k: {"driver": "f" * 64},
        )

    def write(self, name, value):
        (self.artifact / name).write_text(json.dumps(value))

    def verify(self, value=None):
        with (
            patch.object(runner, "source_hashes", return_value={}),
            patch.object(
                runner,
                "load_tool",
                side_effect=lambda path: demo if path.name == "phase_g_demo.py" else self.verifier,
            ),
        ):
            return runner.verify_browser(
                self.value if value is None else value,
                root=self.root,
                run_id=RUN,
                real=True,
                artifact=self.artifact,
                profile="provider_real",
            )

    def test_full_provider_fixture_requires_fresh_sdk_and_raw_otlp_without_local_engine_claims(
        self,
    ):
        self.assertEqual(self.verify(), 2)
        for extra in (
            "model_setup",
            "engine_inference",
            "engine_provenance",
            "model_manifest_sha256",
        ):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.verify({**self.value, extra: {}})
        self.assertFalse((self.artifact / "playwright.json").exists())

    def test_missing_or_stale_real_stats_sdk_or_trace_cannot_pass(self):
        for filename in (
            "playwright-stats.json",
            "provider-sdk-records.json",
            "provider-trace-conversation-agent.json",
        ):
            path = self.artifact / filename
            raw = path.read_bytes()
            path.unlink()
            with self.subTest(missing=filename), self.assertRaises((ValueError, OSError)):
                self.verify()
            path.write_bytes(raw)
        self.write(
            "provider-sdk-records.json",
            {
                "schema_version": 1,
                "run_id": "b" * 32,
                "mode": "provider_real",
                "records": records(),
            },
        )
        with self.assertRaises(ValueError):
            self.verify()

    def test_bad_provider_labels_resources_cohort_versions_or_held_dependency_do_not_pass(self):
        for field, value in (
            ("mode", "local_real"),
            ("gate_source_hashes", {}),
            ("declaration_sha256", "stale"),
            ("resources", {}),
            ("runtime_versions", {}),
            ("slow_postgres", {}),
            ("held_supplier", {}),
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.verify({**self.value, field: value})
        for field, change in (
            ("cohort", {"lost_accepted": 1}),
            ("provider_inference", {"external_resources": "measured"}),
            ("provider_inference", {"actual_sdk_usage": False}),
        ):
            bad = copy.deepcopy(self.value)
            bad[field].update(change)
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.verify(bad)
        bad = copy.deepcopy(self.value)
        bad["traces"]["conversation-agent"]["model_providers"]["gpt-5.4-mini"] = "elevenlabs"
        with self.assertRaises(ValueError):
            self.verify(bad)

    def test_real_runner_stats_bind_invocation_and_reject_skips_or_forged_counts(self):
        original = {
            "schema_version": 1,
            "run_id": RUN,
            "stats": {"expected": 2, "unexpected": 0, "skipped": 0, "flaky": 0},
        }
        for change in (
            {"schema_version": True},
            {"run_id": "b" * 32},
            {"stats": {"expected": 0, "unexpected": 0, "skipped": 0, "flaky": 0}},
            {"stats": {"expected": 2, "unexpected": 0, "skipped": 1, "flaky": 0}},
            {"transcript": "SYNTHETIC-PRIVATE"},
        ):
            self.write("playwright-stats.json", {**original, **change})
            with self.subTest(fields=list(change)), self.assertRaises(ValueError):
                self.verify()
        self.write("playwright-stats.json", original)

    def test_raw_sdk_or_trace_failure_is_reverified_not_trusted_summary(self):
        payload = {
            "schema_version": 1,
            "run_id": RUN,
            "mode": "provider_real",
            "records": records(),
        }
        payload["records"][0]["values"]["trace_failed"] = 1
        self.write("provider-sdk-records.json", payload)
        with self.assertRaises(ValueError):
            self.verify()
        payload["records"][0]["values"]["trace_failed"] = 0
        self.write("provider-sdk-records.json", payload)
        self.write("provider-trace-conversation-agent.json", {"result": {"resourceSpans": []}})
        with self.assertRaises(ValueError):
            self.verify()


class CleanupReconciliationTests(unittest.TestCase):
    def scenario(self, *, lost=False, present=False, foreign=False):
        now = [0.0]
        removed = [False]
        identifier = "1" * 64
        other = "2" * 64
        name = "p1-g-" + RUN + "-native"
        label = "io.livekit-ecosystem.demo=" + RUN
        calls = []

        def control(argv, timeout):
            calls.append(argv)
            if argv[1] == "inspect":
                return json.dumps(
                    {"name": "/" + name, "labels": {"io.livekit-ecosystem.demo": RUN}}
                )
            if argv[1] == "rm":
                removed[0] = True
                if lost:
                    raise RuntimeError("SYNTHETIC-PRIVATE")
                return identifier
            if not removed[0]:
                return identifier
            if foreign and argv[-1].startswith("name="):
                return other
            return identifier if present else ""

        return name, label, control, lambda: now[0], lambda n: now.__setitem__(0, now[0] + n), calls

    def test_lost_remove_ack_requires_both_exact_id_and_name_absence(self):
        name, label, control, clock, pause, calls = self.scenario(lost=True)
        demo.remove_owned_container(name, label, control, clock=clock, pause=pause)
        self.assertEqual(sum(argv[1] == "rm" for argv in calls), 1)
        self.assertTrue(any(argv[-1].startswith("id=") for argv in calls))

    def test_present_or_foreign_replacement_never_becomes_success(self):
        for changes in ({"lost": True, "present": True}, {"lost": True, "foreign": True}):
            name, label, control, clock, pause, _ = self.scenario(**changes)
            with self.subTest(changes=changes), self.assertRaises((TimeoutError, ValueError)):
                demo.remove_owned_container(name, label, control, clock=clock, pause=pause)


if __name__ == "__main__":
    unittest.main()
