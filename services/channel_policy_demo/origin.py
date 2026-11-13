"""Explicit P2-input to P1-owned policy-work composition for the local POC.

The trusted publisher supplies the profile/route; this module authenticates no
account and attests no P2 database. It creates neither a queue nor a worker.
Imports are inert. The original message remains solely in P2.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, TypeVar, get_args

from delegation_reliability import (
    ChannelPolicyCoordinator,
    ChannelPolicyOrigin,
    ChannelPolicyView,
    CoordinatorError,
    channel_policy_key,
    encode_channel_policy_request,
    produce_channel_policy_request,
)
from delegation_reliability.contracts import ContractError, Scope, identifier
from delegation_reliability.coordinator import CoordinatorCode
from delegation_reliability.fixed_policy_contracts import (
    FixedPolicyRequest,
    encode_fixed_policy_request,
    parse_fixed_policy_request,
    produce_fixed_policy_request,
)

from .wire import (
    ChannelAccountScope,
    ChannelOperationLookup,
    OriginWireError,
    PreparedChannelInput,
    channel_identifier,
    parse_accept_frame,
    parse_lookup_frame,
    parse_profile_frame,
    require_p3_compatible,
    uuid_value,
)

LOGGER = logging.getLogger("p3_channel_origin")
LOGGER.addHandler(logging.NullHandler())
_SAFE_CODES = frozenset(get_args(CoordinatorCode)) | {"known"}
T = TypeVar("T")
Event = Literal["accept", "lookup", "inspect_profile"]


@dataclass(frozen=True, slots=True)
class ChannelOriginBinding:
    """Trusted finite route, unrelated to model text or browser room grants."""

    profile_id: str
    scope: Scope
    case_id: str
    conversation_id: str
    sender_id: str


def _binding(value: ChannelOriginBinding) -> ChannelOriginBinding:
    if type(value) is not ChannelOriginBinding or type(value.scope) is not Scope:
        raise CoordinatorError("invalid_input")
    return ChannelOriginBinding(
        uuid_value(value.profile_id),
        Scope(identifier(value.scope.tenant_id), identifier(value.scope.account_id)),
        identifier(value.case_id),
        identifier(value.conversation_id),
        channel_identifier(value.sender_id),
    )


class ChannelOriginService:
    """Own one coordinator after validated construction; caller owns case reads.

    ``accept`` calls the coordinator exactly once. Its first-origin semantics
    reconcile an uncertain commit without another submit. Lookup is read-only and
    preserves known history after case changes or expiry. Explicit execution and
    result delivery belong to separate application ports.
    """

    def __init__(
        self,
        *,
        binding: ChannelOriginBinding,
        template: FixedPolicyRequest,
        coordinator: ChannelPolicyCoordinator,
        deadline_window_ms: int = 30000,
    ) -> None:
        # No ownership transfer, I/O or close on failed construction.
        try:
            copied = _binding(binding)
            if (
                type(template) is not FixedPolicyRequest
                or type(coordinator) is not ChannelPolicyCoordinator
                or type(deadline_window_ms) is not int
                or not 20 <= deadline_window_ms <= 60000
            ):
                raise CoordinatorError("invalid_input")
            policy = parse_fixed_policy_request(encode_fixed_policy_request(template))
            if (
                coordinator.scope != copied.scope
                or policy.scope != copied.scope
                or policy.case_id != copied.case_id
                or policy.conversation_id != copied.conversation_id
            ):
                raise CoordinatorError("unauthorized")
        except (ContractError, OriginWireError, AttributeError, TypeError, ValueError):
            raise CoordinatorError("invalid_input") from None
        self._binding, self._template = copied, policy
        self._coordinator, self._window = coordinator, deadline_window_ms
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closing = False
        self._counts = {
            "started": 0,
            "succeeded": 0,
            "failed": 0,
            "cancelled_waiters": 0,
            "accepted_observed": 0,
            "replayed_observed": 0,
            "lookup_found": 0,
            "lookup_absent": 0,
            "profile_reads": 0,
            "telemetry_failed": 0,
        }

    def _bind(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif loop is not self._loop:
            raise CoordinatorError("invalid_input")

    def metrics(self) -> MappingProxyType[str, int]:
        """Process-local observations, never durable acceptance/business totals."""
        return MappingProxyType(
            {
                **self._counts,
                "active": self._coordinator.pending_count,
                "closing": int(self._closing),
            }
        )

    def _log(self, event: Event, code: str) -> None:
        try:
            LOGGER.info(
                "channel_origin",
                extra={
                    "operation": event,
                    "code": code if type(code) is str and code in _SAFE_CODES else "internal_error",
                },
            )
        except Exception:  # noqa: BLE001 - an exporter cannot change accepted work
            self._counts["telemetry_failed"] += 1

    async def _observe(self, event: Event, action: Callable[[], Awaitable[T]]) -> T:
        self._bind()
        if self._closing:
            raise CoordinatorError("closed")
        self._counts["started"] += 1
        try:
            result = await action()
        except asyncio.CancelledError:
            self._counts["cancelled_waiters"] += 1
            self._log(event, "request_aborted")
            raise
        except OriginWireError as error:
            codes: dict[str, CoordinatorCode] = {
                "InvalidCommand": "invalid_input",
                "AccessDenied": "unauthorized",
                "IdentityConflict": "identity_conflict",
            }
            self._counts["failed"] += 1
            translated = CoordinatorError(codes[error.code])
            self._log(event, translated.code)
            raise translated from None
        except CoordinatorError as error:
            self._counts["failed"] += 1
            self._log(event, error.code)
            raise
        except ContractError:
            self._counts["failed"] += 1
            self._log(event, "invalid_input")
            raise CoordinatorError("invalid_input") from None
        except Exception:  # noqa: BLE001 - private dependency text never crosses this port
            self._counts["failed"] += 1
            self._log(event, "internal_error")
            raise CoordinatorError("internal_error") from None
        self._counts["succeeded"] += 1
        self._log(event, "known")
        return result

    def _check_scope(self, scope: ChannelAccountScope) -> None:
        expected = self._binding.scope
        if scope != ChannelAccountScope(expected.tenant_id, expected.account_id):
            raise CoordinatorError("unauthorized")

    def _check_input(self, value: PreparedChannelInput) -> int:
        revision = require_p3_compatible(value)
        self._check_scope(value.scope)
        if (
            value.case_id != self._binding.case_id
            or value.conversation_id != self._binding.conversation_id
            or value.sender_id != self._binding.sender_id
        ):
            raise CoordinatorError("unauthorized")
        return revision

    def _receipt(self, view: ChannelPolicyView, query: ChannelOperationLookup) -> dict[str, object]:
        # The public coordinator already validates P1's entire record/body. Keep
        # application route and original-origin checks explicit at this boundary.
        request, record = view.request, view.record
        body = encode_channel_policy_request(request)
        if (
            record.payload.body != body
            or record.payload.sha256 != hashlib.sha256(body).hexdigest()
            or record.idempotency_key != channel_policy_key(query.operation_key)
        ):
            raise CoordinatorError("invalid_stored_state")
        origin = request.origin
        if (
            request.scope != self._binding.scope
            or request.case_id != self._binding.case_id
            or request.request.conversation_id != self._binding.conversation_id
        ):
            raise CoordinatorError("unauthorized")
        if (
            origin.profile_id != self._binding.profile_id
            or origin.operation_key != query.operation_key
            or origin.payload_sha256 != query.payload_sha256
        ):
            raise CoordinatorError("identity_conflict")
        return {
            "operationKey": origin.operation_key,
            "scope": {
                "tenantId": request.scope.tenant_id,
                "accountId": request.scope.account_id,
            },
            "payloadDigest": origin.payload_sha256,
            "receiptId": uuid_value(record.work_id),
        }

    async def accept(self, raw: bytes) -> dict[str, object]:
        async def run() -> dict[str, object]:
            source = parse_accept_frame(raw)
            revision = self._check_input(source)
            inner = self._template.to_wire()
            inner.pop("input_fingerprint")
            inner.update(
                delegation_id=channel_policy_key(source.operation_key),
                request_revision=revision,
                deadline_at_ms=time.time_ns() // 1000000 + self._window,
                attempt={"attempt_id": "origin_proposal", "number": 1},
            )
            proposal = produce_channel_policy_request(
                {
                    "schema_version": 1,
                    "kind": "delegation.request",
                    "capability": "booking.evaluate_policy",
                    "input_schema_version": 3,
                    "origin": ChannelPolicyOrigin(
                        "p2.prepared_dispatch.v1",
                        self._binding.profile_id,
                        source.operation_key,
                        source.input_receipt_id,
                        source.payload_sha256,
                        source.payload_byte_length,
                    ).to_wire(),
                    "request": produce_fixed_policy_request(inner).to_wire(),
                }
            )
            accepted = await self._coordinator.accept(proposal)
            receipt = self._receipt(accepted.view, source.lookup())
            self._counts["accepted_observed" if accepted.created else "replayed_observed"] += 1
            return receipt

        return await self._observe("accept", run)

    async def lookup(self, raw: bytes) -> dict[str, object] | None:
        async def run() -> dict[str, object] | None:
            query = parse_lookup_frame(raw)
            self._check_scope(query.scope)
            view = await self._coordinator.find(channel_policy_key(query.operation_key))
            if view is None:
                self._counts["lookup_absent"] += 1
                return None
            receipt = self._receipt(view, query)
            self._counts["lookup_found"] += 1
            return receipt

        return await self._observe("lookup", run)

    async def inspect_profile(self, raw: bytes) -> None:
        async def run() -> None:
            if parse_profile_frame(raw) != self._binding.profile_id:
                raise CoordinatorError("unauthorized")
            # Authorized public read only. This is configured serving readiness,
            # not a fresh attestation of P2's receiver/profile database row.
            if await self._coordinator.find("p2_origin_preflight") is not None:
                raise CoordinatorError("invalid_stored_state")
            self._counts["profile_reads"] += 1

        await self._observe("inspect_profile", run)

    async def close(self) -> None:
        self._bind()
        self._closing = True
        await self._coordinator.close()
