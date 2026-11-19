"""Independent persisted fake supplier with read-only, idempotent inquiries.

The seed operation is explicit fixture administration. Runtime inquiry/lookup
never creates schema or updates a booking. Scope comes from the trusted local
caller; the fixture is not an authentication service or a production supplier.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import NoReturn, Protocol

from .execution_models import ExecutionError, InquiryResult
from .models import BookingChange

LOGGER = logging.getLogger("continuity_lab.supplier")
SUPPLIER_SCHEMA_VERSION = 1
_BUSY_TIMEOUT_SECONDS = 5.0
_UNAVAILABLE_DATE = date(2030, 12, 25)
_BOOKINGS_DDL = """CREATE TABLE bookings (
    scope_id TEXT NOT NULL,
    booking_reference TEXT NOT NULL,
    check_in TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (typeof(revision) = 'integer' AND revision >= 0),
    PRIMARY KEY (scope_id, booking_reference)
)"""
_INQUIRIES_DDL = """CREATE TABLE inquiries (
    effect_id TEXT PRIMARY KEY NOT NULL,
    scope_id TEXT NOT NULL,
    booking_reference TEXT NOT NULL,
    request_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (scope_id, booking_reference) REFERENCES bookings(scope_id, booking_reference)
)"""


class SupplierRejected(ExecutionError):
    """Definitive inquiry/input rejection; no inquiry was accepted."""

    code = "inquiry_rejected"


class SupplierReplayConflict(ExecutionError):
    """An existing effect or seed identity has different accepted semantics."""

    code = "inquiry_conflict"


class SupplierUnavailable(ExecutionError):
    """The persisted fake supplier cannot safely serve its declared contract."""

    code = "dependency_unavailable"


@dataclass(frozen=True, slots=True)
class InquiryCapabilities:
    idempotent: bool = True
    lookup: bool = True
    read_only: bool = True


@dataclass(frozen=True, slots=True)
class BookingSnapshot:
    scope_id: str
    booking_reference: str
    check_in: date
    revision: int


@dataclass(frozen=True, slots=True)
class InquiryObservation:
    result: InquiryResult
    effect_id: str
    created: bool


class InquirySupplierPort(Protocol):
    """Read-only inquiry capability shared by compatibility and mutable authorities."""

    capabilities: InquiryCapabilities

    def inquire(
        self, *, scope_id: str, effect_id: str, request: BookingChange
    ) -> InquiryObservation: ...
    def lookup(
        self, *, scope_id: str, effect_id: str, request: BookingChange
    ) -> InquiryObservation | None: ...


def _event(event: str, code: str = "ok") -> None:
    # These call sites pass fixed producer literals, never request/exception data.
    if event == "supplier_unavailable":
        level = logging.ERROR
    elif event in {"supplier_replay_conflict", "supplier_initialization_rejected"}:
        level = logging.WARNING
    elif event == "supplier_initialization_failed":
        level = logging.ERROR
    else:
        level = logging.INFO
    try:
        LOGGER.log(level, event, extra={"event": event, "code": code})
    except Exception:  # noqa: BLE001 - telemetry cannot alter supplier truth or failures
        return


def _identity(value: str) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > 128:
        raise SupplierRejected("Supplier identity is invalid")
    return value


def _reference(value: str) -> str:
    if type(value) is not str:
        raise SupplierRejected("Supplier booking reference is invalid")
    try:
        canonical = BookingChange(value, date(2030, 12, 1), confirmed=True).booking_reference
    except (ValueError, TypeError) as error:
        raise SupplierRejected("Supplier booking reference is invalid") from error
    if canonical != value:
        raise SupplierRejected("Supplier booking reference must be canonical")
    return canonical


def _request(value: BookingChange) -> str:
    if type(value) is not BookingChange:
        raise SupplierRejected("A validated supplier inquiry is required")
    try:
        canonical = BookingChange(value.booking_reference, value.new_check_in, value.confirmed)
    except (ValueError, TypeError) as error:
        raise SupplierRejected("Supplier inquiry is invalid") from error
    if canonical != value:
        raise SupplierRejected("Supplier inquiry must be canonical")
    return json.dumps(canonical.payload(), sort_keys=True, separators=(",", ":"))


def _database_path(database: str | Path) -> Path:
    if not isinstance(database, (str, Path)):
        raise SupplierUnavailable("Supplier database path is invalid")
    if str(database) in {"", ":memory:"}:
        raise SupplierUnavailable("A file-backed supplier database is required")
    path = Path(database).absolute()
    if path.is_symlink() or (path.exists() and not path.is_file()) or not path.parent.is_dir():
        raise SupplierUnavailable("Supplier database path is invalid")
    return path.parent.resolve() / path.name


def _normalized_sql(sql: str) -> str:
    parts = re.split(r"('(?:''|[^'])*')", sql)
    return "".join(
        value if index % 2 else re.sub(r"\s+", "", value).casefold()
        for index, value in enumerate(parts)
    )


def _schema(connection: sqlite3.Connection) -> None:
    if connection.execute("PRAGMA user_version").fetchone()[0] != SUPPLIER_SCHEMA_VERSION:
        raise SupplierUnavailable("Supplier schema version is unsupported; initialize explicitly")
    expected = {"bookings": _BOOKINGS_DDL, "inquiries": _INQUIRIES_DDL}
    objects = connection.execute(
        "SELECT type, name, sql FROM sqlite_schema WHERE name NOT GLOB 'sqlite_*'"
    ).fetchall()
    if len(objects) != len(expected):
        raise SupplierUnavailable("Supplier schema is unsupported")
    for kind, name, sql in objects:
        if (
            kind != "table"
            or name not in expected
            or not isinstance(sql, str)
            or _normalized_sql(sql) != _normalized_sql(expected[name])
        ):
            raise SupplierUnavailable("Supplier schema is unsupported")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise SupplierUnavailable("Supplier persisted state is invalid")


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Duplicate fields")
        result[name] = value
    return result


def _nonfinite(_: str) -> NoReturn:
    raise ValueError("Nonfinite JSON")


def _json_object(value: object, fields: set[str]) -> dict:
    if not isinstance(value, str) or len(value.encode("utf-8")) > 2048:
        raise ValueError("Invalid persisted JSON size")
    body = json.loads(value, object_pairs_hook=_unique_fields, parse_constant=_nonfinite)
    if not isinstance(body, dict) or set(body) != fields:
        raise ValueError("Invalid persisted fields")
    return body


def _booking_row(row: sqlite3.Row) -> BookingSnapshot:
    try:
        scope, reference, when, revision = row
        _identity(scope)
        _reference(reference)
        if not isinstance(when, str) or type(revision) is not int or revision < 0:
            raise ValueError("Invalid booking state")
        parsed_date = date.fromisoformat(when)
        if parsed_date.isoformat() != when:
            raise ValueError("Noncanonical booking date")
        return BookingSnapshot(scope, reference, parsed_date, revision)
    except (ValueError, TypeError, SupplierRejected) as error:
        raise SupplierUnavailable("Supplier persisted booking is invalid") from error


def _inquiry_row(row: sqlite3.Row) -> InquiryObservation:
    try:
        effect, scope, reference, request_json, result_json, created = row
        _identity(effect)
        _identity(scope)
        _reference(reference)
        body = _json_object(request_json, {"booking_reference", "new_check_in", "confirmed"})
        accepted = BookingChange(
            body["booking_reference"], date.fromisoformat(body["new_check_in"]), body["confirmed"]
        )
        if _request(accepted) != request_json or accepted.booking_reference != reference:
            raise ValueError("Invalid accepted inquiry")
        fields = _json_object(result_json, {"booking_reference", "new_check_in", "available"})
        result = InquiryResult(
            fields["booking_reference"],
            date.fromisoformat(fields["new_check_in"]),
            fields["available"],
        )
        if (
            result.booking_reference != accepted.booking_reference
            or result.new_check_in != accepted.new_check_in
            or json.dumps(result.payload(), sort_keys=True, separators=(",", ":")) != result_json
        ):
            raise ValueError("Invalid stored inquiry result")
        if not isinstance(created, str) or len(created) > 64:
            raise ValueError("Invalid inquiry timestamp")
        instant = datetime.fromisoformat(created)
        if instant.tzinfo is None or instant.utcoffset() != timedelta(0):
            raise ValueError("Invalid inquiry timestamp")
        return InquiryObservation(result=result, effect_id=effect, created=False)
    except (ValueError, TypeError, SupplierRejected) as error:
        raise SupplierUnavailable("Supplier persisted inquiry is invalid") from error


def _validate_data(connection: sqlite3.Connection) -> None:
    for row in connection.execute("SELECT * FROM bookings"):
        _booking_row(row)
    for row in connection.execute("SELECT * FROM inquiries"):
        _inquiry_row(row)


def initialize_supplier(
    database: str | Path,
    *,
    scope_id: str,
    booking_reference: str = "DEMO-BK-001",
    check_in: date = date(2030, 12, 1),
) -> None:
    """Explicitly create/validate fixture schema and seed one immutable booking.

    Repeating the same seed is harmless. A changed seed never resets a booking
    or its inquiry history. Serving constructors cannot call this operation.
    """
    scope_id = _identity(scope_id)
    booking_reference = _reference(booking_reference)
    if type(check_in) is not date:
        raise SupplierRejected("Supplier fixture date is invalid")
    path = _database_path(database)
    try:
        if not path.exists():
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(descriptor)
        with closing(sqlite3.connect(path, timeout=_BUSY_TIMEOUT_SECONDS)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            try:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                objects = connection.execute(
                    "SELECT count(*) FROM sqlite_schema WHERE name NOT GLOB 'sqlite_*'"
                ).fetchone()[0]
                if version == 0 and objects == 0:
                    connection.execute(_BOOKINGS_DDL)
                    connection.execute(_INQUIRIES_DDL)
                    connection.execute("PRAGMA user_version=1")
                _schema(connection)
                _validate_data(connection)
                existing = connection.execute(
                    "SELECT * FROM bookings WHERE scope_id=? AND booking_reference=?",
                    (scope_id, booking_reference),
                ).fetchone()
                if existing is not None:
                    booking = _booking_row(existing)
                    if booking.check_in != check_in or booking.revision != 0:
                        raise SupplierReplayConflict(
                            "Supplier fixture seed conflicts with existing booking"
                        )
                else:
                    connection.execute(
                        "INSERT INTO bookings VALUES (?, ?, ?, 0)",
                        (scope_id, booking_reference, check_in.isoformat()),
                    )
                connection.commit()
            finally:
                if connection.in_transaction:
                    connection.rollback()
    except (sqlite3.Error, OSError) as error:
        raise SupplierUnavailable("Supplier fixture initialization failed") from error
    _event("supplier_initialized")


class FakeSupplier:
    capabilities = InquiryCapabilities()

    def __init__(self, database: str | Path) -> None:
        self.database = _database_path(database)
        with self._connection() as connection:
            connection.execute("BEGIN")
            _validate_data(connection)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        try:
            with closing(
                sqlite3.connect(
                    self.database.as_uri() + "?mode=rw",
                    uri=True,
                    timeout=_BUSY_TIMEOUT_SECONDS,
                )
            ) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA foreign_keys=ON")
                _schema(connection)
                try:
                    yield connection
                finally:
                    if connection.in_transaction:
                        connection.rollback()
        except sqlite3.Error as error:
            _event("supplier_unavailable", "dependency_unavailable")
            raise SupplierUnavailable("Supplier storage is unavailable") from error

    def _existing(
        self,
        connection: sqlite3.Connection,
        *,
        scope_id: str,
        effect_id: str,
        canonical: str,
    ) -> InquiryObservation | None:
        row = connection.execute(
            "SELECT * FROM inquiries WHERE effect_id=?", (effect_id,)
        ).fetchone()
        if row is None:
            return None
        if row["scope_id"] != scope_id or row["request_json"] != canonical:
            _event("supplier_replay_conflict", "inquiry_conflict")
            raise SupplierReplayConflict(
                "Supplier inquiry identity conflicts with its accepted request"
            )
        return _inquiry_row(row)

    def inquire(
        self, *, scope_id: str, effect_id: str, request: BookingChange
    ) -> InquiryObservation:
        scope_id, effect_id = _identity(scope_id), _identity(effect_id)
        canonical = _request(request)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._existing(
                connection, scope_id=scope_id, effect_id=effect_id, canonical=canonical
            )
            if existing is not None:
                _event("supplier_inquiry_replayed")
                return existing
            booking = connection.execute(
                "SELECT * FROM bookings WHERE scope_id=? AND booking_reference=?",
                (scope_id, request.booking_reference),
            ).fetchone()
            if booking is None:
                raise SupplierRejected("Supplier booking is unavailable for this inquiry")
            _booking_row(booking)
            result = InquiryResult(
                request.booking_reference,
                request.new_check_in,
                request.new_check_in != _UNAVAILABLE_DATE,
            )
            connection.execute(
                "INSERT INTO inquiries VALUES (?, ?, ?, ?, ?, ?)",
                (
                    effect_id,
                    scope_id,
                    request.booking_reference,
                    canonical,
                    json.dumps(result.payload(), sort_keys=True, separators=(",", ":")),
                    datetime.now(UTC).isoformat(),
                ),
            )
            connection.commit()
        _event("supplier_inquiry_created")
        return InquiryObservation(result=result, effect_id=effect_id, created=True)

    def lookup(
        self, *, scope_id: str, effect_id: str, request: BookingChange
    ) -> InquiryObservation | None:
        scope_id, effect_id = _identity(scope_id), _identity(effect_id)
        canonical = _request(request)
        with self._connection() as connection:
            # Scope first: a caller cannot retrieve another scope's observation.
            if (
                connection.execute(
                    "SELECT 1 FROM inquiries WHERE effect_id=? AND scope_id=?",
                    (effect_id, scope_id),
                ).fetchone()
                is None
            ):
                _event("supplier_lookup_missing")
                return None
            result = self._existing(
                connection, scope_id=scope_id, effect_id=effect_id, canonical=canonical
            )
        _event("supplier_lookup_found")
        return result

    def booking(self, *, scope_id: str, booking_reference: str) -> BookingSnapshot:
        scope_id, booking_reference = _identity(scope_id), _reference(booking_reference)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM bookings WHERE scope_id=? AND booking_reference=?",
                (scope_id, booking_reference),
            ).fetchone()
            if row is None:
                raise SupplierRejected("Supplier booking is unavailable")
            return _booking_row(row)

    def count_inquiries(self, *, scope_id: str) -> int:
        scope_id = _identity(scope_id)
        with self._connection() as connection:
            return connection.execute(
                "SELECT count(*) FROM inquiries WHERE scope_id=?", (scope_id,)
            ).fetchone()[0]


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise SupplierRejected("Supplier initialization arguments are invalid")


def main(argv: list[str] | None = None) -> int:
    # Application configuration is explicit; importing the supplier library does
    # not attach handlers or change root logging. Reuse the owned safe formatter.
    from .execution_cli import configure_logging

    configure_logging()
    parser = _Parser(description="Initialize a deterministic, read-only inquiry supplier fixture")
    parser.add_argument("--db", required=True)
    subcommands = parser.add_subparsers(dest="action", required=True)
    initialize = subcommands.add_parser("init")
    initialize.add_argument("--scope", required=True)
    initialize.add_argument("--booking", default="DEMO-BK-001")
    initialize.add_argument("--check-in", default="2030-12-01")
    try:
        args = parser.parse_args(argv)
        initialize_supplier(
            args.db,
            scope_id=args.scope,
            booking_reference=args.booking,
            check_in=date.fromisoformat(args.check_in),
        )
    except ExecutionError as error:
        event = (
            "supplier_initialization_failed"
            if isinstance(error, SupplierUnavailable)
            else "supplier_initialization_rejected"
        )
        _event(event, error.code)
        print(
            json.dumps(
                {
                    "status": "failed",
                    "code": error.code,
                    "detail": "Supplier fixture initialization failed",
                }
            )
        )
        return 2
    except ValueError:
        _event("supplier_initialization_rejected", "invalid_input")
        print(
            json.dumps(
                {
                    "status": "failed",
                    "code": "invalid_input",
                    "detail": "Supplier fixture input is invalid",
                }
            )
        )
        return 2
    except Exception:  # noqa: BLE001 - secret-safe, nonzero outer CLI containment
        _event("supplier_initialization_failed", "unexpected_error")
        print(
            json.dumps(
                {
                    "status": "failed",
                    "code": "unexpected_error",
                    "detail": "Supplier fixture initialization failed",
                }
            )
        )
        return 1
    print(
        json.dumps(
            {
                "status": "initialized",
                "schema_version": SUPPLIER_SCHEMA_VERSION,
                "read_only_inquiries": True,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
