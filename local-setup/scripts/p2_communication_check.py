"""Actual v7 communication storage/migration/recovery; scripted trusted port facts only."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import signal
import stat
import sys
import tempfile
import time
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p2_communication_diagnostics as diagnostics
import p2_native_check as native
import p2_playback_check as media
import p3_coordinator_check as core

from harness.process_control import FileBarrier, OwnedProcess

ROOT = Path(__file__).resolve().parents[2]
GateError = native.GateError
MODE = "local_synthetic_p2_communication"
EXERCISE_OBSERVATIONS: int | None = 28
CASE_NAMES = (
    "v6_preservation_v7_repeat_older_upgrade",
    "interrupted_v7_ddl_rollback",
    "exact_response_input_operation_speech_binding",
    "concurrent_replay_and_changed_payload_conflict",
    "independent_source_capability_roles",
    "wrong_scope_response_generation_denied",
    "generated_and_sdk_partial_source_separation",
    "commutative_reordering_and_contradiction",
    "missing_client_completion_stays_unknown",
    "global_per_response_caps_original_replay",
    "expiry_revocation_original_evidence_only",
    "commit_before_ack_kill_fresh_replay",
    "counter_catalog_drift_no_growth",
    "retained_io_timeout_and_later_progress",
    "populated_v7_restore_original_receipts",
    "safe_telemetry_without_business_authority",
)
MODES = (
    "cleanup",
    "crash",
    "drift",
    "exercise",
    "expiry",
    "install",
    "legacy-seed",
    "replay",
    "upgrade",
    "upgrade-hold",
    "verify",
)
OWNER_MODES = ("cleanup", "install", "upgrade", "upgrade-hold", "verify")
RESPONSES = {
    "cleanup": {
        "cleanupComplete": True,
        "mode": "cleanup",
        "nodeVersion": "process.versions.node",
        "ownedSchemaAbsent": True,
        "schemaVersion": 1,
        "status": "passed",
        "storageVersion": 0,
    },
    "drift": {
        "completedGroups": ["counter_catalog_drift_no_growth"],
        "driftKind": "count|catalog exact private marker kind",
        "errorCode": "SchemaMismatch",
        "mode": "drift",
        "newRows": 0,
        "nodeVersion": "process.versions.node",
        "schemaVersion": 1,
        "status": "passed",
        "storageVersion": 7,
    },
    "exercise": {
        "maximumConnections": 2,
        "completedGroups": [
            "exact_response_input_operation_speech_binding",
            "concurrent_replay_and_changed_payload_conflict",
            "independent_source_capability_roles",
            "wrong_scope_response_generation_denied",
            "generated_and_sdk_partial_source_separation",
            "commutative_reordering_and_contradiction",
            "missing_client_completion_stays_unknown",
            "retained_io_timeout_and_later_progress",
            "safe_telemetry_without_business_authority",
        ],
        "maximumOperations": 4,
        "mode": "exercise",
        "nodeVersion": "process.versions.node",
        "observations": "exact implementation-bound count below32 (to be "
        "frozen before firstmeasurement)",
        "responses": 9,
        "schemaVersion": 1,
        "status": "passed",
        "storageVersion": 7,
    },
    "expiry": {
        "completedGroups": ["expiry_revocation_original_evidence_only"],
        "expiredNewResponseDenied": True,
        "freshBindingProgress": True,
        "mode": "expiry",
        "nodeVersion": "process.versions.node",
        "originalLateEvidenceAccepted": True,
        "schemaVersion": 1,
        "status": "passed",
        "storageVersion": 7,
    },
    "install": {
        "mode": "install",
        "nodeVersion": "process.versions.node",
        "schemaVersion": 1,
        "status": "passed",
        "storageVersion": 6,
    },
    "legacy-seed": {
        "legacyCallbacks": 1,
        "legacyNativeInputs": 1,
        "legacyOperationAcceptances": 1,
        "legacyRecoveryCommands": 1,
        "legacyReplyIntents": 1,
        "legacySendAttempts": 1,
        "legacySendResults": 1,
        "legacySmsInputs": 1,
        "mode": "legacy-seed",
        "nodeVersion": "process.versions.node",
        "schemaVersion": 1,
        "status": "passed",
        "storageVersion": 6,
    },
    "replay": {
        "completedGroups": [
            "global_per_response_caps_original_replay",
            "commit_before_ack_kill_fresh_replay",
        ],
        "mode": "replay",
        "newGenerationCalls": 0,
        "newOperationCalls": 0,
        "nodeVersion": "process.versions.node",
        "observations": 32,
        "originalObservationReceiptPreserved": True,
        "originalResponseReceiptPreserved": True,
        "responses": 10,
        "schemaVersion": 1,
        "status": "passed",
        "storageVersion": 7,
    },
    "upgrade": {
        "legacyPreserved": True,
        "mode": "upgrade",
        "nodeVersion": "process.versions.node",
        "olderUpgradesCompatible": True,
        "repeatedUpgrade": True,
        "rollbackTablesAbsent": True,
        "schemaVersion": 1,
        "status": "passed",
        "storageVersion": 7,
    },
    "verify": {
        "exactIdentityJoins": True,
        "legacyPreserved": True,
        "mode": "verify",
        "noAcknowledgements": True,
        "nodeVersion": "process.versions.node",
        "observations": 32,
        "originalReceiptsStable": True,
        "responses": 10,
        "schemaVersion": 1,
        "status": "passed",
        "storageVersion": 7,
    },
}
BARRIERS = (
    "communication_capacity_ready",
    "communication_capacity_waiting",
    "communication_expiry_ready",
    "communication_expiry_waiting",
    "communication_upgrade_ddl",
    "communication_observation_committed",
)
FIXTURE_PROOF_FILES = (
    "communication-legacy-original.json",
    "communication-exercise-proof.json",
    "communication-expiry-proof.json",
    "communication-capacity-proof.json",
    "communication-crash-original.json",
    "communication-replay-proof.json",
    "communication-owner-proof.json",
    "communication-operations.json",
    "communication-populated-backup.sql",
)
PROOF_FILES = (
    "owned-kills.json",
    "communication-capacity-lock.json",
    "communication-expiry-lock.json",
    "communication-before-restore.json",
    "communication-after-restore.json",
    "communication-reopen-restore.json",
    "communication-owner-proof.json",
    "communication-populated-backup.sql",
)


def validate_child_environment(environment: dict[str, str], mode: str) -> None:
    if mode not in MODES:
        raise GateError("invalid_child_mode")
    media.validate_child_environment(
        environment, "media-install" if mode in OWNER_MODES else "media-seed"
    )


def child_environment(values: dict[str, str], common: dict[str, str], mode: str) -> dict[str, str]:
    if mode not in MODES:
        raise GateError("invalid_child_mode")
    result = media.child_environment(
        values, common, "media-install" if mode in OWNER_MODES else "media-seed"
    )
    validate_child_environment(result, mode)
    return result


def validated_stage(raw: bytes, mode: str, *, fault: str | None = None) -> dict[str, Any]:
    if mode not in RESPONSES:
        raise GateError("invalid_child_mode")
    value = native.decode(raw)
    expected = dict(RESPONSES[mode])
    expected.pop("nodeVersion")
    if mode == "exercise":
        if type(EXERCISE_OBSERVATIONS) is not int or not 0 < EXERCISE_OBSERVATIONS < 32:
            raise GateError("unfrozen_fixture_protocol")
        expected["observations"] = EXERCISE_OBSERVATIONS
    if mode == "drift":
        if fault not in ("count", "catalog"):
            raise GateError("invalid_fault_schedule")
        expected["driftKind"] = fault
    if (
        set(value) != set(expected) | {"nodeVersion"}
        or not core.supported_node(value.get("nodeVersion"))
        or not all(native.exact(value[k], v) for k, v in expected.items())
    ):
        raise GateError("invalid_stage_report")
    return value


def validated_report(raw: bytes) -> dict[str, Any]:
    value = native.decode(raw)
    expected = {
        "schema_version": 1,
        "status": "passed",
        "mode": MODE,
        "tests": 16,
        "passed": 16,
        "errors": 0,
        "failures": 0,
        "skipped": 0,
        "cleanup_complete": True,
        "case_results": [{"name": n, "status": "passed", "code": "ok"} for n in CASE_NAMES],
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
    }
    if set(value) != set(expected) | {
        "duration_seconds",
        "child_commands",
        "node_version",
        "proofs",
    } or not all(native.exact(value[k], v) for k, v in expected.items()):
        raise GateError("invalid_report")
    duration = value["duration_seconds"]
    if (
        type(duration) not in (int, float)
        or not 0 < duration <= 180
        or not math.isfinite(duration)
        or type(value["child_commands"]) is not int
        or value["child_commands"] != 21
        or not core.supported_node(value["node_version"])
    ):
        raise GateError("invalid_report")
    proofs = value["proofs"]
    if type(proofs) is not dict or set(proofs) != set(PROOF_FILES):
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


def validated_capacity(raw: bytes) -> dict[str, Any]:
    value = native.decode(raw)
    expected = {
        "schemaVersion": 1,
        "admittedOperations": 4,
        "abandonedWaiters": 1,
        "settledOperations": 4,
        "fifthRejected": "Overloaded",
        "laterProgress": True,
    }
    if not native.exact(value, expected):
        raise GateError("invalid_capacity_proof")
    return value


def validated_expiry(raw: bytes) -> dict[str, Any]:
    value = native.decode(raw)
    expected = {
        "schemaVersion": 1,
        "expiredNewResponseDenied": True,
        "freshBindingProgress": True,
        "originalLateEvidenceAccepted": True,
        "originalReceiptPreserved": True,
    }
    if not native.exact(value, expected):
        raise GateError("invalid_expiry_proof")
    return value


def validate_inventory(snapshot: dict[str, Any]) -> None:
    """Independent identity joins. Pending evidence does not imply a prepared operation."""
    try:
        responses = snapshot["native_responses"]
        observations = snapshot["native_observations"]
        settings = snapshot["communication_settings"]
        if len(responses) != 10 or len(observations) != 32 or len(settings) != 1:
            raise GateError("inventory_count_mismatch")
        expected = {
            "response_count": 10,
            "observation_count": 32,
            "max_responses": 10,
            "max_observations": 32,
            "max_observations_per_response": 4,
        }
        if any(
            type(settings[0].get(k)) is not int or settings[0][k] != v for k, v in expected.items()
        ):
            raise GateError("inventory_capacity_mismatch")
        tables = {
            name: {r[key]: r for r in snapshot[name]}
            for name, key in [
                ("native_responses", "response_id"),
                ("inbox", "receipt_id"),
                ("processing_intents", "receipt_id"),
                ("dispatch_plans", "receipt_id"),
                ("native_bindings", "binding_id"),
            ]
        }
        if any(len(tables[name]) != len(snapshot[name]) for name in tables):
            raise GateError("inventory_duplicate_identity")
        ids = tables["native_responses"]
        inbox = tables["inbox"]
        intents = tables["processing_intents"]
        plans = tables["dispatch_plans"]
        bindings = tables["native_bindings"]
        if (
            len({r["receipt_id"] for r in responses}) != 10
            or len({r["receipt_id"] for r in observations}) != 32
            or len({(r["binding_id"], r["source"], r["event_id"]) for r in observations}) != 32
        ):
            raise GateError("inventory_identity_mismatch")
        grouped: dict[str, list[int]] = {key: [] for key in ids}
        scope_sequences: dict[tuple[str, str, str], list[int]] = {}
        for response in responses:
            anchor = native.decode(response["canonical_anchor"].encode(), maximum=8192)
            anchor_keys = {
                "schemaVersion",
                "responseId",
                "generationId",
                "sdkSpeechId",
                "bindingId",
                "inputId",
                "receiptId",
                "operationKey",
                "caseRevision",
                "scope",
                "providerScope",
                "caseId",
                "conversationId",
                "roomId",
                "participantId",
            }
            if (
                set(anchor) != anchor_keys
                or not native.exact(anchor["schemaVersion"], 1)
                or any(
                    not media.is_uuid(anchor[k])
                    for k in (
                        "responseId",
                        "generationId",
                        "bindingId",
                        "inputId",
                        "receiptId",
                        "operationKey",
                    )
                )
            ):
                raise GateError("inventory_anchor_invalid")
            if (
                type(anchor["caseRevision"]) is not str
                or not re.fullmatch(r"[1-9][0-9]{0,18}", anchor["caseRevision"])
                or int(anchor["caseRevision"]) > 9223372036854775807
            ):
                raise GateError("inventory_revision_invalid")
            if (
                hashlib.sha256(response["canonical_anchor"].encode()).hexdigest()
                != response["anchor_digest"]
            ):
                raise GateError("inventory_digest_mismatch")
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
            if any(anchor[k] != response[col] for k, col in fields.items()) or anchor["scope"] != {
                "tenantId": response["tenant_id"],
                "accountId": response["account_id"],
            }:
                raise GateError("inventory_scope_mismatch")
            binding = bindings.get(anchor["bindingId"])
            if binding is None:
                raise GateError("inventory_binding_missing")
            bound = native.decode(binding["canonical_binding"].encode(), maximum=4096)
            expected_bound = {
                "schemaVersion": 1,
                "bindingId": anchor["bindingId"],
                "providerScope": anchor["providerScope"],
                "scope": anchor["scope"],
                "caseId": anchor["caseId"],
                "conversationId": anchor["conversationId"],
                "roomId": anchor["roomId"],
                "participantId": anchor["participantId"],
                "expiresAt": bound.get("expiresAt"),
            }
            if (
                not native.exact(bound, expected_bound)
                or hashlib.sha256(binding["canonical_binding"].encode()).hexdigest()
                != binding["binding_digest"]
            ):
                raise GateError("inventory_binding_digest_mismatch")
            binding_fields = {
                "binding_id": anchor["bindingId"],
                "tenant_id": anchor["scope"]["tenantId"],
                "provider": "livekit",
                "provider_account_id": anchor["providerScope"]["providerAccountId"],
                "account_id": anchor["scope"]["accountId"],
                "conversation_id": anchor["conversationId"],
                "case_id": anchor["caseId"],
                "room_id": anchor["roomId"],
                "participant_id": anchor["participantId"],
            }
            if any(binding[k] != v for k, v in binding_fields.items()) or datetime.fromisoformat(
                bound["expiresAt"]
            ) != datetime.fromisoformat(binding["expires_at"]):
                raise GateError("inventory_binding_scope_mismatch")
            sequence = response["response_sequence"]
            if type(sequence) is not int or sequence < 1:
                raise GateError("inventory_sequence_mismatch")
            scope_sequences.setdefault(
                (response["tenant_id"], response["account_id"], response["conversation_id"]), []
            ).append(sequence)
            receipt = anchor["receiptId"]
            if (
                receipt not in inbox
                or receipt not in intents
                or intents[receipt]["operation_key"] != anchor["operationKey"]
            ):
                raise GateError("inventory_input_mismatch")
            original = inbox[receipt]
            wire = native.decode(original["wire_json"].encode())
            semantic = {
                k: v for k, v in wire.items() if k not in {"receivedAt", "retryCount", "signature"}
            }
            expected_wire = {
                "schemaVersion": 1,
                "type": "text.received",
                "providerScope": anchor["providerScope"],
                "accountScope": anchor["scope"],
                "conversationId": anchor["conversationId"],
                "caseId": anchor["caseId"],
                "eventId": anchor["inputId"],
                "messageId": anchor["inputId"],
                "senderId": anchor["bindingId"],
                "channel": "web_chat",
                "body": "INVESTIGATE",
            }
            if (
                not native.exact(semantic, expected_wire)
                or json.dumps(semantic, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
                != original["canonical_payload"]
                or json.dumps(wire, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
                != original["wire_json"]
            ):
                raise GateError("inventory_input_scope_mismatch")
            column_fields = {
                "tenant_id": anchor["scope"]["tenantId"],
                "provider": "livekit",
                "provider_account_id": anchor["providerScope"]["providerAccountId"],
                "account_id": anchor["scope"]["accountId"],
                "conversation_id": anchor["conversationId"],
                "event_id": anchor["inputId"],
                "message_id": anchor["inputId"],
            }
            if anchor["providerScope"] != {
                "tenantId": anchor["scope"]["tenantId"],
                "provider": "livekit",
                "providerAccountId": original["provider_account_id"],
            } or any(original[k] != v for k, v in column_fields.items()):
                raise GateError("inventory_input_column_mismatch")
            plan = plans.get(receipt)
            state = intents[receipt]["state"]
            if state == "dispatched" and plan is None:
                raise GateError("inventory_missing_preparation")
            if plan is not None:
                if (
                    state != "dispatched"
                    or plan["operation_key"] != anchor["operationKey"]
                    or hashlib.sha256(plan["payload_json"].encode()).hexdigest()
                    != plan["payload_digest"]
                ):
                    raise GateError("inventory_plan_mismatch")
                prepared = native.decode(plan["payload_json"].encode())
                expected_plan = {
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
                        "senderId": anchor["bindingId"],
                        "body": wire["body"],
                    },
                }
                if not native.exact(prepared, expected_plan):
                    raise GateError("inventory_plan_scope_mismatch")
            elif state != "pending":
                raise GateError("inventory_unexpected_processing_state")
        for sequences in scope_sequences.values():
            if sorted(sequences) != list(range(1, len(sequences) + 1)):
                raise GateError("inventory_scope_sequence_mismatch")
        for observation in observations:
            response = ids[observation["response_id"]]
            payload = native.decode(observation["canonical_payload"].encode())
            if (
                not native.exact(payload.get("schemaVersion"), 1)
                or not media.is_uuid(observation["receipt_id"])
                or not media.is_uuid(payload.get("eventId"))
                or hashlib.sha256(observation["canonical_payload"].encode()).hexdigest()
                != observation["payload_digest"]
                or payload["responseId"] != response["response_id"]
                or observation["binding_id"] != response["binding_id"]
                or payload["eventId"] != observation["event_id"]
            ):
                raise GateError("inventory_observation_mismatch")
            if observation["source"] == "agent_sdk":
                if (
                    set(payload)
                    != {
                        "schemaVersion",
                        "eventId",
                        "responseId",
                        "generationId",
                        "sdkSpeechId",
                        "fact",
                    }
                    or payload["generationId"] != response["generation_id"]
                    or payload["sdkSpeechId"] != response["sdk_speech_id"]
                ):
                    raise GateError("inventory_sdk_mismatch")
                fact = payload["fact"]
                if type(fact) is not dict:
                    raise GateError("inventory_sdk_fact_invalid")
                if fact.get("type") == "generated_complete":
                    if (
                        set(fact) != {"type", "text"}
                        or type(fact["text"]) is not str
                        or not fact["text"]
                        or len(fact["text"].encode()) > 4096
                    ):
                        raise GateError("inventory_sdk_fact_invalid")
                elif fact.get("type") == "speech_settled":
                    if (
                        set(fact) != {"type", "state", "sdkText"}
                        or fact["state"] not in {"completed", "interrupted", "unknown"}
                        or (
                            fact["sdkText"] is not None
                            and (
                                type(fact["sdkText"]) is not str
                                or not fact["sdkText"]
                                or len(fact["sdkText"].encode()) > 4096
                            )
                        )
                    ):
                        raise GateError("inventory_sdk_fact_invalid")
                else:
                    raise GateError("inventory_sdk_fact_invalid")
            elif observation["source"] == "browser_client":
                if (
                    set(payload)
                    != {"schemaVersion", "eventId", "responseId", "state", "observedAudioMs"}
                    or payload["state"] not in {"started", "partial", "interrupted", "completed"}
                    or type(payload["observedAudioMs"]) is not int
                    or not 0 <= payload["observedAudioMs"] <= 180000
                ):
                    raise GateError("inventory_browser_invalid")
            else:
                raise GateError("inventory_source_mismatch")
            sequence = observation["observation_sequence"]
            if type(sequence) is not int or not 1 <= sequence <= 4:
                raise GateError("inventory_sequence_mismatch")
            grouped[response["response_id"]].append(sequence)
        if max(len(v) for v in grouped.values()) != 4 or any(
            sorted(v) != list(range(1, len(v) + 1)) for v in grouped.values()
        ):
            raise GateError("inventory_per_response_mismatch")
    except (
        KeyError,
        ValueError,
        TypeError,
        AttributeError,
        OverflowError,
        RecursionError,
        GateError,
    ):
        raise GateError("invalid_inventory_proof") from None


def target_path(root: Path, path: Path) -> Path:
    if (
        path.is_absolute()
        or path.parts[:3] != (".local", "validation", "p2-communication")
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
    result = current / path.name
    if (
        result.exists()
        or result.is_symlink()
        or result.with_name(result.stem + "-artifacts").exists()
        or result.with_name(result.stem + "-artifacts").is_symlink()
    ):
        raise GateError("evidence_exists")
    return result


class Children(native.Children):
    def start(
        self, name: str, argv: list[str], environment: dict[str, str], *, cwd: Path
    ) -> OwnedProcess:
        if self.count >= 32 or re.fullmatch(r"[a-z0-9-]{1,48}", name) is None:
            raise GateError("child_budget")
        native.remaining(self.deadline)
        self.count += 1
        child = OwnedProcess(
            argv, cwd=cwd, env=environment, output_directory=self.work / name, max_output_bytes=4096
        )
        self.children.append(child)
        return child

    def finish(
        self,
        child: OwnedProcess,
        *,
        deadline: float | None = None,
        require_zero: bool = True,
        accepted_codes: tuple[int, ...] | None = None,
    ) -> bytes:
        raw = super().finish(
            child, deadline=deadline, require_zero=require_zero, accepted_codes=accepted_codes
        )
        if self.captured > 262144:
            raise GateError("capture_budget")
        return raw

    def kill(self, child: OwnedProcess) -> dict[str, Any]:
        result = child.kill(timeout=min(3, native.remaining(self.deadline)))
        out, err = core.CaptureBudget.read(child.output_directory, 4096)
        self.captured += len(out) + len(err)
        if (
            not result.killed
            or result.returncode != -signal.SIGKILL
            or child.cleanup_failed
            or out
            or err
            or self.captured > 262144
        ):
            raise GateError("owned_kill_not_observed")
        child.close()
        return {"pid": result.pid, "returncode": result.returncode, "actualSigkill": True}


def bounded_read(path: Path, maximum: int = 32768) -> bytes:
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_nlink != 1
        or not 0 < info.st_size <= maximum
    ):
        raise GateError("invalid_artifact")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as source:
        current = os.fstat(source.fileno())
        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
            raise GateError("invalid_artifact")
        raw = source.read(maximum + 1)
    if not 0 < len(raw) <= maximum:
        raise GateError("invalid_artifact")
    return raw


def read_json(path: Path, *, maximum: int = 32768) -> dict[str, Any]:
    return native.decode(bounded_read(path, maximum), maximum=maximum)


def validate_ready(value: dict[str, Any], kind: str) -> None:
    if kind == "capacity":
        if (
            set(value)
            != {
                "schemaVersion",
                "responseIds",
                "eventIds",
                "maximumOperations",
                "maximumConnections",
            }
            or not native.exact(value["schemaVersion"], 1)
            or not native.exact(value["maximumOperations"], 4)
            or not native.exact(value["maximumConnections"], 2)
        ):
            raise GateError("invalid_capacity_proof")
        for key in ("responseIds", "eventIds"):
            if (
                type(value[key]) is not list
                or len(value[key]) != 4
                or any(not media.is_uuid(v) for v in value[key])
                or len(set(value[key])) != 4
            ):
                raise GateError("invalid_capacity_proof")
    elif kind == "expiry":
        if (
            set(value)
            != {"schemaVersion", "bindingId", "responseId", "inputId", "operationKey", "expiresAt"}
            or not native.exact(value["schemaVersion"], 1)
            or any(
                not media.is_uuid(value[k])
                for k in ("bindingId", "responseId", "inputId", "operationKey")
            )
        ):
            raise GateError("invalid_expiry_proof")
        stamp = value["expiresAt"]
        if type(stamp) is not str or not re.fullmatch(
            r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", stamp
        ):
            raise GateError("invalid_expiry_proof")
        try:
            datetime.fromisoformat(stamp)
        except ValueError:
            raise GateError("invalid_expiry_proof") from None
    else:
        raise GateError("invalid_schedule")


def validated_backend_identity(
    raw: bytes, *, phase: str, schema: str, process_id: int
) -> tuple[int, ...]:
    value = native.decode(raw, maximum=1024)
    if (
        type(phase) is not str
        or phase not in {"capacity", "expiry"}
        or type(schema) is not str
        or not re.fullmatch(r"p2_playback_[a-f0-9]{32}", schema)
        or type(process_id) is not int
        or not 1 <= process_id <= 2147483647
    ):
        raise GateError("invalid_backend_identity")
    if (
        set(value) != {"schemaVersion", "phase", "processId", "schema", "backendIds"}
        or not native.exact(value["schemaVersion"], 1)
        or value["phase"] != phase
        or type(value["processId"]) is not int
        or value["processId"] != process_id
        or value["schema"] != schema
    ):
        raise GateError("invalid_backend_identity")
    ids = value["backendIds"]
    if (
        type(ids) is not list
        or len(ids) != (2 if phase == "capacity" else 1)
        or any(type(pid) is not int or not 1 <= pid <= 2147483647 for pid in ids)
        or ids != sorted(set(ids))
    ):
        raise GateError("invalid_backend_identity")
    return tuple(ids)


def lock_schedule(
    children: Children,
    child: OwnedProcess,
    kind: str,
    barriers: dict[str, FileBarrier],
    work: Path,
    connection: Any,
    schema: str,
    artifacts: Path,
) -> None:
    from psycopg import sql

    stem = "communication_" + kind + "_ready"
    waiting = "communication_" + kind + "_waiting"
    child.wait_for_barrier(barriers[stem], timeout=min(10, native.remaining(children.deadline)))
    ready = read_json(work / ("communication-" + kind + "-ready.json"))
    validate_ready(ready, kind)
    with connection.transaction():
        connection.execute(
            sql.SQL("SELECT * FROM {}.admission WHERE singleton FOR UPDATE").format(
                sql.Identifier(schema)
            )
        )
        owner_pid = connection.info.backend_pid
        if kind == "expiry":
            retained = connection.execute(
                sql.SQL(
                    "SELECT b.expires_at,r.operation_key,i.event_id FROM {}.native_bindings b JOIN {}.native_responses r ON r.binding_id=b.binding_id JOIN {}.inbox i ON i.receipt_id=r.input_receipt_id WHERE b.binding_id=%s AND r.response_id=%s"
                ).format(*[sql.Identifier(schema)] * 3),
                [ready["bindingId"], ready["responseId"]],
            ).fetchone()
            if (
                retained is None
                or retained[0] != datetime.fromisoformat(ready["expiresAt"])
                or str(retained[1]) != ready["operationKey"]
                or retained[2] != ready["inputId"]
            ):
                raise GateError("expiry_original_join_mismatch")
        else:
            count = connection.execute(
                sql.SQL(
                    "SELECT count(*) FROM {}.native_responses WHERE response_id=ANY(%s::uuid[])"
                ).format(sql.Identifier(schema)),
                [ready["responseIds"]],
            ).fetchone()[0]
            if count != 4:
                raise GateError("capacity_original_join_mismatch")
        child.release_barrier(barriers[stem])
        child.wait_for_barrier(
            barriers[waiting], timeout=min(2, native.remaining(children.deadline))
        )
        until = min(children.deadline, time.monotonic() + (1.45 if kind == "expiry" else 0.75))
        first_observed = None
        backend_ids: tuple[int, ...] | None = None
        while True:
            if backend_ids is None:
                backend_path = work / ("communication-" + kind + "-backends.json")
                if backend_path.exists() or backend_path.is_symlink():
                    backend_ids = validated_backend_identity(
                        bounded_read(backend_path, 1024),
                        phase=kind,
                        schema=schema,
                        process_id=child.pid,
                    )
            selected = []
            if backend_ids is not None:
                if owner_pid in backend_ids:
                    raise GateError("owner_backend_reused")
                connection.execute("SELECT pg_stat_clear_snapshot()")
                rows = connection.execute(
                    "SELECT pid,pg_blocking_pids(pid) FROM pg_stat_activity WHERE usename='livekit_lab' AND pid=ANY(%s)",
                    [list(backend_ids)],
                ).fetchall()
                edges = {pid: set(blockers) for pid, blockers in rows}
                allowed = {owner_pid, *backend_ids}
                reachable = {owner_pid}
                for _ in range(2):
                    reachable.update(pid for pid, blockers in edges.items() if blockers & reachable)
                complete = (
                    set(edges) == set(backend_ids)
                    and set(backend_ids) <= reachable
                    and all(
                        pid not in blockers and blockers <= allowed
                        for pid, blockers in edges.items()
                    )
                )
                if complete and (
                    len(backend_ids) == 1
                    or any(blockers & set(backend_ids) for blockers in edges.values())
                ):
                    selected = [
                        {"pid": pid, "blockers": sorted(blockers)}
                        for pid, blockers in sorted(edges.items())
                    ]
            if selected:
                clock = connection.execute(
                    "SELECT date_trunc('milliseconds',clock_timestamp())"
                ).fetchone()[0]
                if first_observed is None:
                    first_observed = clock
                    if kind == "expiry" and not clock < datetime.fromisoformat(ready["expiresAt"]):
                        raise GateError("expiry_wait_not_before_deadline")
                if kind == "capacity" or clock >= datetime.fromisoformat(ready["expiresAt"]):
                    break
            if time.monotonic() >= until:
                raise GateError("actual_owned_sql_waiter_missing")
            time.sleep(0.002)
        native.write_json(
            artifacts / ("communication-" + kind + "-lock.json"),
            {
                "schemaVersion": 1,
                "schema": schema,
                "ownedChildPid": child.pid,
                "ownedBackendIds": list(backend_ids or ()),
                "ownerBackendPid": owner_pid,
                "waiters": selected,
                "firstWaitObservedDbClock": first_observed.isoformat(
                    timespec="milliseconds"
                ).replace("+00:00", "Z"),
                "releaseObservedDbClock": clock.isoformat(timespec="milliseconds").replace(
                    "+00:00", "Z"
                ),
                "expiresAt": ready.get("expiresAt"),
                "queryTextObserved": False,
                "lockAuthority": "parent_owned_isolated_schema_admission",
                "ready": ready,
            },
        )


def run(root: Path, artifacts: Path, started: float, cleanup: dict[str, bool]) -> dict[str, Any]:
    import psycopg
    from psycopg import sql
    from psycopg.types.json import Jsonb

    if type(EXERCISE_OBSERVATIONS) is not int or not 0 < EXERCISE_OBSERVATIONS < 32:
        raise GateError("unfrozen_fixture_protocol")
    final = started + 180
    deadline = final - 15
    setup = core.load_setup(root)
    values = setup.load_settings()
    project = root / "projects/channel-continuity"
    node = shutil.which("node")
    docker = shutil.which("docker")
    compiler = project / "node_modules/typescript/bin/tsc"
    if not node or not docker or not compiler.is_file():
        raise GateError("missing_setup")
    run_id = uuid4().hex
    schema = "p2_playback_" + run_id
    scratch = project / ".local/communication-check"
    core.private_directory(scratch)
    with tempfile.TemporaryDirectory(prefix="run-", dir=scratch) as temporary:
        work = Path(temporary).resolve()
        children = Children(work, deadline)
        barriers = {name: FileBarrier(work, name) for name in BARRIERS}
        common = {
            "P2_COMM_DIRECTORY": str(work),
            "P2_COMM_SCHEMA": schema,
            "P2_COMM_PG_PORT": values["POSTGRES_PORT"],
        }
        script = work / "compiled/tests/pg_communication_cases.js"
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
            "expiresAt": (datetime.now(UTC) + timedelta(seconds=220))
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "ids": {"text": str(uuid4()), "voice": str(uuid4())},
        }
        communication: dict[str, Any] = {
            "schemaVersion": 1,
            **{
                k: secrets.token_urlsafe(32) for k in ("publisherToken", "sdkToken", "browserToken")
            },
            "inputIds": [str(uuid4()) for _ in range(3)],
        }
        for name, config in (("fixture.json", fixture), ("communication.json", communication)):
            native.write_json(work / name, config)
        exclude = (
            tuple(v for d in (fixture, communication) for k, v in d.items() if k.endswith("Token"))
            + tuple(
                hashlib.sha256((prefix + token).encode()).hexdigest()
                for prefix, token in (
                    ("evidence-account:", fixture["accountToken"]),
                    ("evidence-browser:", communication["browserToken"]),
                    ("evidence-bearer:", fixture["bindingToken"]),
                    ("evidence-publisher:", fixture["publisherToken"]),
                    ("evidence-communication-publisher:", communication["publisherToken"]),
                    ("evidence-sdk:", communication["sdkToken"]),
                )
            )
            + tuple(values[k] for k in setup.SECRET_KEYS)
        )
        installed = False
        backup_possible = False
        container = ""
        backup_dir = "/tmp/p2-communication-" + run_id
        version = ""
        kills = []
        groups: set[str] = set()
        before_restore: dict[str, Any] = {}

        def connect() -> Any:
            return psycopg.connect(
                host="127.0.0.1",
                port=int(values["POSTGRES_PORT"]),
                dbname="livekit_lab",
                user="continuity_migrator",
                password=values["POSTGRES_MIGRATION_PASSWORD"],
                sslmode="disable",
                connect_timeout=2,
                options="-c search_path=pg_catalog -c statement_timeout=3000 -c lock_timeout=1500",
                autocommit=True,
            )

        def snapshot() -> dict[str, Any]:
            with closing(connect()) as c:
                names = [
                    r[0]
                    for r in c.execute(
                        "SELECT tablename FROM pg_tables WHERE schemaname=%s ORDER BY tablename",
                        [schema],
                    )
                ]
                if not 1 <= len(names) <= 64:
                    raise GateError("invalid_snapshot")
                result = {}
                for name in names:
                    rows = c.execute(
                        sql.SQL(
                            "SELECT to_jsonb(t) FROM {}.{} t ORDER BY to_jsonb(t)::text LIMIT 65"
                        ).format(sql.Identifier(schema), sql.Identifier(name))
                    ).fetchall()
                    if len(rows) > 64:
                        raise GateError("snapshot_limit")
                    result[name] = [r[0] for r in rows]
                    encoded = json.dumps(result, sort_keys=True).encode()
                    if len(encoded) > 2097152 or any(s.encode() in encoded for s in exclude):
                        raise GateError("invalid_snapshot")
                return result

        def stage(
            mode: str,
            label: str | None = None,
            *,
            fault: str | None = None,
            end: float | None = None,
        ) -> dict[str, Any]:
            raw = children.call(
                label or mode,
                [node, str(script), mode],
                child_environment(values, common, mode),
                cwd=work,
                deadline=end,
            )
            result = validated_stage(raw, mode, fault=fault)
            groups.update(result.get("completedGroups", []))
            return result

        try:
            children.call(
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
            )
            native.write_json(
                artifacts / "runtime-build-parity.json",
                native.verify_runtime_build(project, work / "compiled"),
            )
            installed = True
            version = stage("install")["nodeVersion"]
            stage("legacy-seed")
            old = snapshot()
            native.write_json(artifacts / "before-v6.json", old, maximum=2097152)
            interrupted = children.start(
                "upgrade-hold",
                [node, str(script), "upgrade-hold"],
                child_environment(values, common, "upgrade-hold"),
                cwd=work,
            )
            interrupted.wait_for_barrier(
                barriers["communication_upgrade_ddl"], timeout=min(10, native.remaining(deadline))
            )
            kills.append(children.kill(interrupted))
            rollback = snapshot()
            if old != rollback or any(
                k in rollback
                for k in ("communication_settings", "native_responses", "native_observations")
            ):
                raise GateError("upgrade_rollback_changed_rows")
            native.write_json(artifacts / "after-rollback-v6.json", rollback, maximum=2097152)
            stage("upgrade")
            upgraded = snapshot()
            if any(
                name != "schema_metadata" and rows != upgraded.get(name)
                for name, rows in old.items()
            ):
                raise GateError("upgrade_changed_legacy_rows")
            groups.update(CASE_NAMES[:2])
            with closing(connect()) as owner_connection:
                expiry = children.start(
                    "expiry",
                    [node, str(script), "expiry"],
                    child_environment(values, common, "expiry"),
                    cwd=work,
                )
                lock_schedule(
                    children, expiry, "expiry", barriers, work, owner_connection, schema, artifacts
                )
                value = validated_stage(children.finish(expiry), "expiry")
                groups.update(value["completedGroups"])
                exercise = children.start(
                    "exercise",
                    [node, str(script), "exercise"],
                    child_environment(values, common, "exercise"),
                    cwd=work,
                )
                lock_schedule(
                    children,
                    exercise,
                    "capacity",
                    barriers,
                    work,
                    owner_connection,
                    schema,
                    artifacts,
                )
                value = validated_stage(children.finish(exercise), "exercise")
                groups.update(value["completedGroups"])
            crash = children.start(
                "crash",
                [node, str(script), "crash"],
                child_environment(values, common, "crash"),
                cwd=work,
            )
            crash.wait_for_barrier(
                barriers["communication_observation_committed"],
                timeout=min(10, native.remaining(deadline)),
            )
            kills.append(children.kill(crash))
            stage("replay")
            for kind in ("count", "catalog"):
                fault_path = work / "communication-fault.json"
                native.write_json(fault_path, {"schemaVersion": 1, "kind": kind})
                before = snapshot()
                with closing(connect()) as c:
                    if kind == "count":
                        original = c.execute(
                            sql.SQL(
                                "SELECT response_count FROM {}.communication_settings WHERE singleton"
                            ).format(sql.Identifier(schema))
                        ).fetchone()[0]
                        c.execute(
                            sql.SQL(
                                "UPDATE {}.communication_settings SET response_count=response_count+1 WHERE singleton"
                            ).format(sql.Identifier(schema))
                        )
                    else:
                        original = c.execute(
                            sql.SQL(
                                "SELECT catalog_snapshot FROM {}.schema_metadata WHERE singleton"
                            ).format(sql.Identifier(schema))
                        ).fetchone()[0]
                        c.execute(
                            sql.SQL(
                                "UPDATE {}.schema_metadata SET catalog_snapshot='{{}}'::jsonb WHERE singleton"
                            ).format(sql.Identifier(schema))
                        )
                    try:
                        stage("drift", "drift-" + kind, fault=kind)
                    finally:
                        c.execute(
                            sql.SQL("UPDATE {}.{} SET {}=%s WHERE singleton").format(
                                sql.Identifier(schema),
                                sql.Identifier(
                                    "communication_settings"
                                    if kind == "count"
                                    else "schema_metadata"
                                ),
                                sql.Identifier(
                                    "response_count" if kind == "count" else "catalog_snapshot"
                                ),
                            ),
                            [original if kind == "count" else Jsonb(original)],
                        )
                        fault_path.unlink()
                if before != snapshot():
                    raise GateError("drift_grew_rows")
            stage("verify")
            before_restore = snapshot()
            validate_inventory(before_restore)
            validated_capacity(bounded_read(work / "communication-capacity-proof.json"))
            validated_expiry(bounded_read(work / "communication-expiry-proof.json"))
            native.write_json(
                artifacts / "communication-before-restore.json", before_restore, maximum=2097152
            )
            container = (
                children.call(
                    "backup-container",
                    [
                        docker,
                        "ps",
                        "--filter",
                        "label=com.docker.compose.service=postgres",
                        "--filter",
                        "label=com.docker.compose.project.working_dir=" + str(root / "local-setup"),
                        "--format",
                        "{{.ID}}",
                    ],
                    core.base_environment(),
                    cwd=work,
                )
                .decode()
                .strip()
            )
            if not re.fullmatch(r"[a-f0-9]{12,64}", container):
                raise GateError("wrong_backup_container")
            backup_possible = True
            children.call(
                "backup-directory",
                [docker, "exec", container, "mkdir", "-m", "700", backup_dir],
                core.base_environment(),
                cwd=work,
            )
            pg_env = {
                **core.base_environment(),
                "PGPASSWORD": values["POSTGRES_MIGRATION_PASSWORD"],
            }
            children.call(
                "backup-dump",
                [
                    docker,
                    "exec",
                    "-e",
                    "PGPASSWORD",
                    container,
                    "pg_dump",
                    "--host=127.0.0.1",
                    "--username=continuity_migrator",
                    "--dbname=livekit_lab",
                    "--schema=" + schema,
                    "--inserts",
                    "--no-owner",
                    "--file=" + backup_dir + "/schema.sql",
                ],
                pg_env,
                cwd=work,
            )
            children.call(
                "backup-copy",
                [
                    docker,
                    "cp",
                    container + ":" + backup_dir + "/schema.sql",
                    str(work / "communication-populated-backup.sql"),
                ],
                core.base_environment(),
                cwd=work,
            )
            with closing(connect()) as c:
                owner = c.execute(
                    "SELECT pg_get_userbyid(nspowner),obj_description(oid,'pg_namespace') FROM pg_namespace WHERE nspname=%s",
                    [schema],
                ).fetchone()
                if owner != ("continuity_migrator", "p2-channel-schema-v7"):
                    raise GateError("backup_owner_mismatch")
                c.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            children.call(
                "backup-restore",
                [
                    docker,
                    "exec",
                    "-e",
                    "PGPASSWORD",
                    container,
                    "psql",
                    "-X",
                    "--host=127.0.0.1",
                    "--username=continuity_migrator",
                    "--dbname=livekit_lab",
                    "--set=ON_ERROR_STOP=1",
                    "--single-transaction",
                    "--file=" + backup_dir + "/schema.sql",
                ],
                pg_env,
                cwd=work,
            )
            restored = snapshot()
            stage("replay", "reopen-replay")
            stage("verify", "reopen-verify")
            reopened = snapshot()
            if before_restore != restored or restored != reopened:
                raise GateError("restored_rows_changed")
            native.write_json(
                artifacts / "communication-after-restore.json", restored, maximum=2097152
            )
            native.write_json(
                artifacts / "communication-reopen-restore.json", reopened, maximum=2097152
            )
            groups.add(CASE_NAMES[14])
            if groups != set(CASE_NAMES):
                raise GateError("missing_named_assertions")
            native.write_json(artifacts / "owned-kills.json", {"schemaVersion": 1, "kills": kills})
            for name in FIXTURE_PROOF_FILES:
                native.safe_copy(work / name, artifacts / name, exclude)
            native.safe_copy(script, artifacts / "pg_communication_cases.js", exclude)
        finally:
            primary = sys.exception()
            failed = False
            children.deadline = final
            for child in reversed(children.children):
                if child.returncode is None:
                    try:
                        children.stop(child, deadline=min(final, time.monotonic() + 3))
                    except Exception:  # noqa: BLE001 - Complete independent cleanup and preserve fixed first failure.
                        failed = True
            if primary is not None:
                diagnostics.retain_safely(work, artifacts, children.children, primary, exclude)
            if installed:
                try:
                    stage("cleanup", end=final)
                except Exception:  # noqa: BLE001 - Complete independent cleanup and preserve fixed first failure.
                    failed = True
            if backup_possible:
                try:
                    children.call(
                        "backup-remove",
                        [docker, "exec", container, "rm", "-rf", "--", backup_dir],
                        core.base_environment(),
                        cwd=work,
                        deadline=final,
                    )
                except Exception:  # noqa: BLE001 - Complete independent cleanup and preserve fixed first failure.
                    failed = True
            try:
                children.close()
            except Exception:  # noqa: BLE001 - Complete independent cleanup and preserve fixed first failure.
                failed = True
            cleanup["cleanup_complete"] = not failed
            if failed and primary is None:
                raise GateError("cleanup_incomplete")
        if not cleanup["cleanup_complete"]:
            raise GateError("cleanup_incomplete")
        manifest = {name: media.identity(artifacts / name) for name in PROOF_FILES}
        return validated_report(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "passed",
                    "mode": MODE,
                    "tests": 16,
                    "passed": 16,
                    "errors": 0,
                    "failures": 0,
                    "skipped": 0,
                    "cleanup_complete": True,
                    "case_results": [
                        {"name": n, "status": "passed", "code": "ok"} for n in CASE_NAMES
                    ],
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
                    "duration_seconds": time.monotonic() - started,
                    "child_commands": children.count,
                    "node_version": version,
                    "proofs": manifest,
                }
            ).encode()
        )


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    started = time.monotonic()
    cleanup = {"cleanup_complete": False}
    target = None
    try:
        target = target_path(
            root, args.report or Path(".local/validation/p2-communication/" + uuid4().hex + ".json")
        )
        artifacts = target.with_name(target.stem + "-artifacts")
        artifacts.mkdir(mode=0o700)
        value = run(root, artifacts, started, cleanup)
    except (GateError, core.GateError) as error:
        value = {
            "status": "failed",
            "mode": MODE,
            "code": error.code,
            "duration_seconds": time.monotonic() - started,
            **cleanup,
        }
    except Exception:  # noqa: BLE001 - Complete independent cleanup and preserve fixed first failure.
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
