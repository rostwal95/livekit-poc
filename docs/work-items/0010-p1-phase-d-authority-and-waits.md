# P1 Phase D exact consent and durable continuation

Status: Completed
Last reviewed: 9 November 2026

## Behavior and scope

After the completed Phase C gate, implement P1-I11 through P1-I14: canonical
revisioned case snapshots, exact quotes/confirmation and atomic action-intent
commitment, durable waits/signals and finite retry/deadline policy. Rich lifecycle
uses PostgreSQL; retain the existing SQLite inquiry proof and live M1 application.
Actual fake booking mutation, cancellation, leases and event delivery follow later.

| Criterion | Given | When | Then: safety | Then: useful progress | Test/mode and evidence |
| --- | --- | --- | --- | --- | --- |
| P1-06/07 contribution | Current case/quote and authenticated owner | Commit exact explicit confirmation | Missing/changed/stale/expired/wrong-actor input creates no intent/dispatch | Valid confirmation commits one immutable intent and stable dispatch event | Real PostgreSQL validation/race/replay tests |
| P1-10/11 contribution | Persisted wait, typed signal and absolute deadline | Signal before/after wait or restart | Scoped changed replay conflicts; unrelated/expired signal never grants authority | Exact current signal consumes once under the original task | Independent process and real local container evidence |
| P1-12 contribution | Admitted inquiry and finite retry policy | Transient/permanent/ambiguous error or deadline | No infinite retry or unsafe ambiguous resend; budget remains finite | Eligible transient retry progresses with the original effect | Fake clock, actual worker and independent supplier ledger |
| Retention | Persisted requests, signals, confirmations and effects | Expiry, overload or repeated command | Identity protection is retained; no cleanup/recreation path | Existing replay/read remains available at capacity | Explicit no-prune contract and late replay tests |
| Schema upgrade | Populated ACTIVE PostgreSQL v1 | Explicit owner-only v2 migration or interruption | All v1 inquiry data/receipt survives; serving never performs DDL | Repeated upgrade and old/new operations progress | Transaction rollback/process loss, role negatives and container |

## Interfaces and ownership

Keep the original task/execution identity. Case authority owns current request
revision, owner, immutable quote/confirmation and committed intent. P1 continuation
control owns waits, signal inbox and eligible inquiry attempts beside the existing
inquiry tables; it is not another recovering queue. The inquiry result and overall
continuation disposition remain distinct. No schema or runtime dependency upgrade
is bundled into this feature slice.

Case updates and commitment serialize under the same short authority transaction.
A revision that commits first invalidates stale confirmation; an intent that commits
first cannot be rewritten by a later revision. Confirmation consumption and intent/
dispatch insertion share one transaction. Check expiry after acquiring locks.
The trusted token service supplies actor/scope; quote issuance is a trusted fixture
producer operation, separate from the user's explicit confirmation command.

## Failure cases and validation

| Gate | Applicability | Required assertions | Prerequisite/bound | Evidence |
| --- | --- | --- | --- | --- |
| G-READY | Entire phase | Phase C passed; authority/retry/retention decisions reviewed | Frozen local runtime and existing roles | Phase C gate and this work item |
| G-CONTRACT | New typed boundaries | Exact fields, immutable snapshots, actor binding, scoped replay/conflict | No model/provider credentials | Unit and real-store tests |
| G-DURABLE | Schema, intent, wait, retry | Before/after-commit loss, independent process recovery, atomic race winner and useful progress | Local PostgreSQL and independent synthetic supplier | Real PG lane plus installed container |
| G-OBS | New state/error producers | Fixed safe event/code; no token/payload/SQL/private exception text | Synthetic sentinels and allowlisted fields | Producer/CLI tests and logs |
| G-FAST | Shared source/policy | All offline tests, lint/type/format/docs plus original regression scenarios | Project interpreter; no providers | Retained complete gate output |
| G-MEDIA | Runtime image rebuild regression | Existing LiveKit text/audio smoke and original M1 identity | Existing preserved local stack | Native RTC smoke, not browser playback |
| G-PACKAGE | Installed application boundary | Final code is imported from installed wheel outside source tree | Local built image | Module hashes and real consumer probe |

Retain receipts indefinitely within explicit finite lab admission bounds. Do not
introduce TTL deletion, history pruning or an expired identity becoming new work.
An ambiguous external failure remains uncertain even after deadline; a deadline
cannot prove an operation did not happen. A failed or unavailable required setup,
skipped scenario, zero-test runner or timeout cannot pass.

## Results and handoff

Phase D is complete for P1-I11 through P1-I14. The first SQLite inquiry proof
and live M1 application are preserved. New authority and continuation behavior
runs on explicit PostgreSQL v2 under the original task identity, with a separate
immutable case UUID. No supplier booking mutation or public cancellation API is
claimed by this phase.

Observed final gates:

- make check passed 385 offline Python tests, zero skips and no ResourceWarning.
  Ruff, structural and documentation checks passed; normal mypy covered 43
  service/core files plus the strict process helper. The nine new authority,
  continuation, policy and observation boundary files passed strict mypy with
  follow-imports=silent. Imported legacy modules retain the existing broad type
  gate; this is not a claim of full-repository strict typing. make format-check
  passed for 98 Python files.
- make postgres-check POSTGRES_REPORT=.local/validation/p1-phase-d/postgres-gate.json
  passed 116 actual local PostgreSQL tests with zero failures/errors/skips:
  49 original cases, 17 v2 upgrade/index cases, 26 case authority cases and 24
  lifecycle cases. Final execution ran without concurrent container rebuilds;
  finite database/lock budgets were unchanged.
- Versioned ACTIVE-v1-to-v2 migration passed interruption, actual child process
  loss at three checkpoints, replay and populated inquiry preservation. New
  immutable tables reject UPDATE/DELETE/TRUNCATE; mutable state retains bounded
  progression only. Column/check/FK/role/index drift fails closed. Four ordinary
  task-leading indexes support cap/history queries without redundant uniqueness.
  Completed source cutover receipts still preserve v2 progress.
- Case identity is a canonical UUID distinct from task/workflow identity. Creation,
  replay, revision and container restart preserve it; database non-null/unique/
  distinct constraints and malformed-read tests pass. The current association is
  one case per original task; future multi-workflow association remains explicit.
- Exact case/quote/confirmation validation rejects missing/altered/stale/expired/
  wrong-actor input before intent. Confirmed intent, stable effect and dispatch
  commit atomically. Existing receipt replay survives expiry without a new effect.
  Concurrent revision/commit has one protected winner. Reads require matching
  original confirmation and mandatory dispatch evidence.
- Direct confirmation and signal consumption share managed state/deadline checks
  and atomically close waits/update continuation. Revision closes old waits,
  retains old unconsumed signal receipts and permits a fresh valid proposal to
  progress within the original deadline. Expired business work cannot be revived
  by a revision. Scope/owner negatives and normal useful progress pass.
- Wait/signal tests cover early/late receipt, semantic replay/conflict, unrelated
  callback, exact once-logical consumption, independent-process waiting and
  expiry, transaction rollback and concurrent consumers. No room or sleeping task
  retains a wait. No cleanup/TTL/pruning erases identity protection.
- Retry tests cover finite attempts/backoff, permanent rejection, exhaustion,
  deadlines, trusted positive no-dispatch evidence and ambiguous outcomes without
  automatic resend. Independent worker loss after supplier success reconciles the
  original effect. Deadline is checked after lookup before dispatch; known results
  are not erased by expiry. Legacy start/recover/finish cannot bypass managed policy.
- Authenticated service/async/telemetry tests verify actor derivation before port
  access, no body scope override, exact parsing, finite labels/private registries,
  real counts/durations, secret-safe errors and exporter/logger failure containment.
  Cancelled callers retain I/O capacity until the actual commit thread finishes;
  later valid reads still progress. These are application boundaries, not IAM or
  independent human-presence attestation.
- make phase-d-demo passed using two separate disposable runtime-only containers
  with no shared application file. Pending waits/no intent were observed before
  the first exited. The second consumed the exact early signal once, replayed the
  same intent/event and rejected another expired wait. Thirty-one installed core
  modules matched host hashes outside the source tree. Distinct case identity,
  positive metric samples, safe producer events, unchanged booking and historical
  cutover receipt were verified. Passing evidence was written only after owned
  schema/container cleanup. No live M1 database or existing volume was reset.
- Final actual LiveKit smoke passed readiness/authentication, original M1 replay/
  conflict, named dispatch, ordinary/full UTF-8 text and real audio frame reception.
  The original M1 task ID was unchanged. Browser playback/model/human consent
  evidence is not inferred from native RTC traffic or the synthetic demo clock.
- Documentation policy checked 68 maintained files. All 33 Design Mermaid diagrams
  passed actual syntax parsing with a malformed negative fixture. Whitespace
  checks passed. Remote Linux CI is wired but not claimed executed.
- Complete acceptance ledger remains correctly incomplete, exit 2: BASE-01 and
  P1-01 through P1-05 pass; 49 product release scenarios remain unimplemented.
  Phase task completion and specific migration/authority/wait/policy evidence do
  not claim supplier apply, cancellation, distributed leases or complete release.

Review corrected commit/control deadline bypass, stale-wait revision progress,
missing committed evidence, stored-payload workflow binding, pre-dispatch deadline
checks, conditional write counts, case/workflow identity separation and wait-driven
commit logging. Demo review tightened dormant-state assertions, exact error codes,
positive metric samples and post-cleanup reporting. An outdated stale-wait test
was updated to assert the new atomic invalidation contract and retained receipts.
A concurrent image-build run hit bounded database connection timeouts; its failed
output is retained, and the complete final database gate passed serially without
weakening timeouts or converting failures to skips.

Evidence lives under .local/validation/p1-phase-d: fast.txt, format.txt,
strict-boundaries.txt, postgres.txt, postgres-gate.json, start.json,
container-demo.json, demo-command.txt, smoke.json, deep.json, documentation.json,
mermaid.json, source-manifest.json and phase-gate.json. Earlier diagnostic attempts
remain separate. Machine evidence identifies the working-tree files; documentation
contains no private repository/source identifiers. AI assisted implementation and
independent case/lifecycle/schema/service/operational reviews.

Next: P1-E, P1-I15 through P1-I18: version the proposal/intent to bind the specific
expected supplier booking revision before actual apply; add mutation capability/
reconciliation, cancellation and atomic completion/outbox behavior. Never infer
confirmed supplier revision later from mutable booking state. Business UI/media,
leases, delivery, full product traces, SDK consumer/platform matrix and selected
real inference remain later explicit gates.
