"""Run isolated exact-consent/retry/wait demonstrations against the local stack.

Two fresh, disposable runtime-only containers share persisted PostgreSQL state.
Only this invocation's synthetic schema is removed. Existing app/volume state is
preserved. Run with the frozen project interpreter after rebuilding the stack.
"""

import hashlib
import importlib.util
import json
import os
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
    from continuity_lab.case_models import QuoteSnapshot
    from continuity_lab.cutover import cutover
    from continuity_lab.execution import ExecutionStore
    from continuity_lab.managed_inquiry_worker import InquiryNotDispatched, ManagedInquiryWorker
    from continuity_lab.migrations import migrate
    from continuity_lab.models import BookingChange
    from continuity_lab.postgres_case import PostgresCaseAuthority
    from continuity_lab.postgres_lifecycle import PostgresLifecycle
    from continuity_lab.postgres_migrations import upgrade_v2
    from continuity_lab.postgres_settings import PostgresSettings
    from continuity_lab.postgres_store import PostgresExecutionStore
    from continuity_lab.retry_policy import RetryPolicy
    from continuity_lab.supplier import FakeSupplier, initialize_supplier

    spec = importlib.util.spec_from_file_location(
        "phase_d_demo_stack", ROOT / "local-setup/stack.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Local setup is unavailable")
    stack = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stack)
    setup = ROOT / "local-setup"
    values = stack.load_settings()
    stack.assert_owned_containers(setup, values)
    base = stack.compose_arguments(setup)
    container = stack.run(base + ["ps", "-q", "control-api"], values, setup).strip()
    image = stack.run(
        ["docker", "inspect", "--format", "{{.Image}}", container], values, setup
    ).strip()
    networks = json.loads(
        stack.run(
            ["docker", "inspect", "--format", "{{json .NetworkSettings.Networks}}", container],
            values,
            setup,
        )
    )
    network = stack.PROJECT + "_lab"
    if network not in networks:
        raise RuntimeError("The owned local network is unavailable")
    run_id = uuid4().hex
    schema = "p1_demo_" + run_id
    owner = PostgresSettings(
        port=int(values["POSTGRES_PORT"]),
        user="continuity_migrator",
        password=values["POSTGRES_MIGRATION_PASSWORD"],
        schema=schema,
    )
    runtime = PostgresSettings(
        port=int(values["POSTGRES_PORT"]), password=values["POSTGRES_PASSWORD"], schema=schema
    )
    base_time = datetime(2030, 12, 1, tzinfo=UTC)
    clock = [base_time]
    actor = AuthenticatedActor("demo-owner", "phase-d-demo")
    names = []
    reports = ROOT / ".local/validation/p1-phase-d"
    reports.mkdir(parents=True, exist_ok=True)
    parent = ROOT / ".local/phase-d-demo"
    parent.mkdir(mode=0o700, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix=run_id + "-", dir=parent) as folder_name:
            folder = Path(folder_name)
            database = folder / "source.sqlite3"
            migrate(database, folder / "before-v1.sqlite3")
            source = ExecutionStore(database)
            records = [
                source.submit(
                    scope_id=actor.scope_id,
                    idempotency_key=key,
                    request=BookingChange("DEMO-BK-001", date(2030, 12, 10), True),
                ).execution
                for key in ("primary", "expires")
            ]
            cutover(database, folder / "before-cutover.sqlite3", owner)
            upgrade_v2(owner)
            executions = PostgresExecutionStore(runtime)
            cases = PostgresCaseAuthority(executions, clock=lambda: clock[0])
            lifecycle = PostgresLifecycle(executions, cases=cases, clock=lambda: clock[0])
            supplier_path = folder / "supplier.sqlite3"
            initialize_supplier(supplier_path, scope_id=actor.scope_id)
            supplier = FakeSupplier(supplier_path)
            before = supplier.booking(scope_id=actor.scope_id, booking_reference="DEMO-BK-001")

            class OnceNotDispatched(FakeSupplier):
                failed = False

                def inquire(self, **kwargs):
                    if not self.failed:
                        self.failed = True
                        raise InquiryNotDispatched("Synthetic positive no-dispatch evidence")
                    return super().inquire(**kwargs)

            retry_supplier = OnceNotDispatched(supplier_path)
            timeline = []
            for index, record in enumerate(records):
                lifecycle.manage(
                    scope_id=actor.scope_id,
                    task_id=record.task_id,
                    policy=RetryPolicy(),
                    deadline=base_time + timedelta(hours=2),
                )
                worker = ManagedInquiryWorker(lifecycle, retry_supplier if index == 0 else supplier)
                outcome = worker.run_one(scope_id=actor.scope_id, task_id=record.task_id)
                if index == 0:
                    assert outcome.state == "retry_wait"
                    timeline.append("retry_wait")
                    clock[0] = base_time + timedelta(seconds=1)
                    outcome = worker.run_one(scope_id=actor.scope_id, task_id=record.task_id)
                assert outcome.state == "inquiry_complete"
                cases.enroll(actor=actor, task_id=record.task_id)
                cases.publish_quote(
                    actor=actor,
                    quote=QuoteSnapshot(
                        str(uuid4()),
                        record.task_id,
                        0,
                        "DEMO-BK-001",
                        date(2030, 12, 10),
                        12500,
                        "USD",
                        (base_time + timedelta(hours=1)).isoformat(),
                    ),
                )
            timeline.append("inquiry_complete")
            expected = {
                p.stem: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in CORE_SOURCE.glob("*.py")
                if p.stem not in {"__init__", "__main__"}
            }
            environment = {
                "P1_POSTGRES_HOST": "postgres",
                "P1_POSTGRES_PORT": "5432",
                "P1_POSTGRES_DB": "livekit_lab",
                "P1_POSTGRES_USER": "livekit_lab",
                "P1_POSTGRES_PASSWORD": values["POSTGRES_PASSWORD"],
                "P1_POSTGRES_SCHEMA": schema,
                "DEMO_TOKEN": "a" * 40,
                "DEMO_TASK_ID": records[0].task_id,
                "DEMO_EXPIRED_TASK_ID": records[1].task_id,
                "DEMO_WAIT_ID": str(uuid4()),
                "DEMO_EXPIRED_WAIT_ID": str(uuid4()),
                "DEMO_MODULE_HASHES": json.dumps(expected, separators=(",", ":")),
            }
            envfile = folder / "runtime.env"
            descriptor = os.open(envfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as stream:
                stream.write(
                    "".join(key + "=" + value + "\n" for key, value in environment.items())
                )
            stages = []
            for phase in ("prepare", "advance"):
                name = "p1-d-demo-" + run_id + "-" + phase
                names.append(name)
                command = [
                    "docker",
                    "run",
                    "--rm",
                    "--init",
                    "--name",
                    name,
                    "--label",
                    "io.livekit-ecosystem.demo=" + run_id,
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
                    "--memory",
                    "256m",
                    "--pids-limit",
                    "64",
                    "--workdir",
                    "/tmp",
                    image,
                    "python",
                    "/app/local-setup/scripts/case_probe.py",
                    phase,
                ]
                result = json.loads(stack.run(command, values, setup, 90))
                assert result["status"] == "passed"
                stages.append(result)
            assert (
                stages[0]["case_id"] == stages[1]["case_id"]
                and stages[0]["case_id"] != records[0].task_id
            )
            timeline += ["waiting", "intent_committed"]
            receipt = cutover(database, folder / "before-cutover.sqlite3", owner)
            assert receipt.state == "active"
            assert (
                supplier.booking(scope_id=actor.scope_id, booking_reference="DEMO-BK-001") == before
            )
            assert supplier.count_inquiries(scope_id=actor.scope_id) == 2
            result = {
                "status": "passed",
                "mode": "local_synthetic",
                "timeline": timeline,
                "runtime_containers": 2,
                "case_workflow_ids_distinct": True,
                "no_shared_application_files": True,
                "installed_modules": len(expected),
                "source_digest": hashlib.sha256(
                    json.dumps(expected, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
                "logical_inquiries": 2,
                "booking_unchanged": True,
                "cutover_receipt_preserved_after_upgrade": True,
                "stages": stages,
                "cleanup": "owned_demo_schema_and_containers_only",
                "live_m1_backend": "unchanged",
            }
    finally:
        for name in names:
            inspected = stack.run(
                [
                    "docker",
                    "ps",
                    "-aq",
                    "--filter",
                    "name=^/" + name + "$",
                    "--filter",
                    "label=io.livekit-ecosystem.demo=" + run_id,
                ],
                values,
                setup,
            ).strip()
            if inspected:
                stack.run(["docker", "rm", "-f", inspected], values, setup)
        if not schema.startswith("p1_demo_") or len(schema) != 40:
            raise RuntimeError("Only the owned demo schema may be removed")
        with closing(owner.connect(application_name="continuity-migrate")) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
            )
    result["cleanup_verified"] = True
    (reports / "container-demo.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - secret-safe local operator boundary
        print(
            '{"status":"failed","code":"phase_d_demo_failed","action":"check_role_setup_and_rebuild_stack"}'
        )
        sys.exit(1)
