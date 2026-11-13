# P3 Delegation Reliability Kit implementation plan

Status: Active
Last reviewed: 13 November 2026

## Purpose and current baseline

Deliver a Python coordination library and an authenticated TypeScript capability
service that keep conversation responsive while independent, read-only work runs.
Results must remain scoped, revision-aware and explainable after retries,
cancellation, process failure, handoff and reconnect.

The [P3 charter](../projects/delegation-reliability-scope.md) owns requirements;
the [build plan](../build-plan.md) owns ecosystem ordering. This document divides
PLAN-17 through PLAN-21 and P3's share of PLAN-22 into implementation sessions.
P3-I identifiers are planning tasks, not new acceptance scenarios. P3-01/P3-03/
P3-11 now have registered passing lab assertions; the remaining 14 cases stay
planned and full release remains pending.

Reuse the existing pinned runtimes, local LiveKit server, diagnostic worker,
TypeScript console, protected API metrics, error envelope and repository harness.
Their current transport/intake behavior does not establish delegation, model
reasoning, remote recovery or browser voice quality. Do not rebuild that foundation.


Select applicable engineering gates from the [validation authority](../validation-plan.md)
for every task. Record Given/When/Then safety and useful-progress criteria, safe
producer log/error/metric assertions and actual test-mode evidence. Python work
follows the [engineering guide](../python-engineering.md); changed Design.md uses
the [standard template](../design-template.md). These are task completion rules,
not evidence that planned acceptance scenarios already pass.

Current first-source work is recorded in the [slice work item](../work-items/0023-p3-native-baseline.md).
P3-I01/I02 passed their bounded first-slice gates. This plan remains active;
unimplemented tasks and all full project acceptance rows remain pending. Phase
completion requires the actual exit evidence below.

The [I03/I04 contract/trust work item](../work-items/0025-p3-specialist-contracts-and-trust.md)
adds the first policy wire/evidence/principal boundary. The
[I05 HTTP work item](../work-items/0027-p2-standalone-and-p3-http.md) extends it with
one authenticated scripted handler/client and actual socket evidence. The
[I06 phase](../work-items/0028-p2-dispatch-and-p3-coordinator.md) now adds immutable
coordinator acceptance/find/get/requested-cancel through P1's separately installed
public read-only work profile and a Python HTTP client. The corrected actual gate
separates runtime and owner credentials, uses synthetic case preflight, observes
postcommit kill/fresh lookup, and probes transport independently. I06 issues no
attempt or durable specialist result. The [I07A phase](../work-items/0029-p2-gateway-and-p3-issued-execution.md)
now adds the explicit P1-issued runner and immutable result observations via the
optional work-profile v2 upgrade. Deterministic attempt_<uuidhex> wire correlation
is derived from the issued UUID while accepted bytes remain unchanged. I07B's
first durable delivery and separately confirmed fake action are implemented in the
[I07B phase](../work-items/0030-p2-agent-recovery-and-p3-completion.md). P1 work-profile
v3 owns immutable delivery/action receipts and atomic work eligibility plus exact
case commitment; the independent receiver owns byte acceptance. Selected gates passed, completing the I07A/I07B
implementation task. Broader protected case race/recovery schedules and media
remain later gates. I08 adds actual concurrent
acceptance/conflict, a public completion/inspection example and first complete
registered lab runners. P3-01/P3-03/P3-11 have fresh passing reports;14 other charter
rows remain planned. Final task/artifact qualification is recorded in the
[I08 work item](../work-items/0031-revision-routing-and-delegation-acceptance.md).
The [result-projection phase](../work-items/0032-linked-confirmation-and-result-projections.md)
completed I09: explicit P1 work v4 result feed and owner-installed P3 metadata v1.
The actual and installed 12-case gates passed both pre/postcommit kills, fresh resume,
original-observation replay and independent identity reconciliation. Applicability
is immutable as-of metadata. I10 delivery-only resumable processing completed its
selected local gates. I11 adds explicit refreshed applicability, monotonic
retained evidence and permanent display tombstones. I12 protected action/revision
schedules passed their selected source/installed gates through unchanged P1/P3
authorities. I13 passed its selected source and isolated installed eighteen-case
deadline/cancellation gates and forty-six compatibility assertions in the
[completed handoff](../work-items/0036-native-input-and-deadline-cancellation.md).
The selected P2 native/artifact and final phase regression/shared gates also passed,
completing I13 within its selected temporal scope. The
[current recovery handoff](../work-items/0037-playback-evidence-and-process-recovery.md)
records I14's qualified seventeen-case source and isolated installed gates, each
with eight owned process kills and one actual two-waiter issuance graph. Eighty
existing execution/processing/applicability/action/deadline assertions passed with
cleanup and unchanged P1/P3 production runtime. Original command replay is
lookup-only; a separately supplied new command needs fresh P1 eligibility.
Unknown delivery remains unacknowledged while later current work progresses.
I15 completed selected standalone consumption through its maintained eight-offline
and eight-installed-lab gate in the [handoff](../work-items/0038-case-rehydration-and-standalone-release.md).
Fresh declared archives and unadapted public completion/metadata examples passed,
including original replay with zero new writes/invoke/accept/apply, one owned
caller-process kill and complete cleanup. Final shared phase gates passed; that checkpoint preserved P1's seventy-seven
and P3's thirty runtime payloads. I16 bounded standalone image HTTP passed selected local qualification, with I17 fixed-policy evidence also selected-qualified. Broader platform,
media and full charter release remain separately planned; fourteen full rows remain
planned and this phase adds no registration. The selected I18A durable fixed-policy
prerequisite is recorded in [0041](../work-items/0041-standalone-channel-and-durable-policy.md): twelve source and twelve installed assertions, a separate eight-assertion
offline package gate and four focused HTTP regressions passed. All 146 selected compatibility assertions passed;
Final shared/M1 checks passed in that completed handoff. Selected I18B native
RTC text background conversation/UI qualification subsequently passed in
[0042](../work-items/0042-responsive-native-policy-and-compact-demo.md).
The completed [0043 handoff](../work-items/0043-stable-result-delivery-and-return-context.md)
qualifies selected backend v2 delivery/current-channel reads with sixteen storage
and four return actual source assertions; its twenty-five-stage offline package
lane remains separate. [0044](../work-items/0044-origin-bound-channel-policy.md)
implements original P2-input binding, schema3 facades, narrow operation client and
application HTTP with passing focused unit/socket checks and isolated package/fake-port
qualification. Fourteen selected actual source assertions passed. Integrated
voice/text/SMS handoff, restart/discovery, applicable provider runs, complete
release and the final video retain their later gates. All fourteen remaining full
P3 acceptance rows remain planned; fifty-five catalog definitions/twenty-four registered
runners remain unchanged.

### Qualified I16 standalone image path

The [completed handoff](../work-items/0039-bounded-channel-workloads-and-image-evidence.md)
keeps the new four-field image result separate from policy eligibility and P1 durable
execution. Actual immutable PNG bytes are bounded before the provider; missing or
ambiguous values require clarification and image instructions remain inert data.
Twenty contract/socket assertions and their fresh installed repetition passed
selected qualification in 0039 and both passed current compatibility reruns in 0040.
The scripted fixture mapping establishes no OCR or real vision inference. A reviewed
versioned P1 operation extension is required before image work can enter the durable
coordinator. I17 fixed-policy semantic evidence passed selected qualification in 0040;
fourteen full charter rows remain planned.

## Dependency gates and ownership

| Gate | Required contract or evidence | Needed before |
| --- | --- | --- |
| G-P1-EXEC | I06 has immutable accepted input/read/cancel. I07A adds public P1-issued grants and immutable opaque results through explicit v2; the one-step P3 runner owns invocation outside transactions. Generic workers, automatic retry and durable delivery events remain separate gates. | Acceptance foundation at I06; real persisted invocation/result progression at I07 and recovery in P3-C |
| G-CASE | Public exact case reads and P1 action_api bind verified work/case credentials on the same PostgreSQL target; work eligibility, current exact confirmation, case intent and receipt share one protected transaction. Selected first-path schedules do not close every later race. | P3-I07 authorized fake action; broader P3-C race assertions remain separate |
| G-P1-RECOVERY | P1's process-recovery, effect uncertainty and postcommit cancellation contracts have executable evidence | P3-I12 through P3-I14 |
| G-DELIVERY | Explicit P1 work v3 delivery intent/possible marker/receipt plus a bounded independent persistent receiver. Only a newly persisted begin permits accept; an existing possible send performs lookup only. No outbox or automatic retry loop. | First useful-result path; P2 deployment is unnecessary |
| G-P1-MEDIA | A scripted native AgentSession conversational adapter and actual self-hosted browser audio path exist under PLAN-11 | P3-E voice/responsiveness checks |
| G-P2-ROUTE | P2's public association/current-route adapter and handoff/resumption contract are usable | Integrated P3-I19 and P3-I22; not standalone reliability tests |
| G-PACKAGE | P1's execution library can be consumed through declared public exports without sibling storage imports | Isolated standalone consumer in P3-I15 |

P1 alone owns durable acceptance, attempts, retry/deadline eligibility and execution
outcomes. P3 owns immutable delegation input, result validation/applicability and
routing observations. Case authority owns accepted action intents. P2 or the small
standalone adapter owns delivery acceptance/evidence. Specialist status/result/cancel
endpoints are observations of a bounded P1-owned attempt, not another recovering
queue. No specialist receives booking-mutation or notification authority.

P3-A introduced the Python workspace member under projects/delegation-reliability/python.
I03/I04 added specialist-ts/src, project tests and contracts/delegation fixtures
with actual Python/TypeScript producers and consumers. I05 added TypeScript HTTP;
I06 added Python coordinator/client modules through the same packages and maintained
discovery. I07A extends these public boundaries with runner.py and execution_api.
I07B adds completion.py/action_adapter.py through public delivery_api, receiver_api,
action_api and case_control_api; it creates no replacement authority or side ledger.
The root console presents read models; it must not own case revisions, retry
eligibility or a second event bus.

Add any new package/source/tests to actual workspace, lint/format/type/test/build
discovery in the same slice. Preserve deliberately failing fixture and nonzero-test
checks. Existing console-only pnpm checks or service-only typing cannot qualify
the specialist or coordinator.

## Session sizing and completion rule

Each task below is one reviewable slice. Its estimate includes implementation,
focused tests and a short handoff, assuming named prerequisites already work.
Ranges are preliminary engineering hours, not elapsed dates or a release promise.
Split any task exceeding its upper bound; retain IDs and acceptance semantics.
Learning, review findings, dependency resolution and shared infrastructure work are
additional rather than silently counted twice. The 24 slices total 64–89h before
that contingency; recalibrate after P3-I08 and P3-I14.

Every slice updates its owned README/Design/AGENTS guidance, runs the applicable
existing checks and records a work item. Add telemetry with real producers,
register acceptance runners only after assertions exist, and preserve incomplete
status for missing work. Commands for future services/runners enter runnable
quickstarts only after implementation and verification.

## P3-A: Native baseline and remote-boundary decision

Entry: read the root/project instructions, current native SDK interfaces and fixed
capability scope. This small controlled baseline may proceed without the complete
P1/P2 application. It establishes orchestration behavior, not durable recovery or
real-model/audio performance.

| Task | Prerequisites | PLAN mapping | Concrete deliverable | Failure/negative assertion | Acceptance contribution | Effort |
| --- | --- | --- | --- | --- | --- | --- |
| P3-I01 | Reviewed charter; current frozen toolchain | Before PLAN-17 | One bounded, seeded capability input and controlled outcome fixture; a single-agent tool example with useful-result and responsiveness observations | Invalid or excessive context is rejected; a held capability does not falsely report completion | P3-16 initial baseline | 2–3h |
| P3-I02 | P3-I01 | Before PLAN-17 | Native local-subagent example using equivalent bounded input; retained baseline and a decision explaining process/language/permission isolation for a remote boundary | Record context differences and remote tradeoffs; do not claim native tasks survive an independent process failure | P3-16 initial baseline | 2–3h |

Exit: repeatable tools/native examples and the remote-boundary decision are
reviewed before a remote service is built. Native execution may be faster; the
remote service must have an explicit isolation/recovery reason rather than a
promised latency improvement. PLAN-21 still performs the full three-way comparison.

## P3-B: One authenticated capability and useful result

Entry: P3-A complete; G-P1-EXEC, G-CASE and G-DELIVERY are stable enough for one
normal path. Schemas and independent fixture work can begin while those gates
stabilize, but mocked ports cannot pass real execution or durability assertions.
Start with scripted booking.evaluate_policy over seeded verified facts. Introduce
image extraction only after this first remote slice works.

| Task | Prerequisites | PLAN mapping | Concrete deliverable | Failure/negative assertion | Acceptance contribution | Effort |
| --- | --- | --- | --- | --- | --- | --- |
| P3-I03 | P3-I02; shared case/execution field decisions | PLAN-17 | Versioned request/result/error envelopes, semantic canonicalization, trusted input/source fingerprints and bounded evidence/provenance fields; shared Python/TypeScript positive/negative fixtures | Reject unsupported version, changed same-ID payload, wrong revision/scope, unknown capability and malformed output before acceptance/use | P3-01, P3-03, P3-11 | 3–4h |
| P3-I04 | P3-I03 | PLAN-17 | Local service-principal binding, capability/evidence authorization and explicit limits/units for context, image, result, time and active attempts | Forged JSON scope, missing credential, inaccessible evidence, swapped source/version/fingerprint, arbitrary fetch URL and oversized input cannot invoke work or disclose another account's result | P3-11 | 2–3h |
| P3-I05 | P3-I04 | PLAN-17 | Bounded scripted TypeScript HTTP handler and typed client for one capability; safe errors and invocation observations | Wrong schema/auth or excess capacity is rejected; lost connections do not create a service-owned recovering queue; timeout does not prove computation stopped | P3-01, P3-11 | 3–4h |
| P3-I06 | P3-I03; public P1 accepted-work profile; scoped case-read preflight | PLAN-17 | Implemented coordinator submit/find/get/requested-cancel and Python HTTP client with declared dependencies. Complete immutable canonical input/digest/deadline persist through P1 before acknowledgement; delivery interface is reserved for I07, not invoked here. | Caller mutation cannot alter accepted context; misbound credential scope fails before writes; ambiguous commit reconciles the original key without a second submit. Independent socket and persisted-acceptance proofs do not issue an execution. | P3-01, P3-03 foundation | 3–4h |
| P3-I07 | P3-I05, P3-I06; G-P1-EXEC issued progression; G-CASE; G-DELIVERY | PLAN-17 | I07A/I07B completed their selected issued HTTP result, durable receiver and exact fake-action gates | Read-only candidate/result cannot authorize mutation; stale-A/current-B useful action, atomic work/case guard and owned cleanup must pass | P3-01; initial P3-05 | Split around frozen prerequisites |
| P3-I07A | P3-I05/I06; explicit P1 work v2 | PLAN-17 | Implemented scoped issued runner, stable command/attempt reconciliation, immutable bounded result and read applicability; no retry queue | Replayed/unknown issuance never reinvokes; late/stale/cancelled strict results remain historical; original accepted bytes survive | P3-01 foundation | Bounded prerequisite slice |
| P3-I07B | P3-I07A; G-CASE; G-DELIVERY | PLAN-17 | Implemented explicit first delivery and guarded action adapters over owner-upgraded P1 work v3, independent receiver and existing leased fake supplier worker. The selected combined gate passed. | Zero stale action intents; current independently confirmed B commits one intent/effect; original receipt survives later cancellation/expiry and cannot retarget. Broader I12/I13 schedules remain required. | P3-01; initial P3-05 | Bounded first-path slice |
| P3-I08 | P3-I07 | PLAN-17 | Implemented independent-process same-ID replay/conflict, public completion/inspection example and complete registered lab runners for P3-01/P3-03/P3-11; all three have fresh passing reports | Concurrent equal requests retain one immutable logical delegation; changed payload conflicts. Full input/output/schema/scope/image-resource rejection inventory and valid progress execute; no one-physical-computation claim. Final task/artifact gates passed, completing I08. | P3-01/P3-03/P3-11 lab rows | 2–3h |

Exit: one real useful current result, same-ID conflict and a minimal stale-result
rejection work before adding models or the second capability. Show accepted,
running and result observations in the console only when real responses/events
supply them. Keep execution, applicability and delivery in separate fields.

Telemetry/error minimum: fixed capability/outcome/error-code dimensions; correlate
delegation, P1 attempt, revision and delivery IDs in safe logs/spans, never metric
labels. Return typed validation/auth/conflict/capacity/deadline/unknown-outcome
errors without provider messages or credentials. HTTP retry advice cannot authorize
another logical delegation or external action.

## P3-C: Durable applicability, races and recovery

Entry: P3-B complete and G-P1-RECOVERY available. Introduce only P3-owned versioned
metadata. P1 remains the execution ledger. Any applicability decision records the
revision it evaluated; current action authority is always revalidated atomically.
P3-I06 already persists and replays the complete immutable envelope/digest in
P1 acceptance; P3-I09 must not retrofit identity after acknowledgement. Apply
S-I05's one-shot migration/configuration mechanism to P3-owned schema and grants;
serving roles cannot perform DDL or receive bootstrap administrator credentials.

| Task | Prerequisites | PLAN mapping | Concrete deliverable | Failure/negative assertion | Acceptance contribution | Effort |
| --- | --- | --- | --- | --- | --- | --- |
| P3-I09 | P3-I08; P1 durable event contract; S-I05 applied to P3 schema/grants | PLAN-18 | Implemented owner-installed metadata v1 and bounded explicit projection from the P1 work v4 result-only feed, preserving original accepted identities. Actual and installed 12-case recovery gates and final phase checks passed, completing I09. As-of metadata grants no action or delivery permission | Upgrade preserves accepted identities; an interrupted projection resumes without inventing execution state or losing a P1 result | P3-04, P3-08 | 3–4h |
| P3-I10 | P3-I09; G-DELIVERY | PLAN-18 | Implemented explicit delivery-only processing over owner-upgraded projection v2, fixed policy, separate discovery/terminal watermark and exact event ACKs after required processing. Actual and installed 16-case gates, coherent-snapshot/race proof and final phase checks passed, completing I10; P1 receipts remain authoritative and no source ACK/action is introduced | Replay preserves original delivery receipts and event ACKs; unknown A stays unACKed while later eligible B progresses. Existing possible-send absence remains lookup-only, with zero automatic action or duplicate logical receiver acceptance. | P3-04 | 2–3h |
| P3-I11 | P3-I09; G-CASE | PLAN-18 | Implemented explicit exact-command non-atomic applicability refresh, monotonic retained invalidation witnesses and profile-lifetime display tombstones over owner-upgraded projection v3. The 18-case source gate passed; isolated installed and final phase gates passed, completing I11. | Late A remains outdated with zero A-derived current actions; valid separately confirmed B progresses. Display hiding preserves original projection/refresh/ACK/receipt identities, unresolved processing and replay at capacity; it reclaims no protected slots. | P3-05 | 3–4h |
| P3-I12 | P3-I11; G-P1-RECOVERY | PLAN-18 | Completed selected actual revision/intent/cancellation schedules through unchanged public authorities: 16 assertions, two true two-waiter order graphs, three owned kills, nine retained business-completion joins and isolated installed-artifact qualification; final local gates passed, completing I12 | Reject A atomically with zero A-derived current intents/effects and permit one independently confirmed B intent; later revision cannot reverse a committed external intent; show P1's actual cancellation/effect outcome | P3-06, P3-07 | 3–4h |
| P3-I13 | P3-I09, P3-I11; P1 fake-clock/cancellation contract | PLAN-18 | Completed selected eighteen-case source/installed scope and final phase gates. Expiry before/during invocation and separate cancellation requested/acknowledged/invalidation observations | No new ineligible attempt starts; authority-observed time governs eligibility, never model completion timestamps; ignored cancellation may complete but its invalidated result cannot cause an action | P3-09, P3-10 | 3–4h |
| P3-I14 | P3-I10, P3-I12, P3-I13 | PLAN-18 | Qualified selected source and isolated installed seventeen-case recovery gates, each with eight owned kills/one issuance graph; eighty compatibility assertions passed. Preserve unchanged P1/P3 runtime, exact issuance owner/command replay, retained results/receipts, unknown delivery gaps and useful current progress in the [current handoff](../work-items/0037-playback-evidence-and-process-recovery.md). | New processes recover accepted work through P1; duplicate read-only computation cannot create a second logical result or authorized effect | P3-08; P3-04 recovery | 3–4h |
| P3-I15 | P3-I14; G-PACKAGE | PLAN-18 and PLAN-22 | Completed selected maintained local build/install command, fresh declared P1 wheel, P3 wheel/sdist/rebuilt and npm parity, and unadapted public completion/metadata examples: sixteen assertions (eight offline plus eight installed lab), one owned caller-process kill and complete cleanup passed in [0038](../work-items/0038-case-rehydration-and-standalone-release.md). Existing P1/P3 runtime authority remains unchanged; broader platform/release gates remain separate | Example works without repository PYTHONPATH, sibling store imports, P2 gateway or the complete P1/reference deployment; import alone does not start a server | Standalone release gate; P3-01/P3-08 | 2–3h |

Exit: deterministic normal/replay/race/deadline/cancellation/process tests pass
with real persisted adapters. UI history shows successfully computed but outdated
results honestly; it never labels them as a current answer. Cancellation
acknowledgement is not a guaranteed remote stop. Correlate the authority decision
and eventual effect outcome without copying another component's state machine.

Record recovery lag, attempts, invalidation reasons and valid-result progress.
Keep late results and tombstones long enough for the declared replay horizon;
expiry/display-history limits cannot remove idempotency protection.

## P3-D: Two bounded read-only capabilities

Entry: P3-C complete. Both capabilities share the same authenticated attempt
contract, limits, provider interface and permission boundary. Deterministic fixtures
remain the default; no external model credential is required here.

| Task | Prerequisites | PLAN mapping | Concrete deliverable | Failure/negative assertion | Acceptance contribution | Effort |
| --- | --- | --- | --- | --- | --- | --- |
| P3-I16 | P3-I15; scoped evidence adapter from P3-I04 | PLAN-19 | Completed selected qualification in [0039](../work-items/0039-bounded-channel-workloads-and-image-evidence.md). Add the finite booking.extract_document contract, scoped immutable PNG decoder/handler and configured public clients/examples. Scripted fixture evaluation is separate from structural validation and the independent literal factual oracle; P1 remains policy-only. | Distinguish schema validity from known-fixture factual accuracy; reject valid JSON with wrong values or swapped evidence. Missing/ambiguous fields clarify; reject inaccessible, oversized or excessive-dimension images before uncontrolled work | P3-15, P3-11 | 3–4h |
| P3-I17 | P3-I16; existing scripted policy capability | PLAN-19 | Completed selected standalone HTTP qualification in [0040](../work-items/0040-operations-ui-and-fixed-policy-evidence.md): explicit policy-v2 immutable policy/fact/rule witnesses, independent literal factual checks and adversarial text. Source20/installed20, image regressions and146 compatibility assertions passed. At that checkpoint the durable runner was v1-only. I18A now adds explicit v2 durable consumption; v1 defaults remain unchanged. Native background conversation/UI still belongs to full I18. | Untrusted text cannot grant tools; invented policy rules and conflicting/unsupported evidence fail factual evaluation. Provenance/confidence grants no authority; uncertainty clarifies, correctly grounded current results progress, and no mutation/notification capability exists | P3-15, P3-11 | 3–4h |

Exit: the two named capabilities return useful schema-valid evidence or explicit
clarification under the same bounded contract. Apply the charter's immutable-source and provenance contract, retaining separate structural and factual fixture outcomes; evidence must support the accepted source/version, and no timestamp or model metadata grants authority.
Node Agents/native RTC is not needed for these ordinary HTTP handlers; introduce
it only if an actual Node-hosted realtime agent is separately selected. Continuous
video, arbitrary specialists and a dynamic tool marketplace remain deferred.

## P3-E: Responsive conversation, route continuity and local runtime

I18A is a durable-consumption prerequisite. I18B separately passed selected source
and installed RTC text qualification for an AgentSession continuing a useful answer
while remote work is held, plus the compact result view in
[0042](../work-items/0042-responsive-native-policy-and-compact-demo.md).
Selected backend v2 delivery/current-channel reads subsequently qualified in
[0043](../work-items/0043-stable-result-delivery-and-return-context.md).
[0044](../work-items/0044-origin-bound-channel-policy.md) implements the
original P2-origin prerequisite with focused unit/socket evidence and passing
isolated package/fake-port qualification; its fourteen selected actual source assertions
passed. Integrated
room handoff and voice/text/SMS, later load/runtime/restart gates, applicable
provider runs and the final demo video remain planned. Keep the standalone image
capability separate; this work adds no image operation to P1 or v2/v3 projection,
refresh or guarded-action adapter.


Entry: P3-D complete and G-P1-MEDIA available. Use a standalone delivery adapter
first. G-P2-ROUTE is needed only for the integrated resumption scenario, not all
coordinator tests. Reuse the existing console and native LiveKit controls. P3-I22 can first prove
actual browser/media integration with the narrow standalone delivery adapter.
Repeat routing through P2 when G-P2-ROUTE exists; retain that integrated reference
app evidence for S-I08. A standalone pass cannot be labelled as the P2 integration.

| Task | Prerequisites | PLAN mapping | Concrete deliverable | Failure/negative assertion | Acceptance contribution | Effort |
| --- | --- | --- | --- | --- | --- | --- |
| P3-I18 | P3-I17; G-P1-MEDIA | PLAN-20 | The selected I18A durable prerequisite passed twelve source/twelve installed assertions with a separate offline eight and four HTTP regressions in [0041](../work-items/0041-standalone-channel-and-durable-policy.md). Explicit v2 facades reuse opaque P1 work authority and preserve v1 defaults. I18B now implements the explicit native RTC text application and compact optional result view in [0042](../work-items/0042-responsive-native-policy-and-compact-demo.md); selected source/installed qualification passed twelve backend/SDK assertions and three actual RTC/browser groups per mode, plus eight separate installed package assertions. Broader integrated voice/result routing follows separately; use existing authority, not a new bus. | With the specialist held on a barrier, another user question gets a useful response; no blocking DB/HTTP work or fake timed progress occupies the conversation loop | P3-02; P3-17 preparation | 3–4h |
| P3-I19 | P3-I18; G-DELIVERY; G-P2-ROUTE for integrated adapter | PLAN-20 | Selected backend v2 delivery/current-channel reads qualified in [0043](../work-items/0043-stable-result-delivery-and-return-context.md): sixteen storage/four return actual source assertions and a separate twenty-five-stage offline package lane. [0044](../work-items/0044-origin-bound-channel-policy.md) implements original P2-origin binding, schema3 facades, narrow client and application HTTP with unit/socket evidence and passing isolated package/fake-port qualification; fourteen selected actual source assertions passed. Integrated room handoff and voice/text/SMS delivery retain their later gate. | Returning interaction receives only its scoped current result; old room/agent references cannot drop delivery or leak another account's context | P3-12 | 2–4h |
| P3-I20 | P3-I18; P1 admission limits | PLAN-20 | Seeded global/per-tenant saturation experiment and bounded TypeScript active-attempt registry with documented overload outcomes | Saturated A cannot exceed caps; admitted B progresses; service rejection leaves accepted P1 work inspectable and eligible under its retry policy | P3-13 | 3–4h |
| P3-I21 | P3-I14, P3-I19; versioned P3 storage; S-I05 applied to P3 services/configuration | PLAN-20 and PLAN-09 extension | Product Compose services, migration/readiness checks and a normal same-volume restart scenario | Restart preserves accepted delegation/results and callback deduplication; startup/shutdown are bounded; normal stop never resets data | P3-14 | 2–3h |
| P3-I22 | P3-I18 through P3-I21; G-P2-ROUTE for integrated P2 repetition | PLAN-20 and PLAN-11/15 integration | Actual self-hosted browser voice/interruption/result-routing demonstration with fixture inference first | Observe playback/interruption at the client; speech interruption is not business cancellation; unavailable microphone/playback evidence stays unverified | P3-17, P3-02, P3-12 | 3–4h |

Exit: the user can watch work continue while conversation stays responsive,
revise the case, see A become outdated, and see B deliver through the returning
route. The UI has separate execution/applicability/delivery lanes, safe errors and
an inspection view backed by bounded queries. Keyboard operation, reduced motion,
empty/error/unknown states and mobile reflow remain usable.

Keep one fixed admission policy. A small two-tenant fixture can demonstrate
fairness; it is not a production capacity claim. P1 owns durable queue limits;
the TypeScript service separately protects finite active invocations and input
resources. Do not reschedule accepted work inside that service.

## P3-F: Comparable evidence and release handoff

Entry: P3-E complete. Prior-phase local P3 assertions have runners with meaningful positive
counts, failure artifacts and bounded cleanup. Current shared media/release gates
remain separate from the P3 implementation tasks.

| Task | Prerequisites | PLAN mapping | Concrete deliverable | Failure/negative assertion | Acceptance contribution | Effort |
| --- | --- | --- | --- | --- | --- | --- |
| P3-I23 | P3-I22; retained P3-I01/I02 baseline | PLAN-21 | Controlled three-way tool/native/remote benchmark using equivalent fixtures, declared workload/resources and budgets fixed before evaluation | Retain raw samples, correctness, queue/recovery delay, event-loop lag and CPU/RSS; zero stale intents plus valid-result progression; no tail percentile from inadequate samples | P3-16 local comparison | 3–4h |
| P3-I24 | P3-I23; explicit live credentials/budget for live lane | PLAN-21 and PLAN-22 | Selected real-model image/policy/voice runs; final API/failure review, isolated consumer rerun and short success/failure demo | Check evidence against expected outcomes; report provider/configuration, context differences and actual/unavailable cost; absent live setup is not a passing portfolio gate | P3-15/P3-16/P3-17 live evidence; release gate | 3–4h |

Local-ready V1 requires all 17 cases' local assertions, independent-process
recovery, standalone installation and actual local media evidence. Portfolio-ready
V1 additionally requires the selected live outcomes, three comparable baselines,
cost/configuration, independent review and explainable demonstration. Report
passed, failed, unimplemented and not-run evidence distinctly. Provider failure
must not be hidden by switching to a fake model and retaining a live label.

Use native SDK session/turn metrics and reports before custom instrumentation.
Add P3 spans only at delegation/invocation/result/applicability/delivery boundaries.
Bound exporter queues/retry/shutdown; collector failure cannot block acceptance or
conversation. Client-observed audio timings and agent-side emission are different
measurements. IDs belong in safe logs/spans, not unbounded metric dimensions.

## Acceptance coverage

P3-01/P3-03/P3-11 have complete registered lab runners and fresh passing reports.
The remaining 14 mappings identify planned assertions. The charter remains
authoritative for each case; selected lab completion does not qualify full release.

| Acceptance ID | Primary task(s) | Required retained proof |
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

## Demonstration checkpoints

| Checkpoint | What the viewer sees | Deliberate failure and useful recovery |
| --- | --- | --- |
| After P3-B | A bounded scripted specialist produces current structured evidence; a separately confirmed fake action is possible | Same-ID changed input conflicts; delayed stale A does not become B's answer |
| After P3-C | Execution succeeds or recovers independently of session lifetime; applicability remains explicit | Kill a process after compute/before acknowledgement; recover through P1 and preserve one logical result/effect |
| After P3-D | Static document extraction and fixed-policy analysis cite their evidence | Missing/adversarial input produces clarification or validation failure, not invented facts/tools |
| After P3-E | Conversation continues, revision changes, old result is marked historical and the current result follows the returning route | Ignore remote cancellation or close the room; retain the observed outcome and safely route applicable work |
| After P3-F | A short success/failure story followed by an inspectable comparison and standalone API example | Show raw evidence and limits rather than a blanket claim that remote specialists are always faster |

## AI coding-agent task packet example

For subsequent P3 work, preserve the completed selected I15 standalone assertions
in [work item0038](../work-items/0038-case-rehydration-and-standalone-release.md) and
create the next task from the [template](../work-items/template.md).
Read the [project instructions](../../projects/delegation-reliability/AGENTS.md),
[shared design](../../Design.md), charter and existing producer/consumer tests.
Preserve I11 refresh/retention, I12 protected-action schedules, I13 temporal proof
and I14's source/installed process recovery recorded in the
[current handoff](../work-items/0037-playback-evidence-and-process-recovery.md).

Retain the qualified Python/npm artifacts and their explicit local adapters, then
map the remaining standalone release assertions before broadening qualification.
Use declared P1 public execution/case/delivery surfaces and isolated installations;
no checkout product path or sibling store import may supply missing runtime code.
Keep cancellation request, remote acknowledgement, stored result truth and current
applicability separate. Exact caller confirmation and P1's protected transaction
remain required; packaging cannot create another execution owner or renew permission.

Run meaningful scoped assertions and maintained fast/frontend checks. Actual
PostgreSQL/process schedules need owned barriers, exact identity/effect truth and
cleanup. Register a full acceptance row only when its entire normative inventory
executes. Retain commands, observed results, review findings and remaining work
without treating a selected phase as full release.

## References and shared policies

Read [validation](../validation-plan.md), [observability](../observability.md),
[demonstration UX](../demo-plan.md), [technology policy](../technology-baseline.md)
and the [runtime-boundary decision](../decisions/0001-runtime-boundaries.md).
Public API examples in the charter are planned application contracts, not native
LiveKit methods. Frozen versions are refreshed at integration/release checkpoints,
not automatically before every task. No real carrier, Cloud account, continuous
video pipeline or additional orchestration platform is required for this scope.
