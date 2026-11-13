"""Independent literal oracle for the eight selected public prepared-read cases.

Only supplied owner snapshots and source-bound observations are examined. This
module performs no I/O, imports no product codec and grants no work authority.
Full table multisets, original bytes and actual held owners are separate proof.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections import Counter
from datetime import UTC, datetime
from typing import Any, Literal, TypedDict, cast
from uuid import UUID

CASES = (
    "null_without_plan",
    "original_native_sms_bytes",
    "replay_at_capacity",
    "revoked_source_history",
    "scoped_denials",
    "read_only_owner_rows",
    "held_read_owns_close",
    "settled_owned_cleanup",
)
TABLES = frozenset(
    [
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
)
_ROLES = {"compile-public", "compile-fixture", "setup", "read", "cleanup"}
_BODIES = {
    "unprepared": "Retain without preparing.",
    "native": "Read the original policy: café 🧭.",
    "sms": "Review the signed SMS policy.",
}
_FIXTURE_GROUPS = [
    "known_unprepared_null",
    "exact_native_and_signed_sms_plans",
    "equal_read_replay_at_capacity",
    "retained_read_after_source_revocation",
    "foreign_unknown_scope_provider_denied",
    "actual_held_read_close_pending",
]


class PreparedReadEvidenceError(ValueError):
    def __init__(self) -> None:
        self.code: Literal["invalid_proof"] = "invalid_proof"
        super().__init__(self.code)


class CaseResult(TypedDict):
    status: Literal["passed"]
    code: Literal["ok"]


def need(condition: object) -> None:
    if condition is not True:
        raise PreparedReadEvidenceError()


def obj(value: object, fields: set[str] | None = None) -> dict[str, Any]:
    need(type(value) is dict)
    result = cast(dict[str, Any], value)
    need(all(type(key) is str for key in result))
    if fields is not None:
        need(set(result) == fields)
    return result


def rows(value: object, maximum: int = 64) -> list[dict[str, Any]]:
    need(type(value) is list and len(cast(list[object], value)) <= maximum)
    return [obj(item) for item in cast(list[object], value)]


def integer(value: object, low: int = 0, high: int = 4102444800000) -> int:
    need(type(value) is int)
    result = cast(int, value)
    need(low <= result <= high)
    return result


def text(value: object, maximum: int = 32768) -> str:
    need(type(value) is str)
    result = cast(str, value)
    need(len(result.encode("utf-8", "strict")) <= maximum)
    return result


def identifier(value: object) -> str:
    result = text(value, 64)
    need(re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", result, re.ASCII) is not None)
    return result


def uuid(value: object) -> str:
    result = text(value, 36)
    parsed = UUID(result)
    need(parsed.version == 4 and str(parsed) == result)
    return result


def digest(value: object) -> str:
    result = text(value, 64)
    need(re.fullmatch(r"[0-9a-f]{64}", result, re.ASCII) is not None)
    return result


def packed(value: object, *, ordered: bool = False, ascii_only: bool = False) -> str:
    return json.dumps(
        value,
        sort_keys=not ordered,
        ensure_ascii=ascii_only,
        separators=(",", ":"),
        allow_nan=False,
    )


def same(left: object, right: object) -> None:
    need(packed(left) == packed(right))


def sha(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8", "strict")).hexdigest()


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        need(key not in result)
        result[key] = value
    return result


def _nonfinite(_: str) -> object:
    raise PreparedReadEvidenceError()


def decode(value: object) -> dict[str, Any]:
    raw = text(value)
    result: object = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_nonfinite)
    return obj(result)


def one(values: list[dict[str, Any]], key: str, expected: object) -> dict[str, Any]:
    found = [value for value in values if packed(value.get(key)) == packed(expected)]
    need(len(found) == 1)
    return found[0]


def millis(value: object, *, wire: bool = False) -> int:
    raw = text(value, 64)
    if wire:
        need(
            re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z", raw)
            is not None
        )
    parsed = datetime.fromisoformat(raw)
    offset = parsed.utcoffset()
    if parsed.tzinfo is None or offset is None:
        raise PreparedReadEvidenceError()
    delta = parsed.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    # Match JavaScript Date's millisecond observation of real PostgreSQL µs.
    # Integer floor also handles pre-epoch instants without floating-point loss.
    microseconds = ((delta.days * 86400 + delta.seconds) * 1000000) + delta.microseconds
    return microseconds // 1000


def iso(value: object) -> str:
    ms = integer(value)
    return (
        datetime.fromtimestamp(ms // 1000, UTC).strftime("%Y-%m-%dT%H:%M:%S") + f".{ms % 1000:03d}Z"
    )


def snapshot(value: object) -> dict[str, list[dict[str, Any]]]:
    raw = obj(value, set(TABLES))
    return {table: rows(raw[table]) for table in TABLES}


def graph(value: object, schema: str) -> dict[str, Any]:
    g = obj(
        value,
        {
            "schema",
            "table",
            "association",
            "row_lock",
            "holder_pid",
            "holder_usename",
            "expected_waiters",
            "holder_query",
            "holder_query_sha256",
            "holder_locks",
            "waiters",
        },
    )
    same(g["holder_usename"], "continuity_migrator")
    same(g["schema"], schema)
    same(g["table"], "dispatch_plans")
    same(g["association"], "unique_disposable_channel_schema")
    need(g["row_lock"] is False)
    holder = integer(g["holder_pid"], 1, 2147483647)
    same(integer(g["expected_waiters"]), 1)
    holder_query = text(g["holder_query"], 16384)
    same(digest(g["holder_query_sha256"]), sha(holder_query))
    need(
        re.search(re.escape(schema) + r'"?\."?dispatch_plans', holder_query) is not None
        and "ACCESS EXCLUSIVE" in holder_query.upper()
    )

    def locks(
        value: object, expected_mode: str, granted: bool, expected_oid: int | None = None
    ) -> int:
        values = rows(value, 8)
        need(bool(values))
        identities: set[tuple[str, bool]] = set()
        oids: set[int] = set()
        for lock in values:
            obj(lock, {"relation_oid", "schema", "table", "locktype", "mode", "granted"})
            same(lock["schema"], schema)
            same(lock["table"], "dispatch_plans")
            same(lock["locktype"], "relation")
            need(type(lock["granted"]) is bool)
            mode = text(lock["mode"], 32)
            need(
                mode
                in {
                    "AccessShareLock",
                    "RowShareLock",
                    "RowExclusiveLock",
                    "ShareUpdateExclusiveLock",
                    "ShareLock",
                    "ShareRowExclusiveLock",
                    "ExclusiveLock",
                    "AccessExclusiveLock",
                }
            )
            identity = (mode, lock["granted"])
            need(identity not in identities)
            identities.add(identity)
            oids.add(integer(lock["relation_oid"], 1, 4294967295))
        need(len(oids) == 1 and (expected_mode, granted) in identities)
        oid = next(iter(oids))
        if expected_oid is not None:
            same(oid, expected_oid)
        return oid

    oid = locks(g["holder_locks"], "AccessExclusiveLock", True)
    need(all(lock["granted"] is True for lock in g["holder_locks"]))
    waiters = rows(g["waiters"], 1)
    need(len(waiters) == 1)
    waiter = obj(
        waiters[0],
        {
            "pid",
            "usename",
            "blockers",
            "wait_event_type",
            "query",
            "query_sha256",
            "relation_locks",
        },
    )
    same(waiter["usename"], "livekit_lab")
    need(integer(waiter["pid"], 1, 2147483647) != holder)
    same(waiter["blockers"], [holder])
    same(waiter["wait_event_type"], "Lock")
    query = text(waiter["query"], 16384)
    need(query.lstrip().upper().startswith("SELECT"))
    same(digest(waiter["query_sha256"]), sha(query))
    locks(waiter["relation_locks"], "AccessShareLock", False, oid)
    return g


def _validate(bundle: object) -> dict[str, CaseResult]:
    b = obj(
        bundle,
        {
            "schema_version",
            "config",
            "native_bearer_sha256",
            "schema",
            "setup",
            "read",
            "sms_source",
            "before",
            "after",
            "observations",
            "groups",
            "cleanup",
        },
    )
    same(integer(b["schema_version"]), 1)
    need(len(packed(b).encode("utf-8", "strict")) <= 2097152)
    schema = text(b["schema"], 63)
    need(re.fullmatch(r"p2_prepared_[0-9a-f]{32}", schema) is not None)
    config = obj(
        b["config"],
        {
            "schema_version",
            "scope",
            "case_id",
            "conversation_id",
            "binding_id",
            "input_ids",
            "parent_expires_at_ms",
        },
    )
    same(integer(config["schema_version"]), 1)
    scoped = obj(config["scope"], {"tenantId", "accountId"})
    scope = {
        "tenantId": identifier(scoped["tenantId"]),
        "accountId": identifier(scoped["accountId"]),
    }
    identifier(config["case_id"])
    identifier(config["conversation_id"])
    binding_id = uuid(config["binding_id"])
    input_ids = obj(config["input_ids"], {"unprepared", "native", "sms"})
    need(len({binding_id, *(uuid(value) for value in input_ids.values())}) == 4)
    integer(config["parent_expires_at_ms"], 1)
    before, after = snapshot(b["before"]), snapshot(b["after"])
    for table in TABLES:
        same(
            dict(Counter(packed(row) for row in before[table])),
            dict(Counter(packed(row) for row in after[table])),
        )
    metadata = before["schema_metadata"]
    need(len(metadata) == 1)
    for key, expected_count in (
        ("version", 8),
        ("max_inbox", 3),
        ("max_challenges", 4),
        ("max_associations", 4),
        ("max_senders", 4),
    ):
        same(integer(metadata[0][key]), expected_count)
    need(metadata[0]["singleton"] is True)
    same(metadata[0]["runtime_role"], "livekit_lab")
    for table in (
        "reply_intents",
        "result_receipts",
        "send_attempts",
        "send_results",
        "send_operations",
        "send_recovery_commands",
        "send_recovery_observations",
        "outbound_routes",
        "callback_observations",
        "native_observations",
        "native_responses",
    ):
        same(before[table], [])
    setup = obj(
        b["setup"],
        {
            "schema_version",
            "receiver_id",
            "inputs",
            "plans",
            "capacity_code",
            "revocations",
            "synthetic_ports",
        },
    )
    same(integer(setup["schema_version"]), 1)
    need(setup["synthetic_ports"] is True)
    same(setup["capacity_code"], "Overloaded")
    receiver = uuid(setup["receiver_id"])
    need(len(before["outbox_settings"]) == 1)
    same(before["outbox_settings"][0]["receiver_id"], receiver)
    need(len(before["inbox"]) == len(before["processing_intents"]) == 3)
    need(len(before["dispatch_plans"]) == len(before["dispatch_attempts"]) == 2)
    need(len(before["admission"]) == len(before["conversations"]) == 1)
    same(integer(before["admission"][0]["inbox_count"]), 3)
    conversation = before["conversations"][0]
    for key, expected in (
        ("tenant_id", scope["tenantId"]),
        ("account_id", scope["accountId"]),
        ("conversation_id", config["conversation_id"]),
    ):
        same(conversation[key], expected)
    same(integer(conversation["last_sequence"]), 3)
    inputs = obj(setup["inputs"], {"unprepared", "native", "sms"})
    plans = obj(setup["plans"], {"native", "sms"})
    revocations = obj(setup["revocations"], {"native", "sms"})
    native_revocation = obj(revocations["native"], {"bindingId", "revokedAt"})
    same(native_revocation["bindingId"], binding_id)
    native_revoked_ms = millis(native_revocation["revokedAt"], wire=True)
    same(
        obj(revocations["sms"], {"revoked", "associationVersion"}),
        {"revoked": True, "associationVersion": "2"},
    )
    receipts: set[str] = set()
    operations: set[str] = set()
    source_events: dict[str, dict[str, Any]] = {}
    for ordinal, label in enumerate(("unprepared", "native", "sms"), 1):
        identity = obj(inputs[label], {"receiptId", "operationKey"})
        receipt, operation = uuid(identity["receiptId"]), uuid(identity["operationKey"])
        need(receipt not in receipts and operation not in operations)
        receipts.add(receipt)
        operations.add(operation)
        inbox = one(before["inbox"], "receipt_id", receipt)
        process = one(before["processing_intents"], "receipt_id", receipt)
        same(process["operation_key"], operation)
        event = decode(inbox["wire_json"])
        source_events[label] = event
        fields = {
            "schemaVersion",
            "type",
            "eventId",
            "providerScope",
            "accountScope",
            "caseId",
            "conversationId",
            "receivedAt",
            "channel",
            "messageId",
            "senderId",
            "body",
        }
        if label == "sms":
            fields.add("occurredAt")
        obj(event, fields)
        same(integer(event["schemaVersion"]), 1)
        same(event["type"], "text.received")
        same(event["accountScope"], scope)
        same(event["caseId"], config["case_id"])
        same(event["conversationId"], config["conversation_id"])
        same(event["eventId"], input_ids[label])
        same(event["messageId"], input_ids[label])
        same(event["body"], _BODIES[label])
        text(event["body"], 4096)
        native = label != "sms"
        provider = {
            "tenantId": scope["tenantId"],
            "provider": "livekit" if native else "fake_sms",
            "providerAccountId": "prepared_rtc" if native else "prepared_sms",
        }
        same(event["providerScope"], provider)
        same(event["channel"], "web_chat" if native else "sms")
        same(event["senderId"], binding_id if native else "prepared_sms_sender")
        for key, expected in (
            ("tenant_id", scope["tenantId"]),
            ("account_id", scope["accountId"]),
            ("conversation_id", config["conversation_id"]),
            ("provider", provider["provider"]),
            ("provider_account_id", provider["providerAccountId"]),
            ("event_id", input_ids[label]),
            ("message_id", input_ids[label]),
        ):
            same(inbox[key], expected)
        same(integer(inbox["association_epoch"]), 1)
        same(integer(inbox["acceptance_sequence"]), ordinal)
        accepted_ms = millis(inbox["accepted_at"])
        same(accepted_ms, millis(event["receivedAt"], wire=True))
        same(inbox["wire_json"], packed(event, ascii_only=True))
        same(
            inbox["canonical_payload"],
            packed(
                {key: value for key, value in event.items() if key != "receivedAt"}, ascii_only=True
            ),
        )
        for key in ("claim_owner", "claim_until", "claim_kind", "next_attempt_at"):
            need(process[key] is None)
        if label == "unprepared":
            same(process["state"], "pending")
            same(integer(process["attempt_count"]), 0)
            same(integer(process["claim_epoch"]), 0)
            need(process["possible_external"] is False and process["external_receipt_id"] is None)
            same(process["last_code"], "none")
            need(
                not any(
                    row["receipt_id"] == receipt
                    for table in ("dispatch_plans", "dispatch_attempts")
                    for row in before[table]
                )
            )
            continue
        same(process["state"], "dispatched")
        same(integer(process["attempt_count"]), 1)
        same(integer(process["claim_epoch"]), 1)
        need(process["possible_external"] is True)
        uuid(process["external_receipt_id"])
        same(process["last_code"], "accepted")
        plan = one(before["dispatch_plans"], "receipt_id", receipt)
        same(plan["operation_key"], operation)
        same(integer(plan["association_epoch"]), 1)
        submission = {
            "schemaVersion": 1,
            "kind": "investigation",
            "operationKey": operation,
            "scope": {"tenantId": scope["tenantId"], "accountId": scope["accountId"]},
            "caseId": config["case_id"],
            "caseRevision": "1",
            "conversationId": config["conversation_id"],
            "message": {
                "receiptId": receipt,
                "eventId": input_ids[label],
                "messageId": input_ids[label],
                "senderId": event["senderId"],
                "body": event["body"],
            },
        }
        canonical = packed(submission, ordered=True)
        same(text(plan["payload_json"]), canonical)
        same(digest(plan["payload_digest"]), sha(canonical))
        same(
            obj(plans[label], {"submission", "canonicalPayload", "payloadDigest"}),
            {
                "submission": submission,
                "canonicalPayload": canonical,
                "payloadDigest": sha(canonical),
            },
        )
        frame = {"schemaVersion": 1, "canonicalPayload": canonical, "payloadDigest": sha(canonical)}
        need(len(packed(frame, ordered=True).encode()) <= 32768)
        attempt = one(before["dispatch_attempts"], "receipt_id", receipt)
        same(integer(attempt["epoch"]), 1)
        uuid(attempt["owner_id"])
        same(attempt["disposition"], "accepted")
        need(
            accepted_ms
            <= millis(attempt["started_at"])
            <= millis(plan["prepared_at"])
            <= millis(attempt["finished_at"])
            <= native_revoked_ms
        )
    need(len(receipts | operations) == 6)
    need(
        len(before["native_bindings"])
        == len(before["associations"])
        == len(before["sender_heads"])
        == len(before["challenges"])
        == 1
    )
    binding = before["native_bindings"][0]
    same(binding["binding_id"], binding_id)
    native_provider = {
        "tenantId": scope["tenantId"],
        "provider": "livekit",
        "providerAccountId": "prepared_rtc",
    }
    bound = {
        "schemaVersion": 1,
        "bindingId": binding_id,
        "providerScope": native_provider,
        "scope": {"tenantId": scope["tenantId"], "accountId": scope["accountId"]},
        "caseId": config["case_id"],
        "conversationId": config["conversation_id"],
        "roomId": "prepared_room",
        "participantId": "prepared_participant",
        "expiresAt": iso(config["parent_expires_at_ms"]),
    }
    same(decode(binding["canonical_binding"]), bound)
    same(text(binding["canonical_binding"]), packed(bound, ordered=True))
    same(digest(binding["binding_digest"]), sha(binding["canonical_binding"]))
    same(digest(binding["bearer_digest"]), digest(b["native_bearer_sha256"]))
    for key, expected in (
        ("tenant_id", scope["tenantId"]),
        ("account_id", scope["accountId"]),
        ("provider", "livekit"),
        ("provider_account_id", "prepared_rtc"),
        ("conversation_id", config["conversation_id"]),
        ("case_id", config["case_id"]),
        ("room_id", "prepared_room"),
        ("participant_id", "prepared_participant"),
    ):
        same(binding[key], expected)
    same(millis(binding["expires_at"]), config["parent_expires_at_ms"])
    same(millis(binding["revoked_at"]), native_revoked_ms)
    for label in ("unprepared", "native"):
        need(
            millis(binding["published_at"])
            <= millis(source_events[label]["receivedAt"])
            <= native_revoked_ms
            < config["parent_expires_at_ms"]
        )
    association, head, challenge = (
        before["associations"][0],
        before["sender_heads"][0],
        before["challenges"][0],
    )
    for key, expected in (
        ("tenant_id", scope["tenantId"]),
        ("provider", "fake_sms"),
        ("provider_account_id", "prepared_sms"),
        ("sender_id", "prepared_sms_sender"),
    ):
        for row in (association, head, challenge):
            same(row[key], expected)
    for key, expected in (
        ("account_id", scope["accountId"]),
        ("case_id", config["case_id"]),
        ("conversation_id", config["conversation_id"]),
    ):
        same(association[key], expected)
        same(challenge[key], expected)
    same(integer(association["epoch"]), 1)
    same(integer(head["epoch"]), 2)
    need(head["active_epoch"] is None)
    same(integer(challenge["expected_epoch"]), 0)
    need(
        millis(challenge["consumed_at"])
        <= millis(association["activated_at"])
        <= millis(source_events["sms"]["receivedAt"])
        <= millis(association["revoked_at"])
    )
    sms = obj(b["sms_source"], {"schema_version", "raw_utf8", "headers"})
    same(integer(sms["schema_version"]), 1)
    signed = decode(sms["raw_utf8"])
    obj(signed, {"schemaVersion", "eventId", "messageId", "senderId", "body", "occurredAt"})
    same(integer(signed["schemaVersion"]), 1)
    for key in ("eventId", "messageId", "senderId", "body", "occurredAt"):
        same(signed[key], source_events["sms"][key])
    millis(signed["occurredAt"], wire=True)
    headers = obj(sms["headers"], {"timestamp", "signature"})
    timestamp = text(headers["timestamp"], 10)
    need(re.fullmatch(r"[1-9][0-9]{9}", timestamp) is not None)
    domain = (
        "p2.fake_sms.v1\n" + scope["tenantId"] + "\nfake_sms\nprepared_sms\n" + timestamp + "\n"
    )
    expected = hmac.new(
        bytes([0x52]) * 32, domain.encode() + text(sms["raw_utf8"]).encode(), hashlib.sha256
    ).hexdigest()
    same(digest(headers["signature"]), expected)
    need(abs(millis(source_events["sms"]["receivedAt"]) / 1000 - int(timestamp)) <= 60)
    read = obj(
        b["read"],
        {
            "schema_version",
            "status",
            "fixture_groups",
            "codes",
            "held_read_settled",
            "close_settled",
            "retained_owners",
            "synthetic_ports",
            "actual_database_write_assertions",
        },
    )
    same(integer(read["schema_version"]), 1)
    same(read["status"], "passed")
    same(read["fixture_groups"], _FIXTURE_GROUPS)
    same(
        read["codes"], {"foreign": "NotFound", "unknown": "NotFound", "wrong_provider": "NotFound"}
    )
    need(
        read["held_read_settled"] is True
        and read["close_settled"] is True
        and read["synthetic_ports"] is True
    )
    same(integer(read["retained_owners"]), 0)
    same(integer(read["actual_database_write_assertions"]), 0)
    observations = obj(
        b["observations"],
        {"held_wait_graph", "held_wait_graph_at_close", "close_pending", "read_pid"},
    )
    initial_graph = graph(observations["held_wait_graph"], schema)
    same(initial_graph, graph(observations["held_wait_graph_at_close"], schema))
    same(
        observations["close_pending"],
        {
            "schema_version": 1,
            "pending_read": True,
            "pending_close": True,
            "subsequent_read_code": "StorageUnavailable",
        },
    )
    groups = obj(b["groups"], {"schema_version", "groups", "capture_bytes"})
    same(integer(groups["schema_version"]), 1)
    integer(groups["capture_bytes"], 0, 1048576)
    group_rows = rows(groups["groups"], 5)
    need(len(group_rows) == 5 and {row["role"] for row in group_rows} == _ROLES)
    pids: set[int] = set()
    for row in group_rows:
        obj(row, {"role", "pid", "returncode", "group_settled", "cleanup_failed"})
        pid = integer(row["pid"], 1, 2147483647)
        need(pid not in pids)
        pids.add(pid)
        same(integer(row["returncode"]), 0)
        need(row["group_settled"] is True and row["cleanup_failed"] is False)
    same(integer(observations["read_pid"], 1, 2147483647), one(group_rows, "role", "read")["pid"])
    cleanup = obj(
        b["cleanup"],
        {"namespace_absent", "pre_drop_relation_locks", "proof", "owned_work_removal_authorized"},
    )
    need(cleanup["namespace_absent"] is True and cleanup["owned_work_removal_authorized"] is True)
    same(integer(cleanup["pre_drop_relation_locks"]), 0)
    same(cleanup["proof"], {"schema_version": 1, "namespace_absent": True, "receiver_id": receiver})
    return {case: {"status": "passed", "code": "ok"} for case in CASES}


def validate_bundle(bundle: object) -> dict[str, CaseResult]:
    """Return all eight passes only for a complete proof, with no input mutation."""
    try:
        return _validate(bundle)
    except PreparedReadEvidenceError:
        raise
    except Exception:  # noqa: BLE001 - finite proof boundary excludes private data/error text
        raise PreparedReadEvidenceError() from None
