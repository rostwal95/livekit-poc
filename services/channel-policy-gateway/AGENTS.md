# Channel policy gateway coding instructions

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Give coding agents the reading order, ownership, rules and checks for channel policy gateway work |
| Audience | Coding agents and engineers changing the Node gateway or its component tests |
| Scope | This Node application and its component tests; excludes P2 storage and the sibling Python application |
| Owns | Agent workflow for the gateway: reading order, owned paths, development rules, verification and handoff |
| Related | [Root instructions](../../AGENTS.md) · [README](README.md) · [Design](Design.md) · [Work item 0045](../../docs/work-items/0045-joined-native-channel-policy.md) |

## Read first

Read these before editing:

| Document | Why read it |
| --- | --- |
| [Root instructions](../../AGENTS.md) | Shared reading order, owned paths, development rules and verification |
| [README.md](README.md) | Implemented behavior, commands and validation |
| [Design.md](Design.md) | Design, limits and failure handling |
| [Active work item 0045](../../docs/work-items/0045-joined-native-channel-policy.md) | Active change plan, observed verification and handoff |
| Affected public P2 APIs and tests | Current interfaces and behavior that a change touches |

## Owned paths

| Area | Responsibility |
| --- | --- |
| This Node application and its component tests | Owned here |
| Storage, preparation and channel authorization | Owned by P2 |
| Origin/executor composition | Owned by the sibling Python application |
| Durable queues and execution ledgers | Neither application adds another durable queue or execution ledger |

## Development rules

### Imports, configuration and serving

- Import public package exports only.
- Keep imports inert and configuration typed.
- Keep HTTP hosting and setup explicit.
- Serving code performs no DDL (schema-changing SQL).
- Normal stop preserves state.
- Destructive reset requires a separate action.
- Preserve default configuration/CLI behavior.
- Room control and native bridge are separate opt-ins.

### Source owners and discovery

- Select native/SMS owners from a validated stored provider/event.
- A request's source label can only check consistency, never select a privileged owner.
- Rescan at most sixteen retained inputs from zero.
- Expose overflow and examine later records past pending/unknown gaps.
- No terminal acknowledgement cursor.
- Return original prepared bytes and verify their input/operation/scope/body/digest.
- A read cannot prepare, claim, dispatch or reassociate a source.

### Rooms and native clients

- The observed Node epoch/generation is authoritative.
- A publication or attachment retry keeps its exact original identity/capability.
- Matching current-room input requires an attached public native client.
- Missing attachment fails unavailable.
- Dormant/older retained inputs keep their separate deterministic background path.
  They cannot select the new room's worker.
- Stop and drain the actual per-room native client and context/read observers before
  releasing the room or admitting the next room (B).
- Public context HTTP remains an as-of response.
- Parent/worker End must fence late callbacks.
- Room closure does not establish that deeper global application SQL has drained.

### Bounds, slots and cleanup

- Bound actual reads before awaiting.
- A timed-out waiter retains its slot.
- Drain actual operations before closing borrowed P2 owners.
- Retry incomplete close.
- Reuse existing P2 pools for context rehydration.
- Preserve public context bounds of two handlers/sixteen sockets separately from
  room controls' four/eight.

### Errors, logs and secrets

- Use finite errors and numeric observations.
- Never log input, token, dependency exception text or per-ID metrics.
- Keep all provider keys outside this process.

## Verification

1. Run focused tests/types first.
2. Then run real PostgreSQL/process integration and the shared fast lane.

From the repository root:

| Check | Command | When to run |
| --- | --- | --- |
| P2 build | `pnpm --filter @livekit-ecosystem/channel-continuity build` | Before this consumer |
| Focused types | `pnpm --filter @livekit-ecosystem/channel-policy-gateway typecheck` | First, for every change |
| Focused tests | `pnpm --filter @livekit-ecosystem/channel-policy-gateway test` | First, for every change |
| Real PostgreSQL/process integration | Not named in these instructions | After focused tests and types |
| Shared fast lane | `HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh` | After focused tests and types |
| Formatting | `make frontend-check` | For every change |
| Documentation | `.venv/bin/python -m harness.documentation_check` | For every change |

Also:

- Build P2 before this consumer.
- Validate formatting and documentation.
- Missing, skipped and timed-out requirements cannot pass.

## Handoff

- Record commands, assertions, actual/fake boundaries, source evidence, review
  findings and remaining work in
  [0045](../../docs/work-items/0045-joined-native-channel-policy.md).
- A component pass does not complete the three-project demo or its broader charter
  requirements.
