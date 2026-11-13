"""Explicit source/isolated-package qualification for the scripted image capability.

No providers, private settings, database, compiler or listener are used on import.
This host tool verifies source-bound synthetic fixtures, not OCR/model accuracy.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import time
from pathlib import Path
from typing import Any, NoReturn
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import p3_package_check as packages
from p3_document_evidence import (
    CASE_NAMES,
    MAX_CAPTURE,
    MAX_CHILDREN,
    MAX_PROOF,
    MAX_REPORT,
    MAX_STREAM,
    MODE,
    PROOF_NAMES,
    SAFE_CODES,
    GateError,
    cases,
    decode,
    digest,
    exact,
    is_hash,
    json_bytes,
    natural,
    private_directory,
    read_private,
    target_path,
    validate_bundle,
    validate_environment,
    validate_reply,
    write_private,
)
from p3_document_package import GroupedOwnedProcess, ScopedPackageRun

sys.path.insert(0, str(ROOT))
from harness.process_control import FileBarrier, OwnedProcess

FIXTURE_NODE = "projects/delegation-reliability/specialist-ts/tests/fixtures/document-cases.mjs"
FIXTURE_PYTHON = "projects/delegation-reliability/tests/document_cases.py"
ORACLE_HELPER = "projects/delegation-reliability/tests/test_document_oracle.py"
PROJECT = "projects/delegation-reliability/specialist-ts"
STAGES = frozenset(
    {
        "compile",
        "fresh-package",
        "python-venv",
        "python-install",
        "npm-install",
        "installed-imports",
        "node-producer",
        "node-server",
        "python-contracts",
        "python-http",
    }
)
BUILDER_EXPECTED_CHILDREN = 17
MAX_RETAINED_BYTES = 16777216
MAX_RETAINED_FILES = 2048


def _translate(error: BaseException) -> GateError:
    if isinstance(error, GateError):
        return error
    if isinstance(error, packages.GateError):
        return GateError({"consumer_failed": "component_failed"}.get(error.code, error.code))
    return GateError("unexpected_error")


ENROLLMENT_NAMES = (
    "bad_crc",
    "truncated",
    "trailing",
    "apng",
    "unsupported",
    "bomb",
    "bad_filter",
    "zlib_trailing",
    "huge_header",
)


def validate_enrollment(raw: bytes) -> dict[str, Any]:
    value = decode(raw, 8192)
    if (
        value.keys() != {"schema_version", "kind", "records"}
        or not exact(value["schema_version"], 1)
        or value["kind"] != "document.image-references"
        or type(value["records"]) is not list
        or len(value["records"]) != 9
    ):
        raise GateError("invalid_proof")
    for name, row in zip(ENROLLMENT_NAMES, value["records"], strict=True):
        if (
            type(row) is not dict
            or row.keys() != {"name", "reference"}
            or row["name"] != name
            or type(row["reference"]) is not dict
        ):
            raise GateError("invalid_proof")
        ref = row["reference"]
        if (
            ref.keys()
            != {"source_id", "version", "sha256", "media_type", "byte_length", "width", "height"}
            or ref["source_id"] != "document_" + name
            or ref["version"] != "document_v1"
            or ref["media_type"] != "image/png"
            or not is_hash(ref["sha256"])
            or not natural(ref["byte_length"], 1, 2097152)
            or not natural(ref["width"], 1, 2048)
            or not natural(ref["height"], 1, 2048)
        ):
            raise GateError("invalid_proof")
    return value


def validate_failure_sidecar(raw: bytes, *, node: bool) -> dict[str, Any]:
    value = decode(raw, 8192)
    modes = {"node-producer", "node-server"} if node else {"python-contracts", "python-http"}
    stages = (
        {"setup", "producer", "registry", "listen", "serve", "close"}
        if node
        else {
            "setup",
            "contracts",
            "pixels",
            "imports",
            "snapshots",
            "positive_complete",
            "positive_missing",
            "positive_ambiguous",
            "positive_adversarial",
            "grants",
            "inaccessible",
            "size_bounds",
            "corrupt_images",
            "bounded_decode",
            "expiry",
            "timeout",
            "cancel",
            "close",
        }
    )
    if (
        value.keys() != {"schema_version", "status", "mode", "stage", "code", "cleanup_complete"}
        or not exact(value["schema_version"], 1)
        or value["status"] != "failed"
        or type(value["mode"]) is not str
        or value["mode"] not in modes
        or type(value["stage"]) is not str
        or value["stage"] not in stages
        or type(value["code"]) is not str
        or value["code"] not in (SAFE_CODES - {"ok"}) | {"fixture_failed"}
        or type(value["cleanup_complete"]) is not bool
    ):
        raise GateError("invalid_proof")
    return value


class DocumentRun(packages.PackageRun):
    """Reuse owned child settlement and exact-marker cleanup; no lab methods run."""

    def __init__(self, root: Path, report: Path, *, installed: bool) -> None:
        super().__init__(root, report)
        self.installed = installed
        total = 360 if installed else 120
        self.deadline = self.started + total - 20
        self.final_deadline = self.started + total
        assert self.node is not None
        self.base = {
            "PATH": str(Path(self.node).resolve().parent) + ":/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "CI": "1",
            "NO_COLOR": "1",
            "COREPACK_HOME": "/private/tmp/livekit-pinned-corepack",
            "COREPACK_ENABLE_NETWORK": "0",
        }
        self.nested_builder: ScopedPackageRun | None = None
        self.nested_commands = 0
        self.nested_capture_bytes = 0
        self.nested_cleanup_known = True
        self.capture_versions: dict[int, list[str]] = {}
        self.tokens = (secrets.token_urlsafe(32), secrets.token_urlsafe(32))
        self.directory = self.work / "journey"
        self.inputs = self.work / "inputs"
        private_directory(self.directory)
        private_directory(self.inputs)
        self.node_fixture = root / FIXTURE_NODE
        self.python_fixture = root / FIXTURE_PYTHON
        self.client_python = Path(sys.executable)
        self.bundle: dict[str, Any] = {}
        self.phase: dict[str, Any] = {}
        self.oracle: dict[str, Any] = {}
        self.builder_report: dict[str, Any] | None = None
        self.before: dict[str, str] = {}
        self.barriers = {
            name: FileBarrier(self.directory, name)
            for name in (
                "document_server_ready",
                "document_post_decode_held",
                "document_timeout_held",
                "document_timeout_verified",
                "document_cancel_held",
                "document_cancel_verified",
                "document_close_held",
                "document_close_requested",
                "document_close_incomplete",
            )
        }

    def nested_usage(self) -> tuple[int, int, int]:
        if self.nested_builder is None:
            return self.nested_commands, self.nested_capture_bytes, 0
        return (
            self.nested_builder.commands,
            self.nested_builder.captured,
            sum(self.nested_builder.reservations.values()),
        )

    def start(
        self,
        argv: list[str | Path],
        *,
        stage: str,
        cwd: Path | None = None,
        environment: dict[str, str] | None = None,
        cleanup: bool = False,
    ) -> OwnedProcess:
        nested_children, nested_capture, nested_reserved = self.nested_usage()
        if stage not in STAGES or self.commands + nested_children >= MAX_CHILDREN:
            raise GateError("child_budget")
        self.remaining(cleanup=cleanup)
        environment = environment or self.base
        validate_environment(
            environment,
            stage
            if stage in {"node-producer", "node-server", "python-contracts", "python-http"}
            else "build",
        )
        available = (
            MAX_CAPTURE
            - self.captured
            - nested_capture
            - nested_reserved
            - sum(self.reservations.values())
        )
        limit = min(MAX_STREAM, available // 2)
        if limit < 1:
            raise GateError("child_budget")
        self.commands += 1
        self.stage = stage
        output = self.work / "raw-commands" / f"{self.commands:02d}-{stage}"
        private_directory(output.parent)
        child = GroupedOwnedProcess(
            [str(v) for v in argv],
            cwd=cwd or self.work,
            env=environment,
            output_directory=output,
            max_output_bytes=limit,
            final_deadline=self.final_deadline,
        )
        self.children.append(child)
        self.outputs[child.pid] = output
        self.reservations[child.pid] = 2 * limit
        return child

    def capture(self, child: OwnedProcess) -> tuple[bytes, bytes]:
        directory = self.outputs[child.pid]
        raw = tuple(
            read_private(directory / n, MAX_STREAM, empty=True)
            for n in ("stdout.bin", "stderr.bin")
        )
        safe: list[bytes] = []
        leaked = False
        for stream in raw:
            for token in self.tokens:
                if token.encode() in stream:
                    leaked = True
                    stream = stream.replace(token.encode(), b"[redacted]")
            safe.append(stream)
        if type(child.returncode) is not int or child.cleanup_failed:
            if leaked:
                raise GateError("unsafe_capture")
            return safe[0], safe[1]
        key = digest(safe[0] + b"\0" + safe[1])
        versions = self.capture_versions.setdefault(child.pid, [])
        if key not in versions:
            if len(versions) >= 3:
                raise GateError("retention_failed")
            suffix = "" if not versions else f"-cleanup-{len(versions)}"
            retained = self.retained / "commands" / (directory.name + suffix)
            private_directory(retained)
            for name, stream in zip(("stdout.bin", "stderr.bin"), safe, strict=True):
                write_private(retained / name, stream)
            self.captured += sum(map(len, raw))
            versions.append(key)
        self.reservations.pop(child.pid, None)
        self.accounted.add(child.pid)
        if self.captured + self.nested_usage()[1] > MAX_CAPTURE:
            raise GateError("child_budget")
        if leaked:
            raise GateError("unsafe_capture")
        return safe[0], safe[1]

    def finish(self, child: OwnedProcess) -> bytes:
        primary: BaseException | None = None
        result = None
        try:
            result = child.wait(timeout=min(60, self.remaining()))
        except BaseException as error:  # noqa: BLE001 - preserve primary while attempting independent cleanup.
            primary = error
        try:
            child.close()
        except BaseException as error:  # noqa: BLE001 - attempt each actual owner; do not mask first failure.
            if primary is None:
                primary = error
        output = b""
        try:
            output, _ = self.capture(child)
        except BaseException as error:  # noqa: BLE001 - safe bounded retention is independent of child settlement.
            if primary is None:
                primary = error
        if primary is not None:
            raise _translate(primary)
        if result is None or result.returncode != 0 or child.cleanup_failed:
            raise GateError("component_failed")
        return output

    def fixture_environment(self, role: str) -> dict[str, str]:
        result = {
            **self.base,
            "P3_DOCUMENT_DIRECTORY": str(self.directory),
            "P3_DOCUMENT_FIXTURES": str(self.inputs),
        }
        if role in {"node-server", "python-http"}:
            result.update(P3_DOCUMENT_TOKEN=self.tokens[0], P3_DOCUMENT_OTHER_TOKEN=self.tokens[1])
        validate_environment(result, role)
        return result

    def source_index(self) -> dict[str, str]:
        fixed = {
            "uv.lock",
            "pnpm-lock.yaml",
            "pyproject.toml",
            "harness/process_control.py",
            "local-setup/scripts/p3_document_check.py",
            "local-setup/scripts/p3_document_evidence.py",
            "local-setup/scripts/p3_document_package.py",
            "local-setup/scripts/p3_package_check.py",
            "projects/agent-continuity/python/README.md",
            "projects/agent-continuity/python/pyproject.toml",
            FIXTURE_NODE,
            FIXTURE_PYTHON,
            ORACLE_HELPER,
            PROJECT + "/README.md",
            PROJECT + "/package.json",
            PROJECT + "/tsconfig.json",
            "projects/delegation-reliability/python/README.md",
            "projects/delegation-reliability/python/pyproject.toml",
        }
        for folder, suffixes in (
            ("projects/agent-continuity/python/src/continuity_lab", {".py", ".typed"}),
            (
                "projects/delegation-reliability/python/src/delegation_reliability",
                {".py", ".typed"},
            ),
            (PROJECT + "/src", {".ts"}),
            (PROJECT + "/dist", {".js", ".ts"}),
            (PROJECT + "/examples", {".mjs"}),
            ("projects/delegation-reliability/examples", {".py"}),
            ("contracts/delegation", {".json", ".png"}),
        ):
            for path in (self.root / folder).rglob("*"):
                if "__pycache__" not in path.parts and path.is_file() and path.suffix in suffixes:
                    fixed.add(path.relative_to(self.root).as_posix())
        output = {}
        for name in sorted(fixed):
            path = self.root / name
            if not path.is_file() or path.is_symlink() or path.stat().st_size > 2097152:
                raise GateError("invalid_artifact")
            output[name] = digest(path.read_bytes())
        return output

    def prepare(self) -> None:
        if sys.version_info[:3] != (3, 14, 10):
            raise GateError("missing_setup")
        self.before = self.source_index()
        write_private(self.retained / "source-before.json", json_bytes(self.before))
        source = self.root / "contracts/delegation"
        for path in sorted(source.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            if path.is_symlink() or path.suffix not in {".json", ".png"}:
                raise GateError("invalid_artifact")
            write_private(self.inputs / path.relative_to(source), path.read_bytes())
            write_private(self.retained / "inputs" / path.relative_to(source), path.read_bytes())
        self.oracle = decode(read_private(self.retained / "inputs/documents/expected-v1.json"))
        assert self.node is not None
        project = self.root / PROJECT
        compiled = self.work / "compiled"
        self.finish(
            self.start(
                [
                    self.node,
                    project / "node_modules/typescript/bin/tsc",
                    "--project",
                    project / "tsconfig.json",
                    "--outDir",
                    compiled,
                ],
                stage="compile",
                cwd=self.root,
            )
        )
        fresh = {
            p.relative_to(compiled).as_posix(): p.read_bytes()
            for p in compiled.rglob("*")
            if p.is_file()
        }
        current = {
            p.relative_to(project / "dist").as_posix(): p.read_bytes()
            for p in (project / "dist").rglob("*")
            if p.is_file()
        }
        if (
            not fresh
            or fresh != current
            or any(p.is_symlink() for p in (*compiled.rglob("*"), *(project / "dist").rglob("*")))
        ):
            raise GateError("invalid_artifact")
        write_private(
            self.retained / "compiled-parity.json",
            json_bytes({name: digest(raw) for name, raw in fresh.items()}),
        )
        if self.installed:
            self.install()

    def copy_tree(self, source: Path, target: Path) -> None:
        for path in sorted(source.rglob("*")):
            if path.is_symlink():
                raise GateError("invalid_artifact")
            if path.is_file():
                write_private(
                    target / path.relative_to(source), read_private(path, 8388608, empty=True)
                )

    def install(self) -> None:
        assert self.node is not None
        requested = Path(".local/validation/p3-package/document-" + uuid4().hex + ".json")
        target = self.root / requested
        self.stage = "fresh-package"
        self.nested_cleanup_known = False
        self.nested_builder = ScopedPackageRun(
            self.root,
            target,
            outer_children=lambda: self.commands,
            outer_capture=lambda: self.captured,
            outer_reservations=lambda: sum(self.reservations.values()),
            deadline=self.deadline,
            final_deadline=self.final_deadline,
        )
        try:
            self.nested_builder.offline()
            self.nested_builder.cleanup_resources()
            report = self.nested_builder.successful_report()
        finally:
            self.nested_commands = self.nested_builder.commands
            self.nested_capture_bytes = self.nested_builder.captured
            self.nested_cleanup_known = (
                self.nested_builder.children_settled() and not self.nested_builder.work.exists()
            )
        raw = read_private(target)
        if not exact(packages.validated_report(raw), report):
            raise GateError("invalid_report")
        if (
            report["status"] != "passed"
            or report["mode"] != "offline"
            or not exact(report["tests"], 8)
            or report["cleanup_complete"] is not True
            or not exact(report["child_commands"], BUILDER_EXPECTED_CHILDREN)
        ):
            raise GateError("invalid_report")
        retained = target.with_name(target.stem + "-artifacts")
        index = packages.validate_retained_index(retained, report["retained_index_sha256"])
        self.nested_capture_bytes = sum(
            entry["bytes"]
            for name, entry in index["files"].items()
            if name.startswith("commands/") and name.endswith(("stdout.bin", "stderr.bin"))
        )
        if (
            self.commands + self.nested_commands >= MAX_CHILDREN
            or self.captured + self.nested_capture_bytes > MAX_CAPTURE
        ):
            raise GateError("child_budget")
        self.nested_cleanup_known = True
        self.builder_report = report
        write_private(self.retained / "package-builder" / "report.json", raw)
        self.copy_tree(retained, self.retained / "package-builder" / "artifacts")
        archive_paths = {}
        for label in ("p1-wheel", "p3-wheel", "specialist-npm"):
            entry = report["artifacts"][label]
            path = retained / entry["path"]
            body = read_private(path, 8388608)
            if len(body) != entry["bytes"] or digest(body) != entry["sha256"]:
                raise GateError("invalid_artifact")
            archive_paths[label] = path
        self.client_python = self.work / "venv/bin/python"
        self.finish(
            self.start(
                [sys.executable, "-I", "-m", "venv", "--without-pip", self.work / "venv"],
                stage="python-venv",
            )
        )
        self.finish(
            self.start(
                [
                    self.root / ".venv/bin/uv",
                    "--no-config",
                    "pip",
                    "install",
                    "--offline",
                    "--python",
                    self.client_python,
                    "-r",
                    retained / "requirements.txt",
                    archive_paths["p1-wheel"],
                    archive_paths["p3-wheel"],
                ],
                stage="python-install",
            )
        )
        application = self.work / "application"
        private_directory(application)
        write_private(
            application / "package.json",
            b'{"name":"document-installed-consumer","private":true,"type":"module"}\n',
        )
        for name in (FIXTURE_NODE, FIXTURE_PYTHON, ORACLE_HELPER):
            write_private(application / name, (self.root / name).read_bytes())
        for folder, pattern in (
            ("projects/delegation-reliability/examples", "*.py"),
            (PROJECT + "/examples", "*.mjs"),
        ):
            for path in (self.root / folder).glob(pattern):
                write_private(application / path.relative_to(self.root), path.read_bytes())
        self.node_fixture, self.python_fixture = (
            application / FIXTURE_NODE,
            application / FIXTURE_PYTHON,
        )
        for name in ("npm-user.conf", "npm-global.conf"):
            write_private(self.work / name, b"")
        npm = Path(self.node).resolve().parents[1] / "lib/node_modules/npm/bin/npm-cli.js"
        if not npm.is_file():
            raise GateError("missing_setup")
        self.finish(
            self.start(
                [
                    self.node,
                    npm,
                    "install",
                    "--offline",
                    "--ignore-scripts",
                    "--no-audit",
                    "--no-fund",
                    "--userconfig=" + str(self.work / "npm-user.conf"),
                    "--globalconfig=" + str(self.work / "npm-global.conf"),
                    "--cache",
                    self.work / "npm-cache",
                    archive_paths["specialist-npm"],
                ],
                stage="npm-install",
                cwd=application,
            )
        )
        check = "from pathlib import Path;import sys;import delegation_reliability.document as a;import delegation_reliability.document_contracts as b;assert all(m.__file__ is not None and Path(m.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()) for m in (a,b));print('installed_document_imports_ok')"
        if (
            self.finish(
                self.start([self.client_python, "-I", "-c", check], stage="installed-imports")
            ).strip()
            != b"installed_document_imports_ok"
        ):
            raise GateError("invalid_artifact")
        installed = application / "node_modules/@livekit-ecosystem/delegation-specialist"
        current = self.root / PROJECT
        expected = {
            "dist/" + p.relative_to(current / "dist").as_posix(): p.read_bytes()
            for p in (current / "dist").rglob("*")
            if p.is_file()
        }
        expected.update(
            {"examples/" + p.name: p.read_bytes() for p in (current / "examples").glob("*.mjs")}
        )
        expected["README.md"] = (current / "README.md").read_bytes()
        actual = {
            p.relative_to(installed).as_posix(): p for p in installed.rglob("*") if p.is_file()
        }
        if (
            set(actual) != set(expected) | {"package.json"}
            or any(p.is_symlink() for p in installed.rglob("*"))
            or any(actual[n].read_bytes() != body for n, body in expected.items())
            or json.loads(actual["package.json"].read_bytes())
            != json.loads((current / "package.json").read_bytes())
        ):
            raise GateError("invalid_artifact")
        write_private(
            self.retained / "installed-parity.json",
            json_bytes(
                {
                    "python_imports_inside_isolated_prefix": True,
                    "npm_payloads": {name: digest(raw) for name, raw in expected.items()},
                    "npm_manifest_semantic_equal": True,
                }
            ),
        )

    def await_barrier(self, child: OwnedProcess, name: str) -> None:
        child.wait_for_barrier(self.barriers[name], timeout=min(20, self.remaining()))

    def release(self, child: OwnedProcess, name: str) -> None:
        child.release_barrier(self.barriers[name])

    def journey(self) -> None:
        assert self.node is not None
        node_output = self.finish(
            self.start(
                [self.node, self.node_fixture, "node-producer"],
                stage="node-producer",
                environment=self.fixture_environment("node-producer"),
            )
        )
        validate_reply(node_output, "node-producer")
        py_output = self.finish(
            self.start(
                [self.client_python, "-I", self.python_fixture, "python-contracts"],
                stage="python-contracts",
                environment=self.fixture_environment("python-contracts"),
            )
        )
        validate_reply(py_output, "python-contracts")
        server = self.start(
            [self.node, self.node_fixture, "node-server"],
            stage="node-server",
            environment=self.fixture_environment("node-server"),
        )
        self.await_barrier(server, "document_server_ready")
        endpoint = decode(read_private(self.directory / "document-endpoint.json"))
        if (
            endpoint.keys() != {"schema_version", "host", "port", "node_version"}
            or not exact(endpoint["schema_version"], 1)
            or endpoint["host"] != "127.0.0.1"
            or endpoint["node_version"] != "24.22.2"
            or not natural(endpoint["port"], 1, 65535)
        ):
            raise GateError("invalid_proof")
        enrollment = read_private(self.directory / "document-image-references.json", 8192)
        validate_enrollment(enrollment)
        write_private(self.retained / "proofs/document-image-references.json", enrollment)
        client = self.start(
            [self.client_python, "-I", self.python_fixture, "python-http"],
            stage="python-http",
            environment=self.fixture_environment("python-http"),
        )
        self.await_barrier(server, "document_post_decode_held")
        phase = decode(read_private(self.directory / "document-phase.json"))
        if (
            phase.keys()
            != {
                "schema_version",
                "kind",
                "node_pid",
                "attempt_id",
                "input_fingerprint",
                "deadline_at_ms",
                "worker_exit_code",
            }
            or not exact(phase["schema_version"], 1)
            or phase["kind"] != "document.post-decode-held"
            or not exact(phase["node_pid"], server.pid)
            or type(phase["attempt_id"]) is not str
            or not is_hash(phase["input_fingerprint"])
            or not exact(phase["worker_exit_code"], 0)
            or not natural(phase["deadline_at_ms"], 1, 4102444800000)
        ):
            raise GateError("invalid_proof")
        if not 0 < phase["deadline_at_ms"] - time.time_ns() // 1000000 <= 5000:
            raise GateError("invalid_proof")
        while time.time_ns() // 1000000 < phase["deadline_at_ms"]:
            self.remaining()
            if server.returncode is not None or client.returncode is not None:
                raise GateError("component_failed")
            time.sleep(
                max(0.0, min(0.02, (phase["deadline_at_ms"] - time.time_ns() // 1000000) / 1000))
            )
        self.release(server, "document_post_decode_held")
        self.phase = phase
        for hold, verified in (
            ("document_timeout_held", "document_timeout_verified"),
            ("document_cancel_held", "document_cancel_verified"),
        ):
            self.await_barrier(server, hold)
            self.await_barrier(client, verified)
            self.release(server, hold)
        self.await_barrier(server, "document_close_held")
        self.await_barrier(client, "document_close_requested")
        write_private(self.directory / "document-server.stop", f"{server.pid}\n".encode("ascii"))
        self.await_barrier(server, "document_close_incomplete")
        self.release(server, "document_close_held")
        validate_reply(self.finish(client), "python-http")
        validate_reply(self.finish(server), "node-server")
        proofs = {name: read_private(self.directory / name, MAX_PROOF) for name in PROOF_NAMES}
        self.bundle = validate_bundle(proofs, self.oracle, phase=phase)
        for name, raw in proofs.items():
            write_private(self.retained / "proofs" / name, raw)
        write_private(
            self.retained / "proofs/document-phase.json",
            read_private(self.directory / "document-phase.json"),
        )
        write_private(
            self.retained / "proofs/document-endpoint.json",
            read_private(self.directory / "document-endpoint.json"),
        )
        if self.source_index() != self.before:
            raise GateError("source_changed")
        write_private(self.retained / "source-after.json", json_bytes(self.before))
        expected = 9 if self.installed else 5
        if self.commands != expected or self.nested_commands != (
            BUILDER_EXPECTED_CHILDREN if self.installed else 0
        ):
            raise GateError("child_budget")
        self.passed.update(CASE_NAMES)

    def cleanup_resources(self) -> None:
        first: BaseException | None = None
        if self.nested_builder is not None:
            try:
                if not (
                    self.nested_cleanup_known
                    and self.nested_builder.children_settled()
                    and not self.nested_builder.work.exists()
                ):
                    self.nested_builder.cleanup_resources()
            except BaseException as error:  # noqa: BLE001 - retain primary while all independent owners close.
                first = error
            self.nested_commands = self.nested_builder.commands
            self.nested_capture_bytes = self.nested_builder.captured
            self.nested_cleanup_known = (
                self.nested_builder.children_settled() and not self.nested_builder.work.exists()
            )
            if not self.nested_cleanup_known:
                target = self.retained / "unresolved-nested-work.json"
                if not target.exists():
                    try:
                        write_private(
                            target,
                            json_bytes(
                                {
                                    "schema_version": 1,
                                    "status": "retained_for_cleanup",
                                    "work_directory": str(self.nested_builder.work),
                                    "retained_artifacts": str(self.nested_builder.retained),
                                    "children": [
                                        {
                                            "pid": child.pid,
                                            "returncode": child.returncode,
                                            "cleanup_failed": child.cleanup_failed,
                                        }
                                        for child in self.nested_builder.children
                                    ],
                                }
                            ),
                        )
                    except BaseException as error:  # noqa: BLE001 - diagnostics cannot mask first owner failure.
                        if first is None:
                            first = error
        try:
            super().cleanup_resources()
        except BaseException as error:  # noqa: BLE001 - direct outer resources close after nested owner attempt.
            if first is None:
                first = error
        if first is not None:
            raise first

    def remove_work(self) -> None:
        if not self.nested_cleanup_known:
            self.retain_unresolved_work()
            raise GateError("cleanup_incomplete")
        super().remove_work()

    def retain_failure_inputs(self) -> None:
        # Retain only safe direct proof names. Never copy arbitrary work/config files.
        for name in (
            *PROOF_NAMES,
            "document-phase.json",
            "document-endpoint.json",
            "document-image-references.json",
            "document-node-failure.json",
            "document-python-failure.json",
        ):
            path = self.directory / name
            target = self.retained / "failure-proofs" / name
            if path.exists() and not target.exists():
                try:
                    raw = read_private(path, MAX_PROOF)
                    if name.endswith("-failure.json"):
                        validate_failure_sidecar(raw, node=name == "document-node-failure.json")
                    elif name == "document-image-references.json":
                        validate_enrollment(raw)
                    if any(token.encode() in raw for token in self.tokens):
                        continue
                    write_private(target, raw)
                except (OSError, GateError):
                    continue


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.exit(2, '{"schema_version":1,"status":"failed","code":"invalid_input"}\n')


def validated_report(raw: bytes) -> dict[str, Any]:
    value = decode(raw, MAX_REPORT)
    required = {
        "schema_version",
        "status",
        "mode",
        "tests",
        "passed",
        "errors",
        "failures",
        "skipped",
        "cleanup_complete",
        "provider_calls",
        "vision_inference_claimed",
        "P1_image_execution_claimed",
        "child_commands",
        "direct_child_commands",
        "nested_package_children",
        "worker_records",
        "canonical_http_results",
        "duration_seconds",
        "case_results",
        "retained_index_sha256",
        "package_assertions",
        "code",
        "stage",
    }
    if (
        value.keys() != required
        or not exact(value["schema_version"], 1)
        or value["status"] != "passed"
        or type(value["mode"]) is not str
        or value["mode"] not in {MODE, MODE + "_installed"}
        or not exact(value["tests"], 20)
        or not exact(value["passed"], 20)
        or any(not exact(value[k], 0) for k in ("errors", "failures", "skipped"))
        or value["cleanup_complete"] is not True
        or not exact(value["provider_calls"], 8)
        or value["vision_inference_claimed"] is not False
        or value["P1_image_execution_claimed"] is not False
        or not exact(value["case_results"], cases(CASE_NAMES))
        or not is_hash(value["retained_index_sha256"])
        or not natural(value["worker_records"], 9, 64)
        or not exact(value["canonical_http_results"], 5)
        or value["code"] != "ok"
        or value["stage"] != "complete"
    ):
        raise GateError("invalid_report")
    installed = value["mode"] == MODE + "_installed"
    expected = {
        "direct_child_commands": 9 if installed else 5,
        "nested_package_children": BUILDER_EXPECTED_CHILDREN if installed else 0,
        "child_commands": 9 + BUILDER_EXPECTED_CHILDREN if installed else 5,
        "package_assertions": 8 if installed else 0,
    }
    if (
        any(not exact(value[k], v) for k, v in expected.items())
        or type(value["duration_seconds"]) not in (int, float)
        or not 0 < value["duration_seconds"] <= (360 if installed else 120)
    ):
        raise GateError("invalid_report")
    return value


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    parser = SafeParser(description=__doc__)
    parser.add_argument("--installed", action="store_true")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if args.plan:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "not_started",
                    "cases": list(CASE_NAMES),
                    "tests": 20,
                    "installed": args.installed,
                    "direct_children": 9 if args.installed else 5,
                    "nested_package_children": BUILDER_EXPECTED_CHILDREN if args.installed else 0,
                    "total_seconds": 360 if args.installed else 120,
                    "cleanup_seconds": 20,
                    "maximum_children": MAX_CHILDREN,
                    "maximum_capture_bytes": MAX_CAPTURE,
                    "maximum_proof_bytes": MAX_PROOF,
                    "provider_calls": False,
                    "P1_image_execution_claimed": False,
                },
                sort_keys=True,
            )
        )
        return 0
    run: DocumentRun | None = None
    target: Path | None = None
    primary: GateError | None = None
    cleanup = False
    index_sha = ""
    stage = "input"
    try:
        target = target_path(
            root, args.report or Path(".local/validation/p3-document/" + uuid4().hex + ".json")
        )
        private_directory(target.parent)
        run = DocumentRun(root, target, installed=args.installed)
        run.prepare()
        run.journey()
    except BaseException as error:  # noqa: BLE001 - finite tooling boundary, preserve primary and attempt all cleanup.
        primary = _translate(error)
        if run is not None:
            stage = run.stage
    if run is not None:
        try:
            if primary is not None:
                run.retain_failure_inputs()
            run.cleanup_resources()
            cleanup = run.nested_cleanup_known and run.children_settled() and not run.work.exists()
            if not cleanup:
                raise GateError("cleanup_incomplete")
        except BaseException as error:  # noqa: BLE001 - primary failure wins; unresolved work is retained.
            if primary is None:
                primary = _translate(error)
            run.retain_unresolved_work()
        try:
            files = [p for p in run.retained.rglob("*") if p.is_file()]
            if (
                len(files) > MAX_RETAINED_FILES
                or sum(p.stat().st_size for p in files) > MAX_RETAINED_BYTES
            ):
                raise GateError("retention_failed")
            index_sha = run.retained_index()
            from p3_document_evidence import validate_manifest

            index_raw = read_private(run.retained / "retained-index.json", 1048576)
            if digest(index_raw) != index_sha:
                raise GateError("retention_failed")
            validate_manifest(run.retained, index_raw)
        except BaseException as error:  # noqa: BLE001 - safe evidence failures never replace original failure.
            if primary is None:
                primary = _translate(error)
    count = len(run.passed) if run is not None else 0
    if primary is None and (not cleanup or count != 20):
        primary = GateError("component_failed")
    value = {
        "schema_version": 1,
        "status": "passed" if primary is None and cleanup and count == 20 else "failed",
        "mode": MODE + ("_installed" if args.installed else ""),
        "tests": 20,
        "passed": count,
        "errors": 0,
        "failures": int(primary is not None),
        "skipped": 0,
        "cleanup_complete": cleanup,
        "provider_calls": run.bundle.get("provider_calls") if run is not None else None,
        "vision_inference_claimed": False,
        "P1_image_execution_claimed": False,
        "child_commands": run.commands + run.nested_commands if run is not None else 0,
        "direct_child_commands": run.commands if run is not None else 0,
        "nested_package_children": run.nested_commands if run is not None else 0,
        "worker_records": run.bundle.get("worker_records") if run is not None else None,
        "canonical_http_results": run.bundle.get("canonical_http_results")
        if run is not None
        else None,
        "duration_seconds": time.monotonic() - run.started if run is not None else 0,
        "case_results": cases(tuple(n for n in CASE_NAMES if run is not None and n in run.passed)),
        "retained_index_sha256": index_sha,
        "package_assertions": 8 if run is not None and run.builder_report is not None else 0,
        "code": primary.code if primary is not None else "ok",
        "stage": stage if primary is not None else "complete",
    }
    raw = json_bytes(value)
    if value["status"] == "passed":
        validated_report(raw)
    if target is not None:
        write_private(target, raw)
    sys.stdout.buffer.write(raw)
    return 0 if value["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
