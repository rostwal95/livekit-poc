"""Immutable, dependency-free contracts for bounded P1 inquiry workload manifests.

A manifest declares an experiment, not a measurement result. Its canonical digest
binds later evidence to the reviewed schedules and budgets. Resource memory limits
and runner memory samples describe cgroup-accounted bytes, never process RSS.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, cast

MAX_MANIFEST_BYTES = 32768
MAX_JSON_DEPTH = 8
MAX_REQUESTS = 32
MAX_RAW_SAMPLES = 4096
WorkloadKind = Literal["steady", "burst", "saturation"]


class WorkloadValidationError(ValueError):
    """A fixed safe diagnostic; untrusted manifest fields are never echoed."""


def _integer(value: object, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise WorkloadValidationError("Workload integer is outside its declared safe bounds")
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise WorkloadValidationError("Workload boolean must be explicit")
    return value


def _kind(value: object) -> WorkloadKind:
    if type(value) is not str or value not in {"steady", "burst", "saturation"}:
        raise WorkloadValidationError("Unsupported workload experiment kind")
    return cast(WorkloadKind, value)


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    """Per-container declared caps; CPU millicores, accounted bytes and cgroup tasks."""

    cpu_millicores: int
    memory_bytes: int
    pids_limit: int

    def __post_init__(self) -> None:
        _integer(self.cpu_millicores, 100, 4000)
        _integer(self.memory_bytes, 64 * 1024 * 1024, 1024 * 1024 * 1024)
        _integer(self.pids_limit, 16, 256)


@dataclass(frozen=True, slots=True)
class Experiment:
    """One schedule; one client limit covers admissions, reads, replays and cancellation.

    Observers share that limit; they must not create an extra HTTP request pool.
    """

    name: str
    kind: WorkloadKind
    worker_count: int
    request_count: int
    accepted_count: int
    rejected_count: int
    arrival_interval_ms: int
    client_concurrency: int
    deadline_seconds: int
    pending_limit: int
    active_limit: int
    record_limit: int
    lease_seconds: int
    workers_start_after_submissions: bool

    def __post_init__(self) -> None:
        kind = _kind(self.kind)
        _integer(self.worker_count, 1, 2)
        if type(self.name) is not str or self.name != f"{kind}-w{self.worker_count}":
            raise WorkloadValidationError("Experiment name must match its bounded kind and mode")
        _integer(self.request_count, 1, MAX_REQUESTS)
        _integer(self.accepted_count, 1, MAX_REQUESTS)
        _integer(self.rejected_count, 0, MAX_REQUESTS)
        if self.accepted_count + self.rejected_count != self.request_count:
            raise WorkloadValidationError("Experiment acceptance counts do not cover its requests")
        _integer(self.arrival_interval_ms, 0, 1000)
        _integer(self.client_concurrency, 1, 4)
        _integer(self.deadline_seconds, 1, 180)
        _integer(self.pending_limit, 1, 64)
        _integer(self.active_limit, 1, 4)
        _integer(self.record_limit, 1, 1000)
        _integer(self.lease_seconds, 30, 30)
        _boolean(self.workers_start_after_submissions)
        if self.active_limit > self.pending_limit or self.pending_limit > self.record_limit:
            raise WorkloadValidationError("Experiment capacity limits are inconsistent")
        if (self.request_count - 1) * self.arrival_interval_ms >= self.deadline_seconds * 1000:
            raise WorkloadValidationError("The arrival schedule cannot fit its experiment deadline")
        if kind == "steady" and self.arrival_interval_ms == 0:
            raise WorkloadValidationError("A steady workload requires a positive arrival interval")
        if kind != "steady" and self.arrival_interval_ms != 0:
            raise WorkloadValidationError("A burst workload cannot declare spaced arrivals")
        if kind == "saturation":
            if (
                not self.workers_start_after_submissions
                or self.accepted_count != self.pending_limit
                or self.rejected_count == 0
                or self.active_limit != 1
            ):
                raise WorkloadValidationError(
                    "Saturation must prove bounded admission before workers"
                )
        elif self.workers_start_after_submissions or self.rejected_count != 0:
            raise WorkloadValidationError(
                "Normal workloads require live workers and successful admission"
            )


@dataclass(frozen=True, slots=True)
class WorkloadManifest:
    """Cgroup sampling and case polling have separate declared cadences.

    Result latency is observed, including polling lag; raw scheduled offers,
    HTTP starts/acknowledgements and result-observation times belong in evidence.
    """

    schema_version: int
    workload_id: str
    seed: int
    overall_deadline_seconds: int
    cleanup_deadline_seconds: int
    sample_interval_seconds: int
    observation_interval_ms: int
    http_timeout_seconds: int
    maximum_samples: int
    api_resources: ResourceLimits
    worker_resources: ResourceLimits
    experiments: tuple[Experiment, ...]

    def __post_init__(self) -> None:
        _integer(self.schema_version, 1, 1)
        if type(self.workload_id) is not str or self.workload_id != "p1-inquiry-v1":
            raise WorkloadValidationError("Unsupported versioned workload identity")
        _integer(self.seed, 0, 4294967295)
        _integer(self.overall_deadline_seconds, 1, 600)
        _integer(self.cleanup_deadline_seconds, 1, 90)
        _integer(self.sample_interval_seconds, 1, 1)
        _integer(self.observation_interval_ms, 250, 1000)
        _integer(self.http_timeout_seconds, 1, 5)
        _integer(self.maximum_samples, 1, MAX_RAW_SAMPLES)
        if (
            type(self.api_resources) is not ResourceLimits
            or type(self.worker_resources) is not ResourceLimits
        ):
            raise WorkloadValidationError(
                "Explicit typed API and worker resource limits are required"
            )
        if type(self.experiments) is not tuple or len(self.experiments) != 6:
            raise WorkloadValidationError("Exactly six workload experiments are required")
        if any(type(experiment) is not Experiment for experiment in self.experiments):
            raise WorkloadValidationError("Experiments must use the immutable workload contract")
        expected = {
            (kind, workers) for kind in ("steady", "burst", "saturation") for workers in (1, 2)
        }
        observed = {(experiment.kind, experiment.worker_count) for experiment in self.experiments}
        if observed != expected:
            raise WorkloadValidationError(
                "Each workload kind requires both worker-count modes once"
            )
        if any(
            experiment.deadline_seconds > self.overall_deadline_seconds
            for experiment in self.experiments
        ):
            raise WorkloadValidationError(
                "An experiment cannot exceed the overall workload deadline"
            )


def _object(value: object, fields: frozenset[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != fields:
        raise WorkloadValidationError("Workload object has missing or unsupported fields")
    return cast(dict[str, object], value)


def _resource(value: object) -> ResourceLimits:
    data = _object(value, frozenset({"cpu_millicores", "memory_bytes", "pids_limit"}))
    return ResourceLimits(
        cpu_millicores=_integer(data["cpu_millicores"], 100, 4000),
        memory_bytes=_integer(data["memory_bytes"], 64 * 1024 * 1024, 1024 * 1024 * 1024),
        pids_limit=_integer(data["pids_limit"], 16, 256),
    )


def _experiment(value: object) -> Experiment:
    fields = frozenset(Experiment.__dataclass_fields__)
    data = _object(value, fields)
    name = data["name"]
    if type(name) is not str or re.fullmatch(r"(?:steady|burst|saturation)-w[12]", name) is None:
        raise WorkloadValidationError("Experiment identity is invalid")
    return Experiment(
        name=name,
        kind=_kind(data["kind"]),
        worker_count=_integer(data["worker_count"], 1, 2),
        request_count=_integer(data["request_count"], 1, MAX_REQUESTS),
        accepted_count=_integer(data["accepted_count"], 1, MAX_REQUESTS),
        rejected_count=_integer(data["rejected_count"], 0, MAX_REQUESTS),
        arrival_interval_ms=_integer(data["arrival_interval_ms"], 0, 1000),
        client_concurrency=_integer(data["client_concurrency"], 1, 4),
        deadline_seconds=_integer(data["deadline_seconds"], 1, 180),
        pending_limit=_integer(data["pending_limit"], 1, 64),
        active_limit=_integer(data["active_limit"], 1, 4),
        record_limit=_integer(data["record_limit"], 1, 1000),
        lease_seconds=_integer(data["lease_seconds"], 30, 30),
        workers_start_after_submissions=_boolean(data["workers_start_after_submissions"]),
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    data: dict[str, object] = {}
    for key, value in pairs:
        if key in data:
            raise WorkloadValidationError("Duplicate workload field")
        data[key] = value
    return data


def _parse_integer(value: str) -> int:
    if len(value) > 12:
        raise WorkloadValidationError("Workload integer representation is too large")
    return int(value)


def _deny_noninteger(_value: str) -> object:
    raise WorkloadValidationError("Workload JSON numbers must be finite integers")


def _check_depth(text: str) -> None:
    depth = 0
    quoted, escaped = False, False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise WorkloadValidationError("Workload JSON nesting exceeds its bound")
        elif char in "]}":
            depth -= 1


def parse_workload_manifest(raw: bytes) -> WorkloadManifest:
    """Parse one bounded UTF-8 JSON document; duplicate/unknown fields fail closed."""
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_MANIFEST_BYTES:
        raise WorkloadValidationError("Workload manifest exceeds its byte bound")
    try:
        text = raw.decode("utf-8")
        _check_depth(text)
        value: object = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_int=_parse_integer,
            parse_float=_deny_noninteger,
            parse_constant=_deny_noninteger,
        )
    except WorkloadValidationError:
        raise
    except (UnicodeError, ValueError, TypeError, RecursionError):
        raise WorkloadValidationError("Invalid workload JSON") from None
    data = _object(value, frozenset(WorkloadManifest.__dataclass_fields__))
    workload_id, experiments = data["workload_id"], data["experiments"]
    if type(workload_id) is not str:
        raise WorkloadValidationError("Workload identity must be explicit")
    if type(experiments) is not list or len(experiments) != 6:
        raise WorkloadValidationError("Exactly six workload experiments are required")
    values = cast(list[object], experiments)
    return WorkloadManifest(
        schema_version=_integer(data["schema_version"], 1, 1),
        workload_id=workload_id,
        seed=_integer(data["seed"], 0, 4294967295),
        overall_deadline_seconds=_integer(data["overall_deadline_seconds"], 1, 600),
        cleanup_deadline_seconds=_integer(data["cleanup_deadline_seconds"], 1, 90),
        sample_interval_seconds=_integer(data["sample_interval_seconds"], 1, 1),
        observation_interval_ms=_integer(data["observation_interval_ms"], 250, 1000),
        http_timeout_seconds=_integer(data["http_timeout_seconds"], 1, 5),
        maximum_samples=_integer(data["maximum_samples"], 1, MAX_RAW_SAMPLES),
        api_resources=_resource(data["api_resources"]),
        worker_resources=_resource(data["worker_resources"]),
        experiments=tuple(_experiment(item) for item in values),
    )


def load_workload_manifest(path: Path) -> WorkloadManifest:
    """Read a regular local manifest with bounded allocation; never follow a file symlink."""
    try:
        if (
            path.is_symlink()
            or not path.is_file()
            or not 1 <= path.stat().st_size <= MAX_MANIFEST_BYTES
        ):
            raise WorkloadValidationError("A bounded regular workload manifest is required")
        with path.open("rb") as stream:
            raw = stream.read(MAX_MANIFEST_BYTES + 1)
    except OSError:
        raise WorkloadValidationError("Workload manifest is not readable") from None
    return parse_workload_manifest(raw)


def canonical_manifest_bytes(manifest: WorkloadManifest) -> bytes:
    """Stable versioned content for evidence binding; formatting/field order is irrelevant."""
    if type(manifest) is not WorkloadManifest:
        raise WorkloadValidationError("A validated immutable workload manifest is required")
    return json.dumps(
        asdict(manifest), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")


def manifest_digest(manifest: WorkloadManifest) -> str:
    return hashlib.sha256(canonical_manifest_bytes(manifest)).hexdigest()
