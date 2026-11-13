"""Fresh bounded P3 concurrency and complete rejection acceptance gates."""

from __future__ import annotations

import argparse
import json
import math
import os
import secrets
import shutil
import sys
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p3_coordinator_check as core

from harness.process_control import FileBarrier, OwnedProcess, ProcessControlError

ROOT = Path(__file__).resolve().parents[2]
DEADLINE_SECONDS = 180.0
MODE = "local_synthetic_p3_contract_acceptance"
CASES = {
    "P3-03": (
        "concurrent_equal_one_logical",
        "changed_admission_conflict",
        "immutable_original_snapshot",
        "cross_scope_zero_disclosure",
        "fresh_process_original_inspection",
        "issued_current_useful_result",
        "independent_owner_reconciliation",
        "cleanup_ownership",
    ),
    "P3-11": (
        "malformed_output_rejected_safe",
        "wrong_revision_rejected_safe",
        "unsupported_schema_rejected_safe",
        "mismatched_tenant_rejected_safe",
        "oversized_result_rejected_safe",
        "oversized_context_rejected_safe",
        "oversized_request_rejected_safe",
        "oversized_image_rejected_safe",
        "evidence_facts_rejected_safe",
        "positive_progress_after_rejections",
        "independent_zero_invalid_results",
        "cleanup_ownership",
    ),
}
CODEC_CASES = [
    "malformed_output",
    "wrong_revision",
    "unsupported_schema",
    "mismatched_tenant",
    "oversized_result",
    "oversized_context",
    "oversized_request",
    "oversized_image",
    "evidence_facts",
]
OWNER_MODES = frozenset({"install", "locks", "owner-check", "cleanup"})
COMMON = {"P3_ACCEPT_CASE_ID", "P3_ACCEPT_SCHEMA", "P3_ACCEPT_DIRECTORY"}
MODE_KEYS = {
    "install": COMMON,
    "locks": COMMON,
    "owner-check": COMMON,
    "cleanup": COMMON,
    "original": COMMON | {"P3_ACCEPT_TOKEN"},
    "equal": COMMON | {"P3_ACCEPT_TOKEN"},
    "changed": COMMON | {"P3_ACCEPT_TOKEN"},
    "verify": COMMON | {"P3_ACCEPT_TOKEN", "P3_ACCEPT_SPECIALIST_PORT"},
    "negative": COMMON
    | {"P3_ACCEPT_TOKEN", "P3_ACCEPT_SPECIALIST_PORT", "P3_ACCEPT_BAD_PORT", "P3_ACCEPT_FIXTURE"},
}
GateError = core.GateError


def child_environment(
    values: dict[str, str], *, mode: str, context: dict[str, str]
) -> dict[str, str]:
    if mode not in MODE_KEYS:
        raise GateError("invalid_child_mode")
    owner = mode in OWNER_MODES
    password = "P3_ACCEPT_OWNER_PASSWORD" if owner else "P3_ACCEPT_RUNTIME_PASSWORD"
    result = {
        **core.base_environment(),
        "P3_ACCEPT_PG_PORT": values["POSTGRES_PORT"],
        password: values["POSTGRES_MIGRATION_PASSWORD" if owner else "POSTGRES_PASSWORD"],
        **{key: context[key] for key in MODE_KEYS[mode]},
    }
    validate_child_environment(result, mode)
    return result


def validate_child_environment(value: dict[str, str], mode: str) -> None:
    if mode not in MODE_KEYS:
        raise GateError("invalid_child_mode")
    password = "P3_ACCEPT_OWNER_PASSWORD" if mode in OWNER_MODES else "P3_ACCEPT_RUNTIME_PASSWORD"
    required = MODE_KEYS[mode] | {"P3_ACCEPT_PG_PORT", password}
    if (
        not required <= set(value)
        or set(value) - required - core.BASE_ENVIRONMENT_KEYS
        or any(type(v) is not str or not v or "\0" in v for v in value.values())
    ):
        raise GateError("unsafe_child_environment")


def validated_report(raw: bytes, case_id: str) -> dict[str, Any]:
    if case_id not in CASES:
        raise GateError("invalid_case")
    value = core.decode(raw)
    expected = {
        "schema_version",
        "status",
        "case_id",
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
        "node_version",
    }
    if set(value) != expected:
        raise GateError("invalid_report")
    for key in (
        "schema_version",
        "tests",
        "passed",
        "errors",
        "failures",
        "skipped",
        "child_terminations",
    ):
        if type(value[key]) is not int:
            raise GateError("invalid_report")
    duration = value["duration_seconds"]
    if (
        value["schema_version"] != 1
        or value["status"] != "passed"
        or value["case_id"] != case_id
        or value["mode"] != MODE
        or value["tests"] != len(CASES[case_id])
        or value["passed"] != len(CASES[case_id])
        or any(value[key] != 0 for key in ("errors", "failures", "skipped", "child_terminations"))
        or value["cleanup_complete"] is not True
        or type(duration) not in (int, float)
        or not math.isfinite(duration)
        or not 0 < duration <= DEADLINE_SECONDS
        or not core.supported_node(value["node_version"])
        or value["case_results"]
        != [{"name": name, "status": "passed", "code": "ok"} for name in CASES[case_id]]
    ):
        raise GateError("invalid_report")
    return value


def report_target(root: Path, target: Path) -> Path:
    path = (target if target.is_absolute() else root / target).absolute()
    if ".." in path.parts or not path.is_relative_to(
        root / ".local/validation/p3-contract-acceptance"
    ):
        raise GateError("unsafe_evidence_path")
    core.private_directory(path.parent)
    if path.exists() or path.is_symlink():
        raise GateError("existing_report")
    return path


def retain_report(root: Path, target: Path, report: dict[str, Any]) -> None:
    path = report_target(root, target)
    raw = (json.dumps(report, sort_keys=True, indent=2) + "\n").encode()
    if len(raw) > 32768:
        raise GateError("invalid_report")
    with os.fdopen(
        os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb"
    ) as stream:
        stream.write(raw)


def validate_server(raw: bytes, case_id: str, node_version: str) -> bool:
    value = core.decode(raw)
    expected = {
        "status": "passed",
        "cleanup_complete": True,
        "evaluations": 1,
        "invalid_responses": 5 if case_id == "P3-11" else 0,
        "invalid_cases": CODEC_CASES[:5] if case_id == "P3-11" else [],
        "raw_requests": 5 if case_id == "P3-11" else 0,
        "codec_cases": CODEC_CASES if case_id == "P3-11" else [],
        "active": 0,
        "requests": 0,
        "sockets": 0,
        "node_version": node_version,
    }
    return (
        value == expected
        and all(
            type(value[k]) is int
            for k in (
                "evaluations",
                "invalid_responses",
                "raw_requests",
                "active",
                "requests",
                "sockets",
            )
        )
        and value["cleanup_complete"] is True
    )


def validate_server_cleanup(raw: bytes, node_version: str) -> bool:
    value = core.decode(raw)
    fields = {
        "status",
        "cleanup_complete",
        "evaluations",
        "invalid_responses",
        "invalid_cases",
        "raw_requests",
        "codec_cases",
        "active",
        "requests",
        "sockets",
        "node_version",
    }
    return (
        set(value) == fields
        and value["status"] == "passed"
        and value["cleanup_complete"] is True
        and value["node_version"] == node_version
        and all(
            type(value[k]) is int and 0 <= value[k] <= 32
            for k in ("evaluations", "invalid_responses", "raw_requests")
        )
        and all(type(value[k]) is int and value[k] == 0 for k in ("active", "requests", "sockets"))
        and type(value["invalid_cases"]) is list
        and type(value["codec_cases"]) is list
        and len(value["invalid_cases"]) <= 5
        and len(value["codec_cases"]) <= 9
        and all(v in CODEC_CASES for v in value["invalid_cases"] + value["codec_cases"])
    )


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, choices=CASES)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    case_id = args.case
    started = time.monotonic()
    deadline = started + DEADLINE_SECONDS
    work_deadline = deadline - 10
    target = args.report or Path(
        ".local/validation/p3-contract-acceptance/" + uuid4().hex + ".json"
    )
    cleanup_complete = False
    try:
        report_target(root, target)
        setup = core.load_setup(root)
        try:
            values = setup.load_settings()
        except setup.SetupError:
            raise GateError("missing_setup") from None
        project = root / "projects/delegation-reliability/specialist-ts"
        fixture = project / "tests/fixtures/acceptance-server.mjs"
        cases = root / "projects/delegation-reliability/tests/pg_acceptance_cases.py"
        interpreter = root / ".venv/bin/python"
        compiler = project / "node_modules/typescript/bin/tsc"
        node = shutil.which("node")
        if node is None or not all(p.is_file() for p in (fixture, cases, interpreter, compiler)):
            raise GateError("missing_setup")
        scratch = root / ".local/p3-contract-acceptance-check"
        core.private_directory(scratch)
        with tempfile.TemporaryDirectory(prefix="run-", dir=scratch) as temporary:
            work = Path(temporary)
            budget = core.CaptureBudget()
            sequence = 0

            def process(
                command: list[str], mode: str, *, env: dict[str, str] | None = None
            ) -> dict[str, Any]:
                nonlocal sequence
                sequence += 1
                output = work / (str(sequence) + "-" + mode)
                limit = budget.reserve(10240)
                if env is None:
                    env = child_environment(values, mode=mode, context=context)
                with OwnedProcess(
                    command, cwd=work, env=env, output_directory=output, max_output_bytes=limit
                ) as child:
                    result = child.wait(
                        timeout=core.remaining(deadline if mode == "cleanup" else work_deadline)
                    )
                stdout, stderr = budget.read(output, limit)
                if child.cleanup_failed or result.returncode != 0 or stderr:
                    raise GateError("runner_failed_" + mode)
                value = core.decode(stdout)
                if value.get("status") != "passed":
                    raise GateError("case_failed_" + mode)
                return value

            limit = budget.reserve(10240)
            with OwnedProcess(
                [node, str(compiler), "--project", str(project / "tsconfig.json")],
                cwd=project,
                env=core.base_environment(),
                output_directory=work / "compile",
                max_output_bytes=limit,
            ) as compiler_child:
                compiled = compiler_child.wait(timeout=core.remaining(work_deadline))
            stdout, stderr = budget.read(work / "compile", limit)
            if compiler_child.cleanup_failed or compiled.returncode != 0 or stdout or stderr:
                raise GateError("compile_failed")
            context = {
                "P3_ACCEPT_CASE_ID": case_id,
                "P3_ACCEPT_SCHEMA": "p1_work_acceptance_" + uuid4().hex,
                "P3_ACCEPT_DIRECTORY": str(work),
                "P3_ACCEPT_TOKEN": secrets.token_urlsafe(32),
                "P3_ACCEPT_FIXTURE": str(root / "contracts/delegation/v1.json"),
            }
            command = [str(interpreter), "-I", str(cases)]

            def call(mode: str) -> dict[str, Any]:
                return process([*command, mode], mode)

            server_result_verified = False
            installed = False
            schema_clean = False
            server_clean = True
            node_version = ""
            observed: list[str] = []
            server_limit = budget.reserve(10240)
            server_env = {
                **core.base_environment(),
                "P3_ACCEPT_CASE_ID": case_id,
                "P3_ACCEPT_TOKEN": context["P3_ACCEPT_TOKEN"],
                "P3_ACCEPT_FIXTURE": context["P3_ACCEPT_FIXTURE"],
                "P3_ACCEPT_READY": str(work / "server_ready.reached"),
                "P3_ACCEPT_ENDPOINT_FILE": str(work / "endpoint.json"),
                "P3_ACCEPT_STOP": str(work / "server.stop"),
            }
            try:
                if call("install") != {"status": "passed", "version": 2}:
                    raise GateError("invalid_report")
                installed = True
                server_clean = False
                ready_barrier = FileBarrier(work, "server_ready")
                with OwnedProcess(
                    [node, str(fixture)],
                    cwd=project,
                    env=server_env,
                    output_directory=work / "server",
                    max_output_bytes=server_limit,
                ) as server:
                    try:
                        server.wait_for_barrier(
                            ready_barrier,
                            timeout=min(10, core.remaining(work_deadline)),
                        )
                        endpoint = core.decode((work / "endpoint.json").read_bytes())
                        if (
                            set(endpoint) != {"port", "bad_port", "node_version"}
                            or any(
                                type(endpoint[k]) is not int or not 1 <= endpoint[k] <= 65535
                                for k in ("port", "bad_port")
                            )
                            or not core.supported_node(endpoint["node_version"])
                        ):
                            raise GateError("invalid_report")
                        node_version = endpoint["node_version"]
                        context["P3_ACCEPT_SPECIALIST_PORT"] = str(endpoint["port"])
                        context["P3_ACCEPT_BAD_PORT"] = str(endpoint["bad_port"])
                        if case_id == "P3-03":
                            with ExitStack() as stack:
                                barriers = {
                                    name: FileBarrier(work, name)
                                    for name in (
                                        "original_preflight",
                                        "equal_preflight",
                                        "changed_preflight",
                                        "owner_ready",
                                        "original_commit",
                                        "sql_contention",
                                    )
                                }
                                jobs = {}
                                limits = {}
                                for mode in ("original", "equal", "changed", "locks"):
                                    limit = budget.reserve(10240)
                                    limits[mode] = limit
                                    jobs[mode] = stack.enter_context(
                                        OwnedProcess(
                                            [*command, mode],
                                            cwd=work,
                                            env=child_environment(
                                                values, mode=mode, context=context
                                            ),
                                            output_directory=work / mode,
                                            max_output_bytes=limit,
                                        )
                                    )
                                try:
                                    for mode in ("original", "equal", "changed"):
                                        try:
                                            jobs[mode].wait_for_barrier(
                                                barriers[mode + "_preflight"],
                                                timeout=min(10, core.remaining(work_deadline)),
                                            )
                                        except ProcessControlError:
                                            failed = core.decode(
                                                (work / mode / "stdout.bin").read_bytes()
                                            )
                                            line = failed.get("line")
                                            if (
                                                failed.get("status") == "failed"
                                                and type(line) is int
                                                and 1 <= line <= 2000
                                            ):
                                                raise GateError(
                                                    "runner_failed_" + mode + "_line_" + str(line)
                                                ) from None
                                            raise
                                    jobs["locks"].wait_for_barrier(
                                        barriers["owner_ready"],
                                        timeout=min(10, core.remaining(work_deadline)),
                                    )
                                    (work / "original.release").touch(mode=0o600)
                                    jobs["original"].wait_for_barrier(
                                        barriers["original_commit"],
                                        timeout=min(5, core.remaining(work_deadline)),
                                    )
                                    for mode in ("equal", "changed"):
                                        (work / (mode + ".release")).touch(mode=0o600)
                                    jobs["locks"].wait_for_barrier(
                                        barriers["sql_contention"],
                                        timeout=min(0.8, core.remaining(work_deadline)),
                                    )
                                    (work / "commit.release").touch(mode=0o600)
                                    results = {}
                                    for mode, job in jobs.items():
                                        settled = job.wait(
                                            timeout=min(10, core.remaining(work_deadline))
                                        )
                                        stdout, stderr = budget.read(work / mode, limits[mode])
                                        if job.cleanup_failed or settled.returncode != 0 or stderr:
                                            raise GateError("runner_failed_" + mode)
                                        results[mode] = core.decode(stdout)
                                    first, second, changed, locks = (
                                        results[k]
                                        for k in ("original", "equal", "changed", "locks")
                                    )
                                    if (
                                        first.get("status") != "passed"
                                        or second.get("status") != "passed"
                                        or first.get("created") is not True
                                        or second.get("created") is not False
                                        or any(
                                            first.get(k) != second.get(k)
                                            for k in ("work_id", "sha256", "deadline_at_ms")
                                        )
                                        or changed
                                        != {
                                            "status": "passed",
                                            "mode": "changed",
                                            "code": "identity_conflict",
                                            "created": False,
                                        }
                                        or locks
                                        != {
                                            "status": "passed",
                                            "holders": 1,
                                            "waiters": 2,
                                            "actual_admission_lock_contention": True,
                                        }
                                    ):
                                        raise GateError("invalid_race_report")
                                finally:
                                    for name in (
                                        "original.release",
                                        "equal.release",
                                        "changed.release",
                                        "commit.release",
                                    ):
                                        (work / name).touch(mode=0o600, exist_ok=True)
                            useful = call("verify")
                            if (
                                useful.get("status") != "passed"
                                or useful.get("selected_invocations") != 1
                                or useful.get("cross_scope_disclosures") != 0
                                or useful.get("work_id") != first["work_id"]
                                or useful.get("sha256") != first["sha256"]
                            ):
                                raise GateError("invalid_report")
                            observed.extend(CASES[case_id][:6])
                        else:
                            rejected = call("negative")
                            expected_records = [
                                {
                                    "name": name,
                                    "code": "transport_unknown",
                                    "result_committed": False,
                                }
                                for name in CODEC_CASES[:5]
                            ]
                            if rejected != {
                                "status": "passed",
                                "python_codec_cases": CODEC_CASES,
                                "invalid_observations": expected_records,
                                "invalid_results_committed": 0,
                                "positive_results_committed": 1,
                            }:
                                raise GateError("invalid_negative_report")
                            observed.extend(CASES[case_id][:10])
                        count = 1 if case_id == "P3-03" else 6
                        expected_owner = {
                            "status": "passed",
                            "counts": {
                                "accepted_work": count,
                                "issued_attempts": count,
                                "attempt_results": 1,
                                "cancellation_commands": 0,
                            },
                            "foreign_records": 0,
                            "invalid_result_commits": 0,
                        }
                        if call("owner-check") != expected_owner:
                            raise GateError("owner_reconciliation_failed")
                        observed.append(CASES[case_id][-2])
                    finally:
                        (work / "server.stop").touch(mode=0o600, exist_ok=True)
                        stopped = server.wait(timeout=min(5, core.remaining(deadline)))
                        stdout, stderr = budget.read(work / "server", server_limit)
                        server_clean = (
                            stopped.returncode == 0
                            and not server.cleanup_failed
                            and not stderr
                            and validate_server_cleanup(stdout, node_version)
                        )
                        server_result_verified = validate_server(stdout, case_id, node_version)
            finally:
                schema_clean = call("cleanup") == {"status": "passed", "schema_removed": True}
                cleanup_complete = server_clean and schema_clean
            if not installed or not cleanup_complete:
                raise GateError("cleanup_incomplete")
            if not server_result_verified:
                raise GateError("invalid_server_report")
            observed.append(CASES[case_id][-1])
            if observed != list(CASES[case_id]):
                raise GateError("invalid_report")
            report = validated_report(
                json.dumps(
                    {
                        "schema_version": 1,
                        "status": "passed",
                        "case_id": case_id,
                        "mode": MODE,
                        "tests": len(observed),
                        "passed": len(observed),
                        "errors": 0,
                        "failures": 0,
                        "skipped": 0,
                        "duration_seconds": time.monotonic() - started,
                        "cleanup_complete": True,
                        "child_terminations": 0,
                        "case_results": [
                            {"name": name, "status": "passed", "code": "ok"} for name in observed
                        ],
                        "node_version": node_version,
                    }
                ).encode(),
                case_id,
            )
        retain_report(root, target, report)
        print(json.dumps(report, sort_keys=True))
        return 0
    except GateError as error:
        code = error.code
    except ProcessControlError:
        code = "runner_failed"
    except Exception:  # noqa: BLE001 - fixed tooling diagnostics exclude private dependency details
        code = "gate_failed"
    failure = {
        "schema_version": 1,
        "status": "failed",
        "case_id": case_id,
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
