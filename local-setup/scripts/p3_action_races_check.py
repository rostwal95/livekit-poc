"""Explicit P3 protected-action race gate; no provider calls or new authority.

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
MODE = "local_synthetic_p3_action_races"
CASE_NAMES = (
    "validated_a_b_revision_first_atomic_rejection",
    "valid_b_exact_confirmation_effect_progress",
    "a_intent_first_b_revision_rejected",
    "committed_revision_boundary_original_receipt",
    "preintent_cancel_zero_authority",
    "postintent_predispatch_cancel_zero_apply",
    "after_claim_cancel_zero_apply",
    "postreservation_cancel_original_apply",
    "known_external_success_late_cancel_deadline",
    "action_precommit_kill_rollback_progress",
    "action_postcommit_kill_original_receipt",
    "supplier_commit_kill_fresh_lookup_no_reapply",
    "changed_confirmation_scope_conflicts_zero_new_effect",
    "waiter_abort_retains_guard_io_cleanup",
    "result_receiver_distinct_from_supplier_effect",
    "independent_full_identity_reconciliation_cleanup",
)
MODE_ORDER = (
    "install",
    "prepare-b-first",
    "action-b-first",
    "revise-b-first",
    "lock-b-first",
    "finish-b-first",
    "prepare-a-first",
    "action-a-first",
    "revise-a-first",
    "lock-a-first",
    "finish-a-first",
    "cancel-before-intent",
    "prepare-claim",
    "worker-claim",
    "cancel-claim",
    "prepare-reserved",
    "worker-reserved",
    "cancel-reserved",
    "prepare-applied",
    "worker-applied",
    "cancel-applied",
    "recover-applied",
    "prepare-precommit",
    "action-precommit",
    "recover-precommit",
    "prepare-postcommit",
    "action-postcommit",
    "recover-postcommit",
    "owned-lifetime",
    "owner-check",
    "cleanup",
)
OWNER_MODES = frozenset(["install", "lock-b-first", "lock-a-first", "owner-check", "cleanup"])
COMMON = frozenset({"P3_RACE_WORK_SCHEMA", "P3_RACE_CASE_SCHEMA", "P3_RACE_DIRECTORY"})
BARRIERS = {
    "action-b-first": "a_before_locks_b_first",
    "action-a-first": "a_before_locks_a_first",
    "revise-b-first": "b_before_revise_b_first",
    "revise-a-first": "b_before_revise_a_first",
    "lock-b-first": "case_admission_b_first",
    "lock-a-first": "case_admission_a_first",
    "worker-claim": "worker_claim",
    "worker-reserved": "worker_reserved",
    "worker-applied": "supplier_committed",
    "action-precommit": "action_before_commit",
    "action-postcommit": "action_after_commit",
}
MODE_KEYS = {
    mode: COMMON
    | (set() if mode in OWNER_MODES else {"P3_RACE_TOKEN"})
    | ({"P3_RACE_BARRIER"} if mode in BARRIERS else set())
    for mode in MODE_ORDER
}
RESPONSES: dict[str, dict[str, Any] | None] = {
    "install": {"status": "passed", "work_version": 4, "case_version": 4},
    "prepare-b-first": {"status": "passed", "scenario": "b_first", "revision": 2},
    "prepare-a-first": {"status": "passed", "scenario": "a_first", "revision": 2},
    "action-b-first": {"status": "passed", "scenario": "b_first", "action_code": "stale_revision"},
    "revise-b-first": {"status": "passed", "scenario": "b_first", "case_revision": 4},
    "lock-b-first": {
        "status": "passed",
        "order": "revision_first",
        "waiters": 2,
        "blocking_graphs": 1,
    },
    "finish-b-first": {
        "status": "passed",
        "cases": [
            "validated_a_b_revision_first_atomic_rejection",
            "valid_b_exact_confirmation_effect_progress",
        ],
    },
    "action-a-first": {"status": "passed", "scenario": "a_first", "action_committed": True},
    "revise-a-first": {
        "status": "passed",
        "scenario": "a_first",
        "revision_code": "intent_committed",
    },
    "lock-a-first": {
        "status": "passed",
        "order": "intent_first",
        "waiters": 2,
        "blocking_graphs": 1,
    },
    "finish-a-first": {
        "status": "passed",
        "cases": [
            "a_intent_first_b_revision_rejected",
            "committed_revision_boundary_original_receipt",
            "postintent_predispatch_cancel_zero_apply",
            "result_receiver_distinct_from_supplier_effect",
        ],
    },
    "cancel-before-intent": {"status": "passed", "cases": ["preintent_cancel_zero_authority"]},
    "prepare-claim": {"status": "passed", "scenario": "claim", "intent_committed": True},
    "prepare-reserved": {"status": "passed", "scenario": "reserved", "intent_committed": True},
    "prepare-applied": {"status": "passed", "scenario": "applied", "intent_committed": True},
    "prepare-precommit": {"status": "passed", "scenario": "precommit", "intent_committed": False},
    "prepare-postcommit": {"status": "passed", "scenario": "postcommit", "intent_committed": False},
    "worker-claim": {
        "status": "passed",
        "cases": ["after_claim_cancel_zero_apply"],
        "state": "cancelled",
        "worker_code": "transition_conflict",
    },
    "cancel-claim": {"status": "passed", "disposition": "cancelled_before_dispatch"},
    "worker-reserved": {
        "status": "passed",
        "cases": ["postreservation_cancel_original_apply"],
        "state": "succeeded",
        "supplier_applied_calls": 1,
    },
    "cancel-reserved": {"status": "passed", "disposition": "requested_best_effort"},
    "worker-applied": None,
    "cancel-applied": {
        "status": "passed",
        "disposition": "requested_best_effort",
        "supplier_applied_calls": 1,
        "work_expired": True,
        "lease_expired": True,
    },
    "recover-applied": {
        "status": "passed",
        "cases": [
            "known_external_success_late_cancel_deadline",
            "supplier_commit_kill_fresh_lookup_no_reapply",
        ],
        "state": "succeeded",
        "supplier_applied_calls": 1,
    },
    "action-precommit": None,
    "recover-precommit": {
        "status": "passed",
        "cases": ["action_precommit_kill_rollback_progress"],
        "supplier_applied_calls": 1,
    },
    "action-postcommit": None,
    "recover-postcommit": {
        "status": "passed",
        "cases": [
            "action_postcommit_kill_original_receipt",
            "changed_confirmation_scope_conflicts_zero_new_effect",
        ],
        "supplier_applied_calls": 1,
    },
    "owned-lifetime": {
        "status": "passed",
        "cases": ["waiter_abort_retains_guard_io_cleanup"],
        "variants": 2,
        "cleanup_complete": True,
    },
    "owner-check": {
        "status": "passed",
        "cases": ["independent_full_identity_reconciliation_cleanup"],
        "exact_reconciliation": True,
    },
    "cleanup": {"status": "passed", "cleanup_complete": True},
}

GateError = core.GateError


def validate_child_environment(environment: dict[str, str], mode: str) -> None:
    if mode not in MODE_KEYS:
        raise GateError("invalid_child_mode")
    password = "P3_RACE_OWNER_PASSWORD" if mode in OWNER_MODES else "P3_RACE_RUNTIME_PASSWORD"
    required = {"P3_RACE_PG_PORT", password, *MODE_KEYS[mode]}
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
    password = "P3_RACE_OWNER_PASSWORD" if owner else "P3_RACE_RUNTIME_PASSWORD"
    try:
        environment = {
            **core.base_environment(),
            "P3_RACE_PG_PORT": values["POSTGRES_PORT"],
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
        "supplier_authority",
        "runtime_change",
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
        or value["child_terminations"] != 3
        or value["blocking_graphs_observed"] != 2
        or value["cleanup_complete"] is not True
        or type(duration) not in (int, float)
        or not 0 < duration <= DEADLINE_SECONDS
        or not math.isfinite(duration)
        or value["provider_calls"] is not False
        or value["source_authority"] != "actual_public_p1_work_case_action_and_leased_effects"
        or value["supplier_authority"] != "independent_cooperating_sqlite_per_schedule"
        or value["runtime_change"] != "validation_only_existing_p3_p1_guards"
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
        root / ".local/validation/p3-action-races"
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
        root / ".local/validation/p3-action-races"
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


PROOF_FILES = ("graph_b_first.json", "graph_a_first.json", "owner_proof.json")
MAX_PROOF_BYTES = 4096


def proof_target(root: Path, target: Path) -> Path:
    report = (target if target.is_absolute() else root / target).absolute()
    if ".." in report.parts or not report.is_relative_to(
        root / ".local/validation/p3-action-races"
    ):
        raise GateError("unsafe_evidence_path")
    folder = report.with_name(report.stem + "-artifacts")
    core.private_directory(folder.parent)
    if folder.exists() or folder.is_symlink():
        raise GateError("existing_proof")
    return folder


def validate_proof(name: str, raw: bytes) -> None:
    if name not in PROOF_FILES or type(raw) is not bytes or not 1 <= len(raw) <= MAX_PROOF_BYTES:
        raise GateError("invalid_proof")
    try:
        value = json.loads(raw, object_pairs_hook=core.unique_object)
        if name == "owner_proof.json":
            if (
                type(value) is not dict
                or set(value)
                != {
                    "status",
                    "exact_reconciliation",
                    "actions",
                    "applied",
                    "receipts",
                    "results",
                    "reconciliation_sha256",
                }
                or value["status"] != "passed"
                or value["exact_reconciliation"] is not True
                or any(
                    type(value[key]) is not int or value[key] != expected
                    for key, expected in (
                        ("actions", 10),
                        ("applied", 6),
                        ("receipts", 2),
                        ("results", 12),
                    )
                )
                or type(value["reconciliation_sha256"]) is not str
                or re.fullmatch(r"[0-9a-f]{64}", value["reconciliation_sha256"]) is None
            ):
                raise GateError("invalid_proof")
        else:
            if type(value) is not list or len(value) != 2:
                raise GateError("invalid_proof")
            for row in value:
                if (
                    type(row) is not dict
                    or set(row) != {"pid", "blockers"}
                    or type(row["pid"]) is not int
                    or not 1 <= row["pid"] <= 2147483647
                    or type(row["blockers"]) is not list
                    or not 1 <= len(row["blockers"]) <= 2
                    or any(
                        type(pid) is not int or not 1 <= pid <= 2147483647
                        for pid in row["blockers"]
                    )
                    or len(row["blockers"]) != len(set(row["blockers"]))
                    or row["pid"] in row["blockers"]
                ):
                    raise GateError("invalid_proof")
            pids = {row["pid"] for row in value}
            first, second = sorted(value, key=lambda row: len(row["blockers"]))
            if (
                len(pids) != 2
                or len(first["blockers"]) != 1
                or len(second["blockers"]) != 2
                or first["blockers"][0] in pids
                or set(second["blockers"]) != {first["blockers"][0], first["pid"]}
            ):
                raise GateError("invalid_proof")
    except (ValueError, TypeError, UnicodeError, RecursionError, KeyError):
        raise GateError("invalid_proof") from None


def retain_proof(root: Path, target: Path, work: Path) -> str:
    """Retain three closed structural proofs only; no fixture databases or raw payloads."""
    folder = proof_target(root, target)
    snapshots: dict[str, bytes] = {}
    for name in PROOF_FILES:
        source = work / name
        info = source.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise GateError("invalid_proof")
        with os.fdopen(os.open(source, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
            raw = stream.read(MAX_PROOF_BYTES + 1)
        validate_proof(name, raw)
        snapshots[name] = raw
    folder.mkdir(mode=0o700)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "status": "retained_structural_proof",
        "maximum_file_bytes": MAX_PROOF_BYTES,
        "raw_request_confirmation_credentials_retained": False,
        "files": [],
    }
    for name, raw in snapshots.items():
        with os.fdopen(
            os.open(folder / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600),
            "wb",
        ) as stream:
            stream.write(raw)
        manifest["files"].append(
            {"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        )
    with os.fdopen(
        os.open(
            folder / "manifest.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        ),
        "w",
    ) as stream:
        json.dump(manifest, stream, sort_keys=True, indent=2)
        stream.write("\n")
    return str(folder.relative_to(root))


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--diagnostic",
        action="store_true",
        help="Retain redacted failure captures; never qualifies",
    )
    args = parser.parse_args(argv)
    started = time.monotonic()
    deadline = started + DEADLINE_SECONDS
    work_deadline = deadline - 15
    target = args.report or Path(".local/validation/p3-action-races/" + uuid4().hex + ".json")
    cleanup_complete = False
    diagnostic_state: dict[str, Any] = (
        {"diagnostic": True, "diagnostics_retained": False, "diagnostics_code": "not_available"}
        if args.diagnostic
        else {}
    )
    try:
        report_target(root, target)
        proof_target(root, target)
        if args.diagnostic:
            diagnostic_target(root, target)
        setup = core.load_setup(root)
        try:
            values = setup.load_settings()
        except setup.SetupError:
            raise GateError("missing_setup") from None
        cases = root / "projects/delegation-reliability/tests/pg_action_race_cases.py"
        helper = root / "local-setup/scripts/p3_action_case_fixture.py"
        interpreter = root / ".venv/bin/python"
        if not all(p.is_file() for p in (cases, helper, interpreter)):
            raise GateError("missing_setup")
        scratch = root / ".local/p3-action-races-check"
        core.private_directory(scratch)
        with tempfile.TemporaryDirectory(prefix="run-", dir=scratch) as temporary:
            work = Path(temporary)
            budget = core.CaptureBudget()
            context = {
                "P3_RACE_WORK_SCHEMA": "p1_work_actionrace_" + uuid4().hex,
                "P3_RACE_CASE_SCHEMA": "p3_completion_" + uuid4().hex,
                "P3_RACE_TOKEN": secrets.token_urlsafe(32),
                "P3_RACE_DIRECTORY": str(work),
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
            ) + (context["P3_RACE_TOKEN"],)
            with diagnostic_failure(
                root, target, work, local_redactions, diagnostic_state, enabled=args.diagnostic
            ):
                terminations = 0
                blocking_graphs = 0
                seen: set[str] = set()
                launched: set[str] = set()

                def reserve_mode(mode: str) -> None:
                    if mode not in MODE_KEYS or mode in launched or len(launched) >= 32:
                        raise GateError("invalid_child_mode")
                    launched.add(mode)

                def call(mode: str) -> dict[str, Any]:
                    reserve_mode(mode)
                    return run_child(
                        [*command, mode],
                        cwd=work,
                        environment=child_environment(values, mode=mode, context=context),
                        output=work / mode,
                        deadline=deadline if mode == "cleanup" else work_deadline,
                        budget=budget,
                    )

                def accept(mode: str, value: dict[str, Any]) -> None:
                    expected = RESPONSES[mode]
                    if expected is None or not exact_child(value, expected):
                        raise GateError("invalid_report")
                    names = expected.get("cases", [])
                    if type(names) is not list or any(
                        type(name) is not str or name not in CASE_NAMES or name in seen
                        for name in names
                    ):
                        raise GateError("invalid_report")
                    seen.update(names)

                def expect(mode: str) -> None:
                    accept(mode, call(mode))

                @contextmanager
                def held(mode: str) -> Iterator[tuple[OwnedProcess, int]]:
                    reserve_mode(mode)
                    context["P3_RACE_BARRIER"] = str(work / (BARRIERS[mode] + ".reached"))
                    limit = budget.reserve(4096)
                    with OwnedProcess(
                        [*command, mode],
                        cwd=work,
                        env=child_environment(values, mode=mode, context=context),
                        output_directory=work / mode,
                        max_output_bytes=limit,
                    ) as child:
                        yield child, limit

                def collect(mode: str, child: OwnedProcess, limit: int) -> None:
                    accept(
                        mode,
                        checked_child(
                            child,
                            output=work / mode,
                            limit=limit,
                            budget=budget,
                            deadline=work_deadline,
                            mode=mode,
                        ),
                    )

                def wait(child: OwnedProcess, barrier: FileBarrier) -> None:
                    child.wait_for_barrier(barrier, timeout=min(15, core.remaining(work_deadline)))

                def kill_at(mode: str) -> None:
                    nonlocal terminations
                    barrier = FileBarrier(work, BARRIERS[mode])
                    with held(mode) as (child, limit):
                        wait(child, barrier)
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

                def race(suffix: str) -> None:
                    nonlocal blocking_graphs
                    expect("prepare-" + suffix)
                    a_mode, b_mode, lock_mode = (
                        "action-" + suffix,
                        "revise-" + suffix,
                        "lock-" + suffix,
                    )
                    a_barrier, b_barrier, lock_barrier = (
                        FileBarrier(work, BARRIERS[mode]) for mode in (a_mode, b_mode, lock_mode)
                    )
                    label = suffix.replace("-", "_")
                    first_wait, graph = (
                        FileBarrier(work, "first_wait_" + label),
                        FileBarrier(work, "order_graph_" + label),
                    )
                    with held(a_mode) as (a, a_limit):
                        wait(a, a_barrier)
                        with held(b_mode) as (b, b_limit):
                            wait(b, b_barrier)
                            # The locker is already the observer. No interpreter starts
                            # while either public writer is queued behind its lock.
                            with held(lock_mode) as (locker, lock_limit):
                                wait(locker, lock_barrier)
                                if suffix == "b-first":
                                    b.release_barrier(b_barrier)
                                else:
                                    a.release_barrier(a_barrier)
                                wait(locker, first_wait)
                                if suffix == "b-first":
                                    a.release_barrier(a_barrier)
                                else:
                                    b.release_barrier(b_barrier)
                                wait(locker, graph)
                                locker.release_barrier(lock_barrier)
                                collect(lock_mode, locker, lock_limit)
                                blocking_graphs += 1
                                collect(a_mode, a, a_limit)
                                collect(b_mode, b, b_limit)
                    expect("finish-" + suffix)

                def cancelled_worker(suffix: str) -> None:
                    expect("prepare-" + suffix)
                    mode = "worker-" + suffix
                    barrier = FileBarrier(work, BARRIERS[mode])
                    with held(mode) as (child, limit):
                        wait(child, barrier)
                        expect("cancel-" + suffix)
                        child.release_barrier(barrier)
                        collect(mode, child, limit)

                try:
                    expect("install")
                    race("b-first")
                    race("a-first")
                    expect("cancel-before-intent")
                    cancelled_worker("claim")
                    cancelled_worker("reserved")
                    expect("prepare-applied")
                    kill_at("worker-applied")
                    expect("cancel-applied")
                    expect("recover-applied")
                    for suffix in ("precommit", "postcommit"):
                        expect("prepare-" + suffix)
                        kill_at("action-" + suffix)
                        expect("recover-" + suffix)
                    expect("owned-lifetime")
                    expect("owner-check")
                    if seen != set(CASE_NAMES):
                        raise GateError("invalid_report")
                finally:
                    original = sys.exception()
                    try:
                        cleanup_complete = exact_child(
                            call("cleanup"), {"status": "passed", "cleanup_complete": True}
                        )
                    except Exception:
                        cleanup_complete = False
                        if original is None:
                            raise
                if not cleanup_complete:
                    raise GateError("cleanup_incomplete")
                if launched != set(MODE_KEYS):
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
                            "child_terminations": terminations,
                            "blocking_graphs_observed": blocking_graphs,
                            "case_results": [
                                {"name": name, "status": "passed", "code": "ok"}
                                for name in CASE_NAMES
                            ],
                            "source_authority": "actual_public_p1_work_case_action_and_leased_effects",
                            "supplier_authority": "independent_cooperating_sqlite_per_schedule",
                            "runtime_change": "validation_only_existing_p3_p1_guards",
                            "provider_calls": False,
                        }
                    ).encode()
                )
                if args.diagnostic:
                    raise GateError("diagnostic_not_qualification")
                retain_proof(root, target, work)
        retain_report(root, target, report)
        print(json.dumps(report, sort_keys=True))
        return 0
    except GateError as error:
        code = error.code
    except ProcessControlError:
        code = "runner_failed"
    except Exception:  # noqa: BLE001 - private dependency diagnostics never enter reports
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
