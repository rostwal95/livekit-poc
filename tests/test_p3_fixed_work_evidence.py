"""Independent adversarial controls; the positive data is explicitly synthetic."""

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
evidence = importlib.import_module("p3_fixed_work_evidence")
FIXTURE = json.loads((ROOT / "tests/fixtures/p3-fixed-work-proof-positive.json").read_bytes())


def fixture() -> dict[str, Any]:
    return copy.deepcopy(FIXTURE)


def run(value: dict[str, Any]) -> dict[str, object]:
    return evidence.validate_bundle(
        value["authority"],
        value["peer"],
        value["wires"],
        value["sources"],
        expected_scope=value["expected_scope"],
    )


def replace_result(value: dict[str, Any], index: int, result: dict[str, Any]) -> None:
    """Repair every declared result digest so semantic tests cannot fail on SHA alone."""
    raw = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    sha = hashlib.sha256(raw.encode()).hexdigest()
    value["wires"][index]["result_utf8"] = raw
    value["peer"]["records"][index]["result_sha256"] = sha
    row = value["authority"]["records"][index]
    if row["result_sha256"] is not None:
        row["result_sha256"] = sha
        for event in value["authority"]["events"]:
            if event["work_id"] == row["work_id"]:
                event["result_sha256"] = sha


def assign(value: dict[str, Any], path: tuple[str | int, ...], replacement: object) -> None:
    node: Any = value
    for part in path[:-1]:
        node = node[part]
    node[path[-1]] = replacement


class FixedWorkEvidenceTests(unittest.TestCase):
    def rejects(self, value: dict[str, Any]) -> None:
        with self.assertRaises(evidence.GateError) as error:
            run(value)
        self.assertEqual(error.exception.code, "invalid_proof")
        self.assertEqual(str(error.exception), "invalid_proof")

    def test_complete_literal_positive_and_no_input_mutation(self) -> None:
        value = fixture()
        before = copy.deepcopy(value)
        result = run(value)
        self.assertEqual(
            (result["stored_results"], result["rejected_bodies"], result["feed_events"]), (8, 5, 8)
        )
        self.assertEqual((result["public_invocations"], result["fault_invocations"]), (7, 6))
        self.assertEqual(value, before)

    def test_closed_shapes_primitive_types_and_actual_occupancy(self) -> None:
        mutations = (
            (("authority", "schema_version"), True),
            (("authority", "counts", "work"), True),
            (("authority", "schema_versions", "case"), "4"),
            (("authority", "counts", "actions"), 1),
            (("authority", "counts", "supplier_calls"), 1),
            (("authority", "scope", "account_id"), "foreign_account"),
            (("peer", "cleanup_complete"), 1),
            (("peer", "counts", "active"), 1),
            (("peer", "counts", "sockets"), 1),
            (("peer", "counts", "requests"), 1),
            (("authority", "records", 0, "attempt_number"), True),
            (("authority", "records", 0, "epoch"), 2),
            (("authority", "records", 0, "owner_id"), "not-a-uuid"),
            (("authority", "records", 0, "unexpected"), "PRIVATE_SENTINEL"),
            (("wires", 0, "request_utf8"), "x" * 16385),
        )
        for path, replacement in mutations:
            with self.subTest(path=path):
                value = fixture()
                assign(value, path, replacement)
                self.rejects(value)

    def test_original_work_attempt_wire_and_feed_joins(self) -> None:
        mutations = (
            (("authority", "records", 1, "work_id"), FIXTURE["authority"]["records"][0]["work_id"]),
            (
                ("authority", "records", 1, "attempt_id"),
                FIXTURE["authority"]["records"][0]["attempt_id"],
            ),
            (("peer", "records", 0, "request_sha256"), "0" * 64),
            (("peer", "records", 0, "result_sha256"), "0" * 64),
            (("authority", "records", 0, "accepted_request_sha256"), "0" * 64),
            (("authority", "events", 0, "scope", "account_id"), "foreign_account"),
            (("authority", "events", 0, "source_id"), "00000000-0000-4000-8000-000000000099"),
            (("authority", "events", 0, "issue_command_id"), "different_command"),
            (("authority", "events", 0, "result_sha256"), "0" * 64),
            (("authority", "events", 0, "origin"), "adopted_history"),
            (("authority", "events", 0, "sequence"), 2),
        )
        for path, replacement in mutations:
            with self.subTest(path=path):
                value = fixture()
                assign(value, path, replacement)
                self.rejects(value)
        value = fixture()
        value["authority"]["events"].pop()
        self.rejects(value)
        value = fixture()
        value["wires"][0], value["wires"][1] = value["wires"][1], value["wires"][0]
        self.rejects(value)

    def test_sources_are_complete_scoped_immutable_and_bounded(self) -> None:
        for kind in (
            "missing",
            "duplicate",
            "extra",
            "body",
            "scope",
            "dimensions",
            "boolean_length",
        ):
            with self.subTest(kind=kind):
                value = fixture()
                if kind == "missing":
                    value["sources"].pop()
                elif kind == "duplicate":
                    value["sources"].append(copy.deepcopy(value["sources"][0]))
                elif kind == "extra":
                    extra = copy.deepcopy(value["sources"][0])
                    extra["reference"]["source_id"] = "unused_source"
                    value["sources"].append(extra)
                elif kind == "body":
                    value["sources"][0]["body_utf8"] = "{}"
                elif kind == "scope":
                    value["sources"][0]["scope"]["account_id"] = "foreign_account"
                elif kind == "dimensions":
                    value["sources"][0]["reference"]["width"] = 1
                else:
                    value["sources"][0]["reference"]["byte_length"] = True
                self.rejects(value)

    def test_repaired_hashes_cannot_make_wrong_facts_or_model_provenance_valid(self) -> None:
        for kind in ("decision", "rule", "witness", "producer"):
            with self.subTest(kind=kind):
                value = fixture()
                result = json.loads(value["wires"][0]["result_utf8"])
                if kind == "decision":
                    result["eligible"] = False
                elif kind == "rule":
                    result["rule_refs"][0]["minimum_notice_days"] = 6
                elif kind == "witness":
                    result["fact_refs"][0]["fact_id"] = "unsupported_fact"
                else:
                    result["producer"].update(model_id="invented_model", model_version="1")
                replace_result(value, 0, result)
                self.rejects(value)

    def test_declared_negative_must_have_its_exact_fault_and_no_SQL_result(self) -> None:
        value = fixture()
        result = json.loads(value["wires"][4]["result_utf8"])
        result["eligible"] = True
        replace_result(value, 4, result)
        self.rejects(value)
        value = fixture()
        value["authority"]["records"][4]["result_sha256"] = value["peer"]["records"][4][
            "result_sha256"
        ]
        self.rejects(value)
        value = fixture()
        value["peer"]["records"][4]["peer"] = "public"
        self.rejects(value)

    def test_declared_bad_witness_cannot_alias_a_legitimate_source_fact(self) -> None:
        value = fixture()
        index = next(i for i, row in enumerate(value["wires"]) if row["label"] == "wrong_witness")
        row = value["wires"][index]
        accepted, issued, result = (
            json.loads(row[key]) for key in ("accepted_request_utf8", "request_utf8", "result_utf8")
        )
        source = copy.deepcopy(
            next(item for item in value["sources"] if item["reference"] == accepted["evidence"][1])
        )
        body = json.loads(source["body_utf8"])
        body["observations"][0]["fact_id"] = "notice_forged"

        def canonical(item: object) -> str:
            return json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

        def sha(item: str) -> str:
            return hashlib.sha256(item.encode()).hexdigest()

        source["body_utf8"] = canonical(body)
        source["reference"].update(
            source_id="facts_witness_control",
            sha256=sha(source["body_utf8"]),
            byte_length=len(source["body_utf8"].encode()),
        )
        value["sources"].append(source)
        for request in (accepted, issued):
            request["context_snapshot"]["facts_source_id"] = source["reference"]["source_id"]
            request["evidence"][1] = source["reference"]
            request["input_fingerprint"] = sha(
                canonical(
                    {
                        key: item
                        for key, item in request.items()
                        if key not in {"attempt", "input_fingerprint"}
                    }
                )
            )
        result["input_fingerprint"] = accepted["input_fingerprint"]
        result["fact_refs"][0].update(
            {key: source["reference"][key] for key in ("source_id", "version", "sha256")}
        )
        row.update(
            accepted_request_utf8=canonical(accepted),
            request_utf8=canonical(issued),
            result_utf8=canonical(result),
        )
        value["authority"]["records"][index].update(
            accepted_request_sha256=sha(row["accepted_request_utf8"]),
            input_fingerprint=accepted["input_fingerprint"],
        )
        value["peer"]["records"][index].update(
            input_fingerprint=accepted["input_fingerprint"],
            request_sha256=sha(row["request_utf8"]),
            result_sha256=sha(row["result_utf8"]),
        )
        # This original body is now factually valid. Its declared negative is absent.
        self.rejects(value)

    def test_database_time_cancel_and_read_only_witnesses(self) -> None:
        mutations = (
            (("authority", "clock_witnesses", "expired_valid", "db_now_ms"), 1),
            (("authority", "clock_witnesses", "postcommit_lease", "db_now_ms"), 1),
            (("authority", "read_snapshot_sha256", "after"), "0" * 64),
            (("authority", "supplier_observation", "apply_calls"), 1),
            (("authority", "supplier_observation", "inquiry_calls"), 1),
            (("authority", "supplier_observation", "final_sha256"), "0" * 64),
            (("authority", "cancellations", 0, "requested_at_ms"), 1),
            (("authority", "cancellations", 1, "disposition"), "already_terminal"),
            (("authority", "records", 0, "cancel_requested"), False),
        )
        for path, replacement in mutations:
            with self.subTest(path=path):
                value = fixture()
                assign(value, path, replacement)
                self.rejects(value)
        value = fixture()
        row = value["authority"]["records"][0]
        row["recorded_at_ms"] = row["deadline_at_ms"] + 1
        value["authority"]["events"][0]["recorded_at_ms"] = row["recorded_at_ms"]
        self.rejects(value)

    def test_database_and_receiver_wall_clocks_are_not_compared_as_authority(self) -> None:
        for offset in (-100, 100):
            with self.subTest(database_offset_ms=offset):
                value = fixture()
                for row in value["authority"]["records"]:
                    for field in (
                        "accepted_at_ms",
                        "issued_at_ms",
                        "lease_until_ms",
                        "recorded_at_ms",
                    ):
                        if row[field] is not None:
                            row[field] += offset
                for event in value["authority"]["events"]:
                    event["recorded_at_ms"] += offset
                for cancel in value["authority"]["cancellations"]:
                    cancel["requested_at_ms"] += offset
                # Absolute business deadlines are shared values. The DB-only lease
                # witness and its lease move together; receiver timestamps do not.
                lease = value["authority"]["clock_witnesses"]["postcommit_lease"]
                lease["lease_until_ms"] += offset
                lease["db_now_ms"] += offset
                self.assertEqual(run(value)["stored_results"], 8)

    def test_server_outcome_callback_is_not_a_client_receipt_timestamp(self) -> None:
        value = fixture()
        value["peer"]["records"][0]["returned_at_ms"] = value["wires"][0]["observed_at_ms"] + 1
        self.assertEqual(run(value)["stored_results"], 8)

    def test_commutative_witness_order_and_one_logical_owner_remain_valid(self) -> None:
        value = fixture()
        result = json.loads(value["wires"][2]["result_utf8"])
        result["fact_refs"].reverse()
        replace_result(value, 2, result)
        value["sources"].reverse()
        run(value)
        owner = value["authority"]["records"][0]["owner_id"]
        for row in value["authority"]["records"]:
            row["owner_id"] = owner
            row["command_id"] = "same_per_work_command"
        for event in value["authority"]["events"]:
            event["issue_command_id"] = "same_per_work_command"
        run(value)


if __name__ == "__main__":
    unittest.main()
