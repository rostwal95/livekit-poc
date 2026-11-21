"""Public P1-issued read-only attempts/results; imports never start I/O or upgrade."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TypeVar

from .authorization import BearerToken
from .execution_store import ExecutionStore
from .issued_models import (
    AttemptResult,
    ExecutionLimits,
    ExecutionObservation,
    ExecutionPort,
    Issuance,
    IssuedAttempt,
)
from .postgres_settings import PostgresSettings
from .work_api import WorkClient, open_work_client
from .work_models import WorkDirectory, WorkError, WorkPayload, WorkRecord, WorkScope

__all__ = [
    "AttemptResult",
    "BearerToken",
    "ExecutionClient",
    "ExecutionLimits",
    "ExecutionObservation",
    "ExecutionPort",
    "Issuance",
    "IssuedAttempt",
    "PostgresSettings",
    "WorkDirectory",
    "WorkError",
    "WorkRecord",
    "WorkScope",
    "open_execution_client",
]
T = TypeVar("T")


class ExecutionClient:
    """Four actual offloaded I/O calls; waiter cancellation retains real ownership."""

    def __init__(self, work: WorkClient, store: ExecutionStore) -> None:
        if type(work) is not WorkClient or type(store) is not ExecutionStore:
            raise WorkError("invalid_input")
        self._work, self._store = work, store

    @property
    def scope(self) -> WorkScope:
        return self._work.scope

    @property
    def pending_count(self) -> int:
        return self._work.pending_count

    def metrics(self) -> Mapping[str, int]:
        return self._work.metrics()

    async def _run(self, operation: Callable[[WorkScope], T]) -> T:
        return await self._work._run(operation)

    async def issue(self, *, work_id: str, owner_id: str, command_id: str) -> Issuance:
        return await self._run(
            lambda scope: self._store.issue(scope, work_id, owner_id, command_id)
        )

    async def find_issue(self, *, command_id: str) -> IssuedAttempt | None:
        return await self._run(lambda scope: self._store.find_issue(scope, command_id))

    async def complete(self, *, attempt: IssuedAttempt, body: bytes) -> AttemptResult:
        if (
            type(attempt) is not IssuedAttempt
            or type(attempt.record) is not WorkRecord
            or type(attempt.record.scope) is not WorkScope
            or type(attempt.record.payload) is not WorkPayload
        ):
            raise WorkError("invalid_input")
        # Rebuild every nested public value before any await; caller objects are not authority.
        record = WorkRecord(
            attempt.record.work_id,
            WorkScope(attempt.record.scope.tenant_id, attempt.record.scope.account_id),
            attempt.record.idempotency_key,
            WorkPayload(
                attempt.record.payload.operation,
                attempt.record.payload.body,
                attempt.record.payload.deadline_at_ms,
            ),
            attempt.record.accepted_at_ms,
            attempt.record.cancel_requested,
            attempt.record.status,
        )
        snapshot = IssuedAttempt(
            record,
            attempt.attempt_id,
            attempt.command_id,
            attempt.number,
            attempt.owner_id,
            attempt.epoch,
            attempt.issued_at_ms,
            attempt.lease_until_ms,
        )
        if type(body) is not bytes or not 1 <= len(body) <= 8192:
            raise WorkError("invalid_input")
        return await self._run(lambda scope: self._store.complete(scope, snapshot, body))

    async def result(self, *, work_id: str, attempt_id: str) -> AttemptResult | None:
        return await self._run(lambda scope: self._store.result(scope, work_id, attempt_id))

    async def observe(self, *, work_id: str) -> ExecutionObservation:
        return await self._run(lambda scope: self._store.observe(scope, work_id))

    async def close(self) -> None:
        await self._work.close()


def open_execution_client(
    *,
    settings: PostgresSettings,
    directory: WorkDirectory,
    token: BearerToken,
    harness_failpoint: Callable[[str], None] | None = None,
) -> ExecutionClient:
    """Open a trusted runtime client against the initialized work schema."""
    client = open_work_client(
        settings=settings, directory=directory, token=token, harness_failpoint=harness_failpoint
    )
    return ExecutionClient(client, ExecutionStore(client._store))
