"""Authored operations gate boundary tests; synthetic offline inputs are not PG/browser evidence."""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import hmac
import importlib.util
import json
import os
import re
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "local-setup/scripts"))
spec = importlib.util.spec_from_file_location(
    "p2_operations_gate_under_test", ROOT / "local-setup/scripts/p2_operations_check.py"
)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class OperationsBoundaryTests(unittest.TestCase):
    def test_plan_declares_separate_groups_and_no_measurement(self):
        v = m.plan()
        self.assertEqual((len(v["storage_cases"]), len(v["browser_groups"])), (16, 3))
        self.assertEqual(len(v["normal_commands"]), 13)
        self.assertFalse(v["measurement_started"])
        self.assertEqual(v["bounds"]["maximum_children"], 24)
        self.assertEqual(v["provider_calls"], 0)
        self.assertEqual(v["sfu_calls"], 0)

    def test_strict_json_rejects_duplicates_primitives_nonfinite_utf8_and_huge_int(self):
        for raw in (
            b'{"a":1,"a":2}',
            b"null",
            b"[]",
            b'{"a":NaN}',
            b"\xff",
            b'{"a":' + b"1" * 10000 + b"}",
        ):
            with self.subTest(size=len(raw)), self.assertRaises(m.GateError):
                m.decode(raw)

    def stage(self, mode="seed"):
        result = (
            copy.deepcopy(m.STAGES[mode])
            if mode != "serve"
            else {
                "casePortClosed": True,
                "getterPending": 0,
                "httpClosed": True,
                "httpHandlers": 0,
                "httpSockets": 0,
                "inboxClosed": True,
                "observerPending": 0,
                "readerActive": 0,
                "readerClosed": True,
                "telemetryClosed": True,
                "exporterDropped": 2,
                "exporterFailures": 1,
            }
        )
        return {
            "schemaVersion": 1,
            "status": "passed",
            "mode": mode,
            "storageVersion": 0 if mode == "cleanup" else 7,
            "nodeVersion": "24.22.2",
            "cleanupComplete": True,
            "result": result,
        }

    def test_each_frozen_stage_positive(self):
        for mode in m.MODES:
            with self.subTest(mode=mode):
                self.assertEqual(
                    m.validated_stage(json.dumps(self.stage(mode)).encode(), mode), self.stage(mode)
                )

    def test_stage_rejects_boolean_versions_unknown_fields_missing_closure_and_wrong_mode(self):
        a = self.stage()
        for changes in (
            {"schemaVersion": True},
            {"cleanupComplete": False},
            {"storageVersion": 6},
            {"mode": "serve"},
            {"rawError": "private"},
        ):
            with self.subTest(changes=changes), self.assertRaises(m.GateError):
                m.validated_stage(json.dumps({**a, **changes}).encode(), "seed")

    def test_serve_cannot_report_closed_with_held_or_unknown_owners(self):
        for key, changed in (
            ("httpSockets", 1),
            ("readerActive", 1),
            ("getterPending", 1),
            ("observerPending", 1),
            ("exporterFailures", True),
            ("exporterDropped", 0),
            ("casePortClosed", False),
        ):
            a = self.stage("serve")
            a["result"][key] = changed
            with self.subTest(key=key), self.assertRaises(m.GateError):
                m.validated_stage(json.dumps(a).encode(), "serve")

    def test_explicit_producer_advances_do_not_convert_unknown_send_result(self):
        a = self.stage("advance-callback")
        a["result"]["ordinarySendResult"] = "delivered"
        with self.assertRaises(m.GateError):
            m.validated_stage(json.dumps(a).encode(), "advance-callback")
        self.assertEqual(self.stage("advance-reconcile")["result"]["newOperationAcceptances"], 0)

    def env(self, directory, mode="serve"):
        return {
            "P2_OPERATIONS_DIRECTORY": str(directory),
            "P2_OPERATIONS_SCHEMA": "p2_operations_" + "a" * 32,
            "P2_OPERATIONS_PG_PORT": "5432",
            (
                "P2_OPERATIONS_OWNER_PASSWORD"
                if mode in m.OWNER_MODES
                else "P2_OPERATIONS_RUNTIME_PASSWORD"
            ): "synthetic-only-password",
        }

    def test_node_environment_roles_do_not_cross_and_reject_ambient_selectors(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw).resolve()
            for mode in m.MODES:
                m.validate_child_environment(self.env(directory, mode), mode)
            for key in (
                "PGPASSWORD",
                "HTTP_PROXY",
                "NODE_OPTIONS",
                "P2_OPERATIONS_OWNER_PASSWORD",
                "LIVEKIT_API_SECRET",
            ):
                with self.subTest(key=key), self.assertRaises(m.GateError):
                    m.validate_child_environment({**self.env(directory), key: "sentinel"}, "serve")

    def test_environment_rejects_malformed_port_schema_nonprivate_or_relative_directory(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw).resolve()
            for key, value in (
                ("P2_OPERATIONS_PG_PORT", "01"),
                ("P2_OPERATIONS_PG_PORT", "65536"),
                ("P2_OPERATIONS_SCHEMA", "public"),
                ("P2_OPERATIONS_DIRECTORY", "relative"),
            ):
                with self.subTest(key=key, value=value), self.assertRaises(m.GateError):
                    m.validate_child_environment({**self.env(directory), key: value}, "serve")
            directory.chmod(0o755)
            with self.assertRaises(m.GateError):
                m.validate_child_environment(self.env(directory), "serve")

    def test_compile_vite_and_browser_cannot_receive_db_or_ambient_provider_environment(self):
        m.validate_child_environment({}, "compile")
        m.validate_child_environment({"P2_OPERATIONS_API_PORT": "32100"}, "vite")
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw).resolve()
            uid = "11111111-1111-4111-8111-111111111111"
            env = {
                "P2_OPERATIONS_BROWSER_ORIGIN": "http://127.0.0.1:32100/",
                "P2_OPERATIONS_BROWSER_OUTPUT": str(directory),
                "P2_OPERATIONS_BROWSER_ACCESS": "a" * 43,
                "P2_OPERATIONS_DIRECTORY": str(directory),
                "P2_OPERATIONS_OWNER": "a" * 32,
                **{
                    "P2_OPERATIONS_" + k: uid
                    for k in ("RECEIPT_ID", "OPERATION_KEY", "OUTBOUND_ID")
                },
            }
            m.validate_child_environment(env, "browser")
            for role, base in (
                ("compile", {}),
                ("vite", {"P2_OPERATIONS_API_PORT": "32100"}),
                ("browser", env),
            ):
                with self.subTest(role=role), self.assertRaises(m.GateError):
                    m.validate_child_environment(
                        {**base, "P2_OPERATIONS_RUNTIME_PASSWORD": "secret"}, role
                    )
            for changed in (
                "http://localhost:32100/",
                "https://127.0.0.1:32100/",
                "http://127.0.0.1:32100/?token=private",
            ):
                with self.assertRaises(m.GateError):
                    m.validate_child_environment(
                        {**env, "P2_OPERATIONS_BROWSER_ORIGIN": changed}, "browser"
                    )

    def test_browser_marker_is_owner_bound_closed_and_boolean_safe(self):
        a = {"schemaVersion": 1, "owner": "a" * 32, "stage": "request-dispatch"}
        self.assertEqual(
            m.validated_marker(json.dumps(a).encode(), "request-dispatch", "a" * 32), a
        )
        for change in (
            {"owner": "b" * 32},
            {"stage": "request-callback"},
            {"schemaVersion": True},
            {"pid": 123},
        ):
            with self.assertRaises(m.GateError):
                m.validated_marker(
                    json.dumps({**a, **change}).encode(), "request-dispatch", "a" * 32
                )

    def test_fixture_has_exact_distinct_capabilities_and_no_synthetic_revision_repair(self):
        a = m.make_fixture()
        self.assertEqual(len(a["ids"]["history"]), 9)
        self.assertEqual(a["request"]["investigationConsent"], True)
        for mutate in (
            lambda x: x.update(schemaVersion=True),
            lambda x: x.update(quote={}),
            lambda x: x.update(nativeToken=x["accountToken"]),
            lambda x: x["scope"].update(accountId="foreign"),
            lambda x: x["ids"]["history"].append(x["ids"]["main"]),
        ):
            b = copy.deepcopy(a)
            mutate(b)
            with self.assertRaises(m.GateError):
                m.validate_fixture(b)

    def test_private_scan_covers_header_and_bare_credentials_and_keys(self):
        a = m.make_fixture()
        secrets = m.fixture_secrets(
            a,
            {"POSTGRES_PASSWORD": "runtime-secret", "POSTGRES_MIGRATION_PASSWORD": "owner-secret"},
        )
        for secret in (
            a["operatorAuthorization"],
            a["operatorAuthorization"][7:],
            a["nativeToken"],
            a["sms"]["hmacKeyBase64"],
            a["cursorKeyBase64"],
            "runtime-secret",
            "owner-secret",
        ):
            with self.subTest(kind=len(secret)), self.assertRaises(m.GateError):
                m.exclude_private(("prefix " + secret).encode(), secrets)
        m.exclude_private(b'{"status":"passed","count":0}', secrets)

    def write(self, path, data=b"{}"):
        path.write_bytes(data)
        path.chmod(0o600)

    def test_endpoint_binds_real_child_pid_and_rejects_boolean_port(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "endpoint.json"
            value = {"schemaVersion": 1, "host": "127.0.0.1", "port": 32100, "pid": 123}
            self.write(path, json.dumps(value).encode())
            self.assertEqual(m.endpoint(path, 123), 32100)
            for change in (
                {"port": True},
                {"pid": 124},
                {"host": "localhost"},
                {"token": "private"},
            ):
                self.write(path, json.dumps({**value, **change}).encode())
                with self.assertRaises(m.GateError):
                    m.endpoint(path, 123)

    def test_fresh_report_target_rejects_absolute_alias_symlink_existing_and_sibling(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            good = Path(".local/validation/p2-operations/actual.json")
            target = m.target_path(root, good)
            for bad in (
                Path("/tmp/actual.json"),
                Path(".local/validation/other/actual.json"),
                Path(".local/validation/p2-operations/nested/actual.json"),
                Path(".local/validation/p2-operations/../actual.json"),
            ):
                with self.assertRaises(m.GateError):
                    m.target_path(root, bad)
            target.with_name("actual-artifacts").mkdir(mode=0o700)
            with self.assertRaises(m.GateError):
                m.target_path(root, good)

    def test_report_accepts_owned_nonwritable_shared_ancestors_but_keeps_leaf_private(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            (root / ".local").mkdir(mode=0o755)
            (root / ".local/validation").mkdir(mode=0o755)
            target = m.target_path(root, Path(".local/validation/p2-operations/fresh.json"))
            self.assertEqual(target.parent.stat().st_mode & 0o777, 0o700)
            uid = os.getuid()
            with patch.object(m.os, "getuid", return_value=uid + 1), self.assertRaises(m.GateError):
                m.target_path(root, Path(".local/validation/p2-operations/foreign.json"))
            (root / ".local").chmod(0o777)
            with self.assertRaises(m.GateError):
                m.target_path(root, Path(".local/validation/p2-operations/other.json"))

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            (root / ".local").mkdir(mode=0o755)
            (root / ".local/validation").mkdir(mode=0o755)
            (root / "other").mkdir(mode=0o700)
            (root / ".local/validation/p2-operations").symlink_to(
                root / "other", target_is_directory=True
            )
            with self.assertRaises(m.GateError):
                m.target_path(root, Path(".local/validation/p2-operations/linked.json"))

    def test_recursive_index_binds_nested_summary_empty_streams_and_exact_root_self_exclusion(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            (root / "nested").mkdir(mode=0o700)
            self.write(root / "nested/summary.json", b'{"status":"passed"}')
            self.write(root / "nested/retained-index.json", b'{"old":"index"}')
            self.write(root / "capture.bin", b"")
            value = m.evidence_index(root)
            sha = m.digest(m.bounded_read(root / "retained-index.json"))
            self.assertEqual(
                set(value["files"]),
                {"nested/summary.json", "nested/retained-index.json", "capture.bin"},
            )
            m.validate_evidence_index(root, sha)
            self.write(root / "nested/summary.json", b'{"status":"failed"}')
            with self.assertRaises(m.GateError):
                m.validate_evidence_index(root, sha)

    def test_index_rejects_extra_file_symlink_hardlink_bad_modes_and_empty_nonstream(self):
        for kind in ("extra", "symlink", "hardlink", "mode", "empty", "directory-mode"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as raw:
                root = Path(raw).resolve()
                self.write(root / "proof.json")
                m.evidence_index(root)
                sha = m.digest(m.bounded_read(root / "retained-index.json"))
                if kind == "extra":
                    self.write(root / "unknown.json")
                elif kind == "symlink":
                    (root / "alias").symlink_to(root / "proof.json")
                elif kind == "hardlink":
                    os.link(root / "proof.json", root / "alias")
                elif kind == "mode":
                    (root / "proof.json").chmod(0o644)
                elif kind == "empty":
                    self.write(root / "proof.json", b"")
                else:
                    (root / "unsafe").mkdir(mode=0o755)
                with self.assertRaises(m.GateError):
                    m.validate_evidence_index(root, sha)

    def test_index_and_direct_file_read_enforce_declared_bounds(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "proof.json"
            self.write(path, b"x" * 17)
            with self.assertRaises(m.GateError):
                m.bounded_read(path, 16)
            self.write(path, b"")
            with self.assertRaises(m.GateError):
                m.bounded_read(path)
            self.assertEqual(m.bounded_read(path, allow_empty=True), b"")


class ActualCallOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def test_caller_cancellation_retains_real_thread_until_release_and_rejects_new_work_after_close(
        self,
    ):
        entered = threading.Event()
        release = threading.Event()
        owners = m.ActualCalls()

        def actual():
            entered.set()
            release.wait(2)
            return 7

        caller = asyncio.create_task(owners.call(actual))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 1))
            caller.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await caller
            self.assertEqual(len(owners.tasks), 1)
            self.assertFalse(await owners.close(time.monotonic()))
            with self.assertRaises(m.GateError):
                await owners.call(lambda: 1)
            release.set()
            self.assertTrue(await owners.close(time.monotonic() + 1))
        finally:
            release.set()
            await owners.close(time.monotonic() + 2)

    def test_public_plan_does_not_load_setup_or_launch_children(self):
        import contextlib
        import io
        from unittest.mock import patch

        out = io.StringIO()
        with (
            patch.object(m.core, "load_setup", side_effect=AssertionError("forbidden")),
            patch.object(m, "Children", side_effect=AssertionError("forbidden")),
            contextlib.redirect_stdout(out),
        ):
            self.assertEqual(m.main(["--plan"]), 0)
        self.assertFalse(json.loads(out.getvalue())["measurement_started"])

    def test_unknown_duplicate_and_conflicting_cli_flags_never_echo_arguments(self):
        import contextlib
        import io

        for args in (
            ["--PRIVATE_SENTINEL"],
            ["--plan", "--plan"],
            ["--plan", "--report", "secret.json"],
        ):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(m.main(args), 1)
            self.assertEqual(json.loads(out.getvalue())["code"], "invalid_arguments")
            self.assertNotIn("SENTINEL", out.getvalue())

    def test_report_exact_groups_counts_finite_duration_and_proof_inventory(self):
        v = {
            "schema_version": 1,
            "status": "passed",
            "mode": m.MODE,
            "tests": 16,
            "passed": 16,
            "storage_cases": list(m.CASE_NAMES),
            "browser_groups": list(m.BROWSER_GROUPS),
            "browser_tests": 1,
            "child_commands": 13,
            "operation_acceptances": 1,
            "ordinary_send_calls": 1,
            "ordinary_send_results": 0,
            "callback_observations": 1,
            "sql_waiter_graphs": 0,
            "sfu_calls": 0,
            "provider_calls": 0,
            "cleanup_complete": True,
            "node_version": "24.22.2",
            "duration_seconds": 20.5,
            "retained_index_sha256": "a" * 64,
            "proofs": {
                name: {"bytes": 1, "sha256": "b" * 64}
                for name in (
                    *m.PROOF_FILES,
                    *m.PARENT_PROOF_FILES,
                )
            },
        }
        m.validated_report(json.dumps(v).encode())
        for name in m.SNAPSHOT_PROOF_FILES:
            missing = copy.deepcopy(v)
            del missing["proofs"][name]
            with self.assertRaises(m.GateError):
                m.validated_report(json.dumps(missing).encode())
        for change in (
            {"child_commands": True},
            {"child_commands": 14},
            {"tests": 19},
            {"sql_waiter_graphs": 1},
            {"cleanup_complete": False},
            {"duration_seconds": float("nan")},
            {"duration_seconds": 10**1000},
            {"proofs": {}},
            {"unknown": 1},
        ):
            with self.assertRaises(m.GateError):
                m.validated_report(json.dumps({**v, **change}).encode())


class OperationsProofTests(unittest.TestCase):
    def uid(self, n):
        return f"{n:08d}-1111-4111-8111-111111111111"

    def compact(self, value):
        return json.dumps(value, separators=(",", ":"), ensure_ascii=True)

    def corpus(self):
        """Literal synthetic relational inventory; no database qualification is claimed."""
        f = m.make_fixture()
        schema = "p2_operations_" + f["owner"]
        case = m.schemas(schema)[1]
        rows = {k: [] for k in m.EXPECTED_MANIFEST["schemaTables"]}
        stamp = "2026-11-12T00:00:00.000Z"
        stored = []
        ids = [f["ids"]["main"], *f["ids"]["history"], f["ids"]["sms"]]
        for n, event_id in enumerate(ids):
            provider = f["providerScope"] if n < 10 else f["sms"]["providerScope"]
            event = {
                "schemaVersion": 1,
                "type": "text.received",
                "eventId": event_id,
                "providerScope": provider,
                "accountScope": f["scope"],
                "conversationId": f["conversationId"],
                "caseId": f["caseId"],
                "receivedAt": stamp,
                "channel": "web_chat" if n < 10 else "sms",
                "messageId": event_id,
                "senderId": "scripted-sender",
                "body": "Original unchanged input " + str(n),
            }
            rid = self.uid(100 + n)
            op = self.uid(200 + n)
            receipt = {
                "receiptId": rid,
                "eventId": event_id,
                "messageId": event_id,
                "acceptanceSequence": str(n + 1),
                "acceptedAt": stamp,
            }
            stored.append(
                {
                    "receipt": receipt,
                    "event": event,
                    "operationKey": op,
                    "processingState": "pending",
                    "associationVersion": "1",
                }
            )
            rows["inbox"].append(
                {
                    "receipt_id": rid,
                    "tenant_id": f["scope"]["tenantId"],
                    "account_id": f["scope"]["accountId"],
                    "provider": provider["provider"],
                    "provider_account_id": provider["providerAccountId"],
                    "event_id": event_id,
                    "message_id": event_id,
                    "conversation_id": f["conversationId"],
                    "wire_json": self.compact(event),
                    "canonical_payload": self.compact(
                        {k: v for k, v in event.items() if k != "receivedAt"}
                    ),
                    "acceptance_sequence": n + 1,
                    "accepted_at": stamp,
                }
            )
            rows["processing_intents"].append(
                {
                    "receipt_id": rid,
                    "operation_key": op,
                    "state": "dispatched" if n == 0 else "pending",
                    "external_receipt_id": self.uid(300) if n == 0 else None,
                }
            )
        original = stored[0]
        submission = {
            "schemaVersion": 1,
            "kind": "investigation",
            "scope": f["scope"],
            "operationKey": original["operationKey"],
            "caseId": f["caseId"],
            "caseRevision": "2",
            "conversationId": f["conversationId"],
            "message": {
                k: original["event"][k] for k in ("eventId", "messageId", "senderId", "body")
            },
        }
        submission["message"]["receiptId"] = original["receipt"]["receiptId"]
        canonical = self.compact(submission)
        sha = m.digest(canonical.encode())
        ledger = [
            {
                "submission": submission,
                "canonicalPayload": canonical,
                "payloadDigest": sha,
                "receipt": {
                    "scope": f["scope"],
                    "operationKey": original["operationKey"],
                    "payloadDigest": sha,
                    "receiptId": self.uid(300),
                },
            }
        ]
        rows["dispatch_plans"] = [
            {
                "receipt_id": original["receipt"]["receiptId"],
                "payload_json": canonical,
                "payload_digest": sha,
            }
        ]
        rows["native_bindings"] = [
            {"binding_id": f["bindingId"]},
            *[{"binding_id": self.uid(500 + n)} for n in range(4)],
        ]
        anchor = {
            "schemaVersion": 1,
            "responseId": f["ids"]["response"],
            "generationId": f["ids"]["generation"],
            "bindingId": f["bindingId"],
            "inputId": f["ids"]["main"],
            "scope": f["scope"],
            "caseId": f["caseId"],
            "conversationId": f["conversationId"],
        }
        anchor_raw = self.compact(anchor)
        rows["native_responses"] = [
            {
                "response_id": f["ids"]["response"],
                "generation_id": f["ids"]["generation"],
                "binding_id": f["bindingId"],
                "input_receipt_id": original["receipt"]["receiptId"],
                "operation_key": original["operationKey"],
                "canonical_anchor": anchor_raw,
                "anchor_digest": m.digest(anchor_raw.encode()),
                "response_sequence": 1,
            }
        ]
        facts = []
        receipts = []
        for n in (1, 2):
            fact = {
                "schemaVersion": 1,
                "eventId": self.uid(400 + n),
                "responseId": f["ids"]["response"],
                "generationId": f["ids"]["generation"],
                "sdkSpeechId": "scripted-speech",
                "fact": {"type": "generated_complete", "text": "Synthetic observation"},
            }
            raw = self.compact(fact)
            digest = m.digest(raw.encode())
            receipt = {
                "receiptId": self.uid(450 + n),
                "payloadDigest": digest,
                "observationSequence": str(n),
            }
            facts.append(fact)
            receipts.append(receipt)
            rows["native_observations"].append(
                {
                    "event_id": fact["eventId"],
                    "response_id": f["ids"]["response"],
                    "binding_id": f["bindingId"],
                    "canonical_payload": raw,
                    "payload_digest": digest,
                    "receipt_id": receipt["receiptId"],
                    "source": "agent_sdk",
                    "observation_sequence": n,
                }
            )
        request = {
            "schemaVersion": 1,
            "outboundId": f["ids"]["outbound"],
            "attemptId": self.uid(600),
            "providerOperationKey": self.uid(601),
            "scope": f["scope"],
        }
        send_raw = self.compact(request)
        send_sha = m.digest(send_raw.encode())
        rows["reply_intents"] = [{"outbound_id": f["ids"]["outbound"]}]
        rows["send_attempts"] = [
            {
                "outbound_id": f["ids"]["outbound"],
                "tenant_id": f["scope"]["tenantId"],
                "account_id": f["scope"]["accountId"],
                "attempt_id": request["attemptId"],
                "provider_operation_key": request["providerOperationKey"],
                "canonical_request": send_raw,
                "request_digest": send_sha,
            }
        ]
        observation = {
            "schemaVersion": 1,
            "eventId": f["ids"]["callback"],
            "attemptId": request["attemptId"],
            "providerOperationKey": request["providerOperationKey"],
            "requestDigest": send_sha,
            "state": "delivered",
        }
        cbraw = self.compact(observation)
        rows["callback_observations"] = [
            {
                "attempt_id": request["attemptId"],
                "canonical_payload": cbraw,
                "payload_digest": m.digest(cbraw.encode()),
                "receipt_id": self.uid(650),
            }
        ]
        snapshot = {schema: rows, case: {"case_metadata": [], "cases": []}}
        proofs = {
            "operations-owner-proof.json": {
                "schema": schema,
                "caseSchema": case,
                "tables": rows,
                "caseTables": snapshot[case],
            },
            "operations-provider-ledger.json": ledger,
            "operations-seed-proof.json": {
                "accepted": [
                    {"receiptId": x["receipt"]["receiptId"], "operationKey": x["operationKey"]}
                    for x in stored[:10]
                ],
                "stored": stored[:10],
                "sms": {"stored": stored[10]},
                "reply": {},
                "sendRequest": request,
                "sendOutcome": {"status": "unknown"},
            },
            "operations-reconcile-proof.json": {
                "operationLookups": 1,
                "newOperationAcceptances": 0,
                "facts": facts,
                "observations": receipts,
                "ledger": ledger,
            },
            "operations-callback-proof.json": {
                "observation": observation,
                "receipt": {"receiptId": self.uid(650)},
                "newSendCalls": 0,
                "view": {"evidence": {"sendResult": None}},
            },
        }
        # Independently exercise the original signed wire and SQL envelope joins.
        request.update(
            caseId=f["caseId"],
            conversationId=f["conversationId"],
            body="Scripted notice",
            senderId=f["sms"]["senderId"],
            providerScope=f["sms"]["providerScope"],
        )
        send_raw = self.compact(request)
        send_sha = m.digest(send_raw.encode())
        rows["send_attempts"][0].update(canonical_request=send_raw, request_digest=send_sha)
        envelope = {
            "schemaVersion": 1,
            "outboundId": f["ids"]["outbound"],
            "responseId": f["ids"]["response"],
            "body": "Scripted notice",
            "scope": f["scope"],
            "caseId": f["caseId"],
            "conversationId": f["conversationId"],
        }
        payload = self.compact(envelope)
        intent_digest = m.digest(payload.encode())
        body_digest = m.digest(b"Scripted notice")
        rows["reply_intents"][0].update(
            tenant_id=f["scope"]["tenantId"],
            account_id=f["scope"]["accountId"],
            case_id=f["caseId"],
            conversation_id=f["conversationId"],
            receipt_id=self.uid(660),
            canonical_payload=payload,
            intent_digest=intent_digest,
            body_digest=body_digest,
        )
        proofs["operations-seed-proof.json"]["reply"] = {
            "receiptId": self.uid(660),
            "intentDigest": intent_digest,
            "bodyDigest": body_digest,
        }
        rows["native_responses"][0].update(
            tenant_id=f["scope"]["tenantId"],
            account_id=f["scope"]["accountId"],
            case_id=f["caseId"],
            conversation_id=f["conversationId"],
        )

        def signed(body, key, prefix):
            raw = self.compact(body).encode()
            timestamp = str(int(m.utc(stamp).timestamp()))
            scope = f["sms"]["providerScope"]
            material = (
                prefix
                + scope["tenantId"]
                + "\n"
                + scope["provider"]
                + "\n"
                + scope["providerAccountId"]
                + "\n"
                + timestamp
                + "\n"
            ).encode() + raw
            return {
                "rawBase64": base64.b64encode(raw).decode(),
                "headers": {
                    "timestamp": timestamp,
                    "signature": hmac.new(
                        base64.b64decode(key), material, hashlib.sha256
                    ).hexdigest(),
                },
            }

        sms = stored[10]["event"]
        sms_body = {
            k: sms[k] for k in ("schemaVersion", "eventId", "messageId", "senderId", "body")
        }
        proofs["operations-seed-proof.json"]["sms"]["signed"] = signed(
            sms_body, f["sms"]["hmacKeyBase64"], "p2.fake_sms.v1\n"
        )
        observation["requestDigest"] = send_sha
        callback_signed = signed(
            observation, f["sms"]["callbackKeyBase64"], "p2.fake_sms_callback.v1\n"
        )
        proofs["operations-callback-proof.json"].update(callback_signed)
        cbraw = self.compact(observation)
        rows["callback_observations"][0].update(
            canonical_payload=cbraw,
            payload_digest=m.digest(cbraw.encode()),
            first_wire=base64.b64decode(callback_signed["rawBase64"]).decode(),
            accepted_at=stamp,
            tenant_id=f["scope"]["tenantId"],
            provider=f["sms"]["providerScope"]["provider"],
            provider_account_id=f["sms"]["providerScope"]["providerAccountId"],
        )
        return f, schema, snapshot, proofs

    def test_eight_large_complete_owner_snapshots_are_retained_without_combined_file_overflow(self):
        _, schema, snapshot, _ = self.corpus()
        snapshot[schema]["schema_metadata"] = [
            {"catalog_snapshot": {"definition": "x" * 180000, "note": "é😀"}}
        ]
        snapshots = {phase: copy.deepcopy(snapshot) for phase in m.SNAPSHOT_PHASES}
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw).resolve()
            manifest = m.write_snapshot_proofs(directory, snapshots, schema)
            self.assertEqual(m.validate_snapshot_proofs(directory, schema), snapshots)
            self.assertGreater(
                sum(d["bytes"] for d in manifest["snapshots"].values()), m.MAX_PROOF_BYTES
            )
            for phase, descriptor in manifest["snapshots"].items():
                source = (directory / descriptor["path"]).read_bytes()
                self.assertLessEqual(len(source), m.MAX_PROOF_BYTES)
                self.assertEqual(
                    json.loads(source)[schema]["schema_metadata"][0]["catalog_snapshot"],
                    snapshot[schema]["schema_metadata"][0]["catalog_snapshot"],
                )
                self.assertEqual(descriptor["tableCounts"][schema]["inbox"], 11)
                self.assertEqual(manifest["digests"][phase], hashlib.sha256(source).hexdigest())
            self.assertEqual(len(list(directory.iterdir())), 9)
            self.assertLessEqual(
                (directory / "gate-owned-before-after.json").stat().st_size, m.MAX_REPORT_BYTES
            )
            self.assertEqual(
                (m.MAX_PROOF_BYTES, m.MAX_EVIDENCE_BYTES, m.MAX_REPORT_BYTES, m.EXPECTED_CHILDREN),
                (1048576, 16777216, 32768, 13),
            )

    def test_snapshot_manifest_rejects_unknown_phases_paths_types_counts_hashes_and_payload_tampering(
        self,
    ):
        _, schema, snapshot, _ = self.corpus()
        snapshots = {phase: copy.deepcopy(snapshot) for phase in m.SNAPSHOT_PHASES}
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw).resolve()
            original = m.write_snapshot_proofs(directory, snapshots, schema)
            path = directory / "gate-owned-before-after.json"
            for change in ("unknown", "path", "type", "bytes", "count", "hash"):
                value = copy.deepcopy(original)
                descriptor = value["snapshots"]["after_seed"]
                if change == "unknown":
                    value["snapshots"]["other"] = descriptor
                elif change == "path":
                    descriptor["path"] = "../outside.json"
                elif change == "type":
                    descriptor["type"] = "runtime_claim"
                elif change == "bytes":
                    descriptor["bytes"] = True
                elif change == "count":
                    descriptor["tableCounts"][schema]["inbox"] = True
                else:
                    descriptor["sha256"] = "0" * 64
                path.write_text(json.dumps(value))
                with self.subTest(change=change), self.assertRaises(m.GateError):
                    m.validate_snapshot_proofs(directory, schema)
            path.write_text(json.dumps(original))
            payload = directory / m.SNAPSHOT_PROOF_FILES[0]
            payload.write_bytes(payload.read_bytes() + b" ")
            with self.assertRaises(m.GateError):
                m.validate_snapshot_proofs(directory, schema)

    def test_oversized_single_snapshot_and_missing_phase_fail_before_any_retention(self):
        _, schema, snapshot, _ = self.corpus()
        snapshots = {phase: copy.deepcopy(snapshot) for phase in m.SNAPSHOT_PHASES}
        for changed in ("oversize", "missing", "extra"):
            values = copy.deepcopy(snapshots)
            if changed == "oversize":
                values["after_reopen"][schema]["schema_metadata"] = [
                    {"catalog_snapshot": "x" * m.MAX_PROOF_BYTES}
                ]
            elif changed == "missing":
                del values["after_seed"]
            else:
                values["other"] = copy.deepcopy(snapshot)
            with tempfile.TemporaryDirectory() as raw:
                directory = Path(raw).resolve()
                with self.subTest(changed=changed), self.assertRaises(m.GateError):
                    m.write_snapshot_proofs(directory, values, schema)
                self.assertEqual(list(directory.iterdir()), [])

    def test_realistic_synthetic_full_original_operation_response_callback_join(self):
        f, schema, snapshot, proofs = self.corpus()
        result = m.validate_owner_joins(proofs, snapshot, f, schema)
        self.assertEqual(result["originalReceipts"], 11)
        self.assertEqual(result["logicalOperationAcceptances"], 1)
        self.assertEqual(result["ordinarySendResults"], 0)
        self.assertFalse(result["humanHearingClaimed"])

    def test_recomputed_wrong_operation_scope_case_conversation_message_and_digest_rejected(self):
        for key in ("scope", "caseId", "conversationId", "message", "digest"):
            f, schema, snapshot, proofs = self.corpus()
            operation = proofs["operations-provider-ledger.json"][0]
            if key == "scope":
                operation["submission"]["scope"] = {**f["scope"], "accountId": "foreign"}
            elif key == "message":
                operation["submission"]["message"]["body"] = "changed"
            elif key == "digest":
                operation["payloadDigest"] = "0" * 64
            else:
                operation["submission"][key] = "foreign"
            if key != "digest":
                operation["canonicalPayload"] = self.compact(operation["submission"])
                operation["payloadDigest"] = m.digest(operation["canonicalPayload"].encode())
                snapshot[schema]["dispatch_plans"][0].update(
                    payload_json=operation["canonicalPayload"],
                    payload_digest=operation["payloadDigest"],
                )
                operation["receipt"]["payloadDigest"] = operation["payloadDigest"]
            with self.subTest(key=key), self.assertRaises(m.GateError):
                m.validate_owner_joins(proofs, snapshot, f, schema)

    def test_changed_original_receipt_provider_sequence_and_duplicate_inventory_reject(self):
        for key in ("receipt", "provider", "sequence", "duplicate"):
            f, schema, snapshot, proofs = self.corpus()
            row = snapshot[schema]["inbox"][0]
            if key == "receipt":
                row["receipt_id"] = self.uid(999)
            elif key == "provider":
                row["provider"] = "foreign"
            elif key == "sequence":
                row["acceptance_sequence"] = 2
            else:
                snapshot[schema]["inbox"].append(copy.deepcopy(row))
            with self.subTest(key=key), self.assertRaises(m.GateError):
                m.validate_owner_joins(proofs, snapshot, f, schema)

    def test_forged_sdk_source_or_sequence_and_callback_cannot_invent_send_result(self):
        for key in ("source", "sequence", "callback", "known-send"):
            f, schema, snapshot, proofs = self.corpus()
            if key == "source":
                snapshot[schema]["native_observations"][0]["source"] = "browser_client"
            elif key == "sequence":
                snapshot[schema]["native_observations"][1]["observation_sequence"] = 1
            elif key == "callback":
                proofs["operations-callback-proof.json"]["observation"]["requestDigest"] = "0" * 64
            else:
                snapshot[schema]["send_results"] = [{"status": "accepted"}]
            with self.subTest(key=key), self.assertRaises(m.GateError):
                m.validate_owner_joins(proofs, snapshot, f, schema)

    def test_snapshot_unknown_missing_foreign_schema_or_boolean_owner_row_fails(self):
        _f, schema, _snapshot, proofs = self.corpus()
        v = proofs["operations-owner-proof.json"]
        for change in (
            {"schema": "public"},
            {"unknown": {}},
            {"caseSchema": schema},
            {"tables": {}},
        ):
            with self.assertRaises(m.GateError):
                m.proof_snapshot({**v, **change}, schema)
        m.proof_snapshot(v, schema)

    def diagnostics(self):
        return {
            "schemaVersion": 1,
            "status": "known",
            "scope": "process",
            "requestId": self.uid(1),
            "observedAt": "2026-11-12T00:00:00.000Z",
            "sources": [
                {
                    "source": source,
                    "state": "observed",
                    "observedAt": "2026-11-12T00:00:00.000Z",
                    "values": [{"name": name, "value": 1} for name in sorted(keys)],
                }
                for source, keys in m.METRIC_KEYS.items()
            ],
            "observations": [
                {
                    "kind": "read_span",
                    "source": "operations",
                    "operation": "context",
                    "status": "ok",
                    "code": "known",
                    "observedAt": "2026-11-12T00:00:00.000Z",
                    "durationMs": 7000,
                    "requestId": self.uid(2),
                }
            ],
        }

    def test_closed_producer_cause_codes_match_public_wire_and_preserve_actual_inbox_rejection(
        self,
    ):
        source = (ROOT / "projects/channel-continuity/src/operations-types.ts").read_text()
        declaration = source.split("export const OPERATIONS_EVENT_CODES = Object.freeze([", 1)[
            1
        ].split("] as const);", 1)[0]
        codes = re.findall(r"'([^']+)'", declaration)
        self.assertEqual((len(codes), len(set(codes))), (76, 76))
        self.assertEqual(m.EVENT_CODES, set(codes))
        value = self.diagnostics()
        event = {
            "kind": "producer_log",
            "source": "inbox",
            "operation": "producer",
            "status": "rejected",
            "code": "AccessDenied",
            "observedAt": "2026-11-12T00:00:00.000Z",
            "durationMs": 0,
            "requestId": None,
        }
        value["observations"].append(event)
        self.assertEqual(m.validate_telemetry(value)["observations"][-1]["code"], "AccessDenied")
        for code in ("UNTRUSTED_SQL_SENTINEL", {"private": "message"}, True, None):
            changed = copy.deepcopy(value)
            changed["observations"][-1]["code"] = code
            with self.subTest(code=code), self.assertRaises(m.GateError):
                m.validate_telemetry(changed)

    def test_actual_span_allows_unclamped_elapsed_and_actual_self_getter_pending(self):
        value = self.diagnostics()
        m.validate_telemetry(value)
        self.assertEqual(value["observations"][0]["durationMs"], 7000)

    def test_telemetry_rejects_unknown_id_labels_bool_nonfinite_missing_or_fake_source(self):
        for key in (
            "unknown",
            "bool",
            "nonfinite",
            "missing",
            "fake-source",
            "nonspan",
            "primitive",
        ):
            v = self.diagnostics()
            if key == "unknown":
                v["sources"][0]["values"][0]["name"] = "receipt-" + self.uid(77)
            elif key == "bool":
                v["observations"][0]["durationMs"] = True
            elif key == "nonfinite":
                v["sources"][0]["values"][0]["value"] = float("inf")
            elif key == "missing":
                v["observations"] = []
            elif key == "fake-source":
                v["sources"].append({**v["sources"][0], "source": "rehydration"})
            elif key == "primitive":
                v["observations"][0]["code"] = {}
            else:
                v["observations"][0]["requestId"] = None
            with self.subTest(key=key), self.assertRaises(m.GateError):
                m.validate_telemetry(v)

    def test_safe_failure_diagnostics_reject_body_raw_path_code_unhashable_and_boolean_frame(self):
        v = {
            "schemaVersion": 1,
            "status": "failed",
            "mode": "exercise",
            "stage": "exercise",
            "errorType": "UnexpectedError",
            "code": None,
            "frames": [{"file": "pg_operations_cases.js", "line": 1}],
        }
        m.validate_node_failure(json.dumps(v).encode(), "exercise")
        for change in (
            {"errorType": {}},
            {"code": {}},
            {"body": "private"},
            {"frames": [{"file": "/private/path.js", "line": 1}]},
            {"frames": [{"file": "pg_operations_cases.js", "line": True}]},
        ):
            with self.assertRaises(m.GateError):
                m.validate_node_failure(json.dumps({**v, **change}).encode(), "exercise")

    def test_seed_diagnostic_successor_preserves_only_finite_public_code_and_substage(self):
        v = {
            "schemaVersion": 1,
            "status": "failed",
            "mode": "seed",
            "stage": "seed_collect_originals",
            "errorType": "ChannelError",
            "code": "Overloaded",
            "frames": [],
        }
        self.assertEqual(
            m.validate_node_failure(json.dumps(v).encode(), "seed")["code"], "Overloaded"
        )
        for change in (
            {"stage": "private_body"},
            {"stage": {}},
            {"code": "private_error_text"},
            {"mode": "exercise"},
        ):
            with self.assertRaises(m.GateError):
                m.validate_node_failure(json.dumps({**v, **change}).encode(), "seed")
        with self.assertRaises(m.GateError):
            m.validate_node_failure(json.dumps({**v, "mode": "exercise"}).encode(), "exercise")

    def test_exercise_diagnostic_stages_are_finite_and_bound_to_exercise_mode(self):
        v = {
            "schemaVersion": 1,
            "status": "failed",
            "mode": "exercise",
            "stage": "exercise",
            "errorType": "AssertionError",
            "code": None,
            "frames": [],
        }
        for stage in (
            "exercise_initial_context",
            "exercise_case_revision_cursor",
            "exercise_expiry_final_grant",
            "exercise_revocation_final_grant",
            "exercise_cursor_scope_section",
            "exercise_cursor_anchor",
            "exercise_canonical_paging",
            "exercise_zero_revision",
            "exercise_read_retry",
            "exercise_ignored_ownership",
            "exercise_http_boundary",
            "exercise_exporter_observations",
        ):
            with self.subTest(stage=stage):
                self.assertEqual(
                    m.validate_node_failure(json.dumps({**v, "stage": stage}).encode(), "exercise")[
                        "stage"
                    ],
                    stage,
                )
                with self.assertRaises(m.GateError):
                    m.validate_node_failure(
                        json.dumps({**v, "stage": stage, "mode": "seed"}).encode(), "seed"
                    )
        for stage in ("exercise_secret_body", "seed_collect_originals", {}, True):
            with self.subTest(stage=stage), self.assertRaises(m.GateError):
                m.validate_node_failure(json.dumps({**v, "stage": stage}).encode(), "exercise")

    def test_compiler_inputs_have_only_approved_two_overrides(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            project = root / "project"
            work = root / "work"
            project.mkdir(mode=0o700)
            work.mkdir(mode=0o700)
            files = m.compiler_inputs(project, work)
            self.assertEqual(len(files), 3)
            for file in files:
                v = m.json_file(file)
                self.assertEqual(set(v), {"extends", "compilerOptions"})
                self.assertEqual(set(v["compilerOptions"]), {"outDir", "tsBuildInfoFile"})
                self.assertTrue(Path(v["extends"]).is_relative_to(project))
                self.assertTrue(Path(v["compilerOptions"]["tsBuildInfoFile"]).is_relative_to(work))


class CleanupFaultTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_browser_child_capture_is_distinct_from_precreated_browser_evidence(self):
        from harness.process_control import UnsafeHarnessPath

        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw).resolve()
            output = work / "browser"
            output.mkdir(mode=0o700)
            env = {
                **m.core.base_environment(),
                "P2_OPERATIONS_BROWSER_ORIGIN": "http://127.0.0.1:12345",
                "P2_OPERATIONS_BROWSER_OUTPUT": str(output),
                "P2_OPERATIONS_BROWSER_ACCESS": "A" * 43,
                "P2_OPERATIONS_DIRECTORY": str(work),
                "P2_OPERATIONS_OWNER": "a" * 32,
                "P2_OPERATIONS_RECEIPT_ID": "00000000-0000-4000-8000-000000000001",
                "P2_OPERATIONS_OPERATION_KEY": "00000000-0000-4000-8000-000000000002",
                "P2_OPERATIONS_OUTBOUND_ID": "00000000-0000-4000-8000-000000000003",
            }
            argv = [
                sys.executable,
                "-I",
                "-c",
                (
                    "import os;from pathlib import Path;"
                    "p=Path(os.environ['P2_OPERATIONS_BROWSER_OUTPUT'])/'controlled.json';"
                    "fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);"
                    "os.write(fd,b'{}');os.close(fd)"
                ),
            ]
            old = m.Children(work, time.monotonic() + 5)
            with self.assertRaises(UnsafeHarnessPath):
                old.start("browser", argv, env, cwd=work)
            self.assertTrue(old.start_failed)
            self.assertEqual(old.children, [])
            captures = m.child_capture_root(work)
            self.assertEqual(captures, work / "commands")
            self.assertNotEqual(captures / "browser", output)
            children = m.Children(
                captures, time.monotonic() + 5, final_deadline=time.monotonic() + 7
            )
            child = children.start("browser", argv, env, cwd=work)
            try:
                self.assertEqual(await asyncio.to_thread(children.finish, child), b"")
            finally:
                await asyncio.to_thread(children.close)
            self.assertEqual((output / "controlled.json").read_bytes(), b"{}")
            self.assertEqual((captures / "browser/stdout.bin").read_bytes(), b"")
            self.assertTrue(m.owned_children_settled(children))
            self.assertEqual(children.count, 1)

    async def test_real_live_owned_child_is_not_forgotten_when_close_observation_throws(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw).resolve()
            barrier = m.FileBarrier(work, "held")
            children = m.Children(work, time.monotonic() + 8, final_deadline=time.monotonic() + 10)
            marker = work / "held.reached"
            pending = work / "held.pending"
            code = (
                "import os,time;fd=os.open("
                + repr(str(pending))
                + ",os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.write(fd,(str(os.getpid())+'\\n').encode());os.close(fd);os.link("
                + repr(str(pending))
                + ","
                + repr(str(marker))
                + ");os.unlink("
                + repr(str(pending))
                + ");time.sleep(30)"
            )
            child = children.start("compile", [sys.executable, "-I", "-c", code], {}, cwd=work)
            try:
                await asyncio.to_thread(child.wait_for_barrier, barrier, timeout=3)
                ddl = []
                with patch.object(children, "close", side_effect=m.GateError("cleanup_incomplete")):
                    complete = await m.cleanup_dependencies(
                        children, m.ActualCalls(), time.monotonic() + 1, lambda: ddl.append(1)
                    )
                self.assertFalse(complete)
                self.assertEqual(ddl, [])
                self.assertIsNone(child.returncode)
            finally:
                child.close()
            self.assertIsNotNone(child.returncode)
            self.assertTrue(child.group_settled)

    async def test_known_exit_with_public_cleanup_failed_still_withholds_ddl(self):
        from types import SimpleNamespace

        children = SimpleNamespace(
            children=[SimpleNamespace(returncode=0, cleanup_failed=True, group_settled=True)],
            start_failed=False,
            close=lambda: None,
        )
        calls = []
        self.assertFalse(
            await m.cleanup_dependencies(
                children, m.ActualCalls(), time.monotonic() + 1, lambda: calls.append(1)
            )
        )
        self.assertEqual(calls, [])

    async def test_cleanup_uses_reserved_final_deadline_then_observes_its_actual_owner(self):
        from types import SimpleNamespace

        children = SimpleNamespace(
            children=[], start_failed=False, deadline=time.monotonic() - 1, close=lambda: None
        )
        final = time.monotonic() + 2
        calls = []

        def ddl():
            calls.append(children.deadline)

        self.assertTrue(await m.cleanup_dependencies(children, m.ActualCalls(), final, ddl))
        self.assertEqual(calls, [final])

    async def test_marker_retry_only_accepts_complete_owned_two_link_transient(self):
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            file = root / "marker.json"
            pending = root / "pending"
            pending.write_text('{"schemaVersion":1}')
            pending.chmod(0o600)
            os.link(pending, file)

            async def release():
                await asyncio.sleep(0.01)
                pending.unlink()

            task = asyncio.create_task(release())
            self.assertEqual(
                await m.wait_private_file(
                    file, SimpleNamespace(returncode=None), time.monotonic() + 1
                ),
                b'{"schemaVersion":1}',
            )
            await task
