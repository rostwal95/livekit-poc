"""Opt-in installed P1 crash/drain workloads; H1 declarations remain immutable."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import random
import re
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4, uuid5

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from harness.reliability_models import (
    ReliabilityCase,
    ReliabilityManifest,
    ReliabilityValidationError,
    canonical_manifest,
    load_manifest,
    manifest_digest,
)
from harness.workload_models import Experiment, load_workload_manifest
from harness.workload_models import manifest_digest as base_digest


def load_tool(name: str, path: Path) -> Any:
    """Only repository-owned, fixed tooling modules cross this dynamic boundary."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Required local tooling is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bench = load_tool("p1_reliability_primitives", ROOT / "local-setup/scripts/p1_benchmark.py")

HOLD_SCRIPT = r"""import json,sqlite3,sys,time
from pathlib import Path
database,status,maximum=Path(sys.argv[1]),Path(sys.argv[2]),int(sys.argv[3])
if not database.is_file() or not status.is_dir() or not 3000<=maximum<=4500:raise SystemExit(3)
connection=sqlite3.connect(database.as_uri()+'?mode=rw',uri=True,timeout=1)
connection.execute('BEGIN IMMEDIATE')
started=time.monotonic()
(status/'held').write_text('1')
try:
 while not (status/'release').exists():
  if (time.monotonic()-started)*1000>=maximum:raise SystemExit(2)
  time.sleep(.005)
finally:
 connection.rollback();connection.close()
elapsed=time.monotonic()-started
(status/'result.pending').write_text(json.dumps({'released':True,'held_seconds':elapsed}))
(status/'result.pending').replace(status/'result.json')
deadline=time.monotonic()+10
while not (status/'exit').exists():
 if time.monotonic()>=deadline:raise SystemExit(4)
 time.sleep(.005)
"""

STATE_SCRIPT = r"""import json
from psycopg import sql
from continuity_lab.postgres_settings import PostgresSettings
s=PostgresSettings.from_env()
with s.connect(application_name='continuity-test') as c:
 rows=c.execute(sql.SQL('SELECT t.task_id,c.deadline,c.state,l.epoch,l.owner_id IS NOT NULL AND l.expires_at>clock_timestamp() AS active FROM {} t JOIN {} c USING(task_id) LEFT JOIN {} l USING(task_id) WHERE t.scope_id=%s ORDER BY t.task_id LIMIT 33').format(sql.Identifier(s.schema,'tasks'),sql.Identifier(s.schema,'execution_controls'),sql.Identifier(s.schema,'execution_leases')),('benchmark-traveller',)).fetchall()
print(json.dumps(rows))
"""


class SampleBudget:
    def __init__(self, maximum: int) -> None:
        if type(maximum) is not int or not 1 <= maximum <= 4096:
            raise ValueError("A finite sample budget is required")
        self.maximum, self.count = maximum, 0
        self.lock = threading.Lock()

    def reserve(self) -> None:
        with self.lock:
            if self.count >= self.maximum:
                raise bench.BenchmarkError("invalid_evidence")
            self.count += 1


class Evidence:
    """One total record cap spans all fault cases and resource epochs."""

    def __init__(self, path: Path, budget: SampleBudget) -> None:
        self.log = bench.EvidenceLog(path, budget.maximum)
        self.budget = budget

    def record(self, experiment: str, kind: str, elapsed: float, **fields: object) -> None:
        self.budget.reserve()
        self.log.record(experiment, kind, elapsed, **fields)

    def close(self) -> None:
        self.log.close()


class Observer:
    def __init__(self, lab: Any, evidence: Evidence) -> None:
        self.lab, self.evidence = lab, evidence
        self.stop = asyncio.Event()
        self.counts: dict[str, int] = {}
        self.previous: dict[str, int] = {}
        self.task = asyncio.create_task(self.run(), name="owned-reliability-resource-observer")

    async def run(self) -> None:
        target = time.monotonic()
        while not self.stop.is_set():
            started = time.monotonic()
            await asyncio.to_thread(self.lab.sample, self.evidence, self.counts, self.previous)
            target, skipped = bench.next_resource_tick(target + 1, time.monotonic(), 1)
            self.evidence.record(
                self.lab.experiment.name,
                "observer",
                self.lab.budget.elapsed(),
                duration_seconds=time.monotonic() - started,
                skipped_intervals=skipped,
            )
            try:
                await asyncio.wait_for(self.stop.wait(), max(0.001, target - time.monotonic()))
            except TimeoutError:
                pass

    def check(self) -> None:
        if self.task.done():
            self.task.result()

    async def wait_for_baseline(self) -> None:
        while any(self.counts.get(name, 0) < 2 for name, _, _ in self.lab.serving):
            self.check()
            await asyncio.sleep(
                min(0.025, self.lab.budget.remaining(), self.lab.overall.remaining())
            )

    async def close(self) -> dict[str, object]:
        self.stop.set()
        await self.task
        if any(self.counts.get(name, 0) < 2 for name, _, _ in self.lab.serving):
            raise bench.BenchmarkError("invalid_evidence")
        if set(self.lab.resource_windows) != {name for name, _, _ in self.lab.serving} or any(
            window.get("observed_window_seconds", 0) <= 0
            for window in self.lab.resource_windows.values()
        ):
            raise bench.BenchmarkError("invalid_evidence")
        return {
            "samples": {
                name.removeprefix(self.lab.prefix + "-"): count
                for name, count in self.counts.items()
            },
            "cpu_windows": {
                name.removeprefix(self.lab.prefix + "-"): dict(window)
                for name, window in self.lab.resource_windows.items()
            },
        }


def original_deadlines(rows: object, accepted: int) -> dict[str, str]:
    if type(rows) is not list or len(rows) != accepted:
        raise bench.BenchmarkError("reconciliation_failed")
    result: dict[str, str] = {}
    for row in rows:
        if type(row) is not dict or set(row) != {"task_id", "deadline", "state", "epoch", "active"}:
            raise bench.BenchmarkError("invalid_evidence")
        task = bench.uuid_value(row["task_id"])
        if type(row["deadline"]) is not str or type(row["active"]) is not bool:
            raise bench.BenchmarkError("invalid_evidence")
        try:
            if datetime.fromisoformat(row["deadline"]).utcoffset() is None:
                raise ValueError("Naive deadline")
        except (ValueError, OverflowError):
            raise bench.BenchmarkError("invalid_evidence") from None
        if task in result:
            raise bench.BenchmarkError("reconciliation_failed")
        result[task] = row["deadline"]
    return result


def api_shutdown_observation(raw: bytes) -> dict[str, object]:
    """Uvicorn re-raises SIGTERM only after its completed lifespan shutdown."""
    if type(raw) is not bytes or len(raw) > 131072:
        raise bench.BenchmarkError("invalid_evidence")
    lines = raw.splitlines()
    complete = sum(line == b"INFO:     Application shutdown complete." for line in lines)
    finished = sum(
        bool(re.fullmatch(rb"INFO:\s+Finished server process \[\d+\]", line)) for line in lines
    )
    if (
        complete != 1
        or finished != 1
        or any(b"Application shutdown failed" in line for line in lines)
    ):
        raise bench.BenchmarkError("cleanup_failed")
    return {
        "application_shutdown_complete_events": complete,
        "server_process_finished_events": finished,
    }


@dataclass(frozen=True, slots=True)
class ProcessState:
    running: bool
    pid: int
    exit_code: int
    started_at: str


class FaultControl:
    def __init__(self, lab: Any, case: ReliabilityCase) -> None:
        self.lab, self.case = lab, case
        self.holder = lab.prefix + "-supplier-hold"
        self.started: float | None = None

    def state(self) -> list[dict[str, Any]]:
        value = bench.strict_json(
            self.lab.command(
                [sys.executable, "-c", STATE_SCRIPT],
                environment=self.lab.pg_environment(owner=False),
            ).encode(),
            131072,
        )
        original_deadlines(value, self.case.accepted)
        return cast(list[dict[str, Any]], value)

    def owned(self, names: list[str]) -> dict[str, ProcessState]:
        if not names or any(name not in self.lab.names for name in names):
            raise bench.BenchmarkError("missing_setup")
        result: dict[str, ProcessState] = {}
        for name in names:
            observed = bench.strict_json(
                self.lab.command(["docker", "inspect", "--format", "{{json .}}", name]).encode(),
                131072,
            )
            if (
                type(observed) is not dict
                or observed["Image"] != self.lab.image
                or observed["Config"]["Labels"].get(self.lab.label_key) != self.lab.label_value
            ):
                raise bench.BenchmarkError("missing_setup")
            state = observed["State"]
            if (
                type(state) is not dict
                or type(state.get("Running")) is not bool
                or type(state.get("Pid")) is not int
                or state["Pid"] < 0
                or type(state.get("ExitCode")) is not int
                or not -(2**31) <= state["ExitCode"] < 2**31
                or type(state.get("StartedAt")) is not str
            ):
                raise bench.BenchmarkError("invalid_evidence")
            result[name] = ProcessState(
                state["Running"], state["Pid"], state["ExitCode"], state["StartedAt"]
            )
        return result

    def api_shutdown(self) -> dict[str, object]:
        from harness.process_control import OwnedProcess

        output = self.lab.directory / "private-api-shutdown"
        with OwnedProcess(
            ["docker", "logs", "--tail", "128", self.lab.prefix + "-api"],
            cwd=self.lab.root,
            env=self.lab.stack.child_environment(self.lab.values),
            output_directory=output,
            max_output_bytes=65536,
        ) as child:
            if child.wait(timeout=5).returncode != 0:
                raise bench.BenchmarkError("dependency_unavailable")
        raw = (output / "stdout.bin").read_bytes() + (output / "stderr.bin").read_bytes()
        return api_shutdown_observation(raw)

    def health(self, name: str) -> dict[str, object]:
        value = bench.strict_json(
            self.lab.command(
                [
                    "docker",
                    "exec",
                    name,
                    "python",
                    "-c",
                    "import json;from pathlib import Path;p=Path('/tmp/benchmark-worker.json');b=p.read_bytes();assert len(b)<=1024;v=json.loads(b);print(json.dumps({'ready':v['ready'],'active_children':v['active_children']}))",
                ]
            ).encode()
        )
        if (
            type(value) is not dict
            or set(value) != {"ready", "active_children"}
            or type(value["ready"]) is not bool
            or type(value["active_children"]) is not int
            or value["active_children"] not in {0, 1}
        ):
            raise bench.BenchmarkError("invalid_evidence")
        return cast(dict[str, object], value)

    def acquire(self) -> None:
        self.lab.names.append(self.holder)
        self.lab.command(
            [
                "docker",
                "run",
                "-d",
                "--name",
                self.holder,
                "--label",
                self.lab.label_key + "=" + self.lab.label_value,
                "--network",
                "none",
                "--user",
                "10001:10001",
                "--init",
                "--read-only",
                "--security-opt",
                "no-new-privileges:true",
                "--cap-drop",
                "ALL",
                "--memory",
                "134217728",
                "--cpus",
                "0.5",
                "--pids-limit",
                "32",
                "--tmpfs",
                "/tmp:rw,nosuid,noexec,size=4m,mode=1777",
                "--mount",
                "type=volume,src=" + self.lab.prefix + "-fixtures,dst=/data",
                self.lab.image,
                "python",
                "-c",
                HOLD_SCRIPT,
                "/data/supplier.sqlite3",
                "/tmp",
                str(self.case.maximum_hold_ms),
            ],
            cap=15,
        )
        while True:
            ready = self.lab.command(
                [
                    "docker",
                    "exec",
                    self.holder,
                    "python",
                    "-c",
                    "from pathlib import Path;print('held' if Path('/tmp/held').is_file() else 'waiting')",
                ]
            )
            if ready == "held":
                self.started = time.monotonic()
                return
            time.sleep(min(0.02, self.lab.budget.remaining(), self.lab.overall.remaining()))

    def release(self) -> dict[str, object]:
        self.lab.command(
            [
                "docker",
                "exec",
                self.holder,
                "python",
                "-c",
                "from pathlib import Path;Path('/tmp/release').touch(exist_ok=False)",
            ]
        )
        while True:
            observed = bench.strict_json(
                self.lab.command(
                    [
                        "docker",
                        "exec",
                        self.holder,
                        "python",
                        "-c",
                        "from pathlib import Path;print(Path('/tmp/result.json').read_text() if Path('/tmp/result.json').is_file() else '{}')",
                    ]
                ).encode()
            )
            if observed:
                if (
                    type(observed) is not dict
                    or set(observed) != {"released", "held_seconds"}
                    or observed["released"] is not True
                    or type(observed["held_seconds"]) not in {int, float}
                    or not 0 < observed["held_seconds"] <= self.case.maximum_hold_ms / 1000
                ):
                    raise bench.BenchmarkError("invalid_evidence")
                self.lab.command(
                    [
                        "docker",
                        "exec",
                        self.holder,
                        "python",
                        "-c",
                        "from pathlib import Path;Path('/tmp/exit').touch(exist_ok=False)",
                    ]
                )
                if self.lab.command(["docker", "wait", self.holder]) != "0":
                    raise bench.BenchmarkError("dependency_unavailable")
                return observed
            time.sleep(min(0.01, self.lab.budget.remaining(), self.lab.overall.remaining()))


async def run_case(
    lab: Any, case: ReliabilityCase, report: Path, budget: SampleBudget, seed: int
) -> dict[str, object]:
    before = Evidence(report / "before-restart.jsonl", budget)
    after = Evidence(report / "after-restart.jsonl", budget)
    driver = bench.HTTPDriver(
        lab.base_url,
        lab.token,
        lab.budget,
        lab.overall,
        before,
        lab.experiment,
        lab.manifest.http_timeout_seconds,
    )
    observer: Observer | None = None
    fault = FaultControl(lab, case)
    rng = random.Random(seed)
    requests = [
        bench.Investigation(
            index,
            str(uuid5(UUID(lab.prefix[5:37]), f"{case.name}:{index}")),
            {
                "booking_reference": "DEMO-BK-001",
                "new_check_in": f"2030-12-{rng.choice(tuple(day for day in range(2, 29) if day != 25)):02}",
                "confirmed": True,
            },
        )
        for index in range(case.accepted + case.rejected)
    ]
    lab.requests = requests
    original = False
    try:
        await bench.wait_ready(lab, driver, workers=False)
        provenance = await asyncio.to_thread(lab.provenance)
        await asyncio.to_thread(lab.start_workers)
        await bench.wait_ready(lab, driver, workers=True)
        observer = Observer(lab, before)
        await observer.wait_for_baseline()
        # A RESERVED SQLite lock permits metadata/lookup reads and blocks the actual
        # inquiry write. No provider/test-fault API enters the production service.
        await asyncio.to_thread(fault.acquire)
        scheduled = time.monotonic()
        for item in requests:
            item.scheduled_offer_at = scheduled
        async with asyncio.TaskGroup() as group:
            for item in requests[: case.accepted]:
                group.create_task(driver.submit(item))
        async with asyncio.TaskGroup() as group:
            for item in requests[case.accepted :]:
                group.create_task(driver.submit(item, reject=True))
        rows = await asyncio.to_thread(fault.state)
        deadlines = original_deadlines(rows, case.accepted)
        while not any(row["active"] and row["state"] == "running" for row in rows):
            observer.check()
            await asyncio.sleep(0.025)
            rows = await asyncio.to_thread(fault.state)
            original_deadlines(rows, case.accepted)
        active = next(row["task_id"] for row in rows if row["active"] and row["state"] == "running")
        selected = next(item for item in requests if item.task_id == active)
        controls_started = time.monotonic()
        current, _ = await asyncio.wait_for(
            asyncio.gather(driver.get(selected), driver.submit(selected, replay=True)),
            case.control_deadline_ms / 1000,
        )
        control_seconds = time.monotonic() - controls_started
        if current["inquiry"]["state"] != "running" or selected.result_at is not None:
            raise bench.BenchmarkError("reconciliation_failed")
        pre_resources = await observer.close()
        observer = None
        names = [name for name, _, _ in lab.serving]
        states_before = await asyncio.to_thread(fault.owned, names)
        if any(not value.running or value.pid <= 0 for value in states_before.values()):
            raise bench.BenchmarkError("reconciliation_failed")
        drain_observation: dict[str, object] | None = None
        active_worker: str | None = None
        if case.kind == "slow-shutdown":
            for name, role, _ in lab.serving:
                if role == "worker":
                    health = await asyncio.to_thread(fault.health, name)
                    if health["ready"] is True and health["active_children"] == 1:
                        active_worker = name
            if active_worker is None:
                raise bench.BenchmarkError("reconciliation_failed")
        stopped = time.monotonic()
        if case.kind == "restart":
            await asyncio.to_thread(lab.command, ["docker", "kill", *names], cap=10)
            hold = await asyncio.to_thread(fault.release)
        else:
            workers = [name for name, role, _ in lab.serving if role == "worker"]

            async def release_delayed() -> dict[str, object]:
                nonlocal drain_observation
                assert active_worker is not None
                while True:
                    health = await asyncio.to_thread(fault.health, active_worker)
                    if health["ready"] is False and health["active_children"] == 1:
                        break
                    await asyncio.sleep(min(0.01, lab.budget.remaining(), lab.overall.remaining()))
                observed = time.monotonic()
                await asyncio.sleep(case.supplier_delay_ms / 1000)
                result = await asyncio.to_thread(fault.release)
                drain_observation = {
                    "ready": False,
                    "active_children": 1,
                    "observed_since_stop_request_seconds": observed - stopped,
                    "minimum_release_delay_seconds": case.supplier_delay_ms / 1000,
                    "observed_to_release_seconds": time.monotonic() - observed,
                }
                return result

            _, hold = await asyncio.gather(
                asyncio.to_thread(
                    lab.command,
                    ["docker", "stop", "--time", str(case.stop_seconds), *workers],
                    cap=case.stop_seconds + 3,
                ),
                release_delayed(),
            )
            await asyncio.to_thread(
                lab.command, ["docker", "stop", "--time", "5", lab.prefix + "-api"], cap=8
            )
        stop_seconds = time.monotonic() - stopped
        if stop_seconds > 30:
            raise bench.BenchmarkError("deadline_exceeded")
        states_stopped = await asyncio.to_thread(fault.owned, names)
        (report / "process-stop-observation.json").write_text(
            json.dumps(
                {
                    "before": {
                        name.removeprefix(lab.prefix + "-"): asdict(value)
                        for name, value in states_before.items()
                    },
                    "stopped": {
                        name.removeprefix(lab.prefix + "-"): asdict(value)
                        for name, value in states_stopped.items()
                    },
                    "stop_seconds": stop_seconds,
                    "supplier_hold": hold,
                    "drain_observation": drain_observation,
                },
                indent=2,
                allow_nan=False,
            )
            + "\n"
        )
        if any(value.running or value.pid != 0 for value in states_stopped.values()):
            raise bench.BenchmarkError("cleanup_failed")
        expected_exits = {
            name: 137 if case.kind == "restart" else (143 if name == lab.prefix + "-api" else 0)
            for name in states_stopped
        }
        if any(value.exit_code != expected_exits[name] for name, value in states_stopped.items()):
            raise bench.BenchmarkError("cleanup_failed")
        api_shutdown = (
            await asyncio.to_thread(fault.api_shutdown) if case.kind == "slow-shutdown" else None
        )
        await asyncio.to_thread(lab.command, ["docker", "start", *names], cap=15)
        await bench.wait_ready(lab, driver, workers=True)
        states_after = await asyncio.to_thread(fault.owned, names)
        if any(
            not value.running or value.started_at == states_before[name].started_at
            for name, value in states_after.items()
        ):
            raise bench.BenchmarkError("reconciliation_failed")
        deadlines_after_restart = await asyncio.to_thread(fault.state)
        if original_deadlines(deadlines_after_restart, case.accepted) != deadlines:
            raise bench.BenchmarkError("reconciliation_failed")
        # Restarted cgroups have a fresh cumulative CPU origin. Keep distinct raw
        # files/windows rather than subtracting counters across lifetimes.
        lab.resource_windows = {}
        driver.evidence = after
        observer = Observer(lab, after)
        async with asyncio.TaskGroup() as group:
            for item in requests[: case.accepted]:
                group.create_task(driver.get(item))
                group.create_task(driver.submit(item, replay=True))
        offered = asyncio.Event()
        offered.set()
        await bench.observe_results(
            driver, requests, offered, lab.manifest.observation_interval_ms / 1000
        )
        async with asyncio.TaskGroup() as group:
            for item in requests[: case.accepted]:
                group.create_task(driver.cancel(item))
        pending = list(requests[: case.accepted])
        while pending:
            observer.check()
            item = pending.pop(0)
            current = await driver.get(item)
            if current["outcome"]["state"] != "cancelled":
                raise bench.BenchmarkError("reconciliation_failed")
            if current["delivery"]["state"] == "exhausted":
                raise bench.BenchmarkError("reconciliation_failed")
            if current["delivery"]["state"] != "delivered":
                pending.append(item)
            await asyncio.sleep(min(0.25, lab.budget.remaining(), lab.overall.remaining()))
        authority, actual = await asyncio.gather(
            asyncio.to_thread(lab.authority), asyncio.to_thread(lab.accepted_rows)
        )
        outcomes = bench.reconcile(requests, actual, authority, case.accepted, case.rejected)
        post_resources = await observer.close()
        observer = None
        deadlines_final = await asyncio.to_thread(fault.state)
        if original_deadlines(deadlines_final, case.accepted) != deadlines:
            raise bench.BenchmarkError("reconciliation_failed")
        process_snapshots = {
            epoch: {
                name.removeprefix(lab.prefix + "-"): asdict(value) for name, value in states.items()
            }
            for epoch, states in {
                "before": states_before,
                "stopped": states_stopped,
                "after": states_after,
            }.items()
        }
        return {
            "case": case.name,
            "status": "measured",
            "cleanup_verified": False,
            "fault": asdict(case),
            "base_schedule": asdict(lab.experiment),
            "outcomes": outcomes,
            "original_deadlines_preserved": True,
            "deadline_epoch_snapshots": {
                "before": rows,
                "after_restart": deadlines_after_restart,
                "final": deadlines_final,
            },
            "process_snapshots": process_snapshots,
            "pre_fault_resource_epoch_includes_idle_baseline": True,
            "old_containers_observed_stopped": True,
            "stopped_exit_codes": {
                name.removeprefix(lab.prefix + "-"): value.exit_code
                for name, value in states_stopped.items()
            },
            "expected_stop_exit_codes": {
                name.removeprefix(lab.prefix + "-"): value for name, value in expected_exits.items()
            },
            "api_shutdown_observation": api_shutdown,
            "new_process_lifetimes_observed": True,
            "lease_clock": "database",
            "control_seconds_while_supplier_blocked": control_seconds,
            "stop_seconds": stop_seconds,
            "supplier_hold": hold,
            "drain_observation": drain_observation,
            "supplier_barrier_scope": "reserved_write_lock_with_active_running_inquiry_not_instruction_level_wait_probe",
            "resource_epochs": {"before": pre_resources, "after": post_resources},
            "provenance": provenance,
            "elapsed_seconds": lab.budget.elapsed(),
            "observed_result_latency": bench.timing_summary(
                [item.result_at - item.scheduled_offer_at for item in requests[: case.accepted]]
            ),
            "requests": [
                {
                    "task_id": item.task_id,
                    "effect_id": item.effect_id,
                    "key_sha256": hashlib.sha256(item.key.encode()).hexdigest(),
                    "rejected": item.rejected,
                    "cancelled_after_measurement": item.cancelled,
                }
                for item in requests
            ],
        }
    except BaseException:
        original = True
        raise
    finally:
        if observer is not None:
            try:
                await observer.close()
            except Exception:
                if not original:
                    raise
        await driver.client.aclose()
        before.close()
        after.close()


def execute(manifest: ReliabilityManifest, *, run: bool, selected_case: str | None = None) -> int:
    frozen_base = load_workload_manifest(ROOT / "harness/workloads/p1-inquiry-v1.json")
    if base_digest(frozen_base) != manifest.base_manifest_sha256:
        raise ReliabilityValidationError("The frozen base declaration changed")
    cases = tuple(
        case for case in manifest.cases if selected_case is None or case.name == selected_case
    )
    if not cases:
        raise ReliabilityValidationError("Unknown selected reliability case")
    if not run:
        print(
            json.dumps(
                {
                    "status": "not_started",
                    "manifest_sha256": manifest_digest(manifest),
                    "cases": [case.name for case in cases],
                    "coverage": "complete_manifest" if selected_case is None else "selected_case",
                }
            )
        )
        return 0
    stack = load_tool("reliability_owned_stack", ROOT / "local-setup/stack.py")
    values = stack.load_settings(ROOT / "local-setup")
    stack.assert_owned_containers(ROOT / "local-setup", values)
    overall = bench.Budget(manifest.overall_deadline_seconds)
    image = stack.run(
        [
            "docker",
            "image",
            "inspect",
            "--format",
            "{{.Id}}",
            "livekit-agent-ecosystem-python:local",
        ],
        values,
        ROOT / "local-setup",
        5,
    ).strip()
    run_id = uuid4().hex
    report = ROOT / ".local/validation/p1-phase-h2" / run_id
    report.mkdir(parents=True, mode=0o700)
    (report / "workload.json").write_bytes(canonical_manifest(manifest))
    budget = SampleBudget(manifest.maximum_samples)
    results = []
    failure = None
    cleanup_failures = []
    try:
        with tempfile.TemporaryDirectory(prefix="p1-h2-", dir=ROOT / ".local") as temporary:
            for index, case in enumerate(cases):
                directory = Path(temporary) / case.name
                directory.mkdir(mode=0o700)
                target = report / case.name
                target.mkdir(mode=0o700)
                schedule = Experiment(
                    name=f"burst-w{case.workers}",
                    kind="burst",
                    worker_count=case.workers,
                    request_count=case.accepted,
                    accepted_count=case.accepted,
                    rejected_count=0,
                    arrival_interval_ms=0,
                    client_concurrency=4,
                    deadline_seconds=case.deadline_seconds,
                    pending_limit=case.accepted,
                    active_limit=1,
                    record_limit=1000,
                    lease_seconds=30,
                    workers_start_after_submissions=False,
                )
                lab = bench.DockerExperiment(
                    ROOT,
                    stack,
                    values,
                    image,
                    stack.PROJECT + "_lab",
                    run_id,
                    index,
                    schedule,
                    frozen_base,
                    directory,
                    overall,
                )
                original = False
                try:
                    lab.prepare()
                    result = asyncio.run(run_case(lab, case, target, budget, manifest.seed))
                    (target / "measurement.json").write_text(
                        json.dumps(result, indent=2, allow_nan=False) + "\n"
                    )
                except BaseException as error:
                    original = True
                    (target / "failure.json").write_text(
                        json.dumps(
                            {"case": case.name, "failure": bench.failure_observation(error)},
                            indent=2,
                        )
                        + "\n"
                    )
                    raise
                finally:
                    try:
                        lab.cleanup()
                    except Exception as error:
                        cleanup_failures.append(
                            {"case": case.name, "failure": bench.failure_observation(error)}
                        )
                        if not original:
                            raise
                result.update(status="passed", cleanup_verified=True)
                results.append(result)
                (target / "result.json").write_text(
                    json.dumps(result, indent=2, allow_nan=False) + "\n"
                )
                overall.remaining()
    except Exception as error:  # noqa: BLE001 - retain only the fixed outer failure observation
        failure = bench.failure_observation(error)
    summary = {
        "schema_version": 1,
        "status": "passed" if len(results) == len(cases) and failure is None else "failed",
        "coverage": "complete_manifest" if selected_case is None else "selected_case",
        "declared_case_count": len(manifest.cases),
        "selected_case_names": [case.name for case in cases],
        "manifest_sha256": manifest_digest(manifest),
        "base_manifest_sha256": manifest.base_manifest_sha256,
        "runtime_image_id": image,
        "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "samples": budget.count,
        "elapsed_seconds": overall.elapsed(),
        "cases": results,
        "failure": failure,
        "cleanup_failures": cleanup_failures,
        "media_or_model_measurements": False,
        "release_gate": "incomplete",
    }
    (report / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    print(
        json.dumps(
            {"status": summary["status"], "cases_passed": len(results), "report": str(report)}
        )
    )
    return 0 if summary["status"] == "passed" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", type=Path, default=ROOT / "harness/workloads/p1-reliability-v1.json"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument(
        "--case", choices=("restart-w1", "restart-w2", "slow-shutdown-w1", "slow-shutdown-w2")
    )
    args = parser.parse_args(argv)
    try:
        return execute(load_manifest(args.manifest), run=args.run, selected_case=args.case)
    except Exception as error:  # noqa: BLE001 - CLI emits safe codes without dependency tracebacks
        code = (
            "invalid_declaration"
            if isinstance(error, ReliabilityValidationError)
            else bench.failure_code(error)
        )
        print(json.dumps({"status": "failed", "code": code}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
