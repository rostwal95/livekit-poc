# Gateway recovery and issued specialist execution

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Record the P2 gateway restart path and P1-issued P3 specialist execution and the gates they passed |
| Audience | Engineers changing the P2 gateway, the P1 issued-work profile or the P3 runner; reviewers; coding agents |
| Scope | Task P2-I08 and the P3-I07A prerequisite; excludes P3-I07B delivery and action, media and complete charter rows |
| Owns | P2-I08 and P3-I07A change plan, observed verification and handoff |
| Related | [Dispatch and coordinator](0028-p2-dispatch-and-p3-coordinator.md) · [Agent recovery and completion](0030-p2-agent-recovery-and-p3-completion.md) · [P2 task plan](../implementation/p2-channel-continuity.md) · [P3 task plan](../implementation/p3-delegation-reliability.md) |

## Behavior and scope

This work item implements P2-I08's real bounded gateway/restart path and the
P3-I07A execution prerequisite. The previous checkpoint has durable P2 one-step
dispatch and P3 immutable acceptance, but acceptance issues no attempt.

P3-I07 is split because its execution, delivery and atomic action prerequisites
are distinct contracts. This slice must prove P1-issued invocation and a durable
useful read-only result. P3-I07B retains delivery and the exact authorized fake
action. Neither full P3-I07 nor a complete P2/P3 charter row passes from this
prerequisite.

Use the maintained repository checkout. The desktop workspace contains an older
independent checkout; it is not the active implementation. Preserve all existing
user state and historical evidence.

| Criterion | Given | When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- | --- |
| P2 gateway recovery, P2-03 contribution | Signed associated SMS input and explicit v2 inbox | Gateway acknowledges accepted input, then is forcibly terminated before dispatch | Receipt, original canonical input and operation identity remain durable; no memory queue owns acceptance | A fresh process selects and dispatches the original input; repeated restart/replay preserves one logical external acceptance | Actual PostgreSQL, owned independent gateway/operation processes and barriers |
| P2 normal ingress | Verified carrier and current associated account | Raw loopback request is received | Unverified/body-selected scope cannot admit or disclose work; owner credentials are absent | Ordinary signed input receives its original acceptance and bounded background progression | Real sockets plus malformed, overload and cleanup fixtures |
| P1 issued progression | Explicit owner-upgraded read-only accepted-work profile | Credential-bound worker claims eligible accepted work | Database-time owner/epoch/lease validation gates writes; cancellation/deadline/caps prevent new ineligible attempts; runtime performs no data definition language (DDL) | An actual current issued attempt can persist one scoped result without holding a transaction across HTTP | Real migration, concurrent claims, stale-owner, replay and result-acknowledgement tests |
| P3 issued invocation, P3-01 contribution | Original immutable accepted envelope and current P1-issued attempt | One bounded run invokes scripted TypeScript policy service | Proposed input attempt is not execution permission; strict correlated result/evidence validation precedes durable acceptance; no action authority | Known useful candidate survives client/process lifetime and remains inspectable through public P1 interfaces | Actual Python-to-TypeScript sockets and fresh-process PostgreSQL read |
| Lifetime and observability | Slow, aborted or failing adapters and throwing telemetry | Waiter expires, cancels or closes | Actual unsettled resources retain their slots; fixed safe errors/logs cannot alter committed truth | Independent/subsequent eligible work progresses and owned cleanup completes | Offline negative/progress tests plus actual socket/process fixtures |

## Interfaces and ownership

### P2 gateway

P2 owns ingress and channel dispatch. A reusable loopback gateway composes only
its public intake/dispatch and explicit scoped adapters. Accepted work is selected
from PostgreSQL rather than a process queue. Claims retain their existing external
cooperation and uncertainty semantics. Native room/audio, revision routing and the
outbox remain later tasks.

### P1 issued-work profile

P1 alone owns accepted work, issued attempts and persisted opaque results. Add an
explicit versioned profile upgrade that preserves v1 identities, bytes, grants,
cancellation and admission protection. Keep booking v4 (the PostgreSQL booking
schema, version 4) and SQLite unchanged. Runtime does not install, repair or
refresh catalog definitions. Public v1 APIs remain compatible and separate
acceptance from execution observations.

### P3 runner

P3 owns strict envelope/result validation and bounded foreground orchestration.
It imports declared P1 APIs, never P1 storage. Replace proposed transport attempt
correlation only from issued authority, without rewriting the accepted envelope or
semantic fingerprint. P1 writes validate scope, work identity, owner and epoch.
Cancellation, expiry, computation, durable result, current applicability,
delivery and exact action authorization remain distinct. No P3 database ledger,
second recovering scheduler, paid inference, carrier or browser media is added.

### Shared constraints

Freeze public APIs and resource, time, byte and retention bounds before
implementation. Preserve original immutable replay after upgrade and after
ambiguous acknowledgement. Use finite process-local counters and fixed safe codes.
Exclude raw request/result bodies, credentials, SQL parameters and dependency
exceptions. Local shared SQL principals and trusted configuration are not
independent database-principal isolation.

## Failure cases and validation

Gate names starting with G- refer to the engineering gates in the
[validation plan](../validation-plan.md). G-HTTP/P3 is specific to this work item.

| Gate | Applicable and why | Required assertion | Bound/prerequisite | Expected artifact |
| --- | --- | --- | --- | --- |
| G-READY/CONTRACT | New public gateway and issued-work contracts | Explicit API/ownership/migration review, current positive and negative fixtures | Frozen existing toolchain; no dependency upgrade | Work item, source tests and independent review |
| G-FAST | New Python/TypeScript and shared harness integration | Normal/negative/progress tests, lint, broad/strict typing, format, contract/import checks | Offline, no provider credentials | Full fast/frontend/format logs, zero skips |
| G-DURABLE P2 | Actual gateway crash after accepted acknowledgement (ACK) | Independent persisted acceptance, kill, fresh restart, stable dispatch/operation identity and cleanup | Owned marked schema, process deadlines and byte caps | Fresh P2 gateway report |
| G-DURABLE P1 | Versioned issued profile and result writes | Upgrade preservation/repeat/interruption, claims/fencing/deadline/cancel/caps, commit uncertainty, runtime privilege/drift rejection and current positive result | Restricted owner/runtime roles, real PostgreSQL | Focused profile and complete P1 regression reports |
| G-HTTP/P3 | Invocation uses actual issued attempt | Strict result correlation, known result persistence, stale epoch rejection, fresh read and actual cleanup | Local scripted TypeScript service, independent Python processes | Fresh execution integration report |
| G-PACKAGE | Public API consumers and versioned metadata | Built archives and outside-checkout public imports/types/behavior as affected | Fresh isolated installation with frozen dependencies | Safe artifact/consumer reports |
| Regression | Preserve established local proof of concept (POC) | Existing P1/P2/P3 tests and actual rebuilt default Docker smoke; original M1 (confirmed-investigation intake) identity retained | No volume reset; no real provider calls | Docker smoke, source comparison and final inventory |
| G-MEDIA/RELEASE | Deferred | No new model/browser/media or completed full charter claim | Separate later phase prerequisites | Remain pending |

New sources and subprocess fixtures enter maintained discovery, type and import
checks. Explicit service lanes stay separate from offline unittest discovery.
Missing setup, skips, zero cases, timeout or incomplete owned cleanup cannot pass.
Retain initial failures and label actual versus synthetic case/agent/evidence
adapters. Correctness-run durations are not throughput or latency-percentile
measurements.

## Results and handoff

### Implemented behavior

#### P2 gateway

P2-I08 exposes the server-only `./gateway` package export. ChannelGateway:

- validates its existing v2 store before binding literal loopback;
- authenticates raw signed fake-SMS input;
- acknowledges committed receipts;
- serves credential-scoped processing reads.

A single owned driver rotates configured accounts and selects bounded eligible
work from PostgreSQL. Accepted responses never own a memory queue. Normal ingress
does not pause already accepted processing. The explicit trusted test-only ACK
hook supplies a deterministic post-ACK, pre-dispatch schedule. No runtime DDL,
default deployment, outbound carrier or native media was added.

Gateway defaults bound:

| Limit | Value |
| --- | --- |
| Sockets | 16 |
| Admitted HTTP requests | Four |
| Headers | 16 headers and 8 KiB of headers |
| Headers and responses | One second each |
| Bodies | Two seconds |
| Startup | Five seconds |

Polling, close and observer bounds:

| Limit | Value |
| --- | --- |
| Polling cadence | 100 ms |
| Polling batch | Four items |
| Per-turn deadline | Two seconds, before every further account scan |
| Close observer budget | Two seconds |
| Async observer notifications | Capped at eight |

Current SQL/adapter I/O retains its own bounded lifetime; a caller deadline does
not terminate that I/O. Close reports an incomplete close truthfully and retains
ownership until actual settlement.

#### P1 issued execution

P1's new `execution_api` exposes ExecutionClient/ExecutionPort and immutable
issued attempt/result observations. `work_admin.upgrade_work_schema_v2`
explicitly and atomically upgrades a previously validated read-only v1 profile. It
retains the original accepted bytes, identities, cancellation and caps. The
existing v1 acceptance API still works on both versions. Booking v4 and SQLite are
unchanged. Runtime has no schema administration or canonical update/delete
permission.

P1 persists issue commands, owner/epoch/lease and one opaque bounded result per
issued attempt. Every protected write uses the existing admission lock and the
server clock sampled after locks.

| Limit | Value |
| --- | --- |
| Logical active leases | Two, by default |
| Attempts per work | At most three, by default |
| Lease | Ten seconds, by default |
| Result bytes | Capped at 8 KiB |

Issuance and result rules:

- Issue replay returns its original grant without another start.
- Cancellation, expiry, exhaustion and an already eligible result prevent new
  issuance.
- Exact issued identity is mandatory for result acceptance.
- Cancelled, expired, superseded or lease-expired known results remain immutable
  history and cannot replace an eligible newer result.
- `eligible_at_commit` describes P1 lease/time/cancellation eligibility, not
  semantic truth or current-case action permission.
- Later cancellation does not erase a known result.

Read-only snapshots keep result truth separate from current cancellation and
execution observations.

#### P3 runner and client

P3-I07A exposes `DelegationRunner.run_once`/`inspect` through declared public
ports. Only newly issued commands may invoke. A fresh authority observation
rejects an already known stale, expired or cancelled grant before HTTP. It cannot
fence a future physical request race.

Transport correlation is `attempt_` followed by the issued UUID's 32 hexadecimal
digits. The original accepted wire attempt bytes and semantic fingerprint remain
unchanged. Strict identity, canonical result and registered policy facts are
validated before P1 persists the result. Replayed or ambiguous issue
acknowledgements only inspect. An unknown completion acknowledgement looks up the
original result. There is no automatic retry loop or P3 execution ledger.

`SpecialistClient.invoke_observed` can return strict historical business-expiry
observations within the unchanged transport budget. The original invoke remains
candidate-only. Even late results must match declared policy facts. P3 retains
actual port work after waiter cancellation or timeout and may persist a known
result after the caller leaves. Deep snapshots also cover nested grants and
observations across awaited case reads.

Current applicability is an explicitly non-atomic case read. Neither the HTTP
service nor a candidate authorizes a booking action. The HTTP service
independently authenticates capability/evidence access and does not itself verify
P1-issued grants; the runner path enforces issuance.

### Observed gates

| Gate | Observed result | Qualification boundary |
| --- | --- | --- |
| Full offline Python | make check passed 1,263 tests: root 1,119; P1 31; P2 14; P3 99; zero skips/violations | Ruff passed; broad mypy 109 and strict mypy 54 maintained source files |
| Python formatting | 261 files passed | No check suppression or blanket type ignore added |
| Frontend/examples | 587 tests: console 326, P2 183, specialist 78; formatting/type/build all passed | Existing console bundle-size advisory remains; no new UI/media qualification |
| Full P1 PostgreSQL | 290 tests, zero errors/failures/skips; 233.478 seconds | Includes 14 new issued-profile cases and all existing v1/booking/migration lanes |
| P2 actual gateway | Three cases, one verified post-ACK/pre-dispatch forced exit; 1.572 seconds, complete cleanup | Actual HTTP and independent gateway restarts; case/agent ports are synthetic and operation acceptance independently persisted |
| P2 complete selected lane | All 22 cases passed, including the prior 19; three total owned forced exits; 7.045 seconds, complete cleanup | Gateway subset is included, not additional unique cases |
| P3 issued execution | All 12 cases passed, zero skips/errors/failures; one verified post-resultcommit forced exit; 15.291 seconds, complete cleanup | Actual Python/TypeScript HTTP plus P1 PostgreSQL; typed synthetic A/B case reads (stale revision A, current revision B), no atomic action/delivery proof |
| Independent P3 reconciliation | Six accepted records, two cancellation commands, six issued attempts/results, exactly six Node evaluator invocations | Owner separately checked both scope fields, input/result hashes and issued-to-wire identity; four eligible, one cancelled and one superseded result |
| Previous P3 acceptance lane | All ten v1 coordinator/socket cases passed with postcommit kill/fresh lookup and cleanup; 10.534 seconds | Confirms v1 compatibility; its direct HTTP probes remain independent of execution issuance |
| P1 built artifacts | 66 package source payloads agree across wheel/source/rebuilt wheel; 18 commands, three isolated environments passed | Existing installed legacy consumers retained; new execution consumer below |
| P3 built artifacts | All 12 payload files agree across wheel/source/rebuilt wheel; offline builds passed | Declared pinned P1 postgres dependency; no workspace file dependency or credential/cache archive |
| New gateway installed consumer | Fresh offline npm install outside checkout, strict NodeNext without @types/pg, two runtime processes and actual HTTP/PostgreSQL passed; 2.644 seconds | Public exports only; typed case/agent and persisted single-operation filesystem adapters explicitly synthetic; schema/process/socket/temp cleanup verified |
| New Python installed consumer | Fresh offline P1/P3 wheels and specialist npm archive passed strict public typing, dependency consistency, v1 acceptance/v2 upgrade, actual issued HTTP, replay and second-process result read | One independently verified evaluator invocation, one work/attempt/result, exact original bytes/deadline and result hash; owner/runtime credentials split and schema/socket/process cleanup complete |
| Documentation/harness | 102 documents and scoped P1/P2/P3 docs/boundary/contract checks passed with zero violations | Scoped wrappers repeated offline suites; those supplemental runs are not added to 1,263 unique tests |
| Diagrams | All ten project diagrams parsed; malformed negative fixture rejected | Syntax only, not visual layout qualification |
| Rebuilt default Docker | Eight actual readiness/authentication/idempotency/conflict/real-time communication (RTC) text/audio checks passed; ten audio frames observed | Original M1 task and volumes preserved; ordinary transport only, no new model or product media gate |

### Independent review and retained failures

Independent automated reviews covered:

- the P1 profile/identity and catalog boundary;
- P2 ingress, startup, polling and close behavior;
- P3 result snapshots and lifetimes;
- the actual gate's credential, proof and cleanup boundaries.

Corrections included actual ingress fairness, monotonic startup and per-scan
deadlines, owned close after late bind, WebhookError-to-authentication mapping,
exact nested snapshot/status validation, consistent public observations and
prefixed UUID wire correlation. P3's gate now independently measures invocation
count. It verifies the current v2 marker while allowing cleanup of its known v1 or
v2 preparation state.

Retained failures:

- The first two actual P3 execution runs failed because the postcommit fixture
  wrote an empty marker rather than the owning process ID (PID) required by
  FileBarrier. Both failed reports retain `cleanup=true`. The corrected exclusive
  mode-0600 PID marker proves the declared arrival and owned forced exit; only the
  third report qualifies.
- P2's initial actual gateway failure exposed the incorrect bad-signature error
  classification. Socket fixture timing was corrected to wait for actual server
  accept/close events. No connection cap was weakened.
- Earlier runner fixtures exposed the wire grammar's leading-letter constraint.
  Both digit and letter UUID cases and known-expiry/stale-grant rejection now have
  regression coverage.
- Early test, format and type findings are retained where raw captures exist.
  Review notes identify transcribed findings where original failing output was
  not retained.

### Commands, evidence and next tasks

Run from the maintained repository with frozen tools and explicit local
restricted-role PostgreSQL setup:

```sh
make p2-gateway-check
make p3-execution-check
make p2-postgres-check
make p3-coordinator-check
make postgres-check
make check
make frontend-check
make format-check
make p1-package-check
.venv/bin/python -m harness.documentation_check
.venv/bin/python local-setup/stack.py start --observability
.venv/bin/python local-setup/stack.py smoke
```

Retained evidence:

| Evidence | Location |
| --- | --- |
| Source inventory, safe logs, exact reports, archived packages and installed consumer sources | `.local/validation/p2-gateway-p3-execution/e3777dc960ec433e83e6d8160e4533c8` |
| Original reports | `.local/validation/postgres`, `p2-postgres`, `p3-execution`, `p3-coordinator`, `p1-package` and `p2-package` |

Historical closed phase reports were preserved. Dependency locks and third-party
versions remain unchanged. Correctness durations and finite caps do not establish
production throughput or percentiles. New installed API consumers ran on host
Python 3.14.10/Node 24.22.2; a new complete platform/release matrix is not
claimed.

P2-I08 and P3-I07A are completed. Next are:

- P2-I09's agent-crash/replay path;
- P3-I07B's durable delivery plus one explicitly authorized fake action through
  the actual case authority.

Full P3-I07 and all 34 complete P2/P3 charter rows remain incomplete and
unregistered. The ordinary Compose console does not yet compose this
gateway/runner. Native transitions, the outbox, broader restart/workload/media
and release assertions keep their separate gates. The selected P1
`provider_real` v2 local qualification remains historical and source-bound; no
paid inference or provider secret file was used here.

AI assistance implemented and independently reviewed this work. No human
sign-off, real carrier, remote continuous integration (CI), publishing, staging
or commit is claimed.
