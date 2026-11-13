# Channel Continuity Kit coding instructions

Status: Active
Last reviewed: 13 November 2026

## Read first

Follow the [root instructions](../../AGENTS.md), then read this project's
[README.md](README.md), [Design.md](Design.md),
[V1 charter](../../docs/projects/channel-continuity-scope.md) and the
[shared validation plan](../../docs/validation-plan.md). Inspect affected source
and tests before editing.

Read the [granular implementation plan](../../docs/implementation/p2-channel-continuity.md)
for phase gates, task prerequisites and failure evidence. These task IDs are not
product acceptance IDs; the charter remains authoritative.

## Owned paths

TypeScript version-1 contracts and implemented intake/dispatch/gateway source live under
projects/channel-continuity/src. Project tests live under tests in this project.
The Python member lives under python/src/channel_continuity. Its default codec
is SDK-free; the optional native adapter consumes the separately owned durable
TypeScript runtime and does not own another queue. Shared wire fixtures live under
contracts/channel. Root workspace/check registration must cover both languages.

The charter owns scope and acceptance IDs. Root design owns shared authority and
ports. Keep unrelated projects and user files intact.

## Development rules

- Persist accepted input before acknowledgement. Preserve trusted tenant/account scope, scoped provider identities and changed-payload conflicts; never deduplicate separate messages by text content.
- Keep `ProviderScope` distinct from verified end-user `AccountScope`. A recognized carrier account does not authorize case access.
- Use the case authority for revisioned intent and confirmation. An ambiguous SMS reply must not invent which revision the user approved.
- Consume native LiveKit text and interruption behavior. Preserve generated, playback, delivery and acknowledgement observations with their source; unknown remains unknown and playback is not consent.
- Keep dormant cases independent of live rooms. Standalone examples use fake SMS and narrow operation/agent ports without importing P1 or P3 application implementations. Real carriers and Cloud evaluation remain optional.
- Define provider replay horizons and receipt/delivery tombstones before cleanup; display-history pruning cannot permit duplicate acceptance. At a real package-consumer boundary, test the npm-pack artifact from an isolated consumer.

### Stable result receiver and current-grant read

The [0043 work item](../../docs/work-items/0043-stable-result-delivery-and-return-context.md) owns the new v8 seam; selected sixteen storage/four return assertions passed.
The work item records separate package and final shared outcomes. Use only the
explicit quiescent owner v7-to-v8 upgrade. Serving code never runs DDL, rotates
the retained receiver ID or adopts an unrelated ordinary outbox UUID.
Accept/find authenticate a distinct trusted publisher capability. The original
canonical P1 intent/result digest and logical recipient remain immutable. This
profile accepts the explicit P3-compatible 64-character identifier subset; reject
wider unsupported identifiers without truncating or rewriting them.

Result metadata and the fixed ordinary notice commit together under the existing
outbox admission lock and maxReplies cap. A notice bodyDigest is never the P1
result_sha256. Exact replay/read remain available at capacity; changed bytes
conflict. Receiver acceptance grants no carrier send, hearing or action authority.
Current-channel reading is separate: derive the route from a current native grant,
release SQL for the public P1 read, then recheck the original grant under locks
with fresh database time. Retain one shared outbox call slot through this entire
sequence; no connection/transaction spans external I/O. Case/reply times and
applicability are observations across separate reads, never an atomic snapshot.
Keep the existing rehydration-v1 shape, native tools-disabled policy, unknown-send
behavior and revision-zero read-only boundary unchanged.

### Operation-only origin integration

The public ./starter OperationClientConfig overload supplies only trusted profile,
loopback endpoint and account/case/conversation/sender bindings with an operation
bearer. Preserve the legacy two-argument constructor and actual two-call/socket
ownership limits. Never fabricate SMS metadata for a native publisher or put this
service credential in browser/model inputs. Keep encoded frame and original
canonical input independently bounded, validating closed descriptors before I/O.

The [0044 work item](../../docs/work-items/0044-origin-bound-channel-policy.md)
keeps original payload bytes in P2 and returns the actual P1 work UUID as the
external receipt. A kind/receipt does not establish channel provenance; real
accepted-event joins are required. Restrict only P3-mapped identifiers/revisions
at the bridge, preserving P2-only sender/event/message bounds. Remote accept
errors remain OutcomeUnknown and failed lookup remains Unavailable; neither
permits a replacement operation key. Fourteen actual source assertions qualified original native/signed-SMS input,
work and result joins. Integrated voice/text/SMS routing remains pending; isolated
package checks remain separate fake-port evidence.

## Verification

Run the TypeScript package's typecheck/test/build and project Python unittest
suite from the root as documented in README.md. Keep exact cross-language
canonical bytes, duplicate-key/Unicode/numeric and UTF-8 boundary fixtures.
Parsing or constructing a TrustedPrincipal object is not authentication. A future
gateway must use the implemented raw authenticated intake boundary, revalidate
current association, and decode untrusted data at the actual boundary; it must not trust a caller-constructed DecodedEvent or receipt.


Use stable P2 acceptance IDs in the change plan and evidence. Run the
relevant implemented scenario, focused structural checks and full fast lane before
handoff. Commands in the README run from the repository root. Planned, skipped,
missing and timed-out checks cannot count as passes. New behavioral runners need
real assertions and useful failure artifacts; no hidden service setup is allowed.

For storage/association changes run make p2-postgres-check after restricted-role
local setup. Server-only exports include ./security, ./postgres, ./migrations, ./dispatch, ./gateway and ./agent-process;
keep the default codec browser-safe. Runtime must not execute DDL, delete canonical
receipts, refresh schema baselines or enroll LINK proofs as business messages.
Preserve stable operation identity, scoped sequence and original receipt after
response loss. SMS-only qualification cannot close a complete product row.

The ./standalone example requires all adapters and trusted scope binding before
intake. Keep receipt acceptance separate from authenticated read-only preview.
Runtime-validate case scope/revision, scripted reply and persisted operation key;
pending/not_executed is the only example operation state. This is not a scheduler,
retry owner, business-action executor or case authority. A preview timeout retains
its slot until the underlying adapter actually settles; never free ignored work
merely because a timer fired. Check monotonic deadlines after each awaited stage
and before success. Helper close owns preview resources only; callers also close
the provided inbox. Run --example and the full PostgreSQL lane for changes here.

For I07 dispatch, use only the explicit owner version1-to-version2 upgrade.
Runtime never repairs drift or changes immutable input/receipt/key. Keep prepared
scope/case/revision/plan/digest frozen before possible external acceptance. Recheck
the original current association before each new accept; reassignment cannot
retarget prior input. Reserve possible_external/state uncertain in a committed
transaction before calling a cooperating investigation adapter outside locks.
Leases guard local observations and do not fence external execution. Keep stable
key/scope/digest idempotency and lookup mandatory. Ordinary attempts are bounded;
lookup-only reconciliation may resolve known original work after exhaustion or
sender revocation without new accept, plan generation or attempt-row growth.

Standalone preview must reject every nonpending state instead of advertising
not_executed after dispatch. Driver deadlines include synchronous observers and
abort callbacks; retain ignored adapter slots until actual settlement and report
incomplete cleanup honestly. Use --dispatch, the full 23-case lane and --example
for dispatch/storage changes. Keep the separate cooperating operation fixture
outside the SDK and prove actual commit/kill/fresh-process lookup. Outbox, broader
restart schedules, case mutation/confirmation and native media remain later slices.

For I08 gateway work, keep the literal-loopback raw HTTP boundary, four-request/
16-socket admission and fixed header/body/response budgets. Import starts no
listener; explicit startup preflights owner-installed v2 without DDL. A startup
timeout retains actual I/O and closes a late bind. Poll only bounded persisted
eligible IDs using configured account credentials, rotate accounts, honor the tick
budget before each SQL scan and revalidate authority in step. No incoming message
may select worker scope or become the owner of a memory queue. Normal ingress
cannot starve committed work; only trusted test-hook mode may hold the ACK-before-
dispatch barrier. Observe actual HTTP200 before the owned SIGKILL, verify zero
prepared/external work before it, then prove fresh-process recovery/replay and
cleanup. Preserve all old cases in the full 23-case lane and use --gateway for the
three-case subset. Keep application-created observer resources outside the
listener's cleanup claim. Default Docker/UI, agent crash, revision routing and media
remain their own slices.

For I09, AgentProcess owns only trusted Node modules inside its POSIX process
group. Validate parent and worker allowed scopes independently; bind every response
to the entire normalized context digest and strict revision/source/decision.
Use its plain agent.port object for the existing port registry. Received data
cannot select modulePath, environment, executable, scope inventory or a PID.
Forward only the finite explicitly configured P2_AGENT_ fields, never ambient PG,
provider, proxy or Node selectors. No shell, import-time process or implicit retry
is allowed. Waiter timeout/abort does not free actual process capacity. Observe
actual child exit, pipes and group disappearance after TERM/KILL; incomplete
cleanup retains ownership. Module code must keep descendants in that group.
Application observer resources and physical remote computation have separate owners.

The --agent fixture keeps a real gateway listening, sees its HTTP200 and an owned
worker PID barrier, waits for PostgreSQL to observe claim expiry, verifies no plan
or external operation, then kills only that known active worker. The next worker
must receive identical original scope/case/revision/input and preserve one logical
operation acceptance. Distinguish repeated scripted processing from business
acceptance; retain both dispatch attempts and independently persisted receipt.
Run real child/descendant unit tests, --agent and the full 23-case lane. SMS/scripted
process qualification does not close a complete charter row or native media gate.

For I10, ./routing routes only a strict original accepted investigation-revision
body. Derive scope/case/operation/receipt from authenticated input inspection and
trusted allowed bindings; no call/body may override them. Provider timestamps are
observations, not revision order. Preserve decimal zero-through-int64 revisions
and known revised/unchanged versus conflict/unknown. No automatic retry/rebase,
matching-payload acceptance inference, command receipt or exact mutation consent
is provided. I11 owns confirmation association.

Standalone reference-case v1 is explicit owner-seeded state for independent use.
Integrated mode selects the bounded local P1 public-case bridge and never copies
P1 revisions into that schema. Runtime does no DDL. Keep actual calls/socket/
connection ownership after waiter timeout and validate AbortSignal before admission.
Discard failed rollback/unknown-commit connections. Router closes only its own
calls; application owns input and authority cleanup. Logs/metrics use fixed enums.

Retained account history authentication is not current sender association.
Do not change ChannelInbox.inspect or claim an atomic revocation fence here.
Run p2_routing_check.py, its offline negative/report/environment tests, public
artifact checks and the old full 23-case PostgreSQL lane. Its two authority
fixtures must observe actual PostgreSQL blocking before release, one transition/
one conflict, valid further progress and postcommit unknown with original receipt.
Independent owner checks prove full P1 mapping/request and zero action effects.
A report-retention failure cannot pass. Missing native/confirmation/revocation
acceptance remains non-passing; no complete P2 row is registered by this slice.

For I11, confirmation is a separate capability and requires a trusted immutable
response/revision/exact-quote binding. Publish only through the distinct controller
credential; ordinary account credentials and model output cannot publish prompts.
Keep full canonical supplier-bound quote bytes opaque through TypeScript. Preserve
int64 decimal metadata and P1 UUIDv5 quote IDs; command IDs are original inbox
operation UUIDs. P1 public commit_confirmation owns atomic quote/revision/time/
cancellation validation and intent commitment. Never replace it with a read then
plain write, current-state inference, automatic retry/rebase or inferred consent.

ConfirmationInputPort requires retained inspect and late inspectForConfirmation.
After prompt lookup, revalidate current original sender/association epoch and exact
original input before the possible authority call. History remains unchanged.
Known revoked/reassigned input is denied; the preflight is not a cross-authority
revocation fence. Replays after revocation remain denied by this facade, even when
P1 retains a known receipt. No lookup-only fallback may start a new write.

Keep fake-SMS v1 closed wire unchanged. Explicit YES responseID is linked through
the immutable registry; bare YES needs both existing trusted event links. Preserve
unknown ACK and explicit same-command replay. Prompt storage has a persisted cap,
immutable tenant/account/response identity, replay-at-cap and changed-payload
conflicts; no prompt pruning, delivery/hearing assertion or duplicate case ledger.
Reference-case v1 remains investigation-only. Default bridge bindings must not gain
confirmation without explicit opt-in. Application closes router, input, registry
and authority separately; actual work/socket ownership survives waiter timeout.
Run p2_confirmation_check.py plus wrapper/HTTP/consent negatives, current I10/old23
regressions and isolated public package consumption. I11 selected evidence does
not register a complete P2 row or qualify native media/UI/outbound delivery.

## Outbound replies and ordinary fake sends

For I12, use the explicit owner `upgradeChannelSchemaV3` after v2 under a
maintenance/quiescence boundary. Serving code never installs, upgrades or repairs
storage. Old installation/v2 upgrade validate v3 without downgrading it; new inbox
and dispatch calls remain compatible. Keep original receipts, canonical input,
prepared plans, keys and dispatch history intact. The outbox is separate from P1
case intent, supplier effects, result-feed acknowledgements and exact consent.

The `./outbox` publisher credential binds immutable tenant/account/case/conversation;
ordinary account credentials cannot enqueue. Stable outbound UUID, response reference
and exact body bytes determine immutable enqueue identity. Body digest and envelope
intent digest are distinct from any P1 result digest. A future 8192-byte result needs
an explicit bounded notice/reference rather than silent SMS truncation. Receiver and
enqueue receipt UUIDs persist through reopen. Queue acceptance is not provider delivery.

Routes and suppression are keyed by tenant/account/conversation, not a global phone
opt-out. Current association, recipient, route version and suppression are checked
with new possible-send reservation under the existing inbox admission guard. This
reservation is the local permission commitment point. Revoke/suppress before it
prevents a new call; later changes cannot retract a paused admitted network call.
A route change cannot transfer prior ownership or rewrite an old attempt. Route
selection never clears suppression. Preserve retained recipient history access.

Each explicit send has a distinct attempt UUID and immutable request/route/association/
provider-operation snapshot. Results are separate immutable records. Possible without
a validated result is unknown, even if a crash preceded the physical call. Unknown
blocks another send or retarget; only known definitive nonacceptance permits another
bounded explicit attempt. I12 adds no daemon, automatic resend or physical exactly-once claim. I13 adds the
separate callback rule below; I14 still owns ambiguous resend qualification.

ChannelOutbox owns its store and actual send tasks. The application separately owns
the supplied carrier client and inbox. Timeout/abort retains actual slots through
settlement; a late known result can be saved while the caller remains uncertain.
Fail incomplete cleanup, then close/reconcile the actual resources. Metrics and logs
use fixed event/code enums only; enqueue replay counters are historical acceptance
observations, not current queued state or unique provider deliveries.

Run `p2_outbox_check.py`, wrapper negatives, all P2 tests, I10/I11/old23 regressions
and an isolated installed public npm consumer. The actual lane includes owner
rollback/backup-restore, old/new dispatch on v3, real process kill, current-route
barriers and independent fake-provider correlation. Preserve original failed runs.
See [the stable phase handoff](../../docs/work-items/0033-outbound-replies-and-completion-processing.md)
for qualification; no complete charter row is registered by I12.

## Handoff

Record the behavior changed, acceptance IDs, interface/migration decisions, exact
commands, observed results and remaining work. Update implementation status only
when evidence supports it. Keep offline, local-media and live-model results
separate, and record assistance and personal contributions accurately.

## Provider callback evidence

For I13, use owner `upgradeChannelSchemaV4` under quiescence. Never alter the closed
v1 SMS/channel wire. Callback schema1 has exactly eight flat fields and a separate
key-bearing integration/HMAC domain. Authenticate fresh exact raw bytes before dedup
or attempt lookup; recheck `clock_timestamp()` after admission locks. Retain original
first raw bytes and canonical semantic fingerprint; retry timestamp/signature are
transport-only, while changed occurredAt/state/providerMessageId conflicts.

Correlate to original immutable attempt provider scope, operation key and request
digest; derive recipient/case from persisted original identity. Current routes, phone
labels and provider message IDs cannot select ownership. No send result is required
for an otherwise valid callback. Late reports after revocation/reassignment remain
old recipient history, and the new owner gains no access.

Keep callback observations separate from immutable send_results. Read both using one
REPEATABLE READ snapshot before reduction. The fixed fake_sms_delivery_evidence_v1
rule is commutative: no arrival/occurredAt winner. Retain terminal contradictions,
provider identity mismatch and positive evidence against definitive nonacceptance.
Accepted then failed alone is compatible. Conflicted reports never become optimistic
physical delivery, human acknowledgement, consent or resend permission.

Callback acceptance and NEW v4 reservation first acquire existing admission; only
callback growth then acquires callback_admission. Reservation reads retained evidence
on ANY of the reply's at most five prior attempts and vetoes a new call. pending is
advisory. Callback first blocks; reservation first cannot be retroactively fenced.
Never rewrite an old send result, retarget or automatically retry. v3 behavior remains
unchanged until explicit v4 upgrade.

Default callback caps 10000/eight and maxima 100000/32 are persisted. Authenticate equal
replay before capacity checks; retain receipt identity for profile lifetime with no
physical pruning. Keep fixed-code logs/metrics, four actual tasks/two SQL connections,
monotonic waiter budgets and retained work after timeout/abort. App-created listeners
and carrier clients have separate cleanup owners; import starts no service.

Run callback24, wrapper negatives, all P2 unit/type/build gates and prior outbox24,
routing22, confirmation18/recovery23 regressions. Prove actual SQL-cancel rollback,
one owned commit-before-ACK SIGKILL, fresh original replay, independent provider/SQL
binding and populated v4 backup/restore/reopen. Do not count SQL cancellation as a
process kill. Validate the installed npm artifact with strict public types and actual
app-owned HTTP/PG consumption. Preserve failed evidence and use the stable
[phase handoff](../../docs/work-items/0034-callback-evidence-and-applicability-refresh.md).
The I13 evidence qualifies only its selected callback slice. Use the separate I14
handoff below for current ordinary lost-response and explicit idempotent recovery
evidence. That I13/I14 evidence alone did not qualify native/media behavior; the
selected I15–I18 gates record it separately. Whole P2 rows and broader UI/load
qualification remain pending.

## Uncertain-send policy

For I14, use explicit owner version 5 after v4 under quiescence. Keep the four new
policy tables and their counter separate from old outbox row shapes. The sole old
catalog relaxation permits repeated provider keys across exact local attempts,
with a scoped operation FK. Adopt all old attempts permanently as ordinary; never
retrofit an old ambiguous send into an idempotent capability. Owner adoption is
paged64/bounded50000 and rejects malformed envelope/result/counter state atomically.

Freeze provider namespace/capability, logical recipient/outbound/response, original
address and body into the provider operation before its first possible call. New
attempt IDs and route observations never enter that operation digest. Preserve
callback-v1 attempt/key/requestDigest correlation. The cooperating fake's terminal
negative must fence all later arrivals of that same key; absence never grants a new key.

Use distinct trusted recovery-controller credentials and immutable UUID commands.
Original-command replay is lookup of its retained receipt, with no provider I/O.
Unknown permissions and possible sends do not retry automatically. Ordinary unknown
always holds. New idempotent calls need current association/route/suppression plus
all-prior callback and operation evidence checks under existing admission. Keep
history valid using a specific immutable predecessor admission witness; later
conflicts veto future calls without retroactively corrupting admitted history.

Keep the existing aggregate SQL/task/pool bounds; the policy SQL helper owns no
second pool or worker. Preserve late actual results after waiter timeout and expose
acknowledgement uncertainty separately from definitive rejection. Metrics/logs use
finite codes with no IDs or payloads. The app owns supplied carrier HTTP cleanup.
Run the actual30 gate, retained regressions and isolated npm artifact consumer.
See [the stable handoff](../../docs/work-items/0035-send-policy-and-action-races.md).
No callback-driven resend, physical exactly-once, complete media row or automatic
booking completion is introduced by this slice.

Selected I15/I16 native composition is described in its native handoff; the opt-in I17 implementation and qualification boundaries are recorded in its communication handoff. Selected I18 current-case rehydration and I19 bounded workloads have passed their separate gates. I20 joined observability passed selected qualification in 0040. I21 is the
current installed starter slice in 0041; I22 and full release remain separate.
Keep its media/lifetime evidence distinct from selected I12/I13/I14 fake-carrier
qualification and installed-package checks. Never label queued acceptance or a
provider report as physical delivery, human acknowledgement or booking completion.

## Native text and committed voice

Use only the explicit `./native` opaque integration and version 6 owner upgrade.
Never fabricate a native caller as a verified fake-SMS provider. Publisher, account,
room-binding and prepare credentials are distinct; browser RTC tokens contain no
native ingress credential. Fix tenant/account/case/conversation/room/participant in
trusted construction. Stream IDs and provider/model output cannot select authority.

Persist input and its stable UUID before ACK or generation. Keep the existing
persisted dispatcher as the sole generation owner; no second queue or direct native
business invocation. Disable `RoomOptions.text_input`, set `session_host=False`,
use manual turns/preemptive generation disabled, and always `StopResponse` from
completed-user-turn hooks. Count real default reply events so a zero assertion is
observable. Genuine recognition snapshots capture original turn identity before
awaits; interim events and SDK promotion are observation only. Repeated commit
must not add an input, context message or automatic reply.

Retain actual sockets/readers/recognition/intake/prepare work through settlement.
Use fresh PostgreSQL time after original admission/binding locks to block NEW
prepare/reservation after expiry/revoke, while retaining account history. An already
admitted possible call is not retrospectively cancelled. No disconnected-room
implicit revoke, grant renewal or retarget is authorized. Keep the parent native
media gate's six browser groups separate from focused SDK/storage groups; do not
invent twelve browser tests or complete P2-15 registration.

Use the stable [native handoff](../../docs/work-items/0036-native-input-and-deadline-cancellation.md)
for evidence. Preserve the optional pinned Agents dependency edge without refreshing
versions. The default Python codec remains independently importable. I17 qualification is separate from the prior native gate. I18 current-case reading/profile has its separate contract and handoff; real inference/recognition and full charter/load gates remain later.

## Source-qualified response evidence

Read [COMMUNICATION.md](COMMUNICATION.md) and the [I17 handoff](../../docs/work-items/0037-playback-evidence-and-process-recovery.md).
Use only explicit owner v6-to-v7 migration for the three additive communication
tables. Keep old canonical rows and original native18/six-key generation wire.
Publisher/SDK/browser/account credentials have separate roles; body source labels,
model text and playback never authenticate or grant confirmation/business authority.
Response/observation replay preserves exact original receipts at legitimate caps.
Response sequence is scoped to tenant/account/conversation; observations sequence
within their original response. Global counters govern profile growth only.

Capture the application ContextVar around synchronous generate_reply, bind the
returned public handle, and retain actual public LLM/TTS node tasks and producer
work through settlement. Never borrow current_speech, SDK private fields, expected
fixture text or SpeechHandle.done as proof actual generation drained. Preserve
streaming, queue of 2/4096-byte/256-chunk limits and normal-exhaustion provenance.
Full generation and synchronized SDK partial text are separate sources. An
interruption request is not a stopped/playback-complete acknowledgement.

Browser evidence is a scoped original-response report. Never map delayed callbacks
to a mutable current response, invent completion after disconnect, or infer human
hearing. Late evidence appends to its retained original response after grant expiry;
new response creation still requires current grant authority. SDK completed and
browser unknown can coexist. Contradictions are retained without timestamp winners.

Run affected actual SDK and HTTP units, strict types, explicit v7 storage16 and
actual browser/audio3 gates, native6/old storage regressions and isolated package
consumers. Keep each proof layer honestly labelled. No complete charter row follows
from these selected scripted scenarios or from a provider/client report.


## Read-only current-case context

Read [REHYDRATION.md](REHYDRATION.md) and the [I18 handoff](../../docs/work-items/0038-case-rehydration-and-standalone-release.md).
Derive scope from the current native grant or exact authenticated already accepted
SMS plus original current epoch. Do not use retained account history as current
channel authority. Reuse the existing inbox transaction/pool; no second read store,
case clone, session queue or automatic acceptance/generation is authorized.
Capture coherent P2 history, release SQL for the public current-case read, then
perform a new protected disclosure check using fresh database time. Later
revocation cannot retract returned bytes; P1/P2 observations are not atomic.

Allowlist public P1 facts and exclude quote/confirmation/control payloads. Preserve
source fingerprints separately from revisions/cursors. Supplier/work state can
advance at one case revision; loaded facts are explicitly as-of, and refresh is
idle/explicit with zero generation. Revision mismatch blocks preparation before
SDK invocation. Keep pure read zero distinct from the existing positive-revision
native dispatch/communication domain; never auto-revise or pretend zero support.

Bound total envelope bytes, not only rows or child text. Omit whole records with
separate scoped continuation. Original source/receipt/operation/response identities
are immutable history; new room bindings use fresh genuine input IDs. Never add
old room responses to new speech controls. Preserve legacy native18/wires and test
pure/model/HTTP, pinned SDK, actual storage/media and installed artifacts distinctly.


The prior 0038 checkpoint passed selected I18 storage 18/media 3, isolated Python 111/npm seven-stage and 166 compatibility assertions. The [0039 handoff](../../docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md) records selected I19 workload 24, current isolated Python 113/npm seven-stage and fresh 187 compatibility assertions, all passed. Preserve those historical source/role/receipt/cleanup boundaries alongside the selected I20 handoff. All seventeen complete P2 charter rows remain planned; pure P1 revision-0
reading does not qualify zero-revision native dispatch or communication.


## I19 workload ownership

Read [WORKLOAD.md](WORKLOAD.md) and the frozen workload manifest before changing
its actual fixture or runner. Preserve the declared schedule and budgets before
measurement. The inbox limit counts every retained row; completion does not
reclaim capacity. Use bounded public credential windows for dormant cases, never
SQL seed bypass or a larger SeededAccounts cap. Report per-instance and actual
aggregate pools/tasks separately; selected cross-scope progress is not fairness.

Ordinary inbox observers reserve a slot before invocation and retain it until
actual promise settlement. Their three-key telemetryMetrics is separate from
existing communication metrics. SQL close does not own an injected transport.
Release application-held observer work before asserting complete cleanup. Keep
SFU inventory read-only in the parent and provider credentials absent. A fresh
process and populated restore must preserve old receipts/keys/body/conflicts;
display eviction must never delete canonical replay protection. Keep I20 and
complete charter acceptance separate from the selected workload experiment.

The selected I19 qualification preserves all original inputs and operation identities through restart and populated restore. Its quantitative observations belong to the declared local profile; the separately qualified I20 view does not extend those capacity claims. Current I21 installed-application qualification belongs to 0041; I22 and
complete release acceptance retain their own gates. Keep the current installed Python 113-test proof distinct from the prior 111-test application snapshot.


## I20 operations reads

Follow [OPERATIONS.md](OPERATIONS.md) and the fixed operations manifest. Preserve
legacy rehydration cursor/field limits and final current-grant admission. The new
signed cursor is application-source/scope/section-bound and never read or mutation
authority. Do not treat accepted-row paging as a complete status-event feed.
Keep explicit refresh and separately observed as-of facts; revision equality is
not workflow/supplier freshness, and revision-zero reads grant no native execution.

The independent operator diagnostic capability carries process facts only. Keep
finite metric/log/span enums, actual reader owners separate from caller spans,
no body/token labels and failed getters unavailable rather than zero. Use source-specific producer maps and the closed 76-code vocabulary;
unknown events, arbitrary labels and accessor fields fail closed. Reserve completion
ownership before callbacks, getters and thenable access. Reentrant close keeps
returned work owned until actual settlement and blocks later getter admission.
Retain ignored async work until it settles.
Observe actual overload, rejection, dropout and useful progress. No default
listener, automatic business queue, resend control or exporter service is added.

Keep one retained UI client across Forget/Connect epochs. Clear private state
immediately but withhold new admission until the old actual owner closes. Close
dependent readers/dispatchers before shared inbox/case resources; attempt every
independent owner within a safe tier and preserve the first failure. Unresolved
owners retain marked work and prevent schema deletion. Source-qualified browser,
actual SQL, socket/mock and installed-package proofs must remain distinct.


The [0040 handoff](../../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md)
records selected I20 qualification: sixteen actual PostgreSQL/read assertions and
three browser groups passed in thirteen owned commands, followed by the isolated
105-payload npm consumer's seven stages and all 187 fresh compatibility assertions.
All selected cleanup checks passed. Pure/model and real loopback producer tests
are distinct from actual SQL/browser and installed-archive evidence. The Python
nine-payload/113-test runtime and application snapshot is unchanged by this slice.
I21 provides the standalone installed starter, with observed qualification in
0041; I22 owns fresh-agent and complete release evidence. All seventeen full charter rows remain planned.


## Installed starter application

Follow [STARTER.md](STARTER.md), the fixed starter manifest and the
[0041 handoff](../../docs/work-items/0041-standalone-channel-and-durable-policy.md).
Keep the executable inert on import and plan before any configuration/PG/listener
startup. The additive application export composes the unchanged SDK. The explicit
owner bootstraps schemas; runtime cannot rewrite immutable profile/catalog data.
Keep route-versus-serve exclusion on one owned session mutex across processes and
retain it until dependent I/O actually closes. No transaction spans external HTTP.

The four-table application receipt ledger is synthetic external evidence, never a
second work queue or business authority. Investigation/idempotent replay and
conflict precede capacity. Equal ordinary port calls append distinct physical
observations; no reliable lookup or automatic resend is implied. Preserve compact
canonical operation bytes/digest/binding validation and the declared wire limits.
Keep ordinary reply text nonempty and legacy carrier response-header contracts.

Normal installed twenty and separate public-P1 six require their own frozen
source, role, process, receipt, permission and populated-restore proofs. Preserve
all failed attempts, exact whole-record snapshots and first errors. Keep existing
SDK/default service/native/P1 sources unchanged. I22 and all complete charter rows
retain separate release gates.
