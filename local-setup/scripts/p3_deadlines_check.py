"""Explicit P3 deadline/cancellation actual gate; no provider or runtime change.

One bounded Node fault peer intentionally ignores business cancellation. P1 public
ports remain the only execution/action authority. Parent owns every process,
credential split, temporal barrier, proof byte and cleanup budget.
"""

from __future__ import annotations

import argparse
import hashlib
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
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p3_coordinator_check as core

from harness.process_control import FileBarrier, OwnedProcess, ProcessControlError

ROOT = Path(__file__).resolve().parents[2]
DEADLINE_SECONDS = 180.0
MAX_REPORT_BYTES = 32768
GateError = core.GateError
MODE = "local_synthetic_p3_deadlines_cancellation"
CASE_NAMES = (
    "deadline_before_issue_zero_attempt",
    "admission_wait_uses_authority_clock",
    "issued_deadline_before_http_zero_invoke",
    "issued_lease_before_http_zero_invoke",
    "cancel_before_issue_zero_attempt",
    "cancel_after_issue_before_http_zero_invoke",
    "deadline_during_http_late_result_retained",
    "producer_timestamp_never_restores_eligibility",
    "lease_during_http_result_ineligible",
    "cancel_ack_running_ignored_result_retained",
    "cancel_ack_loss_remains_unknown",
    "waiter_timeout_retains_io_without_business_cancel",
    "waiter_cancel_retains_io_without_business_cancel",
    "original_issue_result_replay_no_new_invoke",
    "eligible_result_not_retroactive_lease_expiry",
    "valid_current_b_confirmed_effect_progress",
    "post_late_commit_kill_fresh_lookup_only",
    "independent_scope_refresh_metrics_cleanup",
)
MODE_ORDER = (
    "install",
    "seed",
    "before-issue",
    "clock-lock",
    "lock-issue",
    "before-http",
    "invoke-expiry",
    "wait-expiry",
    "invoke-lease",
    "wait-lease",
    "invoke-cancel",
    "cancel-ack",
    "invoke-cancel-lost",
    "cancel-lost",
    "caller-timeout",
    "caller-cancel",
    "known-replay",
    "crash-late",
    "verify-crash",
    "useful-current",
    "owner-check",
    "cleanup",
)
MODES = frozenset(MODE_ORDER)
OWNER_MODES = frozenset(("install", "clock-lock", "owner-check", "cleanup"))
BARRIERS = {
    "clock-lock": "deadline_lock_ready",
    "lock-issue": "issue_before_sql",
    "caller-timeout": "caller_timeout_observed",
    "caller-cancel": "caller_cancel_observed",
    "crash-late": "late_result_commit",
}
RESPONSES: dict[str, dict[str, Any] | None] = {
    "install": {"status": "passed", "work_version": 4, "case_version": 4, "projection_version": 3},
    "seed": {"status": "passed", "case_revision": 2},
    "before-issue": {
        "status": "passed",
        "cases": ["deadline_before_issue_zero_attempt", "cancel_before_issue_zero_attempt"],
    },
    "clock-lock": {"status": "passed", "waiters": 1, "authority_deadline_crossed": True},
    "lock-issue": {
        "status": "passed",
        "cases": ["admission_wait_uses_authority_clock"],
        "code": "expired",
    },
    "before-http": {
        "status": "passed",
        "cases": [
            "issued_deadline_before_http_zero_invoke",
            "issued_lease_before_http_zero_invoke",
            "cancel_after_issue_before_http_zero_invoke",
        ],
    },
    "invoke-expiry": {
        "status": "passed",
        "cases": [
            "deadline_during_http_late_result_retained",
            "producer_timestamp_never_restores_eligibility",
        ],
        "disposition": "expired",
    },
    "wait-expiry": {"status": "passed", "authority_expired": True, "target": "$expiry_or_crash"},
    "invoke-lease": {
        "status": "passed",
        "cases": ["lease_during_http_result_ineligible"],
        "disposition": "lease_expired",
    },
    "wait-lease": {"status": "passed", "authority_lease_expired": True},
    "invoke-cancel": {
        "status": "passed",
        "cases": ["cancel_ack_running_ignored_result_retained"],
        "disposition": "cancelled",
    },
    "cancel-ack": {
        "status": "passed",
        "cancel_requested": True,
        "remote_ack": "observed",
        "remote_state": "running",
        "remote_durable": False,
    },
    "invoke-cancel-lost": {
        "status": "passed",
        "cases": ["cancel_ack_loss_remains_unknown"],
        "disposition": "cancelled",
    },
    "cancel-lost": {
        "status": "passed",
        "cancel_requested": True,
        "remote_ack": "unknown",
        "remote_code": "invalid_response",
    },
    "caller-timeout": {
        "status": "passed",
        "cases": ["waiter_timeout_retains_io_without_business_cancel"],
        "disposition": "eligible_at_commit",
    },
    "caller-cancel": {
        "status": "passed",
        "cases": ["waiter_cancel_retains_io_without_business_cancel"],
        "disposition": "eligible_at_commit",
    },
    "known-replay": {
        "status": "passed",
        "cases": [
            "original_issue_result_replay_no_new_invoke",
            "eligible_result_not_retroactive_lease_expiry",
        ],
    },
    "crash-late": None,
    "verify-crash": {
        "status": "passed",
        "cases": ["post_late_commit_kill_fresh_lookup_only"],
        "disposition": "expired",
    },
    "useful-current": {
        "status": "passed",
        "cases": ["valid_current_b_confirmed_effect_progress"],
        "supplier_calls": 1,
        "supplier_applied": 1,
    },
    "owner-check": {
        "status": "passed",
        "cases": ["independent_scope_refresh_metrics_cleanup"],
        "exact_reconciliation": True,
    },
    "cleanup": {"status": "passed", "cleanup_complete": True},
}
PEER_COUNTS = {
    "invocations": 9,
    "completed": 9,
    "cancel_requests": 2,
    "cancel_acknowledgements": 1,
    "cancel_ack_lost": 1,
    "status_observations": 1,
    "rejected": 2,
    "active": 0,
    "requests": 0,
    "sockets": 0,
}
COMMON = frozenset(
    {
        "P3_DEADLINE_WORK_SCHEMA",
        "P3_DEADLINE_CASE_SCHEMA",
        "P3_DEADLINE_SCHEMA",
        "P3_DEADLINE_DIRECTORY",
    }
)
MODE_KEYS = {
    mode: COMMON
    | (set() if mode in OWNER_MODES else {"P3_DEADLINE_TOKEN", "P3_DEADLINE_PORT"})
    | ({"P3_DEADLINE_BARRIER"} if mode in BARRIERS else set())
    | ({"P3_DEADLINE_TARGET"} if mode == "wait-expiry" else set())
    for mode in MODE_ORDER
}
CAPTURE_NAMES = tuple(mode for mode in MODE_ORDER if mode != "wait-expiry") + (
    "wait-expiry-expiry",
    "wait-expiry-crash",
    "peer",
)
PROOF_FILES = ("authority-proof.json", "peer-observations.json", "eligibility-lock-proof.json")
MAX_PROOF_BYTES = 32768
PEER_BASE_KEYS = frozenset(
    {
        "PATH",
        "HOME",
        "TMPDIR",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
        "NO_COLOR",
        "CI",
        "__CF_USER_TEXT_ENCODING",
    }
)


def peer_base_environment() -> dict[str, str]:
    return {key: value for key, value in core.base_environment().items() if key in PEER_BASE_KEYS}


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
    if ".." in target.parts or not target.is_relative_to(root / ".local/validation/p3-deadlines"):
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
    if ".." in report.parts or not report.is_relative_to(root / ".local/validation/p3-deadlines"):
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
    for mode in CAPTURE_NAMES:
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


def proof_target(root: Path, target: Path) -> Path:
    report = (target if target.is_absolute() else root / target).absolute()
    if ".." in report.parts or not report.is_relative_to(root / ".local/validation/p3-deadlines"):
        raise GateError("unsafe_evidence_path")
    folder = report.with_name(report.stem + "-artifacts")
    core.private_directory(folder.parent)
    if folder.exists() or folder.is_symlink():
        raise GateError("existing_proof")
    return folder


def validate_child_environment(environment: dict[str, str], mode: str) -> None:
    if mode not in MODE_KEYS:
        raise GateError("invalid_child_mode")
    password = (
        "P3_DEADLINE_OWNER_PASSWORD" if mode in OWNER_MODES else "P3_DEADLINE_RUNTIME_PASSWORD"
    )
    required = {*MODE_KEYS[mode], password, "P3_DEADLINE_PG_PORT"}
    if (
        not required <= set(environment)
        or set(environment) - required - core.BASE_ENVIRONMENT_KEYS
        or any(
            type(v) is not str or not 1 <= len(v) <= 4096 or any(c in v for c in ("\0", "\r", "\n"))
            for v in environment.values()
        )
    ):
        raise GateError("unsafe_child_environment")
    if mode == "wait-expiry" and environment["P3_DEADLINE_TARGET"] not in {"expiry", "crash"}:
        raise GateError("invalid_child_mode")


def child_environment(
    values: dict[str, str], context: dict[str, str], *, mode: str
) -> dict[str, str]:
    allowed = COMMON | {
        "P3_DEADLINE_TOKEN",
        "P3_DEADLINE_PORT",
        "P3_DEADLINE_BARRIER",
        "P3_DEADLINE_TARGET",
    }
    if type(context) is not dict or set(context) - allowed or mode not in MODES:
        raise GateError("unsafe_child_environment")
    try:
        owner = mode in OWNER_MODES
        env = {
            **core.base_environment(),
            "P3_DEADLINE_PG_PORT": values["POSTGRES_PORT"],
            "P3_DEADLINE_OWNER_PASSWORD" if owner else "P3_DEADLINE_RUNTIME_PASSWORD": values[
                "POSTGRES_MIGRATION_PASSWORD" if owner else "POSTGRES_PASSWORD"
            ],
            **{name: context[name] for name in MODE_KEYS[mode]},
        }
    except KeyError:
        raise GateError("missing_setup") from None
    validate_child_environment(env, mode)
    return env


def validated_stage(raw: bytes, mode: str, target: str | None = None) -> dict[str, Any]:
    if mode not in MODES or RESPONSES[mode] is None:
        raise GateError("invalid_child_mode")
    value = core.decode(raw)
    expected = RESPONSES[mode]
    assert expected is not None
    if mode == "wait-expiry":
        if target not in {"expiry", "crash"}:
            raise GateError("invalid_child_mode")
        expected = {**expected, "target": target}
    elif target is not None:
        raise GateError("invalid_child_mode")
    if not exact_child(value, expected):
        raise GateError("invalid_report")
    return value


def validated_report(raw: bytes) -> dict[str, Any]:
    value = core.decode(raw)
    fields = {
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
        "case_results",
        "child_terminations",
        "blocking_graphs_observed",
        "peer_invocations",
        "peer_completed",
        "remote_cancel_acknowledgements",
        "remote_cancel_unknown",
        "provider_calls",
        "source_authority",
        "peer_authority",
        "runtime_change",
        "node_version",
    }
    if set(value) != fields:
        raise GateError("invalid_report")
    integers = {
        "schema_version": 1,
        "tests": 18,
        "passed": 18,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "child_terminations": 1,
        "blocking_graphs_observed": 1,
        "peer_invocations": 9,
        "peer_completed": 9,
        "remote_cancel_acknowledgements": 1,
        "remote_cancel_unknown": 1,
    }
    if any(type(value[k]) is not int or value[k] != v for k, v in integers.items()):
        raise GateError("invalid_report")
    d = value["duration_seconds"]
    if (
        value["status"] != "passed"
        or value["mode"] != MODE
        or value["cleanup_complete"] is not True
        or value["provider_calls"] is not False
        or type(d) not in (int, float)
        or not 0 < d <= 180
        or not math.isfinite(d)
        or not core.supported_node(value["node_version"])
        or value["source_authority"] != "actual_public_p1_work_v4_deadline_cancellation_action"
        or value["peer_authority"] != "bounded_intentionally_noncooperating_node_fault_peer"
        or value["runtime_change"] != "validation_only_existing_p3_p1_guards"
        or not exact_child(
            {"records": value["case_results"]},
            {"records": [{"name": n, "status": "passed", "code": "ok"} for n in CASE_NAMES]},
        )
    ):
        raise GateError("invalid_report")
    return value


def peer_report(raw: bytes) -> dict[str, Any]:
    v = core.decode(raw)
    if (
        set(v) != {"status", "cleanup_complete", "node_version", *PEER_COUNTS}
        or v["status"] != "passed"
        or v["cleanup_complete"] is not True
        or not core.supported_node(v["node_version"])
        or any(type(v[k]) is not int or v[k] != n for k, n in PEER_COUNTS.items())
    ):
        raise GateError("invalid_peer_report")
    return v


def proof_json(raw: bytes) -> dict[str, Any]:
    if not 1 <= len(raw) <= 32768:
        raise GateError("invalid_proof")
    value = core.decode(raw)
    if type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise GateError("invalid_proof")
    return value


LABELS = (
    "expired_before",
    "lock_wait",
    "issued_deadline",
    "issued_lease",
    "cancel_before",
    "cancel_issued",
    "expiry",
    "lease",
    "cancel",
    "cancel_lost",
    "caller_timeout",
    "caller_cancel",
    "known",
    "crash",
    "useful",
)
RESULT_LABELS = frozenset(LABELS[6:])
NO_GRANT = frozenset({"expired_before", "lock_wait", "cancel_before"})
CANCELLED_LABELS = frozenset({"cancel_before", "cancel_issued", "cancel", "cancel_lost", "known"})
PEER_RECORD_KEYS = frozenset(
    {
        "label",
        "delegation_id",
        "attempt_id",
        "input_fingerprint",
        "request_sha256",
        "result_sha256",
        "started_at_ms",
        "request_deadline_at_ms",
        "result_completed_at_ms",
        "result_ready_at_ms",
        "cancel_requested",
        "cancel_acknowledged",
        "cancel_ack_lost",
        "response_finished",
        "transport_disconnected",
        "timeliness_observed",
    }
)


def proof_uuid(value: Any) -> bool:
    if type(value) is not str:
        return False
    try:
        return str(UUID(value)) == value and UUID(value).version == 4
    except (ValueError, AttributeError):
        return False


def proof_hash(value: Any) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def proof_time(value: Any) -> bool:
    return type(value) is int and 0 < value <= 4102444800000


def proof_identifier(value: Any) -> bool:
    return (
        type(value) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value) is not None
    )


def validate_proof(name: str, raw: bytes) -> dict[str, Any]:
    """Closed synthetic evidence: missing identity is a failure, never an omitted fact."""
    if name not in PROOF_FILES:
        raise GateError("invalid_proof")
    v = proof_json(raw)
    if name == "eligibility-lock-proof.json":
        if (
            set(v)
            != {
                "schema_version",
                "owner_backend_pid",
                "waiter_backend_pid",
                "blockers",
                "work_id",
                "deadline_at_ms",
                "observed_after_wait_at_ms",
                "expected_new_grants",
            }
            or any(
                type(v[k]) is not int or not 0 < v[k] < 2**31
                for k in ("owner_backend_pid", "waiter_backend_pid")
            )
            or v["owner_backend_pid"] == v["waiter_backend_pid"]
            or type(v["blockers"]) is not list
            or len(v["blockers"]) != 1
            or type(v["blockers"][0]) is not int
            or v["blockers"] != [v["owner_backend_pid"]]
            or not proof_uuid(v["work_id"])
            or not proof_time(v["deadline_at_ms"])
            or not proof_time(v["observed_after_wait_at_ms"])
            or type(v["expected_new_grants"]) is not int
            or v["expected_new_grants"] != 0
            or v["observed_after_wait_at_ms"] < v["deadline_at_ms"]
        ):
            raise GateError("invalid_proof")
    elif name == "authority-proof.json":
        counts = {
            "work": 15,
            "grants": 12,
            "results": 9,
            "cancellations": 5,
            "events": 9,
            "projected": 9,
            "refreshes": 9,
            "intents": 1,
            "effects": 1,
        }
        if (
            set(v)
            != {
                "schema_version",
                "status",
                "source_id",
                "counts",
                "records",
                "cancellations",
                "useful",
                "clock_semantics",
            }
            or v["status"] != "passed"
            or not proof_uuid(v["source_id"])
            or not exact_child(v["counts"], counts)
            or v["clock_semantics"]
            != "P1_database_after_locks; host_and_peer_observations_non_atomic"
            or type(v["records"]) is not list
            or len(v["records"]) != 15
            or type(v["cancellations"]) is not list
            or len(v["cancellations"]) != 5
        ):
            raise GateError("invalid_proof")
        base = {
            "label",
            "scope",
            "work_id",
            "request_sha256",
            "input_fingerprint",
            "deadline_at_ms",
            "attempt_id",
            "result_sha256",
            "disposition",
            "cancel_requested",
        }
        grant = {"issue_command_id", "issued_at_ms", "lease_until_ms", "transport_sha256"}
        result = {
            "recorded_at_ms",
            "reported_completed_at_ms",
            "event_id",
            "event_sequence",
            "projected_sha256",
            "refresh_sha256",
            "refresh_classification",
            "refresh_reason",
        }
        rows: dict[str, Any] = {}
        for r in v["records"]:
            if (
                type(r) is not dict
                or type(r.get("label")) is not str
                or r["label"] not in LABELS
                or r["label"] in rows
            ):
                raise GateError("invalid_proof")
            label = r["label"]
            if (
                set(r)
                != base
                | (grant if label not in NO_GRANT else set())
                | (result if label in RESULT_LABELS else set())
                or not exact_child(
                    r["scope"], {"tenant_id": "tenant_deadline", "account_id": "account_deadline"}
                )
                or not proof_uuid(r["work_id"])
                or not proof_hash(r["request_sha256"])
                or not proof_hash(r["input_fingerprint"])
                or not proof_time(r["deadline_at_ms"])
                or type(r["cancel_requested"]) is not bool
                or r["cancel_requested"] != (label in CANCELLED_LABELS)
            ):
                raise GateError("invalid_proof")
            rows[label] = r
            if label in NO_GRANT:
                if any(r[k] is not None for k in ("attempt_id", "result_sha256", "disposition")):
                    raise GateError("invalid_proof")
                continue
            if (
                not proof_uuid(r["attempt_id"])
                or not proof_identifier(r["issue_command_id"])
                or not proof_hash(r["transport_sha256"])
                or not proof_time(r["issued_at_ms"])
                or not proof_time(r["lease_until_ms"])
                or not r["issued_at_ms"]
                < r["lease_until_ms"]
                <= min(r["issued_at_ms"] + 2500, r["deadline_at_ms"])
            ):
                raise GateError("invalid_proof")
            if label not in RESULT_LABELS:
                if r["result_sha256"] is not None or r["disposition"] is not None:
                    raise GateError("invalid_proof")
                continue
            disposition = (
                "expired"
                if label in {"expiry", "crash"}
                else "lease_expired"
                if label == "lease"
                else "cancelled"
                if label in {"cancel", "cancel_lost"}
                else "eligible_at_commit"
            )
            if (
                r["disposition"] != disposition
                or not proof_hash(r["result_sha256"])
                or not proof_hash(r["projected_sha256"])
                or not proof_hash(r["refresh_sha256"])
                or not proof_time(r["recorded_at_ms"])
                or not proof_time(r["reported_completed_at_ms"])
                or not proof_uuid(r["event_id"])
                or type(r["event_sequence"]) is not int
                or not 1 <= r["event_sequence"] <= 9
                or type(r["refresh_classification"]) is not str
                or r["refresh_classification"]
                not in {"current", "outdated", "invalidated", "unavailable", "rejected"}
                or type(r["refresh_reason"]) is not str
                or r["refresh_reason"]
                not in {
                    "candidate",
                    "clarification",
                    "revision_advanced",
                    "work_cancelled",
                    "case_cancelled",
                    "deadline_expired_local_as_of",
                    "historical_cancelled",
                    "historical_expired",
                    "historical_superseded",
                    "historical_lease_expired",
                    "attempt_advanced",
                    "case_unavailable",
                    "execution_unavailable",
                    "case_revision_unavailable",
                    "rejected_content",
                }
                or (
                    label in {"expiry", "lease", "cancel", "cancel_lost", "crash", "known"}
                    and r["refresh_classification"] == "current"
                )
                or (
                    disposition == "expired"
                    and not r["reported_completed_at_ms"]
                    < r["deadline_at_ms"]
                    <= r["recorded_at_ms"]
                )
                or (
                    disposition == "lease_expired"
                    and not r["lease_until_ms"] <= r["recorded_at_ms"] < r["deadline_at_ms"]
                )
                or (
                    disposition == "eligible_at_commit"
                    and not r["recorded_at_ms"] < r["lease_until_ms"] <= r["deadline_at_ms"]
                )
            ):
                raise GateError("invalid_proof")
        if (
            set(rows) != set(LABELS)
            or len({r["work_id"] for r in rows.values()}) != 15
            or len({rows[x]["attempt_id"] for x in LABELS if x not in NO_GRANT}) != 12
            or {rows[x]["event_sequence"] for x in RESULT_LABELS} != set(range(1, 10))
        ):
            raise GateError("invalid_proof")
        cancellation_work = set()
        cancellation_ids = set()
        for c in v["cancellations"]:
            if (
                type(c) is not dict
                or set(c) != {"work_id", "command_id", "cancellation_id", "requested_at_ms"}
                or not proof_uuid(c["work_id"])
                or not proof_uuid(c["cancellation_id"])
                or not proof_identifier(c["command_id"])
                or not proof_time(c["requested_at_ms"])
                or c["work_id"] in cancellation_work
                or c["cancellation_id"] in cancellation_ids
            ):
                raise GateError("invalid_proof")
            cancellation_work.add(c["work_id"])
            cancellation_ids.add(c["cancellation_id"])
        if cancellation_work != {rows[x]["work_id"] for x in CANCELLED_LABELS}:
            raise GateError("invalid_proof")
        u = v["useful"]
        if (
            type(u) is not dict
            or set(u)
            != {
                "action_id",
                "intent_id",
                "effect_id",
                "supplier_all_calls",
                "supplier_applied",
                "receiver_receipt_id",
                "business_notification_state",
                "business_notification_attempts",
            }
            or any(
                not proof_uuid(u[k])
                for k in ("action_id", "intent_id", "effect_id", "receiver_receipt_id")
            )
            or any(
                type(u[k]) is not int or u[k] != n
                for k, n in {
                    "supplier_all_calls": 1,
                    "supplier_applied": 1,
                    "business_notification_attempts": 0,
                }.items()
            )
            or u["business_notification_state"] != "pending"
        ):
            raise GateError("invalid_proof")
    else:
        if (
            set(v) != {"schema_version", "status", "counters", "records"}
            or v["status"] != "passed"
            or not exact_child(v["counters"], PEER_COUNTS)
            or type(v["records"]) is not list
            or len(v["records"]) != 9
        ):
            raise GateError("invalid_proof")
        labels = set()
        for r in v["records"]:
            if (
                type(r) is not dict
                or set(r) != PEER_RECORD_KEYS
                or type(r["label"]) is not str
                or r["label"] not in RESULT_LABELS
                or r["label"] in labels
                or r["delegation_id"] != "delegation_" + r["label"]
                or type(r["attempt_id"]) is not str
                or re.fullmatch(r"attempt_[0-9a-f]{32}", r["attempt_id"]) is None
                or any(
                    not proof_hash(r[k])
                    for k in ("input_fingerprint", "request_sha256", "result_sha256")
                )
                or any(
                    not proof_time(r[k])
                    for k in (
                        "started_at_ms",
                        "request_deadline_at_ms",
                        "result_completed_at_ms",
                        "result_ready_at_ms",
                    )
                )
                or any(
                    type(r[k]) is not bool
                    for k in (
                        "cancel_requested",
                        "cancel_acknowledged",
                        "cancel_ack_lost",
                        "transport_disconnected",
                        "response_finished",
                    )
                )
                or type(r["timeliness_observed"]) is not str
                or r["timeliness_observed"] not in {"candidate", "expired"}
                or r["started_at_ms"] > r["result_ready_at_ms"]
                or r["timeliness_observed"]
                != (
                    "expired"
                    if r["result_ready_at_ms"] >= r["request_deadline_at_ms"]
                    else "candidate"
                )
                or r["response_finished"] is not True
                or r["transport_disconnected"] is not False
                or r["cancel_requested"] != (r["label"] in {"cancel", "cancel_lost"})
                or r["cancel_acknowledged"] != (r["label"] == "cancel")
                or r["cancel_ack_lost"] != (r["label"] == "cancel_lost")
            ):
                raise GateError("invalid_proof")
            labels.add(r["label"])
        if labels != RESULT_LABELS:
            raise GateError("invalid_proof")
    return v


def validate_proof_bundle(snapshots: dict[str, bytes]) -> None:
    if set(snapshots) != set(PROOF_FILES):
        raise GateError("invalid_proof")
    parsed = {name: validate_proof(name, raw) for name, raw in snapshots.items()}
    rows = {r["label"]: r for r in parsed["authority-proof.json"]["records"]}
    lock = parsed["eligibility-lock-proof.json"]
    if (
        lock["work_id"] != rows["lock_wait"]["work_id"]
        or lock["deadline_at_ms"] != rows["lock_wait"]["deadline_at_ms"]
    ):
        raise GateError("invalid_proof")
    for peer in parsed["peer-observations.json"]["records"]:
        row = rows[peer["label"]]
        if (
            peer["attempt_id"] != "attempt_" + row["attempt_id"].replace("-", "")
            or peer["request_sha256"] != row["transport_sha256"]
            or peer["result_sha256"] != row["result_sha256"]
            or peer["input_fingerprint"] != row["input_fingerprint"]
            or peer["request_deadline_at_ms"] != row["deadline_at_ms"]
            or peer["result_completed_at_ms"] != row["reported_completed_at_ms"]
        ):
            raise GateError("invalid_proof")


def target_path(root: Path, path: Path) -> Path:
    return report_target(root, path)


def retain_proof(root: Path, target: Path, work: Path) -> str:
    destination = proof_target(root, target)
    snapshots = {}
    for name in PROOF_FILES:
        p = work / name
        info = p.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o600
            or not 1 <= info.st_size <= MAX_PROOF_BYTES
        ):
            raise GateError("invalid_proof")
        with os.fdopen(os.open(p, os.O_RDONLY | os.O_NOFOLLOW), "rb") as source:
            actual = os.fstat(source.fileno())
            if (actual.st_dev, actual.st_ino, actual.st_size) != (
                info.st_dev,
                info.st_ino,
                info.st_size,
            ):
                raise GateError("invalid_proof")
            raw = source.read(MAX_PROOF_BYTES + 1)
        if len(raw) != info.st_size:
            raise GateError("invalid_proof")
        validate_proof(name, raw)
        snapshots[name] = raw
    validate_proof_bundle(snapshots)
    destination.mkdir(mode=0o700)
    records = []
    for name, raw in snapshots.items():
        with os.fdopen(
            os.open(
                destination / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            ),
            "wb",
        ) as f:
            f.write(raw)
        records.append({"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    manifest = {
        "schema_version": 1,
        "status": "directly_reviewable_bounded_proof",
        "hash_codec": "sha256_exact_UTF8_file_bytes",
        "records": records,
        "maximum_file_bytes": 32768,
        "raw_request_confirmation_credentials_retained": False,
    }
    with os.fdopen(
        os.open(
            destination / "manifest.json",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        ),
        "wb",
    ) as f:
        f.write((json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
    return str(destination.relative_to(root))


def exclusive_marker(path: Path, data: bytes = b"stop\n") -> None:
    with os.fdopen(
        os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb"
    ) as f:
        f.write(data)


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--diagnostic", action="store_true")
    args = parser.parse_args(argv)
    started = time.monotonic()
    deadline = started + 180
    work_deadline = deadline - 15
    target = args.report or Path(".local/validation/p3-deadlines/" + uuid4().hex + ".json")
    cleanup_complete = False
    peer_closed = False
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
        fixture = root / "projects/delegation-reliability/tests/pg_deadline_cases.py"
        peer_script = (
            root / "projects/delegation-reliability/specialist-ts/tests/fixtures/deadline-peer.mjs"
        )
        interpreter = root / ".venv/bin/python"
        node = shutil.which("node")
        if (
            not node
            or not all(
                p.is_file() and not p.is_symlink()
                for p in (fixture, peer_script, root / "local-setup/scripts/p3_case_fixture.py")
            )
            or not interpreter.is_file()
        ):
            raise GateError("missing_setup")
        scratch = root / ".local/p3-deadlines-check"
        core.private_directory(scratch)
        with tempfile.TemporaryDirectory(prefix="run-", dir=scratch) as tmp:
            work = Path(tmp)
            budget = core.CaptureBudget()
            seen: set[str] = set()
            launched: set[str] = set()
            children = 0
            kill_count = 0
            graph_count = 0
            version = ""
            peer: OwnedProcess | None = None
            context = {
                "P3_DEADLINE_WORK_SCHEMA": "p1_work_deadline_" + uuid4().hex,
                "P3_DEADLINE_CASE_SCHEMA": "p3_completion_" + uuid4().hex,
                "P3_DEADLINE_SCHEMA": "p3_projection_deadline_" + uuid4().hex,
                "P3_DEADLINE_DIRECTORY": str(work),
                "P3_DEADLINE_TOKEN": secrets.token_urlsafe(32),
                "P3_DEADLINE_PORT": "1",
            }
            command = [str(interpreter), "-I", str(fixture)]
            redactions = tuple(
                values[k]
                for k in (
                    "POSTGRES_PASSWORD",
                    "POSTGRES_MIGRATION_PASSWORD",
                    "POSTGRES_ADMIN_PASSWORD",
                    "LOCAL_ACCESS_TOKEN",
                    "LIVEKIT_API_SECRET",
                )
                if k in values
            ) + (context["P3_DEADLINE_TOKEN"],)
            with diagnostic_failure(
                root, target, work, redactions, diagnostic_state, enabled=args.diagnostic
            ):

                def reserve(name: str) -> int:
                    nonlocal children
                    if name not in CAPTURE_NAMES or name in launched or children >= 24:
                        raise GateError("invalid_child_mode")
                    children += 1
                    launched.add(name)
                    return budget.reserve(4096)

                def env(mode: str, target_label: str | None = None) -> dict[str, str]:
                    selected = dict(context)
                    if mode in BARRIERS:
                        selected["P3_DEADLINE_BARRIER"] = str(work / (BARRIERS[mode] + ".reached"))
                    if target_label is not None:
                        selected["P3_DEADLINE_TARGET"] = target_label
                    return child_environment(values, selected, mode=mode)

                def accept(
                    mode: str, value: dict[str, Any], target_label: str | None = None
                ) -> dict[str, Any]:
                    checked = validated_stage(json.dumps(value).encode(), mode, target_label)
                    for name in checked.get("cases", []):
                        if name in seen:
                            raise GateError("invalid_report")
                        seen.add(name)
                    return checked

                def call(mode: str, target_label: str | None = None) -> dict[str, Any]:
                    name = mode + ("-" + target_label if target_label is not None else "")
                    limit = reserve(name)
                    output = work / name
                    with OwnedProcess(
                        [*command, mode],
                        cwd=work,
                        env=env(mode, target_label),
                        output_directory=output,
                        max_output_bytes=limit,
                    ) as child:
                        value = checked_child(
                            child,
                            output=output,
                            limit=limit,
                            budget=budget,
                            deadline=deadline if mode == "cleanup" else work_deadline,
                            mode=mode,
                        )
                    return accept(mode, value, target_label)

                @contextmanager
                def held(mode: str) -> Iterator[tuple[OwnedProcess, int]]:
                    limit = reserve(mode)
                    with OwnedProcess(
                        [*command, mode],
                        cwd=work,
                        env=env(mode),
                        output_directory=work / mode,
                        max_output_bytes=limit,
                    ) as child:
                        yield child, limit

                def collect(mode: str, child: OwnedProcess, limit: int) -> dict[str, Any]:
                    return accept(
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
                    child.wait_for_barrier(barrier, timeout=min(10, core.remaining(work_deadline)))

                def remote_run(
                    mode: str, name: str, controller: str, target_label: str | None = None
                ) -> None:
                    assert peer is not None
                    barrier = FileBarrier(work, name)
                    with held(mode) as (child, limit):
                        wait(peer, barrier)
                        call(controller, target_label)
                        peer.release_barrier(barrier)
                        collect(mode, child, limit)

                try:
                    call("install")
                    peer_limit = reserve("peer")
                    ready = FileBarrier(work, "peer_ready")
                    endpoint = work / "peer-endpoint.json"
                    stop = work / "peer.stop"
                    peer_env = {
                        **peer_base_environment(),
                        "P3_DEADLINE_TOKEN": context["P3_DEADLINE_TOKEN"],
                        "P3_DEADLINE_DIRECTORY": str(work),
                        "P3_DEADLINE_READY": str(work / "peer_ready.reached"),
                        "P3_DEADLINE_ENDPOINT_FILE": str(endpoint),
                        "P3_DEADLINE_STOP": str(stop),
                    }
                    with OwnedProcess(
                        [node, str(peer_script)],
                        cwd=work,
                        env=peer_env,
                        output_directory=work / "peer",
                        max_output_bytes=peer_limit,
                    ) as node_child:
                        peer = node_child
                        wait(peer, ready)
                        point = core.decode(endpoint.read_bytes())
                        if (
                            set(point) != {"port", "node_version"}
                            or type(point["port"]) is not int
                            or not 1 <= point["port"] <= 65535
                            or not core.supported_node(point["node_version"])
                        ):
                            raise GateError("invalid_peer_endpoint")
                        context["P3_DEADLINE_PORT"] = str(point["port"])
                        version = point["node_version"]
                        try:
                            call("seed")
                            call("before-issue")
                            lock_ready = FileBarrier(work, "deadline_lock_ready")
                            before_sql = FileBarrier(work, "issue_before_sql")
                            acquired = FileBarrier(work, "deadline_lock_acquired")
                            observed = FileBarrier(work, "deadline_lock_observed")
                            with held("clock-lock") as (locker, lock_limit):
                                wait(locker, lock_ready)
                                with held("lock-issue") as (issuer, issue_limit):
                                    wait(issuer, before_sql)
                                    locker.release_barrier(lock_ready)
                                    wait(locker, acquired)
                                    issuer.release_barrier(before_sql)
                                    wait(locker, observed)
                                    collect("clock-lock", locker, lock_limit)
                                    collect("lock-issue", issuer, issue_limit)
                                    graph_count += 1
                            call("before-http")
                            remote_run("invoke-expiry", "remote_expiry", "wait-expiry", "expiry")
                            remote_run("invoke-lease", "remote_lease", "wait-lease")
                            remote_run("invoke-cancel", "remote_cancel", "cancel-ack")
                            remote_run("invoke-cancel-lost", "remote_cancel_lost", "cancel-lost")
                            for mode, name in (
                                ("caller-timeout", "remote_timeout"),
                                ("caller-cancel", "remote_waiter_cancel"),
                            ):
                                remote_barrier = FileBarrier(work, name)
                                local_barrier = FileBarrier(work, BARRIERS[mode])
                                with held(mode) as (child, limit):
                                    wait(peer, remote_barrier)
                                    wait(child, local_barrier)
                                    peer.release_barrier(remote_barrier)
                                    child.release_barrier(local_barrier)
                                    collect(mode, child, limit)
                            call("known-replay")
                            remote_barrier = FileBarrier(work, "remote_crash")
                            committed = FileBarrier(work, "late_result_commit")
                            with held("crash-late") as (child, limit):
                                wait(peer, remote_barrier)
                                call("wait-expiry", "crash")
                                peer.release_barrier(remote_barrier)
                                wait(child, committed)
                                termination = child.kill(
                                    timeout=min(3, core.remaining(work_deadline))
                                )
                                stdout, stderr = budget.read(work / "crash-late", limit)
                                if (
                                    not termination.killed
                                    or termination.returncode != -9
                                    or child.cleanup_failed
                                    or stdout
                                    or stderr
                                ):
                                    raise GateError("crash_not_observed")
                                kill_count += 1
                            call("verify-crash")
                            call("useful-current")
                            call("owner-check")
                            if seen != set(CASE_NAMES):
                                raise GateError("invalid_report")
                        finally:
                            primary = sys.exception()
                            try:
                                if not stop.exists():
                                    exclusive_marker(stop)
                                node_result = peer.wait(timeout=min(3, core.remaining(deadline)))
                                stdout, stderr = budget.read(work / "peer", peer_limit)
                                if node_result.returncode != 0 or peer.cleanup_failed or stderr:
                                    raise GateError("peer_cleanup_incomplete")
                                peer_report(stdout)
                                peer_closed = True
                            except Exception:
                                if primary is None:
                                    raise
                        if args.diagnostic:
                            raise GateError("diagnostic_not_qualification")
                finally:
                    primary = sys.exception()
                    try:
                        cleanup_complete = call("cleanup")["cleanup_complete"] is True
                    except Exception:  # noqa: BLE001 - Preserve fixed safe tooling diagnostics and owned cleanup.
                        cleanup_complete = False
                        if primary is None:
                            raise GateError("cleanup_incomplete") from None
                if not cleanup_complete or not peer_closed:
                    raise GateError("cleanup_incomplete")
                retain_proof(root, target, work)
            report = validated_report(
                json.dumps(
                    {
                        "schema_version": 1,
                        "status": "passed",
                        "mode": MODE,
                        "tests": 18,
                        "passed": 18,
                        "failures": 0,
                        "errors": 0,
                        "skipped": 0,
                        "duration_seconds": time.monotonic() - started,
                        "cleanup_complete": True,
                        "case_results": [
                            {"name": n, "status": "passed", "code": "ok"} for n in CASE_NAMES
                        ],
                        "child_terminations": kill_count,
                        "blocking_graphs_observed": graph_count,
                        "peer_invocations": 9,
                        "peer_completed": 9,
                        "remote_cancel_acknowledgements": 1,
                        "remote_cancel_unknown": 1,
                        "provider_calls": False,
                        "source_authority": "actual_public_p1_work_v4_deadline_cancellation_action",
                        "peer_authority": "bounded_intentionally_noncooperating_node_fault_peer",
                        "runtime_change": "validation_only_existing_p3_p1_guards",
                        "node_version": version,
                    }
                ).encode()
            )
    except GateError as e:
        report = {
            "schema_version": 1,
            "status": "failed",
            "mode": MODE,
            "code": e.code,
            "duration_seconds": time.monotonic() - started,
            "cleanup_complete": cleanup_complete,
            **diagnostic_state,
        }
    except ProcessControlError:
        report = {
            "schema_version": 1,
            "status": "failed",
            "mode": MODE,
            "code": "owned_process_failed",
            "duration_seconds": time.monotonic() - started,
            "cleanup_complete": cleanup_complete,
            **diagnostic_state,
        }
    except Exception:  # noqa: BLE001 - Preserve fixed safe tooling diagnostics and owned cleanup.
        report = {
            "schema_version": 1,
            "status": "failed",
            "mode": MODE,
            "code": "gate_failed",
            "duration_seconds": time.monotonic() - started,
            "cleanup_complete": cleanup_complete,
            **diagnostic_state,
        }
    try:
        retain_report(root, target, report)
    except GateError:
        report = {
            "status": "failed",
            "mode": MODE,
            "code": "report_retention_failed",
            "cleanup_complete": cleanup_complete,
        }
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
