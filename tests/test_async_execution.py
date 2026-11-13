"""Real threaded barriers verify finite async store ownership and cancellation."""

import asyncio
import gc
import threading
import unittest
from datetime import date

from continuity_lab.async_execution import AsyncExecutionStore
from continuity_lab.execution_models import (
    ExecutionCapacityExceeded,
    ExecutionPortClosed,
    ExecutionRecord,
    ExecutionStatus,
    ExecutionSubmission,
    Operation,
)
from continuity_lab.models import BookingChange


class BlockingPort:
    """The external synchronous boundary, controlled without mocking asyncio."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.started = asyncio.Event()
        self.finished = asyncio.Event()
        self.release = threading.Event()
        self.lock = threading.Lock()
        self.active = 0
        self.maximum_active = 0
        self.submit_calls = 0
        self.get_calls = 0
        self.error: Exception | None = None
        self.arguments: tuple[str, str, BookingChange, str] | None = None
        self.lookup: tuple[str, str] | None = None
        self.request = BookingChange("DEMO-BK-001", date(2030, 12, 10), confirmed=True)
        self.record = ExecutionRecord(
            task_id="11111111-1111-4111-8111-111111111111",
            scope_id="traveller-a",
            idempotency_key="request-a",
            request=self.request,
            operation=Operation.INQUIRE,
            status=ExecutionStatus.ACCEPTED,
            effect_id="22222222-2222-4222-8222-222222222222",
            version=0,
            created_at="2026-11-09T10:00:00+00:00",
            updated_at="2026-11-09T10:00:00+00:00",
            result=None,
            error_code=None,
        )

    def submit(
        self,
        *,
        scope_id: str,
        idempotency_key: str,
        request: BookingChange,
        operation: str = Operation.INQUIRE,
    ) -> ExecutionSubmission:
        with self.lock:
            self.submit_calls += 1
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
            self.arguments = scope_id, idempotency_key, request, operation
        self.loop.call_soon_threadsafe(self.started.set)
        try:
            if not self.release.wait(timeout=2):
                raise TimeoutError("The test-owned thread barrier was not released")
            if self.error is not None:
                raise self.error
            return ExecutionSubmission(self.record, created=True, enrolled=True)
        finally:
            with self.lock:
                self.active -= 1
            self.loop.call_soon_threadsafe(self.finished.set)

    def get(self, *, scope_id: str, task_id: str) -> ExecutionRecord:
        with self.lock:
            self.get_calls += 1
            self.lookup = scope_id, task_id
        return self.record


class AsyncExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.loop = asyncio.get_running_loop()
        self.port = BlockingPort(self.loop)
        self.wrapper = AsyncExecutionStore(
            self.port, maximum=1, admission_timeout=0.03, shutdown_timeout=1
        )
        self.tasks: set[asyncio.Task] = set()

    async def asyncTearDown(self):
        # Always release real threads before IsolatedAsyncioTestCase shuts down
        # its executor. Assertion failures must not leave the test process hung.
        self.port.release.set()
        await self.wrapper.close()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)

    def submit(self) -> asyncio.Task[ExecutionSubmission]:
        task = asyncio.create_task(
            self.wrapper.submit(
                scope_id="traveller-a", idempotency_key="request-a", request=self.port.request
            )
        )
        self.tasks.add(task)
        return task

    async def started(self) -> None:
        await asyncio.wait_for(self.port.started.wait(), timeout=1)

    async def scheduling_checkpoint(self) -> None:
        """Let previously scheduled calls enter their first await, without sleeping."""
        checkpoint = self.loop.create_future()
        self.loop.call_soon(checkpoint.set_result, None)
        await checkpoint

    async def test_cancelled_caller_holds_slot_until_real_work_finishes(self):
        caller = self.submit()
        await self.started()
        self.assertEqual(self.wrapper.pending_count, 1)
        caller.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await caller
        self.assertEqual(self.wrapper.pending_count, 1)
        with self.assertRaises(ExecutionCapacityExceeded):
            await self.wrapper.get(scope_id="traveller-a", task_id=self.port.record.task_id)
        self.assertEqual(self.port.get_calls, 0)
        self.assertEqual(self.port.active, 1)
        self.port.release.set()
        await asyncio.wait_for(self.port.finished.wait(), timeout=1)
        current = await self.wrapper.get(scope_id="traveller-a", task_id=self.port.record.task_id)
        self.assertEqual(current, self.port.record)
        self.assertEqual(self.port.get_calls, 1)
        self.assertEqual(self.port.maximum_active, 1)
        self.assertEqual(self.wrapper.pending_count, 0)

    async def test_close_rejects_new_work_and_drains_accepted_thread(self):
        caller = self.submit()
        await self.started()
        closer = asyncio.create_task(self.wrapper.close())
        self.tasks.add(closer)
        # A timeout of the observer, shielded from the actual close operation,
        # proves that close is waiting for the held external boundary.
        with self.assertRaises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(closer), timeout=0.02)
        self.assertFalse(closer.done())
        with self.assertRaises(ExecutionPortClosed):
            await self.wrapper.get(scope_id="traveller-a", task_id=self.port.record.task_id)
        self.assertEqual(self.port.get_calls, 0)
        self.port.release.set()
        submission = await caller
        await closer
        self.assertEqual(submission.execution, self.port.record)
        self.assertEqual(self.wrapper.pending_count, 0)
        self.assertEqual(self.port.active, 0)
        with self.assertRaises(ExecutionPortClosed):
            await self.wrapper.submit(
                scope_id="traveller-a", idempotency_key="request-a", request=self.port.request
            )

    async def test_shutdown_timeout_does_not_cancel_thread_or_erase_its_result(self):
        self.wrapper = AsyncExecutionStore(
            self.port, maximum=1, admission_timeout=0.03, shutdown_timeout=0.02
        )
        caller = self.submit()
        await self.started()
        with self.assertRaises(TimeoutError):
            await self.wrapper.close()
        self.assertEqual(self.wrapper.pending_count, 1)
        self.assertEqual(self.port.active, 1)
        self.assertFalse(caller.done())
        with self.assertRaises(ExecutionPortClosed):
            await self.wrapper.get(scope_id="traveller-a", task_id=self.port.record.task_id)
        self.port.release.set()
        self.assertEqual((await caller).execution, self.port.record)
        await self.wrapper.close()
        self.assertEqual(self.wrapper.pending_count, 0)

    async def test_cancelling_close_preserves_running_thread_and_later_drain(self):
        caller = self.submit()
        await self.started()
        closer = asyncio.create_task(self.wrapper.close())
        self.tasks.add(closer)
        with self.assertRaises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(closer), timeout=0.02)
        closer.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await closer
        self.assertEqual(self.wrapper.pending_count, 1)
        self.assertEqual(self.port.active, 1)
        self.port.release.set()
        self.assertEqual((await caller).execution, self.port.record)
        await self.wrapper.close()
        self.assertEqual(self.wrapper.pending_count, 0)

    async def test_original_failure_propagates_and_slot_is_reusable(self):
        class PrivateFailure(RuntimeError):
            def __str__(self):
                raise AssertionError("Do not inspect private exception text")

            def __repr__(self):
                raise AssertionError("Do not inspect private exception representation")

        error = PrivateFailure("SECRET_SENTINEL")
        self.port.error = error
        self.port.release.set()
        with self.assertRaises(PrivateFailure) as raised:
            await self.submit()
        self.assertIs(raised.exception, error)
        self.assertEqual(self.wrapper.pending_count, 0)
        self.port.error = None
        result = await self.wrapper.get(scope_id="traveller-a", task_id=self.port.record.task_id)
        self.assertEqual(result, self.port.record)
        self.assertEqual(self.port.lookup, ("traveller-a", self.port.record.task_id))
        self.assertEqual(
            self.port.arguments,
            ("traveller-a", "request-a", self.port.request, Operation.INQUIRE),
        )

    async def test_cancelled_waiter_failure_is_retrieved_without_loop_warning(self):
        observed = []
        previous = self.loop.get_exception_handler()
        self.loop.set_exception_handler(lambda _loop, context: observed.append(context))
        self.addCleanup(self.loop.set_exception_handler, previous)
        self.port.error = RuntimeError("SECRET_SENTINEL after cancellation")
        caller = self.submit()
        await self.started()
        caller.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await caller
        self.port.release.set()
        await asyncio.wait_for(self.port.finished.wait(), timeout=1)
        self.port.error = None
        # Progress through another public call proves the orphan's slot was
        # released. Do not use close/gather here: that would itself retrieve the
        # failure and hide a missing completion observer in the adapter.
        await self.wrapper.get(scope_id="traveller-a", task_id=self.port.record.task_id)
        gc.collect()
        await self.scheduling_checkpoint()
        self.assertEqual(observed, [])
        self.assertEqual(self.wrapper.pending_count, 0)
        self.assertEqual(self.port.active, 0)

    async def test_queued_call_cannot_start_after_close(self):
        self.wrapper = AsyncExecutionStore(
            self.port, maximum=1, admission_timeout=0.5, shutdown_timeout=1
        )
        caller = self.submit()
        await self.started()
        waiting = asyncio.create_task(
            self.wrapper.get(scope_id="traveller-a", task_id=self.port.record.task_id)
        )
        self.tasks.add(waiting)
        await self.scheduling_checkpoint()
        closer = asyncio.create_task(self.wrapper.close())
        self.tasks.add(closer)
        with self.assertRaises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(closer), timeout=0.02)
        self.port.release.set()
        await caller
        with self.assertRaises(ExecutionPortClosed):
            await waiting
        await closer
        self.assertEqual(self.port.get_calls, 0)
        self.assertEqual(self.wrapper.pending_count, 0)

    async def test_cancellation_during_admission_does_not_leak_capacity(self):
        self.wrapper = AsyncExecutionStore(
            self.port, maximum=1, admission_timeout=0.5, shutdown_timeout=1
        )
        caller = self.submit()
        await self.started()
        waiting = asyncio.create_task(
            self.wrapper.get(scope_id="traveller-a", task_id=self.port.record.task_id)
        )
        self.tasks.add(waiting)
        await self.scheduling_checkpoint()
        waiting.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiting
        self.assertEqual(self.port.get_calls, 0)
        self.port.release.set()
        await caller
        self.assertEqual(
            await self.wrapper.get(scope_id="traveller-a", task_id=self.port.record.task_id),
            self.port.record,
        )
        self.assertEqual(self.port.get_calls, 1)

    async def test_async_context_closes_and_preserves_original_body_failure(self):
        self.port.release.set()
        failure = RuntimeError("Synthetic body failure")
        with self.assertRaises(RuntimeError) as raised:
            async with self.wrapper as entered:
                self.assertIs(entered, self.wrapper)
                self.assertEqual(
                    await entered.get(scope_id="traveller-a", task_id=self.port.record.task_id),
                    self.port.record,
                )
                raise failure
        self.assertIs(raised.exception, failure)
        self.assertEqual(self.wrapper.pending_count, 0)
        with self.assertRaises(ExecutionPortClosed):
            await self.wrapper.__aenter__()

    async def assert_body_failure_survives_cleanup_timeout(self, error: BaseException) -> None:
        self.wrapper = AsyncExecutionStore(
            self.port, maximum=1, admission_timeout=0.03, shutdown_timeout=0.02
        )
        caller = self.submit()
        await self.started()
        with self.assertRaises(type(error)) as raised:
            async with self.wrapper:
                raise error
        self.assertIs(raised.exception, error)
        self.assertIn(
            "Execution I/O cleanup incomplete; already-started work still owns capacity.",
            error.__notes__,
        )
        self.assertEqual(self.wrapper.pending_count, 1)
        self.assertEqual(self.port.active, 1)
        self.assertFalse(caller.done())
        with self.assertRaises(ExecutionPortClosed):
            await self.wrapper.get(scope_id="traveller-a", task_id=self.port.record.task_id)
        self.port.release.set()
        self.assertEqual((await caller).execution, self.port.record)
        await self.wrapper.close()
        self.assertEqual(self.wrapper.pending_count, 0)

    async def test_body_exception_survives_cleanup_timeout_with_safe_incomplete_note(self):
        await self.assert_body_failure_survives_cleanup_timeout(
            RuntimeError("Synthetic body failure")
        )

    async def test_body_cancellation_survives_cleanup_timeout_with_safe_incomplete_note(self):
        await self.assert_body_failure_survives_cleanup_timeout(asyncio.CancelledError())

    def test_invalid_capacity_and_timeout_configuration_is_rejected(self):
        for maximum in (0, -1, 33, True, 1.5, "4"):
            with self.subTest(maximum=maximum), self.assertRaises(ValueError):
                AsyncExecutionStore(self.port, maximum=maximum)
        for option in ("admission_timeout", "shutdown_timeout"):
            for value in (0, -1, True, float("nan"), float("inf"), "1"):
                with self.subTest(option=option, value=value), self.assertRaises(ValueError):
                    AsyncExecutionStore(self.port, **{option: value})


if __name__ == "__main__":
    unittest.main()
