"""Explicit owner installation for the durable delegation profile."""

from contextlib import closing
from uuid import uuid4

from psycopg import sql

from .issued_models import ExecutionLimits
from .postgres_settings import PostgresSettings
from .result_feed_store import validate_feed_state
from .work_models import WorkError, WorkLimits
from .work_schema import (
    ALL_TABLES,
    BASELINE_DDL,
    DEFINITION_SHA256,
    DELIVERY_TABLES,
    MARKER,
    SCHEMA_VERSION,
    catalog_sha256,
    check_settings,
    validate_work_schema,
)
from .work_schema import (
    execution_limits as read_execution_limits,
)

__all__ = ["ExecutionLimits", "PostgresSettings", "WorkLimits", "install_work_schema"]

_DEFAULT_LIMITS = WorkLimits()
_DEFAULT_EXECUTION_LIMITS = ExecutionLimits()
_INSERT_TABLES = (
    "accepted_work",
    "cancellation_commands",
    "issued_attempts",
    "attempt_results",
    *DELIVERY_TABLES,
    "result_feed_heads",
    "result_feed_events",
)


def install_work_schema(
    settings: PostgresSettings,
    limits: WorkLimits = _DEFAULT_LIMITS,
    *,
    execution_limits: ExecutionLimits = _DEFAULT_EXECUTION_LIMITS,
) -> None:
    """Install the final work profile or verify a previously installed profile."""
    check_settings(settings, owner=True)
    if type(limits) is not WorkLimits or type(execution_limits) is not ExecutionLimits:
        raise WorkError("invalid_input")
    try:
        with (
            closing(settings.connect(application_name="continuity-migrate")) as connection,
            connection.transaction(),
        ):
            connection.execute("SET LOCAL search_path TO pg_catalog")
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                ["readonly-work:" + settings.schema],
            )
            row = connection.execute("SELECT current_user AS name").fetchone()
            if row is None or row["name"] != "continuity_migrator":
                raise WorkError("unauthorized")
            namespace = sql.Identifier(settings.schema)
            exists = connection.execute(
                "SELECT 1 FROM pg_namespace WHERE nspname=%s", [settings.schema]
            ).fetchone()
            if exists is None:
                connection.execute(
                    sql.SQL("CREATE SCHEMA {} AUTHORIZATION continuity_migrator").format(namespace)
                )
                connection.execute(
                    sql.SQL(
                        "REVOKE ALL ON SCHEMA {} FROM PUBLIC; GRANT USAGE ON SCHEMA {} TO livekit_lab"
                    ).format(namespace, namespace)
                )
                connection.execute(
                    sql.SQL("COMMENT ON SCHEMA {} IS {}").format(namespace, sql.Literal(MARKER))
                )
                connection.execute(
                    sql.SQL("SET LOCAL search_path TO {},pg_catalog").format(namespace)
                )
                for statement in BASELINE_DDL.split(";"):
                    if statement.strip():
                        connection.execute(statement)
                names = sql.SQL(",").join(
                    sql.Identifier(settings.schema, name) for name in ALL_TABLES
                )
                mutable = sql.SQL(",").join(
                    sql.Identifier(settings.schema, name) for name in _INSERT_TABLES
                )
                connection.execute(
                    sql.SQL("REVOKE ALL ON {} FROM PUBLIC,livekit_lab").format(names)
                )
                connection.execute(sql.SQL("GRANT SELECT ON {} TO livekit_lab").format(names))
                connection.execute(sql.SQL("GRANT INSERT ON {} TO livekit_lab").format(mutable))
                connection.execute(
                    sql.SQL(
                        "GRANT UPDATE(record_count,cancel_count) ON {}.admission TO livekit_lab; GRANT UPDATE(last_sequence) ON {}.result_feed_heads TO livekit_lab"
                    ).format(namespace, namespace)
                )
                connection.execute(
                    sql.SQL("INSERT INTO {}.admission VALUES(true,0,0)").format(namespace)
                )
                connection.execute(
                    sql.SQL("INSERT INTO {}.execution_limits VALUES(true,%s,%s,%s)").format(
                        namespace
                    ),
                    (
                        execution_limits.max_active,
                        execution_limits.max_attempts,
                        execution_limits.lease_ms,
                    ),
                )
                connection.execute(
                    sql.SQL(
                        "INSERT INTO {}.result_feed_source VALUES(true,%s::uuid,floor(extract(epoch FROM clock_timestamp())*1000)::bigint)"
                    ).format(namespace),
                    (str(uuid4()),),
                )
                connection.execute("SET LOCAL search_path TO pg_catalog")
                digest = catalog_sha256(connection, settings.schema)
                connection.execute(
                    sql.SQL("INSERT INTO {}.schema_metadata VALUES(true,%s,%s,%s,%s,%s)").format(
                        namespace
                    ),
                    (
                        SCHEMA_VERSION,
                        DEFINITION_SHA256,
                        digest,
                        limits.max_records,
                        limits.max_cancel_commands,
                    ),
                )
            if (
                validate_work_schema(connection, settings, owner=True) != limits
                or read_execution_limits(connection, settings.schema) != execution_limits
            ):
                raise WorkError("schema_mismatch")
            validate_feed_state(connection, settings.schema)
    except WorkError:
        raise
    except Exception:  # noqa: BLE001 - owner failure cannot expose connection or SQL data
        raise WorkError("storage_unavailable") from None
