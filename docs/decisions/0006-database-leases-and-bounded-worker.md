# Database leases and bounded worker execution

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Record the decision and rationale for database leases, admission bounds and bounded worker execution |
| Audience | Engineers changing P1 leases, admission bounds or worker deployment; coding agents |
| Scope | PostgreSQL v4 lease authority and time, migration and admission, external calls, worker ownership, shutdown and deployment; excludes production capacity and high availability |
| Owns | Lease, admission, worker ownership and shutdown choices and their rationale |
| Related | [Decision 0005](0005-effects-cancellation-and-outbox.md) · [Decision 0007](0007-native-conversation-and-local-media.md) · [Phase F work item](../work-items/0012-p1-phase-f-leases-and-deployment.md) · [Lease and worker guide](../leases-and-workers.md) |

## Context

Phase E established exact consent, retained possible-dispatch evidence and atomic
business completion under a cooperating single-worker slot. Phase F implements P1
implementation tasks P1-I19 through P1-I21: independent worker takeover, stale
local-write rejection and bounded product-worker orchestration. The
[P1 charter](../projects/agent-continuity-scope.md) retains the requirements. This
decision does not complete every related acceptance row or replace the case
authority.

## Decision

### Authority and time

Add explicit ACTIVE PostgreSQL v4 through the one-shot migration role. Retain all
original rows, immutable payloads and cutover receipts. The new `execution_limits`
singleton owns the admission, active, retention and lease bounds. The runtime has
SELECT only on that policy. `execution_leases` retains one task and scope binding,
the invocation owner, a monotonic epoch and database timestamps. A scope foreign
key uses the additive `tasks_identity_scope_key` without changing original task
columns or identities.

Sample `clock_timestamp()` after the admission and row locks. Worker wall time and
a cached `expires_at` value grant no write authority. Every v4 inquiry, effect and
delivery worker write validates the explicit task, scope, owner and epoch, and the
live database expiry, in its protected transaction.

| Lease operation | Rule |
| --- | --- |
| Reacquire the same live invocation | Replays its grant without extending expiry |
| Renew | Conditional; cannot resurrect an expired epoch |
| Release | Clears the owner and expiry and preserves the epoch |
| Acquire after release or expiry | Increments the retained epoch |

Public authenticated confirmation, signal, revision, cancellation and inspection
remain controller operations. They must work while a provider is slow and do not
require the worker's lease. A worker receives a fixed invocation grant and cannot
replace a stale token by reading the new owner's current epoch.

### Migration and admission

Upgrade only ACTIVE v3. Reject an unmanaged RUNNING inquiry before data definition
language (DDL) runs, because v4 blocks legacy worker transitions. The old v3 worker
must first reconcile and finish it. Managed running state retains a leased
recovery path. Existing v1 consent remains readable and replayable without
supplier-binding backfill, and is not selected as executable mutation work.
Startup performs no DDL or cutover.

The shared admission transaction serializes replay, pending capacity and lease
acquisition. Outstanding work includes accepted and running inquiries and
nonterminal managed workflows, including waiting workflows and committed intent.
New enrollment of a previously completed inquiry also observes that budget.
Retention counts every retained task identity, including imported M1 tasks without
execution rows.

An inquiry-complete continuation without a wait still expires under its original
business deadline. A leased expiry step releases its outstanding budget while
preserving the known inquiry result and performing no provider I/O. Known identity
and command replay remains available at capacity. New identities are rejected
without an acceptance receipt. No core record is evicted to make room.

The persisted defaults are:

| Limit | Persisted default |
| --- | --- |
| Outstanding workflows | 1,000 |
| Active leases | Four |
| Retained task identities | 10,000 |
| Lease duration | 30 seconds |

Bounds are configurable by an explicit typed policy at first upgrade. Repeated
upgrade with an explicit different policy conflicts rather than silently changing
active behavior.

### External calls and uncertainty

All supplier and receiver I/O stays outside PostgreSQL transactions. A stale
worker cannot commit local progress after takeover, but a database epoch cannot
cancel an already reserved or sent external request. Stable intents, effects and
events, and provider and receiver bindings, survive every epoch.

A cooperating supplier's lookup and deduplication permits reconciliation or a
same-effect retry. A noncooperating possible dispatch becomes uncertain and is
never blindly resent. A resumed old request may still reach the supplier. That is
why local fencing alone is insufficient. Known success and cancellation remain
separate observations. Receiver deduplication protects the same event when
delivery acknowledgement is lost.

### Worker ownership and shutdown

Select one due step from existing inquiry, wait, intent and delivery state, and
acquire its lease in the same short transaction. There is no additional durable
queue or unbounded in-memory pending buffer. One parent owns at most one step
subprocess. Waiting does not occupy a sleeping child or an active lease between
invocations.

Bound parent process occupancy with a monotonic deadline capped below the lease
policy duration, finite output and a finite consecutive-failure budget. This is not
proof that the remaining database lease is fresh after scheduling delays. The
child's guarded writes still consult database time.

On SIGTERM or SIGINT:

1. Stop new acquisition.
2. Drain within the remaining step and shutdown bound.
3. Kill and reap the owned process group before attempting lease release.

An unreaped child prevents a successful cleanup claim. Abrupt parent loss leaves
the retained lease to expire and durable effect evidence for the next owner.

### Deployment and observations

Use the opt-in `p1-workers` profile, explicit private supplier and sink fixtures
and a deliberately selected ACTIVE v4 schema. The worker receives runtime
credentials only. It cannot migrate, publish proposals or fabricate user
confirmation. Normal stop and start preserves `worker_data` and application
volumes. At the Phase F checkpoint, the browser and API exposed M1 intake (the
original SQLite confirmed-investigation intake) and transport diagnostics. The
[Phase G decision](0007-native-conversation-and-local-media.md) adds the separate
native business profile; the [P1 guide](../../projects/agent-continuity/README.md)
owns current capability status.

Expose readiness and bounded local metrics separately from business outcome.
Observe pending and active bounds, step occupancy, lease rejection and retained
queue ages using fixed dimensions. Process exit success does not imply a completed
booking, delivered event or human acknowledgement. No production capacity,
complete trace export, platform matrix, model quality or high-availability (HA)
claim follows.

## Validation

Validation requires the following evidence:

- Actual independent workers and server-time expiry, concurrent claim winners,
  lost acquisition acknowledgement, renewal, release and stale-epoch rejection,
  capacity replay, external-call pause and takeover, and useful recovered
  progress.
- Populated v3-to-v4 byte preservation, refusal and recovery for unmanaged running
  work, role, schema and policy drift, and actual migrator loss.
- Actual owned subprocess timeout, output and descendant cleanup and SIGTERM
  drain, followed by preserved-state migration, wait and effect recovery repeated
  with installed Docker workers.

Missing setup, required skips, zero tests and timeouts cannot pass. Final observed
results belong in the
[Phase F work item](../work-items/0012-p1-phase-f-leases-and-deployment.md).
