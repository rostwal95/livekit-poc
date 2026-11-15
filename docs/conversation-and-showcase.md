# Conversation and durable-work showcase

Status: Active
Last reviewed: 15 November 2026

## Overview

This guide explains the Phase G showcase. Phase G connects a native Python
AgentSession to the existing P1 (agent continuity) PostgreSQL v4 execution
authority and adds a browser workspace for inspecting real case state. The guide
covers configured inference profiles, local setup, the demonstration flow,
component limits, failure reconciliation, validation, and media invocation replay
and readiness. It is for engineers who run the showcase or change the
conversation, console or controller boundaries.

### What the showcase uses

- By default, the named conversation agent uses bundled local scripted
  speech-to-text (STT), large language model (LLM) and text-to-speech (TTS)
  fixtures.
- Audio crosses actual browser WebRTC tracks and native software development kit
  (SDK) tools.
- No paid model, carrier account or model download is required.
- Physical microphone quality, human hearing and selected provider inference are
  separate evidence. provider_real v2 has passed its Phase H gate.

### Current status

- The [work item](work-items/0013-p1-phase-g-conversation-and-showcase.md)
  records the phase gate.
- P1-I26 host and Linux artifacts, independent API and failure review and the
  genuine native consumer passed, alongside the separate H2 reliability slice.
- Both explicit real-profile implementations exist. The selected provider_real v2
  gate passed both actual browser cases with cleanup. P1 V1 (the fixed
  first-version scope) is qualified for the local proof of concept (POC) using
  provider_real v2.
- The local_real engine profile remains unqualified. Phase H work items track the
  exact scope.
- The P2/P3 charters and full acceptance catalog are unchanged.

## Configured profiles and evidence

### Scripted and local_real profiles

- The default scripted profile preserves the exact Phase G regression: declared
  manual-turn transcripts and prerecorded speech through actual real-time
  communication (RTC).
- The explicit local_real profile uses prepared local Whisper automatic speech
  recognition (ASR), Qwen LLM and tool selection, and Piper generated speech. It
  has no scripted transcript or reply mapping and no paid provider fallback.
- Actual engine, model and media qualification is pending. Read the
  [operations guide](local-real-inference.md) for setup and result ownership.

### Mode selection and readiness

- The API supplies a strict trusted mode. The browser cannot select another
  worker profile in a request.
- The selected native AGENT must report that same mode and the RoomIO-ready
  attribute, plus an active SDK state.
- The badge distinguishes the configured profile from matched native readiness.
  Neither establishes model quality.
- The default prerecorded WAV input is independent of inference mode and never
  proves physical microphone capture.
- All three profiles preserve the original task, key and consent authority and
  the separate explicit exact-quote confirmation.

## Local setup

Before you start:

1. Run the normal bootstrap and local stack setup in the
   [local guide](../local-setup/README.md).
2. Prepare an ACTIVE v4 or v5 schema. For a fresh local database, use the
   documented SQLite migration and cutover and the ordered v2, v3 and v4 owner
   upgrades, plus the additive v5 step. Runtime credentials cannot install or
   activate schemas.
3. Preserve existing M1 data (the original SQLite confirmed-investigation
   intake).

Business mode is explicit. It requires the prepared schema plus independent
supplier and completion-receiver fixtures. Initialize the fixtures and start
business mode:

```sh
.venv/bin/python local-setup/stack.py init-worker-fixtures
.venv/bin/python local-setup/stack.py start-business
.venv/bin/python local-setup/stack.py worker-status
```

### What start-business and stop-business do

- The manager validates role, schema and fixture prerequisites before starting
  the native conversation worker, durable worker, API and optional Jaeger.
- An absent prerequisite is a failure with an actionable code.
- Ordinary start keeps business mode disabled.
- stop-business drains the native and durable workers, removes the native
  conversation-agent container and returns the API to ordinary M1 mode.
  start-business recreates the container, so provider keys do not remain in a
  stopped container's configuration.
- Data remains in its volumes after stop-business. Normal stop preserves volumes
  too.

### Credentials and mounts

- The API mounts the same supplier volume read-only for proposal inspection.
- The native conversation receives runtime PostgreSQL and LiveKit credentials.
  It receives no operator bearer token, migrator credential or supplier volume.
- Supplier and receiver remain separate stores.
- No public route enables test faults or runs a migration.

## Demonstration flow

1. **Authorize the investigation.** Enter the local operator token and
   explicitly authorize investigation of the synthetic booking. The original
   payload and replay key remain frozen through an unknown acknowledgement.
   Atomic acceptance commits execution, case owner and continuation deadline
   together. Approval to investigate does not change a booking.
2. **Observe the case.** Observe the request, inquiry, case revision and recent
   persisted observations. Every refresh is an authenticated current projection.
   Event history is bounded and discloses truncation, and changed snapshots reset
   pagination. An unverified resume universally unique identifier (UUID) cannot
   become the selected business task or voice binding.
3. **Connect scripted voice.** Connect scripted voice for that verified case.
   Choose the explicit local scripted audio source to publish bundled spoken
   pulse-code modulation (PCM) audio through a real browser-native audio track.
   Device microphone mode is a separate choice, and publication requires a user
   action. Start a turn, publish known non-silent audio and commit it. The manual
   recognizer produces declared fixture commands, and the native SDK then invokes
   real no-argument tools bound to the original authorized request. Typed status
   is also supported. The UI labels scripted mode and distinguishes SDK speech
   state from actual browser playback.
4. **Interrupt, end and reconnect.** These actions control media only, and
   accepted work persists independently. An unreliable refresh hint only requests
   a fresh scoped GET. It cannot choose another task, confirm a quote or establish
   completion. A hard reload requires explicit owned-task resume and
   reauthentication.
5. **Request a proposal.** Request a trusted proposal after a successful matching
   availability inquiry. The server reads the independent supplier identity and
   revision outside its protected database transaction, then atomically publishes
   a quote and wait. Changed or unavailable requests cannot reuse another
   inquiry's result.
6. **Approve the exact quote.** Review the exact price, date and expiry, and
   explicitly approve in the authenticated workflow panel. The browser returns
   the opaque original canonical proposal without reconstructing 64-bit numeric
   values. A stale quote or revision, a wrong owner, a mismatch and expiry fail
   closed. The model has no confirmation or signal tool.
7. **Inspect the results.** Inspect the effect, final business outcome and
   receiver delivery separately. A known supplier success remains known after
   cancellation or deadline. Uncertain external effects remain visibly uncertain.
   Delivered does not mean that a human heard speech or acknowledged the result.
   In the phase gate, independently inspect supplier and receiver truth rather
   than accepting UI text as proof.

## Components and limits

In the table, HMAC is a hash-based message authentication code, TTL is time to
live and RPC is a remote procedure call.

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

### Unknown acknowledgements

An unknown submission or command acknowledgement is unresolved.

- Reconcile the frozen original identity and read current state. Do not generate
  another request because a timer elapsed.
- A later projection can be newer than a command receipt.
- A definitive rejection can reopen editing only when no earlier ambiguous
  attempt could have been accepted.

### Native tools after an unknown submit acknowledgement

A submit acknowledgement is unknown when the tool's waiter timed out while the
protected write may still commit. After that, the native get_case and cancel_case
tools work as follows:

1. They first replay the frozen original submit with the same idempotency key, to
   learn the task.
2. They then read or cancel that task.
3. If the replay cannot finish, the tool raises the fixed unavailable error. The
   reply says that the operation could not be completed and points to the
   workflow panel. It never says that nothing was accepted.

### Media actions and browser state

- Browser forget clears the in-memory selection and credentials and ends owned
  media resources. It does not cancel durable business work.
- Microphone permission failure and autoplay restrictions are displayed from
  actual browser operations.
- SDK state and audio element playback are independent.
- Native room interruption never invokes business cancellation.
- Explicit cancellation is a separate durable command. It may be best effort
  after possible external dispatch.

## Validation and evidence

Run make check, make frontend-check and make postgres-check using the frozen
project environment.

- The native suite runs real AgentSession text and manual audio, not direct
  mocked function calls alone.
- The OpenTelemetry Protocol (OTLP) suite decodes real protobuf wire requests and
  tests timeout, queue overflow, inherited credential exclusion and shutdown
  races.
- Installed and browser evidence belongs to make phase-g-demo and the Phase G
  validation directory.

The gate must observe:

- actual audio input and output;
- advancing playback;
- interruption and reconnect;
- held supplier and slow persistence;
- independent mutation and receiver state;
- safe SDK reports;
- inspected Jaeger traces.

Evidence handling:

- Keep screenshots free of credentials.
- Browser HTTP Archive (HAR), trace and video recording are disabled for this
  lane.
- Retain failed artifacts with safe codes and counts. Label missing or failed
  required setup non-passing.
- Preserve the original M1 identity and prior phase closing artifacts during
  compatibility runs.

## Media invocation replay and readiness

### Invocation identity

- A media invocation has its own canonical UUID, separate from the accepted
  business request key and task identity.
- The browser freezes it across an unknown token or room acknowledgement.
- Explicit End or a completed native disconnect starts a new invocation on the
  next Connect, with a fresh room and participant. The same scoped task, case,
  original request and business replay key are preserved.
- Automatic transport reconnect and uncertain mint retries keep their current
  frozen room, participant and invocation.
- The API signs this UUID as the grant identity. It reuses an assigned job only
  for the same invocation.
- The default UI gives each ended invocation a new room. Direct attempts to reuse
  an old room for a different invocation remain fail-closed unless its prior jobs
  are observably terminal.
- An unassigned or unknown dispatch remains unresolved. It cannot be treated as
  ready or blindly replaced.

### Dispatch admission

Before a new dispatch, the local controller observes the private native SDK
health and worker status under the original four-second dispatch deadline.

- A stable idle observation spans the SDK status publication interval. It is
  consumed once for that admission. This avoids dropping a request into a worker
  still advertised as full after shutdown.
- The controller requires an actually assigned nonterminal job before minting
  credentials.
- These are bounded media-admission observations, not another durable business
  queue.
- Slow or unavailable capacity returns a fixed safe failure.
- Runtime and SDK health do not prove actual media. The browser still verifies a
  fresh native reply after reconnect.

### Retained room dispatch snapshots

The pinned self-hosted server retains room dispatch snapshots after worker job
completion.

- The demo therefore does not interpret an old room's running snapshot as a live
  consumer, or guess that a job is safe to delete.
- A new room for an explicitly new invocation makes the media boundary clear.
- Actual reconnect proof requires a fresh native status reply bound to the
  original durable case.

See the
[release-based source](https://github.com/livekit/livekit/blob/v1.13.11/pkg/service/agenthandler.go)
and the [composition decision](decisions/0007-native-conversation-and-local-media.md).

## Explicit provider-real profile

The trusted mode enum is scripted (default), local_real or provider_real.
provider_real is a separately selected profile, never an automatic fallback from
a failed local engine.

- provider_real uses livekit-plugins-deepgram, livekit-plugins-openai and
  livekit-plugins-elevenlabs, all pinned to 1.8.11 with Agents 1.8.11.
- The fixed pipeline is Deepgram nova-3 batch recognition on manual flush, OpenAI
  gpt-5.4-mini streaming Chat Completions with none reasoning and at most 128
  output tokens, and ElevenLabs eleven_v4_turbo chunked HTTP PCM speech.
- The [provider operations guide](provider-demo.md) owns explicit setup, check,
  start and stop, and the trusted provider P1-20 selector.
- Three private keys reach only the native process. Local model caches and
  engines are unnecessary.
- The selected provider_real v2 gate passed both actual browser cases with
  cleanup. P1 V1 is qualified for the local POC using provider_real v2.
- External provider CPU and memory are unobserved. No zero-retention or
  model-quality guarantee follows from local content-free telemetry.
- Default offline and scripted checks make no provider calls.
