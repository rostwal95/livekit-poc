"""Synthetic provider lifecycle/data-isolation tests; never load user credentials."""

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("provider_setup_stack", ROOT / "local-setup/stack.py")
stack = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = stack
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


class PrivateDependencyError(stack.SetupError):
    def __str__(self):
        raise AssertionError("Dependency text must not be rendered")


class ProviderSetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve())
        self.addCleanup(self.temporary.cleanup)
        self.setup = Path(self.temporary.name) / "local-setup"
        self.setup.mkdir()
        (self.setup / "config").mkdir()
        (self.setup / ".env.example").write_text(
            "\n".join(f"{key}={value}" for key, value in DEFAULTS.items()) + "\n"
        )
        (self.setup / "images.env").write_text(
            "\n".join(
                f"{name}=example/service:1.2.3@sha256:{'a' * 64}"
                for name in sorted(stack.IMAGE_KEYS)
            )
            + "\n"
        )
        (self.setup / "config/livekit.yaml.tmpl").write_text(
            "rtc:\n  node_ip: {node_ip}\n  tcp_port: {tcp_port}\n  udp_port: {udp_port}\n"
        )
        (self.setup / "docker-compose.yaml").write_text("services: {}\n")
        shutil.copyfile(ROOT / "local-setup/provider_config.py", self.setup / "provider_config.py")
        shutil.copyfile(
            ROOT / "local-setup/docker-compose.providers.yaml",
            self.setup / "docker-compose.providers.yaml",
        )
        shutil.copyfile(
            ROOT / "local-setup/docker-compose.provider-ca.yaml",
            self.setup / "docker-compose.provider-ca.yaml",
        )
        stack.initialize(self.setup)
        self.path = self.setup / ".env.providers"
        self.keys = {
            key: "synthetic-" + key + "-$[literal]+-private-provider-sentinel"
            for key in sorted(stack.PROVIDER_KEYS)
        }

    def write(self, values=None):
        self.path.write_text(
            "\n".join(f"{key}={value}" for key, value in (values or self.keys).items()) + "\n"
        )
        self.path.chmod(0o600)

    def cli(self, action, *options):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            result = stack.main([action, *options], setup=self.setup)
        return result, json.loads(output.getvalue())

    def test_ca_option_rejects_other_actions_and_invalid_input_before_runtime(self):
        with (
            patch.object(stack, "run") as run,
            patch.object(stack, "assert_owned_containers") as owned,
        ):
            for action in ("init", "start", "start-business", "start-local-real", "stop-provider"):
                code, report = self.cli(action, "--provider-ca-bundle", "/missing/public.pem")
                self.assertEqual(2, code)
                self.assertNotIn("/missing", json.dumps(report))
            self.write()
            code, _ = self.cli("start-provider", "--provider-ca-bundle", "/missing/public.pem")
            self.assertEqual(2, code)
        run.assert_not_called()
        owned.assert_not_called()

    def test_ca_snapshot_is_public_exact_and_only_serving_selects_native_overlay(self):
        from types import SimpleNamespace

        self.write()
        raw = b"synthetic-public-CA-bytes"
        paths = []
        original = stack.provider_configuration

        def configuration(setup):
            module = original(setup)
            return SimpleNamespace(
                read_credentials=module.read_credentials,
                read_ca_bundle=lambda path: paths.append(path) or raw,
            )

        with (
            patch.object(stack, "provider_configuration", side_effect=configuration),
            patch.object(stack, "assert_owned_containers"),
            patch.object(stack, "run", return_value="ready") as run,
        ):
            code, report = self.cli(
                "start-provider", "--provider-ca-bundle", "/approved/public.pem"
            )
        self.assertEqual(0, code)
        self.assertNotIn("synthetic-public", json.dumps(report))
        build, preflight, serving = run.call_args_list
        for call in (build, preflight):
            self.assertNotIn("P1_PROVIDER_CA_SNAPSHOT", call.args[1])
            self.assertNotIn(str(self.setup / "docker-compose.provider-ca.yaml"), call.args[0])
        self.assertEqual([Path("/approved/public.pem")], paths)
        snapshot = Path(serving.args[1]["P1_PROVIDER_CA_SNAPSHOT"])
        self.assertEqual(self.setup / ".generated", snapshot.parent)
        self.assertEqual(raw, snapshot.read_bytes())
        self.assertEqual(0o644, snapshot.stat().st_mode & 0o777)
        self.assertIn(str(self.setup / "docker-compose.provider-ca.yaml"), serving.args[0])

    def test_start_keys_validate_before_ownership_commands_build_preflight_then_only_serving_has_keys(
        self,
    ):
        self.write()
        events = []

        def run(argv, values, *args, **kwargs):
            events.append((argv, dict(values)))
            return "ready"

        with (
            patch.object(
                stack, "assert_owned_containers", side_effect=lambda *_: events.append("owned")
            ),
            patch.object(stack, "run", side_effect=run),
        ):
            code, report = self.cli("start-provider")
        self.assertEqual(0, code)
        self.assertEqual("owned", events[0])
        build, preflight, serving = events[1:]
        self.assertEqual(["build", "control-api"], build[0][-2:])
        self.assertEqual("/app/local-setup/scripts/business_preflight.py", preflight[0][-1])
        for argv, values in (build, preflight):
            self.assertTrue(stack.PROVIDER_KEYS.isdisjoint(values))
            self.assertNotIn(str(self.setup / "docker-compose.providers.yaml"), argv)
        self.assertIn(str(self.setup / "docker-compose.providers.yaml"), serving[0])
        self.assertEqual(self.keys, {key: serving[1][key] for key in stack.PROVIDER_KEYS})
        self.assertEqual(
            ["jaeger", "p1-worker", "conversation-agent", "control-api"], serving[0][-4:]
        )
        self.assertEqual("provider_real", serving[1]["P1_CONVERSATION_INFERENCE"])
        self.assertEqual("provider_real", serving[1]["P1_TRACE_MODE"])
        for argv, _ in (build, preflight, serving):
            for value in self.keys.values():
                self.assertNotIn(value, " ".join(argv))
            self.assertNotIn("--env-file " + str(self.path), " ".join(argv))
        self.assertFalse(report["schemaActivation"])
        self.assertFalse(report["fixtureInitialization"])

    def test_missing_incomplete_invalid_or_public_key_file_stops_before_any_docker_probe(self):
        variants = [
            None,
            {key: "" for key in self.keys},
            {**self.keys, "OPENAI_API_KEY": "short"},
            self.keys,
        ]
        for values in variants:
            if self.path.exists():
                self.path.unlink()
            if values is not None:
                self.write(values)
            if values is self.keys:
                self.path.chmod(0o644)
            with (
                self.subTest(shape="missing" if values is None else "present"),
                patch.object(stack, "assert_owned_containers") as owned,
                patch.object(stack, "run") as run,
            ):
                code, report = self.cli("start-provider")
                self.assertEqual(2, code)
                self.assertEqual("provider_start_failed", report["code"])
                owned.assert_not_called()
                run.assert_not_called()
                for value in self.keys.values():
                    self.assertNotIn(value, json.dumps(report))

    def test_foreign_ownership_prevents_mutation_even_after_complete_key_validation(self):
        self.write()
        before = self.path.read_bytes()
        with (
            patch.object(
                stack,
                "assert_owned_containers",
                side_effect=PrivateDependencyError("private-value"),
            ),
            patch.object(stack, "run") as run,
        ):
            code, report = self.cli("start-provider")
        self.assertEqual((2, "provider_start_failed"), (code, report["code"]))
        run.assert_not_called()
        self.assertEqual(before, self.path.read_bytes())

    def test_preflight_failure_never_adds_override_or_injects_provider_keys(self):
        self.write()
        with (
            patch.object(stack, "assert_owned_containers"),
            patch.object(
                stack,
                "run",
                side_effect=["built", PrivateDependencyError("private-provider-sentinel")],
            ) as run,
        ):
            code, report = self.cli("start-provider")
        self.assertEqual((2, "provider_start_failed"), (code, report["code"]))
        self.assertEqual(2, run.call_count)
        for call in run.call_args_list:
            self.assertTrue(stack.PROVIDER_KEYS.isdisjoint(call.args[1]))
            self.assertNotIn("up", call.args[0])

    def test_stop_does_not_read_or_change_populated_user_keys_and_removes_stopped_native(self):
        self.write()
        before = self.path.read_bytes()
        inode = self.path.stat().st_ino
        with (
            patch.object(
                stack,
                "provider_configuration",
                side_effect=AssertionError("must not read provider file"),
            ),
            patch.object(stack, "assert_owned_containers"),
            patch.object(stack, "run", return_value="stopped") as run,
        ):
            code, report = self.cli("stop-provider")
        self.assertEqual(0, code)
        self.assertEqual("scripted", report["inferenceMode"])
        stop, revert, remove = run.call_args_list
        self.assertEqual(["stop", "-t", "35", "conversation-agent", "p1-worker"], stop.args[0][-5:])
        self.assertEqual("control-api", revert.args[0][-1])
        self.assertEqual("0", revert.args[1]["P1_BUSINESS_ENABLED"])
        self.assertEqual(["rm", "--force", "conversation-agent"], remove.args[0][-3:])
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(inode, self.path.stat().st_ino)
        for call in run.call_args_list:
            self.assertTrue(stack.PROVIDER_KEYS.isdisjoint(call.args[1]))
            self.assertNotIn("--volumes", call.args[0])
            self.assertNotIn("down", call.args[0])
            self.assertNotIn(str(self.setup / "docker-compose.providers.yaml"), call.args[0])

    def test_stop_without_any_provider_file_still_drains_reverts_and_removes(self):
        self.assertFalse(self.path.exists())
        with (
            patch.object(
                stack, "provider_configuration", side_effect=AssertionError("must not read")
            ),
            patch.object(stack, "assert_owned_containers"),
            patch.object(stack, "run", return_value="stopped") as run,
        ):
            self.assertEqual(0, self.cli("stop-provider")[0])
        self.assertEqual(3, run.call_count)
        self.assertFalse(self.path.exists())

    def test_api_reversion_failure_still_removes_container_and_cli_never_formats_private_error(
        self,
    ):
        with (
            patch.object(stack, "assert_owned_containers"),
            patch.object(
                stack,
                "run",
                side_effect=["stopped", PrivateDependencyError("private-key-body"), "removed"],
            ) as run,
        ):
            code, report = self.cli("stop-provider")
        self.assertEqual(3, run.call_count)
        self.assertEqual(["rm", "--force", "conversation-agent"], run.call_args.args[0][-3:])
        self.assertEqual(
            {"status": "failed", "code": "provider_stop_failed", "cleanup_incomplete": False},
            report,
        )
        self.assertEqual(2, code)

    def test_stop_and_cleanup_failures_preserve_original_cause_and_report_fixed_cleanup_flag(self):
        first = PrivateDependencyError("first-private")
        second = PrivateDependencyError("second-private")
        with (
            patch.object(stack, "run", side_effect=[first, "api-restored", second]) as run,
            self.assertRaises(stack.ProviderStopError) as caught,
        ):
            stack.stop_provider(["docker", "compose"], stack.load_settings(self.setup), self.setup)
        self.assertIs(first, caught.exception.__cause__)
        self.assertTrue(caught.exception.cleanup_incomplete)
        self.assertEqual(3, run.call_count)
        with (
            patch.object(stack, "assert_owned_containers"),
            patch.object(stack, "run", side_effect=[first, "api-restored", second]),
        ):
            code, report = self.cli("stop-provider")
        self.assertEqual(2, code)
        self.assertEqual(
            {"status": "failed", "code": "provider_stop_failed", "cleanup_incomplete": True}, report
        )

    def test_stop_refuses_foreign_project_before_commands_with_no_raw_dependency_details(self):
        with (
            patch.object(
                stack,
                "assert_owned_containers",
                side_effect=PrivateDependencyError("private-owner-body"),
            ),
            patch.object(stack, "run") as run,
        ):
            code, report = self.cli("stop-provider")
        run.assert_not_called()
        self.assertEqual(2, code)
        self.assertEqual("provider_stop_failed", report["code"])
        self.assertTrue(report["cleanup_incomplete"])

    def test_init_and_check_report_only_presence_without_starting_or_validating_remote_providers(
        self,
    ):
        with patch.object(stack, "run") as run:
            code, report = self.cli("init-providers")
            self.assertEqual(0, code)
            self.assertFalse(any(report["present"].values()))
            self.assertFalse(report["providerCalls"])
            self.assertEqual(2, self.cli("check-providers")[0])
            run.assert_not_called()
            self.write()
            before = self.path.read_bytes()
            inode = self.path.stat().st_ino
            code, report = self.cli("init-providers")
            self.assertEqual(0, code)
            self.assertFalse(report["created"])
            self.assertTrue(all(report["present"].values()))
            self.assertEqual(before, self.path.read_bytes())
            self.assertEqual(inode, self.path.stat().st_ino)
            for value in self.keys.values():
                self.assertNotIn(value, json.dumps(report))

    def test_normal_start_and_business_start_cannot_inherit_cloud_mode_or_provider_variables(self):
        ambient = {
            key: "ambient-private-provider"
            for key in (
                *stack.PROVIDER_KEYS,
                "OPENAI_BASE_URL",
                "DEEPGRAM_SECRET",
                "ELEVENLABS_VOICE_ID",
                "ELEVEN_EXTRA",
                "P1_CONVERSATION_INFERENCE",
            )
        }
        ambient["P1_CONVERSATION_INFERENCE"] = "provider_real"
        with (
            patch.dict(os.environ, ambient),
            patch.object(
                stack,
                "provider_configuration",
                side_effect=AssertionError("ordinary action cannot read providers"),
            ),
            patch.object(stack, "doctor"),
            patch.object(stack, "assert_owned_containers"),
            patch.object(stack, "run", return_value="ready") as run,
        ):
            self.assertTrue(
                stack.PROVIDER_KEYS.isdisjoint(
                    stack.child_environment(stack.load_settings(self.setup))
                )
            )
            for action in ("start", "start-business"):
                self.assertEqual(0, self.cli(action)[0])
                self.assertTrue(stack.PROVIDER_KEYS.isdisjoint(run.call_args.args[1]))
                self.assertNotIn(
                    str(self.setup / "docker-compose.providers.yaml"), run.call_args.args[0]
                )
            self.assertEqual("scripted", run.call_args.args[1]["P1_CONVERSATION_INFERENCE"])
            self.assertNotIn(
                "ambient-private-provider",
                json.dumps(stack.child_environment(stack.load_settings(self.setup))),
            )

    def test_literal_key_characters_are_process_data_not_shell_or_recursive_substitution(self):
        marker = self.setup / "should-never-exist"
        literal = "$(touch${IFS}" + str(marker) + ")-$HOME-`id`-'quoted\""
        values = {key: literal for key in self.keys}
        self.write(values)
        loaded = stack.provider_values(self.setup, complete=True)
        self.assertEqual(values, loaded)
        expected = hashlib.sha256(literal.encode()).hexdigest()
        code = (
            "import hashlib,os;assert hashlib.sha256(os.environ['OPENAI_API_KEY'].encode()).hexdigest()=="
            + repr(expected)
            + ";print('literal-preserved')"
        )
        observed = stack.run(
            [sys.executable, "-c", code], {**stack.load_settings(self.setup), **loaded}, self.setup
        )
        self.assertEqual("literal-preserved\n", observed)
        self.assertFalse(marker.exists())

    def test_all_three_provider_credentials_are_redacted_even_across_tail_cutoff(self):
        values = {**stack.load_settings(self.setup), **self.keys}
        for key in stack.PROVIDER_KEYS:
            for error in (False, True):
                code = (
                    "import os,sys;value=os.environ[sys.argv[1]].encode();os.write("
                    + ("2" if error else "1")
                    + ",b'p'*10000+value+b'x'*7990);sys.exit("
                    + ("9" if error else "0")
                    + ")"
                )
                argv = [sys.executable, "-c", code, key]
                if error:
                    with self.assertRaises(stack.SetupError) as caught:
                        stack.run(argv, values, self.setup)
                    output = str(caught.exception)
                else:
                    output = stack.run(argv, values, self.setup)
                self.assertIn("[redacted]", output)
                self.assertNotIn(values[key], output)
                self.assertNotIn(values[key][-12:], output)
        self.assertEqual(6, len(stack.SECRET_KEYS))
        self.assertEqual(9, len(stack.REDACTED_SECRET_KEYS))


class ProviderOverrideTests(unittest.TestCase):
    def test_ca_override_mounts_only_public_native_trust_readonly(self):
        text = (ROOT / "local-setup/docker-compose.provider-ca.yaml").read_text()
        self.assertEqual(
            ["conversation-agent"], re.findall(r"^  ([a-z][a-z0-9-]+):$", text, re.MULTILINE)
        )
        self.assertIn("target: /etc/ssl/certs/ca-certificates.crt", text)
        self.assertIn("read_only: true", text)
        for token in (
            "environment:",
            "build:",
            "args:",
            "env_file:",
            "verify=False",
            "SSL_CERT_FILE",
        ):
            self.assertNotIn(token, text)

    def test_override_injects_exact_three_native_environment_fields_only_without_build_or_file_mounts(
        self,
    ):
        text = (ROOT / "local-setup/docker-compose.providers.yaml").read_text()
        self.assertEqual(
            ["conversation-agent"], re.findall(r"^  ([a-z][a-z0-9-]+):$", text, re.MULTILINE)
        )
        fields = re.findall(
            r"^      ([A-Z][A-Z0-9_]*): \$\{([A-Z][A-Z0-9_]*):\?[^}]+\}$", text, re.MULTILINE
        )
        self.assertEqual(stack.PROVIDER_KEYS, {left for left, right in fields})
        self.assertTrue(all(left == right for left, right in fields))
        self.assertEqual(3, len(fields))
        for forbidden in (
            "build:",
            "args:",
            "env_file:",
            "volumes:",
            "ports:",
            "control-api:",
            "p1-worker:",
            "jaeger:",
            "image:",
            ".env.providers",
        ):
            self.assertNotIn(forbidden, text)
        self.assertIn("**/.env.*", (ROOT / ".dockerignore").read_text())


if __name__ == "__main__":
    unittest.main()
