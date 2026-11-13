"""Selected original-input qualification over isolated real P1/P2 profiles.

--plan is inert. Parent tooling owns schema preparation, observed SQL barriers,
process groups and cleanup; products retain all intake/work/result authority.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import shutil
import signal
import stat
import sys
import tempfile
import time
from collections.abc import Callable, Coroutine
from contextlib import closing
from pathlib import Path
from typing import Any, Literal, TypeVar, cast
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT))
import p2_native_check as native
import p2_standalone_check as starter
import p3_case_fixture as case_fixture
import p3_coordinator_check as core
import p3_document_evidence as evidence
from p2_rehydration_p1 import P1ReadFixture
from p3_channel_origin_consumer import make_template
from p3_document_package import GroupedOwnedProcess

from continuity_lab.work_api import PostgresSettings
from delegation_reliability.contracts import Scope
from harness.process_control import ProcessTimeout

CASES = (
    "canonical_source_agreement",
    "original_work_and_p2_receipt_join",
    "equal_replay_zero_new_work",
    "changed_origin_conflict",
    "foreign_scope_route_publisher_denied",
    "mapped_width_revision_zero_denied",
    "stale_new_and_known_historical",
    "concurrent_first_winner_context",
    "owned_commit_before_ack_recovery",
    "original_deadline_evidence_after_clock_config",
    "unknown_lookup_no_resubmit",
    "held_actual_capacity_and_close_retry",
    "issued_verified_outer3_result",
    "current_result_native_read_and_stale_denial",
)
COMMANDS = (
    "compile-public",
    "compile-fixture",
    "setup",
    "origin-race-a",
    "origin-race-b",
    "race",
    "origin-ack",
    "ack-caller",
    "origin-recovered",
    "reconcile",
    "negative",
    "origin-current",
    "result-host",
    "p3-consumer",
    "native-read",
    "cleanup",
)
TOKENS = (
    "ACCOUNT_TOKEN",
    "NATIVE_PUBLISHER_TOKEN",
    "PUBLISHER_TOKEN",
    "NATIVE_A_BEARER",
    "NATIVE_B_BEARER",
    "OPERATION_TOKEN",
)
BASE = frozenset({"PATH", "LANG", "CI", "NO_COLOR", "__CF_USER_TEXT_ENCODING"})
CODES = frozenset(
    {
        "invalid_input",
        "invalid_proof",
        "missing_setup",
        "source_changed",
        "component_failed",
        "cleanup_incomplete",
        "deadline_exceeded",
        "capture_budget",
    }
)
T = TypeVar("T")


class OriginGateError(RuntimeError):
    def __init__(self, code: str = "invalid_proof") -> None:
        self.code = code if type(code) is str and code in CODES else "invalid_proof"
        super().__init__(self.code)


def require(value: object, code: str = "invalid_proof") -> None:
    if value is not True:
        raise OriginGateError(code)


def finite_code(error: BaseException | None) -> str:
    try:
        code = getattr(error, "code", "component_failed")
    except Exception:  # noqa: BLE001 - diagnostic access cannot replace the primary failure
        return "component_failed"
    return code if type(code) is str and code in CODES else "component_failed"


def plan() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "planned",
        "assertions": list(CASES),
        "commands": list(COMMANDS),
        "expected_process_groups": 16,
        "max_process_groups": 24,
        "deadline_seconds": 180,
        "cleanup_seconds": 20,
        "stream_bytes": 65536,
        "aggregate_capture_bytes": 2097152,
        "schemas": 3,
        "scheduled_owned_sigkills": 1,
        "rtc_rooms": 0,
        "provider_calls": False,
        "carrier_sends": 0,
        "supplier_mutations": 0,
        "specialist": "supplied_scripted_fixed_policy_v2",
        "uncertainty_controls": "explicit public-port simulations, not database faults",
        "installed_actual_assertions": 0,
    }


def json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        + "\n"
    ).encode()


def reject_constant(value: str) -> Any:
    raise OriginGateError("invalid_proof")


def read(path: Path, maximum: int = 262144) -> dict[str, Any]:
    info = path.lstat()
    require(
        stat.S_ISREG(info.st_mode)
        and info.st_uid == os.getuid()
        and info.st_nlink == 1
        and stat.S_IMODE(info.st_mode) == 0o600
        and 0 < info.st_size <= maximum
        and not path.is_symlink()
    )
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        opened = os.fstat(stream.fileno())
        body = stream.read(maximum + 1)
    require((opened.st_dev, opened.st_ino, opened.st_size) == (info.st_dev, info.st_ino, len(body)))
    parsed = json.loads(body, object_pairs_hook=core.unique_object, parse_constant=reject_constant)
    require(type(parsed) is dict)
    return cast(dict[str, Any], parsed)


def publish(path: Path, value: object, maximum: int = 262144) -> None:
    body = json_bytes(value)
    require(0 < len(body) <= maximum)
    evidence.private_directory(path.parent)
    temporary: Path | None = None
    identity: tuple[int, int] | None = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix="." + path.name + ".", suffix=".pending", dir=path.parent
        )
        temporary = Path(name)
        opened = os.fstat(descriptor)
        identity = opened.st_dev, opened.st_ino
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path, follow_symlinks=False)
    finally:
        if temporary is not None and identity is not None:
            info = temporary.lstat()
            require((info.st_dev, info.st_ino) == identity)
            temporary.unlink()


def base_environment() -> dict[str, str]:
    values = {name: os.environ[name] for name in BASE if name in os.environ}
    values.update(CI="1", NO_COLOR="1")
    values.setdefault("LANG", "en_US.UTF-8")
    require(bool(values.get("PATH")), "missing_setup")
    return values


def source_snapshot(root: Path) -> dict[str, str]:
    names = {
        root / name
        for name in (
            "AGENTS.md",
            "local-setup/AGENTS.md",
            "projects/channel-continuity/AGENTS.md",
            "projects/delegation-reliability/AGENTS.md",
            "docs/work-items/0044-origin-bound-channel-policy.md",
            "uv.lock",
            "pnpm-lock.yaml",
            "pyproject.toml",
            "package.json",
            "Makefile",
            "local-setup/scripts/p2_channel_origin_check.py",
            "services/channel_policy_demo/__init__.py",
            "services/channel_policy_demo/py.typed",
            "services/channel_policy_demo/wire.py",
            "services/channel_policy_demo/origin.py",
            "services/channel_policy_demo/origin_http.py",
            "services/channel_policy_demo/discovery.py",
            "local-setup/scripts/p2_channel_origin_wire.py",
            "local-setup/scripts/p3_channel_origin.py",
            "local-setup/scripts/p3_channel_origin_http.py",
            "local-setup/scripts/p3_channel_origin_host.py",
            "local-setup/scripts/p3_channel_origin_consumer.py",
            "local-setup/scripts/p3_channel_origin_evidence.py",
            "local-setup/scripts/p3_coordinator_check.py",
            "local-setup/stack.py",
            "harness/process_control.py",
            "harness/foundation.json",
            "local-setup/scripts/p2_rehydration_p1.py",
            "local-setup/scripts/p2_current_case_bridge.py",
            "local-setup/scripts/p3_case_fixture.py",
            "local-setup/scripts/p2_standalone_check.py",
            "local-setup/scripts/p2_native_check.py",
            "local-setup/scripts/p3_document_package.py",
            "local-setup/scripts/p3_document_evidence.py",
            "local-setup/scripts/p3_channel_receiver.py",
            "local-setup/scripts/p2_result_receiver_evidence.py",
            "projects/channel-continuity/package.json",
            "projects/channel-continuity/tsconfig.json",
            "projects/channel-continuity/tsconfig.examples.json",
            "projects/channel-continuity/tsconfig.starter.json",
            "projects/channel-continuity/tsconfig.pg.json",
            "projects/channel-continuity/tsconfig.test.json",
            "projects/channel-continuity/tests/pg_channel_origin_cases.ts",
            "projects/channel-continuity/tests/fixture-work.ts",
            "contracts/delegation/fixed-policy-v2.json",
            "contracts/delegation/channel-policy-v3.json",
        )
    }
    for folder, extensions in (
        ("projects/agent-continuity/python/src", ("*.py", "*.typed")),
        ("projects/delegation-reliability/python/src", ("*.py", "*.typed")),
        ("projects/channel-continuity/src", ("*.ts",)),
        ("projects/channel-continuity/examples", ("*.ts",)),
    ):
        for extension in extensions:
            names.update((root / folder).rglob(extension))
    result = {}
    for path in sorted(names):
        require(path.is_file() and not path.is_symlink(), "missing_setup")
        result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


class Children:
    def __init__(self, directory: Path, deadline: float, final: float) -> None:
        self.directory, self.deadline, self.final = directory, deadline, final
        self.children: dict[str, GroupedOwnedProcess] = {}
        self.sizes: dict[str, int] = {}

    def start(
        self, role: str, argv: list[str], env: dict[str, str], cwd: Path
    ) -> GroupedOwnedProcess:
        require(role in COMMANDS and role not in self.children and len(self.children) < 24)
        require(
            time.monotonic() < (self.final if role == "cleanup" else self.deadline),
            "deadline_exceeded",
        )
        child = GroupedOwnedProcess(
            argv,
            cwd=cwd,
            env=env,
            output_directory=self.directory / ("capture-" + role),
            max_output_bytes=65536,
            final_deadline=self.final,
        )
        self.children[role] = child
        return child

    def account(self, role: str) -> tuple[bytes, bytes]:
        child = self.children[role]
        out, err = core.CaptureBudget.read(child.output_directory, 65536)
        self.sizes[role] = len(out) + len(err)
        require(sum(self.sizes.values()) <= 2097152, "capture_budget")
        return out, err

    def finish(
        self, role: str, accepted: tuple[int, ...] = (0,), *, cleanup: bool = False
    ) -> bytes:
        child = self.children[role]
        remaining = (self.final if cleanup else self.deadline) - time.monotonic()
        require(remaining > 0, "deadline_exceeded")
        result = child.wait(timeout=remaining)
        child.close()
        out, _ = self.account(role)
        require(child.group_settled and not child.cleanup_failed, "cleanup_incomplete")
        require(result.returncode in accepted, "component_failed")
        return out

    def wait_json(self, role: str, path: Path, timeout: float = 10) -> dict[str, Any]:
        child = self.children[role]
        until = min(self.deadline, time.monotonic() + timeout)
        while time.monotonic() < until:
            if path.exists() and path.lstat().st_nlink == 1:
                value = read(path)
                require(child.returncode is None, "component_failed")
                return value
            if child.returncode is not None:
                self.finish(role)
                raise OriginGateError("component_failed")
            try:
                child.wait(timeout=min(0.01, max(0.001, until - time.monotonic())))
            except ProcessTimeout:
                pass
        raise OriginGateError("deadline_exceeded")

    def kill_ack(self) -> dict[str, object]:
        child = self.children["origin-ack"]
        result = child.kill(timeout=min(3, self.deadline - time.monotonic()))
        child.close()
        self.account("origin-ack")
        require(
            result.returncode == -signal.SIGKILL
            and result.killed
            and child.group_settled
            and not child.cleanup_failed
        )
        return {
            "schema_version": 1,
            "role": "origin-ack",
            "pid": child.pid,
            "returncode": result.returncode,
            "group_settled": True,
        }

    def settled(self) -> bool:
        return all(
            type(child.returncode) is int and child.group_settled and not child.cleanup_failed
            for child in self.children.values()
        )

    def close(self) -> None:
        incomplete = False
        for role, child in reversed(tuple(self.children.items())):
            try:
                if child.returncode is None:
                    child.kill(timeout=max(0.001, min(3, self.final - time.monotonic())))
                child.close()
                self.account(role)
                incomplete |= not child.group_settled or child.cleanup_failed
            except Exception:  # noqa: BLE001 - every independent owner must be attempted
                incomplete = True
        require(not incomplete and self.settled(), "cleanup_incomplete")

    def observation(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "groups": [
                {
                    "role": role,
                    "pid": child.pid,
                    "returncode": child.returncode,
                    "group_settled": child.group_settled,
                    "cleanup_failed": child.cleanup_failed,
                }
                for role, child in self.children.items()
            ],
            "capture_bytes": sum(self.sizes.values()),
        }


class SqlHolder:
    """One parent-owned lock, distinct from every runtime connection/task."""

    def __init__(self, settings: PostgresSettings, table: str, row: bool) -> None:
        require(table in {"admission", "accepted_work"})
        self.settings, self.table, self.row = settings, table, row
        self.connection: Any = None
        self.transaction: Any = None
        self.pid: int | None = None

    def acquire(self) -> None:
        from psycopg import sql

        self.connection = self.settings.connect(application_name="continuity-test")
        try:
            self.transaction = self.connection.transaction()
            self.transaction.__enter__()
            if self.row:
                self.connection.execute(
                    sql.SQL("SELECT * FROM {} WHERE singleton FOR UPDATE").format(
                        sql.Identifier(self.settings.schema, self.table)
                    )
                )
            else:
                self.connection.execute(
                    sql.SQL("LOCK TABLE {} IN ACCESS EXCLUSIVE MODE").format(
                        sql.Identifier(self.settings.schema, self.table)
                    )
                )
            self.pid = self.connection.info.backend_pid
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        if self.connection is not None:
            try:
                if self.transaction is not None:
                    self.transaction.__exit__(None, None, None)
                    self.transaction = None
            finally:
                self.connection.close()
                self.connection = None


def sql_waiters(owner: PostgresSettings, holder: SqlHolder, expected: int) -> dict[str, Any]:
    require(type(holder.pid) is int and holder.pid is not None)
    assert holder.pid is not None
    with closing(owner.connect(application_name="continuity-test")) as connection:
        rows = connection.execute(
            "SELECT pid,pg_blocking_pids(pid) AS blockers,query,wait_event_type "
            "FROM pg_stat_activity WHERE datname=current_database() AND usename=current_user "
            "AND pid<>%s AND wait_event_type='Lock' "
            "AND EXISTS(SELECT 1 FROM pg_locks l JOIN pg_class c ON c.oid=l.relation "
            "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE l.pid=pg_stat_activity.pid "
            "AND n.nspname=%s AND c.relname=%s) ORDER BY pid LIMIT 5",
            [holder.pid, owner.schema, holder.table],
        ).fetchall()
        locks = connection.execute(
            "SELECT l.pid,l.relation::bigint AS relation_oid,n.nspname AS schema_name,"
            "c.relname AS table_name,l.locktype,l.mode,l.granted FROM pg_locks l "
            "JOIN pg_class c ON c.oid=l.relation JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE l.pid=ANY(%s) AND n.nspname=%s AND c.relname=%s AND l.locktype='relation' "
            "ORDER BY l.pid,l.mode,l.granted",
            [[holder.pid, *(row["pid"] for row in rows)], owner.schema, holder.table],
        ).fetchall()
    with closing(holder.settings.connect(application_name="continuity-test")) as connection:
        holder_rows = connection.execute(
            "SELECT pid,query,state,application_name FROM pg_stat_activity WHERE pid=%s",
            [holder.pid],
        ).fetchall()
    require(len(holder_rows) == 1 and holder_rows[0]["state"] == "idle in transaction")
    holder_query = holder_rows[0]["query"]
    require(type(holder_query) is str and len(holder_query.encode()) <= 16384)
    require(all(type(row["query"]) is str and len(row["query"].encode()) <= 16384 for row in rows))

    def relation_locks(pid: int) -> list[dict[str, Any]]:
        return [
            {
                "relation_oid": lock["relation_oid"],
                "schema": lock["schema_name"],
                "table": lock["table_name"],
                "locktype": lock["locktype"],
                "mode": lock["mode"],
                "granted": lock["granted"],
            }
            for lock in locks
            if lock["pid"] == pid
        ]

    return {
        "schema": owner.schema,
        "table": holder.table,
        "holder_locks": relation_locks(holder.pid),
        "row_lock": holder.row,
        "holder_query": holder_query,
        "holder_query_sha256": hashlib.sha256(holder_query.encode()).hexdigest(),
        "association": "unique_disposable_work_schema",
        "holder_pid": holder.pid,
        "expected_waiters": expected,
        "waiters": [
            {
                "pid": row["pid"],
                "relation_locks": relation_locks(row["pid"]),
                "blockers": row["blockers"],
                "wait_event_type": row["wait_event_type"],
                "query": row["query"],
                "query_sha256": hashlib.sha256(row["query"].encode()).hexdigest(),
            }
            for row in rows
        ],
    }


async def wait_sql(
    owner: PostgresSettings, holder: SqlHolder, expected: int, deadline: float, capture: Path
) -> dict[str, Any]:
    until = min(deadline, time.monotonic() + 0.8)
    last: dict[str, Any] | None = None
    while time.monotonic() < until:
        last = await asyncio.to_thread(sql_waiters, owner, holder, expected)
        if len(last["waiters"]) >= expected:
            publish(capture, last)
            require(len(last["waiters"]) == expected)
            require(all(row["wait_event_type"] == "Lock" for row in last["waiters"]))
            return last
        await asyncio.sleep(0.005)
    if last is not None:
        publish(capture, last)
    raise OriginGateError("invalid_proof")


def snapshot(owner: PostgresSettings, schemas: tuple[str, ...]) -> dict[str, Any]:
    from psycopg import sql

    result: dict[str, Any] = {}
    with (
        closing(owner.connect(application_name="continuity-test")) as connection,
        connection.transaction(),
    ):
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        for schema in schemas:
            require(schema.startswith(("p2_origin_", "p1_work_origin_", "p3_completion_")))
            tables = connection.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname=%s ORDER BY tablename",
                [schema],
            ).fetchall()
            require(0 < len(tables) <= 64)
            result[schema] = {}
            for item in tables:
                rows = connection.execute(
                    sql.SQL("SELECT to_jsonb(t) AS row FROM {} t LIMIT 65").format(
                        sql.Identifier(schema, item["tablename"])
                    )
                )
                values = [row["row"] for row in rows.fetchall()]
                require(len(values) <= 64)
                result[schema][item["tablename"]] = values
    return result


def database_now(owner: PostgresSettings) -> int:
    with closing(owner.connect(application_name="continuity-test")) as connection:
        row = connection.execute(
            "SELECT floor(extract(epoch FROM clock_timestamp())*1000)::bigint AS now"
        ).fetchone()
    require(row is not None and type(row["now"]) is int)
    assert row is not None
    return cast(int, row["now"])


def work_rows(owner: PostgresSettings) -> list[dict[str, Any]]:
    from psycopg import sql

    with closing(owner.connect(application_name="continuity-test")) as connection:
        rows = connection.execute(
            sql.SQL("SELECT to_jsonb(w) AS row FROM {} w ORDER BY work_id").format(
                sql.Identifier(owner.schema, "accepted_work")
            )
        ).fetchall()
    require(len(rows) <= 4)
    return [row["row"] for row in rows]


async def m1_observation(values: dict[str, str]) -> dict[str, object]:
    import aiohttp

    async with (
        aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3), trust_env=False) as client,
        client.get(
            "http://127.0.0.1:" + values["API_PORT"] + "/api/investigations?limit=100",
            headers={"Authorization": "Bearer " + values["LOCAL_ACCESS_TOKEN"]},
        ) as response,
    ):
        require(response.status == 200, "missing_setup")
        body = await response.content.read(262145)
    require(len(body) <= 262144)
    parsed = json.loads(body, object_pairs_hook=core.unique_object, parse_constant=reject_constant)
    matches = [
        row for row in parsed["items"] if row.get("idempotency_key") == "local-foundation-smoke-v1"
    ]
    require(parsed["scope_id"] == "local-lab" and len(matches) == 1)
    row = matches[0]
    require(
        row["scope_id"] == "local-lab"
        and row["status"] == "queued"
        and row["request"]["confirmed"] is True
    )
    return {
        "scope_id": "local-lab",
        "task_id": row["task_id"],
        "sha256": hashlib.sha256(
            json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        ).hexdigest(),
    }


async def raw_request(
    endpoint: dict[str, Any], token: str, route: str, value: object
) -> dict[str, Any]:
    require(endpoint["host"] == "127.0.0.1" and type(endpoint["port"]) is int)
    body = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    require(0 < len(body) <= 32768)
    reader, writer = await asyncio.open_connection("127.0.0.1", endpoint["port"])
    try:
        writer.write(
            (
                "POST /v1/investigations/"
                + route
                + " HTTP/1.1\r\n"
                + f"Host: 127.0.0.1:{endpoint['port']}\r\nAuthorization: Bearer {token}\r\n"
                + "Content-Type: application/json\r\nConnection: close\r\n"
                + f"Content-Length: {len(body)}\r\n\r\n"
            ).encode("ascii")
            + body
        )
        await writer.drain()
        async with asyncio.timeout(2):
            head = await reader.readuntil(b"\r\n\r\n")
            require(len(head) <= 4096)
            lines = head[:-4].split(b"\r\n")
            headers = {
                key.lower(): value.strip()
                for key, value in (line.split(b":", 1) for line in lines[1:])
            }
            length = int(headers[b"content-length"])
            require(0 < length <= 4096)
            response = await reader.readexactly(length)
        return {"http_status": int(lines[0].split(b" ")[1]), "body": json.loads(response)}
    finally:
        writer.close()
        await writer.wait_closed()


def changed_frame(prepared: dict[str, Any], **changes: object) -> dict[str, object]:
    # Preserve the actual P2 canonical order while changing only selected fields.
    submission = json.loads(prepared["canonicalPayload"])
    submission.update(changes)
    raw = json.dumps(submission, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return {
        "schemaVersion": 1,
        "canonicalPayload": raw,
        "payloadDigest": hashlib.sha256(raw.encode()).hexdigest(),
    }


async def raw_negatives(
    endpoint: dict[str, Any], token: str, prepared: dict[str, Any]
) -> dict[str, Any]:
    payload = json.loads(prepared["canonicalPayload"])
    variants: list[tuple[str, dict[str, object], int, str]] = [
        (
            "foreign_scope",
            {"scope": {"tenantId": "foreign", "accountId": "foreign"}},
            403,
            "unauthorized",
        ),
        ("foreign_case", {"caseId": "foreign_case"}, 403, "unauthorized"),
        ("foreign_conversation", {"conversationId": "foreign_conversation"}, 403, "unauthorized"),
        ("width65", {"caseId": "c" * 65}, 400, "invalid_input"),
        ("revision_zero", {"caseRevision": "0"}, 400, "invalid_input"),
        ("revision_width", {"caseRevision": "1000001"}, 400, "invalid_input"),
    ]
    results = {}
    for name, changes, status, code in variants:
        observed = await raw_request(endpoint, token, "accept", changed_frame(prepared, **changes))
        require(
            observed
            == {
                "http_status": status,
                "body": {"schemaVersion": 1, "status": "error", "code": code},
            }
        )
        results[name] = observed
    require(payload["scope"] != {"tenantId": "foreign", "accountId": "foreign"})
    return results


def node_argv(node: str, script: Path, *arguments: str) -> list[str]:
    code = (
        "if(process.version!=='v24.22.2')process.exit(2);"
        "import(require('node:url').pathToFileURL(process.argv[1]).href).catch(()=>process.exitCode=1)"
    )
    return [node, "--eval", code, str(script), *arguments]


def private_report(root: Path, requested: Path | None) -> Path:
    base = root / ".local/validation/p2-channel-origin"
    evidence.private_directory(base)
    result = requested or base / (str(time.time_ns()) + ".json")
    if not result.is_absolute():
        result = root / result
    require(
        result.parent == base and not result.exists() and not result.is_symlink(), "invalid_input"
    )
    require(not result.with_name(result.stem + "-artifacts").exists(), "invalid_input")
    return result


async def run(root: Path, target: Path) -> dict[str, Any]:
    """One bounded actual schedule; no success is derived from stage names alone."""
    # Imported only on an explicitly requested actual run, never --plan/import.
    from datetime import date

    from p3_channel_origin_evidence import validate_bundle
    from psycopg import sql

    from continuity_lab.case_control_api import BookingChange
    from continuity_lab.execution_api import ExecutionLimits
    from continuity_lab.work_admin import (
        install_work_schema,
        upgrade_work_schema_v2,
        upgrade_work_schema_v3,
        upgrade_work_schema_v4,
    )
    from continuity_lab.work_api import WorkLimits

    started = time.monotonic()
    deadline, final = started + 160, started + 180
    require(sys.version_info[:3] == (3, 14, 10) and not sys.flags.optimize, "missing_setup")
    require(not any(os.environ.get(key) for key in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE")))
    values = cast(dict[str, str], core.load_setup(root).load_settings())
    node = shutil.which("node")
    require(node is not None, "missing_setup")
    assert node is not None
    node = str(Path(node).absolute())
    project = root / "projects/channel-continuity"
    compiler = project / "node_modules/typescript/bin/tsc"
    require(compiler.is_file(), "missing_setup")
    scratch = project / ".local/channel-origin"
    evidence.private_directory(scratch)
    work = Path(tempfile.mkdtemp(prefix="run-", dir=scratch)).resolve()
    os.chmod(work, 0o700)
    artifacts = target.with_name(target.stem + "-artifacts")
    artifacts.mkdir(mode=0o700)
    children = Children(work, deadline, final)
    run_id = uuid4().hex
    p2_schema, work_schema = "p2_origin_" + run_id, "p1_work_origin_" + run_id
    scope = {"tenantId": "origin_tenant", "accountId": "origin_account"}
    ref: dict[str, Any] = {
        "scope": scope,
        "caseId": "origin_case",
        "conversationId": "origin_conversation",
    }
    p1 = P1ReadFixture(values, work, ref)
    owner = PostgresSettings(
        port=int(values["POSTGRES_PORT"]),
        user="continuity_migrator",
        password=values["POSTGRES_MIGRATION_PASSWORD"],
        schema=work_schema,
    )
    observer = PostgresSettings(
        port=int(values["POSTGRES_PORT"]),
        password=values["POSTGRES_PASSWORD"],
        schema=work_schema,
    )
    schemas = p2_schema, work_schema, p1.owner.schema
    tokens = {name: secrets.token_urlsafe(32) for name in (*TOKENS, "WORK_TOKEN", "CASE_TOKEN")}
    state: dict[str, Any] = {
        "stage": "configuration",
        "work_schema_started": False,
        "p2_setup_started": False,
    }
    owned: set[asyncio.Task[Any]] = set()
    holders: list[SqlHolder] = []
    snapshots: dict[str, Any] = {}
    observations: dict[str, Any] = {}
    fixture: dict[str, Any] = {}
    primary: BaseException | None = None
    failure_stage: str | None = None
    cleanup_errors: list[str] = []

    async def bounded(label: str, action: Coroutine[Any, Any, T], *, cleaning: bool = False) -> T:
        if (final if cleaning else deadline) <= time.monotonic():
            action.close()
            raise OriginGateError("deadline_exceeded")
        try:
            task = asyncio.create_task(action, name="origin-parent-" + label)
        except BaseException:
            action.close()
            raise
        owned.add(task)
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        async with asyncio.timeout_at(final if cleaning else deadline):
            return await asyncio.shield(task)

    async def offload(label: str, action: Callable[[], T], *, cleaning: bool = False) -> T:
        return await bounded(label, asyncio.to_thread(action), cleaning=cleaning)

    def p2_environment(mode: str) -> dict[str, str]:
        result = {
            **base_environment(),
            "P2_ORIGIN_DIRECTORY": str(work),
            "P2_ORIGIN_SCHEMA": p2_schema,
            "P2_ORIGIN_PG_PORT": values["POSTGRES_PORT"],
            "P2_ORIGIN_CASE_AUTHORIZATION": "Bearer " + p1.token,
            **{"P2_ORIGIN_" + name: tokens[name] for name in TOKENS},
        }
        if mode in {"setup", "cleanup"}:
            result["P2_ORIGIN_OWNER_PASSWORD"] = values["POSTGRES_MIGRATION_PASSWORD"]
        if mode != "cleanup":
            result["P2_ORIGIN_RUNTIME_PASSWORD"] = values["POSTGRES_PASSWORD"]
        return result

    def python_environment(consumer: bool = False) -> dict[str, str]:
        result = {
            **base_environment(),
            "P3_ORIGIN_DIRECTORY": str(work),
            "P3_ORIGIN_PG_PORT": values["POSTGRES_PORT"],
            "P3_ORIGIN_RUNTIME_PASSWORD": values["POSTGRES_PASSWORD"],
            "P3_ORIGIN_WORK_TOKEN": tokens["WORK_TOKEN"],
            "P3_ORIGIN_CASE_TOKEN": tokens["CASE_TOKEN"],
        }
        key = "PUBLISHER_TOKEN" if consumer else "OPERATION_TOKEN"
        result["P3_ORIGIN_" + key] = tokens[key]
        return result

    async def node_start(role: str) -> None:
        state["stage"] = role
        script = work / "compiled/tests/pg_channel_origin_cases.js"
        children.start(role, node_argv(node, script, role), p2_environment(role), work)

    async def node_call(role: str, *, cleaning: bool = False) -> None:
        await node_start(role)
        await offload(
            "finish-" + role, lambda: children.finish(role, cleanup=cleaning), cleaning=cleaning
        )

    async def host(
        role: str, label: Literal["a", "b"], sender: str, operation: str | None, window: int = 60000
    ) -> dict[str, Any]:
        state["stage"] = role
        template, _ = make_template(
            label,
            Scope(scope["tenantId"], scope["accountId"]),
            ref["caseId"],
            ref["conversationId"],
        )
        config = {
            "schema_version": 1,
            "profile_id": fixture["receiver_id"],
            "scope": {"tenant_id": scope["tenantId"], "account_id": scope["accountId"]},
            "case_id": ref["caseId"],
            "conversation_id": ref["conversationId"],
            "sender_id": sender,
            "task_id": p1.task_id,
            "authority_case_id": p1.case_id,
            "case_schema": p1.owner.schema,
            "work_schema": work_schema,
            "supplier_path": str(p1.supplier),
            "template": template.to_wire(),
            "deadline_window_ms": window,
            "operation_key": operation,
            "parent_deadline_monotonic": final,
        }
        publish(work / (role + "-config.json"), config)
        children.start(
            role,
            [
                sys.executable,
                "-I",
                "-B",
                str(root / "local-setup/scripts/p3_channel_origin_host.py"),
                role,
            ],
            python_environment(),
            root,
        )
        ready = await offload(
            "ready-" + role, lambda: children.wait_json(role, work / (role + "-ready.json"))
        )
        require(
            ready
            == {
                "schema_version": 1,
                "pid": children.children[role].pid,
                "host": "127.0.0.1",
                "port": ready.get("port"),
            }
            and type(ready["port"]) is int
            and 1 <= ready["port"] <= 65535
        )
        return ready

    async def stop_host(role: str) -> None:
        if role in children.children and children.children[role].returncode is None:
            path = work / (role + "-stop.json")
            if not path.exists():
                publish(path, {"schema_version": 1, "stop": True})
            await offload("stop-" + role, lambda: children.finish(role))

    async def take_snapshot(label: str) -> None:
        captured = await offload("snapshot-" + label, lambda: snapshot(owner, schemas))
        snapshots[label] = captured
        publish(artifacts / ("snapshot-" + label + ".json"), captured)

    def work_install() -> None:
        install_work_schema(owner, WorkLimits(16, 16))
        upgrade_work_schema_v2(owner, ExecutionLimits(4, 2, 10000))
        upgrade_work_schema_v3(owner)
        upgrade_work_schema_v4(owner)

    def namespace_guard(schema: str, markers: set[str]) -> bool:
        with closing(owner.connect(application_name="continuity-test")) as connection:
            rows = connection.execute(
                "SELECT pg_get_userbyid(nspowner) AS owner,obj_description(oid,'pg_namespace') AS marker "
                "FROM pg_namespace WHERE nspname=%s",
                [schema],
            ).fetchall()
        if not rows:
            return False
        require(
            rows == [{"owner": "continuity_migrator", "marker": rows[0]["marker"]}]
            and rows[0]["marker"] in markers
        )
        return True

    def quiet() -> None:
        with closing(owner.connect(application_name="continuity-test")) as connection:
            for schema in schemas:
                count = connection.execute(
                    "SELECT count(*) AS n FROM pg_locks l "
                    "JOIN pg_class c ON c.oid=l.relation "
                    "JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE l.pid<>pg_backend_pid() AND n.nspname=%s",
                    [schema],
                ).fetchone()
                require(count is not None and count["n"] == 0, "cleanup_incomplete")

    def drop_work() -> None:
        markers = {"continuity-readonly-work-v" + str(n) for n in range(1, 5)}
        if namespace_guard(work_schema, markers):
            with closing(owner.connect(application_name="continuity-test")) as connection:
                connection.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(work_schema))
                )

    try:
        for schema in schemas:
            with closing(owner.connect(application_name="continuity-test")) as connection:
                require(
                    connection.execute(
                        "SELECT 1 FROM pg_namespace WHERE nspname=%s", [schema]
                    ).fetchone()
                    is None
                )
        before = source_snapshot(root)
        publish(artifacts / "source-before.json", before)
        publish(artifacts / "plan.json", plan())
        publish(
            work / "origin-owned-work.json",
            {"schema_version": 1, "run_id": run_id, "schemas": list(schemas)},
        )
        observations["m1_before"] = await m1_observation(values)
        configs = starter.build_configurations(root, work)
        publish(artifacts / "compiler-configurations.json", {p.name: read(p) for p in configs})
        state["stage"] = "compile-public"
        children.start(
            "compile-public",
            node_argv(node, compiler, "--build", "--force", *(str(p) for p in configs)),
            base_environment(),
            project,
        )
        await offload("compile-public", lambda: children.finish("compile-public"))
        fixture_config = work / "fixture-tsconfig.json"
        base = read_json_source(project / "tsconfig.pg.json")
        include = [str((project / name).absolute()) for name in base["include"]]
        include.append(str(project / "tests/pg_channel_origin_cases.ts"))
        publish(
            fixture_config,
            {
                "extends": str(project / "tsconfig.pg.json"),
                "compilerOptions": {
                    "outDir": str(work / "compiled"),
                    "tsBuildInfoFile": str(work / "fixture.tsbuildinfo"),
                    "typeRoots": [str(project / "node_modules/@types")],
                },
                "include": include,
            },
        )
        state["stage"] = "compile-fixture"
        children.start(
            "compile-fixture",
            node_argv(node, compiler, "--project", str(fixture_config)),
            base_environment(),
            project,
        )
        await offload("compile-fixture", lambda: children.finish("compile-fixture"))
        publish(
            artifacts / "runtime-build-parity.json",
            native.verify_runtime_build(project, work / "compiled"),
        )
        compiled_fixture = work / "compiled/tests/pg_channel_origin_cases.js"
        require(compiled_fixture.is_file() and not compiled_fixture.is_symlink())
        evidence.write_private(artifacts / "compiled-fixture.js", compiled_fixture.read_bytes())
        state["stage"] = "p1-owner-preparation"
        case_port = await p1.bounded(p1.start(), deadline)
        assert p1.control is not None
        revised = await p1.bounded(
            p1.control.revise(
                task_id=p1.task_id,
                expected_revision=0,
                request=BookingChange("DEMO-BK-001", date(2030, 12, 11), True),
            ),
            deadline,
        )
        require(revised.revision == 1)
        # The public synthetic supplier is newly created in this owned run. Keep
        # its application reader input private without changing the parent's umask.
        with os.fdopen(os.open(p1.supplier, os.O_RDONLY | os.O_NOFOLLOW), "rb") as supplier_file:
            supplier_info = os.fstat(supplier_file.fileno())
            require(
                stat.S_ISREG(supplier_info.st_mode)
                and supplier_info.st_uid == os.getuid()
                and supplier_info.st_nlink == 1
                and p1.supplier.parent == work
            )
            os.fchmod(supplier_file.fileno(), 0o600)
        state["work_schema_started"] = True
        await offload("work-install", work_install)
        fixture = {
            "schema_version": 1,
            "scope": scope,
            "case_id": ref["caseId"],
            "conversation_id": ref["conversationId"],
            "recipient_id": "origin_recipient",
            "p2_schema": p2_schema,
            "case_endpoint": {"host": "127.0.0.1", "port": case_port},
            "native_binding_ids": {"a": str(uuid4()), "b": str(uuid4())},
            "parent_expires_at_ms": time.time_ns() // 1000000
            + int((final - time.monotonic()) * 1000),
        }
        publish(work / "fixture.json", fixture)
        state["p2_setup_started"] = True
        await node_call("setup")
        setup = read(work / "p2-origin-setup.json")
        fixture["receiver_id"] = setup["receiver_id"]
        fixture["inputs"] = setup["inputs"]
        original_op = setup["inputs"]["original"]["operationKey"]
        ack_op = setup["inputs"]["ack"]["operationKey"]
        race_a = await host("origin-race-a", "a", fixture["native_binding_ids"]["a"], original_op)
        await host("origin-race-b", "b", fixture["native_binding_ids"]["a"], original_op)
        await node_start("race")
        for role in ("origin-race-a", "origin-race-b"):

            def observe_miss(selected: str = role) -> dict[str, Any]:
                return children.wait_json(selected, work / (selected + "-read-miss.json"))

            observations[role + "_miss"] = await offload(role + "-miss", observe_miss)
        race_lock = SqlHolder(owner, "admission", True)
        holders.append(race_lock)
        await offload("race-lock", race_lock.acquire)
        publish(work / "race-release.json", {"schema_version": 1, "release": True})
        observations["race_wait_graph"] = await wait_sql(
            observer, race_lock, 2, deadline, artifacts / "race-wait-graph.json"
        )
        await offload("race-release", race_lock.close)
        await offload("race-finish", lambda: children.finish("race"))
        await take_snapshot("after_race")
        original_receipt = read(work / "origin-race.json")["receipt"]
        original_work = original_receipt["receiptId"]
        ack_host = await host("origin-ack", "a", "origin_sms_sender", ack_op, 1500)
        require(ack_host["port"] != race_a["port"])
        await node_start("ack-caller")
        committed = await offload(
            "ack-commit",
            lambda: children.wait_json("origin-ack", work / "origin-ack-committed.json"),
        )
        require(committed["pid"] == children.children["origin-ack"].pid)
        rows = await offload("ack-owner-read", lambda: work_rows(owner))
        matching = [row for row in rows if row["work_id"] == committed["work_id"]]
        require(
            len(rows) == 2
            and len(matching) == 1
            and matching[0]["sha256"] == committed["payload_sha256"]
        )
        observations["ack_committed"] = committed
        await take_snapshot("after_ack_commit")
        observations["scheduled_kill"] = await offload("kill-ack", children.kill_ack)
        await offload("ack-caller-finish", lambda: children.finish("ack-caller"))
        winner_body = bytes.fromhex(
            next(row for row in rows if row["work_id"] == original_work)["body"][2:]
        )
        winning = json.loads(winner_body)["request"]["evidence"][0]["version"]
        opposite: Literal["a", "b"] = "b" if winning == "distinct_a" else "a"
        recovered = await host(
            "origin-recovered", opposite, fixture["native_binding_ids"]["a"], None, 30000
        )
        await node_call("reconcile")
        ack_deadline = matching[0]["deadline_at_ms"]
        while True:
            now = await offload("ack-clock", lambda: database_now(owner))
            if now > ack_deadline:
                break
            require(time.monotonic() < deadline, "deadline_exceeded")
            await asyncio.sleep(min(0.02, (ack_deadline - now + 1) / 1000))
        prepared_ack = read(work / "origin-ack-prepared.json")
        expired_lookup = await raw_request(
            recovered,
            tokens["OPERATION_TOKEN"],
            "lookup",
            {
                "operationKey": ack_op,
                "scope": scope,
                "payloadDigest": prepared_ack["payloadDigest"],
            },
        )
        require(
            expired_lookup
            == {
                "http_status": 200,
                "body": {
                    "schemaVersion": 1,
                    "status": "known",
                    "observation": {
                        "status": "accepted",
                        "receipt": read(work / "origin-reconcile.json")["receipt"],
                    },
                },
            }
        )
        observations["clock_after_ack_deadline"] = {
            "schema_version": 1,
            "db_now_ms": now,
            "ack_deadline_at_ms": ack_deadline,
            "lookup": expired_lookup,
        }
        await take_snapshot("after_ack_reconcile")
        state["stage"] = "raw-negative"
        prepared_a = read(work / "origin-original-prepared.json")
        observations["raw_negative"] = await raw_negatives(
            recovered, tokens["OPERATION_TOKEN"], prepared_a
        )
        await node_start("negative")
        await offload(
            "negative-controls",
            lambda: children.wait_json("negative", work / "origin-negative-controls.json"),
        )
        held = SqlHolder(owner, "accepted_work", False)
        holders.append(held)
        await offload("held-lock", held.acquire)
        publish(work / "origin-hold-ready.json", {"schema_version": 1, "hold": True})
        await offload(
            "held-callers",
            lambda: children.wait_json("negative", work / "origin-hold-callers-started.json"),
        )
        observations["held_wait_graph"] = await wait_sql(
            observer, held, 4, deadline, artifacts / "held-wait-graph.json"
        )
        publish(work / "origin-abort-lookups.json", {"schema_version": 1, "abort": True})
        publish(work / "origin-recovered-stop.json", {"schema_version": 1, "stop": True})
        observations["close_incomplete"] = await offload(
            "incomplete-close",
            lambda: children.wait_json(
                "origin-recovered", work / "origin-recovered-cleanup-incomplete.json", 0.5
            ),
        )
        observations["held_wait_graph_at_close"] = await wait_sql(
            observer, held, 4, deadline, artifacts / "held-close-wait-graph.json"
        )
        await offload("held-release", held.close)
        await offload("negative-finish", lambda: children.finish("negative"))
        await offload("recovered-finish", lambda: children.finish("origin-recovered"))
        await take_snapshot("after_negative")
        current = await host("origin-current", "b", fixture["native_binding_ids"]["b"], None)
        await node_start("result-host")
        result_endpoint = await offload(
            "result-ready",
            lambda: children.wait_json("result-host", work / "origin-result-ready.json"),
        )
        ack_work = read(work / "origin-reconcile.json")["receipt"]["receiptId"]
        config = {
            "schema_version": 1,
            "scope": {"tenant_id": scope["tenantId"], "account_id": scope["accountId"]},
            "case_id": ref["caseId"],
            "conversation_id": ref["conversationId"],
            "recipient_id": fixture["recipient_id"],
            "profile_id": fixture["receiver_id"],
            "case_schema": p1.owner.schema,
            "work_schema": work_schema,
            "task_id": p1.task_id,
            "authority_case_id": p1.case_id,
            "supplier_path": str(p1.supplier),
            "receiver_endpoint": {"host": "127.0.0.1", "port": result_endpoint["port"]},
            "original_work_id": original_work,
            "ack_work_id": ack_work,
            "owners": {"original": str(uuid4()), "current": str(uuid4())},
            "parent_deadline_monotonic": final,
        }
        publish(work / "origin-consumer-config.json", config)
        state["stage"] = "p3-consumer"
        children.start(
            "p3-consumer",
            [
                sys.executable,
                "-I",
                "-B",
                str(root / "local-setup/scripts/p3_channel_origin_consumer.py"),
            ],
            python_environment(True),
            root,
        )
        await offload(
            "case-advanced",
            lambda: children.wait_json("p3-consumer", work / "origin-case-advanced.json"),
        )
        stale = changed_frame(
            prepared_a,
            operationKey=str(uuid4()),
            caseRevision="1",
            message={
                **json.loads(prepared_a["canonicalPayload"])["message"],
                "receiptId": str(uuid4()),
                "senderId": fixture["native_binding_ids"]["b"],
            },
        )
        observations["stale_new"] = await raw_request(
            current, tokens["OPERATION_TOKEN"], "accept", stale
        )
        require(
            observations["stale_new"]
            == {
                "http_status": 503,
                "body": {"schemaVersion": 1, "status": "error", "code": "case_changed"},
            }
        )
        replay = {
            "schemaVersion": 1,
            "canonicalPayload": prepared_a["canonicalPayload"],
            "payloadDigest": prepared_a["payloadDigest"],
        }
        observations["known_historical"] = await raw_request(
            race_a, tokens["OPERATION_TOKEN"], "accept", replay
        )
        require(
            observations["known_historical"]
            == {
                "http_status": 200,
                "body": {"schemaVersion": 1, "status": "known", "receipt": original_receipt},
            }
        )
        await take_snapshot("after_case_change_before_current")
        await node_start("native-read")
        await offload("consumer-finish", lambda: children.finish("p3-consumer"))
        await offload("native-read-finish", lambda: children.finish("native-read"))
        publish(work / "origin-result-stop.json", {"schema_version": 1, "stop": True})
        await offload("result-host-finish", lambda: children.finish("result-host"))
        for role in ("origin-current", "origin-race-a", "origin-race-b"):
            await stop_host(role)
        await take_snapshot("final")
        observations["supplier"] = await offload(
            "supplier-truth", lambda: case_fixture.supplier_truth(p1.supplier)
        )
        observations["m1_after"] = await m1_observation(values)
        require(observations["m1_after"] == observations["m1_before"])
        proof_files = {
            path.name: read(path)
            for path in work.glob("*.json")
            if not path.name.endswith("-config.json")
            and path.name not in {"fixture.json", "fixture-tsconfig.json"}
            and not path.name.startswith("build-")
        }
        descriptor = {
            **fixture,
            "case_schema": p1.owner.schema,
            "work_schema": work_schema,
            "task_id": p1.task_id,
            "authority_case_id": p1.case_id,
        }
        from dataclasses import asdict

        catalogue = {}
        for label in ("a", "b"):
            _, records = make_template(
                label,
                Scope(scope["tenantId"], scope["accountId"]),
                ref["caseId"],
                ref["conversationId"],
            )
            catalogue[label] = [
                {
                    "scope": asdict(record.scope),
                    "reference": asdict(record.reference),
                    "body_utf8": record.body.decode(),
                }
                for record in records
            ]
        bundle = {
            "schema_version": 1,
            "descriptor": descriptor,
            "catalogue": catalogue,
            "snapshots": snapshots,
            "observations": observations,
            "files": proof_files,
        }
        publish(artifacts / "actual-bundle.json", bundle, 2097152)
        state["stage"] = "independent-oracle"
        # Qualify the exact retained bytes a fresh reviewer will read, including
        # JSON serialization order. The in-memory producer object is insufficient.
        state["validated"] = validate_bundle(read(artifacts / "actual-bundle.json", 2097152))
        require(set(state["validated"]) == set(CASES))
        require(
            all(row == {"status": "passed", "code": "ok"} for row in state["validated"].values())
        )
    except BaseException as error:  # noqa: BLE001 - preserve primary failure through actual cleanup
        primary, failure_stage = error, state["stage"]
    finally:
        for holder in reversed(holders):
            try:
                await offload("holder-close", holder.close, cleaning=True)
            except Exception:  # noqa: BLE001 - cleanup preserves the primary and other owners
                cleanup_errors.append("sql_holder")
        # Request fixture release/stop before any parent fallback kill. No later business stage starts.
        for name, body in (
            ("race-release.json", {"schema_version": 1, "release": True}),
            ("origin-ack-release.json", {"schema_version": 1, "release": True}),
            ("origin-abort-lookups.json", {"schema_version": 1, "abort": True}),
            ("origin-result-stop.json", {"schema_version": 1, "stop": True}),
        ):
            try:
                if not (work / name).exists():
                    publish(work / name, body)
            except Exception:  # noqa: BLE001 - attempt every owner even if one control cannot publish
                cleanup_errors.append("release_control")
        for role in (
            "origin-race-a",
            "origin-race-b",
            "origin-ack",
            "origin-recovered",
            "origin-current",
        ):
            try:
                if role in children.children and not (work / (role + "-stop.json")).exists():
                    publish(work / (role + "-stop.json"), {"schema_version": 1, "stop": True})
            except Exception:  # noqa: BLE001 - failure of one marker cannot skip another owner
                cleanup_errors.append("stop_control")
        try:
            if owned:
                async with asyncio.timeout_at(final - 5):
                    await asyncio.gather(
                        *(asyncio.shield(task) for task in tuple(owned)), return_exceptions=True
                    )
        except Exception:  # noqa: BLE001 - actual tasks remain retained after observation timeout
            cleanup_errors.append("parent_tasks")
        try:
            await offload("children-close", children.close, cleaning=True)
        except Exception:  # noqa: BLE001 - process ownership is independent of task observation
            cleanup_errors.append("process_groups")
        if children.settled() and all(task.done() and not task.cancelled() for task in owned):
            try:
                await offload("pg-quiet", quiet, cleaning=True)
                if state["p2_setup_started"]:
                    await node_call("cleanup", cleaning=True)
            except Exception:  # noqa: BLE001 - independent work/shared-owner cleanup must still run
                cleanup_errors.append("p2_schema_removal")
            try:
                await offload("work-cleanup-group-close", children.close, cleaning=True)
                require(children.settled(), "cleanup_incomplete")
                await offload("work-owner-quiet", quiet, cleaning=True)
                await offload("drop-work", drop_work, cleaning=True)
            except Exception:  # noqa: BLE001 - preserve the primary and still attempt shared close
                cleanup_errors.append("schema_removal")
            try:
                # Owner cleanup can itself fail or outlive its observer. Reap it
                # before closing the P1 bridge/readers or removing their files.
                await offload("cleanup-group-close", children.close, cleaning=True)
                require(children.settled(), "cleanup_incomplete")
                await offload("shared-owner-quiet", quiet, cleaning=True)
                await p1.close(deadline=final)
                await offload("final-quiet", quiet, cleaning=True)
            except Exception:  # noqa: BLE001 - preserve primary and retain unresolved shared resources
                cleanup_errors.append("shared_owner")
        else:
            cleanup_errors.append("unresolved_owner_no_schema_removal")
        try:
            publish(artifacts / "process-groups.json", children.observation())
        except Exception:  # noqa: BLE001 - retain primary and continue independent evidence capture
            cleanup_errors.append("group_evidence")
        for path in sorted(work.glob("*.json")):
            if path.name in {"fixture-tsconfig.json"} or path.name.startswith("build-"):
                continue
            try:
                publish(artifacts / path.name, read(path))
            except Exception:  # noqa: BLE001 - a malformed child proof cannot replace the primary
                cleanup_errors.append("json_retention")
                try:
                    # Preserve malformed private bytes as data, never as validated proof.
                    raw = starter.bounded_read(path, 262144, allow_empty=True)
                    evidence.write_private(artifacts / ("unparsed-" + path.name + ".bin"), raw)
                except Exception:  # noqa: BLE001 - unsafe/missing originals remain in the owned work tree
                    cleanup_errors.append("raw_retention")
        for role, child in children.children.items():
            try:
                folder = artifacts / ("capture-" + role)
                folder.mkdir(mode=0o700)
                for name in ("stdout.bin", "stderr.bin", "process-group.pid"):
                    source = child.output_directory / name
                    capture_raw = starter.bounded_read(source, 65536, allow_empty=True)
                    evidence.write_private(folder / name, capture_raw)
            except Exception:  # noqa: BLE001 - a missing wrapper marker must still yield a failed report
                cleanup_errors.append("capture_retention")
        try:
            if (artifacts / "source-before.json").exists():
                old = read(artifacts / "source-before.json")
                after = source_snapshot(root)
                publish(artifacts / "source-after.json", after)
                if old != after and primary is None:
                    primary, failure_stage = OriginGateError("source_changed"), "source-final"
        except Exception:  # noqa: BLE001 - retain failed source evidence without erasing the primary
            cleanup_errors.append("source_retention")
        try:
            publish(
                artifacts / "parent-ownership.json",
                {
                    "schema_version": 1,
                    "tasks": len(owned),
                    "pending": sum(not task.done() for task in owned),
                    "cancelled": sum(task.cancelled() for task in owned),
                    "cleanup_errors": cleanup_errors,
                },
            )
        except Exception:  # noqa: BLE001 - report remains failed even when diagnostics cannot publish
            cleanup_errors.append("ownership_evidence")
    retained_raw: bytes | None = None
    try:
        retained_index = starter.retained_inventory(artifacts)
        retained_raw = starter.json_bytes(retained_index)
        starter.write_private(artifacts / "retained-index.json", retained_raw)
        starter.validate_retained_index(artifacts, retained_raw)
    except Exception:  # noqa: BLE001 - incomplete evidence can never produce a passing report
        retained_raw = None
        cleanup_errors.append("retained_index")
    if time.monotonic() >= final and primary is None:
        primary, failure_stage = OriginGateError("deadline_exceeded"), "final-evidence"
    passed = primary is None and not cleanup_errors and children.settled()
    require(not passed or set(children.children) == set(COMMANDS))
    work_retained = True
    if passed:
        marker = read(work / "origin-owned-work.json")
        require(marker == {"schema_version": 1, "run_id": run_id, "schemas": list(schemas)})
        require(work.parent == scratch and work.resolve() == work and not work.is_symlink())
        # Only the explicitly registered, drained test tree is disposable. All
        # source proofs/captures are already in the separately indexed artifacts.
        starter.retained_inventory(work)
        shutil.rmtree(work)
        require(not work.exists())
        work_retained = False
    if time.monotonic() >= final:
        passed = False
        if primary is None:
            primary, failure_stage = OriginGateError("deadline_exceeded"), "final-publication"
    value = {
        "schema_version": 1,
        "status": "passed" if passed else "failed",
        "code": "ok" if passed else finite_code(primary),
        "failure_stage": failure_stage,
        "assertions": len(CASES) if passed else 0,
        "case_results": state.get("validated", {}),
        "skipped": 0,
        "retained_index_sha256": hashlib.sha256(retained_raw).hexdigest() if retained_raw else None,
        "process_groups_sha256": (
            hashlib.sha256((artifacts / "process-groups.json").read_bytes()).hexdigest()
            if (artifacts / "process-groups.json").is_file()
            else None
        ),
        "cleanup_complete": not cleanup_errors and children.settled(),
        "cleanup_errors": cleanup_errors,
        "child_commands": len(children.children),
        "capture_bytes": sum(children.sizes.values()),
        "duration_seconds": time.monotonic() - started,
        "rtc_rooms": 0,
        "provider_calls": False,
        "carrier_sends": 0,
        "supplier_mutations": 0,
        "source_actual_assertions": len(CASES) if passed else 0,
        "installed_actual_assertions": 0,
        "work_directory_retained": work_retained,
        "work_directory": str(work),
    }
    publish(target, value)
    return value


def read_json_source(path: Path) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 262144)
    parsed = json.loads(
        path.read_bytes(), object_pairs_hook=core.unique_object, parse_constant=reject_constant
    )
    require(type(parsed) is dict)
    return cast(dict[str, Any], parsed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if args.plan:
        print(json.dumps(plan(), sort_keys=True))
        return 0
    try:
        report = asyncio.run(run(ROOT, private_report(ROOT, args.report)))
        print(json.dumps(report, sort_keys=True))
        return 0 if report["status"] == "passed" else 1
    except Exception as error:  # noqa: BLE001 - fixed diagnostic envelope excludes private errors
        print(json.dumps({"schema_version": 1, "status": "failed", "code": finite_code(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
