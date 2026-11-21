"""Owner installation and runtime validation of the booking schema."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg import sql

from . import postgres_schema as schema_definition
from .lease_models import CoordinationPolicy
from .migrations import MigrationError, SchemaVersionError
from .postgres_settings import PostgresSettings, advisory_keys

MIGRATOR_ROLE = "continuity_migrator"
RUNTIME_ROLE = "livekit_lab"


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
    check_equivalents: dict[str, tuple[str, ...]]


_CATALOG = _Catalog(
    {name: tuple(columns) for name, columns in schema_definition.COLUMN_SPECS.items()},
    schema_definition.COLUMN_SPECS,
    schema_definition.CHECK_DEFINITIONS,
    schema_definition.CHECK_TABLES,
    schema_definition.KEYS,
    schema_definition.FOREIGN_KEYS,
    schema_definition.GRANTS,
    schema_definition.OPERATING_INDEXES,
    schema_definition.CHECK_EQUIVALENTS,
)


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
    """Fail closed when grants could bypass the schema contract or change structure."""
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
) -> None:
    """Verify the exact initial layout without changing stored state."""
    _identifier(schema)
    try:
        if not 180000 <= connection.info.server_version < 190000:
            raise SchemaVersionError("This schema verifier requires the supported PostgreSQL major")
        owner = connection.execute(
            "SELECT pg_get_userbyid(nspowner) AS owner, "
            "obj_description(oid, 'pg_namespace') AS marker FROM pg_namespace WHERE nspname=%s",
            (schema,),
        ).fetchone()
        if (
            owner is None
            or owner["owner"] != MIGRATOR_ROLE
            or owner["marker"] != schema_definition.MARKER
        ):
            raise SchemaVersionError("PostgreSQL schema ownership is unsupported")
        _restricted_role(connection, MIGRATOR_ROLE)
        current = connection.execute("SELECT current_user AS role").fetchone()
        assert current is not None
        _restricted_role(connection, current["role"])
        catalog = _CATALOG
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
                accepted = {
                    _normalize_sql(value)
                    for value in (catalog.checks[name], *catalog.check_equivalents.get(name, ()))
                }
                if (
                    row["table_name"] != check_table
                    or row["contype"] != "c"
                    or _normalize_sql(row["definition"]) not in accepted
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
        if rows != [{"singleton": True, "version": schema_definition.SCHEMA_VERSION}]:
            raise SchemaVersionError("PostgreSQL schema metadata is unsupported")
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


def install_schema(settings: PostgresSettings, *, policy: CoordinationPolicy | None = None) -> None:
    """Install the initial booking schema or verify an unchanged installation."""
    schema = _identifier(settings.schema)
    selected = CoordinationPolicy() if policy is None else policy
    if type(selected) is not CoordinationPolicy:
        raise MigrationError("A typed coordination policy is required")
    try:
        with (
            settings.connect(application_name="continuity-migrate") as connection,
            connection.transaction(),
        ):
            _owner(connection)
            _restricted_role(connection, RUNTIME_ROLE)
            _admission_lock(connection, schema)
            namespace = sql.Identifier(schema)
            existing = connection.execute(
                "SELECT 1 FROM pg_namespace WHERE nspname=%s", (schema,)
            ).fetchone()
            if existing is None:
                connection.execute(sql.SQL("CREATE SCHEMA {}").format(namespace))
                connection.execute(
                    sql.SQL("COMMENT ON SCHEMA {} IS {}").format(
                        namespace, sql.Literal(schema_definition.MARKER)
                    )
                )
                for name, definition in schema_definition.TABLE_DEFINITIONS.items():
                    connection.execute(
                        sql.SQL("CREATE TABLE {}.{} ").format(namespace, sql.Identifier(name))
                        + sql.SQL(definition).format(schema=namespace)
                    )
                for name, (table, columns) in _CATALOG.operating_indexes.items():
                    connection.execute(
                        sql.SQL("CREATE INDEX {} ON {}.{} ({})").format(
                            sql.Identifier(name),
                            namespace,
                            sql.Identifier(table),
                            sql.SQL(",").join(map(sql.Identifier, columns)),
                        )
                    )
                runtime = sql.Identifier(RUNTIME_ROLE)
                connection.execute(sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC").format(namespace))
                connection.execute(
                    sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(namespace, runtime)
                )
                for table, privileges in _CATALOG.grants.items():
                    relation = sql.Identifier(schema, table)
                    connection.execute(
                        sql.SQL("REVOKE ALL ON {} FROM PUBLIC, {}").format(relation, runtime)
                    )
                    connection.execute(
                        sql.SQL("GRANT {} ON {} TO {}").format(
                            sql.SQL(",").join(map(sql.SQL, privileges)), relation, runtime
                        )
                    )
                connection.execute(
                    sql.SQL(
                        "ALTER DEFAULT PRIVILEGES IN SCHEMA {} REVOKE ALL ON TABLES FROM PUBLIC, {}"
                    ).format(namespace, runtime)
                )
                connection.execute(
                    sql.SQL(
                        "ALTER DEFAULT PRIVILEGES IN SCHEMA {} GRANT SELECT ON TABLES TO {}"
                    ).format(namespace, runtime)
                )
                connection.execute(
                    sql.SQL("INSERT INTO {}.schema_metadata VALUES(TRUE,%s)").format(namespace),
                    (schema_definition.SCHEMA_VERSION,),
                )
                connection.execute(
                    sql.SQL("INSERT INTO {}.execution_limits VALUES(TRUE,%s,%s,%s,%s)").format(
                        namespace
                    ),
                    (
                        selected.maximum_pending,
                        selected.maximum_active,
                        selected.maximum_records,
                        selected.lease_seconds,
                    ),
                )
            validate_schema(connection, schema)
            actual = connection.execute(
                sql.SQL(
                    "SELECT maximum_pending,maximum_active,maximum_records,lease_seconds FROM {}.execution_limits"
                ).format(namespace)
            ).fetchone()
            if actual != {
                "maximum_pending": selected.maximum_pending,
                "maximum_active": selected.maximum_active,
                "maximum_records": selected.maximum_records,
                "lease_seconds": selected.lease_seconds,
            }:
                raise SchemaVersionError(
                    "PostgreSQL coordination policy differs from the requested layout"
                )
    except psycopg.Error as error:
        raise MigrationError("PostgreSQL booking schema installation failed") from error
