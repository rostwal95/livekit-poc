"""Closed typed codec adapters for the one existing durable execution engine."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Generic, Literal, Protocol, TypeVar

from .channel_policy_contracts import (
    ChannelPolicyRequest,
    ChannelPolicyResult,
    encode_channel_policy_request,
    encode_channel_policy_result,
    match_channel_policy_result,
    parse_channel_policy_request,
    parse_channel_policy_result,
    produce_channel_policy_result,
)
from .contracts import (
    Attempt,
    ContractError,
    DelegationRequest,
    DelegationResult,
    canonical,
    encode_request,
    encode_result,
    match_result,
    parse_request,
    parse_result,
)
from .fixed_policy import FixedPolicyResultObservation, verify_fixed_policy_facts
from .fixed_policy_contracts import (
    FixedPolicyRequest,
    FixedPolicyResult,
    encode_fixed_policy_request,
    encode_fixed_policy_result,
    match_fixed_policy_result,
    parse_fixed_policy_request,
    parse_fixed_policy_result,
)
from .http_client import SpecialistResultObservation
from .security import EvidenceRecord, verify_policy_facts

RequestT = TypeVar("RequestT", DelegationRequest, FixedPolicyRequest, ChannelPolicyRequest)
ResultT = TypeVar("ResultT", DelegationResult, FixedPolicyResult, ChannelPolicyResult)
Q_contra = TypeVar("Q_contra", contravariant=True)
R_co = TypeVar("R_co", covariant=True)
PolicyFacts = Literal["candidate", "clarification", "expired"]


class _PolicyCodec(Protocol[RequestT, ResultT]):
    def parse_request(self, body: bytes) -> RequestT: ...
    def encode_request(self, request: RequestT) -> bytes: ...
    def parse_result(self, body: bytes) -> ResultT: ...
    def encode_result(self, result: ResultT) -> bytes: ...
    def with_attempt(self, request: RequestT, attempt: Attempt) -> RequestT: ...
    def replay_identity(self, request: RequestT) -> bytes: ...
    def origin_identity(self, request: RequestT) -> bytes: ...
    def match(
        self, request: RequestT, result: ResultT, at: int
    ) -> Literal["candidate", "expired"]: ...
    def verify(
        self, request: RequestT, result: ResultT, records: tuple[EvidenceRecord, ...], at: int
    ) -> PolicyFacts: ...


class _V1Codec:
    def parse_request(self, body: bytes) -> DelegationRequest:
        return parse_request(body)

    def encode_request(self, request: DelegationRequest) -> bytes:
        return encode_request(request)

    def parse_result(self, body: bytes) -> DelegationResult:
        return parse_result(body)

    def encode_result(self, result: DelegationResult) -> bytes:
        return encode_result(result)

    def with_attempt(self, request: DelegationRequest, attempt: Attempt) -> DelegationRequest:
        return replace(request, attempt=attempt)

    def replay_identity(self, request: DelegationRequest) -> bytes:
        wire = request.to_wire()
        wire.pop("attempt")
        return canonical(wire)

    def origin_identity(self, request: DelegationRequest) -> bytes:
        raise ContractError()

    def match(
        self, request: DelegationRequest, result: DelegationResult, at: int
    ) -> Literal["candidate", "expired"]:
        return match_result(request, result, observed_at_ms=at)

    def verify(
        self,
        request: DelegationRequest,
        result: DelegationResult,
        records: tuple[EvidenceRecord, ...],
        at: int,
    ) -> PolicyFacts:
        return verify_policy_facts(request, result, records, observed_at_ms=at)


class _FixedCodec:
    def parse_request(self, body: bytes) -> FixedPolicyRequest:
        return parse_fixed_policy_request(body)

    def encode_request(self, request: FixedPolicyRequest) -> bytes:
        return encode_fixed_policy_request(request)

    def parse_result(self, body: bytes) -> FixedPolicyResult:
        return parse_fixed_policy_result(body)

    def encode_result(self, result: FixedPolicyResult) -> bytes:
        return encode_fixed_policy_result(result)

    def with_attempt(self, request: FixedPolicyRequest, attempt: Attempt) -> FixedPolicyRequest:
        return replace(request, attempt=attempt)

    def replay_identity(self, request: FixedPolicyRequest) -> bytes:
        wire = request.to_wire()
        wire.pop("attempt")
        return canonical(wire)

    def origin_identity(self, request: FixedPolicyRequest) -> bytes:
        raise ContractError()

    def match(
        self, request: FixedPolicyRequest, result: FixedPolicyResult, at: int
    ) -> Literal["candidate", "expired"]:
        return (
            "expired"
            if match_fixed_policy_result(request, result, observed_at_ms=at) == "expired"
            else "candidate"
        )

    def verify(
        self,
        request: FixedPolicyRequest,
        result: FixedPolicyResult,
        records: tuple[EvidenceRecord, ...],
        at: int,
    ) -> PolicyFacts:
        return verify_fixed_policy_facts(request, result, records, observed_at_ms=at)


class _ChannelCodec:
    def parse_request(self, body: bytes) -> ChannelPolicyRequest:
        return parse_channel_policy_request(body)

    def encode_request(self, request: ChannelPolicyRequest) -> bytes:
        return encode_channel_policy_request(request)

    def parse_result(self, body: bytes) -> ChannelPolicyResult:
        return parse_channel_policy_result(body)

    def encode_result(self, result: ChannelPolicyResult) -> bytes:
        return encode_channel_policy_result(result)

    def with_attempt(self, request: ChannelPolicyRequest, attempt: Attempt) -> ChannelPolicyRequest:
        return replace(request, request=replace(request.request, attempt=attempt))

    def replay_identity(self, request: ChannelPolicyRequest) -> bytes:
        wire = request.to_wire()
        inner = request.request.to_wire()
        inner.pop("attempt")
        wire["request"] = inner
        return canonical(wire)

    def origin_identity(self, request: ChannelPolicyRequest) -> bytes:
        return canonical(
            {
                "origin": request.origin.to_wire(),
                "scope": {
                    "tenant_id": request.scope.tenant_id,
                    "account_id": request.scope.account_id,
                },
                "delegation_id": request.delegation_id,
                "case_id": request.case_id,
                "request_revision": request.request_revision,
                "conversation_id": request.conversation_id,
            }
        )

    def match(
        self, request: ChannelPolicyRequest, result: ChannelPolicyResult, at: int
    ) -> Literal["candidate", "expired"]:
        return (
            "expired"
            if match_channel_policy_result(request, result, observed_at_ms=at) == "expired"
            else "candidate"
        )

    def verify(
        self,
        request: ChannelPolicyRequest,
        result: ChannelPolicyResult,
        records: tuple[EvidenceRecord, ...],
        at: int,
    ) -> PolicyFacts:
        match_channel_policy_result(request, result, observed_at_ms=at)
        return verify_fixed_policy_facts(request.request, result.result, records, observed_at_ms=at)


V1_CODEC: _PolicyCodec[DelegationRequest, DelegationResult] = _V1Codec()
FIXED_CODEC: _PolicyCodec[FixedPolicyRequest, FixedPolicyResult] = _FixedCodec()
CHANNEL_CODEC: _PolicyCodec[ChannelPolicyRequest, ChannelPolicyResult] = _ChannelCodec()


@dataclass(frozen=True, slots=True)
class _ObservedResult(Generic[R_co]):
    result: R_co
    timeliness: Literal["candidate", "expired"]
    observed_at_ms: int
    facts: PolicyFacts | None = None


class _Invocation(Protocol[Q_contra, R_co]):
    async def invoke_observed(self, request: Q_contra) -> _ObservedResult[R_co]: ...
    async def close(self) -> None: ...


class _V1Port(Protocol):
    async def invoke_observed(self, request: DelegationRequest) -> SpecialistResultObservation: ...
    async def close(self) -> None: ...


class _FixedPort(Protocol):
    async def invoke_observed(
        self, request: FixedPolicyRequest, *, evidence: tuple[EvidenceRecord, ...]
    ) -> FixedPolicyResultObservation: ...
    async def close(self) -> None: ...


class _V1Invocation(_Invocation[DelegationRequest, DelegationResult]):
    def __init__(self, port: _V1Port) -> None:
        self._port = port

    async def invoke_observed(
        self, request: DelegationRequest
    ) -> _ObservedResult[DelegationResult]:
        observed = await self._port.invoke_observed(request)
        if type(observed) is not SpecialistResultObservation:
            raise ContractError()
        return _ObservedResult(observed.result, observed.timeliness, observed.observed_at_ms)

    async def close(self) -> None:
        await self._port.close()


class _FixedInvocation(_Invocation[FixedPolicyRequest, FixedPolicyResult]):
    def __init__(self, port: _FixedPort, records: tuple[EvidenceRecord, ...]) -> None:
        self._port, self._records = port, records

    async def invoke_observed(
        self, request: FixedPolicyRequest
    ) -> _ObservedResult[FixedPolicyResult]:
        observed = await self._port.invoke_observed(request, evidence=self._records)
        if (
            type(observed) is not FixedPolicyResultObservation
            or type(observed.applicability) is not str
            or observed.applicability not in {"candidate", "clarification", "expired"}
        ):
            raise ContractError()
        return _ObservedResult(
            observed.result,
            "expired" if observed.applicability == "expired" else "candidate",
            observed.observed_at_ms,
            observed.applicability,
        )

    async def close(self) -> None:
        await self._port.close()


class _ChannelInvocation(_Invocation[ChannelPolicyRequest, ChannelPolicyResult]):
    """Only the explicit specialist boundary sees the unchanged inner v2 request."""

    def __init__(self, port: _FixedPort, records: tuple[EvidenceRecord, ...]) -> None:
        self._inner, self._records = _FixedInvocation(port, records), records

    async def invoke_observed(
        self, request: ChannelPolicyRequest
    ) -> _ObservedResult[ChannelPolicyResult]:
        snapshot = parse_channel_policy_request(encode_channel_policy_request(request))
        if any(
            sum(
                record.scope == snapshot.scope and record.reference == reference
                for record in self._records
            )
            != 1
            for reference in snapshot.request.evidence
        ):
            raise ContractError("evidence_mismatch")
        observed = await self._inner.invoke_observed(snapshot.request)
        inner = parse_fixed_policy_result(encode_fixed_policy_result(observed.result))
        facts = verify_fixed_policy_facts(
            snapshot.request, inner, self._records, observed_at_ms=observed.observed_at_ms
        )
        if observed.facts != facts:
            raise ContractError()
        result = produce_channel_policy_result(snapshot, inner)
        return _ObservedResult(result, observed.timeliness, observed.observed_at_ms, facts)

    async def close(self) -> None:
        await self._inner.close()
