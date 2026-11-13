"""Explicit complete P3 acceptance selectors; fresh bounded local evidence only."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import stat
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "local-setup/scripts"))

from harness.process_control import OwnedProcess, ProcessControlError

DEADLINE_SECONDS = 240
MAX_CAPTURE_BYTES = 32768
SPECS = {
    "P3-01": ("p3_completion_check", "p3-completion", 13),
    "P3-03": ("p3_contract_acceptance_check", "p3-contract-acceptance", 8),
    "P3-11": ("p3_contract_acceptance_check", "p3-contract-acceptance", 12),
}
ENVIRONMENT_KEYS = frozenset(
    {"PATH", "HOME", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL", "LC_CTYPE", "SYSTEMROOT"}
)


class AcceptanceError(ValueError):
    """One fixed acceptance outcome; dependency text is never exposed."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def child_environment() -> dict[str, str]:
    return {
        **{key: os.environ[key] for key in ENVIRONMENT_KEYS if key in os.environ},
        "CI": "1",
        "NO_COLOR": "1",
    }


def private_directory(path: Path) -> None:
    if ".." in path.parts or any(part.is_symlink() for part in (path, *path.parents)):
        raise AcceptanceError("mapping_invalid")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    observed = path.stat()
    if observed.st_uid != os.getuid() or stat.S_IMODE(observed.st_mode) != 0o700:
        raise AcceptanceError("mapping_invalid")


def report_target(root: Path, path: Path) -> Path:
    value = (path if path.is_absolute() else root / path).absolute()
    allowed = (root / ".local/validation", root / ".local/harness")
    if ".." in value.parts or not any(value.is_relative_to(base) for base in allowed):
        raise AcceptanceError("mapping_invalid")
    private_directory(value.parent)
    if value.exists() or value.is_symlink():
        raise AcceptanceError("mapping_invalid")
    return value


def retain(root: Path, path: Path, value: dict[str, Any]) -> None:
    target = report_target(root, path)
    raw = (json.dumps(value, sort_keys=True) + "\n").encode()
    if len(raw) > MAX_CAPTURE_BYTES:
        raise AcceptanceError("mapping_invalid")
    with os.fdopen(
        os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb"
    ) as stream:
        stream.write(raw)


def validate_component(raw: bytes, case_id: str) -> dict[str, Any]:
    if case_id not in SPECS or not raw or len(raw) > MAX_CAPTURE_BYTES:
        raise AcceptanceError("mapping_invalid")
    module_name, _, expected = SPECS[case_id]
    module = importlib.import_module(module_name)
    try:
        value: dict[str, Any] = (
            module.validated_report(raw)
            if case_id == "P3-01"
            else module.validated_report(raw, case_id)
        )
    except (ValueError, TypeError, KeyError, RuntimeError) as error:
        raise AcceptanceError("assertion_failed") from error
    if (
        type(value) is not dict
        or type(value.get("tests")) is not int
        or value["tests"] != expected
        or value.get("cleanup_complete") is not True
        or value.get("status") != "passed"
        or any(
            type(value.get(key)) is not int or value[key] != 0
            for key in ("skipped", "errors", "failures")
        )
    ):
        raise AcceptanceError("assertion_failed")
    return value


def read_component(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_CAPTURE_BYTES:
            raise AcceptanceError("assertion_failed")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            return stream.read(MAX_CAPTURE_BYTES + 1)
    finally:
        os.close(descriptor)


def run_component(root: Path, case_id: str, evidence: Path, deadline: float) -> dict[str, Any]:
    module_name, prefix, _ = SPECS[case_id]
    script = root / "local-setup/scripts" / (module_name + ".py")
    if not script.is_file() or script.is_symlink():
        raise AcceptanceError("setup_required")
    target = root / ".local/validation" / prefix / ("acceptance-" + uuid4().hex + ".json")
    command = [sys.executable, "-I", str(script)]
    if case_id != "P3-01":
        command.extend(("--case", case_id))
    command.extend(("--report", str(target)))
    with tempfile.TemporaryDirectory(prefix="capture-", dir=evidence) as temporary:
        capture = Path(temporary).resolve()
        with OwnedProcess(
            command,
            cwd=root,
            env=child_environment(),
            output_directory=capture / "process",
            max_output_bytes=MAX_CAPTURE_BYTES,
        ) as child:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AcceptanceError("test_error")
            observed = child.wait(timeout=remaining)
        stdout = (capture / "process/stdout.bin").read_bytes()
        stderr = (capture / "process/stderr.bin").read_bytes()
        if child.cleanup_failed or stderr:
            raise AcceptanceError("test_error")
        if observed.returncode != 0:
            # Only the closed fixed failure code is relevant; raw child output is ephemeral.
            try:
                failed = json.loads(stdout)
            except (ValueError, UnicodeError):
                failed = {}
            if type(failed) is dict and failed.get("code") == "missing_setup":
                raise AcceptanceError("setup_required")
            raise AcceptanceError("assertion_failed")
        raw = read_component(target)
        value = validate_component(raw, case_id)
        if validate_component(stdout, case_id) != value:
            raise AcceptanceError("assertion_failed")
        retain(
            root,
            evidence / "component.json",
            {
                "caseId": case_id,
                "path": str(target.relative_to(root)),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "testCount": value["tests"],
                "owned_child_cleanup_complete": True,
            },
        )
        return value


def envelope(case_id: str, code: str, count: int, duration: float) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "caseId": case_id,
        "mode": "lab",
        "status": "passed"
        if code == "passed"
        else "incomplete"
        if code == "setup_required"
        else "failed",
        "testCount": count,
        "skippedCount": 0,
        "failureCount": 1 if code == "assertion_failed" else 0,
        "errorCount": 1 if code in {"mapping_invalid", "test_error"} else 0,
        "durationSeconds": duration,
        "code": code,
    }


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=tuple(SPECS), required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    started = time.monotonic()
    code, count = "test_error", 0
    target: Path | None = None
    evidence: Path | None = None
    try:
        target = report_target(root, args.report)
        base = root / ".local/validation/p3-acceptance"
        private_directory(base)
        evidence = base / uuid4().hex
        evidence.mkdir(mode=0o700)
        value = run_component(root, args.case, evidence, started + DEADLINE_SECONDS - 10)
        if time.monotonic() - started >= DEADLINE_SECONDS:
            raise AcceptanceError("test_error")
        count, code = value["tests"], "passed"
    except AcceptanceError as error:
        code = error.code
    except (ProcessControlError, OSError, ValueError, ImportError):
        code = "test_error"
    except Exception:  # noqa: BLE001 - fixed CLI boundary excludes unexpected private text
        code = "test_error"
    result = envelope(args.case, code, count, time.monotonic() - started)
    try:
        if target is not None:
            retain(root, target, result)
        if evidence is not None:
            retain(root, evidence / "summary.json", result)
    except (AcceptanceError, OSError):
        result = envelope(args.case, "mapping_invalid", 0, time.monotonic() - started)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "passed" else 2 if result["status"] == "incomplete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
