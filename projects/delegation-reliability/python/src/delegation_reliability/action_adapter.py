"""Exact case reads and separately confirmed P1 guarded result authorization.

The specialist cannot reach this controller boundary. Committing an intent is not
supplier execution, result delivery or human acknowledgement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, cast

from continuity_lab.action_api import ActionError, ActionIntent, ActionPort, ActionReceipt
from continuity_lab.case_control_api import CaseControlIdentity
from continuity_lab.case_control_api import CaseSnapshot as AuthorityCase
from continuity_lab.postgres_api import AuthenticatedActor, Confirmation, QuoteSnapshot
from continuity_lab.work_api import WorkError, WorkScope

from .completion import (
    CompletionCode,
    CompletionError,
    DelegationResultReadPort,
    _Call,
    _CompletionOwner,
    _evidence,
    _result,
    _uuid,
)
from .contracts import ContractError, Scope, identifier, integer
from .coordinator import CaseSnapshot
from .security import EvidenceRecord


@dataclass(frozen=True, slots=True)
class ActionBinding:
    """Trusted immutable logical-to-authority identity, never supplied by model JSON."""

    case_id: str
    task_id: str
    authority_case_id: str
    authority_actor_id: str
    authority_scope_id: str
    case_schema: str

    def __post_init__(self) -> None:
        try:
            identifier(self.case_id)
            _uuid(self.task_id)
            _uuid(self.authority_case_id)
            actor = AuthenticatedActor(self.authority_actor_id, self.authority_scope_id)
            if (actor.actor_id, actor.scope_id) != (
                self.authority_actor_id,
                self.authority_scope_id,
            ):
                raise CompletionError("invalid_input")
            if (
                type(self.case_schema) is not str
                or re.fullmatch(r"[a-z][a-z0-9_]{0,62}", self.case_schema) is None
            ):
                raise CompletionError("invalid_input")
        except (ContractError, TypeError, ValueError):
            raise CompletionError("invalid_input") from None


class ExactCaseReadPort(Protocol):
    @property
    def identity(self) -> CaseControlIdentity: ...
    async def case(self, *, task_id: str) -> AuthorityCase: ...


def _bindings(values: tuple[ActionBinding, ...]) -> tuple[ActionBinding, ...]:
    if type(values) is not tuple or not 1 <= len(values) <= 128:
        raise CompletionError("invalid_input")
    copied = []
    for value in values:
        if type(value) is not ActionBinding:
            raise CompletionError("invalid_input")
        copied.append(
            ActionBinding(
                value.case_id,
                value.task_id,
                value.authority_case_id,
                value.authority_actor_id,
                value.authority_scope_id,
                value.case_schema,
            )
        )
    if (
        len({value.case_id for value in copied}) != len(copied)
        or len(
            {
                (value.authority_actor_id, value.authority_scope_id, value.case_schema)
                for value in copied
            }
        )
        != 1
    ):
        raise CompletionError("invalid_input")
    return tuple(copied)


def _confirmation(value: Confirmation) -> Confirmation:
    try:
        if (
            type(value) is not Confirmation
            or type(value.quote) is not QuoteSnapshot
            or value.explicit is not True
        ):
            raise CompletionError("invalid_confirmation")
        quote = value.quote
        copied = QuoteSnapshot(
            quote.quote_id,
            quote.task_id,
            quote.revision,
            quote.booking_reference,
            quote.new_check_in,
            quote.amount_minor,
            quote.currency,
            quote.expires_at,
            quote.case_id,
            quote.expected_supplier_revision,
            quote.supplier_id,
        )
        if copied.schema_version != 2:
            raise CompletionError("invalid_confirmation")
        return Confirmation(copied, value.explicit)
    except (AttributeError, TypeError, ValueError, RuntimeError):
        raise CompletionError("invalid_confirmation") from None


def _intent(value: ActionIntent) -> ActionIntent:
    try:
        if type(value) is not ActionIntent:
            raise CompletionError("invalid_stored_state")
        # This copies the already supplied explicit confirmation; it never creates consent.
        quote = value.quote
        copied = QuoteSnapshot(
            quote.quote_id,
            quote.task_id,
            quote.revision,
            quote.booking_reference,
            quote.new_check_in,
            quote.amount_minor,
            quote.currency,
            quote.expires_at,
            quote.case_id,
            quote.expected_supplier_revision,
            quote.supplier_id,
        )
        return ActionIntent(
            value.intent_id,
            value.task_id,
            value.scope_id,
            value.actor_id,
            value.revision,
            copied,
            value.confirmation_id,
            value.effect_id,
            value.dispatch_event_id,
            value.created_at,
        )
    except (AttributeError, TypeError, ValueError, RuntimeError):
        raise CompletionError("invalid_stored_state") from None


class ExactManagedCaseAuthority:
    """Read adapter with exact cancellation state; the application owns its client."""

    def __init__(
        self, client: ExactCaseReadPort, *, scope: Scope, bindings: tuple[ActionBinding, ...]
    ) -> None:
        from .completion import _scope

        self._scope = _scope(scope)
        self._bindings = _bindings(bindings)
        self._client = client
        self._require_identity()

    def _require_identity(self) -> None:
        try:
            actual = self._client.identity
            first = self._bindings[0]
            if type(actual) is not CaseControlIdentity or (
                actual.actor_id,
                actual.scope_id,
                actual.schema,
            ) != (first.authority_actor_id, first.authority_scope_id, first.case_schema):
                raise CompletionError("unauthorized")
        except CompletionError:
            raise
        except Exception:  # noqa: BLE001 - configuration failure has one fixed safe code
            raise CompletionError("unauthorized") from None

    async def snapshot(self, *, case_id: str) -> CaseSnapshot:
        try:
            key = identifier(case_id)
        except ContractError:
            raise CompletionError("invalid_input") from None
        binding = next((value for value in self._bindings if value.case_id == key), None)
        if binding is None:
            raise CompletionError("not_found")
        self._require_identity()
        observed = await self._client.case(task_id=binding.task_id)
        try:
            if type(observed) is not AuthorityCase or type(observed.cancelled) is not bool:
                raise CompletionError("invalid_stored_state")
            if (observed.task_id, observed.case_id, observed.actor_id, observed.scope_id) != (
                binding.task_id,
                binding.authority_case_id,
                binding.authority_actor_id,
                binding.authority_scope_id,
            ):
                raise CompletionError("unauthorized")
            revision = integer(observed.revision, 0, 9_007_199_254_740_991)
            return CaseSnapshot(self._scope, binding.case_id, revision, observed.cancelled)
        except (ContractError, AttributeError, TypeError, ValueError):
            raise CompletionError("invalid_stored_state") from None


@dataclass(frozen=True, slots=True)
class DelegationAuthorization:
    receipt: ActionReceipt
    reconciled: bool


class DelegationAuthorizer(_CompletionOwner):
    """Bounded controller call requiring a separate exact human confirmation.

    The client owns its P1 action client; the application owns the result inspector.
    P1 atomically guards current work/result/cancellation/deadline and exact case
    authority in the same SQL transaction. No supplier request runs here.
    """

    def __init__(
        self,
        *,
        results: DelegationResultReadPort,
        actions: ActionPort,
        scope: Scope,
        evidence: tuple[EvidenceRecord, ...],
        bindings: tuple[ActionBinding, ...],
        max_active: int = 2,
        timeout_ms: int = 5000,
        cleanup_ms: int = 1000,
    ) -> None:
        super().__init__(
            scope, (actions,), max_active=max_active, timeout_ms=timeout_ms, cleanup_ms=cleanup_ms
        )
        self._actions = actions
        self._results = results
        self._bindings = _bindings(bindings)
        self._evidence = _evidence(self._scope, evidence)
        self._require_actions()

    def _require_actions(self) -> None:
        try:
            self._require_scope(self._actions.scope)
            first = self._bindings[0]
            if (
                self._actions.case_actor_id,
                self._actions.case_scope_id,
                self._actions.case_schema,
            ) != (first.authority_actor_id, first.authority_scope_id, first.case_schema):
                raise CompletionError("unauthorized")
        except CompletionError:
            raise
        except (ActionError, WorkError):
            raise CompletionError("unauthorized") from None
        except Exception:  # noqa: BLE001 - composition cannot reflect arbitrary port errors
            raise CompletionError("unauthorized") from None

    def _binding(self, case_id: str) -> ActionBinding:
        found = next((value for value in self._bindings if value.case_id == case_id), None)
        if found is None:
            raise CompletionError("unauthorized")
        return found

    def _receipt(
        self,
        value: ActionReceipt,
        *,
        work_id: str,
        attempt_id: str,
        result_sha256: str,
        binding: ActionBinding,
        expected_revision: int,
        confirmation: Confirmation | None = None,
        command_id: str | None = None,
    ) -> ActionReceipt:
        try:
            if type(value) is not ActionReceipt or type(value.scope) is not WorkScope:
                raise CompletionError("invalid_stored_state")
            copied = ActionReceipt(
                value.action_id,
                WorkScope(value.scope.tenant_id, value.scope.account_id),
                value.work_id,
                value.attempt_id,
                value.result_sha256,
                value.case_schema,
                value.case_scope_id,
                value.case_actor_id,
                value.case_task_id,
                value.case_id,
                value.expected_revision,
                value.command_id,
                _confirmation(value.confirmation),
                _intent(value.intent),
                value.committed_at_ms,
            )
            if (
                copied.scope,
                copied.work_id,
                copied.attempt_id,
                copied.result_sha256,
                copied.case_schema,
                copied.case_scope_id,
                copied.case_actor_id,
                copied.case_task_id,
                copied.case_id,
                copied.expected_revision,
            ) != (
                WorkScope(self._scope.tenant_id, self._scope.account_id),
                work_id,
                attempt_id,
                result_sha256,
                binding.case_schema,
                binding.authority_scope_id,
                binding.authority_actor_id,
                binding.task_id,
                binding.authority_case_id,
                expected_revision,
            ):
                raise CompletionError("invalid_stored_state")
            if (confirmation is not None and copied.confirmation != confirmation) or (
                command_id is not None and copied.command_id != command_id
            ):
                raise CompletionError("identity_conflict")
            return copied
        except (ActionError, AttributeError, TypeError, ValueError):
            raise CompletionError("invalid_stored_state") from None

    async def inspect(self, work_id: str) -> ActionReceipt | None:
        work_id = _uuid(work_id)

        async def read(_: _Call) -> ActionReceipt | None:
            result = _result(
                await self._results.inspect(work_id), self._scope, work_id, self._evidence
            )
            binding = self._binding(result.request.case_id)
            self._require_actions()
            try:
                value = await self._actions.action(work_id=work_id)
            except ActionError as error:
                raise CompletionError(cast(CompletionCode, error.code)) from None
            return (
                None
                if value is None
                else self._receipt(
                    value,
                    work_id=work_id,
                    attempt_id=result.issued.attempt_id,
                    result_sha256=result.recorded.sha256,
                    binding=binding,
                    expected_revision=result.request.request_revision,
                )
            )

        return await self._run("action_inspect", read)

    async def authorize_once(
        self, work_id: str, *, confirmation: Confirmation, command_id: str
    ) -> DelegationAuthorization:
        work_id = _uuid(work_id)
        supplied = _confirmation(confirmation)
        try:
            command = identifier(command_id)
        except ContractError:
            raise CompletionError("invalid_input") from None
        return await self._run(
            "authorize", lambda call: self._authorize(call, work_id, supplied, command)
        )

    async def _authorize(
        self, call: _Call, work_id: str, confirmation: Confirmation, command_id: str
    ) -> DelegationAuthorization:
        result = _result(await self._results.inspect(work_id), self._scope, work_id, self._evidence)
        binding = self._binding(result.request.case_id)
        quote = confirmation.quote
        if (quote.task_id, quote.case_id, quote.revision) != (
            binding.task_id,
            binding.authority_case_id,
            result.request.request_revision,
        ):
            raise CompletionError("invalid_confirmation")
        if result.result.eligible is not True or result.result.uncertainty != "none":
            raise CompletionError("not_eligible")
        self._require_actions()
        try:
            previous = await self._actions.find_action(command_id=command_id)
            if previous is not None:
                return DelegationAuthorization(
                    self._receipt(
                        previous,
                        work_id=work_id,
                        attempt_id=result.issued.attempt_id,
                        result_sha256=result.recorded.sha256,
                        binding=binding,
                        expected_revision=result.request.request_revision,
                        confirmation=confirmation,
                        command_id=command_id,
                    ),
                    True,
                )
            if (
                result.view.applicability != "candidate"
                or result.recorded.disposition != "eligible_at_commit"
            ):
                raise CompletionError("not_eligible")
            self._check(call)
            self._require_actions()
            call.writing = True
            try:
                committed = await self._actions.authorize(
                    work_id=work_id,
                    attempt_id=result.issued.attempt_id,
                    result_sha256=result.recorded.sha256,
                    expected_revision=result.request.request_revision,
                    confirmation=confirmation,
                    command_id=command_id,
                )
            except ActionError as error:
                if error.code != "acknowledgement_unknown":
                    raise
                self._require_actions()
                try:
                    recovered = await self._actions.find_action(command_id=command_id)
                except ActionError:
                    raise CompletionError("acknowledgement_unknown") from None
                if recovered is None:
                    raise CompletionError("acknowledgement_unknown") from None
                committed = recovered
                self._counts["reconciled"] += 1
                return DelegationAuthorization(
                    self._receipt(
                        committed,
                        work_id=work_id,
                        attempt_id=result.issued.attempt_id,
                        result_sha256=result.recorded.sha256,
                        binding=binding,
                        expected_revision=result.request.request_revision,
                        confirmation=confirmation,
                        command_id=command_id,
                    ),
                    True,
                )
            receipt = self._receipt(
                committed,
                work_id=work_id,
                attempt_id=result.issued.attempt_id,
                result_sha256=result.recorded.sha256,
                binding=binding,
                expected_revision=result.request.request_revision,
                confirmation=confirmation,
                command_id=command_id,
            )
            return DelegationAuthorization(receipt, False)
        except ActionError as error:
            raise CompletionError(cast(CompletionCode, error.code)) from None
