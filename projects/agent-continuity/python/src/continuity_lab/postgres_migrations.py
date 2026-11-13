"""Owner-only PostgreSQL staging/import and read-only schema verification.

SQLite quiescence/cutover is coordinated elsewhere. This module commits only the
target transaction and cannot prove a cross-database atomic switch.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

import psycopg
from psycopg import sql

from . import postgres_schema_v2 as v2
from . import postgres_schema_v3 as v3
from . import postgres_schema_v4 as v4
from .execution_codec import decode_attempt, decode_execution
from .execution_models import (
    AttemptStatus,
    ExecutionStatus,
    InvalidStoredState,
    UnsupportedOperation,
)
from .migrations import MigrationError, SchemaVersionError
from .models import BookingChange, IdempotencyConflict
from .postgres_settings import PostgresSettings, advisory_keys
from .transfer import TransferSnapshot, snapshot_digest

if TYPE_CHECKING:
    from .lease_models import CoordinationPolicy

LOGGER = logging.getLogger("continuity_lab.postgres_migrations")
LOGGER.addHandler(logging.NullHandler())
SCHEMA_VERSION = 1
MIGRATOR_ROLE = "continuity_migrator"
RUNTIME_ROLE = "livekit_lab"
LATEST_SCHEMA_VERSION = 4

_COLUMNS = {
    "tasks": (
        "task_id",
        "scope_id",
        "idempotency_key",
        "payload",
        "status",
        "created_at",
    ),
    "executions": (
        "task_id",
        "operation",
        "status",
        "effect_id",
        "version",
        "created_at",
        "updated_at",
        "result_json",
        "error_code",
    ),
    "execution_attempts": (
        "attempt_id",
        "task_id",
        "attempt_no",
        "status",
        "started_at",
        "finished_at",
        "error_code",
    ),
    "schema_metadata": (
        "singleton",
        "version",
        "state",
        "migration_id",
        "source_digest",
    ),
}

_DEFINITIONS = {
    "tasks": """(
        task_id TEXT COLLATE "C" CONSTRAINT tasks_pk PRIMARY KEY,
        scope_id TEXT COLLATE "C" NOT NULL,
        idempotency_key TEXT COLLATE "C" NOT NULL,
        payload TEXT COLLATE "C" NOT NULL,
        status TEXT COLLATE "C" NOT NULL,
        created_at TEXT COLLATE "C" NOT NULL,
        CONSTRAINT tasks_scoped_key UNIQUE (scope_id, idempotency_key),
        CONSTRAINT tasks_status CHECK (status = 'queued')
    )""",
    "executions": """(
        task_id TEXT COLLATE "C" CONSTRAINT executions_pk PRIMARY KEY,
        operation TEXT COLLATE "C" NOT NULL,
        status TEXT COLLATE "C" NOT NULL,
        effect_id TEXT COLLATE "C" NOT NULL,
        version BIGINT NOT NULL,
        created_at TEXT COLLATE "C" NOT NULL,
        updated_at TEXT COLLATE "C" NOT NULL,
        result_json TEXT COLLATE "C",
        error_code TEXT COLLATE "C",
        CONSTRAINT executions_task_fk FOREIGN KEY (task_id) REFERENCES {schema}.tasks(task_id),
        CONSTRAINT executions_effect_key UNIQUE (effect_id),
        CONSTRAINT executions_operation CHECK (operation = 'booking.inquire'),
        CONSTRAINT executions_status CHECK (status IN ('accepted', 'running', 'succeeded', 'failed')),
        CONSTRAINT executions_version CHECK (version >= 0),
        CONSTRAINT executions_outcome CHECK (
            (status IN ('accepted', 'running') AND result_json IS NULL AND error_code IS NULL)
            OR (status = 'succeeded' AND result_json IS NOT NULL AND error_code IS NULL)
            OR (status = 'failed' AND result_json IS NULL AND error_code IS NOT NULL)
        ),
        CONSTRAINT executions_error CHECK (error_code IS NULL OR length(error_code) BETWEEN 1 AND 64)
    )""",
    "execution_attempts": """(
        attempt_id TEXT COLLATE "C" CONSTRAINT execution_attempts_pk PRIMARY KEY,
        task_id TEXT COLLATE "C" NOT NULL,
        attempt_no BIGINT NOT NULL,
        status TEXT COLLATE "C" NOT NULL,
        started_at TEXT COLLATE "C" NOT NULL,
        finished_at TEXT COLLATE "C",
        error_code TEXT COLLATE "C",
        CONSTRAINT attempts_execution_fk FOREIGN KEY (task_id) REFERENCES {schema}.executions(task_id),
        CONSTRAINT attempts_sequence_key UNIQUE (task_id, attempt_no),
        CONSTRAINT attempts_number CHECK (attempt_no >= 1),
        CONSTRAINT attempts_status CHECK (status IN ('started', 'succeeded', 'failed', 'interrupted')),
        CONSTRAINT attempts_outcome CHECK (
            (status = 'started' AND finished_at IS NULL AND error_code IS NULL)
            OR (status IN ('succeeded', 'interrupted') AND finished_at IS NOT NULL AND error_code IS NULL)
            OR (status = 'failed' AND finished_at IS NOT NULL AND error_code IS NOT NULL)
        ),
        CONSTRAINT attempts_error CHECK (error_code IS NULL OR length(error_code) BETWEEN 1 AND 64)
    )""",
    "schema_metadata": """(
        singleton BOOLEAN CONSTRAINT schema_metadata_pk PRIMARY KEY,
        version INTEGER NOT NULL,
        state TEXT COLLATE "C" NOT NULL,
        migration_id TEXT COLLATE "C",
        source_digest TEXT COLLATE "C",
        CONSTRAINT metadata_singleton CHECK (singleton),
        CONSTRAINT metadata_version CHECK (version = 1),
        CONSTRAINT metadata_state CHECK (state IN ('staging', 'active')),
        CONSTRAINT metadata_pair CHECK ((migration_id IS NULL) = (source_digest IS NULL)),
        CONSTRAINT metadata_active CHECK (state <> 'active' OR migration_id IS NOT NULL),
        CONSTRAINT metadata_digest CHECK (source_digest IS NULL OR source_digest ~ '^[0-9a-f]{{64}}$')
    )""",
}

# PostgreSQL 18's canonical CHECK output, verified against the pinned local
# server. Whitespace/keyword case may differ; quoted values retain exact case.
_CHECK_DEFINITIONS: dict[str, str] = {
    "attempts_error": "CHECK (((error_code IS NULL) OR ((length(error_code) >= 1) AND "
    "(length(error_code) <= 64))))",
    "attempts_number": "CHECK ((attempt_no >= 1))",
    "attempts_outcome": "CHECK ((((status = 'started'::text) AND (finished_at IS NULL) AND "
    "(error_code IS NULL)) OR ((status = ANY (ARRAY['succeeded'::text, "
    "'interrupted'::text])) AND (finished_at IS NOT NULL) AND (error_code IS "
    "NULL)) OR ((status = 'failed'::text) AND (finished_at IS NOT NULL) AND "
    "(error_code IS NOT NULL))))",
    "attempts_status": "CHECK ((status = ANY (ARRAY['started'::text, 'succeeded'::text, "
    "'failed'::text, 'interrupted'::text])))",
    "executions_error": "CHECK (((error_code IS NULL) OR ((length(error_code) >= 1) AND "
    "(length(error_code) <= 64))))",
    "executions_operation": "CHECK ((operation = 'booking.inquire'::text))",
    "executions_outcome": "CHECK ((((status = ANY (ARRAY['accepted'::text, 'running'::text])) AND "
    "(result_json IS NULL) AND (error_code IS NULL)) OR ((status = "
    "'succeeded'::text) AND (result_json IS NOT NULL) AND (error_code IS "
    "NULL)) OR ((status = 'failed'::text) AND (result_json IS NULL) AND "
    "(error_code IS NOT NULL))))",
    "executions_status": "CHECK ((status = ANY (ARRAY['accepted'::text, 'running'::text, "
    "'succeeded'::text, 'failed'::text])))",
    "executions_version": "CHECK ((version >= 0))",
    "metadata_active": "CHECK (((state <> 'active'::text) OR (migration_id IS NOT NULL)))",
    "metadata_digest": "CHECK (((source_digest IS NULL) OR (source_digest ~ "
    "'^[0-9a-f]{64}$'::text)))",
    "metadata_pair": "CHECK (((migration_id IS NULL) = (source_digest IS NULL)))",
    "metadata_singleton": "CHECK (singleton)",
    "metadata_state": "CHECK ((state = ANY (ARRAY['staging'::text, 'active'::text])))",
    "metadata_version": "CHECK ((version = 1))",
    "tasks_status": "CHECK ((status = 'queued'::text))",
}

_KEYS = {
    "tasks_pk": ("tasks", "p", ("task_id",)),
    "tasks_scoped_key": ("tasks", "u", ("scope_id", "idempotency_key")),
    "executions_pk": ("executions", "p", ("task_id",)),
    "executions_effect_key": ("executions", "u", ("effect_id",)),
    "execution_attempts_pk": ("execution_attempts", "p", ("attempt_id",)),
    "attempts_sequence_key": ("execution_attempts", "u", ("task_id", "attempt_no")),
    "schema_metadata_pk": ("schema_metadata", "p", ("singleton",)),
}
_FOREIGN_KEYS = {
    "executions_task_fk": ("executions", ("task_id",), "tasks", ("task_id",)),
    "attempts_execution_fk": (
        "execution_attempts",
        ("task_id",),
        "executions",
        ("task_id",),
    ),
}


@dataclass(frozen=True, slots=True)
class _Catalog:
    columns: dict[str, tuple[str, ...]]
    column_specs: dict[str, dict[str, tuple[str, bool]]]
    checks: dict[str, str]
    check_tables: dict[str, str]
    keys: dict[str, tuple[str, str, tuple[str, ...]]]
    foreign_keys: dict[str, tuple[str, tuple[str, ...], str, tuple[str, ...]]]
    grants: dict[str, tuple[str, ...]]
    operating_indexes: dict[str, tuple[str, tuple[str, ...]]]


def _catalog(version: int) -> _Catalog:
    if type(version) is not int or version not in {1, 2, 3, 4}:
        raise SchemaVersionError("PostgreSQL schema version is unsupported")
    columns: dict[str, tuple[str, ...]] = dict(_COLUMNS)
    specs: dict[str, dict[str, tuple[str, bool]]] = {}
    optional = {
        "result_json",
        "error_code",
        "finished_at",
        "migration_id",
        "source_digest",
    }
    for table, names in columns.items():
        specs[table] = {
            name: (
                "boolean"
                if name == "singleton"
                else "integer"
                if table == "schema_metadata" and name == "version"
                else "bigint"
                if name in {"version", "attempt_no"}
                else "text",
                name not in optional,
            )
            for name in names
        }
    checks = dict(_CHECK_DEFINITIONS)
    check_tables = {
        name: {
            "tasks": "tasks",
            "executions": "executions",
            "attempts": "execution_attempts",
            "metadata": "schema_metadata",
        }[name.split("_", 1)[0]]
        for name in checks
    }
    keys: dict[str, tuple[str, str, tuple[str, ...]]] = dict(_KEYS)
    foreign_keys: dict[str, tuple[str, tuple[str, ...], str, tuple[str, ...]]] = dict(_FOREIGN_KEYS)
    grants: dict[str, tuple[str, ...]] = {
        table: ("SELECT",) if table == "schema_metadata" else ("SELECT", "INSERT", "UPDATE")
        for table in columns
    }
    operating_indexes: dict[str, tuple[str, tuple[str, ...]]] = {}
    if version >= 2:
        operating_indexes.update(v2.OPERATING_INDEXES)
        columns.update(v2.COLUMNS)
        specs.update(v2.COLUMN_SPECS)
        checks.update(v2.CHECK_DEFINITIONS)
        check_tables.update(v2.CHECK_TABLES)
        keys.update(v2.KEYS)
        foreign_keys.update(v2.FOREIGN_KEYS)
        grants.update(v2.GRANTS)
    if version >= 3:
        operating_indexes.update(v3.OPERATING_INDEXES)
        columns.update(v3.COLUMNS)
        specs.update(v3.COLUMN_SPECS)
        checks.update(v3.CHECK_DEFINITIONS)
        check_tables.update(v3.CHECK_TABLES)
        keys.update(v3.KEYS)
        foreign_keys.update(v3.FOREIGN_KEYS)
        grants.update(v3.GRANTS)
    if version >= 4:
        operating_indexes.update(v4.OPERATING_INDEXES)
        columns.update(v4.COLUMNS)
        specs.update(v4.COLUMN_SPECS)
        checks.update(v4.CHECK_DEFINITIONS)
        check_tables.update(v4.CHECK_TABLES)
        keys.update(v4.KEYS)
        foreign_keys.update(v4.FOREIGN_KEYS)
        grants.update(v4.GRANTS)
    return _Catalog(
        columns,
        specs,
        checks,
        check_tables,
        keys,
        foreign_keys,
        grants,
        operating_indexes,
    )


def _declared_version(connection: psycopg.Connection[dict[str, Any]], schema: str) -> int:
    # Select a profile only from a plain owned table/INTEGER column. Reading an
    # unexpected view or RLS expression first could execute drifted SQL before
    # the complete catalog verifier gets a chance to reject its structure.
    shape = connection.execute(
        "SELECT c.relkind,c.relpersistence,c.relrowsecurity,c.relforcerowsecurity,pg_get_userbyid(c.relowner) AS owner,a.atttypid,a.attnotnull,a.attgenerated,a.attidentity,a.atthasdef FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_attribute a ON a.attrelid=c.oid WHERE n.nspname=%s AND c.relname='schema_metadata' AND a.attname='version' AND a.attnum>0 AND NOT a.attisdropped",
        (schema,),
    ).fetchone()
    if (
        shape is None
        or shape["relkind"] != "r"
        or shape["relpersistence"] != "p"
        or shape["relrowsecurity"]
        or shape["relforcerowsecurity"]
        or shape["owner"] != MIGRATOR_ROLE
        or shape["atttypid"] != 23
        or not shape["attnotnull"]
        or shape["attgenerated"]
        or shape["attidentity"]
        or shape["atthasdef"]
    ):
        raise SchemaVersionError("PostgreSQL version metadata structure is unsupported")
    rows = connection.execute(
        sql.SQL("SELECT version FROM {}.schema_metadata").format(sql.Identifier(schema))
    ).fetchall()
    if (
        len(rows) != 1
        or type(rows[0]["version"]) is not int
        or rows[0]["version"] not in {1, 2, 3, 4}
    ):
        raise SchemaVersionError("PostgreSQL schema metadata is unsupported")
    return rows[0]["version"]


@dataclass(frozen=True, slots=True)
class ImportState:
    version: int
    state: str
    migration_id: str | None
    source_digest: str | None


@dataclass(frozen=True, slots=True)
class ImportReport:
    migration_id: str
    source_digest: str
    changed: bool
    tasks: int
    executions: int
    attempts: int
    state: str


def _event(event: str, code: str = "ok") -> None:
    LOGGER.info(event, extra={"event": event, "code": code})


def _identifier(value: str) -> str:
    if type(value) is not str or not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", value):
        raise MigrationError("PostgreSQL identifier is invalid")
    return value


def _normalize_sql(value: str) -> str:
    return "".join(
        part if index % 2 else re.sub(r"\s+", "", part).casefold()
        for index, part in enumerate(re.split(r"('(?:''|[^'])*')", value))
    )


def _restricted_role(connection: psycopg.Connection[dict[str, Any]], role: str) -> None:
    row = connection.execute(
        """SELECT r.rolsuper,r.rolcreatedb,r.rolcreaterole,r.rolreplication,r.rolbypassrls,
                  EXISTS(SELECT 1 FROM pg_auth_members m WHERE m.member=r.oid) AS memberships
             FROM pg_roles r WHERE r.rolname=%s""",
        (role,),
    ).fetchone()
    flags = ("rolsuper", "rolcreatedb", "rolcreaterole", "rolreplication", "rolbypassrls")
    if row is None or any(row[name] for name in flags):
        raise SchemaVersionError("Restricted PostgreSQL roles are required")
    if row["memberships"]:
        raise SchemaVersionError("Inherited PostgreSQL administration is unsupported")


def _owner(connection: psycopg.Connection[dict[str, Any]]) -> None:
    row = connection.execute("SELECT current_user AS role").fetchone()
    if row is None or row["role"] != MIGRATOR_ROLE:
        raise MigrationError("The one-shot migration principal is required")
    _restricted_role(connection, MIGRATOR_ROLE)


def _admission_lock(connection: psycopg.Connection[dict[str, Any]], schema: str) -> None:
    connection.execute("SELECT pg_advisory_xact_lock(%s,%s)", advisory_keys(schema, "admission"))


def _validate_privileges(
    connection: psycopg.Connection[dict[str, Any]], schema: str, catalog: _Catalog
) -> None:
    """Fail closed when grants could bypass the staging gate or change structure."""
    _restricted_role(connection, RUNTIME_ROLE)
    row = connection.execute(
        "SELECT has_database_privilege(%s,current_database(),'CONNECT') AS connect,has_database_privilege(%s,current_database(),'CREATE') AS create,has_database_privilege(%s,current_database(),'TEMPORARY') AS temporary",
        (RUNTIME_ROLE, RUNTIME_ROLE, RUNTIME_ROLE),
    ).fetchone()
    if row is None or not row["connect"] or row["create"] or row["temporary"]:
        raise SchemaVersionError("PostgreSQL runtime database privileges are unsupported")
    grants = connection.execute(
        "SELECT a.privilege_type,a.is_grantable,r.rolname FROM pg_namespace n CROSS JOIN LATERAL aclexplode(COALESCE(n.nspacl,acldefault('n',n.nspowner))) a LEFT JOIN pg_roles r ON r.oid=a.grantee WHERE n.nspname=%s AND a.grantee<>n.nspowner",
        (schema,),
    ).fetchall()
    if {(r["rolname"], r["privilege_type"], r["is_grantable"]) for r in grants} != {
        (RUNTIME_ROLE, "USAGE", False)
    }:
        raise SchemaVersionError("PostgreSQL runtime schema privileges are unsupported")
    grants = connection.execute(
        "SELECT c.relname,a.privilege_type,a.is_grantable,r.rolname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace CROSS JOIN LATERAL aclexplode(COALESCE(c.relacl,acldefault('r',c.relowner))) a LEFT JOIN pg_roles r ON r.oid=a.grantee WHERE n.nspname=%s AND c.relkind='r' AND a.grantee<>c.relowner",
        (schema,),
    ).fetchall()
    expected = {
        (table, RUNTIME_ROLE, privilege, False)
        for table, privileges in catalog.grants.items()
        for privilege in privileges
    }
    if {
        (r["relname"], r["rolname"], r["privilege_type"], r["is_grantable"]) for r in grants
    } != expected:
        raise SchemaVersionError("PostgreSQL runtime table privileges are unsupported")
    if connection.execute(
        "SELECT 1 FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND a.attacl IS NOT NULL LIMIT 1",
        (schema,),
    ).fetchone():
        raise SchemaVersionError("PostgreSQL column privileges are unsupported")
    defaults = connection.execute(
        "SELECT d.defaclnamespace,a.privilege_type,a.is_grantable,r.rolname FROM pg_default_acl d CROSS JOIN LATERAL aclexplode(d.defaclacl) a LEFT JOIN pg_roles r ON r.oid=a.grantee WHERE d.defaclrole=(SELECT oid FROM pg_roles WHERE rolname=%s) AND d.defaclobjtype='r' AND (d.defaclnamespace=0 OR d.defaclnamespace=(SELECT oid FROM pg_namespace WHERE nspname=%s)) AND a.grantee<>d.defaclrole",
        (MIGRATOR_ROLE, schema),
    ).fetchall()
    if {(r["rolname"], r["privilege_type"], r["is_grantable"]) for r in defaults} != {
        (RUNTIME_ROLE, "SELECT", False)
    } or any(r["defaclnamespace"] == 0 for r in defaults):
        raise SchemaVersionError("PostgreSQL future table privileges are unsupported")


def _validate_columns(
    connection: psycopg.Connection[dict[str, Any]], schema: str, catalog: _Catalog
) -> None:
    """Read the current columns together; retain every per-table shape check."""
    rows = connection.execute(
        """SELECT t.relname AS table_name,a.attname,format_type(a.atttypid,a.atttypmod) AS kind,
                  a.attnotnull,c.collname,a.attidentity,a.attgenerated,a.atthasdef
             FROM pg_attribute a JOIN pg_class t ON t.oid=a.attrelid
             JOIN pg_namespace n ON n.oid=t.relnamespace
             LEFT JOIN pg_collation c ON c.oid=a.attcollation
            WHERE n.nspname=%s AND t.relname=ANY(%s) AND a.attnum>0 AND NOT a.attisdropped
            ORDER BY t.relname,a.attnum""",
        (schema, list(catalog.columns)),
    ).fetchall()
    grouped: dict[str, list[dict[str, Any]]] = {table: [] for table in catalog.columns}
    for row in rows:
        grouped[row["table_name"]].append(row)
    for table, columns in catalog.columns.items():
        actual = grouped[table]
        if tuple(row["attname"] for row in actual) != columns:
            raise SchemaVersionError("PostgreSQL columns are unsupported")
        for row in actual:
            expected_type, not_null = catalog.column_specs[table][row["attname"]]
            if (
                row["kind"] != expected_type
                or row["attnotnull"] != not_null
                or row["attidentity"]
                or row["attgenerated"]
                or row["atthasdef"]
                or (expected_type == "text" and row["collname"] != "C")
            ):
                raise SchemaVersionError("PostgreSQL column constraints are unsupported")


def validate_schema(
    connection: psycopg.Connection[dict[str, Any]],
    schema: str,
    *,
    require_active: bool = True,
    minimum_version: int = 1,
) -> None:
    """Validate a declared supported catalog and gate without serving DDL/repair."""
    _identifier(schema)
    try:
        if not 180000 <= connection.info.server_version < 190000:
            raise SchemaVersionError("This schema verifier requires the supported PostgreSQL major")
        owner = connection.execute(
            "SELECT pg_get_userbyid(nspowner) AS owner FROM pg_namespace WHERE nspname=%s",
            (schema,),
        ).fetchone()
        if owner is None or owner["owner"] != MIGRATOR_ROLE:
            raise SchemaVersionError("PostgreSQL schema ownership is unsupported")
        _restricted_role(connection, MIGRATOR_ROLE)
        current = connection.execute("SELECT current_user AS role").fetchone()
        assert current is not None
        _restricted_role(connection, current["role"])
        version = _declared_version(connection, schema)
        catalog = _catalog(version)
        if (
            type(minimum_version) is not int
            or minimum_version not in {1, 2, 3, 4}
            or version < minimum_version
        ):
            raise SchemaVersionError("PostgreSQL schema upgrade is required")
        _validate_privileges(connection, schema, catalog)
        relations = connection.execute(
            "SELECT c.relname,c.relkind,c.relpersistence,pg_get_userbyid(c.relowner) AS owner,c.relrowsecurity,c.relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s",
            (schema,),
        ).fetchall()
        expected = {
            **dict.fromkeys(catalog.columns, "r"),
            **dict.fromkeys(catalog.keys, "i"),
            **dict.fromkeys(catalog.operating_indexes, "i"),
        }
        if {row["relname"]: row["relkind"] for row in relations} != expected or any(
            row["owner"] != MIGRATOR_ROLE
            or row["relpersistence"] != "p"
            or row["relrowsecurity"]
            or row["relforcerowsecurity"]
            for row in relations
        ):
            raise SchemaVersionError("PostgreSQL relation structure is unsupported")
        indexes = connection.execute(
            "SELECT c.relname,t.relname AS table_name,i.indisunique,i.indisprimary,i.indisvalid,i.indisready,i.indislive,i.indimmediate,i.indnkeyatts,i.indnatts,i.indexprs IS NULL AS plain,i.indpred IS NULL AS complete,am.amname,ARRAY(SELECT a.attname FROM unnest(i.indkey) WITH ORDINALITY k(num,ord) JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.num ORDER BY k.ord) AS columns,ARRAY(SELECT o FROM unnest(i.indoption) o) AS options FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_class t ON t.oid=i.indrelid JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_am am ON am.oid=c.relam WHERE n.nspname=%s",
            (schema,),
        ).fetchall()
        for row in indexes:
            if row["relname"] in catalog.keys:
                table_name, constraint_kind, expected_columns = catalog.keys[row["relname"]]
                unique, primary = True, constraint_kind == "p"
            else:
                table_name, expected_columns = catalog.operating_indexes[row["relname"]]
                unique, primary = False, False
            if (
                not all(
                    row[name]
                    for name in (
                        "indisvalid",
                        "indisready",
                        "indislive",
                        "indimmediate",
                        "plain",
                        "complete",
                    )
                )
                or row["indisunique"] != unique
                or row["indisprimary"] != primary
                or row["table_name"] != table_name
                or tuple(row["columns"]) != expected_columns
                or row["options"] != [0] * len(expected_columns)
                or row["indnkeyatts"] != len(expected_columns)
                or row["indnatts"] != len(expected_columns)
                or row["amname"] != "btree"
            ):
                raise SchemaVersionError("PostgreSQL indexes are unsupported")
        if connection.execute(
            "SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=%s LIMIT 1",
            (schema,),
        ).fetchone():
            raise SchemaVersionError("Unexpected PostgreSQL routines are unsupported")
        if connection.execute(
            "SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND (NOT t.tgisinternal OR t.tgenabled <> 'O') LIMIT 1",
            (schema,),
        ).fetchone():
            raise SchemaVersionError("Unexpected PostgreSQL triggers are unsupported")
        if connection.execute(
            "SELECT 1 FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND a.attisdropped LIMIT 1",
            (schema,),
        ).fetchone():
            raise SchemaVersionError("PostgreSQL dropped columns are unsupported")
        _validate_columns(connection, schema, catalog)
        constraints = connection.execute(
            """SELECT x.conname,x.contype,x.convalidated,x.conenforced,x.condeferrable,x.condeferred,t.relname AS table_name,
            pg_get_constraintdef(x.oid) AS definition,
            ARRAY(SELECT a.attname FROM unnest(x.conkey) WITH ORDINALITY k(num,ord) JOIN pg_attribute a ON a.attrelid=x.conrelid AND a.attnum=k.num ORDER BY k.ord) AS columns,
            rt.relname AS reference_table,rn.nspname AS reference_schema,
            ARRAY(SELECT a.attname FROM unnest(x.confkey) WITH ORDINALITY k(num,ord) JOIN pg_attribute a ON a.attrelid=x.confrelid AND a.attnum=k.num ORDER BY k.ord) AS reference_columns,
            x.confupdtype,x.confdeltype,x.confmatchtype
            FROM pg_constraint x JOIN pg_class t ON t.oid=x.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace
            LEFT JOIN pg_class rt ON rt.oid=x.confrelid LEFT JOIN pg_namespace rn ON rn.oid=rt.relnamespace
            WHERE n.nspname=%s""",
            (schema,),
        ).fetchall()
        structural = [row for row in constraints if row["contype"] != "n"]
        expected_constraints = set(catalog.checks) | set(catalog.keys) | set(catalog.foreign_keys)
        if (
            len(structural) != len(expected_constraints)
            or {row["conname"] for row in structural} != expected_constraints
        ):
            raise SchemaVersionError("PostgreSQL constraints are unsupported")
        for row in constraints:
            if (
                not row["convalidated"]
                or not row["conenforced"]
                or row["condeferrable"]
                or row["condeferred"]
            ):
                raise SchemaVersionError("PostgreSQL constraint enforcement is unsupported")
            name = row["conname"]
            if row["contype"] == "n":
                continue
            if name in catalog.checks:
                check_table = catalog.check_tables[name]
                if (
                    row["table_name"] != check_table
                    or row["contype"] != "c"
                    or _normalize_sql(row["definition"]) != _normalize_sql(catalog.checks[name])
                ):
                    raise SchemaVersionError("PostgreSQL CHECK constraints are unsupported")
            elif name in catalog.keys:
                if (
                    row["table_name"],
                    row["contype"],
                    tuple(row["columns"]),
                ) != catalog.keys[name]:
                    raise SchemaVersionError("PostgreSQL identity constraints are unsupported")
            elif name in catalog.foreign_keys and (
                (
                    row["table_name"],
                    tuple(row["columns"]),
                    row["reference_table"],
                    tuple(row["reference_columns"]),
                )
                != catalog.foreign_keys[name]
                or row["reference_schema"] != schema
                or (row["confupdtype"], row["confdeltype"], row["confmatchtype"]) != ("a", "a", "s")
            ):
                raise SchemaVersionError("PostgreSQL foreign keys are unsupported")
        rows = connection.execute(
            sql.SQL("SELECT * FROM {}.schema_metadata").format(sql.Identifier(schema))
        ).fetchall()
        if len(rows) != 1 or rows[0]["singleton"] is not True or rows[0]["version"] != version:
            raise SchemaVersionError("PostgreSQL schema metadata is unsupported")
        metadata = rows[0]
        if (
            (version >= 2 and metadata["state"] != "active")
            or metadata["state"] not in {"staging", "active"}
            or (require_active and metadata["state"] != "active")
        ):
            raise SchemaVersionError("PostgreSQL cutover is not active")
        if (metadata["migration_id"] is None) != (metadata["source_digest"] is None):
            raise SchemaVersionError("PostgreSQL migration identity is invalid")
        if metadata["migration_id"] is not None:
            try:
                if str(UUID(metadata["migration_id"])) != metadata["migration_id"]:
                    raise ValueError("noncanonical identity")
            except (ValueError, TypeError, AttributeError) as error:
                raise SchemaVersionError("PostgreSQL migration identity is invalid") from error
        if metadata["source_digest"] is not None and not re.fullmatch(
            r"[a-f0-9]{64}", metadata["source_digest"]
        ):
            raise SchemaVersionError("PostgreSQL source digest is invalid")
        if version >= 4:
            rows = connection.execute(
                sql.SQL("SELECT * FROM {}.execution_limits").format(sql.Identifier(schema))
            ).fetchall()
            if len(rows) != 1 or rows[0]["singleton"] is not True:
                raise SchemaVersionError("PostgreSQL coordination policy is unavailable")
            limits = rows[0]
            if (
                any(
                    type(limits[name]) is not int
                    for name in (
                        "maximum_pending",
                        "maximum_active",
                        "maximum_records",
                        "lease_seconds",
                    )
                )
                or not 1 <= limits["maximum_pending"] <= 100000
                or not 1 <= limits["maximum_active"] <= min(64, limits["maximum_pending"])
                or not limits["maximum_pending"] <= limits["maximum_records"] <= 1000000
                or not 1 <= limits["lease_seconds"] <= 300
            ):
                raise SchemaVersionError("PostgreSQL coordination policy is unsupported")
    except psycopg.Error as error:
        raise SchemaVersionError("PostgreSQL schema could not be verified") from error


def install_schema(settings: PostgresSettings, *, runtime_role: str = RUNTIME_ROLE) -> None:
    """Create the supported schema under the explicit restricted migration role."""
    schema, runtime_role = _identifier(settings.schema), _identifier(runtime_role)
    if runtime_role != RUNTIME_ROLE:
        raise MigrationError("The fixed restricted runtime principal is required")
    try:
        with (
            settings.connect(application_name="continuity-migrate") as connection,
            connection.transaction(),
        ):
            _owner(connection)
            _restricted_role(connection, runtime_role)
            _admission_lock(connection, schema)
            exists = connection.execute(
                "SELECT 1 FROM pg_namespace WHERE nspname=%s", (schema,)
            ).fetchone()
            if exists:
                validate_schema(connection, schema, require_active=False)
                if _declared_version(connection, schema) >= 2:
                    return
            else:
                connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
                for name, definition in _DEFINITIONS.items():
                    connection.execute(
                        sql.SQL("CREATE TABLE {}.{} ").format(
                            sql.Identifier(schema), sql.Identifier(name)
                        )
                        + sql.SQL(definition).format(schema=sql.Identifier(schema))
                    )
                connection.execute(
                    sql.SQL(
                        "INSERT INTO {}.schema_metadata VALUES (TRUE,1,'staging',NULL,NULL)"
                    ).format(sql.Identifier(schema))
                )
            connection.execute(
                sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC").format(sql.Identifier(schema))
            )
            connection.execute(
                sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                    sql.Identifier(schema), sql.Identifier(runtime_role)
                )
            )
            for table in _COLUMNS:
                connection.execute(
                    sql.SQL("REVOKE ALL ON {}.{} FROM PUBLIC, {}").format(
                        sql.Identifier(schema),
                        sql.Identifier(table),
                        sql.Identifier(runtime_role),
                    )
                )
                grants = (
                    sql.SQL("SELECT")
                    if table == "schema_metadata"
                    else sql.SQL("SELECT,INSERT,UPDATE")
                )
                connection.execute(
                    sql.SQL("GRANT {} ON {}.{} TO {}").format(
                        grants,
                        sql.Identifier(schema),
                        sql.Identifier(table),
                        sql.Identifier(runtime_role),
                    )
                )
            connection.execute(
                sql.SQL(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA {} REVOKE ALL ON TABLES FROM PUBLIC, {}"
                ).format(sql.Identifier(schema), sql.Identifier(runtime_role))
            )
            connection.execute(
                sql.SQL(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA {} GRANT SELECT ON TABLES TO {}"
                ).format(sql.Identifier(schema), sql.Identifier(runtime_role))
            )
            validate_schema(connection, schema, require_active=False)
        _event("postgres_schema_installed")
    except (MigrationError, SchemaVersionError):
        raise
    except psycopg.Error as error:
        raise MigrationError("PostgreSQL schema installation failed") from error


def _copy_snapshot(
    snapshot: TransferSnapshot,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        tables: list[list[dict[str, Any]]] = [
            [dict(row) for row in values]
            for values in (snapshot.tasks, snapshot.executions, snapshot.attempts)
        ]
        for rows, table in zip(tables, ("tasks", "executions", "execution_attempts"), strict=True):
            for row in rows:
                if set(row) != set(_COLUMNS[table]) or any(
                    type(value) not in {str, int, type(None)} for value in row.values()
                ):
                    raise ValueError("invalid transfer row")
                for value in row.values():
                    if isinstance(value, str):
                        value.encode("utf-8")
                        if "\0" in value:
                            raise ValueError("invalid text value")
        tasks, executions, attempts = tables
        tasks.sort(key=lambda row: row["task_id"])
        executions.sort(key=lambda row: row["task_id"])
        attempts.sort(key=lambda row: (row["task_id"], row["attempt_no"], row["attempt_id"]))
        digest = snapshot_digest(tasks, executions, attempts)
        if digest != snapshot.source_digest or not re.fullmatch(
            r"[a-f0-9]{64}", snapshot.source_digest
        ):
            raise ValueError("invalid transfer digest")
        if (
            type(snapshot.migration_id) is not str
            or str(UUID(snapshot.migration_id)) != snapshot.migration_id
        ):
            raise ValueError("invalid transfer identity")
        task_map = {row["task_id"]: row for row in tasks}
        execution_map = {row["task_id"]: row for row in executions}
        if (
            len(task_map) != len(tasks)
            or len(execution_map) != len(executions)
            or len({(row["scope_id"], row["idempotency_key"]) for row in tasks}) != len(tasks)
        ):
            raise ValueError("duplicate transfer identities")
        if len({row["effect_id"] for row in executions}) != len(executions):
            raise ValueError("duplicate effect identities")
        for row in tasks:
            if row["status"] != "queued":
                raise ValueError("invalid task state")
            for name in ("task_id", "scope_id", "idempotency_key"):
                if (
                    type(row[name]) is not str
                    or not row[name]
                    or row[name] != row[name].strip()
                    or len(row[name]) > 128
                ):
                    raise ValueError("invalid task identity")
            payload = json.loads(row["payload"])
            request = BookingChange(
                payload["booking_reference"],
                date.fromisoformat(payload["new_check_in"]),
                payload["confirmed"],
            )
            if (
                set(payload) != {"booking_reference", "new_check_in", "confirmed"}
                or json.dumps(request.payload(), sort_keys=True, separators=(",", ":"))
                != row["payload"]
            ):
                raise ValueError("noncanonical task")
            if datetime.fromisoformat(row["created_at"]).utcoffset() is None:
                raise ValueError("invalid timestamp")
        for row in executions:
            task = task_map[row["task_id"]]
            record = decode_execution(
                {
                    **row,
                    "scope_id": task["scope_id"],
                    "idempotency_key": task["idempotency_key"],
                    "payload": task["payload"],
                }
            )
            if type(row["version"]) is not int or not 0 <= row["version"] <= 9223372036854775807:
                raise ValueError("invalid version")
            if record.created_at != task["created_at"]:
                raise ValueError("different creation timestamp")
            if (record.status == ExecutionStatus.SUCCEEDED) != (record.result is not None) or (
                record.status == ExecutionStatus.FAILED
            ) != (record.error_code is not None):
                raise ValueError("invalid outcome")
        seen = set()
        for row in attempts:
            execution_map[row["task_id"]]
            attempt_record = decode_attempt(row)
            UUID(attempt_record.attempt_id)
            for field in ("started_at", "finished_at"):
                if (
                    row[field] is not None
                    and datetime.fromisoformat(row[field]).utcoffset() is None
                ):
                    raise ValueError("invalid attempt timestamp")
            if (
                attempt_record.attempt_id in seen
                or type(attempt_record.attempt_no) is not int
                or not 1 <= attempt_record.attempt_no <= 9223372036854775807
            ):
                raise ValueError("invalid attempt identity")
            seen.add(attempt_record.attempt_id)
            if (attempt_record.status == AttemptStatus.STARTED) != (
                attempt_record.finished_at is None
            ):
                raise ValueError("invalid attempt finish")
            if (attempt_record.status == AttemptStatus.FAILED) != (
                attempt_record.error_code is not None
            ):
                raise ValueError("invalid attempt error")
        if len({(r["task_id"], r["attempt_no"]) for r in attempts}) != len(attempts):
            raise ValueError("duplicate attempt number")
        for execution in executions:
            history = [row for row in attempts if row["task_id"] == execution["task_id"]]
            if [row["attempt_no"] for row in history] != list(range(1, len(history) + 1)):
                raise ValueError("attempt sequence is not contiguous")
            status = ExecutionStatus(execution["status"])
            if status == ExecutionStatus.ACCEPTED:
                if history or execution["version"] != 0:
                    raise ValueError("accepted execution has attempt history")
            else:
                if not history or any(row["status"] != "interrupted" for row in history[:-1]):
                    raise ValueError("execution history is inconsistent")
                last = history[-1]
                expected_status = "started" if status == ExecutionStatus.RUNNING else status.value
                expected_version = (
                    len(history) if status == ExecutionStatus.RUNNING else len(history) + 1
                )
                if last["status"] != expected_status or execution["version"] != expected_version:
                    raise ValueError("execution version or latest attempt is inconsistent")
                if last["error_code"] != execution["error_code"]:
                    raise ValueError("execution failure does not match attempt")
        return tasks, executions, attempts
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        OverflowError,
        InvalidStoredState,
    ) as error:
        raise MigrationError("Source transfer snapshot is invalid") from error


def _rows(
    connection: psycopg.Connection[dict[str, Any]], schema: str, table: str
) -> list[dict[str, Any]]:
    order = (
        sql.SQL('task_id COLLATE "C",attempt_no,attempt_id COLLATE "C"')
        if table == "execution_attempts"
        else sql.SQL('task_id COLLATE "C"')
    )
    return connection.execute(
        sql.SQL("SELECT * FROM {}.{} ORDER BY {}").format(
            sql.Identifier(schema), sql.Identifier(table), order
        )
    ).fetchall()


def _verify(
    connection: psycopg.Connection[dict[str, Any]],
    schema: str,
    snapshot: TransferSnapshot,
    tables: tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]],
) -> dict[str, Any]:
    metadata = connection.execute(
        sql.SQL("SELECT * FROM {}.schema_metadata WHERE singleton").format(sql.Identifier(schema))
    ).fetchone()
    if metadata is None or (metadata["migration_id"], metadata["source_digest"]) != (
        snapshot.migration_id,
        snapshot.source_digest,
    ):
        raise MigrationError("PostgreSQL import identity conflicts with the source")
    if metadata["state"] != "staging":
        raise MigrationError(
            "Active PostgreSQL work must not be restaged or compared to the old source"
        )
    for table, expected in zip(("tasks", "executions", "execution_attempts"), tables, strict=True):
        if _rows(connection, schema, table) != expected:
            raise MigrationError("PostgreSQL imported state does not match the source")
    return metadata


def stage_import(
    settings: PostgresSettings,
    snapshot: TransferSnapshot,
    *,
    runtime_role: str = RUNTIME_ROLE,
    failpoint: Callable[[str], None] | None = None,
) -> ImportReport:
    """Atomically stage the exact source state, or verify an identical replay."""
    tables = _copy_snapshot(snapshot)
    install_schema(settings, runtime_role=runtime_role)
    schema = _identifier(settings.schema)
    changed = False
    try:
        with (
            settings.connect(application_name="continuity-migrate") as connection,
            connection.transaction(),
        ):
            _owner(connection)
            _admission_lock(connection, schema)
            validate_schema(connection, schema, require_active=False)
            if _declared_version(connection, schema) != 1:
                raise MigrationError("PostgreSQL import requires a staging v1 target")
            metadata = connection.execute(
                sql.SQL("SELECT * FROM {}.schema_metadata WHERE singleton FOR UPDATE").format(
                    sql.Identifier(schema)
                )
            ).fetchone()
            assert metadata is not None
            if metadata["migration_id"] is not None:
                _verify(connection, schema, snapshot, tables)
            else:
                if metadata["state"] != "staging" or any(
                    _rows(connection, schema, name)
                    for name in ("tasks", "executions", "execution_attempts")
                ):
                    raise MigrationError("PostgreSQL target must be empty before import")
                for table, rows in zip(
                    ("tasks", "executions", "execution_attempts"), tables, strict=True
                ):
                    columns = _COLUMNS[table]
                    query = sql.SQL("INSERT INTO {}.{} ({}) VALUES ({})").format(
                        sql.Identifier(schema),
                        sql.Identifier(table),
                        sql.SQL(",").join(map(sql.Identifier, columns)),
                        sql.SQL(",").join(sql.Placeholder() for _ in columns),
                    )
                    with connection.cursor() as cursor:
                        cursor.executemany(query, ([row[name] for name in columns] for row in rows))
                if failpoint:
                    failpoint("postgres.after_stage_rows")
                connection.execute(
                    sql.SQL(
                        "UPDATE {}.schema_metadata SET migration_id=%s,source_digest=%s WHERE singleton"
                    ).format(sql.Identifier(schema)),
                    (snapshot.migration_id, snapshot.source_digest),
                )
                _verify(connection, schema, snapshot, tables)
                changed = True
            if failpoint:
                failpoint("postgres.before_stage_commit")
            state = metadata["state"]
        if failpoint:
            failpoint("postgres.after_stage_commit")
        _event("postgres_import_staged" if changed else "postgres_import_replayed")
        return ImportReport(
            snapshot.migration_id,
            snapshot.source_digest,
            changed,
            len(tables[0]),
            len(tables[1]),
            len(tables[2]),
            state,
        )
    except (MigrationError, SchemaVersionError):
        raise
    except psycopg.Error as error:
        raise MigrationError("PostgreSQL staging import failed") from error


def verify_import(settings: PostgresSettings, snapshot: TransferSnapshot) -> None:
    tables = _copy_snapshot(snapshot)
    try:
        with (
            settings.connect(application_name="continuity-migrate") as connection,
            connection.transaction(),
        ):
            _admission_lock(connection, settings.schema)
            validate_schema(connection, settings.schema, require_active=False)
            _verify(connection, settings.schema, snapshot, tables)
    except (MigrationError, SchemaVersionError):
        raise
    except psycopg.Error as error:
        raise MigrationError("PostgreSQL imported state could not be verified") from error


def activate_import(settings: PostgresSettings, migration_id: str, source_digest: str) -> None:
    """Verify/activate atomically after the coordinator commits source cutover.

    Table locks fence direct DML too. A matching ACTIVE receipt is already
    complete and is never compared with the old source after runtime progress.
    """
    try:
        with (
            settings.connect(application_name="continuity-migrate") as connection,
            connection.transaction(),
        ):
            _owner(connection)
            _admission_lock(connection, settings.schema)
            validate_schema(connection, settings.schema, require_active=False)
            connection.execute(
                sql.SQL("LOCK TABLE {} IN SHARE ROW EXCLUSIVE MODE").format(
                    sql.SQL(",").join(
                        sql.Identifier(settings.schema, table)
                        for table in ("tasks", "executions", "execution_attempts")
                    )
                )
            )
            row = connection.execute(
                sql.SQL(
                    "SELECT state,migration_id,source_digest FROM {}.schema_metadata WHERE singleton FOR UPDATE"
                ).format(sql.Identifier(settings.schema))
            ).fetchone()
            if (
                row is None
                or (row["migration_id"], row["source_digest"]) != (migration_id, source_digest)
                or not migration_id
                or not re.fullmatch(r"[a-f0-9]{64}", source_digest)
            ):
                raise MigrationError("PostgreSQL activation identity conflicts with the source")
            if row["state"] == "staging":
                tables = tuple(
                    _rows(connection, settings.schema, table)
                    for table in ("tasks", "executions", "execution_attempts")
                )
                if snapshot_digest(*tables) != source_digest:
                    raise MigrationError("PostgreSQL staged state changed before activation")
                connection.execute(
                    sql.SQL("UPDATE {}.schema_metadata SET state='active' WHERE singleton").format(
                        sql.Identifier(settings.schema)
                    )
                )
        _event("postgres_import_activated")
    except (MigrationError, SchemaVersionError):
        raise
    except psycopg.Error as error:
        raise MigrationError("PostgreSQL activation failed") from error


def read_import_state(settings: PostgresSettings) -> ImportState:
    """Read the durable gate/receipt without comparing legitimately progressed data."""
    try:
        with (
            settings.connect(application_name="continuity-migrate") as connection,
            connection.transaction(),
        ):
            validate_schema(connection, settings.schema, require_active=False)
            row = connection.execute(
                sql.SQL(
                    "SELECT version,state,migration_id,source_digest FROM {}.schema_metadata WHERE singleton"
                ).format(sql.Identifier(settings.schema))
            ).fetchone()
            assert row is not None
            return ImportState(
                row["version"], row["state"], row["migration_id"], row["source_digest"]
            )
    except (MigrationError, SchemaVersionError):
        raise
    except psycopg.Error as error:
        raise MigrationError("PostgreSQL import state could not be read") from error


@dataclass(frozen=True, slots=True)
class UpgradeReport:
    previous_version: int
    current_version: int
    changed: bool


def upgrade_v2(
    settings: PostgresSettings,
    *,
    failpoint: Callable[[str], None] | None = None,
) -> UpgradeReport:
    """Explicitly add Phase D state to an ACTIVE v1 schema in one transaction.

    Admission shares the existing write lock. Original inquiry rows, payloads,
    attempts and the historical cutover receipt are never rewritten. A stopped
    precommit transaction rolls back DDL and version together; a lost committed
    acknowledgement replays the validated v2 receipt without repairing drift.
    """
    schema = _identifier(settings.schema)
    previous = 1
    try:
        with (
            settings.connect(application_name="continuity-migrate") as connection,
            connection.transaction(),
        ):
            _owner(connection)
            _admission_lock(connection, schema)
            validate_schema(connection, schema, require_active=True)
            previous = _declared_version(connection, schema)
            if previous >= 2:
                return UpgradeReport(previous, previous, False)
            for table, definition in v2.DEFINITIONS.items():
                connection.execute(
                    sql.SQL("CREATE TABLE {}.{} ").format(
                        sql.Identifier(schema), sql.Identifier(table)
                    )
                    + sql.SQL(definition).format(schema=sql.Identifier(schema))
                )
                connection.execute(
                    sql.SQL("REVOKE ALL ON {}.{} FROM PUBLIC, {}").format(
                        sql.Identifier(schema),
                        sql.Identifier(table),
                        sql.Identifier(RUNTIME_ROLE),
                    )
                )
                connection.execute(
                    sql.SQL("GRANT {} ON {}.{} TO {}").format(
                        sql.SQL(",").join(map(sql.SQL, v2.GRANTS[table])),
                        sql.Identifier(schema),
                        sql.Identifier(table),
                        sql.Identifier(RUNTIME_ROLE),
                    )
                )
            for name, (table, columns) in v2.OPERATING_INDEXES.items():
                connection.execute(
                    sql.SQL("CREATE INDEX {} ON {}.{} ({})").format(
                        sql.Identifier(name),
                        sql.Identifier(schema),
                        sql.Identifier(table),
                        sql.SQL(",").join(map(sql.Identifier, columns)),
                    )
                )
            # These changes are invisible until the single DDL transaction commits.
            # v2 is ACTIVE-only: migration cannot race an unfinished source import.
            connection.execute(
                sql.SQL(
                    "ALTER TABLE {}.schema_metadata DROP CONSTRAINT metadata_version, DROP CONSTRAINT metadata_state"
                ).format(sql.Identifier(schema))
            )
            connection.execute(
                sql.SQL("UPDATE {}.schema_metadata SET version=2 WHERE singleton").format(
                    sql.Identifier(schema)
                )
            )
            connection.execute(
                sql.SQL(
                    "ALTER TABLE {}.schema_metadata ADD CONSTRAINT metadata_version CHECK(version=2), ADD CONSTRAINT metadata_state CHECK(state='active')"
                ).format(sql.Identifier(schema))
            )
            if failpoint:
                failpoint("postgres.upgrade.after_ddl")
            validate_schema(connection, schema, require_active=True, minimum_version=2)
            if failpoint:
                failpoint("postgres.upgrade.before_commit")
        if failpoint:
            failpoint("postgres.upgrade.after_commit")
        _event("postgres_schema_upgraded")
        return UpgradeReport(previous, 2, True)
    except (MigrationError, SchemaVersionError):
        raise
    except psycopg.Error as error:
        raise MigrationError("PostgreSQL schema upgrade failed; retain original state") from error


def upgrade_v3(
    settings: PostgresSettings, *, failpoint: Callable[[str], None] | None = None
) -> UpgradeReport:
    """Add mutation/cancellation/completion state to an ACTIVE v2 atomically.

    Legacy authority rows and their exact JSON are preserved. A schema upgrade
    never reconstructs missing supplier revision or human consent from mutable
    booking state. Such legacy intents remain readable but cannot authorize apply.
    """
    schema = _identifier(settings.schema)
    try:
        with (
            settings.connect(application_name="continuity-migrate") as connection,
            connection.transaction(),
        ):
            _owner(connection)
            _admission_lock(connection, schema)
            validate_schema(connection, schema, require_active=True)
            previous = _declared_version(connection, schema)
            if previous >= 3:
                return UpgradeReport(previous, previous, False)
            if previous != 2:
                raise SchemaVersionError("Mutation schema upgrade requires ACTIVE PostgreSQL v2")
            for table, definition in v3.DEFINITIONS.items():
                connection.execute(
                    sql.SQL("CREATE TABLE {}.{} ").format(
                        sql.Identifier(schema), sql.Identifier(table)
                    )
                    + sql.SQL(definition).format(schema=sql.Identifier(schema))
                )
                connection.execute(
                    sql.SQL("REVOKE ALL ON {}.{} FROM PUBLIC, {}").format(
                        sql.Identifier(schema),
                        sql.Identifier(table),
                        sql.Identifier(RUNTIME_ROLE),
                    )
                )
                connection.execute(
                    sql.SQL("GRANT {} ON {}.{} TO {}").format(
                        sql.SQL(",").join(map(sql.SQL, v3.GRANTS[table])),
                        sql.Identifier(schema),
                        sql.Identifier(table),
                        sql.Identifier(RUNTIME_ROLE),
                    )
                )
            for name, (table, columns) in v3.OPERATING_INDEXES.items():
                connection.execute(
                    sql.SQL("CREATE INDEX {} ON {}.{} ({})").format(
                        sql.Identifier(name),
                        sql.Identifier(schema),
                        sql.Identifier(table),
                        sql.SQL(",").join(map(sql.Identifier, columns)),
                    )
                )
            connection.execute(
                sql.SQL("ALTER TABLE {}.execution_controls DROP CONSTRAINT controls_state").format(
                    sql.Identifier(schema)
                )
            )
            connection.execute(
                sql.SQL("ALTER TABLE {}.execution_controls ADD CONSTRAINT controls_state ").format(
                    sql.Identifier(schema)
                )
                + sql.SQL(v3.CONTROL_STATE_CHECK)
            )
            connection.execute(
                sql.SQL("ALTER TABLE {}.schema_metadata DROP CONSTRAINT metadata_version").format(
                    sql.Identifier(schema)
                )
            )
            connection.execute(
                sql.SQL("UPDATE {}.schema_metadata SET version=3 WHERE singleton").format(
                    sql.Identifier(schema)
                )
            )
            connection.execute(
                sql.SQL(
                    "ALTER TABLE {}.schema_metadata ADD CONSTRAINT metadata_version CHECK(version=3)"
                ).format(sql.Identifier(schema))
            )
            if failpoint:
                failpoint("postgres.upgrade_v3.after_ddl")
            validate_schema(connection, schema, require_active=True, minimum_version=3)
            if failpoint:
                failpoint("postgres.upgrade_v3.before_commit")
        if failpoint:
            failpoint("postgres.upgrade_v3.after_commit")
        _event("postgres_schema_upgraded")
        return UpgradeReport(2, 3, True)
    except (MigrationError, SchemaVersionError):
        raise
    except psycopg.Error as error:
        raise MigrationError(
            "PostgreSQL mutation schema upgrade failed; retain original state"
        ) from error


def upgrade_v4(
    settings: PostgresSettings,
    *,
    policy: CoordinationPolicy | None = None,
    failpoint: Callable[[str], None] | None = None,
) -> UpgradeReport:
    """Add retained lease epochs and owner-provisioned limits to ACTIVE v3.

    The explicit policy is inserted only at first upgrade. Replaying an existing
    v4 validates the retained policy, and an explicit different policy conflicts
    rather than silently reconfiguring active work. Original authority rows,
    payloads, attempts and historical cutover receipts are never rewritten.
    """
    from .lease_models import CoordinationPolicy

    if policy is not None and type(policy) is not CoordinationPolicy:
        raise ValueError("A typed coordination policy is required")
    schema = _identifier(settings.schema)
    try:
        with (
            settings.connect(application_name="continuity-migrate") as connection,
            connection.transaction(),
        ):
            _owner(connection)
            _admission_lock(connection, schema)
            validate_schema(connection, schema, require_active=True)
            previous = _declared_version(connection, schema)
            if previous == 4:
                if policy is not None:
                    row = connection.execute(
                        sql.SQL("SELECT * FROM {}.execution_limits WHERE singleton").format(
                            sql.Identifier(schema)
                        )
                    ).fetchone()
                    assert row is not None
                    if {name: row[name] for name in policy.payload()} != policy.payload():
                        raise IdempotencyConflict(
                            "Coordination policy already has different values"
                        )
                return UpgradeReport(4, 4, False)
            if previous != 3:
                raise SchemaVersionError(
                    "Coordination schema upgrade requires ACTIVE PostgreSQL v3"
                )
            # Original unmanaged workers cannot finish through the leased v4
            # boundary. Refuse before DDL so v3 can still reconcile that inquiry.
            if (
                connection.execute(
                    sql.SQL(
                        "SELECT 1 FROM {}.executions e LEFT JOIN {}.execution_controls c ON c.task_id=e.task_id WHERE e.status='running' AND c.task_id IS NULL LIMIT 1"
                    ).format(sql.Identifier(schema), sql.Identifier(schema))
                ).fetchone()
                is not None
            ):
                raise UnsupportedOperation(
                    "Reconcile running legacy inquiries before coordination upgrade"
                )
            selected = CoordinationPolicy() if policy is None else policy
            connection.execute(
                sql.SQL(
                    "ALTER TABLE {}.tasks ADD CONSTRAINT tasks_identity_scope_key UNIQUE(task_id,scope_id)"
                ).format(sql.Identifier(schema))
            )
            for table, definition in v4.DEFINITIONS.items():
                connection.execute(
                    sql.SQL("CREATE TABLE {}.{} ").format(
                        sql.Identifier(schema), sql.Identifier(table)
                    )
                    + sql.SQL(definition).format(schema=sql.Identifier(schema))
                )
                connection.execute(
                    sql.SQL("REVOKE ALL ON {}.{} FROM PUBLIC, {}").format(
                        sql.Identifier(schema), sql.Identifier(table), sql.Identifier(RUNTIME_ROLE)
                    )
                )
                connection.execute(
                    sql.SQL("GRANT {} ON {}.{} TO {}").format(
                        sql.SQL(",").join(map(sql.SQL, v4.GRANTS[table])),
                        sql.Identifier(schema),
                        sql.Identifier(table),
                        sql.Identifier(RUNTIME_ROLE),
                    )
                )
            for name, (table, columns) in v4.OPERATING_INDEXES.items():
                connection.execute(
                    sql.SQL("CREATE INDEX {} ON {}.{} ({})").format(
                        sql.Identifier(name),
                        sql.Identifier(schema),
                        sql.Identifier(table),
                        sql.SQL(",").join(map(sql.Identifier, columns)),
                    )
                )
            connection.execute(
                sql.SQL("INSERT INTO {}.execution_limits VALUES (TRUE,%s,%s,%s,%s)").format(
                    sql.Identifier(schema)
                ),
                (
                    selected.maximum_pending,
                    selected.maximum_active,
                    selected.maximum_records,
                    selected.lease_seconds,
                ),
            )
            connection.execute(
                sql.SQL("ALTER TABLE {}.schema_metadata DROP CONSTRAINT metadata_version").format(
                    sql.Identifier(schema)
                )
            )
            connection.execute(
                sql.SQL("UPDATE {}.schema_metadata SET version=4 WHERE singleton").format(
                    sql.Identifier(schema)
                )
            )
            connection.execute(
                sql.SQL(
                    "ALTER TABLE {}.schema_metadata ADD CONSTRAINT metadata_version CHECK(version=4)"
                ).format(sql.Identifier(schema))
            )
            if failpoint:
                failpoint("postgres.upgrade_v4.after_ddl")
            validate_schema(connection, schema, require_active=True, minimum_version=4)
            if failpoint:
                failpoint("postgres.upgrade_v4.before_commit")
        if failpoint:
            failpoint("postgres.upgrade_v4.after_commit")
        _event("postgres_schema_upgraded")
        return UpgradeReport(3, 4, True)
    except (MigrationError, SchemaVersionError):
        raise
    except psycopg.Error as error:
        raise MigrationError(
            "PostgreSQL coordination schema upgrade failed; retain original state"
        ) from error
