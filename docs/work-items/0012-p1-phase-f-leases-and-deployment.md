# P1 Phase F leases and bounded worker deployment

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Record the plan, observed verification and handoff for P1 Phase F tasks P1-I19 through P1-I21 |
| Audience | Engineers changing P1 leases, admission limits or worker deployment; coding agents |
| Scope | PostgreSQL v4 upgrade, database-time leases and epochs, fenced worker writes, admission limits and the opt-in worker profile; excludes public business HTTP, voice tools, distributed media and full release |
| Owns | Change plan, observed verification and handoff for P1-I19 through P1-I21 |
| Related | [Work item 0011](0011-p1-phase-e-effects-and-completion.md) · [Work item 0013](0013-p1-phase-g-conversation-and-showcase.md) · [Lease decision](../decisions/0006-database-leases-and-bounded-worker.md) · [P1 task plan](../implementation/p1-agent-continuity.md) · [Validation plan](../validation-plan.md) |

## Behavior and scope

Implement P1 (Agent Continuity Lab) tasks P1-I19 through P1-I21 from the
[granular roadmap](../implementation-plan.md) after the completed Phase E gate.
Add an explicit ACTIVE PostgreSQL v4 upgrade, database-time leases and
monotonically retained execution epochs. Fence every worker write in its existing
short transaction. Preserve case consent, stable effects, uncertainty, independent
delivery and the SQLite compatibility subset. Add an opt-in bounded actual P1
worker profile and repeat preserved-volume restart, waits and recovery. The
browser and API remain on M1, the original SQLite confirmed-investigation intake.

### Criteria

| Requirement contribution | Given/When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- |
| P1-15 / P1-I19 | Two independent workers claim, renew, release or take over | One current unexpired owner/epoch; stale and missing grants cannot write; no stale renew/release resurrection | Expired owner is replaced; current work completes | Actual PG, database clock and owned processes |
| P1-09/15 / P1-I20 | Old worker pauses after reservation, successor takes over, old resumes | Supplier calls occur outside locks; cooperation deduplicates original effect; noncooperation stays uncertain without successor resend | Cooperating current worker recovers known result | Real independent processes and persisted supplier |
| P1-10/17/18/19 / P1-I21 | Saturation, SIGTERM/hard deadline and fresh installed worker | No rejected-work acknowledgement, accepted identity/receipts remain readable, no orphan child, no implicit activation/reset | Due managed work and pending delivery resume; waits consume once across restart | Admission races, supervised child tests and Docker restart |
| Migration/retention | Populated v3 upgrades or process stops at DDL/commit | Old rows/JSON/import receipts unchanged; owner-only additive v4; no runtime DDL/core deletion | Retry safely completes/reads original state | Populated versions, ACL/catalog drift and actual interruption |

The criteria table uses these abbreviations:

| Term | Meaning |
| --- | --- |
| PG | PostgreSQL |
| DDL | Data definition language |
| ACL | Access control list |

## Interfaces and ownership

This section records the frozen contracts and decisions for this phase.

### Admission limits

The `execution_limits` singleton retains these settings:

| Option | Default | Description |
| --- | --- | --- |
| `maximum_pending` | 1000 | Outstanding accepted business work |
| `maximum_active` | 4 | Active leases |
| `maximum_records` | 10000 | Retained task identities |
| `lease_seconds` | 30 | Lease duration in seconds |

The owner-only policy is read by every replica. Pending means outstanding accepted
business work, including durable waits and active work, not only base inquiry
status. Retention capacity is separate. Replay precedes new-admission capacity
checks.

### Leases and epochs

Execution leases retain task and scope, nullable owner and expiry, epoch and
timestamps. Use PostgreSQL `clock_timestamp` after admission and row locks. Worker
wall clocks never authorize leases. Acquire replay does not extend a live lease.
Renewal cannot resurrect expiry. Release retains the epoch. Waiting work releases
active capacity.

Every v4 worker claim, reservation and finish requires its explicit task-bound
grant inside the same protected transaction. Public owner commands and reads
remain separate. Old base inquiry writes cannot bypass v4 coordination.

### External requests

A lease fences local writes, not an external request already authorized or sent.
Cooperating supplier identity and effect lookup and deduplication remain required.
A possible noncooperating dispatch remains uncertain. Never infer reversal from
lease loss, process kill, timeout, cancellation or failed local acknowledgement.

### Worker runtime

The runtime owns one bounded child step and no acknowledged memory queue. A step
has a monotonic deadline shorter than its persisted lease. SIGTERM stops new
acquisition and drains, or kills and reaps, its owned child. Durable state survives
forced shutdown. Fixtures and schema activation remain explicit operator tasks.
The runtime receives only restricted credentials and no Docker socket. No new
direct dependency, model call, distributed media or full release claim is
introduced.

## Failure cases and validation

Required evidence:

- Typed negative and normal contracts.
- Actual multi-process epoch and external boundary tests.
- Pending, active and replay limits.
- Graceful and forced shutdown.
- Explicit migration and privilege tests.
- Installed local restart.
- Unchanged M1 and real-time communication (RTC) smoke.

Keep missing setup, zero tests, skips and timeouts non-passing. Preserve failed
artifacts and finite budgets. Run database tests serially with image rebuilds.
Update docs, diagrams, harness and exact evidence before marking completed.

## Results and handoff

P1-I19 through P1-I21 completed. The final machine gate is
`.local/validation/p1-phase-f/phase-gate.json`. The dependency and image baseline
stayed frozen. No public business HTTP or voice tool was added.

### Observed gates

| Observed gate | Command or mode | Result |
| --- | --- | --- |
| Offline/shared harness | make check | 482 tests, zero skips; structural/ownership/negative fixtures, Ruff and normal typing of 56 service/core files pass |
| Strict changed boundaries | mypy --strict --follow-imports=silent | 23 authority/continuation/effect/migration/lease/runtime files pass; the process helper remains separately strict; this is not whole-repository strict typing |
| Real PostgreSQL | make postgres-check with phase report | 237 tests, zero failures/errors/skips: 186 retained earlier suites, 23 v4 upgrades, 14 lease and 14 integrated coordination tests |
| Frontend regression | make frontend-check | TypeScript, 66 tests in three files and production build pass; existing bundle advisory retained |
| Documentation/diagrams | Documentation checker and actual Mermaid parser | 74 documents and 33 diagrams across 11 designs pass; invalid Mermaid fixture rejected |
| Formatting | Ruff format check | 129 Python files pass |
| Actual worker deployment | Rebuild then make phase-f-demo | Two actual profile containers, three starts, 44 core module hashes match installed site-packages code; preserved waits, exact signal and pressure/progress proof |
| Installed legacy compatibility | Phase E demo against the rebuilt package | ACTIVE v3 supplier/receiver external-commit losses recover; 44 installed modules match; original Phase E closing artifact restored byte-for-byte |
| Native media/M1 regression | local-setup/stack.py smoke | Text/UTF-8 and 10 audio frames pass; original M1 investigation identity preserved |
| Complete acceptance catalog | harness run --project all | Six registered runners pass; 49 lack complete registered runners; expected exit 2 remains incomplete portfolio qualification |

### Docker proof

The Phase F Docker proof observed:

- two waits retained after graceful stop
- one persisted confirmation signal consumed exactly once after restart
- rejection without a new durable task at outstanding capacity
- original replay at capacity
- acceptance and useful inquiry progress after business completion freed capacity

The shared active limit was one. All 44 sampled counts respected it, and a live
lease was positively observed. The supplier recorded one physical mutation/apply
and three logical inquiries. The receiver retained three logical completions: the
primary success and two explicit precommit cancellations. The original primary
outcome and event remained unchanged. All three graceful stops exited zero and
reported not-ready with no active owned child. The demo schema, labelled fixture
volume and containers were cleaned before the passing artifact was written.

### Takeover tests

The independent-process tests follow this sequence:

1. Pause an old worker after reservation or supplier success.
2. Wait for actual database expiry.
3. Permit a newer epoch to finish.
4. Resume the old process.

The old process's acknowledgement is rejected. Cooperating effect keys prevent a
second physical booking change. Genuinely noncooperating possible requests stay
uncertain without successor resend. This proves the documented cooperation
boundary, not a hard fence for every in-flight external request.

### Review corrections

Independent reviews corrected late-management and retained-M1 admission paths,
unsupported, stale and exhausted selector eligibility, unmanaged-running upgrade
recovery, no-wait inquiry expiry and delivery without a managed control. Runtime
tests exercise real SIGTERM drain and forced cleanup and descendants, output caps,
release-after-reaping, Unicode claim bounds, private health and metrics, producer
severity and hostile diagnostic metadata. The host-specific exited-group handling
remains bounded. Live permission errors fail visibly. Test scheduling was
corrected to respect the existing one-second lock budget. Production budgets were
not relaxed. Failed iteration artifacts remain separate from passing gates.

### Evidence and next step

Evidence under `.local/validation/p1-phase-f` includes actual database and fast
outputs, strict, format and frontend checks, diagram results, original and
compatibility artifacts, profile timeline, real metrics and logs, runtime build,
native smoke and source manifest. Prior phase gates remain historical. Work was
implemented and reviewed with Codex assistance. Personal reproduction and
explanation are not asserted as a human implementation contribution. Observed
platforms are host macOS and Linux containers with Python 3.14. The full
advertised version and platform matrix and remote CI execution remain unverified.

Next is Phase G, P1-I22 through P1-I25: native conversational tools, authenticated
business projections and UI, application trace export and actual speech and
session interruption evidence. Full library packaging, benchmark and model
quality, production identity and transport, distributed media and complete
portfolio release remain separate gates. No uncertainty was converted into an
automatic unsafe retry, and normal restart never used reset.
