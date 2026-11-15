# Supplier effects, cancellation and completion delivery

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Record the decision and rationale for supplier effects, cancellation and completion delivery |
| Audience | Engineers changing P1 supplier effects, cancellation or completion delivery; coding agents |
| Scope | Payload v2 binding, PostgreSQL v3 upgrade, external and cancellation boundaries, completion, delivery and retention; excludes lease, playback and production capacity claims |
| Owns | Supplier effect, cancellation, completion and delivery choices and their rationale |
| Related | [Decision 0004](0004-case-authority-and-continuation.md) · [Decision 0006](0006-database-leases-and-bounded-worker.md) · [Phase E work item](../work-items/0011-p1-phase-e-effects-and-completion.md) · [Effects and completion guide](../effects-and-completion.md) |

## Context

Phase D committed exact consent but intentionally supplied no apply capability.
Phase E needs supplier revision and target binding before irreversible dispatch.

## Decision

### Compatibility and schema upgrade

Use payload version 2 to bind the case and workflow, the current request revision,
the exact proposal, the supplier identity and the expected supplier booking
revision. Preserve all legacy v1 JSON bytes and known receipts. Legacy consent is
not upgraded by reading current supplier state. It remains compatible for read and
replay, and is ineligible for apply.

Upgrade ACTIVE PostgreSQL v2 explicitly to v3 under the one-shot owner. Preserve
the original inquiry tables, the case, wait and intent columns, and historical
cutover receipts. New effect, cancellation, outcome, event and delivery tables
remain in the same authority. The runtime has no data definition language (DDL)
privilege, no core DELETE or TRUNCATE privilege and no metadata write privilege.

### External and cancellation boundaries

The supplier fixture owns one booking authority used by both read-only inquiry and
mutation. Persist the immutable provider identity and cooperation mode. An apply
call validates the exact committed payload, the compare-and-set (CAS) booking
revision and the stable effect. Cooperating receipt replay occurs before comparing
a later booking revision. A genuinely noncooperating variant offers neither
deduplication nor outcome lookup. Harness observations cannot become undeclared
worker lookup capabilities.

Claim ownership and possible dispatch are separate facts. Commit DISPATCHED before
I/O. A stopped claim with zero dispatch can be attempted safely. Possible prior
calls require cooperating lookup or deduplication evidence, or an uncertain
outcome without resend. Binding the supplier in the proposal prevents target
substitution. Network and provider calls never hold the PostgreSQL transaction or
grant booking authority.

| Cancellation point | Effect |
| --- | --- |
| Before commitment | Prevents intent |
| After commitment, but provably before any dispatch | Can safely prevent the call without rewriting intent |
| Possible prior dispatch | Always means best effort |

Races between confirmation and cancellation, and between cancellation and
dispatch, have one protected winner. Preserve actual known supplier success,
including after a cancellation request or an elapsed deadline. A cancelled async
waiter or interrupted speech is not an explicit business cancellation.

### Completion, delivery and retention

Commit the terminal business outcome, the immutable completion event and pending
delivery in the same transaction. The independent standalone receiver deduplicates
canonical content under one stable event identity. Bind the receiver identity on
first delivery and reject silent target changes across acknowledgement loss.
Delivery failure cannot change a successful business outcome. Delivery is not
human acknowledgement.

Retain effect, cancellation, outcome, event and receiver receipts indefinitely
inside finite lab caps. Diagnostic projections may be pruned independently, and
replay must still deduplicate after pruning. No cleanup or time-to-live (TTL) may
turn an accepted identity into new work. Uncertainty is terminal for automatic
dispatch. Future manual adjudication needs a separately versioned observation and
event contract.

## Validation

Validation uses these scenarios:

- Normal authorized mutation.
- Strict negative confirmation.
- Stale supplier compare-and-set.
- Actual process loss after supplier commit.
- A noncooperating supplier with no resend.
- Cancellation races.
- Atomic outcome and event loss.
- Receiver success with lost local acknowledgement.

Repeat them using installed application code and preserve the live M1 stack (the
original SQLite confirmed-investigation intake). Do not infer a lease,
multi-region media, human-presence, browser playback or production capacity claim.
