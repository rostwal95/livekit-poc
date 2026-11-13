"""Protocol proofs: real producer, shared wire fixtures and inert invalid payloads."""

import copy
import json
import unittest
from pathlib import Path

from channel_continuity import (
    AccountScope,
    ContractError,
    ProviderScope,
    TrustedPrincipal,
    parse_event_json,
    produce_text_event,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = json.loads((ROOT / "contracts/channel/v1.json").read_text())


def principal(value):
    provider = value["providerScope"]
    account = value.get("accountScope")
    return TrustedPrincipal(
        ProviderScope(provider["tenantId"], provider["provider"], provider["providerAccountId"]),
        AccountScope(account["tenantId"], account["accountId"]) if account else None,
    )


class ChannelCodecTests(unittest.TestCase):
    def setUp(self):
        self.event = copy.deepcopy(FIXTURES["valid"][0]["event"])
        self.principal = principal(FIXTURES["valid"][0]["principal"])

    def decode(self, event):
        return parse_event_json(json.dumps(event, ensure_ascii=True), self.principal)

    def test_actual_producer_matches_frozen_wire_and_identity(self):
        produced = produce_text_event(FIXTURES["producerInput"], self.principal)
        self.assertEqual(json.loads(produced.wire_json), self.event)
        self.assertEqual(produced.canonical, FIXTURES["valid"][0]["canonical"])
        self.assertEqual(produced.identity, FIXTURES["valid"][0]["identity"])

    def test_all_valid_variants_match_canonical_bytes_and_original_wire(self):
        for case in FIXTURES["valid"]:
            with self.subTest(case=case["name"]):
                result = parse_event_json(json.dumps(case["event"]), principal(case["principal"]))
                self.assertEqual(json.loads(result.wire_json), case["event"])
                self.assertEqual(result.canonical, case["canonical"])
                self.assertEqual(result.identity, case["identity"])

    def test_all_shared_invalid_wire_cases_have_fixed_payload_free_codes(self):
        for case in FIXTURES["invalid"]:
            with self.subTest(case=case["name"]):
                with self.assertRaises(ContractError) as raised:
                    parse_event_json(case["raw"], principal(case["principal"]))
                self.assertEqual(raised.exception.code, case["code"])
                self.assertEqual(str(raised.exception), case["code"])

    def test_retry_observations_preserve_semantics_and_original_event_identity(self):
        original = self.decode(self.event)
        self.event.update(
            receivedAt="2030-12-02T12:00:00.000Z", signature="new-observation", retryCount=2
        )
        retry = self.decode(self.event)
        self.assertEqual(original.canonical, retry.canonical)
        self.assertEqual(original.identity, retry.identity)
        self.assertNotEqual(original.wire_json, retry.wire_json)

    def test_semantic_payload_destination_and_occurrence_changes_conflict(self):
        original = self.decode(self.event)
        for key, value in [
            ("body", "different"),
            ("conversationId", "other-conversation"),
            ("caseId", "other-case"),
            ("occurredAt", "2030-12-01T09:00:00.000Z"),
            ("expectedCaseRevision", 1),
        ]:
            changed = copy.deepcopy(self.event)
            changed[key] = value
            result = self.decode(changed)
            self.assertEqual(original.identity, result.identity)
            self.assertNotEqual(original.canonical, result.canonical)

    def test_identical_text_under_new_event_identity_remains_distinct(self):
        first = self.decode(self.event)
        self.event["eventId"] = "event-new"
        second = self.decode(self.event)
        self.assertNotEqual(first.identity, second.identity)
        self.assertNotEqual(first.canonical, second.canonical)

    def test_exact_utf8_text_boundary_and_positive_progress_after_rejection(self):
        self.event["body"] = "🧭" * 1024
        result = self.decode(self.event)
        self.assertEqual(result.event["body"], self.event["body"])
        self.event["body"] += "x"
        with self.assertRaises(ContractError):
            self.decode(self.event)
        self.event["body"] = "valid follow-up"
        self.assertEqual(self.decode(self.event).event["body"], "valid follow-up")

    def test_output_is_deeply_immutable_and_does_not_alias_input(self):
        result = self.decode(self.event)
        self.event["providerScope"]["tenantId"] = "changed"
        with self.assertRaises(TypeError):
            result.event["providerScope"]["tenantId"] = "changed"
        with self.assertRaises(AttributeError):
            result.canonical = "changed"
        self.assertIn("tenant-demo", result.canonical)

    def test_provider_identity_does_not_grant_business_account_or_case_authority(self):
        provider_only = TrustedPrincipal(self.principal.provider_scope)
        with self.assertRaises(ContractError) as raised:
            parse_event_json(json.dumps(self.event), provider_only)
        self.assertEqual(raised.exception.code, "AccessDenied")
        self.event.pop("accountScope")
        with self.assertRaises(ContractError) as raised:
            parse_event_json(json.dumps(self.event), provider_only)
        self.assertEqual(raised.exception.code, "AssociationRequired")
        self.event.pop("caseId")
        self.assertEqual(
            parse_event_json(json.dumps(self.event), provider_only).event["type"], "text.received"
        )

    def test_producer_runtime_malformed_and_cyclic_values_are_sanitized(self):
        cyclic = {}
        cyclic["cycle"] = cyclic
        values = [
            None,
            [],
            "secret",
            cyclic,
            {"body": object()},
            {"body": "\ud800"},
            {"body": float("nan")},
            {"body": 1.5},
            {"extra": None, "type": "text.received"},
        ]
        for value in values:
            with self.subTest(kind=type(value).__name__):
                with self.assertRaises(ContractError) as raised:
                    produce_text_event(value, self.principal)
                self.assertEqual(str(raised.exception), "InvalidEvent")

    def test_shared_child_amplification_and_aggregate_text_are_bounded(self):
        shared = {"text": "bounded"}
        for _ in range(6):
            shared = {f"child{index}": shared for index in range(64)}
        with self.assertRaises(ContractError):
            produce_text_event(shared, self.principal)
        with self.assertRaises(ContractError):
            produce_text_event({f"part{index}": "a" * 4096 for index in range(9)}, self.principal)
        with self.assertRaises(ContractError):
            produce_text_event({"body": "a" * 1000000}, self.principal)
        self.assertEqual(
            produce_text_event(FIXTURES["producerInput"], self.principal).canonical,
            FIXTURES["valid"][0]["canonical"],
        )

    def test_exact_raw_wire_byte_limit_accepts_then_rejects_one_extra_byte(self):
        raw = self.decode(self.event).wire_json
        bounded = raw + " " * (32768 - len(raw.encode("utf-8")))
        self.assertEqual(
            parse_event_json(bounded, self.principal).canonical, self.decode(self.event).canonical
        )
        with self.assertRaises(ContractError):
            parse_event_json(bounded + " ", self.principal)

    def test_raw_wire_bound_deep_nesting_and_duplicate_escapes_are_rejected(self):
        for raw in [
            " " * 32769,
            "[" * 5000 + "]" * 5000,
            '{"a":{"a":{"a":{"a":{"a":{"a":{"a":{"a":{"a":1}}}}}}}}}',
        ]:
            with self.subTest(raw_size=len(raw)), self.assertRaises(ContractError):
                parse_event_json(raw, self.principal)

    def test_trusted_scope_configuration_rejects_malformed_and_cross_tenant_values(self):
        for suffix in ["\n", "\r", "\u2028", "\u2029"]:
            with self.assertRaises(ContractError):
                ProviderScope("tenant-demo", "fake_sms", "provider-demo" + suffix)
        with self.assertRaises(ContractError):
            TrustedPrincipal(
                self.principal.provider_scope, AccountScope("other-tenant", "account-demo")
            )
        with self.assertRaises(ContractError):
            parse_event_json(json.dumps(self.event), None)


if __name__ == "__main__":
    unittest.main()
