# Recoverable P2 dispatch and P3 durable submission

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Record recoverable P2 dispatch, the P1 accepted-work profile and P3 durable submission and their gates |
| Audience | Engineers changing P2 dispatch, the P1 work profile or the P3 coordinator and client; reviewers; coding agents |
| Scope | Tasks P2-I07 and P3-I06 plus the P1 read-only accepted-work prerequisite; excludes media and complete charter gates |
| Owns | P2-I07 and P3-I06 change plan, observed verification and handoff |
| Related | [Standalone and HTTP](0027-p2-standalone-and-p3-http.md) · [Gateway and issued execution](0029-p2-gateway-and-p3-issued-execution.md) · [P2 task plan](../implementation/p2-channel-continuity.md) · [P3 task plan](../implementation/p3-delegation-reliability.md) |

## Behavior and scope

This work item implements tasks P2-I07 and P3-I06 after the
[standalone/HTTP checkpoint](0027-p2-standalone-and-p3-http.md). It adds the
minimum public P1 read-only accepted-work profile required to store a complete
immutable delegation envelope.

- Existing P1 booking v4 (PostgreSQL booking schema version 4) and SQLite
  profiles remain unchanged.
- P3 owns no database ledger or recovering queue.
- P2 owns channel dispatch claims, not supplier execution or booking mutation.

Complete charter and media gates stay separate from these bounded tasks.

| Criterion | Given / When | Safety | Useful progress and evidence |
| --- | --- | --- | --- |
| P2 schema/dispatch | Upgrade a validated v1 inbox explicitly through its owner, then claim a committed message | Preserve original canonical bytes, receipt, operation key and sequence; runtime performs no data definition language (DDL); stale claim cannot finish | Existing acceptance/replay/read examples still work and eligible original work progresses |
| P2 acknowledgement loss | A cooperating operation acceptor commits before the dispatcher loses its acknowledgement | Prepared submission and possible-external marker precede I/O; retry never changes the logical key/payload or claims exactly-once computation | Fresh claimant reconciles independently persisted original acceptance under bounded attempts |
| P1 prerequisite | Trusted scoped client submits opaque bounded read-only bytes | Exactly one accepted row per tenant/account/key; no body scope override, automatic install or booking authority | Actual PostgreSQL replay/find/cancel and new-process lookup preserve original bytes/digest/deadline |
| P3 coordinator | Validated case preflight and strict delegation envelope are submitted through public P1 port | Snapshot before await/acknowledgement; conflict preserves original; no second execution owner or false current-case-at-commit claim | Submitted work and cancellation remain inspectable independently of Python coordinator lifetime |
| Python HTTP | Typed client invokes existing TypeScript service through real loopback sockets | Strict capped protocol/identity/expiry, no proxies/redirects/retries; waiter cancellation retains resources until actual cleanup | Valid candidate/status/cancel observations progress after malformed/slow/overload cases |

## Interfaces and ownership

### P2 dispatch

P2 adds:

- an explicit owner-only v1-to-v2 migration;
- bounded persistent claims and attempt history;
- an immutable prepared read-only operation submission;
- a one-step dispatcher.

Processing states become truthful pending, running, dispatched, blocked,
exhausted or uncertain observations. The standalone preview refuses nonpending
input. Once an external call is possible, state never returns to pending.
Database lease fencing cannot itself fence an already paused external request.
The fake operation port explicitly cooperates through stable identity and lookup.

### P1 accepted-work profile

P1 adds public `work_api`/`work_admin` for an opt-in marked version-1 read-only
work profile. It stores accepted payload bytes, digest and deadline once per typed
scope/key, with separate cancellation commands and finite retained caps. Status
remains accepted. There is no generic worker, attempt issuer, completion or
delivery in this prerequisite.

P1 is the owner of these accepted records; they do not duplicate existing booking
execution rows. Runtime uses restricted credentials and explicit scope-bound
clients. The existing local runtime role is shared and is not a claim of
independent database-principal isolation.

### P3 coordinator

P3 adds a Python coordinator submit/find/get/cancel boundary, an explicit
read-only case preflight and strict immutable replay comparison. A proposed wire
attempt is not a P1-issued execution permit. A caller's attempt-only retry may
return the original accepted snapshot; actual semantic changes cannot. Case
validation is a preflight for read-only input, not atomic current action
authorization. Durable result/action/delivery and recovering workers remain
P3-I07 and later work.

### Python HTTP client and packaging

The independent Python HTTP client uses owned asyncio streams and exact protocol
bounds. It adds no HTTP runtime dependency. The P3 distribution declares the P1
public library dependency. Root owns lock/workspace integration and the actual
gates. No provider credentials, paid services, Git publication or remote
continuous integration (CI) is needed.

## Failure cases and validation

Gate names starting with G- refer to the engineering gates in the
[validation plan](../validation-plan.md). G-HTTP is specific to this work item.

| Gate | Required lane | Completion rule |
| --- | --- | --- |
| G-READY/CONTRACT | Frozen public model/port/schema/resource decisions and independent automated review | Resolve P1 API fit before claiming durable coordinator integration |
| G-FAST | Full make check, make frontend-check, make format-check and documentation | New sources enter strict typing and discovered tests; zero skips/missing checks |
| G-DURABLE P2 | Actual migration preservation, concurrent claims, expiry/takeover, rejection, capacity and operation-response-loss reconciliation | Separate persisted acceptor/owned processes; no I/O under database locks; useful recovery and cleanup |
| G-DURABLE P1/P3 | Actual PostgreSQL scoped acceptance/replay/conflict/cancel/caps and lost-acknowledgement/new-process original lookup | Immutable complete bytes and digest stored before acknowledgement, no fake port substitutes |
| G-HTTP | Actual Python-to-TypeScript plus malformed/late/truncated/abort/close socket tests | Finite body/header/response/lifetime limits and actual owned cleanup |
| G-OBS | Fixed logs/exceptions/counters with sentinel input/dependency failure | No raw payload/token/proof/URL/SQL parameters or unhandled background failure |
| G-PACKAGE | Applicable built public artifacts and outside-checkout consumers | Declared P1 dependency; no internal storage imports or repository path injection |
| Regression | Existing P1 PostgreSQL, runtime/packaging and default Docker smoke as affected | Retain historical evidence and original M1 (confirmed-investigation intake) identity; no volume reset |
| G-MEDIA/RELEASE | Deferred | No new model/browser/media, completed charter or production-capacity claim |

Keep retained identity, cancellation and attempt protection bounded and durable.
No cleanup may silently allow late duplicate acceptance. Operation timeouts and
cancellation observations do not prove external termination. Record exact budgets
and raw correctness observations before interpreting performance.

## Results and handoff

### Implemented behavior

P2-I07 now has:

- an owner-only v1-to-v2 upgrade;
- database-time claims with owner/epoch fencing;
- a three-attempt policy;
- persisted immutable preparation;
- bounded lookup/accept through an explicitly cooperating operation port.

Claim transactions finish before external I/O. Possible external submission is
recorded before the call. Uncertain work never returns to pending, including after
attempt exhaustion. Lookup-only reconciliation cannot execute another accept.
Reassociation cannot retarget old input. The standalone preview rejects every
nonpending state.

P3-I06 now snapshots and validates the complete strict envelope before awaiting.
It checks its verified P1 scope before any submission and uses public P1
accepted-work submit/find/get/cancel. Attempt-only replay returns the original
accepted bytes; semantic changes conflict. Ambiguous acknowledgements reconcile
the original record. The read-only case preflight is explicit. A committed P1
projection whose cancellation state is ambiguous fails closed. No P3 ledger,
issued attempt, autonomous scheduler, result storage or action permission was
added.

The opt-in P1 profile has:

- immutable scoped records;
- separate idempotent cancellation commands;
- persisted finite admission counters;
- database time sampled after locks;
- owner installation and catalog/role validation.

Existing booking v4 and SQLite data are preserved. Four actual I/O slots remain
owned after caller cancellation until the underlying thread finishes. Query
budgets apply per statement; they do not promise a five-second whole-operation
database deadline. The shared local runtime role is not independent principal
isolation. Body bytes are opaque to P1; P3 owns delegation schema and semantic
validation.

The Python HTTP client owns bounded loopback streams and validates exact framed
responses and correlated attempts. It keeps canceled or timed-out resources until
cleanup. It has no proxy, redirect, retry or third-party HTTP dependency. Fixed
error codes, sanitized logging and bounded process-local metrics distinguish
received observations, validated candidates, accepted work and requested
cancellation. Telemetry failure cannot reverse committed truth.

### Observed gates

| Gate | Observed result | Qualification boundary |
| --- | --- | --- |
| Full fast Python | make check passed 1,223 tests: root 1,106; P1 28; P2 14; P3 75; zero skips | Ruff and broad mypy 105 / strict mypy 48 source files passed |
| Frontend and examples | make frontend-check passed 572 tests: console 326, P2 168, P3 78; type/build/format passed | Existing console bundle-size advisory remains; no UI/media change in this slice |
| Python formatting | make format-check passed 251 files | No formatter suppression introduced |
| P1 PostgreSQL | 276 tests, zero errors/failures/skips, 225.793 seconds | Includes 13 actual new-profile cases; all existing booking/migration lanes retained |
| P2 PostgreSQL | Full 19 cases, two owned forced exits, complete cleanup; dispatch subset five cases, one forced exit; standalone example two cases | The subset is included in the full lane; synthetic scoped case/agent ports and a separate persisted operation acceptor are explicit |
| P3 coordinator/HTTP | Final reviewed report: 10 cases, zero skips, one verified postcommit forced exit, 18.468 seconds, complete cleanup | Actual PostgreSQL and Python-to-TypeScript sockets; case preflight is typed synthetic; HTTP invocation is independent of accepted-work execution |
| P1 artifacts | 63 source payloads match wheel, source archive and rebuilt wheel; 18 commands / three isolated environments passed | Legacy installed examples plus separate new API consumer below; no new platform-wide release claim |
| New Python installed APIs | Fresh offline environment, built P1/P3 wheels, strict public typing, dependency consistency, actual PostgreSQL submit/replay/conflict/cancel and second-process read passed | Independent owner verified one accepted record, one cancellation, original bytes/hash/deadline, then removed the marked schema |
| New P2 installed API | Fresh outside-checkout offline npm installation, strict TypeScript without @types/pg, actual v1 install/v2 upgrade/signed input/dispatch and second-process replay passed | Case/agent and single-operation filesystem adapters are synthetic; durable recovery proof belongs to the separate source integration lane |
| P3 installed HTTP | Built Python wheel and npm archive communicated through actual loopback sockets; active status, requested cancellation and grounded candidate passed | Python active and Node active/requests/sockets all reached zero; no coordinator-issued execution or provider call |
| Documentation/harness | 101 documents and scoped P1/P2/P3 docs/boundary/contract checks passed with zero violations; all 10 current project Mermaid diagrams parsed and malformed input was rejected | Diagram syntax only, not visual-layout qualification |
| Default Docker regression | Rebuilt observability-enabled stack; all eight actual transport smoke checks passed and ten audio frames were observed | Original M1 task identity and persistent volumes survived; scripted transport only, no new provider/model/media qualification |

All 34 complete P2/P3 acceptance rows remain planned and unregistered. These
focused tasks are completed independently of the later complete charter gates.
Durations describe correctness runs, not throughput or latency-percentile results.
The previous selected `provider_real` v2 P1 qualification remains historical and
source-bound; no paid inference gate was rerun.

### Independent review and retained failures

Independent automated source review covered the P1/P2/P3 lifetime, storage,
recovery and credential boundaries. P1's trusted credential inventory now bounds
actual yielded entries as well as reported mapping size. Empty or overflowing
custom mappings fail, and all 64 legitimate entries progress. The final seven-test
public-value subset and the full fast lane passed after this correction.
Schema/admin validation also received a separate read-only review. Concurrent
untrusted-owner DDL is outside this local profile's guarantee.

Corrections included:

- monotonic late-success/cleanup checks;
- retained local occupancy after ignored abort;
- strict external receipt matching;
- fixed safe telemetry codes.

The P3 gate now gives runtime children only the runtime password. Explicit
install, reconciliation and cleanup children receive only the owner password.
Child environments reject ambient provider, libpq and Node selectors. The closed
platform allowlist includes the macOS-injected text-encoding variable.

Retained failures:

- The first P3 10-case report passed functionally but is nonqualifying because its
  child credential roles were too broad.
- The first corrected runner then failed before useful assertions on the macOS
  environment key. Its schema was independently confirmed absent. Both reports are
  retained beside the final qualifying report.
- P1's first focused run had two DDL test-fixture fetch errors. Those were
  corrected, and the failed report is retained.
- An intermediate 12-case pass precedes the final 13-case profile included in the
  276-case lane.
- A temporary installed-HTTP helper had an invalid invisible character before
  execution. Its failed log and corrected passing run are retained.
- Initial offline dependency installation lacked cached pinned wheels. Normal
  TLS-verified package preparation preceded the genuinely fresh offline
  installation.
- The diagram helper's stale nine-diagram assertion was updated to the actual
  3/4/3 inventory; no diagram syntax defect was hidden.

### Commands, evidence and next tasks

Use the frozen toolchain from the root README and explicit restricted-role local
PostgreSQL setup:

```sh
make p2-dispatch-check
make p2-postgres-check
make p2-demo
make p3-coordinator-check
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
| Final source index, raw safe logs, artifacts, consumer scripts, reviewed failures and phase summary | `.local/validation/p2-p3-dispatch-coordinator/cba83e6c314b4fe2bba2068ae13bf13c` |
| Original integration reports | `.local/validation/postgres`, `.local/validation/p2-postgres` and `.local/validation/p3-coordinator` |

Existing reports were preserved. Each installed-consumer proof records its actual
versus synthetic adapters and owned cleanup.

All 11 P3 package payload files match the wheel, source archive and offline
rebuilt wheel. The P3 wheel declares `agent-continuity[postgres]` 0.1.0.
`uv.lock` records this dependency edge, while `pnpm-lock.yaml` remains unchanged.

Next, implement P2-I08's actual gateway restart path, then revision/routing
behavior. Also implement P3-I07's P1-issued execution, current-result validation
and applicable result/action/delivery behavior according to their subordinate task
plans. Accepted status, proposed wire attempts, HTTP candidates and cancellation
requests grant none of that future authority. Gateway composition, browser
transitions, outbox and broader workloads/media follow their own gates.

AI assistance implemented and independently reviewed this work. No human sign-off,
production-capacity result, provider call, real carrier, Git publication, remote
CI, staging or commit is claimed.
