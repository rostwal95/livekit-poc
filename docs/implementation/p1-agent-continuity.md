# P1 Agent Continuity Lab implementation plan

Status: Active
Last reviewed: 10 November 2026

## Purpose and authority

Implement a Python library for explicitly persisted business work that survives
conversation and process termination. The [P1 charter](../projects/agent-continuity-scope.md)
owns its 20 acceptance requirements; the [build plan](../build-plan.md) owns PLAN-01
through PLAN-22 sequencing. This document decomposes that sequence into bounded
implementation tasks without adding acceptance IDs or a second workflow platform.
Use [project instructions](../../projects/agent-continuity/AGENTS.md),
[shared design](../../Design.md), [validation](../validation-plan.md),
[observability](../observability.md), [demo strategy](../demo-plan.md) and the
[runtime decision](../decisions/0001-runtime-boundaries.md) with this plan.

All twenty P1 rows now have registered runners. P1-01 through P1-05 retain SQLite
acceptance/recovery evidence; retained P1-01 through P1-20 reports passed. Current qualification: P1 V1 is qualified for the local POC using provider_real v2. local_real remains unqualified and complete P2/P3 acceptance remains pending. A task
listed against an acceptance ID
contributes assertions; it does not pass the entire ID until every required
assertion and runtime lane for that row executes successfully.


Select applicable engineering gates from the [validation authority](../validation-plan.md)
for every task. Record Given/When/Then safety and useful-progress criteria, safe
producer log/error/metric assertions and actual test-mode evidence. Python work
follows the [engineering guide](../python-engineering.md); changed Design.md uses
the [standard template](../design-template.md). These are task completion rules,
not evidence that planned acceptance scenarios already pass.

## Current execution checkpoint

Phases A through G and Phase H are implemented with retained acceptance evidence.
P1-I26's typed library, independent public-API review and installed host/Linux
consumers passed. P1-I27's H1 historical inquiry baseline and current complete H2
restart/slow-dependency/saturation/shutdown workload retain distinct source scopes.
Fresh registered P1-18/P1-14 and selected provider_real v2 P1-20 passed, including
both actual provider browser cases. Final packaging, shared quality and the
independent 20-case index passed; the
[release work item](../work-items/0019-p1-phase-h-release-qualification.md) owns
exact results and limits. The optional local_real profile remains unqualified
under its original bounds. complete P2/P3 acceptance remains pending.

### Current local P1 qualification

P1 V1 is implemented and locally qualified with selected provider_real v2.
The final 20-case index, current P1-18/P1-14/P1-20, full H2, PostgreSQL, installed
host/Linux artifacts and shared quality gates passed with independent reviews.
Historical checkpoints retain their original scope. local_real remains unqualified;
complete P2/P3 acceptance remains pending, and hosted CI/publication are outside this local POC.

## Starting point and execution rules

Already implemented: confirmed-investigation intake in continuity_lab, SQLite
scoped replay/conflict, bounded intake capacity, API error/metric handling, the
local Docker stack, diagnostic SDK agent, browser text/reconnect and the visible
intake/replay/conflict proof. Reuse these; do not rebuild them as new milestones.

The standalone backend now implements exact quote confirmation, waits,
retry/deadline policy, supplier mutation/reconciliation, cancellation and durable
completion/outbox state. Phase E final verification passed. Phase F implements database-time leases,
epoch guards, persisted admission and bounded pull-worker deployment, with
its final combined gate passed. G adds scoped conversation tools/current-case UI,
actual scripted local browser/native audio and inspected raw Jaeger v3 traces.
Physical microphone quality, automatic network-loss media recovery, configured
P1 V1 is qualified for the local POC using provider_real v2. local_real remains unqualified and complete P2/P3 acceptance remains pending. Remote CI is
outside the local POC scope. The shared
foundation qualification ledger must distinguish these gaps. Offline schema and
worker tasks need not wait for model credentials or microphone permission; the
corresponding media/release gate remains incomplete until its evidence exists.

Task IDs P1-I01 through P1-I28 identify implementation work, not requirements.
Effort ranges cover prepared implementation, focused tests and a concise handoff;
they are planning estimates, not elapsed-time promises. Most tasks are two to four
hours. If the first coherent assertion will exceed that budget, split the task at
a named persistence or interface boundary and update the central plan. Keep one
primary implementation task active. Add integration/review contingency when
scheduling; do not count learning or investigation as free capacity.

## Phase P1-A: schema-safe execution foundation

**Entry:** current baseline and shared fast checks pass; the qualification ledger
records pending media/platform checks; no new worker is enabled against old data.
Primary paths are continuity_lab, tests and small harness extensions. Keep existing
CLI imports and M1 investigation-only behavior stable.

| Task | PLAN | Prerequisites | Concrete deliverable | Required failure assertion | Acceptance contribution | Effort |
| --- | --- | --- | --- | --- | --- | --- |
| P1-I01 | PLAN-01/02 | Shared foundation ledger and passing baseline | Write the execution work item, transition sketch, SQLite supported subset and exact crash timeline; decide public error/disclosure policy | Investigation consent cannot authorize mutation; unsupported SQLite lifecycle operations cannot silently downgrade behavior | P1-07, P1-19 preparation | 1–2h |
| P1-I02 | PLAN-01/03 | P1-I01 | Add owned-process control, named failpoints, deterministic clock and a pre-upgrade SQLite fixture to the existing harness | A child that was not terminated, zero tests, a timeout or required skip cannot produce a passing crash scenario | P1-04/05/19 harness | 2–3h |
| P1-I03 | PLAN-02 | P1-I01, P1-I02 | Introduce a versioned one-shot additive/new-table migration and typed execution/attempt records without altering original task identities or canonical requests | An interrupted/invalid migration preserves readable old data or a demonstrated restore path; old queued requests remain valid | P1-01, P1-19 | 3–4h |
| P1-I04 | PLAN-02 | P1-I03 | Implement the smallest allowlisted execution port, durable transition writes and a persisted inquiry effect identity before dispatch; retain bounded async storage offload | Concurrent/lost-ack identical submissions yield one identity; changed payload conflicts; the same key in a different scope remains independent | P1-01/02/03 | 3–4h |

Serving processes check their supported schema version rather than silently
performing new migrations on request/startup. Run the versioned SQLite migration
as an explicit controlled operation with its writes quiesced; it still needs
backup/rollback evidence even though the file owner supplies its permissions.
Use the separate one-shot migration principal for later PostgreSQL DDL.

**Exit:** an existing M1 database upgrades safely; intake survives termination of
its accepting process; replay/conflict assertions observe persisted state. There
is still no supplier booking mutation or claim of coroutine checkpointing.

**UI and signals:** preserve the current intake proof. New execution-state labels
remain unavailable until a real worker produces them. Record schema version,
acceptance/transition outcome and storage failures; keep request/case IDs in safe
logs or traces rather than metric labels.

## Phase P1-B: one independent inquiry and its crash window

**Entry:** P1-A migration and identity contract pass. A separate fake-supplier
store must outlive the worker. The worker runs as an independent process, not an
in-process coroutine pretending to restart.

| Task | PLAN | Prerequisites | Concrete deliverable | Required failure assertion | Acceptance contribution | Effort |
| --- | --- | --- | --- | --- | --- | --- |
| P1-I05 | PLAN-03 | P1-I04 | Implement persisted synthetic bookings/inquiries and a supplier port declaring stable-key deduplication and lookup capabilities | Reopening or terminating the worker does not reset supplier inquiry evidence; an inquiry never changes booking state | P1-04/05 fixtures | 2–3h |
| P1-I06 | PLAN-03 | P1-I04, P1-I05 | Execute one accepted inquiry through the allowlisted worker; persist attempt/result and bounded history | No external call occurs inside a database lock; definitive supplier rejection produces a typed outcome and the ordinary successful path still progresses | P1-04 | 2–4h |
| P1-I07 | PLAN-03 | P1-I02, P1-I06 | Stop the worker at supplier-success/before-local-acknowledgement; launch a new process and reconcile by the original effect identity | One logical inquiry is observed in the supplier store, the recovered result is persisted and booking state is unchanged | P1-05 | 3–4h |

**Exit:** run the normal inquiry and controlled crash/recovery without P2, P3,
LiveKit or paid inference. Inspect both independent stores and the actual process
termination. Register P1-04/05 only when those assertions execute.

**UI and signals:** extend the operator inspection view with observed execution
attempts and inquiry results. A harness-confirmed injected crash is an observation;
it must not become a fabricated business failure. Show recovery pending separately
from final inquiry outcome. Add attempt, inquiry dispatch, reconciliation and
completion observations with queue/recovery duration measurements.

## Phase P1-C: early PostgreSQL adapter and trusted scope

Historical Phase C checkpoint: P1-I08/I09/I10 and shared S-I05 were implemented.
The [Phase C work item](../work-items/0009-p1-phase-c-postgres-cutover.md) owns
that original gate/evidence. At that checkpoint, cancel/signal were unsupported
after scope checking and P1-17 was incomplete. PostgreSQL coordination then used
one cooperating session slot without distributed lease/epoch claims. Later phase
checkpoints above own the current lifecycle, lease and scope qualification.


**Entry:** preserve the completed SQLite inquiry crash proof. Introduce PostgreSQL
before implementing the richer lifecycle, using the already provisioned local
service. This is the early adapter pass of PLAN-08, not its multi-worker exit.

| Task | PLAN | Prerequisites | Concrete deliverable | Required failure assertion | Acceptance contribution | Effort |
| --- | --- | --- | --- | --- | --- | --- |
| P1-I08 | PLAN-08 early | P1-I07 and shared S-I05 migration setup | Apply PostgreSQL schema/versioning and repeatable quiesced M1/inquiry-state import through the shared one-shot migration principal, preserving requests, attempts, effect keys, known outcomes and timestamps | Interrupted/repeated cutover preserves accepted state; concurrent new intake is rejected before acknowledgement; no inquiry is recreated under a new effect identity | P1-01/02/03/05/19 | 3–6h |
| P1-I09 | PLAN-08 early | P1-I08 | Implement the single-worker PostgreSQL store/execution adapter; run the common contract on its supported operations and the declared SQLite subset | Unsupported SQLite operations fail explicitly; backend adapters agree on canonical replay/conflict and accepted-state reads | P1-01/02/03/04/05/19 | 3–4h |
| P1-I10 | PLAN-04/08 | P1-I09 | Derive trusted synthetic actor/scope at the application boundary and enforce scope-qualified get, signal, cancel and history access | A forged scope label or another principal cannot inspect, advance or cancel the original workflow under the chosen disclosure policy | P1-17 | 2–3h |

P1-I10 establishes the shared scope guard and tests the operations already
supported. Signal/cancel remain explicitly unsupported until P1-I13/P1-I17; repeat
the scope negatives against those real operations when implemented.

**Exit:** the first inquiry/recovery contract runs on PostgreSQL and supported
SQLite operations remain compatible. Continue full business execution on
PostgreSQL. Do not duplicate a complete distributed scheduler on SQLite or claim
lease/fencing correctness yet.

Use an explicit quiesced cutover: stop new acceptance, drain already admitted
writes, preserve a source backup, import/verify the original state, switch the
adapter only after validation, then re-enable admission. Shared task S-I05 owns
idempotent migration-credential/config/profile upgrades. PostgreSQL migrations run
under a one-shot migration principal; serving API/workers retain restricted runtime
roles and must not receive the bootstrap administrator secret. Verify required
schema grants for DML while asserting that runtime roles cannot create schema.
Retain existing credentials and volume-owner labels; a normal upgrade cannot
require destructive volume reset. Interrupted cutover must
resume from its recorded checkpoint or the preserved source. Do not create a
SQLite/PostgreSQL dual-write path or an undocumented live-migration promise.
Supplier evidence stays in its independent fixture store; no cross-store atomic
transaction is claimed.

**UI and signals:** expose the actual backend and migration state in operator
inspection, not the business consent prompt. A migration mismatch blocks the
new worker rather than making an old task appear newly accepted. Preserve the
existing safe HTTP error envelope and add backend/schema dimensions only from a
fixed vocabulary.

## Phase P1-D: case authority, exact consent and durable waiting

Implementation checkpoint: all four tasks are implemented on PostgreSQL v2.
The [Phase D work item](../work-items/0010-p1-phase-d-authority-and-waits.md) owns
observed gates; the [guide](../case-and-continuation.md) owns working APIs/demo.
At that Phase D checkpoint, supplier apply, cancellation, leases and event
delivery were later work; E/F subsequently implemented those boundaries.


**Entry:** the PostgreSQL adapter is available, trusted scope is explicit and the
case/intent transaction design is reviewed before mutation code is introduced.
Proposed application ports and operations remain those in the P1 charter and
shared design; they are not existing LiveKit SDK methods.

| Task | PLAN | Prerequisites | Concrete deliverable | Required failure assertion | Acceptance contribution | Effort |
| --- | --- | --- | --- | --- | --- | --- |
| P1-I11 | PLAN-04 | P1-I10 | Add case revision, immutable quote/confirmation types and canonical snapshots; decide replay horizons/tombstones before any cleanup | Missing/altered fields, invalid actor or expired quote cannot be upgraded into confirmation by a model summary; history pruning cannot erase effect protection | P1-07/17 and retention | 2–4h |
| P1-I12 | PLAN-04 | P1-I11 | Atomically validate actor, current revision, quote dates/amount/currency/expiry and matching confirmation, then commit one immutable action intent and its dispatch event | Each mismatch rejects before supplier invocation; revision/confirmation races have a documented transaction winner and no partially accepted intent | P1-06/07/13 | 3–4h |
| P1-I13 | PLAN-05 | P1-I09, P1-I11 | Implement persisted waits, absolute business deadlines and a typed deduplicated signal inbox; correlate early and late callbacks | Same payload deduplicates; altered replay conflicts; unrelated or stale confirmation cannot advance work; no permanently sleeping task retains a wait | P1-10/11 | 3–4h |
| P1-I14 | PLAN-06 | P1-I13 | Implement failure classification, eligible retry time, bounded attempts/backoff and fake-clock deadline evaluation | Permanent failure does not retry; exhausted/expired work stops; ambiguous external outcomes cannot be converted into blind transient retries | P1-12 | 3–4h |

**Exit:** valid inquiry results can wait across process loss and resume under the
same identity. A quote is visible separately from an exact explicit confirmation.
The final P1-10 gate also requires the container repetition in P1-I21.

**UI and signals:** show current case revision, quote identity, exact proposed
change, expiry and confirmation status. Confirmation sends a real command against
that snapshot; a stale response causes reinspection rather than silent resubmission.
Show waiting reason and persisted deadline. Record rejected confirmation/revision
and wait/signal outcomes, with no raw booking/transcript values in metrics.

## Phase P1-E: effects, cancellation and durable completion

**Implementation status:** P1-I15 through P1-I18 are implemented and passed the final
combined phase gate recorded in the
[work item](../work-items/0011-p1-phase-e-effects-and-completion.md). This does not
register additional product acceptance runners or complete the media/release lanes.

**Entry:** atomic action-intent commitment and signal/deadline behavior pass.
Only explicitly committed intents may invoke the fake apply capability.

| Task | PLAN | Prerequisites | Concrete deliverable | Required failure assertion | Acceptance contribution | Effort |
| --- | --- | --- | --- | --- | --- | --- |
| P1-I15 | PLAN-07 | P1-I12, P1-I14 | Apply exactly the confirmed fake booking revision through a persisted stable effect key and cooperating supplier adapter | Normal authorized work progresses; absent/stale/mismatched confirmation causes zero supplier apply calls | P1-06/07 | 2–3h |
| P1-I16 | PLAN-07 | P1-I15 | Repeat the effect-success/before-local-ack crash for mutation; add a noncooperating supplier variant | New process reconciles a cooperating effect without an incorrect duplicate; insufficient deduplication/lookup evidence persists uncertainty and performs no unsafe resend | P1-08/09 | 3–4h |
| P1-I17 | PLAN-06 | P1-I12, P1-I15 | Add idempotent cancellation commands, separate cancellation disposition and barrier-controlled confirmation/cancellation races | Precommit cancellation prevents apply; postcommit cancellation cannot claim reversal; altered cancellation replay conflicts | P1-13/14 | 3–4h |
| P1-I18 | PLAN-07 | P1-I16, P1-I17 | Commit final outcome plus stable completion-event intent atomically; deliver outbox with bounded retry to a cooperating standalone sink | Crash before delivery retains the event; repeated delivery retains one logical ID; late replay after diagnostic pruning remains deduplicated or explicitly rejected under the retention policy | P1-03/11/16 and retention | 3–4h |

**Exit requirement:** the single-worker PostgreSQL lifecycle covers confirmed mutation,
cooperative reconciliation, explicit uncertainty and durable completion delivery.
P1-14's actual speech-interruption repetition remains for P1-I25. State outcome,
cancellation disposition, event delivery and user acknowledgement stay separate.

**UI and signals:** show intent commitment, external evidence, result and delivery
as distinct observations. An uncertain outcome requires reconciliation; it must
not render as success or definitive failure. Cancellation displays requested,
observed and too-late/best-effort facts from actual responses. Completion delivery
can fail while business execution remains successful. Add fixed outcome/error
counts from the authenticated service and safe effect/worker/delivery events.
This Phase E checkpoint did not include exported conversation traces or a business
UI. G later adds the scoped native consumer, managed case projection and filtered
application/SDK trace path; [observability](../observability.md) defines its actual
span coverage. Original M1 remains a separate compatible route.

## Phase P1-F: multi-worker coordination and bounded deployment

**Implementation status:** P1-I19 through P1-I21 are implemented and passed the
[combined phase gate](../work-items/0012-p1-phase-f-leases-and-deployment.md).
Phase E's 440 offline and 186 PostgreSQL tests remain historical evidence. V4
adds explicit server-time task leases and retained execution epochs; attempt
generation tokens remain a different identity. No complete acceptance runner or
media/platform release gate is implied by this implementation status.

**Entry:** single-worker business semantics pass on PostgreSQL. Extend coordination
without changing intent commitment or the supplier's declared effect contract.

| Task | PLAN | Prerequisites | Concrete deliverable | Required failure assertion | Acceptance contribution | Effort |
| --- | --- | --- | --- | --- | --- | --- |
| P1-I19 | PLAN-08 coordination | P1-I18 | Add short claim/renewal transactions, lease expiry and conditional writes under an execution epoch | Two independent workers cannot own the current write authority; an old worker resumed after takeover cannot commit a stale update | P1-15 | 3–4h |
| P1-I20 | PLAN-08 coordination | P1-I16, P1-I19 | Pause an old worker at the external-call boundary and resume it after lease expiry | Supplier cooperation prevents an incorrect duplicate effect, or uncertainty is exposed; a database fence alone never passes external-effect safety | P1-09/15 | 3–4h |
| P1-I21 | PLAN-06/08/09 | P1-I18, P1-I20 | Enforce pending/active admission and graceful shutdown; add the actual P1 worker to local orchestration and repeat migration/wait/recovery checks with preserved volumes | Rejected work is never acknowledged; accepted work remains readable at capacity; restart retains waits/effects; shutdown leaves no orphan local tasks; reset is never used as restart | P1-10/17/18/19 | 3–4h |

**Exit:** PostgreSQL multi-worker and stale-effect tests pass using independent
processes; actual container restart preserves accepted state. The SQLite supported
subset remains tested, without implied full scheduler parity. Core deployment
commands enter the quickstart only after implementation and verification.

**UI and signals:** show current attempt and epoch in secondary operator details,
not as business authorization. Explain pending work, admission rejection and
recovery lag. Retain useful progress for admitted work during saturation. Track
queue age, inflight/admission, lease rejection and recovery lag with bounded labels.

**Implemented contract:** v4 worker inquiry/effect/outbox writes guard an explicit
scope/task/owner/epoch in their existing transaction. A paused old process cannot
commit after takeover, but may still send externally: cooperating stable effects
or honest uncertainty remain required. Public authenticated case/read/controller
commands retain their own authority. Pending/active/retained-identity policy is
persisted and finite; uncertainty without a final inquiry business outcome remains
outstanding for manual review. Replay and inspection work at capacity.

The p1-workers profile is opt-in, uses restricted runtime credentials, checks
existing ACTIVE v4 and fixture state, and supervises one bounded POSIX child per
parent. Shutdown stops acquisition, drains within 5 s by default, then kills/reaps
before release. Normal restart reuses named volumes. Upgrade refuses unmanaged
RUNNING v3 work until it finishes under the legacy contract. The final gate must
repeat actual container restart, waits and effect recovery without reset.

## Phase P1-G: conversational adapter, visible continuity and traces

**Implementation checkpoint:** P1-I22 through P1-I25 and their local combined
gate are recorded in the [Phase G work item](../work-items/0013-p1-phase-g-conversation-and-showcase.md).
The gate uses explicit bundled-WAV WebAudio input, native scripted STT/LLM/PCM
output, real browser/native WebRTC, held dependencies, fresh-consumer status,
exact UI confirmation and inspected raw Jaeger v3 trace data. Before controls or
speech, the worker awaits the public RoomIO readiness barrier and publishes
continuity.session_ready=true; session_host=False disables alternate SDK session
ingress. Hardware microphone quality, human hearing acknowledgement, automatic
network-loss recovery remain unqualified. Selected provider_real v2 live inference passed under Phase H.
Remote CI is outside the local POC scope. The task requirements below remain unchanged.

**Entry:** durable ports and case authority are stable. The current diagnostic
worker remains a transport tool; introduce the conversational consumer deliberately.
Reuse native AgentSession, tools, handoffs and suitable AgentTask/TaskGroup behavior.

| Task | PLAN | Prerequisites | Concrete deliverable | Required failure assertion | Acceptance contribution | Effort |
| --- | --- | --- | --- | --- | --- | --- |
| P1-I22 | PLAN-10/11 | P1-I21 and installed-SDK qualification | Connect native conversational submit/get/cancel tools and a separate authenticated controller signal port; return durable acceptance without awaiting supplier completion | Slow storage/supplier does not block the event loop or turn a model assertion into confirmation; session closure does not cancel accepted business work | P1-14/20 preparation | 3–4h |
| P1-I23 | PLAN-11 | P1-I18, P1-I22 | Extend the bounded GET/cursor case projection and showcase from persisted events: request, quote, exact confirmation, attempts, outcome and delivery; retain the small diagnostic console | Reconnect loads the current scoped case; missing/late observations stay unknown; UI timers cannot invent progress or completion | P1-17/20 UI | 2–4h |
| P1-I24 | PLAN-11 | P1-I22 | Add SDK-native metrics/session reports plus bounded application OTLP spans and the P1 metric vocabulary; exercise typed provider/storage/exporter errors | Exporter failure cannot block conversation, acceptance or shutdown; IDs/payloads never become metric labels or unsafe logs | P1-18/20 operational evidence | 2–4h |
| P1-I25 | PLAN-11 | P1-I22, P1-I23, P1-I24 and permitted browser media | Run actual local browser voice with scripted inference/audio, held supplier and slow persistence; interrupt, end and reconnect the session | Business work remains inspectable and completes independently; interruption alone does not cancel; exact mutation confirmation remains required; useful responsiveness is measured | P1-14/20 | 3–4h |

**Exit:** the local voice/tool path supplies P1-20's local-media assertions with
actual audio and browser observations; P1-I27/I28 supply the separately measured
and live evidence. Permission denial or unavailable microphone capability is recorded
as unverified, not replaced by native-SDK frame-count evidence. Trace export must
produce an inspected real trace; a reachable Jaeger UI alone does not pass P1-I24.

**UI and signals:** retain the existing TypeScript console as the default. Decide
on official Agents UI components only for a genuine conversation-client consumer;
a framework rewrite is not a prerequisite. Start with a bounded GET/cursor
projection. Native SDK notifications may request refresh, but cannot become state
authority; no custom event bus or SSE service is required. Use observed
session/agent states, actual durable event history and a separate technical
inspection view. Treat generated output, client playback
and user acknowledgement distinctly. Correlate session/case/workflow/attempt/effect
identities in sanitized logs/traces while retaining one case authority.

## Phase P1-H: reusable artifact and release proof

**Current checkpoint:** P1-I26's typed package/API/independent-consumer boundary
is implemented. The current full four-case H2, registered P1-18 and P1-14, and
selected provider_real v2 P1-20 runtime gates passed. Final source-matching package,
shared quality and index results are owned by the release work item; P1 V1 is qualified for the local POC using provider_real v2. Preserve H1/earlier checkpoints as
historical evidence. local_real remains unqualified; complete P2/P3 acceptance remains pending.

**Entry:** deterministic/process/container behavior and a genuine consumer
establish the package boundary. P1-I26 may run alongside the conversational/media
phase once its listed dependencies pass; do not block packaging on microphone
permission. Final release assessment still waits for every applicable local-media
assertion. H1 established the first S-I06/P1-I27 local inquiry baseline. Freeze seeded
schedules, machine/mode and numeric budgets before each broader workload. The G
media prerequisite has scripted evidence; H2 restart/slow-dependency/saturation/
shutdown measurements and I26 artifact/API/genuine-consumer review have passed.
The selected provider_real v2 media/model scenario has passing runtime evidence.
Configured local_real remains unqualified; profile configuration alone grants no
model result or business authority.

| Task | PLAN | Prerequisites | Concrete deliverable | Required failure assertion | Acceptance contribution | Effort |
| --- | --- | --- | --- | --- | --- | --- |
| P1-I26 | PLAN-11/22 | P1-I18, P1-I21 and a genuine second consumer | Finalize exports, build the P1 wheel, run the standalone CLI/example from an isolated consumer and independently review the public API/failure contract | No repository path injection or undeclared sibling deployment is needed; old M1 entrypoints/data remain compatible; review reproduces one controlled failure | All P1 packaging/review gate | 2–4h |
| P1-I27 | PLAN-11/21/22 | P1-I21, P1-I24; media workloads also P1-I25 | Run seeded steady/burst/saturation, restart and slow-provider workloads under declared budgets; retain raw outcomes and the short normal/crash demonstration | Zero lost accepted work; no incorrect duplicate effects; uncertainty counted honestly; resource/latency regressions are explained rather than hidden by rewriting budgets | P1-15/18/20 and release evidence | 3–4h |
| P1-I28 | PLAN-21/22 | P1-I25, P1-I26, P1-I27 and configured real inference | Resolve only the selected real-inference plugin at its compatibility checkpoint; run the same relevant voice/tool scenario with configured real speech/model inference; record outcomes, cost/configuration and final docs | Real-model output cannot bypass consent/state assertions; missing credentials or unsupported local hardware leave the portfolio gate incomplete | P1-20 live portion; portfolio gate | 3–4h |

**Local-ready exit:** every P1-01 through P1-20 local assertion, applicable shared
quality gate, standalone artifact check, supported-platform setup/migration/restart
proof and independent review passes. This can precede real-inference readiness.

**Portfolio-ready exit:** P1-I28 and the corresponding PLAN-22 review/demo evidence
also pass. Root integrated release still waits for P2/P3. Shared local host/container
and provider/exporter setup are coordinated once; hosted CI/publication are outside
this POC scope. Link their
observed evidence rather than charging or implementing the same work three times.
If plugin, review or capacity findings require fixes, schedule explicit follow-up
tasks; the final row is not permission to mark a failing requirement complete.

## Acceptance traceability

The charter remains authoritative. The table names the tasks that collectively
supply each assertion; multiple entries mean a partial earlier proof cannot close
that scenario on its own.

| Acceptance ID | Required implementation tasks | Final evidence boundary |
| --- | --- | --- |
| P1-01 | P1-I03, P1-I04, P1-I08, P1-I09 | Accepting process terminated; original scoped identity/payload readable |
| P1-02 | P1-I04, P1-I08, P1-I09 | Concurrent duplicates plus lost response after commit |
| P1-03 | P1-I04, P1-I08, P1-I09, P1-I18 | Changed scoped replay conflicts; other scope independent; retention protection |
| P1-04 | P1-I05, P1-I06, P1-I09 | Independent worker persists inquiry; unchanged booking |
| P1-05 | P1-I02, P1-I05, P1-I07, P1-I09 | Actual inquiry-success/before-ack process kill and reconciliation |
| P1-06 | P1-I11, P1-I12, P1-I15 | Exact authorized fake revision applied under stable key |
| P1-07 | P1-I11, P1-I12, P1-I15 | Missing/altered/stale/expired confirmation causes zero apply calls |
| P1-08 | P1-I15, P1-I16 | Actual mutation-success/before-ack kill and reconciliation |
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

## Current commands and per-task handoff

The following commands exist now and run from the repository root after the
[documented bootstrap](../../README.md). All twenty P1 rows have registered
runners. The P1 deep command executes actual PostgreSQL and browser/inference
requirements and needs their explicit setup. It defaults to local_real for P1-20;
select provider_real explicitly using the [provider guide](../provider-demo.md).
Missing setup, failed observations, skips or timeouts cannot pass. P2/P3 remain
planned and their project/ecosystem aggregates remain incomplete.

```sh
make check
make format-check
make frontend-check
.venv/bin/python -m harness validate
.venv/bin/python -m harness run BASE-01
HARNESS_PYTHON=.venv/bin/python sh scripts/harness-deep.sh --module p1
```

Run actual local smoke only with its documented prerequisites; the one-room
transport worker requires other browser sessions to be ended first. Do not invent
new worker, migration or benchmark CLI commands in onboarding before they exist.

For each task, use the [work-item template](../work-items/template.md). Example
packet for P1-I07:

- **Behavior:** recover one persisted inquiry after the selected crash window.
- **Acceptance:** P1-05; preserve P1-04 normal execution and BASE-01.
- **Ownership:** worker/store adapter, independent fake-supplier fixture and
  process scenario; no P2/P3 imports or booking mutation.
- **Inputs:** migrated queued request and supplier capability declaration from
  P1-I03 through P1-I06.
- **Schedule:** block after supplier commits its inquiry result; prove the barrier
  was reached; terminate only the owned worker; start a fresh worker.
- **Assertions:** original inquiry/effect identity recovered, one logical supplier
  inquiry, persisted local result, unchanged booking and bounded child cleanup.
- **Artifacts:** fixture seed, sanitized store/effect history, barrier/termination
  observations, command/version information and machine-readable scenario result.
- **Handoff:** exact implemented commands, test outcomes, public/migration changes,
  reviewed limitations, accurate assistance record and the next eligible task.

The final handoff must distinguish implemented behavior, passing partial tests,
completed acceptance rows and unresolved evidence. UI labels never determine a
backend outcome, and model judgments never replace the durable-state assertions.
