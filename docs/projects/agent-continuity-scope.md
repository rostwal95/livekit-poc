# Agent Continuity Lab scope

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Define the required V1 behavior and stable acceptance IDs for P1, Agent Continuity Lab |
| Audience | Engineers and coding agents who change P1 or check what its release requires |
| Scope | P1 behavior, contracts, acceptance matrix and release gates; excludes shared portfolio policy and evidence rules |
| Owns | P1 requirements and stable acceptance IDs |
| Related | [Portfolio scope](../portfolio-scope.md) · [Validation plan](../validation-plan.md) · [P1 task plan](../implementation/p1-agent-continuity.md) · [P1 README](../../projects/agent-continuity/README.md) · [P1 design](../../projects/agent-continuity/Design.md) |

## Overview

This charter defines the required V1 behavior and the stable acceptance IDs for
P1, Agent Continuity Lab. It is for engineers and coding agents who change P1 or
need to check what its release requires. This charter is authoritative for P1
behavior and acceptance IDs. The [portfolio scope](../portfolio-scope.md) defines
the shared runtime, identifiers and release policy. The
[validation plan](../validation-plan.md) defines what counts as evidence.

### What P1 provides

Agent Continuity Lab provides a small Python API for durable business work started
by a realtime agent. Accepted work can outlive the LiveKit session and the process
that accepted it.

The reference application uses one synthetic booking-change workflow:

1. Investigate availability and price.
2. Obtain a separate confirmation.
3. Apply the confirmed change through a fake supplier.

### Terms used in this charter

| Term | Meaning |
| --- | --- |
| M1 | The original SQLite confirmed-investigation intake; its current schema permits only the `queued` state |
| PLAN-02, PLAN-03 and PLAN-08 | Work packages in the [build plan](../build-plan.md) |
| Phase A through Phase H | The granular implementation phases in the [P1 implementation plan](../implementation/p1-agent-continuity.md) |
| H1 | The inquiry workload slice of Phase H |
| H2 | The restart, slow-dependency, saturation and shutdown slice of Phase H |
| Charter checkpoints P1 A through P1 D | Release-oriented groupings under Development checkpoints; different from the granular phases |
| Implementation task IDs | IDs such as P1-I26 that identify work items in that plan; not acceptance IDs such as P1-20 |
| provider_real v2 | The explicitly selected provider inference profile used for the P1 qualification |
| local_real | The separate local inference profile |

## Implementation status

P1 V1 is implemented and locally qualified with the explicitly selected
provider_real v2 profile. All twenty acceptance rows have retained passing reports
and an independently verified release index.

| Capability | Status | Evidence |
| --- | --- | --- |
| V1 behavior and all twenty acceptance rows with the selected provider_real v2 profile | Qualified | [Release work item](../work-items/0019-p1-phase-h-release-qualification.md) |
| Leases and bounded worker deployment (Phase F gate) | Qualified | [Phase F work item](../work-items/0012-p1-phase-f-leases-and-deployment.md) |
| Conversation, visible continuity and traces (Phase G gate) | Qualified | [Phase G work item](../work-items/0013-p1-phase-g-conversation-and-showcase.md) |
| Declared inquiry workload (H1 gate) | Qualified | [H1 work item](../work-items/0014-p1-phase-h-workload-baseline.md) |
| Restart, slow-dependency, saturation and shutdown (H2 gate) | Qualified | [H2 work item](../work-items/0015-p1-reliability-workloads.md) |
| Host/Linux artifact, API and genuine-consumer gates (P1-I26) | Qualified | [Standalone package work item](../work-items/0016-p1-standalone-package.md) |
| Independent local_real profile | Not qualified | [Local-real operations guide](../local-real-inference.md) |
| Integrated three-project release | Planned | [Portfolio scope](../portfolio-scope.md) |

### Implemented behavior

- The original SQLite M1 investigation contract remains preserved.
- The PostgreSQL v4/v5 path implements exact case, quote and confirmation handling,
  continuation, supplier-effect reconciliation, cancellation, completion delivery,
  leases and bounded worker deployment. The explicit v5 upgrade adds persisted
  mutation retry due time.
- Native and controller consumers share that single authority through the
  standalone typed Python package.

### Qualification evidence

The final 20-case index, the then-current P1-18, P1-14 and P1-20 runs, full H2, real
PostgreSQL, installed host/Linux artifacts and shared quality gates passed with
independent reviews. The registered scripted, reliability and provider-media gates
also passed.

The [release work item](../work-items/0019-p1-phase-h-release-qualification.md)
owns that release evidence. The later
[v5 requalification](../work-items/0047-open-findings-schema-upgrades-and-landing.md)
passed BASE-01 and P1-01 through P1-19. Its fresh P1-20 provider rerun remains open
with the approved certificate bundle prerequisite. Earlier passing reports retain
their original source and profile scope.

### Remaining work and limits

- The independent local_real profile remains unqualified.
- P2 and P3 are partially implemented; their complete acceptance and the
  integrated three-project release remain pending.
- Hosted continuous integration (CI) and publication are outside this local proof
  of concept (POC).

## Ownership and dependencies

### Owners

| Owner | Responsibility |
| --- | --- |
| LiveKit session and its adapter | Conversation, tool invocation, speech interruption, and collecting explicit user input |
| Application case service | Current case revision, verified actor context, and the exact proposal presented for confirmation |
| Continuity package | Durable acceptance, workflow transitions, attempts, waits, signals, cancellation intent, effect records, and completion events |
| Supplier adapter | Explicit idempotency and outcome-lookup capabilities for an external operation |
| Notification or result adapter | Delivery attempts for committed events using stable event identities |

### Standalone and integrated use

The package can run without either of the other portfolio projects. It depends on
narrow store, clock, supplier and event-sink interfaces. A command-line interface
(CLI) and a local event collector are sufficient standalone adapters.

| Dependency | Standalone use | Integrated use |
| --- | --- | --- |
| Project 2 | Not required | Can consume completion events |
| Project 3 | Not required | Can use a narrow durable-execution interface without owning this workflow's state machine |

### Execution and case authority

The booking API wraps the shared `TaskExecutionPort` primitive defined in the
[root design](../../Design.md). That primitive supports a small allowlist of typed
handlers, including P3 specialist work, without exposing an arbitrary workflow
engine.

Booking execution consumes intents committed by `CaseAuthorityPort`. It does not
create a second owner of case revision or mutation authority. The case authority
atomically records its accepted intent and dispatch event, which execution can
consume under a stable identity. The standalone adapter supplies that same small
authority locally.

### Trusted scope and actor context

The package accepts a trusted application scope and actor context. It does not turn
a caller-supplied scope label into authentication. The reference adapter must derive
that context from the shared synthetic account mechanism. Scope-qualified reads and
writes must reject access from a different account or tenant.

## Required V1 behavior

1. **Durable intake.** Commit an accepted request before acknowledging it. Scope,
   operation identity, idempotency key and canonical payload determine replay
   behavior. An identical replay returns the original workflow. A conflicting
   payload under the same identity produces an explicit conflict.
2. **Explicit execution.** Use persisted steps and transitions. Keep workflow
   state, execution attempts and supplier outcomes distinguishable. Ordinary
   Python coroutines are not automatically checkpointed or resumed.
3. **Investigation and confirmation.** Investigate the requested dates, store the
   supplier proposal, and wait durably for an explicit confirmation of that exact
   proposal. Investigation consent never grants permission to apply a change.
4. **Bounded execution.** Enforce configured active-work and pending-work limits,
   deadlines, retry counts and backoff. New work rejected for capacity is not
   acknowledged as accepted. Accepted work remains inspectable during overload.
5. **Persisted waiting.** Store deadlines and signals so that a callback,
   confirmation or timeout can advance work after all original processes have
   exited. No running room or sleeping coroutine is required to retain a waiting
   workflow.
6. **Recovery.** Recover pending or eligible interrupted work using the same
   durable identities. A process or container restart with the same database volume
   preserves accepted requests, steps and known supplier outcomes.
7. **External-effect reconciliation.** Persist the intended effect before issuing
   it. Reuse its stable supplier key, and look up an ambiguous result when the
   supplier supports that contract. Record an uncertain outcome when evidence is
   insufficient for a safe retry or a definitive failure.
8. **Cancellation.** Record a cancellation request separately from its outcome.
   Cancellation before the mutation commitment point prevents that mutation.
   Afterward, cancellation is best effort under the supplier contract. Interrupting
   speech alone does not cancel accepted business work.
9. **Multi-worker coordination.** Add a PostgreSQL backend and prove exclusive
   claims, lease expiry and rejection of stale writes with independent workers.
   Keep database transactions short and keep external calls outside locks.
10. **Observable completion.** Commit result state and an event intent atomically.
    Deliver events at least once under stable IDs, with bounded retry and visible
    delivery failure. A delivered notification is distinct from workflow success.

### Storage backends

| Backend | Role | Notes |
| --- | --- | --- |
| SQLite | Initial single-host backend | Unsupported SQLite operations fail explicitly |
| PostgreSQL | Full V1 execution backend | Required before the V1 multi-worker release gate can pass |

- Do not implicitly implement two full schedulers.
- A versioned additive migration or a new-table design must keep existing M1
  requests readable. The current M1 schema permits only the `queued` state. Make
  that schema decision before introducing worker states in P1 A.
- Table count and physical schema are implementation decisions justified by these
  behaviors.

Introduce the backends in this order:

1. At PLAN-02, explicitly retain SQLite M1 intake and migration, and the first
   single-worker inquiry and recovery subset.
2. After the PLAN-03 SQLite crash demonstration, introduce the PostgreSQL
   single-worker adapter and shared store-contract checks before expanding the full
   lifecycle.
3. Later PLAN-08 work completes multi-worker coordination, migration and
   supported-subset parity.

### Asynchronous database access

All database work must respect the asynchronous API boundary. Declaring a function
with `async def` does not make blocking SQLite calls nonblocking. Use a documented
offload boundary or an appropriate async implementation, with bounded concurrency
and cleanup.

## Public contracts

### Operations

These are proposed application-library operations, not existing LiveKit APIs. The
[case/continuation guide](../case-and-continuation.md) documents the concrete
current Python ports. The table below keeps the V1 behavior contract without
claiming that every facade is importable. Finalize reusable package exports at the
installed-consumer checkpoint.

| Operation | Required behavior |
| --- | --- |
| `submit_change(scope, request, idempotency_key)` | Return the stable workflow identity and whether this call created it, only after commit |
| `get(scope, workflow_id)` | Return the current snapshot, revision, waiting reason, latest outcome, and cancellation state |
| `signal(scope, workflow_id, event_id, payload)` | Durably accept a typed callback or confirmation, deduplicating a scoped event identity |
| `cancel(scope, workflow_id, command_id)` | Return recorded cancellation intent and its current disposition; never claim remote cancellation merely from local task cancellation |
| `events(scope, workflow_id, after_cursor, limit)` | Return bounded, ordered local history for diagnosis and resumption |

### Typed results and errors

Typed requests and results must avoid unstructured status dictionaries at the public
boundary. Errors distinguish these cases:

- invalid input;
- scope denial or not-found, under the chosen disclosure policy;
- idempotency conflict;
- stale revision;
- expired quote;
- invalid confirmation;
- invalid transition;
- capacity rejection;
- unavailable storage.

An uncertain supplier outcome is a persisted business result that requires
reconciliation. It is not an instruction to retry blindly.

### Stable identities, signals and timers

| Contract | Required behavior |
| --- | --- |
| Submission, signal and cancellation IDs | Survive caller retries; reusing an ID with different canonical content is a conflict |
| Signals that arrive before the matching wait | Retained and correlated; unrelated signals cannot advance the workflow |
| Persisted business timers | Use wall-clock deadlines; test clocks make expiry behavior deterministic without long real sleeps |

### Replay horizons and cleanup

Before cleanup is introduced, define replay horizons and retained idempotency,
confirmation and effect tombstones. Business deadlines and diagnostic-history
pruning do not erase the evidence needed to reject a duplicate or reconcile an
uncertain operation. Test a late retry after pruning. An expired identity receives
a documented rejection rather than silently creating new work.

## Correctness and failure boundaries

| Boundary | Required behavior | Notes |
| --- | --- | --- |
| Confirmation snapshot | The confirmed proposal snapshot is immutable | A model statement that the user agreed cannot construct a valid confirmation by itself |
| Mutation commitment point | One protected transaction validates the intent's preconditions and records the intent | A preceding cancellation prevents commitment; a later one cannot promise reversal |
| External-call boundary | Fencing a database write does not stop an expired worker from calling a supplier | No unconditional exactly-once effects; P1-15 adds a stale-worker external-call check |

### Confirmation snapshot

The application presents a persisted proposal. The proposal contains at least the
booking, requested dates, quote identity, additional amount and currency, expiry and
case revision. The confirmed snapshot is immutable. A statement by a large language
model (LLM) that the user agreed cannot construct a valid confirmation by itself.

### Mutation commitment point

Before accepting a mutation intent, validate these facts in the same protected
transaction that records the intent:

- the actor's authority;
- the current case revision;
- quote expiry;
- cancellation status;
- the matching confirmation snapshot.

This transaction is the mutation commitment point.

- A preceding cancellation prevents commitment.
- A later cancellation is an attempt to stop already-committed work and cannot
  promise reversal.
- A user revision after commitment creates a new request or reconciliation path
  rather than silently rewriting the committed operation.

### External-call boundary

The worker should avoid dispatching committed work that it can still safely cancel,
but an external-call boundary remains. Fencing a database write does not stop an
expired worker from calling a supplier. External safety requires that supplier's
idempotency, status lookup or participating fencing behavior. The package does not
promise unconditional exactly-once effects.

## Acceptance matrix

### Status

P1-01 through P1-05 retain executable SQLite acceptance and recovery evidence. All
twenty rows have registered runners and retained passing reports, P1-01 through
P1-20. P1 V1 is qualified for the local POC using provider_real v2. local_real
remains unqualified, and complete P2/P3 acceptance remains pending.

Registration does not establish execution success. Every row remains a release
requirement with its applicable backend and integration evidence.

### Test approach

Deterministic supplier tests use the local fake supplier, controlled clocks and
barriers, and failpoints. No external model or carrier keys are needed. Rows that
involve workers use independent processes, not merely new objects in one process.

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

### Additional requirement for P1-15

For P1-15, also exercise a stale worker attempting an external call. The fake
supplier's participating contract must prevent an incorrect duplicate effect, or the
test must show the operation becoming uncertain. A passing database-fence test alone
is insufficient evidence of supplier safety.

## Development checkpoints

These charter milestones are release-oriented groupings. They are not the granular
implementation Phase A through H labels. The
[P1 implementation plan](../implementation/p1-agent-continuity.md) owns current
phase and task status.

| Step | Outcome | Gate |
| --- | --- | --- |
| Existing M1 | Retain CLI investigation intake, scoped deduplication, and conflict tests | No new completion claim |
| P1 A | Preserve M1 and declare the SQLite compatibility subset, then add one independent SQLite inquiry worker and one crash window | Pass P1-04/P1-05 with investigation permission, followed by the early PostgreSQL adapter before lifecycle expansion |
| P1 B | Persisted steps, waits/signals, retry/deadline policy, separate quote confirmation and mutation commitment | Pass relevant P1-06 through P1-14 |
| P1 C | PostgreSQL workers, stale-write/effect handling, migration/parity hardening and durable result events | Pass P1-15 through P1-19 |
| P1 D | Real LiveKit tool adapter, measured responsiveness and standalone local demonstration | Complete release evidence |

Current status: the Phase F, Phase G, H1, H2 and P1-I26 gates listed under
Implementation status passed. P1 V1 is qualified for the local POC using
provider_real v2. local_real remains unqualified, and complete P2/P3 acceptance
remains pending. Remote CI and publication do not block this POC.

The first checkpoint does not modify bookings. The later mutation crash demo
requires the separate explicit confirmation flow to exist first. This preserves the
permission model of the current `BookingChange` starter.

## Release gates

| Gate | Required evidence | Notes |
| --- | --- | --- |
| Run profiles and restart | Mandatory failure tests and the standalone workflow demonstration run with local persistence and fake suppliers | Restart tests reuse named volumes; destroying a volume is an explicit reset |
| Local-ready V1 | P1-20's actual browser and media lifecycle checks against the local LiveKit server | Uses scripted inference and audio fixtures |
| Portfolio-ready V1 | The relevant interaction repeated with configured real speech and model providers, or with validated local inference | Scripted fixtures alone do not establish real model behavior |
| Release contents | All P1 acceptance rows, shared checks, an API example, a failure trace, a crash demo, a benchmark artifact and limitations | Evidence names the supplier contract, database backend, SDK version, model configuration and run profile |
| Installed-package check | The minimal example runs from an isolated installed consumer of the built wheel | Starts when a real second consumer establishes the package boundary; repeat at release |
| Coding agent contract | Onboarding documents and a harness that maps P1 acceptance IDs to executable scenarios | Missing scenarios remain pending rather than reporting success |

### Run profiles and restart

Retain the native standard-library M1 path. The shared `offline`, `lab` and `live`
profiles are defined centrally. All mandatory failure tests and the standalone
workflow demonstration run with local persistence and fake suppliers.

Container restart tests reuse named volumes. Destroying a volume is an explicit
reset and is outside the restart guarantee.

### Local-ready V1

Local-ready V1 requires P1-20's actual browser and media lifecycle checks against
the local LiveKit server with scripted inference and audio fixtures.

### Portfolio-ready V1

Portfolio-ready V1 additionally repeats the relevant interaction with configured
real speech and model providers, or with validated local inference. Scripted
fixtures alone do not establish real model behavior. Cloud hosting and Cloud
simulations are optional validation paths.

### Release contents

Release requires:

- all P1 acceptance rows;
- shared code-quality and integration checks;
- a minimal API example;
- an inspectable failure trace;
- a reproducible crash demo;
- a benchmark artifact with workload and versions;
- documented limitations.

Release evidence must say which supplier contract, database backend, SDK version,
model configuration and run profile were exercised. Current M1 code is not evidence
that these V1 requirements have been met.

### Installed-package check

When a real second consumer establishes the reusable package boundary, build its
wheel and run the minimal example from an isolated installed consumer. No sibling
source paths or undeclared runtime services may be required. Repeat this check at
release.

### Coding agent contract

The project's onboarding directory, `projects/agent-continuity`, must expose the
required `AGENTS.md`, `Design.md` and `README.md` documents described in the
portfolio scope. Do not move the existing M1 package merely for layout. These
documents must identify authoritative contracts, state ownership, supported
commands, safe local fixtures and the tests that protect each invariant. Proposed
APIs in this scope must be distinguishable from importable code and currently
runnable commands.

The code-level harness must map P1 acceptance IDs to executable scenarios. It must
produce machine-readable outcomes plus useful failure artifacts. It must provide:

- typed request and result fixtures;
- a controllable clock;
- worker process control;
- explicit crash barriers;
- persisted supplier state;
- inspection of effects and workflow history.

Each command and required environment variable must be visible in the documented
entry point. No hidden setup or undisclosed paid-service call is permitted. Missing
scenarios remain pending rather than reporting success.

P1's standalone harness must run without Project 2 or Project 3. The integrated
harness may add those adapters, but it cannot replace the standalone contract tests.
The real-voice scenarios must be labelled separately from deterministic fake-model
scenarios.

This documentation and harness contract is an additional V1 release requirement,
alongside all P1-01 through P1-20 behavior checks.

## Deferred scope

The following are outside V1:

| Area | Deferred item |
| --- | --- |
| Workflow model | General-purpose directed acyclic graph (DAG) execution, arbitrary coroutine persistence and a visual workflow designer |
| Business integrations | Production supplier integrations, payments and automatic compensation for real bookings |
| Operations | Multi-region failover, host or disk disaster recovery and managed autoscaling |
| Platforms | Broad authentication platforms and sophisticated schedulers |

The synthetic application still enforces the required scope and confirmation
boundaries. Add infrastructure only when an accepted requirement and a failing test
justify it.

## References

Use LiveKit's existing sessions, tools and conversational workflow constructs. This
package owns application business-work recovery.

Native AgentSession, AgentTask/TaskGroup, tools, handoffs and job lifecycle own
conversational control. Reuse those surfaces instead of duplicating them. They do
not establish the cross-process business-recovery guarantee required here.

| Document | Purpose |
| --- | --- |
| [Portfolio scope](../portfolio-scope.md) | Shared runtime, identifiers and release policy |
| [Validation plan](../validation-plan.md) | What counts as evidence |
| [P1 implementation plan](../implementation/p1-agent-continuity.md) | Current phase and task status |
| [Case/continuation guide](../case-and-continuation.md) | Concrete current Python ports |
| [Root design](../../Design.md) | The shared `TaskExecutionPort` primitive |
| [Workflow constructs](https://docs.livekit.io/agents/logic/workflows/) | Native AgentSession, AgentTask/TaskGroup, tools and handoffs |
| [Server lifecycle](https://docs.livekit.io/agents/server/lifecycle/) | Native agent server and job lifecycle |
