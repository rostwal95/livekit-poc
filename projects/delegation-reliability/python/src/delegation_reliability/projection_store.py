"""Private bounded PostgreSQL metadata persistence; never a P1 execution store."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from contextlib import closing
from dataclasses import replace
from typing import Any

import psycopg
from psycopg import Connection, sql

from continuity_lab.work_api import PostgresSettings

from .applicability_schema import APPLICABILITY_DDL, MARKER_V3
from .processing_schema import MARKER_V2, PROCESSING_DDL
from .projection_models import (
    ProjectedResult,
    ProjectionBatch,
    ProjectionBinding,
    ProjectionCheckpoint,
    ProjectionError,
    ProjectionLimits,
    event_digest,
    parse_projected,
)

MARKER = "delegation-result-projection-v1"
DDL = """CREATE TABLE projection_metadata(singleton boolean PRIMARY KEY CHECK(singleton),version smallint NOT NULL CHECK(version=1),definition_sha256 text NOT NULL CHECK(definition_sha256 ~ '^[0-9a-f]{64}$'),catalog_snapshot jsonb NOT NULL,max_records integer NOT NULL CHECK(max_records BETWEEN 1 AND 30000));
CREATE TABLE projection_checkpoint(singleton boolean PRIMARY KEY REFERENCES projection_metadata(singleton),source_id uuid NOT NULL,tenant_id text COLLATE "C" NOT NULL CHECK(octet_length(tenant_id) BETWEEN 1 AND 128),account_id text COLLATE "C" NOT NULL CHECK(octet_length(account_id) BETWEEN 1 AND 128),sequence bigint NOT NULL CHECK(sequence BETWEEN 0 AND 9223372036854775807),record_count integer NOT NULL CHECK(record_count=sequence));
CREATE TABLE projected_results(event_sequence bigint PRIMARY KEY CHECK(event_sequence BETWEEN 1 AND 9223372036854775807),event_id uuid NOT NULL CONSTRAINT projection_event_key UNIQUE,work_id uuid NOT NULL,attempt_id uuid NOT NULL CONSTRAINT projection_attempt_key UNIQUE,result_sha256 text NOT NULL CHECK(result_sha256 ~ '^[0-9a-f]{64}$'),event_sha256 text NOT NULL CHECK(event_sha256 ~ '^[0-9a-f]{64}$'),body_json text NOT NULL CHECK(octet_length(body_json) BETWEEN 1 AND 8192),body_sha256 text NOT NULL CHECK(body_sha256 ~ '^[0-9a-f]{64}$'));"""
DEFINITION = hashlib.sha256(DDL.encode()).hexdigest()
DEFINITION_V2 = hashlib.sha256(
    (DDL + "explicit-projection-upgrade-v2" + PROCESSING_DDL).encode()
).hexdigest()
DEFINITION_V3 = hashlib.sha256(
    (
        DDL
        + "explicit-projection-upgrade-v2"
        + PROCESSING_DDL
        + "explicit-projection-upgrade-v3"
        + APPLICABILITY_DDL
    ).encode()
).hexdigest()
ConnectionType = Connection[dict[str, Any]]


def settings(value: PostgresSettings, *, owner: bool = False) -> PostgresSettings:
    if type(value) is not PostgresSettings:
        raise ProjectionError("invalid_input")
    try:
        copied = replace(value)
    except (ValueError, TypeError):
        raise ProjectionError("invalid_input") from None
    if (
        copied.user != ("continuity_migrator" if owner else "livekit_lab")
        or re.fullmatch(r"p3_projection_[a-z0-9_]{1,49}", copied.schema) is None
    ):
        raise ProjectionError("invalid_input")
    return copied


def catalog(connection: ConnectionType, schema: str) -> dict[str, Any]:
    row = connection.execute(
        """SELECT jsonb_build_object(
'owner',pg_get_userbyid(n.nspowner),'acl',n.nspacl::text,
'relations',COALESCE((SELECT jsonb_agg(jsonb_build_object('name',c.relname,'kind',c.relkind,'owner',pg_get_userbyid(c.relowner),'acl',c.relacl::text,'rls',c.relrowsecurity,'force_rls',c.relforcerowsecurity,
'columns',COALESCE((SELECT jsonb_agg(jsonb_build_array(a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull,a.attidentity,a.attgenerated,pg_get_expr(d.adbin,d.adrelid),a.attacl::text) ORDER BY a.attnum) FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum WHERE a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped),'[]'::jsonb),
'constraints',COALESCE((SELECT jsonb_agg(jsonb_build_array(k.conname,pg_get_constraintdef(k.oid)) ORDER BY k.conname) FROM pg_constraint k WHERE k.conrelid=c.oid),'[]'::jsonb),
'indexes',COALESCE((SELECT jsonb_agg(pg_get_indexdef(i.indexrelid) ORDER BY i.indexrelid::regclass::text) FROM pg_index i WHERE i.indrelid=c.oid),'[]'::jsonb),
'functions',COALESCE((SELECT jsonb_agg(pg_get_triggerdef(t.oid) ORDER BY t.tgname) FROM pg_trigger t WHERE t.tgrelid=c.oid AND NOT t.tgisinternal),'[]'::jsonb),
'rules',COALESCE((SELECT jsonb_agg(pg_get_ruledef(w.oid) ORDER BY w.rulename) FROM pg_rewrite w WHERE w.ev_class=c.oid),'[]'::jsonb)) ORDER BY c.relname) FROM pg_class c WHERE c.relnamespace=n.oid),'[]'::jsonb),
'routines',COALESCE((SELECT jsonb_agg(p.proname ORDER BY p.proname) FROM pg_proc p WHERE p.pronamespace=n.oid),'[]'::jsonb)) AS snapshot FROM pg_namespace n WHERE n.nspname=%s""",
        [schema],
    ).fetchone()
    if row is None or type(row["snapshot"]) is not dict:
        raise ProjectionError("schema_mismatch")
    return row["snapshot"]


def validate(
    connection: ConnectionType,
    value: PostgresSettings,
    *,
    owner: bool = False,
    binding: ProjectionBinding | None = None,
) -> tuple[ProjectionCheckpoint, ProjectionLimits]:
    who = connection.execute(
        "SELECT current_user AS name,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,EXISTS(SELECT 1 FROM pg_auth_members WHERE member=r.oid) AS member,has_database_privilege(current_user,current_database(),'CREATE') AS can_create,has_database_privilege(current_user,current_database(),'TEMPORARY') AS can_temp,EXISTS(SELECT 1 FROM pg_namespace n WHERE n.nspname !~ '^pg_' AND n.nspname<>'information_schema' AND (n.nspowner=r.oid OR has_schema_privilege(current_user,n.oid,'CREATE'))) AS schema_admin FROM pg_roles r WHERE rolname=current_user"
    ).fetchone()
    if (
        who is None
        or who["name"] != ("continuity_migrator" if owner else "livekit_lab")
        or any(
            who[k] is not False
            for k in (
                "rolsuper",
                "rolcreatedb",
                "rolcreaterole",
                "rolreplication",
                "rolbypassrls",
                "member",
            )
        )
        or (
            not owner
            and any(who[k] is not False for k in ("can_create", "can_temp", "schema_admin"))
        )
    ):
        raise ProjectionError("schema_mismatch")
    ns = connection.execute(
        "SELECT pg_get_userbyid(nspowner) AS owner,obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=%s",
        [value.schema],
    ).fetchone()
    if (
        ns is None
        or ns["owner"] != "continuity_migrator"
        or ns["marker"] not in {MARKER, MARKER_V2, MARKER_V3}
    ):
        raise ProjectionError("schema_mismatch")
    actual = catalog(connection, value.schema)
    expected = {
        "projection_metadata",
        "projection_metadata_pkey",
        "projection_checkpoint",
        "projection_checkpoint_pkey",
        "projected_results",
        "projected_results_pkey",
        "projection_event_key",
        "projection_attempt_key",
    }
    if ns["marker"] in {MARKER_V2, MARKER_V3}:
        expected |= {
            "processing_control",
            "processing_control_pkey",
            "processing_acks",
            "processing_acks_pkey",
            "processing_event_key",
        }
    if ns["marker"] == MARKER_V3:
        expected |= {
            "refresh_control",
            "refresh_control_pkey",
            "applicability_heads",
            "applicability_heads_pkey",
            "applicability_refreshes",
            "applicability_refreshes_pkey",
            "applicability_revision_key",
        }
    relations = actual.get("relations")
    if (
        type(relations) is not list
        or len(relations) != len(expected)
        or {r["name"] for r in relations} != expected
        or actual.get("routines") != []
        or any(
            r["owner"] != "continuity_migrator"
            or r["kind"] not in ("r", "i")
            or r["rls"]
            or r["force_rls"]
            or r["functions"]
            or r["rules"]
            for r in relations
        )
    ):
        raise ProjectionError("schema_mismatch")
    rows = connection.execute(
        sql.SQL("SELECT * FROM {}.projection_metadata").format(sql.Identifier(value.schema))
    ).fetchall()
    if len(rows) != 1:
        raise ProjectionError("schema_mismatch")
    metadata = rows[0]
    if (
        metadata["singleton"] is not True
        or metadata["version"] != ({MARKER: 1, MARKER_V2: 2, MARKER_V3: 3}[ns["marker"]])
        or metadata["definition_sha256"]
        != ({MARKER: DEFINITION, MARKER_V2: DEFINITION_V2, MARKER_V3: DEFINITION_V3}[ns["marker"]])
        or metadata["catalog_snapshot"] != actual
    ):
        raise ProjectionError("schema_mismatch")
    limits = ProjectionLimits(metadata["max_records"])
    points = connection.execute(
        sql.SQL(
            "SELECT source_id::text,tenant_id,account_id,sequence,record_count FROM {}.projection_checkpoint"
        ).format(sql.Identifier(value.schema))
    ).fetchall()
    if len(points) != 1:
        raise ProjectionError("schema_mismatch")
    from continuity_lab.work_api import WorkScope

    row = points[0]
    point = ProjectionCheckpoint(
        ProjectionBinding(row["source_id"], WorkScope(row["tenant_id"], row["account_id"])),
        row["sequence"],
        row["record_count"],
    )
    if binding is not None:
        if point.binding.source_id != binding.source_id:
            raise ProjectionError("source_mismatch")
        if point.binding.scope != binding.scope:
            raise ProjectionError("unauthorized")
    totals = connection.execute(
        sql.SQL(
            "SELECT count(*) AS count,min(event_sequence) AS low,max(event_sequence) AS high FROM {}.projected_results"
        ).format(sql.Identifier(value.schema))
    ).fetchone()
    if (
        totals is None
        or totals["count"] != point.record_count
        or point.record_count > limits.max_records
        or (point.record_count == 0 and (totals["low"] is not None or totals["high"] is not None))
        or (point.record_count > 0 and (totals["low"] != 1 or totals["high"] != point.sequence))
    ):
        raise ProjectionError("schema_mismatch")
    return point, limits


class ProjectionStore:
    def __init__(
        self,
        value: PostgresSettings,
        binding: ProjectionBinding,
        failpoint: Callable[[str], None] | None = None,
    ) -> None:
        self.settings = settings(value)
        self.binding = binding
        self.failpoint = failpoint
        self.checkpoint()

    def _table(self, name: str) -> sql.Identifier:
        return sql.Identifier(self.settings.schema, name)

    def _decode(self, row: dict[str, Any]) -> ProjectedResult:
        try:
            body = row["body_json"].encode("utf-8")
            if hashlib.sha256(body).hexdigest() != row["body_sha256"]:
                raise ProjectionError("schema_mismatch")
            result = parse_projected(body)
            if (
                result.event.source_id != self.binding.source_id
                or result.event.scope != self.binding.scope
            ):
                raise ProjectionError("schema_mismatch")
            if (
                result.event.sequence,
                result.event.event_id,
                result.event.work_id,
                result.event.attempt_id,
                result.event.result_sha256,
                event_digest(result.event),
            ) != (
                row["event_sequence"],
                str(row["event_id"]),
                str(row["work_id"]),
                str(row["attempt_id"]),
                row["result_sha256"],
                row["event_sha256"],
            ):
                raise ProjectionError("schema_mismatch")
            return result
        except Exception:  # noqa: BLE001 - fixed safe private storage boundary
            raise ProjectionError("schema_mismatch") from None

    def checkpoint(self) -> ProjectionCheckpoint:
        try:
            with closing(self.settings.connect()) as connection, connection.transaction():
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                return validate(connection, self.settings, binding=self.binding)[0]
        except ProjectionError:
            raise
        except Exception:  # noqa: BLE001 - fixed safe private storage boundary
            raise ProjectionError("storage_unavailable") from None

    def get(self, work_id: str, attempt_id: str) -> ProjectedResult | None:
        try:
            with closing(self.settings.connect()) as connection, connection.transaction():
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                validate(connection, self.settings, binding=self.binding)
                row = connection.execute(
                    sql.SQL(
                        "SELECT * FROM {} WHERE work_id=%s::uuid AND attempt_id=%s::uuid"
                    ).format(self._table("projected_results")),
                    [work_id, attempt_id],
                ).fetchone()
                return None if row is None else self._decode(row)
        except ProjectionError:
            raise
        except Exception:  # noqa: BLE001 - fixed safe private storage boundary
            raise ProjectionError("storage_unavailable") from None

    def _originals(
        self, connection: ConnectionType, rows: tuple[ProjectedResult, ...]
    ) -> tuple[ProjectedResult, ...]:
        found = []
        for draft in rows:
            stored = connection.execute(
                sql.SQL("SELECT * FROM {} WHERE event_sequence=%s").format(
                    self._table("projected_results")
                ),
                [draft.event.sequence],
            ).fetchone()
            if stored is None:
                raise ProjectionError("checkpoint_conflict")
            original = self._decode(stored)
            if (
                event_digest(original.event) != event_digest(draft.event)
                or original.request_sha256 != draft.request_sha256
            ):
                raise ProjectionError("identity_conflict")
            found.append(original)
        return tuple(found)

    def reconcile(
        self, expected: ProjectionCheckpoint, rows: tuple[ProjectedResult, ...]
    ) -> ProjectionBatch | None:
        try:
            with closing(self.settings.connect()) as connection, connection.transaction():
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                point, _limits = validate(connection, self.settings, binding=self.binding)
                if point.sequence < rows[-1].event.sequence:
                    return None
                originals = self._originals(connection, rows)
                return ProjectionBatch(point, point, originals, True)
        except ProjectionError:
            raise
        except Exception:  # noqa: BLE001 - fixed safe private storage boundary
            raise ProjectionError("storage_unavailable") from None

    def apply(
        self, expected: ProjectionCheckpoint, rows: tuple[ProjectedResult, ...]
    ) -> ProjectionBatch:
        committing = False
        try:
            with closing(self.settings.connect()) as connection:
                with connection.transaction():
                    connection.execute(
                        sql.SQL("SELECT singleton FROM {} WHERE singleton FOR UPDATE").format(
                            self._table("projection_checkpoint")
                        )
                    )
                    point, limits = validate(connection, self.settings, binding=self.binding)
                    if point.sequence >= rows[-1].event.sequence:
                        originals = self._originals(connection, rows)
                        return ProjectionBatch(point, point, originals, True)
                    if point != expected:
                        raise ProjectionError("checkpoint_conflict")
                    if point.record_count + len(rows) > limits.max_records:
                        raise ProjectionError("capacity")
                    for row in rows:
                        body = row.canonical()
                        connection.execute(
                            sql.SQL(
                                "INSERT INTO {} VALUES(%s,%s::uuid,%s::uuid,%s::uuid,%s,%s,%s,%s)"
                            ).format(self._table("projected_results")),
                            [
                                row.event.sequence,
                                row.event.event_id,
                                row.event.work_id,
                                row.event.attempt_id,
                                row.event.result_sha256,
                                event_digest(row.event),
                                body.decode("utf-8"),
                                hashlib.sha256(body).hexdigest(),
                            ],
                        )
                    after = ProjectionCheckpoint(
                        self.binding, rows[-1].event.sequence, point.record_count + len(rows)
                    )
                    updated = connection.execute(
                        sql.SQL(
                            "UPDATE {} SET sequence=%s,record_count=%s WHERE singleton AND sequence=%s"
                        ).format(self._table("projection_checkpoint")),
                        [after.sequence, after.record_count, point.sequence],
                    )
                    if updated.rowcount != 1:
                        raise ProjectionError("checkpoint_conflict")
                    if self.failpoint is not None:
                        self.failpoint("projection.before_commit")
                    committing = True
                if self.failpoint is not None:
                    self.failpoint("projection.after_commit")
            return ProjectionBatch(point, after, rows, False)
        except ProjectionError:
            raise
        except psycopg.errors.UniqueViolation:
            raise ProjectionError("identity_conflict") from None
        except Exception:  # noqa: BLE001 - ambiguous transaction acknowledgement is preserved
            raise ProjectionError(
                "acknowledgement_unknown" if committing else "storage_unavailable"
            ) from None
