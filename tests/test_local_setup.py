"""Deterministic local-environment and lifecycle guards; no Docker daemon used."""

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

SPEC = importlib.util.spec_from_file_location(
    "local_stack", Path(__file__).resolve().parents[1] / "local-setup/stack.py"
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


class LocalSetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
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
        (self.setup / "scripts").mkdir()
        (self.setup / "scripts/smoke.py").write_text("# fixture\n")
        stack.initialize(self.setup)

    def cli(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = stack.main(list(args), setup=self.setup)
        return result, output.getvalue()

    def test_init_preserves_secrets_and_uses_private_permissions(self):
        path = self.setup / ".secrets.env"
        before = path.read_bytes()
        stack.initialize(self.setup)
        self.assertEqual(before, path.read_bytes())
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        values = stack.load_settings(self.setup)
        self.assertGreaterEqual(len(values["LOCAL_ACCESS_TOKEN"]), 32)
        rendered = (self.setup / ".generated/livekit.yaml").read_text()
        self.assertIn("17881", rendered)
        self.assertNotIn(values["LIVEKIT_API_SECRET"], rendered)

    def test_admin_and_runtime_database_credentials_are_independent(self):
        values = stack.load_settings(self.setup)
        self.assertEqual(
            len({values[name] for name in stack.SECRET_KEYS - {"LIVEKIT_API_KEY"}}),
            len(stack.SECRET_KEYS) - 1,
        )
        for name in stack.SECRET_KEYS - {"LIVEKIT_API_KEY"}:
            self.assertRegex(values[name], r"^[A-Za-z0-9_-]{32,128}$")

    def test_unsafe_secret_bytes_are_rejected_without_echoing_value(self):
        path = self.setup / ".secrets.env"
        values = stack.parse_env(path)
        for unsafe in ("a" * 31, "a" * 129, "a" * 32 + "'", "a" * 32 + "$", "a" * 32 + " "):
            with self.subTest(length=len(unsafe)):
                with self.assertRaises(stack.SetupError) as caught:
                    stack.validate_secrets(path, {**values, "POSTGRES_ADMIN_PASSWORD": unsafe})
                self.assertNotIn(unsafe, str(caught.exception))
                self.assertIn("POSTGRES_ADMIN_PASSWORD", str(caught.exception))

    def test_dotenv_is_data_and_never_executes_substitution(self):
        marker = self.setup / "executed"
        path = self.setup / "fixture.env"
        path.write_text(f"VALUE='$(touch {marker})'\n")
        self.assertEqual(stack.parse_env(path)["VALUE"], f"$(touch {marker})")
        self.assertFalse(marker.exists())

    def test_dotenv_rejects_duplicate_keys_and_invalid_lines(self):
        path = self.setup / "bad.env"
        for content in ("A=one\nA=two\n", "export A=one\n", "A='unclosed\n"):
            with self.subTest(content=content):
                path.write_text(content)
                with self.assertRaises(stack.SetupError):
                    stack.parse_env(path)

    def test_config_rejects_unknown_ports_addresses_and_duplicate_bindings(self):
        variants = [
            {**DEFAULTS, "BAD_SETTING": "one"},
            {**DEFAULTS, "UI_PORT": "80"},
            {**DEFAULTS, "UI_PORT": "$(echo 13000)"},
            {**DEFAULTS, "UI_PORT": DEFAULTS["API_PORT"]},
            {**DEFAULTS, "BIND_ADDRESS": "0.0.0.0"},
            {**DEFAULTS, "BIND_ADDRESS": "127.0.0.2"},
            {**DEFAULTS, "POSTGRES_USER": "ignored_name"},
            {**DEFAULTS, "LIVEKIT_NODE_IP": "hostname.local"},
        ]
        for values in variants:
            with self.subTest(values=values), self.assertRaises(stack.SetupError):
                stack.validate_config(values)

    def test_optional_stack_project_scopes_compose_volumes_and_images(self):
        self.assertEqual(stack.configured_project(self.setup), stack.DEFAULT_PROJECT)
        env = self.setup / ".env"
        env.write_text(env.read_text() + "STACK_PROJECT=livekit-poc\n")
        values = stack.load_settings(self.setup)
        self.assertEqual(stack.configured_project(self.setup), "livekit-poc")
        self.assertEqual(stack.compose_arguments(self.setup)[3], "livekit-poc")
        self.assertEqual(stack.image_name("python", self.setup), "livekit-poc-python:local")
        with patch.object(stack, "run", return_value="") as run:
            stack.assert_owned_containers(self.setup, values)
        calls = [call.args[0] for call in run.call_args_list]
        self.assertEqual(calls[0][-1], "label=com.docker.compose.project=livekit-poc")
        self.assertEqual(
            [call[-1] for call in calls[1:]],
            [f"name=^livekit-poc_{name}$" for name in stack.VOLUMES],
        )

    def test_invalid_stack_project_fails_closed(self):
        for value in ("Livekit", "-poc", "ab", "a" * 42, "live_kit", "poc$(id)"):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(stack.SetupError, "STACK_PROJECT"),
            ):
                stack.validate_config({**DEFAULTS, "STACK_PROJECT": value})
        stack.validate_config({**DEFAULTS, "STACK_PROJECT": "livekit-poc"})

    def test_images_must_be_named_and_pinned(self):
        values = stack.parse_env(self.setup / "images.env")
        for replacement in (
            "example/service:latest",
            "example/service",
            "example/service:1;whoami",
        ):
            with self.subTest(replacement=replacement), self.assertRaises(stack.SetupError):
                stack.validate_images({**values, "LIVEKIT_IMAGE": replacement})
        with self.assertRaises(stack.SetupError):
            stack.validate_images({**values, "TYPO_IMAGE": "example/service:1"})

    def test_image_digest_is_exact_and_mandatory(self):
        values = stack.parse_env(self.setup / "images.env")
        stack.validate_images(values)
        for replacement in (
            "example/service:1.2.3",
            "example/service@sha256:" + "a" * 64,
            "example/service:1.2.3@sha256:" + "a" * 63,
            "example/service:1.2.3@sha256:" + "z" * 64,
        ):
            with self.subTest(reference=replacement), self.assertRaises(stack.SetupError):
                stack.validate_images({**values, "LIVEKIT_IMAGE": replacement})

    def test_credentials_and_local_state_cannot_be_symlinks_or_public(self):
        path = self.setup / ".secrets.env"
        values = stack.parse_env(path)
        path.chmod(0o644)
        with self.assertRaises(stack.SetupError):
            stack.validate_secrets(path, values)
        path.chmod(0o600)
        env = self.setup / ".env"
        env.unlink()
        env.symlink_to(self.setup / ".env.example")
        with self.assertRaises(stack.SetupError):
            stack.initialize(self.setup)

    def test_compose_argv_env_precedence_and_profile_are_explicit(self):
        values = stack.load_settings(self.setup)
        argv = stack.compose_arguments(self.setup, True)
        self.assertEqual(argv[:4], ["docker", "compose", "--project-name", stack.DEFAULT_PROJECT])
        indices = [index for index, value in enumerate(argv) if value == "--env-file"]
        self.assertEqual(
            [Path(argv[index + 1]).name for index in indices],
            ["images.env", ".env", ".secrets.env"],
        )
        self.assertEqual(argv[-2:], ["--profile", "observability"])
        with patch.dict(
            os.environ,
            {
                "LIVEKIT_API_SECRET": "foreign",
                "COMPOSE_FILE": "foreign.yaml",
                "LOCAL_UNMANAGED": "foreign",
                "LOCAL_STACK_OWNER": "foreign",
                "P1_POSTGRES_USER": "livekit_lab_admin",
                "P1_MIGRATION_PASSWORD": "foreign",
            },
        ):
            env = stack.child_environment(values)
        self.assertEqual(env["LIVEKIT_API_SECRET"], values["LIVEKIT_API_SECRET"])
        self.assertNotIn("COMPOSE_FILE", env)
        self.assertNotIn("LOCAL_UNMANAGED", env)
        self.assertNotIn("P1_POSTGRES_USER", env)
        self.assertNotIn("P1_MIGRATION_PASSWORD", env)
        self.assertEqual(
            env["LOCAL_STACK_OWNER"],
            hashlib.sha256(values["LOCAL_ACCESS_TOKEN"].encode()).hexdigest(),
        )
        self.assertNotEqual(env["LOCAL_STACK_OWNER"], values["LOCAL_ACCESS_TOKEN"])

    def test_stop_preserves_volumes_and_reset_requires_explicit_confirmation(self):
        with (
            patch.object(stack, "assert_owned_containers"),
            patch.object(stack, "run", return_value="") as run,
        ):
            code, _output = self.cli("stop")
        self.assertEqual(code, 0)
        self.assertNotIn("--volumes", run.call_args.args[0])
        with patch.object(stack, "run") as run:
            code, _output = self.cli("reset")
        self.assertEqual(code, 2)
        run.assert_not_called()
        with (
            patch.object(stack, "assert_owned_containers"),
            patch.object(stack, "run", return_value="") as run,
        ):
            code, _output = self.cli("reset", "--confirm", "RESET_LOCAL_STACK")
        self.assertEqual(code, 0)
        self.assertIn("--volumes", run.call_args.args[0])
        self.assertNotIn("prune", run.call_args.args[0])

    def test_foreign_checkout_container_blocks_mutation(self):
        values = stack.load_settings(self.setup)
        with (
            patch.object(stack, "run", side_effect=["container-id\n", "/different/checkout\n"]),
            self.assertRaises(stack.SetupError),
        ):
            stack.assert_owned_containers(self.setup, values)

    def test_absent_persistent_volumes_allow_a_fresh_start(self):
        values = stack.load_settings(self.setup)
        with patch.object(stack, "run", return_value="") as run:
            stack.assert_owned_containers(self.setup, values)
        queried = [call.args[0][-1] for call in run.call_args_list[1:]]
        self.assertEqual(
            queried,
            [f"name=^{stack.DEFAULT_PROJECT}_{name}$" for name in stack.VOLUMES],
        )

    def test_matching_volume_credentials_allow_stopped_state_relocation(self):
        values = stack.load_settings(self.setup)
        owner = hashlib.sha256(values["LOCAL_ACCESS_TOKEN"].encode()).hexdigest()
        answers = [""]
        for name in stack.VOLUMES:
            answers.extend((f"{stack.DEFAULT_PROJECT}_{name}\n", owner + "\n"))
        with patch.object(stack, "run", side_effect=answers):
            stack.assert_owned_containers(Path("/relocated/local-setup"), values)

    def test_missing_and_foreign_volume_owners_block_reuse(self):
        values = stack.load_settings(self.setup)
        for index, name in enumerate(stack.VOLUMES):
            for owner in ("", "<no value>", "f" * 64):
                with self.subTest(volume=name, owner=owner):
                    answers = [""] + [""] * index
                    answers.extend((f"{stack.DEFAULT_PROJECT}_{name}\n", owner))
                    with (
                        patch.object(stack, "run", side_effect=answers),
                        self.assertRaises(stack.SetupError) as caught,
                    ):
                        stack.assert_owned_containers(self.setup, values)
                    self.assertIn("different or missing owner", str(caught.exception))
                    self.assertNotIn(values["LOCAL_ACCESS_TOKEN"], str(caught.exception))

    def test_unowned_stopped_volumes_block_stop_and_reset(self):
        name = f"{stack.DEFAULT_PROJECT}_{stack.VOLUMES[0]}"
        for arguments in (("stop",), ("reset", "--confirm", "RESET_LOCAL_STACK")):
            with self.subTest(arguments=arguments):
                with patch.object(stack, "run", side_effect=["", name + "\n", ""]) as run:
                    code, output = self.cli(*arguments)
                self.assertEqual(code, 2)
                self.assertIn("different or missing owner", json.loads(output)["error"])
                self.assertFalse(any("down" in call.args[0] for call in run.call_args_list))

    def test_log_tail_redacts_credentials_crossing_its_cutoff(self):
        values = stack.load_settings(self.setup)
        credential = values["LOCAL_ACCESS_TOKEN"]
        suffix_length = 8000 - len(credential) // 2
        script = (
            "import os,sys; "
            "target = sys.stderr if sys.argv[1] == 'error' else sys.stdout; "
            f"target.write('a' * 9000 + os.environ['LOCAL_ACCESS_TOKEN'] + 'z' * {suffix_length}); "
            "sys.exit(1 if sys.argv[1] == 'error' else 0)"
        )
        for mode in ("success", "error"):
            with self.subTest(mode=mode):
                command = [sys.executable, "-c", script, mode]
                if mode == "error":
                    with self.assertRaises(stack.SetupError) as caught:
                        stack.run(command, values, self.setup)
                    output = str(caught.exception)
                else:
                    output = stack.run(command, values, self.setup)
                    self.assertLessEqual(len(output), 8000)
                self.assertIn("[redacted]", output)
                self.assertNotIn(credential[len(credential) // 2 :], output)

    def test_successful_child_stderr_is_merged_only_when_requested(self):
        values = stack.load_settings(self.setup)
        script = (
            "import os; "
            r"os.write(1, b'stdout-before\n'); "
            r"os.write(2, b'application-event-on-stderr\n'); "
            r"os.write(1, b'stdout-after\n')"
        )
        command = [sys.executable, "-c", script]
        self.assertEqual(stack.run(command, values, self.setup), "stdout-before\nstdout-after\n")
        self.assertEqual(
            stack.run(command, values, self.setup, merge_output=True),
            "stdout-before\napplication-event-on-stderr\nstdout-after\n",
        )

    def test_merged_child_streams_redact_all_credentials(self):
        values = stack.load_settings(self.setup)
        script = (
            "import os; "
            r"os.write(1, ('stdout=' + os.environ['LOCAL_ACCESS_TOKEN'] + '\n').encode()); "
            r"os.write(2, ('stderr=' + os.environ['POSTGRES_PASSWORD'] + '\n').encode())"
        )
        output = stack.run([sys.executable, "-c", script], values, self.setup, merge_output=True)
        self.assertEqual(output, "stdout=[redacted]\nstderr=[redacted]\n")
        for name in stack.SECRET_KEYS:
            self.assertNotIn(values[name], output)

    def test_merged_tail_redacts_credential_crossing_cutoff_from_either_stream(self):
        values = stack.load_settings(self.setup)
        credential = values["LOCAL_ACCESS_TOKEN"]
        script = (
            "import os,sys; "
            "fd=int(sys.argv[1]); "
            "credential=os.environ['LOCAL_ACCESS_TOKEN'].encode(); "
            r"os.write(3-fd, b'other-stream-event\n'); "
            r"os.write(fd, b'a'*9000 + credential + b'z'*(8000-len(credential)//2)); "
            "sys.exit(int(sys.argv[2]))"
        )
        for descriptor in (1, 2):
            for exit_code in (0, 7):
                with self.subTest(descriptor=descriptor, exit_code=exit_code):
                    command = [sys.executable, "-c", script, str(descriptor), str(exit_code)]
                    if exit_code:
                        with self.assertRaises(stack.SetupError) as caught:
                            stack.run(command, values, self.setup, merge_output=True)
                        output = str(caught.exception)
                        self.assertIn("Operation failed with exit 7", output)
                    else:
                        output = stack.run(command, values, self.setup, merge_output=True)
                        self.assertLessEqual(len(output), 8000)
                    self.assertIn("[redacted]", output)
                    self.assertNotIn(credential, output)
                    self.assertNotIn(credential[len(credential) // 2 :], output)

    def test_nonzero_merged_result_preserves_errors_and_stdout_fallback(self):
        values = stack.load_settings(self.setup)
        script = (
            "import os,sys; "
            r"os.write(1, b'stdout-detail\n'); "
            r"os.write(2, ('stderr-detail ' + os.environ['LOCAL_ACCESS_TOKEN'] + '\n').encode()); "
            "sys.exit(7)"
        )
        fallback = (
            "import os,sys; "
            r"os.write(1, ('stdout-fallback ' + os.environ['LOCAL_ACCESS_TOKEN'] + '\n').encode()); "
            "sys.exit(9)"
        )
        for merged in (False, True):
            with self.subTest(merged=merged):
                with self.assertRaises(stack.SetupError) as caught:
                    stack.run(
                        [sys.executable, "-c", script], values, self.setup, merge_output=merged
                    )
                detail = str(caught.exception)
                self.assertIn("Operation failed with exit 7", detail)
                self.assertIn("stderr-detail [redacted]", detail)
                self.assertEqual("stdout-detail" in detail, merged)
                self.assertNotIn(values["LOCAL_ACCESS_TOKEN"], detail)
                with self.assertRaises(stack.SetupError) as caught:
                    stack.run(
                        [sys.executable, "-c", fallback], values, self.setup, merge_output=merged
                    )
                self.assertIn(
                    "Operation failed with exit 9: stdout-fallback [redacted]",
                    str(caught.exception),
                )
                self.assertNotIn(values["LOCAL_ACCESS_TOKEN"], str(caught.exception))

    def test_only_logs_action_requests_stream_merging(self):
        outputs = {
            "logs": "application-event-on-stderr\n",
            "status": "control-api\trunning\thealthy\n",
            "smoke": '{"status":"passed"}\n',
            "config": "",
        }
        for action, child_output in outputs.items():
            with self.subTest(action=action):
                with patch.object(stack, "run", return_value=child_output) as command:
                    code, output = self.cli(action)
                self.assertEqual(code, 0)
                self.assertEqual(
                    command.call_args.kwargs.get("merge_output", False), action == "logs"
                )
                if action == "logs":
                    self.assertEqual(json.loads(output)["output"], "application-event-on-stderr")
                    self.assertEqual(
                        command.call_args.args[0][-4:], ["logs", "--no-color", "--tail", "100"]
                    )

    def test_logs_service_selection_is_allowlisted_and_keeps_bounded_tail(self):
        self.assertEqual(
            set(stack.LOG_SERVICES),
            {
                "console",
                "control-api",
                "conversation-agent",
                "jaeger",
                "livekit",
                "p1-migrate",
                "p1-worker",
                "postgres",
                "rtc-agent",
            },
        )
        for service in stack.LOG_SERVICES:
            with self.subTest(service=service):
                with patch.object(stack, "run", return_value="selected-event") as command:
                    code, output = self.cli("logs", "--service", service)
                self.assertEqual(code, 0)
                self.assertEqual(json.loads(output)["output"], "selected-event")
                self.assertEqual(
                    command.call_args.args[0][-5:],
                    ["logs", "--no-color", "--tail", "100", service],
                )
                self.assertEqual(command.call_args.args[-1], 60)
                self.assertTrue(command.call_args.kwargs["merge_output"])

    def test_service_selection_on_other_actions_fails_before_configuration_or_execution(self):
        actions = (
            "init",
            "doctor",
            "config",
            "start",
            "status",
            "smoke",
            "stop",
            "reset",
            "token",
            "prepare-postgres",
            "migrate-postgres",
        )
        for action in actions:
            with self.subTest(action=action):
                with (
                    patch.object(stack, "load_settings") as load,
                    patch.object(stack, "initialize") as initialize,
                    patch.object(stack, "run") as command,
                ):
                    code, output = self.cli(action, "--service", "rtc-agent")
                self.assertEqual(code, 2)
                self.assertEqual(
                    json.loads(output)["error"], "--service is only supported for the logs action"
                )
                load.assert_not_called()
                initialize.assert_not_called()
                command.assert_not_called()

    def test_unknown_logs_service_cannot_execute_a_command(self):
        with (
            patch.object(stack, "run") as command,
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit) as caught,
        ):
            self.cli("logs", "--service", "unknown-service")
        self.assertEqual(caught.exception.code, 2)
        command.assert_not_called()

    def test_success_and_error_diagnostics_do_not_echo_secrets(self):
        values = stack.load_settings(self.setup)
        with patch.object(stack, "run", return_value=""):
            code, output = self.cli("config")
        self.assertEqual(code, 0)
        for name in stack.SECRET_KEYS - {"LIVEKIT_API_KEY"}:
            self.assertNotIn(values[name], output)
        self.assertEqual(
            stack.redact("failure " + values["LOCAL_ACCESS_TOKEN"], values), "failure [redacted]"
        )
        with patch.object(stack, "run", side_effect=stack.SetupError("safe failure")):
            code, output = self.cli("status")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output)["error"], "safe failure")

    def test_optional_http_readiness_requires_200(self):
        response = MagicMock()
        response.__enter__.return_value.status = 200
        opener = MagicMock(return_value=response)
        stack.wait_for_http("http://127.0.0.1:26686/", opener=opener)
        self.assertEqual(opener.call_count, 1)
        self.assertLessEqual(opener.call_args.kwargs["timeout"], 2)
        response.__exit__.assert_called_once()

    def test_optional_http_failure_exhausts_fake_clock_budget(self):
        now = [0.0]
        opener = MagicMock(side_effect=OSError("not ready"))

        def pause(seconds):
            now[0] += seconds

        with self.assertRaises(stack.SetupError):
            stack.wait_for_http(
                "http://127.0.0.1:26686/",
                timeout_seconds=0.5,
                opener=opener,
                clock=lambda: now[0],
                pause=pause,
            )
        self.assertEqual(now[0], 0.5)
        self.assertEqual(opener.call_count, 2)

    def test_start_only_certifies_requested_and_probed_observability(self):
        for arguments, expected in ((["start"], False), (["start", "--observability"], True)):
            with self.subTest(arguments=arguments):
                with (
                    patch.object(stack, "doctor"),
                    patch.object(stack, "run", return_value=""),
                    patch.object(stack, "wait_for_http") as probe,
                ):
                    code, output = self.cli(*arguments)
                self.assertEqual(code, 0)
                self.assertEqual(json.loads(output)["observabilityReady"], expected)
                self.assertEqual(probe.call_count, int(expected))
        with (
            patch.object(stack, "doctor"),
            patch.object(stack, "run", return_value=""),
            patch.object(
                stack, "wait_for_http", side_effect=stack.SetupError("readiness deadline")
            ),
        ):
            code, output = self.cli("start", "--observability")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output)["status"], "failed")

    def test_status_exposes_only_bounded_service_summary(self):
        with patch.object(
            stack, "run", return_value="control-api\trunning\thealthy\njaeger\trunning\t\n"
        ):
            code, output = self.cli("status")
        self.assertEqual(code, 0)
        report = json.loads(output)
        self.assertNotIn("output", report)
        self.assertEqual(
            report["services"],
            [
                {"service": "control-api", "state": "running", "health": "healthy"},
                {"service": "jaeger", "state": "running", "health": "unreported"},
            ],
        )
        with patch.object(stack, "run", return_value="malformed status"):
            code, output = self.cli("status")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output)["status"], "failed")

    def test_token_is_only_exposed_by_explicit_token_command(self):
        values = stack.load_settings(self.setup)
        code, output = self.cli("token")
        self.assertEqual(code, 0)
        self.assertEqual(output.strip(), values["LOCAL_ACCESS_TOKEN"])

    def test_config_command_does_not_print_expanded_compose(self):
        with patch.object(stack, "run", return_value="") as run:
            code, output = self.cli("config")
        self.assertEqual(code, 0)
        self.assertEqual(run.call_args.args[0][-2:], ["config", "--quiet"])
        self.assertEqual(json.loads(output)["status"], "configuration_valid")

    def legacy_credentials(self):
        path = self.setup / ".secrets.env"
        values = stack.parse_env(path)
        del values["POSTGRES_MIGRATION_PASSWORD"]
        path.write_text("\n".join(f"{key}={value}" for key, value in values.items()) + "\n")
        return path, values

    def test_legacy_upgrade_preserves_credentials_volume_identity_and_custom_config(self):
        path, old = self.legacy_credentials()
        env = self.setup / ".env"
        env.write_text(env.read_text().replace("UI_PORT=13000", "UI_PORT=13001"))
        config_before = env.read_bytes()
        owner_before = stack.stack_owner(old)
        code, output = self.cli("init")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["credentialSchema"], 2)
        self.assertEqual(json.loads(output)["configurationSchema"], 1)
        new = stack.parse_env(path)
        self.assertEqual(set(new), stack.SECRET_KEYS)
        self.assertEqual({key: new[key] for key in old}, old)
        self.assertEqual(stack.stack_owner(new), owner_before)
        self.assertEqual(env.read_bytes(), config_before)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        before_repeat = path.read_bytes()
        stack.initialize(self.setup)
        self.assertEqual(path.read_bytes(), before_repeat)

    def test_legacy_configuration_requires_explicit_init_before_other_actions(self):
        path, _old = self.legacy_credentials()
        before = path.read_bytes()
        for action in (
            "config",
            "start",
            "prepare-postgres",
            "migrate-postgres",
            "upgrade-postgres",
            "token",
        ):
            with self.subTest(action=action), patch.object(stack, "run") as run:
                code, output = self.cli(action)
                self.assertEqual(code, 2)
                self.assertIn("run local setup init", json.loads(output)["error"])
                run.assert_not_called()
                self.assertEqual(path.read_bytes(), before)

    def test_unknown_or_incomplete_credential_schema_fails_without_mutating_state(self):
        path, values = self.legacy_credentials()
        variants = [
            {**values, "UNKNOWN_SECRET": "s" * 48},
            {key: value for key, value in values.items() if key != "POSTGRES_PASSWORD"},
            {**values, "POSTGRES_MIGRATION_PASSWORD": "x" * 48, "UNKNOWN_SECRET": "s" * 48},
        ]
        for candidate in variants:
            with self.subTest(names=set(candidate)):
                path.write_text("\n".join(f"{key}={value}" for key, value in candidate.items()))
                before = path.read_bytes()
                with self.assertRaisesRegex(stack.SetupError, "unsupported setting schema"):
                    stack.initialize(self.setup)
                self.assertEqual(path.read_bytes(), before)

    def test_invalid_legacy_password_or_permissions_cannot_upgrade(self):
        path, values = self.legacy_credentials()
        for invalid in ("x" * 31, "x" * 32 + "';"):
            with self.subTest(length=len(invalid)):
                candidate = {**values, "POSTGRES_PASSWORD": invalid}
                path.write_text("\n".join(f"{key}={value}" for key, value in candidate.items()))
                before = path.read_bytes()
                with self.assertRaises(stack.SetupError) as caught:
                    stack.initialize(self.setup)
                self.assertNotIn(invalid, str(caught.exception))
                self.assertEqual(path.read_bytes(), before)
        path.write_text("\n".join(f"{key}={value}" for key, value in values.items()))
        path.chmod(0o644)
        with self.assertRaisesRegex(stack.SetupError, "0600"):
            stack.initialize(self.setup)
        self.assertNotIn("POSTGRES_MIGRATION_PASSWORD", stack.parse_env(path))

    def test_interrupted_upgrade_before_replace_preserves_old_valid_file_and_can_retry(self):
        path, old = self.legacy_credentials()
        before = path.read_bytes()
        before_files = set(self.setup.iterdir())
        with (
            patch.object(Path, "replace", side_effect=OSError("interrupted atomic replace")),
            self.assertRaises(OSError),
        ):
            stack.initialize(self.setup)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(set(self.setup.iterdir()), before_files)
        stack.validate_secrets(path, stack.parse_env(path), allow_legacy=True)
        stack.initialize(self.setup)
        self.assertEqual({key: stack.parse_env(path)[key] for key in old}, old)

    def test_upgrade_temporary_credentials_are_private_and_inside_ignored_generated_state(self):
        path, _old = self.legacy_credentials()
        original_replace = Path.replace
        temporary_paths = []

        def inspect_replace(source, target):
            if Path(target) == path.resolve():
                temporary_paths.append(source)
                self.assertEqual(source.parent, (self.setup / ".generated").resolve())
                self.assertTrue(source.name.startswith("credentials-"))
                self.assertEqual(stat.S_IMODE(source.stat().st_mode), 0o600)
                self.assertEqual(set(stack.parse_env(source)), stack.SECRET_KEYS)
            return original_replace(source, target)

        with patch.object(Path, "replace", inspect_replace):
            stack.initialize(self.setup)
        self.assertEqual(len(temporary_paths), 1)
        self.assertFalse(temporary_paths[0].exists())

    def test_interrupted_upgrade_after_replace_keeps_complete_private_new_credentials(self):
        path, old = self.legacy_credentials()
        with (
            patch.object(
                stack.os, "fsync", side_effect=[None, OSError("interrupted directory sync")]
            ),
            self.assertRaises(OSError),
        ):
            stack.initialize(self.setup)
        values = stack.parse_env(path)
        stack.validate_secrets(path, values)
        self.assertEqual({key: values[key] for key in old}, old)
        before_repeat = path.read_bytes()
        stack.initialize(self.setup)
        self.assertEqual(path.read_bytes(), before_repeat)

    def test_init_lock_prevents_concurrent_credential_creation_or_rotation(self):
        path, _old = self.legacy_credentials()
        before = path.read_bytes()
        with (
            stack.initialization_lock(self.setup),
            self.assertRaisesRegex(stack.SetupError, "initialization is active"),
        ):
            stack.initialize(self.setup)
        self.assertEqual(path.read_bytes(), before)
        stack.initialize(self.setup)
        stack.validate_secrets(path, stack.parse_env(path))

    def test_symlinked_or_public_initialization_lock_and_hardlinked_secrets_fail_closed(self):
        path, _old = self.legacy_credentials()
        before = path.read_bytes()
        lock = self.setup / ".generated/initialize.lock"
        lock.chmod(0o644)
        with self.assertRaisesRegex(stack.SetupError, "private regular file"):
            stack.initialize(self.setup)
        lock.unlink()
        lock.symlink_to(path)
        with self.assertRaisesRegex(stack.SetupError, "lock is unavailable"):
            stack.initialize(self.setup)
        lock.unlink()
        os.link(path, self.setup / "credential-copy")
        with self.assertRaisesRegex(stack.SetupError, "0600"):
            stack.initialize(self.setup)
        self.assertEqual(path.read_bytes(), before)

    def test_migration_credential_is_redacted_in_success_failure_and_stream_tails(self):
        values = stack.load_settings(self.setup)
        credential = values["POSTGRES_MIGRATION_PASSWORD"]
        script = (
            "import os,sys; "
            "credential=os.environ['POSTGRES_MIGRATION_PASSWORD']; "
            "sys.stderr.write('x'*9000 + credential + 'y'*(8000-len(credential)//2)); "
            "sys.exit(int(sys.argv[1]))"
        )
        for exit_code in (0, 1):
            with self.subTest(exit_code=exit_code):
                if exit_code:
                    with self.assertRaises(stack.SetupError) as caught:
                        stack.run(
                            [sys.executable, "-c", script, str(exit_code)],
                            values,
                            self.setup,
                            merge_output=True,
                        )
                    output = str(caught.exception)
                else:
                    output = stack.run(
                        [sys.executable, "-c", script, str(exit_code)],
                        values,
                        self.setup,
                        merge_output=True,
                    )
                self.assertIn("[redacted]", output)
                self.assertNotIn(credential, output)
                self.assertNotIn(credential[len(credential) // 2 :], output)

    def test_prepare_postgres_uses_owned_container_bounded_exec_without_credential_argv(self):
        values = stack.load_settings(self.setup)
        with (
            patch.object(stack, "assert_owned_containers") as ownership,
            patch.object(stack, "run", return_value="PostgreSQL migration role prepared\n") as run,
        ):
            code, output = self.cli("prepare-postgres")
        self.assertEqual(code, 0)
        ownership.assert_called_once_with(self.setup.resolve(), values)
        self.assertEqual(
            run.call_args.args[0][-5:],
            ["exec", "-T", "postgres", "sh", "/etc/continuity/prepare-postgres.sh"],
        )
        self.assertEqual(run.call_args.args[-1], 45)
        self.assertTrue(run.call_args.kwargs["merge_output"])
        for name in stack.SECRET_KEYS - {"LIVEKIT_API_KEY"}:
            self.assertNotIn(values[name], " ".join(run.call_args.args[0]))
            self.assertNotIn(values[name], output)
        self.assertFalse(json.loads(output)["credentialRotation"])
        self.assertEqual(json.loads(output)["productAcceptance"], "not_certified")

    def test_prepare_postgres_refuses_foreign_state_or_bootstrap_failure(self):
        with (
            patch.object(stack, "assert_owned_containers", side_effect=stack.SetupError("foreign")),
            patch.object(stack, "run") as run,
        ):
            code, output = self.cli("prepare-postgres")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output)["error"], "foreign")
        run.assert_not_called()
        with (
            patch.object(stack, "assert_owned_containers"),
            patch.object(stack, "run", side_effect=stack.SetupError("bootstrap refused")),
        ):
            code, output = self.cli("prepare-postgres")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output)["status"], "failed")

    def test_migrate_postgres_uses_explicit_one_shot_profile_and_preserves_live_source(self):
        values = stack.load_settings(self.setup)
        with (
            patch.object(stack, "assert_owned_containers") as ownership,
            patch.object(stack, "run", return_value='{"status":"schema_ready"}\n') as run,
        ):
            code, output = self.cli("migrate-postgres")
        self.assertEqual(code, 0)
        ownership.assert_called_once_with(self.setup.resolve(), values)
        self.assertEqual(
            run.call_args.args[0][-6:],
            ["--profile", "migrations", "run", "--rm", "--no-deps", "p1-migrate"],
        )
        self.assertEqual(run.call_args.args[-1], 60)
        self.assertTrue(run.call_args.kwargs["merge_output"])
        self.assertFalse(json.loads(output)["sourceCutover"])
        self.assertEqual(json.loads(output)["productAcceptance"], "not_certified")
        for name in stack.SECRET_KEYS - {"LIVEKIT_API_KEY"}:
            self.assertNotIn(values[name], " ".join(run.call_args.args[0]))

    def test_upgrade_postgres_uses_only_owner_profile_and_explicit_upgrade_command(self):
        with (
            patch.object(stack, "assert_owned_containers") as ownership,
            patch.object(stack, "run", return_value='{"current_version":2}') as run,
        ):
            code, output = self.cli("upgrade-postgres")
        self.assertEqual(code, 0)
        ownership.assert_called_once()
        self.assertEqual(
            run.call_args.args[0][-5:],
            ["p1-migrate", "python", "-m", "continuity_lab.postgres_cli", "upgrade"],
        )
        self.assertFalse(json.loads(output)["sourceCutover"])
        for key in stack.SECRET_KEYS - {"LIVEKIT_API_KEY"}:
            self.assertNotIn(stack.load_settings(self.setup)[key], " ".join(run.call_args.args[0]))

    def test_upgrade_effects_uses_only_owner_profile_and_explicit_upgrade_command(self):
        with (
            patch.object(stack, "assert_owned_containers") as ownership,
            patch.object(stack, "run", return_value='{"current_version":2}') as run,
        ):
            code, output = self.cli("upgrade-effects")
        self.assertEqual(code, 0)
        ownership.assert_called_once()
        self.assertEqual(
            run.call_args.args[0][-5:],
            ["p1-migrate", "python", "-m", "continuity_lab.postgres_cli", "upgrade-effects"],
        )
        self.assertFalse(json.loads(output)["sourceCutover"])
        for key in stack.SECRET_KEYS - {"LIVEKIT_API_KEY"}:
            self.assertNotIn(stack.load_settings(self.setup)[key], " ".join(run.call_args.args[0]))

    def test_upgrade_postgres_refuses_foreign_stack_before_running_command(self):
        with (
            patch.object(stack, "assert_owned_containers", side_effect=stack.SetupError("foreign")),
            patch.object(stack, "run") as run,
        ):
            code, _ = self.cli("upgrade-postgres")
        self.assertEqual(code, 2)
        run.assert_not_called()

    def test_worker_profile_actions_are_explicit_and_do_not_activate_schema(self):
        for action in ("start-workers", "stop-workers", "init-worker-fixtures", "worker-status"):
            with (
                self.subTest(action=action),
                patch.object(stack, "assert_owned_containers") as ownership,
                patch.object(stack, "run", return_value="ready") as run,
            ):
                code, output = self.cli(action)
                self.assertEqual(code, 0)
                ownership.assert_called_once()
                argv = run.call_args.args[0]
                self.assertIn("p1-workers", argv)
                self.assertIn("p1-worker", argv)
                self.assertFalse(json.loads(output)["schemaActivation"])
                for key in stack.SECRET_KEYS:
                    self.assertNotIn(stack.load_settings(self.setup)[key], " ".join(argv))
                if action == "init-worker-fixtures":
                    self.assertEqual(
                        argv[-4:], ["python", "-m", "continuity_lab.worker_cli", "init-fixtures"]
                    )

    def test_worker_actions_refuse_foreign_ownership_before_any_command(self):
        for action in (
            "start-workers",
            "stop-workers",
            "init-worker-fixtures",
            "worker-status",
            "upgrade-coordination",
            "upgrade-retry-pacing",
        ):
            with (
                self.subTest(action=action),
                patch.object(
                    stack,
                    "assert_owned_containers",
                    side_effect=stack.SetupError("Foreign checkout"),
                ),
                patch.object(stack, "run") as run,
            ):
                self.assertEqual(self.cli(action)[0], 2)
                run.assert_not_called()

    def test_optional_worker_configuration_rejects_unsafe_targets_without_rotating_secrets(self):
        before = (self.setup / ".secrets.env").read_bytes()
        original = (self.setup / ".env").read_text()
        (self.setup / ".env").write_text(
            original + "\nP1_WORKER_SCOPE=account-a\nP1_WORKER_SCHEMA=continuity_worker\n"
        )
        self.assertEqual(stack.load_settings(self.setup)["P1_WORKER_SCHEMA"], "continuity_worker")
        for schema in ("public", "information_schema", "pg_catalog", "../schema", "unsafe;sql"):
            with self.subTest(schema=schema):
                (self.setup / ".env").write_text(original + "\nP1_WORKER_SCHEMA=" + schema + "\n")
                with self.assertRaises(stack.SetupError):
                    stack.load_settings(self.setup)
        self.assertEqual((self.setup / ".secrets.env").read_bytes(), before)

    def test_normal_start_is_worker_opt_in_and_normal_stop_includes_worker_profile(self):
        with (
            patch.object(stack, "doctor"),
            patch.object(stack, "assert_owned_containers"),
            patch.object(stack, "run", return_value="") as run,
        ):
            self.assertEqual(self.cli("start")[0], 0)
            self.assertNotIn("p1-workers", run.call_args.args[0])
            self.assertEqual(self.cli("stop")[0], 0)
            self.assertIn("p1-workers", run.call_args.args[0])

    def test_coordination_upgrade_runs_only_migration_profile(self):
        with (
            patch.object(stack, "assert_owned_containers"),
            patch.object(stack, "run", return_value='{"current_version":4}') as run,
        ):
            code, output = self.cli("upgrade-coordination")
        self.assertEqual(code, 0)
        self.assertEqual(
            run.call_args.args[0][-5:],
            ["p1-migrate", "python", "-m", "continuity_lab.postgres_cli", "upgrade-coordination"],
        )
        self.assertFalse(json.loads(output)["sourceCutover"])

    def test_retry_pacing_upgrade_runs_only_migration_profile(self):
        with (
            patch.object(stack, "assert_owned_containers"),
            patch.object(stack, "run", return_value='{"current_version":5}') as run,
        ):
            code, output = self.cli("upgrade-retry-pacing")
        self.assertEqual(code, 0)
        self.assertEqual(
            run.call_args.args[0][-5:],
            ["p1-migrate", "python", "-m", "continuity_lab.postgres_cli", "upgrade-retry-pacing"],
        )
        self.assertFalse(json.loads(output)["sourceCutover"])

    def test_migrate_postgres_rejects_foreign_volumes_or_schema_failure(self):
        with (
            patch.object(stack, "assert_owned_containers", side_effect=stack.SetupError("foreign")),
            patch.object(stack, "run") as run,
        ):
            code, output = self.cli("migrate-postgres")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output)["error"], "foreign")
        run.assert_not_called()
        with (
            patch.object(stack, "assert_owned_containers"),
            patch.object(stack, "run", side_effect=stack.SetupError("schema refused")),
        ):
            code, output = self.cli("migrate-postgres")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output)["status"], "failed")


class PostgresBootstrapContractTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.script = self.root / "local-setup/config/020-migration-role.sh"
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        executable = self.directory / "psql"
        executable.write_text(
            f"#!{sys.executable}\n"
            "import json, os, pathlib, sys\n"
            "target=pathlib.Path(os.environ['BOOTSTRAP_CAPTURE'])\n"
            "command_file=next(arg.partition('=')[2] for arg in sys.argv if arg.startswith('--file='))\n"
            "path=pathlib.Path(command_file)\n"
            "target.write_text(json.dumps({'argv':sys.argv[1:], 'sql':path.read_text(), "
            "'mode':path.stat().st_mode & 0o777, 'stdin':sys.stdin.read(), "
            "'PGCONNECT_TIMEOUT':os.environ.get('PGCONNECT_TIMEOUT'), "
            "'selectors':{name:os.environ[name] for name in ('PGHOSTADDR','PGSERVICE','PGSERVICEFILE','PGPASSFILE') if name in os.environ}, "
            "'PGOPTIONS':os.environ.get('PGOPTIONS')}))\n"
            "print(os.environ['MIGRATION_POSTGRES_PASSWORD'])\n"
            "print(os.environ['POSTGRES_PASSWORD'], file=sys.stderr)\n"
            "sys.exit(int(os.environ.get('BOOTSTRAP_EXIT', '0')))\n"
        )
        executable.chmod(0o700)
        self.capture = self.directory / "capture.json"
        self.environment = {
            **os.environ,
            "PATH": str(self.directory) + os.pathsep + os.environ.get("PATH", ""),
            "POSTGRES_USER": "livekit_lab_admin",
            "POSTGRES_DB": "livekit_lab",
            "POSTGRES_PASSWORD": "a" * 48,
            "APP_POSTGRES_PASSWORD": "r" * 48,
            "MIGRATION_POSTGRES_PASSWORD": "m" * 48,
            "BOOTSTRAP_CAPTURE": str(self.capture),
        }

    def bootstrap(self, **overrides):
        return subprocess.run(
            ["sh", "-x", str(self.script)],
            env={**self.environment, **overrides},
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )

    def test_bootstrap_keeps_credentials_out_of_sql_argv_logs_and_private_command_file(self):
        result = self.bootstrap()
        self.assertEqual(result.returncode, 0, result.stderr)
        capture = json.loads(self.capture.read_text())
        self.assertEqual(capture["mode"], 0o600)
        self.assertEqual(capture["stdin"], ("m" * 48 + "\n") * 2)
        for name in ("POSTGRES_PASSWORD", "APP_POSTGRES_PASSWORD", "MIGRATION_POSTGRES_PASSWORD"):
            secret = self.environment[name]
            self.assertNotIn(secret, capture["sql"])
            self.assertNotIn(secret, " ".join(capture["argv"]))
            self.assertNotIn(secret, result.stdout + result.stderr)
        self.assertEqual(capture["PGCONNECT_TIMEOUT"], "3")
        self.assertIn("statement_timeout=5000", capture["PGOPTIONS"])
        command_file = next(
            arg.partition("=")[2] for arg in capture["argv"] if arg.startswith("--file=")
        )
        self.assertFalse(Path(command_file).exists())

    def test_bootstrap_clears_libpq_credential_and_target_redirectors(self):
        result = self.bootstrap(
            PGHOSTADDR="203.0.113.1",
            PGSERVICE="foreign",
            PGSERVICEFILE="/foreign/service",
            PGPASSFILE="/foreign/passwords",
        )
        self.assertEqual(result.returncode, 0)
        capture = json.loads(self.capture.read_text())
        self.assertEqual(capture["selectors"], {})
        self.assertIn("--port=5432", capture["argv"])

    def test_bootstrap_refuses_invalid_or_wrong_identity_credentials_before_psql(self):
        cases = [
            {"MIGRATION_POSTGRES_PASSWORD": "m" * 31},
            {"MIGRATION_POSTGRES_PASSWORD": "m" * 129},
            {"MIGRATION_POSTGRES_PASSWORD": "m" * 48 + "'; SELECT 1"},
            {"POSTGRES_PASSWORD": "admin"},
            {"APP_POSTGRES_PASSWORD": ""},
            {"POSTGRES_USER": "different_admin"},
            {"POSTGRES_DB": "different_db"},
        ]
        for overrides in cases:
            with self.subTest(names=list(overrides)):
                result = self.bootstrap(**overrides)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.capture.exists())
                for secret in overrides.values():
                    if secret:
                        self.assertNotIn(secret, result.stdout + result.stderr)

    def test_bootstrap_suppresses_raw_psql_failure_output(self):
        result = self.bootstrap(BOOTSTRAP_EXIT="7")
        self.assertEqual(result.returncode, 1)
        self.assertIn("inspect role policy and retained credentials", result.stderr)
        for name in ("POSTGRES_PASSWORD", "APP_POSTGRES_PASSWORD", "MIGRATION_POSTGRES_PASSWORD"):
            self.assertNotIn(self.environment[name], result.stdout + result.stderr)

    def test_bootstrap_serializes_role_policy_and_verifies_scram_before_grants(self):
        self.assertEqual(self.bootstrap().returncode, 0)
        sql = json.loads(self.capture.read_text())["sql"]
        self.assertLess(sql.index("pg_advisory_lock"), sql.index("CREATE ROLE"))
        self.assertIn("auth_method <> 'scram-sha-256'", sql)
        self.assertIn("rolpassword IS NULL AS needs_password", sql)
        self.assertIn("\\if :needs_password\n\\password continuity_migrator\n\\endif", sql)
        self.assertEqual(sql.count("\\password continuity_migrator"), 1)
        self.assertNotRegex(sql, r"(?i)ALTER\s+ROLE.*PASSWORD|CREATE\s+ROLE.*PASSWORD")
        self.assertIn("continuity-migrator-v1-pending", sql)
        self.assertIn("continuity-migrator-v1-ready", sql)
        self.assertIn("existing migration role does not match", sql)
        self.assertIn("--host=127.0.0.1 --port=5432 --username=continuity_migrator", sql)
        self.assertIn("--host=127.0.0.1 --port=5432 --username=livekit_lab", sql)
        self.assertEqual(sql.count("\\if :SHELL_ERROR"), 2)
        self.assertLess(sql.index("\\if :SHELL_ERROR"), sql.index("GRANT CONNECT, CREATE"))
        self.assertIn(
            "REVOKE CREATE, TEMPORARY ON DATABASE livekit_lab FROM PUBLIC, livekit_lab", sql
        )
        self.assertIn("NOSUPERUSER NOCREATEDB NOCREATEROLE", sql)
        self.assertIn("NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 4", sql)

    def test_compose_separates_bootstrap_migration_and_runtime_credentials(self):
        compose = (self.root / "local-setup/docker-compose.yaml").read_text()
        services = dict(
            re.findall(
                r"^  ([a-z][a-z0-9-]+):\n(.*?)(?=^  [a-z][a-z0-9-]+:|^networks:)",
                compose,
                re.MULTILINE | re.DOTALL,
            )
        )
        postgres = services["postgres"]
        migration = services["p1-migrate"]
        api = services["control-api"]
        agent = services["rtc-agent"]
        self.assertIn("POSTGRES_PASSWORD: ${POSTGRES_ADMIN_PASSWORD", postgres)
        self.assertIn("MIGRATION_POSTGRES_PASSWORD: ${POSTGRES_MIGRATION_PASSWORD", postgres)
        self.assertIn(
            "./config/020-migration-role.sh:/etc/continuity/prepare-postgres.sh:ro", postgres
        )
        self.assertNotIn("/docker-entrypoint-initdb.d/020", compose)
        self.assertIn("profiles: [migrations]", migration)
        self.assertIn('restart: "no"', migration)
        self.assertIn("command: [python, -m, continuity_lab.postgres_cli, schema]", migration)
        self.assertIn("P1_MIGRATION_USER: continuity_migrator", migration)
        self.assertIn("P1_MIGRATION_PASSWORD: ${POSTGRES_MIGRATION_PASSWORD", migration)
        for text in (api, agent):
            self.assertNotIn("POSTGRES_ADMIN_PASSWORD", text)
            self.assertNotIn("POSTGRES_MIGRATION_PASSWORD", text)
            self.assertNotIn("P1_MIGRATION_", text)
        self.assertIn("P1_POSTGRES_USER: livekit_lab", api)
        self.assertIn("P1_POSTGRES_PASSWORD: ${POSTGRES_PASSWORD", api)
        self.assertNotIn("POSTGRES_ADMIN_PASSWORD", migration)
        self.assertNotIn("${POSTGRES_PASSWORD", migration)
        self.assertNotIn("P1_POSTGRES_", migration)
        self.assertNotIn("ports:", migration)
        self.assertNotIn("volumes:", migration)
        self.assertNotIn("docker.sock", compose)
        self.assertIn("mem_limit: 256m", migration)
        self.assertIn("pids_limit: 64", migration)
        self.assertIn("cpus: 0.5", migration)


if __name__ == "__main__":
    unittest.main()
