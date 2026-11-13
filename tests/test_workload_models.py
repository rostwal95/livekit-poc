"""Frozen workload declarations and hostile JSON cannot become measurement claims."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError, asdict, replace
from pathlib import Path

from harness.workload_models import (
    MAX_MANIFEST_BYTES,
    Experiment,
    ResourceLimits,
    WorkloadManifest,
    WorkloadValidationError,
    canonical_manifest_bytes,
    load_workload_manifest,
    manifest_digest,
    parse_workload_manifest,
)

MANIFEST = Path(__file__).resolve().parents[1] / "harness/workloads/p1-inquiry-v1.json"
FROZEN_DIGEST = "442c9a05f40532a006f09fd4336092f76e2f72e531a178b7852e4859506f7aaf"


class WorkloadManifestTests(unittest.TestCase):
    def setUp(self):
        self.manifest = load_workload_manifest(MANIFEST)
        self.payload = asdict(self.manifest)
        # asdict preserves the immutable tuple; JSON's actual input uses arrays.
        self.payload["experiments"] = list(self.payload["experiments"])

    @staticmethod
    def raw(value):
        return json.dumps(value, allow_nan=True).encode()

    def rejected(self, value):
        with self.assertRaises(WorkloadValidationError) as caught:
            parse_workload_manifest(self.raw(value))
        self.assertNotIn("PRIVATE_SENTINEL", str(caught.exception))

    def test_frozen_v1_manifest_declares_all_six_experiments_before_measurement(self):
        value = self.manifest
        self.assertEqual(value.schema_version, 1)
        self.assertEqual(value.workload_id, "p1-inquiry-v1")
        self.assertEqual(value.seed, 20261109)
        self.assertEqual(
            (value.overall_deadline_seconds, value.cleanup_deadline_seconds), (600, 90)
        )
        self.assertEqual((value.sample_interval_seconds, value.maximum_samples), (1, 4096))
        self.assertEqual((value.observation_interval_ms, value.http_timeout_seconds), (250, 5))
        self.assertEqual(value.api_resources, ResourceLimits(1000, 536870912, 128))
        self.assertEqual(value.worker_resources, value.api_resources)
        self.assertEqual(
            [item.name for item in value.experiments],
            ["steady-w1", "steady-w2", "burst-w1", "burst-w2", "saturation-w1", "saturation-w2"],
        )
        for item in value.experiments:
            self.assertEqual(
                (item.deadline_seconds, item.lease_seconds, item.record_limit), (180, 30, 1000)
            )
            if item.kind == "steady":
                self.assertEqual(
                    (item.request_count, item.arrival_interval_ms, item.client_concurrency),
                    (20, 1000, 1),
                )
            else:
                self.assertEqual(
                    (item.request_count, item.arrival_interval_ms, item.client_concurrency),
                    (32, 0, 4),
                )
            if item.kind == "saturation":
                self.assertEqual(
                    (
                        item.accepted_count,
                        item.rejected_count,
                        item.pending_limit,
                        item.active_limit,
                    ),
                    (8, 24, 8, 1),
                )
                self.assertTrue(item.workers_start_after_submissions)
            else:
                self.assertEqual(
                    (
                        item.accepted_count,
                        item.rejected_count,
                        item.pending_limit,
                        item.active_limit,
                    ),
                    (item.request_count, 0, 64, 4),
                )
                self.assertFalse(item.workers_start_after_submissions)
        self.assertEqual(sum(item.request_count for item in value.experiments), 168)
        self.assertEqual(sum(item.accepted_count for item in value.experiments), 120)
        self.assertEqual(sum(item.rejected_count for item in value.experiments), 48)
        self.assertNotIn("status", self.payload)  # A declaration cannot claim an observed pass.

    def test_digest_binds_canonical_content_and_ignores_json_field_order_or_whitespace(self):
        encoded = canonical_manifest_bytes(self.manifest)
        self.assertEqual(manifest_digest(self.manifest), FROZEN_DIGEST)
        self.assertEqual(hashlib.sha256(encoded).hexdigest(), FROZEN_DIGEST)
        self.assertEqual(encoded, canonical_manifest_bytes(parse_workload_manifest(encoded)))
        reordered = dict(reversed(list(self.payload.items())))
        self.assertEqual(
            manifest_digest(parse_workload_manifest(self.raw(reordered))), FROZEN_DIGEST
        )
        pretty = json.dumps(reordered, indent=4).encode()
        self.assertEqual(manifest_digest(parse_workload_manifest(pretty)), FROZEN_DIGEST)
        changed = replace(self.manifest, seed=self.manifest.seed + 1)
        self.assertNotEqual(manifest_digest(changed), FROZEN_DIGEST)
        changed_mode_order = replace(
            self.manifest, experiments=tuple(reversed(self.manifest.experiments))
        )
        self.assertNotEqual(manifest_digest(changed_mode_order), FROZEN_DIGEST)

    def test_contract_and_nested_resources_are_immutable_without_raw_input_aliases(self):
        with self.assertRaises(FrozenInstanceError):
            self.manifest.seed = 0
        with self.assertRaises(FrozenInstanceError):
            self.manifest.api_resources.memory_bytes = 1
        with self.assertRaises(FrozenInstanceError):
            self.manifest.experiments[0].worker_count = 2
        self.payload["api_resources"]["memory_bytes"] = 1
        self.assertEqual(self.manifest.api_resources.memory_bytes, 536870912)
        self.assertIs(type(self.manifest.experiments), tuple)

    def test_duplicate_keys_are_rejected_at_root_resource_and_experiment_levels(self):
        raw = self.raw(self.payload)
        variants = (
            raw.replace(b'"seed": 20261109', b'"seed": 20261109, "seed": 1'),
            raw.replace(
                b'"cpu_millicores": 1000', b'"cpu_millicores": 1000, "cpu_millicores": 1', 1
            ),
            raw.replace(
                b'"name": "steady-w1"', b'"name": "steady-w1", "name": "PRIVATE_SENTINEL"', 1
            ),
        )
        for value in variants:
            with (
                self.subTest(size=len(value)),
                self.assertRaises(WorkloadValidationError) as caught,
            ):
                parse_workload_manifest(value)
            self.assertNotIn("PRIVATE_SENTINEL", str(caught.exception))

    def test_unknown_and_missing_fields_fail_at_every_owned_object_boundary(self):
        for selector in (
            lambda item: item,
            lambda item: item["api_resources"],
            lambda item: item["experiments"][0],
        ):
            candidate = copy.deepcopy(self.payload)
            selector(candidate)["PRIVATE_SENTINEL"] = "PRIVATE_SENTINEL"
            self.rejected(candidate)
            candidate = copy.deepcopy(self.payload)
            target = selector(candidate)
            target.pop(next(iter(target)))
            self.rejected(candidate)
        candidate = copy.deepcopy(self.payload)
        candidate["experiments"][0]["worker_resources"] = candidate["worker_resources"]
        self.rejected(candidate)  # A worker mode cannot silently change its per-role caps.

    def test_invalid_roots_nested_shapes_versions_and_identities_are_rejected(self):
        for value in (None, [], True, 1, "PRIVATE_SENTINEL"):
            self.rejected(value)
        for field, value in (
            ("schema_version", 2),
            ("workload_id", "PRIVATE_SENTINEL"),
            ("workload_id", 1),
            ("api_resources", []),
            ("worker_resources", None),
            ("experiments", {}),
            ("experiments", [None] * 6),
        ):
            with self.subTest(field=field):
                candidate = copy.deepcopy(self.payload)
                candidate[field] = value
                self.rejected(candidate)

    def test_numeric_booleans_are_never_accepted_as_integer_budgets(self):
        for field in (
            "schema_version",
            "seed",
            "overall_deadline_seconds",
            "cleanup_deadline_seconds",
            "sample_interval_seconds",
            "observation_interval_ms",
            "http_timeout_seconds",
            "maximum_samples",
        ):
            for value in (True, False):
                candidate = copy.deepcopy(self.payload)
                candidate[field] = value
                self.rejected(candidate)
        for field in ("cpu_millicores", "memory_bytes", "pids_limit"):
            candidate = copy.deepcopy(self.payload)
            candidate["worker_resources"][field] = True
            self.rejected(candidate)
        for field in (
            "worker_count",
            "request_count",
            "accepted_count",
            "rejected_count",
            "arrival_interval_ms",
            "client_concurrency",
            "deadline_seconds",
            "pending_limit",
            "active_limit",
            "record_limit",
            "lease_seconds",
        ):
            candidate = copy.deepcopy(self.payload)
            candidate["experiments"][0][field] = True
            self.rejected(candidate)
        for value in (0, 1, "false", None):
            candidate = copy.deepcopy(self.payload)
            candidate["experiments"][0]["workers_start_after_submissions"] = value
            self.rejected(candidate)

    def test_nonfinite_floating_and_oversize_integer_representations_fail_closed(self):
        for value in (float("nan"), float("inf"), -float("inf"), 1.0, 0.5, "1"):
            candidate = copy.deepcopy(self.payload)
            candidate["seed"] = value
            self.rejected(candidate)
        raw = self.raw(self.payload)
        for representation in (b"9" * 1000, b"1e9999", b"-1e9999"):
            with self.assertRaises(WorkloadValidationError):
                parse_workload_manifest(raw.replace(b"20261109", representation, 1))

    def test_byte_encoding_json_depth_and_trailing_document_bounds_are_enforced(self):
        for value in (
            b"",
            b" " * (MAX_MANIFEST_BYTES + 1),
            b"\xff",
            b"\xef\xbb\xbf{}",
            b"{",
            b"{}{}",
            b"[" * 1000 + b"]" * 1000,
        ):
            with self.subTest(size=len(value)), self.assertRaises(WorkloadValidationError):
                parse_workload_manifest(value)
        candidate = copy.deepcopy(self.payload)
        candidate["workload_id"] = '["\\' * 40
        with self.assertRaisesRegex(WorkloadValidationError, "identity"):
            parse_workload_manifest(self.raw(candidate))  # Brackets inside strings are not nesting.

    def test_overall_deadlines_seed_sampling_and_resource_caps_cannot_expand_unbounded(self):
        for field, value in (
            ("seed", -1),
            ("seed", 4294967296),
            ("overall_deadline_seconds", 601),
            ("overall_deadline_seconds", 0),
            ("overall_deadline_seconds", 179),
            ("cleanup_deadline_seconds", 91),
            ("cleanup_deadline_seconds", 0),
            ("sample_interval_seconds", 0),
            ("sample_interval_seconds", 2),
            ("observation_interval_ms", 0),
            ("observation_interval_ms", 249),
            ("observation_interval_ms", 1001),
            ("http_timeout_seconds", 0),
            ("http_timeout_seconds", 6),
            ("maximum_samples", 0),
            ("maximum_samples", 4097),
        ):
            candidate = copy.deepcopy(self.payload)
            candidate[field] = value
            self.rejected(candidate)
        for field, value in (
            ("cpu_millicores", 99),
            ("cpu_millicores", 4001),
            ("memory_bytes", 67108863),
            ("memory_bytes", 1073741825),
            ("pids_limit", 15),
            ("pids_limit", 257),
        ):
            candidate = copy.deepcopy(self.payload)
            candidate["api_resources"][field] = value
            self.rejected(candidate)

    def test_experiment_counts_capacities_and_schedule_invariants_reject_unsafe_work(self):
        changes = (
            {"worker_count": 3},
            {"name": "PRIVATE_SENTINEL"},
            {"kind": "PRIVATE_SENTINEL"},
            {"name": "steady-w2"},
            {"request_count": 33},
            {"accepted_count": 0},
            {"accepted_count": 19},
            {"rejected_count": 1},
            {"client_concurrency": 5},
            {"deadline_seconds": 181},
            {"deadline_seconds": 1},
            {"arrival_interval_ms": 0},
            {"arrival_interval_ms": 1001},
            {"pending_limit": 0},
            {"pending_limit": 65},
            {"active_limit": 5},
            {"pending_limit": 2, "active_limit": 3},
            {"record_limit": 10},
            {"record_limit": 1001},
            {"lease_seconds": 29},
            {"workers_start_after_submissions": True},
        )
        for change in changes:
            with self.subTest(fields=tuple(change)):
                candidate = copy.deepcopy(self.payload)
                candidate["experiments"][0].update(change)
                self.rejected(candidate)
        candidate = copy.deepcopy(self.payload)
        candidate["experiments"][2]["arrival_interval_ms"] = 1
        self.rejected(candidate)

    def test_saturation_must_apply_pressure_before_workers_and_keep_one_active_slot(self):
        for change in (
            {"workers_start_after_submissions": False},
            {"active_limit": 2},
            {"accepted_count": 7, "rejected_count": 25},
            {"request_count": 8, "accepted_count": 8, "rejected_count": 0},
        ):
            candidate = copy.deepcopy(self.payload)
            candidate["experiments"][4].update(change)
            self.rejected(candidate)

    def test_all_six_unique_kind_mode_pairs_are_required(self):
        for values in (
            self.payload["experiments"][:5],
            self.payload["experiments"] + self.payload["experiments"][:1],
        ):
            candidate = copy.deepcopy(self.payload)
            candidate["experiments"] = values
            self.rejected(candidate)
        candidate = copy.deepcopy(self.payload)
        candidate["experiments"][1] = copy.deepcopy(candidate["experiments"][0])
        self.rejected(candidate)

    def test_direct_construction_and_replacement_enforce_the_same_contract(self):
        for action in (
            lambda: replace(self.manifest, seed=True),
            lambda: replace(self.manifest, experiments=list(self.manifest.experiments)),
            lambda: replace(self.manifest, experiments=(None,) * 6),
            lambda: replace(self.manifest, api_resources={}),
            lambda: ResourceLimits(True, 536870912, 128),
            lambda: replace(self.manifest.experiments[0], workers_start_after_submissions=1),
            lambda: canonical_manifest_bytes({}),
        ):
            with self.assertRaises(WorkloadValidationError):
                action()
        self.assertIsInstance(self.manifest, WorkloadManifest)
        self.assertIsInstance(self.manifest.experiments[0], Experiment)

    def test_module_loads_and_hashes_in_an_isolated_interpreter_without_site_packages(self):
        program = (
            "import importlib.util,sys;from pathlib import Path; "
            "spec=importlib.util.spec_from_file_location('stdlib_workload_contract',sys.argv[1]); "
            "module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module; "
            "spec.loader.exec_module(module); "
            "print(module.manifest_digest(module.load_workload_manifest(Path(sys.argv[2]))))"
        )
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-S",
                "-c",
                program,
                str(MANIFEST.parent.parent / "workload_models.py"),
                str(MANIFEST),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), FROZEN_DIGEST)

    def test_loader_uses_regular_bounded_local_files_and_sanitizes_filesystem_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            regular = directory / "declared.json"
            regular.write_bytes(MANIFEST.read_bytes())
            self.assertEqual(load_workload_manifest(regular), self.manifest)
            link = directory / "link.json"
            link.symlink_to(regular)
            oversized = directory / "oversized.json"
            oversized.write_bytes(b" " * (MAX_MANIFEST_BYTES + 1))
            for path in (directory, link, oversized, directory / "PRIVATE_SENTINEL"):
                with (
                    self.subTest(kind=path.name),
                    self.assertRaises(WorkloadValidationError) as caught,
                ):
                    load_workload_manifest(path)
                self.assertNotIn("PRIVATE_SENTINEL", str(caught.exception))
