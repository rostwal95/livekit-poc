"""Explicit P3 applicability/retained-display gate; no provider calls or source ACK.

Private PostgreSQL settings enter role-separated child environments. All schemas
and process barriers are fresh and owned; bounded raw capture is ephemeral.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import secrets
import stat
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p3_coordinator_check as core

from harness.process_control import FileBarrier, OwnedProcess, ProcessControlError

ROOT = Path(__file__).resolve().parents[2]
DEADLINE_SECONDS = 180.0
MAX_REPORT_BYTES = 32768
MODE = "local_synthetic_p3_applicability_refresh"
CASE_NAMES = (
    "projection_v3_nonempty_upgrade_preserves_v2",
    "upgrade_precommit_kill_repeat",
    "populated_refresh_tombstone_backup_restore",
    "late_a_outdated_valid_b_guarded_effect",
    "work_cancel_invalidates_preserves_receipt",
    "case_cancel_monotonic_invalidation",
    "local_deadline_asof_latch",
    "historical_lease_expiry_not_postcommit_invalidation",
    "historical_attempt_exact_identity",
    "case_unavailable_then_recovery",
    "concurrent_local_cas_no_regression",
    "refresh_precommit_kill_resume",
    "refresh_postcommit_kill_original_replay",
    "hidden_display_preserves_replay_truth",
    "hidden_unknown_later_result_progress",
    "scope_source_binding_zero_refresh",
    "retained_capacity_original_replay",
    "independent_identity_reconciliation_cleanup",
)
OWNER_MODES = frozenset(
    {"cleanup", "install", "locks", "owner-check", "upgrade", "restore", "upgrade-crash"}
)
COMMON = frozenset(
    {
        "P3_REFRESH_CASE_SCHEMA",
        "P3_REFRESH_DIRECTORY",
        "P3_REFRESH_WORK_SCHEMA",
        "P3_REFRESH_SCHEMA",
    }
)
RUNTIME = COMMON | {"P3_REFRESH_TOKEN"}
MODE_KEYS = {
    "install": COMMON,
    "seed": RUNTIME,
    "upgrade-crash": COMMON | {"P3_REFRESH_BARRIER"},
    "upgrade": COMMON,
    "refresh-before": RUNTIME | {"P3_REFRESH_BARRIER"},
    "resume": RUNTIME,
    "refresh-after": RUNTIME | {"P3_REFRESH_BARRIER"},
    "replay": RUNTIME,
    "race-a": RUNTIME | {"P3_REFRESH_BARRIER"},
    "race-b": RUNTIME,
    "locks": COMMON,
    "classify": RUNTIME,
    "hide-before": RUNTIME | {"P3_REFRESH_BARRIER"},
    "hide-resume": RUNTIME,
    "hide-after": RUNTIME | {"P3_REFRESH_BARRIER"},
    "progress": RUNTIME,
    "restore": COMMON,
    "verify": RUNTIME,
    "owner-check": COMMON,
    "cleanup": COMMON,
}

GateError = core.GateError


def validate_child_environment(environment: dict[str, str], mode: str) -> None:
    if mode not in MODE_KEYS:
        raise GateError("invalid_child_mode")
    password = "P3_REFRESH_OWNER_PASSWORD" if mode in OWNER_MODES else "P3_REFRESH_RUNTIME_PASSWORD"
    required = {"P3_REFRESH_PG_PORT", password, *MODE_KEYS[mode]}
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
    password = "P3_REFRESH_OWNER_PASSWORD" if owner else "P3_REFRESH_RUNTIME_PASSWORD"
    try:
        environment = {
            **core.base_environment(),
            "P3_REFRESH_PG_PORT": values["POSTGRES_PORT"],
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
        "applicability_authority",
        "backup_restore",
        "blocking_graphs_observed",
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
        "blocking_graphs_observed",
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
        or value["child_terminations"] != 5
        or value["blocking_graphs_observed"] != 1
        or value["cleanup_complete"] is not True
        or type(duration) not in (int, float)
        or not 0 < duration <= DEADLINE_SECONDS
        or not math.isfinite(duration)
        or value["provider_calls"] is not False
        or value["source_authority"] != "actual_p1_work_v4_existing_delivery_action_and_receiver"
        or value["applicability_authority"]
        != "p3_projection_v3_non_atomic_refresh_and_display_metadata"
        or value["backup_restore"] != "validated_versioned_profile_rows_not_pg_dump"
        or value["case_results"]
        != [{"name": name, "status": "passed", "code": "ok"} for name in CASE_NAMES]
    ):
        raise GateError("invalid_report")
    return value


def exact_child(value: dict[str, Any], expected: dict[str, Any]) -> bool:
    """JSON primitive types are part of the protocol: true never substitutes for 1."""
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ) == json.dumps(expected, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        return False


def report_target(root: Path, path: Path) -> Path:
    target = (path if path.is_absolute() else root / path).absolute()
    if ".." in target.parts or not target.is_relative_to(
        root / ".local/validation/p3-applicability"
    ):
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


def diagnostic_target(root: Path, target: Path) -> Path:
    report = (target if target.is_absolute() else root / target).absolute()
    if ".." in report.parts or not report.is_relative_to(
        root / ".local/validation/p3-applicability"
    ):
        raise GateError("unsafe_evidence_path")
    folder = report.with_name(report.stem + "-captures")
    core.private_directory(folder.parent)
    if folder.exists() or folder.is_symlink():
        raise GateError("existing_diagnostics")
    return folder


def redact_capture(raw: bytes, values: tuple[str, ...]) -> bytes:
    """Filter passed local settings only; no provider configuration is inspected."""
    variants = set()
    for value in values:
        if type(value) is not str or not value or len(value.encode()) > 4096:
            raise GateError("unsafe_redaction")
        variants.add(value.encode())
        variants.add(json.dumps(value, ensure_ascii=True)[1:-1].encode())
    for encoded in sorted(variants, key=len, reverse=True):
        raw = raw.replace(encoded, b"[redacted]")
    for pattern in (
        rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?(?:-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|$)",
        rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{16,}\b",
        rb"\bAKIA[A-Z0-9]{16}\b",
        rb"(?i)\bBearer[ \t]+[A-Za-z0-9._~+/-]+=*",
    ):
        raw = re.sub(pattern, b"[redacted]", raw)
    return raw


def retain_diagnostics(root: Path, target: Path, work: Path, values: tuple[str, ...]) -> str:
    """Only bounded allowlisted stdout/stderr streams; never copy fixture/config files."""
    folder = diagnostic_target(root, target)
    folder.mkdir(mode=0o700)
    entries = []
    total = 0
    for mode in MODE_KEYS:
        output = work / mode
        if output.is_symlink():
            raise GateError("unsafe_capture")
        if not output.exists():
            continue
        if not output.is_dir():
            raise GateError("unsafe_capture")
        for stream in ("stdout", "stderr"):
            source = output / (stream + ".bin")
            if not source.exists() and not source.is_symlink():
                continue
            mode_bits = source.lstat().st_mode
            if not stat.S_ISREG(mode_bits) or stat.S_ISLNK(mode_bits):
                raise GateError("unsafe_capture")
            with os.fdopen(os.open(source, os.O_RDONLY | os.O_NOFOLLOW), "rb") as reader:
                original = reader.read(2049)
            if len(original) > 2048:
                raise GateError("unsafe_capture")
            total += len(original)
            if total > 131072:
                raise GateError("unsafe_capture")
            filtered = redact_capture(original, values)[:2048]
            destination = folder / mode / (stream + ".txt")
            destination.parent.mkdir(mode=0o700, exist_ok=True)
            with os.fdopen(
                os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600),
                "wb",
            ) as writer:
                writer.write(filtered)
            entries.append(
                {
                    "path": str(destination.relative_to(folder)),
                    "original_bytes": len(original),
                    "retained_bytes": len(filtered),
                    "sha256": hashlib.sha256(filtered).hexdigest(),
                }
            )
    if not entries:
        raise GateError("missing_capture")
    manifest = {
        "schema_version": 1,
        "status": "retained_diagnostic_not_qualification",
        "raw_originals_retained": False,
        "provider_files_or_values_read": False,
        "source_capture_bytes": total,
        "streams": entries,
    }
    with os.fdopen(
        os.open(
            folder / "manifest.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        ),
        "w",
    ) as writer:
        json.dump(manifest, writer, sort_keys=True, indent=2)
        writer.write("\n")
    return str(folder.relative_to(root))


@contextmanager
def diagnostic_failure(
    root: Path,
    target: Path,
    work: Path,
    values: tuple[str, ...],
    state: dict[str, Any],
    *,
    enabled: bool,
) -> Iterator[None]:
    try:
        yield
    except BaseException:
        if enabled:
            try:
                state["diagnostics_path"] = retain_diagnostics(root, target, work, values)
                state["diagnostics_retained"] = True
                state["diagnostics_code"] = "retained"
            except Exception:  # noqa: BLE001 - preserve the primary failure
                state["diagnostics_retained"] = False
                state["diagnostics_code"] = "retention_failed"
        raise


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
    limit = budget.reserve(4096)
    with OwnedProcess(
        command, cwd=cwd, env=environment, output_directory=output, max_output_bytes=limit
    ) as child:
        return checked_child(
            child, output=output, limit=limit, budget=budget, deadline=deadline, mode=command[-1]
        )


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--diagnostic",
        action="store_true",
        help="Retain redacted failure captures; this run can never qualify or return success",
    )
    args = parser.parse_args(argv)
    started = time.monotonic()
    deadline = started + DEADLINE_SECONDS
    work_deadline = deadline - 15
    target = args.report or Path(".local/validation/p3-applicability/" + uuid4().hex + ".json")
    cleanup_complete = False
    diagnostic_state: dict[str, Any] = (
        {"diagnostic": True, "diagnostics_retained": False, "diagnostics_code": "not_available"}
        if args.diagnostic
        else {}
    )
    try:
        report_target(root, target)
        if args.diagnostic:
            diagnostic_target(root, target)
        setup = core.load_setup(root)
        try:
            values = setup.load_settings()
        except setup.SetupError:
            raise GateError("missing_setup") from None
        cases = root / "projects/delegation-reliability/tests/pg_applicability_cases.py"
        interpreter = root / ".venv/bin/python"
        if not all(p.is_file() for p in (cases, interpreter)):
            raise GateError("missing_setup")
        scratch = root / ".local/p3-applicability-check"
        core.private_directory(scratch)
        with tempfile.TemporaryDirectory(prefix="run-", dir=scratch) as temporary:
            work = Path(temporary)
            budget = core.CaptureBudget()
            context = {
                "P3_REFRESH_WORK_SCHEMA": "p1_work_applicability_" + uuid4().hex,
                "P3_REFRESH_CASE_SCHEMA": "p3_completion_" + uuid4().hex,
                "P3_REFRESH_SCHEMA": "p3_projection_" + uuid4().hex,
                "P3_REFRESH_TOKEN": secrets.token_urlsafe(32),
                "P3_REFRESH_DIRECTORY": str(work),
            }
            command = [str(interpreter), "-I", str(cases)]

            local_redactions = tuple(
                values[key]
                for key in (
                    "POSTGRES_PASSWORD",
                    "POSTGRES_MIGRATION_PASSWORD",
                    "POSTGRES_ADMIN_PASSWORD",
                    "LOCAL_ACCESS_TOKEN",
                    "LIVEKIT_API_SECRET",
                )
                if key in values
            ) + (context["P3_REFRESH_TOKEN"],)
            with diagnostic_failure(
                root, target, work, local_redactions, diagnostic_state, enabled=args.diagnostic
            ):
                terminations = 0
                blocking_graphs = 0
                seen: set[str] = set()

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
                    if not exact_child(call(mode), {"status": "passed", **expected}):
                        raise GateError("invalid_report")
                    names = expected.get("cases", [])
                    if type(names) is not list or any(
                        type(name) is not str or name not in CASE_NAMES or name in seen
                        for name in names
                    ):
                        raise GateError("invalid_report")
                    seen.update(names)

                def kill_at(mode: str, name: str) -> None:
                    nonlocal terminations
                    barrier = FileBarrier(work, name)
                    context["P3_REFRESH_BARRIER"] = str(work / (name + ".reached"))
                    environment = child_environment(values, mode=mode, context=context)
                    limit = budget.reserve(4096)
                    with OwnedProcess(
                        [*command, mode],
                        cwd=work,
                        env=environment,
                        output_directory=work / mode,
                        max_output_bytes=limit,
                    ) as child:
                        child.wait_for_barrier(
                            barrier, timeout=min(15, core.remaining(work_deadline))
                        )
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
                    terminations += 1

                try:
                    expect("install", {"projection_version": 2})
                    expect(
                        "seed", {"source_results": 8, "projected_results": 8, "old_ack_count": 1}
                    )
                    kill_at("upgrade-crash", "upgrade_commit")
                    expect(
                        "upgrade",
                        {"projection_version": 3, "cases": [CASE_NAMES[0], CASE_NAMES[1]]},
                    )
                    kill_at("refresh-before", "refresh_before")
                    expect("resume", {"cases": [CASE_NAMES[11]]})
                    kill_at("refresh-after", "refresh_after")
                    expect("replay", {"cases": [CASE_NAMES[12]]})
                    barrier = FileBarrier(work, "refresh_race")
                    context["P3_REFRESH_BARRIER"] = str(work / "refresh_race.reached")
                    first_limit, second_limit = budget.reserve(4096), budget.reserve(4096)
                    with OwnedProcess(
                        [*command, "race-a"],
                        cwd=work,
                        env=child_environment(values, mode="race-a", context=context),
                        output_directory=work / "race-a",
                        max_output_bytes=first_limit,
                    ) as first:
                        first.wait_for_barrier(
                            barrier, timeout=min(15, core.remaining(work_deadline))
                        )
                        with OwnedProcess(
                            [*command, "race-b"],
                            cwd=work,
                            env=child_environment(values, mode="race-b", context=context),
                            output_directory=work / "race-b",
                            max_output_bytes=second_limit,
                        ) as second:
                            expect("locks", {"blocked": True, "blocking_graphs": 1})
                            blocking_graphs += 1
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
                            if not exact_child(
                                a, {"status": "passed", "revision": 3}
                            ) or not exact_child(
                                b, {"status": "passed", "cases": [CASE_NAMES[10]]}
                            ):
                                raise GateError("invalid_report")
                            if CASE_NAMES[10] in seen:
                                raise GateError("invalid_report")
                            seen.add(CASE_NAMES[10])
                    expect("classify", {"cases": [CASE_NAMES[n] for n in (3, 4, 5, 6, 7, 8, 9)]})
                    kill_at("hide-before", "hide_before")
                    expect("hide-resume", {"cases": [CASE_NAMES[13]]})
                    kill_at("hide-after", "hide_after")
                    expect("progress", {"cases": [CASE_NAMES[14]]})
                    expect(
                        "restore",
                        {
                            "cases": [CASE_NAMES[2]],
                            "populated_tables": 8,
                            "profile_rows_restored": True,
                        },
                    )
                    expect(
                        "verify",
                        {
                            "cases": [CASE_NAMES[15], CASE_NAMES[16]],
                            "source_results": 9,
                            "projected_results": 9,
                        },
                    )
                    expect("owner-check", {"cases": [CASE_NAMES[17]], "exact_reconciliation": True})
                    if seen != set(CASE_NAMES):
                        raise GateError("invalid_report")
                finally:
                    original = sys.exception()
                    try:
                        cleanup_complete = exact_child(
                            call("cleanup"), {"status": "passed", "cleanup_complete": True}
                        )
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
                            "child_terminations": terminations,
                            "blocking_graphs_observed": blocking_graphs,
                            "case_results": [
                                {"name": name, "status": "passed", "code": "ok"}
                                for name in CASE_NAMES
                            ],
                            "source_authority": "actual_p1_work_v4_existing_delivery_action_and_receiver",
                            "applicability_authority": "p3_projection_v3_non_atomic_refresh_and_display_metadata",
                            "backup_restore": "validated_versioned_profile_rows_not_pg_dump",
                            "provider_calls": False,
                        }
                    ).encode()
                )
                if args.diagnostic:
                    raise GateError("diagnostic_not_qualification")
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
        **diagnostic_state,
    }
    try:
        retain_report(root, target, failure)
    except (GateError, OSError):
        pass
    print(json.dumps(failure, sort_keys=True))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
