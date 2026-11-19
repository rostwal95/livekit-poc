# Leases and local worker operations

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Define the operating contract for P1 database leases and the local product worker on ACTIVE PostgreSQL v4 and the additive v5 upgrade |
| Audience | Engineers who operate the P1 worker or change its coordination code; coding agents |
| Scope | Lease authority, due work, worker lifetime, migration, setup, bounds, observability and checks; excludes consent and effect semantics |
| Owns | P1 lease authority, the persisted coordination policy and the local worker runtime contract |
| Related | [Lease decision](decisions/0006-database-leases-and-bounded-worker.md) · [Phase F work item](work-items/0012-p1-phase-f-leases-and-deployment.md) · [Case and continuation](case-and-continuation.md) · [Effects and completion](effects-and-completion.md) · [Local setup](../local-setup/README.md) |

## Overview

This guide is the operating contract for P1's database leases and local product
worker on ACTIVE PostgreSQL v4, including the additive v5 retry-pacing upgrade.

| Section | What it covers |
| --- | --- |
| [Lease authority](#lease-authority) | Lease fields, operations and states, controllers and external calls after takeover |
| [Due work and admission](#due-work-and-admission) | What the pull selector reads and deadline expiry after a completed inquiry |
| [Process lifetime and shutdown](#process-lifetime-and-shutdown) | Worker commands, shutdown, continuation, quiescence and resume |
| [Migration and compatibility](#migration-and-compatibility) | The v4 and v5 upgrades, preserved data and schema validation |
| [Setup and demonstration](#setup-and-demonstration) | Test lane and demo, persistent workspace, upgrades, configuration and stop |
| [Bounds and retention](#bounds-and-retention) | Coordination policy, behavior at capacity and process policy |
| [Observability and failure handling](#observability-and-failure-handling) | Health, metrics, lease errors and failures |
| [Verification and status](#verification-and-status) | Required checks, later phases and current status |

### Phase scope

Phase F of the [P1 implementation plan](implementation/p1-agent-continuity.md)
implements these tasks:

| Phase | Implementation tasks | PostgreSQL | What it adds |
| --- | --- | --- | --- |
| F | P1-I19 through P1-I21 | ACTIVE v4 | Retained lease epochs, conditional worker writes, bounded admission and a local product-worker process |

- The [decision](decisions/0006-database-leases-and-bounded-worker.md) fixes
  authority and shutdown semantics.
- The [phase work item](work-items/0012-p1-phase-f-leases-and-deployment.md)
  records the completed final combined verification gate.
- Existing registered runners retain their exact assertion scope. The harness
  catalog owns current registrations. P1's retained local qualification and its
  open post-v5 provider rerun are recorded in the
  [qualification guide](qualification-gates.md); full P2/P3 charter acceptance
  remains separate.

### Related guides and boundaries

| Document | Purpose |
| --- | --- |
| [Case and continuation guide](case-and-continuation.md) | Exact consent, case identity, waits and retry policy |
| [Effects and completion guide](effects-and-completion.md) | Stable effect identities, cancellation and external truth |
| [Local setup guide](../local-setup/README.md) | Stack lifecycle and the persistent business workspace preparation |

- Use the case/continuation guide and the effects/completion guide for exact
  consent, stable identities, waits, cancellation and external truth.
- Worker deployment adds no business authority by itself and requires no
  inference account.
- The Phase G opt-in conversation profile separately supplies the native consumer
  and case UI. The original M1 intake (the SQLite confirmed-investigation intake)
  and transport diagnostics remain compatible independent routes.

## Lease authority

In the tables, UUID means universally unique identifier.

### Lease fields

| Field | Meaning | Safety boundary |
| --- | --- | --- |
| `task_id` and `scope_id` | Original workflow and trusted configured account | Foreign-key binding and scoped lookup precede lease observations |
| `owner_id` | Fresh UUID for one invocation | Reuse only to replay a lost acquisition acknowledgement |
| `epoch` | Retained positive integer incremented after release/expiry | Never reset or recreate a task to obtain a new authority identity |
| `claimed_at` and `renewed_at` | Database timestamps | Finite UTC observations, not worker-provided lease clocks |
| `expires_at` | Current database-time write eligibility | Sample `clock_timestamp` after admission/row locks |

### Lease operations

| Operation | Effect | Safety boundary |
| --- | --- | --- |
| Acquire by the same live owner | Return the original current grant | Does not extend expiry |
| Renew | Conditional same owner/epoch and unexpired lease | Cannot revive an expired grant |
| Release | Clear owner/expiry after the child is reaped | Retain the epoch and history |
| Takeover | Acquire an expired/released task with a higher epoch | Reject every later old-epoch inquiry/effect/delivery write |

### Lease states

| State | Meaning | Next states |
| --- | --- | --- |
| Live | A current owner holds an unexpired grant by database time | Live after renewal or a same-owner acquire; released; expired |
| Released | Owner and expiry are cleared after the child is reaped; the epoch is retained | Live only through a takeover with a higher epoch |
| Expired | The stored expiry has passed by database time | Live only through a takeover with a higher epoch; renewal cannot revive it |

### Controllers and workers

Controllers can confirm, signal, revise, cancel and inspect while a worker waits
on a provider.

| Caller | Operations | Lease rule |
| --- | --- | --- |
| Authenticated controller | Confirm, signal, revise, cancel and inspect | Does not require the worker lease |
| v4 worker | Claim, reservation and finalization | Validates its explicit grant in the same protected transaction as the write |
| Legacy v1–v3 execution | Supported separate subset | Bare legacy worker transitions reject on v4 |

A worker cannot replace its old token with another owner's observed epoch.

### External calls after takeover

A database fence does not stop a reserved external call.

| Supplier cooperation | Outcome after takeover |
| --- | --- |
| Stable supplier effect keys plus reliable lookup and deduplication | Reconciliation is permitted |
| Without that cooperation | A possible prior dispatch becomes uncertain, with no new apply |

- Known business truth, cancellation request, event transport and human
  acknowledgement remain distinct.
- Keep provider and receiver targets unchanged.

## Due work and admission

### What the pull selector reads

The pull selector reads the existing authority for these kinds of due work:

| Work kind | Due work |
| --- | --- |
| Inquiry | A managed due inquiry or retry |
| Wait | A matching wait and signal, or an expired wait |
| Mutation | An executable committed mutation |
| Delivery | A pending or interrupted completion delivery |

Selection and lease acquisition share one short admission transaction. External
calls are outside it. No second broker or recovering queue is introduced.

### Deadline expiry after a completed inquiry

A completed inquiry with no armed wait also becomes due when its original
business deadline expires. The leased step then:

- closes only the continuation, as `failed`/`deadline_expired`;
- preserves the known successful inquiry result and attempt;
- performs no provider call;
- releases outstanding capacity.

[Bounds and retention](#bounds-and-retention) describes the admission caps and
behavior at capacity.

## Process lifetime and shutdown

### worker_cli commands

| Task | Command | Notes |
| --- | --- | --- |
| Run continuously | `worker_cli run` | Repeatedly pulls at most one lease and owns one child for a single inquiry, wait, mutation or delivery step |
| Run one invocation | `worker_cli once` | Performs at most one such invocation |
| Run one claimed step | `worker_cli step` | Trusted internal child command with a canonical bounded claim |
| Read health | `worker_cli health` | Reads the private health snapshot |
| Read metrics | `worker_cli metrics` | Reads the private metric snapshot |

The child cannot supply a new request or user confirmation. Waiting work stays
durable without a sleeping process between invocations. The
[default process policy](#default-process-policy) bounds polling, steps, drain,
output and failures.

### Shutdown signals

`SIGTERM` or `SIGINT` starts this sequence:

1. The worker stops new claims.
2. It drains the current child within the earlier of the step and shutdown
   bounds.
3. If needed, it kills and reaps the owned process group.
4. Lease release follows confirmed reaping.

An incomplete reap prevents clean completion. Abrupt parent or container death
retains possible-dispatch evidence and the lease until expiry. That allows safe
later recovery under the same task, effect and event.

Process exit zero means that a process step ran. Inspect durable records to
determine the business outcome, remaining waits and delivery.

### Continuing after a completed step

| Selection result | Parent behavior |
| --- | --- |
| `COMPLETED` | After the owned child step releases its step resources, the parent checks shutdown and selects the next eligible durable step immediately |
| `EMPTY` | Retains the configured idle polling |
| `FAILED` | Retains the configured error polling |

- This is not a retry of a failed supplier request or a second process-memory
  queue.
- Child, lease and resource ownership, failure limits, and operation and shutdown
  deadlines remain unchanged.

### Cooperative quiescence and resume

`SIGUSR1` requests a maintenance checkpoint on the continuous worker, and
`SIGUSR2` releases maintenance quiescence.

| State | Meaning | Next states |
| --- | --- | --- |
| Running | The continuous worker selects eligible durable steps | Quiescence requested after `SIGUSR1`; shutting down after `SIGTERM` or `SIGINT` |
| Quiescence requested | `SIGUSR1` does not stop a child or immediately acknowledge quiescence | Quiescent after the checkpoint |
| Quiescent | The outer run loop set actual quiescent state after `run_once` reaped the child, released its lease and completed final queue SQL | Running after `SIGUSR2`; shutting down after `SIGTERM` or `SIGINT` |
| Shutting down | `SIGTERM` or `SIGINT` started the [shutdown sequence](#shutdown-signals) | None; shutdown is sticky |

While quiescent:

- The private five-field health record remains fresh with `ready=false` and
  `active_children=0`.
- `WorkerHealth.is_quiescent` also requires the owned private single-link file,
  bounded age and a live process ID (PID).
- A transient zero active-lease count alone does not establish this checkpoint.

After `SIGUSR2`, existing `WorkerHealth.ready` may report `active_children=0` or
`1`, because eligible work can resume immediately.

- `SIGTERM` and `SIGINT` remain sticky: a later resume request cannot clear
  shutdown.
- Maintenance signals add no user or scope, confirmation or supplier authority,
  and perform no schema work.

#### Use by the isolated media helper

- The isolated media helper records request ownership before sending either
  potentially ambiguous maintenance or pause operation.
- It requires the checkpoint and a separate `active=0` snapshot before its
  declared operating system pause. Unpause and fresh ready health settle resume
  uncertainty.
- Late successful observations cannot bypass stop or deadline checks.
- Unknown cleanup remains visible and non-passing, rather than leaving a claimed
  clean quiesced worker.

Its time limits are:

| Limit | Value | Notes |
| --- | --- | --- |
| Arm and setup budget | 100 seconds | Unchanged |
| Close and resume ceiling | 12 seconds | Unchanged |
| Recovery clock | 45 seconds | Starts before the unpause and resume acknowledgement |

Workload limits are also unchanged.

## Migration and compatibility

### Upgrade v3 to v4 with upgrade-coordination

- `upgrade-coordination` invokes `postgres_cli upgrade-coordination` and
  `upgrade_v4`.
- Only ACTIVE v3 is eligible.
- Unmanaged RUNNING inquiries cause a refusal before any data definition language
  (DDL), that is, schema-changing SQL. Reconcile or finish them with the
  still-supported v3 inquiry worker, then upgrade.
- Managed running attempts retain their original effect and attempt evidence for
  leased recovery.
- Retries of the old install, v2 and v3 upgrades validate v4 without downgrading
  it.

### Upgrade v4 to v5 with upgrade-retry-pacing

- `upgrade-retry-pacing` invokes `postgres_cli upgrade-retry-pacing` and
  `upgrade_v5` on ACTIVE v4.
- It only adds the persisted mutation due time and indexes, so leased work
  continues across it.
- Older upgrades replay against v5 without changes.
- A `pg_dump`/`psql` backup taken before the upgrade restores a valid v4 that can
  be upgraded again.

### Preserved data and legacy consent

- All original rows, IDs, versioned quote, confirmation and intent JSON, and
  historical cutover receipts survive.
- V1 consent remains history and replay compatible. It cannot be filled from a
  current supplier revision. The selector excludes those legacy mutation intents.
- New mutation requires a trusted complete v2 proposal and exact confirmation
  through the existing case authority.

### Runtime schema validation

- Runtime validates the exact schema, grants and the policy singleton.
- It performs no DDL, metadata writes, policy updates or core receipt deletion.
- Missing policy, unsupported types, defaults, indexes or checks, and excess
  grants fail closed.
- A repeated upgrade never silently repairs drift or overwrites policy.

### Fresh schema catalog validation

Schema validation remains fresh on every connection and after the admission lock.
No cross-request or connection cache is introduced.

- One ordered catalog column read replaces the separate reads for the 21 declared
  v4 tables. Each table still receives every existing shape, type, nullability,
  default and collation check.
- Restricted-role flags and inherited-membership checks share one current query.
- Access control list (ACL), index, constraint, ownership and safe metadata-read
  ordering predicates are unchanged.

This reduces query count without discarding security or schema checks.
Correctness and actual fault-window and resource measurements remain separate
gates.

## Setup and demonstration

Run these commands from the repository root with the frozen interpreter and
existing private settings. In the tables, `stack.py` stands for
`.venv/bin/python local-setup/stack.py`.

| Task | Command | Notes |
| --- | --- | --- |
| Initialize, start and prepare roles | `stack.py init`, `stack.py start` and `stack.py prepare-postgres` | Ordinary local stack setup in the [local setup guide](../local-setup/README.md) |
| Prepare a staging target | `stack.py migrate-postgres` | Prepares a new STAGING v1 target; does not activate or import a source |
| Run the test lane | `make postgres-check` | Creates its own isolated active state |
| Run the Phase F demo | `make phase-f-demo` | Creates its own isolated active state |
| Prepare a persistent target | `stack.py prepare-business` | Explicit owner operation; see [What prepare-business does](#what-prepare-business-does) |
| Upgrade an existing schema | `stack.py upgrade-postgres`, `upgrade-effects`, `upgrade-coordination` and `upgrade-retry-pacing` | Owner-only, in order; the upgrade table below lists each source and result |
| Initialize fixtures | `stack.py init-worker-fixtures` | See [Worker profile and fixtures](#worker-profile-and-fixtures) |
| Start the worker | `stack.py start-workers` | Never against an unfinished staging target |
| Check the worker | `stack.py worker-status` | None |
| Stop the worker and the stack | `stack.py stop-workers` and `stack.py stop` | Normal shutdown preserves named volumes |

### Run the isolated test lane and demo

```sh
.venv/bin/python local-setup/stack.py init
.venv/bin/python local-setup/stack.py start
.venv/bin/python local-setup/stack.py prepare-postgres
.venv/bin/python local-setup/stack.py migrate-postgres
make postgres-check
make phase-f-demo
```

- Do not run an upgrade or `start-workers` against the unfinished staging target
  that `migrate-postgres` prepares.
- The demo preserves existing application state and cleans only its owned
  fixtures, schema and containers.
- Read its actual result artifact instead of inferring success from startup logs.

### Prepare a fresh persistent worker workspace

After `init`, `start` and `prepare-postgres`, use the explicit
[owner preparation](../local-setup/README.md#first-persistent-p1-business-workspace),
then initialize fixtures and start the worker:

```sh
.venv/bin/python local-setup/stack.py prepare-business
.venv/bin/python local-setup/stack.py init-worker-fixtures
.venv/bin/python local-setup/stack.py start-workers
.venv/bin/python local-setup/stack.py worker-status
```

### What prepare-business does

On a fresh target, `prepare-business` uses a private auxiliary empty SQLite
source and retained backups for an actual controlled cutover. It then applies the
ordered upgrades through v4 and the additive v5 step. It never reads or quiesces
the serving M1 database. Demonstrations do not prepare this persistent target.

`prepare-business` is not read-only when the target schema is ACTIVE v4: it runs
the owner-only v5 upgrade, without restaging current work. Its report names what
happened in its `schemaActivation` field:

| Target before preparation | What prepare-business does | `schemaActivation` |
| --- | --- | --- |
| Fresh target | Controlled cutover from the empty auxiliary source, then the ordered upgrades through v5 | `explicit_empty_bootstrap` |
| Existing valid ACTIVE v4 | Owner-only v5 upgrade; current work is not restaged | `owner_upgrade_v5` |
| Existing valid ACTIVE v5 | Read-only check | `read_only_ready` |

Retain the bootstrap folder and credentials for retry. Conflicting or unowned
staging state is refused.

### Upgrade an existing ACTIVE v1–v3 schema

An existing ACTIVE v1–v3 application schema has its own retained migration
history. Preserve that source and backup history, and apply the required versions
in order through the owner-only profile. `P1_WORKER_SCHEMA` selects the schema in
trusted local setup configuration; selection alone does not activate it.

```sh
.venv/bin/python local-setup/stack.py upgrade-postgres
.venv/bin/python local-setup/stack.py upgrade-effects
.venv/bin/python local-setup/stack.py upgrade-coordination
.venv/bin/python local-setup/stack.py upgrade-retry-pacing
.venv/bin/python local-setup/stack.py init-worker-fixtures
.venv/bin/python local-setup/stack.py start-workers
.venv/bin/python local-setup/stack.py worker-status
```

| Command | Eligible source | Result |
| --- | --- | --- |
| `stack.py upgrade-postgres` | ACTIVE v1 | v2 |
| `stack.py upgrade-effects` | ACTIVE v2 | v3 |
| `stack.py upgrade-coordination` | ACTIVE v3 | v4 |
| `stack.py upgrade-retry-pacing` | ACTIVE v4 | v5 (persisted mutation retry due time) |

[Migration and compatibility](#migration-and-compatibility) describes the v4 and
v5 steps.

### Configuration and credentials

| Option | Default | Description |
| --- | --- | --- |
| `P1_WORKER_SCOPE` | `demo-traveller` | Worker scope |
| `P1_WORKER_SCHEMA` | `continuity` | Schema selected in trusted local setup configuration |

- Keep local schema configuration consistent for the explicit owner operation
  and the worker.
- Trusted setup files are parsed as data. Never source or print private
  credentials.
- PostgreSQL administration uses only the migration principal. Serving workers
  receive only their restricted runtime credential.

### Worker profile and fixtures

The optional `p1-workers` profile runs `p1-worker` against the retained
`worker_data` volume.

- Fixture initialization explicitly creates private independent supplier and
  sink files and reports their provider and receiver identities.
- Keep those files across restart. Exact proposals bind the provider, and
  delivery binds the receiver.
- Replacing a fixture cannot silently redirect committed work.
- Initialization is not consent, quote publication, workflow admission or
  PostgreSQL schema migration.

### Stop the worker and the stack

```sh
.venv/bin/python local-setup/stack.py stop-workers
.venv/bin/python local-setup/stack.py stop
```

Normal shutdown preserves named volumes. A destructive reset remains a separate
explicit operation. No migration, restart or ordinary check requires reset.

## Bounds and retention

### Persisted coordination policy

| Option | Default | Allowed values | Description |
| --- | --- | --- | --- |
| `maximum_pending` | 1,000 | 1–100,000 | Outstanding workflows, including active/waiting/committed managed work |
| `maximum_active` | 4 | 1–64, never greater than `maximum_pending` | Live leases across the schema |
| `maximum_records` | 10,000 | At least `maximum_pending` and at most 1,000,000 | Retained task identities, including imported M1 tasks |
| `lease_seconds` | 30 s | 1–300 s | Database lease duration |

These caps are local safety bounds, not throughput service-level objectives
(SLOs).

### Behavior at capacity

- Rejected new work receives no durable acknowledgement.
- Original scoped replay, reads and existing-identity enrollment remain
  available, subject to the applicable pending bound.
- Creating managed continuation from a completed inquiry also checks pending
  admission. It cannot reopen capacity through another API.
- Terminal business work leaves the outstanding count, while retained task,
  effect and event records and receiver receipts remain inspectable.
- No receipt is evicted to admit new work.

### Policy installation and retention

- The first upgrade inserts the default or an explicit typed `CoordinationPolicy`.
- Replaying an already upgraded target with no policy validates it. An explicit
  mismatched policy conflicts.
- Changing process-local constructor defaults cannot bypass the persisted v4
  policy.
- Production retention needs a separate replay-horizon and tombstone design.

### Default process policy

| Limit | Value | Notes |
| --- | --- | --- |
| Idle and error polling | 1 second | Applies to `EMPTY` and `FAILED` selections |
| Step ceiling | 15 seconds | Capped at half the configured lease duration |
| Shutdown drain | 5 seconds | The earlier of the step and shutdown bounds applies |
| Child output | 65,536 bytes | Supported output is bounded to 1 MiB |
| Consecutive failed steps | Three | The supported failure budget is bounded to 100 |

The monotonic parent occupancy limit does not prove that a delayed invocation
still owns a fresh lease. Database checks remain decisive.

## Observability and failure handling

### Health and metrics

Worker readiness is a private, bounded, recent parent observation. It is separate
from PostgreSQL availability, supplier outcome and completed workflow.

- Health and metric snapshots use owned private regular files and atomic
  publication.
- `worker_cli health` and `worker_cli metrics` read those observations. There is
  no public product metrics endpoint or complete distributed trace pipeline.
- Fixed worker metrics cover claim outcomes, step kind, outcome, count and
  occupancy, active child count, lease-rejection codes and durable queue
  snapshots.
- Counts and ages from the configured scope are compared with shared schema-wide
  policy limits.
- Queue age measures outstanding durable work. Expired-ownership age is an
  operational recovery observation, not end-to-end completion latency.
- No task, actor, provider, scope or arbitrary exception becomes a metric label.

### Lease errors and failures

Typed lease errors distinguish these conditions:

| Code | Meaning |
| --- | --- |
| `lease_required` | Missing authority |
| `lease_busy` | Current contention |
| `lease_lost` | Expired or superseded authority |

- Admission pressure rejects new work without losing accepted state.
- Child timeout or output failure causes a bounded kill and reap and preserves
  database effect evidence.
- Storage and supplier errors use safe fixed codes.
- Original messages, SQL, canonical claim payloads, credentials and raw child
  output do not become public logs.
- Telemetry failures cannot change business truth or replace original failures.

## Verification and status

### Checks and evidence

Run these gates:

- the offline, strict, style and documentation gates;
- the actual PostgreSQL migration and coordination suites;
- independent process pause and takeover;
- bounded process cleanup;
- installed Docker restart and recovery without resetting volumes.

Verify both safety and useful progress after pressure or failure. Required setup,
skipped, zero-test or timed-out scenarios cannot pass. Exact counts and observed
modes belong in the phase work item, not this operating contract.

### Phase and release status

| Step | Outcome | Gate |
| --- | --- | --- |
| Phase F, P1-I19 through P1-I21 | Retained lease epochs, conditional worker writes, bounded admission and the local product worker | Final combined verification gate completed in the [phase work item](work-items/0012-p1-phase-f-leases-and-deployment.md) |
| Phase G, P1-I22 through P1-I25 | Opt-in business profile with a scripted native `AgentSession` | Inspected local combined gate recorded in the [Phase G work item](work-items/0013-p1-phase-g-conversation-and-showcase.md) |
| H1, the inquiry workload slice of Phase H | Locally measured seeded inquiry baseline for S-I06 (the shared seeded-workload task) and the first P1-I27 slice | Recorded in the [H1 workload work item](work-items/0014-p1-phase-h-workload-baseline.md) |
| Standalone package | Standalone API, isolated examples and independent review | Own source-bound artifact evidence in the [package work item](work-items/0016-p1-standalone-package.md) |

In the Phase G profile:

- The opt-in business profile connects a scripted native `AgentSession` to
  managed PostgreSQL work, bounded authenticated case projections and separate
  exact quote approval.
- Explicit media End retires the room. A fresh native consumer reloads the same
  owned task.
- This is actual local browser and native media. It is not physical microphone
  capture, live-model quality, automatic network-loss recovery or remote
  continuous integration (CI) proof.

The H1 baseline includes actual API and worker control group (cgroup)
observations and independently reconciled results.

| Capability | Status | Evidence |
| --- | --- | --- |
| P1 V1 (the fixed first-version scope) for the local proof of concept (POC) | Qualified | Using `provider_real` v2; see the [Phase H release handoff](work-items/0019-p1-phase-h-release-qualification.md) |
| `local_real` profile | Not qualified | Implemented, but actual engine, model and media qualification remains pending |

- Complete P2/P3 acceptance remains pending.
- Hosted CI and publication are outside this local POC scope.
- Local worker checks and this baseline do not establish high availability or
  production capacity.
