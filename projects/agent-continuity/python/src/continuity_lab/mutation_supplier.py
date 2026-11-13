"""One independent synthetic booking authority for inquiry and exact mutation.

Initialization is explicit. The inquiry view can write only inquiry receipts;
mutation additionally requires a versioned, revision-bound committed intent from
its trusted caller. This local fixture is not an authentication boundary.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from .case_models import ActionIntent, canonical, parse_intent, require_mutation_quote
from .effect_models import MutationResult, parse_mutation_result, require_result_binding
from .execution_models import (
    ExecutionCapacityExceeded,
    ExecutionError,
    InquiryResult,
    UnsupportedOperation,
)
from .models import BookingChange
from .supplier import (
    BookingSnapshot,
    InquiryCapabilities,
    InquiryObservation,
    SupplierRejected,
    SupplierReplayConflict,
    SupplierUnavailable,
)

LOGGER = logging.getLogger("continuity_lab.mutation_supplier")
LOGGER.addHandler(logging.NullHandler())
SCHEMA_VERSION = 1
_TIMEOUT = 5.0
_MAX_PAYLOAD = 32768
_METADATA = """CREATE TABLE supplier_metadata (
 singleton INTEGER PRIMARY KEY CHECK (singleton = 1), provider_id TEXT NOT NULL UNIQUE,
 cooperating INTEGER NOT NULL CHECK (cooperating IN (0,1))
)"""
_BOOKINGS = """CREATE TABLE bookings (
 scope_id TEXT NOT NULL, booking_reference TEXT NOT NULL, check_in TEXT NOT NULL,
 revision INTEGER NOT NULL CHECK (typeof(revision) = 'integer' AND revision >= 0),
 PRIMARY KEY (scope_id, booking_reference)
)"""
_INQUIRIES = """CREATE TABLE inquiry_receipts (
 effect_id TEXT PRIMARY KEY NOT NULL, scope_id TEXT NOT NULL,
 booking_reference TEXT NOT NULL, request_json TEXT NOT NULL, result_json TEXT NOT NULL,
 created_at TEXT NOT NULL,
 FOREIGN KEY (scope_id, booking_reference) REFERENCES bookings(scope_id, booking_reference)
)"""
_RECEIPTS = """CREATE TABLE mutation_receipts (
 effect_id TEXT PRIMARY KEY NOT NULL, scope_id TEXT NOT NULL,
 booking_reference TEXT NOT NULL, request_json TEXT NOT NULL, result_json TEXT NOT NULL,
 created_at TEXT NOT NULL,
 FOREIGN KEY (scope_id, booking_reference) REFERENCES bookings(scope_id, booking_reference)
)"""
_CALLS = """CREATE TABLE apply_calls (
 call_id TEXT PRIMARY KEY NOT NULL, effect_id TEXT NOT NULL, scope_id TEXT NOT NULL,
 request_json TEXT NOT NULL, outcome TEXT NOT NULL CHECK (outcome IN ('applied','replayed','rejected','conflict')),
 result_json TEXT, created_at TEXT NOT NULL,
 CHECK ((outcome IN ('applied','replayed')) = (result_json IS NOT NULL))
)"""
_TABLES = {
    "supplier_metadata": _METADATA,
    "bookings": _BOOKINGS,
    "inquiry_receipts": _INQUIRIES,
    "mutation_receipts": _RECEIPTS,
    "apply_calls": _CALLS,
}


class MutationRejected(SupplierRejected):
    code = "mutation_rejected"


class MutationConflict(SupplierReplayConflict):
    code = "mutation_conflict"


class MutationUnavailable(SupplierUnavailable):
    code = "dependency_unavailable"


class MutationLookupUnsupported(UnsupportedOperation):
    """Absence of lookup capability must never masquerade as an absent effect."""


@dataclass(frozen=True, slots=True)
class MutationCapabilities:
    idempotent: bool = True
    lookup: bool = True

    def __post_init__(self) -> None:
        if type(self.idempotent) is not bool or type(self.lookup) is not bool:
            raise ValueError("Supplier capabilities must be explicit booleans")


@dataclass(frozen=True, slots=True)
class MutationObservation:
    result: MutationResult
    created: bool


def _event(event: str, code: str = "ok") -> None:
    try:
        LOGGER.log(
            logging.ERROR
            if code == "dependency_unavailable"
            else logging.WARNING
            if code != "ok"
            else logging.INFO,
            event,
            extra={"event": event, "code": code},
        )
    except Exception:  # noqa: BLE001 - fixture telemetry cannot change supplier truth
        return


def _identity(value: object) -> str:
    if (
        type(value) is not str
        or not 1 <= len(value) <= 128
        or value != value.strip()
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise MutationRejected("Supplier identity is invalid")
    value.encode("utf-8")
    return value


def _path(value: str | Path) -> Path:
    if not isinstance(value, (str, Path)) or str(value) in {"", ":memory:"}:
        raise MutationUnavailable("A filesystem supplier database is required")
    path = Path(value).absolute()
    if path.is_symlink() or (path.exists() and not path.is_file()) or not path.parent.is_dir():
        raise MutationUnavailable("Supplier path is unavailable")
    return path.parent.resolve() / path.name


def _normalized(value: str) -> str:
    parts = re.split(r"('(?:''|[^'])*')", value)
    return "".join(
        part if i % 2 else re.sub(r"\s+", "", part).casefold() for i, part in enumerate(parts)
    )


def _metadata(connection: sqlite3.Connection) -> tuple[str, bool]:
    rows = connection.execute("SELECT provider_id,cooperating FROM supplier_metadata").fetchall()
    try:
        if (
            len(rows) != 1
            or type(rows[0][0]) is not str
            or str(UUID(rows[0][0])) != rows[0][0]
            or type(rows[0][1]) is not int
            or rows[0][1] not in (0, 1)
        ):
            raise ValueError("Supplier metadata is invalid")
        return rows[0][0], bool(rows[0][1])
    except (ValueError, TypeError, IndexError) as error:
        raise MutationUnavailable("Supplier authority metadata is invalid") from error


def _schema(connection: sqlite3.Connection) -> None:
    if (
        connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1
        or connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION
    ):
        raise MutationUnavailable("Supplier schema is unavailable")
    rows = connection.execute(
        "SELECT type,name,sql FROM sqlite_schema WHERE name NOT GLOB 'sqlite_*'"
    ).fetchall()
    if len(rows) != len(_TABLES) or any(
        kind != "table"
        or name not in _TABLES
        or not isinstance(ddl, str)
        or _normalized(ddl) != _normalized(_TABLES[name])
        for kind, name, ddl in rows
    ):
        raise MutationUnavailable("Supplier schema is unsupported")
    _metadata(connection)
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise MutationUnavailable("Supplier references are invalid")


def _stamp(value: datetime) -> str:
    if type(value) is not datetime or value.utcoffset() is None:
        raise ValueError("Supplier clock must return an aware instant")
    return value.astimezone(UTC).isoformat()


def _stored_stamp(value: object) -> str:
    if type(value) is not str or not 1 <= len(value) <= 64:
        raise ValueError("Supplier timestamp is invalid")
    stamp = datetime.fromisoformat(value)
    if stamp.utcoffset() != timedelta(0):
        raise ValueError("Supplier timestamp must be UTC")
    return value


def _json(value: object) -> dict[str, Any]:
    if type(value) is not str or not 1 <= len(value) <= _MAX_PAYLOAD:
        raise ValueError("Supplier payload is invalid")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for name, item in pairs:
            if name in result:
                raise ValueError("Supplier payload repeats a field")
            result[name] = item
        return result

    body = json.loads(value, object_pairs_hook=unique)
    if type(body) is not dict or canonical(body) != value:
        raise ValueError("Supplier payload must be a canonical object")
    return body


def _booking(row: sqlite3.Row) -> BookingSnapshot:
    try:
        scope, reference = _identity(row["scope_id"]), _identity(row["booking_reference"])
        check_in = date.fromisoformat(row["check_in"])
        request = BookingChange(reference, check_in, True)
        if (
            request.booking_reference != reference
            or type(row["revision"]) is not int
            or not 0 <= row["revision"] < 9223372036854775807
        ):
            raise ValueError("Supplier booking fields are invalid")
        return BookingSnapshot(scope, reference, check_in, row["revision"])
    except (ValueError, TypeError, KeyError, IndexError, OverflowError) as error:
        raise MutationUnavailable("Supplier contains invalid booking state") from error


def _intent(value: ActionIntent) -> tuple[ActionIntent, str]:
    if type(value) is not ActionIntent:
        raise MutationRejected("A revision-bound committed mutation is required")
    try:
        require_mutation_quote(value)
        payload = canonical(value.payload())
        if len(payload) > _MAX_PAYLOAD or parse_intent(json.loads(payload)) != value:
            raise ValueError("Mutation intent is invalid")
        return value, payload
    except (ValueError, TypeError, KeyError, OverflowError, ExecutionError) as error:
        raise MutationRejected("A revision-bound committed mutation is required") from error


def _result(row: sqlite3.Row) -> MutationResult:
    try:
        intent = parse_intent(_json(row["request_json"]))
        quote = require_mutation_quote(intent)
        result = parse_mutation_result(_json(row["result_json"]))
        if (row["effect_id"], row["scope_id"], row["booking_reference"], row["created_at"]) != (
            intent.effect_id,
            intent.scope_id,
            quote.booking_reference,
            result.created_at,
        ):
            raise ValueError("Supplier receipt fields disagree")
        require_result_binding(result, intent)
        _stored_stamp(row["created_at"])
        return result
    except (ValueError, TypeError, KeyError, IndexError, OverflowError, ExecutionError) as error:
        raise MutationUnavailable("Supplier contains invalid mutation evidence") from error


def initialize_mutation_supplier(
    database: str | Path,
    *,
    scope_id: str,
    booking_reference: str = "DEMO-BK-001",
    check_in: date = date(2030, 12, 1),
    revision: int = 0,
    cooperating: bool = True,
) -> None:
    """Seed a new authority or verify an unchanged seed; never reset a booking."""
    if type(cooperating) is not bool:
        raise MutationRejected("Supplier cooperation must be an explicit boolean")
    scope_id = _identity(scope_id)
    request = BookingChange(booking_reference, check_in, True)
    if type(revision) is not int or not 0 <= revision < 9223372036854775807:
        raise MutationRejected("Supplier seed revision is invalid")
    path = _path(database)
    try:
        if not path.exists():
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            os.close(descriptor)
        with closing(sqlite3.connect(path, timeout=_TIMEOUT)) as connection, connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            objects = connection.execute(
                "SELECT 1 FROM sqlite_schema WHERE name NOT GLOB 'sqlite_*' LIMIT 1"
            ).fetchone()
            if version == 0 and objects is None:
                for ddl in _TABLES.values():
                    connection.execute(ddl)
                connection.execute(
                    "INSERT INTO supplier_metadata VALUES (1,?,?)", (str(uuid4()), int(cooperating))
                )
                connection.execute("PRAGMA user_version=1")
            _schema(connection)
            if _metadata(connection)[1] != cooperating:
                raise MutationConflict("Supplier cooperation mode cannot change")
            row = connection.execute(
                "SELECT * FROM bookings WHERE scope_id=? AND booking_reference=?",
                (scope_id, request.booking_reference),
            ).fetchone()
            if row is not None:
                if _booking(row) != BookingSnapshot(
                    scope_id, request.booking_reference, request.new_check_in, revision
                ):
                    raise MutationConflict("Supplier seed identity already has different state")
            else:
                if connection.execute("SELECT count(*) FROM bookings").fetchone()[0] >= 10000:
                    raise ExecutionCapacityExceeded(
                        "Supplier fixture booking capacity is exhausted"
                    )
                connection.execute(
                    "INSERT INTO bookings VALUES (?,?,?,?)",
                    (
                        scope_id,
                        request.booking_reference,
                        request.new_check_in.isoformat(),
                        revision,
                    ),
                )
        _event("mutation_supplier_initialized")
    except (sqlite3.Error, OSError) as error:
        _event("mutation_supplier_failed", "dependency_unavailable")
        raise MutationUnavailable("Supplier initialization is unavailable") from error


class MutationSupplier:
    """Cooperating exact effect deduplication and reliable receipt lookup."""

    capabilities = MutationCapabilities()

    def __init__(
        self,
        database: str | Path,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        failpoint: Callable[[str], None] | None = None,
        maximum_mutations: int = 10000,
        maximum_calls: int = 100000,
    ) -> None:
        for value in (maximum_mutations, maximum_calls):
            if type(value) is not int or not 1 <= value <= 1000000:
                raise ValueError("Supplier limits must be finite positive integers")
        self._provider_id: str | None = None
        self.database = _path(database)
        self.clock = clock
        self.failpoint = failpoint
        self.maximum_mutations = maximum_mutations
        self.maximum_calls = maximum_calls
        if not self.database.is_file():
            raise MutationUnavailable("Supplier must be explicitly initialized")
        with self._connection() as connection:
            self._provider_id = _metadata(connection)[0]

    @property
    def provider_id(self) -> str:
        if self._provider_id is None:
            raise MutationUnavailable("Supplier authority identity is unavailable")
        return self._provider_id

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        try:
            with closing(
                sqlite3.connect(self.database.as_uri() + "?mode=rw", uri=True, timeout=_TIMEOUT)
            ) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA foreign_keys=ON")
                _schema(connection)
                provider_id, cooperating = _metadata(connection)
                expected_mode = self.capabilities == MutationCapabilities()
                if (
                    self.capabilities
                    not in {MutationCapabilities(), MutationCapabilities(False, False)}
                    or cooperating != expected_mode
                    or (self._provider_id is not None and provider_id != self._provider_id)
                ):
                    raise MutationUnavailable("Supplier authority or cooperation mode changed")
                yield connection
        except (sqlite3.Error, OSError) as error:
            _event("mutation_supplier_failed", "dependency_unavailable")
            raise MutationUnavailable("Supplier storage is unavailable") from error

    def inquiry_view(self) -> MutationInquiryView:
        return MutationInquiryView(self)

    def booking(self, *, scope_id: str, booking_reference: str) -> BookingSnapshot:
        scope_id = _identity(scope_id)
        reference = BookingChange(booking_reference, date(2030, 12, 1), True).booking_reference
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM bookings WHERE scope_id=? AND booking_reference=?",
                (scope_id, reference),
            ).fetchone()
            if row is None:
                raise MutationRejected("Supplier booking is unavailable")
            return _booking(row)

    def _call(
        self,
        connection: sqlite3.Connection,
        intent: ActionIntent,
        payload: str,
        outcome: str,
        result: MutationResult | None,
        stamp: str,
    ) -> None:
        count = connection.execute("SELECT count(*) FROM apply_calls").fetchone()[0]
        if count >= self.maximum_calls:
            raise ExecutionCapacityExceeded("Supplier invocation observation capacity is exhausted")
        connection.execute(
            "INSERT INTO apply_calls VALUES (?,?,?,?,?,?,?)",
            (
                str(uuid4()),
                intent.effect_id,
                intent.scope_id,
                payload,
                outcome,
                None if result is None else canonical(result.payload()),
                stamp,
            ),
        )

    def lookup(self, intent: ActionIntent) -> MutationObservation | None:
        intent, payload = _intent(intent)
        if require_mutation_quote(intent).supplier_id != self.provider_id:
            raise MutationConflict("Mutation belongs to another supplier authority")
        if not self.capabilities.lookup:
            raise MutationLookupUnsupported("Supplier does not declare reliable outcome lookup")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM mutation_receipts WHERE effect_id=?", (intent.effect_id,)
            ).fetchone()
            if row is None:
                _event("mutation_lookup_missing")
                return None
            if (row["scope_id"], row["request_json"]) != (intent.scope_id, payload):
                raise MutationConflict("Supplier effect already binds another mutation")
            value = _result(row)
        _event("mutation_lookup_found")
        return MutationObservation(value, False)

    def apply(self, intent: ActionIntent) -> MutationObservation:
        intent, payload = _intent(intent)
        quote = require_mutation_quote(intent)
        if quote.supplier_id != self.provider_id:
            raise MutationConflict("Mutation belongs to another supplier authority")
        stamp = _stamp(self.clock())
        error: ExecutionError | None = None
        observation: MutationObservation | None = None
        with self._connection() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = (
                connection.execute(
                    "SELECT * FROM mutation_receipts WHERE effect_id=?", (intent.effect_id,)
                ).fetchone()
                if self.capabilities.idempotent
                else None
            )
            if row is not None:
                if (row["scope_id"], row["request_json"]) != (intent.scope_id, payload):
                    self._call(connection, intent, payload, "conflict", None, stamp)
                    error = MutationConflict("Supplier effect already binds another mutation")
                else:
                    result = _result(row)
                    # Receipt replay survives a full observation buffer. It
                    # cannot allocate another effect or change a booking.
                    if (
                        connection.execute("SELECT count(*) FROM apply_calls").fetchone()[0]
                        < self.maximum_calls
                    ):
                        self._call(connection, intent, payload, "replayed", result, stamp)
                    observation = MutationObservation(result, False)
            else:
                booking_row = connection.execute(
                    "SELECT * FROM bookings WHERE scope_id=? AND booking_reference=?",
                    (intent.scope_id, quote.booking_reference),
                ).fetchone()
                booking = None if booking_row is None else _booking(booking_row)
                if booking is None or booking.revision != quote.expected_supplier_revision:
                    self._call(connection, intent, payload, "rejected", None, stamp)
                    error = MutationRejected(
                        "Supplier booking revision no longer matches the confirmed proposal"
                    )
                elif (
                    connection.execute(
                        "SELECT count(*) FROM apply_calls WHERE outcome='applied'"
                    ).fetchone()[0]
                    >= self.maximum_mutations
                ):
                    raise ExecutionCapacityExceeded(
                        "Supplier mutation fixture capacity is exhausted"
                    )
                else:
                    assert (
                        quote.case_id is not None and quote.expected_supplier_revision is not None
                    )
                    result = MutationResult(
                        intent.effect_id,
                        intent.intent_id,
                        intent.task_id,
                        quote.case_id,
                        self.provider_id,
                        intent.scope_id,
                        quote.booking_reference,
                        booking.check_in,
                        quote.new_check_in,
                        booking.revision,
                        booking.revision + 1,
                        quote.amount_minor,
                        quote.currency,
                        stamp,
                    )
                    changed = connection.execute(
                        "UPDATE bookings SET check_in=?,revision=revision+1 WHERE scope_id=? AND booking_reference=? AND revision=?",
                        (
                            quote.new_check_in.isoformat(),
                            intent.scope_id,
                            quote.booking_reference,
                            booking.revision,
                        ),
                    )
                    if changed.rowcount != 1:
                        raise MutationUnavailable("Supplier booking changed during protected apply")
                    self._call(connection, intent, payload, "applied", result, stamp)
                    if self.capabilities.idempotent:
                        connection.execute(
                            "INSERT INTO mutation_receipts VALUES (?,?,?,?,?,?)",
                            (
                                intent.effect_id,
                                intent.scope_id,
                                quote.booking_reference,
                                payload,
                                canonical(result.payload()),
                                stamp,
                            ),
                        )
                    observation = MutationObservation(result, True)
            if self.failpoint is not None:
                self.failpoint("supplier.before_mutation_commit")
        if error is not None:
            _event("mutation_supplier_rejected", error.code)
            raise error
        assert observation is not None
        _event("mutation_applied" if observation.created else "mutation_replayed")
        if self.failpoint is not None:
            self.failpoint("supplier.after_mutation_commit")
        return observation

    def count_calls(self, *, scope_id: str) -> int:
        with self._connection() as connection:
            return int(
                connection.execute(
                    "SELECT count(*) FROM apply_calls WHERE scope_id=?", (_identity(scope_id),)
                ).fetchone()[0]
            )

    def count_mutations(self, *, scope_id: str) -> int:
        with self._connection() as connection:
            return int(
                connection.execute(
                    "SELECT count(*) FROM apply_calls WHERE scope_id=? AND outcome='applied'",
                    (_identity(scope_id),),
                ).fetchone()[0]
            )

    def count_inquiries(self, *, scope_id: str) -> int:
        with self._connection() as connection:
            return int(
                connection.execute(
                    "SELECT count(*) FROM inquiry_receipts WHERE scope_id=?", (_identity(scope_id),)
                ).fetchone()[0]
            )


class NonCooperatingMutationSupplier(MutationSupplier):
    """No deduplication or lookup; harness observations grant no worker authority."""

    capabilities = MutationCapabilities(idempotent=False, lookup=False)


class MutationInquiryView:
    """Narrow read-only booking investigation over the SAME mutable authority."""

    capabilities = InquiryCapabilities()

    def __init__(self, supplier: MutationSupplier) -> None:
        self._supplier = supplier
        self.database = supplier.database

    @property
    def provider_id(self) -> str:
        return self._supplier.provider_id

    def booking(self, *, scope_id: str, booking_reference: str) -> BookingSnapshot:
        return self._supplier.booking(scope_id=scope_id, booking_reference=booking_reference)

    def _read(
        self, row: sqlite3.Row, scope_id: str, effect_id: str, request: BookingChange
    ) -> InquiryObservation:
        try:
            if (row["scope_id"], row["booking_reference"], row["request_json"]) != (
                scope_id,
                request.booking_reference,
                canonical(request.payload()),
            ):
                raise SupplierReplayConflict("Inquiry effect already has different semantics")
            body = _json(row["result_json"])
            if set(body) != {"booking_reference", "new_check_in", "available"}:
                raise ValueError("Inquiry result fields are invalid")
            result = InquiryResult(
                body["booking_reference"],
                date.fromisoformat(body["new_check_in"]),
                body["available"],
            )
            if (
                result.booking_reference != request.booking_reference
                or result.new_check_in != request.new_check_in
            ):
                raise ValueError("Inquiry result does not match its request")
            _stored_stamp(row["created_at"])
            return InquiryObservation(result, effect_id, False)
        except (ValueError, TypeError, KeyError, IndexError, OverflowError) as error:
            raise MutationUnavailable("Supplier contains invalid inquiry evidence") from error

    def lookup(
        self, *, scope_id: str, effect_id: str, request: BookingChange
    ) -> InquiryObservation | None:
        scope_id, effect_id = _identity(scope_id), _identity(effect_id)
        if type(request) is not BookingChange:
            raise SupplierRejected("A typed inquiry is required")
        with self._supplier._connection() as connection:
            row = connection.execute(
                "SELECT * FROM inquiry_receipts WHERE effect_id=?", (effect_id,)
            ).fetchone()
            return None if row is None else self._read(row, scope_id, effect_id, request)

    def inquire(
        self, *, scope_id: str, effect_id: str, request: BookingChange
    ) -> InquiryObservation:
        scope_id, effect_id = _identity(scope_id), _identity(effect_id)
        if type(request) is not BookingChange:
            raise SupplierRejected("A typed inquiry is required")
        payload = canonical(request.payload())
        stamp = _stamp(self._supplier.clock())
        with self._supplier._connection() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM inquiry_receipts WHERE effect_id=?", (effect_id,)
            ).fetchone()
            if row is not None:
                return self._read(row, scope_id, effect_id, request)
            booking = connection.execute(
                "SELECT * FROM bookings WHERE scope_id=? AND booking_reference=?",
                (scope_id, request.booking_reference),
            ).fetchone()
            if booking is None:
                raise SupplierRejected("Supplier booking is unavailable")
            _booking(booking)
            if connection.execute("SELECT count(*) FROM inquiry_receipts").fetchone()[0] >= 10000:
                raise ExecutionCapacityExceeded("Supplier inquiry receipt capacity is exhausted")
            result = InquiryResult(
                request.booking_reference,
                request.new_check_in,
                request.new_check_in != date(2030, 12, 25),
            )
            connection.execute(
                "INSERT INTO inquiry_receipts VALUES (?,?,?,?,?,?)",
                (
                    effect_id,
                    scope_id,
                    request.booking_reference,
                    payload,
                    canonical(result.payload()),
                    stamp,
                ),
            )
        _event("mutation_inquiry_created")
        return InquiryObservation(result, effect_id, True)
