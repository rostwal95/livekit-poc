"""Bounded offline/explicit-lab standalone P3 package qualification.

This is repository-owned host tooling. Product consumers are installed outside
the checkout; importing this module performs no setup, I/O or child execution.
"""

from __future__ import annotations

import argparse
import base64
import configparser
import csv
import hashlib
import io
import json
import math
import os
import platform
import re
import shutil
import stat
import sys
import tarfile
import tempfile
import time
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path
from typing import Any, NoReturn, cast
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from harness.process_control import (
    OwnedProcess,  # Host tooling only; isolated consumers receive no checkout path.
)

P3_RUNTIME_FILES = frozenset(
    {
        "delegation_reliability/__init__.py",
        "delegation_reliability/_policy_codec.py",
        "delegation_reliability/__main__.py",
        "delegation_reliability/action_adapter.py",
        "delegation_reliability/applicability_api.py",
        "delegation_reliability/applicability_models.py",
        "delegation_reliability/applicability_refresher.py",
        "delegation_reliability/applicability_schema.py",
        "delegation_reliability/applicability_store.py",
        "delegation_reliability/baseline.py",
        "delegation_reliability/case_adapter.py",
        "delegation_reliability/channel_policy_contracts.py",
        "delegation_reliability/channel_policy_execution.py",
        "delegation_reliability/completion.py",
        "delegation_reliability/completion_processor.py",
        "delegation_reliability/contracts.py",
        "delegation_reliability/coordinator.py",
        "delegation_reliability/delivery_contract.py",
        "delegation_reliability/document.py",
        "delegation_reliability/document_contracts.py",
        "delegation_reliability/fixed_policy.py",
        "delegation_reliability/fixed_policy_contracts.py",
        "delegation_reliability/fixed_policy_execution.py",
        "delegation_reliability/http_client.py",
        "delegation_reliability/models.py",
        "delegation_reliability/native_policy.py",
        "delegation_reliability/processing_api.py",
        "delegation_reliability/processing_models.py",
        "delegation_reliability/processing_schema.py",
        "delegation_reliability/processing_store.py",
        "delegation_reliability/projection_admin.py",
        "delegation_reliability/projection_api.py",
        "delegation_reliability/projection_models.py",
        "delegation_reliability/projection_store.py",
        "delegation_reliability/projector.py",
        "delegation_reliability/py.typed",
        "delegation_reliability/runner.py",
        "delegation_reliability/scripted.py",
        "delegation_reliability/security.py",
    }
)
SPECIALIST_MODULES = frozenset(
    {
        "capability-codec",
        "client",
        "contracts",
        "document-contracts",
        "document-png-worker",
        "document-png",
        "document",
        "fixed-policy-contracts",
        "fixed-policy",
        "http-protocol",
        "http",
        "index",
        "security",
        "server",
    }
)
SPECIALIST_EXAMPLES = frozenset({"policy-http.mjs", "document-http.mjs", "fixed-policy.mjs"})


def validate_current_payload_inventory(
    p3: dict[str, bytes], modules: set[str], examples: set[str]
) -> None:
    """Exact reviewed image/fixed-policy inventory; equal-count substitutions fail."""
    if (
        set(p3) != P3_RUNTIME_FILES
        or modules != SPECIALIST_MODULES
        or examples != SPECIALIST_EXAMPLES
    ):
        raise GateError("invalid_artifact")


OFFLINE_CASES = (
    "python_archive_payload_readme_RECORD",
    "fresh_declared_P1_dependency_wheel",
    "npm_payload_manifest_public_exports",
    "installed_imports_no_startup_IO",
    "strict_installed_Python_consumer",
    "strict_installed_TS_consumer",
    "installed_native_baseline_entrypoint",
    "installed_public_Node_HTTP_example",
)
LAB_CASES = (
    "actual_run_completion_useful_result",
    "equal_acceptance_changed_payload_scope_isolation",
    "separate_exact_confirmation_original_guarded_intent",
    "public_projection_processing_refresh_progress",
    "read_only_inspection_zero_new_calls",
    "owned_completion_ACK_crash_fresh_original_replay",
    "later_cancel_preserves_original_facts_without_new_permission",
    "independent_SQL_receiver_supplier_identity_cleanup",
)
DEADLINE_SECONDS = 360.0
CLEANUP_SECONDS = 20.0
MAX_CHILDREN = 40
MAX_STREAM_BYTES = 65536
MAX_CAPTURE_BYTES = 2097152
MAX_REPORT_BYTES = 32768
MODE_CASES = {
    "install": (),
    "seed": (),
    "effect": (),
    "cleanup": (),
    "complete": (LAB_CASES[0],),
    "metadata": (LAB_CASES[3],),
    "negative": (LAB_CASES[1], LAB_CASES[2], LAB_CASES[4]),
    "replay": (LAB_CASES[5],),
    "cancel": (LAB_CASES[6],),
    "verify": (LAB_CASES[7],),
}
SAFE_CHILD_CODES = frozenset(
    [
        "acknowledgement_unknown",
        "capacity",
        "case_cancelled",
        "case_changed",
        "case_state_unavailable",
        "checkpoint_conflict",
        "cleanup_incomplete",
        "closed",
        "deadline_exceeded",
        "deadline_expired",
        "evidence_mismatch",
        "expired",
        "fixture_failed",
        "identity_conflict",
        "intent_committed",
        "internal_error",
        "invalid_confirmation",
        "invalid_contract",
        "invalid_input",
        "invalid_json",
        "invalid_result",
        "invalid_source_state",
        "invalid_stored_state",
        "not_eligible",
        "not_found",
        "quote_expired",
        "request_aborted",
        "result_mismatch",
        "schema_mismatch",
        "source_mismatch",
        "stale_revision",
        "storage_unavailable",
        "transport_unknown",
        "unauthorized",
        "unknown_attempt",
        "unknown_capability",
        "unsupported_facts",
        "unsupported_version",
    ]
)
FIXTURE_STAGES = frozenset(
    [
        "configuration",
        "install",
        "seed",
        "complete",
        "effect",
        "metadata",
        "negative",
        "replay",
        "cancel",
        "verify",
        "cleanup",
        "verify_counts",
        "verify_source",
        "verify_projection",
        "verify_ack",
        "verify_refresh",
        "verify_delivery",
        "verify_action",
        "verify_effect",
        "verify_business",
        "verify_receiver",
        "verify_supplier",
        "verify_peer",
        "verify_inventory",
    ]
)

PROOF_FILES = (
    "standalone-authority.json",
    "standalone-service.json",
    "standalone-replay.json",
)
ARTIFACT_PATHS = {
    "p1-wheel": "artifacts/p1/agent_continuity-0.1.0-py3-none-any.whl",
    "p3-wheel": "artifacts/wheel/delegation_reliability-0.1.0-py3-none-any.whl",
    "p3-sdist": "artifacts/sdist/delegation_reliability-0.1.0.tar.gz",
    "p3-rebuilt": "artifacts/rebuilt/delegation_reliability-0.1.0-py3-none-any.whl",
    "specialist-npm": "artifacts/npm/livekit-ecosystem-delegation-specialist-0.1.0.tgz",
}
BASE_KEYS = frozenset(
    {
        "PATH",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "COREPACK_HOME",
        "COREPACK_ENABLE_NETWORK",
        "UV_PYTHON_DOWNLOADS",
        "UV_NO_PROGRESS",
        "PYTHONDONTWRITEBYTECODE",
        "__CF_USER_TEXT_ENCODING",
    }
)
COMMON_KEYS = frozenset(
    "P3_STANDALONE_" + name
    for name in ("PG_PORT", "WORK_SCHEMA", "CASE_SCHEMA", "SCHEMA", "DIRECTORY")
)
ROLE_KEYS = {
    "owner": COMMON_KEYS | {"P3_STANDALONE_OWNER_PASSWORD"},
    "runtime": COMMON_KEYS
    | {
        "P3_STANDALONE_RUNTIME_PASSWORD",
        "P3_STANDALONE_WORK_TOKEN",
        "P3_STANDALONE_CASE_TOKEN",
        "P3_STANDALONE_ENDPOINT_FILE",
        "P3_STANDALONE_SPECIALIST_TOKEN",
    },
    "node": frozenset(
        "P3_STANDALONE_" + name
        for name in ("DIRECTORY", "SPECIALIST_TOKEN", "READY_FILE", "ENDPOINT_FILE", "STOP_FILE")
    ),
}
MODES = {
    "install": "owner",
    "seed": "runtime",
    "complete": "runtime",
    "effect": "runtime",
    "metadata": "runtime",
    "negative": "runtime",
    "replay": "runtime",
    "cancel": "runtime",
    "verify": "owner",
    "cleanup": "owner",
}
CODES = frozenset(
    {
        "invalid_input",
        "missing_setup",
        "build_failed",
        "invalid_artifact",
        "consumer_failed",
        "deadline_exceeded",
        "cleanup_incomplete",
        "invalid_report",
        "invalid_proof",
        "retention_failed",
        "child_budget",
        "report_exists",
        "unexpected_error",
    }
)
STAGES = frozenset(
    {
        "input",
        "build_p1",
        "build_p3",
        "rebuild_p3",
        "export",
        "install",
        "imports",
        "types",
        "baseline",
        "node_build",
        "npm_pack",
        "npm_install",
        "node_types",
        "node_example",
        "lab_install",
        "lab_seed",
        "lab_server",
        "lab_complete",
        "lab_effect",
        "lab_metadata",
        "lab_negative",
        "lab_replay",
        "lab_cancel",
        "lab_verify",
        "cleanup",
        "retention",
    }
)


class GateError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code if type(code) is str and code in CODES else "unexpected_error"
        super().__init__(self.code)


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_field")
        result[key] = value
    return result


def decode(raw: bytes, maximum: int = MAX_REPORT_BYTES) -> dict[str, Any]:
    if type(raw) is not bytes or not 1 <= len(raw) <= maximum:
        raise GateError("invalid_report")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")),
        )
    except (ValueError, UnicodeError, RecursionError):
        raise GateError("invalid_report") from None
    if type(value) is not dict:
        raise GateError("invalid_report")
    return cast(dict[str, Any], value)


def _exact(value: object, expected: object) -> bool:
    if type(value) is not type(expected):
        return False
    if type(expected) is dict and type(value) is dict:
        return value.keys() == expected.keys() and all(
            _exact(value[k], v) for k, v in expected.items()
        )
    if type(expected) is list and type(value) is list:
        return len(value) == len(expected) and all(
            _exact(a, b) for a, b in zip(value, expected, strict=True)
        )
    return value == expected


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _hash(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _natural(value: object, minimum: int, maximum: int) -> bool:
    return type(value) is int and minimum <= value <= maximum


def _proof_entry(value: object, maximum: int) -> bool:
    return (
        type(value) is dict
        and set(value) == {"bytes", "sha256"}
        and _natural(value["bytes"], 1, maximum)
        and _hash(value["sha256"])
    )


def validated_report(raw: bytes) -> dict[str, Any]:
    value = decode(raw)
    mode = value.get("mode")
    if type(mode) is not str or mode not in {"offline", "lab"}:
        raise GateError("invalid_report")
    lab = mode == "lab"
    cases = OFFLINE_CASES + (LAB_CASES if lab else ())
    expected = {
        "schema_version": 1,
        "status": "passed",
        "mode": mode,
        "tests": len(cases),
        "passed": len(cases),
        "offline_assertions": 8,
        "lab_assertions": 8 if lab else 0,
        "child_terminations": 1 if lab else 0,
        "child_commands": 28 if lab else 17,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "cleanup_complete": True,
        "provider_calls": False,
        "authority_runtime_changes": False,
        "full_charter_release_claimed": False,
        "node_version": "24.22.2",
        "python_version": "3.14.10",
        "platform": "darwin_arm64",
        "case_results": [{"name": n, "status": "passed", "code": "ok"} for n in cases],
    }
    if set(value) != set(expected) | {
        "duration_seconds",
        "artifacts",
        "proofs",
        "retained_index_sha256",
    }:
        raise GateError("invalid_report")
    if any(not _exact(value[k], v) for k, v in expected.items()):
        raise GateError("invalid_report")
    duration = value["duration_seconds"]
    if (
        type(duration) not in {int, float}
        or not 0 < duration <= DEADLINE_SECONDS
        or not math.isfinite(duration)
    ):
        raise GateError("invalid_report")
    if not _hash(value["retained_index_sha256"]):
        raise GateError("invalid_report")
    artifacts = value["artifacts"]
    if type(artifacts) is not dict or set(artifacts) != set(ARTIFACT_PATHS):
        raise GateError("invalid_report")
    for name, path in ARTIFACT_PATHS.items():
        entry = artifacts[name]
        if (
            type(entry) is not dict
            or set(entry) != {"path", "bytes", "sha256"}
            or entry["path"] != path
            or not _proof_entry({k: entry[k] for k in ("bytes", "sha256")}, 8388608)
        ):
            raise GateError("invalid_report")
    proofs = value["proofs"]
    if (
        type(proofs) is not dict
        or set(proofs) != (set(PROOF_FILES) if lab else set())
        or any(not _proof_entry(entry, MAX_REPORT_BYTES) for entry in proofs.values())
    ):
        raise GateError("invalid_report")
    return value


def target_path(root: Path, requested: Path | None) -> Path:
    if not root.is_absolute() or ".." in root.parts or root != Path(os.path.normpath(root)):
        raise GateError("invalid_input")
    base = root / ".local/validation/p3-package"
    requested = requested or Path(".local/validation/p3-package/" + uuid4().hex + ".json")
    if ".." in requested.parts:
        raise GateError("invalid_input")
    target = requested if requested.is_absolute() else root / requested
    if (
        target.parent != base
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}\.json", target.name) is None
    ):
        raise GateError("invalid_input")
    for ancestor in [base, *base.parents]:
        if ancestor.is_symlink():
            raise GateError("invalid_input")
        if ancestor == root:
            break
    if any(
        path.exists() or path.is_symlink()
        for path in (target, target.with_name(target.stem + "-artifacts"))
    ):
        raise GateError("report_exists")
    return target


def validate_child_environment(
    environment: dict[str, str], role: str, mode: str | None = None
) -> None:
    if type(environment) is not dict or type(role) is not str or role not in ROLE_KEYS:
        raise GateError("invalid_input")
    if role != "node" and (type(mode) is not str or MODES.get(mode) != role):
        raise GateError("invalid_input")
    if role == "node" and mode is not None:
        raise GateError("invalid_input")
    required = ROLE_KEYS[role] | ({"P3_STANDALONE_BARRIER"} if mode == "complete" else set())
    if not required <= environment.keys() or set(environment) - required - BASE_KEYS:
        raise GateError("invalid_input")
    if any(
        type(k) is not str or type(v) is not str or not 1 <= len(v) <= 4096 or "\0" in v
        for k, v in environment.items()
    ):
        raise GateError("invalid_input")
    folder = Path(environment["P3_STANDALONE_DIRECTORY"])
    if not folder.is_absolute() or ".." in folder.parts or folder != Path(os.path.normpath(folder)):
        raise GateError("invalid_input")
    try:
        info = folder.lstat()
        if folder.resolve() != folder:
            raise GateError("invalid_input")
        if (
            not stat.S_ISDIR(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o700
            or info.st_uid != os.geteuid()
        ):
            raise GateError("invalid_input")
    except OSError:
        raise GateError("invalid_input") from None
    paths = {"ENDPOINT_FILE": "specialist-endpoint.json"}
    if role == "node":
        paths.update(READY_FILE="specialist.ready", STOP_FILE="specialist.stop")
    if mode == "complete":
        paths["BARRIER"] = "completion_returned.reached"
    for name, expected in paths.items():
        key = "P3_STANDALONE_" + name
        if key in environment and Path(environment[key]) != folder / expected:
            raise GateError("invalid_input")
    for key in (
        "P3_STANDALONE_WORK_TOKEN",
        "P3_STANDALONE_CASE_TOKEN",
        "P3_STANDALONE_SPECIALIST_TOKEN",
    ):
        if key in environment and re.fullmatch(r"[A-Za-z0-9_-]{43}", environment[key]) is None:
            raise GateError("invalid_input")
    if role != "node":
        port = environment["P3_STANDALONE_PG_PORT"]
        if re.fullmatch(r"[1-9][0-9]{0,4}", port) is None or int(port) > 65535:
            raise GateError("invalid_input")
        suffixes = []
        for name, prefix in (
            ("WORK_SCHEMA", "p1_work_standalone_"),
            ("CASE_SCHEMA", "p3_completion_"),
            ("SCHEMA", "p3_projection_standalone_"),
        ):
            value = environment["P3_STANDALONE_" + name]
            if re.fullmatch(re.escape(prefix) + r"[0-9a-f]{32}", value) is None:
                raise GateError("invalid_input")
            suffixes.append(value[len(prefix) :])
        if len(set(suffixes)) != 1:
            raise GateError("invalid_input")
        password = environment[
            "P3_STANDALONE_" + ("OWNER_PASSWORD" if role == "owner" else "RUNTIME_PASSWORD")
        ]
        if len(password) > 128 or any(c in password for c in "\r\n\0"):
            raise GateError("invalid_input")


def _private_directory(path: Path) -> None:
    if not path.exists():
        if not path.parent.exists():
            _private_directory(path.parent)
        path.mkdir(mode=0o700)
    info = path.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o700
        or info.st_uid != os.geteuid()
    ):
        raise GateError("invalid_artifact")


def _write(path: Path, raw: bytes) -> None:
    _private_directory(path.parent)
    with os.fdopen(
        os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb"
    ) as stream:
        stream.write(raw)


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode()


def _archive_name(value: str) -> None:
    if (
        not value
        or Path(value).is_absolute()
        or ".." in Path(value).parts
        or "\\" in value
        or ":" in value
        or any(part in {"", "."} for part in value.rstrip("/").split("/"))
    ):
        raise GateError("invalid_artifact")


def _archive_entries(entries: list[tuple[str, int]]) -> None:
    if (
        not 1 <= len(entries) <= 512
        or len({n for n, _ in entries}) != len(entries)
        or sum(n for _, n in entries) > 8388608
    ):
        raise GateError("invalid_artifact")
    for name, size in entries:
        _archive_name(name)
        if not _natural(size, 0, 524288):
            raise GateError("invalid_artifact")


def _payload(member: Path, package: str) -> dict[str, bytes]:
    root = member / "src" / package
    if not root.is_dir() or root.is_symlink():
        raise GateError("invalid_artifact")
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise GateError("invalid_artifact")
        if path.is_file() and (path.suffix == ".py" or path.name == "py.typed"):
            result[str(path.relative_to(member / "src"))] = path.read_bytes()
    if not result or package + "/py.typed" not in result:
        raise GateError("invalid_artifact")
    return result


def _wheel(path: Path, member: Path, package: str, expected: dict[str, bytes]) -> None:
    prefix = package + "-0.1.0.dist-info/"
    project = tomllib.loads((member / "pyproject.toml").read_text())["project"]
    metadata_names = {"METADATA", "WHEEL", "top_level.txt", "RECORD"}
    if project.get("scripts"):
        metadata_names.add("entry_points.txt")
    with zipfile.ZipFile(path) as archive:
        _archive_entries([(entry.filename, entry.file_size) for entry in archive.infolist()])
        if any(
            stat.S_IFMT(entry.external_attr >> 16) not in {0, stat.S_IFREG}
            for entry in archive.infolist()
        ):
            raise GateError("invalid_artifact")
        if set(archive.namelist()) != set(expected) | {prefix + name for name in metadata_names}:
            raise GateError("invalid_artifact")
        if {name: archive.read(name) for name in expected} != expected:
            raise GateError("invalid_artifact")
        raw = archive.read(prefix + "METADATA")
        metadata = BytesParser().parsebytes(raw)
        if (
            metadata.get("Version") != "0.1.0"
            or metadata.get("Name") != project["name"]
            or raw.partition(b"\n\n")[2] != (member / "README.md").read_bytes()
            or b"file://" in raw
        ):
            raise GateError("invalid_artifact")
        python_range = metadata.get("Requires-Python", "")
        if type(python_range) is not str or set(python_range.replace(" ", "").split(",")) != {
            ">=3.14",
            "<3.15",
        }:
            raise GateError("invalid_artifact")
        optional = project.get("optional-dependencies", {})
        declared = set(project.get("dependencies", [])) | {
            requirement + '; extra == "' + extra + '"'
            for extra, requirements in optional.items()
            for requirement in requirements
        }
        if (
            set(metadata.get_all("Provides-Extra", [])) != set(optional)
            or set(metadata.get_all("Requires-Dist", [])) != declared
        ):
            raise GateError("invalid_artifact")
        if project.get("scripts"):
            entry_points = configparser.ConfigParser(interpolation=None)
            entry_points.read_string(archive.read(prefix + "entry_points.txt").decode())
            if (
                set(entry_points.sections()) != {"console_scripts"}
                or dict(entry_points["console_scripts"]) != project["scripts"]
            ):
                raise GateError("invalid_artifact")
        requires = metadata.get_all("Requires-Dist", [])
        if package == "delegation_reliability" and set(requires) != {
            "livekit-agents==1.8.11",
            "agent-continuity[postgres]==0.1.0",
            "psycopg[binary]==3.3.8",
        }:
            raise GateError("invalid_artifact")
        rows = list(csv.reader(io.StringIO(archive.read(prefix + "RECORD").decode())))
        if len(rows) != len(archive.namelist()) or {row[0] for row in rows} != set(
            archive.namelist()
        ):
            raise GateError("invalid_artifact")
        for name, algorithm, size in rows:
            if name == prefix + "RECORD":
                if algorithm or size:
                    raise GateError("invalid_artifact")
                continue
            body = archive.read(name)
            if (
                size != str(len(body))
                or algorithm
                != "sha256="
                + base64.urlsafe_b64encode(hashlib.sha256(body).digest()).rstrip(b"=").decode()
            ):
                raise GateError("invalid_artifact")


def _sdist(path: Path, member: Path, expected: dict[str, bytes]) -> None:
    with tarfile.open(path) as archive:
        members = archive.getmembers()
        _archive_entries([(m.name, m.size) for m in members])
        if any(not (m.isfile() or m.isdir()) for m in members):
            raise GateError("invalid_artifact")
        files = {}
        readmes = []
        project_files: dict[str, bytes] = {}
        for item in members:
            if not item.isfile():
                continue
            stream = archive.extractfile(item)
            if stream is None:
                raise GateError("invalid_artifact")
            raw = stream.read()
            if "/src/delegation_reliability/" in item.name:
                files[item.name.split("/src/", 1)[1]] = raw
            if item.name.split("/", 1)[-1] == "README.md":
                readmes.append(raw)
            relative = item.name.split("/", 1)[-1]
            if relative in {"pyproject.toml", "PKG-INFO"}:
                project_files[relative] = raw
            if relative.endswith(".py") and relative.removeprefix("src/") not in expected:
                raise GateError("invalid_artifact")
            if any(
                part in {".git", ".local", ".env.providers", ".venv", "node_modules"}
                for part in Path(item.name).parts
            ):
                raise GateError("invalid_artifact")
        if (
            files != expected
            or readmes != [(member / "README.md").read_bytes()]
            or set(project_files) != {"pyproject.toml", "PKG-INFO"}
            or project_files["pyproject.toml"] != (member / "pyproject.toml").read_bytes()
            or project_files["PKG-INFO"].partition(b"\n\n")[2]
            != (member / "README.md").read_bytes()
        ):
            raise GateError("invalid_artifact")


def validate_node_example(raw: bytes) -> dict[str, Any]:
    """The shipped example emits three safe telemetry rows then its one verdict."""
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_STREAM_BYTES:
        raise GateError("consumer_failed")
    lines = raw.splitlines()
    if len(lines) != 4:
        raise GateError("consumer_failed")
    values = [decode(line) for line in lines]
    telemetry = [
        {"component": "delegation_specialist", "event": event, "operation": operation, "code": "ok"}
        for event, operation in (
            ("attempt_started", "invoke"),
            ("attempt_finished", "invoke"),
            ("closed", "http"),
        )
    ]
    verdict = {
        "status": "passed",
        "mode": "local_scripted_http",
        "capability": "booking.evaluate_policy",
        "result": "candidate",
        "eligible": True,
        "business_action": "not_authorized",
        "durable_acceptance": False,
        "cleanup_complete": True,
    }
    if not _exact(values[:3], telemetry) or not _exact(values[3], verdict):
        raise GateError("consumer_failed")
    return values[3]


def validate_service_observation(stdout: bytes, proof: bytes) -> dict[str, Any]:
    """One canonical private proof file and exactly one stdout terminal newline."""
    parsed = validate_proof(proof, "standalone-service.json")
    canonical = json.dumps(
        parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()
    if proof != canonical or stdout != proof + b"\n":
        raise GateError("consumer_failed")
    return parsed


def _uuid(value: object) -> bool:
    return (
        type(value) is str
        and re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", value
        )
        is not None
    )


AUTHORITY_COUNTS = {
    name: 1
    for name in (
        "accepted",
        "action_receipts",
        "attempts",
        "business_outcomes",
        "case_intents",
        "confirmations",
        "delivery_intents",
        "delivery_receipts",
        "display_tombstones",
        "events",
        "mutation_effects",
        "processing_acks",
        "projected_results",
        "results",
        "supplier_apply_calls",
        "supplier_receipts",
    )
}
AUTHORITY_COUNTS["refresh_commands"] = 2
SCOPE = {"tenant_id": "tenant_standalone", "account_id": "account_standalone"}
ZERO_CALLS = dict.fromkeys(
    (
        "issue_write",
        "complete_write",
        "authorize_write",
        "invoke",
        "receiver_accept",
        "supplier_apply",
    ),
    0,
)
SUMMARY_KEYS = frozenset(
    {
        "work_id",
        "accepted_input_sha256",
        "result_sha256",
        "created_acceptances",
        "invoked",
        "delivery_state",
        "action_id",
        "human_acknowledgement",
        "attempt_id",
        "delivery_id",
        "receipt_id",
        "receiver_id",
        "intent_id",
        "effect_id",
    }
)
IDENTITY_KEYS = frozenset(
    {
        "scope",
        "work_id",
        "delegation_id",
        "request_sha256",
        "wire_request_sha256",
        "input_fingerprint",
        "attempt_id",
        "issue_command_id",
        "owner_id",
        "result_sha256",
        "source_id",
        "event_id",
        "case_task_id",
        "case_id",
        "case_revision",
        "quote_sha256",
        "confirmation_sha256",
        "action_id",
        "intent_id",
        "effect_id",
        "supplier_result_sha256",
        "delivery_id",
        "receiver_id",
        "recipient_id",
        "receipt_id",
        "processing_ack_sha256",
    }
)
METADATA_KEYS = frozenset(
    {
        "source_id",
        "event_id",
        "projection_sha256",
        "processing_ack_sha256",
        "first_refresh_sha256",
        "second_refresh_sha256",
        "display_tombstone_sha256",
        "terminal_watermark",
        "terminal_count",
    }
)


def inventory_digest(records: list[dict[str, Any]]) -> str:
    if not 1 <= len(records) <= 64:
        raise GateError("invalid_proof")
    output = hashlib.sha256(b"p3-standalone-inventory-v1\0")
    total = 0
    for record in records:
        raw = json.dumps(
            record, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
        total += len(raw)
        if len(raw) > 4096 or total > 65536:
            raise GateError("invalid_proof")
        output.update(len(raw).to_bytes(4, "big"))
        output.update(raw)
    return output.hexdigest()


def _summary(value: object, *, original: bool) -> dict[str, Any]:
    if type(value) is not dict or value.keys() != SUMMARY_KEYS:
        raise GateError("invalid_proof")
    for name in (
        "work_id",
        "attempt_id",
        "action_id",
        "delivery_id",
        "receipt_id",
        "receiver_id",
        "intent_id",
        "effect_id",
    ):
        if not _uuid(value[name]):
            raise GateError("invalid_proof")
    if (
        not all(_hash(value[n]) for n in ("accepted_input_sha256", "result_sha256"))
        or not _exact(value["created_acceptances"], int(original))
        or not _exact(value["invoked"], original)
        or value["delivery_state"] != "accepted"
        or value["human_acknowledgement"] != "unobserved"
    ):
        raise GateError("invalid_proof")
    return value


def validate_proof(raw: bytes, name: str) -> dict[str, Any]:
    try:
        value = decode(raw)
        if name == "standalone-service.json":
            fields = {
                "schema_version",
                "status",
                "node_version",
                "invoked",
                "strict_completed",
                "active",
                "requests",
                "sockets",
                "request_sha256",
                "wire_attempt_id",
                "scope",
            }
            expected = {
                "schema_version": 1,
                "status": "closed",
                "node_version": "24.22.2",
                "invoked": 1,
                "strict_completed": 1,
                "active": 0,
                "requests": 0,
                "sockets": 0,
                "scope": SCOPE,
            }
            if (
                value.keys() != fields
                or not all(_exact(value[k], v) for k, v in expected.items())
                or not _hash(value["request_sha256"])
                or type(value["wire_attempt_id"]) is not str
                or re.fullmatch(r"attempt_[0-9a-f]{32}", value["wire_attempt_id"]) is None
            ):
                raise GateError("invalid_proof")
        elif name == "standalone-authority.json":
            if (
                value.keys()
                != {
                    "schema_version",
                    "status",
                    "counts",
                    "identity",
                    "metadata",
                    "inventory_sha256",
                }
                or not _exact(value["schema_version"], 1)
                or value["status"] != "passed"
                or not _exact(value["counts"], AUTHORITY_COUNTS)
            ):
                raise GateError("invalid_proof")
            identity, metadata = value["identity"], value["metadata"]
            if (
                type(identity) is not dict
                or identity.keys() != IDENTITY_KEYS
                or type(metadata) is not dict
                or metadata.keys() != METADATA_KEYS
            ):
                raise GateError("invalid_proof")
            fixed = {
                "scope": SCOPE,
                "delegation_id": "delegation_standalone",
                "issue_command_id": "standalone_execution",
                "case_revision": 2,
                "recipient_id": "recipient_standalone",
            }
            if not all(_exact(identity[k], v) for k, v in fixed.items()):
                raise GateError("invalid_proof")
            for key, item in identity.items():
                if key in fixed:
                    continue
                if not (
                    _hash(item)
                    if key.endswith("sha256") or key == "input_fingerprint"
                    else _uuid(item)
                ):
                    raise GateError("invalid_proof")
            for key, item in metadata.items():
                if not (
                    _exact(item, 1)
                    if key.startswith("terminal_")
                    else _hash(item)
                    if key.endswith("sha256")
                    else _uuid(item)
                ):
                    raise GateError("invalid_proof")
            if any(
                identity[k] != metadata[k]
                for k in ("source_id", "event_id", "processing_ack_sha256")
            ) or value["inventory_sha256"] != inventory_digest(
                [
                    {"kind": "counts", **value["counts"]},
                    {"kind": "identity", **identity},
                    {"kind": "metadata", **metadata},
                ]
            ):
                raise GateError("invalid_proof")
        elif name == "standalone-replay.json":
            if (
                value.keys()
                != {
                    "schema_version",
                    "status",
                    "first",
                    "replay",
                    "after_cancel",
                    "new_call_counts",
                    "cleanup",
                }
                or not _exact(value["schema_version"], 1)
                or value["status"] != "passed"
            ):
                raise GateError("invalid_proof")
            first, replay = (
                _summary(value["first"], original=True),
                _summary(value["replay"], original=False),
            )
            if (
                replay != {**first, "created_acceptances": 0, "invoked": False}
                or not _exact(value["new_call_counts"], ZERO_CALLS)
                or not _exact(
                    value["cleanup"],
                    {
                        "first": {"pending": 0, "cleanup_complete": True},
                        "replay": {"pending": 0, "cleanup_complete": True},
                        "public_pending": 0,
                    },
                )
            ):
                raise GateError("invalid_proof")
            expected = {
                "action_id": first["action_id"],
                "receipt_id": first["receipt_id"],
                "refresh_classification": "invalidated",
                "refresh_reason": "work_cancelled",
                "as_of_kind": "applicability_refresh_as_of_non_atomic",
                "original_facts_preserved": True,
                "new_call_counts": ZERO_CALLS,
            }
            if not _exact(value["after_cancel"], expected):
                raise GateError("invalid_proof")
        else:
            raise GateError("invalid_proof")
        return value
    except (KeyError, TypeError, ValueError, OverflowError, GateError):
        raise GateError("invalid_proof") from None


def validate_proof_bundle(proofs: dict[str, bytes]) -> dict[str, dict[str, Any]]:
    if proofs.keys() != set(PROOF_FILES):
        raise GateError("invalid_proof")
    parsed = {name: validate_proof(raw, name) for name, raw in proofs.items()}
    identity, summary = parsed[PROOF_FILES[0]]["identity"], parsed[PROOF_FILES[2]]["first"]
    if (
        any(
            identity[k] != summary[k]
            for k in (
                "work_id",
                "attempt_id",
                "result_sha256",
                "action_id",
                "intent_id",
                "effect_id",
                "delivery_id",
                "receiver_id",
                "receipt_id",
            )
        )
        or identity["request_sha256"] != summary["accepted_input_sha256"]
        or parsed[PROOF_FILES[1]]["request_sha256"] != identity["wire_request_sha256"]
        or parsed[PROOF_FILES[1]]["wire_attempt_id"]
        != "attempt_" + identity["attempt_id"].replace("-", "")
    ):
        raise GateError("invalid_proof")
    return parsed


def _read_private(path: Path, maximum: int) -> bytes:
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_uid != os.geteuid()
        or info.st_nlink != 1
        or not 1 <= info.st_size <= maximum
    ):
        raise GateError("retention_failed")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        current = os.fstat(stream.fileno())
        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
            raise GateError("retention_failed")
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise GateError("retention_failed")
    return raw


def validate_retained_index(directory: Path, expected_sha256: str) -> dict[str, Any]:
    root_info = directory.lstat()
    if (
        not stat.S_ISDIR(root_info.st_mode)
        or stat.S_IMODE(root_info.st_mode) != 0o700
        or root_info.st_uid != os.geteuid()
    ):
        raise GateError("retention_failed")
    raw = _read_private(directory / "retained-index.json", 1048576)
    value = decode(raw, 1048576)
    if (
        not _hash(expected_sha256)
        or digest(raw) != expected_sha256
        or value.keys() != {"schema_version", "files"}
        or not _exact(value["schema_version"], 1)
        or type(value["files"]) is not dict
        or not 1 <= len(value["files"]) <= 8192
    ):
        raise GateError("retention_failed")
    files = value["files"]
    if "retained-index.json" in files:
        raise GateError("retention_failed")
    actual = set()
    for path in directory.rglob("*"):
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            if stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.geteuid():
                raise GateError("retention_failed")
            continue
        relative = str(path.relative_to(directory))
        actual.add(relative)
        if relative == "retained-index.json":
            continue
        entry = files.get(relative)
        if (
            type(entry) is not dict
            or entry.keys() != {"bytes", "sha256"}
            or not _natural(entry["bytes"], 0, 134217728)
            or not _hash(entry["sha256"])
        ):
            raise GateError("retention_failed")
        assert isinstance(entry, dict)
        content = _read_private(path, 134217728) if info.st_size else b""
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
            or info.st_uid != os.geteuid()
            or digest(content) != entry["sha256"]
            or len(content) != entry["bytes"]
        ):
            raise GateError("retention_failed")
    if actual != set(files) | {"retained-index.json"}:
        raise GateError("retention_failed")
    return value


class PackageRun:
    """One finite host run; all product processes consume isolated installations."""

    def __init__(self, root: Path, report: Path) -> None:
        self.node = shutil.which("node")
        if self.node is None:
            raise GateError("missing_setup")
        self.root, self.report = root, report
        self.started = time.monotonic()
        self.deadline = self.started + DEADLINE_SECONDS - CLEANUP_SECONDS
        self.final_deadline = self.started + DEADLINE_SECONDS
        self.retained = report.with_name(report.stem + "-artifacts")
        self.retained.mkdir(mode=0o700)
        self.work = Path(
            tempfile.mkdtemp(prefix="p3-standalone-package-", dir="/private/tmp")
        ).resolve()
        self.work.chmod(0o700)
        _write(self.work / "owned-marker", b"p3-standalone-package-v1\n")
        self.stage = "input"
        self.commands = 0
        self.captured = 0
        self.passed: set[str] = set()
        self.children: list[OwnedProcess] = []
        self.outputs: dict[int, Path] = {}
        self.accounted: set[int] = set()
        self.reservations: dict[int, int] = {}
        self.artifacts: dict[str, dict[str, object]] = {}
        self.lab_terminations = 0
        self.lab_started = False
        self.lab_cleaned = False
        self.lab_folder: Path | None = None
        self.lab_settings: dict[str, str] = {}
        self.lab_context: dict[str, str] = {}
        self.work_token = self.case_token = self.specialist_token = ""
        self.failure_recorded = False
        self.proofs: dict[str, dict[str, object]] = {}
        self.base = {
            "PATH": str(Path(self.node).parent) + ":/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "COREPACK_ENABLE_NETWORK": "0",
            "COREPACK_HOME": os.environ.get(
                "COREPACK_HOME", "/private/tmp/livekit-pinned-corepack"
            ),
            "UV_PYTHON_DOWNLOADS": "never",
            "UV_NO_PROGRESS": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        self.python: Path | None = None
        self.synthetic = self.work / "application"
        _private_directory(self.synthetic)

    def remaining(self, *, cleanup: bool = False) -> float:
        remaining = (self.final_deadline if cleanup else self.deadline) - time.monotonic()
        if remaining <= 0:
            raise GateError("deadline_exceeded")
        return remaining

    def start(
        self,
        argv: list[str | Path],
        *,
        stage: str,
        cwd: Path | None = None,
        environment: dict[str, str] | None = None,
        cleanup: bool = False,
    ) -> OwnedProcess:
        if (
            stage not in STAGES
            or self.commands >= MAX_CHILDREN
            or self.captured + 2 > MAX_CAPTURE_BYTES
        ):
            raise GateError("child_budget")
        self.remaining(cleanup=cleanup)
        self.stage = stage
        self.commands += 1
        directory = self.retained / "commands" / f"{self.commands:02d}-{stage}"
        _private_directory(directory.parent)
        wrapper = "import os,sys;os.umask(0o077);os.execv(sys.argv[1],sys.argv[1:])"
        available = MAX_CAPTURE_BYTES - self.captured - sum(self.reservations.values())
        limit = min(MAX_STREAM_BYTES, available // 2)
        if limit < 1:
            raise GateError("child_budget")
        child = OwnedProcess(
            [sys.executable, "-I", "-c", wrapper, *(str(x) for x in argv)],
            cwd=cwd or self.work,
            env=environment or self.base,
            output_directory=directory,
            max_output_bytes=limit,
        )
        self.children.append(child)
        self.outputs[child.pid] = directory
        self.reservations[child.pid] = 2 * limit
        return child

    def capture(self, child: OwnedProcess) -> tuple[bytes, bytes]:
        directory = self.outputs[child.pid]
        out, error = (
            (directory / "stdout.bin").read_bytes(),
            (directory / "stderr.bin").read_bytes(),
        )
        if len(out) > MAX_STREAM_BYTES or len(error) > MAX_STREAM_BYTES:
            raise GateError("consumer_failed")
        if child.pid not in self.accounted:
            self.reservations.pop(child.pid, None)
            self.captured += len(out) + len(error)
            self.accounted.add(child.pid)
        if self.captured > MAX_CAPTURE_BYTES:
            raise GateError("child_budget")
        return out, error

    def command(
        self, argv: list[str | Path], *, stage: str, cwd: Path | None = None
    ) -> tuple[bytes, bytes]:
        child = self.start(argv, stage=stage, cwd=cwd)
        failure: BaseException | None = None
        result = None
        try:
            result = child.wait(timeout=min(60, self.remaining()))
        except BaseException as error:  # noqa: BLE001 - attempt independent cleanup/capture and preserve the first primary failure.
            failure = error
        try:
            child.close()
        except BaseException as error:  # noqa: BLE001 - attempt independent cleanup/capture and preserve the first primary failure.
            if failure is None:
                failure = error
        captured = (b"", b"")
        try:
            captured = self.capture(child)
        except BaseException as error:  # noqa: BLE001 - attempt independent cleanup/capture and preserve the first primary failure.
            if failure is None:
                failure = error
        if failure is not None:
            raise failure
        if result is None or result.returncode != 0 or child.cleanup_failed:
            raise GateError("consumer_failed")
        return captured

    def build(self, member: Path, folder: str, selector: str, *, stage: str) -> Path:
        output = self.work / folder
        _private_directory(output)
        self.command(
            [
                self.root / ".venv/bin/uv",
                "--no-config",
                "build",
                "--offline",
                "--no-sources",
                "--python",
                sys.executable,
                selector,
                "--out-dir",
                output,
                member,
            ],
            stage=stage,
        )
        paths = list(output.glob("*.tar.gz" if selector == "--sdist" else "*.whl"))
        if len(paths) != 1 or paths[0].is_symlink():
            raise GateError("invalid_artifact")
        return paths[0]

    def retain_artifact(self, label: str, path: Path) -> None:
        raw = path.read_bytes()
        if not 1 <= len(raw) <= 8388608:
            raise GateError("invalid_artifact")
        relative = ARTIFACT_PATHS[label]
        _write(self.retained / relative, raw)
        self.artifacts[label] = {"path": relative, "bytes": len(raw), "sha256": digest(raw)}

    def source_index(self) -> dict[str, str]:
        names = {
            "uv.lock",
            "pnpm-lock.yaml",
            "pyproject.toml",
            "projects/agent-continuity/python/README.md",
            "projects/agent-continuity/python/pyproject.toml",
            "projects/delegation-reliability/python/README.md",
            "projects/delegation-reliability/python/pyproject.toml",
            "projects/delegation-reliability/specialist-ts/README.md",
            "projects/delegation-reliability/specialist-ts/package.json",
            "projects/delegation-reliability/specialist-ts/tsconfig.json",
            "local-setup/scripts/p3_package_check.py",
            "harness/process_control.py",
            "harness/__init__.py",
            "local-setup/stack.py",
            "contracts/delegation/v1.json",
            "projects/delegation-reliability/tests/pg_standalone_cases.py",
            "projects/delegation-reliability/specialist-ts/tests/fixtures/standalone-server.mjs",
            "local-setup/scripts/p3_case_fixture.py",
        }
        folders = (
            ("projects/agent-continuity/python/src/continuity_lab", {".py", ".typed"}),
            (
                "projects/delegation-reliability/python/src/delegation_reliability",
                {".py", ".typed"},
            ),
            ("projects/delegation-reliability/specialist-ts/src", {".ts"}),
            ("projects/delegation-reliability/specialist-ts/dist", {".js", ".ts"}),
            ("projects/delegation-reliability/specialist-ts/examples", {".mjs"}),
            ("projects/delegation-reliability/examples", {".py"}),
        )
        for name, suffixes in folders:
            names.update(
                str(p.relative_to(self.root))
                for p in (self.root / name).rglob("*")
                if p.is_file() and p.suffix in suffixes
            )
        result = {}
        for name in sorted(names):
            path = self.root / name
            if path.is_symlink() or not path.is_file():
                raise GateError("invalid_artifact")
            result[name] = digest(path.read_bytes())
        return result

    def offline(self) -> dict[str, str]:
        if (
            sys.version_info[:3] != (3, 14, 10)
            or platform.system() != "Darwin"
            or platform.machine() != "arm64"
        ):
            raise GateError("missing_setup")
        snapshot = self.source_index()
        _write(self.retained / "source-index.json", _json_bytes(snapshot))
        p1 = self.root / "projects/agent-continuity/python"
        p3 = self.root / "projects/delegation-reliability/python"
        p1_source, p3_source = (
            _payload(p1, "continuity_lab"),
            _payload(p3, "delegation_reliability"),
        )
        validate_current_payload_inventory(
            p3_source,
            {
                p.stem
                for p in (self.root / "projects/delegation-reliability/specialist-ts/src").glob(
                    "*.ts"
                )
            },
            {
                p.name
                for p in (
                    self.root / "projects/delegation-reliability/specialist-ts/examples"
                ).glob("*.mjs")
            },
        )
        if len(p1_source) != 77:
            raise GateError("invalid_artifact")
        p1_wheel = self.build(p1, "p1-wheel", "--wheel", stage="build_p1")
        _wheel(p1_wheel, p1, "agent_continuity", p1_source)
        self.retain_artifact("p1-wheel", p1_wheel)
        self.passed.add(OFFLINE_CASES[1])
        wheel = self.build(p3, "p3-wheel", "--wheel", stage="build_p3")
        sdist = self.build(p3, "p3-sdist", "--sdist", stage="build_p3")
        _sdist(sdist, p3, p3_source)
        rebuilt = self.build(sdist, "p3-rebuilt", "--wheel", stage="rebuild_p3")
        for label, path in (("p3-wheel", wheel), ("p3-rebuilt", rebuilt)):
            _wheel(path, p3, "delegation_reliability", p3_source)
            self.retain_artifact(label, path)
        self.retain_artifact("p3-sdist", sdist)
        self.passed.add(OFFLINE_CASES[0])
        requirements = self.work / "requirements.txt"
        self.command(
            [
                self.root / ".venv/bin/uv",
                "export",
                "--offline",
                "--frozen",
                "--package",
                "delegation-reliability",
                "--no-dev",
                "--no-emit-workspace",
                "--no-hashes",
                "--no-annotate",
                "--no-header",
                "--project",
                self.root,
                "--output-file",
                requirements,
            ],
            stage="export",
        )
        req = requirements.read_bytes()
        if b"file://" in req or any(line.startswith((b"-e", b"/")) for line in req.splitlines()):
            raise GateError("invalid_artifact")
        _write(self.retained / "requirements.txt", req)
        venv = self.work / "installed"
        self.command([sys.executable, "-I", "-m", "venv", "--without-pip", venv], stage="install")
        self.python = venv / "bin/python"
        self.command(
            [
                self.root / ".venv/bin/uv",
                "--no-config",
                "pip",
                "install",
                "--offline",
                "--python",
                self.python,
                "-r",
                requirements,
                p1_wheel,
                wheel,
            ],
            stage="install",
        )
        self.command(
            [
                self.root / ".venv/bin/uv",
                "--no-config",
                "--offline",
                "pip",
                "check",
                "--python",
                self.python,
            ],
            stage="install",
        )
        self.copy_applications()
        self.python_consumers()
        self.node_consumers()
        if (
            self.commands != 17
            or self.passed != set(OFFLINE_CASES)
            or self.source_index() != snapshot
        ):
            raise GateError("invalid_artifact")
        return snapshot

    def copy_applications(self) -> None:
        for path in sorted((self.root / "projects/delegation-reliability/examples").glob("*.py")):
            raw = path.read_bytes()
            _write(self.synthetic / "projects/delegation-reliability/examples" / path.name, raw)
            _write(self.retained / "applications" / path.name, raw)

    def python_consumers(self) -> None:
        assert self.python is not None
        consumer = self.synthetic / "installed-consumer.py"
        application_directory = self.synthetic / "projects/delegation-reliability/examples"
        code = """from pathlib import Path
import asyncio,json,socket,sys
from importlib.metadata import version
from unittest.mock import patch
def forbidden(*args: object, **kwargs: object) -> object: raise AssertionError("import_started_IO")
with patch.object(socket.socket,"connect",forbidden),patch.object(socket.socket,"bind",forbidden),patch.object(asyncio,"create_task",forbidden):
 import continuity_lab.work_api as work
 import delegation_reliability as product
 import delegation_reliability.document as document
 import delegation_reliability.document_contracts as document_wire
 import standalone_policy as application
for module in (work,product,document,document_wire):
 assert module.__file__ is not None and Path(module.__file__).resolve().is_relative_to(Path(sys.prefix))
assert version("livekit-agents")=="1.8.11" and version("psycopg")=="3.3.8"
def document_roundtrip(request: document_wire.DocumentRequest) -> document_wire.DocumentRequest:
 return document_wire.parse_document_request(document_wire.encode_document_request(request))
async def document_invoke(client: document.DocumentSpecialistClient, request: document_wire.DocumentRequest) -> document_wire.DocumentResult:
 return await client.invoke(request)
def invalid_response(error: product.SpecialistHttpError) -> bool:
 return error.code == "invalid_response"
assert invalid_response(product.SpecialistHttpError("invalid_response"))
print(json.dumps({"schema_version":1,"status":"passed","installed_paths":True,"imports_no_IO":True}))
"""
        _write(consumer, code.encode())
        _write(self.retained / "consumers/installed-consumer.py", code.encode())
        launcher = (
            "import runpy,sys;sys.path.insert(0,"
            + repr(str(application_directory))
            + ");runpy.run_path("
            + repr(str(consumer))
            + ",run_name='__main__')"
        )
        raw, _err = self.command([self.python, "-I", "-c", launcher], stage="imports")
        if decode(raw) != {
            "schema_version": 1,
            "status": "passed",
            "installed_paths": True,
            "imports_no_IO": True,
        }:
            raise GateError("consumer_failed")
        self.passed.add(OFFLINE_CASES[3])
        examples = [consumer, *sorted(application_directory.glob("*.py"))]
        self.command(
            [
                sys.executable,
                "-I",
                "-m",
                "mypy",
                "--strict",
                "--python-executable",
                self.python,
                "--cache-dir",
                self.work / "mypy-cache",
                *examples,
            ],
            stage="types",
        )
        self.passed.add(OFFLINE_CASES[4])
        raw, _err = self.command(
            [self.python, "-I", "-m", "delegation_reliability"], stage="baseline"
        )
        observation = decode(raw)
        if (
            observation.get("status") != "passed"
            or observation.get("equivalent_input_and_result") is not True
            or observation.get("paid_provider_calls") != 0
            or observation.get("sdk_version") != "1.8.11"
            or type(observation.get("observations")) is not list
            or len(observation["observations"]) != 2
        ):
            raise GateError("consumer_failed")
        self.passed.add(OFFLINE_CASES[6])

    def node_consumers(self) -> None:
        assert self.node is not None
        project = self.root / "projects/delegation-reliability/specialist-ts"
        typescript = (project / "node_modules/typescript").resolve()
        if json.loads((typescript / "package.json").read_bytes())["version"] != "7.0.2":
            raise GateError("missing_setup")
        compiled = self.work / "specialist-compiled"
        self.command(
            [
                self.node,
                typescript / "bin/tsc",
                "--project",
                project / "tsconfig.json",
                "--outDir",
                compiled,
            ],
            stage="node_build",
            cwd=self.root,
        )
        expected_dist = {
            str(p.relative_to(project / "dist")): p.read_bytes()
            for p in (project / "dist").rglob("*")
            if p.is_file()
        }
        expected_names = {
            name + suffix for name in SPECIALIST_MODULES for suffix in (".js", ".d.ts")
        }
        if set(expected_dist) != expected_names:
            raise GateError("invalid_artifact")
        if {
            str(p.relative_to(compiled)): p.read_bytes() for p in compiled.rglob("*") if p.is_file()
        } != expected_dist:
            raise GateError("invalid_artifact")
        staged = self.work / "specialist-package"
        for name, raw in expected_dist.items():
            _write(staged / "dist" / name, raw)
        for path in (project / "examples").glob("*.mjs"):
            _write(staged / "examples" / path.name, path.read_bytes())
        for name in ("package.json", "README.md"):
            _write(staged / name, (project / name).read_bytes())
        for name in ("npm-user.conf", "npm-global.conf"):
            _write(self.work / name, b"")
        npm = Path(self.node).resolve().parents[1] / "lib/node_modules/npm/bin/npm-cli.js"
        if not npm.is_file():
            raise GateError("missing_setup")
        output = self.work / "npm-pack"
        _private_directory(output)
        flags = [
            "--userconfig=" + str(self.work / "npm-user.conf"),
            "--globalconfig=" + str(self.work / "npm-global.conf"),
            "--cache",
            str(self.work / "npm-cache"),
        ]
        self.command(
            [
                self.node,
                npm,
                "pack",
                "--offline",
                "--ignore-scripts",
                "--json",
                "--pack-destination",
                output,
                *flags,
            ],
            stage="npm_pack",
            cwd=staged,
        )
        archives = list(output.glob("*.tgz"))
        if len(archives) != 1:
            raise GateError("invalid_artifact")
        expected = {"package/dist/" + name: raw for name, raw in expected_dist.items()}
        expected.update(
            {
                "package/examples/" + p.name: p.read_bytes()
                for p in (project / "examples").glob("*.mjs")
            }
        )
        expected["package/README.md"] = (project / "README.md").read_bytes()
        with tarfile.open(archives[0]) as package:
            members = package.getmembers()
            _archive_entries([(p.name, p.size) for p in members])
            if any(not p.isfile() for p in members):
                raise GateError("invalid_artifact")
            payload = {}
            for entry in members:
                stream = package.extractfile(entry)
                if stream is None:
                    raise GateError("invalid_artifact")
                payload[entry.name] = stream.read()
            manifest = payload.pop("package/package.json", b"")
            if (
                payload != expected
                or len(payload) != len(SPECIALIST_MODULES) * 2 + len(SPECIALIST_EXAMPLES) + 1
                or json.loads(manifest) != json.loads((project / "package.json").read_bytes())
            ):
                raise GateError("invalid_artifact")
        self.retain_artifact("specialist-npm", archives[0])
        _write(
            self.retained / "npm-parity.json",
            _json_bytes(
                {
                    "payloads": {name: digest(raw) for name, raw in expected.items()},
                    "manifest_semantic_equal": True,
                }
            ),
        )
        self.passed.add(OFFLINE_CASES[2])
        _write(
            self.synthetic / "package.json",
            b'{"name":"installed-standalone-consumer","private":true,"type":"module"}\n',
        )
        self.command(
            [
                self.node,
                npm,
                "install",
                "--offline",
                "--ignore-scripts",
                "--no-audit",
                "--no-fund",
                *flags,
                archives[0],
            ],
            stage="npm_install",
            cwd=self.synthetic,
        )
        node_types = (project / "node_modules/@types/node").resolve()
        undici = (node_types.parent.parent / "undici-types").resolve()
        native = (typescript.parent / "@typescript/typescript-darwin-arm64").resolve()
        roots = {
            "typescript": typescript,
            "node-types": node_types,
            "undici-types": undici,
            "typescript-native": native,
        }
        expected_versions = {
            "typescript": "7.0.2",
            "node-types": "26.6.6",
            "undici-types": "8.9.0",
            "typescript-native": "7.0.2",
        }
        toolchain: dict[str, dict[str, object]] = {}
        total_bytes = 0
        for label, directory in roots.items():
            if (
                json.loads((directory / "package.json").read_bytes())["version"]
                != expected_versions[label]
            ):
                raise GateError("missing_setup")
            for path in sorted(directory.rglob("*")):
                if path.is_symlink():
                    raise GateError("invalid_artifact")
                if path.is_file():
                    total_bytes += path.stat().st_size
                    if len(toolchain) >= 4096 or total_bytes > 134217728:
                        raise GateError("invalid_artifact")
                    toolchain[label + "/" + str(path.relative_to(directory))] = {
                        "bytes": path.stat().st_size,
                        "sha256": digest(path.read_bytes()),
                    }
        _write(
            self.retained / "toolchain-proof.json",
            _json_bytes(
                {
                    "schema_version": 1,
                    "versions": expected_versions,
                    "roots": {name: str(path) for name, path in roots.items()},
                    "files": toolchain,
                    "bytes": total_bytes,
                    "product_source_injected": False,
                }
            ),
        )
        _private_directory(self.synthetic / "node_modules/@types")
        (self.synthetic / "node_modules/@types/node").symlink_to(
            node_types, target_is_directory=True
        )
        (self.synthetic / "node_modules/undici-types").symlink_to(undici, target_is_directory=True)
        ts = b"import {SpecialistServer,EvidenceRegistry,LocalTrust,parseRequest,encodeRequest,type DelegationRequest} from '@livekit-ecosystem/delegation-specialist';\nexport function configured(trust:LocalTrust,evidence:EvidenceRegistry):SpecialistServer{return new SpecialistServer({trust,evidence});}\nexport function roundTrip(value:DelegationRequest):DelegationRequest{return parseRequest(encodeRequest(value));}\n"
        ts += b"import {DocumentHandler,DocumentSpecialistClient,parseDocumentRequest,encodeDocumentRequest,type DocumentRequest,type DocumentResult} from '@livekit-ecosystem/delegation-specialist/document';\nexport function configuredDocument(trust:LocalTrust,evidence:EvidenceRegistry,document:DocumentHandler):SpecialistServer{return new SpecialistServer({trust,evidence,document});}\nexport function documentRoundTrip(value:DocumentRequest):DocumentRequest{return parseDocumentRequest(encodeDocumentRequest(value));}\nexport async function documentInvoke(client:DocumentSpecialistClient,request:DocumentRequest):Promise<DocumentResult>{return client.invoke(request);}\n"
        _write(self.synthetic / "consumer.ts", ts)
        config = {
            "compilerOptions": {
                "target": "ES2022",
                "module": "NodeNext",
                "moduleResolution": "NodeNext",
                "strict": True,
                "skipLibCheck": False,
                "noEmit": True,
                "types": ["node"],
            },
            "include": ["consumer.ts"],
        }
        _write(self.synthetic / "tsconfig.json", _json_bytes(config))
        _write(self.retained / "consumers/consumer.ts", ts)
        _write(self.retained / "consumers/tsconfig.json", _json_bytes(config))
        self.command(
            [self.node, typescript / "bin/tsc", "--project", self.synthetic / "tsconfig.json"],
            stage="node_types",
            cwd=self.synthetic,
        )
        self.passed.add(OFFLINE_CASES[5])
        js = (
            "import * as product from '@livekit-ecosystem/delegation-specialist';import {fileURLToPath}from'node:url';if(process.versions.node!=='24.22.2'||!fileURLToPath(import.meta.resolve('@livekit-ecosystem/delegation-specialist')).startsWith("
            + json.dumps(str(self.synthetic / "node_modules") + "/")
            + "))throw Error('installed_import_failed');console.log(JSON.stringify({schema_version:1,status:'passed',exports:Object.keys(product).length}));"
        )
        raw, _err = self.command(
            [self.node, "--input-type=module", "-e", js], stage="imports", cwd=self.synthetic
        )
        if decode(raw).get("status") != "passed":
            raise GateError("consumer_failed")
        installed = self.synthetic / "node_modules/@livekit-ecosystem/delegation-specialist"
        raw, _err = self.command(
            [self.node, installed / "examples/policy-http.mjs"],
            stage="node_example",
            cwd=self.synthetic,
        )
        observed = validate_node_example(raw)
        if (
            observed.get("status") != "passed"
            or observed.get("cleanup_complete") is not True
            or observed.get("business_action") != "not_authorized"
        ):
            raise GateError("consumer_failed")
        self.passed.add(OFFLINE_CASES[7])

    def close_processes(self) -> None:
        first: BaseException | None = None
        for child in reversed(self.children):
            try:
                child.close()
                self.capture(child)
                if child.cleanup_failed:
                    raise GateError("cleanup_incomplete")
            except BaseException as error:  # noqa: BLE001 - attempt independent cleanup/capture and preserve the first primary failure.
                if first is None:
                    first = error
        if first is not None:
            raise first

    def children_settled(self) -> bool:
        """Use actual public exit/reap observations, never a close request alone."""
        return all(
            type(child.returncode) is int and not child.cleanup_failed for child in self.children
        )

    def retain_unresolved_work(self) -> None:
        # This immutable observation aids explicit cleanup; it is never a pass.
        try:
            target = self.retained / "unresolved-work.json"
            if target.exists():
                return
            marker = _read_private(self.work / "owned-marker", 64)
            if marker != b"p3-standalone-package-v1\n":
                return
            states = [
                {
                    "pid": child.pid,
                    "returncode": child.returncode,
                    "cleanup_failed": child.cleanup_failed,
                }
                for child in self.children
            ]
            _write(
                target,
                _json_bytes(
                    {
                        "schema_version": 1,
                        "status": "retained_for_cleanup",
                        "kind": "cleanup_incomplete_observation",
                        "work_directory": str(self.work),
                        "marker_sha256": digest(marker),
                        "children": states,
                    }
                ),
            )
        except Exception:  # noqa: BLE001 - diagnostic retention cannot replace primary cleanup failure.
            return

    def cleanup_resources(self) -> None:
        first: BaseException | None = None
        try:
            self.close_processes()
        except BaseException as error:  # noqa: BLE001 - preserve first while checking actual ownership.
            first = error
        if not self.children_settled():
            self.retain_unresolved_work()
            raise first or GateError("cleanup_incomplete")
        try:
            self.cleanup_lab()
        except BaseException as error:  # noqa: BLE001 - close the independent cleanup child before considering removal.
            if first is None:
                first = error
        try:
            self.close_processes()
        except BaseException as error:  # noqa: BLE001 - every independent child still receives a close attempt.
            if first is None:
                first = error
        if not self.children_settled() or (self.lab_started and not self.lab_cleaned):
            self.retain_unresolved_work()
            raise first or GateError("cleanup_incomplete")
        try:
            self.remove_work()
        except BaseException as error:  # noqa: BLE001 - no downstream operation can mask the first failure.
            if first is None:
                first = error
        if first is not None:
            raise first

    def remove_work(self) -> None:
        if (
            self.work.parent != Path("/private/tmp")
            or not self.work.name.startswith("p3-standalone-package-")
            or self.work.is_symlink()
            or (self.work / "owned-marker").read_bytes() != b"p3-standalone-package-v1\n"
        ):
            raise GateError("cleanup_incomplete")
        shutil.rmtree(self.work)
        if self.work.exists():
            raise GateError("cleanup_incomplete")

    def retained_index(self) -> str:
        records = {}
        for path in sorted(self.retained.rglob("*")):
            info = path.lstat()
            if stat.S_ISDIR(info.st_mode):
                if stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.geteuid():
                    raise GateError("retention_failed")
                continue
            if (
                not stat.S_ISREG(info.st_mode)
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid != os.geteuid()
                or info.st_nlink != 1
            ):
                raise GateError("retention_failed")
            records[str(path.relative_to(self.retained))] = {
                "bytes": info.st_size,
                "sha256": digest(path.read_bytes()),
            }
        raw = _json_bytes({"schema_version": 1, "files": records})
        _write(self.retained / "retained-index.json", raw)
        physical = {
            str(p.relative_to(self.retained)) for p in self.retained.rglob("*") if p.is_file()
        }
        if physical != set(records) | {"retained-index.json"}:
            raise GateError("retention_failed")
        return digest(raw)

    def finish_lab(self, child: OwnedProcess, mode: str, *, cleanup: bool = False) -> None:
        try:
            result = child.wait(timeout=min(40, self.remaining(cleanup=cleanup)))
            child.close()
            raw, _error = self.capture(child)
            expected = {
                "schema_version": 1,
                "mode": mode,
                "status": "passed",
                "cases": list(MODE_CASES[mode]),
            }
            if result.returncode != 0 or not _exact(decode(raw), expected) or child.cleanup_failed:
                self.failure_context(mode, child)
                raise GateError("consumer_failed")
        except Exception:
            self.failure_context(mode, child)
            raise
        self.passed.update(MODE_CASES[mode])

    def failure_context(self, mode: str, child: OwnedProcess) -> None:
        # Bounded diagnostics only. A failed sink never replaces a primary error.
        if (
            self.failure_recorded
            or type(mode) is not str
            or mode not in {*MODES, "node"}
            or type(child.pid) is not int
            or not 1 <= child.pid <= 2147483647
            or (
                child.returncode is not None
                and (type(child.returncode) is not int or not -128 <= child.returncode <= 255)
            )
        ):
            return
        try:
            code, substage = "consumer_failed", mode
            if child.returncode is not None:
                stdout, _stderr = self.capture(child)
                try:
                    value = decode(stdout)
                except GateError:
                    value = {}
                if (
                    value.keys()
                    == {"schema_version", "status", "mode", "stage", "code", "cleanup_failed"}
                    and _exact(value["schema_version"], 1)
                    and value["status"] == "failed"
                    and value["mode"] == mode
                    and type(value["stage"]) is str
                    and value["stage"] in FIXTURE_STAGES
                    and type(value["code"]) is str
                    and value["code"] in SAFE_CHILD_CODES
                    and type(value["cleanup_failed"]) is bool
                ):
                    code, substage = value["code"], value["stage"]
            _write(
                self.retained / "failure-context.json",
                _json_bytes(
                    {
                        "schema_version": 1,
                        "status": "failed",
                        "diagnostic_only": True,
                        "mode": mode,
                        "stage": substage,
                        "code": code,
                        "owned_pid": child.pid,
                        "returncode": child.returncode,
                    }
                ),
            )
            self.failure_recorded = True
        except Exception:  # noqa: BLE001 - diagnostic sink failure cannot replace primary or skip cleanup.
            return

    def lab_command(self, mode: str, *, cleanup: bool = False) -> OwnedProcess:
        assert self.python is not None and self.lab_folder is not None
        role = MODES[mode]
        environment = {**self.base, **self.lab_context}
        if role == "owner":
            environment["P3_STANDALONE_OWNER_PASSWORD"] = self.lab_settings[
                "POSTGRES_MIGRATION_PASSWORD"
            ]
        else:
            environment.update(
                {
                    "P3_STANDALONE_RUNTIME_PASSWORD": self.lab_settings["POSTGRES_PASSWORD"],
                    "P3_STANDALONE_WORK_TOKEN": self.work_token,
                    "P3_STANDALONE_CASE_TOKEN": self.case_token,
                    "P3_STANDALONE_SPECIALIST_TOKEN": self.specialist_token,
                    "P3_STANDALONE_ENDPOINT_FILE": str(
                        self.lab_folder / "specialist-endpoint.json"
                    ),
                }
            )
            if mode == "complete":
                environment["P3_STANDALONE_BARRIER"] = str(
                    self.lab_folder / "completion_returned.reached"
                )
        validate_child_environment(environment, role, mode)
        child = self.start(
            [
                self.python,
                "-I",
                self.synthetic / "projects/delegation-reliability/tests/pg_standalone_cases.py",
                mode,
            ],
            stage="cleanup" if cleanup else "lab_" + mode,
            environment=environment,
            cleanup=cleanup,
        )
        if mode != "complete":
            self.finish_lab(child, mode, cleanup=cleanup)
        return child

    def finish_service(self, peer: OwnedProcess) -> None:
        assert self.lab_folder is not None
        self.stage = "lab_server"
        try:
            result = peer.wait(timeout=min(10, self.remaining()))
            peer.close()
            raw, _stderr = self.capture(peer)
            proof = _read_private(self.lab_folder / "standalone-service.json", 32768)
            validate_service_observation(raw, proof)
            if result.returncode != 0 or peer.cleanup_failed:
                raise GateError("consumer_failed")
        except Exception:
            self.failure_context("node", peer)
            raise

    def lab(self) -> None:
        import importlib.util
        import secrets

        from harness.process_control import FileBarrier

        assert self.python is not None
        spec = importlib.util.spec_from_file_location(
            "p3_standalone_explicit_local_settings", self.root / "local-setup/stack.py"
        )
        if spec is None or spec.loader is None:
            raise GateError("missing_setup")
        setup = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(setup)
        # Reads ordinary local PG/access settings only. No provider configuration.
        values = setup.load_settings()
        self.lab_settings = {
            name: values[name]
            for name in ("POSTGRES_PORT", "POSTGRES_PASSWORD", "POSTGRES_MIGRATION_PASSWORD")
        }
        self.work_token, self.case_token, self.specialist_token = (
            secrets.token_urlsafe(32) for _ in range(3)
        )
        self.lab_folder = self.work / "lab"
        _private_directory(self.lab_folder)
        suffix = uuid4().hex
        self.lab_context = {
            "P3_STANDALONE_PG_PORT": self.lab_settings["POSTGRES_PORT"],
            "P3_STANDALONE_WORK_SCHEMA": "p1_work_standalone_" + suffix,
            "P3_STANDALONE_CASE_SCHEMA": "p3_completion_" + suffix,
            "P3_STANDALONE_SCHEMA": "p3_projection_standalone_" + suffix,
            "P3_STANDALONE_DIRECTORY": str(self.lab_folder),
        }
        for name in (
            "projects/delegation-reliability/tests/pg_standalone_cases.py",
            "projects/delegation-reliability/specialist-ts/tests/fixtures/standalone-server.mjs",
            "local-setup/scripts/p3_case_fixture.py",
            "contracts/delegation/v1.json",
        ):
            raw = (self.root / name).read_bytes()
            _write(self.synthetic / name, raw)
            _write(self.retained / "inputs" / name, raw)
        self.lab_started = True
        self.lab_command("install")
        self.lab_command("seed")
        node_env = {
            **self.base,
            "P3_STANDALONE_DIRECTORY": str(self.lab_folder),
            "P3_STANDALONE_SPECIALIST_TOKEN": self.specialist_token,
            "P3_STANDALONE_READY_FILE": str(self.lab_folder / "specialist.ready"),
            "P3_STANDALONE_ENDPOINT_FILE": str(self.lab_folder / "specialist-endpoint.json"),
            "P3_STANDALONE_STOP_FILE": str(self.lab_folder / "specialist.stop"),
        }
        validate_child_environment(node_env, "node")
        peer = self.start(
            [
                str(self.node),
                self.synthetic
                / "projects/delegation-reliability/specialist-ts/tests/fixtures/standalone-server.mjs",
            ],
            stage="lab_server",
            environment=node_env,
        )
        while not (self.lab_folder / "specialist.ready").exists():
            if peer.returncode is not None:
                self.failure_context("complete", peer)
                raise GateError("consumer_failed")
            self.remaining()
            time.sleep(0.01)
        if _read_private(self.lab_folder / "specialist.ready", 32) != f"{peer.pid}\n".encode():
            raise GateError("consumer_failed")
        barrier = FileBarrier(self.lab_folder, "completion_returned")
        complete = self.lab_command("complete")
        try:
            complete.wait_for_barrier(barrier, timeout=min(30, self.remaining()))
            if (
                _read_private(self.lab_folder / "completion_returned.reached", 32)
                != f"{complete.pid}\n".encode()
            ):
                raise GateError("consumer_failed")
            _read_private(self.lab_folder / "first.json", 32768)
            termination = complete.kill(timeout=min(3, self.remaining()))
            complete.close()
            self.capture(complete)
            if not termination.killed or termination.returncode != -9 or complete.cleanup_failed:
                raise GateError("consumer_failed")
        except Exception:
            self.failure_context("complete", complete)
            raise
        self.lab_terminations += 1
        self.passed.add(LAB_CASES[0])
        for mode in ("effect", "metadata", "negative", "replay", "cancel"):
            self.lab_command(mode)
        _write(self.lab_folder / "specialist.stop", f"{peer.pid}\n".encode())
        self.finish_service(peer)
        self.lab_command("verify")
        proofs = {name: _read_private(self.lab_folder / name, 32768) for name in PROOF_FILES}
        validate_proof_bundle(proofs)
        for name, content in proofs.items():
            _write(self.retained / "proofs" / name, content)
            self.proofs[name] = {"bytes": len(content), "sha256": digest(content)}

    def cleanup_lab(self) -> None:
        if self.lab_started and not self.lab_cleaned:
            self.lab_command("cleanup", cleanup=True)
            self.lab_cleaned = True


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.exit(2, '{"schema_version":1,"status":"failed","code":"invalid_input"}\n')


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    parser = SafeParser(description=__doc__)
    parser.add_argument("--lab", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    run: PackageRun | None = None
    target: Path | None = None
    failure: GateError | None = None
    stage = "input"
    cleanup = False
    try:
        target = target_path(
            root, args.report or Path(".local/validation/p3-package/" + uuid4().hex + ".json")
        )
        _private_directory(target.parent)
        run = PackageRun(root, target)
        snapshot = run.offline()
        if args.lab:
            run.lab()
        if run.source_index() != snapshot:
            raise GateError("invalid_artifact")
    except Exception as error:  # noqa: BLE001 - safe finite tooling boundary; no dependency text.
        failure = error if type(error) is GateError else GateError("unexpected_error")
        if run is not None:
            stage = run.stage
    if run is not None:
        try:
            run.cleanup_resources()
            cleanup = True
        except BaseException:  # noqa: BLE001 - primary failure remains authoritative; unresolved ownership is retained.
            cleanup = False
            if failure is None:
                failure = GateError("cleanup_incomplete")
        try:
            index_sha = run.retained_index()
            validate_retained_index(run.retained, index_sha)
        except Exception:  # noqa: BLE001 - safe finite artifact boundary.
            if failure is None:
                failure = GateError("retention_failed")
            index_sha = ""
        cases = OFFLINE_CASES + (LAB_CASES if args.lab else ())
        if failure is None:
            value = {
                "schema_version": 1,
                "status": "passed",
                "mode": "lab" if args.lab else "offline",
                "tests": len(cases),
                "passed": len(cases),
                "errors": 0,
                "failures": 0,
                "skipped": 0,
                "cleanup_complete": cleanup,
                "provider_calls": False,
                "authority_runtime_changes": False,
                "full_charter_release_claimed": False,
                "offline_assertions": 8,
                "lab_assertions": 8 if args.lab else 0,
                "child_terminations": run.lab_terminations,
                "duration_seconds": time.monotonic() - run.started,
                "child_commands": run.commands,
                "case_results": [
                    {"name": name, "status": "passed", "code": "ok"} for name in cases
                ],
                "artifacts": run.artifacts,
                "proofs": run.proofs,
                "node_version": "24.22.2",
                "python_version": "3.14.10",
                "platform": "darwin_arm64",
                "retained_index_sha256": index_sha,
            }
            if run.passed != set(cases):
                failure = GateError("invalid_report")
            else:
                try:
                    validated_report(_json_bytes(value))
                except GateError as error:
                    failure = error
        if failure is not None:
            value = {
                "schema_version": 1,
                "status": "failed",
                "mode": "lab" if args.lab else "offline",
                "code": failure.code,
                "stage": stage,
                "completed_assertions": len(run.passed),
                "planned_assertions": len(cases),
                "cleanup_complete": cleanup,
                "provider_calls": False,
            }
        raw = _json_bytes(value)
        if target is not None:
            _write(target, raw)
        print(raw.decode(), end="")
        return int(failure is not None)
    raise failure or GateError("unexpected_error")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GateError as error:
        print(json.dumps({"schema_version": 1, "status": "failed", "code": error.code}))
        raise SystemExit(1) from None
