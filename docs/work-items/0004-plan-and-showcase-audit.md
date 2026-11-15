# Plan audit and observable capability showcase

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Record the plan, observed verification and handoff for the plan audit and the observable capability showcase |
| Audience | Engineers changing the showcase UI, API metrics or plan documents; coding agents |
| Scope | Plan audit, documentation and harness standardization, showcase UX and bounded exception and metric handling; excludes completion of any product acceptance ID |
| Owns | Change plan, observed verification and handoff for the plan audit and showcase |
| Related | [Work item 0003](0003-local-project-foundation.md) · [Work item 0005](0005-granular-implementation-plan.md) · [Plan audit](../plan-audit.md) · [Demo plan](../demo-plan.md) · [Observability](../observability.md) |

## Behavior and scope

Audit the entire three-project plan and production-oriented repository
boundaries, standardize current documentation and harness instructions, improve
the showcase user experience (UX), and establish bounded exception and metric
handling. This is foundation work under build-plan work packages PLAN-09–PLAN-11,
plus plan corrections. No planned product acceptance ID becomes complete through a
visual or documentation change. Preserve all 54 requirements.

## Interfaces and ownership

| Document or component | Owns |
| --- | --- |
| [Audit](../plan-audit.md) | Findings |
| [Build plan](../build-plan.md) | Sequencing |
| [Demo plan](../demo-plan.md) | Capability presentation |
| [Observability](../observability.md) | Signal and error policy |
| Charters | Case authority and execution definitions |
| Shared fixtures | Diagnostic shape, not business state |

API metrics have finite dimensions and private registries.

The UI uses the real API for M1 acceptance, replay and conflict (M1 is the
original SQLite confirmed-investigation intake). It records progress only after
validated responses, preserves uncertainty and uses the exact original payload and
key for reconciliation. Planned workflow, channel and specialist proofs remain
labelled. Official asset licenses accompany locally served fonts and symbols.

## Failure cases and validation

Verify actual producer output against the shared diagnostic fixture. Reject
spoofed senders, wrong tracks, malformed or oversized events and the old
incompatible type. Test intake response shape and scope, same-task replay,
changed-payload rejection, request timeouts and uncertainty without automatic
retries.

Harness fixtures must reject missing foundation metadata or entrypoints, unsafe or
duplicate configuration, forbidden imports including relative-import bypasses, and
deleted required docs. Planned future source roots remain allowed.

API tests verify private metric access, finite labels, actual inflight work,
request correlation, sanitized expected and unexpected failures, validation
redaction and cancellation propagation. Actual local smoke, authenticated metric
inspection and browser observations complement those isolated tests.

Run `make check`, `make format-check`, `pnpm check`, `pnpm test`, `pnpm build`,
the deep gate and local-setup smoke with frozen environments. The deep product
gate must remain incomplete with 54 not_implemented cases. Record real browser,
reconnect and microphone coverage separately, including unavailable permission or
capabilities.

## Results and handoff

### Observed gates

All final checks passed.

| Observed gate | Command or mode | Result |
| --- | --- | --- |
| Python checks | Final Python checks | 121 Python tests; Ruff lint and formatting across all 38 maintained Python files; mypy for nine service source files |
| Frontend | Final frontend checks | 59 frontend tests, strict TypeScript and a production console build |
| Documentation | Corpus checker | The 52-document corpus passed with zero violations |
| Traceability | Traceability check | Preserves 54 charter IDs, 54 primary coverage rows and 22 work packages |
| Deep gate | Deep product gate | Incomplete (exit 2): one passing baseline (14 intake tests) and 54 not_implemented product cases |
| Compose smoke | Actual Compose smoke | Passed authentication, intake replay and conflict, named dispatch, text echo and at least ten received synthetic audio frames |
| Metrics and errors | Against the running API | Authenticated metrics scraping and fresh request-ID and error envelopes passed |
| Stack health | Service status | All five core services were healthy; optional Jaeger UI readiness passed, without claiming trace export |

The original M1 investigation identity survived rebuilds.

Browser observations verified invalid-token recovery, room connection, actual SDK
agent arrival, text echo, explicit disconnect and reconnect, real M1 acceptance,
same-identity replay, changed-payload rejection and reinspection of the original
request. The visible confirmation is explicit operator input. Acceptance and
replay are server-verified. New media controls wait for actual agent presence.
Keyboard activation of native project details worked, and reflow at 1280px and
390px had no horizontal overflow. This is not a full accessibility certification.

The current browser bundle is about 561 kB minified and 148 kB gzip. The Vite
chunk warning remains visible. It is dominated by the native SDK and should be
optimized only against a measured load and interaction budget, not suppressed.

### Review corrections

Review resolved browser diagnostic and schema spoofing, agent-arrival admission,
validation recovery, admission-cap reconciliation, Asynchronous Server Gateway
Interface (ASGI) disconnect classification, terminal-dispatch reuse and log
severity. Docker dependency installation now precedes source copies, verified by
successful frozen image builds and runtime checks.

### Evidence and next step

The local showcase remains open on the verified intake result. Evidence is under
`.local/validation/plan-audit`, including these files and screenshots:

| Artifact | Content |
| --- | --- |
| `fast.txt` | Fast check output |
| `format.txt` | Format check output |
| `frontend.txt` | Frontend check output |
| `rtc-smoke.json` | Real-time communication (RTC) smoke result |
| `metrics.txt` | Authenticated metrics scrape |
| `product-gate.json` | Deep product gate result |
| `stack-status.json` | Stack service status |
| Screenshot 01 | Initial UI |
| Screenshot 02 | Official visual reference |
| Screenshots 08 and 09 | Final actual showcase and conflict result |

Temporary captures are local evidence, not product acceptance registrations.

Browser microphone publishing and playback, network-loss media recovery, exported
application traces, remote Linux CI, real-model quality, measured capacity and all
complete product V1s remain unverified or planned. The work used AI assistance and
independent architecture, delivery, UI and API, and harness reviews. The next
product slice remains the schema-safe inquiry and recovery implementation.
