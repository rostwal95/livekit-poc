"""Explicit refresh and display inspection on configured installed public clients.

Owner setup/upgrades occur separately. The caller owns these configured clients,
provides exact source/case/evidence composition and closes them after use. Import
starts no I/O. A historical command replay is not a fresh current-state read.
"""

from delegation_reliability import (
    ApplicabilityClient,
    ApplicabilityRefresh,
    ApplicabilityRefresher,
    ApplicabilityView,
    DisplayTombstone,
)


async def refresh_result(
    refresher: ApplicabilityRefresher,
    *,
    work_id: str,
    attempt_id: str,
    command_id: str,
    expected_revision: int,
) -> ApplicabilityRefresh:
    """One explicit as-of observation; no action, delivery or source ACK is implied."""
    return await refresher.refresh(
        work_id=work_id,
        attempt_id=attempt_id,
        command_id=command_id,
        expected_revision=expected_revision,
    )


async def inspect_result(
    metadata: ApplicabilityClient,
    *,
    work_id: str,
    attempt_id: str,
) -> ApplicabilityView:
    """Exact authenticated facts survive display hiding and later invalidation."""
    return await metadata.inspect(work_id=work_id, attempt_id=attempt_id)


async def hide_result(
    metadata: ApplicabilityClient,
    *,
    work_id: str,
    attempt_id: str,
) -> DisplayTombstone:
    """Explicit permanent display hide; retained capacity/processing are unchanged."""
    return await metadata.hide_display(work_id=work_id, attempt_id=attempt_id)
