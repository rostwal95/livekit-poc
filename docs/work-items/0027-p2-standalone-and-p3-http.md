# P2 standalone intake and P3 specialist HTTP boundary

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Record the P2 standalone intake example and the P3 specialist HTTP boundary and the gates they passed |
| Audience | Engineers changing P2 standalone exports or P3 specialist HTTP and its client; reviewers; coding agents |
| Scope | Tasks P2-I06 and P3-I05; excludes P2 dispatch and outbox, P3 coordinator durability, models and media |
| Owns | P2-I06 and P3-I05 change plan, observed verification and handoff |
| Related | [PostgreSQL inbox](0026-p2-postgres-inbox.md) · [Specialist contracts](0025-p3-specialist-contracts-and-trust.md) · [Dispatch and coordinator](0028-p2-dispatch-and-p3-coordinator.md) · [Validation plan](../validation-plan.md) |

## Behavior and scope

This work item implements tasks P2-I06 and P3-I05 after the reviewed durable-inbox
and specialist trust slices:

- P2 provides the first standalone fake-carrier example through declared exports
  and narrow case, scripted-agent and operation-observation ports.
- P3 exposes one scripted read-only `booking.evaluate_policy` capability through
  authenticated, bounded local HTTP and a typed client.

No new dependency or database migration is planned. Preserve P1 behavior and its
historical selected-provider qualification.

These tasks contribute bounded assertions to acceptance IDs P2-01, P2-02, P2-12,
P2-16, P3-01 and P3-11. Their presence certifies no complete charter acceptance
row or integrated release. P2 recoverable dispatch/outbox, P3 coordinator
durability, protected case/result races, models, browser UI and media remain later
tasks.

| Criterion | Given / When | Safety | Useful progress and evidence |
| --- | --- | --- | --- |
| Standalone P2 | Explicit public adapters and prepared isolated PostgreSQL; sign synthetic input, accept, then replay in a new process | No P1/P3 application imports; no acknowledgement before commit; missing adapter fails visibly | Original receipt, operation key and pending intent survive; authenticated preview returns current bounded observations |
| P2 observation | Case/agent/operation adapter fails or changes scope after receipt | Failure cannot undo acceptance or fabricate executed/delivered work; bounded resources remain owned | Original receipt remains inspectable and a later valid preview progresses |
| Specialist HTTP | Independently configured service principal/evidence plus strict version-1 input | Body scope cannot authorize; invoke/result/cancel/evidence grants remain distinct; immutable source binding is checked | Real loopback request returns a matching grounded read-only candidate |
| HTTP resources | Slow, truncated, excessive, disconnected or concurrent input/response | Finite socket/body/header/time/attempt/response/cleanup bounds; no waiting or recovering queue; timeout is not proof computation stopped | Admitted work/other allowed principal and work after release still progress |
| Diagnostics and artifacts | Sentinel data, injected dependency/telemetry failure and isolated packed consumer | Fixed errors/events/counters exclude bodies/tokens/URLs/raw exception text; package needs declared dependencies only | Actual public example and handler/client function outside checkout; cleanup succeeds |

## Interfaces and ownership

### P2 standalone export

P2 owns an explicit server-only standalone export and example. Signed raw input
uses ChannelInbox's durable acceptance; preview is a separate authenticated read
path. Its ports inspect the current case, produce bounded scripted read-only text
and inspect the persisted operation identity. They never turn a preview into a
business mutation or claim durable dispatch. The original inbox remains pending.

### P3 specialist HTTP

P3 extends the existing TypeScript specialist package and its
zero-runtime-dependency Node HTTP surface. It reuses the strict contracts,
LocalTrust, EvidenceRegistry and AttemptBoundary. Attempt observations are
ephemeral, and P1 remains the eventual execution owner. No callback retry
scheduler, durable specialist queue, arbitrary source fetching or model client is
introduced. Trusted local configuration chooses the identity, evidence and
loopback endpoint. Raw body principal labels grant no rights.

### Implementation ownership

| Owner | Responsibility |
| --- | --- |
| Primary agent | Shared commands, the harness/documentation inventory, isolated artifact integration, final gates and the handoff |
| Separate implementers | The frozen P2 and P3 boundaries |
| Independent automated reviewer | Checks API, failure and resource semantics |

No staging, commit, publishing, remote continuous integration (CI), provider
secret file or paid service call is part of this slice.

## Failure cases and validation

Gate names starting with G- refer to the engineering gates in the
[validation plan](../validation-plan.md). G-HTTP P3 is specific to this work item.

| Gate | Required assertion and exact existing lane | Prerequisite/budget and limit |
| --- | --- | --- |
| G-READY/CONTRACT | Review explicit port/endpoint schemas, authentication/commitment/resource ownership, safe codes and useful outcome; strict shared codecs remain compatible | Freeze before implementation; no new execution authority |
| G-FAST | make check, make frontend-check, make format-check and documentation checks | Frozen local Python/pnpm toolchain; no skipped/missing/zero-test lane passes |
| G-DURABLE P2 | Explicit p2_postgres_check.py lane, public standalone example and actual new-process replay | Prepared restricted local PostgreSQL; owned random schemas/children; cleanup and original identities mandatory |
| G-HTTP P3 | Actual loopback sockets in the specialist Vitest suite; typed-client request/result parsing | No external network/provider; finite ingress, execution and cleanup budgets; caller disconnect cannot silently free live work |
| G-OBS | Inspect real fixed events/counters and safe exceptions with sentinel body/token/dependency data, including telemetry failure | No invented exporter or durable metric totals; no unhandled rejection |
| G-PACKAGE | Build/pack each package; fresh outside-checkout consumer runs P2 public example against local PostgreSQL and P3 HTTP/client | No sibling source import, PYTHONPATH injection or undeclared dev-only driver types; synthetic credentials only |
| Existing-runtime regression | Rebuild affected Docker context and run stack.py smoke | Preserve volumes/M1 (confirmed-investigation intake) identity; transport smoke does not qualify P2/P3 media |
| G-MEDIA/RELEASE | Deferred to their actual phase gates | No new browser/model/media or full product-release claim |

Use barriers for active-work schedules and actual socket closure for disconnect
proof. A malformed or forged request must fail without preventing an
independently valid current request. Resource timers and abort handlers have
explicit owners. Request abort, computation completion, cancellation observation
and release remain separate facts. Neither timing out nor returning valid JSON
grants case authority.

Node APIs must work on both advertised host/runtime majors, 24 and 26. The
[official HTTP documentation](https://nodejs.org/api/http.html) defines transport
lifecycle. Verify behavior on installed runtimes rather than relying on a timeout
option to terminate work. Public exception codes and process-local metrics are
specified in project documentation alongside their implemented producers.

## Results and handoff

### Outcome

P2-I06 and P3-I05 completed their selected implementation and local gates with
independent automated source/API/failure review. Phase P2-A's backend standalone
acceptance/replay proof is present; its future browser projection is explicitly
separate. Phase P3-B still needs coordinator acceptance and a useful durable
result path. All 34 complete P2/P3 charter rows remain planned/unregistered. These
bounded task results do not certify the two full products or integrated
media/release.

### Observed gates

| Executed gate | Observed result |
| --- | --- |
| P2 focused and actual storage | 150 TypeScript tests, source/test checks and public/example builds; 11 offline wrapper tests and strict wrapper typing; full actual PostgreSQL lane passed all 14 cases, zero failures/errors/skips, expected one SIGKILL recovery and complete cleanup |
| P2 standalone demo | Two actual cases passed with two normally exiting fresh public-example processes; safe accepted/replayed projection shows the same receipt, operation key and sequence, pending/not_executed; zero skips and cleanup complete |
| P3 focused HTTP | 36 real-loopback tests passed after source review; strict source/test TypeScript passed; one controlled native ServerResponse failure is explicitly injected on a real request |
| Shared Python and harness | 1,165 tests: 1,091 root, 21 P1, 14 P2 and 39 P3; zero skips or structural violations; Ruff passed, maintained typing covered 97 sources and strict typing 38 |
| Shared frontend | 554 tests: 326 console, 150 P2 and 78 P3; strict checks, Prettier, console production build and both package/example builds passed |
| Documentation and diagrams | All 100 maintained documents checked; 236 Python files formatted; six project Mermaid diagrams parsed and malformed syntax rejected, without a visual-layout qualification claim |
| Installed public artifacts | Fresh npm-pack consumer outside checkout installed offline with scripts disabled; strict types passed without @types/pg; public imports resolved inside installed packages; archives contain no private environment/generated-state/dependency trees |
| Installed P2 actual database | Shipped compiled example copied unchanged into the fresh consumer and run twice with runtime-only credentials; independent SQL reconciliation found one original receipt/pending intent; owner-marked disposable schema and children cleaned up |
| Host/Linux runtime | Node 24.22.2 host public examples passed; pinned Linux Node 26.13.0 nonroot/read-only/network-isolated container passed P3 actual HTTP plus P2 codec/hash-based message authentication code (HMAC)/typed-fake-port preview; Linux P2 database behavior is not claimed by that subset |
| Advertised commands and Docker | Both make p2-demo and make p3-demo passed; affected stack rebuilt with observability ready and all eight transport/authentication/M1 smoke checks passed, ten actual audio frames and original M1 identity preserved |

Frozen offline installation passed, and both dependency lockfiles are unchanged.
Comparison against the prior checkpoint confirms that 108 P1/runtime/console
source files are unchanged. Historical P1 selected-provider qualification and
prior phase reports are retained. No new P1 PostgreSQL/provider release run is
claimed. The existing console bundle-size advisory remains; no UI source change
was made.

### Implemented behavior

P2 exposes `./standalone` with explicit inbox, case, scripted-agent and operation
inspection ports:

- Intake returns a committed receipt before any preview work.
- Preview authenticates the receipt and validates exact scope, case revision,
  operation identity and pending state at every adapter boundary.
- Missing adapters fail before intake. Changed scope or a later adapter failure
  cannot erase acceptance.
- At capacity, an adapter that ignored abort retains its slot until actual
  settlement.
- Helper close owns previews. The caller owns its supplied inbox and in-flight
  intake.

P3 exposes SpecialistServer and SpecialistClient from the root and `/http`, with
no import-time listener, provider client or new dependency. Invoke requires
invoke, result and evidence grants. Status and cancel require their separate grant
and an exact active attempt. It returns a source-grounded scripted candidate and
ephemeral observations. It provides no durable acceptance, action permission,
terminal history or retry ownership.

Metrics and fixed events describe real process-local observations, with at most
eight unsettled observer notifications. Bodies, tokens, proofs, URLs and raw
exceptions are excluded. Counter reset, computed result, response delivery,
business authority and cancellation stop remain distinct. No exporter or
production throughput is claimed. P3's trusted harness-only barrier and observer
own any external resources they create and cannot be selected by request JSON.

### Independent review and retained failures

Review findings produced tested fixes rather than weaker gates:

- Monotonic stage, final-result and cleanup checks reject overdue success even
  when event-loop delay postpones timer callbacks. This covers P2 preview/close
  and P3 headers/body/evaluation/client response/cleanup.
- P3 owns pending bind and rejects concurrent listen safely. Close publishes its
  promise before abort callbacks, caches successful idempotency and waits for
  actual socket/request/work retirement. Reentrant observers cannot create another
  life.
- Aborted or closing work never enters a later harness hook. Ignored abort keeps
  the original attempt permit until settlement; incomplete cleanup is non-passing.
- Raw headers are counted without truncation. Duplicates and framing errors,
  slow/truncated/oversized input, pipeline reuse and request/socket/attempt
  saturation fail within finite bounds, while independently admitted and
  subsequent work progresses.
- Unexpected HTTP failures return sanitized 500/internal_error. Generated error
  IDs obey the frozen identifier grammar. Owned ServerResponse errors are handled
  and cleaned without an unhandled event or private sentinel reflection.
- Public examples enter maintained source/import boundaries. The harness negative
  fixture proves that private cross-project imports and missing example sources
  fail, then proves that the public-import path still passes.

Early P3 test findings and counts are retained as explicitly transcribed review
notes, because the original failing raw captures were not saved. The final 36-test
raw log is retained separately. Machine evidence records this distinction. No
historical raw report or independent human sign-off is manufactured.

### Commands, evidence and next tasks

From the repository root with frozen Python/Node/pnpm and explicit restricted-role
PostgreSQL setup:

```sh
make p2-demo
make p3-demo
make p2-postgres-check
make check
make frontend-check
make format-check
.venv/bin/python -m harness.documentation_check
.venv/bin/python local-setup/stack.py start --observability
.venv/bin/python local-setup/stack.py smoke
```

Retained evidence:

| Evidence | Location |
| --- | --- |
| Actual P2 reports | `.local/validation/p2-postgres/i06-example-01.json` and `.local/validation/p2-postgres/i06-full-01.json` |
| Complete phase inventory, command logs, source index, final review notes, archives and standalone consumer/probe sources | `.local/validation/p2-p3-standalone-http/6fd0437afec743e39efb76d980ca17ae` |

Prior reports were not overwritten.

Package-consumer qualification is this selected local checkpoint. It is not the
complete later P2/P3 artifact release, Python wheel, durability, workload or media
gate. Correctness-run durations are not throughput or latency-percentile
measurements.

AI assistance implemented and independently reviewed these slices. No provider
secret file, paid inference, real carrier, remote CI, publication, staging or
commit was used.

Next tasks:

- Implement P2-I07's persisted recoverable dispatch under the original operation
  identity, then its revision/routing/outbox gates.
- Implement P3-I06's Python coordinator through public P1 execution/case/delivery
  ports before P3-I07's current-result/action path.

Preserve the existing authority and explicit human confirmation. HTTP success and
candidate provenance cannot authorize mutations.
