# Ecosystem build plan

| Field | Value |
| --- | --- |
| Status | Planned |
| Purpose | Sequence the 22 work packages that build three independently usable libraries and one local reference application |
| Audience | Engineers and coding agents who choose, review or sequence the next slice |
| Scope | Work packages PLAN-01 to PLAN-22, stages A to H, dependencies, acceptance coverage and estimate history; excludes granular task detail |
| Owns | Authoritative PLAN work-package sequence, dependencies and estimate history |
| Related | [Granular roadmap](implementation-plan.md) · [Portfolio scope](portfolio-scope.md) · [Validation plan](validation-plan.md) · [Shared design](../Design.md) |

## About this plan

This plan sequences the work to build three independently usable libraries and
one local reference application, with an executable validation path for every
required behavior. It defines 22 work packages, PLAN-01 to PLAN-22, and orders
them into stages A to H. For each work package it records the deliverables,
dependencies and the acceptance IDs it completes. It also keeps the historical
effort estimates. It is written for engineers and coding agents who need to
choose, review or sequence the next slice.

### Contents

| Section | What it covers |
| --- | --- |
| [Current status](#current-status) | Status by project, P1 qualification, the P2/P3 checkpoints, the current frontier and review-driven follow-ups |
| [Foundation and remaining platform work](#foundation-and-remaining-platform-work) | What the local runtime and the P1 phases provide, and the foundation checks to retain |
| [Development principles](#development-principles) | How every slice is delivered |
| [Dependency order](#dependency-order) | Stages, prerequisites and exit results |
| [Work packages by stage](#work-packages-by-stage) | PLAN-01 to PLAN-22 in detail |
| [Acceptance coverage](#acceptance-coverage) | The primary work package for each of the 54 acceptance IDs |
| [Repository layout and local validation](#repository-layout-and-local-validation) | Code locations, package boundaries and validation lanes |
| [Effort and scheduling](#effort-and-scheduling) | The weekly budget and the historical estimates |
| [Decisions and risks to resolve](#decisions-and-risks-to-resolve) | Open questions and where to resolve them |
| [Checkpoints to preserve in the next sessions](#checkpoints-to-preserve-in-the-next-sessions) | Completed P2/P3 evidence that later work must keep |

### Authority and related documents

| Document | Owns |
| --- | --- |
| [Portfolio scope](portfolio-scope.md) | V1 boundaries |
| [Shared design](../Design.md) | State authority and ports |
| [Validation plan](validation-plan.md) | Evidence |
| Project charters for [P1](projects/agent-continuity-scope.md), [P2](projects/channel-continuity-scope.md) and [P3](projects/delegation-reliability-scope.md) | Requirements; they remain authoritative |
| Harness catalog | Executable registrations |

This plan sequences their implementation without adding a fourth framework or
changing acceptance semantics. Individual phase contributions do not
independently establish a complete product release.

### Granular task plans

The [granular roadmap](implementation-plan.md) decomposes these 22 work packages
into phase gates, shared support tasks and project-level implementation slices.
Use its linked [P1](implementation/p1-agent-continuity.md),
[P2](implementation/p2-channel-continuity.md) and
[P3](implementation/p3-delegation-reliability.md) plans for prerequisites,
deliverables, failure assertions, UI/telemetry evidence and task sizing. Those
implementation IDs do not replace acceptance IDs or redefine this plan's
authority. The granular roadmap's preliminary bottom-up sizing is not a measured
delivery forecast. Re-estimate after the first actual recovery slice.

### Identifiers and terms

| Term | Meaning |
| --- | --- |
| PLAN-01 to PLAN-22 | The work packages in this plan. |
| Stages A to H | The ecosystem build stages in the [dependency order](#dependency-order). |
| Phase A to Phase H, for example Phase D | The P1 implementation phases P1-A to P1-H in the [P1 task plan](implementation/p1-agent-continuity.md). They are not the same as the stages. |
| H1, H2 | The P1 Phase H workload steps: the H1 local inquiry baseline, then the H2 restart, slow-dependency, saturation and shutdown workloads. |
| G business profile | The opt-in business application added by P1 Phase G. |
| P1-01, P2-07, P3-15 and similar | Acceptance IDs from the project charters. There are 54 product cases. |
| BASE-01 | The harness baseline case for the existing M1 intake tests. With it, the catalog defines 55 cases. |
| P1-I01, P2-I22, P3-I18B, S-I05 and similar | Implementation task IDs from the granular roadmap. They are not acceptance IDs. |
| STACK-01 to STACK-07 | Technology-stack gates in the [technology baseline](technology-baseline.md). |
| M1 | The existing confirmed-investigation intake. |
| V1 | The fixed project scope. |
| Local-ready V1, Portfolio-ready V1 | The two release gates, defined under Stage H. |
| offline, lab, live | The execution modes in the validation plan. |
| scripted, local_real, provider_real | The trusted inference modes. Scripted is the default. |
| Selected qualification | The gates a work item selected passed within its declared scope. It does not, by itself, complete an acceptance row or a release gate. |
| POC | Proof of concept: the complete local delivery target. |
| CI | Continuous integration. Remote CI and publication are outside this local POC. |

## Current status

### Status by project

| Project | Status | Notes | Acceptance rows | Evidence |
| --- | --- | --- | --- | --- |
| P1 Agent Continuity Lab | Qualified | V1 implemented and locally qualified with provider_real v2; local_real remains unqualified; the P1-20 rerun after the P1 v5 upgrade is open | All 20 registered, with passing retained reports | [0019](work-items/0019-p1-phase-h-release-qualification.md), [0047](work-items/0047-open-findings-schema-upgrades-and-landing.md) |
| P2 Channel Continuity Kit | Partial | P2-I01 to P2-I21 are recorded in completed work items; P2-I22 is the release frontier | 0 of 17 registered; all planned | [Delivery checkpoints](implementation-plan.md#p2-and-p3-delivery-checkpoints) |
| P3 Delegation Reliability Kit | Partial | P3-I01 to P3-I18B are recorded in completed work items; P3-I19 and P3-I22 are in progress | 3 of 17 registered (P3-01, P3-03, P3-11); 14 planned | [Delivery checkpoints](implementation-plan.md#p2-and-p3-delivery-checkpoints) |
| Ecosystem | Partial | Local-ready and portfolio-ready V1 remain incomplete | Catalog: 55 definitions, 24 registered runners | [Release gates](#release-gates) |

The current implementation includes compatible M1 intake, PostgreSQL case,
effect and lease authority, an independent bounded worker, the native scripted
consumer and showcase from P1 Phase G, and the local operational harness. Full
ecosystem coverage remains pending because complete P2/P3 acceptance remains
pending. The 24 registered runners are BASE-01, the twenty P1 rows and the
P3-01, P3-03 and P3-11 lab rows.

### P1 qualification

P1 V1 is implemented and locally qualified with selected provider_real v2, as
recorded in the
[selected-provider local release](work-items/0019-p1-phase-h-release-qualification.md).
All twenty P1 rows have passing retained reports there. P1-01 through P1-05 also
retain SQLite acceptance and recovery evidence.

| Gate or evidence | Recorded outcome | Record |
| --- | --- | --- |
| Final 20-case index, the then-current P1-18, P1-14 and P1-20 runs, full H2, PostgreSQL, installed host/Linux artifacts and shared quality gates | Passed with independent reviews | [0019](work-items/0019-p1-phase-h-release-qualification.md) |
| P1-I26's host/Linux artifacts, independent API review and genuine native consumer | Passed | [0019](work-items/0019-p1-phase-h-release-qualification.md) |
| Selected provider_real v2 gate | Passed both actual browser cases with cleanup | [0019](work-items/0019-p1-phase-h-release-qualification.md) |
| provider_real deep gate rerun after the P1 PostgreSQL v5 upgrade | Passed 20 of 21 rows: BASE-01 and P1-01 to P1-19, with 104 tests and zero skips | [0047](work-items/0047-open-findings-schema-upgrades-and-landing.md) |
| P1-20 in that rerun | Blocked on that network; a rerun with `P1_PROVIDER_CA_BUNDLE` pointing at the approved bundle remains open | [0047](work-items/0047-open-findings-schema-upgrades-and-landing.md) |
| local_real implementation | Not qualified | [0017](work-items/0017-p1-local-real-inference.md) |

Historical checkpoints retain their original scope.

- Complete P2/P3 acceptance remains pending.
- Hosted CI and publication are outside this local POC.

The rerun followed the explicit owner upgrade to P1 PostgreSQL v5 (persisted
mutation retry due time). The passing reference run had mounted an approved
certificate authority (CA) bundle into the native container, but every 0047 run
used the image trust store and recorded zero speech-to-text (STT), large
language model (LLM) and text-to-speech (TTS) usage before the agent's reply
timed out. The v5 change also raised the pinned P1 runtime payload count from 77
to 78.

### P2 and P3 checkpoints

P2 and P3 advance through paired work items, each with its own selected gates.
The granular roadmap's
[delivery checkpoints](implementation-plan.md#p2-and-p3-delivery-checkpoints)
list every work item from 0029 to 0047 with its task IDs, counts and caveats. In
summary:

| Work items | P2 contribution | P3 contribution | Outcome |
| --- | --- | --- | --- |
| 0029 to 0035 | P2-I08 to P2-I14: gateway, agent recovery, revision routing, linked confirmation, outbound replies, callbacks and send policy | P3-I07A to P3-I12: issued execution, first delivery, concurrent acceptance, result projections, processing, applicability refresh and action races | Added; the 0031 phase registered the complete P3-01, P3-03 and P3-11 lab rows |
| 0036 to 0040 | P2-I15 to P2-I20: native input, playback evidence, case rehydration, the bounded workload study and the operations UI | P3-I13 to P3-I17: deadlines, process recovery, standalone consumption, image HTTP and fixed-policy evidence | Added |
| 0041 | P2-I21's installed standalone application | The P3-I18A durable fixed-policy prerequisite | Completed |
| 0042 | None | The selected P3-I18B native real-time communication (RTC) text qualification | Completed |
| 0043 and 0044 | P2-I22 delivery/read and original-input prerequisites | P3-I19 delivery/read and original-input prerequisites | Qualified |

0045 to 0047 compose the joined application described next. No checkpoint after
0031 registered a complete charter row.

### Current frontier: the joined application

The [0045 work item](work-items/0045-joined-native-channel-policy.md) owns the
joined local application and is still Active.

| Sub-phase | Scope | Recorded position |
| --- | --- | --- |
| 45A | The original/prepared/read and installed contracts | Qualified |
| 45B | Public source, gateway, client and executor composition | Implemented; the complete frozen joined database/process gate remains pending |
| 45C | Joins actual native media and the compact browser journey | First connected browser observations recorded; both whole joined observations remain failed |
| 45D | Repeats installed/local packaging, shared validation and the recorded demo | Open |

Phase 45B detail:

- Explicit owner setup succeeds, and preliminary actual signed-SMS, execution and
  delivery joins are observed.
- The current-result producer is component-tested and attached through one
  application-owned room facade.
- Room control and attachment, the Node native prepare/context bridge and a
  single-session scripted worker have scoped component qualification.
- The parent room/process composition now also has a component baseline: Parent
  Start/End passed nineteen focused independent tests.

[0046](work-items/0046-joined-showcase-providers-and-demo.md) then ran the
joined journey with real Deepgram, OpenAI and ElevenLabs models and recorded a
narrated demo video. It registers no charter row and does not replace the 0045
qualification gates. [0047](work-items/0047-open-findings-schema-upgrades-and-landing.md)
closed selected review findings, added the explicit owner upgrades to P1 v5 and
P2 v9 and a landing page, and recorded one complete demo video. Preserve the
existing acceptance IDs, and keep component evidence separate from complete
P2/P3 charter requirements.

### Review-driven follow-ups

The [architecture review disposition](work-items/0020-architecture-audit-reconciliation.md)
is the current findings map.

| Topic | Disposition |
| --- | --- |
| Qualified P1 V1 baseline | Preserve it |
| [Bounded operational extension](work-items/0021-p1-operational-safety-extensions.md) | Select it before claiming restored-database recovery or manual uncertainty resolution; it remains planned |
| P2 contracts and the P3 controlled baseline | Started with their first slices, [0022](work-items/0022-p2-channel-contracts.md) and [0023](work-items/0023-p3-native-baseline.md) |
| P2 and P3 charters and task plans | Now require stronger association lifecycle, recipient/route, source grounding and protected commitment tests |
| Review scope | Adds no fourth project, remote CI, real carrier requirement or dependency upgrade |
| Core compaction | Remains conditional before sustained reclamation |
| Human consumer feedback and dependency-tool qualification | Retain their own future evidence requirements |

The operational extension is additional post-V1 scope, not an unrecorded
prerequisite of the completed gate. P2 and P3 were free to begin their
independent contract and baseline tasks at the existing frontiers. On 10 November
the user selected P2 contracts and the independent P3 controlled baseline as the
next work. The operational extensions do not block these standalone slices.

## Foundation and remaining platform work

### Runtime foundation

The repository includes services/control_api, services/rtc_agent,
apps/local-console and [local-setup](../local-setup/README.md). Compose runs the
self-hosted media server, PostgreSQL, the authenticated local API, the
deterministic transport diagnostic worker and the browser application. Named
volumes, generated credentials, health/readiness checks and lifecycle tooling
establish a runnable foundation. The live M1 API continues to use SQLite.

### P1 phases built on the foundation

| P1 phase | What it adds | Gate and record |
| --- | --- | --- |
| Phase C | The standalone PostgreSQL inquiry backend, after controlled verified cutover | [Phase C work item](work-items/0009-p1-phase-c-postgres-cutover.md) |
| Phase D | Exact case/quote/confirmation and durable continuation | [Phase D work item](work-items/0010-p1-phase-d-authority-and-waits.md) |
| Phase E | PostgreSQL v3 supplier effects, cancellation and atomic completion/outbox state | [Final combined gate](work-items/0011-p1-phase-e-effects-and-completion.md) passed |
| Phase F | P1-I19 through P1-I21 | [Combined gate](work-items/0012-p1-phase-f-leases-and-deployment.md) passed |
| Phase G | P1-I22 through P1-I25 | Inspected local combined gate recorded in the [Phase G work item](work-items/0013-p1-phase-g-conversation-and-showcase.md) |
| Phase H | The completed S-I06/P1-I27 local inquiry baseline (H1), then later restart, slow-dependency, saturation and shutdown results (H2) | [H1 work item](work-items/0014-p1-phase-h-workload-baseline.md); the [reliability work item](work-items/0015-p1-reliability-workloads.md) owns the passed H2 results |

The opt-in business profile from Phase G connects a scripted native AgentSession
to managed PostgreSQL work, bounded authenticated case projections and separate
exact quote approval. Explicit media End retires the room, and a fresh native
consumer reloads the same owned task. This is actual local browser/native media.
It is not physical microphone capture, live-model quality, automatic
network-loss recovery or remote CI proof. Original SQLite M1 and the diagnostic
profile remain independently available. The resulting P1 release status is
under [P1 qualification](#p1-qualification).

### Media foundation evidence

| Evidence | Recorded outcome |
| --- | --- |
| Native software development kit (SDK) smoke runs from the host and Docker | Passed actual text echo and fixture-audio frame checks |
| Authenticated browser room/text, explicit disconnect/reconnect and M1 acceptance/replay/conflict UI checks | Passed |
| G business profile media | Adds explicit bundled-WAV WebAudio publication, actual WebRTC speech output, active interruption and fresh-room status from the same durable task |
| Physical microphone quality and configured inference | Not qualified |

The G business profile's STT and LLM are scripted, and speech uses local
pulse-code modulation (PCM) fixtures. Remote Linux CI is outside this local POC
scope. These contributions do not complete PLAN-09/10/11 or another full charter
row.

### Remaining work for PLAN-09 to PLAN-11

| Work package | Existing foundation | Still required before completion |
| --- | --- | --- |
| PLAN-09 | Pinned Compose infrastructure, explicit business migrations, v4 worker profiles, preserved-state recovery and bounded lifecycle tooling | Complete supported-platform and release reproduction |
| PLAN-10 | Exact installed Python/TypeScript dependency locks and exercised SDK/container images | Remaining component/plugin compatibility, cross-language product contracts and full supported-platform promotion |
| PLAN-11 | Independent diagnostics plus native scripted business tools, scoped case UI, local browser audio/interruption/fresh consumer and inspected filtered traces | Physical microphone/live inference where required, seeded workloads, isolated artifact/API review and complete P1-20/release evidence |

The remaining plan preserves the product dependency order. Existing setup can be
reused by the first inquiry slice. Infrastructure readiness must not be mistaken
for schema-safe execution or model behavior.

### Foundation qualification checks

Retain the following foundation reproduction checks when changing the runtime.
Their historical baseline is distinct from the later G business profile and from
the remaining supported-platform and hardware gates. They are not another
product project or a passing P1/P2/P3 acceptance case.

| Check | What to exercise | Evidence rule |
| --- | --- | --- |
| Browser connection | Authenticated browser connection, rejection of invalid credentials, room-scoped token behavior and disconnect/reconnect against the actual local server and named agent | Treat browser, host-SDK and container-SDK results as distinct observations |
| Text and audio diagnostics | Text echo and the exact audio-diagnostic schema in the browser | Accept agent diagnostics only from the expected agent participant, and correlate media evidence with the intended track |
| Diagnostic fixtures | Deterministic fixture text/audio where supported | Test malformed or unexpected senders and diagnostics |
| Microphone publishing | Only after the operator's explicit action and browser permission | Denial or unavailable permission must remain visible; native-SDK audio reception does not substitute for a browser microphone check |
| Cleanup, restart and configuration | Bounded cleanup, normal restart persistence and port/config behavior | Record which checks ran and which remain pending; a browser capability blocker is an explicit gap, not a successful interaction |
| Installation paths | The selected local host and Linux-container installation paths | Retain their actual architectures; remote CI and publication are outside this POC scope, and an existing workflow file is only an optional automation reference |

Register foundation assertions separately from the 54 product scenarios. The
inquiry/recovery and later backend slices are already implemented. Reproduce
them when affected rather than scheduling them as new work. A recorded
browser-capability blocker does not stop independent offline work. The affected
required media gate remains pending, and it must pass before the corresponding
integrated release claim. The G local business-tool/interruption contribution
belongs to PLAN-11; P2 playback semantics remain under PLAN-15.

Observed foundation qualification is recorded in the
[audit work item](work-items/0004-plan-and-showcase-audit.md). Browser error
recovery, agent-presence admission, text and M1 UI transitions passed at that
checkpoint. The later
[Phase G gate](work-items/0013-p1-phase-g-conversation-and-showcase.md) adds
actual scripted browser/native audio, active interruption, fresh-consumer
continuity and inspected raw Jaeger v3 traces. Hardware microphone capture,
network-loss media recovery and local_real remain unqualified. Remote Linux CI
is outside this local POC scope. No complete product acceptance row follows from
these phase contributions.

## Development principles

### Deliver vertical slices

Deliver one vertical slice at a time: a usable API, persisted behavior, a normal
path, a deterministic failure and a diagnosable result. Begin with the smallest
worker/recovery slice using the existing Python environment. Installing LiveKit
or introducing PostgreSQL must not block that first inquiry demonstration.

### What each work package produces

Each work package produces code, relevant tests, harness registration, updated
status and a concise handoff. A planned acceptance ID becomes executable only
after its actual assertions exist; registering a runner alone cannot complete
it. Retain the working baseline throughout. Move code only for an established
package boundary, with import and test changes in the same slice.

### Dependency baseline

Keep one frozen, validated dependency baseline within a feature slice. Refresh
compatible stable direct versions at a new integration, an intentional upgrade
or a release gate. Do not couple ordinary feature edits to continuous dependency
churn.

### One authority per concern

Use one case authority for confirmed facts, revisions and action intents. The P1
booking API wraps the reusable TaskExecutionPort, and P3 registers allowlisted
specialist work through that port. P2 owns messages and delivery evidence. No
component copies another component's execution queue or current-case authority.

## Dependency order

| Stage | Work packages | Prerequisite | Exit result |
| --- | --- | --- | --- |
| Foundation qualification | Operational parts of PLAN-09 to PLAN-11 | Existing local stack | Browser transport/auth/permission evidence recorded; local host/container parity remains separately evidenced |
| A First recovery slice | PLAN-01 to PLAN-03 | Current M1, harness and bounded foundation qualification | Independent SQLite inquiry worker survives the selected crash boundary |
| Adapter checkpoint | Early adapter portion of PLAN-08 | Stage A | PostgreSQL single-worker adapter passes the selected store contract before lifecycle expansion |
| B Durable business semantics | PLAN-04 to PLAN-07 | Stage A and the early PLAN-08 adapter checkpoint | Confirmed fake change, waits, cancellation, reconciliation and durable result events |
| C Multi-worker local execution | Coordination portion of PLAN-08 and PLAN-09 | Stage B; early adapter already present and infrastructure can start independently | PostgreSQL coordination and repeatable container restart |
| D Real media foundation | PLAN-10 and PLAN-11 | Infrastructure can start independently; durable tool integration needs Stage A and full P1 release needs Stage C | Compatible locked SDKs and actual local browser/agent interaction |
| E Channel continuity | PLAN-12 to PLAN-16 | Case/execution contracts; media foundation for audio cases | Standalone channel SDK and integrated voice/chat/fake-SMS continuity |
| F Delegation reliability | Native baseline decision, then PLAN-17 and PLAN-18 | Stable execution/case ports and a retained tools/native-subagent baseline | One remote typed specialist, duplicate handling and stale-result protection |
| G Multimodal collaboration | PLAN-19 to PLAN-21 | Stage F; P2 routing for integrated resumption | Two bounded capabilities, recovery, current-result routing and comparisons |
| H Ecosystem release | PLAN-22 | All relevant work packages | Local-ready and portfolio-ready gates reported separately |

### Parallel work

- PLAN-10 can start alongside late P1 work.
- P2 schema work and a scripted P3 contract can proceed independently after
  shared interfaces stabilize.
- Keep one primary implementation slice active for the learner. Parallel
  reviews, fixtures and documentation must not create competing contract
  definitions.

## Work packages by stage

This summary names each work package's stage and its acceptance or stack-gate
contribution. The stage sections below own the deliverables, and
[acceptance coverage](#acceptance-coverage) maps each acceptance ID back to its
primary package.

| Work package | Name | Stage | Acceptance or gate contribution |
| --- | --- | --- | --- |
| PLAN-01 | Baseline and scenario contract | A | Keeps BASE-01 passing |
| PLAN-02 | Explicit execution record | A | Protects P1-01, P1-02, P1-03 and P1-19 |
| PLAN-03 | Independent inquiry and recovery | A | Completes P1-04 and P1-05 |
| PLAN-04 | Case authority and confirmation snapshot | B | Establishes P1-06's contract, completes P1-07's rejection cases and seeds cross-scope fixtures for P1-17 |
| PLAN-05 | Persisted waits and signals | B | Completes P1-10 and P1-11 |
| PLAN-06 | Retry, cancellation and resource lifecycle | B | Completes P1-12, P1-13, P1-14 and P1-18 |
| PLAN-07 | Fake mutation, uncertainty and result events | B | Completes P1-06, P1-08, P1-09 and P1-16 |
| PLAN-08 | PostgreSQL adapter and coordination | Adapter checkpoint after A; coordination in C | Completes P1-15 and P1-17 and the full migration/recovery evidence for P1-19 |
| PLAN-09 | Compose runtime and recovery | Foundation qualification and C | Supplies the deployment foundation used by P1-10, P1-18 and later P2/P3 restart scenarios |
| PLAN-10 | Latest-compatible stack promotion | Foundation qualification and D | STACK-01 through STACK-03 now; STACK-04 incrementally; STACK-05/06 after later media/platform runs |
| PLAN-11 | Local LiveKit and browser adapter | Foundation qualification and D | Completes the lab portion of P1-20 and STACK-05/STACK-06 |
| PLAN-12 | TypeScript events and fake carrier | E | Covers P2-01, P2-02 and P2-12 |
| PLAN-13 | Durable intake and case routing | E | Completes P2-03, P2-04, P2-05, P2-06 and P2-16 |
| PLAN-14 | Outbound delivery semantics | E | Completes P2-10 and P2-11 |
| PLAN-15 | Browser and playback continuity | E | Completes P2-07, P2-08, P2-09 and P2-15 |
| PLAN-16 | Bounded load and fresh-agent handoff | E | Completes P2-13, P2-14 and P2-17 |
| Native baseline | Native baseline before PLAN-17 | F | Precedes remote-service implementation; does not replace P3-16's final comparison in PLAN-21 |
| PLAN-17 | One remote specialist contract | F | Covers P3-01, P3-03 and P3-11 |
| PLAN-18 | Result applicability and recovery | F | Covers P3-04, P3-05, P3-06, P3-07, P3-08, P3-09 and P3-10 |
| PLAN-19 | Two bounded capabilities | G | Completes P3-15 in deterministic mode |
| PLAN-20 | Responsive conversation and result routing | G | Completes P3-02, P3-12, P3-13, P3-14 and the lab portion of P3-17 |
| PLAN-21 | Baselines, live inference and performance | G | Completes P3-16 and the live portions of P1-20/P3-17 |
| PLAN-22 | Release and independent review | H | Runs every implemented scenario in its designated lane and retains STACK-07 evidence |

### Stage A: First recovery slice (PLAN-01 to PLAN-03)

#### PLAN-01 Baseline and scenario contract

- Record the current intake behavior, the worker's inquiry permission and the
  exact crash barrier in a work item.
- Extend the harness scenario metadata only as needed for a real process test.
- Keep BASE-01 passing and leave unrelated P1/P2/P3 cases unimplemented.
- Add the first local fast lane using the existing documented command, with no
  provider credentials.

#### PLAN-02 Explicit execution record

- Add a versioned migration for queued M1 requests, a typed single-worker
  execution state and a stable inquiry effect ID persisted before dispatch.
  Preserve original request identities and payloads.
- Implement the smallest TaskExecutionPort adapter in the existing continuity_lab
  boundary. Keep blocking SQLite work behind a bounded async boundary wherever it
  is called by async code.
- Retain a pre-upgrade database fixture. Test failed or interrupted migration
  handling and intake replay before adding more workflow states.
- Preserve the original data or a demonstrated restore path. Do not assume every
  migration can be reversed.
- Decide the supported SQLite compatibility subset in this package: preserve M1
  intake/migration and the first single-worker inquiry/recovery path. Do not
  implicitly promise complete SQLite/PostgreSQL scheduler parity. Document
  supported operations and explicit unsupported-operation errors.

The full V1 business execution backend will be PostgreSQL. PLAN-02 protects
P1-01, P1-02, P1-03 and P1-19.

#### PLAN-03 Independent inquiry and recovery

1. Create a persisted fake supplier whose inquiry state survives independently
   of the worker.
2. Run the worker as a separate process.
3. Stop it after supplier inquiry success and before local result
   acknowledgement.
4. Start a new worker and reconcile the same inquiry identity.
5. Inspect both stores and assert one logical inquiry and an unchanged booking.

Complete P1-04 and P1-05. Retain the ordinary success path alongside the crash.

#### Stage A exit

Stage A exits with a reproducible offline demonstration, process/effect history,
exact commands and an independently reviewed failure boundary. It does not add
booking mutation, model inference, SMS or distributed worker claims.

#### Early PostgreSQL adapter checkpoint

Immediately after PLAN-03, implement the early adapter portion of PLAN-08.
Introduce the PostgreSQL single-worker store/execution adapter, and run the
shared store contract for operations the SQLite subset supports. Preserve
existing M1 identities through the documented import/migration path. Continue
the richer lifecycle on PostgreSQL instead of first duplicating a complete
scheduler on SQLite. This checkpoint does not establish leases, multi-worker
coordination or complete P1-15/P1-19; those remain the later PLAN-08 gate.

### Stage B: Durable business semantics (PLAN-04 to PLAN-07)

The P1 phases have implemented the following contributions:

| P1 phase | Contribution | Gate |
| --- | --- | --- |
| Phase D | PLAN-04, PLAN-05 and the inquiry retry/deadline contribution to PLAN-06 | [Phase D work item](work-items/0010-p1-phase-d-authority-and-waits.md) |
| Phase E | The mutation, cancellation and completion contributions to PLAN-06 and PLAN-07 | Final combined gate passed |
| Phase F | PLAN-08 coordination and the PLAN-06/PLAN-09 bounded admission and deployment contributions | Combined gate passed |

P1 V1 is qualified for the local POC using provider_real v2. local_real remains
unqualified, and complete P2/P3 acceptance remains pending. Later P2/P3 platform
and acceptance tasks remain planned.

#### PLAN-04 Case authority and confirmation snapshot

- Implement a small scoped case authority with expected-revision updates and
  immutable quote/confirmation records.
- Define the trusted synthetic actor context separately from a caller's scope
  label.
- Atomically validate actor, revision, quote, amount/currency, expiry and
  confirmation, and record the mutation intent with its dispatch event. The
  committed intent is the action commitment point.
- Establish P1-06's contract, complete P1-07's rejection cases and seed
  cross-scope fixtures for P1-17.
- Record the API and transaction decision before adding an independently
  running service around this authority.
- Include the retention and replay-horizon decision before adding cleanup.
  Display-history pruning and business deadline expiry cannot erase effect
  identities, confirmations or idempotency protection needed by eligible replay.
  Define retained tombstones and explicitly rejected expired identities, with a
  late-retry test after pruning.

#### PLAN-05 Persisted waits and signals

- Store absolute business deadlines and typed deduplicated signals, including
  signals arriving before their matching wait.
- A waiting workflow consumes no permanently sleeping coroutine.
- Add a controllable clock and deterministic assertions for restart, early and
  late signals, altered replay and unrelated callbacks.
- Complete P1-10 and P1-11.

#### PLAN-06 Retry, cancellation and resource lifecycle

- Classify definitive and transient failures, bound attempts and backoff, and
  apply deadline eligibility.
- Record cancellation separately from execution state.
- Use barriers to race confirmation against cancellation at the commitment
  transaction.
- Preserve the postcommit best-effort boundary, and keep speech interruption
  separate from business cancellation.
- Test admission limits, bounded shutdown and resource cleanup.
- Complete P1-12, P1-13, P1-14 and P1-18.

#### PLAN-07 Fake mutation, uncertainty and result events

- Apply an explicitly confirmed fake change using the persisted effect key.
- Repeat the crash boundary for mutation, and reconcile with a cooperating
  supplier.
- A second fake adapter without safe deduplication/lookup must produce an
  uncertain result after an ambiguous dispatch.
- Commit final state and a stable completion-event intent together. Recover
  outbox delivery after a crash.
- Complete P1-06, P1-08, P1-09 and P1-16.
- Recheck the normal authorized path and cross-scope rejection.

#### Stage B exit

Stage B exits with the complete single-worker business lifecycle, minimal API
examples and deterministic effect/cancellation contracts. No unconditional
exactly-once external effect is claimed.

### Stage C: Multi-worker local execution (PLAN-08 and PLAN-09)

#### PLAN-08 PostgreSQL adapter and coordination

This package has two passes:

1. The single-worker adapter/store-contract pass runs immediately after PLAN-03,
   before Stage B expands the lifecycle. Build on the provisioned PostgreSQL
   service and document the limited SQLite compatibility contract chosen in
   PLAN-02.
2. The coordination pass runs here, after Stage B. Implement short
   claim/renewal transactions and conditional writes using an execution epoch.
   Use independent workers and barriers to prove lease takeover and stale-write
   rejection. Test the old worker's external-call attempt separately against
   the supplier contract.

Rerun the common store contract on the explicitly supported SQLite subset and on
PostgreSQL, then run PostgreSQL-specific multi-worker/lease assertions.
Unsupported SQLite operations fail explicitly instead of silently weakening
guarantees. Complete P1-15 and P1-17 and the full migration/recovery evidence
for P1-19.

#### PLAN-09 Compose runtime and recovery

The operational foundation described above is implemented. This package remains
partial until product recovery and platform evidence pass.

- Extend the pinned images, example configuration, health/readiness checks and
  named volumes with product migrations and synthetic fixtures.
- Provide standalone project selection and an integrated selection as services
  become available.
- Keep offline, lab and live modes explicit.
- Normal stop/start preserves data; reset is a separate explicit operation.
- Validate bounded startup/shutdown and container recovery with actual process
  termination.
- Record PostgreSQL/worker logs and effect histories.

This work supplies the common deployment foundation used by P1-10, P1-18 and
later P2/P3 restart scenarios.

Do not list future Compose commands in a runnable quickstart until they exist
and pass clean-setup tests. Validate macOS Docker Desktop and Linux networking
explicitly; a browser-visible address and a container-visible address can
differ.

### Stage D: Real media foundation (PLAN-10 and PLAN-11)

#### PLAN-10 Latest-compatible stack promotion

Current dependency locks, SDK imports and local images provide initial evidence.

- Refresh official stable direct selections at the integration/upgrade
  checkpoint, then hold the validated baseline fixed within the feature slice.
- Resolve exact runtime/SDK/plugin dependencies, maintain lockfiles and verify
  frozen installation.
- Follow the [technology baseline](technology-baseline.md) rather than
  independently upgrading incompatible transitive packages.
- Perform native imports on declared architectures. Add strict TypeScript
  compilation/test tooling when that language's code is introduced.

The stack gates are completed as follows:

- Complete the applicable provenance, resolution and import checks in STACK-01
  through STACK-03 now.
- STACK-04 is completed incrementally with the actual project code and
  cross-language tests.
- STACK-05/06 require later media/platform runs.

Do not make full stack promotion a circular prerequisite for creating the code
that those gates must test.

#### PLAN-11 Local LiveKit and browser adapter

The actual self-hosted server, browser console and SDK diagnostic worker exist.
Extend this transport foundation with the Python conversational agent and
authenticated browser validation.

Conversation:

- Use native AgentSession, tools, handoffs and AgentTask/TaskGroup where their
  conversational semantics fit. Durable business recovery remains P1's concern.
- Evaluate the official Agents UI components for the product conversation client
  at this checkpoint. Preserve the small existing diagnostic console until a real
  application consumer needs that integration.
- Use scripted inference and audio fixtures first to establish transport, text,
  tool calls, interruptions, disconnect/reconnect and shutdown without paid
  services.
- A tool acknowledges durable acceptance without waiting for supplier
  completion.
- Exercise slow storage/supplier conditions and measure event-loop
  responsiveness.

Complete the lab portion of P1-20 and STACK-05/STACK-06. Retain the
real-inference portion for the portfolio gate.

Observability:

- Add bounded local trace collection and correlated IDs.
- Use the installed SDK's current chat-message/provider metrics, usage and
  session report surfaces, with OpenTelemetry export where supported.
- Classify provider, transport, validation, capacity and storage exceptions into
  structured safe outcomes. Retain observed causes internally without leaking
  credentials.
- Bound exporter queues and timeouts, and test exporter failure without blocking
  conversation.

References: [Tasks](https://docs.livekit.io/agents/logic/tasks/) and
[session data and metrics](https://docs.livekit.io/testing/observability/data/).

#### P1 local-ready release

P1 local-ready release can now run through its full acceptance matrix. Review
its standalone example, public API, migration instructions and failure contract
before publishing P1 claims. Continue P2/P3 work through the established ports.

### Stage E: Channel continuity (PLAN-12 to PLAN-16)

#### PLAN-12 TypeScript events and fake carrier

- Introduce strict TypeScript and runtime-validated, versioned JSON event
  unions.
- Separate provider scope from verified business-account scope.
- Define semantic payload canonicalization so that a metadata-only retry
  deduplicates while a changed message conflicts.
- Add shared positive/negative fixtures exercised in Python and TypeScript.
- Implement the fake carrier and minimal synthetic association flow, with
  signature and access rejection cases.
- Cover P2-01, P2-02 and P2-12.

#### PLAN-13 Durable intake and case routing

- Persist input before acknowledgement, and make dispatch recoverable after
  gateway or agent termination.
- Preserve stable business-operation identities without promising exactly-one
  model invocation.
- Use the case authority for competing commands and delayed/ambiguous
  confirmations.
- Supply a standalone case store, scripted agent and operation port so the
  package can run without P1/P3 services.
- Complete P2-03, P2-04, P2-05, P2-06 and P2-16.

#### PLAN-14 Outbound delivery semantics

- Persist notification intents, attempts and provider callbacks.
- Reordered callbacks retain appropriate stronger evidence under an explicit
  provider rule.
- An acknowledgement lost after a non-idempotent send remains uncertain under
  the documented resend policy.
- Add fake-provider barriers for duplicate callback and ambiguous-send cases.
- Complete P2-10 and P2-11. Integrate P1 completion events without adopting
  workflow ownership.

#### PLAN-15 Browser and playback continuity

- Route native LiveKit text through the single durable acceptance path.
- Preserve generation, native interruption, client playback and acknowledgement
  observations separately.
- Test real browser audio interruption, loss of playback evidence and
  voice/chat/fake-SMS resumption after room closure.
- Rehydrate authoritative current case state and bounded history.
- Complete P2-07, P2-08, P2-09 and P2-15 using the lab media path first.

#### PLAN-16 Bounded load and fresh-agent handoff

- Exercise bursts, inspectability of accepted work and many dormant
  conversations without per-thread rooms.
- Add measured admission/resource limits and a compact event timeline.
- Have a fresh coding agent use only the repository instructions, fixtures and
  harness to make one bounded change and diagnose its result.
- Complete P2-13, P2-14 and P2-17.
- Review the standalone example and integrated P1 adapter for the P2 local gate.

### Stage F: Delegation reliability (native baseline, PLAN-17 and PLAN-18)

#### Native baseline before PLAN-17

Before PLAN-17, retain a small tools/native-local-subagent baseline using the
same bounded capability input and controlled outcomes. Record useful progress,
conversation responsiveness and observed overhead. Decide why an independent
TypeScript service is warranted by process/language isolation or recovery needs.
This decision precedes remote-service implementation. It does not replace the
final three-way model/performance comparison required by P3-16 in PLAN-21.

#### PLAN-17 One remote specialist contract

Implement the Python coordinator and one scripted TypeScript capability behind a
bounded authenticated HTTP invocation.

Execution ownership:

- P1 owns durable acceptance, attempt identity, retry/deadline eligibility and
  result persistence.
- Each remote invocation belongs to one P1-owned attempt.
- Status, cancellation and result endpoints expose correlated attempt
  observations rather than a second recovering queue or scheduler.
- A lost HTTP response follows P1's stable logical identity, duplicate handling
  and retry policy.

Trust, scope and contracts:

- Bind scope to a verified local service principal, and authorize invocation,
  status, result, cancellation and scoped image access. A JSON tenant label
  alone grants no authority.
- Reuse TaskExecutionPort, CaseAuthorityPort and ResultDeliveryPort through
  small local adapters.
- Validate immutable context, scope, schema versions and size limits in both
  languages.
- Demonstrate a current useful result, a minimal stale-result rejection and a
  same-ID conflict before additional capabilities. The full applicability/race
  suite remains PLAN-18.
- Cover P3-01, P3-03 and P3-11.

The TypeScript specialist needs runtime schemas and capability/provider clients.
Install Node Agents/RTC native peers only if it actually hosts a Node realtime
agent. Matching the stack does not require a redundant media participant.

#### PLAN-18 Result applicability and recovery

- Add durable delegation/result metadata, duplicate-completion handling,
  deadline eligibility and separate cancellation/invalidation observations.
- Use barriers for result/revision/intent races. Accept zero stale actions while
  a valid current result still progresses.
- Terminate specialist/coordinator processes and recover through P1's execution
  contract.
- Cover P3-04, P3-05, P3-06, P3-07, P3-08, P3-09 and P3-10.

### Stage G: Multimodal collaboration (PLAN-19 to PLAN-21)

#### PLAN-19 Two bounded capabilities

- Add static booking-image extraction and fixed, versioned policy analysis. They
  may share one service.
- Implement fixture cases for missing/ambiguous fields, evidence references,
  invalid output and adversarial document text.
- Neither capability receives mutation or delivery authority.
- Complete P3-15 in deterministic mode. Actual model outcomes are verified
  separately in PLAN-21.
- Continuous video and additional roles stay out.

#### PLAN-20 Responsive conversation and result routing

- Keep conversation active while a specialist is held on a barrier.
- Deliver through a stable route after handoff/reconnect.
- Exercise per-tenant/global caps, useful progress for another admitted tenant
  and container restart using the same volumes.
- Complete P3-02, P3-12, P3-13, P3-14 and the lab portion of P3-17.

#### PLAN-21 Baselines, live inference and performance

- Extend the pre-PLAN-17 baseline into the final three-way comparison. Compare
  single-agent tools, native local subagents and remote specialists on the same
  task, controlled input and equivalent provider/model configuration. Record
  unavoidable context differences.
- Measure first audible and meaningful response, useful-result time,
  queue/recovery delay, event-loop lag, resource use, task correctness and cost.
- Complete P3-16 and the live portions of P1-20/P3-17.
- Verify screenshot/policy outcomes with selected real models and compare them
  with fixture expectations.
- Optional provider or carrier experiments cannot become default local
  dependencies.

### Stage H: Ecosystem release (PLAN-22)

#### PLAN-22 Release and independent review

- Reproduce setup from a clean environment, run every implemented scenario in
  its designated lane, and check standalone examples as well as integration.
- Retain environment/dependency evidence for STACK-07.
- Review APIs, failure contracts, docs and supported commands independently.
- Record actionable findings, and resolve them or explicitly narrow the claim.
- Produce short success/failure demos and sanitized benchmark summaries.

#### Release gates

| Release gate | Requirements |
| --- | --- |
| Local-ready V1 | All 54 product cases in their local portions, actual local media, supported-platform setup, migrations, recovery and bounded resource tests |
| Portfolio-ready V1 | Everything in local-ready V1, plus retained real-model behavior, outcomes/costs, baseline comparisons, API review and demonstrations |

A skipped, timed-out or unimplemented required scenario leaves the corresponding
gate incomplete. A local scripted inference result cannot establish model
quality.

## Acceptance coverage

Each of the 54 required IDs has a primary implementation package below. The
charter supplies the exact assertions. Integration and release rerun relevant
cases without changing their meaning.

### P1 acceptance IDs

| Acceptance ID | Primary work package | Evidence lane |
| --- | --- | --- |
| P1-01 | PLAN-02 | Persistence and processes |
| P1-02 | PLAN-02 | Deterministic concurrency and persistence |
| P1-03 | PLAN-02 | Deterministic identity/conflict |
| P1-04 | PLAN-03 | Independent worker |
| P1-05 | PLAN-03 | Process crash and reconciliation |
| P1-06 | PLAN-07 | Authorized effect; confirmation contract in PLAN-04 |
| P1-07 | PLAN-04 | Negative confirmation cases |
| P1-08 | PLAN-07 | Mutation crash and reconciliation |
| P1-09 | PLAN-07 | Uncertain external outcome |
| P1-10 | PLAN-05 | Persisted wait; container repetition in PLAN-09 |
| P1-11 | PLAN-05 | Signal identity/correlation |
| P1-12 | PLAN-06 | Fake-clock retry/deadline |
| P1-13 | PLAN-06 | Controlled cancellation race |
| P1-14 | PLAN-06 | Cancellation; audio repetition in PLAN-11 |
| P1-15 | PLAN-08 | PostgreSQL independent workers |
| P1-16 | PLAN-07 | Outbox crash and replay |
| P1-17 | PLAN-08 | Trusted-scope access; fixtures begin PLAN-04 |
| P1-18 | PLAN-06 | Capacity/shutdown; container repetition PLAN-09 |
| P1-19 | PLAN-08 | Migration; first migration protected in PLAN-02 |
| P1-20 | PLAN-11 | Local media; live evidence PLAN-21 |

### P2 acceptance IDs

| Acceptance ID | Primary work package | Evidence lane |
| --- | --- | --- |
| P2-01 | PLAN-12 | Scoped concurrent replay |
| P2-02 | PLAN-12 | Canonical event fixtures |
| P2-03 | PLAN-13 | Gateway crash recovery |
| P2-04 | PLAN-13 | Agent crash/replay |
| P2-05 | PLAN-13 | Controlled case-revision race |
| P2-06 | PLAN-13 | Stale/ambiguous confirmation |
| P2-07 | PLAN-15 | Actual browser audio interruption |
| P2-08 | PLAN-15 | Missing playback observation |
| P2-09 | PLAN-15 | Cross-channel local integration |
| P2-10 | PLAN-14 | Callback replay/reordering |
| P2-11 | PLAN-14 | Ambiguous fake-provider send |
| P2-12 | PLAN-12 | Association/signature/access rejection |
| P2-13 | PLAN-16 | Bounded burst/saturation |
| P2-14 | PLAN-16 | Dormant-thread resource study |
| P2-15 | PLAN-15 | Actual media/text single intake path |
| P2-16 | PLAN-13 | Standalone local integration |
| P2-17 | PLAN-16 | Fresh-agent reproducibility |

### P3 acceptance IDs

| Acceptance ID | Primary work package | Evidence lane |
| --- | --- | --- |
| P3-01 | PLAN-17 | Cross-language useful-result path |
| P3-02 | PLAN-20 | Held specialist and active conversation |
| P3-03 | PLAN-17 | Concurrent replay/conflict |
| P3-04 | PLAN-18 | Completion replay after restart |
| P3-05 | PLAN-18 | Stale result plus current-result liveness |
| P3-06 | PLAN-18 | Atomic authority race |
| P3-07 | PLAN-18 | Postcommit revision/cancellation |
| P3-08 | PLAN-18 | Process crash and durable recovery |
| P3-09 | PLAN-18 | Fake-clock expiry |
| P3-10 | PLAN-18 | Ignored remote cancellation |
| P3-11 | PLAN-17 | Schema/scope/resource negatives |
| P3-12 | PLAN-20 | Handoff/reconnect route |
| P3-13 | PLAN-20 | Admission caps and useful progress |
| P3-14 | PLAN-20 | Persistent-volume restart |
| P3-15 | PLAN-19 | Image/policy fixtures; live evidence PLAN-21 |
| P3-16 | PLAN-21 | Three-baseline comparison |
| P3-17 | PLAN-20 | Actual local media; live evidence PLAN-21 |

## Repository layout and local validation

### Code locations

| Component | Path | Responsibility |
| --- | --- | --- |
| Local runtime | `services/control_api`, `services/rtc_agent`, `apps/local-console` and `local-setup` | The implemented local runtime; operational entry points, not completed P1/P2/P3 libraries |
| P1 | `projects/agent-continuity/python` | P1's one canonical src-layout distribution, with `continuity_lab` retained as its import name |
| P2 | `projects/channel-continuity/src` | P2 TypeScript |
| P3 | `projects/delegation-reliability/python` and `specialist-ts/src` | P3 |
| Shared contracts | A small explicit contract area decided in PLAN-04 | Shared schemas and fixtures; owns data contracts, not application orchestration |

Root services consume P1's locked workspace member; there is no root shadow
core. Preserve installed examples, existing intake tests and schema identities.

### Package boundaries

- Choose an installable package/export boundary when a real second consumer
  needs it. Do not restructure working code merely to populate directories.
- At that checkpoint, build the Python wheel or npm pack artifact, install it in
  an isolated consumer outside repository import paths and execute the minimal
  public-API example.
- Test declared dependencies and exports, and forbid hidden service or sibling
  source imports.
- P3 may reuse P1's installed execution library without requiring P1's complete
  service deployment.
- Repeat these consumer checks at release.

### Validation lanes by work package

| Work packages | Validation added |
| --- | --- |
| PLAN-01 | The fast harness and existing tests |
| PLAN-02 and PLAN-03 | Process and store checks |
| PLAN-08 | PostgreSQL and migration jobs |
| PLAN-10 and PLAN-12 | Frozen dependency and TypeScript checks |
| PLAN-11 and PLAN-15 | Local media checks |
| PLAN-20 and PLAN-21 | Bounded integration and load jobs |

- Gate live-provider runs separately, using explicit credentials and spending
  limits. Never add them to offline checks.
- Every runner declares mode, prerequisites, timeout, cleanup and artifacts.
- Existing CI definitions may mirror those commands, but publishing or executing
  hosted CI is not required for the user-approved local POC.

### Work items and documentation updates

- Use a work item based on the [template](work-items/template.md) for each
  slice. Record behavior and IDs, owned files, interface/authority changes,
  failure schedule, existing commands, expected results and handoff.
- Update the nearest AGENTS.md, Design.md and README.md when commands or
  contracts change.
- Add an architecture decision when changing state authority, persistence,
  protocol or dependency choices.
- Documents use release versions and local scenario IDs for readability. Run
  artifacts retain the technical evidence required by the validation plan.

## Effort and scheduling

### Weekly budget

Reserve the weekly budget across building, tests, review and learning.

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Weekly budget | 12–15 hours per week | Building, tests, review and learning | Keep any coursework within it |
| Earlier envelope | 18–20 weeks | Historical planning context | Not a release date or a refreshed estimate of remaining work |

Coursework within the weekly budget reduces implementation time rather than
adding free capacity.

### Historical estimate

| Work stream | Historical initial effort range |
| --- | --- |
| First worker/recovery slice and CI | 18–26 hours |
| Durable business semantics | 32–46 hours |
| PostgreSQL and local deployment | 22–34 hours |
| SDK compatibility and real media | 24–36 hours |
| Channel SDK, media and handoff | 42–62 hours |
| Delegation, modalities and comparisons | 50–76 hours |
| Ecosystem release and review | 16–24 hours |
| Combined historical estimate | 204–304 hours |

The combined 204–304-hour range is the historical initial task estimate, not
remaining effort. Some infrastructure is now implemented, but no measured basis
exists to subtract a precise number of saved hours or promise a shorter date. A
preliminary task-sizing pass is now recorded in the granular roadmap. A measured
remaining-delivery forecast is still pending.

### Re-estimation and critical path

- Record actual qualification and PLAN-03 implementation, test and review time,
  then publish a revised remaining-work estimate.
- Re-estimate again after the first actual-media and cross-language slices.
  Include learning, dependency issues and review findings explicitly.
- Keep the critical path visible: persisted execution, atomic case authority,
  media integration, channel routing and remote-result applicability.
- Reduce optional experiments before weakening required invariants.

## Decisions and risks to resolve

| Question | Resolve in | Required artifact |
| --- | --- | --- |
| Smallest execution state, M1 migration and SQLite compatibility subset | PLAN-02 | Backend support decision, migration and transition tests |
| Early PostgreSQL adapter before full lifecycle expansion | After PLAN-03; early PLAN-08 pass | Common store contract and preserved M1 identities |
| Retention, replay horizons and safe tombstones | PLAN-04, before any cleanup | Late-replay/pruning fixture and explicit expired-identity policy |
| Supplier inquiry/effect identity and independent crash barrier | PLAN-03 | Failure contract and reproducible process test |
| Case schema, confirmation snapshot and intent transaction | PLAN-04 | Typed contract and transaction decision |
| Lease, clock and external idempotency assumptions | PLAN-08 | Backend contract and stale-worker evidence |
| Native package/runtime compatibility and browser/container addresses | PLAN-09 to PLAN-11 | Locked environment and actual-room smoke |
| Event semantic canonicalization and association trust | PLAN-12 | Shared positive/negative fixtures |
| Playback evidence available on each client/pipeline | PLAN-15 | Observation model and unknown-state tests |
| Native tools/subagent baseline and remote deployment justification | Before PLAN-17 | Controlled baseline and architecture decision |
| Bounded authenticated specialist invocation and single execution owner | PLAN-17 | Principal-binding/transport contract and replay/scope negatives |
| Bounded specialist context and invalidation/cancellation policy | PLAN-17/18 | Versioned schemas and lifecycle tests |
| Installable public package boundary | First real second consumer | Wheel/npm-pack isolated-consumer smoke |
| Numeric performance budgets on the actual development machine | PLAN-11 and PLAN-21 | Workload manifest and retained baseline |

Record decisions before the affected code expands. A failed compatibility or
correctness check produces a bounded fix or a documented scope revision. It does
not justify silently changing acceptance criteria or claiming a stronger result.

## Checkpoints to preserve in the next sessions

Preserve the completed P1 release and its original evidence. Rerun affected P1
gates when behavior or inputs change; unrelated project work does not require
another paid inference run. Follow the detailed P2/P3 plans and their actual
exits, and preserve these completed checkpoints in order:

| Checkpoint | Evidence to preserve |
| --- | --- |
| P2-I09/P3-I07B phase | Its normal/negative actual process, PostgreSQL, installed-artifact and regression evidence, and its retained failures |
| P2-I10 structured compare-and-set (CAS) routing | Its equivalent-authority, installed-artifact and regression evidence |
| P2-I11 linked exact confirmation | The completed confirmation, preserved together with P2-I10 |
| P2-I12 outbound intents and P2-I13 authenticated correlated callback evidence | Their selected migration, route/send/veto, installed-artifact and regression gates |
| P2-I14 explicit uncertain-send policy | Passed its selected actual and installed-consumer gates |
| P3-I08 | Same-ID concurrency and the passing registered P3-01/P3-03/P3-11 lab rows |
| P3-I09 and P3-I10 | Completed P3-I09 resumable applicability/event projections and completed P3-I10 delivery-only processing acknowledgement, with their selected phase/artifact gates |
| P3-I11 | Explicit refreshed applicability and profile-lifetime display retention |
| P3-I12 | Protected action/revision/cancellation schedules, which passed their selected gates through unchanged public authorities |
| P2-I15/I16 and P2-I17 | Selected P2-I15/I16 native/package qualification, and P2-I17's passing implementation/storage/media/artifact evidence plus 147 compatibility assertions |
| P2-I18 | Selected storage/media/artifact gates and 166 compatibility assertions |
| P2-I19 and P2-I20 | P2-I19 capacity/dormant-case and P2-I20 operational UI selected qualification |
| P2-I21 | Installed standalone and public-P1 results, recorded in the completed 0041 handoff |
| P3-I13/I14 | Source/installed process recovery and eighty compatibility assertions |
| P3-I15 | Selected standalone consumption, which passed its eight offline plus eight installed lab assertions |
| P3-I16 and P3-I17 | P3-I16 standalone image extraction, which passed selected local qualification, with P3-I17 fixed-policy evidence also selected-qualified |

These caveats travel with the checkpoints:

| Checkpoints | Caveat |
| --- | --- |
| P2-I09/P3-I07B | Its first useful-result/fake-effect path does not qualify later recovery gates |
| P2-I10 and P2-I11 | Retained inbox access supplies no current-association fence |
| P2-I10 and P2-I11 | A lost revision acknowledgement (ACK) remains unknown without a durable command receipt or rebase |
| P2-I12 to P2-I14 | Provider evidence, physical delivery, user acknowledgement and booking consent remain separate |
| P3-I08 to P3-I12 | Reuse the P3-I07B stable first-delivery receipt; do not create another execution queue or replace accepted identities |
| P2-I21 | P2-I22 retains the separate integrated release gate |
| P2-I15 to P2-I21 and P3-I13 to P3-I17 | Broader release qualification, complete charter rows and integrated media remain separate |

The later completed checkpoints (0041 to 0044) and the active joined
application (0045 to 0047) are summarized under [Current status](#current-status).

These are bounded slices, not calendar commitments. P2/P3 runtime and product
acceptance remain incomplete. Their current contract/baseline source is partial,
and no whole-project gate passes until all required assertions execute. Remote
CI and publication remain outside the local POC scope.
