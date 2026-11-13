"""Separate installed P1/P2 adapter qualification; no setup on import or --plan.

This test-only composition uses public installed business APIs and explicit owner
CLI setup. SQL is bounded independent observation and removal of the fresh,
UUID-owned schema. No default service or provider is involved.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import secrets
import shutil
import sqlite3
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import p2_standalone_check as shared
import p3_coordinator_check as setup_tools
import p3_package_check as package_tools

from harness.process_control import FileBarrier, OwnedProcess

MODE = "installed_p1_adapter_contract"
DIRECT_ROLES = (
    "compile",
    "pack",
    "install",
    "strict-consumer",
    "p1-wheel-build",
    "p1-environment",
    "p1-install",
    "p1-sqlite-init",
    "p1-cutover",
    "p1-upgrade-cases",
    "p1-upgrade-effects",
    "p1-upgrade-work",
    "p1-stale-supplier-init",
    "p1-exact-supplier-init",
    "p1-seed",
    "p1-bridges",
    "p1-revision-consumer",
    "p1-stale-inquiry",
    "p1-stale-quote",
    "p1-stale-consumer",
    "p1-exact-inquiry",
    "p1-exact-quote",
    "p1-exact-consumer",
    "p1-exact-mutation",
    "p1-current-consumer",
    "p1-public-final-verify",
)
STEP_ROLES = ("stale-inquiry", "exact-inquiry", "exact-mutation")
PHASES = ("revision", "stale-confirmation", "exact-confirmation", "current-facts")
MARKERS = (
    "p1_ready",
    "p1_stop",
    "p1_zero_read_done",
    "p1_revision_committed",
    "p1_revision_unknown",
)
SNAPSHOT_PHASES = ("before_zero", "after_zero", "before_final_read", "after_final_read")
SUPPLIER_TABLES = (
    "supplier_metadata",
    "bookings",
    "inquiry_receipts",
    "mutation_receipts",
    "apply_calls",
)
CASE_NAMES = shared.P1_CASE_NAMES
TOTAL_SECONDS, CLEANUP_SECONDS = 360, 20
MAX_DIRECT, EXPECTED_DIRECT, EXPECTED_NESTED = 29, 26, 3
GateError = shared.GateError


def require(value: object) -> None:
    if value is not True:
        raise GateError("invalid_proof")


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def plan() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "not_started",
        "mode": MODE,
        "measurement_started": False,
        "cases": list(CASE_NAMES),
        "direct_roles": list(DIRECT_ROLES),
        "nested_roles": list(STEP_ROLES),
        "direct_commands": EXPECTED_DIRECT,
        "nested_commands": EXPECTED_NESTED,
        "total_commands": EXPECTED_DIRECT + EXPECTED_NESTED,
        "bounds": {
            "total_seconds": TOTAL_SECONDS,
            "cleanup_seconds": CLEANUP_SECONDS,
            "max_direct_children": MAX_DIRECT,
            "max_owned_process_groups": 32,
            "stream_bytes": shared.MAX_STREAM_BYTES,
            "capture_bytes": shared.MAX_CAPTURE_BYTES,
            "proof_bytes": shared.MAX_PROOF_BYTES,
            "evidence_bytes": shared.MAX_EVIDENCE_BYTES,
        },
        "process_accounting": "26 direct command groups plus3 separately owned P1 step sessions; descendants stay owned by their command group. No OS-wide PID census or capacity claim.",
        "claim": "Six public installed adapter assertions; no native revision-zero execution",
    }


def source_snapshot(root: Path) -> dict[str, str]:
    result = shared.source_snapshot(root)
    names = {
        "local-setup/scripts/p2_starter_p1_check.py",
        "local-setup/scripts/p2_starter_p1_evidence.py",
        "local-setup/scripts/p2_starter_p1.py",
        "local-setup/scripts/p2_case_bridge.py",
        "local-setup/scripts/p2_current_case_bridge.py",
        "tests/test_p2_starter_p1_check.py",
        "tests/test_p2_starter_p1_evidence.py",
        "projects/agent-continuity/python/pyproject.toml",
        "projects/agent-continuity/python/README.md",
        "uv.lock",
    }
    names.update(
        p.relative_to(root).as_posix()
        for p in (root / "projects/agent-continuity/python/src/continuity_lab").rglob("*")
        if p.is_file() and p.suffix in {".py", ".typed"}
    )
    for name in names:
        path = root / name
        require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root))
        result[name] = digest(path.read_bytes())
    return dict(sorted(result.items()))


def runtime_base() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in shared.BASE_KEYS}
    shared.validate_environment(env, required=frozenset())
    return env


def validate_step(
    raw: bytes, *, role: str, owner: str, worker_pid: int, executable: Path
) -> dict[str, Any]:
    value = shared.decode(raw, 16384)
    require(set(value) == {"schemaVersion", "owner", "workerProcessId", "steps", "cleanupComplete"})
    require(
        shared.exact(value["schemaVersion"], 1)
        and value["owner"] == owner
        and shared.exact(value["workerProcessId"], worker_pid)
        and value["cleanupComplete"] is True
        and type(value["steps"]) is list
        and len(value["steps"]) == 1
    )
    step = value["steps"][0]
    require(
        type(step) is dict
        and set(step) == {"role", "processId", "groupId", "argvSha256", "returnCode", "groupAbsent"}
    )
    require(
        role in STEP_ROLES
        and step["role"] == role
        and shared.natural(step["processId"], 2**31 - 1, 2)
        and shared.exact(step["groupId"], step["processId"])
        and step["processId"] not in {os.getpid(), os.getpgrp(), worker_pid}
        and step["argvSha256"]
        == digest(shared.json_bytes([str(executable), "-m", "continuity_lab.worker_cli", "step"]))
        and shared.exact(step["returnCode"], 0)
        and step["groupAbsent"] is True
    )
    return value


def group_absent(pid: int) -> bool:
    """Only probe recorded groups; absence never authorizes a later signal."""
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def owner_snapshot(connect: Any, schema: str) -> dict[str, Any]:
    from psycopg import sql

    require(re.fullmatch(r"p1_starter_[0-9a-f]{32}", schema) is not None)
    result: dict[str, Any] = {}
    local_deadline = time.monotonic() + 10
    with closing(connect()) as connection:
        owner = connection.execute(
            "SELECT pg_get_userbyid(nspowner) AS owner FROM pg_namespace WHERE nspname=%s",
            (schema,),
        ).fetchall()
        require(owner == [{"owner": "continuity_migrator"}])
        tables = connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname=%s ORDER BY tablename", (schema,)
        ).fetchall()
        require(1 <= len(tables) <= 64)
        for table in tables:
            shared.remaining(local_deadline)
            name = table["tablename"]
            require(type(name) is str and re.fullmatch(r"[a-z][a-z0-9_]{0,62}", name) is not None)
            rows = connection.execute(
                sql.SQL(
                    "SELECT to_jsonb(t)::text AS body FROM {}.{} t "
                    "ORDER BY to_jsonb(t)::text LIMIT 129"
                ).format(sql.Identifier(schema), sql.Identifier(name))
            ).fetchall()
            require(len(rows) <= 128)
            result[name] = [shared.decode(row["body"].encode()) for row in rows]
    require(len(shared.json_bytes(result)) <= shared.MAX_PROOF_BYTES)
    return result


def supplier_snapshot(path: Path) -> dict[str, Any]:
    shared.bounded_read(path, 8 * 1024 * 1024)
    result = {}
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        for name in SUPPLIER_TABLES:
            rows = connection.execute(f'SELECT * FROM "{name}" ORDER BY 1,2 LIMIT 129').fetchall()
            require(len(rows) <= 128)
            result[name] = [dict(row) for row in rows]
    require(len(shared.json_bytes(result)) <= shared.MAX_PROOF_BYTES)
    return result


def validated_report(raw: bytes) -> dict[str, Any]:
    value = shared.decode(raw, shared.MAX_REPORT_BYTES)
    require(
        set(value)
        == {
            "schema_version",
            "status",
            "mode",
            "tests",
            "passed",
            "failures",
            "errors",
            "skipped",
            "duration_seconds",
            "direct_commands",
            "nested_commands",
            "child_commands",
            "direct_capture_bytes",
            "nested_capture_bound_bytes",
            "cleanup_complete",
            "process_inventory_complete",
            "code",
            "stage",
            "retained_index_sha256",
            "case_results",
        }
    )
    require(
        shared.exact(value["schema_version"], 1)
        and value["mode"] == MODE
        and shared.exact(value["tests"], 6)
        and shared.natural(value["passed"], 6)
        and shared.natural(value["failures"], 1)
        and shared.exact(value["errors"], 0)
        and shared.exact(value["skipped"], 0)
        and shared.natural(value["direct_commands"], MAX_DIRECT)
        and shared.natural(value["nested_commands"], EXPECTED_NESTED)
        and shared.exact(
            value["child_commands"], value["direct_commands"] + value["nested_commands"]
        )
        and value["child_commands"] <= 32
        and shared.natural(value["direct_capture_bytes"], MAX_DIRECT * 2 * shared.MAX_STREAM_BYTES)
        and shared.exact(
            value["nested_capture_bound_bytes"], EXPECTED_NESTED * 2 * shared.MAX_STREAM_BYTES
        )
        and value["direct_capture_bytes"] + value["nested_capture_bound_bytes"]
        <= shared.MAX_CAPTURE_BYTES
        and type(value["cleanup_complete"]) is bool
        and type(value["process_inventory_complete"]) is bool
        and value["code"] in shared.CODES | {"ok"}
        and type(value["stage"]) is str
        and re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", value["stage"]) is not None
        and type(value["duration_seconds"]) in {int, float}
        and 0 <= value["duration_seconds"] <= TOTAL_SECONDS + 5
        and (
            value["retained_index_sha256"] is None
            or (
                type(value["retained_index_sha256"]) is str
                and re.fullmatch(r"[0-9a-f]{64}", value["retained_index_sha256"]) is not None
            )
        )
    )
    passed = value["passed"]
    require(value["case_results"] == [{"name": n, "status": "passed"} for n in CASE_NAMES[:passed]])
    if value["status"] == "passed":
        require(
            passed == 6
            and value["failures"] == 0
            and value["cleanup_complete"] is True
            and value["process_inventory_complete"] is True
            and value["duration_seconds"] <= TOTAL_SECONDS
            and value["code"] == "ok"
            and value["stage"] == "complete"
            and value["direct_commands"] == EXPECTED_DIRECT
            and value["nested_commands"] == EXPECTED_NESTED
            and value["retained_index_sha256"] is not None
        )
    else:
        require(value["status"] == "failed" and value["failures"] == 1 and passed == 0)
    return value


def diagnostic_marker_inventory(work: Path, owner: str) -> dict[str, Any]:
    """Finite observations only; these states never grant cleanup authority."""
    require(re.fullmatch(r"[0-9a-f]{32}", owner) is not None)
    markers: dict[str, Any] = {}
    for name in MARKERS:
        states: dict[str, Any] = {}
        for suffix in ("reached", "released"):
            path = work / (name + "." + suffix)
            state: dict[str, Any] = {"state": "unavailable"}
            try:
                if not path.exists() and not path.is_symlink():
                    state = {"state": "absent"}
                else:
                    raw = shared.bounded_read(path, 16)
                    if re.fullmatch(rb"[1-9][0-9]{0,9}\n", raw) is not None:
                        pid = int(raw[:-1])
                        if 2 <= pid <= 2**31 - 1:
                            state = {"state": "observed", "pid": pid}
            except (GateError, OSError):
                pass
            states[suffix] = state
        markers[name] = states
    return {"schema_version": 1, "owner": owner, "markers": markers}


class ContractRun:
    def __init__(self, root: Path, target: Path) -> None:
        self.root, self.target = root, target
        self.started = time.monotonic()
        self.deadline = self.started + TOTAL_SECONDS - CLEANUP_SECONDS
        self.final = self.started + TOTAL_SECONDS
        self.owner = uuid4().hex
        self.schema = "p1_starter_" + self.owner
        self.artifacts = target.with_name(target.stem + "-artifacts")
        self.artifacts.mkdir(mode=0o700)
        self.commands = self.artifacts / "commands"
        self.commands.mkdir(mode=0o700)
        self.children = shared.Children(
            self.commands, self.deadline, self.final, roles=frozenset(DIRECT_ROLES)
        )
        self.actual = shared.ActualCalls()
        self.steps: dict[str, dict[str, Any]] = {}
        self.worker_pids: dict[str, int] = {}
        self.zero_step_roles: set[str] = set()
        self.work = Path(tempfile.mkdtemp(prefix="p2-starter-p1-", dir="/private/tmp"))
        self.marker = {
            "schema_version": 1,
            "owner": self.owner,
            "schema": self.schema,
            "path": str(self.work),
        }
        try:
            shared.write_private(self.work / "owned-work.json", shared.json_bytes(self.marker))
            shared.write_private(self.artifacts / "owned-work.json", shared.json_bytes(self.marker))
            self.barriers = {name: FileBarrier(self.work, name) for name in MARKERS}
        except BaseException:
            # Constructors above admit no work; this is only our fresh empty scratch.
            shutil.rmtree(self.work)
            raise
        self.stage = "prepare"
        self.before: dict[str, str] = {}
        self.secrets: tuple[bytes, ...] = ()
        self.settings: dict[str, str] = {}
        self.package: dict[str, Any] = {}
        self.python = self.work / "p1-environment/bin/python"
        self.lab_started = self.lab_cleaned = False
        self.proofs: dict[str, Any] = {}
        self.snapshots: dict[str, Any] = {}
        self.suppliers: dict[str, Any] = {}

    def retain(self, name: str, value: Any) -> None:
        raw = shared.json_bytes(value) + b"\n"
        shared.scan_secrets(raw, self.secrets)
        shared.write_private(self.artifacts / name, raw)

    def retain_input(self, name: str) -> dict[str, Any]:
        raw = shared.bounded_read(self.work / name)
        shared.scan_secrets(raw, self.secrets)
        shared.write_private(self.artifacts / name, raw)
        return shared.decode(raw)

    async def finish(self, child: OwnedProcess) -> bytes:
        return await self.actual.call(self.children.finish, child, secrets=self.secrets)

    def start(
        self, role: str, argv: list[str], env: dict[str, str], *, cwd: Path | None = None
    ) -> OwnedProcess:
        require(self.children.count < MAX_DIRECT)
        self.stage = role
        return self.children.start(role, argv, env, cwd=cwd or self.work)

    async def command(self, role: str, argv: list[str], env: dict[str, str]) -> bytes:
        return await self.finish(self.start(role, argv, env))

    def database_env(self, *, owner: bool) -> dict[str, str]:
        prefix = "P1_MIGRATION_" if owner else "P1_POSTGRES_"
        value = {
            **runtime_base(),
            prefix + "HOST": "127.0.0.1",
            prefix + "PORT": self.settings["POSTGRES_PORT"],
            prefix + "DB": "livekit_lab",
            prefix + "USER": "continuity_migrator" if owner else "livekit_lab",
            prefix + "PASSWORD": self.settings[
                "POSTGRES_MIGRATION_PASSWORD" if owner else "POSTGRES_PASSWORD"
            ],
            prefix + "SCHEMA": self.schema,
        }
        shared.validate_environment(
            value,
            required=frozenset(
                prefix + k for k in ("HOST", "PORT", "DB", "USER", "PASSWORD", "SCHEMA")
            ),
        )
        return value

    def fixture_env(self, mode: str) -> dict[str, str]:
        value = {
            **self.database_env(owner=False),
            "P1_STARTER_DIRECTORY": str(self.work),
            "P1_STARTER_INSTALLATION": str(self.python.parent.parent),
            "P1_STARTER_OWNER": self.owner,
        }
        if mode in STEP_ROLES:
            slot = "stale" if mode == "stale-inquiry" else "exact"
            value.update(
                P1_WORKER_SCOPE="p1_starter_" + slot,
                P1_WORKER_SUPPLIER_DB=str(self.work / (slot + "-supplier.sqlite3")),
                P1_WORKER_SINK_DB=str(self.work / (slot + "-completion.sqlite3")),
                P1_WORKER_STATE_FILE=str(self.work / (mode + "-health.json")),
                P1_WORKER_SUPPLIER_MODE="cooperating",
                P1_WORKER_POLL_SECONDS="1",
                P1_WORKER_STEP_SECONDS="15",
                P1_WORKER_DRAIN_SECONDS="5",
                P1_WORKER_OUTPUT_BYTES="8192",
                P1_WORKER_FAILURE_LIMIT="1",
            )
        else:
            value["P1_STARTER_CREDENTIALS"] = str(self.work / "p1-credentials.json")
        shared.validate_environment(value, required=frozenset(value.keys() - shared.BASE_KEYS))
        return value

    async def fixture(self, mode: str, role: str, *, wait: bool = True) -> Any:
        child = self.start(
            role,
            [str(self.python), "-I", str(self.work / "p2_starter_p1.py"), "--mode", mode],
            self.fixture_env(mode),
        )
        if mode in STEP_ROLES:
            self.worker_pids[mode] = child.pid
        if not wait:
            return child
        result = shared.decode(await self.finish(child), 2048)
        require(
            shared.exact(result.get("schemaVersion"), 1)
            and result.get("status") == "passed"
            and result.get("mode") == mode
            and result.get("owner") == self.owner
            and result.get("cleanupComplete") is True
        )
        if mode in STEP_ROLES:
            require(
                set(result)
                == {"schemaVersion", "status", "mode", "owner", "steps", "cleanupComplete"}
            )
            require(shared.exact(result["steps"], 1))
            value = validate_step(
                shared.bounded_read(self.work / (mode + "-settled.json"), 16384),
                role=mode,
                owner=self.owner,
                worker_pid=child.pid,
                executable=self.python,
            )
            require(group_absent(value["steps"][0]["processId"]))
            require(
                all(
                    previous["steps"][0]["processId"] != value["steps"][0]["processId"]
                    for previous in self.steps.values()
                )
            )
            self.steps[mode] = value
            self.retain(mode + "-settled.json", value)
        else:
            require(
                set(result)
                == {"schemaVersion", "status", "mode", "owner", "proofSha256", "cleanupComplete"}
            )
            require(
                type(result["proofSha256"]) is str
                and re.fullmatch(r"[0-9a-f]{64}", result["proofSha256"]) is not None
            )
        return result

    def connect(self) -> Any:
        from continuity_lab.postgres_api import PostgresSettings

        return PostgresSettings(
            host="127.0.0.1",
            port=int(self.settings["POSTGRES_PORT"]),
            dbname="livekit_lab",
            user="continuity_migrator",
            password=self.settings["POSTGRES_MIGRATION_PASSWORD"],
            schema=self.schema,
        ).connect(application_name="continuity-test")

    def schema_absent(self) -> bool:
        with closing(self.connect()) as connection:
            return not connection.execute(
                "SELECT 1 FROM pg_namespace WHERE nspname=%s", (self.schema,)
            ).fetchall()

    async def capture(self, phase: str) -> None:
        require(phase in SNAPSHOT_PHASES and phase not in self.snapshots)
        value = await self.actual.call(owner_snapshot, self.connect, self.schema)
        self.snapshots[phase] = value
        self.retain("owner-" + phase + ".json", value)

    async def suppliers_at(self, phase: str) -> None:
        value = {}
        for slot in ("stale", "exact"):
            value[slot] = await self.actual.call(
                supplier_snapshot, self.work / (slot + "-supplier.sqlite3")
            )
        self.suppliers[phase] = value
        self.retain("supplier-" + phase + ".json", value)

    async def setup(self) -> None:
        self.before = source_snapshot(self.root)
        self.retain("source-before.json", self.before)
        self.package = await self.actual.call(
            shared.prepare_installed, self.root, self.work, self.artifacts, self.children
        )
        ordinary = setup_tools.load_setup(self.root).load_settings()
        self.settings = {
            k: ordinary[k]
            for k in ("POSTGRES_PORT", "POSTGRES_PASSWORD", "POSTGRES_MIGRATION_PASSWORD")
        }
        tokens = [secrets.token_urlsafe(32) for _ in range(6)]
        require(len(set(tokens)) == 6)
        require(
            all(
                16 <= len(self.settings[name]) <= 128
                for name in ("POSTGRES_PASSWORD", "POSTGRES_MIGRATION_PASSWORD")
            )
        )
        self.secrets = tuple(
            v.encode()
            for v in (
                *tokens,
                self.settings["POSTGRES_PASSWORD"],
                self.settings["POSTGRES_MIGRATION_PASSWORD"],
            )
        )
        self.credentials = {
            "schemaVersion": 1,
            "owner": self.owner,
            "p1Tokens": dict(zip(("revision", "stale", "exact"), tokens[:3], strict=True)),
            "bridgeTokens": dict(
                zip(("case", "confirmation", "currentCase"), tokens[3:], strict=True)
            ),
        }
        shared.write_private(self.work / "p1-credentials.json", shared.json_bytes(self.credentials))
        node_credentials = {
            "schemaVersion": 1,
            "role": "p1-contract",
            "caseToken": tokens[3],
            "confirmationToken": tokens[4],
            "currentCaseToken": tokens[5],
        }
        shared.write_private(
            self.work / "node-credentials.json", shared.json_bytes(node_credentials)
        )
        shared.write_private(
            self.work / "ids.json", shared.json_bytes(shared.fixed_ids(self.owner))
        )
        for name in ("p2_starter_p1.py", "p2_case_bridge.py", "p2_current_case_bridge.py"):
            raw = (self.root / "local-setup/scripts" / name).read_bytes()
            shared.write_private(self.work / name, raw)
            shared.write_private(self.artifacts / name, raw)
        uv = str(self.root / ".venv/bin/uv")
        wheels = self.work / "p1-wheel"
        wheels.mkdir(mode=0o700)
        env = shared.offline_environment()
        # uv is explicitly offline; no ambient provider/proxy/python-path selectors.
        await self.command(
            "p1-wheel-build",
            [
                uv,
                "--no-config",
                "build",
                "--no-build-logs",
                "--offline",
                "--no-sources",
                "--python",
                sys.executable,
                "--wheel",
                "--out-dir",
                str(wheels),
                str(self.root / "projects/agent-continuity/python"),
            ],
            env,
        )
        found = list(wheels.glob("*.whl"))
        require(len(found) == 1 and not found[0].is_symlink())
        wheel = found[0]
        member = self.root / "projects/agent-continuity/python"
        expected = {
            p.relative_to(member / "src").as_posix(): p.read_bytes()
            for p in (member / "src/continuity_lab").rglob("*")
            if p.is_file() and p.suffix in {".py", ".typed"}
        }
        require(len(expected) == 77)
        # Retain the bounded candidate before validation so a rejected wheel survives cleanup.
        shared.write_private(self.artifacts / wheel.name, wheel.read_bytes(), 8388608)
        package_tools._wheel(wheel, member, "agent_continuity", expected)
        self.retain(
            "p1-wheel-parity.json",
            {
                "schema_version": 1,
                "runtime_payloads": 77,
                "sha256": digest(wheel.read_bytes()),
                "source": {k: digest(v) for k, v in expected.items()},
            },
        )
        await self.command(
            "p1-environment",
            [
                sys.executable,
                "-I",
                "-m",
                "venv",
                "--without-pip",
                str(self.python.parent.parent),
            ],
            env,
        )
        await self.command(
            "p1-install",
            [
                uv,
                "--no-config",
                "pip",
                "install",
                "--offline",
                "--python",
                str(self.python),
                str(wheel) + "[postgres]",
                "h11==0.16.0",
            ],
            env,
        )
        initial_env = {
            **runtime_base(),
            "P1_STARTER_DIRECTORY": str(self.work),
            "P1_STARTER_INSTALLATION": str(self.python.parent.parent),
            "P1_STARTER_OWNER": self.owner,
        }
        raw = await self.command(
            "p1-sqlite-init",
            [
                str(self.python),
                "-I",
                str(self.work / "p2_starter_p1.py"),
                "--mode",
                "init-source",
            ],
            initial_env,
        )
        require(
            shared.exact(
                shared.decode(raw),
                {
                    "schemaVersion": 1,
                    "status": "passed",
                    "mode": "init-source",
                    "owner": self.owner,
                    "cleanupComplete": True,
                },
            )
        )
        require(await self.actual.call(self.schema_absent))
        self.lab_started = True
        await self.command(
            "p1-cutover",
            [
                str(self.python),
                "-I",
                "-m",
                "continuity_lab.postgres_cli",
                "cutover",
                "--source",
                str(self.work / "source.sqlite3"),
                "--backup",
                str(self.work / "cutover-backup.sqlite3"),
            ],
            self.database_env(owner=True),
        )
        for role, command in (
            ("p1-upgrade-cases", "upgrade"),
            ("p1-upgrade-effects", "upgrade-effects"),
            ("p1-upgrade-work", "upgrade-coordination"),
        ):
            await self.command(
                role,
                [
                    str(self.python),
                    "-I",
                    "-m",
                    "continuity_lab.postgres_cli",
                    command,
                ],
                self.database_env(owner=True),
            )
        for slot in ("stale", "exact"):
            value = self.fixture_env(slot + "-inquiry")
            # This is the supported public initializer, not a hidden worker step.
            raw = await self.command(
                "p1-" + slot + "-supplier-init",
                [
                    str(self.python),
                    "-I",
                    "-m",
                    "continuity_lab.worker_cli",
                    "init-fixtures",
                ],
                {k: v for k, v in value.items() if not k.startswith("P1_STARTER_")},
            )
            require(shared.decode(raw)["status"] == "fixtures_ready")
        await self.suppliers_at("initial")
        await self.fixture("seed", "p1-seed")
        self.originals = self.retain_input("p1-originals.json")

    def node_config(self, phase: str) -> Path:
        slot = (
            "revision"
            if phase == "revision"
            else "stale"
            if phase == "stale-confirmation"
            else "exact"
        )
        original = self.originals["slots"][slot]
        fixtures = {
            "originalRequest": request({"revision": "02", "stale": "03", "exact": "04"}[slot]),
            "expectedTaskId": original["task_id"],
            "authorityCaseId": original["case_id"],
        }
        if phase == "revision":
            fixtures.update(knownRequest=request("03"), unknownReplyRequest=request("04"))
        elif phase in {"stale-confirmation", "exact-confirmation"}:
            quote = self.quotes[slot]
            fixtures["confirmation"] = {
                "scope": {"tenantId": "tenant_starter_p1", "accountId": "account_starter_" + slot},
                "caseId": "case_starter_" + self.owner + "_" + slot,
                "commandId": str(uuid4()),
                "expectedRevision": "0",
                "quoteId": quote["quoteId"],
                "quoteDigest": quote["quoteDigest"],
                "quoteJson": quote["quoteJson"],
                "explicit": True,
            }
            if phase == "stale-confirmation":
                fixtures["revisedRequest"] = request("04")
        else:
            fixtures["expectedSupplier"] = {
                "bookingReference": "DEMO-BK-001",
                "newCheckIn": "2030-12-04",
                "revision": "1",
            }
        value = {
            "schemaVersion": 1,
            "mode": "p1-contract",
            "phase": phase,
            "owner": self.owner,
            "scope": {"tenantId": "tenant_starter_p1", "accountId": "account_starter_" + slot},
            "caseId": "case_starter_" + self.owner + "_" + slot,
            "conversationId": "conversation_starter_" + self.owner + "_" + slot,
            "endpoints": self.endpoints["endpoints"],
            "fixtures": fixtures,
        }
        path = self.work / ("config-" + phase + ".json")
        shared.write_private(path, shared.json_bytes(value))
        self.retain("config-" + phase + ".json", value)
        return path

    def node(self, phase: str) -> OwnedProcess:
        require(phase in PHASES)
        config = self.node_config(phase)
        env = {
            **runtime_base(),
            "P2_STARTER_MODE": "p1-contract",
            "P2_STARTER_OWNER": self.owner,
            "P2_STARTER_WORK": str(self.work),
            "P2_STARTER_IDS": str(self.work / "ids.json"),
            "P2_STARTER_CONFIG": str(config),
            "P2_STARTER_CREDENTIALS": str(self.work / "node-credentials.json"),
            "P2_STARTER_OUTPUT": str(self.work / ("phase-" + phase + ".json")),
        }
        shared.validate_environment(env, required=frozenset(env.keys() - shared.BASE_KEYS))
        label = {
            "stale-confirmation": "stale",
            "exact-confirmation": "exact",
            "current-facts": "current",
        }.get(phase, phase)
        return self.start(
            "p1-" + label + "-consumer",
            [
                str(self.package["node"]),
                str(self.package["consumer"] / "dist/consumer.js"),
            ],
            env,
            cwd=self.package["consumer"],
        )

    async def finish_node(self, phase: str, child: OwnedProcess) -> None:
        summary = shared.decode(await self.finish(child), 2048)
        require(
            shared.exact(
                summary,
                {
                    "schemaVersion": 1,
                    "status": "passed",
                    "mode": "p1-contract",
                    "cleanupComplete": True,
                },
            )
        )
        self.proofs[phase] = self.retain_input("phase-" + phase + ".json")

    async def barrier(self, child: OwnedProcess, name: str) -> None:
        await self.actual.call(
            child.wait_for_barrier,
            self.barriers[name],
            timeout=min(10, shared.remaining(self.deadline)),
        )

    async def journey(self) -> None:
        await self.setup()
        self.quotes: dict[str, Any] = {}
        server = await self.fixture("serve", "p1-bridges", wait=False)
        await self.barrier(server, "p1_ready")
        self.endpoints = self.retain_input("p1-endpoints.json")
        require(
            self.endpoints.get("schemaVersion") == 1
            and self.endpoints.get("owner") == self.owner
            and shared.exact(self.endpoints.get("pid"), server.pid)
            and set(self.endpoints.get("endpoints", {})) == {"case", "confirmation", "currentCase"}
        )
        ports = []
        for endpoint in self.endpoints["endpoints"].values():
            require(
                type(endpoint) is dict
                and set(endpoint) == {"host", "port"}
                and endpoint["host"] == "127.0.0.1"
                and shared.natural(endpoint["port"], 65535, 1)
            )
            ports.append(endpoint["port"])
        require(len(set(ports)) == 3)
        await self.capture("before_zero")
        revision = self.node("revision")
        await self.barrier(revision, "p1_zero_read_done")
        await self.capture("after_zero")
        require(shared.exact(self.snapshots["before_zero"], self.snapshots["after_zero"]))
        revision.release_barrier(self.barriers["p1_zero_read_done"])
        await self.barrier(server, "p1_revision_committed")
        await self.barrier(revision, "p1_revision_unknown")
        server.release_barrier(self.barriers["p1_revision_committed"])
        await self.finish_node("revision", revision)
        for slot in ("stale", "exact"):
            await self.fixture(slot + "-inquiry", "p1-" + slot + "-inquiry")
            await self.fixture("prepare-" + slot + "-quote", "p1-" + slot + "-quote")
            self.quotes[slot] = self.retain_input("p1-" + slot + "-quote.json")
            phase = slot + "-confirmation"
            child = self.node(phase)
            await self.finish_node(phase, child)
        await self.fixture("exact-mutation", "p1-exact-mutation")
        await self.capture("before_final_read")
        await self.suppliers_at("before_final")
        current = self.node("current-facts")
        await self.finish_node("current-facts", current)
        await self.fixture("verify", "p1-public-final-verify")
        projections = self.retain_input("p1-public-projections.json")
        await self.capture("after_final_read")
        await self.suppliers_at("after_final")
        server.release_barrier(self.barriers["p1_stop"])
        terminal = shared.decode(await self.finish(server), 2048)
        require(
            shared.exact(
                terminal,
                {
                    "schemaVersion": 1,
                    "status": "passed",
                    "mode": "serve",
                    "owner": self.owner,
                    "cleanupComplete": True,
                },
            )
        )
        closed = self.retain_input("p1-bridge-closed.json")
        require(
            set(closed)
            == {
                "schemaVersion",
                "owner",
                "pid",
                "endpoints",
                "bridgeMetrics",
                "factoryPending",
                "clients",
                "clientsClosed",
                "cleanupComplete",
            }
        )
        require(
            shared.exact(closed["schemaVersion"], 1)
            and closed["owner"] == self.owner
            and shared.exact(closed["pid"], server.pid)
            and shared.exact(closed["endpoints"], self.endpoints["endpoints"])
            and closed["cleanupComplete"] is True
            and shared.exact(closed["factoryPending"], 0)
            and shared.exact(closed["clients"], 9)
            and shared.exact(closed["clientsClosed"], 9)
        )
        require(type(closed["bridgeMetrics"]) is list and len(closed["bridgeMetrics"]) == 3)
        for index, metrics in enumerate(closed["bridgeMetrics"]):
            keys = {"known", "telemetry_failed", "active_requests", "sockets"}
            keys |= {"unavailable"} if index == 2 else {"rejected", "unknown"}
            require(type(metrics) is dict and set(metrics) == keys)
            require(all(shared.natural(v, 9007199254740991) for v in metrics.values()))
            require(
                metrics["known"] > 0
                and shared.exact(metrics["active_requests"], 0)
                and shared.exact(metrics["sockets"], 0)
            )
        require(self.children.count == EXPECTED_DIRECT and len(self.steps) == EXPECTED_NESTED)
        bundle = {
            "schema_version": 1,
            "owner": self.owner,
            "originals": self.originals,
            "phases": self.proofs,
            "quotes": self.quotes,
            "public_projections": projections,
            "snapshots": self.snapshots,
            "suppliers": self.suppliers,
            "steps": [self.steps[k] for k in STEP_ROLES],
        }
        self.stage = "proof"
        import p2_starter_p1_evidence as evidence

        verdict = evidence.validate_bundle(bundle, owner=self.owner)
        self.retain("p1-adapter-bundle.json", bundle)
        self.retain("p1-adapter-verdict.json", verdict)
        require(source_snapshot(self.root) == self.before)
        self.retain("source-after.json", source_snapshot(self.root))

    def cleanup_schema(self) -> None:
        if not self.lab_started or self.lab_cleaned:
            return
        require(self.children.all_settled())
        for role, outer_pid in self.worker_pids.items():
            require(
                role in self.zero_step_roles
                or (role in self.steps and group_absent(self.steps[role]["steps"][0]["processId"]))
            )
            require(group_absent(outer_pid))
        from psycopg import sql

        with closing(self.connect()) as connection:
            rows = connection.execute(
                "SELECT pg_get_userbyid(nspowner) AS owner FROM pg_namespace WHERE nspname=%s",
                (self.schema,),
            ).fetchall()
            if rows:
                require(rows == [{"owner": "continuity_migrator"}])
                with connection.transaction():
                    connection.execute(
                        sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema))
                    )
        require(self.schema_absent())
        self.lab_cleaned = True

    def retain_phase_failures(self) -> None:
        # Successful phase proofs were already retained by finish_node. Only
        # these four fixed, finite failure records can cross during cleanup.
        for phase in PHASES:
            if phase in self.proofs:
                continue
            name = "phase-" + phase + ".json"
            path = self.work / name
            if not path.exists() and not path.is_symlink():
                continue
            raw = shared.bounded_read(path, 2048)
            shared.validate_actor_failure(raw, "p1-contract")
            shared.scan_secrets(raw, self.secrets)
            shared.write_private(self.artifacts / name, raw, 2048)

    async def cleanup(self) -> bool:
        self.actual.closing = True
        # All admitted blocking calls have finite IO/command observations. Drain
        # them before concurrently touching their owned process handles.
        drained = await self.actual.drain(max(time.monotonic(), self.final - 10))
        owners_closed = True
        if drained:
            capture_deadline = min(self.final - 5, time.monotonic() + CLEANUP_SECONDS - 5)
            for child in self.children.children:
                # returncode only polls this registered owner. A live held
                # child must go directly to bounded close, never a join wait.
                if child.returncode is None or shared.settled(child):
                    continue
                try:
                    await self.actual.cleanup_call(
                        child.wait,
                        timeout=min(2, shared.remaining(capture_deadline)),
                    )
                except BaseException:  # noqa: BLE001 - Still attempt every independent close.
                    owners_closed = False
        try:
            await asyncio.to_thread(self.children.close)
        except BaseException:  # noqa: BLE001 - Still inspect every registered owner below.
            owners_closed = False
        for child in self.children.children:
            try:
                self.children.capture(child, secrets=self.secrets)
            except BaseException:  # noqa: BLE001 - Capture failure cannot skip another owner.
                owners_closed = False
        if not drained or not owners_closed or not self.children.all_settled():
            return False
        # The test observer records its handle before markers. A missing or bad
        # receipt is unknown, never permission to signal a guessed nested PID.
        for role, outer_pid in self.worker_pids.items():
            if role not in self.steps:
                try:
                    raw = shared.bounded_read(self.work / (role + "-settled.json"), 16384)
                    value = shared.decode(raw, 16384)
                    empty = {
                        "schemaVersion": 1,
                        "owner": self.owner,
                        "workerProcessId": outer_pid,
                        "steps": [],
                        "cleanupComplete": True,
                    }
                    if shared.exact(value, empty):
                        require(not (self.work / (role + "-started.json")).exists())
                        self.zero_step_roles.add(role)
                    else:
                        value = validate_step(
                            raw,
                            role=role,
                            owner=self.owner,
                            worker_pid=outer_pid,
                            executable=self.python,
                        )
                        require(group_absent(value["steps"][0]["processId"]))
                        self.steps[role] = value
                except BaseException:  # noqa: BLE001 - Unknown nested ownership retains all dependent state.
                    return False
            require(group_absent(outer_pid))
        self.retain(
            "p1-diagnostic-markers.json", diagnostic_marker_inventory(self.work, self.owner)
        )
        self.retain_phase_failures()
        shared.private_directory(self.work)
        require(
            shared.exact(
                shared.decode(shared.bounded_read(self.work / "owned-work.json")), self.marker
            )
        )
        if self.lab_started:
            await self.actual.cleanup_call(self.cleanup_schema)
        if not await self.actual.close(self.final):
            return False
        require(all(group_absent(v["steps"][0]["processId"]) for v in self.steps.values()))
        # Credential files never enter retained artifacts. Remove work only after
        # complete owner, nested session and schema closure.
        shared.private_directory(self.work)
        require(
            shared.exact(
                shared.decode(shared.bounded_read(self.work / "owned-work.json")), self.marker
            )
        )
        shutil.rmtree(self.work)
        return not self.work.exists() and (not self.lab_started or self.lab_cleaned)


def request(day: str) -> dict[str, Any]:
    require(day in {"02", "03", "04"})
    return {
        "schemaVersion": 1,
        "kind": "booking_investigation",
        "bookingReference": "DEMO-BK-001",
        "newCheckIn": "2030-12-" + day,
        "investigationConsent": True,
    }


async def execute(root: Path, target: Path) -> dict[str, Any]:
    run = ContractRun(root, target)
    primary: BaseException | None = None
    cleanup = False
    index_sha: str | None = None
    try:
        async with asyncio.timeout_at(run.deadline):
            await run.journey()
    except BaseException as error:  # noqa: BLE001 - Primary survives all independent cleanup tiers.
        primary = error
    try:
        async with asyncio.timeout_at(run.final):
            cleanup = await run.cleanup()
    except BaseException as error:  # noqa: BLE001 - Retain private work on incomplete ownership.
        if primary is None:
            primary = error
    try:
        run.retain(
            "owned-children.json",
            {
                "schema_version": 1,
                "cleanup_complete": cleanup,
                "children": [
                    {"pid": c.pid, "returncode": c.returncode, "settled": shared.settled(c)}
                    for c in run.children.children
                ],
                "nested": list(run.steps.values()),
                "process_inventory_complete": all(
                    r in run.steps or r in run.zero_step_roles for r in run.worker_pids
                )
                and not run.children.start_failed,
            },
        )
        if primary is not None or not cleanup:
            run.retain(
                "failure-context.json",
                {
                    "schema_version": 1,
                    "stage": run.stage,
                    "work": str(run.work),
                    "schema": run.schema,
                    "lab_started": run.lab_started,
                    "lab_cleaned": run.lab_cleaned,
                    "cleanup_complete": cleanup,
                },
            )
        inventory = shared.retained_inventory(run.artifacts)
        raw = shared.json_bytes(inventory)
        shared.write_private(run.artifacts / "retained-index.json", raw)
        shared.validate_retained_index(run.artifacts, raw)
        index_sha = digest(raw)
    except BaseException as error:  # noqa: BLE001 - Index failure never erases primary.
        if primary is None:
            primary = error
    code = (
        "ok"
        if primary is None and cleanup
        else (primary.code if isinstance(primary, GateError) else "gate_failed")
    )
    if primary is None and not cleanup:
        code = "cleanup_incomplete"
    passed = 6 if code == "ok" else 0
    value = {
        "schema_version": 1,
        "status": "passed" if passed == 6 else "failed",
        "mode": MODE,
        "tests": 6,
        "passed": passed,
        "failures": int(passed != 6),
        "errors": 0,
        "skipped": 0,
        "duration_seconds": time.monotonic() - run.started,
        "direct_commands": run.children.count,
        "nested_commands": len(run.steps),
        "child_commands": run.children.count + len(run.steps),
        "direct_capture_bytes": run.children.captured,
        "nested_capture_bound_bytes": EXPECTED_NESTED * 2 * shared.MAX_STREAM_BYTES,
        "cleanup_complete": cleanup,
        "process_inventory_complete": all(
            r in run.steps or r in run.zero_step_roles for r in run.worker_pids
        )
        and not run.children.start_failed,
        "code": code,
        "stage": "complete" if passed == 6 else run.stage,
        "retained_index_sha256": index_sha,
        "case_results": [{"name": n, "status": "passed"} for n in CASE_NAMES[:passed]],
    }
    validated_report(shared.json_bytes(value))
    return value


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    started = time.monotonic()
    target = None
    try:
        parser = shared.SafeParser(description=__doc__)
        parser.add_argument("--plan", action="store_true")
        parser.add_argument("--report", type=Path)
        args = parser.parse_args(argv)
        if args.plan:
            print(shared.json_bytes(plan()).decode())
            return 0
        target = shared.target_path(
            root,
            args.report or Path(".local/validation/p2-starter-p1/" + uuid4().hex + ".json"),
            p1_contract=True,
        )
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shared.private_directory(target.parent)
        result = asyncio.run(execute(root, target))
    except BaseException as error:  # noqa: BLE001 - Closed body-free CLI failure.
        result = {
            "schema_version": 1,
            "status": "failed",
            "mode": MODE,
            "tests": 6,
            "passed": 0,
            "failures": 1,
            "errors": 0,
            "skipped": 0,
            "duration_seconds": time.monotonic() - started,
            "direct_commands": 0,
            "nested_commands": 0,
            "child_commands": 0,
            "direct_capture_bytes": 0,
            "nested_capture_bound_bytes": EXPECTED_NESTED * 2 * shared.MAX_STREAM_BYTES,
            "cleanup_complete": False,
            "process_inventory_complete": True,
            "code": error.code if isinstance(error, GateError) else "gate_failed",
            "stage": "input",
            "retained_index_sha256": None,
            "case_results": [],
        }
    raw = shared.json_bytes(result) + b"\n"
    validated_report(raw)
    if target is not None:
        shared.write_private(target, raw, shared.MAX_REPORT_BYTES)
    sys.stdout.buffer.write(raw)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
