# Channel policy gateway coding instructions

Status: Active
Last reviewed: 13 November 2026

## Read first

Read the [root instructions](../../AGENTS.md), [README.md](README.md),
[Design.md](Design.md), the active [work item](../../docs/work-items/0045-joined-native-channel-policy.md)
and affected public P2 APIs/tests before editing.

## Owned paths

Own this Node application and its component tests. P2 owns storage, preparation
and channel authorization. The sibling Python application owns origin/executor
composition. Neither application adds another durable queue or execution ledger.

## Development rules

- Import public package exports only. Keep imports inert and configuration typed.
- Select native/SMS owners from a validated stored provider/event; a request's
  source label can only check consistency, never select a privileged owner.
- Rescan at most sixteen retained inputs from zero; expose overflow and examine
  later records past pending/unknown gaps. No terminal acknowledgement cursor.
- Return original prepared bytes and verify their input/op/scope/body/digest.
  A read cannot prepare, claim, dispatch or reassociate a source.
- Bound actual reads before awaiting. A timed-out waiter retains its slot. Drain
  actual operations before closing borrowed P2 owners; retry incomplete close.
- Use finite errors and numeric observations. Never log input, token, dependency
  exception text or per-ID metrics. Keep all provider keys outside this process.
- Keep HTTP hosting and setup explicit. Serving code performs no DDL. Normal
  stop preserves state; destructive reset requires a separate action.
- Preserve default configuration/CLI behavior. Room control and native bridge
  are separate opt-ins. The observed Node epoch/generation is authoritative;
  a publication or attachment retry keeps its exact original identity/capability.
- Matching current-room input requires an attached public native client. Missing
  attachment fails unavailable. Dormant/older retained inputs keep their separate
  deterministic background path; they cannot select the new room's worker.
- Stop and drain the actual per-room native client and context/read observers
  before releasing the room or admitting B. Public context HTTP remains an as-of
  response; parent/worker End must fence late callbacks. Room closure does not
  establish that deeper global application SQL has drained.
- Reuse existing P2 pools for context rehydration. Preserve public context bounds
  of two handlers/sixteen sockets separately from room controls' four/eight.

## Verification

Run focused tests/types first, then real PG/process integration and the shared
fast lane. Build P2 before this consumer. Validate formatting and documentation.
Missing, skipped and timed-out requirements cannot pass.

## Handoff

Record commands, assertions, actual/fake boundaries, source evidence, review
findings and remaining work in 0045. A component pass does not complete the
three-project demo or its broader charter requirements.
