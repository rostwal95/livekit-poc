"""Independent finite report/environment/factual proof negatives; no services or builds."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "fixed_policy_gate_negative_tests", ROOT / "local-setup/scripts/p3_fixed_policy_check.py"
)
assert SPEC is not None and SPEC.loader is not None
GATE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = GATE
SPEC.loader.exec_module(GATE)
CASES = (
    "legacy_policy_v1_canonical_defaults_and_document_v1_unchanged",
    "v2_request_canonical_fingerprint_and_nested_snapshot",
    "v2_result_strict_states_witness_bounds_and_safe_provenance",
    "actual_TypeScript_producer_Python_consumer_parity",
    "identity_scope_revision_attempt_fingerprint_source_binding_rejection",
    "schema_valid_wrong_decision_rule_threshold_or_fact_fails_factual_verifier",
    "missing_agreeing_conflicting_exact_fact_witness_semantics",
    "expired_result_still_rejects_forged_facts_before_timeliness",
    "actual_HTTP_eligible_ineligible_and_threshold_useful_results",
    "actual_HTTP_missing_and_conflicting_clarification_without_invention",
    "actual_HTTP_policy_and_fact_prompt_text_is_inert",
    "actual_HTTP_adversarial_PNG_document_path_remains_grounded",
    "invoke_result_cancel_evidence_permissions_wrong_scope_zero_evaluation",
    "unknown_source_digest_version_URL_and_swapped_facts_rejected",
    "unsupported_policy_version_rule_threshold_or_malformed_source_rejected",
    "expired_before_start_and_after_held_validation_zero_new_evaluation_then_progress",
    "shared_global_per_principal_attempt_caps_and_other_principal_progress",
    "cancel_timeout_abandonment_retains_actual_held_work_and_truthful_status",
    "close_incomplete_retains_owners_retry_observes_actual_settlement",
    "configured_public_examples_strict_types_exact_wire_proofs_and_zero_owned_occupancy",
)


def wire(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def report(installed=False):
    return {
        "schema_version": 1,
        "status": "passed",
        "mode": "local_fixed_policy_installed" if installed else "local_fixed_policy_source",
        "tests": 20,
        "passed": 20,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "duration_seconds": 1.25,
        "child_commands": 27 if installed else 6,
        "package_assertions": 8 if installed else 0,
        "cleanup_complete": True,
        "code": "ok",
        "stage": "complete",
        "retained_index_sha256": "a" * 64,
        "case_results": [{"name": name, "status": "passed"} for name in CASES],
    }


class FixedPolicyGateNegatives(unittest.TestCase):
    def rejects(self, value):
        with self.assertRaises(GATE.GateError):
            GATE.validated_report(wire(value))

    def test_exact_source_and_installed_inventories_have_distinct_commands(self):
        self.assertEqual(GATE.CASE_NAMES, CASES)
        for installed in (False, True):
            value = report(installed)
            self.assertEqual(GATE.validated_report(wire(value)), value)
            for name, wrong in (
                ("child_commands", 6 if installed else 27),
                ("package_assertions", 0 if installed else 8),
                ("cleanup_complete", False),
                ("tests", 0),
                ("passed", 0),
                ("skipped", 1),
                ("errors", 1),
                ("failures", 1),
            ):
                bad = copy.deepcopy(value)
                bad[name] = wrong
                self.rejects(bad)

    def test_missing_reordered_duplicate_and_unclaimed_cases_never_pass(self):
        changes = [
            list(reversed(report()["case_results"])),
            report()["case_results"][:-1],
            report()["case_results"][:-1] + [report()["case_results"][0]],
            [{"name": name, "status": "skipped"} for name in CASES],
        ]
        for rows in changes:
            bad = report()
            bad["case_results"] = rows
            self.rejects(bad)

    def test_strict_counts_modes_duration_code_stage_and_extra_fields(self):
        for name, wrong in (
            ("tests", True),
            ("errors", False),
            ("passed", "20"),
            ("schema_version", True),
            ("child_commands", 6.0),
            ("mode", "offline"),
            ("stage", "planned"),
            ("code", "private raw exception"),
            ("duration_seconds", 0),
            ("duration_seconds", 120.01),
            ("retained_index_sha256", "A" * 64),
            ("retained_index_sha256", None),
        ):
            bad = report()
            bad[name] = wrong
            self.rejects(bad)
        bad = report()
        bad["unexpected"] = "sentinel"
        self.rejects(bad)
        bad = report()
        del bad["cleanup_complete"]
        self.rejects(bad)
        with self.assertRaises(GATE.GateError):
            GATE.validated_report(
                wire(report()).replace(
                    b'"schema_version":1', b'"schema_version":1,"schema_version":1'
                )
            )

    def test_closed_roles_reject_ambient_credentials_proxy_and_extra_interpreters(self):
        base = {
            "PATH": "/usr/bin:/bin",
            "P3_FIXED_POLICY_DIRECTORY": "/private/tmp/fixed_policy_dir",
            "P3_FIXED_POLICY_INPUTS": "/private/tmp/fixed_policy_inputs",
        }
        GATE.validate_child_environment(base, "producer")
        for name in (
            "OPENAI_API_KEY",
            "AWS_PROFILE",
            "HTTP_PROXY",
            "PYTHONPATH",
            "PGPASSWORD",
            "NODE_OPTIONS",
            "P3_FIXED_POLICY_TOKENS",
        ):
            with self.subTest(name=name), self.assertRaises(GATE.GateError):
                GATE.validate_child_environment(base | {name: "synthetic_forbidden"}, "producer")
        tokens = [chr(65 + n) * 43 for n in range(6)]
        GATE.validate_child_environment(
            base | {"P3_FIXED_POLICY_TOKENS": json.dumps(tokens)}, "serve"
        )
        for wrong in (tokens[:-1], [tokens[0]] * 6, tokens[:-1] + [True], tokens[:-1] + ["x" * 44]):
            with self.assertRaises(GATE.GateError):
                GATE.validate_child_environment(
                    base | {"P3_FIXED_POLICY_TOKENS": json.dumps(wrong)}, "http"
                )
        for key in ("P3_FIXED_POLICY_DIRECTORY", "P3_FIXED_POLICY_INPUTS"):
            with self.assertRaises(GATE.GateError):
                GATE.validate_child_environment(base | {key: "/private/tmp/../escape"}, "codec")

    def test_report_targets_are_new_owned_validation_paths(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as folder:
            root = Path(folder).resolve()
            target = root / ".local/validation/p3-fixed-policy/new-report.json"
            target.parent.mkdir(parents=True, mode=0o700)
            self.assertEqual(GATE.target_path(root, target), target)
            for bad in (
                root / "escape.json",
                target.parent / "../escape.json",
                target.with_name("UPPER.json"),
            ):
                with self.assertRaises(GATE.GateError):
                    GATE.target_path(root, bad)
            target.write_text("{}")
            with self.assertRaises(GATE.GateError):
                GATE.target_path(root, target)

    def test_failed_reports_remain_bounded_safe_and_non_passing(self):
        value = report()
        value.update(
            status="failed",
            passed=8,
            failures=1,
            child_commands=4,
            cleanup_complete=False,
            code="component_failed",
            stage="python-http",
            retained_index_sha256=None,
            case_results=value["case_results"][:8],
        )
        self.assertEqual(GATE.validated_report(wire(value)), value)
        for name, wrong in (
            ("code", "SYNTHETIC_SECRET_VALUE"),
            ("child_commands", 33),
            ("child_commands", True),
            ("errors", False),
            ("stage", "raw_exception_path"),
            ("retained_index_sha256", "secret"),
            ("passed", 9),
        ):
            bad = copy.deepcopy(value)
            bad[name] = wrong
            self.rejects(bad)

    def test_plan_and_invalid_cli_do_not_echo_untrusted_arguments(self):
        command = [sys.executable, "-I", str(ROOT / "local-setup/scripts/p3_fixed_policy_check.py")]
        environment = {"PATH": os.defpath, "LANG": "C.UTF-8"}
        planned = subprocess.run(
            command + ["--plan"],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            timeout=5,
            check=False,
        )
        self.assertEqual(planned.returncode, 0)
        self.assertEqual(planned.stderr, b"")
        value = json.loads(planned.stdout)
        self.assertEqual((value["status"], value["tests"], value["children"]), ("planned", 20, 6))
        self.assertEqual(value["cases"], list(CASES))
        sentinel = "SYNTHETIC_CREDENTIAL_DO_NOT_ECHO"
        rejected = subprocess.run(
            command + ["--unknown", sentinel],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            timeout=5,
            check=False,
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertNotIn(sentinel.encode(), rejected.stdout + rejected.stderr)
        self.assertEqual(rejected.stdout, b"")
        self.assertEqual(
            json.loads(rejected.stderr),
            {"schema_version": 1, "status": "failed", "code": "invalid_input"},
        )

    def test_real_legacy_corpus_uses_declared_setup_bound(self):
        original = (ROOT / "contracts/delegation/v1.json").read_bytes()
        self.assertGreater(len(original), 32768)
        self.assertLessEqual(len(original), 65536)
        with tempfile.TemporaryDirectory(
            prefix="phase40-legacy-corpus-", dir="/private/tmp"
        ) as folder:
            target = Path(folder) / "v1.json"
            GATE.write_private(target, original)
            self.assertEqual(GATE.read_setup_fixture(target), json.loads(original))

    def test_large_legacy_allowance_is_not_shared_by_other_setup_proofs(self):
        original = (ROOT / "contracts/delegation/v1.json").read_bytes()
        with tempfile.TemporaryDirectory(
            prefix="phase40-legacy-name-", dir="/private/tmp"
        ) as folder:
            target = Path(folder) / "fixed-policy-contract-proof.json"
            GATE.write_private(target, original)
            with self.assertRaises(GATE.GateError):
                GATE.read_setup_fixture(target)

    def test_legacy_setup_rejects_overflow_and_duplicate_json_keys(self):
        for original in (b'{"value":"' + b"a" * 65536 + b'"}', b'{"value":1,"value":2}'):
            with tempfile.TemporaryDirectory(
                prefix="phase40-legacy-negative-", dir="/private/tmp"
            ) as folder:
                target = Path(folder) / "v1.json"
                GATE.write_private(target, original)
                with self.assertRaises(GATE.GateError):
                    GATE.read_setup_fixture(target)

    def test_stop_pid_is_complete_before_visibility_and_two_link_phase_is_owned(self):
        work = Path(tempfile.mkdtemp(prefix="phase40-stop-publication-", dir="/private/tmp"))
        target = work / "fixed-policy-server.stop"
        pending = target.with_name(target.name + ".publishing")
        expected = f"{os.getpid()}\n".encode()
        linked, release = threading.Event(), threading.Event()
        errors = []
        original_link = os.link

        def controlled_link(source, destination, *, follow_symlinks=True):
            self.assertEqual((source, destination), (pending, target))
            self.assertFalse(follow_symlinks)
            self.assertFalse(target.exists())
            self.assertEqual(pending.read_bytes(), expected)
            self.assertEqual(stat.S_IMODE(pending.stat().st_mode), 0o600)
            original_link(source, destination, follow_symlinks=follow_symlinks)
            linked.set()
            if not release.wait(timeout=3):
                raise TimeoutError("Controlled publication was not released")

        def publisher():
            try:
                GATE.publish_stop(target, os.getpid())
            except Exception as error:  # noqa: BLE001 - capture the controlled publisher thread outcome for its joining owner.
                errors.append(error)

        owner = threading.Thread(target=publisher)
        try:
            with patch.object(GATE.os, "link", controlled_link):
                owner.start()
                self.assertTrue(linked.wait(timeout=3))
                self.assertEqual(target.read_bytes(), expected)
                self.assertEqual(target.stat().st_nlink, 2)
                self.assertEqual(
                    (target.stat().st_dev, target.stat().st_ino),
                    (pending.stat().st_dev, pending.stat().st_ino),
                )
                self.assertEqual(target.stat().st_uid, os.getuid())
                with self.assertRaises(GATE.GateError):
                    GATE.common.read_private(target, 32)
                release.set()
                owner.join(timeout=3)
            self.assertFalse(owner.is_alive())
            self.assertFalse(errors)
            self.assertFalse(pending.exists())
            self.assertEqual(target.stat().st_nlink, 1)
            self.assertEqual(GATE.common.read_private(target, 32), expected)
        finally:
            release.set()
            if owner.ident is not None:
                owner.join(timeout=3)
            if not owner.is_alive():
                shutil.rmtree(work)
            self.assertFalse(owner.is_alive(), "Private work retained for unresolved publisher")

    def test_stop_pid_publication_never_overwrites_an_original_stop(self):
        with tempfile.TemporaryDirectory(
            prefix="phase40-stop-replay-", dir="/private/tmp"
        ) as folder:
            target = Path(folder) / "fixed-policy-server.stop"
            with os.fdopen(
                os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
            ) as stream:
                stream.write(b"original-stop\n")
            with self.assertRaises((GATE.GateError, OSError)):
                GATE.publish_stop(target, os.getpid())
            self.assertEqual(target.read_bytes(), b"original-stop\n")
            self.assertFalse(target.with_name(target.name + ".publishing").exists())


class FixedPolicyFixturePublication(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "fixed_policy_marker_regression",
            ROOT / "projects/delegation-reliability/tests/fixed_policy_consumer.py",
        )
        assert spec is not None and spec.loader is not None
        cls.consumer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.consumer)

    def fixture(self, folder):
        target = Path(folder) / "fixed_policy_cancel_held.reached"
        pending = target.with_name(target.name + f".{os.getpid()}.pending")
        GATE.write_private(pending, f"{os.getpid()}\n".encode())
        os.link(pending, target, follow_symlinks=False)
        return target, pending

    def test_complete_same_inode_publication_waits_then_reads_original_pid(self):
        with tempfile.TemporaryDirectory(
            prefix="phase40-marker-pending-", dir="/private/tmp"
        ) as folder:
            target, pending = self.fixture(folder)
            self.assertEqual(target.stat().st_nlink, 2)
            self.assertIsNone(self.consumer.read_marker_pid(target, pid=os.getpid()))
            pending.unlink()
            self.assertEqual(self.consumer.read_marker_pid(target, pid=os.getpid()), os.getpid())
            with self.assertRaises(ValueError):
                self.consumer.read_marker_pid(target, pid=os.getpid() + 1)

    def test_legitimate_unlink_between_observations_requires_retry_without_failure(self):
        with tempfile.TemporaryDirectory(
            prefix="phase40-marker-transition-", dir="/private/tmp"
        ) as folder:
            target, pending = self.fixture(folder)
            original_lstat = Path.lstat
            observed = []

            def unlink_during_pending_probe(path):
                if path == pending:
                    observed.append(True)
                    pending.unlink()
                return original_lstat(path)

            with patch.object(Path, "lstat", unlink_during_pending_probe):
                self.assertIsNone(self.consumer.read_marker_pid(target, pid=os.getpid()))
            self.assertEqual(observed, [True])
            self.assertEqual(target.stat().st_nlink, 1)
            self.assertEqual(self.consumer.read_marker_pid(target, pid=os.getpid()), os.getpid())

    def test_foreign_second_link_symlink_and_replaced_inode_cannot_publish(self):
        with tempfile.TemporaryDirectory(
            prefix="phase40-marker-foreign-", dir="/private/tmp"
        ) as folder:
            target, pending = self.fixture(folder)
            pending.rename(Path(folder) / "foreign-link")
            with self.assertRaises(ValueError):
                self.consumer.read_marker_pid(target, pid=os.getpid())
            target.unlink()
            target.symlink_to(Path(folder) / "foreign-link")
            with self.assertRaises(ValueError):
                self.consumer.read_marker_pid(target, pid=os.getpid())
        with tempfile.TemporaryDirectory(
            prefix="phase40-marker-replaced-", dir="/private/tmp"
        ) as folder:
            target, pending = self.fixture(folder)
            original_lstat = Path.lstat

            def replace_before_settlement(path):
                if path == pending:
                    pending.unlink()
                    target.unlink()
                    GATE.write_private(target, f"{os.getpid()}\n".encode())
                return original_lstat(path)

            # Keep the original inode alive so the replacement assertion is independent of inode reuse.
            with (
                target.open("rb"),
                patch.object(Path, "lstat", replace_before_settlement),
                self.assertRaises(ValueError),
            ):
                self.consumer.read_marker_pid(target, pid=os.getpid())

    def test_failure_expectation_context_is_closed_and_body_free(self):
        original = {
            "schema_version": 1,
            "status": "failed",
            "mode": "http",
            "stage": "negative_capacity_primary",
            "code": "fixture_failed",
            "cleanup_complete": True,
            "expectation": {
                "name": "capacity_primary",
                "expected_code": "capacity",
                "observed_code": "identity_conflict",
            },
        }
        GATE.validate_auxiliary(wire(original), "fixed-policy-python-failure.json")
        null = copy.deepcopy(original)
        null["expectation"] = None
        GATE.validate_auxiliary(wire(null), "fixed-policy-python-failure.json")
        for key, value in (
            ("name", "private prompt sentinel"),
            ("expected_code", "unauthorized"),
            ("observed_code", "Bearer private secret sentinel"),
        ):
            wrong = copy.deepcopy(original)
            wrong["expectation"][key] = value
            with self.assertRaises(GATE.GateError):
                GATE.validate_auxiliary(wire(wrong), "fixed-policy-python-failure.json")
        wrong = copy.deepcopy(original)
        wrong["expectation"]["body"] = "private prompt sentinel"
        with self.assertRaises(GATE.GateError):
            GATE.validate_auxiliary(wire(wrong), "fixed-policy-python-failure.json")


class ExistingClientMetricsProof(unittest.TestCase):
    @staticmethod
    def rows():
        # Literal inventory is independent of the host reducer and makes no requests.
        from delegation_reliability.http_client import SpecialistClient, SpecialistEndpoint

        zero = dict(SpecialistClient(SpecialistEndpoint(1), "Bearer " + "A" * 43).metrics())
        expected_keys = {
            "started",
            "received",
            "validated",
            "failed",
            "cancelled",
            "capacity_rejected",
            "cleanup_failed",
            "telemetry_failed",
            "validation_failed",
            "active",
        }
        if set(zero) != expected_keys or any(
            type(value) is not int or value != 0 for value in zero.values()
        ):
            raise AssertionError("Public client metrics shape changed")
        inventory = (
            ("primary", 25, 8),
            ("secondary", 2, 1),
            ("noInvoke", 1, 0),
            ("noResult", 1, 0),
            ("noCancel", 1, 0),
            ("noEvidence", 1, 0),
            ("timeout", 1, 0),
            ("badToken", 1, 0),
            ("document", 1, 1),
        )
        return [
            {
                "name": name,
                "values": {
                    **zero,
                    "started": started,
                    "received": valid,
                    "validated": valid,
                    "failed": started - valid,
                },
            }
            for name, started, valid in inventory
        ]

    def test_existing_public_shape_and_closed_per_client_counts(self):
        rows = self.rows()
        GATE.validate_client_metrics(rows)
        self.assertEqual(
            [
                sum(row["values"][key] for row in rows)
                for key in ("started", "received", "validated", "failed")
            ],
            [34, 10, 10, 24],
        )

    def test_missing_extra_reordered_and_wrong_owner_metrics_fail(self):
        original = self.rows()
        changes = [original[:-1], list(reversed(original)), original + [copy.deepcopy(original[0])]]
        wrong = copy.deepcopy(original)
        wrong[0]["name"] = "foreign"
        changes.append(wrong)
        for rows in changes:
            with self.assertRaises(GATE.GateError):
                GATE.validate_client_metrics(rows)

    def test_each_numeric_value_and_key_is_bound_with_strict_json_types(self):
        original = self.rows()
        for index, row in enumerate(original):
            for key, value in row["values"].items():
                for replacement in (value + 1, bool(value), str(value)):
                    wrong = copy.deepcopy(original)
                    wrong[index]["values"][key] = replacement
                    with self.assertRaises(GATE.GateError):
                        GATE.validate_client_metrics(wrong)
            wrong = copy.deepcopy(original)
            del wrong[index]["values"]["received"]
            with self.assertRaises(GATE.GateError):
                GATE.validate_client_metrics(wrong)


class FixedPolicyProofLiteralNegatives(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((ROOT / "contracts/delegation/fixed-policy-v2.json").read_bytes())
        self.enrollment, _ = GATE.make_enrollment(ROOT)
        self.row = {
            "name": "eligible",
            "request_utf8": self.fixture["request_canonical"],
            "result_utf8": self.fixture["result_canonical"],
        }

    def assess(self, result=None, request=None, records=None):
        row = (
            self.row
            | ({"result_utf8": wire(result).decode()} if result is not None else {})
            | ({"request_utf8": wire(request).decode()} if request is not None else {})
        )
        return GATE.policy_wire(row, self.enrollment["records"] if records is None else records)[2]

    def test_literal_grounded_positive_and_independent_source_policy_versions(self):
        self.assertNotEqual(self.fixture["request"]["evidence"][0]["version"], "notice_v1")
        self.assertEqual(self.assess(), "candidate")
        self.assertEqual(json.loads(self.fixture["policy_body_utf8"])["minimum_notice_days"], 7)
        self.assertEqual(
            json.loads(self.fixture["facts_body_utf8"])["observations"][0]["days_before_arrival"],
            10,
        )

    def test_schema_valid_wrong_decision_rule_threshold_and_fact_are_factual_failures(self):
        for kind in ("decision", "rule", "threshold", "fact", "omitted"):
            bad = copy.deepcopy(self.fixture["result"])
            if kind == "decision":
                bad["eligible"] = False
            elif kind == "rule":
                bad["rule_refs"][0]["rule_id"] = "invented_override"
            elif kind == "threshold":
                bad["rule_refs"][0]["minimum_notice_days"] = 1
            elif kind == "fact":
                bad["fact_refs"][0]["days_before_arrival"] = 11
            else:
                bad["fact_refs"] = []
                bad["eligible"] = None
                bad["uncertainty"] = "missing"
            self.assertEqual(self.assess(result=bad), "unsupported_facts")

    def test_identity_fingerprint_source_scope_and_wrong_version_never_match(self):
        for name, value in (
            ("account_id", "another_account"),
            ("attempt_id", "another_attempt"),
            ("fingerprint", "0" * 64),
            ("source_id", "another_source"),
            ("version", "other_version"),
            ("sha256", "0" * 64),
        ):
            bad = copy.deepcopy(self.fixture["result"])
            if name == "account_id":
                bad["scope"][name] = value
            elif name == "attempt_id":
                bad[name] = value
            elif name == "fingerprint":
                bad["input_fingerprint"] = value
            else:
                bad["fact_refs"][0][name] = value
            with self.subTest(name=name), self.assertRaises(GATE.GateError):
                self.assess(result=bad)

    def test_actual_source_bytes_and_unique_matching_records_are_required(self):
        original = self.enrollment["records"]
        bad = copy.deepcopy(original)
        bad[0]["body_utf8"] += " "
        with self.assertRaises(GATE.GateError):
            self.assess(records=bad)
        with self.assertRaises(GATE.GateError):
            self.assess(records=original[1:])
        with self.assertRaises(GATE.GateError):
            self.assess(records=original + [copy.deepcopy(original[0])])

    def test_boolean_aliases_duplicate_facts_and_malformed_provenance_fail_shape(self):
        for kind in ("threshold", "fact", "duplicate", "provenance"):
            bad = copy.deepcopy(self.fixture["result"])
            if kind == "threshold":
                bad["rule_refs"][0]["minimum_notice_days"] = True
            elif kind == "fact":
                bad["fact_refs"][0]["days_before_arrival"] = True
            elif kind == "duplicate":
                bad["fact_refs"].append(copy.deepcopy(bad["fact_refs"][0]))
            else:
                bad["producer"]["model_id"] = "invented_model"
            with self.subTest(kind=kind), self.assertRaises(GATE.GateError):
                self.assess(result=bad)

    def test_late_timestamp_does_not_mask_schema_valid_false_facts(self):
        request = copy.deepcopy(self.fixture["request"])
        request["deadline_at_ms"] = 1
        request["input_fingerprint"] = hashlib.sha256(
            wire({k: v for k, v in request.items() if k not in {"attempt", "input_fingerprint"}})
        ).hexdigest()
        result = copy.deepcopy(self.fixture["result"])
        result["input_fingerprint"] = request["input_fingerprint"]
        result["eligible"] = False
        self.assertEqual(self.assess(request=request, result=result), "unsupported_facts")
