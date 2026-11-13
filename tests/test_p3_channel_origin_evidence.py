"""Literal stdlib-built owner rows and coordinated forgery controls; no SDK use."""

from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import importlib.util
import json
import socket
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "literal_origin_evidence_tested", ROOT / "local-setup/scripts/p3_channel_origin_evidence.py"
)
assert SPEC is not None and SPEC.loader is not None
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)
T = 1900000000000
SCOPE = {"tenant_id": "tenant_origin", "account_id": "account_origin"}
CAMEL = {"tenantId": "tenant_origin", "accountId": "account_origin"}
P2 = "p2_origin_" + "a" * 32
WORK = "p1_work_origin_" + "b" * 32
CASE = "p3_completion_" + "c" * 32
TABLES = (
    "admission associations callback_admission callback_observations callback_settings challenges communication_settings conversations dispatch_attempts dispatch_plans dispatch_settings inbox native_bindings native_observations native_responses native_settings outbound_routes outbox_admission outbox_settings processing_intents reply_intents result_receipts schema_metadata send_attempts send_operations send_policy_settings send_recovery_commands send_recovery_observations send_results sender_heads",
    "accepted_work admission attempt_results cancellation_commands execution_limits issued_attempts result_actions result_delivery_intents result_delivery_possible result_delivery_receipts result_feed_events result_feed_heads result_feed_source schema_metadata",
    "action_intents business_outcomes cancellation_commands cases completion_deliveries completion_events confirmations execution_attempts execution_controls execution_leases execution_limits execution_signal_consumptions execution_signals execution_waits executions intent_dispatch mutation_attempts mutation_effects quotes schema_metadata tasks",
)
BODIES = [
    "Review the original booking policy.",
    "Review policy after asynchronous SMS.",
    "Review the revised booking policy.",
]


def uid(number):
    return "00000000-0000-4000-8000-" + f"{number:012d}"


def stamp(ms):
    return (
        datetime.fromtimestamp(ms / 1000, UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def raw(value, *, ordered=False, ascii_only=False):
    return json.dumps(
        value,
        sort_keys=not ordered,
        ensure_ascii=ascii_only,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def bytea(value):
    return "\\x" + value.encode().hex()


def renew_request(request):
    inner = request["request"]
    inner["input_fingerprint"] = sha(
        raw({k: v for k, v in inner.items() if k not in {"attempt", "input_fingerprint"}})
    )
    logical = {k: v for k, v in request.items() if k != "input_fingerprint"}
    logical["request"] = {
        k: v for k, v in inner.items() if k not in {"attempt", "input_fingerprint"}
    }
    request["input_fingerprint"] = sha(raw(logical))
    return request


def rewrite_original_work(value, request):
    """Forge every retained original ledger/proof together; source inbox stays fixed."""
    renew_request(request)
    wire = raw(request)
    for stage in value["snapshots"].values():
        for row in stage[WORK]["accepted_work"]:
            if row["work_id"] == uid(41):
                row["body"], row["sha256"] = bytea(wire), sha(wire)
                row["deadline_at_ms"] = request["request"]["deadline_at_ms"]
    proof = value["files"]["origin-p3-consumer.json"]["proof"]["original"]
    proof.update(
        request_canonical=wire,
        request_sha256=sha(wire),
        input_fingerprint=request["input_fingerprint"],
        inner_input_fingerprint=request["request"]["input_fingerprint"],
        origin=request["origin"],
        deadline_at_ms=request["request"]["deadline_at_ms"],
    )


def fixture(winner="a"):
    descriptor = {
        "schema_version": 1,
        "scope": copy.deepcopy(CAMEL),
        "case_id": "case_origin",
        "conversation_id": "conversation_origin",
        "recipient_id": "origin_recipient",
        "p2_schema": P2,
        "work_schema": WORK,
        "case_schema": CASE,
        "case_endpoint": {"host": "127.0.0.1", "port": 14500},
        "native_binding_ids": {"a": uid(1), "b": uid(2)},
        "parent_expires_at_ms": T + 180000,
        "receiver_id": uid(3),
        "task_id": uid(4),
        "authority_case_id": uid(5),
        "inputs": {
            "original": {"receiptId": uid(11), "operationKey": uid(21)},
            "ack": {"receiptId": uid(12), "operationKey": uid(22)},
        },
    }
    catalogue = {}
    for label, days in (("a", 10), ("b", 14)):
        policy = {
            "schema_version": 1,
            "kind": "booking.notice_policy",
            "policy_version": "notice_v1",
            "rule_id": "notice_minimum_days",
            "minimum_notice_days": 7,
            "note": "Source prose is inert.",
        }
        facts = {
            "schema_version": 1,
            "kind": "booking.notice_facts",
            "observations": [{"fact_id": "notice_primary", "days_before_arrival": days}],
            "note": "Synthetic facts.",
        }
        catalogue[label] = [
            {
                "scope": copy.deepcopy(SCOPE),
                "reference": {
                    "source_id": name,
                    "version": "distinct_" + label,
                    "sha256": sha(raw(body)),
                    "media_type": "application/json",
                    "byte_length": len(raw(body).encode()),
                    "width": None,
                    "height": None,
                },
                "body_utf8": raw(body),
            }
            for name, body in (("policy_notice", policy), ("facts_notice", facts))
        ]
    p2 = {name: [] for name in TABLES[0].split()}
    work = {name: [] for name in TABLES[1].split()}
    cases = {name: [] for name in TABLES[2].split()}
    for tables, version in ((p2, 8), (work, 4), (cases, 4)):
        tables["schema_metadata"] = [{"version": version}]
    p2["outbox_settings"] = [{"receiver_id": descriptor["receiver_id"], "max_replies": 8}]
    for label in ("a", "b"):
        binding = {
            "schemaVersion": 1,
            "bindingId": descriptor["native_binding_ids"][label],
            "providerScope": {
                "tenantId": CAMEL["tenantId"],
                "provider": "livekit",
                "providerAccountId": "origin_fixture_rtc",
            },
            "scope": copy.deepcopy(CAMEL),
            "caseId": "case_origin",
            "conversationId": "conversation_origin",
            "roomId": "origin_room_" + label,
            "participantId": "origin_participant_" + label,
            "expiresAt": stamp(T + 180000),
        }
        p2["native_bindings"].append(
            {
                **SCOPE,
                "binding_id": binding["bindingId"],
                "case_id": "case_origin",
                "conversation_id": "conversation_origin",
                "provider": "livekit",
                "provider_account_id": "origin_fixture_rtc",
                "room_id": binding["roomId"],
                "participant_id": binding["participantId"],
                "canonical_binding": raw(binding, ordered=True),
                "binding_digest": sha(raw(binding, ordered=True)),
                "bearer_digest": "a" * 64,
                "published_at": stamp(T),
                "expires_at": stamp(T + 180000),
                "revoked_at": None,
            }
        )
    p2["associations"] = [
        {
            **SCOPE,
            "provider": "fake_sms",
            "provider_account_id": "origin_fixture_sms",
            "conversation_id": "conversation_origin",
            "case_id": "case_origin",
            "sender_id": "origin_sms_sender",
            "epoch": 1,
            "revoked_at": None,
            "activated_at": stamp(T + 500),
        }
    ]
    p2["challenges"] = [{**p2["associations"][0], "consumed_at": stamp(T + 500)}]
    p2["sender_heads"] = [
        {
            "tenant_id": CAMEL["tenantId"],
            "provider": "fake_sms",
            "provider_account_id": "origin_fixture_sms",
            "sender_id": "origin_sms_sender",
            "epoch": 1,
            "active_epoch": 1,
        }
    ]
    sources = {}
    requests = {}
    accepted = {}
    files = {}
    for index, label in enumerate(("original", "ack", "current")):
        native = label != "ack"
        scope_provider = {
            "tenantId": CAMEL["tenantId"],
            "provider": "livekit" if native else "fake_sms",
            "providerAccountId": "origin_fixture_rtc" if native else "origin_fixture_sms",
        }
        accepted_ms = T + [1000, 11000, 31000][index]
        event = {
            "schemaVersion": 1,
            "type": "text.received",
            "eventId": uid(31 + index) if native else "origin_sms_input",
            "providerScope": scope_provider,
            "accountScope": copy.deepcopy(CAMEL),
            "caseId": "case_origin",
            "conversationId": "conversation_origin",
            "receivedAt": stamp(accepted_ms),
            "channel": "web_chat" if native else "sms",
            "messageId": uid(31 + index) if native else "origin_sms_input",
            "senderId": descriptor["native_binding_ids"]["a" if label == "original" else "b"]
            if native
            else "origin_sms_sender",
            "body": BODIES[index],
        }
        if not native:
            event["occurredAt"] = stamp(accepted_ms)
        inbox = {
            **SCOPE,
            "receipt_id": uid(11 + index),
            "provider": scope_provider["provider"],
            "provider_account_id": scope_provider["providerAccountId"],
            "event_id": event["eventId"],
            "message_id": event["messageId"],
            "conversation_id": "conversation_origin",
            "association_epoch": 1,
            "acceptance_sequence": index + 1,
            "accepted_at": stamp(accepted_ms),
            "wire_json": raw(event, ascii_only=True),
            "canonical_payload": raw(
                {k: v for k, v in event.items() if k != "receivedAt"}, ascii_only=True
            ),
        }
        submission = {
            "schemaVersion": 1,
            "kind": "investigation",
            "operationKey": uid(21 + index),
            "scope": copy.deepcopy(CAMEL),
            "caseId": "case_origin",
            "caseRevision": "2" if label == "current" else "1",
            "conversationId": "conversation_origin",
            "message": {
                "receiptId": uid(11 + index),
                "eventId": event["eventId"],
                "messageId": event["messageId"],
                "senderId": event["senderId"],
                "body": event["body"],
            },
        }
        canonical = raw(submission, ordered=True)
        sources[label] = submission
        p2["inbox"].append(inbox)
        p2["processing_intents"].append(
            {
                "receipt_id": uid(11 + index),
                "operation_key": uid(21 + index),
                "state": "dispatched",
                "possible_external": True,
                "external_receipt_id": uid(41 + index),
            }
        )
        p2["dispatch_plans"].append(
            {
                "receipt_id": uid(11 + index),
                "operation_key": uid(21 + index),
                "association_epoch": 1,
                "payload_json": canonical,
                "payload_digest": sha(canonical),
            }
        )
        used = winner if label == "original" else "a" if label == "ack" else "b"
        inner = {
            "schema_version": 1,
            "kind": "delegation.request",
            "capability": "booking.evaluate_policy",
            "input_schema_version": 2,
            "scope": copy.deepcopy(SCOPE),
            "delegation_id": "p2_" + uid(21 + index).replace("-", ""),
            "case_id": "case_origin",
            "request_revision": int(submission["caseRevision"]),
            "context_snapshot": {
                "policy_version": "notice_v1",
                "policy_source_id": "policy_notice",
                "facts_source_id": "facts_notice",
            },
            "evidence": [r["reference"] for r in catalogue[used]],
            "deadline_at_ms": accepted_ms + [60000, 1500, 60000][index],
            "result_route": {"conversation_id": "conversation_origin"},
            "attempt": {"attempt_id": "origin_proposal", "number": 1},
        }
        request = {
            "schema_version": 1,
            "kind": "delegation.request",
            "capability": "booking.evaluate_policy",
            "input_schema_version": 3,
            "origin": {
                "kind": "p2.prepared_dispatch.v1",
                "profile_id": descriptor["receiver_id"],
                "operation_key": uid(21 + index),
                "input_receipt_id": uid(11 + index),
                "payload_sha256": sha(canonical),
                "payload_byte_length": len(canonical.encode()),
            },
            "request": inner,
        }
        renew_request(request)
        requests[label] = request
        row = {
            **SCOPE,
            "work_id": uid(41 + index),
            "idempotency_key": inner["delegation_id"],
            "operation": "booking.evaluate_policy",
            "body": bytea(raw(request)),
            "sha256": sha(raw(request)),
            "deadline_at_ms": inner["deadline_at_ms"],
            "accepted_at_ms": accepted_ms,
        }
        accepted[label] = row
        work["accepted_work"].append(row)
        files["origin-" + label + "-prepared.json"] = {
            "submission": submission,
            "canonicalPayload": canonical,
            "payloadDigest": sha(canonical),
        }
    receipts = {
        label: {
            "operationKey": sources[label]["operationKey"],
            "scope": copy.deepcopy(CAMEL),
            "payloadDigest": requests[label]["origin"]["payload_sha256"],
            "receiptId": accepted[label]["work_id"],
        }
        for label in sources
    }
    files["origin-race.json"] = {
        "schema_version": 1,
        "receipt": receipts["original"],
        "operation_accept_calls": 1,
        "input_receipt_id": uid(11),
    }
    files["origin-race-callers.json"] = {
        "schema_version": 1,
        "receipts": [receipts["original"], receipts["original"]],
    }
    files["origin-reconcile.json"] = {
        "schema_version": 1,
        "receipt": receipts["ack"],
        "accept_calls": 0,
        "input_receipt_id": uid(12),
    }
    files["origin-current-accepted.json"] = {
        "schema_version": 1,
        "receipt": receipts["current"],
        "input_receipt_id": uid(13),
    }
    files["origin-ack-caller.json"] = {
        "schema_version": 1,
        "external_code": "OutcomeUnknown",
        "dispatch_code": "DispatchUnavailable",
        "accept_calls": 1,
        "dispatch": {"state": "uncertain", "possibleExternal": True},
    }
    files["origin-negative-controls.json"] = {
        "schema_version": 1,
        "codes": {
            "changed_origin": "OutcomeUnknown",
            "changed_lookup": "Unavailable",
            "wrong_profile": "Unavailable",
            "wrong_bearer": "Unavailable",
        },
    }
    files["origin-held-lookups.json"] = {
        "schema_version": 1,
        "before": [{"active": 2, "closing": False}] * 2,
        "after": [{"active": 0, "closing": True}] * 2,
        "outcomes": ["Unavailable"] * 4,
        "overload": ["Overloaded"] * 2,
        "caller_sockets_settled": True,
        "p1_drain_claimed": False,
    }
    proof = {}
    for index, label in enumerate(("original", "ack", "current")):
        row = accepted[label]
        request = requests[label]
        proof[label] = {
            "work_id": row["work_id"],
            "request_canonical": raw(request),
            "request_sha256": row["sha256"],
            "input_fingerprint": request["input_fingerprint"],
            "inner_input_fingerprint": request["request"]["input_fingerprint"],
            "deadline_at_ms": row["deadline_at_ms"],
            "origin": request["origin"],
        }
        if label == "ack":
            proof[label].update(execution_requested=False, read_only=True)
            continue
        used = winner if label == "original" else "b"
        proof[label]["catalogue_label"] = used
        issued_at = T + (20000 if label == "original" else 40000)
        issued = {
            **SCOPE,
            "work_id": row["work_id"],
            "attempt_id": uid(51 + index),
            "command_id": "run_" + label,
            "owner_id": uid(61 + index),
            "number": 1,
            "epoch": 1,
            "issued_at_ms": issued_at,
            "lease_until_ms": issued_at + 10000,
        }
        refs = [r["reference"] for r in catalogue[used]]
        days = 10 if used == "a" else 14
        result_inner = {
            "schema_version": 1,
            "kind": "delegation.result",
            "capability": "booking.evaluate_policy",
            "result_schema_version": 2,
            **{
                key: request["request"][key]
                for key in (
                    "scope",
                    "delegation_id",
                    "case_id",
                    "request_revision",
                    "input_fingerprint",
                )
            },
            "attempt_id": "attempt_" + issued["attempt_id"].replace("-", ""),
            "eligible": True,
            "uncertainty": "none",
            "rule_refs": [
                {
                    **{k: refs[0][k] for k in ("source_id", "version", "sha256")},
                    "rule_id": "notice_minimum_days",
                    "minimum_notice_days": 7,
                }
            ],
            "fact_refs": [
                {
                    **{k: refs[1][k] for k in ("source_id", "version", "sha256")},
                    "fact_id": "notice_primary",
                    "days_before_arrival": days,
                }
            ],
            "producer": {
                "producer_id": "deterministic_notice_v1",
                "model_id": None,
                "model_version": None,
                "config_fingerprint": sha(b"origin_supplied_scripted_v1"),
            },
            "completed_at_ms": issued_at + 50,
        }
        result = {
            "schema_version": 1,
            "kind": "delegation.result",
            "capability": "booking.evaluate_policy",
            "result_schema_version": 3,
            "input_fingerprint": request["input_fingerprint"],
            "result": result_inner,
        }
        recorded = {
            **SCOPE,
            "work_id": row["work_id"],
            "attempt_id": issued["attempt_id"],
            "body": bytea(raw(result)),
            "sha256": sha(raw(result)),
            "recorded_at_ms": issued_at + 100,
            "disposition": "eligible_at_commit",
        }
        work["issued_attempts"].append(issued)
        work["attempt_results"].append(recorded)
        work["result_feed_events"].append(
            {
                **SCOPE,
                "work_id": row["work_id"],
                "attempt_id": issued["attempt_id"],
                "sequence": 1 if label == "original" else 2,
                "event_id": uid(81 + index),
            }
        )
        proof[label]["execution"] = {
            "work_id": row["work_id"],
            "result_canonical": raw(result),
            "result_sha256": recorded["sha256"],
            "recorded_at_ms": recorded["recorded_at_ms"],
            "disposition": "eligible_at_commit",
            "applicability": "candidate",
            "issued": {
                k: issued[k]
                for k in (
                    "attempt_id",
                    "command_id",
                    "number",
                    "owner_id",
                    "epoch",
                    "issued_at_ms",
                    "lease_until_ms",
                )
            },
        }
    proof["original"]["stale_delivery"] = {
        "error": "not_eligible",
        "intent": None,
        "historical_result_sha256": proof["original"]["execution"]["result_sha256"],
        "historical_applicability": "outdated",
    }
    result = proof["current"]["execution"]
    intent = {
        "work_id": uid(43),
        "attempt_id": uid(53),
        "delivery_id": uid(91),
        "receiver_id": descriptor["receiver_id"],
        "recipient_id": "origin_recipient",
        "scope": copy.deepcopy(SCOPE),
        "body": base64.b64encode(result["result_canonical"].encode()).decode(),
        "result_sha256": result["result_sha256"],
        "prepared_at_ms": T + 41000,
    }
    receipt = {
        "delivery_id": uid(91),
        "receipt_id": uid(92),
        "receiver_id": descriptor["receiver_id"],
        "recipient_id": "origin_recipient",
        "result_sha256": result["result_sha256"],
        "accepted_at_ms": T + 41001,
    }
    proof["current"]["delivery"] = {
        "state": "accepted",
        "receiver_invoked": True,
        "intent": intent,
        "receipt": receipt,
        "human_acknowledgement": False,
    }
    work["result_delivery_intents"] = [
        {
            **SCOPE,
            **{
                k: intent[k]
                for k in (
                    "work_id",
                    "attempt_id",
                    "delivery_id",
                    "receiver_id",
                    "recipient_id",
                    "result_sha256",
                    "prepared_at_ms",
                )
            },
        }
    ]
    work["result_delivery_possible"] = [{"delivery_id": uid(91), "marked_at_ms": T + 41000}]
    work["result_delivery_receipts"] = [{**receipt, "recorded_at_ms": T + 41002}]
    p2["result_receipts"] = [
        {
            **SCOPE,
            **{
                k: intent[k]
                for k in ("work_id", "attempt_id", "delivery_id", "recipient_id", "result_sha256")
            },
            "outbound_id": uid(91),
            "case_id": "case_origin",
            "conversation_id": "conversation_origin",
            "canonical_intent": raw(intent, ascii_only=True),
        }
    ]
    notice = "Your review result is ready. Rejoin this conversation to view it."
    reply = {
        "schemaVersion": 1,
        "outboundId": uid(91),
        "responseId": "p3_" + uid(43).replace("-", ""),
        "body": notice,
        "scope": copy.deepcopy(CAMEL),
        "caseId": "case_origin",
        "conversationId": "conversation_origin",
    }
    p2["reply_intents"] = [
        {
            **SCOPE,
            "outbound_id": uid(91),
            "response_id": reply["responseId"],
            "receipt_id": uid(92),
            "case_id": "case_origin",
            "conversation_id": "conversation_origin",
            "canonical_payload": raw(reply, ordered=True),
            "intent_digest": sha(raw(reply, ordered=True)),
            "body_digest": sha(notice),
            "accepted_at": stamp(T + 41001),
        }
    ]
    files["origin-current-delivered.json"] = {
        "schema_version": 1,
        "work_id": uid(43),
        "delivery_id": uid(91),
        "receipt": receipt,
    }
    view = {
        "schemaVersion": 1,
        "intent": intent,
        "receipt": receipt,
        "case": {
            "schemaVersion": 1,
            "source": "p1_public_v4",
            "revision": "2",
            "scope": copy.deepcopy(CAMEL),
            "caseId": "case_origin",
            "conversationId": "conversation_origin",
            "workflow": {"taskId": uid(4), "state": "ready", "version": "0"},
            "request": {
                "schemaVersion": 1,
                "kind": "booking_investigation",
                "bookingReference": "DEMO-BK-001",
                "newCheckIn": "2030-12-12",
                "investigationConsent": True,
            },
            "intent": {"state": "not_committed", "intentId": None},
            "supplierResult": None,
            "sourceRevision": "d" * 64,
        },
        "observed": {
            "p2ObservedAt": stamp(T + 42000),
            "caseObservedAt": stamp(T + 42001),
            "disclosureAdmittedAt": stamp(T + 42002),
            "atomic": False,
        },
    }
    files["origin-native-read.json"] = {
        "schema_version": 1,
        "view": view,
        "input": {
            "schemaVersion": 1,
            "bindingId": uid(2),
            "receiptId": uid(13),
            "operationKey": uid(23),
            "inputId": uid(33),
            "channel": "web_chat",
            "acceptanceSequence": "3",
        },
        "rtc_rooms": 0,
        "provider_calls": False,
    }
    proof["real_read_only_controls"] = {
        "changed_profile_accept": "identity_conflict",
        "changed_context_exact_submit": "identity_conflict",
        "key": accepted["original"]["idempotency_key"],
        "separate_work_client": True,
        "specialist_invoked": False,
    }
    proof["simulations"] = [
        {
            "kind": "simulated_public_task_port",
            "reconciliation": name,
            "error": "acknowledgement_unknown",
            "finds": 2,
            "submits": 1,
            "keys": [accepted["original"]["idempotency_key"]] * 3,
            "actual_database_fault": False,
            "closed": True,
        }
        for name in ("missing", "unavailable")
    ]
    proof["case_revision"] = 2
    files["origin-p3-consumer.json"] = {
        "schema_version": 1,
        "status": "passed",
        "code": "ok",
        "stage": "complete",
        "ownership": {
            "startup_tasks": 8,
            "startup_pending": 0,
            "retained_tiers": [0, 0, 0],
            "close_observers_pending": 0,
            "cleanup_complete": True,
        },
        "cleanup_complete": True,
        "specialist": "supplied_scripted_fixed_policy_v2",
        "actual_invoke_count": 2,
        "source_actual_assertions": 0,
        "provider_calls": False,
        "carrier_sends": 0,
        "supplier_mutations": 0,
        "proof": proof,
    }
    pids = {
        role: 101 + n
        for n, role in enumerate(
            ("origin-race-a", "origin-race-b", "origin-ack", "origin-recovered", "origin-current")
        )
    }
    for role, pid in pids.items():
        files[role + "-ready.json"] = {
            "schema_version": 1,
            "pid": pid,
            "host": "127.0.0.1",
            "port": 15000 + pid,
        }
        if role != "origin-ack":
            files[role + "-closed.json"] = {
                "schema_version": 1,
                "pid": pid,
                "cleanup_complete": True,
                "retained_owners": [0, 0, 0],
                **{
                    k: 0
                    for k in (
                        "http_handlers",
                        "http_calls",
                        "http_sockets",
                        "service_pending",
                        "coordinator_pending",
                        "work_pending",
                        "case_pending",
                        "startup_pending",
                    )
                },
            }
    observations = {}
    for role, ordinal in (("origin-race-a", 2), ("origin-race-b", 1)):
        miss = {
            "schema_version": 1,
            "pid": pids[role],
            "key": accepted["original"]["idempotency_key"],
            "ordinal": ordinal,
            "found": False,
        }
        observations[role + "_miss"] = miss
        files[role + "-read-miss.json"] = copy.deepcopy(miss)
        files[role + "-submit-entered.json"] = {
            "schema_version": 1,
            "pid": pids[role],
            "key": accepted["original"]["idempotency_key"],
        }
    for key, table, count, holder in (
        ("race_wait_graph", "admission", 2, 701),
        ("held_wait_graph", "accepted_work", 4, 702),
        ("held_wait_graph_at_close", "accepted_work", 4, 702),
    ):
        query = (
            'SELECT * FROM "' + WORK + '"."' + table + '" WHERE singleton FOR UPDATE'
            if table == "admission"
            else 'SELECT * FROM "' + WORK + '"."' + table + '" WHERE idempotency_key=$1'
        )
        holder_query = (
            query
            if table == "admission"
            else 'LOCK TABLE "' + WORK + '"."accepted_work" IN ACCESS EXCLUSIVE MODE'
        )
        observations[key] = {
            "holder_pid": holder,
            "expected_waiters": count,
            "schema": WORK,
            "table": table,
            "association": "unique_disposable_work_schema",
            "row_lock": table == "admission",
            "holder_query": holder_query,
            "holder_query_sha256": sha(holder_query),
            "holder_locks": [
                {
                    "relation_oid": 7050 if table == "admission" else 7060,
                    "schema": WORK,
                    "table": table,
                    "locktype": "relation",
                    "mode": "RowShareLock" if table == "admission" else "AccessExclusiveLock",
                    "granted": True,
                }
            ],
            "waiters": [
                {
                    "pid": 800 + n,
                    "blockers": [holder],
                    "wait_event_type": "Lock",
                    "query": query,
                    "query_sha256": sha(query),
                    "relation_locks": [
                        {
                            "relation_oid": 7050 if table == "admission" else 7060,
                            "schema": WORK,
                            "table": table,
                            "locktype": "relation",
                            "mode": "RowShareLock" if table == "admission" else "AccessShareLock",
                            "granted": table == "admission",
                        }
                    ],
                }
                for n in range(count)
            ],
        }
    observations["close_incomplete"] = {
        "schema_version": 1,
        "pid": pids["origin-recovered"],
        "cleanup_complete": False,
        "work_pending": 4,
        "coordinator_pending": 4,
    }
    observations["ack_committed"] = {
        "schema_version": 1,
        "pid": pids["origin-ack"],
        "work_id": uid(42),
        "key": accepted["ack"]["idempotency_key"],
        "payload_sha256": accepted["ack"]["sha256"],
        "deadline_at_ms": accepted["ack"]["deadline_at_ms"],
    }
    files["origin-ack-committed.json"] = copy.deepcopy(observations["ack_committed"])
    observations["scheduled_kill"] = {
        "schema_version": 1,
        "role": "origin-ack",
        "pid": pids["origin-ack"],
        "returncode": -9,
        "group_settled": True,
    }
    observations["clock_after_ack_deadline"] = {
        "schema_version": 1,
        "db_now_ms": T + 13000,
        "ack_deadline_at_ms": accepted["ack"]["deadline_at_ms"],
        "lookup": {
            "http_status": 200,
            "body": {
                "schemaVersion": 1,
                "status": "known",
                "observation": {"status": "accepted", "receipt": receipts["ack"]},
            },
        },
    }
    observations["raw_negative"] = {
        name: {"http_status": status, "body": {"schemaVersion": 1, "status": "error", "code": code}}
        for name, status, code in (
            ("foreign_scope", 403, "unauthorized"),
            ("foreign_case", 403, "unauthorized"),
            ("foreign_conversation", 403, "unauthorized"),
            ("width65", 400, "invalid_input"),
            ("revision_zero", 400, "invalid_input"),
            ("revision_width", 400, "invalid_input"),
        )
    }
    observations["stale_new"] = {
        "http_status": 503,
        "body": {"schemaVersion": 1, "status": "error", "code": "case_changed"},
    }
    observations["known_historical"] = {
        "http_status": 200,
        "body": {"schemaVersion": 1, "status": "known", "receipt": receipts["original"]},
    }
    observations["supplier"] = {
        "status": "passed",
        "bookings": [["p3_completion_scope", "DEMO-BK-001", "2030-12-01", 0]],
        "mutation_receipts": [],
        "applied_calls": 0,
    }
    observations["m1_before"] = {"scope_id": "local-lab", "task_id": uid(99), "sha256": "e" * 64}
    observations["m1_after"] = copy.deepcopy(observations["m1_before"])
    ack_event = json.loads(p2["inbox"][1]["wire_json"])
    sms = {
        k: ack_event[k]
        for k in ("schemaVersion", "eventId", "messageId", "senderId", "body", "occurredAt")
    }
    sms_raw = raw(sms, ordered=True)
    timestamp = str((T + 11000) // 1000)
    domain = "p2.fake_sms.v1\ntenant_origin\nfake_sms\norigin_fixture_sms\n" + timestamp + "\n"
    files["origin-sms-source.json"] = {
        "schema_version": 1,
        "raw_utf8": sms_raw,
        "headers": {
            "timestamp": timestamp,
            "signature": hmac.new(
                bytes([0x4F]) * 32, domain.encode() + sms_raw.encode(), hashlib.sha256
            ).hexdigest(),
        },
    }
    cases["tasks"] = [
        {
            "task_id": uid(4),
            "scope_id": "p3_completion_scope",
            "status": "queued",
            "payload": raw(
                {
                    "booking_reference": "DEMO-BK-001",
                    "new_check_in": "2030-12-10",
                    "confirmed": True,
                }
            ),
        }
    ]
    snapshots = {}
    for index, name in enumerate(
        (
            "after_race",
            "after_ack_commit",
            "after_ack_reconcile",
            "after_negative",
            "after_case_change_before_current",
            "final",
        )
    ):
        channel = copy.deepcopy(p2)
        ledger = copy.deepcopy(work)
        case = copy.deepcopy(cases)
        labels = (
            ["original"]
            if index == 0
            else ["original", "ack"]
            if index < 5
            else ["original", "ack", "current"]
        )
        ledger["accepted_work"] = [copy.deepcopy(accepted[k]) for k in labels]
        if index < 5:
            channel["inbox"] = channel["inbox"][:2]
            channel["processing_intents"] = channel["processing_intents"][:2]
            channel["dispatch_plans"] = channel["dispatch_plans"][: 1 if index == 0 else 2]
            channel["reply_intents"] = []
            channel["result_receipts"] = []
            for table in (
                "result_delivery_intents",
                "result_delivery_possible",
                "result_delivery_receipts",
            ):
                ledger[table] = []
        if index == 0:
            channel["processing_intents"][1].update(
                state="pending", possible_external=False, external_receipt_id=None
            )
        if index == 1:
            channel["processing_intents"][1].update(
                state="uncertain", possible_external=True, external_receipt_id=None
            )
        for table in ("issued_attempts", "attempt_results", "result_feed_events"):
            ledger[table] = ledger[table][: 2 if index == 5 else 1 if index == 4 else 0]
        case["cases"] = [
            {
                "task_id": uid(4),
                "case_id": uid(5),
                "actor_id": "p3_completion_user",
                "scope_id": "p3_completion_scope",
                "cancelled": False,
                "revision": 2 if index >= 4 else 1,
                "request_json": raw(
                    {
                        "booking_reference": "DEMO-BK-001",
                        "new_check_in": "2030-12-12" if index >= 4 else "2030-12-11",
                        "confirmed": True,
                    }
                ),
            }
        ]
        snapshots[name] = {P2: channel, WORK: ledger, CASE: case}
    return {
        "schema_version": 1,
        "descriptor": descriptor,
        "snapshots": snapshots,
        "observations": observations,
        "files": files,
        "catalogue": catalogue,
    }


class LiteralEvidenceTests(unittest.TestCase):
    def assert_bad(self, value):
        with self.assertRaisesRegex(m.OriginEvidenceError, "^invalid_proof$") as caught:
            m.validate_bundle(value)
        self.assertEqual(caught.exception.code, "invalid_proof")

    def test_literal_positive_both_first_winners_and_validation_is_nonmutating(self):
        for winner in ("a", "b"):
            value = fixture(winner)
            before = raw(value)
            result = m.validate_bundle(value)
            self.assertEqual(set(result), set(m.CASES))
            self.assertEqual(len(result), 14)
            self.assertTrue(all(x == {"status": "passed", "code": "ok"} for x in result.values()))
            self.assertEqual(raw(value), before)

    def test_postgres_microseconds_match_exact_integer_receipt_milliseconds(self):
        from datetime import timedelta

        for micros in (1, 499, 500, 746, 999):
            with self.subTest(microseconds=micros):
                value = fixture()
                channel = value["snapshots"]["final"][value["descriptor"]["p2_schema"]]
                reply = channel["reply_intents"][0]
                original = datetime.fromisoformat(reply["accepted_at"])
                reply["accepted_at"] = (original + timedelta(microseconds=micros)).isoformat()
                self.assertEqual(len(m.validate_bundle(value)), 14)
                reply["accepted_at"] = (
                    original + timedelta(microseconds=1000 + micros)
                ).isoformat()
                self.assert_bad(value)
        self.assertEqual(m.millis("2026-11-12T23:47:46.220746+00:00"), 1794527266220)
        self.assertEqual(m.millis("2026-11-13T05:17:46.220746+05:30"), 1794527266220)
        self.assertEqual(m.millis("1969-12-31T23:59:59.999999+00:00"), -1)

    def test_sorted_published_json_roundtrip_preserves_exact_p2_wire_for_both_winners(self):
        for winner in ("a", "b"):
            value = json.loads(raw(fixture(winner)))
            self.assertEqual(list(value["descriptor"]["scope"]), ["accountId", "tenantId"])
            before = raw(value)
            self.assertEqual(len(m.validate_bundle(value)), 14)
            self.assertEqual(raw(value), before)

    def test_import_and_validation_use_no_socket_database_sdk_or_process(self):
        with (
            patch.object(socket.socket, "connect", side_effect=AssertionError("network")),
            patch.object(socket.socket, "bind", side_effect=AssertionError("listener")),
        ):
            SPEC.loader.exec_module(m)
            self.assertEqual(len(m.validate_bundle(fixture())), 14)
        source = Path(SPEC.origin).read_text()
        self.assertNotIn("continuity_lab", source)
        self.assertNotIn("delegation_reliability", source)

    def test_bool_unsupported_versions_and_missing_complete_tables_reject(self):
        for change in ("bool", "version", "missing_table", "missing_stage", "missing_catalogue"):
            v = fixture()
            if change == "bool":
                v["schema_version"] = True
            elif change == "version":
                v["snapshots"]["final"][P2]["schema_metadata"][0]["version"] = 9
            elif change == "missing_table":
                del v["snapshots"]["final"][WORK]["result_actions"]
            elif change == "missing_stage":
                del v["snapshots"]["after_ack_commit"]
            else:
                del v["catalogue"]["a"]
            with self.subTest(change=change):
                self.assert_bad(v)

    def test_origin_fields_and_canonical_work_forgery_reject_even_with_both_recomputed_fingerprints(
        self,
    ):
        for field, value in (
            ("payload_sha256", "f" * 64),
            ("payload_byte_length", 1),
            ("profile_id", uid(90)),
            ("operation_key", uid(90)),
            ("input_receipt_id", uid(90)),
        ):
            v = fixture()
            row = v["snapshots"]["final"][WORK]["accepted_work"][0]
            request = json.loads(bytes.fromhex(row["body"][2:]))
            request["origin"][field] = value
            rewrite_original_work(v, request)
            with self.subTest(field=field):
                self.assert_bad(v)

    def test_coordinated_p2_plan_work_fingerprints_cannot_replace_original_inbox_body(self):
        v = fixture()
        channel = v["snapshots"]["final"][P2]
        plan = channel["dispatch_plans"][0]
        payload = json.loads(plan["payload_json"])
        payload["message"]["body"] = "Forged body"
        plan["payload_json"] = raw(payload, ordered=True)
        plan["payload_digest"] = sha(plan["payload_json"])
        row = v["snapshots"]["final"][WORK]["accepted_work"][0]
        request = json.loads(bytes.fromhex(row["body"][2:]))
        request["origin"]["payload_sha256"] = plan["payload_digest"]
        request["origin"]["payload_byte_length"] = len(plan["payload_json"].encode())
        for stage in v["snapshots"].values():
            stage[P2]["dispatch_plans"][0].update(copy.deepcopy(plan))
        v["files"]["origin-original-prepared.json"].update(
            submission=payload,
            canonicalPayload=plan["payload_json"],
            payloadDigest=plan["payload_digest"],
        )
        rewrite_original_work(v, request)
        self.assert_bad(v)
        v = fixture()
        v["snapshots"]["final"][P2]["inbox"][0]["canonical_payload"] = "different"
        self.assert_bad(v)

    def test_catalogue_and_native_sms_scope_cannot_be_swapped(self):
        for mutate in ("facts", "scope", "native", "signature", "challenge"):
            v = fixture()
            if mutate == "facts":
                v["catalogue"]["a"][1]["body_utf8"] = "{}"
            elif mutate == "scope":
                v["snapshots"]["final"][P2]["inbox"][0]["account_id"] = "other"
            elif mutate == "native":
                v["snapshots"]["final"][P2]["native_bindings"][0]["room_id"] = "other"
            elif mutate == "signature":
                v["files"]["origin-sms-source.json"]["headers"]["signature"] = "f" * 64
            else:
                v["snapshots"]["final"][P2]["challenges"][0]["consumed_at"] = None
            with self.subTest(mutate=mutate):
                self.assert_bad(v)

    def test_direct_and_transitive_waiter_graphs_reach_the_same_owned_holder(self):
        for mixed in (False, True):
            v = fixture()
            race = v["observations"]["race_wait_graph"]
            race["waiters"][1]["blockers"] = [race["waiters"][0]["pid"]]
            held = v["observations"]["held_wait_graph"]
            pids = [waiter["pid"] for waiter in held["waiters"]]
            held["waiters"][1]["blockers"] = [pids[0]]
            held["waiters"][2]["blockers"] = [pids[0], held["holder_pid"]] if mixed else [pids[1]]
            held["waiters"][3]["blockers"] = [pids[1], pids[2]] if mixed else [pids[2]]
            v["observations"]["held_wait_graph_at_close"] = copy.deepcopy(held)
            self.assertEqual(len(m.validate_bundle(v)), 14)
        self.assertEqual(len(m.validate_bundle(fixture())), 14)

    def test_transitive_waiter_graph_never_accepts_foreign_edges_cycles_or_missing_waiters(self):
        for change in (
            "foreign",
            "cycle",
            "self",
            "empty",
            "missing",
            "bool",
            "duplicate",
            "branch_cycle",
            "branch_foreign",
        ):
            v = fixture()
            graph = v["observations"]["race_wait_graph"]
            first, second = graph["waiters"]
            second["blockers"] = [first["pid"]]
            if change == "foreign":
                first["blockers"] = [999]
            elif change == "cycle":
                first["blockers"] = [second["pid"]]
            elif change == "self":
                first["blockers"] = [first["pid"]]
            elif change == "empty":
                first["blockers"] = []
            elif change == "missing":
                graph["waiters"].pop()
            elif change == "bool":
                first["blockers"] = [True]
            elif change == "duplicate":
                first["blockers"] = [graph["holder_pid"], graph["holder_pid"]]
            elif change == "branch_cycle":
                first["blockers"] = [graph["holder_pid"], second["pid"]]
            else:
                first["blockers"] = [graph["holder_pid"], 999]
            with self.subTest(change=change):
                self.assert_bad(v)

    def test_schema_validation_select_is_bound_by_actual_relation_locks_not_parameter_text(self):
        v = fixture()
        query = "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE connamespace=(SELECT oid FROM pg_namespace WHERE nspname=$1)"
        for name in ("held_wait_graph", "held_wait_graph_at_close"):
            graph = v["observations"][name]
            for waiter in graph["waiters"]:
                waiter["query"], waiter["query_sha256"] = query, sha(query)
        self.assertNotIn(WORK, query)
        self.assertEqual(len(m.validate_bundle(v)), 14)

    def test_coordinated_wrong_relation_oid_mode_or_grant_never_proves_actual_find(self):
        for change in (
            "schema",
            "table",
            "oid",
            "mode",
            "grant",
            "holder_mode",
            "holder_oid",
            "same_table_oid",
            "locktype",
            "nonselect",
        ):
            v = fixture()
            for name in ("held_wait_graph", "held_wait_graph_at_close"):
                graph = v["observations"][name]
                for waiter in graph["waiters"]:
                    lock = waiter["relation_locks"][0]
                    if change == "schema":
                        lock["schema"] = "p1_work_origin_" + "d" * 32
                    elif change == "table":
                        lock["table"] = "admission"
                    elif change == "oid":
                        lock["relation_oid"] = 9999
                    elif change == "mode":
                        lock["mode"] = "RowExclusiveLock"
                    elif change == "grant":
                        lock["granted"] = True
                    elif change == "same_table_oid":
                        lock["relation_oid"] = 7050
                    elif change == "locktype":
                        lock["locktype"] = "tuple"
                    elif change == "nonselect":
                        waiter["query"] = "UPDATE arbitrary SET value=1"
                        waiter["query_sha256"] = sha(waiter["query"])
                if change == "holder_mode":
                    graph["holder_locks"][0]["mode"] = "RowExclusiveLock"
                elif change == "holder_oid":
                    graph["holder_locks"][0]["relation_oid"] = 9999
                elif change == "same_table_oid":
                    graph["holder_locks"][0]["relation_oid"] = 7050
            with self.subTest(change=change):
                self.assert_bad(v)

    def test_relation_lock_rows_are_closed_strict_finite_and_not_optional(self):
        for change in (
            "extra",
            "missing",
            "bool_oid",
            "int_granted",
            "empty",
            "duplicate",
            "holder_ungranted",
        ):
            v = fixture()
            graph = v["observations"]["race_wait_graph"]
            lock = graph["waiters"][0]["relation_locks"][0]
            if change == "extra":
                lock["model_assertion"] = True
            elif change == "missing":
                del lock["relation_oid"]
            elif change == "bool_oid":
                lock["relation_oid"] = True
            elif change == "int_granted":
                lock["granted"] = 1
            elif change == "empty":
                graph["waiters"][0]["relation_locks"] = []
            elif change == "duplicate":
                graph["waiters"][0]["relation_locks"].append(copy.deepcopy(lock))
            else:
                graph["holder_locks"][0]["granted"] = False
            with self.subTest(change=change):
                self.assert_bad(v)

    def test_forged_waiter_graph_kill_or_socket_truth_reject(self):
        for mutate in ("waiter", "query", "holder", "kill", "drain"):
            v = fixture()
            if mutate == "waiter":
                v["observations"]["held_wait_graph"]["waiters"][1]["pid"] = 800
            elif mutate == "query":
                v["observations"]["race_wait_graph"]["waiters"][0]["query"] = "SELECT 1"
            elif mutate == "holder":
                v["observations"]["held_wait_graph_at_close"]["holder_pid"] = 999
            elif mutate == "kill":
                v["observations"]["scheduled_kill"]["pid"] = 999
            else:
                v["files"]["origin-held-lookups.json"]["p1_drain_claimed"] = True
            with self.subTest(mutate=mutate):
                self.assert_bad(v)

    def test_issued_result_delivery_and_current_native_view_swaps_reject(self):
        for mutate in ("issued", "result", "delivery", "view", "stale_intent"):
            v = fixture()
            work = v["snapshots"]["final"][WORK]
            if mutate == "issued":
                work["issued_attempts"][0]["work_id"] = uid(43)
            elif mutate == "result":
                work["attempt_results"][0]["attempt_id"] = uid(53)
            elif mutate == "delivery":
                work["result_delivery_intents"][0]["work_id"] = uid(41)
            elif mutate == "view":
                v["files"]["origin-native-read.json"]["view"]["case"]["workflow"]["taskId"] = uid(
                    98
                )
            else:
                v["snapshots"]["after_case_change_before_current"][WORK][
                    "result_delivery_intents"
                ] = [copy.deepcopy(work["result_delivery_intents"][0])]
            with self.subTest(mutate=mutate):
                self.assert_bad(v)

    def test_simulations_never_become_database_faults_and_mutation_m1_truth_stays_separate(self):
        for mutate in ("simulation", "extra_submit", "mutation", "m1"):
            v = fixture()
            if mutate == "simulation":
                v["files"]["origin-p3-consumer.json"]["proof"]["simulations"][0][
                    "actual_database_fault"
                ] = True
            elif mutate == "extra_submit":
                v["files"]["origin-p3-consumer.json"]["proof"]["simulations"][0]["submits"] = 2
            elif mutate == "mutation":
                v["observations"]["supplier"]["applied_calls"] = 1
            else:
                v["observations"]["m1_after"]["sha256"] = "f" * 64
            with self.subTest(mutate=mutate):
                self.assert_bad(v)

    def test_expired_ack_clock_observation_cannot_be_inferred_from_process_delay(self):
        for change in ("missing", "equal", "deadline", "receipt", "version"):
            v = fixture()
            clock = v["observations"]["clock_after_ack_deadline"]
            if change == "missing":
                del v["observations"]["clock_after_ack_deadline"]
            elif change == "equal":
                clock["db_now_ms"] = clock["ack_deadline_at_ms"]
            elif change == "deadline":
                clock["ack_deadline_at_ms"] -= 1
            elif change == "receipt":
                clock["lookup"]["body"]["observation"]["receipt"]["receiptId"] = uid(41)
            else:
                clock["schema_version"] = True
            with self.subTest(change=change):
                self.assert_bad(v)

    def test_coordinated_request_evidence_forgery_rejects_trusted_catalogue_anchor(self):
        v = fixture()
        row = v["snapshots"]["final"][WORK]["accepted_work"][0]
        request = json.loads(bytes.fromhex(row["body"][2:]))
        request["request"]["evidence"][1]["version"] = "forged_version"
        rewrite_original_work(v, request)
        self.assert_bad(v)
        self.assertEqual(len(m.validate_bundle(fixture("b"))), 14)

    def test_consumer_and_actual_native_ownership_final_states_must_be_truthful(self):
        for change in (
            "consumer_pending",
            "consumer_retained",
            "host_retained",
            "native_input",
            "case_revision",
            "ack_inbox",
        ):
            v = fixture()
            consumer = v["files"]["origin-p3-consumer.json"]
            if change == "consumer_pending":
                consumer["ownership"]["startup_pending"] = 1
            elif change == "consumer_retained":
                consumer["ownership"]["retained_tiers"] = [1, 0, 0]
            elif change == "host_retained":
                v["files"]["origin-recovered-closed.json"]["work_pending"] = 1
            elif change == "native_input":
                v["files"]["origin-native-read.json"]["input"]["inputId"] = uid(31)
            elif change == "case_revision":
                consumer["proof"]["case_revision"] = 1
            else:
                v["snapshots"]["after_race"][P2]["inbox"][1]["wire_json"] = "{}"
            with self.subTest(change=change):
                self.assert_bad(v)

    def test_only_standard_library_imports_and_baseexception_remains_cancellation(self):
        import ast

        source = Path(SPEC.origin).read_text()
        modules = {
            node.module for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom)
        }
        modules.update(
            alias.name
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        self.assertLessEqual(
            modules,
            {"__future__", "base64", "hashlib", "hmac", "json", "re", "datetime", "typing", "uuid"},
        )
        with (
            patch.object(m, "_validate", side_effect=KeyboardInterrupt),
            self.assertRaises(KeyboardInterrupt),
        ):
            m.validate_bundle(fixture())

    def test_missing_or_malformed_proof_has_only_fixed_safe_error(self):
        for value in (None, [], {"PRIVATE_SENTINEL": "SECRET"}, {"schema_version": float("nan")}):
            self.assert_bad(value)
