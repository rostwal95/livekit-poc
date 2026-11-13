# Channel policy gateway application

Status: Active
Last reviewed: 13 November 2026

## Overview

The Node side of the [joined local application](../channel_policy_demo/README.md)
reads persisted Channel Continuity Kit inputs through its public APIs. Durable
input and dispatch remain in P2; execution, issuance and delivery remain in P1.

## Implementation status

| Component | State |
| --- | --- |
| Bounded source reader | Implemented with focused positive/negative/lifecycle tests |
| Trusted native/SMS owner selection | Implemented from stored provider/event identity |
| Discovery and original prepared frame | Implemented read composition; actual joined PG gate pending |
| Worker read HTTP | Implemented loopback transport with real local HTTP tests; actual joined PG gate pending |
| Public gateway application | Default nine owners; opt-in room control adds one and native context adds two; ordered startup/drain covered by component tests |
| Original operation bridge and runtime | Implemented; preliminary actual signed-SMS/execution/result joins observed |
| Explicit owner bootstrap | Fresh P1/P2 schemas and private profile observed with read-only verification |
| Scripted specialist host | Genuine public SDK fixed-policy handler, immutable evidence and separate one-key role; actual local HTTP invocation passed |
| Room control and worker attachment | Implemented closed epoch/generation commands and one actual public native prepare client; old capabilities cannot retarget a new room |
| Current-room context | Implemented public rehydration facade/server using existing storage; before/after room checks; actual joined PG/media gate pending |
| Actual native/current-result integration | Component wire/interoperability checks pass; parent/browser/provider composition remains in progress |

## Documentation

Read [agent instructions](AGENTS.md), [design](Design.md) and the
[work item](../../docs/work-items/0045-joined-native-channel-policy.md).

## Requirements

Use the validated host Node 24.22.2, frozen pnpm 12.18.0 environment and built
P2/specialist public packages. Imports
perform no environment, PostgreSQL, provider or listener activity. Construction
keeps I/O deferred until explicit start. The source reader borrows public P2
owners; startup creates nine default resources, ten with room control and twelve
with the native bridge. All variants retain the same six PostgreSQL pools.
The runtime owns the borrowed case and operation clients outside that application.

## Commands

From the repository root after frozen workspace installation:

```sh
pnpm --filter @livekit-ecosystem/channel-continuity build
pnpm --filter @livekit-ecosystem/delegation-specialist build
pnpm --filter @livekit-ecosystem/channel-policy-gateway build
```

Then run the component checks:

```sh
pnpm --filter @livekit-ecosystem/channel-policy-gateway typecheck
pnpm --filter @livekit-ecosystem/channel-policy-gateway test
pnpm --filter @livekit-ecosystem/channel-policy-gateway build
```

These are component commands, not a joined application launch procedure.

The optional room-control and native-bridge configurations are separate private
JSON files. The CLI accepts --native-bridge only with --room-control. Its prepare
endpoint is fixed to loopback; caller input cannot choose a worker URL or scope.
The parent publishes and attaches one original room before native generation.
These entrypoints are implemented components; they are not a joined demo launch.

## Validation

Focused tests cover original Unicode bytes, both source owners, scope and changed
payload rejection, overflow, pending gaps, finite errors and retained actual reads
after waiter timeout. Actual local HTTP tests cover credentials, request/response caps,
client abandonment, incomplete headers and startup/socket-close ordering. Fakes
test composition and ownership; these checks do not establish
database or native media qualification.

## Next milestone

Connect one current native room and guarded result disclosure, then finish the
frozen composed gateway/executor qualification. Native media, provider inference
and the compact browser flow keep their separate gates.
