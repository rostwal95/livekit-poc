"""Synthetic parser/join controls only; no service, SQL or public gate qualification."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import unittest
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "p1_evidence_under_test", ROOT / "local-setup/scripts/p2_starter_p1_evidence.py"
)
assert spec and spec.loader
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

OWNER = "a" * 32
STAMP = "2026-11-12T00:00:00+00:00"


def uid(n: int) -> str:
    return str(UUID(int=n, version=4))


def canonical(v: object) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def request(day: int) -> dict:
    return {
        "booking_reference": "DEMO-BK-001",
        "new_check_in": f"2030-12-{day:02d}",
        "confirmed": True,
    }


def wire(v: object, key: str = "") -> object:
    if (
        key
        in {
            "revision",
            "previous_revision",
            "expected_supplier_revision",
            "version",
            "generation",
            "epoch",
            "case_revision",
        }
        and v is not None
    ):
        return str(v)
    if type(v) is dict:
        return {k: wire(i, k) for k, i in v.items()}
    if type(v) is list:
        return [wire(i) for i in v]
    return v


def node_request(v: dict) -> dict:
    return {
        "schemaVersion": 1,
        "kind": "booking_investigation",
        "bookingReference": v["booking_reference"],
        "newCheckIn": v["new_check_in"],
        "investigationConsent": True,
    }


def logical(slot: str) -> dict:
    return {
        "scope": {
            "tenantId": "tenant_starter_p1",
            "accountId": "account_starter_" + slot,
        },
        "caseId": "case_starter_" + OWNER + "_" + slot,
        "conversationId": "conversation_starter_" + OWNER + "_" + slot,
    }


def nodecase(slot: str, revision: str, day: int) -> dict:
    r = logical(slot)
    return {
        "scope": r["scope"],
        "caseId": r["caseId"],
        "revision": revision,
        "request": node_request(request(day)),
        "cancelled": False,
        "committed": False,
    }


def fingerprint(p: dict, slot: str) -> None:
    snapshot = {
        k: v
        for k, v in p.items()
        if k
        not in {
            "events",
            "projection_revision",
            "next_cursor",
            "has_more",
            "cursor_reset",
        }
    }
    raw = canonical(
        {
            "actor_id": "starter_actor_" + OWNER,
            "scope_id": "p1_starter_" + slot,
            "snapshot": snapshot,
            "observations": p["events"],
        }
    )
    p["projection_revision"] = hashlib.sha256(raw.encode()).hexdigest()


def row(table: str, **values: object) -> dict:
    result = {k: None for k in E.OWNER_COLUMNS[table]}
    result.update(values)
    return result


def fixture() -> dict:
    tasks = {s: uid(i + 1) for i, s in enumerate(("revision", "stale", "exact"))}
    cases = {s: uid(i + 11) for i, s in enumerate(tasks)}
    providers = {"stale": uid(101), "exact": uid(102)}
    original = {}
    initial = {k: [] for k in E.OWNER_COLUMNS}
    initial["schema_metadata"] = [
        row(
            "schema_metadata",
            singleton=True,
            version=4,
            state="active",
            migration_id=uid(88),
            source_digest="1" * 64,
        )
    ]
    initial["execution_limits"] = [
        row(
            "execution_limits",
            singleton=True,
            maximum_pending=64,
            maximum_active=2,
            maximum_records=128,
            lease_seconds=30,
        )
    ]
    for slot, day in (("revision", 2), ("stale", 3), ("exact", 4)):
        task, case = tasks[slot], cases[slot]
        key = "starter-" + OWNER + "-" + slot
        p = {
            "schema_version": 1,
            "task_id": task,
            "case_id": case,
            "case_revision": "0",
            "request_key": key,
            "request": request(day),
            "inquiry": {
                "state": "pending",
                "version": "0",
                "effect_id": uid(200 + day),
                "request": request(day),
                "result": None,
                "error_code": None,
                "created_at": STAMP,
                "updated_at": STAMP,
            },
            "lifecycle": {
                "state": "ready",
                "version": "0",
                "deadline": "2030-01-01T00:00:00+00:00",
                "next_attempt_at": None,
                "error_code": None,
                "last_failure": None,
                "lease": None,
            },
            "quote": None,
            "confirmation": {
                "state": "not_requested",
                "intent_id": None,
                "confirmation_id": None,
                "committed_at": None,
            },
            "effect": None,
            "outcome": None,
            "delivery": None,
            "events_total": 0,
            "history_truncated": False,
            "events": [],
            "projection_revision": "0" * 64,
            "next_cursor": None,
            "has_more": False,
            "cursor_reset": False,
        }
        fingerprint(p, slot)
        original[slot] = {
            "created": True,
            "task_id": task,
            "case_id": case,
            "projection": p,
        }
        initial["tasks"].append(
            row(
                "tasks",
                task_id=task,
                scope_id="p1_starter_" + slot,
                idempotency_key=key,
                payload=canonical(request(day)),
                status="queued",
                created_at=STAMP,
            )
        )
        initial["executions"].append(
            row(
                "executions",
                task_id=task,
                operation="booking.inquire",
                status="pending",
                effect_id=uid(200 + day),
                version=0,
                created_at=STAMP,
                updated_at=STAMP,
                result_json=None,
                error_code=None,
            )
        )
        initial["cases"].append(
            row(
                "cases",
                task_id=task,
                case_id=case,
                scope_id="p1_starter_" + slot,
                actor_id="starter_actor_" + OWNER,
                revision=0,
                request_json=canonical(request(day)),
                current_quote_id=None,
                cancelled=False,
                created_at=STAMP,
                updated_at=STAMP,
            )
        )
        initial["execution_controls"].append(
            row("execution_controls", task_id=task, state="ready", version=0)
        )
    final = copy.deepcopy(initial)
    public = {s: copy.deepcopy(v["projection"]) for s, v in original.items()}
    for slot, task_id in tasks.items():
        revision = {"revision": 2, "stale": 1, "exact": 0}[slot]
        next(r for r in final["cases"] if r["task_id"] == task_id).update(
            revision=revision, request_json=canonical(request(4))
        )
        public[slot]["case_revision"] = str(revision)
        public[slot]["request"] = request(4)
    quotes = {}
    qbody = {}
    for slot, day in (("stale", 3), ("exact", 4)):
        body = {
            "schema_version": 2,
            "quote_id": uid(300 + day),
            "task_id": tasks[slot],
            "case_id": cases[slot],
            "revision": 0,
            "booking_reference": "DEMO-BK-001",
            "new_check_in": f"2030-12-{day:02d}",
            "amount_minor": 2500,
            "currency": "USD",
            "expires_at": "2050-01-01T00:00:00+00:00",
            "supplier_id": providers[slot],
            "expected_supplier_revision": 0,
        }
        raw = canonical(body)
        qbody[slot] = body
        quotes[slot] = {
            "schemaVersion": 1,
            "owner": OWNER,
            "slot": slot,
            "taskId": tasks[slot],
            "authorityCaseId": cases[slot],
            "quoteId": body["quote_id"],
            "quoteDigest": hashlib.sha256(raw.encode()).hexdigest(),
            "quoteJson": raw,
            "created": True,
        }
        final["quotes"].append(
            row(
                "quotes",
                quote_id=body["quote_id"],
                task_id=tasks[slot],
                revision=0,
                payload_json=raw,
                created_at=STAMP,
            )
        )
        inquiry_result = {
            "booking_reference": "DEMO-BK-001",
            "new_check_in": f"2030-12-{day:02d}",
            "available": True,
        }
        next(r for r in final["executions"] if r["task_id"] == tasks[slot]).update(
            status="succeeded", version=2, result_json=canonical(inquiry_result)
        )
        public[slot]["inquiry"].update(state="succeeded", version="2", result=inquiry_result)
        state = "completed" if slot == "exact" else "inquiry_complete"
        public[slot]["lifecycle"].update(state=state, version="2")
        next(r for r in final["execution_controls"] if r["task_id"] == tasks[slot]).update(
            state=state, version=2
        )
        final["execution_attempts"].append(
            row(
                "execution_attempts",
                attempt_id=uid(400 + day),
                task_id=tasks[slot],
                attempt_no=1,
                status="succeeded",
                started_at=STAMP,
                finished_at=STAMP,
                error_code=None,
            )
        )
    intent_id, effect_id, confirmation_id, event_id, dispatch_id, command_id = map(
        uid, range(501, 507)
    )
    intent = {
        "schema_version": 2,
        "operation": "booking.apply",
        "intent_id": intent_id,
        "task_id": tasks["exact"],
        "scope_id": "p1_starter_exact",
        "actor_id": "starter_actor_" + OWNER,
        "revision": 0,
        "quote": qbody["exact"],
        "confirmation_id": confirmation_id,
        "effect_id": effect_id,
        "dispatch_event_id": dispatch_id,
        "created_at": STAMP,
    }
    result = {
        "schema_version": 1,
        "task_id": tasks["exact"],
        "case_id": cases["exact"],
        "scope_id": "p1_starter_exact",
        "intent_id": intent_id,
        "effect_id": effect_id,
        "supplier_id": providers["exact"],
        "booking_reference": "DEMO-BK-001",
        "previous_check_in": "2030-12-01",
        "new_check_in": "2030-12-04",
        "previous_revision": 0,
        "revision": 1,
        "amount_minor": 2500,
        "currency": "USD",
        "created_at": STAMP,
    }
    outcome = {
        "schema_version": 1,
        "task_id": tasks["exact"],
        "case_id": cases["exact"],
        "scope_id": "p1_starter_exact",
        "intent_id": intent_id,
        "effect_id": effect_id,
        "state": "succeeded",
        "result": result,
        "error_code": None,
        "cancellation": "not_requested",
        "created_at": STAMP,
    }
    final["confirmations"] = [
        row(
            "confirmations",
            confirmation_id=confirmation_id,
            task_id=tasks["exact"],
            scope_id="p1_starter_exact",
            actor_id="starter_actor_" + OWNER,
            command_id=command_id,
            payload_json=canonical(
                {"schema_version": 2, "quote": qbody["exact"], "explicit": True}
            ),
            created_at=STAMP,
        )
    ]
    final["action_intents"] = [
        row(
            "action_intents",
            intent_id=intent_id,
            task_id=tasks["exact"],
            scope_id="p1_starter_exact",
            actor_id="starter_actor_" + OWNER,
            revision=0,
            quote_id=qbody["exact"]["quote_id"],
            confirmation_id=confirmation_id,
            effect_id=effect_id,
            payload_json=canonical(intent),
            created_at=STAMP,
        )
    ]
    final["intent_dispatch"] = [
        row(
            "intent_dispatch",
            event_id=dispatch_id,
            intent_id=intent_id,
            payload_json=canonical(
                {
                    "schema_version": 1,
                    "event_id": dispatch_id,
                    "type": "booking.apply_requested",
                    "intent": intent,
                    "created_at": STAMP,
                }
            ),
            created_at=STAMP,
        )
    ]
    final["mutation_effects"] = [
        row(
            "mutation_effects",
            intent_id=intent_id,
            task_id=tasks["exact"],
            state="succeeded",
            generation=1,
            attempt_no=1,
            dispatch_count=1,
            result_json=canonical(result),
            updated_at=STAMP,
        )
    ]
    final["mutation_attempts"] = [
        row(
            "mutation_attempts",
            attempt_id=uid(507),
            intent_id=intent_id,
            attempt_no=1,
            state="succeeded",
            started_at=STAMP,
            finished_at=STAMP,
            error_code=None,
        )
    ]
    final["business_outcomes"] = [
        row(
            "business_outcomes",
            task_id=tasks["exact"],
            payload_json=canonical(outcome),
            created_at=STAMP,
        )
    ]
    final["completion_events"] = [
        row(
            "completion_events",
            event_id=event_id,
            task_id=tasks["exact"],
            payload_json=canonical(
                {
                    "schema_version": 1,
                    "kind": "workflow.completed",
                    "event_id": event_id,
                    "outcome": outcome,
                    "created_at": STAMP,
                }
            ),
            created_at=STAMP,
        )
    ]
    next(r for r in final["cases"] if r["task_id"] == tasks["exact"]).update(
        current_quote_id=qbody["exact"]["quote_id"]
    )
    exactpublic = public["exact"]
    exactpublic["quote"] = {
        **wire(qbody["exact"]),
        "confirmation_payload": quotes["exact"]["quoteJson"],
    }
    exactpublic["confirmation"] = {
        "state": "committed",
        "intent_id": intent_id,
        "confirmation_id": confirmation_id,
        "committed_at": STAMP,
    }
    exactpublic["effect"] = {
        "state": "succeeded",
        "generation": "1",
        "attempt_no": 1,
        "dispatch_count": 1,
        "result": wire(result),
        "error_code": None,
        "updated_at": STAMP,
    }
    exactpublic["outcome"] = {**wire(outcome), "event_id": event_id}
    # Public projection's outcome has an explicit source allowlist, not the whole BusinessOutcome wire.
    exactpublic["outcome"] = {
        k: exactpublic["outcome"][k]
        for k in (
            "state",
            "result",
            "error_code",
            "cancellation",
            "created_at",
            "intent_id",
            "effect_id",
            "event_id",
        )
    }
    for slot, projection in public.items():
        fingerprint(projection, slot)

    def current(p: dict, slot: str) -> dict:
        committed = p["confirmation"]["intent_id"] is not None
        e = p["effect"]
        o = p["outcome"]
        r = None if o is None else o["result"]
        return {
            "schemaVersion": 1,
            "source": "p1_public_v4",
            **logical(slot),
            "revision": p["case_revision"],
            "request": node_request(p["request"]),
            "workflow": {
                "taskId": p["task_id"],
                "state": p["lifecycle"]["state"],
                "version": p["lifecycle"]["version"],
            },
            "intent": {
                "state": "committed" if committed else "not_committed",
                "intentId": p["confirmation"]["intent_id"],
            },
            "mutation": {
                "state": "not_observed" if e is None else e["state"],
                "outcome": "not_observed" if o is None else o["state"],
                "cancellation": "not_observed" if o is None else o["cancellation"],
                "effectId": None if o is None else o["effect_id"],
                "outcomeEventId": None if o is None else o["event_id"],
            },
            "supplierResult": None
            if r is None
            else {
                "supplierId": r["supplier_id"],
                "revision": r["revision"],
                "bookingReference": r["booking_reference"],
                "newCheckIn": r["new_check_in"],
            },
            "sourceRevision": p["projection_revision"],
        }

    receipt = {
        "scope": logical("exact")["scope"],
        "caseId": logical("exact")["caseId"],
        "commandId": command_id,
        "revision": "0",
        "quoteId": qbody["exact"]["quote_id"],
        "quoteDigest": quotes["exact"]["quoteDigest"],
        "intentId": intent_id,
        "effectId": effect_id,
    }
    phasefacts = {
        "revision": {
            "initialCase": nodecase("revision", "0", 2),
            "zeroCurrentCase": current(original["revision"]["projection"], "revision"),
            "knownRevision": nodecase("revision", "1", 3),
            "unknownOutcome": "OutcomeUnknown",
            "afterUnknownCase": nodecase("revision", "2", 4),
            "staleOutcome": "RevisionConflict",
            "foreignOutcome": "AccessDenied",
        },
        "stale-confirmation": {
            "beforeCase": nodecase("stale", "0", 3),
            "afterRevision": nodecase("stale", "1", 4),
            "staleOutcome": "RevisionConflict",
        },
        "exact-confirmation": {
            "beforeCase": nodecase("exact", "0", 4),
            "confirmationReceipt": receipt,
            "replayedConfirmationReceipt": copy.deepcopy(receipt),
        },
        "current-facts": {
            "currentCase": current(public["exact"], "exact"),
            "replayedCurrentCase": current(public["exact"], "exact"),
            "foreignOutcome": "AccessDenied",
        },
    }
    metricnumbers = {
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
    groups = {
        "revision": [E.GROUPS[0], E.GROUPS[1], E.GROUPS[4]],
        "stale-confirmation": [],
        "exact-confirmation": [E.GROUPS[2]],
        "current-facts": [E.GROUPS[3], E.GROUPS[5]],
    }
    phases = {}
    for name, values in metricnumbers.items():
        metrics = {
            k: dict(
                zip(
                    ("started", "known", "rejected", "unknown", "failed", "active"),
                    (*counts, 0, 0),
                    strict=True,
                )
            )
            for k, counts in values.items()
        }
        phases[name] = {
            "schemaVersion": 1,
            "mode": "p1-contract",
            "phase": name,
            "owner": OWNER,
            "groups": groups[name],
            "facts": phasefacts[name],
            "metrics": metrics,
            "cleanupComplete": True,
        }
    suppliers_initial = {}
    suppliers_final = {}
    for slot in ("stale", "exact"):
        before = {k: [] for k in E.SUPPLIER_COLUMNS}
        before["supplier_metadata"] = [
            {"singleton": 1, "provider_id": providers[slot], "cooperating": 1}
        ]
        before["bookings"] = [
            {
                "scope_id": "p1_starter_" + slot,
                "booking_reference": "DEMO-BK-001",
                "check_in": "2030-12-01",
                "revision": 0,
            }
        ]
        after = copy.deepcopy(before)
        day = 3 if slot == "stale" else 4
        execution = next(r for r in final["executions"] if r["task_id"] == tasks[slot])
        after["inquiry_receipts"] = [
            {
                "effect_id": execution["effect_id"],
                "scope_id": "p1_starter_" + slot,
                "booking_reference": "DEMO-BK-001",
                "request_json": canonical(request(day)),
                "result_json": execution["result_json"],
                "created_at": STAMP,
            }
        ]
        if slot == "exact":
            after["bookings"][0].update(check_in="2030-12-04", revision=1)
            m = {
                "effect_id": effect_id,
                "scope_id": "p1_starter_exact",
                "booking_reference": "DEMO-BK-001",
                "request_json": canonical(intent),
                "result_json": canonical(result),
                "created_at": STAMP,
            }
            after["mutation_receipts"] = [m]
            after["apply_calls"] = [
                {
                    "call_id": uid(601),
                    "effect_id": effect_id,
                    "scope_id": "p1_starter_exact",
                    "request_json": canonical(intent),
                    "outcome": "applied",
                    "result_json": canonical(result),
                    "created_at": STAMP,
                }
            ]
        suppliers_initial[slot] = before
        suppliers_final[slot] = after
    steps = [
        {
            "schemaVersion": 1,
            "owner": OWNER,
            "workerProcessId": 100 + i,
            "steps": [
                {
                    "role": role,
                    "processId": 200 + i,
                    "groupId": 200 + i,
                    "argvSha256": str(i + 1) * 64,
                    "returnCode": 0,
                    "groupAbsent": True,
                }
            ],
            "cleanupComplete": True,
        }
        for i, role in enumerate(("stale-inquiry", "exact-inquiry", "exact-mutation"))
    ]
    return {
        "schema_version": 1,
        "owner": OWNER,
        "originals": {"schemaVersion": 1, "owner": OWNER, "slots": original},
        "phases": phases,
        "quotes": quotes,
        "public_projections": {
            "schemaVersion": 1,
            "owner": OWNER,
            "projections": public,
        },
        "snapshots": {
            "before_zero": initial,
            "after_zero": copy.deepcopy(initial),
            "before_final_read": final,
            "after_final_read": copy.deepcopy(final),
        },
        "suppliers": {
            "initial": suppliers_initial,
            "before_final": suppliers_final,
            "after_final": copy.deepcopy(suppliers_final),
        },
        "steps": steps,
    }


class EvidenceTests(unittest.TestCase):
    def test_complete_synthetic_join_passes_without_returning_quote_controls(self):
        result = E.validate_bundle(fixture(), owner=OWNER)
        self.assertEqual(result["counts"]["supplier_applied_calls"], 1)
        self.assertEqual(result["groups"], list(E.GROUPS))
        self.assertNotIn("quoteJson", canonical(result))
        self.assertFalse(result["native_revision_zero_execution_claimed"])

    def rejects(self, mutate):
        b = fixture()
        mutate(b)
        with self.assertRaises(E.EvidenceError) as caught:
            E.validate_bundle(b, owner=OWNER)
        self.assertIn(str(caught.exception), E.ERROR_CODES)

    def test_closed_schema_and_primitive_failures_are_finite(self):
        for mutate in [
            lambda b: b.update(schema_version=True),
            lambda b: b.update(unreviewed=1),
            lambda b: b["phases"].update(revision=[]),
            lambda b: b["steps"][0]["steps"][0].update(role=[]),
            lambda b: b["public_projections"]["projections"]["exact"].update(effect=3),
        ]:
            with self.subTest(mutate=mutate):
                self.rejects(mutate)

    def test_missing_table_column_or_extra_task_fails(self):
        for mutate in [
            lambda b: b["snapshots"]["before_final_read"].pop("quotes"),
            lambda b: b["snapshots"]["before_final_read"]["cases"][0].pop("revision"),
            lambda b: b["snapshots"]["before_final_read"]["tasks"].append(
                copy.deepcopy(b["snapshots"]["before_final_read"]["tasks"][0])
            ),
        ]:
            with self.subTest(mutate=mutate):
                self.rejects(mutate)

    def test_read_side_effects_and_supplier_mutation_during_read_fail(self):
        self.rejects(lambda b: b["snapshots"]["after_zero"]["cases"][0].update(revision=1))
        self.rejects(
            lambda b: b["suppliers"]["after_final"]["exact"]["bookings"][0].update(revision=2)
        )

    def test_exact_case_scope_and_effect_source_binding_fail_closed(self):
        self.rejects(
            lambda b: b["phases"]["current-facts"]["facts"]["currentCase"].update(caseId="foreign")
        )
        self.rejects(
            lambda b: b["phases"]["exact-confirmation"]["facts"]["confirmationReceipt"].update(
                effectId=uid(999)
            )
        )
        self.rejects(lambda b: b["quotes"]["exact"].update(authorityCaseId=uid(998)))

    def test_fingerprint_cannot_use_missing_page_or_altered_current_snapshot(self):
        self.rejects(
            lambda b: b["public_projections"]["projections"]["exact"].update(
                has_more=True, next_cursor="opaque"
            )
        )
        self.rejects(
            lambda b: b["public_projections"]["projections"]["revision"]["lifecycle"].update(
                version="99"
            )
        )
        self.rejects(
            lambda b: b["phases"]["current-facts"]["facts"]["currentCase"].update(
                sourceRevision="f" * 64
            )
        )

    def test_currentcase_control_leak_and_supplier_truth_tamper_fail(self):
        self.rejects(
            lambda b: b["phases"]["current-facts"]["facts"]["currentCase"].update(
                quote={"confirmation_payload": "SENTINEL"}
            )
        )
        self.rejects(
            lambda b: [
                b["suppliers"][p]["exact"]["mutation_receipts"][0].update(result_json="{}")
                for p in ("before_final", "after_final")
            ]
        )
        self.rejects(
            lambda b: b["suppliers"]["initial"]["exact"]["supplier_metadata"][0].update(
                provider_id=uid(999)
            )
        )

    def test_second_apply_replayed_send_and_missing_step_fail(self):
        self.rejects(
            lambda b: [
                b["suppliers"][p]["exact"]["apply_calls"].append(
                    copy.deepcopy(b["suppliers"][p]["exact"]["apply_calls"][0])
                )
                for p in ("before_final", "after_final")
            ]
        )
        self.rejects(lambda b: b["steps"].pop())
        self.rejects(lambda b: b["steps"][0]["steps"][0].update(groupAbsent=False))

    def test_budget_duplicate_json_and_nonfinite_fail_safely(self):
        self.rejects(
            lambda b: b["quotes"]["exact"].update(
                quoteJson='{"schema_version":2,"schema_version":2}'
            )
        )
        self.rejects(lambda b: b["steps"][0]["steps"][0].update(returnCode=float("nan")))
        self.rejects(
            lambda b: b["originals"]["slots"]["exact"]["projection"].update(
                request_key="x" * (2097152 + 1)
            )
        )

    def test_unknown_revision_and_zero_promotion_never_pass(self):
        self.rejects(lambda b: b["phases"]["revision"]["facts"].update(unknownOutcome="known"))
        self.rejects(
            lambda b: b["phases"]["revision"]["facts"]["zeroCurrentCase"].update(revision="1")
        )

    def test_replay_counter_or_original_receipt_change_fails(self):
        self.rejects(
            lambda b: b["phases"]["exact-confirmation"]["facts"][
                "replayedConfirmationReceipt"
            ].update(commandId=uid(999))
        )
        self.rejects(
            lambda b: b["phases"]["current-facts"]["metrics"]["currentCase"].update(started=4)
        )

    def test_non_json_containers_cycles_and_row_overflow_are_contained(self):
        touched = []

        class Evil(dict):
            def items(self):
                touched.append(True)
                raise RuntimeError("PRIVATE_SENTINEL")

        with self.assertRaises(E.EvidenceError):
            E.validate_bundle(Evil(), owner=OWNER)
        self.assertEqual(touched, [])
        cycle = {}
        cycle["self"] = cycle
        with self.assertRaises(E.EvidenceError):
            E.validate_bundle(cycle, owner=OWNER)
        self.rejects(
            lambda b: b["snapshots"]["before_zero"]["tasks"].extend(
                [b["snapshots"]["before_zero"]["tasks"][0]] * 129
            )
        )


if __name__ == "__main__":
    unittest.main()
