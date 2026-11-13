"""Independent stdlib literals for owner rows, source signatures and read proofs."""

from __future__ import annotations

import ast
import copy
import hashlib
import hmac
import importlib.util
import json
import socket
import sys
import unittest
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "prepared_read_literal_oracle", ROOT / "local-setup/scripts/p2_prepared_read_evidence.py"
)
assert SPEC is not None and SPEC.loader is not None
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)
T = 1900000000000
SCHEMA = "p2_prepared_" + "a" * 32
TABLE_NAMES = [
    "admission",
    "associations",
    "callback_admission",
    "callback_observations",
    "callback_settings",
    "challenges",
    "communication_settings",
    "conversations",
    "dispatch_attempts",
    "dispatch_plans",
    "dispatch_settings",
    "inbox",
    "native_bindings",
    "native_observations",
    "native_responses",
    "native_settings",
    "outbound_routes",
    "outbox_admission",
    "outbox_settings",
    "processing_intents",
    "reply_intents",
    "result_receipts",
    "schema_metadata",
    "send_attempts",
    "send_operations",
    "send_policy_settings",
    "send_recovery_commands",
    "send_recovery_observations",
    "send_results",
    "sender_heads",
]
CASE_NAMES = {
    "null_without_plan",
    "original_native_sms_bytes",
    "replay_at_capacity",
    "revoked_source_history",
    "scoped_denials",
    "read_only_owner_rows",
    "held_read_owns_close",
    "settled_owned_cleanup",
}


def uid(number):
    return "00000000-0000-4000-8000-" + f"{number:012d}"


def stamp(ms):
    return (
        datetime.fromtimestamp(ms / 1000, UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def raw(value, ordered=False, ascii_only=False):
    return json.dumps(
        value,
        sort_keys=not ordered,
        ensure_ascii=ascii_only,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def fixture():
    scope = {"tenantId": "prepared_tenant", "accountId": "prepared_account"}
    config = {
        "schema_version": 1,
        "scope": scope,
        "case_id": "prepared_case",
        "conversation_id": "prepared_conversation",
        "binding_id": uid(1),
        "input_ids": {"unprepared": uid(2), "native": uid(3), "sms": uid(4)},
        "parent_expires_at_ms": T + 170000,
    }
    tables = {name: [] for name in TABLE_NAMES}
    tables["schema_metadata"] = [
        {
            "singleton": True,
            "version": 8,
            "runtime_role": "livekit_lab",
            "definition_digest": "a" * 64,
            "catalog_snapshot": {"all_columns": ["exact", "unchanged"]},
            "max_inbox": 3,
            "max_challenges": 4,
            "max_associations": 4,
            "max_senders": 4,
        }
    ]
    for name in (
        "callback_admission",
        "callback_settings",
        "communication_settings",
        "dispatch_settings",
        "native_settings",
        "outbox_admission",
        "send_policy_settings",
    ):
        tables[name] = [{"singleton": True}]
    tables["dispatch_settings"][0].update(
        max_active=2, max_attempts=3, lease_ms=500, retry_delay_ms=20
    )
    tables["admission"] = [
        {
            "singleton": True,
            "inbox_count": 3,
            "association_count": 1,
            "challenge_count": 1,
            "sender_count": 1,
        }
    ]
    tables["outbox_settings"] = [
        {
            "singleton": True,
            "receiver_id": uid(30),
            "max_replies": 4,
            "max_routes": 4,
            "max_attempts": 3,
        }
    ]
    tables["conversations"] = [
        {
            "tenant_id": scope["tenantId"],
            "account_id": scope["accountId"],
            "conversation_id": config["conversation_id"],
            "last_sequence": 3,
        }
    ]
    setup = {
        "schema_version": 1,
        "receiver_id": uid(30),
        "inputs": {},
        "plans": {},
        "capacity_code": "Overloaded",
        "revocations": {
            "native": {"bindingId": uid(1), "revokedAt": stamp(T + 5000)},
            "sms": {"revoked": True, "associationVersion": "2"},
        },
        "synthetic_ports": True,
    }
    bodies = [
        "Retain without preparing.",
        "Read the original policy: café 🧭.",
        "Review the signed SMS policy.",
    ]
    for index, label in enumerate(("unprepared", "native", "sms")):
        native = label != "sms"
        provider = {
            "tenantId": scope["tenantId"],
            "provider": "livekit" if native else "fake_sms",
            "providerAccountId": "prepared_rtc" if native else "prepared_sms",
        }
        event = {
            "schemaVersion": 1,
            "type": "text.received",
            "eventId": config["input_ids"][label],
            "providerScope": provider,
            "accountScope": scope,
            "caseId": config["case_id"],
            "conversationId": config["conversation_id"],
            "receivedAt": stamp(T + (index + 1) * 1000),
            "channel": "web_chat" if native else "sms",
            "messageId": config["input_ids"][label],
            "senderId": uid(1) if native else "prepared_sms_sender",
            "body": bodies[index],
        }
        if not native:
            event["occurredAt"] = event["receivedAt"]
        receipt, operation = uid(11 + index), uid(21 + index)
        setup["inputs"][label] = {"receiptId": receipt, "operationKey": operation}
        tables["inbox"].append(
            {
                "receipt_id": receipt,
                "tenant_id": scope["tenantId"],
                "account_id": scope["accountId"],
                "provider": provider["provider"],
                "provider_account_id": provider["providerAccountId"],
                "event_id": event["eventId"],
                "message_id": event["messageId"],
                "conversation_id": config["conversation_id"],
                "association_epoch": 1,
                "acceptance_sequence": index + 1,
                "accepted_at": event["receivedAt"],
                "wire_json": raw(event, ascii_only=True),
                "canonical_payload": raw(
                    {k: v for k, v in event.items() if k != "receivedAt"}, ascii_only=True
                ),
            }
        )
        tables["processing_intents"].append(
            {
                "receipt_id": receipt,
                "operation_key": operation,
                "state": "pending" if index == 0 else "dispatched",
                "claim_owner": None,
                "claim_until": None,
                "claim_kind": None,
                "next_attempt_at": None,
                "claim_epoch": 0 if index == 0 else 1,
                "attempt_count": 0 if index == 0 else 1,
                "possible_external": index != 0,
                "external_receipt_id": None if index == 0 else uid(60 + index),
                "last_code": "none" if index == 0 else "accepted",
            }
        )
        if index == 0:
            continue
        submission = {
            "schemaVersion": 1,
            "kind": "investigation",
            "operationKey": operation,
            "scope": scope,
            "caseId": config["case_id"],
            "caseRevision": "1",
            "conversationId": config["conversation_id"],
            "message": {
                "receiptId": receipt,
                "eventId": event["eventId"],
                "messageId": event["messageId"],
                "senderId": event["senderId"],
                "body": event["body"],
            },
        }
        canonical = raw(submission, ordered=True)
        setup["plans"][label] = {
            "submission": submission,
            "canonicalPayload": canonical,
            "payloadDigest": sha(canonical),
        }
        tables["dispatch_plans"].append(
            {
                "receipt_id": receipt,
                "operation_key": operation,
                "payload_json": canonical,
                "payload_digest": sha(canonical),
                "prepared_at": stamp(T + 3100 + index * 200),
                "association_epoch": 1,
            }
        )
        tables["dispatch_attempts"].append(
            {
                "receipt_id": receipt,
                "epoch": 1,
                "owner_id": uid(70 + index),
                "started_at": stamp(T + 3000 + index * 200),
                "finished_at": stamp(T + 3200 + index * 200),
                "disposition": "accepted",
            }
        )
    bound = {
        "schemaVersion": 1,
        "bindingId": uid(1),
        "providerScope": {
            "tenantId": scope["tenantId"],
            "provider": "livekit",
            "providerAccountId": "prepared_rtc",
        },
        "scope": scope,
        "caseId": config["case_id"],
        "conversationId": config["conversation_id"],
        "roomId": "prepared_room",
        "participantId": "prepared_participant",
        "expiresAt": stamp(T + 170000),
    }
    tables["native_bindings"] = [
        {
            "binding_id": uid(1),
            "tenant_id": scope["tenantId"],
            "account_id": scope["accountId"],
            "provider": "livekit",
            "provider_account_id": "prepared_rtc",
            "case_id": config["case_id"],
            "conversation_id": config["conversation_id"],
            "room_id": "prepared_room",
            "participant_id": "prepared_participant",
            "canonical_binding": raw(bound, ordered=True),
            "binding_digest": sha(raw(bound, ordered=True)),
            "bearer_digest": "b" * 64,
            "published_at": stamp(T),
            "expires_at": stamp(T + 170000),
            "revoked_at": stamp(T + 5000),
        }
    ]
    association = {
        "tenant_id": scope["tenantId"],
        "account_id": scope["accountId"],
        "provider": "fake_sms",
        "provider_account_id": "prepared_sms",
        "conversation_id": config["conversation_id"],
        "case_id": config["case_id"],
        "sender_id": "prepared_sms_sender",
        "epoch": 1,
        "activated_at": stamp(T + 2500),
        "revoked_at": stamp(T + 5500),
    }
    tables["associations"] = [association]
    tables["sender_heads"] = [
        {k: association[k] for k in ("tenant_id", "provider", "provider_account_id", "sender_id")}
        | {"epoch": 2, "active_epoch": None}
    ]
    tables["challenges"] = [
        {
            k: association[k]
            for k in (
                "tenant_id",
                "account_id",
                "provider",
                "provider_account_id",
                "sender_id",
                "case_id",
                "conversation_id",
            )
        }
        | {
            "challenge_id": uid(80),
            "expected_epoch": 0,
            "consumed_at": stamp(T + 2500),
            "secret_digest": "c" * 64,
        }
    ]
    event = json.loads(tables["inbox"][2]["wire_json"])
    signed = {
        k: event[k]
        for k in ("schemaVersion", "eventId", "messageId", "senderId", "body", "occurredAt")
    }
    sms_raw = raw(signed, ordered=True)
    timestamp = str((T + 3000) // 1000)
    domain = (
        "p2.fake_sms.v1\n" + scope["tenantId"] + "\nfake_sms\nprepared_sms\n" + timestamp + "\n"
    )
    sms = {
        "schema_version": 1,
        "raw_utf8": sms_raw,
        "headers": {
            "timestamp": timestamp,
            "signature": hmac.new(
                bytes([0x52]) * 32, domain.encode() + sms_raw.encode(), hashlib.sha256
            ).hexdigest(),
        },
    }
    holder_query = 'LOCK TABLE "' + SCHEMA + '"."dispatch_plans" IN ACCESS EXCLUSIVE MODE'
    query = (
        'SELECT payload_json,payload_digest FROM "'
        + SCHEMA
        + '"."dispatch_plans" WHERE receipt_id=$1'
    )
    lock = {
        "relation_oid": 501,
        "schema": SCHEMA,
        "table": "dispatch_plans",
        "locktype": "relation",
        "mode": "AccessExclusiveLock",
        "granted": True,
    }
    graph = {
        "schema": SCHEMA,
        "table": "dispatch_plans",
        "association": "unique_disposable_channel_schema",
        "row_lock": False,
        "holder_pid": 700,
        "holder_usename": "continuity_migrator",
        "expected_waiters": 1,
        "holder_query": holder_query,
        "holder_query_sha256": sha(holder_query),
        "holder_locks": [lock],
        "waiters": [
            {
                "pid": 701,
                "usename": "livekit_lab",
                "blockers": [700],
                "wait_event_type": "Lock",
                "query": query,
                "query_sha256": sha(query),
                "relation_locks": [{**lock, "mode": "AccessShareLock", "granted": False}],
            }
        ],
    }
    read = {
        "schema_version": 1,
        "status": "passed",
        "fixture_groups": [
            "known_unprepared_null",
            "exact_native_and_signed_sms_plans",
            "equal_read_replay_at_capacity",
            "retained_read_after_source_revocation",
            "foreign_unknown_scope_provider_denied",
            "actual_held_read_close_pending",
        ],
        "codes": {"foreign": "NotFound", "unknown": "NotFound", "wrong_provider": "NotFound"},
        "held_read_settled": True,
        "close_settled": True,
        "retained_owners": 0,
        "synthetic_ports": True,
        "actual_database_write_assertions": 0,
    }
    groups = {
        "schema_version": 1,
        "groups": [
            {
                "role": role,
                "pid": 101 + n,
                "returncode": 0,
                "group_settled": True,
                "cleanup_failed": False,
            }
            for n, role in enumerate(
                ("compile-public", "compile-fixture", "setup", "read", "cleanup")
            )
        ],
        "capture_bytes": 100,
    }
    return {
        "schema_version": 1,
        "config": config,
        "native_bearer_sha256": "b" * 64,
        "schema": SCHEMA,
        "setup": setup,
        "read": read,
        "sms_source": sms,
        "before": tables,
        "after": copy.deepcopy(tables),
        "observations": {
            "held_wait_graph": graph,
            "held_wait_graph_at_close": copy.deepcopy(graph),
            "close_pending": {
                "schema_version": 1,
                "pending_read": True,
                "pending_close": True,
                "subsequent_read_code": "StorageUnavailable",
            },
            "read_pid": 104,
        },
        "groups": groups,
        "cleanup": {
            "namespace_absent": True,
            "pre_drop_relation_locks": 0,
            "proof": {"schema_version": 1, "namespace_absent": True, "receiver_id": uid(30)},
            "owned_work_removal_authorized": True,
        },
    }


def rewrite_plan(value, label, transform):
    plan = value["setup"]["plans"][label]
    submission = copy.deepcopy(plan["submission"])
    transform(submission)
    canonical = raw(submission, ordered=True)
    plan.update(submission=submission, canonicalPayload=canonical, payloadDigest=sha(canonical))
    receipt = value["setup"]["inputs"][label]["receiptId"]
    for stage in ("before", "after"):
        row = next(row for row in value[stage]["dispatch_plans"] if row["receipt_id"] == receipt)
        row.update(payload_json=canonical, payload_digest=sha(canonical))


class PreparedEvidenceTests(unittest.TestCase):
    def assert_bad(self, value):
        with self.assertRaisesRegex(m.PreparedReadEvidenceError, "^invalid_proof$") as caught:
            m.validate_bundle(value)
        self.assertEqual(caught.exception.code, "invalid_proof")

    def test_literal_positive_eight_cases_and_input_is_never_mutated(self):
        value = fixture()
        before = raw(value)
        result = m.validate_bundle(value)
        self.assertEqual(set(result), CASE_NAMES)
        self.assertTrue(all(item == {"status": "passed", "code": "ok"} for item in result.values()))
        self.assertEqual(raw(value), before)

    def test_persisted_sorted_json_roundtrip_and_sql_row_order_are_independent(self):
        value = json.loads(raw(fixture()))
        self.assertEqual(list(value["config"]["scope"]), ["accountId", "tenantId"])
        for values in value["after"].values():
            values.reverse()
        self.assertEqual(len(m.validate_bundle(value)), 8)

    def test_complete_thirty_table_multisets_detect_all_columns_not_only_node_counters(self):
        for change in ("catalog", "unused", "missing", "extra", "many", "row_removed"):
            value = fixture()
            if change == "catalog":
                value["after"]["schema_metadata"][0]["catalog_snapshot"]["all_columns"].append(
                    "changed"
                )
            elif change == "unused":
                value["after"]["native_responses"].append({"model_statement": "PRIVATE_SENTINEL"})
            elif change == "missing":
                del value["after"]["callback_settings"]
            elif change == "extra":
                value["after"]["new_table"] = []
            elif change == "many":
                value["after"]["callback_observations"] = [{} for _ in range(65)]
            else:
                value["after"]["inbox"].pop()
            with self.subTest(change=change):
                self.assert_bad(value)

    def test_coordinated_plan_and_sha_forgeries_cannot_replace_original_inbox_source(self):
        for field, replacement in (
            ("body", "Forged policy."),
            ("receiptId", uid(99)),
            ("senderId", "foreign"),
        ):
            value = fixture()
            rewrite_plan(
                value,
                "native",
                lambda source, key=field, replacement=replacement: source["message"].update(
                    {key: replacement}
                ),
            )
            with self.subTest(field=field):
                self.assert_bad(value)
        value = fixture()
        rewrite_plan(value, "native", lambda source: source.update(caseRevision="2"))
        self.assert_bad(value)

    def test_coordinated_wire_canonical_plan_and_digest_forgery_still_fails_literal_body(self):
        value = fixture()
        for stage in ("before", "after"):
            row = value[stage]["inbox"][1]
            event = json.loads(row["wire_json"])
            event["body"] = "Forged body with recomputed hashes."
            row["wire_json"] = raw(event, ascii_only=True)
            row["canonical_payload"] = raw(
                {k: v for k, v in event.items() if k != "receivedAt"}, ascii_only=True
            )
        rewrite_plan(
            value,
            "native",
            lambda source: source["message"].update(body="Forged body with recomputed hashes."),
        )
        self.assert_bad(value)

    def test_coordinated_signed_sms_rows_and_plan_cannot_change_original_source_sender(self):
        value = fixture()
        for stage in ("before", "after"):
            row = value[stage]["inbox"][2]
            event = json.loads(row["wire_json"])
            event["senderId"] = "foreign_sender"
            row["wire_json"] = raw(event, ascii_only=True)
            row["canonical_payload"] = raw(
                {k: v for k, v in event.items() if k != "receivedAt"}, ascii_only=True
            )
        rewrite_plan(
            value, "sms", lambda source: source["message"].update(senderId="foreign_sender")
        )
        signed = json.loads(value["sms_source"]["raw_utf8"])
        signed["senderId"] = "foreign_sender"
        sms_raw = raw(signed, ordered=True)
        value["sms_source"]["raw_utf8"] = sms_raw
        domain = (
            "p2.fake_sms.v1\nprepared_tenant\nfake_sms\nprepared_sms\n"
            + value["sms_source"]["headers"]["timestamp"]
            + "\n"
        )
        value["sms_source"]["headers"]["signature"] = hmac.new(
            bytes([0x52]) * 32, domain.encode() + sms_raw.encode(), hashlib.sha256
        ).hexdigest()
        self.assert_bad(value)

    def test_pg_microseconds_floor_to_exact_js_milliseconds_with_timezone_equivalence(self):
        for stamp_value, expected in (
            ("2026-11-12T23:47:46.220746+00:00", 1794527266220),
            ("2026-11-13T05:17:46.220746+05:30", 1794527266220),
            ("1969-12-31T23:59:59.999999Z", -1),
            ("1970-01-01T00:00:00.000999Z", 0),
        ):
            self.assertEqual(m.millis(stamp_value), expected)
        value = fixture()
        for stage in ("before", "after"):
            for row in value[stage]["inbox"]:
                instant = datetime.fromisoformat(row["accepted_at"]) + timedelta(microseconds=999)
                row["accepted_at"] = instant.astimezone(
                    timezone(timedelta(hours=5, minutes=30))
                ).isoformat(timespec="microseconds")
            value[stage]["native_bindings"][0]["revoked_at"] = stamp(T + 5000).replace(
                "000Z", "000999+00:00"
            )
        self.assertEqual(len(m.validate_bundle(json.loads(raw(value)))), 8)

    def test_prepared_original_identity_scope_provider_and_receipt_cannot_be_swapped(self):
        for change in ("scope", "provider", "operation", "receipt", "profile", "native_binding"):
            value = fixture()
            if change == "scope":
                rewrite_plan(
                    value, "native", lambda source: source["scope"].update(accountId="foreign")
                )
            elif change == "provider":
                for stage in ("before", "after"):
                    value[stage]["inbox"][1]["provider_account_id"] = "foreign"
            elif change == "operation":
                value["setup"]["inputs"]["native"]["operationKey"] = uid(99)
            elif change == "receipt":
                value["setup"]["inputs"]["native"]["receiptId"] = value["setup"]["inputs"]["sms"][
                    "receiptId"
                ]
            elif change == "profile":
                value["setup"]["receiver_id"] = uid(99)
            else:
                for stage in ("before", "after"):
                    value[stage]["native_bindings"][0]["room_id"] = "other_room"
            with self.subTest(change=change):
                self.assert_bad(value)

    def test_unprepared_gap_and_exact_capacity_remain_truthful(self):
        for change in (
            "count",
            "cap",
            "unprepared_state",
            "pending_work",
            "extra_plan",
            "new_attempt",
        ):
            value = fixture()
            for stage in ("before", "after"):
                if change == "count":
                    value[stage]["admission"][0]["inbox_count"] = 2
                elif change == "cap":
                    value[stage]["schema_metadata"][0]["max_inbox"] = 4
                elif change == "unprepared_state":
                    value[stage]["processing_intents"][0]["state"] = "blocked"
                elif change == "pending_work":
                    value[stage]["processing_intents"][0]["external_receipt_id"] = uid(99)
                elif change == "extra_plan":
                    value[stage]["dispatch_plans"].append(
                        copy.deepcopy(value[stage]["dispatch_plans"][0])
                    )
                else:
                    value[stage]["dispatch_attempts"][0]["epoch"] = 2
            with self.subTest(change=change):
                self.assert_bad(value)

    def test_revoked_native_and_sms_epoch_history_does_not_grant_new_acceptance(self):
        for change in ("native", "sms", "epoch", "active", "challenge"):
            value = fixture()
            for stage in ("before", "after"):
                if change == "native":
                    value[stage]["native_bindings"][0]["revoked_at"] = None
                elif change == "sms":
                    value[stage]["associations"][0]["revoked_at"] = None
                elif change == "epoch":
                    value[stage]["sender_heads"][0]["epoch"] = 1
                elif change == "active":
                    value[stage]["sender_heads"][0]["active_epoch"] = 1
                else:
                    value[stage]["challenges"][0]["consumed_at"] = None
            with self.subTest(change=change):
                self.assert_bad(value)

    def test_exact_signed_sms_bytes_and_domain_are_independently_verified(self):
        for change in ("signature", "raw", "header", "domain"):
            value = fixture()
            sms = value["sms_source"]
            if change == "signature":
                sms["headers"]["signature"] = "f" * 64
            elif change == "raw":
                sms["raw_utf8"] += " "
            elif change == "header":
                sms["headers"]["timestamp"] = "0190000000"
            else:
                sms["headers"]["signature"] = hmac.new(
                    bytes([0x52]) * 32, sms["raw_utf8"].encode(), hashlib.sha256
                ).hexdigest()
            with self.subTest(change=change):
                self.assert_bad(value)

    def test_held_relation_lock_and_ownership_cannot_be_forged_by_caller_markers(self):
        for change in (
            "missing",
            "query",
            "oid",
            "mode",
            "grant",
            "blocker",
            "pid",
            "close",
            "later_read",
        ):
            value = fixture()
            graph = value["observations"]["held_wait_graph"]
            if change == "missing":
                graph["waiters"] = []
            elif change == "query":
                graph["waiters"][0]["query_sha256"] = "f" * 64
            elif change == "oid":
                graph["waiters"][0]["relation_locks"][0]["relation_oid"] = 999
            elif change == "mode":
                graph["holder_locks"][0]["mode"] = "RowShareLock"
            elif change == "grant":
                graph["waiters"][0]["relation_locks"][0]["granted"] = True
            elif change == "blocker":
                graph["waiters"][0]["blockers"] = [999]
            elif change == "pid":
                graph["waiters"][0]["pid"] = graph["holder_pid"]
            elif change == "close":
                value["observations"]["close_pending"]["pending_close"] = False
            else:
                value["observations"]["close_pending"]["subsequent_read_code"] = "NotFound"
            value["observations"]["held_wait_graph_at_close"] = copy.deepcopy(graph)
            with self.subTest(change=change):
                self.assert_bad(value)

    def test_actual_backend_roles_are_required_in_both_observations(self):
        for stage in ("held_wait_graph", "held_wait_graph_at_close", "both"):
            for change in ("holder", "waiter", "missing", "extra"):
                value = fixture()
                names = (
                    ("held_wait_graph", "held_wait_graph_at_close") if stage == "both" else (stage,)
                )
                for name in names:
                    graph = value["observations"][name]
                    if change == "holder":
                        graph["holder_usename"] = "livekit_lab"
                    elif change == "waiter":
                        graph["waiters"][0]["usename"] = "continuity_migrator"
                    elif change == "missing":
                        graph.pop("holder_usename")
                    else:
                        graph["waiters"][0]["decorative_role"] = "livekit_lab"
                with self.subTest(stage=stage, change=change):
                    self.assert_bad(value)

    def test_native_bearer_digest_joins_parent_configuration_after_coordinated_tampering(self):
        for change in ("both_rows", "expected", "missing", "invalid"):
            value = fixture()
            if change == "both_rows":
                for stage in ("before", "after"):
                    value[stage]["native_bindings"][0]["bearer_digest"] = "f" * 64
            elif change == "expected":
                value["native_bearer_sha256"] = "f" * 64
            elif change == "missing":
                value.pop("native_bearer_sha256")
            else:
                value["native_bearer_sha256"] = "B" * 64
            with self.subTest(change=change):
                self.assert_bad(value)

    def test_metadata_select_is_actual_public_read_io_and_os_pg_pid_spaces_are_separate(self):
        value = fixture()
        query = "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE connamespace=$1"
        for name in ("held_wait_graph", "held_wait_graph_at_close"):
            value["observations"][name]["waiters"][0].update(query=query, query_sha256=sha(query))
        value["observations"]["read_pid"] = 701
        value["groups"]["groups"][3]["pid"] = 701
        self.assertEqual(len(m.validate_bundle(value)), 8)

    def test_final_owned_groups_cleanup_and_receiver_are_not_premature_claims(self):
        for change in (
            "group",
            "returncode",
            "role",
            "read_pid",
            "locks",
            "namespace",
            "receiver",
            "removed",
            "capture",
        ):
            value = fixture()
            if change == "group":
                value["groups"]["groups"][3]["group_settled"] = False
            elif change == "returncode":
                value["groups"]["groups"][3]["returncode"] = -9
            elif change == "role":
                value["groups"]["groups"][3]["role"] = "setup"
            elif change == "read_pid":
                value["observations"]["read_pid"] = 999
            elif change == "locks":
                value["cleanup"]["pre_drop_relation_locks"] = 1
            elif change == "namespace":
                value["cleanup"]["namespace_absent"] = False
            elif change == "receiver":
                value["cleanup"]["proof"]["receiver_id"] = uid(99)
            elif change == "removed":
                value["cleanup"]["owned_work_removed"] = True
            else:
                value["groups"]["capture_bytes"] = 1048577
            with self.subTest(change=change):
                self.assert_bad(value)

    def test_node_counters_never_stand_in_for_parent_whole_schema_assertions(self):
        for change in ("inflated", "missing_null", "denial", "owners", "ports"):
            value = fixture()
            if change == "inflated":
                value["read"]["actual_database_write_assertions"] = 2
            elif change == "missing_null":
                value["read"]["fixture_groups"].pop(0)
            elif change == "denial":
                value["read"]["codes"]["foreign"] = "absent"
            elif change == "owners":
                value["read"]["retained_owners"] = 1
            else:
                value["read"]["synthetic_ports"] = False
            with self.subTest(change=change):
                self.assert_bad(value)

    def test_versions_bool_duplicates_nonfinite_surrogates_and_bounds_fail_closed(self):
        for change in (
            "version",
            "schema",
            "bool",
            "duplicate_wire",
            "nonfinite",
            "surrogate",
            "oversized",
        ):
            value = fixture()
            if change == "version":
                value["before"]["schema_metadata"][0]["version"] = 7
                value["after"] = copy.deepcopy(value["before"])
            elif change == "schema":
                value["schema"] = "public"
            elif change == "bool":
                value["groups"]["groups"][0]["returncode"] = False
            elif change == "duplicate_wire":
                for stage in ("before", "after"):
                    value[stage]["inbox"][0]["wire_json"] = '{"schemaVersion":1,"schemaVersion":1}'
            elif change == "nonfinite":
                value["before"]["schema_metadata"][0]["max_inbox"] = float("nan")
            elif change == "surrogate":
                value["sms_source"]["raw_utf8"] = "\ud800"
            else:
                value["before"]["schema_metadata"][0]["catalog_snapshot"] = "x" * 2097152
            with self.subTest(change=change):
                self.assert_bad(value)

    def test_import_and_validation_are_stdlib_only_inert_with_safe_finite_diagnostics(self):
        fresh_spec = importlib.util.spec_from_file_location(
            "prepared_read_inert_probe", SPEC.origin
        )
        self.assertIsNotNone(fresh_spec)
        fresh = importlib.util.module_from_spec(fresh_spec)
        sys.modules[fresh_spec.name] = fresh
        try:
            with patch.object(socket, "socket", side_effect=AssertionError("socket")):
                fresh_spec.loader.exec_module(fresh)
                self.assertEqual(len(fresh.validate_bundle(fixture())), 8)
        finally:
            sys.modules.pop(fresh_spec.name, None)
        imports = ast.parse(Path(SPEC.origin).read_text())
        modules = {n.module for n in ast.walk(imports) if isinstance(n, ast.ImportFrom)}
        modules.update(
            alias.name for n in ast.walk(imports) if isinstance(n, ast.Import) for alias in n.names
        )
        self.assertLessEqual(
            modules,
            {
                "__future__",
                "hashlib",
                "hmac",
                "json",
                "re",
                "collections",
                "datetime",
                "typing",
                "uuid",
            },
        )
        for value in (None, [], {"PRIVATE_SECRET_SENTINEL": "SECRET"}):
            self.assert_bad(value)
        with (
            patch.object(m, "_validate", side_effect=KeyboardInterrupt),
            self.assertRaises(KeyboardInterrupt),
        ):
            m.validate_bundle(fixture())
        self.assertEqual(len(m.validate_bundle(fixture())), 8)
