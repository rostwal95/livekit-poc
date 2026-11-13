"""Public-producer positive join and independent corruption controls; no database/provider."""

from __future__ import annotations

import base64
import copy
import hashlib
import importlib.util
import json
import sys
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from uuid import uuid4

from continuity_lab.delivery_api import DeliveryIntent, DeliveryReceipt
from continuity_lab.work_api import WorkScope
from delegation_reliability.contracts import canonical
from delegation_reliability.fixed_policy_contracts import (
    encode_fixed_policy_request,
    encode_fixed_policy_result,
    parse_fixed_policy_result,
    produce_fixed_policy_request,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "local-setup/scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "result_evidence_tested", SCRIPTS / "p2_result_receiver_evidence.py"
)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)
POLICY = json.loads((ROOT / "contracts/delegation/fixed-policy-v2.json").read_bytes())
NOTICE = "Your review result is ready. Rejoin this conversation to view it."


def positive():
    work = {
        name: []
        for name in (
            "accepted_work",
            "issued_attempts",
            "attempt_results",
            "result_feed_events",
            "result_delivery_intents",
            "result_delivery_possible",
            "result_delivery_receipts",
            "result_actions",
            "cancellation_commands",
        )
    }
    receiver_id, task_id = str(uuid4()), str(uuid4())
    channel = {
        "result_receipts": [],
        "reply_intents": [],
        "outbox_settings": [{"receiver_id": receiver_id}],
    }
    channel.update(send_attempts=[], send_results=[], outbound_routes=[])
    cases = {
        name: []
        for name in (
            "action_intents",
            "mutation_effects",
            "mutation_attempts",
            "cancellation_commands",
            "business_outcomes",
        )
    }
    cases["cases"] = [{"revision": 2, "task_id": task_id, "cancelled": False}]
    proofs = {}
    for label, revision in (("original", 1), ("stale", 1), ("current", 2)):
        raw = copy.deepcopy(POLICY["producer_input"])
        raw.update(delegation_id="return_" + label, request_revision=revision)
        request = produce_fixed_policy_request(raw)
        work_id, attempt_id, command_id = str(uuid4()), str(uuid4()), str(uuid4())
        result = replace(
            parse_fixed_policy_result(canonical(POLICY["result"])),
            delegation_id=request.delegation_id,
            request_revision=revision,
            input_fingerprint=request.input_fingerprint,
            attempt_id="attempt_" + attempt_id.replace("-", ""),
        )
        request_body, result_body = (
            encode_fixed_policy_request(request),
            encode_fixed_policy_result(result),
        )
        digest = hashlib.sha256(result_body).hexdigest()
        issued = {
            "attempt_id": attempt_id,
            "command_id": command_id,
            "number": 1,
            "owner_id": str(uuid4()),
            "epoch": 1,
            "issued_at_ms": 1900000000001,
            "lease_until_ms": 1900000009001,
        }
        recorded = {
            "attempt_id": attempt_id,
            "sha256": digest,
            "recorded_at_ms": 1900000000002,
            "disposition": "eligible_at_commit",
        }
        work["accepted_work"].append(
            {
                "work_id": work_id,
                **raw["scope"],
                "body": "\\x" + request_body.hex(),
                "sha256": hashlib.sha256(request_body).hexdigest(),
            }
        )
        work["issued_attempts"].append({"work_id": work_id, **issued})
        work["attempt_results"].append(
            {"work_id": work_id, **recorded, "body": "\\x" + result_body.hex()}
        )
        work["result_feed_events"].append({"work_id": work_id, "attempt_id": attempt_id})
        proof = {
            "work_id": work_id,
            "request_canonical": request_body.decode(),
            "result_canonical": result_body.decode(),
            "issued": issued,
            "recorded": recorded,
        }
        proofs[label] = proof
        if label == "stale":
            proof.update(
                new_delivery_error="not_eligible", delivery={"state": "missing", "intent": None}
            )
            continue
        intent = DeliveryIntent(
            str(uuid4()),
            WorkScope(**raw["scope"]),
            work_id,
            attempt_id,
            digest,
            receiver_id,
            "recipient_demo",
            result_body,
            1900000000003,
        )
        receipt = DeliveryReceipt(
            intent.delivery_id,
            str(uuid4()),
            receiver_id,
            intent.recipient_id,
            digest,
            1900000000004,
        )
        wire_intent, wire_receipt = json.loads(intent.canonical()), asdict(receipt)
        work["result_delivery_intents"].append(
            {k: v for k, v in wire_intent.items() if k not in {"body", "scope"}}
        )
        work["result_delivery_possible"].append({"delivery_id": intent.delivery_id})
        work["result_delivery_receipts"].append(wire_receipt.copy())
        channel["result_receipts"].append(
            {
                "delivery_id": intent.delivery_id,
                **raw["scope"],
                "work_id": work_id,
                "attempt_id": attempt_id,
                "result_sha256": digest,
                "recipient_id": intent.recipient_id,
                "case_id": request.case_id,
                "conversation_id": request.conversation_id,
                "outbound_id": intent.delivery_id,
                "canonical_intent": intent.canonical().decode(),
            }
        )
        payload = json.dumps(
            {
                "schemaVersion": 1,
                "outboundId": intent.delivery_id,
                "responseId": "p3_" + work_id.replace("-", ""),
                "body": NOTICE,
                "scope": {
                    "tenantId": request.scope.tenant_id,
                    "accountId": request.scope.account_id,
                },
                "caseId": request.case_id,
                "conversationId": request.conversation_id,
            },
            separators=(",", ":"),
        )
        channel["reply_intents"].append(
            {
                "outbound_id": intent.delivery_id,
                "receipt_id": receipt.receipt_id,
                **raw["scope"],
                "case_id": request.case_id,
                "conversation_id": request.conversation_id,
                "response_id": "p3_" + work_id.replace("-", ""),
                "canonical_payload": payload,
                "body_digest": hashlib.sha256(NOTICE.encode()).hexdigest(),
                "intent_digest": hashlib.sha256(payload.encode()).hexdigest(),
                "accepted_at": "2030-03-17T17:46:40.004+00:00",
            }
        )
        # The exact epoch is from the actual public producer; avoid handwritten calendar conversion.
        from datetime import UTC, datetime, timedelta

        channel["reply_intents"][-1]["accepted_at"] = (
            datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=receipt.accepted_at_ms)
        ).isoformat(timespec="milliseconds")
        proof["delivery"] = {
            "state": "accepted",
            "intent": wire_intent,
            "receipt": wire_receipt,
            "receiver_invoked": label == "current",
            "receiver_metrics": {
                "accepted": int(label == "current"),
                "found": int(label == "original"),
            },
        }
        proof["return_view"] = {
            "intent": copy.deepcopy(wire_intent),
            "receipt": wire_receipt.copy(),
            "observed": {"atomic": False},
            "case": {
                "revision": "2",
                "source": "p1_public_v4",
                "caseId": request.case_id,
                "conversationId": request.conversation_id,
                "scope": {
                    "tenantId": request.scope.tenant_id,
                    "accountId": request.scope.account_id,
                },
                "workflow": {"taskId": task_id},
            },
        }
        if label == "original":
            pending = {"intent": copy.deepcopy(wire_intent), "possible": True, "receipt": None}
            proof["ack_loss"] = {
                "kind": "simulated_sender_ack_loss_no_process_kill",
                "before_receiver": pending,
                "after_receiver_before_record": copy.deepcopy(pending),
                "receiver_receipt": wire_receipt.copy(),
            }
    return (
        {
            "status": "passed",
            "scripted_port_invocations": 3,
            "provider_calls": False,
            "cleanup_complete": True,
            "p2_notices": 2,
            "results": proofs,
        },
        {"p2": channel, "work": work, "case": cases},
    )


class ResultEvidenceTests(unittest.TestCase):
    def test_retained_read_requires_real_entry_then_explicit_caller_abort_and_actual_settlement(
        self,
    ):
        proof, _ = positive()
        receipt = proof["results"]["original"]["delivery"]["receipt"]
        control = {
            "fault_kind": "explicit_caller_abort_after_public_p1_read",
            "read_completed": True,
            "caller_aborted": True,
            "pending": {
                "reader": {"active": 1, "waiterRejected": 1},
                "outbox": {"storageActive": 1},
                "idle_transactions": [],
            },
            "settled": {"active": 0},
            "useful_receipt": receipt.copy(),
        }
        m.validate_retained_read(control, receipt)
        mutations = (
            lambda v: v.update(fault_kind="ignored_http_cancellation"),
            lambda v: v.update(read_completed=False),
            lambda v: v.update(caller_aborted=1),
            lambda v: v["pending"]["reader"].update(active=0),
            lambda v: v["pending"]["reader"].update(waiterRejected=0),
            lambda v: v["pending"]["outbox"].update(storageActive=0),
            lambda v: v["pending"].update(idle_transactions=[{"state": "idle in transaction"}]),
            lambda v: v["settled"].update(active=1),
            lambda v: v["useful_receipt"].update(result_sha256="0" * 64),
        )
        for number, mutate in enumerate(mutations):
            changed = copy.deepcopy(control)
            mutate(changed)
            with self.subTest(retained_control=number), self.assertRaises(m.common.GateError):
                m.validate_retained_read(changed, receipt)

    def test_actual_p1_producer_positive_joins_three_results_two_receipts_and_current_case(self):
        proof, snapshot = positive()
        m.validate_join(proof, snapshot, "p2", "work", "case", POLICY)

    def test_coordinated_forgery_across_all_ledgers_cannot_hide_unsupported_policy_facts(self):
        for kind in (
            "extra_rule",
            "extra_fact",
            "wrong_rule",
            "wrong_fact",
            "false_decision",
            "fingerprint",
            "source_hash",
        ):
            proof, snapshots = positive()
            original = proof["results"]["original"]
            work_id = original["work_id"]
            result, request = (
                json.loads(original["result_canonical"]),
                json.loads(original["request_canonical"]),
            )
            if kind == "extra_rule":
                result["rule_refs"].append(copy.deepcopy(result["rule_refs"][0]))
            elif kind == "extra_fact":
                result["fact_refs"].append(copy.deepcopy(result["fact_refs"][0]))
            elif kind == "wrong_rule":
                result["rule_refs"][0]["minimum_notice_days"] = 6
            elif kind == "wrong_fact":
                result["fact_refs"][0]["days_before_arrival"] = 11
            elif kind == "false_decision":
                result["eligible"] = False
            elif kind == "fingerprint":
                request["input_fingerprint"] = result["input_fingerprint"] = "0" * 64
            elif kind == "source_hash":
                request["evidence"][0]["sha256"] = result["rule_refs"][0]["sha256"] = "0" * 64
                logical = {
                    key: value
                    for key, value in request.items()
                    if key not in {"attempt", "input_fingerprint"}
                }
                request["input_fingerprint"] = result["input_fingerprint"] = hashlib.sha256(
                    canonical(logical)
                ).hexdigest()
            original["request_canonical"] = canonical(request).decode()
            original["result_canonical"] = canonical(result).decode()
            new_digest = hashlib.sha256(original["result_canonical"].encode()).hexdigest()
            original["recorded"]["sha256"] = new_digest
            accepted = next(
                row for row in snapshots["work"]["accepted_work"] if row["work_id"] == work_id
            )
            accepted.update(
                body="\\x" + original["request_canonical"].encode().hex(),
                sha256=hashlib.sha256(original["request_canonical"].encode()).hexdigest(),
            )
            recorded = next(
                row for row in snapshots["work"]["attempt_results"] if row["work_id"] == work_id
            )
            recorded.update(
                body="\\x" + original["result_canonical"].encode().hex(), sha256=new_digest
            )
            intent = original["delivery"]["intent"]
            intent.update(
                body=base64.b64encode(original["result_canonical"].encode()).decode(),
                result_sha256=new_digest,
            )
            receipt = original["delivery"]["receipt"]
            receipt["result_sha256"] = new_digest
            original["return_view"].update(intent=copy.deepcopy(intent), receipt=receipt.copy())
            ack = original["ack_loss"]
            ack["receiver_receipt"] = receipt.copy()
            for key in ("before_receiver", "after_receiver_before_record"):
                ack[key]["intent"] = copy.deepcopy(intent)
            for table in ("result_delivery_intents", "result_delivery_receipts"):
                next(
                    row
                    for row in snapshots["work"][table]
                    if row["delivery_id"] == intent["delivery_id"]
                )["result_sha256"] = new_digest
            metadata = next(
                row for row in snapshots["p2"]["result_receipts"] if row["work_id"] == work_id
            )
            metadata.update(canonical_intent=m.canonical(intent), result_sha256=new_digest)
            # Every request/result/body hash, receipt and route remains mutually consistent.
            # Only an independent source/factual/fingerprint check can reject this history.
            with self.subTest(coordinated_forgery=kind), self.assertRaises(m.common.GateError):
                m.validate_join(proof, snapshots, "p2", "work", "case", POLICY)

    def test_independent_original_binding_digest_scope_sql_and_return_corruptions_fail(self):
        mutations = (
            lambda p, s: p.update(scripted_port_invocations=0),
            lambda p, s: p.update(provider_calls=True),
            lambda p, s: p.update(cleanup_complete=False),
            lambda p, s: s["work"]["accepted_work"][0].update(body="\\x00"),
            lambda p, s: s["work"]["accepted_work"][0].update(account_id="foreign"),
            lambda p, s: s["work"]["issued_attempts"][0].update(attempt_id=str(uuid4())),
            lambda p, s: s["work"]["attempt_results"][0].update(sha256="0" * 64),
            lambda p, s: s["work"]["result_feed_events"].pop(),
            lambda p, s: s["work"]["result_delivery_possible"].pop(),
            lambda p, s: s["work"]["result_delivery_receipts"][0].update(receipt_id=str(uuid4())),
            lambda p, s: s["work"]["result_actions"].append({"unexpected": True}),
            lambda p, s: s["case"]["mutation_effects"].append({"unexpected": True}),
            lambda p, s: s["p2"]["send_attempts"].append({"unexpected": True}),
            lambda p, s: s["case"]["cases"][0].update(revision=1),
            lambda p, s: s["p2"]["result_receipts"][0].update(canonical_intent="{}"),
            lambda p, s: s["p2"]["result_receipts"][0].update(result_sha256="0" * 64),
            lambda p, s: s["p2"]["result_receipts"][0].update(case_id="foreign_case"),
            lambda p, s: s["p2"]["reply_intents"][0].update(conversation_id="foreign_conversation"),
            lambda p, s: s["p2"]["reply_intents"][0].update(response_id="foreign_response"),
            lambda p, s: s["p2"]["reply_intents"][0].update(body_digest="0" * 64),
            lambda p, s: p["results"]["original"]["ack_loss"]["before_receiver"].update(
                possible=False
            ),
            lambda p, s: p["results"]["original"]["delivery"]["receiver_metrics"].update(
                accepted=1
            ),
            lambda p, s: p["results"]["current"]["return_view"]["case"].update(revision="1"),
            lambda p, s: p["results"]["current"]["return_view"]["observed"].update(atomic=True),
            lambda p, s: p["results"]["stale"].update(new_delivery_error="ok"),
        )
        for number, mutate in enumerate(mutations):
            proof, snapshot = positive()
            mutate(proof, snapshot)
            with self.subTest(control=number), self.assertRaises(m.common.GateError):
                m.validate_join(proof, snapshot, "p2", "work", "case", POLICY)

    def test_missing_and_malformed_evidence_translate_to_one_safe_error(self):
        proof, snapshot = positive()
        for value in ({}, {**proof, "results": []}, {**proof, "results": {}}):
            with (
                self.subTest(shape=type(value.get("results"))),
                self.assertRaises(m.common.GateError) as caught,
            ):
                m.validate_join(value, snapshot, "p2", "work", "case", POLICY)
            self.assertEqual(caught.exception.code, "invalid_proof")

    def test_restore_preserves_original_rows_and_normalizes_only_timestamp_representation(self):
        proof, snapshots = positive()
        before = snapshots["p2"]
        metadata = copy.deepcopy(before["result_receipts"])
        replies = copy.deepcopy(before["reply_intents"])
        for _ in range(5):
            item, reply = copy.deepcopy(metadata[0]), copy.deepcopy(replies[0])
            delivery_id, work_id, attempt_id = str(uuid4()), str(uuid4()), str(uuid4())
            wire = json.loads(item["canonical_intent"])
            wire.update(delivery_id=delivery_id, work_id=work_id, attempt_id=attempt_id)
            item.update(
                delivery_id=delivery_id,
                outbound_id=delivery_id,
                work_id=work_id,
                attempt_id=attempt_id,
                canonical_intent=m.canonical(wire),
            )
            payload = json.loads(reply["canonical_payload"])
            payload.update(outboundId=delivery_id, responseId="p3_" + work_id.replace("-", ""))
            reply.update(
                outbound_id=delivery_id,
                receipt_id=str(uuid4()),
                response_id=payload["responseId"],
                canonical_payload=json.dumps(payload, separators=(",", ":")),
            )
            reply["intent_digest"] = hashlib.sha256(reply["canonical_payload"].encode()).hexdigest()
            metadata.append(item)
            replies.append(reply)
        replies.append({**replies[0], "outbound_id": str(uuid4()), "receipt_id": str(uuid4())})
        denied = json.loads(metadata[0]["canonical_intent"])
        denied.update(delivery_id=str(uuid4()), work_id=str(uuid4()), attempt_id=str(uuid4()))
        restore = {
            "restored_snapshot": {
                "resultRows": list(reversed(copy.deepcopy(before["result_receipts"]))),
                "replyRows": [
                    {**value, "accepted_at": value["accepted_at"].replace("+00:00", "Z")}
                    for value in reversed(before["reply_intents"])
                ],
            },
            "at_capacity_snapshot": {
                "replyRows": replies,
                "resultRows": metadata,
                "counts": {"reply_count": 8},
            },
            "capacity_denial": {"intent_canonical": m.canonical(denied), "code": "Overloaded"},
            "receipt": proof["results"]["original"]["delivery"]["receipt"],
            "view": proof["results"]["original"]["return_view"],
            "carrier_calls": 0,
        }
        m.validate_restore(restore, before)
        mutations = (
            lambda v: v["restored_snapshot"]["resultRows"][0].update(canonical_intent="{}"),
            lambda v: v["at_capacity_snapshot"]["resultRows"][0].update(case_id="foreign_case"),
            lambda v: v["at_capacity_snapshot"]["replyRows"][0].update(canonical_payload="{}"),
            lambda v: v["at_capacity_snapshot"]["counts"].update(reply_count=7),
            lambda v: v["capacity_denial"].update(code="ok"),
            lambda v: v.update(carrier_calls=1),
        )
        for number, mutate in enumerate(mutations):
            changed = copy.deepcopy(restore)
            mutate(changed)
            with self.subTest(restore_control=number), self.assertRaises(m.common.GateError):
                m.validate_restore(changed, before)


if __name__ == "__main__":
    unittest.main()
