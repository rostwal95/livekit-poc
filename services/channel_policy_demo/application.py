"""Explicit Python source listeners and durable-discovery executor composition.

Serving imports public product APIs only. Startup/stop do no DDL; the separate
owner setup supplies an existing private profile. No process-memory queue owns
acceptance. The parent starts Node between start_sources and start_executor.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Coroutine
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, Protocol, TypeVar

from continuity_lab.case_control_api import CaseControlIdentity
from continuity_lab.postgres_api import CaseProjection, ManagedCaseClient, open_postgres_client
from continuity_lab.work_api import BearerToken, WorkDirectory, WorkPrincipal, WorkScope
from delegation_reliability import ChannelPolicyCoordinator
from delegation_reliability.case_adapter import CaseBinding, ManagedCaseAuthority
from delegation_reliability.coordinator import CaseAuthorityPort, CaseSnapshot
from delegation_reliability.delivery_contract import DeliveryBinding
from delegation_reliability.http_client import SpecialistEndpoint

from .case_bridge import CurrentCaseBinding, CurrentCaseBridge
from .current_result import CurrentResultObservation
from .current_result_producer import (
    CurrentResultProducer,
    CurrentResultProducerError,
    NativeResultReadPort,
    ProducerBinding,
)
from .discovery import DiscoveryScope
from .executor import (
    ChannelPolicyExecutor,
    DiscoveryPort,
    ExecutorBinding,
    PreparedReadPort,
    ScanObservation,
    StoredWorkPort,
)
from .jobs import ChannelPolicyJobFactory, EvidenceCatalogue
from .operator_contract import (
    CaseObservation,
    OperatorError,
    ProgressObservation,
    now_utc,
    progress_observation,
)
from .origin_http import ChannelOriginHttp
from .origin_router import ChannelOriginRouter, OriginRouterBinding
from .owner_config import OwnerProfile, ProfileError, encode_owner_profile, parse_owner_profile
from .public_clients import (
    PublicClientFactory,
    PublicReceiverConfig,
    PublicSpecialistConfig,
    PublicWorkConfig,
)
from .worker_client import (
    ChannelPolicyWorkerClient,
    CoordinatorWorkerDiscoveryReader,
    CoordinatorWorkerPreparedReader,
    WorkerBinding,
    WorkerCredential,
    WorkerEndpoint,
)

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
T = TypeVar("T")
AppCode = Literal["invalid_input", "unavailable", "capacity", "closed", "cleanup_incomplete"]
Tier = Literal["http", "current", "active", "jobs", "readers", "case"]
SCAN_INTERVAL_S = 0.25
IDLE_SCAN_INTERVAL_S = 1.0
CURRENT_READ_RETRY_DELAYS_S = (0.25, 0.5)


def next_scan_interval(previous: float, observed: object) -> float:
    """Rescan quickly while input is unprepared or jobs start/run; back off when idle."""
    if (
        type(observed) is not ScanObservation
        or observed.unprepared
        or observed.started
        or observed.active
    ):
        return SCAN_INTERVAL_S
    return min(IDLE_SCAN_INTERVAL_S, previous * 2)


class ApplicationError(RuntimeError):
    def __init__(self, code: AppCode = "unavailable") -> None:
        self.code: AppCode = (
            code
            if type(code) is str
            and code in {"invalid_input", "unavailable", "capacity", "closed", "cleanup_incomplete"}
            else "unavailable"
        )
        super().__init__(self.code)


class _Closable(Protocol):
    async def close(self) -> None: ...


@dataclass(slots=True)
class _Owner:
    value: _Closable = field(repr=False)
    tier: Tier
    closed: bool = False
    pending: asyncio.Future[None] | None = field(default=None, repr=False)
    action: asyncio.Task[None] | None = field(default=None, repr=False)


class CurrentResultReadPort(Protocol):
    """Borrowed room-specific view; the application owns its producer's drain."""

    async def read(self) -> CurrentResultObservation: ...


@dataclass(frozen=True, slots=True)
class _ResultDependencies:
    binding: ProducerBinding
    discovery: DiscoveryPort
    prepared: PreparedReadPort
    stored: StoredWorkPort
    jobs: ChannelPolicyJobFactory
    evidence: EvidenceCatalogue


@dataclass(slots=True)
class _Attachment:
    producer: CurrentResultProducer = field(repr=False)
    owner: _Owner = field(repr=False)
    closing: bool = False


class _CurrentResultReader:
    def __init__(self, app: ChannelPolicyApplication, attachment: _Attachment) -> None:
        self._app, self._attachment = app, attachment

    def _check(self) -> None:
        self._app._bind()
        self._app._check()
        if (
            self._app._current is not self._attachment
            or self._attachment.closing
            or self._attachment.owner.closed
        ):
            raise ApplicationError("closed")

    async def read(self) -> CurrentResultObservation:
        delays = iter(CURRENT_READ_RETRY_DELAYS_S)
        while True:
            self._check()
            try:
                result = await self._attachment.producer.read()
            except CurrentResultProducerError as error:
                # Bounded side-effect-free retry: shared one/two-slot source
                # bounds collide briefly while dispatch and scans overlap.
                delay = next(delays, None)
                if error.code != "capacity" or delay is None:
                    raise
                await asyncio.sleep(delay)
                continue
            # End and failed cleanup fence late A observations before another room
            # can attach. A retained old facade never selects the current B owner.
            self._check()
            return result


class _CaseReader:
    """Own one public factory result; its identity comes from the same trusted binding."""

    def __init__(self, managed: ManagedCaseClient, profile: OwnerProfile) -> None:
        self._managed = managed
        self._identity = CaseControlIdentity(
            profile.case.actor_id, profile.case.scope_id, profile.database.case_schema
        )

    @property
    def identity(self) -> CaseControlIdentity:
        return self._identity

    async def get(
        self, *, task_id: str, cursor: str | None = None, limit: int = 1
    ) -> CaseProjection:
        return await self._managed.get(task_id=task_id, cursor=cursor, limit=limit)

    async def close(self) -> None:
        await self._managed.close()


def _task(
    action: Coroutine[object, object, T], *, failure: AppCode = "unavailable"
) -> asyncio.Task[T]:
    try:
        task = asyncio.create_task(action)
    except BaseException as error:
        action.close()
        if isinstance(error, Exception):
            raise ApplicationError(failure) from None
        raise
    task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    return task


def _seconds(value: float) -> float:
    if type(value) not in (int, float) or not 0.02 <= value <= 10 or not math.isfinite(value):
        raise ApplicationError("invalid_input")
    return float(value)


class ChannelPolicyApplication:
    """Own all Python app resources, retaining actual startup and close observers.

    One source-start task, one executor loop and at most two existing job owners.
    The owner profile remains private. There is no provider or environment loader.
    Closing stops scans and HTTP admission, drains dependent work/factories, then
    read clients and the shared public case reader. A timed-out close is retryable.
    """

    def __init__(
        self, profile: OwnerProfile, *, startup_timeout_s: float = 10, cleanup_timeout_s: float = 5
    ) -> None:
        try:
            self._profile = parse_owner_profile(encode_owner_profile(profile))
        except ProfileError:
            raise ApplicationError("invalid_input") from None
        self._startup_timeout = _seconds(startup_timeout_s)
        self._cleanup_timeout = _seconds(cleanup_timeout_s)
        self._owners: list[_Owner] = []
        self._starting: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._scanner: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._sources_ready = False
        self._source_deadline: float | None = None
        self._executor: ChannelPolicyExecutor | None = None
        self._worker: ChannelPolicyWorkerClient | None = None
        self._background = asyncio.Semaphore(1)
        self._case_authority: CaseAuthorityPort | None = None
        self._result_dependencies: _ResultDependencies | None = None
        self._current: _Attachment | None = None
        self._closing = False
        self._closed = False
        self._scans_ok = 0
        self._scans_failed = 0
        self._telemetry_failed = 0

    def _bind(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise ApplicationError("invalid_input")
        return loop

    def _check(self) -> None:
        if self._closing:
            raise ApplicationError("closed")

    def _check_starting(self) -> None:
        self._check()
        if self._source_deadline is None or self._bind().time() >= self._source_deadline:
            raise ApplicationError()

    def _own(self, value: _Closable, tier: Tier) -> _Owner:
        owner = _Owner(value, tier)
        self._owners.append(owner)
        return owner

    async def observe_case(self) -> CaseObservation:
        """Read the fixed public case authority, separately from result freshness.

        The Parent drains its operator HTTP calls before closing this app. The
        shared case client retains actual I/O through observer cancellation.
        """
        self._bind()
        self._check()
        if not self._sources_ready or self._case_authority is None:
            raise ApplicationError()
        try:
            snapshot = await self._case_authority.snapshot(case_id=self._profile.route.case_id)
            self._check()
            if (
                type(snapshot) is not CaseSnapshot
                or (snapshot.scope, snapshot.case_id)
                != (self._profile.route.scope, self._profile.route.case_id)
                or type(snapshot.request_revision) is not int
                or snapshot.request_revision < 0
            ):
                raise ApplicationError()
            return CaseObservation(str(snapshot.request_revision), now_utc())
        except ApplicationError:
            raise
        except Exception:  # noqa: BLE001 - read failures never become an empty successful case
            raise ApplicationError() from None

    async def observe_progress(self) -> ProgressObservation:
        """Count original P2 source/dispatch observations; never execution completion."""
        self._bind()
        self._check()
        if not self._sources_ready or self._worker is None:
            raise ApplicationError()
        try:
            async with self._background:
                page = await self._worker.discovery()
            route = self._profile.route
            if (page.profile_id, page.scope, page.case_id, page.conversation_id) != (
                route.profile_id,
                DiscoveryScope(route.scope.tenant_id, route.scope.account_id),
                route.case_id,
                route.conversation_id,
            ):
                raise ApplicationError()
            observed = progress_observation(page)
            self._check()
            return observed
        except ApplicationError:
            raise
        except OperatorError as error:
            raise ApplicationError(
                "capacity" if error.code == "capacity" else "unavailable"
            ) from None
        except Exception:  # noqa: BLE001 - retained prior UI facts stay explicitly historical
            raise ApplicationError() from None

    def attach_current_result(self, native: NativeResultReadPort) -> CurrentResultReadPort:
        """Attach one immutable room reader, sharing existing discovery/job owners.

        The caller owns the native HTTP view and must keep it alive until
        close_current_result succeeds. This app owns only the producer; the
        returned facade has no close, grant, work-selection or execution method.
        """
        self._bind()
        self._check()
        if not self._sources_ready or self._result_dependencies is None:
            raise ApplicationError()
        if self._current is not None:
            raise ApplicationError("capacity")
        d = self._result_dependencies
        try:
            producer = CurrentResultProducer(
                binding=d.binding,
                discovery=d.discovery,
                prepared=d.prepared,
                stored=d.stored,
                inspections=d.jobs,
                native=native,
                evidence=d.evidence,
            )
        except CurrentResultProducerError as error:
            raise ApplicationError(
                "invalid_input" if error.code == "invalid_input" else "unavailable"
            ) from None
        attachment = _Attachment(producer, self._own(producer, "current"))
        self._current = attachment
        return _CurrentResultReader(self, attachment)

    async def close_current_result(self) -> None:
        """Fence the current facade, retaining its owner until actual drain.

        A timed-out or cancelled waiter cannot free the room slot. Successful
        drain removes this owner's bookkeeping so repeated rooms remain bounded.
        Borrowed native transport, jobs and sources are never closed here.
        """
        loop = self._bind()
        current = self._current
        if current is None:
            return
        current.closing = True
        try:
            async with asyncio.timeout_at(loop.time() + self._cleanup_timeout):
                await self._close_tier("current")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - actual close stays owned on failed observation
            raise ApplicationError("cleanup_incomplete") from None
        if self._current is current:
            self._current = None
            self._owners.remove(current.owner)

    def metrics(self) -> MappingProxyType[str, int]:
        return MappingProxyType(
            {
                "sources_ready": int(self._sources_ready),
                "current_result_attached": int(self._current is not None),
                "current_result_closing": int(self._current is not None and self._current.closing),
                "executor_running": int(self._scanner is not None and not self._scanner.done()),
                "owned_resources": sum(not owner.closed for owner in self._owners),
                "starting": int(self._starting is not None and not self._starting.done()),
                "closing": int(self._closing),
                "closed": int(self._closed),
                "scans_succeeded": self._scans_ok,
                "scans_failed": self._scans_failed,
                "telemetry_failed": self._telemetry_failed,
            }
        )

    def _emit(
        self, operation: Literal["sources", "scan", "close"], code: AppCode | Literal["ok"]
    ) -> None:
        try:
            LOGGER.info(
                "channel_policy_application",
                extra={"event": "channel_policy_application", "operation": operation, "code": code},
            )
        except Exception:  # noqa: BLE001 - exporter failure cannot change application truth
            self._telemetry_failed = min(9_007_199_254_740_991, self._telemetry_failed + 1)

    async def _start_sources(self) -> None:
        self._check_starting()
        p = self._profile
        # This task is retained/shielded. Parent close observes it rather than
        # cancelling the actual thread that can return a fresh client later.
        managed = await asyncio.to_thread(
            open_postgres_client, actor=p.actor(), token=p.case_token(), settings=p.case_settings()
        )
        case = _CaseReader(managed, p)
        self._own(case, "case")
        self._check_starting()
        r = p.route
        authority = ManagedCaseAuthority(
            case,
            scope=r.scope,
            bindings=(CaseBinding(r.case_id, p.case.task_id, p.case.authority_case_id),),
        )
        # Fail if the persisted task/reference/revision is unavailable; serving
        # must never repair initial revision zero or silently create a new task.
        await authority.snapshot(case_id=r.case_id)
        self._case_authority = authority
        self._check_starting()
        token = BearerToken(p.credentials.p1_work_token)
        directory = WorkDirectory(
            {
                token: WorkPrincipal(
                    "channel_policy_app", WorkScope(r.scope.tenant_id, r.scope.account_id)
                )
            }
        )
        clients = PublicClientFactory(
            work=PublicWorkConfig(p.work_settings(), directory, token, r.scope),
            specialist=PublicSpecialistConfig(
                SpecialistEndpoint(p.ports.specialist), "Bearer " + p.credentials.specialist_bearer
            ),
            receiver=PublicReceiverConfig(
                p.ports.receiver,
                p.credentials.result_publisher_token,
                r.receiver_id,
                WorkScope(r.scope.tenant_id, r.scope.account_id),
                r.recipient_id,
            ),
            case_authority=authority,
        )
        self._own(clients, "active")
        worker = ChannelPolicyWorkerClient(
            WorkerEndpoint("127.0.0.1", p.ports.read),
            WorkerCredential(p.credentials.worker_bearer),
            WorkerBinding(
                r.profile_id,
                DiscoveryScope(r.scope.tenant_id, r.scope.account_id),
                r.case_id,
                r.conversation_id,
            ),
        )
        self._worker = worker
        self._own(worker, "readers")
        lane = self._background
        discovery, prepared = (
            CoordinatorWorkerDiscoveryReader(worker, lane),
            CoordinatorWorkerPreparedReader(worker, lane),
        )
        router = ChannelOriginRouter(
            binding=OriginRouterBinding(r.profile_id, r.scope, r.case_id, r.conversation_id),
            discovery=CoordinatorWorkerDiscoveryReader(worker),
            prepared=CoordinatorWorkerPreparedReader(worker),
            templates=p.templates(),
            coordinators=clients,
            deadline_window_ms=p.deadline_window_ms,
        )
        self._own(router, "active")
        stored: ChannelPolicyCoordinator = await clients.open()
        self._own(stored, "readers")
        self._check_starting()
        jobs = ChannelPolicyJobFactory(
            scope=r.scope,
            case_authority=authority,
            bindings=(DeliveryBinding(r.case_id, r.conversation_id, r.recipient_id),),
            catalogue=p.evidence(),
            clients=clients,
        )
        self._own(jobs, "jobs")
        executor = ChannelPolicyExecutor(
            binding=ExecutorBinding(
                r.profile_id, r.scope, r.case_id, r.conversation_id, p.app_owner_id
            ),
            discovery=discovery,
            prepared=prepared,
            stored=stored,
            runners=jobs,
        )
        self._executor = executor
        self._own(executor, "active")
        case_http = CurrentCaseBridge(
            (
                CurrentCaseBinding(
                    r.scope.tenant_id,
                    r.scope.account_id,
                    r.case_id,
                    r.conversation_id,
                    p.case.task_id,
                    p.case.authority_case_id,
                    p.credentials.case_bearer,
                    case,
                ),
            )
        )
        self._own(case_http, "http")
        native_http = ChannelOriginHttp(
            router.native, operation_bearer=p.credentials.native_origin_bearer
        )
        self._own(native_http, "http")
        sms_http = ChannelOriginHttp(router.sms, operation_bearer=p.credentials.sms_origin_bearer)
        self._own(sms_http, "http")
        self._check_starting()
        await case_http.start(port=p.ports.case)
        self._check_starting()
        await native_http.start(p.ports.native_origin)
        self._check_starting()
        await sms_http.start(p.ports.sms_origin)
        self._check_starting()
        self._result_dependencies = _ResultDependencies(
            ProducerBinding(
                r.profile_id,
                r.scope,
                r.case_id,
                r.conversation_id,
                p.app_owner_id,
                r.receiver_id,
                r.recipient_id,
            ),
            discovery,
            prepared,
            stored,
            jobs,
            p.evidence(),
        )
        self._sources_ready = True
        self._emit("sources", "ok")

    async def start_sources(self) -> None:
        loop = self._bind()
        self._check()
        if self._sources_ready:
            return
        if self._starting is None:
            self._source_deadline = loop.time() + self._startup_timeout
            self._starting = _task(self._start_sources())
        assert self._source_deadline is not None
        try:
            async with asyncio.timeout_at(self._source_deadline):
                await asyncio.shield(self._starting)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - public startup boundary never exposes dependency text
            self._emit("sources", "unavailable")
            raise ApplicationError() from None

    async def _scan_loop(self) -> None:
        assert self._executor is not None
        interval = SCAN_INTERVAL_S
        while not self._stop.is_set():
            observed: object = None
            try:
                observed = await self._executor.scan_once()
                self._scans_ok = min(9_007_199_254_740_991, self._scans_ok + 1)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - independent scans preserve durable work on failures
                self._scans_failed = min(9_007_199_254_740_991, self._scans_failed + 1)
                self._emit("scan", "unavailable")
            interval = next_scan_interval(interval, observed)
            if not self._stop.is_set():
                try:
                    async with asyncio.timeout(interval):
                        await self._stop.wait()
                except TimeoutError:
                    pass

    async def start_executor(self) -> None:
        self._bind()
        self._check()
        if not self._sources_ready or self._worker is None:
            raise ApplicationError()
        if self._scanner is not None:
            if self._scanner.done():
                raise ApplicationError()
            return
        # Node read/result hosts must be up first. This explicit readiness read
        # creates no plan/claim/work; a failed read cannot start a scan loop.
        try:
            async with self._background:
                await self._worker.discovery()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - readiness boundary hides transport dependency text
            raise ApplicationError() from None
        self._check()
        if self._scanner is None:
            self._scanner = _task(self._scan_loop())

    def _start_owner_close(self, owner: _Owner) -> asyncio.Future[None]:
        if owner.pending is not None and not (
            owner.pending.done()
            and (owner.pending.cancelled() or owner.pending.exception() is not None)
        ):
            return owner.pending
        # Publish before scheduling: an eager dependency callback can reenter
        # application/room close without starting a second close of this owner.
        publication = self._bind().create_future()
        publication.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        owner.pending = publication

        async def close() -> None:
            await owner.value.close()
            owner.closed = True

        try:
            action = _task(close(), failure="cleanup_incomplete")
        except BaseException:
            publication.set_exception(ApplicationError("cleanup_incomplete"))
            raise
        owner.action = action

        def settle(done: asyncio.Task[None]) -> None:
            if done.cancelled():
                publication.cancel()
            elif done.exception() is not None:
                publication.set_exception(ApplicationError("cleanup_incomplete"))
            else:
                publication.set_result(None)

        action.add_done_callback(settle)
        return publication

    async def _close_tier(self, tier: Tier) -> None:
        owners = [owner for owner in self._owners if owner.tier == tier and not owner.closed]
        for owner in owners:
            self._start_owner_close(owner)
        results = await asyncio.gather(
            *(asyncio.shield(owner.pending) for owner in owners if owner.pending is not None),
            return_exceptions=True,
        )
        if any(isinstance(result, BaseException) for result in results):
            raise ApplicationError("cleanup_incomplete")

    async def _finish_close(self) -> None:
        if self._starting is not None:
            await asyncio.gather(asyncio.shield(self._starting), return_exceptions=True)
        await self._close_tier("http")
        await self.close_current_result()
        # Startup-only facade, origin router and executor close concurrently:
        # an unreceived startup close can otherwise block the dependent owner.
        await self._close_tier("active")
        if self._scanner is not None:
            await asyncio.gather(asyncio.shield(self._scanner), return_exceptions=True)
        await self._close_tier("jobs")
        await self._close_tier("readers")
        await self._close_tier("case")
        self._closed = True
        self._sources_ready = False
        self._emit("close", "ok")

    async def close(self) -> None:
        loop = self._bind()
        self._closing = True
        self._stop.set()
        if self._closed:
            return
        if (
            self._close_task is not None
            and self._close_task.done()
            and (self._close_task.cancelled() or self._close_task.exception() is not None)
        ):
            self._close_task = None
        if self._close_task is None:
            self._close_task = _task(self._finish_close(), failure="cleanup_incomplete")
        try:
            async with asyncio.timeout_at(loop.time() + self._cleanup_timeout):
                await asyncio.shield(self._close_task)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - retained close observer has a finite application code
            raise ApplicationError("cleanup_incomplete") from None
