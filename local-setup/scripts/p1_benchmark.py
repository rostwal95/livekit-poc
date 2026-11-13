"""Opt-in local inquiry workload measurements over installed HTTP/worker services.

Every experiment owns fresh state. Samples describe observed infrastructure,
not media/model performance, a reusable library, or a complete release gate.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import math
import os
import platform
import random
import re
import secrets
import socket
import statistics
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Coroutine, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, NoReturn, ParamSpec, TypeVar
from uuid import UUID, uuid4, uuid5

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
MAX_HTTP_BYTES = 65536
SCOPE = "benchmark-traveller"
EXPERIMENTS = frozenset(
    f"{kind}-w{workers}" for kind in ("steady", "burst", "saturation") for workers in (1, 2)
)
ERRORS = frozenset(
    {
        "invalid_evidence",
        "deadline_exceeded",
        "dependency_unavailable",
        "reconciliation_failed",
        "capacity_mismatch",
        "resource_mismatch",
        "cleanup_failed",
        "missing_setup",
        "http_unknown",
    }
)
if TYPE_CHECKING:
    from harness.workload_models import Experiment, ResourceLimits, WorkloadManifest


OPERATIONS = frozenset(
    {
        "unknown",
        "preflight",
        "configuration",
        "schema_prepare",
        "volume_prepare",
        "volume_bootstrap",
        "volume_write_access",
        "fixture_init",
        "api_startup",
        "worker_startup",
        "api_readiness",
        "worker_readiness",
        "provenance",
        "sampling",
        "admission",
        "inspection",
        "cancellation",
        "reconciliation",
        "cleanup",
    }
)
_OPERATION: ContextVar[str] = ContextVar("benchmark_operation", default="unknown")
_P = ParamSpec("_P")
_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class CommandObservation:
    """Only observed process status/timing; no command or captured-output fields."""

    exit_code: int | None
    timed_out: bool
    timeout_seconds: float
    elapsed_seconds: float

    def __post_init__(self) -> None:
        if (
            self.exit_code is not None
            and (type(self.exit_code) is not int or not -(2**31) <= self.exit_code < 2**31)
        ) or type(self.timed_out) is not bool:
            raise ValueError("Invalid command status observation")
        if (
            any(
                type(value) not in {int, float}
                or not math.isfinite(value)
                or not 0 <= value <= 3600
                for value in (self.timeout_seconds, self.elapsed_seconds)
            )
            or self.timeout_seconds == 0
        ):
            raise ValueError("Invalid command timing observation")


class BenchmarkError(RuntimeError):
    def __init__(
        self, code: str, *, operation: str = "unknown", command: CommandObservation | None = None
    ) -> None:
        if type(code) is not str or code not in ERRORS:
            raise ValueError("Unsupported benchmark failure code")
        if type(operation) is not str or operation not in OPERATIONS:
            raise ValueError("Unsupported benchmark operation")
        if command is not None and type(command) is not CommandObservation:
            raise ValueError("Invalid command observation")
        self.code, self.operation, self.command = code, operation, command
        super().__init__("The local workload requirement did not pass")


def contextual_error(error: Exception, operation: str) -> BenchmarkError:
    if isinstance(error, BenchmarkError) and error.operation != "unknown":
        return error
    observed = failure_observation(error)
    command = observed["command"]
    return BenchmarkError(
        str(observed["code"]),
        operation=operation if observed["operation"] == "unknown" else str(observed["operation"]),
        command=CommandObservation(**command) if isinstance(command, dict) else None,
    )


@contextmanager
def operation_scope(operation: str) -> Iterator[None]:
    if operation not in OPERATIONS:
        raise ValueError("Unsupported benchmark operation")
    token = _OPERATION.set(operation)
    try:
        yield
    except Exception as error:
        contextual = contextual_error(error, operation)
        if contextual is error:
            raise
        raise contextual from error
    finally:
        _OPERATION.reset(token)


def at_operation(operation: str) -> Callable[[Callable[_P, _T]], Callable[_P, _T]]:
    def decorate(function: Callable[_P, _T]) -> Callable[_P, _T]:
        @wraps(function)
        def invoke(*args: _P.args, **kwargs: _P.kwargs) -> _T:
            with operation_scope(operation):
                return function(*args, **kwargs)

        return invoke

    return decorate


def at_async_operation(
    operation: str,
) -> Callable[[Callable[_P, Coroutine[Any, Any, _T]]], Callable[_P, Coroutine[Any, Any, _T]]]:
    def decorate(
        function: Callable[_P, Coroutine[Any, Any, _T]],
    ) -> Callable[_P, Coroutine[Any, Any, _T]]:
        @wraps(function)
        async def invoke(*args: _P.args, **kwargs: _P.kwargs) -> _T:
            with operation_scope(operation):
                return await function(*args, **kwargs)

        return invoke

    return decorate


class Budget:
    def __init__(self, seconds: float, *, clock: Callable[[], float] = time.monotonic) -> None:
        if (
            type(seconds) not in {int, float}
            or not math.isfinite(seconds)
            or not 0 < seconds <= 600
        ):
            raise ValueError("Workload deadline must be finite and bounded")
        self.clock, self.started, self.seconds = clock, clock(), seconds
        if not math.isfinite(self.started):
            raise ValueError("Workload clock must be finite")

    def remaining(self, cap: float = 600) -> float:
        value = min(cap, self.seconds - self.elapsed())
        if not math.isfinite(value) or value <= 0:
            raise BenchmarkError("deadline_exceeded")
        return value

    def elapsed(self) -> float:
        value = self.clock() - self.started
        if not math.isfinite(value) or value < 0:
            raise BenchmarkError("invalid_evidence")
        return value


def strict_json(raw: bytes, maximum: int = MAX_HTTP_BYTES) -> Any:
    if type(raw) is not bytes or not 0 < len(raw) <= maximum:
        raise BenchmarkError("invalid_evidence")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise BenchmarkError("invalid_evidence")
            result[key] = value
        return result

    def constant(_value: str) -> NoReturn:
        raise BenchmarkError("invalid_evidence")

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise BenchmarkError("invalid_evidence") from error


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def uuid_value(value: object) -> str:
    if type(value) is not str:
        raise BenchmarkError("invalid_evidence")
    try:
        if str(UUID(value)) == value:
            return value
    except ValueError:
        pass
    raise BenchmarkError("invalid_evidence")


def owned_prefix(run_id: str, experiment_index: int) -> str:
    if (
        type(run_id) is not str
        or re.fullmatch("[0-9a-f]{32}", run_id) is None
        or type(experiment_index) is not int
        or not 0 <= experiment_index < 6
    ):
        raise BenchmarkError("invalid_evidence")
    return f"p1-h-{run_id}-{experiment_index}"


def timing_summary(values: Sequence[float]) -> dict[str, int | float]:
    if not values or any(
        type(value) not in {int, float} or not math.isfinite(value) or value < 0 for value in values
    ):
        raise BenchmarkError("invalid_evidence")
    return {
        "samples": len(values),
        "minimum_seconds": min(values),
        "median_seconds": statistics.median(values),
        "maximum_seconds": max(values),
    }


def next_resource_tick(target: float, finished: float, interval: int) -> tuple[float, int]:
    if (
        type(interval) is not int
        or interval != 1
        or not math.isfinite(target)
        or not math.isfinite(finished)
    ):
        raise BenchmarkError("invalid_evidence")
    skipped = 0 if target > finished else int((finished - target) // interval) + 1
    return target + skipped * interval, skipped


def failure_observation(error: BaseException, depth: int = 0) -> dict[str, object]:
    """Select the original bounded failure; never serialize exception text or attributes wholesale."""
    if isinstance(error, BenchmarkError):
        try:
            checked = BenchmarkError(
                error.code,
                operation=error.operation,
                command=CommandObservation(**asdict(error.command))
                if error.command is not None
                else None,
            )
        except (TypeError, ValueError):
            return {"code": "invalid_evidence", "operation": "unknown", "command": None}
        return {
            "code": checked.code,
            "operation": checked.operation,
            "command": asdict(checked.command) if checked.command is not None else None,
        }
    if isinstance(error, BaseExceptionGroup) and depth < 4:
        observations = [failure_observation(child, depth + 1) for child in error.exceptions[:32]]
        return next(
            (item for item in observations if item["code"] != "dependency_unavailable"),
            observations[0],
        )
    from harness.process_control import ProcessOutputLimit, ProcessTimeout

    code = (
        "deadline_exceeded"
        if isinstance(error, ProcessTimeout)
        else (
            "invalid_evidence"
            if isinstance(error, ProcessOutputLimit)
            else "dependency_unavailable"
        )
    )
    return {"code": code, "operation": "unknown", "command": None}


def failure_code(error: BaseException, depth: int = 0) -> str:
    return str(failure_observation(error, depth)["code"])


def retain_failure_context(
    report: Path, experiment: str, error: BaseException, *, cleanup: bool = False
) -> dict[str, object]:
    """Retain the closed failure record before private command output is removed."""
    if experiment not in EXPERIMENTS or type(cleanup) is not bool:
        raise ValueError("Unsupported failure context")
    observed = failure_observation(error)
    record = {
        "experiment": experiment,
        "stage": "cleanup" if cleanup else "execution",
        "status": "failed",
        "failure": observed,
    }
    path = report / (experiment + (".cleanup-failure.json" if cleanup else ".failure.json"))
    with os.fdopen(
        os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb"
    ) as stream:
        stream.write(canonical(record) + b"\n")
    return observed


class EvidenceLog:
    """Closed numeric vocabularies; no payload, key, token or exception fields."""

    FIELDS: ClassVar[dict[str, set[str]]] = {
        "http": {
            "index",
            "operation",
            "disposition",
            "http_status",
            "duration_seconds",
            "attempt",
            "scheduled_offer_seconds",
            "http_start_seconds",
            "attempt_finished_seconds",
            "offer_queue_delay_seconds",
        },
        "resource": {
            "role",
            "worker_index",
            "cpu_usage_usec",
            "memory_current_bytes",
            "pids_current",
            "cpu_quota_usec",
            "cpu_period_usec",
            "memory_limit_bytes",
            "pids_limit",
            "probe_started_seconds",
            "probe_finished_seconds",
            "probe_duration_seconds",
        },
        "queue": {
            "outstanding",
            "active",
            "maximum_pending",
            "maximum_active",
            "oldest_outstanding_seconds",
            "recovery_lag_seconds",
        },
        "result": {
            "index",
            "scheduled_offer_seconds",
            "http_start_seconds",
            "acknowledged_seconds",
            "first_observed_succeeded_seconds",
            "observed_result_latency_seconds",
            "observation_source",
        },
        "observer": {"duration_seconds", "skipped_intervals"},
    }

    def __init__(self, path: Path, maximum: int) -> None:
        if type(maximum) is not int or not 1 <= maximum <= 4096:
            raise ValueError("Sample capacity must be bounded")
        self._file = os.fdopen(
            os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "w"
        )
        self.maximum, self.count, self._lock = maximum, 0, threading.Lock()

    def record(self, experiment: str, kind: str, elapsed: float, **fields: object) -> None:
        if (
            experiment not in EXPERIMENTS
            or kind not in self.FIELDS
            or set(fields) != self.FIELDS[kind]
        ):
            raise BenchmarkError("invalid_evidence")
        enums = {
            "role": {"api", "worker"},
            "operation": {"submit", "replay", "get", "cancel"},
            "disposition": {
                "accepted",
                "replayed",
                "rejected",
                "observed",
                "cancelled",
                "unknown",
                "failed",
            },
            "observation_source": {"submit", "replay", "get"},
        }
        for key, value in {"elapsed_seconds": elapsed, **fields}.items():
            if key in enums:
                if type(value) is not str or value not in enums[key]:
                    raise BenchmarkError("invalid_evidence")
            else:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise BenchmarkError("invalid_evidence")
                if not math.isfinite(value) or not 0 <= value <= 9223372036854775807:
                    raise BenchmarkError("invalid_evidence")
                if not key.endswith("seconds") and type(value) is not int:
                    raise BenchmarkError("invalid_evidence")
        bounded = {
            "index": (0, 31),
            "attempt": (1, 3),
            "http_status": (0, 599),
            "worker_index": (0, 2),
        }
        for key, (lower, upper) in bounded.items():
            if key in fields:
                number = fields[key]
                if type(number) is not int or not lower <= number <= upper:
                    raise BenchmarkError("invalid_evidence")
        with self._lock:
            if self.count >= self.maximum:
                raise BenchmarkError("invalid_evidence")
            self._file.write(
                json.dumps(
                    {
                        "schema_version": 1,
                        "experiment": experiment,
                        "kind": kind,
                        "elapsed_seconds": elapsed,
                        **fields,
                    },
                    allow_nan=False,
                )
                + "\n"
            )
            self._file.flush()
            self.count += 1

    def close(self) -> None:
        self._file.close()


@dataclass(frozen=True, slots=True)
class CgroupObservation:
    cpu_usage_usec: int
    memory_current_bytes: int
    pids_current: int
    cpu_quota_usec: int
    cpu_period_usec: int
    memory_limit_bytes: int
    pids_limit: int

    @classmethod
    def parse(cls, value: object, limits: ResourceLimits) -> CgroupObservation:
        keys = set(cls.__dataclass_fields__)
        if (
            type(value) is not dict
            or set(value) != keys
            or any(
                type(number) is not int or not 0 <= number <= 9223372036854775807
                for number in value.values()
            )
        ):
            raise BenchmarkError("invalid_evidence")
        result = cls(**value)
        if (
            result.cpu_period_usec < 1
            or result.cpu_quota_usec * 1000 != limits.cpu_millicores * result.cpu_period_usec
            or result.memory_limit_bytes != limits.memory_bytes
            or result.pids_limit != limits.pids_limit
            or result.memory_current_bytes < 1
            or result.pids_current < 1
        ):
            raise BenchmarkError("resource_mismatch")
        return result


CGROUP_SCRIPT = """import json
from pathlib import Path
p=Path('/sys/fs/cgroup')
def number(name):
    value=(p/name).read_text().strip()
    if not value.isdecimal(): raise ValueError('Finite cgroup limit required')
    return int(value)
cpu=dict(line.split() for line in (p/'cpu.stat').read_text().splitlines())
quota,period=(p/'cpu.max').read_text().split()
if not quota.isdecimal() or not period.isdecimal(): raise ValueError('Finite CPU limit required')
print(json.dumps({'cpu_usage_usec':int(cpu['usage_usec']),'memory_current_bytes':number('memory.current'),'pids_current':number('pids.current'),'cpu_quota_usec':int(quota),'cpu_period_usec':int(period),'memory_limit_bytes':number('memory.max'),'pids_limit':number('pids.max')}))
"""


@dataclass(slots=True)
class Investigation:
    index: int
    key: str
    request: dict[str, str | bool]
    task_id: str | None = None
    case_id: str | None = None
    effect_id: str | None = None
    scheduled_offer_at: float | None = None
    submitted_at: float | None = None
    acknowledged_at: float | None = None
    result_at: float | None = None
    result_source: str | None = None
    rejected: bool = False
    cancelled: bool = False

    def body(self) -> dict[str, object]:
        return {**self.request, "idempotency_key": self.key}


def projection(value: object, inquiry: Investigation) -> dict[str, Any]:
    if (
        type(value) is not dict
        or type(value.get("schema_version")) is not int
        or value["schema_version"] != 1
        or value.get("request_key") != inquiry.key
        or value.get("request") != inquiry.request
    ):
        raise BenchmarkError("reconciliation_failed")
    task, case = uuid_value(value.get("task_id")), uuid_value(value.get("case_id"))
    if (inquiry.task_id is not None and task != inquiry.task_id) or (
        inquiry.case_id is not None and case != inquiry.case_id
    ):
        raise BenchmarkError("reconciliation_failed")
    original = value.get("inquiry")
    if (
        type(original) is not dict
        or original.get("request") != inquiry.request
        or original.get("state") not in {"accepted", "running", "succeeded", "failed"}
    ):
        raise BenchmarkError("reconciliation_failed")
    effect_id = uuid_value(original.get("effect_id"))
    if inquiry.effect_id is not None and inquiry.effect_id != effect_id:
        raise BenchmarkError("reconciliation_failed")
    if original["state"] == "succeeded":
        expected = {key: inquiry.request[key] for key in ("booking_reference", "new_check_in")}
        if original.get("result") != {**expected, "available": True}:
            raise BenchmarkError("reconciliation_failed")
    if (
        value.get("quote") is not None
        or value.get("effect") is not None
        or type(value.get("confirmation")) is not dict
        or value["confirmation"].get("state") not in {"not_requested", "cancelled"}
    ):
        raise BenchmarkError("reconciliation_failed")
    inquiry.task_id, inquiry.case_id, inquiry.effect_id = task, case, effect_id
    return value


def acceptance(value: object, inquiry: Investigation, *, replay: bool) -> dict[str, Any]:
    if (
        type(value) is not dict
        or set(value) != {"created", "task_id", "case_id", "projection"}
        or type(value["created"]) is not bool
        or (replay and value["created"] is not False)
    ):
        raise BenchmarkError("reconciliation_failed")
    current = projection(value["projection"], inquiry)
    if (value["task_id"], value["case_id"]) != (current["task_id"], current["case_id"]):
        raise BenchmarkError("reconciliation_failed")
    return current


class HTTPDriver:
    def __init__(
        self,
        base_url: str,
        token: str,
        budget: Budget,
        overall: Budget,
        evidence: EvidenceLog,
        experiment: Experiment,
        http_timeout_seconds: int,
    ) -> None:
        import httpx

        if re.fullmatch(r"http://127\.0\.0\.1:[0-9]{1,5}", base_url) is None:
            raise ValueError("Only an owned loopback HTTP origin is supported")
        self.client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": "Bearer " + token},
            trust_env=False,
            limits=httpx.Limits(
                max_connections=experiment.client_concurrency,
                max_keepalive_connections=experiment.client_concurrency,
            ),
            follow_redirects=False,
        )
        self.budget, self.overall, self.evidence, self.experiment = (
            budget,
            overall,
            evidence,
            experiment,
        )
        self.http_timeout_seconds = http_timeout_seconds
        self.slots = asyncio.Semaphore(experiment.client_concurrency)

    @at_async_operation("api_readiness")
    async def healthy(self) -> bool:
        import httpx

        try:
            async with (
                asyncio.timeout(min(self.budget.remaining(), self.overall.remaining())),
                self.slots,
            ):
                timeout = min(
                    self.budget.remaining(self.http_timeout_seconds),
                    self.overall.remaining(self.http_timeout_seconds),
                )
                async with (
                    asyncio.timeout(timeout),
                    self.client.stream("GET", "/readyz", timeout=timeout) as response,
                ):
                    raw = bytearray()
                    async for part in response.aiter_bytes():
                        raw.extend(part)
                        if len(raw) > MAX_HTTP_BYTES:
                            raise BenchmarkError("invalid_evidence")
                    value = strict_json(bytes(raw))
                    return (
                        response.status_code == 200
                        and type(value) is dict
                        and value.get("status") == "ready"
                    )
        except (httpx.HTTPError, TimeoutError):
            return False

    def observed_result(
        self, inquiry: Investigation, current: Mapping[str, Any], source: str
    ) -> None:
        if inquiry.result_at is not None or current["inquiry"]["state"] != "succeeded":
            return
        if (
            inquiry.scheduled_offer_at is None
            or inquiry.submitted_at is None
            or inquiry.acknowledged_at is None
        ):
            raise BenchmarkError("reconciliation_failed")
        inquiry.result_at = time.monotonic()
        inquiry.result_source = source
        self.evidence.record(
            self.experiment.name,
            "result",
            self.budget.elapsed(),
            index=inquiry.index,
            scheduled_offer_seconds=inquiry.scheduled_offer_at - self.budget.started,
            http_start_seconds=inquiry.submitted_at - self.budget.started,
            acknowledged_seconds=inquiry.acknowledged_at - self.budget.started,
            first_observed_succeeded_seconds=inquiry.result_at - self.budget.started,
            observed_result_latency_seconds=inquiry.result_at - inquiry.scheduled_offer_at,
            observation_source=source,
        )

    async def request(
        self,
        inquiry: Investigation,
        operation: str,
        path: str,
        body: object | None = None,
        attempt: int = 1,
    ) -> tuple[int, Any]:
        import httpx

        offered = time.monotonic()
        scheduled = inquiry.scheduled_offer_at if operation == "submit" else offered
        if scheduled is None:
            raise BenchmarkError("invalid_evidence")
        started: float | None = None
        status, value, disposition = 0, None, "unknown"
        try:
            async with (
                asyncio.timeout(min(self.budget.remaining(), self.overall.remaining())),
                self.slots,
            ):
                started = time.monotonic()
                if operation == "submit" and inquiry.submitted_at is None:
                    inquiry.submitted_at = started
                timeout = min(
                    self.budget.remaining(self.http_timeout_seconds),
                    self.overall.remaining(self.http_timeout_seconds),
                )
                async with (
                    asyncio.timeout(timeout),
                    self.client.stream(
                        "GET" if body is None else "POST", path, json=body, timeout=timeout
                    ) as response,
                ):
                    raw = bytearray()
                    async for part in response.aiter_bytes():
                        raw.extend(part)
                        if len(raw) > MAX_HTTP_BYTES:
                            raise BenchmarkError("invalid_evidence")
                    status, value = response.status_code, strict_json(bytes(raw))
                    disposition = (
                        "observed"
                        if status == 200
                        else "rejected"
                        if status == 503
                        and type(value) is dict
                        and value.get("code") == "capacity_exhausted"
                        else "failed"
                    )
        except (httpx.HTTPError, TimeoutError):
            pass
        finally:
            if started is not None:
                acknowledged = time.monotonic()
                self.evidence.record(
                    self.experiment.name,
                    "http",
                    self.budget.elapsed(),
                    index=inquiry.index,
                    operation=operation,
                    disposition=disposition,
                    http_status=status,
                    duration_seconds=acknowledged - started,
                    attempt=attempt,
                    scheduled_offer_seconds=scheduled - self.budget.started,
                    http_start_seconds=started - self.budget.started,
                    attempt_finished_seconds=acknowledged - self.budget.started,
                    offer_queue_delay_seconds=max(0, started - scheduled),
                )
        return status, value

    @at_async_operation("admission")
    async def submit(
        self, inquiry: Investigation, *, replay: bool = False, reject: bool = False
    ) -> None:
        for attempt in range(1, 4):
            status, value = await self.request(
                inquiry,
                "replay" if replay else "submit",
                "/api/business/investigations",
                inquiry.body(),
                attempt,
            )
            if status == 200:
                if reject:
                    raise BenchmarkError("capacity_mismatch")
                current = acceptance(value, inquiry, replay=replay)
                if inquiry.acknowledged_at is None:
                    inquiry.acknowledged_at = time.monotonic()
                self.observed_result(inquiry, current, "replay" if replay else "submit")
                return
            if status == 503 and type(value) is dict and value.get("code") == "capacity_exhausted":
                if not reject or replay or attempt != 1:
                    raise BenchmarkError("capacity_mismatch")
                inquiry.rejected = True
                return
            if status != 0:
                raise BenchmarkError("dependency_unavailable")
            await asyncio.sleep(min(0.1, self.budget.remaining(), self.overall.remaining()))
        raise BenchmarkError("http_unknown")

    @at_async_operation("inspection")
    async def get(self, inquiry: Investigation) -> dict[str, Any]:
        if inquiry.task_id is None:
            raise BenchmarkError("reconciliation_failed")
        status, value = await self.request(
            inquiry, "get", f"/api/business/cases/{inquiry.task_id}?limit=1"
        )
        if status != 200:
            raise BenchmarkError("http_unknown" if status == 0 else "dependency_unavailable")
        current = projection(value, inquiry)
        self.observed_result(inquiry, current, "get")
        return current

    @at_async_operation("cancellation")
    async def cancel(self, inquiry: Investigation) -> None:
        if inquiry.task_id is None:
            raise BenchmarkError("reconciliation_failed")
        command = str(uuid5(UUID(inquiry.task_id), "benchmark-explicit-cleanup-cancel"))
        for attempt in range(1, 4):
            status, value = await self.request(
                inquiry,
                "cancel",
                f"/api/business/cases/{inquiry.task_id}/cancel",
                {"command_id": command},
                attempt,
            )
            if status == 200 and type(value) is dict and set(value) == {"projection", "receipt"}:
                current = projection(value["projection"], inquiry)
                receipt = value["receipt"]
                if (
                    type(receipt) is not dict
                    or receipt.get("command_id") != command
                    or receipt.get("disposition") != "cancelled_before_commit"
                    or current.get("outcome", {}).get("state") != "cancelled"
                ):
                    raise BenchmarkError("reconciliation_failed")
                inquiry.cancelled = True
                return
            if status != 0:
                raise BenchmarkError("dependency_unavailable")
        raise BenchmarkError("http_unknown")


@at_operation("reconciliation")
def reconcile(
    inquiries: Sequence[Investigation],
    rows: object,
    authority: object,
    expected_accepted: int,
    expected_rejected: int,
) -> dict[str, int]:
    accepted = [item for item in inquiries if item.task_id is not None]
    if (
        len(accepted) != expected_accepted
        or sum(item.rejected for item in inquiries) != expected_rejected
        or any(item.result_at is None or not item.cancelled for item in accepted)
    ):
        raise BenchmarkError("reconciliation_failed")
    expected = {
        item.task_id: {
            "key": item.key,
            "payload": canonical(item.request).decode(),
            "effect_id": item.effect_id,
        }
        for item in accepted
    }
    if (
        len(expected) != expected_accepted
        or len({item.effect_id for item in accepted}) != expected_accepted
        or len({item.key for item in accepted}) != expected_accepted
    ):
        raise BenchmarkError("reconciliation_failed")
    for item in accepted:
        uuid_value(item.task_id)
        uuid_value(item.case_id)
        uuid_value(item.effect_id)
    if (
        type(rows) is not list
        or len(rows) != len(expected)
        or any(
            type(row) is not dict or set(row) != {"task_id", "key", "payload", "effect_id"}
            for row in rows
        )
    ):
        raise BenchmarkError("reconciliation_failed")
    actual = {
        row["task_id"]: {key: row[key] for key in ("key", "payload", "effect_id")} for row in rows
    }
    if actual != expected or len(actual) != len(rows):
        raise BenchmarkError("reconciliation_failed")
    if (
        type(authority) is not dict
        or set(authority)
        != {"booking_unchanged", "apply_calls", "mutations", "receiver_events", "inquiries"}
        or authority["booking_unchanged"] is not True
        or type(authority["apply_calls"]) is not int
        or type(authority["mutations"]) is not int
        or authority["apply_calls"] != 0
        or authority["mutations"] != 0
        or type(authority["receiver_events"]) is not int
        or authority["receiver_events"] != expected_accepted
        or type(authority["inquiries"]) is not list
    ):
        raise BenchmarkError("reconciliation_failed")
    expected_effects = {
        item.effect_id: {
            "request_sha256": hashlib.sha256(canonical(item.request)).hexdigest(),
            "result_sha256": hashlib.sha256(
                canonical(
                    {
                        "booking_reference": item.request["booking_reference"],
                        "new_check_in": item.request["new_check_in"],
                        "available": True,
                    }
                )
            ).hexdigest(),
        }
        for item in accepted
    }
    observed = {}
    for row in authority["inquiries"]:
        if (
            type(row) is not dict
            or set(row) != {"effect_id", "request_sha256", "result_sha256"}
            or row["effect_id"] in observed
        ):
            raise BenchmarkError("reconciliation_failed")
        observed[row["effect_id"]] = {key: row[key] for key in ("request_sha256", "result_sha256")}
    if observed != expected_effects:
        raise BenchmarkError("reconciliation_failed")
    return {
        "accepted": len(accepted),
        "rejected": expected_rejected,
        "inquiry_succeeded": len(accepted),
        "explicitly_cancelled_after_measurement": sum(item.cancelled for item in accepted),
        "receiver_events": expected_accepted,
        "lost_accepted": 0,
        "apply_calls": 0,
        "mutations": 0,
    }


AUTHORITY_SCRIPT = """import sqlite3,json,hashlib
from contextlib import closing
from continuity_lab.mutation_supplier import MutationSupplier
from continuity_lab.completion_sink import CompletionSink
s=MutationSupplier('/data/supplier.sqlite3');b=s.booking(scope_id='benchmark-traveller',booking_reference='DEMO-BK-001')
with closing(sqlite3.connect('file:/data/supplier.sqlite3?mode=ro',uri=True)) as c:
 c.execute('PRAGMA query_only=ON')
 rows=c.execute('SELECT effect_id,request_json,result_json FROM inquiry_receipts WHERE scope_id=? LIMIT 33',('benchmark-traveller',)).fetchall()
print(json.dumps({'booking_unchanged':b.revision==0 and b.check_in.isoformat()=='2030-12-01','apply_calls':s.count_calls(scope_id='benchmark-traveller'),'mutations':s.count_mutations(scope_id='benchmark-traveller'),'receiver_events':CompletionSink('/data/completion.sqlite3').count(),'inquiries':[{'effect_id':r[0],'request_sha256':hashlib.sha256(r[1].encode()).hexdigest(),'result_sha256':hashlib.sha256(r[2].encode()).hexdigest()} for r in rows]}))
"""

PG_PREPARE_SCRIPT = """import json,os
from pathlib import Path
from psycopg import sql
from continuity_lab.postgres_settings import PostgresSettings
from continuity_lab.postgres_migrations import install_schema,upgrade_v2,upgrade_v3,upgrade_v4
from continuity_lab.lease_models import CoordinationPolicy
from continuity_lab.migrations import migrate
from continuity_lab.cutover import cutover
s=PostgresSettings.from_env('P1_MIGRATION_')
with s.connect(application_name='continuity-migrate') as c:
 if c.execute('SELECT 1 FROM pg_namespace WHERE nspname=%s',(s.schema,)).fetchone() is not None:
  print(json.dumps({'status':'refused'}));raise SystemExit(0)
install_schema(s)
with s.connect(application_name='continuity-migrate') as c,c.transaction():
 m=c.execute(sql.SQL('SELECT version,state,migration_id,source_digest,(SELECT COUNT(*) FROM {}) AS tasks FROM {} WHERE singleton').format(sql.Identifier(s.schema,'tasks'),sql.Identifier(s.schema,'schema_metadata'))).fetchone()
 n=c.execute("SELECT oid,pg_get_userbyid(nspowner) AS owner,obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=%s",(s.schema,)).fetchone()
 if m!={'version':1,'state':'staging','migration_id':None,'source_digest':None,'tasks':0} or n is None or n['owner']!='continuity_migrator' or n['marker'] is not None:raise ValueError('Fresh staging ownership required')
 c.execute(sql.SQL('COMMENT ON SCHEMA {} IS {}').format(sql.Identifier(s.schema),sql.Literal(os.environ['H1_SCHEMA_MARKER'])))
 oid=n['oid']
p=Path(os.environ['H1_SOURCE'])
migrate(p,p.with_name('pre-v1.sqlite3'))
cutover(p,p.with_name('pre-cutover.sqlite3'),s)
upgrade_v2(s);upgrade_v3(s);upgrade_v4(s,policy=CoordinationPolicy(**json.loads(os.environ['H1_POLICY'])))
print(json.dumps({'status':'ready','oid':oid}))
"""

PG_READ_SCRIPT = """import json,os
from dataclasses import asdict
from psycopg import sql
from continuity_lab.postgres_settings import PostgresSettings
from continuity_lab.postgres_store import PostgresExecutionStore
from continuity_lab.postgres_work import PostgresWorkQueue
s=PostgresSettings.from_env();scope='benchmark-traveller'
if os.environ['H1_READ']=='queue':
 print(json.dumps(asdict(PostgresWorkQueue(PostgresExecutionStore(s)).snapshot(scope_id=scope))))
elif os.environ['H1_READ']=='rows':
 with s.connect(application_name='continuity-test') as c:
  rows=c.execute(sql.SQL('SELECT t.task_id,t.idempotency_key AS key,t.payload,e.effect_id FROM {} t JOIN {} e USING(task_id) WHERE t.scope_id=%s LIMIT 33').format(sql.Identifier(s.schema,'tasks'),sql.Identifier(s.schema,'executions')),(scope,)).fetchall()
 print(json.dumps(rows))
else:raise ValueError('Unsupported bounded inspection')
"""

PG_CLEANUP_SCRIPT = """import json,os,re
from psycopg import sql
from continuity_lab.postgres_settings import PostgresSettings
s=PostgresSettings.from_env('P1_MIGRATION_')
if re.fullmatch(r'p1_benchmark_[0-9a-f]{32}_[0-5]',s.schema) is None:raise ValueError('Invalid owned namespace')
with s.connect(application_name='continuity-migrate') as c,c.transaction():
 n=c.execute("SELECT oid,pg_get_userbyid(nspowner) AS owner,obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=%s",(s.schema,)).fetchone()
 if n is None:print(json.dumps({'status':'absent'}))
 elif n['owner']!='continuity_migrator' or n['marker']!=os.environ['H1_SCHEMA_MARKER'] or (os.environ.get('H1_SCHEMA_OID') and str(n['oid'])!=os.environ['H1_SCHEMA_OID']):
  print(json.dumps({'status':'unowned'}))
 else:
  c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(s.schema)))
  if c.execute('SELECT 1 FROM pg_namespace WHERE nspname=%s',(s.schema,)).fetchone() is not None:raise ValueError('Owned namespace survived cleanup')
  print(json.dumps({'status':'removed'}))
"""


class DockerExperiment:
    """One UUID-labelled API/worker deployment, with independent cleanup ownership."""

    def __init__(
        self,
        root: Path,
        stack: Any,
        values: dict[str, str],
        image: str,
        network: str,
        run_id: str,
        index: int,
        experiment: Experiment,
        manifest: WorkloadManifest,
        directory: Path,
        overall: Budget,
    ) -> None:
        from continuity_lab.postgres_settings import PostgresSettings

        self.root, self.stack, self.values, self.image, self.network = (
            root,
            stack,
            values,
            image,
            network,
        )
        self.prefix, self.label_key = owned_prefix(run_id, index), "io.livekit-ecosystem.benchmark"
        self.label_value = self.prefix
        self.schema = f"p1_benchmark_{run_id}_{index}"
        self.experiment, self.manifest, self.directory, self.overall = (
            experiment,
            manifest,
            directory,
            overall,
        )
        self.budget = Budget(experiment.deadline_seconds)
        self.owner = PostgresSettings(
            port=int(values["POSTGRES_PORT"]),
            user="continuity_migrator",
            password=values["POSTGRES_MIGRATION_PASSWORD"],
            schema=self.schema,
        )
        self.runtime = PostgresSettings(
            port=int(values["POSTGRES_PORT"]),
            password=values["POSTGRES_PASSWORD"],
            schema=self.schema,
        )
        self.token = secrets.token_urlsafe(36)
        self.names: list[str] = []
        self.volumes: list[str] = []
        self.serving: list[tuple[str, str, int]] = []
        self._lock = threading.Lock()
        self._commands = 0
        self.abort = threading.Event()
        self.private = tuple(values[key] for key in stack.SECRET_KEYS if values.get(key)) + (
            self.token,
        )
        self.queue: Any = None
        self.base_url = ""
        self._worker_env: Path | None = None
        self.requests: list[Investigation] = []
        self._expected_schema = self.schema
        self._schema_candidate = self._schema_owned = False
        self._schema_oid: int | None = None
        self._schema_marker = (
            "livekit-ecosystem-benchmark:" + self.prefix + ":" + secrets.token_hex(16)
        )
        self._volumes_ready = False
        self.resource_windows: dict[str, dict[str, int | float]] = {}

    def command(
        self,
        argv: Sequence[str],
        *,
        budget: Budget | None = None,
        cap: float = 5,
        environment: Mapping[str, str] | None = None,
        operation: str | None = None,
    ) -> str:
        from harness.process_control import OwnedProcess, ProcessTimeout

        stage = _OPERATION.get() if operation is None else operation
        if stage not in OPERATIONS:
            raise ValueError("Unsupported benchmark operation")
        child: OwnedProcess | None = None
        started = time.monotonic()
        remaining: float | None = None
        try:
            selected = budget or self.budget
            if budget is None and self.abort.is_set():
                raise BenchmarkError("deadline_exceeded")
            remaining = selected.remaining(cap)
            if budget is None:
                remaining = min(remaining, self.overall.remaining(cap))
            with self._lock:
                self._commands += 1
                if self._commands > 4096:
                    raise BenchmarkError("invalid_evidence")
                output = self.directory / f"command-{self._commands}"
            with OwnedProcess(
                list(argv),
                cwd=self.root,
                env=dict(environment)
                if environment is not None
                else self.stack.child_environment(self.values),
                output_directory=output,
                max_output_bytes=262144,
            ) as child:
                if child.wait(timeout=remaining).returncode != 0:
                    raise BenchmarkError("dependency_unavailable")
                raw = (output / "stdout.bin").read_bytes()
                if len(raw) > 131072:
                    raise BenchmarkError("invalid_evidence")
                return raw.decode().strip()
        except Exception as error:
            # OwnedProcess has already closed/reaped before any diagnostic is emitted.
            command = (
                None
                if child is None or remaining is None
                else CommandObservation(
                    exit_code=child.returncode,
                    timed_out=isinstance(error, ProcessTimeout),
                    timeout_seconds=remaining,
                    elapsed_seconds=time.monotonic() - started,
                )
            )
            raise BenchmarkError(failure_code(error), operation=stage, command=command) from error

    @at_operation("configuration")
    def envfile(self, name: str, fields: Mapping[str, str]) -> Path:
        path = self.directory / (name + ".env")
        with os.fdopen(
            os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "w"
        ) as stream:
            stream.write("\n".join(key + "=" + value for key, value in fields.items()) + "\n")
        return path

    def pg_environment(self, *, owner: bool) -> dict[str, str]:
        prefix = "P1_MIGRATION_" if owner else "P1_POSTGRES_"
        return {
            "PATH": os.defpath,
            "LANG": "C.UTF-8",
            "PYTHONUNBUFFERED": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            prefix + "HOST": "127.0.0.1",
            prefix + "PORT": self.values["POSTGRES_PORT"],
            prefix + "DB": "livekit_lab",
            prefix + "USER": "continuity_migrator" if owner else "livekit_lab",
            prefix + "PASSWORD": self.values["POSTGRES_MIGRATION_PASSWORD"]
            if owner
            else self.values["POSTGRES_PASSWORD"],
            prefix + "SCHEMA": self.schema,
            "H1_SCHEMA_MARKER": self._schema_marker,
        }

    @at_operation("schema_prepare")
    def prepare_schema(self) -> None:
        e = self.experiment
        environment = {
            **self.pg_environment(owner=True),
            "H1_SOURCE": str(self.directory / "empty.sqlite3"),
            "H1_POLICY": json.dumps(
                {
                    "maximum_pending": e.pending_limit,
                    "maximum_active": e.active_limit,
                    "maximum_records": e.record_limit,
                    "lease_seconds": e.lease_seconds,
                }
            ),
        }
        self._schema_candidate = True
        result = strict_json(
            self.command(
                [sys.executable, "-c", PG_PREPARE_SCRIPT], cap=180, environment=environment
            ).encode()
        )
        if (
            type(result) is not dict
            or result.get("status") != "ready"
            or type(result.get("oid")) is not int
        ):
            if type(result) is dict and result.get("status") == "refused":
                self._schema_candidate = False
            raise BenchmarkError("missing_setup")
        self._schema_oid = result["oid"]
        self._schema_owned = True

    @at_operation("volume_prepare")
    def prepare_volumes(self) -> None:
        for suffix in ("application", "fixtures"):
            name = self.prefix + "-" + suffix
            if self.command(["docker", "volume", "ls", "-q", "--filter", "name=^" + name + "$"]):
                raise BenchmarkError("missing_setup")
            self.volumes.append(name)
            self.command(
                [
                    "docker",
                    "volume",
                    "create",
                    "--label",
                    self.label_key + "=" + self.label_value,
                    name,
                ]
            )
            label = self.command(
                [
                    "docker",
                    "volume",
                    "inspect",
                    "--format",
                    '{{index .Labels "' + self.label_key + '"}}',
                    name,
                ]
            )
            if label != self.label_value:
                raise BenchmarkError("missing_setup")
        mounts = [
            "--mount",
            f"type=volume,src={self.prefix}-application,dst=/data",
            "--mount",
            f"type=volume,src={self.prefix}-fixtures,dst=/business",
        ]
        for operation in ("bootstrap", "write-access"):
            name = self.prefix + "-" + operation
            self.names.append(name)
            argv = (
                ["chown", "10001:10001", "/data", "/business"]
                if operation == "bootstrap"
                else [
                    "python",
                    "-c",
                    "import os;from pathlib import Path;ps=[Path('/data'),Path('/business')];assert all(p.stat().st_uid==10001 for p in ps);fs=[p/'.benchmark-access' for p in ps];fds=[os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600) for p in fs];[os.close(fd) for fd in fds];[p.unlink() for p in fs];print('writable')",
                ]
            )
            result = self.command(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--name",
                    name,
                    "--label",
                    self.label_key + "=" + self.label_value,
                    "--network",
                    "none",
                    "--user",
                    "0:0" if operation == "bootstrap" else "10001:10001",
                    "--read-only",
                    "--security-opt",
                    "no-new-privileges:true",
                    "--memory",
                    "134217728",
                    "--cpus",
                    "0.5",
                    "--pids-limit",
                    "32",
                    *mounts,
                    self.image,
                    *argv,
                ],
                cap=15,
                operation="volume_bootstrap" if operation == "bootstrap" else "volume_write_access",
            )
            if operation == "write-access" and result != "writable":
                raise BenchmarkError("missing_setup", operation="volume_write_access")
        self._volumes_ready = True

    def container(
        self,
        name: str,
        env: Path,
        argv: Sequence[str],
        *,
        role: str,
        worker_index: int = 0,
        detached: bool = True,
        port: int | None = None,
    ) -> str:
        operation = (
            "fixture_init"
            if not detached
            else ("api_startup" if role == "api" else "worker_startup")
        )
        with operation_scope(operation):
            if not self._volumes_ready:
                raise BenchmarkError("missing_setup")
            limits = (
                self.manifest.api_resources if role == "api" else self.manifest.worker_resources
            )
            self.names.append(name)
            args = [
                "docker",
                "run",
                "-d" if detached else "--rm",
                "--name",
                name,
                "--label",
                self.label_key + "=" + self.label_value,
                "--network",
                self.network,
                "--env-file",
                str(env),
                "--workdir",
                "/tmp",
                "--user",
                "10001:10001",
                "--read-only",
                "--init",
                "--stop-timeout",
                "35",
                "--security-opt",
                "no-new-privileges:true",
                "--cap-drop",
                "ALL",
                "--tmpfs",
                "/tmp:rw,nosuid,noexec,size=64m,mode=1777",
                "--memory",
                str(limits.memory_bytes),
                "--cpus",
                f"{limits.cpu_millicores / 1000:.3f}",
                "--pids-limit",
                str(limits.pids_limit),
            ]
            if role == "api":
                args += [
                    "--mount",
                    f"type=volume,src={self.prefix}-application,dst=/data",
                    "--mount",
                    f"type=volume,src={self.prefix}-fixtures,dst=/business,readonly",
                ]
                if port is not None:
                    args += ["--publish", f"127.0.0.1:{port}:8080"]
            else:
                args += ["--mount", f"type=volume,src={self.prefix}-fixtures,dst=/data"]
            result = self.command([*args, self.image, *argv], cap=15)
            if detached:
                self.serving.append((name, role, worker_index))
                if (
                    self.command(["docker", "inspect", "--format", "{{.Image}}", name])
                    != self.image
                ):
                    raise BenchmarkError("missing_setup")
                configured = strict_json(
                    self.command(
                        ["docker", "inspect", "--format", "{{json .HostConfig}}", name]
                    ).encode(),
                    131072,
                )
                if type(configured) is not dict or (
                    configured.get("Memory"),
                    configured.get("NanoCpus"),
                    configured.get("PidsLimit"),
                ) != (limits.memory_bytes, limits.cpu_millicores * 1000000, limits.pids_limit):
                    raise BenchmarkError("resource_mismatch")
            return result

    @at_operation("fixture_init")
    def prepare(self) -> None:
        self.prepare_schema()
        self.prepare_volumes()
        pg = {
            "P1_POSTGRES_HOST": "postgres",
            "P1_POSTGRES_PORT": "5432",
            "P1_POSTGRES_DB": "livekit_lab",
            "P1_POSTGRES_USER": "livekit_lab",
            "P1_POSTGRES_PASSWORD": self.values["POSTGRES_PASSWORD"],
            "P1_POSTGRES_SCHEMA": self.schema,
            "P1_WORKER_SCOPE": SCOPE,
        }
        self._worker_env = self.envfile(
            "worker",
            {
                **pg,
                "P1_WORKER_SUPPLIER_DB": "/data/supplier.sqlite3",
                "P1_WORKER_SINK_DB": "/data/completion.sqlite3",
                "P1_WORKER_POLL_SECONDS": "1",
                "P1_WORKER_STATE_FILE": "/tmp/benchmark-worker.json",
            },
        )
        initialized = strict_json(
            self.container(
                self.prefix + "-init",
                self._worker_env,
                ["python", "-m", "continuity_lab.worker_cli", "init-fixtures"],
                role="worker",
                detached=False,
            ).encode()
        )
        if type(initialized) is not dict or initialized.get("status") != "fixtures_ready":
            raise BenchmarkError("missing_setup")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        api_env = self.envfile(
            "api",
            {
                **pg,
                "LOCAL_ACCESS_TOKEN": self.token,
                "POSTGRES_PASSWORD": self.values["POSTGRES_PASSWORD"],
                "LIVEKIT_URL": "ws://livekit:7880",
                "LIVEKIT_PUBLIC_URL": "ws://127.0.0.1:" + self.values["LIVEKIT_HTTP_PORT"],
                "LIVEKIT_API_KEY": self.values["LIVEKIT_API_KEY"],
                "LIVEKIT_API_SECRET": self.values["LIVEKIT_API_SECRET"],
                "P1_BUSINESS_ENABLED": "1",
                "P1_BUSINESS_SUPPLIER_DB": "/business/supplier.sqlite3",
                "INTAKE_DATABASE": "/data/intake.sqlite3",
            },
        )
        self.container(
            self.prefix + "-api",
            api_env,
            [
                "uvicorn",
                "services.control_api.app:app",
                "--host",
                "0.0.0.0",
                "--port",
                "8080",
                "--workers",
                "1",
                "--limit-concurrency",
                "32",
                "--no-access-log",
            ],
            role="api",
            port=port,
        )
        self.base_url = f"http://127.0.0.1:{port}"

    @at_operation("worker_startup")
    def start_workers(self) -> None:
        if self._worker_env is None:
            raise BenchmarkError("missing_setup")
        for index in range(1, self.experiment.worker_count + 1):
            self.container(
                f"{self.prefix}-worker-{index}",
                self._worker_env,
                ["python", "-m", "continuity_lab.worker_cli", "run"],
                role="worker",
                worker_index=index,
            )

    @at_operation("sampling")
    def sample(
        self, evidence: EvidenceLog, counts: dict[str, int], previous_cpu: dict[str, int]
    ) -> None:
        for name, role, index in tuple(self.serving):
            probe_started = self.budget.elapsed()
            value = strict_json(
                self.command(["docker", "exec", name, "python", "-c", CGROUP_SCRIPT]).encode()
            )
            observation = CgroupObservation.parse(
                value,
                self.manifest.api_resources if role == "api" else self.manifest.worker_resources,
            )
            probe_finished = self.budget.elapsed()
            if observation.cpu_usage_usec < previous_cpu.get(name, 0):
                raise BenchmarkError("resource_mismatch")
            previous_cpu[name] = observation.cpu_usage_usec
            counts[name] = counts.get(name, 0) + 1
            window = self.resource_windows.setdefault(
                name,
                {
                    "baseline_cpu_usage_usec": observation.cpu_usage_usec,
                    "baseline_observed_seconds": probe_finished,
                },
            )
            window.update(
                {
                    "last_cpu_usage_usec": observation.cpu_usage_usec,
                    "last_observed_seconds": probe_finished,
                    "cpu_usage_delta_usec": observation.cpu_usage_usec
                    - window["baseline_cpu_usage_usec"],
                    "observed_window_seconds": probe_finished - window["baseline_observed_seconds"],
                }
            )
            evidence.record(
                self.experiment.name,
                "resource",
                self.budget.elapsed(),
                role=role,
                worker_index=index,
                probe_started_seconds=probe_started,
                probe_finished_seconds=probe_finished,
                probe_duration_seconds=probe_finished - probe_started,
                **asdict(observation),
            )
        snapshot = strict_json(
            self.command(
                [sys.executable, "-c", PG_READ_SCRIPT],
                environment={**self.pg_environment(owner=False), "H1_READ": "queue"},
            ).encode()
        )
        if type(snapshot) is not dict or set(snapshot) != EvidenceLog.FIELDS["queue"]:
            raise BenchmarkError("invalid_evidence")
        if (
            snapshot["active"] > min(self.experiment.worker_count, self.experiment.active_limit)
            or snapshot["outstanding"] > self.experiment.pending_limit
            or (snapshot["maximum_pending"], snapshot["maximum_active"])
            != (self.experiment.pending_limit, self.experiment.active_limit)
        ):
            raise BenchmarkError("capacity_mismatch")
        evidence.record(self.experiment.name, "queue", self.budget.elapsed(), **snapshot)

    @at_operation("reconciliation")
    def authority(self) -> object:
        worker = next(name for name, role, _ in self.serving if role == "worker")
        return strict_json(
            self.command(["docker", "exec", worker, "python", "-c", AUTHORITY_SCRIPT]).encode(),
            131072,
        )

    @at_operation("reconciliation")
    def accepted_rows(self) -> object:
        return strict_json(
            self.command(
                [sys.executable, "-c", PG_READ_SCRIPT],
                environment={**self.pg_environment(owner=False), "H1_READ": "rows"},
            ).encode(),
            131072,
        )

    @at_operation("provenance")
    def provenance(self) -> dict[str, object]:
        packages = {
            "continuity_lab": self.root / "projects/agent-continuity/python/src/continuity_lab",
            "services/control_api": self.root / "services/control_api",
        }
        if any(not (source / "__init__.py").is_file() for source in packages.values()):
            raise BenchmarkError("missing_setup")
        expected = {
            package + "/" + path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for package, source in packages.items()
            for path in source.glob("*.py")
        }
        script = "import continuity_lab,services.control_api,json,hashlib,platform,importlib.metadata; from pathlib import Path; roots={'continuity_lab':Path(continuity_lab.__file__).parent,'services/control_api':Path(services.control_api.__file__).parent}; print(json.dumps({'roots':{k:str(v) for k,v in roots.items()},'hashes':{k+'/'+p.name:hashlib.sha256(p.read_bytes()).hexdigest() for k,v in roots.items() for p in v.glob('*.py')},'versions':{'python':platform.python_version(),'architecture':platform.machine(),**{n:importlib.metadata.version(n) for n in ('psycopg','httpx')}}}))"
        observed = strict_json(
            self.command(["docker", "exec", self.prefix + "-api", "python", "-c", script]).encode(),
            131072,
        )
        if (
            type(observed) is not dict
            or observed.get("hashes") != expected
            or type(observed.get("roots")) is not dict
            or any("site-packages" not in Path(path).parts for path in observed["roots"].values())
        ):
            raise BenchmarkError("missing_setup")
        return {
            "module_hashes": expected,
            "installed_roots": observed["roots"],
            "versions": observed["versions"],
        }

    @at_operation("cleanup")
    def cleanup(self) -> None:
        cleanup = Budget(self.manifest.cleanup_deadline_seconds)
        failures: list[BenchmarkError] = []
        for name in reversed(self.names):
            try:
                found = self.command(
                    ["docker", "ps", "-aq", "--filter", "name=^/" + name + "$"], budget=cleanup
                )
                if not found:
                    continue
                label = self.command(
                    [
                        "docker",
                        "inspect",
                        "--format",
                        '{{index .Config.Labels "' + self.label_key + '"}}',
                        name,
                    ],
                    budget=cleanup,
                )
                if label != self.label_value or not name.startswith(self.prefix + "-"):
                    raise BenchmarkError("cleanup_failed")
                self.command(["docker", "stop", "--time", "35", name], budget=cleanup, cap=40)
                self.command(["docker", "rm", "-f", name], budget=cleanup)
                if self.command(
                    ["docker", "ps", "-aq", "--filter", "name=^/" + name + "$"], budget=cleanup
                ):
                    raise BenchmarkError("cleanup_failed")
            except Exception as error:  # noqa: BLE001 - independent owned cleanup must continue
                failures.append(contextual_error(error, "cleanup"))
        for name in self.volumes:
            try:
                if not self.command(
                    ["docker", "volume", "ls", "-q", "--filter", "name=^" + name + "$"],
                    budget=cleanup,
                ):
                    continue
                label = self.command(
                    [
                        "docker",
                        "volume",
                        "inspect",
                        "--format",
                        '{{index .Labels "' + self.label_key + '"}}',
                        name,
                    ],
                    budget=cleanup,
                )
                if label != self.label_value or name not in {
                    self.prefix + "-application",
                    self.prefix + "-fixtures",
                }:
                    raise BenchmarkError("cleanup_failed")
                self.command(["docker", "volume", "rm", name], budget=cleanup)
                if self.command(
                    ["docker", "volume", "ls", "-q", "--filter", "name=^" + name + "$"],
                    budget=cleanup,
                ):
                    raise BenchmarkError("cleanup_failed")
            except Exception as error:  # noqa: BLE001 - independent owned cleanup must continue
                failures.append(contextual_error(error, "cleanup"))
        try:
            if self._schema_candidate:
                if self.schema != self._expected_schema:
                    raise BenchmarkError("cleanup_failed")
                environment = {
                    **self.pg_environment(owner=True),
                    "H1_SCHEMA_OID": str(self._schema_oid) if self._schema_oid is not None else "",
                }
                result = strict_json(
                    self.command(
                        [sys.executable, "-c", PG_CLEANUP_SCRIPT],
                        budget=cleanup,
                        environment=environment,
                    ).encode()
                )
                if type(result) is not dict or result.get("status") not in {"absent", "removed"}:
                    raise BenchmarkError("cleanup_failed")
                self._schema_owned = False
                self._schema_candidate = False
        except Exception as error:  # noqa: BLE001 - independently reconcile the owned namespace
            failures.append(contextual_error(error, "cleanup"))
        if failures:
            raise BenchmarkError("cleanup_failed", operation="cleanup", command=failures[0].command)


@at_async_operation("api_readiness")
async def wait_ready(lab: DockerExperiment, driver: HTTPDriver, *, workers: bool) -> None:
    while True:
        waiting = "api_readiness"
        if await driver.healthy():
            if not workers:
                return
            waiting = "worker_readiness"
            with operation_scope(waiting):
                script = "import json;from pathlib import Path;from continuity_lab.worker_cli import WorkerHealth;print(json.dumps({'ready':WorkerHealth(Path('/tmp/benchmark-worker.json')).ready()}))"
                healthy = True
                for name, role, _index in lab.serving:
                    if role == "worker":
                        value = strict_json(
                            (
                                await asyncio.to_thread(
                                    lab.command,
                                    ["docker", "exec", name, "python", "-c", script],
                                    operation="worker_readiness",
                                )
                            ).encode()
                        )
                        healthy = healthy and type(value) is dict and value.get("ready") is True
                if healthy:
                    return
        with operation_scope(waiting):
            await asyncio.sleep(min(0.1, lab.budget.remaining(), lab.overall.remaining()))


@at_async_operation("inspection")
async def observe_results(
    driver: HTTPDriver,
    inquiries: Sequence[Investigation],
    offered: asyncio.Event,
    interval_seconds: float,
) -> None:
    cursor = 0
    while True:
        pending = [
            item for item in inquiries if item.task_id is not None and item.result_at is None
        ]
        if not pending and offered.is_set():
            return
        if pending:
            item = pending[cursor % len(pending)]
            cursor += 1
            current = await driver.get(item)
            state = current["inquiry"]["state"]
            if state == "failed":
                raise BenchmarkError("reconciliation_failed")
        await asyncio.sleep(
            min(interval_seconds, driver.budget.remaining(), driver.overall.remaining())
        )


@at_async_operation("reconciliation")
async def run_experiment(lab: DockerExperiment, evidence: EvidenceLog) -> dict[str, object]:
    driver = HTTPDriver(
        lab.base_url,
        lab.token,
        lab.budget,
        lab.overall,
        evidence,
        lab.experiment,
        lab.manifest.http_timeout_seconds,
    )
    stop, offered = asyncio.Event(), asyncio.Event()
    counts: dict[str, int] = {}
    previous_cpu: dict[str, int] = {}
    monitor: asyncio.Task[None] | None = None
    observer: asyncio.Task[None] | None = None

    async def sample_loop() -> None:
        next_sample = time.monotonic()
        while not stop.is_set():
            cycle_started = time.monotonic()
            await asyncio.to_thread(lab.sample, evidence, counts, previous_cpu)
            next_sample += lab.manifest.sample_interval_seconds
            cycle_finished = time.monotonic()
            next_sample, skipped = next_resource_tick(
                next_sample, cycle_finished, lab.manifest.sample_interval_seconds
            )
            evidence.record(
                lab.experiment.name,
                "observer",
                lab.budget.elapsed(),
                duration_seconds=cycle_finished - cycle_started,
                skipped_intervals=skipped,
            )
            remaining = next_sample - time.monotonic()
            try:
                await asyncio.wait_for(stop.wait(), timeout=remaining)
            except TimeoutError:
                pass

    e = lab.experiment
    rng = random.Random(lab.manifest.seed)
    inquiries = [
        Investigation(
            index,
            str(uuid5(UUID(lab.prefix[5:37]), f"{lab.manifest.seed}:{e.name}:{index}")),
            {
                "booking_reference": "DEMO-BK-001",
                "new_check_in": f"2030-12-{rng.randrange(2, 29):02}",
                "confirmed": True,
            },
        )
        for index in range(e.request_count)
    ]
    lab.requests = inquiries
    try:
        await wait_ready(lab, driver, workers=False)
        provenance = await asyncio.to_thread(lab.provenance)
        if not e.workers_start_after_submissions:
            await asyncio.to_thread(lab.start_workers)
            await wait_ready(lab, driver, workers=True)
        monitor = asyncio.create_task(sample_loop(), name="bounded-workload-resource-observer")
        scheduled = time.monotonic()
        for item in inquiries:
            item.scheduled_offer_at = scheduled + item.index * e.arrival_interval_ms / 1000

        async def offer(item: Investigation, *, reject: bool = False) -> None:
            assert item.scheduled_offer_at is not None
            delay = item.scheduled_offer_at - time.monotonic()
            if delay > 0:
                await asyncio.sleep(min(delay, lab.budget.remaining(), lab.overall.remaining()))
            await driver.submit(item, reject=reject)

        if e.workers_start_after_submissions:
            async with asyncio.TaskGroup() as group:
                for item in inquiries[: e.accepted_count]:
                    group.create_task(offer(item))
            # Every original key remains replayable and inspectable at capacity.
            async with asyncio.TaskGroup() as group:
                for item in inquiries[: e.accepted_count]:
                    group.create_task(driver.submit(item, replay=True))
                    group.create_task(driver.get(item))
            async with asyncio.TaskGroup() as group:
                for item in inquiries[e.accepted_count :]:
                    group.create_task(offer(item, reject=True))
            await asyncio.to_thread(lab.start_workers)
            await wait_ready(lab, driver, workers=True)
            offered.set()
            await observe_results(
                driver, inquiries, offered, lab.manifest.observation_interval_ms / 1000
            )
        else:
            observer = asyncio.create_task(
                observe_results(
                    driver, inquiries, offered, lab.manifest.observation_interval_ms / 1000
                ),
                name="bounded-round-robin-result-observer",
            )
            async with asyncio.TaskGroup() as group:
                for item in inquiries:
                    group.create_task(offer(item))
            offered.set()
            await observer
        accepted = [item for item in inquiries if item.task_id is not None]
        if len(accepted) != e.accepted_count:
            raise BenchmarkError("capacity_mismatch")
        # Result measurements finish before these explicit controller cancellations.
        result_latencies, queue_delays, ack_latencies = [], [], []
        for item in accepted:
            if (
                item.result_at is None
                or item.submitted_at is None
                or item.acknowledged_at is None
                or item.scheduled_offer_at is None
            ):
                raise BenchmarkError("reconciliation_failed")
            result_latencies.append(item.result_at - item.scheduled_offer_at)
            queue_delays.append(max(0, item.submitted_at - item.scheduled_offer_at))
            ack_latencies.append(item.acknowledged_at - item.submitted_at)
        async with asyncio.TaskGroup() as group:
            for item in accepted:
                group.create_task(driver.submit(item, replay=True))
                group.create_task(driver.cancel(item))
        pending = list(accepted)
        while pending:
            item = pending.pop(0)
            current = await driver.get(item)
            if current.get("outcome", {}).get("state") != "cancelled":
                raise BenchmarkError("reconciliation_failed")
            delivery = current.get("delivery")
            if type(delivery) is not dict or delivery.get("state") == "exhausted":
                raise BenchmarkError("reconciliation_failed")
            if delivery.get("state") != "delivered":
                pending.append(item)
            await asyncio.sleep(
                min(
                    lab.manifest.observation_interval_ms / 1000,
                    lab.budget.remaining(),
                    lab.overall.remaining(),
                )
            )
        rows = await asyncio.to_thread(lab.accepted_rows)
        truth = await asyncio.to_thread(lab.authority)
        outcome = reconcile(inquiries, rows, truth, e.accepted_count, e.rejected_count)
        stop.set()
        await monitor
        monitor = None
        await asyncio.to_thread(lab.sample, evidence, counts, previous_cpu)
        if any(counts.get(name, 0) < 2 for name, _role, _index in lab.serving):
            raise BenchmarkError("invalid_evidence")
        lab.budget.remaining()
        lab.overall.remaining()
        return {
            "experiment": e.name,
            "status": "passed",
            "outcomes": outcome,
            "scheduled_offer_to_observed_inquiry": timing_summary(result_latencies),
            "offer_queue_delay": timing_summary(queue_delays),
            "first_http_start_to_known_acknowledgement": timing_summary(ack_latencies),
            "observation_interval_ms": lab.manifest.observation_interval_ms,
            "polling_lag_included": True,
            "observation_policy": "one_global_round_robin_get_then_interval_sleep_shared_with_all_http",
            "cohort_sweep_includes_http_and_queue_delay": True,
            "first_result_observation_includes_submit_replay_and_get": True,
            "accounted_memory_not_rss": True,
            "resource_probe": "sequential_docker_exec_python_cgroup_v2",
            "resource_probe_cpu_memory_pids_included": True,
            "resource_window_includes_post_measurement_cancellation_and_delivery": True,
            "resource_target_interval_seconds": lab.manifest.sample_interval_seconds,
            "resource_cpu_windows": {
                role + "-" + str(index): lab.resource_windows[name]
                for name, role, index in lab.serving
            },
            "resource_samples": {
                role + "-" + str(index): counts[name] for name, role, index in lab.serving
            },
            "provenance": provenance,
            "elapsed_seconds": lab.budget.elapsed(),
            "requests": [
                {
                    "index": item.index,
                    "task_id": item.task_id,
                    "case_id": item.case_id,
                    "inquiry_effect_id": item.effect_id,
                    "request_key_sha256": hashlib.sha256(item.key.encode()).hexdigest(),
                    "request_sha256": hashlib.sha256(canonical(item.request)).hexdigest(),
                    "scheduled_offer_seconds": item.scheduled_offer_at - lab.budget.started
                    if item.scheduled_offer_at is not None
                    else None,
                    "actual_http_start_seconds": item.submitted_at - lab.budget.started
                    if item.submitted_at is not None
                    else None,
                    "acknowledgement_seconds": item.acknowledged_at - lab.budget.started
                    if item.acknowledged_at is not None
                    else None,
                    "first_observed_succeeded_seconds": item.result_at - lab.budget.started
                    if item.result_at is not None
                    else None,
                    "first_result_observation_source": item.result_source,
                    "rejected": item.rejected,
                    "cancelled_after_measurement": item.cancelled,
                }
                for item in inquiries
            ],
        }
    finally:
        original = sys.exc_info()[0] is not None
        lab.abort.set()
        offered.set()
        stop.set()
        if observer is not None and not observer.done():
            observer.cancel()
        if observer is not None:
            await asyncio.gather(observer, return_exceptions=True)
        try:
            if monitor is not None:
                await monitor
        except Exception:
            if not original:
                raise
        finally:
            await driver.client.aclose()


def main(argv: Sequence[str] | None = None) -> int:
    from harness.workload_models import (
        canonical_manifest_bytes,
        load_workload_manifest,
        manifest_digest,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", type=Path, default=ROOT / "harness/workloads/p1-inquiry-v1.json"
    )
    parser.add_argument(
        "--run", action="store_true", help="Explicitly run the isolated local workloads"
    )
    arguments = parser.parse_args(argv)
    manifest = load_workload_manifest(arguments.manifest)
    digest = manifest_digest(manifest)
    if not arguments.run:
        print(
            json.dumps(
                {
                    "status": "not_started",
                    "manifest_sha256": digest,
                    "experiments": [item.name for item in manifest.experiments],
                }
            )
        )
        return 0
    spec = importlib.util.spec_from_file_location(
        "p1_benchmark_stack", ROOT / "local-setup/stack.py"
    )
    if spec is None or spec.loader is None:
        raise BenchmarkError("missing_setup")
    stack = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stack)
    values = stack.load_settings(ROOT / "local-setup")
    stack.assert_owned_containers(ROOT / "local-setup", values)
    overall = Budget(manifest.overall_deadline_seconds)

    def control(args: list[str]) -> str:
        value = stack.run(args, values, ROOT / "local-setup", min(5, overall.remaining()))
        if type(value) is not str:
            raise BenchmarkError("invalid_evidence")
        return value.strip()

    image = control(
        [
            "docker",
            "image",
            "inspect",
            "--format",
            "{{.Id}}",
            "livekit-agent-ecosystem-python:local",
        ]
    )
    network = stack.PROJECT + "_lab"
    api = control(stack.compose_arguments(ROOT / "local-setup") + ["ps", "-q", "control-api"])
    networks = strict_json(
        control(
            ["docker", "inspect", "--format", "{{json .NetworkSettings.Networks}}", api]
        ).encode()
    )
    if (
        re.fullmatch(r"sha256:[0-9a-f]{64}", image) is None
        or type(networks) is not dict
        or network not in networks
    ):
        raise BenchmarkError("missing_setup")
    run_id = uuid4().hex
    report = ROOT / ".local/validation/p1-phase-h" / run_id
    report.mkdir(mode=0o700, parents=True, exist_ok=False)
    (report / "workload.json").write_bytes(canonical_manifest_bytes(manifest))
    evidence = EvidenceLog(report / "samples.jsonl", manifest.maximum_samples)
    summaries: list[dict[str, object]] = []
    status, error_code = "failed", None
    cleanup_errors: list[str] = []
    cleanup_observations: list[dict[str, object]] = []
    failure_context: dict[str, object] | None = None
    active_lab: DockerExperiment | None = None
    try:
        with tempfile.TemporaryDirectory(
            prefix="p1-h-" + run_id + "-", dir=ROOT / ".local"
        ) as temporary:
            for index, experiment in enumerate(manifest.experiments):
                directory = Path(temporary) / experiment.name
                directory.mkdir(mode=0o700)
                lab = DockerExperiment(
                    ROOT,
                    stack,
                    values,
                    image,
                    network,
                    run_id,
                    index,
                    experiment,
                    manifest,
                    directory,
                    overall,
                )
                active_lab = lab
                original = False
                try:
                    # Preparation is host tooling, not a conversation loop; keeping
                    # it here lets signals interrupt/reap the owned migration child.
                    lab.prepare()
                    summary = asyncio.run(run_experiment(lab, evidence))
                    (report / (experiment.name + ".measurement.json")).write_text(
                        json.dumps(
                            {
                                **summary,
                                "status": "measured",
                                "cleanup_verified": False,
                                "phase_status": "not_established",
                            },
                            indent=2,
                            allow_nan=False,
                        )
                        + "\n"
                    )
                except BaseException as error:
                    original = True
                    failure_context = retain_failure_context(report, experiment.name, error)
                    raise
                finally:
                    try:
                        lab.cleanup()
                    except Exception as error:
                        cleanup_context = retain_failure_context(
                            report, experiment.name, error, cleanup=True
                        )
                        cleanup_observations.append(
                            {"experiment": experiment.name, **cleanup_context}
                        )
                        if not original:
                            failure_context = cleanup_context
                            raise
                        cleanup_errors.append(experiment.name)
                overall.remaining()
                summaries.append({**summary, "cleanup_verified": True})
                (report / (experiment.name + ".json")).write_text(
                    json.dumps(summaries[-1], indent=2, allow_nan=False) + "\n"
                )
        overall.remaining()
        status = "passed"
    except Exception as error:  # noqa: BLE001 - outer boundary emits only a fixed safe code
        error_code = failure_code(error)
        if failure_context is None:
            failure_context = failure_observation(error)
    finally:
        evidence.close()
    result = {
        "schema_version": 1,
        "status": status,
        "mode": "local_infrastructure_inquiry",
        "manifest_sha256": digest,
        "seed": manifest.seed,
        "runtime_image_id": image,
        "host": {
            "system": platform.system(),
            "architecture": platform.machine(),
            "python": platform.python_version(),
        },
        "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "samples": evidence.count,
        "elapsed_seconds": overall.elapsed(),
        "experiments": summaries,
        "failure_code": error_code,
        "cleanup_failures": cleanup_errors,
        "cleanup_failure_observations": cleanup_observations,
        "failed_experiment": None
        if status == "passed" or active_lab is None
        else {
            "name": active_lab.experiment.name,
            "failure": failure_context,
            "known_accepted": sum(item.task_id is not None for item in active_lab.requests),
            "explicitly_rejected": sum(item.rejected for item in active_lab.requests),
            "http_started_without_known_acknowledgement": sum(
                item.submitted_at is not None and item.task_id is None and not item.rejected
                for item in active_lab.requests
            ),
            "observed_inquiry_results": sum(
                item.result_at is not None for item in active_lab.requests
            ),
            "cancelled_after_measurement": sum(item.cancelled for item in active_lab.requests),
            "request_records": len(active_lab.requests),
            "scheduled_request_count": active_lab.experiment.request_count,
        },
        "release_gate": "incomplete",
        "media_or_model_measurements": False,
    }
    (report / "summary.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(
        json.dumps(
            {
                "status": status,
                "manifest_sha256": digest,
                "experiments_passed": len(summaries),
                "failure_code": error_code,
                "report": str(report),
            }
        )
    )
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
