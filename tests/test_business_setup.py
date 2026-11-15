"""Opt-in business orchestration validates prerequisites and preserves local state."""

import contextlib
import importlib.util
import io
import json
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from continuity_lab.completion_sink import initialize_completion_sink
from continuity_lab.execution_models import StorageUnavailable
from continuity_lab.mutation_supplier import initialize_mutation_supplier

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


stack = load_module("business_test_stack", ROOT / "local-setup/stack.py")
preflight = load_module(
    "business_test_preflight", ROOT / "local-setup/scripts/business_preflight.py"
)

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
    "P1_WORKER_SCOPE": "demo-traveller",
    "P1_WORKER_SCHEMA": "continuity",
}


class BusinessSetupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.setup = Path(self.directory.name) / "local-setup"
        self.setup.mkdir()
        (self.setup / "config").mkdir()
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
        stack.initialize(self.setup)

    def cli(self, action):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = stack.main([action], setup=self.setup)
        return result, json.loads(output.getvalue())

    def test_start_business_builds_checks_then_starts_explicit_services(self):
        before = (self.setup / ".secrets.env").read_bytes()
        with (
            patch.object(stack, "assert_owned_containers") as owned,
            patch.object(stack, "run", return_value="ready") as run,
        ):
            code, result = self.cli("start-business")
        self.assertEqual(code, 0)
        owned.assert_called_once()
        self.assertEqual(run.call_count, 3)
        build, check, start = run.call_args_list
        self.assertEqual(build.args[0][-2:], ["build", "control-api"])
        self.assertEqual(
            check.args[0][-6:],
            [
                "run",
                "--rm",
                "--no-deps",
                "control-api",
                "python",
                "/app/local-setup/scripts/business_preflight.py",
            ],
        )
        self.assertEqual(
            start.args[0][-4:], ["jaeger", "p1-worker", "conversation-agent", "control-api"]
        )
        for command in run.call_args_list:
            argv, values = command.args[:2]
            self.assertIn("p1-business", argv)
            self.assertIn("p1-workers", argv)
            self.assertIn("observability", argv)
            self.assertEqual(values["P1_BUSINESS_ENABLED"], "1")
            self.assertEqual(values["P1_TRACE_ENDPOINT"], "http://jaeger:4318/v1/traces")
            for name in stack.SECRET_KEYS:
                self.assertNotIn(values[name], " ".join(argv))
            self.assertNotIn("init-fixtures", argv)
            self.assertNotIn("--volumes", argv)
        self.assertFalse(result["schemaActivation"])
        self.assertFalse(result["fixtureInitialization"])
        self.assertEqual(before, (self.setup / ".secrets.env").read_bytes())

    def test_missing_prerequisites_do_not_replace_api_or_start_consumers(self):
        with (
            patch.object(stack, "assert_owned_containers"),
            patch.object(
                stack,
                "run",
                side_effect=["built", stack.SetupError("Prepare ACTIVE v4 and fixtures")],
            ) as run,
        ):
            code, result = self.cli("start-business")
        self.assertEqual(code, 2)
        self.assertEqual(run.call_count, 2)
        self.assertNotIn("up", run.call_args.args[0])
        self.assertIn("Prepare ACTIVE", result["error"])

    def test_both_business_actions_refuse_foreign_ownership_before_commands(self):
        for action in ("start-business", "stop-business"):
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

    def test_stop_business_drains_then_disables_api_and_retains_volumes(self):
        with (
            patch.object(stack, "assert_owned_containers"),
            patch.object(stack, "run", return_value="stopped") as run,
        ):
            code, result = self.cli("stop-business")
        self.assertEqual(code, 0)
        self.assertEqual(run.call_count, 3)
        stop, remove, disable = run.call_args_list
        self.assertEqual(stop.args[0][-5:], ["stop", "-t", "35", "conversation-agent", "p1-worker"])
        self.assertEqual(remove.args[0][-3:], ["rm", "--force", "conversation-agent"])
        self.assertEqual(disable.args[0][-1], "control-api")
        self.assertEqual(disable.args[1]["P1_BUSINESS_ENABLED"], "0")
        for command in (stop, remove):
            self.assertNotIn("--volumes", command.args[0])
            self.assertNotIn("down", command.args[0])
        self.assertFalse(result["schemaActivation"])

    def test_normal_start_stays_opt_in_and_normal_stop_includes_owned_profiles(self):
        with (
            patch.object(stack, "doctor"),
            patch.object(stack, "assert_owned_containers"),
            patch.object(stack, "run", return_value="") as run,
        ):
            self.assertEqual(self.cli("start")[0], 0)
            self.assertNotIn("p1-business", run.call_args.args[0])
            self.assertNotIn("P1_BUSINESS_ENABLED", run.call_args.args[1])
            self.assertEqual(self.cli("stop")[0], 0)
            argv = run.call_args.args[0]
            self.assertIn("p1-business", argv)
            self.assertIn("p1-workers", argv)
            self.assertIn("observability", argv)
            self.assertEqual(argv[-3:], ["down", "--timeout", "35"])
            self.assertNotIn("--volumes", argv)

    def test_shell_cannot_silently_activate_business_or_override_trace_target(self):
        values = stack.load_settings(self.setup)
        with patch.dict(
            "os.environ",
            {
                "P1_BUSINESS_ENABLED": "1",
                "P1_TRACE_ENDPOINT": "http://untrusted.invalid",
                "P1_WORKER_SCOPE": "other",
            },
        ):
            environment = stack.child_environment(values)
        self.assertNotIn("P1_BUSINESS_ENABLED", environment)
        self.assertNotIn("P1_TRACE_ENDPOINT", environment)
        self.assertEqual(environment["P1_WORKER_SCOPE"], "demo-traveller")

    def test_compose_native_is_scoped_and_has_no_mutation_fixture_or_operator_secret(self):
        compose = (ROOT / "local-setup/docker-compose.yaml").read_text()
        services = dict(
            re.findall(
                r"^  ([a-z][a-z0-9-]+):\n(.*?)(?=^  [a-z][a-z0-9-]+:|^networks:)",
                compose,
                re.MULTILINE | re.DOTALL,
            )
        )
        native = services["conversation-agent"]
        self.assertIn("profiles: [p1-business]", native)
        self.assertIn("LIVEKIT_LOG_LEVEL: warn", native)
        self.assertNotIn("LIVEKIT_LOG_LEVEL: warning", native)
        self.assertIn("command: [python, -m, services.conversation_agent, start]", native)
        self.assertIn("P1_POSTGRES_USER: livekit_lab", native)
        self.assertIn("P1_WORKER_SCOPE: ${P1_WORKER_SCOPE:-demo-traveller}", native)
        self.assertIn("8082/", native)
        self.assertIn("stop_grace_period: 35s", native)
        for private in (
            "LOCAL_ACCESS_TOKEN",
            "MIGRATION",
            "ADMIN_PASSWORD",
            "volumes:",
            "SUPPLIER_DB",
            "SINK_DB",
        ):
            self.assertNotIn(private, native)
        api = services["control-api"]
        self.assertIn("P1_BUSINESS_ENABLED: ${P1_BUSINESS_ENABLED:-0}", api)
        self.assertIn("worker_data:/business:ro", api)
        self.assertIn("P1_POSTGRES_SCHEMA: ${P1_WORKER_SCHEMA:-continuity}", api)
        self.assertNotIn("4318:", compose)
        self.assertIn("stop_grace_period: 35s", services["p1-worker"])


class BusinessPreflightTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.supplier = self.root / "supplier.sqlite3"
        self.sink = self.root / "completion.sqlite3"
        initialize_mutation_supplier(self.supplier, scope_id="demo-traveller")
        initialize_completion_sink(self.sink)
        self.environment = {
            "P1_WORKER_SCOPE": "demo-traveller",
            "P1_BUSINESS_SUPPLIER_DB": str(self.supplier),
            "P1_BUSINESS_SINK_DB": str(self.sink),
        }
        self.store = MagicMock()
        self.store.settings = SimpleNamespace(schema="continuity")
        self.connection = self.store._connection.return_value.__enter__.return_value
        self.connection.execute.return_value.fetchone.return_value = {"version": 4}

    def exercise(self):
        output = io.StringIO()
        with (
            patch.dict("os.environ", self.environment, clear=True),
            patch.object(preflight.PostgresSettings, "from_env"),
            patch.object(preflight, "PostgresExecutionStore", return_value=self.store),
            contextlib.redirect_stdout(output),
        ):
            code = preflight.main()
        return code, json.loads(output.getvalue())

    def test_valid_prerequisites_are_readonly_and_not_implicitly_activated(self):
        before = (self.supplier.read_bytes(), self.sink.read_bytes())
        code, result = self.exercise()
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "business_prerequisites_ready")
        self.assertFalse(result["schema_activation"])
        self.assertFalse(result["fixture_initialization"])
        self.assertEqual(before, (self.supplier.read_bytes(), self.sink.read_bytes()))
        statement = self.connection.execute.call_args.args[0]
        self.assertEqual(
            statement.as_string(),
            'SELECT version FROM "continuity"."schema_metadata" WHERE singleton',
        )

    def test_retry_pacing_v5_target_is_also_ready(self):
        self.connection.execute.return_value.fetchone.return_value = {"version": 5}
        code, result = self.exercise()
        self.assertEqual((code, result["status"]), (0, "business_prerequisites_ready"))

    def test_missing_or_old_schema_does_not_initialize_fixtures(self):
        for version in (None, {"version": 3}, {"version": 6}):
            with self.subTest(version=version):
                self.connection.execute.return_value.fetchone.return_value = version
                code, result = self.exercise()
                self.assertEqual(code, 2)
                self.assertEqual(result["code"], "prepare_active_v4_and_fixtures")

    def test_missing_fixture_or_changed_scope_is_refused_without_creating_files(self):
        missing = self.root / "missing.sqlite3"
        for changes in (
            {"P1_BUSINESS_SUPPLIER_DB": str(missing)},
            {"P1_BUSINESS_SINK_DB": str(missing)},
            {"P1_WORKER_SCOPE": "other-tenant"},
        ):
            with self.subTest(changes=changes):
                original = self.environment.copy()
                self.environment.update(changes)
                self.assertEqual(self.exercise()[0], 2)
                self.environment = original
                self.assertFalse(missing.exists())

    def test_private_storage_failure_never_exposes_exception_text(self):
        output = io.StringIO()
        with (
            patch.object(
                preflight, "check", side_effect=StorageUnavailable("private-password-or-dsn")
            ),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(preflight.main(), 2)
        self.assertNotIn("private-password", output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["code"], "prepare_active_v4_and_fixtures")

    def test_noncooperating_supplier_cannot_start_the_cooperating_profile(self):
        with contextlib.closing(sqlite3.connect(self.supplier)) as connection, connection:
            connection.execute("UPDATE supplier_metadata SET cooperating=0")
        before = self.supplier.read_bytes()
        self.assertEqual(self.exercise()[0], 2)
        self.assertEqual(before, self.supplier.read_bytes())

    def test_invalid_receiver_schema_cannot_be_repaired_by_preflight(self):
        with contextlib.closing(sqlite3.connect(self.sink)) as connection, connection:
            connection.execute("CREATE TABLE unexpected(value TEXT)")
        before = self.sink.read_bytes()
        self.assertEqual(self.exercise()[0], 2)
        self.assertEqual(before, self.sink.read_bytes())
