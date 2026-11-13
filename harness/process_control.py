"""Owned POSIX test children, named crash barriers and deterministic clocks.

This module is test tooling, not a production worker scheduler or process-control
API. Commands and environment come from trusted fixtures. Output files are private,
byte-capped synthetic evidence; only explicit tail reads apply supplied redactions.
"""

from __future__ import annotations

import math
import os
import re
import selectors
import signal
import stat
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import BinaryIO, Self, cast

MAX_TIMEOUT_SECONDS = 300.0
MAX_OUTPUT_BYTES = 1_048_576
MAX_TAIL_BYTES = 8_192
POLL_SECONDS = 0.01


class ProcessControlError(RuntimeError):
    """A fixture failed to establish its required process observation."""


class ProcessTimeout(ProcessControlError):
    """An observation did not finish within its declared deadline."""


class ProcessExited(ProcessControlError):
    """The child exited before the required live-process observation."""


class ProcessOutputLimit(ProcessControlError):
    """Captured output exceeded the fixture's declared byte budget."""


class UnsafeHarnessPath(ProcessControlError):
    """A fixture path is unsafe or would reuse an existing marker/output."""


def _seconds(value: float, *, allow_zero: bool = False) -> float:
    if type(value) not in (int, float):
        raise ValueError("Duration must be finite and within the declared bound")
    try:
        converted = float(value)
    except OverflowError as error:
        raise ValueError("Duration exceeds finite range") from error
    if (
        not math.isfinite(converted)
        or converted < 0
        or (not allow_zero and converted == 0)
        or converted > MAX_TIMEOUT_SECONDS
    ):
        raise ValueError("Duration must be finite and within the declared bound")
    return converted


def _directory(path: Path, *, create: bool = False, private: bool = True) -> Path:
    candidate = Path(path).absolute()
    if ".." in candidate.parts:
        raise UnsafeHarnessPath("Harness directories cannot contain traversal")
    if any(part.is_symlink() for part in (candidate, *candidate.parents)):
        raise UnsafeHarnessPath("Harness directories cannot contain symlinks")
    if create:
        try:
            candidate.mkdir(mode=0o700)
        except OSError as error:
            raise UnsafeHarnessPath("Harness output directory must be new") from error
    if not candidate.is_dir():
        raise UnsafeHarnessPath("Harness directory does not exist")
    if private and candidate.stat().st_mode & 0o077:
        raise UnsafeHarnessPath("Harness state directory must be private")
    return candidate


def _exclusive_file(path: Path) -> BinaryIO:
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except OSError as error:
        raise UnsafeHarnessPath("Harness artifact must be a new regular file") from error
    return os.fdopen(fd, "wb", buffering=0)


class FileBarrier:
    """One named, single-use child arrival/release point in a private directory."""

    def __init__(self, directory: Path, name: str) -> None:
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name):
            raise ValueError("Invalid failpoint name")
        self.directory = _directory(directory)
        self.name = name
        self._reached = self.directory / f"{name}.reached"
        self._released = self.directory / f"{name}.released"
        if any(path.exists() or path.is_symlink() for path in (self._reached, self._released)):
            raise UnsafeHarnessPath("Failpoint markers must not be reused")

    @staticmethod
    def _read_pid(path: Path) -> int | None:
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(mode) or stat.S_ISLNK(mode):
            raise UnsafeHarnessPath("Failpoint marker must be a regular file")
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as stream:
                data = stream.read(33)
        except OSError as error:
            raise UnsafeHarnessPath("Failpoint marker cannot be read") from error
        if not re.fullmatch(rb"[1-9][0-9]{0,19}\n", data):
            raise ProcessControlError("Invalid failpoint process marker")
        return int(data)

    @staticmethod
    def _write_pid(path: Path, pid: int) -> None:
        pending = path.with_name(f"{path.name}.{pid}.pending")
        owned = False
        try:
            with _exclusive_file(pending) as stream:
                owned = True
                stream.write(f"{pid}\n".encode("ascii"))
                os.fsync(stream.fileno())
            # Publish only a complete marker, without replacing another marker.
            os.link(pending, path, follow_symlinks=False)
        except OSError as error:
            raise UnsafeHarnessPath("Failpoint marker cannot be published") from error
        finally:
            if owned:
                pending.unlink(missing_ok=True)

    def arrive_and_wait(self, *, timeout: float) -> None:
        """Child operation: publish its PID, then await parent release, or fail."""
        deadline = time.monotonic() + _seconds(timeout)
        pid = os.getpid()
        self._write_pid(self._reached, pid)
        while True:
            released = self._read_pid(self._released)
            if released is not None:
                if released != pid:
                    raise ProcessControlError("Failpoint release belongs to another process")
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProcessTimeout("Failpoint was not released before its deadline")
            # Poll an explicit persisted condition; elapsed time never means arrival.
            time.sleep(min(POLL_SECONDS, remaining))


@dataclass(frozen=True, slots=True)
class ProcessResult:
    pid: int
    returncode: int


@dataclass(frozen=True, slots=True)
class Termination:
    pid: int
    returncode: int
    killed: bool


class OwnedProcess:
    """Launch and reap one owned child with finite observations and capture.

    Normal fixture code must call wait or wait_for_barrier promptly to drain
    nonblocking output. No arbitrary PID or process-group kill API is exposed.
    Child programs must not leave independently running descendants behind.
    """

    def __init__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        output_directory: Path,
        max_output_bytes: int = 65_536,
    ) -> None:
        if os.name != "posix":
            raise ProcessControlError("Owned crash verification requires POSIX")
        if (
            isinstance(argv, (str, bytes))
            or not argv
            or any(not isinstance(arg, str) or not arg or "\0" in arg for arg in argv)
        ):
            raise ValueError("Child argv must contain explicit nonempty strings")
        if not isinstance(env, Mapping) or any(
            not isinstance(key, str)
            or not key
            or "=" in key
            or "\0" in key
            or not isinstance(value, str)
            or "\0" in value
            for key, value in env.items()
        ):
            raise ValueError("Child environment must contain explicit strings")
        if type(max_output_bytes) is not int or not 1 <= max_output_bytes <= MAX_OUTPUT_BYTES:
            raise ValueError("Invalid child output byte budget")
        self.output_directory = _directory(output_directory, create=True)
        self._maximum = max_output_bytes
        self._sizes = {"stdout": 0, "stderr": 0}
        self._overflow = False
        self._closed = False
        self._selector = selectors.DefaultSelector()
        self._outputs: dict[str, BinaryIO] = {}
        self._process: subprocess.Popen[bytes] | None = None
        self.termination: Termination | None = None
        self.cleanup_failed = False
        try:
            for name in ("stdout", "stderr"):
                self._outputs[name] = _exclusive_file(self.output_directory / f"{name}.bin")
            self._process = subprocess.Popen(
                list(argv),
                cwd=_directory(cwd, private=False),
                env=dict(env),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
            )
            for name, stream in (
                ("stdout", self._process.stdout),
                ("stderr", self._process.stderr),
            ):
                assert stream is not None
                os.set_blocking(stream.fileno(), False)
                self._selector.register(stream, selectors.EVENT_READ, name)
        except BaseException as error:
            try:
                self.close()
            except Exception:  # noqa: BLE001 - preserve startup cause when cleanup also fails
                self.cleanup_failed = True
                error.add_note("Owned process startup cleanup did not complete")
            raise

    @property
    def pid(self) -> int:
        assert self._process is not None
        return self._process.pid

    @property
    def returncode(self) -> int | None:
        assert self._process is not None
        return self._process.poll()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        try:
            self.close()
        except Exception:  # Preserve an in-flight fixture failure after cleanup.
            self.cleanup_failed = True
            if exc_type is None:
                raise
            if isinstance(exc, BaseException):
                exc.add_note("Owned process cleanup did not complete")

    def _drain(self, timeout: float = 0) -> None:
        for key, _ in self._selector.select(timeout):
            stream = cast(BinaryIO, key.fileobj)
            try:
                data = os.read(stream.fileno(), 8_192)
            except BlockingIOError:
                continue
            if not data:
                self._selector.unregister(stream)
                stream.close()
                continue
            name = str(key.data)
            remaining = self._maximum - self._sizes[name]
            self._outputs[name].write(data[:remaining])
            self._sizes[name] += min(len(data), remaining)
            if len(data) > remaining:
                self._overflow = True
        if self._overflow:
            raise ProcessOutputLimit("Child output exceeded its declared byte budget")

    def _assert_live(self) -> None:
        if self._closed or self.returncode is not None:
            raise ProcessExited("Child is not alive at the required observation")

    def wait_for_barrier(self, barrier: FileBarrier, *, timeout: float) -> None:
        deadline = time.monotonic() + _seconds(timeout)
        while True:
            self._assert_live()
            self._drain()
            reached = barrier._read_pid(barrier._reached)
            if reached is not None:
                if reached != self.pid:
                    raise ProcessControlError("Failpoint was reached by another process")
                self._assert_live()
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProcessTimeout("Child did not reach its required failpoint")
            self._drain(min(POLL_SECONDS, remaining))

    def release_barrier(self, barrier: FileBarrier) -> None:
        self._assert_live()
        if barrier._read_pid(barrier._reached) != self.pid:
            raise ProcessControlError("Owned child has not reached this failpoint")
        barrier._write_pid(barrier._released, self.pid)

    def wait(self, *, timeout: float) -> ProcessResult:
        deadline = time.monotonic() + _seconds(timeout)
        while True:
            self._drain()
            result = self.returncode
            if result is not None and not self._selector.get_map():
                return ProcessResult(self.pid, result)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProcessTimeout("Child did not finish before its deadline")
            self._drain(min(POLL_SECONDS, remaining))

    def _reap_killed(self, timeout: float) -> Termination:
        """Verify that this still-live child was actually killed and reaped."""
        _seconds(timeout)
        self._assert_live()
        assert self._process is not None
        try:
            self._process.kill()
            code = self._process.wait(timeout=timeout)
        except ProcessLookupError as error:
            self._process.wait(timeout=timeout)
            raise ProcessExited("Child exited before the requested kill") from error
        except subprocess.TimeoutExpired as error:
            raise ProcessTimeout("Killed child was not reaped before its deadline") from error
        killed = code == -signal.SIGKILL
        self.termination = Termination(self.pid, code, killed)
        if not killed:
            raise ProcessExited("Child exited without the required kill observation")
        return self.termination

    def kill(self, *, timeout: float = 3) -> Termination:
        """Verify actual SIGKILL, reap the child, then finish bounded capture."""
        deadline = time.monotonic() + _seconds(timeout)
        result = self._reap_killed(timeout)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ProcessTimeout("Child capture exceeded the kill deadline")
        self.wait(timeout=remaining)
        return result

    def output_tail(
        self,
        stream: str,
        *,
        maximum_bytes: int = MAX_TAIL_BYTES,
        redact_values: Sequence[str] = (),
    ) -> str:
        if stream not in self._outputs:
            raise ValueError("Unknown child output stream")
        if type(maximum_bytes) is not int or not 1 <= maximum_bytes <= MAX_TAIL_BYTES:
            raise ValueError("Invalid output tail byte budget")
        if (
            isinstance(redact_values, (str, bytes))
            or len(redact_values) > 32
            or any(
                not isinstance(value, str) or not value or len(value.encode("utf-8")) > 4_096
                for value in redact_values
            )
        ):
            raise ValueError("Invalid output redaction values")
        secrets = [value.encode("utf-8") for value in redact_values]
        overlap = max(map(len, secrets), default=0)
        path = self.output_directory / f"{stream}.bin"
        if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
            raise UnsafeHarnessPath("Child output must remain a regular file")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as source:
            source.seek(max(0, source.seek(0, os.SEEK_END) - maximum_bytes - overlap))
            data = source.read(maximum_bytes + overlap)
        start = max(0, len(data) - maximum_bytes)
        parts: list[bytes] = []
        cursor = start
        if secrets:
            pattern = b"|".join(
                re.escape(value) for value in sorted(secrets, key=len, reverse=True)
            )
            for match in re.finditer(pattern, data):
                if match.end() <= start:
                    continue
                parts.extend((data[cursor : max(cursor, match.start())], b"[redacted]"))
                cursor = match.end()
        parts.append(data[cursor:])
        return b"".join(parts)[-maximum_bytes:].decode("utf-8", errors="ignore")

    def close(self) -> None:
        """Idempotently kill/reap the owned child and close capture resources."""
        if self._closed:
            return
        try:
            if self._process is not None and self._process.poll() is None:
                self._reap_killed(3)
        finally:
            for key in list(self._selector.get_map().values()):
                self._selector.unregister(key.fileobj)
                cast(BinaryIO, key.fileobj).close()
            self._selector.close()
            if self._process is not None:
                for stream in (self._process.stdout, self._process.stderr):
                    if stream is not None:
                        stream.close()
            for output in self._outputs.values():
                output.close()
            self._closed = True


class ManualClock:
    """Explicit UTC business time and monotonic elapsed time for deterministic tests."""

    def __init__(self, start: datetime, *, monotonic_seconds: float = 0) -> None:
        if (
            not isinstance(start, datetime)
            or start.tzinfo is None
            or start.utcoffset() != timedelta(0)
        ):
            raise ValueError("Manual clock requires an aware UTC instant")
        self._now = start.astimezone(UTC)
        self._monotonic = self._interval(monotonic_seconds)

    @staticmethod
    def _interval(value: float) -> float:
        if type(value) not in (int, float):
            raise ValueError("Clock interval must be finite and nonnegative")
        try:
            converted = float(value)
        except OverflowError as error:
            raise ValueError("Clock interval exceeds finite range") from error
        if not math.isfinite(converted) or converted < 0:
            raise ValueError("Clock interval must be finite and nonnegative")
        return converted

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._monotonic

    def advance(self, seconds: float) -> None:
        interval = self._interval(seconds)
        try:
            now = self._now + timedelta(seconds=interval)
        except OverflowError as error:
            raise ValueError("Clock instant exceeds datetime range") from error
        elapsed = self._monotonic + interval
        if not math.isfinite(elapsed):
            raise ValueError("Clock elapsed time exceeds finite range")
        self._now, self._monotonic = now, elapsed
