# Responsive native policy conversation and compact demo

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Record the plan, observed verification and handoff for the P3-I18B responsive native policy conversation and compact demo page |
| Audience | Engineers changing the P3 native policy module or the optional P3 background page; coding agents |
| Scope | Selected P3-I18B native RTC text qualification; excludes microphone, speech recognition, playback, provider runs and the final video |
| Owns | Change plan, observed verification and handoff for P3-I18B |
| Related | [Work item 0041](0041-standalone-channel-and-durable-policy.md) · [Work item 0043](0043-stable-result-delivery-and-return-context.md) · [P3 task plan](../implementation/p3-delegation-reliability.md) · [Build plan](../build-plan.md) · [Validation plan](../validation-plan.md) |

## Behavior and scope

This work item implements the next selected P3-I18B contribution to PLAN-20,
P3-02 and P3-17. A conversational agent:

1. acknowledges a real durable policy request;
2. answers a useful second question while the specialist remains held;
3. then displays the verified result.

Preserve the completed
[0041 handoff](0041-standalone-channel-and-durable-policy.md). This slice uses
one explicit standalone P3 AgentSession and a compact optional browser page. The
first actual profile uses native RTC text. Microphone, speech recognition,
playback and provider qualification retain their separate gates.

### Visual scope

Reuse the existing dark/cyan visual language.

- Keep one composer, a small connection strip and one observed-result card
  together.
- Hide setup and technical details in disclosures.
- Every displayed transition must follow a real application, SDK, transport or
  authority observation. No percentage or timer invents progress.

The current entry/case/voice/project screens were captured and inspected before
this scope was chosen. At the observed narrow viewport, setup and controls occupy
separate screens before conversation output. Current P2/P3 components need
clearer discovery while full integrated V1 remains explicitly planned.

### Terms used in this record

| Term | Meaning |
| --- | --- |
| Implementation task IDs | Such as P3-I18B; identify tasks in the [P3 task plan](../implementation/p3-delegation-reliability.md) |
| P3-I18B | The native RTC text slice of P3-I18 |
| Acceptance IDs | Such as P3-02; identify rows in the project charters |
| PLAN-20 | A work package in the [build plan](../build-plan.md) |
| Selected qualification | The gates chosen for this work item passed; it does not complete a full charter row |
| Gate names | Such as G-READY and G-MEDIA; refer to the engineering gates in the [validation plan](../validation-plan.md) |
| Real-time communication (RTC) | The WebRTC path through the self-hosted LiveKit selective forwarding unit (SFU) |
| SDK | Software development kit; unqualified, the pinned LiveKit Agents SDK, while the "RTC SDK" is the browser LiveKit client library |
| Data transfer object (DTO) | A closed, validated value passed across a public boundary |
| Application binary interface (ABI) | Here means the exact data interface that the native composition and the browser UI share |
| Remote procedure call (RPC) | A request/response call to a business service |
| HTTP Archive (HAR) | A browser network capture format; this phase needs none |
| V1 | The fixed project scope |
| M1 | The original confirmed-investigation intake data, which every phase preserves |

### Criteria

| Criterion | Given | When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- | --- |
| P3-02 selected responsiveness | One trusted positive-revision request, two immutable JSON sources and an actual held specialist | P1 acknowledges, the tool updates its SDK context, then the user asks another question | No second session, queue, schema or model-supplied authority | A useful second native answer arrives before the hold is released | Real pinned SDK, P1 PostgreSQL and authenticated specialist; parent-owned barriers |
| P3 historical applicability | Request A is running when the trusted case advances | Original A completes | Original facts and disposition remain; outdated applicability cannot authorize action | The card explains the observed result and its current applicability separately | Actual case/revision/result joins and typed card assertions |
| Cancellation ownership | SDK waiting ends or the runner times out while actual I/O remains | Another tool/read or End is requested | Original acceptance, command and actual reservations remain; no business cancellation or new invocation | The reserved read lane can inspect, and later settled facts remain available | Held cancellation, internal-timeout and useful-progress controls |
| Scoped compact read | An authenticated configured reader for this exact work | A bounded read completes or fails | No browser-selected scope/URL, raw policy body, invented case timestamp or authority badge | Actual result/disposition/as-of applicability appear in one card | Closed wire decoder, identity/size failures and real browser read |
| Resource close | The session, run and readers own pending operations | End/Forget/close and explicit cleanup retry occur | Waiter completion alone never releases ownership or shared dependencies | Actual settlement permits complete close and later use | Public pending counts, retained tasks and independent resource observations |

### Authority and deferred scope

P1 remains the sole durable acceptance, issuance, deadline, cancellation and
result owner. Keep v1 public defaults, and keep v2 projection/completion/action
unsupported. Native case revision 0 remains read-only. These follow separately:
P2 durable native intake, cross-channel A/B dormancy/SMS/result routing, broader
load/platform release, real-model runs and the final video. No dependency version
updates or remote CI.

## Interfaces and ownership

### Native policy module

Add one P3 public native_policy module and a configured example.

- NativePolicyAgent has one model-argument-free policy tool.
- Trusted construction supplies the frozen positive-revision request, original
  command, coordinator and runner.
- Exactly two immutable evidence sources remain validated by the existing v2
  runner.
- Configure this application runner with two slots: one run and one concurrent
  read. Preserve the runner's existing default of one.
- Do not patch P2NativeRuntime: it owns a separate agent and deliberately
  generates with tools disabled.

### Tool ownership and cancellation

The tool awaits actual P1 acceptance before ctx.update(..., silent=True).

- Retain at most one application-owned run_once task and shield it from SDK
  waiter cancellation.
- SDK CANCELLABLE adds its own get-running/cancel lifecycle tools. They stop
  waiting and never call P1 business cancellation.
- A done wrapper task may still hide pending runner I/O. Release application
  admission only after its task is settled and the public runner/coordinator
  pending counts are zero.
- Later calls inspect the original work. They do not create another task or
  command.
- Abandoned submission/read ownership stays retained until public settlement.

### Observation DTO

NativePolicyObservation is immutable and serializes to at most 4,096 UTF-8 bytes.
It exposes only actual public request/work/attempt/result, original disposition
and applicability fields. Application read completion time is labelled
separately. There is no fabricated current-case revision, case observation time or
atomic snapshot claim. No raw source body or arbitrary exception text belongs in
it. The exact closed DTO, safe-code set and host ABI must be reviewed before
source and browser qualification is measured.

### Optional browser page

The optional p3-background.html owns its P3 room/selected-agent/readiness adapter,
not P1 business RPCs or P2's native runtime.

- Use the proposed fixed authenticated POST /v1/p3-native/session and
  GET /v1/p3-native/observation boundaries.
- The server fixes scope/case/work/room/profile. RTC credentials grant no
  privileged read or worker authority.
- Keep tokens in memory only and clear the input after use.
- One actual observation request may run beside the background execution. Never
  queue overlapping reads.
- Initial input is text. Add audio controls only with corresponding implemented
  readiness, ownership and actual evidence.

### Ownership

| Owner | Owns |
| --- | --- |
| P3 | Product/runtime and Python tests |
| Console | Console state/room/panel/CSS and browser tests |
| Root | Shared discovery, build wiring, this work item and thin actual orchestration |

Reuse the current grouped-process, package, bootstrap, media and private-capture
helpers. Keep installed product consumers independent of checkout product imports
and the P2 runtime. The Python runtime inventory advances from 36 to 37. P1
runtime 77, TS 14/npm 32 and dependency resolution remain held unless an
independently reviewed necessary change exists.

## Failure cases and validation

### Frozen schedule

The frozen actual schedule uses four sequential applications and SDK sessions in
one consumer process:

1. known result;
2. retained timeout/close;
3. historical result after case revision;
4. useful current work.

At most one is active. Only the historical case owns a local RTC room, HTTP host
and browser. The existing trusted bootstrap creates two preparatory case/task
rows, including its separately cancelled case. Four original native requests
create four work, issuance, result and feed records. No business cancellation,
delivery, action or supplier mutation is introduced.

Each case uses one separately owned Node peer with one physical invocation.
Setup, UI build, source copies and browser readiness precede its held-call
critical path. The existing specialist invocation ceiling stays five seconds. The
retained case uses a one-second runner observation deadline and a 100-millisecond
close observation; late settlement is awaited before shared resources close. No
raised transport or lease limit substitutes for responsiveness.

### Command groups and ceilings

| Limit | Value | Applies to |
| --- | --- | --- |
| Command groups | Eleven: specialist compile, public types, UI build, owner setup, one SDK consumer, four Node peers, one browser and owner cleanup | Source mode |
| Command groups | Adds four direct setup groups and seventeen nested package-builder groups, for thirty-two total | Installed mode |
| Offline package assertions | Remain eight, separately | Installed mode |
| Total ceiling | 180 seconds, including twenty seconds for cleanup | Source mode |
| Total ceiling | 360 seconds, including twenty seconds for cleanup | Installed mode |
| Capture | 64 KiB per capture stream and 2 MiB aggregate | Both modes |

The twelve backend assertions, three browser groups and eight installed package
assertions are reported separately.

Measured outcomes for this frozen schedule are recorded below.

### Backend/SDK assertions

The twelve backend/SDK assertions are:

| # | Assertion |
| --- | --- |
| 1 | Trusted positive revision and two sources |
| 2 | One SDK session |
| 3 | Acknowledgement before pending update |
| 4 | Held remote with no result |
| 5 | Useful second turn plus concurrent read |
| 6 | Original verified result |
| 7 | Zero-write replay |
| 8 | Stale historical result |
| 9 | Foreign/malformed denial |
| 10 | Retained waiter/internal-timeout ownership |
| 11 | SDK interruption/cancellation separation |
| 12 | Incomplete-close retry with useful later progress |

Include the counterexample where run_once has returned but runner.pending_count
remains one. A new evaluation must reject before stealing the read slot or making
another HTTP call.

The foreign/malformed assertion executes public constructor/DTO probes in the
installed consumer before entry: zero revision, foreign evidence scope and an
invalid observation. Exact submit/cancel/issue/complete/invoke counters stay zero.
These are contract-rejection controls; they do not claim a PostgreSQL cross-scope
authorization experiment. Existing authority isolation retains its separate gates.

### Browser layout checks

The optional page defers its RTC SDK import until explicit Join, within the same
retained join owner. Short-screen review found the composer below the fold at
1,280 by 720; the corrected desktop spacing keeps the entire composer visible. The
browser gate checks that layout and font readiness before Join. It then restores
its declared main viewport before the five-second held invocation. Visual captures
and unit checks retain their narrower scope; actual native text journeys passed
separately as recorded below.

### Gates

| Gate | Applicable and why | Exact tests/assertions | Prerequisite/resource/time bound | Expected status/artifacts |
| --- | --- | --- | --- | --- |
| G-READY | Native composition and UI share an observed ABI | Reviewed DTO, identities, roles, ownership, literal cases and child schedule | Freeze before actual measurement; scripted and provider-free | Exact manifest and source binding, no invented result |
| G-FAST | Public module, UI and shared discovery | Full make check, frontend-check, format-check and documentation check | Existing pinned offline toolchain | Nonzero suites, no required skips; current source review |
| G-CONTRACT | Public Python and browser boundaries | Immutable bounded DTO, safe errors, positive/zero/foreign identity, token/late-read fencing | Pure tests and strict consumers | Invalid input discloses nothing and invokes nothing |
| G-DURABLE | Real P1 result and cancellation semantics | Twelve declared backend/SDK assertions with independent original identities and rows | Source 180 s/installed 360 s including 20 s cleanup; source 11/installed 32 command groups; four sequential apps as specified above | Actual held/result/owner proofs; no mock-only durability claim |
| G-PACKAGE | New public module and configured example | Existing separate offline-eight builder plus fresh installed native consumer | Python 37/P1 77/npm 32 inventories; no checkout product fallback | Current archive parity, strict types and executed public example |
| G-MEDIA | Native RTC text and browser result view | One room/session/work/browser journey: accept, held follow-up, result, read-failure/retry and End/Forget | Actual local SFU and selected AGENT readiness; fixture inference | Native text/DOM observations only; audio/model quality not inferred |
| G-OBS | User needs truthful failure and ownership | Finite safe logs, actual active/pending counters, telemetry failure containment and sentinel exclusion | No raw prompts, source bodies, tokens, URLs or dependency exceptions | Logging failures never change acceptance or release actual capacity |
| G-RELEASE | Broader ecosystem remains active | Full charter, integrated voice/text/SMS and provider/video evidence | Separate following slices | Missing/skipped/timed-out work stays incomplete |

### Close and cleanup rules

- Close admission first. Retain bounded SDK close and actual call observers.
- Attempt independent coordinator/runner closes even when another close observer
  fails. Observe their successful public closure before shared case/model/room
  removal.
- End and Forget affect conversation/UI ownership, not durable work cancellation.
- Forget clears private display data immediately and fences late callbacks. A new
  Join waits for actual prior cleanup.
- Preserve failed first runs and exact scoped cleanup. Never reset unrelated state
  or the original M1 fixture.

### Observability, UI and engineering rules

- Use fixed safe event/code/status fields and numeric local counters, with bounded
  safe correlation only where existing observability rules permit.
- Keep SDK waiter completion separate from owned run/read reservations and facade
  pending gauges.
- Use typed public Python boundaries, cancellation propagation and explicit units.
  Transactions remain short, and network I/O stays outside them.
- Validate dynamic text and render it with textContent.
- Verify keyboard composing, status announcements, reduced motion and
  narrow/desktop reflow. Screenshots require empty password fields.
- No video, trace or HAR is needed for this phase. The final user-authorized
  sanitized video is a later deliverable.
- Keep final Design.md updates within the standard sections, and distinguish
  implemented producers from planned ones.

### HTTP host bounds

| Limit | Value | Applies to |
| --- | --- | --- |
| Application handlers | Four | HTTP host admission |
| Retained observation calls | One | HTTP host admission |
| Headers | At most 32, each bounded by 2 KiB | HTTP host transport |
| Request line | 2 KiB | HTTP host transport |

These are configured bounds, not a global connection-capacity claim.
Origin, bearer, empty-body and closed JSON checks remain independent. A real
Chromium control established that its normal eighteen-header POST needs this
bound; thirty-three headers still fail before application admission.

## Results and handoff

Selected P3-I18B native RTC text qualification is complete.

- One model-argument-free tool acknowledges real P1 work, releases the SDK
  foreground and retains its actual background owner.
- A useful second answer arrives while the authenticated specialist is held.
- The original result remains distinct from current-case applicability. The
  browser observes the original result as outdated after a trusted case revision.
- No business cancellation, delivery, action or supplier mutation is introduced.

| Gate | Observed result | Evidence and limit |
| --- | --- | --- |
| Source native journey | 12 backend/SDK assertions and 3 browser groups passed; 11 process groups; 30.263 seconds; complete cleanup | .local/validation/p3-native-policy/i18b-source-second-02.json and its sibling artifacts directory |
| Isolated installed journey | 12 backend/SDK assertions and 3 browser groups passed; 32 total groups, comprising 15 direct and 17 nested builder groups; 88.702 seconds; complete cleanup | .local/validation/p3-native-policy/i18b-installed-first-01.json and its sibling artifacts directory |
| Package assertions | 8 separate offline assertions passed within installed mode | Fresh P1/P3 wheel, source/rebuilt archive and npm parity; P3 runtime 37, P1 runtime 77 and npm 32 payloads, with npm manifest separate; isolated public imports and configured example execution |
| Shared code checks | 2,590 Python and 1,580 TypeScript tests passed, with zero required skips; mypy 151 broad/161 strict; Ruff 443 files | Full make check and make frontend-check; optional page included in maintained formatting, typing and build discovery |
| Documentation/design | 120 documents passed structural/link checks; all 41 Mermaid bodies across 11 designs passed syntax parsing | Standard design sections retained; Mermaid syntax does not independently prove architecture meaning |
| Final preservation | Ordinary local stack ready; no selected disposable schemas or RTC rooms remain; original M1 public row unchanged | Separate read-only local-state audit; no provider/private-CA reads or calls in these gates |

### What the runs showed

The four sequential consumer applications retain four original work records,
issued attempts, verified results and feed events. Existing setup creates two
preparatory case/task rows, including a separately cancelled case. The selected
runs record zero work cancellation commands, result deliveries/actions and
supplier calls.

The retained case proves three things:

- a done wrapper with pending I/O still owns capacity;
- a concurrent read remains usable;
- explicit later close can observe actual settlement.

Replay preserves the original identity with zero new submit/issue/complete/invoke
calls. Pre-entry invalid-revision, foreign-evidence and malformed-DTO controls are
contract rejection, not a cross-scope SQL experiment.

### Commands

Run the maintained commands from the repository root:

```sh
make p3-native-policy-plan
make p3-native-policy-check
make p3-native-policy-package-check
make p3-native-policy-build
make check
make frontend-check
make format-check
.venv/bin/python -m harness.documentation_check
```

The actual gates require the ordinary local PostgreSQL and LiveKit services,
restricted roles and managed Chromium. The frozen source/installed ceilings remain
180/360 seconds including twenty cleanup seconds. A reported duration or sampled
local run does not establish production capacity. Inference is scripted; this
profile qualifies neither audio, speech recognition, model quality nor provider
calls. Packaged guides remain qualification-neutral and point to this handoff.
The verified archive bytes were preserved after qualification.

### Reviewed failures and corrections

#### First source run

The first actual source run failed during browser opening after 32.994 seconds
and granted zero of twelve assertions. Its report remains failed with
cleanup:false at .local/validation/p3-native-policy/i18b-source-first-01.json.

- All ten recorded groups ultimately settled. A separate read-only audit verified
  that no selected fixture schemas/rooms remained and M1 was unchanged.
- Cleanup had re-drained already closed, accounted process handles. The corrected
  path skips that drain while still closing/capturing every owner. The maintained
  regression covers accounted, unaccounted and repeated-close paths.
- The original failed flag was not rewritten as a pass.

#### Header limit

An aligned Chromium control independently reproduced eighteen normal headers
receiving a plain-text 400 from the former sixteen-header host. With the bounded
thirty-two-header fix, the same control received 200 JSON/no-store; its browser,
process group and host closed completely. The HTTP regression covers
eighteen-header success and thirty-three-header rejection.

Original-run attribution remains an inference because its raw wire and exact
consumer exception were not retained. The initial intercepted browser control
changed header behavior and asserted before retaining observations; it remains
nonqualifying. The lost stale input from the first normal run is not reconstructed
as original evidence.

#### Diagnostics and scaffolding

Bounded, canonical, token-scanned original native inputs are now retained before
peer startup for diagnosis. Full public request validation precedes specialist
invocation, and complete input/result/authority joins precede any passing
assertion. Early diagnostic retention itself does not certify the embedded
request.

- Initial shared checks also exposed one missing test-owner declaration and three
  regression-test lint findings. These were corrected before the passing shared
  run.
- A private evidence-assembly status-label assertion failed before the first
  normal run; it produced no successor freeze. The original protocol/roles were
  unchanged, and the second source/installed runs used a new verified freeze.
- These scaffolding failures and their original logs remain separate from product
  qualification.

### Review, UI and remaining work

#### Independent review

Independent review:

- rehashed every retained entry (63 source and 146 installed);
- recomputed all eight canonical input/evidence/result and owner-SQL joins;
- inspected wheel RECORD/archive payloads;
- checked actual SDK/room/process closure.

No selected-scope blocker remains. Sources before/after each successful run match
all 232 measured files; the external freeze also binds the root package manifest.
Source and installed browser records show zero page errors and external requests.
Desktop/mobile/Forget captures were inspected after empty-password assertions.

#### UI observations

The optional page uses one composer, connection strip and observed-result card.
Its initial JavaScript is approximately 30.6 kB, with the approximately 532.2 kB
RTC SDK loaded only on Join. This defers transfer rather than reducing the entire
SDK. The short-desktop layout keeps the complete composer visible at 1,280 by 720.
The card exposes execution/result metadata and outdated applicability.

- Showing the original policy conclusion and its seven-day rule/ten-day witness
  directly in the historical card is a following showcase improvement.
- A visible skip link in the retained full-page keyboard capture needs an
  actual-viewport check in the next journey. It does not invalidate these selected
  text/ownership assertions.

#### Next frontier

The next coherent frontier is P3-I19/P2-I22 integrated return routing:

- accepted P2 voice/text;
- held policy work;
- actual room A closure;
- authenticated signed SMS against P1;
- a fresh B interaction receiving only its explicitly accepted current result
  while A remains historical.

It needs typed policy-v2 delivery/read composition and the P1-to-P2 receiver
adapter. Keep P2's tools-disabled generation boundary, revision-zero read-only
behavior, explicit new commands and P1's sole durable authority. Do not substitute
another standalone page for that integration.

Broader voice/provider/load/platform gates and the requested final live video
remain unfinished. Fourteen full P3 and seventeen full P2 charter rows remain
planned; the catalog stays at fifty-five definitions and twenty-four registered
runners. The broader ecosystem goal remains active.

Implementation and tests were AI-assisted, with separate source, evidence and
rendered-capture reviews. Portfolio claims must stay within the inspected scope
and remain explainable from the public interfaces and retained observations.
