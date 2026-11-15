# P3 Delegation Reliability Kit implementation plan

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Break P3, the Delegation Reliability Kit, into bounded implementation tasks with prerequisites, estimates and evidence |
| Audience | Engineers and coding agents who choose the next P3 task, check its prerequisites or record its evidence |
| Scope | Phases P3-A to P3-F, tasks P3-I01 to P3-I24, dependency gates and acceptance traceability; excludes P3 requirements and shared tasks |
| Owns | P3 task decomposition, phase gates, effort sizing and per-task handoff |
| Related | [P3 charter](../projects/delegation-reliability-scope.md) · [Granular roadmap](../implementation-plan.md) · [Build plan](../build-plan.md) · [P3 project instructions](../../projects/delegation-reliability/AGENTS.md) |

## Purpose and authority

This plan breaks P3, the Delegation Reliability Kit, into bounded implementation
tasks. It is for engineers and coding agents who choose the next P3 task, check its
prerequisites or record its evidence. P3 delivers a Python coordination library
and an authenticated TypeScript capability service. Together they keep the
conversation responsive while independent, read-only work runs. Results must
remain scoped, revision-aware and explainable after retries, cancellation, process
failure, handoff and reconnect.

### Contents

| Section | What it covers |
| --- | --- |
| [Current status](#current-status) | What has passed and what remains open |
| [Starting point and dependencies](#starting-point-and-dependencies) | The foundation to reuse, the dependency gates, ownership and the package layout |
| [Planning and completion rules](#planning-and-completion-rules) | Task sizing, engineering gates, what a task can claim and discovery rules |
| [Phases and tasks](#phases-and-tasks) | Phases P3-A through P3-F, each with its status, entry conditions, task table, task details, exit criteria and, where defined, UI and signal requirements |
| [Acceptance traceability](#acceptance-traceability) | The primary tasks for each acceptance ID |
| [Demonstrations and signals](#demonstrations-and-signals) | Demonstration checkpoints and telemetry rules |
| [Commands and task handoff](#commands-and-task-handoff) | Verification commands and a task packet example |

### Authority

| Document | Owns |
| --- | --- |
| [P3 charter](../projects/delegation-reliability-scope.md) | The P3 requirements |
| [Build plan](../build-plan.md) | The ecosystem ordering |
| [Granular roadmap](../implementation-plan.md) | The shared tasks and the cross-project execution gates |
| [Validation plan](../validation-plan.md) | Test lanes, required fault scenarios, benchmarks and evidence |
| [Observability contract](../observability.md) | Signals, safe errors, cardinality and operational evidence |
| [Demonstration UX plan](../demo-plan.md) | Capability demonstrations and honest observable UI transitions |
| [Technology policy](../technology-baseline.md) | Candidate versions, compatibility, promotion and updates |
| [Runtime-boundary decision](../decisions/0001-runtime-boundaries.md) | Runtime, package and persistence boundaries |

- This plan divides PLAN-17 through PLAN-21 and P3's share of PLAN-22 into
  implementation sessions.
- This plan is subordinate to the granular roadmap.
- Read the validation plan, the observability contract, the demonstration UX
  plan, the technology policy and the runtime-boundary decision.

### Scope limits

- Public API examples in the charter are planned application contracts, not native
  LiveKit methods.
- Frozen versions are refreshed at integration and release checkpoints, not
  automatically before every task.
- No real carrier, Cloud account, continuous video pipeline or additional
  orchestration platform is required for this scope.

### How to read the task tables

Each phase lists its tasks in one table with these columns:

| Column | Meaning |
| --- | --- |
| Task | The implementation task ID |
| PLAN | The build-plan work package that the task implements |
| Prerequisites | The tasks, shared tasks (S-I IDs), dependency gates or contracts that must exist first |
| Acceptance | The acceptance IDs that the task contributes assertions to |
| Estimate | The planning estimate in engineering hours |
| Status | The recorded implementation status |
| Evidence | The work item that records the gate results |

The [granular roadmap](../implementation-plan.md) defines the shared S-I tasks,
and [Dependency gates](#dependency-gates) defines gates such as G-P1-EXEC.
"Completed (selected scope)" means the task's selected gates passed. It does not
by itself mean that a charter acceptance row passed.

The task details below each table give the concrete deliverable, the required
failure or negative assertion and, where recorded, status notes with the
qualification counts and remaining limits.

## Current status

P3-I01 through P3-I17 completed their selected gates. P3-I18's durable
prerequisite (P3-I18A) and native real-time communication (RTC) text slice
(P3-I18B) passed selected qualification. P3-I19's 0043 and 0044 prerequisites
are qualified. P3-I20 through P3-I24 remain planned.

P3-01, P3-03 and P3-11 have registered passing lab assertions. The remaining 14
cases stay planned, and full release remains pending. The harness catalog's
fifty-five definitions and twenty-four registered runners remain unchanged.

| Phase | Tasks | Task status | Evidence |
| --- | --- | --- | --- |
| [P3-A](#phase-p3-a-native-baseline-and-remote-boundary-decision) | P3-I01, P3-I02 | Completed (selected scope) | [0023](../work-items/0023-p3-native-baseline.md) |
| [P3-B](#phase-p3-b-one-authenticated-capability-and-useful-result) | P3-I03 to P3-I08, including P3-I07A and P3-I07B | Completed (selected scope) | [0025](../work-items/0025-p3-specialist-contracts-and-trust.md), [0027](../work-items/0027-p2-standalone-and-p3-http.md), [0028](../work-items/0028-p2-dispatch-and-p3-coordinator.md), [0029](../work-items/0029-p2-gateway-and-p3-issued-execution.md), [0030](../work-items/0030-p2-agent-recovery-and-p3-completion.md), [0031](../work-items/0031-revision-routing-and-delegation-acceptance.md) |
| [P3-C](#phase-p3-c-durable-applicability-races-and-recovery) | P3-I09 to P3-I15 | Completed (selected scope) | [0032](../work-items/0032-linked-confirmation-and-result-projections.md), [0033](../work-items/0033-outbound-replies-and-completion-processing.md), [0034](../work-items/0034-callback-evidence-and-applicability-refresh.md), [0035](../work-items/0035-send-policy-and-action-races.md), [0036](../work-items/0036-native-input-and-deadline-cancellation.md), [0037](../work-items/0037-playback-evidence-and-process-recovery.md), [0038](../work-items/0038-case-rehydration-and-standalone-release.md) |
| [P3-D](#phase-p3-d-two-bounded-read-only-capabilities) | P3-I16, P3-I17 | Completed (selected scope) | [0039](../work-items/0039-bounded-channel-workloads-and-image-evidence.md), [0040](../work-items/0040-operations-ui-and-fixed-policy-evidence.md) |
| [P3-E](#phase-p3-e-responsive-conversation-route-continuity-and-local-runtime) | P3-I18 to P3-I22 | P3-I18A and P3-I18B completed (selected scope); P3-I19 prerequisites completed; P3-I20 to P3-I22 planned | [0041](../work-items/0041-standalone-channel-and-durable-policy.md), [0042](../work-items/0042-responsive-native-policy-and-compact-demo.md), [0043](../work-items/0043-stable-result-delivery-and-return-context.md), [0044](../work-items/0044-origin-bound-channel-policy.md) |
| [P3-F](#phase-p3-f-comparable-evidence-and-release-handoff) | P3-I23, P3-I24 | Planned | None yet |

### Open work

- Integrated voice, text and SMS handoff, restart and discovery, applicable
  provider runs, complete release and the final video retain their later gates.
- All fourteen remaining full P3 acceptance rows remain planned.
- Broader platform, media and full charter release remain separately planned.
- This plan remains active. Unimplemented tasks and all full project acceptance
  rows remain pending. Phase completion requires the actual exit evidence in each
  phase.

## Starting point and dependencies

### Existing foundation

Reuse the existing pinned runtimes, the local LiveKit server, the diagnostic
worker, the TypeScript console, the protected API metrics, the error envelope and
the repository harness. Do not rebuild that foundation. Their current transport
and intake behavior does not establish delegation, model reasoning, remote
recovery or browser voice quality.

### Dependency gates

Each gate names the contract or evidence it requires and the work that needs it.

| Dependency | What must exist | Needed by |
| --- | --- | --- |
| G-P1-EXEC | Immutable accepted input, read and cancel (P3-I06), plus public P1-issued grants and immutable opaque results (P3-I07A) | The acceptance foundation at P3-I06, real persisted invocation and result progression at P3-I07, and recovery in Phase P3-C |
| G-CASE | Public exact case reads and the P1 `action_api` bind verified work and case credentials on the same PostgreSQL target | The P3-I07 authorized fake action |
| G-P1-RECOVERY | P1's process-recovery, effect-uncertainty and postcommit cancellation contracts have executable evidence | P3-I12 through P3-I14 |
| G-DELIVERY | An explicit P1 work v3 delivery intent, possible-send marker and receipt, plus a bounded independent persistent receiver | The first useful-result path; P2 deployment is unnecessary |
| G-P1-MEDIA | A scripted native AgentSession conversational adapter and an actual self-hosted browser audio path exist under PLAN-11 | Phase P3-E voice and responsiveness checks |
| G-P2-ROUTE | P2's public association and current-route adapter and its handoff and resumption contract are usable | Integrated P3-I19 and P3-I22; not needed for standalone reliability tests |
| G-PACKAGE | P1's execution library can be consumed through declared public exports without sibling storage imports | The isolated standalone consumer in P3-I15 |

Gate details:

- **G-P1-EXEC:** P3-I07A's grants and results arrive through the explicit P1
  work-profile v2 upgrade. The one-step P3 runner owns invocation outside
  transactions. Generic workers, automatic retry and durable delivery events
  remain separate gates.
- **G-CASE:** work eligibility, current exact confirmation, case intent and
  receipt share one protected transaction. Selected first-path schedules do not
  close every later race. Broader Phase P3-C race assertions remain separate.
- **G-DELIVERY:** only a newly persisted begin permits accept. An existing
  possible send performs lookup only. There is no outbox and no automatic retry
  loop.

### Ownership

| Owner | Owns |
| --- | --- |
| P1 alone | Durable acceptance, attempts, retry and deadline eligibility, and execution outcomes |
| P3 | Immutable delegation input, result validation and applicability, and routing observations |
| The case authority | Accepted action intents |
| P2 or the small standalone adapter | Delivery acceptance and evidence |

- Specialist status, result and cancel endpoints are observations of a bounded
  P1-owned attempt, not another recovering queue.
- No specialist receives booking-mutation or notification authority.

### Package and source layout

| Component | Path | Added by | Notes |
| --- | --- | --- | --- |
| Python workspace member | `projects/delegation-reliability/python` | Phase P3-A | None |
| TypeScript specialist source, project tests and delegation fixtures | `specialist-ts/src` and `contracts/delegation` | P3-I03 and P3-I04 | With actual Python and TypeScript producers and consumers |
| TypeScript HTTP | None listed | P3-I05 | None |
| Python coordinator and client modules | The same packages | P3-I06 | Added through the same packages and maintained discovery |
| Issued runner | `runner.py` and `execution_api` | P3-I07A | Extends these public boundaries |
| Completion and action adapters | `completion.py` and `action_adapter.py` | P3-I07B | Through the public `delivery_api`, `receiver_api`, `action_api` and `case_control_api`; creates no replacement authority or side ledger |

The root console presents read models. It must not own case revisions, retry
eligibility or a second event bus.

## Planning and completion rules

### Task IDs and estimates

- P3-I identifiers are planning tasks, not new acceptance scenarios.
- Each task is one reviewable slice. Its estimate includes implementation,
  focused tests and a short handoff, assuming the named prerequisites already
  work.
- Ranges are preliminary engineering hours, not elapsed dates or a release
  promise.
- Split any task that exceeds its upper bound. Retain the IDs and the acceptance
  semantics.
- Learning, review findings, dependency resolution and shared infrastructure work
  are additional rather than silently counted twice.
- The 24 slices total 64–89h before that contingency. Recalibrate after P3-I08 and
  P3-I14.

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

- Every slice updates its owned README, Design and AGENTS guidance, runs the
  applicable existing checks and records a work item.
- Add telemetry with real producers.
- Register acceptance runners only after their assertions exist, and preserve
  incomplete status for missing work.
- Commands for future services and runners enter runnable quickstarts only after
  implementation and verification.
- Phase completion requires the actual exit evidence in each phase.

### Discovery rules

- Add any new package, source or tests to the actual workspace, lint, format,
  type, test and build discovery in the same slice.
- Preserve deliberately failing fixture checks and nonzero-test checks.
- Existing console-only pnpm checks or service-only typing cannot qualify the
  specialist or the coordinator.

## Phases and tasks

### Phase P3-A: native baseline and remote-boundary decision

**Phase status:** P3-I01 and P3-I02 passed their bounded first-slice gates, recorded in
the [slice work item](../work-items/0023-p3-native-baseline.md).

**Entry:**

- Read the root and project instructions, the current native software
  development kit (SDK) interfaces and the fixed capability scope.
- This small controlled baseline may proceed without the complete P1/P2
  application.

It establishes orchestration behavior, not durable recovery or real-model or audio
performance.

| Task | PLAN | Prerequisites | Acceptance | Estimate | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P3-I01 | Before PLAN-17 | Reviewed charter; current frozen toolchain | P3-16 initial baseline | 2–3h | Completed (selected scope) | [0023](../work-items/0023-p3-native-baseline.md) |
| P3-I02 | Before PLAN-17 | P3-I01 | P3-16 initial baseline | 2–3h | Completed (selected scope) | [0023](../work-items/0023-p3-native-baseline.md) |

**Task details:**

- **P3-I01**
  - Deliverable: one bounded, seeded capability input and a controlled outcome
    fixture. A single-agent tool example with useful-result and responsiveness
    observations.
  - Required failure or negative assertion: invalid or excessive context is
    rejected. A held capability does not falsely report completion.
- **P3-I02**
  - Deliverable: a native local-subagent example using equivalent bounded input.
    A retained baseline and a decision that explains process, language and
    permission isolation for a remote boundary.
  - Required failure or negative assertion: record context differences and remote
    tradeoffs. Do not claim that native tasks survive an independent process
    failure.

**Exit:**

- The repeatable tool and native examples and the remote-boundary decision are
  reviewed before a remote service is built.
- Native execution may be faster. The remote service must have an explicit
  isolation or recovery reason rather than a promised latency improvement.
- PLAN-21 still performs the full three-way comparison.

### Phase P3-B: one authenticated capability and useful result

**Phase status:** all tasks completed their selected gates. P3-I08 registered complete
lab runners for P3-01, P3-03 and P3-11, and all three have fresh passing reports.

**Entry:**

- Phase P3-A is complete.
- G-P1-EXEC, G-CASE and G-DELIVERY are stable enough for one normal path. Schemas
  and independent fixture work can begin while those gates stabilize, but mocked
  ports cannot pass real execution or durability assertions.
- Start with scripted `booking.evaluate_policy` over seeded verified facts.
  Introduce image extraction only after this first remote slice works.

| Task | PLAN | Prerequisites | Acceptance | Estimate | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P3-I03 | PLAN-17 | P3-I02; shared case/execution field decisions | P3-01, P3-03, P3-11 | 3–4h | Completed (selected scope) | [0025](../work-items/0025-p3-specialist-contracts-and-trust.md) |
| P3-I04 | PLAN-17 | P3-I03 | P3-11 | 2–3h | Completed (selected scope) | [0025](../work-items/0025-p3-specialist-contracts-and-trust.md) |
| P3-I05 | PLAN-17 | P3-I04 | P3-01, P3-11 | 3–4h | Completed (selected scope) | [0027](../work-items/0027-p2-standalone-and-p3-http.md) |
| P3-I06 | PLAN-17 | P3-I03; public P1 accepted-work profile; scoped case-read preflight | P3-01, P3-03 foundation | 3–4h | Completed (selected scope) | [0028](../work-items/0028-p2-dispatch-and-p3-coordinator.md) |
| P3-I07 | PLAN-17 | P3-I05, P3-I06; G-P1-EXEC issued progression; G-CASE; G-DELIVERY | P3-01; initial P3-05 | Split around frozen prerequisites | Completed (selected scope) through P3-I07A and P3-I07B | [0029](../work-items/0029-p2-gateway-and-p3-issued-execution.md), [0030](../work-items/0030-p2-agent-recovery-and-p3-completion.md) |
| P3-I07A | PLAN-17 | P3-I05/I06; explicit P1 work v2 | P3-01 foundation | Bounded prerequisite slice | Completed (selected scope) | [0029](../work-items/0029-p2-gateway-and-p3-issued-execution.md) |
| P3-I07B | PLAN-17 | P3-I07A; G-CASE; G-DELIVERY | P3-01; initial P3-05 | Bounded first-path slice | Completed (selected scope) | [0030](../work-items/0030-p2-agent-recovery-and-p3-completion.md) |
| P3-I08 | PLAN-17 | P3-I07 | P3-01/P3-03/P3-11 lab rows | 2–3h | Completed (selected scope) | [0031](../work-items/0031-revision-routing-and-delegation-acceptance.md) |

**Task details:**

- **P3-I03**
  - Deliverable: versioned request, result and error envelopes, semantic
    canonicalization, trusted input and source fingerprints, and bounded evidence
    and provenance fields. Shared Python and TypeScript positive and negative
    fixtures.
  - Required failure or negative assertion: reject an unsupported version, a changed
    same-ID payload, a wrong revision or scope, an unknown capability and malformed
    output before acceptance or use.
  - Status notes: the
    [P3-I03/I04 contract and trust work item](../work-items/0025-p3-specialist-contracts-and-trust.md)
    adds the first policy wire, evidence and principal boundary.
- **P3-I04**
  - Deliverable: local service-principal binding, capability and evidence
    authorization, and explicit limits and units for context, image, result, time
    and active attempts.
  - Required failure or negative assertion: a forged JSON scope, a missing
    credential, inaccessible evidence, a swapped source, version or fingerprint, an
    arbitrary fetch URL and oversized input cannot invoke work or disclose another
    account's result.
- **P3-I05**
  - Deliverable: a bounded scripted TypeScript HTTP handler and a typed client for
    one capability, with safe errors and invocation observations.
  - Required failure or negative assertion: a wrong schema or authentication, or
    excess capacity, is rejected. Lost connections do not create a service-owned
    recovering queue. A timeout does not prove that computation stopped.
  - Status notes: the
    [P3-I05 HTTP work item](../work-items/0027-p2-standalone-and-p3-http.md)
    extends the contract boundary with one authenticated scripted handler and
    client and actual socket evidence.
- **P3-I06**
  - Deliverable: coordinator submit, find, get and requested-cancel, and a Python
    HTTP client with declared dependencies. The complete immutable canonical
    input, digest and deadline persist through P1 before acknowledgement. The
    delivery interface is reserved for P3-I07 and is not invoked here.
  - Required failure or negative assertion: caller mutation cannot alter accepted
    context. A misbound credential scope fails before writes. An ambiguous commit
    reconciles the original key without a second submit. Independent socket and
    persisted-acceptance proofs do not issue an execution.
  - Status notes: the
    [P3-I06 phase](../work-items/0028-p2-dispatch-and-p3-coordinator.md) adds
    immutable coordinator acceptance, find, get and requested-cancel through P1's
    separately installed public read-only work profile, plus a Python HTTP client.
    The corrected actual gate separates runtime and owner credentials, uses a
    synthetic case preflight, observes a postcommit kill and fresh lookup, and
    probes transport independently. P3-I06 issues no attempt and no durable
    specialist result.
- **P3-I07**
  - Deliverable: the issued HTTP result, the durable receiver and the exact fake
    action, split into P3-I07A and P3-I07B.
  - Required failure or negative assertion: a read-only candidate or result cannot
    authorize mutation. The stale-A and current-B useful action, the atomic work and
    case guard and owned cleanup must pass.
  - Status notes: P3-I07A and P3-I07B completed their selected issued HTTP result,
    durable receiver and exact fake-action gates, completing the P3-I07
    implementation task. Broader protected case race and recovery schedules and
    media remain later gates.
- **P3-I07A**
  - Deliverable: a scoped issued runner, stable command and attempt
    reconciliation, an immutable bounded result and read applicability. No retry
    queue.
  - Required failure or negative assertion: a replayed or unknown issuance never
    reinvokes. Late, stale or cancelled strict results remain historical. The
    original accepted bytes survive.
  - Status notes: the
    [P3-I07A phase](../work-items/0029-p2-gateway-and-p3-issued-execution.md) adds
    the explicit P1-issued runner and immutable result observations through the
    optional P1 work-profile v2 upgrade. Deterministic `attempt_<uuidhex>` wire
    correlation is derived from the issued UUID, while the accepted bytes remain
    unchanged.
- **P3-I07B**
  - Deliverable: explicit first delivery and guarded action adapters over the
    owner-upgraded P1 work v3, the independent receiver and the existing leased
    fake supplier worker.
  - Required failure or negative assertion: zero stale action intents. The current
    independently confirmed B commits one intent and effect. The original receipt
    survives later cancellation or expiry and cannot retarget. Broader P3-I12 and
    P3-I13 schedules remain required.
  - Status notes: the first durable delivery and the separately confirmed fake
    action are implemented in the
    [P3-I07B phase](../work-items/0030-p2-agent-recovery-and-p3-completion.md),
    and the selected combined gate passed. P1 work-profile v3 owns immutable
    delivery and action receipts, and atomic work eligibility plus exact case
    commitment. The independent receiver owns byte acceptance.
- **P3-I08**
  - Deliverable: independent-process same-ID replay and conflict, a public
    completion and inspection example, and complete registered lab runners for
    P3-01, P3-03 and P3-11.
  - Required failure or negative assertion: concurrent equal requests retain one
    immutable logical delegation. A changed payload conflicts. The full input,
    output, schema, scope and image-resource rejection inventory and valid progress
    execute. There is no one-physical-computation claim.
  - Status notes: P3-I08 adds actual concurrent acceptance and conflict, a public
    completion and inspection example and the first complete registered lab
    runners. P3-01, P3-03 and P3-11 have fresh passing reports, and 14 other
    charter rows remain planned. The final task and artifact gates passed,
    completing P3-I08. The final qualification is recorded in the
    [P3-I08 work item](../work-items/0031-revision-routing-and-delegation-acceptance.md).

**Exit:** one real useful current result, a same-ID conflict and a minimal
stale-result rejection work before adding models or the second capability.

**UI and signals:**

- Show accepted, running and result observations in the console only when real
  responses or events supply them.
- Keep execution, applicability and delivery in separate fields.
- Telemetry and error minimum: use fixed capability, outcome and error-code
  dimensions. Correlate delegation, P1 attempt, revision and delivery IDs in safe
  logs and spans, never in metric labels.
- Return typed validation, authentication, conflict, capacity, deadline and
  unknown-outcome errors without provider messages or credentials.
- HTTP retry advice cannot authorize another logical delegation or external
  action.

### Phase P3-C: durable applicability, races and recovery

**Phase status:** all seven tasks completed their selected scope. The evidence for each
task is linked from the table.

**Entry:**

- Phase P3-B is complete and G-P1-RECOVERY is available.
- Introduce only P3-owned versioned metadata. P1 remains the execution ledger.
- Any applicability decision records the revision it evaluated. Current action
  authority is always revalidated atomically.
- P3-I06 already persists and replays the complete immutable envelope and digest
  in P1 acceptance. P3-I09 must not retrofit identity after acknowledgement.
- Apply the one-shot migration and configuration mechanism of shared task S-I05,
  defined in the [granular roadmap](../implementation-plan.md), to P3-owned schema
  and grants. Serving roles cannot perform schema changes (data definition
  language, DDL) or receive bootstrap administrator credentials.

| Task | PLAN | Prerequisites | Acceptance | Estimate | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P3-I09 | PLAN-18 | P3-I08; P1 durable event contract; S-I05 applied to P3 schema/grants | P3-04, P3-08 | 3–4h | Completed (selected scope) | [0032](../work-items/0032-linked-confirmation-and-result-projections.md) |
| P3-I10 | PLAN-18 | P3-I09; G-DELIVERY | P3-04 | 2–3h | Completed (selected scope) | [0033](../work-items/0033-outbound-replies-and-completion-processing.md) |
| P3-I11 | PLAN-18 | P3-I09; G-CASE | P3-05 | 3–4h | Completed (selected scope) | [0034](../work-items/0034-callback-evidence-and-applicability-refresh.md) |
| P3-I12 | PLAN-18 | P3-I11; G-P1-RECOVERY | P3-06, P3-07 | 3–4h | Completed (selected scope) | [0035](../work-items/0035-send-policy-and-action-races.md) |
| P3-I13 | PLAN-18 | P3-I09, P3-I11; P1 fake-clock/cancellation contract | P3-09, P3-10 | 3–4h | Completed (selected scope) | [0036](../work-items/0036-native-input-and-deadline-cancellation.md) |
| P3-I14 | PLAN-18 | P3-I10, P3-I12, P3-I13 | P3-08; P3-04 recovery | 3–4h | Completed (selected scope) | [0037](../work-items/0037-playback-evidence-and-process-recovery.md) |
| P3-I15 | PLAN-18 and PLAN-22 | P3-I14; G-PACKAGE | Standalone release gate; P3-01/P3-08 | 2–3h | Completed (selected scope) | [0038](../work-items/0038-case-rehydration-and-standalone-release.md) |

**Task details:**

- **P3-I09**
  - Deliverable: owner-installed P3 metadata v1 and a bounded explicit projection
    from the P1 work v4 result-only feed, preserving the original accepted
    identities. The as-of metadata grants no action or delivery permission.
  - Required failure or negative assertion: the upgrade preserves accepted
    identities. An interrupted projection resumes without inventing execution state
    or losing a P1 result.
  - Status notes: the
    [result-projection phase](../work-items/0032-linked-confirmation-and-result-projections.md)
    completed P3-I09 with the explicit P1 work v4 result feed and owner-installed
    P3 metadata v1. The actual and installed 12-case recovery gates passed both
    precommit and postcommit kills, fresh resume, original-observation replay and
    independent identity reconciliation, and the final phase checks passed.
    Applicability is immutable as-of metadata.
- **P3-I10**
  - Deliverable: explicit delivery-only resumable processing over owner-upgraded
    projection v2, with a fixed policy, separate discovery and terminal watermarks,
    and exact event acknowledgements (ACKs) after the required processing.
  - Required failure or negative assertion: replay preserves the original delivery
    receipts and event ACKs. An unknown A stays unacknowledged while a later
    eligible B progresses. For an existing possible send, an absent record remains
    lookup-only, with zero automatic actions and zero duplicate logical receiver
    acceptances.
  - Status notes: delivery-only processing completed its selected local gates.
    The actual and installed 16-case gates, the coherent-snapshot and race proof
    and the final phase checks passed, completing P3-I10. P1 receipts remain
    authoritative, and no source ACK or action is introduced.
- **P3-I11**
  - Deliverable: an explicit exact-command non-atomic applicability refresh,
    monotonic retained invalidation witnesses and profile-lifetime display
    tombstones over owner-upgraded projection v3.
  - Required failure or negative assertion: a late A remains outdated, with zero
    A-derived current actions. A valid separately confirmed B progresses. Display
    hiding preserves the original projection, refresh, ACK and receipt identities,
    unresolved processing and replay at capacity. It reclaims no protected slots.
  - Status notes: P3-I11 adds explicit refreshed applicability, monotonic retained
    evidence and permanent display tombstones. The 18-case source gate, the
    isolated installed gate and the final phase gates passed, completing P3-I11.
- **P3-I12**
  - Deliverable: actual revision, intent and cancellation schedules through the
    unchanged public authorities.
  - Required failure or negative assertion: reject A atomically, with zero A-derived
    current intents or effects, and permit one independently confirmed B intent. A
    later revision cannot reverse a committed external intent. Show P1's actual
    cancellation and effect outcome.
  - Status notes: the protected action and revision schedules passed their
    selected source and installed gates through unchanged P1/P3 authorities. The
    gate covers 16 assertions, two true two-waiter order graphs, three owned
    kills, nine retained business-completion joins and isolated installed-artifact
    qualification. The final local gates passed, completing P3-I12.
- **P3-I13**
  - Deliverable: expiry before and during invocation, and separate observations of
    cancellation requested, cancellation acknowledged and result invalidation.
  - Required failure or negative assertion: no new ineligible attempt starts.
    Authority-observed time governs eligibility, never model completion timestamps.
    An ignored cancellation may complete, but its invalidated result cannot cause an
    action.
  - Status notes: P3-I13 passed its selected source and isolated installed
    eighteen-case deadline and cancellation gates and forty-six compatibility
    assertions in the
    [completed handoff](../work-items/0036-native-input-and-deadline-cancellation.md).
    The selected P2 native and artifact gates and the final phase regression and
    shared gates also passed, completing P3-I13 within its selected temporal
    scope.
- **P3-I14**
  - Deliverable: qualified source and isolated installed process-recovery gates.
  - Preserve: the unchanged P1/P3 runtime, exact issuance owner and command
    replay, retained results and receipts, unknown delivery gaps and useful current
    progress, as recorded in the completed handoff below.
  - Required failure or negative assertion: new processes recover accepted work
    through P1. Duplicate read-only computation cannot create a second logical
    result or an authorized effect.
  - Status notes: the
    [completed recovery handoff](../work-items/0037-playback-evidence-and-process-recovery.md)
    records the qualified seventeen-case source gate and the isolated installed
    seventeen-case gate. Each has eight owned process kills and one actual
    two-waiter issuance graph. Eighty existing execution, processing,
    applicability, action and deadline compatibility assertions passed with
    cleanup and an unchanged P1/P3 production runtime.
  - Limits: original command replay is lookup-only. A separately supplied new
    command needs fresh P1 eligibility. Unknown delivery remains unacknowledged
    while later current work progresses.
- **P3-I15**
  - Deliverable: a maintained local build and install command, a fresh declared P1
    wheel, P3 wheel, sdist and rebuilt-archive and npm parity, and unadapted public
    completion and metadata examples.
  - Required failure or negative assertion: the example works without a repository
    `PYTHONPATH`, sibling store imports, the P2 gateway or the complete P1 and
    reference deployment. Import alone does not start a server.
  - Status notes: P3-I15 completed selected standalone consumption through its
    maintained gate of sixteen assertions (eight offline plus eight installed lab)
    in the [handoff](../work-items/0038-case-rehydration-and-standalone-release.md).
    Fresh declared archives and the unadapted public completion and metadata
    examples passed, including original replay with zero new writes, invokes,
    accepts or applies, one owned caller-process kill and complete cleanup. The
    final shared phase gates passed. That checkpoint preserved P1's seventy-seven
    and P3's thirty runtime payloads.
  - Limits: the existing P1/P3 runtime authority remains unchanged. Broader
    platform and release gates remain separate.

**Exit:**

- Deterministic normal, replay, race, deadline, cancellation and process tests
  pass with real persisted adapters.
- Cancellation acknowledgement is not a guaranteed remote stop.
- Keep late results and tombstones long enough for the declared replay horizon.
  Expiry and display-history limits cannot remove idempotency protection.

**UI and signals:**

- UI history shows successfully computed but outdated results honestly. It never
  labels them as a current answer.
- Correlate the authority decision and the eventual effect outcome without
  copying another component's state machine.
- Record recovery lag, attempts, invalidation reasons and valid-result progress.

### Phase P3-D: two bounded read-only capabilities

**Phase status:** P3-I16 and P3-I17 completed selected qualification. Fourteen full
charter rows remain planned.

**Entry:**

- Phase P3-C is complete.
- Both capabilities share the same authenticated attempt contract, limits,
  provider interface and permission boundary.
- Deterministic fixtures remain the default. No external model credential is
  required here.

| Task | PLAN | Prerequisites | Acceptance | Estimate | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P3-I16 | PLAN-19 | P3-I15; scoped evidence adapter from P3-I04 | P3-15, P3-11 | 3–4h | Completed (selected scope) | [0039](../work-items/0039-bounded-channel-workloads-and-image-evidence.md) |
| P3-I17 | PLAN-19 | P3-I16; existing scripted policy capability | P3-15, P3-11 | 3–4h | Completed (selected scope) | [0040](../work-items/0040-operations-ui-and-fixed-policy-evidence.md) |

**Task details:**

- **P3-I16**
  - Deliverable: add the finite `booking.extract_document` contract, a scoped
    immutable PNG decoder and handler, and configured public clients and examples.
    Scripted fixture evaluation is separate from structural validation and from
    the independent literal factual oracle. P1 remains policy-only.
  - Required failure or negative assertion: distinguish schema validity from
    known-fixture factual accuracy. Reject valid JSON with wrong values or swapped
    evidence. Missing or ambiguous fields lead to clarification. Reject
    inaccessible, oversized or excessive-dimension images before uncontrolled work.
  - Status notes: the bounded standalone image HTTP path passed selected local
    qualification in the
    [completed handoff](../work-items/0039-bounded-channel-workloads-and-image-evidence.md).
    Twenty contract and socket assertions and their fresh installed repetition
    passed selected qualification in 0039, and both passed current compatibility
    reruns in 0040.
  - Image path rules:
    - The new four-field image result stays separate from policy eligibility and
      P1 durable execution.
    - Actual immutable PNG bytes are bounded before the provider.
    - Missing or ambiguous values require clarification, and image instructions
      remain inert data.
    - The scripted fixture mapping establishes no optical character recognition
      (OCR) or real vision inference.
    - A reviewed versioned P1 operation extension is required before image work
      can enter the durable coordinator.
- **P3-I17**
  - Deliverable: explicit policy-v2 immutable policy, fact and rule witnesses,
    independent literal factual checks and adversarial text.
  - Required failure or negative assertion: untrusted text cannot grant tools.
    Invented policy rules and conflicting or unsupported evidence fail factual
    evaluation. Provenance and confidence grant no authority. Uncertainty leads to
    clarification, correctly grounded current results progress, and no mutation or
    notification capability exists.
  - Status notes: fixed-policy semantic evidence completed selected standalone
    HTTP qualification in
    [0040](../work-items/0040-operations-ui-and-fixed-policy-evidence.md). Twenty
    source and twenty installed assertions, image regressions and 146
    compatibility assertions passed. At that checkpoint the durable runner was
    v1-only. P3-I18A now adds explicit v2 durable consumption, and v1 defaults
    remain unchanged. Native background conversation and UI still belong to the
    full P3-I18.

**Exit:**

- The two named capabilities return useful schema-valid evidence or explicit
  clarification under the same bounded contract.
- Apply the charter's immutable-source and provenance contract, retaining
  separate structural and factual fixture outcomes. Evidence must support the
  accepted source and version. No timestamp or model metadata grants authority.
- Node Agents and native RTC are not needed for these ordinary HTTP handlers.
  Introduce them only if an actual Node-hosted realtime agent is separately
  selected.
- Continuous video, arbitrary specialists and a dynamic tool marketplace remain
  deferred.

### Phase P3-E: responsive conversation, route continuity and local runtime

**Phase status:**

- P3-I18A is a durable-consumption prerequisite. It passed selected qualification
  in [0041](../work-items/0041-standalone-channel-and-durable-policy.md).
- P3-I18B separately passed selected source and installed RTC text qualification
  in [0042](../work-items/0042-responsive-native-policy-and-compact-demo.md). The
  qualification covers an AgentSession that continues a useful answer while
  remote work is held, plus the compact result view.
- Selected backend v2 delivery and current-channel reads subsequently qualified in
  [0043](../work-items/0043-stable-result-delivery-and-return-context.md).
- [0044](../work-items/0044-origin-bound-channel-policy.md) implements the
  original P2-origin prerequisite with focused unit and socket evidence and
  passing isolated package and fake-port qualification. Its fourteen selected
  actual source assertions passed.
- Integrated room handoff and voice, text and SMS, the later load, runtime and
  restart gates, applicable provider runs and the final demo video remain
  planned.
- Keep the standalone image capability separate. This work adds no image
  operation to P1 or to the v2/v3 projection, refresh or guarded-action adapter.

**Entry:**

- Phase P3-D is complete and G-P1-MEDIA is available.
- Use a standalone delivery adapter first. G-P2-ROUTE is needed only for the
  integrated resumption scenario, not for all coordinator tests.
- Reuse the existing console and native LiveKit controls.
- P3-I22 can first prove actual browser and media integration with the narrow
  standalone delivery adapter. Repeat routing through P2 when G-P2-ROUTE exists,
  and retain that integrated reference app evidence for shared task S-I08, the
  integrated release rehearsal in the [granular roadmap](../implementation-plan.md).
- A standalone pass cannot be labelled as the P2 integration.

| Task | PLAN | Prerequisites | Acceptance | Estimate | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P3-I18 | PLAN-20 | P3-I17; G-P1-MEDIA | P3-02; P3-17 preparation | 3–4h | P3-I18A and P3-I18B completed (selected scope) | [0041](../work-items/0041-standalone-channel-and-durable-policy.md), [0042](../work-items/0042-responsive-native-policy-and-compact-demo.md) |
| P3-I19 | PLAN-20 | P3-I18; G-DELIVERY; G-P2-ROUTE for integrated adapter | P3-12 | 2–4h | Open; 0043 and 0044 prerequisites completed | [0043](../work-items/0043-stable-result-delivery-and-return-context.md), [0044](../work-items/0044-origin-bound-channel-policy.md) |
| P3-I20 | PLAN-20 | P3-I18; P1 admission limits | P3-13 | 3–4h | Planned | None yet |
| P3-I21 | PLAN-20 and PLAN-09 extension | P3-I14, P3-I19; versioned P3 storage; S-I05 applied to P3 services/configuration | P3-14 | 2–3h | Planned | None yet |
| P3-I22 | PLAN-20 and PLAN-11/15 integration | P3-I18 through P3-I21; G-P2-ROUTE for integrated P2 repetition | P3-17, P3-02, P3-12 | 3–4h | Planned | None yet |

**Task details:**

- **P3-I18**
  - Deliverable: the explicit v2 durable-consumption prerequisite (P3-I18A) and
    the explicit native RTC text application with a compact optional result view
    (P3-I18B). Explicit v2 facades reuse opaque P1 work authority and preserve v1
    defaults. Broader integrated voice and result routing follows separately. Use
    the existing authority, not a new bus.
  - Required failure or negative assertion: with the specialist held on a barrier,
    another user question gets a useful response. No blocking database or HTTP work
    and no fake timed progress occupies the conversation loop.
  - Status notes, P3-I18A: the selected durable fixed-policy prerequisite is
    recorded in [0041](../work-items/0041-standalone-channel-and-durable-policy.md).
    Twelve source and twelve installed assertions, a separate eight-assertion
    offline package gate and four focused HTTP regressions passed. All 146 selected
    compatibility assertions passed. The final shared checks and the M1 checks (the
    original confirmed-investigation intake) passed in that completed handoff.
  - Status notes, P3-I18B: native RTC text background conversation and UI
    subsequently passed selected source and installed qualification in
    [0042](../work-items/0042-responsive-native-policy-and-compact-demo.md). It
    passed twelve backend and SDK assertions and three actual RTC and browser
    groups per mode, plus eight separate installed package assertions.
- **P3-I19**
  - Deliverable: integrated room handoff and voice, text and SMS delivery of the
    scoped current result, built on the selected prerequisites below.
  - Required failure or negative assertion: the returning interaction receives only
    its scoped current result. Old room or agent references cannot drop delivery or
    leak another account's context.
  - Completed prerequisite, stable result reads: selected backend v2 delivery and
    current-channel reads qualified in
    [0043](../work-items/0043-stable-result-delivery-and-return-context.md).
    Sixteen storage and four return actual source assertions passed, and its
    twenty-five-stage offline package lane remains separate.
  - Completed prerequisite, original-input binding:
    [0044](../work-items/0044-origin-bound-channel-policy.md) implements original
    P2-origin binding, schema version 3 facades, a narrow operation client and
    application HTTP. Focused unit and socket evidence and isolated package and
    fake-port qualification passed. Its fourteen selected actual source
    assertions passed.
  - Remaining: integrated room handoff and voice, text and SMS delivery retain
    their later gate.
- **P3-I20**
  - Deliverable: a seeded global and per-tenant saturation experiment and a
    bounded TypeScript active-attempt registry with documented overload outcomes.
  - Required failure or negative assertion: a saturated A cannot exceed the caps,
    and an admitted B progresses. A service rejection leaves accepted P1 work
    inspectable and eligible under its retry policy.
- **P3-I21**
  - Deliverable: product Compose services, migration and readiness checks, and a
    normal same-volume restart scenario.
  - Required failure or negative assertion: restart preserves accepted delegations,
    results and callback deduplication. Startup and shutdown are bounded. A normal
    stop never resets data.
- **P3-I22**
  - Deliverable: an actual self-hosted browser demonstration of voice,
    interruption and result routing, with fixture inference first.
  - Required failure or negative assertion: observe playback and interruption at the
    client. Speech interruption is not business cancellation. Unavailable microphone
    or playback evidence stays unverified.

**Exit:**

- The user can watch work continue while the conversation stays responsive,
  revise the case, see A become outdated, and see B deliver through the returning
  route.
- The UI has separate execution, applicability and delivery lanes, safe errors and
  an inspection view backed by bounded queries.
- Keyboard operation, reduced motion, empty, error and unknown states and mobile
  reflow remain usable.

**Admission rules:**

- Keep one fixed admission policy.
- A small two-tenant fixture can demonstrate fairness. It is not a production
  capacity claim.
- P1 owns durable queue limits. The TypeScript service separately protects finite
  active invocations and input resources.
- Do not reschedule accepted work inside that service.

### Phase P3-F: comparable evidence and release handoff

**Phase status:** P3-I23 and P3-I24 are planned.

**Entry:**

- Phase P3-E is complete.
- Prior-phase local P3 assertions have runners with meaningful positive counts,
  failure artifacts and bounded cleanup.
- Current shared media and release gates remain separate from the P3
  implementation tasks.

| Task | PLAN | Prerequisites | Acceptance | Estimate | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P3-I23 | PLAN-21 | P3-I22; retained P3-I01/I02 baseline | P3-16 local comparison | 3–4h | Planned | None yet |
| P3-I24 | PLAN-21 and PLAN-22 | P3-I23; explicit live credentials/budget for live lane | P3-15/P3-16/P3-17 live evidence; release gate | 3–4h | Planned | None yet |

**Task details:**

- **P3-I23**
  - Deliverable: a controlled three-way tool, native and remote benchmark using
    equivalent fixtures, a declared workload and resources, and budgets fixed
    before evaluation.
  - Required failure or negative assertion: retain raw samples, correctness, queue
    and recovery delay, event-loop lag, and CPU and resident set size (RSS). Show
    zero stale intents plus valid-result progression. Report no tail percentile from
    inadequate samples.
- **P3-I24**
  - Deliverable: selected real-model image, policy and voice runs, a final API and
    failure review, an isolated consumer rerun and a short success and failure
    demo.
  - Required failure or negative assertion: check evidence against expected
    outcomes. Report the provider and configuration, context differences and actual
    or unavailable cost. An absent live setup is not a passing portfolio gate.

**Release exits:**

| Release exit | Requirement |
| --- | --- |
| Local-ready V1 | All 17 cases' local assertions, independent-process recovery, standalone installation and actual local media evidence |
| Portfolio-ready V1 | Additionally, the selected live outcomes, three comparable baselines, cost and configuration, independent review and an explainable demonstration |

For both exits:

- Report passed, failed, unimplemented and not-run evidence distinctly.
- Provider failure must not be hidden by switching to a fake model and retaining a
  live label.

## Acceptance traceability

P3-01, P3-03 and P3-11 have complete registered lab runners and fresh passing
reports. The remaining 14 mappings identify planned assertions. The charter
remains authoritative for each case. Selected lab completion does not qualify full
release. Each row names the case's primary tasks and the proof to retain.

| Acceptance ID | Implementation tasks | Required final evidence |
| --- | --- | --- |
| P3-01 | P3-I07 | Python-to-TypeScript useful current result, delivery and explicitly authorized fake action |
| P3-02 | P3-I18, P3-I22 | Held specialist plus useful ongoing conversational response |
| P3-03 | P3-I08 | Concurrent equal-ID deduplication and changed-payload conflict |
| P3-04 | P3-I10, P3-I14 | Completion replay before/after restart with one logical result/action intent |
| P3-05 | P3-I11 | Stale A rejected for B while a valid B result progresses |
| P3-06 | P3-I12 | Barrier-controlled atomic authority race |
| P3-07 | P3-I12 | Revision after commitment and actual external cancellation/effect boundary |
| P3-08 | P3-I14 | Real independent process termination and persisted recovery |
| P3-09 | P3-I13 | Expiry before dispatch/during work; no ineligible attempt or applicable late result |
| P3-10 | P3-I13 | Ignored remote cancellation observed separately from result invalidation |
| P3-11 | P3-I03, P3-I04, P3-I17 | Schema/scope/authority/resource/adversarial rejection explanations |
| P3-12 | P3-I19, P3-I22 | Correct scoped route after actual handoff/reconnect |
| P3-13 | P3-I20 | Global/per-tenant bounds and other-tenant progress |
| P3-14 | P3-I21 | Same-volume container restart and safe callback replay |
| P3-15 | P3-I16, P3-I17, P3-I24 | Missing/ambiguous/adversarial image/policy evidence; separate real-model outcomes |
| P3-16 | P3-I23, P3-I24 | Three-way raw timing/correctness/cost/configuration comparison |
| P3-17 | P3-I22, P3-I24 | Actual local browser voice/interruption/routing, with live inference separately labelled |

## Demonstrations and signals

### Demonstration checkpoints

Each checkpoint pairs what the viewer sees with a deliberate failure and a useful
recovery.

| Checkpoint | Normal story | Controlled failure and recovery |
| --- | --- | --- |
| After P3-B | A bounded scripted specialist produces current structured evidence; a separately confirmed fake action is possible | Same-ID changed input conflicts; delayed stale A does not become B's answer |
| After P3-C | Execution succeeds or recovers independently of session lifetime; applicability remains explicit | Kill a process after compute/before acknowledgement; recover through P1 and preserve one logical result/effect |
| After P3-D | Static document extraction and fixed-policy analysis cite their evidence | Missing/adversarial input produces clarification or validation failure, not invented facts/tools |
| After P3-E | Conversation continues, revision changes, old result is marked historical and the current result follows the returning route | Ignore remote cancellation or close the room; retain the observed outcome and safely route applicable work |
| After P3-F | A short success/failure story followed by an inspectable comparison and standalone API example | Show raw evidence and limits rather than a blanket claim that remote specialists are always faster |

### Telemetry rules

- Use native SDK session and turn metrics and reports before custom
  instrumentation.
- Add P3 spans only at delegation, invocation, result, applicability and delivery
  boundaries.
- Bound exporter queues, retry and shutdown. Collector failure cannot block
  acceptance or conversation.
- Client-observed audio timings and agent-side emission are different
  measurements.
- IDs belong in safe logs and spans, not in unbounded metric dimensions.

## Commands and task handoff

### Verification commands

Run meaningful scoped assertions and the maintained fast and frontend checks. The
[root instructions](../../AGENTS.md) list the repository verification commands.
Actual PostgreSQL and process schedules need owned barriers, exact identity and
effect truth, and cleanup.

### Task packet example

Apply these rules to the next P3 task:

| Stage | Rule |
| --- | --- |
| Before starting | Create the task from the [work-item template](../work-items/template.md) |
| Before starting | Read the [project instructions](../../projects/delegation-reliability/AGENTS.md), the [shared design](../../Design.md), the charter and the existing producer and consumer tests |
| Before starting | Preserve the completed selected P3-I15 standalone assertions in [work item 0038](../work-items/0038-case-rehydration-and-standalone-release.md) |
| Before starting | Preserve the P3-I11 refresh and retention, the P3-I12 protected-action schedules, the P3-I13 temporal proof and P3-I14's source and installed process recovery, recorded in the [completed handoff](../work-items/0037-playback-evidence-and-process-recovery.md) |
| While implementing | Retain the qualified Python and npm artifacts and their explicit local adapters, then map the remaining standalone release assertions before broadening qualification |
| While implementing | Use the declared P1 public execution, case and delivery surfaces and isolated installations; no checkout product path or sibling store import may supply missing runtime code |
| While implementing | Keep the cancellation request, the remote acknowledgement, the stored result truth and the current applicability separate |
| While implementing | Exact caller confirmation and P1's protected transaction remain required; packaging cannot create another execution owner or renew permission |
| At handoff | Register a full acceptance row only when its entire normative inventory executes |
| At handoff | Retain the commands, observed results, review findings and remaining work, without treating a selected phase as full release |
