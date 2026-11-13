# Supplier effects, cancellation and completion delivery

Status: Active
Last reviewed: 9 November 2026

## Context and compatibility

Phase D committed exact consent but intentionally supplied no apply capability.
Phase E needs supplier revision and target binding before irreversible dispatch.
Use payload version 2 to bind the case/workflow, current request revision, exact
proposal, supplier identity and expected supplier booking revision. Preserve all
legacy v1 JSON bytes and known receipts. Legacy consent is not upgraded by reading
current supplier state; it is read/replay compatible and ineligible for apply.

Upgrade ACTIVE PostgreSQL v2 explicitly to v3 under the one-shot owner. Preserve
original inquiry tables, case/wait/intent columns and historical cutover receipts.
New effect/cancellation/outcome/event/delivery tables remain in the same authority.
Runtime has no DDL, core DELETE/TRUNCATE or metadata write privilege.

## External and cancellation boundaries

The supplier fixture owns one booking authority used by both read-only inquiry
and mutation. Persist immutable provider identity/cooperation mode. An apply call
validates the exact committed payload, CAS booking revision and stable effect;
cooperating receipt replay occurs before comparing later booking revision.
A genuinely noncooperating variant offers neither deduplication nor outcome lookup.
Harness observations cannot become undeclared worker lookup capabilities.

Claim ownership and possible dispatch are separate facts. Commit DISPATCHED before
I/O. A stopped claim with zero dispatch can be attempted safely; possible prior
calls require cooperating lookup/dedup evidence or an uncertain outcome without
resend. Binding the supplier in the proposal prevents target substitution.
Network/provider calls never hold the PG transaction or grant booking authority.

Cancellation before commitment prevents intent; after commitment but provably before
any dispatch it can safely prevent the call without rewriting intent. Possible
prior dispatch always means best effort. Confirmation/cancellation and cancellation/
dispatch races have one protected winner. Preserve actual known supplier success,
including after a cancellation request or elapsed deadline. A cancelled async
waiter or interrupted speech is not an explicit business cancellation.

## Completion, delivery and retention

Commit terminal business outcome, immutable completion event and pending delivery
in the same transaction. The independent standalone receiver deduplicates canonical
content under one stable event identity. Bound receiver identity on first delivery
and reject silent target changes across acknowledgement loss. Delivery failure
cannot change a successful business outcome; delivery is not human acknowledgement.

Retain effect, cancellation, outcome, event and receiver receipts indefinitely
inside finite lab caps. Diagnostic projections may be pruned independently; replay
must still deduplicate after pruning. No cleanup or TTL may turn an accepted
identity into new work. Uncertainty is terminal for automatic dispatch; future
manual adjudication needs a separately versioned observation/event contract.

## Verification

Use normal authorized mutation, strict negative confirmation, stale supplier CAS,
actual process loss after supplier commit, noncooperating no-resend, cancellation
races, atomic outcome/event loss and receiver-success/local-ack loss. Repeat using
installed application code and preserve the live M1 stack. Do not infer a lease,
multi-region media, human-presence, browser playback or production capacity claim.
