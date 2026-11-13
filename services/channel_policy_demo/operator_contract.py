"""Closed browser observations and original simulated-SMS commands.

These values contain no account selector or backend capability. Progress counts
describe P2 dispatch observations, never specialist completion or acknowledgement.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID

from .discovery import DiscoveryPage, encode_discovery_page, parse_discovery_page

REQUEST_BYTES = 32768
RESPONSE_BYTES = 16384
SMS_BODY_BYTES = 4096
OperatorCode = Literal[
    "invalid_input",
    "unauthorized",
    "conflict",
    "closed",
    "capacity",
    "unavailable",
    "outcome_unknown",
    "cleanup_incomplete",
    "recovery_required",
]
OPERATOR_CODES = frozenset(
    {
        "invalid_input",
        "unauthorized",
        "conflict",
        "closed",
        "capacity",
        "unavailable",
        "outcome_unknown",
        "cleanup_incomplete",
        "recovery_required",
    }
)


class OperatorError(Exception):
    def __init__(self, code: OperatorCode = "unavailable") -> None:
        self.code: OperatorCode = (
            code if type(code) is str and code in OPERATOR_CODES else "unavailable"
        )
        super().__init__(self.code)


def require(value: bool, code: OperatorCode = "invalid_input") -> None:
    if not value:
        raise OperatorError(code)


def uuid_value(value: object) -> str:
    require(type(value) is str and len(value) == 36)
    try:
        text = cast(str, value)
        parsed = UUID(text)
        require(str(parsed) == text and parsed.version == 4)
        return text
    except ValueError:
        raise OperatorError("invalid_input") from None


def timestamp(value: object) -> str:
    require(
        type(value) is str
        and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", value, re.ASCII)
        is not None
    )
    try:
        copied = cast(str, value)
        require(
            datetime.fromisoformat(copied).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            == copied
        )
        return copied
    except ValueError:
        raise OperatorError("invalid_input") from None


def now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def revision(value: object, *, zero: bool = True) -> str:
    require(type(value) is str and re.fullmatch(r"0|[1-9][0-9]{0,18}", value, re.ASCII) is not None)
    text = cast(str, value)
    require((0 if zero else 1) <= int(text) <= 9223372036854775807)
    return text


def fields(value: object, names: set[str]) -> dict[str, object]:
    require(type(value) is dict and set(cast(dict[object, object], value)) == names)
    return cast(dict[str, object], value)


def _pairs(values: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in values:
        require(name not in result)
        result[name] = value
    return result


def _constant(_: str) -> object:
    raise OperatorError("invalid_input")


def decode(raw: bytes, maximum: int = REQUEST_BYTES) -> object:
    require(type(raw) is bytes and 0 < len(raw) <= maximum)
    try:
        return json.loads(
            raw.decode("utf-8", "strict"), object_pairs_hook=_pairs, parse_constant=_constant
        )
    except (ValueError, UnicodeError, RecursionError):
        raise OperatorError("invalid_input") from None


def encode(value: object, maximum: int = RESPONSE_BYTES) -> bytes:
    try:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
            "utf-8", "strict"
        )
        require(0 < len(raw) <= maximum)
        return raw
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise OperatorError("invalid_input") from None


def schema(value: object) -> None:
    require(type(value) is int and value == 1)


def parse_empty(raw: bytes) -> None:
    schema(fields(decode(raw), {"schemaVersion"})["schemaVersion"])


@dataclass(frozen=True, slots=True)
class SmsCommand:
    command_id: str
    occurred_at: str
    body: str

    def __post_init__(self) -> None:
        uuid_value(self.command_id)
        timestamp(self.occurred_at)
        require(type(self.body) is str)
        try:
            require(0 < len(self.body.encode("utf-8", "strict")) <= SMS_BODY_BYTES)
            require("\x00" not in self.body)
        except UnicodeError:
            raise OperatorError("invalid_input") from None

    @property
    def event_id(self) -> str:
        return "cp_sms_" + UUID(self.command_id).hex

    def payload(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "commandId": self.command_id,
            "occurredAt": self.occurred_at,
            "body": self.body,
        }


def parse_sms_command(raw: bytes) -> SmsCommand:
    value = fields(decode(raw), {"schemaVersion", "commandId", "occurredAt", "body"})
    schema(value["schemaVersion"])
    return SmsCommand(
        uuid_value(value["commandId"]), timestamp(value["occurredAt"]), cast(str, value["body"])
    )


@dataclass(frozen=True, slots=True)
class SmsObservation:
    command_id: str
    replayed: bool
    receipt_id: str
    event_id: str
    message_id: str
    acceptance_sequence: str
    accepted_at: str

    def __post_init__(self) -> None:
        uuid_value(self.command_id)
        uuid_value(self.receipt_id)
        expected = "cp_sms_" + UUID(self.command_id).hex
        require(
            type(self.replayed) is bool
            and type(self.event_id) is str
            and type(self.message_id) is str
            and self.event_id == self.message_id == expected
        )
        revision(self.acceptance_sequence, zero=False)
        timestamp(self.accepted_at)

    def payload(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "commandId": self.command_id,
            "replayed": self.replayed,
            "receipt": {
                "receiptId": self.receipt_id,
                "eventId": self.event_id,
                "messageId": self.message_id,
                "acceptanceSequence": self.acceptance_sequence,
                "acceptedAt": self.accepted_at,
            },
        }


@dataclass(frozen=True, slots=True)
class CaseObservation:
    revision: str
    observed_at: str

    def __post_init__(self) -> None:
        revision(self.revision)
        timestamp(self.observed_at)

    def payload(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "case": {"revision": self.revision, "observedAt": self.observed_at},
        }


@dataclass(frozen=True, slots=True)
class ProgressObservation:
    as_of: str
    native: int
    sms: int
    pending: int
    running: int
    dispatched: int
    blocked: int
    exhausted: int
    uncertain: int
    work_known: int

    def __post_init__(self) -> None:
        timestamp(self.as_of)
        values = (
            self.native,
            self.sms,
            self.pending,
            self.running,
            self.dispatched,
            self.blocked,
            self.exhausted,
            self.uncertain,
            self.work_known,
        )
        require(all(type(v) is int and 0 <= v <= 16 for v in values))
        require(self.native + self.sms == sum(values[2:8]) <= 16)
        require(self.work_known <= self.dispatched + self.uncertain)

    def payload(self) -> dict[str, object]:
        names = (
            "native",
            "sms",
            "pending",
            "running",
            "dispatched",
            "blocked",
            "exhausted",
            "uncertain",
            "workKnown",
        )
        return {
            "schemaVersion": 1,
            "asOf": self.as_of,
            "counts": dict(
                zip(
                    names,
                    (
                        self.native,
                        self.sms,
                        self.pending,
                        self.running,
                        self.dispatched,
                        self.blocked,
                        self.exhausted,
                        self.uncertain,
                        self.work_known,
                    ),
                    strict=True,
                )
            ),
        }


def progress_observation(page: DiscoveryPage) -> ProgressObservation:
    try:
        copied = parse_discovery_page(encode_discovery_page(page))
        require(not copied.overflow and copied.next_cursor is None, "capacity")
        counts = {
            name: 0
            for name in (
                "native",
                "sms",
                "pending",
                "running",
                "dispatched",
                "blocked",
                "exhausted",
                "uncertain",
                "work_known",
            )
        }
        for item in copied.items:
            counts[item.source_binding_id] += 1
            counts[item.state] += 1
            counts["work_known"] += int(item.external_receipt_id is not None)
        return ProgressObservation(copied.read_completed_at, **counts)
    except OperatorError:
        raise
    except Exception:  # noqa: BLE001 - untrusted observation never leaks dependency text
        raise OperatorError("unavailable") from None
