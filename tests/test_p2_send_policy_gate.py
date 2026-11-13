"""Offline assertion/environment/report ownership negatives for P2 send-policy qualification."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "p2_send_policy_gate_tested", ROOT / "local-setup/scripts/p2_send_policy_check.py"
)
assert SPEC is not None and SPEC.loader is not None
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def passing() -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": "passed",
        "mode": GATE.MODE,
        "tests": len(GATE.CASE_NAMES),
        "passed": len(GATE.CASE_NAMES),
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "duration_seconds": 2.5,
        "cleanup_complete": True,
        "case_results": [{"name": n, "status": "passed", "code": "ok"} for n in GATE.CASE_NAMES],
        "node_version": "24.22.2",
        "blocking_graphs": {"upgrade": 1, "retry": 2, "callback": 2},
        "child_terminations": 2,
        "schema_version_observed": 5,
        "authority": "P2_explicit_same_key_recovery_not_physical_exactly_once",
    }


class SendPolicyGateTests(unittest.TestCase):
    def invalid(self, value: dict[str, object]) -> None:
        with self.assertRaises(GATE.core.GateError):
            GATE.validated_report(json.dumps(value).encode())

    def test_exact_named_progress_report_passes(self) -> None:
        self.assertEqual(GATE.validated_report(json.dumps(passing()).encode()), passing())

    def test_missing_or_changed_named_assertion_fails(self) -> None:
        for value in ([], [{"name": "fake_pass", "status": "passed", "code": "ok"}]):
            report = passing()
            report["case_results"] = value
            self.invalid(report)

    def test_skip_failure_error_is_not_a_pass(self) -> None:
        for key in ("failures", "errors", "skipped"):
            report = passing()
            report[key] = 1
            self.invalid(report)

    def test_booleans_are_not_case_kill_schema_or_graph_counts(self) -> None:
        for key in (
            "schema_version",
            "tests",
            "passed",
            "child_terminations",
            "schema_version_observed",
        ):
            report = passing()
            report[key] = True
            self.invalid(report)
        report = passing()
        report["blocking_graphs"] = {"upgrade": True, "callback": 2}
        self.invalid(report)

    def test_observed_lock_graph_not_elapsed_delay(self) -> None:
        report = passing()
        report["blocking_graphs"] = {"upgrade": 0, "callback": 2}
        self.invalid(report)

    def test_cleanup_timeout_missing_runtime_cannot_pass(self) -> None:
        for key, value in (
            ("cleanup_complete", False),
            ("duration_seconds", 181),
            ("duration_seconds", float("nan")),
            ("duration_seconds", 0),
            ("node_version", "22.0.0"),
        ):
            report = passing()
            report[key] = value
            self.invalid(report)

    def test_unknown_extra_fields_and_wrong_authority_fail(self) -> None:
        report = passing()
        report["secret"] = "PRIVATE"
        self.invalid(report)
        report = passing()
        report["authority"] = "exactly_once_sms"
        self.invalid(report)

    def test_duplicate_json_evidence_is_rejected(self) -> None:
        with self.assertRaises(GATE.core.GateError):
            GATE.decode(b'{"status":"passed","status":"failed"}')

    def test_owner_and_runtime_closed_environments_are_separate(self) -> None:
        values = {
            "POSTGRES_PORT": "15432",
            "POSTGRES_PASSWORD": "runtime_sentinel",
            "POSTGRES_MIGRATION_PASSWORD": "owner_sentinel",
        }
        context = {
            "P2_SEND_POLICY_SCHEMA": "p2_send_policy_" + "a" * 32,
            "P2_SEND_POLICY_DIRECTORY": "/private/tmp",
        }
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "PRIVATE",
                "PGPASSWORD": "PRIVATE",
                "NODE_OPTIONS": "PRIVATE",
                "HTTP_PROXY": "PRIVATE",
            },
        ):
            owner = GATE.child_environment(values, context, owner=True)
            runtime = GATE.child_environment(values, context, owner=False)
        self.assertNotIn("P2_SEND_POLICY_RUNTIME_PASSWORD", owner)
        self.assertNotIn("P2_SEND_POLICY_OWNER_PASSWORD", runtime)
        self.assertNotIn("P2_SEND_POLICY_CARRIER_TOKEN", owner)
        self.assertEqual(runtime["P2_SEND_POLICY_RUNTIME_PASSWORD"], "runtime_sentinel")
        for env in (owner, runtime):
            for key in ("OPENAI_API_KEY", "PGPASSWORD", "NODE_OPTIONS", "HTTP_PROXY"):
                self.assertNotIn(key, env)
        with self.assertRaises(GATE.core.GateError):
            GATE.child_environment(
                values, {**context, "P2_SEND_POLICY_OWNER_PASSWORD": "PRIVATE"}, owner=False
            )

    def test_child_stage_requires_exact_mode_keys_and_true_boolean(self) -> None:
        value = {
            "status": "passed",
            "mode": "seed",
            "cleanup_complete": True,
            "node_version": "24.22.2",
        }
        self.assertEqual(GATE.validated_stage(json.dumps(value).encode(), "seed"), value)
        for changed in ({"mode": "other"}, {"cleanup_complete": 1}, {"extra": "sentinel"}):
            with self.assertRaises(GATE.core.GateError):
                GATE.validated_stage(json.dumps({**value, **changed}).encode(), "seed")

    def test_cleanup_preserves_primary_and_attempts_remaining_owners(self) -> None:
        visited: list[str] = []
        state = {"cleanup_complete": False}

        async def fail() -> None:
            visited.append("socket")
            raise OSError("PRIVATE_SECONDARY")

        async def backup() -> None:
            visited.append("backup")

        async def schema() -> None:
            visited.append("schema")

        async def run() -> None:
            try:
                raise GATE.core.GateError("original_stage_failure")
            finally:
                await GATE.cleanup_actions((fail, backup, schema), state, sys.exception())

        with self.assertRaises(GATE.core.GateError) as caught:
            asyncio.run(run())
        self.assertEqual(caught.exception.code, "original_stage_failure")
        self.assertFalse(state["cleanup_complete"])
        self.assertEqual(visited, ["socket", "backup", "schema"])

    def test_cleanup_failure_without_primary_cannot_pass(self) -> None:
        async def fail() -> None:
            raise OSError("PRIVATE")

        with self.assertRaises(GATE.core.GateError) as caught:
            asyncio.run(GATE.cleanup_actions((fail,), {"cleanup_complete": False}, None))
        self.assertEqual(caught.exception.code, "cleanup_incomplete")

    def test_cleanup_budget_is_reserved_inside_final_deadline(self) -> None:
        work, final = GATE.deadlines(100.0)
        self.assertEqual(work, 265.0)
        self.assertEqual(final, 280.0)
        self.assertEqual(final - work, GATE.CLEANUP_SECONDS)

    def test_report_retention_never_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "proof.json"
            GATE.retain(path, passing())
            with self.assertRaises(GATE.core.GateError):
                GATE.retain(path, passing())

    def test_failed_report_write_is_nonpassing(self) -> None:
        async def run(*_args: object) -> dict[str, object]:
            return deepcopy(passing())

        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve()
            root.chmod(0o700)
            path = root / ".local/validation/p2-send-policy/new.json"
            with (
                patch.object(GATE, "run", run),
                patch.object(
                    GATE, "retain", side_effect=GATE.core.GateError("report_retention_failed")
                ),
                redirect_stdout(io.StringIO()) as out,
            ):
                self.assertEqual(GATE.main(["--report", str(path)], root=root), 1)
            self.assertEqual(json.loads(out.getvalue())["code"], "report_retention_failed")

    def test_unsafe_target_is_rejected_before_run(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve()
            root.chmod(0o700)
            with self.assertRaises(GATE.core.GateError):
                GATE.target_path(root, Path("../unsafe.json"))

    def test_contract_inventory_is_closed(self) -> None:
        self.assertEqual(len(GATE.CASE_NAMES), 30)
        self.assertEqual(len(set(GATE.CASE_NAMES)), 30)
        self.assertEqual(
            set(GATE.MODES),
            {
                "install",
                "seed",
                "upgrade",
                "repeat",
                "exercise",
                "race",
                "callback-race",
                "crash-observed",
                "crash-reserved",
                "reopen",
                "verify",
            },
        )
        self.assertEqual(set(GATE.OWNER_MODES), {"install", "upgrade", "repeat", "verify"})

    def test_case_identity_order_and_result_code_cannot_be_substituted(self) -> None:
        for kind in ("missing", "duplicate", "reordered", "unknown", "failed", "extra"):
            value = passing()
            rows = deepcopy(value["case_results"])
            assert isinstance(rows, list)
            if kind == "missing":
                rows.pop()
            elif kind == "duplicate":
                rows[0] = rows[1]
            elif kind == "reordered":
                rows.reverse()
            elif kind == "unknown":
                rows[0]["name"] = "fabricated_case"
            elif kind == "failed":
                rows[0]["code"] = "not_actually_observed"
            else:
                rows[0]["private"] = "PRIVATE_CASE_SENTINEL"
            value["case_results"] = rows
            with self.subTest(kind=kind):
                self.invalid(value)

    def test_report_requires_every_field_and_exact_authority(self) -> None:
        for key in passing():
            value = passing()
            del value[key]
            with self.subTest(key=key):
                self.invalid(value)
        for key, value in (
            ("tests", 0),
            ("passed", 29),
            ("child_terminations", 1),
            ("schema_version_observed", 4),
            ("cleanup_complete", 1),
            ("duration_seconds", True),
            ("duration_seconds", float("inf")),
            ("node_version", "26.12.0"),
        ):
            changed = passing()
            changed[key] = value
            with self.subTest(key=key, value=value):
                self.invalid(changed)

    def test_every_lock_group_is_required_with_strict_integer_counts(self) -> None:
        for key in ("upgrade", "retry", "callback"):
            for changed in (True, 0, -1):
                value = passing()
                graphs = {"upgrade": 1, "retry": 2, "callback": 2}
                graphs[key] = changed
                value["blocking_graphs"] = graphs
                with self.subTest(key=key, value=changed):
                    self.invalid(value)
        for graphs in (
            {"upgrade": 1, "retry": 2},
            {"upgrade": 1, "retry": 2, "callback": 2, "invented": 1},
            [],
        ):
            value = passing()
            value["blocking_graphs"] = graphs
            self.invalid(value)

    def test_decode_rejects_nonobject_wrong_type_truncated_and_oversized_evidence(self) -> None:
        for raw in (b"", b"[]", b"null", b"{", b"\xff", b"x" * 32769, "{}", None):
            with self.subTest(kind=type(raw).__name__), self.assertRaises(GATE.core.GateError):
                GATE.decode(raw)

    def test_stage_cannot_expand_the_closed_mode_protocol(self) -> None:
        for mode in GATE.MODES:
            value = {
                "status": "passed",
                "mode": mode,
                "cleanup_complete": True,
                "node_version": "26.13.0",
            }
            self.assertEqual(GATE.validated_stage(json.dumps(value).encode(), mode), value)
        for mode in ("invented", "", "install; ignored"):
            value = {
                "status": "passed",
                "mode": mode,
                "cleanup_complete": True,
                "node_version": "24.22.2",
            }
            with self.assertRaises(GATE.core.GateError):
                GATE.validated_stage(json.dumps(value).encode(), mode)

    def test_child_environment_invalid_types_missing_values_and_extra_context_fail(self) -> None:
        values = {
            "POSTGRES_PORT": "15432",
            "POSTGRES_PASSWORD": "runtime",
            "POSTGRES_MIGRATION_PASSWORD": "owner",
        }
        context = {
            "P2_SEND_POLICY_SCHEMA": "p2_send_policy_" + "a" * 32,
            "P2_SEND_POLICY_DIRECTORY": "/private/tmp/synthetic",
        }
        for name in context:
            for value in ("", "x\x00y", "x\ny", 1, None):
                changed = {**context, name: value}
                with self.subTest(key=name, value=value), self.assertRaises(GATE.core.GateError):
                    GATE.child_environment(values, changed, owner=False)
        for name in values:
            missing = dict(values)
            del missing[name]
            with self.assertRaises(GATE.core.GateError):
                GATE.child_environment(missing, context, owner=True)
        for owner in (0, 1, "runtime", None):
            with self.assertRaises(GATE.core.GateError):
                GATE.child_environment(values, context, owner=owner)
        with self.assertRaises(GATE.core.GateError):
            GATE.child_environment(
                values, {**context, "P2_SEND_POLICY_OWNER_PASSWORD": "PRIVATE"}, owner=False
            )

    def test_child_environment_is_a_snapshot_and_does_not_forward_provider_selectors(self) -> None:
        values = {
            "POSTGRES_PORT": "15432",
            "POSTGRES_PASSWORD": "runtime",
            "POSTGRES_MIGRATION_PASSWORD": "owner",
            "OPENAI_API_KEY": "PRIVATE_PROVIDER_SENTINEL",
            "DEEPGRAM_API_KEY": "PRIVATE_PROVIDER_SENTINEL",
        }
        context = {
            "P2_SEND_POLICY_SCHEMA": "p2_send_policy_" + "a" * 32,
            "P2_SEND_POLICY_DIRECTORY": "/private/tmp/synthetic",
        }
        with patch.dict(
            os.environ,
            {
                "PGSERVICE": "PRIVATE",
                "PGPASSFILE": "PRIVATE",
                "DATABASE_URL": "PRIVATE",
                "PYTHONPATH": "PRIVATE",
                "HTTPS_PROXY": "PRIVATE",
                "ELEVENLABS_API_KEY": "PRIVATE",
            },
        ):
            environment = GATE.child_environment(values, context, owner=False)
        context["P2_SEND_POLICY_SCHEMA"] = "changed"
        values["POSTGRES_PASSWORD"] = "changed"
        self.assertEqual(environment["P2_SEND_POLICY_RUNTIME_PASSWORD"], "runtime")
        self.assertTrue(environment["P2_SEND_POLICY_SCHEMA"].startswith("p2_send_policy_"))
        self.assertFalse(any("PRIVATE" in value for value in environment.values()))
        self.assertNotIn("P2_SEND_POLICY_OWNER_PASSWORD", environment)

    def test_report_is_private_and_rejects_symlink_write(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve()
            root.chmod(0o700)
            target = GATE.target_path(root, Path(".local/validation/p2-send-policy/proof.json"))
            GATE.retain(target, passing())
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(target.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(json.loads(target.read_bytes()), passing())
            alias = target.with_name("alias.json")
            alias.symlink_to(target)
            with self.assertRaises(GATE.core.GateError):
                GATE.retain(alias, {"private": "PRIVATE"})
            self.assertEqual(json.loads(target.read_bytes()), passing())

    def test_report_size_finiteness_and_cycle_rejection_happen_before_file_creation(self) -> None:
        cyclic: dict[str, object] = {}
        cyclic["self"] = cyclic
        for value in (
            {"payload": "x" * 40000},
            {"payload": "😀" * 9000},
            {"number": float("nan")},
            {"number": float("inf")},
            cyclic,
        ):
            with tempfile.TemporaryDirectory() as name:
                target = Path(name) / "proof.json"
                with self.assertRaises(GATE.core.GateError):
                    GATE.retain(target, value)
                self.assertFalse(target.exists())
        with tempfile.TemporaryDirectory() as name:
            target = Path(name) / "bounded-synthetic-snapshot.json"
            GATE.retain(target, {"payload": "x" * 40000}, maximum=1048576)
            self.assertGreater(target.stat().st_size, 32768)
            for maximum in (True, 32769, 0, 1048577):
                with self.assertRaises(GATE.core.GateError):
                    GATE.retain(Path(name) / "bad.json", passing(), maximum=maximum)

    def test_report_ancestors_and_existing_artifacts_cannot_redirect_runs(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve()
            root.chmod(0o700)
            (root / ".local/validation").mkdir(parents=True)
            actual = root / "actual"
            actual.mkdir()
            (root / ".local/validation/p2-send-policy").symlink_to(actual, target_is_directory=True)
            with self.assertRaises(GATE.core.GateError):
                GATE.target_path(root, Path(".local/validation/p2-send-policy/proof.json"))

    def test_capture_bounds_cover_both_streams_all_stages_and_global_total(self) -> None:
        total = 0
        for stage in range(1, 41):
            total = GATE.enforce_capture(stage, 32768, 32768, total)
        self.assertEqual(total, 2621440)
        for args in (
            (0, 0, 0, 0),
            (41, 0, 0, 0),
            (1, 65536, 1, 0),
            (1, 0, 0, 2621441),
            (1, -1, 0, 0),
            (1, 0, -1, 0),
            (1, 0, 0, -1),
            (True, 0, 0, 0),
            (1, True, 0, 0),
            (1, 0, False, 0),
            (1, 0, 0, True),
            (1.0, 0, 0, 0),
        ):
            with self.subTest(args=args), self.assertRaises(GATE.core.GateError):
                GATE.enforce_capture(*args)

    def test_cleanup_cancellation_keeps_all_owners_and_preserves_original_failure(self) -> None:
        visited: list[str] = []
        state = {"cleanup_complete": True}

        async def cancel() -> None:
            visited.append("http")
            raise asyncio.CancelledError()

        async def final() -> None:
            visited.append("schema")

        async def run() -> None:
            try:
                raise GATE.core.GateError("original_stage_failure")
            finally:
                await GATE.cleanup_actions((cancel, final), state, sys.exception())

        with self.assertRaises(GATE.core.GateError) as caught:
            asyncio.run(run())
        self.assertEqual(caught.exception.code, "original_stage_failure")
        self.assertEqual(visited, ["http", "schema"])
        self.assertFalse(state["cleanup_complete"])

    def test_cleanup_cancellation_propagates_after_remaining_cleanup(self) -> None:
        visited: list[str] = []
        state = {"cleanup_complete": True}

        async def cancel() -> None:
            visited.append("http")
            raise asyncio.CancelledError()

        async def final() -> None:
            visited.append("schema")

        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(GATE.cleanup_actions((cancel, final), state, None))
        self.assertEqual(visited, ["http", "schema"])
        self.assertFalse(state["cleanup_complete"])

    def test_unhandled_private_dependency_error_is_redacted_and_cannot_pass(self) -> None:
        async def fail(*_args: object) -> dict[str, object]:
            raise RuntimeError("PRIVATE_DEPENDENCY_SENTINEL")

        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve()
            root.chmod(0o700)
            with patch.object(GATE, "run", fail), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(
                    GATE.main(
                        ["--report", ".local/validation/p2-send-policy/failure.json"], root=root
                    ),
                    1,
                )
            value = json.loads(output.getvalue())
            self.assertEqual(value["status"], "failed")
            self.assertEqual(value["code"], "gate_failed")
            self.assertNotIn("PRIVATE_DEPENDENCY_SENTINEL", output.getvalue())
            self.assertFalse(value["cleanup_complete"])

    def test_sql_snapshot_digest_is_recomputable_from_sorted_retained_json(self) -> None:
        original = {"z": [{"b": 2, "a": "☃"}, 0], "a": "café"}
        reordered = {"a": "café", "z": [{"a": "☃", "b": 2}, 0]}
        expected_bytes = b'{"a":"caf\\u00e9","z":[{"a":"\\u2603","b":2},0]}'
        expected = hashlib.sha256(expected_bytes).hexdigest()
        retained = json.dumps(original, sort_keys=True, indent=2).encode()
        before = deepcopy(original)
        self.assertEqual(GATE.snapshot_digest(original), expected)
        self.assertEqual(GATE.snapshot_digest(reordered), expected)
        self.assertEqual(GATE.snapshot_digest(json.loads(retained)), expected)
        self.assertEqual(original, before)
        self.assertNotEqual(
            GATE.snapshot_digest({"a": "café", "z": [0, {"a": "☃", "b": 2}]}), expected
        )
        with self.assertRaises(ValueError):
            GATE.snapshot_digest({"invalid": float("nan")})


class RecoveryAccountingTests(unittest.TestCase):
    def sample(self, state: str = "observed") -> tuple[dict[str, object], dict[str, object]]:
        uid = lambda n: str(UUID(int=n))
        self.kills = (uid(25), uid(28))
        self.outbound = uid(500)
        commands, observations = [], []
        receipts: dict[str, object] = {}
        facts: dict[str, object] = {}
        for n in range(1, 129):
            identity = uid(n)
            killed = identity in self.kills
            kind = "retry" if killed else "reconcile"
            receipt = {
                "schemaVersion": 1,
                "receiptId": uid(1000 + n),
                "commandId": identity,
                "kind": kind,
                "outboundId": self.outbound,
                "sourceAttemptId": uid(501),
                "providerOperationKey": uid(502),
                "operationDigest": "f" * 64,
                "decision": "retry_reserved" if killed else "lookup_authorized",
                "code": "retry_reserved" if killed else "lookup",
                "newAttemptId": uid(2000 + n) if killed else None,
                "acceptedAt": "2030-01-01T00:00:00.000Z",
            }
            semantic = {
                "schemaVersion": 1,
                "commandId": identity,
                "kind": kind,
                "outboundId": self.outbound,
                "attemptId": uid(501),
                "scope": {"tenantId": "tenant", "accountId": "account"},
                "caseId": "case",
                "conversationId": "conversation",
                "providerOperationKey": uid(502),
                "operationDigest": "f" * 64,
            }
            receipt_raw = json.dumps(receipt, separators=(",", ":"))
            semantic_raw = json.dumps(semantic, separators=(",", ":"))
            commands.append(
                {
                    "command_id": identity,
                    "kind": kind,
                    "provider_operation_key": uid(502),
                    "outbound_id": self.outbound,
                    "source_attempt_id": uid(501),
                    "new_attempt_id": receipt["newAttemptId"],
                    "receipt_json": receipt_raw,
                    "receipt_digest": hashlib.sha256(receipt_raw.encode()).hexdigest(),
                    "canonical_command": semantic_raw,
                    "command_digest": hashlib.sha256(semantic_raw.encode()).hexdigest(),
                }
            )
            receipts[identity] = receipt
            if not killed and not (n == 1 and state == "missing"):
                fact = {
                    "schemaVersion": 1,
                    "commandId": identity,
                    "providerOperationKey": uid(502),
                    "operationDigest": "f" * 64,
                    "source": "lookup",
                    "state": "unknown",
                    "assessment": "reported",
                    "providerMessageId": None,
                    "observedAt": "2030-01-01T00:00:00.000Z",
                }
                raw = json.dumps(fact, separators=(",", ":"))
                observations.append(
                    {
                        "command_id": identity,
                        "canonical_observation": raw,
                        "observation_digest": hashlib.sha256(raw.encode()).hexdigest(),
                    }
                )
                facts[identity] = fact
        deadline_id = uid(999) if state == "absent" else uid(1)
        deadline = (
            None
            if state == "absent"
            else {"receipt": receipts[deadline_id], "observation": facts.get(deadline_id)}
        )
        bounded = {
            "active": 0,
            "recoveryAcknowledgementUnknown": 1,
            "recoveryRejected": 0,
            "timeoutAndAbandonment": {
                "deadlineMs": 25,
                "deadlinePortEntered": state == "observed",
                "deadlineCode": "AcknowledgementUnknown",
                "abortAfterActualPortEntry": True,
                "retainedUntilRelease": True,
                "settledActive": 0,
                "deadlineCommandId": deadline_id,
                "deadlineCommand": deadline,
                "abandonedCommandId": uid(2),
                "abandonedCommand": {"receipt": receipts[uid(2)], "observation": facts[uid(2)]},
                "replay": {
                    "deadlineReplayed": state != "absent",
                    "abandonedReplayed": True,
                    "providerStartedBefore": 4,
                    "providerStartedAfter": 4,
                    "lookupInvocationsBefore": 3,
                    "lookupInvocationsAfter": 3,
                    "retryInvocationsBefore": 1,
                    "retryInvocationsAfter": 1,
                },
            },
        }
        return {
            "send_recovery_commands": commands,
            "send_recovery_observations": observations,
        }, deepcopy(bounded)

    def check(self, snapshot, bounded):
        return GATE.validate_recovery_accounting(
            snapshot, bounded, killed_command_ids=self.kills, outbound_id=self.outbound
        )

    def test_three_exact_deadline_admission_states_pass(self):
        for state in ("absent", "missing", "observed"):
            with self.subTest(state=state):
                snapshot, bounded = self.sample(state)
                result = self.check(snapshot, bounded)
                self.assertEqual(result["commands"], 128)
                self.assertEqual(result["observations"], 125 if state == "missing" else 126)
                self.assertEqual(len(result["missing_command_ids"]), 3 if state == "missing" else 2)

    def test_unrelated_missing_or_extra_or_duplicate_observation_never_passes(self):
        for defect in ("missing", "unknown", "duplicate", "duplicate_command", "count"):
            snapshot, bounded = self.sample()
            rows = snapshot["send_recovery_observations"]
            if defect == "missing":
                rows.pop(4)
            elif defect == "unknown":
                rows[4]["command_id"] = str(UUID(int=9999))
            elif defect == "duplicate":
                rows.append(deepcopy(rows[0]))
            elif defect == "duplicate_command":
                snapshot["send_recovery_commands"][4] = deepcopy(
                    snapshot["send_recovery_commands"][0]
                )
            else:
                snapshot["send_recovery_commands"].pop()
            with self.subTest(defect=defect), self.assertRaises(GATE.core.GateError):
                self.check(snapshot, bounded)

    def test_public_view_must_match_exact_immutable_owner_rows(self):
        for defect in ("receipt", "observation", "absent", "abandoned", "operation"):
            snapshot, bounded = self.sample()
            meta = bounded["timeoutAndAbandonment"]
            if defect == "receipt":
                meta["deadlineCommand"]["receipt"]["acceptedAt"] = "changed"
            elif defect == "observation":
                meta["deadlineCommand"]["observation"]["state"] = "accepted_by_provider"
            elif defect == "absent":
                meta["deadlineCommand"] = None
                meta["replay"]["deadlineReplayed"] = False
            elif defect == "abandoned":
                meta["abandonedCommand"]["observation"] = None
            else:
                meta["abandonedCommandId"] = meta["deadlineCommandId"]
            with self.subTest(defect=defect), self.assertRaises(GATE.core.GateError):
                self.check(snapshot, bounded)

    def test_killed_id_allowlist_cannot_hide_an_unrelated_missing_fact(self):
        snapshot, bounded = self.sample("missing")
        bounded["timeoutAndAbandonment"]["deadlineCommandId"] = str(UUID(int=4))
        with self.assertRaises(GATE.core.GateError):
            self.check(snapshot, bounded)
        snapshot, bounded = self.sample()
        self.kills = (self.kills[0], str(UUID(int=4)))
        with self.assertRaises(GATE.core.GateError):
            self.check(snapshot, bounded)

    def test_replay_growth_missing_replay_and_boolean_counters_fail(self):
        for field, wrong in (
            ("lookupInvocationsAfter", 4),
            ("providerStartedAfter", 5),
            ("retryInvocationsAfter", 2),
            ("deadlineReplayed", False),
            ("abandonedReplayed", False),
            ("lookupInvocationsBefore", True),
        ):
            snapshot, bounded = self.sample()
            bounded["timeoutAndAbandonment"]["replay"][field] = wrong
            with self.subTest(field=field), self.assertRaises(GATE.core.GateError):
                self.check(snapshot, bounded)

    def test_entered_deadline_cannot_claim_missing_provider_fact(self):
        snapshot, bounded = self.sample("missing")
        bounded["timeoutAndAbandonment"]["deadlinePortEntered"] = True
        with self.assertRaises(GATE.core.GateError):
            self.check(snapshot, bounded)

    def test_raw_digest_scope_and_boolean_schema_cannot_forge_a_fact(self):
        for defect in ("digest", "identity", "schema"):
            snapshot, bounded = self.sample()
            row = snapshot["send_recovery_observations"][4]
            fact = json.loads(row["canonical_observation"])
            if defect == "digest":
                row["observation_digest"] = "0" * 64
            else:
                fact["providerOperationKey" if defect == "identity" else "schemaVersion"] = (
                    str(UUID(int=600)) if defect == "identity" else True
                )
                raw = json.dumps(fact, separators=(",", ":"))
                row["canonical_observation"] = raw
                row["observation_digest"] = hashlib.sha256(raw.encode()).hexdigest()
            with self.subTest(defect=defect), self.assertRaises(GATE.core.GateError):
                self.check(snapshot, bounded)

    def test_case_conversation_scope_are_bound_to_both_original_anchors(self):
        semantic = {
            "scope": {"tenantId": "tenant", "accountId": "account"},
            "caseId": "case",
            "conversationId": "conversation",
            "outboundId": "outbound",
            "providerOperationKey": "operation",
            "attemptId": "attempt",
        }
        GATE.validate_recovery_anchor(semantic, deepcopy(semantic), deepcopy(semantic))
        for field in (
            "caseId",
            "conversationId",
            "scope",
            "outboundId",
            "providerOperationKey",
            "attemptId",
        ):
            wrong = deepcopy(semantic)
            wrong[field] = "different"
            with self.subTest(field=field), self.assertRaises(GATE.core.GateError):
                GATE.validate_recovery_anchor(wrong, deepcopy(semantic), deepcopy(semantic))
        with self.assertRaises(GATE.core.GateError):
            GATE.validate_recovery_anchor(
                semantic, {k: v for k, v in semantic.items() if k != "caseId"}, semantic
            )

    def test_fresh_and_restored_replay_must_invoke_exact_known_ids_with_zero_growth(self):
        for state in ("absent", "missing", "observed"):
            _, bounded = self.sample(state)
            meta = bounded["timeoutAndAbandonment"]
            expected = (
                [meta["deadlineCommandId"]] if meta["deadlineCommand"] is not None else []
            ) + [meta["abandonedCommandId"]]
            for restored in (False, True):
                proof = {
                    "schemaVersion": 1,
                    "restoreOnly": restored,
                    "commandIds": expected,
                    "deadlineNotInvoked": meta["deadlineCommand"] is None,
                    "replay": {
                        k: v
                        for k, v in meta["replay"].items()
                        if k not in ("deadlineReplayed", "abandonedReplayed")
                    },
                }
                GATE.validate_bounded_replay(proof, bounded, restored=restored)
                for field, wrong in (
                    ("schemaVersion", True),
                    ("restoreOnly", not restored),
                    ("commandIds", list(reversed(expected)) + [str(UUID(int=9999))]),
                    ("deadlineNotInvoked", meta["deadlineCommand"] is not None),
                ):
                    invalid = deepcopy(proof)
                    invalid[field] = wrong
                    with (
                        self.subTest(state=state, field=field),
                        self.assertRaises(GATE.core.GateError),
                    ):
                        GATE.validate_bounded_replay(invalid, bounded, restored=restored)
                invalid = deepcopy(proof)
                invalid["replay"]["lookupInvocationsAfter"] += 1
                with self.assertRaises(GATE.core.GateError):
                    GATE.validate_bounded_replay(invalid, bounded, restored=restored)

    def test_restored_or_reopened_missing_identity_drift_fails(self):
        snapshot, bounded = self.sample("missing")
        expected = self.check(snapshot, bounded)
        self.assertEqual(self.check(deepcopy(snapshot), deepcopy(bounded)), expected)
        snapshot["send_recovery_observations"].pop(5)
        with self.assertRaises(GATE.core.GateError):
            self.check(snapshot, bounded)


if __name__ == "__main__":
    unittest.main()
