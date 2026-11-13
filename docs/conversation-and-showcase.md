# Conversation and durable-work showcase

Status: Active
Last reviewed: 10 November 2026

## Overview

Phase G connects a native Python AgentSession to the existing PostgreSQL v4
execution authority and adds a browser workspace for inspecting real case state.
By default, the named conversation agent uses bundled local scripted STT/LLM/TTS fixtures.
Audio crosses actual browser WebRTC tracks and native SDK tools; no paid model,
carrier account or model download is required. Physical microphone quality,
human hearing and selected provider inference are separate evidence; provider_real v2 has now passed its Phase H gate.

The [work item](work-items/0013-p1-phase-g-conversation-and-showcase.md) records the
phase gate. P1-I26 host/Linux artifacts, independent API/failure review and genuine
native consumer passed, alongside the separate H2 reliability slice. Both explicit
real-profile implementations exist. The selected provider_real v2 gate passed both actual browser cases with cleanup. P1 V1 is qualified for the local POC using provider_real v2. The local_real engine profile remains unqualified; exact scope is tracked by Phase H work items.
The P2/P3 charters and full acceptance catalog are unchanged.

## Configured profiles and evidence

The default scripted profile preserves the exact Phase G regression: declared
manual-turn transcripts and prerecorded speech through real RTC. The explicit
local_real profile uses prepared local Whisper ASR, Qwen LLM/tool selection and
Piper generated speech, without a scripted transcript/reply mapping or paid
provider fallback. Actual engines/model/media qualification is pending; read the
[operations guide](local-real-inference.md) for setup and result ownership.

The API supplies a strict trusted mode; the browser cannot select another worker
profile in a request. The native selected AGENT must report that same mode and
RoomIO-ready attribute plus active SDK state. The badge distinguishes configured
profile from matched native readiness; neither establishes model quality. The
default prerecorded WAV input is independent of inference mode and never proves
physical microphone capture. All three profiles preserve original task/key/consent
authority and the separate explicit exact-quote confirmation.

## Local setup

Run the normal bootstrap and local stack setup in the [local guide](../local-setup/README.md).
Business mode is explicit and requires an already prepared ACTIVE v4 schema plus
independent supplier and completion-receiver fixtures. For a fresh local database,
use the documented SQLite migration/cutover and ordered v2/v3/v4 owner upgrades;
runtime credentials cannot install or activate schemas. Preserve existing M1 data.

```sh
.venv/bin/python local-setup/stack.py init-worker-fixtures
.venv/bin/python local-setup/stack.py start-business
.venv/bin/python local-setup/stack.py worker-status
```

The manager validates role/schema and fixture prerequisites before starting the
native conversation worker, durable worker, API and optional Jaeger. An absent
prerequisite is a failure with an actionable code. Ordinary start keeps business
mode disabled. stop-business drains native/durable workers and returns the API to
ordinary M1 mode; data remains in its volumes. Normal stop preserves volumes too.

The API mounts the same supplier volume read-only for proposal inspection. Native
conversation receives runtime PostgreSQL and LiveKit credentials, no operator
bearer, migrator credential or supplier volume. Supplier/receiver remain separate
stores. No public route enables test faults or runs a migration.

## Demonstration flow

1. Enter the local operator token and explicitly authorize investigation of the
   synthetic booking. The original payload and replay key remain frozen through an
   unknown acknowledgement. Atomic acceptance commits execution, case owner and
   continuation deadline together. Approval to investigate does not change a booking.
2. Observe request, inquiry, case revision and recent persisted observations. Every
   refresh is an authenticated current projection. Event history is bounded and
   discloses truncation; changed snapshots reset pagination. An unverified resume
   UUID cannot become the selected business task or voice binding.
3. Connect scripted voice for that verified case. Choose the explicit local scripted
   audio source to publish bundled spoken PCM through a real browser-native audio
   track; device microphone mode is a separate choice. Publication requires a user
   action. Start a turn, publish known non-silent audio and commit it. The
   manual recognizer produces declared fixture commands, then the native SDK invokes
   real no-argument tools bound to the original authorized request. Typed status is
   also supported. The UI labels scripted mode and distinguishes SDK speech state
   from actual browser playback.
4. Interrupt output, end voice and reconnect. These actions control media only.
   Accepted work persists independently. An unreliable refresh hint only requests a
   fresh scoped GET. It cannot choose another task, confirm a quote or establish
   completion. Hard reload requires explicit owned-task resume and reauthentication.
5. Request a trusted proposal after a successful matching availability inquiry.
   The server reads the independent supplier identity/revision outside its protected
   database transaction, then atomically publishes a quote/wait. Changed or unavailable
   requests cannot reuse another inquiry's result.
6. Review the exact price/date/expiry and explicitly approve in the authenticated
   workflow panel. The browser returns the opaque original canonical proposal without
   reconstructing 64-bit numeric values. Stale quote/revision, wrong owner, mismatch
   and expiry fail closed. The model has no confirmation/signal tool.
7. Inspect effect, final business outcome and receiver delivery separately. A known
   supplier success remains known after cancellation/deadline. Uncertain external
   effects remain visibly uncertain. Delivered does not mean a human heard speech or
   acknowledged the result. Independently inspect supplier and receiver truth in the
   phase gate rather than accepting UI text as proof.

## Components and limits

| Boundary | Implemented rule |
| --- | --- |
| Managed admission | Same original owner/key/payload replays before new quotas; legacy unmanaged keys are not silently adopted |
| Projection | Current full state; recent 100 observations per source; 50 per page maximum; 64 KiB response; scope/owner-bound digest/cursor |
| HTTP | Existing 16 KiB/five-second body budget, four-slot offload, fixed safe error envelopes and protected metrics |
| Session binding | Signed HMAC grant, 300-second TTL, fixed principal, frozen request/key, room and expected participant; active conflicting room returns session_in_use |
| Native job | One active/pending job per server, 180-second maximum, explicit finite cleanup; manual turn and no implicit inference preloading |
| Native input/tools | 32 tools/text turns, 64 control RPCs, two finite text readers, 4 KiB text, strict caller binding |
| Media authority | Selected native AGENT source only; actual track/playback state separate from generated transcript/output |
| Telemetry | Filtered finite traces, numeric-only SDK usage/report files, finite queue/bytes/deadlines; exporter failure cannot own work |

## Failure reconciliation

An unknown submission or command acknowledgement is unresolved. Reconcile the
frozen original identity and read current state; do not generate another request
because a timer elapsed. A later projection can be newer than a command receipt.
A definitive rejection can reopen editing only when no earlier ambiguous attempt
could have been accepted. Browser forget clears in-memory selection/credentials
and ends owned media resources; it does not cancel durable business work.

Microphone permission failure and autoplay restrictions are displayed from actual
browser operations. SDK state and audio element playback are independent. Native
room interruption never invokes business cancellation. Explicit cancellation is a
separate durable command and may be best effort after possible external dispatch.

## Validation and evidence

Run make check, make frontend-check and make postgres-check using the frozen
project environment. The native suite runs real AgentSession text/manual audio,
not direct mocked function calls alone. The OTLP suite decodes real protobuf wire
requests and tests timeout, queue overflow, inherited credential exclusion and
shutdown races. Installed/browser evidence belongs to make phase-g-demo and the
Phase G validation directory. The gate must observe actual audio input/output,
advancing playback, interruption/reconnect, held supplier/slow persistence,
independent mutation/receiver state, safe SDK reports and inspected Jaeger traces.

Keep screenshots free of credentials. Browser HAR, trace and video recording are
disabled for this lane. Retain failed artifacts with safe codes/counts; label
missing/failed required setup non-passing. Preserve original M1 identity and prior
phase closing artifacts during compatibility runs.

## Media invocation replay and readiness

A media invocation has its own canonical UUID, separate from the accepted business
request key and task identity. The browser freezes it across an unknown token/room
acknowledgement. Explicit End or a completed native disconnect starts a new
invocation on the next Connect with a fresh room and participant, while preserving
the same scoped task, case, original request and business replay key. Automatic
transport reconnect and uncertain mint retries keep their current frozen room,
participant and invocation. The API signs this UUID as the grant identity. It reuses an assigned
job only for the same invocation. The default UI gives each ended invocation a new
room. Direct attempts to reuse an old room for a different invocation remain
fail-closed unless its prior jobs are observably terminal. An unassigned/unknown dispatch remains
unresolved and cannot be treated as ready or blindly replaced.

Before a new dispatch, the local controller observes the private native SDK health
and worker status under the original four-second dispatch deadline. A stable idle
observation spans the SDK status publication interval; it is consumed once for
that admission. This avoids dropping a request into a worker still advertised as
full after shutdown. The controller requires an actually assigned nonterminal job
before minting credentials. These are bounded media-admission observations, not
another durable business queue. Slow/unavailable capacity returns a fixed safe
failure. Runtime/SDK health does not prove actual media; the browser still verifies
a fresh native reply after reconnect.

The pinned self-hosted server retains room dispatch snapshots after worker job
completion. The demo therefore does not interpret an old room's running snapshot
as a live consumer, or guess that a job is safe to delete. A new room for an
explicitly new invocation makes the media boundary clear. Actual reconnect proof
requires a fresh native status reply bound to the original durable case. See the
[release-based source](https://github.com/livekit/livekit/blob/v1.13.11/pkg/service/agenthandler.go)
and the [composition decision](decisions/0007-native-conversation-and-local-media.md).


### Explicit provider-real profile

The trusted mode enum is scripted (default), local_real or provider_real.
provider_real uses livekit-plugins-deepgram, livekit-plugins-openai and
livekit-plugins-elevenlabs, all pinned to 1.8.11 with Agents 1.8.11. The fixed
pipeline is Deepgram nova-3 batch recognition on manual flush, OpenAI gpt-5.4-mini
streaming Chat Completions with none reasoning and at most 128 output tokens,
and ElevenLabs eleven_v4_turbo chunked HTTP PCM speech. It is a separately
selected profile, never an automatic fallback from a failed local engine.

The [provider operations guide](provider-demo.md) owns explicit setup/check/start/stop and
the trusted provider P1-20 selector. Three private keys reach only the native
process; local model caches and engines are unnecessary. The selected provider_real v2 gate passed both actual browser cases with cleanup. P1 V1 is qualified for the local POC using provider_real v2. External provider CPU/memory are
unobserved; no zero-retention or model-quality guarantee follows from local
content-free telemetry. Default offline/scripted checks make no provider calls.
