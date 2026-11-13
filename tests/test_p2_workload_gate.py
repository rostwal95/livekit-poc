"""Offline adversarial protocol/ownership checks; these are not workload measurements."""

from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from harness.process_control import ProcessControlError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "local-setup/scripts"))
spec = importlib.util.spec_from_file_location(
    "p2_workload_gate_under_test", ROOT / "local-setup/scripts/p2_workload_check.py"
)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class WorkloadGateTests(unittest.TestCase):
    def test_plan_has_no_setup_children_or_measurement(self):
        out = io.StringIO()
        with (
            patch.object(m.core, "load_setup", side_effect=AssertionError("setup forbidden")),
            patch.object(m, "Children", side_effect=AssertionError("children forbidden")),
            patch.object(m, "run", side_effect=AssertionError("measurement forbidden")),
            contextlib.redirect_stdout(out),
        ):
            self.assertEqual(m.main(["--plan"]), 0)
        value = json.loads(out.getvalue())
        self.assertEqual(value["status"], "not_started")
        self.assertFalse(value["measurement_started"])
        self.assertEqual(value["bounds"]["expectedChildren"], 16)
        self.assertEqual(len(value["cases"]), 24)

    def test_manifest_duplicate_unknown_nonfinite_and_changed_limit_reject(self):
        value = copy.deepcopy(m.EXPECTED_MANIFEST)
        m.validate_manifest(json.dumps(value).encode())
        for altered in (
            {**value, "unknown": 1},
            {**value, "schemaVersion": True},
            {**value, "bounds": {**value["bounds"], "totalSeconds": 361}},
            {**value, "bounds": {**value["bounds"], "reportBytes": float("nan")}},
        ):
            with self.assertRaises(m.GateError):
                m.validate_manifest(json.dumps(altered).encode())
        with self.assertRaises(m.GateError):
            m.validate_manifest(b'{"schemaVersion":1,"schemaVersion":1}')

    def test_parser_failure_has_fixed_json_without_raw_argument(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(m.main(["--SENTINEL_PRIVATE"]), 1)
        self.assertEqual(json.loads(out.getvalue())["code"], "invalid_arguments")
        self.assertNotIn("SENTINEL", out.getvalue())

    def env(self, mode="serve"):
        role = (
            "P2_WORKLOAD_OWNER_PASSWORD"
            if mode in m.OWNER_MODES
            else "P2_WORKLOAD_RUNTIME_PASSWORD"
        )
        return {
            "P2_WORKLOAD_DIRECTORY": str(Path(tempfile.gettempdir()).resolve()),
            "P2_WORKLOAD_RUN_ID": "a" * 32,
            "P2_WORKLOAD_PG_PORT": "5432",
            role: "synthetic-password",
        }

    def test_inventory_is_closed_and_all_24_names_unique(self):
        manifest = json.loads(
            (ROOT / "projects/channel-continuity/workloads/bounded-v1.json").read_text()
        )
        self.assertEqual(len(m.CASE_NAMES), 24)
        self.assertEqual(len(set(m.CASE_NAMES)), 24)
        self.assertEqual(manifest["cases"], list(m.CASE_NAMES))
        self.assertEqual(manifest["normalCommands"], list(m.NORMAL_COMMANDS))
        self.assertEqual(m.EXPECTED_CHILDREN, 16)
        self.assertLessEqual(m.EXPECTED_CHILDREN, m.MAX_CHILDREN)
        self.assertEqual(manifest["bounds"]["evidenceBytes"], 16777216)
        self.assertFalse(manifest["resourceSemantics"]["physicalIdentityPruning"])

    def test_closed_mode_cannot_gain_owner_role(self):
        for mode in ("unknown", "INSTALL", None, {}, "serve\n"):
            with self.subTest(mode=mode), self.assertRaises(m.GateError):
                m.validate_child_environment(self.env(), mode)

    def test_each_mode_has_exact_one_credential_role(self):
        for mode in m.MODES:
            m.validate_child_environment(self.env(mode), mode)
            for secret in ("P2_WORKLOAD_OWNER_PASSWORD", "P2_WORKLOAD_RUNTIME_PASSWORD"):
                value = self.env(mode)
                value[secret] = "extra"
                if len(value) == 5:
                    with self.assertRaises(m.GateError):
                        m.validate_child_environment(value, mode)

    def test_no_ambient_or_body_selector_environment(self):
        for key in ("OPENAI_API_KEY", "HTTPS_PROXY", "P2_WORKLOAD_CASE", "P2_WORKLOAD_MAX_INBOX"):
            value = self.env()
            value[key] = "synthetic"
            with self.assertRaises(m.GateError):
                m.validate_child_environment(value, "serve")

    def test_empty_nonstring_ports_and_noncanonical_run_ids(self):
        for key, value in [
            ("P2_WORKLOAD_PG_PORT", "0"),
            ("P2_WORKLOAD_PG_PORT", "65536"),
            ("P2_WORKLOAD_PG_PORT", True),
            ("P2_WORKLOAD_RUN_ID", "a" * 32 + "\n"),
            ("P2_WORKLOAD_DIRECTORY", "relative"),
            ("P2_WORKLOAD_RUNTIME_PASSWORD", ""),
        ]:
            env = self.env()
            env[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(m.GateError):
                m.validate_child_environment(env, "serve")

    def test_stage_protocol_has_no_true_equals_one_or_extra_acceptance(self):
        for mode in m.MODES:
            value = {
                "schemaVersion": 1,
                "status": "passed",
                "mode": mode,
                "nodeVersion": "24.22.2",
                **copy.deepcopy(m.STAGES[mode]),
            }
            self.assertEqual(m.validated_stage(json.dumps(value).encode(), mode), value)
            value["schemaVersion"] = True
            with self.assertRaises(m.GateError):
                m.validated_stage(json.dumps(value).encode(), mode)
            value["schemaVersion"] = 1
            value["extra"] = "not reviewed"
            with self.assertRaises(m.GateError):
                m.validated_stage(json.dumps(value).encode(), mode)

    def test_stage_duplicate_json_and_nonfinite_are_rejected(self):
        for raw in (b'{"schemaVersion":1,"schemaVersion":1}', b'{"x":NaN}', b"[]", b"x" * 32769):
            with self.assertRaises(m.GateError):
                m.validated_stage(raw, "serve")

    def test_catalog_requires_exact_frozen_owner_ddl_names(self):
        expected = m.EXPECTED_MANIFEST["catalog"]["tables"]
        self.assertEqual(len(expected), 29)
        self.assertEqual(m.validate_catalog_names(expected), expected)
        for names in (
            expected[:-1],
            [*expected, "foreign_table"],
            [*expected[:-1], expected[0]],
            [*expected[:-1], "other_schema_table"],
            [*expected[:-1], {}],
        ):
            with self.subTest(names=names), self.assertRaises(m.GateError):
                m.validate_catalog_names(names)

    def test_backend_binding_exact_child_schema_distinct_pids(self):
        value = {
            "schemaVersion": 1,
            "phase": "burst",
            "processId": 123,
            "schema": m.schemas("a" * 32)[0],
            "backendIds": [55, 66],
        }
        self.assertEqual(
            m.validated_backends(json.dumps(value).encode(), run_id="a" * 32, process_id=123),
            (55, 66),
        )
        for key, wrong in [
            ("processId", 124),
            ("schema", m.schemas("b" * 32)[0]),
            ("backendIds", [55, 55]),
            ("backendIds", [True, 66]),
            ("backendIds", [66, 55]),
            ("backendIds", [55]),
            ("phase", "expiry"),
        ]:
            altered = {**value, key: wrong}
            with self.subTest(key=key), self.assertRaises(m.GateError):
                m.validated_backends(json.dumps(altered).encode(), run_id="a" * 32, process_id=123)

    def test_quantiles_omit_unjustified_p95(self):
        for n in (0, 1, 19, 20, 1000):
            value = {
                "count": n,
                "p50Ms": 1 if n else None,
                "maximumMs": 2 if n else None,
                **({"p95Ms": 1.9} if n >= 20 else {}),
            }
            m.validate_latency(value)
            if n < 20:
                value["p95Ms"] = 2
                with self.assertRaises(m.GateError):
                    m.validate_latency(value)

    def test_quantitative_nonfinite_bool_range_and_order_fail_closed(self):
        for value in (
            {"count": True, "p50Ms": 1, "maximumMs": 2},
            {"count": 20, "p50Ms": 1, "p95Ms": float("inf"), "maximumMs": 2},
            {"count": 1, "p50Ms": 3, "maximumMs": 2},
            {"count": 20, "p50Ms": 1, "p95Ms": 0.5, "maximumMs": 2},
            {"count": 2001, "p50Ms": 1, "p95Ms": 2, "maximumMs": 3},
        ):
            with self.subTest(value=value), self.assertRaises(m.GateError):
                m.validate_latency(value)

    def test_sorted_ascii_snapshot_hash_is_reproducible_and_order_sensitive_for_rows(self):
        a = {"unicode": "é", "rows": [{"z": 1, "a": 2}]}
        b = {"rows": [{"a": 2, "z": 1}], "unicode": "é"}
        self.assertEqual(m.snapshot_digest(a), m.snapshot_digest(b))
        self.assertNotEqual(m.snapshot_digest([1, 2]), m.snapshot_digest([2, 1]))
        with self.assertRaises(m.GateError):
            m.snapshot_digest({"x": float("nan")})

    def test_private_proof_guards_link_mode_and_size(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "proof.json"
            p.write_bytes(b"{}")
            p.chmod(0o600)
            self.assertEqual(m.bounded_read(p), b"{}")
            p.chmod(0o644)
            with self.assertRaises(m.GateError):
                m.bounded_read(p)
            p.chmod(0o600)
            with self.assertRaises(m.GateError):
                m.bounded_read(p, 1)
            linked = Path(temp) / "linked.json"
            linked.symlink_to(p)
            with self.assertRaises(m.GateError):
                m.bounded_read(linked)
            os.link(p, Path(temp) / "hard.json")
            with self.assertRaises(m.GateError):
                m.bounded_read(p)

    def test_index_rejects_missing_extra_tampered_and_self_indexed_file(self):
        for change in ("extra", "missing", "tamper", "self"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                p = directory / "proof.json"
                p.write_bytes(b"{}")
                p.chmod(0o600)
                m.evidence_index(directory)
                sha = m.hashlib.sha256((directory / "retained-index.json").read_bytes()).hexdigest()
                m.validate_evidence_index(directory, sha)
                if change == "extra":
                    q = directory / "extra.json"
                    q.write_bytes(b"{}")
                    q.chmod(0o600)
                elif change == "missing":
                    p.unlink()
                elif change == "tamper":
                    p.write_bytes(b"[]")
                else:
                    index = json.loads((directory / "retained-index.json").read_text())
                    index["files"]["retained-index.json"] = {"bytes": 2, "sha256": "a" * 64}
                    (directory / "retained-index.json").write_text(json.dumps(index))
                    sha = m.hashlib.sha256(
                        (directory / "retained-index.json").read_bytes()
                    ).hexdigest()
                with self.assertRaises((m.GateError, OSError)):
                    m.validate_evidence_index(directory, sha)

    def test_child_close_attempts_all_independent_owners_after_cancellation(self):
        seen = []

        class Child:
            returncode = 0
            cleanup_failed = False
            group_settled = True

            def __init__(self, label):
                self.label = label

            def close(self):
                seen.append(self.label)
                if self.label == "first":
                    raise m.asyncio.CancelledError()

        with tempfile.TemporaryDirectory() as temp:
            children = m.Children(Path(temp).resolve(), m.time.monotonic() + 5)
            children.children = [Child("second"), Child("first")]
            with self.assertRaises(m.GateError):
                children.close()
        self.assertEqual(seen, ["first", "second"])

    def test_parent_control_connections_remain_owned_after_failed_close(self):
        class Connection:
            def __init__(self, pid, fail=False):
                self.info = SimpleNamespace(backend_pid=pid)
                self.closed = False
                self.fail = fail
                self.calls = 0

            def close(self):
                self.calls += 1
                if self.fail:
                    raise RuntimeError("private")
                self.closed = True

        owner = m.ControlConnections()
        a = Connection(1, True)
        b = Connection(2)
        owner.retain(a)
        owner.retain(b)
        self.assertFalse(owner.close())
        self.assertEqual(a.calls, 1)
        self.assertEqual(b.calls, 1)
        self.assertFalse(owner.settled())
        self.assertEqual(owner.proof()["maximumLive"], 2)
        a.fail = False
        self.assertTrue(owner.close())
        self.assertTrue(owner.proof()["allClosed"])
        self.assertEqual(owner.proof()["possibleRuntimePlusControlConnections"], 10)

    def test_dependent_ddl_guard_requires_actual_exit_and_reap(self):
        for child, expected in [
            (SimpleNamespace(returncode=0, cleanup_failed=False, group_settled=True), True),
            (SimpleNamespace(returncode=None, cleanup_failed=False, group_settled=True), False),
            (SimpleNamespace(returncode=0, cleanup_failed=True, group_settled=True), False),
            (SimpleNamespace(returncode=0, cleanup_failed=False, group_settled=False), False),
        ]:
            self.assertEqual(
                m.owned_children_settled(SimpleNamespace(children=[child], start_failed=False)),
                expected,
            )

    def test_actual_node_fixture_markers_interoperate_with_real_file_barrier(self):
        fixture = (ROOT / "projects/channel-continuity/tests/pg_workload_cases.ts").read_text()
        start = fixture.index("async function until(")
        end = fixture.index("function sample(", start)
        helpers = fixture[start:end]
        node = m.shutil.which("node")
        self.assertIsNotNone(node)
        for wrong in (False, True):
            with self.subTest(wrong=wrong), tempfile.TemporaryDirectory() as temp:
                work = Path(temp).resolve()
                work.chmod(0o700)
                marker = m.FileBarrier(work, "workload_slow_held")
                script = work / "probe.mts"
                script.write_text(
                    "import assert from 'node:assert/strict';import{setTimeout as delay}from'node:timers/promises';import{openSync,closeSync,writeSync,readSync,fsyncSync,fstatSync,linkSync,unlinkSync,constants}from'node:fs';const DIR="
                    + json.dumps(str(work))
                    + ";"
                    + helpers
                    + "await barrier('workload_slow_held');console.log('passed');"
                )
                children = m.Children(work, m.time.monotonic() + 8)
                child = children.start(
                    "marker", [node, str(script)], m.core.base_environment(), cwd=work
                )
                try:
                    child.wait_for_barrier(marker, timeout=3)
                    self.assertEqual(
                        (work / "workload_slow_held.reached").read_bytes(),
                        f"{child.pid}\n".encode(),
                    )
                    if wrong:
                        release = work / "workload_slow_held.released"
                        release.write_bytes(b"1\n")
                        release.chmod(0o600)
                        with self.assertRaises(m.GateError):
                            children.finish(child)
                    else:
                        child.release_barrier(marker)
                        self.assertEqual(children.finish(child), b"passed\n")
                    self.assertFalse(list(work.glob("*.pending")))
                finally:
                    children.close()
                self.assertTrue(m.owned_children_settled(children))

    def test_child_umask_applies_before_third_party_capture_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp).resolve()
            work.chmod(0o700)
            children = m.Children(work, m.time.monotonic() + 5)
            try:
                children.call(
                    "write",
                    [
                        sys.executable,
                        "-I",
                        "-c",
                        "from pathlib import Path; Path('third-party.json').write_text('{}')",
                    ],
                    m.core.base_environment(),
                    cwd=work,
                )
                self.assertEqual((work / "third-party.json").stat().st_mode & 0o777, 0o600)
                self.assertTrue(m.owned_children_settled(children))
            finally:
                children.close()

    def test_child_output_overflow_is_not_a_pass_or_schema_cleanup_authority(self):
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp).resolve()
            work.chmod(0o700)
            children = m.Children(work, m.time.monotonic() + 5)
            try:
                with self.assertRaises(ProcessControlError):
                    children.call(
                        "overflow",
                        [
                            sys.executable,
                            "-I",
                            "-c",
                            "import sys;sys.stdout.write('x'*9000);sys.stdout.flush()",
                        ],
                        m.core.base_environment(),
                        cwd=work,
                    )
            finally:
                children.close()
            self.assertTrue(m.owned_children_settled(children))

    def test_oversized_numeric_values_are_fixed_validation_failures(self):
        for value in (10**1000, -(10**1000), float("inf"), True):
            self.assertFalse(m.bounded_number(value, 0, 5000))
        with self.assertRaises(m.GateError):
            m.validate_latency({"count": 1, "p50Ms": 10**1000, "maximumMs": 10**1000})

    def resource_fixture(self):
        sample = {
            "population": -1,
            "eventLoopMaxMs": 20,
            "monotonicMs": 100,
            "rssBytes": 100000000,
            "heapUsedBytes": 10000000,
            "externalBytes": 1000000,
            "cpuUserMicroseconds": 100000,
            "cpuSystemMicroseconds": 10000,
        }
        quantile = lambda n: {
            "count": n,
            "p50Ms": 10,
            "maximumMs": 20,
            **({"p95Ms": 15} if n >= 20 else {}),
        }
        dormant = {
            "schemaVersion": 1,
            "workloadSeed": 39,
            "performanceBudgets": m.EXPECTED_MANIFEST["performanceBudgets"],
            "scope": "one_node_process_sequential_reader_windows",
            "samples": [{**sample, "population": n} for n in [0, 64, 256, 1000]],
            "processSamples": [sample],
            "cohort": "public_associate_accept_inspect_1000",
            "latencyMs": quantile(1000),
            "readersConcurrent": 1,
            "maximumCredentialWindow": 64,
            "roomsAllocated": 0,
            "agentsAllocated": 0,
        }
        terminal = {
            k: 0 for k in ["active", "intakes", "sockets", "handlers", "driver", "observerPending"]
        }
        capacity = {
            "schemaVersion": 1,
            "workloadSeed": 39,
            "performanceBudgets": m.EXPECTED_MANIFEST["performanceBudgets"],
            "scope": "one_node_process_two_gateways",
            "cleanupComplete": True,
            "configured": {
                "gateways": 2,
                "pools": 4,
                "connections": 8,
                "retainedSqlOperations": 16,
                "dispatcherTasksPerInstance": 2,
                "persistedClaimsPerSchema": 2,
            },
            "observed": {
                "prepareMaximum": 2,
                "httpMaximum": 8,
                "preacceptance": [
                    {
                        "eventId": "00000000-0000-4000-8000-" + str(i).zfill(12),
                        "status": 429,
                        "code": "capacity",
                        "receiptPresent": False,
                    }
                    for i in range(4)
                ],
                "pools": [{"total": 2, "waiting": 2, "occupied": 4}] * 4,
                "snapshots": [
                    {
                        "phase": "burst_held",
                        "pools": [{"total": 2, "idle": 0, "waiting": 2}] * 4,
                        "gateway": [{"active": 4}],
                    }
                ],
            },
            "samples": [sample],
            "usefulCompletionMs": quantile(63),
            "cohorts": {
                k: quantile(n)
                for k, n in [("steady", 16), ("burst", 3), ("slow", 4), ("capfill", 40)]
            },
            "observer": {
                "beforeSqlClose": {
                    "observerPending": 8,
                    "observerDropped": 12,
                    "observerFailures": 0,
                },
                "afterSqlClose": {
                    "observerPending": 8,
                    "observerDropped": 13,
                    "observerFailures": 0,
                },
                "afterActualCallbackSettlement": {
                    "observerPending": 0,
                    "observerDropped": 13,
                    "observerFailures": 0,
                },
            },
            "terminalGateways": [terminal, terminal],
        }
        return dormant, capacity

    def test_resource_envelopes_reject_bool_version_missing_or_unknown_keys(self):
        for field in (
            "dormant_version",
            "capacity_version",
            "capacity_unknown",
            "capacity_missing",
        ):
            dormant, capacity = copy.deepcopy(self.resource_fixture())
            if field == "dormant_version":
                dormant["schemaVersion"] = True
            elif field == "capacity_version":
                capacity["schemaVersion"] = "UNREVIEWED"
            elif field == "capacity_unknown":
                capacity["unknown"] = 1
            else:
                del capacity["schemaVersion"]
            with (
                patch.object(m, "json_file", side_effect=[dormant, capacity]),
                self.subTest(field=field),
                self.assertRaises(m.GateError),
            ):
                m.validate_resources(Path("unused"))

    def test_empty_raw_capture_is_retained_and_indexed_without_allowing_empty_json(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            p = directory / "capture-compile-stderr.bin"
            p.write_bytes(b"")
            p.chmod(0o600)
            with self.assertRaises(m.GateError):
                m.bounded_read(p)
            self.assertEqual(m.bounded_read(p, allow_empty=True), b"")
            q = directory / "proof.json"
            q.write_bytes(b"{}")
            q.chmod(0o600)
            m.evidence_index(directory)
            sha = m.hashlib.sha256((directory / "retained-index.json").read_bytes()).hexdigest()
            self.assertEqual(m.validate_evidence_index(directory, sha)["files"][p.name]["bytes"], 0)

    def test_resource_proof_budgets_are_independent_of_claimed_pass_flags(self):
        for mutate in (
            None,
            "rss",
            "loop",
            "admission",
            "completion",
            "missingOwner",
            "falseDrain",
            "malformed",
        ):
            dormant, capacity = copy.deepcopy(self.resource_fixture())
            if mutate == "rss":
                capacity["samples"][0]["rssBytes"] = 536870913
            elif mutate == "loop":
                dormant["processSamples"][0]["eventLoopMaxMs"] = 1000.1
            elif mutate == "admission":
                capacity["cohorts"]["burst"]["maximumMs"] = 5001
            elif mutate == "completion":
                capacity["usefulCompletionMs"]["maximumMs"] = 15001
            elif mutate == "missingOwner":
                capacity["observed"]["pools"].pop()
            elif mutate == "falseDrain":
                capacity["terminalGateways"][0]["handlers"] = 1
            elif mutate == "malformed":
                capacity = []
            with patch.object(m, "json_file", side_effect=[dormant, capacity]):
                if mutate is None:
                    self.assertIn("capacity", m.validate_resources(Path("unused")))
                else:
                    with self.subTest(mutate=mutate), self.assertRaises(m.GateError):
                        m.validate_resources(Path("unused"))

    def test_final_report_requires_all_cases_exact_children_and_cleanup(self):
        value = {
            "schema_version": 1,
            "status": "passed",
            "mode": m.MODE,
            "tests": 24,
            "passed": 24,
            "cases": list(m.CASE_NAMES),
            "workload_seed": 39,
            "child_commands": 16,
            "capacity_inputs": 64,
            "dormant_inputs": 1002,
            "operation_acceptances": 68,
            "owned_sql_graphs": 1,
            "owned_sql_waiters": 2,
            "rooms_allocated": 0,
            "agents_allocated": 0,
            "cleanup_complete": True,
            "node_version": "24.22.2",
            "capacity_claimed": False,
            "duration_seconds": 10.0,
            "retained_index_sha256": "a" * 64,
        }
        m.validated_report(json.dumps(value).encode())
        for key, wrong in [
            ("passed", 23),
            ("child_commands", 14),
            ("cleanup_complete", False),
            ("duration_seconds", 360),
            ("operation_acceptances", True),
            ("capacity_claimed", True),
            ("cases", list(m.CASE_NAMES[:-1])),
        ]:
            with self.subTest(key=key), self.assertRaises(m.GateError):
                m.validated_report(json.dumps({**value, key: wrong}).encode())

    def test_report_path_never_reuses_or_escapes_owned_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for path in (
                Path("/tmp/x.json"),
                Path(".local/validation/p2-workload/../escape.json"),
                Path(".local/validation/p2-workload/a.JSON"),
            ):
                with self.assertRaises(m.GateError):
                    m.target_path(root, path)
            path = Path(".local/validation/p2-workload/first.json")
            target = m.target_path(root, path)
            target.write_text("{}")
            with self.assertRaises(m.GateError):
                m.target_path(root, path)


if __name__ == "__main__":
    unittest.main()
