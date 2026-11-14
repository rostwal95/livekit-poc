"""Explicit local P2 operations PG/HTTP/browser evidence; no import setup or provider I/O."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import shutil
import stat
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Never, TypeVar
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import p2_native_check as native
import p2_rehydration_check as storage
import p2_workload_check as workload
import p3_coordinator_check as core

from harness.process_control import FileBarrier, OwnedProcess

Result = TypeVar("Result")
GateError = native.GateError
MODE = "local_scripted_p2_operations"
TOTAL_SECONDS, CLEANUP_SECONDS = 240, 20
MAX_CHILDREN, EXPECTED_CHILDREN = 24, 13
MAX_STREAM_BYTES, MAX_CAPTURE_BYTES = 8192, 524288
MAX_PROOF_BYTES, MAX_EVIDENCE_BYTES, MAX_REPORT_BYTES = 1048576, 16777216, 32768
CASE_NAMES = (
    "fixed_operator_capability_and_current_grant",
    "request_body_and_scope_selector_denied",
    "source_scope_section_cursor_binding",
    "ahead_missing_anchor_and_stale_case_cursor_denied",
    "bounded_get_header_host_body_and_client_framing",
    "durable_accepted_pending_running_projection",
    "uncertain_then_known_after_explicit_observation",
    "ordinary_send_unknown_and_callback_separate",
    "bounded_paging_and_canonical_identity_preserved",
    "read_only_zero_revision_and_non_atomic_as_of",
    "safe_read_error_and_same_read_retry",
    "late_read_fenced_and_close_retains_owner",
    "read_admission_overload_and_later_progress",
    "held_throwing_exporter_isolated_and_bounded",
    "real_safe_span_and_finite_metric_labels",
    "fresh_process_original_projection_and_zero_read_writes",
)
BROWSER_GROUPS = (
    "durable_joined_timeline_and_scoped_paging",
    "unknown_carrier_and_callback_source_separation",
    "actual_read_failure_retry_export_outage_and_forget_fencing",
)
NORMAL_COMMANDS = (
    "compile",
    "install",
    "seed",
    "exercise",
    "serve",
    "vite",
    "browser",
    "advance-dispatch",
    "advance-reconcile",
    "advance-callback",
    "verify",
    "reopen",
    "cleanup",
)
MODES = tuple(name for name in NORMAL_COMMANDS if name not in {"compile", "vite", "browser"})
OWNER_MODES = frozenset({"install", "verify", "cleanup"})
COMMON = frozenset({"P2_OPERATIONS_DIRECTORY", "P2_OPERATIONS_SCHEMA", "P2_OPERATIONS_PG_PORT"})
BROWSER_KEYS = frozenset(
    {
        "P2_OPERATIONS_BROWSER_ORIGIN",
        "P2_OPERATIONS_BROWSER_OUTPUT",
        "P2_OPERATIONS_BROWSER_ACCESS",
        "P2_OPERATIONS_DIRECTORY",
        "P2_OPERATIONS_OWNER",
        "P2_OPERATIONS_RECEIPT_ID",
        "P2_OPERATIONS_OPERATION_KEY",
        "P2_OPERATIONS_OUTBOUND_ID",
    }
)
MARKERS = (
    "hold-read",
    "release-read",
    "request-dispatch",
    "dispatch-running",
    "request-reconcile",
    "request-callback",
    "read-failure",
    "release-exporter",
    "browser-finished",
)
PROOF_FILES = (
    "operations-seed-proof.json",
    "operations-exercise-proof.json",
    "operations-dispatch-proof.json",
    "operations-reconcile-proof.json",
    "operations-callback-proof.json",
    "operations-provider-ledger.json",
    "operations-original-context.json",
    "operations-owner-proof.json",
    "operations-reopen-proof.json",
    "operations-server-proof.json",
    "operations-read-held.json",
    "operations-late-read-proof.json",
    "browser/operations-browser-observations.json",
    "browser/operations-ready.png",
    "browser/operations-recovered.png",
)
SNAPSHOT_PHASES = (
    "after_seed",
    "after_exercise",
    "after_dispatch",
    "after_reconcile",
    "after_callback",
    "after_browser",
    "after_verify",
    "after_reopen",
)
SNAPSHOT_PROOF_FILES = tuple("gate-snapshot-" + phase + ".json" for phase in SNAPSHOT_PHASES)
PARENT_PROOF_FILES = (
    "gate-owned-before-after.json",
    "gate-independent-joins.json",
    *SNAPSHOT_PROOF_FILES,
)
STAGES: dict[str, dict[str, Any]] = {
    "install": {"currentCaseSource": "standalone_reference_v1", "installed": True},
    "seed": {
        "nativeBindings": 4,
        "nativeInputs": 10,
        "ordinaryProviderCalls": 1,
        "ordinarySendResult": "unknown",
        "outboundReplies": 1,
        "smsInputs": 1,
    },
    "exercise": {
        "completedGroups": [CASE_NAMES[i] for i in (0, 1, 2, 3, 4, 8, 9, 10, 11, 12, 13, 14)],
        "nativeBindings": 5,
    },
    "advance-dispatch": {
        "logicalOperationAcceptances": 1,
        "possibleProviderCalls": 1,
        "processingState": "uncertain",
    },
    "advance-reconcile": {
        "logicalOperationAcceptances": 1,
        "nativeResponses": 1,
        "newOperationAcceptances": 0,
        "operationLookups": 1,
        "processingState": "dispatched",
        "sdkFacts": 2,
    },
    "advance-callback": {
        "callbackObservations": 1,
        "newSendCalls": 0,
        "ordinarySendResult": "unknown",
        "strongestReported": "delivered",
    },
    "verify": {
        "callbackObservations": 1,
        "completedGroups": list(CASE_NAMES[:15]),
        "exactIdentityJoins": True,
        "nativeBindings": 5,
        "nativeInputs": 10,
        "nativeResponses": 1,
        "operationAcceptances": 1,
        "outboundReplies": 1,
        "preparedPlans": 1,
        "processingIntents": 11,
        "readWrites": 0,
        "sdkFacts": 2,
        "sendAttempts": 1,
        "sendResults": 0,
        "smsInputs": 1,
    },
    "reopen": {
        "completedGroups": [CASE_NAMES[15]],
        "newOperationCalls": 0,
        "newPrepareCalls": 0,
        "newSendCalls": 0,
        "readWrites": 0,
        "sameOriginalFacts": True,
        "sameSignedCursor": True,
    },
    "cleanup": {"ownedSchemasAbsent": True},
}


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def counter(value: Any, maximum: int, minimum: int = 0) -> bool:
    return type(value) is int and minimum <= value <= maximum


def uuid(value: Any) -> bool:
    return (
        type(value) is str
        and re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", value
        )
        is not None
    )


def decode(raw: bytes, maximum: int = MAX_PROOF_BYTES) -> dict[str, Any]:
    return native.decode(raw, maximum=maximum)


def bounded_read(path: Path, maximum: int = MAX_PROOF_BYTES, *, allow_empty: bool = False) -> bytes:
    return workload.bounded_read(path, maximum, allow_empty=allow_empty)


def json_file(path: Path) -> dict[str, Any]:
    return decode(bounded_read(path))


def schemas(schema: str) -> tuple[str, str]:
    if type(schema) is not str or re.fullmatch(r"p2_operations_[0-9a-f]{32}", schema) is None:
        raise GateError("invalid_schema")
    return schema, "p2_case_operations_" + schema.removeprefix("p2_operations_")


def private_directory(path: Path) -> None:
    info = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise GateError("unsafe_evidence_path")


def validate_child_environment(env: dict[str, str], role: str) -> None:
    if (
        type(env) is not dict
        or role not in NORMAL_COMMANDS
        or any(
            type(k) is not str or type(v) is not str or not v or len(v) > 4096 or "\0" in v
            for k, v in env.items()
        )
    ):
        raise GateError("invalid_environment")
    optional: frozenset[str] = frozenset()
    if role in MODES:
        password = (
            "P2_OPERATIONS_OWNER_PASSWORD"
            if role in OWNER_MODES
            else "P2_OPERATIONS_RUNTIME_PASSWORD"
        )
        required = COMMON | {password}
        schemas(env.get("P2_OPERATIONS_SCHEMA", ""))
        port = env.get("P2_OPERATIONS_PG_PORT", "")
        if re.fullmatch(r"[1-9][0-9]{0,4}", port) is None or int(port) > 65535:
            raise GateError("invalid_environment")
    elif role == "browser":
        required = BROWSER_KEYS
        optional = frozenset({"PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"})
        if (
            re.fullmatch(r"[a-f0-9]{32}", env.get("P2_OPERATIONS_OWNER", "")) is None
            or any(
                not uuid(env.get("P2_OPERATIONS_" + k))
                for k in ("RECEIPT_ID", "OPERATION_KEY", "OUTBOUND_ID")
            )
            or re.fullmatch(r"[A-Za-z0-9_-]{43}", env.get("P2_OPERATIONS_BROWSER_ACCESS", ""))
            is None
        ):
            raise GateError("invalid_environment")
        from urllib.parse import urlsplit

        origin = urlsplit(env.get("P2_OPERATIONS_BROWSER_ORIGIN", ""))
        try:
            if (
                origin.scheme != "http"
                or origin.hostname != "127.0.0.1"
                or not origin.port
                or origin.username
                or origin.password
                or origin.path not in {"", "/"}
                or origin.query
                or origin.fragment
            ):
                raise ValueError
        except ValueError:
            raise GateError("invalid_environment") from None
    elif role == "vite":
        required = frozenset({"P2_OPERATIONS_API_PORT"})
        port = env.get("P2_OPERATIONS_API_PORT", "")
        if re.fullmatch(r"[1-9][0-9]{0,4}", port) is None or int(port) > 65535:
            raise GateError("invalid_environment")
    else:
        required = frozenset()
    if not required <= env.keys() or env.keys() - required - optional - core.BASE_ENVIRONMENT_KEYS:
        raise GateError("invalid_environment")
    for key in (
        "P2_OPERATIONS_DIRECTORY",
        "P2_OPERATIONS_BROWSER_OUTPUT",
        "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH",
    ):
        if key in env:
            path = Path(env[key])
            if not path.is_absolute() or path != path.resolve() or path.is_symlink():
                raise GateError("invalid_environment")
            if key == "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH":
                if not path.is_file():
                    raise GateError("invalid_environment")
            else:
                private_directory(path)


def child_environment(values: dict[str, str], common: dict[str, str], mode: str) -> dict[str, str]:
    if (
        mode not in MODES
        or set(common) != COMMON
        or values.get("POSTGRES_PORT") != common["P2_OPERATIONS_PG_PORT"]
    ):
        raise GateError("invalid_environment")
    key = (
        "P2_OPERATIONS_OWNER_PASSWORD" if mode in OWNER_MODES else "P2_OPERATIONS_RUNTIME_PASSWORD"
    )
    source = "POSTGRES_MIGRATION_PASSWORD" if mode in OWNER_MODES else "POSTGRES_PASSWORD"
    env = {**core.base_environment(), **common, key: values.get(source, "")}
    validate_child_environment(env, mode)
    return env


def validated_stage(raw: bytes, mode: str) -> dict[str, Any]:
    if mode not in MODES:
        raise GateError("invalid_child_mode")
    value = decode(raw, MAX_STREAM_BYTES)
    fixed = {
        "schemaVersion": 1,
        "status": "passed",
        "mode": mode,
        "storageVersion": 0 if mode == "cleanup" else 7,
        "nodeVersion": "24.22.2",
        "cleanupComplete": True,
    }
    if (
        set(value) != set(fixed) | {"result"}
        or any(not native.exact(value[k], v) for k, v in fixed.items())
        or type(value["result"]) is not dict
    ):
        raise GateError("invalid_stage")
    result = value["result"]
    if mode == "serve":
        settled = {
            "casePortClosed": True,
            "getterPending": 0,
            "httpClosed": True,
            "httpHandlers": 0,
            "httpSockets": 0,
            "inboxClosed": True,
            "observerPending": 0,
            "readerActive": 0,
            "readerClosed": True,
            "telemetryClosed": True,
        }
        if (
            set(result) != set(settled) | {"exporterDropped", "exporterFailures"}
            or any(not native.exact(result[k], v) for k, v in settled.items())
            or any(
                not counter(result[k], 9223372036854775807, 1)
                for k in ("exporterDropped", "exporterFailures")
            )
        ):
            raise GateError("invalid_stage")
    elif not native.exact(result, STAGES[mode]):
        raise GateError("invalid_stage")
    return value


def validated_marker(raw: bytes, stage: str, owner: str) -> dict[str, Any]:
    if (
        stage not in MARKERS
        or type(owner) is not str
        or re.fullmatch(r"[a-f0-9]{32}", owner) is None
    ):
        raise GateError("invalid_marker")
    value = decode(raw, 256)
    if not native.exact(value, {"schemaVersion": 1, "owner": owner, "stage": stage}):
        raise GateError("invalid_marker")
    return value


def endpoint(path: Path, process_id: int) -> int:
    value = json_file(path)
    if (
        set(value) != {"schemaVersion", "host", "port", "pid"}
        or not native.exact(value["schemaVersion"], 1)
        or value["host"] != "127.0.0.1"
        or not counter(value["port"], 65535, 1)
        or not native.exact(value["pid"], process_id)
    ):
        raise GateError("invalid_endpoint")
    return int(value["port"])


class Children(workload.Children):
    def start(
        self, name: str, argv: list[str], environment: dict[str, str], *, cwd: Path
    ) -> OwnedProcess:
        if (
            self.count >= MAX_CHILDREN
            or name not in NORMAL_COMMANDS
            or any(c.output_directory.name == name for c in self.children)
        ):
            raise GateError("child_budget")
        validate_child_environment(environment, name)
        return super().start(name, argv, environment, cwd=cwd)


def owned_children_settled(children: Children) -> bool:
    return workload.owned_children_settled(children)


def child_capture_root(work: Path) -> Path:
    # Process-control captures require fresh role directories. Browser-produced
    # evidence has its own independently owned work/browser directory.
    private_directory(work)
    directory = work / "commands"
    directory.mkdir(mode=0o700)
    return directory


def target_path(root: Path, path: Path) -> Path:
    if (
        path.is_absolute()
        or len(path.parts) != 4
        or path.parts[:3] != (".local", "validation", "p2-operations")
        or re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}\.json", path.name) is None
    ):
        raise GateError("unsafe_report_path")
    current = root
    for index, part in enumerate(path.parts[:-1]):
        current /= part
        if current.is_symlink():
            raise GateError("unsafe_report_path")
        current.mkdir(mode=0o700, exist_ok=True)
        if index == 2:
            private_directory(current)
        else:
            info = current.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
                raise GateError("unsafe_report_path")
    target = current / path.name
    if (
        target.exists()
        or target.is_symlink()
        or target.with_name(target.stem + "-artifacts").exists()
        or target.with_name(target.stem + "-artifacts").is_symlink()
    ):
        raise GateError("evidence_exists")
    return target


def physical_files(directory: Path) -> dict[str, bytes]:
    private_directory(directory)
    result: dict[str, bytes] = {}
    total = 0
    for path in sorted(directory.rglob("*")):
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            private_directory(path)
            continue
        name = path.relative_to(directory).as_posix()
        if name == "retained-index.json":
            continue
        if re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", name) is None or any(
            p in {".", ".."} for p in Path(name).parts
        ):
            raise GateError("unsafe_proof_file")
        raw = bounded_read(path, MAX_PROOF_BYTES, allow_empty=name.endswith(".bin"))
        total += len(raw)
        if len(result) >= 2048 or total > MAX_EVIDENCE_BYTES:
            raise GateError("evidence_limit")
        result[name] = raw
    if not result:
        raise GateError("missing_evidence")
    return result


def evidence_index(directory: Path) -> dict[str, Any]:
    if (directory / "retained-index.json").exists() or (
        directory / "retained-index.json"
    ).is_symlink():
        raise GateError("evidence_exists")
    files = physical_files(directory)
    value = {
        "schemaVersion": 1,
        "files": {n: {"bytes": len(raw), "sha256": digest(raw)} for n, raw in files.items()},
        "totalBytes": sum(map(len, files.values())),
    }
    native.write_json(directory / "retained-index.json", value, maximum=MAX_PROOF_BYTES)
    return value


def validate_evidence_index(directory: Path, expected_sha256: str) -> dict[str, Any]:
    raw = bounded_read(directory / "retained-index.json")
    if digest(raw) != expected_sha256:
        raise GateError("invalid_evidence_index")
    value = decode(raw)
    actual = physical_files(directory)
    expected = {
        "schemaVersion": 1,
        "files": {n: {"bytes": len(data), "sha256": digest(data)} for n, data in actual.items()},
        "totalBytes": sum(map(len, actual.values())),
    }
    if not native.exact(value, expected):
        raise GateError("invalid_evidence_index")
    return value


def public_source_bytes(path: Path) -> bytes:
    # P1's legitimate empty typed-package marker is part of its 78 payloads.
    if path.name != "py.typed":
        return storage.source_bytes(path)
    before = path.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or before.st_uid != os.getuid()
        or before.st_size != 0
    ):
        raise GateError("unsafe_source_file")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        current = os.fstat(stream.fileno())
        if (current.st_dev, current.st_ino, current.st_size) != (
            before.st_dev,
            before.st_ino,
            0,
        ) or stream.read(1) != b"":
            raise GateError("unsafe_source_file")
    return b""


def source_snapshot(root: Path) -> dict[str, str]:
    paths: set[Path] = set()
    for part, suffixes in (
        ("projects/channel-continuity/src", {".ts"}),
        ("projects/channel-continuity/tests", {".ts"}),
        ("projects/channel-continuity/examples", {".ts"}),
        ("projects/agent-continuity/python/src/continuity_lab", {".py"}),
    ):
        base = root / part
        if base.is_symlink() or not base.is_dir():
            raise GateError("unsafe_source_file")
        selected = {p for p in base.rglob("*") if p.suffix in suffixes}
        if not selected:
            raise GateError("unsafe_source_file")
        paths.update(selected)
    for name in (
        "p2_operations_check.py",
        "p2_native_check.py",
        "p2_playback_check.py",
        "p2_rehydration_check.py",
        "p2_rehydration_media_check.py",
        "p2_workload_check.py",
        "p3_coordinator_check.py",
        "p3_document_package.py",
        "p3_document_evidence.py",
        "p3_package_check.py",
    ):
        paths.add(root / "local-setup/scripts" / name)
    for name in (
        "package.json",
        "pnpm-lock.yaml",
        "harness/process_control.py",
        "tests/test_p2_operations_gate.py",
        "projects/channel-continuity/package.json",
        "projects/channel-continuity/tsconfig.pg.json",
        "projects/channel-continuity/tsconfig.test.json",
        "projects/channel-continuity/tsconfig.json",
        "projects/channel-continuity/tsconfig.examples.json",
        "apps/local-console/src/intake.ts",
        "projects/channel-continuity/operations/bounded-v1.json",
        "apps/local-console/package.json",
        "apps/local-console/p2-operations.html",
        "apps/local-console/vite.operations.config.ts",
        "apps/local-console/playwright.operations.config.ts",
        "apps/local-console/tsconfig.operations.json",
        "apps/local-console/tsconfig.e2e.json",
        "apps/local-console/e2e/p2-operations.browser.ts",
    ):
        paths.add(root / name)
    paths.update((root / "apps/local-console/src").glob("p2-operations*"))
    paths.add(root / "apps/local-console/src/p2-context-policy.ts")
    paths.add(root / "projects/agent-continuity/python/src/continuity_lab/py.typed")
    paths.add(root / "apps/local-console/src/business.ts")
    for name in (
        "PublicSans-Regular.woff2",
        "PublicSans-SemiBold.woff2",
        "commit-mono-400-regular.woff",
        "lk-logo-dark.svg",
    ):
        paths.add(root / "apps/local-console/public/vendor/livekit" / name)
    paths.add(root / "apps/local-console/src/p2-native-policy.ts")
    return {str(p.relative_to(root)): digest(public_source_bytes(p)) for p in sorted(paths)}


def plan(root: Path = ROOT) -> dict[str, Any]:
    validate_manifest(
        storage.source_bytes(root / "projects/channel-continuity/operations/bounded-v1.json")
    )
    return {
        "schema_version": 1,
        "status": "not_started",
        "mode": MODE,
        "storage_cases": list(CASE_NAMES),
        "browser_groups": list(BROWSER_GROUPS),
        "normal_commands": list(NORMAL_COMMANDS),
        "bounds": {
            "total_seconds": TOTAL_SECONDS,
            "cleanup_seconds": CLEANUP_SECONDS,
            "normal_children": EXPECTED_CHILDREN,
            "maximum_children": MAX_CHILDREN,
            "stream_bytes": MAX_STREAM_BYTES,
            "aggregate_capture_bytes": MAX_CAPTURE_BYTES,
            "proof_bytes": MAX_PROOF_BYTES,
            "retained_bytes": MAX_EVIDENCE_BYTES,
            "report_bytes": MAX_REPORT_BYTES,
        },
        "measurement_started": False,
        "sfu_calls": 0,
        "provider_calls": 0,
    }


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise GateError("invalid_arguments")


# The actual orchestration and closed proof joins are added against the frozen producer ABI.
def validate_fixture(value: dict[str, Any]) -> dict[str, Any]:
    keys = {
        "schemaVersion",
        "owner",
        "profileId",
        "sourceId",
        "scope",
        "caseId",
        "conversationId",
        "providerScope",
        "accountToken",
        "publisherToken",
        "nativeToken",
        "bindingId",
        "operatorAuthorization",
        "cursorKeyBase64",
        "expiresAt",
        "request",
        "ids",
        "sms",
        "communication",
    }
    if (
        type(value) is not dict
        or set(value) != keys
        or not native.exact(value["schemaVersion"], 1)
        or type(value["owner"]) is not str
        or re.fullmatch(r"[a-f0-9]{32}", value["owner"]) is None
    ):
        raise GateError("invalid_fixture")
    owner = value["owner"]
    expected = {
        "sourceId": "p2-operations-v1",
        "scope": {"tenantId": "operations-" + owner, "accountId": "account-main"},
        "caseId": "case-main",
        "conversationId": "conversation-main",
        "providerScope": {
            "tenantId": "operations-" + owner,
            "provider": "livekit",
            "providerAccountId": "operations-native",
        },
        "request": {
            "schemaVersion": 1,
            "kind": "booking_investigation",
            "bookingReference": "OPS-001",
            "newCheckIn": "2030-12-10",
            "investigationConsent": True,
        },
    }
    if (
        any(not native.exact(value[k], v) for k, v in expected.items())
        or not uuid(value["profileId"])
        or not uuid(value["bindingId"])
    ):
        raise GateError("invalid_fixture")
    ids = value["ids"]
    if (
        type(ids) is not dict
        or set(ids)
        != {
            "callback",
            "generation",
            "history",
            "main",
            "outbound",
            "response",
            "revisionCommand",
            "sms",
        }
        or type(ids["history"]) is not list
        or len(ids["history"]) != 9
    ):
        raise GateError("invalid_fixture")
    all_ids = [
        value["profileId"],
        value["bindingId"],
        *ids["history"],
        *(v for k, v in ids.items() if k != "history"),
    ]
    if any(not uuid(v) for v in all_ids) or len(set(all_ids)) != len(all_ids):
        raise GateError("invalid_fixture")
    communication = value["communication"]
    sms = value["sms"]
    if (
        type(communication) is not dict
        or set(communication) != {"browserToken", "publisherToken", "sdkToken"}
        or type(sms) is not dict
        or set(sms) != {"callbackKeyBase64", "hmacKeyBase64", "providerScope", "senderId"}
        or not native.exact(
            sms["providerScope"],
            {
                "tenantId": "operations-" + owner,
                "provider": "fake_sms",
                "providerAccountId": "operations-sms",
            },
        )
        or sms["senderId"] != "operations-sender"
    ):
        raise GateError("invalid_fixture")
    authorization = value["operatorAuthorization"]
    if (
        type(authorization) is not str
        or re.fullmatch(r"Bearer [A-Za-z0-9_-]{43}", authorization) is None
    ):
        raise GateError("invalid_fixture")
    tokens = [
        *(value[k] for k in ("accountToken", "publisherToken", "nativeToken")),
        *communication.values(),
        authorization[7:],
    ]
    if any(
        type(v) is not str or re.fullmatch(r"[A-Za-z0-9_-]{43}", v) is None for v in tokens
    ) or len(set(tokens)) != len(tokens):
        raise GateError("invalid_fixture")
    for key in (value["cursorKeyBase64"], sms["hmacKeyBase64"], sms["callbackKeyBase64"]):
        try:
            if (
                type(key) is not str
                or len(base64.b64decode(key, validate=True)) != 32
                or base64.b64encode(base64.b64decode(key)).decode() != key
            ):
                raise ValueError
        except (ValueError, TypeError):
            raise GateError("invalid_fixture") from None
    try:
        expiry = value["expiresAt"]
        if (
            type(expiry) is not str
            or len(expiry) != 24
            or not expiry.endswith("Z")
            or datetime.fromisoformat(expiry)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
            != expiry
        ):
            raise ValueError
    except ValueError:
        raise GateError("invalid_fixture") from None
    return value


def make_fixture() -> dict[str, Any]:
    owner = uuid4().hex
    nonce = secrets.token_bytes(32)

    def material(purpose: str) -> bytes:
        return hmac.new(
            nonce, b"p2.operations.v1\n" + owner.encode() + b"\n" + purpose.encode(), hashlib.sha256
        ).digest()

    def token(purpose: str) -> str:
        return base64.urlsafe_b64encode(material(purpose)).decode().rstrip("=")

    def key(purpose: str) -> str:
        return base64.b64encode(material(purpose)).decode()

    return validate_fixture(
        {
            "schemaVersion": 1,
            "owner": owner,
            "profileId": str(uuid4()),
            "sourceId": "p2-operations-v1",
            "scope": {"tenantId": "operations-" + owner, "accountId": "account-main"},
            "caseId": "case-main",
            "conversationId": "conversation-main",
            "providerScope": {
                "tenantId": "operations-" + owner,
                "provider": "livekit",
                "providerAccountId": "operations-native",
            },
            "accountToken": token("account"),
            "publisherToken": token("publisher"),
            "nativeToken": token("native"),
            "bindingId": str(uuid4()),
            "operatorAuthorization": "Bearer " + token("operator"),
            "cursorKeyBase64": key("cursor"),
            "expiresAt": (datetime.now(UTC) + timedelta(seconds=280))
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "request": {
                "schemaVersion": 1,
                "kind": "booking_investigation",
                "bookingReference": "OPS-001",
                "newCheckIn": "2030-12-10",
                "investigationConsent": True,
            },
            "ids": {
                "history": [str(uuid4()) for _ in range(9)],
                **{
                    k: str(uuid4())
                    for k in (
                        "callback",
                        "generation",
                        "main",
                        "outbound",
                        "response",
                        "revisionCommand",
                        "sms",
                    )
                },
            },
            "sms": {
                "hmacKeyBase64": key("sms-sign"),
                "callbackKeyBase64": key("sms-callback"),
                "providerScope": {
                    "tenantId": "operations-" + owner,
                    "provider": "fake_sms",
                    "providerAccountId": "operations-sms",
                },
                "senderId": "operations-sender",
            },
            "communication": {
                "browserToken": token("communication-browser"),
                "publisherToken": token("communication-publisher"),
                "sdkToken": token("communication-sdk"),
            },
        }
    )


def fixture_secrets(fixture: dict[str, Any], settings: dict[str, str]) -> tuple[str, ...]:
    """Scan-only values; never copied to reports or retained indexes."""
    validate_fixture(fixture)
    base = tuple(
        sorted(
            {
                fixture["operatorAuthorization"],
                fixture["operatorAuthorization"][7:],
                *(
                    fixture[k]
                    for k in ("accountToken", "publisherToken", "nativeToken", "cursorKeyBase64")
                ),
                *fixture["communication"].values(),
                fixture["sms"]["hmacKeyBase64"],
                fixture["sms"]["callbackKeyBase64"],
                *(
                    settings[k]
                    for k in ("POSTGRES_PASSWORD", "POSTGRES_MIGRATION_PASSWORD")
                    if settings.get(k)
                ),
            }
        )
    )
    labels = (
        "zero-account",
        "foreign-account",
        "zero-publisher",
        "foreign-publisher",
        "outbox-publisher",
        "zero-response",
        "zero-sdk",
        "zero-browser",
        "foreign-response",
        "foreign-sdk",
        "foreign-browser",
        "zero-binding",
        "foreign-binding",
        "expired-binding",
        "revoked-binding",
        "wrong-operator",
    )
    aliases = tuple(
        base64.urlsafe_b64encode(
            hmac.new(
                fixture["accountToken"].encode(),
                ("p2.ops.fixture.v1:" + label).encode(),
                hashlib.sha256,
            ).digest()
        )
        .decode()
        .rstrip("=")
        for label in labels
    )
    return (*base, *aliases)


def exclude_private(raw: bytes, forbidden: tuple[str, ...]) -> None:
    if any(secret.encode() in raw for secret in forbidden if secret):
        raise GateError("private_artifact")


def independent_snapshot(connect: Callable[[], Any], schema: str) -> dict[str, Any]:
    """Owner-only observation, separate from product codecs/fixture assertions."""
    from contextlib import closing

    from psycopg import sql

    result = {}
    with closing(connect()) as connection, connection.transaction():
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        for name in schemas(schema):
            names = [
                r[0]
                for r in connection.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname=%s ORDER BY tablename",
                    [name],
                )
            ]
            if name == schema:
                workload.validate_catalog_names(names)
            elif names != ["case_metadata", "cases"]:
                raise GateError("invalid_catalog_inventory")
            tables = {}
            for table in names:
                rows = [
                    r[0]
                    for r in connection.execute(
                        sql.SQL(
                            "SELECT to_jsonb(t) FROM {}.{} t ORDER BY to_jsonb(t)::text LIMIT 65"
                        ).format(sql.Identifier(name), sql.Identifier(table))
                    )
                ]
                if len(rows) > 64:
                    raise GateError("snapshot_limit")
                tables[table] = rows
            result[name] = tables
    if len(json.dumps(result, ensure_ascii=True, allow_nan=False).encode()) > MAX_PROOF_BYTES:
        raise GateError("snapshot_limit")
    return result


class ActualCalls:
    """Shield thread owners; caller cancellation cannot erase an actual SQL/file wait."""

    def __init__(self) -> None:
        self.tasks: set[asyncio.Task[Any]] = set()
        self.closing = False

    async def call(self, function: Callable[..., Result], *args: Any, **kwargs: Any) -> Result:
        if self.closing:
            raise GateError("closed")
        task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
        self.tasks.add(task)

        def settled(done: asyncio.Task[Any]) -> None:
            self.tasks.discard(done)
            if not done.cancelled():
                done.exception()

        task.add_done_callback(settled)
        return await asyncio.shield(task)

    async def close(self, final: float) -> bool:
        self.closing = True
        return await self.drain(final)

    async def drain(self, final: float) -> bool:
        if not self.tasks:
            return True
        _, pending = await asyncio.wait(tuple(self.tasks), timeout=max(0, final - time.monotonic()))
        return not pending and not self.tasks


def decode_array(raw: bytes) -> list[Any]:
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_PROOF_BYTES:
        raise GateError("invalid_proof")
    value = decode(b'{"value":' + raw + b"}", MAX_PROOF_BYTES + 10)["value"]
    if type(value) is not list:
        raise GateError("invalid_proof")
    return value


def shape(value: Any, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise GateError("invalid_proof")
    return value


def utc(value: Any) -> datetime:
    try:
        if type(value) is not str or len(value) != 24 or not value.endswith("Z"):
            raise ValueError
        result = datetime.fromisoformat(value)
        if result.isoformat(timespec="milliseconds").replace("+00:00", "Z") != value:
            raise ValueError
        return result
    except ValueError:
        raise GateError("invalid_proof") from None


def proof_snapshot(value: Any, schema: str) -> dict[str, Any]:
    value = shape(value, {"schema", "caseSchema", "tables", "caseTables"})
    a, b = schemas(schema)
    if (
        value["schema"] != a
        or value["caseSchema"] != b
        or type(value["tables"]) is not dict
        or type(value["caseTables"]) is not dict
    ):
        raise GateError("invalid_snapshot")
    workload.validate_catalog_names(sorted(value["tables"]))
    if set(value["caseTables"]) != {"case_metadata", "cases"}:
        raise GateError("invalid_snapshot")
    for tables in (value["tables"], value["caseTables"]):
        for rows in tables.values():
            if type(rows) is not list or len(rows) > 64 or any(type(r) is not dict for r in rows):
                raise GateError("invalid_snapshot")
    return {a: value["tables"], b: value["caseTables"]}


def snapshot_table_counts(value: dict[str, Any], schema: str) -> dict[str, dict[str, int]]:
    a, b = schemas(schema)
    shape(value, {a, b})
    checked = proof_snapshot(
        {"schema": a, "caseSchema": b, "tables": value[a], "caseTables": value[b]}, schema
    )
    return {
        name: {table: len(rows) for table, rows in tables.items()}
        for name, tables in checked.items()
    }


def write_snapshot_proofs(
    directory: Path, snapshots: dict[str, Any], schema: str
) -> dict[str, Any]:
    private_directory(directory)
    shape(snapshots, set(SNAPSHOT_PHASES))
    payloads: dict[str, bytes] = {}
    counts: dict[str, dict[str, dict[str, int]]] = {}
    for phase in SNAPSHOT_PHASES:
        counts[phase] = snapshot_table_counts(snapshots[phase], schema)
        try:
            raw = json.dumps(
                snapshots[phase],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode()
        except (TypeError, ValueError, OverflowError, RecursionError):
            raise GateError("invalid_snapshot") from None
        if not 1 <= len(raw) <= MAX_PROOF_BYTES:
            raise GateError("proof_limit")
        payloads[phase] = raw
    manifest: dict[str, Any] = {
        "schemaVersion": 1,
        "codec": "json_sort_keys_compact_ascii_v1",
        "snapshots": {},
        "digests": {phase: digest(payloads[phase]) for phase in SNAPSHOT_PHASES},
    }
    for phase, name in zip(SNAPSHOT_PHASES, SNAPSHOT_PROOF_FILES, strict=True):
        raw = payloads[phase]
        with os.fdopen(
            os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600),
            "wb",
        ) as output:
            output.write(raw)
        manifest["snapshots"][phase] = {
            "path": name,
            "type": "postgres_owner_snapshot",
            "bytes": len(raw),
            "sha256": digest(raw),
            "tableCounts": counts[phase],
        }
    native.write_json(
        directory / "gate-owned-before-after.json", manifest, maximum=MAX_REPORT_BYTES
    )
    return manifest


def validate_snapshot_proofs(directory: Path, schema: str) -> dict[str, Any]:
    manifest = shape(
        decode(
            bounded_read(directory / "gate-owned-before-after.json", MAX_REPORT_BYTES),
            MAX_REPORT_BYTES,
        ),
        {"schemaVersion", "codec", "snapshots", "digests"},
    )
    if (
        not native.exact(manifest["schemaVersion"], 1)
        or manifest["codec"] != "json_sort_keys_compact_ascii_v1"
    ):
        raise GateError("invalid_snapshot_proof")
    descriptors = shape(manifest["snapshots"], set(SNAPSHOT_PHASES))
    digests = shape(manifest["digests"], set(SNAPSHOT_PHASES))
    result: dict[str, Any] = {}
    for phase, name in zip(SNAPSHOT_PHASES, SNAPSHOT_PROOF_FILES, strict=True):
        descriptor = shape(descriptors[phase], {"path", "type", "bytes", "sha256", "tableCounts"})
        if (
            descriptor["path"] != name
            or descriptor["type"] != "postgres_owner_snapshot"
            or not counter(descriptor["bytes"], MAX_PROOF_BYTES, 1)
        ):
            raise GateError("invalid_snapshot_proof")
        raw = bounded_read(directory / name)
        if (
            len(raw) != descriptor["bytes"]
            or digest(raw) != descriptor["sha256"]
            or not native.exact(digests[phase], descriptor["sha256"])
        ):
            raise GateError("invalid_snapshot_proof")
        value = decode(raw)
        counts = snapshot_table_counts(value, schema)
        if workload.snapshot_digest(value) != digest(raw) or not native.exact(
            descriptor["tableCounts"], counts
        ):
            raise GateError("invalid_snapshot_proof")
        result[phase] = value
    return result


def one(rows: list[Any], key: str, value: Any) -> dict[str, Any]:
    found = [row for row in rows if type(row) is dict and native.exact(row.get(key), value)]
    if len(found) != 1:
        raise GateError("invalid_identity_join")
    return found[0]


def checked_digest(raw: Any, expected: Any) -> dict[str, Any]:
    if (
        type(raw) is not str
        or type(expected) is not str
        or re.fullmatch(r"[a-f0-9]{64}", expected) is None
        or digest(raw.encode()) != expected
    ):
        raise GateError("invalid_payload_digest")
    return decode(raw.encode(), 32768)


def verify_signed(
    raw_base64: Any,
    headers: Any,
    key_base64: str,
    provider: dict[str, Any],
    prefix: str,
    accepted_at: Any,
) -> dict[str, Any]:
    headers = shape(headers, {"timestamp", "signature"})
    if (
        type(raw_base64) is not str
        or len(raw_base64) > 8192
        or type(headers["timestamp"]) is not str
        or re.fullmatch(r"[1-9][0-9]{9}", headers["timestamp"]) is None
        or type(headers["signature"]) is not str
        or re.fullmatch(r"[a-f0-9]{64}", headers["signature"]) is None
    ):
        raise GateError("invalid_signed_evidence")
    try:
        raw = base64.b64decode(raw_base64, validate=True)
        if len(raw) > 4096 or base64.b64encode(raw).decode() != raw_base64:
            raise ValueError
    except ValueError:
        raise GateError("invalid_signed_evidence") from None
    material = (
        prefix
        + provider["tenantId"]
        + "\n"
        + provider["provider"]
        + "\n"
        + provider["providerAccountId"]
        + "\n"
        + headers["timestamp"]
        + "\n"
    ).encode() + raw
    expected = hmac.new(base64.b64decode(key_base64), material, hashlib.sha256).hexdigest()
    if (
        not hmac.compare_digest(expected, headers["signature"])
        or abs(datetime.fromisoformat(accepted_at).timestamp() - int(headers["timestamp"])) > 60
    ):
        raise GateError("invalid_signed_evidence")
    return decode(raw, 4096)


def validate_owner_joins(
    proofs: dict[str, Any], snapshot: dict[str, Any], fixture: dict[str, Any], schema: str
) -> dict[str, Any]:
    """Recompute original receipt/plan/provider/response/callback joins independently of TS assertions."""
    validate_fixture(fixture)
    if not native.exact(proof_snapshot(proofs["operations-owner-proof.json"], schema), snapshot):
        raise GateError("owner_snapshot_mismatch")
    rows = snapshot[schema]
    expected_counts = {
        "inbox": 11,
        "processing_intents": 11,
        "native_bindings": 5,
        "dispatch_plans": 1,
        "native_responses": 1,
        "native_observations": 2,
        "reply_intents": 1,
        "send_attempts": 1,
        "send_results": 0,
        "callback_observations": 1,
    }
    if any(len(rows[k]) != n for k, n in expected_counts.items()):
        raise GateError("invalid_inventory")
    seed = shape(
        proofs["operations-seed-proof.json"],
        {"accepted", "sms", "reply", "sendRequest", "sendOutcome", "stored"},
    )
    if (
        type(seed["accepted"]) is not list
        or len(seed["accepted"]) != 10
        or type(seed["stored"]) is not list
        or len(seed["stored"]) != 10
        or type(seed["sms"]) is not dict
    ):
        raise GateError("invalid_originals")
    originals = [*seed["stored"], seed["sms"]["stored"]]
    seen = set()
    for original in originals:
        receipt = original["receipt"]
        row = one(rows["inbox"], "receipt_id", receipt["receiptId"])
        intent = one(rows["processing_intents"], "receipt_id", receipt["receiptId"])
        if (
            receipt["receiptId"] in seen
            or not uuid(receipt["receiptId"])
            or row["tenant_id"] != fixture["scope"]["tenantId"]
            or row["account_id"] != fixture["scope"]["accountId"]
            or row["conversation_id"] != fixture["conversationId"]
        ):
            raise GateError("invalid_originals")
        seen.add(receipt["receiptId"])
        event = decode(row["wire_json"].encode(), 8192)
        semantic = decode(row["canonical_payload"].encode(), 8192)
        if (
            not native.exact(event, original["event"])
            or semantic
            != {
                k: v for k, v in event.items() if k not in {"receivedAt", "retryCount", "signature"}
            }
            or event["accountScope"] != fixture["scope"]
            or event["caseId"] != fixture["caseId"]
            or event["conversationId"] != fixture["conversationId"]
            or event["providerScope"]
            != {
                "tenantId": row["tenant_id"],
                "provider": row["provider"],
                "providerAccountId": row["provider_account_id"],
            }
            or event["eventId"] != receipt["eventId"]
            or row["event_id"] != receipt["eventId"]
            or row["message_id"] != receipt["messageId"]
            or str(row["acceptance_sequence"]) != receipt["acceptanceSequence"]
            or intent["operation_key"] != original["operationKey"]
            or datetime.fromisoformat(row["accepted_at"]) != utc(receipt["acceptedAt"])
        ):
            raise GateError("invalid_originals")
    sms_signed = shape(seed["sms"]["signed"], {"rawBase64", "headers"})
    sms_original = seed["sms"]["stored"]
    sms_body = verify_signed(
        sms_signed["rawBase64"],
        sms_signed["headers"],
        fixture["sms"]["hmacKeyBase64"],
        fixture["sms"]["providerScope"],
        "p2.fake_sms.v1\n",
        sms_original["receipt"]["acceptedAt"],
    )
    if any(
        sms_body[k] != sms_original["event"][k]
        for k in ("eventId", "messageId", "senderId", "body")
    ):
        raise GateError("invalid_sms_identity")
    selected = seed["accepted"][0]
    main = one(rows["inbox"], "event_id", fixture["ids"]["main"])
    intent = one(rows["processing_intents"], "receipt_id", main["receipt_id"])
    plan = one(rows["dispatch_plans"], "receipt_id", main["receipt_id"])
    ledger = proofs["operations-provider-ledger.json"]
    if type(ledger) is not list or len(ledger) != 1:
        raise GateError("invalid_operation_inventory")
    operation = shape(ledger[0], {"submission", "canonicalPayload", "payloadDigest", "receipt"})
    submission = checked_digest(operation["canonicalPayload"], operation["payloadDigest"])
    if (
        not native.exact(submission, operation["submission"])
        or plan["payload_json"] != operation["canonicalPayload"]
        or plan["payload_digest"] != operation["payloadDigest"]
        or submission["scope"] != fixture["scope"]
        or submission["caseId"] != fixture["caseId"]
        or submission["conversationId"] != fixture["conversationId"]
        or submission["caseRevision"] != "2"
        or submission["operationKey"] != intent["operation_key"]
        or selected["receiptId"] != main["receipt_id"]
        or selected["operationKey"] != intent["operation_key"]
        or submission["message"]["receiptId"] != main["receipt_id"]
        or operation["receipt"]["scope"] != fixture["scope"]
        or operation["receipt"]["operationKey"] != intent["operation_key"]
        or operation["receipt"]["payloadDigest"] != operation["payloadDigest"]
        or intent["state"] != "dispatched"
        or intent["external_receipt_id"] != operation["receipt"]["receiptId"]
    ):
        raise GateError("invalid_operation_identity")
    event = decode(main["wire_json"].encode(), 8192)
    if any(
        submission["message"][k] != event[k] for k in ("eventId", "messageId", "senderId", "body")
    ):
        raise GateError("invalid_operation_identity")
    response = rows["native_responses"][0]
    anchor = checked_digest(response["canonical_anchor"], response["anchor_digest"])
    if (
        response["response_id"] != fixture["ids"]["response"]
        or response["generation_id"] != fixture["ids"]["generation"]
        or response["binding_id"] != fixture["bindingId"]
        or response["input_receipt_id"] != main["receipt_id"]
        or response["operation_key"] != intent["operation_key"]
        or anchor["scope"] != fixture["scope"]
        or anchor["caseId"] != fixture["caseId"]
        or anchor["conversationId"] != fixture["conversationId"]
        or anchor["inputId"] != fixture["ids"]["main"]
    ):
        raise GateError("invalid_response_identity")
    reconcile = proofs["operations-reconcile-proof.json"]
    if (
        reconcile["operationLookups"] != 1
        or not native.exact(reconcile["newOperationAcceptances"], 0)
        or len(reconcile["facts"]) != 2
        or len(reconcile["observations"]) != 2
        or reconcile["ledger"] != ledger
    ):
        raise GateError("invalid_response_identity")
    if response["response_sequence"] != 1 or sorted(
        r["observation_sequence"] for r in rows["native_observations"]
    ) != [1, 2]:
        raise GateError("invalid_scoped_sequence")
    for fact, receipt in zip(reconcile["facts"], reconcile["observations"], strict=True):
        row = one(rows["native_observations"], "event_id", fact["eventId"])
        payload = checked_digest(row["canonical_payload"], row["payload_digest"])
        if (
            not native.exact(payload, fact)
            or row["source"] != "agent_sdk"
            or row["response_id"] != response["response_id"]
            or row["binding_id"] != fixture["bindingId"]
            or row["receipt_id"] != receipt["receiptId"]
            or str(row["observation_sequence"]) != receipt["observationSequence"]
            or row["payload_digest"] != receipt["payloadDigest"]
        ):
            raise GateError("invalid_observation_identity")
    for key, expected in (
        ("tenant_id", fixture["scope"]["tenantId"]),
        ("account_id", fixture["scope"]["accountId"]),
        ("case_id", fixture["caseId"]),
        ("conversation_id", fixture["conversationId"]),
    ):
        if response[key] != expected:
            raise GateError("invalid_response_identity")
    reply = rows["reply_intents"][0]
    envelope = checked_digest(reply["canonical_payload"], reply["intent_digest"])
    if (
        envelope["scope"] != fixture["scope"]
        or envelope["caseId"] != fixture["caseId"]
        or envelope["conversationId"] != fixture["conversationId"]
        or envelope["outboundId"] != fixture["ids"]["outbound"]
        or envelope["responseId"] != fixture["ids"]["response"]
        or digest(envelope["body"].encode()) != reply["body_digest"]
        or seed["reply"]["receiptId"] != reply["receipt_id"]
        or seed["reply"]["intentDigest"] != reply["intent_digest"]
        or seed["reply"]["bodyDigest"] != reply["body_digest"]
    ):
        raise GateError("invalid_reply_identity")
    for key, expected in (
        ("tenant_id", fixture["scope"]["tenantId"]),
        ("account_id", fixture["scope"]["accountId"]),
        ("case_id", fixture["caseId"]),
        ("conversation_id", fixture["conversationId"]),
    ):
        if reply[key] != expected:
            raise GateError("invalid_reply_identity")
    send = rows["send_attempts"][0]
    request = checked_digest(send["canonical_request"], send["request_digest"])
    if (
        not native.exact(request, seed["sendRequest"])
        or send["outbound_id"] != fixture["ids"]["outbound"]
        or send["tenant_id"] != fixture["scope"]["tenantId"]
        or send["account_id"] != fixture["scope"]["accountId"]
        or request["body"] != envelope["body"]
        or request["scope"] != fixture["scope"]
        or request["caseId"] != fixture["caseId"]
        or request["conversationId"] != fixture["conversationId"]
        or request["providerScope"] != fixture["sms"]["providerScope"]
        or request["senderId"] != fixture["sms"]["senderId"]
    ):
        raise GateError("invalid_send_identity")
    callback = proofs["operations-callback-proof.json"]
    observation = callback["observation"]
    cb = rows["callback_observations"][0]
    retained = checked_digest(cb["canonical_payload"], cb["payload_digest"])
    if (
        retained != observation
        or observation["eventId"] != fixture["ids"]["callback"]
        or observation["attemptId"] != send["attempt_id"]
        or observation["providerOperationKey"] != send["provider_operation_key"]
        or observation["requestDigest"] != send["request_digest"]
        or observation["state"] != "delivered"
        or cb["attempt_id"] != send["attempt_id"]
        or cb["receipt_id"] != callback["receipt"]["receiptId"]
        or not native.exact(callback["newSendCalls"], 0)
    ):
        raise GateError("invalid_callback_identity")
    verified_callback = verify_signed(
        callback["rawBase64"],
        callback["headers"],
        fixture["sms"]["callbackKeyBase64"],
        fixture["sms"]["providerScope"],
        "p2.fake_sms_callback.v1\n",
        cb["accepted_at"],
    )
    if (
        verified_callback != observation
        or cb["first_wire"] != base64.b64decode(callback["rawBase64"]).decode()
        or cb["tenant_id"] != fixture["scope"]["tenantId"]
        or cb["provider"] != fixture["sms"]["providerScope"]["provider"]
        or cb["provider_account_id"] != fixture["sms"]["providerScope"]["providerAccountId"]
    ):
        raise GateError("invalid_callback_identity")
    # Do not convert a carrier callback into an invented ordinary send result.
    if rows["send_results"] or callback["view"]["evidence"]["sendResult"] is not None:
        raise GateError("unknown_send_fact_rewritten")
    return {
        "schemaVersion": 1,
        "originalReceipts": 11,
        "logicalOperationAcceptances": 1,
        "ordinarySendCalls": 1,
        "ordinarySendResults": 0,
        "callbackObservations": 1,
        "syntheticSdkFacts": 2,
        "sourceAndScopeJoins": True,
        "humanHearingClaimed": False,
    }


# Literal closed protocol metadata from approved premeasurement ABI02.
PROOF_KEYS = {
    "operations-callback-proof.json": [
        "schemaVersion",
        "observation",
        "rawBase64",
        "headers",
        "receipt",
        "view",
        "newSendCalls",
    ],
    "operations-dispatch-proof.json": [
        "schemaVersion",
        "before",
        "after",
        "callerCode",
        "logicalOperationAcceptances",
        "possibleProviderCalls",
    ],
    "operations-exercise-proof.json": [
        "schemaVersion",
        "completedGroups",
        "cursor",
        "setupMutations",
        "beforeRead",
        "afterRead",
        "cursorTests",
        "grantTests",
        "httpTests",
        "owners",
        "exporter",
        "zeroCase",
        "noReadWrites",
    ],
    "operations-late-read-proof.json": [
        "schemaVersion",
        "owner",
        "pid",
        "afterForget",
        "afterRelease",
    ],
    "operations-original-context.json": [
        "schemaVersion",
        "status",
        "requestId",
        "context",
        "cursors",
    ],
    "operations-owner-proof.json": ["schema", "caseSchema", "tables", "caseTables"],
    "operations-read-held.json": ["schemaVersion", "owner", "stage", "pid", "readerActive"],
    "operations-reconcile-proof.json": [
        "schemaVersion",
        "result",
        "anchor",
        "response",
        "facts",
        "observations",
        "ledger",
        "operationLookups",
        "newOperationAcceptances",
    ],
    "operations-reopen-proof.json": [
        "schemaVersion",
        "original",
        "fresh",
        "page",
        "before",
        "after",
        "newPrepareCalls",
        "newOperationCalls",
        "newSendCalls",
    ],
    "operations-seed-proof.json": [
        "accepted",
        "sms",
        "reply",
        "sendRequest",
        "sendOutcome",
        "stored",
    ],
    "operations-server-proof.json": [
        "schemaVersion",
        "metrics",
        "diagnostics",
        "preflightReads",
        "preflightIntakeReplay",
        "failedReadRequested",
        "exporterReleased",
        "lateReadHeld",
        "lateReadReleased",
        "finalContextId",
    ],
}

NESTED_KEYS = {
    "collectorMetrics": [
        "started",
        "known",
        "rejected",
        "unavailable",
        "observerDropped",
        "observerFailures",
        "getterFailures",
        "observationsDropped",
        "active",
        "observerPending",
        "getterPending",
        "spansRetained",
    ],
    "cursorTests": [
        "wrongSectionDenied",
        "foreignSourceDenied",
        "foreignScopeDenied",
        "missingAnchorDenied",
        "aheadAnchorDenied",
        "staleCaseDenied",
        "originalPagingPreserved",
    ],
    "exporter": ["beforeRelease", "afterRelease", "intakeReplay"],
    "grantTests": [
        "expiresAt",
        "caseEnteredAt",
        "dbExpiredAt",
        "expiryCode",
        "revokedAt",
        "revokeCode",
        "validAfter",
    ],
    "headers": ["timestamp", "signature"],
    "httpMetrics": ["started", "known", "rejected", "sockets", "handlers"],
    "httpTests": [
        "selectorDenied",
        "duplicateQueryDenied",
        "hostDenied",
        "bodyDenied",
        "methodDenied",
        "operatorDenied",
        "correlatedKnown",
    ],
    "inboxMetrics": [
        "accepted",
        "replayed",
        "rejected",
        "dependencyErrors",
        "overloaded",
        "telemetryFailures",
        "active",
    ],
    "inboxTelemetry": ["observerPending", "observerDropped", "observerFailures"],
    "owners": ["afterAbort", "afterCloseTimeout", "afterRelease", "afterUsefulRead"],
    "readerMetrics": [
        "started",
        "known",
        "denied",
        "invalid",
        "unavailable",
        "overloaded",
        "waiterRejected",
        "active",
    ],
    "serverProofMetrics": ["http", "reader", "telemetry", "inbox", "inboxTelemetry"],
    "signed": ["rawBase64", "headers"],
    "sms": ["signed", "stored"],
    "snapshot": ["schema", "caseSchema", "tables", "caseTables"],
    "zeroCase": ["revision", "sourceRevision", "requestDigest"],
}

BROWSER_REPORT_KEYS = [
    "schemaVersion",
    "status",
    "mode",
    "groups",
    "initial",
    "running",
    "uncertain",
    "known",
    "callback",
    "failed",
    "recovered",
    "forgotten",
    "backendAfterForget",
    "backendAfterRelease",
    "originalReceiptId",
    "originalOperationKey",
    "originalOutboundId",
    "readOnlyControls",
    "actualReadFailure",
    "latePositiveJsDeliveryClaimed",
    "cleanupComplete",
    "pageErrors",
    "unexpectedNetworkRequests",
]

BROWSER_EVIDENCE_KEYS = [
    "schemaVersion",
    "phase",
    "code",
    "telemetryCode",
    "contextObserved",
    "current",
    "asOf",
    "historical",
    "diagnosticsHistorical",
    "ownedClient",
    "actualRequests",
    "cleanupComplete",
    "contextPending",
    "telemetryPending",
    "polling",
    "ticks",
    "readCounts",
    "receipts",
    "operations",
    "outbound",
    "pages",
    "sources",
    "observationCount",
]

SAFE_BROWSER_KEYS = [
    "schemaVersion",
    "status",
    "stage",
    "phase",
    "code",
    "ownedClient",
    "actualRequests",
    "contextPending",
    "telemetryPending",
    "pageErrors",
    "unexpectedNetworkRequests",
]

SAFE_BROWSER_STAGES = [
    "opening",
    "pending_known",
    "running_observed",
    "known_original_operation",
    "source_separation",
    "actual_read_recovered",
    "complete",
]

EXPECTED_MANIFEST = {
    "browserGroups": [
        "durable_joined_timeline_and_scoped_paging",
        "unknown_carrier_and_callback_source_separation",
        "actual_read_failure_retry_export_outage_and_forget_fencing",
    ],
    "budgets": {
        "aggregateCaptureBytes": 524288,
        "cleanupSeconds": 20,
        "contextBytes": 73728,
        "cursorBytes": 2048,
        "directProofBytes": 1048576,
        "errorBytes": 1024,
        "frameBytes": 8192,
        "httpHandlers": 2,
        "httpSockets": 16,
        "inboxActualCalls": 4,
        "inboxPoolConnections": 2,
        "legacyContextBytes": 65536,
        "maximumChildren": 24,
        "normalChildren": 13,
        "readerActualCalls": 2,
        "readersPerProcess": 1,
        "reportBytes": 32768,
        "retainedBytes": 16777216,
        "streamBytes": 8192,
        "telemetryBytes": 16384,
        "telemetryExportOwners": 8,
        "totalSeconds": 240,
    },
    "mutations": "Only explicit fixture seed/revision/revoke/dispatch/callback steps; reads and UI "
    "perform zero business writes",
    "normalChildren": [
        "compile",
        "install",
        "seed",
        "exercise",
        "serve",
        "vite",
        "browser",
        "advance-dispatch",
        "advance-reconcile",
        "advance-callback",
        "verify",
        "reopen",
        "cleanup",
    ],
    "producerFacts": "scripted operation/carrier ports and source-qualified synthetic communication "
    "publication; noRTC/provider qualification",
    "profile": "p2_operations_bounded_v1",
    "schemaTables": [
        "admission",
        "associations",
        "callback_admission",
        "callback_observations",
        "callback_settings",
        "challenges",
        "communication_settings",
        "conversations",
        "dispatch_attempts",
        "dispatch_plans",
        "dispatch_settings",
        "inbox",
        "native_bindings",
        "native_observations",
        "native_responses",
        "native_settings",
        "outbound_routes",
        "outbox_admission",
        "outbox_settings",
        "processing_intents",
        "reply_intents",
        "schema_metadata",
        "send_attempts",
        "send_operations",
        "send_policy_settings",
        "send_recovery_commands",
        "send_recovery_observations",
        "send_results",
        "sender_heads",
    ],
    "schemaVersion": 1,
    "scope": "local read-only operator and scripted producer observations",
    "seed": 40,
    "storageGroups": [
        "fixed_operator_capability_and_current_grant",
        "request_body_and_scope_selector_denied",
        "source_scope_section_cursor_binding",
        "ahead_missing_anchor_and_stale_case_cursor_denied",
        "bounded_get_header_host_body_and_client_framing",
        "durable_accepted_pending_running_projection",
        "uncertain_then_known_after_explicit_observation",
        "ordinary_send_unknown_and_callback_separate",
        "bounded_paging_and_canonical_identity_preserved",
        "read_only_zero_revision_and_non_atomic_as_of",
        "safe_read_error_and_same_read_retry",
        "late_read_fenced_and_close_retains_owner",
        "read_admission_overload_and_later_progress",
        "held_throwing_exporter_isolated_and_bounded",
        "real_safe_span_and_finite_metric_labels",
        "fresh_process_original_projection_and_zero_read_writes",
    ],
    "storageVersion": 7,
}

METRIC_KEYS = {
    "inbox": {
        "accepted",
        "replayed",
        "rejected",
        "dependencyErrors",
        "overloaded",
        "telemetryFailures",
        "active",
    },
    "inbox_telemetry": {"observerPending", "observerDropped", "observerFailures"},
    "operations": {
        "started",
        "known",
        "rejected",
        "unavailable",
        "active",
        "observerPending",
        "observerDropped",
        "observerFailures",
        "getterPending",
        "getterFailures",
        "spansRetained",
        "observationsDropped",
        "readerActive",
        "readerStarted",
        "readerKnown",
        "readerWaiterRejected",
    },
}
EVENT_CODES = {
    "known",
    "invalid_query",
    "access_denied",
    "cursor_stale",
    "overloaded",
    "unavailable",
    "closed",
    "waiter_abandoned",
    "accepted",
    "replayed",
    "rejected",
    "dependency_failure",
    "started",
    "dispatched",
    "uncertain",
    "pending",
    "blocked",
    "exhausted",
    "observer_failed",
    "observer_dropped",
    "InvalidConfiguration",
    "InvalidEvent",
    "AccessDenied",
    "AssociationRequired",
    "AssociationRejected",
    "IdentityConflict",
    "Overloaded",
    "NotFound",
    "StorageUnavailable",
    "AcknowledgementUnknown",
    "SchemaMismatch",
    "CleanupIncomplete",
    "UpgradeRequired",
    "DispatchClaimLost",
    "DispatchUnavailable",
    "OperationConflict",
    "WebhookRejected",
    "invalid_http",
    "body_limit",
    "body_timeout",
    "request_aborted",
    "capacity",
    "unauthorized",
    "not_found",
    "identity_conflict",
    "storage_unavailable",
    "acknowledgement_unknown",
    "closing",
    "cleanup_incomplete",
    "invalid_input",
    "forbidden",
    "idempotency_conflict",
    "capacity_exhausted",
    "dependency_unavailable",
    "communication_known",
    "queued",
    "held",
    "unknown",
    "accepted_by_provider",
    "definitive_not_accepted",
    "route_selected",
    "suppressed",
    "unsuppressed",
    "recovery_known",
    "recovery_unknown",
    "recovery_held",
    "recovery_conflicted",
    "recovery_replayed",
    "lookup_started",
    "retry_started",
    "busy",
    "not_due",
    "not_needed",
    "timeout",
    "context_unavailable",
    "webhook_rejected",
}
UI_PHASES = {"idle", "connecting", "ready", "unavailable", "denied", "closing"}
UI_CODES = {
    "invalid_query",
    "access_denied",
    "cursor_stale",
    "overloaded",
    "unavailable",
    "closed",
    "invalid_response",
    "cleanup_incomplete",
}


def validate_manifest(raw: bytes) -> dict[str, Any]:
    value = decode(raw, MAX_REPORT_BYTES)
    if not native.exact(value, EXPECTED_MANIFEST):
        raise GateError("invalid_manifest")
    return value


def metrics(value: Any, keys: list[str] | set[str]) -> dict[str, Any]:
    value = shape(value, set(keys))
    if any(not counter(v, 9007199254740991) for v in value.values()):
        raise GateError("invalid_metrics")
    return dict(value)


def validate_telemetry(value: Any) -> dict[str, Any]:
    value = shape(
        value,
        {"schemaVersion", "status", "scope", "requestId", "observedAt", "sources", "observations"},
    )
    if (
        not native.exact(value["schemaVersion"], 1)
        or value["status"] != "known"
        or value["scope"] != "process"
        or not uuid(value["requestId"])
    ):
        raise GateError("invalid_telemetry")
    utc(value["observedAt"])
    sources = value["sources"]
    if (
        type(sources) is not list
        or len(sources) != 3
        or [s.get("source") if type(s) is dict else None for s in sources] != list(METRIC_KEYS)
    ):
        raise GateError("invalid_telemetry")
    for source in sources:
        shape(source, {"source", "state", "observedAt", "values"})
        utc(source["observedAt"])
        if (
            source["state"] != "observed"
            or type(source["values"]) is not list
            or len(source["values"]) > 16
        ):
            raise GateError("invalid_telemetry")
        names = set()
        for item in source["values"]:
            shape(item, {"name", "value"})
            if (
                type(item["name"]) is not str
                or item["name"] not in METRIC_KEYS[source["source"]]
                or item["name"] in names
                or not counter(item["value"], 9007199254740991)
            ):
                raise GateError("invalid_telemetry")
            names.add(item["name"])
        if names != METRIC_KEYS[source["source"]]:
            raise GateError("invalid_telemetry")
    events = value["observations"]
    if type(events) is not list or not 1 <= len(events) <= 32:
        raise GateError("invalid_spans")
    for event in events:
        shape(
            event,
            {
                "kind",
                "source",
                "operation",
                "status",
                "code",
                "observedAt",
                "durationMs",
                "requestId",
            },
        )
        if (
            any(
                type(event[k]) is not str for k in ("kind", "source", "operation", "status", "code")
            )
            or event["kind"] not in {"read_span", "producer_log"}
            or event["source"] not in METRIC_KEYS
            or event["operation"] not in {"context", "telemetry", "producer"}
            or event["status"] not in {"ok", "error", "unknown", "rejected", "closed"}
            or event["code"] not in EVENT_CODES
            or not counter(event["durationMs"], 9007199254740991)
        ):
            raise GateError("invalid_spans")
        utc(event["observedAt"])
        if event["kind"] == "read_span":
            if not uuid(event["requestId"]) or event["operation"] == "producer":
                raise GateError("invalid_spans")
        elif event["requestId"] is not None or event["operation"] != "producer":
            raise GateError("invalid_spans")
    if not any(
        e["kind"] == "read_span" and e["operation"] == "context" and e["status"] == "ok"
        for e in events
    ):
        raise GateError("missing_actual_read_span")
    if len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()) > 16384:
        raise GateError("proof_limit")
    return dict(value)


def validate_exercise(proof: dict[str, Any], schema: str, fixture: dict[str, Any]) -> None:
    shape(proof, set(PROOF_KEYS["operations-exercise-proof.json"]))
    if (
        not native.exact(proof["schemaVersion"], 1)
        or not native.exact(proof["completedGroups"], STAGES["exercise"]["completedGroups"])
        or not native.exact(proof["noReadWrites"], True)
    ):
        raise GateError("invalid_exercise")
    if not native.exact(
        proof_snapshot(proof["beforeRead"], schema), proof_snapshot(proof["afterRead"], schema)
    ):
        raise GateError("read_wrote_state")
    for key in ("cursorTests", "httpTests"):
        block = shape(proof[key], set(NESTED_KEYS[key]))
        if any(not native.exact(v, True) for v in block.values()):
            raise GateError("invalid_exercise")
    if (
        type(proof["cursor"]) is not str
        or len(proof["cursor"].encode()) > 2048
        or re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{43}", proof["cursor"]) is None
    ):
        raise GateError("invalid_cursor")
    grant = shape(proof["grantTests"], set(NESTED_KEYS["grantTests"]))
    if (
        not utc(grant["caseEnteredAt"]) < utc(grant["expiresAt"]) <= utc(grant["dbExpiredAt"])
        or grant["expiryCode"] != "access_denied"
        or grant["revokeCode"] != "access_denied"
        or not native.exact(grant["validAfter"], True)
    ):
        raise GateError("invalid_grant_proof")
    utc(grant["revokedAt"])
    bindings = proof["afterRead"]["tables"]["native_bindings"]
    h = digest((fixture["profileId"] + ":expired-binding").encode())
    expired_id = h[:8] + "-" + h[8:12] + "-4" + h[13:16] + "-a" + h[17:20] + "-" + h[20:32]
    # Exact binding names are bound again by the setup publication receipt below.
    mutations = proof["setupMutations"]
    if (
        type(mutations) is not list
        or len(mutations) != 3
        or [m.get("kind") for m in mutations]
        != ["case_revision", "native_binding_publish", "native_binding_revoke"]
    ):
        raise GateError("invalid_setup_mutations")
    expiry_receipt = mutations[1]["receipt"]
    expiry_row = one(bindings, "binding_id", expiry_receipt["bindingId"])
    if datetime.fromisoformat(expiry_row["expires_at"]) != utc(grant["expiresAt"]):
        raise GateError("invalid_grant_proof")
    # Both a fully bound receipt and a matching SQL row are required; no fake timing witness.
    if expiry_receipt["bindingId"] != expired_id:
        raise GateError("invalid_grant_proof")
    owners = shape(proof["owners"], set(NESTED_KEYS["owners"]))
    for key in owners:
        metrics(owners[key], NESTED_KEYS["readerMetrics"])
    if (
        owners["afterAbort"]["active"] != 2
        or owners["afterCloseTimeout"]["active"] != 2
        or owners["afterRelease"]["active"] != 0
        or owners["afterUsefulRead"]["known"] < 1
    ):
        raise GateError("lost_actual_owner")
    exporter = shape(proof["exporter"], set(NESTED_KEYS["exporter"]))
    before = metrics(exporter["beforeRelease"], NESTED_KEYS["collectorMetrics"])
    after = metrics(exporter["afterRelease"], NESTED_KEYS["collectorMetrics"])
    if (
        before["observerPending"] != 8
        or before["observerDropped"] < 1
        or after["observerPending"] != 0
        or after["observerFailures"] != 8
    ):
        raise GateError("invalid_exporter_ownership")
    zero = shape(proof["zeroCase"], set(NESTED_KEYS["zeroCase"]))
    if zero["revision"] != "0" or any(
        type(zero[k]) is not str or re.fullmatch(r"[a-f0-9]{64}", zero[k]) is None
        for k in ("sourceRevision", "requestDigest")
    ):
        raise GateError("invalid_zero_revision")


def validate_browser_context(raw: bytes) -> dict[str, Any]:
    v = shape(decode(raw, 8192), set(SAFE_BROWSER_KEYS))
    if (
        not native.exact(v["schemaVersion"], 1)
        or (type(v["status"]) is not str or v["status"] not in {"passed", "failed"})
        or type(v["stage"]) is not str
        or v["stage"] not in SAFE_BROWSER_STAGES
        or (v["phase"] is not None and (type(v["phase"]) is not str or v["phase"] not in UI_PHASES))
        or (v["code"] is not None and (type(v["code"]) is not str or v["code"] not in UI_CODES))
    ):
        raise GateError("invalid_browser_context")
    for k, maximum in (("ownedClient", 1), ("actualRequests", 2)):
        if v[k] is not None and not counter(v[k], maximum):
            raise GateError("invalid_browser_context")
    if any(
        v[k] is not None and type(v[k]) is not bool for k in ("contextPending", "telemetryPending")
    ) or any(not counter(v[k], 1000000) for k in ("pageErrors", "unexpectedNetworkRequests")):
        raise GateError("invalid_browser_context")
    return v


def validate_browser_evidence(value: Any) -> dict[str, Any]:
    value = shape(value, set(BROWSER_EVIDENCE_KEYS))
    if (
        not native.exact(value["schemaVersion"], 1)
        or type(value["phase"]) is not str
        or value["phase"] not in UI_PHASES
    ):
        raise GateError("invalid_browser_report")
    for k in ("code", "telemetryCode"):
        if value[k] is not None and (type(value[k]) is not str or value[k] not in UI_CODES):
            raise GateError("invalid_browser_report")
    for k in (
        "contextObserved",
        "current",
        "historical",
        "diagnosticsHistorical",
        "cleanupComplete",
        "contextPending",
        "telemetryPending",
        "polling",
    ):
        if type(value[k]) is not bool:
            raise GateError("invalid_browser_report")
    if value["asOf"] is not None:
        utc(value["asOf"])
    for k, maximum in (
        ("ownedClient", 1),
        ("actualRequests", 2),
        ("ticks", 30),
        ("observationCount", 32),
    ):
        if not counter(value[k], maximum):
            raise GateError("invalid_browser_report")
    metrics(value["readCounts"], {"context", "telemetry", "settled", "abandoned"})
    pages = metrics(value["pages"], {"history", "work", "responses", "replies"})
    if any(v > 32 for v in pages.values()):
        raise GateError("invalid_browser_report")
    for field, keys in (
        ("receipts", {"receiptId", "processingState", "operationKey"}),
        ("operations", {"operationKey", "state"}),
        ("outbound", {"outboundId", "result", "callbacks"}),
        ("sources", {"source", "state", "metricCount"}),
    ):
        if type(value[field]) is not list or len(value[field]) > (8 if field == "sources" else 32):
            raise GateError("invalid_browser_report")
        seen = set()
        for row in value[field]:
            shape(row, keys)
            if field == "sources":
                if (
                    type(row["source"]) is not str
                    or row["source"] not in METRIC_KEYS
                    or type(row["state"]) is not str
                    or row["state"] not in {"observed", "pending", "unavailable"}
                    or not counter(row["metricCount"], 16)
                ):
                    raise GateError("invalid_browser_report")
                key = row["source"]
            elif field == "outbound":
                key = row["outboundId"]
                if (
                    not uuid(key)
                    or type(row["result"]) is not str
                    or row["result"]
                    not in {"unknown", "not_observed", "accepted", "definitive_failure"}
                    or type(row["callbacks"]) is not list
                    or len(row["callbacks"]) > 32
                    or any(
                        type(c) is not str
                        or c
                        not in {
                            "accepted_by_provider",
                            "delivered",
                            "failed",
                            "unknown",
                            "read_reported",
                        }
                        for c in row["callbacks"]
                    )
                ):
                    raise GateError("invalid_browser_report")
            else:
                key = row["receiptId"] if field == "receipts" else row["operationKey"]
                state = row["processingState"] if field == "receipts" else row["state"]
                if (
                    not uuid(key)
                    or (field == "receipts" and not uuid(row["operationKey"]))
                    or type(state) is not str
                    or state
                    not in {"pending", "running", "dispatched", "uncertain", "blocked", "exhausted"}
                ):
                    raise GateError("invalid_browser_report")
            if key in seen:
                raise GateError("invalid_browser_report")
            seen.add(key)
    return dict(value)


def validated_browser(
    raw: bytes, fixture: dict[str, Any], selected: dict[str, Any]
) -> dict[str, Any]:
    v = shape(decode(raw, MAX_REPORT_BYTES), set(BROWSER_REPORT_KEYS))
    fixed = {
        "schemaVersion": 1,
        "status": "passed",
        "mode": "local_scripted_p2_operations_browser",
        "groups": list(BROWSER_GROUPS),
        "originalReceiptId": selected["receiptId"],
        "originalOperationKey": selected["operationKey"],
        "originalOutboundId": fixture["ids"]["outbound"],
        "readOnlyControls": True,
        "actualReadFailure": True,
        "latePositiveJsDeliveryClaimed": False,
        "cleanupComplete": True,
        "pageErrors": 0,
        "unexpectedNetworkRequests": 0,
        "backendAfterForget": {"readerActive": 1},
        "backendAfterRelease": {"readerActive": 0},
    }
    if any(not native.exact(v[k], expected) for k, expected in fixed.items()):
        raise GateError("invalid_browser_report")
    for name in (
        "initial",
        "running",
        "uncertain",
        "known",
        "callback",
        "failed",
        "recovered",
        "forgotten",
    ):
        validate_browser_evidence(v[name])
    for name, state in (
        ("initial", "pending"),
        ("running", "running"),
        ("uncertain", "uncertain"),
        ("known", "dispatched"),
        ("callback", "dispatched"),
        ("failed", "dispatched"),
        ("recovered", "dispatched"),
    ):
        row = one(v[name]["receipts"], "receiptId", selected["receiptId"])
        if row["operationKey"] != selected["operationKey"] or row["processingState"] != state:
            raise GateError("invalid_browser_identity")
    for name in ("initial", "running", "uncertain"):
        if (
            one(v[name]["operations"], "operationKey", selected["operationKey"])["state"]
            != {"initial": "pending", "running": "running", "uncertain": "uncertain"}[name]
        ):
            raise GateError("invalid_browser_identity")
    for name in ("known", "callback", "failed", "recovered"):
        if any(r["operationKey"] == selected["operationKey"] for r in v[name]["operations"]):
            raise GateError("invalid_browser_identity")
    for name in ("initial", "known", "callback", "failed", "recovered"):
        outbound = one(v[name]["outbound"], "outboundId", fixture["ids"]["outbound"])
        if (
            outbound["result"] != "unknown"
            or (name == "initial" and outbound["callbacks"])
            or (
                name in {"callback", "failed", "recovered"}
                and "delivered" not in outbound["callbacks"]
            )
        ):
            raise GateError("unknown_send_fact_rewritten")
    if (
        v["failed"]["code"] != "unavailable"
        or not v["failed"]["historical"]
        or v["failed"]["current"]
        or v["failed"]["polling"]
        or v["recovered"]["code"] is not None
        or not v["recovered"]["current"]
        or v["recovered"]["historical"]
    ):
        raise GateError("invalid_browser_recovery")
    forgotten = v["forgotten"]
    if (
        forgotten["contextObserved"]
        or forgotten["asOf"] is not None
        or any(forgotten[k] for k in ("receipts", "operations", "outbound", "sources"))
        or forgotten["ownedClient"] != 0
        or forgotten["actualRequests"] != 0
        or not forgotten["cleanupComplete"]
    ):
        raise GateError("stale_browser_fact")
    return v


def _validate_bundle(
    work: Path, snapshots: dict[str, Any], fixture: dict[str, Any], schema: str, serve_pid: int
) -> dict[str, Any]:
    proofs: dict[str, Any] = {
        name: (
            decode_array(bounded_read(work / name))
            if name == "operations-provider-ledger.json"
            else json_file(work / name)
        )
        for name in PROOF_FILES
        if name.endswith(".json") and not name.startswith("browser/")
    }
    for name, keys in PROOF_KEYS.items():
        shape(proofs[name], set(keys))
    for name, v in proofs.items():
        if name not in {
            "operations-seed-proof.json",
            "operations-owner-proof.json",
            "operations-provider-ledger.json",
        } and not native.exact(v["schemaVersion"], 1):
            raise GateError("invalid_proof")
    validate_exercise(proofs["operations-exercise-proof.json"], schema, fixture)
    identity = validate_owner_joins(proofs, snapshots["after_verify"], fixture, schema)
    if (
        not native.exact(snapshots["after_callback"], snapshots["after_browser"])
        or not native.exact(snapshots["after_browser"], snapshots["after_verify"])
        or not native.exact(snapshots["after_verify"], snapshots["after_reopen"])
    ):
        raise GateError("read_wrote_state")
    reopened = proofs["operations-reopen-proof.json"]
    if (
        not native.exact(proof_snapshot(reopened["before"], schema), snapshots["after_verify"])
        or not native.exact(proof_snapshot(reopened["after"], schema), snapshots["after_reopen"])
        or any(
            not native.exact(reopened[k], 0)
            for k in ("newPrepareCalls", "newOperationCalls", "newSendCalls")
        )
    ):
        raise GateError("invalid_reopen")
    original = proofs["operations-original-context.json"]
    for key in ("access", "case", "history", "work", "responses", "replies"):
        if not native.exact(original["context"][key], reopened["fresh"]["context"][key]):
            raise GateError("original_facts_changed")
    if reopened["original"] != original["context"]["contextId"]:
        raise GateError("invalid_reopen")
    for name, expected in (
        (
            "operations-read-held.json",
            {
                "schemaVersion": 1,
                "owner": fixture["owner"],
                "stage": "read-held",
                "pid": serve_pid,
                "readerActive": 1,
            },
        ),
        (
            "operations-late-read-proof.json",
            {
                "schemaVersion": 1,
                "owner": fixture["owner"],
                "pid": serve_pid,
                "afterForget": {"readerActive": 1},
                "afterRelease": {"readerActive": 0},
            },
        ),
    ):
        if not native.exact(proofs[name], expected):
            raise GateError("lost_actual_owner")
    server = proofs["operations-server-proof.json"]
    for key in ("failedReadRequested", "exporterReleased", "lateReadHeld", "lateReadReleased"):
        if not native.exact(server[key], True):
            raise GateError("invalid_server_proof")
    if (
        not native.exact(server["preflightReads"], 12)
        or server["finalContextId"] != original["context"]["contextId"]
    ):
        raise GateError("invalid_server_proof")
    selected = proofs["operations-seed-proof.json"]["accepted"][0]
    for replay in (
        server["preflightIntakeReplay"],
        proofs["operations-exercise-proof.json"]["exporter"]["intakeReplay"],
    ):
        if (
            replay["status"] != "replayed"
            or replay["receiptId"] != selected["receiptId"]
            or replay["operationKey"] != selected["operationKey"]
        ):
            raise GateError("invalid_replay")
    ms = shape(server["metrics"], set(NESTED_KEYS["serverProofMetrics"]))
    for key, contract in (
        ("http", "httpMetrics"),
        ("reader", "readerMetrics"),
        ("telemetry", "collectorMetrics"),
        ("inbox", "inboxMetrics"),
        ("inboxTelemetry", "inboxTelemetry"),
    ):
        metrics(ms[key], NESTED_KEYS[contract])
    if (
        any(
            ms[part][field] != 0
            for part, field in (
                ("http", "sockets"),
                ("http", "handlers"),
                ("reader", "active"),
                ("telemetry", "active"),
                ("telemetry", "observerPending"),
                ("telemetry", "getterPending"),
                ("inbox", "active"),
                ("inboxTelemetry", "observerPending"),
            )
        )
        or ms["reader"]["known"] < 12
        or ms["telemetry"]["observerDropped"] < 1
        or ms["telemetry"]["observerFailures"] < 1
    ):
        raise GateError("lost_actual_owner")
    validate_telemetry(server["diagnostics"])
    browser = validated_browser(
        bounded_read(work / "browser/operations-browser-observations.json", MAX_REPORT_BYTES),
        fixture,
        selected,
    )
    safe = validate_browser_context(
        bounded_read(work / "browser/operations-browser-context.json", 8192)
    )
    if safe["status"] != "passed" or safe["stage"] != "complete":
        raise GateError("invalid_browser_context")
    for name in ("operations-ready.png", "operations-recovered.png"):
        raw = bounded_read(work / "browser" / name)
        if (
            raw[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
            or int.from_bytes(raw[16:20], "big") != 1440
            or not 1 <= int.from_bytes(raw[20:24], "big") <= 20000
        ):
            raise GateError("invalid_screenshot")
    return {
        "schemaVersion": 1,
        "identity": identity,
        "storageGroups": list(CASE_NAMES),
        "browserGroups": browser["groups"],
        "sameOriginalFactsAfterReopen": True,
        "independentReadSnapshotsUnchanged": True,
        "sqlWaiterGraphs": 0,
        "actualTelemetrySources": list(METRIC_KEYS),
        "syntheticSdkPublicationOnly": True,
    }


def compiler_inputs(project: Path, work: Path) -> list[Path]:
    result = []
    for label, origin, out in (
        ("production", "tsconfig.json", project / "dist"),
        ("pg", "tsconfig.pg.json", work / "compiled"),
        ("examples", "tsconfig.examples.json", project / "dist/examples"),
    ):
        path = work / ("compiler-" + label + ".json")
        native.write_json(
            path,
            {
                "extends": str(project / origin),
                "compilerOptions": {
                    "outDir": str(out),
                    "tsBuildInfoFile": str(work / (label + ".tsbuildinfo")),
                },
            },
        )
        result.append(path)
    return result


def validated_report(raw: bytes) -> dict[str, Any]:
    v = decode(raw, MAX_REPORT_BYTES)
    fixed = {
        "schema_version": 1,
        "status": "passed",
        "mode": MODE,
        "tests": 16,
        "passed": 16,
        "storage_cases": list(CASE_NAMES),
        "browser_groups": list(BROWSER_GROUPS),
        "browser_tests": 1,
        "child_commands": 13,
        "operation_acceptances": 1,
        "ordinary_send_calls": 1,
        "ordinary_send_results": 0,
        "callback_observations": 1,
        "sql_waiter_graphs": 0,
        "sfu_calls": 0,
        "provider_calls": 0,
        "cleanup_complete": True,
        "node_version": "24.22.2",
    }
    if set(v) != set(fixed) | {"duration_seconds", "retained_index_sha256", "proofs"} or any(
        not native.exact(v[k], expected) for k, expected in fixed.items()
    ):
        raise GateError("invalid_report")
    duration = v["duration_seconds"]
    if type(duration) not in {int, float}:
        raise GateError("invalid_report")
    try:
        if not math.isfinite(duration) or not 0 < duration <= TOTAL_SECONDS:
            raise ValueError
    except (ValueError, OverflowError):
        raise GateError("invalid_report") from None
    if (
        type(v["retained_index_sha256"]) is not str
        or re.fullmatch(r"[a-f0-9]{64}", v["retained_index_sha256"]) is None
        or type(v["proofs"]) is not dict
        or set(v["proofs"]) != set(PROOF_FILES) | set(PARENT_PROOF_FILES)
    ):
        raise GateError("invalid_report")
    for descriptor in v["proofs"].values():
        shape(descriptor, {"bytes", "sha256"})
        if (
            not counter(descriptor["bytes"], MAX_PROOF_BYTES, 1)
            or type(descriptor["sha256"]) is not str
            or re.fullmatch(r"[a-f0-9]{64}", descriptor["sha256"]) is None
        ):
            raise GateError("invalid_report")
    return v


async def wait_private_file(path: Path, child: OwnedProcess, deadline: float) -> bytes:
    while True:
        native.remaining(deadline)
        try:
            info = path.lstat()
            # A complete no-overwrite hardlink may briefly have two links before its
            # owned pending name is unlinked. Never treat another unsafe shape as absence.
            if (
                stat.S_ISREG(info.st_mode)
                and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o600
                and info.st_nlink == 2
            ):
                await asyncio.sleep(0.005)
                continue
            return bounded_read(path)
        except FileNotFoundError:
            if child.returncode is not None:
                raise GateError("child_failed") from None
            await asyncio.sleep(0.005)


async def cleanup_dependencies(
    children: Children, actual: ActualCalls, final: float, schema_cleanup: Callable[[], Any] | None
) -> bool:
    complete = True
    try:
        await asyncio.to_thread(children.close)
    except BaseException:  # noqa: BLE001 - Attempt every owned group; actual truth gates downstream cleanup.
        complete = False
    try:
        if not await actual.drain(final) or not owned_children_settled(children):
            complete = False
    except BaseException:  # noqa: BLE001 - Another owner must still be observed after cancellation.
        complete = False
    if complete and schema_cleanup is not None:
        children.deadline = final
        try:
            await actual.call(schema_cleanup)
        except BaseException:  # noqa: BLE001 - Preserve primary and keep the marked work on cleanup failure.
            complete = False
    try:
        await asyncio.to_thread(children.close)
    except BaseException:  # noqa: BLE001 - Reobserve cleanup child plus all independent groups.
        complete = False
    try:
        calls_settled = await actual.close(final)
    except BaseException:  # noqa: BLE001 - Retain unknown host calls, never infer settlement.
        calls_settled = False
    return complete and calls_settled and owned_children_settled(children)


async def run(
    root: Path,
    artifacts: Path,
    started: float,
    cleanup: dict[str, bool],
    browser_executable: str | None = None,
) -> dict[str, Any]:
    import aiohttp
    import psycopg

    final = started + TOTAL_SECONDS
    deadline = final - CLEANUP_SECONDS
    frozen = source_snapshot(root)
    native.write_json(artifacts / "source-before.json", frozen, maximum=MAX_PROOF_BYTES)
    setup = core.load_setup(root)
    settings = setup.load_settings()
    node, corepack = shutil.which("node"), shutil.which("corepack")
    if not node or not corepack:
        raise GateError("missing_setup")
    if browser_executable is not None and (
        not Path(browser_executable).is_absolute() or not Path(browser_executable).is_file()
    ):
        raise GateError("invalid_browser_executable")
    project = root / "projects/channel-continuity"
    scratch = project / ".local/operations"
    core.private_directory(scratch)
    work = Path(tempfile.mkdtemp(prefix="run-", dir=scratch)).resolve()
    work.chmod(0o700)
    fixture = make_fixture()
    schema = "p2_operations_" + fixture["owner"]
    owned = {"schemaVersion": 1, "owner": fixture["owner"], "schemas": list(schemas(schema))}
    native.write_json(work / "operations-owned-work.json", owned)
    native.write_json(work / "fixture.json", fixture)
    browser_output = work / "browser"
    browser_output.mkdir(mode=0o700)
    forbidden = (
        *fixture_secrets(fixture, settings),
        *(settings[k] for k in setup.SECRET_KEYS if settings.get(k)),
    )
    children = Children(child_capture_root(work), deadline, final_deadline=final)
    actual = ActualCalls()
    barriers = {
        k: FileBarrier(work, k) for k in ("operations_ready", "operations_dispatch_entered")
    }
    common = {
        "P2_OPERATIONS_DIRECTORY": str(work),
        "P2_OPERATIONS_SCHEMA": schema,
        "P2_OPERATIONS_PG_PORT": settings["POSTGRES_PORT"],
    }
    script = work / "compiled/tests/pg_operations_cases.js"
    snapshots: dict[str, Any] = {}
    stages: dict[str, bytes] = {}
    attempted = False
    first: BaseException | None = None
    joined: dict[str, Any] | None = None
    serve: OwnedProcess | None = None
    vite: OwnedProcess | None = None
    serve_pid = 0
    retained_ok = True

    def connect() -> Any:
        return psycopg.connect(
            host="127.0.0.1",
            port=int(settings["POSTGRES_PORT"]),
            dbname="livekit_lab",
            user="continuity_migrator",
            password=settings["POSTGRES_MIGRATION_PASSWORD"],
            sslmode="disable",
            connect_timeout=2,
            options="-c search_path=pg_catalog -c statement_timeout=3000 -c lock_timeout=1500 -c timezone=UTC",
            autocommit=True,
        )

    async def capture(label: str) -> None:
        snapshots[label] = await actual.call(independent_snapshot, connect, schema)

    def stage_sync(mode: str, end: float = deadline) -> dict[str, Any]:
        raw = children.call(
            mode,
            [node, str(script), mode],
            child_environment(settings, common, mode),
            cwd=work,
            deadline=end,
        )
        result = validated_stage(raw, mode)
        stages[mode] = raw
        return result

    async def stage(mode: str) -> dict[str, Any]:
        return await actual.call(stage_sync, mode)

    async def marker(name: str, browser: OwnedProcess) -> None:
        raw = await wait_private_file(work / ("operations-" + name + ".json"), browser, deadline)
        validated_marker(raw, name, fixture["owner"])

    try:
        configs = compiler_inputs(project, work)
        await actual.call(
            children.call,
            "compile",
            [
                node,
                str(project / "node_modules/typescript/lib/tsc.js"),
                "--build",
                *[str(p) for p in configs],
            ],
            core.base_environment(),
            cwd=root,
        )
        parity = verify_runtime_build(project, work / "compiled")
        for file in configs:
            copy_private(file, artifacts / file.name, forbidden, maximum=4096)
        native.write_json(artifacts / "runtime-build-proof.json", parity, maximum=MAX_PROOF_BYTES)
        attempted = True
        await stage("install")
        await stage("seed")
        await capture("after_seed")
        await stage("exercise")
        await capture("after_exercise")
        seed = json_file(work / "operations-seed-proof.json")
        selected = seed["accepted"][0]
        serve = children.start(
            "serve",
            [node, str(script), "serve"],
            child_environment(settings, common, "serve"),
            cwd=work,
        )
        serve_pid = serve.pid
        await actual.call(
            serve.wait_for_barrier,
            barriers["operations_ready"],
            timeout=min(30, native.remaining(deadline)),
        )
        port = endpoint(work / "operations-endpoint.json", serve.pid)
        ui_port = native.free_port()
        vite_env = {**core.base_environment(), "P2_OPERATIONS_API_PORT": str(port)}
        vite = children.start(
            "vite",
            [
                corepack,
                "pnpm",
                "--filter",
                "@livekit-ecosystem/local-console",
                "exec",
                "vite",
                "--host",
                "127.0.0.1",
                "--port",
                str(ui_port),
                "--strictPort",
                "--config",
                "vite.operations.config.ts",
            ],
            vite_env,
            cwd=root,
        )
        origin = "http://127.0.0.1:" + str(ui_port)
        async with aiohttp.ClientSession(
            trust_env=False, timeout=aiohttp.ClientTimeout(total=2)
        ) as session:
            while True:
                native.remaining(deadline)
                if vite.returncode is not None:
                    raise GateError("child_failed")
                try:
                    async with session.get(
                        origin + "/p2-operations.html", allow_redirects=False
                    ) as response:
                        body = await response.content.read(8193)
                        if (
                            response.status == 200
                            and len(body) <= 8192
                            and b"/src/p2-operations.ts" in body
                        ):
                            break
                except (aiohttp.ClientError, TimeoutError):
                    pass
                await asyncio.sleep(0.02)
        env = {
            **core.base_environment(),
            "P2_OPERATIONS_BROWSER_ORIGIN": origin,
            "P2_OPERATIONS_BROWSER_OUTPUT": str(browser_output),
            "P2_OPERATIONS_BROWSER_ACCESS": fixture["operatorAuthorization"][7:],
            "P2_OPERATIONS_DIRECTORY": str(work),
            "P2_OPERATIONS_OWNER": fixture["owner"],
            "P2_OPERATIONS_RECEIPT_ID": selected["receiptId"],
            "P2_OPERATIONS_OPERATION_KEY": selected["operationKey"],
            "P2_OPERATIONS_OUTBOUND_ID": fixture["ids"]["outbound"],
        }
        if browser_executable is not None:
            env["PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"] = browser_executable
        browser = children.start(
            "browser",
            [
                corepack,
                "pnpm",
                "--filter",
                "@livekit-ecosystem/local-console",
                "exec",
                "playwright",
                "test",
                "--config",
                "playwright.operations.config.ts",
            ],
            env,
            cwd=root,
        )
        await marker("request-dispatch", browser)
        dispatch = children.start(
            "advance-dispatch",
            [node, str(script), "advance-dispatch"],
            child_environment(settings, common, "advance-dispatch"),
            cwd=work,
        )
        await actual.call(
            dispatch.wait_for_barrier,
            barriers["operations_dispatch_entered"],
            timeout=min(30, native.remaining(deadline)),
        )
        await marker("dispatch-running", browser)
        dispatch.release_barrier(barriers["operations_dispatch_entered"])
        stages["advance-dispatch"] = await actual.call(children.finish, dispatch)
        validated_stage(stages["advance-dispatch"], "advance-dispatch")
        await capture("after_dispatch")
        await marker("request-reconcile", browser)
        await stage("advance-reconcile")
        await capture("after_reconcile")
        await marker("request-callback", browser)
        await stage("advance-callback")
        await capture("after_callback")
        for name in (
            "read-failure",
            "release-exporter",
            "hold-read",
            "release-read",
            "browser-finished",
        ):
            await marker(name, browser)
        await actual.call(children.finish, browser)
        # The serve fixture observes browser-finished and drains actual app owners itself.
        stages["serve"] = await actual.call(children.finish, serve)
        validated_stage(stages["serve"], "serve")
        await actual.call(children.stop, vite, deadline=deadline, require_zero=False)
        await capture("after_browser")
        await stage("verify")
        await capture("after_verify")
        await stage("reopen")
        await capture("after_reopen")
        joined = validate_bundle(work, snapshots, fixture, schema, serve_pid)
        write_snapshot_proofs(artifacts, snapshots, schema)
        if not native.exact(validate_snapshot_proofs(artifacts, schema), snapshots):
            raise GateError("snapshot_retention_changed")
        native.write_json(
            artifacts / "gate-independent-joins.json", joined, maximum=MAX_PROOF_BYTES
        )
        for name in PROOF_FILES:
            path = artifacts / name
            path.parent.mkdir(mode=0o700, exist_ok=True)
            copy_private(work / name, path, forbidden, maximum=MAX_PROOF_BYTES)
    except BaseException as error:  # noqa: BLE001 - Keep primary while every real owner is drained.
        first = error
    finally:
        # Stop all actual children before any cleanup DDL; unknown groups retain work.
        complete = await cleanup_dependencies(
            children, actual, final, (lambda: stage_sync("cleanup", final)) if attempted else None
        )
        for child in children.children:
            for stream in ("stdout", "stderr"):
                try:
                    raw = bounded_read(
                        child.output_directory / (stream + ".bin"),
                        MAX_STREAM_BYTES,
                        allow_empty=True,
                    )
                    # Raw browser/Node failure text is intentionally never published.
                    retain = child.output_directory.name in {"compile", "vite"} or (
                        stream == "stdout" and child.output_directory.name in stages
                    )
                    if retain:
                        exclude_private(raw, forbidden)
                        native.write_json(
                            artifacts
                            / ("capture-" + child.output_directory.name + "-" + stream + ".json"),
                            {
                                "schemaVersion": 1,
                                "bytes": len(raw),
                                "sha256": digest(raw),
                                "retained": False,
                            },
                        )
                        if child.output_directory.name in stages and stream == "stdout":
                            validated_stage(raw, child.output_directory.name)
                            copy_private(
                                child.output_directory / (stream + ".bin"),
                                artifacts / ("stage-" + child.output_directory.name + ".json"),
                                forbidden,
                                maximum=MAX_STREAM_BYTES,
                            )
                except BaseException:  # noqa: BLE001 - Diagnostics must not replace primary or skip another owner.
                    retained_ok = False
        try:
            for mode in MODES:
                path = work / ("operations-failure-" + mode + ".json")
                if path.exists():
                    diagnostic = validate_node_failure(bounded_read(path, 8192), mode)
                    native.write_json(artifacts / path.name, diagnostic)
            context = work / "browser/operations-browser-context.json"
            if context.exists():
                safe = validate_browser_context(bounded_read(context, 8192))
                native.write_json(artifacts / "operations-browser-context.json", safe)
            native.write_json(
                artifacts / "owned-children.json",
                {
                    "schemaVersion": 1,
                    "commands": [
                        {
                            "name": c.output_directory.name,
                            "pid": c.pid,
                            "returncode": c.returncode,
                            "cleanupFailed": c.cleanup_failed,
                            "groupSettled": getattr(c, "group_settled", False),
                            "streams": {
                                s: {
                                    "bytes": len(
                                        bounded_read(
                                            c.output_directory / (s + ".bin"),
                                            MAX_STREAM_BYTES,
                                            allow_empty=True,
                                        )
                                    ),
                                    "sha256": digest(
                                        bounded_read(
                                            c.output_directory / (s + ".bin"),
                                            MAX_STREAM_BYTES,
                                            allow_empty=True,
                                        )
                                    ),
                                }
                                for s in ("stdout", "stderr")
                            },
                        }
                        for c in children.children
                    ],
                    "allOwnedChildrenSettled": owned_children_settled(children),
                },
            )
        except BaseException:  # noqa: BLE001 - Preserve first failure and marked work if evidence cannot be retained.
            retained_ok = False
        cleanup["cleanup_complete"] = complete and retained_ok
        if cleanup["cleanup_complete"]:
            try:
                if work.parent != scratch.resolve() or not native.exact(
                    json_file(work / "operations-owned-work.json"), owned
                ):
                    raise GateError("unsafe_owned_work")
                private_directory(work)
                for data in physical_files(artifacts).values():
                    exclude_private(data, forbidden)
                shutil.rmtree(work)
            except BaseException as error:  # noqa: BLE001 - Do not erase primary; removal is source-bound and ownership-gated.
                cleanup["cleanup_complete"] = False
                first = first or error
        if not cleanup["cleanup_complete"]:
            try:
                native.write_json(
                    artifacts / "owned-work-retained.json",
                    {
                        "schemaVersion": 1,
                        "directory": str(work.relative_to(root)),
                        "schemas": list(schemas(schema)),
                        "cleanupComplete": False,
                    },
                )
            except BaseException:  # noqa: BLE001 - Retention failure cannot replace the primary.
                cleanup["cleanup_complete"] = False
            first = first or GateError("cleanup_incomplete")
    if first is not None:
        raise first
    after = source_snapshot(root)
    native.write_json(artifacts / "source-after.json", after, maximum=MAX_PROOF_BYTES)
    if after != frozen:
        raise GateError("source_changed_during_measurement")
    if children.count != EXPECTED_CHILDREN or [
        c.output_directory.name for c in children.children
    ] != list(NORMAL_COMMANDS):
        raise GateError("unexpected_child_count")
    for data in physical_files(artifacts).values():
        exclude_private(data, forbidden)
    evidence_index(artifacts)
    index_sha = digest(bounded_read(artifacts / "retained-index.json"))
    validate_evidence_index(artifacts, index_sha)
    descriptors = {
        name: {
            "bytes": len(bounded_read(artifacts / name)),
            "sha256": digest(bounded_read(artifacts / name)),
        }
        for name in (*PROOF_FILES, *PARENT_PROOF_FILES)
    }
    return validated_report(
        json.dumps(
            {
                "schema_version": 1,
                "status": "passed",
                "mode": MODE,
                "tests": 16,
                "passed": 16,
                "storage_cases": list(CASE_NAMES),
                "browser_groups": list(BROWSER_GROUPS),
                "browser_tests": 1,
                "child_commands": 13,
                "operation_acceptances": 1,
                "ordinary_send_calls": 1,
                "ordinary_send_results": 0,
                "callback_observations": 1,
                "sql_waiter_graphs": 0,
                "sfu_calls": 0,
                "provider_calls": 0,
                "cleanup_complete": True,
                "node_version": "24.22.2",
                "duration_seconds": time.monotonic() - started,
                "retained_index_sha256": index_sha,
                "proofs": descriptors,
            }
        ).encode()
    )


def copy_private(
    source: Path, target: Path, forbidden: tuple[str, ...], *, maximum: int = MAX_PROOF_BYTES
) -> None:
    raw = bounded_read(source, maximum)
    exclude_private(raw, forbidden)
    with os.fdopen(
        os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb"
    ) as output:
        output.write(raw)


def validate_bundle(
    work: Path, snapshots: dict[str, Any], fixture: dict[str, Any], schema: str, serve_pid: int
) -> dict[str, Any]:
    try:
        return _validate_bundle(work, snapshots, fixture, schema, serve_pid)
    except (KeyError, TypeError, AttributeError, ValueError, OverflowError, IndexError):
        raise GateError("invalid_proof_bundle") from None


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    started = time.monotonic()
    cleanup = {"cleanup_complete": False}
    target = None
    try:
        argsv = list(sys.argv[1:] if argv is None else argv)
        for flag in ("--report", "--plan", "--browser-executable"):
            if sum(a.split("=", 1)[0] == flag for a in argsv) > 1:
                raise GateError("invalid_arguments")
        parser = SafeParser(description=__doc__)
        parser.add_argument("--report", type=Path)
        parser.add_argument("--plan", action="store_true")
        parser.add_argument("--browser-executable")
        args = parser.parse_args(argsv)
        if args.plan:
            if args.report is not None or args.browser_executable is not None:
                raise GateError("invalid_arguments")
            print(json.dumps(plan(root), sort_keys=True))
            return 0
        validate_manifest(
            storage.source_bytes(root / "projects/channel-continuity/operations/bounded-v1.json")
        )
        target = target_path(
            root, args.report or Path(".local/validation/p2-operations/" + uuid4().hex + ".json")
        )
        artifacts = target.with_name(target.stem + "-artifacts")
        artifacts.mkdir(mode=0o700)
        result = asyncio.run(run(root, artifacts, started, cleanup, args.browser_executable))
    except (native.GateError, core.GateError) as error:
        result = {
            "schema_version": 1,
            "status": "failed",
            "mode": MODE,
            "code": error.code,
            "duration_seconds": time.monotonic() - started,
            **cleanup,
        }
    except BaseException:  # noqa: BLE001 - No arbitrary dependency message, stack or argument is retained.
        result = {
            "schema_version": 1,
            "status": "failed",
            "mode": MODE,
            "code": "gate_failed",
            "duration_seconds": time.monotonic() - started,
            **cleanup,
        }
    try:
        if target is not None:
            native.write_json(target, result)
    except (OSError, native.GateError):
        result = {
            "schema_version": 1,
            "status": "failed",
            "mode": MODE,
            "code": "evidence_not_retained",
            **cleanup,
        }
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


def verify_runtime_build(project: Path, compiled: Path) -> dict[str, Any]:
    source = project / "src"
    expected = {
        p.relative_to(source).with_suffix(".js")
        for p in source.rglob("*.ts")
        if not p.name.endswith(".d.ts")
    }
    ancillary = {
        Path("examples/" + name)
        for name in (
            "fake-carrier.js",
            "operations-lab.js",
            "standalone-channel.js",
            "standalone/application.js",
            "standalone/config.js",
            "standalone/external-http.js",
            "standalone/receipt-store.js",
        )
    }
    actual = {p.relative_to(project / "dist") for p in (project / "dist").rglob("*.js")}
    declarations = {p.relative_to(project / "dist") for p in (project / "dist").rglob("*.d.ts")}
    if (
        not expected
        or len(expected) > 128
        or actual != expected | ancillary
        or declarations
        != {p.with_suffix(".d.ts") for p in expected}
        | {
            Path("examples/standalone/" + name + ".d.ts")
            for name in ("application", "config", "external-http", "receipt-store")
        }
        or {p.relative_to(compiled / "src") for p in (compiled / "src").rglob("*.js")} != expected
    ):
        raise GateError("runtime_build_mismatch")
    result = {}
    for name in sorted(expected):
        raw = storage.source_bytes(compiled / "src" / name)
        if raw != storage.source_bytes(project / "dist" / name):
            raise GateError("runtime_build_mismatch")
        result[name.as_posix()] = {
            "source_sha256": digest(storage.source_bytes(source / name.with_suffix(".ts"))),
            "runtime_sha256": digest(raw),
            "declaration_sha256": digest(
                storage.source_bytes(project / "dist" / name.with_suffix(".d.ts"))
            ),
        }
    example = Path("examples/operations-lab.js")
    if storage.source_bytes(compiled / example) != storage.source_bytes(project / "dist" / example):
        raise GateError("runtime_build_mismatch")
    return {
        "schemaVersion": 1,
        "status": "passed",
        "runtimeFiles": len(expected),
        "declarationFiles": len(declarations),
        "sourceCompiledPublicDistEqual": True,
        "files": result,
        "operationsExample": {
            "source_sha256": digest(storage.source_bytes(project / "examples/operations-lab.ts")),
            "runtime_sha256": digest(storage.source_bytes(project / "dist" / example)),
            "compiledParityClaimed": True,
        },
        "fakeCarrierAncillary": {
            "source_sha256": digest(storage.source_bytes(project / "examples/fake-carrier.ts")),
            "runtime_sha256": digest(
                storage.source_bytes(project / "dist/examples/fake-carrier.js")
            ),
            "compiledParityClaimed": False,
            "loadedByOperationsFixture": False,
        },
        "compilerConfigs": ["production", "pg", "examples"],
        "publicDistPayloads": len(actual) + len(declarations),
    }


def validate_node_failure(raw: bytes, mode: str) -> dict[str, Any]:
    v = shape(
        decode(raw, 8192),
        {"schemaVersion", "status", "mode", "stage", "errorType", "code", "frames"},
    )
    codes = {
        "AccessDenied",
        "AcknowledgementUnknown",
        "AssociationRejected",
        "AssociationRequired",
        "CleanupIncomplete",
        "DispatchClaimLost",
        "DispatchUnavailable",
        "IdentityConflict",
        "InvalidConfiguration",
        "InvalidEvent",
        "NotFound",
        "OperationConflict",
        "Overloaded",
        "SchemaMismatch",
        "StorageUnavailable",
        "UpgradeRequired",
        "access_denied",
        "closed",
        "context_unavailable",
        "cursor_stale",
        "invalid_query",
        "overloaded",
        "unavailable",
    }
    seed_stages = {
        "seed",
        "seed_bindings",
        "seed_collect_originals",
        "seed_native_inputs",
        "seed_outbound_enqueue_send",
        "seed_outbound_route",
        "seed_save_originals",
        "seed_sms_accept",
        "seed_sms_association",
    }
    exercise_stages = {
        "exercise",
        "exercise_initial_context",
        "exercise_case_revision_cursor",
        "exercise_expiry_final_grant",
        "exercise_revocation_final_grant",
        "exercise_cursor_scope_section",
        "exercise_cursor_anchor",
        "exercise_canonical_paging",
        "exercise_zero_revision",
        "exercise_read_retry",
        "exercise_ignored_ownership",
        "exercise_http_boundary",
        "exercise_exporter_observations",
    }
    if (
        mode not in MODES
        or not native.exact(v["schemaVersion"], 1)
        or v["status"] != "failed"
        or v["mode"] != mode
        or type(v["stage"]) is not str
        or (
            v["stage"] not in seed_stages
            if mode == "seed"
            else v["stage"] not in exercise_stages
            if mode == "exercise"
            else v["stage"] != mode
        )
        or type(v["errorType"]) is not str
        or v["errorType"]
        not in {
            "AssertionError",
            "ChannelError",
            "OperationsError",
            "RehydrationError",
            "DependencyError",
            "UnexpectedError",
        }
        or (v["code"] is not None and (type(v["code"]) is not str or v["code"] not in codes))
        or type(v["frames"]) is not list
        or len(v["frames"]) > 8
    ):
        raise GateError("invalid_failure_context")
    for frame in v["frames"]:
        shape(frame, {"file", "line"})
        if (
            type(frame["file"]) is not str
            or frame["file"] not in {"pg_operations_cases.js", "operations-lab.js"}
            or not counter(frame["line"], 100000, 1)
        ):
            raise GateError("invalid_failure_context")
    return v


if __name__ == "__main__":
    raise SystemExit(main())
