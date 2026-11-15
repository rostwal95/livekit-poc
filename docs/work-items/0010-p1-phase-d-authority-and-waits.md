# P1 Phase D exact consent and durable continuation

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Record the plan, observed verification and handoff for P1 Phase D tasks P1-I11 through P1-I14 |
| Audience | Engineers changing P1 case authority, confirmation, waits or retry policy; coding agents |
| Scope | Revisioned case snapshots, exact quotes and confirmation, atomic intent commitment, durable waits and signals, and finite retry and deadline policy; excludes supplier mutation, cancellation, leases and event delivery |
| Owns | Change plan, observed verification and handoff for P1-I11 through P1-I14 |
| Related | [Work item 0009](0009-p1-phase-c-postgres-cutover.md) · [Work item 0011](0011-p1-phase-e-effects-and-completion.md) · [Case authority decision](../decisions/0004-case-authority-and-continuation.md) · [P1 task plan](../implementation/p1-agent-continuity.md) · [Validation plan](../validation-plan.md) |

## Behavior and scope

After the completed Phase C gate, implement P1 (Agent Continuity Lab) tasks
P1-I11 through P1-I14 from the [granular roadmap](../implementation-plan.md). They
add canonical revisioned case snapshots, exact quotes, confirmation and atomic
action-intent commitment, durable waits and signals, and finite retry and deadline
policy. Rich lifecycle uses PostgreSQL. Retain the existing SQLite inquiry proof
and the live M1 application (the original SQLite confirmed-investigation intake).
Actual fake booking mutation, cancellation, leases and event delivery follow
later.

### Criteria

| Criterion | Given | When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- | --- |
| P1-06/07 contribution | Current case/quote and authenticated owner | Commit exact explicit confirmation | Missing/changed/stale/expired/wrong-actor input creates no intent/dispatch | Valid confirmation commits one immutable intent and stable dispatch event | Real PostgreSQL validation/race/replay tests |
| P1-10/11 contribution | Persisted wait, typed signal and absolute deadline | Signal before/after wait or restart | Scoped changed replay conflicts; unrelated/expired signal never grants authority | Exact current signal consumes once under the original task | Independent process and real local container evidence |
| P1-12 contribution | Admitted inquiry and finite retry policy | Transient/permanent/ambiguous error or deadline | No infinite retry or unsafe ambiguous resend; budget remains finite | Eligible transient retry progresses with the original effect | Fake clock, actual worker and independent supplier ledger |
| Retention | Persisted requests, signals, confirmations and effects | Expiry, overload or repeated command | Identity protection is retained; no cleanup/recreation path | Existing replay/read remains available at capacity | Explicit no-prune contract and late replay tests |
| Schema upgrade | Populated ACTIVE PostgreSQL v1 | Explicit owner-only v2 migration or interruption | All v1 inquiry data/receipt survives; serving never performs DDL | Repeated upgrade and old/new operations progress | Transaction rollback/process loss, role negatives and container |

## Interfaces and ownership

Keep the original task and execution identity.

| Component | Responsibility |
| --- | --- |
| Case authority | Owns the current request revision, owner, immutable quote and confirmation, and committed intent |
| P1 continuation control | Owns waits, the signal inbox and eligible inquiry attempts beside the existing inquiry tables; it is not another recovering queue |
| Trusted token service | Supplies actor and scope |
| Quote issuance | A trusted fixture producer operation, separate from the user's explicit confirmation command |

The inquiry result and overall continuation disposition remain distinct. No
schema or runtime dependency upgrade is bundled into this feature slice.

Case updates and commitment serialize under the same short authority transaction.
A revision that commits first invalidates stale confirmation. An intent that
commits first cannot be rewritten by a later revision. Confirmation consumption
and intent and dispatch insertion share one transaction. Check expiry after
acquiring locks.

## Failure cases and validation

The gate names in this table are the engineering gates defined in the
[validation plan](../validation-plan.md#engineering-gates-and-acceptance-authoring).

| Gate | Applicable and why | Exact tests/assertions | Prerequisite/resource/time bound | Expected status/artifacts |
| --- | --- | --- | --- | --- |
| G-READY | Entire phase | Phase C passed; authority/retry/retention decisions reviewed | Frozen local runtime and existing roles | Phase C gate and this work item |
| G-CONTRACT | New typed boundaries | Exact fields, immutable snapshots, actor binding, scoped replay/conflict | No model/provider credentials | Unit and real-store tests |
| G-DURABLE | Schema, intent, wait, retry | Before/after-commit loss, independent process recovery, atomic race winner and useful progress | Local PostgreSQL and independent synthetic supplier | Real PG lane plus installed container |
| G-OBS | New state/error producers | Fixed safe event/code; no token/payload/SQL/private exception text | Synthetic sentinels and allowlisted fields | Producer/CLI tests and logs |
| G-FAST | Shared source/policy | All offline tests, lint/type/format/docs plus original regression scenarios | Project interpreter; no providers | Retained complete gate output |
| G-MEDIA | Runtime image rebuild regression | Existing LiveKit text/audio smoke and original M1 identity | Existing preserved local stack | Native RTC smoke, not browser playback |
| G-PACKAGE | Installed application boundary | Final code is imported from installed wheel outside source tree | Local built image | Module hashes and real consumer probe |

Retain receipts indefinitely within explicit finite lab admission bounds. Do not
introduce time-to-live (TTL) deletion, history pruning or an expired identity
becoming new work. An ambiguous external failure remains uncertain even after the
deadline. A deadline cannot prove an operation did not happen. A failed or
unavailable required setup, skipped scenario, zero-test runner or timeout cannot
pass.

## Results and handoff

Phase D is complete for P1-I11 through P1-I14. The first SQLite inquiry proof and
the live M1 application are preserved. New authority and continuation behavior
runs on explicit PostgreSQL v2 under the original task identity, with a separate
immutable case UUID. No supplier booking mutation or public cancellation API is
claimed by this phase.

### Observed final gates

| Observed gate | Command or mode | Result |
| --- | --- | --- |
| Offline checks | `make check` | 385 offline Python tests passed, with zero skips and no ResourceWarning; Ruff, structural and documentation checks passed |
| Typing | Normal mypy | 43 service and core files plus the strict process helper |
| Strict changed boundaries | Strict mypy with `follow-imports=silent` | The nine new authority, continuation, policy and observation boundary files passed |
| Formatting | `make format-check` | 98 Python files passed |
| Real PostgreSQL | `make postgres-check POSTGRES_REPORT=.local/validation/p1-phase-d/postgres-gate.json` | 116 actual local PostgreSQL tests passed with zero failures, errors or skips: 49 original cases, 17 v2 upgrade and index cases, 26 case authority cases and 24 lifecycle cases |
| Installed demo | `make phase-d-demo` | Passed using two separate disposable runtime-only containers with no shared application file; thirty-one installed core modules matched host hashes outside the source tree |
| LiveKit smoke | Final actual LiveKit smoke | Passed readiness and authentication, original M1 replay and conflict, named dispatch, ordinary and full UTF-8 text and real audio frame reception |
| Documentation | Documentation policy | 68 maintained files checked |
| Diagrams | Actual Mermaid syntax parsing | All 33 Design Mermaid diagrams passed, with a malformed negative fixture |
| Whitespace | Whitespace checks | Passed |
| Acceptance ledger | Complete acceptance ledger | Correctly incomplete (exit 2): BASE-01 and P1-01 through P1-05 pass, and 49 product release scenarios remain unimplemented |

Observation details:

- Imported legacy modules retain the existing broad type gate. This is not a
  claim of full-repository strict typing.
- Final PostgreSQL execution ran without concurrent container rebuilds. Finite
  database and lock budgets were unchanged.
- Versioned ACTIVE-v1-to-v2 migration passed interruption, actual child process
  loss at three checkpoints, replay and populated inquiry preservation. New
  immutable tables reject UPDATE, DELETE and TRUNCATE. Mutable state retains
  bounded progression only. Column, check, foreign key (FK), role and index drift
  fails closed. Four ordinary task-leading indexes support cap and history queries
  without redundant uniqueness. Completed source cutover receipts still preserve
  v2 progress.
- Case identity is a canonical UUID distinct from task and workflow identity.
  Creation, replay, revision and container restart preserve it. Database
  non-null, unique and distinct constraints and malformed-read tests pass. The
  current association is one case per original task. Future multi-workflow
  association remains explicit.
- Exact case, quote and confirmation validation rejects missing, altered, stale,
  expired or wrong-actor input before intent. Confirmed intent, stable effect and
  dispatch commit atomically. Existing receipt replay survives expiry without a
  new effect. Concurrent revision and commit have one protected winner. Reads
  require matching original confirmation and mandatory dispatch evidence.
- Direct confirmation and signal consumption share managed state and deadline
  checks, and atomically close waits and update continuation. Revision closes old
  waits, retains old unconsumed signal receipts and permits a fresh valid proposal
  to progress within the original deadline. Expired business work cannot be
  revived by a revision. Scope and owner negatives and normal useful progress
  pass.
- Wait and signal tests cover early and late receipt, semantic replay and
  conflict, unrelated callback, exact once-logical consumption,
  independent-process waiting and expiry, transaction rollback and concurrent
  consumers. No room or sleeping task retains a wait. No cleanup, TTL or pruning
  erases identity protection.
- Retry tests cover finite attempts and backoff, permanent rejection, exhaustion,
  deadlines, trusted positive no-dispatch evidence and ambiguous outcomes without
  automatic resend. Independent worker loss after supplier success reconciles the
  original effect. The deadline is checked after lookup and before dispatch.
  Known results are not erased by expiry. Legacy start, recover and finish cannot
  bypass managed policy.
- Authenticated service, async and telemetry tests verify actor derivation before
  port access, no body scope override, exact parsing, finite labels and private
  registries, real counts and durations, secret-safe errors and exporter and
  logger failure containment. Cancelled callers retain I/O capacity until the
  actual commit thread finishes. Later valid reads still progress. These are
  application boundaries, not identity and access management (IAM) or independent
  human-presence attestation.
- In the Phase D demo, pending waits and no intent were observed before the first
  container exited. The second consumed the exact early signal once, replayed the
  same intent and event and rejected another expired wait. Distinct case
  identity, positive metric samples, safe producer events, an unchanged booking
  and the historical cutover receipt were verified. Passing evidence was written
  only after owned schema and container cleanup. No live M1 database or existing
  volume was reset.
- The original M1 task ID was unchanged. Browser playback, model and human
  consent evidence is not inferred from native real-time communication (RTC)
  traffic or the synthetic demo clock.
- Remote Linux CI is wired but not claimed executed.
- Phase task completion and specific migration, authority, wait and policy
  evidence do not claim supplier apply, cancellation, distributed leases or
  complete release.

### Review corrections

Review corrected commit and control deadline bypass, stale-wait revision progress,
missing committed evidence, stored-payload workflow binding, pre-dispatch deadline
checks, conditional write counts, case and workflow identity separation and
wait-driven commit logging. Demo review tightened dormant-state assertions, exact
error codes, positive metric samples and post-cleanup reporting. An outdated
stale-wait test was updated to assert the new atomic invalidation contract and
retained receipts. A concurrent image-build run hit bounded database connection
timeouts. Its failed output is retained, and the complete final database gate
passed serially without weakening timeouts or converting failures to skips.

### Evidence and next step

Evidence lives under `.local/validation/p1-phase-d`:

| Artifact | Content |
| --- | --- |
| `fast.txt` | Fast lane output |
| `format.txt` | Format check output |
| `strict-boundaries.txt` | Strict boundary type check output |
| `postgres.txt` | Real PostgreSQL lane output |
| `postgres-gate.json` | Real PostgreSQL gate report |
| `start.json` | Local stack start result |
| `container-demo.json` | Installed container demo result |
| `demo-command.txt` | Demo command output |
| `smoke.json` | LiveKit smoke result |
| `deep.json` | Complete acceptance ledger result |
| `documentation.json` | Documentation policy result |
| `mermaid.json` | Mermaid parse results |
| `source-manifest.json` | Working-tree file manifest |
| `phase-gate.json` | Phase gate result |

Earlier diagnostic attempts remain separate. Machine evidence identifies the
working-tree files. Documentation contains no private repository or source
identifiers. AI assisted implementation and independent case, lifecycle, schema,
service and operational reviews.

Next: P1 Phase E (P1-E), tasks P1-I15 through P1-I18. Version the proposal and
intent to bind the specific expected supplier booking revision before actual
apply. Add mutation capability and reconciliation, cancellation, and atomic
completion and outbox behavior. Never infer confirmed supplier revision later from
mutable booking state. Business UI and media, leases, delivery, full product
traces, the SDK consumer and platform matrix, and selected real inference remain
later explicit gates.
