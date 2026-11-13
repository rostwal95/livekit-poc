"""Execute the real parent's failure cleanup with literal owned-port substitutes.

No database connection, child process, socket, provider or actual source gate is
started. The filesystem is a fresh private synthetic tree for each run.
"""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "origin_lifecycle_parent_tested", ROOT / "local-setup/scripts/p2_channel_origin_check.py"
)
assert SPEC is not None and SPEC.loader is not None
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)


class LiteralQuery:
    def __init__(self, one=None, all_rows=None):
        self.one = one
        self.all_rows = [] if all_rows is None else all_rows

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.all_rows


class LiteralConnection:
    def __init__(self, settings, events, fail_drop):
        self.settings, self.events, self.fail_drop = settings, events, fail_drop

    def execute(self, query, parameters=None):
        query_text = str(query)
        if "SELECT 1 FROM pg_namespace" in query_text:
            return LiteralQuery(one=None)
        if "count(*) AS n FROM pg_locks" in query_text:
            self.events.append("quiet")
            return LiteralQuery(one={"n": 0})
        if "pg_get_userbyid(nspowner)" in query_text:
            return LiteralQuery(
                all_rows=[{"owner": "continuity_migrator", "marker": "continuity-readonly-work-v4"}]
            )
        if "DROP SCHEMA" in query_text:
            self.events.append("drop-work")
            if self.fail_drop:
                raise RuntimeError("PRIVATE_DROP_FAILURE_SENTINEL")
            return LiteralQuery()
        raise AssertionError("Unexpected SQL in literal cleanup port")

    def close(self):
        self.events.append("sql-close")


class OriginLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        os.chmod(self.root, 0o700)
        compiler = self.root / "projects/channel-continuity/node_modules/typescript/bin/tsc"
        compiler.parent.mkdir(parents=True)
        compiler.write_bytes(b"synthetic; never executed")
        self.report = self.root / ".local/validation/p2-channel-origin/failed.json"
        self.report.parent.mkdir(parents=True, mode=0o700)

    async def exercise(self, *, fail_drop=False, malformed=False, missing_marker=False):
        events = []
        state = {}
        values = {
            "POSTGRES_PORT": "1",
            "POSTGRES_PASSWORD": "synthetic_runtime",
            "POSTGRES_MIGRATION_PASSWORD": "synthetic_owner",
        }

        class Settings:
            def __init__(self, **arguments):
                self.schema = arguments["schema"]

            def connect(self, **arguments):
                events.append("literal-connect")
                return LiteralConnection(self, events, fail_drop)

        class Fixture:
            def __init__(self, settings, directory, reference):
                self.owner = SimpleNamespace(schema="p3_completion_" + "c" * 32)
                self.directory = directory
                state["work"] = directory

            async def close(self, **arguments):
                events.append("p1-close")
                state["case_closed"] = True

        class Children:
            def __init__(self, directory, deadline, final):
                self.children, self.sizes = {}, {}
                if missing_marker:
                    folder = directory / "capture-compile-public"
                    folder.mkdir(mode=0o700)
                    for name in ("stdout.bin", "stderr.bin"):
                        path = folder / name
                        path.write_bytes(b"")
                        os.chmod(path, 0o600)
                    self.children["compile-public"] = SimpleNamespace(
                        output_directory=folder,
                        pid=12345,
                        returncode=1,
                        group_settled=True,
                        cleanup_failed=False,
                    )

            def close(self):
                events.append("groups-close")

            def settled(self):
                return True

            def observation(self):
                return {
                    "schema_version": 1,
                    "groups": [
                        {
                            "role": role,
                            "pid": child.pid,
                            "returncode": child.returncode,
                            "group_settled": True,
                            "cleanup_failed": False,
                        }
                        for role, child in self.children.items()
                    ],
                    "capture_bytes": 0,
                }

        async def fail_before_compile(settings):
            events.append("primary")
            if malformed:
                path = state["work"] / "origin-malformed-proof.json"
                path.write_bytes(b'{"schema_version":1,PRIVATE_MALFORMED_SENTINEL}')
                os.chmod(path, 0o600)
            raise m.OriginGateError("invalid_proof")

        with (
            patch.dict(m.os.environ, {"PATH": "/synthetic/bin", "LANG": "en_US.UTF-8"}, clear=True),
            patch.object(
                m.core, "load_setup", return_value=SimpleNamespace(load_settings=lambda: values)
            ),
            patch.object(m.shutil, "which", return_value="/synthetic/node"),
            patch.object(m, "PostgresSettings", Settings),
            patch.object(m, "P1ReadFixture", Fixture),
            patch.object(m, "Children", Children),
            patch.object(m, "source_snapshot", return_value={"synthetic_source": "a" * 64}),
            patch.object(m, "m1_observation", fail_before_compile),
        ):
            result = await m.run(self.root, self.report)
        return result, events, state

    def assert_failure_retained(self, result, state):
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["code"], "invalid_proof")
        self.assertEqual(result["failure_stage"], "configuration")
        self.assertEqual(result["source_actual_assertions"], 0)
        self.assertEqual(result["assertions"], 0)
        self.assertTrue(result["work_directory_retained"])
        self.assertTrue(state["work"].is_dir())
        self.assertTrue(state["case_closed"])
        self.assertEqual(json.loads(self.report.read_bytes()), result)
        self.assertEqual(stat.S_IMODE(self.report.stat().st_mode), 0o600)
        artifacts = self.report.with_name(self.report.stem + "-artifacts")
        self.assertTrue((artifacts / "retained-index.json").is_file())
        self.assertEqual(
            m.starter.validate_retained_index(
                artifacts, (artifacts / "retained-index.json").read_bytes()
            )["schema_version"],
            1,
        )
        diagnostics = json.dumps(result)
        self.assertNotIn("PRIVATE_DROP_FAILURE_SENTINEL", diagnostics)
        self.assertNotIn("PRIVATE_MALFORMED_SENTINEL", diagnostics)

    async def test_primary_precompile_failure_closes_shared_owner_and_retains_failed_evidence(self):
        result, events, state = await self.exercise()
        self.assert_failure_retained(result, state)
        self.assertTrue(result["cleanup_complete"])
        self.assertEqual(result["cleanup_errors"], [])
        self.assertEqual(result["child_commands"], 0)
        self.assertEqual(events.count("p1-close"), 1)
        self.assertLess(events.index("primary"), events.index("p1-close"))

    async def test_independent_work_drop_failure_preserves_primary_and_still_closes_p1(self):
        result, events, state = await self.exercise(fail_drop=True)
        self.assert_failure_retained(result, state)
        self.assertFalse(result["cleanup_complete"])
        self.assertTrue(result["cleanup_errors"])
        self.assertEqual(events.count("p1-close"), 1)
        self.assertLess(events.index("drop-work"), events.index("p1-close"))
        self.assertGreaterEqual(events.count("groups-close"), 2)

    async def test_complete_malformed_retained_proof_never_replaces_primary_or_discards_tree(self):
        result, events, state = await self.exercise(malformed=True)
        self.assert_failure_retained(result, state)
        self.assertFalse(result["cleanup_complete"])
        self.assertTrue(result["cleanup_errors"])
        self.assertEqual(
            (state["work"] / "origin-malformed-proof.json").read_bytes(),
            b'{"schema_version":1,PRIVATE_MALFORMED_SENTINEL}',
        )
        artifacts = self.report.with_name(self.report.stem + "-artifacts")
        self.assertEqual(
            (artifacts / "unparsed-origin-malformed-proof.json.bin").read_bytes(),
            (state["work"] / "origin-malformed-proof.json").read_bytes(),
        )
        ownership = json.loads((artifacts / "parent-ownership.json").read_bytes())
        self.assertEqual(ownership["cleanup_errors"], result["cleanup_errors"])
        self.assertIn("p1-close", events)

    async def test_reaped_wrapper_without_group_marker_still_retains_structured_failure(self):
        result, events, state = await self.exercise(missing_marker=True)
        self.assert_failure_retained(result, state)
        self.assertFalse(result["cleanup_complete"])
        self.assertTrue(result["cleanup_errors"])
        self.assertEqual(result["child_commands"], 1)
        artifacts = self.report.with_name(self.report.stem + "-artifacts")
        self.assertEqual((artifacts / "capture-compile-public/stdout.bin").read_bytes(), b"")
        self.assertEqual((artifacts / "capture-compile-public/stderr.bin").read_bytes(), b"")
        self.assertFalse((artifacts / "capture-compile-public/process-group.pid").exists())
        self.assertIn("p1-close", events)
