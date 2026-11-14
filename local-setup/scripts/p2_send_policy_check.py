"""Explicit P2 v5 explicit send-policy gate; application-owned HTTP, no remote provider."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import shutil
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable
from contextlib import closing
from pathlib import Path
from typing import Any, NoReturn
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import p2_postgres_check as core

from harness.process_control import FileBarrier, OwnedProcess

DEADLINE_SECONDS = 180.0
CLEANUP_SECONDS = 15.0
MODE = "local_synthetic_p2_send_policy_v5"
MODES = frozenset(
    (
        "install",
        "seed",
        "upgrade",
        "repeat",
        "exercise",
        "race",
        "callback-race",
        "crash-observed",
        "crash-reserved",
        "reopen",
        "verify",
    )
)
OWNER_MODES = frozenset(("install", "upgrade", "repeat", "verify"))
CASE_NAMES = (
    "populated_v4_to_v5_preserves_original_bytes",
    "repeated_owner_upgrade_validates_caps_and_counters",
    "partial_ddl_cancel_rolls_back",
    "populated_v5_backup_restore_fresh_reopen",
    "runtime_catalog_counter_and_namespace_drift_denied",
    "distinct_controller_and_capability_scope",
    "ordinary_and_idempotent_normal_progress",
    "terminal_nonacceptance_allows_new_operation",
    "ordinary_observed_lost_response_stays_unknown",
    "original_recipient_survives_route_change",
    "ordinary_unknown_explicit_retry_holds",
    "idempotent_observed_lost_response",
    "lookup_known_acceptance_no_send",
    "absent_unavailable_lookup_remains_unknown",
    "explicit_same_key_distinct_attempt_one_acceptance",
    "original_command_replay_zero_invocations",
    "changed_command_identity_conflicts",
    "competing_retry_commands_one_reservation",
    "expected_attempt_and_attempt_caps",
    "current_route_revocation_suppression_veto",
    "reservation_first_preserves_original_call",
    "callback_first_vetoes_contending_retry",
    "retry_first_callback_retains_admitted_call",
    "reused_key_callbacks_keep_exact_attempt_identity",
    "prior_operation_conflict_preserves_history_vetoes_future",
    "command_caps_preserve_replay_and_inspection",
    "provider_observed_sigkill_original_command_replay",
    "reserved_before_wire_sigkill_fresh_same_key_progress",
    "bounded_ignored_io_and_fixed_telemetry",
    "independent_sql_provider_ledger_reconciliation",
)


def validate_recovery_accounting(
    snapshot: dict[str, Any],
    bounded: dict[str, Any],
    *,
    killed_command_ids: tuple[str, str],
    outbound_id: str,
) -> dict[str, Any]:
    """Join exact durable identities, including a deadline before provider entry.

    The two killed IDs and outbound ID come from parent-owned fixture identities.
    Child-reported public views must match independently queried immutable rows;
    no generic missing-row count or producer success flag grants a pass.
    """

    def fail() -> NoReturn:
        raise core.GateError("independent_recovery_accounting_mismatch")

    def identifier(value: object) -> bool:
        try:
            return type(value) is str and str(UUID(value)) == value
        except (ValueError, AttributeError, TypeError):
            return False

    def same(left: object, right: object) -> bool:
        try:
            return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(
                right, sort_keys=True, allow_nan=False
            )
        except (TypeError, ValueError):
            return False

    def payload(row: dict[str, Any], key: str, hash_key: str) -> dict[str, Any]:
        raw = row.get(key)
        if type(raw) is not str:
            fail()
        try:
            encoded = raw.encode("utf-8")
        except UnicodeError:
            fail()
        if not 1 <= len(encoded) <= 4096:
            fail()
        if hashlib.sha256(encoded).hexdigest() != row.get(hash_key):
            fail()
        try:
            value = json.loads(raw, object_pairs_hook=core.unique_object)
        except (ValueError, UnicodeError, RecursionError):
            fail()
        if type(value) is not dict or not same(value, value):
            fail()
        return value

    for key, expected in (
        ("active", 0),
        ("recoveryAcknowledgementUnknown", 1),
        ("recoveryRejected", 0),
    ):
        if type(bounded.get(key)) is not int or bounded[key] != expected:
            fail()
    rows = snapshot.get("send_recovery_commands")
    facts = snapshot.get("send_recovery_observations")
    if type(rows) is not list or len(rows) != 128 or type(facts) is not list:
        fail()
    commands: dict[str, dict[str, Any]] = {}
    receipts: dict[str, dict[str, Any]] = {}
    observations: dict[str, dict[str, Any]] = {}
    for row in rows:
        if type(row) is not dict or not identifier(row.get("command_id")):
            fail()
        identity = row["command_id"]
        if identity in commands:
            fail()
        receipt = payload(row, "receipt_json", "receipt_digest")
        semantic = payload(row, "canonical_command", "command_digest")
        if (
            set(receipt)
            != {
                "schemaVersion",
                "receiptId",
                "commandId",
                "kind",
                "outboundId",
                "sourceAttemptId",
                "providerOperationKey",
                "operationDigest",
                "decision",
                "code",
                "newAttemptId",
                "acceptedAt",
            }
            or set(semantic)
            != {
                "schemaVersion",
                "kind",
                "commandId",
                "outboundId",
                "attemptId",
                "scope",
                "caseId",
                "conversationId",
                "providerOperationKey",
                "operationDigest",
            }
            or type(receipt.get("schemaVersion")) is not int
            or receipt["schemaVersion"] != 1
            or type(semantic.get("schemaVersion")) is not int
            or semantic["schemaVersion"] != 1
            or semantic.get("kind") != row.get("kind")
            or semantic.get("outboundId") != row.get("outbound_id")
            or semantic.get("attemptId") != row.get("source_attempt_id")
            or semantic.get("providerOperationKey") != row.get("provider_operation_key")
            or semantic.get("operationDigest") != receipt.get("operationDigest")
            or receipt.get("commandId") != identity
            or semantic.get("commandId") != identity
            or receipt.get("kind") != row.get("kind")
            or receipt.get("providerOperationKey") != row.get("provider_operation_key")
            or receipt.get("outboundId") != row.get("outbound_id")
            or receipt.get("sourceAttemptId") != row.get("source_attempt_id")
            or receipt.get("newAttemptId") != row.get("new_attempt_id")
        ):
            fail()
        commands[identity], receipts[identity] = row, receipt
    for row in facts:
        if type(row) is not dict or not identifier(row.get("command_id")):
            fail()
        identity = row["command_id"]
        if identity in observations or identity not in commands:
            fail()
        fact = payload(row, "canonical_observation", "observation_digest")
        if (
            set(fact)
            != {
                "schemaVersion",
                "commandId",
                "providerOperationKey",
                "operationDigest",
                "source",
                "state",
                "assessment",
                "providerMessageId",
                "observedAt",
            }
            or type(fact.get("schemaVersion")) is not int
            or fact["schemaVersion"] != 1
            or fact.get("commandId") != identity
            or fact.get("providerOperationKey") != commands[identity]["provider_operation_key"]
            or fact.get("operationDigest") != receipts[identity].get("operationDigest")
        ):
            fail()
        observations[identity] = fact
    if (
        type(killed_command_ids) is not tuple
        or len(killed_command_ids) != 2
        or not all(identifier(x) for x in killed_command_ids)
        or len(set(killed_command_ids)) != 2
        or not identifier(outbound_id)
    ):
        fail()
    for identity in killed_command_ids:
        if (
            identity not in commands
            or identity in observations
            or receipts[identity].get("kind") != "retry"
            or receipts[identity].get("decision") != "retry_reserved"
            or not identifier(receipts[identity].get("newAttemptId"))
        ):
            fail()
    meta = bounded.get("timeoutAndAbandonment")
    keys = {
        "deadlineMs",
        "deadlinePortEntered",
        "deadlineCode",
        "abortAfterActualPortEntry",
        "retainedUntilRelease",
        "settledActive",
        "deadlineCommandId",
        "deadlineCommand",
        "abandonedCommandId",
        "abandonedCommand",
        "replay",
    }
    if (
        type(meta) is not dict
        or set(meta) != keys
        or type(meta["deadlineMs"]) is not int
        or meta["deadlineMs"] != 25
        or type(meta["deadlinePortEntered"]) is not bool
        or meta["deadlineCode"] != "AcknowledgementUnknown"
        or meta["abortAfterActualPortEntry"] is not True
        or meta["retainedUntilRelease"] is not True
        or type(meta["settledActive"]) is not int
        or meta["settledActive"] != 0
    ):
        fail()
    deadline_id, abandoned_id = meta["deadlineCommandId"], meta["abandonedCommandId"]
    if (
        not identifier(deadline_id)
        or not identifier(abandoned_id)
        or len({deadline_id, abandoned_id, *killed_command_ids}) != 4
    ):
        fail()
    expected_missing = set(killed_command_ids)
    for identity, view, required in (
        (deadline_id, meta["deadlineCommand"], False),
        (abandoned_id, meta["abandonedCommand"], True),
    ):
        if view is None:
            if required or identity in commands or identity in observations:
                fail()
            continue
        if (
            type(view) is not dict
            or set(view) != {"receipt", "observation"}
            or identity not in commands
            or not same(view["receipt"], receipts[identity])
            or not same(view["observation"], observations.get(identity))
            or receipts[identity].get("kind") != "reconcile"
            or receipts[identity].get("decision") != "lookup_authorized"
            or receipts[identity].get("outboundId") != outbound_id
            or receipts[identity].get("newAttemptId") is not None
        ):
            fail()
        if identity not in observations:
            if required or meta["deadlinePortEntered"]:
                fail()
            expected_missing.add(identity)
    if meta["deadlinePortEntered"] and deadline_id not in observations:
        fail()
    if meta["deadlineCommand"] is not None:
        for key in ("sourceAttemptId", "providerOperationKey", "operationDigest", "outboundId"):
            if receipts[deadline_id].get(key) != receipts[abandoned_id].get(key):
                fail()
    if set(commands) - set(observations) != expected_missing:
        fail()
    replay = meta["replay"]
    pairs = (
        ("providerStartedBefore", "providerStartedAfter"),
        ("lookupInvocationsBefore", "lookupInvocationsAfter"),
        ("retryInvocationsBefore", "retryInvocationsAfter"),
    )
    replay_keys = {"deadlineReplayed", "abandonedReplayed", *(k for pair in pairs for k in pair)}
    if (
        type(replay) is not dict
        or set(replay) != replay_keys
        or replay["deadlineReplayed"] is not (meta["deadlineCommand"] is not None)
        or replay["abandonedReplayed"] is not True
    ):
        fail()
    for before, after in pairs:
        if (
            type(replay[before]) is not int
            or not 0 <= replay[before] <= 10000
            or type(replay[after]) is not int
            or replay[after] != replay[before]
        ):
            fail()
    return {
        "commands": 128,
        "observations": len(observations),
        "missing_command_ids": sorted(expected_missing),
        "deadline_command_id": deadline_id,
        "deadline_committed": deadline_id in commands,
        "deadline_observed": deadline_id in observations,
        "abandoned_command_id": abandoned_id,
        "original_replay_zero_invocations": True,
    }


def validate_recovery_anchor(
    semantic: dict[str, Any], source_request: dict[str, Any], operation: dict[str, Any]
) -> None:
    """Bind command case/conversation/scope to its original request and operation."""
    for key in ("scope", "caseId", "conversationId", "outboundId", "providerOperationKey"):
        if any(key not in item for item in (semantic, source_request, operation)):
            raise core.GateError("independent_command_anchor_mismatch")
        values = [
            json.dumps(item[key], sort_keys=True, allow_nan=False)
            for item in (semantic, source_request, operation)
        ]
        if values[0] != values[1] or values[0] != values[2]:
            raise core.GateError("independent_command_anchor_mismatch")
    if (
        "attemptId" not in source_request
        or semantic.get("attemptId") != source_request["attemptId"]
    ):
        raise core.GateError("independent_command_anchor_mismatch")


def validate_bounded_replay(
    proof: dict[str, Any], bounded: dict[str, Any], *, restored: bool
) -> None:
    """Require actual known-only replay in the new process, separate from row retention."""
    meta = bounded["timeoutAndAbandonment"]
    expected = ([meta["deadlineCommandId"]] if meta["deadlineCommand"] is not None else []) + [
        meta["abandonedCommandId"]
    ]
    if (
        set(proof) != {"schemaVersion", "restoreOnly", "commandIds", "deadlineNotInvoked", "replay"}
        or type(proof["schemaVersion"]) is not int
        or proof["schemaVersion"] != 1
        or proof["restoreOnly"] is not restored
        or type(proof["commandIds"]) is not list
        or proof["commandIds"] != expected
        or proof["deadlineNotInvoked"] is not (meta["deadlineCommand"] is None)
    ):
        raise core.GateError("independent_bounded_replay_mismatch")
    pairs = (
        ("providerStartedBefore", "providerStartedAfter"),
        ("lookupInvocationsBefore", "lookupInvocationsAfter"),
        ("retryInvocationsBefore", "retryInvocationsAfter"),
    )
    replay = proof["replay"]
    if type(replay) is not dict or set(replay) != {k for pair in pairs for k in pair}:
        raise core.GateError("independent_bounded_replay_mismatch")
    for before, after in pairs:
        if (
            type(replay[before]) is not int
            or not 0 <= replay[before] <= 10000
            or type(replay[after]) is not int
            or replay[before] != replay[after]
        ):
            raise core.GateError("independent_bounded_replay_mismatch")


def decode(raw: bytes) -> dict[str, Any]:
    if type(raw) is not bytes or not 1 <= len(raw) <= 32768:
        raise core.GateError("invalid_report")
    try:
        value = json.loads(raw, object_pairs_hook=core.unique_object)
    except (ValueError, UnicodeError, RecursionError):
        raise core.GateError("invalid_report") from None
    if type(value) is not dict:
        raise core.GateError("invalid_report")
    return value


def validated_report(raw: bytes) -> dict[str, Any]:
    v = decode(raw)
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
        "case_results",
        "node_version",
        "blocking_graphs",
        "child_terminations",
        "schema_version_observed",
        "authority",
    }
    if set(v) != expected:
        raise core.GateError("invalid_report")
    if any(
        type(v[k]) is not int
        for k in (
            "schema_version",
            "tests",
            "passed",
            "failures",
            "errors",
            "skipped",
            "child_terminations",
            "schema_version_observed",
        )
    ):
        raise core.GateError("invalid_report")
    graphs = v["blocking_graphs"]
    if (
        type(graphs) is not dict
        or set(graphs) != {"upgrade", "retry", "callback"}
        or any(type(x) is not int for x in graphs.values())
    ):
        raise core.GateError("invalid_report")
    d = v["duration_seconds"]
    if (
        v["schema_version"] != 1
        or v["status"] != "passed"
        or v["mode"] != MODE
        or v["tests"] != len(CASE_NAMES)
        or v["passed"] != len(CASE_NAMES)
        or any(v[k] != 0 for k in ("failures", "errors", "skipped"))
        or type(d) not in (int, float)
        or not math.isfinite(d)
        or not 0 < d <= DEADLINE_SECONDS
        or v["cleanup_complete"] is not True
        or v["child_terminations"] != 2
        or v["schema_version_observed"] != 5
        or v["authority"] != "P2_explicit_same_key_recovery_not_physical_exactly_once"
        or v["blocking_graphs"] != {"upgrade": 1, "retry": 2, "callback": 2}
        or not core.supported_node(v["node_version"])
        or v["case_results"] != [{"name": n, "status": "passed", "code": "ok"} for n in CASE_NAMES]
    ):
        raise core.GateError("invalid_report")
    return v


def validated_stage(raw: bytes, mode: str) -> dict[str, Any]:
    if mode not in MODES:
        raise core.GateError("invalid_stage")
    v = decode(raw)
    if (
        set(v) != {"status", "mode", "cleanup_complete", "node_version"}
        or v["status"] != "passed"
        or v["mode"] != mode
        or v["cleanup_complete"] is not True
        or not core.supported_node(v["node_version"])
    ):
        raise core.GateError("invalid_stage")
    return v


def child_environment(
    values: dict[str, str], context: dict[str, str], *, owner: bool
) -> dict[str, str]:
    required = {"POSTGRES_PORT", "POSTGRES_MIGRATION_PASSWORD", "POSTGRES_PASSWORD"}
    if (
        type(owner) is not bool
        or type(context) is not dict
        or set(context) != {"P2_SEND_POLICY_SCHEMA", "P2_SEND_POLICY_DIRECTORY"}
        or type(values) is not dict
        or not required.issubset(values)
        or any(
            type(v) is not str
            or not 1 <= len(v) <= 4096
            or any(c in v for c in ("\x00", "\n", "\r"))
            for v in (*context.values(), *(values[k] for k in required))
        )
    ):
        raise core.GateError("invalid_environment")
    return {
        **core.base_environment(),
        **context,
        "P2_SEND_POLICY_PG_PORT": values["POSTGRES_PORT"],
        "P2_SEND_POLICY_OWNER_PASSWORD" if owner else "P2_SEND_POLICY_RUNTIME_PASSWORD": values[
            "POSTGRES_MIGRATION_PASSWORD" if owner else "POSTGRES_PASSWORD"
        ],
    }


def target_path(root: Path, path: Path) -> Path:
    target = path if path.is_absolute() else root / path
    target = target.absolute()
    allowed = root / ".local/validation/p2-send-policy"
    if ".." in target.parts or not target.is_relative_to(allowed):
        raise core.GateError("unsafe_evidence_path")
    core.private_directory(target.parent)
    if target.exists() or target.is_symlink():
        raise core.GateError("unsafe_evidence_path")
    return target


def retain(path: Path, value: dict[str, Any], *, maximum: int = 32768) -> None:
    try:
        raw = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
        if type(maximum) is not int or maximum not in (32768, 1048576) or len(raw) > maximum:
            raise ValueError()
        with os.fdopen(
            os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb"
        ) as f:
            f.write(raw)
    except (OSError, ValueError, TypeError, RecursionError, UnicodeError):
        raise core.GateError("report_retention_failed") from None


def deadlines(started: float) -> tuple[float, float]:
    final = started + DEADLINE_SECONDS
    return final - CLEANUP_SECONDS, final


async def cleanup_actions(
    actions: tuple[Callable[[], Awaitable[None]], ...],
    state: dict[str, bool],
    primary: BaseException | None,
) -> None:
    failed = False
    control: BaseException | None = None
    for action in actions:
        try:
            await action()
        except BaseException as error:  # noqa: BLE001 - All owned cleanup runs even during cancellation.
            failed = True
            if not isinstance(error, Exception) and control is None:
                control = error
    state["cleanup_complete"] = not failed
    if primary is None:
        if control is not None:
            raise control
        if failed:
            raise core.GateError("cleanup_incomplete")


def snapshot_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode()
    ).hexdigest()


def enforce_capture(stage: int, stdout_bytes: int, stderr_bytes: int, total_bytes: int) -> int:
    if (
        any(type(v) is not int or v < 0 for v in (stage, stdout_bytes, stderr_bytes, total_bytes))
        or not 1 <= stage <= 40
        or stdout_bytes + stderr_bytes > 65536
        or total_bytes + stdout_bytes + stderr_bytes > 2621440
    ):
        raise core.GateError("capture_overflow")
    return total_bytes + stdout_bytes + stderr_bytes


async def run(
    root: Path, artifacts: Path, started: float, cleanup: dict[str, bool]
) -> dict[str, Any]:
    deadline, final_deadline = deadlines(started)
    values = core.load_setup(root).load_settings()
    project = root / "projects/channel-continuity"
    node, docker = shutil.which("node"), shutil.which("docker")
    compiler = project / "node_modules/typescript/bin/tsc"
    if not node or not docker or not compiler.is_file():
        raise core.GateError("missing_setup")
    schema = "p2_send_policy_" + uuid4().hex
    stage, capture, node_version = 0, 0, ""
    server = None
    writers: set[asyncio.StreamWriter] = set()
    handlers: set[asyncio.Task[Any]] = set()
    ledger: list[dict[str, Any]] = []
    operations: dict[str, dict[str, Any]] = {}
    graphs: dict[str, int] = {}
    lock_proof: dict[str, Any] = {}
    container, backup_directory = "", ""
    container_created = False

    def connect(*, owner: bool = True) -> psycopg.Connection[dict[str, Any]]:
        return psycopg.connect(
            host="127.0.0.1",
            port=int(values["POSTGRES_PORT"]),
            dbname="livekit_lab",
            user="continuity_migrator" if owner else "livekit_lab",
            password=values["POSTGRES_MIGRATION_PASSWORD" if owner else "POSTGRES_PASSWORD"],
            sslmode="disable",
            connect_timeout=2,
            options="-c search_path=pg_catalog -c statement_timeout=3000 -c lock_timeout=1500",
            autocommit=True,
            row_factory=dict_row,
        )

    def canonical(v: object) -> bytes:
        return json.dumps(v, separators=(",", ":"), ensure_ascii=False).encode()

    def digest(v: object) -> str:
        return hashlib.sha256(canonical(v)).hexdigest()

    def snapshot(c: psycopg.Connection[dict[str, Any]], *, policy: bool) -> dict[str, Any]:
        names = [
            "admission",
            "inbox",
            "processing_intents",
            "sender_heads",
            "associations",
            "challenges",
            "conversations",
            "dispatch_settings",
            "dispatch_plans",
            "dispatch_attempts",
            "outbox_settings",
            "outbox_admission",
            "reply_intents",
            "outbound_routes",
            "send_attempts",
            "send_results",
            "callback_settings",
            "callback_admission",
            "callback_observations",
        ]
        if policy:
            names += [
                "send_policy_settings",
                "send_operations",
                "send_recovery_commands",
                "send_recovery_observations",
            ]
        return {
            n: [
                x["value"]
                for x in c.execute(
                    sql.SQL(
                        "SELECT to_jsonb(t) AS value FROM {}.{} t ORDER BY to_jsonb(t)::text"
                    ).format(sql.Identifier(schema), sql.Identifier(n))
                ).fetchall()
            ]
            for n in names
        }

    def capture_check(out: Path) -> None:
        nonlocal capture
        capture = enforce_capture(
            stage, (out / "stdout.bin").stat().st_size, (out / "stderr.bin").stat().st_size, capture
        )

    async def command(
        argv: list[str], environment: dict[str, str], name: str, *, expected: int = 0
    ) -> bytes:
        nonlocal stage
        stage += 1
        out = artifacts / f"{stage:02d}-{name}"

        def actual() -> bytes:
            with OwnedProcess(
                argv, cwd=project, env=environment, output_directory=out, max_output_bytes=65536
            ) as child:
                result = child.wait(timeout=min(20, core.remaining(deadline)))
            capture_check(out)
            if (
                child.cleanup_failed
                or result.returncode != expected
                or (out / "stderr.bin").read_bytes()
            ):
                raise core.GateError("stage_failed_" + name)
            return (out / "stdout.bin").read_bytes()

        return await asyncio.to_thread(actual)

    async def mode(name: str, *, owner: bool = False, expected: int = 0) -> dict[str, Any]:
        nonlocal node_version
        if name not in MODES or owner != (name in OWNER_MODES):
            raise core.GateError("invalid_environment")
        raw = await command(
            [node, script, name],
            child_environment(values, context, owner=owner),
            name,
            expected=expected,
        )
        v = decode(raw)
        if expected:
            if v.get("status") != "failed" or v.get("mode") != name:
                raise core.GateError("missing_expected_failure")
        else:
            v = validated_stage(raw, name)
            node_version = v["node_version"]
        return v

    async def observe(blocker: int, minimum: int, label: str, *, owner: bool = False) -> list[int]:
        until = time.monotonic() + 1.2
        with closing(connect(owner=owner)) as c:
            while True:
                rows = c.execute(
                    "SELECT pid,pg_blocking_pids(pid) AS blockers FROM pg_stat_activity WHERE usename=current_user AND pid<>pg_backend_pid()"
                ).fetchall()
                reached = {blocker}
                for _ in range(4):
                    reached.update(
                        r["pid"] for r in rows if any(x in reached for x in r["blockers"])
                    )
                found = sorted(reached - {blocker})
                if len(found) >= minimum:
                    lock_proof[label] = {
                        "ownerBlockerPid": blocker,
                        "observedWaiters": [r for r in rows if r["pid"] in found],
                    }
                    return found
                if time.monotonic() >= until:
                    raise core.GateError("unobserved_database_barrier")
                await asyncio.sleep(0.005)

    scratch = project / ".local/p2-send-policy-check"
    core.private_directory(scratch)
    try:
        with tempfile.TemporaryDirectory(prefix="run-", dir=scratch) as tmp:
            folder = Path(tmp).resolve()
            barriers = {
                n: FileBarrier(folder, n)
                for n in (
                    "race_ready",
                    "race_first",
                    "race_second",
                    "callback_ready",
                    "callback_first",
                    "callback_second",
                    "reserved",
                    "observed",
                )
            }
            import secrets

            token = secrets.token_urlsafe(32)
            ids = [str(uuid4()) for _ in range(32)]

            async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
                task = asyncio.current_task()
                assert task is not None
                handlers.add(task)
                writers.add(writer)
                try:
                    if len(writers) > 4:
                        return
                    head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 1)
                    if len(head) > 4096:
                        raise ValueError()
                    lines = head.decode("ascii").split("\r\n")
                    headers: dict[str, str] = {}
                    for line in lines[1:-2]:
                        k, v = line.split(":", 1)
                        k = k.lower()
                        if k in headers:
                            raise ValueError()
                        headers[k] = v.strip()
                    if (
                        headers.get("authorization") != "Bearer " + token
                        or headers.get("content-type") != "application/json"
                        or headers.get("connection") != "close"
                        or "transfer-encoding" in headers
                    ):
                        raise ValueError()
                    length = int(headers["content-length"])
                    if not 1 <= length <= 32768:
                        raise ValueError()
                    raw = await asyncio.wait_for(reader.readexactly(length), 1)
                    body = decode(raw)
                    path = lines[0]
                    if path == "POST /v1/idempotent-sms/lookup HTTP/1.1":
                        if set(body) != {
                            "schemaVersion",
                            "providerScope",
                            "providerOperationKey",
                            "operationDigest",
                        }:
                            raise ValueError()
                        prior = operations.get(body["providerOperationKey"])
                        if prior is not None and (
                            prior["digest"] != body["operationDigest"]
                            or prior["operation"]["providerScope"] != body["providerScope"]
                        ):
                            raise ValueError()
                        observation = {
                            **body,
                            "state": prior["state"] if prior else "absent",
                            "providerMessageId": prior["message"] if prior else None,
                        }
                        ledger.append(
                            {"kind": "lookup", "request": body, "observation": observation}
                        )
                        response = {
                            "schemaVersion": 1,
                            "status": "known",
                            "observation": observation,
                        }
                    else:
                        ordinary = path == "POST /v1/sms/send HTTP/1.1"
                        if not ordinary and path != "POST /v1/idempotent-sms/send HTTP/1.1":
                            raise ValueError()
                        if ordinary:
                            request = body
                            operation = None
                            operation_sha = None
                        else:
                            if set(body) != {
                                "schemaVersion",
                                "operation",
                                "operationDigest",
                                "attempt",
                            }:
                                raise ValueError()
                            operation = body["operation"]
                            operation_sha = digest(operation)
                            if operation_sha != body["operationDigest"]:
                                raise ValueError()
                            a = body["attempt"]
                            request = {
                                "schemaVersion": 1,
                                "outboundId": operation["outboundId"],
                                "responseId": operation["responseId"],
                                "body": operation["body"],
                                "scope": operation["scope"],
                                "caseId": operation["caseId"],
                                "conversationId": operation["conversationId"],
                                "attemptId": a["attemptId"],
                                "providerOperationKey": operation["providerOperationKey"],
                                "providerScope": operation["providerScope"],
                                "senderId": operation["senderId"],
                                "associationVersion": a["associationVersion"],
                                "routeVersion": a["routeVersion"],
                            }
                            if digest(request) != a["requestDigest"]:
                                raise ValueError()
                        if (
                            request["providerScope"]
                            != {
                                "tenantId": "tenant-a",
                                "provider": "fake_sms",
                                "providerAccountId": "carrier-a",
                            }
                            or request["scope"]
                            != {"tenantId": "tenant-a", "accountId": "account-a"}
                            or request["caseId"] != "case-a"
                            or request["conversationId"] != "conversation-a"
                        ):
                            raise ValueError()
                        prior_count = sum(
                            x.get("request", {}).get("outboundId") == request["outboundId"]
                            for x in ledger
                            if x["kind"] == "send"
                        )
                        label = request["body"]
                        absent = label in ("absent_drop", "temporal_terminal") and prior_count == 0
                        terminal = (
                            label in ("terminal_negative", "temporal_terminal") and not absent
                        )
                        prior = operations.get(request["providerOperationKey"])
                        if prior and (
                            prior["digest"] != operation_sha or prior["operation"] != operation
                        ):
                            raise ValueError()
                        state = (
                            prior["state"]
                            if prior
                            else "definitive_not_accepted"
                            if terminal
                            else "accepted_by_provider"
                        )
                        message = (
                            prior["message"]
                            if prior
                            else None
                            if terminal
                            else "provider-" + request["providerOperationKey"]
                        )
                        physical = (
                            not absent
                            and (ordinary or prior is None)
                            and state == "accepted_by_provider"
                        )
                        if not ordinary and not absent and prior is None:
                            operations[request["providerOperationKey"]] = {
                                "operation": operation,
                                "digest": operation_sha,
                                "state": state,
                                "message": message,
                            }
                        result = {
                            "schemaVersion": 1,
                            "attemptId": request["attemptId"],
                            "requestDigest": digest(request),
                            "status": state,
                        }
                        if message is not None:
                            result["providerMessageId"] = message
                        ledger.append(
                            {
                                "kind": "send",
                                "request": request,
                                "operation": operation,
                                "operationDigest": operation_sha,
                                "physicalAcceptance": physical,
                                "result": None if absent else result,
                            }
                        )
                        retain_ledger = {"observations": ledger, "operations": operations}
                        (folder / "provider-ledger.json").write_bytes(canonical(retain_ledger))
                        (folder / "provider-ledger.json").chmod(0o600)
                        if (
                            absent
                            or label == "ordinary_drop"
                            or (label == "idem_drop" and prior_count == 0)
                        ):
                            return
                        response = {"schemaVersion": 1, "status": "known", "result": result}
                        if not ordinary:
                            response.update(
                                providerOperationKey=request["providerOperationKey"],
                                operationDigest=operation_sha,
                            )
                    out = canonical(response)
                    if len(out) > 8192:
                        raise ValueError()
                    writer.write(
                        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                        + str(len(out)).encode()
                        + b"\r\nConnection: close\r\n\r\n"
                        + out
                    )
                    await writer.drain()
                except (
                    TimeoutError,
                    ValueError,
                    KeyError,
                    UnicodeError,
                    OSError,
                    core.GateError,
                    asyncio.IncompleteReadError,
                    asyncio.LimitOverrunError,
                ):
                    pass
                finally:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except OSError:
                        pass
                    finally:
                        writers.discard(writer)
                        handlers.discard(task)

            server = await asyncio.start_server(handle, "127.0.0.1", 0, limit=4096)
            assert server.sockets
            (folder / "fixture.json").write_bytes(
                canonical({"ids": ids, "port": server.sockets[0].getsockname()[1], "token": token})
            )
            (folder / "fixture.json").chmod(0o600)
            compiled = folder / "compiled"
            await command(
                [node, str(compiler), "--project", str(project / "tsconfig.json")],
                core.base_environment(),
                "build",
            )
            await command(
                [
                    node,
                    str(compiler),
                    "--project",
                    str(project / "tsconfig.pg.json"),
                    "--outDir",
                    str(compiled),
                ],
                core.base_environment(),
                "compile",
            )
            script = str(compiled / "tests/pg_send_policy_cases.js")
            context = {"P2_SEND_POLICY_SCHEMA": schema, "P2_SEND_POLICY_DIRECTORY": str(folder)}
            await mode("install", owner=True)
            await mode("seed")
            with closing(connect()) as c:
                original = snapshot(c, policy=False)
            if len(original["send_attempts"]) != 1 or len(original["send_results"]) != 1:
                raise core.GateError("missing_populated_v4")
            # Malformed existing envelopes/results/counters must roll back all new DDL.
            for defect in ("body", "result", "counter"):
                with closing(connect()) as c:
                    if defect == "body":
                        row = c.execute(
                            sql.SQL(
                                "SELECT attempt_id,canonical_request,request_digest FROM {}.send_attempts"
                            ).format(sql.Identifier(schema))
                        ).fetchone()
                        assert row
                        altered = json.loads(row["canonical_request"])
                        altered["body"] = "changed-with-valid-hash"
                        c.execute(
                            sql.SQL(
                                "UPDATE {}.send_attempts SET canonical_request=%s,request_digest=%s WHERE attempt_id=%s"
                            ).format(sql.Identifier(schema)),
                            [canonical(altered).decode(), digest(altered), row["attempt_id"]],
                        )
                    elif defect == "result":
                        row = c.execute(
                            sql.SQL(
                                "SELECT attempt_id,canonical_result FROM {}.send_results"
                            ).format(sql.Identifier(schema))
                        ).fetchone()
                        assert row
                        altered = json.loads(row["canonical_result"])
                        altered["attemptId"] = str(uuid4())
                        c.execute(
                            sql.SQL(
                                "UPDATE {}.send_results SET canonical_result=%s WHERE attempt_id=%s"
                            ).format(sql.Identifier(schema)),
                            [canonical(altered).decode(), row["attempt_id"]],
                        )
                    else:
                        c.execute(
                            sql.SQL(
                                "UPDATE {}.outbox_admission SET reply_count=reply_count+1"
                            ).format(sql.Identifier(schema))
                        )
                await mode("upgrade", owner=True, expected=1)
                with closing(connect()) as c:
                    assert row is not None
                    if defect == "body":
                        c.execute(
                            sql.SQL(
                                "UPDATE {}.send_attempts SET canonical_request=%s,request_digest=%s WHERE attempt_id=%s"
                            ).format(sql.Identifier(schema)),
                            [row["canonical_request"], row["request_digest"], row["attempt_id"]],
                        )
                    elif defect == "result":
                        c.execute(
                            sql.SQL(
                                "UPDATE {}.send_results SET canonical_result=%s WHERE attempt_id=%s"
                            ).format(sql.Identifier(schema)),
                            [row["canonical_result"], row["attempt_id"]],
                        )
                    else:
                        c.execute(
                            sql.SQL(
                                "UPDATE {}.outbox_admission SET reply_count=reply_count-1"
                            ).format(sql.Identifier(schema))
                        )
                    if (
                        c.execute(
                            "SELECT 1 FROM pg_tables WHERE schemaname=%s AND tablename='send_operations'",
                            [schema],
                        ).fetchone()
                        or snapshot(c, policy=False) != original
                    ):
                        raise core.GateError("adoption_rollback_failed")
            with closing(connect()) as blocker:
                blocker.execute("BEGIN")
                blocker.execute(
                    sql.SQL("CREATE TABLE {}.send_operations(blocker boolean)").format(
                        sql.Identifier(schema)
                    )
                )
                row = blocker.execute("SELECT pg_backend_pid() AS pid").fetchone()
                assert row
                stage += 1
                out = artifacts / f"{stage:02d}-cancel-upgrade"
                with OwnedProcess(
                    [node, script, "upgrade"],
                    cwd=project,
                    env=child_environment(values, context, owner=True),
                    output_directory=out,
                    max_output_bytes=65536,
                ) as child:
                    found = await observe(row["pid"], 1, "upgrade", owner=True)
                    with closing(connect()) as c:
                        if c.execute(
                            "SELECT pg_cancel_backend(%s) AS cancelled", [found[0]]
                        ).fetchone() != {"cancelled": True}:
                            raise core.GateError("cancel_failed")
                    result = await asyncio.to_thread(
                        child.wait, timeout=min(20, core.remaining(deadline))
                    )
                capture_check(out)
                blocker.execute("ROLLBACK")
                if result.returncode != 1 or child.cleanup_failed:
                    raise core.GateError("cancel_not_observed")
            graphs["upgrade"] = 1
            with closing(connect()) as c:
                if (
                    snapshot(c, policy=False) != original
                    or c.execute(
                        "SELECT 1 FROM pg_tables WHERE schemaname=%s AND tablename='send_operations'",
                        [schema],
                    ).fetchone()
                ):
                    raise core.GateError("ddl_rollback_failed")
            await mode("upgrade", owner=True)
            await mode("repeat", owner=True)
            with closing(connect()) as c:
                if snapshot(c, policy=False) != original:
                    raise core.GateError("old_row_bytes_changed")
            await mode("exercise")
            for name, label, markers in (
                ("race", "retry", ("race_ready", "race_first", "race_second")),
                (
                    "callback-race",
                    "callback",
                    ("callback_ready", "callback_first", "callback_second"),
                ),
            ):
                stage += 1
                out = artifacts / f"{stage:02d}-{name}"
                with OwnedProcess(
                    [node, script, name],
                    cwd=project,
                    env=child_environment(values, context, owner=False),
                    output_directory=out,
                    max_output_bytes=65536,
                ) as child:
                    await asyncio.to_thread(
                        child.wait_for_barrier, barriers[markers[0]], timeout=10
                    )
                    with closing(connect()) as blocker:
                        blocker.execute("BEGIN")
                        blocker.execute(
                            sql.SQL(
                                "SELECT singleton FROM {}.admission WHERE singleton FOR UPDATE"
                            ).format(sql.Identifier(schema))
                        )
                        row = blocker.execute("SELECT pg_backend_pid() AS pid").fetchone()
                        assert row
                        (folder / (markers[0] + ".go")).touch(mode=0o600)
                        await asyncio.to_thread(
                            child.wait_for_barrier, barriers[markers[1]], timeout=5
                        )
                        await observe(row["pid"], 1, label)
                        (folder / (markers[1] + ".go")).touch(mode=0o600)
                        await asyncio.to_thread(
                            child.wait_for_barrier, barriers[markers[2]], timeout=5
                        )
                        await observe(row["pid"], 2, label)
                        blocker.execute("COMMIT")
                    (folder / (markers[2] + ".go")).touch(mode=0o600)
                    result = await asyncio.to_thread(
                        child.wait, timeout=min(20, core.remaining(deadline))
                    )
                capture_check(out)
                if result.returncode or child.cleanup_failed:
                    raise core.GateError("stage_failed_" + name)
                validated_stage((out / "stdout.bin").read_bytes(), name)
                graphs[label] = 2
            for name, marker in (("crash-observed", "observed"), ("crash-reserved", "reserved")):
                stage += 1
                out = artifacts / f"{stage:02d}-{name}"
                with OwnedProcess(
                    [node, script, name],
                    cwd=project,
                    env=child_environment(values, context, owner=False),
                    output_directory=out,
                    max_output_bytes=65536,
                ) as child:
                    await asyncio.to_thread(child.wait_for_barrier, barriers[marker], timeout=10)
                    child.kill(timeout=5)
                    result = child.wait(timeout=5)
                capture_check(out)
                if result.returncode != -9 or child.cleanup_failed:
                    raise core.GateError("kill_not_observed")
            await mode("reopen")
            await mode("verify", owner=True)
            # Runtime never repairs corrupted counters/catalog/operation anchor; no carrier I/O.
            before_negative = len(ledger)
            for defect in ("counter", "namespace", "catalog"):
                with closing(connect()) as c:
                    if defect == "counter":
                        c.execute(
                            sql.SQL(
                                "UPDATE {}.send_policy_settings SET recovery_count=recovery_count+1"
                            ).format(sql.Identifier(schema))
                        )
                    elif defect == "namespace":
                        row = c.execute(
                            sql.SQL(
                                "SELECT provider_operation_key,provider_account_id FROM {}.send_operations WHERE outbound_id=%s"
                            ).format(sql.Identifier(schema)),
                            [ids[5]],
                        ).fetchone()
                        assert row
                        c.execute(
                            sql.SQL(
                                "UPDATE {}.send_operations SET provider_account_id='foreign' WHERE provider_operation_key=%s"
                            ).format(sql.Identifier(schema)),
                            [row["provider_operation_key"]],
                        )
                    else:
                        c.execute(
                            sql.SQL(
                                "ALTER TABLE {}.send_policy_settings ADD COLUMN forbidden integer"
                            ).format(sql.Identifier(schema))
                        )
                (folder / "negative.json").write_text(json.dumps({"defect": defect}))
                (folder / "negative.json").chmod(0o600)
                await mode("exercise")
                (folder / "negative.json").unlink()
                with closing(connect()) as c:
                    if defect == "counter":
                        c.execute(
                            sql.SQL(
                                "UPDATE {}.send_policy_settings SET recovery_count=recovery_count-1"
                            ).format(sql.Identifier(schema))
                        )
                    elif defect == "namespace":
                        c.execute(
                            sql.SQL(
                                "UPDATE {}.send_operations SET provider_account_id=%s WHERE provider_operation_key=%s"
                            ).format(sql.Identifier(schema)),
                            [row["provider_account_id"], row["provider_operation_key"]],
                        )
                    else:
                        c.execute(
                            sql.SQL(
                                "ALTER TABLE {}.send_policy_settings DROP COLUMN forbidden"
                            ).format(sql.Identifier(schema))
                        )
                if len(ledger) != before_negative:
                    raise core.GateError("corrupt_runtime_invoked_provider")
            # Repeated owner migration must reject exact counter corruption and restore without repair.
            with closing(connect()) as c:
                c.execute(
                    sql.SQL(
                        "UPDATE {}.send_policy_settings SET recovery_count=recovery_count+1"
                    ).format(sql.Identifier(schema))
                )
            await mode("verify", owner=True, expected=1)
            with closing(connect()) as c:
                c.execute(
                    sql.SQL(
                        "UPDATE {}.send_policy_settings SET recovery_count=recovery_count-1"
                    ).format(sql.Identifier(schema))
                )
            bounded = decode((folder / "bounded.json").read_bytes())
            bounded_replay = decode((folder / "bounded-replay.json").read_bytes())
            validate_bounded_replay(bounded_replay, bounded, restored=False)
            retain(artifacts / "bounded-replay-before.json", bounded_replay)
            with closing(connect()) as c:
                before = snapshot(c, policy=True)
                recovery_accounting = validate_recovery_accounting(
                    before, bounded, killed_command_ids=(ids[25], ids[28]), outbound_id=ids[15]
                )
                attempts = before["send_attempts"]
                if (
                    len(before["send_operations"]) < 10
                    or len(before["send_recovery_commands"]) < 15
                    or len(before["send_recovery_observations"]) < 15
                ):
                    raise core.GateError("missing_policy_facts")
                # Full independent scope/request/result/operation/receipt digest joins.
                ops = {r["provider_operation_key"]: r for r in before["send_operations"]}
                for a in attempts:
                    request = json.loads(a["canonical_request"])
                    op = ops[a["provider_operation_key"]]
                    payload = json.loads(op["canonical_operation"])
                    if (
                        hashlib.sha256(a["canonical_request"].encode()).hexdigest()
                        != a["request_digest"]
                        or payload["providerOperationKey"] != request["providerOperationKey"]
                        or payload["body"] != request["body"]
                        or payload["senderId"] != request["senderId"]
                        or payload["scope"] != request["scope"]
                        or payload["outboundId"] != request["outboundId"]
                        or payload["responseId"] != request["responseId"]
                        or payload["caseId"] != request["caseId"]
                        or payload["conversationId"] != request["conversationId"]
                        or digest(payload) != op["operation_digest"]
                    ):
                        raise core.GateError("independent_operation_mismatch")
                by_attempt = {a["attempt_id"]: a for a in attempts}
                for command_row in before["send_recovery_commands"]:
                    receipt = json.loads(command_row["receipt_json"])
                    semantic = json.loads(command_row["canonical_command"])
                    source = by_attempt[command_row["source_attempt_id"]]
                    operation = ops[command_row["provider_operation_key"]]
                    validate_recovery_anchor(
                        semantic,
                        json.loads(source["canonical_request"]),
                        json.loads(operation["canonical_operation"]),
                    )
                    if (
                        hashlib.sha256(command_row["receipt_json"].encode()).hexdigest()
                        != command_row["receipt_digest"]
                        or hashlib.sha256(command_row["canonical_command"].encode()).hexdigest()
                        != command_row["command_digest"]
                        or receipt["commandId"] != command_row["command_id"]
                        or receipt["newAttemptId"] != command_row["new_attempt_id"]
                        or receipt["sourceAttemptId"] != source["attempt_id"]
                        or receipt["providerOperationKey"] != source["provider_operation_key"]
                        or receipt["outboundId"] != source["outbound_id"]
                        or receipt["operationDigest"] != operation["operation_digest"]
                        or semantic["scope"]
                        != {"tenantId": source["tenant_id"], "accountId": source["account_id"]}
                        or semantic["kind"] != receipt["kind"]
                    ):
                        raise core.GateError("independent_receipt_mismatch")
                for fact in before["send_recovery_observations"]:
                    if (
                        hashlib.sha256(fact["canonical_observation"].encode()).hexdigest()
                        != fact["observation_digest"]
                    ):
                        raise core.GateError("independent_observation_mismatch")
                for item in ledger:
                    if item["kind"] == "send":
                        a = next(
                            (
                                x
                                for x in attempts
                                if x["attempt_id"] == item["request"]["attemptId"]
                            ),
                            None,
                        )
                        if (
                            a is None
                            or a["canonical_request"] != canonical(item["request"]).decode()
                        ):
                            raise core.GateError("provider_attempt_join_failed")
                if (
                    sum(
                        x.get("physicalAcceptance") is True
                        for x in ledger
                        if x.get("request", {}).get("outboundId") == ids[5]
                    )
                    != 1
                    or sum(
                        x["kind"] == "send" and x["request"]["outboundId"] == ids[5] for x in ledger
                    )
                    != 2
                ):
                    raise core.GateError("same_key_acceptance_not_proven")
                if any(
                    x["kind"] == "send" and x["request"]["outboundId"] == ids[10]
                    for x in ledger[1:]
                    if x.get("request", {}).get("attemptId")
                    != next(a["attempt_id"] for a in attempts if a["outbound_id"] == ids[10])
                ):
                    raise core.GateError("callback_veto_sent")
            with closing(connect(owner=False)) as runtime:
                for name in (
                    "send_operations",
                    "send_recovery_commands",
                    "send_recovery_observations",
                ):
                    row = runtime.execute(
                        "SELECT has_table_privilege(current_user,%s,'UPDATE') OR has_table_privilege(current_user,%s,'DELETE') OR has_table_privilege(current_user,%s,'TRUNCATE') AS unsafe",
                        [schema + "." + name] * 3,
                    ).fetchone()
                    if row != {"unsafe": False}:
                        raise core.GateError("immutable_privilege_escape")
                row = runtime.execute(
                    "SELECT has_schema_privilege(current_user,%s,'CREATE') AS unsafe", [schema]
                ).fetchone()
                if row != {"unsafe": False}:
                    raise core.GateError("runtime_ddl_escape")
            retain(
                artifacts / "provider-ledger.json",
                {"observations": ledger, "operations": operations},
                maximum=1048576,
            )
            retain(artifacts / "before-v5.json", before, maximum=1048576)
            retain(artifacts / "recovery-accounting-before.json", recovery_accounting)
            retain(artifacts / "old-v4.json", original, maximum=1048576)
            retain(artifacts / "lock-proof.json", lock_proof)
            for name in (
                "seed.json",
                "exercise.json",
                "race.json",
                "callback-race.json",
                "callback-inverse.json",
                "temporal.json",
                "bounded.json",
                "reopen.json",
                "reserved-request.json",
                "reserved-original.json",
                "observed-request.json",
                "observed-original.json",
                "capacity.json",
            ):
                if (folder / name).is_file():
                    shutil.copyfile(folder / name, artifacts / name)
                    (artifacts / name).chmod(0o600)
            listing = (
                (
                    await command(
                        [
                            docker,
                            "ps",
                            "--filter",
                            "label=com.docker.compose.service=postgres",
                            "--filter",
                            "label=com.docker.compose.project=" + core.load_setup(ROOT).PROJECT,
                            "--format",
                            "{{.ID}}",
                        ],
                        core.base_environment(),
                        "backup-container",
                    )
                )
                .decode()
                .strip()
            )
            if not re.fullmatch(r"[a-f0-9]{12,64}", listing):
                raise core.GateError("missing_backup_container")
            container = listing
            working = (
                (
                    await command(
                        [
                            docker,
                            "inspect",
                            "--format",
                            '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}',
                            container,
                        ],
                        core.base_environment(),
                        "backup-owner",
                    )
                )
                .decode()
                .strip()
            )
            if Path(working) != root / "local-setup":
                raise core.GateError("wrong_backup_container")
            backup_directory = "/tmp/p2-send-policy-" + uuid4().hex
            await command(
                [docker, "exec", container, "mkdir", "-m", "700", backup_directory],
                core.base_environment(),
                "backup-directory",
            )
            container_created = True
            pg_env = {
                **core.base_environment(),
                "PGPASSWORD": values["POSTGRES_MIGRATION_PASSWORD"],
            }
            await command(
                [
                    docker,
                    "exec",
                    "-e",
                    "PGPASSWORD",
                    container,
                    "pg_dump",
                    "--host=127.0.0.1",
                    "--username=continuity_migrator",
                    "--dbname=livekit_lab",
                    "--schema=" + schema,
                    "--inserts",
                    "--no-owner",
                    "--file=" + backup_directory + "/schema.sql",
                ],
                pg_env,
                "backup-dump",
            )
            await command(
                [
                    docker,
                    "cp",
                    container + ":" + backup_directory + "/schema.sql",
                    str(artifacts / "populated-v5-backup.sql"),
                ],
                core.base_environment(),
                "backup-copy",
            )
            (artifacts / "populated-v5-backup.sql").chmod(0o600)
            with closing(connect()) as c:
                schema_owner = c.execute(
                    "SELECT pg_get_userbyid(nspowner) AS owner,obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=%s",
                    [schema],
                ).fetchone()
                if schema_owner != {
                    "owner": "continuity_migrator",
                    "marker": "p2-channel-schema-v5",
                }:
                    raise core.GateError("backup_ownership_mismatch")
                c.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            await command(
                [
                    docker,
                    "exec",
                    "-e",
                    "PGPASSWORD",
                    container,
                    "psql",
                    "-X",
                    "--host=127.0.0.1",
                    "--username=continuity_migrator",
                    "--dbname=livekit_lab",
                    "--set=ON_ERROR_STOP=1",
                    "--single-transaction",
                    "--file=" + backup_directory + "/schema.sql",
                ],
                pg_env,
                "backup-restore",
            )
            with closing(connect()) as c:
                after = snapshot(c, policy=True)
            after_accounting = validate_recovery_accounting(
                after, bounded, killed_command_ids=(ids[25], ids[28]), outbound_id=ids[15]
            )
            if before != after or after_accounting != recovery_accounting:
                raise core.GateError("restored_row_bytes_changed")
            retain(artifacts / "after-v5.json", after, maximum=1048576)
            count = len(ledger)
            await mode("repeat", owner=True)
            # Replay-only reopen preserves exact original unknown permission, not another retry.
            (folder / "restore-only").touch(mode=0o600)
            await mode("reopen")
            restored_replay = decode((folder / "bounded-replay.json").read_bytes())
            validate_bounded_replay(restored_replay, bounded, restored=True)
            retain(artifacts / "bounded-replay-restored.json", restored_replay)
            with closing(connect()) as c:
                reopened = snapshot(c, policy=True)
            reopened_accounting = validate_recovery_accounting(
                reopened, bounded, killed_command_ids=(ids[25], ids[28]), outbound_id=ids[15]
            )
            if (
                after != reopened
                or len(ledger) != count
                or reopened_accounting != recovery_accounting
            ):
                raise core.GateError("restore_replay_changed_state")
            retain(artifacts / "after-reopen-v5.json", reopened, maximum=1048576)
            retain(artifacts / "recovery-accounting-restored.json", reopened_accounting)
            retain(
                artifacts / "restore-proof.json",
                {
                    "snapshot_codec": "json_sort_keys_compact_ascii_v1",
                    "before_sha256": snapshot_digest(before),
                    "after_sha256": snapshot_digest(after),
                    "reopen_sha256": snapshot_digest(reopened),
                    "provider_observations_before": count,
                    "provider_observations_after": len(ledger),
                    "counts": {n: len(x) for n, x in before.items()},
                    "original_unknown_and_known_receipts": True,
                },
            )
    finally:
        primary = sys.exception()
        deadline = min(final_deadline, time.monotonic() + CLEANUP_SECONDS)

        async def retain_failure_observation() -> None:
            if primary is not None:
                retain(
                    artifacts / "failure-provider-ledger.json",
                    {"observations": ledger, "operations": operations},
                    maximum=1048576,
                )
                with closing(connect()) as c:
                    exists = c.execute(
                        "SELECT 1 FROM pg_namespace WHERE nspname=%s", [schema]
                    ).fetchone()
                    if exists:
                        current = c.execute(
                            sql.SQL(
                                "SELECT version FROM {}.schema_metadata WHERE singleton"
                            ).format(sql.Identifier(schema))
                        ).fetchone()
                        if current and current["version"] in (4, 5):
                            retain(
                                artifacts / "failure-source-rows.json",
                                snapshot(c, policy=current["version"] == 5),
                                maximum=1048576,
                            )

        async def close_peer() -> None:
            if server is not None:
                server.close()
                await server.wait_closed()
            for w in list(writers):
                w.close()
            if handlers:
                await asyncio.wait_for(
                    asyncio.gather(*list(handlers), return_exceptions=True),
                    min(2, core.remaining(deadline)),
                )
            if writers or handlers:
                raise core.GateError("cleanup_incomplete")

        async def clean_file() -> None:
            if container_created:
                await command(
                    [docker, "exec", container, "rm", "-f", backup_directory + "/schema.sql"],
                    core.base_environment(),
                    "backup-remove",
                )

        async def clean_directory() -> None:
            if container_created:
                await command(
                    [docker, "exec", container, "rmdir", backup_directory],
                    core.base_environment(),
                    "backup-rmdir",
                )

        async def clean_schema() -> None:
            core.remaining(deadline)
            with closing(connect()) as c:
                row = c.execute(
                    "SELECT pg_get_userbyid(nspowner) AS owner,obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=%s",
                    [schema],
                ).fetchone()
                if row:
                    if row["owner"] != "continuity_migrator" or row["marker"] not in (
                        "p2-channel-schema-v1",
                        "p2-channel-schema-v2",
                        "p2-channel-schema-v3",
                        "p2-channel-schema-v4",
                        "p2-channel-schema-v5",
                    ):
                        raise core.GateError("cleanup_ownership_mismatch")
                    c.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))

        await cleanup_actions(
            (close_peer, retain_failure_observation, clean_file, clean_directory, clean_schema),
            cleanup,
            primary,
        )
    return validated_report(
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
                "case_results": [{"name": n, "status": "passed", "code": "ok"} for n in CASE_NAMES],
                "node_version": node_version,
                "blocking_graphs": graphs,
                "child_terminations": 2,
                "schema_version_observed": 5,
                "authority": "P2_explicit_same_key_recovery_not_physical_exactly_once",
            }
        ).encode()
    )


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    started = time.monotonic()
    cleanup = {"cleanup_complete": False}
    target = None
    try:
        target = target_path(
            root, args.report or Path(".local/validation/p2-send-policy/" + uuid4().hex + ".json")
        )
        artifacts = target.with_name(target.stem + "-artifacts")
        artifacts.mkdir(mode=0o700)
        result = asyncio.run(run(root, artifacts, started, cleanup))
    except core.GateError as error:
        result = {
            "status": "failed",
            "mode": MODE,
            "code": error.code,
            "duration_seconds": time.monotonic() - started,
            **cleanup,
        }
    except Exception:  # noqa: BLE001 - Secret-safe host-tooling boundary.
        result = {
            "status": "failed",
            "mode": MODE,
            "code": "gate_failed",
            "duration_seconds": time.monotonic() - started,
            **cleanup,
        }
    try:
        if target is not None:
            retain(target, result)
    except core.GateError:
        result = {"status": "failed", "mode": MODE, "code": "report_retention_failed", **cleanup}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
