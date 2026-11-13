"""Public scoped result delivery intent/receipt API; imports perform no I/O or DDL."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TypeVar

from .authorization import BearerToken
from .delivery_models import (
    DeliveryIntent,
    DeliveryPort,
    DeliveryReceipt,
    DeliverySnapshot,
    DeliveryStart,
    snapshot_intent,
    snapshot_receipt,
)
from .delivery_store import DeliveryStore
from .postgres_settings import PostgresSettings
from .work_api import WorkClient, open_work_client
from .work_models import WorkDirectory, WorkError, WorkScope

__all__ = [
    "DeliveryClient",
    "DeliveryIntent",
    "DeliveryPort",
    "DeliveryReceipt",
    "DeliverySnapshot",
    "DeliveryStart",
    "open_delivery_client",
]
T = TypeVar("T")


class DeliveryClient:
    """A version-3 scoped client, four retained actual I/O slots and explicit close."""

    def __init__(self, work: WorkClient, store: DeliveryStore) -> None:
        if type(work) is not WorkClient or type(store) is not DeliveryStore:
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

    async def prepare(
        self,
        *,
        work_id: str,
        attempt_id: str,
        result_sha256: str,
        receiver_id: str,
        recipient_id: str,
    ) -> DeliveryIntent:
        return await self._run(
            lambda scope: self._store.prepare(
                scope, work_id, attempt_id, result_sha256, receiver_id, recipient_id
            )
        )

    async def begin(self, *, intent: DeliveryIntent) -> DeliveryStart:
        snapshot = snapshot_intent(intent)
        return await self._run(lambda scope: self._store.begin(scope, snapshot))

    async def record_receipt(
        self, *, intent: DeliveryIntent, receipt: DeliveryReceipt
    ) -> DeliveryReceipt:
        original, observation = snapshot_intent(intent), snapshot_receipt(receipt)
        return await self._run(
            lambda scope: self._store.record_receipt(scope, original, observation)
        )

    async def inspect(self, *, work_id: str) -> DeliverySnapshot:
        return await self._run(lambda scope: self._store.inspect(scope, work_id))

    async def close(self) -> None:
        await self._work.close()


def open_delivery_client(
    *,
    settings: PostgresSettings,
    directory: WorkDirectory,
    token: BearerToken,
    harness_failpoint: Callable[[str], None] | None = None,
) -> DeliveryClient:
    """Trusted synchronous startup of an already explicitly upgraded v3 profile."""
    work = open_work_client(
        settings=settings, directory=directory, token=token, harness_failpoint=harness_failpoint
    )
    return DeliveryClient(work, DeliveryStore(work._store))
