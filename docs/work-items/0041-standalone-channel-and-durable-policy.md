# Standalone channel application and durable fixed-policy prerequisite

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Record the plan, observed verification and handoff for the P2-I21 standalone channel application and the P3-I18A durable fixed-policy prerequisite |
| Audience | Engineers changing the P2 standalone starter or the P3 fixed-policy v2 facades; coding agents |
| Scope | Selected P2-I21 and P3-I18A gates; excludes native background conversation, P2-17 fresh-agent review, integrated release and the demo video |
| Owns | Change plan, observed verification and handoff for P2-I21 and P3-I18A |
| Related | [Work item 0040](0040-operations-ui-and-fixed-policy-evidence.md) · [Work item 0042](0042-responsive-native-policy-and-compact-demo.md) · [P2 task plan](../implementation/p2-channel-continuity.md) · [P3 task plan](../implementation/p3-delegation-reliability.md) · [Validation plan](../validation-plan.md) |

## Behavior and scope

This work item advances P2-I21 and the versioned durable prerequisite for P3-I18.

| Project | Task | Behavior |
| --- | --- | --- |
| P2 | P2-I21 | One installed application that demonstrates structured case routing, original history, synthetic delivery and restart recovery without P1/P3 services |
| P3 | P3-I18 durable prerequisite | Explicitly typed fixed-policy version-2 acceptance and issued execution over existing public P1 ports |

This prerequisite does not complete native background conversation or its browser
demonstration.

Preserve the completed
[0040 checkpoint](0040-operations-ui-and-fixed-policy-evidence.md), P1 authority,
original M1 data, all version-1 wire defaults, dependency resolutions and the
default Compose/UI. The [P2 charter](../projects/channel-continuity-scope.md) and
[P3 charter](../projects/delegation-reliability-scope.md) remain authoritative.
P2-16 is advanced through a real installed application. These are separate gates:
P2-17 fresh-agent review, complete native/integrated acceptance and the broader
P3-I18 native adapter. The local ecosystem and final demo-video goal remains
active.

### Terms used in this record

| Term | Meaning |
| --- | --- |
| Implementation task IDs | Such as P2-I21; identify tasks in the project task plans |
| Acceptance IDs | Such as P2-16; identify rows in the project charters |
| P3-I18A | The durable fixed-policy prerequisite slice of P3-I18 qualified here; the native conversation slice follows separately |
| Selected implementation and validation | The gates chosen for this work item; passing them does not complete a full charter row |
| Gate names | Such as G-READY and G-DURABLE; refer to the engineering gates in the [validation plan](../validation-plan.md) |
| Command-line interface (CLI) | The thin executable around the installed starter |
| Compare-and-set (CAS) | A write that succeeds only when the stored revision still matches the expected revision |
| Hash-based message authentication code (HMAC) | A keyed signature value; it is never logged |
| SDK | Software development kit: a reusable public library such as P2's package or the LiveKit Agents SDK |
| Selective forwarding unit (SFU) | The self-hosted LiveKit media server |
| Data definition language (DDL) | Schema-changing SQL; runtime executes none |
| M1 | The original confirmed-investigation intake data, which every phase preserves |
| Proof of concept (POC) | This local repository's delivery target |

### Criteria

| Criterion | Given | When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- | --- |
| P2-16 standalone | Fresh npm installation, explicit role-separated setup and synthetic scope | Bootstrap, associate, accept and route while gateway is quiescent, then serve | Runtime executes no DDL; standalone imports no P1/P3 service; ordinary unknown send cannot auto-retry | Same installed starter demonstrates route, original history and fake delivery | Source/unit, isolated npm consumer and actual PostgreSQL/loopback HTTP |
| P2-16 recovery | Original accepted input/key and app-owned independent synthetic receipts | Kill only owned process after observed commitment or lose external ACK | Replay preserves original identities; external receipts are observations, not another workflow queue | Fresh process recovers eligible work and original facts | Explicit commit/ACK barriers, child ownership and independently read rows |
| P3-I18 prerequisite | Explicit v2 request and immutable scoped policy/fact sources | Accept and execute through new typed public facades | P1 is sole work/result authority; only a newly created fresh issuance can invoke | A valid fixed-policy candidate or clarification is retained | Unit plus actual P1 PostgreSQL/TS HTTP, source and installed |
| P3 historical result | Late, cancelled or superseded result with strictly supported facts | Observe and commit original result | Semantic validation precedes expiry disposition; no forged body commits | Strict historical facts remain inspectable with authority-assigned eligibility | Deadline/ACK-loss/replay fixtures and original result/feed bindings |
| Compatibility | Existing v1 consumer and P1 state | Run unchanged workflows and selected regressions | Default v1 types/bytes and v1-only completion/projection do not silently widen | Existing current work still completes | Full affected package/regression and shared fast gates |

## Interfaces and ownership

### P2 standalone application

P2 composes its existing public package APIs. A thin CLI separates:

- trusted config;
- application lifecycle;
- synthetic external HTTP;
- an application-owned PostgreSQL receipt adapter.

Explicit owner bootstrap creates the standalone fake receipt profile. Runtime only
appends/reads bounded immutable receipts. It creates no pending queue, scheduling
state, lease, worker or case clone. Original-key replay and changed-payload
conflict are checked before new capacity. Provider acceptance, callback delivery
evidence and human acknowledgement remain distinct.

Structured routing runs as an explicit command while the gateway is quiescent,
before dispatch sees the resulting revision. A model prepare hook cannot become a
hidden revision scheduler. One selected reference authority owns standalone case
state. Integrated public-P1 contracts remain a separate consumer lane.

### P3 durable fixed-policy facades

P3 adds explicit v2 coordinator/runner/view facades and a historical result
observation API. They share bounded lifecycle logic with v1 through closed typed
codecs. Existing public v1 constructor types/defaults remain stable.

P1 stores opaque canonical policy bytes and owns acceptance, issuance,
cancellation, eligibility and result history. No schema or P1 product changes are
planned. Current projection/refresh/completion/action adapters remain v1-only.
Revision 0 remains read-only/no-work. This prerequisite introduces no native SDK
tool, UI control, scheduler, autonomous retry, result notification or mutation
authority.

## Failure cases and validation

Freeze the exact named assertions, roles, child schedule, JSON proofs and limits
before actual measurement. The maintained per-project manifest and `--plan` output
must agree with the work-item table. A missing setup, skip, zero-test or timeout is
non-passing. Each real service lane runs under one root-assigned resource owner.
Shared PostgreSQL/SFU/build lanes are serialized when their fixtures overlap.

| Gate | Applicable and why | Exact tests/assertions | Prerequisite/resource/time bound | Expected status/artifacts |
| --- | --- | --- | --- | --- |
| G-READY | Both changes extend public consumers | Reviewed configuration, role separation, exact package inventory and assertion manifest | Explicit local settings; no provider credential reads | Plan and immutable pre-measurement source bindings |
| G-FAST | Product, examples and harness | Full Python/static/type/docs/format and TypeScript test/type/build gates | Pinned local toolchain; no remote CI | Nonzero suites, no required skips |
| G-CONTRACT | New executable and v2 public APIs | Closed config/errors; original replay/conflicts; v1/v2 typing and factual validation | Pure/unit plus exact installed consumers | Declared exports/bin, canonical bytes, safe errors |
| G-DURABLE | Existing P2/P1 durable execution | Named real PostgreSQL/HTTP recovery/late-result/ACK-loss controls | Finite child/byte/deadline/cleanup manifests | Original joined receipt/work/attempt/result facts and actual settled owners |
| G-OBS | New application and facades | Fixed safe event/error/metric values, sentinel exclusion, no body/credential diagnostics | Telemetry failure and ignored cancellation included | Actual producer changes; failed telemetry cannot grant acceptance |
| G-PACKAGE | Installed starter/new facades | Fresh archives installed outside checkout; runtime example and strict public types | Declared offline caches and real local services only | Exact payload inventory and actual executed public methods |
| G-MEDIA | Deferred native integration | No new media assertion belongs to this prerequisite | Existing affected media regressions stay separately labelled | No new voice/physical playback claim |
| G-RELEASE | Still pending | Full charter, native/integrated/provider/demo work continues afterward | Local POC only; no publishing prerequisite | Overall ecosystem remains incomplete |

### Commands

Use existing commands for applicable compatibility. The implemented commands are:

| Task | Command | Notes |
| --- | --- | --- |
| P2 standalone plan and check | `make p2-standalone-plan` and `make p2-standalone-check` | None |
| P2 starter P1 check | `make p2-starter-p1-check` | Separately reported |
| P3 fixed-policy work | `make p3-fixed-work-plan`, `make p3-fixed-work-check` and `make p3-fixed-work-package-check` | None |

Add their actual implementation and exact observed results before marking this
work item complete.

### Logging, retry and shutdown rules

- Log only finite event/code/status, numeric time/bytes/occupancy and scoped safe
  correlation values permitted by the existing observability contract.
- Translate dependency exceptions once into typed safe domain codes. Preserve
  cancellation and original uncertainty.
- Never log raw config, HMAC, credentials, request bodies, policy text or supplier
  URLs.
- Retries require explicit original-key reconciliation and the actual external
  capability. No transport suggestion grants permission.

Shut down in this order:

1. Stop admission.
2. Close dependent gateway/dispatcher/client owners.
3. Observe their actual settlement.
4. Close shared readers/pools.

Parent tooling reaps all owned processes before schema or private work removal.
Preserve primary failures and marked work if cleanup remains incomplete.
User-approved earlier cleanup applies only to the exact failed 0040 resources and
grants no blanket reset.

## Results and handoff

### Implemented behavior

The selected P2-I21 implementation provides:

- an inert public starter factory and executable;
- explicit owner/runtime configuration;
- a profile session mutex;
- a four-table synthetic external receipt store.

All explicit mutating commands require a quiescent gateway. The installed journey
declares twenty assertions, including:

- one owned kill after an actual input acknowledgement;
- original-key external lookup after a lost reply;
- ordinary/idempotent send evidence;
- source-bound callbacks;
- explicit recovery and populated restore.

The separate installed public-P1 lane has six assertions for revision CAS/unknown
acknowledgement, exact stale/current confirmation and allowlisted current facts.
It is independent of the standalone twenty. Neither lane qualifies native
execution at P1 revision 0.

### Selected gate results

| Selected gate | Assertions | Observed result | Evidence and scope |
| --- | --- | --- | --- |
| P2-I21 installed standalone | 20 | Passed in 12.574 seconds; 26 command groups, one planned kill and cleanup complete | 116 archive payloads plus package metadata; independent full-row/restore/source review |
| P2 installed public-P1 adapter contract | 6 | Passed in 15.322 seconds; 26 direct and three separately owned worker groups | Original receipts, complete public fingerprints, owner/supplier joins and cleanup |
| P2 compatibility | 187 | Passed eleven serial lanes in 158.453 seconds | Includes actual native/playback/rehydration regressions; no model inference claim |
| P3-I18A durable fixed-policy source | 12 | Passed fresh final-source qualification | Source proof, thirteen joined work/attempt identities and independent literal review |
| P3-I18A durable fixed-policy installed | 12 | Passed fresh final-archive qualification | Exact Python 36/npm 32 inventories, public example and isolated consumer typing |
| P3 offline package | 8 | Passed separately within installed qualification | Includes the public non-default exception-code type regression; distinct from durable twelve |
| Public HTTP client regressions | Four lanes of 20 each | Passed source/installed fixed-policy and image gates | Preserve original archive identities and reviewed type-only runtime equivalence |
| P3 compatibility | 146 | Passed all ten lanes with cleanup | Original source-bound result; final annotation/fixture equivalence independently reviewed |
| Shared fast/frontend checks | 2,537 Python; 1,501 TypeScript | Passed with zero required skips; all builds and type checks passed | Broad/strict Python 150/156; Python formatting 433; all producer assertions remain separately counted |
| Documentation and design syntax | 119 documents; 41 Mermaid diagrams in eleven designs | Passed structural documentation and Mermaid parsing, including invalid-syntax control | Diagram syntax does not establish a rendered visual review |
| Ordinary doctor/smoke and original M1 | Eight transport checks and preserved baseline | Passed; original confirmed M1 remains queued with identical public row bytes | Final read-only fixture namespace/selected room checks found no residuals; no inference claim |

### P2 SQL evidence

The parent SQL evidence for the P2 journey contains complete rows from all
thirty-five tables in ten separately bounded phase files. It includes stored
catalog metadata and fresh schema-owner/table-name checks. Current live schema
validation is separately performed by the public SDK/store preflight. The
snapshots do not claim a fresh full columns/constraints/grants catalog at every
phase. Runtime permission denials and the original provider, callback and recovery
source joins retain their own proofs. No whole record is truncated to fit an
evidence bound.

### P3-I18A scope

The P3-I18A results establish explicit versioned durable policy consumption
through existing public P1 work authority. P1 retains opaque canonical bytes and
remains the execution/result owner. v1 defaults and v1-only
delivery/projection/action adapters remain unchanged. The results do not complete
P3-I18's native background tool, ongoing conversation or UI.

These remain planned: P2-I22 fresh-agent/release work, coherent integrated P1
native revision-0 execution, the complete charter registrations, remaining
cross-channel/media evidence and the final credential-free demo video. The
fifty-five catalog definitions/twenty-four registered runners are unchanged by
these selected assertions.

### Failures and corrections

The main P2 run passed all twenty assertions, including populated restore. The
separate public-P1 six and the fresh compatibility 187 also passed.

- Earlier failed runs caught fixture and backup-ownership defects. Original
  reports retain their failures and incomplete-cleanup flags, with later exact
  cleanup recorded separately.
- The unrecoverable second wheel-check failure and the original compatibility
  deadline failure remain unattributed. Subsequent controlled reproductions have
  their own scope.
- Strict validation also identified a public exception-code annotation defect.
  The corrected union type preserves constructor/runtime behavior. Final P3 source
  and installed runs bind the corrected bytes. The existing isolated package
  consumer now verifies the non-default code statically and at runtime.
- Prior compatibility and HTTP/image results retain original source/archive
  identities, supported by an independent exact runtime/fixture equivalence
  review. They are not relabelled fresh runs.
- Earlier README/package observations remain preserved separately.

### Handoff

Selected implementation and validation are complete. The private retained
checkpoint records exact commands, counts, source/archive identities, failed
predecessors, scoped recovery, actual ownership, source preservation and
independent review roles. AI assistance is disclosed there; source authors do not
independently qualify their own implementations. Native background conversation,
the compact integrated UI, full charter/release evidence and the final local
provider demo/video remain planned. The broader local POC and final demo-video
goal remains active.
