"""Fixed two-process Root unittest lane with exact coverage and bounded ownership.

Project lanes and acceptance runners do not use this helper. Normal nested helper
cleanup belongs to the existing tests. Forced worker stop cannot establish that
new-session helpers settled, so it always leaves cleanup incomplete.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, cast

ROLES = ("sdk", "other")
SDK_MODULES = frozenset({"test_conversation_agent", "test_provider_inference", "test_rtc_agent"})
MAX_JSON = 1_048_576
MAX_STREAM = 1_048_576
MAX_CAPTURE = 2_097_152
MAX_RETAINED = 8_388_608
MAX_IDS = 10_000
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_.]{0,511}\Z", re.ASCII)


class _Invalid(Exception):
    pass


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _Invalid("invalid_json")
        result[key] = value
    return result


def _constant(_value: str) -> None:
    raise _Invalid("invalid_json")


def _json(raw: bytes) -> dict[str, Any]:
    if not 0 < len(raw) <= MAX_JSON:
        raise _Invalid("metadata_limit")
    try:
        value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
    except (ValueError, UnicodeError) as error:
        raise _Invalid("invalid_json") from error
    if type(value) is not dict:
        raise _Invalid("invalid_json")
    return cast(dict[str, Any], value)


def _directory(path: Path) -> tuple[int, int]:
    meta = path.lstat()
    if (
        not stat.S_ISDIR(meta.st_mode)
        or stat.S_IMODE(meta.st_mode) != 0o700
        or meta.st_uid != os.geteuid()
        or path.resolve(strict=True) != path
    ):
        raise _Invalid("unsafe_evidence")
    return meta.st_dev, meta.st_ino


def _publish(directory: Path, name: str, value: dict[str, Any]) -> None:
    _directory(directory)
    raw = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode()
    if len(raw) > MAX_JSON:
        raise _Invalid("metadata_limit")
    pending = directory / (name + ".pending")
    fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
    os.link(pending, directory / name, follow_symlinks=False)
    pending.unlink()


def _read(directory: Path, name: str) -> dict[str, Any] | None:
    path = directory / name
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_uid != os.geteuid()
            or not 0 < before.st_size <= MAX_JSON
        ):
            raise _Invalid("unsafe_metadata")
        if before.st_nlink == 2:
            try:
                pending = (directory / (name + ".pending")).lstat()
            except FileNotFoundError:
                pending = None
            if pending and (pending.st_dev, pending.st_ino) == (before.st_dev, before.st_ino):
                return None  # Only the exact atomic publication window may be retried.
        if before.st_nlink != 1:
            raise _Invalid("unsafe_metadata")
        raw = stream.read(MAX_JSON + 1)
        after = os.fstat(stream.fileno())
        current = path.lstat()
        if (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_uid,
            before.st_nlink,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_uid,
            after.st_nlink,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ) or (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino):
            raise _Invalid("changed_metadata")
    return _json(raw)


def _ids(value: Any) -> list[str]:
    if (
        type(value) is not list
        or not 0 < len(value) <= MAX_IDS
        or any(type(item) is not str or IDENTIFIER.fullmatch(item) is None for item in value)
        or len(set(value)) != len(value)
    ):
        raise _Invalid("invalid_ids")
    return cast(list[str], value)


def _selected(identifier: str, role: str) -> bool:
    return (identifier.split(".", 1)[0] in SDK_MODULES) == (role == "sdk")


def _manifest(value: dict[str, Any], role: str, nonce: str, pid: int) -> dict[str, Any]:
    if (
        value.keys() != {"schemaVersion", "nonce", "role", "pid", "full", "selected"}
        or type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or value["nonce"] != nonce
        or value["role"] != role
        or type(value["pid"]) is not int
        or value["pid"] != pid
    ):
        raise _Invalid("invalid_manifest")
    full, selected = _ids(value["full"]), _ids(value["selected"])
    if selected != [identifier for identifier in full if _selected(identifier, role)]:
        raise _Invalid("invalid_partition")
    return value


def _parity(manifests: list[dict[str, Any]]) -> list[str]:
    left, right = manifests
    if left["full"] != right["full"]:
        raise _Invalid("discovery_mismatch")
    if set(left["selected"]) & set(right["selected"]) or set(left["selected"]) | set(
        right["selected"]
    ) != set(left["full"]):
        raise _Invalid("coverage_mismatch")
    return cast(list[str], left["full"])


def _result(value: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "schemaVersion",
        "nonce",
        "role",
        "pid",
        "started",
        "testsRun",
        "failures",
        "errors",
        "skips",
        "unexpectedSuccesses",
        "expectedFailures",
        "successful",
    }
    if value.keys() != fields or any(
        type(value[k]) is not type(manifest[k]) or value[k] != manifest[k]
        for k in ("schemaVersion", "nonce", "role", "pid")
    ):
        raise _Invalid("invalid_result")
    for key in (
        "testsRun",
        "failures",
        "errors",
        "skips",
        "unexpectedSuccesses",
        "expectedFailures",
    ):
        if type(value[key]) is not int or not 0 <= value[key] <= MAX_IDS:
            raise _Invalid("invalid_result")
    started = _ids(value["started"])
    if started != manifest["selected"] or value["testsRun"] != len(started):
        raise _Invalid("execution_mismatch")
    if type(value["successful"]) is not bool:
        raise _Invalid("invalid_result")
    if not value["successful"] or any(
        value[k] for k in ("failures", "errors", "skips", "unexpectedSuccesses")
    ):
        raise _Invalid("tests_failed")
    return value


def _prune(suite: unittest.TestSuite, role: str, full: list[str]) -> unittest.TestSuite:
    if (
        type(suite) is not unittest.TestSuite
        or vars(suite).keys() != {"_tests", "_removed_tests"}
        or type(vars(suite)["_tests"]) is not list
        or type(vars(suite)["_removed_tests"]) is not int
        or vars(suite)["_removed_tests"] != 0
    ):
        raise _Invalid("unsupported_suite")
    selected = unittest.TestSuite()
    for item in suite:
        if type(item) is unittest.TestSuite:
            child = _prune(item, role, full)
            if child.countTestCases():
                selected.addTest(child)
        elif isinstance(item, unittest.TestCase):
            identifier = item.id()
            full.append(identifier)
            if _selected(identifier, role):
                selected.addTest(item)
        else:
            raise _Invalid("unsupported_suite")
    return selected


class _RecordingResult(unittest.TextTestResult):
    def __init__(self, stream: Any, descriptions: bool, verbosity: int) -> None:
        super().__init__(stream, descriptions, verbosity)
        self.started: list[str] = []

    def startTest(self, test: unittest.TestCase) -> None:
        self.started.append(test.id())
        super().startTest(test)


def _worker(root: Path, directory: Path, role: str, nonce: str) -> int:
    try:
        _directory(directory)
        # Match python -m unittest's checkout import path, while -I excludes ambient PYTHONPATH.
        sys.path.insert(0, str(root))
        loader = unittest.TestLoader()
        suite = loader.discover("tests", pattern="test_*.py")
        if loader.errors:
            raise _Invalid("discovery_failed")
        full: list[str] = []
        selected = _prune(suite, role, full)
        manifest = _manifest(
            {
                "schemaVersion": 1,
                "nonce": nonce,
                "role": role,
                "pid": os.getpid(),
                "full": full,
                "selected": [x for x in full if _selected(x, role)],
            },
            role,
            nonce,
            os.getpid(),
        )
        _publish(directory, role + ".manifest.json", manifest)
        if sys.stdin.buffer.read(4) != b"GO\n":
            raise _Invalid("control_denied")
        result = cast(
            _RecordingResult,
            unittest.TextTestRunner(verbosity=2, resultclass=_RecordingResult).run(selected),
        )
        _publish(
            directory,
            role + ".result.json",
            {
                "schemaVersion": 1,
                "nonce": nonce,
                "role": role,
                "pid": os.getpid(),
                "started": result.started,
                "testsRun": result.testsRun,
                "failures": len(result.failures),
                "errors": len(result.errors),
                "skips": len(result.skipped),
                "unexpectedSuccesses": len(result.unexpectedSuccesses),
                "expectedFailures": len(result.expectedFailures),
                "successful": result.wasSuccessful(),
            },
        )
        return 0 if result.wasSuccessful() and not result.skipped else 1
    except BaseException:  # noqa: BLE001 - isolate discovery/test exit from parent diagnostics
        # Details, including import/test exceptions, belong only to private capture.
        return 2


@dataclass(frozen=True)
class _Timing:
    total: float = 120.0
    cleanup: float = 5.0

    def validate(self) -> None:
        if (
            not all(
                type(v) in (int, float) and math.isfinite(v) for v in (self.total, self.cleanup)
            )
            or not 0 < self.cleanup < self.total <= 120
            or self.cleanup > 5
        ):
            raise ValueError("invalid_timing")


@dataclass
class _Child:
    role: str
    process: subprocess.Popen[bytes]
    manifest: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    sizes: dict[str, int] = field(default_factory=lambda: {"stdout": 0, "stderr": 0})
    tails: dict[str, bytes] = field(default_factory=lambda: {"stdout": b"", "stderr": b""})
    signals: list[int] = field(default_factory=list)
    group_absent: bool = False
    signal_errors: list[int] = field(default_factory=list)


def _group(child: _Child) -> bool:
    if child.group_absent:
        return False
    try:
        os.killpg(child.process.pid, 0)
        return True
    except ProcessLookupError:
        child.group_absent = True
        return False
    except PermissionError:
        return True


def run_root_tests(
    root: Path,
    progress: Callable[[object], dict[str, str | int | float | None]],
    *,
    _timing: _Timing | None = None,
) -> dict[str, Any]:
    """Run one complete Root selection; private timing injection only shrinks tests' budget."""
    timing = _timing or _Timing()
    timing.validate()
    began = time.monotonic()
    final = began + timing.total
    work_end = final - timing.cleanup
    children: list[_Child] = []
    outputs: dict[tuple[str, str], BinaryIO] = {}
    selector = selectors.DefaultSelector()
    code: str | None = None
    stopped: float | None = None
    interrupted = False
    timed_out = False
    forced = False
    overflow = False
    admitted = False
    full: list[str] = []
    captured = 0
    last_stderr = b""
    directory: Path | None = None
    identity: tuple[int, int] | None = None
    handlers: dict[signal.Signals, Any] = {}
    captures_settled = False

    def interrupt(_signum: int, _frame: Any) -> None:
        nonlocal interrupted
        interrupted = True

    def fail(value: str) -> None:
        nonlocal code
        if code is None:
            code = value

    def drain(wait: float = 0) -> None:
        nonlocal captured, overflow, last_stderr
        for key, _ in selector.select(max(0, wait)):
            child, name = key.data
            stream = cast(BinaryIO, key.fileobj)
            try:
                raw = os.read(stream.fileno(), 8192)
            except BlockingIOError:
                continue
            if not raw:
                selector.unregister(stream)
                stream.close()
                continue
            child.tails[name] = (child.tails[name] + raw)[-65536:]
            if name == "stderr":
                last_stderr = child.tails[name]
            allowed = min(MAX_STREAM - child.sizes[name], MAX_CAPTURE - captured, len(raw))
            if allowed:
                outputs[(child.role, name)].write(raw[:allowed])
                child.sizes[name] += allowed
                captured += allowed
            if allowed < len(raw):
                overflow = True
                fail("capture_overflow")

    def stop() -> None:
        nonlocal stopped, forced
        if stopped is None:
            stopped = time.monotonic()
        elapsed = time.monotonic() - stopped
        phase = min(timing.cleanup / 3, 1.0)
        target = (
            signal.SIGINT
            if elapsed < phase
            else signal.SIGTERM
            if elapsed < phase * 2
            else signal.SIGKILL
        )
        for child in children:
            if child.process.stdin and not child.process.stdin.closed:
                try:
                    child.process.stdin.close()
                except OSError:
                    fail("control_cleanup_failed")
            child.process.poll()
            if elapsed < min(0.05, timing.cleanup / 6):
                continue
            if (
                _group(child)
                and int(target) not in child.signals
                and int(target) not in child.signal_errors
            ):
                try:
                    os.killpg(child.process.pid, target)
                    child.signals.append(int(target))
                    forced = True
                except ProcessLookupError:
                    child.group_absent = True
                except OSError:
                    child.signal_errors.append(int(target))
                    fail("signal_cleanup_failed")

    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            handlers[signum] = signal.signal(signum, interrupt)
        directory = Path(tempfile.mkdtemp(prefix="harness-root-unittest-")).resolve()
        identity = _directory(directory)
        nonce = uuid.uuid4().hex
        for role in ROLES:
            if time.monotonic() >= work_end or interrupted:
                raise _Invalid("timeout" if not interrupted else "interrupted")
            for name in ("stdout", "stderr"):
                fd = os.open(
                    directory / (role + "." + name + ".bin"),
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                )
                outputs[(role, name)] = os.fdopen(fd, "wb", buffering=0)
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    str(Path(__file__).resolve()),
                    "--worker",
                    str(root),
                    str(directory),
                    role,
                    nonce,
                ],
                cwd=root,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            child = _Child(role, process)
            children.append(child)  # Ownership starts before any pipe setup may fail.
            _publish(
                directory,
                role + ".owner.json",
                {"schemaVersion": 1, "nonce": nonce, "role": role, "pid": process.pid},
            )
            for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
                assert stream is not None
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, (child, name))
        while True:
            now = time.monotonic()
            if interrupted:
                fail("interrupted")
            if now >= work_end:
                timed_out = True
                fail("timeout")
            if _directory(directory) != identity:
                fail("changed_evidence")
            if code is None and not admitted:
                for child in children:
                    if child.manifest is None:
                        value = _read(directory, child.role + ".manifest.json")
                        if value is not None:
                            child.manifest = _manifest(value, child.role, nonce, child.process.pid)
                        elif child.process.poll() is not None:
                            raise _Invalid("discovery_failed")
                if all(c.manifest is not None for c in children):
                    full = _parity([cast(dict[str, Any], c.manifest) for c in children])
                    for child in children:
                        assert child.process.stdin is not None
                        child.process.stdin.write(b"GO\n")
                        child.process.stdin.close()
                    admitted = True
            if admitted:
                for child in children:
                    if child.result is None:
                        value = _read(directory, child.role + ".result.json")
                        if value is not None:
                            try:
                                child.result = _result(value, cast(dict[str, Any], child.manifest))
                            except _Invalid as error:
                                if str(error) == "tests_failed":
                                    child.result = value
                                fail(str(error))
                        elif child.process.poll() is not None:
                            fail("missing_result")
            if timed_out or interrupted or overflow:
                stop()
            complete = all(c.process.poll() is not None and not _group(c) for c in children)
            if complete and not selector.get_map():
                break
            if now >= final:
                timed_out = True
                fail("timeout")
                break
            drain(min(0.01, final - now))
        if admitted:
            for child in children:
                value = _read(directory, child.role + ".result.json")
                if value is None:
                    fail("missing_result")
                else:
                    try:
                        child.result = _result(value, cast(dict[str, Any], child.manifest))
                    except _Invalid as error:
                        if str(error) == "tests_failed":
                            child.result = value
                        fail(str(error))
                if child.process.returncode != 0:
                    fail("worker_failed")
    except _Invalid as error:
        timed_out = timed_out or str(error) == "timeout"
        fail(str(error))
    except (OSError, ValueError, AssertionError):
        fail("runner_failed")
    finally:
        # Every returned child is retained through one original deadline, including spawn failure.
        while children and time.monotonic() < final:
            complete = all(c.process.poll() is not None and not _group(c) for c in children)
            if complete and not selector.get_map():
                break
            stop()
            try:
                drain(min(0.01, max(0, final - time.monotonic())))
            except (OSError, ValueError):
                fail("capture_cleanup_failed")
        for child in children:
            child.process.poll()
            for stream in (child.process.stdin, child.process.stdout, child.process.stderr):
                if stream and not stream.closed:
                    stream.close()
        captures_settled = not selector.get_map()
        selector.close()
        for stream in outputs.values():
            stream.close()
        for signum, previous in handlers.items():
            signal.signal(signum, previous)
    outer_clean = all(c.process.returncode is not None and not _group(c) for c in children)
    cleanup_complete = (
        len(children) == 2 and outer_clean and captures_settled and not forced and code is None
    )
    if not outer_clean:
        fail("cleanup_incomplete")
    if time.monotonic() >= final:
        timed_out = True
        fail("timeout")
    artifacts: dict[str, Any] = {}
    if directory is not None:
        total_bytes = 0
        try:
            if _directory(directory) != identity:
                raise _Invalid("changed_evidence")
            for index, path in enumerate(directory.iterdir()):
                if (
                    index >= 16
                    or re.fullmatch(
                        r"(?:sdk|other)\.(?:(?:owner|manifest|result)\.json(?:\.pending)?|(?:stdout|stderr)\.bin)",
                        path.name,
                    )
                    is None
                ):
                    raise _Invalid("unsafe_evidence")
                meta = path.lstat()
                if (
                    not stat.S_ISREG(meta.st_mode)
                    or meta.st_nlink != 1
                    or stat.S_IMODE(meta.st_mode) != 0o600
                    or meta.st_uid != os.geteuid()
                    or meta.st_size > MAX_JSON
                ):
                    raise _Invalid("unsafe_evidence")
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(fd, "rb") as source:
                    opened = os.fstat(source.fileno())
                    if (opened.st_dev, opened.st_ino, opened.st_nlink, opened.st_size) != (
                        meta.st_dev,
                        meta.st_ino,
                        1,
                        meta.st_size,
                    ):
                        raise _Invalid("changed_evidence")
                    raw = source.read(MAX_JSON + 1)
                    after = os.fstat(source.fileno())
                    if (
                        len(raw) != meta.st_size
                        or (after.st_mtime_ns, after.st_ctime_ns, after.st_size)
                        != (opened.st_mtime_ns, opened.st_ctime_ns, opened.st_size)
                        or path.lstat().st_ino != opened.st_ino
                    ):
                        raise _Invalid("changed_evidence")
                total_bytes += len(raw)
                if total_bytes > MAX_RETAINED:
                    raise _Invalid("evidence_limit")
                artifacts[path.name] = {
                    "bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
        except (OSError, _Invalid):
            fail("evidence_invalid")
    result: dict[str, Any] = {
        "command": [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
            "-p",
            "test_*.py",
            "-v",
        ],
        "runner": "fixed_two_process_root",
        "commandKind": "logical_discovery_selection",
        "workerCommands": [list(cast(list[str], c.process.args)) for c in children],
        "exitCode": 124
        if timed_out
        else 0
        if code is None
        else 130
        if code == "interrupted"
        else 1,
        "status": "passed" if code is None else "failed",
        "timedOut": timed_out,
        "code": code or "ok",
        "testCount": len(full)
        if code is None
        else sum(len(c.result["started"]) for c in children if c.result),
        "skippedCount": sum(c.result["skips"] for c in children if c.result),
        "stdout": "",
        "stderr": "test suite exceeded 120 seconds"
        if timed_out
        else ""
        if code is None
        else "root test lane failed; inspect private evidence",
        "cleanup_complete": cleanup_complete,
        "outer_groups_settled": outer_clean,
        "captures_settled": captures_settled,
        "nested_cleanup": "normal_fixture_cleanup_only"
        if cleanup_complete
        else "unverified_without_successful_fixture_completion",
        "retainedWork": str(directory) if directory else None,
        "artifacts": artifacts,
        "durationSeconds": time.monotonic() - began,
        "workers": [
            {
                "role": c.role,
                "pid": c.process.pid,
                "returncode": c.process.returncode,
                "groupAbsent": c.group_absent,
                "signals": c.signals,
                "signalErrors": c.signal_errors,
                "selectedCount": len(c.manifest["selected"]) if c.manifest else 0,
            }
            for c in children
        ],
    }
    if timed_out:
        result["timeoutProgress"] = progress(last_stderr)
        result["workerProgress"] = {c.role: progress(c.tails["stderr"]) for c in children}
    else:
        result["runnerExitCode"] = result["exitCode"]
    if len(json.dumps(result).encode()) > 65536:
        return {
            "exitCode": 1,
            "status": "failed",
            "code": "summary_limit",
            "retainedWork": str(directory),
            "cleanup_complete": cleanup_complete,
        }
    if time.monotonic() >= final and result["exitCode"] == 0:
        result.update(
            exitCode=124,
            status="failed",
            code="timeout",
            timedOut=True,
            stderr="test suite exceeded 120 seconds",
            timeoutProgress=progress(last_stderr),
        )
        result.pop("runnerExitCode", None)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true", required=True)
    parser.add_argument("root", type=Path)
    parser.add_argument("directory", type=Path)
    parser.add_argument("role", choices=ROLES)
    parser.add_argument("nonce")
    args = parser.parse_args()
    if re.fullmatch(r"[0-9a-f]{32}", args.nonce) is None:
        return 2
    return _worker(args.root.resolve(), args.directory.resolve(), args.role, args.nonce)


if __name__ == "__main__":
    raise SystemExit(main())
