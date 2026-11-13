"""Signed conversational bindings cannot expand scope, lifetime or consent."""

import json
import unittest
from datetime import date

from continuity_lab.authorization import AuthenticatedActor, AuthenticationFailed
from continuity_lab.case_models import canonical
from continuity_lab.models import BookingChange
from continuity_lab.session_grants import ConversationGrant, _signature, sign_grant, verify_grant


class SessionGrantTests(unittest.TestCase):
    def setUp(self):
        self.secret = "synthetic-server-signing-secret-" * 2
        self.actor = AuthenticatedActor("opérator-東京", "tenant-é")
        self.arguments = {
            "secret": self.secret,
            "actor": self.actor,
            "room": "business-unit",
            "participant": "browser-unit",
            "request": BookingChange("démo-001", date(2030, 12, 10), True),
            "request_key": "request-é-東京",
            "now": 1900000000,
        }
        self.raw = sign_grant(**self.arguments)
        self.envelope = json.loads(self.raw)
        self.payload = self.envelope["payload"]

    def verify(self, raw=None, **changes):
        options = {
            "secret": self.secret,
            "room": "business-unit",
            "expected_scope": self.actor.scope_id,
            "expected_actor": self.actor.actor_id,
            "now": 1900000001,
        }
        options.update(changes)
        return verify_grant(self.raw if raw is None else raw, **options)

    def resign(self, **changes):
        payload = {**self.payload, **changes}
        return canonical({"payload": payload, "signature": _signature(payload, self.secret)})

    def assert_rejected(self, raw, **changes):
        with self.assertRaises(AuthenticationFailed) as result:
            self.verify(raw, **changes)
        self.assertEqual(str(result.exception), "A valid local conversation binding is required")
        for private in (self.secret, self.raw, self.arguments["request_key"]):
            self.assertNotIn(private, str(result.exception))

    def test_unicode_canonical_roundtrip_and_exact_investigation_only_binding(self):
        grant = self.verify()
        self.assertIs(type(grant), ConversationGrant)
        self.assertEqual(grant.payload(), self.payload)
        self.assertEqual(self.raw, canonical(self.envelope))
        self.assertEqual(grant.request.booking_reference, "DÉMO-001")
        self.assertEqual(grant.request_key, "request-é-東京")
        self.assertEqual(grant.expires_at - grant.issued_at, 300)
        self.assertIsNone(grant.task_id)
        self.assertEqual(
            set(grant.payload()),
            {
                "schema_version",
                "grant_id",
                "issued_at",
                "expires_at",
                "room",
                "participant",
                "scope_id",
                "actor_id",
                "request",
                "request_key",
                "task_id",
            },
        )
        self.assertNotIn("approval", grant.payload())
        self.assertNotIn("confirmation", grant.payload())
        self.assertNotIn(self.secret, repr(grant))

    def test_signature_and_every_scope_binding_fail_closed(self):
        for field, value in (
            ("room", "business-other"),
            ("participant", "browser-other"),
            ("scope_id", "other"),
            ("actor_id", "other"),
            ("request_key", "different"),
            ("task_id", "11111111-1111-4111-8111-111111111111"),
        ):
            changed = {**self.envelope, "payload": {**self.payload, field: value}}
            with self.subTest(field=field):
                self.assert_rejected(canonical(changed))
        for changes in (
            {"room": "business-other"},
            {"expected_scope": "other"},
            {"expected_actor": "other"},
            {"secret": "wrong-" * 8},
        ):
            self.assert_rejected(self.raw, **changes)
        self.assert_rejected(canonical({**self.envelope, "signature": "A" * 43}))

    def test_nonce_and_timestamps_do_not_change_logical_binding_digest(self):
        first = self.verify()
        second = self.verify(sign_grant(**{**self.arguments, "now": 1900000001}))
        self.assertNotEqual(first.grant_id, second.grant_id)
        self.assertEqual(first.binding_digest(), second.binding_digest())
        for field, value in (
            ("request_key", "other"),
            ("participant", "browser-other"),
            ("task_id", "11111111-1111-4111-8111-111111111111"),
        ):
            other = self.verify(self.resign(**{field: value}))
            self.assertNotEqual(first.binding_digest(), other.binding_digest())

    def test_expiry_future_timestamp_and_noninteger_clocks_are_rejected(self):
        self.assertEqual(self.verify(now=1900000000).issued_at, 1900000000)
        self.assertEqual(self.verify(now=1900000299).expires_at, 1900000300)
        for clock in (1899999999, 1900000300, 1900000301, True, 1900000001.0):
            self.assert_rejected(self.raw, now=clock)
        for changes in (
            {"issued_at": True},
            {"issued_at": 1900000000.0},
            {"expires_at": 1900000300.0},
            {"expires_at": 1900000301},
            {"expires_at": 1900000000},
            {"schema_version": True},
            {"schema_version": 1.0},
            {"schema_version": 2},
        ):
            with self.subTest(changes=changes):
                self.assert_rejected(self.resign(**changes))

    def test_unknown_duplicate_nonfinite_and_oversized_fields_are_rejected(self):
        for raw in (
            canonical({**self.envelope, "scope_id": "override"}),
            self.resign(approval=True),
            self.raw.replace('"payload":', '"payload":{},"payload":', 1),
            self.raw.replace(
                '"issued_at":1900000000', '"issued_at":1900000000,"issued_at":1900000000'
            ),
            self.raw.replace('"issued_at":1900000000', '"issued_at":NaN'),
            self.raw.replace('"issued_at":1900000000', '"issued_at":Infinity'),
            "x" * 8193,
            "é" * 4100,
            "[]",
            "null",
            "",
            "{",
            42,
        ):
            with self.subTest(raw=str(raw)[:60]):
                self.assert_rejected(raw)

    def test_valid_mac_still_requires_canonical_domain_values_and_exact_types(self):
        for changes in (
            {"request": {**self.payload["request"], "booking_reference": "démo-001"}},
            {"request": {**self.payload["request"], "new_check_in": "20301210"}},
            {"request": {**self.payload["request"], "confirmed": 1}},
            {"request": {**self.payload["request"], "confirmed": False}},
            {"request": {**self.payload["request"], "approved": True}},
            {"request_key": "invalid\nkey"},
            {"room": "lab-unit"},
            {"participant": "agent-unit"},
            {"actor_id": " actor"},
            {"grant_id": "11111111-1111-4111-8111-11111111111A"},
            {"task_id": "11111111-1111-4111-8111-11111111111A"},
        ):
            with self.subTest(changes=changes):
                self.assert_rejected(self.resign(**changes))

    def test_trusted_signer_rejects_bad_credentials_clock_and_unconfirmed_request(self):
        for changes in (
            {"secret": "short"},
            {"secret": "s" * 513},
            {"now": True},
            {"now": 1.0},
            {"request_key": "\n"},
            {"room": "lab-unit"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                sign_grant(**{**self.arguments, **changes})


class MediaInvocationIdentityTests(unittest.TestCase):
    def test_trusted_signed_binding_replays_the_explicit_media_invocation_identity(self):
        from datetime import date

        from continuity_lab.authorization import AuthenticatedActor
        from continuity_lab.models import BookingChange
        from continuity_lab.session_grants import sign_grant, verify_grant

        invocation = "a1111111-1111-4111-8111-111111111111"
        options = {
            "secret": "s" * 40,
            "actor": AuthenticatedActor("local-operator", "demo-traveller"),
            "room": "business-test",
            "participant": "browser-test",
            "request": BookingChange("DEMO-BK-001", date(2030, 12, 10), True),
            "request_key": "original-key",
            "grant_id": invocation,
            "now": 1000,
        }
        first, second = sign_grant(**options), sign_grant(**options)
        self.assertEqual(first, second)
        bound = verify_grant(
            first,
            secret="s" * 40,
            room="business-test",
            expected_scope="demo-traveller",
            expected_actor="local-operator",
            now=1001,
        )
        self.assertEqual(bound.grant_id, invocation)
        for invalid in ("not-a-uuid", "A1111111-1111-4111-8111-111111111111", True):
            with self.subTest(identity=invalid), self.assertRaises(ValueError):
                sign_grant(**{**options, "grant_id": invalid})
