"""Real held thread proves installed async cancellation and finite cleanup ownership."""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from continuity_lab.api import (
    AsyncExecutionStore,
    BookingChange,
    ExecutionCapacityExceeded,
    ExecutionPortClosed,
    ExecutionRecord,
    ExecutionStore,
    ExecutionSubmission,
    Operation,
    migrate,
)


async def exercise(root: Path) -> None:
    database = root / "held.sqlite3"
    migrate(database, root / "held-backup.sqlite3")
    store = ExecutionStore(database)
    loop = asyncio.get_running_loop()
    started, finished = asyncio.Event(), asyncio.Event()
    release = threading.Event()

    class HeldPort:
        def submit(
            self,
            *,
            scope_id: str,
            idempotency_key: str,
            request: BookingChange,
            operation: str = Operation.INQUIRE,
        ) -> ExecutionSubmission:
            loop.call_soon_threadsafe(started.set)
            try:
                if not release.wait(timeout=5):
                    raise TimeoutError("The owned fixture barrier was not released")
                return store.submit(
                    scope_id=scope_id,
                    idempotency_key=idempotency_key,
                    request=request,
                    operation=operation,
                )
            finally:
                loop.call_soon_threadsafe(finished.set)

        def get(self, *, scope_id: str, task_id: str) -> ExecutionRecord:
            return store.get(scope_id=scope_id, task_id=task_id)

    wrapper = AsyncExecutionStore(
        HeldPort(), maximum=1, admission_timeout=0.02, shutdown_timeout=0.02
    )
    request = BookingChange("DEMO-BK-001", date(2030, 12, 10), True)
    caller = asyncio.create_task(
        wrapper.submit(scope_id="resource-fixture", idempotency_key="stable-key", request=request)
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        caller.cancel()
        try:
            await caller
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("Caller cancellation did not propagate")
        assert wrapper.pending_count == 1
        try:
            await wrapper.get(scope_id="resource-fixture", task_id="not-started")
        except ExecutionCapacityExceeded:
            pass
        else:
            raise AssertionError("Pending work released capacity prematurely")
        try:
            await wrapper.close()
        except TimeoutError:
            pass
        else:
            raise AssertionError("Held work unexpectedly completed cleanup")
        assert wrapper.pending_count == 1
        release.set()
        await asyncio.wait_for(finished.wait(), timeout=2)
        await wrapper.close()
        assert wrapper.pending_count == 0
        replay = ExecutionStore(database).submit(
            scope_id="resource-fixture", idempotency_key="stable-key", request=request
        )
        assert not replay.created and not replay.enrolled
        try:
            await wrapper.get(scope_id="resource-fixture", task_id=replay.execution.task_id)
        except ExecutionPortClosed:
            pass
        else:
            raise AssertionError("Closed wrapper admitted new work")
    finally:
        release.set()
        await asyncio.gather(caller, return_exceptions=True)
        await wrapper.close()


def main() -> int:
    with TemporaryDirectory(prefix="installed-resource-") as directory:
        asyncio.run(exercise(Path(directory)))
    print(
        json.dumps(
            {
                "schema_version": 1,
                "status": "passed",
                "cancelled_waiter_propagated": True,
                "capacity_retained_until_real_completion": True,
                "close_timeout_preserved_pending_work": True,
                "accepted_write_survived_waiter_cancellation": True,
                "closed_rejected_new_work": True,
                "pending_after_cleanup": 0,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
