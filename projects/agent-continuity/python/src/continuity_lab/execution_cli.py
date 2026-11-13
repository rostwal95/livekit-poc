"""Explicit offline migration and inquiry admission; no worker is started here."""

import argparse
import json
import logging
import sys
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import NoReturn

from .execution import ExecutionStore
from .execution_models import ExecutionError
from .migrations import MigrationError, migrate
from .models import BookingChange, IdempotencyConflict, IntakeCapacityExceeded
from .sqlite_admission import SourceAdmissionClosed

_CODES = frozenset(
    {
        "ok",
        "succeeded",
        "failed",
        "execution_error",
        "execution_not_found",
        "transition_conflict",
        "unsupported_operation",
        "storage_unavailable",
        "invalid_stored_state",
        "capacity_exhausted",
        "execution_port_closed",
        "migration_failed",
        "schema_version_unsupported",
        "idempotency_conflict",
        "invalid_input",
        "inquiry_conflict",
        "inquiry_rejected",
        "dependency_unavailable",
        "unexpected_error",
        "source_quiesced",
        "authentication_required",
        "cutover_failed",
        "stale_revision",
        "quote_expired",
        "invalid_confirmation",
        "case_cancelled",
        "intent_committed",
        "permanent_failure",
        "retry_exhausted",
        "deadline_expired",
        "ambiguous_outcome",
        "lease_busy",
        "lease_lost",
        "lease_required",
        "worker_runtime_failed",
        "worker_output_limit",
        "worker_cleanup_incomplete",
        "worker_health_unavailable",
        "worker_step_interrupted",
        "mutation_rejected",
        "mutation_conflict",
        "supplier_rejected",
        "attempts_exhausted",
        "delivery_exhausted",
    }
)
_EVENTS = frozenset(
    {
        "execution_cli",
        "trace_shutdown_incomplete",
        "worker_trace_cleanup_failed",
        "event",
        "execution_lease_acquired",
        "execution_lease_released",
        "execution_lease_renewed",
        "worker_cli_failed",
        "worker_health_failed",
        "worker_queue_observation_failed",
        "worker_release_failed",
        "worker_runtime_started",
        "worker_runtime_stopped",
        "worker_step_finished",
        "worker_step_started",
        "cancellation_recorded",
        "completion_committed",
        "completion_delivered",
        "completion_delivery_failed",
        "completion_delivery_observed",
        "completion_delivery_started",
        "completion_diagnostics_pruned",
        "completion_sink_accepted",
        "completion_sink_initialized",
        "completion_sink_replayed",
        "completion_sink_unavailable",
        "mutation_applied",
        "mutation_claimed",
        "mutation_dispatch_reserved",
        "mutation_dispatched",
        "mutation_finished",
        "mutation_inquiry_created",
        "mutation_lookup_found",
        "mutation_lookup_missing",
        "mutation_reconciled",
        "mutation_replayed",
        "mutation_supplier_failed",
        "mutation_supplier_initialized",
        "mutation_supplier_rejected",
        "mutation_worker_completed",
        "mutation_worker_failed",
        "execution_accepted",
        "execution_replayed",
        "storage_failed",
        "attempt_started",
        "attempt_recovered",
        "supplier_initialized",
        "supplier_unavailable",
        "supplier_replay_conflict",
        "supplier_inquiry_replayed",
        "supplier_inquiry_created",
        "supplier_lookup_missing",
        "supplier_lookup_found",
        "supplier_initialization_rejected",
        "supplier_initialization_failed",
        "inquiry_dispatched",
        "inquiry_reconciled",
        "worker_completed",
        "worker_failed",
        "attempt_finished",
        "authentication_rejected",
        "command_failed",
        "source_quiesced",
        "source_cutover",
        "postgres_schema_installed",
        "postgres_import_staged",
        "postgres_import_replayed",
        "postgres_import_activated",
        "postgres_schema_upgraded",
        "confirmation_signal_accepted",
        "confirmation_signal_replayed",
        "confirmation_wait_advanced",
        "confirmation_wait_armed",
        "continuation_enabled",
        "managed_attempt_completed",
        "managed_attempt_started",
        "managed_inquiry_dispatched",
        "managed_inquiry_reconciled",
        "managed_worker_completed",
        "managed_worker_failed",
        "case_operation",
        "case_enrolled",
        "case_replayed",
        "case_revised",
        "quote_published",
        "quote_replayed",
        "intent_committed",
        "intent_replayed",
    }
)


class _SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.exit(
            2,
            '{"status":"failed","code":"invalid_command","message":"Invalid arguments; use --help."}\n',
        )


class _SafeFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event, code = getattr(record, "event", "execution_cli"), getattr(record, "code", "ok")
        payload = {
            "service": "continuity-execution",
            "timestamp": datetime.now(UTC).isoformat(),
            "severity": record.levelname.lower(),
            "event": event if isinstance(event, str) and event in _EVENTS else "execution_cli",
            "code": code if isinstance(code, str) and code in _CODES else "execution_error",
        }
        operation, outcome = getattr(record, "operation", None), getattr(record, "outcome", None)
        if isinstance(operation, str) and operation in {
            "enroll",
            "managed_submit",
            "projection",
            "prepare_quote",
            "get",
            "revise",
            "confirm",
            "arm_wait",
            "signal",
            "advance",
            "waits",
            "lifecycle",
            "cancel",
            "effect",
            "completion",
            "delivery",
        }:
            payload["operation"] = operation
        if isinstance(outcome, str) and outcome in {"success", "rejected", "failed"}:
            payload["outcome"] = outcome
        return json.dumps(payload)


class _ApplicationHandler(logging.StreamHandler):
    pass


def configure_logging() -> None:
    """Explicit application setup; domain imports do not configure root logging."""
    logger = logging.getLogger("continuity_lab")
    if not any(isinstance(handler, _ApplicationHandler) for handler in logger.handlers):
        handler = _ApplicationHandler()
        handler.setFormatter(_SafeFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def main(argv: list[str] | None = None) -> int:
    parser = _SafeParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    migration = commands.add_parser("migrate", help="explicit quiesced migration with a backup")
    migration.add_argument("--backup", type=Path, required=True)
    submit = commands.add_parser("submit", help="accept or explicitly enroll an inquiry")
    submit.add_argument("--scope", required=True)
    submit.add_argument("--key", required=True)
    submit.add_argument("--booking", required=True)
    submit.add_argument("--check-in", type=date.fromisoformat, required=True)
    submit.add_argument("--confirm", action="store_true")
    inspect = commands.add_parser("get", help="read one explicitly enrolled inquiry")
    inspect.add_argument("--scope", required=True)
    inspect.add_argument("--task-id", required=True)
    listing = commands.add_parser("list", help="read bounded scoped inquiry state")
    listing.add_argument("--scope", required=True)
    listing.add_argument("--limit", type=int, default=100)
    args = parser.parse_args(argv)
    configure_logging()
    try:
        if args.command == "migrate":
            value: object = asdict(migrate(args.db, args.backup))
        else:
            store = ExecutionStore(args.db)
            if args.command == "submit":
                value = asdict(
                    store.submit(
                        scope_id=args.scope,
                        idempotency_key=args.key,
                        request=BookingChange(args.booking, args.check_in, args.confirm),
                    )
                )
            elif args.command == "get":
                value = asdict(store.get(scope_id=args.scope, task_id=args.task_id))
            else:
                value = [
                    asdict(record) for record in store.list(scope_id=args.scope, limit=args.limit)
                ]
        print(json.dumps(value, default=str, indent=2))
        return 0
    except (
        ExecutionError,
        MigrationError,
        IdempotencyConflict,
        IntakeCapacityExceeded,
        ValueError,
        OSError,
    ) as error:
        if isinstance(error, SourceAdmissionClosed):
            code = "source_quiesced"
        elif isinstance(error, IdempotencyConflict):
            code = "idempotency_conflict"
        elif isinstance(error, IntakeCapacityExceeded):
            code = "capacity_exhausted"
        else:
            candidate = getattr(error, "code", "invalid_input")
            code = (
                candidate if isinstance(candidate, str) and candidate in _CODES else "invalid_input"
            )
        # stdout is a safe command result; stderr contains producer logs only.
        print(
            json.dumps(
                {
                    "status": "failed",
                    "code": code,
                    "message": "Command failed; inspect the safe code and retained state.",
                }
            )
        )
        if code != "storage_unavailable":
            logging.getLogger("continuity_lab").warning(
                "command_failed",
                extra={"event": "command_failed", "code": code},
            )
        return 2
    except Exception:  # noqa: BLE001 - sanitized outer command boundary
        print(
            json.dumps(
                {
                    "status": "failed",
                    "code": "unexpected_error",
                    "message": "Command failed; inspect the safe code and retained state.",
                }
            )
        )
        logging.getLogger("continuity_lab").error(
            "command_failed",
            extra={"event": "command_failed", "code": "unexpected_error"},
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
