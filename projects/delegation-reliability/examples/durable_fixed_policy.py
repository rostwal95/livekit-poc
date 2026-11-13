"""Configured durable policy-v2 journey, with no implicit setup or import-time I/O.

The application supplies authenticated P1 clients and immutable evidence to the
facades. It owns their bounded close observers and closes shared case readers only
after both facades have actually closed. Preserve original owner/command/input IDs
when resuming; never remint a deadline or interpret a result as mutation consent.
"""

from __future__ import annotations

from delegation_reliability import (
    FixedPolicyCoordinator,
    FixedPolicyRun,
    FixedPolicyRunner,
    FixedPolicySubmission,
)
from delegation_reliability.fixed_policy_contracts import FixedPolicyRequest


async def run_durable_fixed_policy(
    *,
    coordinator: FixedPolicyCoordinator,
    runner: FixedPolicyRunner,
    request: FixedPolicyRequest,
    command_id: str,
) -> tuple[FixedPolicySubmission, FixedPolicyRun]:
    """Acknowledge through P1 before one explicit issued invocation or known replay.

    The returned result and its original commit disposition are retained facts.
    The view's separate as-of applicability is never delivery/action permission.
    Ports remain application-owned; this function starts no worker or scheduler.
    """
    accepted = await coordinator.submit(request)
    observed = await runner.run_once(accepted.view.record.work_id, command_id)
    return accepted, observed
