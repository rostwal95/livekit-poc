"""Explicit cooperating local result receiver, separate from execution and human ACK.

Initialization alone creates its private SQLite schema. Runtime retains immutable
receipts and never prunes identity protection, starts a queue, or sends messages.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import stat
import time
from collections.abc import Callable, Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from types import MappingProxyType
from uuid import uuid4

from .bounded_io import BoundedAsyncIO
from .delivery_models import (
    DeliveryIntent,
    DeliveryReceipt,
    match_receipt,
    snapshot_intent,
)
from .execution_models import ExecutionCapacityExceeded, ExecutionPortClosed
from .work_models import WorkCode, WorkError, WorkScope, work_identifier, work_uuid

__all__ = [
    "ReceiverBinding",
    "ResultReceiver",
    "initialize_result_receiver",
    "open_result_receiver",
]
LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
_SCHEMA = {
    "receiver_metadata": "CREATE TABLE receiver_metadata(singleton INTEGER PRIMARY KEY CHECK(singleton=1),receiver_id TEXT NOT NULL,max_records INTEGER NOT NULL CHECK(max_records BETWEEN 1 AND 10000))",
    "result_receipts": "CREATE TABLE result_receipts(delivery_id TEXT PRIMARY KEY NOT NULL,intent_json TEXT NOT NULL CHECK(length(intent_json) BETWEEN 1 AND 16384),receipt_json TEXT NOT NULL CHECK(length(receipt_json) BETWEEN 1 AND 2048))",
}


@dataclass(frozen=True, slots=True)
class ReceiverBinding:
    scope: WorkScope
    recipient_id: str

    def __post_init__(self) -> None:
        if type(self.scope) is not WorkScope:
            raise WorkError("invalid_input")
        work_identifier(self.recipient_id)


def _path(value: str | Path) -> Path:
    if (
        not isinstance(value, (str, Path))
        or not str(value)
        or len(str(value)) > 4096
        or "\0" in str(value)
        or str(value) == ":memory:"
    ):
        raise WorkError("invalid_input")
    path = Path(value).absolute()
    if ".." in path.parts or path.is_symlink() or not path.parent.is_dir():
        raise WorkError("invalid_input")
    parent = path.parent.resolve()
    info = parent.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o022:
        raise WorkError("invalid_input")
    return parent / path.name


def _private(path: Path) -> None:
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_uid != os.getuid()
        or info.st_nlink != 1
    ):
        raise WorkError("schema_mismatch")


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _schema(connection: sqlite3.Connection) -> tuple[str, int]:
    if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
        raise WorkError("schema_mismatch")
    rows = connection.execute(
        "SELECT type,name,sql FROM sqlite_schema WHERE name NOT GLOB 'sqlite_*'"
    ).fetchall()
    if len(rows) != len(_SCHEMA):
        raise WorkError("schema_mismatch")
    for kind, name, definition in rows:
        if (
            kind != "table"
            or name not in _SCHEMA
            or type(definition) is not str
            or _normalize(definition) != _normalize(_SCHEMA[name])
        ):
            raise WorkError("schema_mismatch")
    metadata = connection.execute(
        "SELECT singleton,receiver_id,max_records FROM receiver_metadata"
    ).fetchall()
    if (
        len(metadata) != 1
        or metadata[0][0] != 1
        or type(metadata[0][2]) is not int
        or not 1 <= metadata[0][2] <= 10000
    ):
        raise WorkError("schema_mismatch")
    try:
        return work_uuid(metadata[0][1]), metadata[0][2]
    except WorkError:
        raise WorkError("schema_mismatch") from None


def initialize_result_receiver(
    database: str | Path, *, receiver_id: str | None = None, maximum_records: int = 1000
) -> str:
    """Explicit install or validation-only reopen; existing core receipts are retained."""
    path = _path(database)
    if receiver_id is not None:
        work_uuid(receiver_id)
    if type(maximum_records) is not int or not 1 <= maximum_records <= 10000:
        raise WorkError("invalid_input")
    try:
        if not path.exists():
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            os.close(descriptor)
        _private(path)
        with closing(sqlite3.connect(path, timeout=1)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                count = connection.execute(
                    "SELECT count(*) FROM sqlite_schema WHERE name NOT GLOB 'sqlite_*'"
                ).fetchone()[0]
                if connection.execute("PRAGMA user_version").fetchone()[0] == 0 and count == 0:
                    for ddl in _SCHEMA.values():
                        connection.execute(ddl)
                    connection.execute(
                        "INSERT INTO receiver_metadata VALUES(1,?,?)",
                        (receiver_id or str(uuid4()), maximum_records),
                    )
                    connection.execute("PRAGMA user_version=1")
                actual, limit = _schema(connection)
                if (receiver_id is not None and receiver_id != actual) or maximum_records != limit:
                    raise WorkError("identity_conflict")
                connection.commit()
            finally:
                if connection.in_transaction:
                    connection.rollback()
        return actual
    except WorkError:
        raise
    except Exception:  # noqa: BLE001 - File/SQLite details are private.
        raise WorkError("storage_unavailable") from None


def _receipt_json(value: DeliveryReceipt) -> str:
    return json.dumps(
        {
            "delivery_id": value.delivery_id,
            "receipt_id": value.receipt_id,
            "receiver_id": value.receiver_id,
            "recipient_id": value.recipient_id,
            "result_sha256": value.result_sha256,
            "accepted_at_ms": value.accepted_at_ms,
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


class _ReceiverStore:
    def __init__(
        self, database: str | Path, receiver_id: str, failpoint: Callable[[str], None] | None
    ) -> None:
        self.path, self.receiver_id, self.failpoint = (
            _path(database),
            work_uuid(receiver_id),
            failpoint,
        )
        self._failures = 0
        self._lock = Lock()
        try:
            with closing(self.connection()) as connection:
                if _schema(connection)[0] != receiver_id:
                    raise WorkError("identity_conflict")
        except WorkError:
            raise
        except Exception:  # noqa: BLE001 - Private filesystem/SQLite boundary.
            raise WorkError("storage_unavailable") from None

    def connection(self) -> sqlite3.Connection:
        _private(self.path)
        connection = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=1)
        try:
            if _schema(connection)[0] != self.receiver_id:
                raise WorkError("identity_conflict")
            return connection
        except BaseException:
            connection.close()
            raise

    @property
    def failures(self) -> int:
        with self._lock:
            return self._failures

    def emit(self, operation: str, code: str) -> None:
        try:
            LOGGER.info(
                "result_receiver_operation",
                extra={"event": "result_receiver_operation", "operation": operation, "code": code},
            )
        except Exception:  # noqa: BLE001 - Telemetry cannot change commit truth.
            with self._lock:
                self._failures += 1

    def _find(
        self, connection: sqlite3.Connection, intent: DeliveryIntent
    ) -> DeliveryReceipt | None:
        row = connection.execute(
            "SELECT intent_json,receipt_json FROM result_receipts WHERE delivery_id=?",
            (intent.delivery_id,),
        ).fetchone()
        if row is None:
            return None
        if row[0] != intent.canonical().decode("ascii"):
            raise WorkError("identity_conflict")
        try:
            data = json.loads(row[1])
            expected = {
                "delivery_id",
                "receipt_id",
                "receiver_id",
                "recipient_id",
                "result_sha256",
                "accepted_at_ms",
            }
            if type(data) is not dict or set(data) != expected:
                raise WorkError("schema_mismatch")
            value = DeliveryReceipt(
                data["delivery_id"],
                data["receipt_id"],
                data["receiver_id"],
                data["recipient_id"],
                data["result_sha256"],
                data["accepted_at_ms"],
            )
            if _receipt_json(value) != row[1]:
                raise WorkError("schema_mismatch")
            match_receipt(intent, value)
            return value
        except (WorkError, ValueError, TypeError, KeyError):
            raise WorkError("schema_mismatch") from None

    def find(self, intent: DeliveryIntent) -> DeliveryReceipt | None:
        try:
            with closing(self.connection()) as connection:
                value = self._find(connection, intent)
            self.emit("find", "ok")
            return value
        except WorkError:
            raise
        except Exception:  # noqa: BLE001 - Private filesystem/SQLite boundary.
            raise WorkError("storage_unavailable") from None

    def accept(self, intent: DeliveryIntent) -> DeliveryReceipt:
        committing = False
        try:
            with closing(self.connection()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    value = self._find(connection, intent)
                    if value is None:
                        limit = _schema(connection)[1]
                        if (
                            connection.execute("SELECT count(*) FROM result_receipts").fetchone()[0]
                            >= limit
                        ):
                            raise WorkError("capacity")
                        value = DeliveryReceipt(
                            intent.delivery_id,
                            str(uuid4()),
                            self.receiver_id,
                            intent.recipient_id,
                            intent.result_sha256,
                            time.time_ns() // 1000000,
                        )
                        connection.execute(
                            "INSERT INTO result_receipts VALUES(?,?,?)",
                            (
                                intent.delivery_id,
                                intent.canonical().decode("ascii"),
                                _receipt_json(value),
                            ),
                        )
                    if self.failpoint is not None:
                        self.failpoint("receiver.before_commit")
                    committing = True
                    connection.commit()
                    if self.failpoint is not None:
                        self.failpoint("receiver.after_commit")
                finally:
                    if connection.in_transaction:
                        connection.rollback()
            self.emit("accept", "ok")
            return value
        except WorkError as error:
            self.emit("accept", "acknowledgement_unknown" if committing else error.code)
            raise WorkError("acknowledgement_unknown" if committing else error.code) from None
        except Exception:  # noqa: BLE001 - ACK loss and storage failure remain distinct.
            code: WorkCode = "acknowledgement_unknown" if committing else "storage_unavailable"
            self.emit("accept", code)
            raise WorkError(code) from None


class ResultReceiver:
    """Four actual SQLite I/O slots; no network listener or automatic delivery loop."""

    def __init__(self, store: _ReceiverStore, bindings: tuple[ReceiverBinding, ...]) -> None:
        if (
            type(store) is not _ReceiverStore
            or type(bindings) is not tuple
            or not 1 <= len(bindings) <= 64
        ):
            raise WorkError("invalid_input")
        copied = []
        for value in bindings:
            if type(value) is not ReceiverBinding or type(value.scope) is not WorkScope:
                raise WorkError("invalid_input")
            copied.append(
                ReceiverBinding(
                    WorkScope(value.scope.tenant_id, value.scope.account_id), value.recipient_id
                )
            )
        if len(set(copied)) != len(copied):
            raise WorkError("invalid_input")
        self._store, self._bindings = store, tuple(copied)
        self._io = BoundedAsyncIO(maximum=4, admission_timeout=0.05, shutdown_timeout=5)

    @property
    def receiver_id(self) -> str:
        return self._store.receiver_id

    @property
    def pending_count(self) -> int:
        return self._io.pending_count

    def metrics(self) -> Mapping[str, int]:
        return MappingProxyType(
            {"pending": self.pending_count, "telemetry_failures": self._store.failures}
        )

    def _snapshot(self, intent: DeliveryIntent) -> DeliveryIntent:
        value = snapshot_intent(intent)
        if (
            value.receiver_id != self.receiver_id
            or ReceiverBinding(value.scope, value.recipient_id) not in self._bindings
        ):
            raise WorkError("unauthorized")
        return value

    async def _run(self, operation: Callable[[], DeliveryReceipt | None]) -> DeliveryReceipt | None:
        try:
            return await self._io._run(operation)
        except ExecutionCapacityExceeded:
            raise WorkError("capacity") from None
        except ExecutionPortClosed:
            raise WorkError("closed") from None

    async def accept(self, intent: DeliveryIntent) -> DeliveryReceipt:
        value = self._snapshot(intent)
        result = await self._run(lambda: self._store.accept(value))
        if result is None:
            raise WorkError("schema_mismatch")
        return result

    async def find(self, intent: DeliveryIntent) -> DeliveryReceipt | None:
        value = self._snapshot(intent)
        return await self._run(lambda: self._store.find(value))

    async def close(self) -> None:
        deadline = time.monotonic() + 5
        try:
            await self._io.close()
            if time.monotonic() >= deadline:
                raise WorkError("cleanup_incomplete")
        except TimeoutError:
            raise WorkError("cleanup_incomplete") from None


def open_result_receiver(
    database: str | Path,
    *,
    receiver_id: str,
    bindings: tuple[ReceiverBinding, ...],
    harness_failpoint: Callable[[str], None] | None = None,
) -> ResultReceiver:
    """Trusted synchronous startup; opens an existing owner-initialized private file."""
    if harness_failpoint is not None and not callable(harness_failpoint):
        raise WorkError("invalid_input")
    return ResultReceiver(_ReceiverStore(database, receiver_id, harness_failpoint), bindings)
