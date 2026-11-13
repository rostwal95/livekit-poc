"""Independent persistent cooperating completion receiver for local demonstrations.

Core receipts are never deleted. A separate diagnostic projection can be pruned
without erasing stable event deduplication. Serving opens an existing private
file; only explicit initialization creates schema and receiver identity.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import stat
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from .case_models import utc_instant, uuid_identity
from .effect_models import CompletionEvent, parse_completion_event
from .execution_models import ExecutionCapacityExceeded, ExecutionError
from .models import IdempotencyConflict

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
_VERSION = 1
_TABLES = {
    "sink_metadata": """CREATE TABLE sink_metadata (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1),
        receiver_id TEXT NOT NULL UNIQUE
    )""",
    "completion_receipts": """CREATE TABLE completion_receipts (
        event_id TEXT PRIMARY KEY NOT NULL,
        payload_json TEXT NOT NULL CHECK(length(payload_json) BETWEEN 1 AND 65536),
        received_at TEXT NOT NULL
    )""",
    "completion_diagnostics": """CREATE TABLE completion_diagnostics (
        event_id TEXT PRIMARY KEY NOT NULL REFERENCES completion_receipts(event_id),
        observed_at TEXT NOT NULL
    )""",
}


class CompletionSinkUnavailable(ExecutionError):
    code = "dependency_unavailable"


class CompletionSinkConflict(IdempotencyConflict):
    code = "idempotency_conflict"


@dataclass(frozen=True, slots=True)
class SinkReceipt:
    event_id: str
    created: bool
    received_at: str


class CompletionSinkPort(Protocol):
    @property
    def receiver_id(self) -> str: ...

    def accept(self, event: CompletionEvent) -> SinkReceipt: ...


def _event(event: str) -> None:
    try:
        LOGGER.info(event, extra={"event": event, "code": "ok"})
    except Exception:  # noqa: BLE001 - producer telemetry cannot change accepted state
        return


def _path(value: str | Path) -> Path:
    if type(value) not in {str, Path} and not isinstance(value, Path):
        raise CompletionSinkUnavailable("Receiver requires a file-backed database")
    if str(value) in {"", ":memory:"}:
        raise CompletionSinkUnavailable("Receiver requires a file-backed database")
    path = Path(value).absolute()
    if path.is_symlink() or not path.parent.is_dir() or (path.exists() and not path.is_file()):
        raise CompletionSinkUnavailable("Receiver database path is invalid")
    return path.parent.resolve() / path.name


def _private(path: Path) -> None:
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_nlink != 1
    ):
        raise CompletionSinkUnavailable(
            "Receiver database must be a private owner-only regular file"
        )


def _normalized(value: str) -> str:
    return "".join(
        part if index % 2 else re.sub(r"\s+", "", part).casefold()
        for index, part in enumerate(re.split(r"('(?:''|[^'])*')", value))
    )


def _schema(connection: sqlite3.Connection) -> str:
    if connection.execute("PRAGMA user_version").fetchone()[0] != _VERSION:
        raise CompletionSinkUnavailable("Receiver schema version is unsupported")
    objects = connection.execute(
        "SELECT type,name,sql FROM sqlite_schema WHERE name NOT GLOB 'sqlite_*'"
    ).fetchall()
    if len(objects) != len(_TABLES):
        raise CompletionSinkUnavailable("Receiver schema is unsupported")
    for kind, name, definition in objects:
        if (
            kind != "table"
            or name not in _TABLES
            or type(definition) is not str
            or _normalized(definition) != _normalized(_TABLES[name])
        ):
            raise CompletionSinkUnavailable("Receiver schema is unsupported")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise CompletionSinkUnavailable("Receiver state is inconsistent")
    rows = connection.execute("SELECT receiver_id FROM sink_metadata").fetchall()
    if len(rows) != 1:
        raise CompletionSinkUnavailable("Receiver identity is missing")
    try:
        return uuid_identity(rows[0][0])
    except (ValueError, TypeError, AttributeError) as error:
        raise CompletionSinkUnavailable("Receiver identity is invalid") from error


def initialize_completion_sink(database: str | Path, *, receiver_id: str | None = None) -> str:
    path = _path(database)
    if receiver_id is not None:
        receiver_id = uuid_identity(receiver_id)
    try:
        if not path.exists():
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            os.close(descriptor)
        _private(path)
        with closing(sqlite3.connect(path, timeout=5)) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            try:
                if (
                    connection.execute("PRAGMA user_version").fetchone()[0] == 0
                    and connection.execute(
                        "SELECT count(*) FROM sqlite_schema WHERE name NOT GLOB 'sqlite_*'"
                    ).fetchone()[0]
                    == 0
                ):
                    for ddl in _TABLES.values():
                        connection.execute(ddl)
                    connection.execute(
                        "INSERT INTO sink_metadata VALUES (1,?)",
                        (receiver_id or str(uuid4()),),
                    )
                    connection.execute("PRAGMA user_version=1")
                actual = _schema(connection)
                if receiver_id is not None and receiver_id != actual:
                    raise CompletionSinkConflict(
                        "Receiver identity conflicts with retained configuration"
                    )
                connection.commit()
            finally:
                if connection.in_transaction:
                    connection.rollback()
        _event("completion_sink_initialized")
        return actual
    except (OSError, sqlite3.Error) as error:
        raise CompletionSinkUnavailable("Receiver initialization failed") from error


class CompletionSink:
    def __init__(
        self,
        database: str | Path,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        maximum_records: int = 10000,
        diagnostic_limit: int = 100,
    ) -> None:
        if (
            type(maximum_records) is not int
            or not 1 <= maximum_records <= 1000000
            or type(diagnostic_limit) is not int
            or not 1 <= diagnostic_limit <= 1000
        ):
            raise ValueError("Receiver record limits must be finite positive integers")
        self.database = _path(database)
        self.clock, self.maximum_records, self.diagnostic_limit = (
            clock,
            maximum_records,
            diagnostic_limit,
        )
        self._receiver_id = ""
        with self._connection() as connection:
            self._receiver_id = _schema(connection)

    @property
    def receiver_id(self) -> str:
        return self._receiver_id

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        try:
            _private(self.database)
            with closing(
                sqlite3.connect(self.database.as_uri() + "?mode=rw", uri=True, timeout=5)
            ) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA foreign_keys=ON")
                actual = _schema(connection)
                if self._receiver_id and actual != self._receiver_id:
                    raise CompletionSinkConflict(
                        "Receiver identity changed from its configured target"
                    )
                yield connection
        except (OSError, sqlite3.Error) as error:
            raise CompletionSinkUnavailable("Receiver storage is unavailable") from error

    def _now(self) -> str:
        value = self.clock()
        if type(value) is not datetime or value.utcoffset() is None:
            raise ValueError("Receiver clock must return an aware instant")
        return value.astimezone(UTC).isoformat()

    def accept(self, event: CompletionEvent) -> SinkReceipt:
        if type(event) is not CompletionEvent:
            raise ValueError("A typed completion event is required")
        payload = event.canonical()
        if len(payload.encode("utf-8")) > 65536:
            raise ValueError("Completion event exceeds receiver payload limit")
        with self._connection() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = connection.execute(
                "SELECT payload_json,received_at FROM completion_receipts WHERE event_id=?",
                (event.event_id,),
            ).fetchone()
            if prior is not None:
                if prior["payload_json"] != payload:
                    raise CompletionSinkConflict("Completion event already has different semantics")
                # Validate retained evidence before acknowledging an identical retry.
                try:
                    parsed = parse_completion_event(json.loads(prior["payload_json"]))
                    received = utc_instant(prior["received_at"]).isoformat()
                except (ValueError, TypeError, AttributeError) as error:
                    raise CompletionSinkUnavailable("Receiver receipt is inconsistent") from error
                if parsed != event:
                    raise CompletionSinkUnavailable("Receiver receipt is inconsistent")
                created = False
            else:
                count = connection.execute("SELECT count(*) FROM completion_receipts").fetchone()[0]
                if count >= self.maximum_records:
                    raise ExecutionCapacityExceeded(
                        "Receiver receipt retention capacity is exhausted"
                    )
                received = self._now()
                created = True
                connection.execute(
                    "INSERT INTO completion_receipts VALUES (?,?,?)",
                    (event.event_id, payload, received),
                )
            connection.execute(
                "INSERT INTO completion_diagnostics VALUES (?,?) ON CONFLICT(event_id) DO UPDATE SET observed_at=excluded.observed_at",
                (event.event_id, self._now()),
            )
            connection.execute(
                "DELETE FROM completion_diagnostics WHERE event_id IN (SELECT event_id FROM completion_diagnostics ORDER BY observed_at DESC,event_id DESC LIMIT -1 OFFSET ?)",
                (self.diagnostic_limit,),
            )
        _event("completion_sink_accepted" if created else "completion_sink_replayed")
        return SinkReceipt(event.event_id, created, received)

    def prune_diagnostics(self, *, keep: int = 0) -> int:
        if type(keep) is not int or not 0 <= keep <= self.diagnostic_limit:
            raise ValueError("Diagnostic retention must remain within its configured bound")
        with self._connection() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "DELETE FROM completion_diagnostics WHERE event_id IN (SELECT event_id FROM completion_diagnostics ORDER BY observed_at DESC,event_id DESC LIMIT -1 OFFSET ?)",
                (keep,),
            )
            removed = cursor.rowcount
        _event("completion_diagnostics_pruned")
        return removed

    def count(self) -> int:
        with self._connection() as connection:
            return int(connection.execute("SELECT count(*) FROM completion_receipts").fetchone()[0])

    def diagnostic_count(self) -> int:
        with self._connection() as connection:
            return int(
                connection.execute("SELECT count(*) FROM completion_diagnostics").fetchone()[0]
            )

    def get(self, *, event_id: str) -> CompletionEvent | None:
        event_id = uuid_identity(event_id)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM completion_receipts WHERE event_id=?",
                (event_id,),
            ).fetchone()
            if row is None:
                return None
            try:
                event = parse_completion_event(json.loads(row["payload_json"]))
                if event.event_id != event_id or event.canonical() != row["payload_json"]:
                    raise ValueError("Receiver event binding is inconsistent")
                return event
            except (
                ValueError,
                TypeError,
                KeyError,
                AttributeError,
                OverflowError,
            ) as error:
                raise CompletionSinkUnavailable("Receiver receipt is invalid") from error
