# Ecosystem plan, structure and harness audit

Status: Active
Last reviewed: 13 November 2026

## Scope and assessment

Reviewed the build sequence, all three charters, state authority, persistence,
package boundaries, version policy, acceptance mapping, coding-agent instructions,
local runtime, harness implementation, documentation rules, UI and failure/telemetry
surfaces. Independent reviews checked architecture, delivery, current LiveKit APIs
and the implemented fixes. This is an engineering audit of a developing portfolio,
not a production certification.

The three projects remain a strong fit for durable agent workflows, channel
continuity and delegation. Keep them as three reusable libraries plus one reference
application. The central safety model is sound: one case authority, separate
investigation and mutation consent, atomic intent commitment, explicit external
uncertainty, cancellation distinct from speech interruption, and liveness alongside
stale-result rejection. All 54 product requirements and 22 work packages remain.
[Target role](https://jobs.ashbyhq.com/livekit/1757f49e-7e19-4c45-85f7-e4637dff66fb).

## Current role alignment

The [target posting](https://jobs.ashbyhq.com/livekit/1757f49e-7e19-4c45-85f7-e4637dff66fb)
was rechecked on 13 November. It emphasizes realtime voice/text, channels such as
SMS, durable state across interactions, delegation, approachable developer APIs,
Python/TypeScript and clear examples/documentation. The mapping below is our
engineering interpretation; it is not employer endorsement or an upstream
framework contribution claim.

| Role emphasis | Ecosystem demonstration | Current evidence boundary |
| --- | --- | --- |
| Voice and text | One native SDK session, durable committed input, interruption and fresh-room context | Selected P2 native/media gates passed; joined app/provider repetition pending |
| Text across channels | Same scoped case through browser/native input and signed local SMS | Selected storage/routing gates passed; carrier behavior is simulated and labelled |
| Stateful workflows | P1 acceptance, issued work, revision/confirmation, effects and recovery after media ends | P1 selected provider-real local release passed; joined executor restart still requires its gate |
| Agent collaboration | Typed P3 specialist calls, factual validation, applicability and receiver-bound delivery | Selected source/installed gates passed; joined background execution still requires actual integration |
| Developer experience | Independently consumable kits, typed Python/TypeScript boundaries, examples and harness commands | Existing kit artifacts qualified; new root application artifacts pending |

The [Agents overview](https://docs.livekit.io/agents/) supports keeping native
media/session ownership in LiveKit while these libraries compose durable business
and channel boundaries. The local POC does not establish hosted fleet capacity.
Observe scale through declared local workloads and truthful resource/latency
measurements, then keep production capacity claims separate.

## Subsequent architecture review

The [10 November audit disposition](work-items/0020-architecture-audit-reconciliation.md)
compares the supplied architecture review with current source and Phase H evidence.
It distinguishes superseded findings from current corrections and planned
extensions. The [operational follow-up](work-items/0021-p1-operational-safety-extensions.md)
owns future restored-database quarantine and append-only adjudication criteria;
P2/P3 charters retain identity/routing and evidence/applicability requirements.
These additions do not reopen completed P1 V1 evidence or claim future tests passed.

## Findings and actions

| Priority | Finding | Change and rationale |
| --- | --- | --- |
| P2 | Browser silently discarded the worker's actual audio.frames diagnostic because it expected audio.received | Shared Python/TypeScript fixture and runtime parser now protect the exact schema |
| P2 | Browser topics were treated as proof of agent identity | Validate actual SDK agent kind and intended microphone track before accepting observations |
| P2 | Room connectivity enabled messages before the agent joined | Gate messages/microphone on actual validated agent presence and expose the waiting state |
| P2 | Validation rejection could trap the intake form | Allow correction after definitive rejection while retaining the identity of any earlier unacknowledged attempt |
| P2 | Storage admission limits also blocked accepted-work replay and inspection | Enforce quota atomically only on new growth; preserve replay/conflict and bounded reads at capacity |
| P2 | A client disconnect without a response inflated server-failure metrics | Observe the actual ASGI disconnect as client cancellation instead of an invented server 500 |
| P2 | Operational source paths triggered full selection but escaped import-boundary enforcement | Mandatory non-product foundation manifest covers services, app, setup and contracts; P1/P2/P3 remain the only product modules |
| P2 | Native delegation comparison happened after the remote service investment | Require a small tools/native baseline before PLAN-17; retain the final three-way benchmark |
| P2 | HTTP specialists could accidentally acquire a second durable execution queue | Define bounded authenticated per-attempt invocation; P1 owns acceptance, attempts, retries and deadlines |
| P2 | Node Agents/native RTC peers looked mandatory for ordinary HTTP capabilities | Make them conditional on an actual Node realtime component |
| P2 | Independently usable libraries lacked a built-artifact consumer gate | Verify a wheel or npm package from outside the checkout once a genuine package boundary exists |
| P2 | Specialist scope labels lacked an explicit principal-binding decision | Bind request/status/cancel/result access to a trusted service principal and test forged scope |
| P2 | API failures lacked standard correlation and current observability signals | Protected finite-label metrics, structured safe logs, fresh request IDs and normalized error envelopes now support the foundation |
| P3 | Full lifecycle risked being implemented twice before PostgreSQL coordination | Keep SQLite M1/first inquiry, introduce the early PostgreSQL adapter after PLAN-03, then expand lifecycle once |
| P3 | Retention could weaken late-replay safety | Decide replay horizons/tombstones before cleanup; display pruning cannot delete effect protection |
| P3 | Historical effort included foundation work already implemented | Separate historical range from unmeasured remaining effort and re-estimate after the first recovery slice |
| P3 | Architecture decisions escaped the documentation corpus | Include docs/decisions and record the current runtime/package/storage decision |
| P3 | Source edits invalidated the Docker dependency installation layer | Separate frozen dependency installation from source copies in Python and console builds |
| P3 | CI omitted the available formatting check | Add the same formatting scope used locally |
| P3 | UI styling and raw diagnostic presentation did little to explain capability transitions | Apply current LiveKit visual references and a real intake/replay/conflict walkthrough; planned V1 proofs stay labelled |

## Production-oriented structure

| Area | Purpose and ownership |
| --- | --- |
| projects/agent-continuity | P1 reusable library, public execution boundary and standalone consumer |
| projects/channel-continuity | P2 channel SDK, adapters and standalone consumer |
| projects/delegation-reliability | P3 coordinator/capability contracts and standalone consumer |
| continuity_lab | Compatible SQLite M1/inquiry plus PostgreSQL case, continuation, effects, leases and bound conversation service in the canonical P1 src distribution; typed artifact extraction and installed consumers passed |
| services | Deployable application adapters/workers; not library internals |
| apps/local-console | One operational/demo interface, no competing case authority |
| contracts | Small producer/consumer fixtures and future explicit versioned product schemas |
| local-setup | Isolated development orchestration, pins, config and state-preserving lifecycle |
| harness and tests | Structural contracts, executable tests and separate acceptance outcomes |
| docs and docs/decisions | Authoritative scope, implementation sequence, decisions and evidence policy |

Use typed public ports and forbid service/store imports across protected boundaries.
Extract packages when real consumers establish the need; avoid moving working code
merely to manufacture a conventional folder tree. Root packaging owns the
application; the canonical P1 src distribution now supplies typed public APIs and
isolated installed examples with independent review. Final host/Linux integration,
current H2 workloads and selected provider_real v2 media qualification passed in
the [local P1 release](work-items/0019-p1-phase-h-release-qualification.md). F/G and
historical H1 retain their own evidence scopes. local_real, physical quality,
human acknowledgement and production capacity remain unqualified; P2/P3 remain
planned. Remote CI/publication are outside this local POC scope.

## Optimized delivery order

1. Reproduce the implemented A–G foundations: actual scoped native media/current
   case, exact consent, independent inquiry/effects and preserved-state restart.
   Keep unqualified hardware microphone results separate; remote Linux CI is outside the local POC scope.
2. Use the measured [H1 seeded inquiry baseline](work-items/0014-p1-phase-h-workload-baseline.md)
   and the passed current H2/provider_real v2 workload evidence with their distinct
   source scopes. Freeze budgets before future measurements and preserve
   uncertainty as an outcome.
3. Retain completed I26 public API, isolated host/Linux consumers and independent
   failure review. Repeat affected gates after changes; preserve original M1
   compatibility and the single PostgreSQL execution owner.
4. Deliver the smallest P2 standalone consumer and durable event path. Add actual
   playback/resumption evidence after its contract exists.
5. Measure native delegation, justify the deployment boundary, then build one
   authenticated bounded HTTP specialist before the second capability.
6. Finish failure demonstrations, isolated package installation, supported-platform
   checks, real-model evaluation and measured comparison. Do not reduce acceptance
   criteria to fit a date.

The [build plan](build-plan.md) is authoritative for package dependencies and
estimates. Freeze tested versions inside a feature slice; refresh at actual
SDK/provider integration or intentional release work. PostgreSQL worker scaling
and single-SFU local media capacity are different measurements. Distributed media
requires separately scoped infrastructure. [Agent lifecycle](https://docs.livekit.io/agents/server/lifecycle/),
[distributed media](https://docs.livekit.io/transport/self-hosting/distributed/).

## Showcase, observability and evidence

The [demo plan](demo-plan.md) defines a visible normal/failure proof for each
library and the implemented intake/diagnostic plus G business/native-media
showcase. The [observability contract](observability.md) separates implemented
metrics/logs/inspected filtered traces, the measured H1 inquiry baseline and
still-open broader workload studies. UI transitions must follow actual
responses/events, retain unknown outcomes and respect reduced-motion preferences.
Keep the real native session contract and authority visible; use official UI
components only when a genuine consumer needs them. A visual refresh alone does not justify a frontend
framework migration. [Agents UI components](https://docs.livekit.io/frontends/agents-ui/).

The harness remains deliberately small. Structural success, Python tests, frontend
checks, actual RTC smoke, browser observations and model evaluation are separate
lanes. Missing tests, required skips, timeouts and planned acceptance runners cannot
become passing product evidence. Import scanning is a useful structural guard,
not a complete language resolver or runtime sandbox.

## Observed UI audit steps

These observations belong to the historical foundation audit, not the later G
media gate or a new claim about every browser/device.

1. Entry and connection: healthy after fixes. Invalid-token recovery, scoped room
   connection and real agent arrival were observed. Controls wait for the agent.
2. Realtime activity: healthy for browser text and explicit reconnect. Echo came
   from the SDK agent; microphone/playback remain unverified.
3. Durable intake: healthy for the implemented foundation. Acceptance, same-task
   replay, changed-payload rejection and original-payload recovery were observed.
4. Navigation and reflow: native details/keyboard activation worked; 1280px and
   390px layouts had no horizontal overflow. This does not establish full WCAG
   compliance or every browser/device combination.

Initial screenshots showed a functioning token boundary and honest planned labels,
but unrelated green styling, a passive log and no visible durable proof. The revised
screen uses the current LiveKit brand reference, explicit waiting/connected states,
a real intake transition sequence and visibly planned project stories. Accepted
captures and their scope are retained with the work-item evidence.

Results and unresolved limits are recorded in the
[audit work item](work-items/0004-plan-and-showcase-audit.md). Subsequent F/G
implementation adds durable leased execution, the scoped native/current-case
profile and inspected raw Jaeger v3 traces. The
[Phase G work item](work-items/0013-p1-phase-g-conversation-and-showcase.md) owns its
inspected local combined gate. Controls wait for public RoomIO readiness and the
exact native attribute; alternate SDK session hosting is disabled. Current release
work preserves the measured H1 inquiry and H2 reliability slices. P1-I26 host/Linux
artifacts, independent API/failure review and genuine native consumer passed.
P1 V1 is qualified for the local POC using provider_real v2. local_real remains unqualified and complete P2/P3 acceptance remains pending. Hardware microphone
quality, complete P2/P3 V1s and production capacity remain separate. Hosted
CI/publication are outside this local POC scope.


### Current local P1 qualification

P1 V1 is implemented and locally qualified with selected provider_real v2.
The final 20-case index, current P1-18/P1-14/P1-20, full H2, PostgreSQL, installed
host/Linux artifacts and shared quality gates passed with independent reviews.
Historical checkpoints retain their original scope. local_real remains unqualified;
complete P2/P3 acceptance remains pending, and hosted CI/publication are outside this local POC.
