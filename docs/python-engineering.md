# Python engineering and failure contracts

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Define the Python engineering practices and failure contracts for this repository |
| Audience | Engineers and coding agents who write or review Python |
| Scope | New Python product code and materially changed Python boundaries; excludes gates, observability vocabulary and dependency promotion |
| Owns | Python API, typing, async and resource, persistence, diagnostics and package engineering practices |
| Related | [Validation plan](validation-plan.md) · [Observability contract](observability.md) · [Technology baseline](technology-baseline.md) · [Root instructions](../AGENTS.md) |

## Scope and current enforcement

This guide covers types and public APIs, async execution and cleanup,
persistence and effects, exceptions, logging and metrics, and testing.

### Where the rules apply

Apply these rules to new Python product code and materially changed Python
boundaries. Preserve working M1 interfaces (the original SQLite
confirmed-investigation intake). Do not rewrite the repository merely to adopt a
pattern.

Other documents own related contracts:

| Document | Owns |
| --- | --- |
| [Validation plan](validation-plan.md) | Gates |
| [Observability contract](observability.md) | The operational field and error vocabulary |
| [Technology policy](technology-baseline.md) | Dependency promotion |

### Runtime and tooling

| Requirement | Version or value | Notes |
| --- | --- | --- |
| Selected Python runtime | 3.14.10 | None |
| Python support for the root and all three current project distributions | `>=3.14,<3.15` | No other interpreter support is advertised |
| Ruff syntax target | `py311` | A conservative target; this is not a Python support claim |
| Test framework | `unittest` | The existing pytest installation does not require converting tests |
| Type checking in `make check` | `mypy --check-untyped-defs` | Covers services and all three current project Python src packages |
| Additional strict checks | Selected public APIs, safety helpers, workload and inference boundaries | This is not whole-repository strict typing |
| Platform evidence | Local host and Linux container, recorded separately | Remote continuous integration (CI) and publication are outside this proof-of-concept (POC) scope |

## Types, modules and public APIs

| Practice | Required application | Verification |
| --- | --- | --- |
| Explicit boundaries | Annotate new public methods, adapter protocols, configuration and return types; validate external JSON at runtime before constructing domain values | Type check the new package, negative schema fixtures and public consumer tests |
| Small domain values | Prefer enums/unions for finite outcomes and immutable dataclasses for accepted values; use tuples or copied immutable nested values where needed | Mutate the original caller input after acceptance; the persisted canonical payload/digest must remain unchanged |
| Honest immutability | `frozen=True` prevents attribute rebinding, not mutation of a nested `dict`; never pass a live case object as accepted context | Snapshot and replay/conflict tests include nested collections |
| Typed ports | Use small `Protocol` interfaces for store, clock, supplier, execution, case and delivery boundaries; explicit constructor injection | Common adapter contract tests; no service locator or cross-project storage imports |
| Local responsibility | Keep pure validation/transition logic separate from I/O adapters and process entrypoints; do not hide a scheduler in a generic helper | Ownership/import checks and process tests through public interfaces |
| Controlled escape hatches | Confine `Any` to decoded external data before validation; explain narrow type ignores and do not use blanket `ignore-errors` or broad casts to hide a mismatch | Reviewer inspects each new escape hatch; expand maintained mypy paths when a new package exists |
| Compatibility | Use syntax/APIs supported by the declared minimum; introduce newer APIs only with a support-policy change and matrix evidence | Build/import and behavior tests on each supported interpreter |

### Test adapters and dynamic composition

- Before dynamic application composition, assign each test adapter to its public
  Protocol. Exercise the actual invoked method in a focused contract test.
- A broad Any or loader must not hide a missing method or a structured observation
  return type.
- Construct narrower closed references with their exact fields. Static structural
  assignability does not authorize extra wire fields.

### Module conventions

- Keep docstrings focused on invariants, units, ownership, side effects and raised
  domain errors.
- Avoid mutable default arguments and import-time network or database work.
- Libraries receive configuration. Entrypoints load and validate environment
  settings.
- Secret-bearing fields must have safe representations. That alone does not make
  arbitrary serialization safe.

### Package layout

P1 uses the canonical src layout under projects/agent-continuity/python, with api,
postgres_api and testing as explicit public surfaces.

- Services depend on its locked workspace distribution. Harness and application
  code stay out of the wheel.
- Verify direct and rebuilt installed artifacts outside repository import paths,
  using only declared extras.

The Python packaging guide explains how the src layout helps expose accidental
source-tree imports:
[packaging layouts](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/).

## Async execution, deadlines and cleanup

| Rule | Required behavior and test |
| --- | --- |
| One lifecycle owner | Use context managers/lifespan and explicit close/aclose for owned pools, sessions, streams, readers and tasks; test normal exit, failure and cancellation |
| Structured concurrency | Use `TaskGroup` for related request/session tasks where shared failure/cancellation is intended; keep native LiveKit lifecycle ownership in its SDK; durable work belongs to P1 |
| Cancellation propagation | Cleanup in `finally`; re-raise `CancelledError`. Never catch `BaseException` as a normal error category or convert cancellation to success/retry |
| Task outcomes | Await owned tasks or retain them and retrieve exceptions; no detached fire-and-forget task can carry accepted work |
| Finite work | Bound active operations, queued items, bytes, pool connections, retries and cleanup time; state overload policy before accepting work |
| Blocking I/O | Prefer supported async clients; isolate unavoidable blocking I/O behind finite capacity. Cancellation of a waiter does not stop an already running thread: retain its slot until the operation finishes |
| CPU work | Do not execute large decode/model/CPU loops on the conversation event loop; select a bounded process/service boundary when measurement warrants it |
| Deadlines | Persist UTC absolute business expiry; derive remaining request time and measure durations monotonically. Set per-attempt and total budgets; a timeout does not prove a remote effect stopped |
| Shutdown | Stop admission, finish or leave recoverable durable work, then close resources under a declared budget; verify a fresh process can recover accepted work |

### Closing owned resources

Close in dependency order:

1. Close independent owners within a dependency tier.
2. Observe their successful actual closure before closing their shared readers.

Ownership rules during close:

- A failed or timed-out close observer may leave actual I/O owned. Retry the
  public close to observe that same owner.
- A cancelled task cannot prove that a worker thread stopped.
- Parent tooling must verify that owned children exited and were reaped before
  dropping their schemas or deleting application, supplier and environment files.
- Preserve private work and report incomplete cleanup while any dependent owner
  remains unresolved.

### Shield, uncancel and TaskGroup

| Primitive | Rule |
| --- | --- |
| `shield` | Use it only for a justified narrow ownership boundary, such as observing an already-started bounded I/O operation; it does not make work durable |
| `uncancel` | Do not use it to suppress cancellation casually |
| `TaskGroup` | It aggregates failures; when that interface is used, handle `ExceptionGroup` deliberately, without discarding unhandled branches |

Python documents the cancellation requirements of these structured concurrency
primitives:
[async tasks and cancellation](https://docs.python.org/3.14/library/asyncio-task.html).

## Persistence and effects

### Transactions

- Keep transactions short and parameterized.
- Commit acceptance and required dispatch intent atomically. Return acceptance
  only after commit.
- Validate scope, semantic canonicalization and changed-payload conflicts within
  the authoritative operation.
- Check conditional-write results. A zero-row lease or revision update is not a
  successful transition.
- Never hold a transaction over network or model calls.

### Migrations

- Use versioned migrations, pre-upgrade fixtures and the shared one-shot migration
  principal.
- Runtime roles cannot perform schema administration.
- Test interrupted and repeated migrations, preserved-volume restart, controlled
  rollback and restore, and retained M1 identities.
- Keep SQLite's supported subset explicit. Richer execution runs on PostgreSQL
  rather than a second full scheduler.

### External effects

- Record stable effect identity before dispatch.
- Distinguish definitive failure, confirmed success and uncertain external
  outcome.
- Retry only when the supplier contract, persisted state and remaining budget
  permit it. Classify backoff and jitter explicitly.
- A retryable HTTP failure cannot authorize a new business key or repeat an
  uncertain external mutation.
- Retain replay and effect tombstones before cleanup. Deadline expiry cannot make
  an accepted operation new again.

## Exceptions and boundary translation

Expected domain failures should have a small typed hierarchy with stable safe
codes. The table is a target contract for new adapters, not a claim that every
class already exists.

- Existing IdempotencyConflict and IntakeCapacityExceeded remain compatible.
- Keep HTTP status choices in transport adapters, not domain models.
- An uncertain result is an explicit state, not a generic exception that
  automatically triggers another attempt.

| Category | Handling | Required negative assertion |
| --- | --- | --- |
| Invalid/unsupported input | Reject before acceptance; stable validation/version code | No partial record or reflected sensitive value |
| Permission or scope | Fail closed at the verified-principal boundary | No cross-account lookup, mutation or evidence disclosure |
| Same-ID conflict | Preserve original accepted semantics | Changed payload never overwrites prior state |
| Capacity/dependency | Explicit retry/defer advice bounded by caller policy | Replays/inspection remain available; admitted work remains durable |
| Storage failure | Roll back a failed transaction; reconcile ambiguous commit acknowledgement | No false acceptance/failure; same identity resolves the outcome |
| Lease/revision conflict | Reject the stale write/intent and inspect authority | Stale computation cannot authorize current action |
| Cancellation/deadline | Preserve requested, observed and committed outcomes separately | Timeout/acknowledgement does not falsely establish external termination |
| Unexpected defect | Translate once at the outer process/HTTP boundary, emit safe correlation and fail visibly | Sanitized response, no secret/provider text; no swallowed failure |

### Catching and translating exceptions

- Catch the narrow dependency exception where recovery or translation is
  meaningful.
- Preserve causes with raise ... from error inside the process. Never serialize
  the exception chain to public responses or logs without a proven sanitizer.
- Broad except Exception is reserved for an explicit outer containment or cleanup
  boundary with tests.
- Do not log and re-raise the same expected failure at every layer.
- Fallback to an empty successful value is not recovery.

### Testing exception paths

Test new exceptions through the existing transaction and transport normalizers,
including their actual rollback and observer paths.

- A permission denial or invalid cursor must retain its finite domain
  classification without incrementing a storage outage counter.
- Unexpected SQL failures remain unavailable.
- Rollback ownership continues after caller timeout until the underlying
  transaction settles.

## Logging and metrics

### Library and application loggers

- Reusable libraries use named module loggers and leave handler, format and export
  configuration to the application.
- A library may use NullHandler. It must not configure the root logger.
- The existing control API owns its application-specific JSON logger.
- New process entrypoints must deliberately configure their own safe logging,
  including SDK and native output limitations.

Python's logging guidance distinguishes library loggers from application
configuration:
[library logging](https://docs.python.org/3.14/howto/logging.html#configuring-logging-for-a-library).

### Events and fields

- Emit fixed event names and allowlisted fields from real state transitions.
- Use one boundary event for the unexpected failure, with the UTC timestamp,
  service, operation, code, outcome and elapsed seconds where known.
- Add validated scoped correlation fields only when their retention and access
  policy permits it.
- Avoid expensive formatting when disabled.

### Sensitive content

Production diagnostics must never include prompts, images, transcripts,
credentials, raw URLs, SQL parameters or provider exception text. exc_info=True
and logger.exception can reveal those values. Use them only with an explicitly
tested safe diagnostic path.

### Severity and telemetry failure

| Situation | Rule |
| --- | --- |
| Expected validation, conflict and cancellation | Normally need an outcome and code rather than a repeated stack trace |
| Failed operation | Declare `ERROR` |
| Process that cannot safely continue | Declare `CRITICAL` |
| Telemetry failure | It cannot block business acceptance, the media loop or shutdown |
| Logging and export buffers | Bound them and the overload policy; do not claim stdout is nonblocking by construction |

### Testing diagnostics

Tests must inspect emitted JSON and log fields and error envelopes using synthetic
secret sentinels, request bodies, headers, IDs, unknown fields and exception
messages. Verify:

- one expected event and no duplicate handlers;
- context isolation and finite metric dimensions;
- correct counters and durations;
- collector-failure behavior.

Operational counters reset; durable state remains the truth.

## Testing and promotion

### Test design

- Use the existing unittest suite consistently unless a concrete fixture requires
  pytest. Do not maintain duplicate runners for the same assertions.
- Async tests must await cleanup and inspect task failures.
- Use real local stores and processes for persistence claims, typed fakes for unit
  boundaries, and deterministic barriers and fake clocks for schedules.
- Mock an external boundary, not the internal method whose implementation is under
  test.
- Each failure test needs an ordinary success assertion and an eventual-progress
  assertion, including a second eligible tenant where fairness is claimed.

### Required verification evidence

| Verification | Required evidence |
| --- | --- |
| Public behavior | Acceptance ID, precise preconditions/action/expected durable and externally observed outcome |
| Failure schedule | Named barrier/crash point, actual process termination where claimed, bounded recovery and cleanup |
| Resources | Streams/connections/processes closed; cancelled callers cannot bypass capacity; warnings/leaked tasks investigated |
| Storage | Concurrent replay/conflict, short transactions, migration/restore, supported-store parity and actual backend isolation |
| Diagnostics | Safe typed exceptions, redaction, finite labels and exporter outage assertions |
| Packaging | Installed artifact consumer, public typing/exports, declared dependencies and advertised-version matrix |

### Repository checks

These are the current runnable repository checks. The
[root instructions](../AGENTS.md) own exact setup and commands.

| Task | Command | Notes |
| --- | --- | --- |
| Run the repository checks | `make check` | None |
| Check formatting | `make format-check` | None |
| Check TypeScript changes | `make frontend-check` | Only for TypeScript changes |

- New packages must be included in lint, type checking and test discovery in the
  same slice that introduces them.
- Adopt stronger Ruff and type settings incrementally with actual passing
  evidence. Neither the current default lint nor a percentage coverage target
  proves these contracts.
- Do not add tests that only reproduce prose, count files or mirror private
  implementation.

### Gates and evidence

The [work-item template](work-items/template.md) records the applicable
[engineering gates](validation-plan.md), evidence and unresolved requirements.
Missing mandatory evidence keeps its gate incomplete. A rule in this guide is an
implementation and review requirement, not proof that all existing source has
been certified against it.
