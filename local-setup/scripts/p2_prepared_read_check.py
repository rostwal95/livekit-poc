"""Bounded opt-in prepared-read qualification; --plan never starts resources.

This parent owns one disposable P2 profile and five registered process groups.
The independent literal oracle qualifies saved complete rows and actual SQL waits.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import re
import secrets
import shutil
import stat
import sys
import tempfile
import time
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from types import ModuleType
from typing import Any, Never, TypeVar, cast
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import p2_native_check as native
import p2_standalone_check as starter
import p3_coordinator_check as core
import p3_document_evidence as evidence
from p2_prepared_read_evidence import CASES, TABLES, validate_bundle

from continuity_lab.work_api import PostgresSettings

ROLES = ("compile-public", "compile-fixture", "setup", "read", "cleanup")
BASE = frozenset({"PATH", "LANG", "CI", "NO_COLOR", "__CF_USER_TEXT_ENCODING"})
TOKENS = ("ACCOUNT_TOKEN", "FOREIGN_ACCOUNT_TOKEN", "NATIVE_PUBLISHER_TOKEN", "NATIVE_BEARER")
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
_PRIVATE_OWNER: ModuleType | None = None


class PreparedGateError(RuntimeError):
    def __init__(self, code: object = "invalid_proof") -> None:
        self.code = code if type(code) is str and code in CODES else "invalid_proof"
        super().__init__(self.code)


def require(value: object, code: str = "invalid_proof") -> None:
    if value is not True:
        raise PreparedGateError(code)


def finite_code(error: BaseException | None) -> str:
    if type(error) is PreparedGateError:
        code = vars(error).get("code")
        return code if type(code) is str and code in CODES else "component_failed"
    if isinstance(error, TimeoutError):
        return "deadline_exceeded"
    return "component_failed"


def plan() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "planned",
        "assertions": list(CASES),
        "commands": list(ROLES),
        "expected_process_groups": 5,
        "max_process_groups": 8,
        "deadline_seconds": 180,
        "business_seconds": 160,
        "cleanup_seconds": 20,
        "stream_bytes": 65536,
        "aggregate_capture_bytes": 1048576,
        "schemas": 1,
        "scheduled_owned_sigkills": 0,
        "rtc_rooms": 0,
        "provider_calls": False,
        "p1_calls": 0,
        "carrier_sends": 0,
        "supplier_mutations": 0,
        "installed_actual_assertions": 0,
    }


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        require(key not in result)
        result[key] = value
    return result


def _constant(_: str) -> Any:
    raise PreparedGateError()


def json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        )
        + "\n"
    ).encode()


def read(path: Path, maximum: int = 2097152) -> dict[str, Any]:
    raw = starter.bounded_read(path, maximum)
    value = json.loads(
        raw.decode("utf-8", "strict"), object_pairs_hook=_pairs, parse_constant=_constant
    )
    require(type(value) is dict)
    return cast(dict[str, Any], value)


def publish(path: Path, value: object, maximum: int = 2097152) -> None:
    evidence.private_directory(path.parent)
    raw = json_bytes(value)
    require(len(raw) <= maximum)
    descriptor, name = tempfile.mkstemp(
        prefix="." + path.name + ".", suffix=".pending", dir=path.parent
    )
    pending = Path(name)
    info = os.fstat(descriptor)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(pending, path, follow_symlinks=False)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        current = pending.lstat()
        require((current.st_dev, current.st_ino) == (info.st_dev, info.st_ino))
        pending.unlink()


def base_environment() -> dict[str, str]:
    value = {key: os.environ[key] for key in BASE if key in os.environ}
    value.update(CI="1", NO_COLOR="1")
    value.setdefault("LANG", "en_US.UTF-8")
    require(bool(value.get("PATH")), "missing_setup")
    return value


def private_group_owner() -> ModuleType:
    """One gate-private copy of unchanged owner code; no shared-limit mutation."""
    global _PRIVATE_OWNER
    if _PRIVATE_OWNER is None:
        path = Path(starter.__file__).resolve()
        spec = importlib.util.spec_from_file_location("p2_prepared_private_group_owner", path)
        require(spec is not None and spec.loader is not None)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(spec.name, None)
            raise
        for key, value in (
            ("MAX_CHILDREN", 8),
            ("MAX_STREAM_BYTES", 65536),
            ("MAX_CAPTURE_BYTES", 1048576),
        ):
            setattr(module, key, value)
        _PRIVATE_OWNER = module
    return _PRIVATE_OWNER


class Groups:
    def __init__(self, directory: Path, deadline: float, final: float) -> None:
        self.module = private_group_owner()
        self.business = self.module.Children(
            directory, deadline, final, roles=frozenset(ROLES[:-1])
        )
        self.cleanup = self.module.Children(directory, final, final, roles=frozenset({"cleanup"}))
        self.owners: dict[str, Any] = {}
        self.sentinels: tuple[bytes, ...] = ()

    def start(self, role: str, argv: list[str], environment: dict[str, str], cwd: Path) -> Any:
        require(role in ROLES and role not in self.owners and len(self.owners) < 5)
        self.capture_budget()
        registry = self.cleanup if role == "cleanup" else self.business
        child = registry.start(role, argv, environment, cwd=cwd)
        self.owners[role] = child
        self.capture_budget()
        return child

    def capture_budget(self) -> None:
        require(self.business.count + self.cleanup.count <= 8, "capture_budget")
        require(
            self.business.captured
            + self.cleanup.captured
            + self.business.reservations
            + self.cleanup.reservations
            <= 1048576,
            "capture_budget",
        )

    def finish(self, role: str) -> bytes:
        registry = self.cleanup if role == "cleanup" else self.business
        result = registry.finish(self.owners[role], secrets=self.sentinels)
        self.capture_budget()
        return cast(bytes, result)

    def settled(self) -> bool:
        return bool(self.business.all_settled() and self.cleanup.all_settled())

    def close_business(self) -> None:
        self.business.close()

    def close_cleanup(self) -> None:
        self.cleanup.close()

    def capture_all(self) -> None:
        failed = False
        for role, child in self.owners.items():
            if child.returncode is not None:
                registry = self.cleanup if role == "cleanup" else self.business
                try:
                    registry.capture(child, secrets=self.sentinels)
                except Exception:  # noqa: BLE001 - one missing capture cannot suppress others
                    failed = True
        self.capture_budget()
        require(not failed, "capture_budget")

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
                for role, child in self.owners.items()
            ],
            "capture_bytes": self.business.captured + self.cleanup.captured,
        }


class Actions:
    """A timeout ends only observation; actual offloads stay registered for teardown."""

    def __init__(self, deadline: float, final: float) -> None:
        self.deadline, self.final = deadline, final
        self.tasks: set[asyncio.Task[Any]] = set()

    async def run(self, call: Callable[[], T], *, cleaning: bool = False) -> T:
        limit = self.final if cleaning else self.deadline
        require(time.monotonic() < limit, "deadline_exceeded")
        operation = asyncio.to_thread(call)
        try:
            task = asyncio.create_task(operation)
        except BaseException:
            operation.close()
            raise
        self.tasks.add(task)
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        async with asyncio.timeout_at(limit):
            return await asyncio.shield(task)

    async def drain(self) -> bool:
        if not self.tasks:
            return True
        try:
            async with asyncio.timeout_at(self.final):
                await asyncio.gather(
                    *(asyncio.shield(task) for task in self.tasks), return_exceptions=True
                )
        except TimeoutError:
            return False
        return all(task.done() and not task.cancelled() for task in self.tasks)


async def wait_marker(groups: Groups, path: Path, deadline: float) -> dict[str, Any]:
    while time.monotonic() < deadline:
        try:
            info = path.lstat()
        except FileNotFoundError:
            info = None
        if info is not None:
            require(
                stat.S_ISREG(info.st_mode)
                and stat.S_IMODE(info.st_mode) == 0o600
                and info.st_uid == os.geteuid()
                and 0 < info.st_size <= 65536
            )
            if info.st_nlink == 1:
                require(groups.owners["read"].returncode is None, "component_failed")
                return read(path, 65536)
            require(info.st_nlink == 2)
        require(groups.owners["read"].returncode is None, "component_failed")
        await asyncio.sleep(0.005)
    raise PreparedGateError("deadline_exceeded")


def source_snapshot(root: Path) -> dict[str, str]:
    project = root / "projects/channel-continuity"
    paths = (
        set((project / "src").rglob("*.ts"))
        | set((project / "examples").rglob("*.ts"))
        | set((project / "tests").rglob("*.ts"))
    )
    paths.update(
        project / name
        for name in (
            "package.json",
            "tsconfig.json",
            "tsconfig.examples.json",
            "tsconfig.starter.json",
            "tsconfig.pg.json",
            "tsconfig.test.json",
            "tests/pg_prepared_read_cases.ts",
            "tests/pg_channel_origin_cases.ts",
            "tests/fixture-work.ts",
            "tests/read-prepared.test.ts",
            "tests/prepared-read-fixture.test.ts",
        )
    )
    p1 = root / "projects/agent-continuity/python"
    paths.update((p1 / "src").rglob("*.py"))
    paths.update((p1 / "src").rglob("py.typed"))
    paths.add(p1 / "pyproject.toml")
    paths.update(
        root / "local-setup/scripts" / name
        for name in (
            "p2_prepared_read_check.py",
            "p2_prepared_read_evidence.py",
            "p2_standalone_check.py",
            "p2_native_check.py",
            "p3_coordinator_check.py",
            "p3_document_package.py",
            "p3_document_evidence.py",
            "p3_package_check.py",
        )
    )
    paths.update(
        root / name
        for name in (
            "local-setup/stack.py",
            "harness/process_control.py",
            "pnpm-lock.yaml",
            "package.json",
            "pyproject.toml",
            "uv.lock",
            "tests/test_p2_prepared_read_gate.py",
        )
    )
    result = {}
    for path in sorted(paths):
        require(
            path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root),
            "missing_setup",
        )
        result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def snapshot(settings: PostgresSettings) -> dict[str, Any]:
    from psycopg import sql

    require(re.fullmatch(r"p2_prepared_[0-9a-f]{32}", settings.schema) is not None)
    with (
        closing(settings.connect(application_name="continuity-test")) as connection,
        connection.transaction(),
    ):
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        tables = connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname=%s ORDER BY tablename",
            [settings.schema],
        ).fetchall()
        require({row["tablename"] for row in tables} == TABLES)
        result = {}
        for table in sorted(TABLES):
            values = [
                row["row"]
                for row in connection.execute(
                    sql.SQL("SELECT to_jsonb(t) AS row FROM {} t LIMIT 65").format(
                        sql.Identifier(settings.schema, table)
                    )
                ).fetchall()
            ]
            require(len(values) <= 64)
            result[table] = sorted(values, key=lambda value: json_bytes(value))
        return result


class SqlHolder:
    def __init__(self, settings: PostgresSettings) -> None:
        self.settings = settings
        self.connection: Any = None
        self.transaction: Any = None
        self.pid: int | None = None

    @property
    def closed(self) -> bool:
        return self.connection is None and self.transaction is None

    def acquire(self) -> None:
        from psycopg import sql

        self.connection = self.settings.connect(application_name="continuity-test")
        try:
            self.transaction = self.connection.transaction()
            self.transaction.__enter__()
            self.connection.execute(
                sql.SQL("LOCK TABLE {} IN ACCESS EXCLUSIVE MODE").format(
                    sql.Identifier(self.settings.schema, "dispatch_plans")
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
                self.transaction = None


def wait_graph(observer: PostgresSettings, holder: SqlHolder) -> dict[str, Any]:
    require(holder.pid is not None)
    with closing(observer.connect(application_name="continuity-test")) as connection:
        rows = connection.execute(
            "SELECT pid,usename,pg_blocking_pids(pid) AS blockers,query,wait_event_type FROM pg_stat_activity WHERE datname=current_database() AND usename=current_user AND pid<>%s AND wait_event_type='Lock' AND EXISTS(SELECT 1 FROM pg_locks l JOIN pg_class c ON c.oid=l.relation JOIN pg_namespace n ON n.oid=c.relnamespace WHERE l.pid=pg_stat_activity.pid AND n.nspname=%s AND c.relname='dispatch_plans') ORDER BY pid LIMIT 2",
            [holder.pid, observer.schema],
        ).fetchall()
        locks = connection.execute(
            "SELECT l.pid,l.relation::bigint AS relation_oid,n.nspname AS schema_name,c.relname AS table_name,l.locktype,l.mode,l.granted FROM pg_locks l JOIN pg_class c ON c.oid=l.relation JOIN pg_namespace n ON n.oid=c.relnamespace WHERE l.pid=ANY(%s) AND n.nspname=%s AND c.relname='dispatch_plans' AND l.locktype='relation' ORDER BY l.pid,l.mode,l.granted",
            [[holder.pid, *(row["pid"] for row in rows)], observer.schema],
        ).fetchall()
    with closing(holder.settings.connect(application_name="continuity-test")) as connection:
        owner = connection.execute(
            "SELECT pid,usename,query,state,application_name FROM pg_stat_activity WHERE pid=%s",
            [holder.pid],
        ).fetchall()
    require(len(owner) == 1 and owner[0]["state"] == "idle in transaction")
    require(type(owner[0]["query"]) is str and len(owner[0]["query"].encode()) <= 16384)
    require(all(type(row["query"]) is str and len(row["query"].encode()) <= 16384 for row in rows))

    def related(pid: int) -> list[dict[str, Any]]:
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
        "schema": observer.schema,
        "table": "dispatch_plans",
        "association": "unique_disposable_channel_schema",
        "row_lock": False,
        "holder_pid": holder.pid,
        "holder_usename": owner[0]["usename"],
        "holder_query": owner[0]["query"],
        "holder_query_sha256": hashlib.sha256(owner[0]["query"].encode()).hexdigest(),
        "holder_locks": related(cast(int, holder.pid)),
        "expected_waiters": 1,
        "waiters": [
            {
                "pid": row["pid"],
                "usename": row["usename"],
                "blockers": row["blockers"],
                "wait_event_type": row["wait_event_type"],
                "query": row["query"],
                "query_sha256": hashlib.sha256(row["query"].encode()).hexdigest(),
                "relation_locks": related(row["pid"]),
            }
            for row in rows
        ],
    }


async def observed_wait(
    actions: Actions, observer: PostgresSettings, holder: SqlHolder, until: float
) -> dict[str, Any]:
    from p2_prepared_read_evidence import graph

    while time.monotonic() < until:
        value = await actions.run(lambda: wait_graph(observer, holder))
        try:
            graph(value, observer.schema)
            return value
        except ValueError:
            await asyncio.sleep(0.005)
    raise PreparedGateError("deadline_exceeded")


async def exercise_hold(
    actions: Actions,
    groups: Groups,
    holder: SqlHolder,
    observer: PostgresSettings,
    work: Path,
    deadline: float,
    read_pid: int,
) -> dict[str, Any]:
    await actions.run(holder.acquire)
    hold_until = min(deadline, time.monotonic() + 0.85)
    observations: dict[str, Any] = {}
    primary: BaseException | None = None
    try:
        async with asyncio.timeout_at(hold_until):
            publish(work / "prepared-hold-ready.json", {"schema_version": 1, "hold": True})
            require(
                starter.exact(
                    await wait_marker(
                        groups, work / "prepared-read-callers-started.json", hold_until
                    ),
                    {"schema_version": 1, "callerCount": 1},
                )
            )
            observations["held_wait_graph"] = await observed_wait(
                actions, observer, holder, hold_until
            )
            publish(work / "prepared-wait-graph.json", observations["held_wait_graph"])
            publish(work / "prepared-close-read.json", {"schema_version": 1, "close": True})
            pending = await wait_marker(groups, work / "prepared-close-pending.json", hold_until)
            require(
                starter.exact(
                    pending,
                    {
                        "schema_version": 1,
                        "pending_read": True,
                        "pending_close": True,
                        "subsequent_read_code": "StorageUnavailable",
                    },
                )
            )
            observations["close_pending"] = pending
            observations["held_wait_graph_at_close"] = await observed_wait(
                actions, observer, holder, hold_until
            )
            publish(
                work / "prepared-wait-graph-at-close.json", observations["held_wait_graph_at_close"]
            )
            observations["read_pid"] = read_pid
    except BaseException as error:  # noqa: BLE001 - retain control-flow/primary across holder cleanup
        primary = error
    finally:
        try:
            await actions.run(holder.close, cleaning=True)
        except BaseException as error:  # noqa: BLE001 - actual holder cleanup never replaces primary
            if primary is None:
                primary = error
    if primary is not None:
        raise primary
    return observations


def namespace(settings: PostgresSettings) -> list[dict[str, Any]]:
    with closing(settings.connect(application_name="continuity-test")) as connection:
        return connection.execute(
            "SELECT pg_get_userbyid(nspowner) AS owner,obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=%s",
            [settings.schema],
        ).fetchall()


def relation_locks(settings: PostgresSettings) -> int:
    with closing(settings.connect(application_name="continuity-test")) as connection:
        row = connection.execute(
            "SELECT count(*) AS n FROM pg_locks l JOIN pg_class c ON c.oid=l.relation JOIN pg_namespace n ON n.oid=c.relnamespace WHERE l.pid<>pg_backend_pid() AND n.nspname=%s",
            [settings.schema],
        ).fetchone()
        require(row is not None)
        assert row is not None
        return cast(int, row["n"])


def drop_partial(settings: PostgresSettings) -> None:
    from psycopg import sql

    found = namespace(settings)
    if not found:
        return
    require(
        len(found) == 1
        and found[0]["owner"] == "continuity_migrator"
        and found[0]["marker"] in {"p2-channel-schema-v" + str(n) for n in range(1, 9)}
    )
    require(relation_locks(settings) == 0, "cleanup_incomplete")
    with closing(settings.connect(application_name="continuity-test")) as connection:
        connection.execute(
            sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(settings.schema))
        )


def node_argv(node: str, script: Path, *arguments: str) -> list[str]:
    return [node, "--no-warnings", str(script), *arguments]


def fixture_config(project: Path, work: Path) -> Path:
    raw = json.loads((project / "tsconfig.pg.json").read_bytes())
    path = work / "fixture-tsconfig.json"
    publish(
        path,
        {
            "extends": str(project / "tsconfig.pg.json"),
            "compilerOptions": {
                "outDir": str(work / "compiled"),
                "tsBuildInfoFile": str(work / "fixture.tsbuildinfo"),
                "typeRoots": [str(project / "node_modules/@types")],
            },
            "include": [
                *(str(project / name) for name in raw["include"]),
                str(project / "tests/pg_prepared_read_cases.ts"),
            ],
        },
    )
    return path


def validate_saved_bundle(path: Path) -> dict[str, Any]:
    value = validate_bundle(read(path))
    require(
        set(value) == set(CASES)
        and all(row == {"status": "passed", "code": "ok"} for row in value.values())
    )
    return cast(dict[str, Any], value)


async def cleanup_owners(
    actions: Actions, groups: Groups, holder: SqlHolder, cleanup_schema: Callable[[], Any]
) -> list[str]:
    errors = []
    for label, callback in (
        ("sql_holder", holder.close),
        ("business_groups", groups.close_business),
        ("cleanup_groups", groups.close_cleanup),
    ):
        try:
            await actions.run(callback, cleaning=True)
        except Exception:  # noqa: BLE001 - attempt independent owner cleanup and preserve primary
            errors.append(label)
    drained = await actions.drain()
    if drained and holder.closed and groups.settled():
        try:
            await actions.run(cleanup_schema, cleaning=True)
        except Exception:  # noqa: BLE001 - failed schema cleanup never changes original error
            errors.append("schema_cleanup")
        try:
            await actions.run(groups.close_cleanup, cleaning=True)
        except Exception:  # noqa: BLE001 - cleanup role must itself settle before retention/removal
            errors.append("cleanup_groups_final")
    else:
        errors.append("unresolved_owner_no_ddl")
    return errors


def private_report(root: Path, requested: Path | None) -> Path:
    folder = root / ".local/validation/p2-prepared-read"
    evidence.private_directory(folder)
    path = requested or folder / ("run-" + uuid4().hex + ".json")
    require(
        path.is_absolute()
        and path.resolve() == path
        and path.parent == folder
        and not path.exists()
        and not path.is_symlink(),
        "invalid_input",
    )
    return path


def remove_owned_work(
    work: Path, scratch: Path, marker: dict[str, Any], *, authorized: bool
) -> None:
    require(
        authorized and work.parent == scratch and work.resolve() == work and not work.is_symlink(),
        "cleanup_incomplete",
    )
    require(read(work / "prepared-owned-work.json") == marker)
    starter.retained_inventory(work)
    shutil.rmtree(work)
    require(not work.exists(), "cleanup_incomplete")


async def run(root: Path, target: Path) -> dict[str, Any]:
    started = time.monotonic()
    deadline, final = started + 160, started + 180
    require(sys.version_info[:3] == (3, 14, 10) and not sys.flags.optimize, "missing_setup")
    values = cast(dict[str, str], core.load_setup(root).load_settings())
    node = str(starter.tool("node"))
    project = root / "projects/channel-continuity"
    compiler = project / "node_modules/typescript/bin/tsc"
    require(compiler.is_file(), "missing_setup")
    scratch = project / ".local/prepared-read"
    evidence.private_directory(scratch)
    work = Path(tempfile.mkdtemp(prefix="run-", dir=scratch)).resolve()
    os.chmod(work, 0o700)
    artifacts = target.with_name(target.stem + "-artifacts")
    artifacts.mkdir(mode=0o700)
    groups, actions = Groups(work, deadline, final), Actions(deadline, final)
    schema = "p2_prepared_" + uuid4().hex
    owner = PostgresSettings(
        port=int(values["POSTGRES_PORT"]),
        user="continuity_migrator",
        password=values["POSTGRES_MIGRATION_PASSWORD"],
        schema=schema,
    )
    observer = PostgresSettings(
        port=int(values["POSTGRES_PORT"]), password=values["POSTGRES_PASSWORD"], schema=schema
    )
    holder = SqlHolder(owner)
    tokens = {name: secrets.token_urlsafe(32) for name in TOKENS}
    groups.sentinels = tuple(
        value.encode()
        for value in (
            *tokens.values(),
            values["POSTGRES_PASSWORD"],
            values["POSTGRES_MIGRATION_PASSWORD"],
        )
    )
    config: dict[str, Any] = {
        "schema_version": 1,
        "scope": {"tenantId": "prepared_tenant", "accountId": "prepared_account"},
        "case_id": "prepared_case",
        "conversation_id": "prepared_conversation",
        "binding_id": str(uuid4()),
        "input_ids": {name: str(uuid4()) for name in ("unprepared", "native", "sms")},
        "parent_expires_at_ms": int(time.time() * 1000 + max(0, final - time.monotonic()) * 1000),
    }
    marker = {"schema_version": 1, "schema": schema, "work_id": uuid4().hex}
    data: dict[str, Any] = {}
    observations: dict[str, Any] = {}
    primary: BaseException | None = None
    failure_stage: str | None = None
    stage = "configuration"
    setup_started = False
    cleanup: dict[str, Any] = {}
    cleanup_errors: list[str] = []
    source_before: dict[str, str] | None = None
    retained_raw: bytes | None = None
    work_retained = True

    def role_environment(mode: str) -> dict[str, str]:
        result = {
            **base_environment(),
            "P2_PREPARED_DIRECTORY": str(work),
            "P2_PREPARED_SCHEMA": schema,
            "P2_PREPARED_PG_PORT": values["POSTGRES_PORT"],
            **{"P2_PREPARED_" + key: token for key, token in tokens.items()},
        }
        if mode != "read":
            result["P2_PREPARED_OWNER_PASSWORD"] = values["POSTGRES_MIGRATION_PASSWORD"]
        if mode != "cleanup":
            result["P2_PREPARED_RUNTIME_PASSWORD"] = values["POSTGRES_PASSWORD"]
        return result

    def node_start(mode: str) -> Any:
        return groups.start(
            mode,
            node_argv(node, work / "compiled/tests/pg_prepared_read_cases.js", mode),
            role_environment(mode),
            project,
        )

    def cleanup_schema() -> None:
        quiet = relation_locks(owner)
        require(quiet == 0, "cleanup_incomplete")
        cleanup["pre_drop_relation_locks"] = quiet
        if setup_started and (work / "prepared-setup.json").exists():
            node_start("cleanup")
            groups.finish("cleanup")
            cleanup["proof"] = read(work / "prepared-cleanup.json")
        elif setup_started:
            drop_partial(owner)
        require(not namespace(owner), "cleanup_incomplete")
        require(relation_locks(owner) == 0, "cleanup_incomplete")
        cleanup["namespace_absent"] = True
        cleanup["owned_work_removal_authorized"] = False

    try:
        require(not await actions.run(lambda: namespace(owner)))
        source_before = source_snapshot(root)
        publish(artifacts / "source-before.json", source_before)
        publish(artifacts / "plan.json", plan())
        publish(work / "prepared-owned-work.json", marker)
        publish(work / "prepared-fixture.json", config)
        configurations = starter.build_configurations(root, work)
        publish(
            artifacts / "compiler-configurations.json",
            {path.name: read(path) for path in configurations},
        )
        stage = "compile-public"
        groups.start(
            stage,
            node_argv(
                node, compiler, "--build", "--force", *(str(path) for path in configurations)
            ),
            base_environment(),
            project,
        )
        await actions.run(lambda: groups.finish("compile-public"))
        stage = "compile-fixture"
        config_path = fixture_config(project, work)
        groups.start(
            stage,
            node_argv(node, compiler, "--project", str(config_path)),
            base_environment(),
            project,
        )
        await actions.run(lambda: groups.finish("compile-fixture"))
        publish(
            artifacts / "runtime-build-parity.json",
            native.verify_runtime_build(project, work / "compiled"),
        )
        for name in ("pg_prepared_read_cases", "pg_channel_origin_cases"):
            built = work / "compiled/tests" / (name + ".js")
            info = built.lstat()
            require(
                stat.S_ISREG(info.st_mode)
                and info.st_nlink == 1
                and info.st_uid == os.geteuid()
                and not built.is_symlink()
                and built.resolve() == built
                and info.st_size <= 131072
            )
            raw = built.read_bytes()
            starter.scan_secrets(raw, groups.sentinels)
            starter.write_private(artifacts / (name + ".js"), raw, 131072)
        stage = "setup"
        setup_started = True
        node_start(stage)
        await actions.run(lambda: groups.finish("setup"))
        data["setup"] = read(work / "prepared-setup.json")
        data["sms_source"] = read(work / "prepared-sms-source.json")
        data["before"] = await actions.run(lambda: snapshot(owner))
        publish(artifacts / "snapshot-before.json", data["before"])
        stage = "read"
        child = node_start(stage)
        require(
            starter.exact(
                await wait_marker(groups, work / "prepared-controls-complete.json", deadline),
                {"schema_version": 1, "complete": True},
            )
        )
        stage = "actual-sql-hold"
        observations.update(
            await exercise_hold(actions, groups, holder, observer, work, deadline, child.pid)
        )
        await actions.run(lambda: groups.finish("read"))
        data["read"] = read(work / "prepared-read.json")
        data["after"] = await actions.run(lambda: snapshot(owner))
        publish(artifacts / "snapshot-after.json", data["after"])
    except BaseException as error:  # noqa: BLE001 - retain first error while attempting every independent cleanup
        primary, failure_stage = error, stage
    finally:
        cleanup_errors.extend(await cleanup_owners(actions, groups, holder, cleanup_schema))
        for label, callback in (
            ("capture", groups.capture_all),
            ("groups", lambda: publish(artifacts / "process-groups.json", groups.observation())),
        ):
            try:
                await actions.run(callback, cleaning=True)
            except Exception:  # noqa: BLE001 - diagnostics cannot prevent remaining retention
                cleanup_errors.append(label)
        for path in sorted(work.glob("*.json")):
            try:
                publish(artifacts / path.name, read(path))
            except Exception:  # noqa: BLE001 - preserve original private bytes when proof parsing fails
                cleanup_errors.append("json_retention")
                try:
                    starter.write_private(
                        artifacts / ("unparsed-" + path.name + ".bin"),
                        starter.bounded_read(path, 2097152, allow_empty=True),
                        2097152,
                    )
                except Exception:  # noqa: BLE001 - unresolved originals remain in private work directory
                    cleanup_errors.append("raw_retention")
        for role, child in groups.owners.items():
            try:
                destination = artifacts / ("capture-" + role)
                evidence.private_directory(destination)
                for name in ("stdout.bin", "stderr.bin", "process-group.pid"):
                    raw = starter.bounded_read(
                        child.output_directory / name, 65536, allow_empty=True
                    )
                    starter.scan_secrets(raw, groups.sentinels)
                    starter.write_private(destination / name, raw, 65536)
            except Exception:  # noqa: BLE001 - missing capture metadata keeps run failed, other owners retained
                cleanup_errors.append("capture_retention")
        try:
            source_after = source_snapshot(root)
            publish(artifacts / "source-after.json", source_after)
            require(source_before is not None and source_before == source_after, "source_changed")
        except Exception as error:  # noqa: BLE001 - preserve primary source error and retain failed evidence
            cleanup_errors.append("source_retention")
            if primary is None:
                primary, failure_stage = error, "source-final"
        try:
            if primary is None and not cleanup_errors:
                require(groups.settled() and set(groups.owners) == set(ROLES), "cleanup_incomplete")
                require(read(work / "prepared-owned-work.json") == marker)
                require(work.parent == scratch and work.resolve() == work and not work.is_symlink())
                starter.retained_inventory(work)
                cleanup["owned_work_removal_authorized"] = True
                bundle = {
                    "schema_version": 1,
                    "config": config,
                    "native_bearer_sha256": hashlib.sha256(
                        tokens["NATIVE_BEARER"].encode()
                    ).hexdigest(),
                    "schema": schema,
                    **data,
                    "observations": observations,
                    "groups": groups.observation(),
                    "cleanup": cleanup,
                }
                publish(artifacts / "actual-bundle.json", bundle)
                case_results = validate_saved_bundle(artifacts / "actual-bundle.json")
            else:
                case_results = {}
        except Exception as error:  # noqa: BLE001 - no success without independent persisted-byte oracle
            primary, failure_stage = error, "independent-oracle"
            case_results = {}
        try:
            retained_raw = starter.json_bytes(starter.retained_inventory(artifacts))
            starter.write_private(artifacts / "retained-index.json", retained_raw)
            starter.validate_retained_index(artifacts, retained_raw)
        except Exception:  # noqa: BLE001 - retention/index failure never authorizes work removal
            retained_raw = None
            cleanup_errors.append("retained_index")
    passed = (
        primary is None
        and not cleanup_errors
        and groups.settled()
        and len(case_results) == 8
        and retained_raw is not None
        and time.monotonic() < final
    )
    if passed:
        try:
            remove_owned_work(
                work,
                scratch,
                marker,
                authorized=cleanup.get("namespace_absent") is True
                and bool(actions.tasks)
                and all(task.done() and not task.cancelled() for task in actions.tasks),
            )
            work_retained = False
        except Exception as error:  # noqa: BLE001 - exact work removal failure remains failed and recoverable
            passed = False
            primary, failure_stage = error, "work-removal"
    if time.monotonic() >= final:
        passed = False
        if primary is None:
            primary, failure_stage = PreparedGateError("deadline_exceeded"), "final-publication"
    result = {
        "schema_version": 1,
        "status": "passed" if passed else "failed",
        "code": "ok" if passed else finite_code(primary),
        "failure_stage": failure_stage,
        "assertions": 8 if passed else 0,
        "case_results": case_results,
        "skipped": 0,
        "cleanup_complete": not cleanup_errors
        and groups.settled()
        and cleanup.get("namespace_absent") is True
        and all(task.done() and not task.cancelled() for task in actions.tasks),
        "cleanup_errors": cleanup_errors,
        "child_commands": len(groups.owners),
        "capture_bytes": groups.observation()["capture_bytes"],
        "duration_seconds": time.monotonic() - started,
        "source_actual_assertions": 8 if passed else 0,
        "installed_actual_assertions": 0,
        "work_directory_retained": work_retained,
        "work_directory": str(work),
        "retained_index_sha256": hashlib.sha256(retained_raw).hexdigest() if retained_raw else None,
        "rtc_rooms": 0,
        "provider_calls": False,
        "p1_calls": 0,
        "carrier_sends": 0,
        "supplier_mutations": 0,
    }
    publish(target, result)
    return result


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise PreparedGateError("invalid_input")


def main(argv: list[str] | None = None) -> int:
    try:
        parser = SafeParser(description=__doc__)
        parser.add_argument("--plan", action="store_true")
        parser.add_argument("--report", type=Path)
        args = parser.parse_args(argv)
        if args.plan:
            print(json.dumps(plan(), sort_keys=True))
            return 0
        value = asyncio.run(run(ROOT, private_report(ROOT, args.report)))
        print(json.dumps(value, sort_keys=True))
        return 0 if value["status"] == "passed" else 1
    except Exception as error:  # noqa: BLE001 - finite public envelope never exposes private details
        print(json.dumps({"schema_version": 1, "status": "failed", "code": finite_code(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
