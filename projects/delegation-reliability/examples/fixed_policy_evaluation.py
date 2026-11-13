"""Explicit configured policy-v2 consumer; no implicit setup or action authority."""

from __future__ import annotations

import time
from typing import Protocol

from delegation_reliability.contracts import ContractError
from delegation_reliability.fixed_policy import (
    snapshot_fixed_policy_records,
    verify_fixed_policy_facts,
)
from delegation_reliability.fixed_policy_contracts import (
    FixedPolicyRequest,
    FixedPolicyResult,
    encode_fixed_policy_request,
    encode_fixed_policy_result,
    parse_fixed_policy_request,
    parse_fixed_policy_result,
)
from delegation_reliability.security import EvidenceRecord


class FixedPolicyInvocationPort(Protocol):
    async def invoke(self, request: FixedPolicyRequest) -> FixedPolicyResult: ...


async def evaluate_fixed_policy(
    *,
    client: FixedPolicyInvocationPort,
    request: FixedPolicyRequest,
    records: tuple[EvidenceRecord, ...],
) -> FixedPolicyResult:
    """Return only supported facts or clarification; the caller owns client lifetime."""
    snapshot = parse_fixed_policy_request(encode_fixed_policy_request(request))
    evidence = snapshot_fixed_policy_records(records)
    observed = await client.invoke(snapshot)
    result = parse_fixed_policy_result(encode_fixed_policy_result(observed))
    if (
        verify_fixed_policy_facts(
            snapshot, result, evidence, observed_at_ms=time.time_ns() // 1_000_000
        )
        == "expired"
    ):
        raise ContractError("expired")
    return result
