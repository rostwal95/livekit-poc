# Local console coding agent instructions

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Give coding agents the reading order, owned paths, rules and checks for local console changes |
| Audience | Coding agents and engineers changing the browser console or its optional pages |
| Scope | Default console and its opt-in pages; excludes backend case, consent, effect and delivery authority |
| Owns | Local console agent reading order, owned paths, development rules and verification |
| Related | [Root instructions](../../AGENTS.md) · [Console guide](README.md) · [Console design](Design.md) · [Local setup guide](../../local-setup/README.md) · [Observability guide](../../docs/observability.md) |

## Read first

Read these documents:

| Document | Why read it |
| --- | --- |
| [Root instructions](../../AGENTS.md) | Follow first: repository-wide reading order, rules and verification |
| [README.md](README.md) | Implemented pages, owned interfaces, limits and commands |
| [Design.md](Design.md) | Component design, limits and failure handling for every page |
| [Local setup guide](../../local-setup/README.md) | Stack lifecycle, readiness and isolated browser-gate orchestration |
| [Shared projection contract](../../contracts/business/case-projection.json) | Shared business case projection evidence |
| [Observability guide](../../docs/observability.md) | Signals, safe errors, cardinality and operational evidence |
| The active P1 work item | Where results and evidence paths for the change are recorded |

Contents: Development rules first cover the default console, then the optional
pages: the isolated P2 native input page, the v7 response evidence view, the
current-case context panel, the operations read page and the joined showcase page.
Verification follows the same order.

## Owned paths

| Area | Responsibility |
| --- | --- |
| This directory | The browser console, pure typed client/controller helpers, unit and browser tests, build configuration and static-server configuration |
| Business controller | Frozen client requests and display observations |
| Voice controller | Real-time communication (RTC) lifecycle and media resources |
| Backend authorities | Case scope, revision checks, consent, intent commitment, effects and delivery |
| Retained M1 intake and diagnostic transport | Separate implemented paths; M1 is the existing confirmed-investigation intake |

## Development rules

### Types, wire schemas and quote bytes

- Use strict TypeScript and the pinned native LiveKit SDK.
- Validate public wire schemas and cross-field identities at runtime.
- BIGINT revisions, generations and epochs remain canonical decimal strings.
- Preserve the exact original opaque quote confirmation payload.
- Never regenerate the quote confirmation payload with a JavaScript numeric round trip.
- Compare displayed quote facts with its canonical bytes before enabling consent.

### Rendering, tokens, Forget and task hints

- Render dynamic text with textContent.
- Keep tokens out of builds, URLs, browser storage, logs and evidence.
- Clear the private input on use.
- Explicit Forget and pagehide clear shared credentials and release room/readers/tracks.
- Reload requires explicit scoped resume.
- Browser task hints require a selected native AGENT sender, reliable topic/schema
  validation and authenticated GET before any business update.
- A model statement, speech state or playback event never authorizes a mutation.

### Native agent readiness

- Gate input/RPC/status on a connected selected native AGENT with all of the following:
  - observed SDK state idle/listening/thinking/speaking;
  - the exact public `continuity.session_ready` attribute true, produced after actual
    RoomIO subscription readiness;
  - an exact `continuity.inference_mode` match to the authenticated mint mode.
- Presence or Listening alone is not sufficient.
- Preserve stopping published input and End when readiness is lost.

### Input publishing and playback

- Publishing either scripted local input or the physical microphone requires a user
  action.
- Default to the explicitly labelled local WAV/WebAudio source.
- Never replace getUserMedia or claim that a scripted stream proves hardware capture.
- Keep physical microphone permission denial real and separate.
- Own a created input before awaiting publish so timeout/End can stop it even during
  a stalled publication.
- Keep mute available after agent departure and during reconnect.
- Separate native speech state from actual browser playback.
- End voice and speech interruption never call business cancellation.

### Inference modes and timeouts

- Scripted is the default.
- local_real and provider_real are selected only by trusted server configuration.
- The strict mint response accepts exactly those three modes.
- Before native matching readiness, show a configured expected profile.
- A badge never qualifies actual model quality.
- Keep WAV fixture input separate from inference mode and physical capture.
- Preserve 8-second scripted/other RPCs, 12-second real commit and 5-second media
  cleanup.
- Incoming transcription keeps two readers of 16 KiB each, with a whole stream
  deadline of 10 seconds for scripted or 40 seconds for local_real or provider_real.
- Abort on room closure and clear owned timers on exit.
- Trusted inference modes are exactly scripted (default), local_real and provider_real.
- Preserve the selected mode through mint, native readiness, numeric usage and
  sanitized traces.
- A configured badge or process health is not actual inference/media qualification.
- No silent provider/model fallback exists.
- All modes preserve bound tools and separate exact human confirmation.
- Read the [provider operations guide](../../docs/provider-demo.md) before changing
  provider composition.
- Offline validation must not read private key values or invoke providers.
- Never source, print, copy or include `local-setup/.env.providers` in reports or
  build contexts.
- Only the explicit native provider runtime receives the three keys.
- Accept all three exact wire modes, require matching native attributes plus SDK
  readiness and reset stale mode on lifecycle changes.
- Real commits keep 12 seconds and real transcription streams 40 seconds. Other RPCs
  remain 8 seconds and cleanup 5 seconds.
- Provider credentials never enter UI state or evidence.

### Reconnect, End and new rooms

- Keep automatic transport reconnect and unknown mint retries bound to the exact
  current room/participant/invocation.
- After explicit End or an established native disconnect, create fresh media
  identities only on the next Join after actual cleanup.
- The durable task/case stays the same.
- Require a new live consumer reply, not stale participant presence or retained text,
  to qualify continuation.
- Retain unresolved media-operation ownership across End/disconnect.
- Block new room creation until actual cleanup settles, or require explicit page
  reload/resume.
- Fence late HTTP/RTC acknowledgements across lifecycle changes.

### Bounds, retries and observed state

- Bound HTTP response bytes, incoming text readers/duration, active operations,
  retries and displayed history.
- Retain frozen investigation or command identities after any possibly accepted attempt.
- Retry unchanged.
- Unknown reads preserve last observed facts.
- Only persisted current snapshots and validated receipts can update workflow state.
- Cursors page a bounded recent observation window, not a complete audit log.

### Consent, controllers, accessibility and progress

- Preserve the M1 consent and replay contract.
- Keep business, voice and transport controllers separate, with native SDK adapters
  outside pure state decisions.
- Support keyboard access, clear labels, responsive layout and reduced motion.
- Do not add timers that invent progress or simulate supplier/worker observations.

### Isolated P2 native input page

- The optional p2-native.html page uses its separate vite.native.config.ts and
  p2-native-build target.
- It is not the default M1/P1 console or an automatically deployed Compose service.
- Durable input acceptance, native SDK generation and browser playback appear as
  separate facts.
- Only reliable data from the selected native AGENT can update six-key generation
  observations, and it must match known accepted input/operation.
- Sixty-four generation identities and thirty-two retained inputs bound local state.
- Known receipts survive stale notifications.
- A rejected retry cannot erase unknown original acceptance.
- End closes owned media/I/O and does not business-cancel.
- The profile is explicitly scripted and fixture-driven. Positive microphone, general
  automatic speech recognition (ASR) and live-model quality are not implied.

### Response evidence view (optional v7 page)

The [playback phase](../../docs/work-items/0037-playback-evidence-and-process-recovery.md)
adds the opt-in v7 response view and its separately recorded qualification.

- The optional v7 page keeps generated text, SDK output and client-reported playback
  in separate lanes.
- Accept p2.response only from the selected native AGENT and an already known
  input/operation.
- Read the bounded full response through the fixed operator-authenticated POST.
- RTC grants carry no read/publication capability.
- Keep monotonic receipt counts, stale-read fences and immutable original identity.
- Interrupt the exact response handle through p2.interrupt_response.
- The legacy session-wide interrupt exists only for the older native profile.
- Neither a remote interrupt request nor local pulse-code modulation (PCM)
  observation proves hearing, stopped external work, acknowledgement or consent.
- Client completion is an explicit report.
- Missing reports stay unknown.
- Keep the checkbox that allows the demo to withhold client reports.
- Own AudioContext/worklet/port/source lifetimes through late settlement and failed close.
- End remains incomplete until all actual owners settle.
- Measure real PCM in a response window on the continuous selected track while
  output is playing.
- The meter is not a per-word playout synchronizer.
- Do not add timers that invent progress.

### Current-case context panel

A and B are the first and second room's SDK/RTC instances.

- The optional context panel is read-only.
- Validate the current grant-bound snapshot, keep original accepted
  receipt/operation/source identities and display independent case/history
  observation times.
- A matching case revision does not make cached workflow or supplier outcomes current.
- Explicit idle refresh is required.
- Preserve loaded revision 0 without enabling the positive-revision native
  intake/prepare contract or automatically revising authority to manufacture progress.
- Keep context reads and the fixed dormant-SMS request as separate bounded owners.
- Late replies must match their original session/ticket.
- An aborted waiter is not actual I/O settlement.
- Old-room responses stay inert history and cannot become B interrupt/playback controls.
- End closes media and retains unresolved owners.
- End neither revokes backend history nor business-cancels accepted input.
- The application closes A before the parent deletes its room, performs the fixed
  signed SMS with no A/B room, and waits for owned B-ready evidence before fresh mint.
- Keep failed/unknown stages truthful and preserve original mint on uncertain retry.

### Native RTC text conversation and policy card

- The SDK session and authenticated read capabilities of the opt-in native RTC text
  conversation and compact policy card remain separate from P2 durable native intake
  and the default P1 console.

### Operations read page (opt-in)

#### Build and bundle

- The separate p2-operations.html / vite.operations.config.ts / operations
  TypeScript profile uses only the public browser-safe P2 operations-types export.
- Preserve the default Docker build exclusion and the explicit workspace dependency.
- No checkout product-source alias or Node runtime module belongs in this browser bundle.

#### Read binding and size limits

- Pin the first authenticated read-view binding and reject changed account, case,
  conversation or native identity for that activation.
- Preserve the original 65,536 byte context envelope, the new 8,192 byte
  cursor/request frame and the 73,728 byte total.
- Process diagnostics have a separate 16,384 byte closed schema and privileged
  operator capability.
- Keep case, accepted-history, work, send-result, callback, SDK/browser and process
  facts source-qualified.
- Context revision 0 is read-only.
- Source time and revision do not make cross-authority reads atomic.

#### Client ownership and cleanup

- Own at most one actual browser client, including retiring epochs, with at most one
  context and one telemetry request.
- A waiter timeout or 1,000 ms close timeout never releases actual
  fetch/body-cancellation ownership.
- Forget clears private facts/token immediately, retains that owner, and blocks
  Connect until actual settlement.
- Explicit cleanup retry re-observes the same owner.
- Contain rendering callback failures so they cannot prevent cleanup or strand HTTP work.
- Invoke the captured native or injected fetch function without a client-object receiver.
- Keep the strict receiver regression and actual browser connection check.

#### Polling and paging

- Poll no faster than every two seconds for at most thirty ticks per activation or
  explicit Resume.
- Never queue a tick behind an active read.
- Older paging pauses polling, caps retained rows at thirty-two per section and
  preserves original IDs.
- Refresh current starts a new page window.
- Denial pauses every UI poll and labels retained facts/diagnostics historical.
- Process diagnostic permission alone cannot restore context access.
- Failed reads preserve labelled previous observations.

#### Controls, telemetry and accessibility

- No mutation, quote, retry-send, cancel, publish or consent control belongs here.
- Validate telemetry against the closed public source/status/cause schema.
- Do not replace distinct producer causes with raw exception text or invent numeric
  values.
- Use textContent, finite error categories, visible keyboard focus and reduced motion.
- Preserve the distinction between this bounded power-user surface and the planned
  compact portfolio demo. Long full-page evidence after paging is not proof that the
  final demo flow or video is finished.

### Joined showcase page (opt-in)

#### Page, proxy and grant URLs

- The optional channel-policy.html page has its own typed wire/client/controller,
  one lazy native room adapter and a compact panel.
- Preserve default pages.
- The fixed Vite proxy has no credential and forwards only to the local Parent API.
- Grant URLs are authenticated canonical `ws://127.0.0.1` with an explicit valid port.
- The trusted setup selects the host port, normally 17880.
- Never substitute the container's internal port or let browser input select the target.

#### Activation identity, End and Forget

- Parent activation epoch/generation/original Start identity is separate from the
  Node cursor.
- Retain original unknown Start/SMS commands, actual fetch/readers and media owners.
- End and Forget must fence late callbacks without adopting a late grant.
- End preserves the separate operator channel.
- Forget clears private facts and general authorization while already admitted
  scoped cleanup remains owned.
- The v1 adapter uses p2.interrupt and no optional response/playback authority.

#### HTTP owners and End retirement

- The joined client/controller retains at most three actual HTTP owners: at most two
  non-End operations and one reserved End operation, including body-reader cleanup.
- Capture one original-only retirement owner before Forget clears general authorization.
- The retirement owner may send the exact original End once and at most one automatic
  replay after original Start and first End actually settle.
- Later explicit Retry End re-observes the same scope and repairs retained
  original/ordinary readers.
- Repeated Forget coalesces.
- An exact closed acknowledgement is separate from actual request, reader and media
  settlement.
- Keep the next Join blocked until all are proved settled.
- Never adopt a late original grant after End.

#### Displayed observations

- Case and current-result timestamps are independent.
- P2 dispatch counts are not execution completion.
- Render real observations without timed progress animation.
- Keep provider/scripted labels explicit.

## Verification

From the repository root:

```sh
corepack pnpm --filter @livekit-ecosystem/local-console test
corepack pnpm --filter @livekit-ecosystem/local-console build
```

| Check | Command | When to run |
| --- | --- | --- |
| Console unit tests | `corepack pnpm --filter @livekit-ecosystem/local-console test` | Console changes |
| Console build | `corepack pnpm --filter @livekit-ecosystem/local-console build` | Console changes |
| Affected real local browser gate | Affected gate in [README.md](README.md), using the documented isolated orchestration helper | HTTP, RTC, microphone, playback, proxy or UI lifecycle changes |
| Root full fast validation lane | `HARNESS_PYTHON=.venv/bin/python sh scripts/harness-check.sh` | Shared contract or harness changes |
| Current-case storage (18 groups) and media (three groups) gates | `make p2-rehydration-check` and `make p2-rehydration-media-check`, run separately | Affected current-case context panel changes |
| Native RTC text source and installed gates | `make p3-native-policy-check` and `make p3-native-policy-package-check` | Changes to their HTTP, SDK or room lifetime |
| Operations build and actual gate | `make p2-operations-build`, `make p2-operations-plan` and `make p2-operations-check` | Affected operations read page changes |
| Fresh connected browser/RTC and screenshot checks | No single command | Changes to the actual joined lifecycle |

The table indexes these checks; the rules below it remain authoritative.

### All console changes

- Run the affected real local browser gate after HTTP, RTC, microphone, playback,
  proxy or UI lifecycle changes.
- Use the documented isolated orchestration helper for its token, audio fixture,
  seeded scope and PostgreSQL marker coordination.
- Mocked controller tests cannot establish actual WebRTC connectivity, audible output
  or native event-loop responsiveness during a database wait.
- Browser screenshots must first verify every password input is empty.
- Trace/video/HTTP Archive (HAR) remain disabled.
- Shared contract or harness changes require the root full fast validation lane.

### Isolated P2 native input page

- The selected actual six-group native and installed Python/npm package gates passed.
  Final selected phase checks and the affected UI-hint media rerun passed in the
  [completed handoff](../../docs/work-items/0036-native-input-and-deadline-cancellation.md).

### Response evidence view

- Open the visible Input references disclosure before entering a fixture reference
  in an actual browser gate.
- Preserve finite cached failure observations before browser/process teardown.
- Never retain raw Playwright messages or credential inputs.

### Current-case context panel

- Run the declared 18-group storage and three-group media gates separately after
  affected changes.
- I18 verified current-case rehydration passed its selected 18-group storage and
  three-group media gates in the
  [completed handoff](../../docs/work-items/0038-case-rehydration-and-standalone-release.md).
- Unit checks, generated text, SDK settlement, observed PCM and human acknowledgement
  have different meanings.

### Later selected slices

- Selected P2-I19 workload/dormancy and P3-I16 image evidence passed in 0039.
- The selected P2-I20 operations and standalone P3-I17 fixed-policy gates passed in
  [0040](../../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md).
- Selected P2-I21 and the P3-I18A durable prerequisite passed in
  [0041](../../docs/work-items/0041-standalone-channel-and-durable-policy.md).
- The opt-in native RTC text conversation and compact policy card passed selected
  source/installed qualification in
  [0042](../../docs/work-items/0042-responsive-native-policy-and-compact-demo.md).
- Both selected browser journeys passed their three groups.
- Integrated voice/SMS/showcase/video and full P2/P3 charter release remain pending.
- Repeat the native source/installed gates after changing their HTTP, SDK or room
  lifetime.

### Operations read page

- Run the separate operations build and declared actual gate after affected changes.
- Report unit, static visual and PostgreSQL/HTTP/browser assertions separately in the
  [completed 0040 handoff](../../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md).
- The selected pass covers forty UI tests and the actual sixteen PostgreSQL/HTTP and
  three browser groups.
- Evidence may retain bounded receipt/operation IDs and counts but no token or body.
- Assert empty passwords before screenshots, with trace/video/HAR disabled.

### Joined showcase page

- Fresh connected browser/RTC and screenshot checks remain required after changes to
  the actual joined lifecycle.

## Handoff

- Record accepted behavior, authority/failure boundaries, acceptance IDs, exact
  commands, observed results and evidence paths in the active work item.
- Distinguish unit/build results, real PostgreSQL state, native SDK observations and
  actual browser audio playback.
- Missing/skipped/timed-out checks remain non-passing.
- Update current capabilities and nearby docs together.
- Preserve honest personal contribution and AI-assistance statements for portfolio use.
