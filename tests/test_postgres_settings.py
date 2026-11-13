"""Local connection configuration guards do not claim live PostgreSQL evidence."""

import os
import unittest
from dataclasses import FrozenInstanceError
from unittest.mock import patch

import psycopg

from continuity_lab.execution_models import StorageUnavailable
from continuity_lab.postgres_settings import PostgresSettings, advisory_keys


class PostgresSettingsTests(unittest.TestCase):
    def test_settings_are_immutable_and_repr_excludes_credential(self):
        settings = PostgresSettings(password="SECRET_SENTINEL")
        self.assertNotIn("SECRET_SENTINEL", repr(settings))
        with self.assertRaises(FrozenInstanceError):
            settings.user = "another"

    def test_explicit_keyword_connection_preserves_fixed_local_limits(self):
        settings = PostgresSettings(password="SECRET_SENTINEL")
        with (
            patch.dict(
                os.environ,
                {
                    "PGHOST": "untrusted.invalid",
                    "PGPASSWORD": "other",
                    "PGOPTIONS": "-c statement_timeout=0",
                },
                clear=True,
            ),
            patch("continuity_lab.postgres_settings.psycopg.connect") as connect,
        ):
            self.assertIs(settings.connect(), connect.return_value)
        kwargs = connect.call_args.kwargs
        self.assertEqual(kwargs["host"], "127.0.0.1")
        self.assertEqual(kwargs["password"], "SECRET_SENTINEL")
        self.assertEqual(kwargs["connect_timeout"], 5)
        self.assertEqual(kwargs["application_name"], "continuity-runtime")
        self.assertTrue(kwargs["autocommit"])
        self.assertIn("statement_timeout=5000", kwargs["options"])
        self.assertIn("lock_timeout=1000", kwargs["options"])
        self.assertIn("idle_in_transaction_session_timeout=5000", kwargs["options"])
        self.assertEqual(kwargs["sslmode"], "disable")
        self.assertNotIn("conninfo", kwargs)

    def test_invalid_configuration_fails_before_connection_without_echoing_values(self):
        variants = [
            {"host": "untrusted.invalid"},
            {"host": []},
            {"port": True},
            {"port": 0},
            {"port": 65536},
            {"dbname": "SECRET_SENTINEL;drop"},
            {"user": "Uppercase"},
            {"schema": "../outside"},
            {"password": ""},
            {"password": "SECRET\nSENTINEL"},
        ]
        for values in variants:
            with self.subTest(values=values), self.assertRaises(ValueError) as error:
                PostgresSettings(**({"password": "private"} | values))
            self.assertNotIn("SECRET", str(error.exception))
        with self.assertRaises(ValueError):
            PostgresSettings(password="private").connect(application_name="SECRET_SENTINEL")

    def test_environment_namespaces_keep_runtime_and_migrator_credentials_separate(self):
        values = {
            "P1_POSTGRES_PASSWORD": "runtime-secret",
            "P1_MIGRATION_PASSWORD": "migration-secret",
            "PGPASSWORD": "ignored-secret",
        }
        with patch.dict(os.environ, values, clear=True):
            runtime = PostgresSettings.from_env()
            migration = PostgresSettings.from_env("P1_MIGRATION_")
        self.assertEqual((runtime.user, runtime.password), ("livekit_lab", "runtime-secret"))
        self.assertEqual(
            (migration.user, migration.password), ("continuity_migrator", "migration-secret")
        )
        self.assertNotIn("secret", repr(runtime))

    def test_missing_or_invalid_environment_reports_safe_configuration_error(self):
        for values in (
            {},
            {"P1_POSTGRES_PASSWORD": "private", "P1_POSTGRES_PORT": "SECRET_SENTINEL"},
        ):
            with patch.dict(os.environ, values, clear=True), self.assertRaises(ValueError) as error:
                PostgresSettings.from_env()
            self.assertNotIn("SECRET_SENTINEL", str(error.exception))

    def test_connection_error_never_formats_private_driver_exception(self):
        class PrivateDriverError(psycopg.OperationalError):
            def __str__(self):
                raise AssertionError("Private driver message must not be read")

            def __repr__(self):
                raise AssertionError("Private driver representation must not be read")

        error = PrivateDriverError("SECRET_SENTINEL")
        with (
            patch("continuity_lab.postgres_settings.psycopg.connect", side_effect=error),
            self.assertRaises(StorageUnavailable) as caught,
        ):
            PostgresSettings(password="private").connect()
        self.assertEqual(caught.exception.code, "storage_unavailable")
        self.assertNotIn("SECRET_SENTINEL", str(caught.exception))
        self.assertIs(caught.exception.__cause__, error)

    def test_inherited_hostaddr_or_service_cannot_redirect_the_local_target(self):
        for key in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"):
            with (
                self.subTest(key=key),
                patch.dict(os.environ, {key: "SECRET_SENTINEL"}, clear=True),
                patch("continuity_lab.postgres_settings.psycopg.connect") as connect,
                self.assertRaises(ValueError) as error,
            ):
                PostgresSettings(password="private").connect()
            connect.assert_not_called()
            self.assertNotIn("SECRET_SENTINEL", str(error.exception))

    def test_advisory_namespaces_are_stable_distinct_and_bounded_integers(self):
        first = advisory_keys("continuity", "admission")
        self.assertEqual(first, advisory_keys("continuity", "admission"))
        self.assertNotEqual(first, advisory_keys("continuity", "worker"))
        self.assertNotEqual(first, advisory_keys("test_schema", "admission"))
        self.assertTrue(all(type(value) is int and -(2**31) <= value < 2**31 for value in first))
        with self.assertRaises(ValueError):
            advisory_keys("continuity", "SECRET_SENTINEL")


if __name__ == "__main__":
    unittest.main()
