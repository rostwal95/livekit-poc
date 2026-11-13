# Source-qualified playback evidence and process recovery

Status: Completed
Last reviewed: 11 November 2026

## Behavior and scope

Implement P2-I17 and P3-I14 after the
[completed native/deadline phase](0036-native-input-and-deadline-cancellation.md).
The [P2 charter](../projects/channel-continuity-scope.md),
[P3 charter](../projects/delegation-reliability-scope.md),
[P2 task plan](../implementation/p2-channel-continuity.md),
[P3 task plan](../implementation/p3-delegation-reliability.md),
[shared design](../../Design.md) and [validation plan](../validation-plan.md)
remain authoritative. P2 contributes to P2-07/P2-08. P3 contributes to P3-08 and
P3-04 recovery. Task completion is distinct from complete charter registration.

P2 adds opt-in durable communication evidence to the existing native composition.
A response binds original accepted input/receipt/operation, native room binding,
generation and exact public SDK speech identity. Actual full generated text,
SDK synchronized/terminal observations and browser-reported playback remain
separate immutable facts. Interruption is a speech operation; it cannot supply
consent, undo accepted input or automatically regenerate a known read-only result.
A client disconnect without completion evidence leaves playback unknown.

P3 exercises real specialist and coordinator process loss through the existing
P1 public execution, result, delivery and guarded-action ports. Replayed issuance
is lookup-only. An explicitly supplied new command after actual authority lease
expiry may admit another bounded read-only attempt; repeated computation cannot
create another authorized effect. Existing possible delivery with no known receipt
remains unknown and receives no automatic accept retry. No recovering scheduler
or competing execution ledger is introduced.

Preserve all closed prior evidence, P1's 77 runtime payloads/README/schema/API,
P3's 30 runtime payloads when existing public guards suffice, original M1 and the
default Compose/services/UI. Hold the validated dependency and image baseline.
Use local scripted fixtures, actual PostgreSQL, owned processes and self-hosted
LiveKit/browser media. Provider credential files, private CA data, paid inference,
Git publication and remote CI are not inputs to this phase. P2-I18 cross-channel
room rehydration, broader capabilities/load and full integrated release remain later.

| Criterion | Given | When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- | --- |
| Durable response anchor | Accepted native input and trusted publisher | Exact response/generation/speech binding is registered | Immutable full scope/receipt/key/room joins; no relinking or source labels from body | Actual model output proceeds only after the anchor is committed | Real PG and SDK; replay/conflict and independent owner joins |
| Actual generated text | Captured per-generation SDK call context | LLM stream completes, fails or is interrupted | Record full text only on actual normal exhaustion; no expected-fixture substitution | A valid bounded stream is retained as generated text | Actual pinned SDK, string/ChatChunk/multiple segments, error/overflow negatives |
| SDK ownership | Queued or delayed nodes and interruption watchdog | A handle becomes done before underlying work settles | Captured app token/handle mapping never follows mutable current speech; actual node/iterator ownership remains occupied | Later generation progresses only after old work drains | Real SDK queued/delayed/ignored-cancellation tests |
| Interrupted browser output | One bound response has real playing audio | User interrupts near the fixed fixture midpoint | Native interrupted/partial source evidence retained; no full-played or human ACK inferred | Same input/operation remains inspectable, later eligible response progresses | Actual browser/RTC measured media progress and durable observations |
| Missing playback | Client closes before completion evidence | Room/track/SDK close | Absent client completion remains unknown even if SDK completed | Original accepted work and generated facts remain readable | Real disconnect, independent store reads and complete owned cleanup |
| Source trust | Distinct publisher/SDK/browser-report capabilities | Wrong role, participant, response or generation is supplied | Reject without cross-account disclosure or future-response interruption | Authorized original response report is accepted | Public receiving boundaries and source-specific fixtures |
| Observation identity | Stable event UUID and canonical payload | Equal replay, changed replay, reordering or contradiction occurs | Original receipt survives; conflicts stay visible; no timestamp winner | Order-independent source-qualified projection and bounded history | Concurrent PG, immutable rows, pure reducers and installed consumer |
| Capacity/expiry | Profile-lifetime response/observation inventory | Caps, binding expiry or revoke occur | Known replay remains available; late original facts grant no new response/prepare/action | Historical scoped inspection still works | Actual caps/replay and post-lock DB-time schedules |
| Explicit v7 upgrade | Populated owner-installed v6 | Partial DDL, repeated/older upgrade or dump/restore runs | Preserve all prior inputs/outbox/native receipts, rows and role separation; no serving DDL | Fresh v7 response/evidence and old dispatch progress | Owned kill/cancel rollback, populated restore/reopen and independent byte hashes |
| Specialist/coordinator loss | Persisted accepted work and P1 issuance | Kill specialist, coordinator before invocation or during actual HTTP | Original bytes/attempt histories retained; old command never invokes again | Explicit newly created eligible attempt progresses after DB lease expiry | Real owned PID kills, fresh public consumers and one observed issuance-order graph |
| Result recovery | Valid strict result approaches protected commit | Kill before or after commit | Result/feed atomicity and original exact lookup; no hidden repeat invocation | Known result can be inspected and delivered | Actual SQL/process barriers and independent result/feed joins |
| Delivery recovery | Original receiver/route and possible intent | Kill before accept or after receiver commit | Absence stays unknown; known original receipt is reconciled without accept retry or retarget | Separate eligible work progresses around unresolved gap | Real receiver and fresh processing/ACK replay |
| Action recovery | Separately supplied exact confirmation | Kill after authoritative action commitment | Stable original receipt and one intent/effect; zero physical reapply | Existing leased worker completes one independently observed fake effect | Public action API, actual quote/worker/supplier joins |
| Exceptions/telemetry | Sink/SDK/socket/store fails or waiter leaves | Error, cancellation, timeout or close races occur | Fixed safe codes; no bodies/credentials/exception reflection; actual I/O keeps its owner | Later useful work and independent cleanup remain possible | Redaction, outage, cancellation, finite metric/capture and late-close tests |
| Public packaging | Current built Python/npm artifacts | Isolated consumers exercise new evidence/recovery | No checkout injection, undeclared runtime or sibling storage imports | Minimal public examples perform actual declared behavior | Archive/README/metadata parity, strict imports/types and selected actual integrations |

## Interfaces and ownership

P2 owns the TypeScript communication contract/store/facade, explicit owner v7
migration, native Python communication ports/SDK capture, project fixtures/tests
and project guides. Proposed additive tables are communication_settings,
native_responses and native_observations. They share the original inbox admission,
four SQL operations and two connections; no new pool, queue or execution owner.
The existing channel codec and closed six-key p2.generation wire stay compatible.
A separate versioned response mapping and authenticated response-bound playback
RPC carry observation identity. Browser RTC tokens expose neither publication nor
SQL/native-ingress credentials. No acknowledgement or inferred-consent variant
is added by this phase.

Fix the response anchor before the captured LLM node emits output. An app-owned
ContextVar is set only around synchronous generate_reply and reset immediately;
a one-shot handle binding connects the returned public handle to that captured
context before any node publication. Do not use session.current_speech as node
identity. Do not treat SpeechHandle.done as actual iterator settlement: explicitly
retain node/iterator ownership through ignored cancellation, then retire mappings.
Use public SDK surfaces only. Store SDK synchronized text only as that source's
observation; unsupported per-segment positions stay unavailable. A known interrupted
preparation is limited to the opt-in scripted read-only profile, with an actually
completed LLM stream, no SDK failure and settled ownership. Incomplete/error streams
remain unknown and do not authorize business acceptance.

Response/observation identities and tombstones last for profile lifetime, with no
physical pruning or reclaimed capacity. Proposed persisted defaults are 1,024
responses/8,192 observations/16 observations per response; maxima are
10,000/100,000/64. Raw generated text is bounded to 4,096 UTF8 bytes. Exact schemas,
source roles, reducer and limits receive a separate immutable contract before code.
Late evidence can append only to its original response after grant expiry/revoke;
current permission is still required for a new response, prepare or operation.

P3 owns recovery fixture/server/test composition and five project guides. Prefer
unchanged P1/P3 production schemas/APIs/runtime. The planned actual gate has
17 named assertions, eight verified owned kills, one actual two-waiter issuance
order graph, 25 one-time Python modes and two specialist lifetimes plus one
compiler command: 28 children within a ceiling of 32. Freeze exact modes, expected
responses and counts before implementation. Two authenticated scopes may share
one P1 profile; only completion scope is projected, without collapsing case/account
bindings or adding another ledger. The final current action uses actual public P1
case/quote/confirmation and an independently observed supplier application.

Root owns this work item, browser/controller/evidence UI, new storage/media/recovery
orchestration and wrapper negatives, Make/discovery, shared guides and checkpoint.
Keep generated full text, native progress and client-reported playback visibly
separate. UI progress must follow actual observations; no timers invent workflow
progress. Preserve reduced motion, keyboard access, safe text rendering and empty
credential fields in screenshots. Actual case/consent/business authority remains
outside communication evidence.

## Failure cases and validation

| Gate | Applies and exact scope | Execution and fixed resource bounds | Required result |
| --- | --- | --- | --- |
| G-READY | Selected IDs, migration/commitment/capture/source boundaries, public-only recovery | Closed previous checkpoint verified before edits; immutable per-lane protocol/source snapshots before normal measurement | Plan/contracts retained; missing setup or unresolved authority design is non-passing |
| G-FAST/G-CONTRACT | New models, schemas, reducers, lifetime and replay | Pinned Python/Node tools, all new source in typing/lint/test discovery; no providers | Narrow positives/negatives, full make check/frontend/format and compatibility pass |
| G-DURABLE P2 | Proposed 16 storage groups: upgrade/rollback/bind/replay/auth/reduction/caps/expiry/ACK loss/drift/lifetime/restore/telemetry | Provisional 180 seconds total/15 cleanup, at most 32 owned commands, 4 KiB per stream/256 KiB aggregate, 32 KiB report; source-freeze exact inventory before qualification | Actual fresh PG, owned termination, independently recomputable rows/digests and zero false side effects |
| G-MEDIA P2 | Three actual groups: normal source-qualified output; measured midpoint interruption; disconnect without completion report | Provisional 240 seconds total/20 cleanup, at most 32 commands, 8 KiB per stream/512 KiB aggregate and 32 KiB report; freeze exact midpoint/fixture/RTC telemetry before qualification | Native SDK/browser/PG useful progress, source-qualified unknowns, no regeneration from playback interruption and complete cleanup |
| G-DURABLE P3 | 17 recovery assertions and exact original input/result/receipt/effect reconciliation | 180 seconds total/15 cleanup, at most 32 commands, 2 KiB streams/128 KiB aggregate, 32 KiB report; every work has a fresh horizon of at most 60 seconds | Eight owned kills, one true two-waiter SQL graph, bounded explicit recovery and one authorized physical fake effect |
| G-OBS | New producer fields and error/code semantics | Finite metric names/labels, bounded sinks/tasks/capture; secret/body/URL sentinels and real failure paths | Safe emitted records, meaningful counters and independent cleanup after sink failure |
| G-PACKAGE | New P2 evidence API and P3 recovery composition | Current wheel/sdist/rebuilt/npm payload/README parity, isolated public imports/types plus unadapted fixture/example behavior | Default codec remains SDK-free; installed actual scopes labeled accurately |
| Compatibility | Affected previously qualified native/store/process and shared contracts | Prior native six-group gate and P2 141 lanes; P3 deadline/execution/applicability/action/processing as affected; preserve P1 qualification for unchanged inputs | Fresh required normal reports; no missing/skip/timeout pass and no overwriting closed evidence |
| Final local handoff | Current docs/design/harness, ordinary stack and source-bound checkpoint | Documentation/Mermaid checks, default doctor/smoke, M1 preservation, independent review and owned residual checks | Accurate completed selected tasks, source/artifact hashes and explicit remaining charter work |
| G-RELEASE | Complete product/ecosystem qualification remains later | Consider only complete P2-07/08 or P3-04/08 registrations after every required assertion and independent review passes | No blanket project, physical hearing, general model, capacity or hosted-release claim |

The budgets above are planned preimplementation ceilings; exact child/case/env/
proof contracts must be frozen before any normal measurement. A correction after
failure retains the earlier failed run and adds a new explicit source/contract
version. Diagnostics never qualify normal gates. Do not enlarge budgets or weaken
authority guards to hide a failure.

Existing commands include make check, make frontend-check, make format-check,
make p2-native-check, make p2-postgres-check, make p2-send-policy-check,
make p3-deadlines-check, make p3-execution-check, make p3-processing-check,
make p3-applicability-check and make p3-action-races-check. New focused commands
are added only with real implementation and negative report/environment fixtures.
Keep actual PostgreSQL lanes serialized; package preparation and offline checks
may run independently. Never reset ordinary named volumes or emit token commands
into shared diagnostics.

Logs carry fixed component/event/code/source/outcome plus finite durations and
occupancy, never transcript, token, arbitrary URL, body or exception text. New
Python public models/ports are typed; cancellation propagates and actual resource
ownership survives caller timeout. Browser report acceptance is not human hearing,
acknowledgement or exact quote confirmation.

## Results and handoff

Selected P2-I17 and P3-I14 are complete for this local POC. All required selected
source, installed-artifact, regression, shared and cleanup gates passed. P2-I18
current-case room rehydration and P3-I15 standalone release completeness are next;
complete P2/P3 charter, broader workload and conversational-media qualification
remain separately gated. The catalog stays at 55 cases and 24 registered runners,
with all seventeen full P2 and fourteen remaining full P3 rows still planned.

### Implemented behavior

P2 explicitly upgrades v6 to v7 through owner maintenance, adding three tables
without another pool or execution owner. Source roles, original input/operation/
room/speech bindings, commutative contradictory facts, profile growth limits and
original replay stay separate from current preparation permission. Response
sequences are scoped to tenant/account/conversation; observation sequences are
local to the response. Late facts cannot create new acceptance or consent.

The Python adapter captures immutable context at the actual public LLM/TTS node
call and binds the exact returned public SpeechHandle. It retains real producers,
streams and SDK tasks through ignored cancellation. Normal EOF supplies full
generated text; a failed/incomplete LLM iterator does not. A later TTS or playback
failure preserves an already completed generated-text fact. The scoped communication
profile rejects the legacy session-wide interrupt while preserving the older
profile. The browser shows generated text, SDK output and client reports in
separate lanes. Actual PCM windows support the controlled interruption demo;
missing completion reports stay unknown. Latest-read fences prevent stale failures
from overwriting recovered response availability. End owns every actual reader,
I/O, worklet, port, source and AudioContext through settlement.

P3 adds qualification composition over unchanged public P1/P3 runtime authority.
Real specialist/coordinator process loss reconciles original issued input, results,
delivery and exact confirmed action. Original possible delivery with no receipt
stays unknown; only an explicit new eligible command admits another read-only
attempt. There is no recovering daemon, second accepted-work queue, automatic
receiver accept retry or inferred consent. Independent supplier truth records one
authorized fake application, without claiming exactly-once computation.

### Executed qualification

| Gate | Observed result | Exact scope and limits |
| --- | --- | --- |
| P2 storage, final normal 04 | 16/16, 21 commands, two owned kills, two actual SQL graphs; 7.589 seconds; cleanup passed | v6 preservation/rollback, v7 replay/binding/roles/reduction/caps/expiry, retained I/O, count/catalog drift and populated restore; ten responses/thirty-two facts; direct public API plus real PG, not sixteen HTTP/media tests |
| P2 playback, final normal 05 | 3/3 groups in one Playwright case, nine commands; 26.721 seconds; cleanup passed | Actual local SFU/SDK/browser. Normal non-silent PCM 1,864 ms, interruption trigger 877 ms and settled partial 973 ms against the 2,058.25 ms fixture; final client-report-withheld response remains unknown |
| P2 read recovery | Actual forced HTTP 503, response-local unavailable state, released fault and same-response successful refresh | Preserves original facts and logical operation; no timer-created progress or stale global failure banner |
| P3 recovery source | 17/17, eight actual owned kills, one issuance SQL graph, 28 commands; 53.574 seconds; cleanup passed | Explicit original-identity recovery through existing authorities and independently observed authorized fake effect |
| P3 installed recovery | 17/17, eight kills, one graph, 28 commands; actual gate 59.236 seconds; cleanup passed | Fresh current Python/npm artifacts, unchanged P1 wheel, five unadapted fixture/contract copies; compiler command checks a strict public installed consumer, not checkout source-build parity |
| P2 installed npm | 84 payloads plus current README/semantic manifest; seven commands; 2.146 seconds | Strict public NodeNext consumer without @types/pg; actual v7 PG/receiving HTTP, independent role negatives, fresh-process original receipts and zero repeat preparation/operation calls |
| P2 installed Python | Eight payloads in wheel/sdist/rebuilt wheel, raw README/RECORD parity; fifteen commands; 94 zero-skip tests | Default codec/pure communication remain SDK-free. Optional pinned SDK imports/types, 31 actual SDK lifecycle/control tests, eighteen HTTP tests, twenty-eight pure-model tests, four streaming units and thirteen mixed Lab tests; no installed RTC/provider claim |
| P2 compatibility | 147/147: 23 recovery, 22 routing, 18 confirmation, 24 outbox, 24 callback, 30 send-policy and six prior native groups | Backend source 04 and native source 05 split is explicit; runtime payloads/README are unchanged across the later proof-writer adjustment; all cleanup passed |
| P3 compatibility | 80/80: execution 12, processing 16, applicability 18, action races 16 and deadlines 18 | Existing selected authority/deadline behavior preserved; each actual gate cleans its owned profile |
| Final shared Python | 1,966/1,966; no skips; lint and broad/strict typing passed | 49 P1, 94 P2, 277 P3 and 1,546 root tests; 143 broad and 123 strict typed files |
| Final frontend and format | 1,124/1,124 TypeScript tests, types/builds, isolated native build and formatting passed | 458 console, 588 P2 and 78 specialist tests; 369 Python files formatted; existing default bundle-size advisory is not a capacity result |
| Documentation and diagrams | 111 documents, zero violations; all 28 Mermaid diagrams parse | Standard templates, current instructions/roadmaps and source-qualified observability; diagram parsing is syntax evidence, not semantic or visual proof |
| Ordinary stack and preservation | Doctor ready; eight real smoke checks and ten observed audio frames; original M1 task preserved | No inference/provider calls, volume reset or default UI/Compose change. Read-only residual audit found zero selected native/recovery schemas and rooms |

### Failure provenance and corrections

Earlier failures remain retained and non-passing. P2 storage normal 01 exposed a
v6 seed reply that inherited a v7 terminal literal. Normal 02 reached both actual
kill/lock schedules but rejected four uncontracted expiry-proof fields. The fixture
was aligned with the frozen v6/closed proof contract; the guards were not relaxed.
Normal 03 passed; normal 04 reconfirmed the final shared helper/source binding.

Playback normal 01 lost its browser stage before temporary-tree removal; its exact
original cause is unavailable. Normal 02 retained the normal-stage timeout. A
subsequent static audit found the test filling a field inside a closed Input
references disclosure. The test now follows the visible UI, as the earlier native
positive already did. Normal 03 passed all browser paths and receiving-side media
verification but rejected a source-proof file written as 0644. A controlled
reproduction confirmed the writer behavior; explicit O_EXCL/O_NOFOLLOW 0600 writes
and exclusive/symlink tests fixed it. A nonexistent redundant artifact filename
was removed; all seven real required proofs remained. Normal 04 passed. Visual
review then found the stale read-warning presentation; final normal 05 adds actual
read-failure/recovery evidence and passes all original playback predicates.

P3 diagnostic runs never qualify normal recovery. Retained failure/source versions
record restricted-role SQL visibility, the safe parent/child diagnostic refinement,
a fixture actor-scope argument error, and manual confirmation serialization that
omitted the public schema. Named public bindings and public payload serializers
fixed those defects; physical apply/count and authority predicates stayed strict.
The first failed source run and one early diagnostic lacked enough context to
recover their exact original causes. This limitation is preserved. The final source
and installed gates, safe proofs and independent reviews pass.

First npm preparation referenced a missing private driver template before actual
PG measurement; the corrected isolated driver is retained. Earlier 91- and 93-test
Python artifacts remain valid historical predecessors. The fresh 94-test artifact
binds the current example writer and unadapted test copies. Missing discovery owners
and outdated test-corpus report literals were corrected; final full gates pass.
No authority, resource, audio or timeout budget was enlarged to hide a failure.

### Source and evidence binding

Local reports live under .local/validation/p2-communication,
.local/validation/p2-playback, .local/validation/p3-recovery and the existing
regression/artifact families. The consolidated source-bound checkpoint is
.local/validation/p2-playback-p3-recovery/ccfb98f7872c4cf6afc099dd482439c9.
Machine evidence owns file/archive identities, safe diagnostics, commands,
independent reviews and provenance; source-control identifiers are not documentation.

Independent reviews recomputed the storage restore/receipt/clock joins, all seven
media proof hashes and actual SDK publication/SQL joins, source/installed P3 proof
bundles, isolated archives/README/RECORD and current consumer copies. Reviewers
explicitly disclose authored fixtures/tests. The final media freeze includes 127
unchanged maintained inputs plus three unused generated build entries; the latter
were replaced by the subsequent native build. The actual gate serves Vite source,
not those generated outputs. This overbroad freeze and current build identities
are explicitly recorded. Storage normal 04 binds its 111-file snapshot through 109 unchanged current inputs
and two retained, byte-verified playback helper/test snapshots. Those later deltas
change a non-executed browser-proof literal and playback test corpus; all four
media-helper dependencies actually used by the SQL wrapper have identical ASTs
and global construction. No 111-current claim is made. Historical source snapshots
reconstructed after edits were byte-verified against premeasurement hashes and
labelled as reconstructions.

All 1,145 closed prior artifacts were reverified. P1's 77 and P3's 30 production
payloads, P1 READMEs, locks, image pins, default Compose/console and original M1
remain unchanged. Provider/private-CA files were not read. Known SDK/browser
facts do not establish physical hearing, human acknowledgement, consent, model
quality, general ASR, supported-platform release or production capacity. Continue
with I18/I15 under a new scoped work item and fresh gates.
