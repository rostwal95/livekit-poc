"""Installed application consumer for the isolated Phase D container demo."""

import hashlib
import importlib
import json
import logging
import os
import sys
from collections import deque
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from continuity_lab.authorization import AuthenticatedActor, BearerToken, TokenDirectory
from continuity_lab.case_models import Confirmation
from continuity_lab.case_service import ScopedCaseService
from continuity_lab.execution_cli import _SafeFormatter, configure_logging
from continuity_lab.execution_models import ExecutionError
from continuity_lab.postgres_case import PostgresCaseAuthority
from continuity_lab.postgres_lifecycle import PostgresLifecycle
from continuity_lab.postgres_settings import PostgresSettings
from continuity_lab.postgres_store import PostgresExecutionStore

BASE = datetime(2030, 12, 1, tzinfo=UTC)


def main() -> int:
    configure_logging()
    records: deque[str] = deque(maxlen=256)

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(_SafeFormatter().format(record))

    logging.getLogger("continuity_lab").addHandler(Capture())
    expected = json.loads(os.environ["DEMO_MODULE_HASHES"])
    for name, digest in expected.items():
        module = importlib.import_module("continuity_lab." + name)
        if module.__file__ is None:
            raise RuntimeError("Installed module path is unavailable")
        path = Path(module.__file__).resolve()
        if (
            "/site-packages/" not in str(path)
            or hashlib.sha256(path.read_bytes()).hexdigest() != digest
        ):
            raise RuntimeError("Installed module validation failed")
    phase = sys.argv[1]
    now = BASE + timedelta(seconds=5) if phase == "prepare" else BASE + timedelta(minutes=2)
    executions = PostgresExecutionStore(PostgresSettings.from_env())
    cases = PostgresCaseAuthority(executions, clock=lambda: now)
    lifecycle = PostgresLifecycle(executions, cases=cases, clock=lambda: now)
    token = BearerToken(os.environ["DEMO_TOKEN"])
    directory = TokenDirectory({token: AuthenticatedActor("demo-owner", "phase-d-demo")})
    service = ScopedCaseService(directory, cases, lifecycle)
    task_id, expired_id = os.environ["DEMO_TASK_ID"], os.environ["DEMO_EXPIRED_TASK_ID"]
    first = service.get(token=token, task_id=task_id)
    expired = service.get(token=token, task_id=expired_id)
    assert (
        first.case_id != task_id
        and expired.case_id != expired_id
        and first.case_id != expired.case_id
    )
    if first.quote is None or expired.quote is None:
        raise RuntimeError("Demo requires persisted proposals")
    confirmation = Confirmation(first.quote, True)
    event = "early-confirmation"
    if phase == "prepare":
        signal = service.signal(token=token, event_id=event, confirmation=confirmation)
        assert signal.created and signal.consumed_wait_id is None
        primary = service.arm_wait(
            token=token,
            task_id=task_id,
            wait_id=os.environ["DEMO_WAIT_ID"],
            quote=first.quote,
            deadline=BASE + timedelta(minutes=30),
        )
        expiring = service.arm_wait(
            token=token,
            task_id=expired_id,
            wait_id=os.environ["DEMO_EXPIRED_WAIT_ID"],
            quote=expired.quote,
            deadline=BASE + timedelta(minutes=1),
        )
        assert primary.state == expiring.state == "pending"
        for identity in (task_id, expired_id):
            assert service.get_lifecycle(token=token, task_id=identity).state == "waiting"
            assert service.get(token=token, task_id=identity).intent is None
        result = {
            "status": "passed",
            "phase": "prepared",
            "case_id": first.case_id,
            "early_signal_retained": True,
            "wait_state": primary.state,
            "task_id": task_id,
        }
    elif phase == "advance":
        advanced = service.advance(token=token, task_id=task_id)
        repeated = service.advance(token=token, task_id=task_id)
        assert advanced.intent is not None and repeated.intent == advanced.intent
        receipt = service.signal(token=token, event_id=event, confirmation=confirmation)
        assert not receipt.created and receipt.consumed_wait_id == os.environ["DEMO_WAIT_ID"]
        expired_state = service.advance(token=token, task_id=expired_id)
        assert (
            expired_state.lifecycle.state == "failed"
            and expired_state.lifecycle.error_code == "deadline_expired"
        )
        rejected = False
        try:
            service.confirm(
                token=token, confirmation=Confirmation(expired.quote, True), command_id="too-late"
            )
        except ExecutionError as error:
            assert error.code == "transition_conflict"
            rejected = True
        else:
            raise RuntimeError("Expired continuation unexpectedly committed an intent")
        assert rejected and service.get(token=token, task_id=expired_id).intent is None
        assert len(cases.dispatches(actor=directory.authenticate(token), task_id=task_id)) == 1
        for operation, outcome, minimum in (
            ("advance", "success", 3),
            ("signal", "success", 1),
            ("confirm", "rejected", 1),
        ):
            labels = {"operation": operation, "outcome": outcome}
            count = service.telemetry.registry.get_sample_value(
                "continuity_case_operations_total", labels
            )
            durations = service.telemetry.registry.get_sample_value(
                "continuity_case_operation_duration_seconds_count", labels
            )
            assert count is not None and count >= minimum and durations == count
        result = {
            "status": "passed",
            "phase": "advanced",
            "case_id": first.case_id,
            "lifecycle": advanced.lifecycle.state,
            "intent": asdict(advanced.intent),
            "expired_wait_state": expired_state.lifecycle.state,
            "expired_wait_code": expired_state.lifecycle.error_code,
            "signal_replayed": True,
            "logical_dispatch_events": 1,
            "installed_modules": len(expected),
            "metric_operations_observed": True,
        }
    else:
        raise ValueError("Unknown demo stage")
    events = {json.loads(row)["event"] for row in records}
    required = (
        {"case_operation", "confirmation_signal_accepted", "confirmation_wait_armed"}
        if phase == "prepare"
        else {
            "case_operation",
            "confirmation_signal_replayed",
            "intent_committed",
            "confirmation_wait_advanced",
        }
    )
    assert required <= events
    assert all(
        os.environ["DEMO_TOKEN"] not in row and task_id not in row and expired_id not in row
        for row in records
    )
    result["producer_events"] = sorted(events)
    print(json.dumps(result, default=str))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - secret-safe standalone demo boundary
        print('{"status":"failed","code":"case_probe_failed"}')
        sys.exit(1)
