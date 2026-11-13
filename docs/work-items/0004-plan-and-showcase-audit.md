# Plan audit and observable capability showcase

Status: Completed
Last reviewed: 9 November 2026

## Behavior and scope

Audit the entire three-project plan and production-oriented repository boundaries,
standardize current documentation/harness instructions, improve the showcase UX,
and establish bounded exception/metric handling. This is foundation work under
PLAN-09–PLAN-11 plus plan corrections; no planned product acceptance ID becomes
complete through a visual or documentation change. Preserve all 54 requirements.

## Interfaces and ownership

The [audit](../plan-audit.md) records findings; the [build plan](../build-plan.md)
owns sequencing. The [demo plan](../demo-plan.md) owns capability presentation;
[observability](../observability.md) owns signal/error policy. Case authority and
execution remain defined by their charters. Shared fixtures own diagnostic shape,
not business state. API metrics have finite dimensions and private registries.

The UI uses the real API for M1 acceptance/replay/conflict. It records progress
only after validated responses, preserves uncertainty and uses exact original
payload/key for reconciliation. Planned workflow, channel and specialist proofs
remain labelled. Official asset licenses accompany locally served fonts/symbols.

## Failure cases and validation

Verify actual producer output against the shared diagnostic fixture and reject
spoofed senders, wrong tracks, malformed/oversized events and the old incompatible
type. Test intake response shape/scope, same-task replay, changed-payload rejection,
request timeouts and uncertainty without automatic retries.

Harness fixtures must reject missing foundation metadata/entrypoints, unsafe or
duplicate configuration, forbidden imports including relative-import bypasses,
and deleted required docs. Planned future source roots remain allowed.

API tests verify private metric access, finite labels, actual inflight work,
request correlation, sanitized expected/unexpected failures, validation redaction
and cancellation propagation. Actual local smoke, authenticated metric inspection
and browser observations complement those isolated tests.

Run make check, make format-check, pnpm check, pnpm test, pnpm build, the deep gate
and local-setup smoke with frozen environments. The deep product gate must remain
incomplete with 54 not_implemented cases. Record real browser/reconnect/microphone
coverage separately, including unavailable permission or capabilities.

## Results and handoff

All final checks passed: 121 Python tests, 59 frontend tests, strict TypeScript,
Ruff lint and formatting across all 38 maintained Python files, mypy for nine
service source files, and a production console build. The 52-document corpus
passed with zero violations. Traceability preserves 54 charter IDs, 54 primary
coverage rows and 22 work packages. The deep gate returned incomplete/exit 2 with
one passing baseline (14 intake tests) and 54 not_implemented product cases.

Actual Compose smoke passed authentication, intake replay/conflict, named dispatch,
text echo and at least ten received synthetic audio frames. The original M1
investigation identity survived rebuilds. Authenticated metrics scraping and fresh
request-ID/error envelopes passed against the running API. All five core services
were healthy; optional Jaeger UI readiness passed, without claiming trace export.

Browser observations verified invalid-token recovery, room connection, actual SDK
agent arrival, text echo, explicit disconnect/reconnect, real M1 acceptance,
same-identity replay, changed-payload rejection and reinspection of the original
request. The visible confirmation is explicit operator input; acceptance/replay
are server-verified. New media controls wait for actual agent presence. Keyboard
activation of native project details worked, and 1280px/390px reflow had no horizontal
overflow. This is not a full accessibility certification.

The local showcase remains open on the verified intake result. Evidence is under
.local/validation/plan-audit: fast.txt, format.txt, frontend.txt, rtc-smoke.json,
metrics.txt, product-gate.json, stack-status.json and screenshots. Screenshot 01
captures the initial UI; 02 is the official visual reference; 08/09 retain the
final actual showcase and conflict result. Temporary captures are local evidence,
not product acceptance registrations.

Review resolved browser diagnostic/schema spoofing, agent-arrival admission,
validation recovery, admission-cap reconciliation, ASGI disconnect classification,
terminal-dispatch reuse and log severity. Docker dependency installation now
precedes source copies, verified by successful frozen image builds and runtime
checks. Current browser bundle is about 561 kB minified / 148 kB gzip; the Vite
chunk warning remains visible. It is dominated by the native SDK and should be
optimized only against a measured load/interaction budget, not suppressed.

Browser microphone publishing/playback, network-loss media recovery, exported
application traces, remote Linux CI, real-model quality, measured capacity and
all complete product V1s remain unverified or planned. The work used
AI assistance and independent architecture, delivery, UI/API and harness reviews.
The next product slice remains the schema-safe inquiry/recovery implementation.
