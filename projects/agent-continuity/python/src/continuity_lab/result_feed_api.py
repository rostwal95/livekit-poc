"""Public read-only scoped result feed; no acknowledgement, scheduler or import-time I/O."""

from __future__ import annotations

from collections.abc import Mapping

from .authorization import BearerToken
from .postgres_settings import PostgresSettings
from .result_feed_models import (
    ResultFeedCursor,
    ResultFeedEvent,
    ResultFeedPage,
    ResultFeedPort,
    copy_cursor,
)
from .result_feed_store import ResultFeedStore
from .work_api import WorkClient
from .work_models import WorkDirectory, WorkError, WorkScope
from .work_store import WorkStore

__all__ = [
    "ResultFeedClient",
    "ResultFeedCursor",
    "ResultFeedEvent",
    "ResultFeedPage",
    "ResultFeedPort",
    "open_result_feed_client",
]


class ResultFeedClient:
    def __init__(
        self, store: ResultFeedStore, directory: WorkDirectory, token: BearerToken
    ) -> None:
        if type(store) is not ResultFeedStore:
            raise WorkError("invalid_input")
        self._store = store
        self._boundary = WorkClient(store.work, directory, token)
        self._source_id = store.source_id

    @property
    def scope(self) -> WorkScope:
        return self._boundary.scope

    @property
    def source_id(self) -> str:
        return self._source_id

    @property
    def pending_count(self) -> int:
        return self._boundary.pending_count

    def metrics(self) -> Mapping[str, int]:
        return self._boundary.metrics()

    async def read(
        self, *, after: ResultFeedCursor | None = None, limit: int = 25
    ) -> ResultFeedPage:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise WorkError("invalid_input")
        cursor = None if after is None else copy_cursor(after)
        current = self.scope
        scope = WorkScope(current.tenant_id, current.account_id)
        if cursor is not None and (cursor.scope != scope or cursor.source_id != self.source_id):
            raise WorkError("identity_conflict")

        def read(actual: WorkScope) -> ResultFeedPage:
            if actual != scope:
                raise WorkError("unauthorized")
            return self._store.read(scope, cursor, limit)

        return await self._boundary._run(read)

    async def close(self) -> None:
        await self._boundary.close()


def open_result_feed_client(
    *, settings: PostgresSettings, directory: WorkDirectory, token: BearerToken
) -> ResultFeedClient:
    if type(directory) is not WorkDirectory:
        raise WorkError("invalid_input")
    directory.authenticate(token)
    return ResultFeedClient(ResultFeedStore(WorkStore(settings)), directory, token)
