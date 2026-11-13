"""Explicit P2 v4 authenticated callback gate; application-owned HTTP, no remote provider."""

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
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

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
MODE = "local_synthetic_p2_callback_v4"
CASE_NAMES = (
    "populated_v3_to_v4_preserves_originals",
    "repeat_old_upgrades_no_downgrade_and_limits",
    "owner_upgrade_rollback",
    "populated_v4_pg_dump_restore_fresh_reopen",
    "runtime_no_ddl_catalog_and_counter_drift",
    "callback_domain_key_and_fresh_clock_auth",
    "provider_scope_original_recipient_correlation",
    "wrong_attempt_operation_or_digest_rejected",
    "concurrent_exact_event_replay_one_receipt",
    "reordered_json_fresh_signature_retry_same_receipt",
    "changed_event_semantics_conflict",
    "distinct_event_ids_same_report_retained",
    "reordered_weaker_evidence_no_regression",
    "terminal_and_provider_identity_conflicts_retained",
    "callback_before_send_result_normal_progress",
    "callback_never_rewrites_send_result_or_grants_consent",
    "delayed_revoked_reassigned_original_history",
    "cross_account_case_inspection_denied",
    "global_per_attempt_caps_preserve_replay_read",
    "callback_veto_any_prior_attempt_before_reservation",
    "reservation_first_preserves_admitted_original_attempt",
    "callback_commit_sigkill_before_ack_fresh_replay",
    "bounded_failure_observation_and_cleanup",
    "independent_SQL_provider_reconciliation",
)


def decode(raw: bytes) -> dict[str, Any]:
    if type(raw) is not bytes or not 1 <= len(raw) <= 65536:
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
        or set(graphs) != {"upgrade", "callback"}
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
        or v["child_terminations"] != 1
        or v["schema_version_observed"] != 4
        or v["authority"] != "P2_callback_reports_not_delivery_or_resend_authority"
        or v["blocking_graphs"] != {"upgrade": 1, "callback": 2}
        or not core.supported_node(v["node_version"])
        or v["case_results"] != [{"name": n, "status": "passed", "code": "ok"} for n in CASE_NAMES]
    ):
        raise core.GateError("invalid_report")
    return v


def validated_stage(raw: bytes, mode: str) -> dict[str, Any]:
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
    if set(context) != {"P2_CALLBACK_SCHEMA", "P2_CALLBACK_DIRECTORY"}:
        raise core.GateError("invalid_environment")
    return {
        **core.base_environment(),
        **context,
        "P2_CALLBACK_PG_PORT": values["POSTGRES_PORT"],
        "P2_CALLBACK_OWNER_PASSWORD" if owner else "P2_CALLBACK_RUNTIME_PASSWORD": values[
            "POSTGRES_MIGRATION_PASSWORD" if owner else "POSTGRES_PASSWORD"
        ],
    }


def target_path(root: Path, path: Path) -> Path:
    target = path if path.is_absolute() else root / path
    target = target.absolute()
    allowed = root / ".local/validation/p2-callbacks"
    if ".." in target.parts or not target.is_relative_to(allowed):
        raise core.GateError("unsafe_evidence_path")
    core.private_directory(target.parent)
    if target.exists() or target.is_symlink():
        raise core.GateError("unsafe_evidence_path")
    return target


def retain(path: Path, value: dict[str, Any]) -> None:
    try:
        with os.fdopen(
            os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb"
        ) as f:
            f.write((json.dumps(value, indent=2, sort_keys=True) + "\n").encode())
    except OSError:
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
    for action in actions:
        try:
            await action()
        except Exception:  # noqa: BLE001 - Attempt every owned cleanup and retain the first stage failure.
            failed = True
    state["cleanup_complete"] = not failed
    if failed and primary is None:
        raise core.GateError("cleanup_incomplete")


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
    schema = "p2_callback_" + uuid4().hex
    stage, node_version = 0, ""
    container, backup_directory = "", ""
    container_created = False
    graphs: dict[str, int] = {}
    lock_proof: dict[str, Any] = {}

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

    async def command(
        argv: list[str], environment: dict[str, str], name: str, *, maximum: int = 65536
    ) -> bytes:
        nonlocal stage
        stage += 1
        out = artifacts / f"{stage:02d}-{name}"

        def actual() -> bytes:
            with OwnedProcess(
                argv, cwd=project, env=environment, output_directory=out, max_output_bytes=maximum
            ) as child:
                result = child.wait(timeout=min(20.0, core.remaining(deadline)))
            if child.cleanup_failed or result.returncode or (out / "stderr.bin").read_bytes():
                raise core.GateError("stage_failed_" + name)
            return (out / "stdout.bin").read_bytes()

        return await asyncio.to_thread(actual)

    async def node_mode(mode: str, *, owner: bool = False) -> dict[str, Any]:
        nonlocal node_version
        v = validated_stage(
            await command(
                [node, script, mode], child_environment(values, context, owner=owner), mode
            ),
            mode,
        )
        node_version = v["node_version"]
        return v

    def snapshot(
        connection: psycopg.Connection[dict[str, Any]], *, callbacks: bool
    ) -> dict[str, Any]:
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
        ]
        if callbacks:
            names += ["callback_settings", "callback_admission", "callback_observations"]
        return {
            name: [
                r["value"]
                for r in connection.execute(
                    sql.SQL(
                        "SELECT to_jsonb(t) AS value FROM {}.{} t ORDER BY to_jsonb(t)::text"
                    ).format(sql.Identifier(schema), sql.Identifier(name))
                ).fetchall()
            ]
            for name in names
        }

    async def observe(blocker: int, minimum: int, *, owner: bool) -> list[int]:
        end = time.monotonic() + 1.1
        with closing(connect(owner=owner)) as c:
            while True:
                rows = c.execute(
                    "SELECT pid,pg_blocking_pids(pid) AS blockers FROM pg_stat_activity WHERE usename=current_user AND pid<>pg_backend_pid()"
                ).fetchall()
                reached = {blocker}
                for _ in range(4):
                    reached.update(
                        r["pid"] for r in rows if any(p in reached for p in r["blockers"])
                    )
                found = sorted(reached - {blocker})
                if len(found) >= minimum:
                    lock_proof["upgrade" if owner else "callback"] = {
                        "ownerBlockerPid": blocker,
                        "observedWaiters": [
                            {"pid": r["pid"], "blockers": r["blockers"]}
                            for r in rows
                            if r["pid"] in found
                        ],
                    }
                    return found
                if time.monotonic() >= end:
                    raise core.GateError("unobserved_database_barrier")
                await asyncio.sleep(0.005)

    scratch = project / ".local/p2-callback-check"
    core.private_directory(scratch)
    try:
        with tempfile.TemporaryDirectory(prefix="run-", dir=scratch) as temporary:
            folder = Path(temporary).resolve()
            barriers = {
                n: FileBarrier(folder, n)
                for n in (
                    "race_ready",
                    "race_callback",
                    "race_reserve",
                    "reservation",
                    "committed",
                    "expiry_ready",
                    "expiry_waiting",
                    "expiry_rejected",
                )
            }
            ids = [str(uuid4()) for _ in range(5)]
            (folder / "fixture.json").write_text(json.dumps({"ids": ids}))
            (folder / "fixture.json").chmod(0o600)
            compiled = folder / "compiled"
            for name, configuration in (
                ("build", "tsconfig.json"),
                ("compile", "tsconfig.pg.json"),
            ):
                await command(
                    [node, str(compiler), "--project", str(project / configuration)]
                    + (["--outDir", str(compiled)] if name == "compile" else []),
                    core.base_environment(),
                    name,
                )
            script = str(compiled / "tests/pg_callback_cases.js")
            context = {"P2_CALLBACK_SCHEMA": schema, "P2_CALLBACK_DIRECTORY": str(folder)}
            await node_mode("install", owner=True)
            await node_mode("seed")
            with closing(connect()) as owner:
                original = snapshot(owner, callbacks=False)
            if (
                len(original["reply_intents"]) != 3
                or len(original["send_attempts"]) != 3
                or len(original["send_results"]) != 3
            ):
                raise core.GateError("missing_populated_v3")
            # Fail after partial new DDL, then independently prove transactional rollback.
            with closing(connect()) as blocker:
                blocker.execute("BEGIN")
                blocker.execute(
                    sql.SQL("CREATE TABLE {}.callback_observations(blocker boolean)").format(
                        sql.Identifier(schema)
                    )
                )
                pid_row = blocker.execute("SELECT pg_backend_pid() AS pid").fetchone()
                assert pid_row is not None
                pid = pid_row["pid"]
                stage += 1
                out = artifacts / f"{stage:02d}-rollback-upgrade"
                with OwnedProcess(
                    [node, script, "upgrade"],
                    cwd=project,
                    env=child_environment(values, context, owner=True),
                    output_directory=out,
                    max_output_bytes=16384,
                ) as child:
                    blocked = await observe(pid, 1, owner=True)
                    graphs["upgrade"] = 1
                    with closing(connect()) as observer:
                        if observer.execute(
                            "SELECT pg_cancel_backend(%s) AS cancelled", [blocked[0]]
                        ).fetchone() != {"cancelled": True}:
                            raise core.GateError("cancel_upgrade_failed")
                    result = await asyncio.to_thread(child.wait, timeout=core.remaining(deadline))
                blocker.execute("ROLLBACK")
                if (
                    result.returncode != 1
                    or child.cleanup_failed
                    or decode((out / "stdout.bin").read_bytes()).get("status") != "failed"
                ):
                    raise core.GateError("rollback_not_observed")
            with closing(connect()) as owner:
                if (
                    snapshot(owner, callbacks=False) != original
                    or owner.execute(
                        sql.SQL("SELECT version FROM {}.schema_metadata").format(
                            sql.Identifier(schema)
                        )
                    ).fetchone()
                    != {"version": 3}
                    or owner.execute(
                        "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relname='callback_settings'",
                        [schema],
                    ).fetchone()
                ):
                    raise core.GateError("upgrade_rollback_failed")
            await node_mode("upgrade", owner=True)
            await node_mode("repeat", owner=True)
            with closing(connect()) as owner:
                if snapshot(owner, callbacks=False) != original:
                    raise core.GateError("original_data_changed")
            stage += 1
            expiry_out = artifacts / f"{stage:02d}-expiry"
            with OwnedProcess(
                [node, script, "expiry"],
                cwd=project,
                env=child_environment(values, context, owner=False),
                output_directory=expiry_out,
                max_output_bytes=16384,
            ) as expiry_child:
                await asyncio.to_thread(
                    expiry_child.wait_for_barrier, barriers["expiry_ready"], timeout=10
                )
                with closing(connect()) as blocker:
                    blocker.execute("BEGIN")
                    blocker.execute(
                        sql.SQL(
                            "SELECT singleton FROM {}.admission WHERE singleton FOR UPDATE"
                        ).format(sql.Identifier(schema))
                    )
                    pid_row = blocker.execute("SELECT pg_backend_pid() AS pid").fetchone()
                    assert pid_row is not None
                    expiry_pid = pid_row["pid"]
                    align_end = time.monotonic() + 1.2
                    while True:
                        clock_row = blocker.execute(
                            "SELECT extract(epoch FROM clock_timestamp())::double precision AS seconds"
                        ).fetchone()
                        assert clock_row is not None
                        clock = float(clock_row["seconds"])
                        if 0.1 <= clock % 1 <= 0.3:
                            break
                        if time.monotonic() >= align_end:
                            raise core.GateError("clock_alignment_failed")
                        await asyncio.sleep(0.005)
                    signed_seconds = int(clock) - 60
                    (folder / "expiry-timestamp.json").write_text(
                        json.dumps({"timestamp": signed_seconds})
                    )
                    (folder / "expiry-timestamp.json").chmod(0o600)
                    (folder / "expiry_ready.go").touch(mode=0o600)
                    await asyncio.to_thread(
                        expiry_child.wait_for_barrier, barriers["expiry_waiting"], timeout=5
                    )
                    await observe(expiry_pid, 1, owner=False)
                    lock_proof["expiry"] = lock_proof.pop("callback")
                    outside_end = time.monotonic() + 1.1
                    while True:
                        clock_row = blocker.execute(
                            "SELECT floor(extract(epoch FROM clock_timestamp()))::bigint AS seconds"
                        ).fetchone()
                        assert clock_row is not None
                        outside = int(clock_row["seconds"])
                        if outside - signed_seconds > 60:
                            break
                        if time.monotonic() >= outside_end:
                            raise core.GateError("expiry_clock_not_observed")
                        await asyncio.sleep(0.005)
                    (folder / "expiry_waiting.go").touch(mode=0o600)
                    blocker.execute("COMMIT")
                await asyncio.to_thread(
                    expiry_child.wait_for_barrier, barriers["expiry_rejected"], timeout=5
                )
                with closing(connect()) as owner:
                    rejected = owner.execute(
                        sql.SQL("SELECT count(*) AS count FROM {}.callback_observations").format(
                            sql.Identifier(schema)
                        )
                    ).fetchone()
                    counter = owner.execute(
                        sql.SQL("SELECT callback_count FROM {}.callback_admission").format(
                            sql.Identifier(schema)
                        )
                    ).fetchone()
                    if rejected != {"count": 0} or counter != {"callback_count": 0}:
                        raise core.GateError("expired_callback_retained")
                (folder / "expiry_rejected.go").touch(mode=0o600)
                expiry_result = await asyncio.to_thread(
                    expiry_child.wait, timeout=core.remaining(deadline)
                )
            if expiry_result.returncode or expiry_child.cleanup_failed:
                raise core.GateError("expiry_boundary_failed")
            validated_stage((expiry_out / "stdout.bin").read_bytes(), "expiry")
            lock_proof["expiry_clock"] = {
                "signedSeconds": signed_seconds,
                "outsideObservedSeconds": outside,
                "initialAgeSeconds": 60,
                "expiredRows": 0,
                "counterAfterExpired": 0,
                "freshUsefulReport": True,
            }
            stage += 1
            out = artifacts / f"{stage:02d}-exercise"
            with OwnedProcess(
                [node, script, "exercise"],
                cwd=project,
                env=child_environment(values, context, owner=False),
                output_directory=out,
                max_output_bytes=32768,
            ) as child:
                await asyncio.to_thread(child.wait_for_barrier, barriers["race_ready"], timeout=10)
                with closing(connect()) as blocker:
                    blocker.execute("BEGIN")
                    blocker.execute(
                        sql.SQL(
                            "SELECT singleton FROM {}.admission WHERE singleton FOR UPDATE"
                        ).format(sql.Identifier(schema))
                    )
                    pid_row = blocker.execute("SELECT pg_backend_pid() AS pid").fetchone()
                    assert pid_row is not None
                    pid = pid_row["pid"]
                    (folder / "race_ready.go").touch(mode=0o600)
                    await asyncio.to_thread(
                        child.wait_for_barrier, barriers["race_callback"], timeout=5
                    )
                    await observe(pid, 1, owner=False)
                    (folder / "race_callback.go").touch(mode=0o600)
                    await asyncio.to_thread(
                        child.wait_for_barrier, barriers["race_reserve"], timeout=5
                    )
                    await observe(pid, 2, owner=False)
                    graphs["callback"] = 2
                    (folder / "race_reserve.go").touch(mode=0o600)
                    blocker.execute("COMMIT")
                await asyncio.to_thread(child.wait_for_barrier, barriers["reservation"], timeout=10)
                admitted = decode((folder / "admitted-request.json").read_bytes())
                with closing(connect()) as owner:
                    row = owner.execute(
                        sql.SQL(
                            "SELECT canonical_request FROM {}.send_attempts WHERE attempt_id=%s"
                        ).format(sql.Identifier(schema)),
                        [admitted["attemptId"]],
                    ).fetchone()
                    if (
                        row is None
                        or json.loads(row["canonical_request"]) != admitted
                        or admitted["senderId"] != "sender-new"
                    ):
                        raise core.GateError("reservation_not_committed")
                provider_before = len(json.loads((folder / "provider.json").read_text()))
                await node_mode("late-callback")
                if len(json.loads((folder / "provider.json").read_text())) != provider_before:
                    raise core.GateError("callback_invoked_provider")
                (folder / "reservation.go").touch(mode=0o600)
                result = await asyncio.to_thread(child.wait, timeout=core.remaining(deadline))
            if result.returncode or child.cleanup_failed:
                raise core.GateError("exercise_failed")
            validated_stage((out / "stdout.bin").read_bytes(), "exercise")
            # Owned SIGKILL after durable callback commit and before app HTTP response.
            stage += 1
            out = artifacts / f"{stage:02d}-commit-kill"
            with OwnedProcess(
                [node, script, "crash"],
                cwd=project,
                env=child_environment(values, context, owner=False),
                output_directory=out,
                max_output_bytes=16384,
            ) as child:
                await asyncio.to_thread(child.wait_for_barrier, barriers["committed"], timeout=10)
                receipt = decode((folder / "crash-receipt.json").read_bytes())
                with closing(connect()) as owner:
                    row = owner.execute(
                        sql.SQL(
                            "SELECT receipt_id::text FROM {}.callback_observations WHERE event_id='committed-crash'"
                        ).format(sql.Identifier(schema))
                    ).fetchone()
                    if row != {"receipt_id": receipt["receiptId"]}:
                        raise core.GateError("kill_not_after_commit")
                termination = child.kill(timeout=5)
                if not termination.killed or termination.returncode != -9:
                    raise core.GateError("owned_kill_not_observed")
            if child.cleanup_failed:
                raise core.GateError("cleanup_incomplete")
            await node_mode("replay")
            with closing(connect()) as owner:
                owner.execute(
                    sql.SQL("UPDATE {}.callback_admission SET callback_count=0").format(
                        sql.Identifier(schema)
                    )
                )
            await node_mode("counter")
            with closing(connect()) as owner:
                owner.execute(
                    sql.SQL("UPDATE {}.callback_admission SET callback_count=12").format(
                        sql.Identifier(schema)
                    )
                )
                owner.execute(
                    sql.SQL("COMMENT ON SCHEMA {} IS 'p2-callback-invalid-marker'").format(
                        sql.Identifier(schema)
                    )
                )
            await node_mode("drift")
            with closing(connect()) as owner:
                owner.execute(
                    sql.SQL("COMMENT ON SCHEMA {} IS 'p2-channel-schema-v4'").format(
                        sql.Identifier(schema)
                    )
                )
                before = snapshot(owner, callbacks=True)
            if {
                n: len(before[n])
                for n in ("reply_intents", "send_attempts", "send_results", "callback_observations")
            } != {
                "reply_intents": 5,
                "send_attempts": 7,
                "send_results": 6,
                "callback_observations": 12,
            } or before["callback_admission"] != [{"singleton": True, "callback_count": 12}]:
                raise core.GateError("independent_counts_mismatch")
            ledger = json.loads((folder / "provider.json").read_text())
            if len(ledger) != 6:
                raise core.GateError("provider_count_mismatch")
            for row in before["send_attempts"]:
                request = json.loads(row["canonical_request"])
                if (
                    hashlib.sha256(row["canonical_request"].encode()).hexdigest()
                    != row["request_digest"]
                ):
                    raise core.GateError("request_digest_mismatch")
                known = next(
                    (r for r in before["send_results"] if r["attempt_id"] == request["attemptId"]),
                    None,
                )
                observation = next(
                    (r for r in ledger if r["request"]["attemptId"] == request["attemptId"]), None
                )
                if observation is None:
                    if known is not None or request["outboundId"] != ids[4]:
                        raise core.GateError("unexplained_possible_attempt")
                elif (
                    observation["request"] != request
                    or known is None
                    or json.loads(known["canonical_result"]) != observation["result"]
                ):
                    raise core.GateError("provider_attempt_binding_mismatch")
            public_receipts: list[dict[str, Any]] = []
            proof = decode((folder / "proof.json").read_bytes())
            public_receipts.extend(r["receipt"] for r in proof["normal"]["observations"])
            early = decode((folder / "before-result.json").read_bytes())
            public_receipts.extend(r["receipt"] for r in early["observations"])
            public_receipts.append(decode((folder / "crash-receipt.json").read_bytes()))
            for row in before["callback_observations"]:
                event = json.loads(row["canonical_payload"])
                attempt = next(
                    (a for a in before["send_attempts"] if a["attempt_id"] == event["attemptId"]),
                    None,
                )
                if attempt is None:
                    raise core.GateError("callback_original_binding_mismatch")
                request = json.loads(attempt["canonical_request"])
                if (
                    event["providerOperationKey"] != attempt["provider_operation_key"]
                    or event["requestDigest"] != attempt["request_digest"]
                    or row["event_id"] != event["eventId"]
                    or row["attempt_id"] != event["attemptId"]
                    or {
                        "tenantId": row["tenant_id"],
                        "provider": row["provider"],
                        "providerAccountId": row["provider_account_id"],
                    }
                    != request["providerScope"]
                    or row["payload_digest"]
                    != hashlib.sha256(row["canonical_payload"].encode()).hexdigest()
                    or json.loads(row["first_wire"]) != event
                    or request["scope"] != {"tenantId": "tenant-a", "accountId": "account-a"}
                    or request["caseId"] != "case-a"
                    or request["conversationId"] != "conversation-a"
                ):
                    raise core.GateError("callback_original_binding_mismatch")
                public = next(
                    (r for r in public_receipts if r["eventId"] == event["eventId"]), None
                )
                if public is not None:
                    accepted = datetime.fromisoformat(row["accepted_at"])
                    accepted = accepted.replace(microsecond=(accepted.microsecond // 1000) * 1000)
                    canonical_time = accepted.isoformat(timespec="milliseconds").replace(
                        "+00:00", "Z"
                    )
                    if (
                        public["receiptId"] != row["receipt_id"]
                        or public["attemptId"] != row["attempt_id"]
                        or public["payloadDigest"] != row["payload_digest"]
                        or public["acceptedAt"] != canonical_time
                    ):
                        raise core.GateError("public_callback_receipt_mismatch")
            if len(public_receipts) != 10:
                raise core.GateError("missing_public_callback_receipts")
            retain(artifacts / "lock-proof.json", lock_proof)
            with closing(connect(owner=False)) as runtime:
                for name in ("callback_settings", "callback_observations"):
                    row = runtime.execute(
                        "SELECT has_table_privilege(current_user,%s,'UPDATE') OR has_table_privilege(current_user,%s,'DELETE') OR has_table_privilege(current_user,%s,'TRUNCATE') AS unsafe",
                        [schema + "." + name] * 3,
                    ).fetchone()
                    if row != {"unsafe": False}:
                        raise core.GateError("immutable_privilege_escape")
                if runtime.execute(
                    "SELECT has_schema_privilege(current_user,%s,'CREATE') AS unsafe", [schema]
                ).fetchone() != {"unsafe": False}:
                    raise core.GateError("runtime_ddl_escape")
            # Only fully settled processes above. Preserve populated new metadata and exact first raw bytes.
            retain(artifacts / "populated-v4-before.json", before)
            listing = (
                (
                    await command(
                        [
                            docker,
                            "ps",
                            "--filter",
                            "label=com.docker.compose.project=livekit-agent-ecosystem",
                            "--filter",
                            "label=com.docker.compose.service=postgres",
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
            if not re.fullmatch(r"[0-9a-f]{12,64}", listing):
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
            backup_directory = "/tmp/p2-callback-" + uuid4().hex
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
                    str(artifacts / "populated-v4-schema-backup.sql"),
                ],
                core.base_environment(),
                "backup-copy",
            )
            (artifacts / "populated-v4-schema-backup.sql").chmod(0o600)
            with closing(connect()) as owner:
                if owner.execute(
                    "SELECT pg_get_userbyid(nspowner) AS owner,obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=%s",
                    [schema],
                ).fetchone() != {"owner": "continuity_migrator", "marker": "p2-channel-schema-v4"}:
                    raise core.GateError("backup_ownership_mismatch")
                owner.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
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
            with closing(connect()) as owner:
                after = snapshot(owner, callbacks=True)
            if json.dumps(before, sort_keys=True, ensure_ascii=True) != json.dumps(
                after, sort_keys=True, ensure_ascii=True
            ):
                raise core.GateError("restore_changed_bytes")
            retain(artifacts / "populated-v4-after.json", after)
            await node_mode("repeat", owner=True)
            await node_mode("replay")
            with closing(connect()) as owner:
                reopened = snapshot(owner, callbacks=True)
            if reopened != before or len(json.loads((folder / "provider.json").read_text())) != 6:
                raise core.GateError("reopen_changed_facts")
            for name in (
                "proof.json",
                "expiry-proof.json",
                "reopen-proof.json",
                "before-result.json",
                "provider.json",
                "crash-observation.json",
                "crash-receipt.json",
                "admitted-request.json",
            ):
                retain(
                    artifacts / name,
                    decode((folder / name).read_bytes())
                    if name != "provider.json"
                    else {"observations": json.loads((folder / name).read_text())},
                )

            def canonical(v: object) -> bytes:
                return json.dumps(
                    v, sort_keys=True, separators=(",", ":"), ensure_ascii=True
                ).encode()

            retain(
                artifacts / "backup-proof.json",
                {
                    "status": "passed",
                    "exact_all_rows": True,
                    "callback_count": 12,
                    "provider_before": 6,
                    "provider_after": 6,
                    "before_sha256": hashlib.sha256(canonical(before)).hexdigest(),
                    "after_sha256": hashlib.sha256(canonical(after)).hexdigest(),
                    "reopen_sha256": hashlib.sha256(canonical(reopened)).hexdigest(),
                },
            )
    finally:
        primary = sys.exception()
        deadline = min(final_deadline, time.monotonic() + CLEANUP_SECONDS)

        async def remove_backup_file() -> None:
            if container_created:
                await command(
                    [docker, "exec", container, "rm", "-f", backup_directory + "/schema.sql"],
                    core.base_environment(),
                    "backup-remove",
                )

        async def remove_backup_directory() -> None:
            if container_created:
                await command(
                    [docker, "exec", container, "rmdir", backup_directory],
                    core.base_environment(),
                    "backup-rmdir",
                )

        async def remove_schema() -> None:
            core.remaining(deadline)
            with closing(connect()) as owner:
                row = owner.execute(
                    "SELECT pg_get_userbyid(nspowner) AS owner,obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=%s",
                    [schema],
                ).fetchone()
                if row is not None:
                    if row["owner"] != "continuity_migrator" or row["marker"] not in (
                        "p2-channel-schema-v1",
                        "p2-channel-schema-v2",
                        "p2-channel-schema-v3",
                        "p2-channel-schema-v4",
                        "p2-callback-invalid-marker",
                    ):
                        raise core.GateError("cleanup_ownership_mismatch")
                    owner.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
                if owner.execute(
                    "SELECT 1 FROM pg_namespace WHERE nspname=%s", [schema]
                ).fetchone():
                    raise core.GateError("cleanup_incomplete")

        await cleanup_actions(
            (remove_backup_file, remove_backup_directory, remove_schema), cleanup, primary
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
                "child_terminations": 1,
                "schema_version_observed": 4,
                "authority": "P2_callback_reports_not_delivery_or_resend_authority",
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
            root, args.report or Path(".local/validation/p2-callbacks/" + uuid4().hex + ".json")
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
