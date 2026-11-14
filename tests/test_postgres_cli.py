"""Role choice and exception privacy at the explicit PostgreSQL CLI boundary."""

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from continuity_lab import postgres_cli
from continuity_lab.execution_cli import _SafeFormatter
from continuity_lab.execution_models import StorageUnavailable


class PrivateFailure(RuntimeError):
    def __str__(self):
        raise AssertionError("Private exception text must not be read")

    def __repr__(self):
        raise AssertionError("Private exception representation must not be read")


class PostgresCliTests(unittest.TestCase):
    def test_schema_uses_only_explicit_migration_environment_and_does_not_activate(self):
        with (
            patch.object(postgres_cli.PostgresSettings, "from_env") as settings,
            patch.object(postgres_cli, "install_schema") as install,
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(postgres_cli.main(["schema"]), 0)
        settings.assert_called_once_with("P1_MIGRATION_")
        install.assert_called_once_with(settings.return_value)
        self.assertEqual(json.loads(output.getvalue())["activation"], "not_requested")

    def test_upgrade_uses_migration_settings_and_reports_observed_version(self):
        from continuity_lab.postgres_migrations import UpgradeReport

        with (
            patch.object(postgres_cli.PostgresSettings, "from_env") as settings,
            patch.object(
                postgres_cli, "upgrade_v2", return_value=UpgradeReport(1, 2, True)
            ) as upgrade,
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(postgres_cli.main(["upgrade"]), 0)
        settings.assert_called_once_with("P1_MIGRATION_")
        upgrade.assert_called_once_with(settings.return_value)
        self.assertEqual(json.loads(output.getvalue())["current_version"], 2)

    def test_effects_upgrade_uses_migration_settings_and_reports_observed_version(self):
        from continuity_lab.postgres_migrations import UpgradeReport

        with (
            patch.object(postgres_cli.PostgresSettings, "from_env") as settings,
            patch.object(
                postgres_cli, "upgrade_v3", return_value=UpgradeReport(2, 3, True)
            ) as upgrade,
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(postgres_cli.main(["upgrade-effects"]), 0)
        settings.assert_called_once_with("P1_MIGRATION_")
        upgrade.assert_called_once_with(settings.return_value)
        self.assertEqual(json.loads(output.getvalue())["current_version"], 3)

    def test_coordination_upgrade_uses_migration_settings_and_reports_observed_version(self):
        from continuity_lab.postgres_migrations import UpgradeReport

        with (
            patch.object(postgres_cli.PostgresSettings, "from_env") as settings,
            patch.object(
                postgres_cli, "upgrade_v4", return_value=UpgradeReport(3, 4, True)
            ) as upgrade,
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(postgres_cli.main(["upgrade-coordination"]), 0)
        settings.assert_called_once_with("P1_MIGRATION_")
        upgrade.assert_called_once_with(settings.return_value)
        self.assertEqual(json.loads(output.getvalue())["current_version"], 4)

    def test_retry_pacing_upgrade_uses_migration_settings_and_reports_observed_version(self):
        from continuity_lab.postgres_migrations import UpgradeReport

        with (
            patch.object(postgres_cli.PostgresSettings, "from_env") as settings,
            patch.object(
                postgres_cli, "upgrade_v5", return_value=UpgradeReport(4, 5, True)
            ) as upgrade,
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(postgres_cli.main(["upgrade-retry-pacing"]), 0)
        settings.assert_called_once_with("P1_MIGRATION_")
        upgrade.assert_called_once_with(settings.return_value)
        self.assertEqual(json.loads(output.getvalue())["current_version"], 5)

    def test_runtime_status_does_not_request_owner_settings(self):
        with (
            patch.object(postgres_cli.PostgresSettings, "from_env") as settings,
            patch.object(postgres_cli, "PostgresExecutionStore") as store,
            patch.object(postgres_cli, "read_import_state") as metadata,
            redirect_stdout(io.StringIO()) as output,
        ):
            metadata.return_value.version = 2
            self.assertEqual(postgres_cli.main(["status"]), 0)
        settings.assert_called_once_with()
        store.assert_called_once_with(settings.return_value)
        self.assertEqual(json.loads(output.getvalue())["state"], "active")
        self.assertEqual(json.loads(output.getvalue())["schema_version"], 2)

    def test_storage_failure_emits_safe_code_without_exception_text(self):
        with (
            patch.object(
                postgres_cli.PostgresSettings,
                "from_env",
                side_effect=StorageUnavailable("SECRET_SENTINEL"),
            ),
            self.assertLogs("continuity_lab", level="ERROR") as logs,
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(postgres_cli.main(["status"]), 2)
        self.assertEqual(json.loads(output.getvalue())["code"], "storage_unavailable")
        self.assertNotIn(
            "SECRET_SENTINEL",
            output.getvalue() + "".join(_SafeFormatter().format(row) for row in logs.records),
        )

    def test_unexpected_failure_never_reads_private_exception_text_or_repr(self):
        with (
            patch.object(postgres_cli.PostgresSettings, "from_env", side_effect=PrivateFailure()),
            self.assertLogs("continuity_lab", level="ERROR") as logs,
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(postgres_cli.main(["status"]), 1)
        self.assertEqual(json.loads(output.getvalue())["code"], "unexpected_error")
        self.assertNotIn(
            "Traceback",
            output.getvalue() + "".join(_SafeFormatter().format(row) for row in logs.records),
        )

    def test_malformed_private_argument_is_not_reflected(self):
        with (
            redirect_stdout(io.StringIO()),
            patch("sys.stderr", new_callable=io.StringIO) as error,
            self.assertRaises(SystemExit),
        ):
            postgres_cli.main(
                ["submit", "--scope", "SECRET_SENTINEL", "--check-in", "SECRET_SENTINEL"]
            )
        self.assertNotIn("SECRET_SENTINEL", error.getvalue())

    def test_malformed_exception_code_cannot_escape_sanitized_boundary(self):
        class BadCode(ValueError):
            def __init__(self, message):
                super().__init__(message)
                self.code = []

        with (
            patch.object(
                postgres_cli.PostgresSettings, "from_env", side_effect=BadCode("SECRET_SENTINEL")
            ),
            self.assertLogs("continuity_lab", level="ERROR"),
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(postgres_cli.main(["status"]), 2)
        self.assertEqual(json.loads(output.getvalue())["code"], "execution_error")
        self.assertNotIn("SECRET_SENTINEL", output.getvalue())

    def test_stored_state_and_schema_failures_keep_safe_codes(self):
        from continuity_lab.execution_models import InvalidStoredState
        from continuity_lab.migrations import SchemaVersionError

        for error, expected in (
            (InvalidStoredState("SECRET_SENTINEL"), "invalid_stored_state"),
            (SchemaVersionError("SECRET_SENTINEL"), "schema_version_unsupported"),
        ):
            with (
                self.subTest(code=expected),
                patch.object(postgres_cli.PostgresSettings, "from_env"),
                patch.object(postgres_cli, "PostgresExecutionStore", side_effect=error),
                self.assertLogs("continuity_lab", level="ERROR") as logs,
                redirect_stdout(io.StringIO()) as output,
            ):
                self.assertEqual(postgres_cli.main(["status"]), 2)
            self.assertEqual(json.loads(output.getvalue())["code"], expected)
            self.assertEqual(len(logs.records), 1)
            self.assertEqual(logs.records[0].event, "command_failed")
            rendered = output.getvalue() + "".join(
                _SafeFormatter().format(row) for row in logs.records
            )
            self.assertNotIn("SECRET_SENTINEL", rendered)
            self.assertNotIn("Traceback", rendered)
