# Agent Continuity Python distribution

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Explain how to install the standalone package and use its public API and installed commands |
| Audience | Developers who install the wheel and use its public API or installed commands |
| Scope | Installed package surfaces, extras, entrypoints and the package gate; excludes application services and the harness |
| Owns | The package's typed public imports, extras, installed commands and isolated artifact gate |
| Related | [Project onboarding](../README.md) · [Design](../Design.md) · [Package work item](../../../docs/work-items/0016-p1-standalone-package.md) · [Phase H release work item](../../../docs/work-items/0019-p1-phase-h-release-qualification.md) |

## Overview

The standalone `agent-continuity` distribution keeps the `continuity_lab` import
name and the existing persisted formats. It owns durable inquiry and managed case
behavior. Application services and the harness are separate consumers.

This README ships inside the package. It is for developers who install the wheel
and use its public API or installed commands. Commands under [Commands](#commands)
assume an environment where the package is installed. The package gate under
[Validation](#validation) is repository tooling that runs from the ecosystem
checkout.

Contents:

- [Implementation status](#implementation-status): installation extras, import
  surfaces and trust boundaries.
- [Requirements](#requirements): Python version and storage prerequisites.
- [Commands](#commands): installed entrypoints.
- [Python API usage](#python-api-usage): the managed client, work profile versions
  1 to 4, and closing boundaries.
- [Validation](#validation) and [Next milestone](#next-milestone).

### Terms used in this README

| Term | Meaning |
| --- | --- |
| M1 | The original SQLite confirmed-investigation intake, which `continuity_lab.api` keeps compatible |
| Booking schema | The PostgreSQL case-authority schema behind `postgres_api`, `case_control_api` and the case side of `action_api`. Its version line runs from v1 to v5 |
| Work profile | The separate opt-in schema line, v1 to v4, behind `work_api` and the APIs built on it |
| Owner | The migration principal that installs or upgrades a schema; serving code uses restricted runtime settings |
| DDL | Data definition language (schema changes); only explicit owner calls run it |
| ACK | Acknowledgement |
| P1-I26, P3-I07A | Implementation task IDs from the source repository's plans |

## Implementation status

| Capability | Status | Evidence |
| --- | --- | --- |
| SQLite inquiry subset, base installation | Qualified | P1-I26 installed SQLite consumer; [package work item](../../../docs/work-items/0016-p1-standalone-package.md) |
| Managed PostgreSQL case boundary, `postgres` extra | Qualified | P1-I26 actual PostgreSQL startup; [package work item](../../../docs/work-items/0016-p1-standalone-package.md) |
| [Work profile v1](#work-profile-version-1-read-only-accepted-work): read-only accepted work | Qualified | Selected gate in the [acceptance phase](../../../docs/work-items/0028-p2-dispatch-and-p3-coordinator.md) |
| [Work profile v2](#work-profile-version-2-issued-read-only-execution): issued read-only execution | Qualified | Selected gate in the [issued-execution phase](../../../docs/work-items/0029-p2-gateway-and-p3-issued-execution.md) |
| [Work profile v3](#work-profile-version-3-result-delivery-and-guarded-case-action): result delivery and guarded case action | Qualified | Selected gates in the [completion phase](../../../docs/work-items/0030-p2-agent-recovery-and-p3-completion.md) |
| [Work profile v4](#work-profile-version-4-scoped-result-feed): scoped result feed | Qualified | Selected local qualification in the [phase handoff](../../../docs/work-items/0032-linked-confirmation-and-result-projections.md) |

The base installation supports the explicit SQLite inquiry subset without
third-party dependencies. Optional extras add the rest:

| Installation | Provides |
| --- | --- |
| Base | The explicit SQLite inquiry subset, without third-party dependencies |
| `postgres` extra | The existing managed PostgreSQL case boundary |
| `telemetry` extra | Optional bounded trace export |

Runtime services do not migrate storage or infer mutation consent.

### Import surfaces

| Import surface | Supported responsibility |
| --- | --- |
| `continuity_lab.api` | Validated request and result values, explicit SQLite migration, M1 compatibility, the inquiry store and async port, and safe diagnostic codes |
| `continuity_lab.postgres_api` | Authenticated, credential-bound managed submit, get and cancel, and separate controller quote and confirmation operations |
| `continuity_lab.work_api` | Opt-in, scoped, opaque read-only accepted-work submit, find, get and cancel, and an immutable verified scope. Accepted is not an issued attempt or a completed action |
| `continuity_lab.work_admin` | Explicit v1 install, the v2 issued-execution upgrade, the v3 result delivery and action upgrade, and the v4 generic result-feed upgrade. No runtime DDL or booking-schema upgrade |
| `continuity_lab.execution_api` | Scoped issued read-only attempts and immutable result observations on work profile v2 to v4 |
| `continuity_lab.delivery_api` | Bound result-delivery preparation, a possible-call marker and known receiver receipts on work profile v3 or v4 |
| `continuity_lab.result_feed_api` | Source- and scope-bound result-only pages and immutable historical references on an explicitly upgraded work profile v4 |
| `continuity_lab.receiver_api` | An explicitly initialized private cooperating receiver with immutable scoped delivery receipts. No send transport or human ACK |
| `continuity_lab.action_api` | Atomic work-result eligibility plus exact current case-authority intent commitment, with scoped replay |
| `continuity_lab.case_control_api` | Separate trusted exact-case read, revise and confirmation operations over the existing booking v4 or v5 schema |
| `continuity_lab.testing` | An explicit independent synthetic supplier and a one-inquiry fixture worker. No production supplier or generic handler claim |

### Trust boundaries

- The application provides trusted scope to the SQLite compatibility API.
- The managed client authenticates its configured token for every call. It accepts
  no caller scope, actor or arbitrary callable.
- Its typed receipts distinguish accepted work, business outcome, cancellation
  disposition and delivery.
- Projection payloads remain bounded current observations, with their existing
  versioned wire contract.

## Documentation

| Document | Purpose |
| --- | --- |
| [Project onboarding](../README.md) | P1 capability summary, authoritative links and working repository commands |
| [Design](../Design.md) | P1 implementation boundaries, state ownership and failure handling |
| [Package work item](../../../docs/work-items/0016-p1-standalone-package.md) | P1-I26 installed examples, artifact checks and API and failure review results |
| Package-check evidence | Kept in the source repository |

Implementation task P1-I26 owns the independently installed examples, artifact
checks and API and failure review. No full release claim follows from
installation.

## Requirements

| Requirement | Version or value | Notes |
| --- | --- | --- |
| Python | `>=3.14,<3.15` | Python 3.14 is supported; the package gate records executed interpreter and platform evidence |
| PostgreSQL mode | An explicitly prepared ACTIVE v4 or v5 booking authority | Needs restricted credentials; the v5 upgrade only adds a persisted mutation retry due time and its indexes |
| Opt-in work profile | Its own explicitly installed `p1_work_` schema | See [Work profile version 1](#work-profile-version-1-read-only-accepted-work) |
| Inference provider | None | No inference provider is required |

## Commands

The installed package provides these entrypoints:

| Task | Command | Notes |
| --- | --- | --- |
| Run the existing M1 demo | `python -m continuity_lab demo` | `python -m continuity_lab` keeps the existing module entrypoints; `demo` runs the M1 demo, which owns disposable synthetic state |
| Migrate, submit and read inquiries | `agent-continuity-inquiry` | Explicit migration, submission and bounded reads through its `migrate`, `submit`, `get` and `list` commands |
| Run the installed leased worker | `agent-continuity-worker` | Needs the `postgres` extra and already prepared authority and fixtures; its PostgreSQL fixture setup and credentials are explicit |

After installing the built local wheel, these installed entrypoints are available:

```sh
python -m continuity_lab demo
agent-continuity-inquiry --help
```

Worker startup needs the `postgres` extra and already prepared authority and
fixtures. Even worker help imports the declared `postgres` extra. With that extra
installed, help does not connect or start work:

```sh
agent-continuity-worker --help
```

Wheels are local build artifacts here, not a claim of publication to a package
index.

## Python API usage

### Managed PostgreSQL client

Managed startup uses `open_postgres_client` with validated `PostgresSettings`,
`AuthenticatedActor` and `BearerToken` values from trusted application
configuration. This synchronous factory connects to existing ACTIVE v4 or v5 state;
offload it before serving media.

- Native tools expose only submit, get and cancel.
- `prepare_quote` and `signal` belong to a separate authenticated controller that
  collects the exact confirmation.
- Closing a client is not a request to cancel accepted business work.

### Work profile version 1: read-only accepted work

The P3 prerequisite is an explicit P1-owned profile, independent of booking v4.

1. Choose a fresh `p1_work_` schema.
2. Call `work_admin.install_work_schema` with owner `PostgresSettings` and finite
   `WorkLimits`. A repeated install validates the unchanged catalog, grants and
   limits; it does not repair or refresh the baseline.
3. Serve with `open_work_client`, passing restricted settings, a `WorkDirectory`
   that maps `BearerToken` to `WorkPrincipal`, and a typed
   `WorkScope(tenant_id, account_id)`. Trusted startup validates the existing
   profile. Offload this synchronous factory before serving media.

**Client and payload.**

- The async client has `scope`, `submit`, `find`, `get`, `cancel`, `pending_count`,
  `metrics` and `close`. Methods authenticate the bound credential and accept no
  caller scope override.
- `WorkPayload` contains an allowlisted read-only operation, immutable bytes up to
  16 KiB, a P1-computed SHA-256 and the original UTC millisecond deadline.
- Application code validates its own versioned envelope. P1 treats the bytes as
  opaque.
- Exact scope/key replay returns the original bytes, receipt and deadline before
  admission capacity and expiry checks. Changed bytes or a changed deadline
  conflict.
- New input requires 1–60,000 ms remaining, according to database time sampled
  after the admission lock.

**Status and cancellation.**

- Status remains accepted. `cancel` records an immutable requested-only receipt; it
  does not prove execution stopped.
- The v1 acceptance API issues no attempt. It continues to expose accepted status
  on v2.
- No generic worker, delivery, booking confirmation or cleanup deletion is
  implemented here.

**Limits and resources.**

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Retained records | 1,000 by default | The work profile | Configurable up to 10,000 at explicit install |
| Cancel commands | 1,000 by default | The work profile | Configurable up to 10,000 at explicit install |
| I/O slots | Four | The async boundary | Held until actual thread completion, including for abandoned callers |
| Close observation | Five seconds | `close` | Fails if work is incomplete |
| Database budget | The existing budget | Each local connection and statement | Not a five-second aggregate SQL-operation guarantee |

Application log sinks own their resources. Sink exceptions are counted and cannot
change committed work truth.

**Errors and diagnostics.**

- `WorkError` exposes a fixed profile-specific code without payload, SQL or
  credential text.
- `acknowledgement_unknown` must reconcile the original key, never invent a new
  operation.
- `metrics` returns process-local pending and telemetry-failure observations, not
  durable totals or an exporter.
- The trusted `harness_failpoint` factory option is for commit barriers only. It
  must never be selected by received data.

The [acceptance phase](../../../docs/work-items/0028-p2-dispatch-and-p3-coordinator.md)
and [issued-execution phase](../../../docs/work-items/0029-p2-gateway-and-p3-issued-execution.md)
own their actual database, process and artifact evidence. The shared local runtime
role is not independent P1/P2 database-principal isolation. This explicit profile
does not change the original SQLite or booking v4 schema and worker selectors.

### Work profile version 2: issued read-only execution

**Upgrade.** Call `work_admin.upgrade_work_schema_v2` with the owner and optional
`ExecutionLimits`, only after v1 installation.

- The migration validates the original profile before changing its version and
  known catalog. It locks admission, preserves every accepted byte, receipt,
  cancellation and limit, and commits atomically.
- A repeated upgrade validates v2, v3 or v4 without downgrade. Mismatched
  configuration or drift fails without refreshing its baseline.
- The old install call validates v2 and never downgrades it.
- Runtime v1 execution startup fails closed without DDL. Existing acceptance, read,
  replay and cancel work on all four known versions.

**Client.** Use `execution_api.open_execution_client` with the same restricted
settings and credential directory. Its public methods are
`issue(work_id, owner_id, command_id)`, `find_issue(command_id)`,
`complete(attempt, body)`, `result(work_id, attempt_id)`, `observe` and `close`,
all using keyword arguments. `issue` returns `Issuance(attempt, created)`.

- Only `created=true` may initiate invocation. Replay returns the exact original
  grant, even after expiry, cancellation or later attempts.
- `acknowledgement_unknown` requires `find_issue` on the original command, never a
  new command or automatic invocation.
- P1 issues the UUID attempt and owner identity, number, epoch and absolute lease
  together with the complete original accepted record. Wire attempt labels do not
  issue it.

**Limits.**

The owner selects each logical bound within its allowed values:

| Option | Default | Allowed values | Description |
| --- | --- | --- | --- |
| Active leases per schema | 2 | 1–4 | An authority limit, not proof that remote work stopped |
| Attempts per work | 3 | 1–3 | Issued attempts for one accepted work |
| Lease duration | 10,000 ms | 100–30,000 ms | Clipped to the original deadline |

- Admission uses the existing protected singleton and database time after locks.
- No new issuance follows requested cancellation, business expiry, active-lease
  capacity, attempt exhaustion or an already eligible recorded result.
- There is no autonomous selector, retry loop or lease renewal. Caller cancellation
  and transport failure do not assert remote stop.

**Results.**

- `complete` snapshots the full grant before awaiting. It accepts 1–8,192 opaque
  result bytes only for an exact persisted grant.
- One immutable body, digest, timestamp and disposition is retained per attempt.
  Changed result bytes conflict.
- Dispositions are `eligible_at_commit`, `cancelled`, `expired`, `superseded` and
  `lease_expired`. The first means only P1 eligibility at commit; P3 must validate
  semantics and current-case authority.
- Old epochs can retain historical results but cannot replace a newer result or
  become eligible.
- An eligible result remains recorded after a later cancellation or deadline.
  `observe` also returns the current requested-cancellation flag separately.
- Result ACK uncertainty reconciles through `result` on the same issued ID.
- Runtime cannot rewrite or delete grants or results, change limits or execute DDL.
  No result retention cleanup is implied.

**Resources and scope.** The issued client uses the same four actual I/O slots,
fixed safe `WorkError` codes, contained logs and five-second cleanup observation as
the acceptance API. Slots survive cancelled waiters. Replayed commands and reads
remain available at logical capacity. Active lease bounds are authority limits, not
a claim that a paused remote process has physically stopped. This is the P3-I07A
prerequisite, not completed P3 execution recovery, delivery, current-case action or
media qualification.

### Work profile version 3: result delivery and guarded case action

**Upgrade.** After known v2 setup, call `work_admin.upgrade_work_schema_v3` through
its migration owner.

- The atomic extension adds four INSERT-only tables. It preserves accepted input,
  cancellations, issued grants, result bytes and original limits.
- Repeating v1 to v4 administration validates the known current profile without
  downgrade or catalog repair.
- Runtime v1 and v2 clients remain compatible. New delivery and action clients
  require v3 or v4.
- Each work can own at most one delivery intent, one possible marker, one receipt
  and one guarded action. These identities are retained, not pruned, and their
  total is bounded by the existing finite accepted-work limit.

**Result delivery.** Use `delivery_api.open_delivery_client` with the same
credential-bound settings. The delivery flow is:

1. `prepare(work_id, attempt_id, result_sha256, receiver_id, recipient_id)` binds
   the known eligible stored result bytes and the exact receiver and recipient
   before I/O. Changed bindings conflict.
2. `begin(intent)` revalidates work cancellation, the deadline and result
   eligibility, then records possible external acceptance. Only its `created=true`
   result permits a new accept call.
3. `record_receipt(intent, receipt)` retains an exact known receipt, even after a
   later cancellation or expiry.

An existing possible marker uses lookup only; absent evidence remains unknown.
Later phases own retry and outbox work. Receiver acceptance is neither playback nor
human acknowledgement.

**Private receiver.**

- `receiver_api.initialize_result_receiver` explicitly creates a private mode-0600
  SQLite receiver. `open_result_receiver` never creates schema.
- Its receiver UUID and finite scope/recipient bindings are trusted startup
  configuration.
- `accept` and `find` require the exact immutable intent.
- Core receipts deduplicate before the persisted capacity check and survive process
  restart.
- This receiver introduces no background delivery, HTTP listener or notification
  action.

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Retained records | 1,000 by default | The receiver | Owner initialization allows 1–10,000 |
| Scope/recipient bindings | At most 64 unique entries | The configured binding tuple | Trusted startup configuration |
| I/O slots | Four actual slots | Receiver calls | Retain threads after waiter cancellation |
| Close observation | Five seconds | Receiver close | Retains threads after waiter cancellation |

**Guarded case action.** The new `case_control_api` opens a separate
credential-bound trusted controller for exact case reads, compare-and-set revise
and ordinary exact confirmation. P3 uses `action_api.open_action_client` for its
result-dependent path.

- The factory binds a work credential to an explicit case actor and credential, and
  to distinct case and work schemas on the exact same local SQL target. No command
  body can choose that actor, scope, database or schema.
- `authorize` receives a stored work, attempt and result digest, the expected
  revision and an independent typed exact `Confirmation`.
- It locks booking admission, then work admission, then case/control rows. The case
  authority samples database time after locks and validates current exact consent.
- The guarded receipt and case intent commit atomically. A cancelled or expired work
  result or a stale quote cannot win this transaction.
- Known receipt replay returns original facts after a later expiry or cancellation.
  Changed work, result, confirmation or bindings conflict.
- An unknown acknowledgement is inspected with `find_action` or `action` under the
  original identity, never resubmitted as a new logical action.
- Existing supplier workers execute the original committed intent separately,
  outside SQL transactions.

These surfaces use fixed safe codes, bounded owned I/O and telemetry containment.
All factories and initializers are synchronous trusted startup, not a
conversational turn. The
[completion phase](../../../docs/work-items/0030-p2-agent-recovery-and-p3-completion.md)
owns actual test and proof scope. No semantic policy parsing, model consent, second
execution owner, automatic recovery scheduler or production-capacity claim is
added.

### Work profile version 4: scoped result feed

**Upgrade.** After explicit v3 setup, call `work_admin.upgrade_work_schema_v4` with
the owner.

- It locks existing admission, adds only three feed tables and adopts existing
  immutable results in deterministic recorded-time, work and attempt order.
  `adopted_history` does not claim original commit order.
- A before-commit failure or actual owner process loss rolls back the complete
  upgrade. An uncertain ACK reconciles by repeating the same upgrade.
- A repeat never repairs data or rotates source or event IDs.
- All original accepted, cancellation, grant, result, delivery and action
  identities and bytes remain. Booking v4 and SQLite are separate formats.

**Client.** Use `result_feed_api.open_result_feed_client` with the existing
restricted settings, `WorkDirectory` and `BearerToken`. The client exposes the
verified `scope`, a stable `source_id`, `read(after=None,limit=25)`,
`pending_count`, `metrics` and `close`.

- `None` begins at sequence 0. Limits are 1–100.
- `ResultFeedCursor(source_id,scope,sequence)` binds the profile incarnation and
  account. A wrong source or scope and an ahead-of-head cursor fail.
- Empty pages retain the cursor, and explicit rewind is allowed.
- `high_watermark` is own-scope only.
- A client opened before profile recreation rejects the new source. Restored or
  branched database incarnation rotation is not qualified.

**Events.**

- Each `ResultFeedEvent` references event, work and attempt IDs, the original
  `issue_command_id`, the result SHA, time and disposition, and a live or
  `adopted_history` origin. It duplicates no result body.
- Read original historical grants through `execution_api.find_issue` and the exact
  `result(work_id,attempt_id)`.
- Live event, head and result commit atomically under existing admission locking.
  Result replay emits nothing.
- Per-scope sequences are contiguous committed facts.
- Sequence datatypes accept signed-int64. Retained events are bounded by the
  original accepted-work cap × attempt cap, at most 30,000, and scope heads by
  accepted records.
- The runtime role can only insert events and update the head sequence. It cannot
  rewrite or delete source identity or event bytes.

**What a page does not grant.** Pages are read-only, with no ACK, cancel event,
background retry, action or delivery permission. A later work or case change does
not refresh an earlier P3 observation. The same four retained actual I/O slots,
fixed safe `WorkError` boundary and five-second close observation apply. Factory
startup is synchronous trusted composition to offload before media turns. The
[phase handoff](../../../docs/work-items/0032-linked-confirmation-and-result-projections.md)
records source-level, actual PostgreSQL and fresh installed-artifact evidence,
selected local qualification and remaining product boundaries.

### Closing boundaries and safe error codes

- Call `close` or use the async context manager.
- Cancelling a waiter propagates `CancelledError` while the actual synchronous work
  retains capacity.
- A close timeout reports incomplete cleanup. It does not stop the thread or undo a
  write. Retain ownership and close again after the work finishes.
- New operations on a closing or closed boundary fail with `execution_port_closed`.
- `safe_error_code` selects only a fixed diagnostic vocabulary. Do not serialize
  exception arguments, causes, request data or credential-bearing configuration. It
  grants no retry or mutation authority.

## Validation

| Check | Command | What it proves | Status |
| --- | --- | --- | --- |
| Package gate | `.venv/bin/python -m harness.package_check` | Artifact payload equality and isolated installed consumers; runs from the ecosystem checkout | Qualified at the P1-I26 checkpoint |
| Unit tests | The repository fast lane; see [project onboarding](../README.md#commands) | The typed surface and lifecycle failures, without rebuilding artifacts | Implemented |
| PostgreSQL-store and platform evidence | Declared integration lanes | Positive PostgreSQL startup and the tested macOS and Linux ARM64 environments | Qualified at the P1-I26 checkpoint |

The opt-in package gate builds a source distribution and a wheel, rebuilds from the
source distribution and runs isolated installed consumers. Unit tests cover the
typed surface and lifecycle failures without rebuilding artifacts on every run.

Run the explicit host-tooling gate from the ecosystem checkout and frozen
environment. The harness is not distributed inside this product wheel:

```sh
.venv/bin/python -m harness.package_check
```

Prepare the exact pinned build and runtime dependency cache before this offline
gate. Missing cached setup is a failure. The gate verifies:

- source, source-distribution and wheel payload equality, declared extras, type
  metadata and private retained artifacts;
- fresh virtual environments with isolated interpreters and no repository path
  injection;
- an SQLite consumer that preserves a preexisting M1 task through explicit
  migration, persists a real read-only supplier result, replays its original
  identity and rejects changed content;
- a separate real thread that proves bounded async ownership;
- a `postgres`-extra consumer that reproduces a controlled loopback startup failure.

Positive PostgreSQL-store and platform evidence run in their declared integration
lanes.

## Next milestone

| Step | Outcome | Gate |
| --- | --- | --- |
| P1-I26 package checkpoint | Complete for the tested Python 3.14 macOS and Linux ARM64 environments | [Package work item](../../../docs/work-items/0016-p1-standalone-package.md) |
| Remaining P1 media, real-inference and complete release assertions | Required separate evidence at the checkpoint | The [Phase H release work item](../../../docs/work-items/0019-p1-phase-h-release-qualification.md) owns the later release status |
| Complete P2/P3 acceptance | Remains pending | P2 and P3 project gates |

At the checkpoint, host direct and rebuilt artifacts, isolated installed consumers,
independent API and failure review, actual PostgreSQL startup and a genuine native
and browser consumer passed. The package work item owns those results.

This README keeps that P1-I26 checkpoint. Source payload equality does not claim
byte-identical archives, publication or untested platform support.
