# Exact effects and durable completion guide

Status: Active
Last reviewed: 10 November 2026

## Overview

P1 Phase E implements P1-I15 through P1-I18 on ACTIVE PostgreSQL v3: an
independently persisted synthetic booking mutation, bounded reconciliation,
idempotent cancellation and atomic business outcome/completion commitment. A
separate cooperating SQLite receiver demonstrates stable completion delivery
across a real process stop after receiver commit and before local acknowledgement.
The [phase work item](work-items/0011-p1-phase-e-effects-and-completion.md) records
verification. Implementation task completion does not complete every charter
acceptance row. The six existing BASE-01/P1-01 through P1-05 runners retain their
existing scope. Phase F subsequently implements v4 leases and bounded workers;
G adds the scoped scripted native/media/UI and inspected trace contribution.
The [H1 workload work item](work-items/0014-p1-phase-h-workload-baseline.md) now
records the historical local inquiry baseline. Current H2 workloads, installed
host/Linux package/API review and selected provider_real v2 qualification passed
under the [Phase H local P1 release](work-items/0019-p1-phase-h-release-qualification.md).

Read the [case and continuation guide](case-and-continuation.md) for the original
workflow, exact consent, waits, signals and read-only inquiry policy. Original M1
investigation intake and diagnostics remain separate from the G managed-case UI
and native conversation profile. Exact quote confirmation is authenticated UI
authority; no model tool grants itself mutation permission.

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

Quote payload v2 adds case_id, expected_supplier_revision and supplier_id together.
All three absent identifies the historical v1 proposal. Read/replay of historical
quotes, confirmations and intents remains supported after migration. V1 data is
never upgraded by inferring a later supplier revision or configured provider. A
new mutation requires a trusted fresh v2 proposal and managed continuation with
its original absolute business deadline. The case authority remains the only
commitment point. Existing M1 confirmation continues to grant investigation only.

Initialize the mutation fixture explicitly. For the end-to-end booking flow,
use its read-only inquiry_view() with ManagedInquiryWorker so investigation,
quote revision and apply observe the same booking authority. Read provider_id and
booking revision from that fixture and bind them into the trusted proposal before
requesting exact confirmation. The older FakeSupplier remains the original
standalone inquiry demonstration, not an interchangeable mutation authority. The provider identity and cooperating mode persist in fixture
metadata. Reopening with conflicting identity/mode fails. Switching supplier
files after commitment cannot redirect the effect to another booking authority.
The worker rejects a provider mismatch before consuming a new attempt or calling
lookup/apply. A known result must match every committed identity and operation
field before it can become local business truth.

## Claim, dispatch and reconciliation

PostgresEffects uses the shared protected admission/case transaction and original
managed control. MutationWorker holds the existing cooperative worker session
slot for one bounded invocation. Supplier lookup/apply happens after each database
transaction closes. No new execution queue, sleeping task or broker is created.

1. A claim creates a retained attempt and advances an attempt-owner generation.
   CLAIMED alone proves no new dispatch reservation. A process that stops here
   can recover and progress even with a noncooperating supplier.
2. prepare_dispatch checks current generation, active attempt and CLAIMED state,
   then commits DISPATCHED and increments dispatch_count before any apply call.
   A duplicate reservation cannot advance that attempt again.
3. dispatch_count greater than zero records a possible prior invocation even when
   a later recovery has returned the row to CLAIMED. A database commit does not
   prove a request reached the supplier, and a missing response does not prove it
   did not take effect.
4. With declared reliable lookup and idempotency, recovery looks up the same
   immutable effect first. A known result is persisted even after cancellation or
   business expiry. A reliable absent result permits the same effect's bounded
   retry before the original deadline.
5. Without those cooperating guarantees, a possible dispatch becomes terminal
   UNCERTAIN without another apply. Fixture inspection cannot substitute for the
   declared provider contract. Automatic adjudication after terminal uncertainty
   is outside this phase and would need an explicit new outcome/event contract.
6. Fresh positive no-dispatch dependency failures can return to PENDING for a
   manually initiated bounded retry. Unknown defects propagate and preserve
   dispatch evidence. An expired deadline or exhausted budget with possible prior
   dispatch cannot fabricate a definite failed external effect.

Quote expiry is checked when intent commits. Dispatch uses the original business
deadline, so an already committed quote may pass its quote expiry before a still
eligible dispatch. No deadline check can reverse an already accepted request.
The shared worker slot is cooperative single-worker coordination. Generation
checks fence local attempt writes, not supplier I/O; they are not lease epochs or
an unconditional guarantee of exactly one physical request.

## Cancellation contract

The authenticated public service derives actor/scope internally. Cancellation
uses a typed USER_REQUESTED reason and a scoped command identity. Same command
and task returns the original receipt before retention capacity is checked.
Reusing it for another task conflicts. Cancellation and confirmation/reservation
serialize through the same protected case boundary.

| Observation at cancellation | Immutable receipt | Business behavior |
| --- | --- | --- |
| No committed intent | cancelled_before_commit | Set case cancelled, expire pending waits and atomically complete cancelled with no mutation identity |
| Intent exists and dispatch_count is zero | cancelled_before_dispatch | Keep immutable intent, close any current attempt and complete cancelled without apply |
| Any prior dispatch reservation | requested_best_effort | Record request and case flag, preserve pending control/effect truth until reliable result or uncertainty |
| Final outcome already exists | already_terminal | Retain original outcome/event and add cancellation receipt |

Cancellation during an active read-only inquiry does not erase its known inquiry
result or close its attempt prematurely. It prevents a new booking mutation and
keeps the continuation cancelled. A later known mutation success remains success
with a requested_best_effort observation. Cancellation is never a refund,
compensation or supplier rollback promise.

## Completion and receiver delivery

The final effect disposition, business_outcomes row, immutable completion_events
row and initial completion_deliveries row commit together. A failed transaction
publishes none of those final facts. A lost return after commit is recovered by
reading the same completion, without another mutation attempt.

Business outcome, delivery and human acknowledgement are separate dimensions:

- SUCCEEDED contains exact supplier result evidence. FAILED contains a definitive
  safe failure. UNCERTAIN preserves an unresolved possible effect. CANCELLED
  requires positive evidence that mutation was prevented.
- PENDING/DELIVERING/DELIVERED/EXHAUSTED describe completion transport only. A
  failed or exhausted delivery cannot change a successful business outcome.
- DELIVERED proves this cooperating receiver accepted the canonical event. It
  does not establish a live conversation, spoken response, browser playback or
  human acknowledgement.

Before first receiver I/O, delivery binds its immutable receiver_id in PostgreSQL.
All later attempts require the same receiver, including after a lost
acknowledgement. A mismatched receiver is rejected before attempt consumption.
CompletionDeliveryWorker performs one bounded attempt outside the database
transaction. A receiver/storage failure records bounded exponential backoff. A
crash after receiver success leaves DELIVERING recoverable with the same event
and target. Receiver deduplication makes the retained logical event unique even
when transport retries more than once. Explicit rerouting is deferred.

## Setup and demonstration

Run with the frozen interpreter from the repository root. Preserve existing
local settings and volumes:

```sh
.venv/bin/python local-setup/stack.py init
.venv/bin/python local-setup/stack.py start
.venv/bin/python local-setup/stack.py prepare-postgres
.venv/bin/python local-setup/stack.py migrate-postgres
```

migrate-postgres prepares a STAGING v1 target for controlled cutover. It does not
activate an unfinished import. For a deliberately selected ACTIVE application
schema, first apply the owner-only v2 upgrade, then the v3 effects upgrade.
Do not run these two upgrades against the fresh STAGING target:

```sh
.venv/bin/python local-setup/stack.py upgrade-postgres
.venv/bin/python local-setup/stack.py upgrade-effects
```

The regression lane and demo activate their own isolated synthetic schemas; run
these directly after role setup without upgrading the live schema:

```sh
make postgres-check
make phase-e-demo
```

The one-shot postgres_cli upgrade-effects command reads only P1_MIGRATION_*;
serving and worker operations read only runtime credentials. Do not print/source
private settings or pass credentials in command arguments. Runtime constructors
validate schema and never perform DDL. V3 is additive to v2 and preserves existing
rows, IDs, import receipts and immutable payloads. Only the existing control-state
vocabulary expands for completed/cancelled. The migration verifies constraints,
indexes and exact role grants, and rejects drift or a STAGING source.

The phase demo uses its own synthetic schema and separately persisted supplier/
receiver files. Runtime-only containers stop after external success and restart
under the same identities. It inspects supplier booking revision, local outcome,
stable completion and receiver receipt rather than relying on log narration.
The synthetic clock is not a latency measurement. The demo cleans only its owned
resources. Normal local stop/start preserves application state.

## Bounds and retention

| Resource | Default and supported bound | Exhaustion or replay behavior |
| --- | --- | --- |
| Mutation attempts per effect | 8, trusted configuration 1–100 | Manual invocations consume retained attempts; no possible dispatch means definitive exhaustion, possible dispatch remains uncertain |
| Cancellation receipts per task | 128, trusted configuration 1–10,000 | Reject new commands at capacity, preserve original replay and reads |
| Completion delivery attempts | 8, trusted configuration 1–100 | Retry same event/receiver, then EXHAUSTED without changing business truth, a last lost acknowledgement can still coexist with a retained receiver receipt |
| Delivery delay | 1 s initial, 30 s maximum, configurable up to 3,600 s | Persist next eligibility, no hidden sleeping retry loop |
| Receiver core receipts | 10,000, trusted configuration 1–1,000,000 | Refuse new events at capacity, replay retained events first |
| Receiver diagnostic projection | 100, trusted configuration 1–1,000 | Bound/prune diagnostic rows only, retain canonical dedup receipts |

Core mutation attempts, cancellations, outcomes, events, delivery routing and
supplier/receiver deduplication receipts are retained. PostgreSQL runtime roles
have no DELETE grants on those records. The sink prune_diagnostics operation
removes only a separate display projection. A late event replay after pruning
returns the original receiver receipt and cannot recreate a logical completion.
Production cleanup requires a separate replay-horizon/tombstone design. Current
limits are explicit lab safety bounds, not measured storage or throughput SLOs.

## Observability and verification

Fixed producer events cover mutation claim/reservation, supplier application or
reconciliation, cancellation, completion and delivery. Logs exclude payloads,
SQL parameters, identities, booking values, credentials and raw exception text.
Typed failures distinguish validation/conflict, dependency failure, definitive
supplier rejection, original deadline, bounded exhaustion and ambiguous outcome.
Specific effect failure codes map to the existing continuation error vocabulary;
receiver failure never changes it. Telemetry exceptions cannot replace accepted
results or original errors.

CaseTelemetry measures real authenticated cancel/effect/completion/delivery calls
alongside existing case operations. Its fixed 16 operation names and three
outcomes allow at most 48 label combinations and 816 counter/histogram series.
It provides local render() output. Counters are process observations and reset on
restart; the retained ledger is authoritative. Phase E itself did not add export.
G later adds bounded filtered application/SDK spans inspected via raw Jaeger v3
trace data; see [observability](observability.md) for the actual coverage. H1 adds
observed inquiry latency and API/worker resource measurements. The later H2
restart/slow-dependency/saturation/shutdown and selected provider_real v2 media
gates passed. Human-delivery acknowledgement, physical quality and production
capacity remain unqualified; local_real is a separately unqualified profile.

Unit and real PostgreSQL tests cover exact provider/result binding, uncertainty,
claim/reservation crash distinctions, stale generations, cancellation races,
atomic completion rollback and lost returns. Independent supplier and receiver
process tests cover external success before local acknowledgement. Tests also
exercise backoff/caps, receiver-target swapping, privacy, permission/schema drift,
capacity replay and late replay after diagnostic pruning. Required missing setup,
skips, zero tests and timeout remain non-passing. See the phase work item for the
final observed commands/results. F leases and the
[G local native/media/UI gate](work-items/0013-p1-phase-g-conversation-and-showcase.md)
are subsequent contributions. The measured H1 baseline contributes to S-I06 and
the first P1-I27 workload slice. I26 installed-consumer/artifact/API review, current
H2 and selected I28 provider_real v2 inference completed the local P1 V1 release.
The [release handoff](work-items/0019-p1-phase-h-release-qualification.md) owns exact
qualification and limits; the [implementation plan](implementation/p1-agent-continuity.md)
keeps P2/P3 planned and local_real independently unqualified.
