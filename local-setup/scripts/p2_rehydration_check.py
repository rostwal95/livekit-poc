"""Explicit isolated PostgreSQL current-case rehydration qualification.

No settings, database, listener or provider calls occur on import. Runtime and
migration child credentials are role-separated; the public P1 bridge remains an
independently owned parent application, never a copy of P1 case state.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
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
import traceback
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p2_communication_check as previous
import p2_native_check as native
import p2_playback_check as media
import p3_coordinator_check as core

from harness.process_control import FileBarrier, OwnedProcess

ROOT = Path(__file__).resolve().parents[2]
GateError = native.GateError
MODE = "local_synthetic_p2_rehydration"
CASE_NAMES = (
    "native_current_scope_derived",
    "accepted_sms_current_epoch_derived",
    "unaccepted_or_bad_hmac_no_disclosure",
    "wrong_tenant_account_case_denied",
    "native_expiry_behind_lock_denied",
    "revocation_first_denied_and_valid_progress",
    "sms_reassignment_old_receipt_denied",
    "disclosure_admitted_first_not_retracted",
    "standalone_current_authority_over_stale_history",
    "p1_public_current_facts_and_supplier_source",
    "coherent_p2_snapshot_during_append",
    "separate_scoped_paging_and_case_fingerprint",
    "byte_bound_whole_record_paging",
    "no_read_side_effects_or_new_owner",
    "retained_io_timeout_and_later_progress",
    "historical_responses_not_new_room_controls",
    "fresh_process_same_history_new_current_case",
    "original_v7_populated_restore_preserved",
)
OWNER_MODES = frozenset(
    {"install", "verify", "cleanup", "media-install", "media-verify", "media-cleanup"}
)
EXERCISE_GROUPS = tuple(CASE_NAMES[i] for i in (0, 1, 2, 3, 6, 8, 9, 10, 11, 12, 13, 14, 15))
STAGE_EXTRA: dict[str, dict[str, object]] = {
    "install": {"currentCaseSource": "standalone_reference_v1"},
    "seed": {"acceptedInputs": 4, "bindings": 3},
    "exercise": {
        "completedGroups": list(EXERCISE_GROUPS),
        "caseSourceKinds": ["standalone_reference_v1", "p1_public_v4"],
        "readonlyOperations": 1,
    },
    "expiry": {"completedGroups": [CASE_NAMES[4]]},
    "revocation": {"completedGroups": [CASE_NAMES[5], CASE_NAMES[7]]},
    "replay": {"completedGroups": [CASE_NAMES[16]], "factsPreserved": True, "readSideEffects": 0},
    "verify": {"snapshotRowsMatched": True, "readSideEffects": 0},
    "cleanup": {"cleanupComplete": True, "ownedSchemaAbsent": True},
    "media-install": {"currentCaseSource": "standalone_reference_v1"},
    "media-seed": {"nativeBindings": 2, "nativeInputs": 0},
    "media-verify": {
        "nativeInputs": 3,
        "smsInputs": 1,
        "operationAcceptances": 4,
        "nativeReplies": 3,
        "sameCase": True,
        "oldFactsPreserved": True,
    },
    "media-cleanup": {"cleanupComplete": True, "ownedSchemaAbsent": True},
}
COMMON = frozenset({"P2_REHYDRATION_DIRECTORY", "P2_REHYDRATION_SCHEMA", "P2_REHYDRATION_PG_PORT"})
INTEGRATED = frozenset({"P2_REHYDRATION_CURRENT_CASE_PORT", "P2_REHYDRATION_CURRENT_CASE_TOKEN"})
PROOFS = (
    "rehydration-seed-proof.json",
    "rehydration-exercise-proof.json",
    "rehydration-expiry-backends.json",
    "rehydration-expiry-ready.json",
    "rehydration-expiry-proof.json",
    "rehydration-expiry-private.json",
    "rehydration-revocation-proof.json",
    "rehydration-p1-before.json",
    "rehydration-p1-after.json",
    "rehydration-crash-original.json",
    "rehydration-replay-proof.json",
    "rehydration-owner-proof.json",
    "rehydration-restored-replay-proof.json",
    "rehydration-restored-owner-proof.json",
    "rehydration-operations.json",
)
BARRIERS = (
    "rehydration_expiry_ready",
    "rehydration_expiry_waiting",
    "rehydration_after_read",
    "rehydration_p1_advance",
)


def validate_child_environment(environment: dict[str, str], mode: str) -> None:
    if mode not in {*STAGE_EXTRA, "crash", "media-serve", "media-sms"}:
        raise GateError("invalid_environment")
    role = (
        "P2_REHYDRATION_OWNER_PASSWORD"
        if mode in OWNER_MODES
        else "P2_REHYDRATION_RUNTIME_PASSWORD"
    )
    required = COMMON | {role} | (INTEGRATED if mode == "exercise" else set())
    if (
        not required <= environment.keys()
        or environment.keys() - required - core.BASE_ENVIRONMENT_KEYS
        or any(type(v) is not str or not v or len(v) > 4096 for v in environment.values())
        or re.fullmatch(
            r"p2_rehydration_[a-f0-9]{32}", environment.get("P2_REHYDRATION_SCHEMA", "")
        )
        is None
        or re.fullmatch(r"[1-9][0-9]{0,4}", environment.get("P2_REHYDRATION_PG_PORT", "")) is None
        or not 1 <= int(environment["P2_REHYDRATION_PG_PORT"]) <= 65535
    ):
        raise GateError("invalid_environment")
    directory = Path(environment["P2_REHYDRATION_DIRECTORY"])
    if not directory.is_absolute() or directory != directory.resolve() or directory.is_symlink():
        raise GateError("invalid_environment")
    if mode == "exercise" and (
        re.fullmatch(r"[A-Za-z0-9_-]{43}", environment["P2_REHYDRATION_CURRENT_CASE_TOKEN"]) is None
        or re.fullmatch(r"[1-9][0-9]{0,4}", environment["P2_REHYDRATION_CURRENT_CASE_PORT"]) is None
        or not 1 <= int(environment["P2_REHYDRATION_CURRENT_CASE_PORT"]) <= 65535
    ):
        raise GateError("invalid_environment")


def child_environment(
    values: dict[str, str],
    common: dict[str, str],
    mode: str,
    integrated: dict[str, str] | None = None,
) -> dict[str, str]:
    owner = mode in OWNER_MODES
    result = {
        **core.base_environment(),
        **common,
        "P2_REHYDRATION_OWNER_PASSWORD" if owner else "P2_REHYDRATION_RUNTIME_PASSWORD": values[
            "POSTGRES_MIGRATION_PASSWORD" if owner else "POSTGRES_PASSWORD"
        ],
    }
    if mode == "exercise":
        result.update(integrated or {})
    validate_child_environment(result, mode)
    return result


def validated_stage(raw: bytes, mode: str) -> dict[str, Any]:
    if mode not in STAGE_EXTRA:
        raise GateError("invalid_stage")
    expected = {
        "schemaVersion": 1,
        "status": "passed",
        "mode": mode,
        "nodeVersion": "24.22.2",
        "storageVersion": 0 if mode in {"cleanup", "media-cleanup"} else 7,
        **STAGE_EXTRA[mode],
    }
    value = native.decode(raw)
    if not native.exact(value, expected):
        raise GateError("invalid_stage")
    return value


def fixture(run_id: str) -> dict[str, Any]:
    scope = {"tenantId": "rehydration-tenant", "accountId": "rehydration-account"}
    return {
        "schemaVersion": 1,
        "scope": scope,
        "providerScope": {
            "tenantId": scope["tenantId"],
            "provider": "livekit",
            "providerAccountId": "local-native",
        },
        "caseId": "rehydration-case",
        "conversationId": "rehydration-conversation",
        **{
            k: secrets.token_urlsafe(32) for k in ("accountToken", "publisherToken", "prepareToken")
        },
        "expiresAt": (datetime.now(UTC) + timedelta(seconds=180))
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "bindings": {
            label: {
                "bindingId": str(uuid4()),
                "roomId": "p2-rehydration-" + run_id + "-" + label.lower(),
                "participantId": "browser-" + run_id + "-" + label.lower(),
                "agentId": "agent-" + run_id + "-" + label.lower(),
                "bindingToken": secrets.token_urlsafe(32),
            }
            for label in ("A", "B")
        },
        "ids": {k: str(uuid4()) for k in ("voice", "text", "sms", "newText")},
        "communication": {
            k: secrets.token_urlsafe(32) for k in ("publisherToken", "sdkToken", "browserToken")
        },
        "sms": {
            "providerScope": {
                "tenantId": scope["tenantId"],
                "provider": "fake_sms",
                "providerAccountId": "local-sms",
            },
            "senderId": "demo-sender",
            "hmacKeyBase64": base64.b64encode(secrets.token_bytes(32)).decode("ascii"),
        },
        "referenceRequest": {
            "schemaVersion": 1,
            "kind": "booking_investigation",
            "bookingReference": "DEMO-BK-001",
            "newCheckIn": "2030-12-10",
            "investigationConsent": True,
        },
    }


def source_bytes(path: Path) -> bytes:
    """Public maintained files are not private proof files; still reject links/races."""
    before = path.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or not 0 < before.st_size <= 1048576
    ):
        raise GateError("unsafe_source_file")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino, opened.st_size) != (
            before.st_dev,
            before.st_ino,
            before.st_size,
        ):
            raise GateError("unsafe_source_file")
        raw = stream.read(1048577)
    if len(raw) != before.st_size:
        raise GateError("unsafe_source_file")
    return raw


def source_snapshot(root: Path) -> dict[str, str]:
    paths = [
        *sorted((root / "projects/channel-continuity/src").glob("*.ts")),
        root / "projects/channel-continuity/package.json",
        root / "projects/channel-continuity/tsconfig.pg.json",
        root / "projects/channel-continuity/tests/pg_rehydration_cases.ts",
        *(
            root / "local-setup/scripts" / name
            for name in (
                "p2_rehydration_check.py",
                "p2_rehydration_p1.py",
                "p2_current_case_bridge.py",
                "p3_case_fixture.py",
                "p2_native_check.py",
                "p2_communication_check.py",
                "p2_playback_check.py",
                "p3_coordinator_check.py",
            )
        ),
        root / "harness/process_control.py",
        root / "harness/__init__.py",
        root / "local-setup/stack.py",
    ]
    paths.extend(
        sorted((root / "projects/agent-continuity/python/src/continuity_lab").glob("*.py"))
    )
    paths.extend(
        sorted((root / "projects/channel-continuity/python/src/channel_continuity").glob("*.py"))
    )
    paths.extend(root / n for n in ("pyproject.toml", "uv.lock", "pnpm-lock.yaml"))
    return {str(p.relative_to(root)): hashlib.sha256(source_bytes(p)).hexdigest() for p in paths}


def retained_index(directory: Path) -> dict[str, Any]:
    entries = {}
    for p in sorted(directory.rglob("*")):
        info = p.lstat()
        if p.is_symlink() or info.st_uid != os.getuid():
            raise GateError("unsafe_evidence_path")
        if p.is_dir():
            os.chmod(p, 0o700)
        elif p.is_file() and info.st_nlink == 1:
            if p == directory / "retained-index.json":
                raise GateError("report_exists")
            os.chmod(p, 0o600)
            entries[str(p.relative_to(directory))] = {
                "bytes": info.st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
        else:
            raise GateError("unsafe_evidence_path")
    if not entries:
        raise GateError("evidence_missing")
    value = {"schemaVersion": 1, "files": entries}
    native.write_json(directory / "retained-index.json", value, maximum=1048576)
    return value


def snapshot(connect: Any, schemas: tuple[str, ...]) -> dict[str, Any]:
    from psycopg import sql

    result: dict[str, Any] = {}
    with closing(connect()) as c:
        for schema in schemas:
            names = [
                r[0]
                for r in c.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname=%s ORDER BY tablename",
                    [schema],
                )
            ]
            if not 1 <= len(names) <= 64:
                raise GateError("invalid_snapshot")
            tables = {}
            for name in names:
                rows = c.execute(
                    sql.SQL(
                        "SELECT to_jsonb(t) FROM {}.{} t ORDER BY to_jsonb(t)::text LIMIT 65"
                    ).format(sql.Identifier(schema), sql.Identifier(name))
                ).fetchall()
                if len(rows) > 64:
                    raise GateError("snapshot_limit")
                tables[name] = [r[0] for r in rows]
            result[schema] = tables
    if len(json.dumps(result).encode()) > 2097152:
        raise GateError("snapshot_limit")
    return result


def expiry_schedule(
    children: previous.Children,
    child: OwnedProcess,
    barriers: dict[str, FileBarrier],
    work: Path,
    connect: Any,
    schema: str,
    artifacts: Path,
) -> None:
    from psycopg import sql

    child.wait_for_barrier(
        barriers["rehydration_expiry_ready"], timeout=min(10, native.remaining(children.deadline))
    )
    ready = native.decode(media.bounded_read(work / "rehydration-expiry-ready.json", maximum=1024))
    if (
        set(ready) != {"schemaVersion", "bindingId", "expiresAt", "processId", "schema"}
        or type(ready["schemaVersion"]) is not int
        or ready["schemaVersion"] != 1
        or ready["processId"] != child.pid
        or type(ready["processId"]) is not int
        or ready["schema"] != schema
        or not media.is_uuid(ready["bindingId"])
    ):
        raise GateError("invalid_expiry_proof")
    try:
        expiry = datetime.fromisoformat(ready["expiresAt"])
    except (ValueError, TypeError):
        raise GateError("invalid_expiry_proof") from None
    with closing(connect()) as connection, connection.transaction():
        connection.execute(
            sql.SQL("SELECT * FROM {}.admission WHERE singleton FOR UPDATE").format(
                sql.Identifier(schema)
            )
        )
        row = connection.execute(
            sql.SQL("SELECT expires_at FROM {}.native_bindings WHERE binding_id=%s").format(
                sql.Identifier(schema)
            ),
            [ready["bindingId"]],
        ).fetchone()
        if row is None or row[0] != expiry:
            raise GateError("expiry_original_join_mismatch")
        owner = connection.info.backend_pid
        child.release_barrier(barriers["rehydration_expiry_ready"])
        child.wait_for_barrier(
            barriers["rehydration_expiry_waiting"],
            timeout=min(2, native.remaining(children.deadline)),
        )
        identity = native.decode(
            media.bounded_read(work / "rehydration-expiry-backends.json", maximum=1024)
        )
        if (
            set(identity) != {"schemaVersion", "phase", "schema", "processId", "backendIds"}
            or identity["schemaVersion"] != 1
            or type(identity["schemaVersion"]) is not int
            or identity["phase"] != "expiry"
            or identity["schema"] != schema
            or identity["processId"] != child.pid
            or type(identity["processId"]) is not int
            or type(identity["backendIds"]) is not list
            or len(identity["backendIds"]) != 1
            or type(identity["backendIds"][0]) is not int
            or identity["backendIds"][0] <= 0
            or identity["backendIds"][0] == owner
        ):
            raise GateError("invalid_backend_identity")
        backend = identity["backendIds"][0]
        until = min(children.deadline, time.monotonic() + 2)
        first = None
        while True:
            connection.execute("SELECT pg_stat_clear_snapshot()")
            edge = connection.execute(
                "SELECT pid,pg_blocking_pids(pid) FROM pg_stat_activity WHERE usename='livekit_lab' AND pid=%s",
                [backend],
            ).fetchone()
            clock = connection.execute(
                "SELECT date_trunc('milliseconds',clock_timestamp())"
            ).fetchone()[0]
            if edge is not None and edge[0] == backend and set(edge[1]) == {owner}:
                if first is None:
                    first = clock
                    if not first < expiry:
                        raise GateError("expiry_wait_not_before_deadline")
                if clock >= expiry:
                    break
            if time.monotonic() >= until:
                raise GateError("actual_owned_sql_waiter_missing")
            time.sleep(0.002)
        native.write_json(
            artifacts / "rehydration-expiry-lock.json",
            {
                "schemaVersion": 1,
                "schema": schema,
                "ownedChildPid": child.pid,
                "ownedBackendId": backend,
                "ownerBackendPid": owner,
                "blockers": [owner],
                "firstWaitObservedDbClock": first.isoformat(timespec="milliseconds"),
                "releaseObservedDbClock": clock.isoformat(timespec="milliseconds"),
                "expiresAt": ready["expiresAt"],
                "queryTextObserved": False,
            },
        )


def owned_children_settled(children: previous.Children) -> bool:
    """DDL cannot race a stop request whose actual owned process is unresolved."""
    return all(
        type(child.returncode) is int and child.cleanup_failed is False
        for child in children.children
    )


async def run(
    root: Path, artifacts: Path, started: float, cleanup: dict[str, bool]
) -> dict[str, Any]:
    import psycopg
    from p2_rehydration_p1 import P1ReadFixture
    from psycopg import sql

    final = started + 180
    deadline = final - 15
    setup = core.load_setup(root)
    values = setup.load_settings()
    node, docker = shutil.which("node"), shutil.which("docker")
    project = root / "projects/channel-continuity"
    compiler = project / "node_modules/typescript/bin/tsc"
    if not node or not docker or not compiler.is_file():
        raise GateError("missing_setup")
    run_id = uuid4().hex
    schema = "p2_rehydration_" + run_id
    case_schema = "p2_case_rehydration_" + run_id
    scratch = project / ".local/rehydration-check"
    core.private_directory(scratch)
    frozen = source_snapshot(root)
    native.write_json(artifacts / "source-before.json", frozen, maximum=262144)
    work = Path(tempfile.mkdtemp(prefix="run-", dir=scratch)).resolve()
    try:
        os.chmod(work, 0o700)
        native.write_json(
            work / "rehydration-owned-work.json", {"schemaVersion": 1, "schema": schema}
        )
        children = previous.Children(work, deadline)
        barriers = {name: FileBarrier(work, name) for name in BARRIERS}
        common = {
            "P2_REHYDRATION_DIRECTORY": str(work),
            "P2_REHYDRATION_SCHEMA": schema,
            "P2_REHYDRATION_PG_PORT": values["POSTGRES_PORT"],
        }
        f = fixture(run_id)
        native.write_json(work / "fixture.json", f)
        reference = {k: f[k] for k in ("scope", "caseId", "conversationId")}
        p1 = P1ReadFixture(values, work, reference)
        script = work / "compiled/tests/pg_rehydration_cases.js"
        groups: set[str] = set()
        installed = False
        backup_possible = False
        container = ""
        backup_dir = "/tmp/p2-rehydration-" + run_id
        kills = []
        integrated: dict[str, str] = {}
        exclusions = (
            tuple(values[k] for k in setup.SECRET_KEYS)
            + tuple(
                v
                for d in (f, f["communication"], f["bindings"]["A"], f["bindings"]["B"])
                for k, v in d.items()
                if k.endswith("Token")
            )
            + (f["sms"]["hmacKeyBase64"], p1.token)
        )

        def connect() -> Any:
            return psycopg.connect(
                host="127.0.0.1",
                port=int(values["POSTGRES_PORT"]),
                dbname="livekit_lab",
                user="continuity_migrator",
                password=values["POSTGRES_MIGRATION_PASSWORD"],
                sslmode="disable",
                connect_timeout=2,
                options="-c search_path=pg_catalog -c statement_timeout=3000 -c lock_timeout=1500",
                autocommit=True,
            )

        def stage(mode: str, label: str | None = None, end: float | None = None) -> dict[str, Any]:
            raw = children.call(
                label or mode,
                [node, str(script), mode],
                child_environment(values, common, mode, integrated),
                cwd=work,
                deadline=min(end or deadline, time.monotonic() + 20),
            )
            result = validated_stage(raw, mode)
            groups.update(result.get("completedGroups", []))
            return result

        try:
            await asyncio.to_thread(
                children.call,
                "compile",
                [
                    node,
                    str(compiler),
                    "--project",
                    str(project / "tsconfig.pg.json"),
                    "--outDir",
                    str(work / "compiled"),
                ],
                core.base_environment(),
                cwd=project,
                deadline=min(deadline, time.monotonic() + 30),
            )
            native.write_json(
                artifacts / "runtime-build-parity.json",
                native.verify_runtime_build(project, work / "compiled"),
            )
            installed = True
            await asyncio.to_thread(stage, "install")
            await asyncio.to_thread(stage, "seed")
            port = await p1.bounded(p1.start(), min(deadline, time.monotonic() + 20))
            integrated = {
                "P2_REHYDRATION_CURRENT_CASE_PORT": str(port),
                "P2_REHYDRATION_CURRENT_CASE_TOKEN": p1.token,
            }
            expiry_deadline = min(deadline, time.monotonic() + 20)
            expiry = children.start(
                "expiry",
                [node, str(script), "expiry"],
                child_environment(values, common, "expiry"),
                cwd=work,
            )
            await asyncio.to_thread(
                expiry_schedule, children, expiry, barriers, work, connect, schema, artifacts
            )
            groups.update(
                validated_stage(
                    await asyncio.to_thread(children.finish, expiry, deadline=expiry_deadline),
                    "expiry",
                )["completedGroups"]
            )
            await asyncio.to_thread(stage, "revocation")
            exercise_deadline = min(deadline, time.monotonic() + 20)
            exercise = children.start(
                "exercise",
                [node, str(script), "exercise"],
                child_environment(values, common, "exercise", integrated),
                cwd=work,
            )
            await asyncio.to_thread(
                exercise.wait_for_barrier,
                barriers["rehydration_p1_advance"],
                timeout=min(12, native.remaining(deadline)),
            )
            native.write_json(
                artifacts / "rehydration-p1-supplier-proof.json",
                await p1.bounded(p1.advance(), exercise_deadline),
            )
            exercise.release_barrier(barriers["rehydration_p1_advance"])
            groups.update(
                validated_stage(
                    await asyncio.to_thread(children.finish, exercise, deadline=exercise_deadline),
                    "exercise",
                )["completedGroups"]
            )
            crash = children.start(
                "crash",
                [node, str(script), "crash"],
                child_environment(values, common, "crash"),
                cwd=work,
            )
            await asyncio.to_thread(
                crash.wait_for_barrier,
                barriers["rehydration_after_read"],
                timeout=min(10, native.remaining(deadline)),
            )
            kills.append(await asyncio.to_thread(children.kill, crash))
            await asyncio.to_thread(stage, "replay")
            await asyncio.to_thread(stage, "verify")
            before = await asyncio.to_thread(snapshot, connect, (schema, case_schema))
            native.write_json(artifacts / "before-restore.json", before, maximum=2097152)
            container = (
                (
                    await asyncio.to_thread(
                        children.call,
                        "backup-container",
                        [
                            docker,
                            "ps",
                            "--filter",
                            "label=com.docker.compose.service=postgres",
                            "--filter",
                            "label=com.docker.compose.project.working_dir="
                            + str(root / "local-setup"),
                            "--format",
                            "{{.ID}}",
                        ],
                        core.base_environment(),
                        cwd=work,
                    )
                )
                .decode()
                .strip()
            )
            if re.fullmatch(r"[a-f0-9]{12,64}", container) is None:
                raise GateError("wrong_backup_container")
            backup_possible = True
            await asyncio.to_thread(
                children.call,
                "backup-directory",
                [docker, "exec", container, "mkdir", "-m", "700", backup_dir],
                core.base_environment(),
                cwd=work,
            )
            pg_env = {
                **core.base_environment(),
                "PGPASSWORD": values["POSTGRES_MIGRATION_PASSWORD"],
            }
            await asyncio.to_thread(
                children.call,
                "backup-dump",
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
                    "--schema=" + case_schema,
                    "--inserts",
                    "--no-owner",
                    "--file=" + backup_dir + "/schema.sql",
                ],
                pg_env,
                cwd=work,
            )
            await asyncio.to_thread(
                children.call,
                "backup-copy",
                [
                    docker,
                    "cp",
                    container + ":" + backup_dir + "/schema.sql",
                    str(work / "rehydration-backup.sql"),
                ],
                core.base_environment(),
                cwd=work,
            )
            with closing(connect()) as c:
                for target, marker in (
                    (schema, "p2-channel-schema-v7"),
                    (case_schema, "p2-reference-case-v1"),
                ):
                    row = c.execute(
                        "SELECT pg_get_userbyid(nspowner),obj_description(oid,'pg_namespace') FROM pg_namespace WHERE nspname=%s",
                        [target],
                    ).fetchone()
                    if row != ("continuity_migrator", marker):
                        raise GateError("backup_owner_mismatch")
                    c.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(target)))
            await asyncio.to_thread(
                children.call,
                "backup-restore",
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
                    "--file=" + backup_dir + "/schema.sql",
                ],
                pg_env,
                cwd=work,
            )
            restored = await asyncio.to_thread(snapshot, connect, (schema, case_schema))
            await asyncio.to_thread(stage, "replay", "restored-replay")
            await asyncio.to_thread(stage, "verify", "restored-verify")
            reopened = await asyncio.to_thread(snapshot, connect, (schema, case_schema))
            if before != restored or restored != reopened:
                raise GateError("restored_rows_changed")
            native.write_json(artifacts / "after-restore.json", restored, maximum=2097152)
            native.write_json(artifacts / "reopened-restore.json", reopened, maximum=2097152)
            validate_context_proofs(
                work, before, schema, f, artifacts / "rehydration-p1-supplier-proof.json"
            )
            groups.add(CASE_NAMES[17])
            if groups != set(CASE_NAMES):
                raise GateError("missing_named_assertions")
            native.write_json(artifacts / "owned-kills.json", {"schemaVersion": 1, "kills": kills})
            for name in PROOFS:
                native.safe_copy(work / name, artifacts / name, exclusions, maximum=262144)
            native.safe_copy(
                script, artifacts / "pg_rehydration_cases.js", exclusions, maximum=262144
            )
        finally:
            primary = sys.exception()
            failed = False
            children.deadline = final
            for child in reversed(children.children):
                if child.returncode is None:
                    try:
                        await asyncio.to_thread(
                            children.stop, child, deadline=min(final, time.monotonic() + 3)
                        )
                    except BaseException:  # noqa: BLE001 - close every child before owner cleanup.
                        failed = True
            try:
                children.close()
            except BaseException:  # noqa: BLE001 - attempt every independent child; dependent DDL uses public settlement below.
                failed = True
            if not owned_children_settled(children):
                failed = True
            try:
                if primary is not None:
                    safe = {
                        "schemaVersion": 1,
                        "type": "GateError"
                        if isinstance(primary, GateError)
                        else "DependencyError",
                        "code": primary.code if isinstance(primary, GateError) else "gate_failed",
                        "frames": [
                            {"file": Path(frame.filename).name, "line": frame.lineno}
                            for frame in traceback.extract_tb(primary.__traceback__)
                            if Path(frame.filename).name
                            in {
                                "p2_rehydration_check.py",
                                "p2_rehydration_p1.py",
                                "p2_current_case_bridge.py",
                                "p3_case_fixture.py",
                            }
                        ][-4:],
                        "children": [
                            {
                                "name": c.output_directory.name,
                                "pid": c.pid,
                                "returncode": c.returncode,
                            }
                            for c in children.children
                        ],
                    }
                    native.write_json(artifacts / "failure-context.json", safe)
                    for name in (
                        "install",
                        "seed",
                        "expiry",
                        "exercise",
                        "revocation",
                        "crash",
                        "replay",
                        "verify",
                    ):
                        p = work / ("rehydration-failure-" + name + ".json")
                        if p.exists():
                            native.safe_copy(p, artifacts / p.name, exclusions, maximum=4096)
            except BaseException:  # noqa: BLE001 - diagnostics cannot replace primary or skip cleanup.
                failed = True
            if primary is not None:
                # Retain every available approved source proof before removing
                # quiescent private inputs; each diagnostic is independent.
                for name in (*PROOFS, "rehydration-replay-comparison.json"):
                    try:
                        source = work / name
                        proof_target = artifacts / name
                        if source.exists():
                            if proof_target.exists():
                                if media.bounded_read(
                                    proof_target, maximum=262144
                                ) != media.bounded_read(source, maximum=262144):
                                    raise GateError("diagnostic_identity_mismatch")
                            else:
                                native.safe_copy(source, proof_target, exclusions, maximum=262144)
                    except BaseException:  # noqa: BLE001 - preserve primary and continue independent diagnostics/cleanup.
                        failed = True
            p1_closed = False
            try:
                await p1.close(deadline=final)
                p1_closed = True
            except BaseException:  # noqa: BLE001 - retain unresolved P1 I/O and primary while closing independent children.
                failed = True
            if installed:
                if owned_children_settled(children) and p1_closed:
                    try:
                        await asyncio.to_thread(stage, "cleanup", None, final)
                    except BaseException:  # noqa: BLE001 - independently owned schema cleanup after actual dependencies settle.
                        failed = True
                else:
                    failed = True
            if backup_possible and owned_children_settled(children):
                try:
                    await asyncio.to_thread(
                        children.call,
                        "backup-remove",
                        [docker, "exec", container, "rm", "-rf", "--", backup_dir],
                        core.base_environment(),
                        cwd=work,
                        deadline=final,
                    )
                except BaseException:  # noqa: BLE001 - exact UUID-owned backup path only.
                    failed = True
            elif backup_possible:
                failed = True
            try:
                children.close()
            except BaseException:  # noqa: BLE001 - preserve actual cleanup incompleteness.
                failed = True
            cleanup["cleanup_complete"] = (
                not failed and p1_closed and owned_children_settled(children)
            )
            if failed and primary is None:
                raise GateError("cleanup_incomplete")
        if source_snapshot(root) != frozen:
            raise GateError("source_changed_during_measurement")
        retained_index(artifacts)
        validate_retained_index(
            artifacts, hashlib.sha256((artifacts / "retained-index.json").read_bytes()).hexdigest()
        )
        return validated_report(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "passed",
                    "mode": MODE,
                    "tests": 18,
                    "passed": 18,
                    "errors": 0,
                    "failures": 0,
                    "skipped": 0,
                    "case_results": [
                        {"name": n, "status": "passed", "code": "ok"} for n in CASE_NAMES
                    ],
                    "cleanup_complete": cleanup["cleanup_complete"],
                    "schema_version_observed": 7,
                    "owned_child_terminations": 1,
                    "blocking_graphs_observed": 1,
                    "populated_restore_verified": True,
                    "actual_p1_supplier_apply_calls": 1,
                    "provider_calls": False,
                    "actual_browser_qualification_claimed": False,
                    "human_acknowledgement_claimed": False,
                    "duration_seconds": time.monotonic() - started,
                    "child_commands": children.count,
                    "node_version": "24.22.2",
                    "retained_index_sha256": hashlib.sha256(
                        (artifacts / "retained-index.json").read_bytes()
                    ).hexdigest(),
                }
            ).encode()
        )

    finally:
        first = sys.exception()
        cleanup_error: BaseException | None = None
        if cleanup["cleanup_complete"]:
            try:
                native.remaining(final)
                remove_owned_work(work, scratch, schema)
                native.remaining(final)
            except BaseException as error:  # noqa: BLE001 - preserve original failure and actual cleanup state.
                cleanup["cleanup_complete"] = False
                cleanup_error = error
        if not cleanup["cleanup_complete"]:
            # Preserve actual owner inputs while closure is unresolved. Removing
            # a supplier file under an in-flight thread would fabricate cleanup.
            try:
                native.write_json(
                    artifacts / "owned-work-retained.json",
                    {
                        "schemaVersion": 1,
                        "directory": str(work.relative_to(root)),
                        "schema": schema,
                        "caseSchema": case_schema,
                        "cleanupComplete": False,
                    },
                )
            except BaseException:  # noqa: BLE001 - failed diagnostics cannot replace the primary or skip cleanup.
                cleanup["cleanup_complete"] = False
        if first is None and cleanup_error is not None:
            raise GateError("cleanup_incomplete") from None


def remove_owned_work(work: Path, scratch: Path, schema: str) -> None:
    if (
        work.is_symlink()
        or work.parent != scratch.resolve()
        or not re.fullmatch(r"run-[a-z0-9_-]{6,32}", work.name)
    ):
        raise GateError("cleanup_incomplete")
    marker = native.decode(media.bounded_read(work / "rehydration-owned-work.json", maximum=256))
    if not native.exact(marker, {"schemaVersion": 1, "schema": schema}):
        raise GateError("cleanup_incomplete")
    shutil.rmtree(work)
    if work.exists():
        raise GateError("cleanup_incomplete")


def sql_instant(value: object) -> str:
    if type(value) is not str:
        raise GateError("source_identity_mismatch")
    try:
        observed = datetime.fromisoformat(value)
        if observed.tzinfo is None:
            raise ValueError()
        return observed.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    except ValueError:
        raise GateError("source_identity_mismatch") from None


def validate_original_receipt(receipt: object, row: dict[str, Any], kind: str) -> None:
    if kind == "history":
        expected = {
            "receiptId": row["receipt_id"],
            "eventId": row["event_id"],
            "messageId": row["message_id"],
            "acceptanceSequence": str(row["acceptance_sequence"]),
            "acceptedAt": sql_instant(row["accepted_at"]),
        }
    elif kind == "response":
        expected = {
            "responseId": row["response_id"],
            "receiptId": row["receipt_id"],
            "anchorDigest": row["anchor_digest"],
            "responseSequence": str(row["response_sequence"]),
            "acceptedAt": sql_instant(row["accepted_at"]),
        }
    else:
        raise GateError("source_identity_mismatch")
    if not native.exact(receipt, expected):
        raise GateError("source_identity_mismatch")


def validate_context_proofs(
    work: Path, snapshot: dict[str, Any], schema: str, f: dict[str, Any], supplier_proof: Path
) -> None:
    """Consumer decoding and independent SQL/supplier joins, not child self-report."""
    from channel_continuity.codec import (
        AccountScope,
        ProviderScope,
        TrustedPrincipal,
        parse_event_json,
    )
    from channel_continuity.native_rehydration import context_from

    tables = snapshot[schema]
    if any(
        len(tables[k]) != n
        for k, n in {
            "inbox": 14,
            "native_bindings": 6,
            "dispatch_plans": 1,
            "native_responses": 1,
            "native_observations": 3,
            "reply_intents": 1,
            "send_attempts": 0,
            "send_results": 0,
        }.items()
    ):
        raise GateError("invalid_inventory")
    original = {row["receipt_id"]: row for row in tables["inbox"]}
    processing = {row["receipt_id"]: row for row in tables["processing_intents"]}
    allowed = [
        (f["scope"], f["caseId"], f["conversationId"]),
        (
            {"tenantId": f["scope"]["tenantId"], "accountId": f["scope"]["accountId"] + "-other"},
            f["caseId"] + "-other",
            f["conversationId"] + "-other",
        ),
    ]
    exercise = native.decode(
        media.bounded_read(work / "rehydration-exercise-proof.json", maximum=262144), maximum=262144
    )
    contexts = [
        exercise[k]
        for k in (
            "initial",
            "fromSms",
            "current",
            "p1Context",
            "foreign",
            "beforeAppend",
            "firstPage",
            "secondPage",
        )
    ]
    for name in (
        "rehydration-p1-before.json",
        "rehydration-p1-after.json",
        "rehydration-replay-proof.json",
        "rehydration-restored-replay-proof.json",
        "rehydration-crash-original.json",
    ):
        contexts.append(
            native.decode(media.bounded_read(work / name, maximum=262144), maximum=262144)[
                "context"
            ]
        )
    for context in contexts:
        decoded = cast(dict[str, Any], context_from(context).payload())
        for retained in decoded["history"]["messages"]:
            receipt = retained["receipt"]
            row = original.get(receipt["receiptId"])
            if (
                row is None
                or json.loads(row["wire_json"]) != retained["event"]
                or row["event_id"] != receipt["eventId"]
                or row["message_id"] != receipt["messageId"]
                or str(row["acceptance_sequence"]) != receipt["acceptanceSequence"]
                or str(row["association_epoch"]) != retained["associationVersion"]
                or sql_instant(row["accepted_at"]) != receipt["acceptedAt"]
            ):
                raise GateError("source_identity_mismatch")
            validate_original_receipt(receipt, row, "history")
            parsed = parse_event_json(
                row["wire_json"],
                TrustedPrincipal(
                    ProviderScope(row["tenant_id"], row["provider"], row["provider_account_id"]),
                    AccountScope(row["tenant_id"], row["account_id"]),
                ),
            )
            intent = processing.get(receipt["receiptId"])
            if (
                parsed.canonical != row["canonical_payload"]
                or intent is None
                or intent["operation_key"] != retained["operationKey"]
                or intent["state"] != retained["processingState"]
                or row["conversation_id"] != retained["event"]["conversationId"]
                or retained["event"].get("accountScope")
                != {"tenantId": row["tenant_id"], "accountId": row["account_id"]}
            ):
                raise GateError("source_identity_mismatch")
        current = decoded["case"]
        if (current["scope"], current["caseId"], current["conversationId"]) not in allowed:
            raise GateError("source_identity_mismatch")
        for response in decoded["responses"]["items"]:
            anchor = response["anchor"]
            matches = [
                row
                for row in tables["native_responses"]
                if row["response_id"] == anchor["responseId"]
            ]
            if (
                len(matches) != 1
                or json.loads(matches[0]["canonical_anchor"]) != anchor
                or hashlib.sha256(matches[0]["canonical_anchor"].encode()).hexdigest()
                != response["receipt"]["anchorDigest"]
                or matches[0]["receipt_id"] != response["receipt"]["receiptId"]
                or str(matches[0]["response_sequence"]) != response["receipt"]["responseSequence"]
                or sql_instant(matches[0]["accepted_at"]) != response["receipt"]["acceptedAt"]
            ):
                raise GateError("source_identity_mismatch")
            validate_original_receipt(response["receipt"], matches[0], "response")
        for work_ref in decoded["work"]["items"]:
            row = original.get(work_ref["receiptId"])
            intent = processing.get(work_ref["receiptId"])
            if (
                row is None
                or intent is None
                or work_ref["operationKey"] != intent["operation_key"]
                or work_ref["acceptanceSequence"] != str(row["acceptance_sequence"])
                or work_ref["state"] != intent["state"]
                or not native.exact(work_ref["possibleExternal"], intent["possible_external"])
                or work_ref["externalReceiptId"] != intent["external_receipt_id"]
                or work_ref["attempts"] != intent["attempt_count"]
                or work_ref["lastCode"] != intent["last_code"]
                or work_ref["nextAttemptAt"]
                != (
                    None
                    if intent["next_attempt_at"] is None
                    else sql_instant(intent["next_attempt_at"])
                )
            ):
                raise GateError("source_identity_mismatch")
        for reply in decoded["replies"]["items"]:
            matches = [
                r for r in tables["reply_intents"] if r["outbound_id"] == reply["outboundId"]
            ]
            if (
                len(matches) != 1
                or reply["responseId"] != matches[0]["response_id"]
                or reply["receiptId"] != matches[0]["receipt_id"]
                or reply["acceptedAt"] != sql_instant(matches[0]["accepted_at"])
                or reply["bodyDigest"] != matches[0]["body_digest"]
                or reply["attemptCount"] != 0
                or reply["lastAttempt"] is not None
                or reply["callbackObservations"] != []
                or reply["callbacksTruncated"] is not False
                or {"tenantId": matches[0]["tenant_id"], "accountId": matches[0]["account_id"]}
                != decoded["case"]["scope"]
                or matches[0]["case_id"] != decoded["case"]["caseId"]
                or matches[0]["conversation_id"] != decoded["case"]["conversationId"]
            ):
                raise GateError("source_identity_mismatch")
    before = native.decode(
        media.bounded_read(work / "rehydration-p1-before.json", maximum=65536), maximum=65536
    )["context"]["case"]
    after = native.decode(
        media.bounded_read(work / "rehydration-p1-after.json", maximum=65536), maximum=65536
    )["context"]["case"]
    supplier = native.decode(media.bounded_read(supplier_proof, maximum=32768))
    actual = supplier["mutation"]
    result = actual["result"]
    if (
        before["revision"] != "0"
        or after["revision"] != "0"
        or before["sourceRevision"] == after["sourceRevision"]
        or before["supplierResult"] is not None
        or after["intent"]["state"] != "committed"
        or after["mutation"]["state"] != "succeeded"
        or after["mutation"]["outcome"] != "succeeded"
        or after["mutation"]["effectId"] != actual["effect_id"]
        or after["workflow"]["taskId"] != supplier["taskId"]
        or supplier["supplier"]["applied_calls"] != 1
    ):
        raise GateError("supplier_source_mismatch")
    observed = after["supplierResult"]
    if (
        observed is None
        or observed["supplierId"] != result["supplier_id"]
        or observed["revision"] != str(result["revision"])
        or observed["bookingReference"] != result["booking_reference"]
        or observed["newCheckIn"] != result["new_check_in"]
    ):
        raise GateError("supplier_source_mismatch")


def validate_retained_index(directory: Path, expected_sha256: str) -> dict[str, Any]:
    raw = media.bounded_read(directory / "retained-index.json", maximum=1048576)
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise GateError("invalid_evidence_index")
    index = native.decode(raw, maximum=1048576)
    if (
        set(index) != {"schemaVersion", "files"}
        or not native.exact(index["schemaVersion"], 1)
        or type(index["files"]) is not dict
        or "retained-index.json" in index["files"]
    ):
        raise GateError("invalid_evidence_index")
    physical = set()
    for path in directory.rglob("*"):
        info = path.lstat()
        if path.is_symlink() or info.st_uid != os.getuid():
            raise GateError("unsafe_evidence_path")
        if path.is_dir():
            if stat.S_IMODE(info.st_mode) != 0o700:
                raise GateError("unsafe_evidence_path")
        elif path.is_file() and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600:
            relative = str(path.relative_to(directory))
            physical.add(relative)
            if relative == "retained-index.json":
                continue
            entry = index["files"].get(relative)
            if (
                type(entry) is not dict
                or set(entry) != {"bytes", "sha256"}
                or type(entry["bytes"]) is not int
                or entry["bytes"] != info.st_size
                or entry["sha256"] != hashlib.sha256(path.read_bytes()).hexdigest()
            ):
                raise GateError("invalid_evidence_index")
        else:
            raise GateError("unsafe_evidence_path")
    if physical != set(index["files"]) | {"retained-index.json"}:
        raise GateError("invalid_evidence_index")
    return index


def validated_report(raw: bytes) -> dict[str, Any]:
    value = native.decode(raw)
    variable = {"duration_seconds", "child_commands", "retained_index_sha256"}
    expected = {
        "schema_version": 1,
        "status": "passed",
        "mode": MODE,
        "tests": 18,
        "passed": 18,
        "errors": 0,
        "failures": 0,
        "skipped": 0,
        "case_results": [{"name": n, "status": "passed", "code": "ok"} for n in CASE_NAMES],
        "cleanup_complete": True,
        "schema_version_observed": 7,
        "owned_child_terminations": 1,
        "blocking_graphs_observed": 1,
        "populated_restore_verified": True,
        "actual_p1_supplier_apply_calls": 1,
        "provider_calls": False,
        "actual_browser_qualification_claimed": False,
        "human_acknowledgement_claimed": False,
        "node_version": "24.22.2",
    }
    if (
        set(value) != set(expected) | variable
        or not native.exact({k: v for k, v in value.items() if k not in variable}, expected)
        or type(value["duration_seconds"]) not in (int, float)
        or not 0 <= value["duration_seconds"] <= 180
        or not math.isfinite(value["duration_seconds"])
        or type(value["child_commands"]) is not int
        or value["child_commands"] != 18
        or type(value["retained_index_sha256"]) is not str
        or re.fullmatch(r"[a-f0-9]{64}", value["retained_index_sha256"]) is None
    ):
        raise GateError("invalid_report")
    return value


def target_path(root: Path, requested: Path) -> Path:
    if (
        requested.is_absolute()
        or requested.parts[:3] != (".local", "validation", "p2-rehydration")
        or len(requested.parts) != 4
        or re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}\.json", requested.name) is None
    ):
        raise GateError("unsafe_report_path")
    current = root
    for part in requested.parts[:-1]:
        current /= part
        if current.is_symlink():
            raise GateError("unsafe_report_path")
        if not current.exists():
            current.mkdir(mode=0o700)
        if not current.is_dir() or current.stat().st_mode & 0o022:
            raise GateError("unsafe_report_path")
    target = current / requested.name
    if (
        target.exists()
        or target.is_symlink()
        or target.with_name(target.stem + "-artifacts").exists()
    ):
        raise GateError("evidence_exists")
    return target


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    started = time.monotonic()
    cleanup = {"cleanup_complete": False}
    target = None
    try:
        target = target_path(
            root, args.report or Path(".local/validation/p2-rehydration/" + uuid4().hex + ".json")
        )
        artifacts = target.with_name(target.stem + "-artifacts")
        artifacts.mkdir(mode=0o700)
        value = asyncio.run(run(root, artifacts, started, cleanup))
    except (native.GateError, core.GateError) as error:
        value = {
            "schema_version": 1,
            "status": "failed",
            "mode": MODE,
            "code": error.code,
            "duration_seconds": time.monotonic() - started,
            **cleanup,
        }
    except Exception:  # noqa: BLE001 - never reflect credentials or dependency exception bodies.
        value = {
            "schema_version": 1,
            "status": "failed",
            "mode": MODE,
            "code": "gate_failed",
            "duration_seconds": time.monotonic() - started,
            **cleanup,
        }
    try:
        if target is not None:
            native.write_json(target, value)
    except (OSError, GateError):
        value = {
            "schema_version": 1,
            "status": "failed",
            "mode": MODE,
            "code": "evidence_not_retained",
            **cleanup,
        }
    print(json.dumps(value, sort_keys=True))
    return 0 if value["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
