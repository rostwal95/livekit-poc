# Controlled PostgreSQL cutover and restricted runtime

Status: Active
Last reviewed: 9 November 2026

## Context

S-I05 and P1-I08 through P1-I10 introduce PostgreSQL before richer workflow state.
The first SQLite crash proof remains available. Neither a schema migration nor a
new backend may change accepted requests, attempts, timestamps, effect identities
or known outcomes. Source and target cannot commit one distributed transaction.

## Decision

Use a recoverable, ordered one-shot cutover. SQLite schema v1 remains the normal
inquiry subset. The explicit source operation acquires the cooperating worker
slot and a reserved writer transaction, takes a private v1 backup and upgrades to
schema v2 with a permanent quiescence record. Every cooperating intake/enrollment/
attempt writer checks this gate inside its transaction. Reads, original replay
and changed-payload conflicts remain available. No automatic unquiesce or dual
write exists. Direct SQLite file access is trusted administration, not a tenant
security boundary.

Source quiescence is permanently bound to a fingerprint of the selected
host/port/database/schema before import. A retry using another target fails
closed. Preserve the original connection form on retry: differing container/host
aliases or port mappings are not automatically treated as the same destination.
Credentials are excluded from this identity.

Target schema v1 starts STAGING. Import writes all three original tables and its
receipt in one PostgreSQL transaction. Exact canonical row values and a SHA-256
content digest are verified before source CUTOVER. Activation locks target
business tables, rechecks the digest and marks ACTIVE in one transaction. A
matching completed receipt is returned on retry without reimporting legitimately
progressed target records. Serving adapters require ACTIVE on every operation.

| Durable checkpoint | Retry behavior |
| --- | --- |
| SQLite v1 and empty staging target | Verify any retained original backup, then quiesce and import |
| SQLite QUIESCED and empty staging target | Reuse the recorded migration identity and original backup; import |
| SQLite QUIESCED and matching staged import | Verify exact rows; record source CUTOVER; activate |
| SQLite CUTOVER and matching staging target | Verify exact rows and activate |
| SQLite CUTOVER and matching ACTIVE receipt | Return completion; preserve subsequent PostgreSQL progress |
| SQLite QUIESCED with ACTIVE target, wrong receipt or changed source/backup | Fail closed; investigate retained state; no automatic repair |

A backup must remain a regular owner-only 0600 file with one hard link. Restore
is a separate operator decision into a new path. Once target writes are possible,
restoring source for live writes would create divergent authorities; first isolate
all consumers and reconcile target/supplier effects. Never reset a volume to repair
an import. The local demo uses isolated schemas/files and leaves the live M1 API
on its existing database; it does not automatically switch the browser application.

## Credentials and privileges

Bootstrap administration remains inside the PostgreSQL container. Versioned local
credential initialization adds one migration secret atomically while retaining all
existing secrets, configuration and volume-owner labels. Explicit prepare-postgres
runs after health for both fresh and retained volumes. Existing non-null role
passwords are authenticated over TCP/SCRAM and never rotated by normal startup.

The continuity_migrator principal owns the schema and runs only the one-shot
migrations profile. It has no superuser, database creation, role creation,
replication or membership privilege. It may create schemas in the isolated lab
database. Runtime livekit_lab has CONNECT/USAGE, SELECT/INSERT/UPDATE on business
tables and SELECT on migration metadata. It cannot create schema/table/temp
objects, delete/truncate, modify metadata, assume owner or grant privileges.
Future tables default to SELECT only; writable grants need an explicit migration.
Schema/version/constraint/index/owner/grant drift fails closed without serving DDL.

P1_MIGRATION_* settings are for administrative commands only. P1_POSTGRES_* settings
are runtime-only. Passwords are explicit connection arguments from private local
configuration; no DSN or secret enters argv, SQL text, source, logs or reports.
The local connector permits only loopback or the Compose PostgreSQL hostname;
remote transport/TLS and production identity policy require a separate design.

## Runtime and actor boundary

Both inquiry adapters implement WorkerExecutionPort and share row decoding.
PostgreSQL uses a bounded transaction admission lock and a separate session
worker lock. Connections use autocommit with short explicit business transactions;
no transaction remains open across a supplier call. This is a cooperating single
worker, not a lease, fencing epoch, HA guarantee or connection pool.

ScopedInquiryService authenticates every call against an immutable trusted local
token directory and derives account scope internally. Untrusted request data
cannot choose scope. Inaccessible/unknown IDs have the same response; cancel and
signal check authorized existence before reporting unsupported operation. This
is a typed synthetic application boundary, not production IAM or a public HTTP
endpoint. Phase D adds a separate ScopedCaseService for real typed confirmation signals.
The legacy inquiry service retains its unsupported signal/cancel contract; repeat
these guards when cancellation is implemented.

## Consequences and evidence

The explicit real PostgreSQL lane fails on missing setup and does not turn required
scenarios into skips. It tests adapter parity, actual privilege rejection,
interrupted imports, receipt conflicts, backup restore, active-target replay,
scoped access and independent worker recovery. The fast lane retains SQLite proofs.
At the original Phase C rollout checkpoint, P1-15/P1-17 and full backend/platform
qualification were still open; that slice alone did not complete the release.
Later phases passed those acceptance rows and the selected provider_real v2 local
P1 qualification, recorded in the [current Phase H handoff](../work-items/0019-p1-phase-h-release-qualification.md).
local_real remains unqualified and complete P2/P3 acceptance remains pending. Materialized snapshots
suit this bounded synthetic lab; large production migrations require measured
memory/storage budgets and a separately reviewed streaming/batch import procedure.

[PostgreSQL explicit locking](https://www.postgresql.org/docs/18/explicit-locking.html),
[PostgreSQL schema privileges](https://www.postgresql.org/docs/18/ddl-schemas.html),
[Psycopg transaction management](https://www.psycopg.org/psycopg3/docs/basic/transactions.html).
