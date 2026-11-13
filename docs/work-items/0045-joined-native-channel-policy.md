# Joined native channel and background policy application

Status: Active
Last reviewed: 13 November 2026

## Behavior and scope

Compose the qualified P2 native intake/rehydration, original-input policy-v3 and
P2 result-receiver seams into one locally runnable synthetic travel-support
application. This contributes to P2-I22, P3-I19/P3-I22, P2-09/P2-12/P2-15 and
P3-02/P3-12/P3-17. It does not replace the remaining charter/release requirements.
The full goal still includes provider-backed runs, broader restart/scale evidence,
clean documentation, independent review and a recorded working demo.

P1 remains the case/work/issuance/result/delivery authority; P2 owns input,
association, prepared bytes and communication receipts; P3 verifies factual
results and applicability. One P2 NativeRuntime owns the SDK session in each
current room. End closes media, not durable business work. A separate bounded
application executor continues while no room is present. Existing standalone
pages and default P1/M1 behavior stay compatible.

| Criterion | Given | When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- | --- |
| Original accepted input | Current trusted native grant or signed local SMS input | Durable P2 dispatch reaches the origin bridge | Preserve original event/receipt/op/digest/UTF-8 bytes and deterministic P1 key; no fake SMS identity for native input | The actual P1 work UUID is discoverable through persisted P2 dispatch evidence | Actual PG/API joins and codec/scope negatives |
| Responsive conversation | One issued policy call is held briefly | Another text question arrives | No synchronous DB/specialist work blocks the conversational event loop | A fresh native reply arrives while the work remains observably pending | Actual RTC text and independent issued-work barrier |
| End and return | Native room A is closed independently | Signed simulated SMS is accepted during dormancy, then room B joins | No old-room credential/control or late callback can disclose B's result; End grants no cancellation | Work/result persists without a room; B reads only its scoped current result | Actual browser/audio, server participant observation and source/work/receiver joins |
| Stale result | A result belongs to case revision 1 | Explicit authenticated case revision advances to 2 | New delivery of A is denied before a delivery intent; speech/playback never confirms a mutation | New current work B progresses and yields a verified result | Separate deterministic stale-A/useful-B scenario |
| Restart discovery | Accepted original work or a known result already exists | Application executor is restarted normally | No process-memory queue/cursor owns acceptance; never skip unknown/pending gaps or force re-invocation with new identities | Bounded reread of persisted P2/P1 records rediscovers accepted or completed work | Actual independent process restart with exact original receipts |
| Ownership and diagnostics | HTTP, factory, SDK, reader or close is held/fails | Timeout, abort, End or shutdown occurs | Retain actual tasks/slots/sockets and primary error; withhold dependent closure/removal until settled | Explicit close retry permits the next useful interaction | Pure/fake lifecycle plus actual held-I/O and media checks |

## Interfaces and ownership

The new root application belongs under services/channel_policy_demo with a
standard AGENTS.md, README.md and Design.md. Runtime composition imports only
public P1/P2/P3 APIs; local-setup remains owner preparation and orchestration.
Promote the already qualified origin wire/service/HTTP composition into this
application with compatibility entrypoints for existing local gate tooling.
Do not import test fixtures or private P1 stores from serving code.

| Boundary | Contract and owner |
| --- | --- |
| P2 prepared-input read | Add a typed public readPrepared(accountToken, receiptId) to the existing dispatcher/store. It returns the original PreparedDispatch, or null only for a known authorized input without a plan. Missing/foreign rows preserve NotFound/AccessDenied; corrupt plans preserve SchemaMismatch/OperationConflict. Use the existing read-only transaction/row/plan validators, never binding reassociation, a case/model call, claim or dispatch. Known history remains readable after native/source revocation without granting new acceptance. No table/version change. |
| Bounded discovery | Trusted Node composition pages ChannelInbox.history and reads ChannelDispatcher.inspect. Native and SMS have separate integration-scoped dispatcher/readPrepared owners; choose only through a validated stored provider/event binding, never client-selected source. Delegate prepared reads through the configured gateway rather than reaching into its private dispatcher or constructing fake ports. One configured case/conversation, at most sixteen retained inputs, one page of at most sixteen entries per read. Enforce the sixteen-input profile cap in owner settings and fail explicitly on overflow/nextCursor; never silently omit later work. Continue examining later entries past a pending/uncertain gap. Never persist a terminal watermark over those gaps. |
| Discovery HTTP | Separate worker bearer bound in trusted construction. Closed version-1 list returns input/op/current dispatch state and nullable actual P1 work UUID, bounded cursor and source metadata. A separate prepared-frame read returns exactly the existing accept frame as its raw known-200 JSON body, with a distinct finite no-plan response and the existing independent 32768-byte framed cap. It adds no second wrapping layer or duplicate parsed body. Neither endpoint accepts body-selected scope. |
| Python executor | Fixed booking.evaluate_policy capability only, one executor process and at most two actual job owners. One stable logical app-owner UUID is persisted in private owner configuration and reused for per-job runners; each work uses command cp45_ followed by its work UUID hexadecimal. Normal restart reuses both identities only after the old process is reaped. Validate original P2 source/frame against the full public P3/P1 stored origin before invocation. Use current public case authority, the winning request's allowlisted immutable evidence pair and existing P1 issuance. Each per-job runner owns separate execution/specialist clients; its app slot stays retained until actual pending work and dependent close observers settle, even when run_once's waiter has timed out. Reconcile unknown outcomes through reads; do not create another queue, lease system or result ledger. |
| Specialist | Existing bounded TypeScript policy-v2 HTTP and independent factual validation. The outer request/result stays v3; the unchanged specialist contract stays v2. Scripted rules are labelled. No model, tool or transcript grants mutation authority. |
| Result delivery/read | Use existing receiver-bound P1 delivery and P2 ChannelResultReceiver. Trusted current-read route links the original input/work/result/intent/receiver and calls ChannelResultReader.native with the current grant. Browser input cannot choose scope or substitute a grant. Resolve the delivery ID through public P3 delivery inspection. Distinguish no delivery, no currently applicable result and failed read; never disclose stale result bytes through a newer grant. |
| Native lifecycle | Reuse P2 NativeRuntime manual text/voice input, committed final-turn identities, prepare ownership, communication capture and current-grant rehydration. Keep SDK default text consumption and SessionHost disabled. No second NativePolicyAgent/AgentSession. |
| Case revision | Closed version-1 expectedRevision decimal plus typed BookingChange, fixed task/case and a separate controller capability; call public CaseControlClient.revise. A failed revision ACK remains explicitly uncertain, without fabricating a command receipt. CurrentCaseHttpClient is read-only. Investigation consent remains distinct from exact quote confirmation. This slice creates no supplier mutation, automatic approval or policy-result action. |
| Local packaging/setup | Declare the root app's P2/P3/native runtime extra; existing dev dependencies do not establish container availability. Use frozen compatible versions, explicit owner setup, stable ignored private configuration and runtime-only credentials. Normal stop preserves PG state; reset is separate. |

Transient room/task/cache state is bounded observation only. Process restart
resets the discovery scan and revalidates P2/P1 truth. This phase's normal restart
proves accepted-not-issued and already-completed cases; arbitrary death during an
issued attempt retains its explicit lease/reconciliation gate rather than a
fabricated completion. Retained inputs at capacity remain readable/replayable.

Freeze the exact process/role and resource inventory before each actual gate.
Preserve native prepare's four-second limit, specialist HTTP's five-second limit,
runner's ten-second ceiling and original-origin sixty-second proposal window.
Do not widen them to stage a long demo. Use separate short held-work cases: release
one after a useful reply; release the End case as soon as room A is independently
absent. A long dormant/SMS/B journey must not hold one HTTP invocation indefinitely.

## Failure cases and validation

Implement and qualify the following phases in order. Missing/skipped/timed-out
assertions stay incomplete; no product catalog registration is added prematurely.

| Phase/gate | Concrete change | Required assertions | Evidence and exit |
| --- | --- | --- | --- |
| 45A: contracts and ownership | Root service skeleton/design; promote qualified origin composition; public P2 prepared read; closed scoped discovery/current-result wires and bounded executor ports | Positive/negative schema, scope/identity/digest/UTF-8 and large-frame cases; no read mutation; safe finite errors; import has no I/O; held factories/calls/close retain ownership | Focused Python/TS tests, strict typing, existing fourteen actual origin assertions after promotion, affected package checks and independent API/failure review |
| 45B: actual backend composition | Explicit owner setup plus runtime Node gateway, Python origin/executor and stable receiver/current reader | Persisted P2 discovery, replay/conflict, actual P1 issuance/result, stale-A denied/current-B delivered, signed SMS provenance, accepted/completed normal executor restart, useful progress and incomplete close | Fresh isolated PG/HTTP/process gate, frozen numeric budgets and complete independent SQL/source/receipt oracle; actual groups reaped before DDL |
| 45C: compact UI and native media | Separate opt-in page/build; one P2 native room owner; conversation, Voice/Text controls, local SMS simulator, current case and one verified result card | Real text/WAV voice, useful follow-up while held, interruption distinct from cancellation, End/dormancy/SMS/B current result, stale callbacks/grants denied, keyboard/reduced-motion/mobile usability | Actual self-hosted SDK/Playwright media, selected-track playback and fresh reply; screenshot-first visual audit; no fake timed progress or physical-hearing claim |
| 45D: reproducible app and handoff | Documented app launch/stop, explicit packaging/container profile and scoped installed repetition | Public installed imports, correct runtime extras, actual normal restart/state preservation, no token/provider data in browser storage/logs/artifacts, all owners settled | Fresh installed/app evidence distinct from source; affected regression and full-fast/doc checks; clean independently reviewed handoff |

Current preserved regression entrypoints include make channel-origin-unit,
make channel-origin-check, make channel-origin-package-check,
make p2-result-receiver-check, make p3-native-policy-check and the selected P2
native/rehydration lanes. New application commands are proposals until their
asserted implementations exist. The phase freezes their actual role inventory,
deadline, byte/slot/stream caps and cleanup budget before measurement.

Logs use finite operation/code/outcome and bounded safe correlation, with one
translation at HTTP/app boundaries. Do not log text, tokens or dependency error
messages. Metrics record numeric accepted/dispatched/issued/stored/delivered/
unknown/stale counts, active slots, scan/call duration and cleanup outcomes with
finite labels. Exporter failure cannot block acceptance. UI transitions follow
validated observations; execution, applicability, delivery and client playback
are separate facts. IDs, full histories and trace detail stay in disclosures.

Selected provider-real integration follows through the trusted existing provider
configuration and separately versioned native mode/readiness/usage contracts.
It must not relabel the scripted native adapter. Final recording is a separate
bounded credential-free capture after source/media/provider qualification, with
scripted input/synthetic supplier/SMS labels and reproducible commands.

## Results and handoff

### 45A qualification passed

The contracts/read/ownership subphase is qualified. This work item remains Active:
45B, 45C and 45D, the broader P2/P3 release gates and the recorded demo remain.
No complete product acceptance registration was added.

| Gate | Measured result | Scope and retained report |
| --- | --- | --- |
| Canonical origin source | Fourteen assertions, sixteen process groups, 14.288 seconds, zero skips, cleanup complete | .local/validation/p2-channel-origin/phase45a-final-fourth-04.json |
| Public prepared read | Eight assertions, five process groups, 2.524 seconds, zero skips, cleanup complete | .local/validation/p2-prepared-read/phase45a-prepared-first-01.json |
| Root application artifacts | Thirty-two process groups, 130 selected installed app tests, 62.855 seconds, cleanup complete | .local/validation/p2-result-receiver-package/phase45a-root-application-second-02.json |
| Shared Python | 3,007 tests: 49 P1, 113 P2, 436 P3 and 2,409 root; zero required skips or violations | make check; broad typing 160 sources, strict typing 184 sources |
| Shared TypeScript | 1,732 tests: 622 console, 882 P2, 179 specialist and 49 gateway; zero required skips | make frontend-check PNPM=pnpm; formatting, strict types and builds passed |
| Documentation and compatibility | 129 maintained documents, 495 formatted Python files, 47 Mermaid bodies across thirteen designs; invalid syntax control rejected | Documentation checker, offline syntax parser and make format-check |
| Existing local stack | Doctor ready; eight smoke checks and ten received audio frames | Existing scripted transport only; original M1 identity/state preserved |

The actual source oracles independently replay saved full bundles. Their 224
origin and 223 prepared-read source bindings matched current inputs at audit.
The prepared gate compared all thirty tables and actual owner/runtime SQL roles,
relation OIDs/blockers and the private-launch native bearer digest; it issued no
P1 business call. Both source gates had zero provider/RTC/carrier/supplier effects,
reaped all groups before DDL and removed only their owned successful work trees.
Independent read-only checks found the disposable namespaces absent and the
original M1 record unchanged.

The root package lane checked 439 source bindings, 52 runtime payloads and nine
P2 Python payloads. Direct and normal-sdist rebuilt root wheels matched member
bytes and RECORD. The 190-file source archive included 129 default raw test
sources; only the seven selected raw app suites were executed in this installed
lane. Their counts are thirteen wire, eighteen origin service, nineteen HTTP,
two composition, twenty-two discovery, twenty-four current-result and thirty-two
executor tests. Twenty-three raw consumer inputs were unchanged. Actual SQL,
RTC and provider assertions remain zero in this package lane; its existing eight
P3 offline assertions and sixty-one P3 fake-port tests retain their separate scope.
All thirty-two process groups and temporary consumer/prefix paths were independently
observed absent after cleanup. An author audited retained package evidence with
that authorship disclosed; separate non-author reviews covered the implementation
and final selection/counter delta.

Reviews corrected concrete failure cases before closure: fresh invalid runner
quarantine, useful later-work admission through advisory rotation, allocation and
factory cancellation ownership, finite exception copying without dependency
accessors, canonical UTC dates, strict prepared revisions and trusted method
snapshots. Actual HTTP tests cover four held handlers, two retained source reads,
eight-plus-one socket admission, partial-header expiry, startup recovery and
listener/handler/socket closure ordering. The HTTP transport borrows the source
reader; it drains first, then the reader drains retained P2 I/O, then P2 owners
close. No wrapper confuses one tier's completed waiter with all dependent work.

Earlier failed observations are preserved. The first promoted source run exposed
millisecond rounding in the verifier; exact integer truncation fixed it without
runtime changes. The first shared fast run stopped at the empty required type
marker; adding its explicit PEP 561 comment satisfied the existing structural
rule. The earlier 126-test installed package is historical after four cancellation/
finite-error regressions were added; the fresh 130-test run qualifies current code.
No old report, archive, index or completed checkpoint was rewritten.

Supported component commands now include make p2-prepared-read-plan,
make p2-prepared-read-unit, make p2-prepared-read-check, make channel-policy-unit,
make channel-policy-package-plan and make channel-policy-package-check. Plans are
inert. Actual gates need the documented local services and frozen interpreter;
package checks use offline cached artifacts. The phase retains one selected
private closeout with raw evidence and current source bindings. Machine evidence
owns code identifiers; prose makes no upstream contribution, production-capacity
or complete portfolio-ownership claim.

### 45B implementation in progress

The next coherent slice composes the actual public clients behind the qualified
ports. It contributes to the same P2-I22/P3-I19/P3-I22 requirements; no complete
charter registration is added before its full assertions exist.

| Component | Implementation boundary | Required safety and useful-progress checks |
| --- | --- | --- |
| Worker read client | One fixed profile/route and loopback bearer; at most two actual socket/read owners; separate borrowed discovery/prepared adapters | Strict real response bytes and scope, explicit no-plan status, no retry, abandoned waiter and late connection/close ownership |
| Origin publisher router | Two configured native/SMS facets; at most two actual temporary call owners globally | Attest original P2 plan before trusting sender, preserve known winner after template change, reject wrong role/scope/bytes, unique coordinator/service ownership |
| Node application | Two public gateways, one native/history inbox, result outbox/receiver/reader and the bounded source/HTTP readers | No serving DDL or fake read ports; thin public dispatch inspection; ordered actual startup/drain and public source/receipt joins |
| Job factory/adapter | Two global tickets spanning partial construction, execution, guarded delivery and close | Original immutable evidence, stable owner/command, no supplier action, stale denial distinct from stored execution, partial/factory cancellation remains owned |
| Actual runtime/setup | Explicit public owner bootstrap, fixed ignored configuration and separate runtime principals | Persist accepted input/work/result through normal restart; no new execution queue, database ledger or changed original deadline |

Two canonical publisher listeners have an aggregate eight-handler/sixteen-socket
bound; the global origin resource pool remains two. Node's native, SMS, read and
receiver listeners have separate declared bounds. The actual gate freezes the
complete process/socket/byte/time inventory after the serving interfaces exist
and before measurement; the current table is not an executed gate.

A stored eligible-at-commit result can later be expired. Current native result
production must validate original source/work/result/delivery joins, use current
P3 applicability and compare the current P2 case observation before exposing any
body. Long dormancy must show honest inapplicability and useful new work, never
renew an old deadline or silently create a refresh operation. The separate
historical-body policy is not part of this slice.

### Component implementation checkpoint

The worker client, two-facet origin router, guarded jobs, canonical case/receiver
transports, public startup factories, private owner profile and Python application
owner are implemented. Focused reviews corrected final-read identity validation,
partial client ownership, pre-delivery original-request checks, supported policy
configuration, private-file races and finite task-allocation errors. Retained
failed observations remain unchanged. The Node application has nine owned
resources; its runtime/operation bridge and both explicit serving entrypoints
passed their component checks. The optional native room owner is a later
application integration.

The root channel-demo extra declares its direct aiohttp and h11 dependencies at
the existing pinned versions. Offline lock refresh preserved all ninety-seven
resolved package versions. New sources/tests are registered in strict typing,
foundation checks and the joined unit target. Expanded installed coverage and
full shared validation are required after this implementation freezes; the old
45A artifact report is historical evidence.

Owner bootstrap and a preliminary actual signed-SMS/execution/delivery path are
now observed below. Current-result serving, complete joined restart assertions,
native media, provider runs, UI and video remain pending. The component checkpoint
advances no complete charter acceptance row.

### Shared validation and startup-cost follow-up

The TypeScript workspace passed 1,818 tests across the console, P2, specialist and
new gateway runtime, plus strict compilation, formatting and builds. The fresh
isolated root application package passed 341 selected tests across seventeen
unadapted suites, direct/rebuilt payload and RECORD checks, exact dependency
metadata and complete cleanup of thirty-two process groups. The package lane has
zero actual SQL, provider or media assertions.

The first full Python run exposed an older consumer test that expected a duplicate
helper class identity. Its replacement asserts the exact adjacent compatibility
wrapper and the single canonical receiver class while retaining isolated import
and denied network/process checks. Both affected suites passed. Two subsequent
root-suite runs exceeded the unchanged 120-second wall limit; these remain
non-passing. A separately supervised exact discovery ran all 2,616 root tests with
zero skips in 117.343 wall seconds. P1/P2/P3 suites separately passed 49/113/436
cases. These observations do not constitute a passing make check command.

The startup optimization now lazily resolves seven baseline/native exports and
three existing module aliases. All 121 ordered public names preserve their genuine
objects, signatures, static types and explicit native behavior. Instrumented median
core import fell from 896 to 85 milliseconds across three matching samples. No
native SDK modules or background threads load for a contracts-only import. The
focused native/baseline tests and independent compatibility review passed; test
coverage and the 120-second suite limit remain unchanged. A diagnostic timing
wrapper with an incorrect import path is retained as nonqualifying evidence.

The fresh full make check passed 3,217 Python tests: 49 P1, 113 P2, 439 P3 and
2,616 root, with zero skips or structural violations. Broad typing covered 169
sources and strict typing covered 194. A subsequent isolated package run passed
all 341 selected installed tests and thirty-two process groups in 67.955 seconds,
with complete cleanup. Its retained report is
.local/validation/p2-result-receiver-package/phase45b-root-application-second-02.json.
Independent retained-evidence inspection confirmed the optimized P3 module in the
direct, rebuilt and installed artifacts. Later workspace dependency changes are
separate from that captured snapshot; no historical report was rewritten.

The first actual owner bootstrap stopped before P2 installation because macOS
adds an encoding environment variable to Node. The closed child allowlist now
accepts only that additional harmless variable. A real no-database Node regression
retains rejection of ambient database, provider and Node-option selectors. All
27 setup tests and independent review passed. The failed private attempt remains
unchanged with its actual P1 v4 state and no P2 schema; it was never repaired.

A fresh owner attempt succeeded. Read-only SQL verified P1 case/work v4 and P2 v8,
the actual receiver identity, an investigation-only case at revision one, and no
work, result, quote, intent or cancellation. Private journals and configurations
have modes 0700/0600 with one link per file. The original SQLite M1 record matched
its freshly read public-API baseline. A separate two-process paused-executor
startup passed actual source discovery and both gateway health reads, then normal
shutdown. These observations establish their stated setup/startup scope.

### First joined backend observations

The scripted specialist host composes the public SDK trust, immutable evidence
registry and fixed-policy handler. It has a separate one-key runtime role and no
PostgreSQL, provider or effect credential. The public listener now accepts an
explicit fixed port while preserving its ephemeral-port default. Its 187 SDK and
162 gateway tests passed; independent review repeated 39 affected cases. The
private specialist configuration deduplicates equal shared evidence and rejects
conflicting source versions or bytes. All 49 profile/setup tests and four actual
Python-to-Node parser cases passed, including the full 32-record bound.

The preliminary backend probe preserved one real signed simulated-SMS input and
equal replay. Actual persisted state joined that original receipt and prepared
payload to one P1 work, one issued attempt, one scripted eligible-at-commit result,
one P1 delivery receipt and the exact P2 receiver row. The stable app owner,
command, work key, body and original deadline were preserved. Five process groups
completed normal shutdown in the third observation, which took 3.818 seconds;
completed-work restart left all protected counts unchanged. The report is
.local/validation/phase45b-sms-restart-third-03/report.json.

The first two preliminary probes failed in their private oracle code: selection
of an SDK observer event as a receipt, then comparison of the specialist wire
attempt alias with the P1 UUID. Their raw reports and owned process cleanup are
retained. The third observation explicitly binds their earlier scoped positive
facts without relabelling either failed whole run. It reuses the original input
and creates no replacement work. Its completed restart observation is bounded;
it is not the final scan-completion/recovery gate.

These probes have no complete executed-source snapshot and are preliminary
integration evidence. The formal 45B gate still needs a frozen role/source
inventory, current-result disclosure, stale-room denial, useful progress and
complete restart assertions. Actual native media, real providers and video are
absent from these probes. The scripted result is not current disclosure authority
after its original deadline. Provider files were not read.

The new read-only job facade shares the existing two job tickets and exposes no
run or delivery command. Its 60 tests include queued cancellation, retained reads
and dependency-ordered close. The current-result producer has 39 tests and checks
original source, factual evidence, execution, delivery, native grant/case and fresh
applicability. Independent review corrected eager scan admission before task
publication; close now observes the same publication barrier. These components
still require the actual room-bound HTTP and application integration.

### Expanded source and installed checkpoint

After the producer, inspection and specialist-configuration changes, make check
passed 3,276 Python tests: 49 P1, 113 P2, 439 P3 and 2,675 root, with no skips or
structural violations. Broad typing covered 169 sources and strict typing 195.
An earlier full run failed only an obsolete package-test counter; that report is
retained and the corrected narrow suite passed all 51 cases before the final run.

The fresh isolated application lane passed 399 selected tests across eighteen
unadapted suites, 62 root runtime payloads and the existing nine P2 Python
payloads. Its thirty-two groups completed cleanup in 78.363 seconds. The retained
report is
.local/validation/p2-result-receiver-package/phase45b-root-application-third-03.json.
Public strict consumers now exercise the actual producer/inspection protocol;
old plans, source-binding, wheel/RECORD, role, capture and cleanup gates are
unchanged. Setup's 27 tests remain a separate administrative suite rather than
being counted in those 399 installed application tests. This checkpoint has no
SQL, media or provider assertions. Subsequent room-client/native work needs fresh
source and installed evidence.

### Next implementation boundary

45B must connect the implemented current-result producer to the room-bound Node
read and qualify the composed owners with a complete frozen actual gate.
The gate must prove original evidence/deadline and native/SMS source identity,
useful guarded work and accepted/completed normal restart. A stored eligible-at-commit result and current applicability remain
distinct after expiry or case change. The current native read must filter that
applicability before disclosing any body; parsing or a retained P2 receipt does not
establish it. No joined launch, media/UI, provider or recording claim follows from
45A. The remaining phase table above stays authoritative.


### Native composition component checkpoint

The application owns one captured current-result producer and reuses the existing
worker, coordinator and two job tickets. Its borrowed facade checks the original
attachment before and after every read. Failed, cancelled and timed-out cleanup
keeps the slot; successful detach removes closed bookkeeping. Independent checks
passed 94 tests across the application, room wire/client, result client and worker
callback. The affected jobs/producer/CLI/import regressions passed 126 tests.

The native worker configuration passed 25 tests, including pure import/parse/encode
with environment, file, socket, process and task access denied. Explicit loading
requires a private regular JSON file with stable metadata. The single-session
worker passed 23 tests and independent review: one genuine unconnected SDK
Runtime/AgentSession and actual prepare listener are exercised; connected RTC
lifetime schedules use explicit fake public constructors. End retains late model,
SDK-start and RTC-connect work before closing dependencies. Partial signal setup
and failed cleanup preserve finite errors and actual ownership.

The context adapter passed twenty genuine SDK tests after independent review
found a shallow-copy race. It now snapshots mutable public messages, tool-call
records and plain metadata before awaiting; native media/runtime objects remain
borrowed. Original failing and fixed mutation observations are retained.

The Node gateway passed all 232 tests and strict checks. Its opt-in native bridge
owns one public prepare client per current room and reuses existing storage for
case rehydration. Missing attachment for the current room is unavailable; exact
replay cannot retarget the worker. Shared HTTP extraction preserves the original
26 prepare assertions and adds twenty current-callback assertions. Independent
review and five additional TCP probes verified current-only no-store headers and
current-room denial immediately before successful socket write.

A fresh Python-control to compiled-Node to Python-prepare observation passed ten
checks, including original UTF-8/digest handling, exact attachment replay,
changed-capability conflict, old-A rejection and fresh-B progress. Its Node child
and actual HTTP owners drained. Grant storage and the prepare runtime are explicit
synthetic ports; this is no PostgreSQL, connected RTC, provider or media claim.
Retained component evidence is indexed under
.local/validation/channel-policy-native-components/checkpoint-01/index.json.

These component results do not complete 45B or 45C. Parent room/process ownership,
the frozen joined database/current-result/restart gate, actual browser voice/text/
SMS return, provider integration and final recording remain required. The expanded
source/installed inventory and full shared checks must be refreshed after these
sources freeze; the prior 3,276/399 counts above remain historical.

### Native source and installed baseline closed

The subsequent frozen component checkpoint passed make check: 3,510 Python tests
(49 P1, 113 P2, 439 P3 and 2,909 root), zero required skips or structural
violations, broad typing across 183 sources and strict typing across 208. The
full frontend gate passed 1,927 TypeScript tests (622 console, 886 P2, 187
specialist and 232 gateway), formatting, types and builds. Documentation checks
covered 129 maintained documents; all 47 Mermaid bodies across thirteen designs
parsed, and the invalid-syntax control was rejected.

A fresh isolated package run passed 625 selected tests in twenty-eight unadapted
raw suites, with all thirty-two process groups settled and cleanup complete in
85.717 seconds. Non-author checker-code review and a separate retained-artifact
audit checked the actual wheel/source archive, installed paths, raw suites,
public npm fixture and process evidence. This remains offline component evidence:
actual database, connected RTC and provider assertions are zero. The indexed
checkpoint is
.local/validation/channel-policy-native-components/checkpoint-02/index.json.

The first two full Python observations exceeded the existing root 120-second
deadline and remain failed. Separate diagnostic runs that observed completion are
retained without qualification. The final full gate passed under the original
deadline. Two independent partial-request deadline tests now run concurrently
with their original assertions and real one-second limits. Timeout diagnostics
retain only validated test identifiers and numeric progress; raw output and
dependency exception text are excluded. No deadline or coverage was weakened.

This closes the component baseline only. Parent room/process ownership, actual
SDK-disconnect handling, the joined PostgreSQL/current-result/restart gate,
browser voice/text/End/dormant-SMS/return, provider qualification, reproducible
application launch and the recorded demo remain required. Later source changes
need fresh evidence and do not inherit this checkpoint automatically.

### Parent and operator component baseline

The next source baseline passed make check with 3,684 Python tests: 49 P1,
116 P2, 439 P3 and 3,080 root. Required skips and structural violations are zero;
broad typing covers 192 sources and strict typing 218. The Root runner uses two
fixed workers under the original aggregate 120-second limit, including five
seconds for cleanup. Both complete discovery manifests agreed, and their exact
70/3,010 disjoint selections executed in 88.916 seconds with successful reap,
group absence and no stop signals. This is the expanded test set, not a
same-source performance comparison with earlier observations.

The isolated installed lane passed 752 tests across 36 unadapted raw suites,
84 root runtime payloads and nine P2 Python payloads. Its 32 builder groups and ten
explicit harmless test-child groups all settled, with complete cleanup in
87.148 seconds. Non-author checker review and 66 independent checker tests cover
the separately counted child ownership receipts. No product database, connected
RTC or provider calls occur in this lane. Retained artifacts and source bindings
are indexed under
.local/validation/channel-policy-native-components/checkpoint-03/index.json.

Parent Start/End now owns original room commands, child startup/drain and exact
current-result attachment separately from the durable background App. Operator
authorization survives room End; read-only case/progress facts and signed
simulated SMS use the existing public boundaries. Genuine SDK close events fence
admission before asynchronous cleanup. Review corrected a private-file metadata
race and a reentrant factory-close gap, with negative lifecycle tests. The new
Parent composition passed nineteen focused independent tests.

A separate actual local SFU admin probe created one original room, minted and
verified restricted tokens, deleted it and observed absence. A fresh public-SDK
query independently observed the same original room absent. The first probe's
wrong host port remains failed; configured host-port propagation was corrected
for both worker and browser grants. DeleteRoom has no atomic expected-SID fence;
these are as-of observations and establish no connected native/media behavior.

This baseline precedes the joined UI retirement correction and launcher. The
joined database/current-result/stale/restart assertions, connected browser
voice/text/End/dormant-SMS/return journey, real-provider qualification and video
remain pending. Full P2/P3 acceptance and the overall demo goal remain incomplete.


### Launcher and first connected browser observations

The explicit launcher and its helper passed 36 focused tests, strict typing,
lint, formatting and inert-plan checks. Review corrected late-adopted UI cleanup,
independent UI/Parent admission fencing and failed-reader drain proof. The full
Python gate then passed 3,720 tests: 49 P1, 116 P2, 439 P3 and 3,116 root, with
zero required skips or structural violations. Broad typing covered 192 sources
and strict typing 220. The Root 70/3,046 partitions completed in 83.444 seconds
under the original 120-second aggregate budget. This is the baseline before the
subsequent preview-shutdown correction, not evidence for later code edits.

The UI retirement correction passed 73 focused tests and independent review.
It reserves the third HTTP ticket for End, captures original-only cleanup across
Forget, permits one bounded automatic post-Start replay and retains explicit
same-owner retry. Repeated Forget coalesces; a closed acknowledgement cannot
release outstanding readers or media. The full frontend gate passed 2,000 tests:
695 console, 886 P2, 187 specialist and 232 gateway, plus formatting, types and
all maintained builds. The freshly built joined UI includes these fixes.

The first backend-only launcher lifecycle passed eight actual checks in 1.459
seconds: authenticated status/case/progress, wrong-key denial and normal shutdown.
All three process groups exited successfully and were absent; private persistent
configuration and the original M1 public-API row were preserved. The retained source/test and actual observation index is
.local/validation/channel-policy-joined-first-01/index.json. It preserves both
failed whole runs; portable commands remain in the local setup guide.

The first connected browser probe observed real native readiness, one fresh text
reply, non-silent samples from the selected remote audio track, original native
work dispatch, End/client drain, dormant-SMS visibility and Forget. It measured
202 PCM windows, 170 above its declared threshold, from one selected track;
these are test observations, not hearing, ASR quality or a latency benchmark.
Passwords were empty, browser storage empty and no page errors or external
requests were observed. No SMS or returning B was submitted in this probe.

Both whole joined observations remain failed. The browser driver's Chromium
close observer did not establish child/pipe settlement within its original
window. The outer runtime controller reached its original 300-second business
deadline before the later stop marker. Its normal shutdown reaped all five
observed groups, including the native worker, with unchanged source/profile and
persistent files. The UI exited 143 without the wrapper's closed frame because
the pinned Vite preview installs its own signal handler. Browser-driver and
preview-shutdown corrections are in progress; neither failure is relabelled.

A separate fresh public-SDK query observed the exact original room absent.
Read-only SQL observed its native binding revoked, two accepted/issued/result/
delivery records and two P2 result receipts in total, with zero result actions.
These separately timed counts include the prior SMS result and new native result;
they do not replace full original-input/evidence/result joins or establish fresh
current applicability. Provider files and provider calls remained absent.

The remaining connected voice/interruption/dormant-SMS/return and restart
assertions, fresh source-bound qualification after corrections, real-provider
run and recorded walkthrough remain required. The complete P2/P3 charters and
overall demo goal remain incomplete.
