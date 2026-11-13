"""Prove confirmed mutation and completion across fresh installed containers.

Own one isolated PostgreSQL schema, named fixture volume and labelled disposable
containers. Runtime credentials never include owner/bootstrap secrets. Existing
local application state and volumes are preserved. No external model is required.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import secrets
import sys
import tempfile
from contextlib import closing
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
CORE_SOURCE = ROOT / "projects/agent-continuity/python/src/continuity_lab"
sys.path.insert(0, str(ROOT))


def main() -> int:
    if not (CORE_SOURCE / "__init__.py").is_file():
        raise RuntimeError("The canonical continuity source package is required")
    from psycopg import sql

    from continuity_lab.authorization import AuthenticatedActor
    from continuity_lab.case_models import Confirmation, QuoteSnapshot
    from continuity_lab.cutover import cutover
    from continuity_lab.effect_models import DeliveryState, EffectState
    from continuity_lab.execution import ExecutionStore
    from continuity_lab.migrations import migrate
    from continuity_lab.models import BookingChange
    from continuity_lab.postgres_case import PostgresCaseAuthority
    from continuity_lab.postgres_effects import PostgresEffects
    from continuity_lab.postgres_lifecycle import PostgresLifecycle
    from continuity_lab.postgres_migrations import upgrade_v2, upgrade_v3
    from continuity_lab.postgres_settings import PostgresSettings
    from continuity_lab.postgres_store import PostgresExecutionStore
    from continuity_lab.retry_policy import RetryPolicy
    from harness.process_control import OwnedProcess

    spec = importlib.util.spec_from_file_location("phase_e_stack", ROOT / "local-setup/stack.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Local setup unavailable")
    stack = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stack)
    setup = ROOT / "local-setup"
    values = stack.load_settings()
    stack.assert_owned_containers(setup, values)
    base = stack.compose_arguments(setup)

    def command(argv):
        return stack.run(argv, values, setup, 30).strip()

    live = command(base + ["ps", "-q", "control-api"])
    image = command(["docker", "inspect", "--format", "{{.Image}}", live])
    network = stack.PROJECT + "_lab"
    networks = json.loads(
        command(["docker", "inspect", "--format", "{{json .NetworkSettings.Networks}}", live])
    )
    if network not in networks or not image.startswith("sha256:"):
        raise RuntimeError("Owned runtime image/network unavailable")
    run_id = uuid4().hex
    schema = "p1_effect_demo_" + run_id
    volume = "p1-effect-demo-" + run_id
    label = "io.livekit-ecosystem.demo=" + run_id
    owner = PostgresSettings(
        port=int(values["POSTGRES_PORT"]),
        user="continuity_migrator",
        password=values["POSTGRES_MIGRATION_PASSWORD"],
        schema=schema,
    )
    runtime = PostgresSettings(
        port=int(values["POSTGRES_PORT"]), password=values["POSTGRES_PASSWORD"], schema=schema
    )
    now = datetime(2030, 12, 1, tzinfo=UTC)
    actor = AuthenticatedActor("demo-owner", "phase-e-demo")
    parent = ROOT / ".local/phase-e-demo"
    parent.mkdir(mode=0o700, exist_ok=True)
    reports = ROOT / ".local/validation/p1-phase-e"
    reports.mkdir(parents=True, exist_ok=True)
    names = []
    owned_volume = False
    result = None

    def failure_report(name, record):
        try:
            (reports / name).write_text(json.dumps(record, indent=2) + "\n")
        except OSError:
            # Diagnostics cannot replace an original failure. No pass is emitted.
            return

    try:
        with tempfile.TemporaryDirectory(prefix=run_id + "-", dir=parent) as folder_name:
            folder = Path(folder_name)
            database = folder / "source.sqlite3"
            migrate(database, folder / "before-v1.sqlite3")
            source = ExecutionStore(database)
            tasks = [
                source.submit(
                    scope_id=actor.scope_id,
                    idempotency_key=key,
                    request=BookingChange("DEMO-BK-001", date(2030, 12, 10), True),
                ).execution
                for key in ("primary", "cancel")
            ]
            cutover(database, folder / "before-cutover.sqlite3", owner)
            upgrade_v2(owner)
            upgrade_v3(owner)
            executions = PostgresExecutionStore(runtime, clock=lambda: now)
            cases = PostgresCaseAuthority(executions, clock=lambda: now)
            lifecycle = PostgresLifecycle(executions, cases=cases, clock=lambda: now)
            effects = PostgresEffects(executions, cases=cases, clock=lambda: now)
            enrolled = []
            for task in tasks:
                enrolled.append(cases.enroll(actor=actor, task_id=task.task_id))
                lifecycle.manage(
                    scope_id=actor.scope_id,
                    task_id=task.task_id,
                    policy=RetryPolicy(),
                    deadline=now + timedelta(minutes=30),
                )
            expected = {
                path.stem: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(CORE_SOURCE.glob("*.py"))
                if not path.stem.startswith("__")
            }
            environment = {
                "P1_POSTGRES_HOST": "postgres",
                "P1_POSTGRES_PORT": "5432",
                "P1_POSTGRES_DB": "livekit_lab",
                "P1_POSTGRES_USER": "livekit_lab",
                "P1_POSTGRES_PASSWORD": values["POSTGRES_PASSWORD"],
                "P1_POSTGRES_SCHEMA": schema,
                "DEMO_TOKEN": secrets.token_urlsafe(32),
                "DEMO_TASK_ID": tasks[0].task_id,
                "DEMO_CANCEL_TASK_ID": tasks[1].task_id,
                "DEMO_MODULE_HASHES": json.dumps(expected, separators=(",", ":")),
            }
            envfile = folder / "runtime.env"
            fd = os.open(envfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as stream:
                stream.write(
                    "".join(key + "=" + value + "\n" for key, value in environment.items())
                )
            owned_volume = True
            command(["docker", "volume", "create", "--label", label, volume])
            observed = command(
                [
                    "docker",
                    "volume",
                    "inspect",
                    "--format",
                    '{{ index .Labels "io.livekit-ecosystem.demo" }}',
                    volume,
                ]
            )
            if observed != run_id:
                raise RuntimeError("Fixture volume ownership mismatch")
            bootstrap_name = "p1-e-" + run_id + "-volume"
            names.append(bootstrap_name)
            command(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--name",
                    bootstrap_name,
                    "--label",
                    label,
                    "--network",
                    "none",
                    "--user",
                    "0:0",
                    "--mount",
                    "type=volume,src=" + volume + ",dst=/data",
                    image,
                    "chown",
                    "10001:10001",
                    "/data",
                ]
            )
            stages = []

            def stage(phase, expected_exit=0):
                name = "p1-e-" + run_id + "-" + phase
                names.append(name)
                argv = [
                    "docker",
                    "run",
                    "--rm",
                    "--init",
                    "--name",
                    name,
                    "--label",
                    label,
                    "--network",
                    network,
                    "--env-file",
                    str(envfile),
                    "--read-only",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges:true",
                    "--tmpfs",
                    "/tmp:rw,nosuid,size=32m,mode=1777",
                    "--mount",
                    "type=volume,src=" + volume + ",dst=/data",
                    "--memory",
                    "256m",
                    "--pids-limit",
                    "64",
                    "--workdir",
                    "/tmp",
                    image,
                    "python",
                    "/app/local-setup/scripts/effect_probe.py",
                    phase,
                ]
                with OwnedProcess(
                    argv,
                    cwd=ROOT,
                    env=stack.child_environment(values),
                    output_directory=folder / phase,
                    max_output_bytes=131072,
                ) as child:

                    def tail(stream):
                        try:
                            return child.output_tail(
                                stream,
                                maximum_bytes=8192,
                                redact_values=tuple(
                                    environment[k] for k in ("P1_POSTGRES_PASSWORD", "DEMO_TOKEN")
                                ),
                            )
                        except Exception:  # noqa: BLE001 - evidence failure cannot hide the original
                            return "unavailable"

                    try:
                        observed = child.wait(timeout=90)
                        output = tail("stdout")
                        if observed.returncode != expected_exit:
                            raise RuntimeError("Installed demo stage failed")
                        record = json.loads(output)
                        assert record["status"] == (
                            "passed" if expected_exit == 0 else "crashed_as_planned"
                        )
                        record["exit_code"] = observed.returncode
                    except Exception:
                        failure_report(
                            "failed-" + run_id + "-" + phase + ".json",
                            {
                                "phase": phase,
                                "exit": child.returncode,
                                "stdout": tail("stdout"),
                                "stderr": tail("stderr"),
                            },
                        )
                        raise
                stages.append(record)
                return record

            seeded = stage("seed")
            provider = seeded["provider_id"]
            with envfile.open("a") as stream:
                stream.write("DEMO_SUPPLIER_ID=" + provider + "\n")
            revision = seeded["expected_supplier_revision"]
            assert revision == 0
            intents = []
            for task, case in zip(tasks, enrolled, strict=True):
                quote = QuoteSnapshot(
                    str(uuid4()),
                    case.task_id,
                    case.revision,
                    case.request.booking_reference,
                    case.request.new_check_in,
                    2500,
                    "USD",
                    (now + timedelta(minutes=5)).isoformat(),
                    case.case_id,
                    revision,
                    provider,
                )
                cases.publish_quote(actor=actor, quote=quote)
                intents.append(
                    cases.commit_intent(
                        actor=actor,
                        confirmation=Confirmation(quote, True),
                        command_id="confirm-" + task.task_id,
                    )
                )
            stage("crash-apply", 71)
            reserved = effects.get(scope_id=actor.scope_id, task_id=tasks[0].task_id)
            assert (
                reserved is not None
                and reserved.state == EffectState.DISPATCHED
                and reserved.dispatch_count == 1
            )
            assert effects.completion(actor=actor, task_id=tasks[0].task_id) is None
            stage("reconcile")
            success = effects.get(scope_id=actor.scope_id, task_id=tasks[0].task_id)
            cancelled = effects.get(scope_id=actor.scope_id, task_id=tasks[1].task_id)
            assert (
                success is not None
                and success.state == EffectState.SUCCEEDED
                and success.intent == intents[0]
                and success.dispatch_count == 1
            )
            assert (
                cancelled is not None
                and cancelled.state == EffectState.CANCELLED
                and cancelled.dispatch_count == 0
            )
            event = effects.completion(actor=actor, task_id=tasks[0].task_id)
            assert event is not None
            stage("crash-deliver", 72)
            pending = effects.delivery(actor=actor, task_id=tasks[0].task_id)
            assert (
                pending is not None
                and pending.state == DeliveryState.DELIVERING
                and pending.attempts == 1
            )
            stage("verify")
            delivered = effects.delivery(actor=actor, task_id=tasks[0].task_id)
            assert (
                delivered is not None
                and delivered.state == DeliveryState.DELIVERED
                and delivered.attempts == 2
            )
            assert effects.completion(actor=actor, task_id=tasks[0].task_id) == event
            assert effects.get(scope_id=actor.scope_id, task_id=tasks[0].task_id) == success
            receipt = cutover(database, folder / "before-cutover.sqlite3", owner)
            assert receipt.state == "active"
            result = {
                "status": "passed",
                "mode": "local_synthetic",
                "runtime_containers": 5,
                "installed_modules": len(expected),
                "module_hashes": expected,
                "source_digest": hashlib.sha256(
                    json.dumps(expected, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
                "supplier_commit_exit": 71,
                "receiver_commit_exit": 72,
                "physical_mutations": 1,
                "logical_receiver_events": 1,
                "cancelled_dispatches": 0,
                "event_identity_preserved": True,
                "outcome_unchanged_by_delivery": True,
                "diagnostic_prune_retains_dedup": True,
                "cutover_receipt_preserved_at_v3": True,
                "live_m1_backend": "unchanged",
                "stages": stages,
            }
    finally:
        # A Docker failure must not prevent independent database cleanup, or hide
        # the original stage failure. Only this run's checked resources qualify.
        cleanup_failures = []
        for name in names:
            try:
                found = command(
                    [
                        "docker",
                        "ps",
                        "-aq",
                        "--filter",
                        "name=^/" + name + "$",
                        "--filter",
                        "label=" + label,
                    ]
                )
                if found:
                    command(["docker", "rm", "-f", found])
            except Exception:  # noqa: BLE001 - continue independent owned cleanup
                cleanup_failures.append("owned_container_cleanup_failed")
        if owned_volume:
            try:
                observed = command(
                    [
                        "docker",
                        "volume",
                        "inspect",
                        "--format",
                        '{{ index .Labels "io.livekit-ecosystem.demo" }}',
                        volume,
                    ]
                )
                if observed != run_id or volume != "p1-effect-demo-" + run_id:
                    raise RuntimeError("Refuse to remove unowned fixture volume")
                command(["docker", "volume", "rm", volume])
            except Exception:  # noqa: BLE001 - database cleanup is still independent
                cleanup_failures.append("owned_volume_cleanup_failed")
        try:
            if schema != "p1_effect_demo_" + run_id or len(run_id) != 32:
                raise RuntimeError("Refuse to remove unowned schema")
            with closing(owner.connect(application_name="continuity-migrate")) as connection:
                connection.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
                )
        except Exception:  # noqa: BLE001 - record cleanup separately from original failure
            cleanup_failures.append("owned_schema_cleanup_failed")
        if cleanup_failures:
            failure_report(
                "failed-" + run_id + "-cleanup.json",
                {"status": "failed", "codes": cleanup_failures},
            )
            if sys.exc_info()[0] is None:
                raise RuntimeError("Owned cleanup did not complete")
    assert result is not None
    result["cleanup_verified"] = True
    (reports / "container-demo.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - secret-safe operator boundary
        print(
            '{"status":"failed","code":"phase_e_demo_failed","action":"check_role_setup_and_rebuild_stack"}'
        )
        sys.exit(1)
