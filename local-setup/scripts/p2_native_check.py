"""Qualify isolated native P2 text/audio against local LiveKit and PostgreSQL.

Only ordinary local setup is read. Provider credential files and model endpoints
are not inputs. Private capture/configuration is bounded and ephemeral.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import signal
import socket
import sys
import tempfile
import time
import traceback
from collections.abc import Awaitable, Callable
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p3_coordinator_check as core

from harness.process_control import FileBarrier, OwnedProcess

ROOT = Path(__file__).resolve().parents[2]
MODE = "local_scripted_p2_native"
TOTAL_SECONDS = 240.0
CLEANUP_SECONDS = 20.0
MAX_REPORT_BYTES = 32768
MAX_CHILDREN = 24
MAX_CAPTURE_BYTES = 524288
MAX_STREAM_BYTES = 8192
CASE_NAMES = (
    "native_mint_authentication_and_fixed_binding",
    "native_text_durable_before_dispatch",
    "original_text_replay_receipt_operation",
    "committed_voice_shared_case_acceptance",
    "repeated_voice_commit_no_extra_acceptance",
    "native_returned_media_and_owned_cleanup",
)
NODE_MODES = (
    "install",
    "legacy-seed",
    "upgrade",
    "upgrade-interrupt",
    "seed",
    "expiry",
    "serve",
    "replay",
    "verify",
    "cleanup",
)
OWNER_MODES = frozenset({"install", "upgrade", "upgrade-interrupt", "verify", "cleanup"})
COMMON_ENV = frozenset({"P2_NATIVE_DIRECTORY", "P2_NATIVE_SCHEMA", "P2_NATIVE_PG_PORT"})
BASE_ENV = core.BASE_ENVIRONMENT_KEYS
PYTHON_METRICS = frozenset(
    {
        "textStreamsSeen",
        "voiceCaptures",
        "voiceCommits",
        "genuineFinalSnapshots",
        "durableAcceptCalls",
        "nativeInputsAccepted",
        "nativeInputsReplayed",
        "nativeInputsRejected",
        "nativeGenerationAttempts",
        "nativeGeneratedReplies",
        "defaultReplyInvocations",
        "activeReaders",
        "activePrepare",
        "activeIntakes",
        "activeVoiceWork",
        "activeReplyObservers",
        "observerPending",
        "observerFailures",
        "observerDropped",
        "sdkSessionClosed",
        "sdkCloseAllocationFailed",
    }
)
BROWSER_FLAGS = frozenset(
    {
        "unauthed_mint_rejected",
        "selector_mint_rejected",
        "ready",
        "text_accepted",
        "text_replayed_original_identity",
        "voice_accepted",
        "repeated_voice_commit_original_identity",
        "returned_native_text",
        "correlated_native_replies",
        "native_audio_advanced",
        "no_hardware_microphone",
        "fixture_track_stopped",
        "disconnected",
        "cleanup_complete",
    }
)


class GateError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__("Native P2 qualification did not pass")


def decode(raw: bytes, *, maximum: int = MAX_REPORT_BYTES) -> dict[str, Any]:
    if type(raw) is not bytes or not 1 <= len(raw) <= maximum:
        raise GateError("invalid_report")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=core.unique_object,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
    except (ValueError, UnicodeError, RecursionError, core.GateError):
        raise GateError("invalid_report") from None
    if type(value) is not dict:
        raise GateError("invalid_report")
    return value


def exact(actual: object, expected: object) -> bool:
    if type(actual) is not type(expected):
        return False
    if type(expected) is dict and type(actual) is dict:
        return actual.keys() == expected.keys() and all(
            exact(actual[k], v) for k, v in expected.items()
        )
    if type(expected) is list and type(actual) is list:
        return len(actual) == len(expected) and all(
            exact(a, b) for a, b in zip(actual, expected, strict=True)
        )
    return actual == expected


def validated_report(raw: bytes) -> dict[str, Any]:
    value = decode(raw)
    expected = {
        "schema_version": 1,
        "status": "passed",
        "mode": MODE,
        "tests": 6,
        "passed": 6,
        "errors": 0,
        "failures": 0,
        "skipped": 0,
        "cleanup_complete": True,
        "case_results": [{"name": name, "status": "passed", "code": "ok"} for name in CASE_NAMES],
        "inference_mode": "scripted",
        "provider_calls": False,
        "schema_version_observed": 6,
        "native_inputs": 2,
        "auxiliary_inputs": 3,
        "legacy_inputs": 1,
        "normal_prepared_plans": 2,
        "auxiliary_prepared_plans": 1,
        "normal_operation_acceptances": 2,
        "auxiliary_operation_acceptances": 1,
        "playwright_tests": 1,
        "owned_child_terminations": 1,
        "blocking_graphs_observed": 1,
        "native_generation_attempts": 2,
        "native_generated_replies": 2,
        "competing_default_replies": 0,
        "populated_restore_verified": True,
        "physical_microphone_qualification_claimed": False,
        "full_playback_or_room_resumption_claimed": False,
    }
    if set(value) != set(expected) | {
        "duration_seconds",
        "node_version",
        "browser_version",
        "child_commands",
    }:
        raise GateError("invalid_report")
    if not all(exact(value[key], wanted) for key, wanted in expected.items()):
        raise GateError("invalid_report")
    duration, children = value["duration_seconds"], value["child_commands"]
    if (
        type(duration) not in (int, float)
        or not 0 < duration <= TOTAL_SECONDS
        or not math.isfinite(duration)
        or type(children) is not int
        or not 1 <= children <= MAX_CHILDREN
    ):
        raise GateError("invalid_report")
    if (
        not core.supported_node(value["node_version"])
        or type(value["browser_version"]) is not str
        or re.fullmatch(r"[0-9]{1,4}(?:\.[0-9]{1,5}){3}", value["browser_version"]) is None
    ):
        raise GateError("invalid_report")
    return value


def child_environment(
    values: dict[str, str], context: dict[str, str], *, mode: str
) -> dict[str, str]:
    if (
        mode not in NODE_MODES
        or set(context) != COMMON_ENV
        or not re.fullmatch(r"p2_native_[a-f0-9]{32}", context["P2_NATIVE_SCHEMA"])
    ):
        raise GateError("invalid_child_mode")
    owner = mode in OWNER_MODES
    secret = "P2_NATIVE_OWNER_PASSWORD" if owner else "P2_NATIVE_RUNTIME_PASSWORD"
    source = "POSTGRES_MIGRATION_PASSWORD" if owner else "POSTGRES_PASSWORD"
    if not values.get(source) or values.get("POSTGRES_PORT") != context["P2_NATIVE_PG_PORT"]:
        raise GateError("missing_setup")
    result = {**core.base_environment(), **context, secret: values[source]}
    if set(result) - BASE_ENV != COMMON_ENV | {secret}:
        raise GateError("invalid_child_environment")
    return result


def validated_stage(raw: bytes, mode: str) -> dict[str, Any]:
    value = decode(raw)
    expected: dict[str, Any] = {
        "schemaVersion": 1,
        "status": "passed",
        "mode": mode,
        "cleanupComplete": True,
    }
    if mode not in NODE_MODES or mode == "upgrade-interrupt":
        raise GateError("invalid_child_mode")
    if mode == "verify":
        expected.update(
            {
                "schemaVersionObserved": 6,
                "nativeInputs": 2,
                "auxInputs": 3,
                "legacyInputs": 1,
                "processingIntents": 6,
                "normalPreparedPlans": 2,
                "auxPreparedPlans": 1,
                "normalOperationAcceptances": 2,
                "auxOperationAcceptances": 1,
                "nativeBindings": 3,
                "exactIdentityJoins": True,
                "legacyPreserved": True,
                "auxReplayPreserved": True,
            }
        )
    keys = set(expected) | {"nodeVersion"} | ({"metrics"} if mode == "serve" else set())
    if (
        set(value) != keys
        or not all(exact(value[k], wanted) for k, wanted in expected.items())
        or not core.supported_node(value.get("nodeVersion"))
    ):
        raise GateError("invalid_stage_report")
    if mode == "serve":
        expected_metrics = {
            "accepted": 2,
            "replayed": 1,
            "dispatched": 2,
            "active": 0,
            "intakes": 0,
            "sockets": 0,
            "handlers": 0,
            "driver": 0,
            "observerPending": 0,
        }
        if not exact(value["metrics"], expected_metrics):
            raise GateError("invalid_stage_report")

    return value


def validated_python(raw: bytes) -> dict[str, Any]:
    value = decode(raw)
    expected = {
        "schemaVersion": 1,
        "status": "passed",
        "mode": "serve",
        "cleanupComplete": True,
        "sdkClosed": True,
        "roomClosed": True,
        "httpClosed": True,
    }
    if set(value) != set(expected) | {"metrics"} or not all(
        exact(value[k], wanted) for k, wanted in expected.items()
    ):
        raise GateError("invalid_stage_report")
    metrics = value["metrics"]
    if (
        type(metrics) is not dict
        or set(metrics) != PYTHON_METRICS
        or any(type(v) is not int or not 0 <= v <= 1000000 for v in metrics.values())
    ):
        raise GateError("invalid_stage_report")
    fixed = {
        "voiceCaptures": 1,
        "voiceCommits": 2,
        "genuineFinalSnapshots": 1,
        "durableAcceptCalls": 3,
        "nativeInputsAccepted": 2,
        "nativeInputsReplayed": 1,
        "nativeGenerationAttempts": 2,
        "nativeGeneratedReplies": 2,
        "defaultReplyInvocations": 0,
        "activeReaders": 0,
        "activePrepare": 0,
        "activeIntakes": 0,
        "activeVoiceWork": 0,
        "activeReplyObservers": 0,
        "observerPending": 0,
        "observerFailures": 0,
        "observerDropped": 0,
        "sdkSessionClosed": 1,
        "sdkCloseAllocationFailed": 0,
    }
    if any(metrics[key] != wanted for key, wanted in fixed.items()):
        raise GateError("invalid_stage_report")
    return value


def validated_browser(raw: bytes) -> dict[str, Any]:
    value = decode(raw)
    if (
        set(value)
        != BROWSER_FLAGS | {"schema_version", "browser_version", "unexpected_network_requests"}
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or any(value[key] is not True for key in BROWSER_FLAGS)
        or type(value["unexpected_network_requests"]) is not int
        or value["unexpected_network_requests"] != 0
        or type(value["browser_version"]) is not str
        or re.fullmatch(r"[0-9]{1,4}(?:\.[0-9]{1,5}){3}", value["browser_version"]) is None
    ):
        raise GateError("invalid_browser_report")
    return value


def target_path(root: Path, path: Path) -> Path:
    if (
        path.is_absolute()
        or ".." in path.parts
        or path.suffix != ".json"
        or path.parts[:3] != (".local", "validation", "p2-native")
        or re.fullmatch(r"[a-z0-9_-]{1,80}\.json", path.name) is None
    ):
        raise GateError("unsafe_evidence_path")
    target = root / path
    if target.exists() or target.is_symlink() or any(p.is_symlink() for p in target.parents):
        raise GateError("unsafe_evidence_path")
    core.private_directory(target.parent)
    return target


def write_json(path: Path, value: object, *, maximum: int = MAX_REPORT_BYTES) -> None:
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    if len(raw) > maximum:
        raise GateError("report_limit")
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)


def endpoint(path: Path) -> int:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 256:
        raise GateError("invalid_endpoint")
    value = decode(path.read_bytes(), maximum=256)
    if (
        set(value) != {"host", "port"}
        or value["host"] != "127.0.0.1"
        or type(value["port"]) is not int
        or not 1024 <= value["port"] <= 65535
    ):
        raise GateError("invalid_endpoint")
    return value["port"]


def snapshot_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode()
    ).hexdigest()


def remaining(deadline: float) -> float:
    value = deadline - time.monotonic()
    if value <= 0:
        raise GateError("deadline_exceeded")
    return value


async def cleanup_actions(
    actions: tuple[Callable[[], Awaitable[None]], ...],
    state: dict[str, bool],
    primary: BaseException | None,
) -> None:
    """Attempt each independent owner; preserve the first in-flight failure."""
    failed = False
    control: BaseException | None = None
    for action in actions:
        try:
            await action()
        except BaseException as error:  # noqa: BLE001 - Cleanup also runs after caller cancellation.
            failed = True
            if not isinstance(error, Exception) and control is None:
                control = error
    state["cleanup_complete"] = not failed
    if primary is None:
        if control is not None:
            raise control
        if failed:
            raise GateError("cleanup_incomplete")


class Children:
    """Private bounded child capture; no raw streams become public reports."""

    def __init__(self, work: Path, deadline: float) -> None:
        self.work, self.deadline = work, deadline
        self.count = 0
        self.captured = 0
        self.children: list[OwnedProcess] = []

    def start(
        self, name: str, argv: list[str], environment: dict[str, str], *, cwd: Path
    ) -> OwnedProcess:
        if self.count >= MAX_CHILDREN or re.fullmatch(r"[a-z0-9-]{1,48}", name) is None:
            raise GateError("child_budget")
        remaining(self.deadline)
        self.count += 1
        child = OwnedProcess(
            argv,
            cwd=cwd,
            env=environment,
            output_directory=self.work / name,
            max_output_bytes=MAX_STREAM_BYTES,
        )
        self.children.append(child)
        return child

    def finish(
        self,
        child: OwnedProcess,
        *,
        deadline: float | None = None,
        require_zero: bool = True,
        accepted_codes: tuple[int, ...] | None = None,
    ) -> bytes:
        result = child.wait(timeout=min(120, remaining(deadline or self.deadline)))
        stdout, stderr = core.CaptureBudget.read(child.output_directory, MAX_STREAM_BYTES)
        self.captured += len(stdout) + len(stderr)
        if self.captured > MAX_CAPTURE_BYTES or child.cleanup_failed:
            raise GateError("capture_or_cleanup_failed")
        child.close()
        if result.returncode not in (
            accepted_codes
            if accepted_codes is not None
            else ((0,) if require_zero else (0, -signal.SIGTERM))
        ):
            raise GateError("child_failed")
        return stdout

    def call(
        self,
        name: str,
        argv: list[str],
        environment: dict[str, str],
        *,
        cwd: Path,
        deadline: float | None = None,
        accepted_codes: tuple[int, ...] | None = None,
    ) -> bytes:
        return self.finish(
            self.start(name, argv, environment, cwd=cwd),
            deadline=deadline,
            accepted_codes=accepted_codes,
        )

    def stop(self, child: OwnedProcess, *, deadline: float, require_zero: bool = True) -> bytes:
        sent = child.returncode is None
        if sent:
            os.kill(child.pid, signal.SIGTERM)
        # Vite may translate the requested signal to its conventional Node exit143.
        # A process that already exited nonzero has not acknowledged our shutdown.
        accepted = (
            None if require_zero else ((0, -signal.SIGTERM, 128 + signal.SIGTERM) if sent else (0,))
        )
        return self.finish(
            child, deadline=deadline, require_zero=require_zero, accepted_codes=accepted
        )

    def close(self) -> None:
        failed = False
        for child in reversed(self.children):
            try:
                child.close()
                failed |= child.cleanup_failed or child.returncode is None
            except Exception:  # noqa: BLE001 - Contain tooling cleanup failures; preserve primary outcome.
                failed = True
        if failed:
            raise GateError("cleanup_incomplete")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def safe_copy(
    source: Path, target: Path, secret_values: tuple[str, ...], *, maximum: int = 2097152
) -> None:
    if source.is_symlink() or not source.is_file() or source.stat().st_size > maximum:
        raise GateError("invalid_artifact")
    raw = source.read_bytes()
    if any(value.encode() in raw for value in secret_values if value):
        raise GateError("private_artifact")
    descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)


def verify_runtime_build(project: Path, compiled: Path) -> dict[str, Any]:
    """Bind self-referenced public dist to the source compilation used by this run."""
    source = project / "src"
    roots = (source, project / "dist", compiled, compiled / "src")
    if any(path.is_symlink() or not path.is_dir() for path in roots):
        raise GateError("runtime_build_mismatch")
    names = {
        path.relative_to(source).with_suffix(".js")
        for path in source.rglob("*.ts")
        if not path.name.endswith(".d.ts")
    }
    actual = {path.relative_to(project / "dist") for path in (project / "dist").rglob("*.js")}
    # The separate packaged CLI example is not imported by this native runtime.
    # Keep its explicit inventory distinct; artifact gates qualify that example.
    ancillary_name = Path("examples/fake-carrier.js")
    ancillary = {}
    if ancillary_name in actual:
        extra = project / "dist" / ancillary_name
        origin = project / "examples/fake-carrier.ts"
        if any(
            path.is_symlink() or not path.is_file() or path.stat().st_size > 1048576
            for path in (extra, origin)
        ) or any(path.is_symlink() or not path.is_dir() for path in (extra.parent, origin.parent)):
            raise GateError("runtime_build_mismatch")
        ancillary[str(ancillary_name)] = {
            "runtime_sha256": hashlib.sha256(extra.read_bytes()).hexdigest(),
            "source_sha256": hashlib.sha256(origin.read_bytes()).hexdigest(),
            "compiledParityClaimed": False,
            "loadedByNativeFixture": False,
        }
        actual.remove(ancillary_name)
    # The opt-in operations application is packaged separately, but current PG
    # compilation emits its exact source import. Do not admit arbitrary examples.
    operations_name = Path("examples/operations-lab.js")
    operations_runtime = project / "dist" / operations_name
    operations_source = project / "examples/operations-lab.ts"
    operations_compiled = compiled / operations_name
    operations_paths = (operations_runtime, operations_source, operations_compiled)
    if any(path.exists() or path.is_symlink() for path in operations_paths):
        if any(
            path.is_symlink() or not path.is_file() or path.stat().st_size > 1048576
            for path in operations_paths
        ) or any(
            path.is_symlink() or not path.is_dir()
            for path in (
                operations_runtime.parent,
                operations_source.parent,
                operations_compiled.parent,
            )
        ):
            raise GateError("runtime_build_mismatch")
        raw = operations_compiled.read_bytes()
        if raw != operations_runtime.read_bytes() or operations_name not in actual:
            raise GateError("runtime_build_mismatch")
        ancillary[str(operations_name)] = {
            "runtime_sha256": hashlib.sha256(raw).hexdigest(),
            "source_sha256": hashlib.sha256(operations_source.read_bytes()).hexdigest(),
            "compiledParityClaimed": True,
            "loadedByNativeFixture": False,
        }
        actual.remove(operations_name)
    # The starter is one exact application bundle, never a general examples exception.
    starter_names = {
        Path("examples/standalone-channel.js"),
        *(
            Path("examples/standalone") / (name + ".js")
            for name in ("config", "receipt-store", "external-http", "application")
        ),
    }
    starter_paths = [
        path
        for name in starter_names
        for path in (project / name.with_suffix(".ts"), project / "dist" / name, compiled / name)
    ]
    if any(path.exists() or path.is_symlink() for path in starter_paths):
        for name in sorted(starter_names):
            origin, built, expected = (
                project / name.with_suffix(".ts"),
                project / "dist" / name,
                compiled / name,
            )
            if name not in actual or any(
                path.is_symlink() or not path.is_file() or path.stat().st_size > 1048576
                for path in (origin, built, expected)
            ):
                raise GateError("runtime_build_mismatch")
            for base, path in ((project, origin), (project / "dist", built), (compiled, expected)):
                if any(
                    parent.is_symlink() or not parent.is_dir()
                    for parent in path.parents
                    if parent != base and base in parent.parents
                ):
                    raise GateError("runtime_build_mismatch")
            raw = expected.read_bytes()
            if raw != built.read_bytes():
                raise GateError("runtime_build_mismatch")
            ancillary[str(name)] = {
                "runtime_sha256": hashlib.sha256(raw).hexdigest(),
                "source_sha256": hashlib.sha256(origin.read_bytes()).hexdigest(),
                "compiledParityClaimed": True,
                "loadedByNativeFixture": False,
            }
            actual.remove(name)
        compiled_starter = {
            path.relative_to(compiled)
            for path in (compiled / "examples").rglob("*.js")
            if path.relative_to(compiled / "examples").parts[0].startswith("standalone")
        }
        if compiled_starter != starter_names:
            raise GateError("runtime_build_mismatch")
        for directory in (project / "dist/examples/standalone", compiled / "examples/standalone"):
            if {
                Path("examples/standalone") / path.relative_to(directory)
                for path in directory.rglob("*.js")
            } != starter_names - {Path("examples/standalone-channel.js")}:
                raise GateError("runtime_build_mismatch")
    compiled_names = {
        path.relative_to(compiled / "src") for path in (compiled / "src").rglob("*.js")
    }
    if not names or len(names) > 128 or actual != names or compiled_names != names:
        raise GateError("runtime_build_mismatch")
    hashes = {}
    for name in sorted(names):
        expected = compiled / "src" / name
        built = project / "dist" / name
        origin = source / name.with_suffix(".ts")
        if any(
            path.is_symlink() or not path.is_file() or path.stat().st_size > 1048576
            for path in (expected, built, origin)
        ):
            raise GateError("runtime_build_mismatch")
        for base, path in (
            (source, origin),
            (project / "dist", built),
            (compiled / "src", expected),
        ):
            if any(
                parent.is_symlink() or not parent.is_dir()
                for parent in path.parents
                if parent != base and base in parent.parents
            ):
                raise GateError("runtime_build_mismatch")
        raw = expected.read_bytes()
        if raw != built.read_bytes():
            raise GateError("runtime_build_mismatch")
        hashes[str(name)] = {
            "source_sha256": hashlib.sha256(origin.read_bytes()).hexdigest(),
            "runtime_sha256": hashlib.sha256(raw).hexdigest(),
        }
    return {
        "schemaVersion": 1,
        "status": "passed",
        "runtimeFiles": len(names),
        "sourceCompiledPublicDistEqual": True,
        "ancillary": ancillary,
        "files": hashes,
    }


def validate_partial_terminal(raw: bytes, kind: str) -> dict[str, Any]:
    value = decode(raw, maximum=4096)
    flags = (
        {"cleanupComplete", "sdkClosed", "roomClosed", "httpClosed"}
        if kind == "python"
        else {"cleanupComplete"}
    )
    expected = (
        {"schemaVersion", "status", "mode", "metrics"}
        | flags
        | ({"nodeVersion"} if kind == "node" else set())
    )
    labels = (
        PYTHON_METRICS
        if kind == "python"
        else {
            "accepted",
            "replayed",
            "dispatched",
            "active",
            "intakes",
            "sockets",
            "handlers",
            "driver",
            "observerPending",
        }
    )
    if (
        kind not in {"python", "node"}
        or set(value) != expected
        or not exact(value["schemaVersion"], 1)
        or value["status"] != "passed"
        or value["mode"] != "serve"
        or any(type(value[key]) is not bool for key in flags)
        or type(value["metrics"]) is not dict
        or set(value["metrics"]) != labels
        or any(
            type(item) is not int or not 0 <= item <= 1000000 for item in value["metrics"].values()
        )
        or (kind == "node" and not core.supported_node(value["nodeVersion"]))
    ):
        raise GateError("invalid_failure_context")
    return value


def validate_startup(raw: bytes, *, require_ready: bool = False) -> dict[str, Any]:
    value = decode(raw, maximum=2048)
    names = (
        "httpBound",
        "nodeEndpointReady",
        "roomConnected",
        "participantObserved",
        "sdkStart",
        "sdkReady",
    )
    if (
        set(value)
        != {
            "schemaVersion",
            "stage",
            "participantWaitBudgetMs",
            "sdkReadinessBudgetMs",
            "expectedParticipantObserved",
            "milestonesMs",
        }
        or not exact(value["schemaVersion"], 1)
        or not exact(value["participantWaitBudgetMs"], 60000)
        or not exact(value["sdkReadinessBudgetMs"], 10000)
        or type(value["expectedParticipantObserved"]) is not bool
        or type(value["stage"]) is not str
        or value["stage"]
        not in {
            "http_bound",
            "waiting_node",
            "room_connected",
            "waiting_participant",
            "sdk_starting",
            "ready",
        }
        or type(value["milestonesMs"]) is not dict
        or set(value["milestonesMs"]) != set(names)
    ):
        raise GateError("invalid_startup_observations")
    milestones = value["milestonesMs"]
    previous = -1
    missing = False
    for name in names:
        sample = milestones[name]
        if sample is None:
            missing = True
        elif missing or type(sample) is not int or not 0 <= sample <= 240000 or sample < previous:
            raise GateError("invalid_startup_observations")
        else:
            previous = sample
    if value["expectedParticipantObserved"] != (milestones["participantObserved"] is not None):
        raise GateError("invalid_startup_observations")
    if (require_ready or value["stage"] == "ready") and (
        value["stage"] != "ready"
        or missing
        or not value["expectedParticipantObserved"]
        or milestones["sdkReady"] - milestones["sdkStart"] >= 10000
        or milestones["participantObserved"] - milestones["roomConnected"] >= 60000
    ):
        raise GateError("invalid_startup_observations")
    return value


def validate_browser_context(raw: bytes, *, require_complete: bool = False) -> dict[str, Any]:
    value = decode(raw, maximum=1024)
    if (
        set(value)
        != {"schemaVersion", "stage", "connection", "pageErrors", "inputStatuses", "counts"}
        or not exact(value["schemaVersion"], 1)
        or type(value["stage"]) is not str
        or value["stage"]
        not in {
            "initializing",
            "mint_authentication",
            "mint_selector",
            "page_loading",
            "rtc_connect",
            "native_ready",
            "text_acceptance",
            "text_replay",
            "returned_text",
            "returned_audio",
            "voice_capture",
            "voice_acceptance",
            "voice_replay",
            "generation_completion",
            "cleanup",
            "complete",
        }
        or type(value["connection"]) is not str
        or value["connection"]
        not in {
            "Disconnected",
            "Joining",
            "Connected",
            "Reconnecting",
            "Closing",
            "Cleanup incomplete",
            "unobserved",
        }
        or type(value["pageErrors"]) is not int
        or not 0 <= value["pageErrors"] <= 1000
    ):
        raise GateError("invalid_failure_context")
    if (
        type(value["inputStatuses"]) is not list
        or len(value["inputStatuses"]) > 32
        or any(
            type(item) is not str
            or item not in {"pending", "accepted", "replayed", "rejected", "unknown", "unobserved"}
            for item in value["inputStatuses"]
        )
        or type(value["counts"]) is not dict
        or set(value["counts"])
        != {"sent", "accepted", "replayed", "rejected", "unknown", "invalid_ack"}
        or any(
            item is not None and (type(item) is not int or not 0 <= item <= 1000000)
            for item in value["counts"].values()
        )
    ):
        raise GateError("invalid_failure_context")
    if require_complete and (
        value["stage"] != "complete"
        or value["connection"] != "Disconnected"
        or value["pageErrors"] != 0
    ):
        raise GateError("invalid_failure_context")
    return value


def retain_failure_context(
    work: Path,
    artifacts: Path,
    children: Children,
    secret_values: tuple[str, ...],
    primary: BaseException,
) -> None:
    """Retain fixed failure locations, never raw child streams or exception text."""
    code = primary.code if isinstance(primary, (GateError, core.GateError)) else "gate_failed"
    if type(code) is not str or re.fullmatch(r"[a-z0-9_-]{1,80}", code) is None:
        code = "gate_failed"
    write_json(
        artifacts / "failure-context.json",
        {
            "status": "failed",
            "code": code,
            "errorType": type(primary).__name__
            if type(primary).__name__
            in {
                "GateError",
                "ValueError",
                "TypeError",
                "KeyError",
                "AttributeError",
                "AssertionError",
                "TimeoutError",
                "OSError",
            }
            else "DependencyError",
            "frames": [
                {"file": Path(frame.filename).name, "line": frame.lineno}
                for frame in traceback.extract_tb(primary.__traceback__)
                if Path(frame.filename).name in {"p2_native_check.py", "process_control.py"}
            ][-4:],
            "last_child": children.children[-1].output_directory.name
            if children.children
            else None,
            "child_commands": children.count,
        },
    )
    for name in (
        *(f"native-failure-{mode}.json" for mode in NODE_MODES),
        "python-failure-context.json",
    ):
        path = work / name
        if not path.exists():
            continue
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
            raise GateError("invalid_failure_context")
        value = decode(path.read_bytes(), maximum=4096)
        python = name == "python-failure-context.json"
        if python:
            if (
                set(value)
                != {"schemaVersion", "status", "mode", "stage", "errorType", "code", "frames"}
                or type(value["schemaVersion"]) is not int
                or value["schemaVersion"] != 1
                or value["status"] != "failed"
                or value["mode"] != "serve"
                or type(value["stage"]) is not str
                or value["stage"]
                not in {
                    "initializing",
                    "configuration",
                    "http_binding",
                    "waiting_node",
                    "rtc_connect",
                    "waiting_participant",
                    "sdk_start",
                    "ready",
                    "cleanup",
                    "finished",
                }
                or type(value["errorType"]) is not str
                or value["errorType"]
                not in {"NativeError", "TimeoutError", "OSError", "RuntimeError", "DependencyError"}
                or (
                    value["code"] is not None
                    and (
                        type(value["code"]) is not str
                        or value["code"]
                        not in {
                            "invalid_input",
                            "forbidden",
                            "idempotency_conflict",
                            "capacity_exhausted",
                            "dependency_unavailable",
                            "acknowledgement_unknown",
                            "closed",
                        }
                    )
                )
            ):
                raise GateError("invalid_failure_context")
            allowed_files = {
                "native_lab.py",
                "native_scripted.py",
                "native.py",
                "native_models.py",
                "native_rehydration.py",
                "native_http.py",
            }
        else:
            if (
                set(value) != {"type", "sqlState", "frames"}
                or type(value["type"]) is not str
                or value["type"] not in {"AssertionError", "Error", "DependencyError"}
                or (
                    value["sqlState"] is not None
                    and (
                        type(value["sqlState"]) is not str
                        or re.fullmatch(r"[A-Z0-9]{5}", value["sqlState"]) is None
                    )
                )
            ):
                raise GateError("invalid_failure_context")
            allowed_files = {"pg_native_cases.js"}
        if type(value["frames"]) is not list or len(value["frames"]) > 4:
            raise GateError("invalid_failure_context")
        for frame in value["frames"]:
            if (
                type(frame) is not dict
                or set(frame) != {"file", "line"}
                or type(frame["file"]) is not str
                or frame["file"] not in allowed_files
                or type(frame["line"]) is not int
                or not 1 <= frame["line"] <= 1000000
            ):
                raise GateError("invalid_failure_context")
        safe_copy(path, artifacts / name, secret_values, maximum=4096)
    for kind in ("python", "node"):
        terminal = work / (kind + "-terminal.json")
        if terminal.exists() or terminal.is_symlink():
            if terminal.is_symlink() or not terminal.is_file() or terminal.stat().st_size > 4096:
                raise GateError("invalid_failure_context")
            observed = validate_partial_terminal(terminal.read_bytes(), kind)
            write_json(
                artifacts / ("failed-" + kind + "-observations.json"),
                {"gateStatus": "failed", "processObservation": observed},
            )
    browser = work / "browser-report/native-browser-observations.json"
    if browser.exists() or browser.is_symlink():
        if browser.is_symlink() or not browser.is_file() or browser.stat().st_size > 4096:
            raise GateError("invalid_failure_context")
        value = decode(browser.read_bytes(), maximum=4096)
        if not set(value) <= BROWSER_FLAGS | {
            "schema_version",
            "browser_version",
            "unexpected_network_requests",
        } or not exact(value.get("schema_version"), 1):
            raise GateError("invalid_failure_context")
        for key, item in value.items():
            if key in BROWSER_FLAGS and type(item) is not bool:
                raise GateError("invalid_failure_context")
        version = value.get("browser_version")
        requests = value.get("unexpected_network_requests")
        if (
            type(version) is not str
            or re.fullmatch(r"[0-9]{1,3}(?:\.[0-9]{1,8}){1,3}", version) is None
            or type(requests) is not int
            or not 0 <= requests <= 1000000
        ):
            raise GateError("invalid_failure_context")
        safe_copy(
            browser, artifacts / "failed-browser-observations.json", secret_values, maximum=4096
        )
    startup = work / "native-startup-observations.json"
    if startup.exists() or startup.is_symlink():
        if startup.is_symlink() or not startup.is_file() or startup.stat().st_size > 2048:
            raise GateError("invalid_failure_context")
        validate_startup(startup.read_bytes())
        safe_copy(
            startup, artifacts / "failed-startup-observations.json", secret_values, maximum=2048
        )
    browser_context = work / "browser-report/native-browser-context.json"
    if browser_context.exists() or browser_context.is_symlink():
        if (
            browser_context.is_symlink()
            or not browser_context.is_file()
            or browser_context.stat().st_size > 1024
        ):
            raise GateError("invalid_failure_context")
        validate_browser_context(browser_context.read_bytes())
        safe_copy(
            browser_context, artifacts / "failed-browser-context.json", secret_values, maximum=1024
        )
    compiled = work / "compiled/tests/pg_native_cases.js"
    if compiled.is_file():
        safe_copy(compiled, artifacts / "failed-node-fixture.js", secret_values, maximum=262144)


def retain_failure_safely(
    work: Path,
    artifacts: Path,
    children: Children,
    secret_values: tuple[str, ...],
    primary: BaseException,
) -> bool:
    """Diagnostics are best effort; a failed sink must not skip any resource owner."""
    try:
        retain_failure_context(work, artifacts, children, secret_values, primary)
        return True
    except Exception:  # noqa: BLE001 - Diagnostic-only boundary; preserve primary and all cleanup.
        try:
            write_json(
                artifacts / "failure-context-unavailable.json",
                {"status": "unavailable", "code": "safe_context_not_retained"},
            )
        except Exception:  # noqa: BLE001 - A broken diagnostic sink cannot own resource cleanup.
            return False
        return False


def validated_expiry_proof(raw: bytes) -> dict[str, Any]:
    from uuid import UUID

    value = decode(raw)
    fields = {
        "schemaVersion",
        "ownerBackendPid",
        "waiters",
        "bindingId",
        "receiptId",
        "reservedReceiptId",
        "expiresAt",
        "firstWaitObservedDbClock",
        "releaseObservedDbClock",
        "newPrepareCalls",
        "newOperationCalls",
        "reservedOperationCalls",
        "blockedStatus",
        "reservedStatus",
    }
    if (
        set(value) != fields
        or type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
    ):
        raise GateError("invalid_expiry_proof")
    if type(value["ownerBackendPid"]) is not int or not 1 <= value["ownerBackendPid"] <= 2147483647:
        raise GateError("invalid_expiry_proof")
    waiters = value["waiters"]
    if (
        type(waiters) is not list
        or len(waiters) != 1
        or type(waiters[0]) is not dict
        or set(waiters[0]) != {"pid", "blockers"}
    ):
        raise GateError("invalid_expiry_proof")
    waiter = waiters[0]
    if (
        type(waiter["pid"]) is not int
        or not 1 <= waiter["pid"] <= 2147483647
        or waiter["pid"] == value["ownerBackendPid"]
        or not exact(waiter["blockers"], [value["ownerBackendPid"]])
    ):
        raise GateError("invalid_expiry_proof")
    try:
        for key in ("bindingId", "receiptId", "reservedReceiptId"):
            if type(value[key]) is not str or str(UUID(value[key])) != value[key]:
                raise ValueError()
        if value["receiptId"] == value["reservedReceiptId"]:
            raise ValueError()
        clocks = []
        for key in ("firstWaitObservedDbClock", "expiresAt", "releaseObservedDbClock"):
            if (
                type(value[key]) is not str
                or len(value[key]) > 40
                or re.fullmatch(
                    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|\+00:00)",
                    value[key],
                )
                is None
            ):
                raise ValueError()
            clocks.append(datetime.fromisoformat(value[key]))
        if not clocks[0] < clocks[1] <= clocks[2]:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise GateError("invalid_expiry_proof") from None
    if not all(
        exact(value[key], wanted)
        for key, wanted in {
            "newPrepareCalls": 0,
            "newOperationCalls": 0,
            "reservedOperationCalls": 1,
            "blockedStatus": "blocked",
            "reservedStatus": "dispatched",
        }.items()
    ):
        raise GateError("invalid_expiry_proof")
    return value


def expiry_schedule(
    children: Children,
    node: str,
    script: Path,
    values: dict[str, str],
    common: dict[str, str],
    work: Path,
    connection: Any,
    deadline: float,
) -> None:
    from psycopg import sql

    ready = FileBarrier(work, "expiry_ready")
    waiting = FileBarrier(work, "expiry_waiting")
    # Warm the owner connection before the child creates its short-lived grant.
    with closing(connection()) as owner:
        blocker = owner.execute("SELECT pg_backend_pid()").fetchone()[0]
        child = children.start(
            "expiry",
            [node, str(script), "expiry"],
            child_environment(values, common, mode="expiry"),
            cwd=work,
        )
        child.wait_for_barrier(ready, timeout=min(10, remaining(deadline)))
        original = decode((work / "native-expiry-original.json").read_bytes())
        expires_at = datetime.fromisoformat(original["grant"]["expiresAt"])
        if expires_at.tzinfo is None:
            raise GateError("invalid_expiry_proof")
        graph: list[dict[str, Any]] = []
        observed_at: datetime | None = None
        first_wait_at: datetime | None = None
        owner.execute("BEGIN")
        try:
            owner.execute(
                sql.SQL("SELECT * FROM {}.admission FOR UPDATE").format(
                    sql.Identifier(common["P2_NATIVE_SCHEMA"])
                )
            )
            child.release_barrier(ready)
            child.wait_for_barrier(waiting, timeout=min(2, remaining(deadline)))
            until = min(deadline, time.monotonic() + 1.4)
            while True:
                owner.execute("SELECT pg_stat_clear_snapshot()")
                rows = owner.execute(
                    "SELECT pid,pg_blocking_pids(pid) FROM pg_stat_activity WHERE %s=ANY(pg_blocking_pids(pid)) AND pid<>pg_backend_pid()",
                    [blocker],
                ).fetchall()
                if rows:
                    graph = [{"pid": row[0], "blockers": row[1]} for row in rows]
                    if (
                        len(graph) != 1
                        or graph[0]["pid"] == blocker
                        or graph[0]["blockers"] != [blocker]
                    ):
                        raise GateError("invalid_expiry_graph")
                    first_wait_at = owner.execute("SELECT clock_timestamp()").fetchone()[0]
                    if first_wait_at is None or first_wait_at >= expires_at:
                        raise GateError("expiry_predeadline_waiter_not_observed")
                    break
                if child.returncode is not None or time.monotonic() >= until:
                    raise GateError("expiry_waiter_not_observed")
                time.sleep(0.005)
            while True:
                observed_at = owner.execute("SELECT clock_timestamp()").fetchone()[0]
                if observed_at >= expires_at:
                    break
                if child.returncode is not None or time.monotonic() >= until:
                    raise GateError("expiry_boundary_not_observed")
                time.sleep(0.005)
        finally:
            owner.execute("ROLLBACK")
        validated_stage(children.finish(child), "expiry")
        proof = decode((work / "native-expiry-proof.json").read_bytes())
        if (
            proof.get("prepareCalls") != 1
            or type(proof.get("prepareCalls")) is not int
            or proof.get("operationCalls") != 1
            or type(proof.get("operationCalls")) is not int
            or proof.get("expiredNewPrepareCalls") != 0
            or type(proof.get("expiredNewPrepareCalls")) is not int
            or proof.get("expiredNewOperationCalls") != 0
            or type(proof.get("expiredNewOperationCalls")) is not int
            or proof.get("result", {}).get("status") != "blocked"
            or proof.get("reservedResult", {}).get("status") != "dispatched"
        ):
            raise GateError("invalid_expiry_proof")
        retained = {
            "schemaVersion": 1,
            "ownerBackendPid": blocker,
            "waiters": graph,
            "bindingId": original["grant"]["bindingId"],
            "receiptId": original["ack"]["receiptId"],
            "reservedReceiptId": original["reverseAck"]["receiptId"],
            "expiresAt": expires_at.isoformat(),
            "firstWaitObservedDbClock": first_wait_at.isoformat()
            if first_wait_at is not None
            else None,
            "releaseObservedDbClock": observed_at.isoformat() if observed_at is not None else None,
            "newPrepareCalls": 0,
            "newOperationCalls": 0,
            "reservedOperationCalls": 1,
            "blockedStatus": "blocked",
            "reservedStatus": "dispatched",
        }
        validated_expiry_proof(json.dumps(retained).encode())
        write_json(work / "native-expiry-lock-proof.json", retained)


async def run(
    root: Path,
    artifacts: Path,
    started: float,
    cleanup: dict[str, bool],
    browser_executable: str | None,
) -> dict[str, Any]:
    import aiohttp
    import psycopg
    from livekit import api
    from psycopg import sql

    final_deadline = started + TOTAL_SECONDS
    work_deadline = final_deadline - CLEANUP_SECONDS
    setup = core.load_setup(root)
    values = setup.load_settings()
    project = root / "projects/channel-continuity"
    console = root / "apps/local-console"
    node, docker = shutil.which("node"), shutil.which("docker")
    compiler = project / "node_modules/typescript/bin/tsc"
    python = root / ".venv/bin/python"
    app = project / "examples/native_lab.py"
    vite = console / "node_modules/vite/bin/vite.js"
    playwright = console / "node_modules/@playwright/test/cli.js"
    if (
        not node
        or not docker
        or not all(p.is_file() for p in (compiler, python, app, vite, playwright))
    ):
        raise GateError("missing_setup")
    if browser_executable is not None and (
        not Path(browser_executable).is_absolute() or not Path(browser_executable).is_file()
    ):
        raise GateError("missing_browser")
    run_id = uuid4().hex
    schema = "p2_native_" + run_id
    scratch = project / ".local/native-check"
    core.private_directory(scratch)
    with tempfile.TemporaryDirectory(prefix="run-", dir=scratch) as temporary:
        work = Path(temporary).resolve()
        children = Children(work, work_deadline)
        common = {
            "P2_NATIVE_DIRECTORY": str(work),
            "P2_NATIVE_SCHEMA": schema,
            "P2_NATIVE_PG_PORT": values["POSTGRES_PORT"],
        }
        fixture: dict[str, Any] = {
            "schemaVersion": 1,
            "providerScope": {
                "tenantId": "native-tenant",
                "provider": "livekit",
                "providerAccountId": "local-native",
            },
            "scope": {"tenantId": "native-tenant", "accountId": "native-account"},
            "caseId": "native-case",
            "conversationId": "native-conversation",
            "bindingId": str(uuid4()),
            "roomId": "p2-native-" + run_id,
            "participantId": "browser-" + run_id,
            "agentId": "p2-native-agent-" + run_id,
            **{
                key: secrets.token_urlsafe(32)
                for key in ("accountToken", "publisherToken", "bindingToken", "prepareToken")
            },
            "expiresAt": "",
            "ids": {"text": str(uuid4()), "voice": str(uuid4())},
        }
        media: dict[str, Any] = {
            "url": "ws://127.0.0.1:" + values["LIVEKIT_HTTP_PORT"],
            **{key: fixture[key] for key in ("roomId", "participantId", "agentId", "bindingId")},
            "browserAccessToken": secrets.token_urlsafe(32),
        }
        token_kinds: tuple[tuple[str, Literal["agent", "standard"]], ...] = (
            ("nativeToken", "agent"),
            ("browserToken", "standard"),
        )
        for name, kind in token_kinds:
            identity = fixture["agentId" if kind == "agent" else "participantId"]
            media[name] = (
                api.AccessToken(values["LIVEKIT_API_KEY"], values["LIVEKIT_API_SECRET"])
                .with_identity(identity)
                .with_kind(kind)
                .with_ttl(timedelta(seconds=240))
                .with_grants(
                    api.VideoGrants(
                        room_join=True,
                        room=fixture["roomId"],
                        can_publish=True,
                        can_subscribe=True,
                        can_publish_data=True,
                        can_update_own_metadata=kind == "agent",
                        can_manage_agent_session=False,
                    )
                )
                .to_jwt()
            )
        secrets_to_exclude = (
            tuple(str(v) for k, v in fixture.items() if k.endswith("Token"))
            + tuple(str(v) for k, v in media.items() if k.endswith("Token"))
            + tuple(values[k] for k in setup.SECRET_KEYS)
        )
        secrets_to_exclude += tuple(
            hashlib.sha256((prefix + fixture[key]).encode()).hexdigest()
            for prefix, key in (
                ("aux-account:", "accountToken"),
                ("aux-publisher:", "publisherToken"),
                ("aux-binding:", "bindingToken"),
                ("expiry-binding:", "bindingToken"),
            )
        )
        api_client = api.LiveKitAPI(
            url="http://127.0.0.1:" + values["LIVEKIT_HTTP_PORT"],
            api_key=values["LIVEKIT_API_KEY"],
            api_secret=values["LIVEKIT_API_SECRET"],
            timeout=aiohttp.ClientTimeout(total=3),
            failover=False,
        )
        room_attempted = False
        installed = False
        backup_possible = False
        container = ""
        backup_dir = "/tmp/p2-native-" + run_id
        node_report: dict[str, Any] = {}
        python_report: dict[str, Any] = {}
        browser_report: dict[str, Any] = {}
        node_version = ""

        def connection() -> Any:
            return psycopg.connect(
                host="127.0.0.1",
                port=int(values["POSTGRES_PORT"]),
                dbname="livekit_lab",
                user="continuity_migrator",
                password=values["POSTGRES_MIGRATION_PASSWORD"],
                sslmode="disable",
                connect_timeout=2,
                options="-c search_path=pg_catalog -c statement_timeout=3000 -c lock_timeout=1500",
                autocommit=True,
            )

        def snapshot() -> dict[str, Any]:
            with closing(connection()) as conn:
                names = [
                    row[0]
                    for row in conn.execute(
                        "SELECT tablename FROM pg_tables WHERE schemaname=%s ORDER BY tablename",
                        [schema],
                    )
                ]
                if not 1 <= len(names) <= 64:
                    raise GateError("invalid_schema_snapshot")
                result = {}
                for name in names:
                    result[name] = conn.execute(
                        sql.SQL(
                            "SELECT COALESCE(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]'::jsonb) FROM {}.{} t"
                        ).format(sql.Identifier(schema), sql.Identifier(name))
                    ).fetchone()[0]
                encoded = json.dumps(result, sort_keys=True).encode()
                if any(value.encode() in encoded for value in secrets_to_exclude):
                    raise GateError("private_artifact")
                return result

        try:
            compiled = work / "compiled"
            children.call(
                "compile",
                [
                    node,
                    str(compiler),
                    "--project",
                    str(project / "tsconfig.pg.json"),
                    "--outDir",
                    str(compiled),
                ],
                core.base_environment(),
                cwd=project,
            )
            script = compiled / "tests/pg_native_cases.js"
            if not script.is_file():
                raise GateError("missing_setup")
            write_json(
                artifacts / "runtime-build-parity.json", verify_runtime_build(project, compiled)
            )

            def stage(
                mode: str, label: str | None = None, *, deadline: float | None = None
            ) -> dict[str, Any]:
                raw = children.call(
                    label or mode,
                    [node, str(script), mode],
                    child_environment(values, common, mode=mode),
                    cwd=work,
                    deadline=deadline,
                )
                return validated_stage(raw, mode)

            fixture["expiresAt"] = (
                (datetime.now(UTC) + timedelta(seconds=280))
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z")
            )
            write_json(work / "fixture.json", fixture)
            write_json(work / "media.json", media)
            installed = True  # Cleanup checks exact owner/marker even after an unknown install ACK.
            node_version = stage("install")["nodeVersion"]
            stage("legacy-seed")
            legacy_before = snapshot()
            ddl_barrier = FileBarrier(work, "upgrade_ddl")
            interrupted = children.start(
                "upgrade-interrupt",
                [node, str(script), "upgrade-interrupt"],
                child_environment(values, common, mode="upgrade-interrupt"),
                cwd=work,
            )
            interrupted.wait_for_barrier(ddl_barrier, timeout=min(10, remaining(work_deadline)))
            killed = interrupted.kill(timeout=min(3, remaining(work_deadline)))
            if not killed.killed or killed.returncode != -signal.SIGKILL:
                raise GateError("upgrade_kill_not_observed")
            core.CaptureBudget.read(interrupted.output_directory, MAX_STREAM_BYTES)
            interrupted.close()
            legacy_after = snapshot()
            if (
                legacy_before != legacy_after
                or "native_settings" in legacy_after
                or "native_bindings" in legacy_after
            ):
                raise GateError("upgrade_rollback_changed_old_state")
            write_json(artifacts / "before-v5.json", legacy_before, maximum=2097152)
            write_json(artifacts / "after-rollback-v5.json", legacy_after, maximum=2097152)
            write_json(
                artifacts / "upgrade-rollback-proof.json",
                {
                    "schemaVersion": 1,
                    "ownedPid": killed.pid,
                    "returncode": killed.returncode,
                    "actualSigkill": killed.killed,
                    "before_sha256": snapshot_digest(legacy_before),
                    "after_sha256": snapshot_digest(legacy_after),
                    "newTablesAbsent": True,
                },
            )
            stage("upgrade")
            stage("seed")
            expiry_schedule(children, node, script, values, common, work, connection, work_deadline)
            python_http = FileBarrier(work, "python_http_ready")
            python_ready = FileBarrier(work, "python_ready")
            node_ready = FileBarrier(work, "node_ready")
            room_attempted = True
            await api_client.room.create_room(
                api.CreateRoomRequest(
                    name=fixture["roomId"],
                    empty_timeout=180,
                    departure_timeout=10,
                    max_participants=3,
                    metadata=json.dumps({"profile": "p2-native-lab", "owner": run_id}),
                )
            )
            python_child = children.start(
                "python-app",
                [str(python), "-I", str(app), str(work)],
                {**core.base_environment(), "P2_NATIVE_DIRECTORY": str(work)},
                cwd=work,
            )
            python_child.wait_for_barrier(python_http, timeout=min(15, remaining(work_deadline)))
            python_port = endpoint(work / "python-endpoint.json")
            node_child = children.start(
                "node-app",
                [node, str(script), "serve"],
                child_environment(values, common, mode="serve"),
                cwd=work,
            )
            node_child.wait_for_barrier(node_ready, timeout=min(15, remaining(work_deadline)))
            endpoint(work / "node-endpoint.json")
            ui_port = free_port()
            vite_child = children.start(
                "vite",
                [
                    node,
                    str(vite),
                    "--config",
                    str(console / "vite.native.config.ts"),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(ui_port),
                    "--strictPort",
                ],
                {
                    **core.base_environment(),
                    "P2_NATIVE_HTTP_ORIGIN": "http://127.0.0.1:" + str(python_port),
                },
                cwd=console,
            )
            # Wait for a real local HTTP listener, never a synthetic ready timer.
            until = min(work_deadline, time.monotonic() + 10)
            while True:
                if vite_child.returncode is not None:
                    raise GateError("browser_server_failed")
                try:
                    with socket.create_connection(("127.0.0.1", ui_port), timeout=0.2):
                        break
                except OSError:
                    if time.monotonic() >= until:
                        raise GateError("browser_server_unavailable") from None
                    await asyncio.sleep(0.01)
            browser_output = work / "browser-report"
            browser_output.mkdir(mode=0o700)
            browser_environment = {
                **core.base_environment(),
                "P2_NATIVE_BROWSER_ORIGIN": "http://127.0.0.1:" + str(ui_port),
                "P2_NATIVE_BROWSER_OUTPUT": str(browser_output),
                "P2_NATIVE_BROWSER_ACCESS": media["browserAccessToken"],
                "P2_NATIVE_TEXT_ID": fixture["ids"]["text"],
                "P2_NATIVE_VOICE_ID": fixture["ids"]["voice"],
            }
            if browser_executable is not None:
                browser_environment["PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"] = browser_executable
            children.call(
                "browser",
                [
                    node,
                    str(playwright),
                    "test",
                    "--config",
                    str(console / "playwright.native.config.ts"),
                    "--global-timeout",
                    "90000",
                ],
                browser_environment,
                cwd=console,
            )
            python_child.wait_for_barrier(python_ready, timeout=min(1, remaining(work_deadline)))
            validate_startup(
                (work / "native-startup-observations.json").read_bytes(), require_ready=True
            )
            browser_report = validated_browser(
                (browser_output / "native-browser-observations.json").read_bytes()
            )
            validate_browser_context(
                (browser_output / "native-browser-context.json").read_bytes(), require_complete=True
            )
            pw = decode((browser_output / "playwright.json").read_bytes(), maximum=1048576)
            if pw.get("stats", {}).get("expected") != 1 or any(
                pw["stats"].get(k) != 0 for k in ("unexpected", "flaky", "skipped")
            ):
                raise GateError("invalid_browser_report")
            write_json(artifacts / "playwright-stats.json", pw["stats"])
            python_report = validated_python(children.stop(python_child, deadline=work_deadline))
            node_report = validated_stage(
                children.stop(node_child, deadline=work_deadline), "serve"
            )
            children.stop(vite_child, deadline=work_deadline, require_zero=False)
            stage("replay")
            stage("verify")
            before = snapshot()
            write_json(artifacts / "before-v6.json", before, maximum=2097152)
            container = (
                children.call(
                    "backup-container",
                    [
                        docker,
                        "ps",
                        "--filter",
                        "label=com.docker.compose.service=postgres",
                        "--filter",
                        "label=com.docker.compose.project.working_dir=" + str(root / "local-setup"),
                        "--format",
                        "{{.ID}}",
                    ],
                    core.base_environment(),
                    cwd=work,
                )
                .decode()
                .strip()
            )
            if re.fullmatch(r"[a-f0-9]{12,64}", container) is None:
                raise GateError("wrong_backup_container")
            backup_possible = True  # Creation may commit before the CLI acknowledgement.
            children.call(
                "backup-directory",
                [docker, "exec", container, "mkdir", "-m", "700", backup_dir],
                core.base_environment(),
                cwd=work,
            )
            pg_env = {
                **core.base_environment(),
                "PGPASSWORD": values["POSTGRES_MIGRATION_PASSWORD"],
            }
            children.call(
                "backup-dump",
                [
                    docker,
                    "exec",
                    "-e",
                    "PGPASSWORD",
                    container,
                    "pg_dump",
                    "--host=127.0.0.1",
                    "--username=continuity_migrator",
                    "--dbname=livekit_lab",
                    "--schema=" + schema,
                    "--inserts",
                    "--no-owner",
                    "--file=" + backup_dir + "/schema.sql",
                ],
                pg_env,
                cwd=work,
            )
            children.call(
                "backup-copy",
                [
                    docker,
                    "cp",
                    container + ":" + backup_dir + "/schema.sql",
                    str(work / "populated-v6-backup.sql"),
                ],
                core.base_environment(),
                cwd=work,
            )
            with closing(connection()) as conn:
                owner = conn.execute(
                    "SELECT pg_get_userbyid(nspowner),obj_description(oid,'pg_namespace') FROM pg_namespace WHERE nspname=%s",
                    [schema],
                ).fetchone()
                if owner != ("continuity_migrator", "p2-channel-schema-v6"):
                    raise GateError("backup_ownership_mismatch")
                conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            children.call(
                "backup-restore",
                [
                    docker,
                    "exec",
                    "-e",
                    "PGPASSWORD",
                    container,
                    "psql",
                    "-X",
                    "--host=127.0.0.1",
                    "--username=continuity_migrator",
                    "--dbname=livekit_lab",
                    "--set=ON_ERROR_STOP=1",
                    "--single-transaction",
                    "--file=" + backup_dir + "/schema.sql",
                ],
                pg_env,
                cwd=work,
            )
            after = snapshot()
            stage("replay", "reopen-replay")
            stage("verify", "reopen-verify")
            reopened = snapshot()
            if before != after or after != reopened:
                raise GateError("restored_row_bytes_changed")
            write_json(artifacts / "after-v6.json", after, maximum=2097152)
            write_json(artifacts / "after-reopen-v6.json", reopened, maximum=2097152)
            write_json(
                artifacts / "restore-proof.json",
                {
                    "snapshot_codec": "json_sort_keys_compact_ascii_v1",
                    "before_sha256": snapshot_digest(before),
                    "after_sha256": snapshot_digest(after),
                    "reopen_sha256": snapshot_digest(reopened),
                    "counts": {key: len(rows) for key, rows in before.items()},
                },
            )
            for name in (
                "native-owner-proof.json",
                "native-legacy-original.json",
                "native-aux-original.json",
                "native-expiry-proof.json",
                "native-expiry-lock-proof.json",
                "native-aux-replay.json",
                "native-expiry-operations.json",
                "native-operations.json",
                "node-private-proof.json",
                "python-private-proof.json",
                "native-startup-observations.json",
                "populated-v6-backup.sql",
            ):
                safe_copy(work / name, artifacts / name, secrets_to_exclude)
            for name in (
                "native-browser-observations.json",
                "native-browser-context.json",
                "native-workspace.png",
            ):
                safe_copy(browser_output / name, artifacts / name, secrets_to_exclude)
            write_json(artifacts / "native-python-report.json", python_report)
            write_json(artifacts / "native-node-report.json", node_report)
        finally:
            primary = sys.exception()
            failed = False
            children.deadline = final_deadline
            # Stop serving children before touching their exact owned schema.
            for child in reversed(children.children):
                if child.returncode is None:
                    try:
                        children.stop(
                            child,
                            deadline=min(final_deadline, time.monotonic() + 3),
                            require_zero=child.output_directory.name != "vite",
                        )
                    except Exception:  # noqa: BLE001 - Contain tooling cleanup failures; preserve primary outcome.
                        failed = True
            try:
                children.close()
            except Exception:  # noqa: BLE001 - Contain tooling cleanup failures; preserve primary outcome.
                failed = True
            if primary is not None:
                retain_failure_safely(work, artifacts, children, secrets_to_exclude, primary)
            if installed:
                try:
                    raw = children.call(
                        "cleanup",
                        [node, str(work / "compiled/tests/pg_native_cases.js"), "cleanup"],
                        child_environment(values, common, mode="cleanup"),
                        cwd=work,
                        deadline=final_deadline,
                    )
                    validated_stage(raw, "cleanup")
                except Exception:  # noqa: BLE001 - Contain tooling cleanup failures; preserve primary outcome.
                    failed = True
            if backup_possible:
                operations = (
                    (
                        "backup-remove",
                        [docker, "exec", container, "rm", "-f", backup_dir + "/schema.sql"],
                        (0,),
                    ),
                    ("backup-rmdir", [docker, "exec", container, "rmdir", backup_dir], (0, 1)),
                    # Positional UUID-owned path, never interpolated shell text.
                    (
                        "backup-absent",
                        [
                            docker,
                            "exec",
                            container,
                            "sh",
                            "-ec",
                            '[ ! -e "$1" ] && [ ! -L "$1" ]',
                            "sh",
                            backup_dir,
                        ],
                        (0,),
                    ),
                )
                for name, command, codes in operations:
                    try:
                        children.call(
                            name,
                            command,
                            core.base_environment(),
                            cwd=work,
                            deadline=final_deadline,
                            accepted_codes=codes,
                        )
                    except Exception:  # noqa: BLE001 - Every independent cleanup is attempted.
                        failed = True
            if room_attempted:
                try:
                    response = await api_client.room.list_rooms(
                        api.ListRoomsRequest(names=[fixture["roomId"]])
                    )
                    for item in response.rooms:
                        if item.name != fixture["roomId"] or json.loads(item.metadata) != {
                            "profile": "p2-native-lab",
                            "owner": run_id,
                        }:
                            raise GateError("room_ownership_mismatch")
                        await api_client.room.delete_room(api.DeleteRoomRequest(room=item.name))
                    if (
                        await api_client.room.list_rooms(
                            api.ListRoomsRequest(names=[fixture["roomId"]])
                        )
                    ).rooms:
                        raise GateError("room_cleanup_incomplete")
                except Exception:  # noqa: BLE001 - Contain tooling cleanup failures; preserve primary outcome.
                    failed = True

            async def close_children() -> None:
                children.close()

            await cleanup_actions((api_client.aclose, close_children), cleanup, primary)
            cleanup["cleanup_complete"] = cleanup["cleanup_complete"] and not failed
            if not cleanup["cleanup_complete"] and primary is None:
                raise GateError("cleanup_incomplete")

        if not cleanup["cleanup_complete"]:
            raise GateError("cleanup_incomplete")
        return validated_report(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "passed",
                    "mode": MODE,
                    "tests": 6,
                    "passed": 6,
                    "errors": 0,
                    "failures": 0,
                    "skipped": 0,
                    "cleanup_complete": True,
                    "case_results": [
                        {"name": name, "status": "passed", "code": "ok"} for name in CASE_NAMES
                    ],
                    "duration_seconds": time.monotonic() - started,
                    "node_version": node_version,
                    "browser_version": browser_report["browser_version"],
                    "child_commands": children.count,
                    "inference_mode": "scripted",
                    "provider_calls": False,
                    "schema_version_observed": 6,
                    "native_inputs": 2,
                    "auxiliary_inputs": 3,
                    "legacy_inputs": 1,
                    "normal_prepared_plans": 2,
                    "auxiliary_prepared_plans": 1,
                    "normal_operation_acceptances": 2,
                    "auxiliary_operation_acceptances": 1,
                    "playwright_tests": 1,
                    "owned_child_terminations": 1,
                    "blocking_graphs_observed": 1,
                    "native_generation_attempts": python_report["metrics"][
                        "nativeGenerationAttempts"
                    ],
                    "native_generated_replies": python_report["metrics"]["nativeGeneratedReplies"],
                    "competing_default_replies": python_report["metrics"][
                        "defaultReplyInvocations"
                    ],
                    "populated_restore_verified": True,
                    "physical_microphone_qualification_claimed": False,
                    "full_playback_or_room_resumption_claimed": False,
                }
            ).encode()
        )


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--browser-executable")
    args = parser.parse_args(argv)
    started = time.monotonic()
    cleanup = {"cleanup_complete": False}
    target = None
    try:
        target = target_path(
            root, args.report or Path(".local/validation/p2-native/" + uuid4().hex + ".json")
        )
        artifacts = target.with_name(target.stem + "-artifacts")
        artifacts.mkdir(mode=0o700)
        value = asyncio.run(run(root, artifacts, started, cleanup, args.browser_executable))
    except (GateError, core.GateError) as error:
        value = {
            "status": "failed",
            "mode": MODE,
            "code": error.code,
            "duration_seconds": time.monotonic() - started,
            **cleanup,
        }
    except Exception:  # noqa: BLE001 - Contain tooling cleanup failures; preserve primary outcome.
        value = {
            "status": "failed",
            "mode": MODE,
            "code": "gate_failed",
            "duration_seconds": time.monotonic() - started,
            **cleanup,
        }
    try:
        if target is not None:
            write_json(target, value)
    except (OSError, GateError):
        value = {"status": "failed", "mode": MODE, "code": "evidence_not_retained", **cleanup}
    print(json.dumps(value, sort_keys=True))
    return 0 if value["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
