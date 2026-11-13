"""Offline storage-gate boundaries; actual PostgreSQL qualification is separate."""

import copy
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
    "p2_communication_gate_test", ROOT / "local-setup/scripts/p2_communication_check.py"
)
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def encoded(value):
    return json.dumps(value).encode()


def context():
    return {
        "P2_COMM_DIRECTORY": "/private/synthetic",
        "P2_COMM_SCHEMA": "p2_playback_" + "a" * 32,
        "P2_COMM_PG_PORT": "15432",
    }


def settings():
    return {
        "POSTGRES_PASSWORD": "runtime_sentinel",
        "POSTGRES_MIGRATION_PASSWORD": "owner_sentinel",
    }


def uuid(n):
    return f"{n:08d}-1111-4111-8111-111111111111"


def sample_report():
    return {
        "schema_version": 1,
        "status": "passed",
        "mode": "local_synthetic_p2_communication",
        "tests": 16,
        "passed": 16,
        "errors": 0,
        "failures": 0,
        "skipped": 0,
        "cleanup_complete": True,
        "case_results": [{"name": n, "status": "passed", "code": "ok"} for n in GATE.CASE_NAMES],
        "schema_version_observed": 7,
        "prior_schema_version": 6,
        "owned_child_terminations": 2,
        "blocking_graphs_observed": 2,
        "responses": 10,
        "observations": 32,
        "populated_restore_verified": True,
        "provider_calls": False,
        "actual_browser_qualification_claimed": False,
        "actual_model_capture_claimed": False,
        "human_acknowledgement_claimed": False,
        "duration_seconds": 10.5,
        "child_commands": 21,
        "node_version": "24.22.2",
        "proofs": {n: {"bytes": 100, "sha256": "a" * 64} for n in GATE.PROOF_FILES},
    }


class StorageReportTests(unittest.TestCase):
    def test_exact_sixteen_named_storage_groups_and_complete_report(self):
        self.assertEqual(len(GATE.CASE_NAMES), 16)
        self.assertEqual(len(set(GATE.CASE_NAMES)), 16)
        self.assertEqual(GATE.validated_report(encoded(sample_report())), sample_report())

    def test_case_omission_reorder_duplicate_skip_and_wrong_qualification_fail(self):
        for kind in ("missing", "reordered", "duplicate", "skipped", "browser", "model", "ack"):
            item = sample_report()
            if kind == "missing":
                item["case_results"].pop()
            elif kind == "reordered":
                item["case_results"].reverse()
            elif kind == "duplicate":
                item["case_results"][0] = item["case_results"][1]
            elif kind == "skipped":
                item["skipped"] = 1
            else:
                item[
                    {
                        "browser": "actual_browser_qualification_claimed",
                        "model": "actual_model_capture_claimed",
                        "ack": "human_acknowledgement_claimed",
                    }[kind]
                ] = True
            with self.subTest(kind=kind), self.assertRaises(GATE.GateError):
                GATE.validated_report(encoded(item))

    def test_primitive_types_actual_kills_graphs_caps_and_children_are_exact(self):
        for key, value in [
            ("tests", True),
            ("responses", 10.0),
            ("observations", 31),
            ("owned_child_terminations", 1),
            ("blocking_graphs_observed", 1),
            ("child_commands", 20),
            ("child_commands", 22),
            ("child_commands", True),
            ("cleanup_complete", 1),
            ("provider_calls", 0),
            ("schema_version_observed", 6),
        ]:
            with self.subTest(key=key, value=value), self.assertRaises(GATE.GateError):
                GATE.validated_report(encoded({**sample_report(), key: value}))

    def test_nonfinite_duration_runtime_and_incomplete_proof_manifest_fail(self):
        for value in [0, -1, 181, True, float("nan"), float("inf"), 10**1000]:
            with self.assertRaises(GATE.GateError):
                GATE.validated_report(encoded({**sample_report(), "duration_seconds": value}))
        for value in ["24.22.1", "v24.22.2", "25.0.0", "26.12.0", None]:
            with self.assertRaises(GATE.GateError):
                GATE.validated_report(encoded({**sample_report(), "node_version": value}))
        item = sample_report()
        item["proofs"].pop(next(iter(item["proofs"])))
        with self.assertRaises(GATE.GateError):
            GATE.validated_report(encoded(item))

    def test_json_duplicate_aliases_nested_extra_truncation_and_capture_bound_fail(self):
        raw = encoded(sample_report())
        for value in [
            raw[:-1],
            b"\xff",
            b"[]",
            b"x" * 32769,
            raw.replace(b'"schema_version": 1', b'"schema_version": 1,"\\u0073chema_version": 1'),
            encoded({**sample_report(), "token": "secret"}),
        ]:
            with self.assertRaises(GATE.GateError):
                GATE.validated_report(value)


class StorageStageTests(unittest.TestCase):
    def test_exact_frozen_stage_shapes_and_drift_enum(self):
        for mode, source in GATE.RESPONSES.items():
            value = copy.deepcopy(source)
            value["nodeVersion"] = "24.22.2"
            if mode == "exercise":
                value["observations"] = 23
            if mode == "drift":
                value["driftKind"] = "count"
            with self.subTest(mode=mode), patch.object(GATE, "EXERCISE_OBSERVATIONS", 23):
                self.assertEqual(
                    GATE.validated_stage(
                        encoded(value), mode, fault="count" if mode == "drift" else None
                    ),
                    value,
                )

    def test_unfrozen_exercise_and_killed_modes_never_claim_success(self):
        item = {**GATE.RESPONSES["exercise"], "nodeVersion": "24.22.2", "observations": 23}
        for value in [None, True, 0, 32, 1.5]:
            with (
                patch.object(GATE, "EXERCISE_OBSERVATIONS", value),
                self.assertRaises(GATE.GateError),
            ):
                GATE.validated_stage(encoded(item), "exercise")
        for mode in ["upgrade-hold", "crash", "unknown"]:
            with self.assertRaises(GATE.GateError):
                GATE.validated_stage(b'{"status":"passed"}', mode)

    def test_missing_false_extra_and_source_observation_claims_fail(self):
        for mode in ["cleanup", "legacy-seed", "upgrade", "verify", "replay"]:
            item = {**GATE.RESPONSES[mode], "nodeVersion": "24.22.2"}
            for key in tuple(item):
                changed = dict(item)
                del changed[key]
                with self.subTest(mode=mode, key=key), self.assertRaises(GATE.GateError):
                    GATE.validated_stage(encoded(changed), mode)
            with self.assertRaises(GATE.GateError):
                GATE.validated_stage(encoded({**item, "token": "secret"}), mode)
        item = {**GATE.RESPONSES["exercise"], "nodeVersion": "24.22.2", "observations": 23}
        item["actualConnections"] = item.pop("maximumConnections")
        with patch.object(GATE, "EXERCISE_OBSERVATIONS", 23), self.assertRaises(GATE.GateError):
            GATE.validated_stage(encoded(item), "exercise")

    def test_unfrozen_cli_stops_before_any_configuration_or_pg_read(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(GATE, "EXERCISE_OBSERVATIONS", None),
            patch.object(
                GATE.core,
                "load_setup",
                side_effect=AssertionError("configuration_must_not_be_read"),
            ) as setup,
            redirect_stdout(io.StringIO()) as stream,
        ):
            self.assertEqual(
                GATE.main(
                    ["--report", ".local/validation/p2-communication/unfrozen.json"],
                    root=Path(temporary).resolve(),
                ),
                1,
            )
            setup.assert_not_called()
            self.assertEqual(json.loads(stream.getvalue())["code"], "unfrozen_fixture_protocol")


class StorageEnvironmentTests(unittest.TestCase):
    def test_all_modes_have_one_role_and_no_ambient_authority(self):
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "provider_sentinel",
                "PGPASSWORD": "ambient",
                "PYTHONPATH": "foreign",
                "HTTPS_PROXY": "private",
            },
            clear=False,
        ):
            for mode in GATE.MODES:
                env = GATE.child_environment(settings(), context(), mode)
                GATE.validate_child_environment(env, mode)
                self.assertFalse(
                    {"OPENAI_API_KEY", "PGPASSWORD", "PYTHONPATH", "HTTPS_PROXY"} & env.keys()
                )
                password = (
                    "P2_COMM_OWNER_PASSWORD"
                    if mode in GATE.OWNER_MODES
                    else "P2_COMM_RUNTIME_PASSWORD"
                )
                self.assertIn(password, env)
                self.assertNotIn(
                    "P2_COMM_RUNTIME_PASSWORD"
                    if mode in GATE.OWNER_MODES
                    else "P2_COMM_OWNER_PASSWORD",
                    env,
                )

    def test_extra_missing_dual_credentials_and_unsafe_context_fail(self):
        base = GATE.child_environment(settings(), context(), "exercise")
        for key, value in [
            ("P2_COMM_OWNER_PASSWORD", "owner"),
            ("OPENAI_API_KEY", "secret"),
            ("P2_COMM_SCHEMA", "public"),
            ("P2_COMM_DIRECTORY", "relative"),
            ("P2_COMM_DIRECTORY", "/private/../foreign"),
            ("P2_COMM_PG_PORT", True),
            ("P2_COMM_PG_PORT", "65536"),
        ]:
            with self.subTest(key=key, value=value), self.assertRaises(GATE.GateError):
                GATE.validate_child_environment({**base, key: value}, "exercise")
        for key in context():
            item = dict(base)
            del item[key]
            with self.assertRaises(GATE.GateError):
                GATE.validate_child_environment(item, "exercise")


class StorageProofTests(unittest.TestCase):
    def test_capacity_and_expiry_are_source_progress_without_guessed_sql_counts(self):
        capacity = {
            "schemaVersion": 1,
            "admittedOperations": 4,
            "abandonedWaiters": 1,
            "settledOperations": 4,
            "fifthRejected": "Overloaded",
            "laterProgress": True,
        }
        expiry = {
            "schemaVersion": 1,
            "expiredNewResponseDenied": True,
            "freshBindingProgress": True,
            "originalLateEvidenceAccepted": True,
            "originalReceiptPreserved": True,
        }
        self.assertEqual(GATE.validated_capacity(encoded(capacity)), capacity)
        self.assertEqual(GATE.validated_expiry(encoded(expiry)), expiry)
        for item in [
            {**capacity, "actualSqlWaiters": 2},
            {**capacity, "admittedOperations": True},
            {**capacity, "laterProgress": False},
        ]:
            with self.assertRaises(GATE.GateError):
                GATE.validated_capacity(encoded(item))
        with self.assertRaises(GATE.GateError):
            GATE.validated_expiry(encoded({**expiry, "originalReceiptPreserved": False}))

    def test_ready_identities_times_and_connection_bounds(self):
        capacity = {
            "schemaVersion": 1,
            "responseIds": [uuid(n) for n in range(1, 5)],
            "eventIds": [uuid(n) for n in range(5, 9)],
            "maximumOperations": 4,
            "maximumConnections": 2,
        }
        GATE.validate_ready(capacity, "capacity")
        for key, value in [
            ("responseIds", [uuid(1)] * 4),
            ("maximumConnections", True),
            ("maximumOperations", 5),
            ("eventIds", []),
        ]:
            with self.assertRaises(GATE.GateError):
                GATE.validate_ready({**capacity, key: value}, "capacity")
        expiry = {
            "schemaVersion": 1,
            "bindingId": uuid(1),
            "responseId": uuid(2),
            "inputId": uuid(3),
            "operationKey": uuid(4),
            "expiresAt": "2026-11-11T00:00:00.000Z",
        }
        GATE.validate_ready(expiry, "expiry")
        for value in ["2026-99-11T00:00:00.000Z", "tomorrow", True, "2026-11-11T00:00:00Z"]:
            with self.assertRaises(GATE.GateError):
                GATE.validate_ready({**expiry, "expiresAt": value}, "expiry")

    def test_private_file_reads_reject_modes_symlinks_hardlinks_empty_and_overflow(self):
        with tempfile.TemporaryDirectory() as temporary:
            p = Path(temporary) / "proof.json"
            p.write_bytes(b"{}")
            p.chmod(0o600)
            self.assertEqual(GATE.read_json(p), {})
            link = p.with_name("link")
            link.symlink_to(p)
            with self.assertRaises(GATE.GateError):
                GATE.read_json(link)
            link.unlink()
            link.hardlink_to(p)
            with self.assertRaises(GATE.GateError):
                GATE.read_json(p)
            link.unlink()
            p.chmod(0o644)
            with self.assertRaises(GATE.GateError):
                GATE.read_json(p)
            p.chmod(0o600)
            for data in [b"", b"x" * 32769]:
                p.write_bytes(data)
                with self.assertRaises(GATE.GateError):
                    GATE.read_json(p)

    def test_fresh_report_and_sidecar_cannot_be_reused_or_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            path = Path(".local/validation/p2-communication/fresh.json")
            target = GATE.target_path(root, path)
            for value in [
                Path("../outside.json"),
                Path(".local/validation/p2-communication/nested/fresh.json"),
                Path(".local/validation/p2-communication/../outside.json"),
            ]:
                with self.assertRaises(GATE.GateError):
                    GATE.target_path(root, value)
            target.with_name("fresh-artifacts").mkdir(mode=0o700)
            with self.assertRaises(GATE.GateError):
                GATE.target_path(root, path)


# Independent fixtures build stored SQL rows from original immutable input/plan bytes.
# They do not call PostgreSQL, SDKs, RTC or any provider.
def canonical(value, *, sorted_keys=False):
    return json.dumps(value, sort_keys=sorted_keys, separators=(",", ":"), ensure_ascii=True)


def sha_text(value):
    import hashlib

    return hashlib.sha256(value.encode()).hexdigest()


def change_payload(row, field, digest_field, change):
    value = json.loads(row[field])
    change(value)
    row[field] = canonical(value)
    row[digest_field] = sha_text(row[field])


def inventory():
    stamp = "2026-11-11T00:00:00.000Z"
    scope = {"tenantId": "native-tenant", "accountId": "native-account"}
    provider = {
        "tenantId": "native-tenant",
        "provider": "livekit",
        "providerAccountId": "local-native",
    }
    result = {
        key: []
        for key in (
            "native_responses",
            "native_observations",
            "communication_settings",
            "inbox",
            "processing_intents",
            "dispatch_plans",
            "native_bindings",
        )
    }
    result["communication_settings"] = [
        {
            "singleton": True,
            "response_count": 10,
            "observation_count": 32,
            "max_responses": 10,
            "max_observations": 32,
            "max_observations_per_response": 4,
        }
    ]
    sequence = 0
    for index in range(10):
        binding, response, generation, input_id, receipt, operation = (
            uuid(n + index) for n in (100, 200, 300, 400, 500, 600)
        )
        event = {
            "schemaVersion": 1,
            "type": "text.received",
            "providerScope": provider,
            "accountScope": scope,
            "conversationId": "native-conversation",
            "caseId": "native-case",
            "eventId": input_id,
            "messageId": input_id,
            "senderId": binding,
            "receivedAt": stamp,
            "channel": "web_chat",
            "body": "INVESTIGATE",
        }
        semantic = {k: v for k, v in event.items() if k != "receivedAt"}
        result["inbox"].append(
            {
                "receipt_id": receipt,
                "tenant_id": scope["tenantId"],
                "provider": "livekit",
                "provider_account_id": provider["providerAccountId"],
                "event_id": input_id,
                "message_id": input_id,
                "account_id": scope["accountId"],
                "conversation_id": "native-conversation",
                "association_epoch": 1,
                "canonical_payload": canonical(semantic, sorted_keys=True),
                "wire_json": canonical(event, sorted_keys=True),
                "acceptance_sequence": index + 1,
                "accepted_at": stamp,
            }
        )
        result["processing_intents"].append(
            {"receipt_id": receipt, "operation_key": operation, "state": "dispatched"}
        )
        plan = {
            "schemaVersion": 1,
            "kind": "investigation",
            "operationKey": operation,
            "scope": scope,
            "caseId": "native-case",
            "caseRevision": "1",
            "conversationId": "native-conversation",
            "message": {
                "receiptId": receipt,
                "eventId": input_id,
                "messageId": input_id,
                "senderId": binding,
                "body": "INVESTIGATE",
            },
        }
        plan_raw = canonical(plan)
        result["dispatch_plans"].append(
            {
                "receipt_id": receipt,
                "operation_key": operation,
                "payload_json": plan_raw,
                "payload_digest": sha_text(plan_raw),
                "prepared_at": stamp,
                "association_epoch": 1,
            }
        )
        anchor = {
            "schemaVersion": 1,
            "responseId": response,
            "generationId": generation,
            "sdkSpeechId": "speech_" + str(index),
            "bindingId": binding,
            "inputId": input_id,
            "receiptId": receipt,
            "operationKey": operation,
            "caseRevision": "1",
            "scope": scope,
            "providerScope": provider,
            "caseId": "native-case",
            "conversationId": "native-conversation",
            "roomId": "room_" + str(index),
            "participantId": "browser_" + str(index),
        }
        bound = {
            "schemaVersion": 1,
            "bindingId": binding,
            "providerScope": provider,
            "scope": scope,
            "caseId": "native-case",
            "conversationId": "native-conversation",
            "roomId": anchor["roomId"],
            "participantId": anchor["participantId"],
            "expiresAt": "2026-11-11T00:03:00.000Z",
        }
        bound_raw = canonical(bound)
        result["native_bindings"].append(
            {
                "binding_id": binding,
                "tenant_id": scope["tenantId"],
                "provider": "livekit",
                "provider_account_id": provider["providerAccountId"],
                "account_id": scope["accountId"],
                "conversation_id": "native-conversation",
                "case_id": "native-case",
                "room_id": bound["roomId"],
                "participant_id": bound["participantId"],
                "bearer_digest": sha_text("synthetic-binding-" + str(index)),
                "canonical_binding": bound_raw,
                "binding_digest": sha_text(bound_raw),
                "published_at": stamp,
                "expires_at": bound["expiresAt"],
                "revoked_at": None,
            }
        )
        anchor_raw = canonical(anchor)
        result["native_responses"].append(
            {
                "response_id": response,
                "generation_id": generation,
                "sdk_speech_id": anchor["sdkSpeechId"],
                "binding_id": binding,
                "input_receipt_id": receipt,
                "operation_key": operation,
                "tenant_id": scope["tenantId"],
                "account_id": scope["accountId"],
                "conversation_id": "native-conversation",
                "case_id": "native-case",
                "canonical_anchor": anchor_raw,
                "anchor_digest": sha_text(anchor_raw),
                "receipt_id": uuid(700 + index),
                "response_sequence": index + 1,
                "accepted_at": stamp,
            }
        )
        # Two responses deliberately have no observations: absence remains unknown.
        if index >= 8:
            continue
        facts = [
            ("agent_sdk", {"type": "generated_complete", "text": "Bounded generated text."}),
            (
                "agent_sdk",
                {
                    "type": "speech_settled",
                    "state": "interrupted" if index == 1 else "completed",
                    "sdkText": None if index == 1 else "Independent SDK observation.",
                },
            ),
            ("browser_client", "started"),
            ("browser_client", "partial" if index == 1 else "completed"),
        ]
        for source, fact in facts:
            sequence += 1
            payload = {"schemaVersion": 1, "eventId": uuid(800 + sequence), "responseId": response}
            if source == "agent_sdk":
                payload.update(
                    generationId=generation, sdkSpeechId=anchor["sdkSpeechId"], fact=fact
                )
            else:
                payload.update(state=fact, observedAudioMs=250)
            raw = canonical(payload)
            result["native_observations"].append(
                {
                    "binding_id": binding,
                    "source": source,
                    "event_id": payload["eventId"],
                    "response_id": response,
                    "canonical_payload": raw,
                    "payload_digest": sha_text(raw),
                    "receipt_id": uuid(900 + sequence),
                    "observation_sequence": (sequence - 1) % 4 + 1,
                    "accepted_at": stamp,
                }
            )
    return result


class IndependentInventoryTests(unittest.TestCase):
    def test_complete_ten_response_thirty_two_observation_inventory_is_accepted_without_mutation(
        self,
    ):
        value = inventory()
        before = copy.deepcopy(value)
        GATE.validate_inventory(value)
        self.assertEqual(value, before)
        self.assertEqual(len(value["native_responses"]), 10)
        self.assertEqual(len(value["native_observations"]), 32)
        self.assertEqual(value["native_observations"][0]["observation_sequence"], 1)
        self.assertEqual(value["native_observations"][4]["observation_sequence"], 1)

    def test_counts_capacity_and_sequences_require_exact_primitives(self):
        for table, column, value in (
            ("communication_settings", "response_count", True),
            ("communication_settings", "observation_count", 32.0),
            ("communication_settings", "max_responses", 11),
            ("communication_settings", "max_observations", 33),
            ("communication_settings", "max_observations_per_response", 5),
            ("native_responses", "response_sequence", True),
            ("native_responses", "response_sequence", 2),
            ("native_observations", "observation_sequence", 1.0),
            ("native_observations", "observation_sequence", 0),
            ("native_observations", "observation_sequence", 2),
        ):
            item = inventory()
            item[table][0][column] = value
            with (
                self.subTest(table=table, column=column, value=value),
                self.assertRaises(GATE.GateError),
            ):
                GATE.validate_inventory(item)

    def test_foreign_recomputed_anchor_or_missing_input_operation_never_passes(self):
        for key, value in (
            ("responseId", uuid(9999)),
            ("bindingId", uuid(9999)),
            ("inputId", uuid(9999)),
            ("operationKey", uuid(9999)),
            ("scope", {"tenantId": "foreign", "accountId": "foreign"}),
            (
                "providerScope",
                {"tenantId": "foreign", "provider": "livekit", "providerAccountId": "foreign"},
            ),
        ):
            item = inventory()
            change_payload(
                item["native_responses"][0],
                "canonical_anchor",
                "anchor_digest",
                lambda a, key=key, value=value: a.update({key: value}),
            )
            with self.subTest(key=key), self.assertRaises(GATE.GateError):
                GATE.validate_inventory(item)
        for table, column in (("inbox", "receipt_id"), ("processing_intents", "operation_key")):
            item = inventory()
            item[table][0][column] = uuid(9999)
            with self.subTest(table=table), self.assertRaises(GATE.GateError):
                GATE.validate_inventory(item)

    def test_input_sql_scope_provider_and_event_columns_match_original_canonical_wire(self):
        for key in (
            "tenant_id",
            "provider",
            "provider_account_id",
            "account_id",
            "conversation_id",
            "event_id",
            "message_id",
        ):
            item = inventory()
            item["inbox"][0][key] = "foreign"
            with self.subTest(column=key), self.assertRaises(GATE.GateError):
                GATE.validate_inventory(item)

    def test_input_recomputed_semantic_bytes_cannot_diverge_from_accepted_plan(self):
        for key, value in (
            ("body", "Different original text"),
            ("type", "delivery.reported"),
            ("channel", "sms"),
            ("schemaVersion", True),
            ("extra", "unsupported"),
        ):
            item = inventory()
            original = item["inbox"][0]
            payload = json.loads(original["wire_json"])
            payload[key] = value
            original["wire_json"] = canonical(payload, sorted_keys=True)
            original["canonical_payload"] = canonical(
                {k: v for k, v in payload.items() if k != "receivedAt"}, sorted_keys=True
            )
            with self.subTest(key=key), self.assertRaises(GATE.GateError):
                GATE.validate_inventory(item)

    def test_plan_scope_message_identity_revision_and_digest_match_response_and_input(self):
        changes = [
            lambda p: p.update(scope={"tenantId": "foreign", "accountId": "foreign"}),
            lambda p: p.update(operationKey=uuid(9999)),
            lambda p: p.update(caseRevision="2"),
            lambda p: p.update(caseId="foreign"),
            lambda p: p.update(conversationId="foreign"),
            lambda p: p["message"].update(eventId=uuid(9999)),
            lambda p: p["message"].update(receiptId=uuid(9999)),
            lambda p: p["message"].update(body="different"),
            lambda p: p.update(kind="confirmation"),
        ]
        for index, change in enumerate(changes):
            item = inventory()
            change_payload(item["dispatch_plans"][0], "payload_json", "payload_digest", change)
            with self.subTest(change=index), self.assertRaises(GATE.GateError):
                GATE.validate_inventory(item)
        item = inventory()
        item["dispatch_plans"][0]["payload_digest"] = "0" * 64
        with self.assertRaises(GATE.GateError):
            GATE.validate_inventory(item)

    def test_missing_duplicate_plan_and_undispatched_intent_are_not_original_preparation(self):
        for kind in ("missing", "duplicate", "operation", "pending"):
            item = inventory()
            if kind == "missing":
                item["dispatch_plans"].pop()
            elif kind == "duplicate":
                item["dispatch_plans"].append(copy.deepcopy(item["dispatch_plans"][0]))
            elif kind == "operation":
                item["dispatch_plans"][0]["operation_key"] = uuid(9999)
            else:
                item["processing_intents"][0]["state"] = "pending"
            with self.subTest(kind=kind), self.assertRaises(GATE.GateError):
                GATE.validate_inventory(item)

    def test_source_specific_closed_payloads_cannot_be_relabelled_with_recomputed_digest(self):
        changes = [
            (0, lambda p: p.update(schemaVersion=True)),
            (0, lambda p: p.update(extra="unsupported")),
            (0, lambda p: p.update(fact={"type": "generated_complete", "text": ""})),
            (1, lambda p: p["fact"].update(state="delivered")),
            (2, lambda p: p.update(observedAudioMs=True)),
            (2, lambda p: p.update(state="heard")),
            (2, lambda p: p.update(generationId=uuid(9999))),
        ]
        for index, change in changes:
            item = inventory()
            change_payload(
                item["native_observations"][index], "canonical_payload", "payload_digest", change
            )
            with (
                self.subTest(index=index, change=changes.index((index, change))),
                self.assertRaises(GATE.GateError),
            ):
                GATE.validate_inventory(item)
        item = inventory()
        item["native_observations"][0]["source"] = "browser_client"
        with self.assertRaises(GATE.GateError):
            GATE.validate_inventory(item)

    def test_exact_original_observation_identity_and_per_response_caps_are_enforced(self):
        for kind in (
            "receipt",
            "event",
            "binding",
            "response",
            "generation",
            "speech",
            "source",
            "digest",
        ):
            item = inventory()
            row = item["native_observations"][0]
            if kind == "receipt":
                row["receipt_id"] = item["native_observations"][1]["receipt_id"]
            elif kind == "event":
                row["event_id"] = item["native_observations"][1]["event_id"]
                change_payload(
                    row,
                    "canonical_payload",
                    "payload_digest",
                    lambda p, event_id=row["event_id"]: p.update(eventId=event_id),
                )
            elif kind in ("generation", "speech"):
                change_payload(
                    row,
                    "canonical_payload",
                    "payload_digest",
                    lambda p, kind=kind: p.update(
                        {"generationId" if kind == "generation" else "sdkSpeechId": uuid(9999)}
                    ),
                )
            elif kind == "digest":
                row["payload_digest"] = "0" * 64
            elif kind == "source":
                row["source"] = "provider"
            else:
                row["binding_id" if kind == "binding" else "response_id"] = uuid(9999)
            with self.subTest(kind=kind), self.assertRaises(GATE.GateError):
                GATE.validate_inventory(item)
        item = inventory()
        target = item["native_responses"][0]
        row = item["native_observations"][6]
        row["response_id"], row["binding_id"] = target["response_id"], target["binding_id"]
        change_payload(
            row,
            "canonical_payload",
            "payload_digest",
            lambda p: p.update(responseId=target["response_id"]),
        )
        with self.assertRaises(GATE.GateError):
            GATE.validate_inventory(item)


class IndependentResourceBoundaryTests(unittest.TestCase):
    def test_ready_malformed_array_members_use_fixed_gate_errors(self):
        valid = {
            "schemaVersion": 1,
            "responseIds": [uuid(i) for i in range(1, 5)],
            "eventIds": [uuid(i) for i in range(5, 9)],
            "maximumOperations": 4,
            "maximumConnections": 2,
        }
        for key in ("responseIds", "eventIds"):
            for value in (
                None,
                {},
                [None] * 4,
                [{}, uuid(2), uuid(3), uuid(4)],
                [[1], uuid(2), uuid(3), uuid(4)],
            ):
                with self.subTest(key=key, value=value), self.assertRaises(GATE.GateError):
                    GATE.validate_ready({**valid, key: value}, "capacity")

    def test_real_owned_child_capture_then_actual_kill_reap_and_no_false_kill(self):
        import signal
        import sys
        import time

        from harness.process_control import ProcessExited

        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            children = GATE.Children(work, time.monotonic() + 8)
            self.addCleanup(children.close)
            self.assertEqual(
                children.call(
                    "normal",
                    [sys.executable, "-I", "-c", "print('bounded')"],
                    {"PATH": os.defpath},
                    cwd=work,
                ),
                b"bounded\n",
            )
            barrier = GATE.FileBarrier(work, "owned_wait")
            code = (
                "import os,time\n"
                f"p={str(work / 'owned_wait.reached')!r}\n"
                "f=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)\n"
                "os.write(f,(str(os.getpid())+'\\n').encode());os.close(f)\n"
                "time.sleep(10)\n"
            )
            child = children.start(
                "held", [sys.executable, "-I", "-c", code], {"PATH": os.defpath}, cwd=work
            )
            child.wait_for_barrier(barrier, timeout=3)
            proof = children.kill(child)
            self.assertEqual(
                proof, {"pid": child.pid, "returncode": -signal.SIGKILL, "actualSigkill": True}
            )
            self.assertEqual(child.returncode, -signal.SIGKILL)
            with self.assertRaises(ProcessExited):
                children.kill(child)
            children.close()
            self.assertFalse(any(c.cleanup_failed for c in children.children))

    def test_real_output_overflow_cannot_release_owned_cleanup(self):
        import sys
        import time

        from harness.process_control import ProcessOutputLimit

        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            children = GATE.Children(work, time.monotonic() + 8)
            child = children.start(
                "overflow",
                [sys.executable, "-I", "-c", "import os,time;os.write(1,b'x'*4097);time.sleep(10)"],
                {"PATH": os.defpath},
                cwd=work,
            )
            try:
                with self.assertRaises(ProcessOutputLimit):
                    children.finish(child)
            finally:
                children.close()
            self.assertIsNotNone(child.returncode)
            self.assertFalse(child.cleanup_failed)
            self.assertLessEqual((child.output_directory / "stdout.bin").stat().st_size, 4096)

    def test_cleanup_attempts_every_owner_and_retains_incomplete_state(self):
        import time
        from types import SimpleNamespace

        calls = []

        def close(name, fail=False):
            calls.append(name)
            if fail:
                raise RuntimeError("synthetic_close_failure")

        with tempfile.TemporaryDirectory() as temporary:
            children = GATE.Children(Path(temporary).resolve(), time.monotonic() + 2)
            children.children = [
                SimpleNamespace(close=lambda: close("first"), cleanup_failed=False, returncode=0),
                SimpleNamespace(
                    close=lambda: close("second", True), cleanup_failed=True, returncode=None
                ),
                SimpleNamespace(close=lambda: close("third"), cleanup_failed=False, returncode=0),
            ]
            with self.assertRaises(GATE.GateError) as caught:
                children.close()
            self.assertEqual(caught.exception.code, "cleanup_incomplete")
            self.assertEqual(calls, ["third", "second", "first"])

    def test_child_and_capture_aggregate_caps_are_fail_closed(self):
        import time

        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            children = GATE.Children(work, time.monotonic() + 1)
            children.count = 32
            with self.assertRaises(GATE.GateError):
                children.start("too-many", ["not-executed"], {}, cwd=work)
            children.count = 0
            with self.assertRaises(GATE.GateError):
                children.start("../unsafe", ["not-executed"], {}, cwd=work)
            children.captured = 262144
            with patch.object(GATE.native.Children, "finish", return_value=b"x"):
                # The superclass owns accumulation; simulate one more captured byte.
                children.captured += 1
                with self.assertRaises(GATE.GateError):
                    children.finish(None)

    def test_ready_invalidity_stops_before_any_sql_lock_or_release(self):
        import time
        from types import SimpleNamespace

        child = SimpleNamespace(
            wait_for_barrier=lambda *a, **k: None,
            release_barrier=lambda *a: self.fail("invalid_ready_released"),
        )
        children = SimpleNamespace(deadline=time.monotonic() + 2)
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            with (
                patch.object(GATE, "read_json", return_value={"schemaVersion": 1}),
                self.assertRaises(GATE.GateError),
            ):
                GATE.lock_schedule(
                    children,
                    child,
                    "capacity",
                    {"communication_capacity_ready": object()},
                    work,
                    None,
                    "p2_playback_" + "a" * 32,
                    work,
                )


class IndependentPreparationBoundaryTests(unittest.TestCase):
    def test_pending_anchor_without_plan_is_valid_observation_not_completed_preparation(self):
        value = inventory()
        # Captured LLM anchor publication precedes dispatch-plan commitment.
        value["processing_intents"][0]["state"] = "pending"
        receipt = value["processing_intents"][0]["receipt_id"]
        value["dispatch_plans"] = [p for p in value["dispatch_plans"] if p["receipt_id"] != receipt]
        GATE.validate_inventory(value)


def backend_identity(phase="capacity"):
    return {
        "schemaVersion": 1,
        "phase": phase,
        "processId": 12345,
        "schema": "p2_playback_" + "a" * 32,
        "backendIds": [81, 82] if phase == "capacity" else [81],
    }


class IndependentBackendIdentityTests(unittest.TestCase):
    def validate(self, value, phase="capacity", **changes):
        return GATE.validated_backend_identity(
            encoded(value),
            phase=phase,
            schema=changes.get("schema", "p2_playback_" + "a" * 32),
            process_id=changes.get("process_id", 12345),
        )

    def test_exact_owned_backend_metadata_for_both_schedules(self):
        for phase, expected in (("capacity", (81, 82)), ("expiry", (81,))):
            with self.subTest(phase=phase):
                self.assertEqual(self.validate(backend_identity(phase), phase), expected)

    def test_foreign_process_schema_phase_or_extra_authority_cannot_select_waiters(self):
        for key, value in (
            ("schemaVersion", True),
            ("phase", "expiry"),
            ("processId", 99999),
            ("processId", True),
            ("schema", "p2_playback_" + "b" * 32),
            ("query", "untrusted query text"),
        ):
            item = backend_identity()
            item[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(GATE.GateError):
                self.validate(item)
        for key in backend_identity():
            item = backend_identity()
            del item[key]
            with self.subTest(missing=key), self.assertRaises(GATE.GateError):
                self.validate(item)

    def test_backend_count_order_unique_positive_and_primitive_types_are_exact(self):
        for values in (
            None,
            {},
            [],
            [81],
            [81, 81],
            [82, 81],
            [0, 82],
            [-1, 82],
            [True, 82],
            [81.0, 82],
            ["81", 82],
            [{}, 82],
            [81, 82, 83],
        ):
            with self.subTest(values=values), self.assertRaises(GATE.GateError):
                self.validate({**backend_identity(), "backendIds": values})
        with self.assertRaises(GATE.GateError):
            self.validate({**backend_identity("expiry"), "backendIds": [81, 82]}, "expiry")

    def test_backend_protocol_rejects_duplicate_alias_json_nonobject_and_oversize(self):
        raw = encoded(backend_identity())
        for value in (
            raw.replace(b'"schemaVersion": 1', b'"schemaVersion": 1,"\\u0073chemaVersion": 1'),
            b"[]",
            b"null",
            b"\xff",
            raw[:-1],
            b" " * 1024 + raw,
        ):
            with self.subTest(raw_length=len(value)), self.assertRaises(GATE.GateError):
                GATE.validated_backend_identity(
                    value, phase="capacity", schema="p2_playback_" + "a" * 32, process_id=12345
                )


class IndependentScopedSequenceTests(unittest.TestCase):
    def test_response_sequence_is_local_to_account_conversation_while_profile_count_is_global(self):
        value = inventory()
        index = 9
        response = value["native_responses"][index]
        response["account_id"] = "another-account"
        response["response_sequence"] = 1
        change_payload(
            response,
            "canonical_anchor",
            "anchor_digest",
            lambda a: a["scope"].update(accountId="another-account"),
        )
        original = value["inbox"][index]
        original["account_id"] = "another-account"
        event = json.loads(original["wire_json"])
        event["accountScope"]["accountId"] = "another-account"
        original["wire_json"] = canonical(event, sorted_keys=True)
        original["canonical_payload"] = canonical(
            {k: v for k, v in event.items() if k != "receivedAt"}, sorted_keys=True
        )
        binding = value["native_bindings"][index]
        binding["account_id"] = "another-account"
        change_payload(
            binding,
            "canonical_binding",
            "binding_digest",
            lambda b: b["scope"].update(accountId="another-account"),
        )
        change_payload(
            value["dispatch_plans"][index],
            "payload_json",
            "payload_digest",
            lambda p: p["scope"].update(accountId="another-account"),
        )
        GATE.validate_inventory(value)


class IndependentRetainedBindingTests(unittest.TestCase):
    def test_recomputed_anchor_room_and_participant_must_match_original_binding(self):
        for key in ("roomId", "participantId"):
            value = inventory()
            change_payload(
                value["native_responses"][0],
                "canonical_anchor",
                "anchor_digest",
                lambda a, key=key: a.update({key: "foreign"}),
            )
            with self.subTest(key=key), self.assertRaises(GATE.GateError):
                GATE.validate_inventory(value)

    def test_retained_binding_row_canonical_identity_digest_and_existence_are_joined(self):
        for kind in ("missing", "duplicate", "room", "scope", "digest", "canonical"):
            value = inventory()
            row = value["native_bindings"][0]
            if kind == "missing":
                value["native_bindings"].pop(0)
            elif kind == "duplicate":
                value["native_bindings"].append(copy.deepcopy(row))
            elif kind == "room":
                row["room_id"] = "foreign"
            elif kind == "scope":
                row["account_id"] = "foreign"
            elif kind == "digest":
                row["binding_digest"] = "0" * 64
            else:
                change_payload(
                    row, "canonical_binding", "binding_digest", lambda b: b.update(roomId="foreign")
                )
            with self.subTest(kind=kind), self.assertRaises(GATE.GateError):
                GATE.validate_inventory(value)


class IndependentAbandonedWaiterProofTests(unittest.TestCase):
    def test_one_actual_abandoned_waiter_is_required_without_claiming_sql_ownership(self):
        value = {
            "schemaVersion": 1,
            "admittedOperations": 4,
            "abandonedWaiters": 1,
            "settledOperations": 4,
            "fifthRejected": "Overloaded",
            "laterProgress": True,
        }
        self.assertEqual(GATE.validated_capacity(encoded(value)), value)
        missing = dict(value)
        del missing["abandonedWaiters"]
        for wrong in [
            missing,
            *({**value, "abandonedWaiters": v} for v in (None, False, True, 0, 2, 1.0, "1")),
            {**value, "actualSqlWaiters": 2},
        ]:
            with self.subTest(value=wrong), self.assertRaises(GATE.GateError):
                GATE.validated_capacity(encoded(wrong))
