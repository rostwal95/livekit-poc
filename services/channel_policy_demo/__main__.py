"""Explicit local application CLI; import and --plan allocate no runtime owners."""

from __future__ import annotations

import asyncio
import json
import signal
import sys
from collections.abc import Coroutine, Sequence
from inspect import getattr_static
from pathlib import Path
from typing import Literal, Protocol, TypeVar

ExecutorMode = Literal["running", "paused"]
Event = Literal["sources_ready", "app_ready", "cleanup_incomplete", "closed", "error"]
Code = Literal["ok", "invalid_arguments", "invalid_profile", "unavailable", "cleanup_incomplete"]
_READINESS_SECONDS = 15.0
_POLL_SECONDS = 0.1
_CLOSE_OBSERVER_SECONDS = 5.0
T = TypeVar("T")


class ApplicationPort(Protocol):
    """The application retains actual owners behind each bounded public waiter."""

    async def start_sources(self) -> None: ...
    async def start_executor(self) -> None: ...
    async def close(self) -> None: ...


class EventSink(Protocol):
    def __call__(self, event: Event, code: Code, executor: ExecutorMode) -> None: ...


class CliError(ValueError):
    def __init__(self) -> None:
        super().__init__("invalid_arguments")


def _event(event: Event, code: Code, executor: ExecutorMode) -> None:
    sys.stdout.write(
        json.dumps(
            {"schema_version": 1, "event": event, "code": code, "executor": executor},
            separators=(",", ":"),
        )
        + "\n"
    )
    sys.stdout.flush()


def _emit(sink: EventSink, event: Event, code: Code, executor: ExecutorMode) -> None:
    try:
        sink(event, code, executor)
    except Exception:  # noqa: BLE001, S110 - broken output cannot abandon actual owners
        pass


def _task(action: Coroutine[object, object, T]) -> asyncio.Task[T]:
    try:
        task = asyncio.create_task(action)
    except BaseException:
        action.close()
        raise
    task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    return task


def _arguments(argv: Sequence[str]) -> tuple[Path, ExecutorMode] | None:
    if list(argv) == ["--plan"]:
        return None
    if not argv or argv[0] != "serve" or len(argv) not in (3, 5):
        raise CliError()
    values: dict[str, str] = {}
    for index in range(1, len(argv), 2):
        name, value = argv[index], argv[index + 1]
        if type(name) is not str or type(value) is not str:
            raise CliError()
        if name not in {"--profile", "--executor"} or name in values:
            raise CliError()
        values[name] = value
    if "--profile" not in values or values.get("--executor", "running") not in {
        "running",
        "paused",
    }:
        raise CliError()
    raw = values["--profile"]
    try:
        if not 0 < len(raw.encode("utf-8", "strict")) <= 4096 or any(ord(c) < 32 for c in raw):
            raise CliError()
        path = Path(raw)
        if not path.is_absolute() or path.suffix != ".json":
            raise CliError()
    except (ValueError, TypeError, UnicodeError):
        raise CliError() from None
    return path, "paused" if values.get("--executor") == "paused" else "running"


def _retry_readiness(error: Exception) -> bool:
    try:
        code: object = getattr_static(error, "code", None)
    except Exception:  # noqa: BLE001 - dependency descriptors never enter diagnostics
        return False
    return type(code) is str and code == "unavailable"


async def _wait_stage(
    stage: asyncio.Task[None], stop: asyncio.Task[bool], *, deadline: float | None = None
) -> bool:
    timeout = None if deadline is None else max(0.0, deadline - asyncio.get_running_loop().time())
    done, _ = await asyncio.wait(
        (stage, stop), timeout=timeout, return_when=asyncio.FIRST_COMPLETED
    )
    return stage in done and stop not in done


async def run_application(
    app: ApplicationPort,
    *,
    executor: ExecutorMode,
    stop: asyncio.Event,
    emit: EventSink = _event,
) -> int:
    """Supervise public startup/close; cancellation never cancels actual stages.

    The one readiness deadline bounds read-only Node readiness attempts, never a
    business operation. Close observers are bounded and retryable; actual owners
    can keep the process alive until the parent explicitly terminates it.
    """
    if type(executor) is not str or executor not in {"running", "paused"}:
        raise CliError()
    loop = asyncio.get_running_loop()
    stopping: asyncio.Task[bool] | None = None
    source: asyncio.Task[None] | None = None
    readiness: asyncio.Task[None] | None = None
    cancelled = failed = False
    incomplete_emitted = False
    try:
        stopping = _task(stop.wait())
        if not stop.is_set():
            source = _task(app.start_sources())
            if await _wait_stage(source, stopping):
                source.result()
                if not stop.is_set():
                    _emit(emit, "sources_ready", "ok", executor)
                if executor == "running":
                    deadline = loop.time() + _READINESS_SECONDS
                    while not stop.is_set():
                        if loop.time() >= deadline:
                            raise RuntimeError
                        readiness = _task(app.start_executor())
                        if not await _wait_stage(readiness, stopping, deadline=deadline):
                            if not stop.is_set():
                                raise RuntimeError
                            break
                        try:
                            readiness.result()
                        except Exception as error:  # noqa: BLE001 - finite readiness-only retry
                            if not _retry_readiness(error):
                                raise RuntimeError from None
                            if loop.time() >= deadline:
                                raise RuntimeError from None
                            await asyncio.wait(
                                (stopping,),
                                timeout=min(_POLL_SECONDS, max(0.0, deadline - loop.time())),
                            )
                        else:
                            if loop.time() >= deadline and not stop.is_set():
                                raise RuntimeError
                            if not stop.is_set():
                                _emit(emit, "app_ready", "ok", executor)
                            break
                elif not stop.is_set():
                    _emit(emit, "app_ready", "ok", executor)
                if not stop.is_set():
                    await asyncio.shield(stopping)
    except asyncio.CancelledError:
        cancelled = True
    except Exception:  # noqa: BLE001 - no path, argv or private dependency diagnostic escapes
        failed = True
        _emit(emit, "error", "unavailable", executor)
    finally:
        stop.set()
        closing: asyncio.Task[None] | None = None

        async def close_and_settle() -> None:
            # Begin public close before observing held startup/readiness waiters.
            await app.close()
            await asyncio.gather(
                *(asyncio.shield(task) for task in (source, readiness) if task is not None),
                return_exceptions=True,
            )

        while True:
            try:
                if closing is None:
                    closing = _task(close_and_settle())
                async with asyncio.timeout(_CLOSE_OBSERVER_SECONDS):
                    await asyncio.shield(closing)
                break
            except asyncio.CancelledError:
                cancelled = True
                if closing is not None and closing.done():
                    closing = None
            except Exception:  # noqa: BLE001 - actual close owner remains retained for repair
                if closing is not None and closing.done():
                    closing = None
            if not incomplete_emitted:
                _emit(emit, "cleanup_incomplete", "cleanup_incomplete", executor)
                incomplete_emitted = True
            if closing is None:
                # An explicit failed observer is retried, never a business call.
                pause_deadline = loop.time() + _POLL_SECONDS
                while loop.time() < pause_deadline:
                    try:
                        await asyncio.sleep(max(0.0, pause_deadline - loop.time()))
                    except asyncio.CancelledError:
                        cancelled = True
        if stopping is not None:
            # This event-only waiter owns no business I/O and settles once stop is set.
            while not stopping.done():
                try:
                    await asyncio.shield(stopping)
                except asyncio.CancelledError:
                    cancelled = True
        _emit(emit, "closed", "ok", executor)
    if cancelled:
        raise asyncio.CancelledError
    return 1 if failed else 0


def _load_application(path: Path) -> ApplicationPort:
    # Only serving loads the trusted bounded private profile and runtime classes.
    from .application import ChannelPolicyApplication
    from .owner_config import read_owner_profile

    return ChannelPolicyApplication(read_owner_profile(path))


async def _serve(path: Path, executor: ExecutorMode) -> int:
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    installed: list[signal.Signals] = []
    try:
        for selected in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(selected, stop.set)
            installed.append(selected)
        try:
            app = _load_application(path)
        except Exception as error:  # noqa: BLE001 - no private profile/loader exception text
            # ProfileError is intentionally identified only inside the serving path.
            from .owner_config import ProfileError

            _emit(
                _event,
                "error",
                "invalid_profile" if isinstance(error, ProfileError) else "unavailable",
                executor,
            )
            return 2 if isinstance(error, ProfileError) else 1
        return await run_application(app, executor=executor, stop=stop, emit=_event)
    finally:
        for selected in installed:
            loop.remove_signal_handler(selected)


def main(argv: Sequence[str] | None = None) -> int:
    """Return finite exit status; command arguments and private text are never echoed."""
    try:
        selected = _arguments(sys.argv[1:] if argv is None else argv)
    except Exception:  # noqa: BLE001 - malformed CLI values are never printed
        _emit(_event, "error", "invalid_arguments", "running")
        return 2
    if selected is None:
        sys.stdout.write(
            json.dumps(
                {
                    "schema_version": 1,
                    "event": "plan",
                    "code": "ok",
                    "stages": ["sources_ready", "app_ready", "closed"],
                    "limits": {
                        "node_readiness_ms": 15000,
                        "readiness_poll_ms": 100,
                        "close_observer_ms": 5000,
                    },
                    "profile": "explicit_private_json",
                    "provider_access": False,
                    "serving_ddl": False,
                },
                separators=(",", ":"),
            )
            + "\n"
        )
        sys.stdout.flush()
        return 0
    try:
        return asyncio.run(_serve(*selected))
    except Exception:  # noqa: BLE001 - no dependency text reaches CLI diagnostics
        _emit(_event, "error", "unavailable", selected[1])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
