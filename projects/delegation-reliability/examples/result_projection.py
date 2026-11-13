"""Explicit result projection and inspection using configured public clients.

The application installs P1 work v4/P3 projection v1 with separate owner tooling
before constructing clients. It owns the projector's lifecycle; the projector
owns its feed/execution/projection clients and the application owns its case port.
Import starts no DDL, tasks, listener or provider. Stored applicability describes
non-atomic past reads and cannot authorize a current action.
"""

from __future__ import annotations

from dataclasses import dataclass

from delegation_reliability import (
    ProjectedResult,
    ProjectionBatch,
    ProjectionCheckpoint,
    ProjectionClient,
    ProjectionProjector,
)


@dataclass(frozen=True, slots=True)
class ProjectionInspection:
    checkpoint: ProjectionCheckpoint
    result: ProjectedResult | None


async def project_results(projector: ProjectionProjector, *, limit: int = 4) -> ProjectionBatch:
    """Consume at most eight references once; the caller explicitly schedules later steps."""
    return await projector.project_once(limit=limit)


async def inspect_projected(
    client: ProjectionClient, *, work_id: str, attempt_id: str
) -> ProjectionInspection:
    """Read checkpoint then exact result separately; neither read advances the source."""
    point = await client.checkpoint()
    row = await client.get(work_id=work_id, attempt_id=attempt_id)
    return ProjectionInspection(point, row)
