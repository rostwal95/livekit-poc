# Native committed input and delegation deadline cancellation

Status: Completed
Last reviewed: 11 November 2026

## Behavior and scope

Implement P2-I15/I16 and P3-I13 after the
[completed send-policy/action-race phase](0035-send-policy-and-action-races.md).
The [P2 task plan](../implementation/p2-channel-continuity.md),
[P3 task plan](../implementation/p3-delegation-reliability.md), project charters,
[shared design](../../Design.md) and [validation plan](../validation-plan.md)
remain authoritative. P2 contributes to P2-15 through native committed text/audio;
P3 contributes to P3-09/P3-10 through deadline and cancellation schedules.
Task completion is separate from complete charter-row registration or release.

P2 adds a separate opt-in native LiveKit composition over the existing durable
P2 input/dispatch authority. Each committed browser text message or final voice
utterance must be durably accepted before Python conversational processing or
business dispatch. Preserve native stream/utterance identity across retries;
interim transcription is observation only. Disable the competing SDK automatic
text/reply path. One stable scoped input may have repeated processing attempts
but only one original logical acceptance and operation identity. Native media,
generation, interruption, browser playback and business consent remain distinct.

P3 uses P1's existing accepted-work, issued-attempt, deadline, cancellation and
protected-action interfaces. Validate expiry before invocation and while work is
held, ignored remote cancellation, late known result retention/invalidation and
later eligible progress. Keep request, remote acknowledgement, remote outcome,
stored result and current applicability separate. Add no recovering scheduler.

Preserve the preceding checkpoint, ordinary M1 state, P1's 77 qualified runtime
payloads/README/schema/public API, image pins and default composition. Prefer
unchanged P3 runtime where existing guards already implement the contract. Any
observed production defect requires a focused reviewed fix and affected regressions.
Use installed pinned SDK versions. A new public adapter dependency edge must be
declared and checked through isolated installed consumption; changing an edge is
not permission to update unrelated versions. No paid provider or real carrier is
needed. Provider credential files are not inputs to this phase's checks.

P2-I17's complete interruption/missing-playback inventory and I18's cross-channel
room resumption remain separate slices; this phase must still run actual hybrid
browser/SDK input and returned-media checks for the behavior it implements.
Broader P3 specialist/coordinator kill recovery, document capabilities, load and
full integrated/package release retain their later phase gates.

| Criterion | Given | When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- | --- |
| Native text acceptance | Trusted fixed room/participant/account binding | A native lk.chat stream commits | Persist exact input before dispatch; reject unbound sender, changed replay and excess input | Original receipt and business operation are inspectable and current input gets a real native reply | Actual browser, self-hosted LiveKit, PostgreSQL and independent owner reads |
| One text consumer | Native SDK defaults can reply automatically | Opt-in P2 session starts and text is retried | Default text/session ingress is disabled; retry retains original identity and cannot create another logical action | One committed accepted input dispatches through the configured Python adapter | SDK positive-default control, public options, actual stream replay and call/operation counts |
| Committed voice | Bound audio track and manual committed utterance | Interim/final transcription and repeated callbacks occur | Interim or duplicate observations cannot accept another input or supply mutation consent | A final utterance uses the same durable boundary and eligible processing as text | Scripted native ASR, fixture audio over actual WebRTC and stored identity joins |
| Hybrid session | Text and voice use one trusted case/conversation | The user changes modality | Raw media remains in tracks; sender/room labels cannot override trusted scope | Both inputs retain source-qualified receipts and useful replies | Actual browser/native session and durable history |
| Media lifecycle | Premature input, denied permission, interrupted or closed session | Controls/readers or output settle | Gate readiness; bound readers/tasks/bytes/time; retain uncertain acceptance and separate playback observations | Cleanup completes and later eligible session work progresses | Boundary/unit negatives and actual scripted browser lane |
| Deadline before dispatch | Accepted work remains retained after business expiry | A runner attempts issuance/invocation | Authority time rejects new ineligible attempts with zero specialist/action call | Retained history is readable and a separate eligible work item progresses | Fake-clock contract tests and actual P1 PostgreSQL/public ports |
| Deadline during invocation | A valid issued attempt reaches an owned specialist barrier | Authority observes expiry before completion | Late strict facts remain historical/inapplicable; no new action/delivery permission follows | Independent eligible result and exact-confirmed action can progress | Held actual HTTP/process schedule, execution/result/case joins |
| Cancellation before invoke | Cancellation wins before invocation eligibility | Runner resumes | Zero new specialist call or action; original cancellation receipt remains stable | Unrelated eligible work progresses | Actual public cancellation and deterministic owned barrier |
| Ignored remote cancellation | A specialist has already begun read-only work | Cancellation is requested and acknowledged or ignored | Do not equate ACK with termination; preserve observed remote completion separately from invalidation | Known strict late result is retained without authorizing action | Actual scoped HTTP cancellation/status/invoke and independent counts |
| Caller abandonment | I/O outlives waiter timeout/cancellation | Caller leaves or close expires | Actual work retains capacity until settlement; no uncertain result becomes automatic retry | Late truth can be inspected and owned cleanup eventually completes | Unit/real I/O negative and later progress |
| Diagnostics | Failures contain sentinel secret/body/URL values | Producer emits errors/logs/metrics or telemetry fails | Fixed safe codes/fields, finite metric vocabulary; no raw payload, credential or exception reflection | Primary behavior and bounded shutdown still complete | Producer assertions and telemetry failure fixtures |
| Packaging and compatibility | Explicitly built public packages and independent consumers | Native adapter and deadline examples are installed | No checkout injection, private sibling stores, implicit DDL or undeclared serving dependencies | Actual minimal public behavior executes from the installed artifacts | Offline archive parity, isolated install and selected actual integration |

## Interfaces and ownership

P2 owns channel contracts, trusted native ingress, the Python adapter and project
tests/examples. Its existing PostgreSQL inbox and processing intent retain input
and operation authority. Native source identity and verified business binding
must be authenticated independently of text/transcription contents. Do not disguise
native events as authenticated SMS or trust a caller-constructed principal.
Use a separate opt-in composition; preserve qualified P1 service behavior.
Readiness includes the SDK's public RoomIO subscription barrier. Bound and close
custom lk.chat readers; disable the SDK default text consumer and session-host
alternate ingress. Document exact commit points, body/stream caps, pool ownership,
retry identities, capabilities and public dependency edges before qualification.

P3 owns its deadline/cancellation schedules, fixtures, public composition example
if needed and project tests/docs. Existing P1 public execution/case/action ports
own time and authority; derived metadata remains as-of evidence. Test-only owner
fixtures may inspect isolated schemas for exact reconciliation but product adapters
must not import sibling stores. Known receipts/results survive later expiry or
cancellation; no cached applicability permits a new action.

Root integration owns this work item, shared Make/discovery/policy, independent
gate-negative tests, shared guides and final source-bound evidence. Agree adapter,
browser and local setup ownership before editing overlapping files. Freeze exact
case/mode inventories, role-specific environments, resource/cleanup budgets and
source hashes before any normal qualification measurement. Preserve earlier
failures and diagnostic/nonqualifying runs separately.

## Failure cases and validation

| Gate | Applicable and why | Exact tests/assertions | Prerequisite/resource/time bound | Expected status/artifacts |
| --- | --- | --- | --- | --- |
| G-READY | New native trust/dispatch and temporal eligibility boundaries | This table, reviewed interfaces and explicit case/mode protocol snapshots | Freeze protocol before normal measurement; selected existing pinned tools | Initial plan and immutable premeasurement records |
| G-FAST | New Python/TypeScript, test and shared harness paths | make check, make frontend-check, make format-check; strict new Python paths and meaningful negatives | Frozen local dependencies; zero required skips/violations | Actual counts and raw safe command results |
| G-CONTRACT | Native ingress, reply/correlation and cancellation observations | Positive/replay/changed-body/cross-scope/unknown-field/byte-limit and source-qualified state fixtures | Strict primitive types, finite input/output buffers and exact identity | Language-consistent and public-boundary results |
| G-DURABLE | Accepted native work and deadline/cancel results | Actual isolated PostgreSQL and public authority, independent owner joins, fresh process inspect/replay and prior relevant regressions | Owned schemas/children, fixed deadline plus cleanup reserve; no ordinary reset | Nonzero named actual cases, truthful failure provenance and complete cleanup |
| G-MEDIA | New native modality and room input composition | Real browser lk.chat, fixture voice over WebRTC, acceptance-before-dispatch, duplicate negative, returned native text/audio and readiness/cleanup | Explicit local scripted fixture mode, self-hosted LiveKit, actual browser; no provider keys | Actual browser/SDK/store evidence; physical microphone and real inference remain separate |
| G-OBS | New ingress/dispatch or schedule observations | Fixed producer counters/events, secret-sentinel and telemetry-outage assertions | Fixed labels, bounded sink/task/reader resources | Safe emitted records and meaningful counter changes |
| G-PACKAGE | Python adapter and public P2/P3 consumer boundaries | Archive payload/metadata parity, isolated installs and actual public example behavior | Existing pinned third-party versions, declared dependency edges, no repository PYTHONPATH | Current source-bound wheel/npm and selected integration reports |
| G-RELEASE | Complete project/ecosystem qualification | Not closed by selected task evidence | Remaining normative acceptance rows and later phases still required | Keep complete product release pending |

Existing commands include make check, make frontend-check, make format-check,
make p2-postgres-check, make p2-send-policy-check, make p3-execution-check,
make p3-applicability-check and make p3-action-races-check, plus the selected
registered P3 lab rows and ordinary local stack doctor/smoke. New focused native
and deadline commands enter the maintained Make/README surfaces only with their
actual implementation and negative report/environment tests. Missing setup,
zero-test runs, required skips, timeouts or incomplete cleanup cannot pass.

Logs use fixed event/operation/code/outcome fields with finite numeric duration
and occupancy measurements. Preserve uncertainty in exception translation;
cancellation propagates while actual I/O retains its owner. Exclude bodies,
headers, grants, addresses, credentials, arbitrary URLs and exception chains from
logs/metrics/reports. Native generation and playback observations never become
acceptance, human acknowledgement or exact quote confirmation.

## Results and handoff

P2-I15/I16 and P3-I13 completed their selected local phase. Actual source,
isolated installed consumption, affected compatibility, full fast checks and
ordinary stack validation passed. Full P2/P3 charter and ecosystem release remain
pending; no catalog registration is added by this slice.

| Evidence | Result | Scope and limit |
| --- | --- | --- |
| Baseline preservation | All 1,029 previous artifact hashes and 607 source hashes matched before edits; the closed artifacts were independently reverified afterward | P1's 77 and P3's 30 runtime payloads, P1 README/schema/API and default runtime remain unchanged |
| Final P2 native source | Six named groups passed in 31.063 seconds, one Playwright case, 24 owned commands, one actual kill and one SQL waiter graph; cleanup complete | Browser lk.chat and committed WAV voice share two accepted inputs, two logical operations and two actual SDK replies, with zero default replies |
| P2 database/lifecycle | Populated v5 rollback, owner v6 upgrade, fresh replay, exact 26-table dump/restore/reopen and both expiry orders passed | A grant expiring while blocked prevents a NEW prepare/call; an already reserved call may finish. Historical acceptance remains readable |
| P2 Python installation | Current six payloads and raw README match wheel, sdist and rebuilt wheel; default codec imports without SDK; optional native imports/types/pip check and 55 exact copied tests passed | Synthetic SDK and loopback HTTP, distinct from actual RTC/browser proof |
| P2 npm installation | Current 78 payloads plus semantic manifest, strict public NodeNext types and seven preparation/actual stages passed | Real v6 PostgreSQL and loopback HTTP with synthetic read-only case/operation ports; original fresh-process replay adds zero prepare/operation calls |
| P3 temporal source | 18 assertions passed in 56.389 seconds; one owned kill, one actual SQL waiter graph, complete cleanup | Existing public P1 authority; producer completion time never grants current eligibility |
| P3 installed consumer | 18 actual assertions passed in 61.077 seconds from isolated current wheel/npm composition | Thirty Python runtime payloads and specialist archive retain parity; copied composition uses public APIs without checkout injection |
| P2 compatibility | 141 assertions passed across full recovery 23, routing 22, confirmation 18, outbox 24, callbacks 24 and send policy 30 | All six fresh lanes completed cleanup; an additional focused agent case passed separately and is not counted as 23 |
| P3 compatibility | 46 assertions passed across execution 12, applicability 18 and action races 16 | Three fresh actual lanes completed cleanup; unchanged registered catalog reports retain their preceding qualified scope |
| Full fast validation | 1,788 Python tests: P1 49, P2 55, P3 251 and root 1,433; no required skips or structural violations | make check also passed Ruff and broad/strict typing over 141/116 paths |
| TypeScript/build | 1,000 tests: console 392, P2 530 and specialist 78; types, formatting and builds passed | Includes 65 native browser-policy tests, one real local HTTP proxy regression and the independent 15-case dispatcher schema regression; separate native build passed |
| Harness/format/design | 45 native gate tests and 29 deadline gate tests; Python formatting of 355 files; 109 documentation checks and 28 Mermaid syntax checks passed | Invalid Mermaid rejected; diagrams retain separate semantic source review. Catalog remains 55 cases/24 registered, with 17 P2 and 14 P3 rows planned |
| Runtime preservation | Ordinary stack doctor and smoke passed eight checks and ten audio frames, preserving original M1 identity | Diagnostic transport only, with inference disabled. Read-only final audit found zero native fixture schemas and zero native lab rooms; no ordinary reset |

The P2 final report is
.local/validation/p2-native/i15-i16-final-10.json, with its same-stem artifacts.
The preceding successful native run and every failed attempt remain separately
retained. P3's selected source report is
.local/validation/p3-deadlines/i13-corrected-03.json. The phase checkpoint under
.local/validation/p2-native-p3-deadlines retains source/contract indices, package
archives, raw safe gate outputs, independent reviews and the final summary.
The selected P2 Python package is the refreshed installed 55-test tree; the earlier
51-test tree remains earlier evidence and is never relabeled. Npm installation
qualifies PostgreSQL/HTTP, while the source gate independently qualifies RTC/media.

### Preserved failures and corrections

The first P2 fixture compared a hardened null-prototype codec object with a
JSON-loaded ordinary object. An independent browser-free reproduction proved equal
serialized values; complete public-object comparisons were normalized while raw
SQL bytes and stable identity checks stayed unchanged. The subsequent expiry
schedule exposed a real missing v6 dispatcher branch: an actual diagnostic observed
UpgradeRequired with zero prepare/operation calls. The fix adds only version six
after the unchanged role/catalog/definition validation, with independent positive
and malformed-metadata regressions. Early fixture dispatch failure now races the
owned barrier and a finite timer rather than leaving an unresolved top-level await.

The Vite /p2 prefix also captured the native HTML entry. The corrected API-only
regular expression is supported by the
[official proxy contract](https://vite.dev/config/server-options.html#server-proxy)
and an actual local HTTP regression. Startup separately waits for the exact bound
participant under a 60-second precondition before the unchanged 10-second SDK
readiness/whole-start bound; six ordered monotonic milestones document what actually
happened. Timing alone is not claimed as the cause of the previous browser failure.
A further isolated browser control proved that innerText of the closed evidence
panel was empty while textContent held valid JSON. The harness now reads bounded
textContent; producer metrics from that failed run independently showed accepted
text and a completed reply. Screenshot review then corrected the stale voice hint
using known receipt/generation facts, followed by a fresh passing media run.

Earlier native attempts with cleanup reported false remain false. Controlled Vite
shutdown now recognizes its conventional encoded signal exit only after this owner
actually requested termination; an already exited nonzero process still fails.
The later zero-residual audit does not rewrite historical cleanup reports. Failure
diagnostics retain closed stages, fixed source locations, finite producer counters
and body-free browser statuses; raw private capture/configuration stays ephemeral.
A diagnostic sink failure cannot skip independent resource cleanup.

P3's initial normal run failed the fixture's projection-schema prefix guard; the
fixture was corrected to the existing public prefix without changing that guard.
The explicitly declared macOS child-environment correction, proof-schema hardening
and offline npm config preparation failure remain distinct retained records.
The final source and isolated installed runs are the only selected qualifications.
The deliberately noncooperating peer is test-only; production cancellation remains
cooperative. All nine invoke responses in the temporal proof finished at the local
HTTP server, which does not establish a human acknowledgement.

### Boundaries and next work

Native media uses the local scripted recognizer/model/voice fixtures over actual
WebRTC. It does not qualify physical microphone capture, human hearing, real model
quality, production capacity or every interruption/playback outcome. Acceptance,
SDK generation, observed playback, specialist result truth and human consent stay
separate. No provider credential file, paid inference, real carrier, publication
or remote CI was used. The declared optional Python native dependency edge reuses
the existing Agents 1.8.11 pin; all 97 resolved package versions and the pnpm lock
remain unchanged.

P2-I17 is next for complete interruption/missing-playback behavior; I18 then covers
verified current-case continuation across a new room, browser text and fake SMS.
P3-I14 is next for broader specialist/coordinator process recovery. Those tasks,
document modalities, load, remaining complete charter rows and integrated release
retain their own acceptance gates. Known late results remain immutable facts;
new action or delivery always requires current public authority.
