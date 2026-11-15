# Native conversation, local media and exact approval

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Record the decision and rationale for the native conversation, local media input and exact approval boundary |
| Audience | Engineers changing the native conversation, media input, projections or trace export; coding agents |
| Scope | Native session and tools, media invocations, projections, scripted audio, microphone capture, trace export and room dispatch snapshots; excludes production identity, provider credentials and release acceptance |
| Owns | Native conversation, media input, projection and trace export choices and their rationale |
| Related | [Decision 0006](0006-database-leases-and-bounded-worker.md) · [Phase G work item](../work-items/0013-p1-phase-g-conversation-and-showcase.md) · [Conversation and showcase guide](../conversation-and-showcase.md) · [Conversation agent design](../../services/conversation_agent/Design.md) |

## Context

P1 has one durable PostgreSQL authority and independent supplier and receiver
truth. A conversation must use it without creating a recovering queue, blocking
its media loop or turning model output into consent. The showcase must expose
actual state and be reproducible locally without model or carrier accounts or
device permissions.

## Decision

### Native session, tools and approval

Use native AgentSession, manual audio turns and three native no-argument tools:
`submit_investigation`, `get_case` and `cancel_case`. Trusted composition binds an
expiring signed room and participant grant to the frozen original investigation,
principal and replay key.

Atomic managed admission commits execution, case owner, continuation and deadline
together. Session lifetime never owns accepted work. Exact mutation
confirmation stays in the authenticated controller and UI. It uses the opaque
original canonical quote with supplier identity, supplier revision and case
binding.

### Media invocations and dispatch

A separate canonical media invocation UUID is frozen across uncertain mint
acknowledgements and changes only after an explicit ended invocation. The signed
grant preserves that identity. Closing AgentSession also requires explicit
JobContext shutdown after cleanup. A finished session cannot retain a worker slot.
Each explicitly ended media invocation gets a fresh room and participant and a new
native consumer, while the business task, case and key stay unchanged. Automatic
transport reconnect and unknown mint retry preserve the existing invocation.

New dispatch waits for stable native idle observations and actual assignment
within the existing finite deadline. Direct old-room replacement additionally
requires observable known-job termination. Empty or unassigned dispatches remain
unresolved rather than ready.

### Projections and notifications

Use current full scoped snapshots plus bounded recent derived persisted
observations. Revisions and epochs cross JSON as decimal strings. A native
notification only requests an authenticated GET. It cannot select scope, approve
or establish completion. Retain the original key and payload after unknown
acknowledgements. Keep M1 intake (the original SQLite confirmed-investigation
intake) and transport diagnostics independently available.

### Scripted audio source

Provide an explicit browser-native scripted-audio source as the default local demo
input, alongside a separate device-microphone choice. A user action creates and
publishes a real Web Audio MediaStream and LocalAudioTrack from the bundled spoken
pulse-code modulation (PCM) fixture. It crosses real WebRTC and the native SDK
speech-to-text (STT), large language model (LLM), text-to-speech (TTS) and tool
path. It does not replace getUserMedia, inject transcripts, fabricate playback or
bypass native control remote procedure calls (RPCs). The scripted recognizer
intentionally maps voiced turns to declared fixture commands. It does not claim
general recognition or model quality.

### Host microphone capture

Actual local host Chrome and Chromium capture probes remained pending with granted
and denied permission across multiple versions, including the test runner's pinned
build. Independent Web Audio probes produced live, advancing nonzero audio and
cleanly closed resources. This motivates an explicit reproducible fixture source,
not a passing claim for physical microphone capture.

Device mode checks native permission denial and bounds pending capture,
publication and cleanup, retaining uncertainty and ownership until real
completion. Physical microphone quality and human hearing remain separate
qualification work.

### Trace export

Use private trace providers with strict copy-based sanitization and an owned
finite HTTP OpenTelemetry Protocol (OTLP) transport. Ignore ambient exporter
credentials and proxies, discard response bodies, strip content, events, links and
trace-state headers, and export only bounded allowed metadata. SDK usage and report
observations select numeric fields rather than serializing reports.

Telemetry outage, queue saturation or shutdown cannot own or rewrite business
results. The dedicated native process contains SDK and OpenTelemetry (OTel) log
namespaces to fixed safe fields before the CLI root handler adds job metadata.

### Self-hosted room dispatch snapshots

The pinned
[server job deregistration source](https://github.com/livekit/livekit/blob/v1.13.11/pkg/service/agenthandler.go)
retains room dispatch state separately from worker job routing. Actual local runs
observed a closed native job and idle worker while the old room dispatch snapshot
still reported running. Fresh media rooms avoid coupling the durable case to that
snapshot lifecycle.

The browser gate still requires the same owned task and a fresh live native status
response. Room presence and retained transcripts cannot pass it. Unknown or jobless
records are never blindly deleted, and no custom quiescence fence or
process-memory business scheduler is introduced.

## Consequences

This adds a genuine second durable-service consumer without another workflow
framework, event bus, server-sent events (SSE) layer or frontend framework
rewrite. It also gives the local demo a deterministic input that requires no
device setup.

It does not provide production identity and access management (IAM), remote TLS
or provider credentials, general speech recognition, quality or cost evidence, or
full release acceptance. Those remain explicit later gates.

## Alternatives considered

| Alternative | Outcome | Reason |
| --- | --- | --- |
| Implicit model confirmation tool | Rejected | It would collapse investigation and exact mutation consent |
| Browser timer or mock projection | Rejected | Not accepted as progress evidence |
| Overriding getUserMedia with a synthetic return | Rejected | It would obscure the capture boundary |
| Upstream default OTLP exporter | Not used | It could merge ambient credentials and expose response bodies |

An openly selected scripted source keeps the capture boundary visible. The pinned
official encoder is used instead of the upstream default exporter, with the owned
transport and real protobuf-wire regression tests.

## Validation

The [Phase G work item](../work-items/0013-p1-phase-g-conversation-and-showcase.md)
owns exact results. Validation requires:

- Offline, native, HTTP and trace tests.
- The real restricted-role PostgreSQL lane.
- Installed source and asset parity.
- Actual browser scripted input and playback.
- Native tool acceptance.
- Interruption, end and reconnect.
- Real permission-denial handling.
- Held PostgreSQL and supplier responsiveness.
- Independent effect and receiver truth.
- Inspected three-service traces.
- Verified owned cleanup.

Missing or failed lanes leave the combined phase gate non-passing. Preserve the
original M1 identity and prior phase closing evidence.
