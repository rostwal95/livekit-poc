"""Prove the actual leased P1 profile across stop/start and preserved fixtures.

This invocation owns one UUID-labelled fixture volume, two worker containers,
short-lived profile probes and one isolated schema. Existing M1 volumes are never
mounted. Passing evidence is written only after independent owned cleanup.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import secrets
import sys
import tempfile
import time
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
    from prometheus_client.parser import text_string_to_metric_families
    from psycopg import sql

    from continuity_lab.authorization import (
        AuthenticatedActor,
        BearerToken,
        ScopedInquiryService,
        TokenDirectory,
    )
    from continuity_lab.case_models import Confirmation, QuoteSnapshot
    from continuity_lab.case_service import ScopedCaseService
    from continuity_lab.cutover import cutover
    from continuity_lab.effect_models import CancellationDisposition, DeliveryState, EffectState
    from continuity_lab.execution import ExecutionStore
    from continuity_lab.execution_cli import _CODES, _EVENTS
    from continuity_lab.lease_models import CoordinationPolicy
    from continuity_lab.lifecycle_models import LifecycleState, WaitState
    from continuity_lab.migrations import migrate
    from continuity_lab.models import BookingChange, IntakeCapacityExceeded
    from continuity_lab.postgres_case import PostgresCaseAuthority
    from continuity_lab.postgres_effects import PostgresEffects
    from continuity_lab.postgres_lifecycle import PostgresLifecycle
    from continuity_lab.postgres_migrations import (
        read_import_state,
        upgrade_v2,
        upgrade_v3,
        upgrade_v4,
    )
    from continuity_lab.postgres_settings import PostgresSettings
    from continuity_lab.postgres_store import PostgresExecutionStore
    from continuity_lab.retry_policy import RetryPolicy
    from harness.process_control import OwnedProcess

    spec = importlib.util.spec_from_file_location("phase_f_stack", ROOT / "local-setup/stack.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Local setup is unavailable")
    stack = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stack)
    setup = ROOT / "local-setup"
    values = stack.load_settings()
    stack.assert_owned_containers(setup, values)
    base = stack.compose_arguments(setup)

    def control(argv):
        return stack.run(argv, values, setup, 30).strip()

    live = control(base + ["ps", "-q", "control-api"])
    image = control(["docker", "inspect", "--format", "{{.Image}}", live])
    tagged = control(
        [
            "docker",
            "image",
            "inspect",
            "--format",
            "{{.Id}}",
            stack.image_name("python"),
        ]
    )
    network = stack.PROJECT + "_lab"
    networks = json.loads(
        control(["docker", "inspect", "--format", "{{json .NetworkSettings.Networks}}", live])
    )
    if image != tagged or not image.startswith("sha256:") or network not in networks:
        raise RuntimeError("The profile image and owned runtime network must match the live stack")
    run_id = uuid4().hex
    schema = "p1_worker_demo_" + run_id
    volume = "p1-worker-demo-" + run_id
    label_key = "io.livekit-ecosystem.demo"
    label = label_key + "=" + run_id
    owner = PostgresSettings(
        port=int(values["POSTGRES_PORT"]),
        user="continuity_migrator",
        password=values["POSTGRES_MIGRATION_PASSWORD"],
        schema=schema,
    )
    runtime = PostgresSettings(
        port=int(values["POSTGRES_PORT"]), password=values["POSTGRES_PASSWORD"], schema=schema
    )
    actor = AuthenticatedActor("demo-owner", "phase-f-demo")
    token = BearerToken(secrets.token_urlsafe(32))
    directory = TokenDirectory({token: actor})
    parent = ROOT / ".local/phase-f-demo"
    parent.mkdir(mode=0o700, exist_ok=True)
    reports = ROOT / ".local/validation/p1-phase-f"
    reports.mkdir(parents=True, exist_ok=True)
    secret_values = tuple(
        dict.fromkeys([values[key] for key in stack.SECRET_KEYS if values.get(key)] + [token.value])
    )
    names = []
    worker_names: list[str] = []
    volume_candidate = False
    result = None
    state = {"stage": "prepare"}
    timeline: list[str] = []

    def redact(value):
        for private in secret_values:
            value = value.replace(private, "[redacted]")
        return value

    def failure_report(name, record):
        try:
            (reports / name).write_text(json.dumps(record, indent=2) + "\n")
        except OSError:
            return  # Diagnostic failure cannot replace the original error.

    def check(condition, code):
        if not condition:
            state["invariant"] = code
            raise RuntimeError("A declared demo invariant failed")

    try:
        with tempfile.TemporaryDirectory(prefix=run_id + "-", dir=parent) as folder_name:
            folder = Path(folder_name)
            commands = [0]

            def command(argv, *, expected_exit=0, timeout=30, include_stderr=False):
                commands[0] += 1
                if commands[0] > 2000:
                    raise RuntimeError("Demo command count exceeded its bound")
                output_directory = folder / ("command-" + str(commands[0]))
                with OwnedProcess(
                    argv,
                    cwd=ROOT,
                    env=stack.child_environment(values),
                    output_directory=output_directory,
                    max_output_bytes=262144,
                ) as child:

                    def tail(stream):
                        try:
                            return child.output_tail(
                                stream, maximum_bytes=8192, redact_values=secret_values
                            )
                        except Exception:  # noqa: BLE001 - preserve original observation failure
                            return "unavailable"

                    try:
                        observed = child.wait(timeout=timeout)
                        if observed.returncode != expected_exit:
                            raise RuntimeError("Demo command returned an unexpected status")

                        def read_output(stream):
                            fd = os.open(
                                output_directory / (stream + ".bin"), os.O_RDONLY | os.O_NOFOLLOW
                            )
                            with os.fdopen(fd, "rb") as source_stream:
                                payload = source_stream.read(131073)
                            if len(payload) > 131072:
                                raise RuntimeError("Demo result exceeded its finite byte bound")
                            return payload.decode("utf-8").strip()

                        stdout = read_output("stdout")
                        if include_stderr:
                            return "\n".join(
                                part for part in (stdout, read_output("stderr")) if part
                            )
                        return stdout
                    except Exception:
                        failure_report(
                            "failed-" + run_id + "-command-" + str(commands[0]) + ".json",
                            {
                                "stage": state["stage"],
                                "exit": child.returncode,
                                "stdout": tail("stdout"),
                                "stderr": tail("stderr"),
                            },
                        )
                        raise

            try:
                source_db = folder / "source.sqlite3"
                migrate(source_db, folder / "before-v1.sqlite3")
                source = ExecutionStore(source_db)
                request = BookingChange("DEMO-BK-001", date(2030, 12, 10), True)
                tasks = [
                    source.submit(
                        scope_id=actor.scope_id, idempotency_key=key, request=request
                    ).execution
                    for key in ("primary", "waiting")
                ]
                cutover(source_db, folder / "before-cutover.sqlite3", owner)
                upgrade_v2(owner)
                upgrade_v3(owner)
                upgrade_v4(owner, policy=CoordinationPolicy(2, 1, 10, 30))
                executions = PostgresExecutionStore(runtime)
                cases = PostgresCaseAuthority(executions)
                lifecycle = PostgresLifecycle(executions, cases=cases)
                effects = PostgresEffects(executions, cases=cases)
                service = ScopedCaseService(directory, cases, lifecycle, effects=effects)
                inquiry = ScopedInquiryService(directory, executions)
                enrolled = []
                deadline = datetime.now(UTC) + timedelta(seconds=180)
                for task in tasks:
                    enrolled.append(service.enroll(token=token, task_id=task.task_id))
                    lifecycle.manage(
                        scope_id=actor.scope_id,
                        task_id=task.task_id,
                        policy=RetryPolicy(),
                        deadline=deadline,
                    )
                expected = {
                    path.stem: hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in sorted(CORE_SOURCE.glob("*.py"))
                    if not path.stem.startswith("__")
                }
                check(
                    len(expected) >= 44
                    and all(
                        name in expected
                        for name in (
                            "postgres_leases",
                            "worker_runtime",
                            "api",
                            "postgres_api",
                            "testing",
                        )
                    ),
                    "installed_core_module_inventory",
                )
                envfile = folder / "profile.env"
                fd = os.open(envfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as stream:
                    stream.write(
                        "POSTGRES_PASSWORD="
                        + values["POSTGRES_PASSWORD"]
                        + "\nP1_WORKER_SCHEMA="
                        + schema
                        + "\nP1_WORKER_SCOPE="
                        + actor.scope_id
                        + "\n"
                    )
                profile = base + ["--env-file", str(envfile), "--profile", "p1-workers"]
                volume_candidate = True
                command(["docker", "volume", "create", "--label", label, volume])
                observed = command(
                    [
                        "docker",
                        "volume",
                        "inspect",
                        "--format",
                        '{{ index .Labels "' + label_key + '" }}',
                        volume,
                    ]
                )
                check(observed == run_id, "owned_fixture_volume_label")
                bootstrap = "p1-f-" + run_id + "-volume"
                names.append(bootstrap)
                command(
                    [
                        "docker",
                        "run",
                        "--rm",
                        "--name",
                        bootstrap,
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

                def profile_run(
                    name,
                    *,
                    detached=False,
                    remove=False,
                    state_path="/data/worker-a.json",
                    extra=(),
                ):
                    names.append(name)
                    argv = profile + [
                        "run",
                        "--no-deps",
                        "--name",
                        name,
                        "--label",
                        label,
                        "--volume",
                        volume + ":/data",
                        "-e",
                        "P1_POSTGRES_SCHEMA=" + schema,
                        "-e",
                        "P1_WORKER_SCOPE=" + actor.scope_id,
                        "-e",
                        "P1_WORKER_STATE_FILE=" + state_path,
                    ]
                    if detached:
                        argv.append("-d")
                    if remove:
                        argv.append("--rm")
                    return argv + ["p1-worker"] + list(extra)

                initialized = json.loads(
                    command(
                        profile_run(
                            "p1-f-" + run_id + "-init",
                            remove=True,
                            extra=("python", "-m", "continuity_lab.worker_cli", "init-fixtures"),
                        )
                    )
                )
                check(initialized["status"] == "fixtures_ready", "profile_fixture_initialization")
                name_a = "p1-f-" + run_id + "-a"
                name_b = "p1-f-" + run_id + "-b"
                workers = [name_a]
                worker_names.append(name_a)
                state["stage"] = "initial-inquiry"
                command(profile_run(name_a, detached=True))

                def inspect_worker(name):
                    details = json.loads(command(["docker", "inspect", name]))[0]
                    check(details["Image"] == image, "profile_uses_exact_built_image")
                    check(
                        any(
                            mount.get("Type") == "volume"
                            and mount.get("Name") == volume
                            and mount.get("Destination") == "/data"
                            for mount in details["Mounts"]
                        ),
                        "profile_uses_owned_fixture_volume",
                    )
                    check(
                        network in details["NetworkSettings"]["Networks"],
                        "profile_uses_owned_network",
                    )
                    environment = details["Config"]["Env"]
                    check(
                        not any(
                            item.startswith(
                                (
                                    "P1_MIGRATION_",
                                    "POSTGRES_ADMIN_PASSWORD=",
                                    "POSTGRES_MIGRATION_PASSWORD=",
                                )
                            )
                            for item in environment
                        ),
                        "runtime_credentials_only",
                    )
                    return details

                maximum_active = [0]
                active_samples = [0]

                def sample_active():
                    with executions._connection() as connection:
                        row = connection.execute(
                            sql.SQL(
                                "SELECT COUNT(*) AS n FROM {} WHERE expires_at>clock_timestamp()"
                            ).format(sql.Identifier(schema, "execution_leases"))
                        ).fetchone()
                    check(
                        row is not None and type(row["n"]) is int and row["n"] <= 1,
                        "persisted_global_active_cap",
                    )
                    assert row is not None
                    maximum_active[0] = max(maximum_active[0], row["n"])
                    active_samples[0] += 1
                    return row["n"]

                def poll(stage, predicate):
                    state["stage"] = stage
                    due = time.monotonic() + 45
                    while time.monotonic() < due:
                        sample_active()
                        for name in workers:
                            check(
                                inspect_worker(name)["State"]["Running"],
                                "worker_running_during_progress",
                            )
                        if predicate():
                            timeline.append(stage)
                            return
                        time.sleep(0.1)
                    check(False, "bounded_progress_" + stage)

                def health(name, expected="ready"):
                    code = 0 if expected == "ready" else 1
                    record = json.loads(
                        command(
                            [
                                "docker",
                                "exec",
                                name,
                                "python",
                                "-m",
                                "continuity_lab.worker_cli",
                                "health",
                            ],
                            expected_exit=code,
                        )
                    )
                    check(record["status"] == expected, "actual_worker_health")
                    return record

                def probe(name):
                    record = json.loads(
                        command(
                            [
                                "docker",
                                "exec",
                                "--workdir",
                                "/tmp",
                                "-e",
                                "DEMO_MODULE_HASHES=" + json.dumps(expected, separators=(",", ":")),
                                name,
                                "python",
                                "/app/local-setup/scripts/worker_probe.py",
                            ]
                        )
                    )
                    check(
                        record["status"] == "passed"
                        and record["module_hashes_verified"]
                        and record["installed_modules"] == len(expected),
                        "installed_package_proof",
                    )
                    return record

                poll(
                    "two-inquiries-complete",
                    lambda: (
                        all(
                            lifecycle.get(scope_id=actor.scope_id, task_id=task.task_id).state
                            == LifecycleState.INQUIRY_COMPLETE
                            for task in tasks
                        )
                        and sample_active() == 0
                    ),
                )
                health(name_a)
                initial = probe(name_a)
                check(
                    initial["inquiries"] == 2
                    and initial["booking_revision"]
                    == initial["mutations"]
                    == initial["apply_calls"]
                    == initial["receiver_events"]
                    == 0,
                    "same_authority_initial_inquiry_truth",
                )
                check(
                    initial["supplier_id"] == initialized["provider_id"],
                    "supplier_identity_preserved",
                )
                quotes = []
                wait_ids = []
                issued = datetime.now(UTC)
                for case in enrolled:
                    quote = QuoteSnapshot(
                        str(uuid4()),
                        case.task_id,
                        case.revision,
                        case.request.booking_reference,
                        case.request.new_check_in,
                        2500,
                        "USD",
                        (issued + timedelta(seconds=120)).isoformat(),
                        case.case_id,
                        0,
                        initial["supplier_id"],
                    )
                    cases.publish_quote(actor=actor, quote=quote)
                    wait_id = str(uuid4())
                    service.arm_wait(
                        token=token,
                        task_id=case.task_id,
                        wait_id=wait_id,
                        quote=quote,
                        deadline=issued + timedelta(seconds=110),
                    )
                    quotes.append(quote)
                    wait_ids.append(wait_id)
                poll(
                    "two-durable-waits",
                    lambda: (
                        all(
                            lifecycle.get(scope_id=actor.scope_id, task_id=task.task_id).state
                            == LifecycleState.WAITING
                            and service.get(token=token, task_id=task.task_id).intent is None
                            for task in tasks
                        )
                        and sample_active() == 0
                    ),
                )
                rejected = False
                try:
                    inquiry.submit(token=token, idempotency_key="third", request=request)
                except IntakeCapacityExceeded:
                    rejected = True
                check(rejected, "outstanding_cap_rejects_new_acceptance")
                replay = inquiry.submit(token=token, idempotency_key="primary", request=request)
                check(
                    not replay.created and replay.execution.task_id == tasks[0].task_id,
                    "known_replay_at_capacity",
                )
                with executions._connection() as connection:
                    retained = connection.execute(
                        sql.SQL("SELECT COUNT(*) AS n FROM {}").format(
                            sql.Identifier(schema, "tasks")
                        )
                    ).fetchone()
                check(
                    retained is not None and retained["n"] == 2,
                    "rejected_work_has_no_durable_acknowledgement",
                )

                metric_records = []

                def metrics(name, phase):
                    text = command(
                        [
                            "docker",
                            "exec",
                            name,
                            "python",
                            "-m",
                            "continuity_lab.worker_cli",
                            "metrics",
                        ]
                    )
                    positive: dict[str, float] = {}
                    for family in text_string_to_metric_families(text):
                        for sample in family.samples:
                            check(
                                sample.name.startswith("continuity_worker_"), "fixed_metric_names"
                            )
                            check(
                                set(sample.labels) <= {"kind", "outcome", "code", "le"},
                                "fixed_metric_label_keys",
                            )
                            for key, value in sample.labels.items():
                                allowed = {
                                    "kind": {"inquiry", "wait", "mutation", "delivery"},
                                    "outcome": {
                                        "acquired",
                                        "empty",
                                        "stopped",
                                        "completed",
                                        "failed",
                                        "timed_out",
                                    },
                                    "code": {"lease_lost", "lease_busy", "lease_required"},
                                }
                                if key == "le":
                                    check(
                                        value == "+Inf"
                                        or (
                                            math.isfinite(float(value))
                                            and float(value)
                                            in {0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 15}
                                        ),
                                        "fixed_histogram_buckets",
                                    )
                                else:
                                    check(value in allowed[key], "fixed_metric_label_values")
                            check(
                                all(
                                    private not in text
                                    for private in secret_values
                                    + (actor.scope_id, tasks[0].task_id, tasks[1].task_id)
                                ),
                                "metric_privacy",
                            )
                            if sample.value > 0 and sample.name.endswith("_total"):
                                positive[sample.name] = positive.get(sample.name, 0) + sample.value
                    check(
                        positive.get("continuity_worker_claims_total", 0) > 0,
                        "positive_real_worker_metrics",
                    )
                    metric_records.append(
                        {
                            "phase": phase,
                            "positive_counters": positive,
                            "fixed_labels_verified": True,
                            "bytes": len(text.encode()),
                        }
                    )
                    return positive

                metrics(name_a, "a-before-first-stop")
                stopped = []

                def stop_worker(name, state_path, phase):
                    health(name)
                    command(["docker", "stop", "-t", "25", name], timeout=30)
                    details = inspect_worker(name)
                    check(
                        not details["State"]["Running"] and details["State"]["ExitCode"] == 0,
                        "graceful_worker_exit",
                    )
                    copied = folder / (phase + "-health.json")
                    command(["docker", "cp", name + ":" + state_path, str(copied)])
                    info = json.loads(copied.read_text())
                    check(
                        info["ready"] is False and info["active_children"] == 0,
                        "stopped_health_has_no_owned_child",
                    )
                    helper = "p1-f-" + run_id + "-" + phase + "-health"
                    after = json.loads(
                        command(
                            profile_run(
                                helper,
                                remove=True,
                                state_path=state_path,
                                extra=("python", "-m", "continuity_lab.worker_cli", "health"),
                            ),
                            expected_exit=1,
                        )
                    )
                    check(after["status"] == "not_ready", "stopped_worker_not_ready")
                    stopped.append(
                        {"phase": phase, "exit_code": 0, "ready": False, "active_children": 0}
                    )

                state["stage"] = "preserved-wait-stop"
                stop_worker(name_a, "/data/worker-a.json", "a-first")
                workers.clear()
                for index, task in enumerate(tasks):
                    check(
                        service.get(token=token, task_id=task.task_id).intent is None,
                        "no_intent_while_stopped",
                    )
                    observed = service.waits(token=token, task_id=task.task_id)
                    check(
                        len(observed) == 1
                        and observed[0].wait_id == wait_ids[index]
                        and observed[0].state == WaitState.PENDING,
                        "same_wait_retained_after_stop",
                    )
                event_id = str(uuid4())
                signal = service.signal(
                    token=token, event_id=event_id, confirmation=Confirmation(quotes[0], True)
                )
                check(
                    signal.created
                    and signal.consumed_wait_id is None
                    and service.get(token=token, task_id=tasks[0].task_id).intent is None,
                    "signal_persisted_while_worker_stopped",
                )
                command(["docker", "start", name_a])
                workers.append(name_a)
                command(profile_run(name_b, detached=True, state_path="/data/worker-b.json"))
                workers.append(name_b)
                worker_names.append(name_b)

                def primary_delivered():
                    value = service.get_effect(token=token, task_id=tasks[0].task_id)
                    delivery = service.get_delivery(token=token, task_id=tasks[0].task_id)
                    return (
                        value is not None
                        and value.state == EffectState.SUCCEEDED
                        and delivery is not None
                        and delivery.state == DeliveryState.DELIVERED
                    )

                poll("restarted-workers-complete-primary", primary_delivered)
                primary = service.get_effect(token=token, task_id=tasks[0].task_id)
                completion = service.get_completion(token=token, task_id=tasks[0].task_id)
                check(
                    primary is not None
                    and primary.result is not None
                    and primary.result.previous_revision == 0
                    and primary.result.revision == 1
                    and completion is not None
                    and completion.outcome.result == primary.result,
                    "exact_mutation_outcome",
                )
                signal_replay = service.signal(
                    token=token, event_id=event_id, confirmation=Confirmation(quotes[0], True)
                )
                check(
                    not signal_replay.created
                    and signal_replay.signal_id == signal.signal_id
                    and signal_replay.consumed_wait_id == wait_ids[0],
                    "exact_signal_consumed_once",
                )
                with executions._connection() as connection:
                    consumed = connection.execute(
                        sql.SQL("SELECT COUNT(*) AS n FROM {} WHERE signal_id=%s").format(
                            sql.Identifier(schema, "execution_signal_consumptions")
                        ),
                        (signal.signal_id,),
                    ).fetchone()
                check(
                    consumed is not None and consumed["n"] == 1, "one_original_signal_consumption"
                )
                other = service.waits(token=token, task_id=tasks[1].task_id)
                check(
                    len(other) == 1 and other[0].state == WaitState.PENDING,
                    "other_wait_not_advanced",
                )
                third = inquiry.submit(
                    token=token, idempotency_key="third", request=request
                ).execution
                check(
                    third.task_id not in {task.task_id for task in tasks},
                    "new_postgres_acceptance_after_progress",
                )
                service.enroll(token=token, task_id=third.task_id)
                lifecycle.manage(
                    scope_id=actor.scope_id,
                    task_id=third.task_id,
                    policy=RetryPolicy(),
                    deadline=datetime.now(UTC) + timedelta(seconds=90),
                )
                poll(
                    "capacity-freed-for-third-inquiry",
                    lambda: (
                        lifecycle.get(scope_id=actor.scope_id, task_id=third.task_id).state
                        == LifecycleState.INQUIRY_COMPLETE
                    ),
                )
                retained_other_wait = service.waits(token=token, task_id=tasks[1].task_id)
                check(
                    len(retained_other_wait) == 1
                    and retained_other_wait[0].state == WaitState.PENDING
                    and lifecycle.get(scope_id=actor.scope_id, task_id=tasks[1].task_id).state
                    == LifecycleState.WAITING,
                    "other_wait_retained_until_explicit_cancel",
                )
                for task in (tasks[1], third):
                    cancelled = service.cancel(
                        token=token, task_id=task.task_id, command_id="cancel-" + task.task_id
                    )
                    check(
                        cancelled.disposition == CancellationDisposition.BEFORE_COMMIT,
                        "public_cancel_prevents_unconfirmed_mutation",
                    )

                def all_delivered():
                    for task in (tasks[0], tasks[1], third):
                        delivery = service.get_delivery(token=token, task_id=task.task_id)
                        if delivery is None or delivery.state != DeliveryState.DELIVERED:
                            return False
                    return sample_active() == 0

                poll("cancelled-completions-delivered", all_delivered)
                for task in (tasks[1], third):
                    observed = service.get_completion(token=token, task_id=task.task_id)
                    check(
                        observed is not None
                        and observed.outcome.state == EffectState.CANCELLED
                        and observed.outcome.intent_id is None
                        and service.get(token=token, task_id=task.task_id).intent is None,
                        "cancelled_outcome_without_mutation_authority",
                    )
                check(
                    service.get_completion(token=token, task_id=tasks[0].task_id) == completion
                    and service.get_effect(token=token, task_id=tasks[0].task_id) == primary,
                    "primary_outcome_and_event_unchanged",
                )
                final = probe(name_a)
                check(
                    final["inquiries"] == 3
                    and final["receiver_events"] == 3
                    and final["mutations"] == final["apply_calls"] == final["booking_revision"] == 1
                    and final["supplier_id"] == initial["supplier_id"],
                    "retained_supplier_receiver_truth",
                )
                metrics(name_a, "a-before-final-stop")
                metrics(name_b, "b-before-final-stop")
                state["stage"] = "final-graceful-stop"
                stop_worker(name_a, "/data/worker-a.json", "a-final")
                workers.remove(name_a)
                stop_worker(name_b, "/data/worker-b.json", "b-final")
                workers.clear()
                producer_events = set()
                for name in (name_a, name_b):
                    raw = command(["docker", "logs", "--tail", "500", name], include_stderr=True)
                    check(
                        all(
                            private not in raw
                            for private in secret_values
                            + (actor.scope_id, tasks[0].task_id, tasks[1].task_id, third.task_id)
                        ),
                        "producer_log_privacy",
                    )
                    for line in raw.splitlines():
                        record = json.loads(line)
                        check(
                            set(record)
                            <= {
                                "service",
                                "timestamp",
                                "severity",
                                "event",
                                "code",
                                "operation",
                                "outcome",
                            },
                            "safe_log_field_allowlist",
                        )
                        check(
                            record.get("event") in _EVENTS and record.get("code") in _CODES,
                            "safe_producer_vocabulary",
                        )
                        check(
                            record.get("service") == "continuity-execution"
                            and record.get("severity")
                            in {"debug", "info", "warning", "error", "critical"},
                            "safe_log_service_and_level",
                        )
                        producer_events.add(record["event"])
                check(
                    {
                        "worker_runtime_started",
                        "worker_runtime_stopped",
                        "worker_step_started",
                        "worker_step_finished",
                        "managed_worker_completed",
                        "mutation_worker_completed",
                        "completion_delivery_observed",
                    }
                    <= producer_events,
                    "actual_profile_producer_events",
                )
                receipt = cutover(source_db, folder / "before-cutover.sqlite3", owner)
                check(
                    receipt.state == "active"
                    and read_import_state(runtime).version == 4
                    and inquiry.get(token=token, task_id=third.task_id).task_id == third.task_id,
                    "completed_cutover_receipt_retains_v4_progress",
                )
                check(sample_active() == 0, "all_worker_leases_released")
                result = {
                    "status": "passed",
                    "mode": "local_synthetic",
                    "worker_containers": 2,
                    "worker_starts": 3,
                    "installed_modules": len(expected),
                    "module_hashes": expected,
                    "runtime_image_id": image,
                    "original_task_ids": [task.task_id for task in tasks],
                    "case_ids_distinct": all(case.case_id != case.task_id for case in enrolled),
                    "retained_waits_after_stop": 2,
                    "signal_consumptions": 1,
                    "admission_rejected_without_ack": True,
                    "replay_at_capacity": True,
                    "useful_acceptance_after_progress": True,
                    "global_active_limit": 1,
                    "maximum_observed_active_leases": maximum_active[0],
                    "active_lease_samples": active_samples[0],
                    "physical_mutations": 1,
                    "supplier_apply_calls": 1,
                    "logical_inquiries": 3,
                    "logical_receiver_events": 3,
                    "primary_outcome_event_unchanged": True,
                    "cutover_receipt_preserved_at_v4": True,
                    "stops": stopped,
                    "metrics": metric_records,
                    "safe_producer_events": sorted(producer_events),
                    "timeline": timeline,
                    "live_m1_backend": "unchanged",
                }
            except Exception as error:
                logs = []
                for name in worker_names:
                    try:
                        owned = control(
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
                        if owned:
                            logs.append(
                                redact(
                                    command(
                                        ["docker", "logs", "--tail", "50", owned],
                                        include_stderr=True,
                                    )
                                )[-8192:]
                            )
                    except Exception:  # noqa: BLE001 - preserve original failure and independent cleanup
                        logs.append("unavailable")
                failure_report(
                    "failed-" + run_id + "-scenario.json",
                    {
                        "status": "failed",
                        "state": state,
                        "timeline": timeline,
                        "worker_log_tails": logs,
                        "error_type": type(error).__name__,
                    },
                )
                raise
    finally:
        failures = []
        for name in names:
            try:
                found = control(
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
                    control(["docker", "rm", "-f", found])
            except Exception:  # noqa: BLE001 - continue independent owned cleanup
                failures.append("owned_container_cleanup_failed")
        if volume_candidate:
            try:
                observed = control(
                    [
                        "docker",
                        "volume",
                        "inspect",
                        "--format",
                        '{{ index .Labels "' + label_key + '" }}',
                        volume,
                    ]
                )
                if observed != run_id or volume != "p1-worker-demo-" + run_id:
                    raise RuntimeError("Only the exact owned fixture volume may be removed")
                control(["docker", "volume", "rm", volume])
            except Exception:  # noqa: BLE001 - schema cleanup is independent
                failures.append("owned_volume_cleanup_failed")
        try:
            if schema != "p1_worker_demo_" + run_id or len(run_id) != 32:
                raise RuntimeError("Only the exact owned schema may be removed")
            with closing(owner.connect(application_name="continuity-migrate")) as connection:
                connection.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
                )
        except Exception:  # noqa: BLE001 - preserve original failure and record cleanup
            failures.append("owned_schema_cleanup_failed")
        if failures:
            failure_report(
                "failed-" + run_id + "-cleanup.json", {"status": "failed", "codes": failures}
            )
            if sys.exc_info()[0] is None:
                raise RuntimeError("Owned cleanup did not complete")
    if result is None:
        raise RuntimeError("Demo did not establish passing evidence")
    result["cleanup_verified"] = True
    (reports / "container-demo.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - secret-safe local operator boundary
        print(
            '{"status":"failed","code":"phase_f_demo_failed","action":"inspect_retained_safe_evidence"}'
        )
        sys.exit(1)
