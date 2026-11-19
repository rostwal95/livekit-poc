"""Run one explicitly accepted inquiry under a cooperative local worker lock.

This is the SQLite/macOS/Linux inquiry subset: no polling loop, automatic retry,
lease, mutation or coroutine checkpoint. Supplier calls occur after the attempt
transaction commits. A new invocation reconciles a stopped worker's stable effect.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import NoReturn

from .execution import ExecutionStore
from .execution_cli import configure_logging
from .execution_models import (
    ExecutionError,
    ExecutionRecord,
    ExecutionStatus,
    FailureCode,
    WorkerExecutionPort,
)
from .migrations import MigrationError
from .sqlite_admission import SourceAdmissionClosed
from .supplier import FakeSupplier, SupplierRejected
from .worker_lock import WORKER_LOCK_SUFFIX, WorkerBusy, WorkerLockUnavailable

__all__ = ["InquiryWorker", "WorkerBusy", "WorkerLockUnavailable", "main"]

LOGGER = logging.getLogger("continuity_lab.inquiry_worker")
if not any(isinstance(handler, logging.NullHandler) for handler in LOGGER.handlers):
    LOGGER.addHandler(logging.NullHandler())

_FAILURE_CODES = frozenset(
    {
        "execution_error",
        "execution_not_found",
        "transition_conflict",
        "unsupported_operation",
        "storage_unavailable",
        "invalid_stored_state",
        "capacity_exhausted",
        "inquiry_rejected",
        "inquiry_conflict",
        "dependency_unavailable",
        "schema_version_unsupported",
        "migration_failed",
        "invalid_input",
        "unexpected_error",
        "source_quiesced",
    }
)


def _error_code(error: Exception) -> str:
    if isinstance(error, SourceAdmissionClosed):
        return "source_quiesced"
    if isinstance(error, (ExecutionError, MigrationError)):
        try:
            candidate = error.code
            if type(candidate) is str and candidate in _FAILURE_CODES:
                return candidate
        except Exception:  # noqa: BLE001 - diagnostic metadata cannot replace an original failure
            return "execution_error"
        return "execution_error"
    if isinstance(error, ValueError):
        return "invalid_input"
    return "unexpected_error"


def _event(event: str, code: str = "ok") -> None:
    """Producer literals only; no exception, SQL, scope, request or provider text."""
    level = logging.INFO
    if event == "worker_failed":
        level = logging.WARNING if code == "capacity_exhausted" else logging.ERROR
    elif code == "inquiry_rejected":
        level = logging.WARNING
    try:
        LOGGER.log(level, event, extra={"event": event, "code": code})
    except Exception:  # noqa: BLE001 - telemetry cannot alter inquiry truth or failures
        return


class InquiryWorker:
    """Execute/reconcile one inquiry; domain failure never grants mutation authority."""

    def __init__(
        self,
        executions: WorkerExecutionPort,
        supplier: FakeSupplier,
        *,
        failpoint: Callable[[str], None] | None = None,
    ) -> None:
        if isinstance(executions, ExecutionStore) and (
            executions.database == supplier.database
            or os.path.samefile(executions.database, supplier.database)
        ):
            raise ValueError("Execution and supplier state must use independent files")
        self.executions, self.supplier, self.failpoint = executions, supplier, failpoint
        self.lock_path = (
            executions.database.with_name(executions.database.name + WORKER_LOCK_SUFFIX)
            if isinstance(executions, ExecutionStore)
            else None
        )

    def run_one(self, *, scope_id: str, task_id: str) -> ExecutionRecord:
        """Hold the cooperative slot, commit a claim, then call the supplier.

        A stopped RUNNING attempt is explicitly replaced through recover_attempt.
        Any non-definitive supplier/dependency error leaves it RUNNING for manual
        reconciliation. The store enforces its finite manual-attempt bound.
        """
        try:
            with self.executions.worker_slot():
                current = self.executions.get(scope_id=scope_id, task_id=task_id)
                if current.status in {ExecutionStatus.SUCCEEDED, ExecutionStatus.FAILED}:
                    return current
                if current.status == ExecutionStatus.ACCEPTED:
                    started = self.executions.start_attempt(
                        scope_id=scope_id, task_id=task_id, expected_version=current.version
                    )
                else:
                    started = self.executions.recover_attempt(
                        scope_id=scope_id, task_id=task_id, expected_version=current.version
                    )
                try:
                    observation = self.supplier.lookup(
                        scope_id=scope_id,
                        effect_id=started.execution.effect_id,
                        request=started.execution.request,
                    )
                    if observation is None:
                        _event("inquiry_dispatched")
                        observation = self.supplier.inquire(
                            scope_id=scope_id,
                            effect_id=started.execution.effect_id,
                            request=started.execution.request,
                        )
                    else:
                        _event("inquiry_reconciled")
                except SupplierRejected:
                    completed = self.executions.finish_attempt(
                        scope_id=scope_id,
                        task_id=task_id,
                        attempt_id=started.attempt.attempt_id,
                        expected_version=started.execution.version,
                        error_code=FailureCode.INQUIRY_REJECTED,
                    )
                    _event("worker_completed", "inquiry_rejected")
                    return completed
                if self.failpoint is not None:
                    self.failpoint("worker.after_supplier_success")
                completed = self.executions.finish_attempt(
                    scope_id=scope_id,
                    task_id=task_id,
                    attempt_id=started.attempt.attempt_id,
                    expected_version=started.execution.version,
                    result=observation.result,
                )
                _event("worker_completed", "succeeded")
                return completed
        except Exception as error:
            # Observe this worker outcome once, then retain the original failure.
            _event("worker_failed", _error_code(error))
            raise


class _SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.exit(
            2,
            '{"status":"failed","code":"invalid_command","message":"Invalid arguments; use --help."}\n',
        )


def main(argv: list[str] | None = None) -> int:
    parser = _SafeParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--supplier-db", type=Path, required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--task-id", required=True)
    args = parser.parse_args(argv)
    configure_logging()
    entered_worker = False
    try:
        worker = InquiryWorker(ExecutionStore(args.db), FakeSupplier(args.supplier_db))
        entered_worker = True
        result = worker.run_one(scope_id=args.scope, task_id=args.task_id)
    except Exception as error:  # noqa: BLE001 - secret-safe CLI containment
        if not entered_worker and _error_code(error) == "unexpected_error":
            _event("worker_failed", "unexpected_error")
        # Do not print the dependency error or its chain, even for unexpected defects.
        print(
            json.dumps(
                {
                    "status": "failed",
                    "code": _error_code(error),
                    "message": "Worker failed; inspect the safe code and retained state.",
                }
            )
        )
        return 1 if _error_code(error) == "unexpected_error" else 2
    print(json.dumps(asdict(result), default=str, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
