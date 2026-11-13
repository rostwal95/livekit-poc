"""Explicit v1-to-v2 source quiescence and read-only transfer snapshots."""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import stat
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4

from .execution import ExecutionStore
from .execution_codec import decode_attempt, decode_execution
from .execution_models import ExecutionError
from .migrations import _backup, _path, _validate_legacy, require_schema
from .sqlite_admission import CUTOVER_DDL, CUTOVER_SCHEMA_VERSION
from .transfer import TransferSnapshot, make_snapshot

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())


class CutoverError(ExecutionError):
    code = "cutover_failed"


@dataclass(frozen=True, slots=True)
class SourceState:
    migration_id: str
    source_digest: str
    state: str
    backup_path: Path = field(repr=False)
    target_identity: str | None = None


@contextmanager
def _source_errors() -> Iterator[None]:
    try:
        yield
    except (sqlite3.Error, OSError) as error:
        raise CutoverError("Source storage is unavailable; retain source and backup") from error


def _private_backup(path: Path) -> None:
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
    ):
        raise CutoverError("Retained backup must remain a private owner-only regular file")


def _state(connection: sqlite3.Connection) -> SourceState:
    rows = connection.execute(
        "SELECT migration_id,source_digest,state,backup_path,target_identity FROM source_cutover"
    ).fetchall()
    if len(rows) != 1:
        raise CutoverError("Source has invalid cutover metadata")
    migration_id, digest, state, backup, target = rows[0]
    try:
        valid_identity = isinstance(migration_id, str) and str(UUID(migration_id)) == migration_id
    except ValueError:
        valid_identity = False
    if (
        not valid_identity
        or not isinstance(digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        or state not in {"quiesced", "cutover"}
        or not isinstance(backup, str)
        or (
            target is not None
            and (not isinstance(target, str) or re.fullmatch(r"[0-9a-f]{64}", target) is None)
        )
    ):
        raise CutoverError("Source has invalid cutover metadata")
    return SourceState(migration_id, digest, state, Path(backup), target)


def read_source_state(database: str | Path) -> SourceState | None:
    store = ExecutionStore(database)
    with (
        _source_errors(),
        closing(
            sqlite3.connect(store.database.as_uri() + "?mode=ro", uri=True, timeout=5)
        ) as connection,
    ):
        connection.execute("PRAGMA foreign_keys=ON")
        require_schema(connection)
        if connection.execute("PRAGMA user_version").fetchone()[0] == 1:
            return None
        return _state(connection)


def _snapshot(connection: sqlite3.Connection, migration_id: str) -> TransferSnapshot:
    connection.row_factory = sqlite3.Row
    tasks = [dict(row) for row in connection.execute("SELECT * FROM tasks ORDER BY task_id")]
    executions = [
        dict(row) for row in connection.execute("SELECT * FROM executions ORDER BY task_id")
    ]
    attempts = [
        dict(row)
        for row in connection.execute(
            "SELECT * FROM execution_attempts ORDER BY task_id,attempt_no,attempt_id"
        )
    ]
    for rows in (tasks, executions, attempts):
        for row in rows:
            for value in row.values():
                if isinstance(value, str):
                    value.encode("utf-8")
                    if "\0" in value:
                        raise CutoverError("Source text is unsupported by the selected target")
    task_map = {row["task_id"]: row for row in tasks}
    _validate_legacy(connection)
    for row in executions:
        task = task_map[row["task_id"]]
        decode_execution(
            {
                **row,
                "scope_id": task["scope_id"],
                "idempotency_key": task["idempotency_key"],
                "payload": task["payload"],
            }
        )
    for row in attempts:
        decode_attempt(row)
    return make_snapshot(tasks, executions, attempts, migration_id=migration_id)


def source_snapshot(database: str | Path) -> TransferSnapshot:
    store = ExecutionStore(database)
    with (
        _source_errors(),
        closing(
            sqlite3.connect(store.database.as_uri() + "?mode=ro", uri=True, timeout=5)
        ) as connection,
    ):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN")
        require_schema(connection)
        if connection.execute("PRAGMA user_version").fetchone()[0] != CUTOVER_SCHEMA_VERSION:
            raise CutoverError("Source must be explicitly quiesced before export")
        state = _state(connection)
        snapshot = _snapshot(connection, state.migration_id)
        if snapshot.source_digest != state.source_digest:
            raise CutoverError("Source changed after its cutover snapshot")
        return snapshot


def prepare_source(
    database: str | Path,
    backup: str | Path,
    *,
    failpoint: Callable[[str], None] | None = None,
) -> TransferSnapshot:
    """Drain a cooperating worker and writes, back up v1, then persist CLOSED v2.

    Existing v2 source metadata resumes only its own migration and backup. There
    is deliberately no automatic unquiesce/dual-write path after a target commit.
    """
    store = ExecutionStore(database)
    destination = _path(backup, must_exist=False)
    if destination == store.database:
        raise CutoverError("Source and backup must use different files")
    try:
        with store.worker_slot(), closing(sqlite3.connect(store.database, timeout=5)) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            try:
                require_schema(connection)
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if version == CUTOVER_SCHEMA_VERSION:
                    state = _state(connection)
                    if (
                        state.backup_path != destination
                        or not destination.is_file()
                        or destination.is_symlink()
                    ):
                        raise CutoverError("Cutover backup does not match the original operation")
                    _private_backup(destination)
                    with closing(
                        sqlite3.connect(destination.as_uri() + "?mode=ro", uri=True)
                    ) as saved:
                        saved.execute("PRAGMA foreign_keys=ON")
                        require_schema(saved)
                        if (
                            saved.execute("PRAGMA user_version").fetchone()[0] != 1
                            or _snapshot(saved, state.migration_id).source_digest
                            != state.source_digest
                        ):
                            raise CutoverError(
                                "Retained backup no longer matches the original snapshot"
                            )
                    snapshot = _snapshot(connection, state.migration_id)
                    if snapshot.source_digest != state.source_digest:
                        raise CutoverError("Source changed after quiescence")
                    connection.rollback()
                    return snapshot
                if destination.exists():
                    _private_backup(destination)
                    with closing(
                        sqlite3.connect(destination.as_uri() + "?mode=ro", uri=True)
                    ) as saved:
                        saved.execute("PRAGMA foreign_keys=ON")
                        require_schema(saved)
                        if saved.execute("PRAGMA user_version").fetchone()[0] != 1:
                            raise CutoverError(
                                "Retained backup must contain the original v1 source"
                            )
                        comparison_id = str(uuid4())
                        if (
                            _snapshot(saved, comparison_id).source_digest
                            != _snapshot(connection, comparison_id).source_digest
                        ):
                            raise CutoverError("Retained backup does not match the current source")
                else:
                    _backup(store.database, destination)
                if failpoint is not None:
                    failpoint("source.before_quiesce_commit")
                migration_id = str(uuid4())
                snapshot = _snapshot(connection, migration_id)
                connection.execute(CUTOVER_DDL)
                connection.execute(
                    "INSERT INTO source_cutover (singleton,migration_id,source_digest,state,backup_path) VALUES (1,?,?, 'quiesced',?)",
                    (migration_id, snapshot.source_digest, str(destination)),
                )
                connection.execute("PRAGMA user_version=2")
                require_schema(connection)
                connection.commit()
            finally:
                if connection.in_transaction:
                    connection.rollback()
        LOGGER.info("source_quiesced", extra={"event": "source_quiesced", "code": "ok"})
        if failpoint is not None:
            failpoint("source.after_quiesce")
        return snapshot
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError) as error:
        raise CutoverError(
            "Source quiescence failed; inspect retained source and backup"
        ) from error


def mark_source_cutover(database: str | Path, snapshot: TransferSnapshot) -> None:
    store = ExecutionStore(database)
    with (
        store.worker_slot(),
        closing(sqlite3.connect(store.database, timeout=5)) as connection,
        connection,
    ):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        require_schema(connection)
        state = _state(connection)
        actual = _snapshot(connection, state.migration_id)
        if (state.migration_id, state.source_digest) != (
            snapshot.migration_id,
            snapshot.source_digest,
        ) or actual.source_digest != state.source_digest:
            raise CutoverError("Source no longer matches the verified target import")
        changed = connection.execute(
            "UPDATE source_cutover SET state='cutover' WHERE singleton=1 AND migration_id=? AND source_digest=? AND state IN ('quiesced','cutover')",
            (snapshot.migration_id, snapshot.source_digest),
        )
        if changed.rowcount != 1:
            raise CutoverError("Source cutover checkpoint could not be committed")
    LOGGER.info("source_cutover", extra={"event": "source_cutover", "code": "ok"})


def bind_source_target(database: str | Path, target_identity: str) -> None:
    """Bind one source migration to one trusted destination, with no rebinding.

    Source-only quiescence may precede destination selection; only a QUIESCED
    source with no target can be bound. Once bound, another endpoint/schema
    cannot import it, including after legitimate progress on the original target.
    """
    if (
        not isinstance(target_identity, str)
        or re.fullmatch(r"[0-9a-f]{64}", target_identity) is None
    ):
        raise CutoverError("Cutover destination identity is invalid")
    store = ExecutionStore(database)
    with (
        _source_errors(),
        store.worker_slot(),
        closing(sqlite3.connect(store.database, timeout=5)) as connection,
        connection,
    ):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        require_schema(connection)
        state = _state(connection)
        if state.target_identity is not None:
            if state.target_identity != target_identity:
                raise CutoverError("Source is already bound to a different cutover destination")
            return
        if state.state != "quiesced":
            raise CutoverError("Completed source lacks its destination checkpoint")
        connection.execute(
            "UPDATE source_cutover SET target_identity=? WHERE singleton=1 AND target_identity IS NULL AND state='quiesced'",
            (target_identity,),
        )
