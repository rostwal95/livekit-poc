"""Explicit test-owner P1 composition for the local read-only rehydration gate.

Only this fixture imports owner/leased-worker instrumentation. The case bridge and
P2 consumers use public clients; there is no production authority or import I/O.
"""

from __future__ import annotations

import asyncio
import math
import secrets
import time
from collections.abc import Coroutine
from pathlib import Path
from typing import Any
from uuid import uuid4

import p3_case_fixture as fixture
from p2_current_case_bridge import (
    CurrentCaseBinding,
    PublicCurrentCaseReader,
    start_current_case_bridge,
)

from continuity_lab.case_control_api import CaseControlClient
from continuity_lab.conversation_composition import build_conversation_service
from continuity_lab.postgres_api import (
    BearerToken,
    Confirmation,
    ManagedCaseClient,
    PostgresSettings,
)


class P1ReadFixture:
    """The parent owns one marked synthetic authority and one actual fake supplier."""

    def __init__(self, values: dict[str, str], directory: Path, reference: dict[str, Any]) -> None:
        schema = "p3_completion_" + uuid4().hex
        self.owner = PostgresSettings(
            port=int(values["POSTGRES_PORT"]),
            user="continuity_migrator",
            password=values["POSTGRES_MIGRATION_PASSWORD"],
            schema=schema,
        )
        self.runtime = PostgresSettings(
            port=int(values["POSTGRES_PORT"]),
            password=values["POSTGRES_PASSWORD"],
            schema=schema,
        )
        self.supplier = directory / "rehydration-p1-supplier.sqlite3"
        self.token = secrets.token_urlsafe(32)
        self.reference = reference
        self.installed = False
        self.reader: PublicCurrentCaseReader | None = None
        self.managed: ManagedCaseClient | None = None
        self.control: CaseControlClient | None = None
        self.task_id = ""
        self.case_id = ""
        self.bridge: Any = None
        self.advanced = False
        self._operations: set[asyncio.Task[Any]] = set()
        self._resource_closers: dict[str, asyncio.Task[Any]] = {}
        self.closing_requested = False
        self._active_operation: asyncio.Task[Any] | None = None
        self._operation_deadline: float | None = None
        self._operation_abandoned = False
        self._advance_started = False

    async def bounded(self, operation: Coroutine[Any, Any, Any], deadline: float) -> Any:
        """A timed-out waiter retains the actual operation until close observes it."""
        if (
            type(deadline) not in (float, int)
            or not math.isfinite(deadline)
            or deadline <= time.monotonic()
        ):
            operation.close()
            raise TimeoutError()
        if (
            self.closing_requested
            or self._active_operation is not None
            and not self._active_operation.done()
        ):
            operation.close()
            raise RuntimeError("The fixture is closing or already owns an active operation")
        self._operation_deadline = deadline
        self._operation_abandoned = False
        task = asyncio.create_task(operation, name="rehydration-p1-owned-operation")
        self._active_operation = task
        self._operations.add(task)
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        try:
            async with asyncio.timeout(max(0.001, deadline - time.monotonic())):
                return await asyncio.shield(task)
        except (TimeoutError, asyncio.CancelledError):
            if self._active_operation is task:
                self._operation_abandoned = True
            raise

    def _admit_stage(self) -> None:
        """A prior stage may settle late; it never authorizes starting a new one."""
        if (
            self.closing_requested
            or self._operation_abandoned
            or self._operation_deadline is None
            or time.monotonic() >= self._operation_deadline
            or asyncio.current_task() is not self._active_operation
        ):
            raise TimeoutError()

    async def start(self) -> int:
        self._admit_stage()
        if self.installed:
            raise ValueError("Explicit one-shot fixture installation required")
        self.installed = True
        await asyncio.to_thread(fixture.install, self.owner, self.supplier)
        self._admit_stage()
        bearer = BearerToken(secrets.token_urlsafe(32))
        boundary = build_conversation_service(
            actor=fixture.ACTOR,
            token=bearer,
            settings=self.runtime,
            quote_database=self.supplier,
        )
        self.reader = PublicCurrentCaseReader(boundary, bearer, self.runtime.schema)
        self.managed = ManagedCaseClient(boundary, bearer)
        self.control = CaseControlClient(boundary, bearer, self.runtime.schema)
        self._admit_stage()
        accepted = await self.managed.submit(
            idempotency_key="rehydration_current_case", request=fixture.REQUEST
        )
        self.task_id, self.case_id = accepted.task_id, accepted.case_id
        self._admit_stage()
        ref = self.reference
        self.bridge = await start_current_case_bridge(
            (
                CurrentCaseBinding(
                    tenant_id=ref["scope"]["tenantId"],
                    account_id=ref["scope"]["accountId"],
                    case_id=ref["caseId"],
                    conversation_id=ref["conversationId"],
                    task_id=self.task_id,
                    authority_case_id=self.case_id,
                    token=self.token,
                    reader=self.reader,
                ),
            )
        )
        return int(self.bridge.port)

    async def advance(self) -> dict[str, object]:
        self._admit_stage()
        if self.managed is None or self.control is None or self._advance_started:
            raise ValueError("Explicit one-shot fixture advancement required")
        self._advance_started = True
        self._admit_stage()
        await asyncio.to_thread(fixture.inquire, self.runtime, self.supplier, self.task_id)
        self._admit_stage()
        quote = await self.managed.prepare_quote(
            task_id=self.task_id, expected_revision=0, command_id=str(uuid4())
        )
        self._admit_stage()
        confirmation = Confirmation(quote.quote, True)
        committed = await self.control.commit_confirmation(
            task_id=self.task_id, command_id=str(uuid4()), confirmation=confirmation
        )
        self._admit_stage()
        mutation = await asyncio.to_thread(
            fixture.mutate, self.runtime, self.supplier, self.task_id
        )
        self._admit_stage()
        truth = await asyncio.to_thread(fixture.supplier_truth, self.supplier)
        if truth["applied_calls"] != 1 or mutation["effect_id"] != committed.effect_id:
            raise AssertionError("Independent supplier proof did not match")
        self._admit_stage()
        self.advanced = True
        return {
            "schemaVersion": 1,
            "caseRevision": "0",
            "taskId": self.task_id,
            "authorityCaseId": self.case_id,
            "mutation": mutation,
            "supplier": truth,
        }

    async def close(self, *, deadline: float | None = None) -> None:
        """Drain business I/O, then bridge, reader and marked schema in that order."""
        self.closing_requested = True
        final = deadline if deadline is not None else time.monotonic() + 15
        if type(final) not in (int, float) or not math.isfinite(final):
            raise TimeoutError()
        primary: BaseException | None = None

        async def observe(task: asyncio.Future[Any]) -> None:
            remaining = final - time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            async with asyncio.timeout(remaining):
                await asyncio.shield(task)

        def business_settled() -> bool:
            # Cancellation is not evidence that the real worker/thread settled.
            return all(task.done() and not task.cancelled() for task in self._operations)

        async def resource(name: str, action: Any) -> bool:
            nonlocal primary
            try:
                if final <= time.monotonic():
                    raise TimeoutError()
                task = self._resource_closers.get(name)
                if (
                    task is not None
                    and task.done()
                    and (task.cancelled() or task.exception() is not None)
                ):
                    # A public close may have timed out observing its own actual owner.
                    # Invoke the public close again; never inspect private client state.
                    task = None
                if task is None:
                    task = asyncio.create_task(action(), name="rehydration-p1-close-" + name)
                    task.add_done_callback(
                        lambda done: None if done.cancelled() else done.exception()
                    )
                    self._resource_closers[name] = task
                await observe(task)
                return True
            except BaseException as error:  # noqa: BLE001 - retain the first failure and dependent-tier ownership.
                primary = primary or error
                return False

        if self._operations:
            try:
                await observe(asyncio.gather(*self._operations, return_exceptions=True))
            except BaseException as error:  # noqa: BLE001 - retain actual pending operations; stop bridge admission independently.
                primary = error
        bridge_settled = self.bridge is None or await resource("bridge", self.bridge.close)
        reader_settled = self.reader is None
        if bridge_settled and business_settled() and self.reader is not None:
            reader_settled = await resource("reader", self.reader.close)
        if self.installed:
            if (
                bridge_settled
                and reader_settled
                and business_settled()
                and final > time.monotonic()
            ):

                async def cleanup() -> None:
                    await asyncio.to_thread(fixture.cleanup, self.owner)

                await resource("schema", cleanup)
            else:
                primary = primary or TimeoutError()
        if primary is not None:
            raise primary
