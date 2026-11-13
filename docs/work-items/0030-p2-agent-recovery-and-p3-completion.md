# Agent recovery and delivered guarded results

Status: Completed
Last reviewed: 11 November 2026

## Behavior and scope

Implement P2-I09's owned agent-process failure/replay boundary and P3-I07B's first
durable useful-result delivery plus explicitly confirmed fake action. Reuse the
completed gateway/issued-execution checkpoint in work item 0029. P1 remains the
only execution and case-intent authority. Delivery receipt ownership is separate
from execution; specialists never receive booking mutation or notification rights.
All complete product, media, workload and integrated release rows keep their own
gates. The maintained checkout remains Downloads/repositories/livekit-agent-ecosystem;
the desktop workspace is an older independent checkout.

| Criterion | Given | When | Safety | Useful progress | Required evidence |
| --- | --- | --- | --- | --- | --- |
| P2-I09, P2-04 contribution | A committed scoped message and original case/operation identity | Independently owned agent process is terminated while preparing a decision | No prepared plan or logical business acceptance is fabricated; slots remain owned until actual process/pipe cleanup | A fresh eligible attempt reprocesses original input, records repeated processing and produces one logical operation acceptance | Real agent processes, PostgreSQL claims, controlled barriers and independent operation truth |
| Process isolation | Trusted executable/module configuration and finite allowed scopes | Normal, malformed, excessive, slow or aborted worker output | No shell/input-selected command, inherited provider/PG selector, cross-scope response or unbounded output/task | Normal valid decisions progress and subsequent work succeeds after failure/cleanup | Real child/group lifecycle, framing/identity/byte/time/cap tests |
| Durable delivery | A strict useful persisted result and trusted receiver/recipient binding | Delivery is planned, accepted, loses acknowledgement or is replayed | Original target/result/body/identity cannot be replaced; acceptance is not human acknowledgement | Original receipt is found after process lifetime and usable result remains delivered without another logical notification | Explicit versioned P1 profile, independent persistent cooperating receiver, normal/lost-ACK/fresh-read tests |
| Guarded action | An eligible stored result, mapped current case and independent exact human confirmation | Authorize or replay with cancellation, expiry, revision change or ambiguity | Result eligibility and current exact case intent validate in one P1 transaction; stale/cancelled/expired results and changed confirmation cannot create an intent | Current B plus its exact confirmation commits one intent and one independently observed fake supplier change | Actual PostgreSQL work/case stores, deterministic lock/barrier schedules and persisted fake effect truth |
| Resource/diagnostic ownership | Held I/O, canceled waiters and failing telemetry | Timeout, close or logging failure | Actual resources remain owned until settlement and committed truth is preserved; diagnostics contain fixed safe values | Admitted eligible work/reconciliation continues and owned cleanup completes | Unit, process/socket and actual database gates with zero required skips |

## Interfaces and ownership

P2 adds an explicit public owned-process agent adapter and worker-side framing
helper around its existing narrow scripted decision port. Runtime input cannot
select an executable, process ID or worker scope. The adapter neither owns durable
acceptance nor retries; PostgreSQL and ChannelDispatcher retain those concerns.
There is no booking or native media implementation in this adapter.

P1 adds only necessary public case commands/reads around its existing v4 authority
and an explicit v2-to-v3 upgrade for the optional work profile's immutable delivery
and guarded-action records. Preserve original v1/v2 work APIs and every accepted
input/result/command. No booking-v4 or SQLite migration, runtime DDL or automatic
baseline refresh is permitted. New public models/ports must be frozen before code
uses them, with finite retention caps, immutable target/result binding and safe
reconciliation of uncertain commits.

The guarded action path uses one consistent lock order across the selected
booking and work authorities, requires the same supported PostgreSQL target and
validates both credential bindings. Sample authoritative time after required locks.
Generic P1 result guards bind work/attempt/result digest; P3 validates the strict
capability envelope, evidence and exact mapped case/revision before requesting
action. P1 does not import P3 schemas or derive confirmation from model output.
The original action receipt and case intent commit together and survive later
cancellation/expiry. No external receiver/supplier call occurs inside that transaction.

P3 adds bounded explicit completion methods through declared public interfaces.
Delivery intent, possible delivery, receiver acceptance, current applicability,
exact human confirmation and committed action remain different observations.
There is no second execution ledger, autonomous retry scheduler, invented current
case permission or delivered-to-human claim. A persisted cooperating receiver may
own receipt deduplication, but cannot own execution or booking state.

## Failure cases and validation

| Gate | Required assertions | Setup and bounds | Completion rule |
| --- | --- | --- | --- |
| G-READY/CONTRACT | Public API, typed ownership, wire and version/lock-order review | Frozen existing Python/Node/SDK/dependencies; no upgrade | Agreed APIs, current positive/negative fixtures and independent review |
| G-FAST | Unit/process framing/lifetime/semantic guards, lint/type/format and boundary checks | Offline, no provider credentials | Full maintained suites; zero skips, missing sources or zero-case runners |
| G-DURABLE P2 | Actual mid-agent death, persisted claim/replay, visible repeated processing and one logical acceptance | Owned processes, isolated marked schemas, finite capture/deadlines | New focused and complete previous P2 lanes pass with cleanup |
| G-DURABLE P1 | Explicit upgrade/repeat/interruption, preserved bytes/identities, roles/drift, caps, scoped replay/target conflict and uncertain commit | Restricted owner/runtime roles and actual PostgreSQL | Focused new-profile and full P1 regression lanes pass |
| G-COMPLETION/ACTION | Actual issued HTTP result, receiver acceptance/reconciliation and exact v4 case commitment/effect; stale A versus current B; work cancel/expiry before guarded commit | Synthetic data, independent receiver/supplier persistence and controlled processes/barriers | No stale/unauthorized effect and useful current confirmed action succeeds |
| G-PACKAGE | Public built artifact imports/types and normal behavior outside checkout | Fresh isolated wheel/npm installs with declared dependencies | No private storage imports, workspace injection or startup-on-import |
| Regression | Existing APIs, previous actual lanes, rebuilt default Docker transport/persistence | Preserve application volumes and original M1 identity | No provider/model/media requalification implied |
| G-MEDIA/RELEASE | Separate later work | No real provider/carrier or native/browser audio change in this slice | Complete charter/release rows remain pending |

Bound queues, child output, response bytes, deadlines, attempts, retention and
shutdown observations before measuring. Known external results survive caller
cancellation; a timeout cannot fabricate prevention or rollback. Include fixed
safe logs/error codes, finite process-local metrics, throwing-observer progression
and redaction/sentinel tests. Retain original failures and distinguish actual
stores/processes from synthetic case/agent adapters. Correctness durations are not
throughput, latency-percentile or production-capacity measurements.

## Results and handoff

### Implemented behavior

P2-I09 adds the public ./agent-process adapter and worker-side framed protocol.
Trusted configuration chooses the executable/module and finite scope bindings;
message/model input cannot select a command or PID. Each invocation owns a POSIX
process group, bounded pipes, deadline and admission slot through actual cleanup.
The actual recovery fixture leaves the gateway alive, kills its independently
owned scripted agent, waits for DB-observed claim expiry and repeats the same
input/case/operation. Two recorded attempts produce one logical cooperating
operation acceptance. Logical lease expiry cannot stop physical model computation;
this trusted-process adapter is not a security sandbox for arbitrary executables.

P1 work-profile v3 explicitly upgrades validated v2 state without rewriting
accepted input, issued grants, results or cancellations. Four immutable bounded
record sets own delivery intent, possible send, receiver receipt and guarded action
receipt. They inherit the existing per-work retention cap. Serving code performs
no DDL. v1/v2 callers and explicit older upgrades remain compatible on supported
versions. A public bounded SQLite result receiver retains immutable receipt truth
and verifies scope, recipient, receiver identity and original result bytes.

P3-I07B adds DelegationDeliveryClient and DelegationAuthorizer with declared P1
public ports. Deep snapshots precede awaits. Only a newly persisted delivery begin
may accept at the receiver; an existing possible send performs lookup only. Reliable
absence remains unknown because a paused sender may still act. Receiver acceptance
proves accepted bytes, independently of playback or human acknowledgement. Known
late receipts survive cancellation and deadline without changing their target.

An independent exact human Confirmation is required for action. Trusted startup
binds the work credential and case actor/scope/schema/task. On the same supported
PostgreSQL target, P1 locks booking admission, work admission and case/control,
checks DB time after the required locks, verifies current issued-result eligibility
and exact current case confirmation, and commits case intent plus action receipt
in one transaction. A fresh result cannot attach to an independently committed
prior intent. Original receipt replay preserves known facts after cancellation or
expiry. The existing leased worker performs the fake supplier call outside SQL;
the specialist has no mutation or notification privilege. Case/action reads remain
credential-bound, and finite metrics/safe fixed logs cannot change committed truth.

The test receiver is an in-process async/threaded public port over separate
persistent SQLite, rather than a network receiver service. Its fault schedule kills
the caller after the receiver commit, then a fresh caller reopens and finds the
original receipt. Gate confirmations are separately supplied synthetic operator
input; no real human gesture is measured. The combined 13-case gate proves replay
after later work cancellation; actual expiry rejection is covered by focused P1
PostgreSQL cases, without attributing timed expiry replay to that combined gate.

### Observed gates

| Gate | Observed result | Qualification boundary |
| --- | --- | --- |
| Full offline Python | make check passed 1,310 tests: root 1,132; P1 42; P2 14; P3 122; zero skips/violations | Ruff passed; broad mypy 120 and strict mypy 68 maintained source files |
| Python formatting | 281 files passed | No blanket check suppression added |
| Frontend/examples | 600 tests: console 326, P2 196, specialist 78; formatting/type/build passed | Existing console bundle-size advisory remains; no new UI/media qualification |
| Full P1 PostgreSQL | 315 tests, zero errors/failures/skips; 287.016 seconds | Includes 11 delivery-profile and 14 guarded-action cases, plus all previous lanes |
| Guarded-action focused lane | All 14 actual cases passed | Lock-order cancellation races, current/stale/expired/forged results, rollback/lost ACK, caps, actor rebinding, throwing logs and prior-intent attribution; included in 315 |
| P2 agent recovery | One focused case, one verified owned worker SIGKILL; 1.610 seconds; cleanup complete | Live gateway, actual PG expiry/claims, synthetic scripted decisions and independently persisted cooperating operation |
| P2 complete selected lane | All 23 cases passed; four owned forced exits; 9.675 seconds; cleanup complete | The new agent subset is included, not additional unique cases |
| P3 completion/action | All 13 cases passed; one receiver-commit SIGKILL; 14.938 seconds; cleanup complete | Actual case v4/work v3, Python/TypeScript HTTP, persistent receiver and fake supplier; no real model/carrier |
| Independent P3 reconciliation | Four work/attempt/result records, two cancellations, two delivery intent/possible/receipt sets, one action/case intent and one fake supplier change; four evaluator invocations | Owner verifies both scope fields, issued/result/receiver identity, exact confirmation/quote and supplier booking revision; stale A/current B uses actual case revisions 2/4 |
| Previous P3 execution | All 12 cases passed; 15.986 seconds; cleanup complete | Revalidates prior v2 issued HTTP behavior, including result-commit process death |
| Previous P3 acceptance | All ten cases passed; 10.884 seconds; cleanup complete | Revalidates v1 acceptance and independent socket probes |
| P1 built artifacts | 74 payload files agree across wheel/source/rebuilt wheel; 18 commands and three isolated environments passed | Legacy installed consumers plus new public modules retained |
| P3 built artifacts | 15 payload files agree across wheel/source/rebuilt wheel; three offline build commands passed | Frozen declared dependencies; no workspace injection |
| P2 installed artifact | Fresh offline npm consumer, strict NodeNext without @types/pg, actual worker/gateway/PG and two runtime processes passed | Replay worker starts [1, 0], original receipt/operation/external receipt preserved, owned schema/process/socket/temp cleanup complete |
| Installed P1/P3 completion | Fresh offline wheels/npm, strict public mypy, consistency across 74 installed packages and all 16 bounded stages passed in 30.845 seconds | Installed public APIs and worker_cli inquiry/mutation; one policy evaluation/result/delivery/action/fake effect, independent owner reconciliation and fresh-process replay; all owned schemas/processes/sockets/scratch cleaned |
| Installed authority identity | Owner independently linked the persisted runner owner to its issued attempt and verified zero case effects before separately supplied exact quote/revision-2 confirmation | Fresh replay preserved result/receipt/action IDs with zero further policy or receiver invocation; source bootstrap was explicit owner-only test tooling |
| Separate P3 public artifact | 41 Python public exports, strict Python Protocol/Node declarations, cross-language request/result parity and installed loopback HTTP example passed; 17 npm payloads verified | Ten stages, 24.616 seconds, owned temporary cleanup; no database used by this separate checker |
| Rebuilt default Docker | Eight readiness/auth/idempotency/conflict/RTC text/audio checks passed; ten audio frames observed | Original M1 task and persistent volumes preserved; transport only, no new model/media qualification |
| Documentation/harness | 103 documents and pure scoped P1/P2/P3 boundary/contract checks passed with zero violations | Scoped checks request no duplicate offline tests; all 34 full product rows remain planned/unregistered |
| Diagrams | All 13 changed root/project diagrams parsed; malformed negative rejected | Syntax qualification only |

### Review corrections and retained failures

Independent automated reviews covered delivery/profile preservation, case/work
lock order and current-time guards, P2 process lifetime/late callback ownership,
P3 immutable snapshots and read-only reconciliation, and owner/runtime separation
and independent proof in actual gates. Corrections retain ownership after failed
process-group cleanup, prevent late events from fabricating cleanup, sample DB time
after case locks, reject retroactive prior-intent attribution, and independently
link delivery/action records to original result, confirmation, quote and fake effect.
No human sign-off is claimed.

The first focused P1 delivery runner omitted its test-only harness path under -I;
it failed before SQL. A later FileBarrier path used the unresolved /var alias;
the fixture now resolves its owned /private/var directory. Early focused lint/type/
format findings are retained with their original captures. P2's first actual gate
reported invalid_report after a mixed source/built opaque adapter and diagnostic
output in the JSON stream; its private original capture was removed by the runner.
The retained raw-named file is a later diagnostic reproduction, not that original
capture. P2's first installed consumer used the wrong temporary path and failed
before runtime; the corrected fresh run qualifies. These failures remain separate
from passing reports. Source-fixture timing and gate evidence were corrected
without weakening business assertions, bounds or cleanup requirements.

The first installed completion fixture expected a missing-explicit-consent error
after entering P3, but P1 correctly rejected that Confirmation during construction.
Its failed report and complete schema/process/scratch cleanup are retained; the
fixture now accepts that earlier public rejection. A second fixture run incorrectly
expected DelegationRun.recorded on replay: that field describes newly recorded
completion in the current call. Replay correctly has recorded=None while its
persisted view.execution.result retains the original result. Both failed fixtures
completed their owned cleanup and caused no product change. The separate P3 artifact checker
also corrected three tooling assumptions: npm may reorder manifest JSON keys
while preserving exact parsed semantics; the pinned Corepack executable path must
exist; and the installed HTTP example emits three verified safe NDJSON events
before its final JSON report. Exact source/declaration/example bytes, public typing
and business assertions remain required.

### Commands, evidence and next tasks

From the maintained repository with frozen tools and explicit local restricted-role
PostgreSQL setup:

```sh
make p2-agent-check
make p3-completion-check
make p2-postgres-check
make postgres-check
make p3-execution-check
make p3-coordinator-check
make check
make frontend-check
make format-check
```

The fresh phase evidence directory is
.local/validation/p2-agent-p3-completion/be5a881c129944619586eb512ece2e83.
Its final manifest binds passing reports, archives, outside-checkout consumers,
safe raw failures, review provenance and current source hashes. Prior closed phase
evidence is preserved. Existing booking/inquiry, services and console sources are
unchanged; only three existing optional work-profile modules changed, alongside
new modules. Dependency locks remain unchanged. Historical P1 selected-provider
qualification remains source-bound; no provider credentials or paid inference were
used by this phase.

All selected gates passed. P2-I09 and P3-I07B complete this bounded phase; I07A
plus I07B complete the P3-I07 task. All 34 complete P2/P3 charter rows
remain planned/unregistered. Next are P2-I10 revision-aware competing-channel
routing and P3-I08 concurrent replay/conflict plus the first fully asserted runners.
Resumable projections/delivery recovery, native media, default P2/P3 Docker/UI
composition, broader workloads and integrated release retain their later gates.
Correctness-run durations are not production latency/throughput measurements.
