# Source-qualified communication contract

Status: Active
Last reviewed: 11 November 2026

## Overview

The opt-in I17 profile preserves durable generated, SDK and browser response facts
without combining them into a claim that a person heard a response. Qualification,
commands and exact evidence are recorded in the [phase handoff](../../docs/work-items/0037-playback-evidence-and-process-recovery.md).
The [project design](Design.md) owns architecture and tradeoffs; the [charter](../../docs/projects/channel-continuity-scope.md)
owns complete acceptance requirements. I18 current-case room rehydration separately
passed its selected storage/media and installed-consumer gates, as recorded in the
[completed handoff](../../docs/work-items/0038-case-rehydration-and-standalone-release.md).
P2-I19/I20 and full release retain their own requirements.

## Trusted construction and public API

Import server APIs from `@livekit-ecosystem/channel-continuity/communication`.
`createCommunicationIntegration(native, grants)` requires the opaque native
integration and trusted finite scope/case/conversation grants. Supply distinct
publisher, SDK and browser credentials, separate from account/native credentials.
The SDK never accepts a caller-created principal or a payload source label as
authentication.

| API | Capability and result |
| --- | --- |
| beginResponse | Publisher binds immutable response, generation, SDK speech, binding, accepted input receipt/operation and case revision; returns original response receipt |
| observeSdk | SDK credential appends actual generated_complete or speech_settled fact; returns immutable observation receipt |
| observeBrowser | Browser credential appends client started/partial/interrupted/completed report with observedAudioMs; returns immutable observation receipt |
| inspectResponse | Account credential returns exact original anchor/receipt and coherent generated/SDK/browser projection |
| responses | Account-scoped descending page1–32 with original scoped response sequence |
| observations | Original-response page1–8 after a response-local observation sequence |

The loopback HTTP gateway exposes four explicit POST routes under `/v1/native/`:
`responses`, `sdk-observations`, `browser-observations`, `response-inspect`.
Credential determines role. Requests are canonical UTF-8 JSON, at most 32768 bytes;
write receipts are at most 2048 and read views 65536. Responses require explicit
Connection:close. Invalid responses after a possible write remain unknown. There
is no automatic retry. The application owns all listeners/clients separately.

## Storage, lifetime and recovery

Run owner `upgradeChannelSchemaV7` explicitly after v6 with service writers
quiescent. Three additive tables retain profile settings, response anchors and
source/event observations. Serving performs no DDL or cleanup. Original canonical
rows/receipts remain unchanged. Interrupted upgrade rolls back before a fresh
owner upgrade; populated backup/restore uses the actual local PostgreSQL tools.

One original admission lock guards cap counters and new rows. A new response
requires the current original binding and fresh database time after locks.
Original retained facts/replays remain valid after expiry/revoke; this permits
historical observation without renewing a room or starting preparation.

Default caps are 1024 responses,8192 observations and16 per response. Supported
maxima are 10000/100000/64. New identities fail before growth at capacity; equal
original replay retains its receipt. Response sequence is scoped to tenant,
account and conversation; observation sequence is local to the original response.
Global counts remain profile-cap metadata. There is no physical pruning, TTL,
identity reuse or replay-horizon erasure in this profile.

## Streaming native adapter

The pure `channel_continuity.native_communication` module supplies immutable typed
models/port and a bounded loopback client. The optional pinned `[native]` adapter
uses public SDK nodes and the exact public returned SpeechHandle.

An application ContextVar is captured around synchronous generate_reply and
propagates into SDK-created tasks. The LLM/TTS node records ownership at the
synchronous node call; missing/retired contexts fail closed. It never borrows
session.current_speech or private SDK fields. A bounded collector forwards source
chunks immediately through queue of 2 while retaining at most4096 UTF-8 bytes and256
chunks. It preserves flush boundaries and backpressure. At most16 TTS calls and8
actual SDK node tasks are admitted for one response; session metadata holds 64
response identities. Full generated text requires normal actual LLM exhaustion,
source closure and known durable publication. Prefix/error/overflow is incomplete.

SpeechHandle.done can precede actual provider cancellation/drain. Actual node,
producer and publication ownership survives it; a cancellation-ignoring source
holds capacity until real settlement. SDK terminal text is actual settled chat
item text, never expected fixture output or the generated-text substitute. A clean
complete scripted read-only preparation interrupted during output can preserve its
known decision; playback does not trigger automatic regeneration. Source or SDK
failure remains unknown and cannot create known preparation.

The original native18 metrics and six-key p2.generation topic remain compatible.
The separate p2.response mapping carries response/generation/speech identity without
text. Authenticated p2.playback reports the original response; p2.interrupt_response
requests interruption only on its captured handle. A request is not proof stopped.
The application readonly `/p2/response` endpoint uses its separate operator bearer.

## Projection and UI meaning

Generated text, SDK state/text and browser state are independent fields. The
commutative reducer retains contradictory evidence; arrival or provider time never
selects a winner. SDK completed plus no browser completion remains browser unknown.
A browser completed state is displayed as completed_reported. Neither state is
human acknowledgement, exact quote consent, supplier effect or business completion.

The local page measures actual browser PCM frames for its client report. Normal
playback requires explicit completion reporting. Interrupted playback records a
partial observation separately from SDK interrupted settlement. Withheld reports
and disconnect leave durable browser state unknown; later useful input still
progresses. A delayed original response cannot interrupt or relabel a new response.

## Observability and verification

Store counters report committed anchors/facts/replay and admitted SQL failures;
pre-SQL authentication/shape failures are outside that counter population. SQL
failure, unknown write acknowledgement, conflict and capacity are separate fixed
codes. Observer failure cannot affect business evidence; promises have a cap of 8 with
pending/dropped visibility. Application observer resources have separate ownership.
Python communication metrics are a separate finite map from native18. Logs contain
fixed event/code fields without transcripts, IDs or credentials.

Verification layers stay distinct: public reducer/model and actual socket units,
pinned actual SDK capture tests, storage16 with actual lock graphs/commit kills and
populated restore, browser/audio3, previous native6 and storage regressions, and
fresh installed npm/Python consumers. Missing/skipped/timed-out requirements do not
pass. No complete P2 charter row or real inference/physical-hearing guarantee follows
from these selected scripted gates.


## Cross-room historical reads

The separate [rehydration contract](REHYDRATION.md) can include compact original
response/speech references and generated/SDK/browser source summaries. It does not
include full output text or enroll historical responses as new-room controls.
Reading context creates no communication observation, playback claim, human
acknowledgement or mutation consent. The source response/observation receipts and
all existing evidence remain unchanged; byte-limited pages omit whole records.
