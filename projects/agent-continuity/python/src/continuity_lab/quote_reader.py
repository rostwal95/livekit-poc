"""Read-only view of the independent synthetic provider for trusted proposals."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import date
from pathlib import Path

from .models import BookingChange
from .mutation_supplier import (
    MutationRejected,
    MutationUnavailable,
    _booking,
    _metadata,
    _path,
    _schema,
)
from .supplier import BookingSnapshot


class ReadOnlyQuoteSupplier:
    """Open an existing fixture with SQLite read-only/query-only protection.

    Retain initial provider/mode identity and verify it in every read snapshot.
    This port exposes no apply or receipt-writing capability.
    """

    def __init__(self, database: str | Path) -> None:
        self.database = _path(database)
        self._identity: tuple[str, bool] | None = None
        with self._connection() as connection:
            self._identity = _metadata(connection)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        try:
            with closing(
                sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True, timeout=1)
            ) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA query_only=ON")
                connection.execute("BEGIN")
                _schema(connection)
                if self._identity is not None and _metadata(connection) != self._identity:
                    raise MutationUnavailable("Quote provider identity changed")
                yield connection
        except (sqlite3.Error, OSError) as error:
            raise MutationUnavailable("Quote provider is unavailable") from error

    @property
    def provider_id(self) -> str:
        if self._identity is None:
            raise MutationUnavailable("Quote provider identity is unavailable")
        return self._identity[0]

    def booking(self, *, scope_id: str, booking_reference: str) -> BookingSnapshot:
        request = BookingChange(booking_reference, date(2030, 12, 1), True)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM bookings WHERE scope_id=? AND booking_reference=?",
                (scope_id, request.booking_reference),
            ).fetchone()
            if row is None:
                raise MutationRejected("Booking is unavailable")
            return _booking(row)
