"""Explicit scripted native room-to-SMS-to-new-room qualification; no import I/O."""

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
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p2_native_check as native
import p2_playback_check as previous
import p2_rehydration_check as storage
import p3_coordinator_check as core

from harness.process_control import FileBarrier, OwnedProcess

ROOT = Path(__file__).resolve().parents[2]
GateError = native.GateError
MODE = "local_scripted_p2_rehydration_media"
CASE_NAMES = (
    "room_a_real_voice_text_original_receipts",
    "dormant_sms_current_case_revision",
    "fresh_room_b_rehydration_and_new_reply",
)
NODE_METRICS = {
    "accepted": 3,
    "replayed": 0,
    "dispatched": 3,
    "active": 0,
    "intakes": 0,
    "sockets": 0,
    "handlers": 0,
    "driver": 0,
    "observerPending": 0,
}
COMM_METRICS = {
    "responsesAccepted": 3,
    "responsesReplayed": 0,
    "observationsAccepted": 6,
    "observationsReplayed": 0,
    "identityConflicts": 0,
    "rejected": 0,
    "unknownAcknowledgements": 0,
    "capacityRejected": 0,
    "telemetryFailures": 0,
    "observerPending": 0,
    "observerDropped": 0,
}
TOTAL_SECONDS = 240
CLEANUP_SECONDS = 20


class Children(native.Children):
    def start(
        self, name: str, argv: list[str], environment: dict[str, str], *, cwd: Path
    ) -> OwnedProcess:
        if self.count >= 32 or re.fullmatch(r"[a-z0-9-]{1,48}", name) is None:
            raise GateError("child_budget")
        native.remaining(self.deadline)
        self.count += 1
        wrapper = "import os,sys;os.umask(0o077);os.execv(sys.argv[1],sys.argv[1:])"
        child = OwnedProcess(
            [sys.executable, "-I", "-c", wrapper, *argv],
            cwd=cwd,
            env=environment,
            output_directory=self.work / name,
            max_output_bytes=8192,
        )
        self.children.append(child)
        return child


def target_path(root: Path, path: Path) -> Path:
    if (
        path.is_absolute()
        or path.parts[:3] != (".local", "validation", "p2-rehydration-media")
        or len(path.parts) != 4
        or re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}\.json", path.name) is None
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


def source_snapshot(root: Path) -> dict[str, str]:
    result = storage.source_snapshot(root)
    paths = [
        root / "local-setup/scripts/p2_rehydration_media_check.py",
        root / "projects/channel-continuity/examples/rehydration_lab.py",
        root / "projects/channel-continuity/examples/native_lab.py",
        root / "projects/channel-continuity/examples/native_scripted.py",
    ]
    paths.extend(
        sorted(
            path
            for path in (root / "apps/local-console/src").rglob("*")
            if path.suffix in {".ts", ".css"}
        )
    )
    paths.extend(
        root / "apps/local-console" / name
        for name in (
            "p2-native.html",
            "vite.native.config.ts",
            "playwright.rehydration.config.ts",
            "e2e/p2-rehydration.media.ts",
        )
    )
    for path in paths:
        result[str(path.relative_to(root))] = hashlib.sha256(storage.source_bytes(path)).hexdigest()
    return dict(sorted(result.items()))


def _validated_browser(raw: bytes, fixture: dict[str, Any]) -> dict[str, Any]:
    value = native.decode(raw, maximum=32768)
    fixed = {
        "schemaVersion": 1,
        "status": "passed",
        "mode": "local_scripted_p2_rehydration_browser",
        "groups": list(CASE_NAMES),
        "smsKnown": True,
        "refreshFailureRetained": True,
        "actualBrowserAudio": True,
        "physicalHearingClaimed": False,
        "readOnlyLoadGeneratedReplies": 0,
        "cleanupComplete": True,
        "pageErrors": 0,
        "unexpectedNetworkRequests": 0,
    }
    if set(value) != set(fixed) | {"sessions"} or any(
        not native.exact(value[k], v) for k, v in fixed.items()
    ):
        raise GateError("invalid_browser_report")
    sessions = value["sessions"]
    if type(sessions) is not dict or set(sessions) != {"A", "B"}:
        raise GateError("invalid_browser_report")
    a, b = sessions["A"], sessions["B"]
    if (
        type(a) is not dict
        or set(a) != {"bindingId", "contextId", "caseRevision", "inputs", "responses"}
        or type(b) is not dict
        or set(b)
        != {
            "bindingId",
            "contextId",
            "caseRevision",
            "historyReceipts",
            "historyChannels",
            "historicalResponses",
            "input",
            "response",
        }
    ):
        raise GateError("invalid_browser_report")
    for name, item, revision in (("A", a, "1"), ("B", b, "2")):
        if (
            item["bindingId"] != fixture["bindings"][name]["bindingId"]
            or not previous.is_uuid(item["contextId"])
            or item["caseRevision"] != revision
        ):
            raise GateError("invalid_browser_report")
    if (
        type(a["inputs"]) is not list
        or len(a["inputs"]) != 2
        or type(a["responses"]) is not list
        or len(a["responses"]) != 2
    ):
        raise GateError("invalid_browser_report")
    inputs = [*a["inputs"], b["input"]]
    responses = [*a["responses"], b["response"]]
    for row, key, channel in zip(
        inputs,
        ("voice", "text", "newText"),
        ("voice_transcript", "web_chat", "web_chat"),
        strict=True,
    ):
        if (
            type(row) is not dict
            or set(row)
            != {"inputId", "channel", "status", "receiptId", "operationKey", "acceptanceSequence"}
            or row["inputId"] != fixture["ids"][key]
            or row["channel"] != channel
            or row["status"] != "accepted"
            or not all(previous.is_uuid(row[k]) for k in ("inputId", "receiptId", "operationKey"))
            or type(row["acceptanceSequence"]) is not str
            or re.fullmatch(r"[1-9][0-9]{0,18}", row["acceptanceSequence"]) is None
        ):
            raise GateError("invalid_browser_report")
    for row, item in zip(responses, inputs, strict=True):
        if (
            type(row) is not dict
            or set(row)
            != {
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
            or row["inputId"] != item["inputId"]
            or row["operationKey"] != item["operationKey"]
            or not all(
                previous.is_uuid(row[k])
                for k in ("responseId", "generationId", "inputId", "operationKey")
            )
            or type(row["sdkSpeechId"]) is not str
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", row["sdkSpeechId"]) is None
            or not native.exact(row["observationCount"], 2)
            or row["generated_observed"] is not True
            or row["sdk_state"] != "completed"
            or row["browser_state"] != "unknown"
            or row["conflicted"] is not False
            or any(
                type(row[k]) is not int or not 0 <= row[k] <= 180000
                for k in ("observed_audio_ms", "sampled_audio_ms")
            )
            or row["sampled_audio_ms"] < row["observed_audio_ms"]
            or row["observed_audio_ms"] <= 100
        ):
            raise GateError("invalid_browser_report")
    if (
        any(
            len({row[k] for row in responses}) != 3
            for k in ("responseId", "generationId", "sdkSpeechId")
        )
        or len({row["receiptId"] for row in inputs}) != 3
        or len({row["operationKey"] for row in inputs}) != 3
    ):
        raise GateError("invalid_browser_report")
    if (
        type(b["historyReceipts"]) is not list
        or len(b["historyReceipts"]) != 3
        or not all(previous.is_uuid(v) for v in b["historyReceipts"])
        or len(set(b["historyReceipts"])) != 3
        or not {row["receiptId"] for row in a["inputs"]} <= set(b["historyReceipts"])
        or type(b["historyChannels"]) is not list
        or len(b["historyChannels"]) != 3
        or not all(type(v) is str for v in b["historyChannels"])
        or set(b["historyChannels"]) != {"voice_transcript", "web_chat", "sms"}
        or type(b["historicalResponses"]) is not list
        or len(b["historicalResponses"]) != 2
    ):
        raise GateError("invalid_browser_report")
    expected = {row["responseId"]: row for row in a["responses"]}
    for row in b["historicalResponses"]:
        if (
            type(row) is not dict
            or set(row)
            != {
                "responseId",
                "bindingId",
                "generationId",
                "sdkSpeechId",
                "sdkState",
                "browserState",
                "historical",
            }
            or not previous.is_uuid(row["responseId"])
            or row["responseId"] not in expected
            or row["bindingId"] != a["bindingId"]
            or row["generationId"] != expected[row["responseId"]]["generationId"]
            or row["sdkSpeechId"] != expected[row["responseId"]]["sdkSpeechId"]
            or row["sdkState"] != "completed"
            or row["browserState"] != "unknown"
            or row["historical"] is not True
        ):
            raise GateError("invalid_browser_report")
    if {row["responseId"] for row in b["historicalResponses"]} != set(expected):
        raise GateError("invalid_browser_report")
    return value


def _validated_sms(raw: bytes, fixture: dict[str, Any]) -> dict[str, Any]:
    value = native.decode(raw, maximum=2048)
    if (
        set(value)
        != {
            "schemaVersion",
            "status",
            "smsAccepted",
            "caseRevision",
            "receiptId",
            "operationKey",
            "eventId",
        }
        or not native.exact(value["schemaVersion"], 1)
        or value["status"] != "passed"
        or not native.exact(value["smsAccepted"], 1)
        or value["caseRevision"] != "2"
        or value["eventId"] != fixture["ids"]["sms"]
        or not all(previous.is_uuid(value[k]) for k in ("receiptId", "operationKey", "eventId"))
    ):
        raise GateError("invalid_sms_report")
    return value


def _validated_node(raw: bytes) -> dict[str, Any]:
    value = native.decode(raw, maximum=32768)
    expected = {
        "schemaVersion": 1,
        "status": "passed",
        "mode": "media-serve",
        "nodeVersion": "24.22.2",
        "storageVersion": 7,
        "cleanupComplete": True,
        "metrics": NODE_METRICS,
        "communicationMetrics": COMM_METRICS,
    }
    if set(value) != set(expected) | {"rehydrationMetrics", "readHttpMetrics"} or any(
        not native.exact(value[k], v) for k, v in expected.items()
    ):
        raise GateError("invalid_node_report")
    for name, keys in (
        (
            "rehydrationMetrics",
            {
                "started",
                "known",
                "denied",
                "invalid",
                "unavailable",
                "overloaded",
                "waiterRejected",
                "telemetryFailures",
                "observerDropped",
                "active",
                "observerPending",
            },
        ),
        ("readHttpMetrics", {"started", "known", "rejected", "sockets", "handlers"}),
    ):
        metrics = value[name]
        if (
            type(metrics) is not dict
            or set(metrics) != keys
            or any(type(v) is not int or not 0 <= v <= 128 for v in metrics.values())
            or any(
                metrics[k] != 0 for k in keys & {"active", "observerPending", "sockets", "handlers"}
            )
        ):
            raise GateError("invalid_node_report")
    return value


def _validated_browser_context(raw: bytes) -> dict[str, Any]:
    value = native.decode(raw, maximum=16384)
    if (
        set(value)
        != {
            "schemaVersion",
            "stage",
            "groups",
            "pageErrors",
            "unexpectedNetworkRequests",
            "connection",
            "ready",
            "phase",
            "caseRevision",
            "inputStates",
            "responseStates",
        }
        or not native.exact(value["schemaVersion"], 1)
        or value["stage"]
        not in {
            "initializing",
            "authentication",
            "join_a",
            "voice_a",
            "chat_a",
            "refresh_a",
            "end_a",
            "sms",
            "join_b",
            "new_reply_b",
            "end_b",
            "complete",
        }
        or type(value["groups"]) is not list
        or value["groups"] != list(CASE_NAMES)[: len(value["groups"])]
        or any(
            type(value[k]) is not int or not 0 <= value[k] <= 1000
            for k in ("pageErrors", "unexpectedNetworkRequests")
        )
    ):
        raise GateError("invalid_browser_context")
    if value["connection"] is not None and (
        type(value["connection"]) is not str
        or value["connection"]
        not in {
            "Disconnected",
            "Joining",
            "Connected",
            "Reconnecting",
            "Closing",
            "Cleanup incomplete",
        }
    ):
        raise GateError("invalid_browser_context")
    if value["ready"] is not None and type(value["ready"]) is not bool:
        raise GateError("invalid_browser_context")
    if value["caseRevision"] is not None and (
        type(value["caseRevision"]) is not str
        or re.fullmatch(r"0|[1-9][0-9]{0,18}", value["caseRevision"]) is None
    ):
        raise GateError("invalid_browser_context")
    if value["phase"] is not None and (
        type(value["phase"]) is not str
        or value["phase"] not in {"empty", "loading", "ready", "unavailable", "ended"}
    ):
        raise GateError("invalid_browser_context")
    inputs = value["inputStates"]
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
    responses = value["responseStates"]
    if responses is not None:
        if type(responses) is not list or len(responses) > 3:
            raise GateError("invalid_browser_context")
        for row in responses:
            if (
                type(row) is not dict
                or set(row) != {"sdkState", "browserState", "generated", "observedAudioMs"}
                or type(row["sdkState"]) is not str
                or row["sdkState"] not in {"unknown", "completed", "interrupted", "conflicted"}
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
                or type(row["generated"]) is not bool
                or type(row["observedAudioMs"]) is not int
                or not 0 <= row["observedAudioMs"] <= 180000
            ):
                raise GateError("invalid_browser_context")
    return value


def _validated_session(value: object, label: str, f: dict[str, Any]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {
        "schemaVersion",
        "label",
        "bindingId",
        "cleanupComplete",
        "sdkClosed",
        "roomClosed",
        "metrics",
        "communicationMetrics",
        "rehydrationMetrics",
        "contextClientMetrics",
        "modelCalls",
        "modelContexts",
        "sttFrames",
        "sttAudioSeconds",
        "ttsFrames",
        "ttsSourceRateMultiplier",
    }:
        raise GateError("invalid_python_session")
    count = 2 if label == "A" else 1
    if (
        not native.exact(value["schemaVersion"], 1)
        or value["label"] != label
        or value["bindingId"] != f["bindings"][label]["bindingId"]
        or any(value[k] is not True for k in ("cleanupComplete", "sdkClosed", "roomClosed"))
        or not native.exact(value["modelCalls"], count)
        or not native.exact(value["ttsSourceRateMultiplier"], 2)
    ):
        raise GateError("invalid_python_session")
    expected = {k: 0 for k in native.PYTHON_METRICS}
    expected.update(
        {
            "textStreamsSeen": 1,
            "durableAcceptCalls": count,
            "nativeInputsAccepted": count,
            "nativeGenerationAttempts": count,
            "nativeGeneratedReplies": count,
            "voiceCaptures": int(label == "A"),
            "voiceCommits": int(label == "A"),
            "genuineFinalSnapshots": int(label == "A"),
        }
    )
    if not native.exact(value["metrics"], expected):
        raise GateError("invalid_python_session")
    comm = {
        "activeNodes": 0,
        "activeProducers": 0,
        "activePublications": 0,
        "activeReports": 0,
        "anchorsKnown": count,
        "browserReportsKnown": 0,
        "generatedFactsKnown": count,
        "observerFailures": 0,
        "rejectedReports": 0,
        "sdkFactsKnown": count,
        "unknownAcknowledgements": 0,
    }
    if not native.exact(value["communicationMetrics"], comm):
        raise GateError("invalid_python_session")
    metrics = value["rehydrationMetrics"]
    if (
        type(metrics) is not dict
        or set(metrics) != {"loads", "loaded", "failed", "revisionMismatch", "active"}
        or any(type(v) is not int or not 0 <= v <= 16 for v in metrics.values())
        or metrics["loaded"] != metrics["loads"]
        or not 1 <= metrics["loads"] <= 16
        or any(metrics[k] != 0 for k in ("failed", "revisionMismatch", "active"))
    ):
        raise GateError("invalid_python_session")
    client = value["contextClientMetrics"]
    if (
        type(client) is not dict
        or set(client) != {"started", "known", "unavailable", "active"}
        or any(type(v) is not int or not 0 <= v <= 16 for v in client.values())
        or client["started"] != metrics["loads"]
        or client["known"] != client["started"]
        or client["active"] != 0
        or client["unavailable"] != 0
    ):
        raise GateError("invalid_python_session")
    models = value["modelContexts"]
    if type(models) is not list or len(models) != count:
        raise GateError("invalid_python_session")
    for row in models:
        if (
            type(row) is not dict
            or set(row)
            != {"contextId", "caseId", "revision", "sourceRevision", "historyReceiptIds"}
            or not previous.is_uuid(row["contextId"])
            or row["caseId"] != f["caseId"]
            or row["revision"] != ("1" if label == "A" else "2")
            or type(row["sourceRevision"]) is not str
            or re.fullmatch(r"[a-f0-9]{64}", row["sourceRevision"]) is None
            or type(row["historyReceiptIds"]) is not list
            or len(row["historyReceiptIds"]) != (0 if label == "A" else 3)
            or not all(previous.is_uuid(v) for v in row["historyReceiptIds"])
        ):
            raise GateError("invalid_python_session")
    if (
        type(value["sttFrames"]) is not int
        or not 0 <= value["sttFrames"] <= 16000
        or type(value["ttsFrames"]) is not int
        or not 1 <= value["ttsFrames"] <= 16000
        or type(value["sttAudioSeconds"]) not in (int, float)
        or not math.isfinite(value["sttAudioSeconds"])
        or not 0 <= value["sttAudioSeconds"] <= 180
        or (label == "A" and (value["sttFrames"] == 0 or value["sttAudioSeconds"] <= 0))
        or (label == "B" and (value["sttFrames"] != 0 or value["sttAudioSeconds"] != 0))
    ):
        raise GateError("invalid_python_session")
    return value


def _validated_python(raw: bytes, f: dict[str, Any]) -> dict[str, Any]:
    value = native.decode(raw, maximum=32768)
    fixed = {
        "schemaVersion": 1,
        "status": "passed",
        "mode": "rehydration-serve",
        "cleanupComplete": True,
        "httpClosed": True,
        "smsRequests": 1,
        "smsKnown": True,
    }
    if (
        set(value) != set(fixed) | {"sessions"}
        or any(not native.exact(value[k], v) for k, v in fixed.items())
        or type(value["sessions"]) is not dict
        or set(value["sessions"]) != {"A", "B"}
    ):
        raise GateError("invalid_python_report")
    for label in ("A", "B"):
        validated_session(value["sessions"][label], label, f)
    return value


def _validated_python_failure(raw: bytes) -> dict[str, Any]:
    value = native.decode(raw, maximum=4096)
    if (
        set(value)
        != {"schemaVersion", "status", "mode", "stage", "errorType", "code", "cleanupComplete"}
        or not native.exact(value["schemaVersion"], 1)
        or value["status"] != "failed"
        or value["mode"] != "rehydration-serve"
        or type(value["stage"]) is not str
        or value["stage"]
        not in {
            "http_binding",
            "waiting_node",
            "rtc_connect",
            "waiting_participant",
            "sdk_start",
            "ready",
            "serving",
            "cleanup",
            "closed",
        }
        or type(value["errorType"]) is not str
        or value["errorType"]
        not in {"NativeError", "TimeoutError", "OSError", "CancelledError", "DependencyError"}
        or type(value["cleanupComplete"]) is not bool
    ):
        raise GateError("invalid_python_failure")
    if value["code"] is not None and (
        value["errorType"] != "NativeError"
        or type(value["code"]) is not str
        or value["code"]
        not in {
            "invalid_input",
            "forbidden",
            "idempotency_conflict",
            "capacity_exhausted",
            "dependency_unavailable",
            "acknowledgement_unknown",
            "closed",
        }
    ):
        raise GateError("invalid_python_failure")
    return value


def _reference_digest(f: dict[str, Any], revision: str) -> str:
    request = {
        "schemaVersion": 1,
        "kind": "booking_investigation",
        "bookingReference": f["referenceRequest"]["bookingReference"],
        "newCheckIn": f["referenceRequest"]["newCheckIn"] if revision == "1" else "2030-01-13",
        "investigationConsent": True,
    }
    value = {
        "schemaVersion": 1,
        "source": "standalone_reference_v1",
        "scope": {"tenantId": f["scope"]["tenantId"], "accountId": f["scope"]["accountId"]},
        "caseId": f["caseId"],
        "conversationId": f["conversationId"],
        "revision": revision,
        "request": request,
        "workflow": None,
        "intent": {"state": "not_committed", "intentId": None},
        "mutation": {
            "state": "not_observed",
            "outcome": "not_observed",
            "cancellation": "not_observed",
            "effectId": None,
            "outcomeEventId": None,
        },
        "supplierResult": None,
    }
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def validate_owner(
    snapshot: dict[str, Any],
    browser: dict[str, Any],
    python: dict[str, Any],
    f: dict[str, Any],
    sms: dict[str, Any],
    operations: object,
) -> None:
    from channel_continuity.codec import (
        AccountScope,
        ProviderScope,
        TrustedPrincipal,
        parse_event_json,
    )

    counts = {
        "inbox": 4,
        "processing_intents": 4,
        "dispatch_plans": 4,
        "native_bindings": 2,
        "native_responses": 3,
        "native_observations": 6,
    }
    if (
        any(type(snapshot.get(k)) is not list or len(snapshot[k]) != n for k, n in counts.items())
        or type(operations) is not list
        or len(operations) != 4
    ):
        raise GateError("owner_inventory_mismatch")
    rows = {r["receipt_id"]: r for r in snapshot["inbox"]}
    intents = {r["receipt_id"]: r for r in snapshot["processing_intents"]}
    plans = {r["receipt_id"]: r for r in snapshot["dispatch_plans"]}
    bindings = {r["binding_id"]: r for r in snapshot["native_bindings"]}
    for label in ("A", "B"):
        expected = f["bindings"][label]
        binding = bindings.get(expected["bindingId"])
        if (
            binding is None
            or binding["room_id"] != expected["roomId"]
            or binding["participant_id"] != expected["participantId"]
            or binding["tenant_id"] != f["scope"]["tenantId"]
            or binding["account_id"] != f["scope"]["accountId"]
            or binding["case_id"] != f["caseId"]
            or binding["conversation_id"] != f["conversationId"]
            or binding["provider"] != "livekit"
            or binding["provider_account_id"] != f["providerScope"]["providerAccountId"]
            or hashlib.sha256(binding["canonical_binding"].encode()).hexdigest()
            != binding["binding_digest"]
            or hashlib.sha256(expected["bindingToken"].encode()).hexdigest()
            != binding["bearer_digest"]
        ):
            raise GateError("owner_binding_mismatch")
        expected_binding = {
            "schemaVersion": 1,
            "bindingId": expected["bindingId"],
            "providerScope": f["providerScope"],
            "scope": f["scope"],
            "caseId": f["caseId"],
            "conversationId": f["conversationId"],
            "roomId": expected["roomId"],
            "participantId": expected["participantId"],
            "expiresAt": f["expiresAt"],
        }
        if not native.exact(json.loads(binding["canonical_binding"]), expected_binding):
            raise GateError("owner_binding_mismatch")
    inputs = [*browser["sessions"]["A"]["inputs"], browser["sessions"]["B"]["input"]]
    for item, label, expected_sequence in zip(
        inputs, ("A", "A", "B"), ("1", "2", "4"), strict=True
    ):
        row = rows.get(item["receiptId"])
        if (
            row is None
            or row["event_id"] != item["inputId"]
            or row["message_id"] != item["inputId"]
            or str(row["acceptance_sequence"]) != expected_sequence
            or item["acceptanceSequence"] != expected_sequence
            or row["provider"] != "livekit"
            or row["provider_account_id"] != f["providerScope"]["providerAccountId"]
        ):
            raise GateError("owner_input_mismatch")
        parsed = parse_event_json(
            row["wire_json"],
            TrustedPrincipal(
                ProviderScope(row["tenant_id"], row["provider"], row["provider_account_id"]),
                AccountScope(row["tenant_id"], row["account_id"]),
            ),
        )
        wire = json.loads(row["wire_json"])
        if (
            parsed.canonical != row["canonical_payload"]
            or wire["senderId"] != f["bindings"][label]["bindingId"]
            or wire["channel"] != item["channel"]
            or wire["caseId"] != f["caseId"]
            or wire["conversationId"] != f["conversationId"]
            or wire["accountScope"] != f["scope"]
            or intents[row["receipt_id"]]["operation_key"] != item["operationKey"]
            or intents[row["receipt_id"]]["state"] != "dispatched"
        ):
            raise GateError("owner_input_mismatch")
    smsrow = rows.get(sms["receiptId"])
    if (
        smsrow is None
        or smsrow["event_id"] != f["ids"]["sms"]
        or smsrow["provider"] != "fake_sms"
        or smsrow["provider_account_id"] != f["sms"]["providerScope"]["providerAccountId"]
        or str(smsrow["acceptance_sequence"]) != "3"
        or intents[smsrow["receipt_id"]]["operation_key"] != sms["operationKey"]
        or intents[smsrow["receipt_id"]]["state"] != "dispatched"
    ):
        raise GateError("owner_sms_mismatch")
    sms_wire = json.loads(smsrow["wire_json"])
    command = json.loads(sms_wire["body"])
    if (
        sms_wire["senderId"] != f["sms"]["senderId"]
        or command["kind"] != "case.revise_investigation"
        or command["expectedRevision"] != "1"
        or command["request"]["newCheckIn"] != "2030-01-13"
    ):
        raise GateError("owner_sms_mismatch")
    for operation in operations:
        receipt = operation["receipt"]
        submission = operation["submission"]
        row = rows.get(submission["message"]["receiptId"])
        plan = plans.get(submission["message"]["receiptId"])
        if (
            row is None
            or plan is None
            or operation["canonicalPayload"] != plan["payload_json"]
            or hashlib.sha256(plan["payload_json"].encode()).hexdigest() != plan["payload_digest"]
            or operation["payloadDigest"] != plan["payload_digest"]
            or json.loads(plan["payload_json"]) != submission
            or receipt["operationKey"] != intents[row["receipt_id"]]["operation_key"]
            or receipt["scope"] != f["scope"]
            or receipt["payloadDigest"] != plan["payload_digest"]
            or receipt["receiptId"] != intents[row["receipt_id"]]["external_receipt_id"]
            or submission["caseId"] != f["caseId"]
            or submission["conversationId"] != f["conversationId"]
        ):
            raise GateError("owner_operation_mismatch")
    expected_responses = {
        r["responseId"]: (r, label)
        for label, items in (
            ("A", browser["sessions"]["A"]["responses"]),
            ("B", [browser["sessions"]["B"]["response"]]),
        )
        for r in items
    }
    for response in snapshot["native_responses"]:
        observed, label = expected_responses[response["response_id"]]
        anchor = json.loads(response["canonical_anchor"])
        binding = bindings[anchor["bindingId"]]
        original = rows[anchor["receiptId"]]
        if (
            hashlib.sha256(response["canonical_anchor"].encode()).hexdigest()
            != response["anchor_digest"]
            or anchor["responseId"] != response["response_id"]
            or anchor["generationId"] != response["generation_id"]
            or anchor["bindingId"] != response["binding_id"]
            or anchor["sdkSpeechId"] != response["sdk_speech_id"]
            or anchor["receiptId"] != response["input_receipt_id"]
            or anchor["operationKey"] != response["operation_key"]
            or response["tenant_id"] != f["scope"]["tenantId"]
            or response["account_id"] != f["scope"]["accountId"]
            or response["case_id"] != f["caseId"]
            or response["conversation_id"] != f["conversationId"]
            or anchor["bindingId"] != f["bindings"][label]["bindingId"]
            or anchor["generationId"] != observed["generationId"]
            or anchor["sdkSpeechId"] != observed["sdkSpeechId"]
            or anchor["inputId"] != observed["inputId"]
            or anchor["operationKey"] != observed["operationKey"]
            or anchor["caseRevision"] != ("1" if label == "A" else "2")
            or anchor["roomId"] != binding["room_id"]
            or anchor["participantId"] != binding["participant_id"]
            or anchor["caseId"] != f["caseId"]
            or anchor["scope"] != f["scope"]
            or original["event_id"] != anchor["inputId"]
        ):
            raise GateError("owner_response_mismatch")
        facts = [
            r
            for r in snapshot["native_observations"]
            if r["response_id"] == response["response_id"]
        ]
        if (
            len(facts) != 2
            or sorted(int(r["observation_sequence"]) for r in facts) != [1, 2]
            or any(r["source"] != "agent_sdk" for r in facts)
        ):
            raise GateError("owner_fact_mismatch")
        payloads = []
        for fact in facts:
            value = json.loads(fact["canonical_payload"])
            payloads.append(value)
            if (
                hashlib.sha256(fact["canonical_payload"].encode()).hexdigest()
                != fact["payload_digest"]
                or fact["binding_id"] != anchor["bindingId"]
                or value["responseId"] != anchor["responseId"]
                or value["eventId"] != fact["event_id"]
                or value["generationId"] != anchor["generationId"]
                or value["sdkSpeechId"] != anchor["sdkSpeechId"]
            ):
                raise GateError("owner_fact_mismatch")
        if (
            sorted(p["fact"]["type"] for p in payloads) != ["generated_complete", "speech_settled"]
            or next(p["fact"] for p in payloads if p["fact"]["type"] == "speech_settled")["state"]
            != "completed"
        ):
            raise GateError("owner_fact_mismatch")
    original_receipts = {inputs[0]["receiptId"], inputs[1]["receiptId"], sms["receiptId"]}
    if set(browser["sessions"]["B"]["historyReceipts"]) != original_receipts:
        raise GateError("owner_context_history_mismatch")
    validate_history_channels(browser, rows)
    for label in ("A", "B"):
        for item in python["sessions"][label]["modelContexts"]:
            if item["sourceRevision"] != _reference_digest(f, item["revision"]) or (
                label == "B"
                and (
                    set(item["historyReceiptIds"]) != original_receipts
                    or item["contextId"] != browser["sessions"]["B"]["contextId"]
                )
            ):
                raise GateError("owner_model_context_mismatch")


def validate_history_channels(browser: dict[str, Any], rows: dict[str, Any]) -> None:
    for receipt_id, channel in zip(
        browser["sessions"]["B"]["historyReceipts"],
        browser["sessions"]["B"]["historyChannels"],
        strict=True,
    ):
        if json.loads(rows[receipt_id]["wire_json"])["channel"] != channel:
            raise GateError("owner_context_history_mismatch")


def _validated_report(raw: bytes) -> dict[str, Any]:
    value = native.decode(raw, maximum=32768)
    fixed = {
        "schema_version": 1,
        "status": "passed",
        "mode": MODE,
        "tests": 3,
        "passed": 3,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "cleanup_complete": True,
        "case_results": [{"name": name, "status": "passed", "code": "ok"} for name in CASE_NAMES],
        "schema_version_observed": 7,
        "native_inputs": 3,
        "fake_sms_inputs": 1,
        "operation_acceptances": 4,
        "responses": 3,
        "sdk_observations": 6,
        "browser_observations": 0,
        "playwright_tests": 1,
        "provider_calls": False,
        "physical_hearing_claimed": False,
        "human_acknowledgement_claimed": False,
        "read_only_load_generated_replies": 0,
        "dormant_rooms_observed": 0,
        "node_version": "24.22.2",
    }
    variables = {"duration_seconds", "child_commands", "proofs", "retained_index_sha256"}
    if (
        set(value) != set(fixed) | variables
        or any(not native.exact(value[k], v) for k, v in fixed.items())
        or type(value["duration_seconds"]) not in (int, float)
        or not math.isfinite(value["duration_seconds"])
        or not 0 <= value["duration_seconds"] <= 240
        or type(value["child_commands"]) is not int
        or value["child_commands"] != 10
        or type(value["retained_index_sha256"]) is not str
        or re.fullmatch(r"[a-f0-9]{64}", value["retained_index_sha256"]) is None
        or type(value["proofs"]) is not dict
        or set(value["proofs"])
        != {"browser", "python", "node", "sdk_source", "owner", "dormancy", "fixture"}
    ):
        raise GateError("invalid_report")
    for item in value["proofs"].values():
        if (
            type(item) is not dict
            or set(item) != {"bytes", "sha256"}
            or type(item["bytes"]) is not int
            or not 1 <= item["bytes"] <= 2097152
            or type(item["sha256"]) is not str
            or re.fullmatch(r"[a-f0-9]{64}", item["sha256"]) is None
        ):
            raise GateError("invalid_report")
    return value


def validated_browser(raw: bytes, fixture: dict[str, Any]) -> dict[str, Any]:
    try:
        return _validated_browser(raw, fixture)
    except GateError:
        raise
    except (
        KeyError,
        TypeError,
        ValueError,
        IndexError,
        AttributeError,
        OverflowError,
        RecursionError,
    ):
        raise GateError("invalid_browser_report") from None


def validated_sms(raw: bytes, fixture: dict[str, Any]) -> dict[str, Any]:
    try:
        return _validated_sms(raw, fixture)
    except GateError:
        raise
    except (
        KeyError,
        TypeError,
        ValueError,
        IndexError,
        AttributeError,
        OverflowError,
        RecursionError,
    ):
        raise GateError("invalid_sms_report") from None


def validated_node(raw: bytes) -> dict[str, Any]:
    try:
        return _validated_node(raw)
    except GateError:
        raise
    except (
        KeyError,
        TypeError,
        ValueError,
        IndexError,
        AttributeError,
        OverflowError,
        RecursionError,
    ):
        raise GateError("invalid_node_report") from None


def validated_browser_context(raw: bytes) -> dict[str, Any]:
    try:
        return _validated_browser_context(raw)
    except GateError:
        raise
    except (
        KeyError,
        TypeError,
        ValueError,
        IndexError,
        AttributeError,
        OverflowError,
        RecursionError,
    ):
        raise GateError("invalid_browser_context") from None


def validated_session(value: object, label: str, fixture: dict[str, Any]) -> dict[str, Any]:
    try:
        return _validated_session(value, label, fixture)
    except GateError:
        raise
    except (
        KeyError,
        TypeError,
        ValueError,
        IndexError,
        AttributeError,
        OverflowError,
        RecursionError,
    ):
        raise GateError("invalid_python_session") from None


def validated_python(raw: bytes, fixture: dict[str, Any]) -> dict[str, Any]:
    try:
        return _validated_python(raw, fixture)
    except GateError:
        raise
    except (
        KeyError,
        TypeError,
        ValueError,
        IndexError,
        AttributeError,
        OverflowError,
        RecursionError,
    ):
        raise GateError("invalid_python_report") from None


def validated_python_failure(raw: bytes) -> dict[str, Any]:
    try:
        return _validated_python_failure(raw)
    except GateError:
        raise
    except (
        KeyError,
        TypeError,
        ValueError,
        IndexError,
        AttributeError,
        OverflowError,
        RecursionError,
    ):
        raise GateError("invalid_python_failure") from None


def validated_report(raw: bytes) -> dict[str, Any]:
    try:
        return _validated_report(raw)
    except GateError:
        raise
    except (
        KeyError,
        TypeError,
        ValueError,
        IndexError,
        AttributeError,
        OverflowError,
        RecursionError,
    ):
        raise GateError("invalid_report") from None


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

    final = started + 240
    deadline = final - 20
    setup = core.load_setup(root)
    values = setup.load_settings()
    node = shutil.which("node")
    python = root / ".venv/bin/python"
    project = root / "projects/channel-continuity"
    console = root / "apps/local-console"
    compiler = project / "node_modules/typescript/bin/tsc"
    if node is None or not all(
        path.is_file()
        for path in (
            python,
            compiler,
            project / "examples/rehydration_lab.py",
            console / "node_modules/vite/bin/vite.js",
            console / "node_modules/@playwright/test/cli.js",
        )
    ):
        raise GateError("missing_setup")
    if browser_executable is not None and (
        not Path(browser_executable).is_absolute() or not Path(browser_executable).is_file()
    ):
        raise GateError("missing_browser")
    frozen = source_snapshot(root)
    native.write_json(artifacts / "source-before.json", frozen, maximum=262144)
    native.write_json(artifacts / "fixture-proof.json", previous.fixture_proof(root))
    run_id = uuid4().hex
    schema = "p2_rehydration_" + run_id
    case_schema = "p2_case_rehydration_" + run_id
    scratch = project / ".local/rehydration-media-check"
    core.private_directory(scratch)
    work = Path(tempfile.mkdtemp(prefix="run-", dir=scratch)).resolve()
    os.chmod(work, 0o700)
    native.write_json(work / "rehydration-owned-work.json", {"schemaVersion": 1, "schema": schema})
    try:
        children = Children(work, deadline)
        barriers = {
            name: FileBarrier(work, name)
            for name in ("python_http_ready", "node_ready", "python_a_closed", "sms_requested")
        }
        f = storage.fixture(run_id)
        # Existing native grants permit at most five minutes. This finite app grant spans
        # the independent 240s parent and does not renew on reconnect.
        from datetime import UTC, datetime

        f["expiresAt"] = (
            (datetime.now(UTC) + timedelta(seconds=280))
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        media: dict[str, Any] = {
            "schemaVersion": 1,
            "url": "ws://127.0.0.1:" + values["LIVEKIT_HTTP_PORT"],
            "browserAccessToken": secrets.token_urlsafe(32),
            "owner": run_id,
            "bindings": {},
        }
        for label in ("A", "B"):
            tokens = {}
            for key, kind in (("nativeToken", "agent"), ("browserToken", "standard")):
                tokens[key] = (
                    api.AccessToken(values["LIVEKIT_API_KEY"], values["LIVEKIT_API_SECRET"])
                    .with_identity(
                        f["bindings"][label]["agentId" if kind == "agent" else "participantId"]
                    )
                    .with_kind(cast(Literal["agent", "standard"], kind))
                    .with_ttl(timedelta(seconds=240))
                    .with_grants(
                        api.VideoGrants(
                            room_join=True,
                            room=f["bindings"][label]["roomId"],
                            can_publish=True,
                            can_subscribe=True,
                            can_publish_data=True,
                            can_update_own_metadata=kind == "agent",
                            can_manage_agent_session=False,
                        )
                    )
                    .to_jwt()
                )
            media["bindings"][label] = tokens
        exclusions = tuple(values[k] for k in setup.SECRET_KEYS) + tuple(
            str(value)
            for value in (
                f["accountToken"],
                f["publisherToken"],
                f["prepareToken"],
                *f["communication"].values(),
                f["bindings"]["A"]["bindingToken"],
                f["bindings"]["B"]["bindingToken"],
                media["browserAccessToken"],
                *media["bindings"]["A"].values(),
                *media["bindings"]["B"].values(),
                f["sms"]["hmacKeyBase64"],
            )
        )
        native.write_json(work / "fixture.json", f)
        native.write_json(work / "media.json", media)
        client = api.LiveKitAPI(
            url="http://127.0.0.1:" + values["LIVEKIT_HTTP_PORT"],
            api_key=values["LIVEKIT_API_KEY"],
            api_secret=values["LIVEKIT_API_SECRET"],
            timeout=aiohttp.ClientTimeout(total=3),
            failover=False,
        )
        common = {
            "P2_REHYDRATION_DIRECTORY": str(work),
            "P2_REHYDRATION_SCHEMA": schema,
            "P2_REHYDRATION_PG_PORT": values["POSTGRES_PORT"],
        }
        installed = False
        room_attempted: set[str] = set()
        script = work / "compiled/tests/pg_rehydration_cases.js"
        browser_output = work / "browser-report"
        browser: dict[str, Any] = {}
        python_report: dict[str, Any] = {}
        node_report: dict[str, Any] = {}
        sms: dict[str, Any] = {}
        snapshot: dict[str, Any] = {}

        async def stage(mode: str, end: float | None = None) -> dict[str, Any]:
            raw = await asyncio.to_thread(
                children.call,
                mode,
                [node, str(script), mode],
                storage.child_environment(values, common, mode),
                cwd=work,
                deadline=min(end or deadline, time.monotonic() + 20),
            )
            return storage.validated_stage(raw, mode)

        async def rooms() -> Any:
            return await client.room.list_rooms(
                api.ListRoomsRequest(names=[f["bindings"][key]["roomId"] for key in ("A", "B")])
            )

        async def create_room(label: str) -> None:
            name = f["bindings"][label]["roomId"]
            current = await rooms()
            if any(item.name == name for item in current.rooms):
                raise GateError("room_exists_before_owned_create")
            room_attempted.add(label)
            await client.room.create_room(
                api.CreateRoomRequest(
                    name=name,
                    empty_timeout=180,
                    departure_timeout=10,
                    max_participants=3,
                    metadata=json.dumps({"profile": "p2-rehydration-lab", "owner": run_id}),
                )
            )

        async def delete_room(label: str) -> None:
            name = f["bindings"][label]["roomId"]
            current = await rooms()
            for item in current.rooms:
                if item.name != name:
                    continue
                if json.loads(item.metadata) != {"profile": "p2-rehydration-lab", "owner": run_id}:
                    raise GateError("room_ownership_mismatch")
                await client.room.delete_room(api.DeleteRoomRequest(room=name))
            if any(item.name == name for item in (await rooms()).rooms):
                raise GateError("room_cleanup_incomplete")

        try:
            await asyncio.to_thread(
                children.call,
                "compile",
                [
                    node,
                    str(compiler),
                    "--project",
                    str(project / "tsconfig.pg.json"),
                    "--outDir",
                    str(work / "compiled"),
                ],
                core.base_environment(),
                cwd=project,
                deadline=min(deadline, time.monotonic() + 30),
            )
            native.write_json(
                artifacts / "runtime-build-parity.json",
                native.verify_runtime_build(project, work / "compiled"),
            )
            installed = True
            await stage("media-install")
            await stage("media-seed")
            if (await rooms()).rooms:
                raise GateError("room_exists_before_owned_create")
            await create_room("A")
            python_child = children.start(
                "python-app",
                [str(python), "-I", str(project / "examples/rehydration_lab.py"), str(work)],
                core.base_environment(),
                cwd=work,
            )
            await asyncio.to_thread(
                python_child.wait_for_barrier,
                barriers["python_http_ready"],
                timeout=min(15, native.remaining(deadline)),
            )
            python_port = native.endpoint(work / "python-endpoint.json")
            node_child = children.start(
                "node-app",
                [node, str(script), "media-serve"],
                storage.child_environment(values, common, "media-serve"),
                cwd=work,
            )
            await asyncio.to_thread(
                node_child.wait_for_barrier,
                barriers["node_ready"],
                timeout=min(15, native.remaining(deadline)),
            )
            native.endpoint(work / "node-endpoint.json")
            native.endpoint(work / "rehydration-endpoint.json")
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
            until = min(deadline, time.monotonic() + 10)
            while True:
                if vite_child.returncode is not None:
                    raise GateError("browser_server_failed")
                try:
                    connection = await asyncio.to_thread(
                        socket.create_connection, ("127.0.0.1", ui_port), 0.2
                    )
                    connection.close()
                    break
                except OSError:
                    if time.monotonic() >= until:
                        raise GateError("browser_server_unavailable") from None
                    await asyncio.sleep(0.01)
            browser_output.mkdir(mode=0o700)
            environment = {
                **core.base_environment(),
                "P2_NATIVE_BROWSER_ORIGIN": "http://127.0.0.1:" + str(ui_port),
                "P2_NATIVE_BROWSER_OUTPUT": str(browser_output),
                "P2_NATIVE_BROWSER_ACCESS": media["browserAccessToken"],
                **{
                    "P2_REHYDRATION_" + name + "_ID": f["ids"][key]
                    for name, key in (
                        ("VOICE", "voice"),
                        ("TEXT", "text"),
                        ("NEW_TEXT", "newText"),
                        ("SMS", "sms"),
                    )
                },
            }
            if browser_executable is not None:
                environment["PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"] = browser_executable
            browser_deadline = min(deadline, time.monotonic() + 150)
            browser_child = children.start(
                "browser",
                [
                    node,
                    str(console / "node_modules/@playwright/test/cli.js"),
                    "test",
                    "--config",
                    str(console / "playwright.rehydration.config.ts"),
                    "--global-timeout",
                    "150000",
                ],
                environment,
                cwd=console,
            )
            sms_done = False
            while browser_child.returncode is None:
                if not sms_done and (work / "sms_requested.reached").exists():
                    await asyncio.to_thread(
                        python_child.wait_for_barrier,
                        barriers["sms_requested"],
                        timeout=min(1, native.remaining(browser_deadline)),
                    )
                    await asyncio.to_thread(
                        python_child.wait_for_barrier,
                        barriers["python_a_closed"],
                        timeout=min(5, native.remaining(browser_deadline)),
                    )
                    validated_session(
                        native.decode(
                            previous.bounded_read(
                                work / "rehydration-python-session-A.json", maximum=32768
                            )
                        ),
                        "A",
                        f,
                    )
                    await delete_room("A")
                    if (await rooms()).rooms:
                        raise GateError("dormant_room_remained")
                    native.write_json(
                        artifacts / "dormancy-room-proof.json",
                        {
                            "schemaVersion": 1,
                            "owner": run_id,
                            "roomAClosedBeforeSms": True,
                            "roomsBeforeSms": 0,
                            "smsRequestedByOwnedPythonPid": python_child.pid,
                        },
                    )
                    raw = await asyncio.to_thread(
                        children.call,
                        "media-sms",
                        [node, str(script), "media-sms"],
                        storage.child_environment(values, common, "media-sms"),
                        cwd=work,
                        deadline=min(browser_deadline, time.monotonic() + 20),
                    )
                    terminal = native.decode(raw)
                    sms = validated_sms(
                        previous.bounded_read(work / "rehydration-sms-result.json", maximum=2048), f
                    )
                    if not native.exact(
                        terminal,
                        {"mode": "media-sms", "nodeVersion": "24.22.2", "storageVersion": 7, **sms},
                    ):
                        raise GateError("invalid_sms_report")
                    await create_room("B")
                    native.write_json(
                        work / "room_b_ready.json",
                        {
                            "schemaVersion": 1,
                            "roomId": f["bindings"]["B"]["roomId"],
                            "owner": run_id,
                        },
                    )
                    sms_done = True
                if time.monotonic() >= browser_deadline:
                    raise GateError("browser_deadline")
                if (
                    python_child.returncode is not None
                    or node_child.returncode is not None
                    or vite_child.returncode is not None
                ):
                    raise GateError("media_dependency_exited")
                await asyncio.sleep(0.01)
            await asyncio.to_thread(children.finish, browser_child, deadline=browser_deadline)
            if not sms_done:
                raise GateError("sms_not_observed")
            browser = validated_browser(
                previous.bounded_read(
                    browser_output / "rehydration-browser-observations.json", maximum=32768
                ),
                f,
            )
            playwright = native.decode(
                previous.bounded_read(browser_output / "playwright.json", maximum=1048576),
                maximum=1048576,
            )
            stats = playwright.get("stats", {})
            if not native.exact(stats.get("expected"), 1) or any(
                not native.exact(stats.get(key), 0) for key in ("unexpected", "flaky", "skipped")
            ):
                raise GateError("invalid_browser_report")
            native.write_json(artifacts / "playwright-stats.json", stats)
            python_report = validated_python(
                await asyncio.to_thread(
                    children.stop, python_child, deadline=min(deadline, time.monotonic() + 12)
                ),
                f,
            )
            node_report = validated_node(
                await asyncio.to_thread(
                    children.stop, node_child, deadline=min(deadline, time.monotonic() + 10)
                )
            )
            if not native.exact(
                native.decode(previous.bounded_read(work / "node-terminal.json", maximum=32768)),
                node_report,
            ) or not native.exact(
                native.decode(previous.bounded_read(work / "python-terminal.json", maximum=32768)),
                python_report,
            ):
                raise GateError("terminal_file_mismatch")
            await asyncio.to_thread(
                children.stop,
                vite_child,
                deadline=min(deadline, time.monotonic() + 3),
                require_zero=False,
            )
            await stage("media-verify")

            def owner_snapshot() -> dict[str, Any]:
                with closing(
                    psycopg.connect(
                        host="127.0.0.1",
                        port=int(values["POSTGRES_PORT"]),
                        dbname="livekit_lab",
                        user="continuity_migrator",
                        password=values["POSTGRES_MIGRATION_PASSWORD"],
                        sslmode="disable",
                        connect_timeout=2,
                        options="-c search_path=pg_catalog -c statement_timeout=3000",
                        autocommit=True,
                    )
                ) as connection:
                    owner = connection.execute(
                        "SELECT pg_get_userbyid(nspowner),obj_description(oid,'pg_namespace')FROM pg_namespace WHERE nspname=%s",
                        [schema],
                    ).fetchone()
                    if owner != ("continuity_migrator", "p2-channel-schema-v7"):
                        raise GateError("schema_ownership_mismatch")
                    ref = connection.execute(
                        sql.SQL(
                            "SELECT revision,request_json,cancelled,committed FROM {}.cases WHERE tenant_id=%s AND account_id=%s AND case_id=%s"
                        ).format(sql.Identifier(case_schema)),
                        [f["scope"]["tenantId"], f["scope"]["accountId"], f["caseId"]],
                    ).fetchone()
                    if (
                        ref is None
                        or ref[0] != 2
                        or json.loads(ref[1])["newCheckIn"] != "2030-01-13"
                        or ref[2] is not False
                        or ref[3] is not False
                    ):
                        raise GateError("current_case_owner_mismatch")
                    return {
                        name: [
                            row[0]
                            for row in connection.execute(
                                sql.SQL(
                                    "SELECT to_jsonb(t) FROM {}.{} t ORDER BY to_jsonb(t)::text LIMIT 65"
                                ).format(sql.Identifier(schema), sql.Identifier(name))
                            ).fetchall()
                        ]
                        for name in (
                            "inbox",
                            "processing_intents",
                            "dispatch_plans",
                            "native_bindings",
                            "native_responses",
                            "native_observations",
                        )
                    }

            snapshot = await asyncio.to_thread(owner_snapshot)
            operations_raw = previous.bounded_read(
                work / "rehydration-operations.json", maximum=262144
            )
            operations = native.decode(b'{"rows":' + operations_raw + b"}", maximum=262160)["rows"]

            validate_owner(snapshot, browser, python_report, f, sms, operations)
            sources: list[dict[str, Any]] = []
            for label in ("A", "B"):
                source_proof = native.decode(
                    previous.bounded_read(
                        work / ("communication-python-source-" + label + ".json"), maximum=1048576
                    ),
                    maximum=1048576,
                )
                sources.append(source_proof)
            combined: dict[str, Any] = {
                "schemaVersion": 1,
                "source": "native_sdk_public_nodes",
                "anchors": [item for source in sources for item in source["anchors"]],
                "sdkFacts": [item for source in sources for item in source["sdkFacts"]],
            }
            response_rows = {row["response_id"]: row for row in snapshot["native_responses"]}
            for item in combined["anchors"]:
                storage.validate_original_receipt(
                    item["receipt"], response_rows[item["payload"]["responseId"]], "response"
                )
            previous.validate_python_source_proof(
                json.dumps(
                    combined, ensure_ascii=False, separators=(",", ":"), allow_nan=False
                ).encode(),
                snapshot,
            )
            native.write_json(
                artifacts / "combined-python-source-proof.json", combined, maximum=1048576
            )
            native.write_json(artifacts / "owner-snapshot.json", snapshot, maximum=2097152)
            for name in (
                "rehydration-media-owner-proof.json",
                "rehydration-sms-result.json",
                "rehydration-node-private-proof.json",
                "rehydration-operations.json",
                "node-terminal.json",
                "python-terminal.json",
                "rehydration-python-terminal.json",
                "rehydration-python-session-A.json",
                "rehydration-python-session-B.json",
                "communication-python-source-A.json",
                "communication-python-source-B.json",
            ):
                native.safe_copy(work / name, artifacts / name, exclusions, maximum=1048576)
            for name in (
                "rehydration-browser-observations.json",
                "rehydration-browser-context.json",
                "rehydration-restored.png",
            ):
                native.safe_copy(
                    browser_output / name, artifacts / name, exclusions, maximum=2097152
                )
            native.safe_copy(
                script, artifacts / "pg_rehydration_cases.js", exclusions, maximum=262144
            )
        finally:
            primary = sys.exception()
            failed = False
            children.deadline = final
            for child in reversed(children.children):
                if child.returncode is None:
                    try:
                        await asyncio.to_thread(
                            children.stop,
                            child,
                            deadline=min(final, time.monotonic() + 4),
                            require_zero=child.output_directory.name != "vite",
                        )
                    except BaseException:  # noqa: BLE001 - Attempt independent owners and preserve primary failure.
                        failed = True
            if primary is not None:
                for name, reader in (
                    ("rehydration-python-failure.json", validated_python_failure),
                    ("browser-report/rehydration-browser-context.json", validated_browser_context),
                ):
                    try:
                        path = work / name
                        if path.exists():
                            safe = reader(previous.bounded_read(path, maximum=16384))
                            native.write_json(artifacts / Path(name).name, safe, maximum=16384)
                    except BaseException:  # noqa: BLE001 - Attempt independent owners and preserve primary failure.
                        failed = True
                try:
                    native.write_json(
                        artifacts / "failure-context.json",
                        {
                            "schemaVersion": 1,
                            "code": primary.code
                            if isinstance(primary, GateError)
                            else "gate_failed",
                            "children": [
                                {
                                    "name": child.output_directory.name,
                                    "pid": child.pid,
                                    "returncode": child.returncode,
                                }
                                for child in children.children
                            ],
                        },
                    )
                    for name in (
                        "media-install",
                        "media-seed",
                        "media-serve",
                        "media-sms",
                        "media-verify",
                    ):
                        path = work / ("rehydration-failure-" + name + ".json")
                        if path.exists():
                            native.safe_copy(path, artifacts / path.name, exclusions, maximum=4096)
                except BaseException:  # noqa: BLE001 - Attempt independent owners and preserve primary failure.
                    failed = True
            try:
                await cleanup_schema_if_settled(children, installed, stage, final)
            except BaseException:  # noqa: BLE001 - Never delete a schema while a child may still own I/O.
                failed = True
            for label in sorted(room_attempted):
                try:
                    async with asyncio.timeout(max(0.001, native.remaining(final))):
                        await delete_room(label)
                except BaseException:  # noqa: BLE001 - Attempt independent owners and preserve primary failure.
                    failed = True

            async def close_children() -> None:
                close_owned_children(children)

            try:
                await native.cleanup_actions((client.aclose, close_children), cleanup, primary)
            except BaseException:
                failed = True
                if primary is None:
                    raise
            cleanup["cleanup_complete"] = cleanup.get("cleanup_complete", False) and not failed
            if primary is None and not cleanup["cleanup_complete"]:
                raise GateError("cleanup_incomplete")
        if source_snapshot(root) != frozen:
            raise GateError("source_changed_during_measurement")
        if not cleanup["cleanup_complete"]:
            raise GateError("cleanup_incomplete")
        paths = {
            "browser": "rehydration-browser-observations.json",
            "python": "python-terminal.json",
            "node": "node-terminal.json",
            "sdk_source": "combined-python-source-proof.json",
            "owner": "owner-snapshot.json",
            "dormancy": "dormancy-room-proof.json",
            "fixture": "fixture-proof.json",
        }
        proofs = {}
        for key, name in paths.items():
            raw = previous.bounded_read(artifacts / name, maximum=2097152)
            proofs[key] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

        storage.retained_index(artifacts)
        index_sha = hashlib.sha256((artifacts / "retained-index.json").read_bytes()).hexdigest()
        storage.validate_retained_index(artifacts, index_sha)
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
                        {"name": name, "status": "passed", "code": "ok"} for name in CASE_NAMES
                    ],
                    "schema_version_observed": 7,
                    "native_inputs": 3,
                    "fake_sms_inputs": 1,
                    "operation_acceptances": 4,
                    "responses": 3,
                    "sdk_observations": 6,
                    "browser_observations": 0,
                    "playwright_tests": 1,
                    "provider_calls": False,
                    "physical_hearing_claimed": False,
                    "human_acknowledgement_claimed": False,
                    "read_only_load_generated_replies": 0,
                    "dormant_rooms_observed": 0,
                    "node_version": "24.22.2",
                    "duration_seconds": time.monotonic() - started,
                    "child_commands": children.count,
                    "proofs": proofs,
                    "retained_index_sha256": index_sha,
                },
                allow_nan=False,
            ).encode()
        )

    finally:
        finish_owned_work(
            root, artifacts, work, scratch, schema, case_schema, final, cleanup, sys.exception()
        )


def close_owned_children(children: Children) -> None:
    failed = False
    for child in reversed(children.children):
        try:
            child.close()
        except BaseException:  # noqa: BLE001 - Attempt every independent owned process.
            failed = True
    if failed or any(
        child.returncode is None or child.cleanup_failed for child in children.children
    ):
        raise GateError("cleanup_incomplete")


async def cleanup_schema_if_settled(
    children: Children,
    installed: bool,
    stage: Callable[[str, float | None], Awaitable[dict[str, Any]]],
    final: float,
) -> None:
    # Public process exit/reap and cleanup status must settle before dependent DDL.
    # A failed close cannot be converted into permission to delete live inputs/state.
    close_owned_children(children)
    if installed:
        await stage("media-cleanup", final)


def finish_owned_work(
    root: Path,
    artifacts: Path,
    work: Path,
    scratch: Path,
    schema: str,
    case_schema: str,
    final: float,
    cleanup: dict[str, bool],
    primary: BaseException | None,
) -> None:
    cleanup_error: BaseException | None = None
    if cleanup["cleanup_complete"]:
        try:
            native.remaining(final)
            storage.remove_owned_work(work, scratch, schema)
            native.remaining(final)
        except BaseException as error:  # noqa: BLE001 - preserve primary and actual cleanup status.
            cleanup["cleanup_complete"] = False
            cleanup_error = error
    if not cleanup["cleanup_complete"]:
        try:
            native.write_json(
                artifacts / "owned-work-retained.json",
                {
                    "schemaVersion": 1,
                    "directory": str(work.relative_to(root)),
                    "schema": schema,
                    "caseSchema": case_schema,
                    "cleanupComplete": False,
                },
            )
        except BaseException:  # noqa: BLE001 - diagnostics cannot replace the primary failure.
            cleanup["cleanup_complete"] = False
    if primary is None and cleanup_error is not None:
        raise GateError("cleanup_incomplete") from None


def retain_gate_failure(artifacts: Path, error: BaseException, cleanup: dict[str, bool]) -> None:
    """Fixed, body-free diagnostics also cover setup before the inner owner block."""
    frames: list[dict[str, Any]] = []
    trace = error.__traceback__
    while trace is not None and len(frames) < 6:
        name = Path(trace.tb_frame.f_code.co_filename).name
        if name in {
            "p2_rehydration_media_check.py",
            "p2_rehydration_check.py",
            "process_control.py",
        }:
            frames.append({"file": name, "line": trace.tb_lineno})
        trace = trace.tb_next
    kind = (
        "GateError"
        if isinstance(error, (GateError, core.GateError))
        else "TimeoutError"
        if isinstance(error, TimeoutError)
        else "ValueError"
        if isinstance(error, ValueError)
        else "OSError"
        if isinstance(error, OSError)
        else "DependencyError"
    )
    try:
        native.write_json(
            artifacts / "gate-failure-context.json",
            {
                "schemaVersion": 1,
                "status": "failed",
                "mode": MODE,
                "stage": "qualification"
                if (artifacts / "runtime-build-parity.json").exists()
                else "preflight",
                "errorType": kind,
                "code": error.code
                if isinstance(error, GateError) and error.code in {"unsafe_proof_file"}
                else "gate_failed",
                "frames": frames,
                "cleanupComplete": cleanup["cleanup_complete"],
            },
            maximum=4096,
        )
    except BaseException:  # noqa: BLE001 - Diagnostics must never replace primary or skip cleanup.
        cleanup["cleanup_complete"] = False


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--browser-executable")
    args = parser.parse_args(argv)
    started = time.monotonic()
    cleanup = {"cleanup_complete": False}
    target = None
    artifacts: Path | None = None
    try:
        target = target_path(
            root,
            args.report or Path(".local/validation/p2-rehydration-media/" + uuid4().hex + ".json"),
        )
        artifacts = target.with_name(target.stem + "-artifacts")
        artifacts.mkdir(mode=0o700)
        value = asyncio.run(run(root, artifacts, started, cleanup, args.browser_executable))
    except (native.GateError, core.GateError) as error:
        if artifacts is not None:
            retain_gate_failure(artifacts, error, cleanup)
        value = {
            "schema_version": 1,
            "status": "failed",
            "mode": MODE,
            "code": error.code,
            "duration_seconds": time.monotonic() - started,
            **cleanup,
        }
    except Exception as error:  # noqa: BLE001 - Never retain dependency exception text or credentials.
        if artifacts is not None:
            retain_gate_failure(artifacts, error, cleanup)
        value = {
            "schema_version": 1,
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
        value = {
            "schema_version": 1,
            "status": "failed",
            "mode": MODE,
            "code": "evidence_not_retained",
            **cleanup,
        }
    print(json.dumps(value, sort_keys=True))
    return 0 if value["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
