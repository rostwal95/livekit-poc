"""Lease values reject malformed authority without I/O or payload disclosure."""

import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from uuid import uuid4

from continuity_lab.lease_models import (
    MAX_EPOCH,
    CoordinationPolicy,
    LeaseBusy,
    LeaseGrant,
    LeaseLost,
    LeaseRequired,
    LeaseSnapshot,
    WorkClaim,
    WorkKind,
)

STAMP = "2030-12-01T00:00:00+00:00"
DUE = "2030-12-01T00:00:30+00:00"


class LeaseModelsTests(unittest.TestCase):
    def grant(self, **changes):
        return replace(LeaseGrant("scope-a", "task-a", str(uuid4()), 1, DUE), **changes)

    def test_policy_defaults_are_explicit_finite_and_immutable(self):
        policy = CoordinationPolicy()
        self.assertEqual(
            policy.payload(),
            {
                "maximum_pending": 1000,
                "maximum_active": 4,
                "maximum_records": 10000,
                "lease_seconds": 30,
            },
        )
        with self.assertRaises(FrozenInstanceError):
            policy.lease_seconds = 999
        payload = policy.payload()
        payload["maximum_active"] = 50
        self.assertEqual(policy.maximum_active, 4)

    def test_policy_rejects_bool_float_and_bad_cross_limits(self):
        for name in CoordinationPolicy().payload():
            for value in (True, False, 1.0, "1", None, -1, 0):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    replace(CoordinationPolicy(), **{name: value})
        for changes in (
            {"maximum_pending": 100001},
            {"maximum_active": 65},
            {"maximum_records": 1000001},
            {"lease_seconds": 301},
            {"maximum_pending": 2, "maximum_active": 3},
            {"maximum_records": 999},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(CoordinationPolicy(), **changes)
        self.assertEqual(CoordinationPolicy(1, 1, 1, 1).lease_seconds, 1)
        self.assertEqual(CoordinationPolicy(100000, 64, 1000000, 300).maximum_records, 1000000)

    def test_grant_is_immutable_and_epoch_is_positive_bounded_exact_integer(self):
        value = self.grant()
        with self.assertRaises(FrozenInstanceError):
            value.epoch = 2
        for epoch in (0, -1, True, 1.0, str(1), MAX_EPOCH + 1):
            with self.subTest(epoch=epoch), self.assertRaises(ValueError):
                self.grant(epoch=epoch)
        self.assertEqual(self.grant(epoch=MAX_EPOCH).epoch, MAX_EPOCH)

    def test_grant_rejects_noncanonical_or_unbounded_identifiers(self):
        for field in ("scope_id", "task_id"):
            for value in ("", " actor", "actor ", "x\n", "x\x7f", "x" * 129, None):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.grant(**{field: value})
        owner = str(uuid4())
        for value in (owner.upper(), owner.replace("-", ""), "SECRET_SENTINEL", None):
            with self.subTest(value=value), self.assertRaises(ValueError) as error:
                self.grant(owner_id=value)
            self.assertNotIn("SECRET_SENTINEL", str(error.exception))

    def test_grant_expiry_requires_canonical_utc_aware_string(self):
        for value in (
            "SECRET_SENTINEL",
            "2030-12-01T00:00:00",
            "2030-12-01T00:00:00Z",
            "2030-12-01T01:00:00+01:00",
            "2030-12-01",
            datetime.now(UTC),
            "2030-12-01T00:00:00.000000+00:00",
            "0001-01-01T00:00:00+01:00",
            "9999-12-31T23:59:59-01:00",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError) as error:
                self.grant(expires_at=value)
            self.assertNotIn("SECRET_SENTINEL", str(error.exception))

    def test_observation_owner_expiry_pair_and_clock_order(self):
        grant = self.grant()
        snapshot = LeaseSnapshot(
            grant.scope_id,
            grant.task_id,
            grant.owner_id,
            grant.epoch,
            grant.expires_at,
            STAMP,
            STAMP,
        )
        self.assertEqual(snapshot.grant(), grant)
        released = replace(snapshot, owner_id=None, expires_at=None)
        with self.assertRaises(LeaseLost):
            released.grant()
        for changes in (
            {"owner_id": None},
            {"expires_at": None},
            {"expires_at": STAMP},
            {"renewed_at": "2030-11-30T23:59:59+00:00"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(snapshot, **changes)

    def test_work_step_is_typed_and_only_wait_has_authority_derived_actor(self):
        grant = self.grant()
        for kind in (WorkKind.INQUIRY, WorkKind.MUTATION, WorkKind.DELIVERY):
            self.assertEqual(WorkClaim(grant, kind).grant, grant)
            with self.assertRaises(ValueError):
                WorkClaim(grant, kind, "actor-a")
        self.assertEqual(WorkClaim(grant, WorkKind.WAIT, "actor-a").actor_id, "actor-a")
        for args in (
            (grant, "inquiry"),
            (None, WorkKind.INQUIRY),
            (grant, WorkKind.WAIT),
            (grant, WorkKind.WAIT, " SECRET_SENTINEL"),
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                WorkClaim(*args)

    def test_coordination_errors_have_finite_safe_categories(self):
        self.assertEqual(
            {LeaseBusy.code, LeaseLost.code, LeaseRequired.code},
            {"lease_busy", "lease_lost", "lease_required"},
        )
