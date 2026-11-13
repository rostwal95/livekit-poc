"""Explicit, backed-up SQLite migration for the initial inquiry-only subset.

Callers must quiesce application writes for this one-shot operation. A reserved
SQLite writer lock protects the migration snapshot; it does not make an external
process obey the quiescence contract after commit. Serving code calls
require_schema, which never creates or repairs schema/data.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from .models import BookingChange
from .sqlite_admission import CUTOVER_DDL, CUTOVER_SCHEMA_VERSION

SCHEMA_VERSION = 1
_TIMEOUT_SECONDS = 5.0
_MAX_LEGACY_PAYLOAD_BYTES = 2048

TASKS_DDL = """CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY,
    scope_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status = 'queued'),
    created_at TEXT NOT NULL,
    UNIQUE (scope_id, idempotency_key)
)"""

EXECUTIONS_DDL = """CREATE TABLE executions (
    task_id TEXT PRIMARY KEY NOT NULL REFERENCES tasks(task_id),
    operation TEXT NOT NULL CHECK (operation = 'booking.inquire'),
    status TEXT NOT NULL CHECK (status IN ('accepted', 'running', 'succeeded', 'failed')),
    effect_id TEXT NOT NULL UNIQUE,
    version INTEGER NOT NULL CHECK (typeof(version) = 'integer' AND version >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    result_json TEXT,
    error_code TEXT,
    CHECK (
        (status IN ('accepted', 'running') AND result_json IS NULL AND error_code IS NULL)
        OR (status = 'succeeded' AND result_json IS NOT NULL AND error_code IS NULL)
        OR (status = 'failed' AND result_json IS NULL AND error_code IS NOT NULL)
    ),
    CHECK (error_code IS NULL OR (length(error_code) BETWEEN 1 AND 64))
)"""

ATTEMPTS_DDL = """CREATE TABLE execution_attempts (
    attempt_id TEXT PRIMARY KEY NOT NULL,
    task_id TEXT NOT NULL REFERENCES executions(task_id),
    attempt_no INTEGER NOT NULL CHECK (typeof(attempt_no) = 'integer' AND attempt_no >= 1),
    status TEXT NOT NULL CHECK (status IN ('started', 'succeeded', 'failed', 'interrupted')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    error_code TEXT,
    UNIQUE (task_id, attempt_no),
    CHECK (
        (status = 'started' AND finished_at IS NULL AND error_code IS NULL)
        OR (status IN ('succeeded', 'interrupted') AND finished_at IS NOT NULL AND error_code IS NULL)
        OR (status = 'failed' AND finished_at IS NOT NULL AND error_code IS NOT NULL)
    ),
    CHECK (error_code IS NULL OR (length(error_code) BETWEEN 1 AND 64))
)"""

_TABLES = {"tasks": TASKS_DDL, "executions": EXECUTIONS_DDL, "execution_attempts": ATTEMPTS_DDL}


class MigrationError(ValueError):
    """A safe migration failure; the cause remains internal to the caller."""

    code = "migration_failed"


class SchemaVersionError(MigrationError):
    """The runtime cannot serve the declared or actual SQLite schema."""

    code = "schema_version_unsupported"


@dataclass(frozen=True, slots=True)
class MigrationReport:
    previous_version: int
    current_version: int
    changed: bool
    backfilled: int
    backup_created: bool


def _normalized_sql(value: str) -> str:
    # Keyword/layout differences are harmless; string literals define actual
    # allowed values and must not be case-folded into a different constraint.
    parts = re.split(r"('(?:''|[^'])*')", value)
    return "".join(
        part if index % 2 else re.sub(r"\s+", "", part).casefold()
        for index, part in enumerate(parts)
    )


def _check_tables(connection: sqlite3.Connection, expected: dict[str, str]) -> None:
    objects = connection.execute(
        "SELECT type, name, sql FROM sqlite_schema WHERE name NOT GLOB 'sqlite_*'"
    ).fetchall()
    if len(objects) != len(expected):
        raise SchemaVersionError("SQLite schema is not supported")
    for kind, name, sql in objects:
        if (
            kind != "table"
            or name not in expected
            or not isinstance(sql, str)
            or _normalized_sql(sql) != _normalized_sql(expected[name])
        ):
            raise SchemaVersionError("SQLite schema is not supported")


def require_schema(connection: sqlite3.Connection) -> None:
    """Require the exact v1 schema with active FK enforcement; perform no DDL.

    This detects a forged user_version and foreign-key corruption before serving
    work. It does not attest to external effects or authenticate scope labels.
    """
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in (SCHEMA_VERSION, CUTOVER_SCHEMA_VERSION):
            raise SchemaVersionError("SQLite migration is required or schema is unsupported")
        if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise SchemaVersionError("SQLite foreign-key enforcement is required")
        _check_tables(
            connection,
            _TABLES if version == SCHEMA_VERSION else {**_TABLES, "source_cutover": CUTOVER_DDL},
        )
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise SchemaVersionError("SQLite foreign-key integrity check failed")
    except sqlite3.Error as error:
        raise SchemaVersionError("SQLite schema could not be verified") from error


def _valid_identity(value: object) -> bool:
    return isinstance(value, str) and bool(value) and len(value) <= 128 and value == value.strip()


def _reject_constant(_: str) -> None:
    raise ValueError("Nonfinite JSON values are not supported")


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    fields: dict[str, object] = {}
    for name, value in pairs:
        if name in fields:
            raise ValueError("Duplicate JSON fields are not supported")
        fields[name] = value
    return fields


def _validate_legacy(connection: sqlite3.Connection) -> int:
    count = 0
    cursor = connection.execute(
        "SELECT task_id, scope_id, idempotency_key, payload, status, created_at FROM tasks"
    )
    for task_id, scope, key, payload, status, created in cursor:
        try:
            if (
                not all(_valid_identity(value) for value in (task_id, scope, key))
                or status != "queued"
            ):
                raise ValueError("Invalid legacy identity or state")
            if (
                not isinstance(payload, str)
                or len(payload.encode("utf-8")) > _MAX_LEGACY_PAYLOAD_BYTES
            ):
                raise ValueError("Invalid legacy payload")
            values = json.loads(
                payload, object_pairs_hook=_unique_fields, parse_constant=_reject_constant
            )
            if not isinstance(values, dict) or set(values) != {
                "booking_reference",
                "new_check_in",
                "confirmed",
            }:
                raise ValueError("Invalid legacy payload fields")
            if not isinstance(values["new_check_in"], str):
                raise TypeError("Invalid legacy date")
            change = BookingChange(
                booking_reference=values["booking_reference"],
                new_check_in=date.fromisoformat(values["new_check_in"]),
                confirmed=values["confirmed"],
            )
            canonical = json.dumps(change.payload(), sort_keys=True, separators=(",", ":"))
            if canonical != payload:
                raise ValueError("Noncanonical legacy payload")
            if not isinstance(created, str) or len(created) > 64 or created != created.strip():
                raise ValueError("Invalid legacy timestamp")
            instant = datetime.fromisoformat(created)
            if instant.tzinfo is None or instant.utcoffset() != timedelta(0):
                raise ValueError("Legacy timestamp must be UTC")
        except (ValueError, TypeError, OverflowError) as error:
            raise MigrationError(
                "Legacy intake data is invalid; no migration was applied"
            ) from error
        count += 1
    return count


def _path(value: str | Path, *, must_exist: bool) -> Path:
    if str(value) in {"", ":memory:"}:
        raise MigrationError("Migration requires filesystem database and backup paths")
    candidate = Path(value).absolute()
    if candidate.is_symlink() or (candidate.exists() and not candidate.is_file()):
        raise MigrationError("Migration paths must be regular files")
    if not candidate.parent.is_dir():
        raise MigrationError("Migration parent directory is missing")
    if must_exist and not candidate.is_file():
        raise MigrationError("Migration database is missing")
    return candidate.parent.resolve() / candidate.name


def _backup(source: Path, destination: Path) -> None:
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    completed = False
    try:
        deadline = time.monotonic() + _TIMEOUT_SECONDS

        def progress(_status: int, _remaining: int, _total: int) -> None:
            if time.monotonic() >= deadline:
                raise MigrationError("SQLite backup exceeded its deadline")

        with (
            closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as reader,
            closing(sqlite3.connect(destination)) as target,
        ):
            reader.backup(target, pages=64, progress=progress, sleep=0.01)
        completed = True
    finally:
        if not completed:
            destination.unlink(missing_ok=True)


def migrate(
    database: str | Path,
    backup: str | Path,
    *,
    failpoint: Callable[[str], None] | None = None,
) -> MigrationReport:
    """Upgrade quiesced v0 M1 data atomically after a private SQLite backup.

    Existing v1 data is verified and left unchanged without rewriting a backup.
    A new database is initialized only by this explicit operation. Existing
    backup files are never overwritten. Failpoints are test callbacks owned by
    the caller, invoked after DDL and immediately before commit. Do not expose
    them as remotely selectable production operations.
    """
    try:
        database_path = _path(database, must_exist=False)
        backup_path = _path(backup, must_exist=False)
        if database_path == backup_path:
            raise MigrationError("Database and backup paths must differ")
        if not database_path.exists():
            descriptor = os.open(database_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(descriptor)
        with closing(sqlite3.connect(database_path, timeout=_TIMEOUT_SECONDS)) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            try:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if version in (SCHEMA_VERSION, CUTOVER_SCHEMA_VERSION):
                    require_schema(connection)
                    connection.rollback()
                    return MigrationReport(version, version, False, 0, False)
                if version != 0:
                    raise SchemaVersionError("SQLite schema version is not supported")
                table_count = connection.execute(
                    "SELECT count(*) FROM sqlite_schema WHERE name NOT GLOB 'sqlite_*'"
                ).fetchone()[0]
                _check_tables(connection, {"tasks": TASKS_DDL} if table_count else {})
                backfilled = _validate_legacy(connection) if table_count else 0
                _backup(database_path, backup_path)
                if not table_count:
                    connection.execute(TASKS_DDL)
                connection.execute(EXECUTIONS_DDL)
                connection.execute(ATTEMPTS_DDL)
                if failpoint is not None:
                    failpoint("migration.after_schema")
                for task_id, created_at in connection.execute(
                    "SELECT task_id, created_at FROM tasks"
                ):
                    connection.execute(
                        "INSERT INTO executions VALUES (?, 'booking.inquire', 'accepted', ?, 0, ?, ?, NULL, NULL)",
                        (task_id, str(uuid4()), created_at, created_at),
                    )
                connection.execute("PRAGMA user_version=1")
                require_schema(connection)
                if failpoint is not None:
                    failpoint("migration.before_commit")
                connection.commit()
                return MigrationReport(0, SCHEMA_VERSION, True, backfilled, True)
            finally:
                if connection.in_transaction:
                    connection.rollback()
    except MigrationError:
        raise
    except (OSError, sqlite3.Error) as error:
        raise MigrationError(
            "SQLite migration or backup failed; inspect safe diagnostics"
        ) from error
