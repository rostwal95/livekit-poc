"""Explicit local P3 acceptance/socket gate; never starts or resets the stack.

Private settings enter only explicit child environments. Installed Python children
use public P1/P3 interfaces; raw bounded capture is deleted before safe retention.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import re
import secrets
import shutil
import stat
import sys
import tempfile
import time
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from harness.process_control import FileBarrier, OwnedProcess, ProcessControlError

DEADLINE_SECONDS = 180.0
MAX_CAPTURE_BYTES = 131072
MAX_REPORT_BYTES = 32768
CASE_NAMES = (
    "immutable_snapshot",
    "scoped_replay_conflict_read",
    "requested_cancel_original_replay",
    "postcommit_ack_reconciliation",
    "misbound_scope_zero_acceptance",
    "fresh_process_original_lookup",
    "after_commit_sigkill_reconciliation",
    "python_typescript_grounded_candidate",
    "live_status_cancel_progress",
    "cleanup_ownership",
)
MODE = "local_synthetic_p3_acceptance_http"


class GateError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__("P3 coordinator qualification did not pass")


def load_setup(root: Path) -> ModuleType:
    name = "p3_coordinator_setup_" + uuid4().hex
    specification = importlib.util.spec_from_file_location(name, root / "local-setup/stack.py")
    if specification is None or specification.loader is None:
        raise GateError("missing_setup")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    try:
        specification.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


def private_directory(path: Path) -> None:
    if ".." in path.parts or any(part.is_symlink() for part in (path, *path.parents)):
        raise GateError("unsafe_evidence_path")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise GateError("unsafe_evidence_path")


BASE_ENVIRONMENT_KEYS = frozenset(
    {
        "PATH",
        "HOME",
        "TMPDIR",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "SYSTEMROOT",
        "__CF_USER_TEXT_ENCODING",
        "NO_COLOR",
        "CI",
    }
)
OWNER_MODES = frozenset({"install", "owner-check", "cleanup"})
MODE_CONTEXT_KEYS = {
    "install": ("P3_CHECK_SCHEMA",),
    "owner-check": ("P3_CHECK_SCHEMA",),
    "cleanup": ("P3_CHECK_SCHEMA", "P3_CHECK_PROFILE_INSTALLED"),
    "exercise": (
        "P3_CHECK_SCHEMA",
        "P3_CHECK_TOKEN",
        "P3_CHECK_SPECIALIST_PORT",
        "P3_CHECK_RELEASE",
    ),
    "verify": ("P3_CHECK_SCHEMA", "P3_CHECK_TOKEN", "P3_CHECK_PRIMARY_SHA256"),
    "crash": (
        "P3_CHECK_SCHEMA",
        "P3_CHECK_TOKEN",
        "P3_CHECK_CRASH_DEADLINE",
        "P3_CHECK_COMMIT_MARKER",
    ),
    "verify-crash": ("P3_CHECK_SCHEMA", "P3_CHECK_TOKEN", "P3_CHECK_CRASH_DEADLINE"),
}


def base_environment() -> dict[str, str]:
    inherited = BASE_ENVIRONMENT_KEYS - {"NO_COLOR", "CI"}
    return {
        **{name: os.environ[name] for name in inherited if name in os.environ},
        "NO_COLOR": "1",
        "CI": "1",
    }


def validate_child_environment(environment: dict[str, str], mode: str) -> None:
    if mode not in MODE_CONTEXT_KEYS:
        raise GateError("invalid_child_mode")
    password = "P3_MIGRATION_PASSWORD" if mode in OWNER_MODES else "P3_RUNTIME_PASSWORD"
    required = {"P3_POSTGRES_PORT", password, *MODE_CONTEXT_KEYS[mode]}
    if (
        not required <= set(environment)
        or set(environment) - required - BASE_ENVIRONMENT_KEYS
        or any(
            type(value) is not str or not value or "\0" in value for value in environment.values()
        )
    ):
        raise GateError("unsafe_child_environment")


def child_environment(
    values: dict[str, str], *, mode: str, context: dict[str, str]
) -> dict[str, str]:
    if mode not in MODE_CONTEXT_KEYS:
        raise GateError("invalid_child_mode")
    owner = mode in OWNER_MODES
    password = "P3_MIGRATION_PASSWORD" if owner else "P3_RUNTIME_PASSWORD"
    selected = "POSTGRES_MIGRATION_PASSWORD" if owner else "POSTGRES_PASSWORD"
    result = {
        **base_environment(),
        "P3_POSTGRES_PORT": values["POSTGRES_PORT"],
        password: values[selected],
        **{name: context[name] for name in MODE_CONTEXT_KEYS[mode]},
    }
    validate_child_environment(result, mode)
    return result


def remaining(deadline: float) -> float:
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise GateError("deadline_exceeded")
    return min(DEADLINE_SECONDS, seconds)


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GateError("invalid_report")
        result[key] = value
    return result


def decode(raw: bytes) -> dict[str, Any]:
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_REPORT_BYTES:
        raise GateError("invalid_report")
    try:
        value = json.loads(raw, object_pairs_hook=unique_object)
    except (ValueError, UnicodeError, RecursionError):
        raise GateError("invalid_report") from None
    if type(value) is not dict:
        raise GateError("invalid_report")
    return value


def supported_node(version: object) -> bool:
    if type(version) is not str or len(version) > 32:
        return False
    match = re.fullmatch(r"(24|26)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version)
    if match is None:
        return False
    major, minor, patch = (int(item) for item in match.groups())
    return major == 24 and (minor, patch) >= (22, 2) or major == 26 and minor >= 13


def validated_report(raw: bytes) -> dict[str, Any]:
    report = decode(raw)
    keys = {
        "schema_version",
        "status",
        "mode",
        "tests",
        "passed",
        "failures",
        "errors",
        "skipped",
        "duration_seconds",
        "cleanup_complete",
        "child_terminations",
        "case_results",
        "node_version",
        "case_authority",
        "invocation_authority",
    }
    if set(report) != keys:
        raise GateError("invalid_report")
    for name in (
        "schema_version",
        "tests",
        "passed",
        "failures",
        "errors",
        "skipped",
        "child_terminations",
    ):
        if type(report[name]) is not int:
            raise GateError("invalid_report")
    duration = report["duration_seconds"]
    if (
        report["schema_version"] != 1
        or report["status"] != "passed"
        or report["mode"] != MODE
        or report["tests"] != len(CASE_NAMES)
        or report["passed"] != len(CASE_NAMES)
        or any(report[key] != 0 for key in ("failures", "errors", "skipped"))
        or report["child_terminations"] != 1
        or report["cleanup_complete"] is not True
        or type(duration) not in (int, float)
        or not 0 < duration <= DEADLINE_SECONDS
        or not math.isfinite(duration)
        or not supported_node(report["node_version"])
        or report["case_authority"] != "synthetic_typed_read_preflight"
        or report["invocation_authority"] != "independent_transport_probe_no_issued_attempt"
        or type(report["case_results"]) is not list
    ):
        raise GateError("invalid_report")
    expected = [{"name": name, "status": "passed", "code": "ok"} for name in CASE_NAMES]
    if report["case_results"] != expected:
        raise GateError("invalid_report")
    return report


def validated_server(raw: bytes, node_version: str) -> bool:
    report = decode(raw)
    return (
        set(report)
        == {"status", "cleanup_complete", "active", "requests", "sockets", "node_version"}
        and report["status"] == "passed"
        and report["cleanup_complete"] is True
        and all(
            type(report[key]) is int and report[key] == 0
            for key in ("active", "requests", "sockets")
        )
        and report["node_version"] == node_version
        and supported_node(node_version)
    )


def report_target(root: Path, path: Path) -> Path:
    target = path if path.is_absolute() else root / path
    target = target.absolute()
    if ".." in target.parts or not target.is_relative_to(root / ".local/validation/p3-coordinator"):
        raise GateError("unsafe_evidence_path")
    private_directory(target.parent)
    if target.exists() or target.is_symlink():
        raise GateError("existing_report")
    return target


def retain_report(root: Path, path: Path, report: dict[str, Any]) -> None:
    target = report_target(root, path)
    payload = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
    if len(payload) > MAX_REPORT_BYTES:
        raise GateError("invalid_report")
    with os.fdopen(
        os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb"
    ) as stream:
        stream.write(payload)


class CaptureBudget:
    """One aggregate gate budget; reserve the live Node process before other calls."""

    def __init__(self) -> None:
        self.available = MAX_CAPTURE_BYTES

    def reserve(self, maximum: int = 12288) -> int:
        total = min(maximum, self.available)
        if total < 2:
            raise GateError("capture_limit")
        self.available -= total
        return total // 2

    @staticmethod
    def read(output: Path, per_stream: int) -> tuple[bytes, bytes]:
        values = tuple((output / (name + ".bin")).read_bytes() for name in ("stdout", "stderr"))
        if any(len(value) > per_stream for value in values):
            raise GateError("capture_limit")
        return values[0], values[1]


def run_child(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    output: Path,
    deadline: float,
    budget: CaptureBudget,
) -> dict[str, Any]:
    validate_child_environment(environment, command[-1])
    limit = budget.reserve()
    with OwnedProcess(
        command, cwd=cwd, env=environment, output_directory=output, max_output_bytes=limit
    ) as child:
        result = child.wait(timeout=remaining(deadline))
    stdout, stderr = budget.read(output, limit)
    if child.cleanup_failed or child.returncode is None:
        raise GateError("cleanup_incomplete")
    if result.returncode != 0 or stderr:
        raise GateError("runner_failed")
    value = decode(stdout)
    if value.get("status") != "passed":
        raise GateError("case_failed")
    return value


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    started = time.monotonic()
    deadline, work_deadline = started + DEADLINE_SECONDS, started + DEADLINE_SECONDS - 10
    target = args.report or Path(".local/validation/p3-coordinator/" + uuid4().hex + ".json")
    cleanup_complete = False
    try:
        report_target(root, target)  # Refuse stale/existing evidence before any DB work.
        setup = load_setup(root)
        try:
            values = setup.load_settings()
        except setup.SetupError:
            raise GateError("missing_setup") from None
        project = root / "projects/delegation-reliability/specialist-ts"
        fixture = project / "tests/fixtures/python-client-server.mjs"
        cases = root / "projects/delegation-reliability/tests/pg_coordinator_cases.py"
        compiler = project / "node_modules/typescript/bin/tsc"
        node = shutil.which("node")
        interpreter = root / ".venv/bin/python"
        if node is None or not all(
            path.is_file() for path in (fixture, cases, compiler, interpreter)
        ):
            raise GateError("missing_setup")
        scratch = root / ".local/p3-coordinator-check"
        private_directory(scratch)
        with tempfile.TemporaryDirectory(prefix="run-", dir=scratch) as temporary:
            work = Path(temporary)
            budget = CaptureBudget()
            # Compiler is a process, but does not emit a JSON case result.
            compile_limit = budget.reserve()
            with OwnedProcess(
                [node, str(compiler), "--project", str(project / "tsconfig.json")],
                cwd=project,
                env=base_environment(),
                output_directory=work / "compile",
                max_output_bytes=compile_limit,
            ) as compiler_child:
                compiled = compiler_child.wait(timeout=remaining(work_deadline))
            if compiler_child.cleanup_failed or compiled.returncode != 0:
                raise GateError("compile_failed")
            budget.read(work / "compile", compile_limit)
            schema = "p1_work_p3_" + uuid4().hex
            context = {
                "P3_CHECK_SCHEMA": schema,
                "P3_CHECK_TOKEN": secrets.token_urlsafe(32),
                "P3_CHECK_RELEASE": str(work / "specialist.release"),
                "P3_CHECK_PROFILE_INSTALLED": "0",
            }
            python_command = [str(interpreter), "-I", str(cases)]
            ready = FileBarrier(work, "specialist_ready")
            commit = FileBarrier(work, "committed")
            server_limit = budget.reserve()
            server_environment = {
                **base_environment(),
                "P3_CHECK_TOKEN": context["P3_CHECK_TOKEN"],
                "P3_CHECK_READY": str(work / "specialist_ready.reached"),
                "P3_CHECK_ENDPOINT_FILE": str(work / "endpoint.json"),
                "P3_CHECK_RELEASE": context["P3_CHECK_RELEASE"],
                "P3_CHECK_STOP": str(work / "specialist.stop"),
            }
            installed = False
            server_clean = schema_clean = killed = False
            observed: list[str] = []
            primary_sha = ""
            node_version = ""
            try:
                result = run_child(
                    [*python_command, "install"],
                    cwd=work,
                    environment=child_environment(values, mode="install", context=context),
                    output=work / "install",
                    deadline=work_deadline,
                    budget=budget,
                )
                if result != {"status": "passed", "foreign_records": 0, "total_records": 0}:
                    raise GateError("invalid_report")
                installed = True
                context["P3_CHECK_PROFILE_INSTALLED"] = "1"
                with OwnedProcess(
                    [node, str(fixture)],
                    cwd=project,
                    env=server_environment,
                    output_directory=work / "server",
                    max_output_bytes=server_limit,
                ) as server:
                    try:
                        server.wait_for_barrier(ready, timeout=min(10, remaining(work_deadline)))
                        endpoint_raw = (work / "endpoint.json").read_bytes()
                        endpoint = decode(endpoint_raw)
                        if (
                            set(endpoint) != {"port", "node_version"}
                            or type(endpoint["port"]) is not int
                            or not 1 <= endpoint["port"] <= 65535
                            or not supported_node(endpoint["node_version"])
                        ):
                            raise GateError("invalid_report")
                        node_version = endpoint["node_version"]
                        context["P3_CHECK_SPECIALIST_PORT"] = str(endpoint["port"])
                        result = run_child(
                            [*python_command, "exercise"],
                            cwd=work,
                            environment=child_environment(values, mode="exercise", context=context),
                            output=work / "exercise",
                            deadline=work_deadline,
                            budget=budget,
                        )
                        expected_main = [
                            name
                            for name in CASE_NAMES
                            if name
                            not in {
                                "fresh_process_original_lookup",
                                "after_commit_sigkill_reconciliation",
                                "cleanup_ownership",
                            }
                        ]
                        if (
                            set(result) != {"status", "cases", "primary_sha256"}
                            or set(result["cases"]) != set(expected_main)
                            or len(result["cases"]) != len(expected_main)
                            or type(result["primary_sha256"]) is not str
                            or re.fullmatch(r"[0-9a-f]{64}", result["primary_sha256"]) is None
                        ):
                            raise GateError("invalid_report")
                        owner_check = run_child(
                            [*python_command, "owner-check"],
                            cwd=work,
                            environment=child_environment(
                                values, mode="owner-check", context=context
                            ),
                            output=work / "owner-check",
                            deadline=work_deadline,
                            budget=budget,
                        )
                        if owner_check != {
                            "status": "passed",
                            "foreign_records": 0,
                            "total_records": 2,
                        }:
                            raise GateError("owner_reconciliation_failed")
                        observed.extend(result["cases"])
                        primary_sha = result["primary_sha256"]
                        context["P3_CHECK_PRIMARY_SHA256"] = primary_sha
                        result = run_child(
                            [*python_command, "verify"],
                            cwd=work,
                            environment=child_environment(values, mode="verify", context=context),
                            output=work / "verify",
                            deadline=work_deadline,
                            budget=budget,
                        )
                        if result != {
                            "status": "passed",
                            "cases": ["fresh_process_original_lookup"],
                        }:
                            raise GateError("invalid_report")
                        observed.extend(result["cases"])
                        context["P3_CHECK_CRASH_DEADLINE"] = str(
                            time.time_ns() // 1_000_000 + 30000
                        )
                        context["P3_CHECK_COMMIT_MARKER"] = str(work / "committed.reached")
                        crash_limit = budget.reserve()
                        with OwnedProcess(
                            [*python_command, "crash"],
                            cwd=work,
                            env=child_environment(values, mode="crash", context=context),
                            output_directory=work / "crash",
                            max_output_bytes=crash_limit,
                        ) as crash:
                            crash.wait_for_barrier(
                                commit, timeout=min(10, remaining(work_deadline))
                            )
                            termination = crash.kill(timeout=min(3, remaining(work_deadline)))
                            killed = termination.killed and termination.returncode == -9
                        stdout, stderr = budget.read(work / "crash", crash_limit)
                        if crash.cleanup_failed or not killed or stdout or stderr:
                            raise GateError("crash_not_observed")
                        result = run_child(
                            [*python_command, "verify-crash"],
                            cwd=work,
                            environment=child_environment(
                                values, mode="verify-crash", context=context
                            ),
                            output=work / "verify-crash",
                            deadline=work_deadline,
                            budget=budget,
                        )
                        if result != {
                            "status": "passed",
                            "cases": ["after_commit_sigkill_reconciliation"],
                        }:
                            raise GateError("invalid_report")
                        observed.extend(result["cases"])
                    finally:
                        (work / "specialist.release").touch(mode=0o600, exist_ok=True)
                        (work / "specialist.stop").touch(mode=0o600, exist_ok=True)
                        stopped = server.wait(timeout=min(5, remaining(deadline)))
                        stdout, stderr = budget.read(work / "server", server_limit)
                        server_clean = (
                            stopped.returncode == 0
                            and not stderr
                            and not server.cleanup_failed
                            and validated_server(stdout, node_version)
                        )
            finally:
                # Install is transactional, but cleanup still checks for a partially
                # present owned marked profile if a setup child failed unexpectedly.
                clean = run_child(
                    [*python_command, "cleanup"],
                    cwd=work,
                    environment=child_environment(values, mode="cleanup", context=context),
                    output=work / "cleanup",
                    deadline=deadline,
                    budget=budget,
                )
                schema_clean = clean == {"status": "passed", "schema_removed": True}
                cleanup_complete = schema_clean and server_clean
            if not installed or not server_clean or not schema_clean or not killed:
                raise GateError("cleanup_incomplete")
            observed.append("cleanup_ownership")
            if set(observed) != set(CASE_NAMES) or len(observed) != len(CASE_NAMES):
                raise GateError("invalid_report")
            report = validated_report(
                json.dumps(
                    {
                        "schema_version": 1,
                        "status": "passed",
                        "mode": MODE,
                        "tests": len(CASE_NAMES),
                        "passed": len(CASE_NAMES),
                        "failures": 0,
                        "errors": 0,
                        "skipped": 0,
                        "duration_seconds": time.monotonic() - started,
                        "cleanup_complete": True,
                        "child_terminations": 1,
                        "case_results": [
                            {"name": name, "status": "passed", "code": "ok"} for name in CASE_NAMES
                        ],
                        "node_version": node_version,
                        "case_authority": "synthetic_typed_read_preflight",
                        "invocation_authority": "independent_transport_probe_no_issued_attempt",
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
    except Exception:  # noqa: BLE001 - private configuration/child failures stay inside this tooling boundary
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
        # An unsafe/existing target must never be replaced merely to retain failure.
        pass
    print(json.dumps(failure, sort_keys=True))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
