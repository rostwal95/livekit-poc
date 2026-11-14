"""Explicit local PostgreSQL administration and trusted operator inquiry commands.

Credentials come only from the named environment. This is a synthetic local
operator boundary, not a public multi-tenant API or migration daemon.
"""

import json
import logging
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

from .cutover import cutover
from .execution_cli import _CODES, _SafeParser, configure_logging
from .execution_models import ExecutionError
from .inquiry_worker import InquiryWorker
from .managed_inquiry_worker import ManagedInquiryWorker
from .migrations import MigrationError
from .models import BookingChange, IdempotencyConflict, IntakeCapacityExceeded
from .postgres_lifecycle import PostgresLifecycle
from .postgres_migrations import (
    install_schema,
    read_import_state,
    upgrade_v2,
    upgrade_v3,
    upgrade_v4,
    upgrade_v5,
)
from .postgres_settings import PostgresSettings
from .postgres_store import PostgresExecutionStore
from .sqlite_admission import SourceAdmissionClosed
from .supplier import FakeSupplier


def main(argv: list[str] | None = None) -> int:
    parser = _SafeParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("schema", help="owner-only schema preparation; does not activate")
    commands.add_parser("upgrade", help="owner-only additive ACTIVE v1 to v2 upgrade")
    commands.add_parser("upgrade-effects", help="owner-only additive ACTIVE v2 to v3 upgrade")
    commands.add_parser("upgrade-coordination", help="owner-only additive ACTIVE v3 to v4 upgrade")
    commands.add_parser("upgrade-retry-pacing", help="owner-only additive ACTIVE v4 to v5 upgrade")
    transfer = commands.add_parser(
        "cutover", help="quiesce, verify and activate an existing v1 source"
    )
    transfer.add_argument("--source", type=Path, required=True)
    transfer.add_argument("--backup", type=Path, required=True)
    commands.add_parser("status", help="runtime schema/readiness check; active target required")
    submit = commands.add_parser("submit", help="trusted operator admission")
    submit.add_argument("--scope", required=True)
    submit.add_argument("--key", required=True)
    submit.add_argument("--booking", required=True)
    submit.add_argument("--check-in", type=date.fromisoformat, required=True)
    submit.add_argument("--confirm", action="store_true")
    for command in ("get", "history", "work", "work-managed"):
        item = commands.add_parser(command)
        item.add_argument("--scope", required=True)
        item.add_argument("--task-id", required=True)
        if command in {"work", "work-managed"}:
            item.add_argument("--supplier-db", type=Path, required=True)
    listing = commands.add_parser("list")
    listing.add_argument("--scope", required=True)
    listing.add_argument("--limit", type=int, default=100)
    args = parser.parse_args(argv)
    configure_logging()
    try:
        value: object
        if args.command in {
            "schema",
            "cutover",
            "upgrade",
            "upgrade-effects",
            "upgrade-coordination",
            "upgrade-retry-pacing",
        }:
            settings = PostgresSettings.from_env("P1_MIGRATION_")
            if args.command == "upgrade-retry-pacing":
                value = asdict(upgrade_v5(settings))
            elif args.command == "upgrade-coordination":
                value = asdict(upgrade_v4(settings))
            elif args.command == "upgrade-effects":
                value = asdict(upgrade_v3(settings))
            elif args.command == "upgrade":
                value = asdict(upgrade_v2(settings))
            elif args.command == "schema":
                install_schema(settings)
                value = {
                    "status": "schema_prepared",
                    "backend": "postgres",
                    "activation": "not_requested",
                }
            else:
                value = asdict(cutover(args.source, args.backup, settings))
        else:
            store = PostgresExecutionStore(PostgresSettings.from_env())
            if args.command == "status":
                value = {
                    "status": "ready",
                    "backend": "postgres",
                    "schema_version": read_import_state(store.settings).version,
                    "state": "active",
                }
            elif args.command == "submit":
                value = asdict(
                    store.submit(
                        scope_id=args.scope,
                        idempotency_key=args.key,
                        request=BookingChange(args.booking, args.check_in, args.confirm),
                    )
                )
            elif args.command == "get":
                value = asdict(store.get(scope_id=args.scope, task_id=args.task_id))
            elif args.command == "history":
                value = [
                    asdict(row) for row in store.attempts(scope_id=args.scope, task_id=args.task_id)
                ]
            elif args.command == "work-managed":
                value = asdict(
                    ManagedInquiryWorker(
                        PostgresLifecycle(store), FakeSupplier(args.supplier_db)
                    ).run_one(scope_id=args.scope, task_id=args.task_id)
                )
            elif args.command == "work":
                value = asdict(
                    InquiryWorker(store, FakeSupplier(args.supplier_db)).run_one(
                        scope_id=args.scope, task_id=args.task_id
                    )
                )
            else:
                value = [asdict(row) for row in store.list(scope_id=args.scope, limit=args.limit)]
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
                candidate
                if isinstance(candidate, str) and candidate in _CODES
                else "execution_error"
            )
        result = 2
    except Exception:  # noqa: BLE001 - sanitized application command boundary
        code, result = "unexpected_error", 1
    print(
        json.dumps(
            {
                "status": "failed",
                "code": code,
                "message": "Command failed; inspect the safe code and retained state.",
            }
        )
    )
    logging.getLogger("continuity_lab").error(
        "command_failed", extra={"event": "command_failed", "code": code}
    )
    return result


if __name__ == "__main__":
    sys.exit(main())
