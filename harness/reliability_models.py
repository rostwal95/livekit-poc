"""Frozen declarations for actual P1 restart and slow-supplier workload evidence."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, cast

BASE_DIGEST = "442c9a05f40532a006f09fd4336092f76e2f72e531a178b7852e4859506f7aaf"
FaultKind = Literal["restart", "slow-shutdown"]


class ReliabilityValidationError(ValueError):
    """Only fixed safe diagnostics; declaration values are never reflected."""


def integer(value: object, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ReliabilityValidationError("Reliability budget is outside its safe range")
    return value


@dataclass(frozen=True, slots=True)
class ReliabilityCase:
    kind: FaultKind
    workers: int
    accepted: int
    rejected: int
    deadline_seconds: int
    control_deadline_ms: int
    supplier_delay_ms: int
    maximum_hold_ms: int
    stop_seconds: int

    @property
    def name(self) -> str:
        return f"{self.kind}-w{self.workers}"

    def __post_init__(self) -> None:
        if type(self.kind) is not str or self.kind not in {"restart", "slow-shutdown"}:
            raise ReliabilityValidationError("Unknown reliability fault schedule")
        integer(self.workers, 1, 2)
        integer(self.accepted, 8, 8)
        integer(self.rejected, 24, 24)
        integer(self.deadline_seconds, 120, 180)
        integer(self.control_deadline_ms, 500, 1500)
        integer(self.maximum_hold_ms, 3000, 4500)
        integer(self.stop_seconds, 5, 10)
        integer(self.supplier_delay_ms, 0, 1500)
        if (self.kind == "restart" and self.supplier_delay_ms != 0) or (
            self.kind == "slow-shutdown" and self.supplier_delay_ms < 1000
        ):
            raise ReliabilityValidationError("Fault delay does not match its declared mode")


@dataclass(frozen=True, slots=True)
class ReliabilityManifest:
    schema_version: int
    workload_id: str
    base_manifest_sha256: str
    seed: int
    overall_deadline_seconds: int
    maximum_samples: int
    cases: tuple[ReliabilityCase, ...]

    def __post_init__(self) -> None:
        integer(self.schema_version, 1, 1)
        if (
            type(self.workload_id) is not str
            or self.workload_id != "p1-reliability-v1"
            or type(self.base_manifest_sha256) is not str
            or self.base_manifest_sha256 != BASE_DIGEST
        ):
            raise ReliabilityValidationError("Unsupported reliability declaration or base")
        integer(self.seed, 0, 4294967295)
        integer(self.overall_deadline_seconds, 180, 600)
        integer(self.maximum_samples, 128, 4096)
        if (
            type(self.cases) is not tuple
            or len(self.cases) != 4
            or any(type(case) is not ReliabilityCase for case in self.cases)
        ):
            raise ReliabilityValidationError("Four explicit immutable fault cases are required")
        if {(case.kind, case.workers) for case in self.cases} != {
            (kind, workers) for kind in ("restart", "slow-shutdown") for workers in (1, 2)
        }:
            raise ReliabilityValidationError("Both fault schedules require both worker counts")
        if any(case.deadline_seconds > self.overall_deadline_seconds for case in self.cases):
            raise ReliabilityValidationError("Case deadline exceeds the original run budget")


def canonical_manifest(manifest: ReliabilityManifest) -> bytes:
    if type(manifest) is not ReliabilityManifest:
        raise ReliabilityValidationError("An immutable reliability declaration is required")
    return json.dumps(
        asdict(manifest), sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def manifest_digest(manifest: ReliabilityManifest) -> str:
    return hashlib.sha256(canonical_manifest(manifest)).hexdigest()


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ReliabilityValidationError("Duplicate reliability declaration field")
        result[key] = value
    return result


def _constant(_: str) -> object:
    raise ReliabilityValidationError("Nonfinite reliability value is invalid")


def _object(value: object, fields: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != fields:
        raise ReliabilityValidationError("Reliability fields are missing or unsupported")
    return cast(dict[str, object], value)


def parse_manifest(data: bytes) -> ReliabilityManifest:
    if type(data) is not bytes or not 1 <= len(data) <= 16384:
        raise ReliabilityValidationError("Reliability declaration byte bound exceeded")
    # Bound nesting before JSON decoding, including nesting inside hostile strings.
    depth, quoted, escaped = 0, False, False
    for byte in data:
        if escaped:
            escaped = False
        elif quoted and byte == 92:
            escaped = True
        elif byte == 34:
            quoted = not quoted
        elif not quoted and byte in (91, 123):
            depth += 1
            if depth > 8:
                raise ReliabilityValidationError("Reliability declaration nesting exceeded")
        elif not quoted and byte in (93, 125):
            depth -= 1
    try:
        decoded = json.loads(
            data.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant
        )
        root = _object(decoded, set(ReliabilityManifest.__dataclass_fields__))
        items = root["cases"]
        if type(items) is not list or len(items) != 4:
            raise ReliabilityValidationError("Four fault declarations are required")
        cases = []
        for item in items:
            fields = _object(item, set(ReliabilityCase.__dataclass_fields__))
            if type(fields["kind"]) is not str:
                raise ReliabilityValidationError("Fault kind must be explicit")
            cases.append(
                ReliabilityCase(
                    kind=cast(FaultKind, fields["kind"]),
                    workers=integer(fields["workers"], 1, 2),
                    accepted=integer(fields["accepted"], 8, 8),
                    rejected=integer(fields["rejected"], 24, 24),
                    deadline_seconds=integer(fields["deadline_seconds"], 120, 180),
                    control_deadline_ms=integer(fields["control_deadline_ms"], 500, 1500),
                    supplier_delay_ms=integer(fields["supplier_delay_ms"], 0, 1500),
                    maximum_hold_ms=integer(fields["maximum_hold_ms"], 3000, 4500),
                    stop_seconds=integer(fields["stop_seconds"], 5, 10),
                )
            )
        for key in ("workload_id", "base_manifest_sha256"):
            if type(root[key]) is not str:
                raise ReliabilityValidationError("Declaration identities must be strings")
        return ReliabilityManifest(
            schema_version=integer(root["schema_version"], 1, 1),
            workload_id=cast(str, root["workload_id"]),
            base_manifest_sha256=cast(str, root["base_manifest_sha256"]),
            seed=integer(root["seed"], 0, 4294967295),
            overall_deadline_seconds=integer(root["overall_deadline_seconds"], 180, 600),
            maximum_samples=integer(root["maximum_samples"], 128, 4096),
            cases=tuple(cases),
        )
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise ReliabilityValidationError("Reliability declaration is invalid") from None


def load_manifest(path: Path) -> ReliabilityManifest:
    if type(path) is not Path and not isinstance(path, Path):
        raise ReliabilityValidationError("A local declaration path is required")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 16384:
                raise ReliabilityValidationError("A bounded regular declaration is required")
            return parse_manifest(stream.read(16385))
    except (OSError, ValueError):
        raise ReliabilityValidationError(
            "Reliability declaration is unavailable or invalid"
        ) from None
