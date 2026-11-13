# Outbound replies and resumable completion processing

Status: Completed
Last reviewed: 11 November 2026

## Behavior and scope

Implement P2-I12's durable reply intents, authorized versioned routes and ordinary
fake-carrier sends, alongside P3-I10's resumable completion processing. Continue the
[completed linked-confirmation/projection phase](0032-linked-confirmation-and-result-projections.md).
Use the maintained Downloads/repositories/livekit-agent-ecosystem checkout.
Preserve closed evidence, original M1 data and every existing accepted identity.

P1 continues to own execution, result events and delivery/action receipts. P2 owns
communication intents and provider observations; P3 owns derived projection and
consumer-processing metadata. No new P1 schema/API or dependency version is required.
The existing P1 result feed contains delegation results, not booking completion
notifications. Automatic booking-completion-to-P2 integration needs a separately
published application handoff; this phase does not claim it.

| Criterion | Given | When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- | --- |
| P2-I12 durable reply | Distinct trusted publisher and immutable recipient/case/conversation binding | Equal or changed outbound identity is enqueued, including at capacity | One original receipt; changed body/recipient/response conflicts; account credentials cannot publish | Fresh process discovers committed pending reply and performs normal send | Actual PostgreSQL, concurrent enqueue, retained original receipt and owned process kill |
| Authorized routing | Verified original recipient association and versioned route/suppression state | Route is missing, revoked, reassigned, suppressed or replaced | No unauthorized new reservation or disclosure; suppression survives route selection | A newly verified route for the same recipient permits eligible work | Actual guarded transactions and independent fake-provider truth |
| Permission commitment | Route and suppression checked atomically with possible-send reservation | Revoke/suppress races with reservation | Winning revocation prevents a new call; later changes cannot retarget or retract an already admitted possible call | Original admitted attempt retains its exact route and correlation | Controlled database locking and paused-call schedule |
| Outbound uncertainty | Immutable per-attempt identity and possible marker | Process/caller exits or provider outcome is unavailable | Unknown is never automatically retried or labelled definitive failure; a new route cannot retarget the old attempt | Known original result remains inspectable; definitive nonacceptance permits a bounded explicit new attempt | Real process/socket lifetime and fresh-process observations |
| P3-I10 processing | Projected source event and fixed delivery policy | Explicit bounded processing step reads results | No new execution owner, source ACK, automatic action or cached applicability permission | Exact accepted delivery receipt or definite not-required decision gains a durable event acknowledgement | Actual P1 delivery/receiver ports, source/event/work/attempt/digest reconciliation |
| Separate cursors | Unknown event A and eligible later event B | Bounded scan advances and later wraps explicitly | Discovery cursor does not acknowledge A; terminal watermark never skips unacknowledged events | B progresses while A stays unknown; a later original-receipt lookup can complete A | Head-of-line failure/progress schedule and independent owner checks |
| Crash/replay | Existing delivery intent/possible marker/receipt and processing acknowledgement | Terminate before/after each relevant commitment | No receipt for another attempt, duplicate logical acceptance, new action or hidden undelivered result | Fresh process resumes known work and preserves original receipts/ACKs | Actual owned SIGKILL, repeated replay, duplicate workers and acknowledgement-loss reconciliation |
| Bounds/diagnostics | Capacity, hostile input, slow I/O and failing telemetry | Timeout, cancellation, malformed data or exporter failure | Actual work remains owned; finite rows/scans/bytes/tasks; logs omit bodies/credentials | Valid work, reads and replays still progress | Unit/socket/storage negatives plus useful progress and cleanup |

## Interfaces and ownership

### P2 reply and route authority

Introduce a separate server-only outbox surface with an explicit owner inbox
v2-to-v3 upgrade. Preserve inbox v1/v2 records, dispatch state and existing APIs.
The shared inbox admission guard serializes current association, route/suppression
checks and possible-send reservation. Serving performs no DDL or catalog repair.

Trusted publisher configuration binds credentials to tenant/account/case/
conversation. A reply draft has schema version, stable outbound UUID, response
reference and at most 4096 exact UTF-8 bytes. Recipient identity comes from trusted
configuration, never an untrusted phone number or a model-supplied account label.
Immutable enqueue receipt and intent digest are distinct from a P1 result digest.
A future P1-result adapter needs a bounded notice/reference rather than silently
truncating an 8192-byte result into SMS text.

Authenticated recipient reads expose retained replies and bounded pending IDs.
Route selection requires the current verified original association and an expected
route-version CAS. Recipient-level suppression persists through route changes;
selecting a route never implicitly unsuppresses it. Missing/unauthorized routes
hold work without a provider attempt. Reassignment cannot transfer old ownership.

Each actual invocation has a new immutable attempt UUID and frozen logical
recipient, address, association epoch, route version, provider operation key and
request digest. A separate immutable result row records validated provider
acceptance or definitive nonacceptance. A possible attempt without a validated
result remains unknown after restart and blocks another send of that reply.
Only known definitive nonacceptance permits another explicit bounded attempt.
Provider calls execute outside database locks. Reservation is the local permission
commitment; later revoke/suppress cannot independently fence a paused external call.

Persisted reply cap defaults to 1000, maximum 10000; attempts default to three,
maximum five per reply. Retained attempt growth is bounded by those settings;
replay/read remain available at capacity. Actual calls default to two per instance,
maximum four, with finite SQL, carrier, socket and cleanup budgets. No daemon,
process-memory acknowledgement queue, callback endpoint or implicit resend loop
is introduced. I13 owns callback evidence; I14 owns capability-specific ambiguous
resend/reconciliation qualification. Ordinary provider acceptance is not delivery,
playback, hearing, human acknowledgement or booking consent.

### P3 consumer-processing metadata

Explicit owner projection v1-to-v2 upgrade preserves source UUID/scope, all old
projection bytes/checkpoint and configured limits. Add only fixed processing
policy/control and immutable terminal per-event acknowledgements. Policy binds
receiver UUID and finite case/conversation-to-recipient mappings before I/O;
runtime cannot change it. Existing projection reads/writes remain compatible.

A bounded processor read exposes existing projected references through its
version-checked metadata client.
The explicit processor observes at most eight rows total per step, including at
most one wrap. A scan cursor tracks discovery. A separate terminal watermark
advances only over contiguous acknowledged events. Unknown/unavailable delivery
gets no terminal ACK; scan progress allows later eligible work without claiming
that earlier work completed. No retry/due/lease/execution queue fields are added.

For a known receipt, match exact source event, work, attempt, result digest,
receiver and recipient before acknowledgement, even after later cancellation.
A receipt for another attempt cannot acknowledge a historical event. For a new
delivery, use the existing public delivery facade's fresh result/case preflight
and P1 eligibility checks; stored as-of projection status grants no permission.
Existing possible-send plus reliable receiver absence remains unknown and lookup
only. No automatic acceptance retry, recipient rebase or action is authorized.

Terminal ACK plus scan/control CAS commit atomically. Same-event replay returns
its original terminal observation. Unknown write acknowledgement performs one
exact lookup, never blind resubmission. Definite rejected/historical not-required
observations may be terminal under the fixed versioned policy; unavailable,
ambiguous or unbound state cannot be invented. I11 retains broader applicability
refresh and replay-horizon/tombstone policy. Feed cursors remain source history;
processing ACK is P3-owned metadata, not a P1 consumer-ACK API.

Public facade policy inspection returns immutable copies with current binding
validation. Each resource has one declared lifecycle owner. Application-owned
result/case readers remain outside a processor's cleanup claim. New Python types,
public exports, fixtures and examples join strict typing, lint, tests and harness
ownership immediately. No current dependency/image/toolchain version changes.

## Failure cases and validation

| Gate | Applicable and why | Exact assertions | Prerequisites/resource/time bound | Expected evidence |
| --- | --- | --- | --- | --- |
| G-READY | Agree authority/permission/identity and ACK policy before product edits | Review charter rows and existing ports; no new P1 authority or global source ACK | Existing frozen local baseline | This plan plus reviewed module/API inventory |
| G-FAST/OBS | New public persistence/transport/processing boundaries | Ordinary, scope, conflict, capacity, primitive/canonical validation, cancellation/late close and safe telemetry | Offline; no provider configuration/private CA reads | Full maintained Python/frontend/lint/types/format and safe negative fixtures |
| G-DURABLE P2 | Inbox v3 upgrade and recoverable outbox | Original bytes/IDs, repeat/rollback/backup-restore, role/drift, enqueue/kill/replay, route/suppression races, same-recipient progress, one ordinary provider invocation and immutable attempts | Restricted actual PostgreSQL, owned fake carrier/ledger; fixed work/cleanup deadline | Exact named cases, independent SQL/provider truth and complete cleanup |
| G-DURABLE P3 | Projection v2 and completion ACK recovery | Upgrade preservation/interruption, actual pre/postcommit kills, receipt-after-restart, unknown A/later B progress, exact-event receipt binding, unchanged policy/source/scope, zero automatic action | Actual P1 v4 feed/delivery plus independent receiver; fixed bounded scan and deadline | Exact named cases, independent metadata/receipt reconciliation and complete cleanup |
| G-PACKAGE | New standalone public APIs | Fresh npm/wheel/sdist/rebuilt installs outside checkout, declared dependencies, strict public typing, ordinary send/processing and new-process original receipt/ACK replay | Offline frozen caches; no sibling/private P1 storage imports in product | Current archive/source parity, honest fixture authority labels and owned cleanup |
| Regression | Preserve old semantics through new profile versions | Existing P2 recovery/routing/confirmation lanes; P3 projection/coordinator/execution and registered lab rows; relevant P1 database compatibility | Serialize restricted-role database lanes; preserve original M1/volumes | Fresh selected reports; unavailable/zero/skipped/timed-out checks cannot pass |
| Runtime/docs | Local operation and clean handoff | Ordinary Docker readiness/text/audio smoke, original M1 identity, documentation standards and current Mermaid syntax | No reset/default media/provider rollout | Exact measured evidence, source hashes and previous checkpoint verification |
| Full-product release | Remains separate | No new full row without all normative assertions and required independent review | Callback/resend, broader recovery, native media and integrated product gates remain explicit | Catalog stays honest; no blanket release/capacity claim |

Freeze inventories and work/cleanup budgets before measuring. Preserve the first
failure and distinguish diagnostic reproductions from original capture. Use fixed
safe error/outcome codes and bounded per-instance counters from real operations;
no payload, route address, tenant/recipient or credential as metric labels.
Telemetry failure cannot change persisted truth. A timeout never proves that a
provider call or worker stopped. Retain actual thread/task/socket/process ownership
until settlement, and fail incomplete cleanup visibly.

## Results and handoff

P2-I12 and P3-I10 completed their selected local phase gates. P1 remains the
case/execution/result/delivery authority; P2 owns communication state and P3 owns
derived projection/processing metadata. No complete charter row was added.

| Area | Implemented behavior | Observed proof |
| --- | --- | --- |
| P2 outbound | Owner inbox v2-to-v3 upgrade, immutable recipient/reply identity, guarded versioned route/suppression and possible-send reservation | 24 actual assertions, independently observed route/upgrade contention, owned process loss, ordinary fake HTTP acceptance and complete cleanup |
| P2 populated migration | Exact original accepted input and prepared dispatch survive backup/restore, upgrade and public replay | Actual Docker pg_dump/psql restores exact populated v3 canonical snapshots: 6 replies, 8 attempts, 7 results plus old inbox/dispatch rows; fresh known/unknown replay retains seven carrier observations with zero extra calls |
| P3 processing | Owner projection v1-to-v2 upgrade preserves original bytes; separate discovery and contiguous terminal ACK metadata | 16 actual assertions, five owned-PID kills, competing-ACK SQL contention, unknown A/later B progress and exact source/ACK/P1/receiver joins |
| Coherent snapshot | Processing control/ACK CAS observes one repeatable-read snapshot while an old public projector writes a fresh eighth result on v2 | Processing snapshot through seven, fresh checkpoint eight; definite serialization conflict and ambiguous ACK each reconcile exactly once without another write |
| Maintained fast gates | Full offline tests, lint/types and formatting retain new modules, examples, wrappers and negative fixtures | 1,501 Python tests: P1 49, P2 14, P3 189, root 1,249; 723 TypeScript tests: console 326, P2 319, specialist 78; broad 133/strict 95 type sources; 321 formatted files |
| Compatibility | Original selected P2/P3 behavior remains intact | Fresh P2 recovery/routing/confirmation 23/22/18 and six P3 lanes: projection 12, coordinator 10, issued execution 12, registered P3-01/03/11 13/8/12 |
| Installed consumers | Frozen offline installs outside the checkout use declared public APIs and strict types | P2 58 emitted JavaScript/declaration/README files match current bytes plus manifest JSON semantics; P3 wheel/sdist/rebuilt match 25 runtime files and run all 16 processing assertions |
| Local runtime | Ordinary stack rebuild/readiness/transport and original state | Ordinary start/doctor/smoke passed: 8 checks, 10 actual audio frames, original M1 identity preserved without reset |
| Documentation | Standardized guides and design diagrams remain current | 106 documents pass; 14 current root/project Mermaid blocks parse with malformed-input negative, qualifying syntax only |

Commands ran from the maintained checkout with its Python 3.14 interpreter and
pinned Node/pnpm environment: make check, make frontend-check, make format-check,
make typecheck, explicit p2_outbox_check.py and p3_processing_check.py, the old
P2/P3 database/process gates and registered harness run P3-01/P3-03/P3-11. Required
lanes passed without skips. Correctness durations are not production latency or
capacity measurements.

P1 product code, all 77 runtime payload bytes and the qualified package archive
are reused unchanged. This phase does not rerun the previous 327-case P1 PostgreSQL lane;
provider/native qualification also remains historical. Current compatibility evidence comes
from exact runtime/archive parity and the actual public interfaces exercised by
these P2/P3 gates. Historical provider evidence retains its original source scope.
This phase did not read provider keys or a private CA, call paid inference, upgrade
dependencies, publish Git changes or require remote CI.

P2 provider acceptance is distinct from physical delivery, human acknowledgement
and booking consent. Its possible-send reservation commits the current route and
suppression permission; later revocation cannot retract an already admitted
external call. Unknown attempts retain their original route and cannot be
automatically retried. Automatic booking-completion-to-P2 integration still needs
a separately published application handoff; the delegation result feed is not a
booking-completion feed. Callback and ambiguous resend qualification remain later
I13/I14 work. The installed fake-send consumer makes no P1 or real-provider claim.

P3 processing ACKs describe the fixed delivery-only policy. Discovery never
acknowledges an unresolved gap; possible-send plus receiver absence remains unknown
after cancellation, expiry or case change. Known exact receipts are facts before
fresh applicability. Stored as-of metadata supplies no action or current delivery
permission. Fresh case/recipient preflights are not an atomic cross-authority
revocation fence. Full action/recovery, refresh and tombstone policy remain
separate. The profile-row backup/restore procedure is validated and explicitly
labelled separately from pg_dump.

Independent reviews resolved strict primitive models, same-case conversation
routing, exact source/attempt/digest binding, retained thread/task/socket lifetime
and full receiver/ACK/control identity joins. The original P3 source16 passed
before the concurrency review. That review changed the ACK transaction to
repeatable read and maps SQLSTATE 40001 to definite checkpoint_conflict, followed
by one exact ACK lookup without another write. The strengthened source16 and
exact unadapted installed16 passed. Their isolation schedule proves a frozen
snapshot through seven while the old public projector appends eight, rather than
claiming to reproduce the exact old race. No actual P3 PostgreSQL run failed.

P2 first01 correctly observed DispatchUnavailable and persisted uncertainty after
a lost ACK; the fixture had expected an uncertain return instead of the public
exception. Second02 and diagnostic03 correctly rejected the old client with
UpgradeRequired, then failed a cross-process object/prototype comparison. The
fixture now compares serialized immutable values. All three original failed
reports and raw captures remain retained; each observed zero carrier calls and
complete cleanup. These corrections did not weaken a guard. Corrected04 and
final05 passed their narrower inventories. The final backup fixture adds an actual
populated v3 round trip without changing product code or the installed archive.
Narrow lint, type, import, fixture and Mermaid iterations remain retained without
promoting an intermediate result to the final scope.

The full 1,501 Python and 723 TypeScript suites preceded the final test-only
populated restore strengthening. The strengthened 24-case lane, narrow 16-case
wrapper checks and final global types/format checks passed afterward. Existing
full-suite results retain their measured source scope; the final fixture changes
are covered by those subsequent focused and static checks.

### Remaining boundaries and next phase

- P2-I13 adds authenticated correlated callback evidence and reduction; I14 owns
  provider-specific ambiguous send/reconciliation policy.
- P3-I11 adds applicability refresh and replay/tombstone policy. Broader protected
  action/cancellation recovery remains I12/I13/I14 work.
- The catalog remains 24 registered of 55: all 17 P2 and 14 P3 rows stay planned,
  with only P3-01/P3-03/P3-11 qualified as complete lab rows.
- Complete native/media integration, production capacity and full P2/P3 release
  retain their own gates. The local POC stays independent of GitHub/remote CI.

The evidence checkpoint is `.local/validation/p2-outbox-p3-processing/3b3ca5c5ca79483b92f1fe9b3f214b7a`.
Its final ignored index binds current reports, package/source hashes,
retained first failures, independent reviews and preserved previous checkpoints.

