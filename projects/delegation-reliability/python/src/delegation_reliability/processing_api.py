"""Credential-bound processing reads; private writes belong to CompletionProcessor."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from continuity_lab.work_api import (
    BearerToken,
    PostgresSettings,
    WorkDirectory,
    WorkError,
    WorkScope,
)

from .processing_models import (
    CompletionPolicy,
    ProcessingAcknowledgement,
    ProcessingCheckpoint,
    ProcessingPage,
    parse_ack,
    snapshot_policy,
)
from .processing_store import ProcessingStore
from .projection_api import _Call, _ProjectionOwner
from .projection_models import (
    ProjectedResult,
    ProjectionBinding,
    ProjectionError,
    parse_projected,
    uuid,
)


class ProcessingClient(_ProjectionOwner):
    def __init__(
        self,
        store: ProcessingStore,
        directory: WorkDirectory,
        token: BearerToken,
        *,
        max_active: int = 2,
        timeout_ms: int = 5000,
        cleanup_ms: int = 1000,
    ) -> None:
        super().__init__(max_active=max_active, timeout_ms=timeout_ms, cleanup_ms=cleanup_ms)
        self._store, self._directory, self._token = store, directory, token
        self._authorize()

    def _authorize(self) -> None:
        try:
            scope = self._directory.authenticate(self._token).scope
            if scope != self._store.binding.scope:
                raise ProjectionError("unauthorized")
        except WorkError:
            raise ProjectionError("unauthorized") from None

    @property
    def scope(self) -> WorkScope:
        self._authorize()
        return WorkScope(self._store.binding.scope.tenant_id, self._store.binding.scope.account_id)

    @property
    def source_id(self) -> str:
        self._authorize()
        return self._store.binding.source_id

    @property
    def policy(self) -> CompletionPolicy:
        self._authorize()
        return snapshot_policy(self._store.policy)

    async def checkpoint(self) -> ProcessingCheckpoint:
        self._authorize()
        return await self._run(
            "processing_checkpoint", lambda _call: asyncio.to_thread(self._store.checkpoint)
        )

    async def acknowledgement(self, *, event_id: str) -> ProcessingAcknowledgement | None:
        self._authorize()
        event_id = uuid(event_id)
        return await self._run(
            "processing_ack_read",
            lambda _call: asyncio.to_thread(self._store.acknowledgement, event_id),
        )

    async def _page(self, limit: int) -> ProcessingPage:
        self._authorize()
        if type(limit) is not int or not 1 <= limit <= 8:
            raise ProjectionError("invalid_input")
        return await self._run(
            "processing_page", lambda _call: asyncio.to_thread(self._store.page, limit)
        )

    async def _commit(
        self,
        expected: ProcessingCheckpoint,
        row: ProjectedResult,
        ack: ProcessingAcknowledgement | None,
    ) -> tuple[ProcessingCheckpoint, ProcessingAcknowledgement | None]:
        self._authorize()
        if (
            type(expected) is not ProcessingCheckpoint
            or expected.binding != self._store.binding
            or expected.policy_sha256 != self.policy.sha256
        ):
            raise ProjectionError("identity_conflict")
        point = ProcessingCheckpoint(
            ProjectionBinding(
                expected.binding.source_id,
                WorkScope(expected.binding.scope.tenant_id, expected.binding.scope.account_id),
            ),
            expected.policy_sha256,
            expected.revision,
            expected.terminal_watermark,
            expected.scan_after,
            expected.terminal_count,
            expected.projected_through,
        )
        copied = parse_projected(row.canonical())
        observed = None if ack is None else parse_ack(ack.canonical())

        async def write(
            call: _Call,
        ) -> tuple[ProcessingCheckpoint, ProcessingAcknowledgement | None]:
            self._check(call)
            call.writing = True
            return await asyncio.to_thread(self._store.commit, point, copied, observed)

        return await self._run("processing_commit", write)

    async def _reconcile(
        self, row: ProjectedResult
    ) -> tuple[ProcessingCheckpoint, ProcessingAcknowledgement] | None:
        self._authorize()
        copied = parse_projected(row.canonical())
        return await self._run(
            "processing_reconcile", lambda _call: asyncio.to_thread(self._store.reconcile, copied)
        )


def open_processing_client(
    *,
    settings: PostgresSettings,
    directory: WorkDirectory,
    token: BearerToken,
    source_id: str,
    policy: CompletionPolicy,
    harness_failpoint: Callable[[str], None] | None = None,
    max_active: int = 2,
    timeout_ms: int = 5000,
    cleanup_ms: int = 1000,
) -> ProcessingClient:
    if type(directory) is not WorkDirectory:
        raise ProjectionError("invalid_input")
    try:
        scope = directory.authenticate(token).scope
    except WorkError:
        raise ProjectionError("unauthorized") from None
    if harness_failpoint is not None and not callable(harness_failpoint):
        raise ProjectionError("invalid_input")
    binding = ProjectionBinding(source_id, WorkScope(scope.tenant_id, scope.account_id))
    return ProcessingClient(
        ProcessingStore(settings, binding, snapshot_policy(policy), harness_failpoint),
        directory,
        token,
        max_active=max_active,
        timeout_ms=timeout_ms,
        cleanup_ms=cleanup_ms,
    )
