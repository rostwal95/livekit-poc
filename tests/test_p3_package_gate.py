"""Independent frozen-protocol negatives for the standalone artifact gate.

Synthetic reports and temporary files only. This suite never builds, installs,
starts PostgreSQL or runs the combined qualification driver. Initial24 report,
environment and path tests were independently authored. Later proof/index
extensions share the tooling author and receive separate root review.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

SPEC = importlib.util.spec_from_file_location(
    "p3_package_gate_tests",
    Path(__file__).resolve().parents[1] / "local-setup/scripts/p3_package_check.py",
)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)
OFFLINE = [
    "python_archive_payload_readme_RECORD",
    "fresh_declared_P1_dependency_wheel",
    "npm_payload_manifest_public_exports",
    "installed_imports_no_startup_IO",
    "strict_installed_Python_consumer",
    "strict_installed_TS_consumer",
    "installed_native_baseline_entrypoint",
    "installed_public_Node_HTTP_example",
]
LAB = [
    "actual_run_completion_useful_result",
    "equal_acceptance_changed_payload_scope_isolation",
    "separate_exact_confirmation_original_guarded_intent",
    "public_projection_processing_refresh_progress",
    "read_only_inspection_zero_new_calls",
    "owned_completion_ACK_crash_fresh_original_replay",
    "later_cancel_preserves_original_facts_without_new_permission",
    "independent_SQL_receiver_supplier_identity_cleanup",
]
ARTIFACTS = {
    "p1-wheel": "artifacts/p1/agent_continuity-0.1.0-py3-none-any.whl",
    "p3-wheel": "artifacts/wheel/delegation_reliability-0.1.0-py3-none-any.whl",
    "p3-sdist": "artifacts/sdist/delegation_reliability-0.1.0.tar.gz",
    "p3-rebuilt": "artifacts/rebuilt/delegation_reliability-0.1.0-py3-none-any.whl",
    "specialist-npm": "artifacts/npm/livekit-ecosystem-delegation-specialist-0.1.0.tgz",
}
PROOFS = ["standalone-authority.json", "standalone-service.json", "standalone-replay.json"]


def encoded(value):
    return json.dumps(value, separators=(",", ":")).encode()


def report(*, lab=False):
    cases = OFFLINE + (LAB if lab else [])
    return {
        "schema_version": 1,
        "status": "passed",
        "mode": "lab" if lab else "offline",
        "tests": len(cases),
        "passed": len(cases),
        "offline_assertions": 8,
        "lab_assertions": 8 if lab else 0,
        "child_terminations": 1 if lab else 0,
        "child_commands": 28 if lab else 17,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "cleanup_complete": True,
        "provider_calls": False,
        "authority_runtime_changes": False,
        "full_charter_release_claimed": False,
        "node_version": "24.22.2",
        "python_version": "3.14.10",
        "platform": "darwin_arm64",
        "duration_seconds": 17.5,
        "case_results": [{"name": name, "status": "passed", "code": "ok"} for name in cases],
        "artifacts": {
            name: {"path": path, "bytes": 128, "sha256": "a" * 64}
            for name, path in ARTIFACTS.items()
        },
        "proofs": {name: {"bytes": 1024, "sha256": "b" * 64} for name in PROOFS} if lab else {},
        "retained_index_sha256": "c" * 64,
    }


class PackageReportTests(unittest.TestCase):
    def test_reviewed_payload_inventory_covers_actual_public_sources(self):
        root = Path(__file__).resolve().parents[1]
        project = root / "projects/delegation-reliability"
        source = project / "python/src"
        runtime = {
            path.relative_to(source).as_posix(): path.read_bytes()
            for path in (source / "delegation_reliability").glob("*")
            if path.is_file() and path.suffix in {".py", ".typed"}
        }
        modules = {path.stem for path in (project / "specialist-ts/src").glob("*.ts")}
        examples = {path.name for path in (project / "specialist-ts/examples").glob("*.mjs")}
        module.validate_current_payload_inventory(runtime, modules, examples)
        self.assertEqual((len(runtime), len(modules), len(examples)), (39, 14, 3))
        for absent in (
            "delegation_reliability/fixed_policy.py",
            "delegation_reliability/fixed_policy_contracts.py",
            "delegation_reliability/_policy_codec.py",
            "delegation_reliability/fixed_policy_execution.py",
            "delegation_reliability/native_policy.py",
            "delegation_reliability/channel_policy_contracts.py",
            "delegation_reliability/channel_policy_execution.py",
        ):
            with self.subTest(absent=absent), self.assertRaises(module.GateError):
                module.validate_current_payload_inventory(
                    {name: body for name, body in runtime.items() if name != absent},
                    modules,
                    examples,
                )

    def rejects(self, value):
        with self.assertRaises(module.GateError) as caught:
            module.validated_report(encoded(value))
        self.assertEqual(caught.exception.code, "invalid_report")

    def test_exact_offline_and_combined_positive_remain_distinct(self):
        for lab in (False, True):
            value = report(lab=lab)
            self.assertEqual(module.validated_report(encoded(value)), value)
        self.assertEqual(module.OFFLINE_CASES, tuple(OFFLINE))
        self.assertEqual(module.LAB_CASES, tuple(LAB))

    def test_combined_is_eight_offline_plus_eight_actual_not_sixteen_PG(self):
        value = report(lab=True)
        for field, changed in (
            ("lab_assertions", 16),
            ("offline_assertions", 0),
            ("tests", 8),
            ("passed", 8),
            ("child_commands", 17),
            ("child_terminations", 0),
            ("mode", "offline"),
        ):
            bad = copy.deepcopy(value)
            bad[field] = changed
            self.rejects(bad)

    def test_missing_unknown_and_failure_fields_are_not_success(self):
        for lab in (False, True):
            for key in report(lab=lab):
                bad = report(lab=lab)
                del bad[key]
                self.rejects(bad)
        for extra in ("private_body", "cleanup_pending", "stdout", "source_rows"):
            bad = report()
            bad[extra] = "untrusted"
            self.rejects(bad)
        for status in ("failed", "partial", "skipped", "running"):
            bad = report()
            bad["status"] = status
            self.rejects(bad)

    def test_strict_integer_and_boolean_types(self):
        for name in (
            "schema_version",
            "tests",
            "passed",
            "offline_assertions",
            "lab_assertions",
            "child_terminations",
            "child_commands",
            "failures",
            "errors",
            "skipped",
        ):
            for value in (True, False, "0", 0.0, None, [], {}):
                bad = report()
                bad[name] = value
                self.rejects(bad)
        for name in (
            "cleanup_complete",
            "provider_calls",
            "authority_runtime_changes",
            "full_charter_release_claimed",
        ):
            for value in (0, 1, "false", None, [], {}):
                bad = report()
                bad[name] = value
                self.rejects(bad)

    def test_wrong_authority_platform_cleanup_or_provider_claim_rejected(self):
        for field, value in (
            ("cleanup_complete", False),
            ("provider_calls", True),
            ("authority_runtime_changes", True),
            ("full_charter_release_claimed", True),
            ("node_version", "26.13.0"),
            ("python_version", "3.14.9"),
            ("platform", "linux_arm64"),
        ):
            bad = report()
            bad[field] = value
            self.rejects(bad)

    def test_duration_bounds_and_huge_json_integer_do_not_raise_raw_errors(self):
        for value in (
            0,
            -1,
            True,
            "1",
            None,
            [],
            {},
            360.001,
            10**500,
            -(10**500),
            math.nan,
            math.inf,
            -math.inf,
        ):
            bad = report()
            bad["duration_seconds"] = value
            self.rejects(bad)
        good = report()
        good["duration_seconds"] = 360
        self.assertEqual(module.validated_report(encoded(good))["duration_seconds"], 360)

    def test_case_identity_order_coverage_and_fixed_codes(self):
        mutations = []
        bad = report(lab=True)
        bad["case_results"][0], bad["case_results"][1] = (
            bad["case_results"][1],
            bad["case_results"][0],
        )
        mutations.append(bad)
        bad = report(lab=True)
        bad["case_results"][-1] = bad["case_results"][0]
        mutations.append(bad)
        bad = report(lab=True)
        bad["case_results"].pop()
        mutations.append(bad)
        bad = report(lab=True)
        bad["case_results"][0]["code"] = "unknown"
        mutations.append(bad)
        bad = report(lab=True)
        bad["case_results"][0]["status"] = True
        mutations.append(bad)
        bad = report(lab=True)
        bad["case_results"][0]["name"] = 0
        mutations.append(bad)
        bad = report(lab=True)
        bad["case_results"][0]["details"] = "private"
        mutations.append(bad)
        for value in mutations:
            self.rejects(value)

    def test_archive_labels_paths_and_bytes_are_exact(self):
        mutations = []
        for field in ("artifacts",):
            for value in (None, [], True, "archive"):
                bad = report()
                bad[field] = value
                mutations.append(bad)
        bad = report()
        del bad["artifacts"]["p1-wheel"]
        mutations.append(bad)
        bad = report()
        bad["artifacts"]["unreviewed"] = bad["artifacts"]["p3-wheel"]
        mutations.append(bad)
        for path in (
            "../escape.whl",
            "/private/tmp/archive.whl",
            ARTIFACTS["p3-rebuilt"],
            {"path": "wrong"},
        ):
            bad = report()
            bad["artifacts"]["p3-wheel"]["path"] = path
            mutations.append(bad)
        for size in (0, -1, True, "128", 8388609):
            bad = report()
            bad["artifacts"]["p3-wheel"]["bytes"] = size
            mutations.append(bad)
        bad = report()
        bad["artifacts"]["p3-wheel"]["extra"] = 1
        mutations.append(bad)
        for value in mutations:
            self.rejects(value)

    def test_hashes_and_retained_index_are_required_canonical_SHA256(self):
        for value in (None, "", "a" * 63, "A" * 64, "g" * 64, "a" * 64 + "\n", 1, True, []):
            bad = report()
            bad["retained_index_sha256"] = value
            self.rejects(bad)
            bad = report()
            bad["artifacts"]["p1-wheel"]["sha256"] = value
            self.rejects(bad)
            bad = report(lab=True)
            bad["proofs"][PROOFS[0]]["sha256"] = value
            self.rejects(bad)

    def test_offline_proofs_empty_and_combined_exact_three_bounded_descriptors(self):
        bad = report()
        bad["proofs"] = report(lab=True)["proofs"]
        self.rejects(bad)
        for value in ({}, None, [], True):
            bad = report(lab=True)
            bad["proofs"] = value
            self.rejects(bad)
        for name in PROOFS:
            bad = report(lab=True)
            del bad["proofs"][name]
            self.rejects(bad)
        for size in (0, -1, True, 32769):
            bad = report(lab=True)
            bad["proofs"][PROOFS[0]]["bytes"] = size
            self.rejects(bad)
        bad = report(lab=True)
        bad["proofs"]["phantom.json"] = {"bytes": 1, "sha256": "a" * 64}
        self.rejects(bad)

    def test_raw_JSON_duplicate_primitives_unicode_and_size(self):
        raw = encoded(report())
        cases = [
            b"",
            b"null",
            b"[]",
            b"false",
            b"123",
            b'"str"',
            b"\xff",
            b'{"x":NaN}',
            b'{"x":1,"x":1}',
            b'{"x":{"nested":1,"nested":1}}',
            b"[" * 2000 + b"]" * 2000,
            b" " * 32769,
            raw.replace(b'"mode":"offline"', b'"mode":"offline","mode":"offline"'),
        ]
        for value in cases:
            with self.subTest(value=value[:40]), self.assertRaises(module.GateError):
                module.validated_report(value)
        for value in (bytearray(raw), raw.decode()):
            with self.assertRaises(module.GateError):
                module.validated_report(value)

    def test_failure_code_constructor_never_reflects_untrusted_value(self):
        for value in ("SENTINEL_PRIVATE_FAILURE", [], {}, None, True):
            error = module.GateError(value)
            self.assertEqual(str(error), "unexpected_error")


class PackageEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.owned = tempfile.TemporaryDirectory(prefix="phase38-package-env-", dir="/private/tmp")
        self.folder = Path(self.owned.name)
        self.folder.chmod(0o700)
        self.addCleanup(self.owned.cleanup)

    def environment(self, role, mode=None):
        prefix = "P3_STANDALONE_"
        common = {prefix + "DIRECTORY": str(self.folder)}
        if role != "node":
            suffix = "a" * 32
            common.update(
                {
                    prefix + "PG_PORT": "5432",
                    prefix + "WORK_SCHEMA": "p1_work_standalone_" + suffix,
                    prefix + "CASE_SCHEMA": "p3_completion_" + suffix,
                    prefix + "SCHEMA": "p3_projection_standalone_" + suffix,
                    prefix
                    + (
                        "OWNER_PASSWORD" if role == "owner" else "RUNTIME_PASSWORD"
                    ): "synthetic_password",
                }
            )
        if role in ("runtime", "node"):
            common.update(
                {
                    prefix + "SPECIALIST_TOKEN": "s" * 43,
                    prefix + "ENDPOINT_FILE": str(self.folder / "specialist-endpoint.json"),
                }
            )
        if role == "runtime":
            common.update({prefix + "WORK_TOKEN": "w" * 43, prefix + "CASE_TOKEN": "c" * 43})
        if role == "node":
            common.update(
                {
                    prefix + "READY_FILE": str(self.folder / "specialist.ready"),
                    prefix + "STOP_FILE": str(self.folder / "specialist.stop"),
                }
            )
        if mode == "complete":
            common[prefix + "BARRIER"] = str(self.folder / "completion_returned.reached")
        return common

    def rejects(self, env, role, mode=None):
        with self.assertRaises(module.GateError) as caught:
            module.validate_child_environment(env, role, mode)
        self.assertEqual(caught.exception.code, "invalid_input")

    def test_exact_owner_runtime_complete_and_node_roles(self):
        for mode, role in {
            "install": "owner",
            "seed": "runtime",
            "complete": "runtime",
            "effect": "runtime",
            "metadata": "runtime",
            "negative": "runtime",
            "replay": "runtime",
            "cancel": "runtime",
            "verify": "owner",
            "cleanup": "owner",
        }.items():
            module.validate_child_environment(self.environment(role, mode), role, mode)
        module.validate_child_environment(self.environment("node"), "node")

    def test_each_required_key_missing_is_rejected(self):
        for role, mode in (("owner", "install"), ("runtime", "complete"), ("node", None)):
            original = self.environment(role, mode)
            for key in original:
                changed = dict(original)
                del changed[key]
                self.rejects(changed, role, mode)

    def test_owner_runtime_and_node_credentials_cannot_cross_roles(self):
        for role, mode in (("owner", "install"), ("runtime", "replay"), ("node", None)):
            for name in (
                "P3_STANDALONE_OWNER_PASSWORD",
                "P3_STANDALONE_RUNTIME_PASSWORD",
                "PGPASSWORD",
                "HTTP_PROXY",
                "NODE_OPTIONS",
                "PYTHONPATH",
                "HOME",
                "PROVIDER_API_KEY",
            ):
                env = self.environment(role, mode)
                if name in env:
                    continue
                env[name] = "synthetic_forbidden"
                self.rejects(env, role, mode)

    def test_invalid_roles_modes_and_nontext_values_are_safe(self):
        env = self.environment("runtime", "replay")
        for role, mode in (
            ("runtime", "install"),
            ("owner", "replay"),
            ("node", "seed"),
            ([], None),
            ("missing", None),
            ("runtime", []),
        ):
            self.rejects(env, role, mode)
        for value in (None, True, 5432, [], {}):
            changed = dict(env)
            changed["P3_STANDALONE_PG_PORT"] = value
            self.rejects(changed, "runtime", "replay")

    def test_canonical_port_schema_family_and_same_UUID_suffix(self):
        for value in ("0", "01", "65536", "-1", "5432\n", "5.0", "True"):
            changed = self.environment("owner", "install")
            changed["P3_STANDALONE_PG_PORT"] = value
            self.rejects(changed, "owner", "install")
        for key, value in (
            ("WORK_SCHEMA", "p1_work_standalone_" + "B" * 32),
            ("CASE_SCHEMA", "p3_completion_" + "b" * 32),
            ("SCHEMA", "p3_projection_" + "a" * 32),
        ):
            changed = self.environment("owner", "install")
            changed["P3_STANDALONE_" + key] = value
            self.rejects(changed, "owner", "install")

    def test_control_paths_exact_private_directory_and_no_parent_escape(self):
        for role, mode, key, name in (
            ("runtime", "complete", "BARRIER", "other.reached"),
            ("runtime", "replay", "ENDPOINT_FILE", "other.json"),
            ("node", None, "READY_FILE", "different.ready"),
            ("node", None, "STOP_FILE", "different.stop"),
        ):
            env = self.environment(role, mode)
            env["P3_STANDALONE_" + key] = str(self.folder / name)
            self.rejects(env, role, mode)
        env = self.environment("node")
        env["P3_STANDALONE_DIRECTORY"] = str(self.folder / ".." / self.folder.name)
        self.rejects(env, "node")
        env = self.environment("node")
        env["P3_STANDALONE_DIRECTORY"] = "relative"
        self.rejects(env, "node")
        self.folder.chmod(0o755)
        self.rejects(self.environment("node"), "node")

    def test_symlink_directory_rejected_without_reading_target_files(self):
        linked = self.folder / "linked"
        linked.symlink_to(self.folder, target_is_directory=True)
        env = self.environment("node")
        env["P3_STANDALONE_DIRECTORY"] = str(linked)
        self.rejects(env, "node")

    def test_tokens_password_bounds_and_no_barrier_outside_held_mode(self):
        for value in ("s" * 42, "s" * 44, "s" * 43 + "\n", "has spaces", ""):
            env = self.environment("runtime", "replay")
            env["P3_STANDALONE_SPECIALIST_TOKEN"] = value
            self.rejects(env, "runtime", "replay")
        for value in ("x" * 129, "secret\n", "secret\r", "secret\0"):
            env = self.environment("owner", "install")
            env["P3_STANDALONE_OWNER_PASSWORD"] = value
            self.rejects(env, "owner", "install")
        env = self.environment("runtime", "replay")
        env["P3_STANDALONE_BARRIER"] = str(self.folder / "completion_returned.reached")
        self.rejects(env, "runtime", "replay")


class PackageTargetTests(unittest.TestCase):
    def setUp(self):
        self.owned = tempfile.TemporaryDirectory(
            prefix="phase38-package-target-", dir="/private/tmp"
        )
        self.root = Path(self.owned.name)
        self.root.chmod(0o700)
        self.addCleanup(self.owned.cleanup)

    def test_fresh_target_default_and_explicit_are_read_only(self):
        relative = Path(".local/validation/p3-package/selected.json")
        self.assertEqual(module.target_path(self.root, relative), self.root / relative)
        generated = module.target_path(self.root, None)
        self.assertEqual(generated.parent, self.root / ".local/validation/p3-package")
        self.assertFalse((self.root / ".local").exists())
        self.assertEqual(module.target_path(self.root, generated), generated)

    def test_existing_report_or_artifact_sibling_cannot_be_reused(self):
        base = self.root / ".local/validation/p3-package"
        base.mkdir(parents=True)
        target = base / "selected.json"
        target.write_bytes(b"preserved")
        with self.assertRaisesRegex(module.GateError, "^report_exists$"):
            module.target_path(self.root, target)
        self.assertEqual(target.read_bytes(), b"preserved")
        target.unlink()
        (base / "selected-artifacts").mkdir()
        with self.assertRaisesRegex(module.GateError, "^report_exists$"):
            module.target_path(self.root, target)

    def test_wrong_directory_name_traversal_and_relative_root_reject(self):
        for requested in (
            Path("/private/tmp/elsewhere.json"),
            Path(".local/validation/p3-package/nested/report.json"),
            Path(".local/validation/p3-package/../report.json"),
            Path(".local/validation/p3-package/.hidden.json"),
            Path(".local/validation/p3-package/selected.txt"),
        ):
            with self.assertRaises(module.GateError):
                module.target_path(self.root, requested)
        with self.assertRaises(module.GateError):
            module.target_path(Path("relative"), None)

    def test_broken_symlink_report_and_symlink_ancestor_are_rejected(self):
        base = self.root / ".local/validation/p3-package"
        base.mkdir(parents=True)
        target = base / "selected.json"
        target.symlink_to(base / "missing")
        with self.assertRaisesRegex(module.GateError, "^report_exists$"):
            module.target_path(self.root, target)
        target.unlink()
        linked = self.root / "other"
        linked.mkdir()
        base.rmdir()
        base.symlink_to(linked, target_is_directory=True)
        with self.assertRaisesRegex(module.GateError, "^invalid_input$"):
            module.target_path(self.root, target)


def framed_digest(records):
    """Independent literal codec, not the producer's digest implementation."""
    value = hashlib.sha256(b"p3-standalone-inventory-v1\0")
    for record in records:
        raw = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        value.update(len(raw).to_bytes(4, "big"))
        value.update(raw)
    return value.hexdigest()


def uuid_for(number):
    return f"00000000-0000-4000-8000-{number:012x}"


def proof_corpus():
    """Synthetic, distinct identities only; never an assertion of actual state."""
    scope = {"tenant_id": "tenant_standalone", "account_id": "account_standalone"}
    identity = {
        "scope": scope,
        "work_id": uuid_for(1),
        "delegation_id": "delegation_standalone",
        "request_sha256": "a" * 64,
        "wire_request_sha256": "b" * 64,
        "input_fingerprint": "c" * 64,
        "attempt_id": uuid_for(2),
        "issue_command_id": "standalone_execution",
        "owner_id": uuid_for(3),
        "result_sha256": "d" * 64,
        "source_id": uuid_for(4),
        "event_id": uuid_for(5),
        "case_task_id": uuid_for(6),
        "case_id": uuid_for(7),
        "case_revision": 2,
        "quote_sha256": "e" * 64,
        "confirmation_sha256": "f" * 64,
        "action_id": uuid_for(8),
        "intent_id": uuid_for(9),
        "effect_id": uuid_for(10),
        "supplier_result_sha256": "0" * 64,
        "delivery_id": uuid_for(11),
        "receiver_id": uuid_for(12),
        "recipient_id": "recipient_standalone",
        "receipt_id": uuid_for(13),
        "processing_ack_sha256": "1" * 64,
    }
    metadata = {
        "source_id": uuid_for(4),
        "event_id": uuid_for(5),
        "projection_sha256": "2" * 64,
        "processing_ack_sha256": "1" * 64,
        "first_refresh_sha256": "3" * 64,
        "second_refresh_sha256": "4" * 64,
        "display_tombstone_sha256": "5" * 64,
        "terminal_watermark": 1,
        "terminal_count": 1,
    }
    counts = dict.fromkeys(
        (
            "accepted",
            "action_receipts",
            "attempts",
            "business_outcomes",
            "case_intents",
            "confirmations",
            "delivery_intents",
            "delivery_receipts",
            "display_tombstones",
            "events",
            "mutation_effects",
            "processing_acks",
            "projected_results",
            "results",
            "supplier_apply_calls",
            "supplier_receipts",
        ),
        1,
    )
    counts["refresh_commands"] = 2
    authority = {
        "schema_version": 1,
        "status": "passed",
        "counts": counts,
        "identity": identity,
        "metadata": metadata,
        "inventory_sha256": framed_digest(
            [
                {"kind": "counts", **counts},
                {"kind": "identity", **identity},
                {"kind": "metadata", **metadata},
            ]
        ),
    }
    summary = {
        "work_id": uuid_for(1),
        "accepted_input_sha256": "a" * 64,
        "result_sha256": "d" * 64,
        "created_acceptances": 1,
        "invoked": True,
        "delivery_state": "accepted",
        "action_id": uuid_for(8),
        "human_acknowledgement": "unobserved",
        "attempt_id": uuid_for(2),
        "delivery_id": uuid_for(11),
        "receipt_id": uuid_for(13),
        "receiver_id": uuid_for(12),
        "intent_id": uuid_for(9),
        "effect_id": uuid_for(10),
    }
    zero = dict.fromkeys(
        (
            "issue_write",
            "complete_write",
            "authorize_write",
            "invoke",
            "receiver_accept",
            "supplier_apply",
        ),
        0,
    )
    replay = {
        "schema_version": 1,
        "status": "passed",
        "first": summary,
        "replay": {**summary, "created_acceptances": 0, "invoked": False},
        "after_cancel": {
            "action_id": uuid_for(8),
            "receipt_id": uuid_for(13),
            "refresh_classification": "invalidated",
            "refresh_reason": "work_cancelled",
            "as_of_kind": "applicability_refresh_as_of_non_atomic",
            "original_facts_preserved": True,
            "new_call_counts": zero,
        },
        "new_call_counts": zero,
        "cleanup": {
            "first": {"pending": 0, "cleanup_complete": True},
            "replay": {"pending": 0, "cleanup_complete": True},
            "public_pending": 0,
        },
    }
    service = {
        "schema_version": 1,
        "status": "closed",
        "node_version": "24.22.2",
        "invoked": 1,
        "strict_completed": 1,
        "active": 0,
        "requests": 0,
        "sockets": 0,
        "request_sha256": "b" * 64,
        "wire_attempt_id": "attempt_" + uuid_for(2).replace("-", ""),
        "scope": scope,
    }
    return {
        "standalone-authority.json": authority,
        "standalone-service.json": service,
        "standalone-replay.json": replay,
    }


class PackageProofTests(unittest.TestCase):
    # Extension authored by gate author after peer's independent24; root reviews it.
    def rejects(self, proofs):
        with self.assertRaisesRegex(module.GateError, "^invalid_proof$"):
            module.validate_proof_bundle({name: encoded(value) for name, value in proofs.items()})

    def repair_inventory(self, authority):
        authority["inventory_sha256"] = framed_digest(
            [
                {"kind": "counts", **authority["counts"]},
                {"kind": "identity", **authority["identity"]},
                {"kind": "metadata", **authority["metadata"]},
            ]
        )

    def test_distinct_realistic_closed_bundle_and_independent_digest(self):
        proofs = proof_corpus()
        observed = module.validate_proof_bundle({k: encoded(v) for k, v in proofs.items()})
        self.assertEqual(observed, proofs)
        self.assertEqual(
            module.inventory_digest([{"kind": "identity", **proofs[PROOFS[0]]["identity"]}]),
            framed_digest([{"kind": "identity", **proofs[PROOFS[0]]["identity"]}]),
        )

    def test_wrong_valid_wire_SHA_and_wrong_wire_attempt_cannot_borrow_proof(self):
        for field, value in (
            ("request_sha256", "6" * 64),
            ("wire_attempt_id", "attempt_" + uuid_for(99).replace("-", "")),
        ):
            proofs = proof_corpus()
            proofs[PROOFS[1]][field] = value
            self.rejects(proofs)

    def test_authority_changed_result_or_receipt_cannot_borrow_original_summary(self):
        for field, value in (
            ("result_sha256", "6" * 64),
            ("receipt_id", uuid_for(99)),
            ("action_id", uuid_for(99)),
            ("work_id", uuid_for(99)),
        ):
            proofs = proof_corpus()
            authority = proofs[PROOFS[0]]
            authority["identity"][field] = value
            self.repair_inventory(authority)
            self.rejects(proofs)

    def test_source_scope_metadata_and_hash_mismatch_reject(self):
        for which in (
            "foreign_scope",
            "source_mismatch",
            "event_mismatch",
            "ack_hash_mismatch",
            "digest_changed",
        ):
            proofs = proof_corpus()
            authority = proofs[PROOFS[0]]
            if which == "foreign_scope":
                authority["identity"]["scope"]["account_id"] = "foreign_account"
            elif which == "source_mismatch":
                authority["metadata"]["source_id"] = uuid_for(99)
            elif which == "event_mismatch":
                authority["metadata"]["event_id"] = uuid_for(99)
            elif which == "ack_hash_mismatch":
                authority["metadata"]["processing_ack_sha256"] = "6" * 64
            else:
                authority["inventory_sha256"] = "6" * 64
            if which != "digest_changed":
                self.repair_inventory(authority)
            self.rejects(proofs)

    def test_required_identity_fields_and_private_extras_reject(self):
        for key in proof_corpus()[PROOFS[0]]["identity"]:
            proofs = proof_corpus()
            del proofs[PROOFS[0]]["identity"][key]
            self.rejects(proofs)
        for key in PROOFS:
            proofs = proof_corpus()
            proofs[key]["private_headers"] = {"Authorization": "synthetic-denied"}
            self.rejects(proofs)

    def test_bool_integer_substitutions_and_live_occupancy_reject(self):
        for field, value in (
            ("invoked", True),
            ("strict_completed", True),
            ("active", 1),
            ("requests", 1),
            ("sockets", 1),
        ):
            proofs = proof_corpus()
            proofs[PROOFS[1]][field] = value
            self.rejects(proofs)
        proofs = proof_corpus()
        proofs[PROOFS[0]]["counts"]["accepted"] = True
        self.repair_inventory(proofs[PROOFS[0]])
        self.rejects(proofs)
        proofs = proof_corpus()
        proofs[PROOFS[2]]["replay"]["created_acceptances"] = False
        self.rejects(proofs)

    def test_replay_calls_cleanup_and_human_ack_are_separate(self):
        for key in proof_corpus()[PROOFS[2]]["new_call_counts"]:
            proofs = proof_corpus()
            proofs[PROOFS[2]]["new_call_counts"][key] = 1
            self.rejects(proofs)
        for which in ("cleanup", "pending", "human_ack", "current_permission"):
            proofs = proof_corpus()
            record = proofs[PROOFS[2]]
            if which == "cleanup":
                record["cleanup"]["replay"]["cleanup_complete"] = False
            elif which == "pending":
                record["cleanup"]["first"]["pending"] = 1
            elif which == "human_ack":
                record["first"]["human_acknowledgement"] = "observed"
            else:
                record["after_cancel"]["refresh_classification"] = "current"
            self.rejects(proofs)

    def test_unknown_missing_proof_and_malformed_hash_types_reject(self):
        for key in PROOFS:
            proofs = proof_corpus()
            del proofs[key]
            self.rejects(proofs)
        proofs = proof_corpus()
        proofs["private.json"] = {}
        self.rejects(proofs)
        for value in ([], {}, True, None, "g" * 64):
            proofs = proof_corpus()
            proofs[PROOFS[1]]["request_sha256"] = value
            self.rejects(proofs)


class PackageFailureContextTests(unittest.TestCase):
    def test_first_failed_child_context_retains_only_fixed_safe_observations(self):
        for value in (
            {
                "schema_version": 1,
                "status": "failed",
                "mode": "verify",
                "stage": "verify_action",
                "code": "identity_conflict",
                "cleanup_failed": False,
            },
            {
                "schema_version": 1,
                "status": "failed",
                "mode": "verify",
                "stage": [],
                "code": "synthetic_private_value",
                "cleanup_failed": False,
            },
            {
                "schema_version": 1,
                "status": "failed",
                "mode": "verify",
                "stage": "verify_action",
                "code": "synthetic_private_value",
                "cleanup_failed": False,
            },
        ):
            with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
                folder = Path(temporary)
                folder.chmod(0o700)
                run = object.__new__(module.PackageRun)
                run.retained = folder
                run.failure_recorded = False
                run.capture = lambda child, value=value: (encoded(value), b"")
                run.failure_context("verify", SimpleNamespace(pid=os.getpid(), returncode=1))
                observed = json.loads((folder / "failure-context.json").read_bytes())
                self.assertTrue(observed["diagnostic_only"])
                self.assertEqual(observed["returncode"], 1)
                self.assertNotIn(
                    b"synthetic_private_value", (folder / "failure-context.json").read_bytes()
                )
                self.assertEqual(
                    observed["stage"],
                    "verify_action" if value["code"] == "identity_conflict" else "verify",
                )
                before = (folder / "failure-context.json").read_bytes()
                run.failure_context("cleanup", SimpleNamespace(pid=os.getpid(), returncode=1))
                self.assertEqual((folder / "failure-context.json").read_bytes(), before)


class PackageIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="phase38-package-index-", dir="/private/tmp")
        self.folder = Path(self.temp.name)
        self.folder.chmod(0o700)
        self.addCleanup(self.temp.cleanup)

    def write(self, name, raw):
        path = self.folder / name
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
        return path

    def corpus(self, *, omit_nested=False, self_entry=False):
        self.write("package/summary.json", b'{"status":"passed"}\n')
        self.write("commands/stdout.bin", b"")
        files = {
            str(p.relative_to(self.folder)): {
                "bytes": p.stat().st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
            for p in self.folder.rglob("*")
            if p.is_file()
        }
        if omit_nested:
            del files["package/summary.json"]
        if self_entry:
            files["retained-index.json"] = {"bytes": 1, "sha256": "a" * 64}
        raw = encoded({"schema_version": 1, "files": files})
        self.write("retained-index.json", raw)
        return hashlib.sha256(raw).hexdigest()

    def rejects(self, sha):
        with self.assertRaises(module.GateError):
            module.validate_retained_index(self.folder, sha)

    def test_exact_nested_summary_and_empty_capture_pass(self):
        sha = self.corpus()
        value = module.validate_retained_index(self.folder, sha)
        self.assertEqual(set(value["files"]), {"package/summary.json", "commands/stdout.bin"})

    def test_omitted_nested_summary_fails_physical_inventory(self):
        self.rejects(self.corpus(omit_nested=True))

    def test_manifest_cannot_include_itself_or_wrong_hash(self):
        self.rejects(self.corpus(self_entry=True))
        self.rejects("b" * 64)

    def test_extra_file_changed_bytes_and_missing_indexed_file_fail(self):
        sha = self.corpus()
        path = self.write("extra.json", b"{}")
        self.rejects(sha)
        path.unlink()
        original = (self.folder / "package/summary.json").read_bytes()
        (self.folder / "package/summary.json").write_bytes(b'{"status":"failed"}\n')
        self.rejects(sha)
        (self.folder / "package/summary.json").write_bytes(original)
        (self.folder / "commands/stdout.bin").unlink()
        self.rejects(sha)

    def test_symlink_and_hardlink_fail_before_hash_read(self):
        sha = self.corpus()
        path = self.folder / "package/summary.json"
        outside = self.folder.parent / (self.folder.name + "-outside")
        outside.write_bytes(path.read_bytes())
        outside.chmod(0o600)
        self.addCleanup(outside.unlink)
        path.unlink()
        path.symlink_to(outside)
        self.rejects(sha)
        path.unlink()
        os.link(outside, path)
        self.rejects(sha)

    def test_root_file_and_manifest_modes_are_private(self):
        sha = self.corpus()
        for path, mode in (
            (self.folder, 0o755),
            (self.folder / "package/summary.json", 0o644),
            (self.folder / "retained-index.json", 0o644),
        ):
            original = path.stat().st_mode & 0o777
            path.chmod(mode)
            try:
                self.rejects(sha)
            finally:
                path.chmod(original)

    def test_manifest_rejects_private_extra_fields_bool_sizes_and_duplicate_json(self):
        self.corpus()
        path = self.folder / "retained-index.json"
        original = path.read_bytes()
        value = json.loads(original)
        for changed in ({**value, "private_headers": {}}, {**value, "schema_version": True}):
            raw = encoded(changed)
            path.write_bytes(raw)
            self.rejects(hashlib.sha256(raw).hexdigest())
        value = json.loads(original)
        value["files"]["package/summary.json"]["bytes"] = True
        raw = encoded(value)
        path.write_bytes(raw)
        self.rejects(hashlib.sha256(raw).hexdigest())
        raw = b'{"schema_version":1,"schema_version":1,"files":{}}'
        path.write_bytes(raw)
        self.rejects(hashlib.sha256(raw).hexdigest())


if __name__ == "__main__":
    unittest.main()
