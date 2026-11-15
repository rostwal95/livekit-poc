# Runtime, package and persistence boundaries

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Record the decision and rationale for project, persistence, runtime, specialist and packaging boundaries |
| Audience | Engineers changing project, runtime or package boundaries; coding agents |
| Scope | Libraries, reference application, durable execution ownership, HTTP specialists and package extraction; excludes acceptance requirements, which stay in the charters |
| Owns | Runtime, package and persistence boundary choices and their rationale |
| Related | [Decision 0002](0002-sqlite-inquiry-subset.md) · [Plan audit](../plan-audit.md) · [Build plan](../build-plan.md) · [P1 charter](../projects/agent-continuity-scope.md) |

## Context

The foundation already has Python Agents, a TypeScript browser SDK and a local
PostgreSQL service. Expanding every component into its own runtime, or maintaining
two complete schedulers, would add work without establishing the required behavior.
The [plan audit](../plan-audit.md) explains the reviewed tradeoffs.

## Decision

### Projects and persistence

Keep three libraries and one reference application. Local infrastructure and
contracts are shared support areas.

Preserve the SQLite M1 intake (the original confirmed-investigation intake) and
the first inquiry and recovery slice. Introduce PostgreSQL execution after that
first process proof, before rich lifecycle expansion. The
[build plan](../build-plan.md) and the
[P1 (Agent Continuity Lab) charter](../projects/agent-continuity-scope.md) own the
supported SQLite subset and the remaining multi-worker acceptance requirements.

### Runtime ownership

| Concern | Owner |
| --- | --- |
| Conversational sessions, tasks, tools, handoffs, dispatch and process lifecycle | Reused from LiveKit |
| Durable acceptance, execution attempts, retry eligibility and deadlines | P1 alone |
| Bounded capability invocations within those attempts | HTTP specialists |

HTTP specialist request, status and cancel observations do not introduce another
recovering queue. Bind their request scope to a trusted local service principal.

### Specialists and realtime peers

Ordinary HTTP specialists use TypeScript schemas, handlers and capability clients.
Add Node Agents or native real-time communication (RTC) peers only if a Node
realtime agent is actually selected. Compare native tools and subagents before
choosing remote deployment, and retain the final three-way comparison as release
evidence.

### Packaging

Extract an installable library when a real consumer needs its public boundary.
Verify a built wheel or npm package from an isolated consumer without repository
imports. Do not turn the current service application package into evidence that
all three planned libraries can already be installed independently.

## Consequences

This avoids duplicate scheduling, unnecessary native dependencies and early
packaging churn. It preserves all 54 product requirements, trusted scope,
confirmation, uncertain-effect handling and replay-safe retention.

The current V1 local media server is a single selective forwarding unit (SFU).
PostgreSQL worker coordination does not imply distributed media capacity. Full
scope and acceptance authority remain in the charters.

## Validation

Each change still needs normal and failure-path evidence.
