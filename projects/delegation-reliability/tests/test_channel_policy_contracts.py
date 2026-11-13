"""Origin identity and nested policy-v2 boundaries; no authority or transport work."""

from __future__ import annotations

import copy
import hashlib
import json
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from delegation_reliability.channel_policy_contracts import (
    CHANNEL_POLICY_ORIGIN_KIND,
    ChannelPolicyOrigin,
    ChannelPolicyRequest,
    ChannelPolicyResult,
    channel_policy_key,
    encode_channel_policy_request,
    encode_channel_policy_result,
    match_channel_policy_result,
    parse_channel_policy_request,
    parse_channel_policy_result,
    produce_channel_policy_request,
    produce_channel_policy_result,
)
from delegation_reliability.contracts import (
    CAPABILITY,
    Attempt,
    ContractError,
    canonical,
    parse_request,
)
from delegation_reliability.fixed_policy import verify_fixed_policy_facts
from delegation_reliability.fixed_policy_contracts import (
    FixedPolicyRequest,
    FixedPolicyResult,
    encode_fixed_policy_request,
    encode_fixed_policy_result,
    parse_fixed_policy_request,
    parse_fixed_policy_result,
    produce_fixed_policy_request,
)
from delegation_reliability.security import EvidenceRecord

ROOT = Path(__file__).resolve().parents[3]
FIXTURE: Any = json.loads((ROOT / "contracts/delegation/fixed-policy-v2.json").read_bytes())
CHANNEL_FIXTURE: Any = json.loads(
    (ROOT / "contracts/delegation/channel-policy-v3.json").read_bytes()
)
PROFILE = "00000000-0000-4000-8000-000000000001"
OPERATION = "00000000-0000-4000-8000-000000000002"
RECEIPT = "00000000-0000-4000-8000-000000000003"


def origin() -> ChannelPolicyOrigin:
    return ChannelPolicyOrigin(
        CHANNEL_POLICY_ORIGIN_KIND, PROFILE, OPERATION, RECEIPT, "a" * 64, 32768
    )


def inner_request(operation: str = OPERATION) -> FixedPolicyRequest:
    value: dict[str, Any] = copy.deepcopy(FIXTURE["producer_input"])
    value["delegation_id"] = channel_policy_key(operation)
    return produce_fixed_policy_request(value)


def producer_input(
    source: ChannelPolicyOrigin | None = None, request: FixedPolicyRequest | None = None
) -> dict[str, object]:
    source = origin() if source is None else source
    request = inner_request(source.operation_key) if request is None else request
    return {
        "schema_version": 1,
        "kind": "delegation.request",
        "capability": CAPABILITY,
        "input_schema_version": 3,
        "origin": source.to_wire(),
        "request": request.to_wire(),
    }


def request_value() -> ChannelPolicyRequest:
    return produce_channel_policy_request(producer_input())


def inner_result(request: FixedPolicyRequest) -> FixedPolicyResult:
    value: dict[str, Any] = copy.deepcopy(FIXTURE["result"])
    value.update(
        delegation_id=request.delegation_id,
        input_fingerprint=request.input_fingerprint,
        attempt_id=request.attempt.attempt_id,
    )
    return parse_fixed_policy_result(canonical(value))


def result_value() -> ChannelPolicyResult:
    request = request_value()
    return produce_channel_policy_result(request, inner_result(request.request))


class ChannelPolicyBoundaryTests(unittest.TestCase):
    def test_closed_typed_roundtrip_proxies_and_independent_fingerprint(self) -> None:
        value = request_value()
        wire = cast(dict[str, Any], value.to_wire())
        logical = copy.deepcopy(wire)
        logical.pop("input_fingerprint")
        logical["request"].pop("attempt")
        logical["request"].pop("input_fingerprint")
        self.assertEqual(value.input_fingerprint, hashlib.sha256(canonical(logical)).hexdigest())
        self.assertNotEqual(value.input_fingerprint, value.request.input_fingerprint)
        self.assertEqual(parse_channel_policy_request(encode_channel_policy_request(value)), value)
        self.assertEqual(
            (
                value.scope,
                value.delegation_id,
                value.case_id,
                value.request_revision,
                value.deadline_at_ms,
                value.conversation_id,
                value.attempt,
            ),
            (
                value.request.scope,
                value.request.delegation_id,
                value.request.case_id,
                value.request.request_revision,
                value.request.deadline_at_ms,
                value.request.conversation_id,
                value.request.attempt,
            ),
        )
        with self.assertRaises(FrozenInstanceError):
            cast(Any, value).input_fingerprint = "0" * 64
        with self.assertRaises(FrozenInstanceError):
            cast(Any, value.origin).payload_byte_length = 2

    def test_shared_golden_requests_verify_exact_bytes_and_both_independent_fingerprints(
        self,
    ) -> None:
        self.assertEqual(CHANNEL_FIXTURE["policy_fixture"], "fixed-policy-v2.json")
        originals = {case["name"]: case for case in CHANNEL_FIXTURE["p2_cases"]}
        self.assertEqual(len(CHANNEL_FIXTURE["channel_cases"]), 3)
        for case in CHANNEL_FIXTURE["channel_cases"]:
            with self.subTest(case=case["name"]):
                raw = case["request_canonical"].encode()
                made = produce_channel_policy_request(case["producer_input"])
                restored = parse_channel_policy_request(raw)
                self.assertEqual(restored, made)
                self.assertEqual(encode_channel_policy_request(restored), raw)
                self.assertEqual(hashlib.sha256(raw).hexdigest(), case["request_sha256"])
                self.assertEqual(len(raw), case["request_bytes"])
                self.assertLessEqual(len(raw), 16384)
                self.assertEqual(
                    encode_fixed_policy_request(restored.request).decode(),
                    case["inner_request_canonical"],
                )
                self.assertEqual(restored.input_fingerprint, case["outer_input_fingerprint"])
                self.assertEqual(
                    restored.request.input_fingerprint, case["inner_input_fingerprint"]
                )
                wire: dict[str, Any] = json.loads(raw)
                inner_logical = copy.deepcopy(wire["request"])
                inner_logical.pop("input_fingerprint")
                inner_logical.pop("attempt")
                outer_logical = copy.deepcopy(wire)
                outer_logical.pop("input_fingerprint")
                outer_logical["request"] = inner_logical
                for logical, expected in (
                    (inner_logical, case["inner_input_fingerprint"]),
                    (outer_logical, case["outer_input_fingerprint"]),
                ):
                    # The oracle uses stdlib UTF-8 JSON rather than the production canonical helper.
                    literal_bytes = json.dumps(
                        logical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                    ).encode()
                    self.assertEqual(hashlib.sha256(literal_bytes).hexdigest(), expected)
                original = originals[case["name"]]
                original_wire = original["submission"]
                self.assertEqual(restored.origin.profile_id, CHANNEL_FIXTURE["profile_id"])
                self.assertEqual(restored.origin.operation_key, original_wire["operationKey"])
                self.assertEqual(
                    restored.origin.input_receipt_id, original_wire["message"]["receiptId"]
                )
                self.assertEqual(restored.origin.payload_sha256, original["payload_sha256"])
                self.assertEqual(
                    restored.origin.payload_byte_length, original["payload_byte_length"]
                )
                self.assertEqual(
                    restored.delegation_id,
                    "p2_" + original_wire["operationKey"].replace("-", ""),
                )
                self.assertEqual(restored.request_revision, int(original_wire["caseRevision"]))

    def test_shared_golden_results_retain_outer_and_inner_identity_and_v2_bytes(self) -> None:
        for case in CHANNEL_FIXTURE["channel_cases"]:
            with self.subTest(case=case["name"]):
                request = parse_channel_policy_request(case["request_canonical"].encode())
                raw = case["result_canonical"].encode()
                result = parse_channel_policy_result(raw)
                wire: dict[str, Any] = json.loads(raw)
                nested_bytes = json.dumps(
                    wire["result"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ).encode()
                self.assertEqual(encode_channel_policy_result(result), raw)
                self.assertEqual(hashlib.sha256(raw).hexdigest(), case["result_sha256"])
                self.assertEqual(len(raw), case["result_bytes"])
                self.assertLessEqual(len(raw), 8192)
                self.assertEqual(encode_fixed_policy_result(result.result), nested_bytes)
                self.assertEqual(parse_fixed_policy_result(nested_bytes), result.result)
                self.assertEqual(produce_channel_policy_result(request, result.result), result)
                self.assertEqual(result.input_fingerprint, case["outer_input_fingerprint"])
                self.assertEqual(result.result.input_fingerprint, case["inner_input_fingerprint"])
                self.assertEqual(result.result.delegation_id, request.delegation_id)
                self.assertEqual(result.result.scope, request.scope)
                self.assertEqual(result.result.case_id, request.case_id)
                self.assertEqual(result.result.request_revision, request.request_revision)
                self.assertEqual(result.result.attempt_id, request.attempt.attempt_id)
                self.assertEqual(
                    match_channel_policy_result(
                        request, result, observed_at_ms=result.result.completed_at_ms
                    ),
                    "candidate",
                )
                self.assertEqual(
                    match_channel_policy_result(
                        request, result, observed_at_ms=request.deadline_at_ms
                    ),
                    "expired",
                )

    def test_stable_key_uses_only_original_operation_uuid(self) -> None:
        key = "p2_00000000000040008000000000000002"
        self.assertEqual(channel_policy_key(OPERATION), key)
        for changed in (
            replace(origin(), profile_id=RECEIPT),
            replace(origin(), input_receipt_id=PROFILE),
            replace(origin(), payload_sha256="b" * 64),
            replace(origin(), payload_byte_length=1),
        ):
            made = produce_channel_policy_request(producer_input(changed))
            self.assertEqual(made.delegation_id, key)
            self.assertNotEqual(made.input_fingerprint, request_value().input_fingerprint)

    def test_changed_operation_requires_matching_inner_key(self) -> None:
        value = producer_input(replace(origin(), operation_key=RECEIPT), inner_request())
        with self.assertRaises(ContractError) as caught:
            produce_channel_policy_request(value)
        self.assertEqual(caught.exception.code, "identity_conflict")
        changed = produce_channel_policy_request(
            producer_input(replace(origin(), operation_key=RECEIPT))
        )
        self.assertEqual(changed.delegation_id, channel_policy_key(RECEIPT))

    def test_changed_logical_request_fields_change_outer_fingerprint(self) -> None:
        original = request_value()
        proposals = (
            replace(original.request, deadline_at_ms=original.deadline_at_ms + 1),
            replace(original.request, request_revision=original.request_revision + 1),
            replace(original.request, conversation_id="other_conversation"),
            replace(original.request, scope=replace(original.scope, tenant_id="other_tenant")),
            replace(
                original.request,
                evidence=(replace(original.request.evidence[0], sha256="b" * 64),)
                + original.request.evidence[1:],
            ),
        )
        for proposal in proposals:
            wire = proposal.to_wire()
            wire.pop("input_fingerprint")
            inner = produce_fixed_policy_request(wire)
            with self.subTest(inner=inner.input_fingerprint):
                changed = produce_channel_policy_request(producer_input(request=inner))
                self.assertNotEqual(changed.input_fingerprint, original.input_fingerprint)

    def test_issued_attempt_changes_preserve_both_logical_fingerprints(self) -> None:
        original = request_value()
        issued = replace(original.request, attempt=Attempt("attempt_issued", 2))
        changed = produce_channel_policy_request(producer_input(request=issued))
        self.assertEqual(changed.request.input_fingerprint, original.request.input_fingerprint)
        self.assertEqual(changed.input_fingerprint, original.input_fingerprint)
        self.assertNotEqual(
            encode_channel_policy_request(changed), encode_channel_policy_request(original)
        )

    def test_claimed_inner_and_outer_fingerprints_are_independently_verified(self) -> None:
        for target in ("inner", "outer"):
            wire = cast(dict[str, Any], request_value().to_wire())
            if target == "inner":
                wire["request"]["input_fingerprint"] = "0" * 64
            else:
                wire["input_fingerprint"] = "0" * 64
            with self.subTest(target=target), self.assertRaises(ContractError) as caught:
                parse_channel_policy_request(canonical(wire))
            self.assertEqual(caught.exception.code, "identity_conflict")

    def test_origin_uuid_kind_digest_and_strict_byte_length(self) -> None:
        invalid: tuple[tuple[str, object], ...] = (
            ("kind", "sms"),
            ("profile_id", "abcdefab-cdef-4abc-8abc-abcdefabcdef".upper()),
            ("operation_key", "00000000-0000-1000-8000-000000000002"),
            ("input_receipt_id", RECEIPT.replace("-", "")),
            ("profile_id", True),
            ("profile_id", "secret_\ud800"),
            ("payload_sha256", "A" * 64),
            ("payload_sha256", "a" * 63),
            ("payload_byte_length", True),
            ("payload_byte_length", 0),
            ("payload_byte_length", -1),
            ("payload_byte_length", 32769),
            ("payload_byte_length", "32768"),
        )
        for key, bad in invalid:
            wire = cast(dict[str, Any], request_value().to_wire())
            wire["origin"][key] = bad
            with self.subTest(key=key, bad=repr(bad)), self.assertRaises(ContractError):
                parse_channel_policy_request(canonical(wire))
        for length in (1, 32768):
            made = produce_channel_policy_request(
                producer_input(replace(origin(), payload_byte_length=length))
            )
            self.assertEqual(made.origin.payload_byte_length, length)

    def test_headers_unknown_fields_and_bool_versions_are_closed(self) -> None:
        for base, parser, version in (
            (request_value().to_wire(), parse_channel_policy_request, "input_schema_version"),
            (result_value().to_wire(), parse_channel_policy_result, "result_schema_version"),
        ):
            for field, bad in (
                ("schema_version", True),
                ("schema_version", 3),
                (version, True),
                (version, 2),
                ("kind", "unexpected"),
                ("capability", "booking.other"),
                ("extra", "secret_sentinel"),
            ):
                mutated = copy.deepcopy(base)
                mutated[field] = bad
                with self.subTest(field=field, bad=bad), self.assertRaises(ContractError):
                    parser(canonical(mutated))
        for nested in ("origin", "request"):
            wire = cast(dict[str, Any], request_value().to_wire())
            wire[nested]["extra"] = "secret_sentinel"
            with self.subTest(nested=nested), self.assertRaises(ContractError):
                parse_channel_policy_request(canonical(wire))
        wire = cast(dict[str, Any], result_value().to_wire())
        wire["result"]["extra"] = "secret_sentinel"
        with self.assertRaises(ContractError):
            parse_channel_policy_result(canonical(wire))

    def test_duplicate_keys_invalid_utf8_and_numbers_fail_before_contract_use(self) -> None:
        for raw, parser in (
            (encode_channel_policy_request(request_value()), parse_channel_policy_request),
            (encode_channel_policy_result(result_value()), parse_channel_policy_result),
        ):
            duplicates = b'{"schema_version":1,' + raw[1:]
            for invalid in (duplicates, b"\xff" + raw, b"true", b"NaN"):
                with self.subTest(prefix=invalid[:20]), self.assertRaises(ContractError):
                    parser(invalid)
        raw = encode_channel_policy_request(request_value())
        needle = b'"payload_byte_length":32768'
        for replacement in (needle + b"," + needle, b'"payload_byte_length":1.0'):
            with self.assertRaises(ContractError):
                parse_channel_policy_request(raw.replace(needle, replacement))

    def test_entire_request_and_result_byte_bounds_are_independent(self) -> None:
        for value, encoder, parser, maximum, constant in (
            (
                request_value(),
                encode_channel_policy_request,
                parse_channel_policy_request,
                16384,
                "MAX_REQUEST_BYTES",
            ),
            (
                result_value(),
                encode_channel_policy_result,
                parse_channel_policy_result,
                8192,
                "MAX_RESULT_BYTES",
            ),
        ):
            raw = encoder(cast(Any, value))
            self.assertLess(len(raw), maximum)
            self.assertEqual(parser(b" " * (maximum - len(raw)) + raw), value)
            with self.assertRaises(ContractError):
                parser(b" " * (maximum + 1 - len(raw)) + raw)
            # A valid inner v2 does not bypass the complete outer encoder bound.
            with (
                patch("delegation_reliability.channel_policy_contracts." + constant, len(raw) - 1),
                self.assertRaises(ContractError),
            ):
                encoder(cast(Any, value))

    def test_result_wrap_preserves_inner_bytes_and_matches_original_request(self) -> None:
        request = request_value()
        nested = inner_result(request.request)
        result = produce_channel_policy_result(request, nested)
        self.assertEqual(
            encode_fixed_policy_result(result.result), encode_fixed_policy_result(nested)
        )
        self.assertEqual(result.input_fingerprint, request.input_fingerprint)
        self.assertEqual(parse_channel_policy_result(encode_channel_policy_result(result)), result)
        self.assertEqual(
            match_channel_policy_result(request, result, observed_at_ms=FIXTURE["observed_at_ms"]),
            "candidate",
        )
        self.assertEqual(
            match_channel_policy_result(request, result, observed_at_ms=request.deadline_at_ms),
            "expired",
        )

    def test_result_outer_and_inner_identity_issued_attempt_and_evidence_are_matched(self) -> None:
        request = request_value()
        good = inner_result(request.request)
        invalid = (
            replace(good, attempt_id="other_attempt"),
            replace(good, delegation_id="other_delegation"),
            replace(good, scope=replace(good.scope, account_id="other_account")),
            replace(good, case_id="other_case"),
            replace(good, request_revision=good.request_revision + 1),
            replace(good, input_fingerprint="0" * 64),
            replace(good, rule_refs=(replace(good.rule_refs[0], sha256="b" * 64),)),
        )
        for nested in invalid:
            with self.subTest(nested=nested.attempt_id), self.assertRaises(ContractError):
                produce_channel_policy_result(request, nested)
        result = replace(produce_channel_policy_result(request, good), input_fingerprint="0" * 64)
        with self.assertRaises(ContractError) as caught:
            match_channel_policy_result(request, result, observed_at_ms=FIXTURE["observed_at_ms"])
        self.assertEqual(caught.exception.code, "result_mismatch")

    def test_clarification_and_observation_time_keep_original_v2_semantics(self) -> None:
        request = request_value()
        missing = replace(
            inner_result(request.request), eligible=None, uncertainty="missing", fact_refs=()
        )
        wrapped = produce_channel_policy_result(request, missing)
        self.assertEqual(
            match_channel_policy_result(request, wrapped, observed_at_ms=FIXTURE["observed_at_ms"]),
            "clarification",
        )
        self.assertEqual(
            match_channel_policy_result(request, wrapped, observed_at_ms=request.deadline_at_ms),
            "expired",
        )
        with self.assertRaises(ContractError):
            match_channel_policy_result(request, wrapped, observed_at_ms=True)

    def test_wrapping_correlation_does_not_claim_factual_truth(self) -> None:
        request = request_value()
        wrong = replace(inner_result(request.request), eligible=False)
        wrapped = produce_channel_policy_result(request, wrong)
        self.assertEqual(
            match_channel_policy_result(request, wrapped, observed_at_ms=FIXTURE["observed_at_ms"]),
            "candidate",
        )
        records = tuple(
            EvidenceRecord(request.scope, ref, FIXTURE[key].encode())
            for ref, key in zip(
                request.request.evidence, ("policy_body_utf8", "facts_body_utf8"), strict=True
            )
        )
        with self.assertRaises(ContractError) as caught:
            verify_fixed_policy_facts(
                request.request, wrapped.result, records, observed_at_ms=FIXTURE["observed_at_ms"]
            )
        self.assertEqual(caught.exception.code, "unsupported_facts")

    def test_producer_inputs_are_snapshotted_and_typed_encoders_revalidate(self) -> None:
        source = cast(dict[str, Any], producer_input())
        made = produce_channel_policy_request(source)
        source["origin"]["payload_sha256"] = "0" * 64
        source["request"]["context_snapshot"]["policy_version"] = "changed"
        self.assertEqual(made.origin.payload_sha256, "a" * 64)
        self.assertEqual(made.request.context_snapshot.policy_version, "notice_v1")
        with self.assertRaises(ContractError):
            encode_channel_policy_request(replace(made, origin=cast(Any, made.origin.to_wire())))
        corrupt = copy.deepcopy(made)
        object.__setattr__(corrupt.request, "scope", {"tenant_id": "forged"})
        with self.assertRaises(ContractError):
            encode_channel_policy_request(corrupt)
        with self.assertRaises(ContractError):
            encode_channel_policy_result(replace(result_value(), result=cast(Any, {})))

    def test_public_errors_do_not_retain_received_text(self) -> None:
        sentinel = "PRIVATE_ORIGIN_SENTINEL"
        wire = cast(dict[str, Any], request_value().to_wire())
        wire["origin"]["profile_id"] = sentinel
        with self.assertRaises(ContractError) as caught:
            parse_channel_policy_request(canonical(wire))
        self.assertNotIn(sentinel, str(caught.exception))
        self.assertEqual(caught.exception.args, (caught.exception.code,))
        for bad in (sentinel, "abcdefab-cdef-4abc-8abc-abcdefabcdef".upper(), True):
            with self.subTest(bad=bad), self.assertRaises(ContractError):
                channel_policy_key(cast(str, bad))

    def test_original_v2_and_legacy_wire_defaults_remain_separate(self) -> None:
        original = parse_fixed_policy_request(canonical(FIXTURE["request"]))
        result = parse_fixed_policy_result(canonical(FIXTURE["result"]))
        self.assertEqual(
            encode_fixed_policy_request(original).decode(), FIXTURE["request_canonical"]
        )
        self.assertEqual(encode_fixed_policy_result(result).decode(), FIXTURE["result_canonical"])
        for parser in (parse_request, parse_fixed_policy_request):
            with self.assertRaises(ContractError):
                parser(encode_channel_policy_request(request_value()))
        with self.assertRaises(ContractError):
            parse_channel_policy_request(encode_fixed_policy_request(original))


if __name__ == "__main__":
    unittest.main()
