"""Explicit durable P3 metadata projection gate; no providers, scheduler or source ACK.

Private PostgreSQL settings enter role-separated child environments. All schemas
and process barriers are fresh and owned; bounded raw capture is ephemeral.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import secrets
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p3_coordinator_check as core

from harness.process_control import FileBarrier, OwnedProcess, ProcessControlError

ROOT = Path(__file__).resolve().parents[2]
DEADLINE_SECONDS = 180.0
MAX_REPORT_BYTES = 32768
MODE = "local_synthetic_p3_result_projection"
CASE_NAMES = (
    "v3_history_adopted_stable_source",
    "invalid_result_quarantined",
    "valid_result_after_quarantine",
    "precommit_kill_fresh_resume",
    "concurrent_batch_original_replay",
    "case_only_change_preserves_asof",
    "postcommit_kill_fresh_original",
    "retention_capacity_no_advance",
    "foreign_scope_zero_disclosure",
    "source_uuid_mismatch_rejected",
    "independent_source_projection_zero_intents",
    "cleanup_ownership",
)
OWNER_MODES = frozenset({"install", "upgrade", "locks", "owner-check", "cleanup"})
COMMON = frozenset(
    {
        "P3_PROJECT_WORK_SCHEMA",
        "P3_PROJECT_CASE_SCHEMA",
        "P3_PROJECT_SCHEMA",
        "P3_PROJECT_DIRECTORY",
    }
)
RUNTIME = COMMON | {"P3_PROJECT_TOKEN"}
MODE_KEYS = {
    "install": COMMON,
    "seed": RUNTIME,
    "upgrade": COMMON,
    "crash-before": RUNTIME | {"P3_PROJECT_BARRIER"},
    "resume": RUNTIME,
    "race-a": RUNTIME | {"P3_PROJECT_BARRIER"},
    "race-b": RUNTIME,
    "locks": COMMON,
    "crash-after": RUNTIME | {"P3_PROJECT_BARRIER"},
    "verify": RUNTIME,
    "owner-check": COMMON,
    "cleanup": COMMON,
}
GateError = core.GateError


def validate_child_environment(environment: dict[str, str], mode: str) -> None:
    if mode not in MODE_KEYS:
        raise GateError("invalid_child_mode")
    password = "P3_PROJECT_OWNER_PASSWORD" if mode in OWNER_MODES else "P3_PROJECT_RUNTIME_PASSWORD"
    required = {"P3_PROJECT_PG_PORT", password, *MODE_KEYS[mode]}
    if (
        not required <= set(environment)
        or set(environment) - required - core.BASE_ENVIRONMENT_KEYS
        or any(
            type(value) is not str or not value or "\0" in value for value in environment.values()
        )
    ):
        raise GateError("unsafe_child_environment")


def child_environment(
    values: dict[str, str], *, mode: str, context: dict[str, str]
) -> dict[str, str]:
    if mode not in MODE_KEYS:
        raise GateError("invalid_child_mode")
    owner = mode in OWNER_MODES
    password = "P3_PROJECT_OWNER_PASSWORD" if owner else "P3_PROJECT_RUNTIME_PASSWORD"
    try:
        environment = {
            **core.base_environment(),
            "P3_PROJECT_PG_PORT": values["POSTGRES_PORT"],
            password: values["POSTGRES_MIGRATION_PASSWORD" if owner else "POSTGRES_PASSWORD"],
            **{name: context[name] for name in MODE_KEYS[mode]},
        }
    except KeyError:
        raise GateError("missing_setup") from None
    validate_child_environment(environment, mode)
    return environment


def validated_report(raw: bytes) -> dict[str, Any]:
    value = core.decode(raw)
    fields = {
        "schema_version",
        "status",
        "mode",
        "tests",
        "passed",
        "errors",
        "failures",
        "skipped",
        "duration_seconds",
        "cleanup_complete",
        "child_terminations",
        "case_results",
        "source_authority",
        "projection_authority",
        "provider_calls",
    }
    if set(value) != fields:
        raise GateError("invalid_report")
    for name in (
        "schema_version",
        "tests",
        "passed",
        "errors",
        "failures",
        "skipped",
        "child_terminations",
    ):
        if type(value[name]) is not int:
            raise GateError("invalid_report")
    duration = value["duration_seconds"]
    if (
        value["schema_version"] != 1
        or value["status"] != "passed"
        or value["mode"] != MODE
        or value["tests"] != len(CASE_NAMES)
        or value["passed"] != len(CASE_NAMES)
        or any(value[name] != 0 for name in ("errors", "failures", "skipped"))
        or value["child_terminations"] != 2
        or value["cleanup_complete"] is not True
        or type(duration) not in (int, float)
        or not 0 < duration <= DEADLINE_SECONDS
        or not math.isfinite(duration)
        or value["provider_calls"] is not False
        or value["source_authority"] != "actual_p1_work_v4_result_only_feed"
        or value["projection_authority"] != "asof_metadata_no_execution_delivery_or_action"
        or value["case_results"]
        != [{"name": name, "status": "passed", "code": "ok"} for name in CASE_NAMES]
    ):
        raise GateError("invalid_report")
    return value


def report_target(root: Path, path: Path) -> Path:
    target = (path if path.is_absolute() else root / path).absolute()
    if ".." in target.parts or not target.is_relative_to(root / ".local/validation/p3-projection"):
        raise GateError("unsafe_evidence_path")
    core.private_directory(target.parent)
    if target.exists() or target.is_symlink():
        raise GateError("existing_report")
    return target


def retain_report(root: Path, target: Path, report: dict[str, Any]) -> None:
    path = report_target(root, target)
    raw = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
    if len(raw) > MAX_REPORT_BYTES:
        raise GateError("invalid_report")
    with os.fdopen(
        os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb"
    ) as stream:
        stream.write(raw)


def checked_child(
    child: OwnedProcess,
    *,
    output: Path,
    limit: int,
    budget: core.CaptureBudget,
    deadline: float,
    mode: str,
) -> dict[str, Any]:
    result = child.wait(timeout=core.remaining(deadline))
    stdout, stderr = budget.read(output, limit)
    if child.cleanup_failed or child.returncode is None:
        raise GateError("cleanup_incomplete")
    if result.returncode != 0 or stderr:
        raise GateError("runner_failed_" + mode)
    value = core.decode(stdout)
    if value.get("status") != "passed":
        raise GateError("case_failed")
    return value


def run_child(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    output: Path,
    deadline: float,
    budget: core.CaptureBudget,
) -> dict[str, Any]:
    validate_child_environment(environment, command[-1])
    limit = budget.reserve(8192)
    with OwnedProcess(
        command, cwd=cwd, env=environment, output_directory=output, max_output_bytes=limit
    ) as child:
        return checked_child(
            child, output=output, limit=limit, budget=budget, deadline=deadline, mode=command[-1]
        )


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    started = time.monotonic()
    deadline = started + DEADLINE_SECONDS
    work_deadline = deadline - 15
    target = args.report or Path(".local/validation/p3-projection/" + uuid4().hex + ".json")
    cleanup_complete = False
    try:
        report_target(root, target)
        setup = core.load_setup(root)
        try:
            values = setup.load_settings()
        except setup.SetupError:
            raise GateError("missing_setup") from None
        cases = root / "projects/delegation-reliability/tests/pg_projection_cases.py"
        interpreter = root / ".venv/bin/python"
        if not all(p.is_file() for p in (cases, interpreter)):
            raise GateError("missing_setup")
        scratch = root / ".local/p3-projection-check"
        core.private_directory(scratch)
        with tempfile.TemporaryDirectory(prefix="run-", dir=scratch) as temporary:
            work = Path(temporary)
            budget = core.CaptureBudget()
            context = {
                "P3_PROJECT_WORK_SCHEMA": "p1_work_projection_" + uuid4().hex,
                "P3_PROJECT_CASE_SCHEMA": "p3_completion_" + uuid4().hex,
                "P3_PROJECT_SCHEMA": "p3_projection_" + uuid4().hex,
                "P3_PROJECT_TOKEN": secrets.token_urlsafe(32),
                "P3_PROJECT_DIRECTORY": str(work),
            }
            command = [str(interpreter), "-I", str(cases)]

            def call(mode: str) -> dict[str, Any]:
                return run_child(
                    [*command, mode],
                    cwd=work,
                    environment=child_environment(values, mode=mode, context=context),
                    output=work / mode,
                    deadline=deadline if mode == "cleanup" else work_deadline,
                    budget=budget,
                )

            def expect(mode: str, expected: dict[str, Any]) -> None:
                if call(mode) != {"status": "passed", **expected}:
                    raise GateError("invalid_report")

            def kill_at(mode: str, name: str) -> None:
                barrier = FileBarrier(work, name)
                context["P3_PROJECT_BARRIER"] = str(work / (name + ".reached"))
                environment = child_environment(values, mode=mode, context=context)
                limit = budget.reserve(8192)
                with OwnedProcess(
                    [*command, mode],
                    cwd=work,
                    env=environment,
                    output_directory=work / mode,
                    max_output_bytes=limit,
                ) as child:
                    child.wait_for_barrier(barrier, timeout=min(15, core.remaining(work_deadline)))
                    termination = child.kill(timeout=min(3, core.remaining(work_deadline)))
                stdout, stderr = budget.read(work / mode, limit)
                if (
                    child.cleanup_failed
                    or not termination.killed
                    or termination.returncode != -9
                    or stdout
                    or stderr
                ):
                    raise GateError("crash_not_observed")

            try:
                expect("install", {"work_version": 3, "case_version": 4})
                expect("seed", {"results": 4})
                expect(
                    "upgrade",
                    {"work_version": 4, "projection_version": 1, "cases": [CASE_NAMES[0]]},
                )
                kill_at("crash-before", "before_commit")
                expect(
                    "resume",
                    {"cases": [CASE_NAMES[1], CASE_NAMES[2], CASE_NAMES[3], CASE_NAMES[5]]},
                )
                barrier = FileBarrier(work, "race_commit")
                context["P3_PROJECT_BARRIER"] = str(work / "race_commit.reached")
                first_limit = budget.reserve(8192)
                second_limit = budget.reserve(8192)
                with OwnedProcess(
                    [*command, "race-a"],
                    cwd=work,
                    env=child_environment(values, mode="race-a", context=context),
                    output_directory=work / "race-a",
                    max_output_bytes=first_limit,
                ) as first:
                    first.wait_for_barrier(barrier, timeout=min(15, core.remaining(work_deadline)))
                    with OwnedProcess(
                        [*command, "race-b"],
                        cwd=work,
                        env=child_environment(values, mode="race-b", context=context),
                        output_directory=work / "race-b",
                        max_output_bytes=second_limit,
                    ) as second:
                        expect("locks", {"blocked": True})
                        first.release_barrier(barrier)
                        a = checked_child(
                            first,
                            output=work / "race-a",
                            limit=first_limit,
                            budget=budget,
                            deadline=work_deadline,
                            mode="race-a",
                        )
                        b = checked_child(
                            second,
                            output=work / "race-b",
                            limit=second_limit,
                            budget=budget,
                            deadline=work_deadline,
                            mode="race-b",
                        )
                        if a != {"status": "passed", "cases": []} or b != {
                            "status": "passed",
                            "cases": [CASE_NAMES[4]],
                        }:
                            raise GateError("invalid_report")
                kill_at("crash-after", "after_commit")
                expect("verify", {"cases": list(CASE_NAMES[6:10])})
                expect("owner-check", {"cases": [CASE_NAMES[10]]})
            finally:
                original = sys.exception()
                try:
                    cleanup_complete = call("cleanup") == {
                        "status": "passed",
                        "schemas_removed": True,
                    }
                except Exception:  # Preserve the first failure and report incomplete cleanup.
                    cleanup_complete = False
                    if original is None:
                        raise
            if not cleanup_complete:
                raise GateError("cleanup_incomplete")
            report = validated_report(
                json.dumps(
                    {
                        "schema_version": 1,
                        "status": "passed",
                        "mode": MODE,
                        "tests": len(CASE_NAMES),
                        "passed": len(CASE_NAMES),
                        "errors": 0,
                        "failures": 0,
                        "skipped": 0,
                        "duration_seconds": time.monotonic() - started,
                        "cleanup_complete": True,
                        "child_terminations": 2,
                        "case_results": [
                            {"name": name, "status": "passed", "code": "ok"} for name in CASE_NAMES
                        ],
                        "source_authority": "actual_p1_work_v4_result_only_feed",
                        "projection_authority": "asof_metadata_no_execution_delivery_or_action",
                        "provider_calls": False,
                    }
                ).encode()
            )
        retain_report(root, target, report)
        print(json.dumps(report, sort_keys=True))
        return 0
    except GateError as error:
        code = error.code
    except ProcessControlError:
        code = "runner_failed"
    except Exception:  # noqa: BLE001 - private dependency exceptions never enter retained evidence
        code = "gate_failed"
    failure = {
        "schema_version": 1,
        "status": "failed",
        "mode": MODE,
        "code": code,
        "duration_seconds": time.monotonic() - started,
        "cleanup_complete": cleanup_complete,
    }
    try:
        retain_report(root, target, failure)
    except (GateError, OSError):
        pass
    print(json.dumps(failure, sort_keys=True))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
