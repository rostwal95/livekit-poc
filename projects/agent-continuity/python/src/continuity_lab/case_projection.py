"""Bounded current case snapshots and recent persisted observations.

The cursor paginates a fixed observation window. It is scoped to the complete
current snapshot, so a changed/late observation resets the page instead of being
hidden behind an old offset. These summaries are not an append-only event bus.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

from psycopg import sql

from .authorization import AuthenticatedActor
from .case_models import (
    CaseSnapshot,
    Confirmation,
    QuoteSnapshot,
    canonical,
    identity,
    integer,
    parse_confirmation,
    parse_quote,
    utc_instant,
    uuid_identity,
)
from .execution_codec import decode_attempt
from .execution_models import InvalidStoredState, UnsupportedOperation
from .postgres_case import Connection, PostgresCaseAuthority
from .postgres_effects import PostgresEffects
from .postgres_leases import _snapshot as lease_snapshot
from .postgres_lifecycle import PostgresLifecycle, _wait
from .postgres_store import PostgresExecutionStore
from .postgres_unit_of_work import protected_transaction

MAX_RESPONSE_BYTES = 65536
HISTORY_SOURCE_LIMIT = 100
MAX_OBSERVATIONS = 1000
BIGINT_KEYS = frozenset(
    {
        "revision",
        "previous_revision",
        "expected_supplier_revision",
        "version",
        "generation",
        "epoch",
        "case_revision",
    }
)


def strict_json(value: str) -> object:
    """Reject duplicate keys, non-finite constants and invalid UTF-8 text."""
    if type(value) is not str:
        raise ValueError("A canonical JSON string is required")
    value.encode("utf-8")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in items:
            if key in result:
                raise ValueError("Duplicate JSON fields are unsupported")
            result[key] = item
        return result

    def constant(_name: str) -> object:
        raise ValueError("Non-finite JSON is unsupported")

    return json.loads(value, object_pairs_hook=pairs, parse_constant=constant)


def parse_confirmation_payload(value: str, *, explicit: bool) -> Confirmation:
    if explicit is not True:
        raise ValueError("Exact explicit confirmation is required")
    if type(value) is not str or not 1 <= len(value.encode("utf-8")) <= 4096:
        raise ValueError("Exact quote payload must be bounded UTF-8 JSON")
    parsed = strict_json(value)
    quote = parse_quote(parsed)
    if canonical(quote.payload()) != value:
        raise ValueError("Exact quote payload must retain its canonical bytes")
    return Confirmation(quote, True)


def wire_value(value: object, key: str = "") -> object:
    if key in BIGINT_KEYS and value is not None:
        return str(integer(value))
    if value is None or type(value) in {str, bool}:
        return value
    if type(value) is int:
        integer(value, maximum=9007199254740991)
        return value
    if isinstance(value, Mapping):
        if not all(type(name) is str for name in value):
            raise ValueError("Wire fields must be text")
        return {name: wire_value(item, name) for name, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [wire_value(item) for item in value]
    raise ValueError("Unsupported projection value")


def quote_payload(quote: QuoteSnapshot) -> dict[str, object]:
    display = wire_value(quote.payload())
    assert isinstance(display, dict)
    display["confirmation_payload"] = canonical(quote.payload())
    return display


@dataclass(frozen=True, slots=True)
class CaseProjection:
    _json: str = field(repr=False)

    @classmethod
    def create(cls, value: dict[str, object]) -> CaseProjection:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        if len(encoded.encode("utf-8")) > MAX_RESPONSE_BYTES:
            raise InvalidStoredState("Current projection exceeds its response bound")
        return cls(encoded)

    def payload(self) -> dict[str, object]:
        value = json.loads(self._json)
        if type(value) is not dict:
            raise InvalidStoredState("Projection payload is invalid")
        return cast(dict[str, object], value)


def _cursor(revision: str, offset: int) -> str:
    raw = canonical({"v": 1, "revision": revision, "offset": offset}).encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(value: str | None) -> tuple[str, int] | None:
    if value is None:
        return None
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9_-]{1,512}", value) is None:
        raise ValueError("Projection cursor is malformed")
    try:
        decoded = base64.b64decode(
            value + "=" * ((-len(value)) % 4), altchars=b"-_", validate=True
        ).decode("ascii")
        item = strict_json(decoded)
        if type(item) is not dict or set(item) != {"v", "revision", "offset"}:
            raise ValueError("Projection cursor fields are invalid")
        if (
            type(item["v"]) is not int
            or item["v"] != 1
            or type(item["revision"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", item["revision"]) is None
        ):
            raise ValueError("Projection cursor version is invalid")
        offset = integer(item["offset"], maximum=MAX_OBSERVATIONS)
        if _cursor(item["revision"], offset) != value:
            raise ValueError("Projection cursor is not canonical")
        return item["revision"], offset
    except (ValueError, UnicodeError, binascii.Error, KeyError, TypeError) as error:
        raise ValueError("Projection cursor is invalid") from error


class PostgresCaseProjection:
    def __init__(
        self,
        executions: PostgresExecutionStore,
        *,
        cases: PostgresCaseAuthority | None = None,
        lifecycle: PostgresLifecycle | None = None,
        effects: PostgresEffects | None = None,
    ) -> None:
        self.executions = executions
        self.cases = cases or PostgresCaseAuthority(executions)
        self.lifecycle = lifecycle or PostgresLifecycle(executions, cases=self.cases)
        self.effects = effects or PostgresEffects(executions, cases=self.cases)
        if any(
            owner.executions is not executions
            for owner in (self.cases, self.lifecycle, self.effects)
        ):
            raise ValueError("Projection requires one durable execution authority")

    def _table(self, name: str) -> sql.Identifier:
        return sql.Identifier(self.executions.settings.schema, name)

    def _observations(
        self, connection: Connection, case: CaseSnapshot
    ) -> tuple[list[dict[str, object]], int, bool]:
        events: list[dict[str, object]] = []
        execution = self.executions._get(connection, case.scope_id, case.task_id)

        def add(
            event_id: str,
            kind: str,
            state: str,
            stamp: str,
            details: dict[str, object] | None = None,
        ) -> None:
            identity(event_id)
            utc_instant(stamp)
            events.append(
                {
                    "event_id": event_id,
                    "kind": kind,
                    "state": state,
                    "observed_at": stamp,
                    "details": details or {},
                }
            )

        add(
            "task:" + hashlib.sha256(case.task_id.encode("utf-8")).hexdigest(),
            "task",
            "accepted",
            execution.created_at,
        )
        total = 1
        truncated = False
        sources = [
            ("execution_attempts", "task_id", case.task_id, "attempt_id", "started_at"),
            ("quotes", "task_id", case.task_id, "quote_id", "created_at"),
            ("confirmations", "task_id", case.task_id, "confirmation_id", "created_at"),
            ("execution_waits", "task_id", case.task_id, "wait_id", "created_at"),
            ("cancellation_commands", "task_id", case.task_id, "cancellation_id", "created_at"),
        ]
        if case.intent is not None:
            sources.append(
                (
                    "mutation_attempts",
                    "intent_id",
                    case.intent.intent_id,
                    "attempt_id",
                    "started_at",
                )
            )
        for table, column, binding, key, stamp in sources:
            count = connection.execute(
                sql.SQL("SELECT COUNT(*) AS n FROM {} WHERE {}=%s").format(
                    self._table(table), sql.Identifier(column)
                ),
                (binding,),
            ).fetchone()
            if count is None or type(count["n"]) is not int or count["n"] < 0:
                raise InvalidStoredState("Observation count is unavailable")
            total += count["n"]
            truncated = truncated or count["n"] > HISTORY_SOURCE_LIMIT
            rows = connection.execute(
                sql.SQL("SELECT * FROM {} WHERE {}=%s ORDER BY {} DESC,{} DESC LIMIT %s").format(
                    self._table(table),
                    sql.Identifier(column),
                    sql.Identifier(stamp),
                    sql.Identifier(key),
                ),
                (binding, HISTORY_SOURCE_LIMIT),
            ).fetchall()
            for row in rows:
                uuid_identity(row[key])
                if table == "execution_attempts":
                    attempt = decode_attempt(row)
                    add(
                        "inquiry-attempt:" + attempt.attempt_id,
                        "inquiry_attempt",
                        attempt.status.value,
                        attempt.finished_at or attempt.started_at,
                        {
                            "attempt_no": attempt.attempt_no,
                            "error_code": None
                            if attempt.error_code is None
                            else attempt.error_code.value,
                        },
                    )
                elif table == "quotes":
                    quote = parse_quote(strict_json(row["payload_json"]))
                    if quote.task_id != case.task_id or (
                        quote.schema_version == 2 and quote.case_id != case.case_id
                    ):
                        raise InvalidStoredState("Quote observation belongs to another case")
                    if canonical(quote.payload()) != row["payload_json"]:
                        raise InvalidStoredState("Quote observation is not canonical")
                    add(
                        "quote:" + quote.quote_id,
                        "quote",
                        "published",
                        row["created_at"],
                        {"quote_id": quote.quote_id, "revision": str(quote.revision)},
                    )
                elif table == "confirmations":
                    confirmation = parse_confirmation(strict_json(row["payload_json"]))
                    if (
                        confirmation.quote.task_id != case.task_id
                        or row["actor_id"] != case.actor_id
                        or row["scope_id"] != case.scope_id
                        or canonical(confirmation.payload()) != row["payload_json"]
                    ):
                        raise InvalidStoredState(
                            "Confirmation observation has invalid owner evidence"
                        )
                    add(
                        "confirmation:" + row[key],
                        "confirmation",
                        "committed",
                        row["created_at"],
                        {"quote_id": confirmation.quote.quote_id},
                    )
                elif table == "execution_waits":
                    waiting = _wait(row)
                    add(
                        "wait:" + waiting.wait_id,
                        "wait",
                        waiting.state.value,
                        waiting.finished_at or waiting.created_at,
                        {"quote_id": waiting.quote.quote_id},
                    )
                elif table == "cancellation_commands":
                    receipt = self.effects._cancel_receipt(row, case, False)
                    add(
                        "cancellation:" + receipt.cancellation_id,
                        "cancellation",
                        receipt.disposition.value,
                        receipt.created_at,
                        {"disposition": receipt.disposition.value},
                    )
                else:
                    from .effect_models import EffectFailure

                    if row["state"] not in {
                        "started",
                        "interrupted",
                        "succeeded",
                        "failed",
                        "uncertain",
                        "cancelled",
                    }:
                        raise InvalidStoredState(
                            "Mutation attempt observation has an invalid state"
                        )
                    number = integer(row["attempt_no"], maximum=100)
                    code = (
                        None
                        if row["error_code"] is None
                        else EffectFailure(row["error_code"]).value
                    )
                    add(
                        "mutation-attempt:" + row[key],
                        "mutation_attempt",
                        row["state"],
                        row["finished_at"] or row["started_at"],
                        {"attempt_no": number, "error_code": code},
                    )
        if len(events) > MAX_OBSERVATIONS:
            raise InvalidStoredState("Observation window exceeds its finite bound")
        return events, total, truncated

    def get(
        self, *, actor: AuthenticatedActor, task_id: str, cursor: str | None = None, limit: int = 10
    ) -> CaseProjection:
        if type(actor) is not AuthenticatedActor:
            raise ValueError("A trusted authenticated actor is required")
        task_id = identity(task_id)
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("Projection page limit must be between 1 and 50")
        # Owner authorization precedes cursor decoding and every historical read.
        with protected_transaction(self.executions) as connection:
            case = self.cases.get_in_transaction(connection, actor, task_id)
            supplied = _decode_cursor(cursor)
            metadata = connection.execute(
                sql.SQL("SELECT version FROM {} WHERE singleton").format(
                    self._table("schema_metadata")
                )
            ).fetchone()
            if metadata is None or metadata["version"] != 4:
                raise UnsupportedOperation("Business projection requires schema v4")
            execution, control = self.lifecycle._current(connection, actor.scope_id, task_id)
            lease_row = connection.execute(
                sql.SQL("SELECT * FROM {} WHERE task_id=%s AND scope_id=%s").format(
                    self._table("execution_leases")
                ),
                (task_id, actor.scope_id),
            ).fetchone()
            lease = (
                None if lease_row is None else lease_snapshot(lease_row, actor.scope_id, task_id)
            )
            effect_row = self.effects._effect_row(connection, task_id)
            effect = None if effect_row is None else self.effects._snapshot(effect_row, case)
            event = self.effects._completion(connection, case)
            if effect is not None and (
                (effect.state.value in {"succeeded", "failed", "uncertain", "cancelled"})
                != (event is not None)
            ):
                raise InvalidStoredState("Mutation observation and completion disagree")
            delivery = None if event is None else self.effects._delivery(connection, event)
            try:
                observations, total, truncated = self._observations(connection, case)
            except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as error:
                raise InvalidStoredState("Recent observation evidence is invalid") from error
            if event is not None:
                observations.append(
                    {
                        "event_id": "outcome:" + event.event_id,
                        "kind": "outcome",
                        "state": event.outcome.state.value,
                        "observed_at": event.created_at,
                        "details": {},
                    }
                )
                total += 1
            if delivery is not None:
                observations.append(
                    {
                        "event_id": "delivery:" + delivery.event.event_id,
                        "kind": "delivery",
                        "state": delivery.state.value,
                        "observed_at": delivery.updated_at,
                        "details": {},
                    }
                )
                total += 1
            observations.sort(
                key=lambda item: (str(item["observed_at"]), str(item["event_id"])), reverse=True
            )
            confirmation_state = (
                "cancelled"
                if case.cancelled and case.intent is None
                else "committed"
                if case.intent is not None
                else "required"
                if case.quote is not None
                else "not_requested"
            )
            inquiry = {
                "state": execution.status.value,
                "version": str(execution.version),
                "effect_id": execution.effect_id,
                "request": execution.request.payload(),
                "result": None if execution.result is None else execution.result.payload(),
                "error_code": None if execution.error_code is None else execution.error_code.value,
                "created_at": execution.created_at,
                "updated_at": execution.updated_at,
            }
            continuation = {
                "state": control.state.value,
                "version": str(control.version),
                "deadline": control.deadline,
                "next_attempt_at": control.next_attempt_at,
                "error_code": None if control.error_code is None else control.error_code.value,
                "last_failure": None
                if control.last_failure is None
                else control.last_failure.value,
                "lease": None
                if lease is None
                else {
                    "owner_id": lease.owner_id,
                    "epoch": str(lease.epoch),
                    "expires_at": lease.expires_at,
                    "claimed_at": lease.claimed_at,
                    "renewed_at": lease.renewed_at,
                },
            }
            mutation = (
                None
                if effect is None
                else {
                    "state": effect.state.value,
                    "generation": str(effect.generation),
                    "attempt_no": effect.attempt_no,
                    "dispatch_count": effect.dispatch_count,
                    "result": None
                    if effect.result is None
                    else wire_value(effect.result.payload()),
                    "error_code": None if effect.error_code is None else effect.error_code.value,
                    "updated_at": effect.updated_at,
                }
            )
            outcome = (
                None
                if event is None
                else {
                    "state": event.outcome.state.value,
                    "result": None
                    if event.outcome.result is None
                    else wire_value(event.outcome.result.payload()),
                    "error_code": None
                    if event.outcome.error_code is None
                    else event.outcome.error_code.value,
                    "cancellation": event.outcome.cancellation.value,
                    "created_at": event.outcome.created_at,
                    "intent_id": event.outcome.intent_id,
                    "effect_id": event.outcome.effect_id,
                    "event_id": event.event_id,
                }
            )
            transport = (
                None
                if delivery is None
                else {
                    "state": delivery.state.value,
                    "event_id": delivery.event.event_id,
                    "target_id": delivery.target_id,
                    "generation": str(delivery.generation),
                    "attempts": delivery.attempts,
                    "next_attempt_at": delivery.next_attempt_at,
                    "error_code": delivery.error_code,
                    "updated_at": delivery.updated_at,
                }
            )
            value: dict[str, object] = {
                "schema_version": 1,
                "task_id": task_id,
                "case_id": case.case_id,
                "case_revision": str(case.revision),
                "request_key": execution.idempotency_key,
                "request": case.request.payload(),
                "inquiry": inquiry,
                "lifecycle": continuation,
                "quote": None if case.quote is None else quote_payload(case.quote),
                "confirmation": {
                    "state": confirmation_state,
                    "intent_id": None if case.intent is None else case.intent.intent_id,
                    "confirmation_id": None if case.intent is None else case.intent.confirmation_id,
                    "committed_at": None if case.intent is None else case.intent.created_at,
                },
                "effect": mutation,
                "outcome": outcome,
                "delivery": transport,
                "events_total": integer(total, maximum=9007199254740991),
                "history_truncated": truncated,
            }
            fingerprint = canonical(
                {
                    "actor_id": actor.actor_id,
                    "scope_id": actor.scope_id,
                    "snapshot": value,
                    "observations": observations,
                }
            )
            if len(fingerprint.encode("utf-8")) > 1048576:
                raise InvalidStoredState("Projection fingerprint exceeds its finite bound")
            revision = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
            reset = supplied is not None and supplied[0] != revision
            offset = 0 if supplied is None or reset else supplied[1]
            if offset > len(observations):
                raise ValueError("Projection cursor offset exceeds the observation window")
            page = observations[offset : offset + limit]
            value.update(
                {
                    "events": page,
                    "projection_revision": revision,
                    "next_cursor": _cursor(revision, offset + len(page))
                    if offset + len(page) < len(observations)
                    else None,
                    "has_more": offset + len(page) < len(observations),
                    "cursor_reset": reset,
                }
            )
            return CaseProjection.create(value)
