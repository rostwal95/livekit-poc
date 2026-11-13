# Explicit send uncertainty policy and protected action races

Status: Completed
Last reviewed: 11 November 2026

## Behavior and scope

Implement P2-I14 and validate P3-I12 after the
[completed callback/applicability phase](0034-callback-evidence-and-applicability-refresh.md).
The [P2 task plan](../implementation/p2-channel-continuity.md),
[P3 task plan](../implementation/p3-delegation-reliability.md) and their charters
remain authoritative. This slice contributes to P2-11 and P3 protected-action
requirements; task completion does not register an entire charter row.

P2 adds an explicit trusted reconciliation/retry policy for immutable outbound
operations, including a real local fake provider that observes a request and loses
its response. Ordinary possible sends remain unknown and cannot be resent. A
separate cooperating idempotent fake capability may safely reuse its original
provider key through a new explicitly authorized local attempt. P3 exercises the
existing public guarded-action and worker interfaces under real revision,
cancellation and process-loss schedules. P1 remains the sole work/case/action
and effect authority. Preserve its 77 runtime payloads, schema and public APIs;
preserve P3's 30 runtime payloads unless an evidenced defect requires review.

Keep dependency locks, image pins, provider configuration and ordinary M1 state.
Native voice/text/UI composition, real carriers, paid inference, automatic booking
completion handoff, automatic retry, broader deadline/recovery schedules and full
release remain separate phases. No remote CI or publication is required.

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

Keep ChannelOutbox.send's ordinary contract and callback v1 unchanged. Add an
explicit IdempotentFakeSmsClient with trusted idempotent_fake_sms_v1 capability,
bounded fixed loopback send/lookup endpoints and stable immutable ProviderOperation.
Canonical operation bytes bind trusted provider scope/key, original logical
recipient/account/case/conversation/outbound/response and frozen sender/address/body.
They exclude local attempt UUID and observational association/route epochs. Each
new local invocation retains its own attempt UUID and existing attempt-sensitive
request digest. A callback still requires exact attempt, operation key and request
digest; the stable key alone grants no association or recipient access.

The send wire carries the frozen operation once plus attempt identity/digest and
route/association observations. Validate and reconstruct the full canonical
SendRequest. Lookup carries only the configured provider scope, stable operation
key and operation digest after local full-operation validation. Bound request
bytes to 32768, command receipts to 4096 and lookup observations to 2048.

Expose reconcile(controllerToken, command), retry(controllerToken, command),
recoveryCommand(accountToken, commandId) and inspectRecovery(accountToken,
outboundId) through the server-only outbox surface. Recovery-controller grants
are separately trusted, scope-bound and distinct from account/publisher access.
No caller body/model chooses credentials, provider capability, recipient or policy.
Stable equal command replay returns its first semantic receipt/observation before
new reads/caps and performs zero provider I/O. Changed target/expected attempt
conflicts. A new observation or retry requires a new explicit command identity.

Ordinary ambiguous sends remain held. Lookup known/absent/unavailable is separate
as-of evidence and never overwrites send_results. Known acceptance holds any new
retry. A provider-reported definitive nonacceptance must be durable terminal truth
for that stable key: an original delayed call cannot later be accepted under the
cooperating fake contract. A merely absent/not-yet-observed operation remains
unknown and cannot authorize a new key. Absence or unavailability remains unknown; only a fresh trusted command,
configured idempotent-and-lookup capability, current original-recipient permission
and no callback veto may reserve a new attempt. Contradictory message identities
remain conflicted, never erase facts or open sends. Historical lookup may record
truth after revocation but cannot authorize retry. Current route observations may
reauthorize the same original address; no new address retargets the frozen operation.

Upgrade inbox v4 to v5 explicitly under owner maintenance/quiescence. Add only
send_policy_settings, send_operations, send_recovery_commands and
send_recovery_observations. Put the bounded mutable recovery_count in the new
settings row with runtime column-only UPDATE permission; preserve old admission
row shapes. Relax the old send_attempts provider-key uniqueness and add its
composite tenant/account/outbound/operation FK. Operation keys remain unique in
send_operations, which fixes provider namespace/capability/canonical digest and
first-attempt anchor. The first-attempt FK is deferred so both immutable records
commit together before any call. Validate anchor, request/digest/provider namespace
on reservation/read. An additional immutable admission proof and digest in the
new operation row preserve the exact evidence used for a later new-key operation:
first-operation identity, or its immediate predecessor attempt/key and one exact
immutable definitive-nonacceptance send-result/lookup-observation digest. Cap this
canonical proof at 4096 bytes. History validates this committed proof, independently
of later aggregate evidence; late contradictions cannot erase an already admitted
operation or authorize another call. A separate fresh admission check examines
at most five retained operations for the logical outbound: known acceptance or
conflict on an earlier operation vetoes any new key or retry call. Historical
reads still return the originally admitted operation and its immutable proof.
Runtime performs no DDL, deletion or immutable-row update.

Adopt old attempts as separate ordinary operations in validated pages of 64;
never retrofit idempotency through changed constructor configuration. Preserve
old request/result/callback/receipt bytes. Bound adoption by existing retained
reply/attempt caps; malformed rows or drift roll back the entire owner upgrade.
Old upgrade functions validate the current version without downgrading it.

Retain existing five attempts per reply, two network calls (maximum four), four
SQL calls over two connections, waiter default two seconds/maximum five and close
two seconds. Recovery commands default to 10000 total/eight per operation,
maximum 100000/32; one immutable observation per command. Inspect returns at most
five compact operations. Retention is the profile lifetime; no TTL or identity
reuse/capacity reclamation. Actual I/O owns its slot after caller abandonment.

P2 owns its contracts/client/policy/store/migrations, public exports, project
unit/actual tests, p2_send_policy_check.py, wrapper negatives and three project
guides. Shared tooling owns Makefile and foundation/documentation discovery.

### P3 existing authority under explicit schedules

Use unchanged public P1 ActionClient, case-control, worker and supplier ports and
unchanged public P3 completion facades/example. Test wrappers only schedule their
existing trusted test hooks; product code never imports private P1 stores. P3
owns pg_action_race_cases.py, test_action_schedules.py, the explicit
p3_action_case_fixture.py helper and five project guides. Shared tooling owns
p3_action_races_check.py, root protocol negatives and integration guides.

A validates through facade preflight before the owner fixture holds the isolated
case admission lock. Prewarm independent B and observer/locker children, queue
B-then-A or A-then-B, and observe actual pg_blocking_pids two-waiter chains. Release
promptly without changing P1's 1000 ms SQL lock timeout. Do not start interpreters
while writers wait or substitute fortunate sleeps for an observed graph.

B-first commits revision two to three before A reaches its protected guard;
A may reject at revision three before B's separate three-to-four edit commits.
The later current B at revision four receives an independent exact confirmation
and progresses. Do not claim that the complete two-edit revision sequence was
committed before A's atomic check. Stale A commits zero intent/effect. A-first commits
its intent and causes B's public revise to reject with intent_committed. Once
A's intent commits, revision cannot succeed on that case. Cancellation before
intent returns cancelled_before_commit; before dispatch returns
cancelled_before_dispatch with a retained CANCELLED effect and zero supplier call.
After-claim cancellation may make the resumed old worker raise TransitionConflict;
record that safe existing conflict and inspect terminal facts rather than changing
the worker. After dispatch reservation, requested_best_effort cannot fence an
admitted held supplier call. Known supplier success/result/receipt survives later
cancellation/deadline; terminal cancellation is already_terminal.

Use a fresh independent supplier/case/inquiry/quote for each schedule: applying
one quote advances supplier revision and cannot be hidden by reused stale setup.
Each individual work schedule respects the unchanged maximum 60-second work
horizon. Join exact source/work/attempt/result digest through confirmation,
intent/effect, supplier receipt and applied_calls; counts alone cannot qualify it.
Receiver acceptance remains separate from supplier/business completion and human ACK.

## Failure cases and validation

| Gate | Applicable and why | Exact assertions | Prerequisite/resource/time bound | Expected evidence |
| --- | --- | --- | --- | --- |
| G-READY | New P2 durable policy and P3 schedules | Freeze four-table/operation/controller/unknown contracts and closed actual child inventories before edits | Prior phase34 checkpoint and current source equality | This work item, machine contract and plan |
| G-FAST/OBS | New public types, async policy and tooling | Strict primitive/canonical/scope/conflict/cap, snapshot mutation, cancellation, late cleanup, secret sentinels, telemetry outage and useful progress | Offline frozen dependencies, no providers/private CA | Full Python/frontend, lint/types/format and targeted negatives |
| G-DURABLE P2 | New owner v5 and explicit uncertainty | Populated v4-to-v5, repeat/old upgrades, SQL-cancel rollback, populated pg_dump/restore, real lost responses, lookup/retry races, two owned PID kills and independent provider ledger | Role-separated actual PostgreSQL and owned loopback HTTP, fixed finite child budgets | Thirty frozen named assertions with complete cleanup |
| G-DURABLE P3 | Existing atomic action/external effect boundary | Both revision lock orders, exact valid B, pre/post reservation cancellation, pre/post action commit and supplier-commit process loss, no reapply | 180 seconds total/15 cleanup; at most 32 child calls; 128 KiB aggregate/2 KiB per stream/32 KiB report | Sixteen assertions, two actual SQL graphs, three owned PID kills and exact joins |
| G-PACKAGE | Reusable public policy and existing action composition | Fresh offline npm/wheel/sdist/rebuilt installs, strict public imports/types, actual policy/action fixture outside checkout and original command replay | Frozen source and bounded isolated consumer resources | Archive/source parity, exact example/fixture hashes, actual cleanup |
| Regression | Preserve old profiles and qualified behavior | P2 callbacks/outbox/routing/confirmation/recovery; P3 coordinator/execution/projection/processing/applicability and registered P3-01/03/11 | Exclusive serialized actual PostgreSQL lanes | Fresh exact selected reports; no skip/missing/timeout pass |
| Runtime/docs | Reproducible local handoff | Full source/dependency preservation, Docker readiness/text/audio, original M1, standardized guides and all Mermaid syntax | No reset or providers | Measured logs, independent review and sealed checkpoint |
| Full project release | Broader media/load/recovery still pending | Preserve catalog registrations and remaining normative rows | Separate future gates | No blanket P2/P3/ecosystem pass |

P2 freezes 30 assertions: populated upgrade preservation; repeat/old upgrades and
limits; interrupted DDL rollback; populated v5 dump/restore with original replay;
runtime privilege/catalog/counter drift; controller/account/publisher scope;
ordinary/idempotent normal success; definite failure plus separate useful new
operation; ordinary provider-observed lost response; fresh-process original unknown
after route change; ordinary explicit retry hold; idempotent lost response; exact
known lookup without send; absent/unavailable lookup without automatic retry;
explicit new same-operation retry with distinct attempt/two HTTP requests/one
fake acceptance; equal command replay without I/O; changed command conflict;
concurrent retry reservation; stale expected attempt/attempt cap; revoke/suppression/
route no retarget; reservation-first frozen bytes after revoke; any-prior-callback
veto first; retry-first late callback; callback exact old/new attempt with reused
key; wrong operation/digest/key/message conflict and late evidence preserving
already-admitted operation history; global/per-operation command cap
and replay; owned post-provider-observation kill/fresh replay; owned post-reservation
pre-wire kill/safe progress; actual ignored-timeout I/O lifetime/diagnostics; and
independent SQL/provider reconciliation. SQL cancellation is not a process kill.

P3 freezes 16 assertions: B-first stale A reject; independently confirmed B effect;
A-first B revise rejection; committed boundary/original receipt; pre-intent cancel;
post-intent pre-dispatch cancel; after-claim cancel; post-reservation cancel and
original apply; known supplier success after late cancel/deadline; precommit kill
rollback/progress; postcommit kill original replay; supplier-commit kill lookup
without reapply; changed confirmation/scope conflict; caller timeout/cancel actual
I/O ownership and cleanup; receiver-versus-business/ACK distinction; and exact
identity joins. The closed mode/env manifest is recorded before measurement.

Use existing fixed public error/outcome enums. Emit actual bounded controller,
lookup, retry, hold/veto, unknown-ACK and retained-active counters with explicit
units; no account/recipient/address/key/work/event/body metric labels. Log fixed
safe operation/outcome/error fields; never raw headers, credentials, exception
text or bodies. Contain observer failure. Translate boundary errors once, propagate
cancellation, retain actual calls after waiter timeout, and require later progress.

New Python fixtures/wrappers/helpers enter lint/format/strict typing/test discovery
with their source. Preserve first failures and exact finite owner/runtime child
environments; no ambient provider/proxy/Python-path/database selectors. Create
owned UUID schemas/files/barriers, terminate only owned children and fail incomplete
cleanup. Freeze fixture/mode/protocol names before normal qualification.

Commands from the maintained repository include make check, make frontend-check,
make format-check, make p2-send-policy-check and make p3-action-races-check plus
the explicit prior service lanes and harness run P3-01/P3-03/P3-11. New target
commands become runnable only when their implementations are present. Required
unavailable setup, missing assertions, skips, zero tests and timeouts cannot pass.

## Results and handoff

P2-I14 and P3-I12 completed their selected local implementation/validation gates.
No full P2/P3 charter row was registered. P1 retains case/work/action/effect
ownership; its 77 runtime payloads, packaged README, schema and public API are
unchanged. P3's 30 runtime payloads and schema are unchanged. Dependency locks and
ordinary local state are preserved.

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

The final global Python/type results come from one complete make-check rerun after
the evidence-hash helper regression was added; its type excerpt is not another
execution. The preceding 1,659-test run remains retained. Frontend and formatting
checks are separate measured runs. Correctness-gate durations do not establish
production latency, throughput, provider capacity or real-model/media quality.

All failed/diagnostic/prepared-only observations remain distinct. P2 first failed
because a counter-drift test probed an already accepted fact instead of a new
reservation; the corrected source and strengthened proofs remain separately
retained. Additional review required real global-capacity exhaustion, original
ordinary fresh-process replay and revocation before retry. A later evidence-only
fix separated directly reproducible SQL snapshot hashing from the unchanged
JavaScript provider-wire digest. Earlier row-equality proof remains valid within
its exact scope. Earlier installed npm consumers are retained separately from the
final current-README/public-reconciliation consumer.

P3's first fixture overwrote a required public work marker; the fix preserves the
authority marker and keeps fixture ownership separate. Further fixture corrections
refresh owner activity snapshots, preserve original cancellation receipts, catch
invalid confirmation at its public constructor and separate the evidence-inventory
digest from the bounded P3 wire codec. The observed digest failure did not preserve
original byte/node totals, so it is not attributed to one specific wire limit.
Normal run seven passed the preceding scope; normal eight/diagnostic nine exposed
the strengthened owner-proof codec mismatch; selected final normal ten passed.
Diagnostics always fail qualification. Initial normal failure captures were not
available under their frozen policy; later bounded diagnostic reproductions are
labelled separately. No P1/P3 production guard or timeout was weakened.

The retained P3 inventory digest is produced after independent source assertions;
the raw inventory is not retained for later independent digest recomputation.
Its two SQL graphs and compact owner counts are retained and directly reviewed.
The installed P3 gate exercises inspect_accepted; run_completion is strictly typed
and imported, not claimed executed by this gate. Quiescent backup cuts and owner
joins are not an atomic cross-service snapshot or production-capacity result.

Commands include make check, make frontend-check, make format-check,
make p2-send-policy-check, make p3-action-races-check, the selected old service
lanes, registered lab P3-01/P3-03/P3-11 and ordinary stack start/doctor/smoke.
The source-bound phase checkpoint is retained under
.local/validation/p2-send-policy-p3-action-races; it preserves the closed prior
checkpoint and exact source/archive/report identities. Independent product,
tooling, installed-consumer and integration/evidence reviews bound the results.

Next: P2-I15 native voice/text continuity and P3-I13 broader deadline/cancellation
behavior. P2-I16–I22 and P3-I14–I24 retain their planned media, integration,
load/UI, document capability, full packaging/release and model-comparison gates.
P1's historical selected provider-real qualification is reused only for unchanged
payloads; no paid inference, external provider/carrier, native P2/P3 media,
publication or remote CI was executed here.
