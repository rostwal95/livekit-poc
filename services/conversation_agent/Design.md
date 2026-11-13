# Native conversation agent design

Status: Active
Last reviewed: 10 November 2026

## Overview

This service is a native LiveKit Agents consumer of P1 durable work. A real
AgentSession runs Agent function tools against a trusted asynchronous business
port. Scripted is the default and makes SDK/RTC/lifecycle checks deterministic
without downloads or providers. The explicit local_real implementation uses prepared
Whisper/Qwen/Piper engines behind the same bounded ports; actual engine/model/media
qualification remains pending. Business authority remains in
the authenticated service and PostgreSQL; a room is not a workflow owner.

The profile contributes to P1-I22 through P1-I25 and P1-14/17/18/20. The
[P1 charter](../../docs/projects/agent-continuity-scope.md) owns acceptance criteria;
the [Phase G work item](../../docs/work-items/0013-p1-phase-g-conversation-and-showcase.md)
owns phase evidence and remaining release prerequisites.

## Objectives

| Kind | Objective | Observable result |
| --- | --- | --- |
| Business | Continue accepted investigation across session end | The durable task remains inspectable and independently executable |
| Business | Preserve explicit control of booking changes | Exact quote/revision approval comes only from the authenticated panel |
| Technical | Exercise the actual LiveKit SDK locally | Native audio/manual turns, tools, speech, interruption and report observations |
| Technical | Keep conversation responsive under slow storage/telemetry | Storage offload, finite work, owned cleanup and optional export |
| Technical | Keep portfolio claims reproducible | Synthetic fixtures and separate unit, SDK, database and browser evidence |

## Functional requirements

| Kind | Requirement | Implementation and acceptance surface |
| --- | --- | --- |
| Business | Accept only an already authorized investigation | Signed grant freezes request/principal/replay key; submit tool has no arguments |
| Business | Inspect/cancel only the current owned task | Trusted SessionBusinessPort binds task; no arbitrary model task identity |
| Business | Preserve exact confirmation authority | No model confirmation/signal tool; authenticated controller validates persisted quote/revision |
| Technical | Require verified controls | Caller-bound RPC accepts only schema_version 1 with no authority fields |
| Technical | Transport actual audio | Non-silent received PCM qualifies fixture STT; prerecorded speech traverses native TTS output |
| Technical | Provide honest visible progress | Native transcription/state plus UUID refresh hint; panel authenticates a fresh durable read |
| Technical | Close independently owned resources | Session, report/export observer and storage port each receive bounded cleanup |

## Non-functional requirements

| Requirement | Configured bound or behavior | Units | Verification | Status |
| --- | --- | --- | --- | --- |
| Admission | One assigned/pending job; serialized assignment | jobs/worker | Admission concurrency tests | Implemented |
| Recognition ownership | At most two active/closing stream handles; one active and one waiting ASR operation | handles/operations | Actual SDK turn-reset, third-handle rejection and cancelled-close regressions | Implemented; real-provider gate separate |
| Session lifetime | 180 maximum | seconds | Worker configuration/lifecycle | Configured; runtime gate separate |
| Media readiness | Public RoomIO barrier, at most 10; caller controls rejected before completion | seconds | Gated output subscription, timeout and cancellation regressions | Implemented |
| Control ingress | 128 bytes; 64 commands; exact versioned object | UTF-8 bytes/session calls | Positive/negative RPC tests | Implemented |
| Text ingress | 4 KiB; two readers; 3-second read budget; 32 turns | bytes/tasks/seconds/turns | Overflow, foreign caller and closure tests | Implemented |
| Tool work | 32 tool calls; 8 KiB finite JSON receipts | calls/bytes | Bounds and sanitized failure tests | Implemented |
| Audio ingress | 16 kHz mono PCM16; 12 seconds/turn, 190 seconds/session; 32 qualified turns | Hz/seconds/turns | Provider/native AudioInput tests | Implemented |
| Speech fixture bank | Seven declared output phrases; each at most 12 seconds | clips/seconds | WAV format/size/symlink tests | Implemented |
| Storage responsiveness | Blocking operations off media loop; seven-second adapter timeout | seconds | Adapter/offload tests | Implemented |
| Cleanup | Session 5, observer 2, port 5; server end 18/drain 20/process shutdown 20 | seconds | Cleanup ordering/failure tests and runtime gate | Implemented budgets |
| Telemetry | Queue 128; wire request 64 KiB; HTTP I/O timeout 0.5 | spans/bytes/seconds | Real receiver, saturation/outage tests | Implemented |
| Startup diagnostics | Six finite phase codes in the existing five-field schema; no readiness inferred from construction | events | Privacy/lifecycle tests and actual runtime failure evidence | Implemented |
| Numeric observation retention | At most 32 local files, each at most 4 KiB | files/bytes | Observer tests | Implemented |
| Privacy | No transcript/grant/secrets/full reports in application logs or exported spans | content policy | Sentinel fixtures and decoded protobuf | Implemented; native paths reviewed separately |

## Back-of-the-envelope calculations

These are configured sizing estimates, not measured throughput or latency claims.

| Input and formula | Result | Exclusions |
| --- | --- | --- |
| 16,000 samples/s × 2 bytes/sample × 1 channel | 32,000 PCM bytes/s | RTP/Opus, encryption and RTC buffers |
| 32,000 bytes/s × 12 s | 384,000 PCM bytes/maximum turn | Native framing and temporary objects |
| Two text readers × 4,096 payload bytes | 8,192 admitted text bytes | Native RTC transport buffers and Python objects |
| 128 queued spans × 65,536 maximum wire bytes | 8 MiB conservative wire-size envelope | Python object overhead; normal sanitized spans are smaller |
| 32 observation files × 4,096 bytes | 128 KiB numeric payload ceiling | Filesystem metadata |
| 5 s + 2 s + 5 s cleanup budgets | 12 s sequential application cleanup envelope | External process termination and pathological filesystem behavior |

The actual output WAV bank contains approximately 1.1 MB of PCM; exact per-asset
bytes, durations and hashes live in the [manifest](assets/manifest.json). One
conversation process is the initial capacity; the SDK memory warning/limit settings
are 192/256 MiB. Actual RSS, multi-worker scale and throughput need measured
benchmarks before a capacity claim.

## High-level design

```mermaid
flowchart LR
    UI[Authenticated workflow panel] --> API[Business HTTP controller]
    API --> PG[(Case and execution authority)]
    API --> GRANT[Signed session grant]
    GRANT --> CONV[Native conversation worker]
    UI <--> RTC[Self-hosted LiveKit]
    RTC <--> CONV
    MODE[Trusted scripted or local_real or provider_real] --> CONV
    FIXTURES[Local deterministic fixtures] <-->|scripted| CONV
    MODELS[Private Whisper Qwen Piper engines] <-->|local_real| CONV
    KEYS[Privately validated native-only keys] -->|provider_real| CONV
    CONV <-->|provider_real bounded HTTPS| PROVIDERS[Deepgram OpenAI ElevenLabs]
    CONV --> PORT[Bound business port]
    PORT --> OFFLOAD[Bounded storage offload]
    OFFLOAD --> PG
    WORKER[Independent durable worker] <--> PG
    WORKER --> SUPPLIER[Synthetic supplier and completion receiver]
    CONV -. refresh hint .-> UI
    CONV --> SAFE[Sanitized trace and numeric observer]
    SAFE --> OTLP[Optional local collector]
```

1. The HTTP controller authenticates the user and mints a short-lived signed
   room/participant binding from server authority.
2. LiveKit carries media, native transcription/state and bounded control messages.
   The worker verifies its grant before installing native tools.
3. The business port binds the original investigation and replay identity. Blocking
   storage calls execute through finite offload; PostgreSQL commits durable work.
4. Durable workers execute independently of the conversation. Exact confirmation
   uses the separate HTTP controller and persisted case authority.
5. Refresh hints request an authenticated read. Optional traces and numeric
   observations describe execution without becoming business authority.

## Sequence diagram

```mermaid
sequenceDiagram
    participant UI as Workflow panel
    participant API as Authenticated controller
    participant RTC as LiveKit room
    participant Agent as Native AgentSession
    participant Port as Bound business port
    participant DB as Durable authority
    participant Worker as Durable worker
    participant Inference as Selected inference adapters
    participant Providers as Optional external provider APIs
    UI->>API: Request investigation-bound session
    API->>DB: Validate principal and optional existing task
    API->>RTC: Mint participant token and named agent dispatch
    RTC->>Agent: Signed metadata job
    Agent->>Agent: Verify room, participant, scope, actor and expiry
    Agent->>Agent: Await public RoomIO readiness within ten seconds
    Agent-->>UI: Exact continuity.inference_mode plus session_ready and SDK state
    UI->>Agent: start_turn RPC from expected participant
    UI->>RTC: Non-silent audio frames
    RTC->>Agent: Native audio input
    UI->>Agent: commit_turn RPC
    Agent->>Inference: Explicit manual-flush recognition then bounded model turn
    alt scripted default
        Inference-->>Agent: Declared fixture transcript and tool selection
    else local_real
        Inference-->>Agent: Private Whisper and Qwen output
    else provider_real
        Inference->>Providers: Native-only credentials and bounded HTTPS recognition/model calls
        Providers-->>Inference: Deepgram final transcription and OpenAI stream
        Inference-->>Agent: Validated bounded model/tool chunks
    end
    Note over Agent,Providers: Model output grants no business or confirmation authority
    Agent->>Port: submit_investigation with no arguments
    Port->>DB: Authenticate and atomically accept frozen request/key
    DB-->>Port: Durable receipt
    Port-->>Agent: Minimal safe projection
    Agent->>Inference: Bounded synthesis for selected profile
    opt provider_real
        Inference->>Providers: ElevenLabs chunked HTTP PCM speech request
        Providers-->>Inference: Generated PCM frames
    end
    Inference-->>Agent: Scripted PCM or local Piper or provider-generated PCM
    Agent-->>UI: Actual audio, bounded transcription and nonauthoritative refresh hint
    UI->>API: Authenticated current projection read
    UI->>RTC: End session
    Agent->>Agent: Close media, observer and port
    Worker->>DB: Claim and continue durable investigation
    UI->>API: Separate exact quote/revision confirmation
    API->>DB: Validate and commit intent atomically
    Worker->>DB: Execute permitted step and persist outcome/delivery
    UI->>API: Reauthenticate and resume same owned task
```

## Low-level design

```mermaid
classDiagram
    class ConversationRuntime {
        +start(room)
        +aclose()
    }
    class ConversationControls {
        +start_turn(data)
        +commit_turn(data)
        +interrupt(data)
        +on_text(reader, identity)
        +aclose()
    }
    class DurableAgent {
        +submit_investigation()
        +get_case()
        +cancel_case()
    }
    class BusinessPort {
        <<interface>>
        +submit_investigation()
        +get_case()
        +cancel_case()
        +aclose()
    }
    class SessionBusinessPort
    class AgentSession
    class ScriptedSTT
    class ScriptedLLM
    class ScriptedTTS
    class LocalConversationRuntime
    class ProviderConversationRuntime
    class LocalSTT
    class LocalLLM
    class LocalTTS
    class ProviderSTT
    class BoundedLLM
    class ProviderTTS
    class SessionObserver
    ConversationRuntime *-- AgentSession
    ConversationRuntime *-- ConversationControls
    AgentSession --> DurableAgent
    AgentSession --> ScriptedSTT
    AgentSession --> ScriptedLLM
    AgentSession --> ScriptedTTS
    DurableAgent --> BusinessPort
    SessionBusinessPort ..|> BusinessPort
    ConversationRuntime <|-- LocalConversationRuntime
    LocalConversationRuntime <|-- ProviderConversationRuntime
    LocalConversationRuntime --> LocalSTT : selected local profile
    LocalConversationRuntime --> LocalLLM
    LocalConversationRuntime --> LocalTTS
    ProviderConversationRuntime --> ProviderSTT : selected provider profile
    ProviderConversationRuntime --> BoundedLLM
    ProviderConversationRuntime --> ProviderTTS
    SessionObserver --> AgentSession
```

## Components and related details

### Implementation and authority

| Component | Responsibility | Authority boundary |
| --- | --- | --- |
| worker.py | Native dispatch/admission, prewarm, room connection and cleanup | Verifies composition before media; owns one bounded session |
| scripted.py | SDK provider extensions and validated PCM bank | Fixed fixture mapping; no remote inference or new consent |
| session.py | Native Agent/AgentSession, tools and bounded RTC controls | Tools have no model scope/task/confirmation arguments |
| composition.py | Signed grant verification and asynchronous service binding | Server principal, frozen request/key and current owned task |
| observations.py | Numeric usage/report extraction and finite local files | No full report serialization; exporter never owns business state |
| telemetry.py | Fixed JSON application/SDK log boundary | Exception bodies, metadata and transcript text excluded |
| projects/agent-continuity/python/src/continuity_lab/tracing.py | Private provider, sanitized copies and finite HTTP export | Explicit local endpoint, no environment auth/proxy hooks |

### Interfaces and identity

BusinessPort exposes async submit_investigation/get_case/cancel_case/aclose.
The three native tools additionally receive an SDK-injected RunContext; it is
hidden from model arguments and carries no model-selected business scope. Each
uses ctx.update with a fixed pending receipt and silent=True before awaiting its
port operation. This releases the current speech turn while the SDK owns the
ongoing tool/deferred result. ToolFlag.NONE preserves the three-tool schema and
avoids adding model-visible task cancellation/listing capabilities. A pending
update is not acceptance and cannot trigger an acceptance hint or spoken receipt.

A verified ConversationBinding fixes the expected browser-/smoke- participant.
Room metadata is a signed server grant, not participant-editable identity.
The browser sends only schema_version 1 to business.start_turn,
business.commit_turn and business.interrupt. Replies use turn_started,
turn_committed/no_audio and speech_interrupted respectively.

The runtime sets the public session_host=False option. This disables the SDK
RemoteSession transport and its lk.agent.session byte handler, which otherwise
provides a separate input/interrupt path outside the owned caller/readiness checks.
Native tools and the owned bounded lk.chat/three-RPC interface remain available.
The native SDK regression includes a default-host positive control and verifies
that this profile never registers the alternate byte ingress.

AgentSession.start can publish listening before its RoomIO setup is complete.
The runtime therefore awaits the public session.room_io.wait_for_ready() with a
ten-second deadline, disables input, marks the owned controls ready, and publishes
the exact continuity.session_ready='true' participant attribute before greeting.
The UI combines that attribute with the selected agent's active SDK state. The
barrier requires the expected participant and audio output subscription, not an
input microphone. RPC and text handlers reject premature requests before calling
session.interrupt or generating a reply. In the frozen SDK, interrupting a first
capture while its subscription wait is pending can cancel a shared audio-output
future; later TTS generation then produces no synchronized output. The readiness
precondition avoids that path through public APIs without patching SDK internals.

Native lk.chat input is read by the owned bounded stream handler. Native
lk.transcription output and lk.agent.state attributes describe the conversation.
The continuity.observed data hint carries only schema_version and a canonical
task UUID to the expected participant. The UI verifies a fresh authenticated
projection before applying state. Reconnect binds the same durable request/key
or an authorized existing task; a lost acknowledgement never generates a new
business identity automatically.

### Lifecycle and retention

A readiness timeout or cancellation never publishes a successful ready attribute
or queues startup speech. The worker retains ownership of SDK, observer and port
cleanup after failed startup. Controls close synchronously before reader/session
cleanup awaits, so an ended runtime cannot regain readiness.

The SDK prewarm loads finite spoken assets; model preloading stays disabled.
Manual turn handling uses vad=None. Non-silent PCM qualifies the first fixed
investigate transcript, subsequent qualified turns produce status, and silent
turns do not advance the script. The exact text allowlist additionally permits
cancel this investigation. Native speech interruption and session end never call
cancel_case.

SDK async tools remain bounded by the 32-call session budget and the port's
seven-second operation deadline. The bounded offload keeps its real thread and
slot until completion even if a caller or speech turn stops waiting. Session
cleanup drains SDK-owned tasks independently from storage cleanup; a timed-out
cleanup remains visibly incomplete. The final validated receipt alone enters the
SDK deferred-result path. Speech interruption does not cancel a business task.

Accepted workflow state remains in PostgreSQL and external synthetic receipts.
This service adds no storage schema or business migration. Numeric observer files
are a disposable local diagnostic projection with finite retention. Normal stack
stop preserves durable volumes; explicit reset follows the local setup guide.

### Explicit local real-inference profile

P1_CONVERSATION_INFERENCE is validated as scripted, local_real or provider_real; one configured
process keeps the same local-business-agent name. Native readiness publishes its
mode with continuity.session_ready only after actual RoomIO readiness. The API
mint and selected native participant must agree before browser controls become usable.

Local speech providers own finite HTTP operations and fixed private endpoints.
Whisper receives at most 12 s mono16 kHz PCM; Piper returns at most 20 s mono22050 Hz
PCM. STT/TTS native calls each have 10 s around 8 s child work; LLM is 30 s with 128 output
tokens, 256 chunks, 4 KiB output and 64 KiB context. One active/one waiting operation
per provider prevents unbounded pressure. Models are explicitly prepared and
mounted read-only; runtime never downloads or uses a remote provider fallback.

The same three bound no-argument tools, exact separate controller consent, native
SessionHost exclusion, storage offload and independent cleanup remain. Fixed safe
error codes and finite usage/traces identify the actual configured mode without
retaining transcripts/prompts. The [operations guide](../../docs/local-real-inference.md)
owns model pins, licenses, commands and remaining qualification. Default-scripted
diagrams and Phase G measurements do not establish real-model behavior.

### Trusted provider composition

The shared/native path accepts exactly scripted (default), local_real and
provider_real. The diagrams retain the shared authority path; profile adapters use the same session and bound task rather than creating another
case authority. provider_real composes Deepgram nova-3 batch recognition after
manual flush, OpenAI gpt-5.4-mini streaming tool selection and ElevenLabs
eleven_v4_turbo chunked HTTP PCM speech. Only the native process receives provider
keys, and real output cannot bypass separate exact human consent.

The SDK clears a manual turn by replacing its recognition pipeline while the old
pipeline closes asynchronously. ProviderSTT owns at most two stream handles for
that transition, rejecting a third. Each remains owned until full SDK aclose
succeeds; natural run completion or cancelled close does not release ownership.
The shared HTTP pool still admits one active and one waiting ASR operation under
the original deadline and audio/session caps. These handle and operation counts
are different bounds. Actual AgentSession reset/capture/commit and shutdown tests
cover this lifecycle without provider calls.

The [provider operations guide](../../docs/provider-demo.md) owns strict key setup, explicit lifecycle,
fixed model/voice/transports, bounded execution and the fresh P1-20 selector.
Real profiles keep 12-second commit and 40-second incoming-transcription limits;
other RPCs remain 8 seconds and browser cleanup 5 seconds. No silent fallback,
provider resource-capacity result or blanket zero-retention claim is made.
The selected provider_real v2 gate passed both actual browser cases with cleanup. P1 V1 is qualified for the local POC using provider_real v2.

The prerecorded input track is prepared and published silently. After the native
start_turn response is strictly verified as turn_started, a new non-looping source
plays the unchanged WAV from sample zero. Closed, muted, replaced, superseded or
not-ready input cannot be restarted by a late reply. Physical microphone capture
is independent; fixture alignment does not force a model tool or establish ASR quality.
A passing provider scenario cannot qualify the separate local-engine declaration.

## Security and privacy

The server validates HMAC grant signatures, room/expected participant, configured
scope/actor and finite expiry before constructing the port. Model/tool schemas
cannot supply an actor, task, request key, confirmation or storage credential.
Cancellation targets only the current owned task. Investigation consent and exact
quote confirmation remain distinct even when the agent speaks an apparent approval.

Application and dedicated native SDK log formatting keeps only fixed finite
metadata. Optional export strips raw attributes, events, links, status descriptions,
resource labels and trace-state content into a new span while retaining ancestry.
The original SDK span is unchanged. The local exporter does not honor OTEL header,
credential provider or proxy environment hooks, does not follow redirects, and
closes responses after status inspection without reading their body. Audio and
transcript recording are disabled; trace recording is enabled with SDK redaction.
Review SDK recording behavior separately from the application's exported-field
allowlist. See the shared [observability policy](../../docs/observability.md).

## Observability

Fixed JSON events distinguish admission rejection, session start/end, invalid
input, hint failure, application failure and incomplete cleanup. Raw dependency
errors never become application messages. Export uses one private provider and a
bounded worker queue. Saturation drops diagnostic observations; collector outage
cannot change an accepted business result.

After native session closure, the observer extracts finite numeric usage/report
fields, closes the exporter off the media loop and writes a small private local
file. SDK report failure remains a failure observation. Collector readiness alone
is insufficient; the phase gate must inspect actual stored SDK/application spans.

## Metrics

| Producer | Observations | Interpretation |
| --- | --- | --- |
| Native session usage | Input/output tokens, STT/TTS audio seconds, TTS characters | Scripted fixture accounting stays separate from actual real-profile usage; counts alone establish no model quality or business outcome |
| Session report projection | Report event count, duration and observation flag | Numeric report evidence; no full history or room/participant IDs |
| Trace processor | Exported, dropped and failed counts | HTTP export observations; no guarantee of collector ingestion |
| Durable worker | Existing claims, steps, duration, active children and lease rejections | Process lifecycle; supplier outcome remains persisted authority |
| Scripted providers | Received/non-silent audio seconds, qualified turns and emitted frames | Native transport/progress assertions, separate from browser playback |

High-cardinality task/effect UUIDs are permitted only in sanitized traces, not
metric labels. Model names and operation labels use fixed allowlists. See the
shared metrics policy for service-wide signals and operational follow-up.

## Exception handling

Invalid grants/configuration fail before tools are installed. Invalid callers,
oversized bodies and state conflicts receive fixed RPC errors. Native tools map
ordinary adapter failures to a fixed ToolError without exception text/chains;
cancellation propagates. Optional refresh hints fail independently of accepted work.

Worker cleanup attempts native session close, observer/report/export close and
business port close independently. It preserves an existing application failure
and reports incomplete cleanup when a resource cannot finish. Interruption and
disconnect are media lifecycle transitions, not business cancellation. Unknown
acknowledgements retain the original replay identity and require an authoritative
read or replay.

## Design considerations and trade-offs

| Choice | Benefit | Cost or remaining boundary |
| --- | --- | --- |
| Scripted local providers with real SDK execution | Repeatable RTC/tool/lifecycle verification without a paid dependency | No general STT, model quality or free-form agent claim |
| Manual push-to-talk and no VAD model | Explicit turns, no inference download and deterministic tests | Additional UI controls; real conversational turn detection is a later profile |
| Separate durable workers | Accepted work survives session lifetime | Requires prepared PostgreSQL authority and independent runtime operations |
| No-argument bound tools | Scope/request/replay authority cannot come from a model | A new business request needs a new authenticated server binding |
| Authenticated exact approval in panel | Preserves canonical quote/revision validation | Spoken confirmation alone cannot advance mutation |
| Safe copies and bounded optional OTLP | Privacy, finite retention and outage isolation | Deliberately reduced debugging detail; HTTP success needs collector inspection |
| One job per native worker | Simple admission/cleanup and reproducible local capacity | Scaling requires additional workers and measured resource qualification |

Pinned release APIs are qualified against installed livekit-agents 1.8.11.
Current official [session](https://docs.livekit.io/agents/logic/sessions/),
[turn handling](https://docs.livekit.io/agents/logic/turns/),
[async tools](https://docs.livekit.io/agents/logic/tools/async/) and
[observability](https://docs.livekit.io/testing/observability/data/) documentation
provides context; a dependency promotion must rerun native provider/room tests.

## Validation and acceptance gates

| Gate | Sufficient evidence | Limits and prerequisites |
| --- | --- | --- |
| Native SDK | Actual AgentSession tool runs, manual real AudioInput, silent negative, real TTS AudioEmitter, interruption/closure and spawn tests | Frozen agent/local extras; no external provider |
| Trusted adapter | Grant tamper/expiry/scope/caller rejection, current-task-only operations, safe errors and independent cleanup | Real PostgreSQL acceptance/replay is a separate lane |
| Telemetry | Decode real loopback OTLP protobuf; inspect safe fields, env-header exclusion, delayed response/outage, bounded queue and shutdown races | Local receiver binding required; no collector ingestion claim from HTTP alone |
| Browser | Real WebRTC input/output samples, native transcription, interruption, session end and authorized reconnect | Controlled browser/media fixture; human microphone and hearing remain separate |
| Durable continuity | Independent worker progress, scoped projection, exact approval, supplier/outcome/delivery evidence under held dependencies | Prepared v4 schema/runtime roles and synthetic supplier/receiver |
| Compatibility and full phase | Full fast/type/style/docs, original diagnostic/M1, PostgreSQL and previous recovery lanes | Missing, skipped or timed-out required scenarios remain non-passing |

Run the focused commands in [AGENTS.md](AGENTS.md), then the authoritative phase
and shared gates. Record exact observed results in the work item. A local scripted
pass does not complete all V1 product scenarios, supported-platform qualification,
benchmarking, isolated package release or real-model evaluation.

The SDK inserts a cache-boundary control marker before voice LLM generation.
The bounded adapter admits only its exact canonical type alongside plain text;
media, arbitrary controls and subclasses remain rejected. The marker remains
inside serialized context limits and is handled by the pinned provider formatter.
Actual AgentSession reset/capture/commit tests verify this path against the old
pre-provider rejection, with mocked wire, positive PCM/usage and owned cleanup.
