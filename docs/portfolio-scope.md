# LiveKit Agents portfolio scope

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Define the V1 boundaries, execution modes and release definitions shared by the three projects |
| Audience | Engineers and coding agents who need to know what V1 must contain and what counts as a release |
| Scope | Shared V1 scope, architecture decisions, modes and release gates; excludes project acceptance IDs, which the charters own |
| Owns | V1 boundaries, execution modes and release definitions |
| Related | [Root design](../Design.md) · [Build plan](build-plan.md) · [Validation plan](validation-plan.md) · [Technology baseline](technology-baseline.md) |

## Overview

This document defines the V1 boundaries, execution modes and release definitions
shared by the three projects in this repository. It is for engineers and coding
agents who need to know what V1 must contain, which document owns each requirement
and what counts as a release. Project-specific requirements and acceptance IDs live
in the project charters.

Contents:

| Section | Purpose |
| --- | --- |
| Implementation status | What is implemented and qualified today |
| Reference application | The synthetic travel-support case |
| Fixed architecture decisions | The eight fixed architecture decisions |
| Local execution modes | The offline, lab and live modes |
| Required coding agent interface | Onboarding documents, harness and workflow |
| Build order and checkpoints | Stage gates and current stage status |
| Definition of done | The Local-ready V1 and Portfolio-ready V1 gates |
| Deferred scope | What V1 excludes |
| Current evidence | The evidence added by M1, the local foundation and each P1 phase |

### Projects

Build three independently usable libraries and one synthetic travel-support
reference application. These are implementation requirements.

| Project | Primary language | Owns | Required V1 demonstration |
| --- | --- | --- | --- |
| [Agent Continuity Lab](projects/agent-continuity-scope.md) | Python | Durable execution, waits, attempts, cancellation intent, supplier effects, completion events | End the conversation, crash after a fake supplier effect, restart and reconcile |
| [Channel Continuity Kit](projects/channel-continuity-scope.md) | TypeScript, with a Python agent adapter | Durable message acceptance, channel association, delivery evidence, case routing | Resume a case across voice, browser text and simulated SMS, including interrupted speech and duplicate input |
| [Delegation Reliability Kit](projects/delegation-reliability-scope.md) | Python coordinator and TypeScript specialists | Scoped delegation, validated results, applicability and routing | Keep conversation responsive, revise the request, reject the old result, recover a specialist |

### Authoritative documents

| Document | Purpose |
| --- | --- |
| Project charters, linked in the table above | Define acceptance IDs |
| [Design.md](../Design.md) | Defines shared ownership and interfaces |
| [Validation plan](validation-plan.md) | Defines release evidence |
| [Technology baseline](technology-baseline.md) | Defines the version policy |
| [Build plan](build-plan.md) | Owns delivery sequencing |

Changes to a V1 boundary must update those contracts and the affected harness
scenarios together.

### Terms

| Term | Meaning |
| --- | --- |
| V1 | The fixed first-version scope of each project |
| M1 | The original SQLite confirmed-investigation intake |
| PLAN-01 to PLAN-22 | The work packages in the build plan |
| Phase A to Phase H | The granular P1 implementation phases; H1 (declared inquiry workload baseline) and H2 (restart and slow-supplier workloads) are Phase H slices |
| Implementation task IDs | IDs such as P2-I15 that identify work items in the [granular roadmap](implementation-plan.md); not acceptance IDs such as P2-15 |
| Selected qualification | The gates chosen for one work item passed within that item's declared local scope; it never completes a full acceptance row by itself |
| scripted, local_real and provider_real | The trusted inference modes; the default is scripted |
| POC | Proof of concept |
| CI | Continuous integration |

## Implementation status

| Capability | Status | Evidence |
| --- | --- | --- |
| M1 intake and the local operational foundation | Implemented | [Local setup](../local-setup/README.md) |
| P1 V1 with selected provider_real v2 | Qualified | [P1 release work item](work-items/0019-p1-phase-h-release-qualification.md) |
| local_real inference profile | Not qualified | [Local-real operations guide](local-real-inference.md) |
| P2 and P3 | Partial: selected implementation tasks passed their own gates; complete acceptance remains pending | [P2 charter](projects/channel-continuity-scope.md) · [P3 charter](projects/delegation-reliability-scope.md) |
| Harness catalog registrations | Partial: full product coverage remains pending | [Harness guide](../harness/README.md) |

P1-01 through P1-05 retain executable SQLite acceptance and recovery evidence. The
harness catalog owns current complete runner registrations.

### Local foundation and media evidence

The [local setup](../local-setup/README.md) now provides Compose orchestration for
self-hosted LiveKit, PostgreSQL, a control API, an SDK transport diagnostic worker
and a browser console.

- The API exposes authenticated local token and dispatch operations and the
  existing SQLite M1 intake.
- The explicit business profile separately adapts managed PostgreSQL work.
  PostgreSQL readiness alone does not establish business persistence.

Host and Docker native-SDK smoke runs passed actual text echo and fixture-audio
frame checks without inference. Authenticated browser room/text, explicit data
reconnect and real M1 UI transitions also passed.

Phase G adds actual scripted browser/native WebRTC, active speech interruption,
fresh-room status from the same durable task and inspected raw Jaeger v3 traces.
Controls are gated by the public RoomIO barrier and the exact native readiness
attribute. Alternate SDK SessionHost ingress is disabled.

This media evidence has these limits:

- Physical microphone quality and automatic network-loss media recovery remain
  unqualified.
- The local_real inference profile remains unqualified. The separate provider_real
  v2 qualification is described under Current local P1 qualification below.
- Remote CI is outside this local POC scope.

This foundation and media evidence is partial operational evidence for PLAN-09
through PLAN-11.

### P1 backend phases

The standalone P1 backend separately implements inquiry execution, exact consent
and durable continuation. P1 backend implementation adds deterministic
durable-execution evidence separately from the operational foundation.

- PostgreSQL v3 effects, cancellation and completion are implemented, with the
  passed [Phase E final gate](work-items/0011-p1-phase-e-effects-and-completion.md).
- Phase F implements v4 leases, stale-write/effect handling and a bounded worker
  profile, with its passed
  [combined gate](work-items/0012-p1-phase-f-leases-and-deployment.md).
- Phase G conversational business integration has local evidence in its
  [work item](work-items/0013-p1-phase-g-conversation-and-showcase.md).

The Current evidence section lists what each phase added. Cross-channel continuity,
specialist reasoning, real-inference evidence for P2 and P3, and full product
release remain pending.

### Current local P1 qualification

P1 V1 is implemented and locally qualified with selected provider_real v2. The final
20-case index, the current P1-18, P1-14 and P1-20 runs, full H2, PostgreSQL,
installed host/Linux artifacts and shared quality gates passed with independent
reviews. Historical checkpoints retain their original scope.

local_real remains unqualified. Complete P2/P3 acceptance remains pending. Hosted CI
and publication are outside this local POC.

### P2 and P3 selected checkpoints

The completed work items below added P2 and P3 capability within existing V1
requirements. Each one records its exact qualification boundary. Later checkpoints
are summarized in the [build plan](build-plan.md) and in the implementation status
of each project charter.

| Capability | Status | Evidence |
| --- | --- | --- |
| Linked confirmation and result projections | Qualified | [0032](work-items/0032-linked-confirmation-and-result-projections.md) |
| Outbound replies and completion processing (P2-I12, P3-I10) | Qualified | [0033](work-items/0033-outbound-replies-and-completion-processing.md) |
| Callback evidence and applicability refresh (P2-I13, P3-I11) | Qualified | [0034](work-items/0034-callback-evidence-and-applicability-refresh.md) |
| Send policy and action races (P2-I14, P3-I12) | Qualified | [0035](work-items/0035-send-policy-and-action-races.md) |
| Native input and deadline cancellation (P2-I15, P2-I16, P3-I13) | Qualified | [0036](work-items/0036-native-input-and-deadline-cancellation.md) |
| Playback evidence and process recovery (P2-I17, P3-I14) | Qualified | [0037](work-items/0037-playback-evidence-and-process-recovery.md) |

#### Linked confirmation and result projections (0032)

The
[completed linked-confirmation/result-projection slice](work-items/0032-linked-confirmation-and-result-projections.md)
adds explicit linked consent and resumable derived observations to the existing
P2/P3 V1 requirements. It creates no new charter row, default service or execution
authority. Selected local qualification passed. The existing 24 catalog
registrations and the remaining 17 P2 and 14 P3 planned rows are unchanged.

#### Outbound replies and completion processing (0033)

The
[completed outbound-reply/processing slice](work-items/0033-outbound-replies-and-completion-processing.md)
adds P2 communication intents and ordinary fake sends, and P3 consumer-processing
metadata, within existing V1 requirements. The selected local gates passed,
completing P2-I12 and P3-I10. Callbacks, ambiguous-send policy and full native
release retain their separate requirements.

- Queued acceptance is not carrier delivery or human acknowledgement.
- A processing acknowledgement (ACK) is not a source ACK, an execution result or an
  action permission.
- P1 remains the execution and case owner.

Default topology and the existing 24 registered cases are unchanged. Complete P2/P3
acceptance remains pending.

#### Callback evidence and applicability refresh (0034)

The
[completed callback/applicability phase](work-items/0034-callback-evidence-and-applicability-refresh.md)
retains selected passing P2-I13/P3-I11 evidence. Callbacks remain original-attempt
observations. Refreshed applicability is non-atomic as-of metadata. Display hiding
preserves profile-lifetime replay identities and protected capacity.

#### Send policy and action races (0035)

The
[completed send-policy/action-race phase](work-items/0035-send-policy-and-action-races.md)
completed the selected local gates for P2-I14 and P3-I12.

- Ordinary unknown sends remain held. Only a separately configured cooperating
  idempotent provider and a new trusted controller command can reserve an eligible
  same-operation retry.
- P3 exercises both protected revision/intent lock orders and cancellation/effect
  boundaries through existing public guards.
- At that checkpoint, P1's 77 and P3's 30 runtime payloads, their authorities and
  default Compose/UI were unchanged.

No new complete charter row, automatic retry, external provider/inference call or
full-release claim follows.

#### Native input and deadline cancellation (0036)

The [completed phase](work-items/0036-native-input-and-deadline-cancellation.md)
keeps three independently usable projects.

- P2-I15/I16 provides a distinct optional native adapter and page. Its selected
  actual six-group native gate and isolated installed-package gates passed. Final
  selected phase regression and shared gates passed.
- The explicit two-table owner v6 upgrade changes no default M1/P1 service or
  Compose profile.
- Native text and genuine committed voice enter one durable input/operation path
  before SDK generation.
- All complete P2 rows remain planned. Later selected playback and room-rehydration
  tasks passed in their own handoffs.

P3-I13 passed eighteen selected source assertions, the same eighteen installed
assertions and forty-six compatibility assertions, with unchanged P1/P3 production
runtime payloads. This qualifies the selected deadline/cancellation boundary. It
does not qualify general recovery, a remote-stop guarantee or full P3 release.
Preserve that closed checkpoint while developing later scope, such as the checkpoint
below.

#### Playback evidence and process recovery (0037)

The
[completed 0037 handoff](work-items/0037-playback-evidence-and-process-recovery.md)
implements P2-I17 source-qualified response/text/SDK/browser evidence under
explicit owner v7.

- Its sixteen-case PostgreSQL storage gate, three-group actual browser/media gate
  and isolated npm/Python artifact gates passed. These include ninety-four
  unadapted Python checks and 147 P2 compatibility assertions.
- This completes selected I17 qualification. Final shared phase closure is recorded
  separately in the handoff.
- Generated text and SDK completion never prove physical playback or consent.

P3-I14 passed seventeen source and the same seventeen installed recovery checks,
each with eight owned kills and one actual issuance-order graph, plus eighty
compatibility assertions. That checkpoint preserved P1's seventy-seven and P3's
thirty runtime payloads.

- Original issuance replay does not invoke.
- Possible delivery without a known receipt remains unknown.
- A separately confirmed current result progresses through existing public P1
  guards.
- No autonomous recovery scheduler or source ACK is added.

P2-I18 current-case rehydration and P3-I15 broader standalone qualification were
planned at that checkpoint and passed their selected 0038 gates afterward. The
catalog remains fifty-five cases with twenty-four registrations. All seventeen P2
and fourteen remaining P3 full rows stay planned.

## Reference application

### Synthetic journey

Use fictional accounts, bookings, screenshots, prices and policies.

1. A traveller asks about changing dates.
2. Investigation produces a quote.
3. A separate explicit confirmation of the exact quote and case revision is
   required before a fake supplier can modify the fake booking.

No real booking, payment or customer system is involved.

### Examples and shared code

The same case supplies examples for all three projects. Each library must also have
a small standalone example using narrow local adapters. Shared code is limited to
actual contracts and infrastructure. No fourth platform project is introduced.

P1 now exposes its standalone typed Python API to the native service and isolated
examples. Keep its built-artifact checks. Define later P2/P3 exports from actual
consumers, and test wheel/npm-pack artifacts outside checkout paths.

Standalone means no undeclared sibling source imports and no full sibling service
deployment. It does not forbid depending on an installed narrow library contract.

## Fixed architecture decisions

1. **Reuse LiveKit.** Reuse LiveKit media, sessions, text streams, tools, handoffs
   and native local subagents. Add application continuity and reliability through
   explicit ports.
2. **Separate identities.** Separate session, conversation, case, workflow,
   delegation and delivery IDs. A business case can survive many rooms and periods
   without a running agent.
3. **One case authority.** Keep one authority for current case facts, revisions and
   confirmed action intents. Messages, model summaries and specialist results are
   evidence, not competing case authorities.
4. **Short transactions.** Keep transactions short. Model, carrier and supplier
   calls run outside database locks and away from the conversational event loop.
5. **Persist before acknowledgement.** Persist accepted work before
   acknowledgement. Use stable scoped identities and explicit changed-payload
   conflicts. Transport retries can repeat attempts. Logical identity does not
   imply exactly-once execution.
6. **Action commitment point.** Atomically validate the current revision and
   confirmation and record an action intent. This is the action commitment point.
   Later edits cannot silently rewrite that intent. Cancellation follows the
   documented external boundary.
7. **Distinct outcomes.** Keep execution outcome, result applicability, delivery
   evidence and user acknowledgement distinct. Preserve unknown observations as
   unknown.
8. **Storage and infrastructure.**
   - SQLite supports the initial single-host lab. PostgreSQL is the required
     multi-worker V1 backend.
   - Preserve SQLite M1 compatibility and the first inquiry crash demonstration.
     Then introduce the PostgreSQL single-worker adapter before expanding the full
     lifecycle. The build plan defines the support checkpoint.
   - Introduce no Redis, Kafka, Kubernetes or workflow platform in V1.
   - Multi-worker application execution does not imply a distributed LiveKit media
     plane. V1 retains one local selective forwarding unit (SFU). Multi-server media
     infrastructure is separate future work.

LiveKit documents native conversational workflows and local agent execution. Its
text streams have no long-term persistence. Those boundaries explain the
application responsibilities above. See
[workflows](https://docs.livekit.io/agents/logic/workflows/),
[text streams](https://docs.livekit.io/transport/data/text-streams/) and
[local server](https://docs.livekit.io/transport/self-hosting/local/).

## Local execution modes

The [local setup README](../local-setup/README.md) owns the implemented
lab-foundation commands. The mode contracts below describe full product coverage to
build. The current lab stack provides transport diagnostics and M1 intake, not the
completed project scenarios. Future mode commands enter the quickstart only after
implementation and validation.

| Mode | Required behavior | External services |
| --- | --- | --- |
| offline | Deterministic SDK, database, process-crash and contract scenarios with fake suppliers, SMS and models | None after tools, images and fixtures are installed |
| lab | Actual self-hosted LiveKit and browser media/text, local persistence, scripted inference and audio fixtures | None after setup; validates transport and lifecycle, not AI quality |
| live | The same local application and media infrastructure with configured real inference | Provider credentials and internet, or separately validated local inference |

### Independence and optional services

Each project must run independently. An integrated mode composes the same adapters.
Optional real SMS and Cloud evaluation use separate explicit commands. They cannot
become prerequisites for the local suite.

The explicit local_real speech/model implementation uses prepared local Whisper,
Qwen and Piper inference. Actual engine/media qualification is pending. Local vision
inference remains later hardware-dependent work.

### Compose setup and release requirements

The current Compose setup includes pinned images, example configuration, generated
local credentials, health/readiness checks, named volumes and bounded lifecycle
commands. Product releases additionally require business migrations, fixtures and
complete local host/container/media validation on the selected macOS host and Linux
containers. Remote CI is not required.

- Use no host-networking-only assumption.
- Test container-to-server and browser-to-server addresses separately.
- Bind development services locally by default.

### Restart and reset safety

Restart reuses volumes and must preserve accepted state. Destructive reset is a
separate explicit command. A normal setup, test or shutdown command must never erase
the database. Offline tests must fail if they unexpectedly need a remote model or
paid service.

## Required coding agent interface

### Entry-point documents

The root [AGENTS.md](../AGENTS.md), [Design.md](../Design.md) and
[README.md](../README.md) are the entry points. Each project work area has the same
three files:

| Document | Purpose |
| --- | --- |
| `AGENTS.md` | Identifies owned files, instructions, safe commands, protected invariants and verification requirements |
| `Design.md` | Identifies data flow, interface boundaries, failure semantics and the authoritative project charter |
| `README.md` | Identifies implemented capabilities, exact setup/run/test commands, environment variables, examples and evidence locations |

### Harness requirements

The [harness](../harness/README.md) must provide:

- discoverable commands;
- machine-readable scenario registration;
- predictable exit codes;
- deterministic fixtures;
- isolated state;
- bounded execution;
- diagnostic artifacts.

A fresh coding agent must be able to select an acceptance ID, change one component,
run the relevant checks and explain a failure using repository context alone.

### Slice workflow

For every implementation slice:

1. Record its scope and acceptance IDs before code.
2. Implement the smallest coherent behavior.
3. Run the relevant checks and inspect failures.
4. Review the change and update capability status.

Record assistance and personal contributions accurately. No code-generation metric
or line-count target substitutes for understanding, correctness or usable APIs.

### Current local POC delivery target

The user clarified on 10 November 2026 that all code and validation should be
completed locally. GitHub publishing and remote CI runs are out of scope.

Local completion still requires:

- the applicable functional acceptance assertions;
- bounded resources;
- persistence and recovery;
- safe diagnostics;
- installed examples;
- actual browser, media and inference evidence.

Local Linux containers and the host are the supported execution environments for
this POC. Remote deployment, package-index publication and hosted automation are
future choices rather than blockers for finishing P1 and starting P2. Keep measured
local capabilities distinct from any future production or global-capacity
qualification.

## Build order and checkpoints

| Stage | Required result before proceeding |
| --- | --- |
| Foundation | Scope, instructions, harness, M1 and local infrastructure implemented. Qualify actual browser authentication, sender/diagnostic handling and permitted media locally. Hosted CI is outside scope. |
| P1 A | Schema-safe SQLite M1 extension, one independent worker, persisted inquiry and deterministic crash/reconciliation. The early PostgreSQL adapter follows before lifecycle expansion. |
| P1 backend and integration | Phases A–G, H1 and H2 retain their passed local evidence. P1-I26 host/Linux artifacts, independent API/failure review and genuine native consumer passed. All twenty P1 rows are registered. |
| P2 | Preserve the selected native (P2-I15/I16), P2-I17 playback, P2-I18 current-case and P2-I19 workload qualification. P2-I22 and full acceptance remain separate. |
| P3 | Preserve the selected P3-I14 recovery, P3-I15 standalone and P3-I16 image qualification. After P3-I17, P3-I18 native background integration and final comparison/release follow. |
| Integrated release | All acceptance IDs, standalone examples, local deployment, live evidence, benchmarks and documentation pass their release gates. |

### Current stage status

| Capability | Status | Evidence |
| --- | --- | --- |
| P1 V1 for the local POC with provider_real v2 | Qualified | [P1 release work item](work-items/0019-p1-phase-h-release-qualification.md) |
| local_real profile | Not qualified | [Local-real operations guide](local-real-inference.md) |
| Operations UI and telemetry (P2-I20) | Qualified | [0040](work-items/0040-operations-ui-and-fixed-policy-evidence.md) |
| Installed standalone and public-P1 results (P2-I21) | Qualified | [0041](work-items/0041-standalone-channel-and-durable-policy.md) |
| Fixed-policy evidence (P3-I17) | Qualified | [0040](work-items/0040-operations-ui-and-fixed-policy-evidence.md) |
| Durable prerequisite within P3-I18 (I18A) | Qualified | [0041](work-items/0041-standalone-channel-and-durable-policy.md) |
| Native RTC text application within P3-I18 (I18B) | Qualified | [0042](work-items/0042-responsive-native-policy-and-compact-demo.md) |
| Complete P2/P3 acceptance | Planned | [P2 charter](projects/channel-continuity-scope.md) · [P3 charter](projects/delegation-reliability-scope.md) |

Broader integrated voice and result routing follows separately.

### Specialist execution ownership

P1 remains the single durable execution owner for specialist attempts. Specialist
HTTP status, cancellation and result messages are scoped observations, not a second
durable scheduler. Bind remote requests to a verified service principal.
Request-body scope is not authentication. Node Agents is conditional on an actual
Node-hosted realtime agent, not a prerequisite for every TypeScript capability.

### Replay horizons before cleanup

Before cleanup exists, define replay horizons and retained idempotency/effect
tombstones. Business deadline expiry and display-history pruning cannot silently
permit a previously accepted operation to execute again.

### First supplier effect

The P1 A supplier effect is creation of a persisted investigation/inquiry. It does
not modify a booking. The later mutation crash demonstration requires the separate
confirmation contract first.

### Scheduling and estimates

The [build plan](build-plan.md) owns work-package dependencies, effort estimates and
the next sessions. Re-estimate after the first worker/recovery slice using actual
implementation and learning time. Release evidence determines readiness.

## Definition of done

Two named gates prevent fake providers from being mistaken for completed AI
functionality.

| Gate | Required evidence | Notes |
| --- | --- | --- |
| Local-ready V1 | Deterministic correctness, real-process recovery, contracts, PostgreSQL multi-worker scenarios, self-hosted media integration and local deployment checks | Applicable scenario IDs must execute; planned checks cannot count as passing |
| Portfolio-ready V1 | Local-ready V1 plus selected real-model voice and visual scenarios, outcomes and costs, benchmark evidence, a demo and an independent review | Cloud Agent Simulations are optional and do not replace actual audio/browser checks |
| Every release | Minimal developer example, clean-checkout setup, guarantees and limitations, correlated traces, raw benchmark output and an honest capability table | Mandatory deterministic invariants require exact assertions; model judgments supplement them |

### Local-ready V1

Local-ready V1 passes deterministic correctness, real-process recovery,
Python/TypeScript contracts where relevant, PostgreSQL multi-worker scenarios,
actual self-hosted media integration and local deployment checks. Applicable
scenario IDs must execute. Planned checks cannot count as passing.

### Portfolio-ready V1

Portfolio-ready V1 additionally:

- passes selected real-model voice and visual scenarios;
- records outcomes and costs;
- publishes meaningful benchmark evidence;
- provides a short success/failure demo;
- completes an independent API and failure-contract review.

### Contents of every release

Every release includes a minimal developer example, setup from a clean checkout,
guarantees and limitations, correlated traces, raw benchmark output and an honest
implemented-capability table. Mandatory deterministic invariants require exact
assertions. Model judgments supplement those assertions.

### Cloud simulations

Cloud Agent Simulations are optional. They require a Cloud project, and text mode
does not exercise the audio pipeline. Local playback/interruption evidence must come
from actual audio/browser checks. See
[Agent Simulations](https://docs.livekit.io/testing/simulations/).

## Deferred scope

The following are outside V1:

| Area | Deferred item |
| --- | --- |
| Media and embodiment | Live video, continuous screen analysis, robotics and avatars |
| Orchestration | General-purpose directed acyclic graphs (DAGs), arbitrary coroutine replay and dynamic specialist marketplaces |
| Production integrations | Production carrier certification, real supplier mutations and payments, and enterprise identity platforms |
| Scale | Multi-region failover and production-scale claims |

Follow upstream changes and pursue small useful contributions during development.
An upstream merge is not a release prerequisite.

## Current evidence

The harness catalog owns current complete runner registrations. Full product
coverage remains pending, and missing rows are non-passing. The evidence so far:

| Capability | Status | Evidence |
| --- | --- | --- |
| M1 suite: intake persistence, canonical payloads, scoped replay/conflict behavior and fresh-process reads | Implemented | Existing M1 suite |
| Local operational foundation: API boundary tests and actual host/container SDK text/audio smoke | Implemented | [Local setup guide](../local-setup/README.md) |
| Phases A and B: persisted inquiry and independent supplier crash/reconciliation | Qualified | [Phase A](work-items/0007-p1-phase-a-execution-foundation.md) · [Phase B](work-items/0008-p1-phase-b-inquiry-recovery.md) |
| Phase C: controlled PostgreSQL cutover, real store parity and a trusted synthetic scope boundary | Qualified | [Phase C](work-items/0009-p1-phase-c-postgres-cutover.md) |
| Phase D: exact consent, atomic intent/dispatch and persistent waits/signals/retry/deadlines | Qualified | [Phase D](work-items/0010-p1-phase-d-authority-and-waits.md) |
| Phase E: supplier-bound v2 proposals, owner-only v3 upgrade, mutation reconciliation/uncertainty, cancellation and durable completion delivery | Qualified | [Phase E final combined gate](work-items/0011-p1-phase-e-effects-and-completion.md) |
| Phase F: v4 server-time leases, conditional epoch guards, persisted capacity and bounded pull-worker deployment | Qualified | [Phase F final gate](work-items/0012-p1-phase-f-leases-and-deployment.md) |
| Phase G: scoped native conversation/current-case UI, scripted local media and inspected filtered traces | Qualified | [Phase G gate](work-items/0013-p1-phase-g-conversation-and-showcase.md) |
| Phase H and P1-I26: artifact/API/genuine-consumer review and H1/H2 inquiry/reliability slices | Qualified | [H1](work-items/0014-p1-phase-h-workload-baseline.md) · [H2](work-items/0015-p1-reliability-workloads.md) · [P1-I26](work-items/0016-p1-standalone-package.md) |

These limits apply to the evidence above:

- The M1 database still stores queued investigation requests only.
- Browser loading establishes application delivery only.
- The standalone inquiry worker is implemented alongside the historical
  single-worker effects boundary of Phase E.

The [local setup guide](../local-setup/README.md) and [build plan](build-plan.md)
separate this evidence from missing product behavior and remaining compatibility
checks.

Channel SDK, delegation runtime and complete product release evidence remain open.
Remote CI is outside scope.
