# Local continuity console

Status: Active
Last reviewed: 12 November 2026

## Overview

A strict TypeScript console demonstrates a synthetic durable P1 case alongside
native LiveKit AgentSession speech. Investigation permission, exact quote consent,
supplier outcome and receiver delivery remain separate observations. The native
voice path defaults to deterministic local fixtures. An explicit local_real profile
implements local Whisper/Qwen/Piper inference; engine/model/media qualification
remains pending and is separate from selecting the configured profile.
The selected provider_real v2 gate passed both actual browser cases with cleanup. P1 V1 is qualified for the local POC using provider_real v2.

The prerecorded input track is prepared and published silently. After the native
start_turn response is strictly verified as turn_started, a new non-looping source
plays the unchanged WAV from sample zero. Closed, muted, replaced, superseded or
not-ready input cannot be restarted by a late reply. Physical microphone capture
is independent; fixture alignment does not force a model tool or establish ASR quality.
Default integrated P2/P3 workspaces remain planned; the optional P2 native page
and selected P3 library/qualification paths are implemented.

## Implementation status

The managed case panel submits investigation-only requests, resumes an authenticated
task, displays persisted attempts and lifecycle state, prepares a supplier quote,
accepts explicit exact-quote consent and requests business cancellation. Read failures
preserve the last observed facts. Unknown admission or command acknowledgements
retain the original frozen key and payload for reconciliation.

The voice panel joins an already verified task through the native browser SDK,
offers explicit scripted-audio or physical-microphone input, supports manual input start/commit,
speech interruption, native text status, audio playback and same-task continuation through a fresh media room after End.
Automatic SDK transport reconnect and uncertain session-mint retries retain the
exact current room, participant and invocation. Explicit End or an established
native disconnect retires that media context; after actual cleanup, the next Join
creates a fresh room, participant and invocation while rehydrating the same durable
case. Controls wait for the selected native agent to report both an active SDK session
state and exact public `continuity.session_ready=true`, emitted only after actual
RoomIO subscription readiness, plus continuity.inference_mode matching the
authenticated scripted/local_real/provider_real mint mode. The badge is unconfigured before
mint, configured before native matching readiness, then native-profile-matched;
none of those labels alone proves model quality. Presence or Listening alone does not enable input
or status requests. A new native
consumer must return a fresh status reply.

The default input is a packaged local WAV decoded through WebAudio and published
as a real native WebRTC track after an explicit action. It accesses no microphone
and does not replace browser capture APIs. Physical microphone is a separate source
choice with real permission checks and bounded capture acknowledgements. Native
agent state, browser playback and business state are displayed separately.
Reliable task hints from the selected native agent trigger scoped HTTP reads;
the hint itself carries no authoritative business state or consent.

The retained transport diagnostics and independent M1 SQLite intake/replay/conflict
fixture remain available below the primary workflow. They are not the PostgreSQL
managed workflow. The shared operator token stays in page memory, clears from its
input on use and is forgotten explicitly or on page exit. Reload requires token
and task re-entry. No credentials or task identity are persisted in browser storage.

Controller/unit checks and production compilation qualify client boundaries.
Actual PostgreSQL, WebRTC playback and browser fault evidence are separate gates;
inspect the current phase work item before making portfolio claims. The fixed V1
scope is owned by the [portfolio scope](../../docs/portfolio-scope.md).

### Isolated P2 native input page

The optional p2-native.html page uses its separate vite.native.config.ts and
p2-native-build target. It is not the default M1/P1 console or an automatically
deployed Compose service. The selected actual six-group native and installed
Python/npm package gates passed; final selected phase checks and the affected UI-hint media
rerun passed in the [completed handoff](../../docs/work-items/0036-native-input-and-deadline-cancellation.md).

Durable input acceptance, native SDK generation and browser playback appear as
separate facts. Only reliable data from the selected native AGENT can update
six-key generation observations, and it must match known accepted input/operation.
Sixty-four generation identities and thirty-two retained inputs bound local state.
Known receipts survive stale notifications; a rejected retry cannot erase unknown
original acceptance. End closes owned media/I/O and does not business-cancel.
The profile is explicitly scripted and fixture-driven; positive microphone,
general ASR and live-model quality are not implied. I17 selected playback gates
passed in the [current handoff](../../docs/work-items/0037-playback-evidence-and-process-recovery.md);
I18 current-case room rehydration passed its selected storage and media gates in the
[completed handoff](../../docs/work-items/0038-case-rehydration-and-standalone-release.md).

### Verified current-case continuation

The opt-in continuity profile adds a read-only case/history panel to p2-native.html.
It uses the current verified native grant, or the exact accepted SMS and current
association, to restore separately observed current case facts and original channel
history. Retained account history alone is not current channel authorization.
Case revision and source fingerprint are separate: workflow or supplier facts can
advance at the same revision. Refresh is explicit and idle, with zero acceptance,
preparation or generation. Earlier responses remain inert source-qualified history,
never controls for the new room or proof of human acknowledgement.

The standalone native demo legitimately begins at revision 1; an accepted SMS CAS
advances it to 2. Public P1 revision 0 is readable but cannot enter the existing
positive-revision native dispatch contract. The profile does not map 0 to 1 or
revise a case automatically. Broader integrated continuation needs its own reviewed
contract; this limitation does not change P1's existing local POC qualification.

The controlled sequence closes actual A media/SDK resources, deletes the owned A
room, handles the fixed signed SMS while neither A nor B exists, then creates owned
B. B mint waits for that exact parent readiness marker. B loads verified context
before SDK readiness; a later genuine input receives a separate native reply.
Unknown mint retries preserve their original media identities. Input, current case,
SDK output, browser playback and supplier outcome remain separate facts.

After frozen setup, local services, restricted-role preparation and managed Chromium,
run from the repository root:

```sh
make p2-rehydration-check
make p2-rehydration-media-check
```

The selected 0038 eighteen-group storage gate passed in 6.534 seconds and the three-group media
gate passed in 35.797 seconds, with owned cleanup. The 0038 isolated Python consumer
passed 111 tests across nine payloads; 632 P2 TypeScript and 503 console unit tests
passed separately. Those unit/package checks retain their narrower scope; the
media gate establishes its actual room dormancy and scripted browser observations.
The [completed handoff](../../docs/work-items/0038-case-rehydration-and-standalone-release.md) records current results, failed attempts and limits.
No timer manufactures progress, and scripted PCM observation does not prove physical
microphone capture, general ASR or human hearing.

### Opt-in operations read view

The separate `p2-operations.html` page implements the P2-I20 read/error/telemetry
surface qualified in the selected local gates recorded in the
[completed 0040 handoff](../../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md).
It leaves the default P1/M1 page and native controls unchanged. The first authenticated
read pins the trusted native/account/case binding for that activation. Refresh current
loads a new as-of context; Load older reads bounded original history through signed,
section-specific cursors. A current case read and the P2 snapshot are not atomic.
Revision 0 remains read-only and is never mapped to revision 1.

Accepted input receipts, dispatch state, carrier send results, carrier callbacks,
generated text, SDK settlement and browser reports stay separate observations.
The process panel shows volatile producer counters and bounded read spans with
source and observation time; unavailable metrics remain unavailable. Neither
counter growth nor elapsed time establishes durable progress or human hearing.

Connect, Refresh current, Retry read, Load older, Pause/Resume updates and Forget
are the only controls. The password input clears on use. Forget immediately clears
facts and the credential while retaining any actual request owner; a new Connect
is blocked until actual cleanup settles. Context denial pauses all polling and
labels retained context and diagnostics historical. Process diagnostics have a
separate operator permission; they do not prove current case authorization.

From the repository root, after the pinned workspace setup:

```sh
make p2-operations-build
make p2-operations-plan
make p2-operations-check
```

The build compiles the public P2 browser-safe export and the separate operations
TypeScript profile. Its Vite configuration proxies only `/p2-operations/` to a
trusted literal loopback port (`P2_OPERATIONS_API_PORT`). No credential enters the
bundle, URL or browser storage. The default console build and Docker input remain
separate. The local check owns its restricted disposable state and actual browser;
the selected gate passed all sixteen PG/HTTP assertions and three browser groups
in one Playwright journey, with thirteen owned children and complete cleanup in
13.779 seconds. Forty policy/client/controller tests include the native-fetch
receiver and retained-owner regressions; static screenshots establish their
narrower visual scope. P2-I19 workload/dormancy qualification remains recorded in
the [0039 handoff](../../docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md).

This is a power-user read view. The qualified full-page captures after explicit
paging are 6,540 and 5,824 pixels high. A compact showcase with progressive
disclosure and the final demo video remain planned; this pass does not complete
the main portfolio user experience.

## Optional background conversation demo

The separate p3-background.html page implements the compact P3-I18B native text
surface. A conversation composer, connection strip and observed policy card share
one workspace; setup and diagnostics use disclosures. The application supplies one
trusted positive-revision request and two immutable JSON sources. The page does
not select a case, infer authority from model text or offer booking actions.

Join uses the fixed authenticated session route; observation uses a separate
operator bearer on a fixed same-origin GET. The server fixes all identities and
room grants. Credentials stay in memory, and the password input clears on use.
Exactly one room and one observation request are retained through actual cleanup.
End stops the local conversation; Forget also clears private display state and
fences late callbacks. Neither command cancels durable work.

The policy card distinguishes accepted/running work, original committed facts,
result disposition and separately read applicability. A failed read marks old
facts historical; Retry reads the original work. A result for an older case
revision remains visible as outdated. The page makes no atomic-snapshot, audio,
model-quality or human-acknowledgement claim.

From the repository root, with the pinned offline workspace dependencies:

```sh
make p3-native-policy-build
make p3-native-policy-plan
```

Run make p3-native-policy-check and make p3-native-policy-package-check for
the actual source and isolated installed gates. They require the ordinary local PostgreSQL
and SFU services plus managed Chromium, use fresh disposable state and scripted
inference, and never load .env.providers. Each owns its HTTP host and optional
page. The installed gate adds eight separate offline package assertions. The
[handoff](../../docs/work-items/0042-responsive-native-policy-and-compact-demo.md)
records twelve backend/SDK assertions and three browser groups passing in each
mode, with complete cleanup in 30.263 and 88.702 seconds respectively. Installed
mode passed eight separate package assertions. The source/installed browser gates
include held useful text, outdated result, read failure/retry, keyboard/reflow and
Forget. The card currently exposes execution/result metadata; richer historical
policy conclusions and rule/fact presentation follow with the combined showcase.
Voice, SMS result routing, provider quality and the final video remain separate.

## Documentation

Read [AGENTS.md](AGENTS.md), [Design.md](Design.md), the
[local setup guide](../../local-setup/README.md), [demo plan](../../docs/demo-plan.md)
and [validation plan](../../docs/validation-plan.md). Shared projection evidence is
under [business contracts](../../contracts/business/case-projection.json).

## Requirements

Use repository-pinned Node and pnpm versions. The console uses livekit-client
2.23.0 and Playwright 1.65.0; exact direct versions and resolution are maintained in
package.json and the root lockfile. Managed controls need the local control API,
PostgreSQL, fake supplier and worker. Voice additionally needs LiveKit and the
native business agent. Microphone access requires a secure/loopback browser origin,
permission and an explicit user action when the physical source is selected. The
default scripted source needs WebAudio support and its local packaged fixture.
Provider credentials are unnecessary for scripted/local_real. Optional provider_real
requires privately configured keys outside the console.

Local fonts and symbols retain their upstream licenses in public/vendor/livekit.
The visual system follows LiveKit references and labels this as an independent
project built with LiveKit.

## Commands

From the repository root after the documented dependency install:

```sh
corepack pnpm --filter @livekit-ecosystem/local-console test
corepack pnpm --filter @livekit-ecosystem/local-console build
corepack pnpm --filter @livekit-ecosystem/local-console dev
```

The development server uses port 3000 and proxies /api to the local API on port
18080. The production container serves port 8080 and proxies /api to control-api.
Use the [local setup guide](../../local-setup/README.md) for normal stack lifecycle,
readiness and isolated browser-gate orchestration.

The browser runner is `corepack pnpm --filter @livekit-ecosystem/local-console test:e2e`.
It requires an isolated seeded stack and E2E_BASE_URL, E2E_OPERATOR_TOKEN,
E2E_REPORT_DIR and E2E_COORDINATION_DIR from its orchestration helper.
Run make browser-setup from the repository root to install the Chromium build
selected by the pinned Playwright dependency. Both scripted and local-real browser
lanes use that managed build by default; the gate itself never installs a browser.
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH can explicitly select an existing browser binary. Never put the operator token in a command argument,
source file or retained report. The runner does not provision/reset the stack.

The dedicated local-real browser lane is separate from the retained scripted
regression lane. Its exact orchestration and prerequisites belong to the
[operations guide](../../docs/local-real-inference.md). Both use the prerecorded
WAV as the default explicit input source; neither implies physical microphone capture.

The third trusted profile, provider_real, displays Cloud providers
(Deepgram/OpenAI/ElevenLabs). Its three keys stay outside browser/API payloads and
storage. Input source remains independent: a prerecorded WAV never certifies
physical capture. The [provider guide](../../docs/provider-demo.md) owns opt-in
operations and the qualified provider_real v2 media evidence. A configured or matched badge
alone does not establish successful inference.

### Optional native/deadline checks

Run from the repository root after frozen dependency setup and the documented
local stack/restricted database-role preparation:

```sh
make p2-native-build
make p2-native-check
make p3-deadlines-check
```

The first command builds the P2 SDK, then the isolated p2-native.html entry to
dist-native. It starts no service and changes no default console entry. The second
owns the selected qualified host SDK/browser/gateway exercise against local Docker
LiveKit/PostgreSQL; the third is the qualified selected P3 temporal gate. Final
phase gates and the affected media rerun after the UI hint update passed.
Scripts use ordinary local setup, never provider credentials.
The [completed handoff](../../docs/work-items/0036-native-input-and-deadline-cancellation.md) owns exact evidence and prerequisites.

## Validation

Unit tests verify strict wire schemas, BIGINT decimal preservation, exact opaque
quote matching, unchanged command replay, unknown acknowledgements, bounded HTTP
and text reads, permission errors, lifecycle races and cleanup. The shared producer
fixture protects Python/browser compatibility. Build checks native SDK types.

The real browser gate uses the first-class local scripted input, actual local HTTP
and native WebRTC, checks audio
currentTime advancement, manual speech controls, reconnect identity, scoped reload,
permission denial, a positively observed native PostgreSQL wait, a held actual
supplier read with responsive native controls and explicit quote mutation. Its JSON observations contain only allowlisted booleans, counts and states.
Trace, video and HAR capture are disabled. Optional workspace images are captured
only after asserting all password fields are empty. Missing helper markers,
permissions, audio, skipped dependent cases or timeouts are non-passing evidence.

## Next milestone

The [completed Phase H handoff](../../docs/work-items/0019-p1-phase-h-release-qualification.md)
records current browser/fault/provider gates and sanitized evidence. Repeat the
affected gates after HTTP, RTC, readiness or cleanup changes using the declared
inputs and trusted profile. The [granular implementation plan](../../docs/implementation-plan.md)
records selected P2-I19 workload/dormancy and P3-I16 static-image qualification.
Selected P2-I20 operations and standalone P3-I17 fixed-policy gates passed in
[0040](../../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md). P2-I21 standalone qualification and P3-I18A durable-v2 qualification passed in
[0041](../../docs/work-items/0041-standalone-channel-and-durable-policy.md).
Selected P3-I18B native RTC text qualification passed in
[0042](../../docs/work-items/0042-responsive-native-policy-and-compact-demo.md).
The compact integrated showcase, comparison flow and video remain
planned, as does full charter registration. Keep this console a scoped
projection/conversation client; backend authorities own workflow execution and effects.

## Optional response playback showcase

Build the isolated page with make p2-native-build. The selected local gates are:

```sh
make p2-communication-check
make p2-playback-check
make p3-recovery-check
```

The playback helper owns a disposable room, local host SDK/gateway/browser and
explicit v7 schema against ordinary local Docker services. The page follows each
response through generated text, SDK output and client-reported playback. A measured
partial interruption retains the original input and full generated fact. Withheld
client reports leave playback unknown. Controls never supply business confirmation.
The [current handoff](../../docs/work-items/0037-playback-evidence-and-process-recovery.md)
records actual outcomes and prerequisites; provider or hardware qualification does
not follow from this scripted fixture.


## Joined channel-policy showcase

The optional channel-policy.html page is implemented as a compact conversation,
Voice/Text controls, one case/current-result card and a signed synthetic SMS
surface. Its components and disconnected responsive layout have focused tests;
actual joined database/RTC/provider validation and final recording remain pending.

Build with make channel-policy-ui-build and serve with make channel-policy-ui-dev.
The fixed local server uses 127.0.0.1:5179 and proxies only the joined API to
127.0.0.1:11033. These commands do not start the backend. The complete Parent
launcher is under integration. The page starts locked; enter the separate generated
operator credential explicitly. It remains in RAM and never enters a URL/build.

End closes the current media activation and preserves independent operator access
for dormant SMS and read-only observations. Forget clears that authorization and
private view facts. Current results, case revision/time, P2 dispatch counts, SDK
speech and media-element playback remain separate observations. The first mode
is labelled scripted with recorded WAV input; it does not establish general ASR,
real provider inference, hardware microphone capture or hearing.
