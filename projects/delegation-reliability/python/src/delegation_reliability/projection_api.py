"""Credential-bound reads and private projection persistence with finite ownership.

Synchronous factories validate existing owner-installed state. Import performs no
I/O. Cancellation/timeout retains actual owned work until settlement; no retry or
background projection loop is created.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol, TypeVar

from continuity_lab.work_api import (
    BearerToken,
    PostgresSettings,
    WorkDirectory,
    WorkError,
    WorkScope,
)

from .projection_models import (
    ProjectedResult,
    ProjectionBatch,
    ProjectionBinding,
    ProjectionCheckpoint,
    ProjectionError,
    ProjectionLimits,
    parse_projected,
    uuid,
)
from .projection_store import ProjectionStore

__all__ = [
    "ProjectedResult",
    "ProjectionBatch",
    "ProjectionBinding",
    "ProjectionCheckpoint",
    "ProjectionClient",
    "ProjectionError",
    "ProjectionLimits",
    "open_projection_client",
]
LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
T = TypeVar("T")


class _Closable(Protocol):
    async def close(self) -> None: ...


@dataclass(eq=False, slots=True)
class _Call:
    deadline: float
    writing: bool = False
    abandoned: bool = False
    task: asyncio.Task[object] | None = field(default=None, repr=False)


class _ProjectionOwner:
    def __init__(
        self,
        owned: tuple[_Closable, ...] = (),
        *,
        max_active: int = 2,
        timeout_ms: int = 5000,
        cleanup_ms: int = 1000,
    ) -> None:
        if (
            type(max_active) is not int
            or not 1 <= max_active <= 4
            or type(timeout_ms) is not int
            or not 20 <= timeout_ms <= 10000
            or type(cleanup_ms) is not int
            or not 20 <= cleanup_ms <= 5000
        ):
            raise ProjectionError("invalid_input")
        self._owned = owned
        self._maximum = max_active
        self._timeout = timeout_ms / 1000
        self._cleanup = cleanup_ms / 1000
        self._calls: set[_Call] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None
        self._counts = {
            "started": 0,
            "succeeded": 0,
            "failed": 0,
            "timed_out_waiters": 0,
            "cancelled_waiters": 0,
            "capacity_rejected": 0,
            "telemetry_failed": 0,
        }

    @property
    def pending_count(self) -> int:
        return len(self._calls)

    def metrics(self) -> MappingProxyType[str, int]:
        return MappingProxyType({**self._counts, "active": self.pending_count})

    def _bind(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        if self._loop is not loop:
            raise ProjectionError("invalid_input")
        return loop

    def _check(self, call: _Call) -> None:
        if call.abandoned:
            raise ProjectionError("request_aborted")
        if self._bind().time() >= call.deadline:
            raise ProjectionError("deadline_exceeded")

    async def _run(self, name: str, operation: Callable[[_Call], Awaitable[T]]) -> T:
        loop = self._bind()
        if self._closed:
            raise ProjectionError("closed")
        if len(self._calls) >= self._maximum:
            self._counts["capacity_rejected"] += 1
            raise ProjectionError("capacity")
        call = _Call(loop.time() + self._timeout)
        self._calls.add(call)
        self._counts["started"] += 1

        async def actual() -> T:
            code, outcome = "ok", "succeeded"
            try:
                return await operation(call)
            except ProjectionError as error:
                code, outcome = error.code, "failed"
                raise
            except asyncio.CancelledError:
                code, outcome = "request_aborted", "failed"
                raise
            except Exception:  # noqa: BLE001 - stable public boundary; never dependency text
                code, outcome = "storage_unavailable", "failed"
                raise ProjectionError("storage_unavailable") from None
            finally:
                self._counts[outcome] += 1
                try:
                    LOGGER.info(
                        "result_projection",
                        extra={"operation": name, "code": code, "outcome": outcome},
                    )
                except Exception:  # noqa: BLE001 - telemetry cannot alter persisted truth
                    self._counts["telemetry_failed"] += 1

        task = loop.create_task(actual())
        call.task = task

        def settled(done: asyncio.Task[T]) -> None:
            self._calls.discard(call)
            if not done.cancelled():
                done.exception()

        task.add_done_callback(settled)
        try:
            async with asyncio.timeout_at(call.deadline):
                result = await asyncio.shield(task)
                if loop.time() >= call.deadline:
                    raise TimeoutError
                return result
        except TimeoutError:
            call.abandoned = True
            self._counts["timed_out_waiters"] += 1
            raise ProjectionError(
                "acknowledgement_unknown" if call.writing else "deadline_exceeded"
            ) from None
        except asyncio.CancelledError:
            call.abandoned = True
            self._counts["cancelled_waiters"] += 1
            raise

    async def close(self) -> None:
        loop = self._bind()
        self._closed = True
        for call in self._calls:
            if not call.writing:
                call.abandoned = True
        if (
            self._close_task is not None
            and self._close_task.done()
            and (self._close_task.cancelled() or self._close_task.exception() is not None)
        ):
            self._close_task = None
        if self._close_task is None:

            async def finish() -> None:
                tasks = [call.task for call in self._calls if call.task is not None]
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                outcomes = await asyncio.gather(
                    *(resource.close() for resource in self._owned), return_exceptions=True
                )
                if any(isinstance(result, BaseException) for result in outcomes):
                    raise ProjectionError("cleanup_incomplete")

            self._close_task = loop.create_task(finish())
            self._close_task.add_done_callback(
                lambda done: None if done.cancelled() else done.exception()
            )
        try:
            async with asyncio.timeout(self._cleanup):
                await asyncio.shield(self._close_task)
        except TimeoutError:
            raise ProjectionError("cleanup_incomplete") from None
        if self._calls:
            raise ProjectionError("cleanup_incomplete")


class ProjectionClient(_ProjectionOwner):
    """Read API; its private write path is used only by validating projector code."""

    def __init__(
        self,
        store: ProjectionStore,
        directory: WorkDirectory,
        token: BearerToken,
        *,
        max_active: int = 2,
        timeout_ms: int = 5000,
        cleanup_ms: int = 1000,
    ) -> None:
        super().__init__(max_active=max_active, timeout_ms=timeout_ms, cleanup_ms=cleanup_ms)
        self._store = store
        self._directory = directory
        self._token = token
        self._authorize()

    def _authorize(self) -> None:
        try:
            scope = self._directory.authenticate(self._token).scope
        except WorkError:
            raise ProjectionError("unauthorized") from None
        if scope != self._store.binding.scope:
            raise ProjectionError("unauthorized")

    @property
    def scope(self) -> WorkScope:
        self._authorize()
        scope = self._store.binding.scope
        return WorkScope(scope.tenant_id, scope.account_id)

    @property
    def source_id(self) -> str:
        self._authorize()
        return self._store.binding.source_id

    async def checkpoint(self) -> ProjectionCheckpoint:
        self._authorize()
        return await self._run(
            "checkpoint", lambda _call: asyncio.to_thread(self._store.checkpoint)
        )

    async def get(self, *, work_id: str, attempt_id: str) -> ProjectedResult | None:
        self._authorize()
        work_id = uuid(work_id)
        attempt_id = uuid(attempt_id)
        return await self._run(
            "get", lambda _call: asyncio.to_thread(self._store.get, work_id, attempt_id)
        )

    def _snapshot(
        self, expected: ProjectionCheckpoint, rows: tuple[ProjectedResult, ...]
    ) -> tuple[ProjectionCheckpoint, tuple[ProjectedResult, ...]]:
        self._authorize()
        if (
            type(expected) is not ProjectionCheckpoint
            or expected.binding != self._store.binding
            or type(rows) is not tuple
            or not 1 <= len(rows) <= 8
        ):
            raise ProjectionError("invalid_input")
        copied = tuple(parse_projected(row.canonical()) for row in rows)
        for index, row in enumerate(copied, 1):
            if (
                row.event.source_id != expected.binding.source_id
                or row.event.scope != expected.binding.scope
                or row.event.sequence != expected.sequence + index
            ):
                raise ProjectionError("invalid_input")
        point = ProjectionCheckpoint(
            ProjectionBinding(
                expected.binding.source_id,
                WorkScope(expected.binding.scope.tenant_id, expected.binding.scope.account_id),
            ),
            expected.sequence,
            expected.record_count,
        )
        return point, copied

    async def _apply(
        self, expected: ProjectionCheckpoint, rows: tuple[ProjectedResult, ...]
    ) -> ProjectionBatch:
        expected, rows = self._snapshot(expected, rows)

        async def apply(call: _Call) -> ProjectionBatch:
            self._check(call)
            call.writing = True
            return await asyncio.to_thread(self._store.apply, expected, rows)

        return await self._run("apply", apply)

    async def _reconcile(
        self, expected: ProjectionCheckpoint, rows: tuple[ProjectedResult, ...]
    ) -> ProjectionBatch | None:
        expected, rows = self._snapshot(expected, rows)
        return await self._run(
            "reconcile", lambda _call: asyncio.to_thread(self._store.reconcile, expected, rows)
        )


def open_projection_client(
    *,
    settings: PostgresSettings,
    directory: WorkDirectory,
    token: BearerToken,
    source_id: str,
    harness_failpoint: Callable[[str], None] | None = None,
    max_active: int = 2,
    timeout_ms: int = 5000,
    cleanup_ms: int = 1000,
) -> ProjectionClient:
    """Trusted synchronous startup; explicit existing v1 only, no DDL or env read."""
    if type(directory) is not WorkDirectory:
        raise ProjectionError("invalid_input")
    try:
        scope = directory.authenticate(token).scope
    except WorkError:
        raise ProjectionError("unauthorized") from None
    if harness_failpoint is not None and not callable(harness_failpoint):
        raise ProjectionError("invalid_input")
    binding = ProjectionBinding(source_id, WorkScope(scope.tenant_id, scope.account_id))
    return ProjectionClient(
        ProjectionStore(settings, binding, harness_failpoint),
        directory,
        token,
        max_active=max_active,
        timeout_ms=timeout_ms,
        cleanup_ms=cleanup_ms,
    )
