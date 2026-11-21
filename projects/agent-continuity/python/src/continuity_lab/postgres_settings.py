"""Explicit local PostgreSQL connection settings; credentials never enter a DSN."""

from __future__ import annotations

import hashlib
import os
import re
import struct
from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .execution_models import StorageUnavailable

_IDENTIFIER = re.compile(r"[a-z][a-z0-9_]{0,62}")
_APPLICATION_NAMES = frozenset(
    {
        "continuity-runtime",
        "continuity-migrate",
        "continuity-test",
    }
)


def validate_identifier(value: str) -> str:
    """Validate a trusted configuration identifier, without reflecting its value."""
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError("PostgreSQL identifier must use the supported lowercase format")
    return value


def advisory_keys(schema: str, purpose: str) -> tuple[int, int]:
    """Database-local cooperating lock keys, shared by runtime and migration."""
    validate_identifier(schema)
    if type(purpose) is not str or purpose not in {"admission", "worker"}:
        raise ValueError("Unsupported PostgreSQL lock purpose")
    digest = hashlib.sha256(f"continuity-v1:{schema}:{purpose}".encode("ascii")).digest()
    return struct.unpack(">ii", digest[:8])


@dataclass(frozen=True, slots=True)
class PostgresSettings:
    host: str = "127.0.0.1"
    port: int = 15432
    dbname: str = "livekit_lab"
    user: str = "livekit_lab"
    password: str = field(default="", repr=False)
    schema: str = "continuity"

    def __post_init__(self) -> None:
        if type(self.host) is not str or self.host not in {"127.0.0.1", "localhost", "postgres"}:
            raise ValueError("Only the documented local PostgreSQL hosts are supported")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("PostgreSQL port is invalid")
        for value in (self.dbname, self.user, self.schema):
            validate_identifier(value)
        if (
            type(self.password) is not str
            or not self.password
            or len(self.password) > 128
            or any(character in self.password for character in "\0\r\n")
        ):
            raise ValueError("PostgreSQL password is missing or invalid")

    @classmethod
    def from_env(cls, prefix: str = "P1_POSTGRES_") -> PostgresSettings:
        """Read only named explicit settings; callers own environment provisioning."""
        if type(prefix) is not str or prefix not in {
            "P1_POSTGRES_",
            "P1_MIGRATION_",
            "P1_TEST_POSTGRES_",
        }:
            raise ValueError("Unsupported PostgreSQL configuration prefix")
        try:
            return cls(
                host=os.environ.get(prefix + "HOST", "127.0.0.1"),
                port=int(os.environ.get(prefix + "PORT", "15432")),
                dbname=os.environ.get(prefix + "DB", "livekit_lab"),
                user=os.environ.get(
                    prefix + "USER",
                    "continuity_migrator" if prefix == "P1_MIGRATION_" else "livekit_lab",
                ),
                password=os.environ[prefix + "PASSWORD"],
                schema=os.environ.get(prefix + "SCHEMA", "continuity"),
            )
        except (KeyError, ValueError) as error:
            raise ValueError("PostgreSQL configuration is incomplete or invalid") from error

    def connect(
        self,
        *,
        application_name: str = "continuity-runtime",
    ) -> psycopg.Connection[dict[str, Any]]:
        """Open an owned autocommit connection with finite local budgets.

        Explicit options override inherited PGOPTIONS. TLS is disabled only for
        this fixed loopback/Docker-network fixture; remote deployment is outside
        this configuration and needs its own verified transport policy.
        """
        if type(application_name) is not str or application_name not in _APPLICATION_NAMES:
            raise ValueError("Unsupported PostgreSQL application name")
        # libpq consults hostaddr independently of host. A service file can also
        # supply it, so explicit host/user/password alone do not isolate target
        # selection from an inherited developer shell. Reject these selectors
        # without mutating the process-wide environment in concurrent callers.
        if any(os.environ.get(key) for key in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE")):
            raise ValueError("Inherited PostgreSQL target selectors are unsupported")
        try:
            return psycopg.connect(
                host=self.host,
                port=self.port,
                dbname=self.dbname,
                user=self.user,
                password=self.password,
                connect_timeout=5,
                application_name=application_name,
                options="-c statement_timeout=5000 -c lock_timeout=1000 -c idle_in_transaction_session_timeout=5000",
                sslmode="disable",
                gssencmode="disable",
                target_session_attrs="read-write",
                client_encoding="UTF8",
                autocommit=True,
                row_factory=dict_row,
            )
        except psycopg.Error as error:
            raise StorageUnavailable("PostgreSQL connection is unavailable") from error
