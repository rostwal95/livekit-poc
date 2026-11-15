# Linked confirmation and resumable result projections

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Record the plan, observed verification and handoff for P2-I11 linked confirmation and P3-I09 resumable result projections |
| Audience | Engineers changing P2 confirmation routing, the P1 result feed or P3 projections; coding agents |
| Scope | Selected P2-I11 and P3-I09 local phase gates; excludes outbox, refresh policy, native media and integrated release |
| Owns | Change plan, observed verification and handoff for P2-I11 and P3-I09 |
| Related | [Work item 0031](0031-revision-routing-and-delegation-acceptance.md) · [Work item 0033](0033-outbound-replies-and-completion-processing.md) · [P2 task plan](../implementation/p2-channel-continuity.md) · [P3 task plan](../implementation/p3-delegation-reliability.md) · [Validation plan](../validation-plan.md) |

## Behavior and scope

This work item implements two tasks and continues the completed
[revision-routing/acceptance phase](0031-revision-routing-and-delegation-acceptance.md):

| Project | Task | Behavior |
| --- | --- | --- |
| P2 | P2-I11 | Adds the linked exact-confirmation flow |
| P3 | P3-I09 | Adds a bounded, resumable result/applicability projection |

P1 remains the only integrated case and execution authority. Preserve:

- original booking v4 and work v1/v2/v3 bytes and identities;
- current local state;
- all closed checkpoints.

Use the maintained Downloads/repositories/livekit-agent-ecosystem checkout. The
desktop workspace is an older independent checkout.

### Terms used in this record

| Term | Meaning |
| --- | --- |
| Implementation task IDs | Such as P2-I11; identify tasks in the [P2 task plan](../implementation/p2-channel-continuity.md) and [P3 task plan](../implementation/p3-delegation-reliability.md) |
| Acceptance IDs | Such as P2-06; identify rows in the project charters |
| Selected local phase gates | The gates chosen for this work item; passing them does not complete a full acceptance (charter) row |
| Gate names | Such as G-READY and G-DURABLE; refer to the engineering gates in the [validation plan](../validation-plan.md) |
| Acknowledgement (ACK) | A receiver's confirmation that it accepted a message or command; a lost ACK leaves the outcome unknown |
| Compare-and-set (CAS) | A write that succeeds only when the stored revision or checkpoint still matches the expected value |
| Data definition language (DDL) | Schema-changing SQL; explicit owner upgrades run it, serving code does not |
| M1 | The original confirmed-investigation intake data, which every phase preserves |

### Criteria

| Criterion | Given | When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- | --- |
| P2-I11, P2-06 contribution | Immutable trusted prompt bound to exact quote, original revision, account/case/conversation/response | Old, unlinked, altered or current signed user confirmation arrives | Bare yes cannot select the latest quote; stale or wrong scope cannot create an intent; no model-generated consent | A current explicitly linked confirmation commits one exact existing-authority intent | Actual signed SMS v1, P1 case transaction, stable command identity and independent intent/effect truth |
| Current confirmation preflight | Retained accepted input and original sender association epoch | Revoked or reassigned sender's old input is routed as a new confirmation | New narrow eligibility read rejects known revoked/reassigned input; ordinary retained history remains readable | Current eligible input can proceed | Negative/progress tests; this preflight is not an atomic cross-authority revocation fence |
| Confirmation ambiguity/replay | Original operation key and known P1 command receipt | Confirmation ACK is lost, then the caller explicitly replays original input | Unknown stays unknown until original receipt is found; no new key, auto retry or rebase | Original intent/effect receipt returns without another logical action | Actual postcommit response loss/fresh-process lookup/replay |
| P1 durable result feed | Explicit owner upgrade of existing validated work v3 | Existing results are adopted or a new opaque result commits | Original data unchanged; each result and event reference commit together; no lower-sequence late commit is skipped | Stable scope-local cursor yields historical and subsequent results after restart | Atomic v4 upgrade/backfill, concurrent commits, kill/replay and bounded page assertions |
| P3-I09 projection | Strict source/scope-bound feed and declared public result/grant APIs | Explicit projector step validates a bounded batch | Projection owns no execution, delivery, action or source acknowledgement; missing/unavailable source cannot be invented | Validated or definitely rejected event metadata and checkpoint commit together | Actual PostgreSQL profile, ordered feed, typed observations and independent reconciliation |
| Projection recovery | Cursor plus immutable event identities and observations | Caller/process exits before or after commit, or same batch races | No partial cursor advance; replay returns original as-of observation; changed immutable event conflicts | Fresh process resumes or reads original committed batch | Owned pre/postcommit termination and concurrent replay tests |
| Honest applicability | Stored observation and later case/cancel/time changes | Read projection after authority changes without another result event | Stored status is explicitly as-of, never current action permission or a timeless current badge | Existing public authority reads remain available; later refresh policy stays explicit | Case-change/no-new-event schedule and zero action/delivery effects |
| Limits and diagnostics | Adversarial data, slow I/O, capacity and failing telemetry | Timeout, cancellation, invalid cursor, cap or observer failure | Finite rows/pages/tasks/bytes; actual I/O stays owned; logs/errors exclude bodies/credentials | Valid admitted work, replay and reads still progress | Unit/socket/process/storage negatives plus useful-progress and cleanup gates |

## Interfaces and ownership

### P2 prompt registry

P2 adds a separate immutable prompt-registry v1 profile. It has:

- explicit owner installation;
- bounded retained records;
- distinct controller publication credentials;
- credential-scoped reads.

The registry owns response association, not current case facts. A prompt holds
opaque canonical supplier-bound quote-v2 JSON, its SHA256 and a bounded decimal
revision. This preserves P1 int64 fields without JavaScript number coercion.
Registration does not prove generation, sending, playback or human comprehension.

### Linked confirmation input

The existing closed fake-SMS v1 carrier remains unchanged. A linked confirmation
takes one of two forms:

- YES followed by an exact response ID;
- a strict versioned structured command.

A bare YES requires explicit trusted native reply/revision metadata when
available. Otherwise the router asks for clarification. New confirmation routing
requires the separate current-confirmation input preflight; it does not fall back
to retained history. A supplied model statement, generated response or playback
grants no consent.

### Integrated confirmation through P1

Integrated confirmation uses public P1 exact controller APIs through an opt-in
privilege on the bounded local application bridge. Existing revision bindings do
not gain that privilege.

P1 checks the original full quote, current case and revision, expiry and
cancellation, and intent atomically. The original message operation key is the
confirmation command ID. P1's existing command receipt permits explicit
original-command replay, unlike investigation revise's receipt-free CAS. There
is no new P1 booking schema or source of supplier execution authority.

The known cross-authority association-revocation commitment gap remains a
required later full-product gate. It is not an invented native-media prerequisite
for P2-06.

### P1 result feed

P1 adds an explicit optional work-profile v3-to-v4 owner upgrade and a generic
result-only feed. Three tables own:

- an immutable source UUID;
- finite scope-local heads;
- immutable result-event references.

A live event/sequence is allocated after the existing admission guard, inside the
same result transaction. Result replay emits no second event. Atomic adoption
gives existing results a deterministic per-scope order labelled adopted_history,
never a fictional original commit order.

No accepted/issue/cancel/delivery/action feed or per-consumer acknowledgement is
added. A cursor binds the source UUID, the verified WorkScope and the committed
sequence. Pages are finite and reveal only that scope's high water. Restored or
branched source incarnation rotation remains separate unqualified work.

### P3 projection

P3 adds an explicitly owner-installed projection v1 with three tables:

- immutable source/scope/config metadata;
- the checkpoint;
- one observation per source event.

Public clients expose bounded checkpoint/result reads. Writes are private to an
explicit projector step. Strict result/grant/evidence validation uses declared P1
public APIs. No result blob, queue, retry state, delivery/action receipt or copied
execution ownership is introduced.

Checkpoint and rows share one CAS transaction. Same-batch replay returns the
original stored observation. Partial overlap may return a typed checkpoint
conflict that requires another explicit step. An unknown commit reconciles the
exact checkpoint/event identities once and never resubmits the write.

### Applicability and dependencies

Applicability metadata describes non-atomic execution/case/time observations.
Definitely invalid P3 output can be quarantined with a safe reason and advance the
checkpoint. Unavailable source reads do not advance it. Case unavailability is an
explicit as-of observation. Case-only/cancellation refresh and resumable delivery
processing remain later P3-I10/P3-I11 policy.

The new P3 direct psycopg dependency pins the already locked version. No resolved
package/runtime version upgrade is allowed.

## Failure cases and validation

| Gate | Required assertions | Setup and bounds | Completion rule |
| --- | --- | --- | --- |
| G-READY/CONTRACT | Frozen quote/link, result-feed cursor and projection CAS contracts | Existing pinned local stack; direct dependency metadata only | No product edits before authority/API agreement |
| G-FAST/OBS | New and existing units, runtime schema/data validation, diagnostics, lint/types/format and harness boundaries | Offline; no provider configuration/keys/calls | Nonzero full maintained suites; no required skips or weakened guards |
| G-DURABLE P1 | Atomic/repeated/interrupted v4 adoption; immutable bytes/IDs; event/result atomicity; scope-local cursor/no gaps/caps/roles/drift | Restricted actual PostgreSQL, controlled transactions/processes | Focused new feed cases and full affected P1 regression pass |
| G-CONFIRMATION P2 | Old/unlinked/current links, changed prompt payload, known revocation preflight, postcommit ACK loss/original replay and useful exact action | Signed synthetic carrier, prompt store, actual P1 case and existing leased fake worker | Zero stale/unauthorized intent and one valid separately confirmed fake effect; owned cleanup |
| G-PROJECTION P3 | Pre/postcommit exit, fresh resume, duplicate batch, rejected metadata/valid progress, cursor/source/scope/cap and as-of honesty | Actual P1 v4 feed and P3 v1 schema with owner/runtime separation | Exact independent source/projection counts, unchanged identities and zero delivery/action calls |
| G-PACKAGE | New public feed/confirmation/projection imports/types and positive behavior | Fresh isolated declared wheel/npm installs outside checkout | No sibling/private storage import, implicit DDL or startup-on-import |
| Regression | Existing P2 routing/recovery, registered P3 lab rows and prior durable lanes, rebuilt local Docker smoke | Preserve original M1 identity/volumes and source-bound provider evidence | All affected lanes pass; no new model/media/carrier claim |
| G-MEDIA/RELEASE | Deferred full-product work | No default UI/Compose/carrier/model rollout in this slice | Existing three registered P3 rows remain; no new full row without all required assertions |

Rules for every gate run:

- Keep work/cleanup deadlines fixed before running.
- Retain actual I/O/thread/socket ownership after waiter cancellation, including
  late close observers.
- Runtime performs no DDL, fingerprint refresh, tombstone deletion or implicit
  retry loop.
- Retain first failures and label controlled diagnostic reproductions accurately.
- Correctness durations are not capacity or production latency measurements.

## Results and handoff

P2-I11 and P3-I09 passed their selected local phase gates. P1 remains the only
integrated case/execution authority. No full charter row was added.

The evidence checkpoint is `.local/validation/p2-confirmation-p3-projection/d4bd9fbd898447f6aaf3d7c7bb93f307`.
Its final manifest binds reports, artifacts, source hashes, original failures and
independent automated reviews. The preceding closed checkpoint is preserved.

| Area | Implemented behavior | Observed proof |
| --- | --- | --- |
| P1 prerequisite | Explicit work v3-to-v4 adoption, immutable source UUID, scope-local contiguous result-only cursor and atomic live result/event writes | 11 focused PostgreSQL cases, including actual owner termination/rollback; full 327-case PostgreSQL regression passed |
| P2 exact consent | Separate owner-installed immutable prompt registry, publisher credentials, linked YES/strict structured command, current eligibility preflight and opt-in confirmation HTTP client/bridge | 18 actual integration assertions; two competing revision/confirmation waiters; zero stale/unlinked intents, lost ACK/original receipt replay, one separately confirmed leased fake effect |
| P3 metadata | Owner-installed three-table v1, strict source/result/grant validation, validated/rejected metadata and atomic checkpoint CAS | 12 actual assertions and two owned SIGKILL schedules; fresh resume, duplicate-batch original observations, capacity/cursor/source/scope rejection and independent reconciliation |
| Honest applicability | Stored execution/case/time observations are explicitly non-atomic and as-of | Case changes without a new result event preserve the original historical observation; no delivery/action intent is produced |
| Compatibility | Existing inputs, data and optional work v1/v2/v3 remain supported | P2 routing 22 and prior 23/four-kill lanes; P3 coordinator 10/execution 12; registered P3-01/03/11 repeat 13/8/12, all with cleanup |
| Maintained fast gates | Discovery, boundaries, typing, formatting and documentation include new modules/examples/tests | 1,439 Python tests: P1 49, P2 14, P3 161, root 1,215; 673 TypeScript tests: console 326, P2 269, specialist 78; broad 128/strict 86 type sources; 309 formatted files |
| Documentation | Standard guides, task status, design and handoff updated | 105 documents pass; 13 root/project Mermaid diagrams parse, with malformed-input negative; syntax qualification only |
| Local runtime | Ordinary stack rebuilt with observability and original state | Eight smoke checks, 10 actual audio frames, original M1 identity preserved; installed image imports all three exact new P1 feed modules |

### Commands

Commands were executed from the maintained checkout with its Python 3.14
interpreter and pinned Node/pnpm environment:

| Task | Command | Notes |
| --- | --- | --- |
| Shared fast gates | `make check`, `make frontend-check`, `make format-check` and `make typecheck` | None |
| P1 PostgreSQL and P2 lanes | Explicit `postgres_check.py`, `p2_confirmation_check.py` and `p2_routing_check.py` | Plus the existing P2 recovery gate |
| P3 lanes | `p3_projection_check.py` | Plus the P3 coordinator/execution gates |
| Registered lab rows | Registered `harness run P3-01`, `P3-03` and `P3-11` | None |

Required lanes had no skips, errors or failures.

### Package and dependency evidence

- **P1 artifacts.** Fresh built P1 wheel/sdist/rebuilt payloads match 77 runtime
  files. Public feed imports/types run in a new isolated interpreter.
- **P3 artifacts.** P3 wheel/sdist/rebuilt payloads match 20 runtime files with
  the declared psycopg dependency. Its isolated installed consumer runs all 12
  actual recovery assertions through the exact copied public projection example
  and the strengthened original-identity fixture.
- **P3 import boundaries.** The example/type consumer uses declared public APIs.
  Test tooling retains its configured projection client through a private test
  handle. Only the explicit owner helper imports P1 migration/worker internals. No
  private P1 storage import enters the P3 product.
- **P2 npm artifact.** It is installed offline outside the checkout and checked
  with strict NodeNext typing. Its actual registry, immutable binding/cap, bigint
  quote bytes, unknown HTTP ACK and fresh-process original receipt checks pass.
  That installed authority/input peer is explicitly synthetic. Actual P1
  confirmation and supplier execution are proved separately by the 18-case
  integration.
- **Cleanup.** Temporary schemas, processes, sockets and installed environments
  are cleaned up.

The P3 direct psycopg dependency reuses 3.3.8. Offline lock comparison proves all
97 resolved versions/sources unchanged; only P3 direct dependency metadata
changes. A final P1 README status cleanup rebuilds package metadata while
preserving all 77 runtime payloads byte-for-byte as used by the installed
integration. Both exact artifact identities remain in evidence. No provider
keys/private CA were read and no paid inference was used.

### Reviews and retained intermediate results

Independent reviews resolved:

- UUIDv5 quote identity;
- strict HTTP Connection-close framing;
- caller/task lifetime ownership;
- foreign request metadata quarantine;
- source/scope validation on stored projection reads;
- strict primitive codecs.

The actual projection owner proof compares all four pre-upgrade
work/attempt/issue identities and request/result digests to the feed, accepted
data and projections.

Retained intermediate results are labelled accurately:

- typing/test-fixture fixes;
- initial installed-tool setup failures;
- the system-Python lock comparison, corrected against the last tested image;
- frontend formatting checked before the final format pass.

Package manifest parity compares exact JSON meaning where the package manager
reformats bytes. The initial over-strict byte check is recorded separately. A
prepared older P3 consumer was never executed, and its temporary environment was
removed. The first actual P2/P3 integration and installed gate attempts passed;
broader claims do not follow from those selected successes.

### Remaining boundaries and next phase

- P2's current association check is a late preflight. An atomic cross-authority
  association-revocation commitment fence remains required before full relevant
  security/confirmation qualification. Ordinary retained history stays readable.
- P3 projection is result-only historical metadata. Case-only/cancellation
  refresh, durable processing acknowledgement, possible-send recovery and delivery
  policy require explicit P3-I10/P3-I11 design. Restored/branched source
  incarnation rotation remains unqualified.
- Next implement P2-I12's communication identities/outbox and P3-I10's resumable
  completion processing, with frozen contracts, failure schedules, retained
  receipts, useful progress and tests before extending product registration.
- The catalog remains 24 registered of 55: all 17 P2 and 14 P3 rows remain
  planned; only the existing three P3 lab rows are qualified. Complete P2/P3
  native media, broader recovery, production capacity and integrated release
  remain pending.

Keep current provider qualification within its historical source-bound scope.
All code, secrets and Docker state remain local. Publication and remote CI are
outside this proof of concept's (POC's) completion requirements.
