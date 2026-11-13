# Exact consent and durable continuation guide

Status: Active
Last reviewed: 10 November 2026

## Overview

P1 Phase D implemented P1-I11 through P1-I14 on PostgreSQL v2: case authority,
exact quote/confirmation, atomic intent/dispatch commitment, durable waits and
signals, and finite retry/deadline policy. Phase E implements P1-I15 through
P1-I18 on PostgreSQL v3: supplier-bound mutation, cancellation and durable
completion delivery, with its [final gate](work-items/0011-p1-phase-e-effects-and-completion.md)
passed. All continuation state is keyed to the original task. A successful inquiry and a completed booking change are different
facts. Phase F adds v4 leases and bounded workers; G adds a separate scoped
managed-case UI and native scripted conversation consumer. Original SQLite M1
intake and transport diagnostics remain independently available.

Cases receive a distinct immutable case_id; task_id remains the original workflow
identity. This subset binds one case to one task; revision, replay and restart
preserve both. A future multi-workflow case association must be explicit.

## Public boundaries

| Boundary | Purpose | Authority and limitations |
| --- | --- | --- |
| CaseAuthorityPort / PostgresCaseAuthority | Enroll/read/revise current case; validate quotes and commit exact intent | Trusted application actor; original tasks/payload/effect unchanged |
| ScopedCaseService | Authenticate case commands, cancellation and effect/completion/delivery views; derive actor/scope from TokenDirectory | No actor/scope override or quote-publishing method; absent effects configuration is explicitly unsupported |
| AsyncCaseService | Finite offload of the same authenticated service | Four default slots; cancelled callers retain capacity until real work finishes |
| PostgresLifecycle | Manage the original inquiry, persist waits/signals and advance due work | Existing execution owner; no parallel durable queue |
| ManagedInquiryWorker | One bounded lookup-first inquiry attempt | V2/v3 cooperative session slot; v4 explicit task lease and same-transaction epoch guard |
| PostgresEffects / MutationWorker | Execute committed exact supplier proposals, retain cancellation and atomically complete the business outcome/event | V3 cooperative slot; v4 current explicit lease/epoch, original effect identity and supplier cooperation |
| Completion delivery boundary | Deliver a stable immutable completion event to an independent cooperating receiver | Receiver identity binds before first attempt; delivery is separate from business outcome and human acknowledgement |
| CaseTelemetry | Observe real public operations | Private metric registry; fixed labels and safe producer fields |

QuoteSnapshot is immutable and versioned. It binds quote ID, original task ID,
current case revision, booking reference, requested check-in date, integer amount
in minor units, currency and absolute UTC expiry. Supported fixture currencies
are USD, EUR, GBP and INR. New v2 quotes additionally bind the immutable case ID,
supplier identity and expected supplier booking revision. All three bindings
are required together; supplier revision is an exact nonnegative integer with
room for its successor. Floats, boolean amounts/revisions, unknown/extra fields
and unsupported payload versions are rejected. Legacy v1 bytes and known
read/replay receipts remain unchanged after v3 upgrade; they cannot authorize
a new mutation. Reissue an exact v2 proposal instead of filling bindings from
current supplier state. Existing intake confirmation remains investigation-only.

A trusted synthetic proposal producer calls publish_quote. It must provide a
fresh quote for the current case snapshot; the old inquiry effect is never reused
as evidence for revised dates. ScopedCaseService does not expose proposal issuance.
Confirmation contains the exact quote and explicit=True. Free-text/model summaries
cannot substitute for it. This is a trusted explicit application command, not a
human-presence attestation. The G profile collects exact quote/revision approval
through a separate authenticated panel action; no native model tool can confirm.
The synthetic browser test proves that control path, not physical human presence.
A production adapter must preserve explicit user action and the same authority.

## Transaction and replay contract

1. Scope/owner lookup uses the actor authenticated by the application. Unknown,
   other-account and another-owner case IDs have the same unavailable response.
2. Admission lock, case row and continuation/wait rows have one consistent order.
   Clock/expiry checks happen after acquiring locks. Supplier/model/network work
   never occurs in this transaction.
3. A new command validates current revision/quote, exact confirmation, owner,
   cancellation flag, quote expiry and managed business/wait deadline/state.
   A new v2 mutation intent requires an existing managed business deadline.
4. Immutable confirmation, action intent, stable effect ID and dispatch event
   commit together. Managed continuation/wait disposition updates in that same
   transaction. An intent is a commitment record; supplier mutation and
   completion delivery run separately through Phase E workers, outside this
   transaction. Phase D historical demonstrations stop at commitment.
5. Same command/content returns the original committed receipt even after expiry;
   altered command replay conflicts. Different valid commands for an already
   committed exact proposal cannot create another logical effect/event.
6. Revision and commitment serialize. Revision first rejects stale confirmation;
   commitment first rejects in-place rewrite and requires a new request path.
   Revision is compare-and-set: after an ambiguous acknowledgement, inspect the
   current revision before submitting another revision command.

## Waits and retry policy

Signals retain typed actor/task/quote content under a scoped event identity. An
early signal remains persisted before its wait exists. Arm a wait with a stable
UUID, exact quote and absolute deadline; advance consumes one current matching
signal and commits its intent in the same transaction. Same signal replay dedups;
altered event content conflicts. Unrelated/stale/expired signals cannot advance
work. Deadline is effective after process/container loss without a sleeping task.
Publishing a replacement proposal expires the prior pending wait and returns
continuation to inquiry_complete without extending its original business
deadline. A fresh exact signal can then advance the new wait; old signals cannot
confirm the replacement. Replaying an old publication never restores it as current.

| Observation | Persisted disposition | Eligibility |
| --- | --- | --- |
| Positive evidence of no dispatch and transient failure | retry_wait with next_attempt_at | Bounded exponential delay; strictly before original deadline |
| Permanent rejection | failed | No retry |
| Finite attempt budget exhausted | failed / retry_exhausted | No retry |
| Business deadline reached before a safe dispatch | failed / deadline_expired | No dispatch or renewed deadline |
| Ambiguous dispatch or failed reconciliation of a prior possible effect | uncertain / ambiguous_outcome | No automatic resend; retain evidence |
| Successful lookup after deadline | Actual known inquiry result | Persist truth; deadline cannot erase an observed effect |

The default policy is three attempts, one-second initial delay and thirty-second
maximum delay; trusted configuration permits 1–100 attempts and delays up to one
hour, within the underlying execution attempt cap. Each worker invocation makes
one attempt; explicit later invocation evaluates persisted eligibility. It checks
remaining deadline again after lookup and immediately before dispatch. A clock
check cannot reverse a request already accepted by a supplier.

Legacy start/recover/finish methods reject managed execution attempts, preventing
bypass of continuation policy. SQLite continues to support the original inquiry
subset; it gains no waits/retries/case scheduler.

## Effects, cancellation and completion

The [effects/completion guide](effects-and-completion.md) owns the detailed
supplier, receiver, worker and replay contract. This section connects that
boundary to case authority and continuation.

Mutation uses the immutable committed supplier/revision binding and a stable
effect identity. Persist possible dispatch before making the supplier call.
Reliable lookup plus stable-key deduplication can reconcile a lost response;
missing cooperation retains an uncertain outcome and forbids an unsafe resend.
Known supplier results survive later cancellation or deadline expiry. Quote
expiry is checked when consent commits; it does not retroactively rewrite an
intent. A fresh dispatch still checks the original business deadline.

Cancellation commands retain their original scoped identity and disposition:
before commitment or positively before dispatch, cancellation prevents apply;
after possible dispatch it is best effort and cannot claim remote reversal.
Cancellation during an in-flight read-only inquiry preserves an observed success
or closes a failed attempt without scheduling another retry.

Final business outcome, immutable completion event and pending delivery commit
together. A terminal lifecycle remains completed/cancelled/failed/uncertain when
advance replays the committed intent. Delivery has its own bounded policy and
receiver binding. Receiver deduplication survives diagnostic pruning; core
receipts are retained. Delivery success is not proof of human acknowledgement.

## Leased workers on PostgreSQL v4

Phase F extends the same authority with retained per-task execution leases and a
persisted coordination policy. A worker passes an explicit LeaseGrant into
PostgresLifecycle/PostgresEffects. Inquiry claim/finish, mutation claim/reservation/
finish and outbox claim/finish validate the task/scope/owner/epoch and stored expiry
inside the existing protected transaction. Database clock_timestamp is sampled
after locks; process wall clocks cannot extend lease authority. Release retains the
epoch, takeover increments it, and stale renewal/release/writes fail closed.

Public authenticated case/read/controller commands keep their actor/revision
contract and are distinct from worker lease ownership. A current lease grants no
consent and does not fence provider I/O. Known supplier truth after business
cancellation/deadline still requires a current owner. A paused former owner cannot
commit it after losing its epoch; fresh cooperating lookup or explicit uncertainty
handles the external boundary. Terminal uncertainty is not reopened automatically.

The default owner-installed policy is 1,000 outstanding accepted workflows, four
active leases, 10,000 retained task identities and 30 s leases. Outstanding includes
accepted/running base inquiry without a final business outcome, including uncertain
inquiry awaiting manual review, or a nonterminal managed control such as wait/intent.
It is not the number of runnable queue entries. A terminal effect outcome, including
UNCERTAIN, leaves outstanding capacity; an unresolved inquiry does not. Reads and
known replay remain available when new work or leases are refused.

PostgresWorkQueue selects current due inquiry/wait/mutation/delivery state and
acquires its task lease atomically. It does not own another persisted queue or
acknowledge work in process memory. Stale/legacy signals and exhausted epochs must
not prevent eligible current work from progressing. The opt-in p1-workers profile
runs the actual bounded P1 pull worker: one supervised POSIX child per parent,
step timeout at most min(15 s, lease duration / 2), default 5 s shutdown drain,
then bounded kill/reap before release. Existing named fixtures and database state
survive normal restart. Consult the Phase F work item and local setup guide for
the deliberately selected ACTIVE v4 schema and private fixture procedure. The
[lease/worker guide](leases-and-workers.md) owns the full runtime contract.

Upgrade v4 explicitly from ACTIVE v3 with upgrade-coordination under the migration
principal. Finish unmanaged RUNNING v3 inquiries first; serving code cannot rewrite
legacy attempts as leased work or run DDL. Managed running state can recover under
v4. Existing v1-v3 read/replay and supported legacy execution remain tested, while
old unmanaged start/recover/finish are unsupported on v4.

## Setup and demonstration

Use the frozen project interpreter from the repository root. Existing setup and
credentials are preserved:

```sh
.venv/bin/python local-setup/stack.py init
.venv/bin/python local-setup/stack.py start
.venv/bin/python local-setup/stack.py prepare-postgres
.venv/bin/python local-setup/stack.py migrate-postgres
make postgres-check
make phase-d-demo
```

The demo creates only its own synthetic schema/files. It performs an explicit
SQLite-to-PostgreSQL cutover and owner-only v2 upgrade, executes a safe transient
inquiry retry, and then uses two separate disposable runtime-only containers.
The first persists an early confirmation signal and waits, exits, and leaves no
process/application file holding the wait. The second consumes once under the
original task, checks a second expired wait and verifies exact intent replay.
It checks installed module hashes outside the source tree, unchanged fake booking,
one dispatch event and observed metrics. It removes only its own schema/containers;
the live M1 database and named volumes stay unchanged. The scripted demo clock is
synthetic, not a latency/capacity measurement or proof of a human interaction.

For a deliberately selected ACTIVE v1 application schema, postgres_cli upgrade
performs the owner-only v2 upgrade. The separate postgres_cli upgrade-effects
performs ACTIVE v2 to v3; repeated upgrades validate the existing catalog without
downgrading it. Both read only P1_MIGRATION_* credentials; runtime commands read
only P1_POSTGRES_*. Serving processes never perform DDL, and v1 consent history
is not backfilled during the upgrade.
The local stack upgrade-postgres action applies that one-shot upgrade to its
configured schema and refuses a STAGING target. It never activates an unfinished
cutover. The default migrate-postgres action still prepares v1 for cutover.
Never source or print private credential files or put passwords in arguments.

## Resources, retention and observability

| Resource | Default bound | Exhaustion and replay |
| --- | --- | --- |
| Retained cases / controls | 10,000 each | Reject new identities; preserve existing reads/replay |
| Quotes / confirmation receipts per case | 32 / 128 | Retain authority/effect protection; reject new records |
| Signals / waits per execution | 100 / 8 | Existing exact replay remains available |
| Mutation attempts / cancellation commands per case | 8 / 128 | Finite manual mutation recovery; preserve prior cancellation replay |
| Completion delivery | 8 attempts; 1 s initial / 30 s maximum delay | Persist due time; delivered/exhausted state remains readable |
| Async I/O | 4 operations; 0.05 s admission; 10 s drain | Capacity error; cancellation does not release a running thread's slot |
| PostgreSQL | 5 s connect/statements; 1 s lock wait | Explicit bounded rejection or storage failure; no hidden retry |

No core cleanup or TTL API exists. Fixture diagnostic pruning must preserve
supplier/receiver receipts. Retain replay, confirmation, signal, consumption,
cancellation, outcome/event and effect identities within these finite lab bounds.
Business expiry cannot make an accepted identity new. Production cleanup needs a
separate replay-horizon/tombstone design and late-retry tests before deployment.
Task-leading indexes support per-task cap/history queries; bounds are configured
limits, not measured production capacity.

CaseTelemetry emits continuity_case_operations_total and
continuity_case_operation_duration_seconds with operation/outcome labels only.
Thirteen operation names and three outcomes bound label combinations to 39,
including cancel, effect, completion and delivery. Counters
reset with the process; durable records remain the truth. The registry is local
to the service instance and can be scraped through render(); no new HTTP exporter
or complete distributed trace is claimed. A telemetry failure cannot alter a
business result or mask its original exception.

JSON producer logs contain fixed event/code and optional allowlisted operation/
outcome. Tokens, actor/task/quote values, raw SQL, payloads and exception strings
are excluded. Stable errors include stale_revision, invalid_confirmation,
quote_expired, deadline_expired, intent_committed, execution_not_found,
idempotency_conflict, capacity_exhausted and the existing storage/schema codes.
Use synthetic operator results and retained state to investigate; retry advice
cannot authorize a new confirmation or uncertain external effect.

## Verification and next boundary

The explicit PostgreSQL gate includes populated-v1 upgrade interruption/replay,
immutable-role/constraint/index checks, exact rejection and useful confirmation,
revision races, signal dedup/early/late delivery, finite retries, ambiguity,
process loss and expiry. Full fast validation retains prior SQLite, API and RTC
regressions. The local container demo and actual RTC smoke are separate evidence.
Required skips, missing setup, zero tests or timeout never pass.

Phase E implementation and targeted tests now cover supplier-bound v2 consent,
actual v2-to-v3 migration preservation, mutation/cancellation/outbox contracts and
known inquiry results after cancellation. Its final combined gate passed;
exact observed results belong in the Phase E work item. Phase F implements
P1-I19 through P1-I21: database-time leases, stale external-call safety and bounded
worker deployment/restart. Its
[combined gate](work-items/0012-p1-phase-f-leases-and-deployment.md) has passed.
Phase G implements P1-I22 through P1-I25 with its inspected local combined
gate recorded in the [Phase G work item](work-items/0013-p1-phase-g-conversation-and-showcase.md). The opt-in business profile
connects a scripted native AgentSession to managed PostgreSQL work, bounded
authenticated case projections and separate exact quote approval. Explicit
media End retires the room; a fresh native consumer reloads the same owned
task. This is actual local browser/native media, not physical microphone
capture, live-model quality, automatic network-loss recovery or remote CI proof.
The public RoomIO readiness barrier precedes controls/speech, and SDK alternate
session hosting is disabled. The
[H1 workload work item](work-items/0014-p1-phase-h-workload-baseline.md) records the
locally measured seeded inquiry baseline for S-I06 and the first P1-I27 slice.
The current H2 restart/slow-dependency/saturation/shutdown workload, installed
host/Linux artifacts, standalone API/consumer review and selected provider_real v2
media qualification passed. The [Phase H release handoff](work-items/0019-p1-phase-h-release-qualification.md)
records the qualified local P1 V1 scope and exact evidence. local_real remains
unqualified under its original limits. Production identity, physical capture,
human hearing and production capacity remain separate; hosted CI/publication are
outside this local POC, and complete P2/P3 acceptance remains pending.
