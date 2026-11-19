# Lifecycle drains and documentation cleanup

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Preserve accepted inputs during room and application shutdown and reconcile maintained documentation with code |
| Audience | Engineers reviewing lifecycle ownership and local POC operation |
| Scope | GW-A1, GW-A2 and DEMO-A6 follow-up across existing P2/P3 joined tasks; excludes new release claims and effect retry redesign |
| Owns | This slice's contracts, failure schedules, verification and documentation review coverage |
| Related | [Code audit](0049-sdk-compatibility-and-code-review.md) · [Joined application](0045-joined-native-channel-policy.md) · [Validation](../validation-plan.md) · [Documentation standards](../documentation-standards.md) |

## Behavior and scope

Room End must fence new native input and drain original accepted inputs while
their original grant, dispatch and worker dependencies remain available. Only
then may it revoke the room capability and stop the native worker. End does not
cancel accepted business work.

Application shutdown must prepare the Parent front tier while dispatch remains
live, then quiesce gateway dispatch before closing the Parent application and
its origin listeners. The gateway's room-control and read dependencies remain
available until Parent cleanup succeeds. A single stop request must continue to
observe retained cleanup rather than require another signal to make progress.

This is corrective work within the existing P2 native lifecycle and P3 joined
application tasks. It adds no acceptance registration, business authority,
provider fallback or schema upgrade. Review every maintained document selected
by `harness/documentation.json`; distinguish current guidance from historical
qualification records. Existing accepted-state, media and provider gates retain
their scope.

### Terms used in this record

| Term | Meaning |
| --- | --- |
| GW-A1 | Gateway dispatch outliving its Parent origin dependencies |
| GW-A2 | Final accepted room input racing worker stop and grant revocation |
| DEMO-A6 | Inverted cleanup observer budgets and stalled reobservation |
| Parent | Python owner of operator, room, SMS and background application resources |
| Quiesce | Sticky dispatch admission fence followed by observation of actual dispatched calls |
| P1/P2/P3 | Durable work authority, channel continuity and delegation reliability |

### Criteria

| Criterion | Given | When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- | --- |
| GW-A1 | Live gateway and Parent origins | Stop during held dispatch | No origin closure before actual dispatch settles; no attempt consumed against a knowingly closed dependency | Cleanup completes after release with original identities | Controlled public-port schedules and actual process/store lane where available |
| GW-A2 | Final native input durably accepted | End before original prepare/dispatch completes | No early grant revocation or worker stop; unknown remains owned | Original input reaches its original operation; later room can progress | Native manager, dispatcher and Python room regressions; actual PG/media gate remains separate |
| DEMO-A6 | Cleanup outlasts an observer or a close attempt fails | One stop signal then dependency settlement | No forced exit, discarded owner or duplicate business invocation | Same retained cleanup is reobserved without a second signal | Parent/launcher cancellation, timeout and retry tests |
| Documentation | All maintained documents | Review prose, commands, links, diagrams and status against owners | Historical evidence is not promoted and qualification limits remain visible | Readers find executable commands and consistent current guidance | Per-document semantic ledger plus documentation/static checks |

## Interfaces and ownership

| Component | Path | Responsibility | Status |
| --- | --- | --- | --- |
| Parent preparation | `services/channel_policy_demo/parent.py` | Fence Parent admission and drain front owners while App remains available | Implemented |
| Native room owner | `services/channel_policy_demo/native_room.py` | Await native admission/drain before stopping worker dependencies | Implemented |
| Channel dispatcher and gateway | `projects/channel-continuity/src` | Sticky quiesce and actual retained dispatch ownership | Implemented |
| Node composition | `services/channel-policy-gateway/src` | Bind room drain and local child quiesce to current owners | Implemented |
| Joined launcher | `local-setup/scripts/channel_policy_launch.py` | Prepare, quiesce, dependency cleanup and automatic retained reobservation | Implemented |
| Maintained documentation | Paths selected by `harness/documentation.json` | Accurate current instructions and clearly labelled historical evidence | 137 reviewed |

P1 remains the sole durable execution owner. P2 retains original input, grant,
dispatch and operation identities. New local process-control observations grant
no consent, receiver authority or effect permission. No serving DDL is added.

## Failure cases and validation

Use held real coroutine owners to force the unsafe schedules before the repair,
then assert safety and progress after release. Keep actual I/O owned through
observer timeout and cancellation. A definite failed cleanup can be reobserved;
an unknown business result cannot be resubmitted under a new identity.

| Gate | Applicable and why | Exact tests/assertions | Prerequisite/resource/time bound | Expected status/artifacts |
| --- | --- | --- | --- | --- |
| G-READY | Cross-owner lifecycle correction | Criteria and owner order reviewed before coding | Local source and existing work items | This record and review messages |
| G-FAST | Shared source and documentation | Focused Python/TypeScript regressions, full fast, type/lint/format/docs | Frozen Python 3.14 and Node baseline; serial broad suites | Reports under `output/lifecycle-cleanup` |
| G-CONTRACT | New preparation/quiesce boundaries | Original current binding, repeated request, cancellation, malformed/foreign child frame negatives | Public interfaces and bounded controlled adapters | Focused reports and contract review |
| G-DURABLE | Retained accepted input | Actual PostgreSQL/process shutdown and recovery evidence | Running isolated local stack, no destructive reset | Missing setup remains non-passing |
| G-OBS | New lifecycle observation | Finite safe codes, trusted closed frames, no private payloads | Synthetic sentinel tests | Retained reports |
| G-MEDIA | Room lifecycle changes | Actual SDK/browser final-input/End and return-room journey | Local SFU/browser/media stack | Offline tests cannot substitute |
| G-PACKAGE | Affected public package interface | Isolated built-consumer smoke where applicable | Frozen artifacts and no checkout injection | Separate from source tests |
| G-RELEASE | No release promotion in this slice | Retain all unrelated open release obligations | Existing full acceptance and provider gates | Not inferred from this repair |

Do not read provider key values or invoke remote models. Normal stop preserves
state. Missing setup, skips, zero-test runners and timeouts remain non-passing.
Do not alter frozen workload or acceptance deadlines to make a gate pass.

## Results and handoff

The corrective implementation and selected verification are complete. Evidence
is retained under `output/lifecycle-cleanup`; broader release obligations remain
separate as described below.

### Implemented behavior

| Finding | Correction | Important boundary |
| --- | --- | --- |
| Dispatch could outlive Parent origins | Parent preparation drains rooms, operator HTTP and SMS before gateway dispatch quiescence; application origins close afterward | A library caller composing its own gateway must supply the same barrier before Parent `close()` |
| End could retire the final accepted input's dependencies | Fence the original bearer, observe admitted SQL acceptance, then drain original dispatch receipts before grant revocation and worker stop | P2 acceptance is separate from P1 work acceptance; End does not wait for a policy result |
| An in-flight prepare could fail when its original room began closing | A narrowly guarded same-room fallback preserves the existing claim and input through deterministic preparation | Replaced rooms, aborts, expiry and ordinary active-room SDK failures retain their rejection behavior |
| A failed close observation could leave the room stuck until another End | A retained supervisor reobserves only `cleanup_incomplete` within the original configured room budget | Actual work survives observer cancellation; terminal errors and ambiguous SFU deletion are not automatically retried |
| An unready gateway could leave quiescence waiting for readiness forever | Observe owned spawn settlement, then stop/reap a child that never published validated readiness | Absence of readiness is never fabricated into a dispatch-quiesced acknowledgement |
| Shutdown observers could expire before their dependencies | Room default/maximum 30 seconds, Parent default/maximum 60 seconds and launcher observer 120 seconds; automatic retained cleanup reobservation | These are lifecycle observer bounds, not extensions of grants, business deadlines, provider calls or frozen qualification budgets |

The trusted process-local native fence retains at most 1,024 bearer identities.
A native drain admits at most two actual owners, examines at most sixteen total
account-history rows and admits retries for twenty seconds. It matches original
provider, tenant, provider account, sender and channel identity. It reconciles
possible calls by original operation; it never clears attempts, invents a key or
grants another invocation after an unknown acknowledgement.

Current authorization still applies. Revoked or expired grants, blocked or
exhausted inputs, history overflow and unresolved external work can leave the
room visibly Closing. Neither a larger observer nor application shutdown makes
those inputs eligible. Serving adds no DDL, business cancellation or consent.

### Failure discovery and corrective evidence

The first actual joined browser attempt reproduced an incomplete End after the
original native acknowledgement. Read-only inspection found the original input
already dispatched to P1 and its binding revoked; Parent remained Closing. A
later replay of the exact original End completed in 36 ms. The failed run and
profile were retained. This exposed the missing automatic room reobservation
and an unnecessary dispatch attempt consumed by the in-flight prepare race.

After those corrections, a fresh scripted profile observed all eleven planned
browser journey stages: text acknowledgement before its P1 link, End, the
original durable link after End, dormant signed synthetic SMS, rejoin with
history, recorded voice, its durable link and advancing audio playback. End
completed in about 1.9 seconds after its acknowledged input, before any SDK
generation observation for that turn. All three inputs dispatched on their
first attempt in this run.

One stop signal while the second room remained active produced an intermediate
`cleanup_incomplete` observation, then a closed frame without another signal.
Specialist, gateway and UI each exited zero, were reaped, had absent process
groups and published validated closure. The active marker disappeared and
profile state remained intact. A pre-launch snapshot bound 474 source/artifact
files; they were unchanged at shutdown.

The Codex Desktop update then interrupted the browser controller before its
final result write. Its original running-status report is preserved unchanged;
the eleven observed stages, launcher closure and independent durable
reconciliation are recorded separately. Recovery inspection found no owned
browser process and all three exact child PIDs absent. This is selected
scripted journey evidence, not a completed frozen browser controller or full
45B/45C/45D qualification.

| Check | Observed result | What it establishes | Evidence under `output/lifecycle-cleanup` |
| --- | --- | --- | --- |
| Parent lifecycle regressions | 23 passed | Front-before-App ordering, shared cancellation-safe observers and startup failure ownership | `parent-green.log` |
| Native room regressions | 25 passed; the new supervisor schedules failed before repair | Same activation, retained owners, automatic recovery and bounded retry admission | `room-supervisor-red.log`, `room-supervisor-green.log` |
| Independent lifecycle review | No material ownership or race defect found in the reviewed repairs | Source and assertion review; fake ports remain separate from runtime proof | `p3-independent-lifecycle-review.json` |
| Supplemental actual PostgreSQL/HTTP fixture | Six scenarios passed; three independent external receipts | SQL-held acceptance fence, held possible call and lost ACK progress; revoked, expired and exhausted inputs do not invoke | `pg-native-end-result.json` |
| Fixture ownership and cleanup | Four role children exited zero, reaped with pipe EOF and absent groups; fresh schema absence independently verified | Only its own fresh schema and credential copies were removed after reconciliation | `pg-native-end-result.json` and referenced private run report |
| Default local-stack smoke | Eight checks passed with ten audio frames | Authenticated transport, stable identities, text/audio and original M1 preservation | `stack-smoke.log` |
| Fresh joined journey and stop | Eleven stages observed; controller final write interrupted by desktop update | Actual local browser/SDK, End and one-signal child cleanup within the selected schedule | `joined-attempt-2/joined-interruption-reconciliation.json` |
| Independent joined durable reconciliation | Three original P2 inputs, three P1 work/results/deliveries, two revoked bindings and zero supplier mutations | Read-only repeatable snapshot joins; each input dispatched once on its first attempt | `joined-attempt-2/joined-durable-reconciliation.json` |
| Existing PostgreSQL dispatch/gateway/process lanes | Dispatch five, gateway three, standalone two and agent one passed; zero skips and complete cleanup | Original public-port behavior and process-kill recovery after the dispatch lifecycle change | `final-integration-validation.json` and its referenced logs |
| Existing native gate | All six groups passed in 32.2 seconds, with actual PostgreSQL, LiveKit and Chromium | Durable text/recorded voice, original replay, returned media, observed SQL contention and owned cleanup | `final-p2-native.log` |
| Existing original-input integration gate | All fourteen assertions passed in 10.6 seconds across sixteen child commands | P1/P2 original joins, ACK-loss reconciliation, useful progress, current result and stale denial | `final-channel-origin.log` |
| Isolated installed-package gate | 772 application tests, 61 P3 tests and eight builder assertions passed in 81.1 seconds; all 42 process groups settled | Installed public types/exports and application fake-port behavior; no checkout injection | `installed-package-review.json` and referenced private gate report |
| Complete fast lane | 3,816 Python tests passed: P1 49, P2 125, P3 453 and root 3,189; zero skips and no structural violations | Maintained offline Python, contracts, structure and actual loopback test assertions | `final-fast.json` |
| TypeScript suites | 2,072 tests passed: console 729, channel 912, specialist 188 and gateway 243; zero skips | Four maintained package suites, separate from browser/media qualification | `final-typescript-tests.log` |
| Types, lint and formatting | Python broad 194/strict 221 files, with overlap; four TypeScript packages; 568 Python format files and maintained Prettier selection passed | Maintained quality selections; package helper rechecked after its change | `final-validation.json` |
| Catalog and M1 baseline | 55 cases, 24 registered runners validated; BASE-01 fourteen tests passed without skips | Metadata and preserved existing intake, not full product certification | `final-catalog-validate.json`, `final-base-01.json` |
| Production builds | Workspace, operations, P3 background and joined UI builds passed | Maintained production build selections; existing Vite chunk-size warnings remain | `final-validation.json` and referenced build logs |
| Documentation and diagram syntax | 137 documents checked without violations; all 53 Mermaid blocks across seventeen files parsed, with positive/negative controls | Current corpus structure/links and diagram syntax; not rendered-layout or product behavior proof | `documentation-ledger.json`, `mermaid-syntax.json` and final checker reports |

The supplemental PostgreSQL fixture uses a cooperating durable receipt port;
it is not P1, RTC or a provider gate. Its blocked cases remain blocked. The
joined observations use genuine local SDK/browser/media and real P1/P2 stores,
but do not force every disconnect, transport fault or ownership schedule.

The installed-package gate now checks the new lifecycle method declarations,
runtime exports and private installation paths without importing the checkout.
Its exact application inventory was updated from the stale room/Parent counts
to 25/23 and 772 total, with new negative count controls. Legacy probes,
assertion groups and frozen budgets remain unchanged. It does not execute the
Node gateway application lifecycle from an isolated package.

### Documentation review

The semantic ledger covers all 137 maintained Markdown files: 67 complete
reads, eighteen targeted reviews, forty-four historical-retention reviews and
eight prior-complete/current-contract reviews. These categories remain explicit;
reviewing a historical record does not rerun its assertions.

Corrections reconcile schema namespaces, implemented versus planned scope,
public API contracts, commands, ownership, shutdown order and historical versus
current qualification. The prior full PostgreSQL run with five errors is no
longer described as passing from a later targeted 27-test rerun. Existing open
release obligations remain open. The fifty-four charter acceptance rows retain
their original contents.

The earlier audit is now named
`0049-sdk-compatibility-and-code-review.md`; maintained references use that path.
The course-alignment row was removed from the documentation index. Original
machine audit paths remain unchanged so their evidence is still traceable.

### Handoff limits

No provider credentials were read or provider calls made. The work remains
local and uncommitted; no remote publication, deployment or reset occurred.
Existing unrelated local state and the two joined test profiles are retained.

Full joined 45B/45C/45D gates, complete remaining P2/P3 charter acceptance,
post-v5 provider reruns and broader model-quality evaluation remain separate
requirements. P1 post-reservation retry pacing remains the separate limitation
recorded in the earlier audit. The book retains its previous source snapshot
and was not regenerated by this repository cleanup.
