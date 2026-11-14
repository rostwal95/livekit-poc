"""Verify explicit business prerequisites without installing or activating state."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from psycopg import sql

from continuity_lab.authorization import AuthenticatedActor
from continuity_lab.completion_sink import _path, _private, _schema
from continuity_lab.execution_models import ExecutionError
from continuity_lab.mutation_supplier import _metadata
from continuity_lab.postgres_settings import PostgresSettings
from continuity_lab.postgres_store import PostgresExecutionStore
from continuity_lab.quote_reader import ReadOnlyQuoteSupplier


def check() -> None:
    """Require a retained ACTIVE v4 or v5 target and already initialized fixture files."""
    actor = AuthenticatedActor(
        "local-operator", os.environ.get("P1_WORKER_SCOPE", "demo-traveller")
    )
    store = PostgresExecutionStore(PostgresSettings.from_env())
    with store._connection() as connection:
        row = connection.execute(
            sql.SQL("SELECT version FROM {} WHERE singleton").format(
                sql.Identifier(store.settings.schema, "schema_metadata")
            )
        ).fetchone()
        if row is None or row["version"] not in (4, 5):
            raise ValueError("Business operation requires an ACTIVE v4 or v5 schema")
    supplier_path = Path(os.environ.get("P1_BUSINESS_SUPPLIER_DB", "/business/supplier.sqlite3"))
    supplier = ReadOnlyQuoteSupplier(supplier_path)
    supplier.booking(scope_id=actor.scope_id, booking_reference="DEMO-BK-001")
    with supplier._connection() as source:
        if _metadata(source)[1] is not True:
            raise ValueError("Business profile requires its configured cooperating supplier")
    sink_path = _path(os.environ.get("P1_BUSINESS_SINK_DB", "/business/completion.sqlite3"))
    if supplier_path.absolute() == sink_path:
        raise ValueError("Business supplier and receiver must remain independent")
    _private(sink_path)
    with closing(sqlite3.connect(sink_path.as_uri() + "?mode=ro", uri=True, timeout=1)) as sink:
        sink.row_factory = sqlite3.Row
        sink.execute("PRAGMA foreign_keys=ON")
        sink.execute("PRAGMA query_only=ON")
        sink.execute("BEGIN")
        _schema(sink)


def main() -> int:
    try:
        check()
    except (ExecutionError, ValueError, OSError, sqlite3.Error):
        print(
            json.dumps(
                {
                    "status": "business_prerequisites_missing",
                    "code": "prepare_active_v4_and_fixtures",
                }
            )
        )
        return 2
    print(
        json.dumps(
            {
                "status": "business_prerequisites_ready",
                "schema_activation": False,
                "fixture_initialization": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
