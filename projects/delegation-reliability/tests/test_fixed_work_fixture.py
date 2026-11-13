"""Pure setup/publication/lifetime controls for the actual durable-v2 fixture."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixture = load_module(
    ROOT / "projects/delegation-reliability/tests/pg_fixed_policy_execution_cases.py",
    "fixed_work_fixture_test_subject",
)
host = load_module(
    ROOT / "local-setup/scripts/p3_durable_fixed_policy_check.py", "fixed_work_host_test_subject"
)


class FixtureControls(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix="p3-fixed-work-unit-", dir="/private/tmp"
        )
        self.directory = Path(self.temporary.name).resolve()
        self.directory.chmod(0o700)
        self.environment = patch.dict(
            os.environ, {"P3_FIXED_WORK_DIRECTORY": str(self.directory)}, clear=True
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def test_metadata_has_its_own_finite_profile_and_strict_canonical_read(self):
        value = {"rows": [{"id": n, "values": list(range(8))} for n in range(100)]}
        raw = fixture.file_json(value)
        from delegation_reliability.contracts import ContractError, canonical

        with self.assertRaises(ContractError):
            canonical(value)
        fixture.save("setup.json", value)
        self.assertEqual(fixture.load("setup.json"), value)
        for bad in (
            {"value": float("nan")},
            {"value": "\ud800"},
            {"value": "a" * 32768},
            {"rows": list(range(4096))},
        ):
            with (
                self.subTest(
                    bad_type=type(bad["value"] if "value" in bad else bad["rows"]).__name__
                ),
                self.assertRaises((AssertionError, UnicodeError)),
            ):
                fixture.file_json(bad)
        (self.directory / "duplicate.json").write_bytes(b'{"a":1,"a":1}')
        (self.directory / "duplicate.json").chmod(0o600)
        with self.assertRaises(AssertionError):
            fixture.load("duplicate.json")
        self.assertEqual(raw, fixture.file_json(json.loads(raw)))

    def test_atomic_publish_preserves_existing_bytes_and_rejects_foreign_links(self):
        target = self.directory / "fixed_work_known.reached"
        original = b"123\n"
        fixture.publish(target, original)
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(target.stat().st_nlink, 1)
        with self.assertRaises(FileExistsError):
            fixture.publish(target, b"999\n")
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(list(self.directory.glob("*.pending")), [])
        linked = self.directory / "unrelated"
        os.link(target, linked)
        with self.assertRaises(AssertionError):
            fixture.marker_pid(target, 123)
        linked.unlink()
        with self.assertRaises(AssertionError):
            fixture.marker_pid(target, 999)

    def test_exact_same_inode_marker_transition_waits_until_single_link(self):
        target = self.directory / "fixed_work_known.reached"
        pending = target.with_name(target.name + ".123.pending")
        pending.write_bytes(b"123\n")
        pending.chmod(0o600)
        os.link(pending, target)
        thread = threading.Thread(target=lambda: (time.sleep(0.01), pending.unlink()))
        thread.start()
        try:
            self.assertEqual(fixture.marker_pid(target, 123), 123)
        finally:
            thread.join(timeout=1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(target.stat().st_nlink, 1)

    def test_enrollment_consumes_all_exact_sources_and_fresh_request_horizons(self):
        from delegation_reliability.fixed_policy_contracts import (
            encode_fixed_policy_request,
            parse_fixed_policy_request,
        )
        from delegation_reliability.security import EvidenceRegistry

        scope = {"tenant_id": "tenant_fixed_work", "account_id": "account_fixed_work"}
        enrolled = host.enrollment(ROOT, scope)
        fixture.save("fixed-work-input.json", enrolled)
        fixture.save(
            "fixed-work-context.json",
            {
                "schema_version": 1,
                "scope": scope,
                "owners": {n: str(uuid4()) for n in fixture.LABELS},
                "commands": {n: "cmd_" + n for n in fixture.LABELS},
            },
        )
        self.assertEqual(len(enrolled["records"]), 4)
        for label in fixture.LABELS:
            before = time.time_ns() // 1_000_000
            request = fixture.request(label)
            after = time.time_ns() // 1_000_000
            records = fixture.evidence(label)
            self.assertEqual(len(records), 2)
            EvidenceRegistry(records)
            self.assertEqual(
                request, parse_fixed_policy_request(encode_fixed_policy_request(request))
            )
            horizon = 1000 if label.startswith("expired_") else 60000
            self.assertGreaterEqual(request.deadline_at_ms, before + horizon)
            self.assertLessEqual(request.deadline_at_ms, after + horizon)
            for record in records:
                self.assertEqual(hashlib.sha256(record.body).hexdigest(), record.reference.sha256)
        self.assertEqual(json.loads(fixture.evidence("missing")[1].body)["observations"], [])
        self.assertEqual(
            [
                r["days_before_arrival"]
                for r in json.loads(fixture.evidence("conflicting")[1].body)["observations"]
            ],
            [10, 3],
        )
        self.assertEqual(
            json.loads(fixture.evidence("known")[1].body)["kind"], "booking.notice_facts"
        )

    def test_role_environment_rejects_cross_owner_and_ambient_selectors(self):
        shared = {
            "P3_FIXED_WORK_DIRECTORY": str(self.directory),
            "P3_FIXED_WORK_WORK_SCHEMA": "p1_work_fixedv2_" + "a" * 32,
            "P3_FIXED_WORK_CASE_SCHEMA": "p3_completion_" + "a" * 32,
            "P3_FIXED_WORK_PG_PORT": "15432",
        }
        runtime = {
            **shared,
            "P3_FIXED_WORK_TOKEN": "a" * 43,
            "P3_FIXED_WORK_RUNTIME_PASSWORD": "synthetic_runtime",
        }
        owner = {**shared, "P3_FIXED_WORK_OWNER_PASSWORD": "synthetic_owner"}
        for mode, env in (("exercise", runtime), ("install", owner)):
            with patch.dict(os.environ, env, clear=True):
                fixture.environment(mode)
            for name in (
                "HTTP_PROXY",
                "PGHOSTADDR",
                "PYTHONPATH",
                "P3_FIXED_WORK_OWNER_PASSWORD"
                if mode == "exercise"
                else "P3_FIXED_WORK_RUNTIME_PASSWORD",
            ):
                with (
                    patch.dict(os.environ, {**env, name: "not_forwarded"}, clear=True),
                    self.assertRaises(AssertionError),
                ):
                    fixture.environment(mode)

    def test_owner_cursor_queries_actual_protected_P1_catalog_names(self):
        # Owner/test-only catalog inspection; runtime consumers do not import it.
        from continuity_lab.work_schema import (
            DELIVERY_TABLES,
            EXECUTION_TABLES,
            FEED_TABLES,
            TABLES,
        )

        catalog = set(TABLES + EXECUTION_TABLES + DELIVERY_TABLES + FEED_TABLES)
        queries = []

        class Cursor:
            def fetchall(self):
                return []

        class Connection:
            def execute(self, query):
                sql = query.as_string()
                table = sql.split('"')[3]
                if table not in catalog:
                    raise LookupError("unknown_table")
                queries.append(table)
                self_outer.assertTrue(sql.endswith("LIMIT 129"))
                return Cursor()

        self_outer = self
        inventory = host.read_owner_inventory(Connection(), "p1_work_fixedv2_" + "a" * 32)
        self.assertEqual(set(inventory), set(queries))
        self.assertEqual(len(queries), 11)
        self.assertTrue(set(inventory) <= catalog)
        self.assertTrue(
            {"result_delivery_intents", "result_delivery_possible", "result_delivery_receipts"}
            <= inventory.keys()
        )
        self.assertNotIn("result_deliveries", inventory)
        from psycopg import sql

        with self.assertRaisesRegex(LookupError, "unknown_table"):
            Connection().execute(sql.SQL('SELECT * FROM "owned"."result_deliveries" LIMIT 129'))

    def test_owner_cursor_rejects_overcap_without_pruning(self):
        class Cursor:
            def fetchall(self):
                return [{} for _ in range(129)]

        class Connection:
            def execute(self, _query):
                return Cursor()

        with self.assertRaises(host.GateError) as caught:
            host.read_owner_inventory(Connection(), "p1_work_fixedv2_" + "a" * 32)
        self.assertEqual(caught.exception.code, "invalid_proof")

    def test_nested_failure_retention_waits_actual_settlement_then_copies_exact_owner(self):
        owner = object.__new__(host.DurableWorkRun)
        owner.root, owner.retained = self.directory, self.directory / "outer-artifacts"
        host.private_directory(owner.retained)
        owner.failed_mode, owner.builder_report, owner.nested_cleanup_known = True, None, False
        report = (
            self.directory / ".local/validation/p3-package" / ("fixed-work-" + "a" * 32 + ".json")
        )
        retained = report.with_name(report.stem + "-artifacts")
        host.write_private(retained / "commands/01-build/stdout.bin", b"controlled_capture")
        child = Mock(spec=host.GroupedOwnedProcess)
        child.pid, child.returncode, child.cleanup_failed, child.group_settled = (
            123,
            None,
            True,
            False,
        )
        state = {"closed": False}
        owner.nested_builder = SimpleNamespace(
            report=report,
            retained=retained,
            work=self.directory / "removed-nested-work",
            children=[child],
            children_settled=lambda: state["closed"],
            stage="node_build",
            commands=1,
            captured=18,
        )
        self.assertFalse(owner.retain_nested_failure())
        self.assertFalse((owner.retained / "failed-package-builder").exists())
        state["closed"], owner.nested_cleanup_known = True, True
        child.returncode, child.cleanup_failed, child.group_settled = 0, False, True
        self.assertTrue(owner.retain_nested_failure())
        destination = owner.retained / "failed-package-builder"
        descriptor = json.loads((destination / "descriptor.json").read_bytes())
        self.assertEqual(descriptor["retained_path"], str(retained))
        self.assertEqual(descriptor["children"][0]["pid"], 123)
        self.assertTrue(descriptor["cleanup_complete"])
        self.assertFalse(descriptor["report_exists"])
        self.assertEqual(
            (destination / "artifacts/commands/01-build/stdout.bin").read_bytes(),
            b"controlled_capture",
        )
        self.assertEqual(json.loads((destination / "copy-complete.json").read_bytes())["files"], 1)
        owner.retained = self.directory / "copy-sink-failure"
        host.private_directory(owner.retained)
        with (
            patch.object(owner, "copy_tree", side_effect=OSError("controlled_copy")),
            self.assertRaises(OSError),
        ):
            owner.retain_nested_failure()
        destination = owner.retained / "failed-package-builder"
        self.assertTrue((destination / "descriptor.json").is_file())
        self.assertFalse((destination / "copy-complete.json").exists())
        self.assertEqual(
            (retained / "commands/01-build/stdout.bin").read_bytes(), b"controlled_capture"
        )

    def test_nested_diagnostic_failure_does_not_escape_remaining_cleanup(self):
        owner = object.__new__(host.DurableWorkRun)
        owner.directory = self.directory / "journey"
        host.private_directory(owner.directory)
        with (
            patch.object(
                owner, "retain_nested_failure", side_effect=OSError("controlled_sink")
            ) as retained,
            patch.object(owner.directory.__class__, "rglob", return_value=iter(())),
        ):
            owner.retain_failure_inputs()
        retained.assert_called_once()


class LifetimeControls(unittest.IsolatedAsyncioTestCase):
    async def test_entry_failure_is_observed_before_missing_marker_wait(self):
        async def rejected():
            raise ValueError("controlled_failure")

        pending = asyncio.create_task(rejected())

        async def never(*_args):
            await asyncio.Event().wait()

        with (
            patch.object(fixture, "wait_marker", never),
            self.assertRaisesRegex(ValueError, "controlled_failure"),
        ):
            async with asyncio.timeout(0.2):
                await fixture.wait_entry(pending, "fixed_work_cancelled_held", 123)
        self.assertTrue(pending.done())

    async def test_bundle_closure_attempts_independent_tier_and_retries_before_reader(self):
        calls = []

        class Owner:
            def __init__(self, name, fail=False):
                self.name, self.fail = name, fail

            async def close(self):
                calls.append(self.name)
                if self.fail:
                    raise ValueError("held_owner")

        bundle = object.__new__(fixture.Bundle)
        bundle.runner, bundle.coordinator, bundle.client = (
            Owner("runner", True),
            Owner("coordinator"),
            Owner("reader"),
        )
        with self.assertRaisesRegex(ValueError, "held_owner"):
            await bundle.close()
        self.assertCountEqual(calls, ["runner", "coordinator"])
        bundle.runner.fail = False
        await bundle.close()
        self.assertEqual(calls[-3:], ["runner", "coordinator", "reader"])


if __name__ == "__main__":
    unittest.main()
