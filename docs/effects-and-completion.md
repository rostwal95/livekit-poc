# Exact effects and durable completion guide

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Explain exact supplier effects, cancellation, reconciliation and durable completion delivery |
| Audience | Engineers who change P1 mutation, cancellation, provider or receiver binding and outbox behavior |
| Scope | P1 supplier effects and completion contracts, operations and evidence; excludes conversational and worker lifecycle detail |
| Owns | Mutation reservation and reconciliation, cancellation dispositions, outcome commitment and completion delivery |
| Related | [Case and continuation](case-and-continuation.md) · [Leases and workers](leases-and-workers.md) · [P1 guide](../projects/agent-continuity/README.md) · [Phase E work item](work-items/0011-p1-phase-e-effects-and-completion.md) |

## Overview

This guide explains how P1 (agent continuity) applies an exactly confirmed
booking change through an independent supplier, reconciles uncertain dispatches,
records cancellation and delivers a stable completion event to an independent
receiver. It is for engineers who change mutation, cancellation, provider or
receiver binding, or outbox behavior.

### Phase E scope

P1 Phase E implements P1-I15 through P1-I18 on ACTIVE PostgreSQL v3:

- an independently persisted synthetic booking mutation;
- bounded reconciliation;
- idempotent cancellation;
- atomic business outcome and completion commitment.

A separate cooperating SQLite receiver demonstrates stable completion delivery
across a real process stop after receiver commit and before local
acknowledgement. The
[phase work item](work-items/0011-p1-phase-e-effects-and-completion.md) records
verification.

Implementation task completion does not complete every charter acceptance row.
At the Phase E checkpoint the six runners, BASE-01 and P1-01 through P1-05,
retained their inquiry scope. The [qualification guide](qualification-gates.md)
and harness catalog own current registrations and the open post-v5 provider
rerun; historical phase results are not fresh evidence for later changes.

### Later phases

- Phase F subsequently implements v4 leases and bounded workers.
- Phase G adds the scoped scripted native, media and UI contribution and the
  inspected trace contribution.
- The [H1 workload work item](work-items/0014-p1-phase-h-workload-baseline.md)
  records the historical local inquiry baseline.
- Current H2 workloads, installed host and Linux package and API review, and
  selected provider_real v2 qualification passed under the
  [Phase H local P1 release](work-items/0019-p1-phase-h-release-qualification.md).

H1 and H2 are slices of Phase H. H1 is the declared inquiry workload baseline. H2
covers restart, slow-dependency, saturation and shutdown workloads.

### Related guides

Read the [case and continuation guide](case-and-continuation.md) for the original
workflow, exact consent, waits, signals and read-only inquiry policy.

- The original M1 investigation intake (the SQLite confirmed-investigation
  intake) and its diagnostics remain separate from the Phase G managed-case UI and
  native conversation profile.
- Exact quote confirmation is authenticated UI authority. No model tool grants
  itself mutation permission.

## Authority and compatibility

| Identity or fact | Owner and meaning | Required binding |
| --- | --- | --- |
| Original task and inquiry effect | Execution store | Unchanged by case, mutation or delivery |
| Case and current revision | Case authority | Distinct immutable case UUID under original task and trusted owner |
| Quote v2 and confirmation | Case authority | Exact case/task/revision, supplier UUID and expected booking revision, booking/date, integer amount, currency and expiry |
| Mutation intent and effect | Immutable action intent | Separate from inquiry effect and completion event |
| Supplier booking and result | Independent synthetic mutation supplier | Immutable provider UUID and capability mode, scope, exact intent/effect and expected revision |
| Final business outcome and event | Effect authority in one transaction | One final outcome and stable completion event per original task |
| Delivery and receiver receipt | Outbox plus independent completion sink | Original event and receiver UUID across every retry |

In the table, UUID means universally unique identifier.

### Quote v2 and legacy v1

- Quote payload v2 adds case_id, expected_supplier_revision and supplier_id
  together. All three absent identifies the historical v1 proposal.
- Read and replay of historical quotes, confirmations and intents remains
  supported after migration.
- V1 data is never upgraded by inferring a later supplier revision or configured
  provider.
- A new mutation requires a trusted fresh v2 proposal and managed continuation
  with its original absolute business deadline.
- The case authority remains the only commitment point.
- Existing M1 confirmation continues to grant investigation only.

### Mutation fixture and provider binding

To set up the end-to-end booking flow:

1. Initialize the mutation fixture explicitly.
2. Use its read-only inquiry_view() with ManagedInquiryWorker, so that
   investigation, quote revision and apply observe the same booking authority.
3. Read provider_id and the booking revision from that fixture, and bind them
   into the trusted proposal before requesting exact confirmation.

The older FakeSupplier remains the original standalone inquiry demonstration. It
is not an interchangeable mutation authority.

- The provider identity and cooperating mode persist in fixture metadata.
  Reopening with a conflicting identity or mode fails.
- Switching supplier files after commitment cannot redirect the effect to
  another booking authority.
- The worker rejects a provider mismatch before consuming a new attempt or
  calling lookup or apply.
- A known result must match every committed identity and operation field before
  it can become local business truth.

## Claim, dispatch and reconciliation

PostgresEffects uses the shared protected admission and case transaction and the
original managed control. On v3, MutationWorker holds the cooperative worker
session slot for one bounded invocation; v4/v5 use the explicit lease and epoch
guards in the [worker guide](leases-and-workers.md). Supplier lookup and apply happen after
each database transaction closes. No new execution queue, sleeping task or broker
is created.

1. A claim creates a retained attempt and advances an attempt-owner generation.
   CLAIMED alone proves no new dispatch reservation. A process that stops here
   can recover and progress, even with a noncooperating supplier.
2. prepare_dispatch checks the current generation, active attempt and CLAIMED
   state. It then commits DISPATCHED and increments dispatch_count before any
   apply call. A duplicate reservation cannot advance that attempt again.
3. A dispatch_count greater than zero records a possible prior invocation, even
   when a later recovery has returned the row to CLAIMED. A database commit does
   not prove that a request reached the supplier, and a missing response does not
   prove that it did not take effect.
4. With declared reliable lookup and idempotency, recovery looks up the same
   immutable effect first. A known result is persisted even after cancellation or
   business expiry. A reliable absent result permits the same effect's bounded
   same-key retry only while the case is not cancelled and before the original
   deadline; see
   [Lookup miss after a prior reservation](#lookup-miss-after-a-prior-reservation).
5. Without those cooperating guarantees, a possible dispatch becomes terminal
   UNCERTAIN without another apply. Fixture inspection cannot substitute for the
   declared provider contract. Automatic adjudication after terminal uncertainty
   is outside this phase and would need an explicit new outcome and event
   contract.
6. Fresh positive no-dispatch dependency failures can return to PENDING for a
   manually initiated bounded retry. Unknown defects propagate and preserve
   dispatch evidence. An expired deadline or exhausted budget with possible prior
   dispatch cannot fabricate a definite failed external effect.

### Lookup miss after a prior reservation

After a prior dispatch reservation, a lookup that finds nothing permits the
same-key retry only while the case is not cancelled and before the original
deadline. Otherwise the effect finishes UNCERTAIN with ambiguous_outcome. It
never finishes as cancelled_before_dispatch or deadline_expired, because a paused
earlier call may still reach the supplier.

| Case state when the lookup finds nothing | Result |
| --- | --- |
| Not cancelled and before the original deadline | Same-key retry of the same effect |
| Cancelled | UNCERTAIN with ambiguous_outcome; cancellation disposition requested_best_effort |
| Original deadline reached | UNCERTAIN with ambiguous_outcome |

### Deadlines and attempt generations

- Quote expiry is checked when the intent commits. Dispatch uses the original
  business deadline, so an already committed quote may pass its quote expiry
  before a still eligible dispatch.
- No deadline check can reverse an already accepted request.
- The shared worker slot is cooperative single-worker coordination.
- Generation checks fence local attempt writes, not supplier I/O. They are not
  lease epochs or an unconditional guarantee of exactly one physical request.

## Cancellation contract

The authenticated public service derives actor and scope internally.

- Cancellation uses a typed USER_REQUESTED reason and a scoped command identity.
- The same command and task return the original receipt before retention
  capacity is checked. Reusing the command for another task conflicts.
- Cancellation and confirmation or reservation serialize through the same
  protected case boundary.

| Observation at cancellation | Immutable receipt | Business behavior |
| --- | --- | --- |
| No committed intent | cancelled_before_commit | Set case cancelled, expire pending waits and atomically complete cancelled with no mutation identity |
| Intent exists and dispatch_count is zero | cancelled_before_dispatch | Keep immutable intent, close any current attempt and complete cancelled without apply |
| Any prior dispatch reservation | requested_best_effort | Record request and case flag; preserve pending control/effect truth until reliable result or uncertainty; a later lookup miss ends UNCERTAIN, never cancelled_before_dispatch |
| Final outcome already exists | already_terminal | Retain original outcome/event and add cancellation receipt |

After cancellation, an effect with a prior dispatch reservation gets no same-key
retry. A lookup that finds nothing finishes it UNCERTAIN with ambiguous_outcome
and the requested_best_effort disposition, because a paused earlier call may
still reach the supplier. See
[Lookup miss after a prior reservation](#lookup-miss-after-a-prior-reservation).

- Cancellation during an active read-only inquiry does not erase its known
  inquiry result or close its attempt prematurely. It prevents a new booking
  mutation and keeps the continuation cancelled.
- A later known mutation success remains success, with a requested_best_effort
  observation.
- Cancellation is never a refund, compensation or supplier rollback promise.

## Completion and receiver delivery

### Atomic completion

The final effect disposition, the business_outcomes row, the immutable
completion_events row and the initial completion_deliveries row commit together.
A failed transaction publishes none of those final facts. A lost return after
commit is recovered by reading the same completion, without another mutation
attempt.

### Outcome, delivery and acknowledgement are separate

Business outcome, delivery and human acknowledgement are separate dimensions.

| State | Dimension | Meaning |
| --- | --- | --- |
| SUCCEEDED | Business outcome | Contains exact supplier result evidence |
| FAILED | Business outcome | Contains a definitive safe failure |
| UNCERTAIN | Business outcome | Preserves an unresolved possible effect |
| CANCELLED | Business outcome | Requires positive evidence that mutation was prevented |
| PENDING, DELIVERING, DELIVERED, EXHAUSTED | Delivery | Describe completion transport only |

- A failed or exhausted delivery cannot change a successful business outcome.
- DELIVERED proves that this cooperating receiver accepted the canonical event.
  It does not establish a live conversation, spoken response, browser playback or
  human acknowledgement.

### Receiver binding and retries

- Before the first receiver I/O, delivery binds its immutable receiver_id in
  PostgreSQL.
- All later attempts require the same receiver, including after a lost
  acknowledgement. A mismatched receiver is rejected before attempt consumption.
- CompletionDeliveryWorker performs one bounded attempt outside the database
  transaction.
- A receiver or storage failure records bounded exponential backoff.
- A crash after receiver success leaves DELIVERING recoverable with the same
  event and target.
- Receiver deduplication makes the retained logical event unique, even when
  transport retries more than once.
- Explicit rerouting is deferred.

## Setup and demonstration

Run with the frozen interpreter from the repository root. Preserve existing local
settings and volumes.

### Prepare a staging target

```sh
.venv/bin/python local-setup/stack.py init
.venv/bin/python local-setup/stack.py start
.venv/bin/python local-setup/stack.py prepare-postgres
.venv/bin/python local-setup/stack.py migrate-postgres
```

migrate-postgres prepares a STAGING v1 target for controlled cutover. It does not
activate an unfinished import.

### Upgrade a selected ACTIVE application schema

For a deliberately selected ACTIVE application schema, first apply the owner-only
v2 upgrade, then the v3 effects upgrade. Do not run these two upgrades against
the fresh STAGING target:

```sh
.venv/bin/python local-setup/stack.py upgrade-postgres
.venv/bin/python local-setup/stack.py upgrade-effects
```

### Run the regression lane and demo

The regression lane and demo activate their own isolated synthetic schemas. Run
these directly after role setup, without upgrading the live schema:

```sh
make postgres-check
make phase-e-demo
```

### Credential and migration rules

- The one-shot postgres_cli upgrade-effects command reads only P1_MIGRATION_*.
  Serving and worker operations read only runtime credentials.
- Do not print or source private settings or pass credentials in command
  arguments.
- Runtime constructors validate the schema and never perform data definition
  language (DDL), that is, schema-changing SQL.
- V3 is additive to v2. It preserves existing rows, IDs, import receipts and
  immutable payloads. Only the existing control-state vocabulary expands, for
  completed and cancelled.
- The migration verifies constraints, indexes and exact role grants, and rejects
  drift or a STAGING source.

### What the phase demo checks

- The phase demo uses its own synthetic schema and separately persisted supplier
  and receiver files.
- Runtime-only containers stop after external success and restart under the same
  identities.
- The demo inspects the supplier booking revision, local outcome, stable
  completion and receiver receipt rather than relying on log narration.
- The synthetic clock is not a latency measurement.
- The demo cleans only its owned resources. Normal local stop and start preserve
  application state.

## Bounds and retention

| Resource | Default and supported bound | Exhaustion or replay behavior |
| --- | --- | --- |
| Mutation attempts per effect | 8, trusted configuration 1–100 | Manual invocations consume retained attempts; no possible dispatch means definitive exhaustion, possible dispatch remains uncertain |
| Cancellation receipts per task | 128, trusted configuration 1–10,000 | Reject new commands at capacity, preserve original replay and reads |
| Completion delivery attempts | 8, trusted configuration 1–100 | Retry same event/receiver, then EXHAUSTED without changing business truth |
| Delivery delay | 1 s initial, 30 s maximum, configurable up to 3,600 s | Persist next eligibility, no hidden sleeping retry loop |
| Receiver core receipts | 10,000, trusted configuration 1–1,000,000 | Refuse new events at capacity, replay retained events first |
| Receiver diagnostic projection | 100, trusted configuration 1–1,000 | Bound/prune diagnostic rows only, retain canonical dedup receipts |

After EXHAUSTED, a last lost acknowledgement can still coexist with a retained
receiver receipt.

### Retained records

- Core mutation attempts, cancellations, outcomes, events, delivery routing and
  supplier and receiver deduplication receipts are retained.
- PostgreSQL runtime roles have no DELETE grants on those records.
- The sink prune_diagnostics operation removes only a separate display
  projection. A late event replay after pruning returns the original receiver
  receipt and cannot recreate a logical completion.
- Production cleanup requires a separate replay-horizon and tombstone design.
- Current limits are explicit lab safety bounds, not measured storage or
  throughput service-level objectives (SLOs).

## Observability and verification

### Logs and failure codes

- Fixed producer events cover mutation claim and reservation, supplier
  application or reconciliation, cancellation, completion and delivery.
- Logs exclude payloads, SQL parameters, identities, booking values, credentials
  and raw exception text.
- Typed failures distinguish validation or conflict, dependency failure,
  definitive supplier rejection, original deadline, bounded exhaustion and
  ambiguous outcome.
- Specific effect failure codes map to the existing continuation error
  vocabulary. Receiver failure never changes it.
- Telemetry exceptions cannot replace accepted results or original errors.

### Metrics and traces

- CaseTelemetry measures real authenticated cancel, effect, completion and
  delivery calls alongside existing case operations.
- Its fixed 16 operation names and three outcomes allow at most 48 label
  combinations and 816 counter and histogram series.
- It provides local render() output. Counters are process observations and reset
  on restart. The retained ledger is authoritative.
- Phase E itself did not add export. Phase G later adds bounded filtered
  application and software development kit (SDK) spans, inspected through raw
  Jaeger v3 trace data. See [observability](observability.md) for the actual
  coverage.
- H1 adds observed inquiry latency and API and worker resource measurements.
- The later H2 restart, slow-dependency, saturation and shutdown gates and the
  selected provider_real v2 media gates passed.
- Human-delivery acknowledgement, physical quality and production capacity remain
  unqualified. local_real is a separately unqualified profile.

### Tests

Unit and real PostgreSQL tests cover:

- exact provider and result binding;
- uncertainty;
- claim and reservation crash distinctions;
- stale generations;
- cancellation races;
- atomic completion rollback;
- lost returns.

Independent supplier and receiver process tests cover external success before
local acknowledgement. Tests also exercise backoff and caps, receiver-target
swapping, privacy, permission and schema drift, capacity replay and late replay
after diagnostic pruning.

Required missing setup, skips, zero tests and timeout remain non-passing. See the
phase work item for the final observed commands and results.

### Later contributions and release status

- Phase F leases and the
  [Phase G local native, media and UI gate](work-items/0013-p1-phase-g-conversation-and-showcase.md)
  are subsequent contributions.
- The measured H1 baseline contributes to S-I06 (the shared seeded-workload task)
  and the first P1-I27 workload slice.
- P1-I26 installed-consumer, artifact and API review, the current H2 workloads and
  selected P1-I28 provider_real v2 inference completed the local P1 V1 (fixed
  first-version scope) release.
- The [release handoff](work-items/0019-p1-phase-h-release-qualification.md) owns
  exact qualification and limits.
- The [implementation plan](implementation/p1-agent-continuity.md) records the
  implemented P2/P3 slices and their remaining charter release work, while
  local_real remains independently unqualified.
