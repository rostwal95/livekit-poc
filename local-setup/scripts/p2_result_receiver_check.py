"""Selected actual P2 receiver/P3 return qualification; --plan starts no resources."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT))
import p2_native_check as native
import p2_rehydration_check as prior
import p2_standalone_check as starter
import p3_coordinator_check as core
import p3_document_evidence as evidence
from p3_document_package import GroupedOwnedProcess

from harness.process_control import OwnedProcess, ProcessTimeout

GateError = evidence.GateError
CASES = (
    "populated_v7_upgrade_preserves_original_bytes",
    "interrupted_upgrade_rolls_back",
    "repeat_upgrade_and_old_api_compatibility",
    "populated_backup_restore_and_capacity_denial",
    "atomic_original_receipt_and_notice",
    "concurrent_exact_replay_zero_writes",
    "changed_foreign_and_ordinary_uuid_collision_denied",
    "opaque_result_and_notice_bounds",
    "original_replay_and_current_read_at_capacity",
    "owned_receiver_commit_ack_loss_and_fresh_lookup",
    "receiver_history_survives_native_revocation",
    "fresh_b_scope_and_public_p1_current_case",
    "revocation_between_external_read_and_disclosure_denied",
    "expiry_after_observed_protected_lock_wait_denied",
    "held_read_retains_actual_capacity_without_sql_transaction",
    "incomplete_close_retry_and_useful_current_progress",
)
JOIN_CASES = (
    "v2_actual_p1_possible_delivery_lookup_only_reconciliation",
    "original_result_receipt_historical_after_actual_case_revision",
    "outdated_undelivered_result_denied_before_intent",
    "explicit_current_result_reaches_same_conversation_b_read",
)
COMMANDS = (
    "compile-public",
    "compile-fixture",
    "setup",
    "upgrade",
    "exercise",
    "commit-before-ack",
    "recover",
    "serve",
    "p3-consumer",
    "backup-container",
    "backup-dump",
    "backup-copy",
    "backup-restore",
    "restore-check",
    "cleanup",
    "backup-remove",
)
ROLES = {
    "setup",
    "upgrade",
    "exercise",
    "commit-before-ack",
    "recover",
    "serve",
    "restore-check",
    "cleanup",
}
CAPABILITIES = {
    "ACCOUNT_TOKEN",
    "NATIVE_PUBLISHER_TOKEN",
    "PUBLISHER_TOKEN",
    "NATIVE_A_BEARER",
    "NATIVE_B_BEARER",
    "NATIVE_REVOKE_BEARER",
    "NATIVE_EXPIRE_BEARER",
}
NODE_VERSION = "v24.22.2"
PYTHON_VERSION = (3, 14, 10)


def plan() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "planned",
        "storage_assertions": list(CASES),
        "return_assertions": list(JOIN_CASES),
        "commands": list(COMMANDS),
        "public_compile_profiles": ["production", "examples", "starter"],
        "max_process_groups": 16,
        "deadline_seconds": 180,
        "cleanup_seconds": 20,
        "stream_bytes": 65536,
        "aggregate_capture_bytes": 2097152,
        "max_p2_schemas": 2,
        "max_p1_schemas": 2,
        "owned_sigkills": 1,
        "p3_work_results": 3,
        "p3_receiver_acceptances": 2,
        "carrier_calls": 0,
        "rtc_rooms": 0,
        "provider_calls": False,
        "private_provider_config_reads": False,
        "specialist": "local scripted supplied port; no specialist HTTP/model claim",
        "python_version": "3.14.10",
        "node_version": NODE_VERSION[1:],
        "private_work": "projects/channel-continuity/.local/result-receiver-check/run-*",
        "backup_authority": "exact per-run PGAPPNAME; no DDL or file removal while unresolved",
    }


def load(path: Path, maximum: int = 262144) -> dict[str, Any]:
    value = json.loads(evidence.read_private(path, maximum), object_pairs_hook=core.unique_object)
    if type(value) is not dict:
        raise GateError("invalid_proof")
    return cast(dict[str, Any], value)


def save(path: Path, value: object) -> None:
    evidence.write_private(path, evidence.json_bytes(value))


def source_snapshot(root: Path) -> dict[str, str]:
    result = prior.source_snapshot(root)
    paths = [
        *(
            root / "projects/channel-continuity" / name
            for name in (
                "tsconfig.json",
                "tsconfig.examples.json",
                "tsconfig.starter.json",
                "tsconfig.pg.json",
                "tsconfig.test.json",
            )
        ),
        *sorted((root / "projects/channel-continuity/examples").rglob("*.ts")),
        *sorted(
            (root / "projects/delegation-reliability/python/src/delegation_reliability").glob(
                "*.py"
            )
        ),
        root / "projects/channel-continuity/tests/pg_result_receiver_cases.ts",
        root / "projects/channel-continuity/tests/fixture-work.ts",
        root / "contracts/delegation/result-receiver-v1.json",
        root / "contracts/delegation/fixed-policy-v2.json",
        *(
            root / "local-setup/scripts" / name
            for name in (
                "p2_result_receiver_check.py",
                "p2_standalone_check.py",
                "p3_result_return_cases.py",
                "p3_channel_receiver.py",
                "p2_result_receiver_evidence.py",
                "p3_document_package.py",
                "p3_document_evidence.py",
            )
        ),
    ]
    for path in paths:
        result[path.relative_to(root).as_posix()] = hashlib.sha256(
            prior.source_bytes(path)
        ).hexdigest()
    return dict(sorted(result.items()))


def child_environment(
    values: dict[str, str],
    common: dict[str, str],
    tokens: dict[str, str],
    mode: str,
) -> dict[str, str]:
    if mode not in ROLES:
        raise GateError("invalid_environment")
    required = {
        "P2_RESULT_SCHEMA",
        "P2_RESULT_DIRECTORY",
        "P2_RESULT_PG_PORT",
        "P2_RESULT_SHARED_FIXTURE",
        "P2_RESULT_CASE_AUTHORIZATION",
    }
    if set(common) != required or set(tokens) != {"P2_RESULT_" + k for k in CAPABILITIES}:
        raise GateError("invalid_environment")
    result = {**core.base_environment(), **common, **tokens}
    if mode in {"setup", "upgrade", "cleanup"}:
        result["P2_RESULT_OWNER_PASSWORD"] = values["POSTGRES_MIGRATION_PASSWORD"]
    if mode not in {"upgrade", "cleanup"}:
        # Setup also seeds an old reply through the restricted public runtime.
        result["P2_RESULT_RUNTIME_PASSWORD"] = values["POSTGRES_PASSWORD"]
    validate_child_environment(result, mode)
    return result


def validate_child_environment(environment: dict[str, str], mode: str) -> None:
    """Closed role sets; setup also needs the public runtime to seed history."""
    if mode not in ROLES:
        raise GateError("invalid_environment")
    common = {
        "P2_RESULT_SCHEMA",
        "P2_RESULT_DIRECTORY",
        "P2_RESULT_PG_PORT",
        "P2_RESULT_SHARED_FIXTURE",
        "P2_RESULT_CASE_AUTHORIZATION",
        *("P2_RESULT_" + name for name in CAPABILITIES),
    }
    credentials = set()
    if mode in {"setup", "upgrade", "cleanup"}:
        credentials.add("P2_RESULT_OWNER_PASSWORD")
    if mode not in {"upgrade", "cleanup"}:
        credentials.add("P2_RESULT_RUNTIME_PASSWORD")
    if (
        not (common | credentials) <= environment.keys()
        or set(environment) - common - credentials - core.BASE_ENVIRONMENT_KEYS
        or any(type(v) is not str or not v or len(v) > 4096 for v in environment.values())
        or re.fullmatch(r"p2_result_[0-9a-f]{32}", environment.get("P2_RESULT_SCHEMA", "")) is None
        or re.fullmatch(r"[1-9][0-9]{0,4}", environment.get("P2_RESULT_PG_PORT", "")) is None
        or not 1 <= int(environment["P2_RESULT_PG_PORT"]) <= 65535
        or not Path(environment["P2_RESULT_DIRECTORY"]).is_absolute()
        or not Path(environment["P2_RESULT_SHARED_FIXTURE"]).is_absolute()
        or re.fullmatch(r"Bearer [A-Za-z0-9_-]{43}", environment["P2_RESULT_CASE_AUTHORIZATION"])
        is None
        or any(
            re.fullmatch(r"[A-Za-z0-9_-]{43}", environment["P2_RESULT_" + name]) is None
            for name in CAPABILITIES
        )
        or any(not 32 <= len(environment[name]) <= 128 for name in credentials)
    ):
        raise GateError("invalid_environment")


class Children(native.Children):
    """Existing capture/closure API with the maintained process-group owner."""

    def __init__(self, work: Path, deadline: float, final: float) -> None:
        super().__init__(work, deadline)
        self.final = final
        self._names: set[str] = set()
        self._accounted: set[int] = set()

    def start(
        self,
        name: str,
        argv: list[str],
        environment: dict[str, str],
        *,
        cwd: Path,
    ) -> GroupedOwnedProcess:
        if name not in COMMANDS or name in self._names or self.count >= len(COMMANDS):
            raise GateError("child_budget")
        if not argv or not Path(argv[0]).is_absolute():
            raise GateError("invalid_input")
        native.remaining(self.deadline)
        child = GroupedOwnedProcess(
            argv,
            cwd=cwd,
            env=environment,
            output_directory=self.work / name,
            max_output_bytes=65536,
            final_deadline=self.final,
        )
        self.children.append(child)
        self._names.add(name)
        self.count += 1
        return child

    def account(self, child: OwnedProcess) -> tuple[bytes, bytes]:
        stdout, stderr = core.CaptureBudget.read(child.output_directory, 65536)
        if id(child) not in self._accounted:
            self._accounted.add(id(child))
            self.captured += len(stdout) + len(stderr)
        if self.captured > 2097152:
            raise GateError("unsafe_capture")
        return stdout, stderr

    def finish(
        self,
        child: OwnedProcess,
        *,
        deadline: float | None = None,
        require_zero: bool = True,
        accepted_codes: tuple[int, ...] | None = None,
    ) -> bytes:
        result = child.wait(timeout=min(120, native.remaining(deadline or self.deadline)))
        child.close()
        stdout, _ = self.account(child)
        if (
            not isinstance(child, GroupedOwnedProcess)
            or not child.group_settled
            or child.cleanup_failed
        ):
            raise GateError("cleanup_incomplete")
        allowed = (
            accepted_codes
            if accepted_codes is not None
            else ((0,) if require_zero else (0, -signal.SIGTERM))
        )
        if result.returncode not in allowed:
            raise GateError("component_failed")
        return stdout

    def wait_json(
        self, child: GroupedOwnedProcess, path: Path, *, timeout: float
    ) -> dict[str, Any]:
        end = min(self.deadline, time.monotonic() + timeout)
        while True:
            if child.returncode is not None:
                self.finish(child)
                raise GateError("component_failed")
            if path.exists():
                value = load(path)
                if child.returncode is not None:
                    raise GateError("component_failed")
                return value
            seconds = end - time.monotonic()
            if seconds <= 0:
                raise ProcessTimeout("Owned marker observation exceeded its deadline")
            try:
                child.wait(timeout=min(0.02, seconds))
            except ProcessTimeout:
                continue

    def close(self) -> None:
        failed = False
        for child in reversed(self.children):
            try:
                if id(child) not in self._accounted:
                    if child.returncode is None:
                        child.kill(timeout=min(3, native.remaining(self.final)))
                    else:
                        child.wait(timeout=min(3, native.remaining(self.final)))
                child.close()
                self.account(child)
                failed |= (
                    not isinstance(child, GroupedOwnedProcess)
                    or not child.group_settled
                    or child.cleanup_failed
                    or type(child.returncode) is not int
                )
            except Exception:  # noqa: BLE001 - attempt all independent owned groups.
                failed = True
        if failed:
            raise GateError("cleanup_incomplete")

    def settled(self) -> bool:
        return all(
            isinstance(c, GroupedOwnedProcess)
            and c.group_settled
            and not c.cleanup_failed
            and type(c.returncode) is int
            for c in self.children
        )

    def kill_owned(self, child: GroupedOwnedProcess) -> dict[str, Any]:
        outcome = child.kill(timeout=min(3, native.remaining(self.deadline)))
        child.close()
        out, err = self.account(child)
        if outcome.returncode != -signal.SIGKILL or not outcome.killed or out or err:
            raise GateError("invalid_proof")
        if child.cleanup_failed or not child.group_settled:
            raise GateError("cleanup_incomplete")
        return {"pid": child.pid, "returncode": outcome.returncode, "group_settled": True}


def node_argv(node: str, script: Path, *arguments: str) -> list[str]:
    """Pin the actual existing Node command without adding a hidden probe group."""
    code = (
        f"if(process.version!=={json.dumps(NODE_VERSION)})process.exit(2);"
        "import(require('node:url').pathToFileURL(process.argv[1]).href)"
        ".catch(()=>process.exitCode=1)"
    )
    return [node, "--eval", code, str(script), *arguments]


def retain(source: Path, target: Path, exclusions: tuple[str, ...], maximum: int = 2097152) -> None:
    raw = evidence.read_private(source, maximum, empty=True)
    if any(v.encode() in raw for v in exclusions if v):
        raise GateError("unsafe_capture")
    if target.exists():
        if evidence.read_private(target, maximum, empty=True) != raw:
            raise GateError("invalid_artifact")
        return
    evidence.write_private(target, raw)


def public_build_command(
    root: Path, work: Path, artifacts: Path, node: str, compiler: Path
) -> list[str]:
    """Build the exact public source/examples/declarations in one owned group.

    Runtime parity still independently checks emitted bytes. Derivative compiler
    configs and build-info files belong to this run, never a prior shared cache.
    """
    configs = starter.build_configurations(root, work)
    save(
        artifacts / "compiler-configurations.json",
        {path.name: load(path, 16384) for path in configs},
    )
    return node_argv(node, compiler, "--build", "--force", *(str(path) for path in configs))


async def run(root: Path, artifacts: Path, state: dict[str, Any]) -> dict[str, Any]:
    import aiohttp
    import psycopg
    from p2_rehydration_p1 import P1ReadFixture
    from p2_result_receiver_evidence import validate_bundle, validate_restore
    from psycopg import sql

    from continuity_lab.work_api import PostgresSettings
    from continuity_lab.work_schema import validate_work_schema

    started = time.monotonic()
    final, deadline = started + 180, started + 160
    state["stage"] = "preflight"
    if any(os.environ.get(k) for k in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE")):
        raise GateError("invalid_environment")
    setup = core.load_setup(root)
    values = setup.load_settings()
    node, docker = shutil.which("node"), shutil.which("docker")
    project = root / "projects/channel-continuity"
    compiler = project / "node_modules/typescript/bin/tsc"
    if (
        not node
        or not docker
        or not compiler.is_file()
        or sys.version_info[:3] != PYTHON_VERSION
        or sys.flags.optimize
    ):
        raise GateError("missing_setup")
    node, docker = str(Path(node).absolute()), str(Path(docker).absolute())
    python = str(Path(sys.executable).absolute())
    run_id = uuid4().hex
    schema, work_schema = "p2_result_" + run_id, "p1_work_result_" + run_id
    scratch = project / ".local/result-receiver-check"
    evidence.private_directory(scratch)
    work = Path(tempfile.mkdtemp(prefix="run-", dir=scratch)).resolve()
    os.chmod(work, 0o700)
    state["work"] = str(work)
    children = Children(work, deadline, final)
    scope = {"tenantId": "result_tenant", "accountId": "result_account"}
    reference = {"scope": scope, "caseId": "result_case", "conversationId": "result_conversation"}
    p1 = P1ReadFixture(values, work, reference)
    backup_path = "/tmp/p2-result-" + run_id + ".sql"
    backup_apps = {kind: "p2_result_" + run_id + "_" + kind for kind in ("dump", "restore")}
    registration = {
        "schema_version": 1,
        "run_id": run_id,
        "owner": "continuity_migrator",
        "p2_schema": schema,
        "work_schema": work_schema,
        "case_schema": p1.runtime.schema,
        "work_directory": str(work),
        "backup_path": backup_path,
        "backup_applications": backup_apps,
    }
    save(work / "ownership.json", registration)
    save(artifacts / "ownership.json", registration)
    tokens = {"P2_RESULT_" + name: secrets.token_urlsafe(32) for name in CAPABILITIES}
    exclusions = tuple(values[k] for k in setup.SECRET_KEYS) + tuple(tokens.values()) + (p1.token,)
    source_before = source_snapshot(root)
    save(artifacts / "source-before.json", source_before)
    save(artifacts / "plan.json", plan())
    common: dict[str, str] = {}
    script = work / "compiled/tests/pg_result_receiver_cases.js"
    container = ""
    owned_work = backup_possible = False
    backup_started: set[str] = set()
    backup_completed: set[str] = set()
    original_m1: dict[str, Any] | None = None
    before: dict[str, Any] | None = None

    def registered() -> None:
        if not evidence.exact(load(work / "ownership.json"), registration):
            raise GateError("invalid_proof")
        if (
            re.fullmatch(r"p2_result_[0-9a-f]{32}", schema) is None
            or re.fullmatch(r"p1_work_result_[0-9a-f]{32}", work_schema) is None
            or re.fullmatch(r"p3_completion_[0-9a-f]{32}", p1.runtime.schema) is None
            or schema[-32:] != run_id
            or work_schema[-32:] != run_id
        ):
            raise GateError("invalid_proof")

    def connect() -> Any:
        native.remaining(children.deadline)
        return psycopg.connect(
            host="127.0.0.1",
            port=int(values["POSTGRES_PORT"]),
            dbname="livekit_lab",
            user="continuity_migrator",
            password=values["POSTGRES_MIGRATION_PASSWORD"],
            sslmode="disable",
            gssencmode="disable",
            connect_timeout=2,
            autocommit=True,
            application_name="p2-result-observer-" + run_id,
            options="-c search_path=pg_catalog -c statement_timeout=3000 -c lock_timeout=1500",
        )

    def preflight_names() -> None:
        registered()
        with closing(connect()) as connection:
            rows = connection.execute(
                "SELECT nspname FROM pg_namespace WHERE nspname=ANY(%s)",
                [[schema, work_schema, p1.runtime.schema]],
            ).fetchall()
            if rows:
                raise GateError("invalid_proof")

    def pg_quiet(end: float) -> None:
        """An exited Docker CLI alone does not retire its remote database backend."""
        registered()
        while True:
            native.remaining(end)
            with closing(connect()) as connection:
                connection.execute("SELECT pg_stat_clear_snapshot()")
                rows = connection.execute(
                    "SELECT pid,application_name FROM pg_stat_activity WHERE datname='livekit_lab' AND usename='continuity_migrator' AND application_name=ANY(%s)",
                    [list(backup_apps.values())],
                ).fetchall()
            native.remaining(end)
            if not rows:
                return
            seconds = end - time.monotonic()
            if seconds <= 0:
                raise GateError("cleanup_incomplete")
            time.sleep(min(0.02, seconds))

    async def m1_observation(end: float) -> dict[str, Any]:
        seconds = min(3, native.remaining(end))
        async with (
            aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=seconds, ceil_threshold=6),
                trust_env=False,
                auto_decompress=False,
                cookie_jar=aiohttp.DummyCookieJar(),
            ) as session,
            session.get(
                "http://127.0.0.1:" + values["API_PORT"] + "/api/investigations?limit=100",
                headers={"Authorization": "Bearer " + values["LOCAL_ACCESS_TOKEN"]},
                allow_redirects=False,
                max_headers=32,
                max_line_size=2048,
                max_field_size=2048,
            ) as response,
        ):
            lengths = response.headers.getall("Content-Length", [])
            if (
                response.status != 200
                or "Content-Encoding" in response.headers
                or "Transfer-Encoding" in response.headers
                or response.headers.getall("Content-Type", []) != ["application/json"]
                or len(lengths) != 1
                or re.fullmatch(r"[1-9][0-9]{0,5}", lengths[0]) is None
                or int(lengths[0]) > 262144
            ):
                raise GateError("missing_setup")
            raw = await response.content.readexactly(int(lengths[0]))
            value = evidence.decode(raw, 262144)
        if value.get("scope_id") != "local-lab" or type(value.get("items")) is not list:
            raise GateError("invalid_proof")
        rows = [
            r
            for r in value["items"]
            if type(r) is dict and r.get("idempotency_key") == "local-foundation-smoke-v1"
        ]
        if len(rows) != 1:
            raise GateError("missing_setup")
        row = rows[0]
        if row.get("scope_id") != "local-lab":
            raise GateError("invalid_proof")
        return {
            "scope_id": "local-lab",
            "task_id": row["task_id"],
            "sha256": hashlib.sha256(evidence.json_bytes(row)).hexdigest(),
        }

    def stage(mode: str) -> dict[str, Any]:
        registered()
        state["stage"] = mode
        raw = children.call(
            mode,
            node_argv(node, script, mode),
            child_environment(values, common, tokens, mode),
            cwd=work,
        )
        result = native.decode(raw)
        if result != {"schema_version": 1, "mode": mode, "status": "passed", "carrier_calls": 0}:
            raise GateError("invalid_proof")
        return result

    async def command(
        name: str, argv: list[str], environment: dict[str, str] | None = None
    ) -> bytes:
        state["stage"] = name
        return await asyncio.to_thread(
            children.call, name, argv, environment or core.base_environment(), cwd=project
        )

    def p2_guard(*, expected_version: int | None = None) -> int | None:
        registered()
        with closing(connect()) as connection:
            found = connection.execute(
                "SELECT pg_get_userbyid(nspowner),obj_description(oid,'pg_namespace') FROM pg_namespace WHERE nspname=%s",
                [schema],
            ).fetchone()
            if found is None:
                return None
            if (
                found[0] != "continuity_migrator"
                or re.fullmatch(r"p2-channel-schema-v[1-8]", found[1] or "") is None
            ):
                raise GateError("invalid_proof")
            version = int(found[1][-1])
            if expected_version is not None and version != expected_version:
                raise GateError("invalid_proof")
            return version

    def drop_owned_work() -> None:
        native.remaining(final)
        registered()
        owner = PostgresSettings(
            port=int(values["POSTGRES_PORT"]),
            user="continuity_migrator",
            password=values["POSTGRES_MIGRATION_PASSWORD"],
            schema=work_schema,
        )
        with closing(owner.connect(application_name="continuity-test")) as connection:
            row = connection.execute(
                "SELECT pg_get_userbyid(nspowner) AS owner,obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=%s",
                [work_schema],
            ).fetchone()
            if row is None:
                return
            if (
                row["owner"] != "continuity_migrator"
                or re.fullmatch(r"continuity-readonly-work-v[1-4]", row["marker"] or "") is None
            ):
                raise GateError("invalid_proof")
            validate_work_schema(connection, owner, owner=True)
            native.remaining(final)
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(work_schema))
            )

    def partial_p2_cleanup() -> None:
        """Validate an already-created v1-v8 profile; this path never installs DDL."""
        registered()
        modules = {
            "database": (work / "compiled/src/database.js").as_uri(),
            "migrations": (work / "compiled/src/migrations.js").as_uri(),
            "pg": (project / "node_modules/pg/lib/index.js").as_uri(),
        }
        code = (
            "if(process.version!==" + json.dumps(NODE_VERSION) + ")process.exit(2);"
            "const {validate}=await import(" + json.dumps(modules["database"]) + ");"
            "const m=await import(" + json.dumps(modules["migrations"]) + ");"
            "const {default:pg}=await import(" + json.dumps(modules["pg"]) + ");"
            "const fs=await import('node:fs');"
            "const d={host:'127.0.0.1',port:Number(process.env.P2_RESULT_PG_PORT),database:'livekit_lab',user:'continuity_migrator',password:process.env.P2_RESULT_OWNER_PASSWORD,schema:process.env.P2_RESULT_SCHEMA};"
            "const c=new pg.Client({...d,ssl:false,connectionTimeoutMillis:1500,query_timeout:5000,options:'-c search_path=pg_catalog -c statement_timeout=3000 -c lock_timeout=1500'});"
            "try{await c.connect();await c.query('BEGIN');"
            "const r=await c.query(\"SELECT pg_get_userbyid(nspowner) AS owner,obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=$1\",[d.schema]);"
            "if(r.rowCount!==1||r.rows[0].owner!=='continuity_migrator'||!/^p2-channel-schema-v[1-8]$/.test(r.rows[0].marker))throw Error();"
            "await validate(c,d,m.DEFINITION_DIGEST,true,m.DISPATCH_DEFINITION_DIGEST,m.OUTBOX_DEFINITION_DIGEST,m.CALLBACK_DEFINITION_DIGEST,m.SEND_POLICY_DEFINITION_DIGEST,m.NATIVE_DEFINITION_DIGEST,m.COMMUNICATION_DEFINITION_DIGEST,m.RESULT_RECEIVER_DEFINITION_DIGEST);"
            "const original=process.env.P2_RESULT_DIRECTORY+'/result-setup.json';"
            "if(fs.existsSync(original)){const expected=JSON.parse(fs.readFileSync(original,'utf8')).receiver_id;"
            "const actual=await c.query('SELECT receiver_id::text FROM \"'+d.schema+'\".outbox_settings WHERE singleton');"
            "if(actual.rowCount!==1||actual.rows[0].receiver_id!==expected)throw Error();}"
            "await c.query('DROP SCHEMA \"'+d.schema+'\" CASCADE');await c.query('COMMIT');"
            "fs.writeFileSync(process.env.P2_RESULT_DIRECTORY+'/result-partial-cleanup.json',JSON.stringify({schema_version:1,guard:r.rows[0],namespace_absent:true})+'\\n',{flag:'wx',mode:384});"
            "process.stdout.write(JSON.stringify({schema_version:1,mode:'cleanup',status:'passed',carrier_calls:0})+'\\n');"
            "}catch{await c.query('ROLLBACK').catch(()=>{});process.exitCode=1;}finally{await c.end();}"
        )
        raw = children.call(
            "cleanup",
            [node, "--input-type=module", "--eval", code],
            child_environment(values, common, tokens, "cleanup"),
            cwd=project,
        )
        if native.decode(raw) != {
            "schema_version": 1,
            "mode": "cleanup",
            "status": "passed",
            "carrier_calls": 0,
        }:
            raise GateError("cleanup_incomplete")

    def remote_done(kind: str) -> bool:
        if kind not in backup_started:
            return True
        child = next(
            (c for c in children.children if c.output_directory.name == "backup-" + kind), None
        )
        if child is None:
            return False
        stdout, _ = children.account(child)
        marker = ("P2_RESULT_REMOTE_" + run_id + "_" + kind + ":").encode()
        return re.search(rb"(?:^|\n)" + re.escape(marker) + rb"[0-9]{1,3}\n$", stdout) is not None

    try:
        await asyncio.to_thread(preflight_names)
        original_m1 = await m1_observation(deadline)
        save(artifacts / "m1-before.json", original_m1)
        await command("compile-public", public_build_command(root, work, artifacts, node, compiler))
        await command(
            "compile-fixture",
            node_argv(
                node,
                compiler,
                "--project",
                str(project / "tsconfig.pg.json"),
                "--outDir",
                str(work / "compiled"),
            ),
        )
        save(
            artifacts / "runtime-build-parity.json",
            native.verify_runtime_build(project, work / "compiled"),
        )
        state["stage"] = "p1-case-setup"
        port = await p1.bounded(p1.start(), deadline)
        assert p1.control is not None
        from datetime import date

        from continuity_lab.case_control_api import BookingChange

        revised = await p1.bounded(
            p1.control.revise(
                task_id=p1.task_id,
                expected_revision=0,
                request=BookingChange("DEMO-BK-001", date(2030, 12, 11), True),
            ),
            deadline,
        )
        if revised.revision != 1:
            raise GateError("invalid_proof")
        fixture = {
            "schema_version": 1,
            "scope": scope,
            "case_id": reference["caseId"],
            "conversation_id": reference["conversationId"],
            "recipient_id": "result_recipient",
            "legacy_outbound_id": str(uuid4()),
            **{
                name: [str(uuid4()) for _ in range(8)]
                for name in ("delivery_ids", "work_ids", "attempt_ids")
            },
            "native_binding_ids": {name: str(uuid4()) for name in ("a", "b", "revoke", "expire")},
            "case_endpoint": {"host": "127.0.0.1", "port": port},
        }
        save(work / "fixture.json", fixture)
        save(artifacts / "fixture.json", fixture)
        common = {
            "P2_RESULT_SCHEMA": schema,
            "P2_RESULT_DIRECTORY": str(work),
            "P2_RESULT_PG_PORT": values["POSTGRES_PORT"],
            "P2_RESULT_SHARED_FIXTURE": str(root / "contracts/delegation/result-receiver-v1.json"),
            "P2_RESULT_CASE_AUTHORIZATION": "Bearer " + p1.token,
        }
        state["p2_setup_started"] = True
        for mode in ("setup", "upgrade", "exercise"):
            await asyncio.to_thread(stage, mode)
        state["stage"] = "commit-before-ack"
        crash = children.start(
            "commit-before-ack",
            node_argv(node, script, "commit-before-ack"),
            child_environment(values, common, tokens, "commit-before-ack"),
            cwd=work,
        )
        reached = await asyncio.to_thread(
            children.wait_json, crash, work / "commit-before-ack.reached", timeout=10
        )
        if reached.get("pid") != crash.pid:
            raise GateError("invalid_proof")
        save(artifacts / "owned-kill.json", children.kill_owned(crash))
        await asyncio.to_thread(stage, "recover")
        state["stage"] = "serve"
        server = children.start(
            "serve",
            node_argv(node, script, "serve"),
            child_environment(values, common, tokens, "serve"),
            cwd=work,
        )
        endpoint = await asyncio.to_thread(
            children.wait_json, server, work / "serve-ready.json", timeout=10
        )
        if (
            set(endpoint) != {"schema_version", "host", "port", "receiver_id"}
            or endpoint["host"] != "127.0.0.1"
            or type(endpoint["port"]) is not int
            or not 1 <= endpoint["port"] <= 65535
        ):
            raise GateError("invalid_proof")
        if endpoint["receiver_id"] != load(work / "result-setup.json")["receiver_id"]:
            raise GateError("invalid_proof")
        from continuity_lab.execution_api import ExecutionLimits
        from continuity_lab.work_admin import (
            install_work_schema,
            upgrade_work_schema_v2,
            upgrade_work_schema_v3,
            upgrade_work_schema_v4,
        )
        from continuity_lab.work_api import WorkLimits

        work_owner = PostgresSettings(
            port=int(values["POSTGRES_PORT"]),
            user="continuity_migrator",
            password=values["POSTGRES_MIGRATION_PASSWORD"],
            schema=work_schema,
        )

        async def prepare_work() -> None:
            p1._admit_stage()
            await asyncio.to_thread(install_work_schema, work_owner, limits=WorkLimits(8, 8))
            p1._admit_stage()
            await asyncio.to_thread(
                upgrade_work_schema_v2, work_owner, limits=ExecutionLimits(3, 3, 10000)
            )
            p1._admit_stage()
            await asyncio.to_thread(upgrade_work_schema_v3, work_owner)
            p1._admit_stage()
            await asyncio.to_thread(upgrade_work_schema_v4, work_owner)

        owned_work = True
        state["stage"] = "p1-work-setup"
        await p1.bounded(prepare_work(), deadline)
        config = {
            "schema_version": 1,
            "scope": {"tenant_id": scope["tenantId"], "account_id": scope["accountId"]},
            "case_id": fixture["case_id"],
            "conversation_id": fixture["conversation_id"],
            "recipient_id": fixture["recipient_id"],
            "receiver_id": endpoint["receiver_id"],
            "receiver_port": endpoint["port"],
            "task_id": p1.task_id,
            "authority_case_id": p1.case_id,
            "case_schema": p1.runtime.schema,
            "work_schema": work_schema,
            "supplier_path": str(p1.supplier),
            "owners": {label: str(uuid4()) for label in ("original", "stale", "current")},
        }
        save(work / "p3-return-config.json", config)
        save(
            work / "p3-return-policy.json",
            json.loads((root / "contracts/delegation/fixed-policy-v2.json").read_bytes()),
        )
        consumer_env = {
            **{
                k: v
                for k, v in core.base_environment().items()
                if k in {"PATH", "LANG", "CI", "NO_COLOR", "__CF_USER_TEXT_ENCODING"}
            },
            "P3_RESULT_DIRECTORY": str(work),
            "P3_RESULT_PG_PORT": values["POSTGRES_PORT"],
            "P3_RESULT_RUNTIME_PASSWORD": values["POSTGRES_PASSWORD"],
            "P3_RESULT_WORK_TOKEN": secrets.token_urlsafe(32),
            "P3_RESULT_CASE_TOKEN": secrets.token_urlsafe(32),
            "P3_RESULT_PUBLISHER_TOKEN": tokens["P2_RESULT_PUBLISHER_TOKEN"],
            "P3_RESULT_NATIVE_B_BEARER": tokens["P2_RESULT_NATIVE_B_BEARER"],
        }
        exclusions += tuple(
            consumer_env[k] for k in ("P3_RESULT_WORK_TOKEN", "P3_RESULT_CASE_TOKEN")
        )
        await command(
            "p3-consumer",
            [python, "-I", "-B", str(root / "local-setup/scripts/p3_result_return_cases.py")],
            consumer_env,
        )
        await asyncio.to_thread(children.stop, server, deadline=deadline)
        state["stage"] = "independent-joins"
        before = await asyncio.to_thread(
            prior.snapshot, connect, (schema, work_schema, p1.runtime.schema)
        )
        save(artifacts / "before-restore.json", before)
        verdict = validate_bundle(work, before, schema, work_schema, p1.runtime.schema)
        if verdict != {"storage_assertions_before_restore": 14, "return_assertions": 4}:
            raise GateError("invalid_proof")
        container = (
            (
                await command(
                    "backup-container",
                    [
                        docker,
                        "ps",
                        "--filter",
                        "label=com.docker.compose.service=postgres",
                        "--filter",
                        "label=com.docker.compose.project=" + setup.PROJECT,
                        "--filter",
                        "label=com.docker.compose.project.working_dir=" + str(root / "local-setup"),
                        "--format",
                        "{{.ID}}",
                    ],
                )
            )
            .decode()
            .strip()
        )
        if re.fullmatch(r"[a-f0-9]{12,64}", container) is None:
            raise GateError("missing_setup")
        backup_possible = True
        for kind in ("dump", "restore"):
            if kind == "restore":
                await command(
                    "backup-copy",
                    [docker, "cp", container + ":" + backup_path, str(work / "result-backup.sql")],
                )
                os.chmod(work / "result-backup.sql", 0o600)
                evidence.read_private(work / "result-backup.sql", 2097152)
                await asyncio.to_thread(pg_quiet, deadline)
                if p2_guard(expected_version=8) != 8:
                    raise GateError("invalid_proof")
                with closing(connect()) as connection:
                    native.remaining(deadline)
                    connection.execute(
                        sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
                    )
            pg_env = {
                **core.base_environment(),
                "PGPASSWORD": values["POSTGRES_MIGRATION_PASSWORD"],
                "PGAPPNAME": backup_apps[kind],
                "PGOPTIONS": "-c statement_timeout=5000 -c lock_timeout=1500 -c idle_in_transaction_session_timeout=5000",
            }
            tool_args = (
                [
                    "pg_dump",
                    "--host=127.0.0.1",
                    "--username=continuity_migrator",
                    "--dbname=livekit_lab",
                    "--schema=" + schema,
                    "--inserts",
                    "--no-owner",
                    "--lock-wait-timeout=3000",
                    "--file=" + backup_path,
                ]
                if kind == "dump"
                else [
                    "psql",
                    "-X",
                    "--host=127.0.0.1",
                    "--username=continuity_migrator",
                    "--dbname=livekit_lab",
                    "--set=ON_ERROR_STOP=1",
                    "--single-transaction",
                    "--file=" + backup_path,
                ]
            )
            shell = (
                'umask 077; "$@"; p2_backup_status=$?; printf "\\nP2_RESULT_REMOTE_'
                + run_id
                + "_"
                + kind
                + ':%s\\n" "$p2_backup_status"; exit "$p2_backup_status"'
            )
            backup_started.add(kind)
            await command(
                "backup-" + kind,
                [
                    docker,
                    "exec",
                    "-e",
                    "PGPASSWORD",
                    "-e",
                    "PGAPPNAME",
                    "-e",
                    "PGOPTIONS",
                    container,
                    "sh",
                    "-c",
                    shell,
                    "p2-result-backup",
                    *tool_args,
                ],
                pg_env,
            )
            if not remote_done(kind):
                raise GateError("cleanup_incomplete")
            backup_completed.add(kind)
            await asyncio.to_thread(pg_quiet, deadline)
        restored = await asyncio.to_thread(prior.snapshot, connect, (schema,))
        if not evidence.exact(restored[schema], before[schema]):
            raise GateError("invalid_proof")
        save(artifacts / "after-restore.json", restored)
        await asyncio.to_thread(stage, "restore-check")
        validate_restore(load(work / "result-restore-check.json"), before[schema])
        state["validated"] = True
    finally:
        primary = sys.exception()
        failure_stage = state.get("stage", "preflight")
        children.deadline = final
        cleanup_errors: list[str] = []
        state["stage"] = "cleanup"
        try:
            await asyncio.to_thread(children.close)
        except Exception:  # noqa: BLE001 - retain primary failure through independent cleanup.
            cleanup_errors.append("process_groups")
        groups_closed = children.settled()
        dependencies_settled = False
        if groups_closed:
            try:
                if not all(remote_done(kind) for kind in backup_started):
                    raise GateError("cleanup_incomplete")
                await asyncio.to_thread(pg_quiet, final)
                registered()
                await p1.close(deadline=final)
                dependencies_settled = True
            except Exception:  # noqa: BLE001 - retain primary failure through independent cleanup.
                cleanup_errors.append("retained_dependency_owner")
            if dependencies_settled:
                if state.get("p2_setup_started"):
                    try:
                        version = await asyncio.to_thread(p2_guard)
                        if version is not None:
                            if version == 8 and (work / "result-setup.json").exists():
                                await asyncio.to_thread(stage, "cleanup")
                            else:
                                await asyncio.to_thread(partial_p2_cleanup)
                    except Exception:  # noqa: BLE001 - retain primary failure through independent cleanup.
                        cleanup_errors.append("p2_schema")
                # A newly timed-out cleanup child must settle before later DDL.
                if not children.settled():
                    try:
                        await asyncio.to_thread(children.close)
                    except Exception:  # noqa: BLE001 - retain every dependent owner.
                        cleanup_errors.append("cleanup_process_groups")
                    dependencies_settled = children.settled()
                if dependencies_settled and owned_work:
                    try:
                        await asyncio.to_thread(drop_owned_work)
                    except Exception:  # noqa: BLE001 - retain primary failure through independent cleanup.
                        cleanup_errors.append("p1_work_schema")
                if dependencies_settled and backup_possible and container:
                    try:
                        if not all(remote_done(kind) for kind in backup_started):
                            raise GateError("cleanup_incomplete")
                        await asyncio.to_thread(pg_quiet, final)
                        await command(
                            "backup-remove",
                            [docker, "exec", container, "rm", "-f", "--", backup_path],
                        )
                    except Exception:  # noqa: BLE001 - retain primary failure through independent cleanup.
                        cleanup_errors.append("backup_file")
        else:
            cleanup_errors.append("unresolved_group_owner")
        try:
            await asyncio.to_thread(children.close)
        except Exception:  # noqa: BLE001 - retain primary failure through independent cleanup.
            cleanup_errors.append("cleanup_process_groups")
        groups_closed = children.settled()
        if original_m1 is not None:
            try:
                current_m1 = await m1_observation(final)
                save(artifacts / "m1-after.json", current_m1)
                if current_m1 != original_m1:
                    raise GateError("invalid_proof")
            except Exception:  # noqa: BLE001 - retain primary failure through independent cleanup.
                cleanup_errors.append("m1_preservation")
        for path in sorted(work.glob("*.json")):
            if path.name in {"fixture.json", "ownership.json"} or path.name.startswith(
                ("result-", "p3-return-")
            ):
                if path.name == "p3-return-config.json":
                    continue
                try:
                    retain(path, artifacts / path.name, exclusions)
                except Exception:  # noqa: BLE001 - retain primary failure through independent cleanup.
                    cleanup_errors.append("proof_retention")
        for name in ("commit-before-ack.reached", "result-backup.sql"):
            path = work / name
            if path.exists():
                try:
                    retain(path, artifacts / name, exclusions)
                except Exception:  # noqa: BLE001 - retain primary failure through independent cleanup.
                    cleanup_errors.append("proof_retention")
        for child in children.children:
            target = artifacts / "commands" / child.output_directory.name
            try:
                evidence.private_directory(target)
                for name in ("stdout.bin", "stderr.bin", "process-group.pid"):
                    path = child.output_directory / name
                    if path.exists():
                        retain(path, target / name, exclusions, 65536)
                save(
                    target / "owner.json",
                    {
                        "pid": child.pid,
                        "returncode": child.returncode,
                        "group_settled": isinstance(child, GroupedOwnedProcess)
                        and child.group_settled,
                        "cleanup_failed": child.cleanup_failed,
                    },
                )
            except Exception:  # noqa: BLE001 - retain primary failure through independent cleanup.
                cleanup_errors.append("capture_retention")
        observations = [
            {
                "pid": c.pid,
                "role": c.output_directory.name,
                "returncode": c.returncode,
                "group_settled": isinstance(c, GroupedOwnedProcess) and c.group_settled,
                "cleanup_failed": c.cleanup_failed,
            }
            for c in children.children
        ]
        try:
            save(artifacts / "process-groups.json", observations)
            save(
                artifacts / "backup-ownership.json",
                {
                    "applications": backup_apps,
                    "started": sorted(backup_started),
                    "completed": sorted(backup_completed),
                    "remote_completion_markers": {
                        kind: remote_done(kind) for kind in backup_started
                    },
                    "private_work_retained": True,
                },
            )
        except Exception:  # noqa: BLE001 - evidence failure must not replace the primary failure.
            cleanup_errors.append("ownership_retention")
        state["cleanup_complete"] = not cleanup_errors and groups_closed and dependencies_settled
        state["cleanup_errors"] = sorted(set(cleanup_errors))
        state["child_commands"] = children.count
        state["capture_bytes"] = children.captured
        if primary is not None:
            state["failure_stage"] = failure_stage
        if primary is None and cleanup_errors:
            raise GateError("cleanup_incomplete")
    if source_snapshot(root) != source_before:
        raise GateError("source_changed")
    save(artifacts / "source-after.json", source_snapshot(root))
    if (
        not state.get("validated")
        or not state["cleanup_complete"]
        or children.count != len(COMMANDS)
    ):
        raise GateError("invalid_proof")
    if time.monotonic() > final:
        raise GateError("deadline_exceeded")
    retained = [path for path in artifacts.rglob("*") if path.is_file()]
    if len(retained) > 256 or sum(path.stat().st_size for path in retained) > 16777216:
        raise GateError("retention_failed")
    prior.retained_index(artifacts)
    index_sha256 = hashlib.sha256((artifacts / "retained-index.json").read_bytes()).hexdigest()
    prior.validate_retained_index(artifacts, index_sha256)
    if time.monotonic() > final:
        raise GateError("deadline_exceeded")
    case_results = [{"name": name, "status": "passed"} for name in (*CASES, *JOIN_CASES)]
    return {
        "schema_version": 1,
        "status": "passed",
        "storage_assertions": 16,
        "return_assertions": 4,
        "case_results": case_results,
        "skipped": 0,
        "cleanup_complete": True,
        "child_commands": children.count,
        "duration_seconds": time.monotonic() - started,
        "provider_calls": False,
        "private_provider_config_reads": False,
        "rtc_rooms": 0,
        "carrier_calls": 0,
        "node_version": NODE_VERSION[1:],
        "python_version": "3.14.10",
        "work_directory_retained": str(work),
        "retained_index_sha256": index_sha256,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if args.plan:
        print(json.dumps(plan(), indent=2))
        return 0
    target = args.report or Path(".local/validation/p2-result-receiver") / (uuid4().hex + ".json")
    if (
        target.is_absolute()
        or target.parent != Path(".local/validation/p2-result-receiver")
        or re.fullmatch(r"[A-Za-z0-9_-]{1,96}\.json", target.name) is None
    ):
        raise GateError("unsafe_path")
    target = ROOT / target
    artifacts = target.with_name(target.stem + "-artifacts")
    if target.exists() or artifacts.exists():
        raise GateError("unsafe_path")
    evidence.private_directory(artifacts)
    state: dict[str, Any] = {"cleanup_complete": False}
    try:
        result = asyncio.run(run(ROOT, artifacts, state))
    except Exception as error:  # noqa: BLE001 - outer tooling boundary, no dependency text
        code = "deadline_exceeded" if isinstance(error, ProcessTimeout) else "component_failed"
        if (
            isinstance(error, (GateError, native.GateError, core.GateError, prior.GateError))
            and type(error.code) is str
            and error.code in evidence.GATE_CODES
        ):
            code = error.code
        result = {
            "schema_version": 1,
            "status": "failed",
            "code": code,
            **state,
            "failure_stage": state.get("failure_stage", state.get("stage", "preflight")),
        }
    save(target, result)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
