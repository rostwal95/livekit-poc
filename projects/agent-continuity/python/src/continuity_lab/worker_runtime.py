"""Bounded durable pull worker with one owned subprocess and no local work queue.

PostgreSQL decides eligibility and owns acceptance/leases. A child runs one durable
step; its exit describes process execution, never the supplier's business outcome.
The parent stops acquiring on shutdown and reaps its child before releasing the
lease. Killing a child leaves external-effect evidence for the next owner.
"""

from __future__ import annotations

import json
import logging
import math
import os
import selectors
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol, Self
from uuid import uuid4

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

from .execution_cli import _CODES, _EVENTS
from .execution_models import ExecutionError
from .lease_models import (
    CoordinationPolicy,
    LeaseBusy,
    LeaseGrant,
    LeaseLost,
    LeaseRequired,
    WorkClaim,
    WorkKind,
)
from .postgres_work import QueueSnapshot

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
MAX_CLAIM_BYTES = 2048


class WorkerRuntimeError(ExecutionError):
    code = "worker_runtime_failed"


class WorkerOutputLimit(WorkerRuntimeError):
    code = "worker_output_limit"


class WorkerCleanupIncomplete(WorkerRuntimeError):
    code = "worker_cleanup_incomplete"


class StepOutcome(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    STOPPED = "stopped"


def _duration(value: float, minimum: float, maximum: float) -> float:
    if type(value) not in (float, int):
        raise ValueError("Worker duration must be finite and bounded")
    try:
        converted = float(value)
    except OverflowError as error:
        raise ValueError("Worker duration exceeds finite range") from error
    if not math.isfinite(converted) or not minimum <= converted <= maximum:
        raise ValueError("Worker duration must be finite and bounded")
    return converted


@dataclass(frozen=True, slots=True)
class RuntimePolicy:
    poll_seconds: float = 1.0
    step_timeout_seconds: float = 15.0
    drain_timeout_seconds: float = 5.0
    maximum_output_bytes: int = 65536
    maximum_consecutive_failures: int = 3

    def __post_init__(self) -> None:
        _duration(self.poll_seconds, 0.01, 5)
        _duration(self.step_timeout_seconds, 0.01, 15)
        _duration(self.drain_timeout_seconds, 0.01, 5)
        if (
            type(self.maximum_output_bytes) is not int
            or not 1 <= self.maximum_output_bytes <= 1048576
        ):
            raise ValueError("Worker output budget must be bounded")
        if (
            type(self.maximum_consecutive_failures) is not int
            or not 1 <= self.maximum_consecutive_failures <= 100
        ):
            raise ValueError("Worker failure budget must be bounded")


@dataclass(frozen=True, slots=True)
class StepResult:
    kind: WorkKind
    outcome: StepOutcome
    returncode: int
    reaped: bool


class WorkQueuePort(Protocol):
    def policy(self) -> CoordinationPolicy: ...
    def snapshot(self, *, scope_id: str) -> QueueSnapshot: ...
    def claim_next(self, *, scope_id: str, owner_id: str) -> WorkClaim | None: ...
    def release(self, grant: LeaseGrant) -> None: ...


class StepChildPort(Protocol):
    def poll(self) -> int | None: ...
    def drain(self) -> None: ...
    def kill_and_reap(self, *, timeout: float) -> int: ...
    def close(self) -> None: ...


class StepLauncherPort(Protocol):
    def start(self, claim: WorkClaim, *, maximum_output_bytes: int) -> StepChildPort: ...


def encode_work_claim(claim: WorkClaim) -> str:
    if type(claim) is not WorkClaim:
        raise ValueError("A typed work claim is required")
    value = {
        "schema_version": 1,
        "grant": {
            "scope_id": claim.grant.scope_id,
            "task_id": claim.grant.task_id,
            "owner_id": claim.grant.owner_id,
            "epoch": claim.grant.epoch,
            "expires_at": claim.grant.expires_at,
        },
        "kind": claim.kind.value,
        "actor_id": claim.actor_id,
    }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if len(encoded.encode("utf-8")) > MAX_CLAIM_BYTES:
        raise ValueError("Work claim exceeds the internal message bound")
    return encoded


def parse_work_claim(value: str) -> WorkClaim:
    if type(value) is not str or len(value.encode("utf-8")) > MAX_CLAIM_BYTES:
        raise ValueError("Internal work claim must be bounded JSON")

    def unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for name, item in pairs:
            if name in result:
                raise ValueError("Internal work claim has duplicate fields")
            result[name] = item
        return result

    body = json.loads(value, object_pairs_hook=unique_pairs)
    if (
        type(body) is not dict
        or set(body) != {"schema_version", "grant", "kind", "actor_id"}
        or type(body["schema_version"]) is not int
        or body["schema_version"] != 1
    ):
        raise ValueError("Internal work claim schema is unsupported")
    grant = body["grant"]
    if type(grant) is not dict or set(grant) != {
        "scope_id",
        "task_id",
        "owner_id",
        "epoch",
        "expires_at",
    }:
        raise ValueError("Internal lease grant fields are invalid")
    # Dataclass validation rejects floats/bools, malformed identities and clocks.
    result = WorkClaim(
        LeaseGrant(
            grant["scope_id"],
            grant["task_id"],
            grant["owner_id"],
            grant["epoch"],
            grant["expires_at"],
        ),
        WorkKind(body["kind"]),
        body["actor_id"],
    )
    if encode_work_claim(result) != value:
        raise ValueError("Internal work claim must use its canonical encoding")
    return result


def _event(event: str, code: str = "ok") -> None:
    try:
        LOGGER.log(
            logging.ERROR if code != "ok" else logging.INFO,
            event,
            extra={"event": event, "code": code},
        )
    except Exception:  # noqa: BLE001 - telemetry cannot alter accepted work
        return


class WorkerTelemetry:
    """Finite process observations; the database remains business authority."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.claims = Counter(
            "continuity_worker_claims_total",
            "Worker claim observations",
            ("outcome",),
            registry=self.registry,
        )
        self.steps = Counter(
            "continuity_worker_steps_total",
            "Owned worker process steps",
            ("kind", "outcome"),
            registry=self.registry,
        )
        self.duration = Histogram(
            "continuity_worker_step_duration_seconds",
            "Owned worker process occupancy",
            ("kind", "outcome"),
            buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 15),
            registry=self.registry,
        )
        self.active = Gauge(
            "continuity_worker_active_children", "Owned worker child count", registry=self.registry
        )

        self.rejections = Counter(
            "continuity_worker_lease_rejections_total",
            "Observed stale/busy/missing lease errors",
            ("code",),
            registry=self.registry,
        )
        self.queue_gauges = {
            "outstanding": Gauge(
                "continuity_worker_outstanding",
                "Scoped durable outstanding workflows",
                registry=self.registry,
            ),
            "active": Gauge(
                "continuity_worker_active_leases",
                "Scoped durable current lease count",
                registry=self.registry,
            ),
            "maximum_pending": Gauge(
                "continuity_worker_pending_limit",
                "Schema durable outstanding limit",
                registry=self.registry,
            ),
            "maximum_active": Gauge(
                "continuity_worker_active_limit",
                "Schema lease concurrency limit",
                registry=self.registry,
            ),
            "oldest_outstanding_seconds": Gauge(
                "continuity_worker_oldest_outstanding_seconds",
                "Scoped oldest outstanding age",
                registry=self.registry,
            ),
            "recovery_lag_seconds": Gauge(
                "continuity_worker_recovery_lag_seconds",
                "Scoped expired owner recovery lag",
                registry=self.registry,
            ),
        }

    def queue(self, value: QueueSnapshot) -> None:
        if type(value) is not QueueSnapshot:
            raise ValueError("A validated durable queue snapshot is required")
        try:
            for name, gauge in self.queue_gauges.items():
                gauge.set(getattr(value, name))
        except Exception:  # noqa: BLE001 - metrics cannot change durable work
            return

    def lease_rejection(self, code: str) -> None:
        if code not in {"lease_busy", "lease_lost", "lease_required"}:
            return
        try:
            self.rejections.labels(code).inc()
        except Exception:  # noqa: BLE001 - metrics cannot change durable work
            return

    def claim(self, outcome: str) -> None:
        if outcome not in {"acquired", "empty", "stopped"}:
            raise ValueError("Invalid worker claim outcome")
        try:
            self.claims.labels(outcome).inc()
        except Exception:  # noqa: BLE001 - explicit observation boundary
            return

    def child(self, active: bool) -> None:
        try:
            self.active.set(1 if active else 0)
        except Exception:  # noqa: BLE001 - explicit observation boundary
            return

    def step(self, result: StepResult, duration: float) -> None:
        try:
            self.steps.labels(result.kind.value, result.outcome.value).inc()
            self.duration.labels(result.kind.value, result.outcome.value).observe(max(0, duration))
        except Exception:  # noqa: BLE001 - explicit observation boundary
            return

    def render(self) -> bytes:
        return generate_latest(self.registry)


class ProcessStepChild:
    """Own and drain both pipes without retaining untrusted child output."""

    def __init__(
        self,
        argv: Sequence[str],
        *,
        environment: Mapping[str, str],
        cwd: Path,
        maximum_output_bytes: int,
        observe_code: Callable[[str], None] | None = None,
    ) -> None:
        if (
            isinstance(argv, (str, bytes))
            or not 1 <= len(argv) <= 64
            or any(
                type(arg) is not str or not arg or "\0" in arg or len(arg) > 4096 for arg in argv
            )
        ):
            raise ValueError("A bounded child argument vector is required")
        if type(maximum_output_bytes) is not int or not 1 <= maximum_output_bytes <= 1048576:
            raise ValueError("A bounded output budget is required")
        if os.name != "posix" or not hasattr(os, "waitid") or not hasattr(os, "WNOWAIT"):
            raise ValueError("Owned worker subprocesses require POSIX wait observation")
        self._maximum = maximum_output_bytes
        self._received = 0
        self._observe_code = observe_code
        self._buffers: dict[int, bytes] = {}
        self._selector = selectors.DefaultSelector()
        self._process = subprocess.Popen(
            list(argv),
            env=dict(environment),
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        assert self._process.stdout is not None and self._process.stderr is not None
        self._streams = (self._process.stdout, self._process.stderr)
        self._closed = False
        try:
            for stream in self._streams:
                os.set_blocking(stream.fileno(), False)
                self._selector.register(stream, selectors.EVENT_READ)
                self._buffers[stream.fileno()] = b""
        except Exception:
            self.close()
            raise

    @property
    def pid(self) -> int:
        return self._process.pid

    def _kill_group(self) -> None:
        try:
            os.killpg(self._process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            # On macOS a group containing only a zombie leader returns EPERM;
            # exit visibility can trail that result briefly. Keep its PID held
            # and retry only this owned group under a small monotonic budget.
            if sys.platform == "darwin":
                deadline = time.monotonic() + 0.05
                while True:
                    if (
                        os.waitid(os.P_PID, self._process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                        is not None
                    ):
                        return
                    if time.monotonic() >= deadline:
                        break
                    time.sleep(0.001)
                    try:
                        os.killpg(self._process.pid, signal.SIGKILL)
                        return
                    except ProcessLookupError:
                        return
                    except PermissionError:
                        continue
            raise

    def poll(self) -> int | None:
        if self._process.returncode is not None:
            return self._process.returncode
        # Observe without reaping: retaining the leader PID prevents group-ID
        # reuse before terminating any unexpectedly surviving descendants.
        observed = os.waitid(os.P_PID, self._process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        if observed is None:
            return None
        self._kill_group()
        try:
            return self._process.wait(timeout=1)
        except subprocess.TimeoutExpired as error:
            raise WorkerCleanupIncomplete("Owned worker child could not be reaped") from error

    def _observe_line(self, line: bytes) -> None:
        if len(line) > 4096:
            return
        try:
            value = json.loads(line)
            required = {"service", "timestamp", "severity", "event", "code"}
            if (
                type(value) is not dict
                or not required <= set(value)
                or set(value) - (required | {"operation", "outcome"})
            ):
                return
            if (
                value["service"] != "continuity-execution"
                or type(value["event"]) is not str
                or value["event"] not in _EVENTS
                or type(value["code"]) is not str
                or value["code"] not in _CODES
            ):
                return
            levels = {
                "debug": logging.DEBUG,
                "info": logging.INFO,
                "warning": logging.WARNING,
                "error": logging.ERROR,
                "critical": logging.CRITICAL,
            }
            if type(value["severity"]) is not str or value["severity"] not in levels:
                return
            # Reconstruct only finite producer fields. A success code such as
            # succeeded retains its validated level; no raw level/text is logged.
            LOGGER.log(
                levels[value["severity"]],
                value["event"],
                extra={"event": value["event"], "code": value["code"]},
            )
            if self._observe_code is not None:
                self._observe_code(value["code"])
        except Exception:  # noqa: BLE001 - child output is untrusted observation only
            return

    def drain(self) -> None:
        # Drain all currently available bytes before observing process exit, so
        # an exited writer cannot hide output beyond the byte cap in a pipe.
        while True:
            ready = self._selector.select(0)
            if not ready:
                return
            for key, _ in ready:
                chunk = os.read(key.fd, 16384)
                if not chunk:
                    pending = self._buffers.pop(key.fd, b"")
                    if pending:
                        self._observe_line(pending)
                    self._selector.unregister(key.fileobj)
                    continue
                self._received += len(chunk)
                if self._received > self._maximum:
                    raise WorkerOutputLimit("Worker output exceeded its bound")
                pending = self._buffers[key.fd] + chunk
                lines = pending.split(b"\n")
                self._buffers[key.fd] = lines.pop()
                for line in lines:
                    self._observe_line(line)

    def kill_and_reap(self, *, timeout: float = 1) -> int:
        timeout = _duration(timeout, 0.01, 2)
        if self._process.returncode is None:
            self._kill_group()
        try:
            return self._process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            raise WorkerCleanupIncomplete("Owned worker child could not be reaped") from error

    def close(self) -> None:
        if self._closed:
            return
        if self._process.returncode is None:
            self.kill_and_reap()
        self._selector.close()
        for stream in self._streams:
            stream.close()
        self._closed = True

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


class ProcessStepLauncher:
    def __init__(
        self,
        argv: Sequence[str],
        *,
        environment: Mapping[str, str],
        cwd: Path,
        observe_code: Callable[[str], None] | None = None,
    ) -> None:
        self.argv, self.environment, self.cwd = tuple(argv), dict(environment), cwd
        self.observe_code = observe_code

    def start(self, claim: WorkClaim, *, maximum_output_bytes: int) -> ProcessStepChild:
        environment = {**self.environment, "P1_WORKER_CLAIM": encode_work_claim(claim)}
        return ProcessStepChild(
            self.argv,
            environment=environment,
            cwd=self.cwd,
            maximum_output_bytes=maximum_output_bytes,
            observe_code=self.observe_code,
        )


class WorkerRuntime:
    """Pull one durable claim, own one child, then release only after reaping."""

    def __init__(
        self,
        queue: WorkQueuePort,
        launcher: StepLauncherPort,
        *,
        scope_id: str,
        lease_seconds: int,
        policy: RuntimePolicy | None = None,
        telemetry: WorkerTelemetry | None = None,
        clock: Callable[[], float] = time.monotonic,
        pause: Callable[[float], None] = time.sleep,
        observe: Callable[[bool, int], None] | None = None,
    ) -> None:
        if (
            type(scope_id) is not str
            or not 1 <= len(scope_id) <= 128
            or scope_id != scope_id.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in scope_id)
        ):
            raise ValueError("Worker scope is invalid")
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 300:
            raise ValueError("Worker lease policy must be bounded")
        if policy is not None and type(policy) is not RuntimePolicy:
            raise ValueError("A typed runtime policy is required")
        self.queue, self.launcher, self.scope_id, self.lease_seconds = (
            queue,
            launcher,
            scope_id,
            lease_seconds,
        )
        self.policy = policy or RuntimePolicy()
        self.telemetry = telemetry or WorkerTelemetry()
        self.clock, self.pause, self.observe = clock, pause, observe
        self._stopping = False
        self._quiesce_requested = False
        self._quiescent = False
        self._child: StepChildPort | None = None
        self._consecutive_failures = 0
        self._last_observation = float("-inf")
        self._last_observed_state: tuple[bool, int] | None = None

    @property
    def stopping(self) -> bool:
        return self._stopping

    @property
    def quiescent(self) -> bool:
        return self._quiescent

    def request_quiesce(self) -> None:
        if not self._stopping:
            self._quiesce_requested = True

    def request_resume(self) -> None:
        self._quiesce_requested = False

    def request_stop(self) -> None:
        self._stopping = True
        self._quiesce_requested = False

    def _publish(self, *, force: bool = False) -> None:
        if self.observe is not None:
            state = (
                not self._stopping and not self._quiescent,
                0 if self._child is None else 1,
            )
            now = self.clock()
            if (
                not force
                and state == self._last_observed_state
                and now - self._last_observation < 1
            ):
                return
            self._last_observation, self._last_observed_state = now, state
            try:
                self.observe(*state)
            except Exception:  # noqa: BLE001 - health reporting cannot lose durable work
                _event("worker_health_failed", "worker_health_unavailable")

    def _observe_queue(self) -> None:
        if self._stopping:
            return
        try:
            self.telemetry.queue(self.queue.snapshot(scope_id=self.scope_id))
        except Exception:  # noqa: BLE001 - observation cannot change business authority
            _event("worker_queue_observation_failed", "worker_health_unavailable")

    def _owned_step(self, claim: WorkClaim) -> StepResult:
        child = self.launcher.start(claim, maximum_output_bytes=self.policy.maximum_output_bytes)
        self._child = child
        self.telemetry.child(True)
        started = self.clock()
        deadline = started + min(self.policy.step_timeout_seconds, self.lease_seconds / 2)
        stop_deadline = None
        try:
            while True:
                self._publish()
                try:
                    child.drain()
                except WorkerOutputLimit:
                    return StepResult(
                        claim.kind, StepOutcome.FAILED, child.kill_and_reap(timeout=1), True
                    )
                result = child.poll()
                if result is not None:
                    return StepResult(
                        claim.kind,
                        StepOutcome.COMPLETED if result == 0 else StepOutcome.FAILED,
                        result,
                        True,
                    )
                now = self.clock()
                if self._stopping and stop_deadline is None:
                    stop_deadline = now + self.policy.drain_timeout_seconds
                due = deadline if stop_deadline is None else min(deadline, stop_deadline)
                if now >= due:
                    outcome = StepOutcome.STOPPED if self._stopping else StepOutcome.TIMED_OUT
                    return StepResult(claim.kind, outcome, child.kill_and_reap(timeout=1), True)
                self.pause(min(0.02, due - now))
        finally:
            # close must finish before lease release; failed reaping keeps the
            # lease until DB expiry and fails the supervisor visibly.
            child.close()
            self._child = None
            self.telemetry.child(False)
            self._publish()

    def run_once(self) -> StepResult | None:
        if self._stopping:
            self.telemetry.claim("stopped")
            self._publish()
            return None
        self._observe_queue()
        if self._stopping:
            self.telemetry.claim("stopped")
            self._publish()
            return None
        try:
            claim = self.queue.claim_next(scope_id=self.scope_id, owner_id=str(uuid4()))
        except ExecutionError as error:
            # Diagnose only trusted types. A provider's code property must not
            # replace its original error or trigger arbitrary metadata access.
            for category, code in (
                (LeaseBusy, "lease_busy"),
                (LeaseLost, "lease_lost"),
                (LeaseRequired, "lease_required"),
            ):
                if isinstance(error, category):
                    self.telemetry.lease_rejection(code)
                    break
            raise
        if claim is None:
            self.telemetry.claim("empty")
            self._publish()
            return None
        if type(claim) is not WorkClaim or claim.grant.scope_id != self.scope_id:
            raise WorkerRuntimeError("Queue returned an invalid scoped claim")
        self.telemetry.claim("acquired")
        if self._stopping:
            self.queue.release(claim.grant)
            self.telemetry.claim("stopped")
            self._publish()
            return None
        started = self.clock()
        _event("worker_step_started")
        try:
            result = self._owned_step(claim)
        finally:
            if self._child is None:
                original_failure = sys.exc_info()[0] is not None
                try:
                    self.queue.release(claim.grant)
                except Exception:
                    _event("worker_release_failed", "worker_cleanup_incomplete")
                    if not original_failure:
                        raise
        self._observe_queue()
        self.telemetry.step(result, self.clock() - started)
        self._publish(force=True)
        _event(
            "worker_step_finished",
            "ok" if result.outcome == StepOutcome.COMPLETED else "worker_step_interrupted",
        )
        if result.outcome == StepOutcome.COMPLETED:
            self._consecutive_failures = 0
        else:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.policy.maximum_consecutive_failures:
                raise WorkerRuntimeError("Consecutive worker process failures exhausted the bound")
        return result

    def run(self) -> None:
        _event("worker_runtime_started")
        try:
            while not self._stopping:
                if self._quiesce_requested:
                    # This outer checkpoint owns no child, lease, or queue call:
                    # run_once has finished its release and final observation.
                    self._quiescent = True
                    self._publish(force=True)
                    while self._quiesce_requested and not self._stopping:
                        self._publish()
                        self.pause(min(0.1, self.policy.poll_seconds))
                    self._quiescent = False
                    self._publish(force=True)
                    if self._stopping:
                        break
                result = self.run_once()
                if result is not None and result.outcome == StepOutcome.COMPLETED:
                    # The owned child is reaped and its lease released. Pull the
                    # next durable claim without delaying already-runnable work.
                    continue
                # Empty selections and unsuccessful steps retain bounded backoff.
                deadline = self.clock() + self.policy.poll_seconds
                while not self._stopping and self.clock() < deadline:
                    self._publish()
                    self.pause(min(0.1, max(0, deadline - self.clock())))
        finally:
            self._stopping = True
            self._quiescent = False
            self._publish()
            _event("worker_runtime_stopped")
