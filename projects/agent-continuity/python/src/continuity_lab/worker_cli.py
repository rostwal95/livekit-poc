"""Explicit synthetic fixtures and leased PostgreSQL worker process commands.

The worker accepts no public task payload or confirmation. Existing authority
selects each step; runtime credentials cannot install or activate a schema.
"""

from __future__ import annotations

import json
import math
import os
import signal
import stat
import sys
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from uuid import uuid4

from .execution_cli import _CODES, _SafeParser, configure_logging
from .execution_models import ExecutionError, TransitionConflict
from .lease_models import WorkClaim, WorkKind
from .mutation_supplier import MutationSupplier
from .worker_runtime import (
    ProcessStepLauncher,
    RuntimePolicy,
    WorkerRuntime,
    WorkerTelemetry,
    _event,
    parse_work_claim,
)

_WORKER_KEYS = frozenset(
    {
        "P1_WORKER_SCOPE",
        "P1_WORKER_SUPPLIER_DB",
        "P1_WORKER_SINK_DB",
        "P1_WORKER_STATE_FILE",
        "P1_WORKER_SUPPLIER_MODE",
        "P1_WORKER_POLL_SECONDS",
        "P1_WORKER_STEP_SECONDS",
        "P1_WORKER_DRAIN_SECONDS",
        "P1_WORKER_OUTPUT_BYTES",
        "P1_WORKER_FAILURE_LIMIT",
        "P1_WORKER_CLAIM",
    }
)


def _safe_code(error: ExecutionError) -> str:
    try:
        candidate = getattr(error, "code", "execution_error")
        return candidate if type(candidate) is str and candidate in _CODES else "execution_error"
    except Exception:  # noqa: BLE001 - error metadata cannot escape the process boundary
        return "unexpected_error"


def _path(value: str) -> Path:
    if type(value) is not str or not value or "\0" in value:
        raise ValueError("A bounded absolute worker path is required")
    path = Path(value)
    if len(value) > 4096 or not path.is_absolute() or ".." in path.parts or path.is_symlink():
        raise ValueError("A bounded absolute worker path is required")
    return path.parent.resolve() / path.name


@dataclass(frozen=True, slots=True)
class WorkerSettings:
    scope_id: str
    supplier_db: Path
    sink_db: Path
    state_file: Path
    cooperating: bool
    policy: RuntimePolicy

    def __post_init__(self) -> None:
        if (
            type(self.scope_id) is not str
            or not 1 <= len(self.scope_id) <= 128
            or self.scope_id != self.scope_id.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in self.scope_id)
        ):
            raise ValueError("Worker scope is invalid")
        if type(self.cooperating) is not bool or type(self.policy) is not RuntimePolicy:
            raise ValueError("Worker policy must be typed")
        paths = tuple(
            _path(str(path)) for path in (self.supplier_db, self.sink_db, self.state_file)
        )
        if len({*paths, paths[2].with_suffix(".prom")}) != 4:
            raise ValueError("Supplier, receiver, health and metric paths must be distinct")
        for name, path in zip(("supplier_db", "sink_db", "state_file"), paths, strict=True):
            object.__setattr__(self, name, path)

    @classmethod
    def from_env(cls, environment: Mapping[str, str] | None = None) -> WorkerSettings:
        values = os.environ if environment is None else environment
        if any(key.startswith("P1_MIGRATION_") for key in values):
            raise ValueError("Worker processes cannot receive migration credentials")
        if {key for key in values if key.startswith("P1_WORKER_")} - _WORKER_KEYS:
            raise ValueError("Unknown worker configuration settings")
        scope = values.get("P1_WORKER_SCOPE", "demo-traveller")
        if (
            type(scope) is not str
            or not 1 <= len(scope) <= 128
            or scope != scope.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in scope)
        ):
            raise ValueError("Worker scope is invalid")
        mode = values.get("P1_WORKER_SUPPLIER_MODE", "cooperating")
        if mode not in {"cooperating", "noncooperating"}:
            raise ValueError("Unsupported supplier cooperation mode")
        return cls(
            scope,
            _path(values.get("P1_WORKER_SUPPLIER_DB", "/data/supplier.sqlite3")),
            _path(values.get("P1_WORKER_SINK_DB", "/data/completion.sqlite3")),
            _path(
                values.get(
                    "P1_WORKER_STATE_FILE", str(Path(tempfile.gettempdir()) / "p1-worker.json")
                )
            ),
            mode == "cooperating",
            RuntimePolicy(
                poll_seconds=float(values.get("P1_WORKER_POLL_SECONDS", "1")),
                step_timeout_seconds=float(values.get("P1_WORKER_STEP_SECONDS", "15")),
                drain_timeout_seconds=float(values.get("P1_WORKER_DRAIN_SECONDS", "5")),
                maximum_output_bytes=int(values.get("P1_WORKER_OUTPUT_BYTES", "65536")),
                maximum_consecutive_failures=int(values.get("P1_WORKER_FAILURE_LIMIT", "3")),
            ),
        )


class WorkerHealth:
    """Private atomic readiness observation, not a workflow/outcome record."""

    def __init__(self, path: Path, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.path = _path(str(path))
        self.clock = clock

    def _existing(self) -> None:
        try:
            info = self.path.lstat()
        except FileNotFoundError:
            return
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
        ):
            raise ValueError("Worker health file must be a private owned regular file")

    def publish(self, ready: bool, active: int) -> None:
        if type(ready) is not bool or type(active) is not int or active not in {0, 1}:
            raise ValueError("Worker health values are invalid")
        self._existing()
        stamp = self.clock()
        if type(stamp) not in (float, int) or not math.isfinite(stamp) or stamp < 0:
            raise ValueError("Worker health clock is invalid")
        record = {
            "schema_version": 1,
            "pid": os.getpid(),
            "monotonic_seconds": stamp,
            "ready": ready,
            "active_children": active,
        }
        temporary = self.path.with_name(self.path.name + "." + uuid4().hex + ".pending")
        owned = False
        try:
            descriptor = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            owned = True
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(json.dumps(record, separators=(",", ":")))
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
        finally:
            if owned:
                temporary.unlink(missing_ok=True)

    def _matches(self, *, ready: bool, active: int | None, maximum_age_seconds: float) -> bool:
        if (
            type(maximum_age_seconds) not in (float, int)
            or not math.isfinite(maximum_age_seconds)
            or not 0 < maximum_age_seconds <= 60
        ):
            raise ValueError("Worker health age must be bounded")
        try:
            self._existing()
            descriptor = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as stream:
                data = stream.read(1025)
            if len(data) > 1024:
                return False
            value = json.loads(data)
            if (
                type(value) is not dict
                or set(value)
                != {"schema_version", "pid", "monotonic_seconds", "ready", "active_children"}
                or type(value["schema_version"]) is not int
                or value["schema_version"] != 1
                or type(value["pid"]) is not int
                or not 1 <= value["pid"] <= 2147483647
                or type(value["ready"]) is not bool
                or type(value["active_children"]) is not int
                or value["active_children"] not in {0, 1}
                or type(value["monotonic_seconds"]) not in (float, int)
                or not math.isfinite(value["monotonic_seconds"])
            ):
                return False
            age = self.clock() - value["monotonic_seconds"]
            if (
                value["ready"] is not ready
                or (active is not None and value["active_children"] != active)
                or not 0 <= age <= maximum_age_seconds
            ):
                return False
            os.kill(value["pid"], 0)
            return True
        except (OSError, ValueError, TypeError, KeyError, OverflowError):
            return False

    def ready(self, *, maximum_age_seconds: float = 10) -> bool:
        return self._matches(ready=True, active=None, maximum_age_seconds=maximum_age_seconds)

    def is_quiescent(self, *, maximum_age_seconds: float = 10) -> bool:
        """Observe a fresh live not-ready worker with no owned child."""
        return self._matches(ready=False, active=0, maximum_age_seconds=maximum_age_seconds)


def _supplier(settings: WorkerSettings) -> MutationSupplier:
    from .mutation_supplier import MutationSupplier, NonCooperatingMutationSupplier

    factory = MutationSupplier if settings.cooperating else NonCooperatingMutationSupplier
    return factory(settings.supplier_db)


def _execute_step(settings: WorkerSettings, claim: WorkClaim) -> None:
    from .authorization import AuthenticatedActor
    from .completion_sink import CompletionSink
    from .effect_models import DeliveryState
    from .lifecycle_models import LifecycleState
    from .managed_inquiry_worker import ManagedInquiryWorker
    from .mutation_worker import MutationWorker
    from .outbox_delivery import CompletionDeliveryWorker
    from .postgres_effects import PostgresEffects
    from .postgres_lifecycle import PostgresLifecycle
    from .postgres_settings import PostgresSettings
    from .postgres_store import PostgresExecutionStore

    executions = PostgresExecutionStore(PostgresSettings.from_env())
    lifecycle = PostgresLifecycle(executions, worker_lease=claim.grant)
    effects = PostgresEffects(executions, worker_lease=claim.grant)
    if claim.kind == WorkKind.INQUIRY:
        current = lifecycle.get(scope_id=settings.scope_id, task_id=claim.grant.task_id)
        if current.state not in {
            LifecycleState.READY,
            LifecycleState.RUNNING,
            LifecycleState.RETRY_WAIT,
            LifecycleState.INQUIRY_COMPLETE,
        }:
            raise TransitionConflict("Inquiry selection is no longer current")
        ManagedInquiryWorker(lifecycle, _supplier(settings).inquiry_view()).run_one(
            scope_id=settings.scope_id, task_id=claim.grant.task_id
        )
    elif claim.kind == WorkKind.WAIT:
        current = lifecycle.get(scope_id=settings.scope_id, task_id=claim.grant.task_id)
        if current.state != LifecycleState.WAITING or claim.actor_id is None:
            raise TransitionConflict("Wait selection is no longer current")
        lifecycle.advance(
            actor=AuthenticatedActor(claim.actor_id, settings.scope_id), task_id=claim.grant.task_id
        )
    elif claim.kind == WorkKind.MUTATION:
        current = lifecycle.get(scope_id=settings.scope_id, task_id=claim.grant.task_id)
        if current.state != LifecycleState.INTENT_COMMITTED:
            raise TransitionConflict("Mutation selection is no longer current")
        MutationWorker(effects, _supplier(settings)).run_one(
            scope_id=settings.scope_id, task_id=claim.grant.task_id
        )
    else:
        delivery = effects.delivery_for_scope(
            scope_id=settings.scope_id, task_id=claim.grant.task_id
        )
        if delivery is None or delivery.state not in {
            DeliveryState.PENDING,
            DeliveryState.DELIVERING,
        }:
            raise TransitionConflict("Delivery selection is no longer current")
        CompletionDeliveryWorker(effects, CompletionSink(settings.sink_db)).run_one(
            scope_id=settings.scope_id, task_id=claim.grant.task_id
        )
    print(json.dumps({"status": "step_completed", "kind": claim.kind.value}))


def _step(settings: WorkerSettings) -> None:
    claim = parse_work_claim(os.environ.get("P1_WORKER_CLAIM", ""))
    if claim.grant.scope_id != settings.scope_id:
        raise TransitionConflict("Work claim belongs to another configured scope")
    endpoint = os.environ.get("P1_TRACE_ENDPOINT")
    if not endpoint:
        _execute_step(settings, claim)
        return

    # The base worker lane never imports OpenTelemetry. A trusted optional
    # endpoint opts this owned child into content-free local tracing.
    from .tracing import TraceRuntime, TraceSettings

    tracing = TraceRuntime(
        TraceSettings(
            "durable-worker",
            endpoint=endpoint,
            shutdown_timeout=0.3,
            mode=os.environ.get("P1_TRACE_MODE", "scripted"),
        )
    )
    attributes: dict[str, str | float] = {
        "continuity.task_id": claim.grant.task_id,
        "continuity.epoch": claim.grant.epoch,
    }
    try:
        with tracing.span(claim.kind.value, **attributes) as span:
            started = time.monotonic()
            try:
                _execute_step(settings, claim)
            finally:
                span.set_attribute(
                    "continuity.duration_seconds", max(0, time.monotonic() - started)
                )
    finally:
        try:
            tracing.provider.force_flush(timeout_millis=300)
        except Exception:  # noqa: BLE001 - preserve business result, never render telemetry errors
            _event("worker_trace_cleanup_failed", "dependency_unavailable")
        finally:
            try:
                tracing.close()
            except Exception:  # noqa: BLE001 - optional diagnostics cannot mask operation errors
                _event("worker_trace_cleanup_failed", "dependency_unavailable")


def _child_environment(settings: WorkerSettings) -> dict[str, str]:
    from .postgres_settings import PostgresSettings

    database = PostgresSettings.from_env()
    environment = {
        "PATH": os.defpath,
        "LANG": "C.UTF-8",
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "P1_POSTGRES_HOST": database.host,
        "P1_POSTGRES_PORT": str(database.port),
        "P1_POSTGRES_DB": database.dbname,
        "P1_POSTGRES_USER": database.user,
        "P1_POSTGRES_PASSWORD": database.password,
        "P1_POSTGRES_SCHEMA": database.schema,
        "P1_WORKER_SCOPE": settings.scope_id,
        "P1_WORKER_SUPPLIER_DB": str(settings.supplier_db),
        "P1_WORKER_SINK_DB": str(settings.sink_db),
        "P1_WORKER_SUPPLIER_MODE": "cooperating" if settings.cooperating else "noncooperating",
    }
    endpoint = os.environ.get("P1_TRACE_ENDPOINT")
    if endpoint:
        from .tracing import TraceSettings

        mode = os.environ.get("P1_TRACE_MODE", "scripted")
        TraceSettings("durable-worker", endpoint=endpoint, mode=mode)
        environment["P1_TRACE_ENDPOINT"] = endpoint
        if "P1_TRACE_MODE" in os.environ:
            environment["P1_TRACE_MODE"] = mode
    return environment


def _run(settings: WorkerSettings, *, once: bool) -> None:
    from .completion_sink import CompletionSink
    from .postgres_settings import PostgresSettings
    from .postgres_store import PostgresExecutionStore
    from .postgres_work import PostgresWorkQueue

    _supplier(settings)
    CompletionSink(settings.sink_db)
    queue = PostgresWorkQueue(PostgresExecutionStore(PostgresSettings.from_env()))
    limits = queue.policy()
    health = WorkerHealth(settings.state_file)
    telemetry = WorkerTelemetry()

    def observe(ready: bool, active: int) -> None:
        health.publish(ready, active)
        metrics = settings.state_file.with_suffix(".prom")
        # Reuse health path ownership rules; metrics contain only fixed labels.
        WorkerHealth(metrics)._existing()
        temporary = metrics.with_name(metrics.name + "." + uuid4().hex + ".pending")
        owned = False
        try:
            payload = telemetry.render()
            if len(payload) > 131072:
                raise ValueError("Worker metric snapshot exceeded its bound")
            descriptor = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            owned = True
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
            temporary.replace(metrics)
        finally:
            if owned:
                temporary.unlink(missing_ok=True)

    launcher = ProcessStepLauncher(
        (sys.executable, "-m", "continuity_lab.worker_cli", "step"),
        environment=_child_environment(settings),
        cwd=Path(tempfile.gettempdir()),
        observe_code=telemetry.lease_rejection,
    )
    runtime = WorkerRuntime(
        queue,
        launcher,
        scope_id=settings.scope_id,
        lease_seconds=limits.lease_seconds,
        policy=settings.policy,
        observe=observe,
        telemetry=telemetry,
    )

    def stop(_signum: int, _frame: FrameType | None) -> None:
        runtime.request_stop()

    def quiesce(_signum: int, _frame: FrameType | None) -> None:
        runtime.request_quiesce()

    def resume(_signum: int, _frame: FrameType | None) -> None:
        runtime.request_resume()

    handlers = {
        signal.SIGTERM: stop,
        signal.SIGINT: stop,
        signal.SIGUSR1: quiesce,
        signal.SIGUSR2: resume,
    }
    previous = {sig: signal.getsignal(sig) for sig in handlers}
    try:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
        # Readiness cannot precede installation of the maintenance/stop handlers.
        health.publish(True, 0)
        if once:
            result = runtime.run_once()
            print(
                json.dumps(
                    {
                        "status": "idle" if result is None else "step_observed",
                        "outcome": None if result is None else result.outcome.value,
                    }
                )
            )
        else:
            runtime.run()
    finally:
        runtime.request_stop()
        try:
            health.publish(False, 0)
        except (OSError, ValueError):
            _event("worker_health_failed", "worker_health_unavailable")
        for sig, original in previous.items():
            signal.signal(sig, original)


def _initialize(settings: WorkerSettings) -> None:
    from .completion_sink import CompletionSink, initialize_completion_sink
    from .mutation_supplier import initialize_mutation_supplier

    for database in (settings.supplier_db, settings.sink_db):
        database.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not settings.supplier_db.exists():
        initialize_mutation_supplier(
            settings.supplier_db, scope_id=settings.scope_id, cooperating=settings.cooperating
        )
    supplier = _supplier(settings)
    supplier.booking(scope_id=settings.scope_id, booking_reference="DEMO-BK-001")
    initialize_completion_sink(settings.sink_db)
    print(
        json.dumps(
            {
                "status": "fixtures_ready",
                "provider_id": supplier.provider_id,
                "receiver_id": CompletionSink(settings.sink_db).receiver_id,
            }
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = _SafeParser(description=__doc__)
    parser.add_argument(
        "command", choices=("init-fixtures", "run", "once", "step", "health", "metrics")
    )
    args = parser.parse_args(argv)
    configure_logging()
    try:
        settings = WorkerSettings.from_env()
        if args.command != "step" and "P1_WORKER_CLAIM" in os.environ:
            raise ValueError("A parent worker cannot accept an ambient work claim")
        if args.command == "metrics":
            metrics = settings.state_file.with_suffix(".prom")
            WorkerHealth(metrics)._existing()
            descriptor = os.open(metrics, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as stream:
                payload = stream.read(131073)
            if len(payload) > 131072:
                raise ValueError("Worker metric snapshot exceeded its bound")
            print(payload.decode("utf-8"), end="")
            return 0
        if args.command == "health":
            ready = WorkerHealth(settings.state_file).ready()
            print(json.dumps({"status": "ready" if ready else "not_ready"}))
            return 0 if ready else 1
        if args.command == "init-fixtures":
            _initialize(settings)
        elif args.command == "step":
            _step(settings)
        else:
            _run(settings, once=args.command == "once")
        return 0
    except (ExecutionError, ValueError, OSError) as error:
        code = "invalid_input"
        if isinstance(error, ExecutionError):
            code = _safe_code(error)
        print(json.dumps({"status": "failed", "code": code}))
        _event("worker_cli_failed", code)
        return 2
    except Exception:  # noqa: BLE001 - secret-safe process boundary
        print('{"status":"failed","code":"unexpected_error"}')
        _event("worker_cli_failed", "unexpected_error")
        return 1


if __name__ == "__main__":
    sys.exit(main())
