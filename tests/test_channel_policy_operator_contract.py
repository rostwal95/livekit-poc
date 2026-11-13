"""Closed original command and honest source-qualified observation contracts."""

from __future__ import annotations

import dataclasses
import json
import unittest
from uuid import uuid4

from services.channel_policy_demo import operator_contract as m
from services.channel_policy_demo.discovery import DiscoveryItem, DiscoveryPage, DiscoveryScope

NOW = "2026-11-13T09:00:00.000Z"


def command():
    return m.SmsCommand(str(uuid4()), NOW, "Investigate this change 🧭 e\u0301")


def page(items=(), **changes):
    values = {
        "profile_id": str(uuid4()),
        "scope": DiscoveryScope("tenant_demo", "account_demo"),
        "case_id": "case_demo",
        "conversation_id": "conversation_demo",
        "read_completed_at": NOW,
        "items": items,
        "overflow": False,
        "next_cursor": None,
    }
    values.update(changes)
    return DiscoveryPage(**values)


class OperatorContractTests(unittest.TestCase):
    def test_original_sms_roundtrip_and_identity_are_stable(self):
        c = command()
        self.assertEqual(m.parse_sms_command(m.encode(c.payload())), c)
        self.assertEqual(c.event_id, "cp_sms_" + c.command_id.replace("-", ""))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            c.body = "changed"

    def test_sms_rejects_unauthorized_selectors_and_duplicate_fields(self):
        c = command().payload()
        for name in ("senderId", "scope", "port", "provider", "expectedRevision"):
            with self.subTest(name=name), self.assertRaises(m.OperatorError):
                m.parse_sms_command(m.encode(c | {name: "foreign"}))
        with self.assertRaises(m.OperatorError):
            m.parse_sms_command(m.encode(c)[:-1] + b',"schemaVersion":1}')

    def test_byte_limit_is_utf8_and_body_cannot_be_empty_or_surrogate(self):
        c = command()
        self.assertEqual(
            len(m.SmsCommand(c.command_id, NOW, "\U0001f9ed" * 1024).body.encode()), 4096
        )
        for value in ("", "\U0001f9ed" * 1025, "x\0y", "\ud800", None, True):
            with self.subTest(value=repr(value)[:20]), self.assertRaises(m.OperatorError):
                m.SmsCommand(c.command_id, NOW, value)

    def test_flat_json_bounds_and_version_are_strict(self):
        c = command().payload()
        for raw in (b"", b"[]", b"null", b"{", b"\xff", b'{"value":NaN}', b" " * 32769):
            with self.subTest(raw=raw[:16]), self.assertRaises(m.OperatorError):
                m.parse_sms_command(raw)
        for value in (True, 1.0, "1", 2):
            with self.subTest(version=value), self.assertRaises(m.OperatorError):
                m.parse_sms_command(m.encode(c | {"schemaVersion": value}))

    def test_original_command_requires_uuid4_and_canonical_time(self):
        c = command()
        for value in (str(uuid4()).upper(), "123", "00000000-0000-1000-8000-000000000001"):
            with self.subTest(identity=value), self.assertRaises(m.OperatorError):
                m.SmsCommand(value, NOW, "text")
        for value in (
            "2026-02-30T09:00:00.000Z",
            NOW.replace(".000", ""),
            NOW.replace("Z", "+00:00"),
        ):
            with self.subTest(time=value), self.assertRaises(m.OperatorError):
                m.SmsCommand(c.command_id, value, "text")

    def test_receipt_must_bind_both_provider_identities_to_original_command(self):
        c = command()
        good = m.SmsObservation(c.command_id, False, str(uuid4()), c.event_id, c.event_id, "1", NOW)
        self.assertEqual(good.payload()["receipt"]["eventId"], c.event_id)
        for changes in (
            {"event_id": "foreign"},
            {"message_id": "foreign"},
            {"replayed": 1},
            {"acceptance_sequence": "0"},
        ):
            with self.subTest(changes=changes), self.assertRaises(m.OperatorError):
                dataclasses.replace(good, **changes)

    def test_case_observation_is_separate_and_zero_is_readable(self):
        self.assertEqual(
            m.CaseObservation("0", NOW).payload(),
            {"schemaVersion": 1, "case": {"revision": "0", "observedAt": NOW}},
        )
        for value in (1, True, "01", "-1", "9223372036854775808"):
            with self.subTest(revision=value), self.assertRaises(m.OperatorError):
                m.CaseObservation(value, NOW)

    def test_progress_counts_original_sources_and_dispatch_not_completion(self):
        items = (
            DiscoveryItem(str(uuid4()), str(uuid4()), "1", "native", "pending", False, None),
            DiscoveryItem(str(uuid4()), str(uuid4()), "2", "sms", "dispatched", True, str(uuid4())),
            DiscoveryItem(str(uuid4()), str(uuid4()), "3", "sms", "uncertain", True, None),
        )
        observed = m.progress_observation(page(items))
        self.assertEqual(
            observed.payload(),
            {
                "schemaVersion": 1,
                "asOf": NOW,
                "counts": {
                    "native": 1,
                    "sms": 2,
                    "pending": 1,
                    "running": 0,
                    "dispatched": 1,
                    "blocked": 0,
                    "exhausted": 0,
                    "uncertain": 1,
                    "workKnown": 1,
                },
            },
        )
        self.assertNotIn("completed", json.dumps(observed.payload()))

    def test_overflow_is_not_a_partial_success(self):
        with self.assertRaises(m.OperatorError) as caught:
            m.progress_observation(
                page(
                    tuple(
                        DiscoveryItem(
                            str(uuid4()), str(uuid4()), str(i + 1), "native", "pending", False, None
                        )
                        for i in range(16)
                    ),
                    overflow=True,
                    next_cursor="16",
                )
            )
        self.assertEqual(caught.exception.code, "capacity")

    def test_progress_rejects_impossible_counts(self):
        valid = m.ProgressObservation(NOW, 1, 0, 1, 0, 0, 0, 0, 0, 0)
        for changes in (
            {"native": True},
            {"sms": 17},
            {"work_known": 1},
            {"pending": 0},
            {"running": -1},
        ):
            with self.subTest(changes=changes), self.assertRaises(m.OperatorError):
                dataclasses.replace(valid, **changes)

    def test_empty_commands_reject_body_authority(self):
        m.parse_empty(b'{"schemaVersion":1}')
        for raw in (
            b'{"schemaVersion":true}',
            b'{"schemaVersion":1,"scope":{}}',
            b'{"schemaVersion":1,"schemaVersion":1}',
        ):
            with self.subTest(raw=raw), self.assertRaises(m.OperatorError):
                m.parse_empty(raw)

    def test_errors_do_not_reflect_unknown_inputs(self):
        error = m.OperatorError("PRIVATE_BACKEND_SENTINEL")
        self.assertEqual(str(error), "unavailable")
        self.assertNotIn("PRIVATE", repr(error))


if __name__ == "__main__":
    unittest.main()
