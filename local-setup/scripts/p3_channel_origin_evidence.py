"""Independent literal owner-row oracle for the fourteen origin assertions.

Only the standard library is used. No SDK parser/producer, database, filesystem,
process, network or clock is consulted. The caller supplies complete owner SQL
snapshots and source-bound observations; no model/host statement grants authority.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, TypedDict, cast
from uuid import UUID

CASES = (
    "canonical_source_agreement",
    "original_work_and_p2_receipt_join",
    "equal_replay_zero_new_work",
    "changed_origin_conflict",
    "foreign_scope_route_publisher_denied",
    "mapped_width_revision_zero_denied",
    "stale_new_and_known_historical",
    "concurrent_first_winner_context",
    "owned_commit_before_ack_recovery",
    "original_deadline_evidence_after_clock_config",
    "unknown_lookup_no_resubmit",
    "held_actual_capacity_and_close_retry",
    "issued_verified_outer3_result",
    "current_result_native_read_and_stale_denial",
)
STAGES = (
    "after_race",
    "after_ack_commit",
    "after_ack_reconcile",
    "after_negative",
    "after_case_change_before_current",
    "final",
)
P2_TABLES = frozenset(
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
WORK_TABLES = frozenset(
    [
        "accepted_work",
        "admission",
        "attempt_results",
        "cancellation_commands",
        "execution_limits",
        "issued_attempts",
        "result_actions",
        "result_delivery_intents",
        "result_delivery_possible",
        "result_delivery_receipts",
        "result_feed_events",
        "result_feed_heads",
        "result_feed_source",
        "schema_metadata",
    ]
)
CASE_TABLES = frozenset(
    [
        "action_intents",
        "business_outcomes",
        "cancellation_commands",
        "cases",
        "completion_deliveries",
        "completion_events",
        "confirmations",
        "execution_attempts",
        "execution_controls",
        "execution_leases",
        "execution_limits",
        "execution_signal_consumptions",
        "execution_signals",
        "execution_waits",
        "executions",
        "intent_dispatch",
        "mutation_attempts",
        "mutation_effects",
        "quotes",
        "schema_metadata",
        "tasks",
    ]
)
NOTICE = "Your review result is ready. Rejoin this conversation to view it."
_LABELS = ("original", "ack", "current")
_BODIES = {
    "original": "Review the original booking policy.",
    "ack": "Review policy after asynchronous SMS.",
    "current": "Review the revised booking policy.",
}
_SCOPE = {"tenant_id", "account_id"}
_REF = {"source_id", "version", "sha256", "media_type", "byte_length", "width", "height"}
_INNER_REQUEST = {
    "schema_version",
    "kind",
    "capability",
    "input_schema_version",
    "scope",
    "delegation_id",
    "case_id",
    "request_revision",
    "context_snapshot",
    "evidence",
    "deadline_at_ms",
    "result_route",
    "attempt",
    "input_fingerprint",
}


class OriginEvidenceError(ValueError):
    def __init__(self) -> None:
        self.code = "invalid_proof"
        super().__init__(self.code)


class CaseResult(TypedDict):
    status: Literal["passed"]
    code: Literal["ok"]


def require(value: object) -> None:
    if value is not True:
        raise OriginEvidenceError()


def object_value(value: object, names: set[str] | None = None) -> dict[str, Any]:
    require(type(value) is dict)
    result = cast(dict[str, Any], value)
    require(all(type(key) is str for key in result))
    if names is not None:
        require(set(result) == names)
    return result


def rows(value: object, maximum: int = 64) -> list[dict[str, Any]]:
    require(type(value) is list and len(cast(list[object], value)) <= maximum)
    return [object_value(item) for item in cast(list[object], value)]


def text(value: object, maximum: int = 32768) -> str:
    require(type(value) is str)
    result = cast(str, value)
    require(len(result.encode("utf-8", "strict")) <= maximum)
    return result


def integer(value: object, minimum: int = 0, maximum: int = 4102444800000) -> int:
    require(type(value) is int)
    result = cast(int, value)
    require(minimum <= result <= maximum)
    return result


def uuid(value: object) -> str:
    raw = text(value, 36)
    parsed = UUID(raw)
    require(parsed.version == 4 and str(parsed) == raw)
    return raw


def digest(value: object) -> str:
    raw = text(value, 64)
    require(re.fullmatch(r"[0-9a-f]{64}", raw) is not None)
    return raw


def identifier(value: object) -> str:
    raw = text(value, 64)
    require(re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", raw) is not None)
    return raw


def packed(value: object, *, ascii_only: bool = False, sorted_keys: bool = True) -> str:
    return json.dumps(
        value,
        ensure_ascii=ascii_only,
        sort_keys=sorted_keys,
        separators=(",", ":"),
        allow_nan=False,
    )


def same(left: object, right: object) -> None:
    require(packed(left) == packed(right))


def sha(value: str | bytes) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        require(key not in result)
        result[key] = value
    return result


def decode(value: object, maximum: int = 32768) -> dict[str, Any]:
    raw = text(value, maximum)
    result: object = json.loads(
        raw,
        object_pairs_hook=_pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(OriginEvidenceError()),
    )
    return object_value(result)


def bytea(value: object, maximum: int) -> str:
    raw = text(value, maximum * 2 + 2)
    require(re.fullmatch(r"\\x(?:[0-9a-f]{2})+", raw) is not None)
    result = bytes.fromhex(raw[2:])
    require(0 < len(result) <= maximum)
    return result.decode("utf-8", "strict")


def one(values: list[dict[str, Any]], key: str, expected: object) -> dict[str, Any]:
    selected = [value for value in values if packed(value.get(key)) == packed(expected)]
    require(len(selected) == 1)
    return selected[0]


def millis(value: object) -> int:
    raw = text(value, 64)
    instant = datetime.fromisoformat(raw)
    require(instant.tzinfo is not None and instant.utcoffset() is not None)
    # JavaScript Date.parse and stored integer receipts discard sub-millisecond
    # precision. Integer arithmetic avoids rounding and float epoch precision loss.
    return (instant - datetime(1970, 1, 1, tzinfo=UTC)) // timedelta(milliseconds=1)


def _snapshot(
    value: object, schemas: tuple[str, str, str]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    result = object_value(value, set(schemas))
    selected = []
    for schema, expected, version in zip(
        schemas, (P2_TABLES, WORK_TABLES, CASE_TABLES), (8, 4, 4), strict=True
    ):
        supplied_tables = object_value(result[schema], set(expected))
        tables = {table: rows(supplied_tables[table]) for table in supplied_tables}
        metadata = tables["schema_metadata"]
        require(len(metadata) == 1)
        same(integer(metadata[0]["version"]), version)
        selected.append(tables)
    return selected[0], selected[1], selected[2]


def _catalogue(value: object, scope: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    catalogue = object_value(value, {"a", "b"})
    output = {}
    for label, days in (("a", 10), ("b", 14)):
        evidence = rows(catalogue[label], 2)
        require(len(evidence) == 2)
        for index, entry in enumerate(evidence):
            object_value(entry, {"scope", "reference", "body_utf8"})
            same(object_value(entry["scope"], _SCOPE), scope)
            reference = object_value(entry["reference"], _REF)
            same(reference["source_id"], "policy_notice" if index == 0 else "facts_notice")
            same(reference["version"], "distinct_" + label)
            same(reference["media_type"], "application/json")
            require(reference["width"] is reference["height"] is None)
            body = text(entry["body_utf8"], 4096)
            same(digest(reference["sha256"]), sha(body))
            same(integer(reference["byte_length"], 1, 4096), len(body.encode()))
            source = decode(body, 4096)
            same(body, packed(source))
            same(integer(source["schema_version"]), 1)
            text(source["note"], 2048)
            if index == 0:
                object_value(
                    source,
                    {
                        "schema_version",
                        "kind",
                        "policy_version",
                        "rule_id",
                        "minimum_notice_days",
                        "note",
                    },
                )
                same(source["kind"], "booking.notice_policy")
                same(source["policy_version"], "notice_v1")
                same(source["rule_id"], "notice_minimum_days")
                same(integer(source["minimum_notice_days"]), 7)
            else:
                object_value(source, {"schema_version", "kind", "observations", "note"})
                same(source["kind"], "booking.notice_facts")
                same(
                    source["observations"],
                    [{"fact_id": "notice_primary", "days_before_arrival": days}],
                )
        output[label] = evidence
    return output


def _source(
    channel: dict[str, Any], receipt: str, label: str, descriptor: dict[str, Any], revision: int
) -> tuple[dict[str, Any], str]:
    inbox = one(channel["inbox"], "receipt_id", uuid(receipt))
    process = one(channel["processing_intents"], "receipt_id", receipt)
    plan = one(channel["dispatch_plans"], "receipt_id", receipt)
    event = decode(inbox["wire_json"])
    require(
        set(event)
        <= {
            "schemaVersion",
            "type",
            "eventId",
            "providerScope",
            "accountScope",
            "caseId",
            "conversationId",
            "occurredAt",
            "receivedAt",
            "retryCount",
            "signature",
            "channel",
            "messageId",
            "senderId",
            "body",
            "expectedCaseRevision",
            "replyToResponseId",
            "causationId",
        }
    )
    same(integer(event["schemaVersion"]), 1)
    same(event["type"], "text.received")
    same(event["accountScope"], descriptor["scope"])
    same(event["caseId"], descriptor["case_id"])
    same(event["conversationId"], descriptor["conversation_id"])
    same(event["body"], _BODIES[label])
    same(inbox["wire_json"], packed(event, ascii_only=True))
    semantic = {
        key: value
        for key, value in event.items()
        if key not in {"receivedAt", "retryCount", "signature"}
    }
    same(inbox["canonical_payload"], packed(semantic, ascii_only=True))
    provider = object_value(event["providerScope"], {"tenantId", "provider", "providerAccountId"})
    same(provider["tenantId"], descriptor["scope"]["tenantId"])
    for key, value in (
        ("tenant_id", provider["tenantId"]),
        ("account_id", descriptor["scope"]["accountId"]),
        ("provider", provider["provider"]),
        ("provider_account_id", provider["providerAccountId"]),
        ("event_id", event["eventId"]),
        ("message_id", event["messageId"]),
        ("conversation_id", descriptor["conversation_id"]),
    ):
        same(inbox[key], value)
    integer(inbox["acceptance_sequence"], 1)
    same(millis(inbox["accepted_at"]), millis(event["receivedAt"]))
    if label == "ack":
        same(provider["provider"], "fake_sms")
        same(provider["providerAccountId"], "origin_fixture_sms")
        same(event["channel"], "sms")
        same(event["eventId"], "origin_sms_input")
        same(event["senderId"], "origin_sms_sender")
        association = one(channel["associations"], "sender_id", "origin_sms_sender")
        for key in (
            "tenant_id",
            "account_id",
            "provider",
            "provider_account_id",
            "conversation_id",
        ):
            same(association[key], inbox[key])
        same(association["case_id"], descriptor["case_id"])
        require(association["revoked_at"] is None)
        same(association["epoch"], inbox["association_epoch"])
        challenge = one(channel["challenges"], "sender_id", "origin_sms_sender")
        for key in (
            "tenant_id",
            "account_id",
            "provider",
            "provider_account_id",
            "conversation_id",
            "case_id",
            "sender_id",
        ):
            same(challenge[key], association[key])
        head = one(channel["sender_heads"], "sender_id", "origin_sms_sender")
        for key in ("tenant_id", "provider", "provider_account_id", "sender_id"):
            same(head[key], association[key])
        same(integer(head["active_epoch"], 1), integer(association["epoch"], 1))
        same(integer(head["epoch"], 1), head["active_epoch"])
        require(millis(association["activated_at"]) <= millis(inbox["accepted_at"]))
        require(challenge["consumed_at"] is not None)
        require(millis(challenge["consumed_at"]) <= millis(inbox["accepted_at"]))
    else:
        binding_id = uuid(descriptor["native_binding_ids"]["a" if label == "original" else "b"])
        binding = one(channel["native_bindings"], "binding_id", binding_id)
        same(provider["provider"], "livekit")
        same(provider["providerAccountId"], "origin_fixture_rtc")
        same(event["channel"], "web_chat")
        same(event["senderId"], binding_id)
        uuid(event["eventId"])
        same(event["messageId"], event["eventId"])
        require(binding["revoked_at"] is None)
        require(
            millis(binding["published_at"])
            <= millis(inbox["accepted_at"])
            < millis(binding["expires_at"])
        )
        raw_binding = text(binding["canonical_binding"])
        same(digest(binding["binding_digest"]), sha(raw_binding))
        bound = decode(raw_binding)
        object_value(
            bound,
            {
                "schemaVersion",
                "bindingId",
                "providerScope",
                "scope",
                "caseId",
                "conversationId",
                "roomId",
                "participantId",
                "expiresAt",
            },
        )
        same(integer(bound["schemaVersion"]), 1)
        digest(binding["bearer_digest"])
        same(binding["provider"], provider["provider"])
        same(binding["provider_account_id"], provider["providerAccountId"])
        same(bound["bindingId"], binding_id)
        same(bound["providerScope"], provider)
        same(bound["scope"], descriptor["scope"])
        same(bound["caseId"], descriptor["case_id"])
        same(bound["conversationId"], descriptor["conversation_id"])
        for key, value in (
            ("tenant_id", provider["tenantId"]),
            ("account_id", descriptor["scope"]["accountId"]),
            ("case_id", descriptor["case_id"]),
            ("conversation_id", descriptor["conversation_id"]),
            ("room_id", "origin_room_" + ("a" if label == "original" else "b")),
            ("participant_id", "origin_participant_" + ("a" if label == "original" else "b")),
        ):
            same(binding[key], value)
        same(bound["roomId"], binding["room_id"])
        same(bound["participantId"], binding["participant_id"])
        same(millis(bound["expiresAt"]), millis(binding["expires_at"]))
    operation = uuid(process["operation_key"])
    same(plan["operation_key"], operation)
    same(plan["association_epoch"], inbox["association_epoch"])
    submission = {
        "schemaVersion": 1,
        "kind": "investigation",
        "operationKey": operation,
        # P2 canonical wire order is fixed independently of the order in which
        # the enclosing evidence JSON publisher serialized descriptor objects.
        "scope": {
            "tenantId": descriptor["scope"]["tenantId"],
            "accountId": descriptor["scope"]["accountId"],
        },
        "caseId": descriptor["case_id"],
        "caseRevision": str(revision),
        "conversationId": descriptor["conversation_id"],
        "message": {
            "receiptId": receipt,
            "eventId": event["eventId"],
            "messageId": event["messageId"],
            "senderId": event["senderId"],
            "body": event["body"],
        },
    }
    raw = packed(submission, sorted_keys=False)
    require(len(raw.encode()) <= 32768)
    same(plan["payload_json"], raw)
    same(digest(plan["payload_digest"]), sha(raw))
    return submission, raw


def _request(
    row: dict[str, Any],
    source: dict[str, Any],
    raw: str,
    descriptor: dict[str, Any],
    catalogue: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any], str]:
    request_raw = bytea(row["body"], 16384)
    request = decode(request_raw, 16384)
    object_value(
        request,
        {
            "schema_version",
            "kind",
            "capability",
            "input_schema_version",
            "origin",
            "request",
            "input_fingerprint",
        },
    )
    same(integer(request["schema_version"]), 1)
    same(request["kind"], "delegation.request")
    same(request["capability"], "booking.evaluate_policy")
    same(integer(request["input_schema_version"]), 3)
    same(request_raw, packed(request))
    same(digest(row["sha256"]), sha(request_raw))
    origin = object_value(
        request["origin"],
        {
            "kind",
            "profile_id",
            "operation_key",
            "input_receipt_id",
            "payload_sha256",
            "payload_byte_length",
        },
    )
    same(
        origin,
        {
            "kind": "p2.prepared_dispatch.v1",
            "profile_id": descriptor["receiver_id"],
            "operation_key": source["operationKey"],
            "input_receipt_id": source["message"]["receiptId"],
            "payload_sha256": sha(raw),
            "payload_byte_length": len(raw.encode()),
        },
    )
    integer(origin["payload_byte_length"], 1, 32768)
    nested = object_value(request["request"], _INNER_REQUEST)
    scope = {
        "tenant_id": descriptor["scope"]["tenantId"],
        "account_id": descriptor["scope"]["accountId"],
    }
    same(object_value(nested["scope"], _SCOPE), scope)
    for key in _SCOPE:
        same(row[key], scope[key])
    for key, header_value in (("schema_version", 1), ("input_schema_version", 2)):
        same(integer(nested[key]), header_value)
    for key, expected in (
        ("kind", "delegation.request"),
        ("capability", "booking.evaluate_policy"),
        ("case_id", descriptor["case_id"]),
        ("result_route", {"conversation_id": descriptor["conversation_id"]}),
        (
            "context_snapshot",
            {
                "policy_version": "notice_v1",
                "policy_source_id": "policy_notice",
                "facts_source_id": "facts_notice",
            },
        ),
        ("attempt", {"attempt_id": "origin_proposal", "number": 1}),
    ):
        same(nested[key], expected)
    same(integer(nested["request_revision"], 1, 1000000), int(source["caseRevision"]))
    key = "p2_" + UUID(source["operationKey"]).hex
    same(nested["delegation_id"], key)
    same(row["idempotency_key"], key)
    same(row["operation"], "booking.evaluate_policy")
    same(integer(nested["deadline_at_ms"]), row["deadline_at_ms"])
    require(integer(row["accepted_at_ms"]) < row["deadline_at_ms"])
    inner_logical = {
        key: value for key, value in nested.items() if key not in {"attempt", "input_fingerprint"}
    }
    same(digest(nested["input_fingerprint"]), sha(packed(inner_logical)))
    outer_logical = {key: value for key, value in request.items() if key != "input_fingerprint"}
    outer_logical["request"] = inner_logical
    same(digest(request["input_fingerprint"]), sha(packed(outer_logical)))
    matches = [
        label
        for label, records in catalogue.items()
        if packed(nested["evidence"]) == packed([entry["reference"] for entry in records])
    ]
    require(len(matches) == 1)
    return request, matches[0]


def _graph(value: object, descriptor: dict[str, Any], table: str, count: int) -> dict[str, Any]:
    graph = object_value(value)
    same(graph["schema"], descriptor["work_schema"])
    same(graph["table"], table)
    same(graph["association"], "unique_disposable_work_schema")
    require(graph["row_lock"] is (table == "admission"))
    holder = integer(graph["holder_pid"], 1, 2147483647)
    same(integer(graph["expected_waiters"]), count)
    waiters = rows(graph["waiters"], 4)
    require(
        len(waiters) == count and len({integer(v["pid"], 1, 2147483647) for v in waiters}) == count
    )
    target = re.escape(descriptor["work_schema"]) + r'"?\."?' + table
    holder_query = text(graph["holder_query"], 16384)
    same(digest(graph["holder_query_sha256"]), sha(holder_query))
    require(re.search(target, holder_query) is not None)
    require(
        ("FOR UPDATE" in holder_query.upper())
        if table == "admission"
        else ("ACCESS EXCLUSIVE" in holder_query.upper())
    )

    def relation_locks(
        value: object, mode: str, granted: bool, target_oid: int | None = None
    ) -> int:
        locks = rows(value, 8)
        require(bool(locks))
        identities: set[tuple[str, bool]] = set()
        oids: set[int] = set()
        for lock in locks:
            object_value(lock, {"relation_oid", "schema", "table", "locktype", "mode", "granted"})
            same(lock["schema"], descriptor["work_schema"])
            same(lock["table"], table)
            same(lock["locktype"], "relation")
            require(type(lock["granted"]) is bool)
            lock_mode = text(lock["mode"], 32)
            require(
                lock_mode
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
            identity = (lock_mode, lock["granted"])
            require(identity not in identities)
            identities.add(identity)
            oids.add(integer(lock["relation_oid"], 1, 4294967295))
        require(len(oids) == 1 and (mode, granted) in identities)
        oid = next(iter(oids))
        if target_oid is not None:
            same(oid, target_oid)
        return oid

    target_oid = relation_locks(
        graph["holder_locks"],
        "RowShareLock" if table == "admission" else "AccessExclusiveLock",
        True,
    )
    require(all(lock["granted"] is True for lock in graph["holder_locks"]))
    waiter_pids = {integer(waiter["pid"], 1, 2147483647) for waiter in waiters}
    require(holder not in waiter_pids)
    edges: dict[int, tuple[int, ...]] = {}
    for waiter in waiters:
        pid = integer(waiter["pid"], 1, 2147483647)
        blockers = waiter["blockers"]
        require(type(blockers) is list and 1 <= len(blockers) <= count)
        targets = tuple(integer(blocker, 1, 2147483647) for blocker in blockers)
        require(len(set(targets)) == len(targets))
        require(all(target != pid and target in waiter_pids | {holder} for target in targets))
        edges[pid] = targets
        same(waiter["wait_event_type"], "Lock")
        query = text(waiter["query"], 16384)
        same(digest(waiter["query_sha256"]), sha(query))
        # Public WorkStore.find can be blocked in its schema-validation SELECT
        # before its final table SELECT. The actual relation lock, not a literal
        # SQL parameter value or final-query claim, binds the disposable table.
        require(query.lstrip().upper().startswith("SELECT"))
        relation_locks(
            waiter["relation_locks"],
            "RowShareLock" if table == "admission" else "AccessShareLock",
            table == "admission",
            target_oid,
        )
    # PostgreSQL row-lock queueing can report another admitted waiter as the
    # immediate blocker. Every supplied edge must still reach this exact owned
    # holder through the complete finite namespaced graph; no foreign edge or
    # cycle is accepted merely because one alternative path reaches the holder.
    visiting: set[int] = set()
    settled: set[int] = {holder}

    def reaches_holder(pid: int) -> None:
        require(pid not in visiting)
        if pid in settled:
            return
        visiting.add(pid)
        for blocker in edges[pid]:
            reaches_holder(blocker)
        visiting.remove(pid)
        settled.add(pid)

    for pid in waiter_pids:
        reaches_holder(pid)
    return graph


def _execution(
    work: dict[str, Any],
    accepted: dict[str, Any],
    request: dict[str, Any],
    entry: list[dict[str, Any]],
    proof: dict[str, Any],
) -> dict[str, Any]:
    work_id = accepted["work_id"]
    issued = one(work["issued_attempts"], "work_id", work_id)
    recorded = one(work["attempt_results"], "work_id", work_id)
    uuid(issued["attempt_id"])
    uuid(issued["owner_id"])
    same(integer(issued["number"], 1, 3), 1)
    same(integer(issued["epoch"], 1, 3), 1)
    require(integer(issued["issued_at_ms"]) < integer(issued["lease_until_ms"]))
    for value in (issued, recorded):
        same(value["work_id"], work_id)
        same(value["attempt_id"], issued["attempt_id"])
        for key in _SCOPE:
            same(value[key], accepted[key])
    raw = bytea(recorded["body"], 8192)
    result = decode(raw, 8192)
    object_value(
        result,
        {
            "schema_version",
            "kind",
            "capability",
            "result_schema_version",
            "input_fingerprint",
            "result",
        },
    )
    same(raw, packed(result))
    same(integer(result["schema_version"]), 1)
    same(integer(result["result_schema_version"]), 3)
    same(result["kind"], "delegation.result")
    same(result["capability"], "booking.evaluate_policy")
    same(result["input_fingerprint"], request["input_fingerprint"])
    same(digest(recorded["sha256"]), sha(raw))
    same(recorded["disposition"], "eligible_at_commit")
    inner = object_value(
        result["result"],
        {
            "schema_version",
            "kind",
            "capability",
            "result_schema_version",
            "scope",
            "delegation_id",
            "case_id",
            "request_revision",
            "attempt_id",
            "input_fingerprint",
            "eligible",
            "uncertainty",
            "rule_refs",
            "fact_refs",
            "producer",
            "completed_at_ms",
        },
    )
    same(integer(inner["schema_version"]), 1)
    same(integer(inner["result_schema_version"]), 2)
    same(inner["kind"], "delegation.result")
    same(inner["capability"], "booking.evaluate_policy")
    for key in ("scope", "delegation_id", "case_id", "request_revision", "input_fingerprint"):
        same(inner[key], request["request"][key])
    same(inner["attempt_id"], "attempt_" + UUID(issued["attempt_id"]).hex)
    require(inner["eligible"] is True)
    same(inner["uncertainty"], "none")
    days = decode(entry[1]["body_utf8"])["observations"][0]["days_before_arrival"]
    rule = {key: entry[0]["reference"][key] for key in ("source_id", "version", "sha256")}
    fact = {key: entry[1]["reference"][key] for key in ("source_id", "version", "sha256")}
    same(inner["rule_refs"], [{**rule, "rule_id": "notice_minimum_days", "minimum_notice_days": 7}])
    same(inner["fact_refs"], [{**fact, "fact_id": "notice_primary", "days_before_arrival": days}])
    require(type(days) is int and days >= 7)
    same(
        inner["producer"],
        {
            "producer_id": "deterministic_notice_v1",
            "model_id": None,
            "model_version": None,
            "config_fingerprint": sha(b"origin_supplied_scripted_v1"),
        },
    )
    require(
        issued["issued_at_ms"]
        <= integer(inner["completed_at_ms"])
        <= integer(recorded["recorded_at_ms"])
        <= min(accepted["deadline_at_ms"], issued["lease_until_ms"])
    )
    same(proof["work_id"], work_id)
    same(proof["result_canonical"], raw)
    same(proof["result_sha256"], recorded["sha256"])
    same(proof["recorded_at_ms"], recorded["recorded_at_ms"])
    same(proof["disposition"], "eligible_at_commit")
    same(proof["applicability"], "candidate")
    same(
        proof["issued"],
        {
            key: issued[key]
            for key in (
                "attempt_id",
                "command_id",
                "number",
                "owner_id",
                "epoch",
                "issued_at_ms",
                "lease_until_ms",
            )
        },
    )
    feed = one(work["result_feed_events"], "work_id", work_id)
    same(feed["attempt_id"], issued["attempt_id"])
    for key in _SCOPE:
        same(feed[key], accepted[key])
    return result


def _delivery(
    channel: dict[str, Any],
    work: dict[str, Any],
    request: dict[str, Any],
    result: dict[str, Any],
    descriptor: dict[str, Any],
    files: dict[str, Any],
    proof: dict[str, Any],
) -> None:
    same(proof["state"], "accepted")
    require(proof["receiver_invoked"] is True and proof["human_acknowledgement"] is False)
    intent = object_value(
        proof["intent"],
        {
            "attempt_id",
            "body",
            "delivery_id",
            "prepared_at_ms",
            "receiver_id",
            "recipient_id",
            "result_sha256",
            "scope",
            "work_id",
        },
    )
    receipt = object_value(
        proof["receipt"],
        {
            "delivery_id",
            "receipt_id",
            "receiver_id",
            "recipient_id",
            "result_sha256",
            "accepted_at_ms",
        },
    )
    record = one(work["attempt_results"], "work_id", intent["work_id"])
    same(intent["attempt_id"], record["attempt_id"])
    same(intent["result_sha256"], record["sha256"])
    require(base64.b64decode(text(intent["body"], 12000), validate=True) == packed(result).encode())
    same(intent["scope"], request["request"]["scope"])
    same(intent["receiver_id"], descriptor["receiver_id"])
    same(intent["recipient_id"], descriptor["recipient_id"])
    uuid(intent["delivery_id"])
    uuid(receipt["receipt_id"])
    for key in ("delivery_id", "receiver_id", "recipient_id", "result_sha256"):
        same(receipt[key], intent[key])
    require(integer(intent["prepared_at_ms"]) <= integer(receipt["accepted_at_ms"]))
    stored = one(work["result_delivery_intents"], "delivery_id", intent["delivery_id"])
    for key in (
        "work_id",
        "attempt_id",
        "result_sha256",
        "receiver_id",
        "recipient_id",
        "prepared_at_ms",
    ):
        same(stored[key], intent[key])
    for key in _SCOPE:
        same(stored[key], intent["scope"][key])
    possible = one(work["result_delivery_possible"], "delivery_id", intent["delivery_id"])
    require(
        intent["prepared_at_ms"] <= integer(possible["marked_at_ms"]) <= receipt["accepted_at_ms"]
    )
    stored_receipt = one(work["result_delivery_receipts"], "delivery_id", intent["delivery_id"])
    for key, value in receipt.items():
        same(stored_receipt[key], value)
    require(integer(stored_receipt["recorded_at_ms"]) >= receipt["accepted_at_ms"])
    metadata = one(channel["result_receipts"], "delivery_id", intent["delivery_id"])
    same(metadata["canonical_intent"], packed(intent, ascii_only=True))
    for key in ("work_id", "attempt_id", "recipient_id", "result_sha256"):
        same(metadata[key], intent[key])
    for key in _SCOPE:
        same(metadata[key], intent["scope"][key])
    same(metadata["outbound_id"], intent["delivery_id"])
    same(metadata["case_id"], descriptor["case_id"])
    same(metadata["conversation_id"], descriptor["conversation_id"])
    reply = one(channel["reply_intents"], "outbound_id", intent["delivery_id"])
    payload = decode(reply["canonical_payload"])
    object_value(
        payload,
        {"schemaVersion", "outboundId", "responseId", "body", "scope", "caseId", "conversationId"},
    )
    same(
        payload,
        {
            "schemaVersion": 1,
            "outboundId": intent["delivery_id"],
            "responseId": "p3_" + UUID(intent["work_id"]).hex,
            "body": NOTICE,
            "scope": descriptor["scope"],
            "caseId": descriptor["case_id"],
            "conversationId": descriptor["conversation_id"],
        },
    )
    same(reply["intent_digest"], sha(reply["canonical_payload"]))
    same(reply["body_digest"], sha(NOTICE))
    require(reply["body_digest"] != intent["result_sha256"])
    same(reply["receipt_id"], receipt["receipt_id"])
    same(millis(reply["accepted_at"]), receipt["accepted_at_ms"])
    for key, value in (
        ("tenant_id", intent["scope"]["tenant_id"]),
        ("account_id", intent["scope"]["account_id"]),
        ("case_id", descriptor["case_id"]),
        ("conversation_id", descriptor["conversation_id"]),
        ("response_id", payload["responseId"]),
    ):
        same(reply[key], value)
    native = object_value(files["origin-native-read.json"])
    same(integer(native["schema_version"]), 1)
    same(integer(native["rtc_rooms"]), 0)
    require(native["provider_calls"] is False)
    view = object_value(native["view"], {"schemaVersion", "intent", "receipt", "case", "observed"})
    same(integer(view["schemaVersion"]), 1)
    same(view["intent"], intent)
    same(view["receipt"], receipt)
    case = object_value(view["case"])
    same(integer(case["schemaVersion"]), 1)
    same(case["source"], "p1_public_v4")
    same(case["revision"], "2")
    same(case["scope"], descriptor["scope"])
    same(case["caseId"], descriptor["case_id"])
    same(case["conversationId"], descriptor["conversation_id"])
    same(case["workflow"], {"taskId": descriptor["task_id"], "state": "ready", "version": "0"})
    same(
        case["request"],
        {
            "schemaVersion": 1,
            "kind": "booking_investigation",
            "bookingReference": "DEMO-BK-001",
            "newCheckIn": "2030-12-12",
            "investigationConsent": True,
        },
    )
    same(case["intent"], {"state": "not_committed", "intentId": None})
    require(case["supplierResult"] is None)
    digest(case["sourceRevision"])
    seen = object_value(
        view["observed"], {"p2ObservedAt", "caseObservedAt", "disclosureAdmittedAt", "atomic"}
    )
    require(seen["atomic"] is False)
    for key in ("p2ObservedAt", "caseObservedAt", "disclosureAdmittedAt"):
        millis(seen[key])
    native_input = object_value(native["input"])
    same(native_input["bindingId"], descriptor["native_binding_ids"]["b"])
    same(native_input["receiptId"], request["origin"]["input_receipt_id"])
    same(native_input["operationKey"], request["origin"]["operation_key"])
    source_row = one(channel["inbox"], "receipt_id", native_input["receiptId"])
    source_event = decode(source_row["wire_json"])
    same(integer(native_input["schemaVersion"]), 1)
    same(native_input["channel"], "web_chat")
    same(native_input["inputId"], source_event["eventId"])
    same(native_input["acceptanceSequence"], str(integer(source_row["acceptance_sequence"], 1)))
    binding = one(channel["native_bindings"], "binding_id", native_input["bindingId"])
    require(
        millis(binding["published_at"])
        <= millis(seen["disclosureAdmittedAt"])
        < millis(binding["expires_at"])
    )
    for name in ("origin-current-delivered.json",):
        same(files[name]["receipt"], receipt)
        same(files[name]["delivery_id"], intent["delivery_id"])
        same(files[name]["work_id"], intent["work_id"])


def _validate(bundle: object) -> dict[str, CaseResult]:
    data = object_value(
        bundle, {"schema_version", "descriptor", "snapshots", "observations", "files", "catalogue"}
    )
    same(integer(data["schema_version"]), 1)
    require(len(packed(data).encode()) <= 2097152)
    descriptor = object_value(
        data["descriptor"],
        {
            "schema_version",
            "scope",
            "case_id",
            "conversation_id",
            "recipient_id",
            "p2_schema",
            "work_schema",
            "case_schema",
            "case_endpoint",
            "native_binding_ids",
            "parent_expires_at_ms",
            "receiver_id",
            "task_id",
            "authority_case_id",
            "inputs",
        },
    )
    same(integer(descriptor["schema_version"]), 1)
    camel = object_value(descriptor["scope"], {"tenantId", "accountId"})
    scope = {
        "tenant_id": identifier(camel["tenantId"]),
        "account_id": identifier(camel["accountId"]),
    }
    identifier(descriptor["case_id"])
    identifier(descriptor["conversation_id"])
    identifier(descriptor["recipient_id"])
    for key in ("receiver_id", "task_id", "authority_case_id"):
        uuid(descriptor[key])
    schemas = tuple(
        text(descriptor[key], 64) for key in ("p2_schema", "work_schema", "case_schema")
    )
    for schema, prefix in zip(
        schemas, ("p2_origin_", "p1_work_origin_", "p3_completion_"), strict=True
    ):
        require(re.fullmatch(prefix + r"[0-9a-f]{32}", schema) is not None)
    require(len(set(schemas)) == 3)
    endpoint = object_value(descriptor["case_endpoint"], {"host", "port"})
    same(endpoint["host"], "127.0.0.1")
    integer(endpoint["port"], 1, 65535)
    native_bindings = object_value(descriptor["native_binding_ids"], {"a", "b"})
    require(uuid(native_bindings["a"]) != uuid(native_bindings["b"]))
    integer(descriptor["parent_expires_at_ms"], 1)
    catalogue = _catalogue(data["catalogue"], scope)
    snapshots = object_value(data["snapshots"], set(STAGES))
    stages = [_snapshot(snapshots[name], (schemas[0], schemas[1], schemas[2])) for name in STAGES]
    channel, work, _cases = stages[-1]
    files, observed = object_value(data["files"]), object_value(data["observations"])
    require(0 < len(files) <= 128)
    require(
        all(
            type(name) is str and name.endswith(".json") and not name.endswith("-config.json")
            for name in files
        )
    )
    for value in files.values():
        object_value(value)
    inputs = object_value(descriptor["inputs"], {"original", "ack"})
    original = object_value(inputs["original"], {"receiptId", "operationKey"})
    ack = object_value(inputs["ack"], {"receiptId", "operationKey"})
    current_marker = object_value(files["origin-current-accepted.json"])
    receipt_ids = {
        "original": uuid(original["receiptId"]),
        "ack": uuid(ack["receiptId"]),
        "current": uuid(current_marker["input_receipt_id"]),
    }
    require(len(set(receipt_ids.values())) == 3)
    require(
        len(channel["inbox"])
        == len(channel["processing_intents"])
        == len(channel["dispatch_plans"])
        == 3
    )
    require(
        len(channel["native_bindings"]) == 2
        and len(channel["associations"]) == len(channel["challenges"]) == 1
    )
    require(len(work["accepted_work"]) == 3)
    requests: dict[str, dict[str, Any]] = {}
    accepted_rows: dict[str, dict[str, Any]] = {}
    labels = {}
    for label in _LABELS:
        submission, raw = _source(
            channel, receipt_ids[label], label, descriptor, 2 if label == "current" else 1
        )
        if label != "current":
            same(submission["operationKey"], inputs[label]["operationKey"])
        row = one(
            work["accepted_work"], "idempotency_key", "p2_" + UUID(submission["operationKey"]).hex
        )
        uuid(row["work_id"])
        request, label_used = _request(row, submission, raw, descriptor, catalogue)
        requests[label], accepted_rows[label], labels[label] = request, row, label_used
        source_proof = object_value(
            files["origin-" + label + "-prepared.json"],
            {"submission", "canonicalPayload", "payloadDigest"},
        )
        same(
            source_proof,
            {"submission": submission, "canonicalPayload": raw, "payloadDigest": sha(raw)},
        )
        process = one(channel["processing_intents"], "receipt_id", receipt_ids[label])
        same(process["external_receipt_id"], row["work_id"])
        same(process["state"], "dispatched")
        require(process["possible_external"] is True)
    require(len({request["origin"]["operation_key"] for request in requests.values()}) == 3)
    source_rows = [one(channel["inbox"], "receipt_id", receipt_ids[label]) for label in _LABELS]
    same([integer(row["acceptance_sequence"], 1) for row in source_rows], [1, 2, 3])
    require(
        millis(source_rows[0]["accepted_at"])
        <= millis(source_rows[1]["accepted_at"])
        <= millis(source_rows[2]["accepted_at"])
    )
    same(labels["current"], "b")
    same(labels["ack"], "a")
    for index, (p2, p1, case) in enumerate(stages):
        expected_labels = (
            ("original",) if index == 0 else _LABELS if index == 5 else ("original", "ack")
        )
        same(len(p1["accepted_work"]), len(expected_labels))
        for label in expected_labels:
            same(
                one(p1["accepted_work"], "work_id", accepted_rows[label]["work_id"]),
                accepted_rows[label],
            )
        for table in ("result_actions", "cancellation_commands"):
            same(p1[table], [])
        for table in (
            "action_intents",
            "business_outcomes",
            "cancellation_commands",
            "confirmations",
            "intent_dispatch",
            "mutation_attempts",
            "mutation_effects",
            "quotes",
        ):
            same(case[table], [])
        for table in (
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
            same(p2[table], [])
        require(len(case["cases"]) == len(case["tasks"]) == 1)
        case_row = case["cases"][0]
        for key, value in (
            ("task_id", descriptor["task_id"]),
            ("case_id", descriptor["authority_case_id"]),
            ("actor_id", "p3_completion_user"),
            ("scope_id", "p3_completion_scope"),
        ):
            same(case_row[key], value)
        require(case_row["cancelled"] is False)
        same(integer(case_row["revision"]), 2 if index >= 4 else 1)
        request_case = decode(case_row["request_json"])
        same(
            request_case,
            {
                "booking_reference": "DEMO-BK-001",
                "new_check_in": "2030-12-12" if index >= 4 else "2030-12-11",
                "confirmed": True,
            },
        )
        same(case["tasks"][0]["task_id"], descriptor["task_id"])
        same(case["tasks"][0]["scope_id"], "p3_completion_scope")
        same(p2["outbox_settings"][0]["receiver_id"], descriptor["receiver_id"])
        expected_plans = 1 if index == 0 else 3 if index == 5 else 2
        same(len(p2["inbox"]), 3 if index == 5 else 2)
        same(len(p2["processing_intents"]), len(p2["inbox"]))
        same(len(p2["dispatch_plans"]), expected_plans)
        if index == 0:
            pending_ack = one(p2["processing_intents"], "receipt_id", receipt_ids["ack"])
            same(pending_ack["state"], "pending")
            require(
                pending_ack["possible_external"] is False
                and pending_ack["external_receipt_id"] is None
            )
        for label in expected_labels:
            if label == "ack" and index == 1:
                process = one(p2["processing_intents"], "receipt_id", receipt_ids[label])
                same(process["state"], "uncertain")
                require(
                    process["possible_external"] is True and process["external_receipt_id"] is None
                )
            else:
                process = one(p2["processing_intents"], "receipt_id", receipt_ids[label])
                same(process["external_receipt_id"], accepted_rows[label]["work_id"])
        if index < 5:
            for table in (
                "result_delivery_intents",
                "result_delivery_possible",
                "result_delivery_receipts",
            ):
                same(p1[table], [])
            same(p2["result_receipts"], [])
            same(p2["reply_intents"], [])
        expected_results = 2 if index == 5 else 1 if index == 4 else 0
        for table in ("issued_attempts", "attempt_results", "result_feed_events"):
            same(len(p1[table]), expected_results)
    # Original source wires/plans and accepted bytes cannot be refreshed by replays.
    for index, (p2, _, _) in enumerate(stages):
        for label in ("original", "ack"):
            for table in ("inbox", "dispatch_plans"):
                if label == "ack" and index == 0 and table == "dispatch_plans":
                    continue
                same(
                    one(p2[table], "receipt_id", receipt_ids[label]),
                    one(channel[table], "receipt_id", receipt_ids[label]),
                )
    race_receipt = files["origin-race.json"]["receipt"]
    for label, filename in (
        ("original", "origin-race.json"),
        ("ack", "origin-reconcile.json"),
        ("current", "origin-current-accepted.json"),
    ):
        result_receipt = files[filename]["receipt"]
        same(
            result_receipt,
            {
                "operationKey": requests[label]["origin"]["operation_key"],
                "scope": camel,
                "payloadDigest": requests[label]["origin"]["payload_sha256"],
                "receiptId": accepted_rows[label]["work_id"],
            },
        )
    same(files["origin-race.json"]["operation_accept_calls"], 1)
    same(files["origin-race-callers.json"]["receipts"], [race_receipt, race_receipt])
    ready_pids = {}
    for role in (
        "origin-race-a",
        "origin-race-b",
        "origin-ack",
        "origin-recovered",
        "origin-current",
    ):
        ready = object_value(files[role + "-ready.json"], {"schema_version", "pid", "host", "port"})
        same(integer(ready["schema_version"]), 1)
        same(ready["host"], "127.0.0.1")
        integer(ready["port"], 1, 65535)
        ready_pids[role] = integer(ready["pid"], 1, 2147483647)
        if role != "origin-ack":
            closed = object_value(files[role + "-closed.json"])
            require(closed["cleanup_complete"] is True)
            same(closed["pid"], ready["pid"])
            same(closed["retained_owners"], [0, 0, 0])
            for name in (
                "http_handlers",
                "http_calls",
                "http_sockets",
                "service_pending",
                "coordinator_pending",
                "work_pending",
                "case_pending",
                "startup_pending",
            ):
                same(integer(closed[name]), 0)
    require(len(set(ready_pids.values())) == 5)
    for role, ordinal in (("origin-race-a", 2), ("origin-race-b", 1)):
        miss = observed[role + "_miss"]
        same(
            miss,
            {
                "schema_version": 1,
                "pid": ready_pids[role],
                "key": requests["original"]["request"]["delegation_id"],
                "ordinal": ordinal,
                "found": False,
            },
        )
        same(files[role + "-read-miss.json"], miss)
        same(files[role + "-submit-entered.json"]["pid"], ready_pids[role])
        same(
            files[role + "-submit-entered.json"]["key"],
            requests["original"]["request"]["delegation_id"],
        )
    race_graph = _graph(observed["race_wait_graph"], descriptor, "admission", 2)
    held = _graph(observed["held_wait_graph"], descriptor, "accepted_work", 4)
    held_close = _graph(observed["held_wait_graph_at_close"], descriptor, "accepted_work", 4)
    require(
        race_graph["holder_locks"][0]["relation_oid"] != held["holder_locks"][0]["relation_oid"]
    )
    same(held["holder_pid"], held_close["holder_pid"])
    same(
        {str(x["pid"]): x for x in held["waiters"]},
        {str(x["pid"]): x for x in held_close["waiters"]},
    )
    incomplete = observed["close_incomplete"]
    require(incomplete["cleanup_complete"] is False)
    same(incomplete["pid"], ready_pids["origin-recovered"])
    same(integer(incomplete["work_pending"]), 4)
    same(integer(incomplete["coordinator_pending"]), 4)
    held_callers = files["origin-held-lookups.json"]
    same(held_callers["outcomes"], ["Unavailable"] * 4)
    same(held_callers["overload"], ["Overloaded"] * 2)
    same(held_callers["before"], [{"active": 2, "closing": False}] * 2)
    same(held_callers["after"], [{"active": 0, "closing": True}] * 2)
    require(
        held_callers["caller_sockets_settled"] is True and held_callers["p1_drain_claimed"] is False
    )
    committed = observed["ack_committed"]
    same(
        committed,
        {
            "schema_version": 1,
            "pid": ready_pids["origin-ack"],
            "work_id": accepted_rows["ack"]["work_id"],
            "key": accepted_rows["ack"]["idempotency_key"],
            "payload_sha256": accepted_rows["ack"]["sha256"],
            "deadline_at_ms": accepted_rows["ack"]["deadline_at_ms"],
        },
    )
    same(files["origin-ack-committed.json"], committed)
    clock = object_value(
        observed["clock_after_ack_deadline"],
        {"schema_version", "db_now_ms", "ack_deadline_at_ms", "lookup"},
    )
    same(integer(clock["schema_version"]), 1)
    same(integer(clock["ack_deadline_at_ms"]), accepted_rows["ack"]["deadline_at_ms"])
    require(integer(clock["db_now_ms"]) > clock["ack_deadline_at_ms"])
    same(
        clock["lookup"],
        {
            "http_status": 200,
            "body": {
                "schemaVersion": 1,
                "status": "known",
                "observation": {
                    "status": "accepted",
                    "receipt": files["origin-reconcile.json"]["receipt"],
                },
            },
        },
    )
    kill = observed["scheduled_kill"]
    same(
        kill,
        {
            "schema_version": 1,
            "role": "origin-ack",
            "pid": ready_pids["origin-ack"],
            "returncode": -9,
            "group_settled": True,
        },
    )
    caller = files["origin-ack-caller.json"]
    same(caller["external_code"], "OutcomeUnknown")
    same(caller["dispatch_code"], "DispatchUnavailable")
    same(integer(caller["accept_calls"]), 1)
    require(caller["dispatch"]["possibleExternal"] is True)
    same(caller["dispatch"]["state"], "uncertain")
    same(integer(files["origin-reconcile.json"]["accept_calls"]), 0)
    same(
        files["origin-negative-controls.json"]["codes"],
        {
            "changed_origin": "OutcomeUnknown",
            "changed_lookup": "Unavailable",
            "wrong_profile": "Unavailable",
            "wrong_bearer": "Unavailable",
        },
    )
    for name, status, code in (
        ("foreign_scope", 403, "unauthorized"),
        ("foreign_case", 403, "unauthorized"),
        ("foreign_conversation", 403, "unauthorized"),
        ("width65", 400, "invalid_input"),
        ("revision_zero", 400, "invalid_input"),
        ("revision_width", 400, "invalid_input"),
    ):
        same(
            observed["raw_negative"][name],
            {"http_status": status, "body": {"schemaVersion": 1, "status": "error", "code": code}},
        )
    same(
        observed["stale_new"],
        {
            "http_status": 503,
            "body": {"schemaVersion": 1, "status": "error", "code": "case_changed"},
        },
    )
    same(
        observed["known_historical"],
        {
            "http_status": 200,
            "body": {"schemaVersion": 1, "status": "known", "receipt": race_receipt},
        },
    )
    consumer = files["origin-p3-consumer.json"]
    same(integer(consumer["schema_version"]), 1)
    same(consumer["status"], "passed")
    same(consumer["code"], "ok")
    same(consumer["stage"], "complete")
    ownership = object_value(
        consumer["ownership"],
        {
            "startup_tasks",
            "startup_pending",
            "retained_tiers",
            "close_observers_pending",
            "cleanup_complete",
        },
    )
    integer(ownership["startup_tasks"], 1, 32)
    same(integer(ownership["startup_pending"]), 0)
    same(integer(ownership["close_observers_pending"]), 0)
    same(ownership["retained_tiers"], [0, 0, 0])
    require(ownership["cleanup_complete"] is True)
    require(consumer["cleanup_complete"] is True and consumer["provider_calls"] is False)
    same(consumer["specialist"], "supplied_scripted_fixed_policy_v2")
    same(integer(consumer["actual_invoke_count"]), 2)
    same(integer(consumer["source_actual_assertions"]), 0)
    same(integer(consumer["supplier_mutations"]), 0)
    same(integer(consumer["carrier_sends"]), 0)
    proof = object_value(consumer["proof"])
    same(integer(proof["case_revision"]), 2)
    same(
        proof["real_read_only_controls"],
        {
            "changed_profile_accept": "identity_conflict",
            "changed_context_exact_submit": "identity_conflict",
            "key": accepted_rows["original"]["idempotency_key"],
            "separate_work_client": True,
            "specialist_invoked": False,
        },
    )
    for index, reconciliation in enumerate(("missing", "unavailable")):
        same(
            proof["simulations"][index],
            {
                "kind": "simulated_public_task_port",
                "reconciliation": reconciliation,
                "error": "acknowledgement_unknown",
                "finds": 2,
                "submits": 1,
                "keys": [accepted_rows["original"]["idempotency_key"]] * 3,
                "actual_database_fault": False,
                "closed": True,
            },
        )
    require(len(proof["simulations"]) == 2)
    for label in _LABELS:
        value = proof[label]
        row, request = accepted_rows[label], requests[label]
        for key, expected in (
            ("work_id", row["work_id"]),
            ("request_canonical", bytea(row["body"], 16384)),
            ("request_sha256", row["sha256"]),
            ("input_fingerprint", request["input_fingerprint"]),
            ("inner_input_fingerprint", request["request"]["input_fingerprint"]),
            ("deadline_at_ms", row["deadline_at_ms"]),
            ("origin", request["origin"]),
        ):
            same(value[key], expected)
        if label != "ack":
            same(value["catalogue_label"], labels[label])
    require(proof["ack"]["execution_requested"] is False and proof["ack"]["read_only"] is True)
    original_result = _execution(
        work,
        accepted_rows["original"],
        requests["original"],
        catalogue[labels["original"]],
        proof["original"]["execution"],
    )
    current_result = _execution(
        work,
        accepted_rows["current"],
        requests["current"],
        catalogue["b"],
        proof["current"]["execution"],
    )
    require(accepted_rows["original"]["work_id"] != accepted_rows["current"]["work_id"])
    require(original_result["result"]["attempt_id"] != current_result["result"]["attempt_id"])
    same(
        proof["original"]["stale_delivery"],
        {
            "error": "not_eligible",
            "intent": None,
            "historical_result_sha256": proof["original"]["execution"]["result_sha256"],
            "historical_applicability": "outdated",
        },
    )
    for table in (
        "result_delivery_intents",
        "result_delivery_possible",
        "result_delivery_receipts",
    ):
        same(len(work[table]), 1)
    same(len(channel["result_receipts"]), 1)
    same(len(channel["reply_intents"]), 1)
    same(work["result_delivery_intents"][0]["work_id"], accepted_rows["current"]["work_id"])
    same(proof["current"]["delivery"]["intent"]["work_id"], accepted_rows["current"]["work_id"])
    _delivery(
        channel,
        work,
        requests["current"],
        current_result,
        descriptor,
        files,
        proof["current"]["delivery"],
    )
    # Safe C-only synthetic HMAC, never the LINK challenge secret or provider keys.
    signed = object_value(
        files["origin-sms-source.json"], {"schema_version", "raw_utf8", "headers"}
    )
    same(integer(signed["schema_version"]), 1)
    sms_raw = text(signed["raw_utf8"], 32768)
    sms = decode(sms_raw)
    object_value(sms, {"schemaVersion", "eventId", "messageId", "senderId", "body", "occurredAt"})
    same(integer(sms["schemaVersion"]), 1)
    same(sms["body"], _BODIES["ack"])
    same(sms["eventId"], "origin_sms_input")
    headers = object_value(signed["headers"], {"timestamp", "signature"})
    timestamp = text(headers["timestamp"], 10)
    require(re.fullmatch(r"[1-9][0-9]{9}", timestamp) is not None)
    domain = (
        "p2.fake_sms.v1\n"
        + scope["tenant_id"]
        + "\nfake_sms\norigin_fixture_sms\n"
        + timestamp
        + "\n"
    )
    same(
        digest(headers["signature"]),
        hmac.new(
            bytes([0x4F]) * 32, domain.encode() + sms_raw.encode(), hashlib.sha256
        ).hexdigest(),
    )
    ack_event = decode(one(channel["inbox"], "receipt_id", receipt_ids["ack"])["wire_json"])
    for key in ("eventId", "messageId", "senderId", "body", "occurredAt"):
        same(sms[key], ack_event[key])
    require(abs(millis(ack_event["receivedAt"]) / 1000 - int(timestamp)) <= 60)
    supplier = observed["supplier"]
    same(supplier["status"], "passed")
    same(integer(supplier["applied_calls"]), 0)
    same(supplier["mutation_receipts"], [])
    same(supplier["bookings"], [["p3_completion_scope", "DEMO-BK-001", "2030-12-01", 0]])
    same(observed["m1_before"], observed["m1_after"])
    same(observed["m1_before"]["scope_id"], "local-lab")
    uuid(observed["m1_before"]["task_id"])
    digest(observed["m1_before"]["sha256"])
    return {name: {"status": "passed", "code": "ok"} for name in CASES}


def validate_bundle(bundle: object) -> dict[str, CaseResult]:
    """Fail closed as one atomic proof: missing/skipped/forged cases never pass."""
    try:
        return _validate(bundle)
    except OriginEvidenceError:
        raise
    except Exception:  # noqa: BLE001 - evidence diagnostics contain no received values
        raise OriginEvidenceError() from None
