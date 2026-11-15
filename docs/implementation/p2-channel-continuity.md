# P2 Channel Continuity Kit implementation plan

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Break P2, the Channel Continuity Kit, into bounded implementation tasks with prerequisites, estimates and evidence |
| Audience | Engineers and coding agents who choose the next P2 task, check its prerequisites or record its evidence |
| Scope | Phases P2-A to P2-E, tasks P2-I01 to P2-I22 and their acceptance traceability; excludes P2 requirements and shared tasks |
| Owns | P2 task decomposition, phase gates, effort sizing and per-task handoff |
| Related | [P2 charter](../projects/channel-continuity-scope.md) · [Granular roadmap](../implementation-plan.md) · [Build plan](../build-plan.md) · [P2 project instructions](../../projects/channel-continuity/AGENTS.md) |

## Purpose and authority

This plan breaks P2, the Channel Continuity Kit, into bounded implementation tasks.
It is for engineers and coding agents who choose the next P2 task, check its
prerequisites or record its evidence. P2 is one independently usable TypeScript
continuity package with its gateway, a Python LiveKit adapter and a browser
example.

### Contents

| Section | What it covers |
| --- | --- |
| [Current status](#current-status) | What has passed and what remains open |
| [Starting point and dependencies](#starting-point-and-dependencies) | The foundation to reuse, the boundary decisions and the cross-project dependencies |
| [Planning and completion rules](#planning-and-completion-rules) | Task sizing, engineering gates, what a task can claim and parallel work |
| [Phases and tasks](#phases-and-tasks) | Phases P2-A through P2-E, each with its status, entry conditions, task table, task details, exit criteria and UI and signal requirements |
| [Acceptance traceability](#acceptance-traceability) | The primary task for each acceptance ID |
| [Demonstrations and signals](#demonstrations-and-signals) | Demonstration checkpoints and the required telemetry, errors and data decisions |
| [Commands and task handoff](#commands-and-task-handoff) | Existing commands, the runner policy and a task packet example |

### Authority

| Document | Owns |
| --- | --- |
| [P2 charter](../projects/channel-continuity-scope.md) | The P2 requirements and acceptance IDs |
| [Build plan](../build-plan.md) | The PLAN work-package sequence, including PLAN-12 through PLAN-16 |
| [Granular roadmap](../implementation-plan.md) | The shared tasks and the cross-project execution gates |
| [Shared design](../../Design.md) | Shared data flow, state authority, interfaces and failure boundaries |
| [Validation plan](../validation-plan.md) | Test lanes, required fault scenarios, benchmarks and evidence |
| [Observability contract](../observability.md) | Signals, safe errors, cardinality and operational evidence |
| [Demo plan](../demo-plan.md) | Capability demonstrations and honest observable UI transitions |

- This plan does not redefine the charter or create acceptance IDs.
- This plan decomposes PLAN-12 through PLAN-16 from the build plan.
- This plan is subordinate to the granular roadmap.
- The shared design, validation plan, observability contract and demo plan
  remain authoritative for their subjects.

### How to read the task tables

Each phase lists its tasks in one table with these columns:

| Column | Meaning |
| --- | --- |
| Task | The implementation task ID |
| PLAN | The build-plan work package that the task implements |
| Prerequisites | The tasks, shared tasks (S-I IDs) or contracts that must exist first |
| Acceptance | The acceptance IDs that the task contributes assertions to |
| Estimate | The planning estimate in engineering hours |
| Status | The recorded implementation status |
| Evidence | The work item that records the gate results |

The [granular roadmap](../implementation-plan.md) defines the shared S-I tasks.
"Completed (selected scope)" means the task's selected gates passed. It never
means that a charter acceptance row passed.

The task details below each table give the concrete deliverable, the required
failure assertion and, where recorded, status notes with the qualification counts
and remaining limits.

## Current status

P2-I01 through P2-I21 completed their selected gates. P2-I22 remains the release
frontier. All seventeen complete charter rows, P2-01 through P2-17, remain planned
and unregistered until their actual assertions pass. The harness catalog stays at
fifty-five definitions with twenty-four registered runners.

| Phase | Tasks | Task status | Evidence |
| --- | --- | --- | --- |
| [P2-A](#phase-p2-a-contract-and-standalone-durable-intake) | P2-I01 to P2-I06 | Completed (selected scope) | [0022](../work-items/0022-p2-channel-contracts.md), [0024](../work-items/0024-p2-verified-durable-intake.md), [0026](../work-items/0026-p2-postgres-inbox.md), [0027](../work-items/0027-p2-standalone-and-p3-http.md) |
| [P2-B](#phase-p2-b-recoverable-dispatch-and-revision-safe-case-routing) | P2-I07 to P2-I11 | Completed (selected scope) | [0028](../work-items/0028-p2-dispatch-and-p3-coordinator.md), [0029](../work-items/0029-p2-gateway-and-p3-issued-execution.md), [0030](../work-items/0030-p2-agent-recovery-and-p3-completion.md), [0031](../work-items/0031-revision-routing-and-delegation-acceptance.md), [0032](../work-items/0032-linked-confirmation-and-result-projections.md) |
| [P2-C](#phase-p2-c-outbound-delivery-with-explicit-uncertainty) | P2-I12 to P2-I14 | Completed (selected scope) | [0033](../work-items/0033-outbound-replies-and-completion-processing.md), [0034](../work-items/0034-callback-evidence-and-applicability-refresh.md), [0035](../work-items/0035-send-policy-and-action-races.md) |
| [P2-D](#phase-p2-d-native-livekit-voice-and-text-continuity) | P2-I15 to P2-I18 | Completed (selected scope) | [0036](../work-items/0036-native-input-and-deadline-cancellation.md), [0037](../work-items/0037-playback-evidence-and-process-recovery.md), [0038](../work-items/0038-case-rehydration-and-standalone-release.md) |
| [P2-E](#phase-p2-e-capacity-packaging-operability-and-release) | P2-I19 to P2-I22 | P2-I19 to P2-I21 completed (selected scope); P2-I22 open | [0039](../work-items/0039-bounded-channel-workloads-and-image-evidence.md), [0040](../work-items/0040-operations-ui-and-fixed-policy-evidence.md), [0041](../work-items/0041-standalone-channel-and-durable-policy.md), [0043](../work-items/0043-stable-result-delivery-and-return-context.md), [0044](../work-items/0044-origin-bound-channel-policy.md) |

### Open work

- P2-I22 remains the release frontier. Joined native voice, text and SMS,
  restart and discovery, applicable provider runs and the video retain their later
  gates.
- All seventeen complete acceptance rows and P2-I22 remain separately gated.
- This plan remains active. Unimplemented tasks and all full project acceptance
  rows remain pending. Phase completion requires the actual exit evidence in each
  phase.

### Related P3 checkpoint

P3-I18B's separate native real-time communication (RTC) text application passed
selected source and installed qualification in
[0042](../work-items/0042-responsive-native-policy-and-compact-demo.md).

## Starting point and dependencies

### Existing foundation

The pinned TypeScript toolchain, the browser software development kit (SDK), the
diagnostic console, the Compose stack, API metrics and the documentation and
structural harness already exist. Reuse them.

The console's current echo and M1 intake (the existing confirmed-investigation
intake) are foundation capabilities. They are not a P2 message inbox, channel
history, association service or business acceptance path.

### Boundaries

Each boundary records a required decision:

| Boundary | Decision | Consequence |
| --- | --- | --- |
| Case authority | Exactly one authority owns the current revision and the confirmed facts | A small standalone adapter implements the same port; integrated mode uses the shared authority rather than copying its store |
| Message persistence | P2 owns the inbox, processing intents, reply outbox, provider attempts and communication evidence | P2 does not own supplier execution or P3 specialist scheduling |
| Business operation | The fake standalone operation port and the P1 integration preserve a stable logical operation identity | Processing or model invocation can repeat; business acceptance cannot silently duplicate |
| Trusted identity | Verified provider integration scope and verified end-user account scope are distinct | A JSON tenant, a sender number or a familiar room name grants no case access |
| Media | LiveKit owns rooms, tracks, text streams, transcription synchronization and interruption | P2 records source-qualified evidence and adds durable acceptance and history |
| Storage and runtime | Reuse the local PostgreSQL infrastructure with P2-owned migrations, a P2 store adapter and bounded connections | Pin a compatible TypeScript database client when one is introduced |

Do not add Redis, Kafka, Cloud, a real carrier or Node Agents merely for HTTP or
message handling.

### Dependencies

| Dependency | What must exist | Needed by |
| --- | --- | --- |
| P1 case and operation contracts | Agreed versions of the `CaseAuthorityPort` and the operation identity fixtures | Contract and fake-carrier work, which may begin while P1 implementation continues and does not require the full P1 deployment |
| P1 authority contract | The P1 PLAN-04 authority contract | Integrated case and confirmation tests |
| P1 completion contract | P1's durable completion contract | P1 result delivery |
| Media lane | The PLAN-11 conversational agent and a permission-qualified local media lane | Actual browser voice and playback |
| P3 | Never a dependency of P2 | Not applicable |

### User interface approach

- Keep the current TypeScript console and the native browser SDK as the default
  UI.
- Evaluate official Agents UI components only when a real product conversation
  surface warrants them. A React rewrite is not a prerequisite.
- Build the authorized timeline and history as a durable GET/cursor projection
  with bounded polling and replay-safe rendering.
- Do not add a bespoke WebSocket transport or a parallel event bus.
- A source event enters one acceptance path before any projection consumes it.

## Planning and completion rules

### Task IDs and estimates

- Task IDs P2-I01 through P2-I22 identify implementation slices, not test
  outcomes.
- Estimates are provisional engineering hours, including the slice's targeted
  tests, documentation and first review. They are not elapsed-time promises.
- Split a task when its failure schedule or interfaces no longer fit one
  reviewable change.
- Re-estimate after the first real gateway crash and the first browser audio run.
- Study, setup failures and subsequent review work consume the shared weekly
  budget.

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

- Register a P2 ID only when every assertion in its charter row exists, not merely
  because one related task passed.
- Phase completion requires the actual exit evidence in each phase.

### Parallel work

- Keep one primary feature slice active.
- Parallel work may prepare fixtures, review an API or implement a clearly frozen
  adapter.
- Two agents must not invent different case revisions or confirmation semantics.

## Phases and tasks

### Phase P2-A: contract and standalone durable intake

**Phase status:** all six tasks completed their selected gates. P2-I01 and P2-I02 passed
their bounded first-slice gates in the
[slice work item](../work-items/0022-p2-channel-contracts.md). P2-I03 through
P2-I05 are recorded in the
[verified-intake](../work-items/0024-p2-verified-durable-intake.md) and
[PostgreSQL inbox](../work-items/0026-p2-postgres-inbox.md) work items. The
[P2-I06 standalone work item](../work-items/0027-p2-standalone-and-p3-http.md)
adds the public example and new-process replay.

**Entry:**

- The root toolchain is frozen.
- An agreed version of the shared case and operation ports exists.
- The current M1 and transport baseline is available.

No P2 executable is assumed.

| Task | PLAN | Prerequisites | Acceptance | Estimate | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P2-I01 | PLAN-12 | Agreed CaseAuthorityPort and operation-identity contract | P2-02, P2-12 | 2–4h | Completed (selected scope) | [0022](../work-items/0022-p2-channel-contracts.md) |
| P2-I02 | PLAN-12 | P2-I01 | P2-02, P2-12 | 2–4h | Completed (selected scope) | [0022](../work-items/0022-p2-channel-contracts.md) |
| P2-I03 | PLAN-12 | P2-I01, P2-I02 | P2-12 | 2–4h | Completed (selected scope) | [0024](../work-items/0024-p2-verified-durable-intake.md) |
| P2-I04 | PLAN-12 | P2-I02, P2-I03; S-I05 applied to P2 schema/grants | P2-01, P2-03 | 3–5h | Completed (selected scope) | [0024](../work-items/0024-p2-verified-durable-intake.md), [0026](../work-items/0026-p2-postgres-inbox.md) |
| P2-I05 | PLAN-12 | P2-I04 | P2-01, P2-02 | 2–4h | Completed (selected scope) | [0024](../work-items/0024-p2-verified-durable-intake.md), [0026](../work-items/0026-p2-postgres-inbox.md) |
| P2-I06 | PLAN-12/13 | P2-I03, P2-I05 | P2-16 foundation | 2–4h | Completed (selected scope) | [0027](../work-items/0027-p2-standalone-and-p3-http.md) |

**Task details:**

- **P2-I01**
  - Deliverable: freeze the version-1 event discriminants, the exported
    principal, receipt, history and error types, scoped identities and semantic
    canonicalization rules under the project source boundary. Record the contract
    decision.
  - Required failure assertion: an unsupported version, an oversized variant and
    a forged body scope fail before acceptance. Two distinct messages with
    identical text remain distinct.
- **P2-I02**
  - Deliverable: add language-neutral valid and invalid fixtures under contracts,
    runtime TypeScript validation and a narrow Python decoder for the adapter
    boundary. Define which retry metadata is excluded from semantic identity.
  - Required failure assertion: both languages agree on unsupported versions,
    unknown variants, scope errors and changed destinations. A metadata-only retry
    does not conflict.
- **P2-I03**
  - Deliverable: implement fake-carrier signature verification and a
    seeded-account association adapter. Only the trusted adapter attaches
    `AccountScope`. Define bounded single-use challenges, association versions and
    revocation, and a local credential and principal configuration contract.
  - Required failure assertion: an invalid signature, a forged association,
    another tenant or case and an unassociated sender cannot read, write or route
    case data. Also reject expired or reused challenges and revoked or reassigned
    identities. Race challenge consumption atomically and permit a valid new
    association. Verify these failures independently.
- **P2-I04**
  - Deliverable: add versioned P2-owned PostgreSQL inbox, receipt and
    processing-intent migrations and atomic accept-before-acknowledgement. Persist
    the original acceptance sequence per tenant, account and conversation. Keep
    provider occurrence time and server receipt time distinct. Provide bounded
    inspect and history queries.
  - Required failure assertion: a failure before commit produces no accepted
    receipt. A loss after commit is reconciled by the original identity. Existing
    accepted records remain inspectable at admission capacity.
- **P2-I05**
  - Deliverable: implement scoped concurrent replay and conflict tests and
    canonical-payload tests. Decide provider replay horizons, receipt and delivery
    tombstones and expired-identity behavior before any cleanup.
  - Required failure assertion: concurrent equal events yield one logical
    message. Changed semantics conflict. A metadata-only retry deduplicates.
    Pruning display history does not permit late duplicate acceptance.
- **P2-I06**
  - Deliverable: add the first standalone fake-carrier example with narrow case,
    scripted-agent and operation adapters. Wire the P2 workspace package, explicit
    test discovery and the smallest real harness runners.
  - Required failure assertion: run with no P1/P3 service present. An omitted
    adapter or setup, or a zero-test runner, fails explicitly. Do not mistake
    existing root console tests for P2 coverage.

**Migration rules:**

- Run P2-owned migrations through the S-I05 one-shot migration principal and its
  versioned configuration upgrade. Shared task S-I05 is defined in the
  [granular roadmap](../implementation-plan.md).
- Serving roles retain only the required runtime permissions. They cannot create
  schemas or receive bootstrap administrator secrets.
- Test preserved-volume and repeated upgrades before accepting inputs.

**Exit:**

- The standalone example accepts a synthetic message, returns a durable receipt
  and replays it under a new process.
- Concurrent deduplication and trust negatives have executable evidence.
- P2-16 is only partial here. Full history, delivery and recovery and isolated
  package installation still follow.

**UI and signals:**

- The current P2-I06 CLI shows committed acceptance followed by replay of the same
  receipt, operation key and sequence, with a pending/`not_executed` preview.
- The planned browser projection must show pending to accepted only after receipt
  validation, the same receipt on repetition and an actionable typed rejection.
- That browser proof belongs to the later gateway and UI integration. CLI proof
  cannot qualify a browser or modality assertion.

### Phase P2-B: recoverable dispatch and revision-safe case routing

**Phase status:** all five tasks completed their selected gates. The evidence for each
task is linked from the table.

**Entry:**

- The Phase P2-A accepted-message and store contract exists.
- The standalone authority must share the real authority's revision and
  confirmation fixtures.
- Integrated tests wait for PLAN-04 rather than inventing a second truth model.

| Task | PLAN | Prerequisites | Acceptance | Estimate | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P2-I07 | PLAN-13 | P2-I06 | P2-03, P2-13 foundation | 2–4h | Completed (selected scope) | [0028](../work-items/0028-p2-dispatch-and-p3-coordinator.md) |
| P2-I08 | PLAN-13 | P2-I07 | P2-03 | 2–4h | Completed (selected scope) | [0029](../work-items/0029-p2-gateway-and-p3-issued-execution.md) |
| P2-I09 | PLAN-13 | P2-I08 | P2-04 contribution | 2–4h | Completed (selected scope) | [0030](../work-items/0030-p2-agent-recovery-and-p3-completion.md) |
| P2-I10 | PLAN-13 | P2-I06; shared authority fixtures from PLAN-04 | P2-05 contribution; full P2-12 remains later | 3–5h | Completed (selected scope) | [0031](../work-items/0031-revision-routing-and-delegation-acceptance.md) |
| P2-I11 | PLAN-13 | P2-I10 | P2-06 | 2–4h | Completed (selected scope) | [0032](../work-items/0032-linked-confirmation-and-result-projections.md) |

**Task details:**

- **P2-I07**
  - Deliverable: bounded per-receipt dispatch and lookup-only reconciliation under
    explicit owner-upgraded v2 claims and attempts and an immutable prepared
    investigation. Cooperating operation acceptance remains external. Gateway
    deployment follows P2-I08.
  - Required failure assertion: slow or ignored adapters retain owned capacity.
    Stale epochs cannot publish. An unknown acknowledgement preserves uncertainty
    and the original key.
  - Status notes: the [P2-I07 phase](../work-items/0028-p2-dispatch-and-p3-coordinator.md)
    adds an explicit owner-only inbox schema v2 upgrade, persisted bounded claims
    and attempts, frozen investigation input and lookup-only reconciliation
    against a cooperating operation port. A possible external call never returns
    to a `not_executed` state. The old standalone preview rejects nonpending
    inputs. The actual PostgreSQL takeover and the external-commit kill and
    reconciliation are selected slice evidence, not a complete product row.
- **P2-I08**
  - Deliverable: a real bounded loopback gateway and a trusted failpoint after the
    accepted acknowledgement and before dispatch. Restart polls the same persisted
    eligible state.
  - Required failure assertion: accepted input is dispatched after restart.
    Repeated recovery cannot create another logical business acceptance. Include
    the normal live path.
  - Status notes: the
    [P2-I08 phase](../work-items/0029-p2-gateway-and-p3-issued-execution.md) adds
    the actual bounded gateway, durable eligible polling and a process restart
    proof after acknowledgement. Selected owned-process gates inspect the original
    history.
- **P2-I09**
  - Deliverable: an explicit owned-process scripted agent adapter, a bounded
    framed worker helper and an independent worker-kill and replay fixture.
  - Required failure assertion: a live gateway preserves the original input, case
    and operation through worker death and claim expiry. Repeated attempts are
    visible with one cooperating logical acceptance. Actual process, process-group
    and pipe ownership must settle before capacity is released.
  - Status notes: the
    [P2-I09 phase](../work-items/0030-p2-agent-recovery-and-p3-completion.md) adds
    an explicit trusted agent-process adapter and framed worker helper. It
    preserves input, case and operation identity through independently killed
    scripted-worker replay. A live gateway observes claim expiry and repeated
    attempts while the cooperating operation accepts one logical investigation.
    The selected phase gates passed, completing P2-I09. The native LiveKit adapter
    is separately qualified within the selected P2-I15/I16 scope.
- **P2-I10**
  - Deliverable: a strict structured investigation router and
    one-selected-authority ports. The selected authority is either the
    owner-installed standalone reference PostgreSQL store or the public P1
    expected-revision compare-and-set (CAS) authority, reached through explicit
    loopback application composition.
  - Required failure assertion: observe real blocking graphs and one winning
    revision despite skewed timestamps. Valid current input progresses. A lost
    acknowledgement (ACK) stays unknown, with no receipt inference or rebase.
    Retained inbox access does not fence current association revocation.
  - Status notes: P2-I10 adds the explicit structured-command router, the
    standalone reference authority and the public-P1 loopback application bridge.
    The selected 22-case equivalent-authority gate and the final phase checks
    passed, completing P2-I10.
- **P2-I11**
  - Deliverable: immutable quote, revision and prompt bindings, linked user
    confirmation and clarification for ambiguous or unlinked replies.
  - Required failure assertion: an old-revision confirmation cannot authorize the
    current mutation. An unlinked SMS "yes" asks for clarification, while a valid
    current linked confirmation can progress.
  - Status notes: the
    [linked-confirmation phase](../work-items/0032-linked-confirmation-and-result-projections.md)
    completed P2-I11 with immutable prompt bindings, exact P1 confirmation,
    explicit original receipt replay and a current-association preflight. Its
    18-case actual integration gate, installed npm gate and final phase gates
    passed. Current sender eligibility is a separate preflight, not an atomic
    cross-authority association-revocation commitment fence.

**Exit:**

- Gateway and agent failure scenarios use actual independent processes, not a
  reopened database connection.
- The operation adapter records one logical acceptance under replay.
- Current and stale confirmations are distinguished without using provider
  timestamps as a universal order.

**UI and signals:**

- One case snapshot shows the winning revision.
- The losing or ambiguous input retains its own receipt and explanation.
- Attempt history may show reprocessing. It cannot be presented as another
  accepted booking operation.

### Phase P2-C: outbound delivery with explicit uncertainty

**Phase status:** all three tasks completed their selected local gates. Automatic
booking-completion integration remains separate.

**Entry:**

- Durable input identities, trusted association and the reply-intent contract
  exist. This phase may proceed alongside media work after these interfaces are
  frozen.
- Automatic integration needs a separately published P1 or application completion
  handoff. The current result-only delegation feed is not that handoff.
- The implemented outbox consumes an explicit trusted application reply intent
  and never reads P1 store internals.

| Task | PLAN | Prerequisites | Acceptance | Estimate | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P2-I12 | PLAN-14 | P2-I07, P2-I10; agreed result-delivery contract | P2-10 foundation, P2-16 | 2–4h | Completed (selected scope) | [0033](../work-items/0033-outbound-replies-and-completion-processing.md) |
| P2-I13 | PLAN-14 | P2-I03, P2-I12 | P2-10, P2-12 | 2–4h | Completed (selected scope) | [0034](../work-items/0034-callback-evidence-and-applicability-refresh.md) |
| P2-I14 | PLAN-14 | P2-I13 | P2-11 | 2–4h | Completed (selected scope) | [0035](../work-items/0035-send-policy-and-action-races.md) |

**Task details:**

- **P2-I12**
  - Deliverable: immutable-recipient reply intents, a stable outbound identity, a
    versioned authorized route and suppression reservation, and bounded attempts
    in owner-upgraded inbox v3.
  - Required failure assertion: a crash after reply-intent commit leaves
    recoverable work. A revocation or suppression that wins before reservation
    prevents a new call. Later changes cannot retract an admitted call or disclose
    another recipient. A newly verified route for the same recipient progresses.
    Reassignment cannot transfer ownership.
  - Status notes: outbound replies completed their selected local gates. The
    24-case actual gate, populated upgrade, restore and replay, an isolated
    ordinary fake-send consumer and the final phase gates passed, completing
    P2-I12. Automatic booking-completion integration remains separate.
- **P2-I13**
  - Deliverable: authenticated callback intake with a 60-second envelope window,
    immutable exact-attempt observations and the deterministic fake-provider
    evidence reducer.
  - Required failure assertion: duplicate or reordered callbacks keep correct
    correlation. An obsolete callback cannot silently regress stronger evidence.
    Another account cannot submit or inspect the callback.
  - Status notes: P2-I13 adds authenticated correlated callback evidence and a
    conservative reservation veto within its selected scope. The 24-case source
    gate, the isolated installed consumer and the final phase gates passed,
    completing P2-I13. Retained callbacks veto a new reservation without
    retracting an already admitted call or authorizing a resend.
- **P2-I14**
  - Deliverable: an explicit uncertain-send policy. Ordinary unknown sends are
    held, and explicit cooperating same-key recovery uses distinct local attempts,
    in owner-only inbox schema v5.
  - Required failure assertion: the outcome becomes unknown rather than
    failed-for-retry. The UI or report never promises one physical SMS delivery
    when the provider cannot establish it. Route changes cannot retarget an
    already sent or uncertain attempt or its recipient. Include a definitive
    failure and an ordinary success.
  - Status notes: the explicit uncertain-send policy passed its selected source
    and installed gates. The selected 30-case gate, populated upgrade and restore,
    an isolated public npm consumer and the final local gates passed, completing
    P2-I14. Historical admission proofs survive late facts. Acceptance or conflict
    on any earlier operation vetoes new calls.

**Exit:**

- Logical notification identity, send attempts and provider evidence are separate
  records.
- Both certain and uncertain fake-provider outcomes are visible.
- All callbacks are scoped and validated.
- The retention policy preserves receipt and delivery protection independently of
  display-history pruning.
- The charter's verified-association, acceptance-sequence and immutable-recipient
  contracts are authoritative. Callbacks and route changes never rewrite an
  uncertain prior send.

**UI and signals:**

- A fake SMS changes from queued to sending to accepted-by-provider, delivered,
  definitively failed or unknown only as actual evidence warrants.
- None of these observations is labelled user acknowledgement or booking consent.

### Phase P2-D: native LiveKit voice and text continuity

**Phase status:** all four tasks completed their selected scope. The evidence for each
task is linked from the table.

**Entry:**

- The Phase P2-B routing and Phase P2-C delivery contracts exist.
- The actual PLAN-11 conversational agent and self-hosted media path exist.
- The existing diagnostic worker is reused as a baseline only. It is not a voice
  conversation adapter.
- Resolve microphone and audio-play permission before the corresponding browser
  check. A blocked or unavailable capability remains pending and cannot count as
  a pass.

| Task | PLAN | Prerequisites | Acceptance | Estimate | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P2-I15 | PLAN-15 | P2-I08, P2-I11; PLAN-11 conversational adapter | P2-15 | 3–5h | Completed (selected scope) | [0036](../work-items/0036-native-input-and-deadline-cancellation.md) |
| P2-I16 | PLAN-15 | P2-I15; qualified local audio fixture lane | P2-15 | 3–5h | Completed (selected scope) | [0036](../work-items/0036-native-input-and-deadline-cancellation.md) |
| P2-I17 | PLAN-15 | P2-I16; browser audio permission/control gate | P2-07, P2-08 | 3–6h | Completed (selected scope) | [0037](../work-items/0037-playback-evidence-and-process-recovery.md) |
| P2-I18 | PLAN-15 | P2-I11, P2-I14, P2-I17 | P2-09, P2-12 | 3–5h | Completed (selected scope) | [0038](../work-items/0038-case-rehydration-and-standalone-release.md) |

**Task details:**

- **P2-I15**
  - Deliverable: route committed browser text through P2 acceptance before
    dispatch to the Python agent. Integrate the installed SDK's native `lk.chat`
    path and disable the competing automatic consumption path for this adapter.
  - Required failure assertion: one committed browser input yields one logical
    acceptance and one business-operation identity. A transport retry or the
    default reply hook cannot create a second action.
  - Status notes: native text passed the selected actual six-group native gate
    and the isolated Python and npm artifact gates in the
    [completed phase](../work-items/0036-native-input-and-deadline-cancellation.md).
    The final regression and shared gates and the affected media rerun passed,
    completing this task within its selected native and artifact scope.
- **P2-I16**
  - Deliverable: add the Python adapter for committed voice utterances, native
    generation and interruption observations, and hybrid text and audio. Raw media
    stays in tracks. Interim transcripts remain observations.
  - Required failure assertion: text and audio together use the same application
    acceptance boundary. Interim text or repeated transcription events cannot grant
    confirmation or create duplicate accepted work.
  - Status notes: committed voice passed the same selected six-group native gate,
    isolated artifact gates, final regression and shared gates and affected media
    rerun as P2-I15, completing this task within its selected native and artifact
    scope.
- **P2-I17**
  - Deliverable: source-qualified response, generated-text, SDK and browser
    observations and scoped-interruption qualification.
  - Required failure assertion: interrupt output halfway and retain partial and
    native interruption evidence. Disconnect before playback evidence and retain
    an unknown completion. Generated full text never becomes proof of full
    playback.
  - Status notes: the
    [I17 handoff](../work-items/0037-playback-evidence-and-process-recovery.md)
    implements source-qualified generated text, SDK progress, response-scoped
    interruption and client-reported playback through an explicit owner-only
    inbox schema v7 upgrade. The sixteen-case PostgreSQL storage gate, the
    three-group actual browser and media gate, the isolated public npm consumer and
    the current eight-payload Python package with ninety-four unadapted tests
    passed, together with 147 P2 compatibility assertions. This completes selected
    P2-I17 qualification. The linked handoff records the results and the separate
    final shared phase closure.
- **P2-I18**
  - Deliverable: a current-grant read-only context, public P1 and reference
    adapters, optional SDK initialization and idle refresh, and a source-separated
    UI.
  - Required failure assertion: a new room or channel resumes the same verified
    case and current revision. Stale summaries and unassociated senders cannot
    override or disclose authoritative facts.
  - Status notes: P2-I18 completed its selected verified current-case room and
    channel rehydration gates in the
    [handoff](../work-items/0038-case-rehydration-and-standalone-release.md).
    Eighteen storage assertions, three actual voice, text, SMS and new-room browser
    groups, a nine-payload Python distribution with 111 unadapted tests, a
    96-payload installed npm consumer with seven stages and 166 compatibility
    assertions passed with complete cleanup.
  - Limits: native loading and source facts remain separate non-atomic as-of
    observations that grant no command authority. Loaded P1 revision 0 stays
    read-only under the existing positive-revision native command contract. Changing
    that domain requires its own versioned work before integrated release.

**Exit:**

- The required local browser example performs real voice interruption and room
  closure and resumption.
- The text and audio route has one logical acceptance path.
- A normal text test or a native-SDK audio counter is insufficient to close the
  browser playback cases.
- Scripted speech establishes transport and evidence semantics, not real model
  quality.

**UI and signals:**

- Channel lanes share a stable case identity, while room and route identities
  change.
- The timeline distinguishes accepted user input, generated response, reported
  playback, carrier delivery and acknowledgement.
- Missing data shows unknown. Switching a tab never fabricates a completed
  communication.

### Phase P2-E: capacity, packaging, operability and release

**Phase status:** P2-I19, P2-I20 and P2-I21 completed selected qualification. P2-I22
remains the release frontier, with its 0043 and 0044 prerequisites completed.

**Entry:**

- The normal and failure paths of Phases P2-A through P2-D exist.
- Complete the standalone gates independently of a running P1/P3 deployment.
  Integrated tests use the public P1 operation and authority contracts.
- P2-I21's isolated fake-carrier package proof may start earlier, after its listed
  prerequisites. Rerun it at release after P2-I18. This does not relax the final
  actual-media continuity gate.

| Task | PLAN | Prerequisites | Acceptance | Estimate | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P2-I19 | PLAN-16 | P2-I08, P2-I14, P2-I18 | P2-13, P2-14 | 3–5h | Completed (selected scope) | [0039](../work-items/0039-bounded-channel-workloads-and-image-evidence.md) |
| P2-I20 | PLAN-16 | P2-I14, P2-I18; existing observability contract | P2-13 support, P2-17 support | 2–4h | Completed (selected scope) | [0040](../work-items/0040-operations-ui-and-fixed-policy-evidence.md) |
| P2-I21 | PLAN-16 | P2-I06, P2-I11, P2-I14; real text consumer boundary | P2-16 | 3–5h | Completed (selected scope) | [0041](../work-items/0041-standalone-channel-and-durable-policy.md) |
| P2-I22 | PLAN-16/22 | P2-I19, P2-I20, P2-I21; integrated P1 public-port adapter | P2-17; all P2 release checks | 3–5h | Open; 0043 and 0044 prerequisites completed | [0043](../work-items/0043-stable-result-delivery-and-return-context.md), [0044](../work-items/0044-origin-bound-channel-policy.md) |

**Task details:**

- **P2-I19**
  - Deliverable: a seeded steady, burst and saturation study and a 1,000-case
    dormancy study, fixed premeasurement budgets, bounded ordinary observer
    callbacks, actual shutdown and fresh-process restart, and populated restore.
  - Required failure assertion: bound admitted work and queues, and reject or
    defer explicitly before acceptance. Every accepted item stays inspectable.
    Many dormant cases allocate no per-case room or agent. Include late replay
    after history pruning.
  - Status notes: the capacity and dormant-case experiments passed selected
    qualification in the
    [completed handoff](../work-items/0039-bounded-channel-workloads-and-image-evidence.md).
    The workload's actual PostgreSQL, HTTP, restart and restore gates and its
    installed package gates passed within the selected scope. They make no
    production capacity, per-case RAM or general fairness claims.
  - Frozen study parameters: the handoff freezes the values in the P2-I19 study
    parameters table after these task details. Accepted rows remain inspectable.
    Display eviction reclaims no replay capacity. `make p2-workload-plan` exposes
    the inventory.
- **P2-I20**
  - Deliverable: read-only GET, cursors and UI, real finite producer, metric and
    span integration, typed read errors and retained ownership.
  - Required failure assertion: telemetry export failure cannot block intake or
    create unbounded work. Identifiers do not become metric labels. Pending,
    unknown and error transitions follow observations, with no timed fake
    progress.
  - Status notes: the joined operational UI and telemetry passed selected
    qualification in
    [0040](../work-items/0040-operations-ui-and-fixed-policy-evidence.md).
    Sixteen actual PostgreSQL and HTTP groups plus three browser groups, an
    isolated npm consumer with 105 payloads across seven stages and 187 current
    compatibility assertions passed. Full charter rows remain separate.
- **P2-I21**
  - Deliverable: an additive public starter factory and bin, closed private
    configuration, explicit owner bootstrap and a quiescent mutation lifecycle.
  - Required failure assertion: no repository-internal imports, sibling service
    deployment or undeclared dependency is needed. A missing export or adapter
    fails visibly. Full standalone case routing, history, fake delivery and
    recovery pass.
  - Status notes: the explicit installed starter application and the separate
    public-P1 consumer completed selected installed-application qualification in
    [0041](../work-items/0041-standalone-channel-and-durable-policy.md). Twenty
    isolated fake-carrier (standalone) assertions and six separate installed
    public-P1 assertions passed. The application receipt ledger is synthetic
    external evidence, not workflow or supplier authority.
  - Application rules:
    - Route the explicit accepted structured input while quiescent, before
      serving.
    - The session mutex excludes concurrent mutating commands and a live gateway
      across processes. Reads remain available.
    - Original send acknowledgements stay unknown when a separately sourced
      lookup later reports provider acceptance.
    - Ordinary unknown sends receive no automatic resend permission.
    - The read-only operations page grants no mutation controls.
    - The current-case contract remains non-atomic and as of its observations.
      P1 revision 0 is readable, while integrated or native execution at revision
      0 needs its own coherent versioned work.
- **P2-I22**
  - Deliverable: complete the fresh-agent handoff, the API and failure-contract
    review, all P2 local assertions, supported-platform evidence and labelled
    real-model portfolio runs. Record defects and final demonstrations.
  - Required failure assertion: a fresh agent finds the contracts and checks
    using repository instructions alone. Missing, skipped or timed-out cases keep
    the gate incomplete. Scripted or Cloud text runs cannot substitute for required
    local audio evidence.
  - Completed prerequisite, stable result reads: the completed
    [0043 handoff](../work-items/0043-stable-result-delivery-and-return-context.md)
    qualifies P2's v8 receiver and current-channel result data reads and P3
    backend v2 delivery. Sixteen storage and four return actual source assertions
    passed, plus a separate twenty-five-stage offline package lane. These reads do
    not qualify RTC media.
  - Completed prerequisite, original-input binding: the completed
    [0044 work item](../work-items/0044-origin-bound-channel-policy.md) implements
    the optional original-origin application prerequisite. It provides typed
    P2-input to P1-work binding, schema version 3 facades, a narrow operation
    client and local application HTTP. Focused unit and socket checks and isolated
    package and fake-port qualification passed. Its fourteen selected actual
    source assertions passed. The adapter does not make P3 a dependency of the
    standalone P2 package. It retains original input identities in existing
    P1-owned work, and the raw message stays in P2.
  - Remaining: P2-I22 remains the release frontier. Joined native voice, text and
    SMS, the integrated native handoff, restart and discovery, applicable provider
    runs and the video retain their later gates. Complete P2-I22 and the charter
    release gates remain planned after the selected standalone qualification.

**P2-I19 study parameters:**

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Seed | 39 | P2-I19 workload | Frozen by the handoff |
| Retained capacity-study inputs | 64 | Capacity study | Separate retained limit, frozen by the handoff |
| Retained dormant-study inputs | 1,024 | Dormancy study | Separate retained limit, frozen by the handoff |
| Dormant samples | 0/64/256/1,000 cases | Dormancy study | Frozen by the handoff |
| Public bounded setup and read windows | 64 | Public setup and reads | Stay at this bound |

**Release exits:**

| Release exit | Requirement |
| --- | --- |
| Local-ready V1 | All 17 P2 rows have passing executable evidence in their required local lanes |
| Local-ready V1 | The standalone and integrated examples, migrations and restart, the installed consumer and the bounded-load results are reviewed |
| Local-ready V1 | Real SMS and Cloud are not prerequisites |
| Portfolio-ready V1 | Add selected real-model voice and text runs, checked outcomes, configuration and costs, a short success and failure demo and reviewed benchmark evidence |
| Portfolio-ready V1 | Re-estimate rather than weakening a mandatory assertion |

## Acceptance traceability

A task references the requirements it advances. The primary task below identifies
the final proof owner. The charter remains authoritative for the complete
assertion.

| Acceptance ID | Implementation tasks | Required final evidence |
| --- | --- | --- |
| P2-01 | P2-I05 | Scoped concurrent replay produces one accepted message and original receipt |
| P2-02 | P2-I05 | Semantic conflict, metadata-only retry and distinct identical-text events |
| P2-03 | P2-I08 | Gateway killed after acknowledgement, then independent-process recovery |
| P2-04 | P2-I09 | Agent termination/replay with visible attempts and stable business acceptance |
| P2-05 | P2-I10 | Controlled competing-channel revision race plus valid progress |
| P2-06 | P2-I11 | Stale/unlinked confirmation rejection or clarification, current linked progress |
| P2-07 | P2-I17 | Actual browser audio interruption preserves partial/native evidence |
| P2-08 | P2-I17 | Missing browser playback observation remains unknown |
| P2-09 | P2-I18 | Voice/chat/fake-SMS continuation after room closure |
| P2-10 | P2-I13 | Correlated duplicate/reordered callback history under the provider rule |
| P2-11 | P2-I14 | Non-idempotent send with lost response and explicit uncertain outcome |
| P2-12 | P2-I03 | Association/signature/account/case access negatives, repeated at each adapter boundary |
| P2-13 | P2-I19 | Bounded overload with inspectability of every accepted item |
| P2-14 | P2-I19 | Dormant-case resource study without permanently allocated rooms/agents |
| P2-15 | P2-I16 | Real hybrid input and custom durable acceptance without a second logical path |
| P2-16 | P2-I21 | Full isolated installed-consumer standalone example, no P1/P3 services |
| P2-17 | P2-I22 | Fresh coding-agent change and diagnosis using only documented harness/context |

P2-I10, P2-I13, P2-I15 and P2-I18 must extend P2-I03's access matrix to cover the
later reads, callbacks and routes. P2-12 cannot be closed permanently by checking
an early webhook path while later paths remain untested.

## Demonstrations and signals

### Demonstration checkpoints

Each checkpoint pairs a normal story with a controlled failure and its visible
recovery.

| Checkpoint | Normal story | Controlled failure and recovery |
| --- | --- | --- |
| P2-A receipt | Fake SMS becomes a durable accepted message | Replay concurrently; show one receipt and a changed-payload conflict |
| P2-B case | Current linked command advances a verified case | Kill gateway/agent or send an obsolete yes; recover accepted input and preserve current authority |
| P2-C delivery | Stable reply proceeds through fake provider observations | Lose send acknowledgement; show unknown without unsupported physical-delivery certainty |
| P2-D continuity | Voice to chat to fake SMS resumes the same current case | Interrupt or lose playback evidence; show partial/unknown instead of fabricated completion |
| P2-E release | Standalone installed package and integrated public-port consumer work | Saturate admission, restart containers and have a fresh agent diagnose a real failing scenario |

### Telemetry, errors and data decisions

Instrument each real producer when it is introduced, not with placeholder zero
counters. Record these observations:

| Area | Observations to record |
| --- | --- |
| Input | Accepted, deduplicated or conflicted |
| Dispatch | Pending, attempted or recovered |
| Case revision | Conflict or clarification |
| Outbound | Queued, attempted or unknown |
| Callback | Applied or retained |
| Route | Changed |
| Response and playback | Generated, interrupted, playback and acknowledgement observed |

Correlation and metric rules:

- Retain scoped correlation in safe logs and spans.
- Metric dimensions are finite channel, provider-kind, outcome and error-code
  values. They are never tenant, phone, case, room, message or response
  identifiers.
- Capture dispatch and queue lag, replay counts, delivery outcomes, resumption
  latency, active work and dormant resource use.

Error and data rules:

- Export typed validation, identity-conflict, association and access, revision
  and clarification, overload and unknown-outcome failures.
- Keep retries bounded by declared eligibility and deadlines. An unknown provider
  send cannot become a definitive failure merely to justify a retry.
- The standalone store and the installed artifact must document schema upgrade
  and restore, retention horizons and unsupported versions.
- Accepted receipt, case intent, supplier outcome, provider delivery and user
  acknowledgement remain separate facts in both the API and the UI.

## Commands and task handoff

### Existing commands

From the repository root, using its frozen environment, these commands exist now:

| Task | Command | Notes |
| --- | --- | --- |
| List the P2 catalog cases | `.venv/bin/python -m harness list --project p2` | Catalog listing |
| Run the P2 structural checks and tests | `HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh --module p2` | Passing does not certify planned product behavior |
| Run the P2 acceptance cases | `.venv/bin/python -m harness run --project p2` | Currently reports incomplete and exits with status 2 |

The same commands as one sequence:

```sh
.venv/bin/python -m harness list --project p2
HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh --module p2
.venv/bin/python -m harness run --project p2
```

The last command currently reports incomplete and exits with status 2.

### Runner policy

- Root pnpm checks discover the implemented console, the P2 channel package and
  the P3 specialist package, including source and test typing, tests, formatting
  and builds.
- Public examples are also included in maintained source boundaries and in format,
  build or executable-consumer checks.
- Each new slice extends actual discovery and its relevant runner with the exact
  working directory, prerequisites, timeout, isolated state and artifact paths.
- Full P2 charter runners remain pending. Preserve missing P2 IDs as non-passing.
- Root and shared-contract changes require the full fast lane and the affected
  cross-language checks, not only a focused structural pass.

### Task packet example

Example packet for P2-I08:

| Packet field | P2-I08 example |
| --- | --- |
| Slice | P2-I08, gateway recovery |
| Inputs | This phase, the accepted receipt, store and dispatch contracts from P2-I04 and P2-I07, and the P2-03 charter row |
| Owned paths | P2 source and tests, plus the smallest necessary harness registration |
| Deferred | New carrier channels, model inference, P1 supplier logic and browser playback |

Before writing code, record a work item with:

- the exact barrier after acknowledgement and before dispatch;
- the gateway and child process owners;
- the persistent fixture store;
- the expected original message and operation identities;
- the cleanup deadline.

Then:

1. Implement the ordinary path.
2. Terminate the actual process at that barrier.
3. Restart with the same state and assert eventual processing plus one logical
   operation acceptance.
4. Retain the event history and process exits.
5. Run the implemented scenario and the full fast checks.
6. Update the nearest AGENTS.md, Design.md, README.md and the handoff with the
   observed outcomes and unresolved IDs.

Do not register placeholder commands or describe repeated model processing as
exactly-once execution.
