"""Explicit equivalent standalone/P1 PostgreSQL revision-routing gate, no providers."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import math
import os
import secrets
import shutil
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import p2_postgres_check as core
from p2_case_bridge import CaseBinding, DropAcknowledgement, start_case_bridge
from psycopg import sql

from continuity_lab.case_control_api import open_case_control_client
from continuity_lab.postgres_api import BearerToken, open_postgres_client
from continuity_lab.work_api import PostgresSettings
from harness.process_control import FileBarrier, OwnedProcess

DEADLINE_SECONDS = 180.0
MODE = "local_synthetic_p2_revision_routing"
GROUP_CASES = (
    "normal_current_case_inspection",
    "controlled_competing_revision_transition",
    "stale_replay_never_infers_original_acceptance",
    "ambiguous_text_clarification",
    "cross_account_routing_denied",
    "current_command_valid_progress",
    "known_unchanged_request",
    "postcommit_ack_loss_stays_unknown",
    "owned_adapter_cleanup",
)
CASE_NAMES = tuple(group + "_" + name for group in ("reference", "p1") for name in GROUP_CASES) + (
    "reference_blocking_graph_observed",
    "p1_blocking_graph_observed",
    "independent_owner_reconciliation",
    "cleanup_ownership",
)


def decode(raw: bytes) -> dict[str, Any]:
    value = json.loads(raw, object_pairs_hook=core.unique_object)
    if type(value) is not dict:
        raise core.GateError("invalid_report")
    return value


def validated_report(raw: bytes) -> dict[str, Any]:
    value = decode(raw)
    if set(value) != {
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
        "authority",
    }:
        raise core.GateError("invalid_report")
    if (
        value["schema_version"] != 1
        or type(value["schema_version"]) is not int
        or value["status"] != "passed"
        or value["mode"] != MODE
    ):
        raise core.GateError("invalid_report")
    if any(
        type(value[key]) is not int for key in ("tests", "passed", "failures", "errors", "skipped")
    ):
        raise core.GateError("invalid_report")
    if (
        value["tests"] != len(CASE_NAMES)
        or value["passed"] != len(CASE_NAMES)
        or any(value[key] != 0 for key in ("failures", "errors", "skipped"))
    ):
        raise core.GateError("invalid_report")
    duration = value["duration_seconds"]
    if (
        type(duration) not in (int, float)
        or not math.isfinite(duration)
        or not 0 < duration <= DEADLINE_SECONDS
        or value["cleanup_complete"] is not True
        or not core.supported_node(value["node_version"])
    ):
        raise core.GateError("invalid_report")
    if (
        value["case_results"]
        != [{"name": name, "status": "passed", "code": "ok"} for name in CASE_NAMES]
        or value["blocking_graphs"] != {"reference": 2, "p1": 2}
        or value["authority"] != "single_selected_CAS_no_command_receipt_or_confirmation"
    ):
        raise core.GateError("invalid_report")
    return value


def target_path(root: Path, requested: Path) -> Path:
    path = (requested if requested.is_absolute() else root / requested).absolute()
    if ".." in path.parts or not path.is_relative_to(root / ".local/validation/p2-routing"):
        raise core.GateError("unsafe_evidence_path")
    core.private_directory(path.parent)
    if path.exists() or path.is_symlink():
        raise core.GateError("existing_report")
    return path


def retain(path: Path, value: dict[str, Any]) -> None:
    with os.fdopen(
        os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "w"
    ) as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")


def child_environment(
    values: dict[str, str], context: dict[str, str], *, owner: bool
) -> dict[str, str]:
    return {
        **core.base_environment(),
        **context,
        "P2_ROUTING_PG_PORT": values["POSTGRES_PORT"],
        "P2_ROUTING_OWNER_PASSWORD" if owner else "P2_ROUTING_RUNTIME_PASSWORD": values[
            "POSTGRES_MIGRATION_PASSWORD" if owner else "POSTGRES_PASSWORD"
        ],
    }


async def run(
    root: Path, artifacts: Path, started: float, cleanup_state: dict[str, bool]
) -> dict[str, Any]:
    deadline = started + DEADLINE_SECONDS
    setup = core.load_setup(root)
    values = setup.load_settings()
    helper_path = root / "local-setup/scripts/p3_case_fixture.py"
    spec = importlib.util.spec_from_file_location("p2_routing_explicit_owner_fixture", helper_path)
    if spec is None or spec.loader is None:
        raise core.GateError("missing_setup")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    project = root / "projects/channel-continuity"
    node = shutil.which("node")
    compiler = project / "node_modules/typescript/bin/tsc"
    if node is None or not compiler.is_file():
        raise core.GateError("missing_setup")
    scratch_root = project / ".local/p2-routing-check"
    core.private_directory(scratch_root)
    schemas: list[tuple[str, str]] = []
    bridge = None
    case_settings = None
    clean = False
    observed: list[str] = []
    graphs: dict[str, int] = {}
    node_version = ""
    sequence = 0

    def connection(schema: str, *, owner: bool = False) -> PostgresSettings:
        return PostgresSettings(
            port=int(values["POSTGRES_PORT"]),
            schema=schema,
            user="continuity_migrator" if owner else "livekit_lab",
            password=values["POSTGRES_MIGRATION_PASSWORD" if owner else "POSTGRES_PASSWORD"],
        )

    def child(command: list[str], environment: dict[str, str], name: str) -> dict[str, Any]:
        nonlocal sequence
        sequence += 1
        code, stdout, stderr = core.run_child(
            command,
            cwd=project,
            environment=environment,
            output=artifacts / f"{sequence:02d}-{name}",
            deadline=deadline,
        )
        if code or stderr:
            raise core.GateError("runner_failed_" + name)
        return decode(stdout)

    with tempfile.TemporaryDirectory(prefix="run-", dir=scratch_root) as temporary:
        work = Path(temporary)
        try:
            for name, arguments in (
                ("build", ["--project", str(project / "tsconfig.json")]),
                (
                    "compile",
                    [
                        "--project",
                        str(project / "tsconfig.pg.json"),
                        "--outDir",
                        str(work / "compiled"),
                    ],
                ),
            ):
                sequence += 1
                code, _, _ = core.run_child(
                    [node, str(compiler), *arguments],
                    cwd=project,
                    environment=core.base_environment(),
                    output=artifacts / f"{sequence:02d}-{name}",
                    deadline=deadline,
                )
                if code:
                    raise core.GateError("compile_failed")
            script = str(work / "compiled/tests/pg_routing_cases.js")
            reference_schema = "p2_case_routing_" + uuid4().hex
            p1_schema = "p3_completion_" + uuid4().hex
            case_settings = connection(p1_schema, owner=True)
            # Explicit owner-only marked synthetic booking authority bootstrap.
            # Runtime bridge/consumer use public P1 clients only; no P3 service.
            schemas.append((p1_schema, helper.MARKER))
            helper.install(case_settings, work / "unused-owner-supplier.sqlite3")
            case_client = open_postgres_client(
                actor=helper.ACTOR, token=BearerToken("b" * 43), settings=connection(p1_schema)
            )
            try:
                accepted = await case_client.submit(
                    idempotency_key="routing-case", request=helper.REQUEST
                )
            finally:
                await case_client.close()
            for group in ("reference", "p1"):
                folder = work / group
                folder.mkdir(mode=0o700)
                inbox_schema = "p2_inbox_" + uuid4().hex
                context = {
                    "P2_ROUTING_DIRECTORY": str(folder),
                    "P2_ROUTING_GROUP": group,
                    "P2_ROUTING_INBOX_SCHEMA": inbox_schema,
                    "P2_ROUTING_REFERENCE_SCHEMA": reference_schema,
                }
                schemas.append((inbox_schema, "p2-channel-schema-v1"))
                if group == "reference":
                    schemas.append((reference_schema, "p2-reference-case-v1"))
                if await asyncio.to_thread(
                    child,
                    [node, script, "setup"],
                    child_environment(values, context, owner=True),
                    "setup-" + group,
                ) != {"status": "passed", "mode": "setup"}:
                    raise core.GateError("invalid_report")
                if group == "p1":
                    token = secrets.token_urlsafe(32)
                    control = open_case_control_client(
                        actor=helper.ACTOR,
                        token=BearerToken("b" * 43),
                        settings=connection(p1_schema),
                    )

                    async def drop_acknowledgement(marker: Path = folder / "drop-next") -> None:
                        if marker.exists():
                            marker.unlink()
                            raise DropAcknowledgement()

                    bridge = await start_case_bridge(
                        (
                            CaseBinding(
                                "tenant-a",
                                "account-a",
                                "case-a",
                                accepted.task_id,
                                accepted.case_id,
                                token,
                                control,
                            ),
                        ),
                        request_timeout_ms=1500,
                        harness_after_revision=drop_acknowledgement,
                    )
                    context.update(
                        P2_ROUTING_BRIDGE_PORT=str(bridge.port), P2_ROUTING_BRIDGE_TOKEN=token
                    )
                sequence += 1
                output = artifacts / f"{sequence:02d}-exercise-{group}"
                with OwnedProcess(
                    [node, script, "exercise"],
                    cwd=project,
                    env=child_environment(values, context, owner=False),
                    output_directory=output,
                    max_output_bytes=16384,
                ) as process:
                    await asyncio.to_thread(
                        process.wait_for_barrier,
                        FileBarrier(folder, "race"),
                        timeout=min(10, core.remaining(deadline)),
                    )
                    selected_schema = reference_schema if group == "reference" else p1_schema
                    with closing(
                        connection(selected_schema, owner=True).connect(
                            application_name="continuity-test"
                        )
                    ) as owner:
                        owner.execute("BEGIN")
                        pid_row = owner.execute("SELECT pg_backend_pid() AS pid").fetchone()
                        assert pid_row is not None
                        owner_pid = pid_row["pid"]
                        if group == "reference":
                            owner.execute(
                                sql.SQL(
                                    "SELECT 1 FROM {}.cases WHERE tenant_id='tenant-a' AND account_id='account-a' AND case_id='case-a' FOR UPDATE"
                                ).format(sql.Identifier(selected_schema))
                            )
                        else:
                            owner.execute(
                                sql.SQL(
                                    "SELECT 1 FROM {}.cases WHERE task_id=%s FOR UPDATE"
                                ).format(sql.Identifier(selected_schema)),
                                [accepted.task_id],
                            )
                        (folder / "race.go").touch(mode=0o600)
                        barrier_deadline = time.monotonic() + 0.8
                        with closing(
                            connection(selected_schema).connect(application_name="continuity-test")
                        ) as observer:
                            while True:
                                rows = observer.execute(
                                    "SELECT pid,pg_blocking_pids(pid) AS blockers FROM pg_stat_activity WHERE usename=current_user AND pid<>pg_backend_pid()"
                                ).fetchall()
                                reached = {owner_pid}
                                for _ in range(4):
                                    reached.update(
                                        row["pid"]
                                        for row in rows
                                        if any(pid in reached for pid in row["blockers"])
                                    )
                                blocked = len(reached - {owner_pid})
                                if blocked == 2:
                                    graphs[group] = blocked
                                    break
                                if time.monotonic() >= barrier_deadline:
                                    raise core.GateError("unobserved_database_race")
                                await asyncio.sleep(0.005)
                        owner.execute("COMMIT")
                    result = await asyncio.to_thread(process.wait, timeout=core.remaining(deadline))
                raw = (output / "stdout.bin").read_bytes()
                if (
                    process.cleanup_failed
                    or result.returncode
                    or (output / "stderr.bin").read_bytes()
                ):
                    raise core.GateError("runner_failed_exercise_" + group)
                result_report = decode(raw)
                if (
                    result_report.get("status") != "passed"
                    or result_report.get("cases") != list(GROUP_CASES)
                    or result_report.get("cleanup_complete") is not True
                    or not core.supported_node(result_report.get("node_version"))
                ):
                    raise core.GateError("invalid_report")
                node_version = result_report["node_version"]
                observed.extend(group + "_" + name for name in GROUP_CASES)
                proof = decode((folder / "proof.json").read_bytes())
                retain(artifacts / (group + "-proof.json"), proof)
                if (
                    proof["race"].count("revised") != 1
                    or proof["race"].count("revision_conflict") != 1
                    or proof["revision"] != "3"
                    or proof["unknown_original_status"] != "outcome_unknown"
                ):
                    raise core.GateError("independent_reconciliation_failed")
                with closing(
                    connection(selected_schema, owner=True).connect(
                        application_name="continuity-test"
                    )
                ) as owner:
                    if group == "reference":
                        row = owner.execute(
                            sql.SQL(
                                "SELECT revision,request_json,cancelled,committed FROM {}.cases"
                            ).format(sql.Identifier(selected_schema))
                        ).fetchone()
                        if (
                            row is None
                            or row["revision"] != 3
                            or json.loads(row["request_json"]) != proof["request"]
                            or row["cancelled"]
                            or row["committed"]
                        ):
                            raise core.GateError("independent_reconciliation_failed")
                    else:
                        row = owner.execute(
                            sql.SQL(
                                "SELECT revision,request_json,cancelled,actor_id,scope_id,case_id FROM {}.cases WHERE task_id=%s"
                            ).format(sql.Identifier(selected_schema)),
                            [accepted.task_id],
                        ).fetchone()
                        if (
                            row is None
                            or row["revision"] != 3
                            or json.loads(row["request_json"])
                            != {
                                "booking_reference": proof["request"]["bookingReference"],
                                "new_check_in": proof["request"]["newCheckIn"],
                                "confirmed": True,
                            }
                            or (row["actor_id"], row["scope_id"], row["case_id"])
                            != (helper.ACTOR.actor_id, helper.ACTOR.scope_id, accepted.case_id)
                            or row["cancelled"]
                        ):
                            raise core.GateError("independent_reconciliation_failed")
                        for table in (
                            "quotes",
                            "confirmations",
                            "action_intents",
                            "mutation_effects",
                            "business_outcomes",
                        ):
                            counted = owner.execute(
                                sql.SQL("SELECT count(*) AS count FROM {}.{}").format(
                                    sql.Identifier(selected_schema), sql.Identifier(table)
                                )
                            ).fetchone()
                            if counted is None or counted["count"] != 0:
                                raise core.GateError("forbidden_effect")
                with closing(
                    connection(inbox_schema, owner=True).connect(application_name="continuity-test")
                ) as owner:
                    for table in ("inbox", "processing_intents"):
                        counted = owner.execute(
                            sql.SQL("SELECT count(*) AS count FROM {}.{}").format(
                                sql.Identifier(inbox_schema), sql.Identifier(table)
                            )
                        ).fetchone()
                        if counted is None or counted["count"] != 6:
                            raise core.GateError("independent_reconciliation_failed")
                if bridge is not None:
                    await bridge.close()
                    if bridge.pending_count or bridge.metrics()["sockets"]:
                        raise core.GateError("cleanup_incomplete")
                    bridge = None
            observed.extend(CASE_NAMES[-4:-1])
        finally:
            if bridge is not None:
                await bridge.close()
            for schema, marker in reversed(schemas):
                with closing(
                    connection(schema, owner=True).connect(application_name="continuity-test")
                ) as owner:
                    row = owner.execute(
                        "SELECT pg_get_userbyid(nspowner) AS owner,obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=%s",
                        [schema],
                    ).fetchone()
                    if row is not None:
                        if row != {"owner": "continuity_migrator", "marker": marker}:
                            raise core.GateError("cleanup_incomplete")
                        owner.execute(
                            sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
                        )
                    if (
                        owner.execute(
                            "SELECT 1 FROM pg_namespace WHERE nspname=%s", [schema]
                        ).fetchone()
                        is not None
                    ):
                        raise core.GateError("cleanup_incomplete")
            clean = True
            cleanup_state["cleanup_complete"] = True
    observed.append(CASE_NAMES[-1])
    if not clean or observed != list(CASE_NAMES):
        raise core.GateError("invalid_report")
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
                "case_results": [
                    {"name": name, "status": "passed", "code": "ok"} for name in CASE_NAMES
                ],
                "node_version": node_version,
                "blocking_graphs": graphs,
                "authority": "single_selected_CAS_no_command_receipt_or_confirmation",
            }
        ).encode()
    )


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    started = time.monotonic()
    cleanup_state = {"cleanup_complete": False}
    try:
        target = target_path(
            root, args.report or Path(".local/validation/p2-routing/" + uuid4().hex + ".json")
        )
        artifacts = target.with_name(target.stem + "-artifacts")
        artifacts.mkdir(mode=0o700)
        result = asyncio.run(run(root, artifacts, started, cleanup_state))
    except core.GateError as error:
        result = {
            "status": "failed",
            "mode": MODE,
            "code": error.code,
            "duration_seconds": time.monotonic() - started,
        }
    except Exception:  # noqa: BLE001 - fixed safe tooling boundary
        result = {
            "status": "failed",
            "mode": MODE,
            "code": "gate_failed",
            "duration_seconds": time.monotonic() - started,
        }
    if result["status"] == "failed":
        result.update(cleanup_state)
    try:
        retain(target, result)
    except (OSError, UnboundLocalError):
        result = {
            "status": "failed",
            "mode": MODE,
            "code": "report_write_failed",
            "duration_seconds": time.monotonic() - started,
            **cleanup_state,
        }
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
