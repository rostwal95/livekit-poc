"""Explicit offline P1 wheel/sdist qualification; host tooling, never product code."""

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import os
import stat
import sys
import tarfile
import tempfile
import time
import zipfile
from collections.abc import Mapping, Sequence
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import NoReturn
from uuid import uuid4

from .process_control import OwnedProcess

ROOT = Path(__file__).resolve().parents[1]
MEMBER = Path("projects/agent-continuity/python")
MAX_FILES = 512
MAX_BYTES = 8 * 1024 * 1024
MAX_FILE_BYTES = 512 * 1024
PRIVATE_SENTINELS = (b"private-configuration-sentinel", b"private-storage-sentinel")
ERRORS = frozenset(
    {
        "invalid_input",
        "missing_setup",
        "build_failed",
        "invalid_artifact",
        "consumer_failed",
        "deadline_exceeded",
        "cleanup_incomplete",
    }
)


class PackageCheckError(RuntimeError):
    def __init__(self, code: str) -> None:
        if type(code) is not str or code not in ERRORS:
            raise ValueError("Unsupported package-check failure code")
        self.code = code
        super().__init__("The isolated package requirement did not pass")


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.exit(2, '{"status":"failed","code":"invalid_input"}\n')


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def archive_name(name: str) -> None:
    path = PurePosixPath(name)
    if (
        not name
        or name.startswith("/")
        or "\\" in name
        or ":" in name
        or any(part in {"", ".", ".."} for part in name.rstrip("/").split("/"))
        or path.is_absolute()
    ):
        raise PackageCheckError("invalid_artifact")


def source_payload(member: Path) -> dict[str, bytes]:
    package = member / "src/continuity_lab"
    if not package.is_dir() or package.is_symlink():
        raise PackageCheckError("missing_setup")
    result = {}
    for path in sorted(package.rglob("*")):
        if path.is_symlink():
            raise PackageCheckError("invalid_artifact")
        if path.is_file() and (path.suffix == ".py" or path.name == "py.typed"):
            result[path.relative_to(package.parent).as_posix()] = path.read_bytes()
    if not result or "continuity_lab/py.typed" not in result:
        raise PackageCheckError("invalid_artifact")
    return result


def metadata(raw: bytes) -> None:
    value = BytesParser().parsebytes(raw)
    required = {
        'psycopg[binary]==3.3.8; extra == "postgres"',
        'prometheus-client==0.26.0; extra == "postgres"',
        'opentelemetry-api==1.45.2; extra == "telemetry"',
        'opentelemetry-sdk==1.45.2; extra == "telemetry"',
        'opentelemetry-exporter-otlp-proto-http==1.45.2; extra == "telemetry"',
    }
    if (
        value.get_all("Name") != ["agent-continuity"]
        or value.get_all("Version") != ["0.1.0"]
        or len(value.get_all("Requires-Python", [])) != 1
        or set(value["Requires-Python"].replace(" ", "").split(",")) != {">=3.14", "<3.15"}
        or len(value.get_all("Provides-Extra", [])) != 2
        or set(value.get_all("Provides-Extra", [])) != {"postgres", "telemetry"}
        or len(value.get_all("Requires-Dist", [])) != len(required)
        or set(value.get_all("Requires-Dist", [])) != required
    ):
        raise PackageCheckError("invalid_artifact")


def wheel_payload(path: Path) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    entries: dict[str, bytes] = {}
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if not 1 <= len(infos) <= MAX_FILES or sum(info.file_size for info in infos) > MAX_BYTES:
            raise PackageCheckError("invalid_artifact")
        for info in infos:
            archive_name(info.filename)
            if (
                stat.S_ISLNK(info.external_attr >> 16)
                or info.file_size > MAX_FILE_BYTES
                or info.filename in entries
            ):
                raise PackageCheckError("invalid_artifact")
            if info.is_dir():
                continue
            raw = archive.read(info)
            if info.filename.startswith("continuity_lab/"):
                result[info.filename] = raw
            elif not info.filename.startswith("agent_continuity-0.1.0.dist-info/"):
                raise PackageCheckError("invalid_artifact")
            entries[info.filename] = raw
    try:
        metadata(entries["agent_continuity-0.1.0.dist-info/METADATA"])
        if entries["agent_continuity-0.1.0.dist-info/top_level.txt"].strip() != b"continuity_lab":
            raise PackageCheckError("invalid_artifact")
        parser = configparser.ConfigParser()
        parser.read_string(entries["agent_continuity-0.1.0.dist-info/entry_points.txt"].decode())
        if dict(parser["console_scripts"]) != {
            "agent-continuity-inquiry": "continuity_lab.execution_cli:main",
            "agent-continuity-worker": "continuity_lab.worker_cli:main",
        }:
            raise PackageCheckError("invalid_artifact")
    except (KeyError, UnicodeError, configparser.Error) as error:
        raise PackageCheckError("invalid_artifact") from error
    return result


def sdist_payload(path: Path) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    seen = set()
    required_files = set()
    with tarfile.open(path, "r:gz") as archive:
        infos = archive.getmembers()
        if not 1 <= len(infos) <= MAX_FILES or sum(info.size for info in infos) > MAX_BYTES:
            raise PackageCheckError("invalid_artifact")
        for info in infos:
            archive_name(info.name)
            if (
                info.name in seen
                or not (info.isfile() or info.isdir())
                or info.size > MAX_FILE_BYTES
                or not info.name.startswith("agent_continuity-0.1.0/")
                and info.name != "agent_continuity-0.1.0"
            ):
                raise PackageCheckError("invalid_artifact")
            seen.add(info.name)
            if not info.isfile():
                continue
            stream = archive.extractfile(info)
            if stream is None:
                raise PackageCheckError("invalid_artifact")
            raw = stream.read(MAX_FILE_BYTES + 1)
            if len(raw) != info.size:
                raise PackageCheckError("invalid_artifact")
            relative = info.name.removeprefix("agent_continuity-0.1.0/")
            if relative.startswith("src/continuity_lab/"):
                result[relative.removeprefix("src/")] = raw
            if relative == "PKG-INFO":
                metadata(raw)
            if relative in {"PKG-INFO", "README.md", "pyproject.toml"}:
                required_files.add(relative)
    if required_files != {"PKG-INFO", "README.md", "pyproject.toml"}:
        raise PackageCheckError("invalid_artifact")
    return result


class Runner:
    def __init__(self, root: Path, uv: Path, private: Path) -> None:
        self.root, self.uv, self.private = root, uv, private
        self.started, self.commands = time.monotonic(), 0
        self.consumer_hashes: dict[str, str] = {}

    def command(self, argv: Sequence[str], *, code: str, maximum: float = 60) -> bytes:
        remaining = min(maximum, 360 - (time.monotonic() - self.started))
        if remaining <= 0:
            raise PackageCheckError("deadline_exceeded")
        self.commands += 1
        environment = {
            "PATH": os.defpath,
            "LANG": "C.UTF-8",
            "UV_PYTHON_DOWNLOADS": "never",
            "UV_NO_PROGRESS": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        try:
            with OwnedProcess(
                list(argv),
                cwd=self.private,
                env=environment,
                output_directory=self.private / f"command-{self.commands}",
                max_output_bytes=262144,
            ) as child:
                if child.wait(timeout=remaining).returncode != 0:
                    raise PackageCheckError(code)
                raw = (self.private / f"command-{self.commands}/stdout.bin").read_bytes()
                stderr = (self.private / f"command-{self.commands}/stderr.bin").read_bytes()
                if len(raw) > 131072:
                    raise PackageCheckError(code)
                if code == "consumer_failed" and any(
                    sentinel in raw + stderr for sentinel in PRIVATE_SENTINELS
                ):
                    raise PackageCheckError(code)
                return raw
        except PackageCheckError:
            raise
        except Exception as error:
            raise PackageCheckError(code) from error

    def build(self, source: Path, out: Path, flag: str) -> Path:
        out.mkdir()
        self.command(
            [
                str(self.uv),
                "--no-config",
                "build",
                "--offline",
                "--no-python-downloads",
                "--python",
                sys.executable,
                flag,
                "--out-dir",
                str(out),
                str(source),
            ],
            code="build_failed",
        )
        suffix = "*.tar.gz" if flag == "--sdist" else "*.whl"
        artifacts = list(out.glob(suffix))
        if len(artifacts) != 1:
            raise PackageCheckError("invalid_artifact")
        return artifacts[0]

    def environment(self, wheel: Path, name: str, *, postgres: bool = False) -> Path:
        venv = self.private / name
        self.command(
            [sys.executable, "-I", "-m", "venv", "--without-pip", str(venv)], code="consumer_failed"
        )
        python = venv / "bin/python"
        package = str(wheel) + ("[postgres]" if postgres else "")
        arguments = [
            str(self.uv),
            "--no-config",
            "pip",
            "install",
            "--offline",
            "--python",
            str(python),
        ]
        if not postgres:
            arguments.append("--no-deps")
        self.command([*arguments, package], code="consumer_failed")
        return python

    def consumer(self, python: Path, name: str) -> dict[str, object]:
        source = self.root / "projects/agent-continuity/examples" / name
        if (
            name not in {"inquiry_consumer.py", "resource_consumer.py", "postgres_consumer.py"}
            or source.is_symlink()
        ):
            raise PackageCheckError("consumer_failed")
        content = source.read_bytes()
        observed = digest(content)
        if name in self.consumer_hashes and self.consumer_hashes[name] != observed:
            raise PackageCheckError("consumer_failed")
        self.consumer_hashes[name] = observed
        target = self.private / (python.parent.parent.name + "-" + name)
        target.write_bytes(content)
        raw = self.command([str(python), "-I", str(target)], code="consumer_failed", maximum=20)
        if any(sentinel in raw for sentinel in PRIVATE_SENTINELS):
            raise PackageCheckError("consumer_failed")
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError) as error:
            raise PackageCheckError("consumer_failed") from error
        if (
            type(value) is not dict
            or value.get("schema_version") != 1
            or value.get("status") != "passed"
        ):
            raise PackageCheckError("consumer_failed")
        return value


def retain_artifacts(directory: Path, artifacts: Mapping[str, Path]) -> None:
    """Retain only the validated product archives, never captured build output."""
    if (
        set(artifacts) != {"wheel", "sdist", "rebuilt_wheel"}
        or directory.exists()
        or directory.is_symlink()
    ):
        raise PackageCheckError("invalid_artifact")
    directory.mkdir(mode=0o700)
    for label, source in artifacts.items():
        target = directory / label
        target.mkdir(mode=0o700)
        raw = source.read_bytes()
        if len(raw) > MAX_BYTES or source.is_symlink():
            raise PackageCheckError("invalid_artifact")
        path = target / source.name
        with os.fdopen(
            os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb"
        ) as stream:
            stream.write(raw)
        if digest(path.read_bytes()) != digest(raw):
            raise PackageCheckError("invalid_artifact")


def check(root: Path, uv: Path, private: Path, retained: Path) -> dict[str, object]:
    member = root / MEMBER
    expected = source_payload(member)
    runner = Runner(root, uv, private)
    wheel = runner.build(member, private / "direct-wheel", "--wheel")
    sdist = runner.build(member, private / "source-dist", "--sdist")
    if wheel_payload(wheel) != expected or sdist_payload(sdist) != expected:
        raise PackageCheckError("invalid_artifact")
    rebuilt = runner.build(sdist, private / "rebuilt-wheel", "--wheel")
    if wheel_payload(rebuilt) != expected or source_payload(member) != expected:
        raise PackageCheckError("invalid_artifact")
    base = runner.environment(wheel, "base")
    rebuilt_python = runner.environment(rebuilt, "rebuilt")
    postgres = runner.environment(wheel, "postgres", postgres=True)
    consumers = {
        "direct_wheel": runner.consumer(base, "inquiry_consumer.py"),
        "sdist_rebuilt_wheel": runner.consumer(rebuilt_python, "inquiry_consumer.py"),
        "thread_ownership": runner.consumer(base, "resource_consumer.py"),
        "postgres_extra_failure": runner.consumer(postgres, "postgres_consumer.py"),
    }
    runner.command(
        [str(postgres), "-I", str(postgres.parent / "agent-continuity-worker"), "--help"],
        code="consumer_failed",
        maximum=10,
    )
    # Qualify original M1 entrypoint and the installed inquiry console script.
    runner.command(
        [str(base), "-I", "-m", "continuity_lab", "demo"], code="consumer_failed", maximum=10
    )
    cli = base.parent / "agent-continuity-inquiry"
    db = private / "cli.sqlite3"
    runner.command(
        [
            str(base),
            "-I",
            str(cli),
            "--db",
            str(db),
            "migrate",
            "--backup",
            str(private / "cli-backup.sqlite3"),
        ],
        code="consumer_failed",
        maximum=10,
    )
    accepted_raw = runner.command(
        [
            str(base),
            "-I",
            str(cli),
            "--db",
            str(db),
            "submit",
            "--scope",
            "cli-fixture",
            "--key",
            "cli-original",
            "--booking",
            "DEMO-BK-001",
            "--check-in",
            "2030-12-10",
            "--confirm",
        ],
        code="consumer_failed",
        maximum=10,
    )
    accepted = json.loads(accepted_raw)
    task = accepted["execution"]["task_id"]
    observed = json.loads(
        runner.command(
            [
                str(base),
                "-I",
                str(cli),
                "--db",
                str(db),
                "get",
                "--scope",
                "cli-fixture",
                "--task-id",
                task,
            ],
            code="consumer_failed",
            maximum=10,
        )
    )
    if observed != accepted["execution"]:
        raise PackageCheckError("consumer_failed")
    retain_artifacts(retained, {"wheel": wheel, "sdist": sdist, "rebuilt_wheel": rebuilt})
    return {
        "schema_version": 1,
        "status": "passed",
        "distribution": "agent-continuity",
        "version": "0.1.0",
        "source_files": len(expected),
        "source_payload_sha256": {name: digest(raw) for name, raw in expected.items()},
        "artifacts": {
            "wheel": {"name": wheel.name, "sha256": digest(wheel.read_bytes())},
            "sdist": {"name": sdist.name, "sha256": digest(sdist.read_bytes())},
            "rebuilt_wheel": {"name": rebuilt.name, "sha256": digest(rebuilt.read_bytes())},
        },
        "wheel_sdist_source_payload_equal": True,
        "root_services_and_harness_absent": True,
        "typed_marker_present": True,
        "fresh_venvs": 3,
        "isolated_interpreter": True,
        "python_version": sys.version.split()[0],
        "consumers": consumers,
        "legacy_m1_cli": True,
        "installed_inquiry_cli": True,
        "installed_worker_help_with_postgres_extra": True,
        "elapsed_seconds": time.monotonic() - runner.started,
        "command_count": runner.commands,
        "driver_sha256": digest(Path(__file__).read_bytes()),
        "consumer_source_sha256": runner.consumer_hashes,
        "retained_artifacts_directory": retained.name,
        "binary_reproducibility_claimed": False,
        "postgres_positive_store_gate": "separate",
        "platform_matrix": "not_established",
        "full_p1_release": "incomplete",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = SafeParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--uv", type=Path, default=Path(sys.executable).with_name("uv"))
    args = parser.parse_args(argv)
    report = args.report or ROOT / ".local/validation/p1-package" / uuid4().hex / "summary.json"
    result: Mapping[str, object]
    try:
        if not args.uv.is_file() or report.exists() or report.is_symlink():
            raise PackageCheckError("missing_setup")
        report.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="p1-package-") as directory:
            result = check(
                ROOT,
                args.uv,
                Path(directory).resolve(),
                report.with_name(report.stem + "-artifacts"),
            )
        result = {**result, "owned_temporary_cleanup_verified": True}
    except Exception as error:  # noqa: BLE001 - retain fixed codes without private build/process text
        result = {
            "schema_version": 1,
            "status": "failed",
            "code": error.code if isinstance(error, PackageCheckError) else "invalid_artifact",
            "full_p1_release": "incomplete",
        }
    try:
        with os.fdopen(
            os.open(report, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "w"
        ) as stream:
            stream.write(json.dumps(result, indent=2, allow_nan=False) + "\n")
    except OSError:
        print('{"status":"failed","code":"cleanup_incomplete"}')
        return 1
    print(json.dumps({"status": result["status"], "report": str(report)}))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
