"""No-PG fault injection of the actual P2 storage orchestrator cleanup path."""

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "local-setup/scripts"))
import p2_rehydration_check as gate
import p2_rehydration_p1 as p1_module


class RehydrationCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def execute_failure(
        self, *, child_pending=False, p1_pending=False, child_cleanup_failed=False
    ):
        temporary = tempfile.TemporaryDirectory(prefix="phase38-p2-cleanup-", dir="/private/tmp")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        compiler = root / "projects/channel-continuity/node_modules/typescript/bin/tsc"
        compiler.parent.mkdir(parents=True, mode=0o700)
        compiler.write_text("synthetic-tool-not-executed\n")
        artifacts = root / "artifacts"
        artifacts.mkdir(mode=0o700)
        primary = gate.GateError("controlled_primary")
        events = []
        holders = {}

        class Children:
            def __init__(self, work, deadline):
                self.work, self.deadline = work, deadline
                self.count = 0
                self.children = [
                    SimpleNamespace(
                        pid=101,
                        returncode=None if child_pending else 0,
                        cleanup_failed=child_cleanup_failed,
                        output_directory=work / "held",
                    )
                ]
                holders["children"] = self

            def call(self, label, argv, environment, **kwargs):
                self.count += 1
                events.append(label)
                if label == "compile":
                    return b""
                mode = argv[-1]
                return json.dumps(
                    {
                        "schemaVersion": 1,
                        "status": "passed",
                        "mode": mode,
                        "nodeVersion": "24.22.2",
                        "storageVersion": 0 if mode == "cleanup" else 7,
                        **gate.STAGE_EXTRA[mode],
                    }
                ).encode()

            def stop(self, child, **kwargs):
                events.append("stop")
                if child.returncode is None:
                    raise gate.GateError("cleanup_incomplete")

            def close(self):
                events.append("close_children")
                if any(c.returncode is None or c.cleanup_failed for c in self.children):
                    raise gate.GateError("cleanup_incomplete")

        class P1:
            token = "p" * 43

            def __init__(self, values, work, reference):
                self.work = work
                holders["p1"] = self

            async def start(self):
                raise primary

            async def bounded(self, operation, deadline):
                return await operation

            async def close(self, **kwargs):
                events.append("close_p1")
                if p1_pending:
                    raise TimeoutError()

        values = {
            "POSTGRES_PORT": "5432",
            "POSTGRES_PASSWORD": "r" * 43,
            "POSTGRES_MIGRATION_PASSWORD": "m" * 43,
        }
        setup = SimpleNamespace(load_settings=lambda: values, SECRET_KEYS=tuple(values))
        cleanup = {"cleanup_complete": False}
        with (
            patch.object(gate.core, "load_setup", return_value=setup),
            patch.object(gate, "source_snapshot", return_value={}),
            patch.object(gate.shutil, "which", side_effect=lambda name: name),
            patch.object(gate.previous, "Children", Children),
            patch.object(gate.native, "verify_runtime_build", return_value={"status": "passed"}),
            patch.object(p1_module, "P1ReadFixture", P1),
            self.assertRaises(gate.GateError) as caught,
        ):
            await gate.run(root, artifacts, time.monotonic(), cleanup)
        self.assertIs(caught.exception, primary)
        return events, holders, cleanup, artifacts

    async def test_live_owned_child_prevents_DDL_and_keeps_marker_and_primary(self):
        events, holders, cleanup, artifacts = await self.execute_failure(child_pending=True)
        self.assertIn("stop", events)
        self.assertIn("close_p1", events)
        self.assertNotIn("cleanup", events)
        self.assertFalse(cleanup["cleanup_complete"])
        self.assertTrue((holders["children"].work / "rehydration-owned-work.json").is_file())
        self.assertTrue((artifacts / "owned-work-retained.json").is_file())

    async def test_unsettled_P1_owner_prevents_P2_DDL_despite_reaped_children(self):
        events, holders, cleanup, _artifacts = await self.execute_failure(p1_pending=True)
        self.assertNotIn("cleanup", events)
        self.assertFalse(cleanup["cleanup_complete"])
        self.assertTrue(holders["children"].work.exists())

    async def test_failed_child_cleanup_blocks_DDL_even_with_an_exit_code(self):
        events, holders, cleanup, _artifacts = await self.execute_failure(child_cleanup_failed=True)
        self.assertTrue(all(child.returncode is not None for child in holders["children"].children))
        self.assertNotIn("cleanup", events)
        self.assertFalse(cleanup["cleanup_complete"])
        self.assertTrue(holders["children"].work.exists())

    async def test_known_closed_owners_allow_schema_cleanup_and_private_work_removal(self):
        events, holders, cleanup, _artifacts = await self.execute_failure()
        self.assertIn("cleanup", events)
        self.assertLess(events.index("close_p1"), events.index("cleanup"))
        self.assertTrue(cleanup["cleanup_complete"])
        self.assertFalse(holders["children"].work.exists())
