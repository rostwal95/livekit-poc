"""Scoped offline package work for the image gate; reviewed 12 November 2026.

The maintained package builder still executes its eight assertions and seventeen
commands. Every command is directly owned here, with the image parent's shared
budgets reserved before spawn. Importing starts no work or configuration reads.
"""

from __future__ import annotations

import copy
import math
import os
import signal
import stat
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import p3_package_check as packages
from p3_document_evidence import (
    MAX_CAPTURE,
    MAX_CHILDREN,
    MAX_STREAM,
    decode,
    json_bytes,
    natural,
    private_directory,
    read_private,
    write_private,
)
from p3_document_evidence import (
    GateError as EvidenceError,
)

from harness.process_control import (
    OwnedProcess,
    ProcessControlError,
    ProcessResult,
    ProcessTimeout,
    Termination,
)

OFFLINE_STAGES = frozenset(
    {
        "build_p1",
        "build_p3",
        "rebuild_p3",
        "export",
        "install",
        "imports",
        "types",
        "baseline",
        "node_build",
        "npm_pack",
        "npm_install",
        "node_types",
        "node_example",
    }
)
OFFLINE_BASE_KEYS = frozenset(
    {
        "PATH",
        "LANG",
        "COREPACK_ENABLE_NETWORK",
        "COREPACK_HOME",
        "UV_PYTHON_DOWNLOADS",
        "UV_NO_PROGRESS",
        "PYTHONDONTWRITEBYTECODE",
    }
)


GROUP_READY_SECONDS = 2.0
GROUP_CLOSE_SECONDS = 3.0
GROUP_POLL_SECONDS = 0.01


def _bounded_seconds(value: float) -> float:
    if type(value) not in (int, float):
        raise ValueError("Invalid group observation deadline")
    try:
        converted = float(value)
    except OverflowError as error:
        raise ValueError("Invalid group observation deadline") from error
    if not math.isfinite(converted) or not 0 < converted <= 300:
        raise ValueError("Invalid group observation deadline")
    return converted


class GroupedOwnedProcess(OwnedProcess):
    """One owned POSIX session, including non-detached compiler descendants.

    The child wrapper establishes its own session before executing trusted argv.
    Its exclusive private marker establishes the exact group even if the leader
    exits before the first parent observation. Cleanup never signals our group or
    an arbitrary caller-supplied PID. A descendant that independently detaches is
    outside this selected compiler fixture contract, not silently claimed closed.
    """

    def __init__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        output_directory: Path,
        max_output_bytes: int = 65_536,
        final_deadline: float | None = None,
    ) -> None:
        if (
            isinstance(argv, (str, bytes))
            or not argv
            or any(type(v) is not str or not v or "\0" in v for v in argv)
            or (
                final_deadline is not None
                and (
                    type(final_deadline) not in (int, float)
                    or not math.isfinite(final_deadline)
                    or final_deadline <= time.monotonic()
                )
            )
        ):
            raise ValueError("Invalid grouped process command")
        self._group_marker = Path(output_directory).absolute() / "process-group.pid"
        self._group_verified = False
        self._group_settled = False
        self._group_final_deadline = final_deadline
        wrapper = (
            "import os,sys;os.umask(0o077);os.setsid();p=sys.argv[1]+'.pending';"
            "fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);"
            "os.write(fd,(str(os.getpid())+'\\n').encode('ascii'));os.close(fd);"
            "os.link(p,sys.argv[1],follow_symlinks=False);os.unlink(p);"
            "os.execv(sys.argv[2],sys.argv[2:])"
        )
        # No fallible group observation after spawn: the caller first retains
        # this owner, then wait/close confirms the child-created group marker.
        super().__init__(
            [sys.executable, "-I", "-c", wrapper, str(self._group_marker), *argv],
            cwd=cwd,
            env=env,
            output_directory=output_directory,
            max_output_bytes=max_output_bytes,
        )

    @property
    def returncode(self) -> int | None:
        result = super().returncode
        if type(result) is int and not self._group_settled:
            # A reaped leader alone says nothing about its retained descendants.
            self.cleanup_failed = True
        return result

    @property
    def group_settled(self) -> bool:
        return self._group_settled

    def _group_deadline(self, seconds: float) -> float:
        result = time.monotonic() + seconds
        if self._group_final_deadline is not None:
            result = min(result, self._group_final_deadline)
        return result

    def _confirm_group(self, deadline: float) -> None:
        if self._group_verified:
            return
        while True:
            if self._group_marker.exists() or self._group_marker.is_symlink():
                # link() publishes complete bytes before unlinking the private
                # pending name. Wait only for that exact same-inode two-link
                # publication window; never accept a linked marker as ready.
                info = self._group_marker.lstat()
                pending = self._group_marker.with_name(self._group_marker.name + ".pending")
                try:
                    other = pending.lstat()
                except FileNotFoundError:
                    other = None
                if (
                    other is not None
                    and stat.S_ISREG(info.st_mode)
                    and stat.S_ISREG(other.st_mode)
                    and info.st_uid == other.st_uid == os.getuid()
                    and stat.S_IMODE(info.st_mode) == stat.S_IMODE(other.st_mode) == 0o600
                    and info.st_nlink == other.st_nlink == 2
                    and (info.st_dev, info.st_ino) == (other.st_dev, other.st_ino)
                ):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ProcessTimeout("Owned process group publication remains incomplete")
                    self._drain(min(GROUP_POLL_SECONDS, remaining))
                    continue
                try:
                    raw = read_private(self._group_marker, 32)
                except EvidenceError as error:
                    raise ProcessControlError("Owned process group marker is invalid") from error
                if raw != f"{self.pid}\n".encode("ascii") or self.pid == os.getpgrp():
                    raise ProcessControlError("Owned process group identity is invalid")
                try:
                    actual = os.getpgid(self.pid)
                except ProcessLookupError:
                    actual = self.pid  # The verified marker precedes exec and any fork.
                if actual != self.pid:
                    raise ProcessControlError("Owned process group identity is invalid")
                self._group_verified = True
                return
            if self.returncode is not None:
                # No marker means no trusted program has yet been exec'd/forked.
                self._group_settled = True
                raise ProcessControlError("Owned process group did not initialize")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProcessTimeout("Owned process group did not initialize")
            self._drain(min(GROUP_POLL_SECONDS, remaining))

    def _group_exists(self) -> bool:
        if not self._group_verified or self.pid <= 1 or self.pid == os.getpgrp():
            raise ProcessControlError("Owned process group identity is unavailable")
        try:
            os.killpg(self.pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            # Darwin can report EPERM for an existing zombie-only group. It
            # remains unresolved until an actual later ESRCH proves absence.
            return True
        return True

    def _settle_group(self, deadline: float) -> None:
        if self._group_settled:
            return
        self._confirm_group(deadline)
        _ = self.returncode  # Reap an already-dead leader before probing its group.
        if self._group_exists():
            # Only the verified, self-created child session may receive a signal.
            try:
                os.killpg(self.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                # EPERM never means settled: the loop still requires ESRCH.
                pass
        while True:
            parent = self.returncode  # poll reaps our direct child as well.
            if type(parent) is int and not self._group_exists():
                self._group_settled = True
                self.cleanup_failed = False
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProcessTimeout("Owned process group cleanup remains incomplete")
            time.sleep(min(GROUP_POLL_SECONDS, remaining))

    def wait(self, *, timeout: float) -> ProcessResult:
        deadline = time.monotonic() + _bounded_seconds(timeout)
        while True:
            self._drain()
            result = self.returncode
            if result is not None:
                # Even a successful compiler parent cannot leave helpers behind.
                self._settle_group(min(deadline, self._group_deadline(GROUP_CLOSE_SECONDS)))
                if not self._selector.get_map():
                    return ProcessResult(self.pid, result)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProcessTimeout("Owned process did not finish before its deadline")
            self._drain(min(GROUP_POLL_SECONDS, remaining))

    def _reap_killed(self, timeout: float) -> Termination:
        if self._group_final_deadline is not None:
            remaining = self._group_final_deadline - time.monotonic()
            if remaining <= 0:
                # Even an exhausted observer still attempts the owned kill, but
                # cannot restart the inherited fixed three-second reap budget.
                assert self._process is not None
                if self.returncode is None:
                    try:
                        self._process.kill()
                    except ProcessLookupError:
                        pass
                raise ProcessTimeout("Owned process reap exceeded its final deadline")
            timeout = min(timeout, remaining)
        return super()._reap_killed(timeout)

    def close(self) -> None:
        first: BaseException | None = None
        try:
            if self._process is not None:
                self._settle_group(self._group_deadline(GROUP_CLOSE_SECONDS))
        except BaseException as error:  # noqa: BLE001 - direct owner still needs cleanup.
            first = error
        try:
            super().close()
        except BaseException as error:  # noqa: BLE001 - preserve the first cleanup error.
            if first is None:
                first = error
        if first is not None or (
            self._process is not None
            and (type(self.returncode) is not int or not self._group_settled)
        ):
            self.cleanup_failed = True
            raise first or ProcessControlError("Owned process group cleanup remains incomplete")
        self.cleanup_failed = False


class ScopedPackageRun(packages.PackageRun):
    """Only offline work; the caller retains this owner through actual cleanup.

    The three outer callbacks return direct-parent values, excluding this owner.
    The caller must also include this owner's live reservations in its own starts.
    """

    def __init__(
        self,
        root: Path,
        report: Path,
        *,
        outer_children: Callable[[], int],
        outer_capture: Callable[[], int],
        outer_reservations: Callable[[], int],
        deadline: float,
        final_deadline: float,
    ) -> None:
        if (
            not all(callable(v) for v in (outer_children, outer_capture, outer_reservations))
            or type(deadline) not in (int, float)
            or type(final_deadline) not in (int, float)
            or not math.isfinite(deadline)
            or not math.isfinite(final_deadline)
            or not time.monotonic() < deadline <= final_deadline
        ):
            raise packages.GateError("child_budget")
        self._outer_children = outer_children
        self._outer_capture = outer_capture
        self._outer_reservations = outer_reservations
        self.commands = 0
        self.captured = 0
        self.reservations = {}
        self._global_budget()  # Fail malformed budgets before allocating any owned work.
        private_directory(report.parent)
        if any(
            p.exists() or p.is_symlink()
            for p in (report, report.with_name(report.stem + "-artifacts"))
        ):
            raise packages.GateError("report_exists")
        self.primary_failure: BaseException | None = None
        self.cleanup_failure: BaseException | None = None
        self._successful: dict[str, Any] | None = None
        super().__init__(root, report)
        self.deadline = min(self.deadline, deadline)
        self.final_deadline = min(self.final_deadline, final_deadline)
        # This is the unchanged, closed offline package profile, not a fixture role.
        self.base["COREPACK_HOME"] = "/private/tmp/livekit-pinned-corepack"

    def _global_budget(self) -> tuple[int, int]:
        outer = (self._outer_children(), self._outer_capture(), self._outer_reservations())
        if any(not natural(value) for value in outer):
            raise packages.GateError("child_budget")
        children = outer[0] + self.commands
        spent_or_reserved = outer[1] + outer[2] + self.captured + sum(self.reservations.values())
        if children > MAX_CHILDREN or spent_or_reserved > MAX_CAPTURE:
            raise packages.GateError("child_budget")
        return children, MAX_CAPTURE - spent_or_reserved

    def start(
        self,
        argv: list[str | Path],
        *,
        stage: str,
        cwd: Path | None = None,
        environment: dict[str, str] | None = None,
        cleanup: bool = False,
    ) -> OwnedProcess:
        children, available = self._global_budget()
        if type(stage) is not str or stage not in OFFLINE_STAGES or children >= MAX_CHILDREN:
            raise packages.GateError("child_budget")
        self.remaining(cleanup=cleanup)
        env = self.base if environment is None else environment
        if (
            type(env) is not dict
            or env != self.base
            or set(env) != OFFLINE_BASE_KEYS
            or any(
                type(k) is not str or type(v) is not str or not v or "\0" in v
                for k, v in env.items()
            )
            or env["COREPACK_ENABLE_NETWORK"] != "0"
            or env["UV_PYTHON_DOWNLOADS"] != "never"
            or env["PYTHONDONTWRITEBYTECODE"] != "1"
        ):
            raise packages.GateError("invalid_input")
        limit = min(MAX_STREAM, available // 2)
        if limit < 1:
            raise packages.GateError("child_budget")
        self.commands += 1
        self.stage = stage
        output = self.retained / "commands" / f"{self.commands:02d}-{stage}"
        private_directory(output.parent)
        child = GroupedOwnedProcess(
            [str(v) for v in argv],
            cwd=cwd or self.work,
            env=dict(env),
            output_directory=output,
            max_output_bytes=limit,
            final_deadline=self.final_deadline,
        )
        self.children.append(child)
        self.outputs[child.pid] = output
        self.reservations[child.pid] = 2 * limit
        return child

    def capture(self, child: OwnedProcess) -> tuple[bytes, bytes]:
        self._global_budget()
        directory = self.outputs[child.pid]
        try:
            output = tuple(
                read_private(directory / name, MAX_STREAM, empty=True)
                for name in ("stdout.bin", "stderr.bin")
            )
        except EvidenceError as error:
            raise packages.GateError("retention_failed") from error
        # A false close request must not release a live child's reservation.
        if type(child.returncode) is not int or child.cleanup_failed:
            return output[0], output[1]
        captured = super().capture(child)
        self._global_budget()
        return captured

    def offline(self) -> dict[str, str]:
        try:
            return super().offline()
        except BaseException as error:
            self.primary_failure = error
            raise

    def lab(self) -> None:
        raise packages.GateError("invalid_input")

    def cleanup_resources(self) -> None:
        try:
            super().cleanup_resources()
        except BaseException as error:  # noqa: BLE001 - cleanup cannot replace the original failure.
            self.cleanup_failure = error
            if self.primary_failure is None:
                self.primary_failure = error
            raise self.primary_failure

    def successful_report(self) -> dict[str, Any]:
        """Commit a validated original offline report only after actual cleanup."""
        if self._successful is not None:
            packages.validate_retained_index(
                self.retained, self._successful["retained_index_sha256"]
            )
            if read_private(self.report) != json_bytes(self._successful):
                raise packages.GateError("retention_failed")
            return copy.deepcopy(self._successful)
        if (
            self.primary_failure is not None
            or self.cleanup_failure is not None
            or self.passed != set(packages.OFFLINE_CASES)
            or self.commands != 17
            or len(self.children) != 17
            or not self.children_settled()
            or any(child.returncode != 0 for child in self.children)
            or self.work.exists()
            or self.lab_started
            or self.lab_terminations != 0
            or self.proofs
        ):
            raise packages.GateError("invalid_report")
        self._global_budget()
        snapshot = decode(read_private(self.retained / "source-index.json", 1048576), 1048576)
        if self.source_index() != snapshot:
            raise packages.GateError("invalid_artifact")
        index_sha = self.retained_index()
        packages.validate_retained_index(self.retained, index_sha)
        report: dict[str, Any] = {
            "schema_version": 1,
            "status": "passed",
            "mode": "offline",
            "tests": 8,
            "passed": 8,
            "errors": 0,
            "failures": 0,
            "skipped": 0,
            "cleanup_complete": True,
            "provider_calls": False,
            "authority_runtime_changes": False,
            "full_charter_release_claimed": False,
            "offline_assertions": 8,
            "lab_assertions": 0,
            "child_terminations": 0,
            "duration_seconds": time.monotonic() - self.started,
            "child_commands": 17,
            "case_results": [
                {"name": name, "status": "passed", "code": "ok"} for name in packages.OFFLINE_CASES
            ],
            "artifacts": self.artifacts,
            "proofs": {},
            "node_version": "24.22.2",
            "python_version": "3.14.10",
            "platform": "darwin_arm64",
            "retained_index_sha256": index_sha,
        }
        raw = json_bytes(report)
        packages.validated_report(raw)
        write_private(self.report, raw)
        self._successful = copy.deepcopy(report)
        return copy.deepcopy(report)
