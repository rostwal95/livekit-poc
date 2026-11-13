# Investigation intake starter walkthrough

Status: Active
Last reviewed: 10 November 2026

This walkthrough covers the implemented M1 starter. The
[portfolio scope](portfolio-scope.md) owns V1 boundaries and the
[build plan](build-plan.md) owns future implementation sequencing.

## Implemented behavior

A local CLI accepts an explicitly confirmed request to investigate a synthetic
booking change. SQLite stores its canonical payload and scoped idempotency key.
Identical replay returns the original task; changed content under that identity
produces a conflict. The current state is queued only.

Confirmation is a starter precondition. It permits investigation, not a booking
mutation, and does not prove identity. This original M1 walkthrough does not
invoke a worker, supplier or LiveKit adapter. The separate inquiry/recovery slice
is now implemented; see the [P1 guide](../projects/agent-continuity/README.md).

## Run an isolated example

From the repository root with the documented Python environment:

```sh
.venv/bin/python -m continuity_lab demo
.venv/bin/python -m harness run BASE-01
```

The demo creates a temporary database, submits a request, reopens it, retries the
request and rejects a conflict. It removes temporary state on exit. BASE-01
separately checks actual fresh-process reads and concurrent intake.

## Keep state between commands

```sh
.venv/bin/python -m continuity_lab submit --key change-001 --booking DEMO-BK-001 --check-in 2030-12-10 --confirm
.venv/bin/python -m continuity_lab list
```

Repeat the submission to obtain the same task with created=false. Keep the key
and change the date to obtain a conflict and exit 2. A new logical intent needs a
new key. Persistent state lives under ignored .local.

## Read the code

1. projects/agent-continuity/python/src/continuity_lab/models.py defines the confirmed investigation request and results.
2. projects/agent-continuity/python/src/continuity_lab/store.py defines canonicalization and transaction boundaries.
3. tests/test_intake.py checks conflicts, concurrency and fresh-process reads.
4. projects/agent-continuity/python/src/continuity_lab/__main__.py provides the CLI adapter.

Explain failure windows before commit, after commit and before the caller sees
the result. A successful intake commit does not establish execution or supplier
outcome. This original M1 CLI uses synchronous SQLite. The new execution port has bounded
async offload; conversational integration must use that boundary.

## Next implementation boundary

The implemented inquiry slice adds explicit migration, persisted execution and
a read-only fake supplier. Its real process test crashes after inquiry success
and recovers the original inquiry without changing the booking. PostgreSQL is
required for the later multi-worker V1 gate. Follow the build plan and
[P1 charter](projects/agent-continuity-scope.md) for acceptance criteria.
