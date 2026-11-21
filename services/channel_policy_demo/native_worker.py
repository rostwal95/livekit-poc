"""One explicitly launched P2 native session, with no database/provider authority.

The prepare listener is available before connecting/waiting for the browser. End
closes the listener and SDK runtime together, then their actual startup observers,
model wrapper, models/read clients and RTC room. Waiter loss never frees owners.
Imports and construction perform no SDK loading, asset reads or network I/O.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import math
import signal
import sys
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypeVar

from .native_models import load_scripted_models
from .native_prepare_http import NativePrepareEndpoint, NativePrepareHttp
from .native_worker_config import (
    InferenceMode,
    NativeWorkerConfig,
    encode_native_worker_config,
    load_native_worker_config,
    parse_native_worker_config,
)

if TYPE_CHECKING:
    from livekit import rtc
    from livekit.agents.voice import CloseEvent

    from channel_continuity.native import NativeRuntime


LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
WorkerCode = Literal["invalid_configuration", "unavailable", "closed", "cleanup_incomplete"]
Stage = Literal[
    "prepare_ready", "room_connected", "waiting_participant", "ready", "session_closed", "closed"
]
SdkCloseReason = Literal[
    "error", "job_shutdown", "participant_disconnected", "user_initiated", "task_completed"
]
Tier = Literal["front", "wrapper", "dependencies", "room"]
T = TypeVar("T")


class NativeWorkerError(RuntimeError):
    def __init__(self, code: WorkerCode = "unavailable") -> None:
        self.code = (
            code
            if type(code) is str
            and code in {"invalid_configuration", "unavailable", "closed", "cleanup_incomplete"}
            else "unavailable"
        )
        super().__init__(self.code)


class _Close(Protocol):
    async def __call__(self) -> None: ...


@dataclass(slots=True)
class _Owner:
    close: _Close = field(repr=False)
    tier: Tier
    closed: bool = False
    pending: asyncio.Task[None] | None = field(default=None, repr=False)


def _task(action: Coroutine[Any, Any, T]) -> asyncio.Task[T]:
    try:
        # Python 3.14 is the frozen baseline. Publish task references before any
        # dependency can run, including when the loop has an eager task factory.
        result = asyncio.create_task(action, eager_start=False)
    except BaseException as error:
        action.close()
        if isinstance(error, Exception):
            raise NativeWorkerError() from None
        raise
    result.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    return result


async def _wait_participant(room: rtc.Room, identity: str) -> None:
    """Observe the bound participant; never grant a different identity readiness."""
    loop = asyncio.get_running_loop()
    present: asyncio.Future[None] = loop.create_future()

    def observed(participant: rtc.RemoteParticipant) -> None:
        if participant.identity == identity and not present.done():
            present.set_result(None)

    room.on("participant_connected", observed)
    try:
        for participant in tuple(room.remote_participants.values()):
            observed(participant)
        async with asyncio.timeout(60):
            await present
    finally:
        room.off("participant_connected", observed)


class NativeWorker:
    """Own a single genuine Runtime/AgentSession and its independent transports.

    start_prepare and connect_room are deliberately separate. Parent publishes
    the immutable grant, starts prepare and attaches it to Node, then supplies a
    browser RTC token while connect_room waits for that participant. No parent,
    publisher, room-view, discovery, PostgreSQL or provider key is accepted here.
    """

    def __init__(
        self,
        config: NativeWorkerConfig,
        *,
        cleanup_timeout_s: float = 5,
        startup_timeout_s: float = 10,
        observer: Callable[[Stage], None] | None = None,
    ) -> None:
        try:
            self._config = parse_native_worker_config(encode_native_worker_config(config))
            if (
                type(cleanup_timeout_s) not in (int, float)
                or not 0.02 <= cleanup_timeout_s <= 10
                or not math.isfinite(cleanup_timeout_s)
                or type(startup_timeout_s) not in (int, float)
                or not 0.02 <= startup_timeout_s <= 10
                or not math.isfinite(startup_timeout_s)
                or observer is not None
                and (
                    not callable(observer)
                    or inspect.iscoroutinefunction(observer)
                    or inspect.isasyncgenfunction(observer)
                    or inspect.iscoroutinefunction(
                        inspect.getattr_static(type(observer), "__call__", None)
                    )
                    or inspect.isasyncgenfunction(
                        inspect.getattr_static(type(observer), "__call__", None)
                    )
                )
            ):
                raise ValueError
        except Exception:  # noqa: BLE001 - secret configuration never reaches diagnostics
            raise NativeWorkerError("invalid_configuration") from None
        self._cleanup = float(cleanup_timeout_s)
        self._startup = float(startup_timeout_s)
        self._startup_deadline: float | None = None
        self._observer = observer
        self._loop: asyncio.AbstractEventLoop | None = None
        self._owners: list[_Owner] = []
        self._opening: asyncio.Task[NativePrepareEndpoint] | None = None
        self._conversation: asyncio.Task[None] | None = None
        self._connect: asyncio.Task[None] | None = None
        self._sdk_start: asyncio.Task[None] | None = None
        self._sdk_monitor: asyncio.Task[None] | None = None
        self._session_closed = asyncio.Event()
        self._session_close_reason: SdkCloseReason | None = None
        self._sdk_close_callback = self._session_closed_observed
        self._close_task: asyncio.Task[None] | None = None
        self._runtime: NativeRuntime | None = None
        self._host: NativePrepareHttp | None = None
        self._room: rtc.Room | None = None
        self._closing = self._closed = self._ready = False
        self._telemetry_failed = 0

    @property
    def session_closed(self) -> bool:
        return self._session_closed.is_set()

    @property
    def session_close_reason(self) -> SdkCloseReason | None:
        return self._session_close_reason

    async def wait_session_closed(self) -> None:
        # This observes the public SDK event, not complete worker/RoomIO drain.
        await self._session_closed.wait()

    def _session_closed_observed(self, event: CloseEvent) -> None:
        from livekit.agents.voice import CloseEvent, CloseReason

        self._ready = False
        self._closing = True
        if self._session_closed.is_set():
            return
        if type(event) is CloseEvent and type(event.reason) is CloseReason:
            self._session_close_reason = event.reason.value
        self._session_closed.set()
        self._emit("session_closed")

    async def _watch_session_closed(self) -> None:
        await self._session_closed.wait()
        self._begin_close()

    def _begin_close(self) -> None:
        self._closing = True
        self._ready = False
        if self._closed:
            return
        if (
            self._close_task is None
            or self._close_task.done()
            and (self._close_task.cancelled() or self._close_task.exception() is not None)
        ):
            try:
                self._close_task = _task(self._finish_close())
            except Exception:  # noqa: BLE001 - actual owners survive failed task allocation
                raise NativeWorkerError("cleanup_incomplete") from None

    def _bind(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise NativeWorkerError("invalid_configuration")
        return loop

    def _check(self) -> None:
        if self._closing:
            raise NativeWorkerError("closed")

    def _check_starting(self) -> None:
        self._check()
        if self._startup_deadline is None or self._bind().time() >= self._startup_deadline:
            raise NativeWorkerError()

    def _own(self, close: _Close, tier: Tier) -> None:
        self._owners.append(_Owner(close, tier))

    def _emit(self, stage: Stage) -> None:
        try:
            LOGGER.info(
                "channel_policy_native_worker",
                extra={"stage": stage, "mode": self._config.inference_mode},
            )
            if self._observer is not None:
                self._observer(stage)
        except Exception:  # noqa: BLE001 - observations never grant or block startup
            self._telemetry_failed = min(9007199254740991, self._telemetry_failed + 1)

    def metrics(self) -> MappingProxyType[str, int]:
        return MappingProxyType(
            {
                "ready": int(self._ready and not self._closing),
                "closing": int(self._closing),
                "closed": int(self._closed),
                "owned_resources": sum(not owner.closed for owner in self._owners),
                "startup_active": int(self._opening is not None and not self._opening.done()),
                "conversation_active": int(
                    self._conversation is not None and not self._conversation.done()
                ),
                "connect_active": int(self._connect is not None and not self._connect.done()),
                "sdk_start_active": int(self._sdk_start is not None and not self._sdk_start.done()),
                "sdk_session_closed": int(self._session_closed.is_set()),
                "sdk_monitor_active": int(
                    self._sdk_monitor is not None and not self._sdk_monitor.done()
                ),
                "telemetry_failed": self._telemetry_failed,
            }
        )

    async def _open_prepare(self) -> NativePrepareEndpoint:
        from channel_continuity.native import NativeHttpIntake, NativeRuntime
        from channel_continuity.native_rehydration import (
            NativeContextHttpClient,
            NativeRehydrationProfile,
        )

        from .current_result_context import with_current_result
        from .worker_current_result import WorkerCurrentResultClient

        self._check_starting()
        c = self._config
        models = await load_scripted_models(c.model_profile)
        self._own(models.aclose, "dependencies")
        self._check_starting()
        current = WorkerCurrentResultClient(
            c.current_endpoint, c.worker_binding, c.current_credential
        )
        self._own(current.close, "dependencies")
        model = with_current_result(models.llm, current)
        self._own(model.aclose, "wrapper")
        intake = NativeHttpIntake(c.native_endpoint, c.native_credential, c.binding)
        self._own(intake.aclose, "dependencies")
        context = NativeContextHttpClient(c.rehydration_endpoint, c.native_credential, c.binding)
        self._own(context.aclose, "dependencies")
        runtime = NativeRuntime(
            c.binding,
            intake,
            stt=models.stt,
            llm=model,
            tts=models.tts,
            rehydration=NativeRehydrationProfile(context),
            inference_mode=c.inference_mode,
        )
        self._runtime = runtime
        self._own(runtime.aclose, "front")
        runtime.session.on("close", self._sdk_close_callback)
        self._sdk_monitor = _task(self._watch_session_closed())
        host = NativePrepareHttp(runtime, prepare_bearer=c.prepare_bearer)
        self._host = host
        self._own(host.close, "front")
        self._check_starting()
        endpoint = await host.start(port=c.prepare_port)
        self._check_starting()
        self._emit("prepare_ready")
        return endpoint

    async def start_prepare(self) -> NativePrepareEndpoint:
        self._bind()
        self._check()
        if self._opening is None:
            self._startup_deadline = self._bind().time() + self._startup
            self._opening = _task(self._open_prepare())
        assert self._startup_deadline is not None
        try:
            async with asyncio.timeout_at(self._startup_deadline):
                return await asyncio.shield(self._opening)
        except asyncio.CancelledError:
            raise
        except NativeWorkerError:
            raise
        except Exception:  # noqa: BLE001 - no model/HTTP diagnostic is exposed
            raise NativeWorkerError() from None

    async def _open_room(self) -> None:
        from livekit import rtc

        if self._runtime is None:
            raise NativeWorkerError()
        self._check()
        c = self._config
        room = rtc.Room()
        self._room = room
        self._own(room.disconnect, "room")
        # FFI connect cannot be abandoned: disconnect returns early before a
        # connection finishes. Retain its actual task and disconnect AFTER it
        # settles, including when End cancels the conversational waiter.
        self._connect = _task(
            room.connect(c.livekit_url, c.livekit_token, rtc.RoomOptions(connect_timeout=10))
        )
        await asyncio.shield(self._connect)
        self._check()
        self._emit("room_connected")
        self._emit("waiting_participant")
        await _wait_participant(room, c.binding.participant_id)
        self._check()
        self._sdk_start = _task(self._runtime.start(room))
        await asyncio.shield(self._sdk_start)
        self._check()
        self._ready = True
        self._emit("ready")

    async def connect_room(self) -> None:
        self._bind()
        self._check()
        if (
            self._opening is None
            or not self._opening.done()
            or self._opening.cancelled()
            or self._opening.exception() is not None
        ):
            raise NativeWorkerError()
        if self._conversation is None:
            self._conversation = _task(self._open_room())
        try:
            await asyncio.shield(self._conversation)
        except asyncio.CancelledError:
            raise
        except NativeWorkerError:
            raise
        except Exception:  # noqa: BLE001 - RTC URLs/tokens and SDK errors remain private
            raise NativeWorkerError() from None

    async def _close_tier(self, tier: Tier) -> None:
        owners = [owner for owner in self._owners if owner.tier == tier and not owner.closed]
        for owner in owners:
            if (
                owner.pending is None
                or owner.pending.done()
                and (owner.pending.cancelled() or owner.pending.exception() is not None)
            ):

                async def close(current: _Owner = owner) -> None:
                    await current.close()
                    current.closed = True

                owner.pending = _task(close())
        outcomes = await asyncio.gather(
            *(asyncio.shield(owner.pending) for owner in owners if owner.pending is not None),
            return_exceptions=True,
        )
        if any(isinstance(outcome, BaseException) for outcome in outcomes):
            raise NativeWorkerError("cleanup_incomplete")

    async def _finish_close(self) -> None:
        if self._sdk_monitor is not None and not self._sdk_monitor.done():
            self._sdk_monitor.cancel()
        if self._sdk_monitor is not None:
            await asyncio.gather(asyncio.shield(self._sdk_monitor), return_exceptions=True)
        if self._opening is not None:
            await asyncio.gather(asyncio.shield(self._opening), return_exceptions=True)
        if self._conversation is not None and not self._conversation.done():
            self._conversation.cancel()
        if self._conversation is not None:
            await asyncio.gather(asyncio.shield(self._conversation), return_exceptions=True)
        # Host prepare may be waiting on SDK work. Both owners must receive End
        # before either is awaited; closing just the host would create a cycle.
        await self._close_tier("front")
        if self._runtime is not None:
            self._runtime.session.off("close", self._sdk_close_callback)
        if self._sdk_start is not None:
            await asyncio.gather(asyncio.shield(self._sdk_start), return_exceptions=True)
        await self._close_tier("wrapper")
        await self._close_tier("dependencies")
        if self._connect is not None:
            await asyncio.gather(asyncio.shield(self._connect), return_exceptions=True)
        await self._close_tier("room")
        self._closed = True
        self._emit("closed")

    async def close(self) -> None:
        loop = self._bind()
        self._begin_close()
        if self._closed:
            return
        assert self._close_task is not None
        try:
            async with asyncio.timeout_at(loop.time() + self._cleanup):
                await asyncio.shield(self._close_task)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - actual cleanup remains retained for public retry
            raise NativeWorkerError("cleanup_incomplete") from None


def _write_state(
    state: str,
    *,
    code: WorkerCode | None = None,
    reason: SdkCloseReason | None = None,
    mode: InferenceMode = "scripted",
) -> None:
    """Finite process protocol; no tokens, paths, input or SDK exception text."""
    value: dict[str, object] = {
        "schemaVersion": 1,
        "component": "channel_policy_native_worker",
        "mode": mode,
        "state": state,
    }
    if code is not None:
        value["code"] = code
    if state == "session_closed":
        value["reason"] = reason
    print(json.dumps(value, separators=(",", ":")), flush=True)


async def _serve(config: NativeWorkerConfig) -> int:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    mode = config.inference_mode

    def observed(stage: Stage) -> None:
        _write_state(
            stage,
            reason=worker.session_close_reason if stage == "session_closed" else None,
            mode=mode,
        )

    worker = NativeWorker(config, observer=observed)
    expiry: asyncio.TimerHandle | None = None
    installed: list[signal.Signals] = []

    async def run() -> None:
        await worker.start_prepare()
        await worker.connect_room()
        await stop.wait()

    running: asyncio.Task[None] | None = None
    stopping: asyncio.Task[bool] | None = None
    sdk_closed: asyncio.Task[None] | None = None
    failed = False
    try:
        expiry = loop.call_later(180, stop.set)
        for name in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(name, stop.set)
            installed.append(name)
        running = _task(run())
        stopping = _task(stop.wait())
        sdk_closed = _task(worker.wait_session_closed())
        done, _ = await asyncio.wait(
            (running, stopping, sdk_closed), return_when=asyncio.FIRST_COMPLETED
        )
        if worker.session_closed:
            if worker.session_close_reason in {None, "error"}:
                failed = True
                _write_state("failed", code="unavailable", mode=mode)
        elif running in done:
            await running
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - finite process outcome; cleanup still runs
        failed = True
        _write_state("failed", code="unavailable", mode=mode)
    finally:
        if sdk_closed is not None:
            sdk_closed.cancel()
            await asyncio.gather(sdk_closed, return_exceptions=True)
        if stopping is not None:
            stopping.cancel()
            await asyncio.gather(stopping, return_exceptions=True)
        try:
            # Reobserve the SAME public cleanup; this is not a business retry.
            async with asyncio.timeout(15):
                for attempt in range(3):
                    try:
                        await worker.close()
                        break
                    except NativeWorkerError as error:
                        if error.code != "cleanup_incomplete" or attempt == 2:
                            raise
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - unresolved owners cannot report a clean stop
            failed = True
            _write_state("failed", code="cleanup_incomplete", mode=mode)
        if running is not None:
            if not running.done():
                running.cancel()
            await asyncio.gather(running, return_exceptions=True)
        if expiry is not None:
            expiry.cancel()
        for name in installed:
            loop.remove_signal_handler(name)
    return 2 if failed else 0


def main(argv: list[str] | None = None) -> int:
    values = sys.argv[1:] if argv is None else argv
    if values == ["--plan"]:
        print(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "mode": "scripted",
                    "component": "channel_policy_native_worker",
                    "startup": [
                        "prepare_listener",
                        "rtc_connect",
                        "bound_participant",
                        "sdk_ready",
                    ],
                    "nativeSessions": 1,
                    "prepareDeadlineMs": 4000,
                    "nativeRuntimeTimerMs": 180000,
                    "workerStopTimerMs": 180000,
                    "providerKeys": False,
                },
                separators=(",", ":"),
            )
        )
        return 0
    if len(values) != 2 or values[0] != "--config":
        _write_state("failed", code="invalid_configuration")
        return 2
    mode: InferenceMode = "scripted"
    try:
        config = load_native_worker_config(Path(values[1]))
        mode = config.inference_mode
        return asyncio.run(_serve(config))
    except KeyboardInterrupt:
        return 130
    except Exception:  # noqa: BLE001 - no config/path/SDK diagnostic is printed
        _write_state("failed", code="unavailable", mode=mode)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
