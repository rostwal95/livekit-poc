# Channel Continuity Kit

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Introduce the P2 TypeScript SDK and gateway and show how to construct, upgrade, run and validate each public capability |
| Audience | Engineers who integrate the package or change it; coding agents |
| Scope | P2 TypeScript exports, owner schema upgrades and local gates; topic contracts and the Python adapter have their own guides |
| Owns | P2 product onboarding: capability status, schema version index, requirements, commands and the local gate index |
| Related | [V1 charter](../../docs/projects/channel-continuity-scope.md) · [Project design](Design.md) · [Project instructions](AGENTS.md) · [Python adapter](python/README.md) · [Task plan](../../docs/implementation/p2-channel-continuity.md) |

## Overview

The Channel Continuity Kit (project P2) is a TypeScript SDK and gateway that
preserve a travel-support case across LiveKit voice, browser text and simulated
SMS. A small Python package provides the version-1 codec and optional native
LiveKit adapters, described in its [package guide](python/README.md). The
[V1 charter](../../docs/projects/channel-continuity-scope.md) defines behavior and
the stable P2 acceptance IDs.

For each public capability this guide describes construction and shutdown, bounds,
the owner schema upgrade and the local gate that qualifies it. Topic guides own the
detailed contracts for communication evidence, current-case reads, the operations
view, the workload study and the installed starter. This guide links to them rather
than repeating them.

### Contents

- Getting started: [Implementation status](#implementation-status),
  [Documentation](#documentation), [Requirements](#requirements) and
  [Commands](#commands).
- Intake and dispatch: [Contracts and durable intake](#contracts-and-durable-intake),
  [Recoverable committed-inbox dispatch](#recoverable-committed-inbox-dispatch),
  [Bounded fake-SMS gateway](#bounded-fake-sms-gateway) and
  [Isolated scripted agent process](#isolated-scripted-agent-process).
- Case changes: [Investigation revision routing](#investigation-revision-routing)
  and [Linked exact confirmation](#linked-exact-confirmation).
- Outbound messages: [Durable outbound replies](#durable-outbound-replies),
  [Authenticated callback evidence](#authenticated-callback-evidence) and
  [Explicit uncertain-send recovery](#explicit-uncertain-send-recovery).
- Native voice and text: [Native application composition](#native-application-composition),
  [Response and playback evidence](#response-and-playback-evidence),
  [Current-case context across rooms and channels](#current-case-context-across-rooms-and-channels)
  and [Original result receipts and current-native reads](#original-result-receipts-and-current-native-reads).
- Profiles and applications: [Bounded workload profile](#bounded-workload-profile),
  [Read-only channel operations](#read-only-channel-operations) and
  [Installed standalone starter](#installed-standalone-starter).
- Quality and plans: [Validation](#validation) and [Next milestone](#next-milestone).

### Terms used in this guide

| Term | Meaning |
| --- | --- |
| Task IDs (I01–I22) | Implementation slices P2-I01 to P2-I22 from the [granular implementation plan](../../docs/implementation/p2-channel-continuity.md), not product acceptance IDs |
| Acceptance IDs (P2-01 to P2-17) | Stable scenarios in the V1 charter, which remains authoritative |
| Owner and runtime roles | The trusted migration owner installs and upgrades schemas; serving code uses the restricted runtime role and runs no data definition language (DDL) |
| Quiescent upgrade | An owner upgrade run while serving processes are stopped |
| Acknowledged input | Input persisted in the inbox; the acknowledgement (ACK) follows the commit |
| Dispatched | The cooperating investigation port acknowledged durable acceptance; this does not mean a business action, carrier send or case mutation completed |
| Unknown or uncertain | An outcome that could not be established, such as a lost acknowledgement; it stays unknown unless an explicit lookup, where one exists, resolves it |
| Selected qualification | A passing local gate for a chosen slice; it does not complete a P2 charter row |

## Implementation status

Every Qualified capability in the table below is implemented and passed its
selected local gate. Each linked work item records the slice's observed checks,
selected qualification and remaining limits.

Selected qualification of a slice does not complete a P2 charter row. All seventeen
complete P2 charter rows remain planned, and complete native and media charter
scenarios remain separate. The existing transport echo and M1 intake remain
separate foundation capabilities.

### Capability status

| Capability | Status | Evidence | Entry points |
| --- | --- | --- | --- |
| I01/I02: [Version-1 event contracts and codec](#version-1-contracts-and-codec) | Qualified | [0022](../../docs/work-items/0022-p2-channel-contracts.md) | Default codec; Python `channel_continuity` |
| I03–I05: [Verified PostgreSQL intake](#verified-postgresql-intake) | Qualified | [0024](../../docs/work-items/0024-p2-verified-durable-intake.md), [0026](../../docs/work-items/0026-p2-postgres-inbox.md) | `./security`, `./postgres`, `./migrations` |
| I06: [Standalone fake-carrier example](#standalone-fake-carrier-demonstration) | Qualified | [0027](../../docs/work-items/0027-p2-standalone-and-p3-http.md) | `./standalone`, `examples/fake-carrier.ts` |
| I07: [Recoverable dispatch](#recoverable-committed-inbox-dispatch) | Qualified | [0028](../../docs/work-items/0028-p2-dispatch-and-p3-coordinator.md) | `./dispatch` |
| I08: [Bounded loopback gateway](#bounded-fake-sms-gateway) | Qualified | [0029](../../docs/work-items/0029-p2-gateway-and-p3-issued-execution.md) | `./gateway` |
| I09: [Scripted agent process](#isolated-scripted-agent-process) | Qualified | [0030](../../docs/work-items/0030-p2-agent-recovery-and-p3-completion.md) | `./agent-process` |
| I10: [Investigation revision routing](#investigation-revision-routing) | Qualified | [0031](../../docs/work-items/0031-revision-routing-and-delegation-acceptance.md) | `./routing`, `./reference-case` |
| I11: [Linked exact confirmation](#linked-exact-confirmation) | Qualified | [0032](../../docs/work-items/0032-linked-confirmation-and-result-projections.md) | `./confirmation`, `./prompt-registry` |
| I12: [Durable outbound replies](#durable-outbound-replies) | Qualified | [0033](../../docs/work-items/0033-outbound-replies-and-completion-processing.md) | `./outbox`, `./fake-sms-send` |
| I13: [Authenticated callback evidence](#authenticated-callback-evidence) | Qualified | [0034](../../docs/work-items/0034-callback-evidence-and-applicability-refresh.md) | `./callbacks` |
| I14: [Explicit uncertain-send recovery](#explicit-uncertain-send-recovery) | Qualified | [0035](../../docs/work-items/0035-send-policy-and-action-races.md) | `./idempotent-fake-sms`, outbox recovery controllers |
| I15/I16: [Native text and committed voice](#native-application-composition) | Qualified | [0036](../../docs/work-items/0036-native-input-and-deadline-cancellation.md) | `./native`, Python `[native]` extra |
| I17: [Response and playback evidence](#response-and-playback-evidence) | Qualified | [0037](../../docs/work-items/0037-playback-evidence-and-process-recovery.md) | `./communication`, `channel_continuity.native_communication` |
| I18: [Current-case context](#current-case-context-across-rooms-and-channels) | Qualified | [0038](../../docs/work-items/0038-case-rehydration-and-standalone-release.md) | `./rehydration`, `channel_continuity.native_rehydration` |
| I19: [Bounded workload profile](#bounded-workload-profile) | Qualified | [0039](../../docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md) | `ChannelInbox.telemetryMetrics()`, workload gate |
| I20: [Read-only channel operations](#read-only-channel-operations) | Qualified | [0040](../../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md) | `./operations`, `./operations-types` |
| I21: [Installed standalone starter](#installed-standalone-starter) | Qualified | [0041](../../docs/work-items/0041-standalone-channel-and-durable-policy.md) | `./starter`, `p2-channel-starter` |
| I22 prerequisite: [Original result receipts and current-native reads](#original-result-receipts-and-current-native-reads) | Qualified | [0043](../../docs/work-items/0043-stable-result-delivery-and-return-context.md) | `./result-receiver`, `./result-receiver-types` |
| I22 prerequisite: [Operation-only client](#operation-client-without-provider-scaffolding) | Qualified | [0044](../../docs/work-items/0044-origin-bound-channel-policy.md) | `./starter` `OperationClientConfig` |
| I22: fresh-agent, supported-platform and integrated release evidence | Planned | [Next milestone](#next-milestone) | Not applicable |
| Integrated native voice/text/SMS journey | Planned | [Next milestone](#next-milestone) | Not applicable |
| Complete P2 charter rows (P2-01 to P2-17) | Planned | [V1 charter](../../docs/projects/channel-continuity-scope.md) | Not applicable |

### Storage schema versions

The inbox schema advances only through explicit owner calls from `./migrations`.
Run each upgrade under quiescence, after the previous version. Serving code never
installs, upgrades or repairs a schema and performs no DDL. Each capability section
states its own upgrade and compatibility rules.

| Version | Owner call | Adds | Section |
| --- | --- | --- | --- |
| v1 | `installChannelSchema` | Inbox, receipts, sender associations and pending processing intents | [Intake](#verified-postgresql-intake) |
| v2 | `upgradeChannelSchemaV2` | Dispatch claims and attempts, prepared investigations and immutable dispatch limits | [Dispatch](#recoverable-committed-inbox-dispatch) |
| v3 | `upgradeChannelSchemaV3` | Durable replies, authorized routes, suppression and send attempts | [Outbound replies](#durable-outbound-replies) |
| v4 | `upgradeChannelSchemaV4` | Authenticated callback evidence and the reservation veto | [Callbacks](#authenticated-callback-evidence) |
| v5 | `upgradeChannelSchemaV5` | Immutable provider operations and recovery commands | [Recovery](#explicit-uncertain-send-recovery) |
| v6 | `upgradeChannelSchemaV6` | Bounded native grants | [Native](#native-application-composition) |
| v7 | `upgradeChannelSchemaV7` | Three communication tables | [Response evidence](#response-and-playback-evidence) |
| v8 | `upgradeChannelSchemaV8` | Original result receipts | [Result receipts](#original-result-receipts-and-current-native-reads) |
| v9 | `upgradeChannelSchemaV9` | Three operating indexes; changes no row | [Result receipts](#owner-upgrades-v8-and-v9) |

## Documentation

### Topic guides in this project

| Document | Purpose |
| --- | --- |
| [Source-qualified communication](COMMUNICATION.md) | The I17 response and playback evidence contract |
| [Current-case rehydration](REHYDRATION.md) | The I18 read-only context contract |
| [Bounded channel workload profile](WORKLOAD.md) | The I19 workload study |
| [Channel operations](OPERATIONS.md) | The I20 read-only operations view |
| [Installed channel starter](STARTER.md) | I21 configuration, commands, bounds and shutdown |
| [Python adapter](python/README.md) | The codec and optional native adapters |

### Project and shared documents

| Document | Purpose |
| --- | --- |
| [Project instructions](AGENTS.md) | Coding-agent rules for this project |
| [Project design](Design.md) | P2 architecture, state ownership and trade-offs |
| [V1 scope and acceptance matrix](../../docs/projects/channel-continuity-scope.md) | Authoritative P2 behavior and acceptance IDs |
| [Granular implementation plan](../../docs/implementation/p2-channel-continuity.md) | Phase gates, task prerequisites and failure evidence |
| [Shared architecture](../../Design.md) | Ecosystem data flow, state authority and ports |
| [Validation plan](../../docs/validation-plan.md) | Test lanes and evidence rules |
| [Technology baseline](../../docs/technology-baseline.md) | Selected versions and validation boundaries |
| [Harness guide](../../harness/README.md) | Harness commands and outcome semantics |
| [Local stack setup](../../local-setup/README.md) | Host requirements and lifecycle commands |
| [Local console](../../apps/local-console/README.md) | The browser operator console |

The implementation plan's task IDs are not product acceptance IDs; the charter
remains authoritative.

## Requirements

| Requirement | Version or value | Notes |
| --- | --- | --- |
| Python environment | Pinned root runtime with the frozen `uv.lock` | Install all declared extras and development dependencies before the full fast suite; service, Agents SDK and inference-boundary tests require them |
| Pure intake subset | Standard library only | No extra dependencies |
| External inference credentials | None | Not needed |
| Docker and Compose | Compose 2+ | Runs the shared lab with pinned images; see the [local setup guide](../../local-setup/README.md) for host requirements and lifecycle commands |
| PostgreSQL lanes | Documented restricted-role local setup | Local init, start and prepare-postgres, plus the pinned host Node toolchain |
| Selected versions | [Technology baseline](../../docs/technology-baseline.md) | Records selected versions and validation boundaries |

## Commands

Run every command from the repository root.

| Task | Command | Notes |
| --- | --- | --- |
| Prepare the frozen Python environment | `uv sync --frozen --all-extras --dev` | All declared extras and development dependencies |
| Type-check the package | `corepack pnpm --filter @livekit-ecosystem/channel-continuity typecheck` | Pinned toolchain |
| Run the package tests | `corepack pnpm --filter @livekit-ecosystem/channel-continuity test` | Pinned toolchain |
| Build the package | `corepack pnpm --filter @livekit-ecosystem/channel-continuity build` | Pinned toolchain |
| Run the project Python tests | `.venv/bin/python -m unittest discover -s projects/channel-continuity/tests -v` | Codec and adapter tests |
| List P2 harness cases | `.venv/bin/python -m harness list --project p2` | None |
| Run the fast lane | `HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh --module p2` | Runs all current Python suites |
| Run P2 acceptance scenarios | `.venv/bin/python -m harness run --project p2` | Currently reports incomplete with exit 2 |

The same sequence, to run from the repository root:

```sh
uv sync --frozen --all-extras --dev
corepack pnpm --filter @livekit-ecosystem/channel-continuity typecheck
corepack pnpm --filter @livekit-ecosystem/channel-continuity test
corepack pnpm --filter @livekit-ecosystem/channel-continuity build
.venv/bin/python -m unittest discover -s projects/channel-continuity/tests -v
.venv/bin/python -m harness list --project p2
HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh --module p2
.venv/bin/python -m harness run --project p2
```

The final command currently reports incomplete with exit 2, because product
acceptance scenarios remain unimplemented. A passing structural check does not
complete those scenarios. The fast lane runs all current Python suites even when
its structural checks focus on this project.

### Local gate commands

Each capability section describes its gate, prerequisites and what the gate
proves. This index lists the commands in one place.

| Task | Command | Notes |
| --- | --- | --- |
| Run the [full PostgreSQL lane](#running-the-postgresql-intake-lane) | `make p2-postgres-check` | 23 cases |
| Run the [standalone examples](#standalone-fake-carrier-demonstration) | `.venv/bin/python local-setup/scripts/p2_postgres_check.py --example` | Two standalone cases |
| Run the [dispatch lane](#running-the-dispatch-lane) | `.venv/bin/python local-setup/scripts/p2_postgres_check.py --dispatch` | Five cases |
| Run the [gateway lane](#running-the-gateway-lane) | `make p2-gateway-check` | Three process and socket cases |
| Run the [scripted agent case](#running-the-agent-recovery-case) | `.venv/bin/python local-setup/scripts/p2_postgres_check.py --agent` | One selected case |
| Run the [revision routing lane](#running-the-routing-lane) | `.venv/bin/python local-setup/scripts/p2_routing_check.py` | Equivalent standalone and P1 fixtures |
| Run the [linked confirmation lane](#running-the-confirmation-lane) | `.venv/bin/python local-setup/scripts/p2_confirmation_check.py` | Actual local gate |
| Run the [outbound replies lane](#running-the-outbox-lane) | `local-setup/scripts/p2_outbox_check.py` with a fresh `--report` path | Use a fresh report path |
| Run the [callback checks](#running-the-callback-checks) | `make p2-callbacks-check` | Plus earlier storage lanes |
| Run the [uncertain-send recovery checks](#running-the-send-policy-checks) | `make p2-send-policy-check` | Plus earlier lanes and an installed consumer |
| Run the [native composition gate](#native-example-and-shutdown) | `make p2-native-check` | Owns PostgreSQL, LiveKit and browser orchestration |
| Run the [response and playback evidence gates](#communication-validation) | `make p2-communication-check`, `make p2-playback-check` | Storage and playback-media gates |
| Run the [current-case context gates](#current-case-context-across-rooms-and-channels) | `make p2-rehydration-check`, `make p2-rehydration-media-check` | Storage and media gates |
| Run the [result receiver lane](#running-the-result-receiver-lanes) | `make p2-result-receiver-plan`, then `make p2-result-receiver-check` | Plan first |
| Run the [result receiver package lane](#running-the-result-receiver-lanes) | `make p2-result-receiver-package-plan`, then `make p2-result-receiver-package-check` | Plan first |
| Run the [workload study](#bounded-workload-profile) | `make p2-workload-plan`, then `make p2-workload-check` | Plan first |
| Build and check the [operations page](#building-and-checking-the-operations-page) | `make p2-operations-build`, `make p2-operations-plan`, `make p2-operations-check` | Build, plan, then check |
| Run the [starter gate](#installed-standalone-starter) | `make p2-standalone-plan`, then `make p2-standalone-check` | Plan first |

## Contracts and durable intake

This section covers the version-1 contracts (I01/I02), verified PostgreSQL intake
(I03–I05) and the standalone fake-carrier example (I06).

### Version-1 contracts and codec

P2-I01/I02 implement strict version-1 event data contracts, a real TypeScript text
producer, a pure Python codec and shared positive and negative fixtures.

- Outputs are immutable.
- Canonical semantics distinguish retry observations from changed payloads or
  destinations.
- Parsers compare separately trusted scope. They do not authenticate an adapter,
  verify association or acknowledge durable acceptance.

The [contract work item](../../docs/work-items/0022-p2-channel-contracts.md) owns
this slice's observed checks and limitations.

### Verified PostgreSQL intake

Explicit server subpaths implement scope-bound fake-SMS authentication,
seeded-account association and the PostgreSQL inbox, receipts and pending
processing intent. Acceptance follows commit, and replay returns the original
receipt. See the [verified-intake contract](../../docs/work-items/0024-p2-verified-durable-intake.md)
and the [PostgreSQL work item](../../docs/work-items/0026-p2-postgres-inbox.md).

### Running the PostgreSQL intake lane

After the documented local init/start/prepare-postgres and pinned host Node setup,
run:

```sh
make p2-postgres-check
```

This lane runs actual association and intake transactions. It also terminates an
owned process after commit but before acknowledgement, then replays, without P1 or
P3 services.

- It creates and cleans only marked disposable schemas.
- The fixture shares the existing restricted runtime credential. It does not
  establish independent P2 database principals.
- It starts no carrier or agent and sends no SMS.
- To retain a run, use a fresh `--report` path with
  `local-setup/scripts/p2_postgres_check.py`.
- Offline tests never connect to PostgreSQL or silently skip this lane.

The full lane runs 23 cases. It includes the standalone examples and the dispatch,
gateway and agent cases described in later sections.

### Standalone fake-carrier demonstration

With the same restricted local PostgreSQL setup and pinned Node prerequisites, run:

```sh
.venv/bin/python local-setup/scripts/p2_postgres_check.py --example
```

This command builds the current public exports and the example, then runs only
the two standalone cases. Two separate processes run `examples/fake-carrier.ts`
through its declared public package imports. The output contains actual accepted
and replayed receipt IDs, stable operation keys and sequence, with
pending/not_executed clearly shown.

- No P1 or P3 service, carrier account, model or provider key is used.
- Only marked disposable schemas are created and cleaned. No default workspace
  state or volumes are reset.
- Optional `--report` uses a fresh exclusive path under `.local/validation/p2-postgres`.
  Existing reports are never overwritten.
- The normal `make p2-postgres-check` lane also includes these examples in its full
  23-case run.

The repository package's demo script can run the same compiled entry against an
already prepared demo schema, with explicit `P2_DEMO_SCHEMA`, `P2_POSTGRES_PORT`
and `P2_RUNTIME_PASSWORD`. Its runtime process refuses migration credentials.
Prefer the wrapper above for complete setup, validation and cleanup.

The I06 example composes explicit inbox, synthetic read-only case, scripted-agent
and pending-operation-inspection ports:

- The synthetic case adapter is a read-only fixture. The agent produces a scripted
  interpretation. The operation adapter only inspects a pending reference.
- The inbox receipt and processing intent are durable. The fake operation
  observation is not an executed business action.
- Acceptance and preview are separate: adapter failure cannot erase an observed
  committed receipt.
- Actual fresh processes confirmed the same receipt and operation key after replay.
- The operation remains pending/not_executed. The preview helper claims no fake
  business-action durability, dispatch or delivery.
- The preview helper rejects nonpending processing state after a dispatcher has
  claimed or dispatched the input.
- A standalone helper closes only its preview resources. Its caller must also close
  the supplied `ChannelInbox`, as the example does even after a preview or cleanup
  failure.

The [phase handoff](../../docs/work-items/0027-p2-standalone-and-p3-http.md) owns
final shared evidence and limitations.

## Recoverable committed-inbox dispatch

I07 adds a bounded persisted investigation-dispatch step and explicit lookup-only
reconciliation through the declared `./dispatch` package export. The
[dispatch handoff](../../docs/work-items/0028-p2-dispatch-and-p3-coordinator.md)
records its evidence.

### Dispatcher API

`ChannelDispatcher` requires explicit case, scripted-agent and cooperating
operation adapters.

| Method | Behavior |
| --- | --- |
| `step(accountToken, receiptId)` | Requests one unit of durable work. |
| `reconcile(accountToken, receiptId)` | Only looks up the immutable original scope, key and payload digest, even after ordinary attempts are exhausted or the sender is reassigned. It never generates a new plan or invokes accept. |
| `inspect` | Returns a bounded attempt history and the authoritative processing state. |

`dispatched` means the investigation port acknowledged durable acceptance. It does
not mean a business action, carrier send or case mutation completed.

### Dispatch owner upgrade and limits

New schemas remain version 1 until an explicit `upgradeChannelSchemaV2` call with
owner settings. Runtime cannot install, alter or repair its schema. The upgrade
preserves canonical input, receipt, sequence, association and operation key.

Quiesce serving processes for an owner upgrade, and take a restorable database
backup for retained deployments. The disposable qualification proves preservation
and rejects drift. It is not a general production backup and restore deployment
procedure.

The owner chooses immutable dispatch limits at upgrade:

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Active leases | 2 (default) | Dispatch schema | None |
| Attempts | 3 (default) | Each input | None |
| Lease | 5,000 ms (default) | Each claim | Qualifying fixtures use 500 ms |
| Retry delay | 250 ms (default) | Between attempts | Qualifying fixtures use 20 ms |

The qualifying fixtures use the shorter lease and delay to exercise actual expiry.
The current global admission guard favors correctness over throughput and is not
a scale benchmark.

### External acceptance and uncertainty

- Prepared investigation payloads are immutable and bounded to 32 KiB.
- The store reserves `possible_external` before invoking accept outside database
  locks.
- An unknown acknowledgement stays uncertain. A lease protects local observations;
  it is not an external execution fence.
- The operation adapter must durably deduplicate scope, key and digest and provide
  authoritative lookup. Its fixture is stored in a separate marked schema and is
  not a second SDK business-execution ledger.
- No background scheduler, hidden memory queue or automatic retry loop is
  installed.
- Two locally admitted calls have a whole-step deadline. Timed-out ignored adapter
  work retains its slot until settlement, and incomplete cleanup is reported.

### Running the dispatch lane

With the same local PostgreSQL and pinned host Node prerequisites:

```sh
.venv/bin/python local-setup/scripts/p2_postgres_check.py --dispatch
```

This explicit five-case lane exercises the declared `./dispatch` export, the
versioned owner upgrade, concurrent claims and admission, expiry and takeover, and
bounded unknown acknowledgements. It also sends a real SIGKILL after a separate
cooperating operation fixture commits. A fresh dispatcher then recovers the
original operation receipt by lookup.

The full lane includes these five cases. The standalone two-case demo continues to
show pending/not_executed. Use a fresh `--report` path for retention.

## Bounded fake-SMS gateway

I08 adds a bounded loopback gateway, `ChannelGateway` from the declared `./gateway`
export. Actual acknowledged-input process-kill and restart evidence is recorded in
the [gateway phase handoff](../../docs/work-items/0029-p2-gateway-and-p3-issued-execution.md).

### Gateway construction and routes

Applications construct `ChannelGateway` with explicit database, integration,
accounts and ports settings. The finite account seeds supply trusted recovery
credentials. Request JSON cannot supply a processing scope. `listen()` binds only
127.0.0.1 and defaults to an ephemeral port.

The host must explicitly install or upgrade to v2 before startup. The runtime
receives no owner credential and executes no DDL.

| Route | Meaning and authentication |
| --- | --- |
| `POST /webhooks/fake-sms` | Exact raw JSON with `application/json`, `Content-Length`, `X-P2-Timestamp` and `X-P2-Signature`. The existing signed-provider and current-association checks precede durable acceptance. |
| `GET /receipts/{id}` | Bearer account credential. Returns a scoped processing observation, never action or booking completion. |
| `GET /health` | Local process and driver health. It does not prove model, carrier, business execution or database readiness for a future operation. |

### Polling and dispatch

One owned driver polls due pending or expired claims with persisted attempt
limits. It rotates configured accounts, bounds each candidate page and honors a
two-second tick eligibility budget. Normal ingress does not pause committed work.

Webhook bytes are verified with a hash-based message authentication code (HMAC)
before a pooled connection or the admission lock is taken. Freshness is still
checked with database time inside the transaction. A pooled connection is reused
after a clean rollback. It is discarded only when the rollback fails or a commit
outcome is uncertain.

Each existing dispatcher step has its own finite deadline (see `dispatchTimeoutMs`
below for its defaults). A composition whose case and operation ports cross process
bridges should set the same budget for every gateway, because a step that expires
after a possible accept leaves that input uncertain. Uncertain exhausted work
requires explicit SDK lookup-only reconciliation. The gateway cannot invent
another acceptance.

Polling also skips uncertain input that is held because its sender association
or native binding is gone (last code `association_required`). That input is
parked outside automatic eligibility. It needs an explicit `step`, which rechecks
current permission, or a lookup-only `reconcile`, which never needs that
permission.

### Gateway options and bounds

Pass these optional settings in the constructor's `options` object:

| Option | Default | Allowed values | Description |
| --- | --- | --- | --- |
| `batchSize` | 4 | 1–16 | Candidate page size for each scan |
| `pollMs` | 100 ms | 20–1,000 ms | Poll cadence |
| `idlePollMs` | `pollMs` | `pollMs`–5,000 ms | Longest pause while idle; the pause doubles after each idle cycle up to this ceiling |
| `dispatchTimeoutMs` | 5,000 ms for native input, 2,000 ms otherwise | 20–5,000 ms | Deadline for one dispatcher step |
| `startupMs` | 5,000 ms | 20–10,000 ms | Startup observer budget |
| `cleanupMs` | 2,000 ms | 20–5,000 ms | Close budget |

- `idlePollMs` is opt-in. The idle pause resets to `pollMs` only when a step
  dispatches work or a newly accepted local intake nudges the loop. A nudge also
  wakes a paused loop at once. Eligible rows that dispatch nothing back off like
  an idle cycle.
- The [0047 work item](../../docs/work-items/0047-open-findings-schema-upgrades-and-landing.md)
  records why `idlePollMs` and `dispatchTimeoutMs` were added and how the joined
  composition uses them.

The listener bounds are fixed:

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Open sockets | 16 | Listener | None |
| Active requests | 4 | Listener | None |
| Raw headers | 16 headers and 8 KiB | Each request | None |
| Header time | 1 second | Each request | None |
| Body time | 2 seconds | Each request | None |
| Raw fake-SMS input | 32 KiB | Each webhook body | None |
| Response | 16 KiB within 1 second | Each response | None |

Keep-alive, pipelining, duplicate headers, transfer encoding and arbitrary routes
do not expand resources.

### Gateway startup, close and observers

- A caller timeout during startup retains the underlying I/O until actual cleanup
  and cannot leave a late serving bind.
- Close stops admission and polling. It observes actual sockets, handlers and the
  driver before closing both SQL owners. Incomplete cleanup is a failure.
- A failed close of the gateway, its dispatcher, the dispatch store or the inbox
  can be retried. The retry observes the retained work again, and each store ends
  its database pool at most once.
- Observer notifications are capped at eight. The application owns any external
  resources created by its observer.

### Acknowledgement semantics and the test hook

Only the explicit trusted `harnessAfterAcknowledgement` test hook gates dispatch,
while the fixture observes a fully flushed receipt. Request data cannot choose that
hook.

Acknowledged means persisted input. Dispatched means cooperating investigation
acceptance. Neither means a completed booking action.

A future default Docker/UI composition is separate from this installed library and
the explicit process demonstration.

### Running the gateway lane

With the same explicit local PostgreSQL setup:

```sh
make p2-gateway-check
```

This command runs three real process and socket cases using the declared
`./gateway` export:

1. Normal authenticated acceptance and dispatch.
2. SIGKILL after a flushed HTTP receipt but before dispatch.
3. Useful progress after a revoked sender is blocked.

Fresh gateway processes recover due input from PostgreSQL. No
acknowledgement-owned memory queue carries it. Replay preserves the original
receipt, operation key, prepared input and cooperating acceptance. The complete
23-case PostgreSQL lane includes these cases.

The case and agent adapters are synthetic and read-only. The operation fixture
persists independently and grants no booking authority. Native voice/browser, a
real carrier and model quality remain separate gates.

## Isolated scripted agent process

I09 adds the explicit server-only `./agent-process` export. It provides the
`AgentProcess` adapter and the trusted worker helper `runAgentWorker`. A live gateway
survives an independently killed scripted worker, observes persisted claim expiry
and replays the same immutable input, case and operation context through a new
worker. Attempts remain visible while the cooperating operation accepts one
logical investigation. The [agent recovery handoff](../../docs/work-items/0030-p2-agent-recovery-and-p3-completion.md)
records its evidence.

### Agent configuration and trust

Constructing either library starts no listener or child. Application configuration
selects a trusted absolute Node module and finite allowed account scopes. Received
message or model data cannot select code, environment, scope or process IDs.

```ts
import { AgentProcess } from '@livekit-ecosystem/channel-continuity/agent-process';
const agent = new AgentProcess({
  modulePath: '/absolute/path/to/trusted-scripted-worker.mjs',
  allowedScopes: [{ tenantId: 'tenant-a', accountId: 'account-a' }],
});
// Supply agent.port as the gateway/dispatcher's plain agent port.
// The application closes both gateway and agent in its lifecycle finally block.
await agent.close();
```

- The trusted worker module calls `runAgentWorker` with its own `allowedScopes`
  and a scripted read-only prepare function.
- The exact canonical stdin context digest binds the returned scope, receipt,
  operation key, case revision and message facts.
- Only explicitly configured `P2_AGENT_` environment fields enter the child, at
  most 16 fields and 4 KiB. No ambient PG, provider, Node-options or target
  selectors are inherited.
- Module code is trusted and must keep its descendants inside the owned process
  group.

### Process limits and cleanup

Each explicit prepare call owns one fresh POSIX process group. Default limits:

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Active workers | 1 | `AgentProcess` | Configurable up to 2 |
| Work budget | 1 second | Each prepare call | None |
| Input | 32 KiB | Each prepare call | None |
| Response | 2 KiB | Each prepare call | None |
| stderr | 4 KiB | Each prepare call | None |
| Cleanup observer budget | 1 second | Each prepare call | None |

- Abort or timeout rejects the waiter and terminates its owned group. The actual
  slot is retained until child exit, pipe close and group disappearance.
- There is no implicit retry queue. The gateway and dispatcher own persisted retry
  eligibility separately.
- Cleanup failures retain the actual slot until the group is observed gone,
  including unexpected cleanup exceptions.
- Local process isolation does not establish a memory or CPU sandbox,
  remote-provider cancellation, model quality or production capacity.
- Applications own observer-created resources and close `AgentProcess` separately
  from the gateway.

### Worker success counters

The `succeeded` counter and the `settled` event with code `ok` describe a validated
worker that has already exited and whose group and streams are gone. A slow
synchronous observer can still delay caller delivery. In that case, the final
signal and monotonic guard rejects the late delivery and increments
`waiterRejected`. Known worker-completion observations are not relabelled as a
successful caller response.

### Running the agent recovery case

With the documented local restricted-role PostgreSQL setup:

```sh
.venv/bin/python local-setup/scripts/p2_postgres_check.py --agent
```

This selected case uses actual gateway HTTP, an independent owned scripted agent,
a PostgreSQL-clock lease observation and a SIGKILL before any prepared or external
operation. It then verifies two identical context hashes, visible attempts and one
logical operation acceptance.

The full 23-case lane includes all earlier 22 cases. Only synthetic data and
marked disposable state are used. Native model/media and complete P2 acceptance
remain separate.

## Investigation revision routing

I10 adds explicit investigation revision routing through one selected case
authority, with equivalent standalone PostgreSQL and public P1 fixtures. The
[routing handoff](../../docs/work-items/0031-revision-routing-and-delegation-acceptance.md)
records its evidence.

The server-only `./routing` export provides `RevisionRouter`, `CaseAuthorityPort`,
`CaseAuthorityHttpClient`, fixed `RoutingError` codes and a strict command
producer. Routing is an explicit application call after intake. The gateway and
dispatcher do not automatically consume these commands.

### Structured revision command

The accepted body is structured JSON, not natural-language interpretation:

```ts
import { encodeRevisionCommand } from '@livekit-ecosystem/channel-continuity/routing';

const body = encodeRevisionCommand({
  schemaVersion: 1,
  kind: 'case.revise_investigation',
  expectedRevision: '0',
  request: {
    schemaVersion: 1,
    kind: 'booking_investigation',
    bookingReference: 'DEMO-BK-001',
    newCheckIn: '2030-12-11',
    investigationConsent: true,
  },
});
```

- Persist this body through the verified input adapter.
- `RevisionRouter.route` takes only the authenticated account credential and the
  original receipt ID. It reads that accepted body and derives scope, case,
  operation and message identity from the retained record. There is no body,
  proposal or scope override argument.
- Provider timestamps remain diagnostic observations.
- Expected revisions are canonical decimal strings from zero through the
  PostgreSQL signed 64-bit maximum. The optional numeric event revision must agree
  with the command.
- Unsupported or noncanonical text causes clarification without an authority call.

### Routing outcomes and lost replies

- The selected authority returns a known revised or unchanged snapshot, or a fixed
  conflict or unknown outcome. A current inspection is an independent observation.
- After a lost committed reply, matching current payload and revision cannot
  establish which command won.
- There is no automatic retry, rebase, durable revision-command receipt or
  inference of original acceptance.
- Investigation consent permits a case request revision. Exact quote confirmation
  and supplier mutation remain separate.

### Router construction and shutdown

Applications construct the router from an `AcceptedInputPort`, a
`CaseAuthorityPort` and trusted scope/case bindings. The router's defaults are
bounded:

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Trusted scope/case bindings | 64 | Router construction | At most |
| Slots | 2 (default) | Router calls | Timeout or abort retains an ignored adapter's actual slot until settlement |
| Budget | 2 seconds (default) | Router calls | None |

- Applications close the router and the supplied inbox and authority clients
  independently.
- `CleanupIncomplete` never certifies a clean shutdown.
- Metrics and fixed event/code logs exclude body, credentials and case identifiers.

### Choosing a case authority

| Composition | Case authority | Behavior |
| --- | --- | --- |
| Standalone | `ReferenceCaseAuthority` from the separate `./reference-case` export | Serves existing state with two connections and two active operations, and performs no runtime DDL |
| Integrated | `CaseAuthorityHttpClient` with the explicitly started local application bridge in `local-setup/scripts/p2_case_bridge.py` | The bridge maps trusted account/case bindings to preconstructed public P1 `CaseControlClient` values and calls only `case` and `revise` |

- For standalone composition, `installReferenceCaseSchema` explicitly creates a
  marked v1 synthetic authority with 1–64 owner-seeded cases.
- Integrated mode never creates a reference copy of P1 case state. There is no
  implicit bridge deployment or dependency on a P3 service.

### Association boundary

`ChannelInbox.inspect` authenticates original retained-account access. It does not
revalidate a sender's current association, and the router adds no atomic
association-revocation fence. Native committed input, confirmation association,
revocation races and complete P2-05/P2-12 remain separate gates.

### Running the routing lane

With the documented restricted-role local PostgreSQL setup:

```sh
.venv/bin/python local-setup/scripts/p2_routing_check.py
```

The equivalent fixtures use actual signed SMS, PostgreSQL locks and an observed
two-caller blocking graph. They require:

- one revision winner and one conflict despite skewed provider times;
- valid next-revision progress;
- unchanged requests;
- original receipt replay;
- postcommit lost-acknowledgement uncertainty.

Independent owner inspection checks the complete P1 mapping and request, and zero
quotes, confirmations, intents or supplier effects. Only marked disposable state is
removed. This selected I10 scope does not register a complete charter row or
qualify native media.

## Linked exact confirmation

I11 adds immutable exact-quote prompt bindings, linked confirmation routing and a
current-association preflight. The
[confirmation handoff](../../docs/work-items/0032-linked-confirmation-and-result-projections.md)
records its evidence.

- The server-only `./confirmation` export adds `ConfirmationRouter` and the
  separate `ConfirmationHttpClient` capability.
- `./prompt-registry` provides explicit `installPromptRegistry` and
  `PromptRegistry`.
- The default codec and the fake-SMS v1 wire are unchanged.
- `ReferenceCaseAuthority` remains investigation-only. For standalone use,
  applications supply a narrow atomic `ConfirmationAuthorityPort`. Integrated mode
  uses public P1 exact-quote commitment through the opt-in local bridge.

### Publishing a quote prompt

A trusted controller obtains a real supplier-bound v2 quote through the public P1
producer. It then publishes an immutable prompt with a distinct publisher
credential. The prompt binds account, logical case, conversation, response ID,
decimal revision, quote ID, SHA256 and the complete original canonical quote JSON.

- Registry publication validates the bounded byte envelope and digest. The P1
  parser and the atomic authority validate the actual issued quote.
- Opaque quote bytes retain large integer literals exactly.
- Quote IDs follow P1's canonical UUID contract, including deterministic UUIDv5
  proposals. Operation, intent and effect IDs remain UUIDv4.
- The publication credential is a trusted application role, separate from seeded
  account credentials. No model tool or input body selects it. The local runtime
  still uses the documented shared PostgreSQL role.
- Response identity is unique within tenant/account. Reusing it for another case,
  conversation or quote conflicts.
- Replay of an existing publication returns its original observation even at
  capacity. A new publication at capacity is explicitly rejected.
- Prompts have no automatic pruning or permanent agent allocation.
- A recorded prompt does not assert sending, playback, hearing or comprehension.

### Confirming by SMS

An accepted SMS can explicitly answer `YES <responseId>`. A bare YES requires both
an existing trusted event `replyToResponseId` and `expectedCaseRevision`. Without
them, the router asks for clarification. The optional structured command preserves
the full decimal revision and exact digest:

```ts
import { encodeConfirmation } from '@livekit-ecosystem/channel-continuity/confirmation';

const body = encodeConfirmation({
  schemaVersion: 1,
  kind: 'case.confirm_quote',
  responseId: prompt.responseId,
  expectedRevision: prompt.revision,
  quoteDigest: prompt.quoteDigest,
  explicit: true,
});
```

### Preflight and commitment

`ConfirmationRouter` requires both the retained authenticated `inspect` and the
separate `inspectForConfirmation` input method. When routing a confirmation, it:

1. Resolves the original immutable prompt.
2. Performs the current original-association preflight immediately before
   commitment, checking that the complete original input identity still matches.
   `ChannelInbox.inspectForConfirmation` rejects a revoked or reassigned original
   epoch. Ordinary retained history remains readable by its original account.
3. Sends only the original explicit user consent plus the bound prompt to the
   authority. P1 validates scope, exact quote and revision, expiry, cancellation
   and command identity inside its commitment transaction.

The preflight is not an atomic P2-to-P1 revocation fence. A revocation after
preflight remains outside this slice's guarantee.

- Stale or ambiguous input asks for clarification. There is no current-case read,
  rebase or model-derived consent.
- The original inbox operation UUID is the confirmation command ID.
- A lost commitment acknowledgement stays unknown. An explicit same-input replay
  can retrieve P1's original intent/effect receipt, including after case
  cancellation or expiry while the association remains eligible.
- This router rejects replay after association revocation and exposes no
  lookup-only historical-receipt route. The durable P1 receipt remains a fact.

### Confirmation bounds and shutdown

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Owned calls | 2 (default) | `ConfirmationRouter` | At most; ignored adapters retain actual capacity after timeout |
| Observation budget | 2 seconds | `ConfirmationRouter` | None |
| Close budget | 1 second | `ConfirmationRouter` | None |

- The HTTP client uses a fresh bounded loopback socket, requires
  `Connection: close` and retains request and socket ownership until both actually
  close.
- Applications also close their input, prompt registry and authority clients.
- The bridge requires `allow_confirmation=True` explicitly. I10-only bindings do
  not gain confirmation.

### Running the confirmation lane

```sh
.venv/bin/python local-setup/scripts/p2_confirmation_check.py
```

The actual local gate covers:

- signed stale, unlinked and current replies;
- publisher separation;
- immutable nonce and cap behavior;
- an observed two-caller revise/confirm race;
- lost acknowledgement and original replay;
- one leased fake supplier change;
- late cancellation;
- known revoked or reassigned input denial;
- independent PostgreSQL and supplier truth.

Default UI/Compose, native media, real inference, automatic gateway routing and
full P2-06/P2-12 registration remain separate. P2 `processing_intents` describe the
existing investigation dispatcher; exact-confirmation truth is the P1 receipt.

## Durable outbound replies

The additive I12 server exports `./outbox` and `./fake-sms-send` provide durable
reply acceptance, versioned authorized routes, recipient-level suppression and
ordinary local fake sends. Qualification and remaining boundaries are recorded in
the [phase handoff](../../docs/work-items/0033-outbound-replies-and-completion-processing.md).
A queued receipt, provider acceptance and human acknowledgement are separate facts.

### Outbox owner setup

Owner setup is explicit and requires serving processes to quiesce before upgrade:

```ts
import {
  installChannelSchema, upgradeChannelSchemaV2, upgradeChannelSchemaV3,
} from '@livekit-ecosystem/channel-continuity/migrations';

await installChannelSchema(ownerDatabase);
await upgradeChannelSchemaV2(ownerDatabase);
await upgradeChannelSchemaV3(ownerDatabase, {
  maxReplies: 1000, maxRoutes: 256, maxAttempts: 3,
});
```

- Existing v1 and v2 profiles continue to work. The outbox requires v3.
- Repeating owner installation or an older upgrade validates v3 and preserves it.
- The migration owner is trusted. Runtime lacks DDL and canonical
  UPDATE/DELETE/TRUNCATE privileges.

### Using the outbox

```ts
import { ChannelOutbox } from '@livekit-ecosystem/channel-continuity/outbox';
import { FakeSmsSendClient } from '@livekit-ecosystem/channel-continuity/fake-sms-send';

const carrier = new FakeSmsSendClient(
  { host: '127.0.0.1', port: fakeCarrierPort }, fakeCarrierAuthorization, providerScope,
);
const outbox = new ChannelOutbox(
  runtimeDatabase, fakeSmsIntegration, seededAccounts,
  [{ token: publisherToken, scope: accountScope, caseId, conversationId }], carrier,
);
try {
  const receipt = await outbox.enqueue(publisherToken, {
    schemaVersion: 1, outboundId, responseId, body: 'Your investigation result is ready.',
  });
  await outbox.selectRoute(accountToken, {
    senderId, associationVersion, expectedRouteVersion: '0',
  });
  const send = await outbox.send(accountToken, receipt.outboundId);
  const retained = await outbox.inspect(accountToken, receipt.outboundId);
  // Render send.status and retained evidence; never invent delivery or hearing.
} finally {
  const results = await Promise.allSettled([outbox.close(), carrier.close()]);
  if (results.some(result => result.status === 'rejected')) throw new Error('CleanupIncomplete');
}
```

- The application supplies and separately closes any `ChannelInbox` used to
  establish associations. Import opens no listener or connection.
- Runtime APIs authenticate retained recipient reads. A newly reassigned sender
  cannot read the old recipient's outbox.
- `pending(accountToken, limit)` returns at most 32 eligible logical IDs and owns no
  scheduling queue.
- Each explicit `send` admits at most one attempt.

### Publishers and immutable replies

- A publisher is a distinct trusted application capability. Its binding supplies
  recipient identity. The draft cannot select tenant, account, case, conversation,
  provider or address.
- The original scoped outbound UUID, response reference and exact 4096-byte UTF-8
  body are immutable.
- Equal replay returns its original receiver, receipt, digests and time even at
  capacity. A changed payload conflicts.
- Receiver identity persists in owner-installed settings. The opt-in
  [v8 result receiver](#original-result-receipts-and-current-native-reads) uses the
  original P1 delivery UUID while retaining its result digest separately. This
  envelope digest does not replace P1 result identity.

### Routes, suppression and reservation

- Route version is a decimal int64 compare-and-set (CAS) value, with zero meaning
  absent. Selecting a route requires its current exact verified association.
- `setSuppressed` is scoped to the immutable tenant/account/conversation.
  Suppression survives address replacement.
- Missing, revoked or suppressed routes hold before a send attempt is created.
- Reservation shares the inbox admission guard with association changes and
  records the exact address, epoch and version before external I/O. Changes
  committed afterward cannot cancel an already admitted call or retarget its old
  attempt.

### Send attempts and results

- An immutable possible-send record precedes the carrier call. A separate immutable
  result records `accepted_by_provider` or `definitive_not_accepted`.
- A missing or unvalidated result is `unknown` and blocks another send, including
  after restart or route change.
- Only definitive nonacceptance permits another explicit attempt, with a fresh
  local attempt and provider operation UUID and the same logical recipient.
- The provider key for an unknown attempt remains frozen.
- The I12 slice itself has no automatic retries, callbacks or provider
  lookup/resend policy. [Callbacks](#authenticated-callback-evidence) and
  [explicit recovery](#explicit-uncertain-send-recovery) are later, separate slices.
- Provider acceptance is not physical delivery, playback, hearing, human
  acknowledgement or booking consent.

### Outbox bounds and shutdown

The owner passes these settings to `upgradeChannelSchemaV3`:

| Option | Default | Allowed values | Description |
| --- | --- | --- | --- |
| `maxReplies` | 1000 | Up to 10000 (owner maximum) | Retained replies |
| `maxRoutes` | 256 | Up to 10000 (owner maximum) | Route records |
| `maxAttempts` | 3 | Up to 5 (owner maximum) | Attempts per reply |

Runtime bounds:

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Actual sends | 2 (default) | Each outbox instance | Maximum 4 |
| Send waiter | 2 seconds (default) | Each send | Maximum 5 seconds |
| Close | 2 seconds | Outbox close | None |

- SQL uses the existing two connections and finite statement, lock and query
  budgets.
- Ordinary store calls are limited to four. `recordResult` and `recordRecovery`
  have their own separate four-slot admission, so a known carrier result is still
  recorded while ordinary calls are busy. At most eight store calls share the two
  pooled connections.
- These are configured bounds, not measured capacity or a global physical-send
  concurrency guarantee.
- Timed-out ignored work retains actual capacity. Late known results can persist
  while the caller stays unknown.
- The application owns carrier shutdown separately and must inspect incomplete
  cleanup.

### Running the outbox lane

With the same restricted local PostgreSQL and pinned Node setup:

```sh
.venv/bin/python local-setup/scripts/p2_outbox_check.py --report .local/validation/p2-outbox/fresh-run.json
```

The explicit lane uses only new UUID-owned schemas and a synthetic loopback
carrier. It performs:

- an actual owner pg_dump/psql backup and restore;
- original and new inbox-dispatch compatibility;
- an owned kill after committed enqueue;
- a real revocation/reservation blocking graph;
- route, suppression and reassignment negatives;
- ordinary fake acceptance and definitive failure;
- fresh-process unknown inspection.

It does not reset application volumes or call providers. Use a fresh report path.
Failed, missing, skipped, timed-out or incomplete-cleanup runs do not pass.

## Authenticated callback evidence

The additive I13 server-only `./callbacks` export authenticates raw fake-provider
reports, retains immutable attempt-correlated evidence and exposes a deterministic
contradiction view. It provides `CallbackInbox`,
`createFakeSmsCallbackIntegration`, `signFakeSmsCallback` and the pure
`reduceCallbackEvidence` rule. Provider reports do not grant resend authority. See
the [callback phase handoff](../../docs/work-items/0034-callback-evidence-and-applicability-refresh.md)
for qualification and remaining boundaries.

### Callback setup

Imports start no listener. Supply explicit database settings, a callback-specific
integration and `SeededAccounts`. The application owns its HTTP listener. The SDK
owns authentication, its SQL pool and admitted tasks. An existing inbound-SMS
integration is not a callback credential.

Run the quiesced owner upgrade after v3:

```ts
import { upgradeChannelSchemaV4 } from '@livekit-ecosystem/channel-continuity/migrations';
import {
  CallbackInbox,
  createFakeSmsCallbackIntegration,
} from '@livekit-ecosystem/channel-continuity/callbacks';

await upgradeChannelSchemaV4(ownerDatabase);
const integration = createFakeSmsCallbackIntegration(providerScope, callbackHmacKey);
const callbacks = new CallbackInbox(runtimeDatabase, integration, accounts);
const receipt = await callbacks.accept(rawBody, { timestamp, signature });
const evidence = await callbacks.inspectAttempt(accountToken, { outboundId, attemptId });
await callbacks.close();
```

- `ownerDatabase` belongs only to the explicit setup job. Serving code uses the
  restricted runtime role.
- `callbackHmacKey` is supplied separately from the inbound SMS key and is never
  transmitted to account clients.
- This is synthetic fake-carrier qualification, with no paid provider or default
  callback service.
- v3 profiles retain their previous behavior until explicitly upgraded to v4.

### Callback contract

| Boundary | Contract |
| --- | --- |
| Raw callback | Exactly eight schema1 fields: `schemaVersion`, `eventId`, `attemptId`, `providerOperationKey`, `requestDigest`, `providerMessageId`, `state`, `occurredAt`. |
| Authentication | Callback-specific HMAC domain and key over trusted provider scope, transport timestamp and exact raw UTF-8 bytes. A 60-second window applies on every retry, including replay at the cap. |
| Identity | Scoped provider event ID. The semantic canonical payload includes `occurredAt`, message ID and state; the signature and retry envelope timestamp are excluded. |
| Correlation | Original persisted attempt ID, provider operation key, request digest and provider scope. The business recipient and case come from that immutable request. |
| Receipt | Original receipt UUID, event and attempt IDs, canonical payload digest and database accepted time. Replay returns the original receipt. |
| Account read | Retained account/case/conversation authentication. A reassigned phone owner cannot inherit old reports. |
| Unknown | No known send result is required. Reports arriving before a normal send ACK remain separate evidence. |
| Contradiction | Delivered or read plus failed, incompatible provider message IDs, or positive evidence against definitive send nonacceptance remain visible as conflicted. |
| Send veto | Any retained callback on any prior attempt blocks a NEW v4 reservation that would otherwise be eligible. It never retries or retargets. |

### Evidence reduction

- The reducer is commutative and timestamp-independent. It retains the strongest
  reported state, all reported provider IDs and fixed conflict reasons.
- Accepted then failed can be a normal provider lifecycle.
- A reported read or delivery is provider evidence, not human acknowledgement,
  consent or a physical-delivery guarantee.
- Original immutable send results remain available alongside the report view.

### Callbacks and new sends

Callback and new-send reservation share the existing admission guard. A callback
that arrives first vetoes a later reservation. A reservation that comes first
retains its admitted frozen attempt. A later report cannot retract an already
possible external call. `pending` is an advisory scan; `reserve` repeats the check
atomically.

### Callback capacity, timeouts and metrics

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Retained observations | 10000 (default) | Profile, globally | Maximum 100000 |
| Observations per attempt | Eight (default) | Each send attempt | Maximum 32 |
| Actual calls | Four | Callback inbox | Share two SQL connections |
| Waiter | Two seconds (default) | Each call | Maximum five seconds |

- Reads and authenticated equal replay remain available at capacity.
- There is no physical pruning. Receipts and provider event identity survive for
  the profile lifetime.
- Timeout or abort retains actual work until settlement.
- A close timeout reports `CleanupIncomplete`, and ownership remains until actual
  close.
- Metrics count accepted and replayed durable observations, public
  rejection/conflict/authentication failures, waiter rejections, actual active work
  and bounded telemetry failures and drops.
- Events use fixed enums only, with no raw body, phone, account, event or key
  labels.
- A late committed observation and a timed-out waiter are separate measured facts.

### Running the callback checks

From the repository root:

```sh
make p2-callbacks-check
.venv/bin/python -m unittest tests.test_p2_callbacks_gate
pnpm --filter @livekit-ecosystem/channel-continuity typecheck
pnpm --filter @livekit-ecosystem/channel-continuity test
```

The actual fixture owns bounded loopback HTTP peers and distinct runtime and owner
processes. It covers SQL-cancel upgrade rollback, a verified owned SIGKILL after
callback commit but before HTTP acknowledgement, fresh replay, and populated v4
pg_dump/psql recovery. Its provider ledger is independent synthetic test tooling.

For shared storage compatibility, also run the earlier 24-case outbox, 22-case
routing, 18-case confirmation and 23-case recovery lanes. The isolated installed
npm consumer checks strict public types without checkout imports or `@types/pg`.
See the stable phase handoff for exact evidence.

The I13 callback observations alone did not qualify ambiguous-send recovery. The
separate [I14 handoff](../../docs/work-items/0035-send-policy-and-action-races.md)
records the current uncertain-send evidence. Complete P2 charter and native
scenarios remain pending.

## Explicit uncertain-send recovery

The I14 `./idempotent-fake-sms` capability and explicit outbox recovery controllers
separate ordinary uncertain sends from a cooperating provider's same-key recovery.
I14 adds version 5 immutable provider operations, explicit lookup/retry controller
commands and conservative outbound-wide evidence fences. See the
[send-policy handoff](../../docs/work-items/0035-send-policy-and-action-races.md)
for qualification and boundaries.

- A non-idempotent lost response remains unknown and never opens a resend.
- Explicit commands retain immutable receipts. Idempotent retries keep the original
  provider operation, recipient, address and body across distinct local attempt
  IDs.
- No physical exactly-once or human-delivery claim follows from a provider's
  reported acceptance.

### Recovery owner upgrade and credentials

- Install owner versions 1→2→3→4→5 under quiescence, ending with
  `upgradeChannelSchemaV5`.
- Existing rows retain their bytes. v4 attempts are adopted permanently as ordinary
  operations.
- The runtime never upgrades or repairs a schema.
- Use a separately configured `recoveryControllers` credential inventory. Account
  and publisher credentials cannot authorize recovery commands.

### Recovery commands

| Method | Behavior |
| --- | --- |
| `reconcile(token,{commandId,outboundId,attemptId})` | Records one exact lookup permission and its separately sourced observation. |
| `retry(token,{commandId,outboundId,expectedAttemptId})` | May reserve one new invocation, only after current permission, callback and retained-operation checks. |
| `recoveryCommand(accountToken,commandId)` and `inspectRecovery(accountToken,outboundId)` | Expose retained history, including unresolved permissions and conflicts. |

Replaying either original command returns its original receipt without invoking
either carrier method. The application closes the outbox and the supplied HTTP
carrier client independently.

### Cooperating provider rules

- The cooperating fake capability binds a stable key to the original operation
  payload before its first possible call.
- A known terminal nonacceptance is a durable per-key tombstone. Lookup absence and
  transport failure remain unknown.
- A matching accepted observation holds a new retry.
- Any callback on any earlier attempt also vetoes a new reservation.
- Different route epochs may reauthorize the same original address. They cannot
  change the operation payload.
- Historical lookup after revocation can record truth but cannot restore send
  permission.
- Provider-contract contradictions are retained and stop future calls. They cannot
  retract an already admitted external call.

### Running the send-policy checks

Run `make p2-send-policy-check`, all package unit, type and build checks, the
earlier callback, outbox, routing, confirmation and recovery lanes, and an isolated
installed-package consumer. The selected synthetic lane includes real HTTP, SQL
contention, owned process kills and populated v5 backup/restore.

## Native application composition

The opt-in `./native` server composition and the Python `[native]` adapter connect
native `lk.chat` text and explicitly committed scripted voice to the same
PostgreSQL inbox and persisted dispatcher (I15/I16). The selected native
text/committed-audio composition uses explicit owner version 6. The
[native phase handoff](../../docs/work-items/0036-native-input-and-deadline-cancellation.md)
records qualification, exact local evidence and remaining boundaries.

- The adapter disables the SDK's automatic text consumer and suppresses automatic
  end-of-turn replies. Only a claimed dispatch may request native generation.
- Generation completion is an SDK observation, separate from browser playback,
  consent and a supplier effect.
- Scripted automatic speech recognition (ASR) maps the local voiced fixture to a
  fixed transcript. It is not general recognition or paid inference.

### Installing the native composition

Install the Python distribution with its explicit `native` extra to obtain the
frozen compatible Agents 1.8.11 edge. The default Python codec import remains free
of SDK initialization. TypeScript consumers import server capabilities from
`@livekit-ecosystem/channel-continuity/native`. Importing starts no listener.

### Native credentials and input binding

- The trusted application configures a separate publisher, account credential and
  room-binding bearer.
- A publisher binds immutable tenant, account, case, conversation, room and
  participant before an input is admitted.
- Browser tokens contain real-time communication (RTC) permission only.
- Neither a room label, an SDK stream ID nor a request-body account selector grants
  durable acceptance.
- Each input has an explicit stable UUID. Equal replay retains its original
  receipt, acceptance sequence and logical operation, while changed bytes conflict.

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Ingress JSON budget | 16384 bytes | Each native input | For at most 2048 raw UTF-8 text bytes, including worst-case JSON escaping |
| Prepare token | Exactly 43 characters | Prepare client `Authorization` argument | Passed as `Bearer <token>` |
| Native credentials | 32–128 characters | Publisher, account and binding credentials | Must differ |

### Native grants

- Owner `upgradeChannelSchemaV6` adds bounded native grants after version 5 under
  maintenance/quiescence. Serving code performs no DDL.
- The same existing inbox, conversation sequence and processing intents own
  acceptance.
- New prepare and reservation acquire the original admission/binding locks and
  recheck fresh PostgreSQL time. Expired or revoked grants block new work.
- Original account-authorized history remains available.
- An expiry after possible external admission cannot retract that already admitted
  call.
- Disconnect alone does not revoke a grant.

### Runtime ownership and generation

- `NativeRuntime` owns two bounded text readers, actual intake and preparation
  work, manual voice capture, the SDK lifecycle and bounded observations.
- Injected recognition must capture the original input UUID before asynchronous
  work and expose a genuine immutable final snapshot plus actual pending work. SDK
  interim promotion and commit completion alone do not establish final provenance.
- Every completed-user-turn hook raises `StopResponse`. Generation happens only
  through the dispatcher bridge after all original handoffs settle.
- Repeated voice commit uses the retained turn result.
- A new generation has a separate UUID and may repeat after recovery while the
  cooperating logical operation remains stable.

### Native example and shutdown

The example `examples/native_lab.py` is a separately launched, loopback-only,
scripted application with bounded HTTP and RTC ownership. The root native gate
(`make p2-native-check`) owns its PostgreSQL, LiveKit and browser orchestration. The example reads only its
explicit private fixture and media files.

- Applications separately close the native inbox/gateway, HTTP agent adapter,
  intake client, SDK runtime, RTC room and their injected providers.
- Timeout preserves actual in-flight work. Incomplete cleanup cannot be reported as
  success.
- The isolated native page is an application demonstration. It distinguishes
  accepted input, dispatch and SDK generation observations.
- The separate I17 communication profile adds generated, SDK and browser evidence
  and response-scoped interruption. Its measured gates are recorded in the linked
  handoff.
- The separate I18 read profile has its own contract and handoff. Real recognizers
  and inference, broader load and complete P2 acceptance retain later gates.

### Native generation metrics

- The `nativeGenerationAttempts` producer counts dispatched preparation attempts
  admitted after input/hook settlement and the first monotonic deadline check. It
  is separate from actual model invocations, which the scripted application
  records independently.
- A delayed started-observation publisher can exhaust the remaining budget. A fresh
  deadline/closed check then prevents any new SDK call.
- Completed replies count only actual successful `SpeechHandle` settlement.
- Observer failures include contained synchronous and asynchronous observer
  failures and logging-sink failures. Pending observations and observations
  dropped at the cap of eight are separate fixed counters.
- Library import attaches no handlers. The explicit application sanitizes SDK log
  fields and exceptions.

## Response and playback evidence

The opt-in I17 `./communication` export and the Python native communication profile
preserve source-qualified response anchors, actual generated text, SDK speech
settlement and client-reported playback. Generated text, SDK output, a browser
completion claim and business acceptance are independent facts. The
[I17 handoff](../../docs/work-items/0037-playback-evidence-and-process-recovery.md)
records qualification and remaining boundaries.

Read the [communication contract](COMMUNICATION.md) before enabling version 7. It
owns the API table, HTTP routes, storage caps, streaming bounds, projection meaning
and verification layers.

### Enabling communication evidence

- Enable the opaque `createCommunicationIntegration` with separate trusted
  publisher, SDK and browser credentials. Use `CommunicationInbox` and
  `CommunicationGateway` from `./communication`.
- Explicit owner `upgradeChannelSchemaV7` adds three tables after v6. Runtime
  performs no DDL.
- `beginResponse` binds the original accepted input receipt, operation, generation
  and SDK speech identity. `observeSdk` and `observeBrowser` append immutable facts.
- Account-authenticated `inspectResponse`, `responses` and `observations` read
  bounded coherent projections.
- The default native profile stays on its existing protocol and eighteen metrics.
- The native Python profile adds `NativeCommunicationHttpClient` and source capture
  through public SDK nodes. Only normal actual source exhaustion publishes full
  generated text.
- Actual large language model (LLM) and text-to-speech (TTS) tasks remain owned
  beyond a forced `SpeechHandle` watchdog settlement. Incomplete, error or overflow
  output cannot create a known preparation.

### Communication validation

Use the root communication-storage and playback-media gates documented in the
handoff (`make p2-communication-check` and `make p2-playback-check`), alongside unit
and type checks, the preceding native gate (`make p2-native-check`) and the old P2
storage regressions. Installed package checks prove public APIs outside the
checkout. Unit/mock, actual PostgreSQL, process-kill and browser/audio evidence
remain distinct.

## Current-case context across rooms and channels

Use `./rehydration` and `channel_continuity.native_rehydration` for the opt-in
read-only current-case profile (I18). The [contract](REHYDRATION.md) defines
current-grant admission, raw already-accepted SMS authentication, coherent P2
history and separately observed P1 facts, byte and page bounds, explicit idle
refresh and original room identity. The
[I18 handoff](../../docs/work-items/0038-case-rehydration-and-standalone-release.md)
records selected qualification.

- Context loading creates no accepted input, prepared operation, reply or
  generation.
- Old generated and playback evidence remains inert history.
- Reading revision zero is supported, while current native dispatch and
  communication keep their explicit positive-revision domain. The profile rejects
  unsupported zero-revision native input before acceptance.
- Broader valid-domain integration remains a release gate.

Its separate storage and media gates are `make p2-rehydration-check` and
`make p2-rehydration-media-check`.

## Original result receipts and current-native reads

The opt-in `./result-receiver` and browser-safe `./result-receiver-types` exports
implement original opaque result acceptance and a separate current-native-grant
read over explicit owner schema v8. This implemented API requires the existing
outbox and a native inbox on the same database and schema. This selected seam does
not complete a P2 charter row or the joined voice/text/SMS browser journey.

### Owner upgrades v8 and v9

- During an explicit quiescent owner step, call
  `upgradeChannelSchemaV8(ownerDatabase)` from `./migrations` after v7. It returns
  the existing receiver UUID and never rotates it.
- Serving code performs no DDL. Old APIs and owner upgrade entry points validate v8
  without downgrading it.
- `upgradeChannelSchemaV9(ownerDatabase)` is a later quiescent owner step after v8.
  It adds three operating indexes and changes no row. The indexes cover due
  processing intents, send attempts by provider operation, and recovery commands by
  outbound reply.
- Before it creates the indexes, the v9 upgrade takes ACCESS EXCLUSIVE locks on
  `schema_metadata`, `admission`, `processing_intents`, `send_attempts` and
  `send_recovery_commands`, then revalidates the schema. The locks change neither
  the v9 catalog nor its definition digest.
- An interrupted v9 upgrade rolls back exactly, and replaying v9 only revalidates
  it. Older upgrade entry points replay against v9, and every runtime store accepts
  v8 or v9.
- New joined-showcase profiles are created at v9. The
  [0047 work item](../../docs/work-items/0047-open-findings-schema-upgrades-and-landing.md)
  records the v9 change and its validation.

### Constructing the receiver and reader

A configured application supplies its existing owners and distinct capabilities:

```ts
import {
  ChannelResultReceiver, ChannelResultReader, parseResultIntent,
} from '@livekit-ecosystem/channel-continuity/result-receiver';

const route = { scope, caseId, conversationId, recipientId };
const receiver = new ChannelResultReceiver(outbox, {
  receiverId, bindings: [{ ...route, publisherToken }],
});
const reader = new ChannelResultReader(outbox, nativeInbox, currentCases, {
  receiverId, bindings: [route],
});
const intent = parseResultIntent(originalP1Canonical);
const receipt = await receiver.accept(publisherToken, intent);
const original = await receiver.find(publisherToken, intent);
const view = await reader.native(currentNativeBearer, intent.delivery_id);
```

- `accept` and `find` require the configured publisher capability.
- A native grant cannot publish. It authorizes only the separate scoped read. The
  reader's route bindings contain no publisher secret.
- This integration accepts the lowercase P3-compatible identifier subset of one
  through 64 characters. Unsupported or longer P2 identifiers are rejected rather
  than truncated or remapped.

### Intent, receipt and notice

The intent is exact sorted ASCII P1 canonical JSON.

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Intent | 16,384 bytes | Each intent | None |
| Decoded body | 8,192 bytes | The strict base64 body | Must match the original `result_sha256` |
| Timestamp integers | 0–4,102,444,800,000 ms | Intent timestamps | P1’s range |
| Notice body | 4,096 bytes | The fixed notice | Has a different digest |

- The six receipt fields remain `delivery_id`, `receipt_id`, `receiver_id`,
  `recipient_id`, `result_sha256` and `accepted_at_ms`.
- One protected outbox transaction retains that original intent and enqueues the
  fixed notice, “Your review result is ready. Rejoin this conversation to view
  it.”
- The original delivery UUID is the outbound UUID. Exact replay retains the
  original receipt even at capacity, while changed intent bytes or an ordinary
  reply UUID collision conflict.

### Current-native read path

Both facades share the existing outbox pool:

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| SQL connections | 2 | Shared outbox pool | Existing pool |
| Actual-call reservations | 4 | Shared outbox pool | Existing pool |
| Active operations | 2 | Receiver | At most |
| Active operations | 1 | Reader | At most |
| Native read request | 256 bytes | Local qualification host | None |
| SDK view | 32,768 bytes | Each read view | None |

- The reader retains its reservation while SQL is released for one public P1
  current-case read. It then locks and rechecks the original native grant with
  fresh database time before disclosure.
- `view.observed` separates P2 read, case read and disclosure times with
  `atomic: false`. Case revision equality does not grant result applicability,
  execution or consent.
- Receiver history remains available after native revocation, while
  current-channel disclosure is denied.

### Result receiver deadlines and shutdown

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Caller deadline | Two seconds (default) | Receiver | None |
| Caller deadline | Three seconds (default) | Reader | None |
| Cleanup observation | Two seconds | Both facades | None |

- Timeout or `CleanupIncomplete` retains actual ownership.
- Close these facade owners before their application-owned outbox, native inbox and
  current-case client.
- Ordinary possible SMS sends remain unknown and do not acquire automatic resend
  permission from result acceptance.

### Running the result-receiver lanes

From the repository root:

| Task | Command | Notes |
| --- | --- | --- |
| Declare the isolated schedule | `make p2-result-receiver-plan` | Starts no resources |
| Run the storage and return lane | `make p2-result-receiver-check` | Needs its reviewed restricted PostgreSQL setup and fixed bounds |
| Plan the installed package lane | `make p2-result-receiver-package-plan` | None |
| Run the installed package lane | `make p2-result-receiver-package-check` | Qualifies the isolated installed APIs |

- The selected 0043 run of the storage and return lane passed sixteen storage and
  four return assertions against real PostgreSQL, including
  commit-before-acknowledgement recovery, lookup-only reconciliation and populated
  backup/restore. These return reads use native grants without an RTC room. The
  0047 work item later added a v9 upgrade case to this lane (seventeen storage and
  four return assertions), and the lane passed.
- The separate package plan and check lanes have twenty copied fake-port tests and
  eight existing offline assertions. They do not repeat the twenty actual
  storage/return assertions of the 0043 run. The
  [0043 work item](../../docs/work-items/0043-stable-result-delivery-and-return-context.md)
  records that separate fresh installed-consumer qualification.
- Each lane requires its own passing report. Source execution does not substitute
  for an installed consumer.

## Bounded workload profile

The opt-in I19 [bounded workload profile](WORKLOAD.md) declares active overload,
retained-capacity replay, actual task settlement and one thousand dormant
conversations. `ChannelInbox.telemetryMetrics()` exposes the ordinary observer's
separate bounded pending/dropped/failure lane.

The [workload handoff](../../docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md)
records selected qualification. Process samples are observations rather than
production capacity claims. Run `make p2-workload-plan` for its fixed declaration
before the actual `make p2-workload-check`. The I20 joined UI is a separate gate.

## Read-only channel operations

The separate `./operations` and browser-safe `./operations-types` exports provide
an opt-in fixed-scope operator view (I20). The [operations contract](OPERATIONS.md)
defines current versus historical facts, explicit refresh, process-local metric and
span sources, exporter failure isolation and actual owner retention.

- `OperationsReader` joins the existing bounded P2 snapshot, a separately observed
  public current-case result and a fresh protected grant check.
- `OperationsReadServer` and `OperationsHttpClient` expose literal-loopback GET
  reads with request correlation and signed cursors bound to source, scope and
  section.
- No body or cursor grants mutation, retry, resend, dispatch or playback authority.
- `examples/operations-lab.ts` composes supplied owners without creating another
  database pool or work queue.
- Applications separately close their inbox, current-case adapter and injected
  exporter transport. A read timeout or Forget clears a caller view without proving
  that underlying work stopped.

### Building and checking the operations page

| Task | Command | Notes |
| --- | --- | --- |
| Build the dedicated console page | `make p2-operations-build` | Separate from the default P1 console and native controls |
| Declare the fixed local schedule | `make p2-operations-plan` | Starts no services |
| Run the operations gate | `make p2-operations-check` | Requires the reviewed restricted-role local setup and explicit gate bounds |

Normal PostgreSQL and browser results and isolated-package qualification are
recorded in the [0040 work item](../../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md).
No complete P2 charter row is closed by an offline model test, a process sample or
this selected operations interface.

## Installed standalone starter

The additive `./starter` application export and the `p2-channel-starter` bin (I21)
compose the existing SDK with explicit owner and runtime configuration, signed fake
SMS, the reference case authority and an application-owned synthetic external
receipt server.

- Route an accepted structured investigation while quiescent, before serving.
  Reply, callback and original-operation recovery remain explicit commands.
- No P1 or P3 deployment, model, new workflow queue or default service is started.
- The existing operations page remains read-only.

See [STARTER.md](STARTER.md) for private configuration, commands, bounds and
shutdown. The [0041 work item](../../docs/work-items/0041-standalone-channel-and-durable-policy.md)
records source-bound qualification and remaining release requirements.

### Operation client without provider scaffolding

The public `./starter` export also accepts a narrow `OperationClientConfig`. It
contains only the profile, the loopback endpoint, trusted
account/case/conversation/sender bindings with an operation bearer and an
optional `callTimeoutMs`. Native publishers can use this client without inventing
SMS provider metadata. See
[operation-only client construction](STARTER.md#operation-only-client-construction).

| Option | Default | Allowed values | Description |
| --- | --- | --- | --- |
| `callTimeoutMs` | `STARTER_LIMITS.externalCallMs` (2,000 ms) | 20 to 5,000 ms | Deadline for one external call |

- The two-argument form always uses the 2,000 ms default.
- The existing two-argument starter configuration remains supported.
- Both paths keep two actual calls, strict original canonical input checks and
  retained socket ownership through timeout and close.

The Python origin bridge is recorded in the completed
[0044 work item](../../docs/work-items/0044-origin-bound-channel-policy.md).
Focused TypeScript and Python unit and socket checks passed. Fourteen actual
PostgreSQL assertions qualified P2 intake to P1 policy work and current result data
reads. The integrated native/voice/SMS journey remains pending. A prepared input's
kind or receipt alone does not prove its source channel.

## Validation

The [V1 acceptance matrix](../../docs/projects/channel-continuity-scope.md) defines
required scenarios. The [shared validation plan](../../docs/validation-plan.md)
separates deterministic correctness, actual local media and real-model evidence.

| Check | Command | What it proves | Status |
| --- | --- | --- | --- |
| Package type, unit and build checks | The package commands in [Commands](#commands) | Source types, unit behavior and public exports | Required for every change |
| Project Python tests | `.venv/bin/python -m unittest discover -s projects/channel-continuity/tests -v` | Codec and adapter behavior | Required for every change |
| Fast lane | `HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh --module p2` | All current Python suites plus this project's structural checks | Required before handoff |
| Selected local gates | The [local gate commands](#local-gate-commands) | The behavior named in each capability section | Passed for each Qualified slice |
| P2 acceptance scenarios | `.venv/bin/python -m harness run --project p2` | Complete charter scenarios | Incomplete (exit 2) |
| Shared local stack smoke | See the [local setup guide](../../local-setup/README.md) | Readiness and transport only | Not product evidence |
| Local-ready V1 | The designated local checks | The Local-ready V1 release gate | Planned |
| Portfolio-ready V1 | Local-ready checks plus the required real-model runs, review, benchmark evidence and demonstration | The Portfolio-ready V1 release gate | Planned |

- Harness reports live under the ignored `.local/harness` directory.
- The shared local stack has separate readiness and transport smoke checks and
  persistent volumes. Its actual text and audio checks do not provide speech-to-text
  (STT), LLM, TTS or product V1 evidence.
- Normal stop/start preserves current local state. Use the documented explicit
  reset only when synthetic data removal is intended.
- Each capability section names its local gate and what it proves. Missing, skipped
  and timed-out requirements remain non-passing.

## Next milestone

Selected local slices are implemented and qualified by their linked handoffs. The
next gates follow them.

| Step | Outcome | Gate |
| --- | --- | --- |
| I12 durable replies, I13 authenticated callbacks and I14 explicit uncertain sends | Implemented and qualified, including isolated installed-package consumption | Linked phase handoffs [0033](../../docs/work-items/0033-outbound-replies-and-completion-processing.md), [0034](../../docs/work-items/0034-callback-evidence-and-applicability-refresh.md) and [0035](../../docs/work-items/0035-send-policy-and-action-races.md) |
| I15/I16 native text and committed audio | Implemented and qualified | Recorded in its own [handoff](../../docs/work-items/0036-native-input-and-deadline-cancellation.md) |
| I17 communication evidence | Implemented and qualified | Implementation and qualification boundaries in its [handoff](../../docs/work-items/0037-playback-evidence-and-process-recovery.md) |
| I18 current-case reads, described in [REHYDRATION.md](REHYDRATION.md) | Implemented and qualified | Selected evidence and limits in its [handoff](../../docs/work-items/0038-case-rehydration-and-standalone-release.md) |
| I19 workload qualification | Implemented and qualified | Tracked in its [separate handoff](../../docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md) |
| I20 read-only operations | Implemented and qualified | Qualified in [0040](../../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md) |
| I21 installed starter | Implemented and qualified | Qualified in [0041](../../docs/work-items/0041-standalone-channel-and-durable-policy.md) |
| P2-I22 | Fresh-agent, supported-platform and integrated release evidence | Next gate |
| Integrated native voice/text/SMS journey | An integrated journey across native voice, text and SMS | Next gate |
| Full P2 charter acceptance | All seventeen P2 rows pass | Separate gate |
| Broader native/media, integrated UI, supported-platform release and load | Wider qualification | Separate gates |

Throughout, preserve verification, association, durable input, exact consent and
immutable operation identity. Provider reports do not prove physical delivery.
