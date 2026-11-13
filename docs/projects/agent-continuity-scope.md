# Agent Continuity Lab scope

Status: Active
Last reviewed: 10 November 2026

## Overview

Agent Continuity Lab provides a small Python API for durable business work started
by a realtime agent. The reference application uses one synthetic booking-change
workflow: investigate availability and price, obtain a separate confirmation, and
apply the confirmed change through a fake supplier. Accepted work can outlive the
LiveKit session and the process that accepted it.

The [portfolio scope](../portfolio-scope.md) defines shared runtime, identifiers
and release policy. The [validation plan](../validation-plan.md) defines evidence.
This charter is authoritative for P1 behavior and acceptance IDs.

## Implementation status

P1 V1 is implemented and locally qualified with explicitly selected provider_real
v2. All twenty acceptance rows have retained passing reports and an independently
verified release index. The original SQLite M1 investigation contract remains
preserved; the PostgreSQL v4 path implements exact case/quote/confirmation,
continuation, supplier-effect reconciliation, cancellation, completion delivery,
leases and bounded worker deployment. Native/controller consumers share that
single authority through the standalone typed Python package.

Current real PostgreSQL, full H2, registered scripted/reliability/provider-media,
installed host/Linux artifact and shared-quality gates passed. The
[release work item](../work-items/0019-p1-phase-h-release-qualification.md) owns
exact current evidence; earlier phase/H1 snapshots retain their historical scope.
The independent local_real profile remains unqualified. P2/P3 and the integrated
three-project release remain planned.

### Current local P1 qualification

P1 V1 is implemented and locally qualified with selected provider_real v2.
The final 20-case index, current P1-18/P1-14/P1-20, full H2, PostgreSQL, installed
host/Linux artifacts and shared quality gates passed with independent reviews.
Historical checkpoints retain their original scope. local_real remains unqualified;
complete P2/P3 acceptance remains pending, and hosted CI/publication are outside this local POC.

## Ownership and dependencies

| Owner | Responsibility |
| --- | --- |
| LiveKit session and its adapter | Conversation, tool invocation, speech interruption, and collecting explicit user input |
| Application case service | Current case revision, verified actor context, and the exact proposal presented for confirmation |
| Continuity package | Durable acceptance, workflow transitions, attempts, waits, signals, cancellation intent, effect records, and completion events |
| Supplier adapter | Explicit idempotency and outcome-lookup capabilities for an external operation |
| Notification or result adapter | Delivery attempts for committed events using stable event identities |

The package can run without either other portfolio project. It depends on narrow
store, clock, supplier, and event-sink interfaces. A CLI and a local event collector
are sufficient standalone adapters. Project 2 can consume completion events, and
Project 3 can use a narrow durable-execution interface without owning this
workflow's state machine.

The booking API wraps the shared `TaskExecutionPort` primitive defined in the
root design. That primitive supports a small allowlist of typed handlers,
including P3 specialist work, without exposing an arbitrary workflow engine.
Booking execution consumes intents committed by `CaseAuthorityPort`; it does not
create a second owner of case revision or mutation authority. The case authority
atomically records its accepted intent and dispatch event, which execution can
consume under a stable identity. The standalone adapter supplies that same small
authority locally.

The package accepts a trusted application scope and actor context; it does not
turn a caller-supplied scope label into authentication. The reference adapter must
derive that context from the shared synthetic account mechanism. Scope-qualified
reads and writes must reject access from a different account or tenant.

## Required V1 behavior

1. **Durable intake.** Commit an accepted request before acknowledging it. Scope,
   operation identity, idempotency key, and canonical payload determine replay
   behavior. An identical replay returns the original workflow; a conflicting
   payload under the same identity produces an explicit conflict.
2. **Explicit execution.** Use persisted steps and transitions. Keep workflow
   state, execution attempts, and supplier outcomes distinguishable. Ordinary
   Python coroutines are not automatically checkpointed or resumed.
3. **Investigation and confirmation.** Investigate the requested dates, store the
   supplier proposal, and wait durably for an explicit confirmation of that exact
   proposal. Investigation consent never grants permission to apply a change.
4. **Bounded execution.** Enforce configured active-work and pending-work limits,
   deadlines, retry counts, and backoff. New work rejected for capacity is not
   acknowledged as accepted. Accepted work remains inspectable during overload.
5. **Persisted waiting.** Store deadlines and signals so a callback, confirmation,
   or timeout can advance work after all original processes have exited. No
   running room or sleeping coroutine is required to retain a waiting workflow.
6. **Recovery.** Recover pending or eligible interrupted work using the same
   durable identities. A process/container restart with the same database volume
   preserves accepted requests, steps, and known supplier outcomes.
7. **External-effect reconciliation.** Persist the intended effect before issuing
   it. Reuse its stable supplier key and look up an ambiguous result when the
   supplier supports that contract. Record an uncertain outcome when evidence is
   insufficient for a safe retry or a definitive failure.
8. **Cancellation.** Record a cancellation request separately from its outcome.
   Cancellation before the mutation commitment point prevents that mutation;
   afterward it is best effort under the supplier contract. Interrupting speech
   alone does not cancel accepted business work.
9. **Multi-worker coordination.** Add a PostgreSQL backend and prove exclusive
   claims, lease expiry, and rejection of stale writes with independent workers.
   Keep database transactions short and keep external calls outside locks.
10. **Observable completion.** Commit result state and an event intent atomically.
    Deliver events at least once under stable IDs, with bounded retry and visible
    delivery failure. A delivered notification is distinct from workflow success.

SQLite is the initial single-host backend. PostgreSQL is required before the V1
multi-worker release gate can pass. A versioned additive migration or new-table design must preserve readable
M1 requests whose current schema permits only the `queued` state. Make that schema
decision before introducing worker states in P1 A. At PLAN-02 explicitly retain
SQLite M1 intake/migration and the first single-worker inquiry/recovery subset.
After the PLAN-03 SQLite crash demonstration, introduce the PostgreSQL single-worker
adapter and shared store-contract checks before expanding the full lifecycle.
PostgreSQL is the full V1 execution backend; do not implicitly implement two full
schedulers. Later PLAN-08 work completes multi-worker coordination, migration and
supported-subset parity. Unsupported SQLite operations fail explicitly. Table
count and physical schema are implementation decisions justified by these behaviors.

All database work must respect the asynchronous API boundary. Using `async def`
does not make blocking SQLite calls nonblocking; use a documented offload boundary
or an appropriate async implementation, with bounded concurrency and cleanup.

## Public contracts

These are proposed application-library operations, not existing LiveKit APIs.
Concrete current Python ports are documented in the
[case/continuation guide](../case-and-continuation.md); the table below retains
the V1 behavior contract without claiming every facade is importable. Finalize
reusable package exports at the installed-consumer checkpoint.

| Operation | Required behavior |
| --- | --- |
| `submit_change(scope, request, idempotency_key)` | Return the stable workflow identity and whether this call created it, only after commit |
| `get(scope, workflow_id)` | Return the current snapshot, revision, waiting reason, latest outcome, and cancellation state |
| `signal(scope, workflow_id, event_id, payload)` | Durably accept a typed callback or confirmation, deduplicating a scoped event identity |
| `cancel(scope, workflow_id, command_id)` | Return recorded cancellation intent and its current disposition; never claim remote cancellation merely from local task cancellation |
| `events(scope, workflow_id, after_cursor, limit)` | Return bounded, ordered local history for diagnosis and resumption |

Typed requests and results must avoid unstructured status dictionaries at the
public boundary. Errors distinguish invalid input, scope denial/not-found under
the chosen disclosure policy, idempotency conflict, stale revision, expired quote,
invalid confirmation, invalid transition, capacity rejection, and unavailable
storage. An uncertain supplier outcome is a persisted business result requiring
reconciliation, rather than an instruction to retry blindly.

Submission, signal, and cancellation IDs must survive caller retries. Reusing an
ID with different canonical content is a conflict. Signals arriving before the
workflow reaches its matching wait are retained and correlated; unrelated signals
cannot advance the workflow. Persisted business timers use wall-clock deadlines;
test clocks make expiry behavior deterministic without long real sleeps.

Before cleanup is introduced, define replay horizons and retained idempotency,
confirmation and effect tombstones. Business deadlines and diagnostic-history
pruning do not erase the evidence needed to reject a duplicate or reconcile an
uncertain operation. Test a late retry after pruning; an expired identity receives
a documented rejection rather than silently creating new work.

## Correctness and failure boundaries

The application presents a persisted proposal containing at least the booking,
requested dates, quote identity, additional amount and currency, expiry, and case
revision. The confirmed snapshot is immutable. An LLM's statement that the user
agreed cannot construct a valid confirmation by itself.

Before accepting a mutation intent, validate the actor's authority, current case
revision, quote expiry, cancellation status, and matching confirmation snapshot in
the same protected transaction that records that intent. This transaction is the
mutation commitment point. A preceding cancellation prevents commitment; a later
cancellation is an attempt to stop already-committed work and cannot promise
reversal. A user revision after commitment creates a new request/reconciliation
path rather than silently rewriting the committed operation.

The worker should avoid dispatching committed work it can still safely cancel,
but there remains an external-call boundary. Fencing a database write does not
stop an expired worker from calling a supplier. External safety requires that
supplier's idempotency, status lookup, or participating fencing behavior. The
package does not promise unconditional exactly-once effects.

## Acceptance matrix

P1-01 through P1-05 retain executable SQLite acceptance/recovery evidence. All
twenty rows now have registered runners, with retained passing runs for P1-01
through P1-19. P1 V1 is qualified for the local POC using provider_real v2. local_real remains unqualified and complete P2/P3 acceptance remains pending.
Registration does not establish execution success; every row remains a release
requirement with its applicable backend/integration evidence. Deterministic supplier tests use the local fake
supplier, controlled clocks/barriers, and failpoints; no external model or carrier
keys are needed. Rows involving workers use independent processes, not merely new
objects in one process.

| ID | Scenario | Required assertion |
| --- | --- | --- |
| P1-01 | Accept, acknowledge, terminate intake process, reopen database | The same scoped workflow and payload remain readable |
| P1-02 | Concurrent identical submissions, including a response lost after commit | One logical workflow; replay returns its original identity |
| P1-03 | Same scoped key with altered payload; same key in another scope | Conflict within the original scope; independent identity in the other scope |
| P1-04 | Independent worker executes an accepted investigation | Supplier inquiry result is persisted; booking is unchanged |
| P1-05 | Crash after persisted supplier inquiry success but before local acknowledgement | Recovery discovers the original inquiry; one logical inquiry effect under the supplier contract |
| P1-06 | Valid quote, matching explicit confirmation, and apply operation | Exactly the confirmed fake booking revision is applied under one stable effect key |
| P1-07 | Missing confirmation, changed dates/amount, stale revision, or expired quote | Mutation intent is not committed and supplier apply is not invoked |
| P1-08 | Crash after fake booking mutation but before local acknowledgement | A new worker reconciles the original effect and records success without an incorrect duplicate mutation |
| P1-09 | Supplier has neither safe deduplication nor reliable outcome lookup after ambiguous dispatch | Workflow records uncertainty; no automatic unsafe resend |
| P1-10 | Waiting workflow survives full process/container restart; signal arrives before or after wait | Matching signal advances it once logically; persisted deadline remains effective |
| P1-11 | Replayed callback, altered replay, and unrelated callback | Same payload is deduplicated; altered payload conflicts; unrelated signal cannot advance work |
| P1-12 | Transient error, permanent rejection, retry exhaustion, and expired deadline | Bounded attempts and correct final failed/uncertain classification; no infinite loop |
| P1-13 | Cancel before commitment and race cancellation with confirmation | The protected transaction establishes one documented winner; cancelled-before-commit work causes no mutation |
| P1-14 | Cancel after commitment or interrupt the agent's speech | No false reversal claim; business work follows the explicit cancellation contract |
| P1-15 | Two PostgreSQL workers claim work; old worker resumes after lease expiry | Current claim wins; old attempt cannot commit a stale database update |
| P1-16 | Commit completion, crash before event delivery, then replay outbox | Completion event survives; delivery is at least once with one stable logical event ID |
| P1-17 | Different account/tenant inspects, signals, or cancels a workflow | Access is rejected without cross-scope state mutation or exposure |
| P1-18 | Saturate the configured pending/active limits and shut down | Explicit pre-acceptance rejection, bounded resources, visible accepted work, and no orphan local tasks |
| P1-19 | Migrate an M1 database with existing queued requests | Original identities and canonical payloads survive; migration failure does not silently destroy intake state |
| P1-20 | Real LiveKit browser voice session under slow persistence and supplier calls, followed by session end | Work remains inspectable and completes independently; separate mutation confirmation is preserved; event-loop responsiveness is measured and supplier completion is not awaited on the conversational path |

For P1-15, also exercise a stale worker attempting an external call. The fake
supplier's participating contract must prevent an incorrect duplicate effect,
or the test must show the operation becoming uncertain. A passing database-fence
test alone is insufficient evidence of supplier safety.

## Development checkpoints

These charter milestones are release-oriented groupings, not the granular
implementation Phase A through H labels. The
[P1 implementation plan](../implementation/p1-agent-continuity.md) owns current
phase/task status. F/G, H1 inquiry, H2 restart/slow-dependency/saturation/shutdown
and P1-I26 host/Linux artifact/API/genuine-consumer gates passed. P1 V1 is qualified for the local POC using provider_real v2. local_real remains unqualified and complete P2/P3 acceptance remains pending.;
remote CI/publication do not block this POC.

| Checkpoint | Deliverable and gate |
| --- | --- |
| Existing M1 | Retain CLI investigation intake, scoped deduplication, and conflict tests; no new completion claim |
| P1 A | Preserve M1 and declare the SQLite compatibility subset, then add one independent SQLite inquiry worker and one crash window; pass P1-04/P1-05 with investigation permission, followed by the early PostgreSQL adapter before lifecycle expansion |
| P1 B | Persisted steps, waits/signals, retry/deadline policy, separate quote confirmation and mutation commitment; pass relevant P1-06 through P1-14 |
| P1 C | PostgreSQL workers, stale-write/effect handling, migration/parity hardening and durable result events; pass P1-15 through P1-19 |
| P1 D | Real LiveKit tool adapter, measured responsiveness, standalone local demonstration, and complete release evidence |

The first checkpoint does not modify bookings. The later mutation crash demo
requires the separate explicit confirmation flow to exist first. This preserves
the permission model of the current `BookingChange` starter.

## Release gates

Retain the native standard-library M1 path. The shared `offline`, `lab`, and `live`
profiles are defined centrally; all mandatory failure tests and the standalone
workflow demonstration run with local persistence and fake suppliers. Container
restart tests reuse named volumes. Destroying a volume is an explicit reset and
is outside the restart guarantee.

Local-ready V1 requires P1-20's actual browser/media lifecycle checks against the
local LiveKit server with scripted inference/audio fixtures. Portfolio-ready V1
additionally repeats the relevant interaction with configured real speech/model
providers or validated local inference. Scripted fixtures alone do not establish
real model behavior. Cloud hosting and Cloud simulations are optional validation
paths.

Release requires all P1 acceptance rows, shared code-quality and integration
checks, a minimal API example, an inspectable failure trace, a reproducible crash
demo, a benchmark artifact with workload and versions, and documented limitations.
When a real second consumer establishes the reusable package boundary, build its
wheel and run the minimal example from an isolated installed consumer. No sibling
source paths or undeclared runtime services may be required. Repeat at release.
Release evidence must say which supplier contract, database backend, SDK version,
model configuration, and run profile were exercised. Current M1 code is not
evidence that these V1 requirements have been met.

### Coding agent contract

The project's onboarding directory, `projects/agent-continuity`, must expose the
required `AGENTS.md`, `Design.md`, and `README.md` documents described in the
portfolio scope, without moving the existing M1 package merely for layout. They must
identify authoritative contracts, state ownership, supported commands, safe local
fixtures, and the tests that protect each invariant. Proposed APIs in this scope
must be distinguishable from importable code and currently runnable commands.

The code-level harness must map P1 acceptance IDs to executable scenarios and
produce machine-readable outcomes plus useful failure artifacts. It must provide
typed request/result fixtures, a controllable clock, worker process control,
explicit crash barriers, persisted supplier state, and inspection of effects and
workflow history. Each command and required environment variable must be visible
in the documented entry point; no hidden setup or undisclosed paid-service call
is permitted. Missing scenarios remain pending rather than reporting success.

P1's standalone harness must run without Project 2 or Project 3. The integrated
harness may add those adapters, but cannot replace the standalone contract tests.
The real-voice scenarios must be labelled separately from deterministic fake-model
scenarios. This documentation and harness contract is an additional V1 release
requirement, alongside all P1-01 through P1-20 behavior checks.

## Deferred scope

General-purpose DAG execution, arbitrary coroutine persistence, a visual workflow
designer, production supplier integrations, payments, automatic compensation for
real bookings, multi-region failover, host/disk disaster recovery, and managed
autoscaling are outside V1. Broad authentication platforms and sophisticated
schedulers are also outside scope; the synthetic application still enforces the
required scope and confirmation boundaries. Add infrastructure only when an
accepted requirement and failing test justify it.

## References

Use LiveKit's existing sessions, tools, and conversational workflow constructs.
This package owns application business-work recovery. Native AgentSession,
AgentTask/TaskGroup, tools, handoffs and job lifecycle own conversational control;
reuse those surfaces instead of duplicating them. They do not establish the
cross-process business-recovery guarantee required here. See
[workflow constructs](https://docs.livekit.io/agents/logic/workflows/) and
[server lifecycle](https://docs.livekit.io/agents/server/lifecycle/).
