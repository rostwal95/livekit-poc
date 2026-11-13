"""Local principal binding, immutable evidence and finite ephemeral attempt permits.

This module performs no dispatch, background work, retries or durable acceptance.
Trusted application configuration supplies grants, source bytes and observed time.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import threading
from dataclasses import asdict, dataclass, field
from typing import Literal, cast, overload

from .contracts import (
    CAPABILITY,
    MAX_DEADLINE_WINDOW_MS,
    MAX_TIMESTAMP_MS,
    ContextSnapshot,
    ContractError,
    DelegationRequest,
    DelegationResult,
    EvidenceRef,
    Scope,
    canonical,
    decode,
    digest,
    encode_request,
    identifier,
    integer,
    match_result,
    object_fields,
    parse_request,
)
from .document_contracts import (
    DOCUMENT_CAPABILITY,
    DocumentRequest,
    encode_document_request,
    parse_document_request,
)
from .fixed_policy_contracts import (
    FixedPolicyRequest,
    encode_fixed_policy_request,
    parse_fixed_policy_request,
)

SupportedRequest = DelegationRequest | DocumentRequest | FixedPolicyRequest


def _snapshot_supported(request: SupportedRequest) -> SupportedRequest:
    if type(request) is FixedPolicyRequest:
        return parse_fixed_policy_request(encode_fixed_policy_request(request))
    if type(request) is DocumentRequest:
        return parse_document_request(encode_document_request(request))
    return parse_request(encode_request(cast(DelegationRequest, request)))


Operation = Literal["invoke", "result", "cancel", "evidence"]
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z", re.ASCII)


def token_digest(token: str) -> str:
    if type(token) is not str or _TOKEN.fullmatch(token) is None:
        raise ContractError("unauthorized")
    return hashlib.sha256(token.encode("ascii")).hexdigest()


@dataclass(frozen=True, slots=True)
class ScopeGrant:
    scope: Scope
    invoke_capabilities: tuple[str, ...] = ()
    result_capabilities: tuple[str, ...] = ()
    cancel_capabilities: tuple[str, ...] = ()
    evidence_sources: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PrincipalGrant:
    principal_id: str
    token_sha256: str = field(repr=False)
    scopes: tuple[ScopeGrant, ...]


class LocalTrust:
    def __init__(self, grants: tuple[PrincipalGrant, ...]) -> None:
        if type(grants) is not tuple or not 1 <= len(grants) <= 32:
            raise ContractError()
        known_ids, known_keys = set[str](), set[str]()
        for grant in grants:
            if type(grant) is not PrincipalGrant:
                raise ContractError()
            identifier(grant.principal_id)
            digest(grant.token_sha256)
            if grant.principal_id in known_ids or grant.token_sha256 in known_keys:
                raise ContractError()
            known_ids.add(grant.principal_id)
            known_keys.add(grant.token_sha256)
            if type(grant.scopes) is not tuple or not 1 <= len(grant.scopes) <= 16:
                raise ContractError()
            seen = set[Scope]()
            for scope in grant.scopes:
                if type(scope) is not ScopeGrant or type(scope.scope) is not Scope:
                    raise ContractError()
                identifier(scope.scope.tenant_id)
                identifier(scope.scope.account_id)
                if scope.scope in seen:
                    raise ContractError()
                seen.add(scope.scope)
                for capabilities in (
                    scope.invoke_capabilities,
                    scope.result_capabilities,
                    scope.cancel_capabilities,
                ):
                    if (
                        type(capabilities) is not tuple
                        or len(capabilities) > 2
                        or any(
                            type(item) is not str or item not in (CAPABILITY, DOCUMENT_CAPABILITY)
                            for item in capabilities
                        )
                        or len(set(capabilities)) != len(capabilities)
                    ):
                        raise ContractError()
                if (
                    type(scope.evidence_sources) is not tuple
                    or len(scope.evidence_sources) > 64
                    or any(type(item) is not str for item in scope.evidence_sources)
                    or len(set(scope.evidence_sources)) != len(scope.evidence_sources)
                ):
                    raise ContractError()
                for source in scope.evidence_sources:
                    identifier(source)
        canonical([asdict(grant) for grant in grants])
        self._grants = grants

    def authenticate(self, authorization: str) -> PrincipalGrant:
        if (
            type(authorization) is not str
            or len(authorization) != 50
            or not authorization.startswith("Bearer ")
        ):
            raise ContractError("unauthorized")
        supplied = token_digest(authorization[7:])
        match = None
        # Equal-sized digests; bounded full scan avoids early-match token comparison.
        for grant in self._grants:
            if hmac.compare_digest(supplied, grant.token_sha256):
                match = grant
        if match is None:
            raise ContractError("unauthorized")
        return match

    def authorize(
        self,
        authorization: str,
        operation: Operation,
        request: SupportedRequest,
        *,
        source_id: str | None = None,
    ) -> str:
        grant = self.authenticate(authorization)
        for scope in grant.scopes:
            if scope.scope != request.scope:
                continue
            if operation == "evidence":
                if source_id is not None and source_id in scope.evidence_sources:
                    return grant.principal_id
            elif operation in ("invoke", "result", "cancel"):
                capabilities = {
                    "invoke": scope.invoke_capabilities,
                    "result": scope.result_capabilities,
                    "cancel": scope.cancel_capabilities,
                }[operation]
                if (
                    DOCUMENT_CAPABILITY if type(request) is DocumentRequest else CAPABILITY
                ) in capabilities:
                    return grant.principal_id
        raise ContractError("unauthorized")


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    scope: Scope
    reference: EvidenceRef
    body: bytes = field(repr=False)


class EvidenceRegistry:
    def __init__(self, records: tuple[EvidenceRecord, ...]) -> None:
        if type(records) is not tuple or len(records) > 32:
            raise ContractError()
        total = 0
        index: dict[tuple[Scope, str], EvidenceRecord] = {}
        for record in records:
            if (
                type(record) is not EvidenceRecord
                or type(record.body) is not bytes
                or type(record.scope) is not Scope
                or type(record.reference) is not EvidenceRef
            ):
                raise ContractError()
            ref = record.reference
            total += len(record.body)
            if not 0 < len(record.body) <= 2_097_152 or total > 8_388_608:
                raise ContractError()
            identifier(record.scope.tenant_id)
            identifier(record.scope.account_id)
            identifier(ref.source_id)
            identifier(ref.version)
            digest(ref.sha256)
            integer(ref.byte_length, 1, 2_097_152)
            if type(ref.media_type) is not str:
                raise ContractError()
            key = (record.scope, ref.source_id)
            if (
                key in index
                or len(record.body) != ref.byte_length
                or hashlib.sha256(record.body).hexdigest() != ref.sha256
            ):
                raise ContractError("evidence_mismatch")
            if ref.media_type == "application/json":
                if len(record.body) > 4096 or ref.width is not None or ref.height is not None:
                    raise ContractError()
            elif ref.media_type == "image/png":
                integer(ref.width, 1, 2048)
                integer(ref.height, 1, 2048)
            else:
                raise ContractError()
            identifier(record.scope.tenant_id)
            identifier(record.scope.account_id)
            identifier(ref.source_id)
            identifier(ref.version)
            digest(ref.sha256)
            index[key] = record
        self._records = index

    def resolve(
        self, authorization: str, request: SupportedRequest, trust: LocalTrust
    ) -> tuple[EvidenceRecord, ...]:
        output = []
        for ref in request.evidence:
            trust.authorize(authorization, "evidence", request, source_id=ref.source_id)
            record = self._records.get((request.scope, ref.source_id))
            if record is None or record.reference != ref:
                raise ContractError("evidence_mismatch")
            output.append(record)
        return tuple(output)


@dataclass(frozen=True, slots=True)
class AttemptPermit:
    principal_id: str
    attempt_id: str
    scope: Scope
    input_fingerprint: str


class AttemptBoundary:
    """Finite live invocation observations only; no queue, timer or recovery owner."""

    def __init__(
        self,
        trust: LocalTrust,
        evidence: EvidenceRegistry,
        *,
        max_active: int = 4,
        max_per_principal: int = 2,
    ) -> None:
        integer(max_active, 1, 16)
        integer(max_per_principal, 1, max_active)
        self._trust, self._evidence = trust, evidence
        self._max_active, self._max_per_principal = max_active, max_per_principal
        self._active: dict[tuple[Scope, str], tuple[AttemptPermit, SupportedRequest]] = {}
        self._lock = threading.Lock()

    @property
    def active(self) -> int:
        with self._lock:
            return len(self._active)

    def acquire(
        self, authorization: str, request: SupportedRequest, *, observed_at_ms: int
    ) -> AttemptPermit:
        # Revalidate typed values at the public resource boundary; frozen types do
        # not turn a caller-created instance into trusted persisted acceptance.
        request = _snapshot_supported(request)
        principal_id = self._trust.authorize(authorization, "invoke", request)
        integer(observed_at_ms, 0, MAX_TIMESTAMP_MS)
        remaining = request.deadline_at_ms - observed_at_ms
        if not 0 < remaining <= MAX_DEADLINE_WINDOW_MS:
            raise ContractError("expired")
        self._evidence.resolve(authorization, request, self._trust)
        key = (request.scope, request.attempt.attempt_id)
        # Only fixed-size map operations occur under this process-local lock.
        with self._lock:
            if key in self._active:
                raise ContractError("identity_conflict")
            for _, active_request in self._active.values():
                if (
                    active_request.scope == request.scope
                    and active_request.delegation_id == request.delegation_id
                    and active_request.input_fingerprint != request.input_fingerprint
                ):
                    raise ContractError("identity_conflict")
            if (
                len(self._active) >= self._max_active
                or sum(item[0].principal_id == principal_id for item in self._active.values())
                >= self._max_per_principal
            ):
                raise ContractError("capacity")
            permit = AttemptPermit(
                principal_id, request.attempt.attempt_id, request.scope, request.input_fingerprint
            )
            self._active[key] = permit, request
            return permit

    @overload
    def inspect(
        self, authorization: str, request: DelegationRequest, operation: Literal["result", "cancel"]
    ) -> DelegationRequest: ...
    @overload
    def inspect(
        self, authorization: str, request: DocumentRequest, operation: Literal["result", "cancel"]
    ) -> DocumentRequest: ...
    @overload
    def inspect(
        self, authorization: str, request: SupportedRequest, operation: Literal["result", "cancel"]
    ) -> SupportedRequest: ...
    def inspect(
        self, authorization: str, request: SupportedRequest, operation: Literal["result", "cancel"]
    ) -> SupportedRequest:
        if type(operation) is not str or operation not in ("result", "cancel"):
            raise ContractError("unauthorized")
        request = _snapshot_supported(request)
        self._trust.authorize(authorization, operation, request)
        with self._lock:
            observed = self._active.get((request.scope, request.attempt.attempt_id))
        if observed is None:
            raise ContractError("unknown_attempt")
        accepted = observed[1]
        if (
            request.input_fingerprint != accepted.input_fingerprint
            or request.delegation_id != accepted.delegation_id
            or request.attempt != accepted.attempt
        ):
            raise ContractError("identity_conflict")
        return accepted

    def release(self, permit: AttemptPermit) -> None:
        if type(permit) is not AttemptPermit or type(permit.scope) is not Scope:
            raise ContractError("unknown_attempt")
        if (
            type(permit.scope.tenant_id) is not str
            or type(permit.scope.account_id) is not str
            or type(permit.attempt_id) is not str
        ):
            raise ContractError("unknown_attempt")
        key = (permit.scope, permit.attempt_id)
        with self._lock:
            observed = self._active.get(key)
            if observed is None or observed[0] is not permit:
                raise ContractError("unknown_attempt")
            del self._active[key]


def verify_policy_facts(
    request: DelegationRequest,
    result: DelegationResult,
    records: tuple[EvidenceRecord, ...],
    *,
    observed_at_ms: int,
) -> Literal["candidate", "expired", "clarification"]:
    applicability = match_result(request, result, observed_at_ms=observed_at_ms)
    policy = next(
        (
            item
            for item in records
            if item.scope == request.scope
            and item.reference.source_id == request.context_snapshot.policy_source_id
        ),
        None,
    )
    if (
        policy is None
        or policy.reference not in request.evidence
        or hashlib.sha256(policy.body).hexdigest() != policy.reference.sha256
    ):
        raise ContractError("evidence_mismatch")
    value = object_fields(decode(policy.body, 4096), {"policy_version", "minimum_notice_days"})
    context: ContextSnapshot = request.context_snapshot
    if value["policy_version"] != context.policy_version:
        raise ContractError("unsupported_facts")
    days = integer(value["minimum_notice_days"], 0, 3650)
    refs = [ref for ref in result.evidence_refs if ref.source_id == policy.reference.source_id]
    if len(refs) != 1 or refs[0].rule_id != "notice_minimum_days":
        raise ContractError("unsupported_facts")
    if result.uncertainty == "none" and result.eligible is not (
        context.days_before_arrival >= days
    ):
        raise ContractError("unsupported_facts")
    if applicability == "expired":
        return "expired"
    if result.uncertainty != "none":
        return "clarification"
    return "candidate"  # Never current authorization or exact mutation consent.
