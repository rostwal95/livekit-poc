# Correlated callback evidence and refreshed result applicability

Status: Completed
Last reviewed: 11 November 2026

## Behavior and scope

Implement the selected P2-I13 and P3-I11 behavior after the
[completed outbound-reply/processing phase](0033-outbound-replies-and-completion-processing.md).
The [P2 task plan](../implementation/p2-channel-continuity.md) and
[P3 task plan](../implementation/p3-delegation-reliability.md) remain subordinate
to their charters. This work contributes to P2-10/P2-12 and P3-05; it does not
register a complete charter row or qualify the full P2/P3 release.

P2 adds authenticated evidence about an existing immutable send attempt. P3
adds explicit refreshed applicability and display tombstones over existing result
references. P1 remains the case/execution/result/delivery/action authority. Its
77 runtime payloads, schema and public interfaces remain unchanged. Keep the
frozen dependency locks and image baseline. New providers, real carriers, paid
inference, default UI/native/Compose composition, automatic booking-completion
handoff, ambiguous-send retries and broader protected-action recovery are separate.

| Criterion | Given | When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- | --- |
| Authenticated callback | Trusted fake-provider integration and raw bytes | Signature/window/scope is invalid, or an authenticated retry arrives | Authentication precedes dedup; body labels grant no account access; bad input creates no evidence | Fresh signed equal retry returns original scoped event receipt | Unit/raw-boundary negatives, actual PostgreSQL and local HTTP |
| Exact original attempt | Persisted possible send with immutable request/route | Callback is delayed, arrives before send acknowledgement, or follows reassignment | Match provider scope, attempt, operation key and request digest; no retarget, current-route rewrite or case disclosure | Correlated evidence remains readable by the original authorized recipient | Independent SQL, callback and carrier observations |
| Evidence reduction | Duplicate/reordered/contradictory provider reports | Accepted/delivered/read/failed/unknown reports are observed | Deterministic provider rule retains all accepted observations; timestamps do not choose a winner; provider evidence is not human ACK or consent | Stronger compatible evidence survives obsolete reports and contradictions remain visible | Permutations, changed-payload conflicts, real callback/result races |
| Send safety veto | A nominal definitive nonacceptance and a correlated callback | Callback acceptance races a new reservation | Shared admission lock orders commitment; callback first blocks a new send; later callback cannot retract an admitted call | Unrelated eligible work still sends; reads/replays remain available | Actual lock contention, both orders, independent invocation counts |
| Refresh identity | Original projected event and fixed source/scope | Stable refresh command replays or changes target/expected revision | Original receipt replays before new reads/caps; changed semantics conflict; full source/attempt/request/result identity matches | One new explicit refresh commits a per-result local revision | Actual PostgreSQL CAS, process loss and exact owner joins |
| Current versus historical | A is running while the case becomes B | A completes, and valid B later completes | A stays historical/outdated; zero A-derived current action; no refreshed badge grants permission | B refreshes as current and a separate exact confirmation can authorize its existing guarded fake-action path | Controlled actual P1 case/work schedule and independent intent/effect truth |
| Monotonic evidence | Existing higher revision/cancellation/expiry observation | Older or unavailable reads follow | No silent revival from stale observations; execution/case/time remain separate as-of observations | Unavailable-only state can recover through a later valid explicit refresh | Unit and actual read/race schedules |
| Display retention | Original projection, refresh receipt and processing ACK | Explicit display hide and late replay | Hide never deletes source/projection/ACK/receipt/command identity or releases protected capacity; unresolved hidden events remain processable | Display returns its stable tombstone; exact authenticated reads and replay retain original bytes | Populated restore, fresh process and independent receiver/metadata checks |
| Bounds and lifetime | Slow I/O, malformed data, saturation or telemetry failure | Waiter times out/cancels or close is interrupted | Actual tasks/threads/sockets remain owned; no unbounded buffer/queue; no credential/body leakage | Later valid work progresses after settlement; replay works at capacity | Real socket/thread/process negatives and safe producer observations |

## Interfaces and ownership

### P2 provider evidence

Keep the existing channel-event and fake-SMS intake v1 wires unchanged. Add a
separate server-only callback capability with a callback-specific raw-byte HMAC
domain/key and finite authentication window. Trusted configuration supplies
ProviderScope. The strict bounded callback body supplies only event/attempt/
provider-operation/request-digest/message identity, state and diagnostic occurrence
time. Account, recipient, case, conversation, address and route come exclusively
from the persisted original attempt. Signature/retry-envelope time is excluded
from semantic identity; a retry still authenticates before lookup.

Use an explicit owner inbox v3-to-v4 upgrade under maintenance/quiescence. Old
APIs and original accepted/send/dispatch bytes remain compatible; older upgrade
functions validate the current profile without downgrading. Runtime performs no
DDL or catalog repair. Callback records and receipts are immutable, scoped by
provider integration and event identity. Equal replay returns the first receipt;
changed semantics conflict. Store bounds apply before accepting new identities;
reads and equal replay remain available at capacity.

Callback evidence is independent of send_results. A callback before the send
response may establish a correlated provider observation without filling in or
rewriting that response. Preserve contradictory provider-message IDs and terminal
reports explicitly. The deterministic fake-provider reducer uses evidence rules,
not occurrence/receipt timestamp order. A reported delivery failure is distinct
from definitive provider nonacceptance. No callback authorizes a resend or new
recipient. Any retained callback on a prior attempt of the reply conservatively
vetoes another send after nominal definitive nonacceptance. Acceptance of that
evidence and new reservation share the existing admission guard; a veto cannot
fence an external call admitted earlier. I14 owns ambiguous-send policy.

The public server-only ./callbacks export provides CallbackInbox.accept,
inspectAttempt, metrics and close, plus createFakeSmsCallbackIntegration and the
synthetic signFakeSmsCallback producer. The exact wire fields are schemaVersion,
eventId, attemptId, providerOperationKey, requestDigest, providerMessageId, state
and occurredAt. Preserve the first authenticated raw bytes separately from the
canonical semantic identity. Account reads/logs expose no key/signature. Recheck
the signature window using database clock_timestamp after admission locks before
lookup/commit; transaction-start time cannot qualify a delayed callback.

Owner v4 adds only callback_settings, callback_admission and callback_observations.
Default caps are 10000 total observations and eight per attempt, with maxima
100000 and 32. Attempt reads return at most 32 observations; existing replies
retain at most five attempts. Runtime may insert evidence and update only its
count column; it cannot update/delete observations or perform DDL. All growth
first takes existing inbox admission, then callback admission. Send reservation
retains its existing outbox guard and reads callback evidence under the already
exclusive inbox admission; no path takes a count guard before admission.

The fixed fake_sms_delivery_evidence_v1 reducer is pure and order-independent.
It preserves separate immutable send result, reported-state flags and message IDs.
The reported strength order is read_reported, delivered, failed,
accepted_by_provider, unknown, none. Accepted then failed is a possible normal
lifecycle; delivered/read together with failed is a terminal contradiction.
Multiple reported message IDs or a mismatch with known send acceptance is an
identity contradiction. Positive acceptance/delivery/read together with definitive
nonacceptance is a send-result contradiction. Any conflict produces an explicit
conflicted assessment; a timestamp never resolves it. These are reported provider
states, not proof of physical delivery or human acknowledgement.

CallbackInbox retains at most four SQL calls over two existing connections;
waiter defaults to two seconds, maximum five, and close is bounded to two seconds.
Observers are bounded to eight. The explicit application-owned HTTP fixture has
4096-byte raw input/header and 2048-byte response limits; it is not an SDK listener
or default service. The SDK owns raw authentication, SQL and actual call lifetime;
the application owns HTTP resources. No expiry or physical callback/receipt
deletion is added. Replay remains supported for the retained profile lifetime;
capacity does not silently discard identity.

### P3 refreshed applicability and retained display

Explicit owner projection v2-to-v3 upgrade preserves all five old tables, original
projection bytes/checkpoint, fixed processing policy and terminal ACKs. Add only
refresh control, per-event applicability heads and immutable refresh receipts.
Heads contain a local revision/latest command and an optional stable permanent
display tombstone. Old public projector/processor APIs remain compatible on v3.

Default total retained refresh commands is 3000, configurable from 1 through
30000; default per-result commands is four, configurable from one through eight.
One head per projected event is bounded by the existing projection limit. Each
canonical refresh receipt is at most 4096 bytes. Hiding reclaims no protected
capacity. The replay horizon is the retained profile lifetime, with no physical
DELETE/TTL/cleanup scheduler or identity reuse.

An explicit ApplicabilityRefresher refreshes one exact work/attempt using a stable
command UUID and expected local revision. Replay checks the complete original
command before new external reads or caps. New observations verify current feed
source/event and exact historical issuance/result/request/evidence. Observe the
current work record's cancellation/current attempt and original deadline, then
the exact current case. Reuse ExactManagedCaseAuthority through public P1 ports.
The original issuance record is historical and cannot substitute for current
cancellation. A stored eligible result is not invalid merely because its old
grant lease later expired. Host deadline observations are local/as-of evidence,
not a new P1 database-time receipt.

Persist separate execution/case/time observations and candidate/clarification
reasons with effective current/outdated/invalidated/unavailable/rejected state.
Expected per-event revision CAS orders local metadata, never provider/wall-clock
timestamps. Retain verified higher case/attempt observations and irreversible
invalidation evidence so stale/unavailable reads cannot revive an older result.
Unavailable alone is recoverable. No atomic source/case read or action/delivery
permission is claimed. Existing processing ACKs and known receipts remain facts.

The authenticated client reads the original refresh command or latest result
view. Explicit hide_display returns a stable tombstone, independently of refresh
revision; original projection/refresh/ACK inspection still works. Existing
processing scans do not filter hidden unresolved events. Ambiguous refresh/hide
commit performs one exact read, never another write. A stale CAS preserves
checkpoint_conflict unless its exact original receipt is found.

The refresher owns its injected feed/execution/metadata clients; the application
owns the shared case adapter. Active calls are bounded to at most four, configured
waiter timeout to at most ten seconds and cleanup to at most five seconds. Actual
I/O remains owned after waiter abandonment. Public examples start no background
work, DDL or provider calls on import.

### Engineering ownership

P2 owns callback contracts/auth/reducer/store/public intake, additive v4 migration
and send veto, project tests/actual fixture/gate and project guides. P3 owns five
applicability modules, additive owner/store compatibility, public exports,
tests/actual fixture/example and project guides. Shared tooling owns the P3 gate
wrapper/root negatives, Makefile/foundation/discovery and documentation inventory.
New Python source, fixtures and examples enter strict typing and test/lint/format
discovery immediately. No product imports private P1 storage.

## Failure cases and validation

| Gate | Applicable and why | Exact assertions | Prerequisite/resource/time bound | Expected evidence |
| --- | --- | --- | --- | --- |
| G-READY | New durable evidence/refresh boundaries | Freeze auth/identity/reducer/CAS/retention contracts, public inventory and ownership before product changes | Current source-bound phase33 baseline | This plan and machine contract record |
| G-FAST/OBS | New public data/async/persistence behavior | Normal, primitive/schema/canonical/scope/conflict/cap, timeout/cancel/late close, secret sentinels and telemetry outage with later useful progress | Offline; no provider configuration/private CA reads | Full Python/frontend, lint/types/format and narrow negative reports |
| G-DURABLE P2 | New owner v4 and provider evidence | Nonempty upgrade/repeat/interruption and populated pg_dump/restore; concurrent replay/conflict; early/delayed/reordered callback; current-route independence; actual veto contention; postcommit process loss/fresh replay | Restricted PostgreSQL, owned loopback HTTP/fake carrier and fixed work/cleanup budgets | Named frozen cases, independent SQL/raw-provider truth and complete cleanup |
| G-DURABLE P3 | New projection v3 metadata | Nonempty upgrade/rollback/repeat and populated refresh/tombstone restore; A-to-B plus valid B guarded progress; monotonic stale read/CAS; hidden unresolved event; pre/postcommit loss and fresh exact replay | Actual public P1 work/case/feed/delivery/receiver; fixed bounded process inventory | Named cases, original projection/ACK/receipt identity joins and complete cleanup |
| G-PACKAGE | New reusable public capabilities | Build npm/wheel/sdist/rebuilt archives and install outside checkout; strict public types; actual callback/refresh and fresh replay through public APIs | Frozen offline dependency caches; explicit local owner setup | Archive/source parity, exact fixture/example identities and owned cleanup |
| Regression | Preserve old profile/API semantics | P2 outbox/confirmation/routing/recovery; P3 processing/projection/coordinator/execution and registered P3-01/03/11 lab rows | Serialized owned actual PostgreSQL lanes | Fresh selected reports; no required missing/skipped/zero/timeout pass |
| Runtime/docs | Reproducible clean local handoff | Ordinary Docker readiness/text/audio smoke, original M1 identity, standardized guides/current Mermaid syntax, old checkpoint and dependency lock preservation | No reset, providers or default product expansion | Exact measured logs, source hashes, independent review and sealed checkpoint |
| Full release | Separate from these selected tasks | Preserve remaining charter rows, media, broader action/cancellation recovery and production capacity as pending | Their own normative gates | No new catalog registration or blanket ecosystem pass |

The P2 actual gate freezes 24 named assertions: populated v3-to-v4 preservation;
repeat/old-upgrade/limits; interrupted owner upgrade; populated v4 pg_dump/restore;
runtime DDL/catalog/counter drift; domain/key/fresh-clock authentication; provider
scope/original recipient; wrong attempt/operation/digest; concurrent equal replay;
reordered JSON/fresh-signature replay; changed-event conflict; distinct events;
weaker-report permutation; terminal/identity contradictions; callback before send
response; immutable send result/no consent; delayed revoke/reassignment history;
cross-account inspection; caps/replay; any-prior-attempt callback veto; reservation
first; postcommit owned SIGKILL/fresh replay; bounded diagnostics/cleanup; and
independent SQL/provider reconciliation. The normal delayed send response is
released after callback; this is not I14's lost-provider-response/resend proof.

The P3 actual gate freezes 18 cases and 20 closed child modes under P3_REFRESH_.
It owns five PID kills at upgrade_commit, refresh_before, refresh_after,
hide_before and hide_after, plus one observed SQL refresh race. The 180-second
total deadline reserves 15 seconds for cleanup. Bound aggregate capture to 128 KiB,
each stream/call to 2048 bytes and final report to 32 KiB. Owner/runtime roles and
credential fields remain separate. Its populated eight-table restore uses
validated versioned profile rows, explicitly not pg_dump. Preserve original
projection/ACK/receiver facts, refreshed heads/receipts and display tombstones;
then prove a fresh public projector append still works on v3.

Freeze exact child field/mode/named-case manifests before measuring. Each failure schedule must also prove valid useful progress.
Keep owner/runtime child environments finite and separate; no ambient provider,
proxy, Python-path or database selectors. Precreate owned PID barriers, retain
bounded diagnostic capture, terminate only owned active children, and fail visible
incomplete cleanup. Preserve original failures and distinguish corrected fixture
assumptions from product changes.

Emit fixed event/outcome/error enums from real operations, bounded counters with
explicit units and no tenant/recipient/address/work/event/body as metric labels.
Never copy raw headers, credentials, provider exception text or result payloads
into diagnostics. Telemetry failure cannot change persisted truth. Translate
boundary exceptions once; cancellation propagates while actual work retains its
slot until settlement. Timeouts do not prove that a remote call or DB thread stopped.

## Results and handoff

P2-I13 and P3-I11 completed their selected local phase gates. P1 remains the
case/execution/result/delivery/action authority. P2 adds provider evidence; P3 adds
derived refresh/display metadata. No full charter row was registered.

| Area | Implemented behavior | Observed proof |
| --- | --- | --- |
| P2 callbacks | Explicit inbox v3-to-v4 owner upgrade, separate raw-byte HMAC, 60-second authentication envelope, exact original-attempt correlation and immutable evidence/reduction | Final strengthened 24-case gate, one owned postcommit process kill, one upgrade-blocking graph, two simultaneous callback/reservation waiters and a separate clock-expiry lock observation; source reports retain exact scope |
| Callback timing and veto | Re-authenticate at admission after SQL waiting; any retained correlated callback vetoes another reservation after nominal nonacceptance | An initially age-60 signature becomes age-61 after observed lock waiting: zero expired callback/counter rows; a fresh valid event progresses. Callback-first prevents reservation; reservation-first retains its admitted external boundary |
| Populated callback recovery | Quiescent actual Docker pg_dump/psql round trip preserves original inbox/outbox plus all new callback evidence | 12 callback observations, 5 replies, 7 attempts and 6 results preserve exact canonical snapshots before/after/reopen; six carrier observations remain six with zero extra provider calls |
| P3 applicability | Owner projection v2-to-v3 upgrade, exact-command replay, local revision CAS, monotonic invalidation evidence and independent display tombstones | Normal source 18-case gate: five owned PID kills, one actual SQL graph, late A outdated/zero A action and separately confirmed valid B fake effect, source/ACK/receiver/refresh/head joins and complete cleanup |
| P3 restore and retention | Populated new commands/heads/tombstones restore alongside unchanged original projection/ACK/source identities | All eight profile tables match the exact quiescent captured cut; fresh old public projector appends the ninth result on v3. This is validated versioned-profile-row restoration, not pg_dump or stale-branch recovery |
| Fast engineering gates | Full offline tests, lint/types and formatting retain new modules, actual fixtures, public examples and protocol negatives | 1,581 Python tests: P1 49, P2 14, P3 225, root 1,293; 772 TypeScript: console 326, P2 368, specialist 78; broad 138/strict 104 type sources; 333 formatted Python files; zero required skips/structural violations |
| Fresh compatibility | Existing selected behavior stays intact on the new profiles | P2 outbox/routing/confirmation/recovery 24/22/18/23 and seven P3 lanes: processing 16, projection 12, coordinator 10, execution 12, registered P3-01/03/11 13/8/12 |
| Installed public consumers | Offline archives install outside the checkout with declared dependencies and strict public imports/types | P2 66 JavaScript/declaration/README payload files match exact bytes plus semantic manifest parity; eight installed stages passed on the first attempt. Fresh P3 wheel/sdist/rebuilt artifacts match 30 runtime files; the exact unadapted installed fixture passes all 18 assertions with five owned kills and one graph in 46.290 seconds. |
| Local runtime | Preserve original state and ordinary transport-only setup | Ordinary Docker start/doctor/smoke passed with 8 checks, 10 actual audio frames and original M1 identity preserved without reset. |
| Documentation | Standardized instructions, ownership, next-step rows and unchanged diagrams | 107 documents pass after final closure; 16 frozen root/project Mermaid bodies retain their syntax qualification only. Syntax parsing does not qualify diagram meaning or runtime behavior |

The global Python/type results come from the same maintained make-check run;
its explicit type excerpt is not a second execution. Python formatting was checked
separately. Frontend formatting, types, tests and build passed separately. Correctness-gate durations are not
production latency/capacity measurements. P2's ordinary delayed provider response
is released after callback; this is not I14's lost-response/resend qualification.

Commands run from the maintained repository with its frozen Python/Node
environment: make check, make frontend-check and make format-check; the explicit
p2_callbacks_check.py and p3_applicability_check.py lanes; the prior P2/P3
database/process lanes and harness run P3-01/P3-03/P3-11. The normal P3 qualifying
invocation used --report .local/validation/p3-applicability/i11-qualified-10.json;
its diagnostic reproductions used a separate --diagnostic selector and fresh
report paths. These selectors cannot relabel diagnostic output as qualification.

P1's 77 runtime payloads and existing qualified archive are reused unchanged.
No new 327-case P1 PostgreSQL run or provider/native qualification is claimed.
Current P2/P3 gates exercise the declared public P1 boundaries and preserve the
historical source-bound evidence. This phase did not read provider keys or a
private CA, call paid inference, upgrade dependencies, publish Git changes or
require remote CI. Ordinary isolated PG/access settings are used privately by
actual local gates and never copied into evidence.

A provider callback is evidence, not physical delivery, hearing, human ACK or
booking consent. Its occurrence timestamp cannot select a winning case revision.
A callback admission veto cannot retract an already admitted paused external
call, and cannot authorize a new send. I14 retains ambiguous provider response,
capability-specific reconciliation/resend and idempotency-policy qualification.
No automatic P1 booking-completion-to-P2 handoff or new default Compose/UI path
is added; the P1 delegation result feed is not that booking-completion handoff.

P3 retains raw execution/case/time observations as non-atomic as-of reads.
Metadata revision orders local commits only. Higher verified revisions, different
attempt/cancellation witnesses and observed local expiry cannot silently revive
under stale/unavailable reads. Host expiry is local/as-of, not a P1 DB-time receipt;
a result eligible at commit does not expire with its old grant lease. Known
receipts and terminal ACKs remain facts. Display hiding is permanent presentation
metadata with profile-lifetime replay: it deletes no protected identity, releases
no retained slot and never filters hidden unresolved processing. Refresh supplies
no action/delivery permission, source ACK or automatic accept retry.

### Retained failures and diagnostic scope

P2 first01 rejected a leading-v Node version fixture before seed, with cleanup.
Second02 used an invalid-length synthetic carrier bearer; the boundary correctly
rejected it. The fixture also lacked listener startup cleanup and reached its
owned deadline. Corrected credentials, owned startup cleanup and a 20-second
stage cap fixed tooling without weakening SDK validation. Corrected03 passed its
narrower sequential-veto inventory. Final04 adds actual callback+reserve blocking
and the post-wait freshness proof; earlier reports remain their original scope.

P3 first01 retained a generic seed failure and complete cleanup, while its child
capture was ephemeral under the original wrapper. No original stderr or precise
first-child reason is invented. Separately retained diagnostic02/03 identify the
fixture's 180-second work horizon versus P1's unchanged 60-second acceptance
maximum; diagnostic03 records WorkError(expired). An early lease-expiry hypothesis
was unconfirmed and is corrected here. A completion was moved before unrelated B
projection/processing I/O without weakening its eligible-at-commit assertion.
Subsequent controlled diagnostics corrected repeated writes to an exclusive
originals file, recomputed the short-deadline logical fingerprint through its
canonical producer, aligned exact named-case protocol output and preserved the
canonical authoritative quote serialization with the supplied explicit consent.
No P1 or runtime safety guard was weakened.

Diagnostic09 executed all named assertions but deliberately remained failed with
diagnostic_not_qualification. Normal10 is the separate qualifying 18-case report.
The diagnostic wrapper retains only bounded sanitized allowlisted child streams;
it cannot produce a qualification pass, and never copies environment, fixture,
SQLite, provider or private-CA files. Original reports, corrected reproductions
and narrow static/test iterations remain retained with honest provenance.

### Remaining scope and next phase

- P2-I14 owns explicit ambiguous-send/reconciliation/resend policy; callbacks do
  not establish one physical delivery or permission to repeat an unknown call.
- P3-I12 owns broader protected action/revision schedules, followed by I13/I14
  cancellation/deadline/recovery. The selected A/B path does not qualify every
  later race or repair the source-incarnation/stale-backup boundary.
- The catalog remains 24 registered of 55: all 17 P2 and remaining 14 P3 rows
  stay planned; P3-01/P3-03/P3-11 retain only their complete lab qualification.
- Full P2/P3 release, native/media composition, production capacity and real
  provider evidence retain their own gates. GitHub/remote CI is not a prerequisite.

The phase evidence checkpoint is
`.local/validation/p2-callbacks-p3-applicability/4b493af39d3448f1b619cd2cb52e16b7`.
Its eventual sealed index binds current reports, source/package hashes, original
failures, independent review and the unchanged closed prior checkpoint.
