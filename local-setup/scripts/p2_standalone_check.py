"""Installed P2 starter qualification; reviewed 12 November 2026.

The standalone twenty assertions and the six installed-P1 adapter assertions have
separate reports and process budgets. Import and --plan perform no setup or I/O.
No provider, RTC, default service or automatic recovery queue is composed here.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import math
import os
import re
import shutil
import stat
import sys
import tarfile
import time
from collections.abc import Callable, Mapping
from contextlib import closing
from pathlib import Path
from typing import Any, Never, TypeVar
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from p3_document_package import GroupedOwnedProcess

from harness.process_control import OwnedProcess

MODE = "local_scripted_installed_p2_starter"
TOTAL_SECONDS, CLEANUP_SECONDS = 360, 20
MAX_CHILDREN = 32
MAX_STREAM_BYTES, MAX_CAPTURE_BYTES = 8192, 524288
MAX_PROOF_BYTES, MAX_EVIDENCE_BYTES, MAX_REPORT_BYTES = 2097152, 16777216, 32768
BASE_KEYS = frozenset(
    {
        "PATH",
        "HOME",
        "TMPDIR",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "SYSTEMROOT",
        "__CF_USER_TEXT_ENCODING",
        "NO_COLOR",
        "CI",
    }
)
CASE_NAMES = (
    "archive_bin_exports_and_strict_types_without_repository",
    "pure_plan_and_import_without_implicit_setup",
    "invalid_missing_foreign_config_fails_closed",
    "owner_bootstrap_then_runtime_no_ddl",
    "verified_association_and_foreign_scope_denial",
    "explicit_structured_case_revision_known_while_quiescent",
    "stale_revision_and_unlinked_input_do_not_authorize_mutation",
    "sms_commit_before_ack_with_original_receipt",
    "equal_replay_and_changed_payload_conflict",
    "distinct_equal_text_inputs_remain_distinct",
    "bounded_original_history_cursor_and_restart",
    "external_receipt_replay_conflict_before_capacity",
    "kill_after_ack_before_dispatch_fresh_recovery",
    "external_commit_ack_loss_lookup_no_duplicate",
    "fake_provider_acceptance_distinct_from_delivery",
    "ordinary_send_unknown_has_no_automatic_resend",
    "callback_replay_and_reorder_preserve_attempt_source",
    "explicit_recovery_known_only_replay_zero_io",
    "fresh_process_original_case_work_reply_facts",
    "actual_stop_dependent_ownership_and_useful_reopen",
)
P1_CASE_NAMES = (
    "installed_public_case_identity_scope_read",
    "public_revision_CAS_conflict_unknown_ACK",
    "exact_quote_confirmation_stale_rejection",
    "currentCase_allowlist_excludes_quote_control",
    "revision_zero_read_only_no_dispatch_claim",
    "public_supplier_effect_sources_no_extra_acceptance",
)
CODES = frozenset(
    {
        "invalid_arguments",
        "invalid_json",
        "invalid_proof",
        "invalid_environment",
        "unsafe_path",
        "report_exists",
        "deadline_exceeded",
        "child_budget",
        "child_failed",
        "capture_budget",
        "secret_in_evidence",
        "cleanup_incomplete",
        "protocol_not_frozen",
        "evidence_not_retained",
        "gate_failed",
    }
)
Result = TypeVar("Result")


class GateError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code if code in CODES else "gate_failed"
        super().__init__(self.code)


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise GateError("invalid_arguments")


ACTOR_MODES = frozenset(
    {
        "config-negative",
        "setup",
        "baseline-client",
        "gateway-a",
        "ack-client",
        "before-restart",
        "later-input",
        "delivery-begin",
        "delivery-recovery",
        "fresh-verify",
        "restore-verify",
        "p1-contract",
    }
)
STARTER_CODES = frozenset(
    {
        "InvalidConfiguration",
        "InvalidCommand",
        "UnsafeFile",
        "AccessDenied",
        "ApplicationBusy",
        "AssociationRequired",
        "AssociationRejected",
        "IdentityConflict",
        "Overloaded",
        "NotFound",
        "SchemaMismatch",
        "UpgradeRequired",
        "InvalidEvent",
        "DispatchClaimLost",
        "DispatchUnavailable",
        "OperationConflict",
        "RevisionConflict",
        "ClarificationRequired",
        "AcknowledgementUnknown",
        "OutcomeUnknown",
        "Unavailable",
        "CleanupIncomplete",
        "Closed",
    }
)


SNAPSHOT_PHASES = (
    "setup",
    "baseline",
    "ack-before-kill",
    "external-committed",
    "external-unknown",
    "recovered",
    "before-fresh",
    "after-fresh",
    "before-restore",
    "after-restore",
)
INBOX_TABLES = (
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
)
CASE_TABLES = ("case_metadata", "cases")
EXTERNAL_TABLES = (
    "idempotent_sms_receipts",
    "investigation_receipts",
    "ordinary_sms_attempts",
    "receipt_metadata",
)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise GateError("invalid_json")
        value[key] = item
    return value


def _constant(_: str) -> Never:
    raise GateError("invalid_json")


def decode(raw: bytes, maximum: int = MAX_PROOF_BYTES) -> dict[str, Any]:
    if type(raw) is not bytes or not 0 < len(raw) <= maximum:
        raise GateError("invalid_json")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
        if type(value) is not dict:
            raise GateError("invalid_json")
        _unicode(value)
        return value
    except (ValueError, UnicodeError, RecursionError, OverflowError):
        raise GateError("invalid_json") from None


def _unicode(value: Any) -> None:
    if type(value) is str:
        value.encode("utf-8")
    elif type(value) is list:
        for item in value:
            _unicode(item)
    elif type(value) is dict:
        for key, item in value.items():
            _unicode(key)
            _unicode(item)


def json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
            "utf-8"
        )
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise GateError("invalid_proof") from None


def exact(value: Any, expected: Any) -> bool:
    if type(value) is not type(expected):
        return False
    if type(expected) is dict:
        return value.keys() == expected.keys() and all(
            exact(value[k], v) for k, v in expected.items()
        )
    if type(expected) is list:
        return len(value) == len(expected) and all(exact(a, b) for a, b in zip(value, expected))
    return bool(value == expected)


def natural(value: Any, maximum: int, minimum: int = 0) -> bool:
    return type(value) is int and minimum <= value <= maximum


def uuid4_string(value: Any) -> bool:
    if type(value) is not str:
        return False
    try:
        parsed = UUID(value)
        return parsed.version == 4 and str(parsed) == value
    except ValueError:
        return False


def remaining(deadline: float) -> float:
    value = deadline - time.monotonic()
    if not math.isfinite(value) or value <= 0:
        raise GateError("deadline_exceeded")
    return value


def private_directory(path: Path) -> None:
    try:
        info = path.lstat()
        if (
            not path.is_absolute()
            or path != path.resolve()
            or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            raise GateError("unsafe_path")
    except OSError:
        raise GateError("unsafe_path") from None


def bounded_read(path: Path, maximum: int = MAX_PROOF_BYTES, *, allow_empty: bool = False) -> bytes:
    private_directory(path.parent)
    try:
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_nlink != 1
            or before.st_size > maximum
            or (not allow_empty and before.st_size == 0)
        ):
            raise GateError("unsafe_path")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise GateError("unsafe_path")
            raw = stream.read(maximum + 1)
            after = os.fstat(stream.fileno())
        if (
            (after.st_dev, after.st_ino, after.st_mode, after.st_uid, after.st_nlink, after.st_size)
            != (
                opened.st_dev,
                opened.st_ino,
                opened.st_mode,
                opened.st_uid,
                opened.st_nlink,
                opened.st_size,
            )
            or len(raw) != after.st_size
            or len(raw) > maximum
            or (not allow_empty and not raw)
        ):
            raise GateError("unsafe_path")
        return raw
    except OSError:
        raise GateError("unsafe_path") from None


def write_private(path: Path, raw: bytes, maximum: int = MAX_PROOF_BYTES) -> None:
    private_directory(path.parent)
    if type(raw) is not bytes or len(raw) > maximum:
        raise GateError("invalid_proof")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if bounded_read(path, maximum, allow_empty=True) != raw:
            raise GateError("evidence_not_retained")
    except OSError:
        raise GateError("evidence_not_retained") from None


def target_path(root: Path, requested: Path, *, p1_contract: bool = False) -> Path:
    leaf = "p2-starter-p1" if p1_contract else "p2-standalone"
    if (
        requested.is_absolute()
        or len(requested.parts) != 4
        or requested.parts[:3] != (".local", "validation", leaf)
        or re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}\.json", requested.name) is None
        or not root.is_absolute()
        or root != root.resolve()
    ):
        raise GateError("unsafe_path")
    root_info = root.lstat()
    if (
        not stat.S_ISDIR(root_info.st_mode)
        or root_info.st_uid != os.getuid()
        or root_info.st_mode & 0o022
    ):
        raise GateError("unsafe_path")
    current = root
    for part in requested.parts[:-1]:
        current /= part
        if not current.exists() and not current.is_symlink():
            current.mkdir(mode=0o700)
        info = current.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or current.is_symlink()
            or info.st_uid != os.getuid()
            or info.st_mode & 0o022
        ):
            raise GateError("unsafe_path")
    target = current / requested.name
    artifacts = target.with_name(target.stem + "-artifacts")
    if any(p.exists() or p.is_symlink() for p in (target, artifacts)):
        raise GateError("report_exists")
    return target


def validate_environment(
    environment: dict[str, str], *, required: frozenset[str], optional: frozenset[str] = frozenset()
) -> None:
    """Only a trusted frozen role supplies the required/optional sets."""
    if (
        type(environment) is not dict
        or not required <= environment.keys()
        or environment.keys() - required - optional - BASE_KEYS
        or any(
            type(k) is not str or type(v) is not str or not v or len(v) > 4096 or "\0" in v
            for k, v in environment.items()
        )
    ):
        raise GateError("invalid_environment")


def scan_secrets(raw: bytes, secrets: tuple[bytes, ...]) -> None:
    if any(type(secret) is not bytes or len(secret) < 16 for secret in secrets):
        raise GateError("invalid_proof")
    if any(secret in raw for secret in secrets):
        raise GateError("secret_in_evidence")


class ActualCalls:
    """Track actual thread work beyond abandoned/cancelled caller observations."""

    def __init__(self) -> None:
        self.tasks: set[asyncio.Task[Any]] = set()
        self.closing = False

    async def call(self, function: Callable[..., Result], *args: Any, **kwargs: Any) -> Result:
        if self.closing:
            raise GateError("cleanup_incomplete")
        return await self._owned(function, *args, **kwargs)

    async def cleanup_call(
        self, function: Callable[..., Result], *args: Any, **kwargs: Any
    ) -> Result:
        # Only the trusted dependency cleanup tier uses this after admission closes.
        return await self._owned(function, *args, **kwargs)

    async def _owned(self, function: Callable[..., Result], *args: Any, **kwargs: Any) -> Result:
        task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
        self.tasks.add(task)

        def settled(done: asyncio.Task[Any]) -> None:
            self.tasks.discard(done)
            if not done.cancelled():
                done.exception()

        task.add_done_callback(settled)
        return await asyncio.shield(task)

    async def drain(self, final_deadline: float) -> bool:
        if not self.tasks:
            return True
        _, pending = await asyncio.wait(
            tuple(self.tasks), timeout=max(0, final_deadline - time.monotonic())
        )
        return not pending and not self.tasks

    async def close(self, final_deadline: float) -> bool:
        self.closing = True
        return await self.drain(final_deadline)


class Children:
    """Append actual owners immediately; independently close all trusted groups."""

    def __init__(
        self, directory: Path, deadline: float, final_deadline: float, *, roles: frozenset[str]
    ) -> None:
        private_directory(directory)
        if (
            type(roles) is not frozenset
            or not roles
            or any(
                type(role) is not str or re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", role) is None
                for role in roles
            )
        ):
            raise GateError("invalid_environment")
        self.directory, self.deadline, self.final_deadline = directory, deadline, final_deadline
        self.roles = roles
        self.children: list[OwnedProcess] = []
        self.count, self.captured, self.reservations = 0, 0, 0
        self.start_failed = False
        self.names: set[str] = set()
        self._captured: set[int] = set()

    def start(
        self, name: str, argv: list[str], environment: Mapping[str, str], *, cwd: Path
    ) -> OwnedProcess:
        remaining(self.deadline)
        if (
            name not in self.roles
            or name in self.names
            or self.count >= MAX_CHILDREN
            or self.captured + self.reservations + 2 * MAX_STREAM_BYTES > MAX_CAPTURE_BYTES
            or not argv
            or not Path(argv[0]).is_absolute()
        ):
            raise GateError("child_budget")
        self.names.add(name)
        self.count += 1
        self.reservations += 2 * MAX_STREAM_BYTES
        try:
            child = GroupedOwnedProcess(
                argv,
                cwd=cwd,
                env=environment,
                output_directory=self.directory / name,
                max_output_bytes=MAX_STREAM_BYTES,
                final_deadline=self.final_deadline,
            )
        except BaseException:
            self.start_failed = True
            raise
        self.children.append(child)
        return child

    def capture(
        self, child: OwnedProcess, *, secrets: tuple[bytes, ...] = ()
    ) -> tuple[bytes, bytes]:
        if not any(owner is child for owner in self.children) or child.returncode is None:
            raise GateError("child_failed")
        raw = tuple(
            bounded_read(child.output_directory / name, MAX_STREAM_BYTES, allow_empty=True)
            for name in ("stdout.bin", "stderr.bin")
        )
        for stream in raw:
            scan_secrets(stream, secrets)
        if id(child) not in self._captured:
            self._captured.add(id(child))
            self.reservations -= 2 * MAX_STREAM_BYTES
            self.captured += sum(len(stream) for stream in raw)
        if self.captured + self.reservations > MAX_CAPTURE_BYTES:
            raise GateError("capture_budget")
        return raw[0], raw[1]

    def finish(
        self,
        child: OwnedProcess,
        *,
        accepted_codes: tuple[int, ...] = (0,),
        secrets: tuple[bytes, ...] = (),
    ) -> bytes:
        result = child.wait(timeout=min(300, remaining(self.deadline)))
        raw, _ = self.capture(child, secrets=secrets)
        child.close()
        if not settled(child):
            raise GateError("cleanup_incomplete")
        if result.returncode not in accepted_codes:
            raise GateError("child_failed")
        return raw

    def close(self) -> None:
        failed = self.start_failed
        for child in reversed(self.children):
            try:
                child.close()
                failed |= not settled(child)
            except BaseException:  # noqa: BLE001 - Retain actual owners and attempt independent cleanup.
                failed = True
        if failed:
            raise GateError("cleanup_incomplete")

    def all_settled(self) -> bool:
        return not self.start_failed and all(settled(child) for child in self.children)


def settled(child: OwnedProcess) -> bool:
    return (
        child.returncode is not None
        and not child.cleanup_failed
        and getattr(child, "group_settled", False) is True
    )


async def cleanup_dependencies(
    children: Children,
    actual: ActualCalls,
    final_deadline: float,
    schema_cleanup: Callable[[], Any] | None,
) -> bool:
    complete = True
    actual.closing = True
    try:
        await asyncio.to_thread(children.close)
    except BaseException:  # noqa: BLE001 - Retain actual owners and attempt independent cleanup.
        complete = False
    try:
        if not await actual.drain(final_deadline) or not children.all_settled():
            complete = False
    except BaseException:  # noqa: BLE001 - Retain actual owners and attempt independent cleanup.
        complete = False
    if complete and schema_cleanup is not None:
        try:
            await actual.cleanup_call(schema_cleanup)
        except BaseException:  # noqa: BLE001 - Retain actual owners and attempt independent cleanup.
            complete = False
    try:
        drained = await actual.close(final_deadline)
    except BaseException:  # noqa: BLE001 - Retain actual owners and attempt independent cleanup.
        drained = False
    return complete and drained and children.all_settled()


def validate_ready(raw: bytes, *, owner: str, process_id: int, kind: str) -> dict[str, Any]:
    value = decode(raw, 512)
    if (
        type(kind) is not str
        or kind not in {"gateway", "external"}
        or type(owner) is not str
        or re.fullmatch(r"[a-f0-9]{32}", owner) is None
        or not natural(process_id, 2**31 - 1, 1)
        or set(value) != {"schemaVersion", "owner", "pid", "kind", "profileId", "host", "port"}
        or not exact(value["schemaVersion"], 1)
        or value["owner"] != owner
        or not exact(value["pid"], process_id)
        or value["kind"] != kind
        or not uuid4_string(value["profileId"])
        or value["profileId"].replace("-", "") != owner
        or value["host"] != "127.0.0.1"
        or not natural(value["port"], 65535, 1)
    ):
        raise GateError("invalid_proof")
    return value


def validate_actor_stage(raw: bytes, mode: str) -> dict[str, Any]:
    if type(mode) is not str or mode not in ACTOR_MODES:
        raise GateError("invalid_proof")
    value = decode(raw, MAX_STREAM_BYTES)
    if not exact(
        value, {"schemaVersion": 1, "status": "passed", "mode": mode, "cleanupComplete": True}
    ):
        raise GateError("invalid_proof")
    return value


P1_CONTRACT_STAGES = frozenset(
    {
        "zero-read",
        "zero-release",
        "known-revise",
        "known-response",
        "unknown-entry",
        "unknown-outcome",
        "unknown-readback",
        "stale-reject",
    }
)


def validate_actor_failure(raw: bytes, mode: str) -> dict[str, Any]:
    value = decode(raw, 2048)
    if (
        type(mode) is not str
        or mode not in ACTOR_MODES
        or set(value)
        != {"schemaVersion", "status", "mode", "stage", "errorType", "code", "cleanupComplete"}
        or not exact(value["schemaVersion"], 1)
        or value["status"] != "failed"
        or value["mode"] != mode
        or type(value["stage"]) is not str
        or not (
            value["stage"]
            in {
                "configuration",
                "invalid-config",
                "association",
                "route",
                "gateway",
                "baseline",
                "ack",
                "before-restart",
                "recovered",
                "delivery-operation",
                "delivery-carriers",
                "recovery",
                "capacity",
                "original",
                "fresh",
                "command",
                "arguments",
                "bootstrap",
                "startup",
                "running",
                "cleanup",
            }
            or mode == "p1-contract"
            and value["stage"] in P1_CONTRACT_STAGES
        )
        or type(value["errorType"]) is not str
        or value["errorType"] not in {"StarterError", "AssertionError", "UnexpectedError"}
        or (
            value["code"] is not None
            and (type(value["code"]) is not str or value["code"] not in STARTER_CODES)
        )
        or type(value["cleanupComplete"]) is not bool
    ):
        raise GateError("invalid_proof")
    return value


def schema_tables(owner: str) -> dict[str, tuple[str, ...]]:
    if type(owner) is not str or re.fullmatch(r"[a-f0-9]{32}", owner) is None:
        raise GateError("invalid_proof")
    return {
        "p2_inbox_" + owner: INBOX_TABLES,
        "p2_case_" + owner: CASE_TABLES,
        "p2_demo_" + owner: EXTERNAL_TABLES,
    }


def snapshot_counts(value: Any, owner: str) -> dict[str, dict[str, int]]:
    expected = schema_tables(owner)
    if type(value) is not dict or value.keys() != expected.keys():
        raise GateError("invalid_proof")
    counts: dict[str, dict[str, int]] = {}
    for schema, names in expected.items():
        tables = value[schema]
        if type(tables) is not dict or set(tables) != set(names):
            raise GateError("invalid_proof")
        counts[schema] = {}
        for name in names:
            rows = tables[name]
            if (
                type(rows) is not list
                or len(rows) > 64
                or any(type(row) is not dict for row in rows)
            ):
                raise GateError("invalid_proof")
            counts[schema][name] = len(rows)
    return counts


def owner_snapshot(
    connect: Callable[[], Any], owner: str, *, deadline: float | None = None
) -> dict[str, Any]:
    """Independent whole-row observation, including stored catalog-snapshot rows.

    One fixed owner connection and one read-only repeatable-read transaction;
    the 65th row causes failure rather than a partial inventory. This does not
    substitute for the application's runtime schema/privilege preflight.
    """
    from psycopg import sql

    expected = schema_tables(owner)
    result: dict[str, Any] = {}
    with closing(connect()) as connection:
        connection.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        try:
            if connection.execute("SELECT current_user").fetchone()[0] != "continuity_migrator":
                raise GateError("invalid_proof")
            for schema, tables in expected.items():
                if deadline is not None:
                    remaining(deadline)
                identity = connection.execute(
                    "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname=%s", [schema]
                ).fetchone()
                names = [
                    row[0]
                    for row in connection.execute(
                        "SELECT tablename FROM pg_tables WHERE schemaname=%s ORDER BY tablename",
                        [schema],
                    )
                ]
                if identity != ("continuity_migrator",) or names != list(tables):
                    raise GateError("invalid_proof")
                data = {}
                for table in tables:
                    if deadline is not None:
                        remaining(deadline)
                    rows = connection.execute(
                        sql.SQL(
                            "SELECT to_jsonb(t) FROM {}.{} t ORDER BY to_jsonb(t)::text LIMIT 65"
                        ).format(sql.Identifier(schema), sql.Identifier(table))
                    ).fetchall()
                    if len(rows) > 64:
                        raise GateError("invalid_proof")
                    data[table] = [row[0] for row in rows]
                result[schema] = data
        finally:
            connection.rollback()
    snapshot_counts(result, owner)
    return result


def write_snapshots(directory: Path, snapshots: dict[str, Any], owner: str) -> dict[str, Any]:
    private_directory(directory)
    if type(snapshots) is not dict or set(snapshots) != set(SNAPSHOT_PHASES):
        raise GateError("invalid_proof")
    payloads: dict[str, bytes] = {}
    manifest: dict[str, Any] = {
        "schemaVersion": 1,
        "owner": owner,
        "codec": "json_sort_keys_compact_ascii_v1",
        "snapshots": {},
    }
    for phase in SNAPSHOT_PHASES:
        counts = snapshot_counts(snapshots[phase], owner)
        try:
            raw = json.dumps(
                snapshots[phase],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
            raise GateError("invalid_proof") from None
        if not 0 < len(raw) <= MAX_PROOF_BYTES:
            raise GateError("invalid_proof")
        payloads[phase] = raw
        manifest["snapshots"][phase] = {
            "path": "starter-sql-" + phase + ".json",
            "type": "postgres_owner_snapshot",
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "tableCounts": counts,
        }
    # Validate every complete phase and every bound before creating any output.
    manifest_raw = json_bytes(manifest)
    if sum(map(len, payloads.values())) + len(manifest_raw) > MAX_EVIDENCE_BYTES:
        raise GateError("capture_budget")
    for phase, raw in payloads.items():
        write_private(directory / manifest["snapshots"][phase]["path"], raw)
    write_private(directory / "starter-sql-snapshots.json", manifest_raw)
    return read_snapshots(directory, manifest_raw, owner)[0]


def read_snapshots(
    directory: Path, raw: bytes, owner: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = decode(raw)
    if (
        set(manifest) != {"schemaVersion", "owner", "codec", "snapshots"}
        or not exact(manifest["schemaVersion"], 1)
        or manifest["owner"] != owner
        or manifest["codec"] != "json_sort_keys_compact_ascii_v1"
        or type(manifest["snapshots"]) is not dict
        or set(manifest["snapshots"]) != set(SNAPSHOT_PHASES)
    ):
        raise GateError("invalid_proof")
    snapshots: dict[str, Any] = {}
    retained = directory / "starter-sql-snapshots.json"
    if (retained.exists() or retained.is_symlink()) and bounded_read(retained) != raw:
        raise GateError("invalid_proof")
    total = len(raw)
    for phase in SNAPSHOT_PHASES:
        descriptor = manifest["snapshots"][phase]
        if (
            type(descriptor) is not dict
            or set(descriptor) != {"path", "type", "bytes", "sha256", "tableCounts"}
            or descriptor["path"] != "starter-sql-" + phase + ".json"
            or descriptor["type"] != "postgres_owner_snapshot"
            or not natural(descriptor["bytes"], MAX_PROOF_BYTES, 1)
            or type(descriptor["sha256"]) is not str
            or re.fullmatch(r"[a-f0-9]{64}", descriptor["sha256"]) is None
        ):
            raise GateError("invalid_proof")
        payload = bounded_read(directory / descriptor["path"])
        total += len(payload)
        if total > MAX_EVIDENCE_BYTES:
            raise GateError("capture_budget")
        value = decode(payload)
        if (
            len(payload) != descriptor["bytes"]
            or hashlib.sha256(payload).hexdigest() != descriptor["sha256"]
            or not exact(snapshot_counts(value, owner), descriptor["tableCounts"])
            or json.dumps(
                value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
            ).encode()
            != payload
        ):
            raise GateError("invalid_proof")
        snapshots[phase] = value
    return manifest, snapshots


PERMISSION_DENIALS = (
    "create_table",
    "update_profile_id",
    "update_config_digest",
    "update_definition_digest",
    "update_catalog_snapshot",
    "update_max_receipts",
)


def validate_permission_proof(raw: bytes, owner: str) -> dict[str, Any]:
    value = decode(raw, 4096)
    if (
        set(value)
        != {
            "schemaVersion",
            "owner",
            "role",
            "denied",
            "counterUpdateAllowed",
            "rolledBack",
            "beforeDigest",
            "afterDigest",
        }
        or not exact(value["schemaVersion"], 1)
        or value["owner"] != owner
        or value["role"] != "livekit_lab"
        or not exact(value["counterUpdateAllowed"], True)
        or not exact(value["rolledBack"], True)
        or not exact(
            value["denied"],
            [{"operation": name, "sqlState": "42501"} for name in PERMISSION_DENIALS],
        )
        or type(value["beforeDigest"]) is not str
        or re.fullmatch(r"[a-f0-9]{64}", value["beforeDigest"]) is None
        or value["beforeDigest"] != value["afterDigest"]
    ):
        raise GateError("invalid_proof")
    return value


def runtime_permission_proof(
    runtime_connect: Callable[[], Any],
    owner_connect: Callable[[], Any],
    owner: str,
    *,
    deadline: float | None = None,
) -> dict[str, Any]:
    """Explicit negative instrumentation, rolled back even on unexpected grant.

    No runtime statement here is a business seed. A statement that unexpectedly
    succeeds fails qualification; rollback equality alone never proves denial.
    """
    import psycopg
    from psycopg import sql

    expected = schema_tables(owner)
    external = "p2_demo_" + owner

    def admit() -> None:
        if deadline is not None:
            remaining(deadline)

    admit()
    before = owner_snapshot(owner_connect, owner, deadline=deadline)
    denied: list[dict[str, str]] = []
    metadata = sql.Identifier(external, "receipt_metadata")
    commands = (
        sql.SQL("CREATE TABLE {}.permission_probe(value integer)").format(sql.Identifier(external)),
        sql.SQL("UPDATE {} SET profile_id='00000000-0000-4000-8000-000000000000'").format(metadata),
        sql.SQL("UPDATE {} SET config_digest=%s").format(metadata),
        sql.SQL("UPDATE {} SET definition_digest=%s").format(metadata),
        sql.SQL("UPDATE {} SET catalog_snapshot='{{}}'::jsonb").format(metadata),
        sql.SQL("UPDATE {} SET max_receipts=17").format(metadata),
    )
    admit()
    with closing(runtime_connect()) as connection:
        admit()
        connection.execute("BEGIN")
        try:
            admit()
            if connection.execute("SELECT current_user").fetchone() != ("livekit_lab",):
                raise GateError("invalid_proof")
            for name, statement in zip(PERMISSION_DENIALS, commands, strict=True):
                admit()
                connection.execute("SAVEPOINT permission_probe")
                try:
                    admit()
                    connection.execute(
                        statement,
                        ["0" * 64]
                        if name in {"update_config_digest", "update_definition_digest"}
                        else None,
                    )
                except psycopg.Error as error:
                    if error.sqlstate != "42501":
                        raise GateError("invalid_proof") from None
                    denied.append({"operation": name, "sqlState": "42501"})
                else:
                    raise GateError("invalid_proof")
                finally:
                    connection.execute("ROLLBACK TO SAVEPOINT permission_probe")
                    connection.execute("RELEASE SAVEPOINT permission_probe")
            admit()
            privileges = connection.execute(
                "SELECT a.attname,has_column_privilege(current_user,c.oid,a.attname,'UPDATE') "
                "FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname=%s AND c.relname='receipt_metadata' AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum",
                [external],
            ).fetchall()
            allowed = {"investigation_count", "idempotent_count", "ordinary_count"}
            admit()
            table_update = connection.execute(
                "SELECT has_table_privilege(current_user,%s,'UPDATE')",
                [external + ".receipt_metadata"],
            ).fetchone()
            if (
                len(privileges) != 10
                or any(
                    type(row[1]) is not bool or row[1] != (row[0] in allowed) for row in privileges
                )
                or table_update != (False,)
            ):
                raise GateError("invalid_proof")
            admit()
            rows = connection.execute(
                sql.SQL(
                    "UPDATE {} SET investigation_count=investigation_count WHERE singleton RETURNING singleton"
                ).format(metadata)
            ).fetchall()
            if rows != [(True,)]:
                raise GateError("invalid_proof")
        finally:
            connection.rollback()
    admit()
    after = owner_snapshot(owner_connect, owner, deadline=deadline)
    if not exact(before, after) or set(after) != set(expected):
        raise GateError("invalid_proof")

    def fingerprint(value: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(
                value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
            ).encode()
        ).hexdigest()

    proof = {
        "schemaVersion": 1,
        "owner": owner,
        "role": "livekit_lab",
        "denied": denied,
        "counterUpdateAllowed": True,
        "rolledBack": True,
        "beforeDigest": fingerprint(before),
        "afterDigest": fingerprint(after),
    }
    return validate_permission_proof(json_bytes(proof), owner)


def validate_archive(
    raw: bytes, payloads: dict[str, bytes], manifest: dict[str, Any]
) -> dict[str, Any]:
    """Compare every member with a predeclared fresh-build byte inventory.

    Package metadata is a separate exact semantic comparison; payloads include
    the raw README and all declared public guides/manifests, not checkout source.
    This function derives counts rather than treating the prediction114 as fact.
    """
    if (
        type(raw) is not bytes
        or not 0 < len(raw) <= 8 * 1024 * 1024
        or type(payloads) is not dict
        or not payloads
        or any(
            type(name) is not str
            or name == "package.json"
            or not name
            or Path(name).is_absolute()
            or ".." in Path(name).parts
            or Path(name).as_posix() != name
            or type(body) is not bytes
            or len(body) > 512 * 1024
            for name, body in payloads.items()
        )
    ):
        raise GateError("invalid_proof")
    expected = {"package/" + name for name in payloads} | {"package/package.json"}
    found: dict[str, bytes] = {}
    seen: set[str] = set()
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
            for member in archive:
                name = member.name
                if (
                    name.rstrip("/") in seen
                    or not (name.startswith("package/") or (name == "package" and member.isdir()))
                    or Path(name).is_absolute()
                    or ".." in Path(name).parts
                    or Path(name).as_posix() != name.rstrip("/")
                    or not (member.isfile() or member.isdir())
                    or member.size > 512 * 1024
                    or len(seen) >= 512
                ):
                    raise GateError("invalid_proof")
                seen.add(name.rstrip("/"))
                if member.isdir():
                    if member.size != 0 or not any(
                        path.startswith(name.rstrip("/") + "/") for path in expected
                    ):
                        raise GateError("invalid_proof")
                    continue
                total += member.size
                if name not in expected or total > 8 * 1024 * 1024:
                    raise GateError("invalid_proof")
                source = archive.extractfile(member)
                if source is None:
                    raise GateError("invalid_proof")
                with source:
                    body = source.read(512 * 1024 + 1)
                if len(body) != member.size:
                    raise GateError("invalid_proof")
                found[name] = body
    except (OSError, tarfile.TarError, ValueError, EOFError):
        raise GateError("invalid_proof") from None
    if (
        found.keys() != expected
        or not exact(decode(found["package/package.json"], 32768), manifest)
        or any(found["package/" + name] != body for name, body in payloads.items())
    ):
        raise GateError("invalid_proof")
    return {
        "schema_version": 1,
        "archive_sha256": hashlib.sha256(raw).hexdigest(),
        "archive_bytes": len(raw),
        "payload_count": len(payloads),
        "manifest_semantics_equal": True,
        "raw_manifest_equality_claimed": False,
        "payloads": {
            name: {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
            for name, body in sorted(payloads.items())
        },
    }


def retained_inventory(directory: Path) -> dict[str, Any]:
    """Exact physical inventory; only the root manifest excludes itself."""
    private_directory(directory)
    files: dict[str, dict[str, Any]] = {}
    total = 0
    for path in sorted(directory.rglob("*")):
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            private_directory(path)
            continue
        if path == directory / "retained-index.json":
            continue
        raw = bounded_read(path, MAX_EVIDENCE_BYTES, allow_empty=True)
        total += len(raw)
        if len(files) >= 2048 or total > MAX_EVIDENCE_BYTES:
            raise GateError("capture_budget")
        files[path.relative_to(directory).as_posix()] = {
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    return {"schema_version": 1, "files": files}


def validate_retained_index(directory: Path, raw: bytes) -> dict[str, Any]:
    value = decode(raw, MAX_PROOF_BYTES)
    if not exact(value, retained_inventory(directory)):
        raise GateError("invalid_proof")
    # The root index is a private control file when already present, even though
    # it is the sole exclusion from its own content inventory.
    index = directory / "retained-index.json"
    if (index.exists() or index.is_symlink()) and bounded_read(index, MAX_PROOF_BYTES) != raw:
        raise GateError("invalid_proof")
    return value


def build_configurations(root: Path, work: Path) -> tuple[Path, ...]:
    """Approved derivative outputs, not a claim of private staging compilation."""
    project = root / "projects/channel-continuity"
    private_directory(work)
    result = []
    for name, base, output in (
        ("production", "tsconfig.json", project / "dist"),
        ("examples", "tsconfig.examples.json", project / "dist/examples"),
        ("starter", "tsconfig.starter.json", project / "dist/examples"),
    ):
        path = work / ("build-" + name + ".json")
        write_private(
            path,
            json_bytes(
                {
                    "extends": str(project / base),
                    "compilerOptions": {
                        "outDir": str(output),
                        "tsBuildInfoFile": str(work / (name + ".tsbuildinfo")),
                        "typeRoots": [str(project / "node_modules/@types")],
                    },
                }
            ),
            16384,
        )
        result.append(path)
    return tuple(result)


def expected_public_payloads(project: Path) -> dict[str, bytes]:
    expected: set[str] = {"README.md", "STARTER.md", "starter/bounded-v1.json"}
    for path in (project / "src").rglob("*.ts"):
        if path.is_symlink() or not path.is_file() or path.name.endswith(".d.ts"):
            raise GateError("invalid_proof")
        stem = path.relative_to(project / "src").with_suffix("").as_posix()
        expected.update({"dist/" + stem + ".js", "dist/" + stem + ".d.ts"})
    for path in (project / "examples").rglob("*.ts"):
        if path.is_symlink() or not path.is_file() or path.name.endswith(".d.ts"):
            raise GateError("invalid_proof")
        stem = path.relative_to(project / "examples").with_suffix("").as_posix()
        expected.add("dist/examples/" + stem + ".js")
        if path.is_relative_to(project / "examples/standalone"):
            expected.add("dist/examples/" + stem + ".d.ts")
    actual = {
        path.relative_to(project).as_posix()
        for path in (project / "dist").rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if actual != {name for name in expected if name.startswith("dist/")}:
        raise GateError("invalid_proof")
    payloads = {}
    for name in sorted(expected):
        path = project / name
        if path.is_symlink() or not path.is_file():
            raise GateError("invalid_proof")
        raw = path.read_bytes()
        if len(raw) > 512 * 1024:
            raise GateError("invalid_proof")
        payloads[name] = raw
    return payloads


def offline_environment() -> dict[str, str]:
    environment = {name: value for name, value in os.environ.items() if name in BASE_KEYS}
    environment.update(CI="1", NO_COLOR="1", COREPACK_ENABLE_NETWORK="0")
    if "COREPACK_HOME" in os.environ:
        environment["COREPACK_HOME"] = os.environ["COREPACK_HOME"]
    validate_environment(
        environment,
        required=frozenset({"COREPACK_ENABLE_NETWORK"}),
        optional=frozenset({"COREPACK_HOME"}),
    )
    return environment


def tool(name: str) -> Path:
    selected = shutil.which(name)
    if selected is None or not Path(selected).is_absolute() or not Path(selected).is_file():
        raise GateError("invalid_environment")
    # Keep the selected executable path. Resolving a Python venv interpreter
    # before exec would change its environment; all callers record exact argv.
    return Path(selected).absolute()


# Pinned pnpm12.18 generated cmd-shim; only contained path slots are normalized.
PNPM_SHIM_NORMALIZED_SHA256 = "7d93f98ae131a6e59aff96e1ca793b15b5516e7baebee1a7b23bdb521d7582cd"
SHIM_PATH = re.compile(rb'"(\$basedir_(?:abs|win))"/\x27([A-Za-z0-9@._+/-]+)\x27')


def executable_bytes(path: Path, maximum: int = 16384, *, single_link: bool = True) -> bytes:
    before = path.lstat()
    require(
        stat.S_ISREG(before.st_mode)
        and before.st_uid == os.getuid()
        and not before.st_mode & 0o022
        and bool(before.st_mode & 0o100)
    )
    require(not single_link or before.st_nlink == 1)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        require(
            (opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino)
            and 0 < opened.st_size <= maximum
        )
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    require(
        len(raw) == opened.st_size
        and (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        == (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
    )
    return raw


def installed_bin(
    consumer: Path, manifest: dict[str, Any], payloads: dict[str, bytes]
) -> tuple[Path, dict[str, Any], bytes]:
    """Execute the actual installed mapping, with an exact pinned shim template."""
    package = (consumer / "node_modules/@livekit-ecosystem/channel-continuity").resolve()
    require(package.is_relative_to(consumer))
    require(exact(decode((package / "package.json").read_bytes(), 32768), manifest))
    mapping = manifest["bin"]
    require(type(mapping) is dict and set(mapping) == {"p2-channel-starter"})
    name = mapping["p2-channel-starter"]
    require(name == "dist/examples/standalone-channel.js" and name in payloads)
    target = package / name
    require(executable_bytes(target, 131072, single_link=False) == payloads[name])
    path = consumer / "node_modules/.bin/p2-channel-starter"
    info = path.lstat()
    require(info.st_uid == os.getuid())
    if stat.S_ISLNK(info.st_mode):
        require(path.resolve() == target.resolve() and path.resolve().is_relative_to(consumer))
        raw = os.readlink(path).encode()
        require(0 < len(raw) <= 4096)
        kind, normalized = "symlink", None
    else:
        raw = executable_bytes(path)
        require(raw.startswith(b"#!/bin/sh\n") and b"\x00" not in raw)
        markers = re.findall(rb"^# cmd-shim-target=([A-Za-z0-9@._+/-]+)$", raw, re.MULTILINE)
        require(len(markers) == 1)
        selected = markers[0]
        relative = Path(selected.decode("ascii"))
        require(
            not relative.is_absolute() and (path.parent / relative).resolve() == target.resolve()
        )
        matches = list(SHIM_PATH.finditer(raw))
        require(len(matches) == 12)
        for match in matches:
            item = Path(match[2].decode("ascii"))
            require(
                not item.is_absolute() and (path.parent / item).resolve().is_relative_to(consumer)
            )
        normalized_raw = SHIM_PATH.sub(
            lambda m: (
                b'"'
                + m[1]
                + b'"/\x27'
                + (b"@TARGET@" if m[2] == selected else b"@NODE_PATH@")
                + b"\x27"
            ),
            raw,
        )
        normalized_raw = normalized_raw.replace(
            b"# cmd-shim-target=" + selected, b"# cmd-shim-target=@TARGET@"
        )
        normalized = hashlib.sha256(normalized_raw).hexdigest()
        require(normalized == PNPM_SHIM_NORMALIZED_SHA256)
        kind = "pnpm_regular_shim"
    proof = {
        "schemaVersion": 1,
        "kind": kind,
        "path": "node_modules/.bin/p2-channel-starter",
        "target": name,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "targetSha256": hashlib.sha256(payloads[name]).hexdigest(),
        "normalizedSha256": normalized,
    }
    return path, proof, raw


def prepare_installed(
    root: Path, work: Path, artifacts: Path, children: Children
) -> dict[str, Any]:
    """Four directly owned offline commands; no configuration, PG or services."""
    private_directory(work)
    private_directory(artifacts)
    project = root / "projects/channel-continuity"
    node, corepack = tool("node"), tool("corepack")
    configs = build_configurations(root, work)
    write_private(
        artifacts / "compiler-configurations.json",
        json_bytes({path.name: decode(bounded_read(path, 16384), 16384) for path in configs}),
        16384,
    )
    environment = offline_environment()
    compiler = project / "node_modules/typescript/lib/tsc.js"
    if not compiler.is_file():
        raise GateError("invalid_environment")
    child = children.start(
        "compile",
        [str(node), str(compiler), "--build", *[str(path) for path in configs]],
        environment,
        cwd=project,
    )
    children.finish(child)
    payloads = expected_public_payloads(project)
    archives = work / "archives"
    archives.mkdir(mode=0o700)
    child = children.start(
        "pack",
        [str(corepack), "pnpm", "pack", "--pack-destination", str(archives)],
        environment,
        cwd=project,
    )
    children.finish(child)
    matches = list(archives.glob("*.tgz"))
    if len(matches) != 1 or matches[0].is_symlink():
        raise GateError("invalid_proof")
    archive = matches[0]
    raw = archive.read_bytes()
    manifest = decode((project / "package.json").read_bytes(), 32768)
    parity = validate_archive(raw, payloads, manifest)
    write_private(artifacts / "package.tgz", raw, 8 * 1024 * 1024)
    write_private(artifacts / "archive-parity.json", json_bytes(parity))
    consumer = work / "consumer"
    consumer.mkdir(mode=0o700)
    package = {
        "name": "p2-starter-installed-consumer",
        "version": "1.0.0",
        "private": True,
        "type": "module",
        "packageManager": decode((root / "package.json").read_bytes(), 32768)["packageManager"],
        "dependencies": {"@livekit-ecosystem/channel-continuity": "file:" + str(archive)},
        "devDependencies": {"typescript": "7.0.2", "@types/node": "26.6.6"},
    }
    config = {
        "compilerOptions": {
            "target": "ES2022",
            "module": "NodeNext",
            "moduleResolution": "NodeNext",
            "strict": True,
            "noUncheckedIndexedAccess": True,
            "exactOptionalPropertyTypes": True,
            "noUnusedLocals": True,
            "noUnusedParameters": True,
            "verbatimModuleSyntax": True,
            "skipLibCheck": False,
            "types": ["node"],
            "outDir": "dist",
        },
        "include": ["consumer.ts", "starter-p1-consumer.ts"],
    }
    write_private(consumer / "package.json", json_bytes(package), 16384)
    write_private(consumer / "tsconfig.json", json_bytes(config), 16384)
    write_private(artifacts / "consumer-package.json", json_bytes(package), 16384)
    write_private(artifacts / "consumer-tsconfig.json", json_bytes(config), 16384)
    for original, target in (
        ("installed-starter-consumer.ts", "consumer.ts"),
        ("starter-p1-consumer.ts", "starter-p1-consumer.ts"),
    ):
        source = project / "tests/fixtures" / original
        if source.is_symlink() or not source.is_file():
            raise GateError("protocol_not_frozen")
        body = source.read_bytes()
        write_private(consumer / target, body)
        write_private(artifacts / target, body)
    child = children.start(
        "install",
        [str(corepack), "pnpm", "install", "--offline", "--ignore-scripts"],
        environment,
        cwd=consumer,
    )
    children.finish(child)
    if (
        (consumer / "node_modules/@types/pg").exists()
        or (consumer / "node_modules/@types/pg").is_symlink()
        or list((consumer / "node_modules/.pnpm").glob("@types+pg@*"))
    ):
        raise GateError("invalid_proof")
    bin_path, bin_proof, bin_raw = installed_bin(consumer, manifest, payloads)
    write_private(artifacts / "installed-bin.json", json_bytes(bin_proof), 16384)
    write_private(artifacts / "installed-bin.bin", bin_raw, 16384)
    child = children.start(
        "strict-consumer",
        [
            str(node),
            str(consumer / "node_modules/typescript/lib/tsc.js"),
            "--project",
            "tsconfig.json",
        ],
        environment,
        cwd=consumer,
    )
    children.finish(child)
    installed = (consumer / "node_modules/@livekit-ecosystem/channel-continuity").resolve()
    if not installed.is_relative_to(consumer) or installed == project:
        raise GateError("invalid_proof")
    for name, body in payloads.items():
        path = installed / name
        if path.is_symlink() or not path.is_file() or path.read_bytes() != body:
            raise GateError("invalid_proof")
    if not exact(decode((installed / "package.json").read_bytes(), 32768), manifest):
        raise GateError("invalid_proof")
    for name in ("pnpm-lock.yaml",):
        path = consumer / name
        if path.is_symlink() or not path.is_file():
            raise GateError("invalid_proof")
        write_private(artifacts / ("consumer-" + name), path.read_bytes())
    for name in ("consumer.js", "starter-p1-consumer.js"):
        path = consumer / "dist" / name
        if path.is_symlink() or not path.is_file():
            raise GateError("invalid_proof")
        write_private(artifacts / ("compiled-" + name), path.read_bytes())
    proof = {
        "schemaVersion": 1,
        "outsideCheckout": not consumer.is_relative_to(root),
        "installedRoot": str(installed),
        "payloads": len(payloads),
        "archiveSha256": parity["archive_sha256"],
        "scriptsDisabled": True,
        "offline": True,
        "strictNodeNext": True,
        "skipLibCheck": False,
        "typesPgInstalled": False,
        "compilerConfigurations": {path.name: decode(bounded_read(path)) for path in configs},
    }
    if not proof["outsideCheckout"]:
        raise GateError("invalid_proof")
    write_private(artifacts / "installed-package-proof.json", json_bytes(proof))
    return {
        "consumer": consumer,
        "bin": bin_path,
        "binProof": bin_proof,
        "node": node,
        "archive": archive,
        "payloads": payloads,
        "manifest": manifest,
        "proof": proof,
    }


NORMAL_ROLES = (
    "compile",
    "pack",
    "install",
    "strict-consumer",
    "plan",
    "config-negative",
    "bootstrap",
    "setup",
    "external",
    "serve-normal",
    "baseline-client",
    "gateway-a",
    "ack-client",
    "before-restart",
    "serve-b",
    "later-input",
    "delivery-begin",
    "delivery-recovery",
    "history",
    "fresh-verify",
    "docker-discovery",
    "dump",
    "copy-out",
    "copy-in",
    "restore",
    "restore-verify",
)
PROOF_KEYS = {
    "starter-setup.json": "initialCase association messages route afterCase",
    "starter-baseline.json": "messages dispatches externalReceipts historyPages replay conflictStatus foreignStatus",
    "starter-ack.json": "httpStatus receipt message",
    "starter-before-restart.json": "message dispatch lookup",
    "starter-recovered.json": "originalMessage replayedReceipt dispatch externalReceipt laterMessage laterDispatch laterExternal",
    "starter-external-held.json": "message record",
    "starter-unknown.json": "message operationOutcome dispatch ordinary idempotent relay outcomes",
    "starter-delivery.json": "operation ordinary idempotent callbacks callbackFacts recoveries replayedRecoveries providerCalls",
    "starter-capacity.json": "investigation idempotent ordinary ordinaryPhysicalProbe",
    "starter-original.json": "cases messages dispatches replies callbacks recoveries externalReceipts historyPages recoveryReplay",
    "starter-fresh.json": "facts metrics",
    "starter-restored.json": "facts metrics",
}


def shape(value: Any, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise GateError("invalid_proof")
    return value


def require(condition: bool) -> None:
    if not condition:
        raise GateError("invalid_proof")


def one(rows: Any, field: str, expected: Any) -> dict[str, Any]:
    require(type(rows) is list)
    matched = [r for r in rows if type(r) is dict and exact(r.get(field), expected)]
    require(len(matched) == 1)
    return matched[0]


def fixed_ids(owner: str) -> dict[str, Any]:
    schema_tables(owner)

    def identity(label: str) -> str:
        h = hashlib.sha256(("p2-starter:41:" + owner + ":" + label).encode()).hexdigest()
        return (
            h[:8]
            + "-"
            + h[8:12]
            + "-4"
            + h[13:16]
            + "-"
            + format((int(h[16], 16) & 3) | 8, "x")
            + h[17:20]
            + "-"
            + h[20:32]
        )

    return {
        "schemaVersion": 1,
        "owner": owner,
        "events": {
            k: {"eventId": "starter_" + owner + "_" + k, "messageId": "message_" + owner + "_" + k}
            for k in "RTKUV"
        },
        "outbound": {k: identity("outbound:" + k) for k in ("ordinary", "idempotent")},
        "responses": {k: "reply_" + owner + "_" + k for k in ("ordinary", "idempotent")},
        "recovery": {
            k: identity("recovery:" + k) for k in ("ordinary", "ordinaryRetry", "idempotent")
        },
        "callbacks": {k: "callback_" + owner + "_" + k for k in ("delivered", "sent")},
        "probes": {
            "ordinaryPhysical": {
                "outboundId": identity("physical:outbound"),
                "attemptId": identity("physical:attempt"),
                "providerOperationKey": identity("physical:operation"),
                "responseId": "physical_" + owner,
            },
            "investigations": [identity("investigation:" + str(i)) for i in range(11)],
            "idempotent": [identity("idempotent:" + str(i)) for i in range(15)],
            "ordinary": [identity("ordinary:" + str(i)) for i in range(13)],
        },
    }


def validate_proof(raw: bytes, name: str, owner: str) -> dict[str, Any]:
    if name not in PROOF_KEYS:
        raise GateError("invalid_proof")
    value = decode(raw)
    shape(value, {"schemaVersion", "owner", *PROOF_KEYS[name].split()})
    require(exact(value["schemaVersion"], 1) and value["owner"] == owner)
    return value


def zero_provider_calls(value: Any) -> None:
    require(exact(value, {"before": 0, "after": 0, "requests": []}))


def relay_record(value: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    shape(
        value,
        {
            "path",
            "request",
            "requestDigest",
            "requestBytes",
            "response",
            "responseDigest",
            "responseBytes",
            "httpStatus",
        },
    )
    require(
        value["path"] in {"/v1/investigations/accept", "/v1/sms/send", "/v1/idempotent-sms/send"}
    )
    require(exact(value["httpStatus"], 200))
    parsed = []
    for prefix, maximum in (("request", 32768), ("response", 4096)):
        require(type(value[prefix]) is str)
        raw = value[prefix].encode("utf-8")
        require(0 < len(raw) <= maximum and exact(value[prefix + "Bytes"], len(raw)))
        require(value[prefix + "Digest"] == hashlib.sha256(raw).hexdigest())
        parsed.append(decode(raw, maximum))
    return parsed[0], parsed[1]


def validate_owner_joins(
    proofs: dict[str, dict[str, Any]], snapshots: dict[str, Any], config: dict[str, Any], owner: str
) -> dict[str, Any]:
    """Recompute original identity and canonical row joins independently of actors."""
    require(set(proofs) == set(PROOF_KEYS) and set(snapshots) == set(SNAPSHOT_PHASES))
    for value in snapshots.values():
        snapshot_counts(value, owner)
    ids = fixed_ids(owner)
    inbox, case, external = tuple(schema_tables(owner))
    final = snapshots["before-restore"]
    require(exact(final, snapshots["after-restore"]))
    require(exact(snapshots["before-fresh"], snapshots["after-fresh"]))
    require(exact(snapshots["recovered"], snapshots["before-fresh"]))
    original = proofs["starter-original.json"]
    facts = {k: original[k] for k in PROOF_KEYS["starter-original.json"].split()}
    for name in ("starter-fresh.json", "starter-restored.json"):
        require(exact(proofs[name]["facts"], facts))
    restored_metrics = proofs["starter-restored.json"]["metrics"]
    require(
        exact(
            restored_metrics,
            {
                "application": {
                    "commandsActive": 0,
                    "retainedGraphs": 0,
                    "gatewayActive": False,
                    "closing": True,
                },
                "external": {
                    "started": 5,
                    "known": 5,
                    "rejected": 0,
                    "active": 0,
                    "sockets": 0,
                    "closing": True,
                    "profileReads": 0,
                },
            },
        )
    )
    zero_provider_calls(original["recoveryReplay"])
    for name in ("starter-fresh.json", "starter-restored.json"):
        zero_provider_calls(proofs[name]["facts"]["recoveryReplay"])
    binding = config["bindings"][0]
    scope = binding["accountScope"]
    provider = binding["providerScope"]
    require(type(original["messages"]) is list and len(original["messages"]) == 5)
    receipts: dict[str, str] = {}
    operation_keys: set[str] = set()
    for label in "RTKUV":
        message = one(
            original["messages"],
            "event",
            one(
                [m["event"] for m in original["messages"]],
                "eventId",
                ids["events"][label]["eventId"],
            ),
        )
        shape(
            message, {"event", "receipt", "operationKey", "processingState", "associationVersion"}
        )
        event, receipt = message["event"], message["receipt"]
        shape(receipt, {"receiptId", "eventId", "messageId", "acceptanceSequence", "acceptedAt"})
        require(
            receipt["eventId"] == event["eventId"] and receipt["messageId"] == event["messageId"]
        )
        require(exact(event["accountScope"], scope) and exact(event["providerScope"], provider))
        require(
            event["caseId"] == binding["caseId"]
            and event["conversationId"] == binding["conversationId"]
        )
        require(message["associationVersion"] == "1")
        require(event["messageId"] == ids["events"][label]["messageId"])
        require(uuid4_string(receipt["receiptId"]) and uuid4_string(message["operationKey"]))
        require(message["processingState"] == "dispatched")
        row = one(final[inbox]["inbox"], "receipt_id", receipt["receiptId"])
        require(row["event_id"] == event["eventId"] and row["message_id"] == event["messageId"])
        require(row["tenant_id"] == scope["tenantId"] and row["account_id"] == scope["accountId"])
        require(row["conversation_id"] == binding["conversationId"])
        require(
            row["provider"] == provider["provider"]
            and row["provider_account_id"] == provider["providerAccountId"]
        )
        require(
            row["sender_id"] == binding["senderId"]
            if "sender_id" in row
            else event["senderId"] == binding["senderId"]
        )
        require(exact(decode(row["wire_json"].encode()), event))
        require(str(row["acceptance_sequence"]) == receipt["acceptanceSequence"])
        intent = one(final[inbox]["processing_intents"], "receipt_id", receipt["receiptId"])
        require(
            intent["operation_key"] == message["operationKey"] and intent["state"] == "dispatched"
        )
        plan_row = one(final[inbox]["dispatch_plans"], "receipt_id", receipt["receiptId"])
        canonical = plan_row["payload_json"].encode()
        require(hashlib.sha256(canonical).hexdigest() == plan_row["payload_digest"])
        submission = decode(canonical)
        require(
            submission["operationKey"] == message["operationKey"]
            and exact(submission["scope"], scope)
        )
        require(
            submission["caseId"] == binding["caseId"]
            and submission["conversationId"] == binding["conversationId"]
        )
        ext = one(
            final[external]["investigation_receipts"], "operation_key", message["operationKey"]
        )
        require(ext["tenant_id"] == scope["tenantId"] and ext["account_id"] == scope["accountId"])
        require(
            ext["canonical_payload"] == plan_row["payload_json"]
            and ext["payload_digest"] == plan_row["payload_digest"]
        )
        require(ext["receipt_id"] == intent["external_receipt_id"])
        dispatch = one(original["dispatches"], "operationKey", message["operationKey"])
        require(
            dispatch["state"] == "dispatched" and dispatch["externalReceiptId"] == ext["receipt_id"]
        )
        public_receipt = one(
            [r["receipt"] for r in original["externalReceipts"]],
            "operationKey",
            message["operationKey"],
        )
        require(
            public_receipt["receiptId"] == ext["receipt_id"]
            and public_receipt["payloadDigest"] == ext["payload_digest"]
        )
        operation_keys.add(message["operationKey"])
        receipts[label] = receipt["receiptId"]
    require(len(operation_keys) == 5 and len(set(receipts.values())) == 5)
    require(
        len(final[inbox]["inbox"])
        == len(final[inbox]["processing_intents"])
        == len(final[inbox]["dispatch_plans"])
        == 5
    )
    require(
        len(final[external]["investigation_receipts"])
        == len(final[external]["idempotent_sms_receipts"])
        == len(final[external]["ordinary_sms_attempts"])
        == 16
    )
    require(len(final[inbox]["reply_intents"]) == len(final[inbox]["send_attempts"]) == 2)
    require(
        len(final[inbox]["callback_observations"]) == 2
        and len(final[inbox]["send_recovery_commands"]) == 3
    )
    metadata = final[external]["receipt_metadata"]
    require(len(metadata) == 1)
    require(metadata[0]["profile_id"] == config["profileId"] and exact(metadata[0]["version"], 1))
    require(
        metadata[0]["definition_digest"]
        == "8ca1848028e76cf0d3eaab4546315a78449ec5b57c9af23bdfd6e6a18eeb54d1"
    )
    require(exact(metadata[0]["max_receipts"], 16))
    for field in ("investigation_count", "idempotent_count", "ordinary_count"):
        require(exact(metadata[0][field], 16))
    require(
        type(metadata[0]["catalog_snapshot"]) is dict
        and metadata[0]["catalog_snapshot"]["owner"] == "continuity_migrator"
    )
    for table, raw_field, hash_field in (
        ("investigation_receipts", "canonical_payload", "payload_digest"),
        ("idempotent_sms_receipts", "canonical_operation", "operation_digest"),
        ("ordinary_sms_attempts", "canonical_request", "request_digest"),
    ):
        for row in final[external][table]:
            require(row["tenant_id"] == scope["tenantId"])
            raw = row[raw_field].encode()
            require(0 < len(raw) <= 32768 and hashlib.sha256(raw).hexdigest() == row[hash_field])
            content = decode(raw, 32768)
            if table == "investigation_receipts":
                require(exact(content["scope"], scope) and row["account_id"] == scope["accountId"])
            else:
                require(
                    row["provider"] == provider["provider"]
                    and row["provider_account_id"] == provider["providerAccountId"]
                )
                require(
                    exact(content["scope"], scope) and exact(content["providerScope"], provider)
                )
            require(
                content["caseId"] == binding["caseId"]
                and content["conversationId"] == binding["conversationId"]
            )
    t = one(
        original["messages"],
        "operationKey",
        one(final[inbox]["processing_intents"], "receipt_id", receipts["T"])["operation_key"],
    )
    u = one(
        original["messages"],
        "operationKey",
        one(final[inbox]["processing_intents"], "receipt_id", receipts["U"])["operation_key"],
    )
    require(t["event"]["body"] == u["event"]["body"] and t["operationKey"] != u["operationKey"])
    setup = proofs["starter-setup.json"]
    require(setup["initialCase"]["revision"] == "0" and setup["afterCase"]["revision"] == "1")
    require(setup["route"]["status"] == "revised")
    require(exact(setup["initialCase"]["request"], binding["initialCase"]["request"]))
    require(len(original["cases"]) == 1 and original["cases"][0]["revision"] == "1")
    require(
        original["cases"][0]["committed"] is False and original["cases"][0]["cancelled"] is False
    )
    case_row = one(final[case]["cases"], "case_id", binding["caseId"])
    require(
        case_row["tenant_id"] == scope["tenantId"] and case_row["account_id"] == scope["accountId"]
    )
    require(
        str(case_row["revision"]) == "1"
        and case_row["cancelled"] is False
        and case_row["committed"] is False
    )
    require(exact(decode(case_row["request_json"].encode()), original["cases"][0]["request"]))
    baseline = proofs["starter-baseline.json"]
    require(exact(baseline["conflictStatus"], 409) and exact(baseline["foreignStatus"], 401))
    require(baseline["replay"]["replayed"] is True)
    require(exact(baseline["replay"]["receipt"], original["messages"][1]["receipt"]))
    require(exact(baseline["messages"], original["messages"][:2]))
    require(
        exact([m for p in baseline["historyPages"] for m in p["messages"]], baseline["messages"])
    )
    require(
        exact([m for p in original["historyPages"] for m in p["messages"]], original["messages"])
    )
    # The one ACK-before-dispatch kill has a genuinely pending original with no plan/attempt/effect.
    ack = proofs["starter-ack.json"]
    before = proofs["starter-before-restart.json"]
    require(exact(ack["httpStatus"], 200) and ack["receipt"]["receiptId"] == receipts["K"])
    require(exact(ack["message"], before["message"]))
    pending = one(
        snapshots["ack-before-kill"][inbox]["processing_intents"], "receipt_id", receipts["K"]
    )
    require(
        pending["state"] == "pending"
        and exact(pending["possible_external"], False)
        and exact(pending["attempt_count"], 0)
    )
    require(
        not any(
            r["receipt_id"] == receipts["K"]
            for r in snapshots["ack-before-kill"][inbox]["dispatch_plans"]
        )
    )
    require(before["dispatch"]["state"] == "pending" and before["lookup"]["status"] == "absent")
    require(
        not any(
            r["operation_key"] == pending["operation_key"]
            for r in snapshots["ack-before-kill"][external]["investigation_receipts"]
        )
    )
    recovered = proofs["starter-recovered.json"]
    require(
        exact(recovered["originalMessage"], {**ack["message"], "processingState": "dispatched"})
        and recovered["replayedReceipt"]["receiptId"] == receipts["K"]
    )
    require(
        recovered["dispatch"]["state"] == "dispatched"
        and recovered["laterDispatch"]["state"] == "dispatched"
    )
    held = proofs["starter-external-held.json"]
    request, response = relay_record(held["record"])
    require(held["record"]["path"] == "/v1/investigations/accept")
    require(held["message"]["receipt"]["receiptId"] == receipts["V"])
    external_v = one(
        snapshots["external-committed"][external]["investigation_receipts"],
        "operation_key",
        held["message"]["operationKey"],
    )
    require(
        request["canonicalPayload"] == external_v["canonical_payload"]
        and request["payloadDigest"] == external_v["payload_digest"]
    )
    require(response["receipt"]["receiptId"] == external_v["receipt_id"])
    unknown = proofs["starter-unknown.json"]
    require(exact(unknown["operationOutcome"], {"ok": False, "code": "DispatchUnavailable"}))
    require(unknown["dispatch"]["state"] == "uncertain")
    v_intent = one(
        snapshots["external-unknown"][inbox]["processing_intents"], "receipt_id", receipts["V"]
    )
    require(
        v_intent["state"] == "uncertain"
        and v_intent["possible_external"] is True
        and v_intent["external_receipt_id"] is None
    )
    require(type(unknown["relay"]) is list and len(unknown["relay"]) == 3)
    require(
        {r["path"] for r in unknown["relay"]}
        == {"/v1/investigations/accept", "/v1/sms/send", "/v1/idempotent-sms/send"}
    )
    for record in unknown["relay"]:
        relay_record(record)
    ordinary_request, ordinary_response = relay_record(
        one(unknown["relay"], "path", "/v1/sms/send")
    )
    ordinary_attempt = unknown["ordinary"]["attempts"][0]
    require(exact(ordinary_request, ordinary_attempt["request"]))
    ordinary_row = one(
        final[external]["ordinary_sms_attempts"], "attempt_id", ordinary_request["attemptId"]
    )
    require(exact(decode(ordinary_row["canonical_request"].encode()), ordinary_request))
    require(ordinary_row["request_digest"] == ordinary_attempt["requestDigest"])
    ordinary_result = ordinary_response["result"]
    require(
        ordinary_result["status"] == "accepted_by_provider"
        and ordinary_result["providerMessageId"] == ordinary_row["provider_message_id"]
    )
    require(
        ordinary_result["attemptId"] == ordinary_request["attemptId"]
        and ordinary_result["requestDigest"] == ordinary_row["request_digest"]
    )
    idem_request, idem_response = relay_record(
        one(unknown["relay"], "path", "/v1/idempotent-sms/send")
    )
    idem_attempt = unknown["idempotent"]["attempts"][0]
    idem_key = idem_request["operation"]["providerOperationKey"]
    require(idem_key == idem_attempt["request"]["providerOperationKey"])
    idem_row = one(final[external]["idempotent_sms_receipts"], "provider_operation_key", idem_key)
    idem_operation = one(final[inbox]["send_operations"], "provider_operation_key", idem_key)
    require(exact(decode(idem_row["canonical_operation"].encode()), idem_request["operation"]))
    require(idem_row["canonical_operation"] == idem_operation["canonical_operation"])
    require(
        idem_request["operationDigest"]
        == idem_row["operation_digest"]
        == idem_operation["operation_digest"]
    )
    idem_result = idem_response["result"]
    require(
        idem_result["status"] == "accepted_by_provider"
        and idem_result["providerMessageId"] == idem_row["provider_message_id"]
    )
    require(
        idem_result["attemptId"] == idem_attempt["request"]["attemptId"]
        and idem_result["requestDigest"] == idem_attempt["requestDigest"]
    )
    delivery = proofs["starter-delivery.json"]
    zero_provider_calls(delivery["providerCalls"])
    require(exact(delivery["recoveries"], delivery["replayedRecoveries"]))
    require(len(delivery["recoveries"]) == 3 and len(delivery["callbacks"]) == 3)
    require(exact(delivery["callbacks"][0], delivery["callbacks"][2]))
    require(delivery["callbackFacts"]["evidence"]["strongestReported"] == "delivered")
    require(len(delivery["callbackFacts"]["observations"]) == 2)
    for item in delivery["callbackFacts"]["observations"]:
        row = one(final[inbox]["callback_observations"], "event_id", item["observation"]["eventId"])
        require(
            row["receipt_id"] == item["receipt"]["receiptId"]
            and row["payload_digest"] == item["receipt"]["payloadDigest"]
        )
        require(row["attempt_id"] == item["observation"]["attemptId"])
        require(exact(decode(row["canonical_payload"].encode()), item["observation"]))
        require(item["observation"]["providerMessageId"] == ordinary_row["provider_message_id"])
        require(
            item["observation"]["attemptId"] == ordinary_request["attemptId"]
            and item["observation"]["providerOperationKey"]
            == ordinary_request["providerOperationKey"]
            and item["observation"]["requestDigest"] == ordinary_row["request_digest"]
        )
        require(
            hashlib.sha256(row["canonical_payload"].encode()).hexdigest() == row["payload_digest"]
        )
        require(
            row["tenant_id"] == provider["tenantId"]
            and row["provider_account_id"] == provider["providerAccountId"]
        )

    for index, kind in enumerate(("ordinary", "idempotent")):
        observation = delivery[kind]
        outbound = ids["outbound"][kind]
        require(
            observation["receipt"]["outboundId"] == outbound and len(observation["attempts"]) == 1
        )
        attempt = observation["attempts"][0]
        sql_attempt = one(final[inbox]["send_attempts"], "outbound_id", outbound)
        require(attempt["request"]["attemptId"] == sql_attempt["attempt_id"])
        require(attempt["requestDigest"] == sql_attempt["request_digest"])
        require(exact(decode(sql_attempt["canonical_request"].encode()), attempt["request"]))
        require(
            hashlib.sha256(sql_attempt["canonical_request"].encode()).hexdigest()
            == sql_attempt["request_digest"]
        )
        unknown_observation = unknown[kind]
        require(
            unknown_observation["state"] == "unknown" and len(unknown_observation["attempts"]) == 1
        )
        require(observation["state"] == "unknown" and attempt["result"] is None)
    idempotent_attempt = delivery["idempotent"]["attempts"][0]["request"]
    provider_key = idempotent_attempt["providerOperationKey"]
    accepted = one(
        final[external]["idempotent_sms_receipts"], "provider_operation_key", provider_key
    )
    operation = one(final[inbox]["send_operations"], "provider_operation_key", provider_key)
    lookup = one(
        delivery["recoveries"],
        "receipt",
        one(
            [r["receipt"] for r in delivery["recoveries"]],
            "commandId",
            ids["recovery"]["idempotent"],
        ),
    )
    observation = lookup["observation"]
    require(
        type(observation) is dict
        and observation["source"] == "lookup"
        and observation["state"] == "accepted_by_provider"
    )
    require(observation["providerMessageId"] == accepted["provider_message_id"])
    require(
        observation["providerOperationKey"] == provider_key
        and observation["operationDigest"]
        == accepted["operation_digest"]
        == operation["operation_digest"]
    )
    require(
        lookup["receipt"]["providerOperationKey"] == provider_key
        and lookup["receipt"]["operationDigest"] == operation["operation_digest"]
    )
    for command_id in ids["recovery"].values():
        public = one(
            delivery["recoveries"],
            "receipt",
            one([r["receipt"] for r in delivery["recoveries"]], "commandId", command_id),
        )
        sql_command = one(final[inbox]["send_recovery_commands"], "command_id", command_id)
        require(exact(public["receipt"], decode(sql_command["receipt_json"].encode())))
        require(
            hashlib.sha256(sql_command["receipt_json"].encode()).hexdigest()
            == sql_command["receipt_digest"]
        )
        require(
            hashlib.sha256(sql_command["canonical_command"].encode()).hexdigest()
            == sql_command["command_digest"]
        )
        require(
            sql_command["tenant_id"] == scope["tenantId"]
            and sql_command["account_id"] == scope["accountId"]
        )
        observations = [
            r for r in final[inbox]["send_recovery_observations"] if r["command_id"] == command_id
        ]
        if public["observation"] is None:
            require(not observations)
        else:
            require(len(observations) == 1)
            raw = observations[0]["canonical_observation"].encode()
            require(
                hashlib.sha256(raw).hexdigest() == observations[0]["observation_digest"]
                and exact(decode(raw), public["observation"])
            )
    cap = proofs["starter-capacity.json"]
    require(
        len(cap["investigation"]["rows"]) == 11
        and len(cap["idempotent"]["rows"]) == 15
        and len(cap["ordinary"]["rows"]) == 13
    )
    for kind in ("investigation", "idempotent"):
        require(
            cap[kind]["conflict"]["code"] == "IdentityConflict"
            and cap[kind]["overloaded"]["code"] == "Overloaded"
        )
    require(cap["ordinary"]["overloaded"]["code"] == "Overloaded")
    for n, item in enumerate(cap["investigation"]["rows"]):
        prepared = item["prepared"]
        require(prepared["submission"]["operationKey"] == ids["probes"]["investigations"][n])
        row = one(
            final[external]["investigation_receipts"],
            "operation_key",
            ids["probes"]["investigations"][n],
        )
        require(
            row["canonical_payload"] == prepared["canonicalPayload"]
            and row["payload_digest"] == prepared["payloadDigest"]
            and row["receipt_id"] == item["receipt"]["receiptId"]
        )
        if n in (0, 1):
            require(prepared["submission"]["message"]["body"] == ("\x00" * 4096 if n == 0 else ""))
    physical = cap["ordinaryPhysicalProbe"]
    for k, v in ids["probes"]["ordinaryPhysical"].items():
        require(physical["request"][k] == v)
    require(
        len(physical["results"]) == 2
        and physical["results"][0]["providerMessageId"]
        != physical["results"][1]["providerMessageId"]
    )
    actual_physical = [
        r
        for r in final[external]["ordinary_sms_attempts"]
        if r["attempt_id"] == physical["request"]["attemptId"]
    ]
    require(len(actual_physical) == 2)
    require(
        {r["provider_message_id"] for r in actual_physical}
        == {r["providerMessageId"] for r in physical["results"]}
    )
    return {
        "schemaVersion": 1,
        "owner": owner,
        "originalReceipts": receipts,
        "logicalOperationKeys": sorted(operation_keys),
        "tables": snapshot_counts(final, owner),
        "ownedSigkills": 1,
        "newOriginalRecoveryHttpCalls": 0,
        "restoreEqual": True,
        "freshReadsEqual": True,
        "ordinaryResend": False,
    }


def source_snapshot(root: Path) -> dict[str, str]:
    project = root / "projects/channel-continuity"
    paths: set[Path] = set()
    for directory in ("src", "examples"):
        paths.update((project / directory).rglob("*.ts"))
    paths.update(
        project / name
        for name in (
            "package.json",
            "README.md",
            "STARTER.md",
            "starter/bounded-v1.json",
            "tsconfig.json",
            "tsconfig.examples.json",
            "tsconfig.starter.json",
        )
    )
    paths.update(
        project / "tests/fixtures" / name
        for name in ("installed-starter-consumer.ts", "starter-p1-consumer.ts")
    )
    for name in (
        "p2_standalone_check.py",
        "p2_native_check.py",
        "p3_coordinator_check.py",
        "p3_document_package.py",
        "p3_document_evidence.py",
        "p3_package_check.py",
    ):
        paths.add(root / "local-setup/scripts" / name)
    paths.update(
        root / name
        for name in (
            "local-setup/stack.py",
            "harness/process_control.py",
            "pnpm-lock.yaml",
            "package.json",
        )
    )
    result = {}
    for path in sorted(paths):
        require(not path.is_symlink() and path.is_file() and path.resolve().is_relative_to(root))
        result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def make_configuration(owner: str, port: int) -> dict[str, Any]:
    import socket

    def free_port() -> int:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1])

    external = free_port()
    gateway = free_port()
    while external == gateway:
        gateway = free_port()
    return {
        "schemaVersion": 1,
        "profileId": str(UUID(owner)),
        "postgres": {"host": "127.0.0.1", "port": port, "database": "livekit_lab"},
        "schemas": dict(zip(("inbox", "case", "external"), schema_tables(owner), strict=True)),
        "bindings": [
            {
                "alias": "primary",
                "providerScope": {
                    "tenantId": "tenant_starter",
                    "provider": "fake_sms",
                    "providerAccountId": "provider_" + owner,
                },
                "accountScope": {"tenantId": "tenant_starter", "accountId": "account_" + owner},
                "caseId": "case_" + owner,
                "conversationId": "conversation_" + owner,
                "senderId": "sender_" + owner,
                "initialCase": {
                    "revision": "0",
                    "request": {
                        "schemaVersion": 1,
                        "kind": "booking_investigation",
                        "bookingReference": "DEMO-BK-001",
                        "newCheckIn": "2030-12-02",
                        "investigationConsent": True,
                    },
                },
            }
        ],
        "endpoints": {"external": external, "gateway": gateway},
        "limits": {"maxInbox": 64, "externalReceipts": 16},
    }


def make_credentials(config: dict[str, Any], settings: dict[str, str]) -> dict[str, dict[str, Any]]:
    import secrets

    profile = config["profileId"]
    bearer = {
        "alias": "primary",
        **{k: secrets.token_urlsafe(32) for k in ("operation", "ordinary", "idempotent")},
    }
    common = {"schemaVersion": 1, "profileId": profile}
    return {
        "owner": {
            **common,
            "role": "owner",
            "postgresPassword": settings["POSTGRES_MIGRATION_PASSWORD"],
        },
        "external": {
            **common,
            "role": "external",
            "postgresPassword": settings["POSTGRES_PASSWORD"],
            "bearers": [bearer],
        },
        "runtime": {
            **common,
            "role": "runtime",
            "postgresPassword": settings["POSTGRES_PASSWORD"],
            "bindings": [
                {
                    "alias": "primary",
                    **{
                        k: secrets.token_urlsafe(32)
                        for k in ("accountToken", "publisherToken", "recoveryToken")
                    },
                }
            ],
            "providerHmac": secrets.token_urlsafe(32),
            "callbackHmac": secrets.token_urlsafe(32),
            "externalBearers": [bearer],
        },
    }


def credential_sentinels(credentials: dict[str, Any]) -> tuple[bytes, ...]:
    result: set[bytes] = set()

    def visit(value: Any, key: str = "") -> None:
        if type(value) is dict:
            for name, item in value.items():
                visit(item, name)
        elif type(value) is list:
            for item in value:
                visit(item, key)
        elif type(value) is str and (
            key.endswith(("Token", "Hmac"))
            or key in {"postgresPassword", "operation", "ordinary", "idempotent"}
        ):
            result.add(value.encode())

    visit(credentials)
    return tuple(sorted(result))


async def wait_file(
    path: Path, child: OwnedProcess, deadline: float, *, maximum: int = MAX_PROOF_BYTES
) -> bytes:
    while True:
        remaining(deadline)
        if path.exists() or path.is_symlink():
            # Only ready JSON has a documented exact `.publishing` hardlink transition.
            info = path.lstat()
            if info.st_nlink == 2:
                pending = path.with_name(path.name + ".publishing")
                try:
                    other = pending.lstat()
                except FileNotFoundError:
                    if path.lstat().st_nlink != 1:
                        raise GateError("unsafe_path") from None
                else:
                    require(
                        stat.S_ISREG(info.st_mode)
                        and not pending.is_symlink()
                        and info.st_uid == other.st_uid == os.getuid()
                        and stat.S_IMODE(info.st_mode) == stat.S_IMODE(other.st_mode) == 0o600
                        and (info.st_dev, info.st_ino) == (other.st_dev, other.st_ino)
                    )
                    await asyncio.sleep(0.005)
                    continue
            return bounded_read(path, maximum)
        if child.returncode is not None:
            raise GateError("child_failed")
        await asyncio.sleep(0.01)


def validate_cli(raw: bytes, command: str) -> dict[str, Any]:
    value = decode(raw, 2048)
    shape(
        value,
        {"schemaVersion", "command", "requestId", "status", "code", "result", "cleanupComplete"},
    )
    require(
        exact(value["schemaVersion"], 1)
        and value["command"] == command
        and uuid4_string(value["requestId"])
    )
    require(
        value["status"] == "known" and value["code"] == "ok" and value["cleanupComplete"] is True
    )
    return value


def validate_closed_metrics(value: dict[str, Any], kind: str) -> None:
    metrics = value["metrics"]
    if kind == "gateway":
        require(
            exact(
                metrics["application"],
                {"commandsActive": 0, "retainedGraphs": 0, "gatewayActive": False, "closing": True},
            )
        )
        gateway = metrics["gateway"]
        require(type(gateway) is dict)
        for key in ("active", "intakes", "sockets", "handlers", "observerPending"):
            require(exact(gateway[key], 0))
        # The gateway's finally clears #loop, and close awaits that settlement.
        require(exact(gateway["driver"], 0))
    else:
        require(type(metrics) is dict)
        for key in ("active", "sockets"):
            require(exact(metrics["external"][key], 0))
        require(exact(metrics["external"]["profileReads"], 5))


def retain_terminal(
    source: Path, destination: Path, kind: str, sentinels: tuple[bytes, ...]
) -> dict[str, Any]:
    raw = bounded_read(source, 65536)
    scan_secrets(raw, sentinels)
    write_private(destination, raw, 65536)
    terminal = decode(raw, 65536)
    validate_closed_metrics(terminal, kind)
    return terminal


def validate_pg_environment() -> None:
    if any(os.environ.get(key) for key in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE")):
        raise GateError("invalid_environment")


def backup_restore_commands(
    docker: str, container: str, owner: str, source: Path, expected: bytes
) -> tuple[list[str], list[str], dict[str, Any]]:
    """Validate host bytes separately from the pinned container dump owner."""
    require(re.fullmatch("[a-f0-9]{12,64}", container) is not None)
    require(re.fullmatch("[a-f0-9]{32}", owner) is not None)
    before = source.lstat()
    require(bounded_read(source, 8 * 1024 * 1024) == expected)
    after = source.lstat()
    require(
        (before.st_dev, before.st_ino, before.st_uid, before.st_gid)
        == (after.st_dev, after.st_ino, after.st_uid, after.st_gid)
    )
    identity: dict[str, Any] = {
        "hostUid": after.st_uid,
        "hostGid": after.st_gid,
        "containerUid": 999,
        "containerGid": 999,
        "mode": "0600",
        "links": 1,
        "bytes": len(expected),
        "sha256": hashlib.sha256(expected).hexdigest(),
    }
    backup = "/tmp/p2-starter-" + owner + ".sql"
    # Compose pins PostgreSQL to 999:999. On the selected Docker engine,
    # archive copying over its existing dump preserves that destination owner;
    # it does not change ownership to match the separately validated host file.
    metadata = f"999:999:600:1:{len(expected)}"
    # UUID-only path and decimal/hash fields are generated by this owner, never
    # shell fragments supplied by a caller. A failed guard retains the file.
    script = (
        "test -f "
        + backup
        + " && test ! -L "
        + backup
        + " && test \"$(stat -c '%u:%g:%a:%h:%s' -- "
        + backup
        + ")\" = '"
        + metadata
        + "'"
        + ' && test "$(sha256sum -- '
        + backup
        + ")\" = '"
        + identity["sha256"]
        + "  "
        + backup
        + "'"
        + " || exit 91; "
        + "psql -X --quiet --set ON_ERROR_STOP=1 --single-transaction --host=127.0.0.1 --username=continuity_migrator --dbname=livekit_lab --file="
        + backup
        + "; result=$?; rm -- "
        + backup
        + '; removed=$?; if [ "$result" -ne 0 ]; then exit "$result"; fi; exit "$removed"'
    )
    return (
        [docker, "cp", "--archive", str(source), container + ":" + backup],
        [
            docker,
            "exec",
            "--user",
            "999:999",
            "-e",
            "PGPASSWORD",
            container,
            "/bin/sh",
            "-c",
            script,
        ],
        identity,
    )


async def run(
    root: Path, artifacts: Path, started: float, cleanup: dict[str, bool]
) -> dict[str, Any]:
    import signal
    import tempfile
    from uuid import uuid4

    import p3_coordinator_check as core
    import psycopg
    from psycopg import sql

    from harness.process_control import FileBarrier

    validate_pg_environment()
    final = started + TOTAL_SECONDS
    deadline = final - CLEANUP_SECONDS
    frozen = source_snapshot(root)
    write_private(artifacts / "source-before.json", json_bytes(frozen))
    setup = core.load_setup(root)
    settings = setup.load_settings()
    owner = uuid4().hex
    work = Path(tempfile.mkdtemp(prefix="phase41-p2-starter-", dir="/private/tmp")).resolve()
    work.chmod(0o700)
    commands = work / "commands"
    commands.mkdir(mode=0o700)
    marker = {"schemaVersion": 1, "owner": owner, "schemas": list(schema_tables(owner))}
    write_private(work / "owned-work.json", json_bytes(marker))
    children = Children(
        commands, deadline, final, roles=frozenset((*NORMAL_ROLES, "backup-cleanup"))
    )
    actual = ActualCalls()
    config = make_configuration(owner, int(settings["POSTGRES_PORT"]))
    credentials = make_credentials(config, settings)
    sentinels = credential_sentinels(credentials)
    for role, value in credentials.items():
        write_private(work / (role + "-credentials.json"), json_bytes(value), 16384)
    write_private(work / "config.json", json_bytes(config), 16384)
    write_private(work / "ids.json", json_bytes(fixed_ids(owner)), 16384)
    snapshots: dict[str, Any] = {}
    proofs: dict[str, dict[str, Any]] = {}
    attempted = False
    first: BaseException | None = None
    container: str | None = None
    backup = "/tmp/p2-starter-" + owner + ".sql"
    backup_possible = False
    dump_complete = False
    restore_started = False
    package: dict[str, Any] | None = None
    join: dict[str, Any] | None = None

    def connect(runtime: bool = False) -> Any:
        validate_pg_environment()
        return psycopg.connect(
            host="127.0.0.1",
            port=int(settings["POSTGRES_PORT"]),
            dbname="livekit_lab",
            user="livekit_lab" if runtime else "continuity_migrator",
            password=settings["POSTGRES_PASSWORD" if runtime else "POSTGRES_MIGRATION_PASSWORD"],
            connect_timeout=2,
            sslmode="disable",
            gssencmode="disable",
            target_session_attrs="read-write",
            client_encoding="UTF8",
            options="-c statement_timeout=5000 -c lock_timeout=2000",
        )

    def drop_schemas() -> None:
        with closing(connect()) as connection:
            for schema in schema_tables(owner):
                row = connection.execute(
                    "SELECT pg_get_userbyid(nspowner),obj_description(oid,'pg_namespace') FROM pg_namespace WHERE nspname=%s",
                    [schema],
                ).fetchone()
                if row is not None:
                    require(
                        row
                        == (
                            "continuity_migrator",
                            {
                                "inbox": "p2-channel-schema-v7",
                                "case": "p2-reference-case-v1",
                                "external": "p2-starter-external-v1:" + config["profileId"],
                            }[next(k for k, v in config["schemas"].items() if v == schema)],
                        )
                    )
                    connection.execute(
                        sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
                    )
            connection.commit()

    def cleanup_storage() -> None:
        if backup_possible:
            # A failed/abandoned container mutation is not evidence of completion.
            require(dump_complete and not restore_started and children.all_settled())
            with closing(connect()) as connection:
                require(
                    connection.execute(
                        "SELECT count(*) FROM pg_stat_activity WHERE pid<>pg_backend_pid() AND datname='livekit_lab' AND usename='continuity_migrator' AND application_name IN ('pg_dump','psql')"
                    ).fetchone()[0]
                    == 0
                )
            children.deadline = final
            assert container is not None
            child = children.start(
                "backup-cleanup",
                [
                    str(tool("docker")),
                    "exec",
                    container,
                    "/bin/sh",
                    "-c",
                    "test -f " + backup + " && test ! -L " + backup + " && rm -- " + backup,
                ],
                {k: v for k, v in os.environ.items() if k in BASE_KEYS},
                cwd=work,
            )
            children.finish(child, secrets=sentinels)
        drop_schemas()

    async def capture(phase: str) -> None:
        require(phase in SNAPSHOT_PHASES and phase not in snapshots)
        snapshots[phase] = await actual.call(owner_snapshot, connect, owner, deadline=deadline)
        raw = json.dumps(
            snapshots[phase],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode()
        write_private(work / ("starter-sql-" + phase + ".json"), raw)

    async def finish(child: OwnedProcess, *, accepted: tuple[int, ...] = (0,)) -> bytes:
        return await actual.call(children.finish, child, accepted_codes=accepted, secrets=sentinels)

    async def stop(child: OwnedProcess, kind: str, output: Path) -> None:
        require(child.returncode is None)
        os.kill(child.pid, signal.SIGTERM)
        validate_cli(await finish(child), "serve" if kind == "gateway" else "external")
        retain_terminal(output, artifacts / output.name, kind, sentinels)

    async def retain_proof(name: str) -> dict[str, Any]:
        raw = bounded_read(work / name)
        scan_secrets(raw, sentinels)
        value = validate_proof(raw, name, owner)
        write_private(artifacts / name, raw)
        proofs[name] = value
        return value

    def actor(mode: str) -> OwnedProcess:
        assert package is not None
        env = {
            **{k: v for k, v in os.environ.items() if k in BASE_KEYS},
            "P2_STARTER_MODE": mode,
            "P2_STARTER_WORK": str(work),
            "P2_STARTER_OWNER": owner,
            "P2_STARTER_CONFIG": str(work / "config.json"),
            "P2_STARTER_CREDENTIALS": str(work / "runtime-credentials.json"),
            "P2_STARTER_IDS": str(work / "ids.json"),
            "P2_STARTER_OUTPUT": str(work / ("stage-" + mode + ".json")),
        }
        if mode == "restore-verify":
            env["P2_STARTER_EXTERNAL_CREDENTIALS"] = str(work / "external-credentials.json")
        validate_environment(env, required=frozenset(k for k in env if k.startswith("P2_STARTER_")))
        return children.start(
            mode,
            [str(package["node"]), str(package["consumer"] / "dist/consumer.js")],
            env,
            cwd=package["consumer"],
        )

    async def stage(mode: str) -> None:
        child = actor(mode)
        validate_actor_stage(await finish(child), mode)
        raw = bounded_read(work / ("stage-" + mode + ".json"))
        scan_secrets(raw, sentinels)
        write_private(artifacts / ("stage-" + mode + ".json"), raw)

    def cli(
        role: str,
        command: str,
        credential_role: str,
        *,
        ready: bool = False,
        input_path: Path | None = None,
    ) -> OwnedProcess:
        assert package is not None
        executable = package["consumer"] / "node_modules/.bin/p2-channel-starter"
        require(executable.is_file() and executable.resolve().is_relative_to(package["consumer"]))
        argv = [
            str(executable),
            command,
            "--config",
            str(work / "config.json"),
            "--credentials",
            str(work / (credential_role + "-credentials.json")),
            "--output",
            str(work / ("terminal-" + role + ".json")),
            "--failure",
            str(work / ("failure-" + role + ".json")),
        ]
        if ready:
            argv += ["--ready", str(work / ("ready-" + role + ".json"))]
        if input_path is not None:
            argv += ["--input", str(input_path)]
        env = {k: v for k, v in os.environ.items() if k in BASE_KEYS}
        validate_environment(env, required=frozenset())
        return children.start(role, argv, env, cwd=package["consumer"])

    try:
        package = await actual.call(prepare_installed, root, work, artifacts, children)
        plan_child = children.start(
            "plan",
            [str(package["consumer"] / "node_modules/.bin/p2-channel-starter"), "plan"],
            {k: v for k, v in os.environ.items() if k in BASE_KEYS},
            cwd=package["consumer"],
        )
        pure = decode(await finish(plan_child), 2048)
        require(
            pure["schemaVersion"] == 1
            and pure["command"] == "plan"
            and pure["status"] == "not_started"
            and pure["setupStarted"] is False
            and pure["providersInvoked"] is False
        )
        require(exact(pure["groups"], list(CASE_NAMES)))
        manifest = (root / "projects/channel-continuity/starter/bounded-v1.json").read_bytes()
        require(pure["manifestSha256"] == hashlib.sha256(manifest).hexdigest())
        write_private(artifacts / "bin-plan.json", json_bytes(pure))
        await stage("config-negative")
        attempted = True
        validate_cli(await finish(cli("bootstrap", "bootstrap", "owner")), "bootstrap")
        bootstrap = decode(bounded_read(work / "terminal-bootstrap.json", 65536), 65536)
        require(exact(bootstrap, {"inboxVersion": 7, "caseVersion": 1, "externalVersion": 1}))
        write_private(artifacts / "bin-bootstrap.json", json_bytes(bootstrap))
        permission = await actual.call(
            runtime_permission_proof, lambda: connect(True), connect, owner, deadline=deadline
        )
        write_private(artifacts / "starter-runtime-permissions.json", json_bytes(permission))
        await stage("setup")
        await retain_proof("starter-setup.json")
        await capture("setup")
        external_child = cli("external", "external", "external", ready=True)
        validate_ready(
            await wait_file(work / "ready-external.json", external_child, deadline, maximum=512),
            owner=owner,
            process_id=external_child.pid,
            kind="external",
        )
        normal = cli("serve-normal", "serve", "runtime", ready=True)
        validate_ready(
            await wait_file(work / "ready-serve-normal.json", normal, deadline, maximum=512),
            owner=owner,
            process_id=normal.pid,
            kind="gateway",
        )
        await stage("baseline-client")
        await retain_proof("starter-baseline.json")
        await stop(normal, "gateway", work / "terminal-serve-normal.json")
        await capture("baseline")
        barriers = {
            stem: FileBarrier(work, stem)
            for stem in (
                "starter_gateway_a_ready",
                "starter_ack_flushed",
                "starter_external_committed",
                "starter_external_unknown",
            )
        }
        gateway_a = actor("gateway-a")
        await actual.call(
            gateway_a.wait_for_barrier,
            barriers["starter_gateway_a_ready"],
            timeout=min(15, remaining(deadline)),
        )
        validate_ready(
            await wait_file(
                work / "starter-gateway-a-ready.json", gateway_a, deadline, maximum=512
            ),
            owner=owner,
            process_id=gateway_a.pid,
            kind="gateway",
        )
        await stage("ack-client")
        await retain_proof("starter-ack.json")
        await actual.call(
            gateway_a.wait_for_barrier,
            barriers["starter_ack_flushed"],
            timeout=min(15, remaining(deadline)),
        )
        await capture("ack-before-kill")
        k_receipt = proofs["starter-ack.json"]["receipt"]["receiptId"]
        k_intent = one(
            snapshots["ack-before-kill"][config["schemas"]["inbox"]]["processing_intents"],
            "receipt_id",
            k_receipt,
        )
        require(
            k_intent["state"] == "pending"
            and k_intent["possible_external"] is False
            and exact(k_intent["attempt_count"], 0)
        )
        require(
            not any(
                r["receipt_id"] == k_receipt
                for r in snapshots["ack-before-kill"][config["schemas"]["inbox"]]["dispatch_plans"]
            )
        )
        termination = await actual.call(gateway_a.kill, timeout=min(5, remaining(deadline)))
        require(termination.killed and termination.returncode == -signal.SIGKILL)
        children.capture(gateway_a, secrets=sentinels)
        gateway_a.close()
        require(settled(gateway_a))
        write_private(
            artifacts / "owned-kill.json",
            json_bytes(
                {
                    "schemaVersion": 1,
                    "owner": owner,
                    "role": "gateway-a",
                    "pid": gateway_a.pid,
                    "httpStatus": 200,
                    "returncode": termination.returncode,
                    "killed": True,
                    "groupSettled": True,
                }
            ),
        )
        await stage("before-restart")
        await retain_proof("starter-before-restart.json")
        gateway_b = cli("serve-b", "serve", "runtime", ready=True)
        validate_ready(
            await wait_file(work / "ready-serve-b.json", gateway_b, deadline, maximum=512),
            owner=owner,
            process_id=gateway_b.pid,
            kind="gateway",
        )
        await stage("later-input")
        await retain_proof("starter-recovered.json")
        await stop(gateway_b, "gateway", work / "terminal-serve-b.json")
        delivery = actor("delivery-begin")
        for stem, phase, name in (
            ("starter_external_committed", "external-committed", "starter-external-held.json"),
            ("starter_external_unknown", "external-unknown", "starter-unknown.json"),
        ):
            await actual.call(
                delivery.wait_for_barrier, barriers[stem], timeout=min(30, remaining(deadline))
            )
            await retain_proof(name)
            await capture(phase)
            delivery.release_barrier(barriers[stem])
        validate_actor_stage(await finish(delivery), "delivery-begin")
        await stage("delivery-recovery")
        for name in ("starter-delivery.json", "starter-capacity.json", "starter-original.json"):
            await retain_proof(name)
        await capture("recovered")
        input_path = work / "history-input.json"
        write_private(
            input_path, json_bytes({"bindingAlias": "primary", "after": "0", "limit": 8}), 16384
        )
        validate_cli(
            await finish(cli("history", "history", "runtime", input_path=input_path)), "history"
        )
        history = decode(bounded_read(work / "terminal-history.json", 65536), 65536)
        require(exact(history["messages"], proofs["starter-original.json"]["messages"]))
        write_private(artifacts / "bin-history.json", json_bytes(history), 65536)
        await capture("before-fresh")
        await stage("fresh-verify")
        await retain_proof("starter-fresh.json")
        await capture("after-fresh")
        await stop(external_child, "external", work / "terminal-external.json")
        await capture("before-restore")
        docker = str(tool("docker"))
        base = {k: v for k, v in os.environ.items() if k in BASE_KEYS}

        async def command(name: str, argv: list[str], env: dict[str, str] | None = None) -> bytes:
            return await finish(children.start(name, argv, base if env is None else env, cwd=work))

        container = (
            (
                await command(
                    "docker-discovery",
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
                )
            )
            .decode()
            .strip()
        )
        require(re.fullmatch("[a-f0-9]{12,64}", container) is not None)
        pg_env = {**base, "PGPASSWORD": settings["POSTGRES_MIGRATION_PASSWORD"]}
        backup_possible = True
        await command(
            "dump",
            [
                docker,
                "exec",
                "-e",
                "PGPASSWORD",
                container,
                "/bin/sh",
                "-c",
                "umask 077; exec pg_dump --host=127.0.0.1 --username=continuity_migrator --dbname=livekit_lab "
                + " ".join("--schema=" + s for s in schema_tables(owner))
                + " --inserts --no-owner --file="
                + backup,
            ],
            pg_env,
        )
        dump_complete = True
        await command(
            "copy-out", [docker, "cp", container + ":" + backup, str(work / "populated.sql")]
        )
        os.chmod(work / "populated.sql", 0o600)
        dump = bounded_read(work / "populated.sql", 8 * 1024 * 1024)
        scan_secrets(dump, sentinels)
        write_private(artifacts / "populated.sql", dump, 8 * 1024 * 1024)
        await actual.call(drop_schemas)
        copy_argv, restore_argv, backup_identity = backup_restore_commands(
            docker, container, owner, work / "populated.sql", dump
        )
        write_private(artifacts / "backup-file.json", json_bytes(backup_identity))
        await command("copy-in", copy_argv)
        restore_started = True
        await command("restore", restore_argv, pg_env)
        backup_possible = False
        await stage("restore-verify")
        await retain_proof("starter-restored.json")
        await capture("after-restore")
        join = validate_owner_joins(proofs, snapshots, config, owner)
        write_snapshots(artifacts, snapshots, owner)
        require(
            exact(
                read_snapshots(
                    artifacts, bounded_read(artifacts / "starter-sql-snapshots.json"), owner
                )[1],
                snapshots,
            )
        )
        write_private(artifacts / "independent-owner-joins.json", json_bytes(join))
    except BaseException as error:  # noqa: BLE001 - Preserve primary while actual independent owners settle.
        first = error
    finally:
        complete = await cleanup_dependencies(
            children, actual, final, cleanup_storage if attempted else None
        )
        retained = True
        try:
            for child in children.children:
                if child.returncode is not None:
                    streams = children.capture(child, secrets=sentinels)
                    directory = artifacts / "commands" / child.output_directory.name
                    directory.parent.mkdir(mode=0o700, exist_ok=True)
                    directory.mkdir(mode=0o700)
                    for stream, raw in zip(("stdout", "stderr"), streams, strict=True):
                        write_private(directory / (stream + ".bin"), raw, MAX_STREAM_BYTES)
            for path in [*work.glob("stage-*.json"), *work.glob("starter-sql-*.json")]:
                if path.name not in {p.name for p in artifacts.iterdir()}:
                    raw = bounded_read(path)
                    scan_secrets(raw, sentinels)
                    value = decode(raw)
                    if value.get("status") == "failed":
                        validate_actor_failure(raw, value["mode"])
                    write_private(artifacts / path.name, raw)
            write_private(
                artifacts / "owned-children.json",
                json_bytes(
                    {
                        "schemaVersion": 1,
                        "owner": owner,
                        "commands": [
                            {
                                "role": c.output_directory.name,
                                "pid": c.pid,
                                "returncode": c.returncode,
                                "cleanupFailed": c.cleanup_failed,
                                "groupSettled": getattr(c, "group_settled", False),
                            }
                            for c in children.children
                        ],
                        "allSettled": children.all_settled(),
                        "actualThreads": len(actual.tasks),
                    }
                ),
            )
        except BaseException:  # noqa: BLE001 - Retention failure must not skip remaining cleanup.
            retained = False
        cleanup["cleanup_complete"] = complete and retained
        if cleanup["cleanup_complete"]:
            try:
                require(exact(decode(bounded_read(work / "owned-work.json")), marker))
                private_directory(work)
                for value in retained_inventory(artifacts)["files"]:
                    scan_secrets(
                        bounded_read(artifacts / value, MAX_EVIDENCE_BYTES, allow_empty=True),
                        sentinels,
                    )
                shutil.rmtree(work)
            except BaseException as error:  # noqa: BLE001 - Preserve primary while actual independent owners settle.
                cleanup["cleanup_complete"] = False
                first = first or error
        if not cleanup["cleanup_complete"]:
            try:
                write_private(
                    artifacts / "owned-work-retained.json",
                    json_bytes(
                        {
                            "schemaVersion": 1,
                            "owner": owner,
                            "path": str(work),
                            "schemas": list(schema_tables(owner)),
                            "cleanupComplete": False,
                        }
                    ),
                )
            except BaseException:  # noqa: BLE001 - Preserve primary and retained unknown work.
                cleanup["cleanup_complete"] = False
            first = first or GateError("cleanup_incomplete")
    if first is not None:
        raise first
    if package is None or join is None:
        raise GateError("invalid_proof")
    after = source_snapshot(root)
    write_private(artifacts / "source-after.json", json_bytes(after))
    require(exact(frozen, after))
    require([c.output_directory.name for c in children.children] == list(NORMAL_ROLES))
    index = retained_inventory(artifacts)
    write_private(artifacts / "retained-index.json", json_bytes(index))
    validate_retained_index(artifacts, json_bytes(index))
    return {
        "schema_version": 1,
        "status": "passed",
        "mode": MODE,
        "tests": 20,
        "passed": 20,
        "cases": list(CASE_NAMES),
        "child_commands": children.count,
        "owned_sigkills": 1,
        "logical_investigations": 5,
        "synthetic_carrier_acceptances": 32,
        "callback_offers": 3,
        "callback_observations": 2,
        "recovery_commands": 3,
        "archive_payloads": len(package["payloads"]),
        "cleanup_complete": True,
        "duration_seconds": time.monotonic() - started,
        "retained_index_sha256": hashlib.sha256(json_bytes(index)).hexdigest(),
        "proofs": {
            name: {
                "bytes": len(bounded_read(artifacts / name)),
                "sha256": hashlib.sha256(bounded_read(artifacts / name)).hexdigest(),
            }
            for name in (
                *PROOF_KEYS,
                "starter-runtime-permissions.json",
                "starter-sql-snapshots.json",
                "independent-owner-joins.json",
                "owned-kill.json",
            )
        },
    }


def validated_report(raw: bytes) -> dict[str, Any]:
    value = decode(raw, MAX_REPORT_BYTES)
    keys = {
        "schema_version",
        "status",
        "mode",
        "tests",
        "passed",
        "cases",
        "child_commands",
        "owned_sigkills",
        "logical_investigations",
        "synthetic_carrier_acceptances",
        "callback_offers",
        "callback_observations",
        "recovery_commands",
        "archive_payloads",
        "cleanup_complete",
        "duration_seconds",
        "retained_index_sha256",
        "proofs",
    }
    shape(value, keys)
    require(
        value["status"] == "passed" and value["mode"] == MODE and value["cleanup_complete"] is True
    )
    for name, expected in {
        "schema_version": 1,
        "tests": 20,
        "passed": 20,
        "child_commands": 26,
        "owned_sigkills": 1,
        "logical_investigations": 5,
        "synthetic_carrier_acceptances": 32,
        "callback_offers": 3,
        "callback_observations": 2,
        "recovery_commands": 3,
    }.items():
        require(exact(value[name], expected))
    require(exact(value["cases"], list(CASE_NAMES)))
    require(natural(value["archive_payloads"], 512, 1))
    duration = value["duration_seconds"]
    require(
        type(duration) in (int, float)
        and 0 <= duration <= TOTAL_SECONDS
        and math.isfinite(duration)
    )
    require(
        type(value["retained_index_sha256"]) is str
        and re.fullmatch("[a-f0-9]{64}", value["retained_index_sha256"]) is not None
    )
    shape(
        value["proofs"],
        {
            *PROOF_KEYS,
            "starter-runtime-permissions.json",
            "starter-sql-snapshots.json",
            "independent-owner-joins.json",
            "owned-kill.json",
        },
    )
    for descriptor in value["proofs"].values():
        shape(descriptor, {"bytes", "sha256"})
        require(
            natural(descriptor["bytes"], MAX_PROOF_BYTES, 1)
            and type(descriptor["sha256"]) is str
            and re.fullmatch("[a-f0-9]{64}", descriptor["sha256"]) is not None
        )
    return value


def plan(*, p1_contract: bool = False) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "not_started",
        "measurement_started": False,
        "mode": "installed_p1_adapter_contract" if p1_contract else MODE,
        "cases": list(P1_CASE_NAMES if p1_contract else CASE_NAMES),
        "bounds": {
            "total_seconds": TOTAL_SECONDS,
            "cleanup_seconds": CLEANUP_SECONDS,
            "maximum_children": MAX_CHILDREN,
            "stream_bytes": MAX_STREAM_BYTES,
            "capture_bytes": MAX_CAPTURE_BYTES,
            "proof_bytes": MAX_PROOF_BYTES,
            "evidence_bytes": MAX_EVIDENCE_BYTES,
            "report_bytes": MAX_REPORT_BYTES,
        },
        "protocol_frozen": True,
    }


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    artifacts: Path | None = None
    target: Path | None = None
    cleanup = {"cleanup_complete": False}
    started = time.monotonic()
    try:
        parser = SafeParser(description=__doc__)
        parser.add_argument("--plan", action="store_true")
        parser.add_argument("--p1-contract", action="store_true")
        parser.add_argument("--report", type=Path)
        args = parser.parse_args(argv)
        if args.plan:
            print(json_bytes(plan(p1_contract=args.p1_contract)).decode())
            return 0
        validate_pg_environment()
        if args.p1_contract:
            import importlib

            p2_starter_p1_check = importlib.import_module("p2_starter_p1_check")

            delegated = [] if args.report is None else ["--report", str(args.report)]
            delegated_result = p2_starter_p1_check.main(delegated, root=root)
            if type(delegated_result) is not int:
                raise GateError("invalid_proof")
            return delegated_result
        target = target_path(
            root, args.report or Path(".local/validation/p2-standalone/" + uuid4().hex + ".json")
        )
        artifacts = target.with_name(target.stem + "-artifacts")
        artifacts.mkdir(mode=0o700)
        result = validated_report(json_bytes(asyncio.run(run(root, artifacts, started, cleanup))))
        write_private(target, json_bytes(result), MAX_REPORT_BYTES)
        print(json_bytes(result).decode())
        return 0
    except BaseException as error:  # noqa: BLE001 - Preserve primary while actual independent owners settle.
        code = error.code if isinstance(error, GateError) else "gate_failed"
        result = {
            "schema_version": 1,
            "status": "failed",
            "mode": MODE,
            "code": code,
            "cleanup_complete": cleanup["cleanup_complete"],
            "duration_seconds": time.monotonic() - started,
        }
        if artifacts is not None:
            try:
                index = retained_inventory(artifacts)
                if not (artifacts / "retained-index.json").exists():
                    write_private(artifacts / "retained-index.json", json_bytes(index))
                result["retained_index_sha256"] = hashlib.sha256(
                    bounded_read(artifacts / "retained-index.json")
                ).hexdigest()
            except BaseException:  # noqa: BLE001 - Retention failure must not skip remaining cleanup.
                result["cleanup_complete"] = False
        if target is not None:
            try:
                write_private(target, json_bytes(result), MAX_REPORT_BYTES)
            except BaseException:  # noqa: BLE001 - Retention failure must not skip remaining cleanup.
                result["cleanup_complete"] = False
        print(json_bytes(result).decode())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
