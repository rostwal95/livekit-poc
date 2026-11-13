"""The v2 source gate is operational metadata, not another execution scheduler."""

import sqlite3

from .models import IntakeCapacityExceeded

CUTOVER_SCHEMA_VERSION = 2
CUTOVER_DDL = """CREATE TABLE source_cutover (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    migration_id TEXT NOT NULL UNIQUE,
    source_digest TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('quiesced', 'cutover')),
    backup_path TEXT NOT NULL,
    target_identity TEXT,
    CHECK (target_identity IS NULL OR length(target_identity) = 64),
    CHECK (length(source_digest) = 64)
)"""


class SourceAdmissionClosed(IntakeCapacityExceeded):
    """Reads/replays remain available; new work must use the selected backend."""

    code = "source_quiesced"


def ensure_write_open(connection: sqlite3.Connection) -> None:
    """Check inside the caller's writer transaction, after previously admitted work drains."""
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version in (0, 1):
        return
    if version != CUTOVER_SCHEMA_VERSION:
        raise SourceAdmissionClosed("SQLite source admission state is unsupported")
    try:
        rows = connection.execute("SELECT state FROM source_cutover").fetchall()
    except sqlite3.Error as error:
        raise SourceAdmissionClosed("SQLite source admission state is unavailable") from error
    if len(rows) != 1 or rows[0][0] not in {"quiesced", "cutover"}:
        raise SourceAdmissionClosed("SQLite source admission state is invalid")
    raise SourceAdmissionClosed("SQLite source is closed to new execution writes")
