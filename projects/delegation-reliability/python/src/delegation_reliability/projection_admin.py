"""Explicit owner-only projection v1 install; serving never performs DDL."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import closing

from psycopg import sql
from psycopg.types.json import Jsonb

from continuity_lab.work_api import PostgresSettings

from .applicability_models import RefreshPolicy, parse_refresh_policy
from .applicability_schema import APPLICABILITY_DDL, MARKER_V3
from .processing_models import CompletionPolicy, parse_policy, snapshot_policy
from .processing_schema import MARKER_V2, PROCESSING_DDL
from .projection_models import ProjectionBinding, ProjectionError, ProjectionLimits
from .projection_store import (
    DDL,
    DEFINITION,
    DEFINITION_V2,
    DEFINITION_V3,
    MARKER,
    catalog,
    settings,
    validate,
)

_DEFAULT_REFRESH_POLICY = RefreshPolicy()

_DEFAULT_LIMITS = ProjectionLimits()


def install_projection_schema(
    value: PostgresSettings,
    *,
    binding: ProjectionBinding,
    limits: ProjectionLimits = _DEFAULT_LIMITS,
) -> None:
    value = settings(value, owner=True)
    if type(binding) is not ProjectionBinding or type(limits) is not ProjectionLimits:
        raise ProjectionError("invalid_input")
    try:
        with (
            closing(value.connect(application_name="continuity-migrate")) as connection,
            connection.transaction(),
        ):
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                ["p3-projection:" + value.schema],
            )
            present = connection.execute(
                "SELECT 1 FROM pg_namespace WHERE nspname=%s", [value.schema]
            ).fetchone()
            if present is not None:
                _point, current_limits = validate(connection, value, owner=True, binding=binding)
                if current_limits != limits:
                    raise ProjectionError("identity_conflict")
                return
            who = connection.execute("SELECT current_user AS name").fetchone()
            if who != {"name": "continuity_migrator"}:
                raise ProjectionError("unauthorized")
            schema = sql.Identifier(value.schema)
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
            connection.execute("SET LOCAL search_path TO pg_catalog")
            connection.execute(
                sql.SQL(
                    "REVOKE ALL ON ALL TABLES IN SCHEMA {} FROM PUBLIC,livekit_lab; GRANT SELECT ON ALL TABLES IN SCHEMA {} TO livekit_lab; GRANT INSERT ON {}.projected_results TO livekit_lab; GRANT UPDATE(sequence,record_count) ON {}.projection_checkpoint TO livekit_lab"
                ).format(schema, schema, schema, schema)
            )
            actual = catalog(connection, value.schema)
            connection.execute(
                sql.SQL("INSERT INTO {}.projection_metadata VALUES(true,1,%s,%s::jsonb,%s)").format(
                    schema
                ),
                [DEFINITION, Jsonb(actual), limits.max_records],
            )
            connection.execute(
                sql.SQL(
                    "INSERT INTO {}.projection_checkpoint VALUES(true,%s::uuid,%s,%s,0,0)"
                ).format(schema),
                [binding.source_id, binding.scope.tenant_id, binding.scope.account_id],
            )
            validate(connection, value, owner=True, binding=binding)
    except ProjectionError:
        raise
    except Exception:  # noqa: BLE001 - fixed safe owner storage boundary
        raise ProjectionError("storage_unavailable") from None


def upgrade_projection_schema_v2(
    value: PostgresSettings,
    *,
    policy: CompletionPolicy,
    harness_failpoint: Callable[[str], None] | None = None,
) -> None:
    """Explicit owner upgrade; retain every v1 row/checkpoint and immutable policy."""
    value = settings(value, owner=True)
    policy = snapshot_policy(policy)
    if harness_failpoint is not None and not callable(harness_failpoint):
        raise ProjectionError("invalid_input")
    committing = False
    try:
        with closing(value.connect(application_name="continuity-migrate")) as connection:
            with connection.transaction():
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                    ["p3-projection:" + value.schema],
                )
                point, _limits = validate(connection, value, owner=True)
                schema = sql.Identifier(value.schema)
                connection.execute(
                    sql.SQL("LOCK TABLE {}.projection_checkpoint IN ACCESS EXCLUSIVE MODE").format(
                        schema
                    )
                )
                point, _limits = validate(connection, value, owner=True)
                version = connection.execute(
                    sql.SQL("SELECT version FROM {}.projection_metadata").format(schema)
                ).fetchone()
                if version in ({"version": 2}, {"version": 3}):
                    existing = connection.execute(
                        sql.SQL("SELECT policy_json FROM {}.processing_control").format(schema)
                    ).fetchall()
                    if (
                        len(existing) != 1
                        or parse_policy(existing[0]["policy_json"].encode()).sha256 != policy.sha256
                    ):
                        raise ProjectionError("identity_conflict")
                    return
                if version != {"version": 1}:
                    raise ProjectionError("schema_mismatch")
                connection.execute(sql.SQL("SET LOCAL search_path TO {},pg_catalog").format(schema))
                for statement in PROCESSING_DDL.split(";"):
                    if statement.strip():
                        connection.execute(statement)
                connection.execute("SET LOCAL search_path TO pg_catalog")
                connection.execute(
                    sql.SQL(
                        "REVOKE ALL ON {}.processing_control,{}.processing_acks FROM PUBLIC,livekit_lab; GRANT SELECT ON {}.processing_control,{}.processing_acks TO livekit_lab; GRANT INSERT ON {}.processing_acks TO livekit_lab; GRANT UPDATE(revision,terminal_watermark,scan_after,terminal_count) ON {}.processing_control TO livekit_lab"
                    ).format(*[schema] * 6)
                )
                connection.execute(
                    sql.SQL("INSERT INTO {}.processing_control VALUES(true,%s,%s,0,0,0,0)").format(
                        schema
                    ),
                    [policy.canonical().decode(), policy.sha256],
                )
                connection.execute(
                    sql.SQL(
                        "ALTER TABLE {}.projection_metadata DROP CONSTRAINT projection_metadata_version_check"
                    ).format(schema)
                )
                connection.execute(
                    sql.SQL("UPDATE {}.projection_metadata SET version=2 WHERE singleton").format(
                        schema
                    )
                )
                connection.execute(
                    sql.SQL(
                        "ALTER TABLE {}.projection_metadata ADD CONSTRAINT projection_metadata_version_check CHECK(version=2)"
                    ).format(schema)
                )
                connection.execute(
                    sql.SQL("COMMENT ON SCHEMA {} IS {}").format(schema, sql.Literal(MARKER_V2))
                )
                connection.execute(
                    sql.SQL(
                        "UPDATE {}.projection_metadata SET definition_sha256=%s,catalog_snapshot=%s::jsonb WHERE singleton"
                    ).format(schema),
                    [DEFINITION_V2, Jsonb(catalog(connection, value.schema))],
                )
                validate(connection, value, owner=True, binding=point.binding)
                if harness_failpoint is not None:
                    harness_failpoint("processing.upgrade.before_commit")
                committing = True
            if harness_failpoint is not None:
                harness_failpoint("processing.upgrade.after_commit")
    except ProjectionError:
        if committing:
            raise ProjectionError("acknowledgement_unknown") from None
        raise
    except Exception:  # noqa: BLE001 - safe owner transaction acknowledgement boundary
        raise ProjectionError(
            "acknowledgement_unknown" if committing else "storage_unavailable"
        ) from None


def upgrade_projection_schema_v3(
    value: PostgresSettings,
    *,
    policy: RefreshPolicy = _DEFAULT_REFRESH_POLICY,
    harness_failpoint: Callable[[str], None] | None = None,
) -> None:
    """Explicit quiescent owner upgrade; retain all old rows and fixed refresh policy."""
    value = settings(value, owner=True)
    if type(policy) is not RefreshPolicy or (
        harness_failpoint is not None and not callable(harness_failpoint)
    ):
        raise ProjectionError("invalid_input")
    policy = parse_refresh_policy(policy.canonical())
    committing = False
    try:
        with closing(value.connect(application_name="continuity-migrate")) as c:
            with c.transaction():
                c.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                    ["p3-projection:" + value.schema],
                )
                point, _limits = validate(c, value, owner=True)
                schema = sql.Identifier(value.schema)
                version = c.execute(
                    sql.SQL("SELECT version FROM {}.projection_metadata").format(schema)
                ).fetchone()
                if version not in ({"version": 2}, {"version": 3}):
                    raise ProjectionError("schema_mismatch")
                # Keep existing processor control-before-projection lock ordering.
                # Upgrade still requires explicit owner maintenance/quiescence.
                c.execute(
                    sql.SQL(
                        "LOCK TABLE {}.processing_control,{}.projection_checkpoint IN ACCESS EXCLUSIVE MODE"
                    ).format(schema, schema)
                )
                validate(c, value, owner=True, binding=point.binding)
                version = c.execute(
                    sql.SQL("SELECT version FROM {}.projection_metadata").format(schema)
                ).fetchone()
                if version == {"version": 3}:
                    existing = c.execute(
                        sql.SQL("SELECT policy_json FROM {}.refresh_control").format(schema)
                    ).fetchall()
                    if (
                        len(existing) != 1
                        or parse_refresh_policy(existing[0]["policy_json"].encode()).sha256
                        != policy.sha256
                    ):
                        raise ProjectionError("identity_conflict")
                    return
                if version != {"version": 2}:
                    raise ProjectionError("schema_mismatch")
                c.execute(sql.SQL("SET LOCAL search_path TO {},pg_catalog").format(schema))
                for statement in APPLICABILITY_DDL.split(";"):
                    if statement.strip():
                        c.execute(statement)
                c.execute("SET LOCAL search_path TO pg_catalog")
                c.execute(
                    sql.SQL(
                        "REVOKE ALL ON {}.refresh_control,{}.applicability_heads,{}.applicability_refreshes FROM PUBLIC,livekit_lab; GRANT SELECT ON {}.refresh_control,{}.applicability_heads,{}.applicability_refreshes TO livekit_lab; GRANT INSERT ON {}.applicability_heads,{}.applicability_refreshes TO livekit_lab; GRANT UPDATE(command_count) ON {}.refresh_control TO livekit_lab; GRANT UPDATE(revision,latest_command_id,tombstone_json,tombstone_sha256) ON {}.applicability_heads TO livekit_lab"
                    ).format(*[schema] * 10)
                )
                c.execute(
                    sql.SQL("INSERT INTO {}.refresh_control VALUES(true,%s,%s,0)").format(schema),
                    [policy.canonical().decode(), policy.sha256],
                )
                c.execute(
                    sql.SQL(
                        "ALTER TABLE {}.projection_metadata DROP CONSTRAINT projection_metadata_version_check"
                    ).format(schema)
                )
                c.execute(
                    sql.SQL("UPDATE {}.projection_metadata SET version=3 WHERE singleton").format(
                        schema
                    )
                )
                c.execute(
                    sql.SQL(
                        "ALTER TABLE {}.projection_metadata ADD CONSTRAINT projection_metadata_version_check CHECK(version=3)"
                    ).format(schema)
                )
                c.execute(
                    sql.SQL("COMMENT ON SCHEMA {} IS {}").format(schema, sql.Literal(MARKER_V3))
                )
                c.execute(
                    sql.SQL(
                        "UPDATE {}.projection_metadata SET definition_sha256=%s,catalog_snapshot=%s::jsonb WHERE singleton"
                    ).format(schema),
                    [DEFINITION_V3, Jsonb(catalog(c, value.schema))],
                )
                validate(c, value, owner=True, binding=point.binding)
                if harness_failpoint is not None:
                    harness_failpoint("applicability.upgrade.before_commit")
                committing = True
            if harness_failpoint is not None:
                harness_failpoint("applicability.upgrade.after_commit")
    except ProjectionError:
        if committing:
            raise ProjectionError("acknowledgement_unknown") from None
        raise
    except Exception:  # noqa: BLE001 - bounded safe owner transaction acknowledgement boundary
        raise ProjectionError(
            "acknowledgement_unknown" if committing else "storage_unavailable"
        ) from None
