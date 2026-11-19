# Ecosystem plan, structure and harness audit

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Record the whole-ecosystem plan, structure and harness audit: its findings, the corrections made and the limits that remain |
| Audience | Engineers and reviewers who want the whole-ecosystem findings, corrections and remaining limits |
| Scope | Build sequence, charters, state authority, packaging, runtime, harness, documentation rules, UI and telemetry; an engineering audit, not a production certification |
| Owns | Reviewed findings, implemented corrections and remaining limits |
| Related | [Build plan](build-plan.md) · [Checkpoint history](checkpoint-history.md) · [Documentation audit](documentation-audit.md) · [Audit work item](work-items/0004-plan-and-showcase-audit.md) · [Audit disposition](work-items/0020-architecture-audit-reconciliation.md) |

## Scope and assessment

This audit is for engineers and reviewers who want the whole-ecosystem findings,
the corrections made and the limits that remain. It is an engineering audit of a
developing portfolio, not a production certification.

### What was reviewed

| Review | Coverage |
| --- | --- |
| The audit | The build sequence, all three charters, state authority, persistence, package boundaries, version policy, acceptance mapping, coding-agent instructions, local runtime, harness implementation, documentation rules, UI and failure/telemetry surfaces |
| Independent reviews | Architecture, delivery, current LiveKit APIs and the implemented fixes |

### Assessment

The three projects remain a strong fit for durable agent workflows, channel
continuity and delegation. Keep them as three reusable libraries plus one
reference application. All 54 product requirements and 22 work packages remain.

The central safety model is sound:

- one case authority;
- separate investigation and mutation consent;
- atomic intent commitment;
- explicit external uncertainty;
- cancellation distinct from speech interruption;
- liveness alongside stale-result rejection.

The [target role](https://jobs.ashbyhq.com/livekit/1757f49e-7e19-4c45-85f7-e4637dff66fb)
is mapped under [Current role alignment](#current-role-alignment).

## Current qualification status

P1 V1, the fixed first-version scope of P1, is implemented and locally qualified
with the selected provider_real v2 profile. The
[local P1 release](work-items/0019-p1-phase-h-release-qualification.md) records
these passed gates, with independent reviews:

- the final 20-case index;
- current P1-18, P1-14 and P1-20;
- full and current H2 workloads;
- PostgreSQL;
- final host/Linux integration and installed host/Linux artifacts;
- selected provider_real v2 media qualification;
- shared quality gates.

P1-I26 host/Linux artifacts, independent API/failure review and a genuine native
consumer passed. Current release work preserves the measured H1 inquiry and H2
reliability slices. Historical checkpoints retain their original scope, and
Phases F and G and the historical H1 slice retain their own evidence scopes.

These remain outside the qualified scope:

| Item | Status |
| --- | --- |
| local_real | Not qualified |
| Physical quality and human acknowledgement | Not qualified |
| Production capacity | Not qualified, and kept separate |
| Hardware microphone quality | Kept separate |
| Complete P2 and P3 V1s | Partial and kept separate: P2 and P3 are partially implemented, and their complete acceptance remains pending |
| Remote and hosted continuous integration (CI) and publication | Outside this local proof of concept (POC) scope |

## Current role alignment

The reviewed [target posting](https://jobs.ashbyhq.com/livekit/1757f49e-7e19-4c45-85f7-e4637dff66fb)
emphasizes realtime voice/text, channels such as
SMS, durable state across interactions, delegation, approachable developer APIs,
Python/TypeScript and clear examples/documentation. The mapping below is our
engineering interpretation. It is not employer endorsement or an upstream
framework contribution claim.

| Role emphasis | Ecosystem demonstration | Current evidence boundary |
| --- | --- | --- |
| Voice and text | One native software development kit (SDK) session, durable committed input, interruption and fresh-room context | Selected P2 native/media gates passed. Joined app/provider repetition pending |
| Text across channels | Same scoped case through browser/native input and signed local SMS | Selected storage/routing gates passed. Carrier behavior is simulated and labelled |
| Stateful workflows | P1 acceptance, issued work, revision/confirmation, effects and recovery after media ends | P1 selected provider-real local release passed. Joined executor restart still requires its gate |
| Agent collaboration | Typed P3 specialist calls, factual validation, applicability and receiver-bound delivery | Selected source/installed gates passed. Joined background execution runs in the [0046](work-items/0046-joined-showcase-providers-and-demo.md) journeys, but its joined qualification assertions remain pending ([0045](work-items/0045-joined-native-channel-policy.md)) |
| Developer experience | Independently consumable kits, typed Python/TypeScript boundaries, examples and harness commands | Existing kit artifacts qualified. New root application artifacts pending |

The [Agents overview](https://docs.livekit.io/agents/) supports keeping native
media/session ownership in LiveKit while these libraries compose durable business
and channel boundaries. The local POC does not establish hosted fleet capacity.
Observe scale through declared local workloads and truthful resource/latency
measurements, then keep production capacity claims separate.

## Subsequent architecture review

- The [10 November audit disposition](work-items/0020-architecture-audit-reconciliation.md)
  compares the supplied architecture review with current source and Phase H
  evidence. It distinguishes superseded findings from current corrections and
  planned extensions.
- The [operational follow-up](work-items/0021-p1-operational-safety-extensions.md)
  owns future restored-database quarantine and append-only adjudication criteria.
- The P2/P3 charters retain identity/routing and evidence/applicability
  requirements.

These additions do not reopen completed P1 V1 evidence or claim future tests
passed.

## Findings and actions

The Priority column holds the audit's priority labels. These P2 and P3 values are
not the project identifiers P2 and P3. PLAN-nn identifiers are
[build plan](build-plan.md) work packages.

| Finding | Priority | Resolution |
| --- | --- | --- |
| Browser silently discarded the worker's actual `audio.frames` diagnostic because it expected `audio.received` | P2 | Shared Python/TypeScript fixture and runtime parser now protect the exact schema |
| Browser topics were treated as proof of agent identity | P2 | Validate actual SDK agent kind and intended microphone track before accepting observations |
| Room connectivity enabled messages before the agent joined | P2 | Gate messages/microphone on actual validated agent presence and expose the waiting state |
| Validation rejection could trap the intake form | P2 | Allow correction after definitive rejection while retaining the identity of any earlier unacknowledged attempt |
| Storage admission limits also blocked accepted-work replay and inspection | P2 | Enforce quota atomically only on new growth. Preserve replay/conflict and bounded reads at capacity |
| A client disconnect without a response inflated server-failure metrics | P2 | Observe the actual Asynchronous Server Gateway Interface (ASGI) disconnect as client cancellation instead of an invented server 500 |
| Operational source paths triggered full selection but escaped import-boundary enforcement | P2 | Mandatory non-product foundation manifest covers services, app, setup and contracts. P1/P2/P3 remain the only product modules |
| Native delegation comparison happened after the remote service investment | P2 | Require a small tools/native baseline before PLAN-17. Retain the final three-way benchmark |
| HTTP specialists could accidentally acquire a second durable execution queue | P2 | Define bounded authenticated per-attempt invocation. P1 owns acceptance, attempts, retries and deadlines |
| Node Agents/native RTC peers looked mandatory for ordinary HTTP capabilities | P2 | Make them conditional on an actual Node realtime component |
| Independently usable libraries lacked a built-artifact consumer gate | P2 | Verify a wheel or npm package from outside the checkout once a genuine package boundary exists |
| Specialist scope labels lacked an explicit principal-binding decision | P2 | Bind request/status/cancel/result access to a trusted service principal and test forged scope |
| API failures lacked standard correlation and current observability signals | P2 | Protected finite-label metrics, structured safe logs, fresh request IDs and normalized error envelopes now support the foundation |
| Full lifecycle risked being implemented twice before PostgreSQL coordination | P3 | Keep SQLite M1/first inquiry, introduce the early PostgreSQL adapter after PLAN-03, then expand lifecycle once |
| Retention could weaken late-replay safety | P3 | Decide replay horizons/tombstones before cleanup. Display pruning cannot delete effect protection |
| Historical effort included foundation work already implemented | P3 | Separate historical range from unmeasured remaining effort and re-estimate after the first recovery slice |
| Architecture decisions escaped the documentation corpus | P3 | Include docs/decisions and record the current runtime/package/storage decision |
| Source edits invalidated the Docker dependency installation layer | P3 | Separate frozen dependency installation from source copies in Python and console builds |
| CI omitted the available formatting check | P3 | Add the same formatting scope used locally |
| UI styling and raw diagnostic presentation did little to explain capability transitions | P3 | Apply current LiveKit visual references and a real intake/replay/conflict walkthrough. Planned V1 proofs stay labelled |

## Production-oriented structure

| Area | Responsibility |
| --- | --- |
| `projects/agent-continuity` | P1 reusable library, public execution boundary and standalone consumer |
| `projects/channel-continuity` | P2 channel SDK, adapters and standalone consumer |
| `projects/delegation-reliability` | P3 coordinator/capability contracts and standalone consumer |
| `continuity_lab` | Compatible SQLite M1/inquiry plus PostgreSQL case, continuation, effects, leases and bound conversation service in the canonical P1 src distribution. Typed artifact extraction and installed consumers passed |
| `services` | Deployable application adapters/workers; not library internals |
| `apps/local-console` | One operational/demo interface, no competing case authority |
| `contracts` | Small producer/consumer fixtures and future explicit versioned product schemas |
| `local-setup` | Isolated development orchestration, pins, config and state-preserving lifecycle |
| `harness` and `tests` | Structural contracts, executable tests and separate acceptance outcomes |
| `docs` and `docs/decisions` | Authoritative scope, implementation sequence, decisions and evidence policy |

- Use typed public ports and forbid service/store imports across protected
  boundaries.
- Extract packages when real consumers establish the need. Avoid moving working
  code merely to manufacture a conventional folder tree.
- Root packaging owns the application. The canonical P1 src distribution now
  supplies typed public APIs and isolated installed examples with independent
  review.

## Optimized delivery order

This is the delivery order the audit recommends. Later work items have delivered
parts of it. The [build plan](build-plan.md) and
[checkpoint history](checkpoint-history.md) track current progress.

1. Reproduce the implemented Phase A to G foundations: actual scoped native
   media/current case, exact consent, independent inquiry/effects and
   preserved-state restart. Keep unqualified hardware microphone results separate.
   Remote Linux CI is outside the local POC scope.
2. Use the measured [H1 seeded inquiry baseline](work-items/0014-p1-phase-h-workload-baseline.md)
   and the passed current H2/provider_real v2 workload evidence with their
   distinct source scopes. Freeze budgets before future measurements and preserve
   uncertainty as an outcome.
3. Retain the completed P1-I26 public API, isolated host/Linux consumers and
   independent failure review. Repeat affected gates after changes. Preserve
   original M1 compatibility and the single PostgreSQL execution owner.
4. Deliver the smallest P2 standalone consumer and durable event path. Add actual
   playback/resumption evidence after its contract exists.
5. Measure native delegation, justify the deployment boundary, then build one
   authenticated bounded HTTP specialist before the second capability.
6. Finish failure demonstrations, isolated package installation,
   supported-platform checks, real-model evaluation and measured comparison. Do
   not reduce acceptance criteria to fit a date.

Planning rules that apply to this order:

- The [build plan](build-plan.md) is authoritative for package dependencies and
  estimates.
- Freeze tested versions inside a feature slice. Refresh at actual SDK/provider
  integration or intentional release work.
- PostgreSQL worker scaling and single selective forwarding unit (SFU) local media
  capacity are different measurements.
- Distributed media requires separately scoped infrastructure.

References: [Agent lifecycle](https://docs.livekit.io/agents/server/lifecycle/)
and [distributed media](https://docs.livekit.io/transport/self-hosting/distributed/).

## Showcase, observability and evidence

### Showcase and UI

- The [demo plan](demo-plan.md) defines a visible normal/failure proof for each
  library and the implemented intake/diagnostic plus Phase G business/native-media
  showcase.
- UI transitions must follow actual responses/events, retain unknown outcomes and
  respect reduced-motion preferences.
- Keep the real native session contract and authority visible. Use official UI
  components only when a genuine consumer needs them
  ([Agents UI components](https://docs.livekit.io/frontends/agents-ui/)).
- A visual refresh alone does not justify a frontend framework migration.

### Observability

The [observability contract](observability.md) separates implemented
metrics/logs/inspected filtered traces, the measured H1 inquiry baseline and
still-open broader workload studies.

### Harness evidence

- The harness remains deliberately small.
- Structural success, Python tests, frontend checks, actual real-time
  communication (RTC) smoke, browser observations and model evaluation are
  separate lanes.
- Missing tests, required skips, timeouts and planned acceptance runners cannot
  become passing product evidence.
- Import scanning is a useful structural guard, not a complete language resolver
  or runtime sandbox.

## Observed UI audit steps

These observations belong to the historical foundation audit, not the later
Phase G media gate or a new claim about every browser/device.

| Step | Area | Result | Observations |
| --- | --- | --- | --- |
| 1 | Entry and connection | Healthy after fixes | Invalid-token recovery, scoped room connection and real agent arrival were observed. Controls wait for the agent |
| 2 | Realtime activity | Healthy for browser text and explicit reconnect | Echo came from the SDK agent. Microphone/playback remain unverified |
| 3 | Durable intake | Healthy for the implemented foundation | Acceptance, same-task replay, changed-payload rejection and original-payload recovery were observed |
| 4 | Navigation and reflow | Native details/keyboard activation worked | 1280px and 390px layouts had no horizontal overflow |

Step 4 does not establish full Web Content Accessibility Guidelines (WCAG)
compliance or every browser/device combination.

Initial screenshots showed a functioning token boundary and honest planned
labels, but unrelated green styling, a passive log and no visible durable proof.
The revised screen uses the current LiveKit brand reference, explicit
waiting/connected states, a real intake transition sequence and visibly planned
project stories. Accepted captures and their scope are retained with the
work-item evidence. Results and unresolved limits are recorded in the
[audit work item](work-items/0004-plan-and-showcase-audit.md).

### Later changes

- Subsequent Phase F/G implementation adds durable leased execution, the scoped
  native/current-case profile and inspected raw Jaeger v3 traces.
- The [Phase G work item](work-items/0013-p1-phase-g-conversation-and-showcase.md)
  owns its inspected local combined gate.
- Controls wait for public RoomIO readiness and the exact native attribute.
  Alternate SDK session hosting is disabled.
- The [current qualification status](#current-qualification-status) summarizes the
  later P1 release and the limits that remain.
