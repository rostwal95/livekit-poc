# Linked confirmation and resumable result projections

Status: Completed
Last reviewed: 11 November 2026

## Behavior and scope

Implement P2-I11's linked exact-confirmation flow and P3-I09's bounded resumable
result/applicability projection. Continue the completed
[revision-routing/acceptance phase](0031-revision-routing-and-delegation-acceptance.md).
P1 remains the only integrated case and execution authority. Preserve original
booking v4, work v1/v2/v3 bytes/identities, current local state and all closed
checkpoints. Use the maintained Downloads/repositories/livekit-agent-ecosystem
checkout; the desktop workspace is an older independent checkout.

| Criterion | Given | When | Safety | Useful progress | Evidence |
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

P2 adds a separate immutable prompt-registry v1 profile with explicit owner
installation, bounded retained records, distinct controller publication credentials
and credential-scoped reads. It owns response association, not current case facts.
A prompt holds opaque canonical supplier-bound quote-v2 JSON, SHA256 and bounded
decimal revision, preserving P1 int64 fields without JavaScript number coercion.
Registration does not prove generation, sending, playback or human comprehension.

The existing closed fake-SMS v1 carrier remains unchanged. Its linked form is
YES followed by an exact response ID, or a strict versioned structured command.
Bare YES requires explicit trusted native reply/revision metadata when available;
otherwise it asks clarification. New confirmation routing requires the separate
current-confirmation input preflight rather than falling back to retained history.
A supplied model statement, generated response or playback grants no consent.

Integrated confirmation uses public P1 exact controller APIs through an opt-in
privilege on the bounded local application bridge. Existing revision bindings do
not gain that privilege. P1 checks the original full quote, current case/revision,
expiry/cancellation and intent atomically; the original message operation key is
the confirmation command ID. P1's existing command receipt permits explicit
original-command replay, unlike investigation revise's receipt-free CAS. There is
no new P1 booking schema or source of supplier execution authority. The known
cross-authority association-revocation commitment gap remains a required later
full-product gate; it is not an invented native-media prerequisite for P2-06.

P1 adds an explicit optional work-profile v3-to-v4 owner upgrade and a generic
result-only feed. Three tables own an immutable source UUID, finite scope-local
heads and immutable result-event references. A live event/sequence is allocated
after the existing admission guard inside the same result transaction; result
replay emits no second event. Atomic adoption gives existing results deterministic
per-scope order labelled adopted_history, never fictional original commit order.
No accepted/issue/cancel/delivery/action feed or per-consumer acknowledgement is
added. A cursor binds source UUID, verified WorkScope and committed sequence;
pages are finite and reveal only that scope's high water. Restored/branched source
incarnation rotation remains separate unqualified work.

P3 adds an explicitly owner-installed projection v1 with three tables: immutable
source/scope/config metadata, checkpoint and one observation per source event.
Public clients expose bounded checkpoint/result reads; writes are private to an
explicit projector step. Strict result/grant/evidence validation uses declared P1
public APIs. No result blob, queue, retry state, delivery/action receipt or copied
execution ownership is introduced. Checkpoint and rows share one CAS transaction.
Same-batch replay returns the original stored observation; partial overlap may
return a typed checkpoint conflict requiring another explicit step. Unknown commit
reconciles exact checkpoint/event identities once, never resubmits the write.

Applicability metadata describes non-atomic execution/case/time observations.
Definite invalid P3 output can be quarantined with a safe reason and advance the
checkpoint; unavailable source reads do not advance. Case unavailability is an
explicit as-of observation. Case-only/cancellation refresh and resumable delivery
processing remain later I10/I11 policy. The new P3 direct psycopg dependency pins
the already locked version; no resolved package/runtime version upgrade is allowed.

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

Keep work/cleanup deadlines fixed before running. Retain actual I/O/thread/socket
ownership after waiter cancellation, including late close observers. Runtime
performs no DDL, fingerprint refresh, tombstone deletion or implicit retry loop.
Retain first failures and label controlled diagnostic reproductions accurately.
Correctness durations are not capacity or production latency measurements.

## Results and handoff

P2-I11 and P3-I09 passed their selected local phase gates. P1 remains the only
integrated case/execution authority; no full charter row was added. The evidence
checkpoint is `.local/validation/p2-confirmation-p3-projection/d4bd9fbd898447f6aaf3d7c7bb93f307`.
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
| Documentation | Standard guides, task status, design and handoff updated | 105 documents pass;13 root/project Mermaid diagrams parse, with malformed-input negative; syntax qualification only |
| Local runtime | Ordinary stack rebuilt with observability and original state | Eight smoke checks, 10 actual audio frames, original M1 identity preserved; installed image imports all three exact new P1 feed modules |

Commands were executed from the maintained checkout with its Python3.14 interpreter
and pinned Node/pnpm environment: `make check`, `make frontend-check`,
`make format-check`, `make typecheck`, explicit `postgres_check.py`,
`p2_confirmation_check.py`, `p2_routing_check.py`, the existing P2 recovery gate,
`p3_projection_check.py`, P3 coordinator/execution gates and registered
`harness run P3-01`, `P3-03`, `P3-11`. Required lanes had no skips, errors or failures.

Fresh built P1 wheel/sdist/rebuilt payloads match 77 runtime files. Public feed
imports/types run in a new isolated interpreter. P3 wheel/sdist/rebuilt payloads
match 20 runtime files with the declared psycopg dependency. Its isolated installed
consumer runs all 12 actual recovery assertions through the exact copied public
projection example and strengthened original-identity fixture. The example/type
consumer uses declared public APIs; test tooling retains its configured projection
client through a private test handle, and the explicit owner helper alone imports
P1 migration/worker internals. No private P1 storage import enters the P3 product.

The P2 npm artifact is installed offline outside the checkout and checked with
strict NodeNext typing. Its actual registry, immutable binding/cap, bigint quote
bytes, unknown HTTP ACK and fresh-process original receipt checks pass. That
installed authority/input peer is explicitly synthetic; actual P1 confirmation and
supplier execution are proved separately by the 18-case integration. Temporary
schemas, processes, sockets and installed environments are cleaned up.

The P3 direct psycopg dependency reuses 3.3.8. Offline lock comparison proves all 97
resolved versions/sources unchanged; only P3 direct dependency metadata changes.
A final P1 README status cleanup rebuilds package metadata while preserving all 77
runtime bytes used by the installed integration; both exact artifact identities
remain in evidence. No provider keys/private CA were read or paid inference used.

Independent reviews resolved UUIDv5 quote identity, strict HTTP Connection-close
framing, caller/task lifetime ownership, foreign request metadata quarantine,
source/scope validation on stored projection reads and strict primitive codecs.
The actual projection owner proof compares all four pre-upgrade work/attempt/
issue identities and request/result digests to feed, accepted data and projections.

Retained intermediate results are labelled accurately: typing/test-fixture fixes,
initial installed-tool setup failures, the system-Python lock comparison corrected
against the last tested image, and frontend formatting checked before the final
format pass. Package manifest parity compares exact JSON meaning where the package
manager reformats bytes; the initial over-strict byte check is recorded separately.
A prepared older P3 consumer was never executed and its temporary environment was
removed. First actual P2/P3 integration and installed gate attempts passed; broader
claims do not follow from those selected successes.

### Remaining boundaries and next phase

- P2's current association check is a late preflight. An atomic cross-authority
  association-revocation commitment fence remains required before full relevant
  security/confirmation qualification. Ordinary retained history stays readable.
- P3 projection is result-only historical metadata. Case-only/cancellation refresh,
  durable processing acknowledgement, possible-send recovery and delivery policy
  require explicit I10/I11 design. Restored/branched source incarnation rotation
  remains unqualified.
- Next implement P2-I12's communication identities/outbox and P3-I10's resumable
  completion processing, with frozen contracts, failure schedules, retained
  receipts, useful progress and tests before extending product registration.
- The catalog remains 24 registered of 55: all 17 P2 and 14 P3 rows remain planned;
  only the existing three P3 lab rows are qualified. Complete P2/P3 native media,
  broader recovery, production capacity and integrated release remain pending.

Keep current provider qualification within its historical source-bound scope.
All code, secrets and Docker state remain local; publication and remote CI are
outside this POC's completion requirements.
