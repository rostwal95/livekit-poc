"""Independent literal joins for the selected receiver qualification; no runtime I/O on import."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import p3_document_evidence as common


def require(value: object) -> None:
    if value is not True:
        raise common.GateError("invalid_proof")


def same(left: object, right: object) -> None:
    require(common.exact(left, right))


def row(values: list[dict[str, Any]], key: str, identity: object) -> dict[str, Any]:
    selected = [value for value in values if common.exact(value.get(key), identity)]
    require(len(selected) == 1)
    return selected[0]


def canonical(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def receipt_join(intent: dict[str, Any], receipt: dict[str, Any]) -> None:
    same(
        set(receipt),
        {
            "delivery_id",
            "receipt_id",
            "receiver_id",
            "recipient_id",
            "result_sha256",
            "accepted_at_ms",
        },
    )
    for key in ("delivery_id", "receiver_id", "recipient_id", "result_sha256"):
        same(receipt[key], intent[key])
    require(type(receipt["accepted_at_ms"]) is int)
    require(
        hashlib.sha256(base64.b64decode(intent["body"], validate=True)).hexdigest()
        == intent["result_sha256"]
    )


def p2_join(
    tables: dict[str, Any],
    intent: dict[str, Any],
    receipt: dict[str, Any],
    case_id: str,
    conversation_id: str,
) -> None:
    receipt_join(intent, receipt)
    metadata = row(tables["result_receipts"], "delivery_id", intent["delivery_id"])
    same(metadata["canonical_intent"], canonical(intent))
    for key in ("work_id", "attempt_id", "result_sha256", "recipient_id"):
        same(metadata[key], intent[key])
    for key in ("tenant_id", "account_id"):
        same(metadata[key], intent["scope"][key])
    same(metadata["outbound_id"], intent["delivery_id"])
    same(metadata["case_id"], case_id)
    same(metadata["conversation_id"], conversation_id)
    reply = row(tables["reply_intents"], "outbound_id", metadata["outbound_id"])
    payload = json.loads(reply["canonical_payload"])
    same(
        set(payload),
        {"schemaVersion", "outboundId", "responseId", "body", "scope", "caseId", "conversationId"},
    )
    same(payload["schemaVersion"], 1)
    same(payload["outboundId"], intent["delivery_id"])
    same(payload["responseId"], "p3_" + UUID(intent["work_id"]).hex)
    same(
        payload["scope"],
        {"tenantId": intent["scope"]["tenant_id"], "accountId": intent["scope"]["account_id"]},
    )
    same(payload["caseId"], case_id)
    same(payload["conversationId"], conversation_id)
    for key, expected in (
        ("tenant_id", intent["scope"]["tenant_id"]),
        ("account_id", intent["scope"]["account_id"]),
        ("case_id", case_id),
        ("conversation_id", conversation_id),
        ("response_id", payload["responseId"]),
    ):
        same(reply[key], expected)
    # The linked notice hashes its own bytes, never the original result bytes.
    require(payload["body"] == "Your review result is ready. Rejoin this conversation to view it.")
    notice_sha = hashlib.sha256(payload["body"].encode()).hexdigest()
    require(notice_sha != receipt["result_sha256"])
    same(reply["body_digest"], notice_sha)
    same(reply["intent_digest"], hashlib.sha256(reply["canonical_payload"].encode()).hexdigest())
    same(reply["receipt_id"], receipt["receipt_id"])
    delta = datetime.fromisoformat(reply["accepted_at"]) - datetime(1970, 1, 1, tzinfo=UTC)
    same(
        delta.days * 86400000 + delta.seconds * 1000 + delta.microseconds // 1000,
        receipt["accepted_at_ms"],
    )
    same(tables["outbox_settings"][0]["receiver_id"], receipt["receiver_id"])


def _validate_join(
    proof: dict[str, Any],
    snapshot: dict[str, Any],
    p2_schema: str,
    work_schema: str,
    case_schema: str,
    sources: dict[str, Any],
) -> None:
    same(proof["status"], "passed")
    same(proof["scripted_port_invocations"], 3)
    require(proof["provider_calls"] is False and proof["cleanup_complete"] is True)
    same(proof["p2_notices"], 2)
    results = proof["results"]
    same(set(results), {"original", "stale", "current"})
    require(len({v["work_id"] for v in results.values()}) == 3)
    work, channel, cases = snapshot[work_schema], snapshot[p2_schema], snapshot[case_schema]
    for name in ("send_attempts", "send_results", "outbound_routes"):
        same(channel[name], [])
    same(len(cases["cases"]), 1)
    same(cases["cases"][0]["revision"], 2)
    require(cases["cases"][0]["cancelled"] is False)
    for name in ("accepted_work", "issued_attempts", "attempt_results", "result_feed_events"):
        same(len(work[name]), 3)
    for name in ("result_delivery_intents", "result_delivery_possible", "result_delivery_receipts"):
        same(len(work[name]), 2)
    for name in ("result_actions", "cancellation_commands"):
        same(work[name], [])
    for name in (
        "action_intents",
        "mutation_effects",
        "mutation_attempts",
        "cancellation_commands",
        "business_outcomes",
    ):
        same(cases[name], [])
    for label, value in results.items():
        request = json.loads(value["request_canonical"])
        result = json.loads(value["result_canonical"])
        logical = {
            key: item
            for key, item in request.items()
            if key not in {"attempt", "input_fingerprint"}
        }
        logical_bytes = json.dumps(
            logical, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode()
        same(request["input_fingerprint"], hashlib.sha256(logical_bytes).hexdigest())
        same(len(request["evidence"]), 2)
        same(len(result["rule_refs"]), 1)
        same(len(result["fact_refs"]), 1)
        same(request["context_snapshot"], sources["producer_input"]["context_snapshot"])
        for ref, original_ref, key in zip(
            request["evidence"],
            sources["producer_input"]["evidence"],
            ("policy_body_utf8", "facts_body_utf8"),
            strict=True,
        ):
            same(ref, original_ref)
            body = sources[key].encode("utf-8")
            same(ref["sha256"], hashlib.sha256(body).hexdigest())
            same(ref["byte_length"], len(body))
        policy, facts = (
            json.loads(sources["policy_body_utf8"]),
            json.loads(sources["facts_body_utf8"]),
        )
        same(policy["policy_version"], "notice_v1")
        same(policy["rule_id"], "notice_minimum_days")
        same(policy["minimum_notice_days"], 7)
        same(facts["observations"], [{"fact_id": "notice_primary", "days_before_arrival": 10}])
        same(result["rule_refs"][0]["rule_id"], policy["rule_id"])
        same(result["fact_refs"][0]["fact_id"], "notice_primary")
        require(type(request["request_revision"]) is int)
        same(request["request_revision"], 2 if label == "current" else 1)
        for key in ("scope", "delegation_id", "case_id", "request_revision", "input_fingerprint"):
            same(result[key], request[key])
        require(result["eligible"] is True)
        same(result["uncertainty"], "none")
        same(result["rule_refs"][0]["minimum_notice_days"], 7)
        same(result["fact_refs"][0]["days_before_arrival"], 10)
        for ref, witness in zip(
            request["evidence"], (result["rule_refs"][0], result["fact_refs"][0]), strict=True
        ):
            for key in ("source_id", "version", "sha256"):
                same(witness[key], ref[key])
        accepted = row(work["accepted_work"], "work_id", value["work_id"])
        same(accepted["body"], "\\x" + value["request_canonical"].encode().hex())
        same(accepted["sha256"], hashlib.sha256(value["request_canonical"].encode()).hexdigest())
        for key in ("tenant_id", "account_id"):
            same(accepted[key], request["scope"][key])
        issued = row(work["issued_attempts"], "work_id", value["work_id"])
        for key, item in value["issued"].items():
            same(issued[key], item)
        same(result["attempt_id"], "attempt_" + UUID(issued["attempt_id"]).hex)
        recorded = row(work["attempt_results"], "work_id", value["work_id"])
        same(recorded["body"], "\\x" + value["result_canonical"].encode().hex())
        same(recorded["sha256"], hashlib.sha256(value["result_canonical"].encode()).hexdigest())
        for key, item in value["recorded"].items():
            same(recorded[key], item)
        same(recorded["disposition"], "eligible_at_commit")
        same(
            row(work["result_feed_events"], "work_id", value["work_id"])["attempt_id"],
            issued["attempt_id"],
        )
        delivery = value["delivery"]
        if label == "stale":
            same(value["new_delivery_error"], "not_eligible")
            same(delivery, {"state": "missing", "intent": None})
            continue
        same(delivery["state"], "accepted")
        intent, receipt, view = delivery["intent"], delivery["receipt"], value["return_view"]
        same(intent["work_id"], value["work_id"])
        same(intent["attempt_id"], issued["attempt_id"])
        same(intent["result_sha256"], recorded["sha256"])
        same(base64.b64decode(intent["body"], validate=True), value["result_canonical"].encode())
        stored = row(work["result_delivery_intents"], "work_id", value["work_id"])
        for key in (
            "delivery_id",
            "attempt_id",
            "result_sha256",
            "receiver_id",
            "recipient_id",
            "prepared_at_ms",
        ):
            same(stored[key], intent[key])
        row(work["result_delivery_possible"], "delivery_id", intent["delivery_id"])
        stored_receipt = row(work["result_delivery_receipts"], "delivery_id", intent["delivery_id"])
        for key, item in receipt.items():
            same(stored_receipt[key], item)
        p2_join(
            channel, intent, receipt, request["case_id"], request["result_route"]["conversation_id"]
        )
        same(view["intent"], intent)
        same(view["receipt"], receipt)
        require(view["observed"]["atomic"] is False)
        same(view["case"]["revision"], "2")
        same(view["case"]["source"], "p1_public_v4")
        same(view["case"]["workflow"]["taskId"], cases["cases"][0]["task_id"])
        same(view["case"]["caseId"], request["case_id"])
        same(view["case"]["conversationId"], request["result_route"]["conversation_id"])
        same(
            view["case"]["scope"],
            {
                "tenantId": request["scope"]["tenant_id"],
                "accountId": request["scope"]["account_id"],
            },
        )
        if label == "original":
            ack = value["ack_loss"]
            same(ack["kind"], "simulated_sender_ack_loss_no_process_kill")
            same(ack["before_receiver"], ack["after_receiver_before_record"])
            require(ack["before_receiver"]["possible"] is True)
            require(ack["before_receiver"]["receipt"] is None)
            same(ack["before_receiver"]["intent"], intent)
            same(ack["receiver_receipt"], receipt)
            same(delivery["receiver_metrics"]["accepted"], 0)
            same(delivery["receiver_metrics"]["found"], 1)
            require(delivery["receiver_invoked"] is False)
        else:
            same(delivery["receiver_metrics"]["accepted"], 1)
            require(delivery["receiver_invoked"] is True)


def validate_join(
    proof: dict[str, Any],
    snapshot: dict[str, Any],
    p2_schema: str,
    work_schema: str,
    case_schema: str,
    sources: dict[str, Any],
) -> None:
    try:
        _validate_join(proof, snapshot, p2_schema, work_schema, case_schema, sources)
    except (KeyError, ValueError, TypeError, IndexError, OverflowError):
        raise common.GateError("invalid_proof") from None


def validate_retained_read(control: dict[str, Any], receipt: dict[str, Any]) -> None:
    """This actual fault is caller cancellation after a completed public P1 read."""
    same(control["fault_kind"], "explicit_caller_abort_after_public_p1_read")
    require(control["read_completed"] is True and control["caller_aborted"] is True)
    same(control["pending"]["reader"]["active"], 1)
    same(control["pending"]["reader"]["waiterRejected"], 1)
    same(control["pending"]["outbox"]["storageActive"], 1)
    same(control["pending"]["idle_transactions"], [])
    same(control["settled"]["active"], 0)
    same(control["useful_receipt"], receipt)


def validate_bundle(
    directory: Path,
    snapshot: dict[str, Any],
    p2_schema: str,
    work_schema: str,
    case_schema: str,
) -> dict[str, int]:
    """Require named literal controls, owner SQL joins and current useful progress."""

    def load(name: str) -> dict[str, Any]:
        value = json.loads(common.read_private(directory / name, 2097152))
        require(type(value) is dict)
        return cast(dict[str, Any], value)

    try:
        setup, upgrade = load("result-setup-snapshot.json"), load("result-upgrade.json")
        same(setup["meta"]["version"], 7)
        same(upgrade["before"], setup)
        same(upgrade["rolled_back"], setup)
        same(upgrade["after"]["meta"]["version"], 8)
        same(upgrade["after"]["replyRows"], setup["replyRows"])
        same(upgrade["after"]["counts"], setup["counts"])
        same(upgrade["receiver_id"], setup["settings"]["receiver_id"])
        exercised = load("result-exercise.json")
        same(exercised["carrier_calls"], 0)
        controls = exercised["controls"]
        names = [value["name"] for value in controls]
        same(
            names,
            [
                "atomic_original_acceptance",
                "concurrent_original_replay",
                "changed_foreign_and_ordinary_collision_denial",
                "full_opaque_body_notice_separation",
                "fresh_b_scoped_public_case_read",
                "revocation_after_public_read_and_receiver_history",
                "expiry_after_protected_admission_wait",
                "retained_waiter_sql_release_close_retry_and_progress",
            ],
        )
        accepted, replay, denied, maximum, fresh, revoked, expired, retained = controls
        intent = json.loads(accepted["intent_canonical"])
        receipt = accepted["receipt"]
        receipt_join(intent, receipt)
        same(len(accepted["after"]["replyRows"]) - len(accepted["before"]["replyRows"]), 1)
        same(len(accepted["after"]["resultRows"]) - len(accepted["before"]["resultRows"]), 1)
        same(replay["snapshot"], accepted["after"])
        same(replay["receipts"], [receipt, receipt])
        same(denied["snapshot"], accepted["after"])
        require(denied["changed_canonical"] != accepted["intent_canonical"])
        same(
            len(base64.b64decode(json.loads(maximum["intent_canonical"])["body"], validate=True)),
            8192,
        )
        require(len(maximum["reply"]["reply"]["body"].encode()) <= 4096)
        same(fresh["view"]["receipt"], receipt)
        same(fresh["view"]["case"]["source"], "p1_public_v4")
        require(fresh["view"]["observed"]["atomic"] is False)
        require(fresh["a"]["bindingId"] != fresh["b"]["bindingId"])
        same(revoked["original_receipt"], receipt)
        graph = expired["blocking_graph"]
        require(type(graph["blocking_pid"]) is int and type(graph["blocked_pid"]) is int)
        require(
            graph["blocking_pid"] != graph["blocked_pid"]
            and graph["blocking_pid"] in graph["blockers"]
        )
        require(
            datetime.fromisoformat(expired["db_expiry_witness"])
            >= datetime.fromisoformat(expired["grant"]["expiresAt"])
        )
        validate_retained_read(retained, receipt)
        crash, recovered = load("commit-before-ack.reached"), load("result-recover.json")
        same(recovered["before"], recovered["after"])
        same(recovered["receipt"], crash["receipt"])
        same(recovered["intent_canonical"], crash["intent_canonical"])
        same(recovered["carrier_calls"], 0)
        served = load("result-serve-final.json")
        same(served["handlers"], 0)
        same(served["pending_tasks"], 0)
        same(served["carrier_calls"], 0)
        validate_join(
            load("p3-return-proof.json"),
            snapshot,
            p2_schema,
            work_schema,
            case_schema,
            load("p3-return-policy.json"),
        )
        return {"storage_assertions_before_restore": 14, "return_assertions": 4}
    except (KeyError, ValueError, TypeError, IndexError, OverflowError):
        raise common.GateError("invalid_proof") from None


def validate_restore(proof: dict[str, Any], before: dict[str, Any]) -> None:
    try:
        # Before is a full owner SQL table map, while the fixture retains its selected rows.
        same(
            sorted(proof["restored_snapshot"]["resultRows"], key=lambda r: r["delivery_id"]),
            sorted(before["result_receipts"], key=lambda r: r["delivery_id"]),
        )

        def replies(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return sorted(
                [
                    {
                        **value,
                        "accepted_at": datetime.fromisoformat(value["accepted_at"])
                        .astimezone(UTC)
                        .isoformat(timespec="milliseconds"),
                    }
                    for value in rows
                ],
                key=lambda r: r["outbound_id"],
            )

        same(replies(proof["restored_snapshot"]["replyRows"]), replies(before["reply_intents"]))
        full = proof["at_capacity_snapshot"]
        same(full["counts"]["reply_count"], 8)
        same(len(full["replyRows"]), 8)
        same(len(full["resultRows"]), 7)
        for original in before["result_receipts"]:
            same(row(full["resultRows"], "delivery_id", original["delivery_id"]), original)
        for original in replies(before["reply_intents"]):
            same(row(replies(full["replyRows"]), "outbound_id", original["outbound_id"]), original)
        same(proof["capacity_denial"]["code"], "Overloaded")
        denied = json.loads(proof["capacity_denial"]["intent_canonical"])
        require(all(row["delivery_id"] != denied["delivery_id"] for row in full["resultRows"]))
        receipt_join(proof["view"]["intent"], proof["receipt"])
        same(proof["view"]["receipt"], proof["receipt"])
        require(proof["view"]["observed"]["atomic"] is False)
        same(proof["carrier_calls"], 0)
    except (KeyError, ValueError, TypeError, IndexError):
        raise common.GateError("invalid_proof") from None
