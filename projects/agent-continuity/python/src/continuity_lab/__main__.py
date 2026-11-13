"""Local commands. All references and requests in the demo are synthetic."""

import argparse
import json
import sqlite3
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from .models import BookingChange, IdempotencyConflict
from .store import TaskStore


def demo() -> None:
    """Show persistence and duplicate intake without keys, network, or paid APIs."""
    with TemporaryDirectory(prefix="continuity-lab-") as directory:
        database = Path(directory) / "tasks.sqlite3"
        request = BookingChange("DEMO-BK-001", date(2030, 12, 10), confirmed=True)
        first = TaskStore(database).submit(
            scope_id="demo-traveller", idempotency_key="change-001", request=request
        )
        # Reconstruct the store; no Python object supplies the persisted task.
        replay = TaskStore(database).submit(
            scope_id="demo-traveller", idempotency_key="change-001", request=request
        )
        print("Milestone 1: offline durable request intake")
        print(f"Accepted task: {first.task.task_id}; created={first.created}")
        print(f"Reopened store: same_task={replay.task == first.task}; created={replay.created}")
        try:
            TaskStore(database).submit(
                scope_id="demo-traveller",
                idempotency_key="change-001",
                request=BookingChange("DEMO-BK-001", date(2030, 12, 11), confirmed=True),
            )
        except IdempotencyConflict:
            print("Conflicting replay: rejected; original request preserved")
        print("Status: queued. Worker, voice and text adapters are later milestones.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path(".local/tasks.sqlite3"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("demo", help="run an isolated offline demo")
    submit = commands.add_parser("submit", help="persist a confirmed investigation request")
    submit.add_argument("--scope", default="demo-traveller")
    submit.add_argument("--key", required=True, help="stable key retained across retries")
    submit.add_argument("--booking", required=True)
    submit.add_argument("--check-in", required=True, type=date.fromisoformat)
    submit.add_argument("--confirm", action="store_true")
    listing = commands.add_parser("list", help="show durable requests for one local scope")
    listing.add_argument("--scope", default="demo-traveller")
    args = parser.parse_args()

    try:
        if args.command == "demo":
            demo()
            return 0
        args.db.parent.mkdir(parents=True, exist_ok=True)
        if args.command == "submit":
            request = BookingChange(args.booking, args.check_in, confirmed=args.confirm)
            result = TaskStore(args.db).submit(
                scope_id=args.scope, idempotency_key=args.key, request=request
            )
            print(json.dumps(asdict(result), default=str, indent=2))
        else:
            tasks = TaskStore(args.db).list_tasks(scope_id=args.scope)
            print(json.dumps([asdict(task) for task in tasks], default=str, indent=2))
    except (ValueError, sqlite3.Error, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
