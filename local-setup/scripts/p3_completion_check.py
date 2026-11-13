"""Explicit result delivery and guarded case action; no provider or runtime DDL."""

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
from pathlib import Path
from typing import Any
from uuid import uuid4

# Shared same-owner gate tooling, never imported by the product distributions.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import p3_coordinator_check as core

from harness.process_control import FileBarrier, OwnedProcess, ProcessControlError

ROOT = Path(__file__).resolve().parents[2]
DEADLINE_SECONDS = 180.0
MAX_REPORT_BYTES = 32768
MODE = "local_synthetic_p3_completion_and_action"
CASE_NAMES = (
    "actual_case_v4_issued_policy_result",
    "revision_a_outdated_zero_delivery_or_action",
    "current_b_useful_strict_result",
    "receiver_commit_ack_loss_original_receipt",
    "changed_delivery_binding_cannot_retarget",
    "work_cancel_after_preflight_zero_intent",
    "exact_confirmation_guarded_intent",
    "actual_leased_fake_effect_once",
    "late_work_cancel_preserves_known_facts",
    "fresh_process_original_delivery_action_read",
    "receiver_commit_sigkill_fresh_reconciliation",
    "independent_owner_reconciliation",
    "cleanup_ownership",
)
OWNER_MODES = frozenset({"install", "owner-check", "cleanup"})
COMMON = {
    "P3_COMPLETE_WORK_SCHEMA",
    "P3_COMPLETE_CASE_SCHEMA",
    "P3_COMPLETE_DIRECTORY",
    "P3_COMPLETE_RECEIVER_ID",
}
MODE_KEYS = {
    "install": COMMON,
    "exercise": COMMON | {"P3_COMPLETE_TOKEN", "P3_COMPLETE_SPECIALIST_PORT"},
    "verify": COMMON | {"P3_COMPLETE_TOKEN", "P3_COMPLETE_SPECIALIST_PORT"},
    "crash": COMMON
    | {"P3_COMPLETE_TOKEN", "P3_COMPLETE_SPECIALIST_PORT", "P3_COMPLETE_COMMIT_MARKER"},
    "verify-crash": COMMON | {"P3_COMPLETE_TOKEN", "P3_COMPLETE_SPECIALIST_PORT"},
    "owner-check": COMMON,
    "cleanup": COMMON,
}
GateError = core.GateError


def validate_child_environment(environment: dict[str, str], mode: str) -> None:
    if mode not in MODE_KEYS:
        raise GateError("invalid_child_mode")
    password = (
        "P3_COMPLETE_OWNER_PASSWORD" if mode in OWNER_MODES else "P3_COMPLETE_RUNTIME_PASSWORD"
    )
    required = {"P3_COMPLETE_PG_PORT", password, *MODE_KEYS[mode]}
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
    password = "P3_COMPLETE_OWNER_PASSWORD" if owner else "P3_COMPLETE_RUNTIME_PASSWORD"
    result = {
        **core.base_environment(),
        "P3_COMPLETE_PG_PORT": values["POSTGRES_PORT"],
        password: values["POSTGRES_MIGRATION_PASSWORD" if owner else "POSTGRES_PASSWORD"],
        **{name: context[name] for name in MODE_KEYS[mode]},
    }
    validate_child_environment(result, mode)
    return result


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
        "node_version",
        "case_authority",
        "invocation_authority",
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
        or value["child_terminations"] != 1
        or value["cleanup_complete"] is not True
        or type(duration) not in (int, float)
        or not 0 < duration <= DEADLINE_SECONDS
        or not math.isfinite(duration)
        or not core.supported_node(value["node_version"])
        or value["case_authority"] != "actual_p1_v4_exact_confirmation_and_guarded_intent"
        or value["invocation_authority"]
        != "runner_requires_p1_issued_attempt_http_service_separately_authenticated"
        or value["case_results"]
        != [{"name": name, "status": "passed", "code": "ok"} for name in CASE_NAMES]
    ):
        raise GateError("invalid_report")
    return value


def validated_server_cleanup(raw: bytes, node_version: str) -> bool:
    value = core.decode(raw)
    count = value.pop("invocation_count", None)
    return (
        type(count) is int
        and 0 <= count <= 16
        and core.validated_server(json.dumps(value).encode(), node_version)
    )


def validated_server(raw: bytes, node_version: str) -> bool:
    value = core.decode(raw)
    return (
        value.get("invocation_count") == 4
        and type(value.get("invocation_count")) is int
        and validated_server_cleanup(raw, node_version)
    )


def report_target(root: Path, path: Path) -> Path:
    target = (path if path.is_absolute() else root / path).absolute()
    if ".." in target.parts or not target.is_relative_to(root / ".local/validation/p3-completion"):
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
    limit = budget.reserve(10240)
    with OwnedProcess(
        command, cwd=cwd, env=environment, output_directory=output, max_output_bytes=limit
    ) as child:
        result = child.wait(timeout=core.remaining(deadline))
    stdout, stderr = budget.read(output, limit)
    if child.cleanup_failed or child.returncode is None:
        raise GateError("cleanup_incomplete")
    if result.returncode != 0 or stderr:
        code = "runner_failed_" + command[-1]
        if result.returncode != 0 and not stderr:
            try:
                failed = core.decode(stdout)
                if failed.get("code") in {
                    "fixture",
                    "owner_work",
                    "owner_case",
                    "owner_receiver",
                    "case_setup",
                    "current_b",
                    "cancel_race",
                    "exact_authorization",
                }:
                    code += "_" + failed["code"]
            except GateError:
                pass
        raise GateError(code)
    value = core.decode(stdout)
    if value.get("status") != "passed":
        raise GateError("case_failed")
    return value


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    started = time.monotonic()
    deadline, work_deadline = started + DEADLINE_SECONDS, started + DEADLINE_SECONDS - 10
    target = args.report or Path(".local/validation/p3-completion/" + uuid4().hex + ".json")
    cleanup_complete = False
    try:
        report_target(root, target)
        setup = core.load_setup(root)
        try:
            values = setup.load_settings()
        except setup.SetupError:
            raise GateError("missing_setup") from None
        project = root / "projects/delegation-reliability/specialist-ts"
        fixture = project / "tests/fixtures/completion-server.mjs"
        cases = root / "projects/delegation-reliability/tests/pg_completion_cases.py"
        compiler = project / "node_modules/typescript/bin/tsc"
        node = shutil.which("node")
        interpreter = root / ".venv/bin/python"
        if node is None or not all(p.is_file() for p in (fixture, cases, compiler, interpreter)):
            raise GateError("missing_setup")
        scratch = root / ".local/p3-completion-check"
        core.private_directory(scratch)
        with tempfile.TemporaryDirectory(prefix="run-", dir=scratch) as temporary:
            work = Path(temporary)
            budget = core.CaptureBudget()
            limit = budget.reserve(10240)
            with OwnedProcess(
                [node, str(compiler), "--project", str(project / "tsconfig.json")],
                cwd=project,
                env=core.base_environment(),
                output_directory=work / "compile",
                max_output_bytes=limit,
            ) as child:
                compiled = child.wait(timeout=core.remaining(work_deadline))
            budget.read(work / "compile", limit)
            if child.cleanup_failed or compiled.returncode != 0:
                raise GateError("compile_failed")
            context = {
                "P3_COMPLETE_WORK_SCHEMA": "p1_work_completion_" + uuid4().hex,
                "P3_COMPLETE_CASE_SCHEMA": "p3_completion_" + uuid4().hex,
                "P3_COMPLETE_RECEIVER_ID": str(uuid4()),
                "P3_COMPLETE_TOKEN": secrets.token_urlsafe(32),
                "P3_COMPLETE_DIRECTORY": str(work),
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

            installed = False
            server_clean = True
            schema_clean = killed = invocation_count_verified = False
            node_version = ""
            observed = []
            server_limit = budget.reserve(10240)
            server_environment = {
                **core.base_environment(),
                "P3_COMPLETE_TOKEN": context["P3_COMPLETE_TOKEN"],
                "P3_COMPLETE_READY": str(work / "specialist_ready.reached"),
                "P3_COMPLETE_ENDPOINT_FILE": str(work / "endpoint.json"),
                "P3_COMPLETE_BARRIERS": str(work),
                "P3_COMPLETE_STOP": str(work / "specialist.stop"),
            }
            try:
                if call("install") != {"status": "passed", "work_version": 3, "case_version": 4}:
                    raise GateError("invalid_report")
                installed = True
                server_clean = False
                with OwnedProcess(
                    [node, str(fixture)],
                    cwd=project,
                    env=server_environment,
                    output_directory=work / "server",
                    max_output_bytes=server_limit,
                ) as server:
                    try:
                        server.wait_for_barrier(
                            FileBarrier(work, "specialist_ready"),
                            timeout=min(10, core.remaining(work_deadline)),
                        )
                        endpoint = core.decode((work / "endpoint.json").read_bytes())
                        if (
                            set(endpoint) != {"port", "node_version"}
                            or type(endpoint["port"]) is not int
                            or not 1 <= endpoint["port"] <= 65535
                            or not core.supported_node(endpoint["node_version"])
                        ):
                            raise GateError("invalid_report")
                        node_version = endpoint["node_version"]
                        context["P3_COMPLETE_SPECIALIST_PORT"] = str(endpoint["port"])
                        result = call("exercise")
                        if set(result) != {"status", "cases"} or result["cases"] != list(
                            CASE_NAMES[:9]
                        ):
                            raise GateError("invalid_report")
                        observed.extend(result["cases"])
                        if call("verify") != {"status": "passed", "cases": [CASE_NAMES[9]]}:
                            raise GateError("invalid_report")
                        observed.append(CASE_NAMES[9])
                        context["P3_COMPLETE_COMMIT_MARKER"] = str(work / "committed.reached")
                        crash_limit = budget.reserve(10240)
                        with OwnedProcess(
                            [*command, "crash"],
                            cwd=work,
                            env=child_environment(values, mode="crash", context=context),
                            output_directory=work / "crash",
                            max_output_bytes=crash_limit,
                        ) as crash:
                            crash.wait_for_barrier(
                                FileBarrier(work, "committed"),
                                timeout=min(10, core.remaining(work_deadline)),
                            )
                            termination = crash.kill(timeout=min(3, core.remaining(work_deadline)))
                            killed = termination.killed and termination.returncode == -9
                        stdout, stderr = budget.read(work / "crash", crash_limit)
                        if crash.cleanup_failed or not killed or stdout or stderr:
                            raise GateError("crash_not_observed")
                        if call("verify-crash") != {"status": "passed", "cases": [CASE_NAMES[10]]}:
                            raise GateError("invalid_report")
                        observed.append(CASE_NAMES[10])
                        expected = {
                            "status": "passed",
                            "work_counts": {
                                "accepted_work": 4,
                                "cancellation_commands": 2,
                                "issued_attempts": 4,
                                "attempt_results": 4,
                                "result_delivery_intents": 2,
                                "result_delivery_possible": 2,
                                "result_delivery_receipts": 2,
                                "result_actions": 1,
                            },
                            "receiver_receipts": 2,
                            "case_intents": 1,
                            "applied_calls": 1,
                        }
                        if call("owner-check") != expected:
                            raise GateError("owner_reconciliation_failed")
                        observed.append(CASE_NAMES[11])
                    finally:
                        for name in ("delayed_a.release", "specialist.stop"):
                            (work / name).touch(mode=0o600, exist_ok=True)
                        stopped = server.wait(timeout=min(5, core.remaining(deadline)))
                        stdout, stderr = budget.read(work / "server", server_limit)
                        server_clean = (
                            stopped.returncode == 0
                            and not stderr
                            and not server.cleanup_failed
                            and validated_server_cleanup(stdout, node_version)
                        )
                        invocation_count_verified = validated_server(stdout, node_version)
            finally:
                schema_clean = call("cleanup") == {"status": "passed", "schemas_removed": True}
                cleanup_complete = server_clean and schema_clean
            if not installed or not server_clean or not schema_clean or not killed:
                raise GateError("cleanup_incomplete")
            if not invocation_count_verified:
                raise GateError("invocation_count_mismatch")
            observed.append(CASE_NAMES[12])
            if observed != list(CASE_NAMES):
                raise GateError("invalid_report")
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
                        "child_terminations": 1,
                        "case_results": [
                            {"name": name, "status": "passed", "code": "ok"} for name in CASE_NAMES
                        ],
                        "node_version": node_version,
                        "case_authority": "actual_p1_v4_exact_confirmation_and_guarded_intent",
                        "invocation_authority": "runner_requires_p1_issued_attempt_http_service_separately_authenticated",
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
    except Exception:  # noqa: BLE001 - fixed tooling boundary excludes private exception text
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
