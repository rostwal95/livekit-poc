# Explicit SQLite inquiry execution and migration

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Record the decision and rationale for the explicit SQLite inquiry execution subset and its migration |
| Audience | Engineers changing P1 SQLite execution, migration or enrollment; coding agents |
| Scope | M1 compatibility, SQLite schema version 1 migration, enrollment, the first inquiry operation, scope and diagnostics; excludes PostgreSQL and richer lifecycle work |
| Owns | SQLite inquiry subset and migration choices and their rationale |
| Related | [Decision 0001](0001-runtime-boundaries.md) · [Decision 0003](0003-postgres-cutover-and-scope.md) · [Phase A work item](../work-items/0007-p1-phase-a-execution-foundation.md) · [P1 charter](../projects/agent-continuity-scope.md) |

## Context

P1 implementation tasks P1-I01 through P1-I04 in the
[granular roadmap](../implementation-plan.md) must preserve requests accepted by
M1, the original SQLite confirmed-investigation intake, while introducing the
first inquiry execution records. Investigation consent does not authorize a
booking mutation. A legacy intake row alone is not proof that a worker exists.

## Decision

### Migration and enrollment

Keep M1 tasks and the existing M1 CLI and API compatible. An explicit quiesced
migration to SQLite schema version 1 creates `executions` and
`execution_attempts`. It preserves task IDs and original canonical payload bytes
and assigns one stable inquiry effect ID. Serving execution operations check the
schema and open an existing file. They never create or migrate the schema. Backup
uses SQLite's supported snapshot API.

The migration enrolls the queued requests in its snapshot. Later writes through
the original M1 API remain intake-only. An explicit `ExecutionStore.submit` with
the same scope, key and canonical request enrolls one missing execution under the
original task ID. Reads never enroll work. A worker selects only explicitly
enrolled executions.

| Term | Meaning |
| --- | --- |
| `created` | A new logical request |
| `enrolled` | A new execution row |

### Supported operation and lifecycle

| Area | In this subset |
| --- | --- |
| First supported operation | `booking.inquire` |
| Included | Immutable typed requests and results, stable effect IDs, version-conditional transitions and bounded async offload |
| Unsupported | Signals, durable waits, mutation, cancellation, retry policies, distributed leases and delivery outbox |

The attempt lifecycle is accepted, then running, then succeeded or failed. Phase B
now adds interrupted-attempt recovery under a cooperative POSIX worker lock. The
default manual attempt bound is eight, and trusted configuration can set it within
1–100. This is not an automatic retry or deadline policy, or a distributed lease.
Hard-link aliases and unsafe lock files are rejected.

Inquiry supplier state lives in a separate database and declares read-only
stable-key deduplication and lookup. Database writes are short. External calls
occur only after the effect and attempt transaction commits. No arbitrary workflow
code or coroutine checkpoint exists.

### Scope and diagnostics

Scope comes from the trusted local caller. SQLite does not authenticate
identities. Unknown and other-scope reads have the same unavailable outcome. HTTP
principal enforcement belongs to the separate application boundary. Failure codes are
allowlisted. Raw SQL and provider messages are not stored or emitted in
diagnostics.

## Consequences

This deliberately supports the first SQLite inquiry proof, not another complete
distributed scheduler. After Phase B's real supplier crash and reconciliation
proof, introduce the early PostgreSQL adapter before richer lifecycle work. The
SQLite assertions for P1-19 do not replace later migration, backend or platform
qualification. Acceptance IDs and release scope remain in the
[charter](../projects/agent-continuity-scope.md).

## Validation

The failure schedule for the acceptance requirements is:

| Requirement or scenario | Failure schedule |
| --- | --- |
| P1-01 | A child acknowledges acceptance, then the harness terminates and reaps that actual process; a new process reads the same request |
| P1-02 | Park the child after commit and before library acknowledgement, terminate it and replay the original key; concurrent identical submissions preserve one workflow and effect |
| P1-03 | Check changed-payload conflict and independent scope |
| Precommit interruption | Leaves no accepted workflow |
| Migration interruption | Rolls back, and the retained backup restores old data |
