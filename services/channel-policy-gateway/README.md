# Channel policy gateway application

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Explain how to build, test and change the Node gateway of the joined voice/SMS showcase |
| Audience | Engineers who build, test or change the gateway; coding agents |
| Scope | Node source reads, worker read HTTP, room control and operation bridge; excludes the joined launch |
| Owns | Gateway runtime behavior, worker read interface, resource limits and validation |
| Related | [Design](Design.md) · [Agent instructions](AGENTS.md) · [Joined application README](../channel_policy_demo/README.md) · [Work item 0045](../../docs/work-items/0045-joined-native-channel-policy.md) |

## Overview

This Node application is the Node side of the
[joined local application](../channel_policy_demo/README.md). It reads persisted
Channel Continuity Kit (P2) inputs through the kit's public APIs. Durable input
and dispatch remain in P2 (channel continuity). Execution, issuance and delivery
remain in P1 (agent continuity).

This README is for engineers who build, test or change the gateway.
[Design.md](Design.md) explains its design, limits and failure handling.

## Implementation status

| Capability | Status | Evidence |
| --- | --- | --- |
| Bounded source reader | Implemented | Focused positive/negative/lifecycle tests |
| Trusted native/SMS owner selection | Implemented | Selects from stored provider/event identity |
| Discovery and original prepared frame | Implemented | Read composition; actual joined PostgreSQL gate pending |
| Worker read HTTP | Implemented | Loopback transport with real local HTTP tests; actual joined PostgreSQL gate pending |
| Public gateway application | Implemented | Default nine owners; opt-in room control adds one and native context adds two; component tests cover ordered startup/drain |
| Original operation bridge and runtime | Implemented | Preliminary actual signed-SMS/execution/result joins observed |
| Explicit owner bootstrap | Implemented | Fresh P1/P2 schemas and private profile observed with read-only verification |
| Scripted specialist host | Implemented | Genuine public SDK fixed-policy handler, immutable evidence and separate one-key role; actual local HTTP invocation passed |
| Room control and worker attachment | Implemented | Closed epoch/generation commands and one actual public native prepare client; old capabilities cannot retarget a new room |
| Current-room context | Implemented | Public rehydration facade/server using existing storage, with before/after room checks; actual joined PostgreSQL/media gate pending |
| Actual native/current-result integration | Partial | Component wire/interoperability checks and selected actual journeys exist in [0046](../../docs/work-items/0046-joined-showcase-providers-and-demo.md); full joined qualification remains open |
| Joined dispatch deadlines | Implemented | Step deadline in [0047](../../docs/work-items/0047-open-findings-schema-upgrades-and-landing.md); bridge budget and claim lease in [0048](../../docs/work-items/0048-code-audit-fixes-and-documentation-cleanup.md) |

### Limits and deadlines

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Dispatch step deadline (`dispatchTimeoutMs`) | 5,000 ms | Both gateways | Reference deadline |
| Bridge per-call budget (`timeoutMs: 5000` in `runtime.ts`) | 5,000 ms | Each operation bridge lookup or accept | Equals the step deadline |
| Client call budget (`callTimeoutMs` in `operation-bridge.ts`) | 5,000 ms | P2 `ExternalOperationClient` | The bridge passes its own budget |
| Bridge default | 1,500 ms | Operation bridge | Replaced by the runtime budget |
| Client default | 2,000 ms | P2 `ExternalOperationClient` | Replaced by the bridge budget |
| Claim lease, newly prepared joined profiles | 8,000 ms | Dispatch claims; persisted by `local-setup/scripts/channel_policy_setup.py` | Exceeds the step deadline |
| Claim lease, earlier profiles | 5,000 ms | Profiles prepared earlier | Kept |

The runtime passes 5,000 ms through both layers rather than inheriting either
shorter default. The 8,000 ms lease leaves room for a receipt near the step
deadline, subject to the fresh database-time guard. Scheduling, SQL or network
delay can still leave a call unknown; the original identity and actual owner
remain retained for reconciliation.

### Room End and application stop

Room End first fences native HTTP intake and settles already admitted accepts,
then drains the original accepted inputs to known dispatch receipts while their
grant and dispatch dependencies remain available. It closes the native client
and read owners before revoking the binding. This does not wait for a policy
result or cancel business work.

If End retires a prepare already awaiting the same room's worker, that prepare
may select the existing deterministic background path within the same dispatch
claim. This exception requires the same captured closing room, a live caller
signal and an unexpired room. Active-room failures, foreign bindings, aborts and
expiry do not receive it; the P2 store still checks the original grant.

| Drain limit | Value | Failure behavior |
| --- | --- | --- |
| Process-local native fences | 1,024 retained bearer hashes | A new fence at capacity is rejected |
| History inspected | Sixteen total account-history rows, before binding filtering | Overflow leaves cleanup incomplete |
| Concurrent actual drains | Two | Additional drains are rejected |
| Drain retry-admission window | 20 seconds | Already admitted actual work remains owned |

Blocked, exhausted, expired, revoked or unresolved inputs can keep the room
Closing. Reobservation cannot create authority or a replacement operation.
Application close drains the room before quiescing both dispatchers, then closes
their read and storage dependencies. The Python Parent's origins stay available
until the launcher observes that dispatch barrier. See the
[lifecycle work item](../../docs/work-items/0050-lifecycle-drain-and-documentation-cleanup.md)
for corrective validation; full joined qualification remains separate.

### Startup resources

| Configuration | Owners created at startup | PostgreSQL pools |
| --- | --- | --- |
| Default | Nine | Six |
| With room control | Ten | Six |
| With the native bridge | Twelve | Six |

All variants retain the same six PostgreSQL pools.

## Documentation

| Document | Purpose |
| --- | --- |
| [Design](Design.md) | Design, limits and failure handling |
| [Agent instructions](AGENTS.md) | Agent rules for changing the gateway |
| [Work item 0045](../../docs/work-items/0045-joined-native-channel-policy.md) | Phases, gates and measured outcomes of the joined application |
| [Work item 0047](../../docs/work-items/0047-open-findings-schema-upgrades-and-landing.md) | Open findings, including the shared 5,000 ms dispatch step |
| [Work item 0048](../../docs/work-items/0048-code-audit-fixes-and-documentation-cleanup.md) | Audit fixes, including the bridge budget and claim lease |
| [Joined application](../channel_policy_demo/README.md) | The Python application that launches this gateway |

## Requirements

| Requirement | Version or value | Notes |
| --- | --- | --- |
| Host Node | 24.22.2 | Validated host version |
| pnpm | 12.18.0 | Frozen environment |
| P2 and specialist public packages | Built | Build them first; see [Commands](#commands) |
| Import side effects | None | Imports perform no environment, PostgreSQL, provider or listener activity |
| Construction I/O | Deferred | Until an explicit start |
| Public P2 owners | Borrowed | The source reader borrows them |
| Case and operation clients | Runtime-owned | The runtime owns these borrowed clients outside the application |

## Commands

### Build the JavaScript dependencies

From the repository root after frozen workspace installation, build the
dependencies:

```sh
pnpm --filter @livekit-ecosystem/channel-continuity build
pnpm --filter @livekit-ecosystem/delegation-specialist build
pnpm --filter @livekit-ecosystem/channel-policy-gateway build
```

### Component checks

Then run the component checks:

```sh
pnpm --filter @livekit-ecosystem/channel-policy-gateway typecheck
pnpm --filter @livekit-ecosystem/channel-policy-gateway test
pnpm --filter @livekit-ecosystem/channel-policy-gateway build
```

| Task | Command | Notes |
| --- | --- | --- |
| Type-check | `pnpm --filter @livekit-ecosystem/channel-policy-gateway typecheck` | Sources and tests |
| Test | `pnpm --filter @livekit-ecosystem/channel-policy-gateway test` | Focused, local HTTP and fake-port tests |
| Build | `pnpm --filter @livekit-ecosystem/channel-policy-gateway build` | Compiles the gateway |

These are component commands, not a joined application launch procedure. The
[joined application README](../channel_policy_demo/README.md) documents the launch.

### Optional room control and native bridge

| Option | Default | Allowed values | Description |
| --- | --- | --- | --- |
| `--room-control` | Not set | Path to a private JSON configuration | Opt-in room control |
| `--native-bridge` | Not set | Path to a private JSON configuration; only with `--room-control` | Opt-in native bridge |

- The optional room-control and native-bridge configurations are separate
  private JSON files.
- The command-line interface (CLI) accepts `--native-bridge` only with
  `--room-control`.
- The prepare endpoint is fixed to loopback. Caller input cannot choose a worker
  URL or scope.
- The Parent room owner publishes and attaches one original room before native
  generation.

These entrypoints are implemented components. They are not a joined demo launch.

## Validation

| Check | Command | What it proves | Status |
| --- | --- | --- | --- |
| Focused tests | `pnpm --filter @livekit-ecosystem/channel-policy-gateway test` | Original Unicode bytes, both source owners, scope and changed-payload rejection, overflow, pending gaps, finite errors and retained actual reads after a waiter timeout | Passed |
| Actual local HTTP tests | `pnpm --filter @livekit-ecosystem/channel-policy-gateway test` | Credentials, request and response caps, client abandonment, incomplete headers and startup/socket-close ordering | Passed |
| Composition tests with fakes | `pnpm --filter @livekit-ecosystem/channel-policy-gateway test` | Composition and ownership | Passed |
| Strict types | `pnpm --filter @livekit-ecosystem/channel-policy-gateway typecheck` | Sources and tests type-check | Passed |
| Joined database and native media qualification | Not yet available | Actual PostgreSQL and native media behavior | Pending |

The passed rows record the `make frontend-check` run in
[0048](../../docs/work-items/0048-code-audit-fixes-and-documentation-cleanup.md),
which covered the gateway's tests, types, formatting and build. Fakes test
composition and ownership. These component checks do not establish database or
native media qualification; those gates are in
[0045](../../docs/work-items/0045-joined-native-channel-policy.md).

## Next milestone

| Step | Outcome | Gate |
| --- | --- | --- |
| Repeat current-room and guarded result-disclosure checks after lifecycle changes | Fresh evidence for the implemented current-room composition | [Lifecycle follow-up](../../docs/work-items/0050-lifecycle-drain-and-documentation-cleanup.md) |
| Finish the frozen composed gateway/executor qualification | Composed gateway and executor qualified | Frozen composed gateway/executor gate in [0045](../../docs/work-items/0045-joined-native-channel-policy.md) |

Native media, provider inference and the compact browser flow keep their
separate gates.
