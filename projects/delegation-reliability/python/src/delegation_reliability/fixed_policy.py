"""Read-only policy-v2 factual verification and configured finite HTTP consumer."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from .contracts import (
    ContractError,
    EvidenceRef,
    Scope,
    decode,
    identifier,
    integer,
    object_fields,
    text,
)
from .fixed_policy_contracts import (
    FIXED_POLICY_MINIMUM_DAYS,
    FIXED_POLICY_RULE,
    FIXED_POLICY_VERSION,
    FixedPolicyApplicability,
    FixedPolicyFactEvidence,
    FixedPolicyRequest,
    FixedPolicyResult,
    encode_fixed_policy_request,
    encode_fixed_policy_result,
    match_fixed_policy_result,
    parse_fixed_policy_request,
    parse_fixed_policy_result,
)
from .http_client import AttemptObservation, SpecialistClient, SpecialistEndpoint
from .security import EvidenceRecord, EvidenceRegistry


def snapshot_fixed_policy_records(
    records: tuple[EvidenceRecord, ...],
) -> tuple[EvidenceRecord, ...]:
    """Copy and bound every supplied record; duplicate scoped IDs never hide facts."""
    if type(records) is not tuple or len(records) > 32:
        raise ContractError()
    copied = []
    for record in records:
        if (
            type(record) is not EvidenceRecord
            or type(record.scope) is not Scope
            or (type(record.reference) is not EvidenceRef or type(record.body) is not bytes)
        ):
            raise ContractError()
        ref = record.reference
        copied.append(
            EvidenceRecord(
                Scope(record.scope.tenant_id, record.scope.account_id),
                EvidenceRef(
                    ref.source_id,
                    ref.version,
                    ref.sha256,
                    ref.media_type,
                    ref.byte_length,
                    ref.width,
                    ref.height,
                ),
                bytes(record.body),
            )
        )
    snapshot = tuple(copied)
    EvidenceRegistry(snapshot)
    return snapshot


def _snapshot_fixed_policy_pair(records: tuple[EvidenceRecord, ...]) -> tuple[EvidenceRecord, ...]:
    """Admit exactly two small JSON records before generic evidence copying."""
    if type(records) is not tuple or len(records) != 2:
        raise ContractError()
    for record in records:
        if (
            type(record) is not EvidenceRecord
            or type(record.scope) is not Scope
            or type(record.reference) is not EvidenceRef
            or type(record.body) is not bytes
            or not 1 <= len(record.body) <= 4096
            or record.reference.media_type != "application/json"
            or record.reference.width is not None
            or record.reference.height is not None
        ):
            raise ContractError()
        if type(decode(record.body, 4096)) is not dict:
            raise ContractError()
    return snapshot_fixed_policy_records(records)


def verify_fixed_policy_facts(
    request: FixedPolicyRequest,
    result: FixedPolicyResult,
    records: tuple[EvidenceRecord, ...],
    *,
    observed_at_ms: int,
) -> FixedPolicyApplicability:
    """Verify exact source facts before reporting time; no action permission results."""
    request = parse_fixed_policy_request(encode_fixed_policy_request(request))
    result = parse_fixed_policy_result(encode_fixed_policy_result(result))
    records = snapshot_fixed_policy_records(records)
    timeliness = match_fixed_policy_result(request, result, observed_at_ms=observed_at_ms)
    selected = []
    for ref in request.evidence:
        matches = [
            record
            for record in records
            if record.scope == request.scope and record.reference.source_id == ref.source_id
        ]
        if len(matches) != 1 or matches[0].reference != ref:
            raise ContractError("evidence_mismatch")
        selected.append(matches[0])
    policy = object_fields(
        decode(selected[0].body, 4096),
        {
            "schema_version",
            "kind",
            "policy_version",
            "rule_id",
            "minimum_notice_days",
            "note",
        },
    )
    text(policy["note"])
    if (
        type(policy["schema_version"]) is not int
        or policy["schema_version"] != 1
        or (
            policy["kind"] != "booking.notice_policy"
            or policy["policy_version"] != request.context_snapshot.policy_version
            or policy["policy_version"] != FIXED_POLICY_VERSION
            or policy["rule_id"] != FIXED_POLICY_RULE
            or type(policy["minimum_notice_days"]) is not int
            or policy["minimum_notice_days"] != FIXED_POLICY_MINIMUM_DAYS
        )
    ):
        raise ContractError("unsupported_facts")
    facts = object_fields(
        decode(selected[1].body, 4096),
        {
            "schema_version",
            "kind",
            "observations",
            "note",
        },
    )
    text(facts["note"])
    if (
        type(facts["schema_version"]) is not int
        or facts["schema_version"] != 1
        or (
            facts["kind"] != "booking.notice_facts"
            or type(facts["observations"]) is not list
            or len(facts["observations"]) > 2
        )
    ):
        raise ContractError("unsupported_facts")
    expected_facts = []
    source = request.evidence[1]
    for item in facts["observations"]:
        observation = object_fields(item, {"fact_id", "days_before_arrival"})
        expected_facts.append(
            FixedPolicyFactEvidence(
                source.source_id,
                source.version,
                source.sha256,
                identifier(observation["fact_id"]),
                integer(observation["days_before_arrival"], 0, 3650),
            )
        )
    if len({ref.fact_id for ref in expected_facts}) != len(expected_facts):
        raise ContractError("unsupported_facts")
    rule = result.rule_refs[0]
    if rule.rule_id != FIXED_POLICY_RULE or rule.minimum_notice_days != FIXED_POLICY_MINIMUM_DAYS:
        raise ContractError("unsupported_facts")
    if sorted(result.fact_refs, key=lambda ref: ref.fact_id) != sorted(
        expected_facts, key=lambda ref: ref.fact_id
    ):
        raise ContractError("unsupported_facts")
    values = {ref.days_before_arrival for ref in expected_facts}
    uncertainty = "missing" if not values else "none" if len(values) == 1 else "conflicting"
    eligible = (
        expected_facts[0].days_before_arrival >= FIXED_POLICY_MINIMUM_DAYS
        if uncertainty == "none"
        else None
    )
    if result.uncertainty != uncertainty or result.eligible is not eligible:
        raise ContractError("unsupported_facts")
    return timeliness


@dataclass(frozen=True, slots=True)
class FixedPolicyResultObservation:
    """Fully source-verified history; never commit eligibility or action permission."""

    result: FixedPolicyResult
    applicability: FixedPolicyApplicability
    observed_at_ms: int


class FixedPolicySpecialistClient:
    """Own the existing bounded transport; semantic verification is explicit."""

    def __init__(
        self,
        endpoint: SpecialistEndpoint,
        authorization: str,
        *,
        timeout_ms: int = 5000,
        max_active: int = 4,
        cleanup_ms: int = 1000,
    ) -> None:
        self._transport = SpecialistClient(
            endpoint,
            authorization,
            timeout_ms=timeout_ms,
            max_active=max_active,
            cleanup_ms=cleanup_ms,
        )

    @property
    def active(self) -> int:
        return self._transport.active

    def metrics(self) -> MappingProxyType[str, int]:
        return self._transport.metrics()

    async def invoke(self, request: FixedPolicyRequest) -> FixedPolicyResult:
        return await self._transport.invoke_fixed_policy(request)

    async def invoke_observed(
        self, request: FixedPolicyRequest, *, evidence: tuple[EvidenceRecord, ...]
    ) -> FixedPolicyResultObservation:
        """Verify every immutable witness, including a historical expired body."""
        return await self._transport.invoke_fixed_policy_observed(request, evidence=evidence)

    async def status(self, request: FixedPolicyRequest) -> AttemptObservation:
        return await self._transport.status_fixed_policy(request)

    async def cancel(self, request: FixedPolicyRequest) -> AttemptObservation:
        return await self._transport.cancel_fixed_policy(request)

    async def close(self) -> None:
        await self._transport.close()
