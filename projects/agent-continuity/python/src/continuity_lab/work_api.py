"""Public credential-bound accepted-work API for the opt-in read-only profile.

Importing performs no network/DDL. The synchronous factory is trusted startup;
move it off conversational event loops. No method grants a mutation or attempt.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from time import monotonic
from types import MappingProxyType
from typing import TypeVar

from .authorization import BearerToken
from .bounded_io import BoundedAsyncIO
from .execution_models import ExecutionCapacityExceeded, ExecutionPortClosed
from .postgres_settings import PostgresSettings
from .work_models import (
    TaskExecutionPort,
    WorkCancellation,
    WorkDirectory,
    WorkError,
    WorkLimits,
    WorkPayload,
    WorkPrincipal,
    WorkRecord,
    WorkScope,
    WorkSubmission,
)
from .work_store import WorkStore

__all__ = [
    "BearerToken",
    "PostgresSettings",
    "TaskExecutionPort",
    "WorkCancellation",
    "WorkClient",
    "WorkDirectory",
    "WorkError",
    "WorkLimits",
    "WorkPayload",
    "WorkPrincipal",
    "WorkRecord",
    "WorkScope",
    "WorkSubmission",
    "open_work_client",
]
T = TypeVar("T")


class WorkClient:
    """One trusted credential binding and at most four actual offloaded I/O calls.

    Cancelling a waiter never rolls back a known committed row or frees an owned
    thread early. close rejects new calls and observes actual I/O for five seconds;
    incomplete cleanup fails and may be observed again after pending work settles.
    """

    def __init__(self, store: WorkStore, directory: WorkDirectory, token: BearerToken) -> None:
        if type(store) is not WorkStore or type(directory) is not WorkDirectory:
            raise WorkError("invalid_input")
        directory.authenticate(token)
        self._store, self._directory, self._token = store, directory, token
        self._io = BoundedAsyncIO(maximum=4, admission_timeout=0.05, shutdown_timeout=5)

    @property
    def scope(self) -> WorkScope:
        """Verified immutable credential scope, available before any write."""
        return self._directory.authenticate(self._token).scope

    @property
    def pending_count(self) -> int:
        return self._io.pending_count

    def metrics(self) -> Mapping[str, int]:
        """Process-local resource/log-sink observations, never durable totals."""
        return MappingProxyType(
            {"pending": self.pending_count, "telemetry_failures": self._store.telemetry_failures}
        )

    async def _run(self, operation: Callable[[WorkScope], T]) -> T:
        scope = self._directory.authenticate(self._token).scope
        try:
            return await self._io._run(lambda: operation(scope))
        except ExecutionCapacityExceeded:
            raise WorkError("capacity") from None
        except ExecutionPortClosed:
            raise WorkError("closed") from None

    async def submit(self, *, idempotency_key: str, payload: WorkPayload) -> WorkSubmission:
        if type(payload) is not WorkPayload:
            raise WorkError("invalid_input")
        snapshot = WorkPayload(payload.operation, payload.body, payload.deadline_at_ms)
        return await self._run(lambda scope: self._store.submit(scope, idempotency_key, snapshot))

    async def find(self, *, idempotency_key: str) -> WorkRecord | None:
        return await self._run(lambda scope: self._store.find(scope, idempotency_key))

    async def get(self, *, work_id: str) -> WorkRecord:
        return await self._run(lambda scope: self._store.get(scope, work_id))

    async def cancel(self, *, work_id: str, command_id: str) -> WorkCancellation:
        return await self._run(lambda scope: self._store.cancel(scope, work_id, command_id))

    async def close(self) -> None:
        deadline = monotonic() + 5
        try:
            await self._io.close()
            if monotonic() >= deadline:
                raise WorkError("cleanup_incomplete")
        except TimeoutError:
            raise WorkError("cleanup_incomplete") from None


def open_work_client(
    *,
    settings: PostgresSettings,
    directory: WorkDirectory,
    token: BearerToken,
    harness_failpoint: Callable[[str], None] | None = None,
) -> WorkClient:
    """Validate existing marked schema at trusted synchronous startup, never DDL.

    harness_failpoint is a trusted test-only commit barrier, not an executor and
    cannot be chosen by payload data. Tokens/scopes are operator configuration.
    """
    if type(directory) is not WorkDirectory:
        raise WorkError("invalid_input")
    directory.authenticate(token)
    if harness_failpoint is not None and not callable(harness_failpoint):
        raise WorkError("invalid_input")
    return WorkClient(WorkStore(settings, harness_failpoint), directory, token)
