# Investigation intake starter walkthrough

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Walk newcomers through running and reading the original M1 confirmed-investigation intake on SQLite |
| Audience | Engineers new to the repository |
| Scope | The M1 starter's behavior, commands, code and next boundary; excludes V1 boundaries and future sequencing |
| Owns | The M1 starter walkthrough: example commands, code reading order and failure windows |
| Related | [Portfolio scope](portfolio-scope.md) · [Build plan](build-plan.md) · [P1 guide](../projects/agent-continuity/README.md) · [P1 charter](projects/agent-continuity-scope.md) |

This walkthrough is for engineers new to the repository who want to run and read
the implemented M1 starter, the original confirmed-investigation intake on
SQLite. It covers what the starter does, how to run it, where its code lives and
what the next slice added. The [portfolio scope](portfolio-scope.md) owns V1
boundaries, and the [build plan](build-plan.md) owns future implementation
sequencing.

## Implemented behavior

A local command-line interface (CLI) accepts an explicitly confirmed request to
investigate a synthetic booking change.

| Input or state | Result |
| --- | --- |
| A confirmed request | SQLite stores the request's canonical payload and scoped idempotency key |
| Identical replay | Returns the original task |
| Changed content under that identity | Produces a conflict |
| Current state | Queued only |

Confirmation is a starter precondition. It permits investigation, not a booking
mutation, and it does not prove identity. This original M1 walkthrough does not
invoke a worker, supplier or LiveKit adapter. The separate inquiry and recovery
slice is now implemented. The [P1 guide](../projects/agent-continuity/README.md)
describes it.

## Run an isolated example

From the repository root with the documented Python environment:

```sh
.venv/bin/python -m continuity_lab demo
.venv/bin/python -m harness run BASE-01
```

| Task | Command | Notes |
| --- | --- | --- |
| Run the self-contained demo | `.venv/bin/python -m continuity_lab demo` | Uses a temporary database and removes temporary state on exit |
| Run the baseline acceptance case | `.venv/bin/python -m harness run BASE-01` | Separately checks actual fresh-process reads and concurrent intake |

The demo creates a temporary database, submits a request, reopens it, retries the
request and rejects a conflict.

## Keep state between commands

```sh
.venv/bin/python -m continuity_lab submit --key change-001 --booking DEMO-BK-001 --check-in 2030-12-10 --confirm
.venv/bin/python -m continuity_lab list
```

| Action | Result |
| --- | --- |
| Repeat the submission | The same task, with `created=false` |
| Keep the key and change the date | A conflict and exit code 2 |
| Start a new logical intent | Needs a new key |

Persistent state lives under the ignored `.local` directory.

## Read the code

Read the files in this order:

| Order | Path | Responsibility |
| --- | --- | --- |
| 1 | `projects/agent-continuity/python/src/continuity_lab/models.py` | Defines the confirmed investigation request and results |
| 2 | `projects/agent-continuity/python/src/continuity_lab/store.py` | Defines canonicalization and transaction boundaries |
| 3 | `tests/test_intake.py` | Checks conflicts, concurrency and fresh-process reads |
| 4 | `projects/agent-continuity/python/src/continuity_lab/__main__.py` | Provides the CLI adapter |

While reading, explain the failure windows before commit, after commit and before
the caller sees the result. A successful intake commit does not establish
execution or supplier outcome.

This original M1 CLI uses synchronous SQLite. The newer execution port has
bounded asynchronous offload, and conversational integration must use that
boundary.

## Next implementation boundary

The implemented inquiry slice adds explicit migration, persisted execution and a
read-only fake supplier. Its real process test crashes after inquiry success and
recovers the original inquiry without changing the booking.

The later multi-worker V1 gate requires PostgreSQL. P1 has since moved to
PostgreSQL and is implemented through schema v5. P1 V1 is qualified for the local
proof of concept, and the [P1 guide](../projects/agent-continuity/README.md)
records the current status. Follow the build plan and the
[P1 charter](projects/agent-continuity-scope.md) for acceptance criteria.
