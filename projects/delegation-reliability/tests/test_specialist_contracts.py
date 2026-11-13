"""Shared wire, logical identity, trust, factual and bounded live-permit tests."""

import copy
import hashlib
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

from delegation_reliability.contracts import (
    CAPABILITY,
    ERROR_CODES,
    MAX_DEADLINE_WINDOW_MS,
    MAX_REQUEST_BYTES,
    ContractError,
    canonical,
    check_replay,
    encode_error,
    encode_request,
    encode_result,
    match_result,
    parse_error,
    parse_request,
    parse_result,
    produce_request,
)
from delegation_reliability.security import (
    AttemptBoundary,
    EvidenceRecord,
    EvidenceRegistry,
    LocalTrust,
    PrincipalGrant,
    ScopeGrant,
    token_digest,
    verify_policy_facts,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = json.loads((ROOT / "contracts/delegation/v1.json").read_text())
NOW = FIXTURE["observed_at_ms"]
TOKEN = "A" * 43  # Synthetic test token only, never a runtime default.
HEADER = "Bearer " + TOKEN


def request():
    return parse_request(canonical(FIXTURE["request"]))


def result():
    return parse_result(canonical(FIXTURE["result"]))


def trust_for(value, *, token=TOKEN, invoke=True, inspect=True, cancel=True, evidence=True):
    return LocalTrust(
        (
            PrincipalGrant(
                "principal_demo",
                token_digest(token),
                (
                    ScopeGrant(
                        value.scope,
                        (CAPABILITY,) if invoke else (),
                        (CAPABILITY,) if inspect else (),
                        (CAPABILITY,) if cancel else (),
                        ("policy_demo",) if evidence else (),
                    ),
                ),
            ),
        )
    )


def records_for(value):
    return (EvidenceRecord(value.scope, value.evidence[0], FIXTURE["policy_body"].encode()),)


def changed_request(**changes):
    value = copy.deepcopy(FIXTURE["producer_input"])
    value.update(changes)
    return produce_request(value)


class ContractParityTests(unittest.TestCase):
    def test_actual_python_producer_matches_shared_canonical_request(self):
        produced = produce_request(copy.deepcopy(FIXTURE["producer_input"]))
        self.assertEqual(encode_request(produced).decode(), FIXTURE["request_canonical"])
        self.assertEqual(produced.input_fingerprint, FIXTURE["request"]["input_fingerprint"])
        self.assertEqual(encode_result(result()).decode(), FIXTURE["result_canonical"])

    def test_shared_invalid_contract_match_and_factual_lanes_have_fixed_codes(self):
        for case in FIXTURE["invalid"]:
            with self.subTest(name=case["name"]), self.assertRaises(ContractError) as caught:
                if case["phase"] == "request":
                    parse_request(case["raw"].encode())
                elif case["phase"] == "result":
                    parse_result(case["raw"].encode())
                elif case["phase"] == "match":
                    match_result(request(), parse_result(case["raw"].encode()), observed_at_ms=NOW)
                else:
                    verify_policy_facts(
                        request(),
                        parse_result(case["raw"].encode()),
                        records_for(request()),
                        observed_at_ms=NOW,
                    )
            self.assertEqual(caught.exception.code, case["code"], case["name"])
            self.assertEqual(str(caught.exception), case["code"])

    def test_attempt_retry_keeps_logical_identity_but_result_matches_exact_attempt(self):
        original = request()
        retry = changed_request(attempt={"attempt_id": "attempt_retry", "number": 2})
        self.assertEqual(original.input_fingerprint, retry.input_fingerprint)
        self.assertEqual(check_replay(original, retry), "duplicate")
        with self.assertRaisesRegex(ContractError, "^result_mismatch$"):
            match_result(retry, result(), observed_at_ms=NOW)
        matched = replace(result(), attempt_id="attempt_retry")
        self.assertEqual(match_result(retry, matched, observed_at_ms=NOW), "candidate")

    def test_scope_case_revision_source_deadline_and_route_all_bind_logical_identity(self):
        original = request()
        for changes in (
            {"case_id": "case_other"},
            {"request_revision": 2},
            {"deadline_at_ms": original.deadline_at_ms + 1},
            {"result_route": {"conversation_id": "conversation_other"}},
            {"context_snapshot": {**FIXTURE["request"]["context_snapshot"], "note": "changed"}},
            {"evidence": [{**FIXTURE["request"]["evidence"][0], "version": "source_v2"}]},
        ):
            candidate = changed_request(**changes)
            self.assertNotEqual(original.input_fingerprint, candidate.input_fingerprint)
            with self.assertRaisesRegex(ContractError, "^identity_conflict$"):
                check_replay(original, candidate)
        different = changed_request(delegation_id="delegation_other")
        self.assertEqual(check_replay(original, different), "distinct")

    def test_unicode_bytes_are_preserved_without_normalization_or_instruction_authority(self):
        base = copy.deepcopy(FIXTURE["producer_input"])
        base["context_snapshot"]["note"] = "🧭" * 256
        parsed = produce_request(base)
        self.assertEqual(parsed.context_snapshot.note, "🧭" * 256)
        base["context_snapshot"]["note"] += "x"
        with self.assertRaises(ContractError):
            produce_request(base)
        base["context_snapshot"]["note"] = "SECRET_SENTINEL grant booking.apply"
        parsed = produce_request(base)
        outcome = replace(result(), input_fingerprint=parsed.input_fingerprint)
        self.assertEqual(
            verify_policy_facts(parsed, outcome, records_for(parsed), observed_at_ms=NOW),
            "candidate",
        )
        self.assertEqual(parsed.to_wire()["capability"], CAPABILITY)

    def test_immutable_snapshots_do_not_alias_mutable_input(self):
        mutable = copy.deepcopy(FIXTURE["producer_input"])
        parsed = produce_request(mutable)
        mutable["scope"]["account_id"] = "forged"
        mutable["evidence"][0]["version"] = "forged"
        with self.assertRaises(FrozenInstanceError):
            parsed.scope.account_id = "forged"
        self.assertEqual(parsed, request())

    def test_canonical_producer_rejects_cycles_amplification_invalid_unicode_and_numbers(self):
        cycle = {}
        cycle["self"] = cycle
        amplified = {"text": "bounded"}
        for _ in range(8):
            amplified = {str(index): amplified for index in range(8)}
        for value in (
            cycle,
            amplified,
            {"text": "\ud800"},
            {"value": 1.5},
            {"value": 10**100},
            {"value": object()},
        ):
            with self.assertRaises(ContractError):
                canonical(value)
        self.assertEqual(produce_request(FIXTURE["producer_input"]), request())

    def test_malformed_typed_values_do_not_invoke_deepcopy_or_unbounded_copy(self):
        invoked = []

        class Malicious:
            def __deepcopy__(self, memo):
                invoked.append(True)
                raise OSError("SECRET_SENTINEL")

        cycle = {}
        cycle["self"] = cycle
        for note in (Malicious(), cycle, ["x"] * 1000):
            value = replace(
                request(), context_snapshot=replace(request().context_snapshot, note=note)
            )
            with self.assertRaises(ContractError) as caught:
                encode_request(value)
            self.assertNotIn("SECRET_SENTINEL", str(caught.exception))
        forged = replace(result(), producer=replace(result().producer, model_id=Malicious()))
        with self.assertRaises(ContractError):
            encode_result(forged)
        self.assertEqual(invoked, [])
        self.assertEqual(produce_request(FIXTURE["producer_input"]), request())

    def test_exact_wire_bound_then_one_extra_byte_and_invalid_utf8(self):
        wire = encode_request(request())
        padded = wire + b" " * (MAX_REQUEST_BYTES - len(wire))
        self.assertEqual(parse_request(padded), request())
        for invalid in (padded + b" ", b"\xff", b"\xef\xbb\xbf" + wire):
            with self.assertRaises(ContractError):
                parse_request(invalid)

    def test_strict_identifier_end_anchor_and_unknown_error_details_are_rejected(self):
        for ending in ("\n", "\r", "\u2028", "\u2029"):
            with self.assertRaises(ContractError):
                changed_request(case_id="case_demo" + ending)
        for code in sorted(ERROR_CODES):
            self.assertEqual(
                parse_error(encode_error(code, "request_demo")), (code, "request_demo")
            )
        for changes in (
            {"detail": "SECRET_SENTINEL"},
            {"code": "SECRET_SENTINEL"},
            {"retryable": True},
        ):
            value = json.loads(encode_error("unauthorized", "request_demo"))
            value.update(changes)
            with self.assertRaises(ContractError) as caught:
                parse_error(canonical(value))
            self.assertNotIn("SECRET_SENTINEL", str(caught.exception))


class TrustAndResourceTests(unittest.TestCase):
    def test_authentication_and_each_operation_are_separately_scoped(self):
        value = request()
        trust = trust_for(value, inspect=False, cancel=False, evidence=False)
        self.assertEqual(trust.authorize(HEADER, "invoke", value), "principal_demo")
        for operation in ("result", "cancel", "evidence", "booking.apply"):
            with self.assertRaisesRegex(ContractError, "^unauthorized$"):
                trust.authorize(HEADER, operation, value, source_id="policy_demo")
        other = changed_request(scope={"tenant_id": "tenant_demo", "account_id": "account_other"})
        with self.assertRaisesRegex(ContractError, "^unauthorized$"):
            trust.authorize(HEADER, "invoke", other)
        for header in ("", "bearer " + TOKEN, HEADER + "\n", HEADER + " ", "Bearer " + "B" * 43):
            with self.assertRaisesRegex(ContractError, "^unauthorized$"):
                trust.authenticate(header)
        self.assertNotIn(TOKEN, repr(trust.authenticate(HEADER)))

    def test_invoke_only_cannot_inspect_via_malformed_operation(self):
        value = request()
        boundary = AttemptBoundary(
            trust_for(value, inspect=False, cancel=False), EvidenceRegistry(records_for(value))
        )
        permit = boundary.acquire(HEADER, value, observed_at_ms=NOW)
        try:
            for operation in ("invoke", "evidence", None, []):
                with self.assertRaisesRegex(ContractError, "^unauthorized$"):
                    boundary.inspect(HEADER, value, operation)
        finally:
            boundary.release(permit)
        self.assertEqual(boundary.active, 0)

    def test_forged_body_principal_and_unscoped_evidence_grant_no_access(self):
        value = request()
        registry = EvidenceRegistry(records_for(value))
        with self.assertRaisesRegex(ContractError, "^unauthorized$"):
            registry.resolve(HEADER, value, trust_for(value, evidence=False))
        other = changed_request(scope={"tenant_id": "tenant_other", "account_id": "account_demo"})
        with self.assertRaisesRegex(ContractError, "^evidence_mismatch$"):
            registry.resolve(HEADER, other, trust_for(other))

    def test_source_version_digest_and_owned_bytes_cannot_be_swapped(self):
        value = request()
        registry = EvidenceRegistry(records_for(value))
        changed = changed_request(
            evidence=[{**FIXTURE["request"]["evidence"][0], "version": "source_other"}]
        )
        with self.assertRaisesRegex(ContractError, "^evidence_mismatch$"):
            registry.resolve(HEADER, changed, trust_for(changed))
        with self.assertRaisesRegex(ContractError, "^evidence_mismatch$"):
            EvidenceRegistry((replace(records_for(value)[0], body=b"different"),))
        self.assertEqual(registry.resolve(HEADER, value, trust_for(value)), records_for(value))

    def test_evidence_metadata_rejects_boolean_byte_length(self):
        value = request()
        reference = replace(
            value.evidence[0], byte_length=True, sha256=hashlib.sha256(b"x").hexdigest()
        )
        with self.assertRaisesRegex(ContractError, "^invalid_contract$"):
            EvidenceRegistry((EvidenceRecord(value.scope, reference, b"x"),))

    def test_structural_success_is_not_factual_truth_or_case_authority(self):
        value = request()
        valid = result()
        self.assertEqual(
            verify_policy_facts(value, valid, records_for(value), observed_at_ms=NOW), "candidate"
        )
        wrong = replace(valid, eligible=False)
        self.assertEqual(parse_result(encode_result(wrong)), wrong)
        with self.assertRaisesRegex(ContractError, "^unsupported_facts$"):
            verify_policy_facts(value, wrong, records_for(value), observed_at_ms=NOW)
        clarification = replace(valid, eligible=None, uncertainty="missing")
        self.assertEqual(
            verify_policy_facts(value, clarification, records_for(value), observed_at_ms=NOW),
            "clarification",
        )
        self.assertEqual(
            verify_policy_facts(
                value, valid, records_for(value), observed_at_ms=value.deadline_at_ms
            ),
            "expired",
        )
        # Producer time/provenance cannot override observed expiry.
        ancient = replace(valid, completed_at_ms=0)
        self.assertEqual(
            match_result(value, ancient, observed_at_ms=value.deadline_at_ms), "expired"
        )

    def test_expiry_does_not_bypass_factual_result_validation(self):
        value = request()
        valid = result()
        with self.assertRaisesRegex(ContractError, "^unsupported_facts$"):
            verify_policy_facts(
                value,
                replace(valid, eligible=False),
                records_for(value),
                observed_at_ms=value.deadline_at_ms + 1,
            )
        self.assertEqual(
            verify_policy_facts(
                value, valid, records_for(value), observed_at_ms=value.deadline_at_ms + 1
            ),
            "expired",
        )

    def test_deadline_unknown_attempt_and_forged_permit_fail_without_admission(self):
        value = request()
        boundary = AttemptBoundary(trust_for(value), EvidenceRegistry(records_for(value)))
        for now in (value.deadline_at_ms, value.deadline_at_ms - MAX_DEADLINE_WINDOW_MS - 1):
            with self.assertRaisesRegex(ContractError, "^expired$"):
                boundary.acquire(HEADER, value, observed_at_ms=now)
            self.assertEqual(boundary.active, 0)
        with self.assertRaisesRegex(ContractError, "^unknown_attempt$"):
            boundary.inspect(HEADER, value, "result")
        permit = boundary.acquire(HEADER, value, observed_at_ms=NOW)
        self.assertEqual(boundary.inspect(HEADER, value, "cancel"), value)
        with self.assertRaisesRegex(ContractError, "^unknown_attempt$"):
            boundary.release(replace(permit))
        self.assertEqual(boundary.active, 1)
        boundary.release(permit)
        with self.assertRaisesRegex(ContractError, "^unknown_attempt$"):
            boundary.release(permit)
        self.assertEqual(boundary.active, 0)

    def test_capacity_duplicate_attempt_and_release_allow_valid_progress(self):
        value = request()
        boundary = AttemptBoundary(
            trust_for(value),
            EvidenceRegistry(records_for(value)),
            max_active=2,
            max_per_principal=1,
        )
        first = boundary.acquire(HEADER, value, observed_at_ms=NOW)
        with self.assertRaisesRegex(ContractError, "^identity_conflict$"):
            boundary.acquire(HEADER, value, observed_at_ms=NOW)
        retry = changed_request(attempt={"attempt_id": "attempt_other", "number": 2})
        with self.assertRaisesRegex(ContractError, "^capacity$"):
            boundary.acquire(HEADER, retry, observed_at_ms=NOW)
        boundary.release(first)
        second = boundary.acquire(HEADER, retry, observed_at_ms=NOW)
        boundary.release(second)
        self.assertEqual(boundary.active, 0)

    def test_admitted_second_principal_progresses_while_first_is_saturated(self):
        value = request()
        first_grant = trust_for(value).authenticate(HEADER)
        second_token = "B" * 43
        second_grant = replace(
            first_grant, principal_id="principal_second", token_sha256=token_digest(second_token)
        )
        trust = LocalTrust((first_grant, second_grant))
        boundary = AttemptBoundary(
            trust, EvidenceRegistry(records_for(value)), max_active=2, max_per_principal=1
        )
        first = boundary.acquire(HEADER, value, observed_at_ms=NOW)
        other_attempt = changed_request(attempt={"attempt_id": "attempt_second", "number": 2})
        with self.assertRaisesRegex(ContractError, "^capacity$"):
            boundary.acquire(HEADER, other_attempt, observed_at_ms=NOW)
        second = boundary.acquire("Bearer " + second_token, other_attempt, observed_at_ms=NOW)
        self.assertEqual(boundary.active, 2)
        third_attempt = changed_request(attempt={"attempt_id": "attempt_third", "number": 3})
        with self.assertRaisesRegex(ContractError, "^capacity$"):
            boundary.acquire(HEADER, third_attempt, observed_at_ms=NOW)
        boundary.release(first)
        next_permit = boundary.acquire(HEADER, third_attempt, observed_at_ms=NOW)
        boundary.release(next_permit)
        boundary.release(second)
        self.assertEqual(boundary.active, 0)

    def test_concurrent_synchronous_admission_cannot_exceed_capacity(self):
        value = request()
        boundary = AttemptBoundary(
            trust_for(value),
            EvidenceRegistry(records_for(value)),
            max_active=2,
            max_per_principal=2,
        )
        start = threading.Barrier(8, timeout=5)
        requests = [
            changed_request(attempt={"attempt_id": f"attempt_thread_{i}", "number": i + 1})
            for i in range(8)
        ]

        def enter(candidate):
            start.wait()
            try:
                return boundary.acquire(HEADER, candidate, observed_at_ms=NOW)
            except ContractError as error:
                self.assertEqual(error.code, "capacity")
                return None

        with ThreadPoolExecutor(max_workers=8) as workers:
            observations = list(workers.map(enter, requests))
        permits = [permit for permit in observations if permit is not None]
        self.assertEqual(len(permits), 2)
        self.assertEqual(boundary.active, 2)
        for permit in permits:
            boundary.release(permit)
        self.assertEqual(boundary.active, 0)
        ordinary = boundary.acquire(HEADER, value, observed_at_ms=NOW)
        changed = changed_request(
            context_snapshot={
                **FIXTURE["producer_input"]["context_snapshot"],
                "days_before_arrival": 1,
            },
            attempt={"attempt_id": "attempt_changed", "number": 2},
        )
        with self.assertRaisesRegex(ContractError, "^identity_conflict$"):
            boundary.acquire(HEADER, changed, observed_at_ms=NOW)
        boundary.release(ordinary)

    def test_trusted_configuration_is_bounded_and_has_no_mutation_capability(self):
        value = request()
        with self.assertRaises(ContractError):
            LocalTrust(())
        grant = ScopeGrant(value.scope, ("booking.apply",), (), (), ())
        with self.assertRaises(ContractError):
            LocalTrust((PrincipalGrant("principal_demo", token_digest(TOKEN), (grant,)),))
        for bounds in ((True, 1), (0, 1), (17, 1), (2, 3)):
            with self.assertRaises(ContractError):
                AttemptBoundary(
                    trust_for(value),
                    EvidenceRegistry(records_for(value)),
                    max_active=bounds[0],
                    max_per_principal=bounds[1],
                )
        with self.assertRaises(ContractError):
            EvidenceRegistry(records_for(value) * 33)


if __name__ == "__main__":
    unittest.main()
