"""Finite diagnostics for owned P2 fixture failures; raw captures stay private."""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p2_native_check as native

from harness.process_control import OwnedProcess

MODES = frozenset(
    {
        "install",
        "legacy-seed",
        "upgrade-hold",
        "upgrade",
        "expiry",
        "exercise",
        "crash",
        "replay",
        "drift",
        "verify",
        "cleanup",
        "media-install",
        "media-seed",
        "media-serve",
        "media-verify",
        "media-cleanup",
    }
)
CHANNEL_CODES = frozenset(
    {
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
    }
)
GATEWAY_CODES = frozenset(
    {
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
    }
)
ERROR_TYPES = frozenset(
    {"AssertionError", "Error", "ChannelError", "GatewayError", "DependencyError"}
)


def validated_failure(raw: bytes, mode: str) -> dict[str, Any]:
    if type(mode) is not str or mode not in MODES:
        raise native.GateError("invalid_diagnostic")
    value = native.decode(raw, maximum=2048)
    if (
        set(value) != {"schemaVersion", "stage", "errorType", "code", "frames"}
        or not native.exact(value["schemaVersion"], 1)
        or type(value["stage"]) is not str
        or value["stage"] not in {mode, "initializing"}
        or type(value["errorType"]) is not str
        or value["errorType"] not in ERROR_TYPES
    ):
        raise native.GateError("invalid_diagnostic")
    code = value["code"]
    kind = value["errorType"]
    if code is not None and (
        type(code) is not str
        or kind not in {"ChannelError", "GatewayError"}
        or code not in (CHANNEL_CODES if kind == "ChannelError" else GATEWAY_CODES)
    ):
        raise native.GateError("invalid_diagnostic")
    frames = value["frames"]
    if type(frames) is not list or len(frames) > 4:
        raise native.GateError("invalid_diagnostic")
    for frame in frames:
        if (
            type(frame) is not dict
            or set(frame) != {"file", "line"}
            or frame["file"] != "pg_communication_cases.js"
            or type(frame["line"]) is not int
            or not 1 <= frame["line"] <= 1000000
        ):
            raise native.GateError("invalid_diagnostic")
    return value


def private_failure(path: Path, mode: str) -> dict[str, Any]:
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_nlink != 1
        or not 0 < info.st_size <= 2048
    ):
        raise native.GateError("invalid_diagnostic")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as source:
        raw = source.read(2049)
    return validated_failure(raw, mode)


def retain_safely(
    work: Path,
    artifacts: Path,
    children: list[OwnedProcess],
    primary: BaseException,
    secret_values: tuple[str, ...],
) -> None:
    """Diagnostics are observation only; every sink failure is contained."""
    try:
        records = []
        for child in children[:32]:
            label = child.output_directory.name
            # Only tooling-owned labels can be recorded. Never copy argv/env/error text.
            if (
                not label
                or len(label) > 48
                or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in label)
            ):
                continue
            code = child.returncode
            if code is not None and (type(code) is not int or not -255 <= code <= 255):
                code = None
            records.append({"child": label, "processPid": child.pid, "returncode": code})
        failures = []
        rejected_files = 0
        for mode in sorted(MODES):
            path = work / ("communication-failure-" + mode + ".json")
            if not path.exists() and not path.is_symlink():
                continue
            try:
                value = private_failure(path, mode)
                raw = json.dumps(value, sort_keys=True).encode()
                if any(secret.encode() in raw for secret in secret_values if secret):
                    continue
                native.write_json(artifacts / path.name, value, maximum=2048)
                failures.append(mode)
            except Exception:  # noqa: BLE001 - A diagnostic must not replace the primary failure.
                rejected_files += 1
        kind = type(primary).__name__
        if kind not in {
            "GateError",
            "ProcessControlError",
            "ProcessExited",
            "ProcessTimeout",
            "OutputLimitExceeded",
            "OSError",
            "TimeoutError",
        }:
            kind = "DependencyError"
        native.write_json(
            artifacts / "fixture-failure-context.json",
            {
                "schemaVersion": 1,
                "status": "failed",
                "primaryType": kind,
                "children": records,
                "retainedFixtureModes": failures,
                "diagnosticFilesRejected": rejected_files,
            },
        )
    except Exception:  # noqa: BLE001 - Sink failures never stop resource cleanup or qualify a run.
        return
