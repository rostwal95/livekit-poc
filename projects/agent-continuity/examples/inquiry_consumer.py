"""Independent installed-library consumer; synthetic data, no service deployment."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import continuity_lab
from continuity_lab.api import (
    BookingChange,
    ExecutionStatus,
    ExecutionStore,
    IdempotencyConflict,
    StorageUnavailable,
    TaskStore,
    migrate,
    safe_error_code,
)
from continuity_lab.testing import FakeSupplier, InquiryWorker, initialize_supplier


def main() -> int:
    installed = Path(continuity_lab.__file__).resolve()
    assert installed.is_relative_to(Path(sys.prefix).resolve())
    assert "site-packages" in installed.parts
    assert sys.prefix != sys.base_prefix
    assert all(
        importlib.util.find_spec(name) is None
        for name in ("services", "harness", "psycopg", "livekit", "prometheus_client")
    )
    with TemporaryDirectory(prefix="installed-inquiry-") as directory:
        root = Path(directory)
        database, supplier_database = root / "inquiry.sqlite3", root / "supplier.sqlite3"
        request = BookingChange("DEMO-BK-001", date(2030, 12, 10), True)
        legacy = TaskStore(database).submit(
            scope_id="example-traveller", idempotency_key="original-request", request=request
        )
        report = migrate(database, root / "before-v1.sqlite3")
        assert report.changed and report.backfilled == 1
        store = ExecutionStore(database)
        accepted = store.submit(
            scope_id="example-traveller", idempotency_key="original-request", request=request
        )
        assert accepted.execution.task_id == legacy.task.task_id
        assert not accepted.created and not accepted.enrolled
        initialize_supplier(supplier_database, scope_id="example-traveller")
        completed = InquiryWorker(store, FakeSupplier(supplier_database)).run_one(
            scope_id="example-traveller", task_id=accepted.execution.task_id
        )
        assert completed.status == ExecutionStatus.SUCCEEDED
        assert completed.result is not None and completed.result.available
        replay = ExecutionStore(database).submit(
            scope_id="example-traveller", idempotency_key="original-request", request=request
        )
        assert replay.execution == completed and not replay.created and not replay.enrolled
        supplier = FakeSupplier(supplier_database)
        booking = supplier.booking(
            scope_id="example-traveller", booking_reference=request.booking_reference
        )
        assert booking.revision == 0 and booking.check_in == date(2030, 12, 1)
        assert supplier.count_inquiries(scope_id="example-traveller") == 1
        try:
            store.submit(
                scope_id="example-traveller",
                idempotency_key="original-request",
                request=BookingChange("DEMO-BK-001", date(2030, 12, 11), True),
            )
        except IdempotencyConflict as conflict:
            conflict_code = safe_error_code(conflict)
        else:
            raise AssertionError("Changed content unexpectedly replayed")
        assert conflict_code == "idempotency_conflict"
        try:
            ExecutionStore(root / "private-storage-sentinel" / "absent.sqlite3")
        except StorageUnavailable as failure:
            storage_code = safe_error_code(failure)
        else:
            raise AssertionError("Missing storage unexpectedly opened")
        assert storage_code == "storage_unavailable"
        assert (
            ExecutionStore(database).get(scope_id="example-traveller", task_id=completed.task_id)
            == completed
        )
    print(
        json.dumps(
            {
                "schema_version": 1,
                "status": "passed",
                "distribution_version": importlib.metadata.version("agent-continuity"),
                "installed_isolated": True,
                "optional_services_absent": True,
                "legacy_task_preserved": True,
                "same_identity_replay": True,
                "inquiry_succeeded": True,
                "booking_unchanged": True,
                "supplier_receipts": 1,
                "conflict_code": conflict_code,
                "storage_failure_code": storage_code,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
