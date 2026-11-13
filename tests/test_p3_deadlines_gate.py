"""Offline adversarial checks for temporal evidence; no database or provider setup."""

import copy
import hashlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "p3_deadlines_gate_test", ROOT / "local-setup/scripts/p3_deadlines_check.py"
)
assert SPEC is not None and SPEC.loader is not None
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def encoded(value):
    return json.dumps(value).encode()


def report():
    return {
        "schema_version": 1,
        "status": "passed",
        "mode": "local_synthetic_p3_deadlines_cancellation",
        "tests": 18,
        "passed": 18,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "duration_seconds": 5.5,
        "cleanup_complete": True,
        "case_results": [
            {"name": name, "status": "passed", "code": "ok"} for name in GATE.CASE_NAMES
        ],
        "child_terminations": 1,
        "blocking_graphs_observed": 1,
        "peer_invocations": 9,
        "peer_completed": 9,
        "remote_cancel_acknowledgements": 1,
        "remote_cancel_unknown": 1,
        "provider_calls": False,
        "source_authority": "actual_public_p1_work_v4_deadline_cancellation_action",
        "peer_authority": "bounded_intentionally_noncooperating_node_fault_peer",
        "runtime_change": "validation_only_existing_p3_p1_guards",
        "node_version": "24.22.2",
    }


def context():
    return {
        "P3_DEADLINE_WORK_SCHEMA": "p1_work_deadline_" + "a" * 32,
        "P3_DEADLINE_CASE_SCHEMA": "p3_completion_" + "a" * 32,
        "P3_DEADLINE_SCHEMA": "p3_projection_deadline_" + "a" * 32,
        "P3_DEADLINE_DIRECTORY": "/private/synthetic",
        "P3_DEADLINE_TOKEN": "A" * 43,
        "P3_DEADLINE_PORT": "12345",
        "P3_DEADLINE_BARRIER": "/private/synthetic/issued.reached",
        "P3_DEADLINE_TARGET": "expiry",
    }


def values():
    return {
        "POSTGRES_PORT": "15432",
        "POSTGRES_PASSWORD": "runtime_sentinel",
        "POSTGRES_MIGRATION_PASSWORD": "owner_sentinel",
        "OPENAI_API_KEY": "provider_sentinel",
    }


class DeadlineReportTests(unittest.TestCase):
    def test_valid_complete_report_and_exact_inventory(self):
        self.assertEqual(GATE.validated_report(encoded(report())), report())
        self.assertEqual(len(GATE.CASE_NAMES), 18)
        self.assertEqual(len(set(GATE.CASE_NAMES)), 18)
        self.assertIn("admission_wait_uses_authority_clock", GATE.CASE_NAMES)
        self.assertIn("cancel_ack_running_ignored_result_retained", GATE.CASE_NAMES)

    def test_missing_duplicate_reordered_and_failed_cases_do_not_qualify(self):
        for kind in ("missing", "duplicate", "reordered", "failed", "unknown"):
            item = report()
            if kind == "missing":
                item["case_results"].pop()
            elif kind == "duplicate":
                item["case_results"][0] = item["case_results"][1]
            elif kind == "reordered":
                item["case_results"].reverse()
            elif kind == "failed":
                item["case_results"][0]["status"] = "failed"
            else:
                item["case_results"][0]["name"] = "fabricated"
            with self.subTest(kind=kind), self.assertRaises(GATE.GateError):
                GATE.validated_report(encoded(item))

    def test_primitive_types_and_nonzero_skips_fail(self):
        for key, value in [
            ("tests", True),
            ("child_terminations", True),
            ("cleanup_complete", 1),
            ("provider_calls", 0),
            ("skipped", 1),
            ("peer_completed", 8),
            ("remote_cancel_unknown", 0),
            ("blocking_graphs_observed", 0),
        ]:
            item = report()
            item[key] = value
            with self.subTest(key=key), self.assertRaises(GATE.GateError):
                GATE.validated_report(encoded(item))

    def test_zero_negative_nonfinite_and_overbudget_duration_fail(self):
        for value in (True, 0, -1, 181, float("inf"), float("nan"), 10**4000):
            item = report()
            item["duration_seconds"] = value
            with self.subTest(kind=type(value).__name__), self.assertRaises(GATE.GateError):
                GATE.validated_report(encoded(item))

    def test_unknown_fields_versions_and_modes_fail(self):
        for changes in (
            {"schema_version": 2},
            {"mode": "live"},
            {"source_authority": "model_timestamp"},
            {"peer_authority": "production_ignores_cancel"},
            {"runtime_change": "new_scheduler"},
            {"token": "secret"},
        ):
            item = {**report(), **changes}
            with self.subTest(changes=tuple(changes)), self.assertRaises(GATE.GateError):
                GATE.validated_report(encoded(item))

    def test_duplicate_keys_malformed_utf8_truncation_and_oversize_fail(self):
        raw = encoded(report())
        for data in (
            raw[:-1],
            b"[]",
            b"\xff",
            b"",
            b"x" * (GATE.MAX_REPORT_BYTES + 1),
            raw.replace(b'"schema_version": 1', b'"schema_version": 1,"schema_version": 1'),
            raw.replace(b'"schema_version": 1', b'"schema_version": 1,"\\u0073chema_version": 1'),
        ):
            with self.assertRaises(GATE.GateError):
                GATE.validated_report(data)

    def test_unsupported_node_version_never_qualifies(self):
        for version in (
            None,
            True,
            "v24.22.2",
            "24.22.1",
            "26.12.0",
            "25.0.0",
            "27.0.0",
            "24.22.2\n",
        ):
            item = report()
            item["node_version"] = version
            with self.subTest(version=version), self.assertRaises(GATE.GateError):
                GATE.validated_report(encoded(item))

    def test_known_stage_protocol_is_exact_and_target_bound(self):
        original = {
            "status": "passed",
            "cancel_requested": True,
            "remote_ack": "observed",
            "remote_state": "running",
            "remote_durable": False,
        }
        self.assertEqual(GATE.validated_stage(encoded(original), "cancel-ack"), original)
        for changes in (
            {"remote_state": "stopped"},
            {"remote_ack": "unknown"},
            {"remote_durable": 0},
            {"remote_durable": True},
            {"body": "secret"},
        ):
            with self.assertRaises(GATE.GateError):
                GATE.validated_stage(encoded({**original, **changes}), "cancel-ack")
        wait = {"status": "passed", "authority_expired": True, "target": "crash"}
        self.assertEqual(GATE.validated_stage(encoded(wait), "wait-expiry", "crash"), wait)
        for mode, target in (
            ("wait-expiry", "expiry"),
            ("wait-expiry", None),
            ("seed", "crash"),
            ("crash-late", None),
            ("unknown", None),
        ):
            with self.assertRaises(GATE.GateError):
                GATE.validated_stage(encoded(wait), mode, target)

    def test_peer_final_occupancy_and_ack_truth_are_required(self):
        original = {
            "status": "passed",
            "cleanup_complete": True,
            "node_version": "24.22.2",
            **GATE.PEER_COUNTS,
        }
        self.assertEqual(GATE.peer_report(encoded(original)), original)
        for key, value in (
            ("active", 1),
            ("requests", 1),
            ("sockets", 1),
            ("cancel_ack_lost", 0),
            ("cancel_acknowledgements", 2),
            ("cleanup_complete", 1),
            ("completed", True),
        ):
            with self.assertRaises(GATE.GateError):
                GATE.peer_report(encoded({**original, key: value}))


class DeadlineEnvironmentTests(unittest.TestCase):
    def test_every_mode_receives_only_its_role_and_exact_context(self):
        for mode in GATE.MODE_ORDER:
            with self.subTest(mode=mode):
                env = GATE.child_environment(values(), context(), mode=mode)
                GATE.validate_child_environment(env, mode)
                owner = mode in GATE.OWNER_MODES
                self.assertEqual("P3_DEADLINE_OWNER_PASSWORD" in env, owner)
                self.assertEqual("P3_DEADLINE_RUNTIME_PASSWORD" in env, not owner)
                self.assertNotIn("OPENAI_API_KEY", env)
                self.assertEqual("P3_DEADLINE_TOKEN" in env, not owner)
                self.assertEqual("P3_DEADLINE_TARGET" in env, mode == "wait-expiry")

    def test_ambient_provider_proxy_interpreter_and_pg_selectors_do_not_leak(self):
        injected = {
            "OPENAI_API_KEY": "provider_sentinel",
            "HTTPS_PROXY": "proxy_sentinel",
            "NODE_OPTIONS": "--inspect",
            "PYTHONPATH": "/foreign/source",
            "PGPASSWORD": "pg_sentinel",
            "P3_DEADLINE_OWNER_PASSWORD": "owner_injected",
        }
        with patch.dict(os.environ, injected):
            env = GATE.child_environment(values(), context(), mode="seed")
        for key in injected:
            self.assertNotIn(key, env)

    def test_wrong_role_missing_or_extra_child_keys_fail(self):
        original = GATE.child_environment(values(), context(), mode="seed")
        for extra in (
            {"P3_DEADLINE_OWNER_PASSWORD": "owner"},
            {"OPENAI_API_KEY": "provider"},
            {"NODE_OPTIONS": "--inspect"},
        ):
            with self.assertRaises(GATE.GateError):
                GATE.validate_child_environment({**original, **extra}, "seed")
        for key in ("P3_DEADLINE_TOKEN", "P3_DEADLINE_RUNTIME_PASSWORD", "P3_DEADLINE_WORK_SCHEMA"):
            item = dict(original)
            item.pop(key)
            with self.assertRaises(GATE.GateError):
                GATE.validate_child_environment(item, "seed")

    def test_control_characters_empty_and_nonstrings_fail(self):
        original = GATE.child_environment(values(), context(), mode="seed")
        for value in (True, 7, "", "x\nsecret", "x\rsecret", "x\0secret", "x" * 4097):
            with self.assertRaises(GATE.GateError):
                GATE.validate_child_environment({**original, "P3_DEADLINE_TOKEN": value}, "seed")

    def test_invalid_modes_targets_and_untrusted_context_keys_fail(self):
        with self.assertRaises(GATE.GateError):
            GATE.child_environment(values(), context(), mode="unknown")
        with self.assertRaises(GATE.GateError):
            GATE.child_environment(values(), {**context(), "OPENAI_API_KEY": "secret"}, mode="seed")
        with self.assertRaises(GATE.GateError):
            GATE.child_environment(
                values(), {**context(), "P3_DEADLINE_TARGET": "other"}, mode="wait-expiry"
            )
        with self.assertRaises(GATE.GateError):
            GATE.child_environment({}, context(), mode="seed")


class DeadlineEvidenceTests(unittest.TestCase):
    def test_existing_report_rejected_before_setup_read(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            target = root / ".local/validation/p3-deadlines/already.json"
            target.parent.mkdir(parents=True, mode=0o700)
            target.write_text("existing")
            with patch.object(GATE.core, "load_setup") as setup, redirect_stdout(io.StringIO()):
                self.assertNotEqual(GATE.main(["--report", str(target)], root=root), 0)
            setup.assert_not_called()
            self.assertEqual(target.read_text(), "existing")

    def test_path_escape_symlink_and_insecure_parent_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            for path in (
                Path("outside.json"),
                Path(".local/validation/p3-deadlines/../escaped.json"),
                Path("/tmp/foreign.json"),
            ):
                with self.assertRaises(GATE.GateError):
                    GATE.report_target(root, path)
            parent = root / ".local/validation/p3-deadlines"
            parent.mkdir(parents=True, mode=0o700)
            link = parent / "link"
            link.symlink_to(root, target_is_directory=True)
            with self.assertRaises(GATE.GateError):
                GATE.report_target(root, link / "report.json")
            parent.chmod(0o755)
            with self.assertRaises(GATE.GateError):
                GATE.report_target(root, parent / "report.json")

    def test_report_is_exclusive_private_and_immutable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            path = root / ".local/validation/p3-deadlines/fresh.json"
            GATE.retain_report(root, path, report())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text()), report())
            with self.assertRaises(GATE.GateError):
                GATE.retain_report(root, path, report())

    def test_raw_secrets_are_redacted_across_tail_boundary(self):
        token = "SENTINEL_" * 12
        raw = ("prefix " + token + " suffix").encode()
        result = GATE.redact_capture(raw, (token,))
        self.assertNotIn(token.encode(), result)
        self.assertIn(b"[redacted]", result)

    def test_missing_oversized_duplicate_and_unknown_proofs_fail(self):
        for name, raw in (
            ("unknown.json", b"{}"),
            ("authority-proof.json", b""),
            ("authority-proof.json", b"x" * 32769),
            ("eligibility-lock-proof.json", b'{"schema_version":1,"schema_version":1}'),
        ):
            with self.assertRaises(GATE.GateError):
                GATE.validate_proof(name, raw)

    def test_lock_proof_requires_real_positive_distinct_pids_and_uuid(self):
        valid = {
            "schema_version": 1,
            "owner_backend_pid": 10,
            "waiter_backend_pid": 20,
            "blockers": [10],
            "work_id": "11111111-1111-4111-8111-111111111111",
            "deadline_at_ms": 2000,
            "observed_after_wait_at_ms": 2001,
            "expected_new_grants": 0,
        }
        self.assertEqual(GATE.validate_proof("eligibility-lock-proof.json", encoded(valid)), valid)
        for change in (
            {"owner_backend_pid": -1, "blockers": [-1]},
            {"owner_backend_pid": 20, "blockers": [20]},
            {"work_id": "not-a-work"},
            {"blockers": [True]},
            {"expected_new_grants": False},
            {"observed_after_wait_at_ms": 1999},
        ):
            with self.subTest(change=tuple(change)), self.assertRaises(GATE.GateError):
                GATE.validate_proof("eligibility-lock-proof.json", encoded({**valid, **change}))

    def test_authority_proof_cannot_omit_exact_join_identities(self):
        fake = {
            "schema_version": 1,
            "status": "passed",
            "source_id": "11111111-1111-4111-8111-111111111111",
            "counts": {
                "work": 15,
                "grants": 12,
                "results": 9,
                "cancellations": 5,
                "events": 9,
                "projected": 9,
                "refreshes": 9,
                "intents": 1,
                "effects": 1,
            },
            "records": [
                {
                    "label": str(n),
                    "scope": {"tenant_id": "tenant_deadline", "account_id": "account_deadline"},
                    "cancel_requested": False,
                }
                for n in range(15)
            ],
            "cancellations": [{} for _ in range(5)],
            "useful": {
                "supplier_all_calls": 1,
                "supplier_applied": 1,
                "business_notification_state": "pending",
                "business_notification_attempts": 0,
            },
            "clock_semantics": "invented",
        }
        with self.assertRaises(GATE.GateError):
            GATE.validate_proof("authority-proof.json", encoded(fake))

    def test_peer_proof_cannot_hide_unbounded_or_secret_fields(self):
        fake = {
            "schema_version": 1,
            "status": "passed",
            "counters": dict(GATE.PEER_COUNTS),
            "records": [
                {
                    "label": str(n),
                    "cancel_requested": False,
                    "cancel_acknowledged": False,
                    "cancel_ack_lost": False,
                    "transport_disconnected": False,
                    "response_finished": True,
                    "private_headers": "SECRET_SENTINEL",
                }
                for n in range(9)
            ],
        }
        with self.assertRaises(GATE.GateError):
            GATE.validate_proof("peer-observations.json", encoded(fake))


class DeadlinePositiveProofTests(unittest.TestCase):
    def setUp(self):
        corpus = json.loads((ROOT / "tests/fixtures/p3-deadline-proof.json").read_bytes())
        self.assertEqual(corpus["scope"], "synthetic_parser_examples_not_actual_PG_evidence")
        self.proofs = corpus["proofs"]

    def raw(self, proofs=None):
        return {name: encoded(value) for name, value in (proofs or self.proofs).items()}

    def test_complete_individual_and_joined_proofs_are_accepted(self):
        for name, value in self.proofs.items():
            self.assertEqual(GATE.validate_proof(name, encoded(value)), value)
        self.assertIsNone(GATE.validate_proof_bundle(self.raw()))

    def test_peer_digest_cannot_be_swapped_from_another_valid_result(self):
        for field in ("request_sha256", "result_sha256", "input_fingerprint"):
            changed = copy.deepcopy(self.proofs)
            changed["peer-observations.json"]["records"][0][field] = "b" * 64
            GATE.validate_proof(
                "peer-observations.json", encoded(changed["peer-observations.json"])
            )
            with self.assertRaises(GATE.GateError):
                GATE.validate_proof_bundle(self.raw(changed))

    def test_lock_proof_must_join_its_exact_work_and_original_deadline(self):
        for field, value in (
            ("work_id", "11111111-1111-4111-8111-111111111111"),
            ("deadline_at_ms", 1800000059999),
        ):
            changed = copy.deepcopy(self.proofs)
            changed["eligibility-lock-proof.json"][field] = value
            GATE.validate_proof(
                "eligibility-lock-proof.json", encoded(changed["eligibility-lock-proof.json"])
            )
            with self.assertRaises(GATE.GateError):
                GATE.validate_proof_bundle(self.raw(changed))

    def test_missing_required_fields_and_unknown_nested_fields_fail(self):
        for name, field in (
            ("authority-proof.json", "work_id"),
            ("peer-observations.json", "attempt_id"),
        ):
            changed = copy.deepcopy(self.proofs[name])
            changed["records"][0].pop(field)
            with self.assertRaises(GATE.GateError):
                GATE.validate_proof(name, encoded(changed))
            changed = copy.deepcopy(self.proofs[name])
            changed["records"][0]["private_headers"] = "SECRET_SENTINEL"
            with self.assertRaises(GATE.GateError):
                GATE.validate_proof(name, encoded(changed))

    def test_known_return_requires_finished_invoke_observation(self):
        changed = copy.deepcopy(self.proofs["peer-observations.json"])
        row = next(row for row in changed["records"] if row["label"] == "cancel")
        row["response_finished"] = False
        with self.assertRaises(GATE.GateError):
            GATE.validate_proof("peer-observations.json", encoded(changed))

    def test_proof_retention_preserves_exact_bytes_hashes_and_privacy(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            work = root / "private"
            work.mkdir(mode=0o700)
            target = root / ".local/validation/p3-deadlines/final.json"
            target.parent.mkdir(parents=True, mode=0o700)
            raw = self.raw()
            for name, value in raw.items():
                (work / name).write_bytes(value)
                (work / name).chmod(0o600)
            saved = root / GATE.retain_proof(root, target, work)
            manifest = json.loads((saved / "manifest.json").read_bytes())
            self.assertFalse(manifest["raw_request_confirmation_credentials_retained"])
            self.assertEqual(len(manifest["records"]), 3)
            for row in manifest["records"]:
                self.assertEqual((saved / row["path"]).read_bytes(), raw[row["path"]])
                self.assertEqual(row["sha256"], hashlib.sha256(raw[row["path"]]).hexdigest())
                self.assertEqual(row["bytes"], len(raw[row["path"]]))
                self.assertEqual((saved / row["path"]).stat().st_mode & 0o777, 0o600)
            with self.assertRaises(GATE.GateError):
                GATE.retain_proof(root, target, work)

    def test_linked_or_missing_proofs_never_publish_partial_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            work = root / "private"
            work.mkdir(mode=0o700)
            target = root / ".local/validation/p3-deadlines/final.json"
            target.parent.mkdir(parents=True, mode=0o700)
            for name, value in self.raw().items():
                (work / name).write_bytes(value)
                (work / name).chmod(0o600)
            source = work / "authority-proof.json"
            source.rename(work / "linked-source")
            source.symlink_to(work / "linked-source")
            with self.assertRaises(GATE.GateError):
                GATE.retain_proof(root, target, work)
            self.assertFalse(target.with_name("final-artifacts").exists())


if __name__ == "__main__":
    unittest.main()
