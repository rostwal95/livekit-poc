# Explicit send uncertainty policy and protected action races

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Record the plan, observed verification and handoff for P2-I14 send uncertainty policy and P3-I12 protected action races |
| Audience | Engineers changing P2 send reconciliation and retry or P3 guarded-action schedules; coding agents |
| Scope | Selected P2-I14 and P3-I12 local gates; excludes native composition, real carriers, automatic retry and full release |
| Owns | Change plan, observed verification and handoff for P2-I14 and P3-I12 |
| Related | [Work item 0034](0034-callback-evidence-and-applicability-refresh.md) · [Work item 0036](0036-native-input-and-deadline-cancellation.md) · [P2 task plan](../implementation/p2-channel-continuity.md) · [P3 task plan](../implementation/p3-delegation-reliability.md) · [Validation plan](../validation-plan.md) |

## Behavior and scope

This work item implements P2-I14 and validates P3-I12 after the
[completed callback/applicability phase](0034-callback-evidence-and-applicability-refresh.md):

| Project | Task | Behavior |
| --- | --- | --- |
| P2 | P2-I14 | Adds an explicit trusted reconciliation/retry policy for immutable outbound operations |
| P3 | P3-I12 | Exercises the existing public guarded-action and worker interfaces under real revision, cancellation and process-loss schedules |

The [P2 task plan](../implementation/p2-channel-continuity.md),
[P3 task plan](../implementation/p3-delegation-reliability.md) and their charters
remain authoritative. This slice contributes to P2-11 and the P3 protected-action
requirements. Task completion does not register an entire charter row.

The P2 policy includes a real local fake provider that observes a request and
loses its response.

- Ordinary possible sends remain unknown and cannot be resent.
- A separate cooperating idempotent fake capability may safely reuse its original
  provider key through a new explicitly authorized local attempt.

P1 remains the sole work/case/action and effect authority. Preserve its 77 runtime payloads, schema
and public APIs. Preserve P3's 30 runtime payloads unless an evidenced defect
requires review.

Keep dependency locks, image pins, provider configuration and ordinary M1 state.
These remain separate phases: native voice/text/UI composition, real carriers,
paid inference, automatic booking completion handoff, automatic retry, broader
deadline/recovery schedules and full release. No remote CI or publication is
required.

### Terms used in this record

| Term | Meaning |
| --- | --- |
| Implementation task IDs | Such as P2-I14; identify tasks in the project task plans |
| Acceptance IDs | Such as P2-11; identify rows in the project charters |
| Selected gates | The gates chosen for this work item; passing them does not complete a full charter row |
| Gate names | Such as G-READY and G-DURABLE; refer to the engineering gates in the [validation plan](../validation-plan.md) |
| Acknowledgement (ACK) | A receiver's confirmation that it accepted a message or command; a lost ACK leaves the outcome unknown |
| Data definition language (DDL) | Schema-changing SQL; explicit owner upgrades run it, serving code does not |
| Foreign key (FK) | Has its usual database meaning |
| Time to live (TTL) | Has its usual database meaning |
| M1 | The original confirmed-investigation intake data, which every phase preserves |
| Process ID (PID) | Identifies an operating-system process; an owned PID kill terminates a process that the gate itself started |
| SQL waiter graph | An observed PostgreSQL lock-wait chain, read through pg_blocking_pids, showing which sessions wait on which holder |

### Criteria

| Criterion | Given | When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- | --- |
| Ordinary possible send | A non-idempotent provider has observed the original request | Response is lost, process restarts or the route changes | Retain unknown; explicit retry holds with zero calls; original recipient/route bytes survive | Unrelated eligible operation and ordinary known success still progress | Actual loopback HTTP, separate provider ledger, fresh process and SQL |
| Cooperating idempotent operation | Trusted fixed provider integration and immutable original operation | A fresh controller command requests reconciliation or retry | Lookup alone never grants permission; known acceptance/callback holds; every retry rechecks current permission without retargeting | An eligible explicit retry uses a new local attempt and identical provider key/payload; two requests yield one fake acceptance | Actual HTTP/SQL concurrency and independent ledger joins |
| Controller identity and retention | Stable command UUID, exact target/expected attempt and fixed capability | Equal replay, changed semantics or capacity is reached | Equal replay performs no network call; changed payload conflicts; old ordinary attempts cannot gain idempotency | Original receipt remains readable/replayable at retained capacity | Strict raw/type/canonical negatives and populated v4-to-v5 restore |
| Callback ordering | Any retained callback on an older or latest attempt | It contends with a new retry reservation | Callback-first vetoes; reservation-first cannot retract the admitted call; reused key alone cannot route callbacks | Existing callback v1 matches its exact attempt and digest | Actual blocking graphs and independent request counts |
| Revision before action | A has passed facade preflight and has an exact confirmation | B wins the authority lock and advances the revision | A's protected transaction rejects with zero A intent/effect | Independently exact-confirmed current B commits/applies once | Two actual SQL waiter graphs, public errors and full identity joins |
| Intent before revision | A wins the protected intent transaction | B attempts to revise the committed case | B receives the public intent-committed rejection; do not invent a later B revision | Original A receipt/effect remains available and applies once | Reverse SQL order and independent authority/supplier reads |
| Cancellation boundary | Cancellation competes with pre-intent, claimed or reserved work | Existing public cancellation/worker ports run | Pre-intent/pre-dispatch prevents application; after reservation stays best effort; after-claim conflict remains explicit | Fresh terminal reads/replay and independent eligible cases progress | Real bounded hooks, fixed public outcomes and supplier ledger |
| Commit loss | An owned child reaches a verified boundary | It is killed before/after action commit or after supplier commit | Precommit rolls back; postcommit original receipt survives; supplier success is looked up without reapplication | A fresh process reconciles exact original identity and completes | Three owned PID kills, immutable receipts and independent applied-call count |
| Lifetime and diagnostics | Slow sockets/threads, caller cancellation or observer failure | A waiter abandons or close times out | Actual work keeps its slot until settlement; no secret/body/credential labels; uncertain effects stay uncertain | Later useful progress and owned complete cleanup | Unit, raw boundary, actual process and telemetry negatives |

## Interfaces and ownership

### P2 immutable operation and explicit policy

#### Operation identity

Keep ChannelOutbox.send's ordinary contract and callback v1 unchanged. Add an
explicit IdempotentFakeSmsClient with:

- the trusted idempotent_fake_sms_v1 capability;
- bounded fixed loopback send/lookup endpoints;
- a stable immutable ProviderOperation.

Canonical operation bytes bind the trusted provider scope/key, the original
logical recipient/account/case/conversation/outbound/response and the frozen
sender/address/body. They exclude the local attempt UUID and observational
association/route epochs. Each new local invocation retains its own attempt UUID
and the existing attempt-sensitive request digest. A callback still requires the
exact attempt, operation key and request digest. The stable key alone grants no
association or recipient access.

#### Wire format and bounds

The send wire carries the frozen operation once, plus attempt identity/digest and
route/association observations. Validate and reconstruct the full canonical
SendRequest. Lookup carries only the configured provider scope, stable operation
key and operation digest, after local full-operation validation.

| Limit | Value | Applies to |
| --- | --- | --- |
| Request bytes | 32768 | Send wire |
| Command receipts | 4096 | Controller commands |
| Lookup observations | 2048 | Lookup wire |

#### Controller commands

The server-only outbox surface exposes:

- reconcile(controllerToken, command);
- retry(controllerToken, command);
- recoveryCommand(accountToken, commandId);
- inspectRecovery(accountToken, outboundId).

Recovery-controller grants are separately trusted, scope-bound and distinct from
account/publisher access. No caller body/model chooses credentials, provider
capability, recipient or policy. Stable equal command replay returns its first
semantic receipt/observation before new reads/caps and performs zero provider
I/O. A changed target/expected attempt conflicts. A new observation or retry
requires a new explicit command identity.

#### Uncertainty and retry rules

- Ordinary ambiguous sends remain held.
- Lookup known/absent/unavailable is separate as-of evidence and never overwrites
  send_results.
- Known acceptance holds any new retry.
- A provider-reported definitive nonacceptance must be durable terminal truth for
  that stable key: an original delayed call cannot later be accepted under the
  cooperating fake contract.
- A merely absent/not-yet-observed operation remains unknown and cannot authorize
  a new key. Absence or unavailability remains unknown.
- Only these together may reserve a new attempt: a fresh trusted command, the
  configured idempotent-and-lookup capability, current original-recipient
  permission and no callback veto.
- Contradictory message identities remain conflicted. They never erase facts or
  open sends.
- Historical lookup may record truth after revocation but cannot authorize retry.
- Current route observations may reauthorize the same original address. No new
  address retargets the frozen operation.

#### Owner v5 storage upgrade

Upgrade inbox v4 to v5 explicitly under owner maintenance/quiescence:

- Add only send_policy_settings, send_operations, send_recovery_commands and
  send_recovery_observations.
- Put the bounded mutable recovery_count in the new settings row, with runtime
  column-only UPDATE permission. Preserve old admission row shapes.
- Relax the old send_attempts provider-key uniqueness and add its composite
  tenant/account/outbound/operation FK.
- Operation keys remain unique in send_operations. That table fixes the provider
  namespace/capability/canonical digest and the first-attempt anchor.
- The first-attempt FK is deferred so both immutable records commit together
  before any call. Validate anchor, request/digest/provider namespace on
  reservation/read.

An additional immutable admission proof and digest in the new operation row
preserve the exact evidence used for a later new-key operation. That evidence is
either the first-operation identity, or its immediate predecessor attempt/key and
one exact immutable definitive-nonacceptance send-result/lookup-observation
digest. Cap this canonical proof at 4096 bytes.

History validates this committed proof independently of later aggregate evidence.
Late contradictions cannot erase an already admitted operation or authorize
another call. A separate fresh admission check examines at most five retained
operations for the logical outbound. Known acceptance or conflict on an earlier
operation vetoes any new key or retry call. Historical reads still return the
originally admitted operation and its immutable proof. Runtime performs no DDL,
deletion or immutable-row update.

#### Adopting old attempts

Adopt old attempts as separate ordinary operations in validated pages of 64. Never
retrofit idempotency through changed constructor configuration. Preserve old
request/result/callback/receipt bytes. Bound adoption by the existing retained
reply/attempt caps. Malformed rows or drift roll back the entire owner upgrade.
Old upgrade functions validate the current version without downgrading it.

#### Limits and retention

Retain the existing attempt, network-call, SQL-call, waiter and close limits.
Recovery commands and observations add their own bounds.

| Bound | Value |
| --- | --- |
| Attempts per reply | existing five |
| Network calls | two (maximum four) |
| SQL calls | four over two connections |
| Waiter | default two seconds/maximum five |
| Close | two seconds |
| Recovery commands | default 10000 total/eight per operation, maximum 100000/32 |
| Observations | one immutable observation per command |
| Inspect | at most five compact operations |

Retention is the profile lifetime, with no TTL or identity reuse/capacity
reclamation. Actual I/O owns its slot after caller abandonment.

#### Ownership

P2 owns its contracts/client/policy/store/migrations, public exports, project
unit/actual tests, p2_send_policy_check.py, wrapper negatives and three project
guides. Shared tooling owns the Makefile and foundation/documentation discovery.

### P3 existing authority under explicit schedules

#### Ownership and test hooks

Use the unchanged public P1 ActionClient, case-control, worker and supplier ports
and the unchanged public P3 completion facades/example. Test wrappers only
schedule their existing trusted test hooks. Product code never imports private P1
stores.

| Owner | Owns |
| --- | --- |
| P3 | `pg_action_race_cases.py`, `test_action_schedules.py`, the explicit `p3_action_case_fixture.py` helper and five project guides |
| Shared tooling | `p3_action_races_check.py`, root protocol negatives and integration guides |

#### Lock-order schedules

A validates through facade preflight before the owner fixture holds the isolated
case admission lock. Prewarm independent B and observer/locker children, queue
B-then-A or A-then-B, and observe actual pg_blocking_pids two-waiter chains.
Release promptly without changing P1's 1000 ms SQL lock timeout. Do not start
interpreters while writers wait, and do not substitute fortunate sleeps for an
observed graph.

- **B-first.** B commits revision two to three before A reaches its protected
  guard. A may reject at revision three before B's separate three-to-four edit
  commits. The later current B at revision four receives an independent exact
  confirmation and progresses. Do not claim that the complete two-edit revision
  sequence was committed before A's atomic check. Stale A commits zero
  intent/effect.
- **A-first.** A commits its intent and causes B's public revise to reject with
  intent_committed. Once A's intent commits, revision cannot succeed on that case.

#### Cancellation outcomes

| Cancellation point | Outcome |
| --- | --- |
| Before intent | Returns `cancelled_before_commit` |
| Before dispatch | Returns `cancelled_before_dispatch`, with a retained CANCELLED effect and zero supplier call |
| After claim | May make the resumed old worker raise TransitionConflict; record that safe existing conflict and inspect terminal facts rather than changing the worker |
| After dispatch reservation | `requested_best_effort` cannot fence an admitted held supplier call |
| After known supplier success | Known supplier success/result/receipt survives later cancellation/deadline; terminal cancellation is `already_terminal` |

#### Fresh fixtures and identity joins

Use a fresh independent supplier/case/inquiry/quote for each schedule. Applying
one quote advances the supplier revision, which reused stale setup cannot hide.
Each individual work schedule respects the unchanged maximum 60-second work
horizon. Join the exact source/work/attempt/result digest through confirmation,
intent/effect, supplier receipt and applied_calls; counts alone cannot qualify it.
Receiver acceptance remains separate from supplier/business completion and human
ACK.

## Failure cases and validation

| Gate | Applicable and why | Exact assertions | Prerequisite/resource/time bound | Expected evidence |
| --- | --- | --- | --- | --- |
| G-READY | New P2 durable policy and P3 schedules | Freeze four-table/operation/controller/unknown contracts and closed actual child inventories before edits | Prior phase34 (work item 0034) checkpoint and current source equality | This work item, machine contract and plan |
| G-FAST/OBS | New public types, async policy and tooling | Strict primitive/canonical/scope/conflict/cap, snapshot mutation, cancellation, late cleanup, secret sentinels, telemetry outage and useful progress | Offline frozen dependencies, no providers/private CA | Full Python/frontend, lint/types/format and targeted negatives |
| G-DURABLE P2 | New owner v5 and explicit uncertainty | Populated v4-to-v5, repeat/old upgrades, SQL-cancel rollback, populated pg_dump/restore, real lost responses, lookup/retry races, two owned PID kills and independent provider ledger | Role-separated actual PostgreSQL and owned loopback HTTP, fixed finite child budgets | Thirty frozen named assertions with complete cleanup |
| G-DURABLE P3 | Existing atomic action/external effect boundary | Both revision lock orders, exact valid B, pre/post reservation cancellation, pre/post action commit and supplier-commit process loss, no reapply | 180 seconds total/15 cleanup; at most 32 child calls; 128 KiB aggregate/2 KiB per stream/32 KiB report | Sixteen assertions, two actual SQL graphs, three owned PID kills and exact joins |
| G-PACKAGE | Reusable public policy and existing action composition | Fresh offline npm/wheel/sdist/rebuilt installs, strict public imports/types, actual policy/action fixture outside checkout and original command replay | Frozen source and bounded isolated consumer resources | Archive/source parity, exact example/fixture hashes, actual cleanup |
| Regression | Preserve old profiles and qualified behavior | P2 callbacks/outbox/routing/confirmation/recovery; P3 coordinator/execution/projection/processing/applicability and registered P3-01/03/11 | Exclusive serialized actual PostgreSQL lanes | Fresh exact selected reports; no skip/missing/timeout pass |
| Runtime/docs | Reproducible local handoff | Full source/dependency preservation, Docker readiness/text/audio, original M1, standardized guides and all Mermaid syntax | No reset or providers | Measured logs, independent review and sealed checkpoint |
| Full project release | Broader media/load/recovery still pending | Preserve catalog registrations and remaining normative rows | Separate future gates | No blanket P2/P3/ecosystem pass |

### Frozen P2 assertions

P2 freezes 30 assertions:

| # | Assertion |
| --- | --- |
| 1 | Populated upgrade preservation |
| 2 | Repeat/old upgrades and limits |
| 3 | Interrupted DDL rollback |
| 4 | Populated v5 dump/restore with original replay |
| 5 | Runtime privilege/catalog/counter drift |
| 6 | Controller/account/publisher scope |
| 7 | Ordinary/idempotent normal success |
| 8 | Definite failure plus separate useful new operation |
| 9 | Ordinary provider-observed lost response |
| 10 | Fresh-process original unknown after route change |
| 11 | Ordinary explicit retry hold |
| 12 | Idempotent lost response |
| 13 | Exact known lookup without send |
| 14 | Absent/unavailable lookup without automatic retry |
| 15 | Explicit new same-operation retry with distinct attempt/two HTTP requests/one fake acceptance |
| 16 | Equal command replay without I/O |
| 17 | Changed command conflict |
| 18 | Concurrent retry reservation |
| 19 | Stale expected attempt/attempt cap |
| 20 | Revoke/suppression/route no retarget |
| 21 | Reservation-first frozen bytes after revoke |
| 22 | Any-prior-callback veto first |
| 23 | Retry-first late callback |
| 24 | Callback exact old/new attempt with reused key |
| 25 | Wrong operation/digest/key/message conflict and late evidence preserving already-admitted operation history |
| 26 | Global/per-operation command cap and replay |
| 27 | Owned post-provider-observation kill/fresh replay |
| 28 | Owned post-reservation pre-wire kill/safe progress |
| 29 | Actual ignored-timeout I/O lifetime/diagnostics |
| 30 | Independent SQL/provider reconciliation |

SQL cancellation is not a process kill.

### Frozen P3 assertions

P3 freezes 16 assertions:

| # | Assertion |
| --- | --- |
| 1 | B-first stale A reject |
| 2 | Independently confirmed B effect |
| 3 | A-first B revise rejection |
| 4 | Committed boundary/original receipt |
| 5 | Pre-intent cancel |
| 6 | Post-intent pre-dispatch cancel |
| 7 | After-claim cancel |
| 8 | Post-reservation cancel and original apply |
| 9 | Known supplier success after late cancel/deadline |
| 10 | Precommit kill rollback/progress |
| 11 | Postcommit kill original replay |
| 12 | Supplier-commit kill lookup without reapply |
| 13 | Changed confirmation/scope conflict |
| 14 | Caller timeout/cancel actual I/O ownership and cleanup |
| 15 | Receiver-versus-business/ACK distinction |
| 16 | Exact identity joins |

The closed mode/env manifest is recorded before measurement.

### Diagnostics, tooling and commands

- Use existing fixed public error/outcome enums.
- Emit actual bounded controller, lookup, retry, hold/veto, unknown-ACK and
  retained-active counters with explicit units. Use no
  account/recipient/address/key/work/event/body metric labels.
- Log fixed safe operation/outcome/error fields. Never log raw headers,
  credentials, exception text or bodies.
- Contain observer failure. Translate boundary errors once, propagate
  cancellation, retain actual calls after waiter timeout, and require later
  progress.
- New Python fixtures/wrappers/helpers enter lint/format/strict typing/test
  discovery with their source.
- Preserve first failures and exact finite owner/runtime child environments, with
  no ambient provider/proxy/Python-path/database selectors.
- Create owned UUID schemas/files/barriers, terminate only owned children and fail
  incomplete cleanup.
- Freeze fixture/mode/protocol names before normal qualification.

Commands from the maintained repository include:

| Task | Command | Notes |
| --- | --- | --- |
| Shared fast gates | `make check`, `make frontend-check` and `make format-check` | None |
| New P2/P3 lanes | `make p2-send-policy-check` and `make p3-action-races-check` | New target commands become runnable only when their implementations are present |
| Regression lanes | The explicit prior service lanes | None |
| Registered lab rows | `harness run P3-01/P3-03/P3-11` | None |

Required unavailable setup, missing assertions, skips, zero tests and timeouts
cannot pass.

## Results and handoff

P2-I14 and P3-I12 completed their selected local implementation/validation gates.
No full P2/P3 charter row was registered.

- P1 retains case/work/action/effect ownership. Its 77 runtime payloads, packaged
  README, schema and public API are unchanged.
- P3's 30 runtime payloads and schema are unchanged.
- Dependency locks and ordinary local state are preserved.

| Area | Implemented or verified behavior | Observed evidence |
| --- | --- | --- |
| P2 send uncertainty | Owner v4-to-v5 upgrade with four new tables, frozen operations, independent local attempts and trusted explicit reconciliation/retry | Final 30-case source gate passed with two owned process kills. Ordinary provider-observed response loss stays unknown after route change/fresh process; an eligible cooperating same-key retry makes two requests with one fake acceptance |
| Temporal authority | Immutable admission witness validates past facts; current all-prior-operation acceptance/conflict/callback evidence separately guards new calls | Late contradictory provider evidence preserves admitted B and blocks C/retry B; known facts/replay are not revalidated as new reservations. Definitive nonacceptance is a durable tombstone in the cooperating fake contract |
| P2 permissions and retention | Current original-recipient route/suppression/association checks under shared admission; bounded commands retained for profile lifetime | Explicit revocation before reservation holds with zero call; reservation first preserves its admitted call. Per-operation eight and legitimate global 128-command exhaustion preserve original replay/inspection; 128 commands/126 observations retained |
| P2 observed SQL ordering | One owner DDL-cancel blocking path, one retry race with two waiters and one callback race with two waiters | The raw blocking_graphs values upgrade:1/retry:2/callback:2 describe waiter counts in these paths, not five independent graphs. Independent retained PID chains and provider ledger agree |
| Populated P2 restore | Actual Docker pg_dump/psql backup, restore and fresh reopen at retained capacity | Original v4 bytes and all populated v5 rows preserve exact before/after/reopen snapshots. Explicit sorted-key compact ASCII JSON codec makes each snapshot digest directly recomputable; 35 local-provider HTTP observations stay 35 with no replay calls |
| P3 guarded action | Actual public facade preflight followed by both SQL writer orders, exact current B progress and retained A receipt | Final source gate passed 16 cases, two real two-waiter SQL graphs and three owned SIGKILLs. B's first revision change precedes A rejection; B's separate later edit supplies independently confirmed revision four. A-first rejects B's revision |
| P3 cancellation and effect truth | Before-intent/before-dispatch prevention, explicit after-claim conflict, best effort after reservation and fresh supplier lookup after commit loss | Independent joins verify 12 strict results, 10 exact actions, six physical supplier applications and two result-receiver receipts. All supplier apply calls equal successful applications, so replay cannot hide another physical call |
| P3 business completion | Separate immutable outcomes/events and notification state | Nine terminal tasks have exact outcome/event/intent/result/cancellation joins with business notifications pending and zero delivery attempts; two result-receiver acceptances establish neither business notification nor human ACK |
| Installed consumers | Fresh offline npm/wheel/sdist/rebuilt archives install outside checkout through declared public APIs/types | P2 72 exact dist/README payloads plus semantic manifest parity; public controller reconciliation/retry and fresh-process original replay retain 3 commands/3 observations with sends 3→0 and lookups 1→0. P3 30 runtime payloads match all three archives; exact unadapted final fixture passes all 16/3 kills/2 graphs in the isolated installed consumer |
| Compatibility | Fresh selected old-profile/process regressions | P2 callbacks/outbox/routing/confirmation/recovery 24/24/22/18/23: 111 assertions. P3 coordinator/execution/projection/processing/applicability and registered P3-01/P3-03/P3-11: 10/12/12/16/18/13/8/12, totaling 101 assertions |
| Engineering gates | Full offline discovery, strict types, formatting and production builds | 1,660 Python tests: 49 P1, 14 P2, 238 P3, 1,359 root. TypeScript 861: 326 console, 457 P2, 78 specialist. Broad typing 138/strict 108; Ruff formatting 340 files; zero required skips or structural violations |
| Runtime and documentation | Original local POC state preserved after isolated gates | Ordinary Docker start and final readiness/smoke passed with eight checks and ten actual diagnostic audio frames; original M1 identity remains. All 108 documents and 18 current Mermaid bodies pass their respective documentation/syntax checks |

### How the results were measured

The final global Python/type results come from one complete make-check rerun after
the evidence-hash helper regression was added. Its type excerpt is not another
execution. The preceding 1,659-test run remains retained. Frontend and formatting
checks are separate measured runs. Correctness-gate durations do not establish
production latency, throughput, provider capacity or real-model/media quality.

Commands include make check, make frontend-check, make format-check,
make p2-send-policy-check, make p3-action-races-check, the selected old service
lanes, registered lab P3-01/P3-03/P3-11 and ordinary stack start/doctor/smoke.
The source-bound phase checkpoint is retained under
.local/validation/p2-send-policy-p3-action-races. It preserves the closed prior
checkpoint and exact source/archive/report identities. Independent product,
tooling, installed-consumer and integration/evidence reviews bound the results.

### Failures and corrections

All failed/diagnostic/prepared-only observations remain distinct.

P2:

- P2 first failed because a counter-drift test probed an already accepted fact
  instead of a new reservation. The corrected source and strengthened proofs
  remain separately retained.
- Additional review required real global-capacity exhaustion, original ordinary
  fresh-process replay and revocation before retry.
- A later evidence-only fix separated directly reproducible SQL snapshot hashing
  from the unchanged JavaScript provider-wire digest. Earlier row-equality proof
  remains valid within its exact scope.
- Earlier installed npm consumers are retained separately from the final
  current-README/public-reconciliation consumer.

P3:

- P3's first fixture overwrote a required public work marker. The fix preserves
  the authority marker and keeps fixture ownership separate.
- Further fixture corrections refresh owner activity snapshots, preserve original
  cancellation receipts, catch invalid confirmation at its public constructor and
  separate the evidence-inventory digest from the bounded P3 wire codec.
- The observed digest failure did not preserve original byte/node totals, so it is
  not attributed to one specific wire limit.
- Normal run seven passed the preceding scope. Normal eight/diagnostic nine exposed
  the strengthened owner-proof codec mismatch. The selected final normal ten
  passed.
- Diagnostics always fail qualification. Initial normal failure captures were not
  available under their frozen policy; later bounded diagnostic reproductions are
  labelled separately.
- No P1/P3 production guard or timeout was weakened.

### Evidence limits

- The retained P3 inventory digest is produced after independent source
  assertions. The raw inventory is not retained for later independent digest
  recomputation. Its two SQL graphs and compact owner counts are retained and
  directly reviewed.
- The installed P3 gate exercises inspect_accepted. run_completion is strictly
  typed and imported, not claimed executed by this gate.
- Quiescent backup cuts and owner joins are not an atomic cross-service snapshot
  or production-capacity result.

### Next work

Next:

| Task | Next behavior |
| --- | --- |
| P2-I15 | Native voice/text continuity |
| P3-I13 | Broader deadline/cancellation behavior |

P2-I16 to P2-I22 and P3-I14 to P3-I24 retain their planned media,
integration, load/UI, document capability, full packaging/release and
model-comparison gates. P1's historical selected provider-real qualification is
reused only for unchanged payloads. No paid inference, external provider/carrier,
native P2/P3 media, publication or remote CI was executed here.
