# Leases and local worker operations

Status: Active
Last reviewed: 10 November 2026

## Scope

Phase F implements P1-I19 through P1-I21 on ACTIVE PostgreSQL v4: retained lease
epochs, conditional worker writes, bounded admission and a local product-worker
process. The [decision](decisions/0006-database-leases-and-bounded-worker.md) fixes
authority and shutdown semantics. The [phase work item](work-items/0012-p1-phase-f-leases-and-deployment.md)
records the completed final combined verification gate.
Existing registered runners retain their exact assertion scope. The harness
catalog owns current registrations; full product acceptance coverage remains pending.

Use the [case/continuation guide](case-and-continuation.md) and
[effects/completion guide](effects-and-completion.md) for exact consent, stable
identities, waits, cancellation and external truth. Worker deployment adds no
business authority by itself and requires no inference account. The G opt-in
conversation profile separately supplies the native consumer and case UI; original
M1 and transport diagnostics remain compatible independent routes.

## Explicit setup

From the repository root with the frozen interpreter and existing private settings:

```sh
.venv/bin/python local-setup/stack.py init
.venv/bin/python local-setup/stack.py start
.venv/bin/python local-setup/stack.py prepare-postgres
.venv/bin/python local-setup/stack.py migrate-postgres
make postgres-check
make phase-f-demo
```

migrate-postgres prepares a new STAGING v1 target; it does not activate/import a
source. The test lane/demo creates its own isolated active state. Do not run
upgrade or start-workers against that unfinished staging target. The demo preserves
existing application state and cleans only its owned fixtures/schema/containers.
Read its actual result artifact instead of inferring success from startup logs.

For a fresh persistent product-worker workspace, use the explicit
[owner preparation](../local-setup/README.md#first-persistent-p1-business-workspace)
after init/start/prepare-postgres, then initialize fixtures and start the worker:

```sh
.venv/bin/python local-setup/stack.py prepare-business
.venv/bin/python local-setup/stack.py init-worker-fixtures
.venv/bin/python local-setup/stack.py start-workers
.venv/bin/python local-setup/stack.py worker-status
```

prepare-business uses a private auxiliary empty SQLite source and retained backups
for actual controlled cutover and ordered ACTIVE v4 upgrades. It never reads or
quiesces the serving M1 database. Demos do not prepare this persistent target.
Retain the bootstrap folder and credentials for retry; conflicting/unowned staging
state is refused. An existing valid ACTIVE v4 target is checked without restaging
current work.

For an existing ACTIVE v1-v3 application schema with its own retained migration
history, preserve that source/backup history and apply the required versions in
order through the owner-only profile. P1_WORKER_SCHEMA selects the schema in
trusted local setup configuration; selection alone does not activate it:

```sh
.venv/bin/python local-setup/stack.py upgrade-postgres
.venv/bin/python local-setup/stack.py upgrade-effects
.venv/bin/python local-setup/stack.py upgrade-coordination
.venv/bin/python local-setup/stack.py upgrade-retry-pacing
.venv/bin/python local-setup/stack.py init-worker-fixtures
.venv/bin/python local-setup/stack.py start-workers
.venv/bin/python local-setup/stack.py worker-status
```

Keep local schema configuration consistent for the explicit owner operation and
the worker. P1_WORKER_SCOPE defaults to demo-traveller and P1_WORKER_SCHEMA defaults
to continuity. Trusted setup files are parsed as data; never source or print
private credentials. PostgreSQL administration uses only the migration principal.
Serving workers receive only their restricted runtime credential.

The optional p1-workers profile runs p1-worker against retained worker_data.
Fixture initialization explicitly creates private independent supplier/sink files
and reports their provider/receiver identities. Keep those files across restart:
exact proposals bind the provider, and delivery binds the receiver. Replacing a
fixture cannot silently redirect committed work. Initialization is not consent,
quote publication, workflow admission or PostgreSQL schema migration.

```sh
.venv/bin/python local-setup/stack.py stop-workers
.venv/bin/python local-setup/stack.py stop
```

Normal shutdown preserves named volumes. A destructive reset remains a separate
explicit operation. No migration, restart or ordinary check requires reset.

## Migration and compatibility

upgrade-coordination invokes postgres_cli upgrade-coordination and upgrade_v4.
Only ACTIVE v3 is eligible. Unmanaged RUNNING inquiries cause a pre-DDL refusal:
reconcile/finish them with the still-supported v3 inquiry worker, then upgrade.
Managed running attempts retain their original effect/attempt evidence for leased
recovery. Old install/v2/v3 upgrade retries validate v4 without downgrading it.

upgrade-retry-pacing invokes postgres_cli upgrade-retry-pacing and upgrade_v5 on
ACTIVE v4. It only adds the persisted mutation due time and indexes, so leased
work continues across it; older upgrades replay against v5 without changes. A
`pg_dump`/`psql` backup taken before the upgrade restores a valid v4 that can be
upgraded again.

All original rows, IDs, versioned quote/confirmation/intent JSON and historical
cutover receipts survive. V1 consent remains history/replay compatible and cannot
be filled from a current supplier revision. The selector excludes those legacy
mutation intents. New mutation requires a trusted complete v2 proposal and exact
confirmation through the existing case authority.

Runtime validates exact schema, grants and the policy singleton. It performs no
DDL, metadata writes, policy updates or core receipt deletion. Missing policy,
unsupported types/defaults/indexes/checks or excess grants fail closed. A repeated
upgrade never silently repairs drift or overwrites policy.

## Lease authority

| Field or operation | Meaning | Safety boundary |
| --- | --- | --- |
| task_id and scope_id | Original workflow and trusted configured account | Foreign-key binding and scoped lookup precede lease observations |
| owner_id | Fresh UUID for one invocation | Reuse only to replay a lost acquisition acknowledgement |
| epoch | Retained positive integer incremented after release/expiry | Never reset or recreate a task to obtain a new authority identity |
| claimed_at and renewed_at | Database timestamps | Finite UTC observations, not worker-provided lease clocks |
| expires_at | Current database-time write eligibility | Sample clock_timestamp after admission/row locks |
| Acquire same live owner | Return the original current grant | Does not extend expiry |
| Renew | Conditional same owner/epoch and unexpired lease | Cannot revive an expired grant |
| Release | Clear owner/expiry after the child is reaped | Retain the epoch and history |
| Takeover | Acquire an expired/released task with a higher epoch | Reject every later old-epoch inquiry/effect/delivery write |

Controllers can confirm, signal, revise, cancel and inspect while a worker waits
on a provider. Those authenticated operations do not require the worker lease.
The v4 worker's claim/reservation/finalization validates its explicit grant in the
same protected transaction as the write. A worker cannot replace its old token
with another owner's observed epoch. Legacy v1-v3 execution remains a supported
separate subset; bare legacy worker transitions reject on v4.

A database fence does not stop a reserved external call. Stable supplier effect
keys plus reliable lookup/deduplication permit reconciliation after takeover.
Without that cooperation, possible prior dispatch becomes uncertain with no new
apply. Known business truth, cancellation request, event transport and human
acknowledgement remain distinct. Keep provider and receiver targets unchanged.

## Due work, admission and retained data

The pull selector reads the existing authority: managed due inquiry/retry,
matching wait/signal or expired wait, executable committed mutation, and pending
or interrupted completion delivery. A completed inquiry with no armed wait also
becomes due when its original business deadline expires: the leased step closes
only continuation as failed/deadline_expired, preserves the known successful
inquiry result/attempt, performs no provider call and releases outstanding capacity.
Selection and lease acquisition share one
short admission transaction. External calls are outside it. No second broker or
recovering queue is introduced.

| Persisted policy | Default | Supported range and interpretation |
| --- | --- | --- |
| maximum_pending | 1,000 | 1–100,000 outstanding workflows, including active/waiting/committed managed work |
| maximum_active | 4 | 1–64 live leases across the schema, never greater than maximum_pending |
| maximum_records | 10,000 | At least maximum_pending and at most 1,000,000 retained task identities, including imported M1 tasks |
| lease_seconds | 30 s | 1–300 s database lease duration |

Rejected new work receives no durable acknowledgement. Original scoped replay,
reads and existing-identity enrollment remain available subject to the applicable
pending bound. Creating managed continuation from a completed inquiry also checks
pending admission; it cannot reopen capacity through another API. Terminal
business work leaves the outstanding count while retained task/effect/event and
receiver receipts remain inspectable. No receipt is evicted to admit new work.

First upgrade inserts the default or explicit typed CoordinationPolicy. Replaying
an already upgraded target with no policy validates it; an explicit mismatched
policy conflicts. Changing process-local constructor defaults cannot bypass the
persisted v4 policy. Production retention needs a separate replay-horizon and
tombstone design. These caps are local safety bounds, not throughput SLOs.

### Fresh schema catalog validation

Schema validation remains fresh on every connection and after the admission lock;
no cross-request or connection cache is introduced. One ordered catalog column
read replaces the separate reads for the 21 declared v4 tables, while each table
still receives every existing shape/type/nullability/default/collation check.
Restricted-role flags and inherited-membership checks share one current query.
ACL, index, constraint, ownership and safe metadata-read ordering predicates are
unchanged. This reduces query count without discarding security or schema checks.
Correctness and actual fault-window/resource measurements remain separate gates.

## Process lifetime and shutdown

The worker_cli run command repeatedly pulls at most one lease and owns one child
for a single inquiry/wait/mutation/delivery step. once performs at most one such
invocation; step is the trusted internal child command with a canonical bounded
claim. The child cannot supply a new request or user confirmation. Waiting work
stays durable without a sleeping process between invocations.

Default process policy is 1-second idle/error polling, a 15-second step ceiling capped at
half the configured lease duration, 5-second shutdown drain, 65,536 bytes of child output
and three consecutive failed steps. Supported output is bounded to 1 MiB and the
failure budget to 100. This monotonic parent occupancy limit does not prove that
a delayed invocation still owns a fresh lease; database checks remain decisive.

SIGTERM/SIGINT stops new claims, drains the current child within the earlier
step/shutdown bound, then kills and reaps the owned process group if needed.
Release follows confirmed reaping. An incomplete reap prevents clean completion.
Abrupt parent/container death retains possible-dispatch evidence and the lease
until expiry, allowing safe later recovery under the same task/effect/event.
Process exit zero means a process step ran; inspect durable records to determine
business outcome, remaining waits and delivery.

After an owned child step returns COMPLETED and releases its step resources,
the parent checks shutdown and selects the next eligible durable step immediately.
EMPTY/FAILED selections retain configured idle/error polling; this is not a retry
of a failed supplier request or a second process-memory queue. Child/lease/resource
ownership, failure limits and operation/shutdown deadlines remain unchanged.

### Cooperative quiescence and resume

SIGUSR1 requests a maintenance checkpoint on the continuous worker; it does not
stop a child or immediately acknowledge quiescence. The outer run loop sets actual
quiescent state after run_once has reaped the child, released its lease and
completed final queue SQL. While quiescent, the private five-field health record
remains fresh with ready=false and active_children=0. WorkerHealth.is_quiescent
also requires the owned private single-link file, bounded age and live PID.
A transient zero active-lease count alone does not establish this checkpoint.

SIGUSR2 releases maintenance quiescence. Existing WorkerHealth.ready may report
active_children=0 or 1 because eligible work can resume immediately. SIGTERM/SIGINT
remain sticky: a later resume request cannot clear shutdown. Maintenance signals
add no user/scope, confirmation or supplier authority and perform no schema work.

The isolated media helper records request ownership before sending either
potentially ambiguous maintenance/pause operation. It requires the checkpoint
and a separate active=0 snapshot before its declared OS pause; unpause and fresh
ready health settle resume uncertainty. The same 100-second arm/setup budget,
12-second close/resume ceiling and unchanged workload limits apply. Its 45-second
recovery clock starts before unpause/resume acknowledgement. Late successful
observations cannot bypass stop/deadline checks. Unknown cleanup remains visible
and non-passing rather than leaving a claimed clean quiesced worker.

## Observability and failure handling

Worker readiness is a private bounded recent parent observation. It is separate
from PostgreSQL availability, supplier outcome and completed workflow. Health and
metric snapshots use owned private regular files and atomic publication.
worker_cli health and worker_cli metrics read those observations; there is no
public product metrics endpoint or complete distributed trace pipeline.

Fixed worker metrics cover claim outcomes, step kind/outcome/count and occupancy,
active child count, lease-rejection codes and durable queue snapshots. Counts/ages
from the configured scope are compared with shared schema-wide policy limits.
Queue age measures outstanding durable work; expired-ownership age is an
operational recovery observation, not end-to-end completion latency. No task,
actor, provider, scope or arbitrary exception becomes a metric label.

Typed lease_required, lease_busy and lease_lost distinguish missing authority,
current contention and expired/superseded authority. Admission pressure rejects
new work without losing accepted state. Child timeout/output failure causes
bounded kill/reap and preserves database effect evidence. Storage/supplier errors
use safe fixed codes. Original messages, SQL, canonical claim payloads, credentials
and raw child output do not become public logs. Telemetry failures cannot change
business truth or replace original failures.

## Verification and next phase

Run offline/strict/style/documentation gates, actual PostgreSQL migration and
coordination suites, independent process pause/takeover, bounded process cleanup,
and installed Docker restart/recovery without resetting volumes. Verify both
safety and useful progress after pressure or failure. Required setup, skipped,
zero-test or timed-out scenarios cannot pass. Exact counts and observed modes
belong in the phase work item, not this operating contract.

Phase G implements P1-I22 through P1-I25 with its inspected local combined
gate recorded in the [Phase G work item](work-items/0013-p1-phase-g-conversation-and-showcase.md). The opt-in business profile
connects a scripted native AgentSession to managed PostgreSQL work, bounded
authenticated case projections and separate exact quote approval. Explicit
media End retires the room; a fresh native consumer reloads the same owned
task. This is actual local browser/native media, not physical microphone
capture, live-model quality, automatic network-loss recovery or remote CI proof.
The [H1 workload work item](work-items/0014-p1-phase-h-workload-baseline.md) records
the locally measured seeded inquiry baseline for S-I06 and the first P1-I27 slice,
including actual API/worker cgroup observations and independently reconciled
results. P1 V1 is qualified for the local POC using provider_real v2. local_real remains unqualified and complete P2/P3 acceptance remains pending.
The standalone API, isolated examples and independent review retain their own
source-bound artifact evidence in the package work item. Local_real
is implemented but actual engine/model/media qualification remains pending.
Hosted CI/publication are outside this local POC scope. Local worker checks
and this baseline do not establish high availability or production capacity.
