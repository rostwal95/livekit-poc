# Revision routing and delegation acceptance

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Record the plan, observed verification and handoff for P2-I10 revision routing and P3-I08 concurrent delegation acceptance |
| Audience | Engineers changing P2 revision routing or P3 acceptance runners; coding agents |
| Scope | Selected P2-I10 and P3-I08 local phase gates; excludes linked confirmation, current sender eligibility, native media and integrated release |
| Owns | Change plan, observed verification and handoff for P2-I10 and P3-I08 |
| Related | [Work item 0030](0030-p2-agent-recovery-and-p3-completion.md) · [Work item 0032](0032-linked-confirmation-and-result-projections.md) · [P2 task plan](../implementation/p2-channel-continuity.md) · [P3 task plan](../implementation/p3-delegation-reliability.md) · [Validation plan](../validation-plan.md) |

## Behavior and scope

This work item implements two tasks:

| Project | Task | Behavior |
| --- | --- | --- |
| P2 | P2-I10 | Bounded competing-command revision routing |
| P3 | P3-I08 | Concurrent immutable delegation acceptance, public inspection example and first fully asserted acceptance runners |

It continues the completed
[agent recovery/completion phase](0030-p2-agent-recovery-and-p3-completion.md).
P1 remains the case and execution authority. Preserve the existing booking v4
(PostgreSQL booking schema version 4), work profile v1/v2/v3, provider-qualified
runtime source, dependency versions and closed evidence. The maintained implementation remains
Downloads/repositories/livekit-agent-ecosystem; the desktop workspace is an older
independent checkout.

### Criteria

| Criterion | Given | When | Safety | Useful progress | Evidence |
| --- | --- | --- | --- | --- | --- |
| P2-I10, P2-05 contribution | Two authenticated accepted commands for one case and expected revision | A controlled database race releases both commands despite skewed provider timestamps | One current authority decides; loser receives conflict, no timestamp arbitration or automatic rebase | One revision transition commits and a subsequent current command progresses | Equivalent standalone PostgreSQL and public P1 case-authority schedules with independently observed locks/state |
| Scope and command data | Immutable original inbox body and verified credential | Route a strict structured investigation request | Body cannot select account, case, SQL target, credential or confirmation; malformed/stale/cancelled cases reject safely | Current well-formed input can revise its mapped case | Negative/progress tests and finite trusted mappings |
| Revision acknowledgement loss | Public case compare-and-set (CAS) commits but reply is lost | Caller times out, inspects or retries the old expected revision | Outcome stays unknown; later matching payload is not proof of original causality; no blind write retry | Fresh current inspection is possible and an independent eligible current command progresses | Actual postcommit response-loss barrier and independent authority truth |
| P3-I08, P3-03 | Same scoped ID and immutable nested envelope | Independent processes submit concurrently; changed content competes | One logical delegation; original canonical bytes/deadline/identity survive; foreign scope cannot disclose/cancel | Original accepted work produces an issued useful result and fresh-process inspection | Actual PostgreSQL, controlled process barriers, TypeScript HTTP and independent owner reconciliation |
| P3-01 | Current issued valid policy request | Complete result, receiver acceptance and separate exact synthetic operator confirmation | Specialist has no mutation/notification right; exact guard prevents stale unauthorized action | One useful delivered result permits one leased fake supplier change | Fresh existing 13-case actual completion/action lane |
| P3-11 | Malformed, unsupported, wrong-revision/scope or excessive input/output/evidence | Both language contracts and actual receive boundaries validate | Fixed safe explanations; no invalid result commitment or action permission | Later valid current request progresses | Complete named negative inventory including context/request/image/result bounds and actual issued HTTP malformed outputs |
| Diagnostics and lifetime | Slow/cancelled adapters, failed observers, uncertain writes | Timeout, shutdown, malformed response or telemetry outage | Bound bytes/tasks/processes/connections; retain actual ownership; exclude raw input/dependency errors/credentials | Admitted independent work and close can settle | Unit/socket/process tests, finite metrics and sentinel checks |

## Interfaces and ownership

### P2 revision-routing port

P2 adds an explicit public revision-routing port, separate from investigation
dispatch. A strict versioned structured command is decoded from already accepted
text. Inbox authentication supplies its original scope, case, receipt and
operation. Expected revisions are bounded decimal strings, including zero.
Provider occurrence time is diagnostic only.

A current unchanged request and a newly revised request are distinct outcomes.
Stale/conflicting, clarification and possible-write unknown outcomes are typed. No
model, unlinked yes, generated message or playback creates quote confirmation or
supplier action authority.

### Standalone and integrated case authority

| Mode | Case authority |
| --- | --- |
| Standalone | One explicitly owner-installed, marked and bounded reference PostgreSQL case authority |
| Integrated | Only the public P1 `case_control_api`, through an explicit local application bridge under `local-setup/scripts` |

Trusted startup owns finite mappings from account/logical case to
actor/scope/task/case/schema. JSON cannot choose credentials or database
settings. P1's existing revise is an atomic expected-revision operation, with no
durable revision-command receipt. Consequently, response loss remains unknown, and
matching later state cannot identify which command won. No P1 schema/runtime
change or second integrated case ledger is introduced.

Inbox inspection authenticates retained account access and does not recheck the
original sender's current association. The router therefore provides no
association-revocation fence. A dedicated current-routing eligibility policy and
cross-authority commitment schedule remain in the complete P2-12 gate. Keep
retained history reads available rather than silently changing their semantics.

### P3 acceptance runners

P3 continues using public P1 acceptance, execution, delivery and action ports.
Concurrency adds assertions and public examples, not another scheduler or ledger.
Register P3-01, P3-03 and P3-11 only once every charter assertion actually
executes through its selected runner; registration itself is not a pass.
Oversized image rejection happens before decoding and does not qualify screenshot
extraction or multimodal inference.

The standalone local application bridge and examples are opt-in. Default Compose,
console, carrier, native media, real inference and remote continuous integration
(CI) remain separate work.

## Failure cases and validation

Gate names starting with G- refer to the engineering gates in the
[validation plan](../validation-plan.md). G-ACCEPTANCE P3 is specific to this work
item.

| Gate | Required assertions | Bounds/setup | Completion rule |
| --- | --- | --- | --- |
| G-READY/CONTRACT | Frozen routing/bridge/result contracts and complete acceptance inventories | Existing pinned Python/Node/software development kit (SDK); no dependency upgrade | Positive/negative API review before product implementation |
| G-FAST/OBS | Current and new units, structural/docs, lint/types/format, frontend and safe signals | Offline, no provider files/values or calls | Nonzero selected suites; no required skips or suppressed defects |
| G-DURABLE P2 | Real same-revision conflict, skewed timestamps, current progress and unknown committed acknowledgement (ACK) | Marked standalone schema and actual P1 v4; runtime-only bridge; controlled locks/barriers | Independent source of truth plus honest cleanup and no retarget/rebase |
| G-ACCEPTANCE P3 | Concurrent equal/changed ID; full boundary negatives; useful delivered/confirmed fake action | Independent processes, actual PostgreSQL and loopback HTTP, owner/runtime split | New direct gates and each registered harness runner pass with exact inventory |
| G-PACKAGE | Affected public routing/example imports, declarations and ordinary behavior outside checkout | Fresh frozen offline npm/wheel installs | No sibling/private storage import or implicit setup |
| Regression | Existing P2/P3 durable lanes and rebuilt default local Docker transport/persistence where runtime payload changes | Preserve original M1 (confirmed-investigation intake) identity and volumes | Required existing behavior still passes; historical media/provider evidence stays source-bound |
| G-MEDIA/RELEASE | Deferred assertions | No browser/audio/provider changes here | No full-project, native modality, scale or integrated release claim |

Fix finite work and cleanup budgets before execution. Use actual barriers and lock
observations instead of fixed sleeps as race proof. Keep live sockets, adapter I/O
and threads owned until actual settlement after waiter cancellation. Retain
initial failures and sanitized provenance separately from qualifying reports.
Correctness-run durations are not production latency percentiles or throughput
evidence.

## Results and handoff

### Implemented behavior

#### P2 revision routing

P2-I10 adds the public `./routing` and `./reference-case` exports. RevisionRouter
routes strict versioned investigation commands from an authenticated retained
inbox record. Scope, case and original input identity come from that record and
finite trusted application bindings. A typed command supplies its original
expected revision and investigation consent. A bare yes requests clarification;
it does not grant quote confirmation or supplier authority. Provider occurrence
timestamps remain observations and never replace the case revision check.

CaseAuthorityPort exposes inspect/revise. The standalone ReferenceCaseAuthority
uses an explicitly owner-installed, marked v1 PostgreSQL schema with at most 64
seeded cases. Runtime can update request/revision but cannot install, insert or
delete canonical cases or metadata. Reads avoid an unnecessary write lock; CAS
locks the selected row. A failed rollback or uncertain commit discards its pooled
connection.

Integrated mode uses the existing public P1 case authority through an opt-in
local application bridge. It creates no parallel integrated case store and leaves
P1 booking v4 unchanged. Known revised/unchanged results, conflicts,
clarification and unknown outcomes stay distinct.

#### HTTP client and Python bridge

The HTTP client binds literal loopback and trusted finite references, with strict
compact JSON and fixed typed responses. It owns both the actual request and the
assigned socket close before returning capacity.

The Python bridge uses the already pinned h11 parser and finite request/close
observers, within these limits:

| Limit | Value | Applies to |
| --- | --- | --- |
| Socket slots | 16 | Python bridge |
| Call slots | Four | Python bridge |
| Headers | 4 KiB | Python bridge requests |
| Bodies | 8 KiB | Python bridge requests |

It snapshots credentials, bindings and request values, verifies the public client
identity, and exposes only exact case inspect/revise. An observed timeout never
proves that a case write stopped. A late socket close remains owned; a later close
can succeed once the socket really settles.

#### Revision outcomes and association scope

P1 revise has no durable revision-command receipt. A lost committed
acknowledgement therefore remains OutcomeUnknown. Fresh state or a stale retry
cannot prove which original command won. No automatic refresh, rebase or second
revision request is hidden in the router or client. Inbox inspection
authenticates retained account access and intentionally does not recheck the old
sender's current association. Current-routing eligibility and atomic
cross-authority revocation remain separate P2-12 work. This implementation does
not change retained-history semantics.

#### P3 concurrent acceptance

P3-I08 adds controlled independent-process acceptance/conflict and full rejection
gates, three complete registered lab runners, and the public
`policy_completion.py` example. The race proceeds as follows:

1. Original, equal and changed submitters observe a scoped find miss.
2. The original public submission is held before commit.
3. The race observes the actual SQL holder/two-waiter graph.
4. The original submission commits.

Equal submission returns the same canonical input, deadline and identity; changed
content conflicts. A fresh process inspects it. Foreign tenant/account reads and
cancellation disclose nothing. One selected issued invocation produces a useful
strict result. This does not promise one physical computation under arbitrary
retries or other consumers.

The full rejection inventory exercises both language codecs and evidence
registries, plus five actual issued malformed HTTP outputs, including wrong
revision/schema/tenant and an oversized result. Context, request and image bytes
and image dimensions reject before decoding. The gate retains the actual fixed
`transport_unknown` runner code and independently binds malformed-response
variants to request indices. It verifies zero invalid result commits and proves
subsequent valid progress. Screenshot extraction and real inference remain
separate capabilities.

#### Public example

The public example copies both the request and the separately supplied exact
Confirmation before its first await. It composes two concurrent submissions,
actual get/inspect, one selected issued result, receiver acceptance and guarded
authorization, with application-owned clients and explicit setup. It performs no
implicit data definition language (DDL), credential loading, provider call or
process startup on import. Receiver acceptance remains accepted bytes; human
acknowledgement is unobserved. Local confirmation inputs are synthetic operator
inputs, not observed human gestures.

### Observed gates

| Gate | Result | Qualification boundary |
| --- | --- | --- |
| Full offline Python | make check passed 1,366 tests: root 1,183; P1 42; P2 14; P3 127; zero required skips/violations | Unique full suite ran once; an initial configuration error stopped before any suite |
| Lint/types/format | Ruff clean, broad mypy 120 and strict 74 source files, 292 formatted Python files | New bridge, gates and example enter maintained discovery |
| Frontend | 638 tests: console 326, P2 234, specialist 78; formatting/type/build passed | Existing bundle-size advisory remains; no new UI/media qualification |
| P2 equivalent routing | 22 cases passed in 2.556s on final exact source; both owner-held lock graphs observed two blocked database paths | Actual signed SMS/account association and PostgreSQL; synthetic SMS/controller composition, not native voice/browser |
| P2 independent truth | One competing transition/one conflict per authority, useful next progress and final revision 3 after committed-ACK loss; zero P1 quote/confirmation/intent/effect/outcome rows | Full mapped actor/scope/case/request and original inbox identities checked; no fabricated command receipt |
| Existing P2 durable lane | 23 cases passed in 8.052s, four verified owned forced exits; cleanup complete | Existing modules preserved; selected recovery cases do not complete any P2 charter row |
| Bridge socket lane | 14 meaningful tests passed with ResourceWarning treated as error | Real loopback sockets with controlled public-port doubles; SQL authority exercised by the separate 22-case lane |
| Registered P3-01 | 13 actual completion/action assertions passed through harness | Fresh issued Python-to-TypeScript result, local SQLite receiver, separate exact confirmation and leased fake supplier effect |
| Registered P3-03 | Eight actual concurrent acceptance assertions passed through harness | Original/equal/changed independent processes, SQL blocking proof, fresh reads and useful issued result |
| Registered P3-11 | 12 complete named negative/progress assertions passed through harness | Both codecs/registries, five malformed issued HTTP outputs, zero invalid results and later valid result |
| Previous P3 execution/acceptance | 12 cases passed in 14.870s and ten passed in 8.976s, with cleanup | Existing v2 issued and v1 acceptance/socket recovery scopes retained |
| P2 installed package | Seven offline stages passed in 2.403s; strict NodeNext, skipLibCheck=false and no @types/pg | Outside-checkout public routing/reference/HTTP APIs, actual reference PostgreSQL CAS, synthetic accepted-input/HTTP composition, fresh stale replay and all cleanup; P1 bridge qualified by the source gate |
| P3 archives/public APIs | 15 Python payload files equal wheel/source/rebuilt wheel; 17 npm payload files verified; 41 Python exports/strict types/canonical parity/installed HTTP passed | Frozen offline installs; existing P3 runtime payload is unchanged |
| Installed public example | 14 stages passed in 35.699s; normal created 1/fresh created 0; one evaluation/result/receipt/action/fake supplier change | Copied example imports installed public wheels/npm only; actual installed worker inquiry/mutation, independent SQL/receiver/supplier proof, original identities and complete cleanup |
| Documentation and diagrams | 104 documents and three pure scoped structural checks passed; 13 Mermaid views parsed and malformed negative rejected | Syntax qualification only; static checks intentionally request no duplicate unit suites |
| Rebuilt Docker | Eight readiness/authentication/replay/conflict/real-time communication (RTC) text/audio checks passed; ten audio frames observed | Original M1 task and volumes preserved; default transport only |

P3-01, P3-03 and P3-11 now have complete lab runners and fresh passing reports.
The catalog contains 55 cases and 24 registrations, including the baseline and 20
P1 rows. All 17 P2 and 14 remaining P3 rows stay planned; neither project nor the
full ecosystem release is complete. Correctness durations are not latency
percentiles, throughput measurements or production capacity guarantees.

### Independent review and retained failures

Independent automated reviews covered:

- the public routing/bridge wire and scopes;
- CAS uncertainty;
- actual database race evidence;
- worker, socket and pool lifetime;
- immutable example consent;
- installed artifact proof.

No human sign-off is claimed. Review corrections include:

- native AbortSignal validation before admission;
- strict primitive processing-state/error-code checks without coercion;
- retained request/socket closure;
- failed-transaction connection discard;
- a held-socket close/release/reclose regression.

Exact confirmation is copied before any await.

Retained failures and their corrections:

- The first actual standalone routing fixture exposed a real normalization defect:
  the full revision command carried `expectedRevision` into a strict case
  snapshot. Both requests became unknown before writing, so the positive-progress
  assertion failed. The reference authority now normalizes the reference to
  scope/case first. Original and later finite-stage diagnostic failures are
  retained separately.
- Owner proof no longer reports an unmeasured command count, and it checks the
  full case/request binding. A report-retention failure now returns failed/nonzero
  instead of printing a passing gate; a regression test protects this
  requirement.
- Early P3 race fixtures used an unsupported 10-second coordinator timeout. They
  later created single-use barriers after a child could publish them. The
  corrected fixture keeps the existing five-second product ceiling, creates
  barriers before startup and publishes complete exclusive process ID (PID)
  markers. Diagnostic reproductions are labelled; missing original ephemeral
  output is not invented.
- The public example's early negative fixture encountered P1's rejection of
  `explicit=False` before entering the example. A held-submit mutation test then
  verified entry-time confirmation copying.
- The first shared catalog attempt rejected the actual Node ECMAScript module
  (ESM) assertion source. `.mjs` is now an explicit supported assertion format
  with positive, missing and non-code fixtures.
- The first final `make check` found four required gate tests without matching
  foundation owners; it stopped before any offline suite. Four exact owners were
  added, and the full suite passed without weakening that rule.
- Initial lint, type, formatting and cache-permission failures remain retained.
  Authorized cache reruns changed no source or tool versions.

Final claims use only qualifying reports.

### Commands, evidence and next tasks

The closed checkpoint lives under
`.local/validation/p2-routing-p3-acceptance/5a2adeae74a1450591351fb6632c12fb`. Its
manifest binds reports, registered runner/component hashes, archives, copied
consumers, safe original failures/reviews and current sources. Prior closed
checkpoints remain intact. All 129 existing P1/service/console runtime sources, 15
P3 runtime payload files and dependency locks are unchanged. The existing
qualified P1 wheel is reused by exact hash, without a new provider/media claim.
Neither provider credentials nor a private certificate authority (CA) was read,
and no provider calls were made.

Run from the maintained repository with the frozen environment and documented
restricted-role local PostgreSQL/pinned Node setup:

```sh
make p2-routing-check
make p2-postgres-check
make p3-contract-check
.venv/bin/python -m harness run P3-01
.venv/bin/python -m harness run P3-03
.venv/bin/python -m harness run P3-11
make check
make frontend-check
make format-check
```

All selected phase gates passed, completing P2-I10 and P3-I08. Next are:

| Task | Next behavior |
| --- | --- |
| P2-I11 | Linked exact confirmation/clarification |
| P3-I09 | Resumable applicability metadata |

Default P2/P3 Compose/UI integration, current sender eligibility,
outbox/recovery, native media, further modalities, workload and integrated release
retain their separately defined gates. The local proof of concept (POC) remains
independent of remote CI and GitHub publication.
