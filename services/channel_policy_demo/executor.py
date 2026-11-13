"""Bounded application orchestration over borrowed public read and job ports.

This module adds no queue, cursor, lease, authority or terminal-result ledger.
A waiter budget never cancels an admitted factory/run/close owner. The caller
closes borrowed discovery/prepared/stored readers only after executor drainage.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
from collections.abc import Coroutine
from dataclasses import dataclass, field
from inspect import getattr_static
from types import MappingProxyType
from typing import Literal, Protocol, TypeVar, cast
from uuid import UUID

from continuity_lab.execution_api import ExecutionObservation
from continuity_lab.work_api import WorkError, WorkPayload, WorkRecord, WorkScope
from delegation_reliability import (
    ChannelPolicyExecutionView,
    ChannelPolicyRequest,
    ChannelPolicyRun,
    ChannelPolicyView,
    channel_policy_key,
    encode_channel_policy_request,
    parse_channel_policy_request,
)
from delegation_reliability.contracts import ContractError, Scope, identifier

from .discovery import (
    DiscoveryError,
    DiscoveryItem,
    DiscoveryPage,
    SourceBindingId,
    encode_discovery_page,
    parse_discovery_page,
)
from .wire import OriginWireError, parse_accept_frame, require_p3_compatible, uuid_value

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
MAX_JOBS = 2
ExecutorCode = Literal[
    "invalid_input",
    "unauthorized",
    "identity_conflict",
    "invalid_stored_state",
    "unavailable",
    "overflow",
    "capacity",
    "closed",
    "deadline_exceeded",
    "request_aborted",
    "cleanup_incomplete",
]
_CODES = frozenset(
    {
        "invalid_input",
        "unauthorized",
        "identity_conflict",
        "invalid_stored_state",
        "unavailable",
        "overflow",
        "capacity",
        "closed",
        "deadline_exceeded",
        "request_aborted",
        "cleanup_incomplete",
    }
)
T = TypeVar("T")


class ExecutorError(RuntimeError):
    """Finite diagnostics never include dependency exceptions or original input."""

    def __init__(self, code: ExecutorCode = "unavailable") -> None:
        self.code: ExecutorCode = code if type(code) is str and code in _CODES else "unavailable"
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class ExecutorBinding:
    profile_id: str
    scope: Scope
    case_id: str
    conversation_id: str
    owner_id: str


class DiscoveryPort(Protocol):
    async def read(self) -> DiscoveryPage: ...


class PreparedReadPort(Protocol):
    async def read(
        self, *, source_binding_id: SourceBindingId, receipt_id: str
    ) -> bytes | None: ...


class StoredWorkPort(Protocol):
    async def get(self, work_id: str) -> ChannelPolicyView: ...


class JobRunnerPort(Protocol):
    @property
    def pending_count(self) -> int: ...

    async def run_once(self, work_id: str, command_id: str) -> ChannelPolicyRun: ...

    async def close(self) -> None: ...


class RunnerFactory(Protocol):
    """A returned runner owns only that job's execution/specialist clients.

    The factory owns partial construction until it returns a valid fresh runner.
    It selects immutable evidence from the winning stored request, never a newer
    application template. A failed factory must retain/close its partial owners.
    """

    async def open(
        self, *, work_id: str, owner_id: str, request: ChannelPolicyRequest
    ) -> JobRunnerPort: ...


@dataclass(frozen=True, slots=True)
class ScanObservation:
    """Process-local as-of counts; started does not mean issued or completed."""

    discovered: int
    unprepared: int
    eligible: int
    started: int
    active: int


@dataclass(slots=True)
class _Scan:
    task: asyncio.Task[ScanObservation] | None = None
    abandoned: bool = False


@dataclass(slots=True)
class _Owner:
    work_id: str
    request: ChannelPolicyRequest = field(repr=False)
    task: asyncio.Task[None] | None = None
    runner: JobRunnerPort | None = field(default=None, repr=False)
    settled: bool = False


def _callable(value: object, name: str) -> None:
    try:
        valid = callable(getattr(value, name, None))
    except Exception:  # noqa: BLE001 - trusted injection boundary, no private diagnostics
        raise ExecutorError("invalid_input") from None
    if not valid:
        raise ExecutorError("invalid_input")


def _budget(value: float) -> float:
    if type(value) not in (int, float) or not 0.001 <= value <= 5 or not math.isfinite(value):
        raise ExecutorError("invalid_input")
    return float(value)


def _binding(value: ExecutorBinding) -> ExecutorBinding:
    try:
        if type(value) is not ExecutorBinding or type(value.scope) is not Scope:
            raise ExecutorError("invalid_input")
        return ExecutorBinding(
            uuid_value(value.profile_id),
            Scope(identifier(value.scope.tenant_id), identifier(value.scope.account_id)),
            identifier(value.case_id),
            identifier(value.conversation_id),
            uuid_value(value.owner_id),
        )
    except (ContractError, OriginWireError, AttributeError, TypeError, ValueError):
        raise ExecutorError("invalid_input") from None


def _spawn(action: Coroutine[object, object, T]) -> asyncio.Task[T]:
    try:
        task = asyncio.create_task(action)
    except BaseException as error:
        # Cleanup also covers allocation cancellation and other control flow.
        action.close()
        if not isinstance(error, Exception):
            raise
        raise ExecutorError("unavailable") from None

    def observed(completed: asyncio.Task[T]) -> None:
        if not completed.cancelled():
            completed.exception()

    task.add_done_callback(observed)
    return task


def _safe_failure(error: ExecutorError) -> ExecutorError:
    """Copy only a finite static code; dependency descriptors/args are untrusted."""
    try:
        value: object = getattr_static(error, "code", None)
    except Exception:  # noqa: BLE001 - static inspection failure has no public diagnostic
        return ExecutorError("unavailable")
    if type(value) is str and value in _CODES:
        return ExecutorError(cast(ExecutorCode, value))
    return ExecutorError("unavailable")


class ChannelPolicyExecutor:
    """One retained scan and at most two actual factory/run/close job owners.

    Calls use a bounded waiter budget. Timeout/cancellation abandons only that
    scan observation; already admitted jobs continue with stable owner/command.
    No further job is admitted after the abandoned scan's next await settles.
    Failed/incomplete public close leaves the owner and its slot retained until a
    subsequent scan/close observes successful actual drainage. No business retry
    occurs within a job owner. Repeated scans reread durable public state.
    Process-local round-robin admission priority prevents completed early inputs
    from starving later work; it resets on restart, skips no source observation,
    and acknowledges or persists no cursor. Fresh malformed runner returns are
    quarantined until public close and an exact zero-pending observation succeed.
    """

    def __init__(
        self,
        *,
        binding: ExecutorBinding,
        discovery: DiscoveryPort,
        prepared: PreparedReadPort,
        stored: StoredWorkPort,
        runners: RunnerFactory,
        timeout_s: float = 5,
        cleanup_timeout_s: float = 1,
    ) -> None:
        copied = _binding(binding)
        for port, method in (
            (discovery, "read"),
            (prepared, "read"),
            (stored, "get"),
            (runners, "open"),
        ):
            _callable(port, method)
        self._timeout, self._cleanup = _budget(timeout_s), _budget(cleanup_timeout_s)
        self._binding = copied
        self._discovery, self._prepared, self._stored, self._runners = (
            discovery,
            prepared,
            stored,
            runners,
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        self._scan: _Scan | None = None
        self._owners: dict[str, _Owner] = {}
        self._close_task: asyncio.Task[None] | None = None
        self._closing = False
        self._priority = 0
        self._counts = {
            "scans_started": 0,
            "scans_succeeded": 0,
            "scans_failed": 0,
            "timed_out_waiters": 0,
            "cancelled_waiters": 0,
            "jobs_started": 0,
            "jobs_succeeded": 0,
            "jobs_failed": 0,
            "owners_settled": 0,
            "cleanup_incomplete": 0,
            "telemetry_failed": 0,
        }

    def _bind(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif loop is not self._loop:
            raise ExecutorError("invalid_input")
        return loop

    @property
    def pending_count(self) -> int:
        """Retained application owners, excluding actual I/O in borrowed readers."""
        return len(self._owners) + int(
            self._scan is not None and self._scan.task is not None and not self._scan.task.done()
        )

    def metrics(self) -> MappingProxyType[str, int]:
        return MappingProxyType(
            {
                **self._counts,
                "active_jobs": len(self._owners),
                "active_scans": self.pending_count - len(self._owners),
                "closing": int(self._closing),
            }
        )

    def _log(
        self, operation: Literal["scan", "job", "close"], code: ExecutorCode | Literal["ok"]
    ) -> None:
        try:
            LOGGER.info("channel_policy_executor", extra={"operation": operation, "code": code})
        except Exception:  # noqa: BLE001 - telemetry cannot alter business or cleanup
            self._counts["telemetry_failed"] += 1

    def _check_scan(self, scan: _Scan) -> None:
        if self._closing:
            raise ExecutorError("closed")
        if scan.abandoned:
            raise ExecutorError("request_aborted")

    def _prune(self) -> None:
        for work_id, owner in tuple(self._owners.items()):
            if owner.settled and owner.task is not None and owner.task.done():
                del self._owners[work_id]
                self._counts["owners_settled"] += 1

    def _borrowed_or_shared(self, runner: JobRunnerPort) -> bool:
        borrowed: tuple[object, ...] = (
            self._discovery,
            self._prepared,
            self._stored,
            self._runners,
        )
        return any(runner is port for port in borrowed) or any(
            owner.runner is runner for owner in self._owners.values()
        )

    def _runner(self, runner: JobRunnerPort) -> JobRunnerPort:
        for method in ("run_once", "close"):
            _callable(runner, method)
        if self._pending(runner) != 0:
            raise ExecutorError("invalid_input")
        return runner

    @staticmethod
    def _pending(runner: JobRunnerPort) -> int:
        try:
            value = runner.pending_count
        except Exception:  # noqa: BLE001 - public owner observation is a finite boundary
            raise ExecutorError("cleanup_incomplete") from None
        if type(value) is not int or not 0 <= value <= 1:
            raise ExecutorError("cleanup_incomplete")
        return value

    def _validate(
        self, item: DiscoveryItem, raw: bytes, value: ChannelPolicyView
    ) -> ChannelPolicyRequest:
        prepared = parse_accept_frame(raw)
        revision = require_p3_compatible(prepared)
        binding = self._binding
        if (
            prepared.scope.tenant_id,
            prepared.scope.account_id,
            prepared.case_id,
            prepared.conversation_id,
        ) != (
            binding.scope.tenant_id,
            binding.scope.account_id,
            binding.case_id,
            binding.conversation_id,
        ):
            raise ExecutorError("unauthorized")
        if (
            prepared.operation_key != item.operation_key
            or prepared.input_receipt_id != item.receipt_id
        ):
            raise ExecutorError("identity_conflict")
        try:
            if (
                type(value) is not ChannelPolicyView
                or type(value.record) is not WorkRecord
                or type(value.record.payload) is not WorkPayload
                or type(value.record.scope) is not WorkScope
            ):
                raise ExecutorError("invalid_stored_state")
            record = value.record
            payload = WorkPayload(
                record.payload.operation, record.payload.body, record.payload.deadline_at_ms
            )
            copied = WorkRecord(
                record.work_id,
                WorkScope(record.scope.tenant_id, record.scope.account_id),
                record.idempotency_key,
                payload,
                record.accepted_at_ms,
                record.cancel_requested,
                record.status,
            )
            request = parse_channel_policy_request(payload.body)
            if (
                copied.work_id != item.external_receipt_id
                or copied.scope != WorkScope(binding.scope.tenant_id, binding.scope.account_id)
                or record.payload.sha256 != hashlib.sha256(payload.body).hexdigest()
                or record.payload.sha256 != payload.sha256
                or payload.deadline_at_ms != request.deadline_at_ms
                or copied.idempotency_key != channel_policy_key(item.operation_key)
                or encode_channel_policy_request(request) != payload.body
                or type(value.request) is not ChannelPolicyRequest
                or encode_channel_policy_request(value.request) != payload.body
            ):
                raise ExecutorError("invalid_stored_state")
        except (ContractError, WorkError, AttributeError, TypeError, ValueError):
            raise ExecutorError("invalid_stored_state") from None
        origin = request.origin
        if (
            request.scope != binding.scope
            or request.case_id != binding.case_id
            or request.conversation_id != binding.conversation_id
        ):
            raise ExecutorError("unauthorized")
        if (
            origin.kind != "p2.prepared_dispatch.v1"
            or origin.profile_id != binding.profile_id
            or origin.operation_key != prepared.operation_key
            or origin.input_receipt_id != prepared.input_receipt_id
            or origin.payload_sha256 != prepared.payload_sha256
            or origin.payload_byte_length != prepared.payload_byte_length
            or request.request_revision != revision
        ):
            raise ExecutorError("identity_conflict")
        return request

    async def _close_owner(self, owner: _Owner) -> None:
        runner = owner.runner
        if runner is None:
            raise ExecutorError("cleanup_incomplete")
        try:
            await runner.close()
            if self._pending(runner):
                raise ExecutorError("cleanup_incomplete")
        except Exception:  # noqa: BLE001 - retain actual owner on every failed close
            self._counts["cleanup_incomplete"] += 1
            self._log("close", "cleanup_incomplete")
            return
        owner.settled = True

    async def _job(self, owner: _Owner) -> None:
        try:
            runner = await self._runners.open(
                work_id=owner.work_id, owner_id=self._binding.owner_id, request=owner.request
            )
        except asyncio.CancelledError:
            # No resource was returned. Failed partial construction remains the
            # factory's responsibility, just as for any other failed open.
            owner.settled = True
            raise
        except Exception:  # noqa: BLE001 - factory owns failed partial construction
            self._counts["jobs_failed"] += 1
            self._log("job", "unavailable")
            owner.settled = True
            return
        if self._borrowed_or_shared(runner):
            self._counts["jobs_failed"] += 1
            self._log("job", "invalid_input")
            owner.settled = True
            return
        # A fresh returned resource remains ours even when validation fails.
        # Quarantine it without invoking; release only after verified drainage.
        owner.runner = runner
        try:
            self._runner(runner)
        except Exception:  # noqa: BLE001 - malformed owners cannot erase actual resources
            self._counts["jobs_failed"] += 1
            self._log("job", "invalid_input")
            await self._close_owner(owner)
            return
        try:
            result = await owner.runner.run_once(owner.work_id, "cp45_" + UUID(owner.work_id).hex)
            if (
                type(result) is not ChannelPolicyRun
                or type(result.view) is not ChannelPolicyExecutionView
                or type(result.invoked) is not bool
                or type(result.view.execution) is not ExecutionObservation
                or result.view.execution.record.work_id != owner.work_id
                or encode_channel_policy_request(result.view.request)
                != encode_channel_policy_request(owner.request)
            ):
                raise ExecutorError("invalid_stored_state")
            self._counts["jobs_succeeded"] += 1
            self._log("job", "ok")
        except Exception:  # noqa: BLE001 - no business retry; actual runner is still owned
            self._counts["jobs_failed"] += 1
            self._log("job", "unavailable")
        finally:
            await self._close_owner(owner)

    def _retry_closes(self) -> None:
        self._prune()
        for owner in self._owners.values():
            if owner.task is not None and owner.task.done() and not owner.settled:
                owner.task = _spawn(self._close_owner(owner))

    async def _scan_once(self, scan: _Scan) -> ScanObservation:
        try:
            page = parse_discovery_page(encode_discovery_page(await self._discovery.read()))
            self._check_scan(scan)
            binding = self._binding
            if (
                page.profile_id != binding.profile_id
                or page.scope.tenant_id != binding.scope.tenant_id
                or page.scope.account_id != binding.scope.account_id
                or page.case_id != binding.case_id
                or page.conversation_id != binding.conversation_id
            ):
                raise ExecutorError("unauthorized")
            if page.overflow or page.next_cursor is not None:
                raise ExecutorError("overflow")
            unprepared = eligible = started = 0
            # Advisory admission priority only: every fresh page remains complete
            # and every entry is reread. This is neither an ACK nor a cursor.
            count = len(page.items)
            offset = self._priority % count if count else 0
            for position in range(count):
                index = (offset + position) % count
                item = page.items[index]
                self._check_scan(scan)
                raw = await self._prepared.read(
                    source_binding_id=item.source_binding_id, receipt_id=item.receipt_id
                )
                self._check_scan(scan)
                if raw is None:
                    unprepared += 1
                    if item.state == "dispatched":
                        raise ExecutorError("invalid_stored_state")
                    continue
                prepared = parse_accept_frame(raw)
                require_p3_compatible(prepared)
                if (
                    prepared.scope.tenant_id,
                    prepared.scope.account_id,
                    prepared.case_id,
                    prepared.conversation_id,
                ) != (
                    binding.scope.tenant_id,
                    binding.scope.account_id,
                    binding.case_id,
                    binding.conversation_id,
                ):
                    raise ExecutorError("unauthorized")
                if (
                    prepared.operation_key != item.operation_key
                    or prepared.input_receipt_id != item.receipt_id
                ):
                    raise ExecutorError("identity_conflict")
                if item.state != "dispatched":
                    continue
                work_id = item.external_receipt_id
                if work_id is None:
                    raise ExecutorError("invalid_stored_state")
                value = await self._stored.get(work_id)
                self._check_scan(scan)
                request = self._validate(item, raw, value)
                eligible += 1
                self._prune()
                if work_id in self._owners or len(self._owners) >= MAX_JOBS:
                    continue
                owner = _Owner(work_id, request)
                self._owners[work_id] = owner
                try:
                    owner.task = _spawn(self._job(owner))
                except BaseException:
                    # Roll back only the unstarted reservation, including control flow.
                    del self._owners[work_id]
                    raise
                self._counts["jobs_started"] += 1
                self._priority = (index + 1) % count
                started += 1
            self._counts["scans_succeeded"] += 1
            self._log("scan", "ok")
            return ScanObservation(
                len(page.items), unprepared, eligible, started, len(self._owners)
            )
        except ExecutorError as error:
            safe = _safe_failure(error)
            self._counts["scans_failed"] += 1
            self._log("scan", safe.code)
            raise safe from None
        except (DiscoveryError, OriginWireError, ContractError):
            self._counts["scans_failed"] += 1
            self._log("scan", "invalid_input")
            raise ExecutorError("invalid_input") from None
        except Exception:  # noqa: BLE001 - outer dependency containment excludes private text
            self._counts["scans_failed"] += 1
            self._log("scan", "unavailable")
            raise ExecutorError("unavailable") from None

    async def scan_once(self) -> ScanObservation:
        loop = self._bind()
        if self._closing:
            raise ExecutorError("closed")
        if self._scan is not None and self._scan.task is not None and not self._scan.task.done():
            raise ExecutorError("capacity")
        self._retry_closes()
        scan = _Scan()
        scan.task = _spawn(self._scan_once(scan))
        self._scan = scan
        self._counts["scans_started"] += 1
        try:
            async with asyncio.timeout_at(loop.time() + self._timeout):
                return await asyncio.shield(scan.task)
        except TimeoutError:
            scan.abandoned = True
            self._counts["timed_out_waiters"] += 1
            raise ExecutorError("deadline_exceeded") from None
        except asyncio.CancelledError:
            scan.abandoned = True
            self._counts["cancelled_waiters"] += 1
            raise

    async def _finish_close(self) -> None:
        if self._scan is not None and self._scan.task is not None:
            await asyncio.gather(self._scan.task, return_exceptions=True)
        self._retry_closes()
        tasks = tuple(owner.task for owner in self._owners.values() if owner.task is not None)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._prune()
        if self._owners:
            raise ExecutorError("cleanup_incomplete")

    async def close(self) -> None:
        loop = self._bind()
        self._closing = True
        if (
            self._close_task is not None
            and self._close_task.done()
            and (self._close_task.cancelled() or self._close_task.exception() is not None)
        ):
            self._close_task = None
        if self._close_task is None:
            try:
                self._close_task = _spawn(self._finish_close())
            except ExecutorError:
                raise ExecutorError("cleanup_incomplete") from None
        try:
            async with asyncio.timeout_at(loop.time() + self._cleanup):
                await asyncio.shield(self._close_task)
        except TimeoutError:
            self._counts["cleanup_incomplete"] += 1
            self._log("close", "cleanup_incomplete")
            raise ExecutorError("cleanup_incomplete") from None
