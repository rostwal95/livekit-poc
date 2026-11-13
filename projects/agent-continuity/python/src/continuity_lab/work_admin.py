"""Explicit public owner installation for the opt-in P1 read-only work profile."""

from collections.abc import Callable
from contextlib import closing
from uuid import uuid4

from psycopg import sql

from .issued_models import ExecutionLimits
from .postgres_settings import PostgresSettings
from .result_feed_store import validate_feed_state
from .work_models import WorkError, WorkLimits
from .work_schema import (
    DDL,
    DEFINITION_SHA256,
    DEFINITION_SHA256_V2,
    DEFINITION_SHA256_V3,
    DEFINITION_SHA256_V4,
    DELIVERY_DDL,
    EXECUTION_DDL,
    FEED_DDL,
    FEED_TABLES,
    MARKER,
    MARKER_V2,
    MARKER_V3,
    MARKER_V4,
    catalog_sha256,
    check_settings,
    execution_limits,
    require_role,
    validate_work_schema,
    work_schema_version,
)

__all__ = [
    "ExecutionLimits",
    "PostgresSettings",
    "WorkLimits",
    "install_work_schema",
    "upgrade_work_schema_v2",
    "upgrade_work_schema_v3",
    "upgrade_work_schema_v4",
]
_DEFAULT_WORK_LIMITS = WorkLimits()


def install_work_schema(
    settings: PostgresSettings, limits: WorkLimits = _DEFAULT_WORK_LIMITS
) -> None:
    """Install one explicitly selected profile or validate an unchanged existing one.

    No booking schema migration, automatic repair, runtime initialization or
    refresh of an existing catalog baseline is performed. Owner remains trusted.
    """
    check_settings(settings, owner=True)
    if type(limits) is not WorkLimits:
        raise WorkError("invalid_input")
    try:
        with (
            closing(settings.connect(application_name="continuity-migrate")) as connection,
            connection.transaction(),
        ):
            connection.execute("SET search_path TO pg_catalog")
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                ["readonly-work:" + settings.schema],
            )
            exists = connection.execute(
                "SELECT 1 FROM pg_namespace WHERE nspname=%s", [settings.schema]
            ).fetchone()
            if exists:
                actual = validate_work_schema(connection, settings, owner=True)
                if actual != limits:
                    raise WorkError("schema_mismatch")
                return
            # Role lookup before schema exists cannot ask has_schema_privilege.
            row = connection.execute("SELECT current_user AS name").fetchone()
            if row is None or row["name"] != "continuity_migrator":
                raise WorkError("unauthorized")
            schema = sql.Identifier(settings.schema)
            connection.execute(
                sql.SQL("CREATE SCHEMA {} AUTHORIZATION continuity_migrator").format(schema)
            )
            connection.execute(
                sql.SQL(
                    "REVOKE ALL ON SCHEMA {} FROM PUBLIC; GRANT USAGE ON SCHEMA {} TO livekit_lab"
                ).format(schema, schema)
            )
            connection.execute(
                sql.SQL("COMMENT ON SCHEMA {} IS {}").format(schema, sql.Literal(MARKER))
            )
            connection.execute(sql.SQL("SET LOCAL search_path TO {},pg_catalog").format(schema))
            for statement in DDL.split(";"):
                if statement.strip():
                    connection.execute(statement)
            connection.execute(
                sql.SQL(
                    "REVOKE ALL ON ALL TABLES IN SCHEMA {} FROM PUBLIC,livekit_lab; GRANT SELECT ON ALL TABLES IN SCHEMA {} TO livekit_lab; GRANT INSERT ON {}.accepted_work,{}.cancellation_commands TO livekit_lab; GRANT UPDATE(record_count,cancel_count) ON {}.admission TO livekit_lab"
                ).format(schema, schema, schema, schema, schema)
            )
            connection.execute(sql.SQL("INSERT INTO {}.admission VALUES(true,0,0)").format(schema))
            connection.execute("SET LOCAL search_path TO pg_catalog")
            digest = catalog_sha256(connection, settings.schema)
            connection.execute(
                sql.SQL("INSERT INTO {}.schema_metadata VALUES(true,1,%s,%s,%s,%s)").format(schema),
                [DEFINITION_SHA256, digest, limits.max_records, limits.max_cancel_commands],
            )
            require_role(connection, settings.schema, owner=True)
            validate_work_schema(connection, settings, owner=True)
    except WorkError:
        raise
    except Exception:  # noqa: BLE001 - Public owner SQL/cleanup containment.
        # Configuration, driver and owner-cleanup details never escape this boundary.
        raise WorkError("storage_unavailable") from None


_DEFAULT_EXECUTION_LIMITS = ExecutionLimits()


def upgrade_work_schema_v2(
    settings: PostgresSettings,
    limits: ExecutionLimits = _DEFAULT_EXECUTION_LIMITS,
    *,
    harness_failpoint: Callable[[str], None] | None = None,
) -> None:
    """Explicit atomic owner upgrade of validated v1; repeat validates v2 without repair.

    Existing acceptance, cancellation and original metadata limits are preserved.
    Trusted failpoint observes before_commit/after_commit only; payloads cannot select it.
    """
    check_settings(settings, owner=True)
    if type(limits) is not ExecutionLimits or (
        harness_failpoint is not None and not callable(harness_failpoint)
    ):
        raise WorkError("invalid_input")
    committing = False
    try:
        with closing(settings.connect(application_name="continuity-migrate")) as connection:
            with connection.transaction():
                connection.execute("SET LOCAL search_path TO pg_catalog")
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                    ["readonly-work:" + settings.schema],
                )
                validate_work_schema(connection, settings, owner=True)
                schema = sql.Identifier(settings.schema)
                connection.execute(
                    sql.SQL("LOCK TABLE {}.admission IN ACCESS EXCLUSIVE MODE").format(schema)
                )
                validate_work_schema(connection, settings, owner=True)
                if work_schema_version(connection, settings.schema) in (2, 3, 4):
                    if execution_limits(connection, settings.schema) != limits:
                        raise WorkError("schema_mismatch")
                    return
                connection.execute(sql.SQL("SET LOCAL search_path TO {},pg_catalog").format(schema))
                for statement in EXECUTION_DDL.split(";"):
                    if statement.strip():
                        connection.execute(statement)
                connection.execute(
                    sql.SQL(
                        "REVOKE ALL ON {}.execution_limits,{}.issued_attempts,{}.attempt_results FROM PUBLIC,livekit_lab; GRANT SELECT ON {}.execution_limits,{}.issued_attempts,{}.attempt_results TO livekit_lab; GRANT INSERT ON {}.issued_attempts,{}.attempt_results TO livekit_lab"
                    ).format(*([schema] * 8))
                )
                connection.execute(
                    sql.SQL("INSERT INTO {}.execution_limits VALUES(true,%s,%s,%s)").format(schema),
                    [limits.max_active, limits.max_attempts, limits.lease_ms],
                )
                connection.execute(
                    sql.SQL(
                        "ALTER TABLE {}.schema_metadata DROP CONSTRAINT schema_metadata_version_check"
                    ).format(schema)
                )
                connection.execute(
                    sql.SQL("UPDATE {}.schema_metadata SET version=2 WHERE singleton").format(
                        schema
                    )
                )
                connection.execute(
                    sql.SQL(
                        "ALTER TABLE {}.schema_metadata ADD CONSTRAINT schema_metadata_version_check CHECK(version=2)"
                    ).format(schema)
                )
                connection.execute(
                    sql.SQL("COMMENT ON SCHEMA {} IS {}").format(schema, sql.Literal(MARKER_V2))
                )
                connection.execute("SET LOCAL search_path TO pg_catalog")
                digest = catalog_sha256(connection, settings.schema)
                connection.execute(
                    sql.SQL(
                        "UPDATE {}.schema_metadata SET version=2,definition_sha256=%s,catalog_sha256=%s WHERE singleton"
                    ).format(schema),
                    [DEFINITION_SHA256_V2, digest],
                )
                validate_work_schema(connection, settings, owner=True)
                if harness_failpoint is not None:
                    harness_failpoint("upgrade.before_commit")
                committing = True
            if harness_failpoint is not None:
                harness_failpoint("upgrade.after_commit")
    except WorkError:
        if committing:
            raise WorkError("acknowledgement_unknown") from None
        raise
    except Exception:  # noqa: BLE001 - Owner/driver/harness cleanup cannot expose private SQL.
        raise WorkError(
            "acknowledgement_unknown" if committing else "storage_unavailable"
        ) from None


def upgrade_work_schema_v3(
    settings: PostgresSettings,
    *,
    harness_failpoint: Callable[[str], None] | None = None,
) -> None:
    """Explicit atomic v2-to-v3 delivery/action extension; replay validates without repair."""
    check_settings(settings, owner=True)
    if harness_failpoint is not None and not callable(harness_failpoint):
        raise WorkError("invalid_input")
    committing = False
    try:
        with closing(settings.connect(application_name="continuity-migrate")) as connection:
            with connection.transaction():
                connection.execute("SET LOCAL search_path TO pg_catalog")
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                    ["readonly-work:" + settings.schema],
                )
                validate_work_schema(connection, settings, owner=True)
                version = work_schema_version(connection, settings.schema)
                if version == 1:
                    raise WorkError("schema_mismatch")
                schema = sql.Identifier(settings.schema)
                connection.execute(
                    sql.SQL("LOCK TABLE {}.admission IN ACCESS EXCLUSIVE MODE").format(schema)
                )
                validate_work_schema(connection, settings, owner=True)
                if work_schema_version(connection, settings.schema) in (3, 4):
                    return
                connection.execute(sql.SQL("SET LOCAL search_path TO {},pg_catalog").format(schema))
                for statement in DELIVERY_DDL.split(";"):
                    if statement.strip():
                        connection.execute(statement)
                for name in (
                    "result_delivery_intents",
                    "result_delivery_possible",
                    "result_delivery_receipts",
                    "result_actions",
                ):
                    table = sql.Identifier(settings.schema, name)
                    connection.execute(
                        sql.SQL(
                            "REVOKE ALL ON {} FROM PUBLIC,livekit_lab; GRANT SELECT,INSERT ON {} TO livekit_lab"
                        ).format(table, table)
                    )
                connection.execute(
                    sql.SQL(
                        "ALTER TABLE {}.schema_metadata DROP CONSTRAINT schema_metadata_version_check"
                    ).format(schema)
                )
                connection.execute(
                    sql.SQL("UPDATE {}.schema_metadata SET version=3 WHERE singleton").format(
                        schema
                    )
                )
                connection.execute(
                    sql.SQL(
                        "ALTER TABLE {}.schema_metadata ADD CONSTRAINT schema_metadata_version_check CHECK(version=3)"
                    ).format(schema)
                )
                connection.execute(
                    sql.SQL("COMMENT ON SCHEMA {} IS {}").format(schema, sql.Literal(MARKER_V3))
                )
                connection.execute("SET LOCAL search_path TO pg_catalog")
                digest = catalog_sha256(connection, settings.schema)
                connection.execute(
                    sql.SQL(
                        "UPDATE {}.schema_metadata SET definition_sha256=%s,catalog_sha256=%s WHERE singleton"
                    ).format(schema),
                    [DEFINITION_SHA256_V3, digest],
                )
                validate_work_schema(connection, settings, owner=True)
                if harness_failpoint is not None:
                    harness_failpoint("upgrade_v3.before_commit")
                committing = True
            if harness_failpoint is not None:
                harness_failpoint("upgrade_v3.after_commit")
    except WorkError:
        if committing:
            raise WorkError("acknowledgement_unknown") from None
        raise
    except Exception:  # noqa: BLE001 - Owner/driver failures expose only fixed codes.
        raise WorkError(
            "acknowledgement_unknown" if committing else "storage_unavailable"
        ) from None


def upgrade_work_schema_v4(
    settings: PostgresSettings,
    *,
    harness_failpoint: Callable[[str], None] | None = None,
) -> None:
    """Atomically adopt v3 result history and enable the generic scoped result feed.

    Backfill order is a deterministic adoption order, never original commit order.
    Repeat validates without generating a new source, repairing rows or refreshing
    catalog trust. No booking schema or existing payload/receipt is changed.
    """
    check_settings(settings, owner=True)
    if harness_failpoint is not None and not callable(harness_failpoint):
        raise WorkError("invalid_input")
    committing = False
    try:
        with closing(settings.connect(application_name="continuity-migrate")) as connection:
            with connection.transaction():
                connection.execute("SET LOCAL search_path TO pg_catalog")
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                    ["readonly-work:" + settings.schema],
                )
                validate_work_schema(connection, settings, owner=True)
                if work_schema_version(connection, settings.schema) not in (3, 4):
                    raise WorkError("schema_mismatch")
                schema = sql.Identifier(settings.schema)
                connection.execute(
                    sql.SQL("LOCK TABLE {}.admission IN ACCESS EXCLUSIVE MODE").format(schema)
                )
                validate_work_schema(connection, settings, owner=True)
                if work_schema_version(connection, settings.schema) == 4:
                    validate_feed_state(connection, settings.schema)
                    return
                connection.execute(sql.SQL("SET LOCAL search_path TO {},pg_catalog").format(schema))
                for statement in FEED_DDL.split(";"):
                    if statement.strip():
                        connection.execute(statement)
                for name in FEED_TABLES:
                    table = sql.Identifier(settings.schema, name)
                    connection.execute(
                        sql.SQL(
                            "REVOKE ALL ON {} FROM PUBLIC,livekit_lab; GRANT SELECT ON {} TO livekit_lab"
                        ).format(table, table)
                    )
                connection.execute(
                    sql.SQL(
                        "GRANT INSERT ON {}.result_feed_heads,{}.result_feed_events TO livekit_lab; GRANT UPDATE(last_sequence) ON {}.result_feed_heads TO livekit_lab"
                    ).format(schema, schema, schema)
                )
                connection.execute(
                    sql.SQL(
                        "INSERT INTO {}.result_feed_source VALUES(true,%s::uuid,floor(extract(epoch FROM clock_timestamp())*1000)::bigint)"
                    ).format(schema),
                    [str(uuid4())],
                )
                # Set-based adoption remains bounded by the existing retained-work
                # and attempt caps. The work admission lock fences all completions.
                ordered = sql.SQL("""
                    SELECT r.tenant_id,r.account_id,r.work_id,r.attempt_id,
                    row_number() OVER (PARTITION BY r.tenant_id,r.account_id
                      ORDER BY r.recorded_at_ms,r.work_id,a.number,r.attempt_id) AS sequence,
                    count(*) OVER (PARTITION BY r.tenant_id,r.account_id) AS tail
                    FROM {}.attempt_results r JOIN {}.issued_attempts a
                    USING(tenant_id,account_id,work_id,attempt_id)
                """).format(schema, schema)
                connection.execute(
                    sql.SQL(
                        "WITH ordered AS ({}) INSERT INTO {}.result_feed_heads SELECT tenant_id,account_id,work_id,tail FROM ordered WHERE sequence=1"
                    ).format(ordered, schema)
                )
                connection.execute(
                    sql.SQL(
                        "WITH ordered AS ({}) INSERT INTO {}.result_feed_events SELECT gen_random_uuid(),tenant_id,account_id,sequence,work_id,attempt_id,'adopted_history' FROM ordered"
                    ).format(ordered, schema)
                )
                connection.execute(
                    sql.SQL(
                        "ALTER TABLE {}.schema_metadata DROP CONSTRAINT schema_metadata_version_check"
                    ).format(schema)
                )
                connection.execute(
                    sql.SQL("UPDATE {}.schema_metadata SET version=4 WHERE singleton").format(
                        schema
                    )
                )
                connection.execute(
                    sql.SQL(
                        "ALTER TABLE {}.schema_metadata ADD CONSTRAINT schema_metadata_version_check CHECK(version=4)"
                    ).format(schema)
                )
                connection.execute(
                    sql.SQL("COMMENT ON SCHEMA {} IS {}").format(schema, sql.Literal(MARKER_V4))
                )
                connection.execute("SET LOCAL search_path TO pg_catalog")
                digest = catalog_sha256(connection, settings.schema)
                connection.execute(
                    sql.SQL(
                        "UPDATE {}.schema_metadata SET definition_sha256=%s,catalog_sha256=%s WHERE singleton"
                    ).format(schema),
                    [DEFINITION_SHA256_V4, digest],
                )
                validate_work_schema(connection, settings, owner=True)
                validate_feed_state(connection, settings.schema)
                if harness_failpoint is not None:
                    harness_failpoint("upgrade_v4.before_commit")
                committing = True
            if harness_failpoint is not None:
                harness_failpoint("upgrade_v4.after_commit")
    except WorkError:
        if committing:
            raise WorkError("acknowledgement_unknown") from None
        raise
    except Exception:  # noqa: BLE001 - owner SQL and cleanup never reflect private details
        raise WorkError(
            "acknowledgement_unknown" if committing else "storage_unavailable"
        ) from None
