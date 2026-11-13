"""Bounded protocol for prerequisite-aware Python acceptance commands.

This tooling knows report semantics and process ownership, never product setup.
Raw child capture and unvalidated reports remain private and are removed on exit.
"""

from __future__ import annotations

import json
import math
import os
import stat
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .process_control import (
    OwnedProcess,
    ProcessControlError,
    ProcessOutputLimit,
    ProcessResult,
    ProcessTimeout,
)

FIELDS = frozenset(
    {
        "schemaVersion",
        "caseId",
        "mode",
        "status",
        "testCount",
        "skippedCount",
        "failureCount",
        "errorCount",
        "durationSeconds",
        "code",
    }
)
CODES = frozenset(
    {
        "passed",
        "setup_required",
        "mapping_invalid",
        "test_error",
        "assertion_failed",
        "skipped",
        "no_tests",
    }
)
MAX_REPORT_BYTES = 65536


class ReportRunnerError(ValueError):
    """An external report did not satisfy its closed acceptance protocol."""


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReportRunnerError("Duplicate report field")
        result[key] = value
    return result


def _constant(_value: str) -> None:
    raise ReportRunnerError("Nonfinite report value")


def read_report(
    path: Path, case_id: str, expected_mode: str, *, max_duration: int = 300
) -> dict[str, Any]:
    """Read one bounded regular nonsymlink report, then validate every field."""
    if type(max_duration) is not int or not 1 <= max_duration <= 900:
        raise ReportRunnerError("Unsupported report duration bound")
    if type(expected_mode) is not str or expected_mode not in {"offline", "lab", "live"}:
        raise ReportRunnerError("Unsupported expected execution mode")
    try:
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
            observed = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(observed.st_mode)
                or observed.st_nlink != 1
                or observed.st_size > MAX_REPORT_BYTES
            ):
                raise ReportRunnerError("Invalid report file")
            raw = stream.read(MAX_REPORT_BYTES + 1)
        if not raw or len(raw) > MAX_REPORT_BYTES:
            raise ReportRunnerError("Invalid report length")
        value = json.loads(raw, object_pairs_hook=_object, parse_constant=_constant)
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ) as error:
        raise ReportRunnerError("Required report unavailable or invalid") from error
    if (
        type(value) is not dict
        or set(value) != FIELDS
        or type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or value["caseId"] != case_id
        or type(value["caseId"]) is not str
        or type(value["mode"]) is not str
        or value["mode"] != expected_mode
        or type(value["status"]) is not str
        or value["status"] not in {"passed", "failed", "incomplete"}
        or type(value["code"]) is not str
        or value["code"] not in CODES
    ):
        raise ReportRunnerError("Report envelope mismatch")
    for field in ("testCount", "skippedCount", "failureCount", "errorCount"):
        if type(value[field]) is not int or not 0 <= value[field] <= 100000:
            raise ReportRunnerError("Invalid report count")
    duration = value["durationSeconds"]
    if (
        type(duration) not in {int, float}
        or not 0 <= duration <= max_duration
        or not math.isfinite(duration)
    ):
        raise ReportRunnerError("Invalid report duration")
    if value["status"] == "passed" and (
        value["code"] != "passed"
        or value["testCount"] == 0
        or value["skippedCount"]
        or value["failureCount"]
        or value["errorCount"]
    ):
        raise ReportRunnerError("Success lacks complete required assertions")
    if value["status"] != "passed" and value["code"] == "passed":
        raise ReportRunnerError("Contradictory report status")
    return dict(value)


@dataclass(frozen=True)
class ReportOutcome:
    status: str
    exit_code: int
    runner_exit_code: int | None
    test_count: int | None
    skipped_count: int
    command: list[str]
    report: dict[str, Any] | None
    diagnostic_code: str


def wait_owned(
    child: OwnedProcess, timeout: int, *, clock: Callable[[], float] = time.monotonic
) -> ProcessResult:
    """Use finite observations without extending the original infrastructure deadline."""
    if type(timeout) is not int or not 1 <= timeout <= 900:
        raise ReportRunnerError("Unsupported infrastructure duration bound")
    deadline = clock() + timeout
    while True:
        remaining = deadline - clock()
        if remaining <= 0:
            raise ProcessTimeout("Owned infrastructure runner exceeded its original deadline")
        try:
            return child.wait(timeout=min(300.0, remaining))
        except ProcessTimeout:
            # A chunk timeout is an observation only. The context still owns the
            # running child; only the final deadline unwinds and closes it.
            if clock() >= deadline:
                raise


def execute_report(
    root: Path,
    directory: Path,
    script: Path,
    case_id: str,
    timeout: int,
    *,
    expected_mode: str,
    infrastructure: bool = False,
) -> ReportOutcome:
    """Run trusted argv with a finite owned lifetime; expose only validated data."""
    report: dict[str, Any] | None = None
    runner_exit: int | None = None
    status, exit_code, code = "runner_error", 1, "runner_unavailable"
    command: list[str] = []
    if (
        type(infrastructure) is not bool
        or type(timeout) is not int
        or not 1 <= timeout <= (900 if infrastructure else 300)
        or infrastructure
        and expected_mode not in {"lab", "live"}
    ):
        return ReportOutcome(status, exit_code, runner_exit, None, 0, command, None, code)
    try:
        with tempfile.TemporaryDirectory(prefix="private-report-", dir=directory) as temp:
            temporary = Path(temp)
            result_path = temporary / "result.json"
            command = [
                sys.executable,
                str(script),
                "--case",
                case_id,
                "--report",
                str(result_path),
            ]
            try:
                with OwnedProcess(
                    command,
                    cwd=root,
                    env=dict(os.environ),
                    output_directory=temporary / "capture",
                    max_output_bytes=65536,
                ) as child:
                    observed = (
                        wait_owned(child, timeout)
                        if infrastructure
                        else child.wait(timeout=timeout)
                    )
                    runner_exit = observed.returncode
                if child.cleanup_failed:
                    raise ProcessControlError("Owned runner cleanup incomplete")
            except ProcessTimeout:
                status, exit_code, code = "timed_out", 124, "runner_timeout"
            except ProcessOutputLimit:
                status, exit_code, code = "runner_error", 1, "runner_output_limit"
            else:
                try:
                    report = read_report(
                        result_path,
                        case_id,
                        expected_mode,
                        max_duration=timeout if infrastructure else 300,
                    )
                except ReportRunnerError:
                    status, exit_code, code = "runner_error", 1, "runner_report_invalid"
                else:
                    if runner_exit == 0 and report["status"] == "passed":
                        status, exit_code, code = "passed", 0, "passed"
                    elif runner_exit == 2 and report["status"] == "incomplete":
                        status, exit_code, code = "incomplete", 2, report["code"]
                    else:
                        status, exit_code, code = "failed", 1, "runner_failure"
    except (OSError, ValueError, ProcessControlError):
        status, exit_code, code = "runner_error", 1, "runner_unavailable"
    return ReportOutcome(
        status,
        exit_code,
        runner_exit,
        None if report is None else report["testCount"],
        0 if report is None else report["skippedCount"],
        command,
        report,
        code,
    )
