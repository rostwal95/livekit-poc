"""Installed runtime consumer for the isolated Phase E container proof.

Only explicit runtime credentials enter this process. Host orchestration owns
schema installation, enrollment and exact confirmation; this probe owns the
independent persisted supplier/receiver state on its isolated /data volume.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import os
import re
import sys
from collections import deque
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from continuity_lab.authorization import AuthenticatedActor, BearerToken, TokenDirectory
from continuity_lab.case_models import uuid_identity
from continuity_lab.case_service import ScopedCaseService
from continuity_lab.case_telemetry import OPERATIONS
from continuity_lab.completion_sink import CompletionSink, initialize_completion_sink
from continuity_lab.effect_models import CancellationDisposition, DeliveryState, EffectState
from continuity_lab.execution_cli import _SafeFormatter, configure_logging
from continuity_lab.lifecycle_models import LifecycleState
from continuity_lab.managed_inquiry_worker import ManagedInquiryWorker
from continuity_lab.mutation_supplier import MutationSupplier, initialize_mutation_supplier
from continuity_lab.mutation_worker import MutationWorker
from continuity_lab.outbox_delivery import CompletionDeliveryWorker
from continuity_lab.postgres_case import PostgresCaseAuthority
from continuity_lab.postgres_effects import PostgresEffects
from continuity_lab.postgres_lifecycle import PostgresLifecycle
from continuity_lab.postgres_settings import PostgresSettings
from continuity_lab.postgres_store import PostgresExecutionStore

BASE = datetime(2030, 12, 1, tzinfo=UTC)
SCOPE = "phase-e-demo"
ACTOR = AuthenticatedActor("demo-owner", SCOPE)
BOOKING = "DEMO-BK-001"
DATA = Path("/data")
REQUIRED_MODULES = frozenset(
    {
        "mutation_supplier",
        "mutation_worker",
        "postgres_effects",
        "completion_sink",
        "outbox_delivery",
    }
)


def installed_modules() -> int:
    """Fail if even one claimed module differs from its host-inspected source."""
    expected = json.loads(os.environ["DEMO_MODULE_HASHES"])
    if type(expected) is not dict or not REQUIRED_MODULES <= set(expected):
        raise ValueError("Complete installed module proof is required")
    for name, digest in expected.items():
        if (
            type(name) is not str
            or re.fullmatch(r"[a-z][a-z0-9_]*", name) is None
            or type(digest) is not str
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise ValueError("Installed module proof is invalid")
        module = importlib.import_module("continuity_lab." + name)
        if module.__file__ is None:
            raise RuntimeError("Installed module path is unavailable")
        path = Path(module.__file__).resolve()
        if (
            "/site-packages/" not in str(path)
            or hashlib.sha256(path.read_bytes()).hexdigest() != digest
        ):
            raise RuntimeError("Installed module validation failed")
    return len(expected)


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {
        "seed",
        "crash-apply",
        "reconcile",
        "crash-deliver",
        "verify",
    }:
        raise ValueError("One supported probe stage is required")
    if any(name.startswith("P1_MIGRATION_") for name in os.environ):
        raise RuntimeError("Runtime must not receive bootstrap credentials")
    configure_logging()
    records: deque[str] = deque(maxlen=256)

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(_SafeFormatter().format(record))

    logging.getLogger("continuity_lab").addHandler(Capture())
    modules = installed_modules()
    phase = sys.argv[1]
    now = BASE + timedelta(seconds=2) if phase == "verify" else BASE
    executions = PostgresExecutionStore(PostgresSettings.from_env(), clock=lambda: now)
    cases = PostgresCaseAuthority(executions, clock=lambda: now)
    lifecycle = PostgresLifecycle(executions, cases=cases, clock=lambda: now)
    effects = PostgresEffects(executions, cases=cases, clock=lambda: now)
    token = BearerToken(os.environ["DEMO_TOKEN"])
    directory = TokenDirectory({token: ACTOR})
    service = ScopedCaseService(directory, cases, lifecycle, effects=effects)
    task_id = uuid_identity(os.environ["DEMO_TASK_ID"])
    cancelled_id = uuid_identity(os.environ["DEMO_CANCEL_TASK_ID"])
    if task_id == cancelled_id:
        raise ValueError("Independent tasks are required")
    first = service.get(token=token, task_id=task_id)
    second = service.get(token=token, task_id=cancelled_id)
    if (
        first.case_id == second.case_id
        or task_id == first.case_id
        or cancelled_id == second.case_id
    ):
        raise RuntimeError("Task and case identities must remain distinct")

    def emit(result: dict[str, object], required: set[str]) -> None:
        events = {json.loads(row)["event"] for row in records}
        if not required <= events:
            raise RuntimeError("Required producer observations are missing")
        sensitive = (
            os.environ["DEMO_TOKEN"],
            os.environ["P1_POSTGRES_PASSWORD"],
            task_id,
            cancelled_id,
            first.case_id,
            second.case_id,
            SCOPE,
        )
        if any(value in row for row in records for value in sensitive):
            raise RuntimeError("Producer diagnostic privacy validation failed")
        metrics: dict[str, float] = {}
        for operation in sorted(OPERATIONS):
            labels = {"operation": operation, "outcome": "success"}
            count = service.telemetry.registry.get_sample_value(
                "continuity_case_operations_total", labels
            )
            if count is not None:
                durations = service.telemetry.registry.get_sample_value(
                    "continuity_case_operation_duration_seconds_count", labels
                )
                if count <= 0 or count != durations:
                    raise RuntimeError("Observed service operation metrics disagree")
                metrics[operation] = count
        if not metrics:
            raise RuntimeError("No real service operations were observed")
        result.update(
            {
                "phase": phase,
                "installed_modules": modules,
                "module_hashes_verified": True,
                "producer_events": sorted(events),
                "metric_operations": metrics,
                "safe_diagnostics_verified": True,
            }
        )
        print(json.dumps(result), flush=True)

    if phase == "seed":
        initialize_mutation_supplier(DATA / "supplier.sqlite3", scope_id=SCOPE)
        initialize_completion_sink(DATA / "completion.sqlite3")
        supplier = MutationSupplier(DATA / "supplier.sqlite3", clock=lambda: now)
        view = supplier.inquiry_view()
        before = supplier.booking(scope_id=SCOPE, booking_reference=BOOKING)
        for identity in (task_id, cancelled_id):
            completed = ManagedInquiryWorker(lifecycle, view).run_one(
                scope_id=SCOPE, task_id=identity
            )
            if completed.state != LifecycleState.INQUIRY_COMPLETE:
                raise RuntimeError("Managed inquiry did not complete")
        if (
            supplier.booking(scope_id=SCOPE, booking_reference=BOOKING) != before
            or before.revision != 0
            or before.check_in != date(2030, 12, 1)
            or supplier.count_mutations(scope_id=SCOPE) != 0
            or supplier.count_calls(scope_id=SCOPE) != 0
            or supplier.count_inquiries(scope_id=SCOPE) != 2
            or CompletionSink(DATA / "completion.sqlite3").count() != 0
        ):
            raise RuntimeError("Seed inquiry changed supplier mutation state")
        emit(
            {
                "status": "passed",
                "provider_id": supplier.provider_id,
                "expected_supplier_revision": before.revision,
                "inquiries": 2,
                "supplier_mutations": 0,
                "supplier_apply_calls": 0,
                "receiver_id": CompletionSink(DATA / "completion.sqlite3").receiver_id,
            },
            {
                "mutation_supplier_initialized",
                "completion_sink_initialized",
                "mutation_inquiry_created",
                "managed_worker_completed",
                "case_operation",
            },
        )
        return 0

    supplier = MutationSupplier(DATA / "supplier.sqlite3", clock=lambda: now)
    sink = CompletionSink(DATA / "completion.sqlite3", clock=lambda: now)
    if supplier.provider_id != uuid_identity(os.environ["DEMO_SUPPLIER_ID"]):
        raise RuntimeError("Persisted supplier differs from the intended authority")
    if first.intent is None or second.intent is None:
        raise RuntimeError("Both exact confirmations must already be committed")
    intent = first.intent
    if (
        intent.quote.supplier_id != supplier.provider_id
        or second.intent.quote.supplier_id != supplier.provider_id
    ):
        raise RuntimeError("Committed proposals target another authority")

    if phase == "crash-apply":
        if service.get_effect(token=token, task_id=task_id) is not None:
            raise RuntimeError("Crash probe must start before the first mutation claim")

        def crash_apply(point: str) -> None:
            if point == "mutation_worker.after_supplier_success":
                value = service.get_effect(token=token, task_id=task_id)
                known = supplier.lookup(intent)
                if (
                    value is None
                    or value.state != EffectState.DISPATCHED
                    or value.result is not None
                    or known is None
                ):
                    raise RuntimeError("Mutation crash boundary is invalid")
                if (
                    supplier.count_mutations(scope_id=SCOPE) != 1
                    or supplier.count_calls(scope_id=SCOPE) != 1
                ):
                    raise RuntimeError("Supplier did not retain exactly one mutation")
                if service.get_completion(token=token, task_id=task_id) is not None:
                    raise RuntimeError("Local completion unexpectedly acknowledged")
                emit(
                    {
                        "status": "crashed_as_planned",
                        "boundary": "supplier_success_before_ack",
                        "supplier_mutations": 1,
                        "supplier_apply_calls": 1,
                    },
                    {"mutation_dispatched", "mutation_applied", "case_operation"},
                )
                os._exit(71)

        MutationWorker(effects, supplier, failpoint=crash_apply).run_one(
            scope_id=SCOPE, task_id=task_id
        )
        raise RuntimeError("Mutation crash boundary was not reached")

    if phase == "reconcile":
        value = MutationWorker(effects, supplier).run_one(scope_id=SCOPE, task_id=task_id)
        known = supplier.lookup(intent)
        if (
            value is None
            or known is None
            or value.state != EffectState.SUCCEEDED
            or value.result != known.result
            or value.attempt_no != 2
            or value.dispatch_count != 1
        ):
            raise RuntimeError("Original supplier result was not reconciled")
        receipt = service.cancel(
            token=token, task_id=cancelled_id, command_id="cancel-before-apply"
        )
        replay = service.cancel(token=token, task_id=cancelled_id, command_id="cancel-before-apply")
        cancelled = MutationWorker(effects, supplier).run_one(scope_id=SCOPE, task_id=cancelled_id)
        if (
            receipt.disposition != CancellationDisposition.BEFORE_DISPATCH
            or receipt.cancellation_id != replay.cancellation_id
            or replay.created
            or cancelled is None
            or cancelled.state != EffectState.CANCELLED
            or cancelled.dispatch_count != 0
        ):
            raise RuntimeError("Cancellation did not prevent dispatch")
        completion = service.get_completion(token=token, task_id=task_id)
        if completion is None or completion.outcome.result != known.result or sink.count() != 0:
            raise RuntimeError("Mutation completion was not retained before delivery")
        if (
            supplier.count_mutations(scope_id=SCOPE) != 1
            or supplier.count_calls(scope_id=SCOPE) != 1
        ):
            raise RuntimeError("Reconciliation or cancellation resent a mutation")
        emit(
            {
                "status": "passed",
                "effect_id": intent.effect_id,
                "intent_id": intent.intent_id,
                "completion_event_id": completion.event_id,
                "state": value.state.value,
                "supplier_mutations": 1,
                "supplier_apply_calls": 1,
                "mutation_attempts": value.attempt_no,
                "cancelled_state": cancelled.state.value,
                "cancelled_dispatch_count": 0,
                "sink_receipts": 0,
            },
            {
                "mutation_reconciled",
                "mutation_worker_completed",
                "cancellation_recorded",
                "completion_committed",
                "case_operation",
            },
        )
        return 0

    if phase == "crash-deliver":

        def crash_deliver(point: str) -> None:
            if point == "outbox.after_sink_success":
                completion = service.get_completion(token=token, task_id=task_id)
                delivery = service.get_delivery(token=token, task_id=task_id)
                if (
                    completion is None
                    or delivery is None
                    or delivery.state != DeliveryState.DELIVERING
                    or sink.get(event_id=completion.event_id) != completion
                    or sink.count() != 1
                ):
                    raise RuntimeError("Delivery crash boundary is invalid")
                emit(
                    {
                        "status": "crashed_as_planned",
                        "boundary": "sink_success_before_ack",
                        "completion_event_id": completion.event_id,
                        "sink_receipts": 1,
                        "delivery_state": delivery.state.value,
                    },
                    {"completion_sink_accepted", "completion_delivery_started", "case_operation"},
                )
                os._exit(72)

        CompletionDeliveryWorker(effects, sink, failpoint=crash_deliver).run_one(
            scope_id=SCOPE, task_id=task_id
        )
        raise RuntimeError("Delivery crash boundary was not reached")

    delivered = CompletionDeliveryWorker(effects, sink).run_one(scope_id=SCOPE, task_id=task_id)
    repeated = CompletionDeliveryWorker(effects, sink).run_one(scope_id=SCOPE, task_id=task_id)
    completion = service.get_completion(token=token, task_id=task_id)
    value = service.get_effect(token=token, task_id=task_id)
    cancelled = service.get_effect(token=token, task_id=cancelled_id)
    retained = service.get_delivery(token=token, task_id=task_id)
    if (
        delivered is None
        or delivered.state != DeliveryState.DELIVERED
        or delivered.attempts != 2
        or delivered != repeated
        or retained != delivered
        or completion is None
        or delivered.event != completion
        or sink.count() != 1
        or sink.get(event_id=completion.event_id) != completion
    ):
        raise RuntimeError("Completion delivery did not retain one original event")
    if (
        value is None
        or value.state != EffectState.SUCCEEDED
        or value.result != completion.outcome.result
        or value.intent != intent
        or value.attempt_no != 2
        or value.dispatch_count != 1
    ):
        raise RuntimeError("Delivery changed original business truth")
    if (
        cancelled is None
        or cancelled.state != EffectState.CANCELLED
        or cancelled.dispatch_count != 0
    ):
        raise RuntimeError("Cancelled task acquired mutation authority")
    sink.prune_diagnostics(keep=0)
    if sink.diagnostic_count() != 0:
        raise RuntimeError("Receiver diagnostic pruning failed")
    replayed = sink.accept(completion)
    if replayed.created or replayed.event_id != completion.event_id or sink.count() != 1:
        raise RuntimeError("Diagnostic pruning weakened retained deduplication")
    if (
        MutationWorker(effects, supplier).run_one(scope_id=SCOPE, task_id=task_id) != value
        or supplier.count_mutations(scope_id=SCOPE) != 1
        or supplier.count_calls(scope_id=SCOPE) != 1
    ):
        raise RuntimeError("Final mutation replay changed the original effect")
    emit(
        {
            "status": "passed",
            "state": value.state.value,
            "effect_id": intent.effect_id,
            "intent_id": intent.intent_id,
            "completion_event_id": completion.event_id,
            "delivery_state": delivered.state.value,
            "delivery_attempts": delivered.attempts,
            "supplier_mutations": 1,
            "supplier_apply_calls": 1,
            "sink_receipts": 1,
            "cancelled_state": cancelled.state.value,
            "retained_deduplication_after_pruning": True,
        },
        {
            "completion_sink_replayed",
            "completion_delivery_observed",
            "completion_diagnostics_pruned",
            "case_operation",
        },
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - secret-safe installed runtime boundary
        print('{"status":"failed","code":"effect_probe_failed"}', flush=True)
        sys.exit(1)
