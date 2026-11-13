"""Finite application I/O offload shared by inquiry and case boundaries."""

import asyncio
import math
from collections.abc import Callable
from types import TracebackType
from typing import Self, TypeVar

from .execution_models import (
    ExecutionCapacityExceeded,
    ExecutionPortClosed,
)

T = TypeVar("T")


class BoundedAsyncIO:
    """Hold an I/O slot until its thread finishes, even when a caller cancels.

    Construct the synchronous adapters during controlled startup, not a media turn.
    Closing rejects new calls and waits for already-started work; it never kills
    a thread or claims a timed-out write was undone.
    """

    def __init__(
        self,
        *,
        maximum: int = 4,
        admission_timeout: float = 0.05,
        shutdown_timeout: float = 10,
    ) -> None:
        if type(maximum) is not int or not 1 <= maximum <= 32:
            raise ValueError("maximum I/O must be between 1 and 32")
        for value in (admission_timeout, shutdown_timeout):
            if type(value) not in {int, float} or not math.isfinite(value) or value <= 0:
                raise ValueError("I/O timeouts must be finite positive seconds")
        self._slots = asyncio.Semaphore(maximum)
        self.admission_timeout, self.shutdown_timeout = admission_timeout, shutdown_timeout
        self._pending: set[asyncio.Task[object]] = set()
        self._closed = False

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    async def _run(self, operation: Callable[[], T]) -> T:
        if self._closed:
            raise ExecutionPortClosed("Execution I/O is closed")
        try:
            await asyncio.wait_for(self._slots.acquire(), timeout=self.admission_timeout)
        except TimeoutError as error:
            raise ExecutionCapacityExceeded("Execution I/O capacity is exhausted") from error
        if self._closed:
            self._slots.release()
            raise ExecutionPortClosed("Execution I/O is closed")
        task = asyncio.create_task(asyncio.to_thread(operation))
        self._pending.add(task)

        def finished(completed: asyncio.Task[object]) -> None:
            self._pending.discard(completed)
            self._slots.release()
            if not completed.cancelled():
                completed.exception()  # Observe orphaned failure, never its private text.

        task.add_done_callback(finished)
        return await asyncio.shield(task)

    async def close(self) -> None:
        self._closed = True
        if self._pending:
            # Timeout/cancellation of close must not cancel the underlying threads.
            await asyncio.wait_for(
                asyncio.shield(asyncio.gather(*tuple(self._pending), return_exceptions=True)),
                timeout=self.shutdown_timeout,
            )

    async def __aenter__(self) -> Self:
        if self._closed:
            raise ExecutionPortClosed("Execution I/O is closed")
        return self

    async def __aexit__(
        self,
        error_type: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            await self.close()
        except TimeoutError:
            if error is None:
                raise
            error.add_note(
                "Execution I/O cleanup incomplete; already-started work still owns capacity."
            )
