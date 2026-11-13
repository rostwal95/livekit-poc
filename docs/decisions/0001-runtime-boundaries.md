# Runtime, package and persistence boundaries

Status: Active
Last reviewed: 9 November 2026

## Context

The foundation already has Python Agents, a TypeScript browser SDK and a local
PostgreSQL service. Expanding every component into its own runtime or maintaining
two complete schedulers would add work without establishing the required behavior.
The [plan audit](../plan-audit.md) explains the reviewed tradeoffs.

## Decision

Keep three libraries and one reference application. Local infrastructure and
contracts are shared support areas. Preserve SQLite M1 intake and the first
inquiry/recovery slice. Introduce PostgreSQL execution after that first process
proof, before rich lifecycle expansion. The build plan and P1 charter own the
supported SQLite subset and remaining multi-worker acceptance requirements.

Reuse LiveKit conversational sessions, tasks, tools, handoffs, dispatch and
process lifecycle. P1 alone owns durable acceptance, execution attempts, retry
eligibility and deadlines. HTTP specialists are bounded capability invocations
within those attempts; request/status/cancel observations do not introduce another
recovering queue. Bind their request scope to a trusted local service principal.

Ordinary HTTP specialists use TypeScript schemas/handlers and capability clients.
Add Node Agents/native RTC peers only if a Node realtime agent is actually selected.
Compare native tools/subagents before choosing remote deployment, and retain the
final three-way comparison as release evidence.

Extract an installable library when a real consumer needs its public boundary.
Verify a built wheel or npm package from an isolated consumer without repository
imports. Do not turn the current service application package into evidence that
all three planned libraries can already be installed independently.

## Consequences and validation

This avoids duplicate scheduling, unnecessary native dependencies and early
packaging churn. It preserves all 54 product requirements, trusted scope,
confirmation, uncertain-effect handling and replay-safe retention. Each change
still needs normal and failure-path evidence. The current V1 local media server
is a single SFU; PostgreSQL worker coordination does not imply distributed media
capacity. Full scope and acceptance authority remain in the charters.
