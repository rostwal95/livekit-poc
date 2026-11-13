"""Fail-closed ownership for disposable media qualification resources.

An absent target is checked before creation. PostgreSQL staging is marked before
cutover; cleanup verifies role, unpredictable marker and namespace OID. A volume
candidate is recorded before Docker's possibly lost acknowledgement and may only
be mounted/removed after its exact label is independently observed.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Callable
from contextlib import closing
from typing import Any

from psycopg import sql

NAMESPACE = re.compile(r"p1_conversation_demo_[0-9a-f]{32}\Z")
NAMESPACE_QUERY = "SELECT oid,pg_get_userbyid(nspowner) AS owner,obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=%s"


class SchemaOwnership:
    """Only a fresh empty staging schema can become a cleanup candidate."""

    def __init__(self, settings: Any) -> None:
        if NAMESPACE.fullmatch(settings.schema) is None:
            raise ValueError("Invalid disposable namespace")
        self.settings = settings
        self.marker = "p1-media-owner-v1:" + secrets.token_hex(32)
        self.oid: int | None = None
        self.candidate = False

    def prepare(self, install: Callable[[Any], object]) -> None:
        with closing(self.settings.connect(application_name="continuity-migrate")) as connection:
            if connection.execute(NAMESPACE_QUERY, (self.settings.schema,)).fetchone() is not None:
                raise ValueError("Disposable namespace already exists")
        # A failed/lost DDL acknowledgement is never permission to drop a schema
        # without the random marker. Unknown staging is left for explicit review.
        self.candidate = True
        install(self.settings)
        with (
            closing(self.settings.connect(application_name="continuity-migrate")) as connection,
            connection.transaction(),
        ):
            row = connection.execute(NAMESPACE_QUERY, (self.settings.schema,)).fetchone()
            metadata = connection.execute(
                sql.SQL(
                    "SELECT version,state,migration_id,source_digest,(SELECT COUNT(*) FROM {}) AS tasks FROM {} WHERE singleton"
                ).format(
                    sql.Identifier(self.settings.schema, "tasks"),
                    sql.Identifier(self.settings.schema, "schema_metadata"),
                )
            ).fetchone()
            if (
                row is None
                or type(row["oid"]) is not int
                or row["owner"] != "continuity_migrator"
                or row["marker"] is not None
                or metadata
                != {
                    "version": 1,
                    "state": "staging",
                    "migration_id": None,
                    "source_digest": None,
                    "tasks": 0,
                }
            ):
                raise ValueError("Fresh empty staging ownership is required")
            connection.execute(
                sql.SQL("COMMENT ON SCHEMA {} IS {}").format(
                    sql.Identifier(self.settings.schema), sql.Literal(self.marker)
                )
            )
            self.oid = row["oid"]

    def cleanup(self) -> None:
        if not self.candidate:
            return
        with (
            closing(self.settings.connect(application_name="continuity-migrate")) as connection,
            connection.transaction(),
        ):
            row = connection.execute(NAMESPACE_QUERY, (self.settings.schema,)).fetchone()
            if row is None:
                return
            if (
                row["owner"] != "continuity_migrator"
                or row["marker"] != self.marker
                or self.oid is None
                or row["oid"] != self.oid
            ):
                raise ValueError("Disposable namespace ownership is unconfirmed")
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.settings.schema))
            )
            if connection.execute(NAMESPACE_QUERY, (self.settings.schema,)).fetchone() is not None:
                raise ValueError("Disposable namespace survived cleanup")


def volume_prepare(
    name: str,
    *,
    label_key: str,
    run_id: str,
    candidates: list[str],
    command: Callable[..., str],
) -> None:
    if (
        re.fullmatch(r"p1-g-[0-9a-f]{32}-(application|fixtures)", name) is None
        or re.fullmatch(r"[0-9a-f]{32}", run_id) is None
        or not name.startswith("p1-g-" + run_id + "-")
        or label_key != "io.livekit-ecosystem.demo"
        or name in candidates
    ):
        raise ValueError("Invalid disposable volume ownership")
    if command(["docker", "volume", "ls", "-q", "--filter", "name=^" + name + "$"]):
        raise ValueError("Disposable volume already exists")
    candidates.append(name)
    command(["docker", "volume", "create", "--label", label_key + "=" + run_id, name])
    volume_verify(name, label_key=label_key, run_id=run_id, command=command)


def volume_verify(name: str, *, label_key: str, run_id: str, command: Callable[..., str]) -> None:
    if (
        command(
            [
                "docker",
                "volume",
                "inspect",
                "--format",
                '{{ index .Labels "' + label_key + '" }}',
                name,
            ]
        )
        != run_id
    ):
        raise ValueError("Disposable volume label does not match its owner")
