"""Independent offline negative contracts for P3 process-recovery tooling."""

import copy
import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "p3_recovery_gate_test", ROOT / "local-setup/scripts/p3_recovery_check.py"
)
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)
EXPECTED_REPORT = {
    "autonomous_scheduler": False,
    "blocking_graphs_observed": 1,
    "case_results": [
        {
            "code": "ok",
            "name": "specialist_process_kill_retains_accepted_input",
            "status": "passed",
        },
        {"code": "ok", "name": "original_issue_replay_never_reinvokes", "status": "passed"},
        {
            "code": "ok",
            "name": "premature_new_command_waits_for_authority_lease",
            "status": "passed",
        },
        {"code": "ok", "name": "explicit_new_command_recovers_useful_result", "status": "passed"},
        {"code": "ok", "name": "coordinator_http_loss_remote_cleanup_observed", "status": "passed"},
        {
            "code": "ok",
            "name": "fresh_coordinator_preserves_input_attempt_history",
            "status": "passed",
        },
        {"code": "ok", "name": "concurrent_recovery_one_created_issue", "status": "passed"},
        {
            "code": "ok",
            "name": "result_precommit_kill_rolls_back_result_and_event",
            "status": "passed",
        },
        {
            "code": "ok",
            "name": "result_postcommit_kill_original_bytes_replayed",
            "status": "passed",
        },
        {
            "code": "ok",
            "name": "possible_delivery_restart_remains_lookup_only_unknown",
            "status": "passed",
        },
        {
            "code": "ok",
            "name": "later_current_work_progresses_around_unknown_gap",
            "status": "passed",
        },
        {
            "code": "ok",
            "name": "receiver_commit_kill_original_receipt_reconciled",
            "status": "passed",
        },
        {
            "code": "ok",
            "name": "fresh_processing_replay_preserves_original_ack",
            "status": "passed",
        },
        {
            "code": "ok",
            "name": "action_commit_kill_exact_confirmation_original_receipt",
            "status": "passed",
        },
        {
            "code": "ok",
            "name": "changed_completion_command_scope_rejected_without_effect",
            "status": "passed",
        },
        {
            "code": "ok",
            "name": "independent_history_receiver_supplier_joins_and_cleanup",
            "status": "passed",
        },
        {
            "code": "ok",
            "name": "coordinator_post_issue_crash_before_first_http",
            "status": "passed",
        },
    ],
    "child_terminations": 8,
    "cleanup_complete": True,
    "completion_case_authority": "actual_p1_case_v4_exact_confirmation",
    "early_case_authority": "synthetic_read_only_only",
    "errors": 0,
    "exactly_once_physical_computation_claimed": False,
    "failures": 0,
    "mode": "local_synthetic_p3_recovery",
    "passed": 17,
    "provider_calls": False,
    "schema_version": 1,
    "skipped": 0,
    "source_authority": "actual_p1_work_v4_existing_execution_completion",
    "status": "passed",
    "supplier_authority": "independent_synthetic_sqlite_actual_leased_worker",
    "tests": 17,
}
EXPECTED_STAGES = {
    "action-crash": None,
    "action-resume": {
        "cases": ["action_commit_kill_exact_confirmation_original_receipt"],
        "mode": "action-resume",
        "original_action_equal": True,
        "schema_version": 1,
        "status": "passed",
        "supplier_apply_calls": 1,
        "supplier_receipts": 1,
    },
    "cleanup": {
        "cases": [],
        "mode": "cleanup",
        "schema_version": 1,
        "schemas_removed": True,
        "status": "passed",
    },
    "conflicts": {
        "cases": ["changed_completion_command_scope_rejected_without_effect"],
        "completion_conflict": "identity_conflict",
        "confirmation_conflict": "identity_conflict",
        "extra_effects": 0,
        "foreign_result": "not_found",
        "known_after_later_cancel": True,
        "mode": "conflicts",
        "new_issue_after_result": "identity_conflict",
        "original_action_after_cancel_equal": True,
        "original_delivery_after_cancel_equal": True,
        "schema_version": 1,
        "status": "passed",
    },
    "coordinator-crash": None,
    "coordinator-resume": {
        "cases": [
            "coordinator_http_loss_remote_cleanup_observed",
            "fresh_coordinator_preserves_input_attempt_history",
        ],
        "mode": "coordinator-resume",
        "new_command_invoked": True,
        "old_command_invoked": False,
        "prior_remote_active": 0,
        "schema_version": 1,
        "status": "passed",
    },
    "delivery-begin-crash": None,
    "install": {
        "case_version": 4,
        "cases": [],
        "mode": "install",
        "projection_version": 3,
        "schema_version": 1,
        "scopes": 2,
        "status": "passed",
        "work_version": 4,
    },
    "issued-crash": None,
    "issued-replay": {
        "cases": [
            "coordinator_post_issue_crash_before_first_http",
            "premature_new_command_waits_for_authority_lease",
        ],
        "changed_owner_code": "identity_conflict",
        "mode": "issued-replay",
        "new_invocations": 0,
        "original_owner_replayed": True,
        "premature_code": "capacity",
        "schema_version": 1,
        "status": "passed",
    },
    "owner-check": {
        "accepted": 7,
        "acks": 1,
        "action_receipts": 1,
        "attempts": 11,
        "business_completions": 1,
        "cases": ["independent_history_receiver_supplier_joins_and_cleanup"],
        "delivery_intents": 2,
        "delivery_receipts": 1,
        "events": 7,
        "exact_reconciliation": True,
        "intents": 1,
        "mode": "owner-check",
        "projected": 2,
        "receiver_accept_calls": 1,
        "receiver_receipts": 1,
        "results": 7,
        "schema_version": 1,
        "status": "passed",
        "supplier_apply_calls": 1,
        "supplier_receipts": 1,
    },
    "processing-replay": {
        "cases": ["fresh_processing_replay_preserves_original_ack"],
        "fresh_direct_delivery_accept_calls": 0,
        "fresh_direct_delivery_receipt_equal": True,
        "mode": "processing-replay",
        "new_receiver_accept_calls": 0,
        "original_ack_equal": True,
        "schema_version": 1,
        "status": "passed",
        "unknown_gap_unacked": True,
    },
    "race-a": {"cases": [], "mode": "race-a", "schema_version": 1, "side": "a", "status": "passed"},
    "race-b": {"cases": [], "mode": "race-b", "schema_version": 1, "side": "b", "status": "passed"},
    "race-locker": {
        "authority_lease_expired": True,
        "blocked": True,
        "cases": [],
        "graphs": 1,
        "mode": "race-locker",
        "schema_version": 1,
        "status": "passed",
        "waiters": 2,
    },
    "race-verify": {
        "cases": [
            "explicit_new_command_recovers_useful_result",
            "concurrent_recovery_one_created_issue",
        ],
        "created_issues": 1,
        "mode": "race-verify",
        "new_invocations": 1,
        "schema_version": 1,
        "status": "passed",
    },
    "receiver-crash": None,
    "receiver-resume": {
        "cases": [
            "later_current_work_progresses_around_unknown_gap",
            "receiver_commit_kill_original_receipt_reconciled",
        ],
        "delivery_state": "accepted",
        "mode": "receiver-resume",
        "receiver_accept_calls": 1,
        "schema_version": 1,
        "status": "passed",
        "terminal_acks": 1,
        "unknown_gap_unacked": True,
    },
    "result-after-crash": None,
    "result-after-resume": {
        "cases": ["result_postcommit_kill_original_bytes_replayed"],
        "mode": "result-after-resume",
        "new_invocations": 0,
        "original_bytes_equal": True,
        "original_events": 1,
        "schema_version": 1,
        "status": "passed",
    },
    "result-before-crash": None,
    "result-before-resume": {
        "cases": ["result_precommit_kill_rolls_back_result_and_event"],
        "mode": "result-before-resume",
        "new_command_invoked": True,
        "rolled_back_events": 0,
        "rolled_back_results": 0,
        "schema_version": 1,
        "status": "passed",
    },
    "specialist-loss": {
        "accepted_preserved": True,
        "cases": ["specialist_process_kill_retains_accepted_input"],
        "mode": "specialist-loss",
        "observed_code": "transport_unknown",
        "schema_version": 1,
        "status": "passed",
    },
    "specialist-resume": {
        "cases": ["original_issue_replay_never_reinvokes"],
        "mode": "specialist-resume",
        "new_command_invoked": True,
        "old_command_invoked": False,
        "schema_version": 1,
        "status": "passed",
    },
    "unknown-resume": {
        "cases": ["possible_delivery_restart_remains_lookup_only_unknown"],
        "delivery_state": "unknown",
        "mode": "unknown-resume",
        "receiver_accept_calls": 0,
        "schema_version": 1,
        "status": "passed",
        "terminal_acks": 0,
    },
}


def encoded(value):
    return json.dumps(value).encode()


def proofs():
    return json.loads((ROOT / "tests/fixtures/p3-recovery-proof-positive.json").read_text())


def report():
    return {
        **copy.deepcopy(EXPECTED_REPORT),
        "duration_seconds": 8.5,
        "child_commands": 28,
        "node_version": "24.22.2",
        "proofs": {
            name: {
                "bytes": len(encoded(value)),
                "sha256": hashlib.sha256(encoded(value)).hexdigest(),
            }
            for name, value in proofs().items()
        },
    }


def context():
    return {
        "P3_RECOVERY_WORK_SCHEMA": "p1_work_recovery_" + "a" * 32,
        "P3_RECOVERY_CASE_SCHEMA": "p3_completion_" + "a" * 32,
        "P3_RECOVERY_PROJECTION_SCHEMA": "p3_projection_recovery_" + "a" * 32,
        "P3_RECOVERY_DIRECTORY": "/private/synthetic-recovery",
        "P3_RECOVERY_ENDPOINT_FILE": "/private/synthetic-recovery/endpoint-b.json",
        "P3_RECOVERY_EXECUTION_TOKEN": "A" * 43,
        "P3_RECOVERY_COMPLETION_TOKEN": "B" * 43,
        "P3_RECOVERY_NODE_TOKEN": "C" * 43,
    }


def environment(mode):
    c = context()
    if mode in {
        "issued-crash",
        "issued-replay",
        "race-a",
        "race-b",
        "race-verify",
        "specialist-loss",
    }:
        c["P3_RECOVERY_ENDPOINT_FILE"] = "/private/synthetic-recovery/endpoint-a.json"
    if mode in GATE.BARRIERS:
        c["P3_RECOVERY_BARRIER"] = str(
            Path(c["P3_RECOVERY_DIRECTORY"]) / (GATE.BARRIERS[mode] + ".reached")
        )
    return GATE.child_environment(
        {
            "POSTGRES_PORT": "15432",
            "POSTGRES_PASSWORD": "runtime_sentinel",
            "POSTGRES_MIGRATION_PASSWORD": "owner_sentinel",
        },
        mode=mode,
        context=c,
    )


class RecoveryReportTests(unittest.TestCase):
    def test_independent_frozen_case_and_mode_inventory(self):
        self.assertEqual(
            tuple(GATE.CASE_NAMES),
            tuple(EXPECTED_REPORT["case_results"][i]["name"] for i in range(17)),
        )
        self.assertEqual(set(GATE.MODE_ORDER), set(EXPECTED_STAGES))
        self.assertEqual(len(GATE.MODE_ORDER), 25)
        self.assertEqual(len([v for v in EXPECTED_STAGES.values() if v is None]), 7)
        self.assertEqual(GATE.validated_report(encoded(report())), report())

    def test_every_original_success_stage_and_no_fabricated_kill_reply(self):
        for mode, expected in EXPECTED_STAGES.items():
            with self.subTest(mode=mode):
                if expected is None:
                    with self.assertRaises(GATE.GateError):
                        GATE.validated_stage(b'{"status":"passed"}', mode)
                else:
                    self.assertEqual(GATE.validated_stage(encoded(expected), mode), expected)

    def test_missing_extra_bool_and_changed_stage_fields_fail_closed(self):
        for mode, expected in EXPECTED_STAGES.items():
            if expected is None:
                continue
            for key in expected:
                for kind in ("missing", "changed"):
                    value = copy.deepcopy(expected)
                    if kind == "missing":
                        del value[key]
                    elif type(value[key]) is int:
                        value[key] = True
                    elif type(value[key]) is bool:
                        value[key] = int(value[key])
                    elif type(value[key]) is list:
                        value[key] = [] if value[key] else ["invented"]
                    else:
                        value[key] = "fabricated"
                    with (
                        self.subTest(mode=mode, key=key, kind=kind),
                        self.assertRaises(GATE.GateError),
                    ):
                        GATE.validated_stage(encoded(value), mode)
            with self.assertRaises(GATE.GateError):
                GATE.validated_stage(encoded({**expected, "token": "secret"}), mode)

    def test_exact_children_kills_graphs_skips_and_authority_claims(self):
        for key, value in [
            ("child_commands", 0),
            ("child_commands", 1),
            ("child_commands", 27),
            ("child_commands", 29),
            ("child_commands", 32),
            ("child_commands", True),
            ("child_terminations", 7),
            ("child_terminations", True),
            ("blocking_graphs_observed", 0),
            ("skipped", 1),
            ("provider_calls", 0),
            ("cleanup_complete", 1),
            ("autonomous_scheduler", True),
            ("exactly_once_physical_computation_claimed", True),
        ]:
            item = {**report(), key: value}
            with self.subTest(key=key, value=value), self.assertRaises(GATE.GateError):
                GATE.validated_report(encoded(item))

    def test_named_cases_missing_duplicate_reordered_and_wrong_modes_fail(self):
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
                item["mode"] = "health_only"
            with self.subTest(kind=kind), self.assertRaises(GATE.GateError):
                GATE.validated_report(encoded(item))

    def test_duration_nonfinite_huge_zero_and_expired_fail(self):
        for value in (0, -1, 181, True, float("nan"), float("inf"), 10**1000):
            with self.subTest(kind=type(value).__name__), self.assertRaises(GATE.GateError):
                GATE.validated_report(encoded({**report(), "duration_seconds": value}))

    def test_wrong_runtime_missing_proofs_and_false_primitive_types_fail(self):
        for version in (None, True, "v24.22.2", "24.22.1", "25.0.0", "26.12.0", "24.22.2\n"):
            with self.subTest(version=version), self.assertRaises(GATE.GateError):
                GATE.validated_report(encoded({**report(), "node_version": version}))
        for kind in ("missing", "extra", "bad_hash", "bool_size", "zero_size", "large_size"):
            item = report()
            p = item["proofs"]
            if kind == "missing":
                p.pop("recovery-lock.json")
            elif kind == "extra":
                p["private.env"] = {"bytes": 1, "sha256": "a" * 64}
            elif kind == "bad_hash":
                p["recovery-lock.json"]["sha256"] = "x" * 64
            elif kind == "bool_size":
                p["recovery-lock.json"]["bytes"] = True
            elif kind == "zero_size":
                p["recovery-lock.json"]["bytes"] = 0
            else:
                p["recovery-lock.json"]["bytes"] = 32769
            with self.subTest(kind=kind), self.assertRaises(GATE.GateError):
                GATE.validated_report(encoded(item))

    def test_malformed_json_duplicate_aliases_utf8_and_capture_bounds_fail(self):
        raw = encoded(report())
        for data in (
            b"",
            b"[]",
            b"\xff",
            raw[:-1],
            b"x" * 32769,
            raw.replace(b'"schema_version": 1', b'"schema_version": 1,"schema_version": 1'),
            raw.replace(b'"schema_version": 1', b'"schema_version": 1,"\\u0073chema_version": 1'),
        ):
            with self.assertRaises(GATE.GateError):
                GATE.validated_report(data)


class RecoveryEnvironmentTests(unittest.TestCase):
    def test_all_twenty_five_roles_are_exact_and_provider_free(self):
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "provider_sentinel",
                "PGPASSWORD": "ambient_sentinel",
                "PYTHONPATH": "foreign",
                "HTTP_PROXY": "http://private",
            },
            clear=False,
        ):
            for mode in EXPECTED_STAGES:
                env = environment(mode)
                GATE.validate_child_environment(env, mode)
                self.assertFalse(
                    {"OPENAI_API_KEY", "PGPASSWORD", "PYTHONPATH", "HTTP_PROXY"} & env.keys()
                )
                password = (
                    "P3_RECOVERY_OWNER_PASSWORD"
                    if mode in GATE.OWNER_MODES
                    else "P3_RECOVERY_RUNTIME_PASSWORD"
                )
                self.assertIn(password, env)
                self.assertNotIn(
                    "P3_RECOVERY_RUNTIME_PASSWORD"
                    if mode in GATE.OWNER_MODES
                    else "P3_RECOVERY_OWNER_PASSWORD",
                    env,
                )

    def test_extra_missing_empty_dual_credentials_and_nonstring_fail(self):
        for mode in ("install", "issued-replay"):
            base = environment(mode)
            for key in tuple(GATE.MODE_KEYS[mode]):
                item = {**base}
                del item[key]
                with self.subTest(mode=mode, missing=key), self.assertRaises(GATE.GateError):
                    GATE.validate_child_environment(item, mode)
            for extra in (
                "OPENAI_API_KEY",
                "PGPASSWORD",
                "PYTHONPATH",
                "HTTP_PROXY",
                "P3_RECOVERY_RUNTIME_PASSWORD"
                if mode == "install"
                else "P3_RECOVERY_OWNER_PASSWORD",
            ):
                with self.subTest(extra=extra), self.assertRaises(GATE.GateError):
                    GATE.validate_child_environment({**base, extra: "secret"}, mode)
            for value in ("", None, True, "x\0y"):
                with self.assertRaises(GATE.GateError):
                    GATE.validate_child_environment({**base, "P3_RECOVERY_PG_PORT": value}, mode)

    def test_paths_schema_ports_and_barrier_cannot_escape_trusted_owner(self):
        for key, value in [
            ("P3_RECOVERY_WORK_SCHEMA", "public"),
            ("P3_RECOVERY_CASE_SCHEMA", "p3_completion_" + ("a" * 32) + "\n"),
            ("P3_RECOVERY_PG_PORT", "65536"),
            ("P3_RECOVERY_PG_PORT", "-1"),
            ("P3_RECOVERY_DIRECTORY", "relative"),
            ("P3_RECOVERY_DIRECTORY", "/private/../foreign"),
            ("P3_RECOVERY_ENDPOINT_FILE", "/foreign/endpoint-b.json"),
        ]:
            with self.subTest(key=key, value=value), self.assertRaises(GATE.GateError):
                GATE.validate_child_environment(
                    {**environment("issued-replay"), key: value}, "issued-replay"
                )
        with self.assertRaises(GATE.GateError):
            GATE.validate_child_environment(
                {**environment("issued-crash"), "P3_RECOVERY_BARRIER": "/foreign/barrier.reached"},
                "issued-crash",
            )


class RecoveryProofTests(unittest.TestCase):
    def test_positive_independent_three_proof_corpus_and_cross_joins(self):
        values = proofs()
        raw = {n: encoded(v) for n, v in values.items()}
        for name, value in values.items():
            self.assertEqual(GATE.validate_proof(name, raw[name]), value)
        GATE.validate_proof_bundle(raw)

    def test_every_proof_rejects_extra_authority_duplicate_keys_and_bad_primitive(self):
        for name, value in proofs().items():
            for item in (
                {**value, "token": "secret"},
                {**value, "schema_version": True},
                {**value, "status": "unknown"},
            ):
                with self.subTest(name=name), self.assertRaises(GATE.GateError):
                    GATE.validate_proof(name, encoded(item))
            raw = encoded(value).replace(
                b'"schema_version": 1', b'"schema_version": 1,"schema_version": 1'
            )
            with self.assertRaises(GATE.GateError):
                GATE.validate_proof(name, raw)

    def test_missing_duplicate_false_graph_and_authority_clock_fail(self):
        original = proofs()["recovery-lock.json"]
        for kind in ("duplicate", "no_block", "self_block", "false_clock", "false_graph"):
            item = copy.deepcopy(original)
            if kind == "duplicate":
                item["waiters"][1] = item["waiters"][0]
            elif kind == "no_block":
                item["waiters"][0]["blockers"] = []
            elif kind == "self_block":
                item["waiters"][0]["blockers"] = [item["waiters"][0]["pid"]]
            elif kind == "false_clock":
                item["observed_db_clock_ms"] = item["old_lease_until_ms"] - 1
            else:
                item["graphs"] = True
            with self.subTest(kind=kind), self.assertRaises(GATE.GateError):
                GATE.validate_proof("recovery-lock.json", encoded(item))

    def test_lock_requires_exact_owned_backend_set_roles_and_private_schema(self):
        base = proofs()["recovery-lock.json"]
        for kind in (
            "foreign_backend",
            "duplicate_process",
            "reordered_roles",
            "owner_overlap",
            "public_schema",
            "missing_writers",
        ):
            item = copy.deepcopy(base)
            if kind == "foreign_backend":
                item["owned_writers"][0]["backend_pid"] += 1000
            elif kind == "duplicate_process":
                item["owned_writers"][1]["process_pid"] = item["owned_writers"][0]["process_pid"]
            elif kind == "reordered_roles":
                item["owned_writers"].reverse()
            elif kind == "owner_overlap":
                item["owned_writers"][0]["backend_pid"] = item["owner_backend_pid"]
            elif kind == "public_schema":
                item["work_schema"] = "public"
            else:
                del item["owned_writers"]
            with self.subTest(kind=kind), self.assertRaises(GATE.GateError):
                GATE.validate_proof("recovery-lock.json", encoded(item))

    def test_lock_visibility_is_truthful_and_admission_target_is_exact(self):
        base = proofs()["recovery-lock.json"]
        for key, value in [
            ("query_visibility", "observed_raw_sql"),
            ("query_visibility", True),
            ("lock_target", "unrelated_table"),
            ("lock_target", None),
        ]:
            item = {**base, key: value}
            with self.subTest(key=key), self.assertRaises(GATE.GateError):
                GATE.validate_proof("recovery-lock.json", encoded(item))
        for key in ("query_visibility", "lock_target"):
            item = dict(base)
            del item[key]
            with self.assertRaises(GATE.GateError):
                GATE.validate_proof("recovery-lock.json", encoded(item))

    def test_parent_owned_process_identities_cannot_be_substituted(self):
        value = proofs()["recovery-lock.json"]
        pids = tuple(w["process_pid"] for w in value["owned_writers"])
        self.assertEqual(
            GATE.validated_owned_lock(
                encoded(value), work_schema=value["work_schema"], process_ids=pids
            ),
            value,
        )
        for schema, owned in [
            (value["work_schema"], tuple(reversed(pids))),
            (value["work_schema"], (1234, 5678)),
            ("p1_work_recovery_" + "b" * 32, pids),
        ]:
            with self.assertRaises(GATE.GateError):
                GATE.validated_owned_lock(encoded(value), work_schema=schema, process_ids=owned)

    def test_authority_counts_no_unknown_gap_ack_or_extra_supplier_apply(self):
        base = proofs()["recovery-authority.json"]
        for key in base["counts"]:
            item = copy.deepcopy(base)
            item["counts"][key] += 1
            with self.subTest(key=key), self.assertRaises(GATE.GateError):
                GATE.validate_proof("recovery-authority.json", encoded(item))

    def test_proof_inventory_is_domain_separated_length_prefixed_and_bounded(self):
        records = [{"a": 1}, {"b": "x"}]
        digest = hashlib.sha256(b"p3-recovery-inventory-v1\0")
        for value in records:
            raw = json.dumps(
                value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
            digest.update(len(raw).to_bytes(4, "big"))
            digest.update(raw)
        self.assertEqual(GATE.inventory_digest(records), digest.hexdigest())
        for values in ([], [{}] * 65, [{"x": "a" * 4097}], [{"x": float("nan")}], [None]):
            with self.assertRaises(GATE.GateError):
                GATE.inventory_digest(values)

    def test_private_proof_files_reject_symlink_hardlink_mode_and_oversize(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            p = root / "proof.json"
            p.write_bytes(b"{}")
            p.chmod(0o600)
            self.assertEqual(GATE.bounded_read(p, 32), b"{}")
            q = root / "symlink"
            q.symlink_to(p)
            with self.assertRaises(GATE.GateError):
                GATE.bounded_read(q, 32)
            q.unlink()
            q.hardlink_to(p)
            with self.assertRaises(GATE.GateError):
                GATE.bounded_read(p, 32)
            q.unlink()
            p.chmod(0o644)
            with self.assertRaises(GATE.GateError):
                GATE.bounded_read(p, 32)
            p.chmod(0o600)
            p.write_bytes(b"x" * 33)
            with self.assertRaises(GATE.GateError):
                GATE.bounded_read(p, 32)

    def test_target_fresh_owned_one_level_and_no_sidecar_reuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            target = GATE.target_path(root, Path(".local/validation/p3-recovery/fresh.json"))
            for path in (
                Path("../outside.json"),
                Path(".local/validation/p3-recovery/nested/fresh.json"),
                Path(".local/validation/p3-recovery/../outside.json"),
            ):
                with self.assertRaises(GATE.GateError):
                    GATE.target_path(root, path)
            target.with_name("fresh-artifacts").mkdir(mode=0o700)
            with self.assertRaises(GATE.GateError):
                GATE.target_path(root, Path(".local/validation/p3-recovery/fresh.json"))


class RecoveryDiagnosticTests(unittest.TestCase):
    def sample(self):
        return {
            "schema_version": 1,
            "status": "failed",
            "mode": "race-locker",
            "stage": "race_query_identity",
            "error_type": "AssertionError",
            "code": "fixture_failed",
            "diagnostics": {
                "queryVisibility": "redacted",
                "cleanup_failure": False,
                "owned_backend_ids": [1001, 1002],
                "waiters": [
                    {"pid": 1001, "blockers": [1000]},
                    {"pid": 1002, "blockers": [1000, 1001]},
                ],
            },
        }

    def test_only_fixed_body_free_nonqualifying_failure_shape_is_retained(self):
        value = self.sample()
        self.assertEqual(GATE.validated_failure(encoded(value), "race-locker"), value)
        for changes in (
            {"status": "passed"},
            {"schema_version": True},
            {"stage": "raw exception body"},
            {"error_type": "SecretError"},
            {"code": "credentialsentinel"},
            {"message": "secret"},
            {"mode": "issued-replay"},
        ):
            with self.subTest(changes=tuple(changes)), self.assertRaises(GATE.GateError):
                GATE.validated_failure(encoded({**value, **changes}), "race-locker")
        value["mode"] = "unknown-mode"
        with self.assertRaises(GATE.GateError):
            GATE.validated_failure(encoded(value), "unknown-mode")

    def test_observed_backend_identity_and_visibility_bounds_fail_closed(self):
        for key, value in [
            ("queryVisibility", "SELECT secret"),
            ("owned_backend_ids", [True]),
            ("owned_backend_ids", [1, 1]),
            ("owned_backend_ids", [1, 2, 3]),
            ("waiters", [{"pid": 9999, "blockers": [1000]}]),
            ("waiters", [{"pid": 1001, "blockers": [True]}]),
        ]:
            item = self.sample()
            item["diagnostics"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(GATE.GateError):
                GATE.validated_failure(encoded(item), "race-locker")

    def test_duplicate_alias_truncated_and_oversized_failure_captures_are_not_retained(self):
        raw = encoded(self.sample())
        for value in (
            raw[:-1],
            b"\xff",
            b"x" * 2049,
            raw.replace(b'"schema_version": 1', b'"schema_version": 1,"\\u0073chema_version": 1'),
        ):
            with self.assertRaises(GATE.GateError):
                GATE.validated_failure(value, "race-locker")


class RecoveryParentDiagnosticTests(unittest.TestCase):
    def sample(self):
        return {
            "schema_version": 1,
            "status": "failed",
            "diagnostic_only": True,
            "parent_observation": {
                "child": "coordinator-crash",
                "operation": "wait",
                "barrier": "coordinator_http_started",
                "kind": "timeout",
                "process_pid": 12345,
                "returncode": None,
            },
            "child_failure": None,
        }

    def test_closed_parent_observation_keeps_live_timeout_unobserved(self):
        value = self.sample()
        self.assertEqual(GATE.validated_parent_failure(encoded(value)), value)
        for changes in [
            {"diagnostic_only": False},
            {"schema_version": True},
            {"status": "passed"},
            {"message": "secret"},
        ]:
            with self.assertRaises(GATE.GateError):
                GATE.validated_parent_failure(encoded({**value, **changes}))

    def test_parent_child_barrier_operation_and_pid_are_closed(self):
        for key, value in [
            ("child", "arbitrary_secret"),
            ("operation", "shell"),
            ("barrier", "issue_commit"),
            ("kind", "assumed_stopped"),
            ("process_pid", True),
            ("process_pid", 0),
            ("returncode", True),
            ("returncode", 256),
        ]:
            item = self.sample()
            item["parent_observation"][key] = value
            with self.subTest(key=key), self.assertRaises(GATE.GateError):
                GATE.validated_parent_failure(encoded(item))
        item = self.sample()
        item["parent_observation"].update(operation="kill", barrier=None, kind="control_error")
        GATE.validated_parent_failure(encoded(item))

    def test_child_failure_requires_observed_exit_and_original_child_mode(self):
        item = self.sample()
        failure = RecoveryDiagnosticTests().sample()
        failure["mode"] = "coordinator-crash"
        failure["stage"] = "coordinator-crash"
        item["child_failure"] = failure
        with self.assertRaises(GATE.GateError):
            GATE.validated_parent_failure(encoded(item))
        item["parent_observation"].update(returncode=1, kind="exited")
        GATE.validated_parent_failure(encoded(item))
        item["child_failure"]["mode"] = "race-locker"
        with self.assertRaises(GATE.GateError):
            GATE.validated_parent_failure(encoded(item))
