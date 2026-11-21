"""Actual P2 producer bytes and negative wire controls; no external services."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

from services.channel_policy_demo import wire as m

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / "contracts/delegation/channel-policy-v3.json").read_bytes())


def encoded(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def canonical_submission(value: dict[str, object]) -> tuple[str, str]:
    raw = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    return raw, hashlib.sha256(raw.encode()).hexdigest()


class ProducerWireTests(unittest.TestCase):
    def test_actual_ts_producer_canonical_and_http_frames_round_trip_without_narrowing(self):
        self.assertEqual(len(FIXTURE["p2_cases"]), 3)
        for case in FIXTURE["p2_cases"]:
            with self.subTest(case=case["name"]):
                parsed = m.parse_accept_frame(case["accept_frame_canonical"].encode())
                self.assertEqual(parsed.to_submission_wire(), case["submission"])
                self.assertEqual(parsed.canonical_payload, case["payload_canonical"])
                self.assertEqual(
                    m.json_text(parsed.to_submission_wire()), case["payload_canonical"]
                )
                self.assertEqual(parsed.payload_sha256, case["payload_sha256"])
                self.assertEqual(parsed.payload_byte_length, case["payload_byte_length"])
                self.assertEqual(
                    parsed.payload_sha256,
                    hashlib.sha256(parsed.canonical_payload.encode()).hexdigest(),
                )
                self.assertEqual(
                    m.parse_lookup_frame(encoded(parsed.lookup().to_wire())), parsed.lookup()
                )
                self.assertGreaterEqual(m.require_p3_compatible(parsed), 1)
                self.assertLessEqual(case["accept_frame_byte_length"], m.FRAME_BYTES)
        maximum = m.parse_accept_frame(FIXTURE["p2_cases"][2]["accept_frame_canonical"].encode())
        self.assertEqual(len(maximum.sender_id), 128)
        self.assertEqual(len(maximum.event_id), 128)
        self.assertEqual(len(maximum.message_id), 128)
        self.assertEqual(m.require_p3_compatible(maximum), 1000000)

    def test_shared_channel_wrapper_binds_original_bytes_without_copying_message_body(self):
        originals = {case["name"]: case for case in FIXTURE["p2_cases"]}
        wrappers = {case["name"]: case for case in FIXTURE["channel_cases"]}
        self.assertEqual(set(wrappers), set(originals))
        for name, case in wrappers.items():
            with self.subTest(case=name):
                original = originals[name]
                parsed = m.parse_accept_frame(original["accept_frame_canonical"].encode())
                request = json.loads(case["request_canonical"])
                nested = request["request"]
                self.assertEqual(
                    request["origin"],
                    {
                        "kind": "p2.prepared_dispatch.v1",
                        "profile_id": FIXTURE["profile_id"],
                        "operation_key": parsed.operation_key,
                        "input_receipt_id": parsed.input_receipt_id,
                        "payload_sha256": parsed.payload_sha256,
                        "payload_byte_length": parsed.payload_byte_length,
                    },
                )
                self.assertEqual(
                    nested["scope"],
                    {"tenant_id": parsed.scope.tenant_id, "account_id": parsed.scope.account_id},
                )
                self.assertEqual(nested["case_id"], parsed.case_id)
                self.assertEqual(nested["result_route"]["conversation_id"], parsed.conversation_id)
                self.assertEqual(nested["request_revision"], m.require_p3_compatible(parsed))
                self.assertEqual(
                    nested["delegation_id"], "p2_" + parsed.operation_key.replace("-", "")
                )
                self.assertNotIn("message", nested)
                self.assertNotIn("body", nested)
                for kind, limit in (("request", 16384), ("result", 8192)):
                    raw = case[kind + "_canonical"].encode()
                    self.assertEqual(len(raw), case[kind + "_bytes"])
                    self.assertLessEqual(len(raw), limit)
                    self.assertEqual(hashlib.sha256(raw).hexdigest(), case[kind + "_sha256"])
                    self.assertEqual(
                        json.dumps(
                            json.loads(raw),
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode(),
                        raw,
                    )
        self.assertGreater(originals["nul_bound"]["payload_byte_length"], 16384)
        self.assertLess(wrappers["nul_bound"]["request_bytes"], 16384)

    def test_shared_negative_frames_fail_at_declared_pre_authority_stage(self):
        expected = {
            "boolean_frame_version": ("parse", "InvalidCommand"),
            "unknown_frame_field": ("parse", "InvalidCommand"),
            "duplicate_frame_key": ("parse", "InvalidCommand"),
            "wrong_original_sha": ("parse", "IdentityConflict"),
            "changed_original_same_sha": ("parse", "IdentityConflict"),
            "unpaired_body_surrogate": ("parse", "InvalidCommand"),
            "body_over_utf8_cap": ("parse", "InvalidCommand"),
            "revision_above_p3": ("intersection", "InvalidCommand"),
            "foreign_route": ("route", "unauthorized"),
        }
        cases = FIXTURE["negative_accept_frames"]
        self.assertEqual({case["name"] for case in cases}, set(expected))
        self.assertEqual(len(cases), len(expected))
        original = m.parse_accept_frame(FIXTURE["p2_cases"][0]["accept_frame_canonical"].encode())
        for case in cases:
            with self.subTest(case=case["name"]):
                self.assertEqual((case["stage"], case["code"]), expected[case["name"]])
                frame = case["frame"].encode()
                if case["stage"] == "parse":
                    with self.assertRaises(m.OriginWireError) as caught:
                        m.parse_accept_frame(frame)
                    self.assertEqual(caught.exception.code, case["code"])
                else:
                    parsed = m.parse_accept_frame(frame)
                    if case["stage"] == "intersection":
                        with self.assertRaises(m.OriginWireError) as caught:
                            m.require_p3_compatible(parsed)
                        self.assertEqual(caught.exception.code, case["code"])
                    else:
                        # Wire validity grants no route authority; the application owns that check.
                        self.assertEqual(m.require_p3_compatible(parsed), 1)
                        self.assertEqual(parsed.scope, original.scope)
                        self.assertEqual(parsed.conversation_id, original.conversation_id)
                        self.assertNotEqual(parsed.case_id, original.case_id)
                        self.assertNotEqual(parsed.payload_sha256, original.payload_sha256)

    def test_nul_payload_and_enclosing_frame_are_distinct_bounded_original_bytes(self):
        case = FIXTURE["p2_cases"][2]
        parsed = m.parse_accept_frame(case["accept_frame_canonical"].encode())
        self.assertEqual(parsed.body, "\0" * 4096)
        self.assertEqual(parsed.payload_byte_length, 25523)
        self.assertEqual(case["accept_frame_byte_length"], 29797)
        self.assertGreater(case["accept_frame_byte_length"], parsed.payload_byte_length)
        for raw in (b"x" * 32769, b"", b"[]", b"null", b"\xff", b'{"schemaVersion":NaN}'):
            with self.subTest(size=len(raw)), self.assertRaises(m.OriginWireError):
                m.parse_accept_frame(raw)

    def test_duplicate_unknown_or_noncanonical_keys_and_wrong_digest_reject_even_with_valid_sha(
        self,
    ):
        original = FIXTURE["p2_cases"][0]["payload_canonical"]
        mutants = [
            " " + original,
            original.replace('"schemaVersion":1', '"schemaVersion":1,"schemaVersion":1', 1),
            original.replace('"schemaVersion":1', '"schemaVersion":true', 1),
            original.replace('"schemaVersion":1', '"schemaVersion":1.0', 1),
            original.replace('"kind":"investigation"', '"kind":"investigation","extra":0', 1),
            original.replace(
                '"tenantId":"tenant_fixed"',
                '"tenantId":"tenant_fixed","tenantId":"tenant_fixed"',
                1,
            ),
            original.replace('"receiptId":', '"unexpected":0,"receiptId":', 1),
        ]
        reordered = json.loads(original)
        reordered = {"kind": reordered.pop("kind"), **reordered}
        mutants.append(json.dumps(reordered, separators=(",", ":")))
        for payload in mutants:
            with (
                self.subTest(control=hashlib.sha256(payload.encode()).hexdigest()),
                self.assertRaises(m.OriginWireError),
            ):
                m.parse_prepared_payload(payload, hashlib.sha256(payload.encode()).hexdigest())
        with self.assertRaises(m.OriginWireError) as caught:
            m.parse_prepared_payload(original, "0" * 64)
        self.assertEqual(caught.exception.code, "IdentityConflict")
        for digest in (None, True, "F" * 64, "1" * 63):
            with (
                self.subTest(digest_type=type(digest).__name__),
                self.assertRaises(m.OriginWireError),
            ):
                m.parse_prepared_payload(original, digest)

    def test_p2_revision_domain_is_preserved_and_p3_intersection_never_coerces_zero_or_overflow(
        self,
    ):
        base = copy.deepcopy(FIXTURE["p2_cases"][0]["submission"])
        for revision in ("1", "1000000", "1000001", "9223372036854775807"):
            candidate = {**base, "caseRevision": revision}
            payload, digest = canonical_submission(candidate)
            parsed = m.parse_prepared_payload(payload, digest)
            self.assertEqual(parsed.case_revision, revision)
            if int(revision) <= 1000000:
                self.assertEqual(m.require_p3_compatible(parsed), int(revision))
            else:
                with self.assertRaises(m.OriginWireError):
                    m.require_p3_compatible(parsed)
        for revision in ("0", "01", "-1", "9223372036854775808", 1, True, "1e3"):
            payload, digest = canonical_submission({**base, "caseRevision": revision})
            with self.subTest(revision=revision), self.assertRaises(m.OriginWireError):
                m.parse_prepared_payload(payload, digest)
        valid = m.parse_accept_frame(FIXTURE["p2_cases"][0]["accept_frame_canonical"].encode())
        with self.assertRaises(m.OriginWireError) as caught:
            m.require_p3_compatible(replace(valid, case_revision="PRIVATE_REVISION_SENTINEL"))
        self.assertNotIn("PRIVATE", str(caught.exception))

    def test_only_ids_mapped_to_p3_use_its_intersection_without_truncation_or_case_folding(self):
        base = copy.deepcopy(FIXTURE["p2_cases"][0]["submission"])
        for field in ("caseId", "conversationId"):
            for identifier in ("A_valid_p2", "n" * 65, "namespace:case"):
                candidate = {**base, field: identifier}
                payload, digest = canonical_submission(candidate)
                parsed = m.parse_prepared_payload(payload, digest)
                self.assertEqual(parsed.to_submission_wire()[field], identifier)
                with (
                    self.subTest(field=field, identifier=identifier),
                    self.assertRaises(m.OriginWireError),
                ):
                    m.require_p3_compatible(parsed)
        for key in ("tenantId", "accountId"):
            candidate = {**base, "scope": {**base["scope"], key: "A_valid_p2"}}
            payload, digest = canonical_submission(candidate)
            parsed = m.parse_prepared_payload(payload, digest)
            with self.assertRaises(m.OriginWireError):
                m.require_p3_compatible(parsed)
        for identifier in ("n" * 129, "spaces forbidden", "é"):
            payload, digest = canonical_submission({**base, "caseId": identifier})
            with self.assertRaises(m.OriginWireError):
                m.parse_prepared_payload(payload, digest)

    def test_body_utf8_bound_and_unpaired_surrogate_reject_before_any_source_authority(self):
        base = copy.deepcopy(FIXTURE["p2_cases"][0]["submission"])
        for body in ("", "x" * 4096, "😀" * 1024):
            candidate = copy.deepcopy(base)
            candidate["message"]["body"] = body
            # JSON.stringify emits Unicode directly; noncanonical ASCII escapes are not accepted.
            payload = json.dumps(candidate, ensure_ascii=False, separators=(",", ":"))
            parsed = m.parse_prepared_payload(payload, hashlib.sha256(payload.encode()).hexdigest())
            self.assertEqual(parsed.body, body)
        for body in ("x" * 4097, "😀" * 1025, "\ud800", "\udfff", 1, None):
            candidate = copy.deepcopy(base)
            candidate["message"]["body"] = body
            payload, digest = canonical_submission(candidate)
            with self.subTest(body_type=type(body).__name__), self.assertRaises(m.OriginWireError):
                m.parse_prepared_payload(payload, digest)

    def test_invalid_uuid_version_case_and_unknown_message_fields_are_closed(self):
        base = copy.deepcopy(FIXTURE["p2_cases"][0]["submission"])
        for identifier in (
            "11111111-1111-1111-8111-111111111111",
            "ABCDEF12-3456-4789-8ABC-ABCDEF123456",
            "not-a-uuid",
            True,
        ):
            candidate = {**base, "operationKey": identifier}
            payload, digest = canonical_submission(candidate)
            with (
                self.subTest(identifier_type=type(identifier).__name__),
                self.assertRaises(m.OriginWireError),
            ):
                m.parse_prepared_payload(payload, digest)
        candidate = copy.deepcopy(base)
        candidate["message"]["extra"] = "PRIVATE_EXTRA_SENTINEL"
        payload, digest = canonical_submission(candidate)
        with self.assertRaises(m.OriginWireError) as caught:
            m.parse_prepared_payload(payload, digest)
        self.assertEqual(caught.exception.args, ("InvalidCommand",))
        self.assertNotIn("PRIVATE", repr(caught.exception))

    def test_lookup_and_profile_frames_require_exact_independent_shapes(self):
        p = m.parse_accept_frame(FIXTURE["p2_cases"][0]["accept_frame_canonical"].encode())
        lookup = p.lookup().to_wire()
        self.assertEqual(m.parse_lookup_frame(encoded(lookup)), p.lookup())
        self.assertEqual(
            m.parse_profile_frame(
                encoded({"schemaVersion": 1, "profileId": FIXTURE["profile_id"]})
            ),
            FIXTURE["profile_id"],
        )
        invalid_lookup = [
            {**lookup, "schemaVersion": 1},
            {**lookup, "payloadDigest": None},
            {**lookup, "scope": {}},
            {**lookup, "operationKey": "bad"},
        ]
        for value in invalid_lookup:
            with self.assertRaises(m.OriginWireError):
                m.parse_lookup_frame(encoded(value))
        for value in (
            {"schemaVersion": True, "profileId": FIXTURE["profile_id"]},
            {"schemaVersion": 1, "profileId": "bad"},
            {"schemaVersion": 1, "profileId": FIXTURE["profile_id"], "extra": 1},
        ):
            with self.assertRaises(m.OriginWireError):
                m.parse_profile_frame(encoded(value))
        with self.assertRaises(m.OriginWireError):
            m.parse_lookup_frame(b" " * 1025)

    def test_closed_frames_and_safe_frozen_data_do_not_reflect_private_message_text(self):
        frame = json.loads(FIXTURE["p2_cases"][0]["accept_frame_canonical"])
        for change in (
            {"schemaVersion": True},
            {"extra": 1},
            {"canonicalPayload": {}},
            {"payloadDigest": "PRIVATE_TOKEN_SENTINEL"},
        ):
            with self.assertRaises(m.OriginWireError) as caught:
                m.parse_accept_frame(encoded({**frame, **change}))
            self.assertNotIn("PRIVATE", str(caught.exception))
        candidate = copy.deepcopy(FIXTURE["p2_cases"][0]["submission"])
        candidate["message"]["body"] = "PRIVATE_BODY_SENTINEL"
        payload, digest = canonical_submission(candidate)
        parsed = m.parse_prepared_payload(payload, digest)
        self.assertNotIn("PRIVATE_BODY", repr(parsed))
        with self.assertRaises(FrozenInstanceError):
            parsed.case_id = "changed"

    def test_import_starts_no_socket_process_or_background_task(self):
        code = """import asyncio,json,socket
from unittest.mock import patch
with patch.object(socket.socket,"connect",side_effect=AssertionError("network")),patch.object(socket.socket,"bind",side_effect=AssertionError("listener")),patch("subprocess.Popen",side_effect=AssertionError("process")),patch.object(asyncio,"create_task",side_effect=AssertionError("background task")):
    from services.channel_policy_demo import wire,origin,origin_http
assert wire.FRAME_BYTES==32768
print(json.dumps({"inert":True}))
"""
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", code, str(ROOT)],
            cwd="/private/tmp",
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"inert": True})


if __name__ == "__main__":
    unittest.main()
