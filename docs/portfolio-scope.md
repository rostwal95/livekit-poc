# LiveKit Agents portfolio scope

Status: Active
Last reviewed: 12 November 2026

Build three independently usable libraries and
one synthetic travel-support reference application. These are implementation
requirements. M1 intake and the local operational foundation are implemented;
P1-01 through P1-05 retain executable SQLite acceptance/recovery evidence. The
harness catalog owns current complete runner registrations; full product coverage
remains pending.

| Project | Primary language | Owns | Required V1 demonstration |
| --- | --- | --- | --- |
| [Agent Continuity Lab](projects/agent-continuity-scope.md) | Python | Durable execution, waits, attempts, cancellation intent, supplier effects, completion events | End the conversation, crash after a fake supplier effect, restart and reconcile |
| [Channel Continuity Kit](projects/channel-continuity-scope.md) | TypeScript, with a Python agent adapter | Durable message acceptance, channel association, delivery evidence, case routing | Resume a case across voice, browser text and simulated SMS, including interrupted speech and duplicate input |
| [Delegation Reliability Kit](projects/delegation-reliability-scope.md) | Python coordinator and TypeScript specialists | Scoped delegation, validated results, applicability and routing | Keep conversation responsive, revise the request, reject the old result, recover a specialist |

The linked project charters define acceptance IDs. [Design.md](../Design.md)
defines shared ownership and interfaces. [Validation plan](validation-plan.md)
defines release evidence. [Technology baseline](technology-baseline.md) defines
the version policy. The [build plan](build-plan.md) owns delivery sequencing. Changes to a V1 boundary must update those contracts and the
affected harness scenarios together.

## Implementation status

The [local setup](../local-setup/README.md) now provides Compose orchestration for
self-hosted LiveKit, PostgreSQL, a control API, an SDK transport diagnostic worker
and a browser console. The API exposes authenticated local token/dispatch
operations and the existing SQLite M1 intake. The explicit business profile
separately adapts managed PostgreSQL work; PostgreSQL readiness alone does not
establish business persistence. The
standalone P1 backend separately implements inquiry execution, exact consent and
durable continuation, with PostgreSQL v3 effects/cancellation/completion now
implemented with the passed [Phase E final gate](work-items/0011-p1-phase-e-effects-and-completion.md).

Host and Docker native-SDK smoke runs passed actual text echo and fixture-audio
frame checks without inference. Authenticated browser room/text, explicit data reconnect and real M1 UI
transitions also passed. G adds actual scripted browser/native WebRTC, active
speech interruption, fresh-room status from the same durable task and inspected
raw Jaeger v3 traces. The public RoomIO barrier and exact native readiness
attribute gate controls; alternate SDK SessionHost ingress is disabled. Physical
microphone quality, automatic network-loss media recovery and configured inference
remain unqualified. Remote CI is outside this local POC scope. This is partial operational evidence for
PLAN-09 through PLAN-11. P1 backend implementation
adds deterministic durable-execution evidence separately. Phase F implements
v4 leases, stale-write/effect handling and a bounded worker profile with its passed
[combined gate](work-items/0012-p1-phase-f-leases-and-deployment.md).
G conversational business integration has local evidence in its
[work item](work-items/0013-p1-phase-g-conversation-and-showcase.md). Cross-channel
continuity, specialist reasoning, configured real inference and full product
release remain pending.

### Current local P1 qualification

P1 V1 is implemented and locally qualified with selected provider_real v2.
The final 20-case index, current P1-18/P1-14/P1-20, full H2, PostgreSQL, installed
host/Linux artifacts and shared quality gates passed with independent reviews.
Historical checkpoints retain their original scope. local_real remains unqualified;
complete P2/P3 acceptance remains pending, and hosted CI/publication are outside this local POC.

The [completed linked-confirmation/result-projection slice](work-items/0032-linked-confirmation-and-result-projections.md)
adds explicit linked consent and resumable derived observations to the existing
P2/P3 V1 requirements. It creates no new charter row, default service or execution
authority. Selected local qualification passed; the existing 24 catalog registrations
and remaining 17 P2/14 P3 planned rows are unchanged.

The [completed outbound-reply/processing slice](work-items/0033-outbound-replies-and-completion-processing.md)
adds P2 communication intents/ordinary fake sends and P3 consumer-processing
metadata within existing V1 requirements. The selected local gates passed,
completing P2-I12/P3-I10; callbacks, ambiguous-send policy and full native release
retain their separate requirements.
Queued acceptance is not carrier delivery or human acknowledgement; a processing
ACK is not a source ACK, execution result or action permission. P1 remains the
execution/case owner. Default topology and the existing 24 registered cases are
unchanged; complete P2/P3 acceptance remains pending.

The [completed callback/applicability phase](work-items/0034-callback-evidence-and-applicability-refresh.md)
retains selected passing P2-I13/P3-I11 evidence. Callbacks remain original-attempt
observations; refreshed applicability is non-atomic as-of metadata. Display hiding
preserves profile-lifetime replay identities and protected capacity.

The [completed send-policy/action-race phase](work-items/0035-send-policy-and-action-races.md)
completed the selected local gates for P2-I14 and P3-I12. Ordinary unknown
sends remain held. Only a separately configured cooperating idempotent provider
and a new trusted controller command can reserve an eligible same-operation retry.
P3 exercises both protected revision/intent lock orders and cancellation/effect
boundaries through existing public guards. P1's 77 and P3's 30 runtime payloads,
their authorities and default Compose/UI remain unchanged. No new complete charter
row, automatic retry, external provider/inference call or full-release claim follows.

### Current native/deadline boundary

The [completed phase](work-items/0036-native-input-and-deadline-cancellation.md) keeps
three independently usable projects. P2-I15/I16 provides a distinct optional
native adapter and page with selected actual six-group native and isolated
installed-package gates passed. Final selected phase regression/shared gates passed. The explicit two-table owner v6 upgrade changes no default M1/P1
service or Compose profile. Native text and genuine committed voice enter one
durable input/operation path before SDK generation. All complete P2 rows remain
planned; later selected playback and room-rehydration tasks passed in their own handoffs.

P3-I13 passed eighteen selected source assertions, the same eighteen installed
assertions and forty-six compatibility assertions with unchanged P1/P3 production
runtime payloads. This qualifies the selected deadline/cancellation boundary,
not general recovery, a remote-stop guarantee or full P3 release. Preserve that
closed checkpoint while developing the separate scope below.

### Earlier playback/recovery checkpoint

The [completed 0037 handoff](work-items/0037-playback-evidence-and-process-recovery.md)
implements P2-I17 source-qualified response/text/SDK/browser evidence under explicit
owner v7. Its sixteen-case PostgreSQL storage gate, three-group actual browser/media
gate and isolated npm/Python artifact gates passed, including ninety-four unadapted
Python checks and 147 P2 compatibility assertions. This completes selected I17
qualification; final shared phase closure is recorded separately in the handoff.
Generated text and SDK completion never prove physical playback or consent.

P3-I14 passed seventeen source and the same seventeen installed recovery checks,
each with eight owned kills and one actual issuance-order graph, plus eighty
compatibility assertions. That checkpoint preserved P1's seventy-seven and P3's
thirty runtime payloads. Original issuance replay does not invoke, possible delivery without a
known receipt remains unknown, and a separately confirmed current result progresses
through existing public P1 guards. No autonomous recovery scheduler or source ACK
is added. P2-I18 current-case rehydration and P3-I15 broader standalone qualification
were planned at that checkpoint and passed their selected 0038 gates afterward.
The catalog remains fifty-five cases/twenty-four registrations;
all seventeen P2 and fourteen remaining P3 full rows stay planned.

## Reference application

Use fictional accounts, bookings, screenshots, prices and policies. A traveller
asks about changing dates. Investigation produces a quote. A separate explicit
confirmation of the exact quote and case revision is required before a fake
supplier can modify the fake booking. No real booking, payment or customer system
is involved.

The same case supplies examples for all three projects. Each library must also
have a small standalone example using narrow local adapters. Shared code is
limited to actual contracts and infrastructure; no fourth platform project is
introduced. P1 now exposes its standalone typed Python API to the native service
and isolated examples. Keep its built-artifact checks; define later P2/P3 exports
from actual consumers and test wheel/npm-pack artifacts outside checkout paths. Standalone
means no undeclared sibling source imports or full sibling service deployment;
it does not forbid depending on an installed narrow library contract.

## Fixed architecture decisions

1. Reuse LiveKit media, sessions, text streams, tools, handoffs and native local
   subagents. Add application continuity and reliability through explicit ports.
2. Separate session, conversation, case, workflow, delegation and delivery IDs.
   A business case can survive many rooms and periods without a running agent.
3. Keep one authority for current case facts, revisions and confirmed action
   intents. Messages, model summaries and specialist results are evidence, not
   competing case authorities.
4. Keep transactions short. Model, carrier and supplier calls run outside
   database locks and away from the conversational event loop.
5. Persist accepted work before acknowledgement. Use stable scoped identities
   and explicit changed-payload conflicts. Transport retries can repeat attempts;
   logical identity does not imply exactly-once execution.
6. Atomically validate the current revision and confirmation and record an action
   intent. This is the action commitment point. Later edits cannot silently
   rewrite that intent; cancellation follows the documented external boundary.
7. Keep execution outcome, result applicability, delivery evidence and user
   acknowledgement distinct. Preserve unknown observations as unknown.
8. SQLite supports the initial single-host lab. PostgreSQL is the required
   multi-worker V1 backend. Preserve SQLite M1 compatibility and the first inquiry
   crash demonstration, then introduce the PostgreSQL single-worker adapter before
   expanding the full lifecycle. The build plan defines the support checkpoint.
   Introduce no Redis, Kafka, Kubernetes or workflow platform in V1. Multi-worker
   application execution does not imply a distributed LiveKit media plane; V1
   retains one local SFU. Multi-server media infrastructure is separate future work.

LiveKit documents native conversational workflows and local agent execution.
Its text streams have no long-term persistence. Those boundaries explain the
application responsibilities above. [Workflows](https://docs.livekit.io/agents/logic/workflows/),
[text streams](https://docs.livekit.io/transport/data/text-streams/),
[local server](https://docs.livekit.io/transport/self-hosting/local/).

## Local execution modes

The local setup README owns the implemented lab-foundation commands. The mode
contracts below describe full product coverage to build; the current lab stack
provides transport diagnostics and M1 intake, not the completed project scenarios.
Future mode commands enter the quickstart only after implementation and validation.

| Mode | Required behavior | External services |
| --- | --- | --- |
| offline | Deterministic SDK, database, process-crash and contract scenarios with fake suppliers, SMS and models | None after tools, images and fixtures are installed |
| lab | Actual self-hosted LiveKit and browser media/text, local persistence, scripted inference and audio fixtures | None after setup; validates transport and lifecycle, not AI quality |
| live | The same local application and media infrastructure with configured real inference | Provider credentials and internet, or separately validated local inference |

Each project must run independently. An integrated mode composes the same
adapters. Optional real SMS and Cloud evaluation use separate explicit commands;
they cannot become prerequisites for the local suite. The explicit local_real
speech/model implementation uses prepared Whisper/Qwen/Piper; actual engine/media
qualification is pending. Local vision inference remains later hardware-dependent work.

The current Compose setup includes pinned images, example configuration, generated
local credentials, health/readiness checks, named volumes and bounded lifecycle
commands. Product releases additionally require business migrations, fixtures and
complete local host/container/media validation on the selected macOS host and
Linux containers. Remote CI is not required. Use no host-networking-only
assumption. Container-to-server and browser-to-server addresses must be tested
separately. Bind development services locally by default.

Restart reuses volumes and must preserve accepted state. Destructive reset is a
separate explicit command. A normal setup, test or shutdown command must never
erase the database. Offline tests must fail if they unexpectedly need a remote
model or paid service.

## Required coding agent interface

The root [AGENTS.md](../AGENTS.md), [Design.md](../Design.md) and
[README.md](../README.md) are the entry points. Each project work area has the
same three files:

- AGENTS.md identifies owned files, instructions, safe commands, protected
  invariants and verification requirements.
- Design.md identifies data flow, interface boundaries, failure semantics and
  the authoritative project charter.
- README.md identifies implemented capabilities, exact setup/run/test commands,
  environment variables, examples and evidence locations.

The [harness](../harness/README.md) must provide discoverable commands,
machine-readable scenario registration, predictable exit codes, deterministic
fixtures, isolated state, bounded execution and diagnostic artifacts. A fresh
coding agent must be able to select an acceptance ID, change one component, run
the relevant checks and explain a failure using repository context alone.

For every implementation slice, record its scope and acceptance IDs before code,
implement the smallest coherent behavior, run the relevant checks, inspect
failures, review the change and update capability status. Record assistance and
personal contributions accurately. No code-generation metric or line-count
target substitutes for understanding, correctness or usable APIs.

### Current local POC delivery target

The user clarified on 10 November 2026 that all code and validation should be
completed locally. GitHub publishing and remote CI runs are out of scope. Local
completion still requires the applicable functional acceptance assertions, bounded
resources, persistence/recovery, safe diagnostics, installed examples and actual
browser/media/inference evidence. Local Linux containers and the host are the
supported execution environments for this POC. Remote deployment, package-index
publication and hosted automation are future choices rather than blockers for
finishing P1 and starting P2. Keep measured local capabilities distinct from any
future production or global-capacity qualification.

## Build order and checkpoints

| Stage | Required result before proceeding |
| --- | --- |
| Foundation | Scope, instructions, harness, M1 and local infrastructure implemented; qualify actual browser authentication, sender/diagnostic handling and permitted media locally; hosted CI is outside scope |
| P1 A | Schema-safe SQLite M1 extension, one independent worker, persisted inquiry and deterministic crash/reconciliation; early PostgreSQL adapter follows before lifecycle expansion |
| P1 backend and integration | Phases A–G, H1 and H2 retain their passed local evidence; P1-I26 host/Linux artifacts, independent API/failure review and genuine native consumer passed; all twenty P1 rows are registered; P1 V1 is qualified for the local POC using provider_real v2. local_real remains unqualified and complete P2/P3 acceptance remains pending. |
| P2 | Preserve selected native, I17 playback, I18 current-case and I19 workload qualification; I20 operations UI/telemetry passed selected 0040 qualification; current I21 installed standalone/public-P1 results belong to 0041, while I22 and full acceptance remain separate |
| P3 | Preserve selected I14 recovery, I15 standalone and I16 image qualification; I17 fixed-policy evidence passed selected 0040 qualification, followed by I18 native background integration and final comparison/release |
| Integrated release | All acceptance IDs, standalone examples, local deployment, live evidence, benchmarks and documentation pass their release gates |

P1 remains the single durable execution owner for specialist attempts. Specialist
HTTP status, cancellation and result messages are scoped observations, not a
second durable scheduler. Bind remote requests to a verified service principal;
request-body scope is not authentication. Node Agents is conditional on an actual
Node-hosted realtime agent, not a prerequisite for every TypeScript capability.

Before cleanup exists, define replay horizons and retained idempotency/effect
tombstones. Business deadline expiry and display-history pruning cannot silently
permit a previously accepted operation to execute again.

The P1 A supplier effect is creation of a persisted investigation/inquiry. It does
not modify a booking. The later mutation crash demonstration requires the
separate confirmation contract first.

The [build plan](build-plan.md) owns work-package dependencies, effort estimates
and the next sessions. Re-estimate after the first worker/recovery slice using
actual implementation and learning time. Release evidence determines readiness.

## Definition of done

Two named gates prevent fake providers from being mistaken for completed AI
functionality:

- Local-ready V1 passes deterministic correctness, real-process recovery,
  Python/TypeScript contracts where relevant, PostgreSQL multi-worker scenarios,
  actual self-hosted media integration and local deployment checks. Applicable
  scenario IDs must execute; planned checks cannot count as passing.
- Portfolio-ready V1 additionally passes selected real-model voice and visual
  scenarios, records outcomes and costs, publishes meaningful benchmark evidence,
  provides a short success/failure demo and completes an independent API and
  failure-contract review.

Every release includes a minimal developer example, setup from a clean checkout,
guarantees and limitations, correlated traces, raw benchmark output and an honest
implemented-capability table. Mandatory deterministic invariants require exact
assertions. Model judgments supplement those assertions.

Cloud Agent Simulations are optional: they require a Cloud project, and text mode
does not exercise the audio pipeline. Local playback/interruption evidence must
come from actual audio/browser checks. [Agent Simulations](https://docs.livekit.io/testing/simulations/).

## Deferred scope

Live video, continuous screen analysis, robotics, avatars, general-purpose DAGs,
arbitrary coroutine replay, dynamic specialist marketplaces, production carrier
certification, real supplier mutations, payments, enterprise identity platforms,
multi-region failover and production-scale claims are outside V1. Follow upstream
changes and pursue small useful contributions during development; an upstream
merge is not a release prerequisite.

## Current evidence

The existing M1 suite establishes intake persistence, canonical payloads, scoped
replay/conflict behavior and fresh-process reads. Its database still stores queued
investigation requests only.

The local operational foundation adds API boundary tests and actual host/container
SDK text/audio smoke. Phases A/B add persisted inquiry and independent supplier
crash/reconciliation evidence; Phase C adds controlled PostgreSQL cutover, real
store parity and a trusted synthetic scope boundary. Phase D adds exact consent,
atomic intent/dispatch and persistent waits/signals/retry/deadlines. Phase E
implements supplier-bound v2 proposals, owner-only v3 upgrade, mutation
reconciliation/uncertainty, cancellation and durable completion delivery, with
its final combined gate passed. Browser
loading establishes application delivery only. The [local setup guide](../local-setup/README.md)
and [build plan](build-plan.md) separate this evidence from missing product
behavior and remaining compatibility checks. The standalone inquiry worker is
implemented alongside the historical single-worker effects boundary. Phase F
adds v4 server-time leases, conditional epoch guards, persisted capacity and
bounded pull-worker deployment with its final gate passed. The
[Phase G gate](work-items/0013-p1-phase-g-conversation-and-showcase.md) adds the
scoped native conversation/current-case UI, scripted local media and inspected
filtered traces. P1-I26 artifact/API/genuine-consumer review and H1/H2 inquiry/
reliability slices passed. Channel SDK, delegation
runtime and complete product release evidence remain open; remote CI is outside scope. Current complete runner registrations belong to the harness catalog; full product
coverage remains pending and missing rows are non-passing.
