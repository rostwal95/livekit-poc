"""Actual local scripted P2 playback evidence, with source-separated observations.

No provider configuration or inference is read. The original six-group native
profile remains a separate regression. This gate owns one room and every child.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import socket
import stat
import sys
import tempfile
import time
import wave
from array import array
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p2_communication_diagnostics as diagnostics
import p2_native_check as native
import p3_coordinator_check as core

from harness.process_control import FileBarrier

ROOT = Path(__file__).resolve().parents[2]
GateError = native.GateError
MODE = "local_scripted_p2_playback"
TOTAL_SECONDS = 240.0
CLEANUP_SECONDS = 20.0
MAX_REPORT_BYTES = 32768
CASE_NAMES = (
    "normal_source_qualified_output",
    "measured_midpoint_interruption_partial_evidence",
    "disconnect_missing_playback_completion_unknown",
)
MODES = ("media-install", "media-seed", "media-serve", "media-verify", "media-cleanup")
OWNER_MODES = frozenset({"media-install", "media-verify", "media-cleanup"})
COMMON_ENV = frozenset({"P2_COMM_DIRECTORY", "P2_COMM_SCHEMA", "P2_COMM_PG_PORT"})
FIXTURE_MS = 2058.25
NODE_METRICS = {
    "accepted": 3,
    "active": 0,
    "dispatched": 3,
    "driver": 0,
    "handlers": 0,
    "intakes": 0,
    "observerPending": 0,
    "replayed": 0,
    "sockets": 0,
}
COMM_METRICS = {
    "capacityRejected": 0,
    "identityConflicts": 0,
    "observationsAccepted": 10,
    "observationsReplayed": 0,
    "rejected": 0,
    "responsesAccepted": 3,
    "responsesReplayed": 0,
    "telemetryFailures": 0,
    "unknownAcknowledgements": 0,
}
PYTHON_METRICS = {
    "activeIntakes": 0,
    "activePrepare": 0,
    "activeReaders": 0,
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
    "textStreamsSeen": 3,
    "voiceCaptures": 0,
    "voiceCommits": 0,
}
PYTHON_COMM_METRICS = {
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
}
VERIFY = {
    "browserCompletedReported": 1,
    "browserObservations": 4,
    "browserPartial": 1,
    "browserUnknown": 1,
    "exactIdentityJoins": True,
    "nativeInputs": 3,
    "noAcknowledgements": True,
    "operationAcceptances": 3,
    "preparedPlans": 3,
    "processingIntents": 3,
    "responses": 3,
    "sdkCompleted": 2,
    "sdkInterrupted": 1,
    "sdkObservations": 6,
    "totalObservations": 10,
}


def validate_child_environment(environment: dict[str, str], mode: str) -> None:
    if mode not in MODES:
        raise GateError("invalid_child_mode")
    password = "P2_COMM_OWNER_PASSWORD" if mode in OWNER_MODES else "P2_COMM_RUNTIME_PASSWORD"
    required = COMMON_ENV | {password}
    if (
        not required <= set(environment)
        or set(environment) - required - core.BASE_ENVIRONMENT_KEYS
        or any(type(v) is not str or not v or "\0" in v for v in environment.values())
    ):
        raise GateError("unsafe_child_environment")
    if (
        not re.fullmatch(r"p2_playback_[a-f0-9]{32}", environment["P2_COMM_SCHEMA"])
        or not re.fullmatch(r"[1-9][0-9]{3,4}", environment["P2_COMM_PG_PORT"])
        or not 1024 <= int(environment["P2_COMM_PG_PORT"]) <= 65535
        or not Path(environment["P2_COMM_DIRECTORY"]).is_absolute()
        or ".." in Path(environment["P2_COMM_DIRECTORY"]).parts
        or str(Path(environment["P2_COMM_DIRECTORY"])) != environment["P2_COMM_DIRECTORY"]
    ):
        raise GateError("unsafe_child_environment")


def child_environment(values: dict[str, str], common: dict[str, str], mode: str) -> dict[str, str]:
    owner = mode in OWNER_MODES
    result = {
        **core.base_environment(),
        **common,
        ("P2_COMM_OWNER_PASSWORD" if owner else "P2_COMM_RUNTIME_PASSWORD"): values[
            "POSTGRES_MIGRATION_PASSWORD" if owner else "POSTGRES_PASSWORD"
        ],
    }
    validate_child_environment(result, mode)
    return result


def validated_stage(raw: bytes, mode: str) -> dict[str, Any]:
    if mode not in MODES:
        raise GateError("invalid_child_mode")
    value = native.decode(raw)
    expected: dict[str, Any] = {
        "schemaVersion": 1,
        "status": "passed",
        "mode": mode,
        "storageVersion": 7,
    }
    if mode == "media-seed":
        expected.update(nativeBindings=1, nativeInputs=0)
    if mode == "media-cleanup":
        expected.update(storageVersion=0, ownedSchemaAbsent=True, cleanupComplete=True)
    if mode == "media-serve":
        expected.update(
            cleanupComplete=True, metrics=NODE_METRICS, communicationMetrics=COMM_METRICS
        )
    if mode == "media-verify":
        expected.update(VERIFY)
    if (
        set(value) != set(expected) | {"nodeVersion"}
        or not core.supported_node(value.get("nodeVersion"))
        or not all(native.exact(value[k], v) for k, v in expected.items())
    ):
        raise GateError("invalid_stage_report")
    return value


def validated_node_ownership(raw: bytes) -> dict[str, Any]:
    value = native.decode(raw)
    expected = {
        "communicationMetrics": {**COMM_METRICS, "observerPending": 0, "observerDropped": 0}
    }
    if not native.exact(value, expected):
        raise GateError("incomplete_communication_ownership")
    return value


def validated_python(raw: bytes) -> dict[str, Any]:
    value = native.decode(raw)
    expected = {
        "schemaVersion": 1,
        "status": "passed",
        "mode": "serve",
        "cleanupComplete": True,
        "sdkClosed": True,
        "roomClosed": True,
        "httpClosed": True,
        "metrics": PYTHON_METRICS,
        "communicationMetrics": PYTHON_COMM_METRICS,
    }
    if not native.exact(value, expected):
        raise GateError("invalid_python_report")
    return value


def is_uuid(value: object) -> bool:
    try:
        return type(value) is str and UUID(value).version == 4 and str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def validated_browser(raw: bytes) -> dict[str, Any]:
    value = native.decode(raw)
    expected = {
        "schemaVersion": 1,
        "status": "passed",
        "mode": "local_scripted_p2_playback_browser",
        "fixtureDurationMs": FIXTURE_MS,
        "actualBrowserAudio": True,
        "physicalHearingClaimed": False,
        "clientReportsWithheldForMissing": True,
        "evidenceReadRecoveryVerified": True,
        "cleanupComplete": True,
        "pageErrors": 0,
        "unexpectedNetworkRequests": 0,
    }
    if set(value) != set(expected) | {"rows", "interruptTriggerAudioMs"} or not all(
        native.exact(value[k], v) for k, v in expected.items()
    ):
        raise GateError("invalid_browser_report")
    rows = value["rows"]
    trigger = value["interruptTriggerAudioMs"]
    if (
        type(rows) is not list
        or len(rows) != 3
        or type(trigger) is not int
        or not FIXTURE_MS * 0.35 <= trigger <= FIXTURE_MS * 0.65
    ):
        raise GateError("invalid_browser_report")
    keys = {
        "responseId",
        "generationId",
        "inputId",
        "operationKey",
        "sdkSpeechId",
        "observationCount",
        "generated_observed",
        "sdk_state",
        "browser_state",
        "conflicted",
        "observed_audio_ms",
        "sampled_audio_ms",
    }
    for i, item in enumerate(rows):
        if (
            type(item) is not dict
            or set(item) != keys
            or any(
                not is_uuid(item[k])
                for k in ("responseId", "generationId", "inputId", "operationKey")
            )
            or type(item["sdkSpeechId"]) is not str
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", item["sdkSpeechId"])
            or item["generated_observed"] is not True
            or item["conflicted"] is not False
        ):
            raise GateError("invalid_browser_report")
        for key in ("observationCount", "observed_audio_ms", "sampled_audio_ms"):
            if type(item[key]) is not int or not 0 <= item[key] <= (
                64 if key == "observationCount" else 180000
            ):
                raise GateError("invalid_browser_report")
        if (
            item["sampled_audio_ms"] < item["observed_audio_ms"]
            or item["sdk_state"] != ("interrupted" if i == 1 else "completed")
            or item["browser_state"] != ("completed_reported", "partial", "unknown")[i]
        ):
            raise GateError("invalid_browser_report")
        if i == 0 and item["observed_audio_ms"] < FIXTURE_MS * 0.75:
            raise GateError("missing_actual_audio")
        if i == 1 and not trigger <= item["observed_audio_ms"] < FIXTURE_MS * 0.85:
            raise GateError("missing_partial_audio")
        if i == 2 and item["observed_audio_ms"] <= 100:
            raise GateError("missing_actual_audio")
    for key in ("responseId", "generationId", "inputId", "operationKey", "sdkSpeechId"):
        if len({item[key] for item in rows}) != 3:
            raise GateError("invalid_browser_identity")
    return value


def validated_report(raw: bytes) -> dict[str, Any]:
    value = native.decode(raw)
    expected = {
        "schema_version": 1,
        "status": "passed",
        "mode": MODE,
        "tests": 3,
        "passed": 3,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "cleanup_complete": True,
        "case_results": [{"name": n, "status": "passed", "code": "ok"} for n in CASE_NAMES],
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
    }
    if (
        set(value)
        != set(expected) | {"duration_seconds", "node_version", "child_commands", "proofs"}
        or not all(native.exact(value[k], v) for k, v in expected.items())
        or not core.supported_node(value.get("node_version"))
    ):
        raise GateError("invalid_report")
    duration = value["duration_seconds"]
    commands = value["child_commands"]
    if (
        type(duration) not in (int, float)
        or not 0 < duration <= TOTAL_SECONDS
        or not math.isfinite(duration)
        or type(commands) is not int
        or commands != 9
    ):
        raise GateError("invalid_report")
    proofs = value["proofs"]
    if type(proofs) is not dict or set(proofs) != {
        "owner_snapshot",
        "browser",
        "node",
        "python",
        "fixture",
        "node_ownership",
        "python_source",
    }:
        raise GateError("invalid_report")
    for item in proofs.values():
        if (
            type(item) is not dict
            or set(item) != {"bytes", "sha256"}
            or type(item["bytes"]) is not int
            or not 0 < item["bytes"] <= 2097152
            or type(item["sha256"]) is not str
            or not re.fullmatch(r"[a-f0-9]{64}", item["sha256"])
        ):
            raise GateError("invalid_report")
    return value


def _validate_owner_snapshot(
    snapshot: dict[str, Any], browser: dict[str, Any], fixture: dict[str, Any]
) -> None:
    """Join independently read SQL rows, raw canonical bytes and browser identities."""
    tables = {
        "native_responses": 3,
        "native_observations": 10,
        "communication_settings": 1,
        "inbox": 3,
        "processing_intents": 3,
        "dispatch_plans": 3,
    }
    if (
        type(snapshot) is not dict
        or set(snapshot) != set(tables)
        or any(type(snapshot[k]) is not list or len(snapshot[k]) != n for k, n in tables.items())
    ):
        raise GateError("owner_inventory_mismatch")
    settings = snapshot["communication_settings"][0]
    if (
        type(settings.get("response_count")) is not int
        or type(settings.get("observation_count")) is not int
        or settings.get("response_count") != 3
        or settings.get("observation_count") != 10
    ):
        raise GateError("owner_counter_mismatch")
    responses = {r["response_id"]: r for r in snapshot["native_responses"]}
    if any(type(r["response_sequence"]) is not int for r in responses.values()) or any(
        type(r["observation_sequence"]) is not int for r in snapshot["native_observations"]
    ):
        raise GateError("owner_identity_mismatch")
    if (
        len(responses) != 3
        or any(type(r["response_sequence"]) is not int for r in responses.values())
        or {r["response_sequence"] for r in responses.values()} != {1, 2, 3}
    ):
        raise GateError("owner_identity_mismatch")
    inbox = {r["receipt_id"]: r for r in snapshot["inbox"]}
    intents = {r["receipt_id"]: r for r in snapshot["processing_intents"]}
    plans = {r["receipt_id"]: r for r in snapshot["dispatch_plans"]}
    if len(inbox) != 3 or set(inbox) != set(intents) or set(inbox) != set(plans):
        raise GateError("owner_input_join_mismatch")
    events = snapshot["native_observations"]
    if (
        len({r["event_id"] for r in events}) != 10
        or len({r["receipt_id"] for r in events}) != 10
        or any(type(r["observation_sequence"]) is not int for r in events)
    ):
        raise GateError("owner_observation_identity_mismatch")
    for i, browser_row in enumerate(browser["rows"]):
        response = responses.get(browser_row["responseId"])
        if response is None:
            raise GateError("owner_response_missing")
        raw = response["canonical_anchor"]
        anchor = native.decode(raw.encode(), maximum=8192)
        if hashlib.sha256(raw.encode()).hexdigest() != response["anchor_digest"]:
            raise GateError("owner_anchor_digest_mismatch")
        fields = {
            "responseId": "response_id",
            "generationId": "generation_id",
            "sdkSpeechId": "sdk_speech_id",
            "bindingId": "binding_id",
            "receiptId": "input_receipt_id",
            "operationKey": "operation_key",
            "caseId": "case_id",
            "conversationId": "conversation_id",
        }
        if (
            any(anchor[k] != response[col] for k, col in fields.items())
            or any(
                anchor[k] != browser_row[k]
                for k in ("responseId", "generationId", "sdkSpeechId", "inputId", "operationKey")
            )
            or anchor["bindingId"] != fixture["bindingId"]
            or anchor["roomId"] != fixture["roomId"]
            or anchor["participantId"] != fixture["participantId"]
            or anchor["scope"] != fixture["scope"]
            or anchor["providerScope"] != fixture["providerScope"]
            or response["tenant_id"] != anchor["scope"]["tenantId"]
            or response["account_id"] != anchor["scope"]["accountId"]
        ):
            raise GateError("owner_anchor_scope_mismatch")
        receipt = anchor["receiptId"]
        if (
            receipt not in inbox
            or intents[receipt]["operation_key"] != anchor["operationKey"]
            or plans[receipt]["operation_key"] != anchor["operationKey"]
        ):
            raise GateError("owner_operation_join_mismatch")
        original = inbox[receipt]
        wire = native.decode(original["wire_json"].encode())
        semantic = {
            k: v for k, v in wire.items() if k not in {"receivedAt", "retryCount", "signature"}
        }
        canonical = json.dumps(semantic, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        if (
            canonical != original["canonical_payload"]
            or json.dumps(wire, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            != original["wire_json"]
        ):
            raise GateError("owner_input_canonical_mismatch")
        expected_input = {
            "schemaVersion": 1,
            "type": "text.received",
            "providerScope": fixture["providerScope"],
            "accountScope": fixture["scope"],
            "conversationId": fixture["conversationId"],
            "caseId": fixture["caseId"],
            "eventId": anchor["inputId"],
            "messageId": anchor["inputId"],
            "senderId": fixture["bindingId"],
            "channel": "web_chat",
            "body": "INVESTIGATE",
        }
        if (
            not native.exact(semantic, expected_input)
            or original["event_id"] != anchor["inputId"]
            or original["message_id"] != anchor["inputId"]
            or original["tenant_id"] != fixture["scope"]["tenantId"]
            or original["provider"] != "livekit"
            or original["provider_account_id"] != fixture["providerScope"]["providerAccountId"]
            or original["account_id"] != fixture["scope"]["accountId"]
            or original["conversation_id"] != fixture["conversationId"]
            or intents[receipt]["state"] != "dispatched"
        ):
            raise GateError("owner_input_scope_mismatch")
        plan = plans[receipt]
        submission = native.decode(plan["payload_json"].encode())
        expected_submission = {
            "schemaVersion": 1,
            "kind": "investigation",
            "operationKey": anchor["operationKey"],
            "scope": anchor["scope"],
            "caseId": anchor["caseId"],
            "caseRevision": anchor["caseRevision"],
            "conversationId": anchor["conversationId"],
            "message": {
                "receiptId": receipt,
                "eventId": anchor["inputId"],
                "messageId": anchor["inputId"],
                "senderId": fixture["bindingId"],
                "body": wire["body"],
            },
        }
        if not native.exact(submission, expected_submission):
            raise GateError("owner_plan_scope_mismatch")
        if hashlib.sha256(plan["payload_json"].encode()).hexdigest() != plan["payload_digest"]:
            raise GateError("owner_plan_digest_mismatch")
        sdk = []
        client = []
        local_sequences = []
        for event in events:
            if event["response_id"] != anchor["responseId"]:
                continue
            payload = native.decode(event["canonical_payload"].encode())
            local_sequences.append(event["observation_sequence"])
            if (
                event["binding_id"] != anchor["bindingId"]
                or payload["responseId"] != event["response_id"]
                or payload["eventId"] != event["event_id"]
                or hashlib.sha256(event["canonical_payload"].encode()).hexdigest()
                != event["payload_digest"]
            ):
                raise GateError("owner_observation_join_mismatch")
            if event["source"] == "agent_sdk":
                if (
                    payload["generationId"] != anchor["generationId"]
                    or payload["sdkSpeechId"] != anchor["sdkSpeechId"]
                ):
                    raise GateError("owner_sdk_identity_mismatch")
                sdk.append(payload["fact"])
            elif event["source"] == "browser_client":
                client.append(payload)
            else:
                raise GateError("owner_source_mismatch")
        generated = [f for f in sdk if f["type"] == "generated_complete"]
        settled = [f for f in sdk if f["type"] == "speech_settled"]
        if (
            len(sdk) != 2
            or len(generated) != 1
            or generated[0]["text"] != "The workflow panel shows the latest durable state."
            or len(settled) != 1
            or settled[0]["state"] != ("interrupted" if i == 1 else "completed")
        ):
            raise GateError("owner_sdk_fact_mismatch")
        if sorted(p["state"] for p in client) != (
            ["completed", "started"] if i == 0 else ["partial", "started"] if i == 1 else []
        ):
            raise GateError("owner_client_state_mismatch")
        if i == 1:
            partial = next(p for p in client if p["state"] == "partial")
            if (
                type(partial["observedAudioMs"]) is not int
                or not FIXTURE_MS * 0.35 <= partial["observedAudioMs"] <= FIXTURE_MS * 0.65
            ):
                raise GateError("owner_midpoint_missing")
        if sorted(local_sequences) != list(range(1, len(local_sequences) + 1)):
            raise GateError("owner_response_sequence_mismatch")
        if len(sdk) + len(client) != browser_row["observationCount"]:
            raise GateError("owner_browser_snapshot_mismatch")


def validated_browser_context(raw: bytes) -> dict[str, Any]:
    value = native.decode(raw, maximum=16384)
    if (
        set(value)
        != {
            "schemaVersion",
            "stage",
            "pageErrors",
            "unexpectedNetworkRequests",
            "inputStates",
            "responses",
        }
        or type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or type(value["stage"]) is not str
        or value["stage"]
        not in {"initializing", "join", "normal", "interrupt", "missing", "cleanup", "complete"}
        or any(
            type(value[k]) is not int or not 0 <= value[k] <= 1000
            for k in ("pageErrors", "unexpectedNetworkRequests")
        )
    ):
        raise GateError("invalid_browser_context")
    inputs, responses = value["inputStates"], value["responses"]
    if inputs is not None and (
        type(inputs) is not list
        or len(inputs) > 3
        or any(
            type(v) is not str
            or v not in {"accepted", "replayed", "unknown", "rejected", "pending"}
            for v in inputs
        )
    ):
        raise GateError("invalid_browser_context")
    if responses is not None:
        if type(responses) is not list or len(responses) > 3:
            raise GateError("invalid_browser_context")
        for row in responses:
            if (
                type(row) is not dict
                or set(row)
                != {
                    "sdkState",
                    "browserState",
                    "generatedObserved",
                    "observationCount",
                    "observedAudioMs",
                    "sampledAudioMs",
                }
                or type(row["sdkState"]) is not str
                or row["sdkState"] not in {"completed", "interrupted", "unknown", "conflicted"}
                or type(row["browserState"]) is not str
                or row["browserState"]
                not in {
                    "unknown",
                    "started",
                    "partial",
                    "interrupted",
                    "completed_reported",
                    "conflicted",
                }
                or type(row["generatedObserved"]) is not bool
                or any(
                    type(row[k]) is not int or not 0 <= row[k] <= limit
                    for k, limit in (
                        ("observationCount", 64),
                        ("observedAudioMs", 180000),
                        ("sampledAudioMs", 180000),
                    )
                )
            ):
                raise GateError("invalid_browser_context")
    return value


def bounded_read(path: Path, *, maximum: int = 32768) -> bytes:
    before = path.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_uid != os.getuid()
        or stat.S_IMODE(before.st_mode) != 0o600
        or before.st_nlink != 1
        or before.st_size > maximum
    ):
        raise GateError("unsafe_proof_file")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as source:
        current = os.fstat(source.fileno())
        if (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino):
            raise GateError("unsafe_proof_file")
        raw = source.read(maximum + 1)
        if len(raw) > maximum:
            raise GateError("unsafe_proof_file")
        return raw


def validate_python_source_proof(raw: bytes, snapshot: dict[str, Any]) -> None:
    """Join actual app-recorded public SDK publications to independently read SQL."""
    try:
        proof = native.decode(raw, maximum=1048576)
        if (
            set(proof) != {"schemaVersion", "source", "anchors", "sdkFacts"}
            or type(proof["schemaVersion"]) is not int
            or proof["schemaVersion"] != 1
            or proof["source"] != "native_sdk_public_nodes"
            or type(proof["anchors"]) is not list
            or len(proof["anchors"]) != 3
            or type(proof["sdkFacts"]) is not list
            or len(proof["sdkFacts"]) != 6
        ):
            raise ValueError
        responses = {x["response_id"]: x for x in snapshot["native_responses"]}
        events = {
            x["event_id"]: x for x in snapshot["native_observations"] if x["source"] == "agent_sdk"
        }
        if len(responses) != 3 or len(events) != 6:
            raise ValueError
        anchor_fields = {
            "schemaVersion",
            "responseId",
            "generationId",
            "sdkSpeechId",
            "bindingId",
            "inputId",
            "receiptId",
            "operationKey",
            "caseRevision",
        }
        seen: set[str] = set()
        for recorded in proof["anchors"]:
            if set(recorded) != {"status", "payload", "receipt"} or recorded["status"] != "known":
                raise ValueError
            payload = recorded["payload"]
            key = payload["responseId"]
            if set(payload) != anchor_fields or key in seen:
                raise ValueError
            seen.add(key)
            row = responses[key]
            anchor = native.decode(row["canonical_anchor"].encode(), maximum=8192)
            if not native.exact(payload, {k: anchor[k] for k in anchor_fields}):
                raise ValueError
            receipt = {
                "responseId": key,
                "receiptId": row["receipt_id"],
                "anchorDigest": row["anchor_digest"],
                "responseSequence": str(row["response_sequence"]),
                "acceptedAt": datetime.fromisoformat(row["accepted_at"])
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z"),
            }
            if not native.exact(recorded["receipt"], receipt):
                raise ValueError
        if seen != set(responses):
            raise ValueError
        seen.clear()
        for recorded in proof["sdkFacts"]:
            if set(recorded) != {"status", "payload", "receipt"} or recorded["status"] != "known":
                raise ValueError
            payload = recorded["payload"]
            key = payload["eventId"]
            if key in seen:
                raise ValueError
            seen.add(key)
            row = events[key]
            canonical = row["canonical_payload"]
            if (
                not native.exact(payload, native.decode(canonical.encode(), maximum=8192))
                or hashlib.sha256(canonical.encode()).hexdigest() != row["payload_digest"]
            ):
                raise ValueError
            receipt = {
                "responseId": row["response_id"],
                "eventId": key,
                "receiptId": row["receipt_id"],
                "payloadDigest": row["payload_digest"],
                "observationSequence": str(row["observation_sequence"]),
                "acceptedAt": datetime.fromisoformat(row["accepted_at"])
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z"),
            }
            if not native.exact(recorded["receipt"], receipt):
                raise ValueError
        if seen != set(events):
            raise ValueError
    except (
        KeyError,
        ValueError,
        TypeError,
        AttributeError,
        OverflowError,
        RecursionError,
        GateError,
    ):
        raise GateError("invalid_python_source_proof") from None


def validate_owner_snapshot(
    snapshot: dict[str, Any], browser: dict[str, Any], fixture: dict[str, Any]
) -> None:
    try:
        _validate_owner_snapshot(snapshot, browser, fixture)
    except (
        KeyError,
        ValueError,
        TypeError,
        AttributeError,
        OverflowError,
        RecursionError,
        GateError,
    ):
        raise GateError("invalid_owner_proof") from None


def target_path(root: Path, path: Path) -> Path:
    if (
        path.is_absolute()
        or path.parts[:3] != (".local", "validation", "p2-playback")
        or len(path.parts) != 4
        or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}\.json", path.name)
    ):
        raise GateError("unsafe_report_path")
    current = root
    for part in path.parts[:-1]:
        current /= part
        if current.is_symlink():
            raise GateError("unsafe_report_path")
        if not current.exists():
            current.mkdir(mode=0o700)
        if not current.is_dir() or current.stat().st_mode & 0o022:
            raise GateError("unsafe_report_path")
    target = current / path.name
    if (
        target.exists()
        or target.is_symlink()
        or target.with_name(target.stem + "-artifacts").exists()
    ):
        raise GateError("evidence_exists")
    return target


def fixture_proof(root: Path) -> dict[str, Any]:
    path = root / "projects/channel-continuity/examples/assets/native-status.wav"
    if path.is_symlink():
        raise GateError("invalid_fixture")
    if not path.is_file() or not 0 < path.stat().st_size <= 1048576:
        raise GateError("invalid_fixture")
    raw = path.read_bytes()
    with wave.open(str(path), "rb") as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, 16000):
            raise GateError("invalid_fixture")
        frames = len(array("h", source.readframes(source.getnframes()))[::2])
    if frames != 32932:
        raise GateError("invalid_fixture")
    return {
        "schemaVersion": 1,
        "sourceBytes": len(raw),
        "sourceSha256": hashlib.sha256(raw).hexdigest(),
        "renderedFrames": frames,
        "sampleRate": 16000,
        "durationMs": FIXTURE_MS,
        "pcmThresholdSquared": 0.00000025,
        "triggerMinimumRatio": 0.35,
        "triggerMaximumRatio": 0.65,
        "normalMinimumPcmRatio": 0.75,
        "interruptedFinalMaximumPcmRatio": 0.85,
        "priorQuietRenderedMs": 250,
        "semantics": "continuous_source_response_window_not_physical_speech_or_hearing",
    }


def identity(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


PYTHON_FAILURE_STAGES = frozenset(
    {
        "initializing",
        "configuration",
        "http_binding",
        "waiting_node",
        "rtc_connect",
        "waiting_participant",
        "sdk_start",
        "ready",
        "cleanup",
        "finished",
    }
)
PYTHON_FAILURE_FILES = frozenset(
    {
        "native_lab.py",
        "native_scripted.py",
        "native.py",
        "native_http.py",
        "native_models.py",
        "native_capture.py",
        "native_communication.py",
        "native_rehydration.py",
    }
)
PYTHON_FAILURE_CODES = frozenset(
    {
        "invalid_input",
        "forbidden",
        "idempotency_conflict",
        "capacity_exhausted",
        "dependency_unavailable",
        "acknowledgement_unknown",
        "closed",
    }
)


def validated_python_failure(raw: bytes) -> dict[str, Any]:
    value = native.decode(raw, maximum=4096)
    if (
        set(value) != {"schemaVersion", "status", "mode", "stage", "errorType", "code", "frames"}
        or not native.exact(value["schemaVersion"], 1)
        or value["status"] != "failed"
        or value["mode"] != "serve"
        or type(value["stage"]) is not str
        or value["stage"] not in PYTHON_FAILURE_STAGES
        or type(value["errorType"]) is not str
        or value["errorType"]
        not in {"NativeError", "TimeoutError", "OSError", "RuntimeError", "DependencyError"}
        or (
            value["code"] is not None
            and (type(value["code"]) is not str or value["code"] not in PYTHON_FAILURE_CODES)
        )
        or type(value["frames"]) is not list
        or len(value["frames"]) > 4
    ):
        raise GateError("invalid_failure_context")
    for frame in value["frames"]:
        if (
            type(frame) is not dict
            or set(frame) != {"file", "line"}
            or type(frame["file"]) is not str
            or frame["file"] not in PYTHON_FAILURE_FILES
            or type(frame["line"]) is not int
            or not 1 <= frame["line"] <= 1000000
        ):
            raise GateError("invalid_failure_context")
    return value


def retain_python_failure_safely(
    work: Path, artifacts: Path, children: native.Children, secret_values: tuple[str, ...]
) -> bool:
    """Copy only finite producer/startup fields, after actual child close attempts."""
    try:
        producer = work / "python-failure-context.json"
        if producer.exists() or producer.is_symlink():
            value = validated_python_failure(bounded_read(producer, maximum=4096))
            raw = json.dumps(value, sort_keys=True).encode()
            if any(v.encode() in raw for v in secret_values if v):
                raise GateError("invalid_failure_context")
            native.write_json(artifacts / producer.name, value, maximum=4096)
        startup = work / "native-startup-observations.json"
        if startup.exists() or startup.is_symlink():
            raw = bounded_read(startup, maximum=2048)
            value = native.validate_startup(raw)
            native.write_json(artifacts / "failed-startup-observations.json", value, maximum=2048)
        if not producer.exists():
            # Import/command failures precede the application's main handler.
            # Retain class + owned locations only, never exception messages.
            allowed = {
                "ImportError",
                "ModuleNotFoundError",
                "SyntaxError",
                "OSError",
                "RuntimeError",
                "AttributeError",
                "TypeError",
                "ValueError",
                "NameError",
            }
            for child in children.children:
                if child.output_directory.name != "python-app":
                    continue
                path = child.output_directory / "stderr.bin"
                if not path.exists():
                    continue
                text = bounded_read(path, maximum=4096).decode("utf-8", errors="replace")
                kinds = []
                frames = []
                for line in text.splitlines():
                    kind = re.match(r"^([A-Za-z_][A-Za-z_0-9]*):", line)
                    if kind and kind[1] in allowed:
                        kinds.append(kind[1])
                    frame = re.match(r'\s*File "([^"]+)", line ([0-9]+)', line)
                    if (
                        frame
                        and Path(frame[1]).name in PYTHON_FAILURE_FILES
                        and 1 <= int(frame[2]) <= 1000000
                    ):
                        frames.append({"file": Path(frame[1]).name, "line": int(frame[2])})
                if kinds:
                    native.write_json(
                        artifacts / "python-startup-failure-observation.json",
                        {
                            "schemaVersion": 1,
                            "status": "failed",
                            "source": "owned_python_stderr",
                            "exceptionType": kinds[-1],
                            "frames": frames[-4:],
                        },
                        maximum=2048,
                    )
        return True
    except BaseException:  # noqa: BLE001 - diagnostics cannot replace the primary or skip cleanup.
        return False


def owned_children_settled(children: native.Children) -> bool:
    return all(type(c.returncode) is int and not c.cleanup_failed for c in children.children)


def close_owned_children(children: native.Children) -> None:
    first: BaseException | None = None
    for child in reversed(children.children):
        try:
            child.close()
        except BaseException as error:  # noqa: BLE001 - attempt every independent process owner.
            if first is None:
                first = error
    if first is not None:
        raise first
    if not owned_children_settled(children):
        raise GateError("cleanup_incomplete")


def remove_owned_work(work: Path, scratch: Path, schema: str, owner: str) -> None:
    if (
        work.is_symlink()
        or work.parent != scratch.resolve()
        or re.fullmatch(r"run-[a-z0-9_-]{6,32}", work.name) is None
        or re.fullmatch(r"[a-f0-9]{32}", owner) is None
        or schema != "p2_playback_" + owner
    ):
        raise GateError("cleanup_incomplete")
    value = native.decode(bounded_read(work / "playback-owned-work.json", maximum=512))
    if not native.exact(
        value,
        {"schemaVersion": 1, "schema": schema, "owner": owner, "roomId": "p2-playback-" + owner},
    ):
        raise GateError("cleanup_incomplete")
    shutil.rmtree(work)
    if work.exists():
        raise GateError("cleanup_incomplete")


async def run(
    root: Path,
    artifacts: Path,
    started: float,
    cleanup: dict[str, bool],
    browser_executable: str | None,
) -> dict[str, Any]:
    import aiohttp
    import psycopg
    from livekit import api
    from psycopg import sql

    final_deadline = started + TOTAL_SECONDS
    work_deadline = final_deadline - CLEANUP_SECONDS
    setup = core.load_setup(root)
    values = setup.load_settings()
    project = root / "projects/channel-continuity"
    console = root / "apps/local-console"
    node = shutil.which("node")
    python = root / ".venv/bin/python"
    compiler = project / "node_modules/typescript/bin/tsc"
    if not node or not all(
        p.is_file()
        for p in (
            python,
            compiler,
            project / "examples/native_lab.py",
            console / "node_modules/vite/bin/vite.js",
            console / "node_modules/@playwright/test/cli.js",
        )
    ):
        raise GateError("missing_setup")
    if browser_executable is not None and (
        not Path(browser_executable).is_absolute() or not Path(browser_executable).is_file()
    ):
        raise GateError("missing_browser")
    native.write_json(artifacts / "fixture-proof.json", fixture_proof(root))
    run_id = uuid4().hex
    schema = "p2_playback_" + run_id
    scratch = project / ".local/playback-check"
    core.private_directory(scratch)
    work = Path(tempfile.mkdtemp(prefix="run-", dir=scratch)).resolve()
    os.chmod(work, 0o700)
    try:
        native.write_json(
            work / "playback-owned-work.json",
            {
                "schemaVersion": 1,
                "schema": schema,
                "owner": run_id,
                "roomId": "p2-playback-" + run_id,
            },
        )
        children = native.Children(work, work_deadline)
        python_http = FileBarrier(work, "python_http_ready")
        python_ready = FileBarrier(work, "python_ready")
        node_ready = FileBarrier(work, "node_ready")
        common = {
            "P2_COMM_DIRECTORY": str(work),
            "P2_COMM_SCHEMA": schema,
            "P2_COMM_PG_PORT": values["POSTGRES_PORT"],
        }
        ids = [str(uuid4()) for _ in range(3)]
        fixture: dict[str, Any] = {
            "schemaVersion": 1,
            "providerScope": {
                "tenantId": "native-tenant",
                "provider": "livekit",
                "providerAccountId": "local-native",
            },
            "scope": {"tenantId": "native-tenant", "accountId": "native-account"},
            "caseId": "native-case",
            "conversationId": "native-conversation",
            "bindingId": str(uuid4()),
            "roomId": "p2-playback-" + run_id,
            "participantId": "browser-" + run_id,
            "agentId": "p2-native-agent-" + run_id,
            **{
                k: secrets.token_urlsafe(32)
                for k in ("accountToken", "publisherToken", "bindingToken", "prepareToken")
            },
            "expiresAt": (datetime.now(UTC) + timedelta(seconds=280))
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "ids": {"text": ids[0], "voice": str(uuid4())},
        }
        communication = {
            "schemaVersion": 1,
            **{
                k: secrets.token_urlsafe(32) for k in ("publisherToken", "sdkToken", "browserToken")
            },
            "inputIds": ids,
        }
        media: dict[str, Any] = {
            "url": "ws://127.0.0.1:" + values["LIVEKIT_HTTP_PORT"],
            **{k: fixture[k] for k in ("roomId", "participantId", "agentId", "bindingId")},
            "browserAccessToken": secrets.token_urlsafe(32),
        }
        token_kinds: tuple[tuple[str, Literal["agent", "standard"]], ...] = (
            ("nativeToken", "agent"),
            ("browserToken", "standard"),
        )
        for name, kind in token_kinds:
            media[name] = (
                api.AccessToken(values["LIVEKIT_API_KEY"], values["LIVEKIT_API_SECRET"])
                .with_identity(fixture["agentId" if kind == "agent" else "participantId"])
                .with_kind(kind)
                .with_ttl(timedelta(seconds=240))
                .with_grants(
                    api.VideoGrants(
                        room_join=True,
                        room=fixture["roomId"],
                        can_publish=True,
                        can_subscribe=True,
                        can_publish_data=True,
                        can_update_own_metadata=kind == "agent",
                        can_manage_agent_session=False,
                    )
                )
                .to_jwt()
            )
        exclude = tuple(
            str(v)
            for d in (fixture, communication, media)
            for k, v in d.items()
            if k.endswith("Token")
        ) + tuple(values[k] for k in setup.SECRET_KEYS)
        for name, value in (
            ("fixture.json", fixture),
            ("media.json", media),
            ("communication.json", communication),
        ):
            native.write_json(work / name, value)
        api_client = api.LiveKitAPI(
            url="http://127.0.0.1:" + values["LIVEKIT_HTTP_PORT"],
            api_key=values["LIVEKIT_API_KEY"],
            api_secret=values["LIVEKIT_API_SECRET"],
            timeout=aiohttp.ClientTimeout(total=3),
            failover=False,
        )
        installed = False
        room_attempted = False
        browser_report: dict[str, Any] = {}
        node_report: dict[str, Any] = {}
        python_report: dict[str, Any] = {}
        node_version = ""
        compiled = work / "compiled"
        script = compiled / "tests/pg_communication_cases.js"

        def stage(mode: str, *, deadline: float | None = None) -> dict[str, Any]:
            return validated_stage(
                children.call(
                    mode,
                    [node, str(script), mode],
                    child_environment(values, common, mode),
                    cwd=work,
                    deadline=deadline,
                ),
                mode,
            )

        try:
            children.call(
                "compile",
                [
                    node,
                    str(compiler),
                    "--project",
                    str(project / "tsconfig.pg.json"),
                    "--outDir",
                    str(compiled),
                ],
                core.base_environment(),
                cwd=project,
            )
            native.write_json(
                artifacts / "runtime-build-parity.json",
                native.verify_runtime_build(project, compiled),
            )
            installed = True
            node_version = stage("media-install")["nodeVersion"]
            stage("media-seed")
            room_attempted = True
            await api_client.room.create_room(
                api.CreateRoomRequest(
                    name=fixture["roomId"],
                    empty_timeout=180,
                    departure_timeout=10,
                    max_participants=3,
                    metadata=json.dumps({"profile": "p2-playback-lab", "owner": run_id}),
                )
            )
            python_child = children.start(
                "python-app",
                [str(python), "-I", str(project / "examples/native_lab.py"), str(work)],
                {**core.base_environment(), "P2_NATIVE_DIRECTORY": str(work)},
                cwd=work,
            )
            python_child.wait_for_barrier(
                python_http,
                timeout=min(15, native.remaining(work_deadline)),
            )
            python_port = native.endpoint(work / "python-endpoint.json")
            node_child = children.start(
                "node-app",
                [node, str(script), "media-serve"],
                child_environment(values, common, "media-serve"),
                cwd=work,
            )
            node_child.wait_for_barrier(
                node_ready, timeout=min(15, native.remaining(work_deadline))
            )
            native.endpoint(work / "node-endpoint.json")
            ui_port = native.free_port()
            vite_child = children.start(
                "vite",
                [
                    node,
                    str(console / "node_modules/vite/bin/vite.js"),
                    "--config",
                    str(console / "vite.native.config.ts"),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(ui_port),
                    "--strictPort",
                ],
                {
                    **core.base_environment(),
                    "P2_NATIVE_HTTP_ORIGIN": "http://127.0.0.1:" + str(python_port),
                },
                cwd=console,
            )
            until = min(work_deadline, time.monotonic() + 10)
            while True:
                if vite_child.returncode is not None:
                    raise GateError("browser_server_failed")
                try:
                    with socket.create_connection(("127.0.0.1", ui_port), timeout=0.2):
                        break
                except OSError:
                    if time.monotonic() >= until:
                        raise GateError("browser_server_unavailable") from None
                    await asyncio.sleep(0.01)
            browser_output = work / "browser-report"
            browser_output.mkdir(mode=0o700)
            env = {
                **core.base_environment(),
                "P2_NATIVE_BROWSER_ORIGIN": "http://127.0.0.1:" + str(ui_port),
                "P2_NATIVE_BROWSER_OUTPUT": str(browser_output),
                "P2_NATIVE_BROWSER_ACCESS": media["browserAccessToken"],
                "P2_PLAYBACK_NORMAL_ID": ids[0],
                "P2_PLAYBACK_INTERRUPT_ID": ids[1],
                "P2_PLAYBACK_MISSING_ID": ids[2],
                "P2_PLAYBACK_FIXTURE_MS": str(FIXTURE_MS),
            }
            if browser_executable is not None:
                env["PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"] = browser_executable
            children.call(
                "browser",
                [
                    node,
                    str(console / "node_modules/@playwright/test/cli.js"),
                    "test",
                    "--config",
                    str(console / "playwright.playback.config.ts"),
                    "--global-timeout",
                    "120000",
                ],
                env,
                cwd=console,
            )
            python_child.wait_for_barrier(
                python_ready, timeout=min(1, native.remaining(work_deadline))
            )
            native.validate_startup(
                (work / "native-startup-observations.json").read_bytes(), require_ready=True
            )
            browser_report = validated_browser(
                (browser_output / "playback-browser-observations.json").read_bytes()
            )
            pw = native.decode((browser_output / "playwright.json").read_bytes(), maximum=1048576)
            if pw.get("stats", {}).get("expected") != 1 or any(
                pw["stats"].get(k) != 0 for k in ("unexpected", "flaky", "skipped")
            ):
                raise GateError("invalid_browser_report")
            native.write_json(artifacts / "playwright-stats.json", pw["stats"])
            python_report = validated_python(children.stop(python_child, deadline=work_deadline))
            node_report = validated_stage(
                children.stop(node_child, deadline=work_deadline), "media-serve"
            )
            children.stop(vite_child, deadline=work_deadline, require_zero=False)
            validated_node_ownership(bounded_read(work / "communication-node-private-proof.json"))
            stage("media-verify")
            with closing(
                psycopg.connect(
                    host="127.0.0.1",
                    port=int(values["POSTGRES_PORT"]),
                    dbname="livekit_lab",
                    user="continuity_migrator",
                    password=values["POSTGRES_MIGRATION_PASSWORD"],
                    sslmode="disable",
                    connect_timeout=2,
                    options="-c statement_timeout=3000 -c search_path=pg_catalog",
                    autocommit=True,
                )
            ) as conn:
                owner = conn.execute(
                    "SELECT pg_get_userbyid(nspowner),obj_description(oid,'pg_namespace') FROM pg_namespace WHERE nspname=%s",
                    [schema],
                ).fetchone()
                if owner != ("continuity_migrator", "p2-channel-schema-v7"):
                    raise GateError("owner_mismatch")
                snapshot = {
                    name: conn.execute(
                        sql.SQL(
                            "SELECT to_jsonb(t) FROM {}.{} t ORDER BY to_jsonb(t)::text"
                        ).format(sql.Identifier(schema), sql.Identifier(name))
                    ).fetchall()
                    for name in (
                        "native_responses",
                        "native_observations",
                        "communication_settings",
                        "inbox",
                        "processing_intents",
                        "dispatch_plans",
                    )
                }
            snapshot = {name: [r[0] for r in rows] for name, rows in snapshot.items()}
            if len(snapshot["native_responses"]) != 3 or len(snapshot["native_observations"]) != 10:
                raise GateError("owner_inventory_mismatch")
            validate_owner_snapshot(snapshot, browser_report, fixture)
            validate_python_source_proof(
                bounded_read(work / "communication-python-source-proof.json", maximum=1048576),
                snapshot,
            )
            if any(
                secret.encode() in json.dumps(snapshot, sort_keys=True).encode()
                for secret in exclude
            ):
                raise GateError("private_artifact")
            native.write_json(artifacts / "owner-snapshot.json", snapshot, maximum=2097152)
            for name in (
                "communication-owner-proof.json",
                "communication-node-private-proof.json",
                "communication-python-source-proof.json",
                "communication-operations.json",
                "node-terminal.json",
                "python-terminal.json",
                "python-private-proof.json",
                "native-startup-observations.json",
            ):
                native.safe_copy(work / name, artifacts / name, exclude)
            for name in (
                "playback-browser-observations.json",
                "playback-browser-context.json",
                "playback-interrupted.png",
            ):
                native.safe_copy(browser_output / name, artifacts / name, exclude)
            native.safe_copy(script, artifacts / "pg_communication_cases.js", exclude)
            native.write_json(artifacts / "native-node-report.json", node_report)
            native.write_json(artifacts / "native-python-report.json", python_report)
        finally:
            primary = sys.exception()
            failed = False
            children.deadline = final_deadline
            for child in reversed(children.children):
                if child.returncode is None:
                    try:
                        children.stop(
                            child,
                            deadline=min(final_deadline, time.monotonic() + 3),
                            require_zero=child.output_directory.name != "vite",
                        )
                    except BaseException:  # noqa: BLE001 - Complete every independently owned cleanup.
                        failed = True
            try:
                close_owned_children(children)
            except BaseException:  # noqa: BLE001 - actual child settlement gates dependent cleanup.
                failed = True
            settled = owned_children_settled(children)
            if not settled:
                failed = True
            if primary is not None:
                # Keep only fixed, body-free failure metadata; raw captures remain ephemeral.
                try:
                    native.write_json(
                        artifacts / "failure-context.json",
                        {
                            "schemaVersion": 1,
                            "status": "failed",
                            "code": primary.code
                            if isinstance(primary, GateError)
                            else "gate_failed",
                            "children": [
                                {"name": c.output_directory.name, "returncode": c.returncode}
                                for c in children.children
                            ],
                        },
                    )
                except (OSError, GateError):
                    failed = True
            if primary is not None:
                try:
                    context_path = work / "browser-report/playback-browser-context.json"
                    if context_path.exists():
                        native.write_json(
                            artifacts / "playback-browser-failure-context.json",
                            validated_browser_context(bounded_read(context_path, maximum=16384)),
                            maximum=16384,
                        )
                except Exception:  # noqa: BLE001 - Diagnostic failure cannot replace the primary error.
                    cleanup["diagnostic_context_rejected"] = True
                diagnostics.retain_safely(work, artifacts, children.children, primary, exclude)
                if not retain_python_failure_safely(work, artifacts, children, exclude):
                    cleanup["python_diagnostic_context_rejected"] = True
                    failed = True
            if installed and settled:
                try:
                    stage("media-cleanup", deadline=final_deadline)
                except BaseException:  # noqa: BLE001 - Preserve the original failure.
                    failed = True
            elif installed:
                failed = True
            if room_attempted and settled:
                try:
                    rooms = await api_client.room.list_rooms(
                        api.ListRoomsRequest(names=[fixture["roomId"]])
                    )
                    for item in rooms.rooms:
                        if item.name != fixture["roomId"] or json.loads(item.metadata) != {
                            "profile": "p2-playback-lab",
                            "owner": run_id,
                        }:
                            raise GateError("room_ownership_mismatch")
                        await api_client.room.delete_room(api.DeleteRoomRequest(room=item.name))
                    if (
                        await api_client.room.list_rooms(
                            api.ListRoomsRequest(names=[fixture["roomId"]])
                        )
                    ).rooms:
                        raise GateError("room_cleanup_incomplete")
                except BaseException:  # noqa: BLE001 - Preserve cleanup of remaining owners.
                    failed = True
            elif room_attempted:
                failed = True

            async def close_children() -> None:
                close_owned_children(children)

            await native.cleanup_actions((api_client.aclose, close_children), cleanup, primary)
            cleanup["cleanup_complete"] = (
                cleanup["cleanup_complete"] and not failed and owned_children_settled(children)
            )
            if not cleanup["cleanup_complete"] and primary is None:
                raise GateError("cleanup_incomplete")
        if not cleanup["cleanup_complete"]:
            raise GateError("cleanup_incomplete")
        proofs = {
            name: identity(artifacts / path)
            for name, path in {
                "owner_snapshot": "owner-snapshot.json",
                "browser": "playback-browser-observations.json",
                "node": "native-node-report.json",
                "node_ownership": "communication-node-private-proof.json",
                "python_source": "communication-python-source-proof.json",
                "python": "native-python-report.json",
                "fixture": "fixture-proof.json",
            }.items()
        }
        return validated_report(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "passed",
                    "mode": MODE,
                    "tests": 3,
                    "passed": 3,
                    "failures": 0,
                    "errors": 0,
                    "skipped": 0,
                    "cleanup_complete": True,
                    "case_results": [
                        {"name": n, "status": "passed", "code": "ok"} for n in CASE_NAMES
                    ],
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
                    "duration_seconds": time.monotonic() - started,
                    "node_version": node_version,
                    "child_commands": children.count,
                    "proofs": proofs,
                }
            ).encode()
        )

    finally:
        primary = sys.exception()
        removal_failed = False
        if cleanup["cleanup_complete"]:
            try:
                native.remaining(final_deadline)
                remove_owned_work(work, scratch, schema, run_id)
            except BaseException:  # noqa: BLE001 - retain original failure and unresolved private inputs.
                cleanup["cleanup_complete"] = False
                removal_failed = True
        if not cleanup["cleanup_complete"]:
            try:
                native.write_json(
                    artifacts / "owned-work-retained.json",
                    {
                        "schemaVersion": 1,
                        "directory": str(work.relative_to(root)),
                        "schema": schema,
                        "roomId": "p2-playback-" + run_id,
                        "owner": run_id,
                        "cleanupComplete": False,
                    },
                )
            except BaseException:  # noqa: BLE001 - a failed diagnostic sink cannot replace primary.
                cleanup["retained_work_context_rejected"] = True
        if removal_failed and primary is None:
            raise GateError("cleanup_incomplete") from None


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--browser-executable")
    args = parser.parse_args(argv)
    started = time.monotonic()
    cleanup = {"cleanup_complete": False}
    target = None
    try:
        target = target_path(
            root, args.report or Path(".local/validation/p2-playback/" + uuid4().hex + ".json")
        )
        artifacts = target.with_name(target.stem + "-artifacts")
        artifacts.mkdir(mode=0o700)
        value = asyncio.run(run(root, artifacts, started, cleanup, args.browser_executable))
    except (GateError, core.GateError) as error:
        value = {
            "status": "failed",
            "mode": MODE,
            "code": error.code,
            "duration_seconds": time.monotonic() - started,
            **cleanup,
        }
    except Exception:  # noqa: BLE001 - Never reflect raw exception data.
        value = {
            "status": "failed",
            "mode": MODE,
            "code": "gate_failed",
            "duration_seconds": time.monotonic() - started,
            **cleanup,
        }
    try:
        if target is not None:
            native.write_json(target, value)
    except (OSError, GateError):
        value = {"status": "failed", "mode": MODE, "code": "evidence_not_retained", **cleanup}
    print(json.dumps(value, sort_keys=True))
    return 0 if value["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
