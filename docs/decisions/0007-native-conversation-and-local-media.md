# Native conversation, local media and exact approval

Status: Active
Last reviewed: 9 November 2026

## Context

P1 has one durable PostgreSQL authority and independent supplier/receiver truth.
A conversation must use it without creating a recovering queue, blocking its media
loop or turning model output into consent. The showcase must expose actual state
and be reproducible locally without model/carrier accounts or device permissions.

## Decision

Use native AgentSession, manual audio turns and three native no-argument tools:
submit_investigation, get_case and cancel_case. Trusted composition binds an
expiring signed room/participant grant to the frozen original investigation,
principal and replay key. A separate canonical media invocation UUID is frozen
across uncertain mint acknowledgements and changes only after an explicit ended
invocation. The signed grant preserves that identity. Closing AgentSession also
requires explicit JobContext shutdown after cleanup; a finished session cannot
retain a worker slot. Each explicitly ended media invocation gets a fresh room/participant and a new
native consumer, while the business task/case/key stay unchanged. Automatic
transport reconnect and unknown mint retry preserve the existing invocation.
New dispatch waits for stable native idle observations and actual assignment
within the existing finite deadline. Direct old-room replacement additionally
requires observable known-job termination. Empty/unassigned
dispatches remain unresolved rather than ready. Atomic managed admission commits execution, case owner
and continuation/deadline together. Session lifetime never owns accepted work.
Exact mutation confirmation stays in the authenticated controller/UI, using the
opaque original canonical quote with supplier identity/revision and case binding.

Use current full scoped snapshots plus bounded recent derived persisted
observations. Revisions/epochs cross JSON as decimal strings. A native notification
only requests an authenticated GET; it cannot select scope, approve or establish
completion. Retain the original key/payload after unknown acknowledgements. Keep
M1 intake and transport diagnostics independently available.

Provide an explicit browser-native scripted-audio source as the default local demo
input, alongside a separate device-microphone choice. A user action creates and
publishes a real Web Audio MediaStream/LocalAudioTrack from the bundled spoken PCM
fixture; it crosses real WebRTC and native SDK STT/LLM/TTS/tools. It does not replace
getUserMedia, inject transcripts, fabricate playback or bypass native control RPCs.
The scripted recognizer intentionally maps voiced turns to declared fixture
commands; it does not claim general recognition or model quality.

Actual local host Chrome/Chromium capture probes remained pending with granted
and denied permission across multiple versions, including the test runner's pinned
build. Independent Web Audio probes produced live, advancing nonzero audio and
cleanly closed resources. This motivates an explicit reproducible fixture source,
not a passing claim for physical microphone capture. Device mode checks native
permission denial and bounds pending capture/publication/cleanup, retaining
uncertainty and ownership until real completion. Physical microphone quality and
human hearing remain separate qualification work.

Use private trace providers with strict copy-based sanitization and an owned finite
HTTP OTLP transport. Ignore ambient exporter credentials/proxies, discard response
bodies, strip content/events/links/trace-state headers and export only bounded
allowed metadata. SDK usage/report observations select numeric fields rather than
serializing reports. Telemetry outage, queue saturation or shutdown cannot own or
rewrite business results. The dedicated native process contains SDK and OTel log
namespaces to fixed safe fields before the CLI root handler adds job metadata.

## Consequences and alternatives

This adds a genuine second durable-service consumer without another workflow
framework, event bus, SSE layer or frontend framework rewrite. It also gives the
local demo a deterministic input that requires no device setup. It does not provide
production IAM, remote TLS/provider credentials, general speech recognition,
quality/cost evidence or full release acceptance. Those remain explicit later gates.

An implicit model confirmation tool was rejected because it would collapse
investigation and exact mutation consent. A browser timer or mock projection was
rejected as progress evidence. Overriding getUserMedia with a synthetic return was
rejected because it would obscure the capture boundary; an openly selected scripted
source keeps that boundary visible. The upstream default OTLP exporter could merge
ambient credentials and expose response bodies, so the pinned official encoder is
used with the owned transport and real protobuf-wire regression tests.

## Validation

The [Phase G work item](../work-items/0013-p1-phase-g-conversation-and-showcase.md)
owns exact results. Require offline/native/HTTP/trace tests, the real restricted-role
PostgreSQL lane, installed source/asset parity, actual browser scripted input and
playback, native tool acceptance, interruption/end/reconnect, real permission-denial
handling, held PostgreSQL/supplier responsiveness, independent effect/receiver truth,
inspected three-service traces and verified owned cleanup. Missing or failed lanes
leave the combined phase gate non-passing. Preserve original M1 identity and prior
phase closing evidence.

## Self-hosted room dispatch snapshots

The pinned [server job deregistration source](https://github.com/livekit/livekit/blob/v1.13.11/pkg/service/agenthandler.go)
retains room dispatch state separately from worker job routing. Actual local runs
observed a closed native job and idle worker while the old room dispatch snapshot
still reported running. Fresh media rooms avoid coupling the durable case to that
snapshot lifecycle. The browser gate still requires the same owned task and a fresh
live native status response; room presence and retained transcripts cannot pass it.
Unknown/jobless records are never blindly deleted, and no custom quiescence fence
or process-memory business scheduler is introduced.
