"""Literal proof joins for the selected durable fixed-policy test composition.

No product parser, answer factory, SQL, configuration, process or provider is used.
Actual process/namespace ownership and trusted source paths belong to the host.
"""

from __future__ import annotations

import copy
import hashlib
import re
import sys
from pathlib import Path
from typing import NoReturn, cast
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p3_document_evidence as common
from p3_fixed_policy_check import policy_wire


class GateError(common.GateError):
    """One fixed safe code for invalid fixed-policy execution evidence."""

    def __init__(self) -> None:
        super().__init__("invalid_proof")
        self.args = ("invalid_proof",)


LABELS = (
    "known",
    "missing",
    "conflicting",
    "wrong_rule",
    "wrong_decision",
    "wrong_witness",
    "foreign_scope",
    "expired_wrong_facts",
    "expired_valid",
    "cancelled",
    "abandoned",
    "postcommit",
    "useful",
)
NEGATIVE = frozenset(
    {"wrong_rule", "wrong_decision", "wrong_witness", "foreign_scope", "expired_wrong_facts"}
)
PUBLIC = frozenset(
    {"known", "missing", "conflicting", "cancelled", "abandoned", "postcommit", "useful"}
)
MAX_TIME = 4_102_444_800_000
ROW_KEYS = frozenset(
    {
        "accepted_at_ms",
        "accepted_request_sha256",
        "attempt_id",
        "attempt_number",
        "cancel_requested",
        "case_id",
        "command_id",
        "deadline_at_ms",
        "delegation_id",
        "disposition",
        "epoch",
        "feed_sequence",
        "input_fingerprint",
        "issued_at_ms",
        "label",
        "lease_until_ms",
        "owner_id",
        "recorded_at_ms",
        "request_revision",
        "result_sha256",
        "wire_attempt_id",
        "work_id",
    }
)
EVENT_KEYS = frozenset(
    {
        "event_id",
        "source_id",
        "scope",
        "sequence",
        "work_id",
        "attempt_id",
        "issue_command_id",
        "result_sha256",
        "recorded_at_ms",
        "disposition",
        "origin",
        "kind",
    }
)


def _fail() -> NoReturn:
    raise GateError()


def _keys(value: object, keys: frozenset[str] | set[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        _fail()
    return cast(dict[str, object], value)


def _array(value: object, size: int | None = None, maximum: int = 26) -> list[object]:
    if type(value) is not list or len(value) > maximum or (size is not None and len(value) != size):
        _fail()
    return cast(list[object], value)


def _integer(value: object, minimum: int = 0, maximum: int = MAX_TIME) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail()
    return value


def _text(value: object, maximum: int = 128) -> str:
    if type(value) is not str or not 1 <= len(value.encode("utf-8")) <= maximum:
        _fail()
    return value


def _identifier(value: object) -> str:
    text = _text(value)
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", text, re.ASCII) is None:
        _fail()
    return text


def _uuid(value: object) -> str:
    text = _text(value, 36)
    parsed = UUID(text)
    if parsed.version != 4 or str(parsed) != text:
        _fail()
    return text


def _hash(value: object) -> str:
    text = _text(value, 64)
    if re.fullmatch(r"[a-f0-9]{64}", text, re.ASCII) is None:
        _fail()
    return text


def _same(first: object, second: object) -> None:
    if not common.exact(first, second):
        _fail()


def _scope(value: object) -> dict[str, str]:
    obj = _keys(value, {"tenant_id", "account_id"})
    return {key: _identifier(obj[key]) for key in ("tenant_id", "account_id")}


def _canonical(value: object) -> bytes:
    return common.canonical(value)


def _wire(value: object, maximum: int) -> dict[str, object]:
    raw = _text(value, maximum).encode("utf-8")
    decoded = common.decode(raw, maximum)
    if type(decoded) is not dict or _canonical(decoded) != raw:
        _fail()
    return cast(dict[str, object], decoded)


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sized(value: object, maximum: int) -> None:
    if len(_canonical(value)) > maximum:
        _fail()


def validate_bundle(
    authority: object,
    peer: object,
    wires: object,
    sources: object,
    *,
    expected_scope: dict[str, str],
) -> dict[str, object]:
    """Join bounded synthetic proofs; never grant execution or cleanup authority.

    The host must first authenticate private input paths, compare allocated schemas,
    retain the exact original files, and verify all actual owned process handles.
    """
    try:
        return _validate(authority, peer, wires, sources, expected_scope=expected_scope)
    except (
        common.GateError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        UnicodeError,
        RecursionError,
        StopIteration,
    ):
        raise GateError() from None


def _validate(
    authority: object,
    peer: object,
    wires: object,
    sources: object,
    *,
    expected_scope: dict[str, str],
) -> dict[str, object]:
    scope = _scope(expected_scope)
    for value in (authority, peer):
        _sized(value, 32768)
    _sized(wires, 524288)
    _sized(sources, 524288)
    if len(_canonical(wires)) + len(_canonical(sources)) > 524288:
        _fail()
    a = _keys(
        authority,
        {
            "schema_version",
            "kind",
            "case_schema",
            "work_schema",
            "schema_versions",
            "scope",
            "source_id",
            "counts",
            "records",
            "events",
            "cancellations",
            "clock_witnesses",
            "read_snapshot_sha256",
            "supplier_observation",
        },
    )
    p = _keys(peer, {"schema_version", "kind", "cleanup_complete", "counts", "records"})
    _same(a["schema_version"], 1)
    _same(p["schema_version"], 1)
    _same(a["kind"], "fixed-policy.execution-authority")
    _same(p["kind"], "fixed-policy.execution-peer")
    _same(p["cleanup_complete"], True)
    _same(_scope(a["scope"]), scope)
    for name in ("case_schema", "work_schema"):
        if re.fullmatch(r"[a-z][a-z0-9_]{0,62}", _text(a[name], 63), re.ASCII) is None:
            _fail()
    if a["case_schema"] == a["work_schema"]:
        _fail()
    _same(a["schema_versions"], {"case": 4, "work": 4})
    _same(
        a["counts"],
        {
            "work": 13,
            "attempts": 13,
            "results": 8,
            "events": 8,
            "cancel_commands": 2,
            "deliveries": 0,
            "actions": 0,
            "supplier_calls": 0,
        },
    )
    _same(
        p["counts"],
        {
            "invoked": 13,
            "returned": 13,
            "public_server_invoked": 7,
            "fault_invoked": 6,
            "active": 0,
            "requests": 0,
            "sockets": 0,
        },
    )
    source_id = _uuid(a["source_id"])
    snapshot = _keys(a["read_snapshot_sha256"], {"before", "after"})
    _same(_hash(snapshot["before"]), _hash(snapshot["after"]))
    supplier = _keys(
        a["supplier_observation"],
        {"inquiry_calls", "apply_calls", "baseline_sha256", "final_sha256"},
    )
    _same(supplier["inquiry_calls"], 0)
    _same(supplier["apply_calls"], 0)
    _same(_hash(supplier["baseline_sha256"]), _hash(supplier["final_sha256"]))
    source_rows = _array(sources)
    if len(source_rows) < 2:
        _fail()
    source_keys: set[bytes] = set()
    source_ids: set[tuple[str, str, str]] = set()
    for item in source_rows:
        row = _keys(item, {"scope", "reference", "body_utf8"})
        _same(_scope(row["scope"]), scope)
        ref = _keys(
            row["reference"],
            {"source_id", "version", "sha256", "media_type", "byte_length", "width", "height"},
        )
        source_key = (scope["tenant_id"], scope["account_id"], _identifier(ref["source_id"]))
        if source_key in source_ids:
            _fail()
        source_ids.add(source_key)
        _identifier(ref["version"])
        _same(ref["media_type"], "application/json")
        _same(ref["width"], None)
        _same(ref["height"], None)
        body = _text(row["body_utf8"], 4096).encode("utf-8")
        _same(_integer(ref["byte_length"], 1, 4096), len(body))
        _same(_hash(ref["sha256"]), _digest(body))
        source_keys.add(_canonical({"scope": scope, "reference": ref}))
    wire_rows, authority_rows, peer_rows = (
        _array(wires, 13),
        _array(a["records"], 13),
        _array(p["records"], 13),
    )
    seen_ids: dict[str, set[str]] = {
        name: set() for name in ("work_id", "attempt_id", "delegation_id")
    }
    referenced: set[bytes] = set()
    by_work: dict[str, dict[str, object]] = {}
    by_label: dict[str, dict[str, object]] = {}
    sequence_set: set[int] = set()
    for index, label in enumerate(LABELS):
        row = _keys(authority_rows[index], ROW_KEYS)
        wire = _keys(
            wire_rows[index],
            {"label", "accepted_request_utf8", "request_utf8", "result_utf8", "observed_at_ms"},
        )
        observation = _keys(
            peer_rows[index],
            {
                "label",
                "peer",
                "scope",
                "delegation_id",
                "wire_attempt_id",
                "input_fingerprint",
                "request_sha256",
                "result_sha256",
                "started_at_ms",
                "returned_at_ms",
            },
        )
        for current in (row, wire, observation):
            _same(current["label"], label)
        _sized(wire, 32768)
        accepted = _wire(wire["accepted_request_utf8"], 16384)
        issued = _wire(wire["request_utf8"], 16384)
        returned = _wire(wire["result_utf8"], 8192)
        _same(
            {k: v for k, v in accepted.items() if k != "attempt"},
            {k: v for k, v in issued.items() if k != "attempt"},
        )
        original_attempt = _keys(accepted["attempt"], {"attempt_id", "number"})
        _identifier(original_attempt["attempt_id"])
        _integer(original_attempt["number"], 1, 16)
        _same(_scope(accepted["scope"]), scope)
        _same(_scope(observation["scope"]), scope)
        for key, identities in seen_ids.items():
            identity = (
                _uuid(row[key])
                if key in {"work_id", "attempt_id", "owner_id"}
                else _identifier(row[key])
            )
            if identity in identities:
                _fail()
            identities.add(identity)
        _uuid(row["owner_id"])
        _identifier(row["command_id"])
        work_id = _uuid(row["work_id"])
        by_work[work_id], by_label[label] = row, row
        _same(
            row["accepted_request_sha256"],
            _digest(_text(wire["accepted_request_utf8"], 16384).encode()),
        )
        _same(observation["request_sha256"], _digest(_text(wire["request_utf8"], 16384).encode()))
        result_sha = _digest(_text(wire["result_utf8"], 8192).encode())
        _same(observation["result_sha256"], result_sha)
        for key in (
            "case_id",
            "delegation_id",
            "request_revision",
            "deadline_at_ms",
            "input_fingerprint",
        ):
            _same(row[key], accepted[key])
        _identifier(row["case_id"])
        _integer(row["request_revision"], 1, 1_000_000)
        _hash(row["input_fingerprint"])
        _same(observation["input_fingerprint"], row["input_fingerprint"])
        _same(observation["delegation_id"], row["delegation_id"])
        _same(row["attempt_number"], 1)
        _same(row["epoch"], 1)
        wire_attempt = "attempt_" + UUID(_uuid(row["attempt_id"])).hex
        _same(row["wire_attempt_id"], wire_attempt)
        _same(observation["wire_attempt_id"], wire_attempt)
        _same(issued["attempt"], {"attempt_id": wire_attempt, "number": 1})
        _same(observation["peer"], "public" if label in PUBLIC else "fault")
        accepted_at, issued_at, deadline, lease = (
            _integer(row[key])
            for key in ("accepted_at_ms", "issued_at_ms", "deadline_at_ms", "lease_until_ms")
        )
        if (
            not accepted_at <= issued_at < deadline <= accepted_at + 60000
            or not issued_at < lease <= issued_at + 10000
        ):
            _fail()
        started, completed, observed = (
            _integer(observation["started_at_ms"]),
            _integer(observation["returned_at_ms"]),
            _integer(wire["observed_at_ms"]),
        )
        if started > completed:
            _fail()
        _same(row["cancel_requested"], label in {"known", "cancelled"})
        refs = _array(issued["evidence"], 2)
        for requested_ref in refs:
            referenced.add(_canonical({"scope": scope, "reference": requested_ref}))
        if label in NEGATIVE:
            try:
                _, _, original_truth = policy_wire(
                    dict(wire), cast(list[dict[str, object]], source_rows)
                )
            except common.GateError:
                if label != "foreign_scope":
                    _fail()
            else:
                if label == "foreign_scope" or original_truth != "unsupported_facts":
                    _fail()
        repaired = copy.deepcopy(returned)
        if label in {"wrong_decision", "expired_wrong_facts"}:
            _same(repaired["eligible"], False)
            repaired["eligible"] = True
        elif label == "wrong_rule":
            rule = _keys(
                _array(repaired["rule_refs"], 1)[0],
                {"source_id", "version", "sha256", "rule_id", "minimum_notice_days"},
            )
            _same(rule["rule_id"], "notice_invented")
            rule["rule_id"] = "notice_minimum_days"
        elif label == "wrong_witness":
            witness = _keys(
                _array(repaired["fact_refs"], 1)[0],
                {"source_id", "version", "sha256", "fact_id", "days_before_arrival"},
            )
            _same(witness["fact_id"], "notice_forged")
            fact_source = next(
                _keys(s, {"scope", "reference", "body_utf8"})
                for s in source_rows
                if _keys(s, {"scope", "reference", "body_utf8"})["reference"] == refs[1]
            )
            source_facts = _keys(
                common.decode(_text(fact_source["body_utf8"], 4096).encode(), 4096),
                {"schema_version", "kind", "observations", "note"},
            )
            witness["fact_id"] = _keys(
                _array(source_facts["observations"], 1)[0], {"fact_id", "days_before_arrival"}
            )["fact_id"]
        elif label == "foreign_scope":
            _same(repaired["scope"], {**scope, "account_id": "account_foreign"})
            repaired["scope"] = dict(scope)
        probe = dict(wire)
        probe["result_utf8"] = _canonical(repaired).decode()
        _, verified_result, truth = policy_wire(probe, cast(list[dict[str, object]], source_rows))
        _same(truth, "clarification" if label in {"missing", "conflicting"} else "candidate")
        result_facts = _array(verified_result["fact_refs"])
        days = [
            _integer(
                _keys(f, {"source_id", "version", "sha256", "fact_id", "days_before_arrival"})[
                    "days_before_arrival"
                ],
                0,
                3650,
            )
            for f in result_facts
        ]
        _same(
            sorted(days), [] if label == "missing" else [3, 10] if label == "conflicting" else [10]
        )
        if label in NEGATIVE:
            for key in ("result_sha256", "recorded_at_ms", "disposition", "feed_sequence"):
                _same(row[key], None)
        else:
            _same(row["result_sha256"], result_sha)
            disposition = (
                "expired"
                if label == "expired_valid"
                else "cancelled"
                if label == "cancelled"
                else "eligible_at_commit"
            )
            _same(row["disposition"], disposition)
            recorded = _integer(row["recorded_at_ms"])
            if (
                recorded < issued_at
                or (disposition == "eligible_at_commit" and recorded >= min(deadline, lease))
                or (disposition == "expired" and recorded < deadline)
            ):
                _fail()
            seq = _integer(row["feed_sequence"], 1, 8)
            if seq in sequence_set:
                _fail()
            sequence_set.add(seq)
        if label in {"expired_valid", "expired_wrong_facts"} and observed < deadline:
            _fail()
    _same(referenced, source_keys)
    _same(sequence_set, set(range(1, 9)))
    events = _array(a["events"], 8)
    event_ids: set[str] = set()
    for sequence, item in enumerate(events, 1):
        event = _keys(item, EVENT_KEYS)
        event_id = _uuid(event["event_id"])
        if event_id in event_ids:
            _fail()
        event_ids.add(event_id)
        _same(event["kind"], "result_recorded")
        _same(event["origin"], "live")
        _same(event["source_id"], source_id)
        _same(_scope(event["scope"]), scope)
        _same(event["sequence"], sequence)
        record = by_work[_uuid(event["work_id"])]
        for key in ("attempt_id", "result_sha256", "recorded_at_ms", "disposition"):
            _same(event[key], record[key])
        if record["label"] in NEGATIVE:
            _fail()
        _same(event["issue_command_id"], record["command_id"])
        _same(record["feed_sequence"], sequence)
    cancellations = _array(a["cancellations"], 2)
    cancel_ids: set[str] = set()
    for item, label in zip(cancellations, ("known", "cancelled"), strict=True):
        cancel = _keys(
            item, {"cancellation_id", "command_id", "work_id", "requested_at_ms", "disposition"}
        )
        identity = _uuid(cancel["cancellation_id"])
        if identity in cancel_ids:
            _fail()
        cancel_ids.add(identity)
        _identifier(cancel["command_id"])
        _same(cancel["work_id"], by_label[label]["work_id"])
        _same(cancel["disposition"], "requested")
        requested = _integer(cancel["requested_at_ms"])
        recorded = _integer(by_label[label]["recorded_at_ms"])
        if (
            label == "known"
            and requested <= recorded
            or label == "cancelled"
            and not _integer(by_label[label]["issued_at_ms"]) <= requested <= recorded
        ):
            _fail()
    clocks = _keys(
        a["clock_witnesses"], {"expired_valid", "expired_wrong_facts", "postcommit_lease"}
    )
    for label, field, original in (
        ("expired_valid", "deadline_at_ms", "expired_valid"),
        ("expired_wrong_facts", "deadline_at_ms", "expired_wrong_facts"),
        ("postcommit_lease", "lease_until_ms", "postcommit"),
    ):
        clock = _keys(clocks[label], {"db_now_ms", field})
        _same(clock[field], by_label[original][field])
        if _integer(clock["db_now_ms"]) < _integer(clock[field]):
            _fail()
    return {
        "schema_version": 1,
        "status": "passed",
        "labels": list(LABELS),
        "work": 13,
        "invocations": 13,
        "public_invocations": 7,
        "fault_invocations": 6,
        "stored_results": 8,
        "rejected_bodies": 5,
        "feed_events": 8,
        "cancellation_commands": 2,
        "source_records": len(source_rows),
        "joined_identity_sha256": _digest(
            _canonical(
                {
                    "scope": scope,
                    "source_id": source_id,
                    "records": authority_rows,
                    "events": events,
                }
            )
        ),
        "limits": "Synthetic fixture proof validation only; host binds actual processes, allocated schemas, private paths and cleanup separately.",
    }
