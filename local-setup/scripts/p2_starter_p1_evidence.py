"""Pure test evidence oracle for the six installed public-P1 adapter groups.

No runtime/P1 imports, service setup, database access, repair or source discovery.
Column inventory is fixed from the reviewed v4 owner definitions (21 tables).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any, cast
from uuid import UUID

OWNER_COLUMNS = {
    "action_intents": (
        "intent_id",
        "task_id",
        "scope_id",
        "actor_id",
        "revision",
        "quote_id",
        "confirmation_id",
        "effect_id",
        "payload_json",
        "created_at",
    ),
    "business_outcomes": ("task_id", "payload_json", "created_at"),
    "cancellation_commands": (
        "cancellation_id",
        "scope_id",
        "task_id",
        "actor_id",
        "command_id",
        "payload_json",
        "disposition",
        "created_at",
    ),
    "cases": (
        "task_id",
        "case_id",
        "scope_id",
        "actor_id",
        "revision",
        "request_json",
        "current_quote_id",
        "cancelled",
        "created_at",
        "updated_at",
    ),
    "completion_deliveries": (
        "event_id",
        "target_id",
        "state",
        "generation",
        "attempts",
        "policy_json",
        "next_attempt_at",
        "error_code",
        "updated_at",
    ),
    "completion_events": ("event_id", "task_id", "payload_json", "created_at"),
    "confirmations": (
        "confirmation_id",
        "task_id",
        "scope_id",
        "actor_id",
        "command_id",
        "payload_json",
        "created_at",
    ),
    "execution_attempts": (
        "attempt_id",
        "task_id",
        "attempt_no",
        "status",
        "started_at",
        "finished_at",
        "error_code",
    ),
    "execution_controls": (
        "task_id",
        "state",
        "policy_json",
        "deadline",
        "next_attempt_at",
        "version",
        "last_failure",
        "error_code",
        "updated_at",
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
    "execution_limits": (
        "singleton",
        "maximum_pending",
        "maximum_active",
        "maximum_records",
        "lease_seconds",
    ),
    "execution_signal_consumptions": ("signal_id", "wait_id", "task_id", "created_at"),
    "execution_signals": (
        "signal_id",
        "scope_id",
        "task_id",
        "actor_id",
        "event_id",
        "payload_json",
        "created_at",
    ),
    "execution_waits": (
        "wait_id",
        "task_id",
        "quote_json",
        "deadline",
        "state",
        "created_at",
        "finished_at",
    ),
    "executions": (
        "task_id",
        "operation",
        "status",
        "effect_id",
        "version",
        "created_at",
        "updated_at",
        "result_json",
        "error_code",
    ),
    "intent_dispatch": ("event_id", "intent_id", "payload_json", "created_at"),
    "mutation_attempts": (
        "attempt_id",
        "intent_id",
        "attempt_no",
        "state",
        "started_at",
        "finished_at",
        "error_code",
    ),
    "mutation_effects": (
        "intent_id",
        "task_id",
        "state",
        "generation",
        "attempt_no",
        "dispatch_count",
        "active_attempt_id",
        "result_json",
        "error_code",
        "dispatched_at",
        "updated_at",
    ),
    "quotes": ("quote_id", "task_id", "revision", "payload_json", "created_at"),
    "schema_metadata": (
        "singleton",
        "version",
        "state",
        "migration_id",
        "source_digest",
    ),
    "tasks": (
        "task_id",
        "scope_id",
        "idempotency_key",
        "payload",
        "status",
        "created_at",
    ),
}

SUPPLIER_COLUMNS = {
    "supplier_metadata": ("singleton", "provider_id", "cooperating"),
    "bookings": ("scope_id", "booking_reference", "check_in", "revision"),
    "inquiry_receipts": (
        "effect_id",
        "scope_id",
        "booking_reference",
        "request_json",
        "result_json",
        "created_at",
    ),
    "mutation_receipts": (
        "effect_id",
        "scope_id",
        "booking_reference",
        "request_json",
        "result_json",
        "created_at",
    ),
    "apply_calls": (
        "call_id",
        "effect_id",
        "scope_id",
        "request_json",
        "outcome",
        "result_json",
        "created_at",
    ),
}
GROUPS = (
    "installed_public_case_identity_scope_read",
    "public_revision_CAS_conflict_unknown_ACK",
    "exact_quote_confirmation_stale_rejection",
    "currentCase_allowlist_excludes_quote_control",
    "revision_zero_read_only_no_dispatch_claim",
    "public_supplier_effect_sources_no_extra_acceptance",
)
PHASES = ("revision", "stale-confirmation", "exact-confirmation", "current-facts")
CURRENT_KEYS = {
    "schemaVersion",
    "source",
    "scope",
    "caseId",
    "conversationId",
    "revision",
    "request",
    "workflow",
    "intent",
    "mutation",
    "supplierResult",
    "sourceRevision",
}
PROJECTION_BASE_KEYS = {
    "schema_version",
    "task_id",
    "case_id",
    "case_revision",
    "request_key",
    "request",
    "inquiry",
    "lifecycle",
    "quote",
    "confirmation",
    "effect",
    "outcome",
    "delivery",
    "events_total",
    "history_truncated",
}
PROJECTION_PAGE_KEYS = {
    "events",
    "projection_revision",
    "next_cursor",
    "has_more",
    "cursor_reset",
}
BIGINT_KEYS = {
    "revision",
    "previous_revision",
    "expected_supplier_revision",
    "version",
    "generation",
    "epoch",
    "case_revision",
}
MAX_BYTES = 16 * 1024 * 1024
MAX_ROWS = 128
ERROR_CODES = frozenset(
    {
        "invalid_bundle",
        "invalid_owner",
        "invalid_shape",
        "invalid_identity",
        "invalid_scope",
        "invalid_fingerprint",
        "changed_read_state",
        "invalid_outcome",
        "invalid_supplier",
        "invalid_steps",
    }
)


class EvidenceError(RuntimeError):
    """Finite body-free evidence failure. Never contains a rejected value."""

    def __init__(self, code: str = "invalid_bundle") -> None:
        self.code = code if code in ERROR_CODES else "invalid_bundle"
        super().__init__(self.code)


def _need(value: bool, code: str = "invalid_bundle") -> None:
    if not value:
        raise EvidenceError(code)


def _object(value: Any, keys: set[str] | None = None) -> dict[str, Any]:
    _need(type(value) is dict, "invalid_shape")
    if keys is not None:
        _need(set(value) == keys, "invalid_shape")
    return cast(dict[str, Any], value)


def _integer(value: Any, minimum: int = 0, maximum: int = 9223372036854775807) -> int:
    _need(type(value) is int and minimum <= value <= maximum, "invalid_shape")
    return cast(int, value)


def _uuid(value: Any) -> str:
    _need(type(value) is str, "invalid_identity")
    try:
        _need(str(UUID(value)) == value, "invalid_identity")
    except (ValueError, AttributeError):
        raise EvidenceError("invalid_identity") from None
    return cast(str, value)


def _sha(value: Any) -> str:
    _need(
        type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value) is not None,
        "invalid_fingerprint",
    )
    return cast(str, value)


def _walk(value: Any, active: set[int], count: list[int], depth: int = 0) -> None:
    count[0] += 1
    _need(count[0] <= 262144 and depth <= 32, "invalid_shape")
    if value is None or type(value) is bool:
        return
    if type(value) is int:
        _integer(value, -9223372036854775808)
        return
    if type(value) is str:
        try:
            _need(len(value.encode("utf-8")) <= 2097152, "invalid_shape")
        except UnicodeError:
            raise EvidenceError("invalid_shape") from None
        return
    _need(type(value) in (list, dict), "invalid_shape")
    _need(id(value) not in active, "invalid_shape")
    active.add(id(value))
    try:
        if type(value) is dict:
            _need(all(type(k) is str for k in value), "invalid_shape")
            for key, item in value.items():
                _walk(key, active, count, depth + 1)
                _walk(item, active, count, depth + 1)
        else:
            for item in value:
                _walk(item, active, count, depth + 1)
    finally:
        active.remove(id(value))


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise EvidenceError("invalid_shape") from None


def _same(a: Any, b: Any, code: str = "invalid_identity") -> None:
    _need(_canonical(a) == _canonical(b), code)


def _payload(value: Any, maximum: int = 65536) -> dict[str, Any]:
    _need(
        type(value) is str and 0 < len(value.encode("utf-8")) <= maximum,
        "invalid_shape",
    )

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in items:
            _need(key not in result, "invalid_shape")
            result[key] = item
        return result

    def constant(_value: str) -> Any:
        raise EvidenceError("invalid_shape")

    try:
        result = json.loads(value, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError):
        raise EvidenceError("invalid_shape") from None
    return _object(result)


def _rows(value: Any, columns: dict[str, tuple[str, ...]]) -> dict[str, list[dict[str, Any]]]:
    result = _object(value, set(columns))
    for table, names in columns.items():
        _need(
            type(result[table]) is list and len(result[table]) <= MAX_ROWS,
            "invalid_shape",
        )
        for row in result[table]:
            _object(row, set(names))
    return result


def _one(rows: list[dict[str, Any]], key: str, value: Any) -> dict[str, Any]:
    found = [r for r in rows if _canonical(r.get(key)) == _canonical(value)]
    _need(len(found) == 1, "invalid_identity")
    return found[0]


def _request(day: int) -> dict[str, Any]:
    return {
        "booking_reference": "DEMO-BK-001",
        "new_check_in": "2030-12-" + str(day).zfill(2),
        "confirmed": True,
    }


def _ui_request(value: Any) -> dict[str, Any]:
    body = _object(value, {"booking_reference", "new_check_in", "confirmed"})
    _need(
        body["booking_reference"] == "DEMO-BK-001" and body["confirmed"] is True,
        "invalid_scope",
    )
    _need(
        type(body["new_check_in"]) is str
        and re.fullmatch(r"2030-12-0[234]", body["new_check_in"]) is not None,
        "invalid_shape",
    )
    return {
        "schemaVersion": 1,
        "kind": "booking_investigation",
        "bookingReference": body["booking_reference"],
        "newCheckIn": body["new_check_in"],
        "investigationConsent": True,
    }


def _scope(slot: str) -> str:
    return "p1_starter_" + slot


def _logical(owner: str, slot: str) -> dict[str, Any]:
    return {
        "scope": {
            "tenantId": "tenant_starter_p1",
            "accountId": "account_starter_" + slot,
        },
        "caseId": "case_starter_" + owner + "_" + slot,
        "conversationId": "conversation_starter_" + owner + "_" + slot,
    }


def _node_case(value: Any, owner: str, slot: str, revision: str, day: int) -> dict[str, Any]:
    case = _object(value, {"scope", "caseId", "revision", "request", "cancelled", "committed"})
    ref = _logical(owner, slot)
    _same(case["scope"], ref["scope"], "invalid_scope")
    _need(
        case["caseId"] == ref["caseId"] and case["revision"] == revision,
        "invalid_identity",
    )
    _same(case["request"], _ui_request(_request(day)))
    _need(case["cancelled"] is False and case["committed"] is False, "invalid_outcome")
    return case


def _wire(value: Any, key: str = "") -> Any:
    if key in BIGINT_KEYS and value is not None:
        return str(_integer(value))
    if type(value) is dict:
        return {name: _wire(item, name) for name, item in value.items()}
    if type(value) is list:
        return [_wire(item) for item in value]
    return value


def _projection(
    value: Any, *, owner: str, slot: str, task: str, case: str, complete: bool
) -> dict[str, Any]:
    body = _object(value, PROJECTION_BASE_KEYS | PROJECTION_PAGE_KEYS)
    _need(
        type(body["schema_version"]) is int and body["schema_version"] == 1,
        "invalid_shape",
    )
    _need(body["task_id"] == task and body["case_id"] == case, "invalid_identity")
    _need(body["request_key"] == "starter-" + owner + "-" + slot, "invalid_identity")
    _need(
        type(body["case_revision"]) is str
        and re.fullmatch(r"0|[1-9][0-9]{0,18}", body["case_revision"]) is not None,
        "invalid_shape",
    )
    _ui_request(body["request"])
    fingerprint = _sha(body["projection_revision"])
    _need(type(body["events"]) is list and len(body["events"]) <= 50, "invalid_shape")
    if complete:
        _need(
            body["has_more"] is False
            and body["history_truncated"] is False
            and body["next_cursor"] is None
            and body["cursor_reset"] is False,
            "invalid_fingerprint",
        )
        _need(_integer(body["events_total"]) == len(body["events"]), "invalid_fingerprint")
        for event in body["events"]:
            _object(event, {"event_id", "kind", "state", "observed_at", "details"})
            _need(
                type(event["event_id"]) is str and type(event["observed_at"]) is str,
                "invalid_shape",
            )
        ordered = sorted(
            body["events"],
            key=lambda e: (e["observed_at"], e["event_id"]),
            reverse=True,
        )
        _same(body["events"], ordered, "invalid_fingerprint")
        material = {
            "actor_id": "starter_actor_" + owner,
            "scope_id": _scope(slot),
            "snapshot": {k: body[k] for k in PROJECTION_BASE_KEYS},
            "observations": body["events"],
        }
        _need(
            hashlib.sha256(_canonical(material).encode()).hexdigest() == fingerprint,
            "invalid_fingerprint",
        )
    return body


def _current(value: Any, projection: dict[str, Any], owner: str, slot: str) -> dict[str, Any]:
    body = _object(value, CURRENT_KEYS)
    ref = _logical(owner, slot)
    confirmation = _object(
        projection["confirmation"],
        {"state", "intent_id", "confirmation_id", "committed_at"},
    )
    lifecycle = _object(projection["lifecycle"])
    effect, outcome = projection["effect"], projection["outcome"]
    result = None
    if outcome is not None:
        result = _object(outcome)["result"]
    if result is None and effect is not None:
        result = _object(effect)["result"]
    expected = {
        "schemaVersion": 1,
        "source": "p1_public_v4",
        **ref,
        "revision": projection["case_revision"],
        "request": _ui_request(projection["request"]),
        "workflow": {
            "taskId": projection["task_id"],
            "state": lifecycle["state"],
            "version": lifecycle["version"],
        },
        "intent": {
            "state": "committed" if confirmation["intent_id"] is not None else "not_committed",
            "intentId": confirmation["intent_id"],
        },
        "mutation": {
            "state": "not_observed" if effect is None else effect["state"],
            "outcome": "not_observed" if outcome is None else outcome["state"],
            "cancellation": "not_observed" if outcome is None else outcome["cancellation"],
            "effectId": None if outcome is None else outcome["effect_id"],
            "outcomeEventId": None if outcome is None else outcome["event_id"],
        },
        "supplierResult": None
        if result is None
        else {
            "supplierId": result["supplier_id"],
            "revision": result["revision"],
            "bookingReference": result["booking_reference"],
            "newCheckIn": result["new_check_in"],
        },
        "sourceRevision": projection["projection_revision"],
    }
    _same(body, expected, "invalid_outcome")
    _object(
        body["request"],
        {
            "schemaVersion",
            "kind",
            "bookingReference",
            "newCheckIn",
            "investigationConsent",
        },
    )
    _object(body["workflow"], {"taskId", "state", "version"})
    _object(body["intent"], {"state", "intentId"})
    _object(
        body["mutation"],
        {"state", "outcome", "cancellation", "effectId", "outcomeEventId"},
    )
    if body["supplierResult"] is not None:
        _object(
            body["supplierResult"],
            {"supplierId", "revision", "bookingReference", "newCheckIn"},
        )
    return body


def _phase(value: Any, owner: str, phase: str) -> dict[str, Any]:
    result = _object(
        value,
        {
            "schemaVersion",
            "mode",
            "phase",
            "owner",
            "groups",
            "facts",
            "metrics",
            "cleanupComplete",
        },
    )
    _need(
        type(result["schemaVersion"]) is int
        and result["schemaVersion"] == 1
        and result["mode"] == "p1-contract"
        and result["phase"] == phase
        and result["owner"] == owner
        and result["cleanupComplete"] is True,
        "invalid_shape",
    )
    expected_groups = {
        "revision": [GROUPS[0], GROUPS[1], GROUPS[4]],
        "stale-confirmation": [],
        "exact-confirmation": [GROUPS[2]],
        "current-facts": [GROUPS[3], GROUPS[5]],
    }
    _same(result["groups"], expected_groups[phase], "invalid_shape")
    expected_metrics = {
        "revision": {
            "case": (6, 3, 2, 1),
            "confirmation": (0, 0, 0, 0),
            "currentCase": (1, 1, 0, 0),
        },
        "stale-confirmation": {
            "case": (2, 2, 0, 0),
            "confirmation": (1, 0, 1, 0),
            "currentCase": (0, 0, 0, 0),
        },
        "exact-confirmation": {
            "case": (1, 1, 0, 0),
            "confirmation": (2, 2, 0, 0),
            "currentCase": (0, 0, 0, 0),
        },
        "current-facts": {
            "case": (0, 0, 0, 0),
            "confirmation": (0, 0, 0, 0),
            "currentCase": (3, 2, 1, 0),
        },
    }
    metrics = _object(result["metrics"], {"case", "confirmation", "currentCase"})
    for source, (started, known, rejected, unknown) in expected_metrics[phase].items():
        _same(
            metrics[source],
            {
                "started": started,
                "known": known,
                "rejected": rejected,
                "unknown": unknown,
                "failed": 0,
                "active": 0,
            },
            "invalid_outcome",
        )
    return _object(result["facts"])


def _time(value: Any) -> datetime:
    _need(type(value) is str, "invalid_shape")
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        raise EvidenceError("invalid_shape") from None
    _need(result.tzinfo is not None, "invalid_shape")
    return result


def _validate_bundle(bundle: Any, *, owner: str) -> dict[str, Any]:
    """Validate all six joins; return only finite names/counts/digests.

    Input rows must be actual complete captures from the separately owned parent.
    This pure oracle cannot prove process absence or perform the SQL captures.
    """
    _need(
        type(owner) is str and re.fullmatch(r"[a-f0-9]{32}", owner) is not None,
        "invalid_owner",
    )
    _walk(bundle, set(), [0])
    _need(len(_canonical(bundle).encode()) <= MAX_BYTES, "invalid_shape")
    data = _object(
        bundle,
        {
            "schema_version",
            "owner",
            "originals",
            "phases",
            "quotes",
            "public_projections",
            "snapshots",
            "suppliers",
            "steps",
        },
    )
    _need(
        type(data["schema_version"]) is int
        and data["schema_version"] == 1
        and data["owner"] == owner,
        "invalid_owner",
    )
    phases = _object(data["phases"], set(PHASES))
    facts = {phase: _phase(phases[phase], owner, phase) for phase in PHASES}
    originals = _object(data["originals"], {"schemaVersion", "owner", "slots"})
    projections = _object(data["public_projections"], {"schemaVersion", "owner", "projections"})
    for envelope in (originals, projections):
        _need(
            type(envelope["schemaVersion"]) is int
            and envelope["schemaVersion"] == 1
            and envelope["owner"] == owner,
            "invalid_owner",
        )
    slots = _object(originals["slots"], {"revision", "stale", "exact"})
    final_public = _object(projections["projections"], set(slots))
    snapshots = _object(
        data["snapshots"],
        {"before_zero", "after_zero", "before_final_read", "after_final_read"},
    )
    captures = {name: _rows(value, OWNER_COLUMNS) for name, value in snapshots.items()}
    _same(captures["before_zero"], captures["after_zero"], "changed_read_state")
    _same(
        captures["before_final_read"],
        captures["after_final_read"],
        "changed_read_state",
    )
    initial, final = captures["before_zero"], captures["before_final_read"]
    _need(
        len(initial["tasks"]) == len(initial["executions"]) == len(initial["cases"]) == 3,
        "invalid_identity",
    )
    _need(
        len(final["tasks"]) == len(final["executions"]) == len(final["cases"]) == 3,
        "invalid_identity",
    )
    for rows in captures.values():
        _need(
            len(rows["schema_metadata"]) == 1
            and rows["schema_metadata"][0]["version"] == 4
            and type(rows["schema_metadata"][0]["version"]) is int
            and rows["schema_metadata"][0]["state"] == "active",
            "invalid_shape",
        )
    task_ids: dict[str, str] = {}
    case_ids: dict[str, str] = {}
    public: dict[str, dict[str, Any]] = {}
    for slot, day in (("revision", 2), ("stale", 3), ("exact", 4)):
        original = _object(slots[slot], {"created", "task_id", "case_id", "projection"})
        _need(original["created"] is True, "invalid_identity")
        task_ids[slot] = _uuid(original["task_id"])
        case_ids[slot] = _uuid(original["case_id"])
        _need(task_ids[slot] != case_ids[slot], "invalid_identity")
        seed_projection = _projection(
            original["projection"],
            owner=owner,
            slot=slot,
            task=task_ids[slot],
            case=case_ids[slot],
            complete=True,
        )
        _need(seed_projection["case_revision"] == "0", "invalid_outcome")
        _same(seed_projection["request"], _request(day))
        for table in ("tasks", "executions", "cases"):
            _one(initial[table], "task_id", task_ids[slot])
            _one(final[table], "task_id", task_ids[slot])
        task = _one(final["tasks"], "task_id", task_ids[slot])
        case = _one(final["cases"], "task_id", task_ids[slot])
        seedcase = _one(initial["cases"], "task_id", task_ids[slot])
        _need(
            task["scope_id"] == case["scope_id"] == _scope(slot)
            and case["actor_id"] == "starter_actor_" + owner
            and task["idempotency_key"] == "starter-" + owner + "-" + slot,
            "invalid_scope",
        )
        _need(
            case["case_id"] == case_ids[slot] and case["cancelled"] is False,
            "invalid_identity",
        )
        _same(_payload(task["payload"]), _request(day))
        _same(_payload(seedcase["request_json"]), _request(day))
        _need(
            type(seedcase["revision"]) is int and seedcase["revision"] == 0,
            "invalid_outcome",
        )
        expected_revision = {"revision": 2, "stale": 1, "exact": 0}[slot]
        _need(
            type(case["revision"]) is int and case["revision"] == expected_revision,
            "invalid_outcome",
        )
        _same(_payload(case["request_json"]), _request(4))
        body = _projection(
            final_public[slot],
            owner=owner,
            slot=slot,
            task=task_ids[slot],
            case=case_ids[slot],
            complete=True,
        )
        public[slot] = body
        _need(body["case_revision"] == str(expected_revision), "invalid_outcome")
        _same(body["request"], _payload(case["request_json"]))
        execution = _one(final["executions"], "task_id", task_ids[slot])
        _need(body["inquiry"]["effect_id"] == execution["effect_id"], "invalid_identity")
        _need(
            body["inquiry"]["state"] == execution["status"]
            and body["inquiry"]["version"] == str(execution["version"]),
            "invalid_outcome",
        )
        _same(
            body["inquiry"]["result"],
            None if execution["result_json"] is None else _payload(execution["result_json"]),
        )
        control = _one(final["execution_controls"], "task_id", task_ids[slot])
        _need(
            body["lifecycle"]["state"] == control["state"]
            and body["lifecycle"]["version"] == str(control["version"]),
            "invalid_outcome",
        )
    _need(
        len(set(task_ids.values())) == len(set(case_ids.values())) == 3,
        "invalid_identity",
    )
    for table, table_rows in final.items():
        for entry in table_rows:
            if "task_id" in entry:
                _need(entry["task_id"] in set(task_ids.values()), "invalid_identity")
    _need(len(final["execution_attempts"]) == 2, "invalid_outcome")
    for slot in ("stale", "exact"):
        attempt = _one(final["execution_attempts"], "task_id", task_ids[slot])
        _need(
            attempt["status"] == "succeeded"
            and _integer(attempt["attempt_no"]) == 1
            and attempt["finished_at"] is not None,
            "invalid_outcome",
        )
    for slot, task_id in task_ids.items():
        case_row = _one(final["cases"], "task_id", task_id)
        quote_id = case_row["current_quote_id"]
        expected_quote = None
        if quote_id is not None:
            quote_payload = _one(final["quotes"], "quote_id", quote_id)["payload_json"]
            expected_quote = {
                **_wire(_payload(quote_payload)),
                "confirmation_payload": quote_payload,
            }
        _same(public[slot]["quote"], expected_quote, "invalid_identity")
        if slot != "exact":
            _need(
                public[slot]["effect"] is None
                and public[slot]["outcome"] is None
                and public[slot]["confirmation"]["intent_id"] is None,
                "invalid_outcome",
            )
    rev = _object(
        facts["revision"],
        {
            "initialCase",
            "zeroCurrentCase",
            "knownRevision",
            "unknownOutcome",
            "afterUnknownCase",
            "staleOutcome",
            "foreignOutcome",
        },
    )
    _node_case(rev["initialCase"], owner, "revision", "0", 2)
    _node_case(rev["knownRevision"], owner, "revision", "1", 3)
    _node_case(rev["afterUnknownCase"], owner, "revision", "2", 4)
    _need(
        rev["unknownOutcome"] == "OutcomeUnknown"
        and rev["staleOutcome"] == "RevisionConflict"
        and rev["foreignOutcome"] == "AccessDenied",
        "invalid_outcome",
    )
    _current(rev["zeroCurrentCase"], slots["revision"]["projection"], owner, "revision")
    stale = _object(facts["stale-confirmation"], {"beforeCase", "afterRevision", "staleOutcome"})
    _node_case(stale["beforeCase"], owner, "stale", "0", 3)
    _node_case(stale["afterRevision"], owner, "stale", "1", 4)
    _need(stale["staleOutcome"] == "RevisionConflict", "invalid_outcome")
    exact = _object(
        facts["exact-confirmation"],
        {"beforeCase", "confirmationReceipt", "replayedConfirmationReceipt"},
    )
    _node_case(exact["beforeCase"], owner, "exact", "0", 4)
    _same(exact["confirmationReceipt"], exact["replayedConfirmationReceipt"])
    current = _object(
        facts["current-facts"], {"currentCase", "replayedCurrentCase", "foreignOutcome"}
    )
    _same(current["currentCase"], current["replayedCurrentCase"])
    _need(current["foreignOutcome"] == "AccessDenied", "invalid_outcome")
    _current(current["currentCase"], public["exact"], owner, "exact")
    quote_records = _object(data["quotes"], {"stale", "exact"})
    quote_bodies: dict[str, dict[str, Any]] = {}
    for slot in ("stale", "exact"):
        record = _object(
            quote_records[slot],
            {
                "schemaVersion",
                "owner",
                "slot",
                "taskId",
                "authorityCaseId",
                "quoteId",
                "quoteDigest",
                "quoteJson",
                "created",
            },
        )
        _need(
            type(record["schemaVersion"]) is int
            and record["schemaVersion"] == 1
            and record["owner"] == owner
            and record["slot"] == slot
            and record["created"] is True,
            "invalid_shape",
        )
        _need(
            record["taskId"] == task_ids[slot] and record["authorityCaseId"] == case_ids[slot],
            "invalid_identity",
        )
        raw = record["quoteJson"]
        body = _object(
            _payload(raw, 4096),
            {
                "schema_version",
                "quote_id",
                "task_id",
                "revision",
                "booking_reference",
                "new_check_in",
                "amount_minor",
                "currency",
                "expires_at",
                "case_id",
                "expected_supplier_revision",
                "supplier_id",
            },
        )
        _same(_canonical(body), raw)
        _need(
            hashlib.sha256(raw.encode()).hexdigest() == _sha(record["quoteDigest"]),
            "invalid_fingerprint",
        )
        _need(
            type(body["schema_version"]) is int
            and body["schema_version"] == 2
            and body["task_id"] == task_ids[slot]
            and body["case_id"] == case_ids[slot]
            and body["revision"] == 0
            and type(body["revision"]) is int,
            "invalid_identity",
        )
        _need(
            body["quote_id"] == _uuid(record["quoteId"])
            and body["new_check_in"] == _request(3 if slot == "stale" else 4)["new_check_in"]
            and body["booking_reference"] == "DEMO-BK-001",
            "invalid_identity",
        )
        row = _one(final["quotes"], "quote_id", record["quoteId"])
        _need(
            row["task_id"] == task_ids[slot] and row["revision"] == 0,
            "invalid_identity",
        )
        _same(row["payload_json"], raw)
        quote_bodies[slot] = body
    _need(len(final["quotes"]) == 2, "invalid_identity")
    for table in (
        "confirmations",
        "action_intents",
        "intent_dispatch",
        "mutation_effects",
        "mutation_attempts",
        "business_outcomes",
        "completion_events",
    ):
        _need(len(final[table]) == 1 and not initial[table], "invalid_outcome")
    _need(not final["cancellation_commands"], "invalid_outcome")
    confirmation = final["confirmations"][0]
    intent = final["action_intents"][0]
    effect = final["mutation_effects"][0]
    outcome = _payload(final["business_outcomes"][0]["payload_json"])
    completion = _payload(final["completion_events"][0]["payload_json"])
    receipt = _object(
        exact["confirmationReceipt"],
        {
            "scope",
            "caseId",
            "commandId",
            "revision",
            "quoteId",
            "quoteDigest",
            "intentId",
            "effectId",
        },
    )
    _same(receipt["scope"], _logical(owner, "exact")["scope"], "invalid_scope")
    _need(
        receipt["caseId"] == _logical(owner, "exact")["caseId"] and receipt["revision"] == "0",
        "invalid_identity",
    )
    _need(
        receipt["quoteId"] == quote_records["exact"]["quoteId"]
        and receipt["quoteDigest"] == quote_records["exact"]["quoteDigest"],
        "invalid_identity",
    )
    _need(
        confirmation["command_id"] == _uuid(receipt["commandId"])
        and intent["intent_id"] == _uuid(receipt["intentId"])
        and intent["effect_id"] == _uuid(receipt["effectId"]),
        "invalid_identity",
    )
    for row in (confirmation, intent):
        _need(
            row["task_id"] == task_ids["exact"]
            and row["scope_id"] == _scope("exact")
            and row["actor_id"] == "starter_actor_" + owner,
            "invalid_scope",
        )
    _same(
        _payload(confirmation["payload_json"]),
        {"schema_version": 2, "quote": quote_bodies["exact"], "explicit": True},
    )
    _need(
        _time(confirmation["created_at"]) <= _time(quote_bodies["exact"]["expires_at"]),
        "invalid_outcome",
    )
    intent_payload = _object(
        _payload(intent["payload_json"]),
        {
            "schema_version",
            "operation",
            "intent_id",
            "task_id",
            "scope_id",
            "actor_id",
            "revision",
            "quote",
            "confirmation_id",
            "effect_id",
            "dispatch_event_id",
            "created_at",
        },
    )
    _need(
        intent_payload["schema_version"] == 2 and intent_payload["operation"] == "booking.apply",
        "invalid_outcome",
    )
    for key in (
        "intent_id",
        "task_id",
        "scope_id",
        "actor_id",
        "revision",
        "quote_id",
        "confirmation_id",
        "effect_id",
    ):
        expected = intent[key]
        if key == "quote_id":
            _need(intent_payload["quote"]["quote_id"] == expected, "invalid_identity")
        else:
            _need(intent_payload[key] == expected, "invalid_identity")
    _same(intent_payload["quote"], quote_bodies["exact"])
    _need(
        intent["confirmation_id"] == confirmation["confirmation_id"]
        and intent["quote_id"] == quote_records["exact"]["quoteId"]
        and intent["revision"] == 0,
        "invalid_identity",
    )
    dispatch = final["intent_dispatch"][0]
    dispatch_payload = _payload(dispatch["payload_json"])
    _need(
        dispatch["intent_id"] == intent["intent_id"]
        and dispatch_payload["event_id"] == dispatch["event_id"],
        "invalid_identity",
    )
    _same(dispatch_payload["intent"], intent_payload)
    _need(
        dispatch["event_id"] == intent_payload["dispatch_event_id"]
        and dispatch_payload["type"] == "booking.apply_requested",
        "invalid_identity",
    )
    _need(
        effect["task_id"] == task_ids["exact"]
        and effect["intent_id"] == intent["intent_id"]
        and effect["state"] == "succeeded"
        and _integer(effect["dispatch_count"]) == 1
        and _integer(effect["attempt_no"]) == 1,
        "invalid_outcome",
    )
    mutation = _object(
        _payload(effect["result_json"]),
        {
            "schema_version",
            "effect_id",
            "intent_id",
            "task_id",
            "case_id",
            "supplier_id",
            "scope_id",
            "booking_reference",
            "previous_check_in",
            "new_check_in",
            "previous_revision",
            "revision",
            "amount_minor",
            "currency",
            "created_at",
        },
    )
    _need(
        type(mutation["schema_version"]) is int
        and mutation["schema_version"] == 1
        and mutation["task_id"] == task_ids["exact"]
        and mutation["case_id"] == case_ids["exact"]
        and mutation["scope_id"] == _scope("exact")
        and mutation["intent_id"] == intent["intent_id"]
        and mutation["effect_id"] == intent["effect_id"],
        "invalid_identity",
    )
    _need(
        mutation["previous_revision"] == 0
        and type(mutation["previous_revision"]) is int
        and mutation["revision"] == 1
        and type(mutation["revision"]) is int
        and mutation["booking_reference"] == "DEMO-BK-001"
        and mutation["new_check_in"] == "2030-12-04",
        "invalid_supplier",
    )
    _integer(mutation["amount_minor"], 0, 9007199254740991)
    _need(
        mutation["amount_minor"] == quote_bodies["exact"]["amount_minor"]
        and mutation["currency"] == quote_bodies["exact"]["currency"],
        "invalid_supplier",
    )
    attempt = final["mutation_attempts"][0]
    _need(
        attempt["intent_id"] == intent["intent_id"]
        and attempt["attempt_no"] == 1
        and attempt["state"] == "succeeded"
        and attempt["finished_at"] is not None,
        "invalid_outcome",
    )
    _need(
        outcome["state"] == "succeeded"
        and outcome["intent_id"] == intent["intent_id"]
        and outcome["effect_id"] == intent["effect_id"]
        and outcome["task_id"] == task_ids["exact"]
        and outcome["case_id"] == case_ids["exact"]
        and outcome["scope_id"] == _scope("exact"),
        "invalid_outcome",
    )
    _same(outcome["result"], mutation)
    _need(
        outcome["error_code"] is None and outcome["cancellation"] == "not_requested",
        "invalid_outcome",
    )
    _need(
        completion["event_id"] == final["completion_events"][0]["event_id"],
        "invalid_identity",
    )
    _same(completion["outcome"], outcome)
    _same(
        public["exact"]["effect"],
        {
            "state": effect["state"],
            "generation": str(effect["generation"]),
            "attempt_no": effect["attempt_no"],
            "dispatch_count": effect["dispatch_count"],
            "result": _wire(mutation),
            "error_code": effect["error_code"],
            "updated_at": effect["updated_at"],
        },
    )
    _same(
        public["exact"]["outcome"],
        {
            **{
                k: _wire(outcome[k], k)
                for k in (
                    "state",
                    "result",
                    "error_code",
                    "cancellation",
                    "created_at",
                    "intent_id",
                    "effect_id",
                )
            },
            "event_id": completion["event_id"],
        },
    )
    _need(
        public["exact"]["outcome"]["event_id"] == completion["event_id"]
        and public["exact"]["confirmation"]["intent_id"] == intent["intent_id"]
        and public["exact"]["confirmation"]["confirmation_id"] == confirmation["confirmation_id"],
        "invalid_identity",
    )
    suppliers = _object(data["suppliers"], {"initial", "before_final", "after_final"})
    for phase in suppliers:
        _object(suppliers[phase], {"stale", "exact"})
        for slot in ("stale", "exact"):
            _rows(suppliers[phase][slot], SUPPLIER_COLUMNS)
    _same(suppliers["before_final"], suppliers["after_final"], "changed_read_state")
    for slot in ("stale", "exact"):
        baseline = suppliers["initial"][slot]
        final_supplier = suppliers["before_final"][slot]
        _need(
            len(baseline["supplier_metadata"]) == len(final_supplier["supplier_metadata"]) == 1
            and len(baseline["bookings"]) == len(final_supplier["bookings"]) == 1,
            "invalid_supplier",
        )
        _same(
            baseline["supplier_metadata"],
            final_supplier["supplier_metadata"],
            "invalid_supplier",
        )
        provider = _uuid(baseline["supplier_metadata"][0]["provider_id"])
        _need(
            baseline["supplier_metadata"][0]["cooperating"] == 1
            and type(baseline["supplier_metadata"][0]["cooperating"]) is int,
            "invalid_supplier",
        )
        _need(
            quote_bodies[slot]["supplier_id"] == provider
            and type(quote_bodies[slot]["expected_supplier_revision"]) is int
            and quote_bodies[slot]["expected_supplier_revision"] == 0,
            "invalid_supplier",
        )
        _need(
            not baseline["inquiry_receipts"]
            and not baseline["mutation_receipts"]
            and not baseline["apply_calls"],
            "invalid_supplier",
        )
        before = baseline["bookings"][0]
        after = final_supplier["bookings"][0]
        _need(
            before["scope_id"] == after["scope_id"] == _scope(slot)
            and before["booking_reference"] == after["booking_reference"] == "DEMO-BK-001"
            and before["revision"] == 0
            and type(before["revision"]) is int,
            "invalid_supplier",
        )
        inquiries = final_supplier["inquiry_receipts"]
        _need(len(inquiries) == 1, "invalid_supplier")
        execution = _one(final["executions"], "task_id", task_ids[slot])
        _need(
            inquiries[0]["effect_id"] == execution["effect_id"]
            and inquiries[0]["scope_id"] == _scope(slot),
            "invalid_identity",
        )
        _need(
            _payload(inquiries[0]["result_json"]).get("available") is True,
            "invalid_supplier",
        )
        _same(
            _payload(inquiries[0]["request_json"]),
            _request(3 if slot == "stale" else 4),
        )
        _same(_payload(inquiries[0]["result_json"]), _payload(execution["result_json"]))
        if slot == "stale":
            _same(before, after, "invalid_supplier")
            _need(
                not final_supplier["mutation_receipts"] and not final_supplier["apply_calls"],
                "invalid_supplier",
            )
        else:
            _need(
                after["revision"] == 1
                and type(after["revision"]) is int
                and after["check_in"] == "2030-12-04",
                "invalid_supplier",
            )
            _need(
                mutation["supplier_id"] == provider
                and mutation["previous_check_in"] == before["check_in"],
                "invalid_supplier",
            )
            _need(
                len(final_supplier["mutation_receipts"]) == len(final_supplier["apply_calls"]) == 1,
                "invalid_supplier",
            )
            m = final_supplier["mutation_receipts"][0]
            call = final_supplier["apply_calls"][0]
            _need(
                m["effect_id"] == call["effect_id"] == intent["effect_id"]
                and m["scope_id"] == call["scope_id"] == _scope("exact")
                and call["outcome"] == "applied",
                "invalid_supplier",
            )
            for item in (m, call):
                _same(_payload(item["request_json"]), intent_payload)
                _same(_payload(item["result_json"]), mutation)
    steps = data["steps"]
    _need(type(steps) is list and len(steps) == 3, "invalid_steps")
    roles: set[str] = set()
    pids: set[int] = set()
    for outer in steps:
        proof = _object(
            outer,
            {"schemaVersion", "owner", "workerProcessId", "steps", "cleanupComplete"},
        )
        _need(
            type(proof["schemaVersion"]) is int
            and proof["schemaVersion"] == 1
            and proof["owner"] == owner
            and proof["cleanupComplete"] is True,
            "invalid_steps",
        )
        _integer(proof["workerProcessId"], 2)
        _need(type(proof["steps"]) is list and len(proof["steps"]) == 1, "invalid_steps")
        step = _object(
            proof["steps"][0],
            {"role", "processId", "groupId", "argvSha256", "returnCode", "groupAbsent"},
        )
        _need(
            type(step["role"]) is str
            and step["role"] in {"stale-inquiry", "exact-inquiry", "exact-mutation"}
            and step["role"] not in roles,
            "invalid_steps",
        )
        pid = _integer(step["processId"], 2)
        _need(
            pid not in pids and step["groupId"] == pid and type(step["groupId"]) is int,
            "invalid_steps",
        )
        roles.add(step["role"])
        pids.add(pid)
        _need(
            type(step["returnCode"]) is int
            and step["returnCode"] == 0
            and step["groupAbsent"] is True,
            "invalid_steps",
        )
        _sha(step["argvSha256"])
    return {
        "schema_version": 1,
        "owner": owner,
        "status": "passed",
        "groups": list(GROUPS),
        "counts": {
            "cases": 3,
            "tasks": 3,
            "confirmations": 1,
            "intents": 1,
            "mutation_effects": 1,
            "supplier_applied_calls": 1,
            "nested_worker_steps": 3,
        },
        "read_snapshots_equal": True,
        "supplier_read_snapshots_equal": True,
        "source_fingerprints": {slot: public[slot]["projection_revision"] for slot in public},
        "snapshot_sha256": {
            name: hashlib.sha256(_canonical(value).encode()).hexdigest()
            for name, value in captures.items()
        },
        "native_revision_zero_execution_claimed": False,
        "observations_atomic": False,
        "revision_command_receipt_claimed": False,
        "physical_cleanup_proven_here": False,
    }


def validate_bundle(bundle: Any, *, owner: str) -> dict[str, Any]:
    """Contain malformed JSON primitives without exposing private input text."""
    try:
        return _validate_bundle(bundle, owner=owner)
    except EvidenceError:
        raise
    except (
        KeyError,
        TypeError,
        ValueError,
        AttributeError,
        OverflowError,
        RecursionError,
        UnicodeError,
    ):
        raise EvidenceError("invalid_shape") from None
