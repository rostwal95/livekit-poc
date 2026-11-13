"""Explicit twelve-case durable fixed-policy gate; imports and --plan start no I/O.

P1 remains the only acceptance/issuance/result authority. Owner SQL is independent
bounded test evidence. This tooling never creates action/delivery permission.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sqlite3
import stat
import sys
import time
from contextlib import closing
from pathlib import Path
from typing import Any, NoReturn, cast
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import p3_document_evidence as common
import p3_fixed_policy_check as policy
import p3_fixed_work_evidence as evidence
import p3_package_check as packages
from p3_document_package import GroupedOwnedProcess, ScopedPackageRun

sys.path.insert(0, str(ROOT))
from harness.process_control import FileBarrier, OwnedProcess

GateError = common.GateError
write_private, read_private, private_directory = (
    common.write_private,
    common.read_private,
    common.private_directory,
)
json_bytes, digest, exact = common.json_bytes, common.digest, common.exact
MAX_CHILDREN, MAX_CAPTURE, MAX_STREAM, MAX_PROOF = 32, 2097152, 65536, 32768
MAX_RETAINED_BYTES, MAX_RETAINED_FILES = 16777216, 2048
SOURCE_CHILDREN, INSTALLED_CHILDREN, BUILDER_EXPECTED_CHILDREN = 8, 29, 17
PROJECT = "projects/delegation-reliability/specialist-ts"
FIXTURE_NODE = PROJECT + "/tests/fixtures/durable-fixed-policy-server.mjs"
FIXTURE_PYTHON = "projects/delegation-reliability/tests/pg_fixed_policy_execution_cases.py"
OWNER_HELPER = "local-setup/scripts/p3_case_fixture.py"
LABELS = (
    "known",
    "missing",
    "conflicting",
    "wrong_rule",
    "wrong_decision",
    "wrong_witness",
    "foreign_scope",
    "expired_wrong_facts",
    "expired_valid",
    "cancelled",
    "abandoned",
    "postcommit",
    "useful",
)
NEGATIVES = frozenset(LABELS[3:8])
CASES = (
    "v1_defaults_and_version_separation",
    "v2_acceptance_original_bytes_scope_and_deadline",
    "full_input_replay_and_changed_identity_conflict",
    "unbound_foreign_zero_cancelled_and_stale_case_denied",
    "new_issuance_only_and_exact_owner_command_replay",
    "known_missing_and_conflicting_truth_preserved",
    "forged_and_expired_bad_facts_zero_result_commit",
    "historical_expired_body_and_authority_time",
    "business_cancel_and_known_fact_separation",
    "abandoned_waiter_retains_capacity_and_retry_close",
    "owned_postcommit_kill_and_fresh_original_lookup",
    "independent_inventory_and_useful_current_progress",
)
PYTHON_MODES = frozenset({"install", "exercise", "commit-kill", "reopen", "cleanup"})
MARKERS = (
    "fixed_work_server_ready",
    "fixed_work_expired_wrong_facts_held",
    "fixed_work_expired_valid_held",
    "fixed_work_cancelled_held",
    "fixed_work_abandoned_held",
    "fixed_work_cancel_verified",
    "fixed_work_abandon_verified",
    "fixed_work_result_committed",
    "fixed_work_useful_committed",
    "fixed_work_reads_verified",
)
STAGES = frozenset(
    {
        "input",
        "prepare",
        "compile",
        "public-types",
        "fresh-package",
        "python-venv",
        "python-install",
        "npm-install",
        "installed-imports",
        "install",
        "node-server",
        "exercise",
        "commit-kill",
        "reopen",
        "proof",
        "cleanup",
        "complete",
    }
)
SAFE_CODES = frozenset(
    {
        "ok",
        "invalid_input",
        "invalid_environment",
        "unsafe_path",
        "invalid_artifact",
        "invalid_proof",
        "invalid_report",
        "missing_setup",
        "source_changed",
        "child_budget",
        "deadline_exceeded",
        "component_failed",
        "cleanup_incomplete",
        "retention_failed",
        "unsafe_capture",
    }
)
BASE_KEYS = frozenset({"PATH", "LANG", "CI", "NO_COLOR", "__CF_USER_TEXT_ENCODING"})
COMMON_KEYS = frozenset(
    {
        "P3_FIXED_WORK_DIRECTORY",
        "P3_FIXED_WORK_WORK_SCHEMA",
        "P3_FIXED_WORK_CASE_SCHEMA",
        "P3_FIXED_WORK_PG_PORT",
    }
)


OWNER_TABLES = (
    "accepted_work",
    "issued_attempts",
    "attempt_results",
    "cancellation_commands",
    "result_feed_events",
    "result_actions",
    "result_delivery_intents",
    "result_delivery_possible",
    "result_delivery_receipts",
    "result_feed_source",
    "schema_metadata",
)
OWNER_STAGES = frozenset(
    {
        "owner_inventory",
        "owner_wire_join",
        "owner_case",
        "owner_supplier",
        "literal_join",
        "client_join",
        "retained_proofs",
    }
)
STAGES = STAGES | OWNER_STAGES


def read_owner_inventory(connection: Any, schema: str) -> dict[str, list[dict[str, Any]]]:
    """Read a finite sealed inventory of actual P1 v4 tables, never an alias."""
    from psycopg import sql

    if type(schema) is not str or re.fullmatch(r"p1_work_fixedv2_[0-9a-f]{32}", schema) is None:
        raise GateError("invalid_proof")
    inventory = {}
    for name in OWNER_TABLES:
        rows = cast(
            list[dict[str, Any]],
            connection.execute(
                sql.SQL("SELECT * FROM {}.{} LIMIT 129").format(
                    sql.Identifier(schema), sql.Identifier(name)
                )
            ).fetchall(),
        )
        if len(rows) > 128:
            raise GateError("invalid_proof")
        inventory[name] = rows
    return inventory


def _translate(error: BaseException) -> GateError:
    if isinstance(error, GateError) and error.code in SAFE_CODES:
        return error
    return GateError("component_failed")


def validate_environment(value: dict[str, str], role: str) -> None:
    if type(value) is not dict or any(
        type(k) is not str or type(v) is not str or not v or "\0" in v for k, v in value.items()
    ):
        raise GateError("invalid_environment")
    if role == "build":
        policy.validate_environment(value, "build")
        return
    if role == "serve":
        required = {
            "P3_FIXED_WORK_DIRECTORY",
            "P3_FIXED_WORK_INPUT_FILE",
            "P3_FIXED_WORK_ENDPOINT_FILE",
            "P3_FIXED_WORK_STOP_FILE",
            "P3_FIXED_WORK_TOKEN",
        }
    elif role in PYTHON_MODES:
        required = set(COMMON_KEYS) | (
            {"P3_FIXED_WORK_OWNER_PASSWORD"}
            if role in {"install", "cleanup"}
            else {"P3_FIXED_WORK_RUNTIME_PASSWORD", "P3_FIXED_WORK_TOKEN"}
        )
    else:
        raise GateError("invalid_environment")
    if not required <= value.keys() or set(value) - required - BASE_KEYS:
        raise GateError("invalid_environment")
    directory = Path(value["P3_FIXED_WORK_DIRECTORY"])
    if not directory.is_absolute() or directory.resolve() != directory or ".." in directory.parts:
        raise GateError("invalid_environment")
    if role == "serve":
        for key, name in (
            ("INPUT_FILE", "fixed-work-input.json"),
            ("ENDPOINT_FILE", "fixed-work-endpoint.json"),
            ("STOP_FILE", "fixed-work.stop"),
        ):
            if Path(value["P3_FIXED_WORK_" + key]) != directory / name:
                raise GateError("invalid_environment")
    else:
        if (
            re.fullmatch(r"p1_work_fixedv2_[0-9a-f]{32}", value["P3_FIXED_WORK_WORK_SCHEMA"])
            is None
            or re.fullmatch(r"p3_completion_[0-9a-f]{32}", value["P3_FIXED_WORK_CASE_SCHEMA"])
            is None
            or re.fullmatch(r"[1-9][0-9]{0,4}", value["P3_FIXED_WORK_PG_PORT"]) is None
            or not 1 <= int(value["P3_FIXED_WORK_PG_PORT"]) <= 65535
        ):
            raise GateError("invalid_environment")
    if (
        "P3_FIXED_WORK_TOKEN" in value
        and re.fullmatch(r"[A-Za-z0-9_-]{43}", value["P3_FIXED_WORK_TOKEN"]) is None
    ):
        raise GateError("invalid_environment")


def target_path(root: Path, requested: Path) -> Path:
    if (
        requested.is_absolute()
        or requested.parts[:3] != (".local", "validation", "p3-fixed-work")
        or len(requested.parts) != 4
        or re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,99}[.]json", requested.name) is None
    ):
        raise GateError("unsafe_path")
    target = root / requested
    if (
        any(p.is_symlink() for p in (target, *target.parents))
        or target.exists()
        or target.with_name(target.stem + "-artifacts").exists()
        or target.with_name(target.stem + "-artifacts").is_symlink()
    ):
        raise GateError("unsafe_path")
    return target


def publish_stop(path: Path, pid: int) -> None:
    if path.name != "fixed-work.stop" or not common.natural(pid, 1, 2**31 - 1):
        raise GateError("unsafe_path")
    private_directory(path.parent)
    pending = path.with_name(path.name + ".publishing")
    fd = os.open(pending, os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write((str(pid) + "\n").encode("ascii"))
            stream.flush()
            os.fsync(stream.fileno())
        os.link(pending, path, follow_symlinks=False)
    finally:
        pending.unlink(missing_ok=True)


def validate_reply(raw: bytes, mode: str) -> None:
    if type(mode) is not str or mode not in PYTHON_MODES:
        raise GateError("invalid_proof")
    v = common.decode(raw)
    if not exact(
        v, {"schema_version": 1, "status": "passed", "mode": mode, "cleanup_complete": True}
    ):
        raise GateError("invalid_proof")


def validated_report(raw: bytes) -> dict[str, Any]:
    v = policy.keys(
        common.decode(raw),
        {
            "schema_version",
            "status",
            "mode",
            "tests",
            "passed",
            "failures",
            "errors",
            "skipped",
            "duration_seconds",
            "child_commands",
            "package_assertions",
            "cleanup_complete",
            "code",
            "stage",
            "retained_index_sha256",
            "case_results",
        },
    )
    installed = v["mode"] == "local_fixed_work_installed"
    if (
        type(v["mode"]) is not str
        or v["mode"] not in {"local_fixed_work_source", "local_fixed_work_installed"}
        or not exact(v["schema_version"], 1)
        or type(v["duration_seconds"]) not in (int, float)
        or not 0 < v["duration_seconds"] <= (360 if installed else 180)
        or not exact(v["tests"], 12)
        or not common.natural(v["passed"], 0, 12)
        or type(v["cleanup_complete"]) is not bool
        or type(v["code"]) is not str
        or v["code"] not in SAFE_CODES
        or type(v["stage"]) is not str
        or v["stage"] not in STAGES
        or not common.natural(v["child_commands"], 0, 32)
        or not exact(v["errors"], 0)
        or not exact(v["skipped"], 0)
        or (
            v["retained_index_sha256"] is not None
            and not common.is_hash(v["retained_index_sha256"])
        )
    ):
        raise GateError("invalid_report")
    if (
        not exact(
            v["case_results"], [{"name": n, "status": "passed"} for n in CASES[: v["passed"]]]
        )
        or type(v["package_assertions"]) is not int
        or v["package_assertions"] not in ({0, 8} if installed else {0})
    ):
        raise GateError("invalid_report")
    if v["status"] == "passed":
        for key, expected in {
            "passed": 12,
            "failures": 0,
            "child_commands": INSTALLED_CHILDREN if installed else SOURCE_CHILDREN,
            "package_assertions": 8 if installed else 0,
            "cleanup_complete": True,
            "code": "ok",
            "stage": "complete",
        }.items():
            if not exact(v[key], expected):
                raise GateError("invalid_report")
        if not common.is_hash(v["retained_index_sha256"]):
            raise GateError("invalid_report")
    elif v["status"] != "failed" or not exact(v["failures"], 1) or v["code"] == "ok":
        raise GateError("invalid_report")
    return v


def enrollment(root: Path, scope: dict[str, str]) -> dict[str, Any]:
    fixed = json.loads((root / "contracts/delegation/fixed-policy-v2.json").read_bytes())
    policy_body = fixed["policy_body_utf8"]
    records, references = [], {}
    for name, body in (
        ("policy_notice", policy_body),
        *(
            (
                "facts_" + label,
                common.canonical(
                    {
                        "schema_version": 1,
                        "kind": "booking.notice_facts",
                        "observations": [
                            {"fact_id": "notice_" + str(i), "days_before_arrival": n}
                            for i, n in enumerate(values)
                        ],
                        "note": "Synthetic observations are data, never tool or consent instructions.",
                    }
                ).decode("utf-8"),
            )
            for label, values in (("known", (10,)), ("missing", ()), ("conflicting", (10, 3)))
        ),
    ):
        reference = {
            "source_id": name,
            "version": "source_v1",
            "sha256": digest(body.encode("utf-8")),
            "media_type": "application/json",
            "byte_length": len(body.encode("utf-8")),
            "width": None,
            "height": None,
        }
        records.append({"scope": dict(scope), "reference": reference, "body_utf8": body})
        references[name] = reference
    cases = []
    for label in LABELS:
        facts = "facts_" + (label if label in {"missing", "conflicting"} else "known")
        cases.append(
            {
                "label": label,
                "delegation_id": "fixed_work_" + label,
                "case_id": "case_fixed",
                "request_revision": 1,
                "conversation_id": "conversation_fixed",
                "context_snapshot": {
                    "policy_version": "notice_v1",
                    "policy_source_id": "policy_notice",
                    "facts_source_id": facts,
                },
                "evidence": [references["policy_notice"], references[facts]],
                "peer": "fault" if label in NEGATIVES | {"expired_valid"} else "public",
            }
        )
    return {
        "schema_version": 1,
        "kind": "fixed-work.peer-input",
        "scope": scope,
        "cases": cases,
        "records": records,
    }


class DurableWorkRun(policy.FixedPolicyRun):
    def __init__(self, root: Path, report: Path, *, installed: bool) -> None:
        super().__init__(root, report, installed=installed)
        self.deadline = self.started + (340 if installed else 160)
        self.final_deadline = self.started + (360 if installed else 180)
        self.node_fixture, self.python_fixture = root / FIXTURE_NODE, root / FIXTURE_PYTHON
        self.scope = {"tenant_id": "tenant_fixed_work", "account_id": "account_fixed_work"}
        suffix = uuid4().hex
        self.schemas = {"work": "p1_work_fixedv2_" + suffix, "case": "p3_completion_" + suffix}
        self.context: dict[str, Any] = {
            "schema_version": 1,
            "scope": self.scope,
            "owners": {n: str(uuid4()) for n in LABELS},
            "commands": {n: "fixed_command_" + n for n in LABELS},
        }
        self.barriers = {name: FileBarrier(self.directory, name) for name in MARKERS}
        self.clocks: dict[str, Any] = {}
        self.supplier_before = ""
        self.read_before = ""
        self.terminations = 0
        self.lab_started, self.lab_cleaned = False, False

    def start(
        self,
        argv: list[str | Path],
        *,
        stage: str,
        cwd: Path | None = None,
        environment: dict[str, str] | None = None,
        cleanup: bool = False,
    ) -> OwnedProcess:
        children, captured, reserved = self.nested_usage()
        if stage not in STAGES or self.commands + children >= MAX_CHILDREN:
            raise GateError("child_budget")
        self.remaining(cleanup=cleanup)
        env = environment or self.base
        validate_environment(
            env, "serve" if stage == "node-server" else stage if stage in PYTHON_MODES else "build"
        )
        available = (
            MAX_CAPTURE - self.captured - captured - reserved - sum(self.reservations.values())
        )
        limit = min(MAX_STREAM, available // 2)
        if limit < 1 or not Path(argv[0]).is_absolute():
            raise GateError("child_budget")
        self.commands += 1
        self.stage = stage
        output = self.work / "raw-commands" / f"{self.commands:02d}-{stage}"
        private_directory(output.parent)
        child = GroupedOwnedProcess(
            [str(v) for v in argv],
            cwd=cwd or self.work,
            env=env,
            output_directory=output,
            max_output_bytes=limit,
            final_deadline=self.final_deadline,
        )
        self.children.append(child)
        self.outputs[child.pid] = output
        self.child_roles[child.pid] = stage
        self.reservations[child.pid] = 2 * limit
        return child

    def finish(self, child: OwnedProcess, *, cleanup: bool = False) -> bytes:
        primary: BaseException | None = None
        result = None
        try:
            result = child.wait(timeout=min(60, self.remaining(cleanup=cleanup)))
        except BaseException as error:  # noqa: BLE001 - preserve primary while closing the actual group.
            primary = error
        try:
            child.close()
        except BaseException as error:  # noqa: BLE001 - observe every actual group even when wait failed.
            if primary is None:
                primary = error
        output = b""
        try:
            output, _ = self.capture(child)
        except BaseException as error:  # noqa: BLE001 - bounded capture is independent of actual closure.
            if primary is None:
                primary = error
        if primary is not None:
            raise _translate(primary)
        if result is None or result.returncode != 0 or child.cleanup_failed:
            raise GateError("component_failed")
        return output

    def source_index(self) -> dict[str, str]:
        result = super().source_index()
        names = {
            FIXTURE_NODE,
            FIXTURE_PYTHON,
            OWNER_HELPER,
            "local-setup/scripts/p3_durable_fixed_policy_check.py",
            "local-setup/scripts/p3_fixed_work_evidence.py",
            "tests/test_p3_fixed_work_evidence.py",
            "tests/fixtures/p3-fixed-work-proof-positive.json",
            "projects/delegation-reliability/tests/test_fixed_policy_execution.py",
            "projects/delegation-reliability/tests/test_fixed_work_fixture.py",
            "projects/delegation-reliability/tests/test_standalone_schedules.py",
            "tests/test_p3_fixed_work_gate.py",
            "projects/delegation-reliability/specialist-ts/tests/durable-fixed-policy-fixture.test.ts",
            "projects/delegation-reliability/tests/test_fixed_policy_observed_boundary.py",
            "projects/delegation-reliability/specialist-ts/tests/fixed-policy-observed.test.ts",
            "projects/delegation-reliability/examples/durable_fixed_policy.py",
            "local-setup/stack.py",
        }
        for name in names:
            path = self.root / name
            if not path.is_file() or path.is_symlink() or path.stat().st_size > 2097152:
                raise GateError("invalid_artifact")
            result[name] = digest(path.read_bytes())
        return dict(sorted(result.items()))

    def prepare(self) -> None:
        if sys.version_info[:3] != (3, 14, 10):
            raise GateError("missing_setup")
        self.before = self.source_index()
        write_private(self.retained / "source-before.json", json_bytes(self.before))
        self.enrollment = enrollment(self.root, self.scope)
        for name, value in (
            ("fixed-work-input.json", self.enrollment),
            ("fixed-work-context.json", self.context),
        ):
            raw = common.canonical(value) + b"\n"
            if len(raw) > MAX_PROOF:
                raise GateError("invalid_artifact")
            write_private(self.directory / name, raw)
            write_private(self.retained / "inputs" / name, raw)
        assert self.node is not None
        project, self.compiled = self.root / PROJECT, self.work / "compiled"
        self.finish(
            self.start(
                [
                    self.node,
                    project / "node_modules/typescript/bin/tsc",
                    "--project",
                    project / "tsconfig.json",
                    "--outDir",
                    self.compiled,
                ],
                stage="compile",
                cwd=self.root,
            )
        )
        expected = {m + suffix for m in packages.SPECIALIST_MODULES for suffix in (".js", ".d.ts")}
        fresh = {
            p.relative_to(self.compiled).as_posix(): p
            for p in self.compiled.rglob("*")
            if p.is_file()
        }
        if set(fresh) != expected or any(p.is_symlink() for p in self.compiled.rglob("*")):
            raise GateError("invalid_artifact")
        write_private(
            self.retained / "fresh-compiled.json",
            json_bytes({n: digest(p.read_bytes()) for n, p in fresh.items()}),
        )
        if self.installed:
            self.install()
        self.public_types()
        specification = importlib.util.spec_from_file_location(
            "fixed_work_ordinary_settings", self.root / "local-setup/stack.py"
        )
        if specification is None or specification.loader is None:
            raise GateError("missing_setup")
        setup = importlib.util.module_from_spec(specification)
        sys.modules[specification.name] = setup
        try:
            specification.loader.exec_module(setup)
            values = setup.load_settings()
        finally:
            sys.modules.pop(specification.name, None)
        self.lab_settings = {
            name: values[name]
            for name in ("POSTGRES_PORT", "POSTGRES_PASSWORD", "POSTGRES_MIGRATION_PASSWORD")
        }
        self.tokens = (
            *self.tokens,
            self.lab_settings["POSTGRES_PASSWORD"],
            self.lab_settings["POSTGRES_MIGRATION_PASSWORD"],
        )

    def public_types(self) -> None:
        application = self.work / "application"
        private_directory(application)
        if not self.installed:
            write_private(
                application / "package.json",
                b'{"name":"fixed-work-public-consumer","private":true,"type":"module"}\n',
            )
            target = application / "node_modules/@livekit-ecosystem/delegation-specialist"
            private_directory(target)
            write_private(
                target / "package.json", (self.root / PROJECT / "package.json").read_bytes()
            )
            for path in self.compiled.glob("*"):
                write_private(target / "dist" / path.name, path.read_bytes())
        copies = {
            FIXTURE_NODE,
            FIXTURE_PYTHON,
            OWNER_HELPER,
            "projects/delegation-reliability/examples/durable_fixed_policy.py",
        }
        copies.update(
            p.relative_to(self.root).as_posix()
            for p in (self.root / PROJECT / "examples").glob("*.mjs")
        )
        for name in copies:
            destination = application / name
            if destination.exists():
                if read_private(destination, 2097152) != (self.root / name).read_bytes():
                    raise GateError("invalid_artifact")
            else:
                write_private(destination, (self.root / name).read_bytes())
        write_private(
            self.retained / "unadapted-copies.json",
            json_bytes({n: digest((self.root / n).read_bytes()) for n in sorted(copies)}),
        )
        self.node_fixture, self.python_fixture = (
            application / FIXTURE_NODE,
            application / FIXTURE_PYTHON,
        )
        consumer = b"import {FixedPolicySpecialistClient,type FixedPolicyResultObservation,type FixedPolicyRequest} from '@livekit-ecosystem/delegation-specialist/fixed-policy';import type {EvidenceRecord} from '@livekit-ecosystem/delegation-specialist';declare const c:FixedPolicySpecialistClient;declare const q:FixedPolicyRequest;declare const r:readonly EvidenceRecord[];const observed:Promise<FixedPolicyResultObservation>=c.invokeObserved(q,r);void observed;\n"
        write_private(application / "consumer.mts", consumer)
        write_private(self.retained / "public-consumer.mts", consumer)
        assert self.node is not None
        self.finish(
            self.start(
                [
                    self.node,
                    self.root / PROJECT / "node_modules/typescript/bin/tsc",
                    "--noEmit",
                    "--strict",
                    "--module",
                    "NodeNext",
                    "--moduleResolution",
                    "NodeNext",
                    "--target",
                    "ES2022",
                    "--types",
                    "node",
                    "--typeRoots",
                    self.root / PROJECT / "node_modules/@types",
                    application / "consumer.mts",
                ],
                stage="public-types",
                cwd=application,
            )
        )

    def fixture_environment(self, mode: str) -> dict[str, str]:
        env = {k: v for k, v in self.base.items() if k in BASE_KEYS}
        env["P3_FIXED_WORK_DIRECTORY"] = str(self.directory)
        if mode == "serve":
            env.update(
                P3_FIXED_WORK_INPUT_FILE=str(self.directory / "fixed-work-input.json"),
                P3_FIXED_WORK_ENDPOINT_FILE=str(self.directory / "fixed-work-endpoint.json"),
                P3_FIXED_WORK_STOP_FILE=str(self.directory / "fixed-work.stop"),
                P3_FIXED_WORK_TOKEN=self.tokens[0],
            )
        else:
            env.update(
                P3_FIXED_WORK_WORK_SCHEMA=self.schemas["work"],
                P3_FIXED_WORK_CASE_SCHEMA=self.schemas["case"],
                P3_FIXED_WORK_PG_PORT=self.lab_settings["POSTGRES_PORT"],
            )
            if mode in {"install", "cleanup"}:
                env["P3_FIXED_WORK_OWNER_PASSWORD"] = self.lab_settings[
                    "POSTGRES_MIGRATION_PASSWORD"
                ]
            else:
                env.update(
                    P3_FIXED_WORK_RUNTIME_PASSWORD=self.lab_settings["POSTGRES_PASSWORD"],
                    P3_FIXED_WORK_TOKEN=self.tokens[0],
                )
        validate_environment(env, mode)
        return env

    def python_mode(self, mode: str, *, finish: bool = True, cleanup: bool = False) -> Any:
        child = self.start(
            [self.client_python, "-I", self.python_fixture, mode],
            stage=mode,
            environment=self.fixture_environment(mode),
            cleanup=cleanup,
        )
        if not finish:
            return child
        raw = self.finish(child, cleanup=cleanup)
        validate_reply(raw, mode)
        return child

    def install(self) -> None:
        assert self.node is not None
        requested = Path(".local/validation/p3-package/fixed-work-" + uuid4().hex + ".json")
        target = self.root / requested
        private_directory(target.parent)
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
            b'{"name":"fixed-work-installed-consumer","private":true,"type":"module"}\n',
        )
        for name in (FIXTURE_NODE, FIXTURE_PYTHON, OWNER_HELPER):
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
        check = "from pathlib import Path;import sys;import delegation_reliability.fixed_policy as a;import delegation_reliability.fixed_policy_execution as b;assert all(m.__file__ is not None and Path(m.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()) for m in (a,b));print('installed_fixed_policy_imports_ok')"
        if (
            self.finish(
                self.start([self.client_python, "-I", "-c", check], stage="installed-imports")
            ).strip()
            != b"installed_fixed_policy_imports_ok"
        ):
            raise GateError("invalid_artifact")
        installed = application / "node_modules/@livekit-ecosystem/delegation-specialist"
        current = self.root / PROJECT
        expected = {
            "dist/" + p.relative_to(self.compiled).as_posix(): p.read_bytes()
            for p in self.compiled.rglob("*")
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

    def owner_settings(self, kind: str = "work") -> Any:
        from continuity_lab.work_api import PostgresSettings

        return PostgresSettings(
            port=int(self.lab_settings["POSTGRES_PORT"]),
            user="continuity_migrator",
            password=self.lab_settings["POSTGRES_MIGRATION_PASSWORD"],
            schema=self.schemas[kind],
        )

    def db_now(self) -> int:
        with closing(
            self.owner_settings().connect(application_name="continuity-test")
        ) as connection:
            row = connection.execute(
                "SELECT floor(extract(epoch FROM clock_timestamp())*1000)::bigint AS now"
            ).fetchone()
            if row is None or not common.natural(row["now"], 0, 4102444800000):
                raise GateError("invalid_proof")
            return int(row["now"])

    def after_db(self, stamp: int, maximum: float, *, require_host: bool = False) -> int:
        if not common.natural(stamp, 0, 4102444800000):
            raise GateError("invalid_proof")
        end = time.monotonic() + maximum
        while True:
            self.remaining()
            observed = self.db_now()
            if observed >= stamp and (not require_host or time.time_ns() // 1_000_000 >= stamp):
                return observed
            if time.monotonic() >= end:
                raise GateError("deadline_exceeded")
            time.sleep(0.005)

    def snapshot(self) -> str:
        from psycopg import sql

        snapshots = {}
        for kind in ("work", "case"):
            settings = self.owner_settings(kind)
            with closing(settings.connect(application_name="continuity-test")) as connection:
                tables = connection.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname=%s ORDER BY tablename",
                    (settings.schema,),
                ).fetchall()
                if not 1 <= len(tables) <= 64:
                    raise GateError("invalid_proof")
                rows = {}
                for table in tables:
                    name = table["tablename"]
                    values = connection.execute(
                        sql.SQL(
                            "SELECT to_jsonb(t)::text AS body FROM {}.{} t ORDER BY to_jsonb(t)::text LIMIT 129"
                        ).format(sql.Identifier(settings.schema), sql.Identifier(name))
                    ).fetchall()
                    if len(values) > 128:
                        raise GateError("invalid_proof")
                    rows[name] = [json.loads(row["body"]) for row in values]
                snapshots[kind] = rows
        raw = common.canonical(snapshots)
        if len(raw) > 524288:
            raise GateError("invalid_proof")
        return digest(raw)

    def supplier(self) -> tuple[str, int, int]:
        path = self.directory / "supplier.sqlite3"
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as connection:
            tables = ("bookings", "inquiry_receipts", "mutation_receipts", "apply_calls")
            rows = {
                name: connection.execute(
                    'SELECT * FROM "' + name + '" ORDER BY 1,2 LIMIT 129'
                ).fetchall()
                for name in tables
            }
            if any(len(v) > 128 for v in rows.values()):
                raise GateError("invalid_proof")
        return (
            digest(common.canonical(rows)),
            len(rows["inquiry_receipts"]),
            len(rows["apply_calls"]),
        )

    def cleanup_lab(self) -> None:
        if not self.lab_started or self.lab_cleaned:
            return
        if not self.children_settled() or not self.nested_cleanup_known:
            raise GateError("cleanup_incomplete")
        self.python_mode("cleanup", cleanup=True)
        with closing(
            self.owner_settings().connect(application_name="continuity-test")
        ) as connection:
            rows = connection.execute(
                "SELECT nspname FROM pg_namespace WHERE nspname IN (%s,%s)",
                (self.schemas["work"], self.schemas["case"]),
            ).fetchall()
            if rows:
                raise GateError("cleanup_incomplete")
        self.lab_cleaned = True

    def journey(self) -> None:
        self.lab_started = True
        self.python_mode("install")
        self.supplier_before, inquiry, apply = self.supplier()
        if inquiry or apply:
            raise GateError("invalid_proof")
        assert self.node is not None
        server = self.start(
            [self.node, self.node_fixture, "serve"],
            stage="node-server",
            environment=self.fixture_environment("serve"),
        )
        self.await_barrier(server, "fixed_work_server_ready")
        endpoint = policy.keys(
            common.decode(read_private(self.directory / "fixed-work-endpoint.json")),
            {"schema_version", "pid", "node_version", "public", "fault"},
        )
        if (
            not exact(endpoint["schema_version"], 1)
            or not exact(endpoint["pid"], server.pid)
            or endpoint["node_version"] != "24.22.2"
        ):
            raise GateError("invalid_proof")
        for role in ("public", "fault"):
            row = policy.keys(endpoint[role], {"host", "port"})
            if row["host"] != "127.0.0.1" or not common.natural(row["port"], 1, 65535):
                raise GateError("invalid_proof")
        if endpoint["public"]["port"] == endpoint["fault"]["port"]:
            raise GateError("invalid_proof")
        client = self.python_mode("exercise", finish=False)
        for label in ("expired_wrong_facts", "expired_valid"):
            self.await_barrier(server, "fixed_work_" + label + "_held")
            phase = policy.keys(
                common.decode(
                    read_private(self.directory / ("fixed-work-" + label + "-phase.json"))
                ),
                {"schema_version", "label", "deadline_at_ms", "request_sha256"},
            )
            if (
                not exact(phase["schema_version"], 1)
                or phase["label"] != label
                or not common.is_hash(phase["request_sha256"])
            ):
                raise GateError("invalid_proof")
            now = self.after_db(phase["deadline_at_ms"], 5, require_host=True)
            self.clocks[label] = {"db_now_ms": now, "deadline_at_ms": phase["deadline_at_ms"]}
            self.release(server, "fixed_work_" + label + "_held")
        self.await_barrier(server, "fixed_work_cancelled_held")
        self.await_barrier(client, "fixed_work_cancel_verified")
        self.release(server, "fixed_work_cancelled_held")
        self.await_barrier(server, "fixed_work_abandoned_held")
        self.await_barrier(client, "fixed_work_abandon_verified")
        self.release(server, "fixed_work_abandoned_held")
        validate_reply(self.finish(client), "exercise")
        crashed = self.python_mode("commit-kill", finish=False)
        self.await_barrier(crashed, "fixed_work_result_committed")
        termination = crashed.kill(timeout=min(3, self.remaining()))
        crashed.close()
        self.capture(crashed)
        if (
            termination.pid != crashed.pid
            or termination.returncode != -9
            or not termination.killed
            or crashed.cleanup_failed
            or not isinstance(crashed, GroupedOwnedProcess)
            or not crashed.group_settled
        ):
            raise GateError("invalid_proof")
        self.terminations += 1
        reopened = self.python_mode("reopen", finish=False)
        self.await_barrier(reopened, "fixed_work_useful_committed")
        grant = common.decode(read_private(self.directory / "grant-postcommit.json"))
        stamp = grant["lease_until_ms"]
        self.clocks["postcommit_lease"] = {
            "db_now_ms": self.after_db(stamp, 12),
            "lease_until_ms": stamp,
        }
        self.read_before = self.snapshot()
        self.release(reopened, "fixed_work_useful_committed")
        self.await_barrier(reopened, "fixed_work_reads_verified")
        after = self.snapshot()
        if after != self.read_before:
            raise GateError("invalid_proof")
        self.release(reopened, "fixed_work_reads_verified")
        validate_reply(self.finish(reopened), "reopen")
        publish_stop(self.directory / "fixed-work.stop", server.pid)
        raw = self.finish(server)
        reply = policy.keys(
            common.decode(raw),
            {"schema_version", "status", "mode", "node_version", "cleanup_complete", "peer_sha256"},
        )
        peer_raw = read_private(self.directory / "fixed-work-peer.json")
        if not exact(
            reply,
            {
                "schema_version": 1,
                "status": "passed",
                "mode": "serve",
                "node_version": "24.22.2",
                "cleanup_complete": True,
                "peer_sha256": digest(peer_raw),
            },
        ):
            raise GateError("invalid_proof")
        self.stage = "proof"
        self.verify(peer_raw, after)
        if self.terminations != 1 or self.source_index() != self.before:
            raise GateError("source_changed")
        for name in ("fixed-work-input.json", "fixed-work-context.json"):
            if read_private(self.directory / name) != read_private(self.retained / "inputs" / name):
                raise GateError("source_changed")
        write_private(self.retained / "source-after.json", json_bytes(self.source_index()))
        self.passed.update(CASES[:-1])

    def verify(self, peer_raw: bytes, read_after: str) -> None:
        from psycopg import sql

        records, wires, cancellations = [], {}, []
        feed = common.decode(read_private(self.directory / "fixed-work-public-feed.json"))
        events = feed["events"]
        with closing(
            self.owner_settings().connect(application_name="continuity-test")
        ) as connection:
            self.stage = "owner_inventory"
            inventory = read_owner_inventory(connection, self.schemas["work"])

            def select(table: str) -> list[dict[str, Any]]:
                return inventory[table]

            accepted, grants, results, cancels, sql_events = (
                select(name)
                for name in (
                    "accepted_work",
                    "issued_attempts",
                    "attempt_results",
                    "cancellation_commands",
                    "result_feed_events",
                )
            )
            actual_counts = {
                "work": len(accepted),
                "attempts": len(grants),
                "results": len(results),
                "events": len(sql_events),
                "cancel_commands": len(cancels),
                "actions": len(select("result_actions")),
                "deliveries": sum(
                    len(select(name))
                    for name in (
                        "result_delivery_intents",
                        "result_delivery_possible",
                        "result_delivery_receipts",
                    )
                ),
                "supplier_calls": 0,
            }
            expected_counts = {
                "work": 13,
                "attempts": 13,
                "results": 8,
                "events": 8,
                "cancel_commands": 2,
                "actions": 0,
                "deliveries": 0,
                "supplier_calls": 0,
            }
            if actual_counts != expected_counts:
                raise GateError("invalid_proof")
            source = select("result_feed_source")
            metadata = select("schema_metadata")
            if (
                len(source) != 1
                or len(metadata) != 1
                or metadata[0]["version"] != 4
                or str(source[0]["source_id"]) != feed["source_id"]
            ):
                raise GateError("invalid_proof")
            self.stage = "owner_wire_join"
            for label in LABELS:
                saved = common.decode(
                    read_private(self.directory / ("accepted-" + label + ".json"))
                )
                rows = [r for r in accepted if str(r["work_id"]) == saved["work_id"]]
                g = [r for r in grants if str(r["work_id"]) == saved["work_id"]]
                r = [r for r in results if str(r["work_id"]) == saved["work_id"]]
                if len(rows) != 1 or len(g) != 1 or len(r) != (0 if label in NEGATIVES else 1):
                    raise GateError("invalid_proof")
                row, grant = rows[0], g[0]
                for stored in (row, grant, *r):
                    if (stored["tenant_id"], stored["account_id"]) != (
                        self.scope["tenant_id"],
                        self.scope["account_id"],
                    ):
                        raise GateError("invalid_proof")
                if (
                    row["idempotency_key"] != "fixed_work_" + label
                    or row["operation"] != "booking.evaluate_policy"
                ):
                    raise GateError("invalid_proof")
                body = bytes(row["body"])
                request = json.loads(body)
                template = next(t for t in self.enrollment["cases"] if t["label"] == label)
                if (
                    body.decode("utf-8") != saved["request_utf8"]
                    or digest(body) != row["sha256"]
                    or grant["command_id"] != self.context["commands"][label]
                    or str(grant["owner_id"]) != self.context["owners"][label]
                    or request["scope"] != self.scope
                    or any(
                        request[k] != template[k]
                        for k in (
                            "delegation_id",
                            "case_id",
                            "request_revision",
                            "context_snapshot",
                            "evidence",
                        )
                    )
                ):
                    raise GateError("invalid_proof")
                peer_wire = common.decode(
                    read_private(self.directory / "peer-wires" / (label + ".json"))
                )
                observed = common.decode(
                    read_private(self.directory / ("observed-" + label + ".json"))
                )
                if set(peer_wire) != {"request_utf8", "result_utf8"}:
                    raise GateError("invalid_proof")
                wire = {
                    "label": label,
                    "accepted_request_utf8": body.decode("utf-8"),
                    "request_utf8": peer_wire["request_utf8"],
                    "result_utf8": peer_wire["result_utf8"],
                    "observed_at_ms": observed["observed_at_ms"],
                }
                wire_raw = common.canonical(wire) + b"\n"
                if len(wire_raw) > 32768:
                    raise GateError("invalid_proof")
                write_private(self.retained / "proofs/wires" / (label + ".json"), wire_raw)
                wires[label] = wire
                result = r[0] if r else None
                event = [x for x in sql_events if str(x["attempt_id"]) == str(grant["attempt_id"])]
                if len(event) != len(r):
                    raise GateError("invalid_proof")
                if result is not None and (
                    bytes(result["body"]).decode("utf-8") != peer_wire["result_utf8"]
                    or digest(bytes(result["body"])) != result["sha256"]
                ):
                    raise GateError("invalid_proof")
                matching_cancel = [c for c in cancels if str(c["work_id"]) == saved["work_id"]]
                records.append(
                    {
                        "label": label,
                        "work_id": saved["work_id"],
                        "delegation_id": request["delegation_id"],
                        "case_id": request["case_id"],
                        "request_revision": request["request_revision"],
                        "input_fingerprint": request["input_fingerprint"],
                        "accepted_request_sha256": row["sha256"],
                        "deadline_at_ms": row["deadline_at_ms"],
                        "accepted_at_ms": row["accepted_at_ms"],
                        "owner_id": str(grant["owner_id"]),
                        "command_id": grant["command_id"],
                        "attempt_id": str(grant["attempt_id"]),
                        "attempt_number": grant["number"],
                        "epoch": grant["epoch"],
                        "issued_at_ms": grant["issued_at_ms"],
                        "lease_until_ms": grant["lease_until_ms"],
                        "wire_attempt_id": "attempt_" + UUID(str(grant["attempt_id"])).hex,
                        "cancel_requested": bool(matching_cancel),
                        "recorded_at_ms": result["recorded_at_ms"] if result else None,
                        "disposition": result["disposition"] if result else None,
                        "result_sha256": result["sha256"] if result else None,
                        "feed_sequence": event[0]["sequence"] if event else None,
                    }
                )
                for cancellation in matching_cancel:
                    if (cancellation["tenant_id"], cancellation["account_id"]) != (
                        self.scope["tenant_id"],
                        self.scope["account_id"],
                    ):
                        raise GateError("invalid_proof")
                    actual = {
                        k: str(cancellation[k])
                        if k in {"cancellation_id", "work_id"}
                        else cancellation[k]
                        for k in ("cancellation_id", "work_id", "command_id", "requested_at_ms")
                    }
                    actual["disposition"] = "requested"
                    saved_cancel = common.decode(
                        read_private(self.directory / ("cancel-" + label + ".json"))
                    )
                    if actual != saved_cancel:
                        raise GateError("invalid_proof")
                    cancellations.append(actual)
            # Public feed is independently joined to actual source/event SQL IDs.
            for public in events:
                matching = [r for r in sql_events if str(r["event_id"]) == public["event_id"]]
                if len(matching) != 1 or any(
                    str(matching[0][k]) != str(public[k])
                    for k in ("work_id", "attempt_id", "sequence", "origin")
                ):
                    raise GateError("invalid_proof")
        lease_wait = policy.keys(
            common.decode(read_private(self.directory / "fixed-work-rejected-lease-wait.json")),
            {"schema_version", "records"},
        )
        expected_wait = [
            {
                "label": row["label"],
                "work_id": row["work_id"],
                "attempt_id": row["attempt_id"],
                "lease_until_ms": row["lease_until_ms"],
                "status": "retryable",
            }
            for row in records
            if row["label"] in {"wrong_rule", "wrong_decision", "wrong_witness", "foreign_scope"}
        ]
        if not exact(lease_wait, {"schema_version": 1, "records": expected_wait}) or any(
            self.clocks["expired_wrong_facts"]["db_now_ms"] < row["lease_until_ms"]
            for row in expected_wait
        ):
            raise GateError("invalid_proof")
        write_private(
            self.retained / "proofs/fixed-work-rejected-lease-wait.json",
            common.canonical(lease_wait) + b"\n",
        )
        self.stage = "owner_case"
        # Exact trusted case/task/revision bindings are independent of a child label.
        cases = common.decode(read_private(self.directory / "fixed-work-cases.json"))
        if set(cases) != {"case_fixed", "case_cancelled"}:
            raise GateError("invalid_proof")
        with closing(
            self.owner_settings("case").connect(application_name="continuity-test")
        ) as connection:
            case_metadata = connection.execute(
                sql.SQL("SELECT version FROM {}.schema_metadata WHERE singleton").format(
                    sql.Identifier(self.schemas["case"])
                )
            ).fetchone()
            if case_metadata is None or case_metadata["version"] != 4:
                raise GateError("invalid_proof")
            rows = connection.execute(
                sql.SQL(
                    "SELECT task_id,case_id,scope_id,actor_id,revision,cancelled FROM {}.cases"
                ).format(sql.Identifier(self.schemas["case"]))
            ).fetchall()
            if len(rows) != 2:
                raise GateError("invalid_proof")
            for label, saved in cases.items():
                match = [
                    r
                    for r in rows
                    if str(r["task_id"]) == saved["task_id"]
                    and str(r["case_id"]) == saved["case_id"]
                ]
                if (
                    len(match) != 1
                    or match[0]["scope_id"] != "p3_completion_scope"
                    or match[0]["actor_id"] != "p3_completion_user"
                    or match[0]["revision"] != 1
                    or match[0]["cancelled"] != (label == "case_cancelled")
                ):
                    raise GateError("invalid_proof")
        self.stage = "owner_supplier"
        final, inquiry, apply = self.supplier()
        if final != self.supplier_before or inquiry or apply:
            raise GateError("invalid_proof")
        authority = {
            "schema_version": 1,
            "kind": "fixed-policy.execution-authority",
            "scope": self.scope,
            "source_id": feed["source_id"],
            "work_schema": self.schemas["work"],
            "case_schema": self.schemas["case"],
            "schema_versions": {"work": 4, "case": 4},
            "records": records,
            "counts": actual_counts,
            "events": events,
            "cancellations": cancellations,
            "clock_witnesses": self.clocks,
            "read_snapshot_sha256": {"before": self.read_before, "after": read_after},
            "supplier_observation": {
                "inquiry_calls": inquiry,
                "apply_calls": apply,
                "baseline_sha256": self.supplier_before,
                "final_sha256": final,
            },
        }
        self.stage = "literal_join"
        verdict = evidence.validate_bundle(
            authority,
            common.decode(peer_raw),
            [wires[n] for n in LABELS],
            self.enrollment["records"],
            expected_scope=self.scope,
        )
        self.stage = "client_join"
        client = common.decode(read_private(self.directory / "fixed-work-client.json"))
        expected_client = {
            "schema_version": 1,
            "kind": "fixed-policy.execution-client",
            "cases": list(CASES),
            "records": [
                {
                    "label": n,
                    "outcome": "invalid_response" if n in NEGATIVES else "stored",
                    "applicability": None
                    if n in NEGATIVES
                    else "expired"
                    if n == "expired_valid"
                    else "clarification"
                    if n in {"missing", "conflicting"}
                    else "candidate",
                }
                for n in LABELS
            ],
            "replay": {
                "new_issue_writes": 0,
                "new_complete_writes": 0,
                "new_invocations": 0,
                "original_identity": True,
            },
            "waiter": {
                "active_after_abandon": 1,
                "close_incomplete": True,
                "active_after_release": 0,
            },
            "default_v1_preserved": True,
            "zero_revision_accepts": 0,
            "zero_revision_invocations": 0,
        }
        if not exact(client, expected_client):
            raise GateError("invalid_proof")
        self.stage = "retained_proofs"
        proofs = {
            "fixed-work-authority.json": common.canonical(authority) + b"\n",
            "fixed-work-peer.json": peer_raw,
            "fixed-work-client.json": common.canonical(client) + b"\n",
            "fixed-work-sources.json": common.canonical(self.enrollment["records"]) + b"\n",
            "literal-verdict.json": common.canonical(verdict) + b"\n",
        }
        if (
            any(len(raw) > MAX_PROOF for raw in proofs.values())
            or sum(len(common.canonical(v)) for v in wires.values())
            + sum(len(raw) for raw in proofs.values())
            > 524288
        ):
            raise GateError("invalid_proof")
        for name, raw in proofs.items():
            write_private(self.retained / "proofs" / name, raw)
        index = {
            n: {
                "path": "wires/" + n + ".json",
                "bytes": (self.retained / "proofs/wires" / (n + ".json")).stat().st_size,
                "sha256": digest(read_private(self.retained / "proofs/wires" / (n + ".json"))),
            }
            for n in LABELS
        }
        write_private(
            self.retained / "proofs/fixed-work-wires-index.json",
            json_bytes({"schema_version": 1, "files": index}),
        )
        write_private(
            self.retained / "proofs/fixed-work-owners.json",
            json_bytes(
                {
                    "schema_version": 1,
                    "owned_kills": self.terminations,
                    "expected_scope": self.scope,
                    "work_schema": self.schemas["work"],
                    "case_schema": self.schemas["case"],
                    "cases": cases,
                }
            ),
        )

    def retain_nested_failure(self) -> bool:
        """Retain only this in-memory builder after actual known owner settlement."""
        builder = self.nested_builder
        if not self.failed_mode or builder is None or self.builder_report is not None:
            return False
        if not self.nested_cleanup_known or not builder.children_settled() or builder.work.exists():
            return False
        if (
            builder.report.parent != self.root / ".local/validation/p3-package"
            or re.fullmatch(r"fixed-work-[0-9a-f]{32}[.]json", builder.report.name) is None
            or builder.retained != builder.report.with_name(builder.report.stem + "-artifacts")
        ):
            raise GateError("retention_failed")
        children = []
        for child in builder.children:
            if (
                type(child.returncode) is not int
                or child.cleanup_failed
                or not isinstance(child, GroupedOwnedProcess)
                or not child.group_settled
            ):
                return False
            children.append(
                {
                    "pid": child.pid,
                    "returncode": child.returncode,
                    "cleanup_failed": child.cleanup_failed,
                    "group_settled": child.group_settled,
                }
            )
        stage = (
            builder.stage
            if builder.stage
            in {
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
            }
            else "unobserved"
        )
        target = self.retained / "failed-package-builder"
        if (target / "copy-complete.json").exists():
            return True
        files: dict[str, dict[str, int | str]] = {}
        total_bytes = 0
        for path in sorted(builder.retained.rglob("*")):
            info = path.lstat()
            if stat.S_ISDIR(info.st_mode):
                if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                    raise GateError("retention_failed")
            elif (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink != 1
            ):
                raise GateError("retention_failed")
            else:
                if (
                    len(files) >= MAX_RETAINED_FILES
                    or total_bytes + info.st_size > MAX_RETAINED_BYTES
                ):
                    raise GateError("retention_failed")
                total_bytes += info.st_size
                files[path.relative_to(builder.retained).as_posix()] = {
                    "bytes": info.st_size,
                    "sha256": digest(read_private(path, 8388608, empty=True)),
                }
        if len(files) > MAX_RETAINED_FILES or total_bytes > MAX_RETAINED_BYTES:
            raise GateError("retention_failed")
        # Publish the actual descriptor first. A later copy fault cannot lose the
        # original retained path or pretend the partial copy was complete.
        write_private(
            target / "descriptor.json",
            json_bytes(
                {
                    "schema_version": 1,
                    "kind": "fixed-work.nested-builder-failure",
                    "report_path": str(builder.report),
                    "report_exists": builder.report.exists(),
                    "retained_path": str(builder.retained),
                    "work_path": str(builder.work),
                    "work_removed": True,
                    "stage": stage,
                    "commands": builder.commands,
                    "captured_bytes": builder.captured,
                    "cleanup_complete": True,
                    "children": children,
                    "file_count": len(files),
                    "file_bytes": total_bytes,
                    "inventory_sha256": digest(common.canonical(files)),
                }
            ),
        )
        self.copy_tree(builder.retained, target / "artifacts")
        write_private(
            target / "copy-complete.json",
            json_bytes(
                {
                    "schema_version": 1,
                    "status": "copied",
                    "files": len(files),
                    "bytes": total_bytes,
                }
            ),
        )
        return True

    def retain_failure_inputs(self) -> None:
        try:
            self.retain_nested_failure()
        except (GateError, OSError, ValueError):
            # Failure-only diagnostics never replace primary failure or skip
            # independent actual owner/DDL/private-work cleanup.
            pass
        for path in self.directory.rglob("*.json"):
            if path.is_symlink() or not path.is_file():
                continue
            target = self.retained / "failure-proofs" / path.relative_to(self.directory)
            if target.exists():
                continue
            try:
                raw = read_private(path, MAX_PROOF)
                common.decode(raw)
                if not any(token.encode() in raw for token in self.tokens):
                    write_private(target, raw)
            except (GateError, OSError, ValueError):
                continue


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.exit(2, '{"schema_version":1,"status":"failed","code":"invalid_input"}\n')


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    parser = SafeParser(description=__doc__)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--installed", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if args.plan:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "planned",
                    "tests": 12,
                    "cases": list(CASES),
                    "children": INSTALLED_CHILDREN if args.installed else SOURCE_CHILDREN,
                    "package_assertions": 8 if args.installed else 0,
                    "deadline_seconds": 360 if args.installed else 180,
                    "cleanup_seconds": 20,
                    "services": "explicit isolated PG +loopback only; no providers/SFU",
                },
                sort_keys=True,
            )
        )
        return 0
    run, target, primary, cleanup, index_sha = None, None, None, False, None
    stage, started = "input", time.monotonic()
    try:
        target = target_path(
            root, args.report or Path(".local/validation/p3-fixed-work/" + uuid4().hex + ".json")
        )
        private_directory(target.parent)
        run = DurableWorkRun(root, target, installed=args.installed)
        run.prepare()
        run.journey()
    except BaseException as error:  # noqa: BLE001 - closed host boundary, no arbitrary exception properties.
        primary = _translate(error)
        if run is not None:
            stage = run.stage
            run.failed_mode = True
    if run is not None:
        try:
            run.cleanup_resources()
            cleanup = (
                run.nested_cleanup_known
                and run.children_settled()
                and not run.work.exists()
                and (not run.lab_started or run.lab_cleaned)
            )
            if not cleanup:
                raise GateError("cleanup_incomplete")
        except BaseException as error:  # noqa: BLE001 - preserve primary and retain unresolved actual owners.
            if primary is None:
                primary = _translate(error)
                stage = "cleanup"
            run.retain_unresolved_work()
        try:
            write_private(
                run.retained / "owned-children.json",
                json_bytes(
                    {
                        "schema_version": 1,
                        "cleanup_complete": cleanup,
                        "children": [
                            {
                                "pid": c.pid,
                                "stage": run.child_roles[c.pid],
                                "returncode": c.returncode,
                                "cleanup_failed": c.cleanup_failed,
                                "group_settled": isinstance(c, GroupedOwnedProcess)
                                and c.group_settled,
                            }
                            for c in run.children
                        ],
                    }
                ),
            )
            if primary is not None:
                write_private(
                    run.retained / "failure-context.json",
                    json_bytes(
                        {
                            "schema_version": 1,
                            "status": "failed",
                            "code": primary.code,
                            "stage": stage,
                            "parent": run.parent_context,
                            "cleanup_complete": cleanup,
                        }
                    ),
                )
            files = [p for p in run.retained.rglob("*") if p.is_file()]
            if (
                len(files) > MAX_RETAINED_FILES
                or sum(p.stat().st_size for p in files) > MAX_RETAINED_BYTES
            ):
                raise GateError("retention_failed")
            index_sha = run.retained_index()
            common.validate_manifest(
                run.retained, read_private(run.retained / "retained-index.json", 1048576)
            )
        except BaseException as error:  # noqa: BLE001 - indexing failure cannot replace primary or skip owned cleanup.
            if primary is None:
                primary = _translate(error)
                stage = "proof"
    if run is not None and primary is None and cleanup:
        run.passed.add(CASES[-1])
    count = len(run.passed) if run is not None else 0
    if primary is None and (count != 12 or not cleanup):
        primary = GateError("component_failed")
    value = {
        "schema_version": 1,
        "status": "passed" if primary is None else "failed",
        "mode": "local_fixed_work_installed" if args.installed else "local_fixed_work_source",
        "tests": 12,
        "passed": count,
        "failures": int(primary is not None),
        "errors": 0,
        "skipped": 0,
        "duration_seconds": time.monotonic() - started,
        "child_commands": run.commands + run.nested_commands if run is not None else 0,
        "package_assertions": 8 if run is not None and run.builder_report is not None else 0,
        "cleanup_complete": cleanup,
        "code": primary.code if primary is not None else "ok",
        "stage": stage if primary is not None else "complete",
        "retained_index_sha256": index_sha,
        "case_results": [{"name": n, "status": "passed"} for n in CASES[:count]],
    }
    raw = json_bytes(value)
    validated_report(raw)
    if target is not None:
        write_private(target, raw)
    sys.stdout.buffer.write(raw)
    return 0 if primary is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
