# Case authority and persisted continuation

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Record the decision and rationale for case authority, exact consent and persisted continuation |
| Audience | Engineers changing P1 case authority, confirmation, waits or retry policy; coding agents |
| Scope | PostgreSQL v2 upgrade, protected operations, quotes, confirmation, signals, waits, retry, case identity and retention; excludes supplier apply, cancellation and leases |
| Owns | Case authority, consent, wait, retry and retention choices and their rationale |
| Related | [Decision 0003](0003-postgres-cutover-and-scope.md) · [Decision 0005](0005-effects-cancellation-and-outbox.md) · [Phase D work item](../work-items/0010-p1-phase-d-authority-and-waits.md) · [Case and continuation guide](../case-and-continuation.md) |

## Context

Phase C established the inquiry identity and PostgreSQL cutover. Phase D needs
exact consent, waiting and retry policy without changing investigation consent
into mutation authority or building a second scheduler. A completed read-only
inquiry is not a completed booking change.

## Decision

### Schema upgrade

Explicitly upgrade ACTIVE PostgreSQL v1 to v2 using the migration principal. Keep
the original three inquiry tables and the cutover receipt unchanged. Add scoped
case, immutable quote, confirmation, intent and dispatch records, and P1-owned
wait, signal and control records. Original tasks, payloads and effect keys remain
immutable. Serving adapters validate v1 and v2 without data definition language
(DDL). SQLite stays the bounded inquiry-only subset.

### Protected operations

Protected operations share the existing admission transaction lock, then the
scoped case or control row. Never hold a transaction across supplier, model or
network calls. Read the trusted clock inside the protected operation and reject
first-time confirmation at or after quote expiry or the business deadline.
Revision and intent commitment have one transaction winner. A committed intent
cannot be rewritten. Use a new request or reconciliation path for subsequent
changes.

### Quotes and confirmation

Quotes contain the exact case, revision, booking, date, amount in minor units,
currency and expiry. A trusted fixture producer records proposals. Authenticated
explicit confirmation is a separate typed command over the exact snapshot. Free
text, model summaries, media playback and caller-supplied actor labels grant no
authority.

Persist the immutable confirmation, one action intent and effect, and a stable
dispatch event together. The event is a durable dispatch intent, not a delivered
event or supplier application. No mutating supplier method exists in this phase.

### Signals and waits

Signals are typed, scoped and content-bound to actor, task and correlation. Early
signals remain durable. Consuming a matching signal revalidates current authority
and expiry in the same transaction that commits intent. Unrelated, stale or
changed replay cannot advance work. No room or sleeping coroutine retains a wait.
Explicit worker or advance calls evaluate persisted UTC deadlines.

### Retry policy

Retry policy uses finite attempts and bounded exponential backoff under an
injected trusted clock.

| Outcome | Behavior |
| --- | --- |
| Transient | Retries preserve the original inquiry effect and reconcile before dispatch |
| Permanent, exhausted or deadline | Stops |
| Ambiguous | Remains uncertain without an automatic resend |

Continuation control is keyed to the original execution and guards use of the
legacy worker. The base inquiry result and continuation stage are separately
inspectable.

### Case identity

Cases receive a distinct immutable `case_id`. The `task_id` remains the original
workflow identity. This subset binds one case to one task, and revision, replay and
restart preserve both. A future multi-workflow case association must be explicit.

### Retention and resources

No cleanup, time-to-live (TTL), prune or DELETE privilege is introduced. Retain
request, confirmation, signal, effect and dispatch identities indefinitely within
the bounded synthetic lab. At capacity, reject new identities while preserving old
replay and read. Quote or deadline expiry does not reset an identity.

Before production cleanup, define and test replay horizons, retained tombstones,
explicit expired-ID rejection and uncertain-effect protection. This phase does not
claim pruning.

## Consequences

PostgreSQL v2 extension is explicit and repeatable.

| Table kind | Grants |
| --- | --- |
| Immutable | SELECT and INSERT only |
| Mutable | SELECT and INSERT, plus UPDATE |

Neither table kind receives runtime DDL, metadata write or destructive grants.
Public conversation, HTTP and UI adapters, actual apply and cancellation,
distributed leases, completion delivery and full release instrumentation remain
later checkpoints.

## Validation

Exact transaction and restart tests are required before acceptance claims.
Interrupted migration must leave readable v1 or complete v2. Both old inquiry and
new lifecycle behavior must pass real database tests.
