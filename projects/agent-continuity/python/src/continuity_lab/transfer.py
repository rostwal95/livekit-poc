"""Immutable, deterministic transfer content for the explicit inquiry cutover."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from uuid import UUID

Row = Mapping[str, object]
TASK_COLUMNS = frozenset(
    {"task_id", "scope_id", "idempotency_key", "payload", "status", "created_at"}
)
EXECUTION_COLUMNS = frozenset(
    {
        "task_id",
        "operation",
        "status",
        "effect_id",
        "version",
        "created_at",
        "updated_at",
        "result_json",
        "error_code",
    }
)
ATTEMPT_COLUMNS = frozenset(
    {"attempt_id", "task_id", "attempt_no", "status", "started_at", "finished_at", "error_code"}
)


def snapshot_digest(
    tasks: Sequence[Row], executions: Sequence[Row], attempts: Sequence[Row]
) -> str:
    def identity(value: object) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError("Transfer identity must be text")
        return value

    def number(value: object) -> int:
        if type(value) is not int or value < 1:
            raise ValueError("Transfer attempt number must be a positive integer")
        return value

    body = {
        "tasks": sorted((dict(row) for row in tasks), key=lambda row: identity(row["task_id"])),
        "executions": sorted(
            (dict(row) for row in executions), key=lambda row: identity(row["task_id"])
        ),
        "attempts": sorted(
            (dict(row) for row in attempts),
            key=lambda row: (
                identity(row["task_id"]),
                number(row["attempt_no"]),
                identity(row["attempt_id"]),
            ),
        ),
    }
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class TransferSnapshot:
    tasks: tuple[Row, ...]
    executions: tuple[Row, ...]
    attempts: tuple[Row, ...]
    migration_id: str
    source_digest: str


def make_snapshot(
    tasks: Sequence[Row],
    executions: Sequence[Row],
    attempts: Sequence[Row],
    *,
    migration_id: str,
) -> TransferSnapshot:
    if not isinstance(migration_id, str) or str(UUID(migration_id)) != migration_id:
        raise ValueError("Migration identity must be a canonical UUID")

    def frozen(rows: Sequence[Row], fields: frozenset[str]) -> tuple[Row, ...]:
        values: list[Row] = []
        for row in rows:
            value = dict(row)
            if set(value) != fields or any(
                item is not None and type(item) not in {str, int} for item in value.values()
            ):
                raise ValueError("Transfer rows contain unsupported fields or values")
            values.append(MappingProxyType(value))
        return tuple(values)

    task_rows = frozen(tasks, TASK_COLUMNS)
    execution_rows = frozen(executions, EXECUTION_COLUMNS)
    attempt_rows = frozen(attempts, ATTEMPT_COLUMNS)
    return TransferSnapshot(
        task_rows,
        execution_rows,
        attempt_rows,
        migration_id,
        snapshot_digest(task_rows, execution_rows, attempt_rows),
    )
