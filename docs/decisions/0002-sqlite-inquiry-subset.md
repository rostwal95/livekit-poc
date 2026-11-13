# Explicit SQLite inquiry execution and migration

Status: Active
Last reviewed: 9 November 2026

## Context

P1-I01 through P1-I04 must preserve accepted M1 requests while introducing the
first inquiry execution records. Investigation consent does not authorize a
booking mutation. A legacy intake row alone is not proof that a worker exists.

## Decision

Keep M1 tasks and its existing CLI/API compatible. An explicit quiesced migration
to SQLite schema version 1 creates executions and execution_attempts, preserving
task IDs and original canonical payload bytes and assigning one stable inquiry
effect ID. Serving execution operations check schema and open an existing file;
they never create/migrate schema. Backup uses SQLite's supported snapshot API.

The migration enrolls the queued requests in its snapshot. Later writes through
the original M1 API remain intake-only. Explicit ExecutionStore.submit with the
same scope/key/canonical request enrolls one missing execution under the original
task ID. created means a new logical request; enrolled means a new execution row.
Reads never enroll work. A worker selects only explicitly enrolled executions.

The first supported operation is booking.inquire. Immutable typed requests/results,
stable effect IDs, version-conditional transitions and bounded async offload are
included. Signals, durable waits, mutation, cancellation, retry policies, distributed
leases and delivery outbox remain unsupported. The attempt lifecycle is accepted
to running to succeeded/failed; Phase B now adds interrupted-attempt recovery under a cooperative POSIX worker
lock. The default manual attempt bound is eight (trusted configuration 1–100);
this is not an automatic retry/deadline policy or a distributed lease. Hard-link
aliases and unsafe lock files are rejected. Inquiry supplier state lives in a
separate database and declares read-only stable-key deduplication/lookup.
Database writes are short; external calls occur only after the effect/attempt
transaction commits. No arbitrary workflow code or coroutine checkpoint exists.

Scope comes from the trusted local caller; SQLite does not authenticate identities.
Unknown and other-scope reads have the same unavailable outcome. HTTP principal
enforcement remains a later application boundary. Failure codes are allowlisted;
raw SQL/provider messages are not stored or emitted in diagnostics.

## Failure schedule and consequences

For P1-01, a child acknowledges acceptance, then the harness terminates/reaps that
actual process; a new process reads the same request. For P1-02, park after commit
before library acknowledgement, terminate the child and replay the original key.
Concurrent identical submissions preserve one workflow/effect. P1-03 checks changed
payload conflict and independent scope. Precommit interruption leaves no accepted
workflow. Migration interruption rolls back and retained backup restores old data.

This deliberately supports the first SQLite inquiry proof, not another complete
distributed scheduler. After Phase B's real supplier crash/reconciliation proof,
introduce the early PostgreSQL adapter before richer lifecycle work. P1-19's
SQLite assertions do not replace later migration/backend/platform qualification.
Acceptance IDs and release scope remain in the [charter](../projects/agent-continuity-scope.md).
