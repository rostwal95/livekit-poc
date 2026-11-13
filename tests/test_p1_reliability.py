"""No Docker: strict declarations, bounded observers and a real SQLite lock barrier."""

import asyncio
import copy
import importlib.util
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, redirect_stdout
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from harness.reliability_models import (
    ReliabilityValidationError,
    canonical_manifest,
    load_manifest,
    manifest_digest,
    parse_manifest,
)

ROOT = Path.cwd()
SPEC = importlib.util.spec_from_file_location(
    "p1_reliability_test_controller", ROOT / "local-setup/scripts/p1_reliability.py"
)
controller = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = controller
SPEC.loader.exec_module(controller)
MANIFEST = ROOT / "harness/workloads/p1-reliability-v1.json"


class ReliabilityDeclarations(unittest.TestCase):
    def setUp(self):
        self.raw = json.loads(MANIFEST.read_text())

    def parse(self, raw):
        return parse_manifest(json.dumps(raw).encode())

    def test_all_four_fault_worker_pairs_and_declared_totals_are_frozen(self):
        value = load_manifest(MANIFEST)
        self.assertEqual(4, len(value.cases))
        self.assertEqual(32, sum(case.accepted for case in value.cases))
        self.assertEqual(96, sum(case.rejected for case in value.cases))
        self.assertEqual(value, parse_manifest(canonical_manifest(value)))
        with self.assertRaises(FrozenInstanceError):
            value.cases[0].workers = 2
        self.raw["cases"][0]["workers"] = 2
        self.assertEqual(1, value.cases[0].workers)

    def test_digest_binds_changes_but_not_object_key_order(self):
        value = self.parse(self.raw)
        reordered = dict(reversed(list(self.raw.items())))
        self.assertEqual(manifest_digest(value), manifest_digest(self.parse(reordered)))
        self.raw["seed"] += 1
        self.assertNotEqual(manifest_digest(value), manifest_digest(self.parse(self.raw)))

    def test_unknown_missing_duplicate_and_nonfinite_fields_fail_closed(self):
        for changed in [
            {**self.raw, "token": "private-sentinel"},
            {k: v for k, v in self.raw.items() if k != "seed"},
            {**self.raw, "seed": True},
            {**self.raw, "seed": float("nan")},
            {**self.raw, "schema_version": 2},
            {**self.raw, "base_manifest_sha256": "private-sentinel"},
        ]:
            with self.subTest(changed=tuple(changed)):
                with self.assertRaises(ReliabilityValidationError) as caught:
                    self.parse(changed)
                self.assertNotIn("private-sentinel", str(caught.exception))
        raw = MANIFEST.read_bytes().replace(
            b'"schema_version": 1', b'"schema_version": 1,"schema_version":1'
        )
        with self.assertRaises(ReliabilityValidationError):
            parse_manifest(raw)

    def test_each_unsafe_fault_budget_or_incomplete_pair_is_rejected(self):
        fields = {
            "workers": 3,
            "accepted": 9,
            "rejected": 0,
            "deadline_seconds": 601,
            "control_deadline_ms": 1600,
            "maximum_hold_ms": 5000,
            "stop_seconds": 0,
            "kind": "arbitrary",
        }
        for field, value in fields.items():
            raw = copy.deepcopy(self.raw)
            raw["cases"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ReliabilityValidationError):
                self.parse(raw)
        self.raw["cases"][1] = self.raw["cases"][0]
        with self.assertRaises(ReliabilityValidationError):
            self.parse(self.raw)

    def test_direct_construction_has_same_finite_bounds_and_fault_semantics(self):
        value = load_manifest(MANIFEST)
        for field, change in [
            ("overall_deadline_seconds", True),
            ("maximum_samples", 100000),
            ("workload_id", []),
            ("base_manifest_sha256", None),
        ]:
            with self.subTest(field=field), self.assertRaises(ReliabilityValidationError):
                replace(value, **{field: change})
        with self.assertRaises(ReliabilityValidationError):
            replace(value.cases[0], supplier_delay_ms=1000)
        with self.assertRaises(ReliabilityValidationError):
            replace(value.cases[2], supplier_delay_ms=0)

    def test_byte_depth_encoding_and_trailing_document_bounds(self):
        for raw in [
            b"",
            b" " * 16385,
            b"[" * 10 + b"]" * 10,
            b"\xff",
            MANIFEST.read_bytes() + b"{}",
        ]:
            with self.subTest(length=len(raw)), self.assertRaises(ReliabilityValidationError):
                parse_manifest(raw)

    def test_regular_file_loader_refuses_symlink_fifo_and_hardlink_without_blocking(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_bytes(MANIFEST.read_bytes())
            link = Path(directory) / "link"
            link.symlink_to(path)
            fifo = Path(directory) / "fifo"
            os.mkfifo(fifo)
            for selected in [link, fifo]:
                with self.assertRaises(ReliabilityValidationError):
                    load_manifest(selected)
            os.link(path, Path(directory) / "hardlink")
            with self.assertRaises(ReliabilityValidationError):
                load_manifest(path)

    def test_plan_validates_without_loading_stack_or_starting_work(self):
        output = io.StringIO()
        with (
            patch.object(
                controller, "load_tool", side_effect=AssertionError("runtime must not load")
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(0, controller.execute(load_manifest(MANIFEST), run=False))
        self.assertEqual("not_started", json.loads(output.getvalue())["status"])


class ReliabilityControllerContracts(unittest.TestCase):
    def test_one_record_cap_is_shared_atomically_across_resource_epochs(self):
        budget = controller.SampleBudget(20)

        def attempt(_):
            try:
                budget.reserve()
                return True
            except controller.bench.BenchmarkError:
                return False

        with ThreadPoolExecutor(max_workers=8) as executor:
            outcomes = list(executor.map(attempt, range(64)))
        self.assertEqual(20, sum(outcomes))
        self.assertEqual(20, budget.count)

    def test_deadline_snapshot_rejects_missing_duplicate_or_cross_identity_rows(self):
        row = {
            "task_id": "11111111-1111-4111-8111-111111111111",
            "deadline": "2030-01-01T00:00:00+00:00",
            "state": "running",
            "epoch": 1,
            "active": True,
        }
        self.assertEqual({row["task_id"]: row["deadline"]}, controller.original_deadlines([row], 1))
        for rows, count in [
            ([], 1),
            ([row, row], 2),
            ([{**row, "task_id": "private-sentinel"}], 1),
            ([{**row, "active": 1}], 1),
        ]:
            with self.assertRaises(controller.bench.BenchmarkError):
                controller.original_deadlines(rows, count)

    def test_uvicorn_sigterm_needs_completed_lifespan_and_finished_process_events(self):
        good = b"INFO:     Application shutdown complete.\nINFO:     Finished server process [7]\n"
        self.assertEqual(
            1, controller.api_shutdown_observation(good)["application_shutdown_complete_events"]
        )
        for raw in (
            b"",
            good.splitlines()[0],
            good.splitlines()[1],
            good + good,
            good + b"Application shutdown failed. private-sentinel",
        ):
            with (
                self.subTest(raw=raw),
                self.assertRaises(controller.bench.BenchmarkError) as caught,
            ):
                controller.api_shutdown_observation(raw)
            self.assertNotIn("private-sentinel", str(caught.exception))

    def test_cli_exception_boundary_does_not_dump_untrusted_dependency_exception(self):
        output = io.StringIO()
        with (
            patch.object(controller, "execute", side_effect=RuntimeError("private-sentinel")),
            redirect_stdout(output),
        ):
            self.assertEqual(1, controller.main([]))
        self.assertEqual(
            {"status": "failed", "code": "dependency_unavailable"}, json.loads(output.getvalue())
        )
        self.assertNotIn("private-sentinel", output.getvalue())

    def test_real_reserved_supplier_lock_blocks_writes_but_allows_reads_and_releases(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            database = folder / "supplier.sqlite3"
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("CREATE TABLE facts(value INTEGER)")
            process = subprocess.Popen(
                [sys.executable, "-c", controller.HOLD_SCRIPT, str(database), str(folder), "4500"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                deadline = time.monotonic() + 2
                while not (folder / "held").exists():
                    if process.poll() is not None or time.monotonic() > deadline:
                        self.fail("owned barrier did not become ready")
                    time.sleep(0.01)
                with closing(sqlite3.connect(database, timeout=0.05)) as connection:
                    self.assertEqual(
                        0, connection.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
                    )
                    with self.assertRaises(sqlite3.OperationalError):
                        connection.execute("INSERT INTO facts VALUES(1)")
                (folder / "release").touch()
                while not (folder / "result.json").exists():
                    if time.monotonic() > deadline:
                        self.fail("owned barrier did not release")
                    time.sleep(0.01)
                value = json.loads((folder / "result.json").read_text())
                self.assertTrue(value["released"])
                with closing(sqlite3.connect(database, timeout=0.1)) as connection:
                    connection.execute("INSERT INTO facts VALUES(1)")
                    connection.commit()
                (folder / "exit").touch()
                self.assertEqual(0, process.wait(timeout=2))
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=2)


class ReliabilitySelectionTests(unittest.TestCase):
    def test_selected_case_is_explicitly_partial_and_unknown_case_cannot_pass(self):
        manifest = load_manifest(MANIFEST)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(0, controller.execute(manifest, run=False, selected_case="restart-w1"))
        self.assertEqual("selected_case", json.loads(output.getvalue())["coverage"])
        self.assertEqual(["restart-w1"], json.loads(output.getvalue())["cases"])
        with self.assertRaises(ReliabilityValidationError):
            controller.execute(manifest, run=False, selected_case="missing")


class ReliabilityResourceEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_role_needs_two_samples_and_its_own_positive_cpu_window(self):
        lab = SimpleNamespace(
            prefix="owned", serving=[("owned-api", "api", None)], resource_windows={}
        )
        observer = object.__new__(controller.Observer)
        observer.lab = lab
        observer.stop = asyncio.Event()
        observer.task = asyncio.create_task(asyncio.sleep(0))
        observer.counts = {"owned-api": 2}
        with self.assertRaises(controller.bench.BenchmarkError):
            await observer.close()
        lab.resource_windows = {"owned-api": {"observed_window_seconds": 0}}
        with self.assertRaises(controller.bench.BenchmarkError):
            await observer.close()
        lab.resource_windows["owned-api"]["observed_window_seconds"] = 0.25
        observer.counts["owned-api"] = 1
        with self.assertRaises(controller.bench.BenchmarkError):
            await observer.close()
        observer.counts["owned-api"] = 2
        evidence = await observer.close()
        self.assertEqual({"api": 2}, evidence["samples"])
        self.assertGreater(evidence["cpu_windows"]["api"]["observed_window_seconds"], 0)


if __name__ == "__main__":
    unittest.main()
