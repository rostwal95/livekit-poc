"""Public wire, trust and immutable-source boundary regression checks."""

from __future__ import annotations

import copy
import hashlib
import json
import unittest
from dataclasses import replace
from pathlib import Path

from delegation_reliability.contracts import CAPABILITY, ContractError, canonical, parse_request
from delegation_reliability.fixed_policy import (
    snapshot_fixed_policy_records,
    verify_fixed_policy_facts,
)
from delegation_reliability.fixed_policy_contracts import (
    encode_fixed_policy_request,
    encode_fixed_policy_result,
    match_fixed_policy_result,
    parse_fixed_policy_request,
    parse_fixed_policy_result,
    produce_fixed_policy_request,
)
from delegation_reliability.security import (
    AttemptBoundary,
    EvidenceRecord,
    EvidenceRegistry,
    LocalTrust,
    PrincipalGrant,
    ScopeGrant,
    token_digest,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = json.loads((ROOT / "contracts/delegation/fixed-policy-v2.json").read_bytes())


def request():
    return parse_fixed_policy_request(canonical(FIXTURE["request"]))


def result():
    return parse_fixed_policy_result(canonical(FIXTURE["result"]))


def records():
    value = request()
    return tuple(
        EvidenceRecord(value.scope, ref, FIXTURE[key].encode())
        for ref, key in zip(value.evidence, ["policy_body_utf8", "facts_body_utf8"], strict=True)
    )


class FixedPolicyBoundaryTests(unittest.TestCase):
    def test_actual_producer_and_result_equal_canonical_shared_wire(self):
        made = produce_fixed_policy_request(copy.deepcopy(FIXTURE["producer_input"]))
        self.assertEqual(encode_fixed_policy_request(made).decode(), FIXTURE["request_canonical"])
        self.assertEqual(encode_fixed_policy_result(result()).decode(), FIXTURE["result_canonical"])
        self.assertEqual(
            verify_fixed_policy_facts(
                made, result(), records(), observed_at_ms=FIXTURE["observed_at_ms"]
            ),
            "candidate",
        )

    def test_source_version_is_independent_of_semantic_policy_version(self):
        value = request()
        self.assertNotEqual(value.evidence[0].version, value.context_snapshot.policy_version)
        self.assertEqual(
            verify_fixed_policy_facts(
                value, result(), records(), observed_at_ms=FIXTURE["observed_at_ms"]
            ),
            "candidate",
        )

    def test_legacy_codec_stays_v1_only(self):
        legacy = json.loads((ROOT / "contracts/delegation/v1.json").read_bytes())
        with self.assertRaises(ContractError) as caught:
            parse_request(encode_fixed_policy_request(request()))
        self.assertEqual(caught.exception.code, "unsupported_version")
        with self.assertRaises(ContractError) as caught:
            parse_fixed_policy_request(canonical(legacy["request"]))
        self.assertEqual(caught.exception.code, "unsupported_version")

    def test_changed_source_fingerprint_and_exact_body_binding(self):
        value = copy.deepcopy(FIXTURE["producer_input"])
        value["evidence"][1]["sha256"] = "0" * 64
        changed = produce_fixed_policy_request(value)
        self.assertNotEqual(changed.input_fingerprint, request().input_fingerprint)
        self.assertEqual(request().input_fingerprint, FIXTURE["request"]["input_fingerprint"])
        with self.assertRaises(ContractError) as caught:
            verify_fixed_policy_facts(
                request(),
                result(),
                (records()[0], replace(records()[1], body=b"{}")),
                observed_at_ms=FIXTURE["observed_at_ms"],
            )
        self.assertEqual(caught.exception.code, "evidence_mismatch")

    def test_mutable_source_and_reference_inputs_are_snapshotted(self):
        original = records()
        snapshot = snapshot_fixed_policy_records(original)
        object.__setattr__(original[1], "body", b"{}")
        self.assertEqual(hashlib.sha256(snapshot[1].body).hexdigest(), request().evidence[1].sha256)
        self.assertEqual(
            verify_fixed_policy_facts(
                request(), result(), snapshot, observed_at_ms=FIXTURE["observed_at_ms"]
            ),
            "candidate",
        )

    def test_factual_verification_is_required_after_correlation(self):
        wrong = replace(result(), eligible=False)
        self.assertEqual(
            match_fixed_policy_result(request(), wrong, observed_at_ms=FIXTURE["observed_at_ms"]),
            "candidate",
        )
        for now in [FIXTURE["observed_at_ms"], request().deadline_at_ms]:
            with self.subTest(now=now), self.assertRaises(ContractError) as caught:
                verify_fixed_policy_facts(request(), wrong, records(), observed_at_ms=now)
            self.assertEqual(caught.exception.code, "unsupported_facts")

    def test_actual_public_attempt_permit_is_shared_and_released_explicitly(self):
        value = request()
        trust = LocalTrust(
            (
                PrincipalGrant(
                    "fixed_principal",
                    token_digest("A" * 43),
                    (
                        ScopeGrant(
                            value.scope,
                            (CAPABILITY,),
                            (CAPABILITY,),
                            (CAPABILITY,),
                            tuple(ref.source_id for ref in value.evidence),
                        ),
                    ),
                ),
            )
        )
        boundary = AttemptBoundary(
            trust, EvidenceRegistry(records()), max_active=1, max_per_principal=1
        )
        permit = boundary.acquire(
            "Bearer " + "A" * 43, value, observed_at_ms=FIXTURE["observed_at_ms"]
        )
        self.assertEqual(boundary.active, 1)
        with self.assertRaises(ContractError) as caught:
            boundary.acquire("Bearer " + "A" * 43, value, observed_at_ms=FIXTURE["observed_at_ms"])
        self.assertEqual(caught.exception.code, "identity_conflict")
        boundary.release(permit)
        self.assertEqual(boundary.active, 0)
        later = boundary.acquire(
            "Bearer " + "A" * 43, value, observed_at_ms=FIXTURE["observed_at_ms"]
        )
        boundary.release(later)
