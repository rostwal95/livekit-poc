"""Explicit public-port completion example for an already configured application.

Install/upgrade P1 and initialize its receiver separately. The application supplies
credential-bound clients, finite trusted mappings, immutable evidence and a separate
exact operator Confirmation. It owns/closes all supplied clients. Import starts no
process, listener, database connection, migration, model or background task.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from continuity_lab.action_api import ActionReceipt, Confirmation
from continuity_lab.postgres_api import InvalidConfirmation, parse_confirmation_payload
from delegation_reliability import (
    DelegationAuthorizer,
    DelegationCoordinator,
    DelegationDelivery,
    DelegationExecutionView,
    DelegationRunner,
    DelegationView,
    ResultDeliveryPort,
)
from delegation_reliability.contracts import (
    DelegationRequest,
    canonical,
    encode_request,
    parse_request,
)


class ExampleInvariantError(RuntimeError):
    """A configured example boundary returned inconsistent known identities."""

    def __init__(self) -> None:
        super().__init__("example_identity_mismatch")


@dataclass(frozen=True, slots=True)
class Inspection:
    """Separate accepted input, current result, delivery and guarded action facts."""

    accepted: DelegationView = field(repr=False)
    execution: DelegationExecutionView = field(repr=False)
    delivery: DelegationDelivery
    action: ActionReceipt | None


@dataclass(frozen=True, slots=True)
class CompletionSummary:
    work_id: str
    accepted_input_sha256: str
    result_sha256: str
    created_acceptances: int
    invoked: bool
    delivery_state: str
    action_id: str
    human_acknowledgement: str = "unobserved"


async def inspect_accepted(
    work_id: str,
    *,
    coordinator: DelegationCoordinator,
    runner: DelegationRunner,
    delivery: ResultDeliveryPort,
    authorizer: DelegationAuthorizer,
) -> Inspection:
    """Read actual authority-backed task/result facts; never invoke or authorize."""
    accepted = await coordinator.get(work_id)
    execution = await runner.inspect(work_id)
    received = await delivery.inspect(work_id)
    action = await authorizer.inspect(work_id)
    if accepted.record.work_id != work_id or execution.execution.record != accepted.record:
        raise ExampleInvariantError()
    return Inspection(accepted, execution, received, action)


async def run_completion(
    request: DelegationRequest,
    *,
    coordinators: tuple[DelegationCoordinator, DelegationCoordinator],
    runner: DelegationRunner,
    delivery: ResultDeliveryPort,
    authorizer: DelegationAuthorizer,
    confirmation: Confirmation,
    execution_command_id: str,
    confirmation_command_id: str,
) -> CompletionSummary:
    """Concurrent replay, one selected issued call, delivery and explicit action.

    This example makes one selected run_once call. It does not promise one physical
    computation under arbitrary retries, lease expiry or other consumers. Repeating
    an original command inspects/replays its known fact under the public contract.
    No confirmation is constructed from the specialist result.
    """
    snapshot = parse_request(encode_request(request))
    if type(confirmation) is not Confirmation:
        raise InvalidConfirmation("An exact explicitly accepted quote is required")
    try:
        trusted_confirmation = parse_confirmation_payload(
            canonical(confirmation.quote.payload()).decode("utf-8"), explicit=confirmation.explicit
        )
    except (ValueError, TypeError, AttributeError):
        raise InvalidConfirmation("An exact explicitly accepted quote is required") from None
    async with asyncio.TaskGroup() as group:
        first = group.create_task(coordinators[0].submit(snapshot))
        second = group.create_task(coordinators[1].submit(snapshot))
    a, b = first.result(), second.result()
    if a.view.record != b.view.record or a.view.request != b.view.request:
        raise ExampleInvariantError()
    created = int(a.created) + int(b.created)
    if created > 1:
        raise ExampleInvariantError()
    work_id = a.view.record.work_id
    if (await coordinators[0].get(work_id)) != a.view:
        raise ExampleInvariantError()
    result = await runner.run_once(work_id, execution_command_id)
    if result.view.result is None or result.view.execution.result is None:
        raise ExampleInvariantError()
    received = await delivery.deliver_once(work_id)
    authorized = await authorizer.authorize_once(
        work_id, confirmation=trusted_confirmation, command_id=confirmation_command_id
    )
    known = await inspect_accepted(
        work_id,
        coordinator=coordinators[0],
        runner=runner,
        delivery=delivery,
        authorizer=authorizer,
    )
    if known.delivery.snapshot != received.snapshot or known.action != authorized.receipt:
        raise ExampleInvariantError()
    return CompletionSummary(
        work_id,
        a.view.record.payload.sha256,
        result.view.execution.result.sha256,
        created,
        result.invoked,
        received.state,
        authorized.receipt.action_id,
    )
