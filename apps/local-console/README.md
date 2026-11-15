# Local continuity console

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Describe each console page, the rules every page shares, and how to build, run and validate the pages |
| Audience | Engineers who run, test or change the browser console; coding agents |
| Scope | The default P1 console and the optional P2, P3 and joined showcase pages; excludes backend authorities and stack lifecycle |
| Owns | Console pages, implemented runtime behavior, commands and validation status |
| Related | [Design](Design.md) · [Agent instructions](AGENTS.md) · [Local setup guide](../../local-setup/README.md) · [Root README](../../README.md) |

## Overview

This README is for engineers who run, test or change the browser console in
`apps/local-console`. It lists the console's pages, states the rules that every
page shares and gives each page's commands and evidence. [Design.md](Design.md)
explains how the pages are built.

The console is a strict TypeScript browser client. Its default page shows a
synthetic durable P1 case beside native LiveKit AgentSession speech.
Investigation permission, exact quote consent, supplier outcome and receiver
delivery remain separate observations. Optional pages exercise P2 channel
continuity, P3 delegated policy work and the joined voice/SMS showcase.

Contents:

- [Implementation status](#implementation-status): tables of every page, with
  links to each page's section, and of capability status
- [Rules shared by every page](#rules-shared-by-every-page)
- One section per page, from
  [P1 business console and native voice](#p1-business-console-and-native-voice)
  to [Joined voice/SMS showcase](#joined-voicesms-showcase)
- [Documentation](#documentation), [Requirements](#requirements),
  [Commands](#commands), [Validation](#validation) and
  [Next milestone](#next-milestone)

## Implementation status

| Page | Path | Purpose | Status |
| --- | --- | --- | --- |
| [P1 business console and native voice](#p1-business-console-and-native-voice) | `index.html` | Managed P1 case, exact quote consent and native voice | Default page, served by the production console container |
| [P2 native input and response playback](#p2-native-input-and-response-playback) | `p2-native.html` | Durable native input, generated responses and playback evidence | Optional |
| [P2 current-case continuation](#p2-current-case-continuation) | Profile on `p2-native.html` | Read-only current case and original history in a fresh room | Optional |
| [P2 operations read view](#p2-operations-read-view) | `p2-operations.html` | Read-only context, history and process diagnostics | Optional |
| [P3 background conversation](#p3-background-conversation) | `p3-background.html` | Native text conversation beside one observed policy card | Optional |
| [Joined voice/SMS showcase](#joined-voicesms-showcase) | `channel-policy.html` and `landing.html` | Joined conversation, case/result card, synthetic SMS and a landing page | Optional |
| [Demo recorder](#demo-recorder) | `scripts/record-channel-policy-demo.mjs` | Drives the joined showcase UI for a recording | Recording tool, not a qualification gate |

| Capability | Status | Evidence |
| --- | --- | --- |
| P1 console with provider_real v2 | Qualified | Selected provider_real v2 gate passed both actual browser cases with cleanup; [provider guide](../../docs/provider-demo.md) |
| P1 console with local_real | Not qualified | Engine, model and media qualification pending; [local-real guide](../../docs/local-real-inference.md) |
| P2 native input and response playback | Qualified | Selected 0036 and 0037 gates passed; [0036](../../docs/work-items/0036-native-input-and-deadline-cancellation.md) · [0037](../../docs/work-items/0037-playback-evidence-and-process-recovery.md) |
| P2 current-case continuation | Qualified | Selected 0038 gates passed; [0038](../../docs/work-items/0038-case-rehydration-and-standalone-release.md) |
| P2 operations read view | Qualified | Selected 0040 gate passed; [0040](../../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md) |
| P3 background conversation | Qualified | Selected 0042 gates passed; [0042](../../docs/work-items/0042-responsive-native-policy-and-compact-demo.md) |
| Joined voice/SMS showcase | Implemented | Focused component and layout tests; joined qualification pending in [0045](../../docs/work-items/0045-joined-native-channel-policy.md) |
| Default integrated P2/P3 workspaces | Planned | Not applicable |

The optional P2 native page and selected P3 library and qualification paths
are implemented. The scripted profile's evidence is described under
[Inference profiles](#inference-profiles).

Controller and unit checks and production compilation qualify client
boundaries. Actual PostgreSQL, WebRTC playback and browser fault evidence are
separate gates. Inspect the current phase work item before making portfolio
claims. The [portfolio scope](../../docs/portfolio-scope.md) owns the fixed V1
project scope.

## Rules shared by every page

These rules hold on every page. The page sections below add only page-specific
behavior.

### Credentials stay in page memory

- Each page keeps its operator token or credential only in page memory. A
  password input clears as soon as it is used.
- No credential or task identity enters a build, URL or browser storage.
- Forget clears the credential. Each page section states what else Forget
  clears.

### Requests, readers and media stay bounded and owned

- Every page bounds response bytes, concurrent operations, retries and
  displayed history. [Design.md](Design.md#non-functional-requirements) lists
  the exact limits.
- A timed-out waiter, End or Forget does not release an actual request, stream
  reader or media resource. The page keeps ownership until the real operation
  settles. A new Join or Connect waits for that cleanup.
- After a lost acknowledgement, the page keeps the original frozen request
  identity and body and reconciles with them unchanged. It never invents a new
  identity.

### Observations are as-of facts

- Each fact comes from its own source at its own read time. Durable input
  acceptance, dispatch, generated text, software development kit (SDK) output,
  browser playback, case revision, supplier outcome and delivery stay separate
  observations.
- Reads from different authorities are not atomic.
- A failed read keeps the last observed facts and labels them unavailable or
  historical.
- Counters, elapsed time, speech state and media playback prove neither durable
  progress nor that a person heard anything. No timer manufactures progress.

### Conversation controls never change business state

- A model statement, speech state, playback event or agent hint never authorizes
  a mutation. No conversation control supplies business confirmation.
- End, Forget and speech interruption never cancel durable work.

### Inference profiles and input sources are separate claims

- Trusted server configuration selects the inference mode: scripted (the
  default), local_real or provider_real. The browser cannot request another.
- A configured or matched profile badge does not establish successful inference
  or model quality.
- Provider keys stay outside browser and API payloads and storage.
- The prerecorded WAV fixture is the default input. It never certifies physical
  microphone capture, general automatic speech recognition (ASR) or human
  hearing. The physical microphone is a separate source with real permission
  checks.

## P1 business console and native voice

The default page (`index.html`) holds a shared memory-only access bar, the
managed business workspace and native voice controls. Collapsed transport
diagnostics and an independent M1 fixture sit below the primary workflow. M1 is
the original confirmed-investigation intake.

### Managed business workspace

The managed case panel:

- submits investigation-only requests;
- resumes an authenticated task;
- displays persisted attempts and lifecycle state;
- prepares a supplier quote;
- accepts explicit consent to that exact quote; and
- requests business cancellation.

Read failures preserve the last observed facts. An unknown admission or command
acknowledgement keeps the original frozen key and payload for reconciliation.
Background polls and agent task hints use only the token already held in memory.
They never read or clear the token field. After a 401 or 403 rejection, the
panel forgets the token only after the failing command finishes, so a definitive
rejection stays definitive.
The panel stops polling once delivery is delivered or exhausted, or once a
failed lifecycle has no outcome, because no further server-side progress can
appear without a new command
([0047](../../docs/work-items/0047-open-findings-schema-upgrades-and-landing.md)).

### Native voice panel

The voice panel joins an already verified task through the native browser SDK.
It offers:

- explicit scripted-audio or physical-microphone input;
- manual input start and commit;
- speech interruption;
- native text status and audio playback; and
- same-task continuation through a fresh media room after End.

Native agent state, browser playback and business state are displayed
separately. Reliable task hints from the selected native agent trigger scoped
HTTP reads. A hint itself carries no authoritative business state or consent.

### Agent readiness gate

Voice controls stay disabled until the selected native agent reports all of the
following:

1. an active SDK session state;
2. the exact public attribute `continuity.session_ready=true`, which the agent
   emits only after actual RoomIO subscription readiness (RoomIO is the LiveKit
   Agents room input/output layer); and
3. a `continuity.inference_mode` value that matches the authenticated mint mode,
   which is the mode returned when the session grant is minted (scripted,
   local_real or provider_real).

Presence or Listening alone does not enable input or status requests. A new
native consumer must return a fresh status reply. The profile badge reads
unconfigured before mint, configured before native matching readiness, then
native-profile-matched. None of those labels alone proves model quality.

### Room identity across reconnects and End

- Automatic SDK transport reconnect and uncertain session-mint retries keep the
  exact current room, participant and invocation.
- Explicit End or an established native disconnect retires that media context.
- After actual cleanup, the next Join creates a fresh room, participant and
  invocation while rehydrating the same durable case.

### Scripted and microphone input

The default input is a packaged local WAV. The page decodes it through WebAudio
and, after an explicit action, publishes it as a real native WebRTC track. This
source accesses no microphone and does not replace browser capture APIs.

The prerecorded track is prepared and published silently. After the native
`start_turn` response is strictly verified as `turn_started`, a new non-looping
source plays the unchanged WAV from sample zero. A late reply cannot restart
input that is closed, muted, replaced, superseded or not ready. Fixture
alignment does not force a model tool or establish ASR quality.

The physical microphone is a separate source choice with real permission checks
and bounded capture acknowledgements. Physical microphone capture is independent
of the fixture.

### Inference profiles

| Profile | What runs | Qualification and evidence |
| --- | --- | --- |
| scripted (default) | Deterministic local fixtures | Exercised by the retained scripted regression lane |
| local_real | Explicitly selected local Whisper, Qwen and Piper inference | Engine, model and media qualification pending; selecting the configured profile is separate from qualification |
| provider_real | Deepgram, OpenAI and ElevenLabs cloud providers, displayed by the page | Selected provider_real v2 gate passed both actual browser cases with cleanup |

P1 V1 is qualified for the local proof of concept (POC) using provider_real v2.
[Local-real and provider-real lanes](#local-real-and-provider-real-lanes) links
each real profile's operations guide.

### Access, reload and retained diagnostics

- The shared operator token is forgotten explicitly or on page exit. Reload
  requires token and task re-entry. No credentials or task identity are
  persisted in browser storage.
- The retained transport diagnostics and the independent M1 SQLite intake,
  replay and conflict fixture remain available below the primary workflow.
  Neither is the PostgreSQL managed workflow.

## P2 native input and response playback

`p2-native.html` is an optional page with its own `vite.native.config.ts` and
`p2-native-build` target. It is neither the default M1/P1 console nor an
automatically deployed Compose service. The profile is explicitly scripted and
fixture-driven, so positive microphone, general ASR and live-model quality are
not implied.

### Durable native input

- Durable input acceptance, native SDK generation and browser playback appear as
  separate facts.
- Only reliable data from the selected native agent (a participant of kind
  AGENT) can update the six-key generation observations. The data must match a
  known accepted input and operation.
- Sixty-four generation identities and thirty-two retained inputs bound local
  state.
- Known receipts survive stale notifications. A rejected retry cannot erase an
  unknown original acceptance.
- End closes owned media and I/O. It does not cancel business work.

### Response playback evidence

The opt-in v7 communication profile (P2 schema version 7) follows each
response through generated text, SDK output and client-reported playback.

- A measured partial interruption retains the original input and the full
  generated fact.
- Withheld client reports leave playback unknown.
- Controls never supply business confirmation.
- Provider or hardware qualification does not follow from this scripted
  fixture.

### Native input and playback gates

Run from the repository root after frozen dependency setup and the documented
local stack and restricted database-role preparation:

```sh
make p2-native-build
make p2-native-check
make p3-deadlines-check
```

The playback phase uses the same page, built with `make p2-native-build`. Its
selected local gates are:

```sh
make p2-communication-check
make p2-playback-check
make p3-recovery-check
```

| Task | Command | Notes |
| --- | --- | --- |
| Build the native page | `make p2-native-build` | Builds the P2 SDK, then the isolated `p2-native.html` entry into `dist-native`; starts no service and changes no default console entry |
| Run the native input gate | `make p2-native-check` | Owns the selected, qualified host SDK, browser and gateway exercise against local Docker LiveKit and PostgreSQL |
| Run the P3 temporal gate | `make p3-deadlines-check` | The qualified selected P3 temporal gate |
| Run the communication gate | `make p2-communication-check` | Selected local gate of the playback phase |
| Run the playback gate | `make p2-playback-check` | Selected local gate of the playback phase |
| Run the P3 recovery gate | `make p3-recovery-check` | Selected local gate of the playback phase |

The three native input and deadline scripts use ordinary local setup, never
provider credentials. The playback helper owns a disposable room, the local host
SDK, gateway and browser, and the explicit v7 schema, all against ordinary local
Docker services.

### Native input and playback evidence

| Selected check | Result | Record |
| --- | --- | --- |
| Native input and deadlines | The selected actual six-group native gate and the installed Python/npm package gates passed | The [completed 0036 handoff](../../docs/work-items/0036-native-input-and-deadline-cancellation.md) owns exact evidence and prerequisites |
| Response playback (P2-I17) | The selected playback gates passed | The [0037 handoff](../../docs/work-items/0037-playback-evidence-and-process-recovery.md) records actual outcomes and prerequisites |

For native input and deadlines, the final selected phase checks and the affected
media rerun after the UI hint update also passed.

## P2 current-case continuation

The opt-in continuity profile adds a read-only case and history panel to
`p2-native.html`. It restores a case in a fresh room after the earlier room has
closed.

### What the panel restores

- The panel uses the current verified native grant, or the exact accepted SMS
  and current association, to restore separately observed current case facts and
  the original channel history.
- Retained account history alone is not current channel authorization.
- Case revision and source fingerprint are separate. Workflow or supplier facts
  can advance at the same revision.
- Refresh is explicit and idle. It performs zero acceptance, preparation or
  generation.
- Earlier responses remain inert, source-qualified history. They never become
  controls for the new room or proof of human acknowledgement.
- The `actualReads` value in the page's rehydration evidence counts only context
  reads that are in progress. Response refreshes do not change it.

### Revision 0 stays read-only

- The standalone native demo legitimately begins at revision 1. An accepted SMS
  compare-and-set (CAS) advances it to 2.
- Public P1 revision 0 is readable but cannot enter the existing
  positive-revision native dispatch contract. The profile does not map 0 to 1 or
  revise a case automatically.
- Broader integrated continuation needs its own reviewed contract. This
  limitation does not change P1's existing local POC qualification.

### Room A, then SMS, then room B

The controlled sequence runs in this order:

1. Close the actual media and SDK resources of room A.
2. Delete the owned room A.
3. Handle the fixed signed SMS while neither room A nor room B exists.
4. Create the owned room B. Minting B's session waits for the exact readiness
   marker that the parent publishes for B.
5. Load verified context into B before SDK readiness. A later genuine input then
   receives a separate native reply.

Unknown mint retries preserve their original media identities. Input, current
case, SDK output, browser playback and supplier outcome remain separate facts.

### Continuation gates and evidence

After frozen setup, local services, restricted-role preparation and managed
Chromium, run from the repository root:

```sh
make p2-rehydration-check
make p2-rehydration-media-check
```

| Task | Command | Notes |
| --- | --- | --- |
| Run the storage gate | `make p2-rehydration-check` | The eighteen-group storage gate against real PostgreSQL |
| Run the media gate | `make p2-rehydration-media-check` | The three-group media gate: room A, signed SMS, then a fresh room B |

| Selected 0038 check | Result |
| --- | --- |
| Eighteen-group storage gate | Passed in 6.534 seconds, with owned cleanup |
| Three-group media gate | Passed in 35.797 seconds, with owned cleanup |
| Isolated Python consumer | 111 tests across nine payloads passed |
| Unit tests, run separately | 632 P2 TypeScript and 503 console unit tests passed |

P2-I18 current-case room rehydration passed these selected storage and media
gates. The unit and package checks keep their narrower scope. The media gate
establishes its actual room dormancy and scripted browser observations. The
[completed 0038 handoff](../../docs/work-items/0038-case-rehydration-and-standalone-release.md)
records current results, failed attempts and limits. Scripted pulse-code
modulation (PCM) observation does not prove physical microphone capture, general
ASR or human hearing.

## P2 operations read view

`p2-operations.html` implements the P2-I20 read, error and telemetry surface. It
is a power-user read view. It leaves the default P1/M1 page and native controls
unchanged.

### Binding and reads

- The first authenticated read pins the trusted native, account and case binding
  for that activation.
- Refresh current loads a new as-of context. Load older reads bounded original
  history through signed, section-specific cursors.
- A current case read and the P2 snapshot are not atomic.
- Revision 0 remains read-only and is never mapped to revision 1.

### What the view shows

- Accepted input receipts, dispatch state, carrier send results, carrier
  callbacks, generated text, SDK settlement and browser reports stay separate
  observations.
- The process panel shows volatile producer counters and bounded read spans with
  their source and observation time. Unavailable metrics remain unavailable.
- Neither counter growth nor elapsed time establishes durable progress or human
  hearing.

### Controls and access

The only controls are Connect, Refresh current, Retry read, Load older,
Pause/Resume updates and Forget.

- Forget immediately clears facts and the credential but keeps any actual
  request owner. A new Connect is blocked until actual cleanup settles.
- Context denial pauses all polling and labels retained context and diagnostics
  historical.
- Process diagnostics need a separate operator permission. They do not prove
  current case authorization.

### Operations build and gate

From the repository root, after the pinned workspace setup:

```sh
make p2-operations-build
make p2-operations-plan
make p2-operations-check
```

| Task | Command | Notes |
| --- | --- | --- |
| Build the operations page | `make p2-operations-build` | Compiles the public P2 browser-safe export and the separate operations TypeScript profile |
| Plan the operations gate | `make p2-operations-plan` | Runs the gate script in plan mode |
| Run the operations gate | `make p2-operations-check` | Owns its restricted disposable state and actual browser |

- The build's Vite configuration proxies only `/p2-operations/` to a trusted
  literal loopback port (`P2_OPERATIONS_API_PORT`).
- The default console build and Docker input remain separate.

### Operations evidence

The [completed 0040 handoff](../../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md)
records the selected local gates:

| Selected 0040 check | Result |
| --- | --- |
| Actual gate | All sixteen PostgreSQL/HTTP assertions and three browser groups passed in one Playwright journey, with thirteen owned children and complete cleanup in 13.779 seconds |
| Policy, client and controller tests | Forty tests, including the native-fetch receiver and retained-owner regressions |
| Static screenshots | Establish only their narrower visual scope |
| Qualified full-page captures after explicit paging | 6,540 and 5,824 pixels high |

P2-I19 workload and dormancy qualification remains recorded in the
[0039 handoff](../../docs/work-items/0039-bounded-channel-workloads-and-image-evidence.md).

This read view is separate from the compact showcase with progressive
disclosure and from the demo video, which
[Joined voice/SMS showcase](#joined-voicesms-showcase) describes. This pass does
not complete the main portfolio user experience.

## P3 background conversation

`p3-background.html` implements the compact P3-I18B native text surface. It is a
native real-time communication (RTC) text profile with no audio controls.

### Layout and scope

- A conversation composer, a connection strip and an observed policy card share
  one workspace. Setup and diagnostics use disclosures.
- The application supplies one trusted positive-revision request and two
  immutable JSON sources.
- The page does not select a case, infer authority from model text or offer
  booking actions.

### Session and lifecycle

- Join uses the fixed authenticated session route. Observation uses a separate
  operator bearer on a fixed same-origin GET.
- The server fixes all identities and room grants.
- Exactly one room and one observation request are retained through actual
  cleanup.
- End stops the local conversation. Forget also clears private display state and
  fences late callbacks. Neither command cancels durable work.

### Policy card

- The card distinguishes accepted or running work, original committed facts,
  result disposition and separately read applicability.
- A failed read marks old facts historical. Retry reads the original work.
- A result for an older case revision remains visible as outdated.
- The page makes no atomic-snapshot, audio, model-quality or
  human-acknowledgement claim.
- The card currently exposes execution and result metadata. Richer historical
  policy conclusions and rule/fact presentation follow with the combined
  showcase.

### Background conversation build and gates

From the repository root, with the pinned offline workspace dependencies:

```sh
make p3-native-policy-build
make p3-native-policy-plan
```

| Task | Command | Notes |
| --- | --- | --- |
| Build the background page | `make p3-native-policy-build` | Offline, with the pinned workspace dependencies |
| Plan the background gates | `make p3-native-policy-plan` | Offline; runs the gate script in plan mode |
| Run the actual source gate | `make p3-native-policy-check` | Needs local services and managed Chromium, as listed below |
| Run the isolated installed gate | `make p3-native-policy-package-check` | Same prerequisites as the source gate |

Run `make p3-native-policy-check` and `make p3-native-policy-package-check` for
the actual source and isolated installed gates. Both gates:

- require the ordinary local PostgreSQL and selective forwarding unit (SFU)
  services plus managed Chromium;
- use fresh disposable state and scripted inference;
- never load `.env.providers`; and
- own their HTTP host and optional page.

### Background conversation evidence

The [0042 handoff](../../docs/work-items/0042-responsive-native-policy-and-compact-demo.md)
records these passing results:

| Mode | Backend/SDK assertions | Browser groups | Additional assertions | Complete cleanup in |
| --- | --- | --- | --- | --- |
| Source | Twelve | Three | None | 30.263 seconds |
| Installed | Twelve | Three | Eight separate offline package assertions | 88.702 seconds |

The source and installed browser gates include held useful text, outdated
result, read failure and retry, keyboard and reflow, and Forget. Voice, SMS
result routing, provider quality and the final video remain separate.

## Joined voice/SMS showcase

`channel-policy.html` is an optional page implemented as a compact
conversation, Voice/Text controls, one case/current-result card and a signed
synthetic SMS surface. A separate `landing.html` page links to both the
showcase and the P1 console.

### Showcase status

Its components and disconnected responsive layout have focused tests. These
isolated checks do not establish a joined database, RTC or real-provider
journey. The active
[0045 work item](../../docs/work-items/0045-joined-native-channel-policy.md)
owns that qualification, which remains pending.
[0046](../../docs/work-items/0046-joined-showcase-providers-and-demo.md)
records three selected provider-mode journeys and the 80-second showcase
recording, and
[0047](../../docs/work-items/0047-open-findings-schema-upgrades-and-landing.md)
records the complete demo recording. Neither replaces the 0045 qualification
gates.

### Build, serve and launch

| Task | Command | Notes |
| --- | --- | --- |
| Build the showcase | `make channel-policy-ui-build` | Builds the showcase and landing pages |
| Serve the showcase | `make channel-policy-ui-dev` | Fixed local server on 127.0.0.1:5179; proxies only the joined API to 127.0.0.1:11033 |

These commands do not start the backend. The joined launcher and its prepared
profiles are documented in the [root README](../../README.md) and the
[local setup guide](../../local-setup/README.md).

### Access and lifecycle

- The page starts locked. Enter the separately generated operator credential
  explicitly.
- End closes the current media activation. It preserves independent operator
  access for dormant SMS (sent while no room is open) and read-only
  observations.
- Forget clears that authorization and the private view facts.
- Current results, case revision and time, P2 dispatch counts, SDK speech and
  media-element playback remain separate observations.

### Text input and retry

- A typed message keeps one frozen text input id until that input is accepted,
  replayed or rejected.
- While the original input is pending or unknown, edited text is refused.
- Enter sends only while Send is enabled and ignores key repeat.
- Retry resends the original unknown input and adds no duplicate conversation
  entry.

### Inference mode and voice source

The first mode is labelled scripted with recorded WAV input. It does not
establish general ASR, real provider inference, hardware microphone capture or
hearing. The trusted grant can instead name provider_real. The
[joined showcase design](Design.md#joined-voicesms-showcase) describes its
readiness check and the microphone source.

### Landing page

`landing.html` is served at the showcase origin root (http://127.0.0.1:5179/).
It links the joined showcase and the P1 console. The console's loopback URL is
injected at build time from the configured UI port and validated before use.

### Demo recorder

`scripts/record-channel-policy-demo.mjs` drives the same showcase UI. With
`--complete`, it opens the landing page first and finishes with one P1 business
case in the console. Its captions and title cards exist only in the recording.
The console token is entered while a title card covers the page. The
[root README](../../README.md) documents the `make channel-policy-demo-record`
and `make ecosystem-demo-record` commands.

## Documentation

| Document | Purpose |
| --- | --- |
| [AGENTS.md](AGENTS.md) | Coding rules for this directory |
| [Design.md](Design.md) | Component design, limits and failure handling for every page |
| [Local setup guide](../../local-setup/README.md) | Stack lifecycle, readiness and isolated browser-gate orchestration |
| [Demo plan](../../docs/demo-plan.md) | Capability demonstrations and honest observable UI transitions |
| [Validation plan](../../docs/validation-plan.md) | Test lanes, required fault scenarios, benchmarks and evidence |
| [Local-real operations guide](../../docs/local-real-inference.md) | The local_real inference profile |
| [Provider guide](../../docs/provider-demo.md) | The provider_real inference profile |
| [Business contracts](../../contracts/business/case-projection.json) | Shared projection evidence |

## Requirements

| Requirement | Version or value | Notes |
| --- | --- | --- |
| Node and pnpm | Repository-pinned versions | Pinned in the root `package.json` |
| livekit-client | 2.23.0 | `package.json` and the root lockfile maintain the exact direct versions and resolution |
| Playwright | 1.65.0 | `package.json` and the root lockfile maintain the exact direct versions and resolution |
| Managed controls | Local control API, PostgreSQL, the fake supplier and the worker | Needed by the business workspace |
| Voice | LiveKit and the native business agent | Needed in addition to the managed-control services |
| Default scripted source | WebAudio support and its local packaged fixture | Default voice input |
| Physical microphone source | Secure or loopback browser origin, permission and an explicit user action | Only when the physical source is selected |
| Provider credentials | None for scripted and local_real | Optional provider_real requires privately configured keys outside the console |

Local fonts and symbols in `public/vendor/livekit` retain their upstream
licenses. The visual system follows LiveKit references and labels this as an
independent project built with LiveKit.

## Commands

Run every command from the repository root after the documented dependency
install.

| Task | Command | Notes |
| --- | --- | --- |
| Run the unit tests | `corepack pnpm --filter @livekit-ecosystem/local-console test` | Controller and unit checks |
| Build the console | `corepack pnpm --filter @livekit-ecosystem/local-console build` | Production compilation |
| Start the development server | `corepack pnpm --filter @livekit-ecosystem/local-console dev` | Port 3000; proxies `/api` to the local API on port 18080 |
| Install the managed Chromium | `make browser-setup` | Installs the Chromium build selected by the pinned Playwright dependency |
| Run the real browser gate | `corepack pnpm --filter @livekit-ecosystem/local-console test:e2e` | Needs an isolated seeded stack and its orchestration helper |

### Unit tests, build and development server

```sh
corepack pnpm --filter @livekit-ecosystem/local-console test
corepack pnpm --filter @livekit-ecosystem/local-console build
corepack pnpm --filter @livekit-ecosystem/local-console dev
```

| Server | Port | `/api` proxy target |
| --- | --- | --- |
| Development server | 3000 | Local API on port 18080 |
| Production container | 8080 | `control-api` |

Use the [local setup guide](../../local-setup/README.md) for normal stack
lifecycle, readiness and isolated browser-gate orchestration.

### Real browser gate

The browser runner is
`corepack pnpm --filter @livekit-ecosystem/local-console test:e2e`.

| Option | Default | Allowed values | Description |
| --- | --- | --- | --- |
| `E2E_BASE_URL`, `E2E_OPERATOR_TOKEN`, `E2E_REPORT_DIR` and `E2E_COORDINATION_DIR` | None | Values from the orchestration helper | Required by the runner |
| `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` | Unset, so the managed Chromium build is used | An existing browser binary | Explicitly selects that binary |

- The runner requires an isolated seeded stack. It does not provision or reset
  the stack.
- Run `make browser-setup` from the repository root to install the Chromium
  build selected by the pinned Playwright dependency. Both scripted and
  local-real browser lanes use that managed build by default. The gate itself
  never installs a browser.
- Never put the operator token in a command argument, source file or retained
  report.

### Local-real and provider-real lanes

- The dedicated local-real browser lane is separate from the retained scripted
  regression lane. Its exact orchestration and prerequisites belong to the
  [operations guide](../../docs/local-real-inference.md).
- Both lanes use the prerecorded WAV as the default explicit input source.
  Neither implies physical microphone capture.
- For the third trusted profile, provider_real, the
  [provider guide](../../docs/provider-demo.md) owns opt-in operations and the
  qualified provider_real v2 media evidence. Its three keys stay outside the
  console, as the shared rules state.

### Commands for the optional pages

Each optional page section holds its own commands and prerequisites:

| Page | Commands and prerequisites |
| --- | --- |
| P2 native input and response playback | [P2 native input and playback gates](#native-input-and-playback-gates), which also list the P3 deadline and recovery gates from the same phases |
| P2 current-case continuation | [P2 continuation gates](#continuation-gates-and-evidence) |
| P2 operations read view | [P2 operations build and gate](#operations-build-and-gate) |
| P3 background conversation | [P3 background conversation build and gates](#background-conversation-build-and-gates) |
| Joined voice/SMS showcase | [Joined showcase build and serve](#build-serve-and-launch) |

## Validation

| Check | Command | What it proves | Status |
| --- | --- | --- | --- |
| Unit tests | `corepack pnpm --filter @livekit-ecosystem/local-console test` | Client schemas, quote bytes, replay, acknowledgements, bounded reads, permissions, races and cleanup | Implemented; 503 console unit tests passed in the 0038 run |
| Shared producer fixture | Runs with the unit tests | Python/browser compatibility | Implemented |
| Production build | `corepack pnpm --filter @livekit-ecosystem/local-console build` | Native SDK types | Implemented |
| Real browser gate | `corepack pnpm --filter @livekit-ecosystem/local-console test:e2e` | Scripted input over actual local HTTP and native WebRTC | Current result recorded in the [Phase H handoff](../../docs/work-items/0019-p1-phase-h-release-qualification.md) |
| Optional page gates | Listed in each page section | Each page's selected behavior | Recorded in each page section |

### Unit and build checks

Unit tests verify:

- strict wire schemas and BIGINT decimal preservation;
- exact opaque quote matching and unchanged command replay;
- unknown acknowledgements;
- bounded HTTP and text reads; and
- permission errors, lifecycle races and cleanup.

The shared producer fixture protects Python/browser compatibility. The build
checks native SDK types.

### Real browser gate coverage

The real browser gate uses the first-class local scripted input, actual local
HTTP and native WebRTC. It checks:

- audio `currentTime` advancement;
- manual speech controls;
- reconnect identity;
- scoped reload;
- permission denial;
- a positively observed native PostgreSQL wait;
- a held actual supplier read with responsive native controls; and
- explicit quote mutation.

Evidence rules:

- Its JSON observations contain only allowlisted booleans, counts and states.
- Trace, video and HTTP Archive (HAR) capture are disabled.
- Optional workspace images are captured only after asserting that all password
  fields are empty.
- Missing helper markers, permissions, audio, skipped dependent cases or
  timeouts are non-passing evidence.

Each optional page section lists its own selected gates and results.

## Next milestone

The [completed Phase H handoff](../../docs/work-items/0019-p1-phase-h-release-qualification.md)
records current browser, fault and provider gates and sanitized evidence.

Later selected qualifications are recorded as follows:

| Capability | Status | Evidence |
| --- | --- | --- |
| P2-I19 workload/dormancy and P3-I16 static-image | Qualified | [Granular implementation plan](../../docs/implementation-plan.md) |
| P2-I20 operations and standalone P3-I17 fixed-policy gates | Qualified | [0040](../../docs/work-items/0040-operations-ui-and-fixed-policy-evidence.md) |
| P2-I21 standalone and P3-I18A durable-v2 | Qualified | [0041](../../docs/work-items/0041-standalone-channel-and-durable-policy.md) |
| P3-I18B native RTC text | Qualified | [0042](../../docs/work-items/0042-responsive-native-policy-and-compact-demo.md) |

| Step | Outcome | Gate |
| --- | --- | --- |
| Repeat the affected gates after HTTP, RTC, readiness or cleanup changes | Fresh evidence using the declared inputs and trusted profile | The affected gates recorded in the Phase H handoff |
| Qualify the joined showcase | A joined database, RTC and real-provider journey for the implemented showcase | [0045](../../docs/work-items/0045-joined-native-channel-policy.md) qualification, which remains pending |
| Build the comparison flow | Remains planned | No gate named in this README |
| Complete full charter registration | Remains planned | The owning project charters |

Keep this console a scoped projection and conversation client. Backend
authorities own workflow execution and effects.
