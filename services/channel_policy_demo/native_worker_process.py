"""Owned real NativeWorker process and its bounded finite stdout observations.

The actual command is fixed and keeps the original virtualenv interpreter path.
Only a private config path and role BASE environment reach the child. No shell,
provider/PG/admin/publisher/view environment or cwd/PYTHONPATH fallback is used.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import stat
from collections.abc import Coroutine, Mapping
from dataclasses import dataclass
from pathlib import Path, PosixPath
from typing import Any, Literal, TypeVar, cast

from .native_room_state import NativeRoomError

STDOUT_BYTES = 65536
STDERR_BYTES = 262144
FRAME_BYTES = 1024
_BASE_KEYS = frozenset({"PATH", "LANG", "CI", "NO_COLOR", "__CF_USER_TEXT_ENCODING"})
_ALLOWED = frozenset(
    {
        "prepare_ready",
        "room_connected",
        "waiting_participant",
        "ready",
        "session_closed",
        "closed",
        "failed",
    }
)
_T = TypeVar("_T")
WorkerStage = Literal[
    "not_started",
    "starting",
    "prepare_ready",
    "room_connected",
    "waiting_participant",
    "ready",
    "session_closed",
    "closed",
    "failed",
]


@dataclass(frozen=True, slots=True)
class WorkerProcessStatus:
    stage: WorkerStage
    running: bool
    reaped: bool
    returncode: int | None
    prepare_ready: bool
    sdk_ready: bool
    protocol_failed: bool
    spawned: bool = False


def _spawn(operation: Coroutine[Any, Any, _T], *, cleanup: bool = False) -> asyncio.Task[_T]:
    try:
        task = asyncio.create_task(operation, eager_start=False)
    except BaseException as error:
        operation.close()
        if isinstance(error, Exception):
            raise NativeRoomError("cleanup_incomplete" if cleanup else "unavailable") from None
        raise
    task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    return task


def _base(values: Mapping[str, str]) -> dict[str, str]:
    try:
        if (
            not isinstance(values, Mapping)
            or len(values) > 5
            or set(values) - _BASE_KEYS
            or not {"PATH", "LANG"} <= set(values)
        ):
            raise ValueError
        copied = {}
        for name, value in values.items():
            if (
                type(name) is not str
                or type(value) is not str
                or not 0 < len(value.encode("utf-8", "strict")) <= 4096
                or "\0" in value
            ):
                raise ValueError
            copied[name] = value
        return copied
    except Exception:  # noqa: BLE001 - finite process boundary; preserve actual child and observer ownership
        raise NativeRoomError("invalid_input") from None


class NativeWorkerProcess:
    """One retained spawn, two bounded readers, one actual wait and one stop owner.

    stop sends one SIGTERM to the exact live process, then observes its real exit
    and all pipe owners. It does not silently force-kill an unresolved child.
    A caller timeout/cancellation never drops a late-returned actual process.
    """

    def __init__(
        self,
        python_executable: Path,
        config_path: Path,
        base_environment: Mapping[str, str],
        *,
        prepare_timeout_s: float = 10,
        cleanup_timeout_s: float = 15,
    ) -> None:
        if (
            type(python_executable) is not PosixPath
            or not python_executable.is_absolute()
            or type(config_path) is not PosixPath
            or not config_path.is_absolute()
        ):
            raise NativeRoomError("invalid_input")
        # Deliberately retain the original .venv/bin/python invocation. Resolving
        # its symlink for execution would lose pyvenv.cfg and installed packages.
        self._python, self._config = python_executable, config_path
        self._environment = _base(base_environment)
        for value, maximum in ((prepare_timeout_s, 15), (cleanup_timeout_s, 15)):
            if type(value) not in (int, float) or not 0.02 <= value <= maximum:
                raise NativeRoomError("invalid_input")
        self._prepare_timeout, self._cleanup = float(prepare_timeout_s), float(cleanup_timeout_s)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._spawning: asyncio.Task[asyncio.subprocess.Process] | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._stdout: asyncio.Task[None] | None = None
        self._stderr: asyncio.Task[None] | None = None
        self._waiting: asyncio.Task[int] | None = None
        self._stopping: asyncio.Task[None] | None = None
        self._prepare = asyncio.Event()
        self._terminal = asyncio.Event()
        self._seen_prepare = False
        self._ready = asyncio.Event()
        self._stage: WorkerStage = "not_started"
        self._progress = 0
        self._protocol_failed = False
        self._closing = False
        self._signal_sent = False
        self._reaped = False
        self._stdout_bytes = self._stderr_bytes = 0
        self._stdout_frames = 0

    def _bind(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        if self._loop is not None and self._loop is not loop:
            raise NativeRoomError("invalid_input")
        self._loop = loop
        return loop

    @property
    def pending_count(self) -> int:
        process_live = self._process is not None and (
            not self._reaped or self._process.returncode is None
        )
        return int(
            process_live
            or any(
                task is not None and not task.done()
                for task in (
                    self._spawning,
                    self._stdout,
                    self._stderr,
                    self._waiting,
                    self._stopping,
                )
            )
        )

    def status(self) -> WorkerProcessStatus:
        code = self._process.returncode if self._process else None
        live = self._process is not None and code is None
        return WorkerProcessStatus(
            self._stage,
            live,
            self._reaped,
            code,
            self._seen_prepare,
            self._ready.is_set() and live and not self._closing and not self._protocol_failed,
            self._protocol_failed,
            self._process is not None,
        )

    async def _spawn_actual(self) -> asyncio.subprocess.Process:
        # Trusted startup verifies paths off the conversational loop; it never
        # substitutes the resolved system interpreter or inherits environment.
        info = await asyncio.to_thread(self._python.stat)
        if not stat.S_ISREG(info.st_mode) or not info.st_mode & 0o111:
            raise NativeRoomError("invalid_input")
        if self._closing:
            raise NativeRoomError("closed")
        process = await asyncio.create_subprocess_exec(
            str(self._python),
            "-I",
            "-B",
            "-m",
            "services.channel_policy_demo.native_worker",
            "--config",
            str(self._config),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=dict(self._environment),
            cwd=str(self._config.parent),
            start_new_session=True,
            limit=FRAME_BYTES + 1,
        )
        # Actual result is adopted before the next await, even if the observer
        # stopped while create_subprocess_exec was opening the process.
        self._process = process
        self._observe_process(process)
        return process

    def _observe_process(self, process: asyncio.subprocess.Process) -> None:
        # Each observer is registered independently. If one task allocation
        # fails, successfully created owners remain reachable and stop can
        # construct the missing pipe/wait observers before waiting for exit.
        failed = False
        if self._waiting is None:
            try:
                self._waiting = _spawn(self._wait_actual(process))
            except Exception:  # noqa: BLE001 - finite process boundary; preserve actual child and observer ownership
                failed = True
        if process.stdout is None or process.stderr is None:
            raise NativeRoomError("cleanup_incomplete")
        if self._stdout is None:
            try:
                self._stdout = _spawn(self._read_stdout(process.stdout))
            except Exception:  # noqa: BLE001 - finite process boundary; preserve actual child and observer ownership
                failed = True
        if self._stderr is None:
            try:
                self._stderr = _spawn(self._read_stderr(process.stderr))
            except Exception:  # noqa: BLE001 - finite process boundary; preserve actual child and observer ownership
                failed = True
        if failed:
            raise NativeRoomError("cleanup_incomplete")

    async def start(self) -> None:
        self._bind()
        if self._closing:
            raise NativeRoomError("closed")
        current = asyncio.current_task()
        if current is not None and current.cancelling():
            raise asyncio.CancelledError
        if self._spawning is None:
            self._stage = "starting"
            self._spawning = _spawn(self._spawn_actual())
        try:
            async with asyncio.timeout(self._prepare_timeout):
                await asyncio.shield(self._spawning)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - finite process boundary; preserve actual child and observer ownership
            raise NativeRoomError("unavailable") from None

    async def wait_prepare(self) -> None:
        self._bind()
        if self._spawning is None:
            raise NativeRoomError("invalid_input")
        try:
            async with asyncio.timeout(self._prepare_timeout):
                await self._prepare.wait()
        except TimeoutError:
            raise NativeRoomError("unavailable") from None
        status = self.status()
        if (
            self._closing
            or status.protocol_failed
            or not status.running
            or not status.prepare_ready
            or status.stage
            not in {"prepare_ready", "room_connected", "waiting_participant", "ready"}
        ):
            raise NativeRoomError("unavailable")

    async def _wait_actual(self, process: asyncio.subprocess.Process) -> int:
        result = await process.wait()
        self._reaped = True
        self._prepare.set()  # wake readiness observer on failure/early exit
        self._terminal.set()
        return result

    async def wait_terminal(self) -> None:
        self._bind()
        if self._spawning is None:
            raise NativeRoomError("invalid_input")
        # Actual closed/failed stdout, malformed framing or real process exit
        # closes conversational admission promptly; stop still owns real reap.
        await self._terminal.wait()

    async def wait_exit(self) -> int:
        self._bind()
        if self._spawning is None:
            raise NativeRoomError("invalid_input")
        # This method observes an existing process; it cannot launch one. Stop
        # and a lost observer may both await the same retained actual wait.
        await asyncio.shield(self._spawning)
        if self._waiting is None:
            raise NativeRoomError("unavailable")
        return await asyncio.shield(self._waiting)

    async def _read_stdout(self, reader: asyncio.StreamReader) -> None:
        try:
            while True:
                raw = await reader.readline()
                if not raw:
                    return
                self._stdout_bytes = min(STDOUT_BYTES + 1, self._stdout_bytes + len(raw))
                self._stdout_frames = min(33, self._stdout_frames + 1)
                if (
                    len(raw) > FRAME_BYTES
                    or self._stdout_bytes > STDOUT_BYTES
                    or self._stdout_frames > 32
                    or not raw.endswith(b"\n")
                ):
                    raise ValueError

                def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
                    value: dict[str, object] = {}
                    for key, entry in items:
                        if key in value:
                            raise ValueError
                        value[key] = entry
                    return value

                value: object = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=pairs)
                if (
                    type(value) is not dict
                    or set(value)
                    not in (
                        {"schemaVersion", "component", "mode", "state"},
                        {"schemaVersion", "component", "mode", "state", "code"},
                        {"schemaVersion", "component", "mode", "state", "reason"},
                    )
                    or type(value["schemaVersion"]) is not int
                    or value["schemaVersion"] != 1
                    or value["component"] != "channel_policy_native_worker"
                    or value["mode"] != "scripted"
                    or type(value["state"]) is not str
                    or value["state"] not in _ALLOWED
                ):
                    raise ValueError
                state = value["state"]
                if state == "failed":
                    if set(value) != {
                        "schemaVersion",
                        "component",
                        "mode",
                        "state",
                        "code",
                    } or value["code"] not in {
                        "invalid_configuration",
                        "unavailable",
                        "closed",
                        "cleanup_incomplete",
                    }:
                        raise ValueError
                    self._protocol_failed = True
                elif state == "session_closed":
                    if set(value) != {
                        "schemaVersion",
                        "component",
                        "mode",
                        "state",
                        "reason",
                    } or not (
                        value["reason"] is None
                        or type(value["reason"]) is str
                        and value["reason"]
                        in {
                            "error",
                            "job_shutdown",
                            "participant_disconnected",
                            "user_initiated",
                            "task_completed",
                        }
                    ):
                        raise ValueError
                elif set(value) != {"schemaVersion", "component", "mode", "state"}:
                    raise ValueError
                if state not in {"closed", "failed", "session_closed"}:
                    expected = ("prepare_ready", "room_connected", "waiting_participant", "ready")
                    if (
                        self._progress >= len(expected)
                        or state != expected[self._progress]
                        or self._stage in {"closed", "failed", "session_closed"}
                    ):
                        raise ValueError
                    self._progress += 1
                self._stage = cast(WorkerStage, state)
                if state == "prepare_ready":
                    self._seen_prepare = True
                    self._prepare.set()
                if state == "ready":
                    self._ready.set()
                if state in {"closed", "failed", "session_closed"}:
                    self._ready.clear()
                    self._terminal.set()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - finite process boundary; preserve actual child and observer ownership
            self._protocol_failed = True
            self._stage = "failed"
            self._prepare.set()
            self._terminal.set()
            # Stop trusting frames but keep draining bounded chunks. Abandoning
            # a full stdout pipe could otherwise deadlock graceful child stop.
            while await reader.read(4096):
                pass

    async def _read_stderr(self, reader: asyncio.StreamReader) -> None:
        while True:
            raw = await reader.read(4096)
            if not raw:
                return
            self._stderr_bytes = min(STDERR_BYTES + 1, self._stderr_bytes + len(raw))
            if self._stderr_bytes > STDERR_BYTES:
                self._protocol_failed = True
                self._terminal.set()
                # Continue draining without retaining bytes; preserve bounded
                # memory/child liveness while the parent observes failure.

    async def _finish_stop(self) -> None:
        if self._spawning is not None:
            await asyncio.gather(asyncio.shield(self._spawning), return_exceptions=True)
        process = self._process
        if process is None:
            return
        self._observe_process(process)
        if process.returncode is None and not self._signal_sent:
            self._signal_sent = True
            try:
                process.send_signal(signal.SIGTERM)
            except ProcessLookupError:
                pass
        assert self._waiting is not None
        await asyncio.shield(self._waiting)
        pipes = tuple(task for task in (self._stdout, self._stderr) if task is not None)
        if pipes:
            await asyncio.gather(*pipes, return_exceptions=True)
        if not self._reaped or process.returncode is None:
            raise NativeRoomError("cleanup_incomplete")
        # No signal is sent after reap, when a PID might later be reused.
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return
        except PermissionError:
            raise NativeRoomError("cleanup_incomplete") from None
        raise NativeRoomError("cleanup_incomplete")

    async def stop(self) -> None:
        self._bind()
        self._closing = True
        self._ready.clear()
        if (
            self._stopping is None
            or self._stopping.done()
            and (self._stopping.cancelled() or self._stopping.exception() is not None)
        ):
            self._stopping = _spawn(self._finish_stop(), cleanup=True)
        try:
            async with asyncio.timeout(self._cleanup):
                await asyncio.shield(self._stopping)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - finite process boundary; preserve actual child and observer ownership
            raise NativeRoomError("cleanup_incomplete") from None

    async def close(self) -> None:
        await self.stop()
