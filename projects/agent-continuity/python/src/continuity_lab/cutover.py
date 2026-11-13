"""Recoverable ordered source/target checkpoints; never dual-write or undo source."""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .postgres_migrations import (
    activate_import,
    install_schema,
    read_import_state,
    stage_import,
    verify_import,
)
from .postgres_settings import PostgresSettings
from .source_transfer import (
    CutoverError,
    bind_source_target,
    mark_source_cutover,
    prepare_source,
    read_source_state,
)


@dataclass(frozen=True, slots=True)
class CutoverReport:
    migration_id: str
    source_digest: str
    state: str
    resumed: bool
    tasks: int
    executions: int
    attempts: int


def cutover(
    database: str | Path,
    backup: str | Path,
    settings: PostgresSettings,
    *,
    failpoint: Callable[[str], None] | None = None,
) -> CutoverReport:
    """Close SQLite, stage/verify exact data, record source cutover, then activate.

    An ACTIVE matching receipt is completion, even after legitimate runtime
    progress. Never recompare or overwrite active business rows with old source.
    Operator controls these paths and migration credentials; serving code cannot
    call this owner-only operation with its restricted runtime role.
    """
    install_schema(settings)
    previous = read_source_state(database)
    snapshot = prepare_source(database, backup, failpoint=failpoint)
    # Bind endpoint/database/schema, excluding credential/role values. Preserve
    # this connection form for retries; different aliases/port mappings fail
    # closed rather than guessing that two configurations share one authority.
    target_identity = hashlib.sha256(
        json.dumps(
            {
                "host": "127.0.0.1" if settings.host == "localhost" else settings.host,
                "port": settings.port,
                "database": settings.dbname,
                "schema": settings.schema,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    bind_source_target(database, target_identity)
    source = read_source_state(database)
    target = read_import_state(settings)
    if source is None:
        raise CutoverError("Source quiescence checkpoint is missing")
    identity = (snapshot.migration_id, snapshot.source_digest)
    if target.state == "active":
        if source.state != "cutover" or (target.migration_id, target.source_digest) != identity:
            raise CutoverError("Active target does not match a completed source cutover")
    else:
        stage_import(settings, snapshot, failpoint=failpoint)
        verify_import(settings, snapshot)
        if failpoint:
            failpoint("cutover.after_target_verified")
        mark_source_cutover(database, snapshot)
        if failpoint:
            failpoint("cutover.after_source_cutover")
        activate_import(settings, *identity)
        if failpoint:
            failpoint("cutover.after_target_active")
    return CutoverReport(
        *identity,
        "active",
        previous is not None,
        len(snapshot.tasks),
        len(snapshot.executions),
        len(snapshot.attempts),
    )
