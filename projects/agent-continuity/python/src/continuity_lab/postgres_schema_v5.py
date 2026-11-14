"""Additive retry-pacing PostgreSQL catalog; serving never executes this DDL.

v5 persists when a mutation effect returned to pending by a known
dependency_unavailable failure becomes due again. Existing rows keep a NULL due
time and remain due at once, so no original payload or identity is rewritten.
The two operating indexes serve due selection without changing its result.
"""

from . import postgres_schema_v3 as v3

DDL: tuple[str, ...] = (
    "ALTER TABLE {schema}.mutation_effects ADD COLUMN next_attempt_at TIMESTAMP WITH TIME ZONE",
    (
        "ALTER TABLE {schema}.mutation_effects ADD CONSTRAINT effects_retry_due "
        "CHECK(next_attempt_at IS NULL OR isfinite(next_attempt_at))"
    ),
)

COLUMNS: dict[str, tuple[str, ...]] = {
    "mutation_effects": (*v3.COLUMNS["mutation_effects"], "next_attempt_at"),
}
COLUMN_SPECS: dict[str, dict[str, tuple[str, bool]]] = {
    "mutation_effects": {
        **v3.COLUMN_SPECS["mutation_effects"],
        "next_attempt_at": ("timestamp with time zone", False),
    },
}
CHECK_DEFINITIONS: dict[str, str] = {
    "effects_retry_due": "CHECK (((next_attempt_at IS NULL) OR isfinite(next_attempt_at)))",
    "metadata_version": "CHECK ((version = 5))",
}
CHECK_TABLES: dict[str, str] = {
    "effects_retry_due": "mutation_effects",
    "metadata_version": "schema_metadata",
}
OPERATING_INDEXES: dict[str, tuple[str, tuple[str, ...]]] = {
    "controls_state_task_idx": ("execution_controls", ("state", "task_id")),
    "mutation_effect_due_idx": ("mutation_effects", ("state", "next_attempt_at", "intent_id")),
}
