# Database leases and bounded worker execution

Status: Active
Last reviewed: 9 November 2026

## Context

Phase E established exact consent, retained possible-dispatch evidence and atomic
business completion under a cooperating single-worker slot. Phase F implements
P1-I19 through P1-I21: independent worker takeover, stale local-write rejection and
bounded product-worker orchestration. The [P1 charter](../projects/agent-continuity-scope.md)
retains the requirements; this decision does not complete every related acceptance
row or replace the case authority.

## Authority and time

Add explicit ACTIVE PostgreSQL v4 through the one-shot migration role. Retain all
original rows, immutable payloads and cutover receipts. The new execution_limits
singleton owns admission/active/retention/lease bounds. Runtime has SELECT only on
that policy. execution_leases retains one task/scope binding, invocation owner,
monotonic epoch and database timestamps. Release clears owner/expiry and preserves
the epoch. A scope foreign key uses the additive tasks_identity_scope_key without
changing original task columns or identities.

Sample clock_timestamp() after admission/row locks. Worker wall time and a cached
expires_at value grant no write authority. Every v4 inquiry/effect/delivery worker
write validates the explicit task/scope/owner/epoch and live database expiry in its
protected transaction. Reacquiring the same live invocation replays its grant
without extending expiry. Renewal is conditional and cannot resurrect an expired
epoch. Acquisition after release/expiry increments the retained epoch.

Public authenticated confirmation, signal, revision, cancellation and inspection
remain controller operations. They must work while a provider is slow and do not
require the worker's lease. A worker receives a fixed invocation grant and cannot
replace a stale token by reading the new owner's current epoch.

## Migration and admission

Upgrade only ACTIVE v3. Reject an unmanaged RUNNING inquiry before DDL because
v4 blocks legacy worker transitions. The old v3 worker must first reconcile and
finish it. Managed running state retains a leased recovery path. Existing v1
consent remains readable/replayable without supplier-binding backfill and is not
selected as executable mutation work. Startup performs no DDL or cutover.

The shared admission transaction serializes replay, pending capacity and lease
acquisition. Outstanding work includes accepted/running inquiries and nonterminal
managed workflows, including waiting and committed intent. New enrollment of a
previously completed inquiry also observes that budget. Retention counts every
retained task identity, including imported M1 tasks without execution rows.
An inquiry-complete continuation without a wait still expires under its original
business deadline. A leased expiry step releases its outstanding budget while
preserving the known inquiry result and performing no provider I/O. Known
identity/command replay remains available at capacity. New identities are
rejected without an acceptance receipt; no core record is evicted to make room.

The persisted defaults are 1,000 outstanding workflows, four active leases,
10,000 retained task identities and 30-second leases. Bounds are configurable by
an explicit typed policy at first upgrade. Repeated upgrade with an explicit
different policy conflicts rather than silently changing active behavior.

## External calls and uncertainty

All supplier/receiver I/O stays outside PostgreSQL transactions. A stale worker
cannot commit local progress after takeover, but a database epoch cannot cancel
an already reserved or sent external request. Stable intent/effect/event and
provider/receiver bindings survive every epoch.

A cooperating supplier's lookup and deduplication permits reconciliation or a
same-effect retry. A noncooperating possible dispatch becomes uncertain and is
never blindly resent. A resumed old request may still reach the supplier; that
is why local fencing alone is insufficient. Known success and cancellation
remain separate observations. Receiver deduplication protects the same event
when delivery acknowledgement is lost.

## Worker ownership and shutdown

Select one due step from existing inquiry/wait/intent/delivery state and acquire
its lease in the same short transaction. There is no additional durable queue or
unbounded in-memory pending buffer. One parent owns at most one step subprocess.
Waiting does not occupy a sleeping child or an active lease between invocations.

Bound parent process occupancy with a monotonic deadline capped below the lease
policy duration, finite output and a finite consecutive-failure budget. This is
not proof that the remaining database lease is fresh after scheduling delays.
The child's guarded writes still consult database time. On SIGTERM/SIGINT, stop
new acquisition, drain within the remaining step/shutdown bound, then kill and
reap the owned process group before attempting lease release. An unreaped child
prevents a successful cleanup claim. Abrupt parent loss leaves the retained
lease to expire and durable effect evidence for the next owner.

## Deployment and observations

Use the opt-in p1-workers profile, explicit private supplier/sink fixtures and a
deliberately selected ACTIVE v4 schema. The worker receives runtime credentials
only; it cannot migrate, publish proposals or fabricate user confirmation. Normal
stop/start preserves worker_data and application volumes. The current browser/API
remains M1 intake and transport diagnostics.

Expose readiness and bounded local metrics separately from business outcome.
Observe pending/active bounds, step occupancy, lease rejection and retained queue
ages using fixed dimensions. Process exit success does not imply a completed
booking, delivered event or human acknowledgement. No production capacity,
complete trace export, platform matrix, model quality or HA claim follows.

## Validation

Require actual independent workers and server-time expiry, concurrent claim
winners, lost acquisition acknowledgement, renewal/release/stale-epoch rejection,
capacity replay, external-call pause/takeover and useful recovered progress.
Require populated v3-to-v4 byte preservation, refusal/recovery for unmanaged
running work, role/schema/policy drift and actual migrator loss. Exercise actual
owned subprocess timeout/output/descendant cleanup and SIGTERM drain, then repeat
preserved-state migration/wait/effect recovery with installed Docker workers.
Missing setup, required skips, zero tests and timeouts cannot pass. Final observed
results belong in the [Phase F work item](../work-items/0012-p1-phase-f-leases-and-deployment.md).
