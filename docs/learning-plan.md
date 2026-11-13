# Ecosystem development learning plan

Status: Active
Last reviewed: 10 November 2026

This plan supplies learning objectives and exercises for the
[build plan](build-plan.md) and its [granular task roadmap](implementation-plan.md).
It does not define a second implementation schedule.
The aim is an implementation that its author can explain, change and debug.

## Time allocation

Use approximately 12–15 hours per week across implementation, testing, review and
study. Reserve at most 3–4 hours for supporting lessons and practice; that time
is part of the total. Re-estimate after the first inquiry/recovery slice using
actual progress. The build plan owns delivery estimates and dependencies.

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

Use explain, attempt, review, change for each feature. Explain expected behavior
and failure cases, attempt a bounded implementation, run it, review it and make a
second change that tests understanding. Use AI for feedback and record assistance
accurately. Revisit difficult small components unaided after a gap.

For independent practice, use an isolated async exercise or small coding problem
that supports the current work. Keep practice separate from product release
claims. A generated scaffold or a passing test alone does not establish personal
implementation skill.

## Recovery and effect learning sessions

P1-I01 through P1-I18 and shared S-I05 are implemented; Phase E final combined
verification passed. Phase F implements P1-I19 through P1-I21 and passed its
combined gate. G implements P1-I22 through P1-I25 and its inspected local gate;
reproduce inquiry, consent, effect, lease/takeover and native-media boundaries,
then explain the measured
[H1 seeded inquiry baseline](work-items/0014-p1-phase-h-workload-baseline.md). The
granular roadmap and [Phase G work item](work-items/0013-p1-phase-g-conversation-and-showcase.md)
record the gates and qualification deltas. Permission-dependent media
gaps block their corresponding integration gate, not independent deterministic
backend work.
Do not infer browser microphone evidence from native SDK smoke. Remote Linux CI
is outside this local POC scope.

1. Run BASE-01 and trace the current canonical request into its transaction.
2. Explain why existing queued-only storage needs a versioned extension before
   execution state changes; test preservation of an existing database.
3. Trace the implemented worker and persisted fake supplier, then make one
   bounded learning change with an added failure assertion.
4. Place the crash barrier after inquiry success and before local acknowledgement.
5. Restart, inspect both stores and explain reconciliation under the stable key.

The five exercises above reproduce the historical read-only inquiry slice; they
do not authorize booking mutation. Now trace a v2 exact proposal through its
case/supplier/revision binding, intent, mutation attempt, cancellation disposition,
immutable business outcome and completion delivery. Reproduce both cooperating
reconciliation and noncooperating uncertainty, and explain why a delivered event
does not prove a human saw it. Read a legacy v1 receipt without inventing new
supplier authority.

For the Phase F checkpoint, explain the difference between a claim generation and a
renewable execution lease. Test stale database writes and stale supplier calls
separately, then show eligible current work progresses. The build plan owns the
sequence and acceptance mapping. Use actual implementation/review time to
re-estimate; historical estimates are not remaining-effort promises. Learn
installed-consumer checks when a real second consumer establishes the boundary,
and replay-safe retention before adding cleanup.

For H reproduction, trace the server clock after a contended database lock, a lease
renewal/release and a paused old worker resuming after takeover. Explain why that
worker loses local write authority while a supplier may still receive its request.
Inspect pending versus active versus retained capacity, including unresolved
inquiry uncertainty, and reproduce useful progress for another admitted workflow.
Then terminate/restart the real P1 worker without reset and identify the same
accepted task, wait/effect and completion. These exercises establish understanding;
Codex-assisted implementation is not an asserted personal coding contribution.

Trace a G native tool through its signed bound port to the original durable task,
then end the room and rehydrate status through a fresh consumer. Explain why the
public RoomIO readiness barrier must precede interruption, why alternate SDK
session hosting is disabled, and why exact quote confirmation stays in the
authenticated panel. Inspect one raw Jaeger v3 trace without treating trace IDs
as consent or business truth. Distinguish the bundled-WAV WebAudio media proof,
real permission denial, hardware capture and live inference. Remote CI is outside scope.

For S-I06 and the first P1-I27 workload slice, reproduce the frozen H1 declaration
and inspect actual schedule/cadence, client-observed timing, cgroup limits and
independent supplier/receiver reconciliation. Explain the shared-host and polling
limits before drawing a scaling conclusion. Freeze hardware, mode, seed, schedule
and budgets before every later workload. Study the passed H2 reliability slice
and I26 host/Linux installed artifacts, API/failure review and genuine native
consumer. P1 V1 is qualified for the local POC using provider_real v2. local_real remains unqualified and complete P2/P3 acceptance remains pending. Hosted CI/publication are outside the local POC scope; a measured
inquiry baseline does not complete the other gates.

## Handoff and readiness

Record behavior attempted, assumptions that failed, tests added, decisions,
assistance and remaining work in the work item. Rehearse a short explanation and
one small code change without relying on the previous generated answer. Publish
only capabilities supported by implemented checks and retained evidence.


### Explicit provider-real profile

The trusted mode enum is scripted (default), local_real or provider_real.
provider_real uses livekit-plugins-deepgram, livekit-plugins-openai and
livekit-plugins-elevenlabs, all pinned to 1.8.11 with Agents 1.8.11. The fixed
pipeline is Deepgram nova-3 batch recognition on manual flush, OpenAI gpt-5.4-mini
streaming Chat Completions with none reasoning and at most 128 output tokens,
and ElevenLabs eleven_v4_turbo chunked HTTP PCM speech. It is a separately
selected profile, never an automatic fallback from a failed local engine.

The [provider operations guide](provider-demo.md) owns explicit setup/check/start/stop and
the trusted provider P1-20 selector. Three private keys reach only the native
process; local model caches and engines are unnecessary. The selected provider_real v2 gate passed both actual browser cases with cleanup. P1 V1 is qualified for the local POC using provider_real v2. External provider CPU/memory are
unobserved; no zero-retention or model-quality guarantee follows from local
content-free telemetry. Default offline/scripted checks make no provider calls.
