"""Validated database-row decoding shared by the supported inquiry adapters."""

import json
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any
from uuid import UUID

from .execution_models import (
    AttemptRecord,
    AttemptStatus,
    ExecutionRecord,
    ExecutionStatus,
    FailureCode,
    InquiryResult,
    InvalidStoredState,
    Operation,
)
from .models import BookingChange

_MAX_INTEGER = 9223372036854775807


def _identity(value: object) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > 128:
        raise ValueError("Invalid stored identity")
    return value


def _uuid(value: object) -> str:
    value = _identity(value)
    if str(UUID(value)) != value:
        raise ValueError("Invalid stored UUID")
    return value


def _integer(value: object, *, minimum: int) -> int:
    if type(value) is not int or not minimum <= value <= _MAX_INTEGER:
        raise ValueError("Invalid stored integer")
    return value


def _timestamp(value: object) -> str:
    if (
        type(value) is not str
        or not 1 <= len(value) <= 64
        or value != value.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or datetime.fromisoformat(value).utcoffset() is None
    ):
        raise ValueError("Invalid stored timestamp")
    # An aware offset/Z representation remains byte-for-byte unchanged. A row
    # reader validates persisted evidence; it must not rewrite its original time.
    return value


def _text(value: object) -> str:
    if type(value) is not str:
        raise ValueError("Invalid stored text")
    return value


def _failure(value: object) -> FailureCode | None:
    return None if value is None else FailureCode(_text(value))


def _body(value: object, fields: set[str]) -> dict[str, Any]:
    body = json.loads(_text(value))
    if type(body) is not dict or set(body) != fields:
        raise ValueError("Invalid stored payload fields")
    return body


def _canonical(request: BookingChange) -> str:
    return json.dumps(request.payload(), sort_keys=True, separators=(",", ":"))


def decode_execution(row: Mapping[str, Any]) -> ExecutionRecord:
    try:
        payload = _body(row["payload"], {"booking_reference", "new_check_in", "confirmed"})
        request = BookingChange(
            payload["booking_reference"],
            date.fromisoformat(_text(payload["new_check_in"])),
            payload["confirmed"],
        )
        if _canonical(request) != row["payload"]:
            raise ValueError("stored request must be canonical")
        task_id = _identity(row["task_id"])
        scope_id = _identity(row["scope_id"])
        key = _identity(row["idempotency_key"])
        effect_id = _uuid(row["effect_id"])
        version = _integer(row["version"], minimum=0)
        created_at, updated_at = _timestamp(row["created_at"]), _timestamp(row["updated_at"])
        operation, status = (
            Operation(_text(row["operation"])),
            ExecutionStatus(_text(row["status"])),
        )
        error_code = _failure(row["error_code"])
        result = None
        if row["result_json"] is not None:
            body = _body(row["result_json"], {"booking_reference", "new_check_in", "available"})
            result = InquiryResult(
                body["booking_reference"],
                date.fromisoformat(_text(body["new_check_in"])),
                body["available"],
            )
            if (
                json.dumps(result.payload(), sort_keys=True, separators=(",", ":"))
                != row["result_json"]
            ):
                raise ValueError("stored result must be canonical")
            if (result.booking_reference, result.new_check_in) != (
                request.booking_reference,
                request.new_check_in,
            ):
                raise ValueError("result does not match request")
        if (status == ExecutionStatus.SUCCEEDED) != (result is not None) or (
            status == ExecutionStatus.FAILED
        ) != (error_code is not None):
            raise ValueError("Invalid stored execution outcome")
        return ExecutionRecord(
            task_id=task_id,
            scope_id=scope_id,
            idempotency_key=key,
            request=request,
            operation=operation,
            status=status,
            effect_id=effect_id,
            version=version,
            created_at=created_at,
            updated_at=updated_at,
            result=result,
            error_code=error_code,
        )
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as error:
        raise InvalidStoredState("Execution contains invalid stored state") from error


def decode_attempt(row: Mapping[str, Any]) -> AttemptRecord:
    try:
        attempt_id, task_id = _uuid(row["attempt_id"]), _identity(row["task_id"])
        number = _integer(row["attempt_no"], minimum=1)
        status = AttemptStatus(_text(row["status"]))
        started_at = _timestamp(row["started_at"])
        finished_at = None if row["finished_at"] is None else _timestamp(row["finished_at"])
        error_code = _failure(row["error_code"])
        if (status == AttemptStatus.STARTED) != (finished_at is None) or (
            status == AttemptStatus.FAILED
        ) != (error_code is not None):
            raise ValueError("Invalid stored attempt outcome")
        return AttemptRecord(
            attempt_id,
            task_id,
            number,
            status,
            started_at,
            finished_at,
            error_code,
        )
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as error:
        raise InvalidStoredState("Attempt contains invalid stored state") from error
