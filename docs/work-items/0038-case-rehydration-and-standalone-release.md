# Case rehydration and standalone release

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Record the plan, observed verification and handoff for P2-I18 case rehydration and P3-I15 standalone consumption |
| Audience | Engineers changing P2 current-case rehydration or the P3 standalone package command; coding agents |
| Scope | Selected P2-I18 and P3-I15 local gates; excludes P3 modalities, load, comparison and the full integrated release |
| Owns | Change plan, observed verification and handoff for P2-I18 and P3-I15 |
| Related | [Work item 0037](0037-playback-evidence-and-process-recovery.md) · [Work item 0039](0039-bounded-channel-workloads-and-image-evidence.md) · [P2 task plan](../implementation/p2-channel-continuity.md) · [P3 task plan](../implementation/p3-delegation-reliability.md) · [Validation plan](../validation-plan.md) |

## Behavior and scope

This work item implements P2-I18 and P3-I15 after the
[completed playback/recovery phase](0037-playback-evidence-and-process-recovery.md).
The [P2 plan](../implementation/p2-channel-continuity.md),
[P3 plan](../implementation/p3-delegation-reliability.md),
[shared design](../../Design.md), [validation authority](../validation-plan.md)
and project charters own the requirements.

| Project | Task | Behavior |
| --- | --- | --- |
| P2 | P2-I18 | Verified current-case rehydration; contributes to P2-09/P2-12 |
| P3 | P3-I15 | Reproducible standalone consumption; contributes to standalone P3-01/P3-08 evidence |

Selected task completion does not automatically register any full charter row.
Preserve qualified P1 and prior native/recovery behavior, the default M1/P1
services/UI and the pinned dependency/image baseline.

Before any maintained edits, all 803 previous artifact hashes and 698 current
public source hashes matched the closed checkpoint. Provider/private-CA/config
files were not read. This phase uses synthetic fixtures, local Docker PG/SFU,
SDK/browser processes and offline package caches. Git publication, remote CI, paid
inference, P3 modalities/load/comparison and the full integrated release are
outside this slice.

### P2 current-case rehydration

P2 opens a fresh verified interaction after a room closes. It restores:

- authoritative case facts and the current revision;
- bounded relevant accepted history;
- pending original work references;
- separately attributed communication evidence.

A new room is not a new business case. An old room, carrier account or familiar
phone number is not current account authorization. Historical read/replay APIs
retain their old meaning. A new current-grant-gated read-only facade supplies
rehydration. It creates zero new accepted inputs, operations, confirmation, sends,
effects or generation. A later new accepted user input demonstrates useful native
continuation separately.

### P3 standalone consumption

P3 turns the previously qualified libraries and private qualification approach
into a maintained, reproducible standalone build/install/example command.

- Fresh P1/P3 wheel/sdist/rebuilt and applicable npm artifacts are consumed
  through public installed imports.
- The public completion example actually runs against the local specialist,
  receiver and an exact separately supplied confirmation.
- Fresh-process replay preserves original facts and adds no new
  invocation/delivery/effect.
- Keep owner bootstrap/worker test instrumentation distinct from the public
  consumer.

### Terms used in this record

| Term | Meaning |
| --- | --- |
| Implementation task IDs | Such as P2-I18; identify tasks in the project task plans |
| Acceptance IDs | Such as P2-09; identify rows in the project charters |
| Selected | Gates and tasks chosen for this work item; passing them does not complete a full charter row |
| Gate names | Such as G-READY and G-DURABLE; refer to the engineering gates in the [validation plan](../validation-plan.md) |
| PostgreSQL (PG) | The actual database used by the durable gates |
| Selective forwarding unit (SFU) | The self-hosted LiveKit media server |
| SDK | Software development kit; here usually the pinned LiveKit Agents SDK |
| Real-time communication (RTC) | The WebRTC media path through LiveKit |
| Data transfer object (DTO) | A closed, validated value passed across a public boundary |
| Pulse-code modulation (PCM) | Raw audio sample data observed at the browser |
| Compare-and-set (CAS) | A write that succeeds only when the stored revision still matches the expected revision |
| Process ID (PID) | Identifies an operating-system process |
| M1 | The original confirmed-investigation intake data, which every phase preserves |

### Criteria

| Criterion | Given | When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- | --- |
| P2-09 contribution | Verified native A with original case/history/work/evidence | Close A, accept a verified fake SMS and join fresh B | No copied authority or duplicate original work; old communication remains source-bound | Current case/revision and relevant voice/text/SMS history load; new accepted input gets a genuine B reply | Actual PG and browser/SDK, exact source/receipt joins |
| P2-12 contribution | Retained history plus separately current native/SMS permission | Forge scope/room/participant; revoke, expire or reassign association | No new disclosure or generation; old trusted history credential semantics remain unchanged | Newly verified current permission can load its own current case | Current-permission races, expiry clocks and account negatives |
| Case authority | Stale summary and case changing during a read | Rehydrate then attempt a new command | Summaries cannot override authoritative facts; separately observed sections are not a cross-store atomic snapshot or write permission | Existing guarded expected revision/exact confirmation still controls later work | Public case adapter/standalone equivalent and negative contract cases |
| Native lifecycle | B begins while A reads/replies settle late | Timeout, cancellation, disconnect and stale response arrival | Original room/generation/speech facts cannot become B playback/completion/interrupt authority; actual I/O stays owned | B progresses after actual cleanup and verified context loading | Actual SDK lifetime tests, browser lifecycle and ownership metrics |
| P3 standalone | Fresh built artifacts, explicit local trusted adapters and no P2 gateway | Import/typecheck/run installed examples | No checkout product imports, startup listener/DDL, inferred consent or second execution owner | Actual public completion delivers useful strict result and one authorized fake effect | Eight offline and eight actual lab assertions |
| P3 replay | Known completed result/delivery/action before caller ACK | Kill owned consumer and replay in a fresh process | Original receipts/results remain; zero new issue/complete/action writes, specialist invoke, receiver accept or supplier apply | Lookup/read/inspection still work and known facts survive later cancellation | Independent PG/receiver/supplier joins and exact public command identities |

## Interfaces and ownership

### P2

P2 owns typed rehydration contracts, the current-grant facade/P2 snapshot store,
standalone and existing public-P1 read adapters, the optional Python context
loader, project fixtures/tests/examples and project guides.

- Preserve the old inbox/history and v7 evidence APIs.
- Prefer no schema change when existing v7 state suffices. Any new persisted state
  requires explicit owner versioning before serving.
- Scope derives from the trusted current native binding, or from the original
  accepted-SMS sender and current association. It never derives from arbitrary
  body case/account labels.

P2 and authoritative case reads are separately observed. The facade works in this
order:

1. Read an authorized, coherent P2 section.
2. Call a narrow read-only case port outside SQL.
3. Perform a fresh protected current-permission check before disclosure.

Before implementing this boundary, freeze the exact observation/expiry/lock
semantics, closed fields, original identity joins, cursor/truncation rules and one
total UTF-8 snapshot cap. Native model context must label history as untrusted
data and never gain confirmation/quote/mutation tools. New-room facts retain
original bindings and IDs.

### P3

P3 owns the maintained standalone package driver, the configured public consumer,
the unadapted public completion/metadata example invocation, specialist/owner
fixtures, focused tests and five guides. P1's 77 and P3's 30 production payloads,
existing public APIs and storage remain unchanged unless a reviewed concrete gap
proves otherwise. Build a fresh P1 dependency wheel instead of referencing a prior
local UUID or private script. Label the supported host/platform and installed
proof scope.

### Root

Root owns this work item, independent protocol review, UI/context presentation and
actual P2 storage/media orchestration, Make/discovery/shared docs and the
checkpoint.

- Parallel work uses frozen interfaces. Actual PG lanes stay serialized.
- No normal measurement starts until exact source/child/env/report/proof contracts
  are retained.
- Independent reviews disclose authored components and test/fixture
  contributions.

## Failure cases and validation

| Gate | Applicability | Fixed bounds | Required result |
| --- | --- | --- | --- |
| G-READY | All selected interfaces and case/grant/authority boundaries | Prior checkpoint verified; immutable protocol before implementation and source snapshots before measurement | P2 eighteen-case storage/three-group media and P3 sixteen-case protocols/source proofs froze before measurement and passed selected qualification |
| G-FAST/G-CONTRACT | New values, cursor/byte/role checks, native context and maintained package command | Pinned Python/Node; all new sources in lint/type/unit/build/discovery | Positive, negative, useful-progress and actual SDK cases; no skips/zero tests/providers |
| P2 G-DURABLE | Current native/SMS authorization, coherent P2 read, external case and final disclosure fence | 180 seconds total/15 cleanup, at most 32 commands, 4 KiB per stream/256 KiB aggregate, 32 KiB report; total context ceiling 64 KiB UTF-8 including framing | Exact identity/source/snapshot joins; zero new business work on rehydrate; fresh clocks/owned SQL order observations and later useful progress |
| P2 G-MEDIA | Voice/text, close, fake SMS, fresh-room current-case restore and native reply | 240 seconds total/20 cleanup, at most 32 commands, 8 KiB per stream/512 KiB aggregate, 32 KiB report; exact case/child count frozen before measurement | Actual local RTC/browser/SDK, current case/context loaded, original facts preserved and complete cleanup |
| P3 G-PACKAGE/G-DURABLE | Maintained isolated public consumers and actual completion/replay | Combined 360 seconds total/20 cleanup, at most 40 commands, 64 KiB per stream/2 MiB aggregate, 32 KiB report; each business work horizon at most 60 seconds | Eight offline plus eight lab assertions; exact supported host, archive/source parity, one actual owned kill and one independent authorized fake effect |
| G-OBS | Current-grant/read/cancel/cleanup/telemetry failures | Fixed event/code/source/outcome and numeric occupancy/duration; bounded sinks/proof inventories | No identifiers in metric labels or bodies/secrets/raw exception text in logs; primary error survives secondary sink/close failure |
| Compatibility | Affected prior native/evidence/authority/standalone paths | Preserve previous reports; source-bound affected PG/native/installed regression selection before closure | Old v6/v7 and current case/replay/permission semantics remain truthful; full shared fast/frontend/format/docs/Mermaid checks pass |
| Final handoff | Instructions/design/README, clean local reproducibility and preservation | Exact physical artifact index, private 0700 directories/0600 regular files; normal stack doctor/smoke/M1 and read-only residual checks | Current source/public input parity, independent review and all owned cleanup; complete charter/release remains separately gated |

Rules for these gates:

- The fixed bounds are ceilings, not observed results.
- Freeze exact named modes, case counts, wire fields, safe diagnostics and proof
  sizes before normal execution.
- Never widen timeout/authority/capacity guards to turn a failed measurement into
  a pass.
- Failed attempts remain failed. Diagnostic runs cannot qualify normal gates.
- Keep ignored cancellation and actual resource settlement visible. A stopped
  waiter is not proof that work stopped.
- Run narrow tests first, affected actual gates next, then full shared gates.
- Provider calls and private credential reads are not part of these validations.

## Results and handoff

Selected P2-I18 and P3-I15 are completed. These passed their selected local gates:

- the read-only current-grant facade;
- the closed immutable context DTO;
- the public P1 projection bridge;
- the optional native context loader;
- the two-room browser continuation.

The maintained P3 command consumes fresh installed public artifacts and
demonstrates completion/replay without another execution owner.

| Selected gate | Observed result | Scope and limits |
| --- | --- | --- |
| P2 storage | 18 passed in 6.534 seconds | Actual PG permission/expiry/revocation, coherent snapshot, real public P1 supplier source, owned kill/fresh replay and populated restore |
| P2 media | 3 groups/1 Playwright case passed in 35.797 seconds; 10 children | Real fixture voice plus native chat in A, A closure/deletion, signed SMS with zero owned A/B rooms, fresh B context before a new reply; full cleanup |
| P2 Python distribution | 111 tests, 9 runtime payloads, 15 commands/52.364 seconds | Fresh wheel/sdist/rebuilt parity, default SDK-free import, optional pinned SDK/public types and unadapted tests; this package gate alone makes no RTC/PG claim |
| P2 npm consumer | 7 stages passed in 2.1696 seconds; 96 byte-equal payload files plus semantic manifest parity | Isolated offline strict public NodeNext consumer, real v7 PG/HTTP, original receipt/context fresh replay, zero new read side effects; supplied synthetic case/operation/SDK facts, no RTC/P1/provider claim |
| P3 standalone command | 8 offline plus 8 actual assertions passed in 58.885 seconds | Fresh declared artifacts and installed public examples, one owned kill/SQL graph, original replay and one separately authorized fake effect |
| P2 compatibility | 166 assertions across 9 distinct serial lanes passed in 98.997 seconds | Recovery 23, routing 22, confirmation 18, outbox 24, callbacks 24, send-policy 30, communication 16, native 6 and playback 3; every cleanup passed |
| Shared fast/frontend | 2,148 Python and 1,224 TypeScript tests passed | Python: 49 P1, 111 P2, 301 P3 and 1,687 root; TypeScript: 503 console, 632 P2 and 89 specialist; zero skips/failures |
| Shared quality | Broad/strict typing 144/132; Python format 387; documentation 113 | All selected checks passed; 29 Mermaid bodies passed syntax-only parsing, not behavioral qualification |
| Ordinary stack | Doctor/smoke passed; 10 audio frames; original M1 preserved | Transport evidence remains separate from product inference or human hearing |

### What the media and storage runs showed

The media run retained three native inputs and one separate SMS, four original
operation acceptances, three responses and six SDK observations. Client reports
were disabled, leaving client evidence unknown despite separately observed PCM.
Context loading generated zero replies. B's actual public model context contained
the current revision 2 and three original voice/chat/SMS history receipts; A's old
responses remained inert. Original receipt/source/digest joins and actual cleanup
were independently reviewed. New input, generation, playback, supplier facts and
human acknowledgement remain different observations.

The storage lane read the actual public P1 case before and after a separately
confirmed leased fake-supplier mutation at unchanged case revision 0. Its changed
projection fingerprint and real supplier result demonstrate why an equal request
revision cannot establish workflow/supplier freshness. Current-case data is
allowlisted; quote/confirmation/control payloads never enter model or UI context.
P1/P2 observations remain separately timed and non-atomic, with a final protected
permission check at disclosure admission. A later revoke cannot retract bytes.

### Failed attempts and corrections

Failed attempts remain failed, with their reports and available safe diagnostics
preserved.

Storage:

- It first stopped on the public-source/private-proof preflight, then on an extra
  reference-fixture field.
- A later real semantic-error normalization defect was fixed in the new read store
  without changing the legacy transaction authority. Rollback/resource ownership
  and safe observer classification were tested.
- The next replay failure was a fixture JSON-prototype comparison, corrected
  through the public DTO validator while preserving all original facts.
- Fresh selected storage runs then passed, including the final dependent-cleanup
  guard.

Media:

- It first stopped before any child/SQL/room on an incompatible private barrier
  stem. Actual producer/FileBarrier/PID interoperability now uses the existing
  lowercase/underscore harness contract.
- The second browser journey completed, but the whole gate correctly failed on a
  third-party reporter's 0644 proof file. Per-child umask 077 plus exec preserves
  the owned PID and creates private files before reading. No permission guard or
  timeout was weakened.
- The third full normal run passed all proofs.

The npm consumer's early type/pending-work expectation failures and superseded
offline preparations remain distinct from its final pass. Process-retention and
dependency-tier cleanup fixes were independently reviewed and fault-tested before
that final actual run.

### Revision 0 boundary

The existing native command/communication contracts require positive case
revisions. P2-I18 accurately reads/displays public P1 revision 0 and prevents new
native intake/generation there. The actual standalone demonstration uses verified
revision 1, a separate SMS CAS to revision 2 and a fresh B reply. A coherent
versioned zero-revision native contract remains required before full integrated
release. Neither zero-to-one mapping nor automatic business revision is allowed.

### Next work and evidence

Next are P2-I19/P2-I20 and P3-I16 before complete release. The catalog remains 55
defined/24 registered: all 17 P2 and the remaining 14 P3 charter rows stay
planned. Broader modalities, general recognition/inference quality and load retain
their own gates. No new default service, provider/private-CA read, paid call,
remote CI, publication, human acknowledgement or physical exactly-once promise
follows from this selected phase.

Exact commands, source/archive identities, failed reports, independent reviews
and retained proof inventories belong to machine evidence. Previous closed
checkpoints remain historical evidence.

Final artifact seal: recorded in the retained checkpoint. That machine record owns
the exact source/archive inventory. This completion marks only the selected scope
and registers no additional complete charter row.
