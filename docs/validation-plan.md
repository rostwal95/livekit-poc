# Portfolio validation and release evidence

Status: Active
Last reviewed: 13 November 2026

The current user-approved delivery is a fully local POC. GitHub publishing and
remote CI execution are out of scope; existing CI configuration is optional
reference material. Execute the local checks and actual store/process/container/
artifact/browser/inference gates below. Hosted execution is not required before
finishing P1 or starting P2 under this delivery scope.

Every project has a finite V1 scope in [portfolio-scope.md](portfolio-scope.md).
Use the acceptance IDs in the three project charters as the traceability unit.
The harness discovers those IDs and records executable evidence as scenarios are
implemented. A documented requirement, mocked fixture or green unrelated test is
not evidence that a product scenario works.

## Test lanes

| Lane | Run when | Required evidence |
| --- | --- | --- |
| Baseline | Every change to the existing starter or harness | Existing intake tests; harness validation and runner tests |
| Deterministic correctness | Every affected implementation slice | Exact invariants, schema errors, replay/conflict, transitions, fake-clock expiry and bounded cancellation |
| Persistence and processes | Changes to storage, worker or delivery behavior | Actual database, independent processes, failpoint-controlled termination and recovery |
| Cross-language contracts | Changes to Python/TypeScript messages | Shared versioned fixtures accepted/rejected consistently, including unknown version and scope errors |
| Local media | Changes to agent, browser, modality or reconnect behavior | Actual self-hosted LiveKit, browser/SDK observations and audio fixtures; no external AI needed |
| Live inference | Before claims about voice/vision/model behavior and portfolio release | Selected real-model runs, checked task outcomes, configuration, costs and artifacts |
| Load and regressions | First baseline, milestone releases or performance changes | Bounded steady/burst/saturation tests, raw samples and comparison to recorded baseline |

Keep default local checks independent of provider credentials. Missing mandatory
setup or scenarios makes a gate incomplete; it cannot silently become a skip or
pass. Optional live lanes report not run when credentials are unavailable and
cannot support live-quality claims. Cloud simulations are optional and separate.

## Historical native/deadline qualification

The [completed handoff](work-items/0036-native-input-and-deadline-cancellation.md)
records these independent boundaries. Selected P2-I15/I16 and P3-I13 implementation,
artifact, compatibility and final shared gates passed, including the affected media
rerun. These selected tasks are complete; full charter release remains separate:

| Boundary | Evidence at the completed native/deadline checkpoint | Qualification limit |
| --- | --- | --- |
| P2 native code | Fifty-five Python, 530 P2 TypeScript, sixty-five browser-policy and forty-five wrapper tests passed; one separate actual local HTTP proxy-routing regression passed | Final shared checks passed separately; these focused counts do not establish full charter release |
| P2 native actual gate | Final current six-group run passed in 31.063 seconds with 24 children, one owned kill and one SQL graph; actual browser text/WAV committed voice, two SDK replies, returned text/audio, v6 restore and complete cleanup | Affected UI-hint media rerun passed; SDK/storage assertions are separate from the six browser groups, and microphone/general inference quality remains unqualified |
| P2 installed Python | Selected isolated default/optional-native wheel, sdist and rebuilt wheel retain six runtime payloads; eight exact source copies passed fifty-five local SDK/HTTP tests | No RTC, PostgreSQL, real provider or physical microphone claim; preserve the earlier fifty-one-test package as historical |
| P2 installed npm | Seventy-eight current dist/README payloads plus semantic manifest; actual public v6 PG/HTTP receipt-before-prepare and fresh-process original replay passed with prepare/operation calls one then zero | Synthetic read-only case and operation ports; no P1 booking, RTC/media or supplier/provider qualification |
| P3-I13 | Eighteen source and eighteen isolated installed assertions passed; existing execution/applicability/action races contribute forty-six compatibility assertions | Preserve exact reports, failures, direct safe proof files and unchanged runtime payloads; no full recovery/release claim |
| Compatibility | P2 old lanes passed 141 assertions plus one focused regression; P3 execution/applicability/action lanes passed forty-six assertions | Preserve exact selected reports; broader P3 recovery and complete product rows remain planned |
| Shared fast/frontend | 1,788 Python checks (P1 49, P2 55, P3 251, root 1,433), zero skips/violations, Ruff, broad/strict typing over 141/116 files and Python formatting over 355 files passed; 1,000 TypeScript tests (console 392, P2 530, P3 78), types, formatting and builds passed | This is the historical native/deadline checkpoint, not the current phase or a rerun of full P1 database/provider qualification |
| Shared/default stack | Eight ordinary stack checks and ten audio frames passed with original M1 preserved; native schema/room residuals were zero after cleanup | Inference disabled transport checks; existing provider/P1 qualification remains historical unless rerun |

The P2 owner-only v6 upgrade adds two native tables under quiescence without
serving DDL or deleting prior inbox/outbox/callback/recovery identity. New intake,
prepare and reservation use fresh database time after admission/binding locks;
retained facts and an already admitted possible call are distinct. Genuine final
recognition preserves the original turn before awaits; SDK-promoted interim text
cannot enter durable intake. Default SDK text and SessionHost consumption are
disabled, and StopResponse prevents automatic generation. Acceptance must precede
explicit dispatcher-owned SDK generation with one input/operation identity.

Retain actual sockets/readers/turn/intake/prepare/observer work until settlement.
Close failures cannot skip independent owners or manufacture zeros. Inspect the
eighteen native producer metrics, bounded safe logs, telemetry outages and six-key
generation observations separately from browser playback. No paid provider call,
physical microphone, general ASR/model quality or complete P2/P3 row follows from
scripted code tests. Catalog registrations remain 24 of 55.

## Engineering gates and acceptance authoring

These are engineering checkpoint names, not new acceptance/catalog IDs. Select
applicable gates in each implementation work item before coding. A gate with a
required unavailable prerequisite remains incomplete for that feature; independent
offline work can continue. The current commands do not yet implement every future
runner listed in the product plans.

| Gate | Applies when | Required assertions and evidence |
| --- | --- | --- |
| G-READY | Every substantial slice | Existing task/acceptance IDs, Given/When/Then criteria, authority/commitment boundary, migration/configuration impact, ordinary/fault schedule, test mode and resource/time budget reviewed |
| G-FAST | Every source/shared policy change | Existing full fast Python/static/docs/type checks and format check pass; affected TypeScript check/test/build passes; new source is included in discovery and typing |
| G-CONTRACT | Public API/schema/adapter changes | Producer/consumer positive and negative fixtures agree on versions, bytes/units, trusted scope, semantic replay/conflict and safe typed errors; no public source-internal imports |
| G-DURABLE | Persisted work/effects/delivery | Actual supported store, concurrent schedules, commit-response-loss, real child termination/restart, preserved identity, migration/restore and eventual useful progress; provider ledger independent of killed worker |
| G-OBS | New event/error/metric/export boundary | Inspect real emitted fields and counter/timing changes; sentinel secrets absent from response/log/trace; finite dimensions, no duplicate events/handlers or cross-context leakage; telemetry failure remains bounded |
| G-MEDIA | Agent/browser/modality/route lifecycle | Actual self-hosted browser/SDK path, track/sender correlation, permission-denial/cleanup, interruption and required playback/reconnect/return-route observations; emission/text simulation is insufficient |
| G-PACKAGE | New package consumer/release | Isolated built wheel/npm-pack installation, real minimal public example, declared dependencies/exports and advertised runtime support evidence; no repository path injection |
| G-RELEASE | Local or portfolio release | All applicable acceptance modes, independent API/failure review, measured workload budgets, supported-platform/setup/restart/shutdown and short success/failure demos; portfolio adds selected real-inference outcomes/configuration/cost |

The [Python guide](python-engineering.md) defines typing, task/resource ownership,
transaction, exception and diagnostic practices. Existing lint/type coverage is
scoped; new packages enter those checks as they are introduced. There is no
universal arbitrary line-coverage threshold. Inspect critical transitions and
failure paths; targeted mutation testing is useful only when a concrete invariant
justifies it, not as another framework prerequisite.

| Acceptance field | Required content |
| --- | --- |
| Traceability | Existing requirement and task IDs, owner and authoritative contract |
| Given | Trusted principal/scope, persisted state/revision, dependency capability and fixture seed |
| When | Public action and deterministic race/crash/failure point; actual process boundary where claimed |
| Then: safety | Exact store/effect/route state, forbidden side effects and stable identity/canonical payload |
| Then: liveness | Expected eligible work/result progresses; rejecting all work cannot pass |
| Diagnostics | Stable safe code, retry/reconciliation meaning, expected producer event/metric and redaction assertions |
| Execution | Offline/media/live lane, real versus fake adapters, timeout, resource limits, cleanup and artifact paths |
| Completion | Nonzero executed assertions, no required skip/timeout, inspected outcome and remaining partial assertions identified |

The P1-05 contract below has actual SQLite process evidence. The P2-03/P3-05
examples describe required future complete assertions; partial slice evidence or
wording alone never establishes acceptance:

- P1-05: given an independently persisted supplier inquiry and original accepted
  identity, kill the worker after supplier success but before local acknowledgement;
  a fresh worker reconciles that inquiry, preserves payload/effect identity,
  completes the eligible request and makes zero booking mutations.
- P2-03: given input committed before dispatch, kill/restart the gateway; the
  original receipt is inspectable, dispatch resumes under its original operation
  key, and the case makes useful progress without another business acceptance.
- P3-05: hold result A, accept revision B, then release A and complete B; A stays
  historical and causes zero current action intents, while valid confirmed B can
  progress through the real case authority.

Diagnostic tests include provider/storage exceptions containing sentinel secrets,
unknown input fields, request/room IDs, credentials and raw URLs. Assert their
absence from public diagnostics while retaining the safe code and useful
correlation. Exercise expected failures, unexpected outer-boundary defects,
cancellation and collector outages separately. Investigate leaked resources and
unretrieved task exceptions; do not hide them with warning suppression.

## Current foundation commands and evidence

The root make check command runs documentation/module checks, all implemented
Python tests and maintained Python lint/service/core type checks in the frozen environment. pnpm check,
pnpm test and pnpm build cover the TypeScript console. The local-setup manager's
smoke command exercises actual API readiness, local authentication, M1
replay/conflict, named-agent dispatch, text and fixture audio. These commands are
separate from product acceptance. All twenty P1 runners are now registered with
retained passing reports. P3-01/P3-03/P3-11 now have complete registered lab
runners and fresh passing reports; all 17 P2 and remaining 14 P3 rows stay planned. The
[Phase H assessment](work-items/0019-p1-phase-h-release-qualification.md) owns the
qualified P1 scope and provenance limits.

The [completed linked-confirmation/projection phase](work-items/0032-linked-confirmation-and-result-projections.md)
recorded passing separate P2 authority/race and P3 projection lanes. Preserve
those exact source-bound assertions when changing their behavior.
For P2, prove staleA/currentB, actual revision-versus-confirmation lock ordering,
linked-response/digest/current-association rejection, post-commit lost ACK plus
original-command receipt replay, one independent fake effect and owned cleanup.
For P1 work v4, require owner adoption with byte preservation, repeat/rollback and
actual SIGKILL recovery, all historical issued references, atomic live result/event
commit, a real blocked completion graph, scoped/source/ahead cursor negatives,
v4 delivery and guarded-action/effect compatibility, full old PostgreSQL regression
and a fresh installed wheel. For P3, require atomic derived rows/checkpoint,
restart/replay, immutable as-of observations, capacity/unknown/definite-malformed
results, strict public source checks and no execution/delivery side effects.
Keep failed fixtures and required setup non-passing. These selected contributions
register no additional complete charter row and do not qualify native media.

The [completed outbound-reply/processing phase](work-items/0033-outbound-replies-and-completion-processing.md)
requires actual P2 owner inbox-v3 migration/backup/restart, immutable enqueue,
current-route/suppression reservation races, known ordinary fake-carrier progress
and unknown-call ownership. P3 requires owner projection-v2 preservation,
separate scan/terminal-watermark assertions, unknownA/laterB progress, exact
receipt binding, real pre/postcommit process loss, concurrent ACK CAS and complete
receiver/SQL reconciliation. Missing setup/skips/timeouts remain non-passing.
P1 APIs and runtime are unchanged: prove all 77 payload bytes remain equal to the
existing qualified artifact, rather than rerunning unrelated provider behavior.
The selected 24-case P2 and 16-case P3 lanes and isolated installed consumers
passed. Fresh P2 23/22/18 and P3 projection/coordinator/execution 12/10/12
regressions plus registered P3 13/8/12 also passed. That phase recorded
1,501 Python and 723 TypeScript tests, broad 133/strict 95 typing sources
and 321 formatted Python files. No new complete charter row follows from these
selected contributions.

The [completed callback/applicability phase](work-items/0034-callback-evidence-and-applicability-refresh.md)
completed selected local phase gates for P2-I13 and P3-I11. Freeze exact child inventories and finite work/cleanup
budgets before actual runs. Callback gates require separate HMAC/window/scope
negatives, semantic replay/conflicts, exact original-attempt correlation before
send acknowledgement and after reassignment, deterministic reordered/conflicting
evidence, and both admission-veto orders with useful unrelated progress. Restore
populated v4 callback records/receipts and unchanged old inbox/outbox bytes.

The P3 gate freezes 18 cases and 20 owner/runtime modes, five PID-owned kills and
one actual CAS blocking graph. Require populated eight-table versioned-profile-row
restore, exact old/new source/ACK/receipt/refresh/tombstone joins before/after/reopen,
late A versus valid independently confirmed B, stale/unavailable observation
handling and hidden unresolved-result progress. This is not pg_dump or stale-branch
recovery proof. Strict JSON primitive types, first-failure precedence and complete
owned cleanup are required. Fresh offline installed consumers and old regression
lanes must pass before selected task completion; missing/skipped/timed-out gates
remain non-passing. Full P2/P3 registrations and media remain separate.

The [completed send-policy/action-race phase](work-items/0035-send-policy-and-action-races.md)
completed the selected local qualification for P2-I14/P3-I12. P2 must continue to
preserve populated v4 rows during owner v5 adoption and actual populated pg_dump/
psql restore/reopen. Keep ordinary provider-observed response loss unknown;
separate known/absent/unavailable lookup from permission for a new explicit
cooperating retry. Match stable operation bytes/key and distinct local attempts,
callback exact-attempt correlation, current permission and both veto orders.
Concurrent controller commands, replay/conflicts/caps, process loss and actual
late I/O ownership must preserve useful progress and independent ledger truth.

P3 requires two actual SQL blocker chains with two simultaneous writer waiters,
using the same prewarmed owner observer and unchanged 1000 ms lock timeout.
Revision-first rejects A atomically and allows independently confirmed B;
intent-first makes B revision fail, while A's original receipt and effect survive.
Assert all pre-intent/claim/reservation/known-effect cancellation boundaries and
three owned kills: action before commit, after commit, and supplier success before
local finish. Fresh processes reconcile original identities without reapplication.
The closed 31-mode/16-case protocol reserves 15 of 180 seconds for cleanup,
permits at most 32 child calls and bounds capture/report bytes. Strict primitive
and PID-marker negatives, exact full joins, public installed consumers and fresh
old regression lanes are required. Diagnostic mode can never qualify. P1/P3
runtime bytes remain unchanged; broader deadline/recovery/media rows stay pending.

The selected checkpoint passed 1,660 Python tests (49 P1, 14 P2, 238 P3,
1,359 root) and 861 TypeScript tests (326 console, 457 P2, 78 specialists), with
broad 138/strict 108 type sources and 340 files passing Ruff formatting. The
30-case P2 and 16-case P3 source gates, isolated installed consumers and prior
111 P2/101 P3 regression assertions passed. These are correctness checks, not
production capacity or real-media measurements.

Native SDK smoke passed from host and container on macOS arm64 Docker Desktop.
Authenticated browser room/text, explicit disconnect/reconnect and M1
acceptance/replay/conflict passed. The separate
[Phase G gate](work-items/0013-p1-phase-g-conversation-and-showcase.md) adds actual
scripted WebAudio/WebRTC input, returned browser audio, active interruption,
fresh-room same-task continuation, held-dependency controls and inspected filtered
traces. The separate selected provider_real v2 gate establishes actual provider
recognition, tools, synthesis and browser playback in its declared local scope.
Physical microphone quality, automatic network-loss media recovery, local_real
qualification and production capacity remain unqualified; remote CI is outside
scope. A normal stop/start
must preserve the M1 identity without volume reset. Optional Jaeger UI readiness
alone does not establish exported traces. See the
[foundation work item](work-items/0003-local-project-foundation.md) for results
and the [local setup guide](../local-setup/README.md) for operational commands.

## Phase A execution evidence

P1-01/P1-02/P1-03 now use the shared five-test test_execution_acceptance.py suite
with actual owned accepting-process termination, commit-before-ack barriers, six
concurrent acceptors and scoped replay/conflict. Migration tests additionally
exercise old data, abrupt precommit exit and SQLite backup/restore; async tests
use actual thread barriers. Phase B now also provides the four-test independent inquiry/supplier crash suite
for P1-04/P1-05. Phase C adds a separate required real-PostgreSQL lane; richer lifecycle and media
evidence remain separate. See the [phase work item](work-items/0007-p1-phase-a-execution-foundation.md).

## Foundation qualification and installed consumers

Before broad product feature expansion, exercise the actual browser's authenticated
local connection, invalid credentials, text echo, expected-agent sender checks,
exact diagnostic payload handling and disconnect/reconnect. Test explicit
microphone enablement and permission denial where browser automation permits it;
use deterministic audio fixtures for repeatable media assertions. Correlate frame
reports to the intended track. Report capability-blocked browser checks as pending.
Host/container SDK smoke and browser playback remain distinct evidence. Qualify
the supported local host and Linux-container paths with actual installed execution,
not source imports or workflow YAML. Hosted CI and publishing are outside this
POC scope. These are foundation checks, not completed product IDs.

P1 now has a standalone src-layout distribution and real isolated consumers. Build
its wheel/sdist, rebuild from the sdist and install outside repository import paths.
Apply the same artifact discipline when later P2/P3 boundaries become real. Its minimal
public-API example must work using declared dependencies and exports, with no
hidden sibling source imports. An installed P1 execution-library dependency may
support P3 standalone use without requiring the full P1 service deployment.
Repeat the applicable consumer test in the release lane.

## Deterministic scenario protocol

Each scenario defines an ID, project, requirement, mode, fixtures, preconditions,
process boundaries, actions, exact assertions, timeout, cleanup and artifacts.
Implemented registration points to a known executable runner. Planned scenarios
have no executable and return not_implemented with a nonzero exit status.

Use barriers/failpoints for concurrency schedules. Use a controllable clock for
timers and retry eligibility; do not depend on long sleeps or lucky races. Fake
provider state must survive the worker crash independently of the worker's local
acknowledgement. Process termination must actually terminate the process in the
crash test. Reopening a connection is insufficient evidence of process recovery.

For each failure injection, include a normal path and a recovery/liveness
assertion. Rejecting all work must not pass safety tests. Compare final database,
supplier and delivery observations against expected histories.

## Required fault boundaries

| Boundary | Required assertions |
| --- | --- |
| Before intake commit | No accepted acknowledgement; no partial accepted record |
| After commit before response | Retry returns the original identity and payload |
| After supplier effect before local acknowledgement | Reconcile under supplier contract; uncertain outcome when safe evidence is absent |
| Lease expires while an old worker resumes | Reject stale state write; separately test the external request boundary |
| Completion committed before outbox delivery | Recover a stable logical event and deduplicate at a cooperating receiver |
| Message persisted before agent dispatch | Recover accepted input after gateway/process failure |
| Outbound send succeeds but acknowledgement is lost | Preserve stable identity and explicit uncertainty without unsupported one-SMS claims |
| User revision races with specialist result | Atomic case-authority decision; no action based on stale/unauthorized input |
| Revision or cancellation after intent commitment | Respect the documented best-effort external boundary; expose actual outcome |
| Room reconnect or agent handoff | Load the right scoped case and current route; preserve partial/unknown communication evidence |
| Slow storage, supplier, carrier or specialist | Bound concurrency and queues; keep active conversation responsive and admitted work inspectable |

## Replay retention and remote trust

Before automated cleanup, record the supported replay horizon, retained
idempotency/effect tombstones and behavior after identity expiry. Pruning display
history or passing a business deadline cannot make an already accepted logical
operation new again. Test a delayed replay after history pruning and preserve
uncertainty/effect evidence required for reconciliation.

For P3 HTTP invocation, bind scope to an authenticated local service principal and
authorize invocation, status/result queries, cancellation and image access. Test
forged body scope, unavailable/invalid service credentials and cross-tenant
references. P1 owns durable attempts and retry/deadline eligibility; remote status,
cancel acknowledgement and late results are correlated observations. Test lost
responses and duplicate invocations without creating another recovering queue.

Before independent specialist implementation, retain a controlled tools/native
subagent baseline and deployment decision. PLAN-21 still runs the final three-way
comparison with equivalent model/provider configuration where applicable.

## Current P2/P3 contract and persistence lanes

P2 now has an explicit real PostgreSQL lane through make p2-postgres-check. It
requires the existing init/start/prepare-postgres setup and pinned host Node;
it creates only marked UUID schemas and uses separate owner/runtime credentials.
Default Vitest discovery excludes its non-test-named PG file, while TypeScript
still checks that source. Missing setup or cleanup never becomes a skip. Use a
fresh --report path under .local/validation/p2-postgres when retaining a run.

The lane verifies signed challenge possession, protected epochs/revocation,
concurrent durable replay, receipt/intent atomicity, paging/caps, schema/privilege
drift and actual accepting-process termination after commit. I07 adds explicit
v2 claims, immutable prepared dispatch and cooperating-acceptor recovery through
make p2-dispatch-check; the full lane includes these five actual cases. Broader
restart schedules, outbox, carrier delivery and media retain their later gates.
The separate gateway/owned scripted-agent lanes now prove their selected restart
boundaries; those are not complete P2 charter rows. make p2-demo selects
the public standalone example and new-process receipt/operation-key replay checks.
Its preview remains pending/not_executed; operation inspection is not dispatch.
P3's contract tests remain provider-free and its I05 suite now uses actual loopback
sockets for authentication, strict framing, held work, timeout/disconnect, response
validation and cleanup. make p3-demo runs the public-export handler/client example.
P3-I06 adds immutable coordinator submission through public P1 work_api; the
coordinator owns no side ledger. make p3-coordinator-check exercises actual P1
PostgreSQL, postcommit process termination/replay, scope isolation and separate
Python-to-TypeScript client transport. Its case preflight fixture is synthetic;
its transport probe is not a P1-issued execution. No coordinator invocation,
durable result/delivery/action or specialist recovering queue is qualified here.
The local PG runtime credential is shared with P1 for these fixtures, which does
not prove independent P1/P2 database principals. A separately exposed deployment
requires an isolated principal before qualification.

Root frontend validation includes all three implemented TypeScript packages and
pinned Prettier checks for P2/P3 source/tests. Python checks include the new P3
contract/trust modules and the strict host PG wrapper. Package-level malformed,
wrong-scope, resource, expected-error and useful-progress tests stay mandatory.

### Revision routing and complete P3 lab acceptance

The [completed routing/acceptance phase](work-items/0031-revision-routing-and-delegation-acceptance.md)
adds equivalent standalone reference/P1 case-CAS qualification. I10 must retain a
real two-command blocking graph under each selected authority, one winning
revision despite skewed occurrence timestamps, stale conflict, valid subsequent
progress, unchanged request and postcommit lost ACK. No matching later state may
be relabelled as the original command receipt. Integrated P1 reads/revisions use
the public bridge with fixed trusted bindings; serving code gains no DDL. Current
association revocation is not atomically rechecked by retained inbox inspection or
this cross-authority CAS; complete P2-12 remains a later gate.

P3-01/P3-03/P3-11 are registered lab cases with fresh passing reports:13 actual
completion/action assertions, 8 independent-process concurrency/identity assertions,
and 12 complete schema/scope/input/output/image-resource rejection assertions,
respectively. Run make p3-contract-check for the latter two direct components;
the harness selectors below execute fresh complete cases:

```sh
.venv/bin/python -m harness run P3-01
.venv/bin/python -m harness run P3-03
.venv/bin/python -m harness run P3-11
```

Use existing restricted-role local PostgreSQL and pinned Node setup. Missing setup,
wrong inventory, stderr contamination, skipped assertions, stale/mismatched report
bytes or incomplete owned cleanup cannot pass. The acceptance wrapper retains a
fresh component path/hash and matches validated stdout to that file. Oversized
image rejection happens before decoding; it does not qualify image extraction or
multimodal inference. Seventeen P2 and fourteen P3 rows remain planned, so their
full project/ecosystem aggregates remain incomplete.

## Audit-driven integration and operational qualification

The [audit disposition](work-items/0020-architecture-audit-reconciliation.md) maps
review findings to current evidence and owned follow-ups. The following are
required exit criteria for the affected future slices, not passing registrations
or additions to the 55-case catalog. Preserve existing project acceptance IDs.

| Owner and existing mapping | Deterministic negative schedule | Useful-progress and evidence requirement |
| --- | --- | --- |
| P2-I03 / P2-12 | Expired/replayed/concurrently consumed association challenge; revoked or reassigned number; valid webhook with another account's case | Current verified association succeeds; no cross-account read/send; actual persisted association/version and protected access checks |
| P2-I04/I10/I11 / P2-05/06 | Skewed/delayed provider timestamps and simultaneous channels; stale or unlinked confirmation | Persist server acceptance order in its named namespace; current exact revision/confirmation progresses; no timestamp-derived authority |
| P2-I12/I13/I18 / P2-09/10/12 | Hold delivery, replace room/route, revoke association, then replay old callback; lose send acknowledgement | Same immutable recipient and logical send identity; current verified route progresses; original ambiguous send stays unknown and retains provider idempotency key where supported |
| P3-I03/I04/I16/I17 / P3-11/15 | Schema-valid wrong fixture fact, altered or cross-account source, invented evidence/rule, injected screenshot instructions | Exact accepted input/source binding, bounded authorized evidence and factual evaluation; ambiguity requests clarification, grounded current facts progress |
| P3-I12 / P3-06/07 | Evaluate A, prepare intent, commit B in another transaction, then submit A; run inverse ordering too | Actual PostgreSQL barriers: zero stale A intents/effects, valid independently confirmed B commits once; postcommit outcome remains explicit |
| S-I08 / integrated release | Cross-account callbacks/results, authorization changes at commitment, malicious input, slow dependency plus valid burst | No capability escalation, bounded queues/tasks, useful valid progress and inspected real sanitized exports; no placeholder metrics |
| Planned P1 operational follow-up | Restore before reservation and before intent while independent supplier/receiver advance; crash reconciliation; race reviewers | Dispatch quarantine, no duplicate mutation, original identities where provable, append-only observations and separate consent; see the operational work item for exact safety/liveness criteria |

A documentation check verifies contracts and links, not these product behaviors.
Before each implementation, freeze actual schemas, finite time/resource budgets,
failpoints, error vocabulary and evidence destinations in its work item. Run the
real store/process/media lane when that boundary is claimed. Do not invent a
passing runner for future adjudication, restoration, P2 or P3 work.

### Discovery and consumer feedback

make test runs root and all three project Python unittest suites; make check additionally
runs the fail-closed structural/test harness, Ruff and maintained typing. Formatting
remains the separate make format-check gate. pytest is installed tooling, not a
second claimed correctness lane. When a P2/P3 package first has source, add its
actual workspace/member paths, lint/format/type checks, tests and build commands
in the same slice. Prove with a failing package fixture and a nonzero test count
that the root gate executes it; a console-only pass cannot qualify a new package.

G-PACKAGE proves artifact execution; it does not prove first-time human usability.
Follow [CONTRIBUTING.md](../CONTRIBUTING.md) for a fresh consumer/feedback record.
Freeze runtime and artifact, time setup, record missing steps and actionable error
interpretation, and retain the resulting API/docs revision or reason for keeping
the API. Human feedback remains pending until a person actually supplies it;
automated independent review must retain its own attribution.

Dependency inventory/scanning is a separately planned local tooling gate in the
[technology policy](technology-baseline.md#dependency-inventory-tool-qualification).
A lockfile or successful frozen installation is not a completed vulnerability scan.

## Load methodology

Measure infrastructure and real media separately. Begin with deterministic
workloads, then use small real-model/media runs within declared resource and
provider limits. V1 requires a laptop-local capacity study, not a claim of
production/global scale.

Use fixed seeded workloads and publish the seed. Suggested starting experiment
points are 1, 10 and 50 concurrently active fake jobs, 1 and 2 independent workers,
and 1,000 dormant conversation records. Increase only while local resources stay
within configured bounds. These are experiments, not promised capacity or minimum
throughput. For real audio, establish one correct session before increasing load.

Required experiments are steady load, a bounded burst, sustained saturation,
worker termination/restart and a slow-provider case. Include a second admitted
tenant when testing per-tenant caps. Overload must reject/defer explicitly before
acceptance or preserve accepted work under its documented policy.

Record accepted/completed/failed/uncertain counts, lost accepted work, duplicate
external effects, queue age, recovery lag, admission and dispatch latency,
event-loop lag, CPU, RSS and errors. For delegation, assert zero stale action
intents and successful progression of expected current results. Keep filler
responses separate from useful task progress.

For voice, record speech end to first audible response, first meaningful
response, interruption yield and time to useful result. Mark timestamp sources:
agent-side emission and client-side playback observations are different.
Collect the installed SDK's current chat-message/provider metrics, session usage
and session reports through documented supported hooks, with bounded OpenTelemetry
export where applicable. Establish the hook/version contract at integration;
deprecated session-level metrics_collected is not the target API. Inject exporter
and provider/store failures, assert safe classified outcomes, and prove telemetry
failure does not block conversation or create unbounded retries.
Report sample counts with p50/p95 and show tail percentiles only with enough
samples to interpret them. Stage timings differ by pipeline; do not invent
STT/LLM/TTS timings for a model that does not expose them.
[LiveKit data hooks](https://docs.livekit.io/testing/observability/data/).

Before performance-sensitive implementation, retain a baseline using the selected
stack and machine. Set numeric budgets in the workload manifest before evaluating
the change. If behavior exceeds a budget, investigate and fix it or document a
reviewed tradeoff and update the baseline explicitly. Never rewrite expected
results just to turn a failed run green.

### H1 declared inquiry baseline

The [H1 work item](work-items/0014-p1-phase-h-workload-baseline.md) owns the completed
S-I06/P1-I27 local inquiry measurement and inspected results. This is a qualified
local baseline, not full H/P1 or portfolio release. The frozen
[manifest](../harness/workloads/p1-inquiry-v1.json) is authoritative for this slice;
the suggested larger experiments above are later work, not implicit H1 coverage.

From the repository root, make p1-benchmark-plan validates the default declaration,
prints its canonical digest and returns status not_started without starting a
workload. make p1-benchmark explicitly runs the installed API/worker lane after
its [local prerequisites](../local-setup/README.md). Preserve the reviewed manifest
and digest before execution. Never change a schedule, bound or expected result to
hide a failed measurement.

| Frozen experiment | Declared new offers and expectation | Required observation |
| --- | --- | --- |
| steady-w1 and steady-w2 | 20 each, at one-second scheduled spacing; all admitted | Original identities/results and scheduled-versus-actual request timings |
| burst-w1 and burst-w2 | 32 each; four shared HTTP slots; all admitted | Bounded caller queueing plus every applicable persisted inquiry result |
| saturation-w1 and saturation-w2 | 32 each; eight admitted and 24 rejected before workers start | Original-key replay/read at capacity, explicit excess rejection and useful result progress after start |
| Aggregate declaration | 168 offers, 120 admissions, 48 capacity rejections | Expected inputs only; reconcile actual records and independent receipts |

The API and each worker are capped at 1000 millicores, 512 MiB and pids limit 128.
Each experiment has 180 seconds within the 600-second overall budget; owned
cleanup has its bounded 90-second allowance. At most 4096 raw records and the
64 KiB HTTP envelope are retained. Missing setup, unreadable/missing observations,
zero useful progress, required timeout, wrong receipts or incomplete owned cleanup
cannot pass. The lane creates source-bound installed containers, UUID-owned
schema/fixtures and no checkout mounts; it never resets ordinary M1 data.

All HTTP operations share one declared semaphore/pool. Case observation is one
global round-robin GET followed by a 250 ms sleep; HTTP/slot delays and cohort
sweeps add lag. Keep scheduled offer, first HTTP start, known validated acknowledgement
and first successful validated submit/replay/GET snapshot separate. Unknown attempt
finish does not imply acceptance. Client-observed result latency includes caller
queueing/polling and cannot stand in for a supplier completion timestamp.

Resource probes are sequential in-container Python reads targeting a one-second
cadence, with actual start/end/duration and skipped intervals. Their CPU/accounted
memory/PID overhead is included. Verify exact configured caps separately from
retained usage overage. Cgroup memory is not RSS or a peak; CPU cumulative usec
have explicit first/last/delta/window. The resource window includes post-inquiry
cancellation/delivery checks and excludes host/VM/shared-database resources.
Raw samples and count/minimum/median/maximum are sufficient for this small baseline;
no unsupported tail percentile, media/model or production capacity is claimed.
See [observability](observability.md) for detailed units and clocks.

Retain frozen workload/source/image/machine provenance, bounded safe raw records,
per-experiment results and failed artifacts under .local/validation/p1-phase-h.
Original failures retain fixed-enum code/operation and observed exit/timeout/budget/
elapsed metadata before temporary capture removal; cleanup failures remain separate.
Reject raw argv/output/environment/body/exception retention. Automatic host platform/
architecture/Python and installed runtime architecture differ from separately
collected Docker-VM hardware/shared-host context; label supporting environment.json
accordingly. A pre-cleanup measured snapshot is not a phase pass. Require independent inquiry
reconciliation, unchanged booking/zero mutation and verified owned cleanup.
Explicit post-inquiry cancellation, final business state and receiver delivery
stay distinct. Preserve closed G artifacts when running the required actual
browser regression for the H console change. H2 restart/slow-dependency/saturation/
shutdown and I26 host/Linux artifact/API/genuine-consumer gates passed separately.
P1 V1 is qualified for the local POC using provider_real v2. local_real remains unqualified and complete P2/P3 acceptance remains pending. This H1 lane alone registers no complete charter runner.

## Development workflow for people and coding agents

1. Read root and nearest AGENTS.md, the affected Design.md, charter and current
   implementation status. Select the acceptance IDs for the change.
2. Write a short change plan with behavior, interfaces, failure cases, validation
   commands and scope limits. Existing deterministic contracts govern the plan.
3. Implement one coherent slice with typed boundaries and meaningful tests of
   the relevant failure behavior. Add new schema migrations without dropping
   existing data. Avoid unrelated refactors.
4. Run the narrow checks, then the required integration lane. Run lint/type/build
   checks for affected languages once those toolchains exist. An unavailable
   tool is a reported gap, not a pass.
5. Inspect artifacts and review correctness, cancellation, resources, schema
   compatibility, API ergonomics and documentation against the acceptance IDs.
6. Update implementation status, decisions and evidence. Record AI assistance and
   leave a concise handoff with commands, results and unresolved work.

The learning workflow remains explain, attempt, review, change. AI assistance
does not remove the need to understand and modify the implementation. Scope and
harness work can be assisted; portfolio authorship claims must match contributions.

## Release gate

Local-ready V1 requires all applicable deterministic and local-media acceptance
rows, standalone examples, integrated contract checks, clean setup, migrations,
restart, bounded shutdown and local load evidence. Portfolio-ready V1 adds
selected real-model behavior, benchmark comparisons, a usable minimal API,
documentation review and a short success/failure demonstration. Each gate reports
passed, failed and unimplemented IDs explicitly.

Require an independent review of the public API and failure contract. The review
must identify assumptions, try the documented setup and verify at least one
failure scenario. Resolve actionable findings or retain a justified, scoped
limitation before release. Percentage coverage alone is not a release criterion.

## Evidence and reporting

Each run records schema version, run/scenario IDs, result, mode, code snapshot provenance, stack versions, fixture seed, workload and resource
limits, timing sources, commands, elapsed duration, and relevant artifact paths.
Live runs additionally record model/provider/configuration, region where known,
sample count, task outcomes and cost or an explicit unavailable-cost observation.
Never dump credentials or the entire process environment into a report.

Write disposable run output under ignored .local/harness. Promote reviewed,
sanitized summaries and reproducible fixtures to a versioned evidence directory
when a release needs them. Logs/traces must correlate case, revision, workflow,
delegation, attempt, effect and delivery identities without treating correlation
as authorization. Preserve raw results needed to explain a failure.

LiveKit unit tests support turn/tool/handoff assertions. Cloud Agent Simulations
can supplement conversation evaluations; text mode bypasses audio. The local
gate must not depend on Cloud or infer actual playback behavior from text tests.
[Unit tests](https://docs.livekit.io/testing/unit-tests/),
[Agent Simulations](https://docs.livekit.io/testing/simulations/).

## Phase C PostgreSQL gate

Run init, start, prepare-postgres and migrate-postgres through local-setup/stack.py,
then make postgres-check using the frozen project interpreter. This explicit lane
loads private local credentials without printing them, rejects ambient target
redirection and creates/removes only isolated owned schemas. Missing setup,
connection refusal, zero tests and skips cannot pass. Fast tests do not silently
start Docker and do not substitute for this lane. CI is wired to run it; remote
CI execution remains unverified until an actual run is observed.

Required assertions include exact M1/inquiry import, backed-up source quiescence,
precommit rollback, abrupt migrator loss at recorded checkpoints, idempotent
completed receipts after legitimate target progress, final locked activation
verification, role/DDL/control-write rejection, common SQLite/PostgreSQL behavior,
trusted actor cross-scope denial, normal inquiry and independent-process supplier
success before local acknowledgement. Preserve the first SQLite proof. Full
P1-15 leases and P1-17 signals/cancellation remain non-passing until implemented.

## Phase D authority and continuation gate

The PostgreSQL gate now also requires the v2 upgrade, exact authority and
wait/signal/retry suites. It tests current scope/actor/revision/quote/deadline,
known-receipt replay after expiry, revision-vs-commit winners, atomic intent/event,
stale-wait invalidation and fresh revision progress, finite transient retry,
permanent/exhausted/deadline failure, ambiguity without resend and independent
process restart. Required suite files, zero-test discovery and skips fail closed.

make phase-d-demo uses two distinct runtime-only containers with no shared app
files. Assert pending waits and no intent before the first exits, then observe
exact consumption, stable replay, a separately expired wait, unchanged supplier,
positive metric samples and safe JSON events in the next. Artifact passes only
after owned schema/container cleanup succeeds. Existing M1 data/volumes and
real RTC smoke must still pass; this is not browser/human-presence/model evidence.
The default PostgreSQL report is .local/validation/postgres/latest.json; explicit
POSTGRES_REPORT selects a phase artifact without overwriting historical gates.

## Phase E mutation, cancellation and completion gate

Run the full fast lane, strict changed-boundary types and format check, followed
by make postgres-check with POSTGRES_REPORT under .local/validation/p1-phase-e.
The real database lane requires v3 upgrades, mutation worker, effect/outbox and
Phase E compatibility/cancellation boundary suites. No required suite can be
removed, silently skipped or replaced by mocks. Keep database checks serial with
image builds and the existing finite lock/connection deadlines.

Require exact v2 case/provider/expected-revision consent; literal v1 preservation
and known receipt replay without granting legacy mutation; wrong provider before
attempt budget; normal authorized progress; actual kill and abrupt exit after
supplier commit; cooperating dedup/lookup and genuine noncooperating uncertainty;
precommit/pre-dispatch/possible-dispatch cancellation races and immutable terminal
truth. Corrupted active-attempt evidence must fail closed without closing another
workflow's attempt. Scope/owner checks precede replay and external calls occur
outside protected transactions. Replacing a pending quote withdraws its old wait
without extending the original business deadline.

Require terminal outcome/event/pending-delivery atomicity, rollback at insertion
barriers, actual receiver commit before process loss, fixed receiver identity,
finite backoff/exhaustion with business result preserved, altered replay rejection,
and late dedup after diagnostic pruning. Core receipts remain retained at capacity.

After image rebuild, make phase-e-demo must observe two external-commit crashes
and recovery in fresh installed containers with source hashes, real safe events,
positive metrics and owned cleanup. Then run the existing RTC smoke to preserve
native text/audio and original M1 identity. These lanes contribute to P1-06/07,
08/09,13/14,16 and migration/retention requirements. They do not complete the
speech-interruption, lease, browser, model, full platform or portfolio release
gates. The harness catalog owns current complete registrations; missing rows remain
non-passing.

## Phase F lease, admission and bounded deployment gate

Require the previous Phase E gate, an explicit owner-only ACTIVE v3-to-v4 upgrade,
and the current frozen dependency/image baseline. The PG lane additionally
requires pg_upgrade_v4_cases.py, pg_lease_cases.py and pg_coordination_cases.py.
Tests must execute actual database/server-clock and independent-process schedules;
missing setup, skips, timeouts or zero tests cannot pass.

Assert populated old rows/bytes/receipts, rollback and abrupt upgrade loss, exact
ACL/catalog policy, unmanaged-running preflight and useful v3 recovery before
upgrade. Exercise acquire replay, renewal, expiry, release, capacity, monotonic
epochs and original scope with two workers. A child blocked on admission before
expiry must recheck actual server time after the lock. A stale/missing grant may
not claim, reserve or acknowledge inquiry, mutation or delivery. Public controller
commands remain independently authorized and do not grant worker authority.

Pause a real old worker after dispatch reservation or external success, observe
lease expiry and takeover, then resume it. The cooperating supplier must dedup
its stable effect; noncooperation must remain uncertain with no successor resend.
Known external truth must stay inspectable while old acknowledgements are fenced.
No database fence alone proves external-call exclusion.

Test pending capacity through waits/committed intents, retained M1 identities,
known replay/enrollment at retention capacity, late management admission, expired
inquiry-complete work, unsupported legacy intents/signals and exhausted epochs.
Require useful eligible work after pressure/expiry; neither failed display history
nor pruning may erase core receipts or create new identities.

Verify one owned process step, output/failure/time limits, actual SIGTERM drain and
forced group cleanup with descendants, lease release only after reaping, strict
internal claim codec and safe real producer metrics/logs. Rebuild the image, run
make phase-f-demo against the actual opt-in worker profile and preserved isolated
fixture volume, then retain the original M1/RTC smoke identity. Keep SQLite inquiry
compatibility and existing Phase E container proof. Optional workflow definitions
mirror local gates; hosted CI/publication are outside the local POC scope.
Complete local integration/model/media and portfolio release still require their
applicable observed evidence.

## Phase G conversation and media lane

Run the [Phase G work item](work-items/0013-p1-phase-g-conversation-and-showcase.md)
against the frozen local environment. Offline discovery includes native AgentSession
manual audio→STT→LLM→function tools, exact HTTP/grant boundaries, safe report/trace
filters and queue/outage/race regressions. The PostgreSQL lane explicitly requires
pg_conversation_cases.py and exercises atomic admission rollback/replay, owner and
revision fencing, useful progress and projection cursor/history bounds.

The installed stack lane requires real browser-published scripted audio, received
speech with advancing browser playback, native interruption, end/reconnect and
independent durable progress under held dependencies. Permission denial is a
separate negative check. Inspect exported OTLP spans and numeric SDK reports, plus
an independent supplier/receiver record. Browser traces/HAR/video must not capture
credentials; artifacts contain only allowlisted counts/states and token-free UI
screenshots. Physical microphone/hearing and real inference remain separate gates.
Keep original M1 identity and prior phase closing artifacts unchanged during
compatibility runs. A failed required lane leaves the phase non-passing.


### Current local P1 qualification

P1 V1 is implemented and locally qualified with selected provider_real v2.
The final 20-case index, current P1-18/P1-14/P1-20, full H2, PostgreSQL, installed
host/Linux artifacts and shared quality gates passed with independent reviews.
Historical checkpoints retain their original scope. local_real remains unqualified;
complete P2/P3 acceptance remains pending, and hosted CI/publication are outside this local POC.


## Case rehydration and standalone qualification

The [completed handoff](work-items/0038-case-rehydration-and-standalone-release.md)
separates focused units, actual durable/media gates and installed consumers. P2
passed eighteen storage assertions in 6.534 seconds and three actual media groups
in one Playwright case in 35.797 seconds. Its nine-payload Python package passed
111 tests in fifteen commands/52.364 seconds; its isolated npm consumer passed
seven stages in 2.1696 seconds. P3 passed eight offline plus eight actual installed
assertions in 58.885 seconds. All 166 selected P2 compatibility assertions passed
in 98.997 seconds. No selected pass registers a full charter row.

Final shared gates passed 2,148 Python tests and 1,224 TypeScript tests
(503 console, 632 P2, 89 specialist), broad/strict typing over 144/132 files,
Python formatting over 387 files and documentation validation for 113 documents. All 29 Mermaid
bodies passed syntax-only parsing. Ordinary doctor/smoke passed with ten audio
frames and original M1 state preserved. The catalog remains 55 defined/24
registered; all 17 P2 and the remaining 14 P3 rows stay planned.

Run make p2-rehydration-check and make p2-rehydration-media-check with existing local
restricted-role PostgreSQL/SFU/browser prerequisites. Run make p3-package-check for
offline artifacts and make p3-package-lab-check for explicit combined validation.
Preserve failed attempts, exact named assertions, owned process/SQL ordering,
complete original receipt joins and populated restore. Manifest validation binds
every physical retained file, including nested summaries, and excludes only its
own descriptor file. Guard shared readers and DDL until actual owners settle.
Missing setup, timeout, skipped work, unresolved cleanup or absent proof cannot pass.

## Active workload and image gates

The [completed handoff](work-items/0039-bounded-channel-workloads-and-image-evidence.md)
records completed selected P2-I19/P3-I16 qualification. Freeze sources, roles, schedules, private
proofs and numeric study ceilings before a normal run; preserve original failures.
These lanes add no catalog registration or full release claim.

| Lane | Selected inventory and bound | Required interpretation |
| --- | --- | --- |
| P2 workload | Twenty-four named assertions; seed 39; 360 seconds including 20 cleanup, at most 32 children, 8 KiB per stream/512 KiB aggregate capture, 2 MiB direct proof and 32 KiB report | Actual restricted-role PostgreSQL/HTTP admission, retained identities, second-scope progress, dormant inspection, fresh-process reopen, populated restore and complete cleanup; selected local qualification passed |
| P2 study ceilings | Admission 5 seconds, useful completion 15 seconds, sampled event-loop maximum 1 second and sampled Node RSS 512 MiB | Fixed selected local failure ceilings; report clock/sample scope and actual observations, not throughput, tenant fairness or production capacity |
| P3 image source | Twenty named assertions: eight cross-language/structural/factual and twelve actual socket/lifecycle; 120 seconds including 20 cleanup | Actual PNG guards, zero provider entries for invalid/expired work, eight scripted provider admissions, independent literal facts and actual resource settlement; selected local qualification passed |
| P3 image installed | Fresh maintained offline-eight artifact builder followed by the same twenty image assertions; 360 seconds including 20 cleanup, at most 32 shared children, 64 KiB streams/2 MiB aggregate capture, 32 KiB proofs/report | Public isolated Python/npm consumers, unadapted declared fixture/helper inputs, exact physical retained index and source/archive scope; not twenty PostgreSQL scenarios or vision inference |

P3's supported PNG subset is RGB8/RGBA8 noninterlaced, at most 2 MiB encoded and
2048×2048 pixels, with bounded chunk/CRC/zlib/scanline/filter validation. Require
actual worker exit 0, a fresh original-deadline check before provider work and
retained provider promises after timeout/cancel. Structural validation does not
prove extracted values or regions: independent valid-JSON wrong-value/swapped-region
negatives must fail factual evaluation. P1 remains policy-only; no durable image
execution or action follows. Selected P2-I20/P3-I17 qualification is recorded below.

## Operations and fixed-policy gates

The [operations and policy handoff](work-items/0040-operations-ui-and-fixed-policy-evidence.md) owns the frozen cases and actual results for P2-I20/P3-I17.
Selected normal qualification passed; complete charter rows retain their own gates.

| Lane | Required inventory | Predeclared bounds and evidence |
| --- | --- | --- |
| P2 operations | Sixteen actual PostgreSQL/HTTP groups and three browser groups in one actual Playwright case | 240 seconds including 20 cleanup; thirteen normal children, ceiling 24; 8 KiB/stream, 512 KiB captures, 1 MiB/direct proof, 16 MiB retention and 32 KiB report. Independent complete durable snapshots and original identity/provider/callback joins; actual zero owned occupancy after closure |
| P2 UI/lifetime | Read-only transitions, paging, failure/recovery, exporter outage and Forget while a real case read is held | Token-free screenshots and allowlisted finite browser observations; raw browser streams/reports are not retained. Backend late-work ownership and unit positive late-result epoch fencing are separate proofs |
| P3 fixed policy source | Eight contract/factual/cross-language and twelve actual HTTP/lifecycle assertions | 120 seconds including 20 cleanup; six direct commands. Fresh fourteen-module private compile and staged unadapted public consumers; no ambient dist authority |
| P3 fixed policy installed | The same twenty assertions from fresh isolated public artifacts, plus eight separately counted offline package assertions | 360 seconds including 20 cleanup; twenty-seven normal direct/nested commands, ceiling 32; 64 KiB/stream, 2 MiB captures and 32 KiB/direct proof/report |

P2 final disclosure after a held external case read uses fresh PostgreSQL time and
current permission. This new gate has zero SQL waiter graphs; unchanged lock-time
freshness is verified separately by the required fresh I18 eighteen-group storage
regression. Preserve the existing actual media compatibility lane. The new UI
studies revision 0 as read-only and introduces no storage version or mutation.

P3 requires all applicable rule/fact witnesses, exact source/version/digest binding,
structural acceptance separated from factual truth, original request fingerprints,
seventeen receiving-path negative probes and actual held-work settlement. The
parent independently joins client canonical wires with server request/result
observations; they are not raw TCP captures. Source and installed reports are
separate from the nested offline-eight artifact report. Preserve v1 defaults,
image HTTP and current durable-policy compatibility. Missing setup, skipped cases,
timeouts, unverified sources, secret captures or incomplete cleanup cannot pass.

The completed 0040 results are P2 sixteen PG/HTTP groups plus three actual browser
groups, isolated npm105/seven stages and 187 current compatibility assertions;
P3 twenty source and twenty installed fixed-policy assertions, separate offline
package checks, both twenty-assertion image compatibility gates and 146 existing
compatibility assertions. The maintained sixteen-assertion P3 package composition
is included in 146, not an extra sixteen PG-only scenarios.

Eight complete P2 owner snapshots use separate <=1 MiB canonical files and a
<=32 KiB path/type/hash/byte/table-count manifest. Aggregate retention stays
16 MiB; all rows/catalog data and independent before/after joins remain present.
Current packaged README prose changes have exact source/archive equivalence
reviews and fresh offline artifact checks; original actual installed archives keep
their original README bindings. Two added foundation entries only discover the
new P2 producer/lifetime regression file. They change no runner registrations.
Final source census, ancestor/link safety, immutable prior checkpoints, exact
physical retained sets and owned cleanup are verified before sealing evidence.


## Standalone application and durable-v2 prerequisite

The [completed 0041 work item](work-items/0041-standalone-channel-and-durable-policy.md)
owns premeasurement manifests, source bindings, closed role/process inventories
and observed results for P2-I21 and the P3-I18 durable prerequisite. These are
selected implementation gates, not new acceptance registrations. P2 installed20,
separate public-P1 six and compatibility187 passed. P3 source12, installed12,
separate offline8 and 146 selected compatibility assertions passed. Shared checks
passed 2,537 Python/1,501 TypeScript tests, broad/strict typing150/156, formatting433
and documentation119. Historical compatibility is bound to original source bytes;
the reviewed exception-code annotation preserves runtime behavior, while fresh
source/installed gates bind the final bytes and installed public type regression.

P2's installed starter must demonstrate routing, original history, synthetic
delivery and restart without P1/P3 services. Its single owned process kill follows
an actual flushed HTTP acknowledgement; external commit/ACK loss is a separate
bounded transport fault and fresh lookup. A distinct installed public-P1 contract
repeat cannot be counted as standalone behavior or inferred from earlier reports.

P3's twelve measured assertions exercise explicit v2 acceptance/issued execution,
strict immutable evidence, original replay, expired/cancelled historical facts,
abandoned-owner retention and fresh lookup after one owned postcommit kill.
Source and isolated installed runs remain separate; installed mode also executes
the eight separately counted offline artifact assertions. Verify exact Python36
and npm32 payload inventories rather than accepting a larger arbitrary package.
The maintained current v1 policy/image and full compatibility gates remain required
when their shared client/core changes. SDK/native/browser/media and real inference
are separate following gates; no scripted durable fixture qualifies them.

## Stable result delivery and package separation

The [0043 work item](work-items/0043-stable-result-delivery-and-return-context.md)
owns the selected source gate: sixteen actual storage assertions and four actual
return assertions, 180 seconds including twenty cleanup seconds and sixteen owned
groups. P2 v8 old-surface coverage is selected outbox inspection, native bind/revoke
and current-case inspection. The eleven historical compatibility lanes keep their
original profiles; they do not establish every API on v8.

The separate result-receiver package gate has a 360-second total bound including
twenty cleanup seconds, at most 32 groups and a fixed 25-group successful schedule.
It builds fresh Python/npm archives, verifies source/archive/install payloads and
uses isolated consumers. Its eight original offline assertions and twenty copied
fake-port tests claim zero actual storage/return assertions. Require indexed final
process-group states and the exact private physical inventory. Missing indexes,
unsafe modes, incomplete closure and elapsed deadlines remain non-passing even
when individual consumers succeed. Joined RTC/voice/SMS and provider/video gates
remain separate from both lanes.
