"""Independent original-receipt and owned-work deletion counterexamples, offline."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "local-setup/scripts"))
import p2_rehydration_check as gate

STAMP = "2026-11-11T10:20:30.123Z"
SQL_STAMP = "2026-11-11T10:20:30.123+00:00"
UID = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"


class OriginalReceiptTests(unittest.TestCase):
    def history(self):
        row = {
            "receipt_id": UID,
            "event_id": "event-1",
            "message_id": "message-1",
            "acceptance_sequence": 1,
            "accepted_at": SQL_STAMP,
        }
        receipt = {
            "receiptId": UID,
            "eventId": "event-1",
            "messageId": "message-1",
            "acceptanceSequence": "1",
            "acceptedAt": STAMP,
        }
        return row, receipt

    def response(self):
        row = {
            "response_id": UID,
            "receipt_id": OTHER,
            "anchor_digest": "a" * 64,
            "response_sequence": 2,
            "accepted_at": SQL_STAMP,
        }
        receipt = {
            "responseId": UID,
            "receiptId": OTHER,
            "anchorDigest": "a" * 64,
            "responseSequence": "2",
            "acceptedAt": STAMP,
        }
        return row, receipt

    def test_original_history_receipt_exact_SQL_identity(self):
        row, r = self.history()
        gate.validate_original_receipt(r, row, "history")

    def test_original_response_receipt_exact_SQL_identity(self):
        row, r = self.response()
        gate.validate_original_receipt(r, row, "response")

    def test_altered_valid_history_time_or_sequence_cannot_borrow_receipt(self):
        row, r = self.history()
        for key, value in (
            ("acceptedAt", "2026-11-11T10:20:31.123Z"),
            ("acceptanceSequence", "2"),
            ("receiptId", OTHER),
            ("eventId", "other"),
            ("messageId", "other"),
        ):
            with self.subTest(key=key), self.assertRaises(gate.GateError):
                gate.validate_original_receipt({**r, key: value}, row, "history")

    def test_altered_valid_response_receipt_cannot_borrow_anchor(self):
        row, r = self.response()
        for key, value in (
            ("acceptedAt", "2026-11-11T10:20:31.123Z"),
            ("responseSequence", "3"),
            ("receiptId", UID),
            ("responseId", OTHER),
            ("anchorDigest", "b" * 64),
        ):
            with self.subTest(key=key), self.assertRaises(gate.GateError):
                gate.validate_original_receipt({**r, key: value}, row, "response")

    def test_receipt_extra_fields_and_numeric_aliases_rejected(self):
        row, r = self.history()
        for changed in (
            {**r, "extra": "private"},
            {**r, "acceptanceSequence": 1},
            {**r, "acceptedAt": SQL_STAMP},
        ):
            with self.assertRaises(gate.GateError):
                gate.validate_original_receipt(changed, row, "history")

    def test_sql_instant_requires_timezone_and_preserves_milliseconds(self):
        self.assertEqual(gate.sql_instant(SQL_STAMP), STAMP)
        for value in (None, True, 123, "2026-11-11T10:20:30.123", "bad"):
            with self.subTest(value=value), self.assertRaises(gate.GateError):
                gate.sql_instant(value)


class OwnedWorkTests(unittest.TestCase):
    def test_matching_private_marker_permits_only_own_work(self):
        with tempfile.TemporaryDirectory() as temporary:
            scratch = Path(temporary).resolve()
            work = scratch / "run-abcdef12"
            work.mkdir(mode=0o700)
            gate.native.write_json(
                work / "rehydration-owned-work.json",
                {"schemaVersion": 1, "schema": "p2_rehydration_" + "a" * 32},
            )
            gate.remove_owned_work(work, scratch, "p2_rehydration_" + "a" * 32)
            self.assertFalse(work.exists())

    def test_wrong_marker_never_removes_supplier(self):
        with tempfile.TemporaryDirectory() as temporary:
            scratch = Path(temporary).resolve()
            work = scratch / "run-abcdef12"
            work.mkdir(mode=0o700)
            supplier = work / "supplier.sqlite3"
            supplier.write_bytes(b"private fixture")
            gate.native.write_json(
                work / "rehydration-owned-work.json", {"schemaVersion": 1, "schema": "foreign"}
            )
            with self.assertRaises(gate.GateError):
                gate.remove_owned_work(work, scratch, "p2_rehydration_" + "a" * 32)
            self.assertEqual(supplier.read_bytes(), b"private fixture")

    def test_foreign_parent_or_symlink_work_never_deleted(self):
        with tempfile.TemporaryDirectory() as temporary:
            scratch = Path(temporary).resolve()
            work = scratch / "run-abcdef12"
            work.mkdir(mode=0o700)
            link = scratch / "run-linked12"
            link.symlink_to(work, target_is_directory=True)
            for candidate, parent in ((link, scratch), (work, scratch / "foreign")):
                with self.assertRaises(gate.GateError):
                    gate.remove_owned_work(candidate, parent, "p2_rehydration_" + "a" * 32)
            self.assertTrue(work.exists())


class ReviewCounterexamples(unittest.TestCase):
    def test_huge_valid_JSON_integer_is_fixed_report_failure(self):
        # A4001-digit JSON integer is within the interpreter's JSON limit but
        # cannot be converted to a finite float. Reject before math.isfinite.
        current = {
            "schema_version": 1,
            "status": "passed",
            "mode": "local_synthetic_p2_rehydration",
            "tests": 18,
            "passed": 18,
            "errors": 0,
            "failures": 0,
            "skipped": 0,
            "case_results": [
                {"name": n, "status": "passed", "code": "ok"} for n in gate.CASE_NAMES
            ],
            "cleanup_complete": True,
            "schema_version_observed": 7,
            "owned_child_terminations": 1,
            "blocking_graphs_observed": 1,
            "populated_restore_verified": True,
            "actual_p1_supplier_apply_calls": 1,
            "provider_calls": False,
            "actual_browser_qualification_claimed": False,
            "human_acknowledgement_claimed": False,
            "node_version": "24.22.2",
            "child_commands": 18,
            "retained_index_sha256": "a" * 64,
        }
        current["duration_seconds"] = 10**4000
        with self.assertRaises(gate.GateError):
            gate.validated_report(json.dumps(current).encode())

    def test_manifest_may_never_invent_a_self_descriptor(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary).resolve()
            (folder / "source.json").write_text("{}")
            gate.retained_index(folder)
            target = folder / "retained-index.json"
            value = json.loads(target.read_bytes())
            value["files"]["retained-index.json"] = {"bytes": 0, "sha256": "0" * 64}
            target.write_text(json.dumps(value))
            target.chmod(0o600)
            with self.assertRaises(gate.GateError):
                gate.validate_retained_index(
                    folder, hashlib.sha256(target.read_bytes()).hexdigest()
                )


if __name__ == "__main__":
    unittest.main()
