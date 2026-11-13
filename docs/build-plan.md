# Ecosystem build plan

Status: Planned

Last reviewed: 13 November 2026

Build three independently usable libraries and one local reference application,
with an executable validation path for every required behavior. The current
implementation includes compatible M1 intake, PostgreSQL case/effect/lease
authority, an independent bounded worker, the native scripted G consumer/showcase
and the local operational harness. P1-01 through P1-05 retain SQLite acceptance/
recovery evidence; all twenty P1 rows now have passing retained reports in the
[selected-provider local release](work-items/0019-p1-phase-h-release-qualification.md).
Full ecosystem coverage remains pending because complete P2/P3 acceptance remains pending. The harness
catalog owns executable registrations; individual phase contributions do not
independently establish a complete product release.

The [gateway/issued checkpoint](work-items/0029-p2-gateway-and-p3-issued-execution.md)
adds P2-I08 and P3-I07A. The [completed bounded phase](work-items/0030-p2-agent-recovery-and-p3-completion.md)
implements P2-I09 owned scripted-agent process recovery and P3-I07B first durable
result delivery and independently confirmed fake action. P1 work-profile v3 adds
immutable recipient-bound delivery and guarded action receipts without replacing
its v1 accepted input or v2 issued execution. Work cancellation/deadline/result
eligibility and exact case authorization share one protected transaction; receiver
and supplier I/O remain outside it. P3 owns no second execution ledger. The selected
process, database, artifact and regression gates passed, completing I09 and full I07.
The [completed phase](work-items/0031-revision-routing-and-delegation-acceptance.md)
adds I10 structured revision routing and I08 concurrency/public inspection plus
complete registered P3-01/P3-03/P3-11 lab runners. Those three rows have fresh passing
reports; all 17 P2 and remaining 14 P3 rows stay planned. I10 selected qualification
is recorded separately. Default Docker/UI composition and
broader recovery/media/model/scale/integrated release remain pending.

[Portfolio scope](portfolio-scope.md) defines V1 boundaries, [shared design](../Design.md)
defines state authority and ports, and [validation plan](validation-plan.md)
defines evidence. The project charters remain authoritative for requirements:
[P1](projects/agent-continuity-scope.md), [P2](projects/channel-continuity-scope.md)
and [P3](projects/delegation-reliability-scope.md). This plan sequences their
implementation without adding a fourth framework or changing acceptance semantics.

The [completed linked-confirmation/result-projection phase](work-items/0032-linked-confirmation-and-result-projections.md)
completes P2-I11 and P3-I09 within their selected local scope; no complete
P2 or additional P3 acceptance row is registered. P2 uses immutable exact prompts
and a current-association preflight, then existing P1 atomic confirmation and
original-command receipts. P1 work v4 exposes result-only source-bound cursors; P3
checkpoints derived as-of observations without creating another execution owner.
Unknown acknowledgement, later work/case changes, delivery/event ACK and broader
recovery remain distinct. Neither addition changes default Compose/UI or the
qualified booking/native/provider behavior.

The [completed outbound-reply/processing phase](work-items/0033-outbound-replies-and-completion-processing.md)
completes P2-I12 and P3-I10 within their selected local scope; the actual and
installed gates passed. P2 preserves one
logical recipient/outbound identity, selects versioned authorized routes and
commits suppression/permission checks with possible-send reservation. P3 adds
only derived terminal ACKs and a separate bounded discovery cursor; an unknown
result stays unacknowledged while later eligible work can progress. P1 APIs,
work v4 and booking/native/provider behavior remain unchanged. Callbacks,
ambiguous resend policy, broader applicability/recovery and complete native/media
release remain separate. No automatic booking-completion integration or new
complete charter row is introduced.

The [completed callback/applicability phase](work-items/0034-callback-evidence-and-applicability-refresh.md)
retains selected passing P2-I13/P3-I11 evidence. Callbacks remain original-attempt
observations; refreshed applicability is non-atomic as-of metadata. Display hiding
preserves profile-lifetime replay identities and protected capacity.

The [completed send-policy/action-race phase](work-items/0035-send-policy-and-action-races.md)
completed the selected local gates for P2-I14 and P3-I12. Ordinary unknown
sends remain held. Only a separately configured cooperating idempotent provider
and a new trusted controller command can reserve an eligible same-operation retry.
P3 exercises both protected revision/intent lock orders and cancellation/effect
boundaries through existing public guards. At that checkpoint, P1's 77 and P3's 30 runtime payloads,
their authorities and default Compose/UI were unchanged. No new complete charter
row, automatic retry, external provider/inference call or full-release claim follows.

## Granular implementation tasks

The [granular roadmap](implementation-plan.md) decomposes these 22 work packages
into phase gates, shared support tasks and project-level implementation slices.
Use its linked [P1](implementation/p1-agent-continuity.md),
[P2](implementation/p2-channel-continuity.md) and
[P3](implementation/p3-delegation-reliability.md) plans for prerequisites,
deliverables, failure assertions, UI/telemetry evidence and task sizing. Those
implementation IDs do not replace acceptance IDs or redefine this plan's authority.
The granular roadmap's preliminary bottom-up sizing is not a measured delivery
forecast; re-estimate after the first actual recovery slice.

## Completed foundation and remaining scope

The repository now includes services/control_api, services/rtc_agent,
apps/local-console and [local-setup](../local-setup/README.md). Compose runs the
self-hosted media server, PostgreSQL, authenticated local API, deterministic
transport diagnostic worker and browser application. Named volumes, generated
credentials, health/readiness checks and lifecycle tooling establish a runnable
foundation. The live M1 API continues to use SQLite. Phase C now provides the
standalone PostgreSQL inquiry backend after controlled verified cutover. Phase D
adds exact case/quote/confirmation and durable continuation. Phase E implements
PostgreSQL v3 supplier effects, cancellation and atomic completion/outbox state;
its [final combined gate](work-items/0011-p1-phase-e-effects-and-completion.md) has
passed. Phase F implements P1-I19 through P1-I21 with its passed
[combined gate](work-items/0012-p1-phase-f-leases-and-deployment.md).
Phase G implements P1-I22 through P1-I25 with its inspected local combined
gate recorded in the [Phase G work item](work-items/0013-p1-phase-g-conversation-and-showcase.md). The opt-in business profile
connects a scripted native AgentSession to managed PostgreSQL work, bounded
authenticated case projections and separate exact quote approval. Explicit
media End retires the room; a fresh native consumer reloads the same owned
task. This is actual local browser/native media, not physical microphone
capture, live-model quality, automatic network-loss recovery or remote CI proof.
Original SQLite M1 and the diagnostic profile remain independently available.
The [H1 work item](work-items/0014-p1-phase-h-workload-baseline.md) records the
completed S-I06/P1-I27 local inquiry baseline. The
[reliability work item](work-items/0015-p1-reliability-workloads.md) owns later
passed restart/slow-dependency/saturation/shutdown results. P1 V1 is qualified for the local POC using provider_real v2. local_real remains unqualified and complete P2/P3 acceptance remains pending. P1-I26 host/Linux artifacts, independent API review and
genuine native consumer passed. The selected provider_real v2 gate passed both actual browser cases with cleanup. P1 V1 is qualified for the local POC using provider_real v2. The local_real implementation remains unqualified.

Native SDK smoke runs from the host and Docker passed actual text echo and
fixture-audio frame checks. Authenticated browser room/text, explicit
disconnect/reconnect and M1 acceptance/replay/conflict UI checks also passed.
The G business profile adds explicit bundled-WAV WebAudio publication, actual
WebRTC speech output, active interruption and fresh-room status from the same
durable task. Its STT/LLM are scripted and speech uses local PCM fixtures. Physical
microphone quality and configured inference remain unqualified. Remote Linux CI
is outside this local POC scope.
These contributions do not complete PLAN-09/10/11 or another full charter row.

| Work package | Existing foundation | Still required before completion |
| --- | --- | --- |
| PLAN-09 | Pinned Compose infrastructure, explicit business migrations, v4 worker profiles, preserved-state recovery and bounded lifecycle tooling | Complete supported-platform and release reproduction |
| PLAN-10 | Exact installed Python/TypeScript dependency locks and exercised SDK/container images | Remaining component/plugin compatibility, cross-language product contracts and full supported-platform promotion |
| PLAN-11 | Independent diagnostics plus native scripted business tools, scoped case UI, local browser audio/interruption/fresh consumer and inspected filtered traces | Physical microphone/live inference where required, seeded workloads, isolated artifact/API review and complete P1-20/release evidence |

The remaining plan preserves the product dependency order. Existing setup can be
reused by the first inquiry slice; infrastructure readiness must not be mistaken
for schema-safe execution or model behavior.

## Foundation qualification and current evidence

Retain the following foundation reproduction checks when changing the runtime.
Their historical baseline is distinct from the later G business profile and the
remaining supported-platform/hardware gates; they are not another product project
or a passing P1/P2/P3 acceptance case.

- Exercise authenticated browser connection, rejection of invalid credentials,
  room-scoped token behavior and disconnect/reconnect against the actual local
  server and named agent. Treat browser, host-SDK and container-SDK results as
  distinct observations.
- Verify text echo and the exact audio-diagnostic schema in the browser. Accept
  agent diagnostics only from the expected agent participant; correlate media
  evidence with the intended track. Use deterministic fixture text/audio where
  supported and test malformed or unexpected senders/diagnostics.
- Exercise microphone publishing only after the operator's explicit action and
  browser permission. Denial or unavailable permission must remain visible;
  native-SDK audio reception does not substitute for a browser microphone check.
- Recheck bounded cleanup, normal restart persistence and port/config behavior.
  Record which checks ran and which remain pending. A browser capability blocker
  is an explicit gap, not a successful interaction.
- Exercise the selected local host and Linux-container installation paths and
  retain their actual architectures. Remote CI/publication are outside this POC
  scope; an existing workflow file is only an optional automation reference.

Register foundation assertions separately from the 54 product scenarios. The
inquiry/recovery and later backend slices are already implemented; reproduce them
when affected rather than scheduling them as new work. A recorded browser-capability blocker does not stop
independent offline work; the affected required media gate remains pending and
must pass before the corresponding integrated release claim. The G local business-tool/interruption contribution belongs to PLAN-11; P2 playback
semantics remain under PLAN-15.

Observed foundation qualification is recorded in the
[audit work item](work-items/0004-plan-and-showcase-audit.md). Browser error recovery,
agent-presence admission, text and M1 UI transitions passed at that checkpoint.
The later [Phase G gate](work-items/0013-p1-phase-g-conversation-and-showcase.md)
adds actual scripted browser/native audio, active interruption, fresh-consumer
continuity and inspected raw Jaeger v3 traces. Hardware microphone capture,
network-loss media recovery and local_real remains unqualified; remote Linux
CI is outside this local POC scope;
no complete product acceptance row follows from these phase contributions.

## Development principles

Deliver one vertical slice at a time: a usable API, persisted behavior, a normal
path, a deterministic failure, and a diagnosable result. Begin with the smallest
worker/recovery slice using the existing Python environment. Installing LiveKit
or introducing PostgreSQL must not block that first inquiry demonstration.

Each work package produces code, relevant tests, harness registration, updated
status and a concise handoff. A planned acceptance ID becomes executable only
after its actual assertions exist. Registering a runner alone cannot complete it.
Retain the working baseline throughout; move code only for an established package
boundary, with import and test changes in the same slice. Keep one frozen,
validated dependency baseline within a feature slice; refresh compatible stable
direct versions at a new integration, an intentional upgrade or release gate,
rather than coupling ordinary feature edits to continuous dependency churn.

Use one case authority for confirmed facts, revisions and action intents. The
P1 booking API wraps the reusable TaskExecutionPort; P3 registers allowlisted
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

PLAN-10 can start alongside late P1 work. P2 schema work and a scripted P3
contract can proceed independently after shared interfaces stabilize. Keep one
primary implementation slice active for the learner; parallel reviews, fixtures
and documentation must not create competing contract definitions.

## Stage A First recovery slice

**PLAN-01 Baseline and scenario contract.** Record the current intake behavior,
the worker's inquiry permission and the exact crash barrier in a work item. Extend
the harness scenario metadata only as needed for a real process test. Keep
BASE-01 passing and leave unrelated P1/P2/P3 cases unimplemented. Add the first
local fast lane using the existing documented command, with no provider credentials.

**PLAN-02 Explicit execution record.** Add a versioned migration for queued M1
requests, a typed single-worker execution state and a stable inquiry effect ID
persisted before dispatch. Preserve original request identities and payloads.
Implement the smallest TaskExecutionPort adapter in the existing continuity_lab
boundary. Keep blocking SQLite work behind a bounded async boundary wherever it
is called by async code. Retain a pre-upgrade database fixture and test failed or
interrupted migration handling and intake replay before adding more workflow
states. Preserve the original data or a demonstrated restore path; do not assume
every migration can be reversed. Decide the supported SQLite compatibility subset
now: preserve M1 intake/migration and the first single-worker inquiry/recovery
path. Do not implicitly promise complete SQLite/PostgreSQL scheduler parity.
Document supported operations and explicit unsupported-operation errors. The
full V1 business execution backend will be PostgreSQL. Protects P1-01, P1-02,
P1-03 and P1-19.

**PLAN-03 Independent inquiry and recovery.** Create a persisted fake supplier
whose inquiry state survives independently of the worker. Run the worker as a
separate process. Stop it after supplier inquiry success and before local result
acknowledgement, then start a new worker and reconcile the same inquiry identity.
Inspect both stores and assert one logical inquiry and an unchanged booking.
Complete P1-04 and P1-05; retain the ordinary success path alongside the crash.

Stage A exits with a reproducible offline demonstration, process/effect history,
exact commands and an independently reviewed failure boundary. It does not add
booking mutation, model inference, SMS or distributed worker claims.

Immediately after PLAN-03, implement the early adapter portion of PLAN-08:
introduce the PostgreSQL single-worker store/execution adapter and run the shared
store contract for operations the SQLite subset supports. Preserve existing M1
identities through the documented import/migration path. Continue the richer
lifecycle on PostgreSQL instead of first duplicating a complete scheduler on
SQLite. This checkpoint does not establish leases, multi-worker coordination or
complete P1-15/P1-19; those remain the later PLAN-08 gate.

## Stage B Durable business semantics

Phase D provides PLAN-04/05 and the inquiry retry/deadline contribution to
PLAN-06. Phase E implements the mutation/cancellation/completion contributions
to PLAN-06/07, with its final combined gate passed. Phase F adds PLAN-08
coordination and PLAN-06/09 bounded admission/deployment contributions, with its
combined gate passed. P1 V1 is qualified for the local POC using provider_real v2. local_real remains unqualified and complete P2/P3 acceptance remains pending. Later P2/P3 platform and acceptance tasks remain planned.

**PLAN-04 Case authority and confirmation snapshot.** Implement a small scoped
case authority with expected-revision updates and immutable quote/confirmation
records. Define the trusted synthetic actor context separately from a caller's
scope label. Atomically validate actor, revision, quote, amount/currency, expiry
and confirmation and record the mutation intent with its dispatch event. The
committed intent is the action commitment point. Establish P1-06's contract,
complete P1-07's rejection cases, and seed cross-scope fixtures for P1-17.
Record the API and transaction decision before
adding an independently running service around this authority. Include the
retention/replay-horizon decision before adding cleanup: display-history pruning
and business deadline expiry cannot erase effect identities, confirmations or
idempotency protection needed by eligible replay. Define retained tombstones and
explicitly rejected expired identities, with a late-retry test after pruning.

**PLAN-05 Persisted waits and signals.** Store absolute business deadlines and
typed deduplicated signals, including signals arriving before their matching
wait. A waiting workflow consumes no permanently sleeping coroutine. Add a
controllable clock and deterministic assertions for restart, early/late signals,
altered replay and unrelated callbacks. Complete P1-10 and P1-11.

**PLAN-06 Retry, cancellation and resource lifecycle.** Classify definitive and
transient failures, bound attempts/backoff and apply deadline eligibility. Record
cancellation separately from execution state. Use barriers to race confirmation
against cancellation at the commitment transaction. Preserve the postcommit
best-effort boundary and keep speech interruption separate from business
cancellation. Test admission limits, bounded shutdown and resource cleanup.
Complete P1-12, P1-13, P1-14 and P1-18.

**PLAN-07 Fake mutation, uncertainty and result events.** Apply an explicitly
confirmed fake change using the persisted effect key. Repeat the crash boundary
for mutation and reconcile with a cooperating supplier. A second fake adapter
without safe deduplication/lookup must produce an uncertain result after an
ambiguous dispatch. Commit final state and a stable completion-event intent
together; recover outbox delivery after a crash. Complete P1-06, P1-08, P1-09 and
P1-16. Recheck the normal authorized path and cross-scope rejection.

Stage B exits with the complete single-worker business lifecycle, minimal API
examples and deterministic effect/cancellation contracts. No unconditional
exactly-once external effect is claimed.

## Stage C Multi-worker local execution

**PLAN-08 PostgreSQL adapter and coordination.** This package has two passes.
The single-worker adapter/store-contract pass runs immediately after PLAN-03,
before Stage B expands the lifecycle. Build on the provisioned PostgreSQL service
and document the limited SQLite compatibility contract chosen in PLAN-02. The
coordination pass runs here after Stage B. Implement short claim/renewal
transactions and conditional writes using an execution epoch. Use independent
workers and barriers to prove lease takeover and stale-write rejection. Test
the old worker's external-call attempt separately against the supplier contract.
Rerun the common store contract on the explicitly supported SQLite subset and
PostgreSQL, then run PostgreSQL-specific multi-worker/lease assertions. Unsupported
SQLite operations fail explicitly instead of silently weakening guarantees.
Complete P1-15 and P1-17 and the
full migration/recovery evidence for P1-19.

**PLAN-09 Compose runtime and recovery.** The operational foundation described
above is implemented; this package remains partial until product recovery and
platform evidence pass. Extend the pinned images, example configuration,
health/readiness checks and named volumes with product migrations and synthetic
fixtures. Provide standalone project selection and an integrated selection as
services become available. Keep offline, lab and live modes explicit. Normal
stop/start preserves data; reset is a separate explicit operation. Validate
bounded startup/shutdown and container recovery with actual process termination.
Record PostgreSQL/worker logs and effect histories. This work supplies the common
deployment foundation used by P1-10, P1-18 and later P2/P3 restart scenarios.

Do not list future Compose commands in a runnable quickstart until they exist and
pass clean-setup tests. Validate macOS Docker Desktop and Linux networking
explicitly; a browser-visible address and a container-visible address can differ.

## Stage D Real media foundation

**PLAN-10 Latest-compatible stack promotion.** Current dependency locks, SDK
imports and local images provide initial evidence. Refresh official stable direct
selections at the integration/upgrade checkpoint, then hold the validated baseline
fixed within the feature slice. Resolve exact runtime/SDK/plugin dependencies,
maintain lockfiles and verify frozen installation. Follow [technology baseline](technology-baseline.md) rather than
independently upgrading incompatible transitive packages. Perform native imports
on declared architectures and add strict TypeScript compilation/test tooling
when that language's code is introduced. Complete the applicable provenance,
resolution and import checks in STACK-01 through STACK-03 now. STACK-04 is
completed incrementally with the actual project code and cross-language tests;
STACK-05/06 require later media/platform runs. Do not make full stack promotion
a circular prerequisite for creating the code that those gates must test.

**PLAN-11 Local LiveKit and browser adapter.** The actual self-hosted server,
browser console and SDK diagnostic worker exist. Extend this transport foundation
with the Python conversational agent and authenticated browser validation. Use
native AgentSession, tools, handoffs and AgentTask/TaskGroup where their
conversational semantics fit; durable business recovery remains P1's concern.
Evaluate the official Agents UI components for the product conversation client
at this checkpoint, preserving the small existing diagnostic console until a real
application consumer needs that integration. Use scripted inference and audio
fixtures first to establish transport, text, tool calls,
interruptions, disconnect/reconnect and shutdown without paid services. A tool
acknowledges durable acceptance without waiting for supplier completion. Exercise
slow storage/supplier conditions and measure event-loop responsiveness. Complete
the lab portion of P1-20 and STACK-05/STACK-06; retain the real-inference portion
for the portfolio gate. Add bounded local trace collection and correlated IDs.
Use the installed SDK's current chat-message/provider metrics, usage and session
report surfaces, with OpenTelemetry export where supported. Classify provider,
transport, validation, capacity and storage exceptions into structured safe
outcomes; retain observed causes internally without leaking credentials. Bound
exporter queues/timeouts and test exporter failure without blocking conversation.
[Tasks](https://docs.livekit.io/agents/logic/tasks/),
[session data and metrics](https://docs.livekit.io/testing/observability/data/).

P1 local-ready release can now run through its full acceptance matrix. Review its
standalone example, public API, migration instructions and failure contract before
publishing P1 claims. Continue P2/P3 work through the established ports.

## Stage E Channel continuity

**PLAN-12 TypeScript events and fake carrier.** Introduce strict TypeScript and
runtime-validated, versioned JSON event unions. Separate provider scope from
verified business-account scope. Define semantic payload canonicalization so a
metadata-only retry deduplicates while a changed message conflicts. Add shared
positive/negative fixtures exercised in Python and TypeScript. Implement the
fake carrier and minimal synthetic association flow, with signature and access
rejection cases. Cover P2-01, P2-02 and P2-12.

**PLAN-13 Durable intake and case routing.** Persist input before acknowledgement
and make dispatch recoverable after gateway or agent termination. Preserve stable
business-operation identities without promising exactly-one model invocation.
Use the case authority for competing commands and delayed/ambiguous confirmations.
Supply a standalone case store, scripted agent and operation port so the package
can run without P1/P3 services. Complete P2-03, P2-04, P2-05, P2-06 and P2-16.

**PLAN-14 Outbound delivery semantics.** Persist notification intents, attempts
and provider callbacks. Reordered callbacks retain appropriate stronger evidence
under an explicit provider rule. An acknowledgement lost after a non-idempotent
send remains uncertain under the documented resend policy. Add fake-provider
barriers for duplicate callback and ambiguous-send cases. Complete P2-10 and
P2-11; integrate P1 completion events without adopting workflow ownership.

**PLAN-15 Browser and playback continuity.** Route native LiveKit text through
the single durable acceptance path. Preserve generation, native interruption,
client playback and acknowledgement observations separately. Test real browser
audio interruption, loss of playback evidence and voice/chat/fake-SMS resumption
after room closure. Rehydrate authoritative current case state and bounded
history. Complete P2-07, P2-08, P2-09 and P2-15 using the lab media path first.

**PLAN-16 Bounded load and fresh-agent handoff.** Exercise bursts, inspectability
of accepted work and many dormant conversations without per-thread rooms. Add
measured admission/resource limits and a compact event timeline. Have a fresh
coding agent use only the repository instructions, fixtures and harness to make
one bounded change and diagnose its result. Complete P2-13, P2-14 and P2-17.
Review the standalone example and integrated P1 adapter for the P2 local gate.

## Stages F and G Delegation reliability

Before PLAN-17, retain a small tools/native-local-subagent baseline using the same
bounded capability input and controlled outcomes. Record useful progress,
conversation responsiveness and observed overhead. Decide why an independent
TypeScript service is warranted by process/language isolation or recovery needs.
This decision precedes remote-service implementation; it does not replace the
final three-way model/performance comparison required by P3-16 in PLAN-21.

**PLAN-17 One remote specialist contract.** Implement the Python coordinator and
one scripted TypeScript capability behind a bounded authenticated HTTP invocation.
P1 owns durable acceptance, attempt identity, retry/deadline eligibility and result
persistence. Each remote invocation belongs to one P1-owned attempt. Status,
cancellation and result endpoints expose correlated attempt observations rather
than a second recovering queue or scheduler. A lost HTTP response follows P1's
stable logical identity, duplicate handling and retry policy.

Bind scope to a verified local service principal and authorize invocation, status,
result, cancellation and scoped image access. A JSON tenant label alone grants
no authority. Reuse TaskExecutionPort, CaseAuthorityPort and ResultDeliveryPort
through small local adapters. Validate immutable context, scope, schema versions
and size limits in both languages. Demonstrate a current useful result, a minimal
stale-result rejection and same-ID conflict before additional capabilities. The
full applicability/race suite remains PLAN-18. Cover P3-01, P3-03 and P3-11.

The TypeScript specialist needs runtime schemas and capability/provider clients;
install Node Agents/RTC native peers only if it actually hosts a Node realtime
agent. Matching the stack does not require a redundant media participant.

**PLAN-18 Result applicability and recovery.** Add durable delegation/result
metadata, duplicate-completion handling, deadline eligibility and separate
cancellation/invalidation observations. Use barriers for result/revision/intent
races; accept zero stale actions while a valid current result still progresses.
Terminate specialist/coordinator processes and recover through P1's execution
contract. Cover P3-04, P3-05, P3-06, P3-07, P3-08, P3-09 and P3-10.

**PLAN-19 Two bounded capabilities.** Add static booking-image extraction and
fixed, versioned policy analysis. They may share one service. Implement fixture
cases for missing/ambiguous fields, evidence references, invalid output and
adversarial document text. Neither capability receives mutation or delivery
authority. Complete P3-15 in deterministic mode; actual model outcomes are
verified separately in PLAN-21. Continuous video and additional roles stay out.

**PLAN-20 Responsive conversation and result routing.** Keep conversation active
while a specialist is held on a barrier. Deliver through a stable route after
handoff/reconnect. Exercise per-tenant/global caps, useful progress for another
admitted tenant and container restart using the same volumes. Complete P3-02,
P3-12, P3-13, P3-14 and the lab portion of P3-17.

**PLAN-21 Baselines, live inference and performance.** Extend the pre-PLAN-17
baseline into the final three-way comparison. Compare single-agent tools,
native local subagents and remote specialists on the same task, controlled input
and equivalent provider/model configuration. Record unavoidable context
differences. Measure first audible and meaningful response, useful-result time,
queue/recovery delay, event-loop lag, resource use, task correctness and cost.
Complete P3-16 and the live portions of P1-20/P3-17. Verify screenshot/policy
outcomes with selected real models and compare them with fixture expectations.
Optional provider or carrier experiments cannot become default local dependencies.

## Stage H Ecosystem release

**PLAN-22 Release and independent review.** Reproduce setup from a clean
environment, run every implemented scenario in its designated lane, and check
standalone examples as well as integration. Retain environment/dependency evidence
for STACK-07. Review APIs, failure contracts, docs and supported commands
independently. Record actionable findings and resolve them or explicitly narrow
the claim. Produce short success/failure demos and sanitized benchmark summaries.

Local-ready V1 requires all 54 product cases in their local portions, actual local
media, supported-platform setup, migrations, recovery and bounded resource tests.
Portfolio-ready V1 adds retained real-model behavior, outcomes/costs, baseline
comparisons, API review and demonstrations. A skipped, timed-out or unimplemented
required scenario leaves the corresponding gate incomplete. A local scripted
inference result cannot establish model quality.

## Acceptance coverage

Each of the 54 required IDs has a primary implementation package below. The
charter supplies the exact assertions; integration and release rerun relevant
cases without changing their meaning.

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

## Repository and local validation progression

The implemented local runtime lives in services/control_api, services/rtc_agent,
apps/local-console and local-setup. These paths provide operational entry points;
they are not completed P1/P2/P3 libraries.

P1 now has one canonical src-layout distribution under
projects/agent-continuity/python, with continuity_lab retained as its import name.
Root services consume its locked workspace member; there is no root shadow core.
Preserve installed examples, existing intake tests and schema identities. Add P2
TypeScript under projects/channel-continuity/src
and P3 under projects/delegation-reliability/python and specialist-ts/src. Keep
shared schemas/fixtures in a small explicit contract area decided in PLAN-04;
that area owns data contracts, not application orchestration.

Choose an installable package/export boundary when a real second consumer needs
it; do not restructure working code merely to populate directories. At that
checkpoint build the Python wheel or npm pack artifact, install it in an isolated
consumer outside repository import paths and execute the minimal public-API
example. Test declared dependencies/exports and forbid hidden service or sibling
source imports. P3 may reuse P1's installed execution library without requiring
P1's complete service deployment. Repeat these consumer checks at release.

Local validation begins with the fast harness and existing tests in PLAN-01. Add process/store
checks with PLAN-02/03, PostgreSQL/migration jobs with PLAN-08, frozen dependency
and TypeScript checks with PLAN-10/12, local media checks with PLAN-11/15, and
bounded integration/load jobs with PLAN-20/21. Gate live-provider runs separately
using explicit credentials and spending limits; never add them to offline checks.
Every runner declares mode, prerequisites, timeout, cleanup and artifacts. Existing
CI definitions may mirror those commands, but publishing or executing hosted CI
is not required for the user-approved local POC.

Use a work item based on the [template](work-items/template.md) for each slice:
behavior and IDs, owned files, interface/authority changes, failure schedule,
existing commands, expected results and handoff. Update nearest AGENTS.md,
Design.md and README.md when commands or contracts change. Add an architecture
decision when changing state authority, persistence, protocol or dependency
choices. Documents use release versions and local scenario IDs for readability;
run artifacts retain the technical evidence required by the validation plan.

## Effort and scheduling

Reserve 12–15 hours per week across building, tests, review and learning. Keep any
coursework within that budget; it reduces implementation time rather than adding
free capacity. The earlier 18–20-week envelope is historical planning context,
not a release date or a refreshed estimate of remaining work.

| Work stream | Historical initial effort range |
| --- | --- |
| First worker/recovery slice and CI | 18–26 hours |
| Durable business semantics | 32–46 hours |
| PostgreSQL and local deployment | 22–34 hours |
| SDK compatibility and real media | 24–36 hours |
| Channel SDK, media and handoff | 42–62 hours |
| Delegation, modalities and comparisons | 50–76 hours |
| Ecosystem release and review | 16–24 hours |

The combined 204–304-hour range is the historical initial task estimate, not
remaining effort. Some infrastructure is now implemented, but no measured basis
exists to subtract a precise number of saved hours or promise a shorter date.
A preliminary task-sizing pass is now recorded in the granular roadmap; a
measured remaining-delivery forecast is still pending. Record actual qualification
and PLAN-03 implementation/test/review time, then publish a revised remaining-work
estimate. Re-estimate again after the first actual-media and cross-language
slices; include learning, dependency issues and review findings explicitly. Keep
the critical path visible: persisted execution,
atomic case authority, media integration, channel routing and remote-result
applicability. Reduce optional experiments before weakening required invariants.

## Decisions and risks to resolve during the relevant slice

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
correctness check produces a bounded fix or a documented scope revision; it does
not justify silently changing acceptance criteria or claiming a stronger result.

### Current local P1 qualification

P1 V1 is implemented and locally qualified with selected provider_real v2.
The final 20-case index, current P1-18/P1-14/P1-20, full H2, PostgreSQL, installed
host/Linux artifacts and shared quality gates passed with independent reviews.
Historical checkpoints retain their original scope. local_real remains unqualified;
complete P2/P3 acceptance remains pending, and hosted CI/publication are outside this local POC.

### Review-driven follow-ups

The [architecture review disposition](work-items/0020-architecture-audit-reconciliation.md)
is the current findings map. Preserve the qualified P1 V1 baseline. Select the
[bounded operational extension](work-items/0021-p1-operational-safety-extensions.md)
before claiming restored-database recovery or manual uncertainty resolution; it
is additional post-V1 scope, not an unrecorded prerequisite of the completed gate.
P2/P3 may still begin their independent contract/baseline tasks at the existing
frontiers. Their charters/task plans now require stronger association lifecycle,
recipient/route, source grounding and protected commitment tests. No fourth
project, remote CI, real carrier requirement or dependency upgrade is added.

The user selected P2 contracts and the independent P3 controlled baseline as the
next work on 10 November. The additional operational extensions remain planned;
they do not block these standalone slices. Core compaction remains conditional
before sustained reclamation. Human consumer feedback and dependency-tool
qualification retain their own future evidence requirements.

### Preserved rehydration and standalone checkpoints

Preserve the [completed native/deadline checkpoint](work-items/0036-native-input-and-deadline-cancellation.md):
selected P2-I15/I16 actual native/artifact and P3-I13 temporal gates passed.
The [completed playback/recovery handoff](work-items/0037-playback-evidence-and-process-recovery.md)
records the current selected scope and retained failure provenance.

P3-I14 passed seventeen source and the same seventeen installed recovery assertions,
each with eight owned process kills and one actual two-waiter issuance graph.
Eighty compatibility assertions also passed across execution, processing,
applicability, action-race and deadline lanes, with complete cleanup and unchanged
P1/P3 runtime payloads. Original issuance replay never invokes; only an explicitly
new eligible command can do so. Unknown possible delivery remains lookup-only,
while separate current work progresses. P1 remains the sole durable authority.

P2-I17 completed its selected communication scope: the sixteen-case PostgreSQL
storage gate, three-group actual browser/media gate, isolated npm consumer and
then-qualified eight-payload Python package with ninety-four unadapted tests passed.
All 147 P2 compatibility assertions passed. Final shared phase closure is recorded
separately in the linked handoff. Generated text, SDK progress, client-reported
playback and business consent remain separate facts. The current
[case rehydration/standalone phase](work-items/0038-case-rehydration-and-standalone-release.md)
completed selected P2-I18 and P3-I15. P2 passed eighteen storage assertions, three
actual room/voice/text/SMS browser groups and 166 compatibility assertions. Its
nine-payload Python distribution passed 111 unadapted tests across fifteen
commands; the 96-payload npm consumer passed seven stages with actual P2
PostgreSQL/HTTP and explicitly synthetic case/operation ports. P3 passed sixteen
installed assertions: eight offline and eight local lab assertions, including one
owned caller-process kill, original replay and complete cleanup. That checkpoint preserved thirty Python and sixteen npm payloads and the
seventy-seven-payload P1 dependency; the later image slice is additive.

Loaded case/history and source-qualified response facts are separate non-atomic
as-of observations. Loading creates no execution, speech or consent authority;
P1 revision0 is read-only under the existing positive-revision native command
contract. Original receipts survive replay, and cleanup retains shared readers and
owned work until dependent clients/processes actually settle.

Final shared gates passed 2,148 Python and 1,224 TypeScript checks, broad/strict
Python typing for 144/132 sources, formatting for 387 Python files, 113-document
validation and syntax parsing for all 29 Mermaid bodies. Ordinary stack doctor and
eight smoke checks passed with ten audio frames and original M1 state preserved.
P2-I19 capacity/dormant-case experiments and P3-I16 standalone static-image
HTTP completed selected qualification in the current handoff.
Selected P2-I20 joined operational UI/telemetry and P3-I17 fixed-policy semantic
evidence passed in the 0040 handoff. Current P2-I21 and the qualified P3-I18A
durable prerequisite belong to 0041; P2-I22 and P3-I18B native/background work
retain their later release gates. The catalog remains fifty-five cases with twenty-four registered
runners; all seventeen P2 and fourteen remaining full P3 rows stay planned.

### Bounded workload and image qualification

The [completed work item](work-items/0039-bounded-channel-workloads-and-image-evidence.md)
owns P2-I19 and P3-I16. P2 implements a seeded steady/burst/saturation and 1,000-case
dormancy study plus bounded ordinary observer callbacks. P3 implements a separate
read-only image contract/HTTP path with actual PNG validation, explicit clarification,
independent synthetic-image facts and fresh installed consumers. Both selected
qualification lanes passed; no new complete acceptance row is registered.
P1's policy-only work authority and default stack remain unchanged. The current
0041 slice adds P2-I21 and explicit P3-I18A durable v2 consumption; P2-I22,
P3-I18B native/background work and full release remain separate.

## Next five development sessions

Preserve the completed P1 release and its original evidence. Rerun affected P1
gates when behavior or inputs change; unrelated project work does not require
another paid inference run. Follow the detailed P2/P3 plans and their actual exits:

1. Preserve the completed P2-I09/P3-I07B phase, its normal/negative actual process,
   PostgreSQL, installed-artifact and regression evidence, and retained failures.
   Its first useful-result/fake-effect path does not qualify later recovery gates.
2. Preserve completed I10 structured CAS routing and its equivalent-authority,
   installed-artifact and regression evidence together with completed I11 linked
   exact confirmation. Retained inbox access supplies no current-association fence. A
   lost revision ACK remains unknown without durable command receipt/rebase.
3. Preserve P2-I12 outbound intents and I13 authenticated correlated callback
   evidence with their selected migration, route/send/veto, installed-artifact and
   regression gates. I14's explicit uncertain-send policy passed its selected actual
   and installed-consumer gates. Provider evidence, physical delivery, user
   acknowledgement and booking consent remain separate.
4. Preserve I08 same-ID concurrency and the passing registered P3-01/P3-03/P3-11
   lab rows, completed I09 resumable applicability/event projections and completed
   I10 delivery-only processing acknowledgement with their selected phase/artifact
   gates, together with I11 explicit refreshed applicability and profile-lifetime
   display retention. I12 protected action/revision/cancellation schedules passed
   their selected gates through unchanged public authorities.
   Reuse the I07B stable first-delivery receipt; do not create another execution
   queue or replace accepted identities.
5. Preserve selected P2-I15/I16 native/package qualification and I17's passing
   implementation/storage/media/artifact evidence plus 147 compatibility assertions.
   Selected P2-I18 storage/media/artifact gates and 166 compatibility assertions
   passed. I19 capacity/dormant-case and I20 operational UI passed selected
   qualification. The current 0041 handoff owns I21 installed standalone/public-P1
   results; I22 retains the separate integrated release gate.
   Preserve P3-I13/I14 source/installed process recovery and eighty compatibility
   assertions. P3-I15 selected standalone consumption passed its eight offline plus
   eight installed lab assertions; I16 standalone image extraction passed selected local qualification, with I17 fixed-policy evidence also selected-qualified. Broader
   release qualification, complete charter rows and integrated media remain separate.

These are bounded slices, not calendar commitments. P2/P3 runtime and product
acceptance remain incomplete. Their current contract/baseline source is partial;
no whole-project gate passes until all required assertions execute. Remote CI and
publication remain outside the local POC scope.

## Operations and policy implementation frontier

The [operations and policy handoff](work-items/0040-operations-ui-and-fixed-policy-evidence.md) records completed selected P2-I20/P3-I17 qualification.
It adds an opt-in read-only operations UI/telemetry adapter and an explicit v2
fixed-policy HTTP contract with independent structural/factual verification.
Preserve all prior completed gates; these additions require fresh affected
storage/media, package, v1 policy/image and shared quality checks. No new complete
catalog registration is made. The [completed 0041 work item](work-items/0041-standalone-channel-and-durable-policy.md)
implements P2-I21's installed standalone application and the coherent typed v2
durable prerequisite for P3-I18. Selected P2 twenty/six/187, P3 source/installed twelve plus separate offline eight
and 146 compatibility assertions, and shared quality gates passed. Preserve the
handoff's exact historical/current source and archive attribution. Native background
conversation and its bounded UI read view follow that prerequisite; v1 completion,
projection and action remain explicitly separate. Full charter/release and model
evidence stay separately gated. Selected task results do not establish full release.

### Stable result seam and next integration dependency

The [0043 work item](work-items/0043-stable-result-delivery-and-return-context.md)
implements selected P3-I19/P2-I22 delivery/read prerequisites. Source qualification
passed sixteen storage and four return assertions; package and final aggregate
outcomes remain separately recorded there. Before native composition, persist a
versioned original P2 operation/input-receipt/digest binding through P1's existing
opaque work body, preserving the first accepted deadline and evidence on replay.
Then join one native SDK owner to A/B voice/text and signed simulated SMS. Model
calls, restart discovery, full charter registration and final video retain their
explicit later evidence. These additions create no new complete acceptance row.

### Qualified original-input prerequisites

The [0044 work item](work-items/0044-origin-bound-channel-policy.md)
implements selected P3-I19/P2-I22 original-input prerequisites without a new queue
or migration. Versioned facades, the narrow operation client and local bridge have
passing focused/shared tests and isolated package/fake-port checks. Its fourteen
actual PostgreSQL assertions passed, including independent original-input/work/result
joins and the owned commit-before-ACK kill. Existing 0043 result-return and P3
completion regressions passed after the shared changes. Integrated media,
restart/discovery, applicable providers and the final video retain their later
gates; no complete charter registration advances from these checks.

### Active joined application

The [0045 work item](work-items/0045-joined-native-channel-policy.md) owns the
joined local application. Phase 45A qualified the original/prepared/read and
installed contracts. Phase 45B implements public source, gateway, client and
executor composition. Explicit owner setup succeeds and preliminary actual
signed-SMS/execution/delivery joins are observed. The current-result producer is
component-tested and attached through one application-owned room facade. Room
control/attachment, the Node native prepare/context bridge and a single-session
scripted worker have scoped component qualification. The parent room/process
composition and complete frozen database/process gate remain pending. Phase 45C
joins actual native media and the compact browser journey. Phase 45D repeats installed/local packaging,
shared validation and the recorded demo. Preserve the existing acceptance IDs and
separate component evidence from complete P2/P3 charter requirements.
