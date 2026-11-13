"""Exact immutable consent data rejects inferred, altered and ambiguous inputs."""

import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime
from uuid import uuid4

from continuity_lab.case_models import (
    ActionIntent,
    Confirmation,
    InvalidConfirmation,
    QuoteSnapshot,
    canonical,
    parse_confirmation,
    parse_intent,
    parse_quote,
)


class CaseModelTests(unittest.TestCase):
    def quote(self, **changes):
        values = {
            "quote_id": str(uuid4()),
            "task_id": "legacy-task",
            "revision": 0,
            "booking_reference": "DEMO-BK-001",
            "new_check_in": date(2030, 12, 10),
            "amount_minor": 1250,
            "currency": "USD",
            "expires_at": "2030-12-01T00:10:00+00:00",
        }
        values.update(changes)
        return QuoteSnapshot(**values)

    def intent(self, quote=None, **changes):
        quote = quote or self.quote()
        values = {
            "intent_id": str(uuid4()),
            "task_id": quote.task_id,
            "scope_id": "account-a",
            "actor_id": "actor-a",
            "revision": quote.revision,
            "quote": quote,
            "confirmation_id": str(uuid4()),
            "effect_id": str(uuid4()),
            "dispatch_event_id": str(uuid4()),
            "created_at": "2030-12-01T00:01:00Z",
        }
        values.update(changes)
        return ActionIntent(**values)

    def test_quote_and_confirmation_roundtrip_without_shared_mutable_payload(self):
        quote = self.quote()
        confirmation = Confirmation(quote, True)
        self.assertEqual(parse_quote(quote.payload()), quote)
        self.assertEqual(parse_confirmation(confirmation.payload()), confirmation)
        first = confirmation.payload()
        first["quote"]["amount_minor"] = 9999
        self.assertEqual(confirmation.quote.amount_minor, 1250)
        self.assertNotEqual(canonical(first), canonical(confirmation.payload()))
        with self.assertRaises(FrozenInstanceError):
            quote.amount_minor = 1
        with self.assertRaises(FrozenInstanceError):
            confirmation.explicit = False

    def test_model_summary_or_truthy_value_cannot_become_explicit_confirmation(self):
        for value in (None, False, 1, "true", "The user agreed", {}, []):
            with self.subTest(kind=type(value).__name__), self.assertRaises(InvalidConfirmation):
                Confirmation(self.quote(), value)
        for body in (
            {"summary": "The user agreed"},
            {"quote": self.quote().payload()},
            {"schema_version": 1, "quote": self.quote().payload(), "explicit": "yes"},
        ):
            with self.assertRaises(InvalidConfirmation):
                parse_confirmation(body)

    def test_missing_unknown_actor_scope_and_schema_fields_are_rejected(self):
        for field in self.quote().payload():
            payload = self.quote().payload()
            payload.pop(field)
            with self.subTest(missing=field), self.assertRaises((ValueError, TypeError)):
                parse_quote(payload)
        confirmation = Confirmation(self.quote(), True).payload()
        for field in ("actor_id", "scope_id", "tenant_id", "source_summary"):
            with self.subTest(extra=field), self.assertRaises(InvalidConfirmation):
                parse_confirmation({**confirmation, field: "attacker"})
        for version in (True, 0, 2, "1"):
            with self.assertRaises(InvalidConfirmation):
                parse_confirmation({**confirmation, "schema_version": version})

    def test_minor_units_are_integers_without_rounding_and_bounded_for_shared_clients(self):
        for value in (True, -1, 1.2, "1250", 9007199254740992):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.quote(amount_minor=value)
        for value in (0, 1250, 9007199254740991):
            self.assertEqual(self.quote(amount_minor=value).amount_minor, value)

    def test_quote_fields_must_be_canonical_and_unambiguous(self):
        for fields in (
            {"quote_id": "not-a-uuid"},
            {"task_id": ""},
            {"task_id": "bad\0id"},
            {"revision": True},
            {"revision": -1},
            {"booking_reference": " demo-bk-001 "},
            {"new_check_in": datetime(2030, 12, 10)},
            {"currency": "usd"},
            {"currency": "ZZZ"},
            {"expires_at": "2030-12-01T00:10:00"},
            {"expires_at": "2030-12-01T05:40:00+05:30"},
        ):
            with self.subTest(fields=list(fields)), self.assertRaises(ValueError):
                self.quote(**fields)
        self.assertEqual(
            self.quote(expires_at="2030-12-01T00:10:00Z").expires_at, "2030-12-01T00:10:00+00:00"
        )

    def test_exact_confirmation_preserves_all_price_date_expiry_and_revision_fields(self):
        quote = self.quote()
        for fields in (
            {"amount_minor": 1251},
            {"currency": "EUR"},
            {"new_check_in": date(2030, 12, 11)},
            {"revision": 1},
            {"expires_at": "2030-12-01T00:11:00Z"},
            {"quote_id": str(uuid4())},
            {"booking_reference": "DEMO-BK-002"},
        ):
            changed = Confirmation(replace(quote, **fields), True)
            self.assertNotEqual(
                canonical(changed.payload()), canonical(Confirmation(quote, True).payload())
            )

    def test_intent_roundtrip_binds_immutable_quote_and_all_stable_ids(self):
        intent = self.intent()
        self.assertEqual(parse_intent(intent.payload()), intent)
        self.assertEqual(intent.created_at, "2030-12-01T00:01:00+00:00")
        for fields in (
            {"task_id": "another-task"},
            {"revision": 1},
            {"effect_id": "bad"},
            {"scope_id": ""},
        ):
            with self.assertRaises(ValueError):
                self.intent(quote=intent.quote, **fields)
        for fields in ({"operation": "booking.inquire"}, {"schema_version": 2}, {"extra": "bad"}):
            with self.assertRaises(ValueError):
                parse_intent({**intent.payload(), **fields})

    def test_invalid_confirmation_errors_do_not_reflect_private_payloads(self):
        original = Confirmation(self.quote(), True).payload()
        original["quote"]["expires_at"] = "SECRET_SENTINEL"
        with self.assertRaises(InvalidConfirmation) as caught:
            parse_confirmation(original)
        self.assertNotIn("SECRET_SENTINEL", str(caught.exception))
        self.assertEqual(caught.exception.code, "invalid_confirmation")
