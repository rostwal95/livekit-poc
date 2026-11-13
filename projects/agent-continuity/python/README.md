# Agent Continuity Python distribution

Status: Active
Last reviewed: 11 November 2026

## Overview

The standalone agent-continuity distribution retains the continuity_lab import
name and existing persisted formats. It owns durable inquiry and managed case
behavior; application services and the harness are separate consumers.

## Implementation status

The base installation supports the explicit SQLite inquiry subset without third
party dependencies. The postgres extra supplies the existing managed PostgreSQL
case boundary. The telemetry extra supplies optional bounded trace export. Runtime
services do not migrate storage or infer mutation consent.

| Import surface | Supported responsibility |
| --- | --- |
| continuity_lab.api | Validated request/result values, explicit SQLite migration, M1 compatibility, inquiry store/async port and safe diagnostic codes |
| continuity_lab.postgres_api | Authenticated credential-bound managed submit/get/cancel and separate controller quote/confirmation operations |
| continuity_lab.work_api | Opt-in scoped opaque read-only accepted-work submit/find/get/cancel and immutable verified scope; accepted is not an issued attempt or completed action |
| continuity_lab.work_admin | Explicit v1 install, v2 issued execution upgrade and v3 result delivery/action and v4 generic result-feed upgrades; no runtime DDL or booking-schema upgrade |
| continuity_lab.execution_api | Scoped issued read-only attempts and immutable result observations on v2–v4 |
| continuity_lab.delivery_api | Bound result-delivery preparation, possible-call marker and known receiver receipts on v3/v4 |
| continuity_lab.result_feed_api | Source/scope-bound result-only pages and immutable historical references on explicitly upgraded work v4 |
| continuity_lab.receiver_api | Explicitly initialized private cooperating receiver with immutable scoped delivery receipts; no send transport or human ACK |
| continuity_lab.action_api | Atomic work-result eligibility plus exact current case-authority intent commitment with scoped replay |
| continuity_lab.case_control_api | Separate trusted exact-case read/revise/confirmation operations over existing booking v4 |
| continuity_lab.testing | Explicit independent synthetic supplier and one-inquiry fixture worker; no production supplier or generic handler claim |

The application provides trusted scope to the SQLite compatibility API. The
managed client authenticates its configured token for every call and accepts no
caller scope, actor or arbitrary callable. Its typed receipts distinguish accepted
work, business outcome, cancellation disposition and delivery. Projection payloads
remain bounded current observations, with their existing versioned wire contract.

## Documentation

Use the [project onboarding](../README.md), [design](../Design.md),
[package work item](../../../docs/work-items/0016-p1-standalone-package.md) and
package-check evidence in the source repository. P1-I26 owns the independently installed examples, artifact
checks and API/failure review; no full release claim follows from installation.

## Requirements

Python 3.14 is supported; executed interpreter/platform evidence is
recorded by the package gate. PostgreSQL mode needs an explicitly prepared ACTIVE
v4 authority and restricted credentials. No inference provider is required.

## Commands

The installed agent-continuity-inquiry command performs explicit migration,
submission and bounded reads. agent-continuity-worker is the installed leased
worker entrypoint; its PostgreSQL fixture/setup and credentials are explicit.
Existing python -m continuity_lab module entrypoints remain available.

After installing the built local wheel, these installed entrypoints are available:

```sh
python -m continuity_lab demo
agent-continuity-inquiry --help
```

The existing M1 demo owns disposable synthetic state. The inquiry command exposes
explicit migrate/submit/get/list commands. Worker startup needs the postgres extra
and already prepared authority/fixtures. Even worker help imports the declared
postgres extra; with that extra installed, it does not connect or start work:

```sh
agent-continuity-worker --help
```

Wheels are local
build artifacts here, not a claim of publication to a package index.

Managed startup uses open_postgres_client with validated PostgresSettings,
AuthenticatedActor and BearerToken values from trusted application configuration.
This synchronous factory connects to existing ACTIVE v4 state; offload it before
serving media. Native tools expose only submit/get/cancel. prepare_quote and signal
belong to a separate authenticated controller collecting the exact confirmation.
Closing a client is not a request to cancel accepted business work.

### Opt-in immutable read-only work

The P3 prerequisite is an explicit P1-owned profile, independent of booking v4.
Choose a fresh p1_work_ schema and call work_admin.install_work_schema with owner
PostgresSettings and finite WorkLimits. A repeated install validates unchanged
catalog/grants/limits; it does not repair or refresh the baseline. Serving uses
open_work_client with restricted settings, a WorkDirectory mapping BearerToken to
WorkPrincipal and typed WorkScope(tenant_id, account_id). Trusted startup validates
the existing profile; offload this synchronous factory before serving media.

The async client has scope, submit, find, get, cancel, pending_count, metrics and
close. Methods authenticate the bound credential and accept no caller scope
override. WorkPayload contains an allowlisted read-only operation, immutable bytes
up to 16 KiB, P1-computed SHA-256 and the original UTC millisecond deadline.
Application code validates its own versioned envelope; P1 treats its bytes as opaque.
Exact scope/key replay returns original bytes/receipt/deadline before admission
capacity/expiry checks; changed bytes or deadline conflict. New input requires
1–60,000 ms remaining according to database time sampled after the admission lock.

Status remains accepted. cancel records an immutable requested-only receipt; it
does not prove execution stopped. The v1 acceptance API issues no attempt; it
continues to expose accepted status on v2. No generic worker, delivery, booking
confirmation or cleanup deletion is implemented here. Retained records and
cancel commands each default to 1,000, configurable up to 10,000 at explicit install.
The async boundary holds four I/O slots until actual thread completion, including
abandoned callers; close observes work for five seconds and fails if incomplete.
Each local connection/statement has its existing database budget; that is not a
five-second aggregate SQL-operation guarantee. Application log sinks own their
resources; sink exceptions are counted and cannot change committed work truth.

WorkError exposes a fixed profile-specific code without payload/SQL/credential
text. acknowledgement_unknown must reconcile the original key, never invent a new
operation. metrics returns process-local pending/telemetry-failure observations,
not durable totals or an exporter. The trusted harness_failpoint factory option
is for commit barriers only and must never be selected by received data.

The [acceptance phase](../../../docs/work-items/0028-p2-dispatch-and-p3-coordinator.md)
and [issued-execution phase](../../../docs/work-items/0029-p2-gateway-and-p3-issued-execution.md)
own their actual database/process/artifact evidence. The shared local runtime role is
not independent P1/P2 database-principal isolation. This explicit profile does not
change the original SQLite or booking v4 schema and worker selectors.

### Explicit issued read-only execution

Call work_admin.upgrade_work_schema_v2 with the owner and optional ExecutionLimits
only after v1 installation. The migration validates the original profile before
changing its version/known catalog, locks admission, preserves every accepted byte,
receipt, cancellation and limit, and commits atomically. A repeated upgrade validates
v2, v3 or v4 without downgrade; mismatched configuration/drift fails without refreshing its baseline. The old
install call validates v2 and never downgrades it. Runtime v1 execution startup fails
closed without DDL; existing acceptance/read/replay/cancel works on all four known versions.

Use execution_api.open_execution_client with the same restricted settings and
credential directory. Public methods are issue(work_id, owner_id, command_id),
find_issue(command_id), complete(attempt, body), result(work_id, attempt_id), observe
and close, all using keyword arguments. issue returns Issuance(attempt, created).
Only created=true may initiate invocation; replay returns the exact original grant
even after expiry, cancellation or later attempts. acknowledgement_unknown requires
find_issue on the original command, never a new command or automatic invocation.
P1 issues UUID attempt/owner identity, number, epoch and absolute lease together
with the complete original accepted record. Wire attempt labels do not issue it.

The defaults are two logical active leases per schema, three attempts per work and
10,000 ms per lease, clipped to the original deadline. Owner-selected limits are
1–4 active leases, 1–3 attempts and 100–30,000 ms leases. Admission uses the existing
protected singleton and database time after locks. No new issuance follows requested
cancellation, business expiry, active-lease capacity, attempt exhaustion or an
already eligible recorded result. There is no autonomous selector/retry loop or
lease renewal; caller cancellation and transport failure do not assert remote stop.

complete snapshots the full grant before awaiting and accepts 1–8,192 opaque result
bytes only for an exact persisted grant. One immutable body/digest/timestamp and
disposition is retained per attempt. Changed result bytes conflict. Dispositions are
eligible_at_commit, cancelled, expired, superseded and lease_expired. The first is
only P1 eligibility at commit; P3 must validate semantics and current-case authority.
Old epochs can retain historical results but cannot replace a newer result or become
eligible. An eligible result remains recorded after later cancellation/deadline;
observe also returns the current requested-cancellation flag separately. Result ACK
uncertainty reconciles result on the same issued ID. Runtime cannot rewrite/delete
grants/results, change limits or execute DDL. No result retention cleanup is implied.

The issued client uses the same four actual I/O slots, fixed safe WorkError codes,
contained logs and five-second cleanup observation as the acceptance API. Slots
survive canceled waiters. Replayed commands/reads remain available at logical
capacity. Active lease bounds are authority limits, not a claim that a paused remote
process has physically stopped. This is the P3-I07A prerequisite, not completed P3
execution recovery, delivery, current-case action or media qualification.


### Explicit result delivery and guarded case action

After known v2 setup, call work_admin.upgrade_work_schema_v3 through its migration
owner. The atomic extension adds four INSERT-only tables and preserves accepted
input, cancellations, issued grants, result bytes and original limits. Repeating
v1–v4 administration validates the known current profile without downgrade or
catalog repair. Runtime v1/v2 clients remain compatible; new delivery/action clients
require v3 or v4. Each work can own at most one delivery intent, one possible marker,
one receipt and one guarded action. These identities are retained, not pruned,
and their total is bounded by the existing finite accepted-work limit.

Use delivery_api.open_delivery_client with the same credential-bound settings.
prepare(work_id, attempt_id, result_sha256, receiver_id, recipient_id) binds the
known eligible stored result bytes and exact receiver/recipient before I/O.
Changed bindings conflict. begin(intent) revalidates work cancellation/deadline
and result eligibility, then records possible external acceptance. Only its
created=true result permits a new accept call. An existing possible marker uses
lookup only; absent evidence remains unknown. Later phases own retry/outbox work.
record_receipt(intent, receipt) retains an exact known receipt even after later
cancellation/expiry. Receiver acceptance is neither playback nor human acknowledgement.

receiver_api.initialize_result_receiver explicitly creates a private mode-0600
SQLite receiver; open_result_receiver never creates schema. Its receiver UUID and
finite scope/recipient bindings are trusted startup configuration. accept/find
require the exact immutable intent. Core receipts deduplicate before the persisted
capacity check and survive process restart. Defaults retain 1,000 records; owner
initialization allows 1–10,000, and the configured binding tuple holds at most 64
unique entries. Four actual I/O slots and five-second close observations retain
threads after waiter cancellation. No background delivery, HTTP listener or
notification action is introduced by this receiver.

The new case_control_api opens a separate credential-bound trusted controller for
exact case reads, compare-and-set revise and ordinary exact confirmation. P3 uses
action_api.open_action_client for its result-dependent path. That factory binds a
work credential to an explicit case actor/credential and distinct case/work
schemas on the exact same local SQL target. No command body can choose that actor,
scope, database or schema. authorize receives a stored work/attempt/result digest,
expected revision and independent typed exact Confirmation. It locks booking
admission, then work admission, then case/control rows; the case authority samples
DB time after locks and validates current exact consent. The guarded receipt and
case intent commit atomically. A cancelled/expired work result or stale quote
cannot win this transaction. Known receipt replay returns original facts after
later expiry/cancellation; changed work/result/confirmation/bindings conflict.
Unknown acknowledgement is inspected with find_action/action under the original
identity, never resubmitted as a new logical action. Existing supplier workers
execute the original committed intent separately, outside SQL transactions.

These surfaces use fixed safe codes, bounded owned I/O and telemetry containment.
All factories/initializers are synchronous trusted startup, not a conversational
turn. The [completion phase](../../../docs/work-items/0030-p2-agent-recovery-and-p3-completion.md)
owns actual test/proof scope; no semantic policy parsing, model consent, second
execution owner, automatic recovery scheduler or production-capacity claim is added.

### Explicit scoped result feed

After explicit v3 setup call work_admin.upgrade_work_schema_v4 with the owner. It
locks existing admission, adds only three feed tables and adopts existing immutable
results in deterministic recorded-time/work/attempt order. adopted_history does
not claim original commit order. Before-commit failure or actual owner process
loss rolls back the complete upgrade; uncertain ACK reconciles by repeating the
same upgrade. Repeat never repairs data or rotates source/event IDs. All original
accepted, cancellation, grant, result, delivery and action identities/bytes remain.
Booking v4 and SQLite are separate formats.

Use result_feed_api.open_result_feed_client with existing restricted settings,
WorkDirectory and BearerToken. The client exposes verified scope, stable source_id,
read(after=None,limit=25), pending_count, metrics and close. None begins sequence 0;
limits are 1–100. ResultFeedCursor(source_id,scope,sequence) binds profile incarnation
and account; wrong source/scope and ahead-of-head cursors fail. Empty pages retain
the cursor; explicit rewind is allowed. high_watermark is own-scope only. A client
opened before profile recreation rejects the new source; restored/branched database
incarnation rotation is not qualified.

Each ResultFeedEvent references event/work/attempt IDs, original issue_command_id,
result SHA/time/disposition and live/adopted_history origin; it duplicates no result
body. Read original historical grants through execution_api.find_issue and exact
result(work_id,attempt_id). Live event/head/result commit atomically under existing
admission locking; result replay emits nothing. Per-scope sequences are contiguous
committed facts. Sequence datatypes accept signed-int64; retained events are bounded
by the original accepted-work cap×attempt cap, at most 30000, and scope heads by
accepted records. Runtime can only insert events and update the head sequence;
source identity/event bytes cannot be rewritten or deleted by the runtime role.

Pages are read-only with no ACK, cancel event, background retry, action or delivery
permission. A later work/case change does not refresh an earlier P3 observation.
The same four retained actual I/O slots, fixed safe WorkError boundary and
five-second close observation apply. Factory startup is synchronous trusted
composition to offload before media turns. The
[phase handoff](../../../docs/work-items/0032-linked-confirmation-and-result-projections.md)
records source-level, actual PostgreSQL and fresh installed-artifact evidence,
selected local qualification and remaining product boundaries.

## Validation

The opt-in package gate builds a source distribution and wheel, rebuilds from the
source distribution and runs isolated installed consumers. Unit tests cover the
typed surface and lifecycle failures without rebuilding artifacts on every run.

Run the explicit host-tooling gate from the ecosystem checkout and frozen
environment; the harness is not distributed inside this product wheel:

```sh
.venv/bin/python -m harness.package_check
```

Prepare the exact pinned build/runtime dependency cache before this offline gate.
Missing cached setup is a failure. The gate verifies source/sdist/wheel payload
equality, declared extras, type metadata and private retained artifacts. Fresh
virtual environments use isolated interpreters and no repository path injection.
Their SQLite consumer preserves a preexisting M1 task through explicit migration,
persists a real read-only supplier result, replays its original identity and rejects
changed content. A separate real thread proves bounded async ownership. The
postgres-extra consumer reproduces a controlled loopback startup failure; positive
PostgreSQL-store and platform evidence run in their declared integration lanes.

Call close or use the async context manager. Cancelling a waiter propagates
CancelledError while actual synchronous work retains capacity. A close timeout
reports incomplete cleanup and does not stop the thread or undo a write; retain
ownership and close again after it finishes. New operations on a closing/closed
boundary fail with execution_port_closed. safe_error_code selects only a fixed
diagnostic vocabulary; do not serialize exception arguments, causes, request data
or credential-bearing configuration. It grants no retry or mutation authority.

## Next milestone

P1-I26 is complete for the tested Python 3.14 macOS and Linux ARM64 environments:
host direct/rebuilt artifacts, isolated installed consumers, independent API/failure
review, actual PostgreSQL startup and genuine native/browser consumer passed.
The [package work item](../../../docs/work-items/0016-p1-standalone-package.md) owns
those results. Remaining P1 media/real-inference and complete release assertions
require separate evidence; complete P2/P3 acceptance remains pending. Source payload equality does not
claim byte-identical archives, publication or untested platform support.
