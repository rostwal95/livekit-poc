"""Real isolated business bootstrap/replay; no serving M1 or operator schema input."""

import asyncio
import hashlib
import importlib.util
import json
import os
import sys
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from psycopg import sql

from continuity_lab.authorization import AuthenticatedActor, BearerToken
from continuity_lab.migrations import migrate
from continuity_lab.models import BookingChange
from continuity_lab.postgres_api import open_postgres_client
from continuity_lab.postgres_migrations import install_schema, read_import_state, stage_import
from continuity_lab.postgres_settings import PostgresSettings
from continuity_lab.source_transfer import prepare_source
from continuity_lab.store import TaskStore

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "real_business_bootstrap", ROOT / "local-setup/scripts/prepare_business.py"
)
bootstrap = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bootstrap
spec.loader.exec_module(bootstrap)


class PostgresBusinessBootstrapCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("P1_RUN_POSTGRES_TESTS") != "1":
            raise RuntimeError("Explicit real PostgreSQL setup is required; this lane cannot skip")
        cls.runtime_base = PostgresSettings.from_env()
        cls.owner_base = PostgresSettings.from_env("P1_MIGRATION_")

    def setUp(self):
        self.schema = "p1_bootstrap_" + uuid4().hex
        self.owner = replace(self.owner_base, schema=self.schema)
        self.runtime = replace(self.runtime_base, schema=self.schema)
        self.addCleanup(self.drop_schema)
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve()
        self.base = self.directory / "business-bootstrap"
        self.main = self.directory / "serving-m1.sqlite3"
        self.accepted = TaskStore(self.main).submit(
            scope_id="m1-original",
            idempotency_key="same",
            request=BookingChange("DEMO-BK-001", date(2030, 12, 10), True),
        )
        self.main_sha = hashlib.sha256(self.main.read_bytes()).hexdigest()

    def drop_schema(self):
        if not self.schema.startswith("p1_bootstrap_") or len(self.schema) != 45:
            raise AssertionError("Only the exact owned bootstrap test namespace may be removed")
        with closing(self.owner.connect(application_name="continuity-migrate")) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(self.schema))
            )

    def snapshot(self):
        with closing(self.owner.connect(application_name="continuity-test")) as connection:
            rows = connection.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname=%s ORDER BY tablename",
                (self.schema,),
            ).fetchall()
            return {
                row["tablename"]: sorted(
                    json.dumps(value, sort_keys=True, default=str)
                    for value in connection.execute(
                        sql.SQL("SELECT * FROM {}").format(
                            sql.Identifier(self.schema, row["tablename"])
                        )
                    ).fetchall()
                )
                for row in rows
            }

    def prepare(self):
        return bootstrap.prepare(self.owner, self.runtime, self.base)

    def unchanged_m1(self):
        self.assertEqual(self.main_sha, hashlib.sha256(self.main.read_bytes()).hexdigest())

    def test_fresh_absent_target_reaches_active_v4_then_readonly_ready_preserves_accepted_business_and_m1(
        self,
    ):
        result = self.prepare()
        self.assertTrue(result["changed"])
        self.assertEqual(
            (4, "active"),
            (read_import_state(self.owner).version, read_import_state(self.owner).state),
        )

        async def admit():
            client = open_postgres_client(
                actor=AuthenticatedActor("bootstrap-operator", "bootstrap-scope"),
                token=BearerToken("bootstrap-token-" + "x" * 32),
                settings=self.runtime,
            )
            async with client:
                accepted = await client.submit(
                    idempotency_key="original",
                    request=BookingChange("DEMO-BK-001", date(2030, 12, 10), True),
                )
                self.assertTrue(accepted.created)
                return accepted.task_id

        task = asyncio.run(admit())
        before = self.snapshot()
        replay = self.prepare()
        self.assertFalse(replay["changed"])
        self.assertIsNone(replay["bootstrap_run_id"])
        self.assertEqual(before, self.snapshot())
        self.assertIn(task, str(before))
        self.unchanged_m1()

    def test_valid_empty_owned_staging_bootstraps_without_touching_serving_source(self):
        install_schema(self.owner)
        self.assertEqual("staging", read_import_state(self.owner).state)
        self.assertTrue(self.prepare()["changed"])
        self.assertEqual(4, read_import_state(self.owner).version)
        self.unchanged_m1()

    def test_nonempty_imported_staging_refuses_before_target_rows_or_source_artifacts_change(
        self,
    ):
        source = self.directory / "foreign-empty-source.sqlite3"
        migrate(source, self.directory / "foreign-before-v1.sqlite3")
        TaskStore(source).submit(
            scope_id="foreign-staging",
            idempotency_key="retain",
            request=BookingChange("DEMO-BK-001", date(2030, 12, 10), True),
        )
        snapshot = prepare_source(source, self.directory / "foreign-before-cutover.sqlite3")
        self.assertEqual(1, len(snapshot.tasks))
        install_schema(self.owner)
        stage_import(self.owner, snapshot)
        before = self.snapshot()
        with self.assertRaises(bootstrap.BootstrapError):
            self.prepare()
        self.assertEqual(before, self.snapshot())
        self.assertFalse(list(self.base.glob("*/source.sqlite3")))
        self.unchanged_m1()

    def test_partial_owned_upgrade_failure_retries_original_receipt_and_backups(self):
        with (
            patch.object(
                bootstrap, "upgrade_v3", side_effect=bootstrap.BootstrapError("bootstrap_failed")
            ),
            self.assertRaises(bootstrap.BootstrapError),
        ):
            self.prepare()
        self.assertEqual(2, read_import_state(self.owner).version)
        entry = next(self.base.glob("target-*.json"))
        receipt = json.loads(entry.read_text())
        folder = self.base / receipt["run_id"]
        backups = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in folder.glob("before-*.sqlite3")
        }
        result = self.prepare()
        self.assertEqual(receipt["run_id"], result["bootstrap_run_id"])
        self.assertEqual(receipt, json.loads(entry.read_text()))
        self.assertEqual(
            backups,
            {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in folder.glob("before-*.sqlite3")
            },
        )
        self.assertEqual(4, read_import_state(self.owner).version)
        self.unchanged_m1()
