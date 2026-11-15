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
| Actual native/current-result integration | Partial | Component wire/interoperability checks pass; gap: parent/browser/provider composition remains in progress |
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

Because the runtime and the bridge pass 5,000 ms, neither the bridge's 1,500 ms
default nor the client's 2,000 ms default can cut off a slow accept inside the
5,000 ms dispatch step. With the 8,000 ms lease, a receipt that arrives near the
step deadline still passes the claim guard.

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
| Connect one current native room and guarded result disclosure | One connected current room with guarded result disclosure | None named yet |
| Finish the frozen composed gateway/executor qualification | Composed gateway and executor qualified | Frozen composed gateway/executor gate in [0045](../../docs/work-items/0045-joined-native-channel-policy.md) |

Native media, provider inference and the compact browser flow keep their
separate gates.
