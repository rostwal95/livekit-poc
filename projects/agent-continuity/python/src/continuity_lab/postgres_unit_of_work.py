"""Internal short PostgreSQL transactions shared by case and continuation owners.

The inquiry adapter owns connection/role/schema policy and the admission lock.
A caller must not perform supplier, model, network or await work in this context.
This is not a second scheduler or a public raw-SQL application interface.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg import sql

from .execution_models import UnsupportedOperation
from .postgres_store import PostgresExecutionStore


@contextmanager
def protected_transaction(
    executions: PostgresExecutionStore,
) -> Iterator[psycopg.Connection[dict[str, Any]]]:
    """Serialize one bounded authority operation, requiring explicit v2 upgrade.

    Keep lock ordering consistent: admission lock, case row, control/wait rows.
    Atomic confirmation consumption uses the same connection as intent creation.
    Expected schema/role/storage errors keep their existing safe error classes.
    """
    with executions._connection() as connection, connection.transaction():
        executions._write_lock(connection)
        row = connection.execute(
            sql.SQL("SELECT version FROM {} WHERE singleton").format(
                sql.Identifier(executions.settings.schema, "schema_metadata")
            )
        ).fetchone()
        if row is None or row["version"] not in {2, 3, 4}:
            raise UnsupportedOperation("Case and lifecycle operations require schema v2 or later")
        yield connection
