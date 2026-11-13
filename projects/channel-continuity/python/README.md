# Channel Continuity Python adapter

Status: Active
Last reviewed: 11 November 2026

## Overview

A pure Python decoder for the versioned P2 channel boundary. The TypeScript SDK
owns event production. This codec is separate from LiveKit SDK APIs.

## Implementation status

Version-1 decoding/canonicalization and text production are implemented. The
optional native adapter composes the separately owned durable TypeScript boundary;
this Python package does not own a second inbox, case authority or carrier store.
The default codec remains pure. The optional native adapter below authenticates a trusted room binding through the separately owned P2 server; it never owns a durable queue.

## Documentation

Read the [project guide](../README.md), [design](../Design.md) and
[contract work item](../../../docs/work-items/0022-p2-channel-contracts.md).

## Requirements

Python 3.14 and the frozen root workspace environment. No runtime dependency,
provider account, Docker service or credential is needed for codec checks.

## Commands

From the repository root after workspace bootstrap:

```sh
.venv/bin/python -m unittest discover -s projects/channel-continuity/tests -v
```

## Validation

Shared synthetic fixtures assert actual producer output, equivalent canonical
bytes and deliberate invalid/scope/size cases in both languages. These checks
do not qualify P2 product acceptance or installed-consumer usability.

## Next milestone

The TypeScript inbox and opt-in native adapter are implemented. The I17
communication profile below has separate qualification recorded in its handoff;
The separate I18 current-case profile is described below; real recognition/inference
and full release scenarios retain subsequent gates.

## Optional native composition

Install `channel-continuity[native]` to enable `channel_continuity.native` with
pinned LiveKit Agents 1.8.11. The default `channel_continuity` codec import remains
independent of the optional SDK. NativeRuntime owns explicit bounded text/manual
voice capture and permits generation only through the persisted P2 dispatch bridge.
NativeHttpIntake uses a literal loopback endpoint and separately supplied binding
credential; no environment/provider keys are loaded. Caller/source identity and
genuine final transcript snapshots are explicit typed values. SDK automatic text
and completed-turn replies are disabled.

Applications separately close runtime, intake, RTC room, injected providers and
HTTP listeners. Timeout retains actual work and incomplete cleanup fails. SDK
completion never proves physical browser playback, user consent or supplier effects.
The [native phase handoff](../../../docs/work-items/0036-native-input-and-deadline-cancellation.md)
records selected scripted-native qualification. The separate [I17 handoff](../../../docs/work-items/0037-playback-evidence-and-process-recovery.md) records source-qualified playback/interruption qualification; I18 current-case context has its own opt-in contract below.

## Optional response evidence

`channel_continuity.native_communication` provides immutable response/observation
models, a typed port and explicit loopback HTTP client without importing the SDK.
Supply four distinct credentials and one trusted immutable native binding. The
client retains two actual requests through socket settlement, limits request and
response bytes, snapshots inputs before awaits and preserves unknown writes.
Read failures do not fabricate absence. No provider environment or default listener
is loaded.

With `[native]`, pass that port into `NativeRuntime(communication=...)` to enable
public SDK LLM/TTS stream capture and response-scoped playback/interrupt RPCs.
The application owns the room, providers, client and server separately. Existing
native wire and eighteen native metrics remain compatible; communication has a
separate eleven-field finite metrics map. A cancellation-ignoring node retains
capacity after SDK forced-handle completion until its actual finally/close.

The collector streams through a two-chunk queue with backpressure and caps of
4096 UTF-8 bytes / 256 chunks. Full generated text requires normal stream exhaustion;
SDK text comes from actual settled chat items. Source failure/overflow/incomplete
model cannot authorize a known preparation. Playback is client-reported evidence,
never human acknowledgement, business consent or a supplier effect. See the
[project communication contract](../COMMUNICATION.md) for capabilities, bounds,
retention, reducer semantics and commands.


## Optional current-case rehydration

`channel_continuity.native_rehydration` provides `RehydrationQuery`, immutable
`RehydrationContext`, `NativeContextHttpClient` and `NativeRehydrationProfile`
without importing the optional SDK. A known context has the strict bounded
current-case/history/work/response/reply DTO; unknown/denied reads never fabricate
empty authoritative state. Native HTTP reads require a fixed current binding and
retain actual sockets/tasks after a waiter stops waiting.

With `[native]`, `NativeRuntime(rehydration=NativeRehydrationProfile(port))` loads a
public `ChatContext` before SDK readiness. `refresh_context()` is explicit and idle;
load/refresh accept and generate nothing. `loaded_context` returns detached data,
`rehydration_metrics()` is separate from native18, and new input keeps the ordinary
persisted dispatch owner. Current/supplier facts are visibly as-of; prepare revision
equality is only a request-revision guard. Old response facts never become active
new-room controls. Pure reads support case revision zero; current native prepare/
communication still require positive revisions, so new native input is denied
before acceptance when loaded zero is unsupported. No automatic revision change.
See [REHYDRATION.md](../REHYDRATION.md) and the [I18 handoff](../../../docs/work-items/0038-case-rehydration-and-standalone-release.md) for
boundaries, source normalization, zero-write reads, paging and selected evidence.
