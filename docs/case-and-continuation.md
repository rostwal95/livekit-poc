# Exact consent and durable continuation guide

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Explain how P1 records a case, binds exact consent to a quote and continues durable work through waits, retries, effects and completion |
| Audience | Engineers who change P1 case authority or continuation, or who operate it locally; coding agents |
| Scope | Case boundaries, transactions, waits, retries, lease interaction, setup, bounds and observability; excludes the detailed effect and worker contracts |
| Owns | P1 case authority, exact quote consent, the transaction and replay contract, waits and retry policy |
| Related | [Case authority decision](decisions/0004-case-authority-and-continuation.md) · [Phase D work item](work-items/0010-p1-phase-d-authority-and-waits.md) · [Effects and completion](effects-and-completion.md) · [Leases and workers](leases-and-workers.md) · [P1 implementation plan](implementation/p1-agent-continuity.md) |

## Overview

This guide explains how P1 (agent continuity) records a case, binds exact consent
to a quote and continues durable work through waits, retries, effects and
completion.

| Section | What it covers |
| --- | --- |
| [Public boundaries](#public-boundaries) | Public interfaces, case and task identity, quote snapshots, proposals and confirmation |
| [Transaction and replay contract](#transaction-and-replay-contract) | Lookup, lock order, validation, commitment, replay and revision races |
| [Waits and retry policy](#waits-and-retry-policy) | Signals, waits, replacement proposals, retry dispositions and defaults |
| [Effects, cancellation and completion](#effects-cancellation-and-completion) | How effects, cancellation and completion connect to case authority |
| [Leased workers on PostgreSQL v4](#leased-workers-on-postgresql-v4) | Lease grants, controllers, outstanding work, the pull worker and the v4 upgrade |
| [Setup and demonstration](#setup-and-demonstration) | The Phase D demo and selected-schema upgrades |
| [Bounds and retention](#bounds-and-retention) | Resource bounds and retention |
| [Observability and failure handling](#observability-and-failure-handling) | Metrics, logs and error codes |
| [Verification and status](#verification-and-status) | The PostgreSQL gate and phase and release status |

### Phase scope

Phases A to H are the granular P1 implementation phases in the
[P1 implementation plan](implementation/p1-agent-continuity.md). Identifiers such
as P1-I11 are implementation task IDs, not acceptance IDs such as P1-20.

| Phase | Implementation tasks | PostgreSQL | What it adds |
| --- | --- | --- | --- |
| D | P1-I11 through P1-I14 | v2 | Case authority, exact quote and confirmation, atomic intent and dispatch commitment, durable waits and signals, finite retry and deadline policy |
| E | P1-I15 through P1-I18 | v3 | Supplier-bound mutation, cancellation and durable completion delivery; its [final gate](work-items/0011-p1-phase-e-effects-and-completion.md) passed |
| F | P1-I19 through P1-I21 | v4 | Leases and bounded workers |
| G | P1-I22 through P1-I25 | v4 | A separate scoped managed-case UI and a native scripted conversation consumer |

- All continuation state is keyed to the original task.
- A successful inquiry and a completed booking change are different facts.

### Related guides and boundaries

| Document | Purpose |
| --- | --- |
| [Effects and completion guide](effects-and-completion.md) | Owns the detailed supplier, receiver, worker and replay contract |
| [Lease and worker guide](leases-and-workers.md) | Owns the full lease and worker runtime contract |
| [Local setup guide](../local-setup/README.md) | The deliberately selected ACTIVE v4 schema and the private fixture procedure |

- The original SQLite M1 intake (the confirmed-investigation intake) and the
  transport diagnostics remain independently available.

## Public boundaries

| Boundary | Purpose | Authority and limitations |
| --- | --- | --- |
| `CaseAuthorityPort` / `PostgresCaseAuthority` | Enroll/read/revise current case; validate quotes and commit exact intent | Trusted application actor; original tasks/payload/effect unchanged |
| `ScopedCaseService` | Authenticate case commands, cancellation and effect/completion/delivery views; derive actor/scope from `TokenDirectory` | No actor/scope override or quote-publishing method; absent effects configuration is explicitly unsupported |
| `AsyncCaseService` | Finite offload of the same authenticated service | Four default slots; cancelled callers retain capacity until real work finishes |
| `PostgresLifecycle` | Manage the original inquiry, persist waits/signals and advance due work | Existing execution owner; no parallel durable queue |
| `ManagedInquiryWorker` | One bounded lookup-first inquiry attempt | V2/v3 cooperative session slot; v4 explicit task lease and same-transaction epoch guard |
| `PostgresEffects` / `MutationWorker` | Execute committed exact supplier proposals, retain cancellation and atomically complete the business outcome/event | V3 cooperative slot; v4 current explicit lease/epoch, original effect identity and supplier cooperation |
| Completion delivery boundary | Deliver a stable immutable completion event to an independent cooperating receiver | Receiver identity binds before first attempt; delivery is separate from business outcome and human acknowledgement |
| `CaseTelemetry` | Observe real public operations | Private metric registry; fixed labels and safe producer fields |

### Case and task identity

Cases receive a distinct immutable `case_id`. `task_id` remains the original
workflow identity. This subset binds one case to one task, and revision, replay
and restart preserve both. A future multi-workflow case association must be
explicit.

### Quote snapshots

`QuoteSnapshot` is immutable and versioned. It binds:

- the quote ID and original task ID;
- the current case revision;
- the booking reference and requested check-in date;
- an integer amount in minor units and its currency;
- an absolute UTC expiry.

Supported fixture currencies are USD, EUR, GBP and INR.

| Version | Additional bindings | Mutation authority |
| --- | --- | --- |
| v1 (legacy) | None | Cannot authorize a new mutation |
| v2 | The immutable case ID, the supplier identity and the expected supplier booking revision, all required together | A new mutation needs an exact v2 proposal |

- Supplier revision is an exact nonnegative integer with room for its successor.
- Floats, boolean amounts or revisions, unknown or extra fields and unsupported
  payload versions are rejected.
- Legacy v1 bytes and known read and replay receipts remain unchanged after the
  v3 upgrade. Reissue an exact v2 proposal instead of filling bindings from
  current supplier state.
- Existing intake confirmation remains investigation-only.

### Proposals and confirmation

- A trusted synthetic proposal producer calls `publish_quote`. It must provide a
  fresh quote for the current case snapshot. The old inquiry effect is never
  reused as evidence for revised dates.
- `ScopedCaseService` does not expose proposal issuance.
- Confirmation contains the exact quote and `explicit=True`. Free-text or model
  summaries cannot substitute for it.
- Confirmation is a trusted explicit application command, not a human-presence
  attestation.
- The Phase G profile collects exact quote and revision approval through a
  separate authenticated panel action. No native model tool can confirm.
- The synthetic browser test proves that control path, not physical human
  presence.
- A production adapter must preserve explicit user action and the same
  authority.

## Transaction and replay contract

1. Scope and owner lookup uses the actor authenticated by the application.
   Unknown, other-account and another-owner case IDs get the same unavailable
   response.
2. The admission lock, case row and continuation and wait rows are locked in one
   consistent order. Clock and expiry checks happen after acquiring locks.
   Supplier, model and network work never occurs in this transaction.
3. A new command validates the current revision and quote, exact confirmation,
   owner, cancellation flag, quote expiry, and the managed business or wait
   deadline and state. A new v2 mutation intent requires an existing managed
   business deadline.
4. Immutable confirmation, action intent, stable effect ID and dispatch event
   commit together. The managed continuation and wait disposition update in that
   same transaction. An intent is a commitment record. Supplier mutation and
   completion delivery run separately through the Phase E workers, outside this
   transaction. Phase D historical demonstrations stop at commitment.
5. The same command and content return the original committed receipt, even after
   expiry. An altered command replay conflicts. Different valid commands for an
   already committed exact proposal cannot create another logical effect or
   event.
6. Revision and commitment serialize. When revision happens first, it rejects the
   stale confirmation. When commitment happens first, it rejects an in-place
   rewrite and requires a new request path. Revision is compare-and-set (CAS):
   after an ambiguous acknowledgement, inspect the current revision before
   submitting another revision command.

## Waits and retry policy

### Signals and waits

- Signals retain typed actor, task and quote content under a scoped event
  identity.
- An early signal remains persisted before its wait exists.
- Arm a wait with a stable universally unique identifier (UUID), the exact quote
  and an absolute deadline.
- Advance consumes one current matching signal and commits its intent in the
  same transaction.
- Replay of the same signal deduplicates. Altered event content conflicts.
- Unrelated, stale or expired signals cannot advance work.
- The deadline is effective after process or container loss, without a sleeping
  task.

### Replacement proposals

Publishing a replacement proposal expires the prior pending wait. Continuation
returns to `inquiry_complete` without extending its original business deadline.
A fresh exact signal can then advance the new wait, but old signals cannot
confirm the replacement. Replaying an old publication never restores it as
current.

### Retry dispositions

| Observation | Persisted disposition | Eligibility |
| --- | --- | --- |
| Positive evidence of no dispatch and transient failure | `retry_wait` with `next_attempt_at` | Bounded exponential delay; strictly before original deadline |
| Permanent rejection | `failed` | No retry |
| Finite attempt budget exhausted | `failed` / `retry_exhausted` | No retry |
| Business deadline reached before a safe dispatch | `failed` / `deadline_expired` | No dispatch or renewed deadline |
| Ambiguous dispatch or failed reconciliation of a prior possible effect | `uncertain` / `ambiguous_outcome` | No automatic resend; retain evidence |
| Successful lookup after deadline | Actual known inquiry result | Persist truth; deadline cannot erase an observed effect |

### Retry policy defaults

Trusted configuration can set these values within the allowed ranges.

| Option | Default | Allowed values | Description |
| --- | --- | --- | --- |
| Attempts | 3 | 1–100, within the underlying execution attempt cap | Finite attempt budget |
| Initial delay | 1 second | Up to one hour | Delay before the first retry |
| Maximum delay | 30 seconds | Up to one hour | Upper bound for any retry delay |

- Each worker invocation makes one attempt. An explicit later invocation
  evaluates persisted eligibility.
- The worker checks the remaining deadline again after lookup and immediately
  before dispatch.
- A clock check cannot reverse a request already accepted by a supplier.

### Legacy methods and SQLite

Legacy start, recover and finish methods reject managed execution attempts, which
prevents bypass of continuation policy. SQLite continues to support the original
inquiry subset. It gains no waits, retries or case scheduler.

## Effects, cancellation and completion

The [effects/completion guide](effects-and-completion.md) owns the detailed
supplier, receiver, worker and replay contract. This section connects that
boundary to case authority and continuation.

### Mutation

- Mutation uses the immutable committed supplier and revision binding and a
  stable effect identity.
- Persist possible dispatch before making the supplier call.
- Reliable lookup plus stable-key deduplication can reconcile a lost response.
  Missing cooperation retains an uncertain outcome and forbids an unsafe resend.
- Known supplier results survive later cancellation or deadline expiry.
- Quote expiry is checked when consent commits. It does not retroactively rewrite
  an intent.
- A fresh dispatch still checks the original business deadline.

### Cancellation

Cancellation commands retain their original scoped identity and disposition.

| Cancellation timing | Effect |
| --- | --- |
| Before commitment, or with positive evidence that dispatch has not happened | Prevents apply |
| After possible dispatch | Best effort; cannot claim remote reversal |
| During an in-flight read-only inquiry | Preserves an observed success, or closes a failed attempt without scheduling another retry |

### Completion

- Final business outcome, immutable completion event and pending delivery commit
  together.
- A terminal lifecycle remains completed, cancelled, failed or uncertain when
  advance replays the committed intent.
- Delivery has its own bounded policy and receiver binding.
- Receiver deduplication survives diagnostic pruning. Core receipts are retained.
- Delivery success is not proof of human acknowledgement.

## Leased workers on PostgreSQL v4

The [lease/worker guide](leases-and-workers.md) owns the full runtime contract.
This section summarizes how leases interact with case authority.

### Lease grants

Phase F extends the same authority with retained per-task execution leases and a
persisted coordination policy. A worker passes an explicit `LeaseGrant` into
`PostgresLifecycle` and `PostgresEffects`.

| Work | Writes that validate the grant |
| --- | --- |
| Inquiry | Claim and finish |
| Mutation | Claim, reservation and finish |
| Outbox | Claim and finish |

- Each of those writes validates the task, scope, owner, epoch and stored expiry
  inside the existing protected transaction.
- Database `clock_timestamp` is sampled after locks. Process wall clocks cannot
  extend lease authority.
- Release retains the epoch and takeover increments it. Stale renewal, release
  and writes fail closed.

### Controllers and lease ownership

- Public authenticated case, read and controller commands keep their actor and
  revision contract. They are distinct from worker lease ownership.
- A current lease grants no consent and does not fence provider I/O.
- Known supplier truth after business cancellation or deadline still requires a
  current owner. A paused former owner cannot commit it after losing its epoch.
  Fresh cooperating lookup or explicit uncertainty handles the external
  boundary.
- Terminal uncertainty is not reopened automatically.

### Default policy and outstanding work

The default owner-installed policy is 1,000 outstanding accepted workflows, four
active leases, 10,000 retained task identities and 30 s leases.

| Work | Counts as outstanding |
| --- | --- |
| Accepted or running base inquiry without a final business outcome, including an uncertain inquiry awaiting manual review | Yes |
| Nonterminal managed control, such as a wait or intent | Yes |
| Terminal effect outcome, including `UNCERTAIN` | No; it leaves outstanding capacity |

Outstanding work is not the number of runnable queue entries. An unresolved
inquiry stays outstanding. Reads and known replay remain available when new work
or leases are refused.

### Pull worker

- `PostgresWorkQueue` selects current due inquiry, wait, mutation and delivery
  state and acquires its task lease atomically. It does not own another persisted
  queue or acknowledge work in process memory.
- Stale or legacy signals and exhausted epochs must not prevent eligible current
  work from progressing.
- The opt-in `p1-workers` profile runs the actual bounded P1 pull worker: one
  supervised POSIX child per parent, a step timeout of at most min(15 s, lease
  duration / 2), a default 5 s shutdown drain, then a bounded kill and reap before
  release.
- Existing named fixtures and database state survive normal restart.
- Consult the
  [Phase F work item](work-items/0012-p1-phase-f-leases-and-deployment.md) and the
  [local setup guide](../local-setup/README.md) for the deliberately selected
  ACTIVE v4 schema and the private fixture procedure.

### Upgrade to v4

- Upgrade to v4 explicitly from ACTIVE v3 with `upgrade-coordination` under the
  migration principal.
- Finish unmanaged RUNNING v3 inquiries first. Serving code cannot rewrite legacy
  attempts as leased work or run data definition language (DDL), that is,
  schema-changing SQL.
- Managed running state can recover under v4.
- Existing v1–v3 read and replay and supported legacy execution remain tested.
  The old unmanaged start, recover and finish methods are unsupported on v4.

## Setup and demonstration

Use the frozen project interpreter from the repository root. Existing setup and
credentials are preserved. In the tables, `stack.py` stands for
`.venv/bin/python local-setup/stack.py`.

| Task | Command | Notes |
| --- | --- | --- |
| Initialize, start and prepare roles | `stack.py init`, `stack.py start` and `stack.py prepare-postgres` | Ordinary local stack setup in the [local setup guide](../local-setup/README.md) |
| Prepare v1 for cutover | `stack.py migrate-postgres` | The default action |
| Run the PostgreSQL test lane | `make postgres-check` | None |
| Run the Phase D demo | `make phase-d-demo` | Creates only its own synthetic schema and files |
| Upgrade a selected ACTIVE v1 schema to v2 | `postgres_cli upgrade` | Owner-only v2 upgrade |
| Upgrade ACTIVE v2 to v3 | `postgres_cli upgrade-effects` | Separate command |
| Apply the v2 upgrade through the local stack | `stack.py upgrade-postgres` | Applies that one-shot upgrade to its configured schema |

### Run the Phase D demo

```sh
.venv/bin/python local-setup/stack.py init
.venv/bin/python local-setup/stack.py start
.venv/bin/python local-setup/stack.py prepare-postgres
.venv/bin/python local-setup/stack.py migrate-postgres
make postgres-check
make phase-d-demo
```

The demo creates only its own synthetic schema and files. It then runs these
stages:

| Stage | What the demo does |
| --- | --- |
| 1 | Performs an explicit SQLite-to-PostgreSQL cutover and the owner-only v2 upgrade |
| 2 | Executes a safe transient inquiry retry |
| 3 | Starts a first disposable runtime-only container, which persists an early confirmation signal and waits, then exits and leaves no process or application file holding the wait |
| 4 | Starts a second disposable runtime-only container, which consumes once under the original task, checks a second expired wait and verifies exact intent replay |
| 5 | Checks installed module hashes outside the source tree, the unchanged fake booking, one dispatch event and observed metrics |
| 6 | Removes only its own schema and containers; the live M1 database and named volumes stay unchanged |

The scripted demo clock is synthetic. It is not a latency or capacity
measurement or proof of a human interaction.

### Upgrade a selected application schema

- For a deliberately selected ACTIVE v1 application schema, `postgres_cli upgrade`
  performs the owner-only v2 upgrade.
- The separate `postgres_cli upgrade-effects` performs the ACTIVE v2 to v3
  upgrade.
- Repeated upgrades validate the existing catalog without downgrading it.
- Both commands read only `P1_MIGRATION_*` credentials. Runtime commands read
  only `P1_POSTGRES_*`.
- Serving processes never perform DDL, and v1 consent history is not backfilled
  during the upgrade.
- The local stack `upgrade-postgres` action applies that one-shot upgrade to its
  configured schema and refuses a STAGING target. It never activates an
  unfinished cutover.
- The default `migrate-postgres` action still prepares v1 for cutover.
- Never source or print private credential files or put passwords in arguments.

## Bounds and retention

### Resource bounds

Values are default bounds. Notes give the behavior at exhaustion and on replay.

| Limit | Value | Notes |
| --- | --- | --- |
| Retained cases / controls | 10,000 each | Reject new identities; preserve existing reads/replay |
| Quotes / confirmation receipts per case | 32 / 128 | Retain authority/effect protection; reject new records |
| Signals / waits per execution | 100 / 8 | Existing exact replay remains available |
| Mutation attempts / cancellation commands per case | 8 / 128 | Finite manual mutation recovery; preserve prior cancellation replay |
| Completion delivery | 8 attempts; 1 s initial / 30 s maximum delay | Persist due time; delivered/exhausted state remains readable |
| Async I/O | 4 operations; 0.05 s admission; 10 s drain | Capacity error; cancellation does not release a running thread's slot |
| PostgreSQL | 5 s connect/statements; 1 s lock wait | Explicit bounded rejection or storage failure; no hidden retry |

### Retention

- No core cleanup or time-to-live (TTL) API exists.
- Fixture diagnostic pruning must preserve supplier and receiver receipts.
- Retain replay, confirmation, signal, consumption, cancellation, outcome and
  event, and effect identities within these finite lab bounds.
- Business expiry cannot make an accepted identity new.
- Production cleanup needs a separate replay-horizon and tombstone design, and
  late-retry tests, before deployment.
- Task-leading indexes support per-task cap and history queries. Bounds are
  configured limits, not measured production capacity.

## Observability and failure handling

### Metrics

`CaseTelemetry` emits `continuity_case_operations_total` and
`continuity_case_operation_duration_seconds` with operation and outcome labels
only.

- Sixteen operation names and three outcomes bound label combinations to 48,
  including cancel, effect, completion and delivery.
- Counters reset with the process. Durable records remain the truth.
- The registry is local to the service instance and can be scraped through
  `render()`. No new HTTP exporter or complete distributed trace is claimed.
- A telemetry failure cannot alter a business result or mask its original
  exception.

### Logs

- JSON producer logs contain a fixed event and code and an optional allowlisted
  operation and outcome.
- Tokens, actor, task and quote values, raw SQL, payloads and exception strings
  are excluded.
- Use synthetic operator results and retained state to investigate. Retry advice
  cannot authorize a new confirmation or an uncertain external effect.

### Error codes

Stable errors include these codes and the existing storage and schema codes. Each
condition is described elsewhere in this guide.

| Code | Condition |
| --- | --- |
| `stale_revision` | The case revision is no longer current, for example a confirmation that lost a revision race |
| `invalid_confirmation` | The confirmation is not the exact current quote with explicit approval |
| `quote_expired` | The quote has expired when consent would commit |
| `deadline_expired` | The managed business or wait deadline has passed |
| `intent_committed` | Commitment already happened, so an in-place rewrite is rejected |
| `execution_not_found` | The same unavailable response for unknown, other-account and another-owner case IDs |
| `idempotency_conflict` | A replay reuses a command or event identity with altered content |
| `capacity_exhausted` | A resource bound rejects a new identity |

## Verification and status

### Checks and evidence

The explicit PostgreSQL gate includes:

- populated-v1 upgrade interruption and replay;
- immutable-role, constraint and index checks;
- exact rejection and useful confirmation;
- revision races;
- signal deduplication and early or late delivery;
- finite retries and ambiguity;
- process loss and expiry.

Full fast validation retains the prior SQLite, API and real-time communication
(RTC) regressions. The local container demo and the actual RTC smoke are separate
evidence. Required skips, missing setup, zero tests or timeout never pass.

### Phase and release status

| Step | Outcome | Gate |
| --- | --- | --- |
| Phase E | Implementation and targeted tests cover supplier-bound v2 consent, actual v2-to-v3 migration preservation, mutation, cancellation and outbox contracts, and known inquiry results after cancellation | Final combined gate passed; exact observed results belong in the [Phase E work item](work-items/0011-p1-phase-e-effects-and-completion.md) |
| Phase F, P1-I19 through P1-I21 | Database-time leases, stale external-call safety and bounded worker deployment and restart | [Combined gate](work-items/0012-p1-phase-f-leases-and-deployment.md) passed |
| Phase G, P1-I22 through P1-I25 | Opt-in business profile with a scripted native `AgentSession` | Inspected local combined gate recorded in the [Phase G work item](work-items/0013-p1-phase-g-conversation-and-showcase.md) |
| H1, the inquiry workload slice of Phase H | Locally measured seeded inquiry baseline for S-I06 (the shared seeded-workload task) and the first P1-I27 slice | Recorded in the [H1 workload work item](work-items/0014-p1-phase-h-workload-baseline.md) |
| Phase H release | The current H2 restart, slow-dependency, saturation and shutdown workload, the installed host and Linux artifacts, the standalone API and consumer review, and the selected `provider_real` v2 media qualification | Passed; the [Phase H release handoff](work-items/0019-p1-phase-h-release-qualification.md) records the qualified local P1 V1 (fixed first-version) scope and exact evidence |

In the Phase G opt-in business profile:

- a scripted native `AgentSession` connects to managed PostgreSQL work, bounded
  authenticated case projections and separate exact quote approval;
- explicit media End retires the room, and a fresh native consumer reloads the
  same owned task;
- the public `RoomIO` readiness barrier precedes controls and speech, and software
  development kit (SDK) alternate session hosting is disabled.

This is actual local browser and native media. It is not physical microphone
capture, live-model quality, automatic network-loss recovery or remote continuous
integration (CI) proof.

| Capability | Status | Evidence |
| --- | --- | --- |
| P1 V1 (the fixed first-version scope) for the local proof of concept (POC) | Qualified | [Phase H release handoff](work-items/0019-p1-phase-h-release-qualification.md) |
| `local_real` profile | Not qualified | Remains unqualified under its original limits |

- Production identity, physical capture, human hearing and production capacity
  remain separate.
- Hosted CI and publication are outside this local POC, and complete P2/P3
  acceptance remains pending.
