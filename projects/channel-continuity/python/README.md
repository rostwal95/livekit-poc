# Channel Continuity Python adapter

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Explain the `channel-continuity` Python codec and its optional native adapters |
| Audience | Engineers who use the Python codec or the optional native adapters; coding agents |
| Scope | The `channel_continuity` distribution and its optional `[native]` modules; excludes the TypeScript runtime they compose |
| Owns | Python package onboarding: modules, extras, native runtime options and package checks |
| Related | [Project guide](../README.md) · [Project design](../Design.md) · [Communication contract](../COMMUNICATION.md) · [Rehydration contract](../REHYDRATION.md) · [Contract work item](../../../docs/work-items/0022-p2-channel-contracts.md) |

## Overview

The `channel-continuity` distribution (import `channel_continuity`) is a pure
Python decoder for the versioned P2 channel boundary. The TypeScript SDK owns event
production. This codec is separate from LiveKit SDK APIs.

The optional native adapters compose the separately owned durable TypeScript
runtime described in the [project guide](../README.md).

| Component | Path | Requires | Responsibility |
| --- | --- | --- | --- |
| Default codec | `channel_continuity` | No runtime dependency | The default version-1 codec, independent of the optional SDK |
| Native runtime | `channel_continuity.native` | The `[native]` extra | `NativeRuntime` and `NativeHttpIntake` for native text and committed voice |
| Response evidence | `channel_continuity.native_communication` | Nothing for the pure models and client; `[native]` for SDK capture | Response evidence models, a typed port and a loopback HTTP client |
| Current-case context | `channel_continuity.native_rehydration` | Nothing for the pure models and client; `[native]` for SDK loading | Current-case context models, `NativeContextHttpClient` and `NativeRehydrationProfile` |

## Implementation status

| Capability | Status | Evidence |
| --- | --- | --- |
| Version-1 decoding, canonicalization and text production | Qualified | [Contract work item](../../../docs/work-items/0022-p2-channel-contracts.md) |
| Scripted native text and committed voice | Qualified | [Native phase handoff](../../../docs/work-items/0036-native-input-and-deadline-cancellation.md) |
| Source-qualified playback and interruption evidence | Qualified | [I17 handoff](../../../docs/work-items/0037-playback-evidence-and-process-recovery.md) |
| Current-case context loading | Qualified | [I18 handoff](../../../docs/work-items/0038-case-rehydration-and-standalone-release.md) |
| Real recognition and inference | Planned | [Next milestone](#next-milestone) |
| Full release scenarios | Planned | [Next milestone](#next-milestone) |

- The default codec remains pure.
- The optional native adapter composes the separately owned durable TypeScript
  boundary. This Python package does not own a second inbox, case authority or
  carrier store.
- The optional native adapter authenticates a trusted room binding through the
  separately owned P2 server. It never owns a durable queue.

## Documentation

| Document | Purpose |
| --- | --- |
| [Project guide](../README.md) | The TypeScript runtime, capability status and local gates |
| [Project design](../Design.md) | P2 architecture, state ownership and trade-offs |
| [Contract work item](../../../docs/work-items/0022-p2-channel-contracts.md) | Version-1 contract checks and limitations |
| [Communication contract](../COMMUNICATION.md) | The optional response evidence profile |
| [Rehydration contract](../REHYDRATION.md) | The optional current-case profile |

## Requirements

| Requirement | Version or value | Notes |
| --- | --- | --- |
| Python | 3.14 | Use the frozen root workspace environment |
| Runtime dependencies | None | Codec checks need no provider account, Docker service or credential |
| Optional native extra | `channel-continuity[native]` | Pins LiveKit Agents 1.8.11 for the SDK adapters |

## Commands

| Task | Command | Notes |
| --- | --- | --- |
| Run the project Python tests | `.venv/bin/python -m unittest discover -s projects/channel-continuity/tests -v` | From the repository root after workspace bootstrap |

From the repository root after workspace bootstrap:

```sh
.venv/bin/python -m unittest discover -s projects/channel-continuity/tests -v
```

## Optional native composition

### Installing and constructing the runtime

Install `channel-continuity[native]` to enable `channel_continuity.native` with
pinned LiveKit Agents 1.8.11. The default `channel_continuity` codec import remains
independent of the optional SDK.

- `NativeRuntime` owns explicit bounded text and manual voice capture. It permits
  generation only through the persisted P2 dispatch bridge.
- `NativeHttpIntake` uses a literal loopback endpoint and a separately supplied
  binding credential. No environment or provider keys are loaded.
- Caller and source identity and genuine final transcript snapshots are explicit
  typed values.
- SDK automatic text and completed-turn replies are disabled.

### Timing for real providers

`NativeRuntime(timing=NativeTiming(...))` optionally widens the model, commit and
transcript budgets for real providers. The defaults match the scripted profile.

| Option | Default | Allowed values | Description |
| --- | --- | --- | --- |
| `NativeTiming.model_seconds` | 2 seconds | 1–30 seconds | Model budget |
| `NativeTiming.commit_seconds` | 4 seconds | 2–12 seconds | Voice commit budget |
| `NativeTiming.transcript_seconds` | 2 seconds | 1–10 seconds, below `commit_seconds` | Transcript budget |
| `NativeTiming.reply` | `"playout"` | `"playout"` or `"scheduled"` | When a dispatch prepare returns |
| `NativeTiming.reply_seconds` | 60 seconds | 5–120 seconds | Bound for each scheduled-reply observer |
| `NativeTiming.replies` | 4 | 1–8 | Owned scheduled-reply observers |
| `NativeRuntime` `inference_mode` | `"scripted"` | `"scripted"` or `"provider_real"` | Labels the session (`p2.inference_mode`) for the browser's readiness check |
| `NativeRuntime` `instructions` | Scripted default | Bounded text, at most 4,096 UTF-8 bytes | Replaces the scripted default |

- With `reply="scheduled"`, a dispatch prepare returns once its reply is scheduled.
  An owned observer (at most `replies`, four by default, each bounded by
  `reply_seconds`) then publishes the completed, interrupted or unknown generation
  status. Close cancels pending observers.
- The default `reply="playout"` keeps the original wait-for-playout contract.
  Scheduled timing is refused together with response capture.

### Native shutdown and evidence limits

- Applications separately close the runtime, intake, real-time communication (RTC)
  room, injected providers and HTTP listeners.
- Timeout retains actual work, and incomplete cleanup fails.
- SDK completion never proves physical browser playback, user consent or supplier
  effects.

The [native phase handoff](../../../docs/work-items/0036-native-input-and-deadline-cancellation.md)
records selected scripted-native qualification. The separate
[I17 handoff](../../../docs/work-items/0037-playback-evidence-and-process-recovery.md)
records source-qualified playback and interruption qualification. I18 current-case
context has its own opt-in contract, described below.

## Optional response evidence

### Pure response client

`channel_continuity.native_communication` provides immutable response and
observation models, a typed port and an explicit loopback HTTP client without
importing the SDK. Supply four distinct credentials and one trusted immutable native
binding.

- The client retains two actual requests through socket settlement.
- It limits request and response bytes, snapshots inputs before awaits and
  preserves unknown writes.
- Read failures do not fabricate absence.
- No provider environment or default listener is loaded.

### SDK stream capture

With `[native]`, pass that port into `NativeRuntime(communication=...)`. This enables
public SDK large language model (LLM) and text-to-speech (TTS) stream capture and
response-scoped playback and interrupt remote procedure calls (RPCs). The
application owns the room, providers, client and server separately.

- The existing native wire and eighteen native metrics remain compatible.
  Communication has a separate eleven-field finite metrics map.
- A cancellation-ignoring node retains capacity after SDK forced-handle completion,
  until its actual finally/close.
- The collector streams through a two-chunk queue with backpressure and caps of
  4096 UTF-8 bytes / 256 chunks.
- Full generated text requires normal stream exhaustion. SDK text comes from actual
  settled chat items.
- Source failure, overflow or an incomplete model cannot authorize a known
  preparation.
- Playback is client-reported evidence, never human acknowledgement, business
  consent or a supplier effect.

See the [project communication contract](../COMMUNICATION.md) for capabilities,
bounds, retention, reducer semantics and commands.

## Optional current-case rehydration

### Pure context models and client

`channel_continuity.native_rehydration` provides `RehydrationQuery`, immutable
`RehydrationContext`, `NativeContextHttpClient` and `NativeRehydrationProfile`
without importing the optional SDK.

- A known context has the strict bounded current-case, history, work, response and
  reply data transfer object (DTO).
- Unknown or denied reads never fabricate empty authoritative state.
- Native HTTP reads require a fixed current binding and retain actual sockets and
  tasks after a waiter stops waiting.

### Loading context into the runtime

With `[native]`, `NativeRuntime(rehydration=NativeRehydrationProfile(port))` loads a
public `ChatContext` before SDK readiness.

- `refresh_context()` is explicit and idle. Load and refresh accept and generate
  nothing.
- `loaded_context` returns detached data.
- `rehydration_metrics()` is separate from the eighteen native metrics.
- New input keeps the ordinary persisted dispatch owner.
- Current and supplier facts are visibly as-of. Prepare revision equality is only a
  request-revision guard.
- Old response facts never become active new-room controls.
- Pure reads support case revision zero. Current native prepare and communication
  still require positive revisions, so new native input is denied before acceptance
  when loaded zero is unsupported. There is no automatic revision change.

See [REHYDRATION.md](../REHYDRATION.md) and the
[I18 handoff](../../../docs/work-items/0038-case-rehydration-and-standalone-release.md)
for boundaries, source normalization, zero-write reads, paging and selected
evidence.

## Validation

| Check | Command | What it proves | Status |
| --- | --- | --- | --- |
| Shared synthetic fixtures | `.venv/bin/python -m unittest discover -s projects/channel-continuity/tests -v` | Actual producer output, equivalent canonical bytes and deliberate invalid, scope and size cases in both languages | Passed (0022) |
| Scripted native gate | `make p2-native-check` | Selected scripted-native behavior | Passed (0036) |
| Communication storage and playback gates | `make p2-communication-check`, `make p2-playback-check` | Source-qualified playback and interruption evidence | Passed (0037) |
| Rehydration storage and media gates | `make p2-rehydration-check`, `make p2-rehydration-media-check` | Selected current-case context evidence | Passed (0038) |
| P2 product acceptance | See the [project guide](../README.md#validation) | Complete charter scenarios | Planned |

The shared fixture checks do not qualify P2 product acceptance or installed-consumer
usability.

## Next milestone

| Step | Outcome | Gate |
| --- | --- | --- |
| TypeScript inbox and opt-in native adapter | Implemented | Scripted-native qualification in the [native phase handoff](../../../docs/work-items/0036-native-input-and-deadline-cancellation.md) |
| I17 communication profile | Separate qualification | Recorded in the [I17 handoff](../../../docs/work-items/0037-playback-evidence-and-process-recovery.md) |
| I18 current-case profile | Opt-in context loading, described above | Recorded in the [I18 handoff](../../../docs/work-items/0038-case-rehydration-and-standalone-release.md) |
| Real recognition and inference | Native composition with real recognizers and inference | Subsequent gate (planned) |
| Full release scenarios | Complete P2 release | Subsequent gate (planned) |
