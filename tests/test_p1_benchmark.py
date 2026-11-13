"""Offline workload controller contracts; never start Docker or a remote provider."""

import asyncio
import copy
import importlib.util
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import httpx

from harness.workload_models import load_workload_manifest

SPEC = importlib.util.spec_from_file_location(
    "p1_benchmark_under_test",
    Path(__file__).resolve().parents[1] / "local-setup/scripts/p1_benchmark.py",
)
bench = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bench
SPEC.loader.exec_module(bench)
REPO = Path(__file__).resolve().parents[1]
if not (REPO / "harness/workloads/p1-inquiry-v1.json").exists():
    REPO = Path.cwd()
MANIFEST = load_workload_manifest(REPO / "harness/workloads/p1-inquiry-v1.json")
TASK = "11111111-1111-4111-8111-111111111111"
CASE = "22222222-2222-4222-8222-222222222222"
EFFECT = "33333333-3333-4333-8333-333333333333"


def inquiry(index=0):
    return bench.Investigation(
        index,
        f"request-{index}",
        {"booking_reference": "DEMO-BK-001", "new_check_in": "2030-12-10", "confirmed": True},
    )


def projection(item, *, state="succeeded", cancelled=False):
    return {
        "schema_version": 1,
        "task_id": TASK,
        "case_id": CASE,
        "request_key": item.key,
        "request": item.request,
        "inquiry": {
            "state": state,
            "effect_id": EFFECT,
            "request": item.request,
            "result": {
                "booking_reference": "DEMO-BK-001",
                "new_check_in": "2030-12-10",
                "available": True,
            }
            if state == "succeeded"
            else None,
        },
        "quote": None,
        "effect": None,
        "confirmation": {"state": "cancelled" if cancelled else "not_requested"},
        "outcome": {"state": "cancelled"} if cancelled else None,
        "delivery": {"state": "delivered"} if cancelled else None,
    }


def receipt(item, *, created=True):
    current = projection(item)
    return {"created": created, "task_id": TASK, "case_id": CASE, "projection": current}


def reconciled():
    item = inquiry()
    bench.acceptance(receipt(item), item, replay=False)
    item.result_at, item.cancelled = 1.0, True
    rows = [
        {
            "task_id": TASK,
            "key": item.key,
            "payload": bench.canonical(item.request).decode(),
            "effect_id": EFFECT,
        }
    ]
    result = {"booking_reference": "DEMO-BK-001", "new_check_in": "2030-12-10", "available": True}
    import hashlib

    authority = {
        "booking_unchanged": True,
        "apply_calls": 0,
        "mutations": 0,
        "receiver_events": 1,
        "inquiries": [
            {
                "effect_id": EFFECT,
                "request_sha256": hashlib.sha256(bench.canonical(item.request)).hexdigest(),
                "result_sha256": hashlib.sha256(bench.canonical(result)).hexdigest(),
            }
        ],
    }
    return item, rows, authority


class BenchmarkContracts(unittest.TestCase):
    def test_slow_resource_probe_skips_missed_slots_instead_of_back_to_back_sampling(self):
        self.assertEqual(bench.next_resource_tick(1.0, 0.2, 1), (1.0, 0))
        self.assertEqual(bench.next_resource_tick(1.0, 2.2, 1), (3.0, 2))
        self.assertEqual(bench.next_resource_tick(2.0, 2.0, 1), (3.0, 1))

    def test_budget_uses_original_deadline_and_rejects_nonfinite_or_reversed_clock(self):
        now = [0.0]
        budget = bench.Budget(10, clock=lambda: now[0])
        now[0] = 9
        self.assertEqual(budget.remaining(5), 1)
        now[0] = 10
        with self.assertRaises(bench.BenchmarkError):
            budget.remaining()
        now[0] = -1
        with self.assertRaises(bench.BenchmarkError):
            budget.remaining()
        for value in (True, float("nan"), float("inf"), 0, 601):
            with self.subTest(value=value), self.assertRaises(ValueError):
                bench.Budget(value)

    def test_json_bounds_duplicates_and_nonfinite_numbers_fail_before_use(self):
        self.assertEqual(bench.strict_json(b'{"a":1}'), {"a": 1})
        for raw in (b"", b'{"a":1,"a":2}', b'{"a":NaN}', b"x" * 65537):
            with self.subTest(length=len(raw)), self.assertRaises(bench.BenchmarkError):
                bench.strict_json(raw)

    def test_owned_names_cannot_select_main_stack_or_unknown_experiment(self):
        self.assertEqual(bench.owned_prefix("a" * 32, 0), "p1-h-" + "a" * 32 + "-0")
        for arguments in (("main", 0), ("a" * 32, True), ("a" * 32, -1), ("a" * 32, 6)):
            with self.subTest(arguments=arguments), self.assertRaises(bench.BenchmarkError):
                bench.owned_prefix(*arguments)

    def test_resource_samples_require_observed_finite_caps_and_accounted_memory(self):
        observed = {
            "cpu_usage_usec": 12345,
            "memory_current_bytes": 123456,
            "pids_current": 7,
            "cpu_quota_usec": 100000,
            "cpu_period_usec": 100000,
            "memory_limit_bytes": 536870912,
            "pids_limit": 128,
        }
        self.assertEqual(
            asdict(bench.CgroupObservation.parse(observed, MANIFEST.api_resources)), observed
        )
        for changes in (
            {"cpu_usage_usec": False},
            {"memory_current_bytes": -1},
            {"pids_current": 0},
            {"cpu_quota_usec": 200000},
            {"memory_limit_bytes": 0},
            {"private": "token"},
        ):
            with self.subTest(changes=changes), self.assertRaises(bench.BenchmarkError):
                bench.CgroupObservation.parse({**observed, **changes}, MANIFEST.api_resources)
        compile(bench.CGROUP_SCRIPT, "cgroup-probe", "exec")
        overage = {**observed, "pids_current": 129, "memory_current_bytes": 536870913}
        self.assertEqual(
            asdict(bench.CgroupObservation.parse(overage, MANIFEST.api_resources)), overage
        )

    def test_projection_rejects_changed_key_payload_ids_or_manufactured_result(self):
        original = inquiry()
        bench.acceptance(receipt(original), original, replay=False)
        for change in (
            {"request_key": "other"},
            {"task_id": CASE},
            {"schema_version": True},
            {"effect": {"state": "succeeded"}},
            {"quote": {"confirmed": True}},
        ):
            with self.subTest(change=change), self.assertRaises(bench.BenchmarkError):
                bench.projection({**projection(original), **change}, original)
        bad = projection(original)
        bad["inquiry"]["result"]["available"] = False
        with self.assertRaises(bench.BenchmarkError):
            bench.projection(bad, original)
        with self.assertRaises(bench.BenchmarkError):
            bench.acceptance(receipt(original, created=True), original, replay=True)

    def test_reconciliation_matches_every_original_identity_and_independent_effect_digest(self):
        item, rows, authority = reconciled()
        result = bench.reconcile([item], rows, authority, 1, 0)
        self.assertEqual(result["inquiry_succeeded"], 1)
        self.assertEqual(result["explicitly_cancelled_after_measurement"], 1)
        self.assertEqual(
            (result["lost_accepted"], result["apply_calls"], result["mutations"]), (0, 0, 0)
        )
        for change in (
            {"apply_calls": 1},
            {"apply_calls": False},
            {"mutations": 1},
            {"booking_unchanged": False},
            {"receiver_events": 0},
            {"inquiries": []},
            {"inquiries": authority["inquiries"] * 2},
        ):
            with self.subTest(change=change), self.assertRaises(bench.BenchmarkError):
                bench.reconcile([item], rows, {**authority, **change}, 1, 0)
        for changed_rows in (
            [],
            rows * 2,
            [{**rows[0], "key": "other"}],
            [{**rows[0], "payload": "{}"}],
        ):
            with self.subTest(rows=len(changed_rows)), self.assertRaises(bench.BenchmarkError):
                bench.reconcile([item], changed_rows, authority, 1, 0)
        with self.assertRaises(bench.BenchmarkError):
            bench.reconcile(
                [item, copy.copy(item)], rows, {**authority, "receiver_events": 2}, 2, 0
            )
        item.result_at = None
        with self.assertRaises(bench.BenchmarkError):
            bench.reconcile([item], rows, authority, 1, 0)
        compile(bench.AUTHORITY_SCRIPT, "independent-authority-probe", "exec")

    def test_small_samples_report_only_count_minimum_median_maximum(self):
        self.assertEqual(
            bench.timing_summary([3.0, 1.0, 2.0]),
            {"samples": 3, "minimum_seconds": 1.0, "median_seconds": 2.0, "maximum_seconds": 3.0},
        )
        for invalid in ([], [True], [float("nan")], [-1]):
            with self.assertRaises(bench.BenchmarkError):
                bench.timing_summary(invalid)

    def test_evidence_caps_and_closed_vocabulary_prevent_secret_and_fake_counter_retention(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "samples.jsonl"
            log = bench.EvidenceLog(path, 1)
            sample = {
                "role": "api",
                "worker_index": 0,
                "cpu_usage_usec": 1,
                "memory_current_bytes": 2,
                "pids_current": 3,
                "cpu_quota_usec": 100000,
                "cpu_period_usec": 100000,
                "memory_limit_bytes": 536870912,
                "pids_limit": 128,
                "probe_started_seconds": 0.01,
                "probe_finished_seconds": 0.02,
                "probe_duration_seconds": 0.01,
            }
            try:
                for changes in (
                    {"token": "private"},
                    {"memory_current_bytes": True},
                    {"worker_index": 3},
                ):
                    with self.subTest(changes=changes), self.assertRaises(bench.BenchmarkError):
                        log.record("steady-w1", "resource", 0.1, **{**sample, **changes})
                log.record("steady-w1", "resource", 0.1, **sample)
                with self.assertRaises(bench.BenchmarkError):
                    log.record("steady-w1", "resource", 0.2, **sample)
            finally:
                log.close()
            self.assertNotIn("private", path.read_text())
            self.assertEqual(len(path.read_text().splitlines()), 1)

    def test_closed_failure_context_rejects_tampered_values_without_serializing_exceptions(self):
        error = bench.BenchmarkError("dependency_unavailable", operation="provenance")
        error.raw_output = "private-sentinel-never-retain"
        error.argv = ["private-sentinel-never-retain"]
        self.assertEqual(
            bench.failure_observation(error),
            {"code": "dependency_unavailable", "operation": "provenance", "command": None},
        )
        error.operation = "private-sentinel-never-retain"
        observed = bench.failure_observation(error)
        self.assertEqual(
            observed, {"code": "invalid_evidence", "operation": "unknown", "command": None}
        )
        self.assertNotIn("private-sentinel", json.dumps(observed))
        for changes in (
            {"exit_code": True},
            {"timed_out": 1},
            {"timeout_seconds": float("nan")},
            {"elapsed_seconds": -1},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                bench.CommandObservation(
                    **{
                        "exit_code": 7,
                        "timed_out": False,
                        "timeout_seconds": 5.0,
                        "elapsed_seconds": 0.1,
                        **changes,
                    }
                )


class HTTPBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.log = bench.EvidenceLog(Path(self.directory.name) / "samples.jsonl", 4096)
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(self.log.close)

    async def driver(self, handler, experiment=None):
        driver = bench.HTTPDriver(
            "http://127.0.0.1:18082",
            "private-token",
            bench.Budget(10),
            bench.Budget(10),
            self.log,
            experiment or MANIFEST.experiments[0],
            5,
        )
        await driver.client.aclose()
        driver.client = httpx.AsyncClient(
            base_url="http://127.0.0.1:18082",
            transport=httpx.MockTransport(handler),
            headers={"Authorization": "Bearer private-token"},
            trust_env=False,
        )
        self.addAsyncCleanup(driver.client.aclose)
        return driver

    async def test_all_http_operations_share_the_declared_concurrency_limit(self):
        active, maximum = 0, 0

        async def handle(request):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0.01)
            active -= 1
            return httpx.Response(200, json={})

        driver = await self.driver(handle)
        item = inquiry()
        item.scheduled_offer_at = driver.budget.clock()
        await asyncio.gather(
            *(
                driver.request(item, operation, "/test", {} if operation != "get" else None)
                for operation in ("submit", "get", "replay", "cancel")
            )
        )
        self.assertEqual(maximum, 1)
        self.assertEqual(self.log.count, 4)

    async def test_readiness_polls_connection_refusal_with_bounded_streamed_shared_client(self):
        attempts = []

        async def handle(request):
            attempts.append(request.url.path)
            if len(attempts) == 1:
                raise httpx.ConnectError("private")
            return httpx.Response(200, json={"status": "ready", "dependencies": {"postgres": True}})

        driver = await self.driver(handle)
        lab = SimpleNamespace(budget=driver.budget, overall=driver.overall, serving=[])
        await bench.wait_ready(lab, driver, workers=False)
        self.assertEqual(attempts, ["/readyz", "/readyz"])

    async def test_unknown_ack_replays_the_identical_original_body_and_preserves_actual_timings(
        self,
    ):
        item = inquiry()
        bodies = []

        async def handle(request):
            bodies.append(request.content)
            if len(bodies) == 1:
                raise httpx.ReadTimeout("private-provider-exception")
            return httpx.Response(200, json=receipt(item))

        driver = await self.driver(handle)
        item.scheduled_offer_at = driver.budget.clock()
        await driver.submit(item)
        self.assertEqual(bodies[0], bodies[1])
        self.assertEqual(item.task_id, TASK)
        self.assertIsNotNone(item.acknowledged_at)
        raw = (Path(self.directory.name) / "samples.jsonl").read_text()
        self.assertNotIn("private-token", raw)
        self.assertNotIn("private-provider-exception", raw)
        records = [
            json.loads(line) for line in raw.splitlines() if json.loads(line)["kind"] == "http"
        ]
        self.assertEqual([record["http_status"] for record in records], [0, 200])
        self.assertLessEqual(
            records[0]["scheduled_offer_seconds"], records[0]["http_start_seconds"]
        )
        self.assertLessEqual(
            records[0]["http_start_seconds"], records[0]["attempt_finished_seconds"]
        )
        result_records = [
            json.loads(line) for line in raw.splitlines() if json.loads(line)["kind"] == "result"
        ]
        self.assertEqual(len(result_records), 1)
        self.assertEqual(result_records[0]["observation_source"], "submit")

    async def test_explicit_capacity_rejection_has_no_accepted_identity_and_replay_cannot_be_rejected(
        self,
    ):
        driver = await self.driver(
            lambda request: httpx.Response(503, json={"code": "capacity_exhausted"})
        )
        rejected = inquiry()
        rejected.scheduled_offer_at = driver.budget.clock()
        await driver.submit(rejected, reject=True)
        self.assertTrue(rejected.rejected)
        self.assertIsNone(rejected.task_id)
        original = inquiry()
        original.scheduled_offer_at = driver.budget.clock()
        with self.assertRaises(bench.BenchmarkError):
            await driver.submit(original, replay=True)

    async def test_permanent_unknown_ack_is_nonpassing_and_is_not_fabricated_as_rejection(self):
        async def handle(request):
            raise httpx.ReadTimeout("private")

        driver = await self.driver(handle)
        item = inquiry()
        item.scheduled_offer_at = driver.budget.clock()
        with self.assertRaises(bench.BenchmarkError) as caught:
            await driver.submit(item)
        self.assertEqual(caught.exception.code, "http_unknown")
        self.assertFalse(item.rejected)
        self.assertIsNone(item.task_id)
        self.assertEqual(self.log.count, 3)

    async def test_cancellation_uses_only_stable_explicit_controller_command_after_result(self):
        item, _, _ = reconciled()
        bodies = []

        async def handle(request):
            self.assertTrue(request.url.path.endswith("/cancel"))
            body = json.loads(request.content)
            bodies.append(body)
            return httpx.Response(
                200,
                json={
                    "projection": projection(item, cancelled=True),
                    "receipt": {
                        "command_id": body["command_id"],
                        "created": True,
                        "cancellation_id": CASE,
                        "disposition": "cancelled_before_commit",
                    },
                },
            )

        driver = await self.driver(handle)
        await driver.cancel(item)
        await driver.cancel(item)
        self.assertEqual(bodies[0], bodies[1])
        self.assertTrue(item.cancelled)

    async def test_concurrent_sampler_cannot_replace_the_original_admission_failure_context(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def handle(request):
            entered.set()
            await release.wait()
            return httpx.Response(500, json={"private": "private-exception-sentinel"})

        @bench.at_operation("sampling")
        def sample_failure():
            raise bench.BenchmarkError("resource_mismatch")

        driver = await self.driver(handle)
        item = inquiry()
        item.scheduled_offer_at = driver.budget.clock()
        submission = asyncio.create_task(driver.submit(item))
        await entered.wait()
        sampling = asyncio.create_task(asyncio.to_thread(sample_failure))
        sampled = (await asyncio.gather(sampling, return_exceptions=True))[0]
        self.assertEqual(bench.failure_observation(sampled)["operation"], "sampling")
        release.set()
        admitted = (await asyncio.gather(submission, return_exceptions=True))[0]
        with (
            self.assertRaises(bench.BenchmarkError) as caught,
            bench.operation_scope("reconciliation"),
        ):
            raise ExceptionGroup("private-exception-sentinel", [admitted])
        observed = bench.failure_observation(caught.exception)
        self.assertEqual(observed["operation"], "admission")
        self.assertEqual(observed["code"], "dependency_unavailable")
        self.assertNotIn("private-exception-sentinel", json.dumps(observed))
        self.assertEqual(bench._OPERATION.get(), "unknown")


class OwnershipTests(unittest.TestCase):
    def lab(self, directory):
        values = {
            "POSTGRES_PORT": "15432",
            "POSTGRES_PASSWORD": "p" * 40,
            "POSTGRES_MIGRATION_PASSWORD": "m" * 40,
            "LIVEKIT_HTTP_PORT": "17880",
            "LIVEKIT_API_KEY": "key",
            "LIVEKIT_API_SECRET": "s" * 40,
        }
        stack = SimpleNamespace(
            SECRET_KEYS={"POSTGRES_PASSWORD", "POSTGRES_MIGRATION_PASSWORD", "LIVEKIT_API_SECRET"},
            child_environment=lambda values: {"PATH": os.defpath},
        )
        return bench.DockerExperiment(
            REPO,
            stack,
            values,
            "sha256:" + "1" * 64,
            "owned_lab",
            "a" * 32,
            0,
            MANIFEST.experiments[0],
            MANIFEST,
            Path(directory).resolve(),
            bench.Budget(600),
        )

    def test_refused_existing_schema_is_never_selected_for_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            lab = self.lab(directory)
            calls = []

            def command(argv, **kwargs):
                calls.append(argv)
                return '{"status":"refused"}'

            lab.command = command
            with self.assertRaises(bench.BenchmarkError):
                lab.prepare_schema()
            self.assertFalse(lab._schema_candidate)
            lab.cleanup()
            self.assertEqual(len(calls), 1)
            self.assertIn(bench.PG_PREPARE_SCRIPT, calls[0])

    def test_namespace_cleanup_child_requires_exact_marker_owner_and_oid_before_any_drop(self):
        from continuity_lab.postgres_settings import PostgresSettings

        schema = "p1_benchmark_" + "a" * 32 + "_0"
        marker = "owned-marker-private"
        for change in ({"marker": "foreign"}, {"owner": "foreign"}, {"oid": 999}):
            row = {"oid": 123, "owner": "continuity_migrator", "marker": marker, **change}
            connection = MagicMock()
            connection.__enter__.return_value = connection
            connection.transaction.return_value.__enter__.return_value = None
            connection.execute.return_value.fetchone.return_value = row
            settings = SimpleNamespace(
                schema=schema, connect=lambda bound=connection, **kwargs: bound
            )
            output = io.StringIO()
            with (
                self.subTest(change=change),
                patch.object(PostgresSettings, "from_env", return_value=settings),
                patch.dict(os.environ, {"H1_SCHEMA_MARKER": marker, "H1_SCHEMA_OID": "123"}),
                redirect_stdout(output),
            ):
                exec(compile(bench.PG_CLEANUP_SCRIPT, "owned-schema-cleanup", "exec"), {})  # noqa: S102 - fixed owned script with a fake database
            self.assertEqual(json.loads(output.getvalue()), {"status": "unowned"})
            self.assertEqual(connection.execute.call_count, 1)
            self.assertNotIn(marker, output.getvalue())

    def test_volume_collision_or_foreign_label_prevents_every_mount_and_fixture_start(self):
        for collision in (True, False):
            with tempfile.TemporaryDirectory() as directory:
                lab = self.lab(directory)
                calls = []

                def command(argv, recorded=calls, existing=collision, **kwargs):
                    recorded.append(argv)
                    if argv[:4] == ["docker", "volume", "ls", "-q"]:
                        return "preexisting" if existing else ""
                    if argv[:3] == ["docker", "volume", "inspect"]:
                        return "foreign-label"
                    return ""

                lab.command = command
                with self.assertRaises(bench.BenchmarkError):
                    lab.prepare_volumes()
                self.assertFalse(lab._volumes_ready)
                self.assertFalse(any(argv[:2] == ["docker", "run"] for argv in calls))
                with self.assertRaises(bench.BenchmarkError):
                    lab.container(
                        lab.prefix + "-init",
                        Path(directory) / "worker.env",
                        ["python"],
                        role="worker",
                    )
                self.assertFalse(any(argv[:2] == ["docker", "run"] for argv in calls))

    def test_lost_volume_create_ack_keeps_candidate_for_exact_label_reconciliation(self):
        with tempfile.TemporaryDirectory() as directory:
            lab = self.lab(directory)

            def failed_create(argv, **kwargs):
                if argv[:3] == ["docker", "volume", "create"]:
                    raise bench.BenchmarkError("deadline_exceeded")
                return ""

            lab.command = failed_create
            with self.assertRaises(bench.BenchmarkError):
                lab.prepare_volumes()
            self.assertEqual(lab.volumes, [lab.prefix + "-application"])
            calls = []
            present = [True]

            def reconcile(argv, **kwargs):
                calls.append(argv)
                if argv[:4] == ["docker", "volume", "ls", "-q"]:
                    return lab.volumes[0] if present[0] else ""
                if argv[:3] == ["docker", "volume", "inspect"]:
                    return lab.label_value
                if argv[:3] == ["docker", "volume", "rm"]:
                    present[0] = False
                return ""

            lab.command = reconcile
            lab.cleanup()
            self.assertFalse(present[0])
            inspect = next(
                i for i, argv in enumerate(calls) if argv[:3] == ["docker", "volume", "inspect"]
            )
            remove = next(
                i for i, argv in enumerate(calls) if argv[:3] == ["docker", "volume", "rm"]
            )
            self.assertLess(inspect, remove)

    def test_owned_volume_access_is_verified_network_none_before_serving_user_mounts(self):
        with tempfile.TemporaryDirectory() as directory:
            lab = self.lab(directory)
            calls = []

            def command(argv, **kwargs):
                calls.append(argv)
                if argv[:3] == ["docker", "volume", "inspect"]:
                    return lab.label_value
                if argv[:2] == ["docker", "run"] and lab.prefix + "-write-access" in argv:
                    return "writable"
                return ""

            lab.command = command
            lab.prepare_volumes()
            self.assertTrue(lab._volumes_ready)
            runs = [argv for argv in calls if argv[:2] == ["docker", "run"]]
            self.assertEqual(len(runs), 2)
            self.assertTrue(all(argv[argv.index("--network") + 1] == "none" for argv in runs))
            self.assertEqual(runs[0][runs[0].index("--user") + 1], "0:0")
            self.assertEqual(runs[1][runs[1].index("--user") + 1], "10001:10001")
            self.assertFalse(any("--env-file" in argv for argv in runs))

    def test_label_mismatch_never_stops_or_removes_a_container(self):
        lab = bench.DockerExperiment.__new__(bench.DockerExperiment)
        lab.manifest = MANIFEST
        lab.prefix = bench.owned_prefix("a" * 32, 0)
        lab.label_key = "owned"
        lab.label_value = lab.prefix
        lab.names = [lab.prefix + "-worker-1"]
        lab.volumes = []
        lab.schema = "p1_benchmark_" + "a" * 32 + "_0"
        lab._schema_candidate = False
        calls = []

        def command(argv, **kwargs):
            calls.append(argv)
            return "container" if argv[:3] == ["docker", "ps", "-aq"] else "wrong-owner"

        lab.command = command
        connection = Mock()
        connection.execute.return_value.fetchone.return_value = None
        lab.owner = SimpleNamespace(connect=lambda **kwargs: connection)
        with self.assertRaises(bench.BenchmarkError):
            lab.cleanup()
        self.assertFalse(any(argv[1] in {"stop", "rm"} for argv in calls))

    def test_real_failed_command_retains_only_fixed_context_before_private_output_is_removed(self):
        sentinel = "private-command-output-env-and-argv-sentinel"
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory).resolve() / "report"
            report.mkdir(mode=0o700)
            with tempfile.TemporaryDirectory(dir=directory) as private:
                lab = self.lab(private)
                with (
                    self.assertRaises(bench.BenchmarkError) as caught,
                    bench.operation_scope("schema_prepare"),
                ):
                    lab.command(
                        [
                            sys.executable,
                            "-c",
                            "import os,sys;print(os.environ['PRIVATE']);print(os.environ['PRIVATE'],file=sys.stderr);sys.exit(7)",
                        ],
                        environment={"PATH": os.defpath, "PRIVATE": sentinel},
                    )
                self.assertIn(sentinel, (lab.directory / "command-1/stdout.bin").read_text())
                retained = bench.retain_failure_context(report, "steady-w1", caught.exception)
                # A cleanup failure is separate and cannot overwrite the first operation/exit.
                bench.retain_failure_context(
                    report,
                    "steady-w1",
                    bench.BenchmarkError("cleanup_failed", operation="cleanup"),
                    cleanup=True,
                )
                self.assertEqual(retained["operation"], "schema_prepare")
                self.assertEqual(retained["command"]["exit_code"], 7)
                self.assertIs(retained["command"]["timed_out"], False)
            self.assertFalse(Path(private).exists())
            execution = json.loads((report / "steady-w1.failure.json").read_text())
            self.assertEqual(execution["failure"], retained)
            self.assertEqual(execution["stage"], "execution")
            self.assertEqual(set(execution["failure"]), {"code", "operation", "command"})
            self.assertEqual(
                set(retained["command"]),
                {
                    "exit_code",
                    "timed_out",
                    "timeout_seconds",
                    "elapsed_seconds",
                },
            )
            for path in report.iterdir():
                self.assertNotIn(sentinel, path.read_text())
                self.assertNotIn("PRIVATE", path.read_text())
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_api_worker_and_fixture_startup_failures_keep_distinct_fixed_operations(self):
        for role, detached, operation in (
            ("api", True, "api_startup"),
            ("worker", True, "worker_startup"),
            ("worker", False, "fixture_init"),
        ):
            with tempfile.TemporaryDirectory() as directory:
                lab = self.lab(directory)
                lab._volumes_ready = True
                with (
                    self.subTest(operation=operation),
                    patch(
                        "harness.process_control.OwnedProcess",
                        side_effect=OSError("private-sentinel"),
                    ),
                    self.assertRaises(bench.BenchmarkError) as caught,
                ):
                    lab.container(
                        lab.prefix + "-test",
                        Path(directory) / "private.env",
                        ["python"],
                        role=role,
                        detached=detached,
                    )
                observed = bench.failure_observation(caught.exception)
                self.assertEqual(observed["operation"], operation)
                self.assertIsNone(observed["command"])
                self.assertNotIn("private-sentinel", json.dumps(observed))

    def test_owned_command_timeout_terminates_and_reaps_its_real_local_process(self):
        from harness.process_control import OwnedProcess

        with tempfile.TemporaryDirectory() as directory:
            lab = bench.DockerExperiment.__new__(bench.DockerExperiment)
            lab.budget = bench.Budget(5)
            lab.overall = bench.Budget(5)
            lab._lock = threading.Lock()
            lab._commands = 0
            lab.abort = threading.Event()
            lab.directory = Path(directory).resolve()
            lab.root = REPO
            lab.stack = SimpleNamespace(child_environment=lambda values: {"PATH": os.defpath})
            lab.values = {}
            owned = []

            def child(*args, **kwargs):
                process = OwnedProcess(*args, **kwargs)
                owned.append(process)
                return process

            with (
                patch("harness.process_control.OwnedProcess", side_effect=child),
                self.assertRaises(bench.BenchmarkError) as caught,
            ):
                lab.command(
                    [sys.executable, "-c", "import time;time.sleep(10)"],
                    cap=0.05,
                    operation="schema_prepare",
                )
            observed = bench.failure_observation(caught.exception)
            self.assertEqual(observed["code"], "deadline_exceeded")
            self.assertEqual(observed["operation"], "schema_prepare")
            self.assertTrue(observed["command"]["timed_out"])
            self.assertEqual(observed["command"]["timeout_seconds"], 0.05)
            self.assertGreaterEqual(observed["command"]["elapsed_seconds"], 0.05)
            self.assertEqual(observed["command"]["exit_code"], owned[0].returncode)
            self.assertEqual(len(owned), 1)
            self.assertIsNotNone(owned[0].returncode)


if __name__ == "__main__":
    unittest.main()
