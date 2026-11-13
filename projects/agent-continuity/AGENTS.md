# Agent Continuity Lab coding instructions

Status: Active
Last reviewed: 11 November 2026

## Read first

Follow the [root instructions](../../AGENTS.md), then read this project's
[README.md](README.md), [Design.md](Design.md),
[V1 charter](../../docs/projects/agent-continuity-scope.md) and the
[shared validation plan](../../docs/validation-plan.md). Inspect affected source
and tests before editing.

Read the [granular implementation plan](../../docs/implementation/p1-agent-continuity.md)
for phase gates, task prerequisites and failure evidence. These task IDs are not
product acceptance IDs; the charter remains authoritative.

## Owned paths

Canonical source is `projects/agent-continuity/python/src/continuity_lab`, retaining
the `continuity_lab` import name, including execution_models.py, execution.py,
async_execution.py, migrations.py and execution_cli.py; PostgreSQL settings/store/
migrations/CLI, source_transfer/cutover, transfer/codec/worker-lock helpers and
authorization.py. Phase D adds case_models/postgres_case, retry_policy/
lifecycle_models/postgres_lifecycle/managed_inquiry_worker, case_service/
case_telemetry, postgres_schema_v2 and bounded_io/postgres_unit_of_work. Phase E
adds effect_models/postgres_effects, mutation_supplier/mutation_worker,
completion_sink/outbox_delivery and postgres_schema_v3. Phase F adds
lease_models/postgres_leases/postgres_work, worker_runtime/worker_cli and
postgres_schema_v4. Baseline tests are
`tests/test_intake.py`; execution, async, migration and actual accepting-process
checks are the corresponding tests/test_execution*.py, test_async_execution.py
and test_migrations.py. Future reusable Python code belongs under `projects/agent-continuity/python`, with project tests under `projects/agent-continuity/tests`. Do not relocate working code merely to fill this directory.

The charter owns scope and acceptance IDs. Root design owns shared authority and
ports. Keep unrelated projects and user files intact.

Read [case/continuation operations](../../docs/case-and-continuation.md) before
changing authority, wait or retry semantics. Read
[effects and completion](../../docs/effects-and-completion.md) before changing
mutation, cancellation, provider/receiver target binding or outbox behavior. Read
[leases and workers](../../docs/leases-and-workers.md) before changing v4
admission, server-time authority, due selection or child ownership. Case revision/confirmation and
wait consumption must share the same protected transaction; preserve direct
confirmation and waiting-state coherence.

## Development rules

The additive public work_api/work_admin profile owns opaque immutable read-only
accepted bytes, exact typed tenant/account/key identity and requested cancellation.
Install explicitly in a marked p1_work_ schema with its owner; runtime validates
catalog/grants and performs no DDL. Preserve bytes/digest/original deadline and
replay before caps/expiry. WorkClient.scope is verified before P3 submits. No
body scope, proposed wire attempt or accepted status is action/execution authority.
Keep the profile separate from booking v4 selectors without duplicating an accepted
logical delegation into a P3 ledger. Test actual PostgreSQL uncertainty, caps,
credential scope, catalog side effects and telemetry-failure useful progression.

The separate execution_api is usable only after the explicit owner-only
upgrade_work_schema_v2. Preserve v1 acceptance/read/cancel APIs on all known
versions; runtime never upgrades, refreshes drift or changes booking v4/SQLite.
Issue returns an immutable grant plus created; only a newly created grant can
cause invocation. Replayed/uncertain commands reconcile through find_issue and
never automatically invoke again. Unknown transport keeps its lease until expiry.
Every write shares admission locking and samples database time after locks.
The scope, original accepted bytes, owner, attempt ID, command, number, epoch and
lease must match the stored grant before a result can be recorded. Keep at most
three immutable results per work and one per issued attempt. Stale/cancelled/late
results remain historical; eligible_at_commit denotes only P1 lease/time/cancel
eligibility, never semantic validity, current-case applicability or action consent.
A later cancellation does not erase a known eligible result. Lease caps bound
logical authority, not physical remote computation. The caller owns HTTP resources;
no implicit retry, renewal, remote-stop claim, worker or delivery is introduced.


Version3 adds result-delivery bindings/possible markers/known receipts and guarded
case-action receipts. Use only the explicit v2-to-v3 owner upgrade. Keep one of
each per original work and retain core identities; no outbox worker or retry loop
is introduced. Delivery prepare binds the stored eligible result and exact
receiver/recipient before I/O; begin.created is the only fresh accept permission.
Replayed possible work looks up its original receiver; absent evidence is unknown.
Known exact receipts survive later cancellation/deadline without claiming human ACK.
The private receiver requires explicit initialization, finite scope/recipient
bindings, stable receiver identity and bounded actual SQLite I/O; no runtime DDL.

Version4 adds a generic result-only feed through result_feed_api and explicit
owner upgrade_work_schema_v4. Preserve source UUID/event IDs on repeat/reopen;
backfill existing results once as adopted_history, preserving original bytes/times.
Append a live event and scoped contiguous sequence in the result transaction under
existing admission locking. No global pre-commit sequence or source ACK is allowed.
Cursors bind source/scope and reject ahead-of-head; page≤100, event retention ≤
accepted cap×attempt cap (at most 30000), signed-int64 sequence types. Serving
performs no DDL or repair. Old APIs and delivery/action support v4. P3 alone owns
derived immutable as-of metadata; later work/case changes do not refresh it.
Restored-branch source incarnation rotation remains unqualified.

Guarded action lock order is booking admission, work admission, case/control.
Revalidate work schema/counters, exact latest eligible result, cancellation and DB
deadline before the existing case authority commits current exact confirmation.
The guarded receipt and case intent share one transaction; no supplier I/O occurs
inside it. A receipt replay returns original truth before later eligibility;
changed result/quote/actor/schema cannot retarget it. P1 does not parse P3 result
semantics or manufacture user confirmation. The new public case_control_api is
separate trusted controller composition; do not expose it to native model tools.
Keep all old booking/source modules and existing public methods compatible.

- Preserve investigation-only consent in M1. A booking mutation requires separate explicit confirmation of the exact quote and case revision.
- Use `TaskExecutionPort`, `CaseAuthorityPort` and supplier/event interfaces. Keep one owner for current case facts and committed action intents; P1 must not import P2 or P3 application implementations.
- Keep persisted workflow state, attempts, waits, effects and cancellation intent distinguishable. Database fencing does not itself fence external supplier calls.
- Keep blocking I/O off the conversational event loop and external calls outside database locks. Bound concurrency, pending work, retries and shutdown.
- Use independent processes, persisted supplier state, controlled clocks and failpoints for recovery evidence. An in-memory fake or reopened connection is insufficient for a process-crash claim.
- Preserve the established PLAN-02 SQLite M1/inquiry compatibility subset and its independent crash proof. The PostgreSQL cutover and Phase F lease/multi-worker gates are recorded evidence; keep future lifecycle changes compatible with those boundaries.
- Preserve quote v2 case/provider/expected supplier revision binding. Legacy v1
  read/replay remains valid but cannot authorize new mutation. Never infer missing
  proposal authority from mutable later supplier state or worker configuration.
- Distinguish CLAIMED before reservation from possible prior dispatch using
  dispatch_count, including on recovered claims. Attempt generation is not a
  distributed lease epoch. V4 separately requires an explicit invocation lease
  validated in the same transaction as each worker write. Validate active-attempt
  intent/number before finishing.
- Keep cancellation receipts separate from effect truth. Zero prior reservations
  can prove prevention; possible dispatch is best effort until reliable result or
  uncertainty. Known success survives cancellation and deadline expiry.
- Commit final outcome, stable completion event and initial delivery together.
  Bind the receiver before first I/O and preserve the same receiver/event across
  lost acknowledgement. Delivery failure cannot alter business outcome or claim
  human acknowledgement.
- Retain core effect/attempt/cancel/outcome/event and supplier/receiver deduplication
  receipts. Only the receiver's separate diagnostic projection may be pruned.
  Test late original replay after projection pruning and at capacity.
- Sample database clock_timestamp after locks for lease authority. Retain epochs
  after release/expiry and reject stale owner/task/scope/epoch writes. Cached
  expiry, worker wall time and a new owner's observed token grant no authority.
- Keep authenticated controller confirmation/signal/cancel/inspection separate
  from worker claims. Do not block user cancellation on an external call or use
  lease ownership as consent. External requests still need provider cooperation
  or explicit uncertainty; database fencing alone cannot stop a reserved call.
- Enforce persisted v4 limits across admission, completed-inquiry management and
  active claims. Include durable waits in outstanding work and all retained task
  identities in record capacity. Preserve existing replay/reads at capacity.
- Pull one due step without a second durable queue. Own at most one child per
  parent, cap monotonic occupancy/output/failures, stop new acquisition on signal,
  and kill/reap the owned group before lease release. Never report clean shutdown
  when child cleanup is incomplete. Keep raw child output out of public logs.
- Upgrade only ACTIVE v3 with no unmanaged RUNNING inquiry. Refuse before DDL so
  original v3 reconciliation remains possible. Runtime and the opt-in worker
  profile never install schema or initialize consent implicitly.
- Define replay horizons/tombstones before cleanup. Preserve the standalone src-layout package and typed api/postgres_api/testing exports. Native services consume the locked workspace member; installed examples must run outside checkout import paths with declared extras. Keep Python support at 3.14 unless an intentional support-policy change is qualified.

Trusted inference modes are exactly scripted (default), local_real and
provider_real. Preserve the selected mode through mint, native readiness, numeric
usage and sanitized traces. A configured badge or process health is not actual
inference/media qualification. No silent provider/model fallback exists. All modes
preserve bound tools and separate exact human confirmation. Read the
[provider operations guide](../../docs/provider-demo.md) before changing provider composition.
Offline validation must not read private key values or invoke providers. Never
source, print, copy or include local-setup/.env.providers in reports or build
contexts. Only the explicit native provider runtime receives the three keys.

Inference configuration belongs to native composition, not the reusable case authority. Preserve the same typed interfaces and effect/confirmation invariants for all modes; provider SDKs add no mutation or scope authority.

## Verification

Use stable P1 acceptance IDs in the change plan and evidence. Run the
relevant implemented scenario, focused structural checks and full fast lane before
handoff. Commands in the README run from the repository root. Planned, skipped,
missing and timed-out checks cannot count as passes. New behavioral runners need
real assertions and useful failure artifacts; no hidden service setup is allowed.

Run make postgres-check after explicit local init/start/prepare-postgres/
migrate-postgres for storage, migration or authorization changes. The Phase E
lane owns isolated ACTIVE v3 test schemas; upgrade a deliberately selected ACTIVE
application schema with upgrade-postgres then upgrade-effects. Never activate an
unfinished import implicitly. Run make phase-e-demo for runtime-container
supplier/receiver success-before-ack recovery evidence. The tests under
tests/postgres are a separate real-database lane, not skipped fast tests. Keep
P1_MIGRATION_* out of runtime services; schema/ACL drift must fail closed.

For Phase F run the actual v4 upgrade/coordination lane and make phase-f-demo.
Use independent processes and DB-server expiry for takeover assertions, including
an old process paused before external I/O and resumed after takeover. Exercise
normal progress, global active/pending/retention limits, known replay at capacity,
SIGTERM drain, timeout/output/descendant cleanup and preserved-volume restart.
Retain negative failures and useful recovered progression; a process exit or
health file alone does not prove business completion. The combined phase gate
remains in its work item, distinct from complete charter/media/release claims.

For inquiry workload changes, read the [H1 work item](../../docs/work-items/0014-p1-phase-h-workload-baseline.md) and preserve its frozen declaration, source-bound installed execution, independent result reconciliation and owned cleanup. Keep actual observations distinct from declared totals, polling latency from supplier completion, and cgroup accounted memory from RSS. Preserve the separately passed H2 reliability and I26 host/Linux artifact/API/genuine-consumer gates. Remaining media and real-inference/release assertions stay separate.

## Handoff

Record the behavior changed, acceptance IDs, interface/migration decisions, exact
commands, observed results and remaining work. Update implementation status only
when evidence supports it. Keep offline, local-media and live-model results
separate, and record assistance and personal contributions accurately.
