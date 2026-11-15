# Stable result delivery and current-channel return context

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Record the plan, observed verification and handoff for the stable result delivery seam and the current-channel return read |
| Audience | Engineers changing P3 fixed-policy delivery, P2 receiver storage or the current-channel result read; coding agents |
| Scope | Selected delivery/read qualification toward P3-I19 and P2-I22; excludes the joined A/B journey, origin binding, provider runs and the final video |
| Owns | Change plan, observed verification and handoff for the P3-I19 and P2-I22 delivery/read seam |
| Related | [Work item 0042](0042-responsive-native-policy-and-compact-demo.md) · [Work item 0044](0044-origin-bound-channel-policy.md) · [P2 task plan](../implementation/p2-channel-continuity.md) · [P3 task plan](../implementation/p3-delegation-reliability.md) · [Validation plan](../validation-plan.md) |

## Behavior and scope

This work item implements the next selected P3-I19 contribution to PLAN-20 and
P3-12, with the P2 routing prerequisite for P2-I22 and selected P2-09/P2-12.

- A verified fixed-policy result can be accepted by a stable conversation receiver
  after its original room closes.
- A newly authorized interaction reads the original accepted result and a
  separately observed current case.
- Receiver acceptance, carrier send, client playback and human acknowledgement
  remain separate facts.

The [completed native handoff](0042-responsive-native-policy-and-compact-demo.md)
qualified P3 RTC text in source and isolated installed modes. Preserve that
checkpoint and its failed first run. Its final shared baseline is 2,590 Python and
1,580 TypeScript tests, with zero required skips. All full P2 and the remaining
fourteen P3 charter rows retain their own assertions. This work item does not
register a partial product row or establish a complete media release.

This slice closes the typed delivery/read seam first. These follow after this seam
passes: the joined A/B voice/text/SMS browser journey, the explicit persisted
P2-origin acceptance contract, the configured provider run and the final video. P2
native generation continues with tools disabled. Native case revision zero remains
read-only.

### Terms used in this record

| Term | Meaning |
| --- | --- |
| Implementation task IDs | Such as P3-I19; identify tasks in the project task plans |
| Acceptance IDs | Such as P3-12; identify rows in the project charters |
| PLAN-20 | A work package in the [build plan](../build-plan.md) |
| Selected qualification | The gates chosen for this work item passed; it does not complete a full charter row |
| Gate names | Such as G-READY and G-DURABLE; refer to the engineering gates in the [validation plan](../validation-plan.md) |
| Acknowledgement (ACK) | A receiver's confirmation that it accepted a message; a lost ACK leaves the outcome unknown |
| Compare-and-set (CAS) | A write that succeeds only when the stored revision still matches the expected revision |
| Real-time communication (RTC) | The WebRTC room path through LiveKit |
| SDK | Software development kit; here the pinned LiveKit Agents SDK |
| Data definition language (DDL) | Schema-changing SQL; serving code runs none |
| M1 | The original confirmed-investigation intake data, which every phase preserves |

### Criteria

| Criterion | Given | When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- | --- |
| P3-12 selected stable delivery | A P1-issued, factually verified v2 result and a trusted logical recipient | Explicit delivery is requested after original room closure | Original scope/work/attempt/result digest and immutable route remain bound; no room handle selects destination | The existing P2 outbox retains one result receipt and one linked notice | Real PostgreSQL and bounded cross-language public consumer |
| Delivery uncertainty | Receiver commits before the sender observes its acknowledgement | Sender acknowledgement is omitted; a separate receiver caller process is killed after commit | P1 possible state permits lookup only; no second acceptance or automatic SMS send | A fresh original-intent lookup recovers the exact receipt | Public P1 possible state and fresh facade lookup; separate owned receiver-process barrier and independent SQL joins |
| Immutable identity | Original intent is replayed or changed under the same identity | Receiver acceptance or lookup occurs | Changed body, digest, work, attempt, receiver or recipient cannot overwrite or retarget accepted state | Exact replay succeeds at legitimate capacity | Positive/negative runtime fixtures and real storage checks |
| Current-channel disclosure | Fresh room B has a valid native grant for the same stable conversation | B requests an accepted result and the case is read publicly | Retained account history and old room A grant do not substitute for current disclosure authority; fresh authorization follows external read | B sees original accepted facts plus explicitly non-atomic current-case observations | Grant expiry/revocation, foreign route and held-read schedules |
| Historical result | Case revision advances after result acceptance | B reads the same result | Original eligibility-at-commit and receipt do not change; outdated result grants no mutation authority | Historical A stays explainable while an explicitly accepted current result can progress | Actual public P1 revision and both original/current result identities |
| Versioned storage | Populated P2 v7 history/outbox/native/communication state exists | Owner explicitly upgrades to v8 or restores a backup | Serving code performs no DDL; old canonical bytes/identities remain; old upgrades never downgrade | Selected outbox inspection, native bind/revoke and current-case inspection work on v8; a fresh process reads retained receiver rows | Actual upgrade, rollback/repeat validation and backup/restore |
| Bounded ownership | Admission, SQL, external case read or receiver transport is slow | Waiter aborts, deadline expires or close is observed | Actual operations retain their slots; no transaction spans external I/O; incomplete cleanup is reported | Original settlement permits retrying close and useful independent reads | Held operations, capacity, abort and cleanup regressions |

## Interfaces and ownership

### P1 delivery authority

P1's existing public delivery v3/profile-v4 API already stores an opaque original
result body of at most 8,192 bytes. It remains the sole durable accepted-work,
issuance, cancellation, deadline and result authority. No P1 storage migration or
new accepted-work queue is needed. Its delivery guard does not atomically fence a
current case revision across a P2 enqueue; current applicability is an as-of read.

### P3 fixed-policy delivery client

P3 adds FixedPolicyDeliveryClient with the same public constructor/default limits
and DelegationDelivery return type as the v1 client. It uses a structural
ResultReceiverPort: receiver_id, accept(DeliveryIntent), find(DeliveryIntent) and
close().

- The existing ownership core and delivery algorithm are shared through closed
  typed v1/v2 paths. Preserve v1 APIs, canonical bytes and action adapters.
- A new v2 delivery requires candidate applicability and eligible_at_commit. An
  already possible original delivery reconciles through find only.
- Revalidate the original request/result/issued attempt and both immutable scoped
  sources before trusting stored state.
- V2 projection, guarded action and autonomous processing remain outside this
  slice.

### P2 receiver storage

P2 introduces an explicit owner v7-to-v8 migration for immutable receiver metadata
linked to the existing reply intent. Result acceptance and notice enqueue commit
inside one existing protected outbox transaction. They share its pool, admission
lock, actual-call bound and maxReplies cap.

- The receiver row is a delivery receipt, not another work ledger or scheduler.
- The original P1 canonical intent, result digest, work/attempt/recipient and
  retained receiver identity remain exact.
- An outbox notice has different bytes and therefore a different body digest.
  Never substitute it for the P1 result digest.
- Ordinary uncertain carrier behavior remains unchanged.

### P2 current-channel result read

A separate bounded result read works in this order:

1. Derive scope/case/conversation from the current native grant.
2. Capture protected P2 state.
3. Release SQL for one external public P1 current-case read.
4. Perform a fresh protected disclosure check.

Preserve the existing rehydration v1 envelope rather than silently widening it.
The read returns the original result/receipt and separately labelled
applicability/as-of facts. It creates no input, generation, confirmation,
execution or send.

### Ownership and configured bounds

| Owner | Owns |
| --- | --- |
| P3 agent | Python completion contracts/core/tests |
| P2 agent | TypeScript receiver/storage/read contracts, migration/runtime version guards and package exports/tests |
| Root | Shared wire fixtures, thin application transport, actual integration orchestration, discovery and documentation |

The public constructors and actual schedule are fixed below before measurement.
No dependency, lock or container-image refresh is planned.

| Boundary | Concrete interface and configured bound |
| --- | --- |
| P3 delivery | FixedPolicyDeliveryClient; ResultReceiverPort receiver_id/accept/find/close; two actual calls, five-second caller budget, one-second close observation |
| P2 acceptance | ChannelResultReceiver(outbox, configuration, options); receiverId; accept/find(publisherToken, originalIntent, signal); two facade calls; exact P1 canonical ASCII intent at most 16,384 bytes, decoded opaque body at most 8,192 bytes |
| P2 return read | ChannelResultReader(outbox, inbox, CurrentCasePort, configuration, options).native(nativeBearer, deliveryId, signal); one reader call; view at most 32,768 bytes; same existing outbox four-call/two-connection owner |
| Identity subset | Scope/recipient use the explicit P3-compatible lowercase 64-character subset; unsupported wider P1/P2 identifiers reject without truncation or rebinding |
| Root local adapter | Fixed loopback accept/find routes; separate publisher bearer, original result digest and exact six-field receipt; at most two retained HTTP calls, two-second waiter, unrounded five-second actual transport budget and one-second close observation |
| Storage schedule | Sixteen storage assertions and four return assertions; 180 seconds total including twenty cleanup seconds; at most sixteen owned process groups, 64 KiB per capture stream and 2 MiB aggregate; at most two P2 and two P1 schemas |

### Process roles

The sixteen process roles are:

| # | Role |
| --- | --- |
| 1 | Public compilation |
| 2 | Fixture compilation |
| 3 | Setup |
| 4 | Upgrade |
| 5 | Exercise |
| 6 | Receiver commit-before-ACK |
| 7 | Recovery |
| 8 | Bounded receiver host |
| 9 | P3 public consumer |
| 10 | Backup container lookup |
| 11 | Dump |
| 12 | Copy |
| 13 | Restore |
| 14 | Restored read/cap checks |
| 15 | Schema cleanup |
| 16 | Backup removal |

The fixture host accepts no browser scope selector and caps native read requests
at 256 bytes. No room, provider, carrier call, supplier mutation or booking action
belongs to this schedule.

### Actual schedule

The actual P3 consumer uses an explicitly local scripted specialist port. Three
real P1 requests/results create two P2 receipts/notices.

- Original result A is prepared/begun through public P1 and accepted by P2. Its
  sender receipt write is then intentionally omitted. Fresh ports must find only
  and record the same receipt. This is an ACK-loss simulation, not a P1
  sender-process crash claim.
- The separately owned Node receiver caller is actually killed after its public
  acceptance and recovers through a fresh process.
- Public P1 CAS advances one case from one to two. An undelivered stale result is
  denied before a new intent, while explicitly accepted current work progresses.
- Both B reads retain the original result/receipt and the separately observed
  revision two. These are native-grant data reads without an actual RTC room; the
  joined media demonstration remains separate.

### Later origin binding

The later generic P2 PreparedDispatch-to-P3 adapter requires an explicit versioned
origin binding. It must retain the original prepared payload digest and
operation/receipt identities. Current fixed-policy v2 context has no such field.

- Do not echo an unpersisted digest, place authority in model/evidence prose,
  derive another key from changed content or advertise stable lookup equivalence.
- Trusted adapters must also handle P2 int64 decimal revisions/128-character
  identifiers versus P3 positive bounded integer revisions/64-character
  identifiers explicitly.

## Failure cases and validation

| Gate | Applicable and why | Exact tests/assertions | Prerequisite/resource/time bound | Expected status/artifacts |
| --- | --- | --- | --- | --- |
| G-READY | New public Python/TypeScript/wire seam | Reviewed immutable intent/receipt mapping, versioned storage, authority and finite fault schedule | Existing pinned offline toolchain; freeze before actual runs | API review and selected plan; no measurements claimed by planning |
| G-FAST | New public runtime and discovery | Focused suites, then full make check, frontend-check, format-check and documentation check | Existing repository interpreters and exact pinned versions | Nonzero tests, zero required skips and no type/lint violations |
| G-CONTRACT | Untrusted receiver/read boundaries | Duplicate/unknown keys, altered canonical bytes/digests, foreign identities, size/range limits and secret sentinels | No provider reads/calls in offline tests | Fail closed before writes/disclosure and preserve original replay |
| G-DURABLE | New P2 v8 metadata and P1 delivery reconciliation | Atomic receipt/notice, commit-before-ACK recovery, replay/conflict/cap, lookup-only unknown and useful current progress | Real isolated PostgreSQL; exact owned process/schema cleanup | Actual independent rows and exact original public identities |
| G-MIGRATION | Explicit additive schema upgrade | Populated v7 upgrade, rollback, repeated validation, old APIs on v8, actual backup/restore | Restricted owner/runtime roles; no serving DDL | Original bytes/identities preserved; runtime cannot repair drift |
| G-PACKAGE | Reusable public APIs and exports | Direct/rebuilt Python artifact and isolated npm consumer with current source/archive parity | Existing artifact builders; frozen inventories updated explicitly | No checkout product fallback or undeclared dependency |
| G-OBS | Honest errors, uncertainty and retained capacity | Safe-code/metric/event assertions, observer outage, aborted waiter, held actual operation and repeated close | Fixed enums, finite labels and numeric units | No raw body/token/dependency text; telemetry cannot change commitment |
| G-MEDIA | Joined conversation is a dependent next slice | Preserve existing native/rehydration qualification; define joined accepted-input/result identity joins separately | No new audio/provider claim from storage tests | Pending until actual joined browser/audio journey runs |
| G-RELEASE | Full project gates and final demo remain active | Complete P2/P3 acceptance, supported platforms, configured-provider integration and sanitized video | Separate required current-source evidence | Missing/skipped/timed-out assertions remain non-passing |

### Retained-read case

The actual retained-read case uses explicit caller cancellation only after a
bounded barrier confirms that the real public P1 read completed. It then holds the
application port promise, aborts its caller and verifies:

- retained actual admission;
- released SQL;
- rejection at capacity;
- incomplete close;
- later useful progress.

The ordinary three-second facade budget is unchanged. Maintained
twenty-millisecond ignored-operation tests supply separate timeout evidence. This
actual case does not establish cancellation of a live P1 HTTP request or
PostgreSQL query.

### Test order and cleanup

1. Start with narrow completion and receiver tests.
2. Run the existing v1 completion/action/processing,
   outbox/callback/send-policy and native/communication/rehydration regressions
   when affected.
3. Run actual PostgreSQL and installed consumers after the API freeze. Record
   exact runnable commands and artifacts with observed outcomes below.

Parent owners stop/reap their own children before removing their own schemas/work
files. Normal restart preserves state; no unrelated cleanup or destructive reset
occurs.

### Logging and metrics rules

- Logs expose finite operation/status/code and bounded safe correlation only.
- Metrics use numeric accepted/replayed/conflict/denied/unknown counts and actual
  active/pending gauges with declared units. No body, token, arbitrary route or
  exception message becomes a label.
- Translate dependency exceptions once to the existing safe error sets.
- Storage acknowledgement loss is uncertainty, not permission to repeat a receiver
  or carrier effect.
- Caller cancellation propagates while actual ownership remains retained until
  settlement.
- Update project designs within their existing standard sections, keeping
  implemented and planned claims separate.

## Results and handoff

Selected delivery/read qualification is complete. This contributes to P3-I19 and
P2-I22; it does not complete either entire task or a charter row. P1 remains the
durable execution/result/case authority. P2 retains one immutable original receipt
and its linked fixed notice. Current native disclosure uses separately timed P1
facts and a fresh final grant check.

| Gate | Exact command or retained report | Observed outcome and scope |
| --- | --- | --- |
| Source storage/return | `.venv/bin/python -B local-setup/scripts/p2_result_receiver_check.py --report .local/validation/p2-result-receiver/source-fourth-04.json` | Sixteen storage/four return assertions, zero skips, sixteen owned groups, 10.388 seconds and complete cleanup |
| Current installed artifacts | `.venv/bin/python -B local-setup/scripts/p2_result_receiver_package_check.py --report .local/validation/p2-result-receiver-package/package-final-03.json` | Twenty-five stages, 46.481 seconds, complete cleanup and indexed final states for twenty-five distinct successful process groups; eight original offline assertions, twenty copied fake-port tests and nine negative codec inputs remain separate from the actual source twenty |
| P2 compatibility | Full `p2_postgres_check.py` plus routing, confirmation, outbox, callbacks, send-policy, native, communication, rehydration, playback and rehydration-media checks | 187 assertions in eleven primary fresh lanes, zero skips and complete cleanup; original profile versions retained |
| P3 compatibility | `make p3-completion-check`, `make p3-processing-check`, `make p3-action-races-check`, `make p3-recovery-check`, `make p3-native-policy-check` | Seventy-four backend assertions and three separately counted browser groups in five fresh lanes; all passed with cleanup |
| Shared Python/harness | `make check` | 2,669 tests, zero required skips, lint, broad typing over 151 files and selected strict typing over 166 files passed |
| Shared frontend | `make frontend-check` | 1,605 tests: 622 console, 804 P2 and 179 specialist; formatting, types and default/two optional builds passed |
| Python formatting | `make format-check` | 454 Python files already formatted |
| Documentation | `.venv/bin/python -B -m harness.documentation_check` | 121 maintained documents passed; no diagram body changed in this slice |
| Final read-only residual audit | One owned process with a twenty-second work deadline and twenty-five-second final cleanup deadline | Passed in 1.271 seconds; zero matching test namespaces, selected database backends and LiveKit rooms; original M1 row unchanged |

### What the source journey showed

The source journey uses a supplied local scripted specialist port. Three real P1
accepted requests/issued results create two P2 notices.

- Original A's public P1 possible marker precedes P2 acceptance. Omitting the
  sender receipt write simulates ACK loss. Fresh ports recover through find only.
- A separately owned receiver caller is actually killed after commit.
- Public case CAS advances revision one to two. Stale undelivered work is denied
  before intent creation, while explicitly accepted current work progresses.
- Returning data reads use current native grants without an RTC room.
- No carrier/provider call or supplier mutation belongs to this new seam.

Independent SQL joins bind exact canonical requests, immutable evidence, issued
attempts, result digests, P1 possible/receipt state, P2 metadata and the different
notice digest. Both full thirty-table SQL restore snapshots match. The restored
profile reaches eight replies/seven result rows, preserves replay/read access and
rejects a fresh ninth result without changing protected rows. Selected old APIs
exercised on v8 are outbox inspection, native bind/revoke and current-case
inspection. Historical compatibility lanes do not establish every API on v8.

### Package inventory

The final package inventory binds 129 entries and 130 physical private files;
forty-five directories have mode 0700. Its six archives independently preserve:

| Payload set | Count | Notes |
| --- | --- | --- |
| P1 Python runtime payloads | 77 | None |
| P3 Python payloads | 37 | Through direct/source/rebuilt artifacts |
| P2 npm payloads | 124 | None |
| Specialist npm payloads | 32 | None |

Package manifests are counted separately. P2 source/archive manifests match
decoded semantics; archive/install manifest bytes match exactly.
Runtime/codecs/types execute from private installations, with no checkout product
fallback. All 224 package source bindings and all 202 actual-source bindings
remain equal to their qualified runs. The selected platform is macOS arm64 with Python 3.14.10,
Node 24.22.2, TypeScript 7.0.2 and Agents 1.8.11. Other platforms retain separate
qualification.

### Preserved failures and corrections

- **First shared Python run.** It failed its old source census after four new
  public TypeScript modules were introduced. Discovery now explicitly includes
  those four modules and requires 81 sources. It was not relaxed to omit new code;
  the final full suite passed.
- **First source run.** It failed during exercise with complete cleanup.
  Controlled regressions reproduced genuine native AccessDenied becoming
  Unavailable through legacy transaction normalization. The narrow correction
  translates that specific class/code at both grant checks; unexpected storage
  errors remain unavailable. The original caught code was not retained, so
  attribution of that first failure remains an inference.
- **Second source run.** It failed before the intended retained-read hold, with
  complete cleanup. Its short fixture deadline did not establish the required
  post-public-read barrier. The corrected actual schedule explicitly aborts only
  after the public P1 read completes, retains actual capacity while the
  application promise is held and proves useful progress after settlement.
  Separate maintained timeout tests cover deadline observation. This is not
  evidence of cancelling live HTTP or SQL I/O.
- **Third source run.** It failed in the consumer, with ten groups and complete
  cleanup. It recorded one scheduled receiver-caller kill and one host kill during
  failure cleanup. The consumer reused an owner UUID as a command ID; its retained
  original UUID violates the lowercase-first command grammar. A controlled
  actual-runner regression proves rejection before admission, then namespaced
  progress and replay. The original caught exception was generic, so exact
  live-error attribution remains an inference. Owner identity and runtime grammar
  were preserved.
- **First package run.** It remains non-passing after reporting twenty-five
  completed commands and complete cleanup. Its final inventory rejected four
  nested input directories created 0755 instead of 0700; no outer index existed.
  The fix creates each missing level privately under a verified anchor and rejects
  unsafe existing paths without chmod. New final process-group evidence and stable
  ownership/error snapshots address the audit's observability gaps. All failed
  files and original modes remain unchanged. The second package run passed. The
  final third build only updates a packaged guide to distinguish the passed source
  seam from remaining native/media integration.
- **Extra agent-only P2 command.** It passed one case. Its wrapper forecast 23;
  the actual report correctly retained one. A separate fresh full default 23-case
  run supplies the primary compatibility report. The extra case is excluded from
  the 187 total, and the original wrapper/narrower report are preserved.

### Evidence, ownership and next work

The durable local closeout report is `.local/validation/phase43-closeout-01.json`.
Its indexed private artifacts retain exact commands, logs, source freezes,
controlled proofs, independent reviews and final live observations. The original
source/package reports retain their own indexes. No prior passing or failed
checkpoint was rewritten. Normal application state and the original M1 intake are
preserved; no Git remote or CI run is needed. AI-assisted implementation,
validation and independent review are recorded in the machine evidence. Portfolio
claims still require personal inspection and explanation.

Next steps, in order:

1. Persist an explicit versioned original P2
   profile/operation/input-receipt/payload-digest binding through existing P1
   opaque work storage. Preserve the first accepted request deadline and evidence
   through equal replay and concurrent winners.
2. Only then join one native SDK owner to room A/B voice/text and signed simulated
   SMS.

Undelivered historical work needs its own authorized origin/work read.
Accepted-work discovery/whole-stack restart, configured-provider composition,
complete P2/P3 charter registrations and the final video retain separate gates. P2
native generation keeps tools disabled, native case revision zero stays read-only,
and receiver acceptance remains distinct from human acknowledgement or mutation
permission. The broader ecosystem goal remains active.
