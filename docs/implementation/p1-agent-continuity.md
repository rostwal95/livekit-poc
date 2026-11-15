# P1 Agent Continuity Lab implementation plan

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Break P1, the Agent Continuity Lab, into bounded implementation tasks with prerequisites, estimates and evidence |
| Audience | Engineers and coding agents who choose the next P1 task, check its prerequisites or record its evidence |
| Scope | Phases P1-A to P1-H, tasks P1-I01 to P1-I28 and their acceptance traceability; excludes P1 requirements and shared tasks |
| Owns | P1 task decomposition, phase gates, effort sizing and per-task handoff |
| Related | [P1 charter](../projects/agent-continuity-scope.md) · [Granular roadmap](../implementation-plan.md) · [Build plan](../build-plan.md) · [P1 project instructions](../../projects/agent-continuity/AGENTS.md) |

## Purpose and authority

This plan breaks P1, the Agent Continuity Lab, into bounded implementation tasks.
It is for engineers and coding agents who choose the next P1 task, check its
prerequisites or record its evidence. P1 is a Python library for explicitly
persisted business work that survives conversation and process termination.

### Contents

| Section | What it covers |
| --- | --- |
| [Current status](#current-status) | What is qualified and what remains open |
| [Starting point and dependencies](#starting-point-and-dependencies) | The foundation to reuse and the shared prerequisites |
| [Planning and completion rules](#planning-and-completion-rules) | Task sizing, engineering gates and what a task can claim |
| [Phases and tasks](#phases-and-tasks) | Phases P1-A through P1-H, each with its status, entry conditions, task table, task details, exit criteria and UI and signal requirements |
| [Acceptance traceability](#acceptance-traceability) | The tasks that supply each acceptance ID |
| [Demonstrations and signals](#demonstrations-and-signals) | Where the demonstration and signal requirements live |
| [Commands and task handoff](#commands-and-task-handoff) | Existing commands and the per-task handoff packet |

### Authority

| Document | Owns |
| --- | --- |
| [P1 charter](../projects/agent-continuity-scope.md) | The 20 P1 acceptance requirements |
| [Build plan](../build-plan.md) | The PLAN-01 through PLAN-22 sequencing |
| [Granular roadmap](../implementation-plan.md) | The shared tasks and the cross-project execution gates |
| [Project instructions](../../projects/agent-continuity/AGENTS.md) | P1 agent workflow and implementation boundaries |
| [Shared design](../../Design.md) | Shared data flow, state authority, interfaces and failure boundaries |
| [Validation plan](../validation-plan.md) | Test lanes, required fault scenarios, benchmarks and evidence |
| [Observability contract](../observability.md) | Signals, safe errors, cardinality and operational evidence |
| [Demo strategy](../demo-plan.md) | Capability demonstrations and honest observable UI transitions |
| [Runtime decision](../decisions/0001-runtime-boundaries.md) | Runtime, package and persistence boundaries |

- This plan decomposes the build plan's sequence into bounded implementation
  tasks. It adds no acceptance IDs and no second workflow platform.
- This plan is subordinate to the granular roadmap.
- Read this plan together with the project instructions, the shared design, the
  validation plan, the observability contract, the demo strategy and the runtime
  decision.

### How to read the task tables

Each phase lists its tasks in one table with these columns:

| Column | Meaning |
| --- | --- |
| Task | The implementation task ID |
| PLAN | The build-plan work package that the task implements |
| Prerequisites | The tasks, shared tasks (S-I IDs) or setup that must exist first |
| Acceptance | The acceptance IDs that the task contributes assertions to |
| Estimate | The planning estimate in engineering hours |
| Status | The recorded implementation status |
| Evidence | The work item that records the gate results |

The [granular roadmap](../implementation-plan.md) defines the shared S-I tasks.
The task details below each table give the concrete deliverable and the required
failure assertion for each task.

## Current status

P1 V1, the fixed version 1 scope of P1, is implemented and locally qualified for
the local proof of concept (POC). Qualification used the selected provider_real v2
profile, which runs real hosted provider inference. Phases P1-A through P1-H are
implemented with retained acceptance evidence. The
[release work item](../work-items/0019-p1-phase-h-release-qualification.md) owns
the exact results and limits.

| Phase | Tasks | Task status | Evidence |
| --- | --- | --- | --- |
| [P1-A](#phase-p1-a-schema-safe-execution-foundation) | P1-I01 to P1-I04 | Completed; Phase A gate passed | [0007](../work-items/0007-p1-phase-a-execution-foundation.md) |
| [P1-B](#phase-p1-b-one-independent-inquiry-and-its-crash-window) | P1-I05 to P1-I07 | Completed; Phase B gate passed | [0008](../work-items/0008-p1-phase-b-inquiry-recovery.md) |
| [P1-C](#phase-p1-c-early-postgresql-adapter-and-trusted-scope) | P1-I08 to P1-I10 | Completed; historical checkpoint | [0009](../work-items/0009-p1-phase-c-postgres-cutover.md) |
| [P1-D](#phase-p1-d-case-authority-exact-consent-and-durable-waiting) | P1-I11 to P1-I14 | Completed on PostgreSQL v2 | [0010](../work-items/0010-p1-phase-d-authority-and-waits.md) |
| [P1-E](#phase-p1-e-effects-cancellation-and-durable-completion) | P1-I15 to P1-I18 | Completed; final combined phase gate passed | [0011](../work-items/0011-p1-phase-e-effects-and-completion.md) |
| [P1-F](#phase-p1-f-multi-worker-coordination-and-bounded-deployment) | P1-I19 to P1-I21 | Completed; combined phase gate passed | [0012](../work-items/0012-p1-phase-f-leases-and-deployment.md) |
| [P1-G](#phase-p1-g-conversational-adapter-visible-continuity-and-traces) | P1-I22 to P1-I25 | Completed; local combined gate passed | [0013](../work-items/0013-p1-phase-g-conversation-and-showcase.md) |
| [P1-H](#phase-p1-h-reusable-artifact-and-release-proof) | P1-I26 to P1-I28 | Completed for provider_real v2; local_real unqualified | [0014](../work-items/0014-p1-phase-h-workload-baseline.md), [0015](../work-items/0015-p1-reliability-workloads.md), [0016](../work-items/0016-p1-standalone-package.md), [0018](../work-items/0018-p1-provider-demo.md), [0019](../work-items/0019-p1-phase-h-release-qualification.md) |

### Current local P1 qualification

| Gate or evidence | Recorded outcome | Record |
| --- | --- | --- |
| Final 20-case index, the current P1-18, P1-14 and P1-20 gates, the full H2 workload, PostgreSQL, installed host and Linux artifacts and the shared quality gates | Passed with independent reviews | [0019](../work-items/0019-p1-phase-h-release-qualification.md) |
| P1-01 through P1-20 rows | All twenty have registered runners; the retained reports passed | [0019](../work-items/0019-p1-phase-h-release-qualification.md) |
| P1-01 through P1-05 SQLite evidence | Retain SQLite acceptance and recovery evidence | [0007](../work-items/0007-p1-phase-a-execution-foundation.md), [0008](../work-items/0008-p1-phase-b-inquiry-recovery.md) |
| P1-I26's typed library, independent public-API review and installed host and Linux consumers | Passed | [0016](../work-items/0016-p1-standalone-package.md), [0019](../work-items/0019-p1-phase-h-release-qualification.md) |
| P1-I27's historical H1 inquiry baseline and current complete H2 workload (restart, slow dependency, saturation and shutdown) | Retain distinct source scopes | [0014](../work-items/0014-p1-phase-h-workload-baseline.md), [0015](../work-items/0015-p1-reliability-workloads.md) |
| Fresh registered P1-18 and P1-14 runs and the selected provider_real v2 P1-20 run | Passed, including both actual provider browser cases | [0019](../work-items/0019-p1-phase-h-release-qualification.md) |
| Final packaging, shared quality and the independent 20-case index | Passed | [0019](../work-items/0019-p1-phase-h-release-qualification.md) |

Historical checkpoints retain their original scope.

### Implemented capabilities

| Capability | Status | Evidence |
| --- | --- | --- |
| Standalone backend: exact quote confirmation, waits, retry and deadline policy, supplier mutation and reconciliation, cancellation and durable completion and outbox state | Qualified: Phase P1-E final verification passed | [0011](../work-items/0011-p1-phase-e-effects-and-completion.md) |
| Phase P1-F database-time leases, epoch guards, persisted admission and bounded pull-worker deployment | Qualified: the final combined gate passed | [0012](../work-items/0012-p1-phase-f-leases-and-deployment.md) |
| Phase P1-G scoped conversation tools, current-case UI, actual scripted local browser and native audio, and inspected raw Jaeger v3 traces | Qualified: the local combined gate passed | [0013](../work-items/0013-p1-phase-g-conversation-and-showcase.md) |

### Open work

- The optional local_real profile, which uses prepared local inference engines,
  remains unqualified under its original bounds.
- Physical microphone quality and automatic network-loss media recovery remain
  unqualified.
- Complete P2/P3 acceptance remains pending.
- Remote and hosted continuous integration (CI) and publication are outside this
  local POC scope.
- The shared foundation qualification ledger must distinguish these gaps.

## Starting point and dependencies

### Existing foundation

The following capabilities are already implemented. Reuse them rather than
rebuilding them as new milestones:

- confirmed-investigation intake in `continuity_lab`;
- SQLite scoped replay and conflict detection;
- bounded intake capacity;
- API error and metric handling;
- the local Docker stack;
- the diagnostic software development kit (SDK) agent;
- browser text and reconnect;
- the visible intake, replay and conflict proof.

This plan calls the existing confirmed-investigation intake M1.

### Dependencies

The [granular roadmap](../implementation-plan.md) defines shared tasks once. P1
uses two of them. Some tasks also depend on qualification or setup rather than
on another task.

| Dependency | What must exist | Needed by |
| --- | --- | --- |
| S-I05 shared task | Idempotent migration-credential, configuration and profile upgrades and the one-shot PostgreSQL migration principal, which S-I05 owns | P1-I08 |
| S-I06 shared task | The small seeded workload and evidence envelope, which S-I06 owns | P1-I27; H1 established the first S-I06/P1-I27 local inquiry baseline |
| Installed-SDK qualification | The installed SDK is qualified | P1-I22 |
| Permitted browser media | Browser media permission is granted | P1-I25 |
| Configured real inference | Real inference is configured | P1-I28 |

## Planning and completion rules

### Task IDs and estimates

- Task IDs P1-I01 through P1-I28 identify implementation work, not requirements.
- Effort ranges cover prepared implementation, focused tests and a concise
  handoff. They are planning estimates, not elapsed-time promises.
- Most tasks are two to four hours. If the first coherent assertion will exceed
  that budget, split the task at a named persistence or interface boundary and
  update the central plan.
- Keep one primary implementation task active.
- Add integration and review contingency when scheduling. Do not count learning or
  investigation as free capacity.

### Engineering gates for every task

Select the applicable engineering gates from the
[validation authority](../validation-plan.md) for every task. Record:

- Given/When/Then safety and useful-progress criteria;
- safe producer log, error and metric assertions;
- actual test-mode evidence.

Python work follows the [engineering guide](../python-engineering.md). A changed
Design.md uses the [standard template](../design-template.md). These are task
completion rules, not evidence that planned acceptance scenarios already pass.

### What a task can claim

- A task listed against an acceptance ID contributes assertions. It does not pass
  the entire ID until every required assertion and runtime lane for that row
  executes successfully.
- Offline schema and worker tasks need not wait for model credentials or
  microphone permission. The corresponding media or release gate remains
  incomplete until its evidence exists.

## Phases and tasks

### Phase P1-A: schema-safe execution foundation

**Phase status:** P1-I01 through P1-I04 passed the
[Phase A gate](../work-items/0007-p1-phase-a-execution-foundation.md).

**Entry:**

- The current baseline and shared fast checks pass.
- The qualification ledger records the pending media and platform checks.
- No new worker is enabled against old data.

The primary paths are `continuity_lab`, its tests and small harness extensions.
Keep the existing CLI imports and M1 investigation-only behavior stable.

| Task | PLAN | Prerequisites | Acceptance | Estimate | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P1-I01 | PLAN-01/02 | Shared foundation ledger and passing baseline | P1-07, P1-19 preparation | 1–2h | Completed | [0007](../work-items/0007-p1-phase-a-execution-foundation.md) |
| P1-I02 | PLAN-01/03 | P1-I01 | P1-04/05/19 harness | 2–3h | Completed | [0007](../work-items/0007-p1-phase-a-execution-foundation.md) |
| P1-I03 | PLAN-02 | P1-I01, P1-I02 | P1-01, P1-19 | 3–4h | Completed | [0007](../work-items/0007-p1-phase-a-execution-foundation.md) |
| P1-I04 | PLAN-02 | P1-I03 | P1-01/02/03 | 3–4h | Completed | [0007](../work-items/0007-p1-phase-a-execution-foundation.md) |

**Task details:**

- **P1-I01**
  - Deliverable: write the execution work item, transition sketch, SQLite
    supported subset and exact crash timeline. Decide the public error and
    disclosure policy.
  - Required failure assertion: investigation consent cannot authorize mutation.
    Unsupported SQLite lifecycle operations cannot silently downgrade behavior.
- **P1-I02**
  - Deliverable: add owned-process control, named failpoints, a deterministic
    clock and a pre-upgrade SQLite fixture to the existing harness.
  - Required failure assertion: a child that was not terminated, zero tests, a
    timeout or a required skip cannot produce a passing crash scenario.
- **P1-I03**
  - Deliverable: introduce a versioned one-shot additive or new-table migration
    and typed execution and attempt records, without altering original task
    identities or canonical requests.
  - Required failure assertion: an interrupted or invalid migration preserves
    readable old data or a demonstrated restore path. Old queued requests remain
    valid.
- **P1-I04**
  - Deliverable: implement the smallest allowlisted execution port, durable
    transition writes and a persisted inquiry effect identity before dispatch.
    Retain bounded async storage offload.
  - Required failure assertion: concurrent identical submissions, and identical
    submissions repeated after a lost acknowledgement, yield one identity. A
    changed payload conflicts. The same key in a different scope remains
    independent.

**Migration rules:**

- Serving processes check their supported schema version. They do not silently
  perform new migrations on a request or at startup.
- Run the versioned SQLite migration as an explicit controlled operation with its
  writes quiesced. It still needs backup and rollback evidence, even though the
  file owner supplies its permissions.
- Use the separate one-shot migration principal for later PostgreSQL schema
  changes (data definition language, DDL).

**Exit:**

- An existing M1 database upgrades safely.
- Intake survives termination of its accepting process.
- Replay and conflict assertions observe persisted state.

There is still no supplier booking mutation and no claim of coroutine
checkpointing.

**UI and signals:**

- Preserve the current intake proof.
- New execution-state labels remain unavailable until a real worker produces them.
- Record the schema version, the acceptance and transition outcome, and storage
  failures.
- Keep request and case IDs in safe logs or traces rather than in metric labels.

### Phase P1-B: one independent inquiry and its crash window

**Phase status:** P1-I05 through P1-I07 passed the
[Phase B gate](../work-items/0008-p1-phase-b-inquiry-recovery.md).

**Entry:**

- The Phase P1-A migration and identity contract pass.
- A separate fake-supplier store must outlive the worker.
- The worker runs as an independent process, not an in-process coroutine
  pretending to restart.

| Task | PLAN | Prerequisites | Acceptance | Estimate | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P1-I05 | PLAN-03 | P1-I04 | P1-04/05 fixtures | 2–3h | Completed | [0008](../work-items/0008-p1-phase-b-inquiry-recovery.md) |
| P1-I06 | PLAN-03 | P1-I04, P1-I05 | P1-04 | 2–4h | Completed | [0008](../work-items/0008-p1-phase-b-inquiry-recovery.md) |
| P1-I07 | PLAN-03 | P1-I02, P1-I06 | P1-05 | 3–4h | Completed | [0008](../work-items/0008-p1-phase-b-inquiry-recovery.md) |

**Task details:**

- **P1-I05**
  - Deliverable: implement persisted synthetic bookings and inquiries, and a
    supplier port that declares stable-key deduplication and lookup capabilities.
  - Required failure assertion: reopening or terminating the worker does not reset
    supplier inquiry evidence. An inquiry never changes booking state.
- **P1-I06**
  - Deliverable: execute one accepted inquiry through the allowlisted worker.
    Persist the attempt, the result and bounded history.
  - Required failure assertion: no external call occurs inside a database lock. A
    definitive supplier rejection produces a typed outcome, and the ordinary
    successful path still progresses.
- **P1-I07**
  - Deliverable: stop the worker after supplier success and before local
    acknowledgement. Launch a new process and reconcile by the original effect
    identity.
  - Required failure assertion: one logical inquiry is observed in the supplier
    store, the recovered result is persisted and booking state is unchanged.

**Exit:**

- Run the normal inquiry and the controlled crash and recovery without P2, P3,
  LiveKit or paid inference.
- Inspect both independent stores and the actual process termination.
- Register P1-04 and P1-05 only when those assertions execute.

**UI and signals:**

- Extend the operator inspection view with observed execution attempts and
  inquiry results.
- A harness-confirmed injected crash is an observation. It must not become a
  fabricated business failure.
- Show recovery pending separately from the final inquiry outcome.
- Add attempt, inquiry dispatch, reconciliation and completion observations, with
  queue and recovery duration measurements.

### Phase P1-C: early PostgreSQL adapter and trusted scope

**Phase status:** this is a historical checkpoint. P1-I08, P1-I09, P1-I10 and shared
task S-I05 were implemented. The
[Phase C work item](../work-items/0009-p1-phase-c-postgres-cutover.md) owns that
original gate and its evidence. At that checkpoint:

- cancel and signal were unsupported after scope checking, and P1-17 was
  incomplete;
- PostgreSQL coordination used one cooperating session slot, without distributed
  lease or epoch claims.

The later phase checkpoints and [Current status](#current-status) own the current
lifecycle, lease and scope qualification.

**Entry:**

- Preserve the completed SQLite inquiry crash proof.
- Introduce PostgreSQL before implementing the richer lifecycle, using the already
  provisioned local service.

This is the early adapter pass of PLAN-08, not its multi-worker exit.

| Task | PLAN | Prerequisites | Acceptance | Estimate | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P1-I08 | PLAN-08 early | P1-I07 and shared S-I05 migration setup | P1-01/02/03/05/19 | 3–6h | Completed | [0009](../work-items/0009-p1-phase-c-postgres-cutover.md) |
| P1-I09 | PLAN-08 early | P1-I08 | P1-01/02/03/04/05/19 | 3–4h | Completed | [0009](../work-items/0009-p1-phase-c-postgres-cutover.md) |
| P1-I10 | PLAN-04/08 | P1-I09 | P1-17 | 2–3h | Completed | [0009](../work-items/0009-p1-phase-c-postgres-cutover.md) |

**Task details:**

- **P1-I08**
  - Deliverable: apply PostgreSQL schema and versioning, and a repeatable
    quiesced import of M1 and inquiry state through the shared one-shot migration
    principal. Preserve requests, attempts, effect keys, known outcomes and
    timestamps.
  - Required failure assertion: an interrupted or repeated cutover preserves
    accepted state. Concurrent new intake is rejected before acknowledgement. No
    inquiry is recreated under a new effect identity.
- **P1-I09**
  - Deliverable: implement the single-worker PostgreSQL store and execution
    adapter. Run the common contract on its supported operations and on the
    declared SQLite subset.
  - Required failure assertion: unsupported SQLite operations fail explicitly.
    Backend adapters agree on canonical replay and conflict and on accepted-state
    reads.
- **P1-I10**
  - Deliverable: derive the trusted synthetic actor and scope at the application
    boundary. Enforce scope-qualified get, signal, cancel and history access.
  - Required failure assertion: a forged scope label or another principal cannot
    inspect, advance or cancel the original workflow under the chosen disclosure
    policy.
  - Scope note: P1-I10 establishes the shared scope guard and tests the operations
    already supported. Signal and cancel remain explicitly unsupported until
    P1-I13 and P1-I17. Repeat the scope negatives against those real operations
    when they are implemented.

**Cutover procedure:** use an explicit quiesced cutover.

1. Stop new acceptance.
2. Drain already admitted writes.
3. Preserve a source backup.
4. Import and verify the original state.
5. Switch the adapter only after validation.
6. Re-enable admission.

An interrupted cutover must resume from its recorded checkpoint or from the
preserved source.

**Migration and credential rules:**

- Shared task S-I05 owns idempotent migration-credential, configuration and
  profile upgrades.
- PostgreSQL migrations run under a one-shot migration principal. Serving API
  processes and workers retain restricted runtime roles and must not receive the
  bootstrap administrator secret.
- Verify the schema grants required for data manipulation (DML), and assert that
  runtime roles cannot create a schema.
- Retain existing credentials and volume-owner labels. A normal upgrade cannot
  require a destructive volume reset.
- Do not create a SQLite/PostgreSQL dual-write path or an undocumented
  live-migration promise.
- Supplier evidence stays in its independent fixture store. No cross-store atomic
  transaction is claimed.

**Exit:**

- The first inquiry and recovery contract runs on PostgreSQL, and supported SQLite
  operations remain compatible.
- Continue full business execution on PostgreSQL.
- Do not duplicate a complete distributed scheduler on SQLite, and do not claim
  lease or fencing correctness yet.

**UI and signals:**

- Expose the actual backend and migration state in operator inspection, not in
  the business consent prompt.
- A migration mismatch blocks the new worker rather than making an old task appear
  newly accepted.
- Preserve the existing safe HTTP error envelope. Add backend and schema
  dimensions only from a fixed vocabulary.

### Phase P1-D: case authority, exact consent and durable waiting

**Phase status:** all four tasks are implemented on PostgreSQL v2. The
[Phase D work item](../work-items/0010-p1-phase-d-authority-and-waits.md) owns the
observed gates. The [case and continuation guide](../case-and-continuation.md)
owns the working APIs and demo. At the Phase D checkpoint, supplier apply,
cancellation, leases and event delivery were later work. Phases P1-E and P1-F
subsequently implemented those boundaries.

**Entry:**

- The PostgreSQL adapter is available.
- Trusted scope is explicit.
- The case and intent transaction design is reviewed before mutation code is
  introduced.

Proposed application ports and operations remain those in the P1 charter and the
shared design. They are not existing LiveKit SDK methods.

| Task | PLAN | Prerequisites | Acceptance | Estimate | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P1-I11 | PLAN-04 | P1-I10 | P1-07/17 and retention | 2–4h | Completed | [0010](../work-items/0010-p1-phase-d-authority-and-waits.md) |
| P1-I12 | PLAN-04 | P1-I11 | P1-06/07/13 | 3–4h | Completed | [0010](../work-items/0010-p1-phase-d-authority-and-waits.md) |
| P1-I13 | PLAN-05 | P1-I09, P1-I11 | P1-10/11 | 3–4h | Completed | [0010](../work-items/0010-p1-phase-d-authority-and-waits.md) |
| P1-I14 | PLAN-06 | P1-I13 | P1-12 | 3–4h | Completed | [0010](../work-items/0010-p1-phase-d-authority-and-waits.md) |

**Task details:**

- **P1-I11**
  - Deliverable: add case revision, immutable quote and confirmation types and
    canonical snapshots. Decide replay horizons and tombstones before any cleanup.
  - Required failure assertion: a model summary cannot upgrade missing or altered
    fields, an invalid actor or an expired quote into confirmation. History
    pruning cannot erase effect protection.
- **P1-I12**
  - Deliverable: atomically validate the actor, the current revision, the quote
    dates, amount, currency and expiry, and the matching confirmation. Then commit
    one immutable action intent and its dispatch event.
  - Required failure assertion: each mismatch rejects before supplier invocation.
    Revision and confirmation races have a documented transaction winner and no
    partially accepted intent.
- **P1-I13**
  - Deliverable: implement persisted waits, absolute business deadlines and a
    typed deduplicated signal inbox. Correlate early and late callbacks.
  - Required failure assertion: the same payload deduplicates. An altered replay
    conflicts. An unrelated or stale confirmation cannot advance work. No
    permanently sleeping task retains a wait.
- **P1-I14**
  - Deliverable: implement failure classification, eligible retry time, bounded
    attempts and backoff, and fake-clock deadline evaluation.
  - Required failure assertion: permanent failure does not retry. Exhausted or
    expired work stops. Ambiguous external outcomes cannot be converted into blind
    transient retries.

**Exit:**

- Valid inquiry results can wait across process loss and resume under the same
  identity.
- A quote is visible separately from an exact explicit confirmation.
- The final P1-10 gate also requires the container repetition in P1-I21.

**UI and signals:**

- Show the current case revision, quote identity, exact proposed change, expiry
  and confirmation status.
- Confirmation sends a real command against that snapshot. A stale response causes
  reinspection rather than silent resubmission.
- Show the waiting reason and the persisted deadline.
- Record rejected confirmation and revision outcomes and wait and signal outcomes,
  with no raw booking or transcript values in metrics.

### Phase P1-E: effects, cancellation and durable completion

**Phase status:** P1-I15 through P1-I18 are implemented and passed the final combined
phase gate recorded in the
[Phase E work item](../work-items/0011-p1-phase-e-effects-and-completion.md). This
does not register additional product acceptance runners or complete the media and
release lanes.

**Entry:**

- Atomic action-intent commitment and signal and deadline behavior pass.
- Only explicitly committed intents may invoke the fake apply capability.

| Task | PLAN | Prerequisites | Acceptance | Estimate | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P1-I15 | PLAN-07 | P1-I12, P1-I14 | P1-06/07 | 2–3h | Completed | [0011](../work-items/0011-p1-phase-e-effects-and-completion.md) |
| P1-I16 | PLAN-07 | P1-I15 | P1-08/09 | 3–4h | Completed | [0011](../work-items/0011-p1-phase-e-effects-and-completion.md) |
| P1-I17 | PLAN-06 | P1-I12, P1-I15 | P1-13/14 | 3–4h | Completed | [0011](../work-items/0011-p1-phase-e-effects-and-completion.md) |
| P1-I18 | PLAN-07 | P1-I16, P1-I17 | P1-03/11/16 and retention | 3–4h | Completed | [0011](../work-items/0011-p1-phase-e-effects-and-completion.md) |

**Task details:**

- **P1-I15**
  - Deliverable: apply exactly the confirmed fake booking revision through a
    persisted stable effect key and a cooperating supplier adapter.
  - Required failure assertion: normal authorized work progresses. An absent,
    stale or mismatched confirmation causes zero supplier apply calls.
- **P1-I16**
  - Deliverable: repeat the crash after effect success and before local
    acknowledgement, this time for a mutation. Add a noncooperating supplier
    variant.
  - Required failure assertion: a new process reconciles a cooperating effect
    without an incorrect duplicate. Insufficient deduplication or lookup evidence
    persists uncertainty and performs no unsafe resend.
- **P1-I17**
  - Deliverable: add idempotent cancellation commands, a separate cancellation
    disposition and barrier-controlled confirmation and cancellation races.
  - Required failure assertion: precommit cancellation prevents apply. Postcommit
    cancellation cannot claim reversal. An altered cancellation replay conflicts.
- **P1-I18**
  - Deliverable: commit the final outcome and a stable completion-event intent
    atomically. Deliver the outbox with bounded retry to a cooperating standalone
    sink.
  - Required failure assertion: a crash before delivery retains the event.
    Repeated delivery retains one logical ID. A late replay after diagnostic
    pruning remains deduplicated or is explicitly rejected under the retention
    policy.

**Exit:**

- The single-worker PostgreSQL lifecycle covers confirmed mutation, cooperative
  reconciliation, explicit uncertainty and durable completion delivery.
- P1-14's actual speech-interruption repetition remains for P1-I25.
- State outcome, cancellation disposition, event delivery and user acknowledgement
  stay separate.

**UI and signals:**

- Show intent commitment, external evidence, result and delivery as distinct
  observations.
- An uncertain outcome requires reconciliation. It must not render as success or
  as definitive failure.
- Cancellation displays requested, observed and too-late or best-effort facts from
  actual responses.
- Completion delivery can fail while business execution remains successful.
- Add fixed outcome and error counts from the authenticated service, and safe
  effect, worker and delivery events.

This Phase E checkpoint did not include exported conversation traces or a business
UI. Phase P1-G later adds the scoped native consumer, the managed case projection
and the filtered application and SDK trace path. The
[observability contract](../observability.md) defines its actual span coverage.
The original M1 remains a separate compatible route.

### Phase P1-F: multi-worker coordination and bounded deployment

**Phase status:** P1-I19 through P1-I21 are implemented and passed the
[combined phase gate](../work-items/0012-p1-phase-f-leases-and-deployment.md).

- Phase E's 440 offline and 186 PostgreSQL tests remain historical evidence.
- PostgreSQL schema v4 adds explicit server-time task leases and retained
  execution epochs. Attempt generation tokens remain a different identity.
- This implementation status implies no complete acceptance runner and no media or
  platform release gate.

**Entry:**

- Single-worker business semantics pass on PostgreSQL.
- Extend coordination without changing intent commitment or the supplier's
  declared effect contract.

| Task | PLAN | Prerequisites | Acceptance | Estimate | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P1-I19 | PLAN-08 coordination | P1-I18 | P1-15 | 3–4h | Completed | [0012](../work-items/0012-p1-phase-f-leases-and-deployment.md) |
| P1-I20 | PLAN-08 coordination | P1-I16, P1-I19 | P1-09/15 | 3–4h | Completed | [0012](../work-items/0012-p1-phase-f-leases-and-deployment.md) |
| P1-I21 | PLAN-06/08/09 | P1-I18, P1-I20 | P1-10/17/18/19 | 3–4h | Completed | [0012](../work-items/0012-p1-phase-f-leases-and-deployment.md) |

**Task details:**

- **P1-I19**
  - Deliverable: add short claim and renewal transactions, lease expiry and
    conditional writes under an execution epoch.
  - Required failure assertion: two independent workers cannot own the current
    write authority. An old worker resumed after takeover cannot commit a stale
    update.
- **P1-I20**
  - Deliverable: pause an old worker at the external-call boundary and resume it
    after lease expiry.
  - Required failure assertion: supplier cooperation prevents an incorrect
    duplicate effect, or uncertainty is exposed. A database fence alone never
    passes external-effect safety.
- **P1-I21**
  - Deliverable: enforce pending and active admission and graceful shutdown. Add
    the actual P1 worker to local orchestration, and repeat the migration, wait
    and recovery checks with preserved volumes.
  - Required failure assertion: rejected work is never acknowledged. Accepted
    work remains readable at capacity. Restart retains waits and effects. Shutdown
    leaves no orphan local tasks. Reset is never used as restart.

**Implemented contract:**

- PostgreSQL v4 worker writes for inquiries, effects and the outbox guard an
  explicit scope, task, owner and epoch in their existing transaction.
- A paused old process cannot commit after takeover, but it may still send
  externally. Cooperating stable effects or honest uncertainty remain required.
- Public authenticated case, read and controller commands retain their own
  authority.
- The pending, active and retained-identity policy is persisted and finite.
- Uncertainty without a final inquiry business outcome remains outstanding for
  manual review.
- Replay and inspection work at capacity.

**Worker deployment profile:**

- The `p1-workers` profile is opt-in. It uses restricted runtime credentials,
  checks the existing ACTIVE v4 and fixture state, and supervises one bounded
  POSIX child per parent.
- Shutdown stops acquisition, drains within 5 s by default, then kills and reaps
  the child before release.
- Normal restart reuses named volumes.
- Upgrade refuses unmanaged RUNNING v3 work until it finishes under the legacy
  contract.
- The final gate must repeat actual container restart, waits and effect recovery
  without reset.

**Exit:**

- PostgreSQL multi-worker and stale-effect tests pass using independent processes.
- Actual container restart preserves accepted state.
- The SQLite supported subset remains tested, without implied full scheduler
  parity.
- Core deployment commands enter the quickstart only after implementation and
  verification.

**UI and signals:**

- Show the current attempt and epoch in secondary operator details, not as
  business authorization.
- Explain pending work, admission rejection and recovery lag.
- Retain useful progress for admitted work during saturation.
- Track queue age, inflight work and admission, lease rejection and recovery lag
  with bounded labels.

### Phase P1-G: conversational adapter, visible continuity and traces

**Phase status:** P1-I22 through P1-I25 and their local combined gate are recorded in the
[Phase G work item](../work-items/0013-p1-phase-g-conversation-and-showcase.md).
The gate uses:

- explicit bundled-WAV WebAudio input;
- native scripted speech-to-text (STT), large language model (LLM) and
  pulse-code modulation (PCM) audio output;
- real browser and native WebRTC;
- held dependencies;
- fresh-consumer status;
- exact UI confirmation;
- inspected raw Jaeger v3 trace data.

Before controls or speech, the worker awaits the public RoomIO readiness barrier
and publishes `continuity.session_ready=true`. `session_host=False` disables
alternate SDK session ingress.

Hardware microphone quality, human hearing acknowledgement and automatic
network-loss recovery remain unqualified. Selected provider_real v2 live inference
passed under Phase P1-H. Remote CI is outside the local POC scope. The task
requirements below remain unchanged.

**Entry:**

- Durable ports and case authority are stable.
- The current diagnostic worker remains a transport tool. Introduce the
  conversational consumer deliberately.
- Reuse native AgentSession, tools, handoffs and suitable AgentTask/TaskGroup
  behavior.

| Task | PLAN | Prerequisites | Acceptance | Estimate | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P1-I22 | PLAN-10/11 | P1-I21 and installed-SDK qualification | P1-14/20 preparation | 3–4h | Completed | [0013](../work-items/0013-p1-phase-g-conversation-and-showcase.md) |
| P1-I23 | PLAN-11 | P1-I18, P1-I22 | P1-17/20 UI | 2–4h | Completed | [0013](../work-items/0013-p1-phase-g-conversation-and-showcase.md) |
| P1-I24 | PLAN-11 | P1-I22 | P1-18/20 operational evidence | 2–4h | Completed | [0013](../work-items/0013-p1-phase-g-conversation-and-showcase.md) |
| P1-I25 | PLAN-11 | P1-I22, P1-I23, P1-I24 and permitted browser media | P1-14/20 | 3–4h | Completed | [0013](../work-items/0013-p1-phase-g-conversation-and-showcase.md) |

**Task details:**

- **P1-I22**
  - Deliverable: connect native conversational submit, get and cancel tools and a
    separate authenticated controller signal port. Return durable acceptance
    without awaiting supplier completion.
  - Required failure assertion: slow storage or a slow supplier does not block the
    event loop or turn a model assertion into confirmation. Session closure does
    not cancel accepted business work.
- **P1-I23**
  - Deliverable: extend the bounded GET/cursor case projection and the showcase
    from persisted events: request, quote, exact confirmation, attempts, outcome
    and delivery. Retain the small diagnostic console.
  - Required failure assertion: reconnect loads the current scoped case. Missing
    or late observations stay unknown. UI timers cannot invent progress or
    completion.
- **P1-I24**
  - Deliverable: add SDK-native metrics and session reports, bounded application
    OpenTelemetry Protocol (OTLP) spans and the P1 metric vocabulary. Exercise
    typed provider, storage and exporter errors.
  - Required failure assertion: exporter failure cannot block conversation,
    acceptance or shutdown. IDs and payloads never become metric labels or unsafe
    logs.
- **P1-I25**
  - Deliverable: run actual local browser voice with scripted inference and audio,
    a held supplier and slow persistence. Interrupt, end and reconnect the
    session.
  - Required failure assertion: business work remains inspectable and completes
    independently. Interruption alone does not cancel. Exact mutation confirmation
    remains required. Useful responsiveness is measured.

**Exit:**

- The local voice and tool path supplies P1-20's local-media assertions with
  actual audio and browser observations. P1-I27 and P1-I28 supply the separately
  measured and live evidence.
- Permission denial or an unavailable microphone capability is recorded as
  unverified. It is not replaced by native-SDK frame-count evidence.
- Trace export must produce an inspected real trace. A reachable Jaeger UI alone
  does not pass P1-I24.

**UI and signals:**

- Retain the existing TypeScript console as the default. Decide on official Agents
  UI components only for a genuine conversation-client consumer. A framework
  rewrite is not a prerequisite.
- Start with a bounded GET/cursor projection. Native SDK notifications may request
  a refresh, but cannot become state authority. No custom event bus or server-sent
  events (SSE) service is required.
- Use observed session and agent states, actual durable event history and a
  separate technical inspection view.
- Treat generated output, client playback and user acknowledgement distinctly.
- Correlate session, case, workflow, attempt and effect identities in sanitized
  logs and traces while retaining one case authority.

### Phase P1-H: reusable artifact and release proof

**Phase status:**

- P1-I26's typed package, API and independent-consumer boundary is implemented.
- The current full four-case H2 workload, the registered P1-18 and P1-14 gates and
  the selected provider_real v2 P1-20 runtime gate passed.
- The [release work item](../work-items/0019-p1-phase-h-release-qualification.md)
  owns the final source-matching package, shared quality and index results. P1 V1
  is qualified for the local POC using provider_real v2.
- H1 established the first S-I06/P1-I27 local inquiry baseline.
- The Phase P1-G media prerequisite has scripted evidence. The H2 restart,
  slow-dependency, saturation and shutdown measurements and the P1-I26 artifact,
  API and genuine-consumer review have passed.
- The selected provider_real v2 media and model scenario has passing runtime
  evidence.
- Configured local_real remains unqualified. Profile configuration alone grants no
  model result or business authority.
- Preserve H1 and earlier checkpoints as historical evidence.

**Entry:**

- Deterministic, process and container behavior and a genuine consumer establish
  the package boundary.
- P1-I26 may run alongside the conversational and media phase once its listed
  dependencies pass. Do not block packaging on microphone permission.
- Final release assessment still waits for every applicable local-media assertion.
- Freeze seeded schedules, the machine and mode, and numeric budgets before each
  broader workload.

| Task | PLAN | Prerequisites | Acceptance | Estimate | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P1-I26 | PLAN-11/22 | P1-I18, P1-I21 and a genuine second consumer | All P1 packaging/review gate | 2–4h | Completed | [0016](../work-items/0016-p1-standalone-package.md), [0019](../work-items/0019-p1-phase-h-release-qualification.md) |
| P1-I27 | PLAN-11/21/22 | P1-I21, P1-I24; media workloads also P1-I25 | P1-15/18/20 and release evidence | 3–4h | Completed | [0014](../work-items/0014-p1-phase-h-workload-baseline.md), [0015](../work-items/0015-p1-reliability-workloads.md), [0019](../work-items/0019-p1-phase-h-release-qualification.md) |
| P1-I28 | PLAN-21/22 | P1-I25, P1-I26, P1-I27 and configured real inference | P1-20 live portion; portfolio gate | 3–4h | Completed for provider_real v2; local_real unqualified | [0018](../work-items/0018-p1-provider-demo.md), [0019](../work-items/0019-p1-phase-h-release-qualification.md); local_real: [0017](../work-items/0017-p1-local-real-inference.md) |

**Task details:**

- **P1-I26**
  - Deliverable: finalize exports, build the P1 wheel, run the standalone CLI and
    example from an isolated consumer, and independently review the public API and
    failure contract.
  - Required failure assertion: no repository path injection or undeclared sibling
    deployment is needed. Old M1 entrypoints and data remain compatible. The
    review reproduces one controlled failure.
- **P1-I27**
  - Deliverable: run seeded steady, burst, saturation, restart and slow-provider
    workloads under declared budgets. Retain raw outcomes and the short normal and
    crash demonstration.
  - Required failure assertion: zero lost accepted work and no incorrect duplicate
    effects. Uncertainty is counted honestly. Resource and latency regressions are
    explained rather than hidden by rewriting budgets.
- **P1-I28**
  - Deliverable: resolve only the selected real-inference plugin at its
    compatibility checkpoint. Run the same relevant voice and tool scenario with
    configured real speech and model inference. Record outcomes, cost and
    configuration, and the final docs.
  - Required failure assertion: real-model output cannot bypass consent or state
    assertions. Missing credentials or unsupported local hardware leave the
    portfolio gate incomplete.

**Release exits:**

| Release exit | Requirement |
| --- | --- |
| Local-ready V1 | Every P1-01 through P1-20 local assertion, applicable shared quality gate, standalone artifact check, supported-platform setup, migration and restart proof, and independent review passes |
| Local-ready V1 | This exit can precede real-inference readiness |
| Portfolio-ready V1 | P1-I28 and the corresponding PLAN-22 review and demo evidence also pass |
| Portfolio-ready V1 | The root integrated release still waits for P2/P3 |

For the Portfolio-ready V1 exit:

- Shared local host and container setup and provider and exporter setup are
  coordinated once. Hosted CI and publication are outside this POC scope. Link
  their observed evidence rather than charging or implementing the same work three
  times.
- If plugin, review or capacity findings require fixes, schedule explicit
  follow-up tasks. The final task row is not permission to mark a failing
  requirement complete.

## Acceptance traceability

The charter remains authoritative. The table names the tasks that collectively
supply each assertion. Multiple entries mean that a partial earlier proof cannot
close that scenario on its own.

| Acceptance ID | Implementation tasks | Required final evidence |
| --- | --- | --- |
| P1-01 | P1-I03, P1-I04, P1-I08, P1-I09 | Accepting process terminated; original scoped identity/payload readable |
| P1-02 | P1-I04, P1-I08, P1-I09 | Concurrent duplicates plus lost response after commit |
| P1-03 | P1-I04, P1-I08, P1-I09, P1-I18 | Changed scoped replay conflicts; other scope independent; retention protection |
| P1-04 | P1-I05, P1-I06, P1-I09 | Independent worker persists inquiry; unchanged booking |
| P1-05 | P1-I02, P1-I05, P1-I07, P1-I09 | Actual process kill after inquiry success and before acknowledgement, then reconciliation |
| P1-06 | P1-I11, P1-I12, P1-I15 | Exact authorized fake revision applied under stable key |
| P1-07 | P1-I11, P1-I12, P1-I15 | Missing/altered/stale/expired confirmation causes zero apply calls |
| P1-08 | P1-I15, P1-I16 | Actual kill after mutation success and before acknowledgement, then reconciliation |
| P1-09 | P1-I14, P1-I16, P1-I20 | Noncooperating ambiguity is persisted; no unsafe resend |
| P1-10 | P1-I13, P1-I21 | Early/late signals and persisted deadline across process/container restart |
| P1-11 | P1-I13, P1-I18 | Deduplicated/changed/unrelated callbacks and retained protection |
| P1-12 | P1-I14 | Controlled-clock retry, exhaustion and expiry classifications |
| P1-13 | P1-I12, P1-I17 | Barrier-controlled precommit cancellation/confirmation race |
| P1-14 | P1-I17, P1-I22, P1-I25 | Postcommit best effort and actual speech interruption |
| P1-15 | P1-I19, P1-I20 | Independent PostgreSQL workers, stale write and external-call boundary |
| P1-16 | P1-I18 | Completion/outbox commit survives crash before delivery |
| P1-17 | P1-I10, P1-I11, P1-I21, P1-I23 | Trusted scope rejects cross-account reads/signals/cancel/history |
| P1-18 | P1-I14, P1-I21, P1-I24, P1-I27 | Admission, inspectability, cleanup, bounded retries/export/shutdown |
| P1-19 | P1-I03, P1-I08, P1-I09, P1-I21 | Original M1 identity/payload preservation and failed migration recovery |
| P1-20 | P1-I22, P1-I23, P1-I24, P1-I25, P1-I27, P1-I28 | Actual local voice/tool independence; real inference additionally required for portfolio |

## Demonstrations and signals

Each phase above ends with its **UI and signals** requirements: what the operator
view must show and which observations to record. These documents own the rest:

| Document | Owns |
| --- | --- |
| [Granular roadmap](../implementation-plan.md#what-each-project-should-show) | The P1 demonstration checkpoints: the first P1 proof and P1 local V1 |
| [Demo plan](../demo-plan.md) | Honest observable UI transitions |
| [Observability contract](../observability.md) | Signals, safe errors and cardinality |

## Commands and task handoff

### Existing commands

These commands exist now. Run them from the repository root after the
[documented bootstrap](../../README.md).

| Task | Command | Notes |
| --- | --- | --- |
| Run the shared fast checks | `make check` | Harness checks with tests, Ruff and mypy |
| Check Python formatting | `make format-check` | Ruff formatting check |
| Run the frontend checks | `make frontend-check` | Formatting, type checks, tests and builds |
| Validate the acceptance catalog | `.venv/bin/python -m harness validate` | Reports the case and registration counts |
| Run the baseline case | `.venv/bin/python -m harness run BASE-01` | The existing M1 intake tests |
| Run the P1 deep gate | `HARNESS_PYTHON=.venv/bin/python sh scripts/harness-deep.sh --module p1` | Needs explicit PostgreSQL and browser/inference setup |

The same commands as one sequence:

```sh
make check
make format-check
make frontend-check
.venv/bin/python -m harness validate
.venv/bin/python -m harness run BASE-01
HARNESS_PYTHON=.venv/bin/python sh scripts/harness-deep.sh --module p1
```

- All twenty P1 rows have registered runners.
- The P1 deep command executes actual PostgreSQL and browser/inference
  requirements and needs their explicit setup.
- The deep command defaults to the local_real profile for P1-20. Select
  provider_real explicitly using the [provider guide](../provider-demo.md).
- Missing setup, failed observations, skips or timeouts cannot pass.
- P2 and P3 are partially implemented. All seventeen P2 rows and fourteen of the
  seventeen P3 rows remain planned, so their project and ecosystem aggregates
  remain incomplete.
- Run actual local smoke only with its documented prerequisites. The one-room
  transport worker requires other browser sessions to be ended first.
- Do not invent new worker, migration or benchmark CLI commands in onboarding
  before they exist.

### Task packet example

For each task, use the [work-item template](../work-items/template.md). Example
packet for P1-I07:

| Packet field | P1-I07 example |
| --- | --- |
| Behavior | Recover one persisted inquiry after the selected crash window |
| Acceptance | P1-05; preserve P1-04 normal execution and BASE-01 |
| Ownership | The worker and store adapter, the independent fake-supplier fixture and the process scenario; no P2/P3 imports and no booking mutation |
| Inputs | The migrated queued request and the supplier capability declaration from P1-I03 through P1-I06 |
| Schedule | The four steps listed below the table |
| Assertions | The original inquiry and effect identity is recovered, with one logical supplier inquiry, a persisted local result, an unchanged booking and bounded child cleanup |
| Artifacts | The fixture seed, sanitized store and effect history, barrier and termination observations, command and version information, and a machine-readable scenario result |
| Handoff | Exact implemented commands, test outcomes, public and migration changes, reviewed limitations, an accurate assistance record and the next eligible task |

The P1-I07 schedule:

1. Block after the supplier commits its inquiry result.
2. Prove the barrier was reached.
3. Terminate only the owned worker.
4. Start a fresh worker.

### Final handoff

The final handoff must distinguish implemented behavior, passing partial tests,
completed acceptance rows and unresolved evidence. UI labels never determine a
backend outcome, and model judgments never replace the durable-state assertions.
