"""Explicit real PostgreSQL P2 lane; never starts, resets or skips the local stack.

Only stack.load_settings reads private local credentials. Child environments bind
fixed local identities; raw capture is bounded, private and removed after review.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import re
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

from harness.process_control import OwnedProcess, ProcessControlError

DEADLINE_SECONDS = 180.0
MAX_CAPTURE_BYTES = 65536
BASE_CASE_NAMES = (
    "migration_and_runtime_privileges",
    "signed_possession_and_invalid_authority",
    "concurrent_exact_replay",
    "semantic_conflict_and_retry_metadata",
    "provider_and_tenant_identity_domains",
    "capacity_preserves_replay_and_reads",
    "challenge_expiry_attempts_and_single_use",
    "revocation_reassignment_and_private_history",
    "stable_sequence_and_history_paging",
    "before_commit_rolls_back",
    "after_commit_response_loss_reconciles",
    "actual_process_exit_after_commit",
    "standalone_example_public_ports",
    "standalone_example_fresh_process_replay",
)
EXAMPLE_CASE_NAMES = BASE_CASE_NAMES[-2:]
DISPATCH_CASE_NAMES = (
    "dispatch_v2_upgrade_preserves_identity",
    "dispatch_concurrency_scope_and_admission",
    "dispatch_lease_takeover_reuses_prepared_plan",
    "dispatch_uncertainty_attempt_bound_and_reconciliation",
    "dispatch_process_kill_after_external_commit",
)
GATEWAY_CASE_NAMES = (
    "gateway_normal_authenticated_http_progress",
    "gateway_sigkill_after_flushed_ack_recovers_original",
    "gateway_persisted_selection_progresses_after_blocked_scope",
)
AGENT_CASE_NAMES = ("gateway_agent_sigkill_expired_claim_replay",)
CASE_NAMES = BASE_CASE_NAMES + DISPATCH_CASE_NAMES + GATEWAY_CASE_NAMES + AGENT_CASE_NAMES


class GateError(RuntimeError):
    """Only fixed local gate categories may leave this boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__("P2 PostgreSQL qualification did not pass")


def load_setup(root: Path) -> ModuleType:
    name = "p2_postgres_setup_" + uuid4().hex
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
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise GateError("unsafe_evidence_path")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise GateError("unsafe_evidence_path")


def base_environment() -> dict[str, str]:
    # Do not forward provider credentials, libpq selectors, NODE_OPTIONS or telemetry.
    allowed = ("PATH", "HOME", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL", "SYSTEMROOT")
    result = {key: os.environ[key] for key in allowed if key in os.environ}
    result.update({"NO_COLOR": "1", "CI": "1"})
    return result


def child_environment(values: dict[str, str]) -> dict[str, str]:
    result = base_environment()
    result.update(
        {
            "P2_POSTGRES_PORT": values["POSTGRES_PORT"],
            "P2_RUNTIME_PASSWORD": values["POSTGRES_PASSWORD"],
            "P2_MIGRATION_PASSWORD": values["POSTGRES_MIGRATION_PASSWORD"],
        }
    )
    return result


def remaining(deadline: float) -> float:
    result = deadline - time.monotonic()
    if result <= 0:
        raise GateError("deadline_exceeded")
    return min(result, DEADLINE_SECONDS)


def run_child(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    output: Path,
    deadline: float,
) -> tuple[int, bytes, bytes]:
    with OwnedProcess(
        command,
        cwd=cwd,
        env=environment,
        output_directory=output,
        max_output_bytes=MAX_CAPTURE_BYTES,
    ) as child:
        result = child.wait(timeout=remaining(deadline))
    if child.cleanup_failed:
        raise GateError("cleanup_incomplete")
    return (
        result.returncode,
        (output / "stdout.bin").read_bytes(),
        (output / "stderr.bin").read_bytes(),
    )


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GateError("invalid_report")
        result[key] = value
    return result


def supported_node(value: object) -> bool:
    if type(value) is not str or len(value) > 32:
        return False
    match = re.fullmatch(r"(24|26)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", value)
    if match is None:
        return False
    major, minor, patch = (int(item) for item in match.groups())
    return (major == 24 and (minor, patch) >= (22, 2)) or (major == 26 and minor >= 13)


def validated_report(
    raw: bytes,
    *,
    example: bool = False,
    dispatch: bool = False,
    gateway: bool = False,
    agent: bool = False,
) -> dict[str, Any]:
    if sum((example, dispatch, gateway, agent)) > 1:
        raise GateError("invalid_report")
    expected_names = (
        EXAMPLE_CASE_NAMES
        if example
        else DISPATCH_CASE_NAMES
        if dispatch
        else GATEWAY_CASE_NAMES
        if gateway
        else AGENT_CASE_NAMES
        if agent
        else CASE_NAMES
    )
    expected_mode = (
        "local_synthetic_postgres_example"
        if example
        else "local_synthetic_postgres_dispatch"
        if dispatch
        else "local_synthetic_postgres_gateway"
        if gateway
        else "local_synthetic_postgres_agent"
        if agent
        else "local_synthetic_postgres"
    )
    if not 1 <= len(raw) <= 16384:
        raise GateError("invalid_report")
    try:
        value = json.loads(raw, object_pairs_hook=unique_object)
    except (ValueError, UnicodeError, RecursionError):
        raise GateError("invalid_report") from None
    expected = {
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
    }
    if example:
        expected.add("demo_observations")
    if type(value) is not dict or set(value) != expected:
        raise GateError("invalid_report")
    integer_fields = ("tests", "passed", "failures", "errors", "skipped", "child_terminations")
    if any(type(value[key]) is not int or value[key] < 0 for key in integer_fields):
        raise GateError("invalid_report")
    duration = value["duration_seconds"]
    cases = value["case_results"]
    if (
        value["schema_version"] != 1
        or type(value["schema_version"]) is not int
        or value["mode"] != expected_mode
        or type(value["status"]) is not str
        or value["status"] not in {"passed", "failed"}
        or type(value["cleanup_complete"]) is not bool
        or type(duration) not in {int, float}
        or not 0 < duration <= DEADLINE_SECONDS
        or not math.isfinite(duration)
        or not supported_node(value["node_version"])
        or type(cases) is not list
        or value["tests"] != len(cases)
        or value["tests"] != value["passed"] + value["failures"] + value["errors"]
    ):
        raise GateError("invalid_report")
    observed_names = []
    for case in cases:
        if (
            type(case) is not dict
            or set(case) != {"name", "status", "code"}
            or type(case["name"]) is not str
            or case["name"] not in expected_names
            or type(case["status"]) is not str
            or case["status"] not in {"passed", "failed"}
            or type(case["code"]) is not str
            or case["code"] not in {"ok", "assertion_failed", "test_timeout", "setup_failed"}
            or (case["status"] == "passed") != (case["code"] == "ok")
        ):
            raise GateError("invalid_report")
        observed_names.append(case["name"])
    if len(set(observed_names)) != len(observed_names):
        raise GateError("invalid_report")
    if (
        value["passed"] != sum(case["status"] == "passed" for case in cases)
        or value["failures"] != sum(case["code"] == "assertion_failed" for case in cases)
        or value["errors"]
        != sum(case["code"] in {"test_timeout", "setup_failed"} for case in cases)
        or value["skipped"] != 0
    ):
        raise GateError("invalid_report")
    if value["status"] == "passed" and (
        tuple(observed_names) != expected_names
        or value["passed"] != len(expected_names)
        or value["failures"] != 0
        or value["errors"] != 0
        or value["skipped"] != 0
        or value["child_terminations"]
        != (0 if example else 1 if dispatch or gateway or agent else 4)
        or value["cleanup_complete"] is not True
        or any(case["status"] != "passed" for case in cases)
    ):
        raise GateError("invalid_report")
    if example:
        observations = value["demo_observations"]
        keys = {
            "phase",
            "receipt_id",
            "operation_key",
            "acceptance_sequence",
            "replayed",
            "processing_state",
            "execution",
        }
        uuid_pattern = r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
        if type(observations) is not list or len(observations) > 2:
            raise GateError("invalid_report")
        for position, observation in enumerate(observations):
            if type(observation) is not dict or set(observation) != keys:
                raise GateError("invalid_report")
            if (
                observation["phase"] != ("accepted" if position == 0 else "replayed")
                or type(observation["replayed"]) is not bool
                or observation["replayed"] != (position == 1)
                or observation["processing_state"] != "pending"
                or observation["execution"] != "not_executed"
                or any(
                    type(observation[key]) is not str
                    or re.fullmatch(uuid_pattern, observation[key]) is None
                    for key in ("receipt_id", "operation_key")
                )
                or type(observation["acceptance_sequence"]) is not str
                or re.fullmatch(r"[1-9][0-9]{0,18}", observation["acceptance_sequence"]) is None
                or int(observation["acceptance_sequence"]) > 9223372036854775807
            ):
                raise GateError("invalid_report")
            if position == 1 and any(
                observation[key] != observations[0][key]
                for key in ("receipt_id", "operation_key", "acceptance_sequence")
            ):
                raise GateError("invalid_report")
        if value["status"] == "passed" and len(observations) != 2:
            raise GateError("invalid_report")
    return value


def retain_report(root: Path, path: Path, report: dict[str, Any]) -> None:
    target = path if path.is_absolute() else root / path
    target = target.absolute()
    allowed = root / ".local/validation/p2-postgres"
    if ".." in target.parts or not target.is_relative_to(allowed):
        raise GateError("unsafe_evidence_path")
    private_directory(target.parent)
    payload = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
    with os.fdopen(
        os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb"
    ) as stream:
        stream.write(payload)


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--example",
        action="store_true",
        help="Run only the standalone public-port and fresh-process example cases",
    )
    selection.add_argument(
        "--dispatch",
        action="store_true",
        help="Run only recoverable committed-inbox dispatch cases",
    )
    selection.add_argument(
        "--gateway", action="store_true", help="Run only actual gateway socket/restart cases"
    )
    selection.add_argument(
        "--agent", action="store_true", help="Run only actual independent agent-process recovery"
    )
    args = parser.parse_args(argv)
    started = time.monotonic()
    deadline = started + DEADLINE_SECONDS
    report: dict[str, Any]
    try:
        setup = load_setup(root)
        try:
            values = setup.load_settings()
        except setup.SetupError:
            raise GateError("missing_setup") from None
        project = root / "projects/channel-continuity"
        compiler = project / "node_modules/typescript/bin/tsc"
        node = shutil.which("node")
        if (
            node is None
            or not compiler.is_file()
            or not (project / "tsconfig.pg.json").is_file()
            or not (project / "tests/pg_inbox_cases.ts").is_file()
            or not (project / "tsconfig.examples.json").is_file()
            or not (project / "examples/fake-carrier.ts").is_file()
        ):
            raise GateError("missing_setup")
        scratch = project / ".local/p2-check"
        private_directory(scratch)
        with tempfile.TemporaryDirectory(prefix="run-", dir=scratch) as temporary:
            work = Path(temporary)
            compiled = work / "compiled"
            # Build declared public exports and the example from this checkout before
            # a new process resolves the package self-reference. No stale dist proof.
            for stage, configuration in (
                ("public", "tsconfig.json"),
                ("example", "tsconfig.examples.json"),
            ):
                child_code, _, _ = run_child(
                    [node, str(compiler), "--project", str(project / configuration)],
                    cwd=project,
                    environment=base_environment(),
                    output=work / ("compile-" + stage),
                    deadline=deadline,
                )
                if child_code != 0:
                    raise GateError("compile_failed")
            child_code, _, _ = run_child(
                [
                    node,
                    str(compiler),
                    "--project",
                    str(project / "tsconfig.pg.json"),
                    "--outDir",
                    str(compiled),
                ],
                cwd=project,
                environment=base_environment(),
                output=work / "compile",
                deadline=deadline,
            )
            if child_code != 0:
                raise GateError("compile_failed")
            child_code, output, errors = run_child(
                [
                    node,
                    str(compiled / "tests/pg_inbox_cases.js"),
                    *(
                        ["--example"]
                        if args.example
                        else ["--dispatch"]
                        if args.dispatch
                        else ["--gateway"]
                        if args.gateway
                        else ["--agent"]
                        if args.agent
                        else []
                    ),
                ],
                cwd=project,
                environment={
                    **child_environment(values),
                    "P2_AGENT_WORKER_MODULE": str(
                        project / "tests/fixtures/scripted-agent-worker.mjs"
                    ),
                },
                output=work / "postgres",
                deadline=deadline,
            )
            report = validated_report(
                output,
                example=args.example,
                dispatch=args.dispatch,
                gateway=args.gateway,
                agent=args.agent,
            )
            if errors or child_code != (0 if report["status"] == "passed" else 1):
                raise GateError("runner_failed")
        # Temporary captures are gone before any result is retained or printed.
        if args.report is not None:
            retain_report(root, args.report, report)
        print(json.dumps(report, sort_keys=True))
        return 0 if report["status"] == "passed" else 1
    except GateError as error:
        code = error.code
    except ProcessControlError:
        code = "runner_failed"
    except Exception:  # noqa: BLE001 - Secret-safe outer host-tooling boundary.
        code = "gate_failed"
    print(
        json.dumps(
            {
                "status": "failed",
                "code": code,
                "mode": "local_synthetic_postgres_example"
                if args.example
                else "local_synthetic_postgres_dispatch"
                if args.dispatch
                else "local_synthetic_postgres_gateway"
                if args.gateway
                else "local_synthetic_postgres_agent"
                if args.agent
                else "local_synthetic_postgres",
            }
        )
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
