# P1 Phase G conversation, visible continuity and traces

Status: Completed
Last reviewed: 10 November 2026

## Behavior and scope

Implement P1-I22 through P1-I25 after Phase F passed. Connect a separate native
AgentSession consumer to durable work, add an authenticated business workspace,
export inspected safe OTLP traces, and verify actual browser scripted speech,
interruption and reconnect. Preserve the diagnostic room and M1 intake.

| Requirement contribution | Given/when | Safety acceptance | Useful progress | Evidence |
| --- | --- | --- | --- | --- |
| P1-14/20 / I22 | Native function tools encounter slow storage or session closure | No event-loop blocking, model-created confirmation, scope override or new identity after ambiguous acknowledgement | Same explicitly authorized investigation is atomically accepted and continues independently | Native SDK tool runs, real PG, bounded async tests |
| P1-17/20 / I23 | Browser submits, requests a quote, approves, disconnects or resumes | Snapshot authority is persisted; stale/unknown observations stay honest; exact canonical quote survives JavaScript BIGINT boundaries | Current scoped work, effect/outcome and delivery become visible with smooth observed transitions | Frontend controllers, HTTP contracts and real browser |
| P1-18/20 / I24 | Real SDK/application spans export, or collector fails | Bounded queues/bytes/time; no transcript, credentials, arbitrary attributes or raw errors; telemetry cannot change authority | Inspect an actual exported trace and real finite metrics/report observations | Sanitization/outage tests and local OTLP receiver |
| P1-14/20 / I25 | Browser publishes scripted audio, receives speech, interrupts, ends and reconnects under held dependencies | Only explicit UI approval authorizes mutation; interruption/end never cancel accepted business work | Responsive native session and durable completion survive session lifetime | Actual browser WebRTC input/output, native SDK and independent supplier state |

## Interfaces and ownership

PostgresManagedAdmission commits execution, distinct case/owner and continuation
with its original absolute deadline in one protected transaction. Existing M1
admission and explicit operator interfaces remain compatible. Legacy keys without
that atomic managed state cannot be silently adopted. Replay precedes new quotas.

The business service authenticates every call. HTTP routes derive principal/scope
from server configuration; native tools receive a signed expiring room/participant
binding and frozen investigation request. Model tools are submit/get/cancel only.
Quote production is an explicit trusted controller action using the same supplier
identity/revision outside database locks, then atomic quote/wait publication.
Exact confirmation is a separate authenticated UI action. BIGINT revision/version
fields are decimal strings; the UI returns opaque canonical confirmation JSON
without reconstructing numeric fields. No new workflow schema or event bus is added.

The projection always returns current state plus bounded recent persisted
observations. Its scoped digest/cursor resets on aggregate change and discloses
history truncation. Native SDK notifications request a fresh authenticated read;
they do not become authority. Tokens and task selection stay out of browser
persistent storage; explicit resume reauthenticates a supplied task identity.

Native AgentSession uses deterministic local STT/LLM/TTS fixtures, real audio
frames and native tool execution. The default explicit browser scripted source
uses a real Web Audio MediaStream/LocalAudioTrack from bundled spoken PCM, with
device microphone capture as a separate bounded source. No getUserMedia override,
transcript injection or synthetic progress is used. The
[composition decision](../decisions/0007-native-conversation-and-local-media.md)
records the observed host capture limitation and source choice. Manual push-to-talk avoids implicit model
preloading. Scripted speech is not model-quality or human microphone evidence.
OTLP uses installed compatible dependencies with strict exported-field filtering
and an owned HTTP transport that ignores ambient credential/proxy hooks.
Playwright 1.65.0 is an exact-pinned development-only first consumer for actual
browser media/UI gates; existing application runtime dependency pins stay frozen.

## Failure cases and validation

Required gates include atomic rollback/lost acknowledgement/deadline replay,
changed payload/scope/actor denial, exact quote and stale revision checks, bounded
history/cursor resets and BIGINT roundtrips. Exercise public HTTP auth/body/response
limits, unknown acknowledgements, polling cancellation/reconnect and safe DOM
rendering. Native SDK tools must execute in a real AgentSession; mock function
calls alone do not establish the conversational path.

Browser media uses an isolated controlled browser and explicit controls with a
known scripted audio source. Observe actual WebRTC samples and browser playback,
PTT interruption, session end/reconnect, held supplier and slow persistence.
Permission denial is a distinct negative scenario. Physical microphone/human
hearing and real-model quality remain separate evidence. Missing required setup,
zero tests, skips or timeouts cannot pass the combined phase gate.

Keep telemetry queue/export/shutdown and model/SDK resource bounds finite. Inspect
an actual local trace, not merely Jaeger UI readiness; exporter refusal/timeouts
must preserve business results and responsiveness. Run full offline/type/style,
frontend, real PostgreSQL, installed runtime, prior compatibility and original
RTC/M1 lanes before handoff. Retain failed artifacts and clean only owned state.

## Results and handoff

P1-I22 through P1-I25 passed their local combined gate. Two complete runs used
fresh isolated schemas, supplier/receiver state and media identities with the same
installed source and runtime image. Each run passed all six actual browser cases
without skips or flaky retries, inspected exported traces and verified owned
container, volume and schema cleanup. Original M1 and diagnostic behavior remains
available. This closes this granular phase, not the full P1 charter or portfolio.

| Lane | Observed final result |
| --- | --- |
| Full offline Python/harness, lint and normal types | 663 tests, zero skips; lint clean; 75 service/core files typed, plus the strict process-control boundary |
| Strict changed boundaries | 19 core, HTTP and native service files pass strict typing |
| Python formatting | 165 files pass the maintained format check |
| Frontend | 263 tests, strict app/browser-test types and production build pass |
| Real PostgreSQL | 255 tests, zero failures, errors or skips on the final source |
| Native SDK regressions | 41 real-SDK/control/cleanup/privacy tests included in the offline suite |
| Actual browser/container gate | Two independent complete runs; six required cases pass in each; Chrome 158.0.8127.18 and Playwright 1.65.0 |
| Independent business truth | One original task, intent and signal consumption; one inquiry, applied mutation, booking revision advance and logical receiver event |
| Observability | Actual raw Jaeger v3 OTLP data from business-api, conversation-agent and durable-worker; current task correlation and content/field exclusion verified in all three |
| Earlier installed behavior | Phase E effect/crash and Phase F leased-worker/restart compatibility pass; their closed artifacts restored byte-for-byte |
| Original M1/RTC | Auth, replay/conflict, named dispatch, text/UTF-8 and ten returned audio frames pass; the original M1 task identity is retained |
| Documentation and design | 80 documents pass policy/link checks; all 36 Mermaid views across 12 Designs parse; diff whitespace checks pass |
| Acceptance registry | Six registered runners pass; 49 full product rows still have no complete runner. The whole-catalog deep command correctly exits 2 with incomplete status |

The browser gate verifies explicit scripted WAV publication through native WebRTC,
received media-element playback advancement, the actual accepted reply, active
speech interruption, a new native consumer's status reply for the same durable
case, explicit reload/resume and real microphone permission denial. The
PostgreSQL fault proves a native-container schema advisory waiter, then requires
remote interrupt acknowledgement and local source stopping before release under
the unchanged SQL lock timeout. The held-supplier case similarly requires media
controls while the real quote HTTP response remains pending, then useful quote
progress. Exact UI approval must preserve the opaque canonical confirmation bytes.
Outcome and receiver delivery are separately observed.

Phase artifacts are generated under `.local/validation/p1-phase-g/`:
`phase-gate.json`, `container-demo.json`, `container-demo-first.json`,
`postgres.json`, the two earlier-phase compatibility reports, documentation and
Mermaid results, safe passing stage summaries and credential-empty screenshots.
Failed runs retain bounded safe evidence. Machine inventories bind the installed
modules, compiled console assets, packaged WAVs, dependency locks and actual
runtime versions; no source snapshot identifiers are added to this document.

Reproduce with the frozen environment and built images described in the root and
local setup guides:

```sh
make check
make format-check
make frontend-check
make postgres-check
make phase-g-demo
.venv/bin/python local-setup/stack.py smoke
HARNESS_PYTHON=.venv/bin/python sh scripts/harness-deep.sh
```

The deep command's incomplete result remains expected until the other complete
charter assertions are implemented and registered; it is not a passing release
command. The dedicated Phase G browser helper supports an explicit pinned browser
executable as described in the local setup guide.

Review and real integration corrected the following boundaries:

- Classic SDK tool execution delayed interruption until storage completed. The
  native tools now use one silent RunContext update before awaiting real durable
  I/O; final receipts alone can acknowledge acceptance or trigger a refresh hint.
- Interrupting startup speech before the first audio subscription could cancel a
  shared readiness future in the frozen SDK and suppress later audio/transcripts.
  A deterministic regression reproduces that precondition. The service now awaits
  the public RoomIO readiness barrier, bounded to ten seconds, before greeting or
  enabling controls; the UI requires the selected native agent's readiness attribute.
- The SDK's default session host exposed an alternate input route. This profile
  disables it through the public session_host option and tests that only its
  bounded caller-checked text/RPC controls remain registered.
- Initial connection failures now retain actual pending media cleanup ownership;
  no replacement adapter is created while prior resources remain unresolved.
- Browser resume setup now waits for an authenticated projection, not an entered
  task identifier. DOM-state assertions use the actual canonical lowercase values.
- The helper checks installed modules/assets and served compiled console hashes
  before browser execution. CI builds matching host console assets first.
- Trace inspection uses the pinned collector's bounded raw v3 API and validates
  original OTLP resource/scope/span fields, without accepting collector-added text.
- The helper retains verified browser/SDK stages before later checks. Independent
  receiver visibility may converge within a finite fifteen-second budget; wrong
  provider/revision, extra mutations/inquiries or missing apply progress fail
  immediately. A business outcome never serves as delivery acknowledgement.

Next is Phase H, beginning with the declared S-I06/P1-I27 seeded steady, burst and
saturation workload baseline. Freeze workloads, hardware/resource assumptions and
budgets before measuring. P1-I26 still needs genuine-consumer/public API and
independent artifact review; the current application wheel does not establish the
planned generic reusable execution release. P1-I28 configured real inference,
measured restart/slow-provider/media workloads, supported-platform qualification
and remote Linux CI execution remain separate evidence. Physical microphone
quality, human hearing/acknowledgement and production capacity are not established
by the scripted local gate. P2 and P3 remain planned.

Implementation and review used AI coding assistance. Portfolio presentation must
retain that attribution and explain the state, consent, failure and evidence
boundaries rather than claiming an independently authored production release.
