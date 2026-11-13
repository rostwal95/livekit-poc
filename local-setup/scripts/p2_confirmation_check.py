"""Explicit actual P1/P2 linked-confirmation gate; synthetic supplier, no providers."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
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

from continuity_lab.case_control_api import CaseControlClient, open_case_control_client
from continuity_lab.postgres_api import BearerToken, open_postgres_client
from continuity_lab.work_api import PostgresSettings
from harness.process_control import FileBarrier, OwnedProcess

DEADLINE_SECONDS = 180.0
MODE = "local_synthetic_p2_linked_confirmation"
PRODUCT_CASES = (
    "distinct_publisher_authentication",
    "immutable_response_across_cases",
    "concurrent_publication_and_replay_at_cap",
    "missing_or_unlinked_text_clarification",
    "stale_linked_quote_zero_commit",
    "altered_digest_zero_commit",
    "case_authority_atomic_revision_race",
    "valid_linked_ack_loss_stays_unknown",
    "explicit_original_receipt_replay",
    "known_receipt_after_late_case_cancel",
    "revoked_sender_blocks_new_confirm",
    "reassigned_sender_cannot_transfer",
    "safe_observation_fields",
    "owned_runtime_cleanup",
)
CASE_NAMES = PRODUCT_CASES + (
    "real_blocking_graph_observed",
    "independent_prompt_case_supplier_reconciliation",
    "restricted_owner_runtime_permissions",
    "cleanup_ownership",
)


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
    if set(v) != {
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
        "blocking_graph",
        "authority",
        "prompt_registry_version",
    }:
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
            "blocking_graph",
            "prompt_registry_version",
        )
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
        or v["blocking_graph"] != 2
        or v["prompt_registry_version"] != 1
        or v["cleanup_complete"] is not True
        or type(d) not in (int, float)
        or not math.isfinite(d)
        or not 0 < d <= DEADLINE_SECONDS
        or not core.supported_node(v["node_version"])
    ):
        raise core.GateError("invalid_report")
    if v["authority"] != "public_P1_atomic_exact_quote_command_no_revocation_fence" or v[
        "case_results"
    ] != [{"name": n, "status": "passed", "code": "ok"} for n in CASE_NAMES]:
        raise core.GateError("invalid_report")
    return v


def target_path(root: Path, requested: Path) -> Path:
    path = (requested if requested.is_absolute() else root / requested).absolute()
    if ".." in path.parts or not path.is_relative_to(root / ".local/validation/p2-confirmation"):
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
    common = {"P2_CONFIRM_INBOX_SCHEMA", "P2_CONFIRM_PROMPT_SCHEMA", "P2_CONFIRM_DIRECTORY"}
    required = (
        common
        if owner
        else common
        | {
            "P2_CONFIRM_QUOTES_FILE",
            "P2_CONFIRM_BRIDGE_PORT",
            "P2_CONFIRM_BRIDGE_TOKEN",
            "P2_CONFIRM_PUBLISH_MAIN_TOKEN",
            "P2_CONFIRM_PUBLISH_RACE_TOKEN",
        }
    )
    if set(context) != required:
        raise core.GateError("unsafe_child_environment")
    return {
        **core.base_environment(),
        **context,
        "P2_CONFIRM_PG_PORT": values["POSTGRES_PORT"],
        "P2_CONFIRM_OWNER_PASSWORD" if owner else "P2_CONFIRM_RUNTIME_PASSWORD": values[
            "POSTGRES_MIGRATION_PASSWORD" if owner else "POSTGRES_PASSWORD"
        ],
    }


async def run(
    root: Path, artifacts: Path, started: float, state: dict[str, bool]
) -> dict[str, Any]:
    deadline = started + DEADLINE_SECONDS
    values = core.load_setup(root).load_settings()
    project = root / "projects/channel-continuity"
    node = shutil.which("node")
    compiler = project / "node_modules/typescript/bin/tsc"
    if node is None or not compiler.is_file():
        raise core.GateError("missing_setup")
    spec = importlib.util.spec_from_file_location(
        "p2_confirmation_explicit_fixture", root / "local-setup/scripts/p3_case_fixture.py"
    )
    if spec is None or spec.loader is None:
        raise core.GateError("missing_setup")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)

    def settings(schema: str, owner: bool = False) -> PostgresSettings:
        return PostgresSettings(
            port=int(values["POSTGRES_PORT"]),
            schema=schema,
            user="continuity_migrator" if owner else "livekit_lab",
            password=values["POSTGRES_MIGRATION_PASSWORD" if owner else "POSTGRES_PASSWORD"],
        )

    sequence = 0
    schemas: list[tuple[str, str]] = []
    bridge = None
    client = None
    race_task = None
    controls: list[CaseControlClient] = []
    observed: list[str] = []
    graph = 0
    node_version = ""

    def child(command: list[str], environment: dict[str, str], label: str) -> dict[str, Any]:
        nonlocal sequence
        sequence += 1
        code, stdout, stderr = core.run_child(
            command,
            cwd=project,
            environment=environment,
            output=artifacts / f"{sequence:02d}-{label}",
            deadline=deadline,
        )
        if code or stderr:
            raise core.GateError("runner_failed_" + label)
        return decode(stdout)

    scratch = project / ".local/p2-confirmation-check"
    core.private_directory(scratch)
    with tempfile.TemporaryDirectory(prefix="run-", dir=scratch) as temporary:
        work = Path(temporary)
        try:
            for label, arguments in (
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
                    output=artifacts / f"{sequence:02d}-{label}",
                    deadline=deadline,
                )
                if code:
                    raise core.GateError("compile_failed")
            case_schema = "p3_completion_" + uuid4().hex
            inbox_schema = "p2_inbox_" + uuid4().hex
            prompt_schema = "p2_prompt_" + uuid4().hex
            schemas.append((case_schema, helper.MARKER))
            helper.install(settings(case_schema, True), work / "supplier.sqlite3")
            token = BearerToken("b" * 43)
            client = open_postgres_client(
                actor=helper.ACTOR,
                token=token,
                settings=settings(case_schema),
                quote_database=work / "supplier.sqlite3",
            )
            main = await client.submit(idempotency_key="confirmation-main", request=helper.REQUEST)
            race = await client.submit(idempotency_key="confirmation-race", request=helper.REQUEST)
            for accepted in (main, race):
                await asyncio.to_thread(
                    helper.inquire,
                    settings(case_schema),
                    work / "supplier.sqlite3",
                    accepted.task_id,
                )
            main_control = open_case_control_client(
                actor=helper.ACTOR,
                token=token,
                settings=settings(case_schema),
                quote_database=work / "supplier.sqlite3",
            )
            controls.append(main_control)
            race_control = open_case_control_client(
                actor=helper.ACTOR,
                token=token,
                settings=settings(case_schema),
                quote_database=work / "supplier.sqlite3",
            )
            controls.append(race_control)

            async def aba(control: CaseControlClient, task_id: str, start: int) -> None:
                await control.revise(
                    task_id=task_id, expected_revision=start, request=helper.ALTERNATE
                )
                await control.revise(
                    task_id=task_id, expected_revision=start + 1, request=helper.REQUEST
                )

            await aba(main_control, main.task_id, 0)
            a = await client.prepare_quote(
                task_id=main.task_id, expected_revision=2, command_id="quote-a"
            )
            await aba(main_control, main.task_id, 2)
            b = await client.prepare_quote(
                task_id=main.task_id, expected_revision=4, command_id="quote-b"
            )
            await aba(race_control, race.task_id, 0)
            r = await client.prepare_quote(
                task_id=race.task_id, expected_revision=2, command_id="quote-race"
            )
            prompts = []
            for receipt, response_id, logical_case, conversation in (
                (a, "response-a", "case-main", "conversation-main"),
                (b, "response-b", "case-main", "conversation-main"),
                (r, "response-race", "case-race", "conversation-race"),
            ):
                raw = json.dumps(
                    receipt.quote.payload(),
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                )
                prompts.append(
                    {
                        "schemaVersion": 1,
                        "scope": {"tenantId": "tenant-a", "accountId": "account-a"},
                        "caseId": logical_case,
                        "conversationId": conversation,
                        "responseId": response_id,
                        "revision": str(receipt.quote.revision),
                        "quoteId": receipt.quote.quote_id,
                        "quoteDigest": hashlib.sha256(raw.encode()).hexdigest(),
                        "quoteJson": raw,
                    }
                )
            retain(work / "quotes.json", {"prompts": prompts})
            retain(artifacts / "controller-quotes.json", {"prompts": prompts})
            context = {
                "P2_CONFIRM_INBOX_SCHEMA": inbox_schema,
                "P2_CONFIRM_PROMPT_SCHEMA": prompt_schema,
                "P2_CONFIRM_DIRECTORY": str(work),
            }
            schemas.extend(
                (
                    (inbox_schema, "p2-channel-schema-v1"),
                    (prompt_schema, "p2-confirmation-prompt-registry-v1"),
                )
            )
            script = str(work / "compiled/tests/pg_confirmation_cases.js")
            if await asyncio.to_thread(
                child,
                [node, script, "setup"],
                child_environment(values, context, owner=True),
                "setup",
            ) != {"status": "passed", "mode": "setup"}:
                raise core.GateError("invalid_report")
            bridge_token = secrets.token_urlsafe(32)

            async def drop() -> None:
                marker = work / "drop-confirm-next"
                if marker.exists():
                    marker.unlink()
                    raise DropAcknowledgement()

            bridge = await start_case_bridge(
                (
                    CaseBinding(
                        "tenant-a",
                        "account-a",
                        "case-main",
                        main.task_id,
                        main.case_id,
                        bridge_token,
                        main_control,
                        allow_confirmation=True,
                    ),
                    CaseBinding(
                        "tenant-a",
                        "account-a",
                        "case-race",
                        race.task_id,
                        race.case_id,
                        bridge_token,
                        race_control,
                        allow_confirmation=True,
                    ),
                ),
                request_timeout_ms=1500,
                harness_after_confirmation=drop,
            )
            context.update(
                P2_CONFIRM_QUOTES_FILE=str(work / "quotes.json"),
                P2_CONFIRM_BRIDGE_PORT=str(bridge.port),
                P2_CONFIRM_BRIDGE_TOKEN=bridge_token,
                P2_CONFIRM_PUBLISH_MAIN_TOKEN=secrets.token_urlsafe(32),
                P2_CONFIRM_PUBLISH_RACE_TOKEN=secrets.token_urlsafe(32),
            )
            sequence += 1
            output = artifacts / f"{sequence:02d}-exercise"
            with OwnedProcess(
                [node, script, "exercise"],
                cwd=project,
                env=child_environment(values, context, owner=False),
                output_directory=output,
                max_output_bytes=32768,
            ) as process:
                await asyncio.to_thread(
                    process.wait_for_barrier,
                    FileBarrier(work, "race"),
                    timeout=min(10, core.remaining(deadline)),
                )
                with (
                    closing(
                        settings(case_schema, True).connect(application_name="continuity-test")
                    ) as owner,
                    closing(
                        settings(case_schema).connect(application_name="continuity-test")
                    ) as observer,
                ):
                    owner.execute("BEGIN")
                    pidrow = owner.execute("SELECT pg_backend_pid() AS pid").fetchone()
                    assert pidrow is not None
                    owner_pid = pidrow["pid"]
                    owner.execute(
                        sql.SQL("SELECT 1 FROM {}.cases WHERE task_id=%s FOR UPDATE").format(
                            sql.Identifier(case_schema)
                        ),
                        [race.task_id],
                    )
                    race_task = asyncio.create_task(
                        race_control.revise(
                            task_id=race.task_id, expected_revision=2, request=helper.ALTERNATE
                        )
                    )
                    end = time.monotonic() + 0.8

                    async def wait_blocked(count: int) -> None:
                        while True:
                            rows = observer.execute(
                                "SELECT pid,pg_blocking_pids(pid) AS blockers FROM pg_stat_activity WHERE usename=current_user AND pid<>pg_backend_pid()"
                            ).fetchall()
                            reached = {owner_pid}
                            for _ in range(4):
                                reached.update(
                                    row["pid"]
                                    for row in rows
                                    if any(p in reached for p in row["blockers"])
                                )
                            if len(reached - {owner_pid}) == count:
                                return
                            if time.monotonic() >= end:
                                raise core.GateError("unobserved_database_race")
                            await asyncio.sleep(0.005)

                    await wait_blocked(1)
                    (work / "race.go").touch(mode=0o600)
                    await wait_blocked(2)
                    graph = 2
                    owner.execute("COMMIT")
                revised = await race_task
                race_task = None
                if revised.revision != 3:
                    raise core.GateError("race_did_not_progress")
                await asyncio.to_thread(
                    process.wait_for_barrier,
                    FileBarrier(work, "cancel"),
                    timeout=min(10, core.remaining(deadline)),
                )
                mutation = await asyncio.to_thread(
                    helper.mutate, settings(case_schema), work / "supplier.sqlite3", main.task_id
                )
                if mutation.get("status") != "passed":
                    raise core.GateError("current_effect_failed")
                await client.cancel(task_id=main.task_id, command_id="after-confirmed-effect")
                (work / "cancel.go").touch(mode=0o600)
                result = await asyncio.to_thread(process.wait, timeout=core.remaining(deadline))
            if process.cleanup_failed or result.returncode or (output / "stderr.bin").read_bytes():
                raise core.GateError("runner_failed_exercise")
            response = decode((output / "stdout.bin").read_bytes())
            if (
                response.get("status") != "passed"
                or response.get("cases") != list(PRODUCT_CASES)
                or response.get("cleanup_complete") is not True
                or not core.supported_node(response.get("node_version"))
            ):
                raise core.GateError("invalid_report")
            node_version = response["node_version"]
            observed.extend(PRODUCT_CASES)
            proof = decode((work / "proof.json").read_bytes())
            retain(artifacts / "proof.json", proof)
            if (
                proof["accepted_inputs"] != 6
                or proof["prompt_count"] != 3
                or proof["revision"] != "4"
                or proof["unknown_original_status"] != "outcome_unknown"
                or proof["authority_calls_after_denied"] != proof["authority_calls_before_denied"]
            ):
                raise core.GateError("independent_reconciliation_failed")
            with closing(
                settings(case_schema, True).connect(application_name="continuity-test")
            ) as owner:
                for table, expected_count in (
                    ("confirmations", 1),
                    ("action_intents", 1),
                    ("mutation_effects", 1),
                    ("business_outcomes", 1),
                ):
                    row = owner.execute(
                        sql.SQL("SELECT count(*) AS count FROM {}.{}").format(
                            sql.Identifier(case_schema), sql.Identifier(table)
                        )
                    ).fetchone()
                    if row is None or row["count"] != expected_count:
                        raise core.GateError("forbidden_or_duplicate_effect")
                row = owner.execute(
                    sql.SQL(
                        "SELECT c.command_id,c.payload_json AS confirmation,i.intent_id,i.effect_id,i.revision,i.quote_id,i.actor_id,i.scope_id,i.task_id,e.state,e.dispatch_count FROM {}.confirmations c JOIN {}.action_intents i USING(confirmation_id) JOIN {}.mutation_effects e USING(intent_id)"
                    ).format(*[sql.Identifier(case_schema)] * 3)
                ).fetchone()
                if (
                    row is None
                    or (
                        row["command_id"],
                        row["intent_id"],
                        row["effect_id"],
                        str(row["revision"]),
                        row["quote_id"],
                        row["actor_id"],
                        row["scope_id"],
                        row["task_id"],
                        row["state"],
                        row["dispatch_count"],
                    )
                    != (
                        proof["command_id"],
                        proof["intent_id"],
                        proof["effect_id"],
                        "4",
                        b.quote.quote_id,
                        helper.ACTOR.actor_id,
                        helper.ACTOR.scope_id,
                        main.task_id,
                        "succeeded",
                        1,
                    )
                    or json.loads(row["confirmation"])
                    != {"schema_version": 2, "quote": b.quote.payload(), "explicit": True}
                ):
                    raise core.GateError("independent_reconciliation_failed")
                rows = owner.execute(
                    sql.SQL(
                        "SELECT task_id,case_id,actor_id,scope_id,revision,request_json FROM {}.cases"
                    ).format(sql.Identifier(case_schema))
                ).fetchall()
                case_map = {row["task_id"]: row for row in rows}
                if (
                    set(case_map) != {main.task_id, race.task_id}
                    or case_map[main.task_id]["case_id"] != main.case_id
                    or case_map[race.task_id]["case_id"] != race.case_id
                    or case_map[main.task_id]["revision"] != 4
                    or case_map[race.task_id]["revision"] != 3
                    or json.loads(case_map[main.task_id]["request_json"])
                    != helper.REQUEST.payload()
                ):
                    raise core.GateError("independent_reconciliation_failed")
            truth = helper.supplier_truth(work / "supplier.sqlite3")
            if (
                truth["applied_calls"] != 1
                or len(truth["mutation_receipts"]) != 1
                or truth["mutation_receipts"][0]["effect_id"] != proof["effect_id"]
            ):
                raise core.GateError("independent_reconciliation_failed")
            with closing(
                settings(prompt_schema, True).connect(application_name="continuity-test")
            ) as owner:
                rows = owner.execute(
                    sql.SQL("SELECT canonical_payload,payload_digest FROM {}.prompts").format(
                        sql.Identifier(prompt_schema)
                    )
                ).fetchall()
                if len(rows) != 3:
                    raise core.GateError("independent_reconciliation_failed")
                expected = {p["responseId"]: p for p in prompts}
                for row in rows:
                    payload = json.loads(row["canonical_payload"])
                    if (
                        payload != expected[payload["responseId"]]
                        or hashlib.sha256(row["canonical_payload"].encode()).hexdigest()
                        != row["payload_digest"]
                    ):
                        raise core.GateError("independent_reconciliation_failed")
                count = owner.execute(
                    sql.SQL("SELECT prompt_count FROM {}.prompt_admission").format(
                        sql.Identifier(prompt_schema)
                    )
                ).fetchone()
                if count is None or count["prompt_count"] != 3:
                    raise core.GateError("independent_reconciliation_failed")
                for table, privilege, allowed in (
                    ("prompts", "SELECT", True),
                    ("prompts", "INSERT", True),
                    ("prompts", "UPDATE", False),
                    ("prompts", "DELETE", False),
                    ("prompt_metadata", "UPDATE", False),
                ):
                    row = owner.execute(
                        "SELECT has_table_privilege(%s,%s,%s) AS allowed",
                        [
                            "livekit_lab",
                            sql.Identifier(prompt_schema, table).as_string(owner),
                            privilege,
                        ],
                    ).fetchone()
                    if row is None or row["allowed"] is not allowed:
                        raise core.GateError("runtime_privilege_failed")
            with closing(
                settings(inbox_schema, True).connect(application_name="continuity-test")
            ) as owner:
                count = owner.execute(
                    sql.SQL("SELECT count(*) AS count FROM {}.inbox").format(
                        sql.Identifier(inbox_schema)
                    )
                ).fetchone()
                if count is None or count["count"] != 6:
                    raise core.GateError("independent_reconciliation_failed")
                row = owner.execute(
                    sql.SQL(
                        "SELECT operation_key::text FROM {}.processing_intents WHERE receipt_id=%s"
                    ).format(sql.Identifier(inbox_schema)),
                    [proof["retained_receipt"]["receiptId"]],
                ).fetchone()
                if row is None or row["operation_key"] != proof["command_id"]:
                    raise core.GateError("independent_reconciliation_failed")
            observed.extend(CASE_NAMES[-4:-1])
        finally:
            if race_task is not None:
                await asyncio.gather(race_task, return_exceptions=True)
            if bridge is not None:
                await bridge.close()
                if bridge.pending_count or bridge.metrics()["sockets"]:
                    raise core.GateError("cleanup_incomplete")
            else:
                for control in controls:
                    await control.close()
            if client is not None:
                await client.close()
            for schema, marker in reversed(schemas):
                with closing(
                    settings(schema, True).connect(application_name="continuity-test")
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
            state["cleanup_complete"] = True
    observed.append(CASE_NAMES[-1])
    if observed != list(CASE_NAMES):
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
                "case_results": [{"name": n, "status": "passed", "code": "ok"} for n in CASE_NAMES],
                "node_version": node_version,
                "blocking_graph": graph,
                "authority": "public_P1_atomic_exact_quote_command_no_revocation_fence",
                "prompt_registry_version": 1,
            }
        ).encode()
    )


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    started = time.monotonic()
    state = {"cleanup_complete": False}
    target = None
    try:
        target = target_path(
            root, args.report or Path(".local/validation/p2-confirmation/" + uuid4().hex + ".json")
        )
        artifacts = target.with_name(target.stem + "-artifacts")
        artifacts.mkdir(mode=0o700)
        result = asyncio.run(run(root, artifacts, started, state))
    except core.GateError as error:
        result = {
            "status": "failed",
            "mode": MODE,
            "code": error.code,
            "duration_seconds": time.monotonic() - started,
            **state,
        }
    except Exception:  # noqa: BLE001 - fixed safe tooling boundary
        result = {
            "status": "failed",
            "mode": MODE,
            "code": "gate_failed",
            "duration_seconds": time.monotonic() - started,
            **state,
        }
    if target is not None:
        try:
            retain(target, result)
        except OSError:
            result = {
                "status": "failed",
                "mode": MODE,
                "code": "report_write_failed",
                "duration_seconds": time.monotonic() - started,
                **state,
            }
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
