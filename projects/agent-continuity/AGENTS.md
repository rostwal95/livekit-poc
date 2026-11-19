# Agent Continuity Lab coding instructions

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Give coding agents the reading order, owned paths, rules and checks for P1 changes |
| Audience | Coding agents and engineers changing the Agent Continuity Lab (P1) |
| Scope | P1 Python distribution, storage, workers and public work profile; excludes P2 and P3 application implementations |
| Owns | P1 agent reading order, owned paths, development rules and verification |
| Related | [Root instructions](../../AGENTS.md) · [P1 guide](README.md) · [P1 design](Design.md) · [V1 charter](../../docs/projects/agent-continuity-scope.md) · [P1 task plan](../../docs/implementation/p1-agent-continuity.md) |

## Read first

Read these documents:

| Document | Why read it |
| --- | --- |
| [Root instructions](../../AGENTS.md) | Follow first: repository-wide reading order, rules and verification |
| [README.md](README.md) | Product onboarding, implementation status and commands |
| [Design.md](Design.md) | State ownership, interfaces and failure boundaries |
| [V1 charter](../../docs/projects/agent-continuity-scope.md) | Authoritative requirements and stable acceptance IDs |
| [Shared validation plan](../../docs/validation-plan.md) | Test lanes, required fault scenarios, benchmarks and evidence |
| Affected source and tests | Inspect them before editing |
| [Granular implementation plan](../../docs/implementation/p1-agent-continuity.md) | Phase gates, task prerequisites and failure evidence |

The implementation plan's task IDs are not product acceptance IDs. The charter
remains authoritative.

Contents: Development rules cover consent and quotes, ports, workflow state,
delivery, leases, workers, schema upgrades and packaging, then the public work
profile, work schemas v2 to v4, guarded action and inference modes. Verification
covers all changes, storage and migration, Phase F and inquiry workloads.

### Before changing specific behavior

| Document | Why read it |
| --- | --- |
| [Case/continuation operations](../../docs/case-and-continuation.md) | Before changing authority, wait or retry semantics |
| [Effects and completion](../../docs/effects-and-completion.md) | Before changing mutation, cancellation, provider/receiver target binding or outbox behavior |
| [Leases and workers](../../docs/leases-and-workers.md) | Before changing v4 admission, server-time authority, due selection or child ownership |

## Owned paths

| Area | Responsibility |
| --- | --- |
| `projects/agent-continuity/python/src/continuity_lab` | Canonical source, retaining the `continuity_lab` import name |
| `tests/test_intake.py` | Baseline tests |
| `tests/test_execution*.py`, `test_async_execution.py` and `test_migrations.py` | Execution, async, migration and actual accepting-process checks |
| `projects/agent-continuity/python` | Canonical reusable Python distribution, examples and packaging |
| `projects/agent-continuity/tests` | Project tests |
| [V1 charter](../../docs/projects/agent-continuity-scope.md) | Scope and acceptance IDs |
| [Root design](../../Design.md) | Shared authority and ports |

The canonical source includes `execution_models.py`, `execution.py`,
`async_execution.py`, `migrations.py` and `execution_cli.py`. It also includes
PostgreSQL settings/store/migrations/CLI, source_transfer/cutover,
transfer/codec/worker-lock helpers and `authorization.py`.

Later phases add these modules:

| Phase | Adds |
| --- | --- |
| Phase D | case_models/postgres_case, retry_policy/lifecycle_models/postgres_lifecycle/managed_inquiry_worker, case_service/case_telemetry, postgres_schema_v2 and bounded_io/postgres_unit_of_work |
| Phase E | effect_models/postgres_effects, mutation_supplier/mutation_worker, completion_sink/outbox_delivery and postgres_schema_v3 |
| Phase F | lease_models/postgres_leases/postgres_work, worker_runtime/worker_cli and postgres_schema_v4 |

- Do not relocate working code merely to fill this directory.
- Keep unrelated projects and user files intact.

## Development rules

### Consent, confirmation and quotes

- Preserve investigation-only consent in M1, the existing confirmed-investigation intake.
- A booking mutation requires separate explicit confirmation of the exact quote and
  case revision.
- Case revision/confirmation and wait consumption must share the same protected
  transaction.
- Preserve direct confirmation and waiting-state coherence.
- Preserve quote v2 case/provider/expected supplier revision binding.
- Legacy v1 read/replay remains valid but cannot authorize new mutation.
- Never infer missing proposal authority from mutable later supplier state or worker
  configuration.

### Ports and ownership

- Use `TaskExecutionPort`, `CaseAuthorityPort` and supplier/event interfaces.
- Keep one owner for current case facts and committed action intents.
- P1 must not import P2 or P3 application implementations.

### Workflow state, attempts and cancellation

- Keep persisted workflow state, attempts, waits, effects and cancellation intent
  distinguishable.
- Database fencing does not itself fence external supplier calls.
- Distinguish CLAIMED before reservation from possible prior dispatch using
  dispatch_count, including on recovered claims.
- Attempt generation is not a distributed lease epoch.
- V4 separately requires an explicit invocation lease validated in the same
  transaction as each worker write.
- Validate active-attempt intent/number before finishing.
- Keep cancellation receipts separate from effect truth.
- Zero prior reservations can prove prevention.
- Possible dispatch is best effort until reliable result or uncertainty.
- Known success survives cancellation and deadline expiry.

### Completion, delivery and receipts

- Commit final outcome, stable completion event and initial delivery together.
- Bind the receiver before first I/O and preserve the same receiver/event across
  lost acknowledgement.
- Delivery failure cannot alter business outcome or claim human acknowledgement.
- Retain core effect/attempt/cancel/outcome/event and supplier/receiver
  deduplication receipts.
- Only the receiver's separate diagnostic projection may be pruned.
- Test late original replay after projection pruning and at capacity.

### Blocking I/O and bounds

- Keep blocking I/O off the conversational event loop and external calls outside
  database locks.
- Bound concurrency, pending work, retries and shutdown.

### Leases and controller commands

- Sample database clock_timestamp after locks for lease authority.
- Retain epochs after release/expiry and reject stale owner/task/scope/epoch writes.
- Cached expiry, worker wall time and a new owner's observed token grant no authority.
- Keep authenticated controller confirmation/signal/cancel/inspection separate from
  worker claims.
- Do not block user cancellation on an external call or use lease ownership as consent.
- External requests still need provider cooperation or explicit uncertainty.
- Database fencing alone cannot stop a reserved call.

### Persisted v4 limits

- Enforce persisted v4 limits across admission, completed-inquiry management and
  active claims.
- Include durable waits in outstanding work and all retained task identities in
  record capacity.
- Preserve existing replay/reads at capacity.

### Worker runtime and children

- Pull one due step without a second durable queue.
- Own at most one child per parent.
- Cap monotonic occupancy/output/failures.
- Stop new acquisition on signal.
- Kill/reap the owned group before lease release.
- Never report clean shutdown when child cleanup is incomplete.
- Keep raw child output out of public logs.

### Schema upgrades, migrations and compatibility

- Upgrade only ACTIVE v3 with no unmanaged RUNNING inquiry.
- Refuse before DDL (schema-changing SQL) so original v3 reconciliation remains
  possible.
- Runtime and the opt-in worker profile never install schema or initialize consent
  implicitly.
- Upgrade a deliberately selected ACTIVE application schema with upgrade-postgres
  then upgrade-effects.
- Never activate an unfinished import implicitly.
- Keep P1_MIGRATION_* out of runtime services.
- Schema or access control list (ACL) drift must fail closed.
- Preserve the established PLAN-02 SQLite M1/inquiry compatibility subset and its
  independent crash proof.
- The PostgreSQL cutover and Phase F lease/multi-worker gates are recorded evidence.
  Keep future lifecycle changes compatible with those boundaries.

### Recovery evidence

- Use independent processes, persisted supplier state, controlled clocks and
  failpoints for recovery evidence.
- An in-memory fake or reopened connection is insufficient for a process-crash claim.

### Replay horizons, packaging and Python support

- Define replay horizons/tombstones before cleanup.
- Preserve the standalone src-layout package and typed api/postgres_api/testing exports.
- Native services consume the locked workspace member.
- Installed examples must run outside checkout import paths with declared extras.
- Keep Python support at 3.14 unless an intentional support-policy change is qualified.

### Public work profile (work_api/work_admin)

- The additive public work_api/work_admin profile owns opaque immutable read-only
  accepted bytes, exact typed tenant/account/key identity and requested cancellation.
- Install the profile explicitly in a marked `p1_work_` schema with its owner.
- Runtime validates catalog/grants and performs no DDL.
- Preserve bytes/digest/original deadline and replay before caps/expiry.
- WorkClient.scope is verified before P3 submits.
- No body scope, proposed wire attempt or accepted status is action/execution authority.
- Keep the profile separate from booking v4 selectors without duplicating an
  accepted logical delegation into a P3 ledger.
- Test actual PostgreSQL uncertainty, caps, credential scope, catalog side effects
  and telemetry-failure useful progression.

### Execution API (work schema v2)

- The separate execution_api is usable only after the explicit owner-only
  upgrade_work_schema_v2.
- Preserve v1 acceptance/read/cancel APIs on all known versions.
- Runtime never upgrades, refreshes drift or changes booking v4/SQLite.
- Issue returns an immutable grant plus created.
- Only a newly created grant can cause invocation.
- Replayed/uncertain commands reconcile through find_issue and never automatically
  invoke again.
- Unknown transport keeps its lease until expiry.
- Every write shares admission locking and samples database time after locks.
- The scope, original accepted bytes, owner, attempt ID, command, number, epoch and
  lease must match the stored grant before a result can be recorded.
- Keep at most three immutable results per work and one per issued attempt.
- Stale/cancelled/late results remain historical.
- eligible_at_commit denotes only P1 lease/time/cancel eligibility, never semantic
  validity, current-case applicability or action consent.
- A later cancellation does not erase a known eligible result.
- Lease caps bound logical authority, not physical remote computation.
- The caller owns HTTP resources.
- No implicit retry, renewal, remote-stop claim, worker or delivery is introduced.

### Result delivery and action receipts (work schema v3)

- Version3 adds result-delivery bindings/possible markers/known receipts and
  guarded case-action receipts.
- Use only the explicit v2-to-v3 owner upgrade.
- Keep one of each per original work and retain core identities.
- No outbox worker or retry loop is introduced.
- Delivery prepare binds the stored eligible result and exact receiver/recipient
  before I/O.
- begin.created is the only fresh accept permission.
- Replayed possible work looks up its original receiver.
- Absent evidence is unknown.
- Known exact receipts survive later cancellation/deadline without claiming human
  acknowledgement (ACK).
- The private receiver requires explicit initialization, finite scope/recipient
  bindings, stable receiver identity and bounded actual SQLite I/O.
- No runtime DDL.

### Result feed (work schema v4)

- Version4 adds a generic result-only feed through result_feed_api and explicit
  owner upgrade_work_schema_v4.
- Preserve source UUID/event IDs on repeat/reopen.
- Backfill existing results once as adopted_history, preserving original bytes/times.
- Append a live event and scoped contiguous sequence in the result transaction under
  existing admission locking.
- No global pre-commit sequence or source ACK is allowed.
- Cursors bind source/scope and reject ahead-of-head.
- Feed limits: page≤100, event retention ≤ accepted cap×attempt cap (at most 30000),
  signed-int64 sequence types.
- Serving performs no DDL or repair.
- Old APIs and delivery/action support v4.
- P3 alone owns derived immutable as-of metadata.
- Later work/case changes do not refresh it.
- Restored-branch source incarnation rotation remains unqualified.

### Guarded action

- Guarded action lock order is booking admission, work admission, case/control.
- Revalidate work schema/counters, exact latest eligible result, cancellation and
  database deadline before the existing case authority commits current exact
  confirmation.
- The guarded receipt and case intent share one transaction.
- No supplier I/O occurs inside that transaction.
- A receipt replay returns original truth before later eligibility.
- Changed result/quote/actor/schema cannot retarget it.
- P1 does not parse P3 result semantics or manufacture user confirmation.
- The new public case_control_api is separate trusted controller composition.
- Do not expose case_control_api to native model tools.
- Keep all old booking/source modules and existing public methods compatible.

### Inference modes

- Trusted inference modes are exactly scripted (default), local_real and provider_real.
- Preserve the selected mode through mint, native readiness, numeric usage and
  sanitized traces.
- A configured badge or process health is not actual inference/media qualification.
- No silent provider/model fallback exists.
- All modes preserve bound tools and separate exact human confirmation.
- Read the [provider operations guide](../../docs/provider-demo.md) before changing
  provider composition.
- Offline validation must not read private key values or invoke providers.
- Never source, print, copy or include `local-setup/.env.providers` in reports or
  build contexts.
- Only the explicit native provider runtime receives the three keys.
- Inference configuration belongs to native composition, not the reusable case authority.
- Preserve the same typed interfaces and effect/confirmation invariants for all modes.
- Provider SDKs add no mutation or scope authority.

## Verification

From the repository root:

| Check | Command | When to run |
| --- | --- | --- |
| Relevant implemented scenario | `.venv/bin/python -m harness run <ID>` | All changes, before handoff |
| Focused structural checks | `HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh --module p1` | All changes, before handoff |
| Full fast lane | `HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh` | All changes, before handoff |
| Real PostgreSQL lane | `make postgres-check` | Storage, migration or authorization changes, after explicit local init/start/prepare-postgres/migrate-postgres |
| Phase E supplier/receiver success-before-ack recovery demo | `make phase-e-demo` | Storage, migration or authorization changes, for runtime-container recovery evidence |
| Phase F v4 upgrade/coordination lane | `make postgres-check` (includes the v4 upgrade, lease and coordination cases) | Phase F lease and worker changes |
| Phase F demo | `make phase-f-demo` | Phase F lease and worker changes |

The table indexes these checks; the rules below it remain authoritative.

### All changes

- Use stable P1 acceptance IDs in the change plan and evidence.
- Run the relevant implemented scenario, focused structural checks and full fast
  lane before handoff.
- Commands in the README run from the repository root.
- Planned, skipped, missing and timed-out checks cannot count as passes.
- New behavioral runners need real assertions and useful failure artifacts.
- No hidden service setup is allowed.

### Storage, migration and authorization changes

- Run `make postgres-check` after explicit local
  init/start/prepare-postgres/migrate-postgres for storage, migration or
  authorization changes.
- The Phase E lane owns isolated ACTIVE v3 test schemas.
- Run `make phase-e-demo` for runtime-container supplier/receiver success-before-ack
  recovery evidence.
- The tests under `tests/postgres` are a separate real-database lane, not skipped
  fast tests.

### Phase F leases and workers

- For Phase F run the actual v4 upgrade/coordination lane and `make phase-f-demo`.
- Use independent processes and database-server expiry for takeover assertions,
  including an old process paused before external I/O and resumed after takeover.
- Exercise normal progress, global active/pending/retention limits, known replay at
  capacity, SIGTERM drain, timeout/output/descendant cleanup and preserved-volume
  restart.
- Retain negative failures and useful recovered progression.
- A process exit or health file alone does not prove business completion.
- The combined phase gate remains in its work item, distinct from complete
  charter/media/release claims.

### Inquiry workloads

- For inquiry workload changes, read the
  [H1 work item](../../docs/work-items/0014-p1-phase-h-workload-baseline.md) and
  preserve its frozen declaration, source-bound installed execution, independent
  result reconciliation and owned cleanup.
- Keep actual observations distinct from declared totals, polling latency from
  supplier completion, and cgroup accounted memory from resident set size (RSS).
- Preserve the separately passed H2 reliability and I26 host/Linux
  artifact/API/genuine-consumer gates.
- Remaining media and real-inference/release assertions stay separate.

## Handoff

- Record the behavior changed, acceptance IDs, interface/migration decisions, exact
  commands, observed results and remaining work.
- Update implementation status only when evidence supports it.
- Keep offline, local-media and live-model results separate.
- Record assistance and personal contributions accurately.
