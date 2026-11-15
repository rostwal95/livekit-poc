# Controlled PostgreSQL cutover and restricted runtime

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Record the decision and rationale for the controlled PostgreSQL cutover and the restricted runtime |
| Audience | Engineers changing P1 PostgreSQL migration, roles or scoped access; coding agents |
| Scope | Source quiescence, destination binding, import, activation, backup, credentials and the actor boundary; excludes remote transport, TLS and production identity policy |
| Owns | PostgreSQL cutover, credential and runtime access choices and their rationale |
| Related | [Decision 0002](0002-sqlite-inquiry-subset.md) · [Decision 0004](0004-case-authority-and-continuation.md) · [Phase C work item](../work-items/0009-p1-phase-c-postgres-cutover.md) · [P1 charter](../projects/agent-continuity-scope.md) |

## Context

Shared task S-I05 and P1 implementation tasks P1-I08 through P1-I10 in the
[granular roadmap](../implementation-plan.md) introduce PostgreSQL before richer
workflow state. The first SQLite crash proof remains available. Neither a schema
migration nor a new backend may change accepted requests, attempts, timestamps,
effect identities or known outcomes. Source and target cannot commit one
distributed transaction.

## Decision

### Source quiescence

Use a recoverable, ordered one-shot cutover. SQLite schema v1 remains the normal
inquiry subset. The explicit source operation acquires the cooperating worker slot
and a reserved writer transaction. It takes a private v1 backup and upgrades to
schema v2 with a permanent quiescence record. Every cooperating intake, enrollment
and attempt writer checks this gate inside its transaction.

Reads, original replay and changed-payload conflicts remain available. No
automatic unquiesce or dual write exists. Direct SQLite file access is trusted
administration, not a tenant security boundary.

### Destination binding

Source quiescence is permanently bound to a fingerprint of the selected host,
port, database and schema before import. A retry using another target fails
closed. Preserve the original connection form on retry. Differing container or
host aliases, or port mappings, are not automatically treated as the same
destination. Credentials are excluded from this identity.

### Import and activation

Target schema v1 starts as STAGING. Import writes all three original tables and
its receipt in one PostgreSQL transaction. Exact canonical row values and a
SHA-256 content digest are verified before source CUTOVER. Activation locks target
business tables, rechecks the digest and marks ACTIVE in one transaction. A
matching completed receipt is returned on retry without reimporting legitimately
progressed target records. Serving adapters require ACTIVE on every operation.

### Retry checkpoints

| Durable checkpoint | Retry behavior |
| --- | --- |
| SQLite v1 and empty staging target | Verify any retained original backup, then quiesce and import |
| SQLite QUIESCED and empty staging target | Reuse the recorded migration identity and original backup; import |
| SQLite QUIESCED and matching staged import | Verify exact rows; record source CUTOVER; activate |
| SQLite CUTOVER and matching staging target | Verify exact rows and activate |
| SQLite CUTOVER and matching ACTIVE receipt | Return completion; preserve subsequent PostgreSQL progress |
| SQLite QUIESCED with ACTIVE target, wrong receipt or changed source/backup | Fail closed; investigate retained state; no automatic repair |

### Backup and restore

A backup must remain a regular owner-only 0600 file with one hard link. Restore is
a separate operator decision into a new path. Once target writes are possible,
restoring the source for live writes would create divergent authorities. First
isolate all consumers and reconcile target and supplier effects. Never reset a
volume to repair an import.

The local demo uses isolated schemas and files and leaves the live M1 API (the
original SQLite confirmed-investigation intake) on its existing database. It does
not automatically switch the browser application.

### Credentials and privileges

Bootstrap administration remains inside the PostgreSQL container. Versioned local
credential initialization adds one migration secret atomically while retaining all
existing secrets, configuration and volume-owner labels. The explicit
`prepare-postgres` action runs after the health check for both fresh and retained
volumes. Existing non-null role passwords are authenticated over TCP with Salted
Challenge Response Authentication Mechanism (SCRAM) and are never rotated by
normal startup.

| Principal | Purpose | Allowed | Denied |
| --- | --- | --- | --- |
| `continuity_migrator` | Owns the schema and runs only the one-shot `migrations` profile | May create schemas in the isolated lab database | Superuser, database creation, role creation, replication or membership privilege |
| `livekit_lab` | Runtime role | CONNECT and USAGE, SELECT, INSERT and UPDATE on business tables, and SELECT on migration metadata | Creating schema, table or temporary objects; deleting or truncating; modifying metadata; assuming the owner role; granting privileges |

Future tables default to SELECT only. Writable grants need an explicit migration.
Schema, version, constraint, index, owner or grant drift fails closed, and serving
code runs no data definition language (DDL).

| Setting prefix | Used by |
| --- | --- |
| `P1_MIGRATION_*` | Administrative commands only |
| `P1_POSTGRES_*` | Runtime only |

Passwords are explicit connection arguments from private local configuration. No data source name (DSN) or secret enters argv, SQL
text, source, logs or reports. The local connector permits only loopback or the
Compose PostgreSQL hostname. Remote transport, TLS and production identity policy
require a separate design.

### Runtime and actor boundary

Both inquiry adapters implement `WorkerExecutionPort` and share row decoding.
PostgreSQL uses a bounded transaction admission lock and a separate session worker
lock. Connections use autocommit with short explicit business transactions. No
transaction remains open across a supplier call. This is a cooperating single
worker, not a lease, fencing epoch, high-availability (HA) guarantee or connection
pool.

`ScopedInquiryService` authenticates every call against an immutable trusted local
token directory and derives account scope internally. Untrusted request data
cannot choose scope. Inaccessible and unknown IDs have the same response. Cancel
and signal check authorized existence before reporting an unsupported operation.
This is a typed synthetic application boundary, not production identity and access
management (IAM) or a public HTTP endpoint.

Phase D adds a separate `ScopedCaseService` for real typed confirmation signals.
The legacy inquiry service retains its unsupported signal and cancel contract.
Repeat these guards when cancellation is implemented.

## Consequences

Materialized snapshots suit this bounded synthetic lab. Large production
migrations require measured memory and storage budgets and a separately reviewed
streaming or batch import procedure.

## Validation

The explicit real PostgreSQL lane fails on missing setup and does not turn
required scenarios into skips. It tests adapter parity, actual privilege
rejection, interrupted imports, receipt conflicts, backup restore, active-target
replay, scoped access and independent worker recovery. The fast lane retains
SQLite proofs.

At the original Phase C rollout checkpoint, P1-15, P1-17 and full backend and
platform qualification were still open. That slice alone did not complete the
release. Later phases passed those acceptance rows and the selected provider_real
v2 local P1 qualification, recorded in the
[current Phase H handoff](../work-items/0019-p1-phase-h-release-qualification.md).
`local_real` remains unqualified, and complete P2 and P3 acceptance remains
pending.

## References

| Document | Purpose |
| --- | --- |
| [PostgreSQL explicit locking](https://www.postgresql.org/docs/18/explicit-locking.html) | Transaction and session lock behavior |
| [PostgreSQL schema privileges](https://www.postgresql.org/docs/18/ddl-schemas.html) | Schema ownership and privileges |
| [Psycopg transaction management](https://www.psycopg.org/psycopg3/docs/basic/transactions.html) | Autocommit and explicit transaction handling |
