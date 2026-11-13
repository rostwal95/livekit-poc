# Case authority and persisted continuation

Status: Active
Last reviewed: 9 November 2026

## Context

Phase C established the inquiry identity and PostgreSQL cutover. Phase D needs
exact consent, waiting and retry policy without changing investigation consent
into mutation authority or building a second scheduler. A completed read-only
inquiry is not a completed booking change.

## Decision

Explicitly upgrade ACTIVE PostgreSQL v1 to v2 using the migration principal.
Keep the original three inquiry tables and cutover receipt unchanged; add scoped
case/immutable quote/confirmation/intent/dispatch and P1-owned wait/signal/control
records. Original tasks/payloads/effect keys remain immutable. Serving adapters
validate v1/v2 without DDL; SQLite stays the bounded inquiry-only subset.

Protected operations share the existing admission transaction lock, then the
scoped case/control row. Never hold a transaction across supplier/model/network
calls. Read the trusted clock inside the protected operation and reject first-time
confirmation at or after quote expiry or business deadline. Revision and intent
commitment have one transaction winner. A committed intent cannot be rewritten;
use a new request/reconciliation path for subsequent changes.

Quotes contain exact case/revision/booking/date/amount-in-minor-units/currency/
expiry. A trusted fixture producer records proposals; authenticated explicit
confirmation is a separate typed command over the exact snapshot. Free text,
model summaries, media playback and caller-supplied actor labels grant no authority.
Persist immutable confirmation, one action intent/effect and a stable dispatch
event together. The event is a durable dispatch intent, not a delivered event or
supplier application. No mutating supplier method exists in this phase.

Signals are typed, scoped and content-bound to actor/task/correlation. Early
signals remain durable; consuming a matching signal revalidates current authority
and expiry in the same transaction that commits intent. Unrelated, stale or
changed replay cannot advance work. No room or sleeping coroutine retains a wait.
Explicit worker/advance calls evaluate persisted UTC deadlines.

Retry policy uses finite attempts and bounded exponential backoff under an
injected trusted clock. Transient retries preserve the original inquiry effect
and reconcile before dispatch; permanent/exhausted/deadline outcomes stop.
Ambiguous outcomes remain uncertain without an automatic resend. Continuation
control is keyed to the original execution and guards use of the legacy worker.
The base inquiry result and continuation stage are separately inspectable.

Cases receive a distinct immutable case_id; task_id remains the original workflow
identity. This subset binds one case to one task; revision, replay and restart
preserve both. A future multi-workflow case association must be explicit.

## Retention and resources

No cleanup, TTL, prune or DELETE privilege is introduced. Retain request,
confirmation, signal, effect and dispatch identities indefinitely within the
bounded synthetic lab. At capacity reject new identities while preserving old
replay/read; quote/deadline expiry does not reset an identity. Before production
cleanup, define and test replay horizons, retained tombstones, explicit expired-ID
rejection and uncertain-effect protection. This phase does not claim pruning.

## Consequences

Exact transaction and restart tests are required before acceptance claims.
PostgreSQL v2 extension is explicit and repeatable; interrupted migration must
leave readable v1 or complete v2. Immutable tables receive SELECT/INSERT only;
mutable tables add UPDATE, with no runtime DDL, metadata write or destructive
grants. Both old inquiry and new lifecycle behavior must pass real database tests.
Public conversation/HTTP/UI adapters, actual apply/cancellation, distributed leases,
completion delivery and full release instrumentation remain later checkpoints.
