"""Finite async offload for the synchronous inquiry port, owned by one event loop."""

from .bounded_io import BoundedAsyncIO
from .execution_models import ExecutionRecord, ExecutionSubmission, InquiryExecutionPort, Operation
from .models import BookingChange


class AsyncExecutionStore(BoundedAsyncIO):
    """Hold an I/O slot until its thread finishes, even when a caller cancels."""

    def __init__(
        self,
        store: InquiryExecutionPort,
        *,
        maximum: int = 4,
        admission_timeout: float = 0.05,
        shutdown_timeout: float = 10,
    ) -> None:
        super().__init__(
            maximum=maximum, admission_timeout=admission_timeout, shutdown_timeout=shutdown_timeout
        )
        self.store = store

    async def submit(
        self,
        *,
        scope_id: str,
        idempotency_key: str,
        request: BookingChange,
        operation: str = Operation.INQUIRE,
    ) -> ExecutionSubmission:
        return await self._run(
            lambda: self.store.submit(
                scope_id=scope_id,
                idempotency_key=idempotency_key,
                request=request,
                operation=operation,
            )
        )

    async def get(self, *, scope_id: str, task_id: str) -> ExecutionRecord:
        return await self._run(lambda: self.store.get(scope_id=scope_id, task_id=task_id))
