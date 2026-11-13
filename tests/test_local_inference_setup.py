"""Offline checks for explicit cached local inference and its isolated topology."""

import contextlib
import importlib.util
import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "local_inference_stack", ROOT / "local-setup/stack.py"
)
stack = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stack)

DEFAULTS = {
    "BIND_ADDRESS": "127.0.0.1",
    "LIVEKIT_NODE_IP": "127.0.0.1",
    "UI_PORT": "13000",
    "API_PORT": "18080",
    "LIVEKIT_HTTP_PORT": "17880",
    "LIVEKIT_TCP_PORT": "17881",
    "LIVEKIT_UDP_PORT": "17882",
    "POSTGRES_PORT": "15432",
    "JAEGER_UI_PORT": "26686",
}
VERIFIED = {
    "status": "verified",
    "profile": "p1-local-real-v1",
    "files": 10,
    "model_bytes": 2708841240,
    "runtime_downloads": False,
}


class LocalInferenceSetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.setup = Path(self.temporary.name) / "local-setup"
        self.setup.mkdir()
        self.setup = self.setup.resolve()
        for name in ("config", "scripts", "models"):
            (self.setup / name).mkdir()
        (self.setup / ".env.example").write_text(
            "\n".join(f"{key}={value}" for key, value in DEFAULTS.items()) + "\n"
        )
        (self.setup / "images.env").write_text(
            "\n".join(
                f"{key}=example/service:1.2.3@sha256:{'a' * 64}" for key in sorted(stack.IMAGE_KEYS)
            )
            + "\n"
        )
        (self.setup / "config/livekit.yaml.tmpl").write_text(
            "rtc:\n  node_ip: {node_ip}\n  tcp_port: {tcp_port}\n  udp_port: {udp_port}\n"
        )
        (self.setup / "docker-compose.yaml").write_text("services: {}\n")
        (self.setup / "scripts/local_models.py").write_text("# fixture\n")
        (self.setup / "models/local-model-manifest.json").write_text("{}\n")
        stack.initialize(self.setup)

    def cli(self, action):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = stack.main([action], setup=self.setup)
        return result, json.loads(output.getvalue())

    def fake_run(self, argv, *_args, **_kwargs):
        return (
            json.dumps(VERIFIED) if str(self.setup / "scripts/local_models.py") in argv else "ready"
        )

    def test_only_fetch_action_passes_fetch_and_neither_model_action_invokes_docker(self):
        for action, fetch in (("models-fetch", True), ("models-verify", False)):
            with (
                self.subTest(action=action),
                patch.object(stack, "run", side_effect=self.fake_run) as run,
            ):
                code, result = self.cli(action)
                self.assertEqual(0, code)
                self.assertEqual(VERIFIED, result)
                run.assert_called_once()
                argv, _, setup, timeout = run.call_args.args
                self.assertEqual(stack.sys.executable, argv[0])
                self.assertEqual(fetch, "--fetch" in argv)
                self.assertEqual(self.setup, setup)
                self.assertEqual(1805, timeout)
                self.assertNotIn("docker", argv)

    def test_model_start_verifies_before_build_and_exposes_no_ports_or_download_action(self):
        with (
            patch.object(stack, "assert_owned_containers") as owned,
            patch.object(stack, "run", side_effect=self.fake_run) as run,
        ):
            code, result = self.cli("start-models")
        self.assertEqual(0, code)
        owned.assert_called_once()
        verify, image_pull, build, start = run.call_args_list
        self.assertIn("local_models.py", " ".join(verify.args[0]))
        self.assertNotIn("--fetch", verify.args[0])
        self.assertEqual(["pull", "--policy", "missing", "p1-llm"], image_pull.args[0][-4:])
        self.assertEqual(1800, image_pull.args[3])
        self.assertEqual(["build", "p1-stt", "p1-tts"], build.args[0][-3:])
        self.assertEqual(list(stack.MODEL_SERVICES), start.args[0][-3:])
        self.assertIn("--no-deps", start.args[0])
        self.assertIn("--wait", start.args[0])
        self.assertFalse(result["schemaActivation"])
        self.assertFalse(result["fixtureInitialization"])
        self.assertFalse(result["runtimeDownloads"])

    def test_initial_image_transfer_failure_does_not_start_engines_or_fetch_weights(self):
        with (
            patch.object(stack, "assert_owned_containers"),
            patch.object(
                stack,
                "run",
                side_effect=[
                    json.dumps(VERIFIED),
                    stack.SetupError("Image transfer deadline exceeded"),
                ],
            ) as run,
        ):
            code, result = self.cli("start-models")
        self.assertEqual(2, code)
        self.assertEqual(2, run.call_count)
        self.assertFalse(
            any("up" in call.args[0] or "--fetch" in call.args[0] for call in run.call_args_list)
        )
        self.assertEqual("failed", result["status"])

    def test_cache_miss_stops_before_any_build_or_service_start_without_echoing_dependency_text(
        self,
    ):
        for action in ("start-models", "start-local-real"):
            with (
                self.subTest(action=action),
                patch.object(stack, "assert_owned_containers"),
                patch.object(stack, "run", side_effect=stack.SetupError("private-sentinel")) as run,
            ):
                code, result = self.cli(action)
                self.assertEqual(2, code)
                self.assertEqual(1, run.call_count)
                self.assertNotIn("private-sentinel", json.dumps(result))
                self.assertNotIn("--fetch", run.call_args.args[0])

    def test_local_real_start_runs_cache_existing_authority_preflight_models_then_consumers(self):
        with (
            patch.object(stack, "assert_owned_containers"),
            patch.object(stack, "run", side_effect=self.fake_run) as run,
        ):
            code, result = self.cli("start-local-real")
        self.assertEqual(0, code)
        self.assertEqual("local_real", result["inferenceMode"])
        self.assertEqual(7, run.call_count)
        verify, shared_build, preflight, image_pull, model_build, model_start, consumers = (
            run.call_args_list
        )
        self.assertIn("local_models.py", " ".join(verify.args[0]))
        self.assertEqual(["build", "control-api"], shared_build.args[0][-2:])
        self.assertEqual("/app/local-setup/scripts/business_preflight.py", preflight.args[0][-1])
        self.assertEqual(["pull", "--policy", "missing", "p1-llm"], image_pull.args[0][-4:])
        self.assertEqual(["build", "p1-stt", "p1-tts"], model_build.args[0][-3:])
        self.assertEqual(list(stack.MODEL_SERVICES), model_start.args[0][-3:])
        self.assertEqual(
            ["jaeger", "p1-worker", "conversation-agent", "control-api"], consumers.args[0][-4:]
        )
        for call in run.call_args_list:
            self.assertEqual("local_real", call.args[1]["P1_CONVERSATION_INFERENCE"])
            self.assertEqual("local_real", call.args[1]["P1_TRACE_MODE"])
            self.assertNotIn("init-fixtures", call.args[0])
            self.assertNotIn("--fetch", call.args[0])
        self.assertFalse(result["schemaActivation"])
        self.assertFalse(result["fixtureInitialization"])

    def test_v4_preflight_failure_never_starts_engines_or_replaces_api(self):
        with (
            patch.object(stack, "assert_owned_containers"),
            patch.object(
                stack,
                "run",
                side_effect=[json.dumps(VERIFIED), "built", stack.SetupError("ACTIVE v4 required")],
            ) as run,
        ):
            code, _ = self.cli("start-local-real")
        self.assertEqual(2, code)
        self.assertEqual(3, run.call_count)
        self.assertTrue(all("up" not in call.args[0] for call in run.call_args_list))

    def test_stop_local_real_drains_native_then_disables_api_then_stops_engines_retaining_cache(
        self,
    ):
        with (
            patch.object(stack, "assert_owned_containers"),
            patch.object(stack, "run", return_value="stopped") as run,
        ):
            code, result = self.cli("stop-local-real")
        self.assertEqual(0, code)
        stop, api, engines = run.call_args_list
        self.assertEqual(["stop", "-t", "35", "conversation-agent", "p1-worker"], stop.args[0][-5:])
        self.assertEqual("0", api.args[1]["P1_BUSINESS_ENABLED"])
        self.assertEqual("scripted", api.args[1]["P1_CONVERSATION_INFERENCE"])
        self.assertEqual(["stop", "-t", "15", *stack.MODEL_SERVICES], engines.args[0][-6:])
        self.assertEqual("scripted", result["inferenceMode"])
        for call in run.call_args_list:
            self.assertNotIn("--volumes", call.args[0])
            self.assertNotIn("down", call.args[0])

    def test_all_runtime_model_actions_refuse_other_checkout_before_any_command(self):
        for action in ("start-models", "stop-models", "start-local-real", "stop-local-real"):
            with (
                self.subTest(action=action),
                patch.object(
                    stack,
                    "assert_owned_containers",
                    side_effect=stack.SetupError("Foreign checkout"),
                ),
                patch.object(stack, "run") as run,
            ):
                self.assertEqual(2, self.cli(action)[0])
                run.assert_not_called()

    def test_ambient_mode_trace_model_endpoints_cannot_activate_ordinary_or_business_start(self):
        injected = {
            "P1_CONVERSATION_INFERENCE": "local_real",
            "P1_TRACE_MODE": "local_real",
            "P1_TRACE_ENDPOINT": "http://private-sentinel",
            "P1_MODELS_CACHE": "/private-sentinel",
        }
        values = stack.load_settings(self.setup)
        with patch.dict(os.environ, injected):
            environment = stack.child_environment(values)
            for key in injected:
                self.assertNotIn(key, environment)
            with (
                patch.object(stack, "assert_owned_containers"),
                patch.object(stack, "run", return_value="ready") as run,
            ):
                self.assertEqual(0, self.cli("start-business")[0])
            for call in run.call_args_list:
                self.assertEqual("scripted", call.args[1]["P1_CONVERSATION_INFERENCE"])
                self.assertEqual("scripted", call.args[1]["P1_TRACE_MODE"])
                self.assertNotIn("p1-models", call.args[0])
        with self.assertRaises(stack.SetupError):
            stack.validate_config({**DEFAULTS, "P1_CONVERSATION_INFERENCE": "local_real"})

    def test_missing_or_symlinked_helper_manifest_and_malformed_helper_proof_fail_closed(self):
        values = stack.load_settings(self.setup)
        for body in (
            "{}",
            "[]",
            "private-sentinel",
            json.dumps({**VERIFIED, "runtime_downloads": True}),
            json.dumps({**VERIFIED, "files": True}),
            json.dumps({**VERIFIED, "model_bytes": 2**64}),
        ):
            with (
                self.subTest(body=body),
                patch.object(stack, "run", return_value=body),
                self.assertRaises(stack.SetupError) as caught,
            ):
                stack.prepare_models(self.setup, values)
            self.assertNotIn("private-sentinel", str(caught.exception))
        helper = self.setup / "scripts/local_models.py"
        helper.unlink()
        helper.symlink_to(self.setup / "models/local-model-manifest.json")
        with patch.object(stack, "run") as run, self.assertRaises(stack.SetupError):
            stack.prepare_models(self.setup, values)
        run.assert_not_called()

    def test_engine_stop_does_not_verify_or_fetch_and_global_stop_includes_model_profile(self):
        with (
            patch.object(stack, "assert_owned_containers"),
            patch.object(stack, "run", return_value="") as run,
        ):
            self.assertEqual(0, self.cli("stop-models")[0])
            run.assert_called_once()
            self.assertEqual(
                ["stop", "-t", "15", *stack.MODEL_SERVICES], run.call_args.args[0][-6:]
            )
            self.assertEqual(0, self.cli("stop")[0])
            self.assertIn("p1-models", run.call_args.args[0])
            self.assertNotIn("--volumes", run.call_args.args[0])


class LocalInferenceTopologyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compose = (ROOT / "local-setup/docker-compose.yaml").read_text()
        cls.services = dict(
            re.findall(
                r"^  ([a-z][a-z0-9-]+):\n(.*?)(?=^  [a-z][a-z0-9-]+:|^networks:)",
                cls.compose,
                re.MULTILINE | re.DOTALL,
            )
        )

    def test_engine_private_network_readonly_existing_cache_and_declared_caps(self):
        for name, memory, cpu in (
            ("p1-llm", "4g", "4.0"),
            ("p1-stt", "1g", "4.0"),
            ("p1-tts", "512m", "2.0"),
        ):
            service = self.services[name]
            with self.subTest(service=name):
                for required in (
                    "<<: *runtime",
                    "profiles: [p1-models]",
                    'user: "10001:10001"',
                    "networks: [inference]",
                    "read_only: true",
                    "source: ./.local/models",
                    "target: /models",
                    "create_host_path: false",
                    "size=64m",
                    "pids_limit: 128",
                    "mem_limit: " + memory,
                    "cpus: " + cpu,
                ):
                    self.assertIn(required, service)
                for forbidden in (
                    "ports:",
                    "network_mode:",
                    "privileged:",
                    "LOCAL_ACCESS_TOKEN",
                    "POSTGRES_",
                    "LIVEKIT_",
                    "docker.sock",
                    "P1_MODELS_CACHE",
                    "--fetch",
                ):
                    self.assertNotIn(forbidden, service)
        self.assertIn("  inference:\n    driver: bridge\n    internal: true", self.compose)
        self.assertIn("networks: [lab, inference]", self.services["conversation-agent"])
        for name, service in self.services.items():
            if name not in {*stack.MODEL_SERVICES, "conversation-agent"}:
                self.assertNotIn("inference]", service)
        runtime = self.compose.split("x-python:", 1)[0]
        for invariant in (
            "init: true",
            "no-new-privileges:true",
            "- ALL",
            "max-size: 10m",
            'max-file: "3"',
        ):
            self.assertIn(invariant, runtime)

    def test_pinned_engine_inputs_and_ollama_no_cloud_finite_queue_context(self):
        llm = self.services["p1-llm"]
        self.assertIn(
            "image: ollama/ollama:0.40.15@sha256:55d6d58fce77338d8b626abbbbec63b79deeb24db3fd67b8a99951a84083552f",
            llm,
        )
        for line in (
            'OLLAMA_MAX_QUEUE: "1"',
            'OLLAMA_NUM_PARALLEL: "1"',
            'OLLAMA_MAX_LOADED_MODELS: "1"',
            'OLLAMA_CONTEXT_LENGTH: "2048"',
            'OLLAMA_NO_CLOUD: "1"',
            "OLLAMA_KEEP_ALIVE: 60s",
            "OLLAMA_MODELS: /models/ollama",
            "HOME: /tmp",
        ):
            self.assertIn(line, llm)
        for name, dockerfile in (("p1-stt", "whisper"), ("p1-tts", "piper")):
            self.assertIn(
                "dockerfile: local-setup/docker/" + dockerfile + ".Dockerfile", self.services[name]
            )
            self.assertIn(
                "PYTHON_IMAGE: ${PYTHON_IMAGE:?Pinned images.env is required}", self.services[name]
            )

    def test_explicit_modes_default_scripted_and_native_keeps_no_model_or_operator_volume(self):
        for name in ("control-api", "conversation-agent"):
            self.assertIn(
                "P1_CONVERSATION_INFERENCE: ${P1_CONVERSATION_INFERENCE:-scripted}",
                self.services[name],
            )
        for name in ("control-api", "conversation-agent", "p1-worker"):
            self.assertIn("P1_TRACE_MODE: ${P1_TRACE_MODE:-scripted}", self.services[name])
        native = self.services["conversation-agent"]
        self.assertNotIn("volumes:", native)
        self.assertNotIn("LOCAL_ACCESS_TOKEN", native)


if __name__ == "__main__":
    unittest.main()
