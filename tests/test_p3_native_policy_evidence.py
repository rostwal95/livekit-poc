"""Independent parent-proof controls with entirely synthetic authority rows.

The literal policy is seven days and the one fact is ten days. These fixtures do
not establish PG, RTC, SDK or browser execution. Expected answers never come from
product handlers or the consumer under test; the parent checks source bytes.
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "local-setup/scripts"))
gate = importlib.import_module("p3_native_policy_check")
FIXTURE = json.loads((ROOT / "tests/fixtures/p3-native-policy-proof-positive.json").read_bytes())


def fixture() -> dict[str, Any]:
    return copy.deepcopy(FIXTURE)


def canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def validate_case(value: dict[str, Any]) -> dict[str, Any]:
    return gate.validate_case(
        value["case"],
        value["peer"],
        value["input_value"],
        label="native_retained",
        owner_id=value["input_value"]["owner_id"],
        command_id=value["case"]["issued"]["command_id"],
    )


def validate_peer(value: dict[str, Any]) -> dict[str, Any]:
    return gate.validate_peer(
        value["peer"], value["input_value"], owner_id=value["input_value"]["owner_id"]
    )


def inventory_fixture() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, str]]:
    """Four synthetic proof references plus the fourteen actual authority tables.

    Case/peer validation is tested separately. These are the fields consumed by
    the inventory join, not purported SDK or PostgreSQL execution evidence.
    """

    def identity(family: int, number: int) -> str:
        return f"{family:08x}-0000-4000-8000-{number:012x}"

    base = fixture()["case"]
    scope = copy.deepcopy(base["scope"])
    tables = {
        name: []
        for name in (
            "schema_metadata",
            "accepted_work",
            "admission",
            "cancellation_commands",
            "execution_limits",
            "issued_attempts",
            "attempt_results",
            "result_actions",
            "result_delivery_intents",
            "result_delivery_possible",
            "result_delivery_receipts",
            "result_feed_source",
            "result_feed_heads",
            "result_feed_events",
        )
    }
    cases, context = {}, {"cases": {}}
    for number, label in enumerate(
        ("native_known", "native_retained", "native_stale", "native_useful"), 1
    ):
        request = copy.deepcopy(base["request"])
        request["delegation_id"] = label
        request["request_revision"] = 2 if label == "native_useful" else 1
        request["input_fingerprint"] = hashlib.sha256(
            canonical(
                {k: v for k, v in request.items() if k not in {"attempt", "input_fingerprint"}}
            )
        ).hexdigest()
        work_id, attempt_id = identity(1, number), identity(2, number)
        accepted = copy.deepcopy(base["accepted"])
        accepted.update(work_id=work_id, idempotency_key=label)
        accepted["payload"].update(
            body=canonical(request).decode(), sha256=hashlib.sha256(canonical(request)).hexdigest()
        )
        issued = copy.deepcopy(base["issued"])
        issued.update(
            record=copy.deepcopy(accepted),
            attempt_id=attempt_id,
            command_id=f"native_run_{number}",
            owner_id=identity(3, number),
        )
        stored = copy.deepcopy(base["stored_result"])
        stored.update(work_id=work_id, attempt_id=attempt_id)
        body = stored["body"]
        for key in ("delegation_id", "request_revision", "input_fingerprint"):
            body[key] = request[key]
        body["attempt_id"] = "attempt_" + attempt_id.replace("-", "")
        stored["sha256"] = hashlib.sha256(canonical(body)).hexdigest()
        cases[label] = {
            "request": request,
            "accepted": accepted,
            "issued": issued,
            "stored_result": stored,
            "case_after": {"case_id": identity(6, 1)},
        }
        context["cases"][label] = {
            "owner_id": issued["owner_id"],
            "command_id": issued["command_id"],
        }
        selected = {
            "tenant_id": scope["tenant_id"],
            "account_id": scope["account_id"],
            "work_id": work_id,
        }
        tables["accepted_work"].append(
            {
                **selected,
                "idempotency_key": label,
                "operation": "booking.evaluate_policy",
                "sha256": accepted["payload"]["sha256"],
                "deadline_at_ms": request["deadline_at_ms"],
                "accepted_at_ms": accepted["accepted_at_ms"],
                "body": "\\x" + canonical(request).hex(),
            }
        )
        tables["issued_attempts"].append(
            {**selected, **{k: v for k, v in issued.items() if k != "record"}}
        )
        tables["attempt_results"].append(
            {
                **selected,
                **{k: v for k, v in stored.items() if k != "body"},
                "body": "\\x" + canonical(body).hex(),
            }
        )
        tables["result_feed_events"].append(
            {
                **selected,
                "attempt_id": attempt_id,
                "event_id": identity(5, number),
                "sequence": number,
                "origin": "live",
            }
        )
    tables["schema_metadata"] = [
        {"singleton": True, "version": 4, "max_records": 16, "max_cancel_commands": 16}
    ]
    tables["admission"] = [{"singleton": True, "record_count": 4, "cancel_count": 0}]
    tables["execution_limits"] = [
        {"singleton": True, "max_active": 4, "max_attempts": 3, "lease_ms": 10000}
    ]
    tables["result_feed_source"] = [
        {"singleton": True, "source_id": identity(4, 1), "adopted_at_ms": 1900000000000}
    ]
    tables["result_feed_heads"] = [{**scope, "anchor_work_id": identity(1, 1), "last_sequence": 4}]
    value = {
        "work": tables,
        "case": {
            "cases": [
                {
                    "case_id": identity(6, 1),
                    "task_id": identity(7, 1),
                    "revision": 2,
                    "cancelled": False,
                },
                {
                    "case_id": identity(6, 2),
                    "task_id": identity(7, 2),
                    "revision": 1,
                    "cancelled": True,
                },
            ],
            "tasks": [{"task_id": identity(7, 1)}, {"task_id": identity(7, 2)}],
        },
    }
    return value, cases, context, scope


class NativePolicyEvidenceTests(unittest.TestCase):
    def rejects_case(self, value: dict[str, Any]) -> None:
        with self.assertRaises(gate.GateError) as error:
            validate_case(value)
        self.assertEqual(error.exception.code, "invalid_proof")

    def rejects_peer(self, value: dict[str, Any]) -> None:
        with self.assertRaises(gate.GateError) as error:
            validate_peer(value)
        self.assertEqual(error.exception.code, "invalid_proof")

    def test_literal_positive_and_no_input_mutation(self) -> None:
        value = fixture()
        before = copy.deepcopy(value)
        self.assertEqual(set(value), {"input_value", "case", "peer"})
        policy, facts = [json.loads(r["body_utf8"]) for r in value["input_value"]["evidence"]]
        self.assertEqual(policy["minimum_notice_days"], 7)
        self.assertEqual(
            facts["observations"], [{"fact_id": "notice_primary", "days_before_arrival": 10}]
        )
        self.assertIs(value["peer"]["record"]["result"]["eligible"], True)
        self.assertEqual(validate_peer(value), value["peer"])
        self.assertEqual(validate_case(value), value["case"])
        self.assertEqual(value, before)

    def test_held_read_is_the_original_binding_work_request_and_attempt(self) -> None:
        replacements = (
            ("binding", "delegation_id", "native_other"),
            ("work", "work_id", "66666666-6666-4666-8666-666666666666"),
            ("work", "request_sha256", "b" * 64),
            ("attempt", "attempt_id", "77777777-7777-4777-8777-777777777777"),
        )
        for section, key, replacement in replacements:
            with self.subTest(section=section, key=key):
                value = fixture()
                value["case"]["ownership"]["read_while_held"][section][key] = replacement
                self.rejects_case(value)

    def test_retained_sdk_cancellation_belongs_to_the_started_call(self) -> None:
        for key, replacement in (("status", "done"), ("call_id", "unrelated_call")):
            with self.subTest(key=key):
                value = fixture()
                value["case"]["sdk"]["events"][2][key] = replacement
                self.rejects_case(value)

    def test_terminal_observation_has_a_public_waiter_state(self) -> None:
        value = fixture()
        value["case"]["observation"]["tool_waiter"] = "not_a_public_waiter_state"
        self.rejects_case(value)

    def test_wrong_facts_reject_after_exact_result_digest_repair(self) -> None:
        for field in ("decision", "witness"):
            with self.subTest(field=field):
                value = fixture()
                result = value["peer"]["record"]["result"]
                if field == "decision":
                    result["eligible"] = False
                else:
                    result["fact_refs"][0]["fact_id"] = "notice_other"
                value["peer"]["record"]["result_sha256"] = hashlib.sha256(
                    canonical(result)
                ).hexdigest()
                # Check the peer boundary alone: a later case/body mismatch must
                # not hide a missing semantic rule or complete-witness check.
                self.rejects_peer(value)

    def test_peer_scope_and_canonical_digest_are_bound(self) -> None:
        for field in ("scope", "digest"):
            with self.subTest(field=field):
                value = fixture()
                if field == "scope":
                    value["peer"]["scope"]["account_id"] = "account_other"
                else:
                    value["peer"]["record"]["result_sha256"] = "c" * 64
                self.rejects_peer(value)

    def test_exactly_one_peer_invocation_return_and_actual_cleanup(self) -> None:
        for field, replacement in (("invoked", 2), ("returned", 0), ("cleanup_complete", False)):
            with self.subTest(field=field):
                value = fixture()
                value["peer"][field] = replacement
                self.rejects_peer(value)

    def test_four_case_fourteen_table_inventory_positive(self) -> None:
        value, cases, context, scope = inventory_fixture()
        before = copy.deepcopy((value, cases, context, scope))
        result = gate.validate_inventory(value, cases, context, scope)
        self.assertEqual(len(value["work"]), 14)
        self.assertEqual(
            result["counts"],
            {
                "work": 4,
                "attempts": 4,
                "results": 4,
                "feed": 4,
                "actions": 0,
                "delivery": 0,
                "work_cancellations": 0,
                "case_preparation_tasks": 2,
            },
        )
        self.assertEqual([row["feed_sequence"] for row in result["records"]], [1, 2, 3, 4])
        self.assertEqual((value, cases, context, scope), before)

    def test_inventory_rejects_changed_authority_bytes_scope_feed_and_counts(self) -> None:
        changes = (
            ("accepted_bytes", "accepted_work", "body", "\\x7b7d"),
            ("result_digest", "attempt_results", "sha256", "b" * 64),
            ("work_scope", "accepted_work", "account_id", "account_other"),
            ("feed_head_scope", "result_feed_heads", "account_id", "account_other"),
            ("feed_head_sequence", "result_feed_heads", "last_sequence", 3),
            (
                "feed_head_anchor",
                "result_feed_heads",
                "anchor_work_id",
                "66666666-6666-4666-8666-666666666666",
            ),
            ("admission_count", "admission", "record_count", 5),
            ("source_uuid", "result_feed_source", "source_id", "not_a_uuid"),
            ("duplicate_sequence", "result_feed_events", "sequence", 2),
        )
        for name, table, key, replacement in changes:
            with self.subTest(name=name):
                value, cases, context, scope = inventory_fixture()
                value["work"][table][0][key] = replacement
                with self.assertRaises(gate.GateError) as error:
                    gate.validate_inventory(value, cases, context, scope)
                self.assertEqual(error.exception.code, "invalid_proof")
        for name in ("extra_table", "extra_authority_row", "extra_result"):
            with self.subTest(name=name):
                value, cases, context, scope = inventory_fixture()
                if name == "extra_table":
                    value["work"]["foreign_authority"] = []
                elif name == "extra_authority_row":
                    value["work"]["result_actions"].append({"unexpected": True})
                else:
                    value["work"]["attempt_results"].append(
                        copy.deepcopy(value["work"]["attempt_results"][0])
                    )
                with self.assertRaises(gate.GateError) as error:
                    gate.validate_inventory(value, cases, context, scope)
                self.assertEqual(error.exception.code, "invalid_proof")


if __name__ == "__main__":
    unittest.main()
