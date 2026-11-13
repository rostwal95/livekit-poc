"""Explicit P2 v3 outbox/ordinary local fake-send gate; no provider or callback profile."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable
from contextlib import closing
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
MODE = "local_synthetic_p2_outbox_v3"
CASE_NAMES = (
    "v2_to_v3_original_bytes_preserved",
    "owner_repeat_and_old_upgrade_never_downgrade",
    "failed_upgrade_rolls_back",
    "actual_backup_restore_reopen",
    "runtime_no_ddl_and_catalog_drift_rejected",
    "distinct_publisher_and_recipient_scope",
    "concurrent_equal_enqueue_one_receipt_changed_payload_conflict",
    "enqueue_replay_at_retained_cap",
    "killed_after_enqueue_fresh_process_pending_recovery",
    "missing_route_holds_without_attempt",
    "revoke_before_reservation_zero_send",
    "suppress_before_reservation_zero_send_preserves_history",
    "reservation_before_revoke_keeps_original_possible_attempt",
    "same_recipient_new_verified_route_progress",
    "reassignment_does_not_transfer_reply_or_old_attempt",
    "concurrent_send_one_provider_invocation",
    "ordinary_provider_acceptance_correlated_to_original_attempt",
    "definitive_failure_allows_bounded_explicit_new_attempt",
    "possible_call_unknown_no_retry_or_retarget_after_restart",
    "safe_actual_producer_observations",
    "independent_sql_provider_reconciliation",
    "actual_lock_order_barriers",
    "restricted_owner_runtime_privileges",
    "complete_owned_cleanup",
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
        or set(graphs) != {"upgrade", "route"}
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
        or v["schema_version_observed"] != 3
        or v["authority"] != "P2_reservation_permission_not_external_send_fence"
        or v["blocking_graphs"] != {"upgrade": 1, "route": 2}
        or not core.supported_node(v["node_version"])
        or v["case_results"] != [{"name": n, "status": "passed", "code": "ok"} for n in CASE_NAMES]
    ):
        raise core.GateError("invalid_report")
    return v


def validated_stage(raw: bytes, mode: str) -> dict[str, Any]:
    value = decode(raw)
    expected = {"status", "mode", "cleanup_complete", "node_version"}
    if mode == "replay":
        expected.add("unknownAttemptId")
    if (
        set(value) != expected
        or value.get("status") != "passed"
        or value.get("mode") != mode
        or value.get("cleanup_complete") is not True
        or not core.supported_node(value.get("node_version"))
    ):
        raise core.GateError("invalid_stage")
    if mode == "replay" and (
        type(value["unknownAttemptId"]) is not str
        or re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
            value["unknownAttemptId"],
        )
        is None
    ):
        raise core.GateError("invalid_stage")
    return value


def child_environment(
    values: dict[str, str], context: dict[str, str], *, owner: bool
) -> dict[str, str]:
    allowed = {
        "P2_OUTBOX_SCHEMA",
        "P2_OUTBOX_DIRECTORY",
        "P2_OUTBOX_CARRIER_PORT",
        "P2_OUTBOX_CARRIER_TOKEN",
    }
    if set(context) != allowed:
        raise core.GateError("invalid_environment")
    selected = {
        key: value
        for key, value in context.items()
        if not owner or key in {"P2_OUTBOX_SCHEMA", "P2_OUTBOX_DIRECTORY"}
    }
    return {
        **core.base_environment(),
        **selected,
        "P2_OUTBOX_PG_PORT": values["POSTGRES_PORT"],
        "P2_OUTBOX_OWNER_PASSWORD" if owner else "P2_OUTBOX_RUNTIME_PASSWORD": values[
            "POSTGRES_MIGRATION_PASSWORD" if owner else "POSTGRES_PASSWORD"
        ],
    }


def target_path(root: Path, path: Path) -> Path:
    target = path if path.is_absolute() else root / path
    target = target.absolute()
    allowed = root / ".local/validation/p2-outbox"
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
    node = shutil.which("node")
    compiler = project / "node_modules/typescript/bin/tsc"
    docker = shutil.which("docker")
    if not node or not compiler.is_file() or not docker:
        raise core.GateError("missing_setup")
    schema = "p2_outbox_" + uuid4().hex
    graphs: dict[str, int] = {}
    stage = 0
    node_version = ""
    ledger: list[dict[str, Any]] = []
    writers: set[asyncio.StreamWriter] = set()
    handlers: set[asyncio.Task[Any]] = set()
    server = None
    peer_failures = 0

    def peer_retired(task: asyncio.Task[Any]) -> None:
        nonlocal peer_failures
        if task.cancelled() or task.exception() is not None:
            peer_failures += 1

    container = ""
    backup_directory = ""
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

    async def command(
        argv: list[str], environment: dict[str, str], name: str, *, maximum: int = 65536
    ) -> bytes:
        nonlocal stage
        stage += 1
        out = artifacts / f"{stage:02d}-{name}"

        def actual() -> bytes:
            with OwnedProcess(
                argv, cwd=project, env=environment, output_directory=out, max_output_bytes=maximum
            ) as process:
                result = process.wait(timeout=core.remaining(deadline))
            if process.cleanup_failed or result.returncode or (out / "stderr.bin").read_bytes():
                raise core.GateError("stage_failed_" + name)
            return (out / "stdout.bin").read_bytes()

        return await asyncio.to_thread(actual)

    async def node_mode(mode: str, *, owner: bool = False) -> dict[str, Any]:
        nonlocal node_version
        value = validated_stage(
            await command(
                [node, script, mode], child_environment(values, context, owner=owner), mode
            ),
            mode,
        )
        node_version = value["node_version"]
        return value

    def snapshot(connection: psycopg.Connection[dict[str, Any]]) -> dict[str, Any]:
        result = {}
        for table in (
            "inbox",
            "processing_intents",
            "sender_heads",
            "associations",
            "challenges",
            "conversations",
            "dispatch_plans",
            "dispatch_attempts",
            "dispatch_settings",
        ):
            rows = connection.execute(
                sql.SQL(
                    "SELECT to_jsonb(t) AS value FROM {}.{} t ORDER BY to_jsonb(t)::text"
                ).format(sql.Identifier(schema), sql.Identifier(table))
            ).fetchall()
            result[table] = [r["value"] for r in rows]
        return result

    def outbox_snapshot(connection: psycopg.Connection[dict[str, Any]]) -> dict[str, Any]:
        rows = {}
        for name in (
            "outbox_settings",
            "outbox_admission",
            "reply_intents",
            "outbound_routes",
            "send_attempts",
            "send_results",
        ):
            values = connection.execute(
                sql.SQL(
                    "SELECT to_jsonb(t) AS value FROM {}.{} t ORDER BY to_jsonb(t)::text"
                ).format(sql.Identifier(schema), sql.Identifier(name))
            ).fetchall()
            rows[name] = [value["value"] for value in values]
        return {"original_inbox_dispatch_rows": snapshot(connection), "outbox_rows": rows}

    def table_count(connection: psycopg.Connection[dict[str, Any]], name: str) -> int:
        row = connection.execute(
            sql.SQL("SELECT count(*) AS count FROM {}.{}").format(
                sql.Identifier(schema), sql.Identifier(name)
            )
        ).fetchone()
        assert row is not None
        return int(row["count"])

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
                found = list(reached - {blocker})
                if len(found) >= minimum:
                    return found
                if time.monotonic() >= end:
                    raise core.GateError("unobserved_database_barrier")
                await asyncio.sleep(0.005)

    scratch = project / ".local/p2-outbox-check"
    core.private_directory(scratch)
    try:
        with tempfile.TemporaryDirectory(prefix="run-", dir=scratch) as temporary:
            folder = Path(temporary)
            compiled = folder / "compiled"
            barriers = {
                name: FileBarrier(folder, name)
                for name in ("queued", "race_ready", "race_send", "late")
            }
            ids = [str(uuid4()) for _ in range(6)]
            (folder / "fixture.json").write_text(json.dumps({"ids": ids}))
            (folder / "fixture.json").chmod(0o600)
            for name, configuration in (
                ("build", "tsconfig.json"),
                ("compile", "tsconfig.pg.json"),
            ):
                args = [node, str(compiler), "--project", str(project / configuration)] + (
                    ["--outDir", str(compiled)] if name == "compile" else []
                )
                await command(args, core.base_environment(), name)
            script = str(compiled / "tests/pg_outbox_cases.js")
            carrier_token = secrets.token_urlsafe(32)
            context = {
                "P2_OUTBOX_SCHEMA": schema,
                "P2_OUTBOX_DIRECTORY": str(folder),
                "P2_OUTBOX_CARRIER_PORT": "1",
                "P2_OUTBOX_CARRIER_TOKEN": carrier_token,
            }
            await node_mode("install", owner=True)
            await node_mode("seed")
            await node_mode("before-upgrade")
            with closing(connect()) as owner:
                original = snapshot(owner)
            # An uncommitted future relation name blocks the actual upgrade after earlier DDL.
            with closing(connect()) as blocker:
                blocker.execute("BEGIN")
                blocker.execute(
                    sql.SQL("CREATE TABLE {}.send_results(blocker boolean)").format(
                        sql.Identifier(schema)
                    )
                )
                row = blocker.execute("SELECT pg_backend_pid() AS pid").fetchone()
                assert row
                pid = row["pid"]
                stage += 1
                out = artifacts / f"{stage:02d}-rollback-upgrade"
                with OwnedProcess(
                    [node, script, "upgrade"],
                    cwd=project,
                    env=child_environment(values, context, owner=True),
                    output_directory=out,
                    max_output_bytes=16384,
                ) as process:
                    blocked = await observe(pid, 1, owner=True)
                    graphs["upgrade"] = 1
                    with closing(connect()) as observer:
                        cancelled = observer.execute(
                            "SELECT pg_cancel_backend(%s) AS cancelled", [blocked[0]]
                        ).fetchone()
                        if not cancelled or cancelled["cancelled"] is not True:
                            raise core.GateError("cancel_upgrade_failed")
                    result = await asyncio.to_thread(process.wait, timeout=core.remaining(deadline))
                blocker.execute("ROLLBACK")
                if (
                    result.returncode != 1
                    or process.cleanup_failed
                    or decode((out / "stdout.bin").read_bytes()).get("status") != "failed"
                ):
                    raise core.GateError("rollback_not_observed")
            with closing(connect()) as owner:
                if (
                    snapshot(owner) != original
                    or owner.execute(
                        sql.SQL("SELECT version FROM {}.schema_metadata").format(
                            sql.Identifier(schema)
                        )
                    ).fetchone()
                    != {"version": 2}
                    or owner.execute(
                        "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relname='reply_intents'",
                        [schema],
                    ).fetchone()
                ):
                    raise core.GateError("upgrade_rollback_failed")
            await node_mode("upgrade", owner=True)
            await node_mode("repeat", owner=True)
            with closing(connect()) as owner:
                if snapshot(owner) != original:
                    raise core.GateError("original_data_changed")
            # Actual PostgreSQL pg_dump/psql round trip of only this UUID-owned schema.
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
            backup_directory = "/tmp/p2-outbox-" + uuid4().hex
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
                    str(artifacts / "owned-schema-backup.sql"),
                ],
                core.base_environment(),
                "backup-copy",
            )
            (artifacts / "owned-schema-backup.sql").chmod(0o600)
            with closing(connect()) as owner:
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
            await node_mode("repeat", owner=True)
            with closing(connect()) as owner:
                if snapshot(owner) != original:
                    raise core.GateError("backup_original_data_changed")
            await node_mode("compatibility")
            with closing(connect()) as owner:
                states = owner.execute(
                    sql.SQL("SELECT state FROM {}.processing_intents ORDER BY receipt_id").format(
                        sql.Identifier(schema)
                    )
                ).fetchall()
                if len(states) != 2 or any(row["state"] != "dispatched" for row in states):
                    raise core.GateError("v3_dispatch_compatibility_failed")
            # Runtime catalog drift and counter corruption must not create a reservation.
            # Actual runtime DDL privilege is independently queried below; drift is reversed by owner.
            with closing(connect()) as owner:
                owner.execute(
                    sql.SQL("COMMENT ON SCHEMA {} IS 'p2-outbox-invalid-marker'").format(
                        sql.Identifier(schema)
                    )
                )
            stage += 1
            bad = artifacts / f"{stage:02d}-catalog-drift"
            with OwnedProcess(
                [node, script, "drift-check"],
                cwd=project,
                env=child_environment(values, context, owner=False),
                output_directory=bad,
                max_output_bytes=16384,
            ) as drift:
                result = await asyncio.to_thread(drift.wait, timeout=core.remaining(deadline))
            if (
                result.returncode
                or drift.cleanup_failed
                or validated_stage((bad / "stdout.bin").read_bytes(), "drift-check").get("status")
                != "passed"
            ):
                raise core.GateError("catalog_drift_not_rejected")
            with closing(connect()) as owner:
                owner.execute(
                    sql.SQL("COMMENT ON SCHEMA {} IS 'p2-channel-schema-v3'").format(
                        sql.Identifier(schema)
                    )
                )
            stage += 1
            out = artifacts / f"{stage:02d}-enqueue-kill"
            with OwnedProcess(
                [node, script, "enqueue-kill"],
                cwd=project,
                env=child_environment(values, context, owner=False),
                output_directory=out,
                max_output_bytes=16384,
            ) as process:
                await asyncio.to_thread(process.wait_for_barrier, barriers["queued"], timeout=10)
                with closing(connect()) as owner:
                    if table_count(owner, "reply_intents") != 1 or table_count(
                        owner, "send_attempts"
                    ):
                        raise core.GateError("queue_kill_wrong_boundary")
                termination = process.kill(timeout=5)
                if not termination.killed or termination.returncode != -9:
                    raise core.GateError("owned_kill_not_observed")
            if process.cleanup_failed:
                raise core.GateError("cleanup_incomplete")

            # Independent ordinary fake provider. Persist its actual observations before reply.
            async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
                task = asyncio.current_task()
                assert task is not None
                handlers.add(task)
                task.add_done_callback(peer_retired)
                writers.add(writer)
                try:
                    if len(writers) > 4:
                        return
                    head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 1)
                    if len(head) > 4096:
                        raise ValueError()
                    lines = head.decode("ascii").split("\r\n")
                    headers = {}
                    if lines[0] != "POST /v1/sms/send HTTP/1.1":
                        raise ValueError()
                    for line in lines[1:-2]:
                        key, value = line.split(":", 1)
                        key = key.lower()
                        if key in headers:
                            raise ValueError()
                        headers[key] = value.strip()
                    if (
                        headers.get("authorization") != "Bearer " + carrier_token
                        or headers.get("content-type") != "application/json"
                        or headers.get("connection") != "close"
                        or "transfer-encoding" in headers
                    ):
                        raise ValueError()
                    size = int(headers["content-length"])
                    if not 1 <= size <= 32768:
                        raise ValueError()
                    raw = await asyncio.wait_for(reader.readexactly(size), 1)
                    request = decode(raw)
                    if (
                        request.get("providerScope")
                        != {
                            "tenantId": "tenant-a",
                            "provider": "fake_sms",
                            "providerAccountId": "carrier-a",
                        }
                        or request.get("scope")
                        != {"tenantId": "tenant-a", "accountId": "account-a"}
                        or request.get("caseId") != "case-a"
                        or request.get("conversationId") != "conversation-a"
                    ):
                        raise ValueError()
                    prior = sum(
                        item["request"]["outboundId"] == request["outboundId"] for item in ledger
                    )
                    failed = request["outboundId"] == ids[5] or (
                        request["outboundId"] == ids[3] and prior == 0
                    )
                    response = {
                        "schemaVersion": 1,
                        "attemptId": request["attemptId"],
                        "requestDigest": hashlib.sha256(raw).hexdigest(),
                        "status": "definitive_not_accepted" if failed else "accepted_by_provider",
                    }
                    if not failed:
                        response["providerMessageId"] = "fake-" + uuid4().hex
                    ledger.append({"request": request, "result": response})
                    (folder / "carrier-ledger.json").write_text(json.dumps(ledger))
                    (folder / "carrier-ledger.json").chmod(0o600)
                    body = json.dumps(
                        {"schemaVersion": 1, "status": "known", "result": response},
                        separators=(",", ":"),
                    ).encode()
                    writer.write(
                        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                        + str(len(body)).encode()
                        + b"\r\nConnection: close\r\n\r\n"
                        + body
                    )
                    await writer.drain()
                except (
                    TimeoutError,
                    ValueError,
                    KeyError,
                    asyncio.IncompleteReadError,
                    asyncio.LimitOverrunError,
                    UnicodeError,
                    OSError,
                    core.GateError,
                ):
                    pass
                finally:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except (OSError, RuntimeError):
                        pass
                    writers.discard(writer)
                    handlers.discard(task)

            server = await asyncio.start_server(handle, "127.0.0.1", 0, limit=4096)
            assert server.sockets
            context["P2_OUTBOX_CARRIER_PORT"] = str(server.sockets[0].getsockname()[1])
            stage += 1
            out = artifacts / f"{stage:02d}-exercise"
            with OwnedProcess(
                [node, script, "exercise"],
                cwd=project,
                env=child_environment(values, context, owner=False),
                output_directory=out,
                max_output_bytes=32768,
            ) as process:
                await asyncio.to_thread(
                    process.wait_for_barrier, barriers["race_ready"], timeout=10
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
                    pid = row["pid"]
                    (folder / "race_ready.go").touch(mode=0o600)
                    await asyncio.to_thread(
                        process.wait_for_barrier, barriers["race_send"], timeout=5
                    )
                    await observe(pid, 1, owner=False)
                    (folder / "race_send.go").touch(mode=0o600)
                    await observe(pid, 2, owner=False)
                    graphs["route"] = 2
                    blocker.execute("COMMIT")
                await asyncio.to_thread(process.wait_for_barrier, barriers["late"], timeout=10)
                with closing(connect()) as owner:
                    row = owner.execute(
                        sql.SQL(
                            "SELECT canonical_request FROM {}.send_attempts WHERE outbound_id=%s"
                        ).format(sql.Identifier(schema)),
                        [ids[2]],
                    ).fetchone()
                    if (
                        row is None
                        or json.loads(row["canonical_request"])["senderId"] != "sender-new"
                        or any(x["request"]["outboundId"] == ids[2] for x in ledger)
                    ):
                        raise core.GateError("late_send_wrong_boundary")
                await node_mode("late-revoke")
                (folder / "late.go").touch(mode=0o600)
                result = await asyncio.to_thread(process.wait, timeout=core.remaining(deadline))
            report = validated_stage((out / "stdout.bin").read_bytes(), "exercise")
            if result.returncode or process.cleanup_failed or report.get("status") != "passed":
                raise core.GateError("exercise_failed")
            node_version = report["node_version"]
            before = len(ledger)
            await node_mode("replay")
            if len(ledger) != before:
                raise core.GateError("replay_invoked_provider")
            proof = decode((folder / "proof.json").read_bytes())
            retain(artifacts / "proof.json", proof)
            retain(artifacts / "carrier-ledger.json", {"observations": ledger})
            with closing(connect()) as owner:
                if snapshot(owner) == original:
                    raise core.GateError("missing_route_progress")
                if (
                    table_count(owner, "reply_intents") != 6
                    or table_count(owner, "send_attempts") != 8
                    or table_count(owner, "send_results") != 7
                    or len(ledger) != 7
                ):
                    raise core.GateError("independent_count_mismatch")
                if sum(x["result"]["status"] == "accepted_by_provider" for x in ledger) != 3:
                    raise core.GateError("independent_provider_mismatch")
                rows = owner.execute(
                    sql.SQL(
                        "SELECT a.canonical_request,a.request_digest,r.canonical_result FROM {}.send_attempts a LEFT JOIN {}.send_results r USING(attempt_id)"
                    ).format(sql.Identifier(schema), sql.Identifier(schema))
                ).fetchall()
                matched = set()
                for row in rows:
                    request = json.loads(row["canonical_request"])
                    if (
                        hashlib.sha256(row["canonical_request"].encode()).hexdigest()
                        != row["request_digest"]
                    ):
                        raise core.GateError("request_bytes_mismatch")
                    observation = next(
                        (x for x in ledger if x["request"]["attemptId"] == request["attemptId"]),
                        None,
                    )
                    if observation is None:
                        if request["outboundId"] != ids[4] or row["canonical_result"] is not None:
                            raise core.GateError("unexplained_possible_send")
                    else:
                        if (
                            observation["request"] != request
                            or json.loads(row["canonical_result"]) != observation["result"]
                        ):
                            raise core.GateError("independent_attempt_binding")
                        matched.add(request["attemptId"])
                if len(matched) != 7:
                    raise core.GateError("duplicate_provider_observation")
                if owner.execute(
                    sql.SQL("SELECT reply_count,route_count FROM {}.outbox_admission").format(
                        sql.Identifier(schema)
                    )
                ).fetchone() != {"reply_count": 6, "route_count": 1}:
                    raise core.GateError("admission_count_mismatch")
                # Owner deliberately corrupts only this marked fixture's counter, then restores it.
                owner.execute(
                    sql.SQL("UPDATE {}.outbox_admission SET reply_count=0").format(
                        sql.Identifier(schema)
                    )
                )
            # The held queued race reply must now reject rather than call the provider.
            stage += 1
            bad = artifacts / f"{stage:02d}-corrupt-counter"
            with OwnedProcess(
                [node, script, "counter-check"],
                cwd=project,
                env=child_environment(values, context, owner=False),
                output_directory=bad,
                max_output_bytes=16384,
            ) as counter:
                result = await asyncio.to_thread(counter.wait, timeout=core.remaining(deadline))
            if (
                result.returncode
                or counter.cleanup_failed
                or validated_stage((bad / "stdout.bin").read_bytes(), "counter-check").get("status")
                != "passed"
                or len(ledger) != 7
            ):
                raise core.GateError("corrupt_counter_sent")
            with closing(connect()) as owner:
                owner.execute(
                    sql.SQL("UPDATE {}.outbox_admission SET reply_count=6").format(
                        sql.Identifier(schema)
                    )
                )
            with closing(connect(owner=False)) as runtime:
                role = runtime.execute(
                    "SELECT rolcreatedb,rolcreaterole,rolsuper,rolbypassrls,has_schema_privilege(current_user,%s,'CREATE') AS create_schema FROM pg_roles WHERE rolname=current_user",
                    [schema],
                ).fetchone()
                if not role or any(role.values()):
                    raise core.GateError("runtime_privilege_escape")
                for name in ("reply_intents", "send_attempts", "send_results"):
                    row = runtime.execute(
                        "SELECT has_table_privilege(current_user,%s,'UPDATE') OR has_table_privilege(current_user,%s,'DELETE') OR has_table_privilege(current_user,%s,'TRUNCATE') AS unsafe",
                        [schema + "." + name] * 3,
                    ).fetchone()
                    if not row or row["unsafe"]:
                        raise core.GateError("immutable_privilege_escape")
            # Second, independent round trip now contains every new v3 fact.
            # All runtime processes have exited with actual client cleanup; no writer remains.
            if writers or handlers or len(ledger) != 7:
                raise core.GateError("nonempty_backup_not_quiescent")
            with closing(connect()) as owner:
                nonempty_before = outbox_snapshot(owner)
            outbox_rows = nonempty_before["outbox_rows"]
            if {name: len(rows) for name, rows in outbox_rows.items()} != {
                "outbox_settings": 1,
                "outbox_admission": 1,
                "reply_intents": 6,
                "outbound_routes": 1,
                "send_attempts": 8,
                "send_results": 7,
            }:
                raise core.GateError("nonempty_backup_missing_facts")
            if not any(
                "é🙂" in row["canonical_payload"] and "\\n" in row["canonical_payload"]
                for row in outbox_rows["reply_intents"]
            ):
                raise core.GateError("nonempty_backup_missing_escaped_text")
            retain(artifacts / "nonempty-v3-before.json", nonempty_before)
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
                    "--file=" + backup_directory + "/schema-nonempty.sql",
                ],
                pg_env,
                "nonempty-backup-dump",
            )
            await command(
                [
                    docker,
                    "cp",
                    container + ":" + backup_directory + "/schema-nonempty.sql",
                    str(artifacts / "nonempty-v3-schema-backup.sql"),
                ],
                core.base_environment(),
                "nonempty-backup-copy",
            )
            (artifacts / "nonempty-v3-schema-backup.sql").chmod(0o600)
            with closing(connect()) as owner:
                marker = owner.execute(
                    "SELECT pg_get_userbyid(nspowner) AS owner,obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=%s",
                    [schema],
                ).fetchone()
                if marker != {"owner": "continuity_migrator", "marker": "p2-channel-schema-v3"}:
                    raise core.GateError("nonempty_backup_ownership_mismatch")
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
                    "--file=" + backup_directory + "/schema-nonempty.sql",
                ],
                pg_env,
                "nonempty-backup-restore",
            )
            with closing(connect()) as owner:
                nonempty_after = outbox_snapshot(owner)

            def canonical(value: object) -> bytes:
                return json.dumps(
                    value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
                ).encode()

            if canonical(nonempty_after) != canonical(nonempty_before):
                raise core.GateError("nonempty_backup_row_bytes_changed")
            retain(artifacts / "nonempty-v3-after.json", nonempty_after)
            await node_mode("repeat", owner=True)
            await node_mode("replay")
            with closing(connect()) as owner:
                after_reopen = outbox_snapshot(owner)
            if canonical(after_reopen) != canonical(nonempty_before) or len(ledger) != 7:
                raise core.GateError("nonempty_backup_reopen_changed_facts")
            retain(
                artifacts / "nonempty-v3-proof.json",
                {
                    "status": "passed",
                    "exact_all_snapshot_row_bytes": True,
                    "new_v3_table_counts": {name: len(rows) for name, rows in outbox_rows.items()},
                    "before_sha256": hashlib.sha256(canonical(nonempty_before)).hexdigest(),
                    "after_sha256": hashlib.sha256(canonical(nonempty_after)).hexdigest(),
                    "after_reopen_sha256": hashlib.sha256(canonical(after_reopen)).hexdigest(),
                    "provider_observations_before": 7,
                    "provider_observations_after": len(ledger),
                    "fresh_known_and_unknown_original_replay": True,
                    "escaped_unicode_reply_preserved": True,
                },
            )
    finally:
        primary = sys.exception()
        deadline = min(final_deadline, time.monotonic() + CLEANUP_SECONDS)

        async def close_peer() -> None:
            core.remaining(deadline)
            if server is not None:
                server.close()
                await server.wait_closed()
            for writer in list(writers):
                writer.close()
            if handlers:
                outcomes = await asyncio.wait_for(
                    asyncio.gather(*list(handlers), return_exceptions=True),
                    min(2, core.remaining(deadline)),
                )
                if any(isinstance(outcome, BaseException) for outcome in outcomes):
                    raise core.GateError("cleanup_incomplete")
            if writers or handlers:
                raise core.GateError("cleanup_incomplete")

        async def remove_backup_file() -> None:
            if container_created:
                await command(
                    [
                        docker,
                        "exec",
                        container,
                        "rm",
                        "-f",
                        backup_directory + "/schema.sql",
                        backup_directory + "/schema-nonempty.sql",
                    ],
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
                        "p2-outbox-invalid-marker",
                    ):
                        raise core.GateError("cleanup_ownership_mismatch")
                    owner.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
                if owner.execute(
                    "SELECT 1 FROM pg_namespace WHERE nspname=%s", [schema]
                ).fetchone():
                    raise core.GateError("cleanup_incomplete")

        await cleanup_actions(
            (close_peer, remove_backup_file, remove_backup_directory, remove_schema),
            cleanup,
            primary,
        )
        if peer_failures and primary is None:
            raise core.GateError("fake_provider_task_failed")
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
                "schema_version_observed": 3,
                "authority": "P2_reservation_permission_not_external_send_fence",
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
            root, args.report or Path(".local/validation/p2-outbox/" + uuid4().hex + ".json")
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
