# P2 Channel Continuity Kit implementation plan

Status: Active
Last reviewed: 13 November 2026

## Purpose, authority and starting point

Implement one independently usable TypeScript continuity package and its gateway,
Python LiveKit adapter and browser example. This plan decomposes PLAN-12 through
PLAN-16 from the [build plan](../build-plan.md); it does not redefine the
[P2 charter](../projects/channel-continuity-scope.md) or create acceptance IDs.
The [shared design](../../Design.md), [validation plan](../validation-plan.md),
[observability contract](../observability.md) and [demo plan](../demo-plan.md)
remain authoritative for their subjects.

The pinned TypeScript toolchain, browser SDK, diagnostic console, Compose stack,
API metrics and documentation/structural harness already exist. Reuse them.
The console's current echo and M1 intake are foundation capabilities, not a P2
message inbox, channel history, association service or business acceptance path.
All P2-01 through P2-17 remain planned until their actual assertions pass.

Task IDs P2-I01 through P2-I22 identify implementation slices, not test outcomes.
Estimates are provisional engineering hours including the slice's targeted tests,
documentation and first review. They are not elapsed-time promises. Split a task
when its failure schedule or interfaces no longer fit one reviewable change;
re-estimate after the first real gateway crash and first browser audio run.
Study, setup failures and subsequent review work consume the shared weekly budget.


Select applicable engineering gates from the [validation authority](../validation-plan.md)
for every task. Record Given/When/Then safety and useful-progress criteria, safe
producer log/error/metric assertions and actual test-mode evidence. Python work
follows the [engineering guide](../python-engineering.md); changed Design.md uses
the [standard template](../design-template.md). These are task completion rules,
not evidence that planned acceptance scenarios already pass.

Current first-source work is recorded in the [slice work item](../work-items/0022-p2-channel-contracts.md).
P2-I01/I02 passed their bounded first-slice gates. This plan remains active;
unimplemented tasks and all full project acceptance rows remain pending. Phase
completion requires the actual exit evidence below.

Current I03/I04/I05 work is recorded in the [verified-intake](../work-items/0024-p2-verified-durable-intake.md)
and [PostgreSQL inbox](../work-items/0026-p2-postgres-inbox.md) work items. The
[I06 standalone work item](../work-items/0027-p2-standalone-and-p3-http.md) adds the
public example and new-process replay. The
[I07 phase](../work-items/0028-p2-dispatch-and-p3-coordinator.md) now adds an explicit
owner v2 upgrade, persisted bounded claims/attempts, frozen investigation input and
lookup-only reconciliation against a cooperating operation port. A possible external
call never returns to a not_executed state; the old standalone preview rejects
nonpending inputs. The [I08 phase](../work-items/0029-p2-gateway-and-p3-issued-execution.md)
adds the actual bounded gateway, durable eligible polling and post-acknowledgement
process restart proof. The [I09 phase](../work-items/0030-p2-agent-recovery-and-p3-completion.md)
adds an explicit trusted agent-process adapter and framed worker helper, preserving
input/case/operation identity through independently killed scripted-worker replay.
A live gateway observes claim expiry and repeated attempts while the cooperating
operation accepts one logical investigation. The selected phase gates passed, completing I09;
I10 adds the explicit structured-command router, standalone reference authority
and public-P1 loopback application bridge. The selected 22-case equivalent
authority gate and final phase checks passed, completing I10. The
[linked-confirmation phase](../work-items/0032-linked-confirmation-and-result-projections.md)
completed I11 with immutable prompt bindings, exact P1 confirmation, explicit original
receipt replay and a current-association preflight. Its 18-case actual integration
and installed npm gates passed. The preflight is not an atomic association-revocation
commitment fence. I12 outbound replies completed their selected local gates;
I13 now adds authenticated correlated callback evidence and a conservative
reservation veto within its selected scope. I14 explicit uncertain-send policy
passed its selected source/installed gates. I15/I16 native text/committed voice
passed selected actual six-group native and isolated Python/npm artifact gates in
the [completed phase](../work-items/0036-native-input-and-deadline-cancellation.md).
Final regression/shared gates and the affected media rerun passed, completing
I15/I16 within their selected native/artifact scope. The
[current I17 handoff](../work-items/0037-playback-evidence-and-process-recovery.md)
implements source-qualified generated text, SDK progress, response-scoped
interruption and client-reported playback through an explicit owner v7 upgrade.
Its sixteen-case PostgreSQL storage gate, three-group actual browser/media gate,
isolated public npm consumer and current eight-payload Python package with
ninety-four unadapted tests passed, together with 147 P2 compatibility assertions.
This completes selected I17 qualification; final shared phase closure is recorded
in the linked handoff. I18 completed its selected verified current-case room/channel
rehydration gates in the [handoff](../work-items/0038-case-rehydration-and-standalone-release.md):
eighteen storage assertions, three actual voice/text/SMS/new-room browser groups,
a nine-payload Python distribution with 111 unadapted tests, a 96-payload installed
npm consumer and 166 compatibility assertions passed with complete cleanup. Native
loading and source facts remain separate non-atomic as-of observations. Loaded P1
revision0 stays read-only under the existing positive-revision native command
contract; changing that domain requires its own versioned work before integrated
release. I19 capacity/dormant-case experiments passed selected qualification;
I20 operational UI/telemetry passed selected qualification in 0040. I21 completed
selected installed-application qualification in [0041](../work-items/0041-standalone-channel-and-durable-policy.md):
twenty standalone and six separate public-P1 assertions passed. P3-I18B's separate
native RTC text application passed selected source/installed qualification in
[0042](../work-items/0042-responsive-native-policy-and-compact-demo.md).
The completed [0043 handoff](../work-items/0043-stable-result-delivery-and-return-context.md)
qualifies P2's v8 receiver/current-channel result data reads and P3 backend v2
delivery with sixteen storage/four return actual source assertions plus a separate
twenty-five-stage offline package lane. These reads do not qualify RTC media.

[0044](../work-items/0044-origin-bound-channel-policy.md) implements original
P2-input binding, schema3 facades, a narrow operation client and application HTTP
with passing focused unit/socket checks and isolated package/fake-port qualification.
Its fourteen selected actual source assertions passed. I22 remains the release frontier;
joined native voice/text/SMS, restart/discovery, applicable provider runs and video
retain their later gates. All seventeen complete charter rows remain
planned/unregistered; the catalog stays fifty-five definitions/twenty-four
registered runners.

### Qualified I19 study

The [completed handoff](../work-items/0039-bounded-channel-workloads-and-image-evidence.md)
freezes seed 39, separate retained limits of 64 capacity-study and 1,024 dormant-study
inputs, and dormant samples at 0/64/256/1,000 cases. Public bounded setup/read windows
stay at 64. Accepted rows remain inspectable; display eviction reclaims no replay
capacity. The workload's actual PostgreSQL/HTTP/restart/restore and installed package
gates passed within selected scope, without production capacity, per-case RAM or general fairness
claims. make p2-workload-plan exposes the inventory. I20 joined operations/telemetry
passed selected qualification in 0040. I21's explicit installed starter application
and separate public-P1 consumer qualified in the completed
[0041 handoff](../work-items/0041-standalone-channel-and-durable-policy.md).
All seventeen complete acceptance rows and I22 remain separately gated.

### Qualified I21 application and active origin boundary

Route the explicit accepted structured input while quiescent before serving.
The session mutex excludes concurrent mutating commands and a live gateway across
processes; reads remain available. Original send acknowledgements stay unknown
when a separately sourced lookup later reports provider acceptance. Ordinary
unknown sends receive no automatic resend permission. The read-only operations
page grants no mutation controls. The current-case contract remains non-atomic
and as of its observations; P1 revision 0 is readable, while integrated/native
execution at zero needs its own coherent versioned work. Active
[0044](../work-items/0044-origin-bound-channel-policy.md) adds an optional original-origin
application adapter without making P3 a dependency of the standalone P2 package.
It retains original input identities in existing P1-owned work; the raw message
stays in P2. Unit/socket checks and isolated package/fake-port qualification passed;
the fourteen selected actual source assertions passed. Complete I22 and charter release gates remain
planned after selected standalone qualification.

## Boundaries and dependencies

| Boundary | Required decision |
| --- | --- |
| Case authority | Exactly one authority owns current revision and confirmed facts. A small standalone adapter implements the same port; integrated mode uses the shared authority rather than copying its store. |
| Message persistence | P2 owns inbox, processing intents, reply outbox, provider attempts and communication evidence. It does not own supplier execution or P3 specialist scheduling. |
| Business operation | The fake standalone operation port and P1 integration preserve stable logical operation identity. Processing or model invocation can repeat; business acceptance cannot silently duplicate. |
| Trusted identity | Verified provider integration scope and verified end-user account scope are distinct. A JSON tenant, sender number or familiar room name grants no case access. |
| Media | LiveKit owns rooms, tracks, text streams, transcription synchronization and interruption. P2 records source-qualified evidence and adds durable acceptance/history. |
| Storage/runtime | Reuse the local PostgreSQL infrastructure with P2-owned migrations/store adapter and bounded connections. Pin a compatible TypeScript database client when introduced. Do not add Redis, Kafka, Cloud, a real carrier or Node Agents merely for HTTP/message handling. |

Contract and fake-carrier work may begin once the CaseAuthorityPort and operation
identity fixtures have agreed versions, while P1 implementation continues. It does
not require the full P1 deployment. Integrated case/confirmation tests require the
P1 PLAN-04 authority contract; P1 result delivery requires its durable completion
contract. Actual browser voice/playback requires the PLAN-11 conversational agent
and permission-qualified local media lane. P3 is never a dependency of P2.

Keep the current TypeScript console and native browser SDK as the default UI.
Evaluate official Agents UI components only when a real product conversation
surface warrants them; a React rewrite is not a prerequisite. Build the authorized
timeline/history as a durable GET/cursor projection with bounded polling and
replay-safe rendering. Do not add a bespoke WebSocket transport or parallel event
bus. A source event enters one acceptance path before any projection consumes it.

Keep one primary feature slice active. Parallel work may prepare fixtures, review
an API or implement a clearly frozen adapter; two agents must not invent different
case revisions or confirmation semantics.

## Phase P2-A: Contract and standalone durable intake

**Entry:** frozen root toolchain, an agreed version of the shared case/operation
ports, and the current M1/transport baseline. No P2 executable is assumed.

| Task | Prerequisites | PLAN | Concrete deliverable | Required failure assertion | Acceptance | Effort |
| --- | --- | --- | --- | --- | --- | --- |
| P2-I01 | Agreed CaseAuthorityPort and operation-identity contract | PLAN-12 | Freeze version-1 event discriminants, exported principal/receipt/history/error types, scoped identities and semantic canonicalization rules under the project source boundary. Record the contract decision. | Unsupported version, oversized variant and forged body scope fail before acceptance; two distinct identical-text messages remain distinct. | P2-02, P2-12 | 2–4h |
| P2-I02 | P2-I01 | PLAN-12 | Add language-neutral valid/invalid fixtures under contracts, runtime TypeScript validation and a narrow Python decoder for the adapter boundary. Define which retry metadata is excluded from semantic identity. | Both languages agree on unsupported versions, unknown variants, scope errors and changed destinations; metadata-only retry does not conflict. | P2-02, P2-12 | 2–4h |
| P2-I03 | P2-I01, P2-I02 | PLAN-12 | Implement fake-carrier signature verification plus a seeded-account association adapter. Only the trusted adapter attaches AccountScope. Define bounded single-use challenges, association versions/revocation and a local credential/principal configuration contract. | Invalid signature, forged association, another tenant/case and an unassociated sender cannot read, write or route case data. Also reject expired/reused challenges and revoked/reassigned identities; race challenge consumption atomically and permit a valid new association. Verify these failures independently. | P2-12 | 2–4h |
| P2-I04 | P2-I02, P2-I03; S-I05 applied to P2 schema/grants | PLAN-12 | Add versioned P2-owned PostgreSQL inbox/receipt/processing-intent migrations and atomic accept-before-acknowledgement. Persist the original per-tenant/account/conversation acceptance sequence; keep provider occurrence and server receipt times distinct. Provide bounded inspect/history queries. | Failure before commit produces no accepted receipt; loss after commit is reconciled by the original identity. Existing accepted records remain inspectable at admission capacity. | P2-01, P2-03 | 3–5h |
| P2-I05 | P2-I04 | PLAN-12 | Implement scoped concurrent replay/conflict and canonical-payload tests. Decide provider replay horizons, receipt/delivery tombstones and expired-identity behavior before any cleanup. | Concurrent equal events yield one logical message; changed semantics conflict; metadata-only retry deduplicates; pruning display history does not permit late duplicate acceptance. | P2-01, P2-02 | 2–4h |
| P2-I06 | P2-I03, P2-I05 | PLAN-12/13 | Add the first standalone fake-carrier example with narrow case, scripted-agent and operation adapters. Wire the P2 workspace package, explicit test discovery and the smallest real harness runners. | Run with no P1/P3 service present; an omitted adapter/setup or zero-test runner fails explicitly. Do not mistake existing root console tests for P2 coverage. | P2-16 foundation | 2–4h |

Run P2-owned migrations through S-I05's one-shot migration principal and
versioned configuration upgrade. Serving roles retain only required runtime
permissions; they cannot create schemas or receive bootstrap administrator secrets.
Test preserved-volume and repeated upgrades before accepting inputs.

**Exit:** the standalone example accepts a synthetic message, returns a durable
receipt and replays it under a new process. Concurrent dedupe and trust negatives
have executable evidence. P2-16 is only partial here: full history/delivery/recovery
and isolated package installation still follow. Register a P2 ID only when every
assertion in its charter row exists, not merely because one related task passed.

**Visible proof:** the current I06 CLI shows committed acceptance followed by
replay of the same receipt/operation key/sequence, with pending/not_executed preview.
The planned browser projection must show pending to accepted only after receipt
validation, the same receipt on repetition and actionable typed rejection. That
browser proof belongs to the later gateway/UI integration; CLI proof cannot
qualify a browser or modality assertion.

## Phase P2-B: Recoverable dispatch and revision-safe case routing

**Entry:** Phase P2-A accepted-message/store contract. The standalone authority
must share the real authority's revision/confirmation fixtures; integrated tests
wait for PLAN-04 rather than inventing a second truth model.

| Task | Prerequisites | PLAN | Concrete deliverable | Required failure assertion | Acceptance | Effort |
| --- | --- | --- | --- | --- | --- | --- |
| P2-I07 | P2-I06 | PLAN-13 | Implemented bounded per-receipt dispatch and lookup-only reconciliation under explicit owner-upgraded v2 claims/attempts and immutable prepared investigation. Cooperating operation acceptance remains external; gateway deployment follows I08. | Slow/ignored adapters retain owned capacity; stale epochs cannot publish; unknown acknowledgement preserves uncertainty and the original key. Actual-PG takeover and external-commit kill/reconciliation are selected slice evidence, not a complete product row. | P2-03, P2-13 foundation | 2–4h |
| P2-I08 | P2-I07 | PLAN-13 | Implemented real bounded loopback gateway and trusted failpoint after accepted acknowledgement before dispatch. Restart polls the same persisted eligible state; selected owned-process gates inspect original history. | Accepted input is dispatched after restart; repeated recovery cannot create another logical business acceptance. Include the normal live path. | P2-03 | 2–4h |
| P2-I09 | P2-I08 | PLAN-13 | Implemented explicit owned-process scripted agent adapter, bounded framed worker helper and independent worker-kill/replay fixture. Selected phase gates passed; the native LiveKit adapter is separately qualified in selected I15/I16 scope. | A live gateway preserves original input/case/operation through worker death and claim expiry; repeated attempts are visible with one cooperating logical acceptance. Actual process/group/pipe ownership must settle before releasing capacity. | P2-04 contribution | 2–4h |
| P2-I10 | P2-I06; shared authority fixtures from PLAN-04 | PLAN-13 | Implemented strict structured investigation router and one-selected-authority ports: owner-installed standalone reference PostgreSQL or public P1 CAS through explicit loopback application composition. The selected equivalent-authority and final phase gates passed, completing I10. | Observe real blocking graphs and one winning revision despite skewed timestamps; valid current input progresses. Lost ACK stays unknown with no receipt inference/rebase. Retained inbox access does not fence current association revocation. | P2-05 contribution; full P2-12 remains later | 3–5h |
| P2-I11 | P2-I10 | PLAN-13 | Implemented immutable quote/revision/prompt bindings, linked user confirmation and ambiguous/unlinked clarification. Selected local integration, installed package and final phase gates passed, completing I11. Current sender eligibility is a separate preflight, not an atomic cross-authority revocation fence. | Old-revision confirmation cannot authorize the current mutation; an unlinked SMS yes asks clarification, while a valid current linked confirmation can progress. | P2-06 | 2–4h |

**Exit:** gateway and agent failure scenarios use actual independent processes,
not a reopened database connection. The operation adapter records one logical
acceptance under replay. Current and stale confirmations are distinguished without
using provider timestamps as a universal order.

**Visible proof:** one case snapshot shows the winning revision. The losing or
ambiguous input retains its own receipt and explanation. Attempt history may show
reprocessing; it cannot be presented as another accepted booking operation.

## Phase P2-C: Outbound delivery with explicit uncertainty

**Entry:** durable input identities, trusted association and the reply-intent
contract. This phase may proceed alongside media work after these interfaces are
frozen. Automatic integration needs a separately published P1/application completion
handoff; the current result-only delegation feed is not that handoff. The
implemented outbox consumes an explicit trusted application reply intent and
never reads P1 store internals.

| Task | Prerequisites | PLAN | Concrete deliverable | Required failure assertion | Acceptance | Effort |
| --- | --- | --- | --- | --- | --- | --- |
| P2-I12 | P2-I07, P2-I10; agreed result-delivery contract | PLAN-14 | Implemented immutable-recipient reply intents, stable outbound identity, versioned authorized route/suppression reservation and bounded attempts in owner-upgraded inbox v3. The 24-case actual gate, populated upgrade/restore/replay, isolated ordinary fake-send consumer and final phase gates passed, completing I12. Automatic booking-completion integration remains separate. | Crash after reply-intent commit leaves recoverable work; a revocation/suppression that wins before reservation prevents a new call; later changes cannot retract an admitted call or disclose another recipient. A newly verified route for the same recipient progresses; reassignment cannot transfer ownership. | P2-10 foundation, P2-16 | 2–4h |
| P2-I13 | P2-I03, P2-I12 | PLAN-14 | Implemented authenticated callback intake with a 60-second envelope window, immutable exact-attempt observations and the deterministic fake-provider evidence reducer. The 24-case source gate and isolated installed consumer passed; final phase gates passed, completing I13. Retained callbacks veto a new reservation without retracting an already admitted call or authorizing resend. | Duplicate/reordered callbacks keep correct correlation; an obsolete callback cannot silently regress stronger evidence; another account cannot submit or inspect the callback. | P2-10, P2-12 | 2–4h |
| P2-I14 | P2-I13 | PLAN-14 | Implemented ordinary unknown holds and explicit cooperating same-key recovery with distinct local attempts in owner v5. The selected 30-case gate, populated upgrade/restore, isolated public npm consumer and final local gates passed, completing I14. Historical admission proofs survive late facts; all-prior acceptance/conflict vetoes new calls. | The outcome becomes unknown rather than failed-for-retry; the UI/report never promises one physical SMS delivery when the provider cannot establish it. Route changes cannot retarget an already sent/uncertain attempt or its recipient. Include a definitive failure and ordinary success. | P2-11 | 2–4h |

**Exit:** logical notification identity, send attempts and provider evidence are
separate records. Both certain and uncertain fake-provider outcomes are visible.
All callbacks are scoped and validated. Retention policy preserves receipt/delivery
protection independently of display-history pruning. The charter's verified-association, acceptance-sequence and immutable-recipient contracts are authoritative; callbacks and route changes never rewrite an uncertain prior send.

**Visible proof:** fake SMS changes from queued to sending to accepted-by-provider,
delivered, definitively failed or unknown only as actual evidence warrants. None
of these observations is labelled user acknowledgement or booking consent.

## Phase P2-D: Native LiveKit voice/text continuity

**Entry:** Phase P2-B routing and Phase P2-C delivery contracts, plus the actual
PLAN-11 conversational agent and self-hosted media path. The existing diagnostic
worker is reused as a baseline only; it is not a voice conversation adapter.
Resolve microphone/audio-play permission before the corresponding browser check.
A blocked or unavailable capability remains pending and cannot count as a pass.

| Task | Prerequisites | PLAN | Concrete deliverable | Required failure assertion | Acceptance | Effort |
| --- | --- | --- | --- | --- | --- | --- |
| P2-I15 | P2-I08, P2-I11; PLAN-11 conversational adapter | PLAN-15 | Completed selected native/artifact scope. Route committed browser text through P2 acceptance before dispatch to the Python agent. Integrate the installed SDK's native lk.chat path and disable the competing automatic consumption path for this adapter. Actual native, isolated artifact and final selected phase gates passed, completing this task within its selected scope. | One committed browser input yields one logical acceptance and one business-operation identity; transport retry or the default reply hook cannot create a second action. | P2-15 | 3–5h |
| P2-I16 | P2-I15; qualified local audio fixture lane | PLAN-15 | Completed selected native/artifact scope. Add the Python adapter for committed voice utterances, native generation/interruption observations and hybrid text/audio. Raw media stays in tracks; interim transcripts remain observations. Actual native, isolated artifact and final selected phase gates passed, completing this task within its selected scope. | Text and audio together use the same application acceptance boundary; interim text or repeated transcription events cannot grant confirmation or create duplicate accepted work. | P2-15 | 3–5h |
| P2-I17 | P2-I16; browser audio permission/control gate | PLAN-15 | Completed selected source-qualified response/generated-text/SDK/browser observation and scoped-interruption qualification: sixteen-case PostgreSQL storage, three-group actual browser/media, isolated npm/current Python94-test gates and 147 compatibility assertions passed. Results and separate shared phase closure are recorded in the [current handoff](../work-items/0037-playback-evidence-and-process-recovery.md). | Interrupt output halfway and retain partial/native interruption evidence; disconnect before playback evidence and retain unknown completion. Generated full text never becomes proof of full playback. | P2-07, P2-08 | 3–6h |
| P2-I18 | P2-I11, P2-I14, P2-I17 | PLAN-15 | Completed selected current-grant read-only context, public P1/reference adapters, optional SDK initialization/idle refresh and source-separated UI: storage18, actual media3, Python111/nine payloads, npm seven stages/96 payloads and 166 compatibility assertions passed with cleanup in [0038](../work-items/0038-case-rehydration-and-standalone-release.md). P1 revision0 remains read-only; loads are non-atomic as-of observations and grant no command authority. | A new room/channel resumes the same verified case and current revision; stale summaries and unassociated senders cannot override or disclose authoritative facts. | P2-09, P2-12 | 3–5h |

**Exit:** the required local browser example performs real voice interruption and
room closure/resumption. The text/audio route has one logical acceptance path.
A normal text test or native-SDK audio counter is insufficient to close the
browser playback cases. Scripted speech establishes transport/evidence semantics,
not real model quality.

**Visible proof:** channel lanes share a stable case identity, while room and route
identities change. The timeline distinguishes accepted user input, generated
response, reported playback, carrier delivery and acknowledgement. Missing data
shows unknown; switching a tab never fabricates a completed communication.

## Phase P2-E: Capacity, packaging, operability and release

**Entry:** normal and failure paths of Phases P2-A through P2-D. Complete the
standalone gates independently of a running P1/P3 deployment; integrated tests use
the public P1 operation/authority contracts. P2-I21's isolated fake-carrier package
proof may start earlier after its listed prerequisites; rerun it at release after
P2-I18. This does not relax the final actual-media continuity gate.

| Task | Prerequisites | PLAN | Concrete deliverable | Required failure assertion | Acceptance | Effort |
| --- | --- | --- | --- | --- | --- | --- |
| P2-I19 | P2-I08, P2-I14, P2-I18 | PLAN-16 | Completed selected qualification in [0039](../work-items/0039-bounded-channel-workloads-and-image-evidence.md). Seeded steady/burst/saturation and 1,000-case dormancy study, fixed premeasurement budgets, bounded ordinary observer callbacks, actual shutdown/fresh-process restart and populated restore. | Bound admitted work/queues and reject/defer explicitly before acceptance; every accepted item stays inspectable. Many dormant cases allocate no per-case room or agent. Include late replay after history pruning. | P2-13, P2-14 | 3–5h |
| P2-I20 | P2-I14, P2-I18; existing observability contract | PLAN-16 | Completed selected qualification in [0040](../work-items/0040-operations-ui-and-fixed-policy-evidence.md): read-only GET/cursors/UI, real finite producer/metric/span integration, typed read errors and retained ownership. Actual PG/HTTP16 +browser3, npm105/seven stages and current187 compatibility assertions passed. Full charter rows remain separate. | Telemetry export failure cannot block intake or create unbounded work; identifiers do not become metric labels. Pending/unknown/error transitions follow observations, with no timed fake progress. | P2-13 support, P2-17 support | 2–4h |
| P2-I21 | P2-I06, P2-I11, P2-I14; real text consumer boundary | PLAN-16 | Completed selected qualification in [0041](../work-items/0041-standalone-channel-and-durable-policy.md): additive public starter factory/bin, closed private configuration, explicit owner bootstrap and quiescent mutation lifecycle. Twenty isolated fake-carrier assertions and six separate installed public-P1 assertions passed. The application receipt ledger is synthetic external evidence, not workflow or supplier authority. | No repository-internal imports, sibling service deployment or undeclared dependency is needed. A missing export/adapter fails visibly. Full standalone case routing, history, fake delivery and recovery pass. | P2-16 | 3–5h |
| P2-I22 | P2-I19, P2-I20, P2-I21; integrated P1 public-port adapter | PLAN-16/22 | [0044](../work-items/0044-origin-bound-channel-policy.md) implements the optional original-origin application prerequisite: typed P2-input/P1-work binding, schema3 facades, narrow operation client and local HTTP, with focused unit/socket checks and passing isolated package/fake-port qualification. Fourteen selected actual source assertions passed. Complete the fresh-agent handoff, API/failure-contract review, all P2 local assertions, supported-platform evidence and labelled real-model portfolio runs. Record defects and final demonstrations; integrated native handoff and video remain later gates. | A fresh agent finds contracts/checks using repository instructions alone; missing/skipped/time-out cases keep the gate incomplete. Scripted or Cloud text runs cannot substitute for required local audio evidence. | P2-17; all P2 release checks | 3–5h |

**Local-ready exit:** all 17 P2 rows have passing executable evidence in their
required local lanes; standalone and integrated examples, migrations/restart,
installed consumer and bounded-load results are reviewed. Real SMS/Cloud are not
prerequisites. **Portfolio-ready exit:** add selected real-model voice/text runs,
checked outcomes/configuration/costs, a short success/failure demo and reviewed
benchmark evidence. Re-estimate rather than weakening a mandatory assertion.

## Acceptance traceability

A task references requirements it advances; the primary row below identifies the
final proof owner. The charter remains authoritative for the complete assertion.

| Acceptance ID | Primary implementation task | Required final evidence |
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

P2-I03's access matrix must be extended by P2-I10, P2-I13, P2-I15 and P2-I18 to
cover the later reads, callbacks and routes. P2-12 cannot be closed permanently by
checking an early webhook path while later paths remain untested.

## Milestone demonstrations

| Milestone | Normal story | Controlled failure and visible recovery |
| --- | --- | --- |
| P2-A receipt | Fake SMS becomes a durable accepted message | Replay concurrently; show one receipt and a changed-payload conflict |
| P2-B case | Current linked command advances a verified case | Kill gateway/agent or send an obsolete yes; recover accepted input and preserve current authority |
| P2-C delivery | Stable reply proceeds through fake provider observations | Lose send acknowledgement; show unknown without unsupported physical-delivery certainty |
| P2-D continuity | Voice to chat to fake SMS resumes the same current case | Interrupt or lose playback evidence; show partial/unknown instead of fabricated completion |
| P2-E release | Standalone installed package and integrated public-port consumer work | Saturate admission, restart containers and have a fresh agent diagnose a real failing scenario |

## Required telemetry, errors and data decisions

Instrument each real producer when introduced, not placeholder zero counters:
input accepted/deduplicated/conflicted; dispatch pending/attempted/recovered;
case revision conflict/clarification; outbound queued/attempted/unknown; callback
applied/retained; route changed; generated/interrupted/playback/acknowledgement
observed. Retain scoped correlation in safe logs/spans. Metric dimensions are
finite channel/provider-kind/outcome/error-code values, never tenant, phone,
case, room, message or response identifiers. Capture dispatch/queue lag, replay
counts, delivery outcomes, resumption latency, active work and dormant resource use.

Export typed validation, identity-conflict, association/access, revision/clarification,
overload and unknown-outcome failures. Keep retries bounded by declared eligibility
and deadlines; an unknown provider send cannot become definitive failure merely
to justify retry. The standalone store and installed artifact must document schema
upgrade/restore, retention horizons and unsupported versions. Accepted receipt,
case intent, supplier outcome, provider delivery and user acknowledgement remain
separate facts in both the API and UI.

## Existing verification commands and future runner policy

From the repository root, using its frozen environment, these commands exist now:

```sh
.venv/bin/python -m harness list --project p2
HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh --module p2
.venv/bin/python -m harness run --project p2
```

The last command currently reports incomplete/exit 2. Root pnpm checks discover
the implemented console, P2 channel package and P3 specialist package, including
source/test typing, tests, formatting and builds. Public examples are also included
in maintained source boundaries and format/build or executable-consumer checks.
Each new slice extends actual discovery and its relevant runner with exact working
directory, prerequisites, timeout, isolated state and artifact paths. Full P2
charter runners remain pending; preserve missing P2 IDs as non-passing. Root/shared-contract changes require the full
fast lane and affected cross-language checks, not just a focused structural pass.

## Coding-agent task packet example

**Slice:** P2-I08, gateway recovery. **Inputs:** this phase, P2-I04/I07's accepted
receipt/store/dispatch contracts and the P2-03 charter row. **Owned paths:** P2
source and tests plus the smallest necessary harness registration. **Deferred:**
new carrier channels, model inference, P1 supplier logic and browser playback.

Before code, record a work item with the exact after-acknowledgement/before-dispatch
barrier, gateway/child process owners, persistent fixture store, expected original
message/operation identities and cleanup deadline. Implement the ordinary path,
terminate the actual process at that barrier, restart with the same state and
assert eventual processing plus one logical operation acceptance. Retain event
history/process exits, run the implemented scenario and full fast checks, then
update the nearest AGENTS.md, Design.md, README.md and handoff with observed
outcomes and unresolved IDs. Do not register placeholder commands or describe
repeated model processing as exactly-once execution.
