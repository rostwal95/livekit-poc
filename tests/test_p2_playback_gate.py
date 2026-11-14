"""Independent playback gate negatives; no settings, PostgreSQL, RTC or providers."""

import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "p2_playback_gate_test", ROOT / "local-setup/scripts/p2_playback_check.py"
)
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)
CASES = (
    "normal_source_qualified_output",
    "measured_midpoint_interruption_partial_evidence",
    "disconnect_missing_playback_completion_unknown",
)
TEXT = "The workflow panel shows the latest durable state."
STAMP = "2026-11-11T00:00:00.000Z"


def uid(n):
    return f"{n:08d}-1111-4111-8111-111111111111"


def wire(value, *, sorted_keys=False):
    return json.dumps(value, sort_keys=sorted_keys, separators=(",", ":"), ensure_ascii=True)


def encoded(value):
    return wire(value).encode()


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def browser_report():
    rows = []
    for i in range(3):
        rows.append(
            {
                "responseId": uid(10 + i),
                "generationId": uid(20 + i),
                "inputId": uid(30 + i),
                "operationKey": uid(40 + i),
                "sdkSpeechId": f"speech_{i}",
                "observationCount": (4, 4, 2)[i],
                "generated_observed": True,
                "sdk_state": ("completed", "interrupted", "completed")[i],
                "browser_state": ("completed_reported", "partial", "unknown")[i],
                "conflicted": False,
                "observed_audio_ms": (1900, 1100, 1900)[i],
                "sampled_audio_ms": (2400, 1450, 2400)[i],
            }
        )
    return {
        "schemaVersion": 1,
        "status": "passed",
        "mode": "local_scripted_p2_playback_browser",
        "fixtureDurationMs": 2058.25,
        "actualBrowserAudio": True,
        "physicalHearingClaimed": False,
        "clientReportsWithheldForMissing": True,
        "evidenceReadRecoveryVerified": True,
        "cleanupComplete": True,
        "pageErrors": 0,
        "unexpectedNetworkRequests": 0,
        "interruptTriggerAudioMs": 900,
        "rows": rows,
    }


def report():
    return {
        "schema_version": 1,
        "status": "passed",
        "mode": "local_scripted_p2_playback",
        "tests": 3,
        "passed": 3,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "cleanup_complete": True,
        "case_results": [{"name": n, "status": "passed", "code": "ok"} for n in CASES],
        "provider_calls": False,
        "inference_mode": "scripted",
        "schema_version_observed": 7,
        "native_inputs": 3,
        "operation_acceptances": 3,
        "responses": 3,
        "sdk_observations": 6,
        "browser_observations": 4,
        "playwright_tests": 1,
        "physical_hearing_claimed": False,
        "human_acknowledgement_claimed": False,
        "room_rehydration_claimed": False,
        "duration_seconds": 30.5,
        "node_version": "24.22.2",
        "child_commands": 9,
        "proofs": {
            name: {"bytes": 100, "sha256": "a" * 64}
            for name in (
                "owner_snapshot",
                "browser",
                "node",
                "python",
                "fixture",
                "node_ownership",
                "python_source",
            )
        },
    }


def python_report():
    return {
        "schemaVersion": 1,
        "status": "passed",
        "mode": "serve",
        "cleanupComplete": True,
        "sdkClosed": True,
        "roomClosed": True,
        "httpClosed": True,
        "metrics": {
            "activeIntakes": 0,
            "activePrepare": 0,
            "activeReaders": 0,
            "activeReplyObservers": 0,
            "activeVoiceWork": 0,
            "defaultReplyInvocations": 0,
            "durableAcceptCalls": 3,
            "genuineFinalSnapshots": 0,
            "nativeGeneratedReplies": 2,
            "nativeGenerationAttempts": 3,
            "nativeInputsAccepted": 3,
            "nativeInputsRejected": 0,
            "nativeInputsReplayed": 0,
            "observerDropped": 0,
            "observerFailures": 0,
            "observerPending": 0,
            "sdkCloseAllocationFailed": 0,
            "sdkSessionClosed": 1,
            "textStreamsSeen": 3,
            "voiceCaptures": 0,
            "voiceCommits": 0,
        },
        "communicationMetrics": {
            "activeNodes": 0,
            "activeProducers": 0,
            "activePublications": 0,
            "activeReports": 0,
            "anchorsKnown": 3,
            "browserReportsKnown": 4,
            "generatedFactsKnown": 3,
            "observerFailures": 0,
            "rejectedReports": 0,
            "sdkFactsKnown": 3,
            "unknownAcknowledgements": 0,
        },
    }


def node_report(mode):
    value = {
        "schemaVersion": 1,
        "status": "passed",
        "mode": mode,
        "storageVersion": 7,
        "nodeVersion": "24.22.2",
    }
    if mode == "media-seed":
        value.update(nativeBindings=1, nativeInputs=0)
    if mode == "media-cleanup":
        value.update(storageVersion=0, ownedSchemaAbsent=True, cleanupComplete=True)
    if mode == "media-serve":
        value.update(
            cleanupComplete=True,
            metrics={
                "accepted": 3,
                "active": 0,
                "dispatched": 3,
                "driver": 0,
                "handlers": 0,
                "intakes": 0,
                "observerPending": 0,
                "replayed": 0,
                "sockets": 0,
            },
            communicationMetrics={
                "capacityRejected": 0,
                "identityConflicts": 0,
                "observationsAccepted": 10,
                "observationsReplayed": 0,
                "rejected": 0,
                "responsesAccepted": 3,
                "responsesReplayed": 0,
                "telemetryFailures": 0,
                "unknownAcknowledgements": 0,
            },
        )
    if mode == "media-verify":
        value.update(
            browserCompletedReported=1,
            browserObservations=4,
            browserPartial=1,
            browserUnknown=1,
            exactIdentityJoins=True,
            nativeInputs=3,
            noAcknowledgements=True,
            operationAcceptances=3,
            preparedPlans=3,
            processingIntents=3,
            responses=3,
            sdkCompleted=2,
            sdkInterrupted=1,
            sdkObservations=6,
            totalObservations=10,
        )
    return value


def owner_snapshot():
    fixture = {
        "bindingId": uid(1),
        "roomId": "room",
        "participantId": "browser",
        "scope": {"tenantId": "tenant", "accountId": "account"},
        "providerScope": {
            "tenantId": "tenant",
            "provider": "livekit",
            "providerAccountId": "local",
        },
        "caseId": "case",
        "conversationId": "conversation",
    }
    browser = browser_report()
    snapshot = {
        name: []
        for name in (
            "native_responses",
            "native_observations",
            "communication_settings",
            "inbox",
            "processing_intents",
            "dispatch_plans",
        )
    }
    snapshot["communication_settings"].append({"response_count": 3, "observation_count": 10})
    sequence = 0
    for i, row in enumerate(browser["rows"]):
        receipt = uid(50 + i)
        event = {
            "schemaVersion": 1,
            "eventId": row["inputId"],
            "providerScope": fixture["providerScope"],
            "accountScope": fixture["scope"],
            "conversationId": "conversation",
            "caseId": "case",
            "receivedAt": STAMP,
            "channel": "web_chat",
            "messageId": row["inputId"],
            "senderId": fixture["bindingId"],
            "body": "INVESTIGATE",
            "type": "text.received",
        }
        canonical_event = wire(
            {k: v for k, v in event.items() if k != "receivedAt"}, sorted_keys=True
        )
        snapshot["inbox"].append(
            {
                "receipt_id": receipt,
                "tenant_id": "tenant",
                "provider": "livekit",
                "provider_account_id": "local",
                "event_id": row["inputId"],
                "message_id": row["inputId"],
                "account_id": "account",
                "conversation_id": "conversation",
                "association_epoch": 1,
                "canonical_payload": canonical_event,
                "wire_json": wire(event, sorted_keys=True),
                "acceptance_sequence": i + 1,
                "accepted_at": STAMP,
            }
        )
        snapshot["processing_intents"].append(
            {"receipt_id": receipt, "operation_key": row["operationKey"], "state": "dispatched"}
        )
        plan = {
            "schemaVersion": 1,
            "kind": "investigation",
            "operationKey": row["operationKey"],
            "scope": fixture["scope"],
            "caseId": "case",
            "caseRevision": "1",
            "conversationId": "conversation",
            "message": {
                "receiptId": receipt,
                "eventId": row["inputId"],
                "messageId": row["inputId"],
                "senderId": fixture["bindingId"],
                "body": "INVESTIGATE",
            },
        }
        payload = wire(plan)
        snapshot["dispatch_plans"].append(
            {
                "receipt_id": receipt,
                "operation_key": row["operationKey"],
                "payload_json": payload,
                "payload_digest": digest(payload),
                "prepared_at": STAMP,
                "association_epoch": 1,
            }
        )
        anchor = {
            "schemaVersion": 1,
            "responseId": row["responseId"],
            "generationId": row["generationId"],
            "sdkSpeechId": row["sdkSpeechId"],
            "bindingId": fixture["bindingId"],
            "inputId": row["inputId"],
            "receiptId": receipt,
            "operationKey": row["operationKey"],
            "caseRevision": "1",
            "scope": fixture["scope"],
            "providerScope": fixture["providerScope"],
            "caseId": "case",
            "conversationId": "conversation",
            "roomId": fixture["roomId"],
            "participantId": fixture["participantId"],
        }
        canonical_anchor = wire(anchor)
        snapshot["native_responses"].append(
            {
                "response_id": row["responseId"],
                "generation_id": row["generationId"],
                "sdk_speech_id": row["sdkSpeechId"],
                "binding_id": fixture["bindingId"],
                "input_receipt_id": receipt,
                "operation_key": row["operationKey"],
                "tenant_id": "tenant",
                "account_id": "account",
                "conversation_id": "conversation",
                "case_id": "case",
                "canonical_anchor": canonical_anchor,
                "anchor_digest": digest(canonical_anchor),
                "receipt_id": uid(60 + i),
                "response_sequence": i + 1,
                "accepted_at": STAMP,
            }
        )
        sdk_facts = [
            {"type": "generated_complete", "text": TEXT},
            {
                "type": "speech_settled",
                "state": "interrupted" if i == 1 else "completed",
                "sdkText": "Synchronized observation",
            },
        ]
        payloads = [
            (
                "agent_sdk",
                {
                    "schemaVersion": 1,
                    "eventId": uid(70 + sequence + j),
                    "responseId": row["responseId"],
                    "generationId": row["generationId"],
                    "sdkSpeechId": row["sdkSpeechId"],
                    "fact": fact,
                },
            )
            for j, fact in enumerate(sdk_facts)
        ]
        client_states = (
            ("started", "completed") if i == 0 else ("started", "partial") if i == 1 else ()
        )
        for state in client_states:
            payloads.append(
                (
                    "browser_client",
                    {
                        "schemaVersion": 1,
                        "eventId": uid(90 + sequence + len(payloads)),
                        "responseId": row["responseId"],
                        "state": state,
                        "observedAudioMs": 900 if state == "partial" else 200,
                    },
                )
            )
        for local_sequence, (source, payload_value) in enumerate(payloads, start=1):
            sequence += 1
            canonical_payload = wire(payload_value)
            snapshot["native_observations"].append(
                {
                    "binding_id": fixture["bindingId"],
                    "source": source,
                    "event_id": payload_value["eventId"],
                    "response_id": row["responseId"],
                    "canonical_payload": canonical_payload,
                    "payload_digest": digest(canonical_payload),
                    "receipt_id": uid(200 + sequence),
                    "observation_sequence": local_sequence,
                    "accepted_at": STAMP,
                }
            )
    return snapshot, browser, fixture


class PlaybackGateContractTests(unittest.TestCase):
    def test_exact_three_case_nine_child_report(self):
        self.assertEqual(tuple(GATE.CASE_NAMES), CASES)
        self.assertEqual(GATE.validated_report(encoded(report())), report())

    def test_report_rejects_missing_extra_reordered_or_nonpassing_cases(self):
        for change in (
            lambda v: v["case_results"].pop(),
            lambda v: v["case_results"].reverse(),
            lambda v: v["case_results"][0].update(status="skipped"),
            lambda v: v.update(human_acknowledgement_claimed=True),
            lambda v: v.update(child_commands=8),
            lambda v: v.update(child_commands=10),
            lambda v: v.update(child_commands=True),
            lambda v: v.update(duration_seconds=float("inf")),
        ):
            value = report()
            change(value)
            with self.subTest(value=value), self.assertRaises(GATE.GateError):
                GATE.validated_report(json.dumps(value).encode())

    def test_duplicate_invalid_utf8_primitive_and_nonfinite_reports_reject(self):
        data = encoded(report())
        for raw in (
            data.replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1'),
            b"[]",
            b"true",
            b"null",
            b"\xff",
            b'{"value":NaN}',
            b" " * 32769,
        ):
            with self.subTest(raw=raw[:80]), self.assertRaises(GATE.GateError):
                GATE.validated_report(raw)

    def test_proof_descriptors_reject_false_primitives_and_unsafe_digest(self):
        for replacement in (
            {"bytes": True, "sha256": "a" * 64},
            {"bytes": 0, "sha256": "a" * 64},
            {"bytes": 2097153, "sha256": "a" * 64},
            {"bytes": 1, "sha256": "A" * 64},
        ):
            value = report()
            value["proofs"]["browser"] = replacement
            with self.subTest(replacement=replacement), self.assertRaises(GATE.GateError):
                GATE.validated_report(encoded(value))

    def test_exact_python_twenty_one_plus_eleven_metrics(self):
        value = python_report()
        self.assertEqual(len(value["metrics"]), 21)
        self.assertEqual(len(value["communicationMetrics"]), 11)
        self.assertEqual(GATE.validated_python(encoded(value)), value)
        for section, key, replacement in (
            ("metrics", "activePrepare", 1),
            ("metrics", "defaultReplyInvocations", 1),
            ("metrics", "nativeGenerationAttempts", 4),
            ("communicationMetrics", "activeNodes", 1),
            ("communicationMetrics", "sdkFactsKnown", 2),
            ("communicationMetrics", "anchorsKnown", True),
        ):
            wrong = copy.deepcopy(value)
            wrong[section][key] = replacement
            with self.subTest(section=section, key=key), self.assertRaises(GATE.GateError):
                GATE.validated_python(encoded(wrong))

    def test_exact_node_nine_plus_nine_metrics_and_all_closed_modes(self):
        for mode in ("media-install", "media-seed", "media-serve", "media-verify", "media-cleanup"):
            self.assertEqual(
                GATE.validated_stage(encoded(node_report(mode)), mode), node_report(mode)
            )
        value = node_report("media-serve")
        self.assertEqual(len(value["metrics"]), 9)
        self.assertEqual(len(value["communicationMetrics"]), 9)
        value["communicationMetrics"]["observationsAccepted"] = 9
        with self.assertRaises(GATE.GateError):
            GATE.validated_stage(encoded(value), "media-serve")
        with self.assertRaises(GATE.GateError):
            GATE.validated_stage(encoded(node_report("media-seed")), "media-verify")

    def test_browser_trigger_and_final_partial_are_separate_measured_facts(self):
        value = browser_report()
        self.assertNotEqual(value["interruptTriggerAudioMs"], value["rows"][1]["observed_audio_ms"])
        self.assertEqual(GATE.validated_browser(encoded(value)), value)
        for change in (
            lambda v: v.update(interruptTriggerAudioMs=True),
            lambda v: v.update(interruptTriggerAudioMs=600),
            lambda v: v["rows"][1].update(observed_audio_ms=899),
            lambda v: v["rows"][1].update(observed_audio_ms=1900),
            lambda v: v["rows"][2].update(browser_state="completed_reported"),
            lambda v: v["rows"][0].update(sampled_audio_ms=1),
            lambda v: v["rows"][2].update(generationId=v["rows"][0]["generationId"]),
        ):
            wrong = copy.deepcopy(value)
            change(wrong)
            with self.subTest(wrong=wrong), self.assertRaises(GATE.GateError):
                GATE.validated_browser(encoded(wrong))

    def test_child_roles_exclude_provider_and_opposite_database_credential(self):
        common = {
            "P2_COMM_DIRECTORY": "/private/synthetic",
            "P2_COMM_SCHEMA": "p2_playback_" + "a" * 32,
            "P2_COMM_PG_PORT": "15432",
        }
        values = {
            "POSTGRES_PASSWORD": "runtime_synthetic",
            "POSTGRES_MIGRATION_PASSWORD": "owner_synthetic",
            "OPENAI_API_KEY": "do_not_forward",
        }
        with patch.object(GATE.core, "base_environment", return_value={}):
            for mode in GATE.MODES:
                env = GATE.child_environment(values, common, mode)
                self.assertNotIn("OPENAI_API_KEY", env)
                wrong = (
                    dict(env, P2_COMM_RUNTIME_PASSWORD="runtime")
                    if mode in GATE.OWNER_MODES
                    else dict(env, P2_COMM_OWNER_PASSWORD="owner")
                )
                with self.subTest(mode=mode), self.assertRaises(GATE.GateError):
                    GATE.validate_child_environment(wrong, mode)
                for key, replacement in (
                    ("P2_COMM_DIRECTORY", "relative"),
                    ("P2_COMM_SCHEMA", "public"),
                    ("P2_COMM_PG_PORT", "80"),
                ):
                    bad = dict(env)
                    bad[key] = replacement
                    with self.subTest(mode=mode, key=key), self.assertRaises(GATE.GateError):
                        GATE.validate_child_environment(bad, mode)

    def test_private_target_rejects_existing_report_proof_and_symlink_parent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = Path(".local/validation/p2-playback/test.json")
            target = GATE.target_path(root, path)
            target.write_text("original")
            with self.assertRaises(GATE.GateError):
                GATE.target_path(root, path)
            target.unlink()
            target.with_name("test-artifacts").mkdir()
            with self.assertRaises(GATE.GateError):
                GATE.target_path(root, path)
            for wrong in (
                Path("/tmp/out.json"),
                Path(".local/validation/p2-playback/../out.json"),
                Path(".local/validation/p2-playback/BAD.json"),
            ):
                with self.subTest(path=wrong), self.assertRaises(GATE.GateError):
                    GATE.target_path(root, wrong)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            elsewhere = root / "elsewhere"
            elsewhere.mkdir()
            (root / ".local").symlink_to(elsewhere, target_is_directory=True)
            with self.assertRaises(GATE.GateError):
                GATE.target_path(root, Path(".local/validation/p2-playback/test.json"))

    def test_fixture_waveform_proof_uses_actual_bytes_and_explicit_downsampled_frame_count(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "projects/channel-continuity/examples/assets/native-status.wav"
            path.parent.mkdir(parents=True)
            with wave.open(str(path), "wb") as clip:
                clip.setnchannels(1)
                clip.setsampwidth(2)
                clip.setframerate(16000)
                clip.writeframes(b"\x10\x27" * 65864)
            proof = GATE.fixture_proof(root)
            self.assertEqual(proof["sourceSha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(proof["renderedFrames"], 32932)
            self.assertEqual(proof["durationMs"], 2058.25)
            self.assertEqual(
                proof["semantics"],
                "continuous_source_response_window_not_physical_speech_or_hearing",
            )
            path.unlink()
            path.symlink_to(root / "missing.wav")
            with self.assertRaises(GATE.GateError):
                GATE.fixture_proof(root)


class PlaybackOwnerJoinTests(unittest.TestCase):
    def test_synthetic_snapshot_has_independent_raw_input_plan_anchor_and_source_joins(self):
        snapshot, browser, fixture = owner_snapshot()
        GATE.validate_owner_snapshot(snapshot, browser, fixture)
        self.assertEqual(len(snapshot["native_observations"]), 10)

    def test_owner_rejects_original_input_identity_or_scope_changes(self):
        for field, replacement in (
            ("event_id", uid(999)),
            ("message_id", uid(999)),
            ("account_id", "foreign"),
            ("provider", "fake_sms"),
        ):
            snapshot, browser, fixture = owner_snapshot()
            snapshot["inbox"][0][field] = replacement
            with self.subTest(field=field), self.assertRaises(GATE.GateError):
                GATE.validate_owner_snapshot(snapshot, browser, fixture)

    def test_owner_rejects_validly_encoded_but_changed_original_input_body(self):
        snapshot, browser, fixture = owner_snapshot()
        row = snapshot["inbox"][0]
        event = json.loads(row["wire_json"])
        event["body"] = "DIFFERENT"
        row["wire_json"] = wire(event, sorted_keys=True)
        row["canonical_payload"] = wire(
            {k: v for k, v in event.items() if k != "receivedAt"}, sorted_keys=True
        )
        with self.assertRaises(GATE.GateError):
            GATE.validate_owner_snapshot(snapshot, browser, fixture)

    def test_owner_rejects_semantically_foreign_prepared_plan_even_with_matching_digest(self):
        for path, replacement in (
            ("eventId", uid(999)),
            ("senderId", uid(999)),
            ("body", "DIFFERENT"),
        ):
            snapshot, browser, fixture = owner_snapshot()
            row = snapshot["dispatch_plans"][0]
            payload = json.loads(row["payload_json"])
            payload["message"][path] = replacement
            row["payload_json"] = wire(payload)
            row["payload_digest"] = digest(row["payload_json"])
            with self.subTest(field=path), self.assertRaises(GATE.GateError):
                GATE.validate_owner_snapshot(snapshot, browser, fixture)

    def test_owner_rejects_noninteger_counters_and_sequences(self):
        for table, field, replacement in (
            ("communication_settings", "response_count", 3.0),
            ("native_responses", "response_sequence", 1.0),
            ("native_observations", "observation_sequence", True),
        ):
            snapshot, browser, fixture = owner_snapshot()
            snapshot[table][0][field] = replacement
            with self.subTest(table=table, field=field), self.assertRaises(GATE.GateError):
                GATE.validate_owner_snapshot(snapshot, browser, fixture)

    def test_owner_rejects_digest_source_response_and_sdk_identity_changes(self):
        for field, replacement in (
            ("payload_digest", "0" * 64),
            ("source", "publisher"),
            ("response_id", uid(999)),
            ("binding_id", uid(999)),
        ):
            snapshot, browser, fixture = owner_snapshot()
            snapshot["native_observations"][0][field] = replacement
            with self.subTest(field=field), self.assertRaises(GATE.GateError):
                GATE.validate_owner_snapshot(snapshot, browser, fixture)

    def test_owner_rejects_missing_browser_source_evidence_and_midpoint_fabrication(self):
        snapshot, browser, fixture = owner_snapshot()
        event = next(
            r
            for r in snapshot["native_observations"]
            if r["source"] == "browser_client"
            and json.loads(r["canonical_payload"])["state"] == "partial"
        )
        payload = json.loads(event["canonical_payload"])
        payload["observedAudioMs"] = 10
        event["canonical_payload"] = wire(payload)
        event["payload_digest"] = digest(event["canonical_payload"])
        with self.assertRaises(GATE.GateError):
            GATE.validate_owner_snapshot(snapshot, browser, fixture)


class PlaybackAdditionalClosureTests(unittest.TestCase):
    def test_ambient_selectors_and_opposite_role_never_enter_closed_children(self):
        common = {
            "P2_COMM_DIRECTORY": "/private/synthetic",
            "P2_COMM_SCHEMA": "p2_playback_" + "a" * 32,
            "P2_COMM_PG_PORT": "15432",
            "P2_COMM_RUNTIME_PASSWORD": "synthetic-runtime",
        }
        for key in (
            "OPENAI_API_KEY",
            "PGHOST",
            "PGPASSWORD",
            "PYTHONPATH",
            "HTTP_PROXY",
            "P2_COMM_OWNER_PASSWORD",
        ):
            with self.subTest(key=key), self.assertRaises(GATE.GateError):
                GATE.validate_child_environment({**common, key: "not-forwarded"}, "media-serve")
        with self.assertRaises(GATE.GateError):
            GATE.validate_child_environment(common, "not-a-mode")

    def test_private_target_rejects_a_world_writable_parent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = root / ".local"
            parent.mkdir(mode=0o777)
            parent.chmod(0o777)
            with self.assertRaises(GATE.GateError):
                GATE.target_path(root, Path(".local/validation/p2-playback/test.json"))

    def test_fixture_rejects_wrong_channels_rate_width_and_rendered_frame_count(self):
        for channels, width, rate, frames in (
            (2, 2, 16000, 65864),
            (1, 4, 16000, 65864),
            (1, 2, 8000, 65864),
            (1, 2, 16000, 65866),
        ):
            with (
                self.subTest(channels=channels, width=width, rate=rate, frames=frames),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                path = root / "projects/channel-continuity/examples/assets/native-status.wav"
                path.parent.mkdir(parents=True)
                with wave.open(str(path), "wb") as clip:
                    clip.setnchannels(channels)
                    clip.setsampwidth(width)
                    clip.setframerate(rate)
                    clip.writeframes(b"\x01" * (frames * channels * width))
                with self.assertRaises(GATE.GateError):
                    GATE.fixture_proof(root)

    def test_browser_unknown_and_interruption_cannot_be_promoted_by_boolean_or_duplicate_wire(self):
        value = browser_report()
        value["rows"][1]["observationCount"] = True
        with self.assertRaises(GATE.GateError):
            GATE.validated_browser(encoded(value))
        raw = encoded(browser_report())
        for field in (b'"actualBrowserAudio":true', b'"physicalHearingClaimed":false'):
            duplicate = raw.replace(field, field + b"," + field)
            with self.subTest(field=field), self.assertRaises(GATE.GateError):
                GATE.validated_browser(duplicate)

    def test_owner_rejects_escaped_duplicate_payload_keys_even_with_updated_digest(self):
        snapshot, browser, fixture = owner_snapshot()
        event = snapshot["native_observations"][0]
        old = event["canonical_payload"]
        event["canonical_payload"] = old.replace(
            '"responseId":', '"responseId":"x","\\u0072esponseId":'
        )
        event["payload_digest"] = digest(event["canonical_payload"])
        with self.assertRaises(GATE.GateError):
            GATE.validate_owner_snapshot(snapshot, browser, fixture)


class PlaybackStageRefinementTests(unittest.TestCase):
    def test_seed_requires_exact_binding_and_zero_accepted_input_facts(self):
        original = node_report("media-seed")
        self.assertEqual(GATE.validated_stage(encoded(original), "media-seed"), original)
        for key, replacement in (
            ("nativeBindings", None),
            ("nativeInputs", None),
            ("nativeBindings", True),
            ("nativeInputs", False),
            ("nativeInputs", 1),
        ):
            value = copy.deepcopy(original)
            if replacement is None:
                value.pop(key)
            else:
                value[key] = replacement
            with self.subTest(key=key, replacement=replacement), self.assertRaises(GATE.GateError):
                GATE.validated_stage(encoded(value), "media-seed")

    def test_cleanup_requires_verified_absence_and_truthful_zero_storage_version(self):
        original = node_report("media-cleanup")
        self.assertEqual(GATE.validated_stage(encoded(original), "media-cleanup"), original)
        for key, replacement in (
            ("ownedSchemaAbsent", None),
            ("cleanupComplete", None),
            ("ownedSchemaAbsent", False),
            ("ownedSchemaAbsent", 1),
            ("storageVersion", 7),
            ("storageVersion", False),
        ):
            value = copy.deepcopy(original)
            if replacement is None:
                value.pop(key)
            else:
                value[key] = replacement
            with self.subTest(key=key, replacement=replacement), self.assertRaises(GATE.GateError):
                GATE.validated_stage(encoded(value), "media-cleanup")


class IndependentPlaybackScopedSequenceTests(unittest.TestCase):
    def test_different_responses_may_start_at_one_but_same_response_cannot_duplicate(self):
        snapshot, browser, fixture = owner_snapshot()
        self.assertEqual(snapshot["native_observations"][0]["observation_sequence"], 1)
        self.assertEqual(snapshot["native_observations"][4]["observation_sequence"], 1)
        GATE.validate_owner_snapshot(snapshot, browser, fixture)
        snapshot["native_observations"][1]["observation_sequence"] = 1
        with self.assertRaises(GATE.GateError):
            GATE.validate_owner_snapshot(snapshot, browser, fixture)


class IndependentNodeCommunicationOwnershipTests(unittest.TestCase):
    def positive(self):
        return {
            "communicationMetrics": {
                **node_report("media-serve")["communicationMetrics"],
                "observerPending": 0,
                "observerDropped": 0,
            }
        }

    def test_complete_known_source_metrics_are_required_not_a_terminal_subset(self):
        value = self.positive()
        self.assertEqual(GATE.validated_node_ownership(encoded(value)), value)
        for key in tuple(value["communicationMetrics"]):
            changed = copy.deepcopy(value)
            del changed["communicationMetrics"][key]
            with self.subTest(missing=key), self.assertRaises(GATE.GateError):
                GATE.validated_node_ownership(encoded(changed))
        for wrong in [
            {},
            {"communicationMetrics": None},
            {**value, "cleanupComplete": True},
            {"communicationMetrics": {**value["communicationMetrics"], "unknownMetric": 0}},
        ]:
            with self.assertRaises(GATE.GateError):
                GATE.validated_node_ownership(encoded(wrong))

    def test_held_dropped_unknown_or_boolean_observer_metrics_cannot_claim_drained(self):
        for key in ("observerPending", "observerDropped"):
            for observation in (1, -1, False, None, 0.0, "0"):
                value = self.positive()
                value["communicationMetrics"][key] = observation
                with (
                    self.subTest(key=key, observation=observation),
                    self.assertRaises(GATE.GateError),
                ):
                    GATE.validated_node_ownership(encoded(value))
        value = self.positive()
        value["communicationMetrics"]["observationsAccepted"] = 10.0
        with self.assertRaises(GATE.GateError):
            GATE.validated_node_ownership(encoded(value))
        unknown = encoded(self.positive()).replace(
            b'"observerPending":0', b'"observerPending":0,"\\u006fbserverPending":0'
        )
        with self.assertRaises(GATE.GateError):
            GATE.validated_node_ownership(unknown)


def python_source_proof(snapshot):
    proof = {"schemaVersion": 1, "source": "native_sdk_public_nodes", "anchors": [], "sdkFacts": []}
    fields = (
        "schemaVersion",
        "responseId",
        "generationId",
        "sdkSpeechId",
        "bindingId",
        "inputId",
        "receiptId",
        "operationKey",
        "caseRevision",
    )
    for row in snapshot["native_responses"]:
        anchor = json.loads(row["canonical_anchor"])
        proof["anchors"].append(
            {
                "status": "known",
                "payload": {key: anchor[key] for key in fields},
                "receipt": {
                    "responseId": row["response_id"],
                    "receiptId": row["receipt_id"],
                    "anchorDigest": row["anchor_digest"],
                    "responseSequence": str(row["response_sequence"]),
                    "acceptedAt": row["accepted_at"],
                },
            }
        )
    for row in snapshot["native_observations"]:
        if row["source"] != "agent_sdk":
            continue
        proof["sdkFacts"].append(
            {
                "status": "known",
                "payload": json.loads(row["canonical_payload"]),
                "receipt": {
                    "responseId": row["response_id"],
                    "eventId": row["event_id"],
                    "receiptId": row["receipt_id"],
                    "payloadDigest": row["payload_digest"],
                    "observationSequence": str(row["observation_sequence"]),
                    "acceptedAt": row["accepted_at"],
                },
            }
        )
    return proof


class IndependentPythonPublicationProofTests(unittest.TestCase):
    def positive(self):
        snapshot, _, _ = owner_snapshot()
        return snapshot, python_source_proof(snapshot)

    def test_actual_publication_receipts_and_source_payloads_join_sql_independent_of_order(self):
        snapshot, proof = self.positive()
        GATE.validate_python_source_proof(encoded(proof), snapshot)
        proof["anchors"].reverse()
        proof["sdkFacts"].reverse()
        GATE.validate_python_source_proof(encoded(proof), snapshot)
        self.assertTrue(
            all(type(r["receipt"]["responseSequence"]) is str for r in proof["anchors"])
        )
        self.assertEqual(
            {r["receipt"]["observationSequence"] for r in proof["sdkFacts"]}, {"1", "2"}
        )

    def test_missing_duplicate_unknown_and_extra_publications_never_claim_exact_sources(self):
        for collection in ("anchors", "sdkFacts"):
            for kind in ("missing", "duplicate", "unknown", "extra"):
                snapshot, proof = self.positive()
                if kind == "missing":
                    proof[collection].pop()
                elif kind == "duplicate":
                    proof[collection][1] = copy.deepcopy(proof[collection][0])
                elif kind == "unknown":
                    proof[collection][0]["status"] = "unknown"
                else:
                    proof[collection][0]["rawError"] = "unsupported"
                with (
                    self.subTest(collection=collection, kind=kind),
                    self.assertRaises(GATE.GateError),
                ):
                    GATE.validate_python_source_proof(encoded(proof), snapshot)

    def test_anchor_identity_scope_metadata_or_receipt_change_cannot_match_actual_publication(self):
        for field, value in (
            ("responseId", uid(999)),
            ("generationId", uid(999)),
            ("sdkSpeechId", "foreign"),
            ("bindingId", uid(999)),
            ("inputId", uid(999)),
            ("receiptId", uid(999)),
            ("operationKey", uid(999)),
            ("caseRevision", "2"),
            ("scope", {"tenantId": "foreign", "accountId": "foreign"}),
        ):
            snapshot, proof = self.positive()
            proof["anchors"][0]["payload"][field] = value
            with self.subTest(field=field), self.assertRaises(GATE.GateError):
                GATE.validate_python_source_proof(encoded(proof), snapshot)
        snapshot, proof = self.positive()
        proof["anchors"][0]["receipt"] = proof["anchors"][1]["receipt"]
        with self.assertRaises(GATE.GateError):
            GATE.validate_python_source_proof(encoded(proof), snapshot)

    def test_sdk_source_original_text_and_handle_cannot_be_replaced_by_browser_or_expected_text(
        self,
    ):
        changes = [
            lambda p: p.update(source="browser_client"),
            lambda p: p["sdkFacts"][0]["payload"].update(generationId=uid(999)),
            lambda p: p["sdkFacts"][0]["payload"].update(sdkSpeechId="foreign"),
            lambda p: p["sdkFacts"][0]["payload"]["fact"].update(
                text="Expected fixture substituted"
            ),
            lambda p: p["sdkFacts"][0]["payload"].update(state="completed"),
            lambda p: p.update(schemaVersion=True),
        ]
        for index, change in enumerate(changes):
            snapshot, proof = self.positive()
            change(proof)
            with self.subTest(change=index), self.assertRaises(GATE.GateError):
                GATE.validate_python_source_proof(encoded(proof), snapshot)

    def test_receipt_ids_digest_canonical_sequence_strings_and_time_are_exact(self):
        for collection, fields in (
            (
                "anchors",
                ("responseId", "receiptId", "anchorDigest", "responseSequence", "acceptedAt"),
            ),
            (
                "sdkFacts",
                (
                    "responseId",
                    "eventId",
                    "receiptId",
                    "payloadDigest",
                    "observationSequence",
                    "acceptedAt",
                ),
            ),
        ):
            for field in fields:
                snapshot, proof = self.positive()
                proof[collection][0]["receipt"][field] = "foreign"
                with (
                    self.subTest(collection=collection, field=field),
                    self.assertRaises(GATE.GateError),
                ):
                    GATE.validate_python_source_proof(encoded(proof), snapshot)
            sequence = "responseSequence" if collection == "anchors" else "observationSequence"
            for value in (1, True, "01", "0", 1.0):
                snapshot, proof = self.positive()
                proof[collection][0]["receipt"][sequence] = value
                with (
                    self.subTest(collection=collection, value=value),
                    self.assertRaises(GATE.GateError),
                ):
                    GATE.validate_python_source_proof(encoded(proof), snapshot)
        snapshot, proof = self.positive()
        proof["sdkFacts"][0]["receipt"]["acceptedAt"] = "2026-11-11T00:00:00.001Z"
        with self.assertRaises(GATE.GateError):
            GATE.validate_python_source_proof(encoded(proof), snapshot)

    def test_unicode_source_digest_uses_original_sql_utf8_bytes_not_reencoded_expected_value(self):
        snapshot, _ = self.positive()
        row = snapshot["native_observations"][0]
        value = json.loads(row["canonical_payload"])
        value["fact"]["text"] = "Actual café 🧭"
        row["canonical_payload"] = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        row["payload_digest"] = digest(row["canonical_payload"])
        proof = python_source_proof(snapshot)
        GATE.validate_python_source_proof(encoded(proof), snapshot)
        escaped_digest = digest(json.dumps(value, ensure_ascii=True, separators=(",", ":")))
        self.assertNotEqual(escaped_digest, row["payload_digest"])
        proof["sdkFacts"][0]["receipt"]["payloadDigest"] = escaped_digest
        with self.assertRaises(GATE.GateError):
            GATE.validate_python_source_proof(encoded(proof), snapshot)
        row["payload_digest"] = escaped_digest
        with self.assertRaises(GATE.GateError):
            GATE.validate_python_source_proof(encoded(proof), snapshot)

    def test_source_json_and_required_hash_descriptor_reject_alias_primitive_and_missing_facts(
        self,
    ):
        snapshot, proof = self.positive()
        raw = encoded(proof)
        for value in (
            b"[]",
            b"null",
            b"\xff",
            raw[:-1],
            raw.replace(b'"schemaVersion":1', b'"schemaVersion":1,"\\u0073chemaVersion":1', 1),
        ):
            with self.subTest(raw_bytes=len(value)), self.assertRaises(GATE.GateError):
                GATE.validate_python_source_proof(value, snapshot)
        value = report()
        self.assertIn("python_source", value["proofs"])
        for change in (
            lambda p: p["proofs"].pop("python_source"),
            lambda p: p["proofs"].update(extra={"bytes": 1, "sha256": "a" * 64}),
            lambda p: p["proofs"]["python_source"].update(sha256="bad"),
        ):
            wrong = copy.deepcopy(value)
            change(wrong)
            with self.assertRaises(GATE.GateError):
                GATE.validated_report(encoded(wrong))


class IndependentBoundedPlaybackProofFileTests(unittest.TestCase):
    def test_private_regular_file_mode_links_and_overflow_are_validated_before_reading(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "proof.json"
            path.write_bytes(b"{}")
            path.chmod(0o600)
            self.assertEqual(GATE.bounded_read(path, maximum=4), b"{}")
            alias = path.with_name("alias")
            alias.symlink_to(path)
            with self.assertRaises(GATE.GateError):
                GATE.bounded_read(alias)
            alias.unlink()
            alias.hardlink_to(path)
            with self.assertRaises(GATE.GateError):
                GATE.bounded_read(path)
            alias.unlink()
            path.chmod(0o644)
            with self.assertRaises(GATE.GateError):
                GATE.bounded_read(path)
            path.chmod(0o600)
            path.write_bytes(b"x" * 5)
            with self.assertRaises(GATE.GateError):
                GATE.bounded_read(path, maximum=4)

    def test_open_identity_and_growth_after_initial_stat_cannot_escape_actual_read_bound(self):
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "proof.json"
            path.write_bytes(b"{}")
            path.chmod(0o600)
            info = path.stat()
            with (
                patch.object(
                    GATE.os,
                    "fstat",
                    return_value=SimpleNamespace(st_dev=info.st_dev, st_ino=info.st_ino + 1),
                ),
                self.assertRaises(GATE.GateError),
            ):
                GATE.bounded_read(path)
            path.write_bytes(b"xxxxx")
            original = SimpleNamespace(
                st_mode=info.st_mode,
                st_uid=info.st_uid,
                st_nlink=1,
                st_size=2,
                st_dev=info.st_dev,
                st_ino=info.st_ino,
            )
            with (
                patch.object(Path, "lstat", return_value=original),
                self.assertRaises(GATE.GateError),
            ):
                GATE.bounded_read(path, maximum=4)


def browser_context():
    return {
        "schemaVersion": 1,
        "stage": "interrupt",
        "pageErrors": 0,
        "unexpectedNetworkRequests": 0,
        "inputStates": ["accepted", "unknown"],
        "responses": [
            {
                "sdkState": "interrupted",
                "browserState": "partial",
                "generatedObserved": True,
                "observationCount": 3,
                "observedAudioMs": 900,
                "sampledAudioMs": 1200,
            }
        ],
    }


class IndependentBrowserFailureContextTests(unittest.TestCase):
    def test_finite_source_context_and_closed_page_nulls_retain_stage_without_qualification(self):
        for stage in (
            "initializing",
            "join",
            "normal",
            "interrupt",
            "missing",
            "cleanup",
            "complete",
        ):
            value = {**browser_context(), "stage": stage}
            self.assertEqual(GATE.validated_browser_context(encoded(value)), value)
        value = {**browser_context(), "stage": "missing", "inputStates": None, "responses": None}
        self.assertEqual(GATE.validated_browser_context(encoded(value)), value)
        self.assertNotIn("status", value)

    def test_body_code_identity_unknown_stage_or_unhashable_values_never_enter_diagnostics(self):
        for changes in (
            {"body": "private_sentinel"},
            {"code": "private_sentinel"},
            {"responseId": uid(999)},
            {"status": "passed"},
            {"stage": "private_sentinel"},
            {"stage": []},
            {"stage": {}},
            {"schemaVersion": True},
            {"pageErrors": False},
            {"unexpectedNetworkRequests": 1.0},
            {"inputStates": ["private_sentinel"]},
            {"inputStates": [{}]},
            {"inputStates": "accepted"},
        ):
            with self.subTest(changes=changes), self.assertRaises(GATE.GateError):
                GATE.validated_browser_context(encoded({**browser_context(), **changes}))

    def test_response_source_states_primitives_counts_and_array_caps_are_strict(self):
        for key, value in (
            ("sdkState", "heard"),
            ("sdkState", []),
            ("browserState", {}),
            ("browserState", "delivered"),
            ("generatedObserved", 1),
            ("observationCount", True),
            ("observationCount", 65),
            ("observedAudioMs", -1),
            ("observedAudioMs", 180001),
            ("sampledAudioMs", float("nan")),
            ("sampledAudioMs", float("inf")),
            ("body", "private_sentinel"),
        ):
            context = browser_context()
            context["responses"][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(GATE.GateError):
                GATE.validated_browser_context(encoded(context))
        for changes in (
            {"responses": [browser_context()["responses"][0]] * 4},
            {"responses": [None]},
            {"responses": {}},
            {"inputStates": ["accepted"] * 4},
            {"pageErrors": 1001},
        ):
            with self.subTest(changes=changes), self.assertRaises(GATE.GateError):
                GATE.validated_browser_context(encoded({**browser_context(), **changes}))

    def test_malformed_alias_oversize_or_unknown_context_cannot_turn_into_success(self):
        raw = encoded(browser_context())
        for value in (
            b"[]",
            b"null",
            b"\xff",
            raw[:-1],
            b" " * 16384 + raw,
            raw.replace(b'"schemaVersion":1', b'"schemaVersion":1,"\\u0073chemaVersion":1', 1),
            encoded({"status": "passed"}),
        ):
            with self.subTest(raw_bytes=len(value)), self.assertRaises(GATE.GateError):
                GATE.validated_browser_context(value)


class IndependentEvidenceReadRecoveryTests(unittest.TestCase):
    def test_actual_unavailable_then_same_response_read_recovery_is_required_strict_true(self):
        value = browser_report()
        self.assertEqual(GATE.validated_browser(encoded(value)), value)
        missing = dict(value)
        del missing["evidenceReadRecoveryVerified"]
        for wrong in [
            missing,
            *(
                {**value, "evidenceReadRecoveryVerified": v}
                for v in (False, None, 1, "true", {}, [])
            ),
        ]:
            with self.subTest(value=wrong), self.assertRaises(GATE.GateError):
                GATE.validated_browser(encoded(wrong))


class PlaybackFailureOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def mocked_run(self, mode):
        from livekit import api

        from harness.process_control import ProcessControlError

        primary = ProcessControlError("controlled_private_sentinel")
        state = {"ddl": 0, "room_reads": 0, "api_close": 0, "child_close": [], "work": None}
        values = {
            "POSTGRES_PORT": "5432",
            "POSTGRES_RUNTIME_PASSWORD": "synthetic-runtime",
            "POSTGRES_PASSWORD": "synthetic-runtime",
            "POSTGRES_MIGRATION_PASSWORD": "synthetic-owner",
            "LIVEKIT_HTTP_PORT": "7880",
            "LIVEKIT_API_KEY": "synthetic-key",
            "LIVEKIT_API_SECRET": "synthetic-secret",
        }

        class Token:
            def __init__(self, *args):
                pass

            def with_identity(self, *args):
                return self

            def with_kind(self, *args):
                return self

            def with_ttl(self, *args):
                return self

            def with_grants(self, *args):
                return self

            def to_jwt(self):
                return "synthetic-token"

        class Room:
            async def create_room(self, *args):
                return None

            async def list_rooms(self, *args):
                state["room_reads"] += 1
                return SimpleNamespace(rooms=[])

        class Api:
            room = Room()

            async def aclose(self):
                state["api_close"] += 1

        class Child:
            def __init__(self, owner, name, code):
                self.owner = owner
                self.output_directory = owner.work / name
                self.output_directory.mkdir(mode=0o700)
                self.pid = 10000 + owner.count
                self.returncode = code
                self.cleanup_failed = False

            def wait_for_barrier(self, *args, **kwargs):
                raise primary

            def close(self):
                state["child_close"].append(self.output_directory.name)
                if self.output_directory.name == "python-app":
                    path = self.owner.work / "python-failure-context.json"
                    if not path.exists():
                        GATE.native.write_json(
                            path,
                            {
                                "schemaVersion": 1,
                                "status": "failed",
                                "mode": "serve",
                                "stage": "waiting_node",
                                "errorType": "NativeError",
                                "code": "closed",
                                "frames": [{"file": "native_lab.py", "line": 630}],
                            },
                        )
                    if mode == "held":
                        raise GATE.GateError("cleanup_incomplete")
                    self.returncode = 0
                    self.cleanup_failed = mode == "failed_close"

        class Children:
            def __init__(self, work, deadline):
                self.work = work
                self.deadline = deadline
                self.count = 0
                self.children = []
                state["work"] = work

            def call(self, name, *args, **kwargs):
                self.count += 1
                self.children.append(Child(self, name, 0))
                if name == "compile":
                    return b""
                if name == "media-cleanup":
                    state["ddl"] += 1
                return encoded(node_report(name))

            def start(self, name, *args, **kwargs):
                self.count += 1
                child = Child(self, name, None)
                self.children.append(child)
                return child

            def close(self):
                first = None
                for child in reversed(self.children):
                    try:
                        child.close()
                    except BaseException as error:  # noqa: BLE001 - fake owner preserves cancellation semantics.
                        first = first or error
                if first is not None:
                    raise first
                if any(c.returncode is None or c.cleanup_failed for c in self.children):
                    raise GATE.GateError("cleanup_incomplete")

            def stop(self, child, **kwargs):
                if mode == "closed":
                    child.returncode = 0
                    return b""
                if mode == "failed_close":
                    child.returncode = 0
                    child.cleanup_failed = True
                    return b""
                raise GATE.GateError("cleanup_incomplete")

        with tempfile.TemporaryDirectory(
            prefix="playback-owned-run-", dir="/private/tmp"
        ) as temporary:
            root = Path(temporary)
            artifacts = root / "artifacts"
            artifacts.mkdir(mode=0o700)
            for rel in (
                ".venv/bin/python",
                "projects/channel-continuity/node_modules/typescript/bin/tsc",
                "projects/channel-continuity/examples/native_lab.py",
                "apps/local-console/node_modules/vite/bin/vite.js",
                "apps/local-console/node_modules/@playwright/test/cli.js",
            ):
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"")
            cleanup = {"cleanup_complete": False}
            setup = SimpleNamespace(
                load_settings=lambda: values,
                SECRET_KEYS=(
                    "POSTGRES_RUNTIME_PASSWORD",
                    "POSTGRES_MIGRATION_PASSWORD",
                    "LIVEKIT_API_SECRET",
                ),
            )
            with (
                patch.object(GATE.core, "load_setup", return_value=setup),
                patch.object(
                    GATE.core,
                    "base_environment",
                    return_value={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
                ),
                patch.object(GATE.shutil, "which", return_value="/usr/bin/node"),
                patch.object(GATE.native, "Children", Children),
                patch.object(
                    GATE.native, "verify_runtime_build", return_value={"status": "passed"}
                ),
                patch.object(GATE, "fixture_proof", return_value={"schemaVersion": 1}),
                patch.object(api, "AccessToken", Token),
                patch.object(api, "LiveKitAPI", return_value=Api()),
                self.assertRaises(ProcessControlError) as caught,
            ):
                await GATE.run(root, artifacts, GATE.time.monotonic(), cleanup, None)
            self.assertIs(caught.exception, primary)
            self.assertEqual(state["api_close"], 1)
            self.assertTrue(
                {"compile", "media-install", "media-seed", "python-app"}
                <= set(state["child_close"])
            )
            if mode == "closed":
                self.assertEqual(state["ddl"], 1)
                self.assertEqual(state["room_reads"], 2)
                self.assertTrue(cleanup["cleanup_complete"])
                self.assertFalse(state["work"].exists())
            else:
                self.assertEqual(state["ddl"], 0)
                self.assertEqual(state["room_reads"], 0)
                self.assertFalse(cleanup["cleanup_complete"])
                self.assertTrue(state["work"].exists())
                retained = json.loads((artifacts / "owned-work-retained.json").read_bytes())
                self.assertEqual(root / retained["directory"], state["work"])
                self.assertTrue((state["work"] / "playback-owned-work.json").is_file())
            self.assertTrue((artifacts / "python-failure-context.json").is_file())
            self.assertNotIn(
                "controlled_private_sentinel",
                (artifacts / "fixture-failure-context.json").read_text(),
            )

    async def test_actual_run_with_unsettled_mock_owner_withholds_ddl_room_and_work_removal(self):
        await self.mocked_run("held")

    async def test_actual_run_with_exit_but_failed_close_withholds_dependent_cleanup(self):
        await self.mocked_run("failed_close")

    async def test_known_closed_mock_owners_allow_cleanup_without_replacing_primary_failure(self):
        await self.mocked_run("closed")


class PlaybackFinitePythonDiagnosticsTests(unittest.TestCase):
    def failure(self):
        return {
            "schemaVersion": 1,
            "status": "failed",
            "mode": "serve",
            "stage": "waiting_node",
            "errorType": "NativeError",
            "code": "closed",
            "frames": [{"file": "native_lab.py", "line": 630}],
        }

    def test_producer_shape_is_closed_and_never_retains_messages_or_unknown_locations(self):
        value = self.failure()
        self.assertEqual(GATE.validated_python_failure(encoded(value)), value)
        for changes in (
            {"body": "private_sentinel"},
            {"schemaVersion": True},
            {"stage": []},
            {"code": "private_sentinel"},
            {"errorType": {}},
            {"frames": [{"file": "private_sentinel.py", "line": 1}]},
            {"frames": [{"file": "native_lab.py", "line": True}]},
        ):
            with self.subTest(changes=changes), self.assertRaises(GATE.GateError):
                GATE.validated_python_failure(encoded({**value, **changes}))

    def test_stderr_observation_drops_error_messages_and_external_paths(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            work = Path(temporary)
            artifacts = work / "artifacts"
            artifacts.mkdir(mode=0o700)
            output = work / "python-app"
            output.mkdir(mode=0o700)
            stream = output / "stderr.bin"
            stream.write_bytes(
                b'Traceback (most recent call last):\n  File "/private/path/native_lab.py", line 24, in <module>\n  File "/private/path/private_sentinel.py", line 10, in <module>\nModuleNotFoundError: private_sentinel_secret\n'
            )
            stream.chmod(0o600)
            children = SimpleNamespace(children=[SimpleNamespace(output_directory=output)])
            self.assertTrue(
                GATE.retain_python_failure_safely(
                    work, artifacts, children, ("private_sentinel_secret",)
                )
            )
            raw = (artifacts / "python-startup-failure-observation.json").read_bytes()
            self.assertNotIn(b"private_sentinel", raw)
            self.assertNotIn(b"/private/path", raw)
            self.assertEqual(json.loads(raw)["frames"], [{"file": "native_lab.py", "line": 24}])
            self.assertEqual(json.loads(raw)["exceptionType"], "ModuleNotFoundError")

    def test_diagnostic_sink_failure_returns_false_without_copying_private_input(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            work = Path(temporary)
            artifacts = work / "artifacts"
            artifacts.mkdir(mode=0o700)
            p = work / "python-failure-context.json"
            p.write_bytes(encoded(self.failure()))
            p.chmod(0o600)
            with patch.object(GATE.native, "write_json", side_effect=OSError("private_sentinel")):
                self.assertFalse(
                    GATE.retain_python_failure_safely(
                        work, artifacts, SimpleNamespace(children=[]), ()
                    )
                )
            self.assertFalse(list(artifacts.iterdir()))
