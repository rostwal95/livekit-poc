"""Versioned exact consent preserves legacy bytes and immutable supplier binding."""

import json
import unittest
from dataclasses import replace
from datetime import date
from itertools import combinations
from uuid import uuid4

from continuity_lab.case_models import (
    MAX_INTEGER,
    ActionIntent,
    Confirmation,
    InvalidConfirmation,
    QuoteSnapshot,
    canonical,
    parse_confirmation,
    parse_intent,
    parse_quote,
    require_mutation_quote,
)
from continuity_lab.execution_models import UnsupportedOperation


class MutationContractTests(unittest.TestCase):
    def quote(self, version=2, **changes):
        values = {
            "quote_id": "10000000-0000-0000-0000-000000000001",
            "task_id": "legacy-task",
            "revision": 0,
            "booking_reference": "DEMO-BK-001",
            "new_check_in": date(2030, 12, 10),
            "amount_minor": 1250,
            "currency": "USD",
            "expires_at": "2030-12-01T00:10:00+00:00",
        }
        if version == 2:
            values.update(
                case_id="20000000-0000-0000-0000-000000000002",
                supplier_id="30000000-0000-0000-0000-000000000003",
                expected_supplier_revision=4,
            )
        return QuoteSnapshot(**(values | changes))

    def intent(self, quote):
        return ActionIntent(
            "40000000-0000-0000-0000-000000000004",
            quote.task_id,
            "account-a",
            "traveller-a",
            quote.revision,
            quote,
            "50000000-0000-0000-0000-000000000005",
            "60000000-0000-0000-0000-000000000006",
            "70000000-0000-0000-0000-000000000007",
            "2030-12-01T00:01:00+00:00",
        )

    def test_literal_v1_quote_confirmation_and_intent_bytes_remain_unchanged(self):
        quote_bytes = (
            '{"amount_minor":1250,"booking_reference":"DEMO-BK-001","currency":"USD",'
            '"expires_at":"2030-12-01T00:10:00+00:00","new_check_in":"2030-12-10",'
            '"quote_id":"10000000-0000-0000-0000-000000000001","revision":0,'
            '"schema_version":1,"task_id":"legacy-task"}'
        )
        confirmation_bytes = '{"explicit":true,"quote":' + quote_bytes + ',"schema_version":1}'
        intent_bytes = (
            '{"actor_id":"traveller-a","confirmation_id":"50000000-0000-0000-0000-000000000005",'
            '"created_at":"2030-12-01T00:01:00+00:00",'
            '"dispatch_event_id":"70000000-0000-0000-0000-000000000007",'
            '"effect_id":"60000000-0000-0000-0000-000000000006",'
            '"intent_id":"40000000-0000-0000-0000-000000000004",'
            '"operation":"booking.apply","quote":' + quote_bytes + ',"revision":0,'
            '"schema_version":1,"scope_id":"account-a","task_id":"legacy-task"}'
        )
        quote = parse_quote(json.loads(quote_bytes))
        confirmation = parse_confirmation(json.loads(confirmation_bytes))
        intent = parse_intent(json.loads(intent_bytes))
        self.assertEqual(quote, self.quote(version=1))
        self.assertEqual(confirmation, Confirmation(quote, True))
        self.assertEqual(intent, self.intent(quote))
        for original, parsed in (
            (quote_bytes, quote),
            (confirmation_bytes, confirmation),
            (intent_bytes, intent),
        ):
            self.assertEqual(canonical(parsed.payload()).encode(), original.encode())
        self.assertEqual(
            (quote.case_id, quote.supplier_id, quote.expected_supplier_revision),
            (None, None, None),
        )
        with self.assertRaises(UnsupportedOperation):
            require_mutation_quote(intent)

    def test_v2_roundtrip_binds_exact_case_supplier_and_supplier_revision(self):
        quote = self.quote()
        confirmation, intent = Confirmation(quote, True), self.intent(quote)
        for value, parser in (
            (quote, parse_quote),
            (confirmation, parse_confirmation),
            (intent, parse_intent),
        ):
            body = value.payload()
            self.assertEqual(body["schema_version"], 2)
            self.assertEqual(parser(json.loads(canonical(body))), value)
        self.assertEqual(require_mutation_quote(intent), quote)
        self.assertEqual(
            {
                key: quote.payload()[key]
                for key in ("case_id", "supplier_id", "expected_supplier_revision")
            },
            {
                "case_id": quote.case_id,
                "supplier_id": quote.supplier_id,
                "expected_supplier_revision": 4,
            },
        )
        copied = confirmation.payload()
        copied["quote"]["supplier_id"] = str(uuid4())
        self.assertEqual(intent.quote.supplier_id, quote.supplier_id)
        self.assertNotEqual(canonical(copied), canonical(confirmation.payload()))

    def test_partial_bindings_are_rejected_by_construction_and_versioned_parse(self):
        fields = ("case_id", "supplier_id", "expected_supplier_revision")
        for size in (1, 2):
            for selected in combinations(fields, size):
                changes = {key: None for key in selected}
                with self.subTest(partial=selected), self.assertRaises(ValueError):
                    self.quote(**changes)
        for field in fields:
            payload = self.quote().payload()
            payload.pop(field)
            with self.subTest(missing=field), self.assertRaises(ValueError):
                parse_quote(payload)
        for field in fields:
            payload = self.quote(version=1).payload()
            payload[field] = self.quote().payload()[field]
            with self.subTest(legacy_extra=field), self.assertRaises(ValueError):
                parse_quote(payload)

    def test_versions_and_exact_field_sets_cannot_be_coerced_or_mixed(self):
        quote = self.quote()
        for version in (None, False, True, 0, 3, 2.0, "2"):
            with self.subTest(version=version):
                with self.assertRaises(ValueError):
                    parse_quote(quote.payload() | {"schema_version": version})
                with self.assertRaises(InvalidConfirmation):
                    parse_confirmation(
                        Confirmation(quote, True).payload() | {"schema_version": version}
                    )
                with self.assertRaises(ValueError):
                    parse_intent(self.intent(quote).payload() | {"schema_version": version})
        for version, inner in ((1, quote), (2, self.quote(version=1))):
            with self.assertRaises(InvalidConfirmation):
                parse_confirmation(
                    Confirmation(inner, True).payload() | {"schema_version": version}
                )
            with self.assertRaises(ValueError):
                parse_intent(self.intent(inner).payload() | {"schema_version": version})
        for extra in ("tenant_id", "revision_hint", "model_summary"):
            with self.assertRaises(ValueError):
                parse_quote(quote.payload() | {extra: "untrusted"})
            with self.assertRaises(InvalidConfirmation):
                parse_confirmation(Confirmation(quote, True).payload() | {extra: "untrusted"})
            with self.assertRaises(ValueError):
                parse_intent(self.intent(quote).payload() | {extra: "untrusted"})

    def test_supplier_revision_is_an_exact_bounded_integer_with_room_for_successor(self):
        for value in (True, False, -1, 1.0, "4", MAX_INTEGER, MAX_INTEGER + 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.quote(expected_supplier_revision=value)
            with self.subTest(parsed=value), self.assertRaises(ValueError):
                parse_quote(self.quote().payload() | {"expected_supplier_revision": value})
        for value in (0, MAX_INTEGER - 1):
            quote = self.quote(expected_supplier_revision=value)
            self.assertEqual(parse_quote(quote.payload()), quote)

    def test_binding_identities_require_canonical_uuids_and_distinct_case_identity(self):
        for field in ("case_id", "supplier_id"):
            for value in (True, 1.0, "", "bad", "30000000000000000000000000000003"):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.quote(**{field: value})
        with self.assertRaises(ValueError):
            self.quote(task_id="20000000-0000-0000-0000-000000000002")

    def test_each_binding_change_changes_exact_confirmation_and_intent_payload(self):
        quote = self.quote()
        original = Confirmation(quote, True)
        for changes in (
            {"case_id": str(uuid4())},
            {"supplier_id": str(uuid4())},
            {"expected_supplier_revision": 5},
        ):
            changed = replace(quote, **changes)
            self.assertNotEqual(
                canonical(Confirmation(changed, True).payload()), canonical(original.payload())
            )
            self.assertNotEqual(
                canonical(self.intent(changed).payload()), canonical(self.intent(quote).payload())
            )
