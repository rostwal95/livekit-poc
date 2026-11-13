"""Additive Phase F PostgreSQL catalog; serving never executes this DDL.

Lease timestamps use the database clock. Existing authority data and consent
payloads are not rewritten, and retained epochs survive release and expiry.
"""

DEFINITIONS: dict[str, str] = {
    "execution_limits": "(singleton BOOLEAN CONSTRAINT execution_limits_pk PRIMARY KEY, "
    "maximum_pending INTEGER NOT NULL, maximum_active INTEGER NOT NULL, "
    "maximum_records INTEGER NOT NULL, lease_seconds INTEGER NOT NULL, "
    "CONSTRAINT limits_singleton CHECK(singleton), "
    "CONSTRAINT limits_pending CHECK(maximum_pending BETWEEN 1 AND 100000), "
    "CONSTRAINT limits_active CHECK(maximum_active BETWEEN 1 AND 64 AND maximum_active <= maximum_pending), "
    "CONSTRAINT limits_records CHECK(maximum_records BETWEEN maximum_pending AND 1000000), "
    "CONSTRAINT limits_lease_seconds CHECK(lease_seconds BETWEEN 1 AND 300))",
    "execution_leases": '(task_id TEXT COLLATE "C" CONSTRAINT execution_leases_pk PRIMARY KEY, '
    'scope_id TEXT COLLATE "C" NOT NULL, owner_id TEXT COLLATE "C", epoch BIGINT NOT NULL, '
    "expires_at TIMESTAMP WITH TIME ZONE, claimed_at TIMESTAMP WITH TIME ZONE NOT NULL, "
    "renewed_at TIMESTAMP WITH TIME ZONE NOT NULL, CONSTRAINT leases_execution_fk "
    "FOREIGN KEY(task_id) REFERENCES {schema}.executions(task_id), CONSTRAINT leases_scope_fk "
    "FOREIGN KEY(task_id,scope_id) REFERENCES {schema}.tasks(task_id,scope_id), "
    "CONSTRAINT leases_owner_pair CHECK((owner_id IS NULL)=(expires_at IS NULL)), "
    "CONSTRAINT leases_owner CHECK(owner_id IS NULL OR length(owner_id) BETWEEN 1 AND 128), "
    "CONSTRAINT leases_epoch CHECK(epoch>=1), CONSTRAINT leases_renewal "
    "CHECK(renewed_at>=claimed_at), CONSTRAINT leases_expiry "
    "CHECK(expires_at IS NULL OR expires_at>renewed_at), CONSTRAINT leases_clocks_finite "
    "CHECK(isfinite(claimed_at) AND isfinite(renewed_at) AND "
    "(expires_at IS NULL OR isfinite(expires_at))))",
}

COLUMNS: dict[str, tuple[str, ...]] = {
    "execution_limits": (
        "singleton",
        "maximum_pending",
        "maximum_active",
        "maximum_records",
        "lease_seconds",
    ),
    "execution_leases": (
        "task_id",
        "scope_id",
        "owner_id",
        "epoch",
        "expires_at",
        "claimed_at",
        "renewed_at",
    ),
}
COLUMN_SPECS: dict[str, dict[str, tuple[str, bool]]] = {
    "execution_limits": {
        "singleton": ("boolean", True),
        "maximum_pending": ("integer", True),
        "maximum_active": ("integer", True),
        "maximum_records": ("integer", True),
        "lease_seconds": ("integer", True),
    },
    "execution_leases": {
        "task_id": ("text", True),
        "scope_id": ("text", True),
        "owner_id": ("text", False),
        "epoch": ("bigint", True),
        "expires_at": ("timestamp with time zone", False),
        "claimed_at": ("timestamp with time zone", True),
        "renewed_at": ("timestamp with time zone", True),
    },
}
CHECK_DEFINITIONS: dict[str, str] = {
    "limits_singleton": "CHECK (singleton)",
    "limits_pending": "CHECK (((maximum_pending >= 1) AND (maximum_pending <= 100000)))",
    "limits_active": "CHECK ((((maximum_active >= 1) AND (maximum_active <= 64)) AND (maximum_active <= maximum_pending)))",
    "limits_records": "CHECK (((maximum_records >= maximum_pending) AND (maximum_records <= 1000000)))",
    "limits_lease_seconds": "CHECK (((lease_seconds >= 1) AND (lease_seconds <= 300)))",
    "leases_owner_pair": "CHECK (((owner_id IS NULL) = (expires_at IS NULL)))",
    "leases_owner": "CHECK (((owner_id IS NULL) OR ((length(owner_id) >= 1) AND (length(owner_id) <= 128))))",
    "leases_epoch": "CHECK ((epoch >= 1))",
    "leases_renewal": "CHECK ((renewed_at >= claimed_at))",
    "leases_expiry": "CHECK (((expires_at IS NULL) OR (expires_at > renewed_at)))",
    "leases_clocks_finite": "CHECK ((isfinite(claimed_at) AND isfinite(renewed_at) AND ((expires_at IS NULL) OR isfinite(expires_at))))",
    "metadata_version": "CHECK ((version = 4))",
}
CHECK_TABLES: dict[str, str] = {
    **dict.fromkeys(
        (
            "limits_singleton",
            "limits_pending",
            "limits_active",
            "limits_records",
            "limits_lease_seconds",
        ),
        "execution_limits",
    ),
    **dict.fromkeys(
        (
            "leases_owner_pair",
            "leases_owner",
            "leases_epoch",
            "leases_renewal",
            "leases_expiry",
            "leases_clocks_finite",
        ),
        "execution_leases",
    ),
    "metadata_version": "schema_metadata",
}
KEYS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "execution_limits_pk": ("execution_limits", "p", ("singleton",)),
    "execution_leases_pk": ("execution_leases", "p", ("task_id",)),
    "tasks_identity_scope_key": ("tasks", "u", ("task_id", "scope_id")),
}
FOREIGN_KEYS: dict[str, tuple[str, tuple[str, ...], str, tuple[str, ...]]] = {
    "leases_execution_fk": ("execution_leases", ("task_id",), "executions", ("task_id",)),
    "leases_scope_fk": (
        "execution_leases",
        ("task_id", "scope_id"),
        "tasks",
        ("task_id", "scope_id"),
    ),
}
GRANTS: dict[str, tuple[str, ...]] = {
    "execution_limits": ("SELECT",),
    "execution_leases": ("SELECT", "INSERT", "UPDATE"),
}
OPERATING_INDEXES: dict[str, tuple[str, tuple[str, ...]]] = {
    "leases_expiry_task_idx": ("execution_leases", ("expires_at", "task_id")),
    "leases_owner_task_idx": ("execution_leases", ("owner_id", "task_id")),
}
