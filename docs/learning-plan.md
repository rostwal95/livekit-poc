# Ecosystem development learning plan

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Give the developer who builds the ecosystem learning objectives and exercises for each build stage |
| Audience | The developer building the ecosystem who wants to understand each part well enough to defend it |
| Scope | Time allocation, stage objectives, the collaborative method and P1 learning exercises; excludes delivery estimates and sequencing |
| Owns | Learning objectives by build stage, practice exercises and the explain, attempt, review, change method |
| Related | [Build plan](build-plan.md) · [Granular task roadmap](implementation-plan.md) · [Phase G work item](work-items/0013-p1-phase-g-conversation-and-showcase.md) · [Provider operations guide](provider-demo.md) |

This plan is for the developer who builds the ecosystem and wants to understand
each part well enough to defend it. It supplies learning objectives and exercises
for the [build plan](build-plan.md) and its
[granular task roadmap](implementation-plan.md). It does not define a second
implementation schedule. The aim is an implementation that its author can
explain, change and debug.

| Term | Meaning |
| --- | --- |
| Task IDs such as P1-I19 or S-I05 | Tasks in the granular roadmap; they are not acceptance IDs |
| Phases A to H | The P1 implementation phases, recorded in work items [0007](work-items/0007-p1-phase-a-execution-foundation.md) to [0019](work-items/0019-p1-phase-h-release-qualification.md) |

## Time allocation

| Budget | Value | Notes |
| --- | --- | --- |
| Weekly total | Approximately 12–15 hours | Covers implementation, testing, review and study |
| Supporting lessons and practice | At most 3–4 hours | Part of the weekly total |

Re-estimate after the first inquiry/recovery slice using actual progress. The
build plan owns delivery estimates and dependencies.

## Learning objectives by stage

| Build stage | Concepts to understand | Evidence of understanding |
| --- | --- | --- |
| Foundation qualification | Browser authentication, sender/schema checks, explicit media permission and evidence limits | Explain which local browser, native SDK and installed-artifact checks have actually run |
| First recovery slice | Python types, canonical payloads, transactions, process lifetime and async I/O boundaries | Explain the SQLite crash window, supported compatibility subset and the early PostgreSQL adapter checkpoint |
| Durable semantics | State transitions, signals, deadlines, confirmation, idempotency and uncertain effects | Trace an accepted operation and distinguish retryable failure from uncertainty |
| Multi-worker execution | Claims, leases, stale-write rejection, migrations and PostgreSQL transactions | Reproduce takeover and explain the separate supplier boundary |
| Media foundation | LiveKit rooms, sessions, tracks, tools, text streams and interruption evidence | Diagnose a real local media flow and trace one tool into durable work |
| Channel continuity | TypeScript strict types, runtime schemas, inbox/outbox, identity and revisions | Explain a delayed confirmation and recover accepted input after a crash |
| Delegation | Native tools/subagent baseline, trusted HTTP principals, P1-owned attempts and result applicability | Explain the remote boundary, reject stale results and allow current results to progress |
| Release hardening | Load methodology, observability, API ergonomics and evidence limits | Run a reproducible benchmark and explain what it establishes |

## Collaborative method

Use explain, attempt, review, change for each feature:

1. Explain the expected behavior and failure cases.
2. Attempt a bounded implementation and run it.
3. Review it.
4. Make a second change that tests your understanding.

- Use AI for feedback and record assistance accurately.
- Revisit difficult small components unaided after a gap.
- For independent practice, use an isolated async exercise or small coding problem
  that supports the current work.
- Keep practice separate from product release claims.
- A generated scaffold or a passing test alone does not establish personal
  implementation skill.

## Recovery and effect learning sessions

These sessions reproduce the implemented P1 inquiry, consent, effect,
lease/takeover and native-media boundaries, then explain the measured
[H1 seeded inquiry baseline](work-items/0014-p1-phase-h-workload-baseline.md).

| Session | What it reproduces |
| --- | --- |
| [Read-only inquiry slice](#read-only-inquiry-slice) | The historical read-only inquiry slice, its crash barrier and reconciliation |
| [Exact consent, effects and completion](#exact-consent-effects-and-completion) | Exact v2 proposals, mutation attempts, reconciliation and completion delivery |
| [Leases and takeover (Phase F)](#leases-and-takeover-phase-f) | Claim generations, renewable leases, stale writes and stale supplier calls |
| [Native conversation and traces (Phase G)](#native-conversation-and-traces-phase-g) | Native tools, fresh-consumer rehydration, readiness and raw traces |
| [Clocks, capacity and restart (Phase H)](#clocks-capacity-and-restart-phase-h) | Server time after takeover, capacity and real worker restart |
| [Workloads and installed artifacts](#workloads-and-installed-artifacts) | The frozen H1 workload, the H2 reliability slice and I26 installed artifacts |

### Current status

| Scope | Status | Evidence |
| --- | --- | --- |
| P1-I01 through P1-I18 and shared S-I05 | Implemented; the Phase E final combined verification passed | [Phase E work item](work-items/0011-p1-phase-e-effects-and-completion.md) |
| Phase F: P1-I19 through P1-I21 | Qualified: passed its combined gate | [Phase F work item](work-items/0012-p1-phase-f-leases-and-deployment.md) |
| Phase G: P1-I22 through P1-I25 | Qualified: passed its inspected local gate | [Phase G work item](work-items/0013-p1-phase-g-conversation-and-showcase.md) |
| P1 V1, the fixed first-version scope of P1 | Qualified for the local proof of concept (POC) using provider_real v2 | [Phase H release work item](work-items/0019-p1-phase-h-release-qualification.md) |
| local_real | Not qualified | [Local real-inference operations](local-real-inference.md) |
| P2 and P3 | Partial: complete P2/P3 acceptance remains pending | [Checkpoint history](checkpoint-history.md) |

The granular roadmap and the
[Phase G work item](work-items/0013-p1-phase-g-conversation-and-showcase.md)
record the gates and qualification deltas.

### Scope limits

- Permission-dependent media gaps block their corresponding integration gate, not
  independent deterministic backend work.
- Do not infer browser microphone evidence from native SDK smoke.
- Remote Linux continuous integration (CI), hosted CI and publication are outside
  this local POC scope.

### Read-only inquiry slice

1. Run BASE-01 and trace the current canonical request into its transaction.
2. Explain why existing queued-only storage needs a versioned extension before
   execution state changes. Test preservation of an existing database.
3. Trace the implemented worker and persisted fake supplier, then make one
   bounded learning change with an added failure assertion.
4. Place the crash barrier after inquiry success and before local acknowledgement.
5. Restart, inspect both stores and explain reconciliation under the stable key.

These five exercises reproduce the historical read-only inquiry slice. They do
not authorize booking mutation.

### Exact consent, effects and completion

1. Trace a v2 exact proposal through its case/supplier/revision binding, intent,
   mutation attempt, cancellation disposition, immutable business outcome and
   completion delivery.
2. Reproduce both cooperating reconciliation and noncooperating uncertainty.
3. Explain why a delivered event does not prove a human saw it.
4. Read a legacy v1 receipt without inventing new supplier authority.

### Leases and takeover (Phase F)

1. Explain the difference between a claim generation and a renewable execution
   lease.
2. Test stale database writes and stale supplier calls separately.
3. Show that eligible current work progresses.

The build plan owns the sequence and acceptance mapping. Use actual
implementation and review time to re-estimate. Historical estimates are not
remaining-effort promises. Learn installed-consumer checks when a real second
consumer establishes the boundary, and learn replay-safe retention before adding
cleanup.

### Native conversation and traces (Phase G)

1. Trace a G native tool through its signed bound port to the original durable
   task.
2. End the room and rehydrate status through a fresh consumer.
3. Explain why the public RoomIO readiness barrier must precede interruption, why
   alternate SDK session hosting is disabled, and why exact quote confirmation
   stays in the authenticated panel.
4. Inspect one raw Jaeger v3 trace without treating trace IDs as consent or
   business truth.
5. Distinguish the bundled-WAV WebAudio media proof, real permission denial,
   hardware capture and live inference.

### Clocks, capacity and restart (Phase H)

1. Trace the server clock after a contended database lock, a lease
   renewal/release and a paused old worker resuming after takeover.
2. Explain why that worker loses local write authority while a supplier may still
   receive its request.
3. Inspect pending versus active versus retained capacity, including unresolved
   inquiry uncertainty.
4. Reproduce useful progress for another admitted workflow.
5. Terminate and restart the real P1 worker without reset, then identify the same
   accepted task, wait/effect and completion.

These exercises establish understanding. Codex-assisted implementation is not an
asserted personal coding contribution.

### Workloads and installed artifacts

1. For S-I06 and the first P1-I27 workload slice, reproduce the frozen H1
   declaration.
2. Inspect actual schedule/cadence, client-observed timing, cgroup limits and
   independent supplier/receiver reconciliation.
3. Explain the shared-host and polling limits before drawing a scaling
   conclusion.
4. Study the passed [H2 reliability slice](work-items/0015-p1-reliability-workloads.md)
   and the [I26](work-items/0016-p1-standalone-package.md) host/Linux installed
   artifacts, API/failure review and genuine native consumer.

Freeze hardware, mode, seed, schedule and budgets before every later workload. A
measured inquiry baseline does not complete the other gates.

## Explicit provider-real profile

The trusted mode enum is scripted (default), local_real or provider_real.
provider_real uses these pinned packages:

| Requirement | Version or value |
| --- | --- |
| `livekit-plugins-deepgram` | 1.8.11 |
| `livekit-plugins-openai` | 1.8.11 |
| `livekit-plugins-elevenlabs` | 1.8.11 |
| LiveKit Agents | 1.8.11 |

Its fixed pipeline has three stages:

| Stage | Fixed choice |
| --- | --- |
| Recognition | Deepgram nova-3 batch recognition on manual flush |
| Reasoning | OpenAI gpt-5.4-mini streaming Chat Completions with none reasoning and at most 128 output tokens |
| Speech | ElevenLabs eleven_v4_turbo chunked HTTP PCM speech |

provider_real is a separately selected profile, never an automatic fallback from
a failed local engine. The [provider operations guide](provider-demo.md) owns
explicit setup/check/start/stop and the trusted provider P1-20 selector.

- Three private keys reach only the native process. Local model caches and
  engines are unnecessary.
- The selected provider_real v2 gate passed both actual browser cases with
  cleanup.
- External provider CPU and memory are unobserved. No zero-retention or
  model-quality guarantee follows from local content-free telemetry.
- Default offline and scripted checks make no provider calls.

## Handoff and readiness

- Record the behavior attempted, assumptions that failed, tests added, decisions,
  assistance and remaining work in the work item.
- Rehearse a short explanation and one small code change without relying on the
  previous generated answer.
- Publish only capabilities supported by implemented checks and retained
  evidence.
