"""Owner-only profile definition and catalog validation; runtime never installs DDL."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import psycopg
from psycopg import sql

from .issued_models import ExecutionLimits
from .postgres_settings import PostgresSettings
from .work_models import WorkError, WorkLimits

SCHEMA_VERSION = 1
MARKER = "continuity-work-0001"
TABLES = ("schema_metadata", "admission", "accepted_work", "cancellation_commands")
DDL = """
CREATE TABLE schema_metadata(singleton boolean PRIMARY KEY CHECK(singleton),version smallint NOT NULL CHECK(version=1),definition_sha256 text COLLATE "C" NOT NULL,catalog_sha256 text COLLATE "C" NOT NULL,max_records integer NOT NULL CHECK(max_records BETWEEN 1 AND 10000),max_cancel_commands integer NOT NULL CHECK(max_cancel_commands BETWEEN 1 AND 10000));
CREATE TABLE admission(singleton boolean PRIMARY KEY CHECK(singleton),record_count integer NOT NULL CHECK(record_count>=0),cancel_count integer NOT NULL CHECK(cancel_count>=0));
CREATE TABLE accepted_work(work_id uuid PRIMARY KEY,tenant_id text COLLATE "C" NOT NULL CHECK(octet_length(tenant_id) BETWEEN 1 AND 128),account_id text COLLATE "C" NOT NULL CHECK(octet_length(account_id) BETWEEN 1 AND 128),idempotency_key text COLLATE "C" NOT NULL CHECK(octet_length(idempotency_key) BETWEEN 1 AND 128),operation text COLLATE "C" NOT NULL CHECK(operation='booking.evaluate_policy'),body bytea NOT NULL CHECK(octet_length(body) BETWEEN 1 AND 16384),sha256 text COLLATE "C" NOT NULL CHECK(sha256 ~ '^[0-9a-f]{64}$'),deadline_at_ms bigint NOT NULL CHECK(deadline_at_ms BETWEEN 0 AND 4102444800000),accepted_at_ms bigint NOT NULL CHECK(accepted_at_ms BETWEEN 0 AND 4102444800000),UNIQUE(tenant_id,account_id,idempotency_key),UNIQUE(tenant_id,account_id,work_id));
CREATE TABLE cancellation_commands(cancellation_id uuid PRIMARY KEY,tenant_id text COLLATE "C" NOT NULL,account_id text COLLATE "C" NOT NULL,work_id uuid NOT NULL,command_id text COLLATE "C" NOT NULL CHECK(octet_length(command_id) BETWEEN 1 AND 128),requested_at_ms bigint NOT NULL CHECK(requested_at_ms BETWEEN 0 AND 4102444800000),UNIQUE(tenant_id,account_id,command_id),FOREIGN KEY(tenant_id,account_id,work_id) REFERENCES accepted_work(tenant_id,account_id,work_id));
"""

EXECUTION_TABLES = ("execution_limits", "issued_attempts", "attempt_results")
EXECUTION_DDL = """
CREATE TABLE execution_limits(singleton boolean PRIMARY KEY CHECK(singleton),max_active integer NOT NULL CHECK(max_active BETWEEN 1 AND 4),max_attempts integer NOT NULL CHECK(max_attempts BETWEEN 1 AND 3),lease_ms integer NOT NULL CHECK(lease_ms BETWEEN 100 AND 30000));
CREATE TABLE issued_attempts(attempt_id uuid PRIMARY KEY,tenant_id text COLLATE "C" NOT NULL,account_id text COLLATE "C" NOT NULL,work_id uuid NOT NULL,command_id text COLLATE "C" NOT NULL CHECK(octet_length(command_id) BETWEEN 1 AND 128),number integer NOT NULL CHECK(number BETWEEN 1 AND 3),owner_id uuid NOT NULL,epoch bigint NOT NULL CHECK(epoch BETWEEN 1 AND 3),issued_at_ms bigint NOT NULL CHECK(issued_at_ms BETWEEN 0 AND 4102444800000),lease_until_ms bigint NOT NULL CHECK(lease_until_ms BETWEEN 0 AND 4102444800000),CHECK(issued_at_ms<lease_until_ms),UNIQUE(tenant_id,account_id,command_id),UNIQUE(tenant_id,account_id,work_id,number),UNIQUE(tenant_id,account_id,work_id,epoch),UNIQUE(tenant_id,account_id,work_id,attempt_id),FOREIGN KEY(tenant_id,account_id,work_id) REFERENCES accepted_work(tenant_id,account_id,work_id));
CREATE INDEX issued_attempts_active ON issued_attempts(lease_until_ms);
CREATE TABLE attempt_results(attempt_id uuid PRIMARY KEY,tenant_id text COLLATE "C" NOT NULL,account_id text COLLATE "C" NOT NULL,work_id uuid NOT NULL,body bytea NOT NULL CHECK(octet_length(body) BETWEEN 1 AND 8192),sha256 text COLLATE "C" NOT NULL CHECK(sha256 ~ '^[0-9a-f]{64}$'),recorded_at_ms bigint NOT NULL CHECK(recorded_at_ms BETWEEN 0 AND 4102444800000),disposition text COLLATE "C" NOT NULL CHECK(disposition IN ('eligible_at_commit','cancelled','expired','superseded','lease_expired')),FOREIGN KEY(tenant_id,account_id,work_id,attempt_id) REFERENCES issued_attempts(tenant_id,account_id,work_id,attempt_id));
"""

DELIVERY_TABLES = (
    "result_delivery_intents",
    "result_delivery_possible",
    "result_delivery_receipts",
    "result_actions",
)
DELIVERY_DDL = """
CREATE TABLE result_delivery_intents(delivery_id uuid PRIMARY KEY,tenant_id text COLLATE "C" NOT NULL,account_id text COLLATE "C" NOT NULL,work_id uuid NOT NULL,attempt_id uuid NOT NULL,result_sha256 text COLLATE "C" NOT NULL CHECK(result_sha256 ~ '^[0-9a-f]{64}$'),receiver_id uuid NOT NULL,recipient_id text COLLATE "C" NOT NULL CHECK(octet_length(recipient_id) BETWEEN 1 AND 128),prepared_at_ms bigint NOT NULL CHECK(prepared_at_ms BETWEEN 0 AND 4102444800000),UNIQUE(tenant_id,account_id,work_id),UNIQUE(delivery_id,receiver_id,recipient_id,result_sha256),FOREIGN KEY(tenant_id,account_id,work_id) REFERENCES accepted_work(tenant_id,account_id,work_id),FOREIGN KEY(tenant_id,account_id,work_id,attempt_id) REFERENCES issued_attempts(tenant_id,account_id,work_id,attempt_id),FOREIGN KEY(attempt_id) REFERENCES attempt_results(attempt_id));
CREATE TABLE result_delivery_possible(delivery_id uuid PRIMARY KEY REFERENCES result_delivery_intents(delivery_id),marked_at_ms bigint NOT NULL CHECK(marked_at_ms BETWEEN 0 AND 4102444800000));
CREATE TABLE result_delivery_receipts(delivery_id uuid PRIMARY KEY REFERENCES result_delivery_possible(delivery_id),receipt_id uuid NOT NULL,receiver_id uuid NOT NULL,recipient_id text COLLATE "C" NOT NULL,result_sha256 text COLLATE "C" NOT NULL,accepted_at_ms bigint NOT NULL CHECK(accepted_at_ms BETWEEN 0 AND 4102444800000),recorded_at_ms bigint NOT NULL CHECK(recorded_at_ms BETWEEN 0 AND 4102444800000),UNIQUE(receiver_id,receipt_id),FOREIGN KEY(delivery_id,receiver_id,recipient_id,result_sha256) REFERENCES result_delivery_intents(delivery_id,receiver_id,recipient_id,result_sha256));
CREATE TABLE result_actions(action_id uuid PRIMARY KEY,tenant_id text COLLATE "C" NOT NULL,account_id text COLLATE "C" NOT NULL,work_id uuid NOT NULL,attempt_id uuid NOT NULL,result_sha256 text COLLATE "C" NOT NULL CHECK(result_sha256 ~ '^[0-9a-f]{64}$'),case_schema text COLLATE "C" NOT NULL CHECK(octet_length(case_schema) BETWEEN 1 AND 63),case_scope_id text COLLATE "C" NOT NULL CHECK(octet_length(case_scope_id) BETWEEN 1 AND 512),case_actor_id text COLLATE "C" NOT NULL CHECK(octet_length(case_actor_id) BETWEEN 1 AND 512),case_task_id uuid NOT NULL,case_id uuid NOT NULL,expected_revision bigint NOT NULL CHECK(expected_revision BETWEEN 0 AND 9223372036854775807),command_id text COLLATE "C" NOT NULL CHECK(octet_length(command_id) BETWEEN 1 AND 128),confirmation_json text COLLATE "C" NOT NULL CHECK(octet_length(confirmation_json) BETWEEN 1 AND 16384),intent_id uuid NOT NULL,intent_json text COLLATE "C" NOT NULL CHECK(octet_length(intent_json) BETWEEN 1 AND 32768),committed_at_ms bigint NOT NULL CHECK(committed_at_ms BETWEEN 0 AND 4102444800000),UNIQUE(tenant_id,account_id,work_id),UNIQUE(tenant_id,account_id,command_id),UNIQUE(case_schema,intent_id),FOREIGN KEY(tenant_id,account_id,work_id) REFERENCES accepted_work(tenant_id,account_id,work_id),FOREIGN KEY(tenant_id,account_id,work_id,attempt_id) REFERENCES issued_attempts(tenant_id,account_id,work_id,attempt_id),FOREIGN KEY(attempt_id) REFERENCES attempt_results(attempt_id));
"""

FEED_TABLES = ("result_feed_source", "result_feed_heads", "result_feed_events")
FEED_DDL = """
CREATE TABLE result_feed_source(singleton boolean PRIMARY KEY CHECK(singleton),source_id uuid NOT NULL UNIQUE,adopted_at_ms bigint NOT NULL CHECK(adopted_at_ms BETWEEN 0 AND 4102444800000));
CREATE TABLE result_feed_heads(tenant_id text COLLATE "C" NOT NULL,account_id text COLLATE "C" NOT NULL,anchor_work_id uuid NOT NULL,last_sequence bigint NOT NULL CHECK(last_sequence BETWEEN 0 AND 9223372036854775807),PRIMARY KEY(tenant_id,account_id),FOREIGN KEY(tenant_id,account_id,anchor_work_id) REFERENCES accepted_work(tenant_id,account_id,work_id));
CREATE TABLE result_feed_events(event_id uuid PRIMARY KEY,tenant_id text COLLATE "C" NOT NULL,account_id text COLLATE "C" NOT NULL,sequence bigint NOT NULL CHECK(sequence BETWEEN 1 AND 9223372036854775807),work_id uuid NOT NULL,attempt_id uuid NOT NULL UNIQUE,origin text COLLATE "C" NOT NULL CHECK(origin IN ('live','adopted_history')),UNIQUE(tenant_id,account_id,sequence),FOREIGN KEY(tenant_id,account_id) REFERENCES result_feed_heads(tenant_id,account_id),FOREIGN KEY(tenant_id,account_id,work_id,attempt_id) REFERENCES issued_attempts(tenant_id,account_id,work_id,attempt_id),FOREIGN KEY(attempt_id) REFERENCES attempt_results(attempt_id));
"""

ALL_TABLES = (*TABLES, *EXECUTION_TABLES, *DELIVERY_TABLES, *FEED_TABLES)
BASELINE_DDL = DDL + EXECUTION_DDL + DELIVERY_DDL + FEED_DDL
DEFINITION_SHA256 = hashlib.sha256((MARKER + BASELINE_DDL).encode()).hexdigest()
Connection = psycopg.Connection[dict[str, Any]]


def check_settings(settings: PostgresSettings, *, owner: bool = False) -> None:
    if (
        type(settings) is not PostgresSettings
        or settings.dbname != "livekit_lab"
        or not settings.schema.startswith("p1_work_")
        or settings.user != ("continuity_migrator" if owner else "livekit_lab")
    ):
        raise WorkError("invalid_input")


def require_role(connection: Connection, schema: str, *, owner: bool = False) -> None:
    row = connection.execute(
        """SELECT current_user AS name,r.rolsuper,r.rolcreatedb,r.rolcreaterole,r.rolreplication,r.rolbypassrls,EXISTS(SELECT 1 FROM pg_auth_members m WHERE m.member=r.oid) AS memberships,has_database_privilege(current_user,current_database(),'CREATE') AS creates,has_database_privilege(current_user,current_database(),'TEMPORARY') AS temps,has_schema_privilege(current_user,%s,'CREATE') AS schema_create FROM pg_roles r WHERE r.rolname=current_user""",
        (schema,),
    ).fetchone()
    if (
        row is None
        or row["name"] != ("continuity_migrator" if owner else "livekit_lab")
        or any(
            row[key]
            for key in (
                "rolsuper",
                "rolcreatedb",
                "rolcreaterole",
                "rolreplication",
                "rolbypassrls",
                "memberships",
            )
        )
        or (not owner and any(row[key] for key in ("creates", "temps", "schema_create")))
    ):
        raise WorkError("schema_mismatch")

    if not owner:
        unsafe = connection.execute(
            """SELECT EXISTS(SELECT 1 FROM pg_namespace n WHERE n.nspname !~ '^pg_' AND n.nspname<>'information_schema' AND (n.nspowner=(SELECT oid FROM pg_roles WHERE rolname=current_user) OR has_schema_privilege(current_user,n.oid,'CREATE'))) OR EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname !~ '^pg_' AND n.nspname<>'information_schema' AND c.relowner=(SELECT oid FROM pg_roles WHERE rolname=current_user)) AS unsafe"""
        ).fetchone()
        if unsafe is None or unsafe["unsafe"] is not False:
            raise WorkError("schema_mismatch")


def _metadata_preflight(connection: Connection, schema: str) -> None:
    # Never select a row from an unvalidated view, generated column or custom type.
    relation = connection.execute(
        """SELECT c.relkind,c.relpersistence,c.relrowsecurity,c.relforcerowsecurity,pg_get_userbyid(c.relowner) AS owner,EXISTS(SELECT 1 FROM pg_trigger t WHERE t.tgrelid=c.oid AND NOT t.tgisinternal) AS triggers,EXISTS(SELECT 1 FROM pg_rewrite r WHERE r.ev_class=c.oid) AS rules FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relname='schema_metadata'""",
        (schema,),
    ).fetchone()
    if relation != {
        "relkind": "r",
        "relpersistence": "p",
        "relrowsecurity": False,
        "relforcerowsecurity": False,
        "owner": "continuity_migrator",
        "triggers": False,
        "rules": False,
    }:
        raise WorkError("schema_mismatch")
    attributes = connection.execute(
        """SELECT a.attname,a.atttypid::int AS type,a.attnotnull,a.attgenerated,a.attidentity,a.attacl,EXISTS(SELECT 1 FROM pg_attrdef d WHERE d.adrelid=a.attrelid AND d.adnum=a.attnum) AS has_default FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relname='schema_metadata' AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum""",
        (schema,),
    ).fetchall()
    expected = (
        ("singleton", 16),
        ("version", 21),
        ("definition_sha256", 25),
        ("catalog_sha256", 25),
        ("max_records", 23),
        ("max_cancel_commands", 23),
    )
    if len(attributes) != len(expected):
        raise WorkError("schema_mismatch")
    for row, (name, kind) in zip(attributes, expected, strict=True):
        if row != {
            "attname": name,
            "type": kind,
            "attnotnull": True,
            "attgenerated": "",
            "attidentity": "",
            "attacl": None,
            "has_default": False,
        }:
            raise WorkError("schema_mismatch")

    indexes = connection.execute(
        """SELECT am.amname,op.opcname,onsp.nspname AS op_namespace,i.indisvalid,i.indisready,i.indisunique,i.indisprimary,i.indnkeyatts,i.indnatts,i.indkey::text,pg_get_expr(i.indexprs,i.indrelid) AS expression,pg_get_expr(i.indpred,i.indrelid) AS predicate FROM pg_index i JOIN pg_class c ON c.oid=i.indrelid JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_class ic ON ic.oid=i.indexrelid JOIN pg_am am ON am.oid=ic.relam JOIN pg_opclass op ON op.oid=i.indclass[0] JOIN pg_namespace onsp ON onsp.oid=op.opcnamespace WHERE n.nspname=%s AND c.relname='schema_metadata'""",
        (schema,),
    ).fetchall()
    if indexes != [
        {
            "amname": "btree",
            "opcname": "bool_ops",
            "op_namespace": "pg_catalog",
            "indisvalid": True,
            "indisready": True,
            "indisunique": True,
            "indisprimary": True,
            "indnkeyatts": 1,
            "indnatts": 1,
            "indkey": "1",
            "expression": None,
            "predicate": None,
        }
    ]:
        raise WorkError("schema_mismatch")
    collations = connection.execute(
        """SELECT a.attname,co.oid::int,ns.nspname,co.collname,co.collprovider,co.collisdeterministic FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_collation co ON co.oid=a.attcollation JOIN pg_namespace ns ON ns.oid=co.collnamespace WHERE n.nspname=%s AND c.relname='schema_metadata' AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum""",
        (schema,),
    ).fetchall()
    expected_oid = connection.execute(
        """SELECT 'pg_catalog."C"'::regcollation::oid::int AS oid"""
    ).fetchone()
    if expected_oid is None or collations != [
        {
            "attname": name,
            "oid": expected_oid["oid"],
            "nspname": "pg_catalog",
            "collname": "C",
            "collprovider": "c",
            "collisdeterministic": True,
        }
        for name in ("definition_sha256", "catalog_sha256")
    ]:
        raise WorkError("schema_mismatch")


def _safe_grants(connection: Connection, schema: str) -> None:
    namespace = connection.execute(
        """SELECT pg_get_userbyid(n.nspowner) AS owner,obj_description(n.oid,'pg_namespace') AS marker FROM pg_namespace n WHERE n.nspname=%s""",
        (schema,),
    ).fetchone()
    if namespace != {
        "owner": "continuity_migrator",
        "marker": MARKER,
    }:
        raise WorkError("schema_mismatch")
    grants = connection.execute(
        """SELECT 'namespace' AS object,coalesce(pg_get_userbyid(x.grantee),'PUBLIC') AS grantee,x.privilege_type,x.is_grantable FROM pg_namespace n CROSS JOIN LATERAL aclexplode(coalesce(n.nspacl,acldefault('n',n.nspowner))) x WHERE n.nspname=%s UNION ALL SELECT c.relname,coalesce(pg_get_userbyid(x.grantee),'PUBLIC'),x.privilege_type,x.is_grantable FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace CROSS JOIN LATERAL aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) x WHERE n.nspname=%s""",
        (schema, schema),
    ).fetchall()
    expected = {
        "namespace": {"USAGE"},
        "schema_metadata": {"SELECT"},
        "admission": {"SELECT"},
        "accepted_work": {"SELECT", "INSERT"},
        "cancellation_commands": {"SELECT", "INSERT"},
    }
    expected.update(
        {
            "execution_limits": {"SELECT"},
            "issued_attempts": {"SELECT", "INSERT"},
            "attempt_results": {"SELECT", "INSERT"},
            "result_feed_source": {"SELECT"},
            "result_feed_heads": {"SELECT", "INSERT"},
            "result_feed_events": {"SELECT", "INSERT"},
            **{name: {"SELECT", "INSERT"} for name in DELIVERY_TABLES},
        }
    )
    observed: dict[str, set[str]] = {name: set() for name in expected}
    for grant in grants:
        if grant["grantee"] == "continuity_migrator":
            continue
        if (
            grant["grantee"] != "livekit_lab"
            or grant["object"] not in expected
            or grant["is_grantable"]
            or grant["privilege_type"] not in expected[grant["object"]]
        ):
            raise WorkError("schema_mismatch")
        observed[grant["object"]].add(grant["privilege_type"])
    if observed != expected:
        raise WorkError("schema_mismatch")
    columns = connection.execute(
        """SELECT c.relname,a.attname,pg_get_userbyid(x.grantee) AS grantee,x.privilege_type,x.is_grantable FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace CROSS JOIN LATERAL aclexplode(a.attacl) x WHERE n.nspname=%s AND a.attnum>0 AND NOT a.attisdropped""",
        (schema,),
    ).fetchall()
    expected_columns = {
        ("admission", "record_count", "livekit_lab", "UPDATE", False),
        ("admission", "cancel_count", "livekit_lab", "UPDATE", False),
        ("result_feed_heads", "last_sequence", "livekit_lab", "UPDATE", False),
    }
    if {tuple(row.values()) for row in columns} != expected_columns:
        raise WorkError("schema_mismatch")


def catalog_sha256(connection: Connection, schema: str) -> str:
    queries = (
        """SELECT c.relname,c.relkind,c.relpersistence,c.relrowsecurity,c.relforcerowsecurity,pg_get_userbyid(c.relowner) AS owner,c.relacl::text FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s ORDER BY c.relname""",
        """SELECT c.relname,a.attname,a.atttypid::int,a.attnum,a.attnotnull,a.attgenerated,a.attidentity,a.attacl::text,co.oid::int AS collation_oid,cn.nspname AS collation_namespace,co.collname,co.collprovider,co.collisdeterministic,co.collcollate,co.collctype,pg_get_expr(d.adbin,d.adrelid) AS expression FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace LEFT JOIN pg_collation co ON co.oid=a.attcollation LEFT JOIN pg_namespace cn ON cn.oid=co.collnamespace LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum WHERE n.nspname=%s AND a.attnum>0 AND NOT a.attisdropped ORDER BY c.relname,a.attnum""",
        """SELECT c.relname,x.conname,x.contype,x.convalidated,pg_get_constraintdef(x.oid,true) AS definition FROM pg_constraint x JOIN pg_class c ON c.oid=x.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s ORDER BY c.relname,x.conname""",
        """SELECT c.relname,pg_get_indexdef(i.indexrelid) AS definition FROM pg_index i JOIN pg_class c ON c.oid=i.indrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s ORDER BY c.relname,definition""",
        """SELECT c.relname,t.tgname,t.tgenabled,pg_get_triggerdef(t.oid) AS definition FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND NOT t.tgisinternal ORDER BY c.relname,t.tgname""",
        """SELECT c.relname,r.rulename,pg_get_ruledef(r.oid) AS definition FROM pg_rewrite r JOIN pg_class c ON c.oid=r.ev_class JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s ORDER BY c.relname,r.rulename""",
    )
    rows = [connection.execute(query, (schema,)).fetchall() for query in queries]
    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def validate_work_schema(
    connection: Connection, settings: PostgresSettings, *, owner: bool = False
) -> WorkLimits:
    connection.execute("SET search_path TO pg_catalog")
    _metadata_preflight(connection, settings.schema)
    tables = ALL_TABLES
    objects = connection.execute(
        """SELECT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=%s) OR EXISTS(SELECT 1 FROM pg_collation c JOIN pg_namespace n ON n.oid=c.collnamespace WHERE n.nspname=%s) OR EXISTS(SELECT 1 FROM pg_operator o JOIN pg_namespace n ON n.oid=o.oprnamespace WHERE n.nspname=%s) OR EXISTS(SELECT 1 FROM pg_opclass o JOIN pg_namespace n ON n.oid=o.opcnamespace WHERE n.nspname=%s) AS unsafe""",
        [settings.schema] * 4,
    ).fetchone()
    if objects is None or objects["unsafe"] is not False:
        raise WorkError("schema_mismatch")
    types = connection.execute(
        """SELECT t.typname,t.typtype,t.typrelid::int,t.typelem::int,c.relname AS relation,e.typname AS element FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace LEFT JOIN pg_class c ON c.oid=t.typrelid LEFT JOIN pg_type e ON e.oid=t.typelem WHERE n.nspname=%s""",
        [settings.schema],
    ).fetchall()
    if len(types) != len(tables) * 2 or {row["typname"] for row in types} != {
        *tables,
        *("_" + name for name in tables),
    }:
        raise WorkError("schema_mismatch")
    for item in types:
        if item["typname"] in tables:
            if (
                item["typtype"] != "c"
                or item["relation"] != item["typname"]
                or item["typelem"] != 0
            ):
                raise WorkError("schema_mismatch")
        elif (
            item["typtype"] != "b"
            or item["typrelid"] != 0
            or item["element"] != "".join(item["typname"][1:])
        ):
            raise WorkError("schema_mismatch")
    require_role(connection, settings.schema, owner=owner)
    _safe_grants(connection, settings.schema)
    relations = connection.execute(
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relkind IN ('r','v','m','f','p') ORDER BY c.relname",
        (settings.schema,),
    ).fetchall()
    if [row["relname"] for row in relations] != sorted(tables):
        raise WorkError("schema_mismatch")
    rows = connection.execute(
        sql.SQL(
            "SELECT singleton,version,definition_sha256,catalog_sha256,max_records,max_cancel_commands FROM {}.schema_metadata"
        ).format(sql.Identifier(settings.schema))
    ).fetchall()
    if len(rows) != 1:
        raise WorkError("schema_mismatch")
    row = rows[0]
    if (
        row["singleton"] is not True
        or type(row["version"]) is not int
        or row["version"] != SCHEMA_VERSION
        or row["definition_sha256"] != DEFINITION_SHA256
        or row["catalog_sha256"] != catalog_sha256(connection, settings.schema)
    ):
        raise WorkError("schema_mismatch")
    try:
        execution_limits(connection, settings.schema)
        return WorkLimits(row["max_records"], row["max_cancel_commands"])
    except WorkError:
        raise WorkError("schema_mismatch") from None


def execution_limits(connection: Connection, schema: str) -> ExecutionLimits:
    """Select only after the complete known catalog has been validated."""
    rows = connection.execute(
        sql.SQL(
            "SELECT singleton,max_active,max_attempts,lease_ms FROM {}.execution_limits"
        ).format(sql.Identifier(schema))
    ).fetchall()
    if len(rows) != 1 or rows[0]["singleton"] is not True:
        raise WorkError("schema_mismatch")
    try:
        return ExecutionLimits(rows[0]["max_active"], rows[0]["max_attempts"], rows[0]["lease_ms"])
    except WorkError:
        raise WorkError("schema_mismatch") from None
