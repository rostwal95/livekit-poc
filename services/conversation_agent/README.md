# Native conversation agent

| Field | Value |
| --- | --- |
| Status | Active |
| Purpose | Explain what the native conversation worker provides and how to configure, run and validate it |
| Audience | Engineers who run or change the conversation worker; coding agents |
| Scope | The `services/conversation_agent` worker and its three inference profiles; excludes the HTTP controller, browser workspace and durable authority |
| Owns | Conversation worker runtime behavior, configuration, commands and validation |
| Related | [Design](Design.md) · [Agent instructions](AGENTS.md) · [P1 charter](../../docs/projects/agent-continuity-scope.md) · [Phase G work item](../../docs/work-items/0013-p1-phase-g-conversation-and-showcase.md) · [Provider guide](../../docs/provider-demo.md) |

## Overview

This service is a separate LiveKit Agents consumer. It connects a real native
AgentSession to the P1 (agent continuity) durable investigation service. This
README is for engineers who run or change the conversation worker.
[Design.md](Design.md) explains its design, limits and failure handling.

The worker runs one of three trusted inference profiles:

| Profile | Behavior |
| --- | --- |
| `scripted` (default) | Declared speech-to-text (STT) and large language model (LLM) fixtures and prerecorded spoken pulse-code modulation (PCM) audio, without downloads or paid inference |
| `local_real` | Prepared local Whisper recognition, Qwen model/tool selection and generated Piper speech; actual engine, model and media qualification remains pending |
| `provider_real` | Deepgram, OpenAI and ElevenLabs; see [Optional provider profile](#optional-provider-profile) |

The authenticated workflow panel owns exact quote approval. The conversation
exposes investigation, inspection and explicit cancellation of its current owned
task.

### Terms

| Term | Meaning |
| --- | --- |
| P1 | Agent continuity |
| Phase G | The P1 conversation and showcase phase |
| P1 V1 | The fixed first-version P1 scope |
| POC | Proof of concept |
| STT, LLM, TTS | Speech-to-text, large language model and text-to-speech |
| PCM | Pulse-code modulation |
| RPC | Remote procedure call |
| PTT | Push-to-talk |
| ASR | Automatic speech recognition |
| OTLP | OpenTelemetry Protocol |
| OTEL | OpenTelemetry |

## Implementation status

| Capability | Status | Evidence |
| --- | --- | --- |
| Native conversation: AgentSession, Agent and three no-argument function tools | Implemented | Actual SDK text and manually committed audio tests |
| Media readiness: public RoomIO readiness barrier before greeting/controls; exact native ready attribute | Qualified | Gated-subscription regression plus actual browser gate |
| Scripted voice: default non-silent audio maps to declared investigate/status transcripts and fixed spoken replies | Qualified | Retained Phase G transport/lifecycle proof, not general inference |
| Provider inference: explicit trusted `provider_real` selects official Deepgram/OpenAI/ElevenLabs plugins with native-only keys | Qualified | Implementation and offline checks present; the selected `provider_real` v2 gate passed both actual browser cases with cleanup |
| Local real inference: explicit trusted `local_real` selects prepared Whisper/Qwen/Piper and bounded fixed private endpoints | Not qualified | Implementation present; actual engine/model/browser qualification pending |
| Trusted business adapter: signed room/participant grant, frozen principal/request/replay key, bounded storage offload | Implemented | Composition/service tests and the separate real PostgreSQL lane |
| Session independence: interruption/closure does not invoke cancellation; accepted work belongs to durable workers | Implemented | Native lifecycle tests; full stack recovery needs its own gate |
| Observations: numeric SDK usage/report files, finite JSON logs, sanitized bounded optional OpenTelemetry Protocol (OTLP) export | Implemented | Local protobuf receiver/outage tests; inspect collector traces separately |
| Browser demonstration: native push-to-talk (PTT) controls, transcription streams and authenticated refresh hints | Qualified | Actual browser run evidence is recorded in the [Phase G work item](../../docs/work-items/0013-p1-phase-g-conversation-and-showcase.md) |

P1 V1, the fixed first-version P1 scope, is qualified for the local POC (proof
of concept) using `provider_real` v2.

This is retained checkpoint evidence. The fresh P1-20 provider-media rerun after
the v5 upgrade remains open in the
[qualification guide](../../docs/qualification-gates.md); the qualified workload
version and the PostgreSQL schema version are separate identifiers.

### Function tools

Native function tools use the SDK's async-tool lifecycle:

1. An injected RunContext records a silent pending update before awaiting storage.
2. Speech can be interrupted while the SDK owns the pending tool. The bounded
   adapter retains its real thread and capacity meanwhile.
3. The final validated receipt produces the deferred result and refresh hint.

Pending is never narrated as accepted work, and PostgreSQL remains the durable
authority. No extra model task-cancellation or task-listing tools are exposed.

**Unknown submit acknowledgement.** A submit acknowledgement is unknown when the
waiter timed out while the protected write may still commit. A submit that local
capacity rejected before it started is treated the same way. After an unknown
submit, `get_case` and `cancel_case` first replay the frozen original submit with
the same idempotency key, then read or cancel that task. If the replay cannot
finish, the tool raises its fixed `ToolError` and the reply says the operation
could not be completed. It never says that nothing was accepted.

### Media readiness

1. After the SDK session starts, the runtime waits at most ten seconds for its
   public `RoomIO.wait_for_ready` barrier. This waits for the expected
   participant and the native output subscription. Microphone publication is not
   required.
2. Only then are controls enabled. `continuity.session_ready='true'` and the
   configured finite `continuity.inference_mode` are published together, and
   the greeting is queued.
3. The browser requires that mode to match its authenticated mint, plus an
   active SDK state.

Early control and text input is rejected. A startup failure or cancellation
stays visible and still receives independent cleanup. This ordering prevents an
interruption of an unsubscribed first output from cancelling the frozen SDK's
shared subscription wait and suppressing later speech and transcription.

### Session ingress

The SDK RemoteSession host is disabled through `session_host=False`. Only the
owned bounded `lk.chat` stream and three caller-checked remote procedure call
(RPC) routes can drive the session. The built-in `lk.agent.session` byte ingress
is not installed.

### Profile behavior

In the default `scripted` profile, the first qualified audio turn maps to
investigate and later turns map to status. Silent input produces no
investigation. Text commands use an explicit allowlist, and cancellation requires
the declared cancel command. These fixture assertions do not qualify human speech
or model quality.

`local_real` uses actual local recognition, model and generated speech with the
same three bound no-argument tools. A model cannot prepare or approve an exact
quote.

### Prerecorded browser input

The prerecorded input track is prepared and published silently. After the native
`start_turn` response is strictly verified as `turn_started`, a new non-looping
source plays the unchanged WAV from sample zero. Closed, muted, replaced,
superseded or not-ready input cannot be restarted by a late reply. Physical
microphone capture is independent. Fixture alignment does not force a model tool
or establish automatic speech recognition (ASR) quality.

## Documentation

| Document | Purpose |
| --- | --- |
| [AGENTS.md](AGENTS.md) | Coding rules for this service |
| [Design.md](Design.md) | Design, limits and failure handling |
| [Shared design](../../Design.md) | Ecosystem data flow and authority |
| [Local setup](../../local-setup/README.md) | Composed profile lifecycle, preparation and health checks |
| [Phase G work item](../../docs/work-items/0013-p1-phase-g-conversation-and-showcase.md) | Phase evidence, including actual browser runs |
| [Conversation guide](../../docs/conversation-and-showcase.md) | Business profile setup, consent and evidence |
| [Local-real operations guide](../../docs/local-real-inference.md) | Prepared local engine operations and qualification boundaries |
| [Provider operations guide](../../docs/provider-demo.md) | Provider profile setup |
| [Asset manifest](assets/manifest.json) | Synthetic audio fixtures |
| [P1 charter](../../docs/projects/agent-continuity-scope.md) | Scope and release criteria |

## Requirements

| Requirement | Version or value | Notes |
| --- | --- | --- |
| Python dependencies | Frozen root `local`, `agent` and `inference` extras | Installed by the root `make bootstrap` |
| Business profile inputs | LiveKit credentials, the PostgreSQL runtime role and schema, and the trusted scope | Supplied by the composed business profile |
| Native worker name | `local-business-agent` | Admits one job; diagnostic worker dispatch stays separate |
| Internal health and load surface | Port 8082 | Served by the native worker |
| Business state | Synthetic business state and existing authority | Installs no schema, initializes no consent and accepts no migration credentials |
| `local_real` inputs | The exact prepared cache and private engines | No implicit model download or fallback |
| `provider_real` inputs | The separately validated keys | No implicit model download or fallback |

Models and engines receive no application credentials, and their endpoints
publish no host ports.

### Settings

| Option | Default | Allowed values | Description |
| --- | --- | --- | --- |
| `P1_CONVERSATION_INFERENCE` | `scripted` | `scripted`, `local_real`, `provider_real` | Trusted inference profile; not a client or tool argument |
| `P1_TRACE_ENDPOINT` | Not set | A validated local OTLP endpoint | Optionally selects the trace export endpoint |

The inference mode is trusted configuration. The same worker name serves one
configured profile. The owned trace exporter ignores OpenTelemetry (OTEL)
credential and header environment settings, and proxy environment settings.

## Commands

| Task | Command | Notes |
| --- | --- | --- |
| Run the composed profile | [Local setup lifecycle](../../local-setup/README.md) | Preparation, health checks, start and stop |
| Start the worker process | `python -m services.conversation_agent start` | Installed container entry; run from the repository root in the prepared environment |

Use the [local setup lifecycle](../../local-setup/README.md) for the composed
profile, preparation, health checks, start and stop. The installed container
entry is:

```sh
python -m services.conversation_agent start
```

Run it from the repository root in the prepared environment. Credentials and
signed grants come from the managed profile and the HTTP controller.

### Optional provider profile

`provider_real` composes these official provider plugins:

| Stage | Provider | Model | Behavior |
| --- | --- | --- | --- |
| Recognition | Deepgram | `nova-3` | Batch recognition at manual flush |
| Model | OpenAI | `gpt-5.4-mini` | Streaming tool selection |
| Speech | ElevenLabs | `eleven_v4_turbo` | Chunked HTTP speech |

It preserves the same three no-argument tools, manual turns and exact separate
human confirmation. Only this native process receives the three private keys. It
requires no local model cache or engine and never silently substitutes profiles.
Read the [provider operations guide](../../docs/provider-demo.md) for setup. The
selected `provider_real` v2 gate passed both actual browser cases with cleanup.

## Validation

| Check | Command | What it proves | Status |
| --- | --- | --- | --- |
| Conversation tests | `.venv/bin/python -m unittest discover -s tests -p 'test_conversation*.py' -v` | Native SDK tools, audio, limits, cleanup and readiness fixtures | Required per change |
| Tracing tests | `.venv/bin/python -m unittest discover -s tests -p 'test_tracing.py' -v` | Local OTLP export, including timeout/outage and shutdown races | Required per change |
| Worker tracing tests | `.venv/bin/python -m unittest discover -s tests -p 'test_worker_tracing.py' -v` | Durable worker child traces | Required per change |
| Separate observations | Browser, worker and live-model lanes | Browser WebRTC playback, independent worker completion and live model quality | Required for affected changes |

From the repository root:

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_conversation*.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_tracing.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_worker_tracing.py' -v
```

What the tests cover:

- Real native SDK function execution, nonzero AudioInput frames, manual STT
  flush, silent rejection and native text-to-speech (TTS) emission.
- Caller, body and reader limits, cleanup ordering, spawn importability and safe
  errors.
- A controlled native output subscription fixture. It verifies that early
  controls fail before touching interruption, and that actual synchronized
  STATUS audio and text follow readiness. Timeout and cancellation fixtures
  cannot claim readiness.
- OTLP tests that bind a local receiver and decode actual protobuf, including
  timeout/outage and shutdown races.

Record browser WebRTC playback, independent worker completion and live model
quality as separate observations.

## Next milestone

| Step | Outcome | Gate |
| --- | --- | --- |
| Preserve the completed Phase G deterministic regression and the current Phase H2 reliability, installed host/Linux artifact and selected `provider_real` v2 media gates | The qualified local P1 V1 scope recorded in the [Phase H handoff](../../docs/work-items/0019-p1-phase-h-release-qualification.md) | Existing passed gates |
| Repeat affected gates after changes | Fresh evidence for the changed behavior | Affected gates |

| Open or out-of-scope item | Status |
| --- | --- |
| `local_real` | Not qualified; a distinct option that requires its own declared run |
| Physical quality, human acknowledgement and production capacity | Remain separate |
| All 17 P2 rows and the remaining 14 P3 rows | Planned, alongside three passing registered P3 lab rows |
| Hosted CI and publication | Outside this local POC scope |
