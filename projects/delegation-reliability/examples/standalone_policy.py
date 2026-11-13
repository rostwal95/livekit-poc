"""Configured standalone consumer using installed public P1/P3 contracts only.

Prepare schemas, synthetic inquiry/quote, receiver and explicit operator consent
separately. The application constructs credential-bound public clients, supplies
the immutable mappings/evidence below, and closes this owner after use. Import
starts no listener, database connection, migration, model or background task.

Keep this file beside the unmodified policy_completion.py example. Both are
application modules; neither replaces or adds a product execution authority.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from policy_completion import CompletionSummary, Inspection, inspect_accepted, run_completion

from continuity_lab.action_api import ActionPort, Confirmation
from continuity_lab.case_control_api import CaseControlClient
from continuity_lab.delivery_api import DeliveryPort
from continuity_lab.execution_api import ExecutionPort
from continuity_lab.receiver_api import ResultReceiver
from continuity_lab.work_api import TaskExecutionPort
from delegation_reliability import (
    ActionBinding,
    DelegationAuthorizer,
    DelegationCoordinator,
    DelegationDeliveryClient,
    DelegationRunner,
    DeliveryBinding,
    ExactManagedCaseAuthority,
    SpecialistInvocationPort,
)
from delegation_reliability.contracts import DelegationRequest, Scope
from delegation_reliability.security import EvidenceRecord


class StandaloneConfigurationError(ValueError):
    def __init__(self) -> None:
        super().__init__("standalone_invalid_configuration")


class StandaloneClosedError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("standalone_closed")


class _Owner(Protocol):
    @property
    def pending_count(self) -> int: ...
    async def close(self) -> None: ...


def _retrieve(task: asyncio.Task[None]) -> None:
    if not task.cancelled():
        task.exception()


@dataclass(slots=True)
class StandaloneApplication:
    """Own the supplied clients after successful composition; no scheduling loop."""

    coordinators: tuple[DelegationCoordinator, DelegationCoordinator]
    runner: DelegationRunner
    delivery: DelegationDeliveryClient
    authorizer: DelegationAuthorizer
    case_client: CaseControlClient = field(repr=False)
    _closing: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _closed: bool = field(default=False, init=False)

    @property
    def cleanup_complete(self) -> bool:
        return self._closed

    @property
    def pending_count(self) -> int:
        return sum(owner.pending_count for owner in self._owners())

    def _owners(self) -> Sequence[_Owner]:
        return (*self.coordinators, self.authorizer, self.delivery, self.runner, self.case_client)

    def _require_open(self) -> None:
        if self._closing is not None:
            raise StandaloneClosedError()

    async def complete(
        self,
        request: DelegationRequest,
        *,
        confirmation: Confirmation,
        execution_command_id: str,
        confirmation_command_id: str,
    ) -> CompletionSummary:
        self._require_open()
        return await run_completion(
            request,
            coordinators=self.coordinators,
            runner=self.runner,
            delivery=self.delivery,
            authorizer=self.authorizer,
            confirmation=confirmation,
            execution_command_id=execution_command_id,
            confirmation_command_id=confirmation_command_id,
        )

    async def inspect(self, work_id: str) -> Inspection:
        self._require_open()
        return await inspect_accepted(
            work_id,
            coordinator=self.coordinators[0],
            runner=self.runner,
            delivery=self.delivery,
            authorizer=self.authorizer,
        )

    async def _close_owned(self) -> None:
        async def attempt(owner: _Owner) -> BaseException | None:
            try:
                await owner.close()
            except BaseException as error:  # noqa: BLE001 - finish independent cleanup before preserving the first failure.
                return error
            return None

        # Dependents drain before their shared result/case readers. Independent
        # owners close concurrently, keeping inherited finite close bounds useful.
        batches: tuple[Sequence[_Owner], ...] = (
            (*self.coordinators, self.authorizer, self.delivery),
            (self.runner,),
            (self.case_client,),
        )
        for batch in batches:
            failures = await asyncio.gather(*(attempt(owner) for owner in batch))
            first = next((error for error in failures if error is not None), None)
            if first is not None:
                # An incomplete public close can retain actual dependent work.
                # Keep its shared readers alive; a later close re-observes this
                # same tier rather than caching the failed close observation.
                raise first
        self._closed = True

    async def close(self) -> None:
        """Retain actual cleanup and readers; retry an incomplete tier observation."""
        if self._closed:
            return
        if self._closing is None or self._closing.done():
            self._closing = asyncio.create_task(self._close_owned())
            self._closing.add_done_callback(_retrieve)
        await asyncio.shield(self._closing)


def configure_standalone(
    *,
    scope: Scope,
    owner_id: str,
    work_clients: tuple[TaskExecutionPort, TaskExecutionPort],
    execution: ExecutionPort,
    specialist: SpecialistInvocationPort,
    case_client: CaseControlClient,
    deliveries: DeliveryPort,
    receiver: ResultReceiver,
    actions: ActionPort,
    evidence: tuple[EvidenceRecord, ...],
    action_bindings: tuple[ActionBinding, ...],
    delivery_bindings: tuple[DeliveryBinding, ...],
) -> StandaloneApplication:
    """Compose already configured public clients; owner setup never runs here.

    Before successful return the caller owns every supplied client and must clean
    them after a constructor failure. Afterwards this application closes them.
    Callers supply two independently owned work clients, immutable trusted case
    and recipient bindings, and a separately obtained exact Confirmation later.
    """
    if (
        type(scope) is not Scope
        or type(work_clients) is not tuple
        or len(work_clients) != 2
        or work_clients[0] is work_clients[1]
    ):
        raise StandaloneConfigurationError()
    trusted_scope = Scope(scope.tenant_id, scope.account_id)
    cases = ExactManagedCaseAuthority(case_client, scope=trusted_scope, bindings=action_bindings)
    coordinators = tuple(
        DelegationCoordinator(executions=client, scope=trusted_scope, case_authority=cases)
        for client in work_clients
    )
    runner = DelegationRunner(
        executions=execution,
        scope=trusted_scope,
        owner_id=owner_id,
        specialist=specialist,
        case_authority=cases,
        evidence=evidence,
        timeout_ms=10000,
    )
    delivery = DelegationDeliveryClient(
        results=runner,
        deliveries=deliveries,
        receiver=receiver,
        scope=trusted_scope,
        evidence=evidence,
        bindings=delivery_bindings,
        timeout_ms=10000,
    )
    authorizer = DelegationAuthorizer(
        results=runner,
        actions=actions,
        scope=trusted_scope,
        evidence=evidence,
        bindings=action_bindings,
        timeout_ms=10000,
    )
    return StandaloneApplication(
        (coordinators[0], coordinators[1]), runner, delivery, authorizer, case_client
    )
