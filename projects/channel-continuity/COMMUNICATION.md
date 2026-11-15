# Source-qualified communication contract

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Define the opt-in I17 communication profile that keeps generated, SDK and browser response facts separate |
| Audience | Engineers who enable or change the P2 communication profile; coding agents |
| Scope | Inbox schema version 7, the `./communication` export and the Python native communication adapter; excludes complete charter acceptance |
| Owns | Communication API, HTTP routes, storage caps, streaming bounds, projection meaning and verification layers |
| Related | [Project guide](README.md) · [Project design](Design.md) · [V1 charter](../../docs/projects/channel-continuity-scope.md) · [I17 handoff](../../docs/work-items/0037-playback-evidence-and-process-recovery.md) · [Rehydration contract](REHYDRATION.md) |

## Overview

This contract describes the opt-in I17 communication profile (task P2-I17, inbox
schema version 7). Read it before enabling version 7.

The profile preserves durable generated, software development kit (SDK) and
browser response facts. It never combines them into a claim that a person heard a
response.

| Capability | Status | Evidence |
| --- | --- | --- |
| I17 response and playback evidence | Qualified | [I17 handoff](../../docs/work-items/0037-playback-evidence-and-process-recovery.md) |
| I18 current-case room rehydration | Qualified | [I18 handoff](../../docs/work-items/0038-case-rehydration-and-standalone-release.md) |
| Complete P2 charter acceptance | Planned | [V1 charter](../../docs/projects/channel-continuity-scope.md) |

- The I17 phase handoff records qualification, commands and exact evidence.
- I18 current-case room rehydration separately passed its selected storage/media
  and installed-consumer gates, as recorded in its completed handoff.
- The [project design](Design.md) owns architecture and tradeoffs. The charter owns
  complete acceptance requirements.
- P2-I19/I20 and full release retain their own requirements.

## Trusted construction and public API

### Construction and credentials

Import server APIs from `@livekit-ecosystem/channel-continuity/communication`,
which provides `CommunicationInbox` and `CommunicationGateway`.

- `createCommunicationIntegration(native, grants)` requires the opaque native
  integration and trusted finite scope/case/conversation grants.
- Supply distinct publisher, SDK and browser credentials, separate from account and
  native credentials.
- The SDK never accepts a caller-created principal or a payload source label as
  authentication.

### Capabilities

| API | Credential | Capability | Result |
| --- | --- | --- | --- |
| `beginResponse` | Publisher | Binds immutable response, generation, SDK speech, binding, accepted input receipt/operation and case revision | The original response receipt |
| `observeSdk` | SDK | Appends an actual `generated_complete` or `speech_settled` fact | An immutable observation receipt |
| `observeBrowser` | Browser | Appends a client started, partial, interrupted or completed report with `observedAudioMs` | An immutable observation receipt |
| `inspectResponse` | Account | Reads one original response | The exact original anchor and receipt and the coherent generated/SDK/browser projection |
| `responses` | Account | Pages responses in descending order | An account-scoped page of 1–32 responses, with the original scoped response sequence |
| `observations` | Account | Pages observations after a response-local observation sequence | A page of 1–8 observations of the original response |

### Loopback HTTP gateway

The loopback HTTP gateway exposes four explicit POST routes under `/v1/native/`:
`responses`, `sdk-observations`, `browser-observations` and `response-inspect`.

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Request | 32768 bytes | Each request | Canonical UTF-8 JSON |
| Write receipt | 2048 bytes | Each write response | None |
| Read view | 65536 bytes | Each read response | None |

- The credential determines the role.
- Responses require explicit `Connection: close`.
- An invalid response after a possible write remains unknown. There is no
  automatic retry.
- The application owns all listeners and clients separately.

## Storage, lifetime and recovery

### Owner upgrade to version 7

Run owner `upgradeChannelSchemaV7` explicitly after v6, with service writers
quiescent. Three additive tables retain profile settings, response anchors and
source/event observations.

- Serving performs no data definition language (DDL) or cleanup.
- Original canonical rows and receipts remain unchanged.
- An interrupted upgrade rolls back before a fresh owner upgrade.
- Populated backup/restore uses the actual local PostgreSQL tools.

### Admission, expiry and sequences

- One original admission lock guards cap counters and new rows.
- A new response requires the current original binding and fresh database time
  after locks.
- Original retained facts and replays remain valid after expiry or revocation. This
  permits historical observation without renewing a room or starting preparation.
- Response sequence is scoped to tenant, account and conversation. Observation
  sequence is local to the original response. Global counts remain profile-cap
  metadata.

### Capacity

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Responses | 1024 (default) | Profile | Supported maximum 10000 |
| Observations | 8192 (default) | Profile | Supported maximum 100000 |
| Observations per response | 16 (default) | Each response | Supported maximum 64 |

- New identities fail before growth at capacity. Equal original replay retains its
  receipt.
- There is no physical pruning, time to live (TTL), identity reuse or
  replay-horizon erasure in this profile.

## Streaming native adapter

### Python modules

The pure `channel_continuity.native_communication` module supplies immutable typed
models, a port and a bounded loopback client, `NativeCommunicationHttpClient`. The
optional pinned `[native]` adapter uses public SDK nodes and the exact public
returned `SpeechHandle`.

### Context capture and node ownership

- An application `ContextVar` is captured around synchronous `generate_reply` and
  propagates into SDK-created tasks.
- The large language model (LLM) and text-to-speech (TTS) nodes record ownership at
  the synchronous node call. Missing or retired contexts fail closed.
- The adapter never borrows `session.current_speech` or private SDK fields.

### Stream bounds

A bounded collector forwards source chunks immediately through a queue of 2. It
preserves flush boundaries and backpressure.

| Limit | Value | Applies to | Notes |
| --- | --- | --- | --- |
| Queue | 2 chunks | Source collector | Forwards immediately |
| Retained generated text | 4096 UTF-8 bytes and 256 chunks | Each response | None |
| TTS calls | 16 | Each response | None |
| Actual SDK node tasks | 8 | Each response | None |
| Response identities in session metadata | 64 | Session metadata | None |

Full generated text requires normal actual LLM exhaustion, source closure and known
durable publication. A prefix, error or overflow is incomplete.

### Settlement and interruption

- `SpeechHandle.done` can precede actual provider cancellation or drain. Actual
  node, producer and publication ownership survives it. A cancellation-ignoring
  source holds capacity until real settlement.
- SDK terminal text is actual settled chat item text, never expected fixture output
  or the generated-text substitute.
- A clean, complete scripted read-only preparation interrupted during output can
  preserve its known decision. Playback does not trigger automatic regeneration.
- Source or SDK failure remains unknown and cannot create a known preparation.

### Topics and endpoints

| Topic or endpoint | Meaning |
| --- | --- |
| Native metrics and `p2.generation` | The original eighteen native metrics and the six-key `p2.generation` topic remain compatible |
| `p2.response` | A separate mapping that carries response, generation and speech identity without text |
| `p2.playback` | Authenticated reports of the original response |
| `p2.interrupt_response` | Requests interruption only on its captured handle; a request is not proof that output stopped |
| `/p2/response` | The application's read-only endpoint, which uses its separate operator bearer |

## Projection and UI meaning

### Independent facts

Generated text, SDK state/text and browser state are independent fields. The
commutative reducer retains contradictory evidence. Arrival or provider time never
selects a winner.

- SDK completed plus no browser completion remains browser unknown.
- A browser completed state is displayed as `completed_reported`.
- Neither state is human acknowledgement, exact quote consent, a supplier effect or
  business completion.

### Browser playback reports

- The local page measures actual browser pulse-code modulation (PCM) frames for its
  client report.
- Normal playback requires explicit completion reporting.
- Interrupted playback records a partial observation separately from SDK
  interrupted settlement.
- Withheld reports and disconnect leave durable browser state unknown. Later useful
  input still progresses.
- A delayed original response cannot interrupt or relabel a new response.

## Cross-room historical reads

The separate [rehydration contract](REHYDRATION.md) can include compact original
response and speech references and generated/SDK/browser source summaries. It does
not include full output text or enroll historical responses as new-room controls.

- Reading context creates no communication observation, playback claim, human
  acknowledgement or mutation consent.
- The source response and observation receipts and all existing evidence remain
  unchanged.
- Byte-limited pages omit whole records.

## Observability

- Store counters report committed anchors, facts and replay, and admitted SQL
  failures. Authentication and shape failures before SQL are outside that counter
  population.
- SQL failure, unknown write acknowledgement, conflict and capacity are separate
  fixed codes.
- Observer failure cannot affect business evidence. Observer promises have a cap of
  8, with pending and dropped visibility.
- Application observer resources have separate ownership.
- Python communication metrics are a separate finite map from the eighteen native
  metrics.
- Logs contain fixed event/code fields without transcripts, IDs or credentials.

## Validation and evidence

These verification layers stay distinct. Each passed within the selected I17 scope
recorded in the [phase handoff](../../docs/work-items/0037-playback-evidence-and-process-recovery.md).

| Check | Command | What it proves | Status |
| --- | --- | --- | --- |
| Public reducer/model tests and actual socket units | Package and Python unit commands in the [project guide](README.md#commands) | Reducer, model and loopback socket behavior | Passed (0037) |
| Pinned actual SDK capture tests | Python unit command in the [project guide](README.md#commands) | Capture through the pinned SDK | Passed (0037) |
| Sixteen-group storage gate | `make p2-communication-check` | Actual lock graphs, commit kills and populated restore | Passed (0037) |
| Three actual browser/audio groups | `make p2-playback-check` | Actual browser and audio evidence | Passed (0037) |
| Previous six-group native gate and storage regressions | `make p2-native-check` and the earlier storage lanes | Earlier native and storage behavior is preserved | Passed (0037) |
| Fresh installed npm and Python consumers | Recorded in the [phase handoff](../../docs/work-items/0037-playback-evidence-and-process-recovery.md) | Public APIs outside the checkout | Passed (0037) |

Missing, skipped or timed-out requirements do not pass. No complete P2 charter row,
real inference or physical-hearing guarantee follows from these selected scripted
gates.
